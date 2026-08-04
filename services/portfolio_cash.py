"""Portfolio cash balance and cash-flow helpers."""

from decimal import Decimal

from services.portfolio_money import decimal_value


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
