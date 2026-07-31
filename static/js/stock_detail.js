function onPopState() {
  const path = window.location.pathname;
  const match = path.match(/^\/stock\/(\d+)$/);
  if (match) {
    showDetailView(match[1]);
  } else {
    showListView();
    loadStocks();
    loadStats();
  }
}

function navigateTo(url) {
  history.pushState(null, '', url);
  const path = new URL(url, location.origin).pathname;
  const match = path.match(/^\/stock\/(\d+)$/);
  if (match) {
    showDetailView(match[1]);
  } else {
    showListView();
    loadStocks();
    loadStats();
  }
}

function goList() {
  navigateTo('/');
}

function showDetailView(code) {
  document.getElementById('view-list').classList.remove('active');
  document.getElementById('view-detail').classList.add('active');
  document.getElementById('btnBack').style.display = 'inline-block';
  loadDetail(code);
}

function showListView() {
  document.getElementById('view-detail').classList.remove('active');
  document.getElementById('view-list').classList.add('active');
  document.getElementById('btnBack').style.display = 'none';
}

// ==================== 详情页 ====================

function getCurrentCode() {
  const el = document.getElementById('detailCode');
  return el ? el.textContent.trim() : '';
}

function refreshCurrentDetailTab(code) {
  const tab = typeof currentTab === 'string' ? currentTab : 'chart';
  if (tab === 'chart') loadKline();
  else if (tab === 'valuation') loadValuation(1095);
  else if (tab === 'dividends') loadDividends(code);
  else if (tab === 'financing') loadFinancing(code);
  else if (tab === 'segments') loadSegments();
  else if (tab === 'financials') loadFinancials();
  else if (tab === 'balance') loadBalanceSheet();
  else if (tab === 'income') loadIncome();
  else if (tab === 'cashflow') loadCashflow();
  else if (tab === 'shareholders') loadShareholders(code);
  else if (tab === 'irm') loadIrm(code);
  else if (tab === 'munger-chat') loadMungerChat();
  else if (tab === 'sticky') loadStickyNotes();
}

async function loadDetail(code) {
  divYearsPopulated = false;
  try {
    // 加载股票基本信息
    const stockRes = await fetch('/api/stock/' + code);
    const stock = await stockRes.json();
    if (stock.error) { showToast(stock.error, 'error'); goList(); return; }
    document.getElementById('detailCode').textContent = stock.code;
    document.getElementById('detailName').textContent = stock.name;
    populateStockSwitcher(stock.code);
    const curYear = new Date().getFullYear();
    let startYear = curYear - 9;
    if (stock.list_date) { const listYear = parseInt(stock.list_date.substring(0,4)); if (listYear > startYear) startYear = listYear; }
    document.getElementById('finFromYear').value = startYear;
    document.getElementById('finToYear').value = curYear;
    document.getElementById('bsFromYear').value = startYear;
    document.getElementById('bsToYear').value = curYear;
    document.getElementById('segFromYear').value = startYear;
    document.getElementById('segToYear').value = curYear;
    document.getElementById('incFromYear').value = startYear;
    document.getElementById('incToYear').value = curYear;
    document.getElementById('cfFromYear').value = startYear;
    document.getElementById('cfToYear').value = curYear;
    resetSegmentsPanel();
    document.getElementById('detailMarket').textContent = stock.market;
    document.getElementById('detailMarket').className = 'market-tag market-' + stock.market;
    document.getElementById('detailIndustry').textContent = stock.industry ? '行业: ' + stock.industry : '';
    document.getElementById('detailListDate').textContent = stock.list_date ? '上市: ' + stock.list_date : '';
    document.getElementById('detailStatus').innerHTML = '<span class="status-tag status-' + stock.status + '">' + stock.status + '</span>';

    // 填充实时指标卡片
    const rt = stock.realtime || {};
    document.getElementById('rtPrice').textContent = rt.price != null ? rt.price.toFixed(2) + ' 元' : '--';
    const peEl = document.getElementById('rtPE');
    peEl.textContent = rt.pe_ttm != null ? rt.pe_ttm.toFixed(2) : '--';
    peEl.className = 'value';
    if (rt.pe_ttm != null && rt.pe_ttm < 0) peEl.classList.add('neg');

    const divYield = parseFloat(stock.dividend_yield);
    const dyEl = document.getElementById('rtDivYield');
    dyEl.textContent = !isNaN(divYield) ? divYield.toFixed(2) + '%' : '--';
    dyEl.className = 'value';

    const mcEl = document.getElementById('rtMarketCap');
    mcEl.textContent = rt.market_cap != null ? rt.market_cap.toFixed(2) + ' 亿' : '--';
    mcEl.className = 'value';
    loadPortfolioPositionCard(stock.code, rt.price);
    loadResearchSummary(stock.code);

    refreshCurrentDetailTab(stock.code);
  } catch (e) {
    showToast('加载详情失败', 'error');
  }
}

async function loadResearchSummary(code) {
  if (!code) return;
  const timeEl = document.getElementById('researchSummaryTime');
  const hiEl = document.getElementById('researchSummaryHighlights');
  const riskEl = document.getElementById('researchSummaryRisks');
  if (!hiEl || !riskEl) return;
  if (timeEl) timeEl.textContent = '读取中...';
  hiEl.innerHTML = '<li>读取中...</li>';
  riskEl.innerHTML = '';
  try {
    const res = await fetch('/api/stock/' + encodeURIComponent(code) + '/research-summary');
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || '摘要生成失败');
    if (code !== getCurrentCode()) return;
    if (timeEl) timeEl.textContent = '更新于 ' + (data.updated_at || '');
    hiEl.innerHTML = (data.highlights || []).map(item => `<li>${esc(item)}</li>`).join('');
    riskEl.innerHTML = (data.risks || []).map(item => `<li>${esc(item)}</li>`).join('');
  } catch (e) {
    if (timeEl) timeEl.textContent = e.message || '摘要生成失败';
    hiEl.innerHTML = '<li>摘要暂不可用。</li>';
    riskEl.innerHTML = '';
  }
}

