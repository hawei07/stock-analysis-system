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
    if (window.BackgroundJobs) BackgroundJobs.watchResponse(data, { open: true });
    if (data.background) {
      status.textContent = data.message || '已转入后台任务';
      return;
    }
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

