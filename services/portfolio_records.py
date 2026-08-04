"""Portfolio trade and corporate action record payloads."""


def trades_payload(execute_query, ensure_tables, currency_for_market, limit=1000):
    ensure_tables()
    rows = execute_query(
        """SELECT t.id, t.trade_date, t.stock_code, s.name, s.market, t.trade_type,
                  t.shares, t.price, t.amount, t.commission, t.stamp_tax, t.transfer_fee,
                  t.total_fee, t.cash_delta, t.shares_before, t.shares_after,
                  t.cost_price_before, t.cost_price_after, t.realized_profit, t.note,
                  t.is_void, t.voided_at, t.void_note
           FROM portfolio_trades t
           JOIN stocks s ON s.code = t.stock_code
           ORDER BY t.trade_date DESC, t.id DESC
           LIMIT %s""",
        (limit,),
    )
    result = []
    for r in rows:
        item = dict(r)
        item["trade_date"] = str(r["trade_date"])
        item["currency"] = currency_for_market(r.get("market"))
        for field in ("shares", "price", "amount", "commission", "stamp_tax", "transfer_fee", "total_fee", "cash_delta", "shares_before", "shares_after"):
            item[field] = float(r[field])
        for field in ("cost_price_before", "cost_price_after", "realized_profit"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        item["is_void"] = bool(r.get("is_void"))
        item["voided_at"] = str(r["voided_at"]) if r.get("voided_at") else None
        item["void_note"] = r.get("void_note") or ""
        result.append(item)
    return result


def actions_payload(execute_query, ensure_tables, currency_for_market, limit=100):
    ensure_tables()
    rows = execute_query(
        """SELECT a.id, a.action_date, a.stock_code, s.name, s.market, a.action_type,
                  a.cash_amount, a.shares, a.price, a.amount, a.cash_delta,
                  a.shares_before, a.shares_after, a.cost_price_before, a.cost_price_after, a.note,
                  a.is_void, a.voided_at, a.void_note
           FROM portfolio_corporate_actions a
           JOIN stocks s ON s.code = a.stock_code
           ORDER BY a.action_date DESC, a.id DESC
           LIMIT %s""",
        (limit,),
    )
    result = []
    for r in rows:
        item = dict(r)
        item["action_date"] = str(r["action_date"])
        item["currency"] = currency_for_market(r.get("market"))
        for field in ("cash_amount", "shares", "price", "amount", "cash_delta", "shares_before", "shares_after"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        for field in ("cost_price_before", "cost_price_after"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        item["is_void"] = bool(r.get("is_void"))
        item["voided_at"] = str(r["voided_at"]) if r.get("voided_at") else None
        item["void_note"] = r.get("void_note") or ""
        result.append(item)
    return result
