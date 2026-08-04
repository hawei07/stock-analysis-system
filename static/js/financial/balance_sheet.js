async function loadBalanceSheet() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const from = document.getElementById('bsFromYear').value;
  const to = document.getElementById('bsToYear').value;
  const period = document.getElementById('bsPeriod').value;
  const quarter = document.getElementById('bsQuarter').value;
  const view = document.getElementById('bsView').value;
  const actualPeriod = period === 'all' ? quarter : period;
  const cmpCodeRaw = document.getElementById('bsCompare').value.trim();
  const cmpCode = await resolveStockCode(cmpCodeRaw);
  if (code !== document.getElementById('detailCode').textContent.trim()) return;
  const wrap = document.getElementById('tableBalanceSheetWrap');
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    const res = await fetch(`/api/stock/${code}/balance-sheet?${params}`);
    let data = await res.json();
    if (code !== document.getElementById('detailCode').textContent.trim()) return;

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        const cmpRes = await fetch(`/api/stock/${cmpCode}/balance-sheet?${params}`);
        cmpData = await cmpRes.json();
        const infoRes = await fetch('/api/stock/' + cmpCode);
        const info = await infoRes.json();
        if (code !== document.getElementById('detailCode').textContent.trim()) return;
        if (!info.error) cmpName = info.name;
      } catch {}
    }
    if (code !== document.getElementById('detailCode').textContent.trim()) return;
    if (!data || data.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无资产负债表数据，请点击"更新数据"拉取</div>';
      return;
    }
    renderBalanceSheetTable(data, cmpData, cmpCode, cmpName);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">加载失败: ' + e.message + '</div>';
  }
}

