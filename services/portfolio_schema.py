"""Portfolio table schema and compatibility helpers."""

from decimal import Decimal, ROUND_HALF_UP


def _decimal_value(value, default="0"):
    if value is None:
        value = default
    return Decimal(str(value))


def _quantize(value, scale="0.0001"):
    return _decimal_value(value).quantize(Decimal(scale), rounding=ROUND_HALF_UP)


def _add_column_if_missing(execute_query, table_name, column_name, column_def):
    try:
        rows = execute_query(f"SHOW COLUMNS FROM {table_name} LIKE '{column_name}'")
        if not rows:
            execute_query(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}",
                fetch=False,
            )
    except Exception:
        pass


def ensure_portfolio_tables(execute_query, sync_cost_basis=None):
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_positions (
            id INT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            shares DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price DECIMAL(18,4) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_portfolio_stock (stock_code),
            CONSTRAINT fk_portfolio_stock FOREIGN KEY (stock_code)
                REFERENCES stocks (code) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
            id INT NOT NULL AUTO_INCREMENT,
            snapshot_date DATE NOT NULL,
            total_market_value DECIMAL(18,2) NOT NULL DEFAULT 0,
            expected_dividend DECIMAL(18,2) NOT NULL DEFAULT 0,
            positions_json JSON NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_snapshot_date (snapshot_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_cash (
            id TINYINT NOT NULL PRIMARY KEY,
            amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        "INSERT IGNORE INTO portfolio_cash (id, amount) VALUES (1, 0)",
        fetch=False,
    )
    _add_column_if_missing(
        execute_query,
        "portfolio_cash",
        "base_amount",
        "DECIMAL(18,2) NULL AFTER amount",
    )

    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_cash_flows (
            id INT NOT NULL AUTO_INCREMENT,
            flow_date DATE NOT NULL,
            amount DECIMAL(18,2) NOT NULL,
            flow_source VARCHAR(20) NOT NULL DEFAULT 'external',
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_flow_date (flow_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    _add_column_if_missing(
        execute_query,
        "portfolio_cash_flows",
        "flow_source",
        "VARCHAR(20) NOT NULL DEFAULT 'external' AFTER amount",
    )
    for column_name, column_def in (
        ("source_type", "VARCHAR(20) NULL AFTER flow_source"),
        ("source_id", "INT NULL AFTER source_type"),
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        _add_column_if_missing(execute_query, "portfolio_cash_flows", column_name, column_def)

    try:
        execute_query(
            """UPDATE portfolio_cash_flows f
               JOIN portfolio_trades t
                 ON f.flow_date = t.trade_date
                AND ABS(f.amount) = t.amount
                AND ((t.trade_type='buy' AND f.amount < 0) OR (t.trade_type='sell' AND f.amount > 0))
               SET f.flow_source='trade'
               WHERE f.flow_source='external'""",
            fetch=False,
        )
    except Exception:
        pass

    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_trades (
            id INT NOT NULL AUTO_INCREMENT,
            trade_date DATE NOT NULL,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
            trade_type VARCHAR(8) NOT NULL,
            shares DECIMAL(18,4) NOT NULL,
            price DECIMAL(18,4) NOT NULL,
            amount DECIMAL(18,2) NOT NULL,
            shares_before DECIMAL(18,4) NOT NULL DEFAULT 0,
            shares_after DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price_before DECIMAL(18,4) NULL,
            cost_price_after DECIMAL(18,4) NULL,
            realized_profit DECIMAL(18,2) NULL,
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_trade_stock_date (stock_code, trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_fee_config (
            id TINYINT NOT NULL PRIMARY KEY,
            commission_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000250,
            min_commission DECIMAL(18,2) NOT NULL DEFAULT 5.00,
            stamp_tax_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000500,
            transfer_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000010,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_corporate_actions (
            id INT NOT NULL AUTO_INCREMENT,
            action_date DATE NOT NULL,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
            action_type VARCHAR(20) NOT NULL,
            cash_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            shares DECIMAL(18,4) NOT NULL DEFAULT 0,
            price DECIMAL(18,4) NULL,
            amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            cash_delta DECIMAL(18,2) NOT NULL DEFAULT 0,
            shares_before DECIMAL(18,4) NOT NULL DEFAULT 0,
            shares_after DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price_before DECIMAL(18,4) NULL,
            cost_price_after DECIMAL(18,4) NULL,
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_action_stock_date (stock_code, action_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """INSERT IGNORE INTO portfolio_fee_config
           (id, commission_rate, min_commission, stamp_tax_rate, transfer_fee_rate)
           VALUES (1, 0.000250, 5.00, 0.000500, 0.000010)""",
        fetch=False,
    )

    for column_name, column_def in (
        ("commission", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER amount"),
        ("stamp_tax", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER commission"),
        ("transfer_fee", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER stamp_tax"),
        ("total_fee", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER transfer_fee"),
        ("cash_delta", "DECIMAL(18,2) NULL AFTER total_fee"),
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        _add_column_if_missing(execute_query, "portfolio_trades", column_name, column_def)

    for column_name, column_def in (
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        _add_column_if_missing(execute_query, "portfolio_corporate_actions", column_name, column_def)

    try:
        rows = execute_query("SELECT amount, base_amount FROM portfolio_cash WHERE id=1")
        if rows and rows[0].get("base_amount") is None:
            flow_rows = execute_query("SELECT COALESCE(SUM(amount), 0) AS total FROM portfolio_cash_flows WHERE is_void=0")
            base_amount = _decimal_value(rows[0]["amount"]) - _decimal_value(flow_rows[0]["total"] if flow_rows else 0)
            execute_query(
                "UPDATE portfolio_cash SET base_amount=%s WHERE id=1",
                (_quantize(base_amount, "0.01"),),
                fetch=False,
            )
    except Exception:
        pass

    try:
        execute_query(
            """UPDATE portfolio_trades
               SET cash_delta = CASE
                   WHEN trade_type='buy' THEN -(amount + total_fee)
                   ELSE amount - total_fee
               END
               WHERE cash_delta IS NULL""",
            fetch=False,
        )
    except Exception:
        pass

    try:
        rows = execute_query("SHOW FULL COLUMNS FROM portfolio_trades LIKE 'stock_code'")
        if rows and rows[0].get("Collation") != "utf8mb4_unicode_ci":
            execute_query(
                "ALTER TABLE portfolio_trades MODIFY stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL",
                fetch=False,
            )
    except Exception:
        pass

    _add_column_if_missing(
        execute_query,
        "portfolio_positions",
        "cost_price",
        "DECIMAL(18,4) NULL AFTER shares",
    )
    _add_column_if_missing(
        execute_query,
        "portfolio_positions",
        "custom_dividend_per_share",
        "DECIMAL(10,4) NULL AFTER shares",
    )
    for column_name, column_def in (
        ("cash_amount", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER expected_dividend"),
        ("total_asset_value", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER cash_amount"),
    ):
        _add_column_if_missing(execute_query, "portfolio_nav_snapshots", column_name, column_def)

    if sync_cost_basis:
        try:
            sync_cost_basis()
        except Exception:
            pass
