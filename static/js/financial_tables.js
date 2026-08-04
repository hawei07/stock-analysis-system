async function resolveStockCode(input) {
  if (!input) return null;
  if (/^\d{6}$/.test(input.trim())) return input.trim();
  try {
    const res = await fetch('/api/stock-search?keyword=' + encodeURIComponent(input.trim()));
    const data = await res.json();
    if (data && data.length > 0) return data[0].code;
  } catch (e) {}
  return null;
}

function fiscalPeriodOrder(key) {
  if (key.indexOf('|') === -1) return { year: Number(key) || 0, period: 0 };
  const [year, period] = key.split('|');
  const periodOrder = { Q1: 1, Q2: 2, Q3: 3, FY: 4 };
  return { year: Number(year) || 0, period: periodOrder[period] || 9 };
}

function sortFiscalKeysAsc(a, b) {
  const left = fiscalPeriodOrder(a);
  const right = fiscalPeriodOrder(b);
  if (left.year !== right.year) return left.year - right.year;
  return left.period - right.period;
}

function formatFiscalKeyLabel(key) {
  if (key.indexOf('|') === -1) return key;
  const [year, period] = key.split('|');
  return year + '-' + period;
}

function onFinPeriodChange() {
  const period = document.getElementById('finPeriod').value;
  const qEl = document.getElementById('finQuarter');
  const vEl = document.getElementById('finView');
  if (period === 'all') {
    qEl.style.display = 'inline-block';
    vEl.style.display = 'inline-block';
  } else {
    qEl.style.display = 'none';
    vEl.style.display = 'none';
  }
  loadFinancials();
}

function onBsPeriodChange() {
  const period = document.getElementById('bsPeriod').value;
  const qEl = document.getElementById('bsQuarter');
  const vEl = document.getElementById('bsView');
  if (period === 'all') {
    qEl.style.display = 'inline-block';
    vEl.style.display = 'inline-block';
  } else {
    qEl.style.display = 'none';
    vEl.style.display = 'none';
  }
  loadBalanceSheet();
}

async function loadFinancials() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  await ensureFinancialIndicatorPreferencesLoaded();
  if (code !== document.getElementById('detailCode').textContent.trim()) return;
  const from = document.getElementById('finFromYear').value;
  const to = document.getElementById('finToYear').value;
  const period = document.getElementById('finPeriod').value;
  const quarter = document.getElementById('finQuarter').value;
  const view = document.getElementById('finView').value;
  const actualPeriod = period === 'all' ? quarter : period;
  const cmpCodeRaw = document.getElementById('finCompare').value.trim();
  const cmpCode = await resolveStockCode(cmpCodeRaw);
  if (code !== document.getElementById('detailCode').textContent.trim()) return;
  const wrap = document.getElementById('tableFinancialsWrap');
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    const res = await fetch(`/api/stock/${code}/financials?${params}`);
    let data = await res.json();
    if (code !== document.getElementById('detailCode').textContent.trim()) return;

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        const cmpRes = await fetch(`/api/stock/${cmpCode}/financials?${params}`);
        cmpData = await cmpRes.json();
        const infoRes = await fetch('/api/stock/' + cmpCode);
        const info = await infoRes.json();
        if (code !== document.getElementById('detailCode').textContent.trim()) return;
        if (!info.error) cmpName = info.name;
      } catch {}
    }
    if (code !== document.getElementById('detailCode').textContent.trim()) return;
    if (!data || data.length === 0) {
      wrap.innerHTML = '<div class="empty">暂无财务数据，请点击"更新数据"拉取</div>';
      return;
    }
    renderFinancialsTable(data, cmpData, cmpCode, cmpName);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">加载失败: ' + e.message + '</div>';
  }
}

