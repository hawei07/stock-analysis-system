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
  if (tab === 'dashboard') loadFundamentalDashboard(code);
  else if (tab === 'compare') initCompareDashboard(code);
  else if (tab === 'capital') initCapitalAllocation(code);
  else if (tab === 'chart') loadKline();
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
    const stock = await StockApi.getJson('/api/stock/' + code);
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
    loadPortfolioPositionCard(stock.code);

    refreshCurrentDetailTab(stock.code);
  } catch (e) {
    showToast('加载详情失败', 'error');
  }
}

async function loadPortfolioPositionCard(code) {
  const sharesEl = document.getElementById('portfolioShares');
  if (!sharesEl) return;
  sharesEl.textContent = '--';
  try {
    const data = await StockApi.getJson('/api/portfolio/positions/' + encodeURIComponent(code));
    if (!data.held) {
      sharesEl.textContent = '未持仓';
      return;
    }
    const shares = Number(data.shares || 0);
    sharesEl.textContent = StockFormat.shares(shares);
  } catch (e) {
    sharesEl.textContent = '--';
  }
}
