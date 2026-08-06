async function saveSnapshot() {
  try {
    const data = await PortfolioApi.saveSnapshot();
    if (data.error) throw new Error(data.error || '记录失败');
    setPortfolioData(data);
    renderSummary(data.summary);
    renderPositions(data.positions || []);
    await loadNav();
    showToast('今日净值已记录', 'success');
  } catch (e) {
    showToast(e.message || '记录失败', 'error');
  }
}

async function loadNav(live = false) {
  const rows = await PortfolioApi.loadNav(live);
  setNavHistoryRows(rows);
  renderNav(navHistoryChartRows());
  renderNavHistoryTable();
}

function renderNav(rows) {
  const el = document.getElementById('navChart');
  if (!PortfolioState.charts.nav) PortfolioState.charts.nav = echarts.init(el);
  updateNavPeriodChange(rows);

  if (!rows.length) {
    PortfolioState.charts.nav.setOption({
      title: {text: '暂无净值快照', left: 'center', top: 'center', textStyle: {fontSize: 14, color: '#999'}},
      xAxis: {show: false},
      yAxis: {show: false},
      series: []
    }, true);
    return;
  }

  const stockValues = rows.map(r => Number(r.stock_market_value || r.total_market_value || 0));
  const cashValues = rows.map(r => {
    const totalAsset = Number(r.total_asset_value || r.total_market_value || 0);
    const stockValue = Number(r.stock_market_value || r.total_market_value || 0);
    return Math.max(totalAsset - stockValue, 0);
  });

  PortfolioState.charts.nav.setOption({
    title: {show: false},
    tooltip: {
      trigger: 'axis',
      formatter(params) {
        const dataIndex = params[0]?.dataIndex ?? 0;
        const row = rows[dataIndex] || {};
        const totalAsset = Number(row.total_asset_value || row.total_market_value || 0);
        const stockValue = Number(row.stock_market_value || row.total_market_value || 0);
        const cashValue = Math.max(totalAsset - stockValue, 0);
        const netFlow = Number(row.net_flow || 0);
        const positionPct = totalAsset > 0 ? stockValue / totalAsset * 100 : null;
        const nav = row.nav_index == null ? '--' : Number(row.nav_index).toFixed(4);
        return `<strong>${esc(String(row.date || params[0]?.axisValue || ''))}</strong><br/>
          净值指数: ${nav}<br/>
          当日出入金: ${signedPrivateMoney(netFlow)}<br/>
          当日收益: ${signedPrivateMoney(row.daily_return)}<br/>
          累计收益: ${signedPrivateMoney(row.cumulative_return)}<br/>
          累计入金: ${money(row.cumulative_in)}<br/>
          累计出金: ${money(row.cumulative_out)}<br/>
          股票仓位: ${money(stockValue)}${positionPct == null ? '' : ' (' + positionPct.toFixed(2) + '%)'}<br/>
          现金/空仓: ${money(cashValue)}${positionPct == null ? '' : ' (' + (100 - positionPct).toFixed(2) + '%)'}<br/>
          总资产: ${money(totalAsset)}`;
      }
    },
    legend: {top: 36, data: ['净值指数', '股票仓位', '现金/空仓']},
    grid: {left: 56, right: 56, top: 82, bottom: 42},
    xAxis: {type: 'category', data: rows.map(r => r.date)},
    yAxis: [
      {type: 'value', name: '净值指数', min: value => Math.max(0, value.min * .98)},
      {type: 'value', name: '总资产', axisLabel: {formatter: v => Math.round(v / 10000) + '万'}}
    ],
    series: [
      {name: '净值指数', type: 'line', smooth: true, symbolSize: 7, data: rows.map(r => r.nav_index), connectNulls: true},
      {name: '股票仓位', type: 'bar', stack: 'asset', yAxisIndex: 1, data: stockValues, itemStyle: {color: '#5b8ff9'}},
      {name: '现金/空仓', type: 'bar', stack: 'asset', yAxisIndex: 1, data: cashValues, itemStyle: {color: '#c8d6e8'}}
    ]
  }, true);

  PortfolioState.charts.nav.setOption({
    yAxis: [
      {
        splitNumber: 4,
        splitLine: {show: true, lineStyle: {color: '#e6edf5'}}
      },
      {
        splitLine: {show: false}
      }
    ],
    series: [
      {},
      {
        barMaxWidth: 64,
        itemStyle: {borderRadius: [0, 0, 4, 4]}
      },
      {
        barMaxWidth: 64,
        itemStyle: {borderRadius: [4, 4, 0, 0]}
      }
    ]
  });
}

