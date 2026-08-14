const _financeTables = {
  inc: { prefix:'inc', fromId:'incFromYear', toId:'incToYear', periodId:'incPeriod', quarterId:'incQuarter', viewId:'incView', cmpId:'incCompare', wrapId:'tableIncomeWrap', api:'income', sectionsFn:getIncomeSections, tableId:'incMainTable', statusId:'incStatus', dataVar:'_incDataMap', keysVar:'_incKeys', cmpDataVar:'_incCmpDataMap', cmpKeysVar:'_incCmpKeys', cmpCodeVar:'_incCmpCode', cmpNameVar:'_incCmpName' },
  cf:  { prefix:'cf', fromId:'cfFromYear', toId:'cfToYear', periodId:'cfPeriod', quarterId:'cfQuarter', viewId:'cfView', cmpId:'cfCompare', wrapId:'tableCashflowWrap', api:'cashflow', sectionsFn:getCashflowSections, tableId:'cfMainTable', statusId:'cfStatus', dataVar:'_cfDataMap', keysVar:'_cfKeys', cmpDataVar:'_cfCmpDataMap', cmpKeysVar:'_cfCmpKeys', cmpCodeVar:'_cfCmpCode', cmpNameVar:'_cfCmpName' },
};

async function loadFinanceTable(prefix) {
  const t = _financeTables[prefix]; if (!t) return;
  // Auto-set year range to last 10 years including current
  const fy = document.getElementById(t.fromId), ty = document.getElementById(t.toId);
  if (!fy.value) fy.value = new Date().getFullYear() - 9;
  if (!ty.value) ty.value = new Date().getFullYear();

  const code = document.getElementById('detailCode').textContent.trim(); if (!code) return;
  const from = document.getElementById(t.fromId).value;
  const to = document.getElementById(t.toId).value;
  const period = document.getElementById(t.periodId).value;
  const quarter = document.getElementById(t.quarterId).value;
  const view = document.getElementById(t.viewId).value;
  const actualPeriod = period === 'all' ? quarter : period;
  const cmpCodeRaw = document.getElementById(t.cmpId).value.trim();
  const cmpCode = await resolveStockCode(cmpCodeRaw);
  if (code !== document.getElementById('detailCode').textContent.trim()) return;
  const wrap = document.getElementById(t.wrapId);
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    let data = await StockApi.getJson(`/api/stock/${code}/${t.api}?${params}`);
    if (code !== document.getElementById('detailCode').textContent.trim()) return;

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        cmpData = await StockApi.getJson(`/api/stock/${cmpCode}/${t.api}?${params}`);
        const info = await StockApi.getJson('/api/stock/' + cmpCode);
        if (code !== document.getElementById('detailCode').textContent.trim()) return;
        if (!info.error) cmpName = info.name;
      } catch {}
    }
    if (code !== document.getElementById('detailCode').textContent.trim()) return;
    if (!data || data.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无数据，请点击"更新数据"拉取</div>';
      return;
    }
    renderFinanceTable(wrap, data, cmpData, cmpCode, cmpName, t);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">加载失败: ' + e.message + '</div>';
  }
}

