"""Build a reliable, period-aware context for the Munger chat.

The chat should receive the same reporting-period and core-profit definitions as
the stock detail pages.  This module deliberately keeps data preparation out of
the prompt-building code so that a style prompt cannot accidentally change the
financial meaning of a number.
"""

from __future__ import annotations

from datetime import datetime
import time
from threading import Lock
from typing import Any

from services.financial_metrics import (
    avg,
    cagr as financial_cagr,
    enrich_financial_summary_item,
    ratio_pct,
    to_float,
)
from services.financial_periods import (
    annual_report_rows,
    filter_usable_report_rows,
    latest_report_row,
    period_label,
    period_sort_key,
    same_period_last_year,
)
from services.market_data import fetch_realtime_quotes
from services.providers.tencent import quote_text
from services.stock_identity import quote_symbol


MARKET_CONTEXT_CACHE_TTL_SECONDS = 60
_market_context_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_market_context_cache_lock = Lock()


CUSTOM_FIELDS = (
    "total_revenue",
    "operate_profit",
    "parent_profit",
    "deducted_profit",
    "operate_cashflow",
    "roe",
    "deducted_roe",
    "roic",
    "total_assets",
    "total_equity",
    "total_shares",
    "basic_eps",
    "debt_ratio",
    "interest_bearing_debt_ratio",
)

INCOME_FIELDS = (
    "total_revenue",
    "operating_revenue",
    "operating_cost",
    "cost_of_revenue",
    "tax_surcharge",
    "selling_expense",
    "admin_expense",
    "finance_expense",
    "rd_expense",
    "finance_interest_income",
    "interest_expense",
    "fee_commission_expense",
    "fair_value_change",
    "invest_income",
    "operating_profit",
    "nonop_income",
    "nonop_expense",
    "total_profit",
    "income_tax",
    "net_profit",
    "parent_net_profit",
)

BALANCE_FIELDS = (
    "monetary_funds",
    "accounts_receivable",
    "inventory",
    "fixed_assets",
    "goodwill",
    "total_liabilities",
    "parent_equity",
)

CASH_FIELDS = (
    "cf_oper_net",
    "cf_buy_assets",
    "cf_invest_net",
    "cf_invest_income",
    "cf_finance_net",
    "cf_repay_debt",
    "cf_borrow",
    "cf_dividend_interest",
)


def _context_query():
    income_select = ",\n               ".join(
        f"inc.{field} AS inc_{field}" for field in INCOME_FIELDS
    )
    balance_select = ",\n               ".join(
        f"bs.{field} AS bs_{field}" for field in BALANCE_FIELDS
    )
    cash_select = ",\n               ".join(
        f"cfs.{field} AS cash_{field}" for field in CASH_FIELDS
    )
    custom_select = ",\n               ".join(f"cf.{field}" for field in CUSTOM_FIELDS)
    return f"""
        SELECT cf.fiscal_year, cf.report_period,
               {custom_select},
               d.dividend_amount, d.dividend_per_share,
               {income_select},
               {balance_select},
               {cash_select}
        FROM custom_financials cf
        LEFT JOIN dividends d
          ON cf.stock_code = d.stock_code
         AND cf.fiscal_year = d.fiscal_year
        LEFT JOIN income_statements inc
          ON cf.stock_code = inc.stock_code
         AND cf.fiscal_year = inc.fiscal_year
         AND cf.report_period = inc.report_period
        LEFT JOIN balance_sheets bs
          ON cf.stock_code = bs.stock_code
         AND cf.fiscal_year = bs.fiscal_year
         AND cf.report_period = bs.report_period
        LEFT JOIN cash_flows cfs
          ON cf.stock_code = cfs.stock_code
         AND cf.fiscal_year = cfs.fiscal_year
         AND cf.report_period = cfs.report_period
        WHERE cf.stock_code = %s
        ORDER BY cf.fiscal_year ASC,
                 FIELD(cf.report_period, 'Q1', 'Q2', 'Q3', 'FY') ASC
    """