function updateNavPeriodChange(rows) {
  const valueEl = document.getElementById('navPeriodChangeValue');
  const rangeEl = document.getElementById('navPeriodChangeRange');
  if (!valueEl || !rangeEl) return;

  const navRows = rows.filter(r => r.nav_index != null && !Number.isNaN(Number(r.nav_index)));
  const firstNavRow = navRows[0];
  const lastNavRow = navRows[navRows.length - 1];
  const firstNav = firstNavRow ? Number(firstNavRow.nav_index) : null;
  const lastNav = lastNavRow ? Number(lastNavRow.nav_index) : null;
  const periodChangePct = firstNav && lastNav != null ? (lastNav / firstNav - 1) * 100 : null;

  valueEl.textContent = periodChangePct == null ? '区间涨跌幅：--' : '区间涨跌幅：' + signedPct(periodChangePct);
  valueEl.className = 'nav-period-change-value ' + profitClass(periodChangePct);
  rangeEl.textContent = rows[0]?.date && rows[rows.length - 1]?.date
    ? `${rows[0].date} 至 ${rows[rows.length - 1].date}`
    : '当前筛选区间';
}

function navPositionPct(row) {
  const totalAsset = Number(row.total_asset_value || row.total_market_value || 0);
  const stockMarketValue = Number(row.stock_market_value || row.total_market_value || 0);
  if (!totalAsset || totalAsset <= 0) return null;
  return stockMarketValue / totalAsset * 100;
}

function navHistoryRowsInRange() {
  const from = document.getElementById('navFromDate')?.value || '';
  const to = document.getElementById('navToDate')?.value || '';
  return PortfolioState.navHistory.rows
    .filter(row => {
      const date = String(row.date || '');
      if (from && date < from) return false;
      if (to && date > to) return false;
      return true;
    })
    .slice();
}

function navHistoryChartRows() {
  return navHistoryRowsInRange()
    .sort((a, b) => String(a.date || '').localeCompare(String(b.date || '')));
}

function navHistoryFilteredRows() {
  return navHistoryRowsInRange()
    .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')));
}

function renderNavHistoryTable() {
  const body = document.getElementById('navHistoryBody');
  const empty = document.getElementById('navHistoryEmpty');
  const totalEl = document.getElementById('navHistoryTotal');
  const pagination = document.getElementById('navHistoryPagination');
  if (!body || !empty || !totalEl || !pagination) return;

  const filtered = navHistoryFilteredRows();
  const totalPages = Math.max(1, Math.ceil(filtered.length / PortfolioState.navHistory.pageSize));
  if (PortfolioState.navHistory.page > totalPages) PortfolioState.navHistory.page = totalPages;
  const start = (PortfolioState.navHistory.page - 1) * PortfolioState.navHistory.pageSize;
  const pageRows = filtered.slice(start, start + PortfolioState.navHistory.pageSize);

  empty.style.display = filtered.length ? 'none' : 'block';
  body.innerHTML = pageRows.map(row => {
    const positionPct = navPositionPct(row);
    const totalValue = row.total_asset_value != null ? row.total_asset_value : row.total_market_value;
    const stockValue = row.stock_market_value != null ? row.stock_market_value : row.total_market_value;
    return `<tr>
      <td>${esc(String(row.date || ''))}</td>
      <td class="num">${row.nav_index == null ? '--' : Number(row.nav_index).toFixed(4)}</td>
      <td class="num ${profitClass(row.nav_change_pct)}">${signedPct(row.nav_change_pct)}</td>
      <td class="num">${money(totalValue)}</td>
      <td class="num">${money(stockValue)}</td>
      <td class="num">${money(row.cash_amount)}</td>
      <td class="num">${positionPct == null ? '--' : positionPct.toFixed(2) + '%'}</td>
      <td class="num ${profitClass(row.daily_return)}">${signedPrivateMoney(row.daily_return)}</td>
      <td class="num ${profitClass(row.cumulative_return)}">${signedPrivateMoney(row.cumulative_return)}</td>
      <td class="num flow-in">${money(row.cumulative_in)}</td>
      <td class="num flow-out">${money(row.cumulative_out)}</td>
    </tr>`;
  }).join('');

  totalEl.textContent = '共 ' + filtered.length + ' 条';
  pagination.innerHTML = renderNavHistoryPagination(totalPages);
}

