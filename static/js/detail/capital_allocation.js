let capitalAllocationCode = '';
let capitalAllocationChart = null;

function initCapitalAllocation(code) {
  code = code || getCurrentCode();
  if (!code) return;
  if (capitalAllocationCode !== code) {
    capitalAllocationCode = code;
    const yearEl = document.getElementById('capitalYear');
    if (yearEl) yearEl.innerHTML = '';
  }
  loadCapitalAllocation();
}

async function loadCapitalAllocation() {
  const code = getCurrentCode();
  const wrap = document.getElementById('capitalAllocation');
  if (!code || !wrap) return;
  wrap.innerHTML = '<div class="empty">加载中...</div>';
  const yearEl = document.getElementById('capitalYear');
  const params = new URLSearchParams();
  if (yearEl?.value) params.set('year', yearEl.value);
  try {
    const res = await fetch('/api/stock/' + encodeURIComponent(code) + '/capital-allocation?' + params.toString());
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    renderCapitalYearSelect(data.years || [], data.selected_year);
    renderCapitalAllocation(data);
  } catch (e) {
    wrap.innerHTML = '<div class="empty" style="color:#ff4d4f">资本配置加载失败: ' + esc(e.message || '') + '</div>';
  }
}

function renderCapitalYearSelect(years, selectedYear) {
  const select = document.getElementById('capitalYear');
  if (!select || !years.length) return;
  const current = select.value || String(selectedYear || years[years.length - 1]);
  const descYears = [...years].sort((a, b) => b - a);
  select.innerHTML = descYears.map(y => `<option value="${esc(String(y))}">${esc(String(y))}</option>`).join('');
  select.value = descYears.map(String).includes(current) ? current : String(selectedYear || descYears[0]);
}

function fmtCapitalMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  const num = Number(value);
  return num.toLocaleString('zh-CN', {maximumFractionDigits: Math.abs(num) >= 100 ? 1 : 2}) + '亿';
}

function fmtCapitalPct(value) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString('zh-CN', {maximumFractionDigits: 2}) + '%';
}

function renderCapitalAllocation(data) {
  const wrap = document.getElementById('capitalAllocation');
  if (!wrap) return;
  if (data.message) {
    wrap.innerHTML = '<div class="empty">' + esc(data.message) + '</div>';
    return;
  }
  const selected = data.selected || {};
  const rows = data.rows || [];
  const signals = data.signals || [];
  const notes = data.notes || [];
  const cardHtml = [
    {name: '经营现金流', value: fmtCapitalMoney(selected.operating_cashflow), note: '自身造血'},
    {name: '投资收益现金', value: fmtCapitalMoney(selected.investment_income_cash), note: '投资回收'},
    {name: '融资流入', value: fmtCapitalMoney(selected.financing_sources), note: '借款/发债/股权融资'},
    {name: '资本开支', value: fmtCapitalMoney(selected.capex), note: fmtCapitalPct(selected.capex_to_ocf) + ' / OCF'},
    {name: '分红', value: fmtCapitalMoney(selected.dividend), note: '分红率 ' + fmtCapitalPct(selected.dividend_payout_ratio)},
    {name: '偿还债务', value: fmtCapitalMoney(selected.debt_repayment), note: fmtCapitalPct(selected.debt_repay_to_ocf) + ' / OCF'},
    {name: '自由现金流', value: fmtCapitalMoney(selected.free_cashflow), note: 'OCF - 资本开支'},
    {name: '经营剩余', value: fmtCapitalMoney(selected.remaining_after_allocation), note: '不含外部融资'},
    {name: '融资后剩余', value: fmtCapitalMoney(selected.financing_remaining_after_allocation), note: '含融资流入'},
  ].map(card => `
    <div class="capital-kpi">
      <div class="capital-kpi-name">${esc(card.name)}</div>
      <div class="capital-kpi-value">${esc(card.value)}</div>
      <div class="capital-kpi-note">${esc(card.note)}</div>
    </div>
  `).join('');

  const signalsHtml = signals.map(s => `
    <div class="capital-signal capital-${esc(s.level || 'neutral')}">
      <div class="capital-signal-title">${esc(s.text || '')}</div>
      <div class="capital-signal-detail">${esc(s.detail || '')}</div>
    </div>
  `).join('');

  const trendRows = rows.slice().reverse().map(r => `
    <tr>
      <td>${esc(String(r.year))}</td>
      <td>${esc(fmtCapitalMoney(r.operating_cashflow))}</td>
      <td>${esc(fmtCapitalMoney(r.investment_income_cash))}</td>
      <td>${esc(fmtCapitalMoney(r.financing_sources))}</td>
      <td>${esc(fmtCapitalMoney(r.capex))}</td>
      <td>${esc(fmtCapitalMoney(r.dividend))}</td>
      <td>${esc(fmtCapitalMoney(r.debt_repayment))}</td>
      <td>${esc(fmtCapitalMoney(r.remaining_after_allocation))}</td>
      <td>${esc(fmtCapitalMoney(r.financing_remaining_after_allocation))}</td>
      <td>${esc(fmtCapitalMoney(r.goodwill_change))}</td>
      <td>${esc(fmtCapitalPct(r.total_shares_change_pct))}</td>
    </tr>
  `).join('');

  wrap.innerHTML = `
    <div class="capital-grid">
      <div class="capital-main">
        <div class="capital-kpi-grid">${cardHtml}</div>
        <div class="capital-chart-card">
          <div class="capital-section-head">
            <h3>${esc(String(selected.year || '-'))} 年资金去向瀑布图</h3>
            <span>经营现金流 + 投资收益现金 + 融资流入 - 资本开支 - 分红 - 回购 - 偿债 = 融资后剩余</span>
          </div>
          <div id="capitalWaterfallChart" class="capital-chart"></div>
        </div>
        <div class="capital-table-card">
          <div class="capital-section-head">
            <h3>年度资本配置明细</h3>
            <span>单位：亿元</span>
          </div>
          <div class="capital-table-wrap">
            <table class="capital-table">
              <thead><tr><th>年份</th><th>经营现金流</th><th>投资收益现金</th><th>融资流入</th><th>资本开支</th><th>分红</th><th>偿债</th><th>经营剩余</th><th>融资后剩余</th><th>商誉变化</th><th>股本变化</th></tr></thead>
              <tbody>${trendRows}</tbody>
            </table>
          </div>
        </div>
      </div>
      <aside class="capital-side">
        <section>
          <h3>资本配置观察</h3>
          ${signalsHtml}
        </section>
        <section>
          <h3>融资与结构变化</h3>
          <div class="capital-side-row"><span>融资流入合计</span><b>${esc(fmtCapitalMoney(selected.financing_sources))}</b></div>
          <div class="capital-side-row"><span>借款/发债流入</span><b>${esc(fmtCapitalMoney(selected.debt_borrow))}</b></div>
          <div class="capital-side-row"><span>股权/其他融资</span><b>${esc(fmtCapitalMoney((Number(selected.equity_financing || 0) + Number(selected.other_financing || 0))))}</b></div>
          <div class="capital-side-row"><span>筹资现金流净额</span><b>${esc(fmtCapitalMoney(selected.finance_net))}</b></div>
          <div class="capital-side-row"><span>商誉变化</span><b>${esc(fmtCapitalMoney(selected.goodwill_change))}</b></div>
          <div class="capital-side-row"><span>总股本变化</span><b>${esc(fmtCapitalPct(selected.total_shares_change_pct))}</b></div>
        </section>
        <section>
          <h3>口径说明</h3>
          ${notes.map(n => `<p>${esc(n)}</p>`).join('')}
        </section>
      </aside>
    </div>
  `;
  renderCapitalWaterfallChart(selected);
}

