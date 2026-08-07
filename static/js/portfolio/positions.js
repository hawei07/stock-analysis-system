async function loadPortfolio() {
  try {
    const data = await PortfolioApi.loadPortfolio();
    if (data.error) throw new Error(data.error || '加载失败');
    setPortfolioData(data);
    renderSummary(data.summary);
    renderPositions(data.positions || []);
  } catch (e) {
    showToast(e.message || '加载持仓失败', 'error');
  }
}

function isAshareTradingTime(date = new Date()) {
  const day = date.getDay();
  if (day === 0 || day === 6) return false;
  const minutes = date.getHours() * 60 + date.getMinutes();
  return (minutes >= 9 * 60 + 30 && minutes < 11 * 60 + 30) || (minutes >= 13 * 60 && minutes < 15 * 60);
}

function shouldAutoRefreshPortfolioPrices() {
  return !document.hidden && isAshareTradingTime(new Date()) && Array.isArray(PortfolioState.portfolioData.positions);
}

async function refreshPortfolioPricesIfNeeded(force = false) {
  if (!force && !shouldAutoRefreshPortfolioPrices()) return false;
  if (PortfolioState.autoRefresh.portfolioPricesInFlight) return false;
  PortfolioState.autoRefresh.portfolioPricesInFlight = true;
  try {
    await loadPortfolio();
    return true;
  } finally {
    PortfolioState.autoRefresh.portfolioPricesInFlight = false;
  }
}

function startPortfolioPriceAutoRefresh() {
  if (PortfolioState.autoRefresh.portfolioPricesTimer) {
    clearInterval(PortfolioState.autoRefresh.portfolioPricesTimer);
  }
  PortfolioState.autoRefresh.portfolioPricesTimer = setInterval(() => {
    refreshPortfolioPricesIfNeeded(false);
  }, 10000);

  if (!PortfolioState.autoRefresh.portfolioPricesListenerBound) {
    PortfolioState.autoRefresh.portfolioPricesListenerBound = true;
    document.addEventListener('visibilitychange', () => {
      if (shouldAutoRefreshPortfolioPrices()) {
        refreshPortfolioPricesIfNeeded(true);
      }
    });
  }

  refreshPortfolioPricesIfNeeded(false);
}

function renderSummary(summary) {
  const total = Number(summary.total_market_value || 0);
  const cash = Number(summary.cash_amount || 0);
  const totalAsset = Number(summary.total_asset_value || (total + cash));
  const dividend = Number(summary.expected_dividend || 0);
  document.getElementById('totalAssetValue').textContent = privateMoney(totalAsset);
  document.getElementById('totalValue').textContent = privateMoney(total);
  document.getElementById('cashAmount').textContent = privateMoney(cash);
  document.getElementById('cashPct').textContent = '占比 ' + (totalAsset > 0 ? (cash / totalAsset * 100).toFixed(2) + '%' : '--');
  const hkdRate = summary.exchange_rates?.HKD_CNY;
  document.getElementById('totalValueSub').textContent = hkdRate?.rate
    ? `统一折算为人民币；HKD→CNY ${Number(hkdRate.rate).toFixed(4)}（${hkdRate.date || '最新'}）`
    : '统一折算为人民币，取不到价格时不计入';
  const profit = summary.unrealized_profit;
  const profitPct = summary.unrealized_profit_pct;
  const profitEl = document.getElementById('portfolioProfit');
  profitEl.textContent = signedPrivateMoney(profit);
  profitEl.className = 'value ' + profitClass(profit);
  document.getElementById('portfolioProfitPct').textContent = profitPct == null ? '按交易自动计算' : `${Number(profitPct).toFixed(2)}% · 成本 ${privateMoney(summary.total_cost_value)}`;
  const dayChange = summary.day_change_value;
  const dayChangeEl = document.getElementById('portfolioDayChange');
  if (dayChangeEl) {
    dayChangeEl.textContent = signedPrivateMoney(dayChange);
    dayChangeEl.className = 'value ' + profitClass(dayChange);
  }
  const dayChangePctEl = document.getElementById('portfolioDayChangePct');
  if (dayChangePctEl) {
    dayChangePctEl.textContent = summary.day_change_pct == null ? '按实时涨跌估算' : `${Number(summary.day_change_pct).toFixed(2)}%`;
  }
  document.getElementById('expectedDividend').textContent = money(dividend);
  document.getElementById('portfolioYield').textContent = total > 0 ? (dividend / total * 100).toFixed(2) + '%' : '--';
  document.getElementById('positionCount').textContent = summary.count || 0;
}

