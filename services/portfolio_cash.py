"""Portfolio cash balance and cash-flow helpers."""

from datetime import datetime
from decimal import Decimal

from services.portfolio_money import decimal_value, quantize


def cash_amount(execute_query, ensure_tables):
    ensure_tables()
    rows = execute_query("SELECT amount FROM portfolio_cash WHERE id=1")
    return float(rows[0]["amount"]) if rows else 0.0


def base_amount(execute_query, ensure_tables):
    ensure_tables()
    rows = execute_query("SELECT base_amount FROM portfolio_cash WHERE id=1")
    return decimal_value(rows[0]["base_amount"]) if rows and rows[0].get("base_amount") is not None else Decimal("0")


def rebuilt_amount(execute_query, base_amount_func):
    base = base_amount_func()
    rows = execute_query("SELECT COALESCE(SUM(amount), 0) AS total FROM portfolio_cash_flows WHERE is_void=0")
    return base + decimal_value(rows[0]["total"] if rows else 0)


def set_cash_amount(execute_query, amount):
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (quantize(amount, "0.01"),),
        fetch=False,
    )


def flow_rows(execute_query, ensure_tables, limit=100):
    ensure_tables()
    return execute_query(
        """SELECT id, flow_date, amount, flow_source, source_type, source_id, note,
                  is_void, voided_at, void_note, created_at
           FROM portfolio_cash_flows
           ORDER BY flow_date DESC, id DESC
           LIMIT %s""",
        (limit,),
    )


def flows_payload(execute_query, ensure_tables, limit=100):
    return [
        {
            "id": r["id"],
            "flow_date": str(r["flow_date"]),
            "amount": round(float(r["amount"]), 2),
            "flow_source": r.get("flow_source") or "external",
            "source_type": r.get("source_type"),
            "source_id": r.get("source_id"),
            "is_void": bool(r.get("is_void")),
            "voided_at": str(r["voided_at"]) if r.get("voided_at") else None,
            "void_note": r.get("void_note") or "",
            "note": r.get("note") or "",
            "created_at": str(r["created_at"]) if r.get("created_at") else None,
        }
        for r in flow_rows(execute_query, ensure_tables, limit)
    ]


def add_external_flow(execute_query, ensure_tables, cash_amount_func, flow_date, amount, note=""):
    ensure_tables()
    flow_date = str(flow_date or datetime.now().date()).strip()
    try:
        datetime.strptime(flow_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("日期格式必须是 YYYY-MM-DD") from exc

    try:
        amount = decimal_value(amount)
    except Exception as exc:
        raise ValueError("资金金额必须是数字") from exc
    if amount == 0:
        raise ValueError("资金金额不能为 0")

    current_cash = decimal_value(cash_amount_func())
    new_cash = current_cash + amount
    if new_cash < 0:
        raise ValueError("现金不足，无法记录这笔流出")

    execute_query(
        "INSERT INTO portfolio_cash_flows (flow_date, amount, flow_source, note) VALUES (%s, %s, %s, %s)",
        (flow_date, quantize(amount, "0.01"), "external", str(note or "").strip()[:255]),
        fetch=False,
    )
    set_cash_amount(execute_query, new_cash)
    return new_cash


def void_external_flow(execute_query, ensure_tables, cash_amount_func, flow_id):
    ensure_tables()
    rows = execute_query("SELECT amount, flow_source, is_void FROM portfolio_cash_flows WHERE id=%s", (flow_id,))
    if not rows:
        raise LookupError("未找到这笔资金流水")
    row = rows[0]
    if row.get("is_void"):
        raise ValueError("这笔资金流水已作废")
    if row.get("flow_source") in ("trade", "action"):
        raise ValueError("交易或权益产生的资金流水不能单独作废，请作废原始记录")

    amount = decimal_value(row["amount"])
    current_cash = decimal_value(cash_amount_func())
    new_cash = current_cash - amount
    if new_cash < 0:
        raise ValueError("作废后现金会小于 0，无法作废")

    execute_query(
        "UPDATE portfolio_cash_flows SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note='作废资金流水' WHERE id=%s",
        (flow_id,),
        fetch=False,
    )
    set_cash_amount(execute_query, new_cash)
    return new_cash


def void_linked_cash_flow(execute_query, source_type, source_id, flow_source, flow_date, amount, code, void_note):
    rows = execute_query(
        """SELECT id, amount
           FROM portfolio_cash_flows
           WHERE is_void=0 AND source_type=%s AND source_id=%s
           LIMIT 1""",
        (source_type, source_id),
    )
    if not rows:
        rows = execute_query(
            """SELECT id, amount
               FROM portfolio_cash_flows
               WHERE is_void=0 AND flow_source=%s AND flow_date=%s
                 AND amount=%s AND (note LIKE %s OR note IS NULL OR note='')
               ORDER BY id DESC
               LIMIT 1""",
            (flow_source, flow_date, amount, f"%{code}%"),
        )
    if not rows:
        return Decimal("0")
    row = rows[0]
    execute_query(
        "UPDATE portfolio_cash_flows SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
        (void_note, row["id"]),
        fetch=False,
    )
    return decimal_value(row["amount"])
