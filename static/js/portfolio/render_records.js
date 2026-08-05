function renderTrades(rows) {
  const body = document.getElementById('tradesBody');
  const empty = document.getElementById('tradesEmpty');
  const totalEl = document.getElementById('tradesTotal');
  const pagination = document.getElementById('tradesPagination');
  if (!body || !empty || !totalEl || !pagination) return;
  setTradesRows(rows);
  const totalPages = Math.max(1, Math.ceil(PortfolioState.trades.rows.length / PortfolioState.trades.pageSize));
  if (PortfolioState.trades.page > totalPages) PortfolioState.trades.page = totalPages;
  const start = (PortfolioState.trades.page - 1) * PortfolioState.trades.pageSize;
  const pageRows = PortfolioState.trades.rows.slice(start, start + PortfolioState.trades.pageSize);
  empty.style.display = PortfolioState.trades.rows.length ? 'none' : 'block';
  body.innerHTML = pageRows.map(r => {
    const isBuy = r.trade_type === 'buy';
    const typeText = isBuy ? '买入' : '卖出';
    const typeClass = isBuy ? 'trade-buy' : 'trade-sell';
    const voidBadge = r.is_void ? '<span class="void-badge">已作废</span>' : '';
    return `<tr class="${r.is_void ? 'void-row' : ''}">
      <td>${esc(r.trade_date)}</td>
      <td><span class="${typeClass}">${typeText}</span>${voidBadge}</td>
      <td><span class="code">${esc(r.stock_code)}</span></td>
      <td><a class="name-link" href="/stock/${esc(r.stock_code)}">${esc(r.name)}</a></td>
      <td class="num">${plain(r.shares)}</td>
      <td class="num">${price2(r.price) || '--'} ${r.currency || ''}</td>
      <td class="num">${money(r.amount)} ${r.currency || ''}</td>
      <td class="num">
        ${money(r.total_fee)} ${r.currency || ''}
        <div class="dividend-meta">佣 ${money(r.commission)} / 印 ${money(r.stamp_tax)} / 过 ${money(r.transfer_fee)}</div>
      </td>
      <td class="num ${Number(r.cash_delta) >= 0 ? 'flow-in' : 'flow-out'}">${signedPrivateMoney(r.cash_delta)} ${r.currency || ''}</td>
      <td class="num">${plain(r.shares_after)}</td>
      <td class="num">${r.cost_price_after == null ? '--' : plain(r.cost_price_after)} ${r.currency || ''}</td>
      <td class="num ${profitClass(r.realized_profit)}">${signedPrivateMoney(r.realized_profit)}</td>
      <td>${esc(r.note || '')}${r.void_note ? `<div class="dividend-meta">作废原因：${esc(r.void_note)}</div>` : ''}</td>
      <td>${r.is_void ? '--' : `<button class="btn btn-danger btn-sm" onclick="voidTrade(${r.id})">作废</button>`}</td>
    </tr>`;
  }).join('');
  totalEl.textContent = '共 ' + PortfolioState.trades.rows.length + ' 条';
  pagination.innerHTML = renderTradesPagination(totalPages);
}

function renderTradesPagination(totalPages) {
  const disabledPrev = PortfolioState.trades.page <= 1 ? ' disabled' : '';
  const disabledNext = PortfolioState.trades.page >= totalPages ? ' disabled' : '';
  const pages = [];
  const start = Math.max(1, PortfolioState.trades.page - 2);
  const end = Math.min(totalPages, PortfolioState.trades.page + 2);
  for (let page = start; page <= end; page++) {
    pages.push(`<button class="page-btn${page === PortfolioState.trades.page ? ' active' : ''}" type="button" onclick="setTradesPage(${page})">${page}</button>`);
  }
  return `
    <button class="page-btn"${disabledPrev} type="button" onclick="setTradesPage(${PortfolioState.trades.page - 1})">上一页</button>
    ${start > 1 ? '<span class="page-ellipsis">...</span>' : ''}
    ${pages.join('')}
    ${end < totalPages ? '<span class="page-ellipsis">...</span>' : ''}
    <button class="page-btn"${disabledNext} type="button" onclick="setTradesPage(${PortfolioState.trades.page + 1})">下一页</button>
  `;
}

function setTradesPage(page) {
  const totalPages = Math.max(1, Math.ceil(PortfolioState.trades.rows.length / PortfolioState.trades.pageSize));
  PortfolioState.trades.page = Math.min(Math.max(1, Number(page) || 1), totalPages);
  renderTrades(PortfolioState.trades.rows);
}

function renderActions(rows) {
  const body = document.getElementById('actionsBody');
  const empty = document.getElementById('actionsEmpty');
  if (!body || !empty) return;
  const typeMap = {cash_dividend: '现金分红', bonus_share: '送股/转增', rights_issue: '配股'};
  empty.style.display = rows.length ? 'none' : 'block';
  body.innerHTML = rows.map(r => {
    const cashDelta = Number(r.cash_delta || 0);
    const voidBadge = r.is_void ? '<span class="void-badge">已作废</span>' : '';
    return `<tr class="${r.is_void ? 'void-row' : ''}">
      <td>${esc(r.action_date)}</td>
      <td>${typeMap[r.action_type] || esc(r.action_type)}${voidBadge}</td>
      <td><span class="code">${esc(r.stock_code)}</span></td>
      <td><a class="name-link" href="/stock/${esc(r.stock_code)}">${esc(r.name)}</a></td>
      <td class="num">${money(r.cash_amount)} ${r.currency || ''}</td>
      <td class="num">${plain(r.shares)}</td>
      <td class="num">${r.price == null ? '--' : price2(r.price)} ${r.currency || ''}</td>
      <td class="num ${cashDelta >= 0 ? 'flow-in' : 'flow-out'}">${signedPrivateMoney(cashDelta)} ${r.currency || ''}</td>
      <td class="num">${plain(r.shares_after)}</td>
      <td class="num">${r.cost_price_after == null ? '--' : plain(r.cost_price_after)} ${r.currency || ''}</td>
      <td>${esc(r.note || '')}${r.void_note ? `<div class="dividend-meta">作废原因：${esc(r.void_note)}</div>` : ''}</td>
      <td>${r.is_void ? '--' : `<button class="btn btn-danger btn-sm" onclick="voidAction(${r.id})">作废</button>`}</td>
    </tr>`;
  }).join('');
}