function renderFinanceTable(wrap, data, cmpData, cmpCode, cmpName, t) {
  const yoyClass = (y) => { if (y == null) return 'fin-yoy-neutral'; return y > 0 ? 'fin-yoy-up' : (y < 0 ? 'fin-yoy-down' : 'fin-yoy-neutral'); };
  const yoyFmt = (y) => { if (y == null) return '-'; return y.toFixed(1) + '%'; };
  const fmtVal = (v, item) => {
    if (v == null) return '-';
    if (item.isPercent || item.unit === '%') return Number(v).toFixed(2) + '%';
    return Math.abs(v) >= 100 ? Number(v).toFixed(0) : Number(v).toFixed(2);
  };

  if (t.prefix === 'inc') {
    data.forEach(enrichIncomeDerivedFields);
    if (cmpData && cmpData.length > 0) cmpData.forEach(enrichIncomeDerivedFields);
  }

  const periods = new Set(data.map(d => d.report_period || 'FY'));
  const isQuarterly = !(periods.size === 1 && periods.has('FY'));

  const makeKey = (d) => { const rp = d.report_period || 'FY'; return isQuarterly ? d.fiscal_year + '|' + rp : d.fiscal_year + ''; };
  const makePrevKey = (key) => { if (!isQuarterly) return (parseInt(key) - 1) + ''; const [yr, rp] = key.split('|'); return (parseInt(yr) - 1) + '|' + rp; };

  const keys = data.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
  if (!isQuarterly) keys.sort((a, b) => parseInt(b) - parseInt(a));
  else keys.sort(sortFiscalKeysDesc);
  const dataMap = {}; for (const d of data) dataMap[makeKey(d)] = d;
  const years = [...new Set(data.map(d => d.fiscal_year))].sort((a, b) => b - a);

  const sections = t.sectionsFn();
  const allFields = []; for (const sec of sections) for (const it of sec.items) allFields.push(it.field);

  // YoY
  const yoyMap = {};
  for (const key of keys) { const d = dataMap[key]; const prevKey = makePrevKey(key); const prev = dataMap[prevKey]; yoyMap[key] = {}; for (const f of allFields) { yoyMap[key][f] = window.FinancialMetrics.pctChange(d ? d[f] : null, prev ? prev[f] : null); } }

  // Comparison
  let cmpDataMap = {}, cmpKeys = [], cmpYoyMap = {};
  if (cmpData && cmpData.length > 0) {
    for (const d of cmpData) cmpDataMap[makeKey(d)] = d;
    cmpKeys = cmpData.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
    for (const key of cmpKeys) { const d = cmpDataMap[key]; const prevKey = makePrevKey(key); const prev = cmpDataMap[prevKey]; cmpYoyMap[key] = {}; for (const f of allFields) { cmpYoyMap[key][f] = window.FinancialMetrics.pctChange(d ? d[f] : null, prev ? prev[f] : null); } }
  }

  const hasCmp = cmpData && cmpData.length > 0;
  let html = '';
  if (hasCmp) {
    const sn = document.getElementById('detailName').textContent.trim();
    html += `<div style="margin-bottom:8px;font-size:14px;font-weight:600;color:#1a1a2e">${sn}  vs  ${cmpName} (${cmpCode})</div>`;
  }
  const keyLabels = keys.map(k => { if (!isQuarterly) return k; const [yr, rp] = k.split('|'); return periods.size > 1 ? yr + '-' + rp : yr; });

  html += `<table class="fin-table" id="${t.tableId}"><thead><tr>`;
  html += '<th class="sticky-col sticky-header" rowspan="2">科目</th>';
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    const lbl = keyLabels[i];
    if (t.prefix === 'inc') {
      html += `<th class="sticky-header year-header" colspan="2"><span class="bs-period-header"><span>${lbl}</span><button type="button" class="bs-composition-icon income-sankey-icon" data-key="${esc(key)}" title="查看利润流向图" aria-label="查看${esc(lbl)}利润流向图"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h4v3H2z"></path><path d="M10 2h4v3h-4z"></path><path d="M10 11h4v3h-4z"></path><path d="M6 5.5c2 0 2-2 4-2"></path><path d="M6 5.5c2 0 2 7 4 7"></path></svg></button></span></th>`;
    } else {
      html += `<th class="sticky-header year-header" colspan="2">${lbl}</th>`;
    }
  }
  html += '</tr><tr>';
  for (const lbl of keyLabels) { html += '<th class="sticky-header sub-header">原值</th>'; html += '<th class="sticky-header sub-header">同比%</th>'; }
  html += '</tr></thead><tbody>';

  const unitLabel = t.prefix === 'inc' ? '单位：金额亿元，比例%' : '单位：亿元';
  html += `<tr class="unit-row"><td class="sticky-col" style="background:#fafafa;font-weight:500">${unitLabel}</td>`;
  for (const k of keys) { html += '<td style="text-align:center;background:#fafafa">原值</td>'; html += '<td style="text-align:center;background:#fafafa">同比%</td>'; }
  html += '</tr>';

  for (const section of sections) {
    html += `<tr class="section-row"><td class="sticky-col" style="background:#e6f0ff;font-weight:700;font-size:13px;color:#1a1a2e" colspan="${keys.length * 2 + 1}">${section.title}</td></tr>`;
    for (const item of section.items) {
      const bs = item.bold ? 'font-weight:600;' : '';
      html += `<tr><td class="sticky-col" style="${bs}"${hasCmp ? ' rowspan="2"' : ''}>${item.name}<span class="chart-icon" data-field="${item.field}" data-name="${esc(item.name)}" data-prefix="${t.prefix}" title="查看趋势图"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><polyline points="2,13 5,8 8,10 11,4 14,7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span></td>`;
      for (const k of keys) { const d = dataMap[k]; const val = d ? d[item.field] : null; const yoy = yoyMap[k] ? yoyMap[k][item.field] : null; html += `<td style="text-align:right;${bs}">${fmtVal(val, item)}</td>`; html += `<td class="${yoyClass(yoy)}" style="text-align:right">${yoyFmt(yoy)}</td>`; }
      html += '</tr>';
      if (hasCmp) {
        html += '<tr style="background:#fff7e6;color:#fa8c16">';
        for (const k of keys) { const d = cmpDataMap[k]; const val = d ? d[item.field] : null; const yoy = cmpYoyMap[k] ? cmpYoyMap[k][item.field] : null; html += `<td style="text-align:right;background:#fff7e6;color:#fa8c16;${bs}">${fmtVal(val, item)}</td>`; html += `<td class="${yoyClass(yoy)}" style="background:#fff7e6;text-align:right">${yoyFmt(yoy)}</td>`; }
        html += '</tr>';
      }
    }
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;

  window[t.dataVar] = dataMap; window[t.keysVar] = keys;
  window[t.cmpDataVar] = cmpDataMap; window[t.cmpKeysVar] = cmpKeys;
  window[t.cmpCodeVar] = cmpCode; window[t.cmpNameVar] = cmpName;

  wrap.querySelectorAll('.chart-icon').forEach(icon => {
    icon.addEventListener('click', function(e) {
      e.stopPropagation();
      openFinanceChart(this.dataset.field, this.dataset.name, this.dataset.prefix);
    });
  });
  if (t.prefix === 'inc') {
    wrap.querySelectorAll('.income-sankey-icon').forEach(icon => {
      icon.addEventListener('click', function(e) {
        e.stopPropagation();
        openIncomeSankey(this.dataset.key);
      });
    });
  }
}

