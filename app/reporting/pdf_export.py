from __future__ import annotations
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak

TEAL = colors.HexColor('#075C59')
TEAL_SOFT = colors.HexColor('#EAF7F5')
ORANGE = colors.HexColor('#F97316')
GRAY = colors.HexColor('#F4F7F9')
TEXT = colors.HexColor('#17313F')
BORDER = colors.HexColor('#DCE5E8')


def _money(v):
    if v is None:
        return 'TRIAL LOCKED'
    return f'{float(v):,.2f}'


def _p(text, style):
    return Paragraph(str(text or ''), style)


def _base_doc(title, subtitle):
    bio = BytesIO()
    doc = SimpleDocTemplate(
        bio, pagesize=landscape(A4),
        rightMargin=10*mm, leftMargin=10*mm, topMargin=10*mm, bottomMargin=10*mm,
        title=title,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleST', parent=styles['Title'], textColor=TEAL, fontSize=16, leading=19, spaceAfter=2)
    sub_style = ParagraphStyle('SubST', parent=styles['Normal'], textColor=colors.HexColor('#647480'), fontSize=8, leading=10, spaceAfter=8)
    normal = ParagraphStyle('NormalST', parent=styles['Normal'], textColor=TEXT, fontSize=7, leading=9)
    small = ParagraphStyle('SmallST', parent=normal, fontSize=6.4, leading=8)
    right = ParagraphStyle('RightST', parent=small, alignment=TA_RIGHT)
    story = [_p(title, title_style), _p(subtitle, sub_style)]
    return bio, doc, story, normal, small, right


def _table_widths(dim_count):
    page_width = landscape(A4)[0] - 20*mm
    fixed = [24*mm, 52*mm, 34*mm]
    numeric_count = max(1, dim_count + 1)
    numeric_width = max(24*mm, (page_width - sum(fixed)) / numeric_count)
    widths = fixed + [numeric_width] * numeric_count
    # Scale down if many dimensions are shown.
    total = sum(widths)
    if total > page_width:
        scale = page_width / total
        widths = [w*scale for w in widths]
    return widths


def _apply_common_table_style(table, header_rows=(0,)):
    commands = [
        ('GRID', (0,0), (-1,-1), 0.25, BORDER),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('LEFTPADDING', (0,0), (-1,-1), 4), ('RIGHTPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]
    for r in header_rows:
        commands += [('BACKGROUND', (0,r), (-1,r), TEAL), ('TEXTCOLOR', (0,r), (-1,r), colors.white), ('FONTNAME', (0,r), (-1,r), 'Helvetica-Bold')]
    table.setStyle(TableStyle(commands))


def balance_sheet_pdf(app_name, database_alias, data, dimension, as_of, selected_departments=None, selected_projects=None):
    subtitle = f'{database_alias} | Laporan Posisi Keuangan | Mode: {dimension.replace("_", " + ").title()} | As of: {as_of or "All data"}'
    if selected_departments:
        subtitle += ' | Dept: ' + ', '.join(selected_departments)
    if selected_projects:
        subtitle += ' | Project: ' + ', '.join(selected_projects)
    bio, doc, story, normal, small, right = _base_doc(app_name, subtitle)

    dims = data['dimensions']
    headers = ['Akun','Nama Akun','Type', *dims, 'TOTAL']
    rows = [[_p(h, small) for h in headers]]
    styles_by_row = []

    last_major = None
    for section in data['sections']:
        if section['major'] != last_major:
            rows.append([_p(section['major'], small)] + ['']*(len(headers)-1)); styles_by_row.append((len(rows)-1, 'major'))
            last_major = section['major']
        rows.append([_p(section['group'], small)] + ['']*(len(headers)-1)); styles_by_row.append((len(rows)-1, 'group'))
        for row in section['rows']:
            vals = []
            total = 0.0
            locked = bool(row.get('masked'))
            for d in dims:
                v = row['values'][d]
                vals.append(_money(v))
                if v is not None: total += float(v)
            rows.append([
                _p(row.get('account_no',''), small), _p(row.get('name',''), small), _p(row.get('account_type',''), small),
                *[_p(v, right) for v in vals], _p('TRIAL LOCKED' if locked else f'{total:,.2f}', right)
            ])
        subtotal_vals = [section['subtotal'][d] for d in dims]
        locked = any(v is None for v in subtotal_vals)
        subtotal_total = sum(float(v) for v in subtotal_vals if v is not None)
        rows.append(['', _p(section['subtotal_label'], small), '', *[_p(_money(v), right) for v in subtotal_vals], _p('TRIAL LOCKED' if locked else f'{subtotal_total:,.2f}', right)])
        styles_by_row.append((len(rows)-1, 'subtotal'))

    for label,key,kind in [
        ('TOTAL ASET LANCAR','CURRENT_ASSET','group'),('TOTAL ASET TETAP / TIDAK LANCAR','NONCURRENT_ASSET','group'),
        ('TOTAL LIABILITAS JANGKA PENDEK','CURRENT_LIABILITY','group'),('TOTAL LIABILITAS JANGKA PANJANG','LONG_TERM_LIABILITY','group'),
        ('TOTAL EKUITAS','EQUITY','group'),('TOTAL ASET / AKTIVA','ASSET','total'),('TOTAL LIABILITAS + EKUITAS / PASIVA','PASIVA','total'),('BALANCE CHECK','CHECK','total')]:
        vals=[]
        for d in dims:
            vals.append(data['group_totals'][d][key] if kind=='group' else data['totals'][d][key])
        locked=any(v is None for v in vals)
        total=sum(float(v) for v in vals if v is not None)
        rows.append(['', _p(label, small), '', *[_p(_money(v), right) for v in vals], _p('TRIAL LOCKED' if locked else f'{total:,.2f}', right)])
        styles_by_row.append((len(rows)-1, 'grand' if key in ('ASSET','PASIVA') else 'subtotal'))

    table = Table(rows, colWidths=_table_widths(len(dims)), repeatRows=1, hAlign='LEFT')
    _apply_common_table_style(table)
    cmds=[]
    for idx, typ in styles_by_row:
        if typ=='major': cmds += [('BACKGROUND',(0,idx),(-1,idx),TEAL),('TEXTCOLOR',(0,idx),(-1,idx),colors.white),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold'),('SPAN',(0,idx),(-1,idx))]
        elif typ=='group': cmds += [('BACKGROUND',(0,idx),(-1,idx),TEAL_SOFT),('TEXTCOLOR',(0,idx),(-1,idx),TEAL),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold'),('SPAN',(0,idx),(-1,idx))]
        elif typ=='subtotal': cmds += [('BACKGROUND',(0,idx),(-1,idx),GRAY),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold')]
        elif typ=='grand': cmds += [('BACKGROUND',(0,idx),(-1,idx),colors.HexColor('#D5EBE6')),('TEXTCOLOR',(0,idx),(-1,idx),TEAL),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold')]
    table.setStyle(TableStyle(cmds))
    story.append(table)
    doc.build(story)
    bio.seek(0)
    return bio


def profit_loss_pdf(app_name, database_alias, data, dimension, date_from, date_to, selected_departments=None, selected_projects=None):
    subtitle = f'{database_alias} | Laporan Laba Rugi | Mode: {dimension.replace("_", " + ").title()} | {date_from or "Awal"} s/d {date_to or "Akhir"}'
    if selected_departments: subtitle += ' | Dept: ' + ', '.join(selected_departments)
    if selected_projects: subtitle += ' | Project: ' + ', '.join(selected_projects)
    bio, doc, story, normal, small, right = _base_doc(app_name, subtitle)
    dims=data['dimensions']
    headers=['Akun','Nama Akun','Type',*dims,'TOTAL']
    rows=[[_p(h,small) for h in headers]]
    styles_by_row=[]
    for section in data['sections']:
        rows.append([_p(section['label'],small)]+['']*(len(headers)-1)); styles_by_row.append((len(rows)-1,'major'))
        for row in section['rows']:
            vals=[row['values'][d] for d in dims]
            locked=bool(row.get('masked')) or any(v is None for v in vals)
            total=sum(float(v) for v in vals if v is not None)
            rows.append([_p(row['account_no'],small),_p(row['name'],small),_p(row['account_type'],small),*[_p(_money(v),right) for v in vals],_p('TRIAL LOCKED' if locked else f'{total:,.2f}',right)])
        vals=[section['subtotal'][d] for d in dims]; locked=any(v is None for v in vals); total=sum(float(v) for v in vals if v is not None)
        rows.append(['',_p('TOTAL '+section['label'],small),'',*[_p(_money(v),right) for v in vals],_p('TRIAL LOCKED' if locked else f'{total:,.2f}',right)])
        styles_by_row.append((len(rows)-1,'subtotal'))
        if section['key']=='COGS':
            vals=[data['summaries'][d]['GROSS_PROFIT'] for d in dims]; locked=any(v is None for v in vals); total=sum(float(v) for v in vals if v is not None)
            rows.append(['',_p('LABA KOTOR',small),'',*[_p(_money(v),right) for v in vals],_p('TRIAL LOCKED' if locked else f'{total:,.2f}',right)]); styles_by_row.append((len(rows)-1,'result'))
        if section['key']=='EXPENSE':
            vals=[data['summaries'][d]['OPERATING_PROFIT'] for d in dims]; locked=any(v is None for v in vals); total=sum(float(v) for v in vals if v is not None)
            rows.append(['',_p('LABA USAHA',small),'',*[_p(_money(v),right) for v in vals],_p('TRIAL LOCKED' if locked else f'{total:,.2f}',right)]); styles_by_row.append((len(rows)-1,'result'))
    vals=[data['summaries'][d]['NET_PROFIT'] for d in dims]; locked=any(v is None for v in vals); total=sum(float(v) for v in vals if v is not None)
    rows.append(['',_p('LABA BERSIH',small),'',*[_p(_money(v),right) for v in vals],_p('TRIAL LOCKED' if locked else f'{total:,.2f}',right)]); styles_by_row.append((len(rows)-1,'grand'))

    table=Table(rows,colWidths=_table_widths(len(dims)),repeatRows=1,hAlign='LEFT')
    _apply_common_table_style(table)
    cmds=[]
    for idx,typ in styles_by_row:
        if typ=='major': cmds += [('BACKGROUND',(0,idx),(-1,idx),TEAL),('TEXTCOLOR',(0,idx),(-1,idx),colors.white),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold'),('SPAN',(0,idx),(-1,idx))]
        elif typ=='subtotal': cmds += [('BACKGROUND',(0,idx),(-1,idx),GRAY),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold')]
        elif typ=='result': cmds += [('BACKGROUND',(0,idx),(-1,idx),TEAL_SOFT),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold')]
        elif typ=='grand': cmds += [('BACKGROUND',(0,idx),(-1,idx),colors.HexColor('#D5EBE6')),('TEXTCOLOR',(0,idx),(-1,idx),TEAL),('FONTNAME',(0,idx),(-1,idx),'Helvetica-Bold')]
    table.setStyle(TableStyle(cmds))
    story.append(table)
    doc.build(story)
    bio.seek(0)
    return bio
