function openTradeModal(code, type = 'buy') {
  const positions = PortfolioState.portfolioData.positions || [];
  const row = positions.find(p => String(p.code) === String(code)) || {};
  const isKnownPosition = Boolean(row.code);
  const codeInput = document.getElementById('tradeCodeInput');
  document.getElementById('tradeModalOverlay').classList.add('active');
  codeInput.value = code || '';
  codeInput.readOnly = isKnownPosition;
  document.getElementById('tradeType').value = type;
  document.getElementById('tradeDate').value = new Date().toISOString().slice(0, 10);
  document.getElementById('tradeSharesInput').value = '';
  document.getElementById('tradePriceInput').value = row.price == null ? '' : price2(row.price);
  document.getElementById('tradeNoteInput').value = '';
  document.getElementById('tradeStockName').textContent = isKnownPosition ? `${row.name || ''} ${code}` : '买入股票';
  document.getElementById('tradeStockMeta').textContent = isKnownPosition
    ? [
        `当前持仓 ${plain(row.shares)} 股`,
        row.cost_price == null ? '成本价 --' : `成本价 ${plain(row.cost_price)} ${row.cost_price_currency || ''}`,
        row.price == null ? '最新价 --' : `最新价 ${money(row.price)} ${row.price_currency || ''}`
      ].join(' · ')
    : '输入股票代码或名称，成交后系统自动创建持仓并计算成本价';
  updateTradeModalMode();
  updateTradeFeeEstimate();
  setTimeout(() => (isKnownPosition ? document.getElementById('tradeSharesInput') : codeInput).focus(), 0);
}

function updateTradeModalMode() {
  const code = document.getElementById('tradeCodeInput').value;
  const type = document.getElementById('tradeType').value;
  const positions = PortfolioState.portfolioData.positions || [];
  const row = positions.find(p => String(p.code) === String(code)) || {};
  const sharesInput = document.getElementById('tradeSharesInput');
  const isSell = type === 'sell';
  document.getElementById('tradeModalTitle').textContent = isSell ? '卖出' : '买入';
  if (isSell && row.shares != null) {
    sharesInput.max = Number(row.shares);
    document.getElementById('tradeHint').textContent = `最多可卖出 ${plain(row.shares)} 股；卖出会按摊薄成本口径重算剩余成本价`;
  } else {
    sharesInput.removeAttribute('max');
    document.getElementById('tradeHint').textContent = isSell
      ? '卖出必须从当前持仓股票后方进入'
      : '买入会自动按成交价计算新的加权成本价；再次买入时按加权平均成本计算';
  }
}

function closeTradeModal() {
  document.getElementById('tradeModalOverlay').classList.remove('active');
}

function openActionModal(code) {
  const row = (PortfolioState.portfolioData.positions || []).find(p => String(p.code) === String(code)) || {};
  document.getElementById('actionModalOverlay').classList.add('active');
  document.getElementById('actionCodeInput').value = code;
  document.getElementById('actionDate').value = new Date().toISOString().slice(0, 10);
  document.getElementById('actionType').value = 'cash_dividend';
  document.getElementById('actionCashInput').value = '';
  document.getElementById('actionSharesInput').value = '';
  document.getElementById('actionPriceInput').value = '';
  document.getElementById('actionNoteInput').value = '';
  document.getElementById('actionStockName').textContent = `${row.name || ''} ${code}`;
  document.getElementById('actionStockMeta').textContent = [
    `当前持仓 ${plain(row.shares)} 股`,
    row.cost_price == null ? '成本价 --' : `成本价 ${plain(row.cost_price)} ${row.cost_price_currency || ''}`
  ].join(' · ');
  updateActionModalMode();
  setTimeout(() => document.getElementById('actionCashInput').focus(), 0);
}

function updateActionModalMode() {
  const type = document.getElementById('actionType').value;
  const cashField = document.getElementById('actionCashField');
  const sharesField = document.getElementById('actionSharesField');
  const priceField = document.getElementById('actionPriceField');
  cashField.style.display = type === 'cash_dividend' ? '' : 'none';
  sharesField.style.display = type === 'bonus_share' || type === 'rights_issue' ? '' : 'none';
  priceField.style.display = type === 'rights_issue' ? '' : 'none';
  const hint = document.getElementById('actionHint');
  if (type === 'cash_dividend') {
    hint.textContent = '现金分红会增加现金，并用到账金额摊薄当前持仓成本价';
  } else if (type === 'bonus_share') {
    hint.textContent = '送股/转增只增加股数，总成本不变，每股成本价会自动摊薄';
  } else {
    hint.textContent = '配股会扣现金并增加股数，按配股金额重算成本价';
  }
}