function incomeValue(row, field) {
  return window.FinancialMetrics.value(row, field);
}

function positiveIncomeValue(row, field) {
  return window.FinancialMetrics.positive(row, field);
}

function incomeRevenueValue(row) {
  return window.FinancialMetrics.incomeRevenue(row);
}

function incomeOperatingRevenueValue(row) {
  return window.FinancialMetrics.incomeOperatingRevenue(row);
}

function incomeInterestIncludedInRevenue(row) {
  return window.FinancialMetrics.incomeInterestIncludedInRevenue(row);
}

function incomeFinanceExpenseBeforeInterestIncomeValue(row) {
  return window.FinancialMetrics.incomeFinanceExpenseBeforeInterestIncome(row);
}

function incomePeriodExpenseValue(row) {
  return window.FinancialMetrics.incomePeriodExpense(row);
}

function incomeGrossValue(row) {
  return window.FinancialMetrics.incomeGross(row);
}

function incomeCoreProfitValue(row) {
  return incomeCoreProfitRawValue(row);
}

function incomeCoreProfitRawValue(row) {
  return window.FinancialMetrics.incomeCoreProfit(row);
}

function enrichIncomeDerivedFields(row) {
  return window.FinancialMetrics.enrichIncomeDerivedFields(row);
}

function incomeOperatingSignedAdjustmentSum(row) {
  return window.FinancialMetrics.incomeOperatingSignedAdjustmentSum(row);
}