async function loadPortfolioPositionCard(code, price) {
  const sharesEl = document.getElementById('portfolioShares');
  const valueEl = document.getElementById('portfolioValue');
  if (!sharesEl || !valueEl) return;
  sharesEl.textContent = '--';
  valueEl.textContent = '读取中...';
  try {
    const res = await fetch('/api/portfolio/positions/' + encodeURIComponent(code));
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || '读取持仓失败');
    if (!data.held) {
      sharesEl.textContent = '未持仓';
      valueEl.textContent = '可在“我的持仓”添加';
      return;
    }
    const shares = Number(data.shares || 0);
    const marketValue = price != null ? shares * Number(price) : null;
    const costPrice = data.cost_price != null ? Number(data.cost_price) : null;
    const profit = marketValue != null && costPrice != null ? marketValue - shares * costPrice : null;
    const profitPct = profit != null && shares * costPrice > 0 ? profit / (shares * costPrice) * 100 : null;
    const dividendPerShare = data.dividend_per_share != null ? Number(data.dividend_per_share) : null;
    const expectedDividend = dividendPerShare != null ? shares * dividendPerShare : null;
    sharesEl.textContent = shares.toLocaleString('zh-CN', {maximumFractionDigits: 2}) + ' 股';
    const parts = [];
    if (marketValue != null) parts.push('市值 ' + marketValue.toLocaleString('zh-CN', {maximumFractionDigits: 2}) + ' 元');
    if (costPrice != null) parts.push('成本价 ' + costPrice.toFixed(4));
    if (profit != null) parts.push('盈亏 ' + (profit >= 0 ? '+' : '') + profit.toLocaleString('zh-CN', {maximumFractionDigits: 2}) + ' 元' + (profitPct == null ? '' : ' (' + (profitPct >= 0 ? '+' : '') + profitPct.toFixed(2) + '%)'));
    if (expectedDividend != null) parts.push('预计分红 ' + expectedDividend.toLocaleString('zh-CN', {maximumFractionDigits: 2}) + ' 元');
    valueEl.textContent = parts.length ? parts.join(' · ') : '已加入持仓';
  } catch (e) {
    sharesEl.textContent = '--';
    valueEl.textContent = e.message || '读取失败';
  }
}

let divYearsPopulated = false;

async function loadDividends(code) {
  if (!code) return;
  try {
    const from = document.getElementById('divFromYear').value;
    const to = document.getElementById('divToYear').value;
    let url = '/api/stock/' + code + '/dividends';
    const params = [];
    if (from) params.push('start_year=' + from);
    if (to) params.push('end_year=' + to);
    if (params.length) url += '?' + params.join('&');
    const res = await fetch(url);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    
    // 首次加载时用全部年份数据填充下拉框
    if (!divYearsPopulated && !from && !to) {
      populateDivYearSelects(data);
    }
    
    renderDividendsChart(data);
  } catch (e) {
    showToast('加载分红数据失败', 'error');
  }
}

function populateDivYearSelects(data) {
  const years = data.map(d => d.fiscal_year).sort((a, b) => a - b);
  if (years.length === 0) return;
  const fromSelect = document.getElementById('divFromYear');
  const toSelect = document.getElementById('divToYear');
  fromSelect.innerHTML = '<option value="">全部</option>';
  toSelect.innerHTML = '<option value="">全部</option>';
  years.forEach(y => {
    fromSelect.innerHTML += `<option value="${y}">${y}</option>`;
    toSelect.innerHTML += `<option value="${y}">${y}</option>`;
  });
  fromSelect.value = years[0];
  toSelect.value = years[years.length - 1];
  divYearsPopulated = true;
}

function onDivYearChange() {
  loadDividends(getCurrentCode());
}

function resetDivYears() {
  const fromSelect = document.getElementById('divFromYear');
  const toSelect = document.getElementById('divToYear');
  const fromOpts = fromSelect.options;
  const toOpts = toSelect.options;
  if (fromOpts.length > 1) fromSelect.value = fromOpts[1].value;
  if (toOpts.length > 1) toSelect.value = toOpts[toOpts.length - 1].value;
  loadDividends(getCurrentCode());
}

