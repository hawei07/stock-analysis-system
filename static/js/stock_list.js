function debounceSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { currentPage = 1; loadStocks(); }, 400);
}

async function loadStocks() {
  const keyword = document.getElementById('keyword').value.trim();
  const params = new URLSearchParams({ page: currentPage, page_size: listPageSize });
  if (keyword) params.append('keyword', keyword);
  if (currentSortBy && !reorderMode) {
    params.append('sort_by', currentSortBy);
    params.append('sort_dir', currentSortDir);
  }

  try {
    const res = await fetch('/api/stocks?' + params);
    const data = await res.json();
    renderTable(data.data);
    totalPages = data.total_pages;
    renderPagination(data);
    updateListControls();
    document.getElementById('emptyHint').style.display = data.total === 0 ? 'block' : 'none';
    scheduleStockPriceAutoRefresh();
    refreshVisibleStockYtd();
  } catch (e) {
    showToast('加载失败', 'error');
  }
}

function renderTable(stocks) {
  const tbody = document.getElementById('stockTableBody');
  const fmtNum = v => (v == null || Number.isNaN(Number(v))) ? '-' : Number(v).toFixed(2);
  const fmtPct = formatRealtimePct;
  tbody.innerHTML = stocks.map(s => `
    <tr data-code="${esc(s.code)}" draggable="${reorderMode ? 'true' : 'false'}">
      <td><span class="code">${esc(s.code)}</span></td>
      <td><span class="drag-handle">::</span><a class="name-link" onclick="navigateTo('/stock/${esc(s.code)}');return false" href="/stock/${esc(s.code)}">${esc(s.name)}</a></td>
      <td data-col="price">${formatPriceWithDayChange(s.price, s.day_change_pct)}</td>
      <td>${fmtNum(s.reasonable_price)}</td>
      <td data-col="reasonable_discount">${fmtPct(s.reasonable_discount)}</td>
      <td>${s.pe_ttm != null ? Number(s.pe_ttm).toFixed(2) : '-'}</td>
      <td><button class="btn btn-outline btn-sm" onclick="openGrahamModal('${esc(s.code)}')" title="编辑格雷厄姆估值参数">${fmtNum(s.reasonable_valuation)}</button></td>
      <td data-col="pb_ex_goodwill">${s.pb_ex_goodwill != null ? Number(s.pb_ex_goodwill).toFixed(2) : '-'}</td>
      <td>${s.dividend_yield != null ? Number(s.dividend_yield).toFixed(2) + '%' : '-'}</td>
      <td data-col="ytd_return">${fmtPct(s.ytd_return)}</td>
      <td>
        <button class="icon-btn icon-btn-delete" onclick="deleteStock('${esc(s.code)}','${esc(s.name)}')" title="删除" aria-label="删除 ${esc(s.name)}">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 6h18"></path>
            <path d="M8 6V4h8v2"></path>
            <path d="M6 6l1 15h10l1-15"></path>
            <path d="M10 11v6"></path>
            <path d="M14 11v6"></path>
          </svg>
        </button>
      </td>
    </tr>
  `).join('');
  bindReorderRows();
}

let stockPriceAutoRefreshTimer = null;
let stockPriceAutoRefreshBusy = false;
let stockYtdRefreshId = 0;

function isStockListTradingTime(now = new Date()) {
  const day = now.getDay();
  if (day === 0 || day === 6) return false;
  const minutes = now.getHours() * 60 + now.getMinutes();
  const aShareMorning = minutes >= 9 * 60 + 30 && minutes <= 11 * 60 + 30;
  const aShareAfternoon = minutes >= 13 * 60 && minutes <= 15 * 60;
  const hkMorning = minutes >= 9 * 60 + 30 && minutes <= 12 * 60;
  const hkAfternoon = minutes >= 13 * 60 && minutes <= 16 * 60;
  return aShareMorning || aShareAfternoon || hkMorning || hkAfternoon;
}

function formatRealtimePct(value, showSign = false) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  const n = Number(value);
  const color = n > 0 ? '#cf1322' : (n < 0 ? '#389e0d' : '#666');
  const sign = showSign && n > 0 ? '+' : '';
  return `<span style="color:${color};font-weight:600">${sign}${n.toFixed(2)}%</span>`;
}

