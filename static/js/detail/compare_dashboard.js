let compareCodes = [];
let compareSelectedMetrics = [];
let compareMetricOptions = [];
let compareDefaultMetrics = [];
let comparePrimaryCode = '';
let compareDraggingMetric = '';

function initCompareDashboard(code) {
  code = code || getCurrentCode();
  if (!code) return;
  if (comparePrimaryCode !== code) {
    comparePrimaryCode = code;
    compareCodes = [code];
    compareSelectedMetrics = [];
    const input = document.getElementById('compareAddInput');
    if (input) input.value = '';
  }
  renderCompareStockChips();
  loadCompareDashboard();
}

function onComparePeriodChange() {
  const period = document.getElementById('comparePeriod')?.value || 'FY';
  const viewEl = document.getElementById('compareView');
  if (viewEl) {
    viewEl.disabled = period === 'FY';
    if (period === 'FY') viewEl.value = 'cumulative';
  }
  loadCompareDashboard();
}

async function addCompareStock() {
  const input = document.getElementById('compareAddInput');
  const raw = (input?.value || '').trim();
  if (!raw) return;
  if (compareCodes.length >= 3) {
    showToast('最多只能对比 3 只股票', 'error');
    return;
  }
  const code = await resolveStockCode(raw);
  if (!code) {
    showToast('未找到匹配股票', 'error');
    return;
  }
  if (compareCodes.includes(code)) {
    showToast('这只股票已经在对比中', 'error');
    return;
  }
  compareCodes.push(code);
  if (input) input.value = '';
  renderCompareStockChips();
  loadCompareDashboard();
}

function removeCompareStock(code) {
  if (code === comparePrimaryCode) return;
  compareCodes = compareCodes.filter(c => c !== code);
  renderCompareStockChips();
  loadCompareDashboard();
}

function renderCompareStockChips(stocks) {
  const wrap = document.getElementById('compareStocks');
  if (!wrap) return;
  const stockMap = {};
  (stocks || []).forEach(s => stockMap[s.code] = s);
  wrap.innerHTML = compareCodes.map((code, idx) => {
    const stock = stockMap[code] || {};
    const label = stock.name ? `${stock.name} ${code}` : code;
    const remove = idx === 0 ? '' : `<button type="button" onclick="removeCompareStock('${esc(code)}')" title="移除">×</button>`;
    return `<span class="compare-stock-chip ${idx === 0 ? 'primary' : ''}">${esc(label)}${remove}</span>`;
  }).join('');
}

function addCompareMetric() {
  const select = document.getElementById('compareMetricSelect');
  const key = select?.value;
  if (!key || compareSelectedMetrics.includes(key)) return;
  compareSelectedMetrics.push(key);
  renderCompareMetricChips();
  loadCompareDashboard();
}

function removeCompareMetric(key) {
  compareSelectedMetrics = compareSelectedMetrics.filter(k => k !== key);
  renderCompareMetricChips();
  loadCompareDashboard();
}

function resetCompareMetrics() {
  compareSelectedMetrics = [...compareDefaultMetrics];
  renderCompareMetricChips();
  loadCompareDashboard();
}

function moveCompareMetric(sourceKey, targetKey) {
  if (!sourceKey || !targetKey || sourceKey === targetKey) return false;
  const from = compareSelectedMetrics.indexOf(sourceKey);
  const to = compareSelectedMetrics.indexOf(targetKey);
  if (from === -1 || to === -1) return false;
  const next = [...compareSelectedMetrics];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  compareSelectedMetrics = next;
  return true;
}

function onCompareMetricDragStart(event, key) {
  compareDraggingMetric = key;
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move';
    event.dataTransfer.setData('text/plain', key);
  }
  event.currentTarget?.classList.add('compare-dragging');
}

function onCompareMetricDragOver(event) {
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
  event.currentTarget?.classList.add('compare-drag-over');
}

function onCompareMetricDragLeave(event) {
  event.currentTarget?.classList.remove('compare-drag-over');
}

function onCompareMetricDrop(event, targetKey) {
  event.preventDefault();
  const sourceKey = compareDraggingMetric || event.dataTransfer?.getData('text/plain');
  document.querySelectorAll('.compare-drag-over').forEach(el => el.classList.remove('compare-drag-over'));
  if (!moveCompareMetric(sourceKey, targetKey)) return;
  renderCompareMetricChips();
  loadCompareDashboard();
}

function onCompareMetricDragEnd(event) {
  event.currentTarget?.classList.remove('compare-dragging');
  document.querySelectorAll('.compare-dragging,.compare-drag-over').forEach(el => el.classList.remove('compare-dragging', 'compare-drag-over'));
  compareDraggingMetric = '';
}

function renderCompareMetricSelect() {
  const select = document.getElementById('compareMetricSelect');
  if (!select || !compareMetricOptions.length) return;
  const groups = {};
  compareMetricOptions.forEach(m => {
    const g = m.group || '其他';
    if (!groups[g]) groups[g] = [];
    groups[g].push(m);
  });
  select.innerHTML = Object.keys(groups).map(group => `
    <optgroup label="${esc(group)}">
      ${groups[group].map(m => `<option value="${esc(m.key)}">${esc(m.name)}</option>`).join('')}
    </optgroup>
  `).join('');
}

