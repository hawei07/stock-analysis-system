const PortfolioState = {
  charts: {
    nav: null,
    allocation: null
  },
  portfolioData: {
    positions: [],
    summary: {}
  },
  feeConfig: {
    commission_rate: 0.00025,
    min_commission: 5,
    stamp_tax_rate: 0.0005,
    transfer_fee_rate: 0.00001
  },
  amountPrivacyMode: localStorage.getItem('portfolioAmountPrivacy') === 'hidden',
  trades: {
    rows: [],
    page: 1,
    collapsed: true,
    loaded: false,
    pageSize: 5
  },
  positions: {
    sortKey: localStorage.getItem('portfolioPositionSortKey') || 'market_value',
    sortDir: localStorage.getItem('portfolioPositionSortDir') || 'desc'
  },
  navHistory: {
    rows: [],
    page: 1,
    pageSize: 20,
    loadPromise: null,
    loaded: false
  },
  earningsCalendar: {
    period: 'year',
    display: 'amount',
    selectedMonth: ''
  },
  autoRefresh: {
    portfolioPricesTimer: null,
    portfolioPricesInFlight: false,
    portfolioPricesListenerBound: false,
    portfolioLoadPromise: null
  }
};

function setPortfolioData(data) {
  PortfolioState.portfolioData = data || {positions: [], summary: {}};
  if (data?.fee_config) setFeeConfig(data.fee_config);
  return PortfolioState.portfolioData;
}

function setFeeConfig(config) {
  if (config) PortfolioState.feeConfig = config;
  return PortfolioState.feeConfig;
}

function resetTradesPage() {
  PortfolioState.trades.page = 1;
}

function setTradesRows(rows) {
  PortfolioState.trades.rows = Array.isArray(rows) ? rows : [];
  PortfolioState.trades.loaded = true;
  return PortfolioState.trades.rows;
}

function setNavHistoryRows(rows) {
  PortfolioState.navHistory.rows = Array.isArray(rows) ? rows : [];
  PortfolioState.navHistory.loaded = true;
  return PortfolioState.navHistory.rows;
}

window.onThemeChanged = function() {
  if (PortfolioState.charts.allocation) {
    PortfolioState.charts.allocation.dispose();
    PortfolioState.charts.allocation = null;
    if (document.getElementById('allocationModalOverlay')?.classList.contains('active')) renderAllocationPie();
  }
  if (PortfolioState.charts.nav) {
    PortfolioState.charts.nav.dispose();
    PortfolioState.charts.nav = null;
    loadNav();
  }
};
document.addEventListener('DOMContentLoaded', () => {
  updateThemeButton();
  updateAmountPrivacyButton();
  checkCloudUpdateOnStartup();
  startCloudBackupStatusPolling();
  mountFlowPanel();
  loadFeeConfig();
  loadPortfolio().finally(startPortfolioPriceAutoRefresh);
  loadFlows();
  loadActions();
  loadNav(true);
  const flowDate = document.getElementById('flowDate');
  if (flowDate && !flowDate.value) flowDate.value = new Date().toISOString().slice(0, 10);
  const tradeDate = document.getElementById('tradeDate');
  if (tradeDate && !tradeDate.value) tradeDate.value = new Date().toISOString().slice(0, 10);
  const actionDate = document.getElementById('actionDate');
  if (actionDate && !actionDate.value) actionDate.value = new Date().toISOString().slice(0, 10);
});