function renderFinancialsTable(data, cmpData, cmpCode, cmpName) {
  const wrap = document.getElementById('tableFinancialsWrap');

  // Helper functions
  const fmtVal = (v, ind) => {
    if (v == null) return '-';
    if (ind.isPercent || ind.unit === '%') return v.toFixed(2);
    if (ind.unit === '亿元' || ind.unit === '亿股') return (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2));
    return v.toFixed(2);
  };
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
  const indicators = getFinancialVisibleIndicators();
  populateFinancialIndicatorPicker();

  // YoY map
  const fields = indicators.map(ind => ind.field);
  const yoyMap = {};
  for (const key of keys) {
    const d = dataMap[key];
    const prevKey = makePrevKey(key);
    const prev = dataMap[prevKey];
    yoyMap[key] = {};
    for (const f of fields) {
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
      for (const f of fields) {
        const cur = d[f];
        if (cur == null || !prev || prev[f] == null || prev[f] === 0) { cmpYoyMap[key][f] = null; continue; }
        cmpYoyMap[key][f] = (cur - prev[f]) / Math.abs(prev[f]) * 100;
      }
    }
  }

  // Sort from localStorage
  const savedOrder = localStorage.getItem('financials-indicator-order');
  if (savedOrder) {
    try {
      const orderFields = normalizeFinancialVisibleFields(JSON.parse(savedOrder));
      const idxMap = {};
      indicators.forEach((ind, i) => idxMap[ind.field] = i);
      indicators.sort((a, b) => {
        const ai = orderFields.indexOf(a.field), bi = orderFields.indexOf(b.field);
        if (ai === -1 && bi === -1) return idxMap[a.field] - idxMap[b.field];
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
      });
    } catch (e) {}
  }
  window._finIndicators = indicators;
  window._finDataMap = dataMap;
  window._finKeys = keys;
  window._finYears = years;
  window._finYoyMap = yoyMap;
  window._finCmpDataMap = cmpDataMap;
  window._finCmpKeys = cmpKeys;
  window._finCmpCode = cmpCode;
  window._finCmpName = cmpName;

  // Build table
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

  html += '<table class="fin-table" id="finMainTable"><thead><tr>';

  if (!isQuarterly) {
    html += '<th class="sort-handle sticky-header" rowspan="2" style="min-width:28px;background:#f0f0f0"></th>';
  }
  html += '<th class="sticky-col sticky-header" rowspan="2" style="min-width:180px">指标</th>';
  for (const lbl of keyLabels) {
    html += `<th class="sticky-header year-header" colspan="2">${lbl}</th>`;
  }
  html += '</tr><tr>';
  for (const lbl of keyLabels) {
    html += '<th class="sticky-header sub-header">原值</th>';
    html += '<th class="sticky-header sub-header">同比%</th>';
  }
  html += '</tr></thead><tbody>';

  // Unit row
  if (!isQuarterly) {
    html += '<tr class="unit-row"><td class="sort-handle" style="background:#fafafa"></td>';
  } else {
    html += '<tr class="unit-row">';
  }
  html += '<td class="sticky-col" style="background:#fafafa;font-weight:500">单位</td>';
  for (const k of keys) {
    html += '<td style="text-align:center;background:#fafafa">-</td>';
    html += '<td style="text-align:center;background:#fafafa">%</td>';
  }
  html += '</tr>';

  // Data rows
  for (const ind of indicators) {
    // Main stock row
    const canRemoveIndicator = !isFinancialLockedIndicator(ind.field);
    html += `<tr data-indicator-field="${ind.field}">`;
    if (!isQuarterly) {
      html += '<td class="sort-handle">⋮⋮</td>';
    }
    html += `<td class="sticky-col"${hasCmp ? ' rowspan="2"' : ''}>
      <span class="fin-indicator-title">${esc(ind.name)}</span>
      ${ind.source ? `<span class="fin-source-badge fin-source-${esc(financialSourceShortName(ind.source))}" title="${esc(ind.source)}">${esc(financialSourceShortName(ind.source))}</span>` : ''}
      <span class="chart-icon" data-field="${esc(ind.field)}" data-name="${esc(ind.name)}" title="查看趋势图"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><polyline points="2,13 5,8 8,10 11,4 14,7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span>
      ${canRemoveIndicator ? `<button class="fin-remove-indicator" type="button" onclick="removeFinancialIndicator('${esc(ind.field)}')" title="删除指标">×</button>` : ''}
    </td>`;
    for (const k of keys) {
      const d = dataMap[k];
      const val = d ? d[ind.field] : null;
      const yoy = yoyMap[k] ? yoyMap[k][ind.field] : null;
      if (!ind.showYoy) {
        let display = fmtVal(val, ind);
        if (val != null && ind.unit) display += ' ' + ind.unit;
        html += `<td>${display}</td><td>-</td>`;
      } else {
        let display = fmtVal(val, ind);
        if (val != null && ind.unit) display += ' ' + ind.unit;
        html += `<td>${display}</td>`;
        html += `<td class="${yoyClass(yoy)}">${yoyFmt(yoy)}</td>`;
      }
    }
    html += '</tr>';

    // Comparison row
    if (hasCmp) {
      html += `<tr class="cmp-row" style="background:#fff7e6;color:#fa8c16">`;
      for (const k of keys) {
        const d = cmpDataMap[k];
        const val = d ? d[ind.field] : null;
        const yoy = cmpYoyMap[k] ? cmpYoyMap[k][ind.field] : null;
        if (!ind.showYoy) {
          let display = fmtVal(val, ind);
          if (val != null && ind.unit) display += ' ' + ind.unit;
          html += `<td style="background:#fff7e6;color:#fa8c16">${display}</td><td style="background:#fff7e6;color:#fa8c16">-</td>`;
        } else {
          let display = fmtVal(val, ind);
          if (val != null && ind.unit) display += ' ' + ind.unit;
          html += `<td style="background:#fff7e6;color:#fa8c16">${display}</td>`;
          html += `<td class="${yoyClass(yoy)}" style="background:#fff7e6">${yoyFmt(yoy)}</td>`;
        }
      }
      html += '</tr>';
    }
  }

  html += '</tbody></table>';
  wrap.innerHTML = html;

  // Sort button: only for annual mode
  const btnSort = document.getElementById('btnToggleSort');
  if (btnSort) btnSort.style.display = (!isQuarterly) ? 'inline-block' : 'none';

  // Attach reorder only for annual
  if (!isQuarterly) {
    attachReorderEvents(wrap);
  }

  // Chart icons
  wrap.querySelectorAll('.chart-icon').forEach(icon => {
    icon.addEventListener('click', function(e) {
      e.stopPropagation();
      openIndicatorChart(this.dataset.field, this.dataset.name);
    });
  });
}

