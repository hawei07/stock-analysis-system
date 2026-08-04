"""Portfolio current state and NAV snapshot helpers."""

import json
from datetime import datetime


def current_state(
    execute_query,
    ensure_tables,
    cash_amount,
    fee_config_payload,
    fill_missing_stock_industries,
    fetch_realtime_quotes,
    latest_dividend_per_share,
    currency_for_market,
    exchange_rate_to_cny,
):
    ensure_tables()
    cash = cash_amount()
    rows = execute_query(
        """SELECT p.id, p.stock_code, p.shares, p.cost_price, p.custom_dividend_per_share,
                  s.name, s.market, s.industry
           FROM portfolio_positions p
           JOIN stocks s ON s.code = p.stock_code
           ORDER BY p.updated_at DESC, p.id DESC"""
    )
    fill_missing_stock_industries(rows)
    positions = []
    if not rows:
        return {
            "positions": [],
            "fee_config": fee_config_payload(),
            "summary": {
                "total_market_value": 0,
                "cash_amount": round(cash, 2),
                "total_asset_value": round(cash, 2),
                "cash_allocation_pct": 100.0 if cash > 0 else 0,
                "total_cost_value": 0,
                "unrealized_profit": None,
                "unrealized_profit_pct": None,
                "expected_dividend": 0,
                "count": 0,
                "industry_allocations": [],
            },
        }

    stock_refs = [{"code": r["stock_code"], "market": r["market"]} for r in rows]
    quotes = fetch_realtime_quotes(stock_refs)
    prices = {
        code: quote.get("price")
        for code, quote in quotes.items()
        if quote.get("price") is not None
    }
    dividends = latest_dividend_per_share([r["stock_code"] for r in rows])
    exchange_rates = {}
    total_market_value = 0.0
    total_cost_value = 0.0
    total_costed_market_value = 0.0
    expected_dividend = 0.0
    total_day_change_value = 0.0
    industry_values = {}

    for r in rows:
        code = r["stock_code"]
        shares = float(r["shares"])
        cost_price = float(r["cost_price"]) if r.get("cost_price") is not None else None
        price = prices.get(code)
        quote = quotes.get(code, {})
        currency = currency_for_market(r.get("market"))
        fx = exchange_rates.get(currency)
        if fx is None:
            fx = exchange_rate_to_cny(currency)
            exchange_rates[currency] = fx
        fx_rate = float(fx["rate"]) if fx and fx.get("rate") is not None else None
        div = dividends.get(code, {})
        custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
        dividend_per_share = custom_dividend if custom_dividend is not None else div.get("dividend_per_share")
        original_market_value = shares * price if price is not None else None
        original_day_change = shares * quote.get("day_change") if quote.get("day_change") is not None else None
        day_change_value = original_day_change * fx_rate if original_day_change is not None and fx_rate is not None else None
        market_value = original_market_value * fx_rate if original_market_value is not None and fx_rate is not None else None
        original_cost_value = shares * cost_price if cost_price is not None else None
        cost_value = original_cost_value * fx_rate if original_cost_value is not None and fx_rate is not None else None
        unrealized_profit = market_value - cost_value if market_value is not None and cost_value is not None else None
        unrealized_profit_pct = unrealized_profit / cost_value * 100 if unrealized_profit is not None and cost_value and cost_value > 0 else None
        original_dividend_amount = shares * dividend_per_share if dividend_per_share is not None else None
        dividend_amount = original_dividend_amount * fx_rate if original_dividend_amount is not None and fx_rate is not None else None
        if market_value is not None:
            total_market_value += market_value
            industry = r.get("industry") or "未分类"
            industry_values[industry] = industry_values.get(industry, 0.0) + market_value
        if day_change_value is not None:
            total_day_change_value += day_change_value
        if cost_value is not None:
            total_cost_value += cost_value
            if market_value is not None:
                total_costed_market_value += market_value
        if dividend_amount is not None:
            expected_dividend += dividend_amount
        positions.append({
            "id": r["id"],
            "code": code,
            "name": r["name"],
            "market": r["market"],
            "industry": r.get("industry"),
            "shares": shares,
            "cost_price": round(cost_price, 4) if cost_price is not None else None,
            "cost_price_currency": currency,
            "price": round(price, 2) if price is not None else None,
            "day_change": round(float(quote.get("day_change")), 2) if quote.get("day_change") is not None else None,
            "day_change_pct": round(float(quote.get("day_change_pct")), 2) if quote.get("day_change_pct") is not None else None,
            "day_change_value": round(day_change_value, 2) if day_change_value is not None else None,
            "price_currency": currency,
            "fx_rate_to_cny": round(fx_rate, 6) if fx_rate is not None else None,
            "fx_rate_date": fx.get("date") if fx else None,
            "fx_rate_source": fx.get("source") if fx else None,
            "original_market_value": round(original_market_value, 2) if original_market_value is not None else None,
            "original_market_value_currency": currency,
            "market_value": round(market_value, 2) if market_value is not None else None,
            "market_value_currency": "CNY",
            "original_cost_value": round(original_cost_value, 2) if original_cost_value is not None else None,
            "original_cost_value_currency": currency,
            "cost_value": round(cost_value, 2) if cost_value is not None else None,
            "cost_value_currency": "CNY",
            "unrealized_profit": round(unrealized_profit, 2) if unrealized_profit is not None else None,
            "unrealized_profit_pct": round(unrealized_profit_pct, 2) if unrealized_profit_pct is not None else None,
            "dividend_per_share": round(dividend_per_share, 2) if dividend_per_share is not None else None,
            "dividend_year": div.get("fiscal_year"),
            "auto_dividend_per_share": round(div.get("dividend_per_share"), 3) if div.get("dividend_per_share") is not None else None,
            "custom_dividend_per_share": round(custom_dividend, 2) if custom_dividend is not None else None,
            "dividend_source": "custom" if custom_dividend is not None else "auto",
            "original_expected_dividend": round(original_dividend_amount, 2) if original_dividend_amount is not None else None,
            "original_expected_dividend_currency": currency,
            "expected_dividend": round(dividend_amount, 2) if dividend_amount is not None else None,
            "expected_dividend_currency": "CNY",
        })

    total_asset_value = total_market_value + cash
    for p in positions:
        value = p.get("market_value")
        p["allocation_pct"] = round(value / total_asset_value * 100, 2) if value is not None and total_asset_value > 0 else None
    positions.sort(key=lambda p: p.get("allocation_pct") or 0, reverse=True)

    industry_allocations = [
        {
            "industry": industry,
            "market_value": round(value, 2),
            "allocation_pct": round(value / total_market_value * 100, 2) if total_market_value > 0 else 0,
        }
        for industry, value in sorted(industry_values.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "positions": positions,
        "fee_config": fee_config_payload(),
        "summary": {
            "total_market_value": round(total_market_value, 2),
            "cash_amount": round(cash, 2),
            "total_asset_value": round(total_asset_value, 2),
            "cash_allocation_pct": round(cash / total_asset_value * 100, 2) if total_asset_value > 0 else 0,
            "total_cost_value": round(total_cost_value, 2),
            "unrealized_profit": round(total_costed_market_value - total_cost_value, 2) if total_cost_value > 0 else None,
            "unrealized_profit_pct": round((total_costed_market_value - total_cost_value) / total_cost_value * 100, 2) if total_cost_value > 0 else None,
            "expected_dividend": round(expected_dividend, 2),
            "day_change_value": round(total_day_change_value, 2),
            "day_change_pct": round(total_day_change_value / total_market_value * 100, 2) if total_market_value > 0 else None,
            "count": len(positions),
            "currency": "CNY",
            "exchange_rates": {
                f"{currency}_CNY": {
                    "rate": round(info["rate"], 6) if info and info.get("rate") is not None else None,
                    "date": info.get("date") if info else None,
                    "source": info.get("source") if info else None,
                    "cached": bool(info.get("cached")) if info else False,
                    "stale": bool(info.get("stale")) if info else False,
                }
                for currency, info in exchange_rates.items()
                if currency != "CNY"
            },
            "industry_allocations": industry_allocations[:8],
        },
    }


def save_snapshot(execute_query, current_state_func):
    state = current_state_func()
    summary = state["summary"]
    execute_query(
        """INSERT INTO portfolio_nav_snapshots
           (snapshot_date, total_market_value, expected_dividend, cash_amount, total_asset_value, positions_json)
           VALUES (CURDATE(), %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             total_market_value=VALUES(total_market_value),
             expected_dividend=VALUES(expected_dividend),
             cash_amount=VALUES(cash_amount),
             total_asset_value=VALUES(total_asset_value),
             positions_json=VALUES(positions_json),
             updated_at=CURRENT_TIMESTAMP""",
        (
            summary["total_market_value"],
            summary["expected_dividend"],
            summary["cash_amount"],
            summary["total_asset_value"],
            json.dumps(state["positions"], ensure_ascii=False),
        ),
        fetch=False,
    )
    return state


def history(execute_query, ensure_tables, current_state_func, include_live=False):
    ensure_tables()
    rows = execute_query(
        """SELECT snapshot_date, total_market_value, expected_dividend,
                  cash_amount, total_asset_value
           FROM portfolio_nav_snapshots
           ORDER BY snapshot_date ASC"""
    )
    if include_live:
        summary = current_state_func()["summary"]
        today = datetime.now().date().isoformat()
        live_row = {
            "snapshot_date": today,
            "total_market_value": summary["total_market_value"],
            "expected_dividend": summary["expected_dividend"],
            "cash_amount": summary["cash_amount"],
            "total_asset_value": summary["total_asset_value"],
        }
        rows = [r for r in rows if str(r["snapshot_date"]) != today]
        rows.append(live_row)

    flow_rows = execute_query(
        """SELECT flow_date,
                  SUM(amount) AS net_flow,
                  SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS flow_in,
                  SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS flow_out
           FROM portfolio_cash_flows
           WHERE flow_source='external' AND is_void=0
           GROUP BY flow_date"""
    )
    flow_by_date = {
        str(r["flow_date"]): {
            "net": float(r["net_flow"] or 0),
            "in": float(r["flow_in"] or 0),
            "out": float(r["flow_out"] or 0),
        }
        for r in flow_rows
    }

    nav_index = None
    prev_value = None
    cumulative_in = 0.0
    cumulative_out = 0.0
    cumulative_return = 0.0
    result = []
    for r in rows:
        date_str = str(r["snapshot_date"])
        value = float(r.get("total_asset_value") or r["total_market_value"])
        flow = flow_by_date.get(date_str, {"net": 0.0, "in": 0.0, "out": 0.0})
        net_flow = flow["net"]
        cumulative_in += flow["in"]
        cumulative_out += flow["out"]
        daily_return = 0.0
        if nav_index is None:
            nav_index = 1.0 if value > 0 else None
        elif prev_value and prev_value > 0:
            adjusted_value = max(0.0, value - net_flow)
            daily_return = value - prev_value - net_flow
            cumulative_return += daily_return
            nav_index = nav_index * (adjusted_value / prev_value)

        prev_nav_index = result[-1]["nav_index"] if result else None
        nav_change_pct = (
            (nav_index / prev_nav_index - 1) * 100
            if nav_index is not None and prev_nav_index not in (None, 0)
            else None
        )
        result.append({
            "date": date_str,
            "total_market_value": round(value, 2),
            "stock_market_value": round(float(r["total_market_value"]), 2),
            "cash_amount": round(float(r.get("cash_amount") or 0), 2),
            "total_asset_value": round(value, 2),
            "net_flow": round(net_flow, 2),
            "flow_in": round(flow["in"], 2),
            "flow_out": round(flow["out"], 2),
            "cumulative_in": round(cumulative_in, 2),
            "cumulative_out": round(cumulative_out, 2),
            "daily_return": round(daily_return, 2),
            "cumulative_return": round(cumulative_return, 2),
            "expected_dividend": round(float(r["expected_dividend"]), 2),
            "nav_index": round(nav_index, 4) if nav_index is not None else None,
            "nav_change_pct": round(nav_change_pct, 2) if nav_change_pct is not None else None,
        })
        prev_value = value

    return result
