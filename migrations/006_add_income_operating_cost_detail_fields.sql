ALTER TABLE income_statements
  ADD COLUMN interest_expense DECIMAL(18,4) DEFAULT NULL AFTER cost_of_revenue,
  ADD COLUMN fee_commission_expense DECIMAL(18,4) DEFAULT NULL AFTER interest_expense;