// ==================== 排序模式 ====================

let _reorderState = null; // { table, tbody, rows, dragRow, ghost, marker, startY, rowHeight, dragIdx }

function toggleSortMode() {
  const table = document.getElementById('finMainTable');
  if (!table) return;
  const btn = document.getElementById('btnToggleSort');
  const isActive = table.classList.contains('sort-mode');

  if (isActive) {
    // 退出排序模式
    table.classList.remove('sort-mode');
    btn.textContent = '调整排序';
    btn.classList.remove('btn-primary');
    btn.classList.add('btn-outline');
    // 清除残留状态
    document.body.classList.remove('reorder-active');
    if (_reorderState) {
      if (_reorderState.ghost) _reorderState.ghost.remove();
      if (_reorderState.marker) _reorderState.marker.remove();
      _reorderState = null;
    }
  } else {
    // 进入排序模式
    table.classList.add('sort-mode');
    btn.textContent = '完成排序';
    btn.classList.remove('btn-outline');
    btn.classList.add('btn-primary');
  }
}

function attachReorderEvents(wrap) {
  const table = document.getElementById('finMainTable');
  if (!table) return;
  const tbody = table.querySelector('tbody');
  if (!tbody) return;

  // 每次渲染后重新绑定
  tbody.removeEventListener('mousedown', _onSortMouseDown);
  tbody.addEventListener('mousedown', _onSortMouseDown);
}