function closeActionModal() {
  document.getElementById('actionModalOverlay').classList.remove('active');
}

async function saveAction() {
  const payload = {
    action_date: document.getElementById('actionDate').value,
    action_type: document.getElementById('actionType').value,
    code: document.getElementById('actionCodeInput').value,
    cash_amount: document.getElementById('actionCashInput').value,
    shares: document.getElementById('actionSharesInput').value,
    price: document.getElementById('actionPriceInput').value,
    note: document.getElementById('actionNoteInput').value.trim()
  };
  try {
    const data = await PortfolioApi.saveAction(payload);
    if (data.error) throw new Error(data.error || '保存权益失败');
    setPortfolioData(data);
    closeActionModal();
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    resetTradesPage();
    renderTrades(data.trades || []);
    renderActions(data.actions || []);
    renderFlows(data.flows || []);
    await loadNav();
    showToast('权益事件已保存，并自动摊薄持仓成本', 'success');
  } catch (e) {
    showToast(e.message || '保存权益失败', 'error');
  }
}

async function saveTrade() {
  const tradeDate = document.getElementById('tradeDate').value;
  const tradeType = document.getElementById('tradeType').value;
  const identifier = document.getElementById('tradeCodeInput').value.trim();
  const shares = document.getElementById('tradeSharesInput').value;
  const price = document.getElementById('tradePriceInput').value;
  const note = document.getElementById('tradeNoteInput').value.trim();
  try {
    const code = await resolveStockCode(identifier);
    if (tradeType === 'sell' && !(PortfolioState.portfolioData.positions || []).some(p => String(p.code) === String(code))) {
      throw new Error('卖出必须从当前持仓股票后方进入');
    }
    const data = await PortfolioApi.saveTrade({trade_date: tradeDate, trade_type: tradeType, code, shares, price, note});
    if (data.error) throw new Error(data.error || '保存交易失败');
    setPortfolioData(data);
    document.getElementById('tradeCodeInput').value = '';
    document.getElementById('tradeSharesInput').value = '';
    document.getElementById('tradePriceInput').value = '';
    document.getElementById('tradeNoteInput').value = '';
    closeTradeModal();
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    resetTradesPage();
    renderTrades(data.trades || []);
    renderActions(data.actions || []);
    renderFlows(data.flows || []);
    await loadNav();
    showToast((tradeType === 'buy' ? '买入' : '卖出') + '已保存，并自动更新持仓成本', 'success');
  } catch (e) {
    showToast(e.message || '保存交易失败', 'error');
  }
}

async function resolveStockCode(identifier) {
  if (/^\d{5,6}$/.test(identifier)) return identifier;
  if (/^hk\d{1,5}$/i.test(identifier)) return identifier.replace(/^hk/i, '').padStart(5, '0');
  const list = await PortfolioApi.searchStock(identifier);
  if (!Array.isArray(list) || !list.length) {
    throw new Error('未找到匹配的股票，请输入代码或更准确的名称');
  }
  const exact = list.find(item => (item.name || '') === identifier || (item.code || '') === identifier);
  return (exact || list[0]).code;
}

async function loadFlows() {
  try {
    const rows = await PortfolioApi.loadFlows();
    renderFlows(Array.isArray(rows) ? rows : []);
  } catch (e) {
    showToast('加载资金流水失败', 'error');
  }
}

async function loadTrades() {
  try {
    const rows = await PortfolioApi.loadTrades();
    resetTradesPage();
    PortfolioState.trades.loaded = true;
    renderTrades(Array.isArray(rows) ? rows : []);
  } catch (e) {
    showToast('加载交易记录失败', 'error');
  }
}

async function toggleTradesPanel() {
  PortfolioState.trades.collapsed = !PortfolioState.trades.collapsed;
  const content = document.getElementById('tradesContent');
  const toggleBtn = document.getElementById('tradesToggleBtn');
  const refreshBtn = document.getElementById('tradesRefreshBtn');
  if (content) content.style.display = PortfolioState.trades.collapsed ? 'none' : 'block';
  if (toggleBtn) toggleBtn.textContent = PortfolioState.trades.collapsed ? '展开' : '收起';
  if (refreshBtn) refreshBtn.style.display = PortfolioState.trades.collapsed ? 'none' : '';
  if (!PortfolioState.trades.collapsed && !PortfolioState.trades.loaded) {
    await loadTrades();
  }
}

async function loadActions() {
  try {
    const rows = await PortfolioApi.loadActions();
    renderActions(Array.isArray(rows) ? rows : []);
  } catch (e) {
    showToast('加载权益记录失败', 'error');
  }
}
