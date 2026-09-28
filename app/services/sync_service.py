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


def _ci_get(obj: dict, *names, default=None):
    """Case-insensitive dictionary getter used for AOL response variations."""
    if not isinstance(obj, dict):
        return default
    lookup = {str(k).lower(): v for k, v in obj.items()}
    for name in names:
        key = str(name).lower()
        if key in lookup:
            return lookup[key]
    return default


def _detail_object(response) -> dict:
    """Return the most likely journal object from an AOL detail response."""
    if isinstance(response, str):
        import json
        try:
            response = json.loads(response)
        except Exception:
            return {}
    if not isinstance(response, dict):
        return {}
    payload = _ci_get(response, "d", default=response)
    if isinstance(payload, list):
        # Some wrappers return d:[{...}]. Prefer the first dict that resembles a journal.
        choices = [x for x in payload if isinstance(x, dict)]
        payload = choices[0] if choices else {}
    if isinstance(payload, dict):
        for key in ("data", "result", "journalVoucher", "journal", "value", "record"):
            nested = _ci_get(payload, key)
            if isinstance(nested, dict):
                nkeys = {str(k).lower() for k in nested.keys()}
                if {"id", "number", "detailjournalvoucher", "details"} & nkeys:
                    payload = nested
                    break
    return payload if isinstance(payload, dict) else {}


def _looks_like_journal_line(obj: dict) -> bool:
    if not isinstance(obj, dict):
        return False
    keys = {str(k).lower() for k in obj.keys()}
    accountish = any(k in keys for k in (
        "accountno", "glaccountno", "account", "glaccount", "accountid", "accountnumber"
    ))
    amountish = any(k in keys for k in (
        "amount", "debit", "credit", "debitamount", "creditamount", "primeamount", "baseamount"
    )) or any("amount" in k for k in keys)
    return accountish and amountish


def _as_dict_list(value) -> list[dict]:
    """Convert common list/wrapper/indexed-dict shapes into a list of dicts."""
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, tuple):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        # Typical wrappers: {data:[...]}, {rows:[...]}, {0:{...},1:{...}}
        for key in ("d", "data", "rows", "list", "items", "content", "details", "detail"):
            nested = _ci_get(value, key)
            rows = _as_dict_list(nested) if nested is not value else []
            if rows:
                return rows
        dict_values = [v for v in value.values() if isinstance(v, dict)]
        if dict_values and all(_looks_like_journal_line(v) for v in dict_values):
            return dict_values
    return []


def _extract_journal_lines(detail) -> list[dict]:
    """Recursively find Journal Voucher detail rows in AOL JSON.

    The public docs name the request-side array `detailJournalVoucher[n]`.  AOL
    deployments can serialize response wrappers differently, so this reader is
    intentionally tolerant while still requiring both an account and an amount.
    """
    if not isinstance(detail, (dict, list)):
        return []

    preferred_names = {
        "detailjournalvoucher", "detailjournalvoucherlist", "details", "detail",
        "journaldetails", "journalvoucherdetails", "detailtrans", "detailtransaction",
        "journalentries", "entries", "lines", "journallines",
    }
    candidates: list[dict] = []

    def walk(value, parent_key=""):
        if isinstance(value, dict):
            if _looks_like_journal_line(value):
                candidates.append(value)
                return
            for k, child in value.items():
                lk = str(k).lower()
                if lk in preferred_names or "detailjournal" in lk or "journalline" in lk:
                    rows = _as_dict_list(child)
                    for row in rows:
                        if _looks_like_journal_line(row):
                            candidates.append(row)
                    # Continue walking too, because wrappers may be one level deeper.
                walk(child, lk)
        elif isinstance(value, list):
            for child in value:
                walk(child, parent_key)

    walk(detail)
    import json
    out=[]; seen=set()
    for line in candidates:
        lid=_ci_get(line,"id","detailId","lineId")
        if lid not in (None, ""):
            key=("id", str(lid))
        else:
            try:
                key=("json", json.dumps(line, sort_keys=True, ensure_ascii=False, default=str))
            except Exception:
                key=("repr", repr(line))
        if key in seen:
            continue
        seen.add(key); out.append(line)
    return out


def _line_account_no(line: dict) -> str:
    value = _ci_get(line, "accountNo", "glAccountNo", "accountNumber", "account", "glAccount", default="")
    if isinstance(value, dict):
        value = _ci_get(value, "no", "accountNo", "number", "code", default="")
    return _text(value)


def _line_department(line: dict) -> str:
    value = _ci_get(line, "departmentName", "department", "departmentNo", default="")
    if isinstance(value, dict):
        value = _ci_get(value, "name", "description", "no", "code", default="")
    return _text(value)


