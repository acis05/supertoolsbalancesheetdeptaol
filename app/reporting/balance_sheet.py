from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from app.models import AccurateDatabase, GLAccount, JournalHeader, JournalLine, User
from app.core.auth import is_trial

BALANCE_MAP = {
    "CASH_BANK": ("ASET", "ASET LANCAR", "Kas dan Bank", "CURRENT_ASSET"),
    "ACCOUNT_RECEIVABLE": ("ASET", "ASET LANCAR", "Piutang Usaha", "CURRENT_ASSET"),
    "INVENTORY": ("ASET", "ASET LANCAR", "Persediaan", "CURRENT_ASSET"),
    "OTHER_CURRENT_ASSET": ("ASET", "ASET LANCAR", "Aset Lancar Lain", "CURRENT_ASSET"),
    "FIXED_ASSET": ("ASET", "ASET TETAP / TIDAK LANCAR", "Aset Tetap", "NONCURRENT_ASSET"),
    "ACCUMULATED_DEPRECIATION": ("ASET", "ASET TETAP / TIDAK LANCAR", "Akumulasi Penyusutan", "NONCURRENT_ASSET"),
    "OTHER_ASSET": ("ASET", "ASET TETAP / TIDAK LANCAR", "Aset Tidak Lancar Lain", "NONCURRENT_ASSET"),
    "ACCOUNT_PAYABLE": ("LIABILITAS", "LIABILITAS JANGKA PENDEK", "Utang Usaha", "CURRENT_LIABILITY"),
    "OTHER_CURRENT_LIABILITY": ("LIABILITAS", "LIABILITAS JANGKA PENDEK", "Liabilitas Jangka Pendek Lain", "CURRENT_LIABILITY"),
    "LONG_TERM_LIABILITY": ("LIABILITAS", "LIABILITAS JANGKA PANJANG", "Liabilitas Jangka Panjang", "LONG_TERM_LIABILITY"),
    "EQUITY": ("EKUITAS", "EKUITAS", "Ekuitas", "EQUITY"),
}
PNL_REVENUE = {"REVENUE", "OTHER_INCOME"}
PNL_EXPENSE = {"COGS", "EXPENSE", "OTHER_EXPENSE"}


def _apply_dimension_filters(stmt, department_filters=None, project_filters=None):
    department_filters = [x for x in (department_filters or []) if x]
    project_filters = [x for x in (project_filters or []) if x]
    if department_filters:
        normal = [x for x in department_filters if x != "__UNMAPPED__"]
        clauses = []
        if normal:
            clauses.append(JournalLine.department_name.in_(normal))
        if "__UNMAPPED__" in department_filters:
            clauses.append(or_(JournalLine.department_name == "", JournalLine.department_name.is_(None)))
        if clauses:
            stmt = stmt.where(or_(*clauses))
    if project_filters:
        normal = [x for x in project_filters if x != "__UNMAPPED__"]
        clauses = []
        if normal:
            clauses.append(JournalLine.project_no.in_(normal))
        if "__UNMAPPED__" in project_filters:
            clauses.append(or_(JournalLine.project_no == "", JournalLine.project_no.is_(None)))
        if clauses:
            stmt = stmt.where(or_(*clauses))
    return stmt


