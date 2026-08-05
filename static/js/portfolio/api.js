(function () {
  function loadPortfolio() {
    return StockApi.getJson('/api/portfolio');
  }

  function loadFeeConfig() {
    return StockApi.getJson('/api/portfolio/fee-config');
  }

  function saveFeeConfig(payload) {
    return StockApi.putJson('/api/portfolio/fee-config', payload);
  }

  function saveTrade(payload) {
    return StockApi.postJson('/api/portfolio/trades', payload);
  }

  function loadTrades() {
    return StockApi.getJson('/api/portfolio/trades');
  }

  function voidTrade(id, voidNote) {
    return StockApi.postJson('/api/portfolio/trades/' + encodeURIComponent(id) + '/void', {void_note: voidNote});
  }

  function saveAction(payload) {
    return StockApi.postJson('/api/portfolio/actions', payload);
  }

  function loadActions() {
    return StockApi.getJson('/api/portfolio/actions');
  }

  function voidAction(id, voidNote) {
    return StockApi.postJson('/api/portfolio/actions/' + encodeURIComponent(id) + '/void', {void_note: voidNote});
  }

  function loadFlows() {
    return StockApi.getJson('/api/portfolio/flows');
  }

  function saveFlow(payload) {
    return StockApi.postJson('/api/portfolio/flows', payload);
  }

  function deleteFlow(id) {
    return StockApi.deleteJson('/api/portfolio/flows/' + encodeURIComponent(id));
  }

  function audit() {
    return StockApi.getJson('/api/portfolio/audit');
  }

  function rebuild() {
    return StockApi.postJson('/api/portfolio/rebuild');
  }

  function saveDividend(code, dividendPerShare) {
    return StockApi.putJson('/api/portfolio/positions/' + encodeURIComponent(code) + '/dividend', {
      dividend_per_share: dividendPerShare
    });
  }

  function resetDividend(code) {
    return StockApi.postJson('/api/portfolio/positions/' + encodeURIComponent(code) + '/dividend/reset');
  }

  function saveSnapshot() {
    return StockApi.postJson('/api/portfolio/snapshot');
  }

  function loadNav(live = false) {
    return StockApi.getJson('/api/portfolio/nav' + (live ? '?live=1' : ''));
  }

  function searchStock(keyword) {
    return StockApi.getJson('/api/stock-search?keyword=' + encodeURIComponent(keyword));
  }

  window.PortfolioApi = {
    loadPortfolio,
    loadFeeConfig,
    saveFeeConfig,
    saveTrade,
    loadTrades,
    voidTrade,
    saveAction,
    loadActions,
    voidAction,
    loadFlows,
    saveFlow,
    deleteFlow,
    audit,
    rebuild,
    saveDividend,
    resetDividend,
    saveSnapshot,
    loadNav,
    searchStock
  };
})();