def _line_project(line: dict) -> str:
    value = _ci_get(line, "projectNo", "projectNumber", "projectName", "project", default="")
    if isinstance(value, dict):
        value = _ci_get(value, "no", "projectNo", "number", "name", "code", default="")
    return _text(value)


def _line_amount_and_type(line: dict) -> tuple[Decimal, str]:
    raw_amount = _ci_get(line, "amount", "baseAmount", "primeAmount")
    debit_raw = _ci_get(line, "debit", "debitAmount")
    credit_raw = _ci_get(line, "credit", "creditAmount")
    amount_type = _text(_ci_get(line, "amountType", "debitCredit", "dc", default="")).upper()

    if debit_raw not in (None, "") and _decimal(debit_raw) != 0:
        return abs(_decimal(debit_raw)), "DEBIT"
    if credit_raw not in (None, "") and _decimal(credit_raw) != 0:
        return abs(_decimal(credit_raw)), "CREDIT"

    signed = _decimal(raw_amount)
    if amount_type in ("D", "DR"):
        amount_type = "DEBIT"
    elif amount_type in ("C", "CR"):
        amount_type = "CREDIT"
    if amount_type not in ("DEBIT", "CREDIT"):
        # Accurate request docs expose amountType, but keep a signed fallback.
        amount_type = "CREDIT" if signed < 0 else "DEBIT"
    return abs(signed), amount_type


def _fetch_journal_detail(client, header: dict) -> tuple[dict, dict, list[dict], str]:
    """Fetch detail using conservative + explicit-field strategies.

    Returns (raw_response, normalized_detail, parsed_lines, strategy).
    """
    hid = _ci_get(header, "id")
    if hid in (None, ""):
        return {}, {}, [], "missing-id"

    attempts = [
        ("plain-id", {"id": hid}),
        ("explicit-detail-fields", {
            "id": hid,
            "fields": "id,number,transDate,description,branchName,lastUpdate,detailJournalVoucher",
        }),
    ]
    last_raw = {}
    for label, params in attempts:
        try:
            raw = client.api_get("journal-voucher", "detail", params)
        except Exception:
            # `fields` support can differ; the plain call remains authoritative.
            if label == "plain-id":
                raise
            continue
        last_raw = raw
        detail = _detail_object(raw)
        lines = _extract_journal_lines(detail)
        if lines:
            return raw, detail, lines, label
    detail = _detail_object(last_raw)
    # Last fallback: list response itself occasionally contains expanded detail.
    lines = _extract_journal_lines(header)
    if lines:
        return last_raw, detail or header, lines, "list-expanded"
    return last_raw, detail, [], attempts[0][0]


def journal_detail_diagnostic(client, header: dict) -> dict:
    """Safe diagnostic summary + raw AOL JSON for one journal header."""
    raw, detail, lines, strategy = _fetch_journal_detail(client, header)
    def shape(value, depth=0):
        if depth > 4:
            return type(value).__name__
        if isinstance(value, dict):
            return {str(k): shape(v, depth+1) for k,v in list(value.items())[:80]}
        if isinstance(value, list):
            return [shape(v, depth+1) for v in value[:3]] + ([f"... {len(value)-3} more"] if len(value)>3 else [])
        if value is None:
            return None
        s=str(value)
        return s if len(s) <= 160 else s[:157] + "..."
    return {
        "header": {k: header.get(k) for k in ("id","number","transDate","description")},
        "strategy": strategy,
        "detail_top_keys": list(detail.keys()) if isinstance(detail, dict) else [],
        "parsed_line_count": len(lines),
        "parsed_line_sample": lines[:2],
        "raw_shape": shape(raw),
    }

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
        detail_resp, detail, lines, detail_strategy = _fetch_journal_detail(client, h)

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
        if not lines:
            zero_detail_headers += 1
        for line_index, line in enumerate(lines, start=1):
            amount, amount_type = _line_amount_and_type(line)
            debit = amount if amount_type == "DEBIT" else Decimal("0")
            credit = amount if amount_type == "CREDIT" else Decimal("0")
            try:
                line_id = int(_ci_get(line, "id", "detailId", "lineId", default=line_index) or line_index)
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
                memo=_text(_ci_get(line, "memo", "description", "notes", default="")),
            ))
            total_lines += 1
            if dept: with_department += 1
            if project: with_project += 1

        if idx % 10 == 0:
            db.commit()
        if job:
            span=max(progress_end-progress_start,1)
            job.progress = min(progress_start + int((idx / total) * span), progress_end)
            job.message = f"Load All Jurnal {idx:,}/{len(headers):,} • detail lines {total_lines:,} • parser {detail_strategy}"
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