function formatPriceWithDayChange(price, dayChangePct) {
  const priceText = price != null && !Number.isNaN(Number(price)) ? Number(price).toFixed(2) : '-';
  return `<span class="price-cell-change">${formatRealtimePct(dayChangePct, true)}</span><span class="price-cell-value">${priceText}</span>`;
}

function updateStockRealtimeCells(items) {
  for (const item of items || []) {
    const row = document.querySelector(`#stockTableBody tr[data-code="${item.code}"]`);
    if (!row) continue;
    const priceCell = row.querySelector('[data-col="price"]');
    const discountCell = row.querySelector('[data-col="reasonable_discount"]');
    const pbCell = row.querySelector('[data-col="pb_ex_goodwill"]');
    if (priceCell) priceCell.innerHTML = formatPriceWithDayChange(item.price, item.day_change_pct);
    if (discountCell) discountCell.innerHTML = formatRealtimePct(item.reasonable_discount);
    if (pbCell) pbCell.textContent = item.pb_ex_goodwill != null ? Number(item.pb_ex_goodwill).toFixed(2) : '-';
  }
}

async function refreshVisibleStockPrices() {
  if (stockPriceAutoRefreshBusy || !isStockListTradingTime()) return;
  if (!document.getElementById('view-list')?.classList.contains('active')) return;
  const rows = Array.from(document.querySelectorAll('#stockTableBody tr[data-code]'));
  const codes = rows.map(row => row.dataset.code).filter(Boolean);
  if (!codes.length) return;
  stockPriceAutoRefreshBusy = true;
  try {
    const res = await fetch('/api/stocks/realtime?codes=' + encodeURIComponent(codes.join(',')));
    const payload = await res.json();
    updateStockRealtimeCells(payload.data || []);
  } catch (e) {
  } finally {
    stockPriceAutoRefreshBusy = false;
  }
}

async function refreshVisibleStockYtd() {
  const rows = Array.from(document.querySelectorAll('#stockTableBody tr[data-code]'));
  const codes = rows.map(row => row.dataset.code).filter(Boolean);
  if (!codes.length) return;
  const refreshId = ++stockYtdRefreshId;
  try {
    const res = await fetch('/api/stocks/ytd?codes=' + encodeURIComponent(codes.join(',')));
    const payload = await res.json();
    if (refreshId !== stockYtdRefreshId) return;
    for (const item of payload.data || []) {
      const row = document.querySelector(`#stockTableBody tr[data-code="${item.code}"]`);
      const cell = row?.querySelector('[data-col="ytd_return"]');
      if (cell) cell.innerHTML = formatRealtimePct(item.ytd_return);
    }
  } catch (e) {
  }
}

function scheduleStockPriceAutoRefresh() {
  if (stockPriceAutoRefreshTimer) return;
  stockPriceAutoRefreshTimer = setInterval(refreshVisibleStockPrices, 10000);
  if (isStockListTradingTime()) setTimeout(refreshVisibleStockPrices, 500);
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshVisibleStockPrices();
});

let grahamDefaults = null;

function numOrEmpty(value) {
  return value == null || Number.isNaN(Number(value)) ? '' : Number(value).toFixed(2);
}

