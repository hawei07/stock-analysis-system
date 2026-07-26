ALTER TABLE income_statements
  ADD COLUMN interest_income DECIMAL(18,4) DEFAULT NULL AFTER rd_expense,
  ADD COLUMN credit_impairment_loss DECIMAL(18,4) DEFAULT NULL AFTER fair_value_change;
