"""Portfolio buy/sell trade operations."""

from datetime import datetime

from services.portfolio_money import decimal_value, quantize


class PortfolioTradeError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def add_trade(
    execute_query,
    execute_insert_id,
    ensure_tables,
    resolve_stock,
    calculate_trade_fees,
    cash_amount_func,
    data,
):
    ensure_tables()
    trade_date = str(data.get("trade_date") or datetime.now().date()).strip()
    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError as exc:
        raise PortfolioTradeError("日期格式必须是 YYYY-MM-DD") from exc

    trade_type = str(data.get("trade_type") or "").strip().lower()
    if trade_type not in ("buy", "sell"):
        raise PortfolioTradeError("交易方向必须是买入或卖出")

    stock = resolve_stock(str(data.get("code", data.get("identifier", ""))).strip())
    if not stock:
        raise PortfolioTradeError("未找到匹配的股票，请输入代码或更准确的名称", 404)
    code = stock["code"]

    try:
        shares = float(data.get("shares"))
    except (TypeError, ValueError) as exc:
        raise PortfolioTradeError("交易股数必须是数字") from exc
    if shares <= 0:
        raise PortfolioTradeError("交易股数必须大于 0")

    try:
        price = float(data.get("price"))
    except (TypeError, ValueError) as exc:
        raise PortfolioTradeError("成交价必须是数字") from exc
    if price <= 0:
        raise PortfolioTradeError("成交价必须大于 0")

    note = str(data.get("note") or "").strip()[:255]
    position_rows = execute_query(
        "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
        (code,),
    )
    old_shares = float(position_rows[0]["shares"]) if position_rows else 0.0
    old_cost = float(position_rows[0]["cost_price"]) if position_rows and position_rows[0].get("cost_price") is not None else None

    amount = shares * price
    amount_dec = quantize(amount, "0.01")
    fees = calculate_trade_fees(amount_dec, trade_type, stock.get("market"))
    total_fee = fees["total_fee"]
    cash_delta_dec = -(amount_dec + total_fee) if trade_type == "buy" else amount_dec - total_fee
    cash_delta = float(cash_delta_dec)
    cash_amount = cash_amount_func()
    new_cash = cash_amount + cash_delta
    if new_cash < 0:
        raise PortfolioTradeError("现金不足，无法买入")

    realized_profit = None
    if trade_type == "buy":
        if old_shares > 0 and old_cost is None:
            raise PortfolioTradeError("这只股票已有持仓但缺少历史成本，无法继续自动计算成本价")
        new_shares = old_shares + shares
        buy_cost = float(amount_dec + total_fee)
        new_cost = ((old_shares * old_cost) + buy_cost) / new_shares if old_shares > 0 else buy_cost / shares
        execute_query(
            """INSERT INTO portfolio_positions (stock_code, shares, cost_price)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE shares=VALUES(shares), cost_price=VALUES(cost_price), updated_at=CURRENT_TIMESTAMP""",
            (code, round(new_shares, 4), round(new_cost, 4)),
            fetch=False,
        )
    else:
        if old_shares <= 0:
            raise PortfolioTradeError("当前没有这只股票的持仓，无法卖出")
        if shares > old_shares:
            raise PortfolioTradeError(f"卖出股数不能超过当前持仓 {old_shares:g} 股")
        new_shares = old_shares - shares
        sell_proceeds = float(amount_dec - total_fee)
        realized_profit = sell_proceeds - (old_cost * shares) if old_cost is not None else None
        new_cost = ((old_shares * old_cost) - sell_proceeds) / new_shares if new_shares > 0 and old_cost is not None else None
        if new_shares > 0:
            execute_query(
                "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                (round(new_shares, 4), round(new_cost, 4) if new_cost is not None else None, code),
                fetch=False,
            )
        else:
            execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

    trade_id = execute_insert_id(
        """INSERT INTO portfolio_trades
           (trade_date, stock_code, trade_type, shares, price, amount,
            commission, stamp_tax, transfer_fee, total_fee, cash_delta,
            shares_before, shares_after, cost_price_before, cost_price_after, realized_profit, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            trade_date,
            code,
            trade_type,
            round(shares, 4),
            round(price, 4),
            round(amount, 2),
            fees["commission"],
            fees["stamp_tax"],
            fees["transfer_fee"],
            fees["total_fee"],
            cash_delta_dec,
            round(old_shares, 4),
            round(new_shares, 4),
            round(old_cost, 4) if old_cost is not None else None,
            round(new_cost, 4) if new_cost is not None else None,
            round(realized_profit, 2) if realized_profit is not None else None,
            note,
        ),
    )
    flow_note = note or f"{stock['name']}({code}) {'买入' if trade_type == 'buy' else '卖出'}"
    execute_query(
        """INSERT INTO portfolio_cash_flows
           (flow_date, amount, flow_source, source_type, source_id, note)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (trade_date, cash_delta_dec, "trade", "trade", trade_id, flow_note[:255]),
        fetch=False,
    )
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (quantize(new_cash, "0.01"),),
        fetch=False,
    )
    return {
        "trade_id": trade_id,
        "stock_code": code,
        "trade_type": trade_type,
        "cash_delta": float(cash_delta_dec),
    }
