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
  const from = document.getElementById('finFromYear').value;
  const to = document.getElementById('finToYear').value;
  const period = document.getElementById('finPeriod').value;
  const quarter = document.getElementById('finQuarter').value;
  const view = document.getElementById('finView').value;
  const actualPeriod = period === 'all' ? quarter : period;
  const cmpCodeRaw = document.getElementById('finCompare').value.trim();
  const cmpCode = await resolveStockCode(cmpCodeRaw);
  const wrap = document.getElementById('tableFinancialsWrap');
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    const res = await fetch(`/api/stock/${code}/financials?${params}`);
    let data = await res.json();

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        const cmpRes = await fetch(`/api/stock/${cmpCode}/financials?${params}`);
        cmpData = await cmpRes.json();
        const infoRes = await fetch('/api/stock/' + cmpCode);
        const info = await infoRes.json();
        if (!info.error) cmpName = info.name;
      } catch {}
    }
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

  // YoY map
  const fields = ['total_revenue', 'operate_profit', 'parent_profit', 'deducted_profit',
    'operate_cashflow', 'roe', 'deducted_roe', 'roic',
    'total_assets', 'total_equity', 'total_shares',
    'core_profit_rate', 'net_profit_rate', 'cashflow_to_profit',
    'dividend_amount', 'dividend_per_share', 'dividend_payout_ratio',
    'basic_eps', 'debt_ratio', 'interest_bearing_debt_ratio'];
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

  // Indicators
  const indicators = [
    { name: '营业总收入', field: 'total_revenue', unit: '亿元', isPercent: false, showYoy: true },
    { name: '核心利润（营业利润）', field: 'operate_profit', unit: '亿元', isPercent: false, showYoy: true },
    { name: '核心利润率', field: 'core_profit_rate', unit: '%', isPercent: true, showYoy: true },
    { name: '归母净利润', field: 'parent_profit', unit: '亿元', isPercent: false, showYoy: true },
    { name: '扣非净利润', field: 'deducted_profit', unit: '亿元', isPercent: false, showYoy: true },
    { name: '净利润率', field: 'net_profit_rate', unit: '%', isPercent: true, showYoy: true },
    { name: '经营现金流/净利润', field: 'cashflow_to_profit', unit: '%', isPercent: true, showYoy: true },
    { name: 'ROE', field: 'roe', unit: '%', isPercent: true, showYoy: true },
    { name: '扣非ROE', field: 'deducted_roe', unit: '%', isPercent: true, showYoy: true },
    { name: 'ROIC', field: 'roic', unit: '%', isPercent: true, showYoy: true },
    { name: '经营活动现金流量净额', field: 'operate_cashflow', unit: '亿元', isPercent: false, showYoy: true },
    { name: '总资产', field: 'total_assets', unit: '亿元', isPercent: false, showYoy: true },
    { name: '归母权益', field: 'total_equity', unit: '亿元', isPercent: false, showYoy: true },
    { name: '总股本', field: 'total_shares', unit: '亿股', isPercent: false, showYoy: true },
    { name: '分红金额', field: 'dividend_amount', unit: '亿元', isPercent: false, showYoy: true },
    { name: '每股分红', field: 'dividend_per_share', unit: '元', isPercent: false, showYoy: true },
    { name: '分红率', field: 'dividend_payout_ratio', unit: '%', isPercent: true, showYoy: true },
    { name: '归母普通股每股收益', field: 'basic_eps', unit: '元', isPercent: false, showYoy: true },
    { name: '股息率', field: 'dividend_yield_fin', unit: '%', isPercent: true, showYoy: false },
    { name: '资产负债率', field: 'debt_ratio', unit: '%', isPercent: true, showYoy: true },
    { name: '有息负债率', field: 'interest_bearing_debt_ratio', unit: '%', isPercent: true, showYoy: true },
  ];

  // Sort from localStorage
  const savedOrder = localStorage.getItem('financials-indicator-order');
  if (savedOrder) {
    try {
      const orderFields = JSON.parse(savedOrder);
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
    html += `<tr data-indicator-field="${ind.field}">`;
    if (!isQuarterly) {
      html += '<td class="sort-handle">⋮⋮</td>';
    }
    html += `<td class="sticky-col"${hasCmp ? ' rowspan="2"' : ''}>${ind.name}<span class="chart-icon" data-field="${ind.field}" data-name="${esc(ind.name)}" title="查看趋势图"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><polyline points="2,13 5,8 8,10 11,4 14,7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span></td>`;
    for (const k of keys) {
      const d = dataMap[k];
      const val = d ? d[ind.field] : null;
      const yoy = yoyMap[k] ? yoyMap[k][ind.field] : null;
      if (!ind.showYoy) {
        html += `<td style="text-align:left">${val || '-'}</td><td>-</td>`;
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
          html += `<td style="text-align:left;background:#fff7e6;color:#fa8c16">${val || '-'}</td><td style="background:#fff7e6;color:#fa8c16">-</td>`;
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

function segmentNum(v) {
  return v == null || Number.isNaN(Number(v)) ? null : Number(v);
}

function fmtSegmentAmount(v) {
  const n = segmentNum(v);
  if (n == null) return '-';
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(2);
}

function fmtSegmentPct(v) {
  const n = segmentNum(v);
  return n == null ? '-' : n.toFixed(1) + '%';
}

function disposeSegmentCharts() {
  for (const chart of [segmentRevenueChart, segmentProfitChart, segmentBubbleChart]) {
    if (chart) chart.dispose();
  }
  segmentRevenueChart = null;
  segmentProfitChart = null;
  segmentBubbleChart = null;
}

function resetSegmentsPanel() {
  segmentLoadSeq++;
  segmentCache = null;
  disposeSegmentCharts();
  const summary = document.getElementById('segmentSummary');
  const wrap = document.getElementById('tableSegmentsWrap');
  const status = document.getElementById('segStatus');
  if (summary) summary.innerHTML = '';
  if (wrap) wrap.innerHTML = '<div class="empty">请点击"查询"加载营收构成数据</div>';
  if (status) status.textContent = '';
}

async function loadSegments() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const requestSeq = ++segmentLoadSeq;
  const from = document.getElementById('segFromYear').value;
  const to = document.getElementById('segToYear').value;
  const dimension = document.getElementById('segDimension').value;
  const status = document.getElementById('segStatus');
  const wrap = document.getElementById('tableSegmentsWrap');
  status.textContent = '加载中...';
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, dimension });
    const res = await fetch(`/api/stock/${code}/segments?${params}`);
    const payload = await res.json();
    if (requestSeq !== segmentLoadSeq || code !== document.getElementById('detailCode').textContent.trim()) return;
    const data = payload.data || [];
    segmentCache = { data, summary: payload.summary || null };
    if (!data.length) {
      disposeSegmentCharts();
      document.getElementById('segmentSummary').innerHTML = '';
      wrap.innerHTML = '<div class="empty">暂无营收构成数据，请点击"更新数据"拉取</div>';
      status.textContent = '暂无数据';
      return;
    }
    renderSegmentsFromCache();
    status.textContent = `共 ${data.length} 条`;
  } catch (e) {
    disposeSegmentCharts();
    document.getElementById('segmentSummary').innerHTML = '';
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">加载失败: ' + e.message + '</div>';
    status.textContent = '加载失败';
  }
}

