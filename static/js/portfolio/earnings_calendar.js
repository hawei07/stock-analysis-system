const EARNINGS_PERIOD_LABELS = {
  day: '日收益',
  month: '月收益',
  year: '年收益'
};

function earningsCalendarRows() {
  return (PortfolioState.navHistory.rows || [])
    .filter(row => row && row.date)
    .map(row => ({...row, date: String(row.date)}))
    .sort((a, b) => a.date.localeCompare(b.date));
}

function earningsNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function earningsPeriodKey(date, period) {
  return period === 'year' ? date.slice(0, 4) : date.slice(0, 7);
}

function earningsPeriodTitle(key, period) {
  if (period === 'year') return `${key}年`;
  const [year, month] = key.split('-');
  return `${year}年${Number(month)}月`;
}

function earningsMonthParts(month) {
  const [year, monthNumber] = String(month || '').split('-').map(Number);
  if (!year || !monthNumber) return null;
  return {year, month: monthNumber};
}

function earningsMonthValue(year, month) {
  return `${year}-${String(month).padStart(2, '0')}`;
}

function earningsPeriodRate(allRows, periodRows) {
  if (!periodRows.length) return null;
  const firstIndex = allRows.indexOf(periodRows[0]);
  const previousRow = firstIndex > 0 ? allRows[firstIndex - 1] : null;
  const firstNav = earningsNumber(periodRows[0].nav_index);
  const baseNav = earningsNumber(previousRow?.nav_index) ?? firstNav;
  const lastNav = earningsNumber(periodRows[periodRows.length - 1].nav_index);
  if (baseNav != null && baseNav > 0 && lastNav != null) {
    return (lastNav / baseNav - 1) * 100;
  }

  let factor = 1;
  let hasRate = false;
  periodRows.forEach(row => {
    const rate = earningsNumber(row.nav_change_pct);
    if (rate == null) return;
    factor *= 1 + rate / 100;
    hasRate = true;
  });
  return hasRate ? (factor - 1) * 100 : null;
}

function earningsPeriodAmount(periodRows) {
  let amount = 0;
  let hasValue = false;
  periodRows.forEach(row => {
    const value = earningsNumber(row.daily_return);
    if (value == null) return;
    amount += value;
    hasValue = true;
  });
  return hasValue ? amount : null;
}

function aggregateEarningsPeriods(allRows, period) {
  const grouped = new Map();
  allRows.forEach(row => {
    const key = earningsPeriodKey(row.date, period);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(row);
  });
  return Array.from(grouped.entries())
    .map(([key, rows]) => ({
      key,
      title: earningsPeriodTitle(key, period),
      rows,
      amount: earningsPeriodAmount(rows),
      rate: earningsPeriodRate(allRows, rows),
      startDate: rows[0].date,
      endDate: rows[rows.length - 1].date
    }))
    .sort((a, b) => b.key.localeCompare(a.key));
}

function earningsDisplayValue(amount, rate) {
  const value = PortfolioState.earningsCalendar.display === 'rate' ? rate : amount;
  if (value == null) return '--';
  return PortfolioState.earningsCalendar.display === 'rate'
    ? signedPct(value)
    : signedPrivateMoney(value);
}

function earningsDisplayClass(amount, rate) {
  const value = PortfolioState.earningsCalendar.display === 'rate' ? rate : amount;
  return profitClass(value);
}

function earningsDisplayLabel() {
  return PortfolioState.earningsCalendar.display === 'rate' ? '收益率' : '收益金额';
}