function renderDividendsChart(data) {
  const dom = document.getElementById('chartDividends');
  if (!dom) return;
  if (chartInstance) chartInstance.dispose();

  const years = data.map(d => d.fiscal_year + '');
  const netProfits = data.map(d => d.net_profit);
  const dividends = data.map(d => d.dividend_amount);
  const payoutRatios = data.map(d => d.net_profit > 0 ? +(d.dividend_amount / d.net_profit * 100).toFixed(1) : null);
  const showLabel = data.length <= 15;

  chartInstance = echarts.init(dom);
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: function(params) {
        const year = params[0].axisValue;
        let html = '<strong>' + year + '</strong><br/>';
        params.forEach(p => {
          if (p.seriesName === '分红比例') {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value !== null ? p.value + '%' : '-') + '<br/>';
          } else {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value !== null ? p.value.toFixed(2) + ' 亿元' : '-') + '<br/>';
          }
        });
        return html;
      }
    },
    legend: {
      data: ['净利润', '分红金额', '分红比例'],
      top: 4
    },
    dataZoom: [
      { type: 'slider', start: data.length > 15 ? Math.max(0, 100 - (15 / data.length * 100)) : 0, end: 100, height: 20, bottom: 10 },
      { type: 'inside' }
    ],
    grid: {
      left: 60,
      right: 80,
      top: 60,
      bottom: data.length > 15 ? 50 : 40
    },
    xAxis: {
      type: 'category',
      data: years,
      name: '财年',
      axisLabel: { fontSize: 12 }
    },
    yAxis: [
      {
        type: 'value',
        name: '金额（亿元）',
        axisLabel: { fontSize: 12 }
      },
      {
        type: 'value',
        name: '分红比例（%）',
        axisLabel: { fontSize: 12 },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '净利润',
        type: 'bar',
        yAxisIndex: 0,
        data: netProfits,
        barMaxWidth: 40,
        itemStyle: { color: '#4a6cf7', borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          formatter: p => p.value >= 100 ? p.value.toFixed(0) : p.value.toFixed(2)
        }
      },
      {
        name: '分红金额',
        type: 'bar',
        yAxisIndex: 0,
        data: dividends,
        barMaxWidth: 40,
        itemStyle: { color: '#52c41a', borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          formatter: p => p.value >= 100 ? p.value.toFixed(0) : p.value.toFixed(2)
        }
      },
      {
        name: '分红比例',
        type: 'line',
        yAxisIndex: 1,
        data: payoutRatios,
        lineStyle: { color: '#fa8c16', width: 2.5 },
        itemStyle: { color: '#fa8c16' },
        symbol: 'circle',
        symbolSize: 6,
        label: {
          show: true,
          position: 'top',
          fontSize: 10,
          color: '#fa8c16',
          formatter: p => p.value !== null ? p.value + '%' : ''
        }
      }
    ]
  };
  chartInstance.setOption(option);
  window.addEventListener('resize', () => {
    chartInstance && chartInstance.resize();
    valInstance && valInstance.resize();
    pbInstance && pbInstance.resize();
  });
}

// ==================== 融资 ====================

let financingInstance = null;

async function loadFinancing(code) {
  if (!code) return;
  const statusEl = document.getElementById('financingStatus');
  if (statusEl) statusEl.textContent = '加载中...';
  try {
    const res = await fetch('/api/stock/' + code + '/financing');
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    renderFinancingChart(data.annual || []);
    renderFinancingTable(data.details || []);
    if (statusEl) statusEl.textContent = data.source || '';
  } catch (e) {
    if (statusEl) statusEl.textContent = '';
    renderFinancingChart([]);
    renderFinancingTable([]);
    showToast(e.message || '加载融资数据失败', 'error');
  }
}

function financingMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return (Number(value) / 1e8).toFixed(2) + '亿元';
}

function financingShares(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿股' : (n / 1e4).toFixed(2) + '万股';
}

function renderFinancingChart(rows) {
  const dom = document.getElementById('chartFinancing');
  if (!dom) return;
  if (financingInstance) financingInstance.dispose();
  financingInstance = echarts.init(dom);

  if (!rows.length) {
    financingInstance.setOption({
      title: { text: '暂无融资数据', left: 'center', top: 'center', textStyle: { fontSize: 14, color: '#999' } },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    }, true);
    return;
  }

  const years = rows.map(r => r.year);
  const financing = rows.map(r => +(Number(r.financing_amount || 0) / 1e8).toFixed(2));
  const dividends = rows.map(r => +(Number(r.dividend_amount || 0) / 1e8).toFixed(2));
  const ratios = rows.map(r => r.ratio == null ? null : Number(r.ratio));
  const showLabel = rows.length <= 18;

  financingInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params) {
        const year = params[0].axisValue;
        let html = '<strong>' + year + '</strong><br/>';
        params.forEach(p => {
          if (p.seriesName === '分红融资比') {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value == null ? '-' : Number(p.value).toFixed(2) + '%') + '<br/>';
          } else {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value == null ? '-' : Number(p.value).toFixed(2) + '亿元') + '<br/>';
          }
        });
        return html;
      }
    },
    legend: { top: 4, data: ['A股-累计融资额', 'A股-累计分红', 'A股-累计分红融资比'] },
    dataZoom: [
      { type: 'slider', start: rows.length > 18 ? Math.max(0, 100 - (18 / rows.length * 100)) : 0, end: 100, height: 20, bottom: 10 },
      { type: 'inside' }
    ],
    grid: { left: 64, right: 82, top: 52, bottom: rows.length > 18 ? 54 : 42 },
    xAxis: { type: 'category', data: years, axisLabel: { fontSize: 12 } },
    yAxis: [
      { type: 'value', name: '累计融资/分红', axisLabel: { formatter: v => v + '亿' } },
      { type: 'value', name: '分红融资比', axisLabel: { formatter: v => v + '%' }, splitLine: { show: false } }
    ],
    series: [
      {
        name: 'A股-累计融资额',
        type: 'bar',
        data: financing,
        barMaxWidth: 38,
        itemStyle: { color: '#73b976', borderRadius: [4, 4, 0, 0] },
        label: { show: showLabel, position: 'top', fontSize: 10, formatter: p => p.value ? p.value.toFixed(2) + '亿' : '' }
      },
      {
        name: 'A股-累计分红',
        type: 'bar',
        data: dividends,
        barMaxWidth: 38,
        itemStyle: { color: '#ff6b73', borderRadius: [4, 4, 0, 0] },
        label: { show: showLabel, position: 'top', fontSize: 10, formatter: p => p.value ? p.value.toFixed(2) + '亿' : '' }
      },
      {
        name: 'A股-累计分红融资比',
        type: 'line',
        yAxisIndex: 1,
        data: ratios,
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { color: '#2f8cff', width: 2 },
        itemStyle: { color: '#2f8cff' },
        label: { show: showLabel, position: 'top', fontSize: 10, color: '#2f8cff', formatter: p => p.value == null ? '' : p.value.toFixed(1) + '%' }
      }
    ]
  }, true);
}

