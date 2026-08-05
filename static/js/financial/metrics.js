window.FinancialMetrics = (() => {
  function number(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function nullableNumber(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  function positive(row, field) {
    return Math.max(value(row, field), 0);
  }

  function value(row, field) {
    return number(row ? row[field] : null, 0);
  }

  function pctChange(cur, prev, ndigits = null) {
    cur = nullableNumber(cur);
    prev = nullableNumber(prev);
    if (cur == null || prev == null || prev === 0) return null;
    const result = (cur - prev) / Math.abs(prev) * 100;
    return ndigits == null ? result : Number(result.toFixed(ndigits));
  }

  function cagr(first, last, years, ndigits = 2) {
    first = nullableNumber(first);
    last = nullableNumber(last);
    years = nullableNumber(years);
    if (first == null || last == null || years == null || years <= 0 || first <= 0 || last <= 0) return null;
    return Number(((Math.pow(last / first, 1 / years) - 1) * 100).toFixed(ndigits));
  }

  function incomeRevenue(row) {
    return value(row, 'total_revenue') || value(row, 'operating_revenue');
  }

  function incomeOperatingRevenue(row) {
    return value(row, 'operating_revenue') || incomeRevenue(row);
  }

  function incomeInterestIncludedInRevenue(row) {
    const totalRevenue = value(row, 'total_revenue');
    const operatingRevenue = value(row, 'operating_revenue');
    const interestIncome = value(row, 'interest_income');
    if (!totalRevenue || !operatingRevenue || !interestIncome) return false;
    return Math.abs((totalRevenue - operatingRevenue) - interestIncome) <= Math.max(Math.abs(interestIncome) * 0.05, 0.05);
  }

  function incomeFinanceExpenseBeforeInterestIncome(row) {
    const financeExpense = value(row, 'finance_expense');
    const financeInterestIncome = positive(row, 'finance_interest_income');
    if (financeInterestIncome > 0) return Math.max(financeExpense + financeInterestIncome, 0);
    return Math.max(financeExpense, 0);
  }

  function incomePeriodExpense(row) {
    return ['selling_expense', 'admin_expense', 'rd_expense']
      .reduce((sum, field) => sum + positive(row, field), 0)
      + incomeFinanceExpenseBeforeInterestIncome(row);
  }

  function incomeGross(row) {
    return Math.max(
      incomeRevenue(row)
        - positive(row, 'cost_of_revenue')
        - positive(row, 'interest_expense')
        - positive(row, 'fee_commission_expense'),
      0
    );
  }

  function incomeCoreProfit(row) {
    return incomeGross(row) - incomePeriodExpense(row) - positive(row, 'tax_surcharge');
  }

  function incomeGrossMargin(row) {
    const operatingRevenue = incomeOperatingRevenue(row);
    const cost = positive(row, 'cost_of_revenue');
    return operatingRevenue > 0 ? (operatingRevenue - cost) / operatingRevenue * 100 : null;
  }

  function incomeCoreProfitRate(row) {
    const revenue = incomeRevenue(row);
    return revenue > 0 ? incomeCoreProfit(row) / revenue * 100 : null;
  }

  function incomeOperatingSignedAdjustmentSum(row) {
    const defs = [
      ['other_income', false],
      ['invest_income', false],
      ['fair_value_change', false],
      ['finance_interest_income', false],
      ['credit_impairment_loss', true],
      ['asset_impairment_loss', true],
      ['asset_disposal_income', false],
    ];
    return defs.reduce((sum, def) => {
      const raw = value(row, def[0]);
      if (!Number.isFinite(raw) || raw === 0) return sum;
      return sum + (def[1] ? -Math.abs(raw) : raw);
    }, 0);
  }

  function incomeOperatingAdjustmentResidual(row) {
    return value(row, 'operating_profit') - incomeCoreProfit(row) - incomeOperatingSignedAdjustmentSum(row);
  }

  function incomeParentProfit(row) {
    if (!row) return 0;
    const parent = Number(row.parent_net_profit);
    if (Number.isFinite(parent)) return parent;
    return value(row, 'net_profit') - value(row, 'minority_profit');
  }

  function enrichIncomeDerivedFields(row) {
    if (!row) return row;
    row.income_gross_margin = incomeGrossMargin(row);
    row.sankey_core_profit = incomeCoreProfit(row);
    row.sankey_core_profit_rate = incomeCoreProfitRate(row);
    return row;
  }

  return {
    cagr,
    pctChange,
    value,
    positive,
    incomeRevenue,
    incomeOperatingRevenue,
    incomeInterestIncludedInRevenue,
    incomeFinanceExpenseBeforeInterestIncome,
    incomePeriodExpense,
    incomeGross,
    incomeCoreProfit,
    incomeGrossMargin,
    incomeCoreProfitRate,
    incomeOperatingSignedAdjustmentSum,
    incomeOperatingAdjustmentResidual,
    incomeParentProfit,
    enrichIncomeDerivedFields,
  };
})();
