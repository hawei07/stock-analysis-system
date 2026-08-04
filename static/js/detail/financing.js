let financingInstance = null;

async function loadFinancing(code) {
  if (!code) return;
  const statusEl = document.getElementById('financingStatus');
  if (statusEl) statusEl.textContent = '加载中...';
  try {
    const res = await fetch('/api/stock/' + code + '/financing');
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    renderFinancingChart(data.annual || []);
    renderFinancingTable(data.details || []);
    if (statusEl) statusEl.textContent = data.source || '';
  } catch (e) {
    if (statusEl) statusEl.textContent = '';
    renderFinancingChart([]);
    renderFinancingTable([]);
    showToast(e.message || '加载融资数据失败', 'error');
  }
}

function financingMoney(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  return (Number(value) / 1e8).toFixed(2) + '亿元';
}

function financingShares(value) {
  if (value == null || Number.isNaN(Number(value))) return '--';
  const n = Number(value);
  return n >= 1e8 ? (n / 1e8).toFixed(2) + '亿股' : (n / 1e4).toFixed(2) + '万股';
}

function renderFinancingChart(rows) {
  const dom = document.getElementById('chartFinancing');
  if (!dom) return;
  if (financingInstance) financingInstance.dispose();
  financingInstance = echarts.init(dom);

  if (!rows.length) {
    financingInstance.setOption({
      title: { text: '暂无融资数据', left: 'center', top: 'center', textStyle: { fontSize: 14, color: '#999' } },
      xAxis: { show: false },
      yAxis: { show: false },
      series: []
    }, true);
    return;
  }

  const years = rows.map(r => r.year);
  const financing = rows.map(r => +(Number(r.financing_amount || 0) / 1e8).toFixed(2));
  const dividends = rows.map(r => +(Number(r.dividend_amount || 0) / 1e8).toFixed(2));
  const ratios = rows.map(r => r.ratio == null ? null : Number(r.ratio));
  const showLabel = rows.length <= 18;

  financingInstance.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter(params) {
        const year = params[0].axisValue;
        let html = '<strong>' + year + '</strong><br/>';
        params.forEach(p => {
          if (p.seriesName === '分红融资比') {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value == null ? '-' : Number(p.value).toFixed(2) + '%') + '<br/>';
          } else {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value == null ? '-' : Number(p.value).toFixed(2) + '亿元') + '<br/>';
          }
        });
        return html;
      }
    },
    legend: { top: 4, data: ['A股-累计融资额', 'A股-累计分红', 'A股-累计分红融资比'] },
    dataZoom: [
      { type: 'slider', start: rows.length > 18 ? Math.max(0, 100 - (18 / rows.length * 100)) : 0, end: 100, height: 20, bottom: 10 },
      { type: 'inside' }
    ],
    grid: { left: 64, right: 82, top: 52, bottom: rows.length > 18 ? 54 : 42 },
    xAxis: { type: 'category', data: years, axisLabel: { fontSize: 12 } },
    yAxis: [
      { type: 'value', name: '累计融资/分红', axisLabel: { formatter: v => v + '亿' } },
      { type: 'value', name: '分红融资比', axisLabel: { formatter: v => v + '%' }, splitLine: { show: false } }
    ],
    series: [
      {
        name: 'A股-累计融资额',
        type: 'bar',
        data: financing,
        barMaxWidth: 38,
        itemStyle: { color: '#73b976', borderRadius: [4, 4, 0, 0] },
        label: { show: showLabel, position: 'top', fontSize: 10, formatter: p => p.value ? p.value.toFixed(2) + '亿' : '' }
      },
      {
        name: 'A股-累计分红',
        type: 'bar',
        data: dividends,
        barMaxWidth: 38,
        itemStyle: { color: '#ff6b73', borderRadius: [4, 4, 0, 0] },
        label: { show: showLabel, position: 'top', fontSize: 10, formatter: p => p.value ? p.value.toFixed(2) + '亿' : '' }
      },
      {
        name: 'A股-累计分红融资比',
        type: 'line',
        yAxisIndex: 1,
        data: ratios,
        smooth: false,
        symbol: 'circle',
        symbolSize: 7,
        lineStyle: { color: '#2f8cff', width: 2 },
        itemStyle: { color: '#2f8cff' },
        label: { show: showLabel, position: 'top', fontSize: 10, color: '#2f8cff', formatter: p => p.value == null ? '' : p.value.toFixed(1) + '%' }
      }
    ]
  }, true);
}

function renderFinancingTable(rows) {
  const body = document.getElementById('financingTableBody');
  const empty = document.getElementById('financingEmpty');
  if (!body || !empty) return;
  empty.style.display = rows.length ? 'none' : 'block';
  body.innerHTML = rows.map(r => `
    <tr>
      <td>${esc(r.date || '--')}</td>
      <td>${esc(r.type || '--')}</td>
      <td class="num">${r.issue_price == null ? '--' : Number(r.issue_price).toFixed(2) + '元'}</td>
      <td class="num">${financingShares(r.issue_shares)}</td>
      <td class="num">${financingMoney(r.amount)}</td>
      <td>${esc(r.method || '--')}</td>
      <td>${esc(r.target || '--')}</td>
      <td>${esc(r.price_method || '--')}</td>
    </tr>
  `).join('');
}

// ==================== 股东 ====================