function renderBalanceSheetTable(data, cmpData, cmpCode, cmpName) {
  const wrap = document.getElementById('tableBalanceSheetWrap');

  // Helper functions
  const yoyClass = (y) => {
    if (y == null) return 'fin-yoy-neutral';
    return y > 0 ? 'fin-yoy-up' : (y < 0 ? 'fin-yoy-down' : 'fin-yoy-neutral');
  };
  const yoyFmt = (y) => {
    if (y == null) return '-';
    return y.toFixed(1) + '%';
  };

  // Quarterly detection: check ALL report_periods
  const periods = new Set(data.map(d => d.report_period || 'FY'));
  const isQuarterly = !(periods.size === 1 && periods.has('FY'));

  // Build composite key maps
  const makeKey = (d) => {
    const rp = d.report_period || 'FY';
    return isQuarterly ? d.fiscal_year + '|' + rp : d.fiscal_year + '';
  };
  const makePrevKey = (key) => {
    if (!isQuarterly) return (parseInt(key) - 1) + '';
    const [year, period] = key.split('|');
    return (parseInt(year) - 1) + '|' + period;
  };

  const keys = data.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
  if (!isQuarterly) {
    keys.sort((a, b) => parseInt(b) - parseInt(a));
  }
  const dataMap = {};
  for (const d of data) dataMap[makeKey(d)] = d;
  const years = [...new Set(data.map(d => d.fiscal_year))].sort((a, b) => b - a);

  // 资产负债表科目分组
  const sections = [
    {
      title: '流动资产',
      items: [
        { name: '货币资金', field: 'monetary_funds' },
        { name: '交易性金融资产', field: 'trading_fin_assets' },
        { name: '应收票据', field: 'notes_receivable' },
        { name: '应收账款', field: 'accounts_receivable' },
        { name: '应收款项融资', field: 'receivables_financing' },
        { name: '预付款项', field: 'prepayment' },
        { name: '其他应收款', field: 'other_receivables' },
        { name: '存货', field: 'inventory' },
        { name: '一年内到期的非流动资产', field: 'noncurrent_assets_due1y' },
        { name: '其他流动资产', field: 'other_current_assets' },
        { name: '流动资产合计', field: 'total_current_assets', bold: true },
      ]
    },
    {
      title: '非流动资产',
      items: [
        { name: '持有至到期投资', field: 'held_to_maturity_invest' },
        { name: '长期股权投资', field: 'longterm_equity_invest' },
        { name: '投资性房地产', field: 'investment_property' },
        { name: '在建工程', field: 'cip' },
        { name: '固定资产', field: 'fixed_assets' },
        { name: '使用权资产', field: 'right_of_use_assets' },
        { name: '无形资产', field: 'intangible_assets' },
        { name: '开发支出', field: 'development_expenditure' },
        { name: '商誉', field: 'goodwill' },
        { name: '长期待摊费用', field: 'longterm_prepaid_expense' },
        { name: '递延所得税资产', field: 'deferred_tax_assets' },
        { name: '其他非流动资产', field: 'other_noncurrent_assets' },
        { name: '非流动资产合计', field: 'total_noncurrent_assets', bold: true },
      ]
    },
    {
      title: '资产总计',
      items: [
        { name: '资产总计', field: 'total_assets', bold: true },
      ]
    },
    {
      title: '流动负债',
      items: [
        { name: '短期借款', field: 'short_borrow' },
        { name: '应付票据', field: 'notes_payable' },
        { name: '应付账款', field: 'accounts_payable' },
        { name: '预收款项', field: 'advance_receipts' },
        { name: '应付职工薪酬', field: 'payroll_payable' },
        { name: '应交税费', field: 'taxes_payable' },
        { name: '其他应付款', field: 'other_payables' },
        { name: '一年内到期的非流动负债', field: 'noncurrent_liab_due1y' },
        { name: '其他流动负债', field: 'other_current_liabilities' },
        { name: '流动负债合计', field: 'total_current_liabilities', bold: true },
      ]
    },
    {
      title: '非流动负债',
      items: [
        { name: '长期借款', field: 'long_borrow' },
        { name: '应付债券', field: 'bonds_payable' },
        { name: '租赁负债', field: 'lease_liabilities' },
        { name: '递延所得税负债', field: 'deferred_tax_liabilities' },
        { name: '非流动负债合计', field: 'total_noncurrent_liabilities', bold: true },
      ]
    },
    {
      title: '负债合计',
      items: [
        { name: '负债合计', field: 'total_liabilities', bold: true },
      ]
    },
    {
      title: '股东权益',
      items: [
        { name: '实收资本（股本）', field: 'paid_in_capital' },
        { name: '资本公积', field: 'capital_reserve' },
        { name: '减：库存股', field: 'treasury_stock' },
        { name: '盈余公积', field: 'surplus_reserve' },
        { name: '未分配利润', field: 'retained_earnings' },
        { name: '归母股东权益合计', field: 'parent_equity', bold: true },
        { name: '少数股东权益', field: 'minority_interests' },
        { name: '股东权益合计', field: 'total_equity', bold: true },
      ]
    }
  ];

  // Collect all BS fields for YoY calculation
  const bsFields = [];
  for (const section of sections) {
    for (const item of section.items) {
      bsFields.push(item.field);
    }
  }

  // YoY map
  const yoyMap = {};
  for (const key of keys) {
    const d = dataMap[key];
    const prevKey = makePrevKey(key);
    const prev = dataMap[prevKey];
    yoyMap[key] = {};
    for (const f of bsFields) {
      const cur = d[f];
      if (cur == null || !prev || prev[f] == null || prev[f] === 0) { yoyMap[key][f] = null; continue; }
      yoyMap[key][f] = (cur - prev[f]) / Math.abs(prev[f]) * 100;
    }
  }

  // Comparison data maps
  let cmpDataMap = {}, cmpKeys = [], cmpYoyMap = {};
  if (cmpData && cmpData.length > 0) {
    for (const d of cmpData) cmpDataMap[makeKey(d)] = d;
    cmpKeys = cmpData.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
    for (const key of cmpKeys) {
      const d = cmpDataMap[key];
      const prevKey = makePrevKey(key);
      const prev = cmpDataMap[prevKey];
      cmpYoyMap[key] = {};
      for (const f of bsFields) {
        const cur = d[f];
        if (cur == null || !prev || prev[f] == null || prev[f] === 0) { cmpYoyMap[key][f] = null; continue; }
        cmpYoyMap[key][f] = (cur - prev[f]) / Math.abs(prev[f]) * 100;
      }
    }
  }

  const hasCmp = cmpData && cmpData.length > 0;
  let html = '';
  if (hasCmp) {
    const stockName = document.getElementById('detailName').textContent.trim();
    html += `<div style="margin-bottom:8px;font-size:14px;font-weight:600;color:#1a1a2e">${stockName}  vs  ${cmpName} (${cmpCode})</div>`;
  }

  // Build display labels from keys
  const keyLabels = keys.map(k => {
    if (!isQuarterly) return k;
    const [yr, rp] = k.split('|');
    return periods.size > 1 ? yr + '-' + rp : yr;
  });

  // Table header: rowspan="2" with colspan="2" per key
  html += '<table class="fin-table" id="bsMainTable"><thead><tr>';
  html += '<th class="sticky-col sticky-header" rowspan="2">科目</th>';
  for (let i = 0; i < keys.length; i++) {
    const key = keys[i];
    const lbl = keyLabels[i];
    html += `<th class="sticky-header year-header" colspan="2"><span class="bs-period-header"><span>${lbl}</span><button type="button" class="bs-composition-icon" data-key="${esc(key)}" title="查看资产/负债构成" aria-label="查看${esc(lbl)}资产/负债构成"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5v6.5h6.5A6.5 6.5 0 0 0 8 1.5Z"></path><path d="M7 2.5A6 6 0 1 0 13.5 9H7V2.5Z"></path></svg></button></span></th>`;
  }
  html += '</tr><tr>';
  for (const lbl of keyLabels) {
    html += '<th class="sticky-header sub-header">原值</th>';
    html += '<th class="sticky-header sub-header">同比%</th>';
  }
  html += '</tr></thead><tbody>';

  // Unit row
  html += '<tr class="unit-row"><td class="sticky-col" style="background:#fafafa;font-weight:500">单位：亿元</td>';
  for (const k of keys) {
    html += '<td style="text-align:center;background:#fafafa">亿元</td>';
    html += '<td style="text-align:center;background:#fafafa">%</td>';
  }
  html += '</tr>';

  for (const section of sections) {
    // Section header: colspan = keys.length * 2 + 1
    html += `<tr class="section-row"><td class="sticky-col" style="background:#e6f0ff;font-weight:700;font-size:13px;color:#1a1a2e" colspan="${keys.length * 2 + 1}">${section.title}</td></tr>`;
    for (const item of section.items) {
      const boldStyle = item.bold ? 'font-weight:600;' : '';
      // Main stock row
      html += `<tr><td class="sticky-col" style="${boldStyle}"${hasCmp ? ' rowspan="2"' : ''}>${item.name}<span class="chart-icon" data-field="${item.field}" data-name="${esc(item.name)}" title="查看趋势图"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><polyline points="2,13 5,8 8,10 11,4 14,7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span></td>`;
      for (const k of keys) {
        const d = dataMap[k];
        const val = d ? d[item.field] : null;
        const yoy = yoyMap[k] ? yoyMap[k][item.field] : null;
        let display = '-';
        if (val != null) {
          display = Math.abs(val) >= 100 ? val.toFixed(0) : val.toFixed(2);
        }
        html += `<td style="text-align:right;${boldStyle}">${display}</td>`;
        html += `<td class="${yoyClass(yoy)}" style="text-align:right">${yoyFmt(yoy)}</td>`;
      }
      html += '</tr>';

      // Comparison row
      if (hasCmp) {
        html += '<tr style="background:#fff7e6;color:#fa8c16">';
        for (const k of keys) {
          const d = cmpDataMap[k];
          const val = d ? d[item.field] : null;
          const yoy = cmpYoyMap[k] ? cmpYoyMap[k][item.field] : null;
          let display = '-';
          if (val != null) {
            display = Math.abs(val) >= 100 ? val.toFixed(0) : val.toFixed(2);
          }
          html += `<td style="text-align:right;background:#fff7e6;color:#fa8c16;${boldStyle}">${display}</td>`;
          html += `<td class="${yoyClass(yoy)}" style="background:#fff7e6;text-align:right">${yoyFmt(yoy)}</td>`;
        }
        html += '</tr>';
      }
    }
  }

  html += '</tbody></table>';
  wrap.innerHTML = html;

  // Expose data for chart modal (now uses composite keys)
  window._bsDataMap = dataMap;
  window._bsKeys = keys;
  window._bsYears = years;
  window._bsCmpDataMap = cmpDataMap;
  window._bsCmpKeys = cmpKeys;
  window._bsCmpCode = cmpCode;
  window._bsCmpName = cmpName;

  // Bind chart icon click events
  wrap.querySelectorAll('.chart-icon').forEach(icon => {
    icon.addEventListener('click', function(e) {
      e.stopPropagation();
      openBSChart(this.dataset.field, this.dataset.name);
    });
  });
  wrap.querySelectorAll('.bs-composition-icon').forEach(icon => {
    icon.addEventListener('click', function(e) {
      e.stopPropagation();
      openBSComposition(this.dataset.key);
    });
  });
}

