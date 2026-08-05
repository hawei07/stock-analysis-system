function renderFlows(rows) {
  const body = document.getElementById('flowsBody');
  const empty = document.getElementById('flowsEmpty');
  if (!body) return;
  const table = body.closest('table');
  if (table) {
    table.querySelector('thead').innerHTML = '<tr><th>日期</th><th>类型</th><th class="num">金额</th><th>备注</th><th>操作</th></tr>';
  }
  empty.style.display = rows.length ? 'none' : 'block';
  body.innerHTML = rows.map(r => {
    const cls = Number(r.amount) >= 0 ? 'flow-in' : 'flow-out';
    const sign = Number(r.amount) >= 0 ? '+' : '';
    const isTrade = r.flow_source === 'trade';
    const isAction = r.flow_source === 'action';
    const typeText = isTrade
      ? (Number(r.amount) >= 0 ? '卖出到账' : '买入扣款')
      : isAction
        ? (Number(r.amount) >= 0 ? '分红到账' : '配股扣款')
        : (Number(r.amount) >= 0 ? '入金' : '出金');
    const voidBadge = r.is_void ? '<span class="void-badge">已作废</span>' : '';
    return `<tr class="${r.is_void ? 'void-row' : ''}">
      <td>${esc(r.flow_date)}</td>
      <td>${typeText}${voidBadge}</td>
      <td class="num ${cls}">${sign}${money(r.amount)}</td>
      <td>${esc(r.note || '')}${r.void_note ? `<div class="dividend-meta">作废原因：${esc(r.void_note)}</div>` : ''}</td>
      <td>${r.is_void || isTrade || isAction ? '--' : `<button class="btn btn-danger btn-sm" onclick="deleteFlow(${r.id})">作废</button>`}</td>
    </tr>`;
  }).join('');
}

async function saveFlow() {
  const flowDate = document.getElementById('flowDate').value;
  const type = document.getElementById('flowType').value;
  const rawAmount = Number(document.getElementById('flowAmount').value || 0);
  const amount = type === 'out' ? -Math.abs(rawAmount) : Math.abs(rawAmount);
  const note = document.getElementById('flowNote').value.trim();
  try {
    const data = await StockApi.postJson('/api/portfolio/flows', {flow_date: flowDate, amount, note});
    if (data.error) throw new Error(data.error || '保存失败');
    latestPortfolioData = data;
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
    const data = await StockApi.deleteJson('/api/portfolio/flows/' + id);
    if (data.error) throw new Error(data.error || '作废失败');
    latestPortfolioData = data;
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
  latestPortfolioData = data;
  if (data.fee_config) latestFeeConfig = data.fee_config;
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
    const data = await StockApi.postJson('/api/portfolio/trades/' + id + '/void', {void_note: note});
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
    const data = await StockApi.postJson('/api/portfolio/actions/' + id + '/void', {void_note: note});
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
    const data = await StockApi.getJson('/api/portfolio/audit');
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
    const data = await StockApi.postJson('/api/portfolio/rebuild');
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
    const data = await StockApi.putJson('/api/portfolio/positions/' + encodeURIComponent(code) + '/dividend', {dividend_per_share: value});
    if (data.error) throw new Error(data.error || '保存失败');
    latestPortfolioData = data;
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
    const data = await StockApi.postJson('/api/portfolio/positions/' + encodeURIComponent(code) + '/dividend/reset');
    if (data.error) throw new Error(data.error || '重置失败');
    latestPortfolioData = data;
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    await loadNav();
    const reset = data.reset_to ? `：${data.reset_to.fiscal_year} 年 ${dividendHistoryMoney(data.reset_to.dividend_per_share)}` : '';
    showToast('已重置为最新历史每股分红' + reset, 'success');
  } catch (e) {
    showToast(e.message || '重置失败', 'error');
  }
}
