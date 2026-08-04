"""Delete a stock and all stock-scoped local data."""


def _table_exists(cursor, table):
    cursor.execute(
        """SELECT COUNT(*) AS n
           FROM information_schema.TABLES
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s""",
        (table,),
    )
    row = cursor.fetchone()
    return bool(row and row.get("n"))


def _stock_code_tables(cursor):
    cursor.execute(
        """SELECT TABLE_NAME
           FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE()
             AND COLUMN_NAME = 'stock_code'
           ORDER BY TABLE_NAME"""
    )
    return [row["TABLE_NAME"] for row in cursor.fetchall()]


def _delete_from_table(cursor, table, code):
    cursor.execute(f"DELETE FROM `{table}` WHERE stock_code = %s", (code,))
    return cursor.rowcount


def delete_stock_with_related_data(get_connection, code):
    """Delete stock master row and every local table keyed by stock_code."""
    conn = get_connection()
    cursor = None
    deleted = {}
    cash_adjustment = 0
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT code, name FROM stocks WHERE code=%s LIMIT 1", (code,))
        stock = cursor.fetchone()
        if not stock:
            return {"deleted_stock": 0, "deleted": {}, "cash_adjustment": 0}

        trade_ids = []
        action_ids = []
        if _table_exists(cursor, "portfolio_trades"):
            cursor.execute("SELECT id FROM portfolio_trades WHERE stock_code=%s", (code,))
            trade_ids = [row["id"] for row in cursor.fetchall()]
        if _table_exists(cursor, "portfolio_corporate_actions"):
            cursor.execute("SELECT id FROM portfolio_corporate_actions WHERE stock_code=%s", (code,))
            action_ids = [row["id"] for row in cursor.fetchall()]

        if _table_exists(cursor, "portfolio_cash_flows") and (trade_ids or action_ids):
            clauses = []
            params = []
            if trade_ids:
                placeholders = ", ".join(["%s"] * len(trade_ids))
                clauses.append(f"(source_type='trade' AND source_id IN ({placeholders}))")
                params.extend(trade_ids)
            if action_ids:
                placeholders = ", ".join(["%s"] * len(action_ids))
                clauses.append(f"(source_type='action' AND source_id IN ({placeholders}))")
                params.extend(action_ids)

            where_sql = " OR ".join(clauses)
            cursor.execute(
                f"SELECT COALESCE(SUM(amount), 0) AS total FROM portfolio_cash_flows WHERE is_void=0 AND ({where_sql})",
                tuple(params),
            )
            row = cursor.fetchone()
            cash_adjustment = float(row["total"] or 0)
            cursor.execute(f"DELETE FROM portfolio_cash_flows WHERE {where_sql}", tuple(params))
            deleted["portfolio_cash_flows"] = cursor.rowcount

            if cash_adjustment and _table_exists(cursor, "portfolio_cash"):
                cursor.execute("UPDATE portfolio_cash SET amount=amount-%s WHERE id=1", (cash_adjustment,))

        for table in _stock_code_tables(cursor):
            if table == "stocks":
                continue
            count = _delete_from_table(cursor, table, code)
            if count:
                deleted[table] = deleted.get(table, 0) + count

        cursor.execute("DELETE FROM stocks WHERE code=%s", (code,))
        deleted_stock = cursor.rowcount
        conn.commit()
        return {
            "deleted_stock": deleted_stock,
            "stock": stock,
            "deleted": deleted,
            "cash_adjustment": cash_adjustment,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        if cursor:
            cursor.close()
        conn.close()


def delete_stock_sticky_notes(load_notes, save_notes, cleanup_images, code):
    notes = load_notes()
    if not isinstance(notes, list):
        return 0
    kept = []
    deleted = 0
    for note in notes:
        if note.get("stock_code") == code:
            cleanup_images(note)
            deleted += 1
        else:
            kept.append(note)
    if deleted:
        save_notes(kept)
    return deleted