def build_balance_sheet(
    db: Session,
    user: User,
    database: AccurateDatabase,
    dimension: str = "department",
    as_of: str | None = None,
    department_filters: list[str] | None = None,
    project_filters: list[str] | None = None,
):
    accounts = {a.account_no: a for a in db.scalars(select(GLAccount).where(GLAccount.database_id == database.id)).all()}
    stmt = (
        select(JournalLine, JournalHeader)
        .join(JournalHeader, (JournalHeader.database_id == JournalLine.database_id) & (JournalHeader.accurate_id == JournalLine.journal_accurate_id))
        .where(JournalLine.database_id == database.id)
    )
    if as_of:
        try:
            cutoff = datetime.strptime(as_of, "%Y-%m-%d")
            stmt = stmt.where(JournalHeader.trans_date <= cutoff.replace(hour=23, minute=59, second=59))
        except ValueError:
            pass
    stmt = _apply_dimension_filters(stmt, department_filters, project_filters)
    entries = db.execute(stmt).all()
    source_line_count = len(entries)
    cash_line_count = 0

    balances = defaultdict(lambda: defaultdict(float))
    earnings = defaultdict(float)
    detail = []
    for line, header in entries:
        acc = accounts.get(line.account_no)
        if not acc:
            continue
        if dimension == "project":
            dim = line.project_no or "(UNMAPPED PROJECT)"
        elif dimension == "project_department":
            dim = f"{line.project_no or '(NO PROJECT)'} | {line.department_name or '(NO DEPARTMENT)'}"
        else:
            dim = line.department_name or "(UNMAPPED DEPARTMENT)"
        debit = float(line.debit or 0); credit = float(line.credit or 0)
        typ = (acc.account_type or "").strip().upper()
        if typ == "CASH_BANK":
            cash_line_count += 1
        if typ in PNL_REVENUE:
            earnings[dim] += credit - debit
        elif typ in PNL_EXPENSE:
            earnings[dim] -= debit - credit
        elif typ in BALANCE_MAP:
            side = BALANCE_MAP[typ][0]
            value = (credit - debit) if side in {"LIABILITAS", "EKUITAS"} else (debit - credit)
            balances[line.account_no][dim] += value
        detail.append({
            "date": header.trans_date.strftime("%Y-%m-%d"), "number": header.number,
            "account_no": line.account_no, "account_name": acc.name, "account_type": typ,
            "department": line.department_name or "", "project": line.project_no or "",
            "debit": debit, "credit": credit, "memo": line.memo or header.description,
        })

    dims = sorted({d for bydim in balances.values() for d in bydim} | set(earnings)) or ["(NO DATA)"]
    sections = []
    totals = {d: {"ASSET": 0.0, "LIABILITY": 0.0, "EQUITY": 0.0} for d in dims}
    group_totals = {d: {
        "CURRENT_ASSET": 0.0, "NONCURRENT_ASSET": 0.0,
        "CURRENT_LIABILITY": 0.0, "LONG_TERM_LIABILITY": 0.0,
        "EQUITY": 0.0,
    } for d in dims}
    order = [
        ("ASET", "ASET LANCAR", ["CASH_BANK","ACCOUNT_RECEIVABLE","INVENTORY","OTHER_CURRENT_ASSET"], "CURRENT_ASSET"),
        ("ASET", "ASET TETAP / TIDAK LANCAR", ["FIXED_ASSET","ACCUMULATED_DEPRECIATION","OTHER_ASSET"], "NONCURRENT_ASSET"),
        ("LIABILITAS", "LIABILITAS JANGKA PENDEK", ["ACCOUNT_PAYABLE","OTHER_CURRENT_LIABILITY"], "CURRENT_LIABILITY"),
        ("LIABILITAS", "LIABILITAS JANGKA PANJANG", ["LONG_TERM_LIABILITY"], "LONG_TERM_LIABILITY"),
        ("EKUITAS", "EKUITAS", ["EQUITY"], "EQUITY"),
    ]
    for major, group, types, group_key in order:
        rows = []
        for typ in types:
            for no, bydim in sorted(balances.items()):
                acc = accounts.get(no)
                if not acc or (acc.account_type or "").strip().upper() != typ:
                    continue
                vals = {d: bydim.get(d, 0.0) for d in dims}
                rows.append({"account_no": no, "name": acc.name, "account_type": typ, "values": vals, "cash_visible": typ == "CASH_BANK"})
                bucket = "ASSET" if major == "ASET" else ("LIABILITY" if major == "LIABILITAS" else "EQUITY")
                for d, v in vals.items():
                    totals[d][bucket] += v
                    group_totals[d][group_key] += v
        # Keep empty groups visible so the report structure stays consistent.
        sections.append({"major": major, "group": group, "group_key": group_key, "rows": rows})

    eq_section = next(s for s in sections if s["group_key"] == "EQUITY")
    current = {d: earnings.get(d, 0.0) for d in dims}
    eq_section["rows"].append({"account_no":"", "name":"Laba Tahun Berjalan (Current Earnings)", "account_type":"CURRENT_EARNINGS", "values":current, "cash_visible":False})
    for d,v in current.items():
        totals[d]["EQUITY"] += v
        group_totals[d]["EQUITY"] += v
    for d in dims:
        totals[d]["PASIVA"] = totals[d]["LIABILITY"] + totals[d]["EQUITY"]
        totals[d]["CHECK"] = totals[d]["ASSET"] - totals[d]["PASIVA"]

    # Add group subtotal objects for table rows.
    subtotal_labels = {
        "CURRENT_ASSET": "TOTAL ASET LANCAR",
        "NONCURRENT_ASSET": "TOTAL ASET TETAP / TIDAK LANCAR",
        "CURRENT_LIABILITY": "TOTAL LIABILITAS JANGKA PENDEK",
        "LONG_TERM_LIABILITY": "TOTAL LIABILITAS JANGKA PANJANG",
        "EQUITY": "TOTAL EKUITAS",
    }
    for section in sections:
        gk = section["group_key"]
        section["subtotal_label"] = subtotal_labels[gk]
        section["subtotal"] = {d: group_totals[d][gk] for d in dims}

    overall_totals = {k: sum(totals[d][k] for d in dims) for k in ("ASSET","LIABILITY","EQUITY","PASIVA","CHECK")}
    overall_group_totals = {k: sum(group_totals[d][k] for d in dims) for k in ("CURRENT_ASSET","NONCURRENT_ASSET","CURRENT_LIABILITY","LONG_TERM_LIABILITY","EQUITY")}

    trial = is_trial(user)
    if trial:
        # Security enforcement: non-CASH_BANK numbers are removed server-side. CSS blur is only visual sugar.
        for section in sections:
            for row in section["rows"]:
                if not row.get("cash_visible"):
                    row["masked"] = True
                    row["values"] = {d: None for d in dims}
            # A subtotal may reveal locked balances, so all group totals are masked in trial.
            section["subtotal"] = {d: None for d in dims}
        for d in dims:
            totals[d] = {k: None for k in ("ASSET","LIABILITY","EQUITY","PASIVA","CHECK")}
            group_totals[d] = {k: None for k in ("CURRENT_ASSET","NONCURRENT_ASSET","CURRENT_LIABILITY","LONG_TERM_LIABILITY","EQUITY")}
        detail = [x for x in detail if x["account_type"] == "CASH_BANK"]
        overall_totals = {k: None for k in overall_totals}
        overall_group_totals = {k: None for k in overall_group_totals}

    return {
        "dimensions": dims, "sections": sections, "totals": totals, "group_totals": group_totals,
        "overall_totals": overall_totals, "overall_group_totals": overall_group_totals,
        "detail": detail, "trial": trial, "source_line_count": source_line_count, "cash_line_count": cash_line_count,
        "department_filters": department_filters or [], "project_filters": project_filters or [],
    }
