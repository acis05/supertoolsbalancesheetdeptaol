from __future__ import annotations
from collections import defaultdict
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import AccurateDatabase, GLAccount, JournalHeader, JournalLine, User
from app.core.auth import is_trial
from app.reporting.balance_sheet import _apply_dimension_filters

PNL_GROUPS = [
    ("REVENUE", "PENDAPATAN USAHA", {"REVENUE"}),
    ("COGS", "HARGA POKOK PENJUALAN", {"COGS"}),
    ("EXPENSE", "BEBAN OPERASIONAL", {"EXPENSE"}),
    ("OTHER_INCOME", "PENDAPATAN LAIN", {"OTHER_INCOME"}),
    ("OTHER_EXPENSE", "BEBAN LAIN", {"OTHER_EXPENSE"}),
]


def build_profit_loss(
    db: Session,
    user: User,
    database: AccurateDatabase,
    dimension: str = "department",
    date_from: str | None = None,
    date_to: str | None = None,
    department_filters: list[str] | None = None,
    project_filters: list[str] | None = None,
):
    accounts = {a.account_no: a for a in db.scalars(select(GLAccount).where(GLAccount.database_id == database.id)).all()}
    stmt = (
        select(JournalLine, JournalHeader)
        .join(JournalHeader, (JournalHeader.database_id == JournalLine.database_id) & (JournalHeader.accurate_id == JournalLine.journal_accurate_id))
        .where(JournalLine.database_id == database.id)
    )
    try:
        if date_from:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            stmt = stmt.where(JournalHeader.trans_date >= dt)
        if date_to:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            stmt = stmt.where(JournalHeader.trans_date <= dt.replace(hour=23, minute=59, second=59))
    except ValueError:
        pass
    stmt = _apply_dimension_filters(stmt, department_filters, project_filters)
    entries = db.execute(stmt).all()

    balances = defaultdict(lambda: defaultdict(float))
    pnl_line_count = 0
    for line, header in entries:
        acc = accounts.get(line.account_no)
        if not acc:
            continue
        typ = (acc.account_type or "").strip().upper()
        if typ not in {"REVENUE","COGS","EXPENSE","OTHER_INCOME","OTHER_EXPENSE"}:
            continue
        pnl_line_count += 1
        if dimension == "project":
            dim = line.project_no or "(UNMAPPED PROJECT)"
        elif dimension == "project_department":
            dim = f"{line.project_no or '(NO PROJECT)'} | {line.department_name or '(NO DEPARTMENT)'}"
        else:
            dim = line.department_name or "(UNMAPPED DEPARTMENT)"
        debit = float(line.debit or 0); credit = float(line.credit or 0)
        # Natural presentation: revenue/income positive on credit; cost/expense positive on debit.
        value = (credit - debit) if typ in {"REVENUE","OTHER_INCOME"} else (debit - credit)
        balances[line.account_no][dim] += value

    dims = sorted({d for bydim in balances.values() for d in bydim}) or ["(NO DATA)"]
    sections = []
    bucket_totals = {d: {"REVENUE":0.0,"COGS":0.0,"EXPENSE":0.0,"OTHER_INCOME":0.0,"OTHER_EXPENSE":0.0} for d in dims}
    for key, label, types in PNL_GROUPS:
        rows=[]
        for no, bydim in sorted(balances.items()):
            acc=accounts.get(no)
            typ=(acc.account_type or "").strip().upper() if acc else ""
            if not acc or typ not in types:
                continue
            vals={d:bydim.get(d,0.0) for d in dims}
            rows.append({"account_no":no,"name":acc.name,"account_type":typ,"values":vals})
            for d,v in vals.items(): bucket_totals[d][key]+=v
        sections.append({"key":key,"label":label,"rows":rows,"subtotal":{d:bucket_totals[d][key] for d in dims}})

    summaries={}
    for d in dims:
        revenue=bucket_totals[d]["REVENUE"]
        cogs=bucket_totals[d]["COGS"]
        expense=bucket_totals[d]["EXPENSE"]
        other_income=bucket_totals[d]["OTHER_INCOME"]
        other_expense=bucket_totals[d]["OTHER_EXPENSE"]
        gross=revenue-cogs
        operating=gross-expense
        net=operating+other_income-other_expense
        summaries[d]={
            "REVENUE":revenue,"COGS":cogs,"GROSS_PROFIT":gross,"EXPENSE":expense,
            "OPERATING_PROFIT":operating,"OTHER_INCOME":other_income,"OTHER_EXPENSE":other_expense,"NET_PROFIT":net,
        }

    overall_summary={k:sum(summaries[d][k] for d in dims) for k in next(iter(summaries.values())).keys()} if summaries else {}

    trial=is_trial(user)
    if trial:
        # Trial entitlement only exposes full Cash/Bank balances. P&L amounts are therefore server-side masked.
        for section in sections:
            for row in section["rows"]:
                row["masked"]=True; row["values"]={d:None for d in dims}
            section["subtotal"]={d:None for d in dims}
        summaries={d:{k:None for k in v} for d,v in summaries.items()}
        overall_summary={k:None for k in overall_summary}

    return {
        "dimensions":dims,"sections":sections,"summaries":summaries,"overall_summary":overall_summary,"trial":trial,
        "source_line_count":len(entries),"pnl_line_count":pnl_line_count,
        "department_filters":department_filters or [],"project_filters":project_filters or [],
    }