const _bsCompositionDefs = {
  assets: [
    { name: '货币资金', field: 'monetary_funds' },
    { name: '交易性金融资产', field: 'trading_fin_assets' },
    { name: '应收票据', field: 'notes_receivable' },
    { name: '应收账款', field: 'accounts_receivable' },
    { name: '应收款项融资', field: 'receivables_financing' },
    { name: '预付款项', field: 'prepayment' },
    { name: '其他应收款', field: 'other_receivables' },
    { name: '存货', field: 'inventory' },
    { name: '一年内到期的非流动资产', field: 'noncurrent_assets_due1y' },
    { name: '其他流动资产', field: 'other_current_assets' },
    { name: '持有至到期投资', field: 'held_to_maturity_invest' },
    { name: '长期股权投资', field: 'longterm_equity_invest' },
    { name: '投资性房地产', field: 'investment_property' },
    { name: '在建工程', field: 'cip' },
    { name: '固定资产', field: 'fixed_assets' },
    { name: '使用权资产', field: 'right_of_use_assets' },
    { name: '无形资产', field: 'intangible_assets' },
    { name: '开发支出', field: 'development_expenditure' },
    { name: '商誉', field: 'goodwill' },
    { name: '长期待摊费用', field: 'longterm_prepaid_expense' },
    { name: '递延所得税资产', field: 'deferred_tax_assets' },
    { name: '其他非流动资产', field: 'other_noncurrent_assets' },
  ],
  liabilities: [
    { name: '短期借款', field: 'short_borrow' },
    { name: '应付票据', field: 'notes_payable' },
    { name: '应付账款', field: 'accounts_payable' },
    { name: '预收款项', field: 'advance_receipts' },
    { name: '应付职工薪酬', field: 'payroll_payable' },
    { name: '应交税费', field: 'taxes_payable' },
    { name: '其他应付款', field: 'other_payables' },
    { name: '一年内到期的非流动负债', field: 'noncurrent_liab_due1y' },
    { name: '其他流动负债', field: 'other_current_liabilities' },
    { name: '长期借款', field: 'long_borrow' },
    { name: '应付债券', field: 'bonds_payable' },
    { name: '租赁负债', field: 'lease_liabilities' },
    { name: '递延所得税负债', field: 'deferred_tax_liabilities' },
  ],
  assetFallback: [
    { name: '流动资产', field: 'total_current_assets' },
    { name: '非流动资产', field: 'total_noncurrent_assets' },
  ],
  liabilityFallback: [
    { name: '流动负债', field: 'total_current_liabilities' },
    { name: '非流动负债', field: 'total_noncurrent_liabilities' },
  ],
};

