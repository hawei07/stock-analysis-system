"""Shareholder table schema helper."""


def ensure_shareholders_table(execute_query):
    execute_query(
        """CREATE TABLE IF NOT EXISTS stock_shareholders (
            id BIGINT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            report_date DATE NOT NULL,
            holder_rank INT NOT NULL,
            holder_name VARCHAR(255) NOT NULL,
            shares_type VARCHAR(80) DEFAULT NULL,
            hold_num DECIMAL(24,4) DEFAULT NULL,
            hold_ratio DECIMAL(10,4) DEFAULT NULL,
            hold_change_label VARCHAR(80) DEFAULT NULL,
            hold_change_num DECIMAL(24,4) DEFAULT NULL,
            change_ratio DECIMAL(10,4) DEFAULT NULL,
            change_type VARCHAR(20) DEFAULT NULL,
            is_report_date TINYINT(1) DEFAULT 1,
            source VARCHAR(80) DEFAULT NULL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_stock_shareholder_period_rank (stock_code, report_date, holder_rank),
            KEY idx_stock_shareholders_stock_date (stock_code, report_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
        fetch=False,
    )