function _onSortMouseDown(e) {
  const table = document.getElementById('finMainTable');
  if (!table || !table.classList.contains('sort-mode')) return;

  // 找到排序手柄
  const handle = e.target.closest('.sort-handle');
  if (!handle) return;
  const row = handle.closest('tr');
  if (!row || !row.dataset.indicatorField) return;

  e.preventDefault();
  document.body.classList.add('reorder-active');

  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr[data-indicator-field]'));
  const dragIdx = rows.indexOf(row);
  const rect = row.getBoundingClientRect();
  const rowHeight = rect.height;
  const startY = e.clientY;
  let curIdx = dragIdx;
  let moveY = startY;

  // 创建 ghost
  const ghost = row.cloneNode(true);
  ghost.classList.add('reorder-ghost');
  ghost.style.width = rect.width + 'px';
  ghost.style.left = rect.left + 'px';
  ghost.style.top = rect.top + 'px';
  document.body.appendChild(ghost);

  // 创建插入标记
  const marker = document.createElement('div');
  marker.classList.add('reorder-insert-marker');
  document.body.appendChild(marker);

  // 高亮被拖拽行
  row.style.opacity = '0.3';

  _reorderState = { table, tbody, rows, dragRow: row, ghost, marker, startY, rowHeight, dragIdx };

  function onMove(ev) {
    moveY = ev.clientY;
    const dy = moveY - startY;
    ghost.style.top = (rect.top + dy) + 'px';

    // 计算目标索引
    const offset = Math.round(dy / rowHeight);
    let targetIdx = dragIdx + offset;
    targetIdx = Math.max(0, Math.min(targetIdx, rows.length - 1));

    if (targetIdx !== curIdx) {
      curIdx = targetIdx;
      // 移动标记
      const targetRow = rows[targetIdx];
      const tr = targetRow.getBoundingClientRect();
      const insertBefore = offset < 0 || (offset === 0 && dy < 0);
      marker.style.top = (insertBefore ? tr.top : tr.bottom - 3) + 'px';
      marker.style.left = tr.left + 'px';
      marker.style.width = tr.width + 'px';
      marker.style.display = 'block';

      // 高亮目标行
      rows.forEach(r => r.classList.remove('sort-hover'));
      rows[targetIdx].classList.add('sort-hover');
    }
  }

  function onUp() {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
    document.body.classList.remove('reorder-active');

    ghost.remove();
    marker.remove();
    row.style.opacity = '';
    rows.forEach(r => r.classList.remove('sort-hover'));

    if (curIdx !== dragIdx && curIdx >= 0 && curIdx < rows.length) {
      const targetRow = rows[curIdx];
      if (curIdx < dragIdx) {
        tbody.insertBefore(row, targetRow);
      } else {
        tbody.insertBefore(row, targetRow.nextSibling);
      }
      // 保存新顺序
      const newRows = tbody.querySelectorAll('tr[data-indicator-field]');
      const newOrder = Array.from(newRows).map(r => r.dataset.indicatorField);
      localStorage.setItem('financials-indicator-order', JSON.stringify(newOrder));
      localStorage.setItem('financials-visible-indicators', JSON.stringify(newOrder));
      saveFinancialIndicatorPreferences(normalizeFinancialVisibleFields(newOrder));
      // 更新全局 indicators
      if (window._finIndicators) {
        const fieldMap = {};
        window._finIndicators.forEach(ind => fieldMap[ind.field] = ind);
        window._finIndicators.length = 0;
        newOrder.forEach(f => { if (fieldMap[f]) window._finIndicators.push(fieldMap[f]); });
      }
    }

    _reorderState = null;
  }

  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

async function updateFinancials() {
  const code = document.getElementById('detailCode').textContent.trim();
  const statusEl = document.getElementById('finStatus');
  statusEl.textContent = '正在更新数据，请稍候...';
  statusEl.style.color = '#1890ff';

  try {
    const res = await fetch('/api/update-financials', {
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
      // 重新加载
      loadFinancials();
    } else {
      statusEl.textContent = '更新失败: ' + (data.error || '未知错误');
      statusEl.style.color = '#ff4d4f';
    }
  } catch (e) {
    statusEl.textContent = '请求失败: ' + e.message;
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 营收构成 ====================

function getIncomeSections() {
  return [
    { title: '收入', items: [{ name: '营业总收入', field: 'total_revenue', bold: true }, { name: '营业收入', field: 'operating_revenue' }, { name: '利息收入', field: 'interest_income' }] },
    { title: '成本与费用', items: [
      { name: '营业总成本', field: 'operating_cost', bold: true }, { name: '营业成本', field: 'cost_of_revenue' },
      { name: '毛利率', field: 'income_gross_margin', isPercent: true },
      { name: '利息支出', field: 'interest_expense' }, { name: '手续费及佣金支出', field: 'fee_commission_expense' },
      { name: '营业税金及附加', field: 'tax_surcharge' }, { name: '销售费用', field: 'selling_expense' },
      { name: '管理费用', field: 'admin_expense' }, { name: '财务费用', field: 'finance_expense' },
      { name: '（其中）利息费用', field: 'finance_interest_expense' }, { name: '（其中）利息收入', field: 'finance_interest_income' },
      { name: '研发费用', field: 'rd_expense' }
    ]},
    { title: '其他收益', items: [
      { name: '其他收益', field: 'other_income' }, { name: '投资收益', field: 'invest_income' },
      { name: '公允价值变动收益', field: 'fair_value_change' }, { name: '信用减值损失', field: 'credit_impairment_loss' },
      { name: '资产减值损失', field: 'asset_impairment_loss' }, { name: '资产处置收益', field: 'asset_disposal_income' },
      { name: '核心利润', field: 'sankey_core_profit', bold: true },
      { name: '核心利润率', field: 'sankey_core_profit_rate', isPercent: true }
    ] },
    { title: '利润', items: [
      { name: '营业利润', field: 'operating_profit', bold: true }, { name: '营业外收入', field: 'nonop_income' },
      { name: '营业外支出', field: 'nonop_expense' }, { name: '利润总额', field: 'total_profit', bold: true },
      { name: '所得税费用', field: 'income_tax' }, { name: '净利润', field: 'net_profit', bold: true },
      { name: '归母净利润', field: 'parent_net_profit', bold: true }, { name: '少数股东损益', field: 'minority_profit' }
    ]},
    { title: '每股指标', items: [{ name: '基本每股收益(元)', field: 'basic_eps' }, { name: '稀释每股收益(元)', field: 'diluted_eps' }] },
    { title: '综合收益', items: [
      { name: '其他综合收益', field: 'other_comprehensive' }, { name: '综合收益总额', field: 'total_comprehensive', bold: true },
      { name: '归母综合收益', field: 'parent_comprehensive' }
    ]},
  ];
}

function getCashflowSections() {
  return [
    { title: '经营活动现金流', items: [
      { name: '销售商品提供劳务收到的现金', field: 'cf_sales_goods' }, { name: '收到的税费返还', field: 'cf_tax_refund' },
      { name: '收到其他与经营活动有关的现金', field: 'cf_other_oper_in' }, { name: '经营活动现金流入小计', field: 'cf_oper_inflow', bold: true },
      { name: '购买商品接受劳务支付的现金', field: 'cf_buy_goods' }, { name: '支付给职工以及为职工支付的现金', field: 'cf_payroll' },
      { name: '支付的各项税费', field: 'cf_tax_pay' }, { name: '支付其他与经营活动有关的现金', field: 'cf_other_oper_out' },
      { name: '经营活动现金流出小计', field: 'cf_oper_outflow', bold: true }, { name: '经营活动现金流量净额', field: 'cf_oper_net', bold: true }
    ]},
    { title: '投资活动现金流', items: [
      { name: '收回投资所收到的现金', field: 'cf_invest_withdraw' }, { name: '取得投资收益所收到的现金', field: 'cf_invest_income' },
      { name: '处置固定资产等收回的现金', field: 'cf_dispose_assets' }, { name: '收到其他与投资活动有关的现金', field: 'cf_other_invest_in' },
      { name: '投资活动现金流入小计', field: 'cf_invest_inflow', bold: true }, { name: '购建固定资产等支付的现金', field: 'cf_buy_assets' },
      { name: '投资所支付的现金', field: 'cf_invest_pay' }, { name: '支付其他与投资活动有关的现金', field: 'cf_other_invest_out' },
      { name: '投资活动现金流出小计', field: 'cf_invest_outflow', bold: true }, { name: '投资活动现金流量净额', field: 'cf_invest_net', bold: true }
    ]},
    { title: '筹资活动现金流', items: [
      { name: '吸收投资收到的现金', field: 'cf_finance_in' }, { name: '取得借款收到的现金', field: 'cf_borrow' },
      { name: '发行债券收到的现金', field: 'cf_bond' }, { name: '收到其他与筹资活动有关的现金', field: 'cf_other_finance_in' },
      { name: '筹资活动现金流入小计', field: 'cf_finance_inflow', bold: true }, { name: '偿还债务支付的现金', field: 'cf_repay_debt' },
      { name: '分配股利利润或偿付利息', field: 'cf_dividend_interest' }, { name: '支付其他与筹资活动有关的现金', field: 'cf_other_finance_out' },
      { name: '筹资活动现金流出小计', field: 'cf_finance_outflow', bold: true }, { name: '筹资活动现金流量净额', field: 'cf_finance_net', bold: true }
    ]},
  ];
}

function onIncPeriodChange() {
  const p = document.getElementById('incPeriod').value;
  document.getElementById('incQuarter').style.display = p === 'all' ? 'inline-block' : 'none';
  document.getElementById('incView').style.display = p === 'all' ? 'inline-block' : 'none';
  loadIncome();
}
function onCfPeriodChange() {
  const p = document.getElementById('cfPeriod').value;
  document.getElementById('cfQuarter').style.display = p === 'all' ? 'inline-block' : 'none';
  document.getElementById('cfView').style.display = p === 'all' ? 'inline-block' : 'none';
  loadCashflow();
}

// Generic load: prefix → {fromId, toId, periodId, quarterId, viewId, cmpId, wrapId, api, sectionsFn, tableId, statusId}
function openIndicatorChart(field, name) {
  const dataMap = window._finDataMap;
  const keys = window._finKeys;
  const indicators = window._finIndicators;
  const cmpDataMap = window._finCmpDataMap;
  const cmpCode = window._finCmpCode;
  const cmpName = window._finCmpName;
  if (!dataMap || !keys || !indicators) return;
  const ind = indicators.find(i => i.field === field);
  if (!ind) return;

  const stockName = document.getElementById('detailName').textContent.trim();
  let title = stockName + ' - ' + name;

  const sortedKeys = [...keys].sort(sortFiscalKeysAsc);
  const vals = sortedKeys.map(k => {
    const d = dataMap[k];
    return d && d[ind.field] != null ? d[ind.field] : null;
  });
  const labels = sortedKeys.map(formatFiscalKeyLabel);

  // YoY line data
  const yoyValues = sortedKeys.map((k, i) => {
    if (i === 0) return null;
    const cur = vals[i];
    const prev = vals[i - 1];
    if (cur == null || prev == null || prev === 0) return null;
    return parseFloat(((cur - prev) / Math.abs(prev) * 100).toFixed(2));
  });

  // CAGR for main stock
  const cleanVals = vals.filter(v => v != null);
  if (cleanVals.length >= 2 && cleanVals[0] !== 0) {
    const firstV = cleanVals[0], lastV = cleanVals[cleanVals.length - 1], n = cleanVals.length - 1;
    const cagr = (Math.pow(lastV / firstV, 1 / n) - 1) * 100;
    title += ' (CAGR: ' + cagr.toFixed(2) + '%)';
  }

  // Comparison values
  let cmpValues = null;
  if (cmpDataMap) {
    cmpValues = sortedKeys.map(k => {
      const d = cmpDataMap[k];
      return d && d[ind.field] != null ? d[ind.field] : null;
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

  const isPercent = ind.isPercent || ind.unit === '%';

  document.getElementById('chartModalTitle').textContent = title;
  document.getElementById('chartModalOverlay').classList.add('active');

  const dom = prepareChartModalBox();
  const chart = echarts.init(dom);
  const series = [];

  // Main bar
  series.push({
    name: stockName,
    type: 'bar',
    data: vals,
    yAxisIndex: 0,
    itemStyle: { color: '#4a6cf7', borderRadius: [4, 4, 0, 0] },
    label: {
      show: true,
      position: 'top',
      fontSize: 11,
      formatter: function(p) {
        if (p.value == null) return '';
        return isPercent ? p.value.toFixed(1) + '%' : p.value.toFixed(2);
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
          return isPercent ? p.value.toFixed(1) + '%' : p.value.toFixed(2);
        }
      }
    });
  }

  // YoY line
  if (keys.length > 1 && yoyValues.some(v => v != null)) {
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
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value != null ? (isPercent ? p.value.toFixed(2) + '%' : p.value.toFixed(2)) : '-') + '<br/>';
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
      nameGap: 30,
      axisLabel: { rotate: isQuarterlyChart(labels) ? 30 : 0 }
    },
    yAxis: [
      {
        type: 'value',
        name: ind.unit || '',
        axisLabel: isPercent ? { formatter: '{value}%' } : {}
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

function isQuarterlyChart(labels) {
  for (const l of labels) {
    if (typeof l === 'string' && /-(Q1|Q2|Q3|FY)$/.test(l)) return true;
  }
  return false;
}

function closeIndicatorChart() {
  document.getElementById('chartModalOverlay').classList.remove('active');
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
  const dom = document.getElementById('chartModalBox');
  if (dom) {
    dom.classList.remove('bs-composition-box');
    dom.classList.remove('income-sankey-box');
    dom.innerHTML = '';
  }
}

// ESC 关闭图表弹窗
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    const overlay = document.getElementById('chartModalOverlay');
    if (overlay && overlay.classList.contains('active')) {
      closeIndicatorChart();
    }
  }
});

// ==================== 数据更新 ====================