function updateEarningsCalendarControls() {
  const state = PortfolioState.earningsCalendar;
  document.querySelectorAll('[data-earnings-period]').forEach(button => {
    const active = button.dataset.earningsPeriod === state.period;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const toggle = document.getElementById('earningsDisplayToggle');
  if (toggle) {
    const toRate = state.display !== 'rate';
    toggle.textContent = toRate ? '↔ 收益率' : '↔ 收益金额';
    toggle.setAttribute('aria-label', toRate ? '切换为收益率' : '切换为收益金额');
    toggle.title = toRate ? '切换为收益率' : '切换为收益金额';
  }
  const note = document.getElementById('earningsCalendarNote');
  if (note) {
    note.textContent = state.display === 'rate'
      ? '收益率按净值指数复合计算，已剔除外部入金/出金影响'
      : '收益金额按每日净值收益汇总，已剔除外部入金/出金影响';
  }
}

function latestEarningsMonth(rows) {
  return rows.length ? rows[rows.length - 1].date.slice(0, 7) : '';
}

function ensureEarningsCalendarMonth(rows) {
  const state = PortfolioState.earningsCalendar;
  if (!state.selectedMonth || !/^\d{4}-\d{2}$/.test(state.selectedMonth)) {
    state.selectedMonth = latestEarningsMonth(rows);
  }
}

function renderEarningsCalendar() {
  const content = document.getElementById('earningsCalendarContent');
  if (!content) return;
  const rows = earningsCalendarRows();
  updateEarningsCalendarControls();
  ensureEarningsCalendarMonth(rows);
  if (!rows.length) {
    content.innerHTML = '<div class="empty">暂无净值数据，请先记录今日净值。</div>';
    return;
  }
  content.innerHTML = PortfolioState.earningsCalendar.period === 'day'
    ? renderDailyEarningsCalendar(rows)
    : renderEarningsPeriodCards(rows, PortfolioState.earningsCalendar.period);
}

function renderDailyEarningsCalendar(rows) {
  const state = PortfolioState.earningsCalendar;
  const parts = earningsMonthParts(state.selectedMonth);
  if (!parts) return '<div class="empty">暂无可展示的日期。</div>';
  const monthRows = rows.filter(row => row.date.slice(0, 7) === state.selectedMonth);
  const rowByDay = new Map(monthRows.map(row => [Number(row.date.slice(8, 10)), row]));
  const firstWeekday = (new Date(parts.year, parts.month - 1, 1).getDay() + 6) % 7;
  const daysInMonth = new Date(parts.year, parts.month, 0).getDate();
  const cells = [];

  for (let i = 0; i < firstWeekday; i++) {
    cells.push('<div class="earnings-day-cell is-empty" aria-hidden="true"></div>');
  }
  for (let day = 1; day <= daysInMonth; day++) {
    const row = rowByDay.get(day);
    const amount = row ? earningsNumber(row.daily_return) : null;
    const rate = row ? earningsNumber(row.nav_change_pct) : null;
    const value = row ? earningsDisplayValue(amount, rate) : '—';
    const classes = row
      ? `has-data ${earningsDisplayClass(amount, rate)}`
      : 'is-empty';
    const label = row
      ? `${row.date} ${earningsDisplayLabel()} ${value}`
      : `${state.selectedMonth}-${String(day).padStart(2, '0')} 暂无数据`;
    cells.push(`<div class="earnings-day-cell ${classes}" aria-label="${esc(label)}">
      <div class="earnings-day-number">${day}</div>
      <div class="earnings-day-value">${value}</div>
    </div>`);
  }

  const firstMonth = rows[0].date.slice(0, 7);
  const lastMonth = rows[rows.length - 1].date.slice(0, 7);
  const previousDisabled = state.selectedMonth <= firstMonth ? ' disabled' : '';
  const nextDisabled = state.selectedMonth >= lastMonth ? ' disabled' : '';
  const amount = earningsPeriodAmount(monthRows);
  const rate = earningsPeriodRate(rows, monthRows);
  return `<div class="earnings-calendar-day-toolbar">
    <button class="earnings-month-nav" type="button" onclick="shiftEarningsCalendarMonth(-1)"${previousDisabled} aria-label="上一个月">‹</button>
    <strong>${parts.year}年${parts.month}月</strong>
    <button class="earnings-month-nav" type="button" onclick="shiftEarningsCalendarMonth(1)"${nextDisabled} aria-label="下一个月">›</button>
  </div>
  <div class="earnings-weekday-grid">${['一', '二', '三', '四', '五', '六', '日'].map(day => `<span>${day}</span>`).join('')}</div>
  <div class="earnings-day-grid">${cells.join('')}</div>
  <div class="earnings-calendar-summary">
    <span>本月已记录 ${monthRows.length} 天</span>
    <strong class="${earningsDisplayClass(amount, rate)}">${earningsDisplayLabel()}：${earningsDisplayValue(amount, rate)}</strong>
  </div>`;
}

function renderEarningsPeriodCards(rows, period) {
  const periods = aggregateEarningsPeriods(rows, period);
  const unit = period === 'month' ? '个月' : '年';
  return `<div class="earnings-period-summary">已记录 ${periods.length} ${unit}，当前显示${earningsDisplayLabel()}</div>
    <div class="earnings-period-grid">${periods.map(item => `
      <div class="earnings-period-card ${earningsDisplayClass(item.amount, item.rate)}">
        <div class="earnings-period-title">${item.title}</div>
        <div class="earnings-period-value">${earningsDisplayValue(item.amount, item.rate)}</div>
        <div class="earnings-period-meta">${item.startDate} ~ ${item.endDate} · ${item.rows.length} 天</div>
      </div>`).join('')}</div>`;
}

function setEarningsCalendarPeriod(period) {
  if (!EARNINGS_PERIOD_LABELS[period]) return;
  PortfolioState.earningsCalendar.period = period;
  renderEarningsCalendar();
}

function toggleEarningsCalendarDisplay() {
  PortfolioState.earningsCalendar.display = PortfolioState.earningsCalendar.display === 'rate'
    ? 'amount'
    : 'rate';
  renderEarningsCalendar();
}

function shiftEarningsCalendarMonth(delta) {
  const state = PortfolioState.earningsCalendar;
  const parts = earningsMonthParts(state.selectedMonth);
  if (!parts) return;
  const next = new Date(parts.year, parts.month - 1 + Number(delta || 0), 1);
  state.selectedMonth = earningsMonthValue(next.getFullYear(), next.getMonth() + 1);
  renderEarningsCalendar();
}

async function openEarningsCalendarModal() {
  const overlay = document.getElementById('earningsCalendarModalOverlay');
  const content = document.getElementById('earningsCalendarContent');
  if (!overlay || !content) return;
  overlay.classList.add('active');
  content.innerHTML = '<div class="empty">正在加载收益数据…</div>';
  const previousRows = PortfolioState.navHistory.rows || [];
  try {
    await loadNav(true);
  } catch (error) {
    if (!previousRows.length) {
      content.innerHTML = `<div class="empty">收益数据加载失败：${esc(error.message || '请稍后重试')}</div>`;
      return;
    }
  }
  renderEarningsCalendar();
}

function closeEarningsCalendarModal() {
  document.getElementById('earningsCalendarModalOverlay')?.classList.remove('active');
}
