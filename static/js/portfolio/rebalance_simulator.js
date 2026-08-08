const REBALANCE_RATIO_MAX = 100;

function rebalanceRoundCents(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round((number + Number.EPSILON) * 100) / 100 : 0;
}

function rebalanceFinite(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

function rebalanceClamp(value, min = 0, max = REBALANCE_RATIO_MAX) {
  return Math.min(max, Math.max(min, rebalanceFinite(value, min)));
}

function rebalanceTargetInputId(code, suffix = '') {
  const safeCode = String(code || '').replace(/[^A-Za-z0-9_-]/g, '_');
  return `rebalanceTarget${safeCode}${suffix}`;
}

function rebalancePriceCny(row) {
  const price = rebalanceFinite(row.price, 0);
  if (price <= 0) return null;
  const currency = String(row.price_currency || '').toUpperCase();
  const fx = currency === 'CNY' ? 1 : rebalanceFinite(row.fx_rate_to_cny, 0);
  return fx > 0 ? price * fx : null;
}

function rebalanceCurrentRatio(value, totalAsset) {
  return totalAsset > 0 && value >= 0 ? value / totalAsset * 100 : 0;
}

function rebalanceRowsFromData(data) {
  const summary = data?.summary || {};
  const totalAsset = rebalanceFinite(
    summary.total_asset_value,
    rebalanceFinite(summary.total_market_value) + rebalanceFinite(summary.cash_amount)
  );
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const rows = positions
    .filter(position => rebalanceFinite(position.shares) > 0 || rebalanceFinite(position.market_value) > 0)
    .map(position => {
      const currentValue = rebalanceFinite(position.market_value, 0);
      const shares = rebalanceFinite(position.shares, 0);
      const priceCny = rebalancePriceCny(position);
      return {
        ...position,
        code: String(position.code || ''),
        currentValue,
        shares,
        priceCny,
        currentRatio: rebalanceCurrentRatio(currentValue, totalAsset),
        canTrade: priceCny != null && shares >= 0,
      };
    });
  return {
    rows,
    totalAsset,
    currentCash: rebalanceFinite(summary.cash_amount, 0),
  };
}

function rebalanceStockTargetSum() {
  const state = PortfolioState.rebalance;
  return state.rows.reduce((sum, row) => sum + rebalanceFinite(state.targetRatios[row.code], row.currentRatio), 0);
}

function rebalanceCashTargetRatio() {
  return rebalanceClamp(REBALANCE_RATIO_MAX - rebalanceStockTargetSum());
}

function initializeRebalanceTargets(rows) {
  const state = PortfolioState.rebalance;
  state.targetRatios = {};
  rows.forEach(row => {
    state.targetRatios[row.code] = row.currentRatio;
  });
  state.userAdjusted = false;
}

function updateRebalanceRows(data, resetTargets = false) {
  const state = PortfolioState.rebalance;
  const next = rebalanceRowsFromData(data);
  const previousTargets = {...state.targetRatios};
  state.rows = next.rows;
  state.totalAsset = next.totalAsset;
  state.currentCash = next.currentCash;
  if (resetTargets || !state.initialized || !state.userAdjusted) {
    initializeRebalanceTargets(next.rows);
  } else {
    state.targetRatios = {};
    next.rows.forEach(row => {
      state.targetRatios[row.code] = previousTargets[row.code] == null
        ? row.currentRatio
        : rebalanceClamp(previousTargets[row.code]);
    });
    const targetSum = rebalanceStockTargetSum();
    if (targetSum > REBALANCE_RATIO_MAX) {
      const scale = REBALANCE_RATIO_MAX / targetSum;
      next.rows.forEach(row => {
        state.targetRatios[row.code] = Number((state.targetRatios[row.code] * scale).toFixed(2));
      });
    }
  }
  state.initialized = true;
}

function rebalanceTradeFee(amountCny, tradeType, row) {
  const estimate = calculateTradeFeeEstimate(
    amountCny,
    tradeType,
    inferDomesticMarket(row.code, row)
  );
  const commission = rebalanceRoundCents(estimate.commission);
  const stampTax = rebalanceRoundCents(estimate.stamp_tax);
  const transferFee = rebalanceRoundCents(estimate.transfer_fee);
  const totalFee = rebalanceRoundCents(commission + stampTax + transferFee);
  const cashDelta = tradeType === 'buy'
    ? -(amountCny + totalFee)
    : amountCny - totalFee;
  return {
    commission,
    stamp_tax: stampTax,
    transfer_fee: transferFee,
    total_fee: totalFee,
    cash_delta: rebalanceRoundCents(cashDelta),
  };
}

function calculateRebalanceSimulation() {
  const state = PortfolioState.rebalance;
  const totalAsset = state.totalAsset;
  let stockTargetValue = 0;
  let totalCashDelta = 0;
  let totalTradeValue = 0;
  let totalFees = 0;
  let buyCount = 0;
  let sellCount = 0;

  const rows = state.rows.map(row => {
    const targetRatio = rebalanceClamp(state.targetRatios[row.code], 0, REBALANCE_RATIO_MAX);
    const targetValue = totalAsset * targetRatio / 100;
    stockTargetValue += targetValue;
    const deltaValue = targetValue - row.currentValue;
    let exactDeltaShares = null;
    let tradeShares = 0;
    let tradeType = '';
    let tradeValue = 0;
    let fee = {commission: 0, stamp_tax: 0, transfer_fee: 0, total_fee: 0, cash_delta: 0};

    if (row.canTrade && row.priceCny > 0) {
      exactDeltaShares = deltaValue / row.priceCny;
      tradeShares = Math.round(exactDeltaShares);
      if (tradeShares < 0) tradeShares = -Math.min(Math.abs(tradeShares), Math.round(row.shares));
      if (tradeShares > 0) {
        tradeType = 'buy';
        buyCount += 1;
      } else if (tradeShares < 0) {
        tradeType = 'sell';
        sellCount += 1;
      }
      if (tradeShares !== 0) {
        tradeValue = rebalanceRoundCents(Math.abs(tradeShares) * row.priceCny);
        fee = rebalanceTradeFee(tradeValue, tradeType, row);
        totalTradeValue += tradeValue;
        totalFees += fee.total_fee;
        totalCashDelta += fee.cash_delta;
      }
    }

    const postShares = row.shares + tradeShares;
    const postMarketValue = row.canTrade && row.priceCny > 0
      ? rebalanceRoundCents(postShares * row.priceCny)
      : row.currentValue;
    return {
      ...row,
      targetRatio,
      targetValue,
      deltaValue,
      exactDeltaShares,
      tradeShares,
      tradeType,
      tradeValue,
      fee,
      postShares,
      postMarketValue,
      roundingGap: postMarketValue - targetValue,
    };
  });

  const cashTargetRatio = rebalanceClamp(REBALANCE_RATIO_MAX - stockTargetValue / totalAsset * 100);
  const cashTargetValue = totalAsset * cashTargetRatio / 100;
  const postCash = rebalanceRoundCents(state.currentCash + totalCashDelta);
  const postStockValue = rows.reduce((sum, row) => sum + row.postMarketValue, 0);
  const postTotalAsset = rebalanceRoundCents(postCash + postStockValue);
  const cashGap = rebalanceRoundCents(postCash - cashTargetValue);

  return {
    rows,
    cashTargetRatio,
    cashTargetValue,
    totalCashDelta: rebalanceRoundCents(totalCashDelta),
    totalTradeValue: rebalanceRoundCents(totalTradeValue),
    totalFees: rebalanceRoundCents(totalFees),
    postCash,
    postStockValue: rebalanceRoundCents(postStockValue),
    postTotalAsset,
    cashGap,
    buyCount,
    sellCount,
  };
}

function rebalanceCell(rowElement, name) {
  return rowElement?.querySelector(`[data-rebalance-cell="${name}"]`);
}

function setRebalanceCell(rowElement, name, value, className = '') {
  const cell = rebalanceCell(rowElement, name);
  if (!cell) return;
  cell.textContent = value;
  cell.className = `num ${className}`.trim();
}

function rebalanceActionLabel(result) {
  if (result.tradeType === 'buy') return '买入';
  if (result.tradeType === 'sell') return '卖出';
  return result.canTrade ? '无需交易' : '缺少股价';
}

function renderRebalanceResults() {
  const state = PortfolioState.rebalance;
  const result = calculateRebalanceSimulation();
  const totalAssetEl = document.getElementById('rebalanceTotalAsset');
  const currentCashEl = document.getElementById('rebalanceCurrentCash');
  const targetCashEl = document.getElementById('rebalanceTargetCash');
  const postCashEl = document.getElementById('rebalancePostCash');
  const cashDeltaEl = document.getElementById('rebalanceCashDelta');
  const feeEl = document.getElementById('rebalanceFeeTotal');
  const postAssetEl = document.getElementById('rebalancePostAsset');
  if (totalAssetEl) totalAssetEl.textContent = privateMoney(state.totalAsset);
  if (currentCashEl) currentCashEl.textContent = privateMoney(state.currentCash);
  if (targetCashEl) targetCashEl.textContent = `${privateMoney(result.cashTargetValue)} (${result.cashTargetRatio.toFixed(2)}%)`;
  if (postCashEl) postCashEl.textContent = privateMoney(result.postCash);
  if (cashDeltaEl) {
    cashDeltaEl.textContent = signedPrivateMoney(result.totalCashDelta);
    cashDeltaEl.className = `rebalance-metric-value ${profitClass(result.totalCashDelta)}`.trim();
  }
  if (feeEl) feeEl.textContent = privateMoney(result.totalFees);
  if (postAssetEl) postAssetEl.textContent = privateMoney(result.postTotalAsset);

  result.rows.forEach(row => {
    const rowElement = document.querySelector(`.rebalance-row[data-rebalance-code="${row.code}"]`);
    if (!rowElement) return;
    const rangeInput = rowElement.querySelector('[data-rebalance-target-range]');
    const numberInput = rowElement.querySelector('[data-rebalance-target-number]');
    if (rangeInput && document.activeElement !== rangeInput) rangeInput.value = row.targetRatio;
    if (numberInput && document.activeElement !== numberInput) numberInput.value = row.targetRatio.toFixed(2);
    setRebalanceCell(rowElement, 'currentValue', privateMoney(row.currentValue));
    setRebalanceCell(rowElement, 'currentShares', plain(row.shares));
    setRebalanceCell(rowElement, 'currentRatio', `${row.currentRatio.toFixed(2)}%`);
    setRebalanceCell(rowElement, 'targetValue', privateMoney(row.targetValue));
    setRebalanceCell(rowElement, 'tradeShares', row.tradeShares === 0 ? '--' : `${row.tradeShares > 0 ? '+' : ''}${plain(row.tradeShares)} 股`, profitClass(row.tradeShares));
    const actionCell = rebalanceCell(rowElement, 'action');
    if (actionCell) {
      actionCell.textContent = rebalanceActionLabel(row);
      actionCell.className = `rebalance-action ${row.tradeType === 'buy' ? 'buy' : row.tradeType === 'sell' ? 'sell' : ''}`.trim();
    }
    setRebalanceCell(rowElement, 'cashDelta', row.tradeShares === 0 ? '--' : signedPrivateMoney(row.fee.cash_delta), profitClass(row.fee.cash_delta));
    const priceCell = rebalanceCell(rowElement, 'price');
    if (priceCell) priceCell.textContent = row.price == null ? '--' : `${money(row.price)} ${row.price_currency || ''}`;
    const note = rowElement.querySelector('[data-rebalance-note]');
    if (note) {
      note.textContent = row.canTrade
        ? `按 ${row.price_currency || 'CNY'} 最新价估算${row.quote_date ? ` · 行情 ${String(row.quote_date).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')}` : ''}`
        : '暂无可用最新股价，暂不能估算';
    }
  });

  setRebalanceCell(document.querySelector('.rebalance-cash-row'), 'currentValue', privateMoney(state.currentCash));
  setRebalanceCell(document.querySelector('.rebalance-cash-row'), 'currentRatio', `${rebalanceCurrentRatio(state.currentCash, state.totalAsset).toFixed(2)}%`);
  setRebalanceCell(document.querySelector('.rebalance-cash-row'), 'targetValue', privateMoney(result.cashTargetValue));
  setRebalanceCell(document.querySelector('.rebalance-cash-row'), 'tradeShares', '--');
  const cashAction = rebalanceCell(document.querySelector('.rebalance-cash-row'), 'action');
  if (cashAction) {
    cashAction.textContent = '自动平衡';
    cashAction.className = 'rebalance-action';
  }
  setRebalanceCell(document.querySelector('.rebalance-cash-row'), 'cashDelta', signedPrivateMoney(result.totalCashDelta), profitClass(result.totalCashDelta));
  const cashTargetHint = document.querySelector('[data-rebalance-cash-target-hint]');
  if (cashTargetHint) cashTargetHint.textContent = `目标比例 ${result.cashTargetRatio.toFixed(2)}%`;

  const summaryEl = document.getElementById('rebalanceTradeSummary');
  if (summaryEl) {
    summaryEl.textContent = result.buyCount || result.sellCount
      ? `预计买入 ${result.buyCount} 只、卖出 ${result.sellCount} 只；交易金额 ${privateMoney(result.totalTradeValue)}`
      : '当前目标比例与持仓比例一致，无需交易';
  }
  const warningEl = document.getElementById('rebalanceWarning');
  if (warningEl) {
    const unavailable = result.rows.filter(row => !row.canTrade);
    const messages = [];
    if (result.postCash < -0.005) messages.push('模拟后现金为负，当前现金不足以完成这组调仓目标');
    if (unavailable.length) messages.push(`${unavailable.map(row => row.name || row.code).join('、')} 缺少最新股价，未计入交易估算`);
    if (Math.abs(result.cashGap) >= 0.01) messages.push(`股数取整及交易费用造成现金偏差 ${signedPrivateMoney(result.cashGap)}`);
    warningEl.textContent = messages.join('；');
    warningEl.className = messages.length ? 'rebalance-warning' : 'rebalance-warning is-hidden';
  }
}

function renderRebalanceTable() {
  const state = PortfolioState.rebalance;
  const content = document.getElementById('rebalanceSimulatorContent');
  if (!content) return;
  if (state.totalAsset <= 0 && !state.rows.length && state.currentCash <= 0) {
    content.innerHTML = '<div class="empty">暂无可模拟的持仓或现金。</div>';
    return;
  }

  const rowsHtml = state.rows.map(row => {
    const id = rebalanceTargetInputId(row.code);
    const targetRatio = rebalanceFinite(state.targetRatios[row.code], row.currentRatio);
    return `<tr class="rebalance-row" data-rebalance-code="${esc(row.code)}">
      <td>
        <div class="rebalance-asset-name">${esc(row.name || row.code)}</div>
        <div class="rebalance-asset-code">${esc(row.code)}</div>
        <div class="rebalance-asset-note" data-rebalance-note></div>
      </td>
      <td class="num" data-rebalance-cell="currentValue">--</td>
      <td class="num" data-rebalance-cell="currentShares">--</td>
      <td class="num" data-rebalance-cell="currentRatio">--</td>
      <td class="rebalance-target-control">
        <div class="rebalance-target-inputs">
          <input id="${id}Range" data-rebalance-target-range type="range" min="0" max="100" step="0.1" value="${targetRatio.toFixed(1)}" oninput="setRebalanceTarget('${esc(row.code)}', this.value)" ${row.canTrade ? '' : 'disabled'}>
          <div class="rebalance-target-number-wrap">
            <input id="${id}Number" data-rebalance-target-number class="rebalance-target-number" type="number" min="0" max="100" step="0.1" value="${targetRatio.toFixed(2)}" oninput="setRebalanceTarget('${esc(row.code)}', this.value)" ${row.canTrade ? '' : 'disabled'}>
            <span>%</span>
          </div>
        </div>
        <div class="rebalance-range-caption">拖动或输入目标比例</div>
      </td>
      <td class="num" data-rebalance-cell="targetValue">--</td>
      <td class="num" data-rebalance-cell="tradeShares">--</td>
      <td data-rebalance-cell="action">--</td>
      <td class="num" data-rebalance-cell="cashDelta">--</td>
    </tr>`;
  }).join('');

  content.innerHTML = `<div class="rebalance-overview">
    <div class="rebalance-metric"><span>当前总资产</span><strong id="rebalanceTotalAsset">--</strong></div>
    <div class="rebalance-metric"><span>当前现金</span><strong id="rebalanceCurrentCash">--</strong></div>
    <div class="rebalance-metric"><span>目标现金</span><strong id="rebalanceTargetCash">--</strong></div>
    <div class="rebalance-metric"><span>调仓后现金</span><strong id="rebalancePostCash">--</strong></div>
    <div class="rebalance-metric"><span>现金变化</span><strong class="rebalance-metric-value" id="rebalanceCashDelta">--</strong></div>
    <div class="rebalance-metric"><span>预计交易费用</span><strong id="rebalanceFeeTotal">--</strong></div>
    <div class="rebalance-metric"><span>模拟后总资产</span><strong id="rebalancePostAsset">--</strong></div>
  </div>
  <div class="rebalance-help">调整股票目标比例后，现金比例会自动补足到 100%。股价取当前最新行情，股数按 1 股取整，交易费用按当前配置估算；本弹窗只做模拟，不会修改真实持仓。</div>
  <div class="rebalance-status" id="rebalanceTradeSummary"></div>
  <div class="rebalance-warning is-hidden" id="rebalanceWarning"></div>
  <div class="table-wrap rebalance-table-wrap">
    <table class="rebalance-table">
      <thead><tr>
        <th>资产</th>
        <th class="num">当前金额</th>
        <th class="num">当前股数</th>
        <th class="num">当前比例</th>
        <th>目标比例</th>
        <th class="num">目标金额</th>
        <th class="num">建议买卖股数</th>
        <th>动作</th>
        <th class="num">现金变化</th>
      </tr></thead>
      <tbody>
        ${rowsHtml}
        <tr class="rebalance-cash-row">
          <td><div class="rebalance-asset-name">现金</div><div class="rebalance-asset-note" data-rebalance-cash-target-hint></div></td>
          <td class="num" data-rebalance-cell="currentValue">--</td>
          <td class="num">--</td>
          <td class="num" data-rebalance-cell="currentRatio">--</td>
          <td><span class="rebalance-cash-auto">自动平衡</span></td>
          <td class="num" data-rebalance-cell="targetValue">--</td>
          <td class="num" data-rebalance-cell="tradeShares">--</td>
          <td data-rebalance-cell="action">自动平衡</td>
          <td class="num" data-rebalance-cell="cashDelta">--</td>
        </tr>
      </tbody>
    </table>
  </div>`;
  renderRebalanceResults();
}

function renderRebalanceSimulator(data) {
  updateRebalanceRows(data, false);
  renderRebalanceTable();
}

function rebalanceDomCodes() {
  return Array.from(document.querySelectorAll('.rebalance-row[data-rebalance-code]'))
    .map(row => row.dataset.rebalanceCode)
    .join('|');
}

function rebalanceStateCodes() {
  return PortfolioState.rebalance.rows.map(row => row.code).join('|');
}

function refreshRebalanceSimulator(data) {
  const state = PortfolioState.rebalance;
  if (!state.active) return;
  const previousCodes = rebalanceDomCodes();
  updateRebalanceRows(data, false);
  if (previousCodes !== rebalanceStateCodes()) {
    renderRebalanceTable();
  } else {
    renderRebalanceResults();
  }
}

function setRebalanceTarget(code, value) {
  const state = PortfolioState.rebalance;
  const row = state.rows.find(item => item.code === String(code));
  if (!row || !row.canTrade) return;
  const otherTargetSum = state.rows
    .filter(item => item.code !== row.code)
    .reduce((sum, item) => sum + rebalanceFinite(state.targetRatios[item.code], item.currentRatio), 0);
  const max = Math.max(0, REBALANCE_RATIO_MAX - otherTargetSum);
  const next = Number(rebalanceClamp(value, 0, max).toFixed(2));
  state.targetRatios[row.code] = next;
  state.userAdjusted = true;
  renderRebalanceResults();
}

function resetRebalanceTargets() {
  const state = PortfolioState.rebalance;
  state.rows.forEach(row => {
    state.targetRatios[row.code] = row.currentRatio;
  });
  state.userAdjusted = false;
  renderRebalanceResults();
}

async function openRebalanceSimulatorModal() {
  const overlay = document.getElementById('rebalanceModalOverlay');
  const content = document.getElementById('rebalanceSimulatorContent');
  if (!overlay || !content) return;
  const state = PortfolioState.rebalance;
  state.active = true;
  state.initialized = false;
  state.userAdjusted = false;
  state.targetRatios = {};
  overlay.classList.add('active');
  content.innerHTML = '<div class="empty">正在获取最新持仓和股价…</div>';
  try {
    const data = await loadPortfolio();
    if (!state.active) return;
    updateRebalanceRows(data, true);
    renderRebalanceTable();
  } catch (error) {
    if (state.active) content.innerHTML = `<div class="empty">调仓模拟器加载失败：${esc(error.message || '请稍后重试')}</div>`;
  }
}

function closeRebalanceSimulatorModal() {
  PortfolioState.rebalance.active = false;
  document.getElementById('rebalanceModalOverlay')?.classList.remove('active');
}