function grahamInputNumber(id) {
  const value = document.getElementById(id).value;
  if (value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function updateGrahamPreview() {
  const payout = grahamInputNumber('grahamPayoutRatio');
  const riskFree = grahamInputNumber('grahamRiskFreeRate');
  const growth = grahamInputNumber('grahamGrowthRate') || 0;
  const expectedProfit = grahamInputNumber('grahamExpectedProfit');
  const totalShares = grahamDefaults?.total_shares;
  let valuation = null;
  let price = null;
  if (payout != null && riskFree != null && riskFree > 0) {
    valuation = payout / riskFree + growth;
  }
  if (valuation != null && expectedProfit != null && totalShares) {
    price = valuation * expectedProfit / totalShares;
  }
  document.getElementById('grahamPreview').innerHTML = `
    <div>合理估值：<b>${valuation != null ? valuation.toFixed(2) : '-'}</b></div>
    <div>合理股价：<b>${price != null ? price.toFixed(2) + ' 元' : '-'}</b></div>
    <div>总股本：${totalShares != null ? Number(totalShares).toFixed(2) + ' 亿股' : '-'}</div>
  `;
}

async function openGrahamModal(code) {
  const modal = document.getElementById('grahamModal');
  document.getElementById('grahamCode').value = code;
  document.getElementById('grahamModalTitle').textContent = `${code} 格雷厄姆估值参数`;
  document.getElementById('grahamPreview').textContent = '加载中...';
  modal.classList.add('active');
  try {
    const res = await fetch(`/api/stock/${code}/graham-valuation`);
    const data = await res.json();
    grahamDefaults = data.defaults || {};
    grahamDefaults.total_shares = data.total_shares;
    document.getElementById('grahamGrowthRate').value = numOrEmpty(data.params?.growth_rate);
    document.getElementById('grahamPayoutRatio').value = numOrEmpty(data.params?.payout_ratio);
    document.getElementById('grahamRiskFreeRate').value = numOrEmpty(data.params?.risk_free_rate);
    document.getElementById('grahamExpectedProfit').value = numOrEmpty(data.params?.expected_profit);
    document.getElementById('grahamPayoutDefault').textContent = `默认：${grahamDefaults.payout_ratio != null ? Number(grahamDefaults.payout_ratio).toFixed(2) + '%' : '暂无最近3年分红比例'}`;
    updateGrahamPreview();
  } catch (e) {
    showToast('估值参数加载失败', 'error');
    closeGrahamModal();
  }
}

function closeGrahamModal() {
  document.getElementById('grahamModal').classList.remove('active');
  grahamDefaults = null;
}

function resetGrahamPayout() {
  document.getElementById('grahamPayoutRatio').value = numOrEmpty(grahamDefaults?.payout_ratio);
  updateGrahamPreview();
}

function resetGrahamRiskFree() {
  document.getElementById('grahamRiskFreeRate').value = '5.00';
  updateGrahamPreview();
}

async function saveGrahamValuation() {
  const code = document.getElementById('grahamCode').value;
  const payload = {
    growth_rate: document.getElementById('grahamGrowthRate').value,
    payout_ratio: document.getElementById('grahamPayoutRatio').value,
    risk_free_rate: document.getElementById('grahamRiskFreeRate').value,
    expected_profit: document.getElementById('grahamExpectedProfit').value,
  };
  try {
    const res = await fetch(`/api/stock/${code}/graham-valuation`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      showToast(data.error || '保存失败', 'error');
      return;
    }
    showToast('估值参数已保存', 'success');
    closeGrahamModal();
    loadStocks();
  } catch (e) {
    showToast('保存失败', 'error');
  }
}

['grahamGrowthRate', 'grahamPayoutRatio', 'grahamRiskFreeRate', 'grahamExpectedProfit'].forEach(id => {
  document.addEventListener('input', e => {
    if (e.target && e.target.id === id) updateGrahamPreview();
  });
});

function updateListControls() {
  document.querySelector('.table-wrap')?.classList.toggle('reorder-mode', reorderMode);
  document.getElementById('btnReorderMode').style.display = reorderMode ? 'none' : '';
  document.getElementById('btnSaveOrder').style.display = reorderMode ? '' : 'none';
  document.getElementById('btnCancelOrder').style.display = reorderMode ? '' : 'none';
  document.getElementById('btnResetSort').style.display = currentSortBy || reorderMode ? '' : 'none';
  document.getElementById('listModeHint').textContent = reorderMode ? '拖动股票行调整默认展示顺序' : (currentSortBy ? '当前为指标排序视图' : '');
  document.getElementById('pagination').style.display = reorderMode ? 'none' : '';
  document.querySelectorAll('[data-sort-arrow]').forEach(el => {
    const field = el.dataset.sortArrow;
    el.textContent = currentSortBy === field ? (currentSortDir === 'asc' ? '↑' : '↓') : '';
  });
}

function sortStocks(field) {
  if (reorderMode) return;
  if (currentSortBy === field) {
    currentSortDir = currentSortDir === 'asc' ? 'desc' : 'asc';
  } else {
    currentSortBy = field;
    currentSortDir = field === 'code' || field === 'name' ? 'asc' : 'desc';
  }
  currentPage = 1;
  loadStocks();
}

function resetListSort() {
  currentSortBy = '';
  currentSortDir = 'asc';
  reorderMode = false;
  listPageSize = 15;
  currentPage = 1;
  loadStocks();
}

function startReorderMode() {
  currentSortBy = '';
  currentSortDir = 'asc';
  reorderMode = true;
  listPageSize = 200;
  currentPage = 1;
  document.getElementById('keyword').value = '';
  loadStocks();
}

function cancelReorderMode() {
  reorderMode = false;
  listPageSize = 15;
  currentPage = 1;
  loadStocks();
}

function bindReorderRows() {
  const tbody = document.getElementById('stockTableBody');
  if (!tbody) return;
  tbody.querySelectorAll('tr').forEach(row => {
    row.ondragstart = e => {
      if (!reorderMode) return e.preventDefault();
      draggedRow = row;
      row.classList.add('dragging');
      e.dataTransfer.effectAllowed = 'move';
    };
    row.ondragend = () => {
      row.classList.remove('dragging');
      tbody.querySelectorAll('tr').forEach(r => r.classList.remove('drag-over'));
      draggedRow = null;
    };
    row.ondragover = e => {
      if (!reorderMode || !draggedRow || draggedRow === row) return;
      e.preventDefault();
      row.classList.add('drag-over');
    };
    row.ondragleave = () => row.classList.remove('drag-over');
    row.ondrop = e => {
      if (!reorderMode || !draggedRow || draggedRow === row) return;
      e.preventDefault();
      row.classList.remove('drag-over');
      const rect = row.getBoundingClientRect();
      const after = e.clientY > rect.top + rect.height / 2;
      tbody.insertBefore(draggedRow, after ? row.nextSibling : row);
    };
  });
}

async function saveDefaultOrder() {
  const codes = Array.from(document.querySelectorAll('#stockTableBody tr')).map(row => row.dataset.code).filter(Boolean);
  if (!codes.length) return;
  try {
    const res = await fetch('/api/stocks/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ codes })
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || '保存失败');
    showToast('默认顺序已保存', 'success');
    reorderMode = false;
    listPageSize = 15;
    currentPage = 1;
    loadStocks();
  } catch (e) {
    showToast('保存顺序失败: ' + e.message, 'error');
  }
}

function renderPagination(data) {
  const pg = document.getElementById('pagination');
  let html = `<span class="info">共 ${data.total} 条 / ${data.total_pages} 页</span>`;
  html += `<button ${data.page <= 1 ? 'disabled' : ''} onclick="goPage(${data.page - 1})">上一页</button>`;
  const start = Math.max(1, data.page - 2);
  const end = Math.min(data.total_pages, data.page + 2);
  for (let i = start; i <= end; i++) {
    html += `<button class="${i === data.page ? 'current' : ''}" onclick="goPage(${i})">${i}</button>`;
  }
  html += `<button ${data.page >= data.total_pages ? 'disabled' : ''} onclick="goPage(${data.page + 1})">下一页</button>`;
  pg.innerHTML = html;
}

function goPage(p) { currentPage = p; loadStocks(); }

async function loadStats() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    document.getElementById('statsInfo').textContent = `共 ${data.total} 只股票 | SH:${data.markets.SH || 0} SZ:${data.markets.SZ || 0} BJ:${data.markets.BJ || 0} HK:${data.markets.HK || 0}`;
  } catch (e) {}
}

