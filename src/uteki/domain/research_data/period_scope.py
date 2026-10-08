"""Conservative calendar-period grounding for the initial NL query interface.

This is a declared syntax subset, not a general temporal language parser. It
never learns periods from stored coverage. Other syntax needs clarification.
"""
from calendar import monthrange
from datetime import date
import re

from .query_contract import Period


PERIOD_SCOPE_VERSION = "explicit-calendar-periods-v2-cutoff-role"
# A sentence-ending period is punctuation, while a decimal suffix is not a year.
_YEAR = r"(?<![\d.])(?P<year>[1-9]\d{3})(?!\d|\.\d)"
_QUARTER = r"(?:Q(?P<q>[1-4])|第?\s*(?P<cq>[一二三四1234])\s*季度)"
_FORWARD = re.compile(_YEAR + r"\s*年?\s*" + _QUARTER, re.I)
_REVERSE = re.compile(_QUARTER + r"\s*(?:of\s+)?" + _YEAR, re.I)
# Refuse constructs whose interpretation would require additional rules. This
# prevents a year inside an unsupported YTD/range expression becoming FY.
_UNSUPPORTED = re.compile(
    r"\b(?:YTD|H[12]|latest|last|current|previous|first\s+half|second\s+half)\b"
    r"|截至|至今|上半年|下半年|前[一二三四1234]季度|最新|去年|今年|最近"
    r"|\d{4}\s*(?:[-/–—]|至|到|through|to)\s*\d", re.I)


_ISO_DATE = r"[1-9]\d{3}-\d{2}-\d{2}"
_CUTOFF_CLAUSES = (
    re.compile(r"以\s*(?P<date>" + _ISO_DATE + r")\s*为\s*(?:资料|材料|信息)\s*(?:可得|可用)?\s*截止(?:日|日期)"),
    re.compile(r"(?:资料|材料|信息)\s*(?:可得|可用)?\s*截止(?:日期|日)\s*(?:为|是|[:：])?\s*(?P<date>" + _ISO_DATE + r")(?![\dTtZz:+]|-\d)"),
    re.compile(r"\b(?:(?:knowledge|information|material)\s+cutoff(?:\s+date)?\s*[:=]?|information\s+available\s+as\s+of)\s*(?P<date>" + _ISO_DATE + r")(?![\dTtZz:+]|-\d)", re.I),
)


def _without_bound_cutoff(question, knowledge_cutoff):
    """Mask only declared information-cutoff clauses matching caller scope.

    This does not choose a cutoff, remove arbitrary dates, or interpret YTD.
    Other syntax remains subject to the conservative period parser below.
    """
    if knowledge_cutoff is None:
        return question
    try:
        cutoff = date.fromisoformat(str(knowledge_cutoff))
    except (TypeError, ValueError):
        raise ValueError('knowledge_cutoff must be an explicit ISO date') from None
    matches = [m for pattern in _CUTOFF_CLAUSES for m in pattern.finditer(question)]
    for match in matches:
        try:
            declared = date.fromisoformat(match['date'])
        except ValueError:
            return None
        if declared != cutoff:
            return None
    chars = list(question)
    for match in matches:
        chars[match.start():match.end()] = ' ' * (match.end()-match.start())
    return ''.join(chars)


def explicit_periods(question, *, fiscal_periods=(), require_fiscal_mapping=False,
                     knowledge_cutoff=None):
    """Return supported absolute periods mentioned literally in the question."""
    question = _without_bound_cutoff(question, knowledge_cutoff)
    if question is None:
        return ()
    question = re.sub(r"([1-9]\d{3})\s*财年", r"FY\1", question)
    if _UNSUPPORTED.search(question):
        return ()
    spans, periods = [], []
    for match in re.finditer(r"\bFY\s*(?P<year>[1-9]\d{3})(?!\d|\.\d)(?:\s*Q(?P<quarter>[1-4]))?", question, re.I):
        matches = {Period.model_validate(item['period']) for item in fiscal_periods
                   if item.get('fiscal_year') == int(match['year'])
                   and item.get('fiscal_quarter') == (int(match['quarter']) if match['quarter'] else None)}
        if len(matches) == 1:
            periods.append(next(iter(matches)))
            spans.append(match.span())
        elif require_fiscal_mapping or matches:
            return ()
    for pattern in (_FORWARD, _REVERSE):
        for match in pattern.finditer(question):
            if any(lo <= match.start() < hi or lo <= match.end()-1 < hi for lo, hi in spans):
                continue
            year = int(match['year'])
            q = match['q'] or match['cq']
            quarter = int(q) if q.isdigit() else "一二三四".index(q) + 1
            end_month = quarter * 3
            periods.append(Period(kind="quarter", start=f"{year}-{'%02d' % (end_month-2)}-01",
                                  end=f"{year}-{end_month:02d}-{monthrange(year, end_month)[1]}"))
            spans.append(match.span())
    for match in re.finditer(_YEAR, question):
        if any(lo <= match.start() < hi for lo, hi in spans):
            continue
        year = int(match['year'])
        tail = question[match.end():]
        prefix = question[:match.start()]
        if not (re.match(r"\s*年", tail) or re.search(r"\b(?:FY\s*|(?:in|for|during|year)\s+)$", prefix, re.I)):
            continue
        # Unrecognized subannual expressions must not degrade into a full year.
        if re.match(r"\s*年?\s*(?:第|Q|[一二三四五六七八九十\d]+\s*(?:月|季度))", tail, re.I):
            return ()
        periods.append(Period(kind="year", start=f"{year}-01-01", end=f"{year}-12-31"))
    return tuple(dict.fromkeys(periods))


def validate_plan_periods(plan, allowed):
    periods = [r.period for r in plan.records if r.period is not None]
    periods.extend(p for c in plan.calculations for p in c.periods)
    if any(p not in allowed for p in periods):
        raise ValueError("plan period is not explicitly grounded in the question")
    if any(d.period_end not in {p.end for p in allowed} for d in plan.documents):
        raise ValueError("document reporting period is not explicitly grounded in the question")