function renderFinancingTable(rows) {
  const body = document.getElementById('financingTableBody');
  const empty = document.getElementById('financingEmpty');
  if (!body || !empty) return;
  empty.style.display = rows.length ? 'none' : 'block';
  body.innerHTML = rows.map(r => `
    <tr>
      <td>${esc(r.date || '--')}</td>
      <td>${esc(r.type || '--')}</td>
      <td class="num">${r.issue_price == null ? '--' : Number(r.issue_price).toFixed(2) + '元'}</td>
      <td class="num">${financingShares(r.issue_shares)}</td>
      <td class="num">${financingMoney(r.amount)}</td>
      <td>${esc(r.method || '--')}</td>
      <td>${esc(r.target || '--')}</td>
      <td>${esc(r.price_method || '--')}</td>
    </tr>
  `).join('');
}

// ==================== 股东 ====================

let shareholderCache = [];
let shareholderCacheCode = '';
let shareholderYearRange = 3;
let shareholderPeriodFilter = 'quarter';
let shareholderChangeFilter = 'all';

async function loadShareholders(code, options = {}) {
  if (!code) return;
  const force = Boolean(options.force);
  const statusEl = document.getElementById('shareholdersStatus');
  const wrap = document.getElementById('shareholderGridWrap');
  if (!force && shareholderCacheCode === code && shareholderCache.length) {
    renderShareholders();
    return;
  }
  if (statusEl) statusEl.textContent = force ? '正在更新...' : '加载中...';
  if (wrap) wrap.innerHTML = '<div class="empty" id="shareholdersEmpty">' + (force ? '正在更新股东数据...' : '正在加载股东数据...') + '</div>';
  try {
    const url = '/api/stock/' + code + '/shareholders' + (force ? '?refresh=1' : '');
    const res = await fetch(url);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    shareholderCache = data.periods || [];
    shareholderCacheCode = code;
    renderShareholders();
    if (statusEl) {
      const fetchedAt = data.fetched_at ? ' · ' + data.fetched_at : '';
      statusEl.textContent = (data.source || '') + fetchedAt;
    }
  } catch (e) {
    shareholderCache = [];
    shareholderCacheCode = '';
    renderShareholders();
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '加载股东数据失败', 'error');
  }
}

function refreshShareholders() {
  const code = getCurrentCode();
  if (!code) return;
  loadShareholders(code, { force: true });
}

function setShareholderPeriodFilter(filter) {
  shareholderPeriodFilter = filter;
  document.querySelectorAll('#shareholderPeriodFilter button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === filter);
  });
  renderShareholders();
}

function setShareholderChangeFilter(filter) {
  shareholderChangeFilter = filter;
  document.querySelectorAll('#shareholderChangeFilter button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === filter);
  });
  renderShareholders();
}

function setShareholderYearRange(years) {
  shareholderYearRange = Number(years) || 3;
  document.querySelectorAll('#shareholderYearRangeFilter button').forEach(btn => {
    btn.classList.toggle('active', Number(btn.dataset.years) === shareholderYearRange);
  });
  renderShareholders();
}

function shareholderYearVisible(period, latestYear) {
  if (!period || !period.year || !latestYear) return true;
  return Number(period.year) >= latestYear - shareholderYearRange + 1;
}

function shareholderPeriodVisible(period) {
  if (shareholderPeriodFilter === 'all') return true;
  if (shareholderPeriodFilter === 'year') return period.month_day === '12-31';
  if (shareholderPeriodFilter === 'half') return period.month_day === '06-30' || period.month_day === '12-31';
  return period.is_report_date && ['03-31', '06-30', '09-30', '12-31'].includes(period.month_day);
}

function formatShareholderShares(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿股' : (n / 1e4).toFixed(2) + '万股';
}

function formatShareholderValue(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿元' : (n / 1e4).toFixed(2) + '万元';
}

function shareholderChangeHtml(holder) {
  const type = holder.change_type || '';
  if (type === 'new') return '<span class="shareholder-change new">✓ 新进</span>';
  if (type === 'unchanged') return '<span class="shareholder-change unchanged">↔ 不变</span>';
  const raw = Number(holder.change || 0);
  if (type === 'increase') return `<span class="shareholder-change increase">▲ ${formatShareholderShares(Math.abs(raw))}</span>`;
  if (type === 'decrease') return `<span class="shareholder-change decrease">▼ ${formatShareholderShares(Math.abs(raw))}</span>`;
  return '';
}

function scrollShareholdersToLatest() {
  const wrap = document.getElementById('shareholderGridWrap');
  if (!wrap) return;
  requestAnimationFrame(() => {
    wrap.scrollLeft = wrap.scrollWidth;
  });
}