async function updateSegments() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const status = document.getElementById('segStatus');
  status.textContent = '更新中...';
  try {
    const res = await fetch('/api/update-segments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code })
    });
    const data = await res.json();
    if (data.success) {
      showToast('营收构成更新完成: ' + (data.records_updated || 0) + ' 条', 'success');
      await loadSegments();
    } else {
      const msg = data.errors && data.errors.length ? data.errors[0] : '更新失败';
      showToast(msg, 'error');
      status.textContent = '更新失败';
    }
  } catch (e) {
    showToast('营收构成更新失败: ' + e.message, 'error');
    status.textContent = '更新失败';
  }
}

function renderSegmentsFromCache() {
  if (!segmentCache) return;
  renderSegmentSummary(segmentCache.summary);
  renderSegmentCharts(segmentCache.data);
  renderSegmentTable(segmentCache.data);
}

function renderSegmentSummary(summary) {
  const el = document.getElementById('segmentSummary');
  if (!summary) {
    el.innerHTML = '';
    return;
  }
  const cards = [
    { label: '最新年度', value: summary.latest_year || '-', sub: '年报口径' },
    { label: '第一大收入来源', value: summary.top_revenue_segment || '-', sub: '占收入 ' + fmtSegmentPct(summary.top_revenue_ratio) },
    { label: '第一大毛利来源', value: summary.top_profit_segment || '-', sub: '占毛利 ' + fmtSegmentPct(summary.top_profit_ratio) },
    { label: 'Top3 收入集中度', value: fmtSegmentPct(summary.top3_revenue_ratio), sub: '综合毛利率 ' + fmtSegmentPct(summary.gross_margin) },
  ];
  el.innerHTML = cards.map(c => `
    <div class="segment-summary-card">
      <div class="label">${esc(c.label)}</div>
      <div class="value">${esc(String(c.value))}</div>
      <div class="sub">${esc(c.sub)}</div>
    </div>
  `).join('');
  bindReorderRows();
}