function incomeOperatingAdjustmentResidual(row) {
  return window.FinancialMetrics.incomeOperatingAdjustmentResidual(row);
}

function incomeParentProfitValue(row) {
  return window.FinancialMetrics.incomeParentProfit(row);
}

function incomePrevKey(key) {
  if (!key) return null;
  if (key.indexOf('|') === -1) return (parseInt(key) - 1) + '';
  const parts = key.split('|');
  return (parseInt(parts[0]) - 1) + '|' + parts[1];
}

function incomeNodeLabel(name, value, row, prevRow, field) {
  const cur = typeof field === 'function' ? field(row) : incomeValue(row, field);
  const prev = typeof field === 'function' ? field(prevRow) : incomeValue(prevRow, field);
  const displayValue = cur < 0 && Math.abs(Math.abs(cur) - value) < 0.01 ? -value : value;
  const amountText = bsFormatAmount(displayValue);
  let labelText = `{node|${name}}\n{amount|${amountText}}`;
  let tooltipText = name + '\n' + amountText;
  if (field && prev !== 0) {
    const rate = window.FinancialMetrics.pctChange(cur, prev);
    if (Number.isFinite(rate)) {
      const yoyText = (rate >= 0 ? '+' : '') + rate.toFixed(2) + '%';
      labelText += `\n{${rate >= 0 ? 'pos' : 'neg'}|${yoyText}}`;
      tooltipText += '\n' + yoyText;
    }
  }
  return { labelText, tooltipText };
}

function incomeAddNode(nodes, nodeMap, name, value, row, prevRow, field, color, depth) {
  if (!Number.isFinite(value) || value <= 0 || nodeMap[name]) return name;
  nodeMap[name] = true;
  const label = incomeNodeLabel(name, value, row, prevRow, field);
  nodes.push({
    name,
    value,
    depth,
    labelText: label.labelText,
    tooltipText: label.tooltipText,
    itemStyle: { color },
    label: {
      color,
      rich: {
        node: { color },
        amount: { color },
        pos: { color: '#ef4444' },
        neg: { color: '#22a866' },
      }
    }
  });
  return name;
}

function incomeAddLink(links, nodeMap, source, target, value, color, curveness) {
  if (!source || !target || !nodeMap[source] || !nodeMap[target] || !Number.isFinite(value) || value <= 0) return;
  links.push({ source, target, value, lineStyle: { color, opacity: 0.28, curveness: curveness || 0.5 } });
}

async function incomeSankeySegmentRows(key, revenue) {
  const code = document.getElementById('detailCode').textContent.trim();
  const year = parseInt(key, 10);
  if (!code || !Number.isFinite(year)) return [];
  try {
    const params = new URLSearchParams({ from_year: year, to_year: year, dimension: 'product' });
    const payload = await StockApi.getJson(`/api/stock/${code}/segments?${params}`);
    const rows = (payload.data || [])
      .filter(row => row.fiscal_year === year && Number(row.revenue) > 0)
      .sort((a, b) => Number(b.revenue || 0) - Number(a.revenue || 0));
    const topRows = rows.slice(0, 6).map(row => ({ name: row.segment_name, value: Number(row.revenue) }));
    const rest = rows.slice(6).reduce((sum, row) => sum + Number(row.revenue || 0), 0);
    if (rest > 0) topRows.push({ name: '其他业务', value: rest });
    const listed = topRows.reduce((sum, row) => sum + row.value, 0);
    const missing = revenue - listed;
    if (missing > Math.max(revenue * 0.02, 0.01)) topRows.push({ name: '未列示收入', value: missing });
    return topRows;
  } catch (e) {
    return [];
  }
}