function bsPeriodLabel(key) {
  if (!key) return '';
  if (key.indexOf('|') === -1) return key;
  const parts = key.split('|');
  return parts[0] + '-' + parts[1];
}

function bsCompositionItems(row, defs, fallbackDefs) {
  const items = defs.map(def => {
    const value = Number(row[def.field]);
    return { name: def.name, value };
  }).filter(item => Number.isFinite(item.value) && item.value > 0);
  if (items.length) return items;
  return fallbackDefs.map(def => {
    const value = Number(row[def.field]);
    return { name: def.name, value };
  }).filter(item => Number.isFinite(item.value) && item.value > 0);
}

function bsCompositionTotal(items) {
  return items.reduce((sum, item) => sum + item.value, 0);
}

function bsFillRemainder(items, total, name) {
  if (!Number.isFinite(total) || total <= 0) return items;
  const itemTotal = bsCompositionTotal(items);
  const remainder = total - itemTotal;
  if (remainder > Math.max(total * 0.005, 0.01)) {
    return [...items, { name, value: remainder }];
  }
  return items;
}

function bsGroupItems(row, defs, total, remainderName) {
  const items = defs.map(def => {
    const value = Number(row[def.field]);
    return { name: def.name, value };
  }).filter(item => Number.isFinite(item.value) && item.value > 0);
  return bsFillRemainder(items, total, remainderName);
}

