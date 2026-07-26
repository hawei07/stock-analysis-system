CREATE TABLE IF NOT EXISTS system_config (
  id INT NOT NULL AUTO_INCREMENT,
  config_key VARCHAR(100) NOT NULL,
  config_value TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_system_config_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stocks (
  id INT NOT NULL AUTO_INCREMENT,
  code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  name VARCHAR(50) NOT NULL,
  market ENUM('SH','SZ','BJ') NOT NULL,
  industry VARCHAR(50) DEFAULT NULL,
  list_date DATE DEFAULT NULL,
  status ENUM('正常','ST','*ST','退市','暂停上市') DEFAULT '正常',
  pe_ttm DECIMAL(10,2) DEFAULT NULL,
  dividend_yield DECIMAL(10,4) DEFAULT NULL,
  display_order INT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS dividends (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  net_profit DECIMAL(18,4) DEFAULT NULL,
  dividend_amount DECIMAL(18,4) DEFAULT NULL,
  dividend_per_share DECIMAL(10,4) DEFAULT NULL,
  ex_date DATE DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_code_year (stock_code, fiscal_year)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS custom_financials (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
  total_revenue DECIMAL(18,4) DEFAULT NULL,
  operate_profit DECIMAL(18,4) DEFAULT NULL,
  parent_profit DECIMAL(18,4) DEFAULT NULL,
  deducted_profit DECIMAL(18,4) DEFAULT NULL,
  operate_cashflow DECIMAL(18,4) DEFAULT NULL,
  roe DECIMAL(10,4) DEFAULT NULL,
  deducted_roe DECIMAL(10,4) DEFAULT NULL,
  roic DECIMAL(10,4) DEFAULT NULL,
  total_assets DECIMAL(18,4) DEFAULT NULL,
  total_equity DECIMAL(18,4) DEFAULT NULL,
  total_shares DECIMAL(18,4) DEFAULT NULL,
  audit_opinion VARCHAR(100) DEFAULT NULL,
  basic_eps DECIMAL(18,4) DEFAULT NULL,
  debt_ratio DECIMAL(10,4) DEFAULT NULL,
  short_borrow DECIMAL(18,4) DEFAULT NULL,
  noncurrent_liab_due1y DECIMAL(18,4) DEFAULT NULL,
  long_borrow DECIMAL(18,4) DEFAULT NULL,
  bonds_payable DECIMAL(18,4) DEFAULT NULL,
  interest_bearing_debt_ratio DECIMAL(10,4) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_financial_stock_year_period (stock_code, fiscal_year, report_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS balance_sheets (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
  monetary_funds DECIMAL(18,4) DEFAULT NULL,
  trading_fin_assets DECIMAL(18,4) DEFAULT NULL,
  notes_receivable DECIMAL(18,4) DEFAULT NULL,
  accounts_receivable DECIMAL(18,4) DEFAULT NULL,
  receivables_financing DECIMAL(18,4) DEFAULT NULL,
  prepayment DECIMAL(18,4) DEFAULT NULL,
  other_receivables DECIMAL(18,4) DEFAULT NULL,
  inventory DECIMAL(18,4) DEFAULT NULL,
  noncurrent_assets_due1y DECIMAL(18,4) DEFAULT NULL,
  other_current_assets DECIMAL(18,4) DEFAULT NULL,
  total_current_assets DECIMAL(18,4) DEFAULT NULL,
  held_to_maturity_invest DECIMAL(18,4) DEFAULT NULL,
  longterm_equity_invest DECIMAL(18,4) DEFAULT NULL,
  investment_property DECIMAL(18,4) DEFAULT NULL,
  cip DECIMAL(18,4) DEFAULT NULL,
  fixed_assets DECIMAL(18,4) DEFAULT NULL,
  right_of_use_assets DECIMAL(18,4) DEFAULT NULL,
  intangible_assets DECIMAL(18,4) DEFAULT NULL,
  development_expenditure DECIMAL(18,4) DEFAULT NULL,
  goodwill DECIMAL(18,4) DEFAULT NULL,
  longterm_prepaid_expense DECIMAL(18,4) DEFAULT NULL,
  deferred_tax_assets DECIMAL(18,4) DEFAULT NULL,
  other_noncurrent_assets DECIMAL(18,4) DEFAULT NULL,
  total_noncurrent_assets DECIMAL(18,4) DEFAULT NULL,
  total_assets DECIMAL(18,4) DEFAULT NULL,
  short_borrow DECIMAL(18,4) DEFAULT NULL,
  notes_payable DECIMAL(18,4) DEFAULT NULL,
  accounts_payable DECIMAL(18,4) DEFAULT NULL,
  advance_receipts DECIMAL(18,4) DEFAULT NULL,
  payroll_payable DECIMAL(18,4) DEFAULT NULL,
  taxes_payable DECIMAL(18,4) DEFAULT NULL,
  other_payables DECIMAL(18,4) DEFAULT NULL,
  noncurrent_liab_due1y DECIMAL(18,4) DEFAULT NULL,
  other_current_liabilities DECIMAL(18,4) DEFAULT NULL,
  total_current_liabilities DECIMAL(18,4) DEFAULT NULL,
  long_borrow DECIMAL(18,4) DEFAULT NULL,
  bonds_payable DECIMAL(18,4) DEFAULT NULL,
  lease_liabilities DECIMAL(18,4) DEFAULT NULL,
  deferred_tax_liabilities DECIMAL(18,4) DEFAULT NULL,
  total_noncurrent_liabilities DECIMAL(18,4) DEFAULT NULL,
  total_liabilities DECIMAL(18,4) DEFAULT NULL,
  paid_in_capital DECIMAL(18,4) DEFAULT NULL,
  capital_reserve DECIMAL(18,4) DEFAULT NULL,
  treasury_stock DECIMAL(18,4) DEFAULT NULL,
  surplus_reserve DECIMAL(18,4) DEFAULT NULL,
  retained_earnings DECIMAL(18,4) DEFAULT NULL,
  parent_equity DECIMAL(18,4) DEFAULT NULL,
  minority_interests DECIMAL(18,4) DEFAULT NULL,
  total_equity DECIMAL(18,4) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_balance_stock_year_period (stock_code, fiscal_year, report_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS income_statements (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
  total_revenue DECIMAL(18,4) DEFAULT NULL,
  operating_revenue DECIMAL(18,4) DEFAULT NULL,
  operating_cost DECIMAL(18,4) DEFAULT NULL,
  cost_of_revenue DECIMAL(18,4) DEFAULT NULL,
  tax_surcharge DECIMAL(18,4) DEFAULT NULL,
  selling_expense DECIMAL(18,4) DEFAULT NULL,
  admin_expense DECIMAL(18,4) DEFAULT NULL,
  finance_expense DECIMAL(18,4) DEFAULT NULL,
  rd_expense DECIMAL(18,4) DEFAULT NULL,
  fair_value_change DECIMAL(18,4) DEFAULT NULL,
  invest_income DECIMAL(18,4) DEFAULT NULL,
  operating_profit DECIMAL(18,4) DEFAULT NULL,
  nonop_income DECIMAL(18,4) DEFAULT NULL,
  nonop_expense DECIMAL(18,4) DEFAULT NULL,
  total_profit DECIMAL(18,4) DEFAULT NULL,
  income_tax DECIMAL(18,4) DEFAULT NULL,
  net_profit DECIMAL(18,4) DEFAULT NULL,
  parent_net_profit DECIMAL(18,4) DEFAULT NULL,
  minority_profit DECIMAL(18,4) DEFAULT NULL,
  basic_eps DECIMAL(18,4) DEFAULT NULL,
  diluted_eps DECIMAL(18,4) DEFAULT NULL,
  other_comprehensive DECIMAL(18,4) DEFAULT NULL,
  total_comprehensive DECIMAL(18,4) DEFAULT NULL,
  parent_comprehensive DECIMAL(18,4) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_income_stock_year_period (stock_code, fiscal_year, report_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS cash_flows (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
  cf_sales_goods DECIMAL(18,4) DEFAULT NULL,
  cf_tax_refund DECIMAL(18,4) DEFAULT NULL,
  cf_other_oper_in DECIMAL(18,4) DEFAULT NULL,
  cf_oper_inflow DECIMAL(18,4) DEFAULT NULL,
  cf_buy_goods DECIMAL(18,4) DEFAULT NULL,
  cf_payroll DECIMAL(18,4) DEFAULT NULL,
  cf_tax_pay DECIMAL(18,4) DEFAULT NULL,
  cf_other_oper_out DECIMAL(18,4) DEFAULT NULL,
  cf_oper_outflow DECIMAL(18,4) DEFAULT NULL,
  cf_oper_net DECIMAL(18,4) DEFAULT NULL,
  cf_invest_withdraw DECIMAL(18,4) DEFAULT NULL,
  cf_invest_income DECIMAL(18,4) DEFAULT NULL,
  cf_dispose_assets DECIMAL(18,4) DEFAULT NULL,
  cf_other_invest_in DECIMAL(18,4) DEFAULT NULL,
  cf_invest_inflow DECIMAL(18,4) DEFAULT NULL,
  cf_buy_assets DECIMAL(18,4) DEFAULT NULL,
  cf_invest_pay DECIMAL(18,4) DEFAULT NULL,
  cf_other_invest_out DECIMAL(18,4) DEFAULT NULL,
  cf_invest_outflow DECIMAL(18,4) DEFAULT NULL,
  cf_invest_net DECIMAL(18,4) DEFAULT NULL,
  cf_finance_in DECIMAL(18,4) DEFAULT NULL,
  cf_borrow DECIMAL(18,4) DEFAULT NULL,
  cf_bond DECIMAL(18,4) DEFAULT NULL,
  cf_other_finance_in DECIMAL(18,4) DEFAULT NULL,
  cf_finance_inflow DECIMAL(18,4) DEFAULT NULL,
  cf_repay_debt DECIMAL(18,4) DEFAULT NULL,
  cf_dividend_interest DECIMAL(18,4) DEFAULT NULL,
  cf_other_finance_out DECIMAL(18,4) DEFAULT NULL,
  cf_finance_outflow DECIMAL(18,4) DEFAULT NULL,
  cf_finance_net DECIMAL(18,4) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_cashflow_stock_year_period (stock_code, fiscal_year, report_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS business_segments (
  id BIGINT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  fiscal_year INT NOT NULL,
  report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
  dimension_type VARCHAR(20) NOT NULL,
  segment_name VARCHAR(120) NOT NULL,
  revenue DECIMAL(18,4) DEFAULT NULL,
  cost DECIMAL(18,4) DEFAULT NULL,
  gross_profit DECIMAL(18,4) DEFAULT NULL,
  gross_margin DECIMAL(10,4) DEFAULT NULL,
  revenue_ratio DECIMAL(10,4) DEFAULT NULL,
  profit_ratio DECIMAL(10,4) DEFAULT NULL,
  source VARCHAR(50) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_segment (stock_code, fiscal_year, report_period, dimension_type, segment_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS graham_valuations (
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  growth_rate DECIMAL(10,4) DEFAULT NULL,
  payout_ratio DECIMAL(10,4) DEFAULT NULL,
  risk_free_rate DECIMAL(10,4) DEFAULT NULL,
  expected_profit DECIMAL(18,4) DEFAULT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS portfolio_positions (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  shares DECIMAL(18,4) NOT NULL DEFAULT 0,
  custom_dividend_per_share DECIMAL(10,4) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_portfolio_stock (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS portfolio_cash (
  id TINYINT NOT NULL,
  amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO portfolio_cash (id, amount) VALUES (1, 0);

CREATE TABLE IF NOT EXISTS portfolio_cash_flows (
  id INT NOT NULL AUTO_INCREMENT,
  flow_date DATE NOT NULL,
  amount DECIMAL(18,2) NOT NULL,
  note VARCHAR(255) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_portfolio_flow_date (flow_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
  id INT NOT NULL AUTO_INCREMENT,
  snapshot_date DATE NOT NULL,
  total_market_value DECIMAL(18,2) NOT NULL DEFAULT 0,
  expected_dividend DECIMAL(18,2) NOT NULL DEFAULT 0,
  cash_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
  total_asset_value DECIMAL(18,2) NOT NULL DEFAULT 0,
  positions_json JSON DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_portfolio_snapshot_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS munger_chats (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  role VARCHAR(20) NOT NULL,
  content MEDIUMTEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_munger_chat_stock (stock_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS munger_cache (
  id INT NOT NULL AUTO_INCREMENT,
  stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  analysis_json MEDIUMTEXT NOT NULL,
  cache_version VARCHAR(40) NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_munger_cache_stock_version (stock_code, cache_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