function sortedPositions(rows) {
  const result = [...(Array.isArray(rows) ? rows : [])];
  const dir = PortfolioState.positions.sortDir === 'asc' ? 1 : -1;
  result.sort((a, b) => {
    const av = Number(a?.[PortfolioState.positions.sortKey]);
    const bv = Number(b?.[PortfolioState.positions.sortKey]);
    const an = Number.isFinite(av) ? av : (PortfolioState.positions.sortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY);
    const bn = Number.isFinite(bv) ? bv : (PortfolioState.positions.sortDir === 'asc' ? Number.POSITIVE_INFINITY : Number.NEGATIVE_INFINITY);
    if (an === bn) return String(a.code || '').localeCompare(String(b.code || ''));
    return (an - bn) * dir;
  });
  return result;
}

function refreshPositionSortIcons() {
  document.querySelectorAll('[data-sort-icon]').forEach(el => {
    const key = el.getAttribute('data-sort-icon');
    el.textContent = key === PortfolioState.positions.sortKey ? (PortfolioState.positions.sortDir === 'asc' ? '↑' : '↓') : '';
  });
}

function setPositionSort(key) {
  if (PortfolioState.positions.sortKey === key) {
    PortfolioState.positions.sortDir = PortfolioState.positions.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    PortfolioState.positions.sortKey = key;
    PortfolioState.positions.sortDir = 'desc';
  }
  localStorage.setItem('portfolioPositionSortKey', PortfolioState.positions.sortKey);
  localStorage.setItem('portfolioPositionSortDir', PortfolioState.positions.sortDir);
  renderPositions(PortfolioState.portfolioData.positions || []);
}

function renderPositions(rows) {
  const body = document.getElementById('positionsBody');
  document.getElementById('positionsEmpty').style.display = rows.length ? 'none' : 'block';
  refreshPositionSortIcons();
  body.innerHTML = sortedPositions(rows).map(r => `
    <tr>
      <td><span class="code">${esc(r.code)}</span></td>
      <td><a class="name-link" href="/stock/${esc(r.code)}">${esc(r.name)}</a></td>
      <td class="num">${plain(r.shares)}</td>
      <td class="num">${r.cost_price == null ? '--' : plain(r.cost_price)} ${r.cost_price_currency || ''}</td>
      <td class="num">${money(r.price)} ${r.price_currency || ''}</td>
      <td class="num ${profitClass(r.day_change_value)}">
        ${signedPrivateMoney(r.day_change_value)}
        <div class="dividend-meta">${r.day_change_pct == null ? '--' : (Number(r.day_change_pct) > 0 ? '+' : '') + Number(r.day_change_pct).toFixed(2) + '%'}</div>
      </td>
      <td class="num">
        ${money(r.market_value)} CNY
        ${r.original_market_value_currency && r.original_market_value_currency !== 'CNY'
          ? `<div class="dividend-meta">${money(r.original_market_value)} ${r.original_market_value_currency} × ${r.fx_rate_to_cny == null ? '--' : Number(r.fx_rate_to_cny).toFixed(4)}</div>`
          : ''}
      </td>
      <td class="num ${profitClass(r.unrealized_profit)}">
        ${signedPrivateMoney(r.unrealized_profit)}
        <div class="dividend-meta">${r.unrealized_profit_pct == null ? '--' : (Number(r.unrealized_profit_pct) > 0 ? '+' : '') + Number(r.unrealized_profit_pct).toFixed(2) + '%'}</div>
      </td>
      <td class="num">${r.allocation_pct == null ? '--' : Number(r.allocation_pct).toFixed(2) + '%'}</td>
      <td class="num">
        <div class="dividend-cell">
          <input class="dividend-input" id="dividendInput-${esc(r.code)}" type="number" min="0" step="0.01" value="${r.dividend_per_share == null ? '' : Number(r.dividend_per_share).toFixed(2)}">
          <button class="btn btn-outline btn-sm" onclick="saveCustomDividend('${esc(r.code)}')">保存</button>
          <button class="btn btn-outline btn-sm" onclick="resetDividendAuto('${esc(r.code)}')">重置</button>
        </div>
        <div class="dividend-meta">
          ${r.dividend_source === 'custom' ? '自定义' : '自动'} · 最新历史分红 ${r.auto_dividend_per_share == null ? '--' : dividendHistoryMoney(r.auto_dividend_per_share)}
        </div>
      </td>
      <td class="num">${money(r.expected_dividend)}</td>
      <td>
        <button class="btn btn-outline btn-sm trade-action-buy" onclick="openTradeModal('${esc(r.code)}', 'buy')">买入</button>
        <button class="btn btn-outline btn-sm trade-action-sell" onclick="openTradeModal('${esc(r.code)}', 'sell')">卖出</button>
        <button class="btn btn-outline btn-sm" onclick="openActionModal('${esc(r.code)}')">分红</button>
      </td>
    </tr>
  `).join('');
}