function segmentYears(data) {
  return [...new Set(data.map(d => d.fiscal_year))].sort((a, b) => a - b);
}

function topSegmentNames(data, field) {
  const latestYear = Math.max(...data.map(d => d.fiscal_year));
  return data.filter(d => d.fiscal_year === latestYear)
    .sort((a, b) => (segmentNum(b[field]) || 0) - (segmentNum(a[field]) || 0))
    .slice(0, 8)
    .map(d => d.segment_name);
}

function buildSegmentSeries(data, field, ratioField) {
  const view = document.getElementById('segView').value;
  const years = segmentYears(data);
  const names = topSegmentNames(data, field);
  const rowsByYear = {};
  for (const row of data) {
    rowsByYear[row.fiscal_year] = rowsByYear[row.fiscal_year] || [];
    rowsByYear[row.fiscal_year].push(row);
  }
  const seriesNames = [...names, '其他'];
  const series = seriesNames.map(name => ({
    name,
    type: 'bar',
    stack: 'total',
    emphasis: { focus: 'series' },
    data: years.map(year => {
      const rows = rowsByYear[year] || [];
      if (name === '其他') {
        return rows.filter(r => !names.includes(r.segment_name)).reduce((sum, r) => sum + (segmentNum(view === 'ratio' ? r[ratioField] : r[field]) || 0), 0);
      }
      const row = rows.find(r => r.segment_name === name);
      return row ? (segmentNum(view === 'ratio' ? row[ratioField] : row[field]) || 0) : 0;
    })
  }));
  return { years, series };
}

function renderSegmentStackChart(domId, title, field, ratioField) {
  const data = segmentCache.data || [];
  const view = document.getElementById('segView').value;
  const { years, series } = buildSegmentSeries(data, field, ratioField);
  const dom = document.getElementById(domId);
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  const chart = echarts.init(dom);
  chart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: v => view === 'ratio' ? Number(v).toFixed(1) + '%' : Number(v).toFixed(2) + ' 亿'
    },
    legend: { type: 'scroll', top: 0 },
    grid: { left: 48, right: 18, top: 56, bottom: 36 },
    xAxis: { type: 'category', data: years },
    yAxis: { type: 'value', name: view === 'ratio' ? '占比(%)' : '亿元' },
    series
  });
  return chart;
}

