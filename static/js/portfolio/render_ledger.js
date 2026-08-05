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