function renderShareholders() {
  const wrap = document.getElementById('shareholderGridWrap');
  if (!wrap) return;
  const latestYear = shareholderCache.reduce((maxYear, period) => {
    const year = Number(period.year);
    return Number.isFinite(year) ? Math.max(maxYear, year) : maxYear;
  }, 0);
  const periods = shareholderCache.filter(period => shareholderYearVisible(period, latestYear) && shareholderPeriodVisible(period));
  if (!periods.length) {
    wrap.innerHTML = '<div class="empty" id="shareholdersEmpty">暂无股东数据</div>';
    return;
  }

  const visiblePeriods = periods.slice().sort((a, b) => a.date.localeCompare(b.date));
  const yearHeader = visiblePeriods.map((period, index) => {
    const prev = visiblePeriods[index - 1];
    const startsYear = !prev || prev.year !== period.year;
    const span = visiblePeriods.filter(item => item.year === period.year).length;
    if (!startsYear) return '';
    return `<th class="shareholder-period year-break" colspan="${span}">${esc(period.year)}</th>`;
  }).join('');

  const periodHeader = visiblePeriods.map((period, index) => {
    const prev = visiblePeriods[index - 1];
    const yearBreak = !prev || prev.year !== period.year ? ' year-break' : '';
    return `<th class="shareholder-period${yearBreak}">
      <div class="shareholder-period-main">${esc(period.label || period.date)}</div>
      <div class="shareholder-period-sub">
        总股本: ${formatShareholderShares(period.total_shares)}<br>
        前十合计: ${period.top10_ratio == null ? '--' : Number(period.top10_ratio).toFixed(2) + '%'} (${formatShareholderShares(period.top10_shares)})
      </div>
    </th>`;
  }).join('');

  const bodyRows = [];
  for (let rank = 1; rank <= 10; rank++) {
    const cells = visiblePeriods.map((period, index) => {
      const holder = (period.holders || []).find(item => item.rank === rank);
      const prev = visiblePeriods[index - 1];
      const yearBreak = !prev || prev.year !== period.year ? ' year-break' : '';
      if (!holder) return `<td class="shareholder-cell${yearBreak}">--</td>`;
      const filteredOut = shareholderChangeFilter !== 'all' && holder.change_type !== shareholderChangeFilter;
      return `<td class="shareholder-cell${yearBreak}${filteredOut ? ' filtered-out' : ''}">
        <div class="shareholder-name" title="${esc(holder.name)}">${esc(holder.name)}</div>
        <div class="shareholder-meta">
          ${shareholderChangeHtml(holder)}
          <span class="shareholder-ratio">${holder.hold_ratio == null ? '--' : Number(holder.hold_ratio).toFixed(2) + '%'}</span>
          (${formatShareholderShares(holder.hold_num)})
          ${holder.shares_type ? '<span class="shareholder-type">' + esc(holder.shares_type) + '</span>' : ''}
        </div>
      </td>`;
    }).join('');
    bodyRows.push(`<tr><td class="rank-col">第${rank}</td>${cells}</tr>`);
  }

  wrap.innerHTML = `<table class="shareholder-grid">
    <thead>
      <tr><th class="rank-col"></th>${yearHeader}</tr>
      <tr><th class="rank-col">排名</th>${periodHeader}</tr>
    </thead>
    <tbody>${bodyRows.join('')}</tbody>
  </table>`;
  scrollShareholdersToLatest();
}

// ==================== 互动易 ====================

let irmAutoSyncStarted = false;

async function startIrmAutoSync() {
  if (irmAutoSyncStarted) return;
  irmAutoSyncStarted = true;
  try {
    await fetch('/api/irm/sync', { method: 'POST' });
    pollIrmStatus();
  } catch (e) {
    // 自动抓取静默失败，不影响正常打开系统。
  }
}

async function pollIrmStatus() {
  try {
    const res = await fetch('/api/irm/status');
    const data = await res.json();
    const statusEl = document.getElementById('irmStatus');
    if (statusEl && data.message) statusEl.textContent = data.message;
    if (data.running) {
      setTimeout(pollIrmStatus, 4000);
    } else if (currentTab === 'irm') {
      loadIrm(getCurrentCode(), { silent: true });
    }
  } catch (e) {
    // 状态轮询失败时不打扰页面。
  }
}

async function loadIrm(code, options = {}) {
  if (!code) return;
  const statusEl = document.getElementById('irmStatus');
  const list = document.getElementById('irmList');
  if (statusEl && !options.silent) statusEl.textContent = '加载中...';
  if (list && !options.silent) list.innerHTML = '<div class="empty" id="irmEmpty">正在加载互动易问答...</div>';
  try {
    const res = await fetch('/api/stock/' + code + '/irm');
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    renderIrm(data);
  } catch (e) {
    if (list) list.innerHTML = '<div class="empty" id="irmEmpty">互动易问答加载失败</div>';
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '加载互动易失败', 'error');
  }
}

async function syncCurrentIrm() {
  const code = getCurrentCode();
  if (!code) return;
  const statusEl = document.getElementById('irmStatus');
  if (statusEl) statusEl.textContent = '抓取中...';
  try {
    const res = await fetch('/api/stock/' + code + '/irm/sync', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || '抓取失败');
    if (statusEl) statusEl.textContent = data.message || ('本次新增 ' + (data.inserted || 0) + ' 条');
    await loadIrm(code, { silent: true });
  } catch (e) {
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '互动易抓取失败', 'error');
  }
}

function formatIrmTime(value) {
  if (!value) return '--';
  const text = String(value);
  return text.length >= 16 ? text.slice(0, 16) : text;
}

function renderIrm(data) {
  const list = document.getElementById('irmList');
  const statusEl = document.getElementById('irmStatus');
  if (!list) return;
  const items = data.items || [];
  const sync = data.sync || {};
  if (statusEl) {
    const parts = [];
    if (data.source) parts.push(data.source);
    if (sync.running) parts.push('后台抓取中');
    else if (sync.message) parts.push(sync.message);
    statusEl.textContent = parts.join(' | ');
  }
  if (!data.supported) {
    list.innerHTML = '<div class="empty" id="irmEmpty">互动问答目前支持沪深股票，其他市场暂不支持。</div>';
    return;
  }
  if (!items.length) {
    list.innerHTML = '<div class="empty" id="irmEmpty">暂无已答复的互动易问答，点击“立即抓取”试试。</div>';
    return;
  }
  list.innerHTML = items.map(item => `
    <article class="irm-item">
      <div class="irm-line">
        <span class="irm-badge question">提问</span>
        <span class="irm-content">${esc(item.question || '')}</span>
        <span class="irm-time">提问于 ${formatIrmTime(item.question_time)}</span>
        ${item.original_url ? `<a class="irm-link" href="${esc(item.original_url)}" target="_blank" rel="noopener">原文链接</a>` : ''}
      </div>
      <div class="irm-line">
        <span class="irm-badge answer">回答</span>
        <span class="irm-content">${esc(item.answer || '')}</span>
        <span class="irm-time">回答于 ${formatIrmTime(item.answer_time || item.update_time)}</span>
      </div>
      <div class="irm-actions">
        <span>转发(${Number(item.forward_count || 0)})</span>
        <span>赞(${Number(item.praise_count || 0)})</span>
        <span>收藏(${Number(item.favorite_count || 0)})</span>
        ${item.source ? `<span>${esc(item.source)}</span>` : ''}
      </div>
    </article>
  `).join('');
}