function renderCompareMetricChips() {
  const wrap = document.getElementById('compareMetricChips');
  if (!wrap) return;
  const meta = {};
  compareMetricOptions.forEach(m => meta[m.key] = m);
  wrap.innerHTML = compareSelectedMetrics.map(key => `
    <span class="compare-metric-chip" draggable="true" data-metric-key="${esc(key)}"
      ondragstart="onCompareMetricDragStart(event, '${esc(key)}')"
      ondragover="onCompareMetricDragOver(event)"
      ondragleave="onCompareMetricDragLeave(event)"
      ondrop="onCompareMetricDrop(event, '${esc(key)}')"
      ondragend="onCompareMetricDragEnd(event)">
      <span class="compare-metric-drag-handle" title="拖动排序">⋮⋮</span>
      ${esc(meta[key]?.name || key)}
      <button type="button" onclick="removeCompareMetric('${esc(key)}')" title="移除">×</button>
    </span>
  `).join('');
}

async function loadCompareDashboard() {
  const wrap = document.getElementById('compareDashboard');
  const primary = getCurrentCode();
  if (!wrap || !primary) return;
  if (!compareCodes.length || compareCodes[0] !== primary) {
    comparePrimaryCode = primary;
    compareCodes = [primary];
  }
  wrap.innerHTML = '<div class="empty">加载中...</div>';
  const yearEl = document.getElementById('compareYear');
  const periodEl = document.getElementById('comparePeriod');
  const viewEl = document.getElementById('compareView');
  const params = new URLSearchParams({
    codes: compareCodes.join(','),
    period: periodEl?.value || 'FY',
    view: viewEl?.value || 'cumulative'
  });
  if (yearEl?.value) params.set('year', yearEl.value);
  if (compareSelectedMetrics.length) params.set('metrics', compareSelectedMetrics.join(','));
  try {
    const data = await StockApi.getJson('/api/stock/' + encodeURIComponent(primary) + '/compare-dashboard?' + params.toString());
    if (primary !== getCurrentCode()) return;
    compareMetricOptions = data.metric_options || compareMetricOptions;
    compareDefaultMetrics = data.default_metrics || compareDefaultMetrics;
    if (!compareSelectedMetrics.length) compareSelectedMetrics = [...compareDefaultMetrics];
    renderCompareYearSelect(data.available_years || [], data.year);
    if (periodEl && data.period && periodEl.value !== data.period) {
      periodEl.value = data.period;
      if (viewEl) {
        viewEl.disabled = data.period === 'FY';
        if (data.period === 'FY') viewEl.value = 'cumulative';
      }
    }
    if (data.period_fallback_note) showToast(data.period_fallback_note, 'success');
    renderCompareMetricSelect();
    renderCompareMetricChips();
    renderCompareStockChips(data.stocks || []);
    renderCompareRows(data);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">对比数据加载失败: ' + esc(e.message || '') + '</div>';
  }
}

function renderCompareYearSelect(years, selectedYear) {
  const select = document.getElementById('compareYear');
  if (!select || !years.length) return;
  const current = select.value || String(selectedYear || years[0]);
  select.innerHTML = years.map(y => `<option value="${esc(String(y))}">${esc(String(y))}</option>`).join('');
  select.value = years.map(String).includes(current) ? current : String(selectedYear || years[0]);
}

function formatCompareValue(value, unit) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  const num = Number(value);
  const digits = Math.abs(num) >= 100 ? 1 : 2;
  return StockFormat.number(num, { maximumFractionDigits: digits }) + (unit || '');
}

function renderCompareRows(data) {
  const wrap = document.getElementById('compareDashboard');
  if (!wrap) return;
  const stocks = data.stocks || [];
  const rows = data.rows || [];
  if (!stocks.length || !rows.length) {
    wrap.innerHTML = '<div class="empty">暂无可对比数据</div>';
    return;
  }

  const headHtml = `
    <thead>
      <tr>
        <th class="compare-metric-head">指标</th>
        ${stocks.map(stock => `
          <th>
            <div class="compare-stock-head-name">${esc(stock.name || stock.code)}</div>
            <div class="compare-stock-head-code">${esc(stock.code || '')}</div>
          </th>
        `).join('')}
      </tr>
    </thead>
  `;

  const bodyHtml = rows.map(row => {
    const vals = row.values || [];
    const nums = vals.map(v => Number(v.value)).filter(v => !Number.isNaN(v));
    const maxAbs = Math.max(...nums.map(v => Math.abs(v)), 0);
    const cells = stocks.map(stock => {
      const item = vals.find(v => v.code === stock.code) || {};
      const value = item.value;
      const num = Number(value);
      const width = value == null || Number.isNaN(num) || maxAbs <= 0 ? 0 : Math.max(4, Math.abs(num) / maxAbs * 100);
      const cls = num < 0 ? 'neg' : 'pos';
      return `
        <td>
          <div class="compare-cell-value">${esc(formatCompareValue(value, row.unit))}</div>
          <div class="compare-bar-track">
            <div class="compare-bar ${cls}" style="width:${width}%"></div>
          </div>
        </td>
      `;
    }).join('');
    return `
      <tr class="compare-metric-row" draggable="true" data-metric-key="${esc(row.key || '')}"
        ondragstart="onCompareMetricDragStart(event, '${esc(row.key || '')}')"
        ondragover="onCompareMetricDragOver(event)"
        ondragleave="onCompareMetricDragLeave(event)"
        ondrop="onCompareMetricDrop(event, '${esc(row.key || '')}')"
        ondragend="onCompareMetricDragEnd(event)">
        <th class="compare-metric-col">
          <div class="compare-metric-name"><span class="compare-metric-drag-handle" title="拖动排序">⋮⋮</span>${esc(row.name)}</div>
          <div class="compare-metric-meta">${esc(row.group || '')}${row.unit ? ' / ' + esc(row.unit) : ''}</div>
        </th>
        ${cells}
      </tr>
    `;
  }).join('');

  wrap.innerHTML = `
    <div class="compare-table-wrap">
      <table class="compare-table">
        ${headHtml}
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}

