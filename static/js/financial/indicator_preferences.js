const FINANCIAL_DEFAULT_INDICATORS = [
  { name: '营业总收入', field: 'total_revenue', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '核心利润', field: 'operate_profit', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '核心利润率', field: 'core_profit_rate', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '归母净利润', field: 'parent_profit', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '扣非净利润', field: 'deducted_profit', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '净利润率', field: 'net_profit_rate', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '经营现金流/净利润', field: 'cashflow_to_profit', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: 'ROE', field: 'roe', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '扣非ROE', field: 'deducted_roe', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: 'ROIC', field: 'roic', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '经营活动现金流量净额', field: 'operate_cashflow', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '总资产', field: 'total_assets', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '归母权益', field: 'total_equity', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '总股本', field: 'total_shares', unit: '亿股', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '分红金额', field: 'dividend_amount', unit: '亿元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '每股分红', field: 'dividend_per_share', unit: '元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '分红率', field: 'dividend_payout_ratio', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '归母普通股每股收益', field: 'basic_eps', unit: '元', isPercent: false, showYoy: true, source: '自定义财报' },
  { name: '股息率', field: 'dividend_yield_fin', unit: '%', isPercent: true, showYoy: false, source: '自定义财报' },
  { name: '资产负债率', field: 'debt_ratio', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
  { name: '有息负债率', field: 'interest_bearing_debt_ratio', unit: '%', isPercent: true, showYoy: true, source: '自定义财报' },
];

const FINANCIAL_EXTRA_INDICATORS = [
  { name: '货币资金', field: 'bs_monetary_funds', unit: '亿元', source: '资产负债表' },
  { name: '应收账款', field: 'bs_accounts_receivable', unit: '亿元', source: '资产负债表' },
  { name: '存货', field: 'bs_inventory', unit: '亿元', source: '资产负债表' },
  { name: '固定资产', field: 'bs_fixed_assets', unit: '亿元', source: '资产负债表' },
  { name: '商誉', field: 'bs_goodwill', unit: '亿元', source: '资产负债表' },
  { name: '商誉/归母权益', field: 'bs_goodwill_to_parent_equity', unit: '%', isPercent: true, source: '资产负债表' },
  { name: '资产负债表总资产', field: 'bs_total_assets', unit: '亿元', source: '资产负债表' },
  { name: '负债合计', field: 'bs_total_liabilities', unit: '亿元', source: '资产负债表' },
  { name: '资产负债表归母权益', field: 'bs_parent_equity', unit: '亿元', source: '资产负债表' },
  { name: '短期借款', field: 'bs_short_borrow', unit: '亿元', source: '资产负债表' },
  { name: '长期借款', field: 'bs_long_borrow', unit: '亿元', source: '资产负债表' },
  { name: '应付债券', field: 'bs_bonds_payable', unit: '亿元', source: '资产负债表' },
  { name: '利润表营业收入', field: 'inc_operating_revenue', unit: '亿元', source: '利润表' },
  { name: '营业成本', field: 'inc_cost_of_revenue', unit: '亿元', source: '利润表' },
  { name: '毛利率', field: 'inc_gross_margin', unit: '%', isPercent: true, source: '利润表' },
  { name: '销售费用', field: 'inc_selling_expense', unit: '亿元', source: '利润表' },
  { name: '管理费用', field: 'inc_admin_expense', unit: '亿元', source: '利润表' },
  { name: '研发费用', field: 'inc_rd_expense', unit: '亿元', source: '利润表' },
  { name: '财务费用', field: 'inc_finance_expense', unit: '亿元', source: '利润表' },
  { name: '投资收益', field: 'inc_invest_income', unit: '亿元', source: '利润表' },
  { name: '利润表营业利润', field: 'inc_operating_profit', unit: '亿元', source: '利润表' },
  { name: '利润总额', field: 'inc_total_profit', unit: '亿元', source: '利润表' },
  { name: '利润表归母净利润', field: 'inc_parent_net_profit', unit: '亿元', source: '利润表' },
  { name: '利润表基本EPS', field: 'inc_basic_eps', unit: '元', source: '利润表' },
  { name: '销售商品收到现金', field: 'cf_cf_sales_goods', unit: '亿元', source: '现金流量表' },
  { name: '现金流表经营现金流净额', field: 'cf_cf_oper_net', unit: '亿元', source: '现金流量表' },
  { name: '购建固定资产等支付现金', field: 'cf_cf_buy_assets', unit: '亿元', source: '现金流量表' },
  { name: '自由现金流', field: 'cf_free_cashflow', unit: '亿元', source: '现金流量表' },
  { name: '投资现金流净额', field: 'cf_cf_invest_net', unit: '亿元', source: '现金流量表' },
  { name: '筹资现金流入小计', field: 'cf_cf_finance_inflow', unit: '亿元', source: '现金流量表' },
  { name: '偿还债务支付现金', field: 'cf_cf_repay_debt', unit: '亿元', source: '现金流量表' },
  { name: '分配股利利润或偿付利息现金', field: 'cf_cf_dividend_interest', unit: '亿元', source: '现金流量表' },
  { name: '筹资现金流净额', field: 'cf_cf_finance_net', unit: '亿元', source: '现金流量表' },
];

let financialIndicatorPreferencesLoaded = false;
let financialIndicatorPreferencesLoading = null;

function getFinancialIndicatorCatalog() {
  return [...FINANCIAL_DEFAULT_INDICATORS, ...FINANCIAL_EXTRA_INDICATORS].map(ind => ({
    showYoy: true,
    isPercent: ind.unit === '%',
    ...ind
  }));
}

function getFinancialDefaultFields() {
  return FINANCIAL_DEFAULT_INDICATORS.map(ind => ind.field);
}

function isFinancialLockedIndicator(field) {
  return getFinancialDefaultFields().includes(field);
}

function normalizeFinancialVisibleFields(fields) {
  const catalog = getFinancialIndicatorCatalog();
  const valid = new Set(catalog.map(ind => ind.field));
  const defaults = getFinancialDefaultFields();
  const seen = new Set();
  const cleaned = [];

  if (Array.isArray(fields)) {
    fields.forEach(field => {
      if (!valid.has(field) || seen.has(field)) return;
      seen.add(field);
      cleaned.push(field);
    });
  }

  defaults.forEach(field => {
    if (!seen.has(field)) {
      seen.add(field);
      cleaned.push(field);
    }
  });

  return cleaned;
}

function getFinancialVisibleFields() {
  try {
    const saved = JSON.parse(localStorage.getItem('financials-visible-indicators') || 'null');
    if (Array.isArray(saved) && saved.length) return normalizeFinancialVisibleFields(saved);
  } catch (e) {}
  try {
    const oldOrder = JSON.parse(localStorage.getItem('financials-indicator-order') || 'null');
    if (Array.isArray(oldOrder) && oldOrder.length) return normalizeFinancialVisibleFields(oldOrder);
  } catch (e) {}
  return getFinancialDefaultFields();
}

function localFinancialSavedFields() {
  for (const key of ['financials-visible-indicators', 'financials-indicator-order']) {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || 'null');
      if (Array.isArray(saved) && saved.length) return saved;
    } catch (e) {}
  }
  return null;
}