function prepareChartModalBox() {
  const dom = document.getElementById('chartModalBox');
  setChartModalControls('');
  if (window._chartModalInstances) {
    window._chartModalInstances.forEach(chart => {
      if (chart) chart.dispose();
    });
    window._chartModalInstances = null;
  }
  if (window._chartModalInstance) {
    window._chartModalInstance.dispose();
    window._chartModalInstance = null;
  }
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  dom.innerHTML = '';
  dom.classList.remove('bs-composition-box');
  dom.classList.remove('income-sankey-box');
  return dom;
}

function setChartModalControls(html) {
  const controls = document.getElementById('chartModalControls');
  if (!controls) return;
  controls.innerHTML = html || '';
  controls.style.display = html ? 'flex' : 'none';
}

function incomeSankeySortedKeys() {
  const keys = window._incKeys || [];
  return [...keys].sort(sortFiscalKeysAsc);
}

function renderIncomeSankeyPeriodControls(activeKey) {
  const keys = incomeSankeySortedKeys();
  if (!keys.length) {
    setChartModalControls('');
    return;
  }
  const index = keys.indexOf(activeKey);
  const options = keys.map(key => `<option value="${esc(key)}"${key === activeKey ? ' selected' : ''}>${esc(bsPeriodLabel(key))}</option>`).join('');
  setChartModalControls(`
    <button class="period-btn" type="button" onclick="stepIncomeSankeyPeriod(-1)"${index <= 0 ? ' disabled' : ''}>上一期</button>
    <select id="incomeSankeyPeriodSelect" data-active-key="${esc(activeKey)}" onchange="switchIncomeSankeyPeriod(this.value)">
      ${options}
    </select>
    <button class="period-btn" type="button" onclick="stepIncomeSankeyPeriod(1)"${index < 0 || index >= keys.length - 1 ? ' disabled' : ''}>下一期</button>
  `);
}

function switchIncomeSankeyPeriod(key) {
  if (key) openIncomeSankey(key);
}

function stepIncomeSankeyPeriod(delta) {
  const select = document.getElementById('incomeSankeyPeriodSelect');
  const activeKey = select?.dataset.activeKey || select?.value;
  const keys = incomeSankeySortedKeys();
  const index = keys.indexOf(activeKey);
  if (index < 0) return;
  const nextKey = keys[index + delta];
  if (nextKey) openIncomeSankey(nextKey);
}

function bsSafeTotal(row, preferredField, fallbackTotal) {
  const value = Number(row[preferredField]);
  if (Number.isFinite(value) && value > 0) return value;
  return fallbackTotal;
}

function bsFormatAmount(value) {
  if (!Number.isFinite(value)) return '-';
  return Math.abs(value) >= 100 ? value.toFixed(2) + '亿' : value.toFixed(2) + '亿';
}

function bsFormatPercent(value, total) {
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0) return '-';
  return (value / total * 100).toFixed(2) + '%';
}

const _bsCompositionPalette = [
  '#1677ff', '#ff4d4f', '#52c41a', '#fa8c16', '#722ed1', '#13c2c2',
  '#eb2f96', '#a0d911', '#faad14', '#2f54eb', '#fa541c', '#08979c',
  '#531dab', '#ad6800', '#389e0d', '#c41d7f', '#0958d9', '#d4380d',
];

function bsColorItems(items) {
  return items.map((item, index) => ({
    ...item,
    itemStyle: { color: item.color || (item.itemStyle && item.itemStyle.color) || _bsCompositionPalette[index % _bsCompositionPalette.length] },
  }));
}

function bsCompositionTableRows(items, groupTotal, baseTotal) {
  if (!items.length) return '<tr><td colspan="4" class="bs-composition-empty">暂无明细数据</td></tr>';
  return items.map((item, index) => (
    `<tr class="bs-composition-data-row" data-pie-index="${index}" style="--bs-row-color:${item.itemStyle.color}"><td>${esc(item.name)}</td><td>${bsFormatAmount(item.value)}</td><td>${bsFormatPercent(item.value, groupTotal)}</td><td>${bsFormatPercent(item.value, baseTotal)}</td></tr>`
  )).join('');
}

