"""Small, source-grounded metadata for the explicitly supported inline adapter."""
from calendar import month_name
import re

from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _hidden, _table_rows, _visible_text
from .financial_records import local_name

METRIC_DESCRIPTION_VERSION = 'us-gaap-data-description-v2'
METRIC_DESCRIPTIONS = {
    'revenue': ('Revenue / 收入', 'Reported revenue under the mapped revenue concept; preserve consolidated versus dimensional scope. Not cash receipts, bookings, or guidance.', ['revenue', 'revenues', 'net sales', '收入', '营业收入']),
    'revenue_including_assessed_tax': ('Revenue including assessed tax / 含代征税收入', 'Reported customer-contract revenue including assessed tax. Keep separate from revenue excluding assessed tax; never sum both definitions.', ['revenue including assessed tax', '含代征税收入']),
    'operating_income': ('Operating income / 营业利润', 'Reported operating income or loss after operating costs and expenses. Not net income, EBITDA, or operating cash flow.', ['operating income', 'operating loss', 'income from operations', '营业利润', '经营利润']),
    'net_income': ('Net income / 净利润', 'Reported net income or loss for the stated scope and period. Preserve the source attribution; do not substitute an adjusted or attributable-income concept.', ['net income', 'net loss', '净利润', '净亏损']),
    'operating_cash_flow': ('Operating cash flow / 经营现金流', 'Net cash provided by or used in operating activities for the stated duration. Not operating profit, free cash flow, or an ending cash balance.', ['operating cash flow', 'cash from operations', '经营现金流', '经营活动现金流量净额']),
    'capex_cash_payments': ('Cash payments for property and equipment / 固定资产购置现金支出', 'Reported cash payments to acquire property, plant and equipment. Not total investment, accrual additions, or free cash flow; do not reverse the cash-payment sign.', ['capex cash payments', 'payments to acquire property plant and equipment', '固定资产购置现金支出']),
}


def table_year_evidence(tag, block):
    """Recognize an explicit annual column label above a located inline fact.

    Match the DOM grid to the stored visible table grid. Nested tables, hidden
    headings, unaligned headers and unclear annual captions supply no mapping.
    Returned labels are evidence, not fiscal-year inference from end dates.
    """
    table = next(tag.iterancestors('table'), None)
    cell = next((a for a in tag.iterancestors() if local_name(a) in {'td', 'th'}), None)
    if table is None or cell is None or not block.get('table'):
        return None
    if table.getroottree().getpath(table) != block.get('dom_path'):
        return None
    rows = [r for r in _table_rows(table, nearest_table=True) if not _hidden(r)]
    stored = {(c['row'], c['column']): c for c in block['table']['cells']}
    occupied, cells, target = set(), [], None
    first_fact_row = None
    for ri, row in enumerate(rows):
        col = 0
        for td in row.xpath('./th|./td'):
            if _hidden(td):
                continue
            while (ri, col) in occupied:
                col += 1
            try:
                rs, cs = max(1, int(td.get('rowspan', '1'))), max(1, int(td.get('colspan', '1')))
            except ValueError:
                return None
            original = stored.get((ri, col))
            if (not original or original['rowspan'] != rs or original['colspan'] != cs
                    or normalize_text(_visible_text(td)) != normalize_text(original['text'])):
                return None
            cells.append(original)
            if td is cell:
                target = original
            if any(local_name(e) == 'nonfraction' for e in td.iter()):
                first_fact_row = ri if first_fact_row is None else min(first_fact_row, ri)
            occupied.update((r, c) for r in range(ri, ri + rs) for c in range(col, col + cs))
            col += cs
    if target is None or first_fact_row is None:
        return None
    headers = [c for c in cells if c['row'] < first_fact_row]
    annual = []
    for header in headers:
        match = re.search(r'\byears?\s+ended\s+([A-Za-z]+)\s+(\d{1,2})\b', header['text'], re.I)
        if match and match[1].lower() in {m.lower() for m in month_name if m}:
            annual.append((next(i for i, m in enumerate(month_name) if m.lower() == match[1].lower()), int(match[2]), header))
    if len({(m, d) for m, d, _ in annual}) != 1:
        return None
    labels = [c for c in headers if re.fullmatch(r'(?:FY\s*)?[1-9]\d{3}', c['text'], re.I)
              and c['column'] <= target['column'] and target['column'] + target['colspan'] <= c['column'] + c['colspan']]
    years = {int(re.search(r'\d{4}', c['text'])[0]) for c in labels}
    if len(years) != 1:
        return None
    header = labels[-1]
    return {'fiscal_year': years.pop(), 'month': annual[0][0], 'day': annual[0][1],
            'header': {k: header[k] for k in ('row', 'column', 'text')},
            'annual_caption': {k: annual[0][2][k] for k in ('row', 'column', 'text')}}
