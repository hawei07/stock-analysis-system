let navChart = null;
let allocationChart = null;
let latestPortfolioData = {positions: [], summary: {}};
let latestFeeConfig = {commission_rate: 0.00025, min_commission: 5, stamp_tax_rate: 0.0005, transfer_fee_rate: 0.00001};
let amountPrivacyMode = localStorage.getItem('portfolioAmountPrivacy') === 'hidden';
let tradeRows = [];
let tradesPage = 1;
let tradesCollapsed = true;
let tradesLoaded = false;
const TRADES_PAGE_SIZE = 5;
let positionSortKey = localStorage.getItem('portfolioPositionSortKey') || 'market_value';
let positionSortDir = localStorage.getItem('portfolioPositionSortDir') || 'desc';
let navHistoryRows = [];
let navHistoryPage = 1;
const NAV_HISTORY_PAGE_SIZE = 20;

window.onThemeChanged = function() {
  if (allocationChart) {
    allocationChart.dispose();
    allocationChart = null;
    if (document.getElementById('allocationModalOverlay')?.classList.contains('active')) renderAllocationPie();
  }
  if (navChart) {
    navChart.dispose();
    navChart = null;
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
  loadPortfolio();
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