function renderBSCompositionSection(container, id, title, items, groupTotal, baseTotal, summaryLabel) {
  const chartId = 'bsCompositionPie' + id;
  const coloredItems = bsColorItems(items);
  const dimPieItems = (activeIndex) => coloredItems.map((item, index) => ({
    ...item,
    itemStyle: {
      ...item.itemStyle,
      opacity: activeIndex == null || index === activeIndex ? 1 : 0.18,
    },
  }));
  container.insertAdjacentHTML('beforeend', `
    <section class="bs-composition-section">
      <div class="bs-composition-pie" id="${chartId}"></div>
      <div class="bs-composition-table-wrap">
        <h4>${esc(title)}</h4>
        <table class="bs-composition-table">
          <colgroup><col class="bs-col-subject"><col class="bs-col-amount"><col class="bs-col-group"><col class="bs-col-total"></colgroup>
          <thead><tr><th>科目</th><th>金额</th><th>占本组</th><th>占总资产</th></tr></thead>
          <tbody>${bsCompositionTableRows(coloredItems, groupTotal, baseTotal)}</tbody>
          <tfoot><tr><td>${esc(summaryLabel)}</td><td>${bsFormatAmount(groupTotal)}</td><td>100%</td><td>${bsFormatPercent(groupTotal, baseTotal)}</td></tr></tfoot>
        </table>
      </div>
    </section>
  `);
  const chartDom = document.getElementById(chartId);
  const chart = echarts.init(chartDom);
  chart.setOption({
    tooltip: {
      trigger: 'item',
      appendToBody: true,
      confine: false,
      formatter: function(p) {
        return p.seriesName + '<br/>' + p.marker + ' ' + p.name + ': ' + bsFormatAmount(p.value) + ' (' + p.percent.toFixed(2) + '%)';
      }
    },
    series: [{
      name: title,
      type: 'pie',
      radius: ['0%', '72%'],
      center: ['50%', '50%'],
      minAngle: 4,
      label: { show: false },
      labelLine: { show: false },
      emphasis: {
        scale: true,
        scaleSize: 14,
        itemStyle: { shadowBlur: 18, shadowColor: 'rgba(0,0,0,.28)' }
      },
      data: coloredItems
    }]
  });
  chartDom.closest('.bs-composition-section').querySelectorAll('.bs-composition-data-row').forEach(row => {
    row.addEventListener('mouseenter', function() {
      const dataIndex = Number(this.dataset.pieIndex);
      if (!Number.isFinite(dataIndex)) return;
      chart.setOption({ series: [{ data: dimPieItems(dataIndex) }] });
      chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex });
      chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex });
      this.classList.add('active');
    });
    row.addEventListener('mouseleave', function() {
      const dataIndex = Number(this.dataset.pieIndex);
      if (!Number.isFinite(dataIndex)) return;
      chart.dispatchAction({ type: 'downplay', seriesIndex: 0, dataIndex });
      chart.dispatchAction({ type: 'hideTip' });
      chart.setOption({ series: [{ data: coloredItems }] });
      this.classList.remove('active');
    });
  });
  return chart;
}

