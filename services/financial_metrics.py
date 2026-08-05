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


def ratio_pct(numerator, denominator, *, require_positive_denominator=False, ndigits=2):
    numerator = to_float(numerator)
    denominator = to_float(denominator)
    if numerator is None or denominator in (None, 0):
        return None
    if require_positive_denominator and denominator <= 0:
        return None
    return round(numerator / denominator * 100, ndigits)


def debt_ratio(total_assets, total_equity, debt_ratio_raw=None, ndigits=2):
    raw = to_float(debt_ratio_raw)
    if raw is not None:
        return round(raw, ndigits)
    assets = to_float(total_assets)
    equity = to_float(total_equity)
    if assets is None or equity is None or assets <= 0:
        return None
    return round((assets - equity) / assets * 100, ndigits)


def dividend_payout_ratio(dividend_amount, parent_profit, ndigits=2):
    return ratio_pct(dividend_amount, parent_profit, require_positive_denominator=True, ndigits=ndigits)


def dividend_yield(dividend_per_share, price, ndigits=2):
    dividend = to_float(dividend_per_share)
    price = to_float(price)
    if dividend is None or dividend <= 0 or price is None or price <= 0:
        return None
    return round(dividend / price * 100, ndigits)


def goodwill_to_parent_equity(goodwill, parent_equity, ndigits=2):
    return ratio_pct(goodwill, parent_equity, ndigits=ndigits)


def free_cashflow(operating_cashflow, capital_expenditure, ndigits=4):
    operating_cashflow = to_float(operating_cashflow)
    capital_expenditure = to_float(capital_expenditure)
    if operating_cashflow is None or capital_expenditure is None:
        return None
    return round(operating_cashflow - capital_expenditure, ndigits)


def gross_margin(revenue, cost, ndigits=2):
    revenue = to_float(revenue)
    cost = to_float(cost)
    if revenue in (None, 0) or cost is None:
        return None
    return round((revenue - cost) / revenue * 100, ndigits)


def income_revenue_from_aliases(row, prefix="inc_"):
    return to_float(row.get(f"{prefix}total_revenue")) or to_float(row.get(f"{prefix}operating_revenue"))


def income_gross_margin_from_aliases(row, prefix="inc_", ndigits=2):
    revenue = to_float(row.get(f"{prefix}operating_revenue")) or to_float(row.get(f"{prefix}total_revenue"))
    cost = to_float(row.get(f"{prefix}cost_of_revenue"))
    if cost is None:
        cost = to_float(row.get(f"{prefix}operating_cost"))
    return gross_margin(revenue, cost, ndigits=ndigits)


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
    metrics = summary_profitability_metrics(
        revenue=item.get("total_revenue"),
        operate_profit=item.get("operate_profit"),
        parent_profit=item.get("parent_profit"),
        operate_cashflow=item.get("operate_cashflow"),
        source_row=source_row,
        ndigits=6,
    )
    item["operate_profit"] = metrics["operate_profit"]
    item["core_profit_rate"] = metrics["core_profit_rate"]
    item["net_profit_rate"] = metrics["net_profit_rate"]
    item["cashflow_to_profit"] = metrics["cashflow_to_profit"]
    return item


def summary_profitability_metrics(
    *,
    revenue,
    operate_profit,
    parent_profit,
    operate_cashflow,
    source_row=None,
    income_prefix="inc_",
    ndigits=2,
):
    core_profit = to_float(operate_profit)
    core_revenue = to_float(revenue)
    has_income_core = False
    if source_row is not None:
        derived_core_profit, derived_revenue, has_income_core = core_profit_from_income_aliases(source_row, income_prefix)
        if has_income_core:
            core_profit = derived_core_profit
            core_revenue = derived_revenue

    return {
        "operate_profit": core_profit,
        "core_profit_rate": ratio_pct(core_profit, core_revenue, ndigits=ndigits),
        "net_profit_rate": ratio_pct(parent_profit, revenue, ndigits=ndigits),
        "cashflow_to_profit": ratio_pct(
            operate_cashflow,
            parent_profit,
            require_positive_denominator=True,
            ndigits=ndigits,
        ),
        "has_income_core": has_income_core,
    }