function renderSegmentBubble(data) {
  const latestYear = Math.max(...data.map(d => d.fiscal_year));
  const latest = data.filter(d => d.fiscal_year === latestYear)
    .sort((a, b) => (segmentNum(b.revenue) || 0) - (segmentNum(a.revenue) || 0))
    .slice(0, 12);
  const dom = document.getElementById('chartSegmentBubble');
  const existing = echarts.getInstanceByDom(dom);
  if (existing) existing.dispose();
  segmentBubbleChart = echarts.init(dom);
  segmentBubbleChart.setOption({
    tooltip: {
      formatter: p => {
        const d = p.data;
        return `${esc(d[3])}<br>收入占比: ${fmtSegmentPct(d[0])}<br>毛利率: ${fmtSegmentPct(d[1])}<br>收入: ${fmtSegmentAmount(d[2])} 亿`;
      }
    },
    grid: { left: 52, right: 24, top: 28, bottom: 42 },
    xAxis: { type: 'value', name: '收入占比(%)' },
    yAxis: { type: 'value', name: '毛利率(%)' },
    series: [{
      type: 'scatter',
      symbolSize: d => Math.max(12, Math.min(58, Math.sqrt(Math.max(d[2], 0)) * 4)),
      data: latest.map(r => [r.revenue_ratio || 0, r.gross_margin || 0, r.revenue || 0, r.segment_name]),
      label: { show: true, formatter: p => p.data[3], position: 'right', fontSize: 11 },
      itemStyle: { color: '#4a6cf7', opacity: .78 }
    }]
  });
}

function renderSegmentCharts(data) {
  segmentRevenueChart = renderSegmentStackChart('chartSegmentRevenue', '历年业务收入构成', 'revenue', 'revenue_ratio');
  segmentProfitChart = renderSegmentStackChart('chartSegmentProfit', '历年业务毛利构成', 'gross_profit', 'profit_ratio');
  renderSegmentBubble(data);
  setTimeout(() => {
    if (segmentRevenueChart) segmentRevenueChart.resize();
    if (segmentProfitChart) segmentProfitChart.resize();
    if (segmentBubbleChart) segmentBubbleChart.resize();
  }, 50);
}

function renderSegmentTable(data) {
  const wrap = document.getElementById('tableSegmentsWrap');
  const years = segmentYears(data).sort((a, b) => b - a);
  const latestYear = Math.max(...data.map(d => d.fiscal_year));
  const names = [...new Set(data.map(d => d.segment_name))].sort((a, b) => {
    const ar = data.find(d => d.fiscal_year === latestYear && d.segment_name === a);
    const br = data.find(d => d.fiscal_year === latestYear && d.segment_name === b);
    return (segmentNum(br?.revenue) || 0) - (segmentNum(ar?.revenue) || 0);
  });
  const map = {};
  for (const row of data) map[row.fiscal_year + '|' + row.segment_name] = row;

  let html = '<table class="fin-table"><thead><tr><th class="sticky-col" rowspan="2">业务名称</th>';
  for (const year of years) html += `<th class="year-header" colspan="4">${year}</th>`;
  html += '</tr><tr>';
  for (const year of years) html += '<th class="sub-header">收入(亿)</th><th class="sub-header">收入占比</th><th class="sub-header">毛利(亿)</th><th class="sub-header">毛利率</th>';
  html += '</tr></thead><tbody>';

  for (const name of names) {
    html += `<tr><td class="sticky-col">${esc(name)}</td>`;
    for (const year of years) {
      const row = map[year + '|' + name];
      html += `<td>${fmtSegmentAmount(row?.revenue)}</td>`;
      html += `<td>${fmtSegmentPct(row?.revenue_ratio)}</td>`;
      html += `<td>${fmtSegmentAmount(row?.gross_profit)}</td>`;
      html += `<td>${fmtSegmentPct(row?.gross_margin)}</td>`;
    }
    html += '</tr>';
  }
  html += '</tbody></table>';
  wrap.innerHTML = html;
}