function openBSComposition(key) {
  const dataMap = window._bsDataMap;
  if (!dataMap || !key || !dataMap[key]) return;

  const row = dataMap[key];
  const stockName = document.getElementById('detailName').textContent.trim();
  const label = bsPeriodLabel(key);
  const rawAssetItems = bsCompositionItems(row, _bsCompositionDefs.assets, _bsCompositionDefs.assetFallback);
  const rawLiabilityItems = bsCompositionItems(row, _bsCompositionDefs.liabilities, _bsCompositionDefs.liabilityFallback);
  const assetTotal = bsSafeTotal(row, 'total_assets', bsCompositionTotal(rawAssetItems));
  const liabilityTotal = bsSafeTotal(row, 'total_liabilities', bsCompositionTotal(rawLiabilityItems));
  const assetItems = bsFillRemainder(rawAssetItems, assetTotal, '其他/未列示资产');
  const liabilityItems = bsFillRemainder(rawLiabilityItems, liabilityTotal, '其他/未列示负债');
  const assetGroupItems = bsGroupItems(row, _bsCompositionDefs.assetFallback, assetTotal, '其他/未列示资产');
  const liabilityGroupItems = bsGroupItems(row, _bsCompositionDefs.liabilityFallback, liabilityTotal, '其他/未列示负债');
  const equityValueRaw = Number(row.total_equity);
  const equityValue = Number.isFinite(equityValueRaw) && equityValueRaw > 0
    ? equityValueRaw
    : Math.max(assetTotal - liabilityTotal, 0);
  const structureItems = [
    { name: '股东权益', value: equityValue, color: '#1677ff' },
    { name: '负债合计', value: liabilityTotal, color: '#ff4d4f' },
  ].filter(item => Number.isFinite(item.value) && item.value > 0);

  document.getElementById('chartModalTitle').textContent = stockName + ' - ' + label + ' 资产负债结构  财报单位：亿元';
  document.getElementById('chartModalOverlay').classList.add('active');

  const dom = prepareChartModalBox();
  dom.classList.add('bs-composition-box');
  dom.innerHTML = '<div class="bs-composition-report"></div>';
  const report = dom.querySelector('.bs-composition-report');

  const charts = [];
  charts.push(renderBSCompositionSection(report, 'Structure', '总资产结构', structureItems, assetTotal, assetTotal, '资产总计'));
  charts.push(renderBSCompositionSection(report, 'AssetGroups', '资产大类：流动/非流动', assetGroupItems, assetTotal, assetTotal, '资产合计'));
  charts.push(renderBSCompositionSection(report, 'Assets', '资产构成', assetItems, assetTotal, assetTotal, '资产合计'));
  charts.push(renderBSCompositionSection(report, 'LiabilityGroups', '负债大类：流动/非流动', liabilityGroupItems, liabilityTotal, assetTotal, '负债合计'));
  charts.push(renderBSCompositionSection(report, 'Liabilities', '负债构成', liabilityItems, liabilityTotal, assetTotal, '负债合计'));

  window._chartModalInstances = charts;
  setTimeout(() => charts.forEach(chart => chart.resize()), 0);
}