function renderNavHistoryPagination(totalPages) {
  const disabledPrev = PortfolioState.navHistory.page <= 1 ? ' disabled' : '';
  const disabledNext = PortfolioState.navHistory.page >= totalPages ? ' disabled' : '';
  const pages = [];
  const start = Math.max(1, PortfolioState.navHistory.page - 2);
  const end = Math.min(totalPages, PortfolioState.navHistory.page + 2);
  for (let page = start; page <= end; page++) {
    pages.push(`<button class="page-btn${page === PortfolioState.navHistory.page ? ' active' : ''}" type="button" onclick="setNavHistoryPage(${page})">${page}</button>`);
  }
  return `
    <button class="page-btn"${disabledPrev} type="button" onclick="setNavHistoryPage(${PortfolioState.navHistory.page - 1})">上一页</button>
    ${start > 1 ? '<span class="page-ellipsis">...</span>' : ''}
    ${pages.join('')}
    ${end < totalPages ? '<span class="page-ellipsis">...</span>' : ''}
    <button class="page-btn"${disabledNext} type="button" onclick="setNavHistoryPage(${PortfolioState.navHistory.page + 1})">下一页</button>
  `;
}

function setNavHistoryPage(page) {
  const filtered = navHistoryFilteredRows();
  const totalPages = Math.max(1, Math.ceil(filtered.length / PortfolioState.navHistory.pageSize));
  PortfolioState.navHistory.page = Math.min(Math.max(1, Number(page) || 1), totalPages);
  renderNavHistoryTable();
}

function applyNavHistoryFilter() {
  PortfolioState.navHistory.page = 1;
  renderNav(navHistoryChartRows());
  renderNavHistoryTable();
}

function resetNavHistoryFilter() {
  const from = document.getElementById('navFromDate');
  const to = document.getElementById('navToDate');
  if (from) from.value = '';
  if (to) to.value = '';
  applyNavHistoryFilter();
}

function excelCell(value) {
  return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function exportNavHistoryExcel() {
  const rows = navHistoryFilteredRows();
  if (!rows.length) {
    showToast('没有可导出的净值明细', 'error');
    return;
  }
  const bodyRows = rows.map(row => {
    const positionPct = navPositionPct(row);
    const totalValue = row.total_asset_value != null ? row.total_asset_value : row.total_market_value;
    const stockValue = row.stock_market_value != null ? row.stock_market_value : row.total_market_value;
    return `<tr>
      <td>${excelCell(row.date)}</td>
      <td>${row.nav_index == null ? '' : Number(row.nav_index).toFixed(4)}</td>
      <td>${row.nav_change_pct == null ? '' : Number(row.nav_change_pct).toFixed(2) + '%'}</td>
      <td>${totalValue == null ? '' : Number(totalValue).toFixed(2)}</td>
      <td>${stockValue == null ? '' : Number(stockValue).toFixed(2)}</td>
      <td>${row.cash_amount == null ? '' : Number(row.cash_amount).toFixed(2)}</td>
      <td>${positionPct == null ? '' : positionPct.toFixed(2) + '%'}</td>
      <td>${row.daily_return == null ? '' : Number(row.daily_return).toFixed(2)}</td>
      <td>${row.cumulative_return == null ? '' : Number(row.cumulative_return).toFixed(2)}</td>
      <td>${row.cumulative_in == null ? '' : Number(row.cumulative_in).toFixed(2)}</td>
      <td>${row.cumulative_out == null ? '' : Number(row.cumulative_out).toFixed(2)}</td>
    </tr>`;
  }).join('');
  const html = `<!doctype html><html><head><meta charset="UTF-8"></head><body>
    <table border="1">
      <thead><tr><th>日期</th><th>净值</th><th>涨跌幅</th><th>总资产</th><th>持仓市值</th><th>现金</th><th>仓位</th><th>当日收益</th><th>累计收益</th><th>累计入金</th><th>累计出金</th></tr></thead>
      <tbody>${bodyRows}</tbody>
    </table>
  </body></html>`;
  const blob = new Blob([html], {type: 'application/vnd.ms-excel;charset=utf-8'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const from = document.getElementById('navFromDate')?.value || '全部';
  const to = document.getElementById('navToDate')?.value || '全部';
  a.href = url;
  a.download = `净值明细_${from}_${to}.xls`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  showToast('净值明细已导出', 'success');
}

window.addEventListener('resize', () => {
  PortfolioState.charts.nav && PortfolioState.charts.nav.resize();
  PortfolioState.charts.allocation && PortfolioState.charts.allocation.resize();
});

function showToast(text, type) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.className = 'toast toast-' + (type || 'success') + ' show';
  setTimeout(() => el.classList.remove('show'), 2600);
}
