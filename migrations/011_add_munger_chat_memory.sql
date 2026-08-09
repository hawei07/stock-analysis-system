-- Per-stock conversation summary. It is context only, never an evidence source.
CREATE TABLE IF NOT EXISTS munger_chat_memory (
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  summary MEDIUMTEXT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  model VARCHAR(100) DEFAULT NULL,
  source_turn_id VARCHAR(40) DEFAULT NULL,
  PRIMARY KEY (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