// ==================== 弹窗 ====================

function openAddModal() {
  document.getElementById('modalTitle').textContent = '添加股票';
  document.getElementById('editCode').value = '';
  document.getElementById('inputCode').value = '';
  document.getElementById('inputCode').disabled = false;
  document.getElementById('inputName').value = '';
  document.getElementById('btnLookup').style.display = 'inline-block';
  document.getElementById('modal').classList.add('active');
}

async function openEditModal(code) {
  try {
    const res = await fetch('/api/stock/' + code);
    const s = await res.json();
    if (s.error) { showToast(s.error, 'error'); return; }
    document.getElementById('modalTitle').textContent = '编辑股票';
    document.getElementById('editCode').value = s.code;
    document.getElementById('inputCode').value = s.code;
    document.getElementById('inputCode').disabled = true;
    document.getElementById('inputName').value = s.name;
    document.getElementById('btnLookup').style.display = 'none';
    document.getElementById('modal').classList.add('active');
  } catch (e) { showToast('获取股票信息失败', 'error'); }
}

function onCodeInput() {
  document.getElementById('inputName').value = '';
}

async function lookupStock() {
  const code = document.getElementById('inputCode').value.trim();
  if (!code) { showToast('请输入股票代码', 'error'); return; }
  const btn = document.getElementById('btnLookup');
  btn.disabled = true;
  btn.textContent = '查询中...';
  try {
    // If not a 6-digit code, search first
    if (!/^\d{6}$/.test(code)) {
      const searchRes = await fetch('/api/stock-search?keyword=' + encodeURIComponent(code));
      const searchData = await searchRes.json();
      if (searchData && searchData.length > 0) {
        const s = searchData[0];
        document.getElementById('inputCode').value = s.code;
        document.getElementById('inputName').value = s.name;
        showToast('已识别: ' + s.name, 'success');
        btn.disabled = false;
        btn.textContent = '查询';
        return;
      }
      showToast('未找到匹配的股票', 'error');
      btn.disabled = false;
      btn.textContent = '查询';
      return;
    }
    const res = await fetch('/api/stock-info/' + code);
    const data = await res.json();
    if (data.error) {
      showToast(data.error, 'error');
    } else {
      document.getElementById('inputName').value = data.name;
      showToast('已识别: ' + data.name, 'success');
    }
  } catch (e) {
    showToast('查询失败', 'error');
  }
  btn.disabled = false;
  btn.textContent = '查询';
}

