from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from sqlalchemy import delete, select
from app.database import SessionLocal
from app.models import AccurateDatabase, GLAccount, Department, Project, JournalHeader, JournalLine, SyncJob, User
from app.services.accurate_client import client_for_database


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    value = str(value).strip()
    candidates = [value, value[:19], value[:10]]
    for candidate in candidates:
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(candidate, fmt)
            except ValueError:
                continue
    return datetime.utcnow()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in {"1", "true", "yes"}


def _text(v) -> str:
    return "" if v is None else str(v).strip()


def _decimal(v) -> Decimal:
    try:
        return Decimal(str(v or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _upsert_account(db, database_id: int, row: dict):
    no = _text(row.get("no") or row.get("accountNo"))
    if not no:
        return
    obj = db.scalar(select(GLAccount).where(GLAccount.database_id == database_id, GLAccount.account_no == no))
    if not obj:
        obj = GLAccount(database_id=database_id, account_no=no)
        db.add(obj)
    obj.accurate_id = row.get("id")
    obj.name = _text(row.get("name") or row.get("accountName"))
    obj.account_type = _text(row.get("accountType")).upper().replace(" ", "_")
    obj.parent_no = _text(row.get("parentNo"))
    obj.suspended = _bool(row.get("suspended"))


def _upsert_department(db, database_id: int, row: dict):
    rid = row.get("id")
    if rid is None:
        return
    obj = db.scalar(select(Department).where(Department.database_id == database_id, Department.accurate_id == int(rid)))
    if not obj:
        obj = Department(database_id=database_id, accurate_id=int(rid))
        db.add(obj)
    obj.name = _text(row.get("name"))
    obj.description = _text(row.get("description"))
    obj.suspended = _bool(row.get("suspended"))


def _upsert_project(db, database_id: int, row: dict):
    no = _text(row.get("no") or row.get("id"))
    if not no:
        return
    obj = db.scalar(select(Project).where(Project.database_id == database_id, Project.project_no == no))
    if not obj:
        obj = Project(database_id=database_id, project_no=no)
        db.add(obj)
    obj.accurate_id = row.get("id")
    obj.name = _text(row.get("name"))
    obj.description = _text(row.get("description"))
    obj.suspended = _bool(row.get("suspended"))


def _detail_object(response: dict) -> dict:
    """Return the journal header/detail object across small AOL response-shape variations."""
    if not isinstance(response, dict):
        return {}
    payload = response.get("d", response)
    # Some wrappers return d:[{...}] or d:{data:{...}}.
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if isinstance(payload, dict):
        for key in ("data", "result", "journalVoucher", "journal"):
            nested = payload.get(key)
            if isinstance(nested, dict) and (nested.get("id") or nested.get("detailJournalVoucher") or nested.get("number")):
                payload = nested
                break
    return payload if isinstance(payload, dict) else {}


def _looks_like_journal_line(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = {str(k).lower() for k in obj.keys()}
    return ("accountno" in keys or "glaccountno" in keys or "account" in keys) and ("amount" in keys or "debit" in keys or "credit" in keys)


def _extract_journal_lines(detail: dict) -> list[dict]:
    """Find journal detail lines recursively, preferring documented field names.

    AOL documents detailJournalVoucher[], but this defensive reader also accepts
    wrappers and minor naming differences so a successful API response does not
    silently become zero local rows.
    """
    if not isinstance(detail, dict):
        return []
    preferred = (
        "detailJournalVoucher", "detailJournalVoucherList", "details",
        "detail", "journalDetails", "journalVoucherDetails",
    )
    for key in preferred:
        value = detail.get(key)
        if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
            if any(_looks_like_journal_line(x) for x in value):
                return value
        if isinstance(value, dict):
            # Some serializers wrap lists as {d:[...]}, {data:[...]}, etc.
            for nested_key in ("d", "data", "rows", "list", "items"):
                nested = value.get(nested_key)
                if isinstance(nested, list) and any(isinstance(x, dict) and _looks_like_journal_line(x) for x in nested):
                    return nested

    found: list[dict] = []
    def walk(value):
        if isinstance(value, dict):
            if _looks_like_journal_line(value):
                found.append(value)
                return
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(detail)
    # De-duplicate by object identity/content-ish key.
    out=[]; seen=set()
    for i,line in enumerate(found):
        key=(line.get("id"), line.get("accountNo") or line.get("glAccountNo"), line.get("amount"), line.get("amountType"), i if line.get("id") is None else 0)
        if key in seen: continue
        seen.add(key); out.append(line)
    return out


def _line_account_no(line: dict) -> str:
    value = line.get("accountNo") or line.get("glAccountNo") or line.get("account") or ""
    if isinstance(value, dict):
        value = value.get("no") or value.get("accountNo") or ""
    return _text(value)


def _line_department(line: dict) -> str:
    value = line.get("departmentName") or line.get("department") or ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("description") or ""
    return _text(value)


def _line_project(line: dict) -> str:
    value = line.get("projectNo") or line.get("projectNumber") or line.get("project") or ""
    if isinstance(value, dict):
        value = value.get("no") or value.get("projectNo") or value.get("name") or ""
    return _text(value)


def sync_masters(db, dbrow: AccurateDatabase, client, job: SyncJob | None = None):
    if job:
        job.message = "Sync akun perkiraan..."; job.progress = 5; db.commit()
    account_rows = list(client.paged_list("glaccount", fields="id,no,name,accountType,parentNo,suspended", page_size=100, extra={"filter.leafOnly": "false"}))
    for row in account_rows: _upsert_account(db, dbrow.id, row)
    db.commit()

    if job:
        job.message = "Sync departemen..."; job.progress = 12; db.commit()
    department_rows = list(client.paged_list("department", fields="id,name,description,suspended", page_size=100))
    for row in department_rows: _upsert_department(db, dbrow.id, row)
    db.commit()

    if job:
        job.message = "Sync project..."; job.progress = 18; db.commit()
    project_rows = list(client.paged_list("project", fields="id,no,name,description,suspended", page_size=100))
    for row in project_rows: _upsert_project(db, dbrow.id, row)
    db.commit()
    return len(account_rows), len(department_rows), len(project_rows)


def sync_all_journals(db, dbrow: AccurateDatabase, client, job: SyncJob | None = None, progress_start: int = 22, progress_end: int = 96):
    """Reload every journal returned by /api/journal-voucher/list.do and detail.do."""
    if job:
        job.message = "Load All Jurnal: membaca daftar Journal Voucher..."; job.progress = progress_start; db.commit()

    # Use conservative fields documented for list. Detail.do supplies the rest.
    headers = list(client.paged_list("journal-voucher", fields="id,number,transDate,description", page_size=100))
    total = max(len(headers), 1)
    total_lines = 0
    with_department = 0
    with_project = 0
    zero_detail_headers = 0

    for idx, h in enumerate(headers, start=1):
        raw_id = h.get("id")
        if raw_id in (None, ""):
            continue
        hid = int(raw_id)
        detail_resp = client.api_get("journal-voucher", "detail", {"id": hid})
        detail = _detail_object(detail_resp)

        header = db.scalar(select(JournalHeader).where(JournalHeader.database_id == dbrow.id, JournalHeader.accurate_id == hid))
        if not header:
            header = JournalHeader(database_id=dbrow.id, accurate_id=hid, trans_date=_dt(detail.get("transDate") or h.get("transDate")))
            db.add(header)
        header.number = _text(detail.get("number") or h.get("number"))
        header.trans_date = _dt(detail.get("transDate") or h.get("transDate"))
        header.description = _text(detail.get("description") or h.get("description"))
        header.branch_name = _text(detail.get("branchName") or h.get("branchName"))
        header.last_update = _text(detail.get("lastUpdate") or h.get("lastUpdate"))
        db.flush()

        db.execute(delete(JournalLine).where(JournalLine.database_id == dbrow.id, JournalLine.journal_accurate_id == hid))
        lines = _extract_journal_lines(detail)
        if not lines:
            zero_detail_headers += 1
        for line_index, line in enumerate(lines, start=1):
            amount = abs(_decimal(line.get("amount") if line.get("amount") is not None else (line.get("debit") or line.get("credit") or 0)))
            amount_type = _text(line.get("amountType")).upper()
            if not amount_type:
                # Fallback for response variations that expose debit/credit separately.
                if _decimal(line.get("debit")) != 0:
                    amount_type = "DEBIT"; amount = abs(_decimal(line.get("debit")))
                elif _decimal(line.get("credit")) != 0:
                    amount_type = "CREDIT"; amount = abs(_decimal(line.get("credit")))
                elif _decimal(line.get("amount")) < 0:
                    amount_type = "CREDIT"
                else:
                    amount_type = "DEBIT"
            debit = amount if amount_type == "DEBIT" else Decimal("0")
            credit = amount if amount_type == "CREDIT" else Decimal("0")
            try:
                line_id = int(line.get("id") or line_index)
            except Exception:
                line_id = line_index
            dept = _line_department(line)
            project = _line_project(line)
            account_no = _line_account_no(line)
            db.add(JournalLine(
                database_id=dbrow.id,
                journal_accurate_id=hid,
                line_accurate_id=line_id,
                account_no=account_no,
                amount=amount,
                amount_type=amount_type,
                debit=debit,
                credit=credit,
                department_name=dept,
                project_no=project,
                memo=_text(line.get("memo") or line.get("description")),
            ))
            total_lines += 1
            if dept: with_department += 1
            if project: with_project += 1

        if idx % 10 == 0:
            db.commit()
        if job:
            span=max(progress_end-progress_start,1)
            job.progress = min(progress_start + int((idx / total) * span), progress_end)
            job.message = f"Load All Jurnal {idx:,}/{len(headers):,} • detail lines {total_lines:,}"
            db.commit()

    db.commit()
    return {
        "headers": len(headers), "lines": total_lines,
        "with_department": with_department, "with_project": with_project,
        "zero_detail_headers": zero_detail_headers,
    }


def _prepare_job(db, job_id: int):
    job = db.get(SyncJob, job_id)
    if not job:
        return None, None, None, None
    job.status = "RUNNING"; job.started_at = datetime.utcnow(); job.progress = 2; job.message = "Membuka koneksi Accurate Online..."; db.commit()
    dbrow = db.get(AccurateDatabase, job.database_id)
    user = db.get(User, job.user_id)
    if not dbrow or not user or not user.oauth:
        raise RuntimeError("Database atau OAuth credential tidak tersedia")
    client = client_for_database(dbrow, user.oauth, db)
    return job, dbrow, user, client


def run_full_sync(job_id: int):
    db = SessionLocal()
    try:
        job, dbrow, user, client = _prepare_job(db, job_id)
        if not job: return
        acc_n, dept_n, proj_n = sync_masters(db, dbrow, client, job)
        stats = sync_all_journals(db, dbrow, client, job, 22, 96)
        dbrow.last_sync_at = datetime.utcnow()
        job.progress = 100; job.status = "DONE"; job.finished_at = datetime.utcnow()
        job.message = (
            f"Sync selesai • {acc_n} akun • {dept_n} departemen • {proj_n} project • "
            f"{stats['headers']} jurnal • {stats['lines']} detail GL • Dept {stats['with_department']} • Project {stats['with_project']}"
        )
        if stats["headers"] and not stats["lines"]:
            job.message += " • WARNING: header jurnal ada tetapi detail GL 0; buka menu Load All Jurnal untuk diagnosis."
        db.commit()
    except Exception as exc:
        db.rollback(); job = db.get(SyncJob, job_id)
        if job:
            job.status = "FAILED"; job.message = f"{type(exc).__name__}: {exc}"; job.finished_at = datetime.utcnow(); db.commit()
    finally:
        db.close()


def run_journal_sync(job_id: int):
    """Journal-only reload used by the Load All Jurnal diagnostic page."""
    db = SessionLocal()
    try:
        job, dbrow, user, client = _prepare_job(db, job_id)
        if not job: return
        # Refresh accounts too, because a report cannot classify a journal line without account type.
        job.message = "Refresh GL Account sebelum Load All Jurnal..."; job.progress = 5; db.commit()
        account_rows = list(client.paged_list("glaccount", fields="id,no,name,accountType,parentNo,suspended", page_size=100, extra={"filter.leafOnly": "false"}))
        for row in account_rows: _upsert_account(db, dbrow.id, row)
        db.commit()
        stats = sync_all_journals(db, dbrow, client, job, 10, 96)
        dbrow.last_sync_at = datetime.utcnow()
        job.progress = 100; job.status = "DONE"; job.finished_at = datetime.utcnow()
        job.message = (
            f"Load All Jurnal selesai • {stats['headers']} header • {stats['lines']} baris GL • "
            f"Dept terisi {stats['with_department']} • Project terisi {stats['with_project']} • "
            f"Header tanpa detail {stats['zero_detail_headers']}"
        )
        db.commit()
    except Exception as exc:
        db.rollback(); job = db.get(SyncJob, job_id)
        if job:
            job.status = "FAILED"; job.message = f"{type(exc).__name__}: {exc}"; job.finished_at = datetime.utcnow(); db.commit()
    finally:
        db.close()
