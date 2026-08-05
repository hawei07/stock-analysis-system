"""Delete stock detail data without deleting portfolio history."""


PORTFOLIO_TABLES = {
    "portfolio_positions",
    "portfolio_trades",
    "portfolio_corporate_actions",
}
EXCLUDED_STOCK_CODE_TABLES = {
    "background_jobs",
    "background_job_logs",
    "portfolio_positions",
    "portfolio_trades",
    "portfolio_corporate_actions",
}


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


def _ensure_watchlist_column(cursor):
    cursor.execute("SHOW COLUMNS FROM stocks LIKE 'is_watchlist'")
    if not cursor.fetchall():
        cursor.execute("ALTER TABLE stocks ADD COLUMN is_watchlist TINYINT NOT NULL DEFAULT 1")


def _has_portfolio_refs(cursor, code):
    for table in PORTFOLIO_TABLES:
        if not _table_exists(cursor, table):
            continue
        cursor.execute(f"SELECT 1 FROM `{table}` WHERE stock_code=%s LIMIT 1", (code,))
        if cursor.fetchone():
            return True
    return False


def delete_stock_with_related_data(transaction, code):
    """Clear stock detail data and remove the stock from the watchlist.

    Portfolio tables are intentionally kept. If portfolio records reference this
    stock, the stocks row is kept with is_watchlist=0 to avoid FK cascades and to
    preserve display metadata for holdings.
    """
    deleted = {}
    with transaction(dictionary=True) as cursor:
        return _delete_stock_with_related_data(cursor, code, deleted)


def _delete_stock_with_related_data(cursor, code, deleted):
    _ensure_watchlist_column(cursor)
    cursor.execute("SELECT code, name FROM stocks WHERE code=%s LIMIT 1", (code,))
    stock = cursor.fetchone()
    if not stock:
        return {"deleted_stock": 0, "hidden_stock": 0, "deleted": {}}

    for table in _stock_code_tables(cursor):
        if table in EXCLUDED_STOCK_CODE_TABLES:
            continue
        count = _delete_from_table(cursor, table, code)
        if count:
            deleted[table] = deleted.get(table, 0) + count

    has_portfolio_refs = _has_portfolio_refs(cursor, code)
    if has_portfolio_refs:
        cursor.execute("UPDATE stocks SET is_watchlist=0 WHERE code=%s", (code,))
        deleted_stock = 0
        hidden_stock = cursor.rowcount
    else:
        cursor.execute("DELETE FROM stocks WHERE code=%s", (code,))
        deleted_stock = cursor.rowcount
        hidden_stock = 0
    return {
        "deleted_stock": deleted_stock,
        "hidden_stock": hidden_stock,
        "portfolio_preserved": has_portfolio_refs,
        "stock": stock,
        "deleted": deleted,
    }


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
