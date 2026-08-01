"""Shared financial metric calculations."""


def to_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def round_or_none(value, ndigits=2):
    return round(value, ndigits) if value is not None else None


def avg(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def pct_change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev) * 100


def cagr(old, new, years):
    if old is None or new is None or years <= 0 or old <= 0 or new <= 0:
        return None
    return ((new / old) ** (1 / years) - 1) * 100


def core_profit_from_income_aliases(row, prefix="inc_"):
    """Calculate core profit using the income-statement/Sankey operating logic."""

    def value(field):
        return to_float(row.get(f"{prefix}{field}")) or 0

    def positive(field):
        return max(value(field), 0)

    revenue = value("total_revenue") or value("operating_revenue")
    has_core_fields = any(
        row.get(f"{prefix}{field}") is not None
        for field in (
            "total_revenue", "operating_revenue", "cost_of_revenue",
            "selling_expense", "admin_expense", "finance_expense", "rd_expense",
        )
    )
    if not has_core_fields:
        return None, revenue, False

    finance_expense = value("finance_expense")
    finance_interest_income = positive("finance_interest_income")
    finance_expense_before_interest_income = (
        max(finance_expense + finance_interest_income, 0)
        if finance_interest_income > 0 else max(finance_expense, 0)
    )
    period_expense = (
        positive("selling_expense")
        + positive("admin_expense")
        + positive("rd_expense")
        + finance_expense_before_interest_income
    )
    gross_profit = max(
        revenue
        - positive("cost_of_revenue")
        - positive("interest_expense")
        - positive("fee_commission_expense"),
        0,
    )
    core_profit = gross_profit - period_expense - positive("tax_surcharge")
    return core_profit, revenue, True


def enrich_financial_summary_item(item, source_row=None):
    revenue = item.get("total_revenue")
    parent_profit = item.get("parent_profit")
    operate_profit = item.get("operate_profit")
    operate_cashflow = item.get("operate_cashflow")

    core_profit = None
    core_revenue = None
    has_income_core = False
    if source_row is not None:
        core_profit, core_revenue, has_income_core = core_profit_from_income_aliases(source_row)
    if has_income_core:
        item["operate_profit"] = core_profit
        item["core_profit_rate"] = core_profit / core_revenue * 100 if core_revenue else None
    else:
        item["core_profit_rate"] = operate_profit / revenue * 100 if revenue else None

    item["net_profit_rate"] = parent_profit / revenue * 100 if revenue else None
    item["cashflow_to_profit"] = (
        operate_cashflow / parent_profit * 100
        if parent_profit and parent_profit > 0 and operate_cashflow is not None else None
    )
    return item