def _as_number(value):
    number = to_float(value)
    return round(number, 6) if number is not None else None


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    item = {
        "fiscal_year": int(row["fiscal_year"]),
        "report_period": row.get("report_period") or "FY",
    }
    for field in CUSTOM_FIELDS:
        item[field] = _as_number(row.get(field))
    for field in INCOME_FIELDS:
        item[f"inc_{field}"] = _as_number(row.get(f"inc_{field}"))
    for field in BALANCE_FIELDS:
        item[f"bs_{field}"] = _as_number(row.get(f"bs_{field}"))
    for field in CASH_FIELDS:
        item[f"cash_{field}"] = _as_number(row.get(f"cash_{field}"))
    item["dividend_amount"] = _as_number(row.get("dividend_amount"))
    item["dividend_per_share"] = _as_number(row.get("dividend_per_share"))
    return enrich_financial_summary_item(item, row)


def _parse_quote_fields(text: str) -> dict[str, Any]:
    if not text or '"' not in text:
        return {}
    try:
        fields = text.split('"')[1].split("~")
    except (IndexError, AttributeError):
        return {}

    def number(index):
        if len(fields) <= index or fields[index] in (None, "", "-"):
            return None
        try:
            return float(fields[index])
        except (TypeError, ValueError):
            return None

    quote = {
        "name": fields[1].strip() if len(fields) > 1 else None,
        "price": number(3),
        "previous_close": number(4),
        "day_change": number(31),
        "day_change_pct": number(32),
        "quote_time": fields[30].strip() if len(fields) > 30 else None,
        "pe_ttm": number(39),
        "pb": number(43),
        "market_cap": number(45),
    }
    return {key: value for key, value in quote.items() if value is not None}


def _load_market_context(stock: dict[str, Any]) -> dict[str, Any]:
    code = str(stock.get("code") or "")
    market = stock.get("market")
    cache_key = (code, str(market or ""), str(stock.get("pe_ttm") or ""))
    now = time.monotonic()
    with _market_context_cache_lock:
        cached = _market_context_cache.get(cache_key)
        if cached and now - cached[0] < MARKET_CONTEXT_CACHE_TTL_SECONDS:
            return dict(cached[1])
        if cached:
            _market_context_cache.pop(cache_key, None)

    result: dict[str, Any] = {
        "price": None,
        "day_change": None,
        "day_change_pct": None,
        "pe_ttm": _as_number(stock.get("pe_ttm")),
        "pb": None,
        "market_cap": None,
        "source": "本地股票表",
    }
    try:
        quotes = fetch_realtime_quotes(
            [{"code": code, "market": market}],
            quote_symbol,
        )
        result.update(quotes.get(code) or {})
    except Exception:
        pass

    try:
        direct = _parse_quote_fields(quote_text(quote_symbol(code, market), timeout=8))
        result.update({key: value for key, value in direct.items() if value is not None})
        if direct:
            result["source"] = "腾讯实时行情"
    except Exception:
        pass

    for key in ("price", "day_change", "day_change_pct", "pe_ttm", "pb", "market_cap"):
        if result.get(key) is not None:
            result[key] = round(float(result[key]), 4)
    result["quote_time"] = result.get("quote_time") or None
    with _market_context_cache_lock:
        _market_context_cache[cache_key] = (time.monotonic(), dict(result))
        if len(_market_context_cache) > 256:
            oldest_key = min(_market_context_cache, key=lambda key: _market_context_cache[key][0])
            _market_context_cache.pop(oldest_key, None)
    return dict(result)


def _load_graham_context(execute_query, stock_code: str, latest_annual: dict | None, latest_period: dict | None):
    try:
        rows = execute_query(
            """SELECT growth_rate, payout_ratio, risk_free_rate, expected_profit
               FROM graham_valuations WHERE stock_code=%s""",
            (stock_code,),
        )
    except Exception:
        return {}
    if not rows:
        return {}
    raw = rows[0]
    values = {key: _as_number(raw.get(key)) for key in (
        "growth_rate", "payout_ratio", "risk_free_rate", "expected_profit"
    )}
    if values.get("expected_profit") is None:
        values["expected_profit"] = (latest_annual or latest_period or {}).get("parent_profit")
    if values.get("payout_ratio") is None or values.get("risk_free_rate") in (None, 0):
        return {"configured": values}
    fair_valuation = values["payout_ratio"] / values["risk_free_rate"] + (values.get("growth_rate") or 0)
    shares = (latest_period or {}).get("total_shares") or (latest_annual or {}).get("total_shares")
    fair_price = None
    if values.get("expected_profit") is not None and shares:
        fair_price = fair_valuation * values["expected_profit"] / shares
    return {
        "configured": values,
        "fair_valuation": round(fair_valuation, 2),
        "fair_price": round(fair_price, 2) if fair_price is not None else None,
    }


