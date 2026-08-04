async function loadFundamentalDashboard(code) {
  code = code || getCurrentCode();
  const wrap = document.getElementById('fundamentalDashboard');
  if (!code || !wrap) return;
  wrap.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const params = new URLSearchParams();
    const cagrYears = getFundamentalCagrYears();
    if (cagrYears) params.set('cagr_years', cagrYears);
    const query = params.toString();
    const data = await StockApi.getJson('/api/stock/' + encodeURIComponent(code) + '/fundamental-dashboard' + (query ? '?' + query : ''));
    if (code !== getCurrentCode()) return;
    renderFundamentalDashboard(data);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">基本面驾驶舱加载失败: ' + esc(e.message || '') + '</div>';
  }
}

function getFundamentalCagrYears() {
  const input = document.getElementById('fundCagrYears');
  const raw = input ? input.value : (localStorage.getItem('fundCagrYears') || '');
  const years = parseInt(raw, 10);
  return Number.isFinite(years) && years > 0 ? String(years) : '';
}

function onFundamentalCagrYearsChange() {
  const years = getFundamentalCagrYears();
  localStorage.setItem('fundCagrYears', years);
  loadFundamentalDashboard(getCurrentCode());
}

function formatFundValue(metric) {
  if (!metric || metric.value == null) return '-';
  const value = Number(metric.value);
  if (Number.isNaN(value)) return '-';
  const decimals = Math.abs(value) >= 100 ? 1 : 2;
  return StockFormat.number(value, { maximumFractionDigits: decimals }) + (metric.unit || '');
}

function renderFundamentalDashboard(data) {
  const wrap = document.getElementById('fundamentalDashboard');
  if (!wrap) return;
  if (data.message) {
    wrap.innerHTML = '<div class="empty">' + esc(data.message) + '</div>';
    return;
  }
  const summary = data.summary || [];
  const groups = data.groups || [];
  const signals = data.signals || [];
  const summaryHtml = summary.map(item => `
    <div class="fund-score-card fund-${esc(item.level || 'neutral')}">
      <div class="fund-score-top">
        <span>${esc(item.title)}</span>
        <span class="fund-badge">${esc(item.text || '-')}</span>
      </div>
      <div class="fund-score-main">
        <span class="fund-score">${item.score == null ? '-' : esc(String(item.score))}</span>
        <span class="fund-score-unit">/100</span>
      </div>
      <div class="fund-score-sub">${esc(item.main || '')}</div>
      <div class="fund-score-note">${esc(item.note || '')}</div>
    </div>
  `).join('');

  const groupsHtml = groups.map(group => `
    <section class="fund-group">
      <h3>${esc(group.title)}</h3>
      <div class="fund-metric-list">
        ${(group.metrics || []).map(m => `
          <div class="fund-metric fund-${esc(m.verdict || 'neutral')}">
            <div>
              <div class="fund-metric-name">${esc(m.name)}</div>
              <div class="fund-metric-note">${esc(m.note || '')}</div>
            </div>
            <div class="fund-metric-value">${esc(formatFundValue(m))}</div>
          </div>
        `).join('')}
      </div>
    </section>
  `).join('');

  const signalsHtml = signals.map(s => `
    <div class="fund-signal fund-${esc(s.level || 'neutral')}">
      <div class="fund-signal-dot"></div>
      <div>
        <div class="fund-signal-title">${esc(s.text || '')}</div>
        <div class="fund-signal-detail">${esc(s.detail || '')}</div>
      </div>
    </div>
  `).join('');

  wrap.innerHTML = `
    <div class="fund-head">
      <div>
        <div class="fund-title">基本面驾驶舱</div>
        <div class="fund-subtitle">数据区间：${esc(data.year_range || '-')}，最新年报：${esc(String(data.latest_year || '-'))}，最新同比：${esc(data.latest_period || '-')}，CAGR区间：${esc(data.cagr_range || '-')}</div>
      </div>
      <div class="fund-head-actions">
        <label class="fund-cagr-control">
          <span>CAGR</span>
          <input id="fundCagrYears" type="number" min="1" max="30" step="1" placeholder="全部" value="${esc(data.cagr_years ? String(data.cagr_years) : '')}" onchange="onFundamentalCagrYearsChange()" onkeydown="if(event.key==='Enter')onFundamentalCagrYearsChange()">
          <span>年</span>
        </label>
        <button class="btn btn-outline btn-sm" type="button" onclick="loadFundamentalDashboard(getCurrentCode())">刷新</button>
      </div>
    </div>
    <div class="fund-score-grid">${summaryHtml}</div>
    <div class="fund-body-grid">
      <div class="fund-groups">${groupsHtml}</div>
      <aside class="fund-signals">
        <h3>风险信号</h3>
        ${signalsHtml}
      </aside>
    </div>
  `;
}

