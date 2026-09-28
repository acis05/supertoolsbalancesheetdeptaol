from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AccurateDatabase, GLAccount, JournalHeader, JournalLine, User
from app.core.auth import is_trial

BALANCE_MAP = {
    "CASH_BANK": ("ASET", "ASET LANCAR", "Kas dan Bank"),
    "ACCOUNT_RECEIVABLE": ("ASET", "ASET LANCAR", "Piutang Usaha"),
    "INVENTORY": ("ASET", "ASET LANCAR", "Persediaan"),
    "OTHER_CURRENT_ASSET": ("ASET", "ASET LANCAR", "Aset Lancar Lain"),
    "FIXED_ASSET": ("ASET", "ASET TIDAK LANCAR", "Aset Tetap"),
    "ACCUMULATED_DEPRECIATION": ("ASET", "ASET TIDAK LANCAR", "Akumulasi Penyusutan"),
    "OTHER_ASSET": ("ASET", "ASET TIDAK LANCAR", "Aset Tidak Lancar Lain"),
    "ACCOUNT_PAYABLE": ("LIABILITAS", "LIABILITAS JANGKA PENDEK", "Utang Usaha"),
    "OTHER_CURRENT_LIABILITY": ("LIABILITAS", "LIABILITAS JANGKA PENDEK", "Liabilitas Jangka Pendek Lain"),
    "LONG_TERM_LIABILITY": ("LIABILITAS", "LIABILITAS JANGKA PANJANG", "Liabilitas Jangka Panjang"),
    "EQUITY": ("EKUITAS", "EKUITAS", "Ekuitas"),
}
PNL_REVENUE = {"REVENUE", "OTHER_INCOME"}
PNL_EXPENSE = {"COGS", "EXPENSE", "OTHER_EXPENSE"}


def build_balance_sheet(db: Session, user: User, database: AccurateDatabase, dimension: str = "department", as_of: str | None = None):
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
    entries = db.execute(stmt).all()

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
        typ = acc.account_type
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
    order = [
        ("ASET", "ASET LANCAR", ["CASH_BANK","ACCOUNT_RECEIVABLE","INVENTORY","OTHER_CURRENT_ASSET"]),
        ("ASET", "ASET TIDAK LANCAR", ["FIXED_ASSET","ACCUMULATED_DEPRECIATION","OTHER_ASSET"]),
        ("LIABILITAS", "LIABILITAS JANGKA PENDEK", ["ACCOUNT_PAYABLE","OTHER_CURRENT_LIABILITY"]),
        ("LIABILITAS", "LIABILITAS JANGKA PANJANG", ["LONG_TERM_LIABILITY"]),
        ("EKUITAS", "EKUITAS", ["EQUITY"]),
    ]
    for major, group, types in order:
        rows = []
        for typ in types:
            for no, bydim in sorted(balances.items()):
                acc = accounts.get(no)
                if not acc or acc.account_type != typ:
                    continue
                vals = {d: bydim.get(d, 0.0) for d in dims}
                rows.append({"account_no": no, "name": acc.name, "account_type": typ, "values": vals, "cash_visible": typ == "CASH_BANK"})
                bucket = "ASSET" if major == "ASET" else ("LIABILITY" if major == "LIABILITAS" else "EQUITY")
                for d, v in vals.items():
                    totals[d][bucket] += v
        if rows:
            sections.append({"major": major, "group": group, "rows": rows})

    eq_section = next((s for s in sections if s["major"] == "EKUITAS"), None)
    if not eq_section:
        eq_section = {"major": "EKUITAS", "group": "EKUITAS", "rows": []}; sections.append(eq_section)
    current = {d: earnings.get(d, 0.0) for d in dims}
    eq_section["rows"].append({"account_no":"", "name":"Laba Tahun Berjalan (Current Earnings)", "account_type":"CURRENT_EARNINGS", "values":current, "cash_visible":False})
    for d,v in current.items(): totals[d]["EQUITY"] += v
    for d in dims:
        totals[d]["PASIVA"] = totals[d]["LIABILITY"] + totals[d]["EQUITY"]
        totals[d]["CHECK"] = totals[d]["ASSET"] - totals[d]["PASIVA"]

    trial = is_trial(user)
    if trial:
        # Security enforcement: non-CASH_BANK numbers are removed server-side. CSS blur is only visual sugar.
        for section in sections:
            for row in section["rows"]:
                if not row.get("cash_visible"):
                    row["masked"] = True
                    row["values"] = {d: None for d in dims}
        # Trial totals reveal only cash/bank. Full balance-sheet totals stay masked.
        for d in dims:
            totals[d] = {k: None for k in ("ASSET","LIABILITY","EQUITY","PASIVA","CHECK")}
        detail = [x for x in detail if x["account_type"] == "CASH_BANK"]

    return {"dimensions": dims, "sections": sections, "totals": totals, "detail": detail, "trial": trial}
