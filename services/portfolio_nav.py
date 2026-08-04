"""Portfolio current state and NAV snapshot helpers."""

import json


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
