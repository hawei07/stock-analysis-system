

async function saveFlow() {
  const flowDate = document.getElementById('flowDate').value;
  const type = document.getElementById('flowType').value;
  const rawAmount = Number(document.getElementById('flowAmount').value || 0);
  const amount = type === 'out' ? -Math.abs(rawAmount) : Math.abs(rawAmount);
  const note = document.getElementById('flowNote').value.trim();
  try {
    const data = await PortfolioApi.saveFlow({flow_date: flowDate, amount, note});
    if (data.error) throw new Error(data.error || '保存失败');
    setPortfolioData(data);
    document.getElementById('flowAmount').value = '';
    document.getElementById('flowNote').value = '';
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    renderFlows(data.flows || []);
    await loadNav();
    showToast('资金流水已保存，并记录今日快照', 'success');
  } catch (e) {
    showToast(e.message || '保存资金流水失败', 'error');
  }
}

async function deleteFlow(id) {
  if (!confirm('确定作废这笔资金流水吗？作废后会同步回滚现金。')) return;
  try {
    const data = await PortfolioApi.deleteFlow(id);
    if (data.error) throw new Error(data.error || '作废失败');
    setPortfolioData(data);
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    renderFlows(data.flows || []);
    await loadNav();
    showToast('资金流水已作废，并更新今日快照', 'success');
  } catch (e) {
    showToast(e.message || '作废资金流水失败', 'error');
  }
}

function applyPortfolioState(data) {
  setPortfolioData(data);
  renderSummary(data.summary || {});
  renderPositions(data.positions || []);
  if (data.trades) renderTrades(data.trades || []);
  if (data.actions) renderActions(data.actions || []);
  if (data.flows) renderFlows(data.flows || []);
}

async function voidTrade(id) {
  const note = prompt('作废原因', '录入错误') || '作废交易';
  if (!confirm('确定作废这笔交易吗？相关现金流水会一起作废，持仓成本会按账本重算。')) return;
  try {
    const data = await PortfolioApi.voidTrade(id, note);
    if (data.error) throw new Error(data.error || '作废交易失败');
    applyPortfolioState(data);
    await loadNav();
    showToast('交易已作废，账本已重算', 'success');
  } catch (e) {
    showToast(e.message || '作废交易失败', 'error');
  }
}

async function voidAction(id) {
  const note = prompt('作废原因', '录入错误') || '作废权益事件';
  if (!confirm('确定作废这笔权益记录吗？相关现金流水会一起作废，持仓成本会按账本重算。')) return;
  try {
    const data = await PortfolioApi.voidAction(id, note);
    if (data.error) throw new Error(data.error || '作废权益记录失败');
    applyPortfolioState(data);
    await loadNav();
    showToast('权益记录已作废，账本已重算', 'success');
  } catch (e) {
    showToast(e.message || '作废权益记录失败', 'error');
  }
}

async function runPortfolioAudit() {
  try {
    const data = await PortfolioApi.audit();
    if (data.error) throw new Error(data.error || '账本检查失败');
    if (data.ok) {
      showToast('账本一致：现金、流水、持仓都对得上', 'success');
      return;
    }
    const detail = (data.issues || []).slice(0, 6).map(item => item.message || item.code || item.type).join('\n');
    if (confirm(`发现 ${data.issues.length} 个账本不一致项：\n${detail}\n\n是否一键重算现金和持仓？`)) {
      await rebuildPortfolioLedger();
    }
  } catch (e) {
    showToast(e.message || '账本检查失败', 'error');
  }
}

async function rebuildPortfolioLedger() {
  try {
    const data = await PortfolioApi.rebuild();
    if (data.error) throw new Error(data.error || '账本重算失败');
    applyPortfolioState(data);
    await loadNav();
    const ok = data.audit?.ok;
    showToast(ok ? '账本已重算，当前一致' : '账本已重算，但仍有需要人工检查的记录', ok ? 'success' : 'error');
  } catch (e) {
    showToast(e.message || '账本重算失败', 'error');
  }
}

async function saveCustomDividend(code) {
  const input = document.getElementById('dividendInput-' + code);
  const rawValue = input ? input.value : '';
  const value = rawValue === '' ? '' : Number(rawValue).toFixed(2);
  try {
    const data = await PortfolioApi.saveDividend(code, value);
    if (data.error) throw new Error(data.error || '保存失败');
    setPortfolioData(data);
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    await loadNav();
    showToast('每股分红已保存', 'success');
  } catch (e) {
    showToast(e.message || '保存失败', 'error');
  }
}

async function resetDividendAuto(code) {
  try {
    const data = await PortfolioApi.resetDividend(code);
    if (data.error) throw new Error(data.error || '重置失败');
    setPortfolioData(data);
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    await loadNav();
    const reset = data.reset_to ? `：${data.reset_to.fiscal_year} 年 ${dividendHistoryMoney(data.reset_to.dividend_per_share)}` : '';
    showToast('已重置为最新历史每股分红' + reset, 'success');
  } catch (e) {
    showToast(e.message || '重置失败', 'error');
  }
}