async function openIncomeSankey(key) {
  const dataMap = window._incDataMap;
  if (!dataMap || !key || !dataMap[key]) return;

  const row = dataMap[key];
  const prevRow = dataMap[incomePrevKey(key)];
  const stockName = document.getElementById('detailName').textContent.trim();
  const label = bsPeriodLabel(key);

  const red = '#ef4444';
  const green = '#22a866';
  const blue = '#1677ff';
  const amber = '#f59e0b';
  const purple = '#7c3aed';

  const revenue = incomeRevenueValue(row);
  const operatingRevenue = incomeOperatingRevenueValue(row);
  const revenueInterestIncome = positiveIncomeValue(row, 'interest_income');
  const cost = positiveIncomeValue(row, 'cost_of_revenue');
  const interestExpense = positiveIncomeValue(row, 'interest_expense');
  const feeCommissionExpense = positiveIncomeValue(row, 'fee_commission_expense');
  const gross = incomeGrossValue(row);
  const periodExpense = incomePeriodExpenseValue(row);
  const taxSurcharge = positiveIncomeValue(row, 'tax_surcharge');
  const coreProfit = incomeCoreProfitRawValue(row);
  const coreProfitValue = Math.abs(coreProfit);
  const coreProfitColor = coreProfit >= 0 ? red : green;
  const operatingProfit = positiveIncomeValue(row, 'operating_profit');
  const netProfit = positiveIncomeValue(row, 'net_profit');
  const parentProfit = Math.max(incomeParentProfitValue(row), 0);
  const minorityProfitSigned = incomeValue(row, 'minority_profit');
  const minorityProfit = Math.abs(minorityProfitSigned);
  const nonopIncome = positiveIncomeValue(row, 'nonop_income');
  const nonopExpense = positiveIncomeValue(row, 'nonop_expense');
  const incomeTax = positiveIncomeValue(row, 'income_tax');
  const segmentRows = await incomeSankeySegmentRows(key, operatingRevenue);

  const nodes = [];
  const nodeMap = {};
  const links = [];
  const addNode = (name, value, field, color, depth) => incomeAddNode(nodes, nodeMap, name, value, row, prevRow, field, color, depth);
  const addLink = (source, target, value, color, curveness) => incomeAddLink(links, nodeMap, source, target, value, color, curveness);

  const revenueNode = addNode('营业总收入', revenue, 'total_revenue', red, 1);
  for (const segment of segmentRows) {
    const node = addNode(segment.name, segment.value, null, red, 0);
    addLink(node, revenueNode, segment.value, red);
  }
  if (!segmentRows.length) {
    const operatingRevenueNode = addNode('营业收入', operatingRevenue, 'operating_revenue', red, 0);
    addLink(operatingRevenueNode, revenueNode, operatingRevenue, red);
  }
  const revenueInterestNode = addNode('利息收入', revenueInterestIncome, 'interest_income', amber, 0);
  addLink(revenueInterestNode, revenueNode, revenueInterestIncome, amber);

  const grossNode = addNode('毛利', gross, incomeGrossValue, red, 2);
  const costNode = addNode('营业成本', cost, 'cost_of_revenue', green, 2);
  const interestExpenseNode = addNode('利息支出', interestExpense, 'interest_expense', green, 2);
  const feeCommissionExpenseNode = addNode('手续费及佣金支出', feeCommissionExpense, 'fee_commission_expense', green, 2);
  addLink(revenueNode, grossNode, gross, red);
  addLink(revenueNode, costNode, cost, green);
  addLink(revenueNode, interestExpenseNode, interestExpense, green);
  addLink(revenueNode, feeCommissionExpenseNode, feeCommissionExpense, green);

  const nonopIncomeNode = addNode('营业外收入', nonopIncome, 'nonop_income', amber, 4);
  const nonopExpenseNode = addNode('营业外支出', nonopExpense, 'nonop_expense', green, 4);
  const opNode = addNode('营业利润', operatingProfit, 'operating_profit', red, 4);

  const adjustmentDefs = [
    ['其他收益', 'other_income', amber, false],
    ['投资收益', 'invest_income', amber, false],
    ['公允价值变动收益', 'fair_value_change', amber, false],
    ['（财务费用）利息收入', 'finance_interest_income', amber, false],
    ['信用减值损失', 'credit_impairment_loss', green, true],
    ['资产减值损失', 'asset_impairment_loss', green, true],
    ['资产处置收益', 'asset_disposal_income', amber, false],
  ];
  const positiveOperatingAdjustmentLinks = [];
  for (const def of adjustmentDefs) {
    const raw = incomeValue(row, def[1]);
    const signedValue = def[3] ? -Math.abs(raw) : raw;
    const value = Math.abs(signedValue);
    const node = addNode(def[0], value, def[1], def[2], 3);
    if (signedValue >= 0) positiveOperatingAdjustmentLinks.push([node, opNode, value, def[2]]);
    else addLink(opNode, node, value, def[2]);
  }

  const coreNode = addNode('核心利润', coreProfitValue, incomeCoreProfitValue, coreProfitColor, 3);
  if (coreProfit >= 0) {
    addLink(grossNode, coreNode, coreProfitValue, red);
  }

  const residual = incomeOperatingAdjustmentResidual(row);
  const residualValue = Math.abs(residual);
  const hasResidual = residualValue > Math.max(operatingProfit * 0.001, 0.01);
  let residualNode = null;
  let residualColor = null;
  if (hasResidual) {
    residualColor = residual >= 0 ? amber : green;
    const residualDepth = residual >= 0 ? 3 : 4;
    residualNode = addNode('其他营业利润调整项', residualValue, incomeOperatingAdjustmentResidual, residualColor, residualDepth);
    if (residual >= 0) positiveOperatingAdjustmentLinks.push([residualNode, opNode, residualValue, residualColor]);
  }
  positiveOperatingAdjustmentLinks.forEach(link => addLink(link[0], link[1], link[2], link[3], 0.08));
  if (coreProfit >= 0) {
    const coreToOperatingProfit = Math.max(coreProfitValue - (hasResidual && residual < 0 ? residualValue : 0), 0);
    addLink(coreNode, opNode, coreToOperatingProfit, red);
  } else {
    addLink(coreNode, opNode, coreProfitValue, green);
  }
  if (hasResidual && residual < 0) {
    addLink(coreNode, residualNode, residualValue, residualColor);
  }

  const periodNode = addNode('期间费用', periodExpense, incomePeriodExpenseValue, green, 3);
  addLink(grossNode, periodNode, periodExpense, green);
  const taxSurchargeNode = addNode('税金及附加', taxSurcharge, 'tax_surcharge', green, 3);
  addLink(grossNode, taxSurchargeNode, taxSurcharge, green);

  const expenseDefs = [
    ['销售费用', 'selling_expense', null],
    ['管理费用', 'admin_expense', null],
    ['研发费用', 'rd_expense', null],
    ['财务费用', 'finance_expense', incomeFinanceExpenseBeforeInterestIncomeValue],
  ];
  for (const def of expenseDefs) {
    const value = def[2] ? def[2](row) : positiveIncomeValue(row, def[1]);
    const node = addNode(def[0], value, def[2] || def[1], green, 4);
    addLink(periodNode, node, value, green);
  }
  const netNode = addNode('净利润', netProfit, 'net_profit', red, 5);
  const taxNode = addNode('所得税费用', incomeTax, 'income_tax', green, 5);
  const opToNet = Math.max(netProfit - nonopIncome - nonopExpense, 0);
  addLink(nonopIncomeNode, netNode, nonopIncome, amber, 0.85);
  addLink(nonopExpenseNode, netNode, nonopExpense, green, 0.85);
  addLink(opNode, taxNode, incomeTax, green, 0.85);
  addLink(opNode, netNode, opToNet, red);

  const minorityColor = minorityProfitSigned < 0 ? green : purple;
  const parentNode = addNode('归属于母公司普通股股东的净利润', parentProfit, incomeParentProfitValue, blue, 6);
  const minorityDepth = minorityProfitSigned < 0 ? 5 : 6;
  const minorityNode = addNode('少数股东损益', minorityProfit, 'minority_profit', minorityColor, minorityDepth);
  if (minorityProfitSigned < 0) {
    addLink(netNode, parentNode, netProfit, blue);
    addLink(minorityNode, parentNode, minorityProfit, minorityColor);
  } else {
    addLink(netNode, parentNode, parentProfit, blue);
    addLink(netNode, minorityNode, minorityProfit, minorityColor);
  }

  document.getElementById('chartModalTitle').textContent = stockName + ' - ' + label + ' 利润流向图  财报单位：亿元';
  document.getElementById('chartModalOverlay').classList.add('active');

  const dom = prepareChartModalBox();
  renderIncomeSankeyPeriodControls(key);
  dom.classList.add('income-sankey-box');
  const chart = echarts.init(dom);
  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  chart.setOption({
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      confine: false,
      formatter: function(p) {
        if (p.dataType === 'edge') {
          return p.data.source + ' → ' + p.data.target + '<br/>' + bsFormatAmount(p.value);
        }
        return (p.data.tooltipText || p.name).replace(/\n/g, '<br/>');
      }
    },
    series: [{
      type: 'sankey',
      data: nodes,
      links: links,
      draggable: false,
      nodeAlign: 'justify',
      nodeWidth: 18,
      nodeGap: 42,
      layoutIterations: 0,
      emphasis: { focus: 'adjacency' },
      label: {
        formatter: function(p) { return p.data.labelText || p.name; },
        fontSize: 12,
        fontWeight: 600,
        color: isDark ? '#d7dde8' : '#1f2937'
      },
      lineStyle: { curveness: 0.5 }
    }]
  });

  window._chartModalInstance = chart;
}