// ==================== 资产负债表 ====================

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
  const wrap = document.getElementById('tableBalanceSheetWrap');
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    const res = await fetch(`/api/stock/${code}/balance-sheet?${params}`);
    let data = await res.json();

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        const cmpRes = await fetch(`/api/stock/${cmpCode}/balance-sheet?${params}`);
        cmpData = await cmpRes.json();
        const infoRes = await fetch('/api/stock/' + cmpCode);
        const info = await infoRes.json();
        if (!info.error) cmpName = info.name;
      } catch {}
    }
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
  return dom;
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

function bsCompositionTableRows(items, groupTotal, baseTotal) {
  if (!items.length) return '<tr><td colspan="4" class="bs-composition-empty">暂无明细数据</td></tr>';
  return items.map(item => (
    `<tr><td>${esc(item.name)}</td><td>${bsFormatAmount(item.value)}</td><td>${bsFormatPercent(item.value, groupTotal)}</td><td>${bsFormatPercent(item.value, baseTotal)}</td></tr>`
  )).join('');
}

function renderBSCompositionSection(container, id, title, items, groupTotal, baseTotal, summaryLabel) {
  const chartId = 'bsCompositionPie' + id;
  container.insertAdjacentHTML('beforeend', `
    <section class="bs-composition-section">
      <div class="bs-composition-pie" id="${chartId}"></div>
      <div class="bs-composition-table-wrap">
        <h4>${esc(title)}</h4>
        <table class="bs-composition-table">
          <thead><tr><th>科目</th><th>金额</th><th>占本组</th><th>占总资产</th></tr></thead>
          <tbody>${bsCompositionTableRows(items, groupTotal, baseTotal)}</tbody>
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
      data: items
    }]
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
    { name: '负债合计', value: liabilityTotal },
    { name: '股东权益', value: equityValue },
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

  const sortedKeys = [...keys].sort((a, b) => a.localeCompare(b)); // oldest first
  // Build display labels: annual shows year, quarterly shows year-period
  const labels = sortedKeys.map(k => {
    if (k.indexOf('|') === -1) return k;
    const [yr, rp] = k.split('|');
    return yr + '-' + rp;
  });
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

function getIncomeSections() {
  return [
    { title: '收入', items: [{ name: '营业总收入', field: 'total_revenue', bold: true }, { name: '营业收入', field: 'operating_revenue' }] },
    { title: '成本与费用', items: [
      { name: '营业总成本', field: 'operating_cost', bold: true }, { name: '营业成本', field: 'cost_of_revenue' },
      { name: '营业税金及附加', field: 'tax_surcharge' }, { name: '销售费用', field: 'selling_expense' },
      { name: '管理费用', field: 'admin_expense' }, { name: '财务费用', field: 'finance_expense' }, { name: '研发费用', field: 'rd_expense' }
    ]},
    { title: '其他收益', items: [{ name: '公允价值变动收益', field: 'fair_value_change' }, { name: '投资收益', field: 'invest_income' }] },
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
  const wrap = document.getElementById(t.wrapId);
  wrap.innerHTML = '<div class="empty">加载中...</div>';

  try {
    const params = new URLSearchParams({ from_year: from, to_year: to, period: actualPeriod, view });
    const res = await fetch(`/api/stock/${code}/${t.api}?${params}`);
    let data = await res.json();

    let cmpData = null, cmpName = '';
    if (cmpCode && cmpCode !== code) {
      try {
        const cmpRes = await fetch(`/api/stock/${cmpCode}/${t.api}?${params}`);
        cmpData = await cmpRes.json();
        const infoRes = await fetch('/api/stock/' + cmpCode);
        const info = await infoRes.json();
        if (!info.error) cmpName = info.name;
      } catch {}
    }
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

  const periods = new Set(data.map(d => d.report_period || 'FY'));
  const isQuarterly = !(periods.size === 1 && periods.has('FY'));

  const makeKey = (d) => { const rp = d.report_period || 'FY'; return isQuarterly ? d.fiscal_year + '|' + rp : d.fiscal_year + ''; };
  const makePrevKey = (key) => { if (!isQuarterly) return (parseInt(key) - 1) + ''; const [yr, rp] = key.split('|'); return (parseInt(yr) - 1) + '|' + rp; };

  const keys = data.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
  if (!isQuarterly) keys.sort((a, b) => parseInt(b) - parseInt(a));
  const dataMap = {}; for (const d of data) dataMap[makeKey(d)] = d;
  const years = [...new Set(data.map(d => d.fiscal_year))].sort((a, b) => b - a);

  const sections = t.sectionsFn();
  const allFields = []; for (const sec of sections) for (const it of sec.items) allFields.push(it.field);

  // YoY
  const yoyMap = {};
  for (const key of keys) { const d = dataMap[key]; const prevKey = makePrevKey(key); const prev = dataMap[prevKey]; yoyMap[key] = {}; for (const f of allFields) { const cur = d[f]; if (cur == null || !prev || prev[f] == null || prev[f] === 0) { yoyMap[key][f] = null; continue; } yoyMap[key][f] = (cur - prev[f]) / Math.abs(prev[f]) * 100; } }

  // Comparison
  let cmpDataMap = {}, cmpKeys = [], cmpYoyMap = {};
  if (cmpData && cmpData.length > 0) {
    for (const d of cmpData) cmpDataMap[makeKey(d)] = d;
    cmpKeys = cmpData.map(makeKey).filter((v, i, a) => a.indexOf(v) === i);
    for (const key of cmpKeys) { const d = cmpDataMap[key]; const prevKey = makePrevKey(key); const prev = cmpDataMap[prevKey]; cmpYoyMap[key] = {}; for (const f of allFields) { const cur = d[f]; if (cur == null || !prev || prev[f] == null || prev[f] === 0) { cmpYoyMap[key][f] = null; continue; } cmpYoyMap[key][f] = (cur - prev[f]) / Math.abs(prev[f]) * 100; } }
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
  for (const lbl of keyLabels) html += `<th class="sticky-header year-header" colspan="2">${lbl}</th>`;
  html += '</tr><tr>';
  for (const lbl of keyLabels) { html += '<th class="sticky-header sub-header">原值</th>'; html += '<th class="sticky-header sub-header">同比%</th>'; }
  html += '</tr></thead><tbody>';

  html += '<tr class="unit-row"><td class="sticky-col" style="background:#fafafa;font-weight:500">单位：亿元</td>';
  for (const k of keys) { html += '<td style="text-align:center;background:#fafafa">亿元</td>'; html += '<td style="text-align:center;background:#fafafa">%</td>'; }
  html += '</tr>';

  for (const section of sections) {
    html += `<tr class="section-row"><td class="sticky-col" style="background:#e6f0ff;font-weight:700;font-size:13px;color:#1a1a2e" colspan="${keys.length * 2 + 1}">${section.title}</td></tr>`;
    for (const item of section.items) {
      const bs = item.bold ? 'font-weight:600;' : '';
      html += `<tr><td class="sticky-col" style="${bs}"${hasCmp ? ' rowspan="2"' : ''}>${item.name}<span class="chart-icon" data-field="${item.field}" data-name="${esc(item.name)}" data-prefix="${t.prefix}" title="查看趋势图"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><polyline points="2,13 5,8 8,10 11,4 14,7" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></span></td>`;
      for (const k of keys) { const d = dataMap[k]; const val = d ? d[item.field] : null; const yoy = yoyMap[k] ? yoyMap[k][item.field] : null; html += `<td style="text-align:right;${bs}">${val != null ? (Math.abs(val) >= 100 ? val.toFixed(0) : val.toFixed(2)) : '-'}</td>`; html += `<td class="${yoyClass(yoy)}" style="text-align:right">${yoyFmt(yoy)}</td>`; }
      html += '</tr>';
      if (hasCmp) {
        html += '<tr style="background:#fff7e6;color:#fa8c16">';
        for (const k of keys) { const d = cmpDataMap[k]; const val = d ? d[item.field] : null; const yoy = cmpYoyMap[k] ? cmpYoyMap[k][item.field] : null; html += `<td style="text-align:right;background:#fff7e6;color:#fa8c16;${bs}">${val != null ? (Math.abs(val) >= 100 ? val.toFixed(0) : val.toFixed(2)) : '-'}</td>`; html += `<td class="${yoyClass(yoy)}" style="background:#fff7e6;text-align:right">${yoyFmt(yoy)}</td>`; }
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
}

function openFinanceChart(field, name, prefix) {
  const t = _financeTables[prefix]; if (!t) return;
  const dataMap = window[t.dataVar]; const keys = window[t.keysVar];
  const cmpDataMap = window[t.cmpDataVar]; const cmpCode = window[t.cmpCodeVar]; const cmpName = window[t.cmpNameVar];
  if (!dataMap || !keys) return;

  const stockName = document.getElementById('detailName').textContent.trim();
  let title = stockName + ' - ' + name;
  const sortedKeys = [...keys].sort((a, b) => a.localeCompare(b));
  const labels = sortedKeys.map(k => { if (k.indexOf('|') === -1) return k; const [yr, rp] = k.split('|'); return yr + '-' + rp; });
  const values = sortedKeys.map(k => { const d = dataMap[k]; return d && d[field] != null ? d[field] : null; });
  const yoyValues = sortedKeys.map((k, i) => { if (i === 0) return null; const cur = values[i]; const prev = values[i - 1]; if (cur == null || prev == null || prev === 0) return null; return parseFloat(((cur - prev) / Math.abs(prev) * 100).toFixed(2)); });

  const cleanVals = values.filter(v => v != null);
  if (cleanVals.length >= 2 && cleanVals[0] !== 0) { const fv = cleanVals[0], lv = cleanVals[cleanVals.length - 1], n = cleanVals.length - 1; title += ' (CAGR: ' + ((Math.pow(lv / fv, 1 / n) - 1) * 100).toFixed(2) + '%)'; }

  let cmpValues = null;
  if (cmpDataMap) cmpValues = sortedKeys.map(k => { const d = cmpDataMap[k]; return d && d[field] != null ? d[field] : null; });
  if (cmpValues && cmpValues.some(v => v != null)) { title += ' vs ' + (cmpName || cmpCode); const cc = cmpValues.filter(v => v != null); if (cc.length >= 2 && cc[0] !== 0) { const fv = cc[0], lv = cc[cc.length - 1], n = cc.length - 1; title += ' (CAGR: ' + ((Math.pow(lv / fv, 1 / n) - 1) * 100).toFixed(2) + '%)'; } }

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
    const res = await fetch(apiUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode: 'incremental' }) });
    const data = await res.json();
    if (data.success) { statusEl.textContent = `更新完成: ${data.records_updated} 条`; statusEl.style.color = '#52c41a'; loadFinanceTable(prefix); }
    else { statusEl.textContent = '更新失败'; statusEl.style.color = '#ff4d4f'; }
  } catch (e) { statusEl.textContent = '请求失败: ' + e.message; statusEl.style.color = '#ff4d4f'; }
}

// ==================== 指标趋势图弹窗 ====================

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

  const sortedKeys = [...keys].sort((a, b) => a.localeCompare(b));
  const vals = sortedKeys.map(k => {
    const d = dataMap[k];
    return d && d[ind.field] != null ? d[ind.field] : null;
  });
  const labels = sortedKeys;

  // YoY line data
  const yoyValues = keys.map((k, i) => {
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
    if (typeof l === 'string' && l.indexOf('|') > 0) return true;
  }
  return false;
}

function closeIndicatorChart() {
  document.getElementById('chartModalOverlay').classList.remove('active');
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