function openBSChart(field, name) {
  const dataMap = window._bsDataMap;
  const keys = window._bsKeys;
  const cmpDataMap = window._bsCmpDataMap;
  const cmpCode = window._bsCmpCode;
  const cmpName = window._bsCmpName;
  if (!dataMap || !keys) return;

  const stockName = document.getElementById('detailName').textContent.trim();
  let title = stockName + ' - ' + name;

  const sortedKeys = [...keys].sort(sortFiscalKeysAsc); // oldest first, Q1/Q2/Q3/FY within each year
  // Build display labels: annual shows year, quarterly shows year-period
  const labels = sortedKeys.map(formatFiscalKeyLabel);
  const values = sortedKeys.map(k => {
    const d = dataMap[k];
    return d && d[field] != null ? d[field] : null;
  });

  // YoY line data
  const yoyValues = sortedKeys.map((k, i) => {
    if (i === 0) return null;
    const cur = values[i];
    const prev = values[i - 1];
    if (cur == null || prev == null || prev === 0) return null;
    return parseFloat(((cur - prev) / Math.abs(prev) * 100).toFixed(2));
  });

  // CAGR for main stock
  const cleanVals = values.filter(v => v != null);
  if (cleanVals.length >= 2 && cleanVals[0] !== 0) {
    const firstV = cleanVals[0], lastV = cleanVals[cleanVals.length - 1], n = cleanVals.length - 1;
    const cagr = (Math.pow(lastV / firstV, 1 / n) - 1) * 100;
    title += ' (CAGR: ' + cagr.toFixed(2) + '%)';
  }

  // Comparison data
  let cmpValues = null;
  if (cmpDataMap) {
    cmpValues = sortedKeys.map(k => {
      const d = cmpDataMap[k];
      return d && d[field] != null ? d[field] : null;
    });
  }

  // Comparison stock CAGR
  if (cmpValues && cmpValues.some(v => v != null)) {
    title += ' vs ' + (cmpName || cmpCode);
    const cmpClean = cmpValues.filter(v => v != null);
    if (cmpClean.length >= 2 && cmpClean[0] !== 0) {
      const firstV = cmpClean[0], lastV = cmpClean[cmpClean.length - 1], n = cmpClean.length - 1;
      const cmpCagr = (Math.pow(lastV / firstV, 1 / n) - 1) * 100;
      title += ' (CAGR: ' + cmpCagr.toFixed(2) + '%)';
    }
  }

  document.getElementById('chartModalTitle').textContent = title;
  document.getElementById('chartModalOverlay').classList.add('active');

  const dom = prepareChartModalBox();
  const chart = echarts.init(dom);
  const series = [];

  // Main bar
  series.push({
    name: stockName,
    type: 'bar',
    data: values,
    yAxisIndex: 0,
    itemStyle: { color: '#4a6cf7', borderRadius: [4, 4, 0, 0] },
    label: {
      show: true,
      position: 'top',
      fontSize: 11,
      formatter: function(p) {
        if (p.value == null) return '';
        return Math.abs(p.value) >= 100 ? p.value.toFixed(0) : p.value.toFixed(2);
      }
    }
  });

  // Comparison bar
  if (cmpValues) {
    series.push({
      name: cmpName || cmpCode,
      type: 'bar',
      data: cmpValues,
      yAxisIndex: 0,
      itemStyle: { color: '#fa8c16', borderRadius: [4, 4, 0, 0] },
      label: {
        show: true,
        position: 'top',
        fontSize: 11,
        formatter: function(p) {
          if (p.value == null) return '';
          return Math.abs(p.value) >= 100 ? p.value.toFixed(0) : p.value.toFixed(2);
        }
      }
    });
  }

  // YoY line (only if not single year)
  if (sortedKeys.length > 1 && yoyValues.some(v => v != null)) {
    series.push({
      name: 'YoY%',
      type: 'line',
      data: yoyValues,
      yAxisIndex: 1,
      lineStyle: { color: '#52c41a', width: 2, type: 'dashed' },
      itemStyle: { color: '#52c41a' },
      symbol: 'circle',
      symbolSize: 5,
      label: {
        show: true,
        position: 'top',
        fontSize: 10,
        color: '#52c41a',
        formatter: function(p) {
          if (p.value == null) return '';
          return p.value.toFixed(1) + '%';
        }
      }
    });
  }

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: function(params) {
        let html = '<strong>' + params[0].axisValue + '</strong><br/>';
        for (const p of params) {
          if (p.seriesName === 'YoY%') {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value != null ? p.value.toFixed(1) + '%' : '-') + '<br/>';
          } else {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value != null ? p.value.toFixed(2) + ' 亿元' : '-') + '<br/>';
          }
        }
        return html;
      }
    },
    grid: { left: 60, right: 80, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: labels,
      name: '年份',
      nameLocation: 'middle',
      nameGap: 30
    },
    yAxis: [
      {
        type: 'value',
        name: '亿元',
      },
      {
        type: 'value',
        name: 'YoY%',
        axisLabel: { formatter: '{value}%' },
        splitLine: { show: false }
      }
    ],
    series: series
  });

  window._chartModalInstance = chart;
}

async function updateBalanceSheet() {
  const code = document.getElementById('detailCode').textContent.trim();
  const statusEl = document.getElementById('bsStatus');
  statusEl.textContent = '正在更新数据，请稍候...';
  statusEl.style.color = '#1890ff';

  try {
    const res = await fetch('/api/update-balance-sheet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'incremental' })
    });
    const data = await res.json();
    if (window.BackgroundJobs) BackgroundJobs.watchResponse(data, { open: true });
    if (data.background) {
      statusEl.textContent = data.message || '已转入后台任务';
      statusEl.style.color = '#1890ff';
      return;
    }
    if (data.success) {
      statusEl.textContent = `更新完成: ${data.records_updated} 条记录 (${data.stocks_processed} 只股票)`;
      statusEl.style.color = '#52c41a';
      loadBalanceSheet();
    } else {
      statusEl.textContent = '更新失败: ' + (data.error || '未知错误');
      statusEl.style.color = '#ff4d4f';
    }
  } catch (e) {
    statusEl.textContent = '请求失败: ' + e.message;
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 利润表 & 现金流量表 (共享投资产负债表逻辑) ====================