function closeModal() {
  document.getElementById('modal').classList.remove('active');
}

async function saveStock() {
  const editCode = document.getElementById('editCode').value;
  const isEdit = !!editCode;

  const code = document.getElementById('inputCode').value.trim();
  const name = document.getElementById('inputName').value.trim();

  if (!code) {
    showToast('请输入股票代码', 'error'); return;
  }

  const body = { code, name };
  const url = isEdit ? '/api/stock/' + editCode : '/api/stock';
  const method = isEdit ? 'PUT' : 'POST';

  try {
    const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await res.json();
    if (data.success) {
      showToast(isEdit ? '更新成功' : '添加成功', 'success');
      closeModal();
      loadStocks();
      loadStats();
    } else {
      showToast(data.error || '操作失败', 'error');
    }
  } catch (e) {
    showToast('请求失败', 'error');
  }
}

async function deleteStock(code, name) {
  if (!confirm(`确认删除 ${code} ${name}？`)) return;
  try {
    const res = await fetch('/api/stock/' + code, { method: 'DELETE' });
    const data = await res.json();
    if (data.success) {
      showToast('删除成功', 'success');
      loadStocks();
      loadStats();
    } else {
      showToast(data.error || '删除失败', 'error');
    }
  } catch (e) { showToast('请求失败', 'error'); }
}

// ==================== 自定义财报 ====================

function switchStock() {
  const code = document.getElementById('stockSwitcher').value;
  if (code) navigateTo('/stock/' + code);
}

async function populateStockSwitcher(currentCode) {
  const sel = document.getElementById('stockSwitcher');
  sel.innerHTML = '<option value="">切换股票...</option>';
  try {
    const res = await fetch('/api/stocks?page=1&page_size=200');
    const data = await res.json();
    for (const s of data.data) {
      const opt = document.createElement('option');
      opt.value = s.code;
      opt.textContent = s.name + ' (' + s.code + ')';
      if (s.code === currentCode) opt.selected = true;
      sel.appendChild(opt);
    }
  } catch {}
}
