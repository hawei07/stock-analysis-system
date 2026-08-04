let shareholderCache = [];
let shareholderCacheCode = '';
let shareholderYearRange = 3;
let shareholderPeriodFilter = 'quarter';
let shareholderChangeFilter = 'all';

async function loadShareholders(code, options = {}) {
  if (!code) return;
  const force = Boolean(options.force);
  const statusEl = document.getElementById('shareholdersStatus');
  const wrap = document.getElementById('shareholderGridWrap');
  if (!force && shareholderCacheCode === code && shareholderCache.length) {
    renderShareholders();
    return;
  }
  if (statusEl) statusEl.textContent = force ? '正在更新...' : '加载中...';
  if (wrap) wrap.innerHTML = '<div class="empty" id="shareholdersEmpty">' + (force ? '正在更新股东数据...' : '正在加载股东数据...') + '</div>';
  try {
    const url = '/api/stock/' + code + '/shareholders' + (force ? '?refresh=1' : '');
    const data = await StockApi.getJson(url);
    if (code !== getCurrentCode()) return;
    shareholderCache = data.periods || [];
    shareholderCacheCode = code;
    renderShareholders();
    if (statusEl) {
      const fetchedAt = data.fetched_at ? ' · ' + data.fetched_at : '';
      statusEl.textContent = (data.source || '') + fetchedAt;
    }
  } catch (e) {
    shareholderCache = [];
    shareholderCacheCode = '';
    renderShareholders();
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '加载股东数据失败', 'error');
  }
}

function refreshShareholders() {
  const code = getCurrentCode();
  if (!code) return;
  loadShareholders(code, { force: true });
}

function setShareholderPeriodFilter(filter) {
  shareholderPeriodFilter = filter;
  document.querySelectorAll('#shareholderPeriodFilter button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === filter);
  });
  renderShareholders();
}

function setShareholderChangeFilter(filter) {
  shareholderChangeFilter = filter;
  document.querySelectorAll('#shareholderChangeFilter button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === filter);
  });
  renderShareholders();
}

function setShareholderYearRange(years) {
  shareholderYearRange = Number(years) || 3;
  document.querySelectorAll('#shareholderYearRangeFilter button').forEach(btn => {
    btn.classList.toggle('active', Number(btn.dataset.years) === shareholderYearRange);
  });
  renderShareholders();
}

function shareholderYearVisible(period, latestYear) {
  if (!period || !period.year || !latestYear) return true;
  return Number(period.year) >= latestYear - shareholderYearRange + 1;
}

function shareholderPeriodVisible(period) {
  if (shareholderPeriodFilter === 'all') return true;
  if (shareholderPeriodFilter === 'year') return period.month_day === '12-31';
  if (shareholderPeriodFilter === 'half') return period.month_day === '06-30' || period.month_day === '12-31';
  return period.is_report_date && ['03-31', '06-30', '09-30', '12-31'].includes(period.month_day);
}

function formatShareholderShares(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿股' : (n / 1e4).toFixed(2) + '万股';
}

function formatShareholderValue(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿元' : (n / 1e4).toFixed(2) + '万元';
}

function shareholderChangeHtml(holder) {
  const type = holder.change_type || '';
  if (type === 'new') return '<span class="shareholder-change new">✓ 新进</span>';
  if (type === 'unchanged') return '<span class="shareholder-change unchanged">↔ 不变</span>';
  const raw = Number(holder.change || 0);
  if (type === 'increase') return `<span class="shareholder-change increase">▲ ${formatShareholderShares(Math.abs(raw))}</span>`;
  if (type === 'decrease') return `<span class="shareholder-change decrease">▼ ${formatShareholderShares(Math.abs(raw))}</span>`;
  return '';
}

function scrollShareholdersToLatest() {
  const wrap = document.getElementById('shareholderGridWrap');
  if (!wrap) return;
  requestAnimationFrame(() => {
    wrap.scrollLeft = wrap.scrollWidth;
  });
}

function renderShareholders() {
  const wrap = document.getElementById('shareholderGridWrap');
  if (!wrap) return;
  const latestYear = shareholderCache.reduce((maxYear, period) => {
    const year = Number(period.year);
    return Number.isFinite(year) ? Math.max(maxYear, year) : maxYear;
  }, 0);
  const periods = shareholderCache.filter(period => shareholderYearVisible(period, latestYear) && shareholderPeriodVisible(period));
  if (!periods.length) {
    wrap.innerHTML = '<div class="empty" id="shareholdersEmpty">暂无股东数据</div>';
    return;
  }

  const visiblePeriods = periods.slice().sort((a, b) => a.date.localeCompare(b.date));
  const yearHeader = visiblePeriods.map((period, index) => {
    const prev = visiblePeriods[index - 1];
    const startsYear = !prev || prev.year !== period.year;
    const span = visiblePeriods.filter(item => item.year === period.year).length;
    if (!startsYear) return '';
    return `<th class="shareholder-period year-break" colspan="${span}">${esc(period.year)}</th>`;
  }).join('');

  const periodHeader = visiblePeriods.map((period, index) => {
    const prev = visiblePeriods[index - 1];
    const yearBreak = !prev || prev.year !== period.year ? ' year-break' : '';
    return `<th class="shareholder-period${yearBreak}">
      <div class="shareholder-period-main">${esc(period.label || period.date)}</div>
      <div class="shareholder-period-sub">
        总股本: ${formatShareholderShares(period.total_shares)}<br>
        前十合计: ${period.top10_ratio == null ? '--' : Number(period.top10_ratio).toFixed(2) + '%'} (${formatShareholderShares(period.top10_shares)})
      </div>
    </th>`;
  }).join('');

  const bodyRows = [];
  for (let rank = 1; rank <= 10; rank++) {
    const cells = visiblePeriods.map((period, index) => {
      const holder = (period.holders || []).find(item => item.rank === rank);
      const prev = visiblePeriods[index - 1];
      const yearBreak = !prev || prev.year !== period.year ? ' year-break' : '';
      if (!holder) return `<td class="shareholder-cell${yearBreak}">--</td>`;
      const filteredOut = shareholderChangeFilter !== 'all' && holder.change_type !== shareholderChangeFilter;
      return `<td class="shareholder-cell${yearBreak}${filteredOut ? ' filtered-out' : ''}">
        <div class="shareholder-name" title="${esc(holder.name)}">${esc(holder.name)}</div>
        <div class="shareholder-meta">
          ${shareholderChangeHtml(holder)}
          <span class="shareholder-ratio">${holder.hold_ratio == null ? '--' : Number(holder.hold_ratio).toFixed(2) + '%'}</span>
          (${formatShareholderShares(holder.hold_num)})
          ${holder.shares_type ? '<span class="shareholder-type">' + esc(holder.shares_type) + '</span>' : ''}
        </div>
      </td>`;
    }).join('');
    bodyRows.push(`<tr><td class="rank-col">第${rank}</td>${cells}</tr>`);
  }

  wrap.innerHTML = `<table class="shareholder-grid">
    <thead>
      <tr><th class="rank-col"></th>${yearHeader}</tr>
      <tr><th class="rank-col">排名</th>${periodHeader}</tr>
    </thead>
    <tbody>${bodyRows.join('')}</tbody>
  </table>`;
  scrollShareholdersToLatest();
}

// ==================== 互动易 ====================