def build_financial_context(
    execute_query,
    stock_code: str,
    *,
    include_market: bool = True,
) -> dict[str, Any]:
    """Return a normalized, period-aware context for one stock."""
    stock_rows = execute_query(
        """SELECT code, name, market, industry, list_date, status, pe_ttm, dividend_yield
           FROM stocks WHERE code=%s""",
        (stock_code,),
    )
    if not stock_rows:
        return {
            "info": {"code": stock_code},
            "all_rows": [],
            "rows": [],
            "annual_rows": [],
            "latest_period": None,
            "yoy_base": None,
            "latest_annual": None,
            "latest": None,
            "warnings": ["未找到股票基础信息"],
            "market": {},
        }

    info = dict(stock_rows[0])
    raw_rows = execute_query(_context_query(), (stock_code,))
    data = [_normalise_row(dict(row)) for row in raw_rows]
    current_year = datetime.now().year
    has_current_year_fy = any(
        int(row["fiscal_year"]) >= current_year and row.get("report_period") == "FY"
        for row in data
    )
    usable = filter_usable_report_rows(
        data,
        current_year=current_year,
        allow_fallback=False,
    )
    usable = sorted(usable, key=period_sort_key)
    annual_rows = sorted(annual_report_rows(usable), key=period_sort_key)
    latest_period = latest_report_row(usable)
    yoy_base = same_period_last_year(usable, latest_period)
    latest_annual = annual_rows[-1] if annual_rows else None
    latest = latest_annual or latest_period
    recent_annual = annual_rows[-5:]

    warnings = []
    if has_current_year_fy:
        warnings.append(f"已忽略 {current_year} 年疑似误标的年报数据")
    if not latest_period:
        warnings.append("没有可用的季度或年报财务数据")
    if latest_period and not yoy_base:
        warnings.append("缺少去年同报告期，无法计算同比")
    if not annual_rows:
        warnings.append("没有可用的完整年报，长期 CAGR 不计算")
    if data and not any(row.get("inc_operating_revenue") is not None for row in data):
        warnings.append("利润表明细不足，核心利润使用财报摘要口径")

    cash_quality_values = []
    for row in recent_annual:
        profit = row.get("parent_profit")
        cashflow = row.get("operate_cashflow")
        if profit not in (None, 0) and cashflow is not None:
            cash_quality_values.append(cashflow / profit)
    positive_cash_quality = (
        round(sum(value > 0.7 for value in cash_quality_values) / len(cash_quality_values) * 100)
        if cash_quality_values else 0
    )
    roe_avg = avg([row.get("roe") for row in recent_annual])
    roe_values = [row.get("roe") for row in annual_rows if row.get("roe") is not None]
    roe_trend = (
        "上升" if len(roe_values) >= 3 and roe_values[-1] > roe_values[0]
        else "下降" if len(roe_values) >= 3 and roe_values[-1] < roe_values[0]
        else "平稳"
    )
    cagr_value = None
    if len(annual_rows) >= 2:
        first = annual_rows[0]
        span = int(latest_annual["fiscal_year"]) - int(first["fiscal_year"])
        cagr_value = financial_cagr(first.get("parent_profit"), latest_annual.get("parent_profit"), span)

    market = _load_market_context(info) if include_market else {
        "source": "纯框架问题，未加载实时行情",
        "quote_time": None,
    }
    graham = _load_graham_context(execute_query, stock_code, latest_annual, latest_period)
    market["graham"] = graham

    return {
        "info": info,
        "all_rows": usable,
        "rows": annual_rows[-10:],
        "annual_rows": annual_rows,
        "years": len(annual_rows),
        "latest_period": latest_period,
        "yoy_base": yoy_base,
        "latest_annual": latest_annual,
        "latest": latest,
        "roe_avg_5y": round(roe_avg, 2) if roe_avg is not None else None,
        "roe_trend": roe_trend,
        "cf_quality": positive_cash_quality,
        "cagr": round(cagr_value, 2) if cagr_value is not None else None,
        "market": market,
        "warnings": warnings,
        "period_note": period_label(latest_period["fiscal_year"], latest_period.get("report_period")) if latest_period else None,
        "yoy_note": (
            f"{period_label(latest_period['fiscal_year'], latest_period.get('report_period'))} vs "
            f"{period_label(yoy_base['fiscal_year'], yoy_base.get('report_period'))}"
            if latest_period and yoy_base else None
        ),
    }