// ==================== K线图 ====================

let klineInstance = null;

function calcEMA(values, period) {
  const k = 2 / (period + 1);
  const ema = [];
  values.forEach((value, index) => {
    if (index === 0) {
      ema.push(value);
    } else {
      ema.push(value * k + ema[index - 1] * (1 - k));
    }
  });
  return ema;
}

function calcMACD(closes) {
  const ema12 = calcEMA(closes, 12);
  const ema26 = calcEMA(closes, 26);
  const dif = closes.map((_, i) => ema12[i] - ema26[i]);
  const dea = calcEMA(dif, 9);
  const macd = dif.map((value, i) => 2 * (value - dea[i]));
  return { dif, dea, macd };
}

function formatTurnover(value) {
  if (!Number.isFinite(value)) return '-';
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)} 亿`;
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)} 万`;
  return value.toFixed(0);
}

function currentKlinePeriod() {
  return document.querySelector('#chartKlinePeriod button.active')?.dataset.period || 'day';
}

function setKlinePeriod(period) {
  document.querySelectorAll('#chartKlinePeriod button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.period === period);
  });
  loadKline();
}

async function loadKline() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const days = document.getElementById('chartPeriod').value;
  const period = currentKlinePeriod();
  const periodTextMap = { day: '日K', week: '周K', month: '月K', quarter: '季K', year: '年K' };
  const dom = document.getElementById('chartKline');
  const statusEl = document.getElementById('chartStatus');
  statusEl.textContent = '加载中...';

  try {
    const res = await fetch(`/api/stock/${code}/kline?days=${days}&period=${period}`);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (data.error) { statusEl.textContent = data.error; return; }
    if (!data || data.length === 0) { statusEl.textContent = '无数据'; return; }

    const dates = data.map(d => d.date);
    const ohlc = data.map(d => [d.open, d.close, d.low, d.high]);
    const volumes = data.map(d => d.volume);
    const amounts = data.map(d => d.amount || (d.volume * d.close * 100));
    const closes = data.map(d => d.close);
    const macdData = calcMACD(closes);
    const highest = data.reduce((best, item, index) => item.high > best.value ? { value: item.high, index } : best, { value: -Infinity, index: 0 });
    const lowest = data.reduce((best, item, index) => item.low < best.value ? { value: item.low, index } : best, { value: Infinity, index: 0 });

    if (klineInstance) klineInstance.dispose();
    klineInstance = echarts.init(dom);

    klineInstance.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: function(params) {
          const d = data[params[0].dataIndex];
          return `<strong>${d.date} ${periodTextMap[period]}</strong><br/>
            开盘: ${d.open.toFixed(2)}<br/>
            收盘: ${d.close.toFixed(2)}<br/>
            最高: ${d.high.toFixed(2)}<br/>
            最低: ${d.low.toFixed(2)}<br/>
            成交量: ${(d.volume / 10000).toFixed(0)} 万手<br/>
            成交额: ${formatTurnover(d.amount || (d.volume * d.close * 100))}<br/>
            DIF: ${macdData.dif[params[0].dataIndex].toFixed(3)}<br/>
            DEA: ${macdData.dea[params[0].dataIndex].toFixed(3)}<br/>
            MACD: ${macdData.macd[params[0].dataIndex].toFixed(3)}`;
        }
      },
      grid: [
        { left: '8%', right: '8%', top: '5%', height: '52%' },
        { left: '8%', right: '8%', top: '64%', height: '14%' },
        { left: '8%', right: '8%', top: '84%', height: '11%' }
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 2, axisLabel: { formatter: v => v.slice(5) } }
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, splitArea: { show: true } },
        { type: 'value', gridIndex: 1, axisLabel: { formatter: v => (v / 10000).toFixed(0) + '万' } },
        {
          type: 'value',
          gridIndex: 1,
          position: 'right',
          splitLine: { show: false },
          axisLabel: { formatter: v => formatTurnover(v).replace(' ', '') }
        },
        {
          type: 'value',
          gridIndex: 2,
          scale: true,
          splitLine: { show: true },
          axisLabel: { formatter: v => v.toFixed(2) }
        }
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: '#cf1322', color0: '#389e0d', borderColor: '#cf1322', borderColor0: '#389e0d' },
          markPoint: {
            symbol: 'circle',
            symbolSize: 1,
            label: { color: chartTextColor(), fontSize: 12, fontWeight: 600, formatter: p => p.value },
            data: [
              {
                name: '最高价',
                coord: [dates[highest.index], highest.value],
                value: highest.value.toFixed(2),
                label: { position: 'top' },
                itemStyle: { color: 'transparent' }
              },
              {
                name: '最低价',
                coord: [dates[lowest.index], lowest.value],
                value: lowest.value.toFixed(2),
                label: { position: 'bottom' },
                itemStyle: { color: 'transparent' }
              }
            ]
          },
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes,
          xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: {
            color: function(p) {
              const d = data[p.dataIndex];
              return d.close >= d.open ? '#cf1322' : '#389e0d';
            }
          }
        },
        {
          name: '成交额',
          type: 'line',
          data: amounts,
          xAxisIndex: 1, yAxisIndex: 2,
          symbol: 'none',
          smooth: true,
          lineStyle: { color: '#5470c6', width: 1.8 }
        },
        {
          name: 'MACD',
          type: 'bar',
          data: macdData.macd,
          xAxisIndex: 2, yAxisIndex: 3,
          barMaxWidth: 8,
          itemStyle: {
            color: function(p) {
              return p.value >= 0 ? '#cf1322' : '#389e0d';
            }
          }
        },
        {
          name: 'DIF',
          type: 'line',
          data: macdData.dif,
          xAxisIndex: 2, yAxisIndex: 3,
          symbol: 'none',
          lineStyle: { color: '#fa8c16', width: 1.4 }
        },
        {
          name: 'DEA',
          type: 'line',
          data: macdData.dea,
          xAxisIndex: 2, yAxisIndex: 3,
          symbol: 'none',
          lineStyle: { color: '#4a6cf7', width: 1.4 }
        }
      ]
    });
    statusEl.textContent = `${periodTextMap[period]} · ${data.length} 条数据`;
    statusEl.style.color = '#52c41a';
  } catch (e) {
    statusEl.textContent = '加载失败';
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 估值分析 ====================

let valInstance = null;
let pbInstance = null;
let dyInstance = null;

async function loadValuation(days) {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const dom = document.getElementById('chartValuation');
  const sidebar = document.getElementById('valSidebar');
  const statusEl = document.getElementById('valStatus');
  statusEl.textContent = '加载中...';

  // Highlight active button
  document.querySelectorAll('#panel-valuation .btn-sm').forEach(b => {
    b.style.background = b.onclick && b.onclick.toString().includes(days) ? '#333' : '#f0f0f0';
    b.style.color = b.onclick && b.onclick.toString().includes(days) ? '#fff' : '#333';
  });

  try {
    const res = await fetch(`/api/stock/${code}/valuation?days=${days}`);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (data.error) { statusEl.textContent = data.error; return; }

    // Filter by days
    const cutoff = days > 3650 ? '2000-01-01' : new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    const peFiltered = data.pe_data.filter(p => p.date >= cutoff);
    const priceFiltered = data.price_data.filter(p => p.date >= cutoff);

    // Build chart - use price dates as unified x-axis, align PE via date map
    const peMap = {}; peFiltered.forEach(p => peMap[p.date] = p.pe);
    const dates = priceFiltered.map(p => p.date);
    const peValues = dates.map(d => peMap[d] != null ? peMap[d] : null);
    const priceValues = priceFiltered.map(p => p.close);
    const pMin = priceValues.length ? Math.min(...priceValues) : null;
    const pMax = priceValues.length ? Math.max(...priceValues) : null;

    // Recalculate percentiles & stats from filtered PE data
    const filteredPeVals = peValues.filter(v => v != null).sort((a, b) => a - b);
    const n = filteredPeVals.length;
    const fp80 = n > 0 ? filteredPeVals[Math.floor(n * 0.8)] : null;
    const fp50 = n > 0 ? filteredPeVals[Math.floor(n * 0.5)] : null;
    const fp20 = n > 0 ? filteredPeVals[Math.floor(n * 0.2)] : null;
    const fmax = n > 0 ? filteredPeVals[n - 1] : null;
    const fmin = n > 0 ? filteredPeVals[0] : null;
    const favg = n > 0 ? +(filteredPeVals.reduce((a, b) => a + b, 0) / n).toFixed(2) : null;
    // Current PE and its percentile (优先使用腾讯实时 PE-TTM)
    const currentPE = data.realtime_pe || data.current_pe;
    const fpct = currentPE && n > 0 ? +(filteredPeVals.filter(v => v <= currentPE).length / n * 100).toFixed(2) : null;

    // Percentile lines
    const p80Line = dates.map(() => fp80);
    const p50Line = dates.map(() => fp50);
    const p20Line = dates.map(() => fp20);

    if (valInstance) valInstance.dispose();
    valInstance = echarts.init(dom);
    valInstance.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['PE-TTM', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) } },
      yAxis: [
        { type: 'value', name: 'PE', min: fmin ? +(fmin * 0.99).toFixed(2) : 0, max: fmax ? +(fmax * 1.01).toFixed(2) : undefined, splitNumber: 5 },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: 'PE-TTM', type: 'line', data: peValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#4a6cf7' }, label: { formatter: '{c}' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#389e0d' }, label: { formatter: '{c}' } }] } },
        { name: '80%分位', type: 'line', data: p80Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: p50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: p20Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    // Sidebar
    sidebar.innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">PE-TTM</div>
      <div style="margin-bottom:4px">当前值: <b style="color:#4a6cf7">${currentPE || '-'}</b></div>
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${fpct != null ? fpct + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">80%: <b>${fp80 || '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${fp50 || '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:8px">20%: <b>${fp20 || '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">最大: <b>${fmax || '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${favg || '-'}</b></div>
      <div style="color:#389e0d">最小: <b>${fmin || '-'}</b></div>`;

    // ===== PB 估值（扣商誉）=====
    const pbFiltered = (data.pb_data || []).filter(p => p.date >= cutoff);
    const pbMap = {}; pbFiltered.forEach(p => pbMap[p.date] = p.pb);
    const pbValues = dates.map(d => pbMap[d] != null ? pbMap[d] : null);
    const filteredPbVals = pbValues.filter(v => v != null).sort((a, b) => a - b);
    const pbn = filteredPbVals.length;
    const bp80 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.8)] : null;
    const bp50 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.5)] : null;
    const bp20 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.2)] : null;
    const bmax = pbn > 0 ? filteredPbVals[pbn - 1] : null;
    const bmin = pbn > 0 ? filteredPbVals[0] : null;
    const bavg = pbn > 0 ? +(filteredPbVals.reduce((a, b) => a + b, 0) / pbn).toFixed(2) : null;
    // 优先使用计算 PB，实时 PB 仅作参考（腾讯行情 PB 可能与扣商誉后的计算值偏差较大）
    const currentPB = data.current_pb;
    const realtimePB = data.realtime_pb;
    const bpct = currentPB && pbn > 0 ? +(filteredPbVals.filter(v => v <= currentPB).length / pbn * 100).toFixed(2) : null;

    // PB Y轴 padding: fmin<1 时扩到 5%，PE 的 1% 对 PB 太紧
    const pbPad = (bmin != null && bmin < 1) ? 0.05 : 0.01;
    const pb80Line = dates.map(() => bp80);
    const pb50Line = dates.map(() => bp50);
    const pb20Line = dates.map(() => bp20);

    if (pbInstance) pbInstance.dispose();
    pbInstance = echarts.init(document.getElementById('chartPb'));
    pbInstance.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['PB(扣商誉)', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) }, boundaryGap: false },
      yAxis: [
        { type: 'value', name: 'PB', min: bmin ? +(bmin * (1 - pbPad)).toFixed(2) : 0, max: bmax ? +(bmax * (1 + pbPad)).toFixed(2) : undefined, splitNumber: 5 },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: 'PB(扣商誉)', type: 'line', data: pbValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', connectNulls: false, markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#4a6cf7' }, label: { formatter: '{c}' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#389e0d' }, label: { formatter: '{c}' } }] } },
        { name: '80%分位', type: 'line', data: pb80Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: pb50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: pb20Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    // PB 侧边栏 — 显示计算 PB（主值）和实时 PB（参考）
    const realtimePBText = (realtimePB != null && realtimePB !== currentPB) 
      ? `<div style="font-size:11px;color:#999;margin-top:2px">实时 PB: <b style="color:#999">${realtimePB.toFixed(2)}</b>（腾讯行情）</div>` 
      : '';
    document.getElementById('pbSidebar').innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">PB(扣商誉)</div>
      <div style="margin-bottom:4px">计算 PB: <b style="color:#4a6cf7">${currentPB ? currentPB.toFixed(2) : '-'}</b></div>
      ${realtimePBText}
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${bpct != null ? bpct + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">80%: <b>${bp80 || '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${bp50 || '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:8px">20%: <b>${bp20 || '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">最大: <b>${bmax || '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${bavg || '-'}</b></div>
      <div style="color:#389e0d">最小: <b>${bmin || '-'}</b></div>`;

    // ===== 股息率估值 =====
    const dyFiltered = (data.dividend_yield_data || []).filter(p => p.date >= cutoff);
    const dyMap = {}; dyFiltered.forEach(p => dyMap[p.date] = p.dividend_yield);
    const dyValues = dates.map(d => dyMap[d] != null ? dyMap[d] : null);
    const filteredDyVals = dyValues.filter(v => v != null).sort((a, b) => a - b);
    const dyn = filteredDyVals.length;
    const dy80 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.8)] : null;
    const dy50 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.5)] : null;
    const dy20 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.2)] : null;
    const dymax = dyn > 0 ? filteredDyVals[dyn - 1] : null;
    const dymin = dyn > 0 ? filteredDyVals[0] : null;
    const dyavg = dyn > 0 ? +(filteredDyVals.reduce((a, b) => a + b, 0) / dyn).toFixed(2) : null;
    const currentDY = data.current_dividend_yield || (dyFiltered.length ? dyFiltered[dyFiltered.length - 1].dividend_yield : null);
    const dypct = currentDY && dyn > 0 ? +(filteredDyVals.filter(v => v <= currentDY).length / dyn * 100).toFixed(2) : null;
    const dy80Line = dates.map(() => dy80);
    const dy50Line = dates.map(() => dy50);
    const dy20Line = dates.map(() => dy20);
    const dyPad = (dymin != null && dymin < 1) ? 0.08 : 0.04;

    if (dyInstance) dyInstance.dispose();
    dyInstance = echarts.init(document.getElementById('chartDividendYield'));
    dyInstance.setOption({
      tooltip: {
        trigger: 'axis',
        valueFormatter: v => v == null ? '-' : Number(v).toFixed(2) + '%'
      },
      legend: { data: ['股息率', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) }, boundaryGap: false },
      yAxis: [
        { type: 'value', name: '股息率(%)', min: dymin ? Math.max(0, +(dymin * (1 - dyPad)).toFixed(2)) : 0, max: dymax ? +(dymax * (1 + dyPad)).toFixed(2) : undefined, splitNumber: 5, axisLabel: { formatter: v => v + '%' } },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: '股息率', type: 'line', data: dyValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', connectNulls: false, markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#52c41a' }, label: { formatter: p => Number(p.value).toFixed(2) + '%' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#ff4d4f' }, label: { formatter: p => Number(p.value).toFixed(2) + '%' } }] } },
        { name: '80%分位', type: 'line', data: dy80Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: dy50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: dy20Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    document.getElementById('dySidebar').innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">股息率</div>
      <div style="margin-bottom:4px">当前值: <b style="color:#4a6cf7">${currentDY != null ? currentDY.toFixed(2) + '%' : '-'}</b></div>
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${dypct != null ? dypct + '%' : '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:2px">80%: <b>${dy80 != null ? dy80.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${dy50 != null ? dy50.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:8px">20%: <b>${dy20 != null ? dy20.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:2px">最大: <b>${dymax != null ? dymax.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${dyavg != null ? dyavg.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#cf1322">最小: <b>${dymin != null ? dymin.toFixed(2) + '%' : '-'}</b></div>`;

    statusEl.textContent = `${peFiltered.length} 个数据点`;
    statusEl.style.color = '#52c41a';
  } catch (e) {
    statusEl.textContent = '加载失败';
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 列表页 ====================
