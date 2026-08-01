"""Shared financial reporting-period helpers."""

from datetime import datetime


PERIOD_ORDER = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}
PERIOD_LABELS = {"Q1": "一季报", "Q2": "中报", "Q3": "三季报", "FY": "年报"}


def period_label(year, period):
    return f"{year} {PERIOD_LABELS.get(period, period or '')}".strip()


def period_sort_key(row):
    return (int(row["fiscal_year"]), PERIOD_ORDER.get(row.get("report_period"), 0))


def filter_usable_report_rows(rows, current_year=None):
    """Ignore current-year FY rows because they are usually mislabelled quarterly data."""
    if current_year is None:
        current_year = datetime.now().year
    usable = [
        r for r in rows
        if not (r.get("report_period") == "FY" and int(r["fiscal_year"]) >= current_year)
    ]
    return usable or list(rows)


def latest_report_row(rows):
    return max(rows, key=period_sort_key) if rows else None


def same_period_last_year(rows, row):
    if not row:
        return None
    lookup = {
        (int(r["fiscal_year"]), r.get("report_period")): r
        for r in rows
    }
    return lookup.get((int(row["fiscal_year"]) - 1, row.get("report_period")))


def annual_report_rows(rows):
    return [r for r in rows if r.get("report_period") == "FY"]


def cagr_start_row(annual_rows, latest_row, cagr_years=None):
    if not annual_rows or not latest_row:
        return None
    if not cagr_years:
        return annual_rows[0]
    target_year = int(latest_row["fiscal_year"]) - int(cagr_years)
    candidates = [r for r in annual_rows if int(r["fiscal_year"]) >= target_year]
    return candidates[0] if candidates else annual_rows[0]