function renderCapitalWaterfallChart(row) {
  const el = document.getElementById('capitalWaterfallChart');
  if (!el || !window.echarts) return;
  if (capitalAllocationChart) capitalAllocationChart.dispose();
  capitalAllocationChart = echarts.init(el);
  const ocf = Number(row.operating_cashflow || 0);
  const investmentIncomeCash = Number(row.investment_income_cash || 0);
  const debtIn = Number(row.debt_borrow || 0);
  const financingSources = Number(row.financing_sources || 0);
  let equityOtherIn = Number(row.equity_financing || 0) + Number(row.other_financing || 0);
  if (financingSources > debtIn + equityOtherIn) equityOtherIn = financingSources - debtIn;
  const capex = Number(row.capex || 0);
  const dividend = Number(row.dividend || 0);
  const buyback = Number(row.buyback || 0);
  const debt = Number(row.debt_repayment || 0);
  const remaining = Number(row.financing_remaining_after_allocation || 0);
  const labels = ['经营现金流', '投资收益现金', '借款/发债', '股权/其他融资', '资本开支', '分红', '回购', '偿债', '融资后剩余'];
  let running = 0;
  const helper = [];
  const values = [];
  const colors = [];

  function addStart(v, color) {
    helper.push(0);
    values.push(v);
    colors.push(color);
    running = v;
  }
  function addDeduct(v, color) {
    const next = running - v;
    helper.push(Math.min(running, next));
    values.push(Math.abs(v));
    colors.push(color);
    running = next;
  }
  function addPositive(v, color) {
    helper.push(Math.min(running, running + v));
    values.push(Math.abs(v));
    colors.push(color);
    running += v;
  }
  function addFinal(v, color) {
    helper.push(Math.min(0, v));
    values.push(Math.abs(v));
    colors.push(color);
  }

  addStart(ocf, '#4a6cf7');
  addPositive(investmentIncomeCash, '#16a34a');
  addPositive(debtIn, '#0ea5e9');
  addPositive(equityOtherIn, '#14b8a6');
  addDeduct(capex, '#d97706');
  addDeduct(dividend, '#9333ea');
  addDeduct(buyback, '#64748b');
  addDeduct(debt, '#dc2626');
  addFinal(remaining, remaining >= 0 ? '#16a34a' : '#dc2626');

  capitalAllocationChart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: {type: 'shadow'},
      formatter: params => {
        const idx = params[0].dataIndex;
        const raw = [ocf, investmentIncomeCash, debtIn, equityOtherIn, -capex, -dividend, -buyback, -debt, remaining][idx];
        return `${labels[idx]}<br/><b>${fmtCapitalMoney(raw)}</b>`;
      }
    },
    grid: {left: 58, right: 24, top: 24, bottom: 48},
    xAxis: {type: 'category', data: labels, axisLabel: {interval: 0}},
    yAxis: {type: 'value', name: '亿元'},
    series: [
      {type: 'bar', stack: 'total', itemStyle: {color: 'transparent'}, emphasis: {itemStyle: {color: 'transparent'}}, data: helper},
      {type: 'bar', stack: 'total', data: values.map((v, i) => ({value: v, itemStyle: {color: colors[i]}})), label: {show: true, position: 'top', formatter: p => fmtCapitalMoney([ocf, investmentIncomeCash, debtIn, equityOtherIn, -capex, -dividend, -buyback, -debt, remaining][p.dataIndex])}}
    ]
  });
}
