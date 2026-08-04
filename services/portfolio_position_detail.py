"""Single portfolio position detail and custom dividend helpers."""

from services.portfolio_money import quantize


class PortfolioPositionError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def position_detail(
    execute_query,
    ensure_tables,
    latest_dividend_per_share,
    currency_for_market,
    code,
):
    ensure_tables()
    rows = execute_query(
        """SELECT p.stock_code, p.shares, p.cost_price, p.custom_dividend_per_share,
                  s.name, s.market, s.industry
           FROM portfolio_positions p
           LEFT JOIN stocks s ON s.code = p.stock_code
           WHERE p.stock_code=%s
           LIMIT 1""",
        (code,),
    )
    if not rows:
        return {"ok": True, "held": False, "code": code}

    r = rows[0]
    shares = float(r["shares"])
    dividends = latest_dividend_per_share([code]).get(code, {})
    custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
    auto_dividend = dividends.get("dividend_per_share")
    dividend_per_share = custom_dividend if custom_dividend is not None else auto_dividend
    return {
        "ok": True,
        "held": True,
        "code": r["stock_code"],
        "name": r.get("name") or r["stock_code"],
        "market": r.get("market") or "SH",
        "industry": r.get("industry"),
        "shares": shares,
        "cost_price": round(float(r["cost_price"]), 4) if r.get("cost_price") is not None else None,
        "cost_price_currency": currency_for_market(r.get("market")),
        "custom_dividend_per_share": round(custom_dividend, 2) if custom_dividend is not None else None,
        "auto_dividend_per_share": round(auto_dividend, 3) if auto_dividend is not None else None,
        "dividend_per_share": round(dividend_per_share, 2) if dividend_per_share is not None else None,
        "dividend_year": dividends.get("fiscal_year"),
        "dividend_source": "custom" if custom_dividend is not None else "auto",
    }


def update_custom_dividend(execute_query, ensure_tables, code, value):
    ensure_tables()
    try:
        value = quantize(value, "0.01")
    except Exception as exc:
        raise PortfolioPositionError("每股分红必须是数字") from exc
    if value < 0:
        raise PortfolioPositionError("每股分红不能小于 0")

    rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
    if not rows:
        raise PortfolioPositionError("持仓中没有这只股票", 404)
    execute_query(
        "UPDATE portfolio_positions SET custom_dividend_per_share=%s WHERE stock_code=%s",
        (value, code),
        fetch=False,
    )
    return value


def reset_custom_dividend(execute_query, ensure_tables, code):
    ensure_tables()
    position_rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
    if not position_rows:
        raise PortfolioPositionError("持仓中没有这只股票", 404)
    execute_query(
        "UPDATE portfolio_positions SET custom_dividend_per_share=NULL WHERE stock_code=%s",
        (code,),
        fetch=False,
    )
