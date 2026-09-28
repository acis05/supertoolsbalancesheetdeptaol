from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from sqlalchemy import delete, select
from app.database import SessionLocal
from app.models import AccurateDatabase, GLAccount, Department, Project, JournalHeader, JournalLine, SyncJob, User
from app.services.accurate_client import client_for_database


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()
    value = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt)
        except ValueError:
            continue
    return datetime.utcnow()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in {"1", "true", "yes"}


def _upsert_account(db, database_id: int, row: dict):
    no = str(row.get("no") or "").strip()
    if not no:
        return
    obj = db.scalar(select(GLAccount).where(GLAccount.database_id == database_id, GLAccount.account_no == no))
    if not obj:
        obj = GLAccount(database_id=database_id, account_no=no)
        db.add(obj)
    obj.accurate_id = row.get("id")
    obj.name = str(row.get("name") or "")
    obj.account_type = str(row.get("accountType") or "")
    obj.parent_no = str(row.get("parentNo") or "")
    obj.suspended = _bool(row.get("suspended"))


def _upsert_department(db, database_id: int, row: dict):
    rid = row.get("id")
    if rid is None:
        return
    obj = db.scalar(select(Department).where(Department.database_id == database_id, Department.accurate_id == int(rid)))
    if not obj:
        obj = Department(database_id=database_id, accurate_id=int(rid))
        db.add(obj)
    obj.name = str(row.get("name") or "")
    obj.description = str(row.get("description") or "")
    obj.suspended = _bool(row.get("suspended"))


def _upsert_project(db, database_id: int, row: dict):
    no = str(row.get("no") or row.get("id") or "").strip()
    if not no:
        return
    obj = db.scalar(select(Project).where(Project.database_id == database_id, Project.project_no == no))
    if not obj:
        obj = Project(database_id=database_id, project_no=no)
        db.add(obj)
    obj.accurate_id = row.get("id")
    obj.name = str(row.get("name") or "")
    obj.description = str(row.get("description") or "")
    obj.suspended = _bool(row.get("suspended"))


def run_full_sync(job_id: int):
    db = SessionLocal()
    try:
        job = db.get(SyncJob, job_id)
        if not job:
            return
        job.status = "RUNNING"; job.started_at = datetime.utcnow(); job.progress = 2; job.message = "Membuka koneksi Accurate Online..."; db.commit()
        dbrow = db.get(AccurateDatabase, job.database_id)
        user = db.get(User, job.user_id)
        if not dbrow or not user or not user.oauth:
            raise RuntimeError("Database atau OAuth credential tidak tersedia")
        client = client_for_database(dbrow, user.oauth, db)

        # Masters
        job.message = "Sync akun perkiraan..."; job.progress = 8; db.commit()
        account_rows = list(client.paged_list("glaccount", fields="id,no,name,accountType,parentNo,suspended", page_size=100, extra={"filter.leafOnly": "false"}))
        for row in account_rows:
            _upsert_account(db, dbrow.id, row)
        db.commit()

        job.message = "Sync departemen..."; job.progress = 15; db.commit()
        department_rows = list(client.paged_list("department", fields="id,name,description,suspended", page_size=100))
        for row in department_rows:
            _upsert_department(db, dbrow.id, row)
        db.commit()

        job.message = "Sync project..."; job.progress = 22; db.commit()
        project_rows = list(client.paged_list("project", fields="id,no,name,description,suspended", page_size=100))
        for row in project_rows:
            _upsert_project(db, dbrow.id, row)
        db.commit()

        # Journal Voucher header list then detail. The docs expose detailJournalVoucher
        # on detail.do, including accountNo, amount, amountType, departmentName, projectNo.
        job.message = "Membaca daftar jurnal voucher..."; job.progress = 28; db.commit()
        headers = list(client.paged_list("journal-voucher", fields="id,number,transDate,description,branchName,lastUpdate", page_size=100))
        total = max(len(headers), 1)
        for idx, h in enumerate(headers, start=1):
            hid = int(h.get("id"))
            detail_resp = client.api_get("journal-voucher", "detail", {"id": hid})
            detail = detail_resp.get("d") or detail_resp.get("r") or {}
            if isinstance(detail, list):
                detail = detail[0] if detail else {}
            header = db.scalar(select(JournalHeader).where(JournalHeader.database_id == dbrow.id, JournalHeader.accurate_id == hid))
            if not header:
                header = JournalHeader(database_id=dbrow.id, accurate_id=hid, trans_date=_dt(detail.get("transDate") or h.get("transDate")))
                db.add(header)
            header.number = str(detail.get("number") or h.get("number") or "")
            header.trans_date = _dt(detail.get("transDate") or h.get("transDate"))
            header.description = str(detail.get("description") or h.get("description") or "")
            header.branch_name = str(detail.get("branchName") or h.get("branchName") or "")
            header.last_update = str(detail.get("lastUpdate") or h.get("lastUpdate") or "")
            db.flush()

            db.execute(delete(JournalLine).where(JournalLine.database_id == dbrow.id, JournalLine.journal_accurate_id == hid))
            lines = detail.get("detailJournalVoucher") or detail.get("detailJournalVoucherList") or detail.get("detail") or []
            if isinstance(lines, dict):
                lines = [lines]
            for line_index, line in enumerate(lines, start=1):
                amount = Decimal(str(line.get("amount") or 0))
                amount_type = str(line.get("amountType") or "").upper()
                debit = amount if amount_type == "DEBIT" else Decimal("0")
                credit = amount if amount_type == "CREDIT" else Decimal("0")
                line_id = int(line.get("id") or line_index)
                db.add(JournalLine(
                    database_id=dbrow.id,
                    journal_accurate_id=hid,
                    line_accurate_id=line_id,
                    account_no=str(line.get("accountNo") or ""),
                    amount=amount,
                    amount_type=amount_type,
                    debit=debit,
                    credit=credit,
                    department_name=str(line.get("departmentName") or ""),
                    project_no=str(line.get("projectNo") or ""),
                    memo=str(line.get("memo") or ""),
                ))
            if idx % 10 == 0:
                db.commit()
            pct = 28 + int((idx / total) * 68)
            job.progress = min(pct, 96); job.message = f"Sync jurnal {idx:,}/{len(headers):,}..."; db.commit()

        dbrow.last_sync_at = datetime.utcnow()
        job.progress = 100; job.status = "DONE"; job.finished_at = datetime.utcnow()
        job.message = f"Sync selesai • {len(account_rows)} akun • {len(department_rows)} departemen • {len(project_rows)} project • {len(headers)} jurnal"
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(SyncJob, job_id)
        if job:
            job.status = "FAILED"; job.message = str(exc); job.finished_at = datetime.utcnow(); db.commit()
    finally:
        db.close()
