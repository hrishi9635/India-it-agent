"""Indian fiscal quarters: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar."""
from datetime import date, timedelta

MONTHS = {6: "Apr-Jun", 9: "Jul-Sep", 12: "Oct-Dec", 3: "Jan-Mar"}


def quarter_end_month(month: int) -> int:
    """Round any month to the quarter-end month it belongs to."""
    return {1: 3, 2: 3, 3: 3, 4: 6, 5: 6, 6: 6, 7: 9, 8: 9, 9: 9, 10: 12, 11: 12, 12: 12}[month]


def label(d) -> str:
    m = quarter_end_month(d.month)
    q = {6: 1, 9: 2, 12: 3, 3: 4}[m]
    fy = d.year + 1 if m in (6, 9, 12) else d.year
    return f"Q{q} FY{str(fy)[-2:]}"


def months_text(d) -> str:
    m = quarter_end_month(d.month)
    year = d.year
    return f"{MONTHS[m]} {year}"


def quarter_end_on_or_before(d: date) -> date:
    ends = []
    for y in (d.year - 1, d.year):
        ends += [date(y, 3, 31), date(y, 6, 30), date(y, 9, 30), date(y, 12, 31)]
    return max(e for e in ends if e <= d)


def target_quarter(today: date | None = None, lag_days: int = 5):
    """The quarter whose results are being announced now."""
    today = today or date.today()
    qe = quarter_end_on_or_before(today - timedelta(days=lag_days))
    return qe, label(qe)


def previous_quarter_end(qe: date) -> date:
    return quarter_end_on_or_before(qe - timedelta(days=40))
