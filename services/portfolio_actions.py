"""Portfolio corporate action operations."""

from datetime import datetime
from decimal import Decimal

from services.portfolio_money import decimal_value, quantize


class PortfolioActionError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code


def add_corporate_action(
    execute_query,
    execute_insert_id,
    ensure_tables,
    resolve_stock,
    cash_amount_func,
    data,
):
    ensure_tables()
    action_date = str(data.get("action_date") or datetime.now().date()).strip()
    try:
        datetime.strptime(action_date, "%Y-%m-%d")
    except ValueError as exc:
        raise PortfolioActionError("日期格式必须是 YYYY-MM-DD") from exc

    action_type = str(data.get("action_type") or "").strip().lower()
    if action_type not in ("cash_dividend", "bonus_share", "rights_issue"):
        raise PortfolioActionError("权益类型必须是现金分红、送股/转增或配股")

    stock = resolve_stock(str(data.get("code", data.get("identifier", ""))).strip())
    if not stock:
        raise PortfolioActionError("未找到匹配的股票，请输入代码或更准确的名称", 404)
    code = stock["code"]

    position_rows = execute_query(
        "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
        (code,),
    )
    if not position_rows:
        raise PortfolioActionError("当前没有这只股票的持仓，无法记录权益事件")
    old_shares = decimal_value(position_rows[0]["shares"])
    old_cost = decimal_value(position_rows[0]["cost_price"]) if position_rows[0].get("cost_price") is not None else None
    if old_shares <= 0 or old_cost is None:
        raise PortfolioActionError("这只股票缺少有效持仓或成本，无法记录权益事件")

    note = str(data.get("note") or "").strip()[:255]
    cash_amount = Decimal("0.00")
    action_shares = Decimal("0.0000")
    price = None
    amount = Decimal("0.00")
    cash_delta = Decimal("0.00")
    new_shares = old_shares
    new_cost = old_cost

    if action_type == "cash_dividend":
        raw_cash = data.get("cash_amount")
        if raw_cash in (None, ""):
            try:
                cash_amount = decimal_value(data.get("dividend_per_share")) * old_shares
            except Exception as exc:
                raise PortfolioActionError("现金分红金额必须是数字") from exc
        else:
            try:
                cash_amount = decimal_value(raw_cash)
            except Exception as exc:
                raise PortfolioActionError("现金分红金额必须是数字") from exc
        if cash_amount <= 0:
            raise PortfolioActionError("现金分红金额必须大于 0")
        cash_amount = quantize(cash_amount, "0.01")
        amount = cash_amount
        cash_delta = cash_amount
        new_cost = ((old_shares * old_cost) - cash_amount) / old_shares
    elif action_type == "bonus_share":
        try:
            action_shares = decimal_value(data.get("shares"))
        except Exception as exc:
            raise PortfolioActionError("送股/转增股数必须是数字") from exc
        if action_shares <= 0:
            raise PortfolioActionError("送股/转增股数必须大于 0")
        new_shares = old_shares + action_shares
        new_cost = (old_shares * old_cost) / new_shares
    else:
        try:
            action_shares = decimal_value(data.get("shares"))
            price = decimal_value(data.get("price"))
        except Exception as exc:
            raise PortfolioActionError("配股股数和价格必须是数字") from exc
        if action_shares <= 0:
            raise PortfolioActionError("配股股数必须大于 0")
        if price < 0:
            raise PortfolioActionError("配股价格不能小于 0")
        amount = quantize(action_shares * price, "0.01")
        cash_delta = -amount
        cash_amount_now = decimal_value(cash_amount_func())
        if cash_amount_now + cash_delta < 0:
            raise PortfolioActionError("现金不足，无法记录配股")
        new_shares = old_shares + action_shares
        new_cost = ((old_shares * old_cost) + amount) / new_shares

    action_id = execute_insert_id(
        """INSERT INTO portfolio_corporate_actions
           (action_date, stock_code, action_type, cash_amount, shares, price, amount, cash_delta,
            shares_before, shares_after, cost_price_before, cost_price_after, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            action_date,
            code,
            action_type,
            cash_amount,
            quantize(action_shares),
            quantize(price) if price is not None else None,
            amount,
            cash_delta,
            quantize(old_shares),
            quantize(new_shares),
            quantize(old_cost),
            quantize(new_cost) if new_cost is not None else None,
            note,
        ),
    )
    if new_shares > 0:
        execute_query(
            "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
            (quantize(new_shares), quantize(new_cost) if new_cost is not None else None, code),
            fetch=False,
        )
    else:
        execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

    if cash_delta != 0:
        cash_amount_now = decimal_value(cash_amount_func())
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (quantize(cash_amount_now + cash_delta, "0.01"),),
            fetch=False,
        )
        flow_label = {"cash_dividend": "分红到账", "rights_issue": "配股扣款"}.get(action_type, "权益现金")
        flow_note = note or f"{stock['name']}({code}) {flow_label}"
        execute_query(
            """INSERT INTO portfolio_cash_flows
               (flow_date, amount, flow_source, source_type, source_id, note)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (action_date, quantize(cash_delta, "0.01"), "action", "action", action_id, flow_note[:255]),
            fetch=False,
        )

    return {"action_id": action_id, "stock_code": code, "action_type": action_type}


def void_corporate_action(
    execute_query,
    void_linked_cash_flow,
    sync_cost_basis,
    cash_amount_func,
    action_id,
    void_note="作废权益事件",
):
    void_note = str(void_note or "作废权益事件").strip()[:255]
    rows = execute_query(
        """SELECT id, action_date, stock_code, cash_delta, is_void
           FROM portfolio_corporate_actions
           WHERE id=%s
           LIMIT 1""",
        (action_id,),
    )
    if not rows:
        raise PortfolioActionError("未找到这笔权益记录", 404)
    row = rows[0]
    if row.get("is_void"):
        raise PortfolioActionError("这笔权益记录已作废")

    execute_query(
        "UPDATE portfolio_corporate_actions SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
        (void_note, action_id),
        fetch=False,
    )
    voided_flow_amount = void_linked_cash_flow(
        "action",
        action_id,
        "action",
        row["action_date"],
        row["cash_delta"],
        row["stock_code"],
        void_note,
    )
    if voided_flow_amount != 0:
        current_cash = decimal_value(cash_amount_func())
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (quantize(current_cash - voided_flow_amount, "0.01"),),
            fetch=False,
        )
    sync_cost_basis()
    return {"action_id": action_id, "voided_flow_amount": float(voided_flow_amount)}