function openFinanceChart(field, name, prefix) {
  const t = _financeTables[prefix]; if (!t) return;
  const dataMap = window[t.dataVar]; const keys = window[t.keysVar];
  const cmpDataMap = window[t.cmpDataVar]; const cmpCode = window[t.cmpCodeVar]; const cmpName = window[t.cmpNameVar];
  if (!dataMap || !keys) return;

  const stockName = document.getElementById('detailName').textContent.trim();
  let title = stockName + ' - ' + name;
  const sortedKeys = [...keys].sort(sortFiscalKeysAsc);
  const labels = sortedKeys.map(formatFiscalKeyLabel);
  const values = sortedKeys.map(k => { const d = dataMap[k]; return d && d[field] != null ? d[field] : null; });
  const yoyValues = sortedKeys.map((k, i) => i === 0 ? null : window.FinancialMetrics.pctChange(values[i], values[i - 1], 2));

  const cleanVals = values.filter(v => v != null);
  if (cleanVals.length >= 2) { const fv = cleanVals[0], lv = cleanVals[cleanVals.length - 1], n = cleanVals.length - 1; const rate = window.FinancialMetrics.cagr(fv, lv, n, 2); if (rate != null) title += ' (CAGR: ' + rate.toFixed(2) + '%)'; }

  let cmpValues = null;
  if (cmpDataMap) cmpValues = sortedKeys.map(k => { const d = cmpDataMap[k]; return d && d[field] != null ? d[field] : null; });
  if (cmpValues && cmpValues.some(v => v != null)) { title += ' vs ' + (cmpName || cmpCode); const cc = cmpValues.filter(v => v != null); if (cc.length >= 2) { const fv = cc[0], lv = cc[cc.length - 1], n = cc.length - 1; const rate = window.FinancialMetrics.cagr(fv, lv, n, 2); if (rate != null) title += ' (CAGR: ' + rate.toFixed(2) + '%)'; } }

  document.getElementById('chartModalTitle').textContent = title;
  document.getElementById('chartModalOverlay').classList.add('active');
  const dom = prepareChartModalBox();
  const chart = echarts.init(dom); const series = [];
  series.push({ name: stockName, type: 'bar', data: values, yAxisIndex: 0, itemStyle: { color: '#4a6cf7', borderRadius: [4, 4, 0, 0] }, label: { show: true, position: 'top', fontSize: 11, formatter(p) { if (p.value == null) return ''; return Math.abs(p.value) >= 100 ? p.value.toFixed(0) : p.value.toFixed(2); } } });
  if (cmpValues) series.push({ name: cmpName || cmpCode, type: 'bar', data: cmpValues, yAxisIndex: 0, itemStyle: { color: '#fa8c16', borderRadius: [4, 4, 0, 0] }, label: { show: true, position: 'top', fontSize: 11, formatter(p) { if (p.value == null) return ''; return Math.abs(p.value) >= 100 ? p.value.toFixed(0) : p.value.toFixed(2); } } });
  if (sortedKeys.length > 1 && yoyValues.some(v => v != null)) series.push({ name: 'YoY%', type: 'line', data: yoyValues, yAxisIndex: 1, lineStyle: { color: '#52c41a', width: 2, type: 'dashed' }, itemStyle: { color: '#52c41a' }, symbol: 'circle', symbolSize: 5, label: { show: true, position: 'top', fontSize: 10, color: '#52c41a', formatter(p) { if (p.value == null) return ''; return p.value.toFixed(1) + '%'; } } });
  chart.setOption({
    tooltip: { trigger: 'axis', formatter(ps) { let h = '<strong>' + ps[0].axisValue + '</strong><br/>'; for (const p of ps) { h += p.marker + ' ' + p.seriesName + ': ' + (p.value != null ? (p.seriesName === 'YoY%' ? p.value.toFixed(1) + '%' : p.value.toFixed(2) + ' 亿元') : '-') + '<br/>'; } return h; } },
    grid: { left: 60, right: 80, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: labels, name: '年份', nameLocation: 'middle', nameGap: 30 },
    yAxis: [{ type: 'value', name: '亿元' }, { type: 'value', name: '%', axisLabel: { formatter: '{value}%' } }],
    series
  });
  window._chartModalInstance = chart;
}

