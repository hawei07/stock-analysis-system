ALTER TABLE income_statements
  ADD COLUMN finance_interest_expense DECIMAL(18,4) DEFAULT NULL AFTER finance_expense,
  ADD COLUMN finance_interest_income DECIMAL(18,4) DEFAULT NULL AFTER finance_interest_expense;
