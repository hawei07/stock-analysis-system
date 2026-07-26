ALTER TABLE income_statements
  ADD COLUMN asset_impairment_loss DECIMAL(18,4) DEFAULT NULL AFTER credit_impairment_loss,
  ADD COLUMN asset_disposal_income DECIMAL(18,4) DEFAULT NULL AFTER asset_impairment_loss,
  ADD COLUMN other_income DECIMAL(18,4) DEFAULT NULL AFTER asset_disposal_income;
