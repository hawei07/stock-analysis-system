"""Portfolio consistency audit helpers."""

from services.portfolio_money import decimal_equal, decimal_value, quantize


def audit_payload(
    execute_query,
    ensure_tables,
    cash_amount_func,
    rebuilt_cash_amount_func,
    cash_base_amount_func,
):
    ensure_tables()
    issues = []
    current_cash = decimal_value(cash_amount_func())
    rebuilt_cash = rebuilt_cash_amount_func()
    if not decimal_equal(current_cash, rebuilt_cash, "0.01"):
        issues.append({
            "type": "cash",
            "message": f"现金与流水推导不一致，相差 {float(quantize(current_cash - rebuilt_cash, '0.01')):.2f}",
            "current": float(quantize(current_cash, "0.01")),
            "expected": float(quantize(rebuilt_cash, "0.01")),
        })

    rows = execute_query(
        """SELECT stock_code, shares_after, cost_price_after
           FROM (
             SELECT stock_code, shares_after, cost_price_after,
                    ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY d DESC, sort_id DESC) AS rn
             FROM (
               SELECT stock_code, shares_after, cost_price_after, trade_date AS d, id AS sort_id
               FROM portfolio_trades WHERE is_void=0
               UNION ALL
               SELECT stock_code, shares_after, cost_price_after, action_date AS d, id AS sort_id
               FROM portfolio_corporate_actions WHERE is_void=0
             ) x
           ) y
           WHERE rn=1"""
    )
    for row in rows:
        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (row["stock_code"],),
        )
        if not position_rows:
            issues.append({"type": "position", "code": row["stock_code"], "message": "账本有记录但当前持仓缺失"})
            continue
        pos = position_rows[0]
        if (
            not decimal_equal(pos.get("shares"), row.get("shares_after"))
            or not decimal_equal(pos.get("cost_price"), row.get("cost_price_after"))
        ):
            issues.append({
                "type": "position",
                "code": row["stock_code"],
                "message": "当前持仓与账本回放结果不一致",
                "current_shares": float(quantize(pos.get("shares"))),
                "expected_shares": float(quantize(row.get("shares_after"))),
                "current_cost": float(quantize(pos.get("cost_price"))) if pos.get("cost_price") is not None else None,
                "expected_cost": float(quantize(row.get("cost_price_after"))) if row.get("cost_price_after") is not None else None,
            })

    return {
        "ok": not issues,
        "issues": issues,
        "cash": {
            "current": float(quantize(current_cash, "0.01")),
            "expected": float(quantize(rebuilt_cash, "0.01")),
            "base_amount": float(quantize(cash_base_amount_func(), "0.01")),
        },
    }