async function ensureFinancialIndicatorPreferencesLoaded() {
  if (financialIndicatorPreferencesLoaded) return;
  if (financialIndicatorPreferencesLoading) return financialIndicatorPreferencesLoading;
  financialIndicatorPreferencesLoading = (async () => {
    try {
      const res = await fetch('/api/preferences/financial-indicators');
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || '读取自定义财报配置失败');
      if (Array.isArray(data.fields) && data.fields.length) {
        const normalized = normalizeFinancialVisibleFields(data.fields);
        localStorage.setItem('financials-visible-indicators', JSON.stringify(normalized));
        localStorage.setItem('financials-indicator-order', JSON.stringify(normalized));
      } else {
        const localSaved = localFinancialSavedFields();
        if (localSaved && localSaved.length) {
          await saveFinancialIndicatorPreferences(normalizeFinancialVisibleFields(localSaved));
        }
      }
    } catch (e) {
    } finally {
      financialIndicatorPreferencesLoaded = true;
      financialIndicatorPreferencesLoading = null;
    }
  })();
  return financialIndicatorPreferencesLoading;
}

async function saveFinancialIndicatorPreferences(fields) {
  try {
    await fetch('/api/preferences/financial-indicators', {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({fields})
    });
  } catch (e) {}
}

function setFinancialVisibleFields(fields, options = {}) {
  const cleaned = normalizeFinancialVisibleFields(fields);
  localStorage.setItem('financials-visible-indicators', JSON.stringify(cleaned));
  localStorage.setItem('financials-indicator-order', JSON.stringify(cleaned));
  if (!options.localOnly) saveFinancialIndicatorPreferences(cleaned);
}

function getFinancialVisibleIndicators() {
  const catalog = getFinancialIndicatorCatalog();
  const map = {};
  catalog.forEach(ind => map[ind.field] = ind);
  const fields = getFinancialVisibleFields();
  const result = fields.map(f => map[f]).filter(Boolean);
  return result.length ? result : catalog.filter(ind => getFinancialDefaultFields().includes(ind.field));
}

function populateFinancialIndicatorPicker() {
  const select = document.getElementById('finAddIndicator');
  if (!select) return;
  const visible = new Set(getFinancialVisibleFields());
  const groups = {};
  getFinancialIndicatorCatalog().forEach(ind => {
    if (visible.has(ind.field)) return;
    const group = ind.source || '其他';
    if (!groups[group]) groups[group] = [];
    groups[group].push(ind);
  });
  const html = Object.keys(groups).map(group => `
    <optgroup label="${esc(group)}">
      ${groups[group].map(ind => `<option value="${esc(ind.field)}">${esc(ind.name)}</option>`).join('')}
    </optgroup>
  `).join('');
  select.innerHTML = html || '<option value="">没有可添加指标</option>';
}

function addFinancialIndicator() {
  const select = document.getElementById('finAddIndicator');
  const field = select ? select.value : '';
  if (!field) return;
  const fields = getFinancialVisibleFields();
  if (!fields.includes(field)) fields.push(field);
  setFinancialVisibleFields(fields);
  loadFinancials();
}

function removeFinancialIndicator(field) {
  if (isFinancialLockedIndicator(field)) {
    showToast('自定义财报指标不能删除', 'error');
    return;
  }
  const fields = getFinancialVisibleFields().filter(f => f !== field);
  if (!fields.length) {
    showToast('至少保留一个指标', 'error');
    return;
  }
  setFinancialVisibleFields(fields);
  loadFinancials();
}

function resetFinancialIndicators() {
  setFinancialVisibleFields(getFinancialDefaultFields());
  loadFinancials();
}

function financialSourceShortName(source) {
  const map = {
    '自定义财报': '自',
    '资产负债表': '资',
    '利润表': '利',
    '现金流量表': '现',
  };
  return map[source] || (source ? source.substring(0, 1) : '');
}