async function loadIncome() { loadFinanceTable('inc'); }
async function loadCashflow() { loadFinanceTable('cf'); }

async function updateIncome() { updateFinanceTable('inc', '/api/update-income'); }
async function updateCashflow() { updateFinanceTable('cf', '/api/update-cashflow'); }

async function updateFinanceTable(prefix, apiUrl) {
  const t = _financeTables[prefix]; if (!t) return;
  const statusEl = document.getElementById(t.statusId);
  statusEl.textContent = '正在更新数据，请稍候...'; statusEl.style.color = '#1890ff';
  try {
    const data = await StockApi.postJson(apiUrl, { mode: 'incremental' });
    StockApi.watchJob(data, { open: true });
    if (data.background) {
      statusEl.textContent = data.message || '已转入后台任务';
      statusEl.style.color = '#1890ff';
      return;
    }
    if (data.success) { statusEl.textContent = `更新完成: ${data.records_updated} 条`; statusEl.style.color = '#52c41a'; loadFinanceTable(prefix); }
    else { statusEl.textContent = '更新失败'; statusEl.style.color = '#ff4d4f'; }
  } catch (e) { statusEl.textContent = '请求失败: ' + e.message; statusEl.style.color = '#ff4d4f'; }
}

// ==================== 指标趋势图弹窗 ====================

