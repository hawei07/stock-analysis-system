let divYearsPopulated = false;

async function loadDividends(code) {
  if (!code) return;
  try {
    const from = document.getElementById('divFromYear').value;
    const to = document.getElementById('divToYear').value;
    let url = '/api/stock/' + code + '/dividends';
    const params = [];
    if (from) params.push('start_year=' + from);
    if (to) params.push('end_year=' + to);
    if (params.length) url += '?' + params.join('&');
    const res = await fetch(url);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    
    // 首次加载时用全部年份数据填充下拉框
    if (!divYearsPopulated && !from && !to) {
      populateDivYearSelects(data);
    }
    
    renderDividendsChart(data);
  } catch (e) {
    showToast('加载分红数据失败', 'error');
  }
}

function populateDivYearSelects(data) {
  const years = data.map(d => d.fiscal_year).sort((a, b) => a - b);
  if (years.length === 0) return;
  const fromSelect = document.getElementById('divFromYear');
  const toSelect = document.getElementById('divToYear');
  fromSelect.innerHTML = '<option value="">全部</option>';
  toSelect.innerHTML = '<option value="">全部</option>';
  years.forEach(y => {
    fromSelect.innerHTML += `<option value="${y}">${y}</option>`;
    toSelect.innerHTML += `<option value="${y}">${y}</option>`;
  });
  fromSelect.value = years[0];
  toSelect.value = years[years.length - 1];
  divYearsPopulated = true;
}

function onDivYearChange() {
  loadDividends(getCurrentCode());
}

function resetDivYears() {
  const fromSelect = document.getElementById('divFromYear');
  const toSelect = document.getElementById('divToYear');
  const fromOpts = fromSelect.options;
  const toOpts = toSelect.options;
  if (fromOpts.length > 1) fromSelect.value = fromOpts[1].value;
  if (toOpts.length > 1) toSelect.value = toOpts[toOpts.length - 1].value;
  loadDividends(getCurrentCode());
}

function renderDividendsChart(data) {
  const dom = document.getElementById('chartDividends');
  if (!dom) return;
  if (chartInstance) chartInstance.dispose();

  const years = data.map(d => d.fiscal_year + '');
  const netProfits = data.map(d => d.net_profit);
  const dividends = data.map(d => d.dividend_amount);
  const payoutRatios = data.map(d => d.net_profit > 0 ? +(d.dividend_amount / d.net_profit * 100).toFixed(1) : null);
  const showLabel = data.length <= 15;

  chartInstance = echarts.init(dom);
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: function(params) {
        const year = params[0].axisValue;
        let html = '<strong>' + year + '</strong><br/>';
        params.forEach(p => {
          if (p.seriesName === '分红比例') {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value !== null ? p.value + '%' : '-') + '<br/>';
          } else {
            html += p.marker + ' ' + p.seriesName + ': ' + (p.value !== null ? p.value.toFixed(2) + ' 亿元' : '-') + '<br/>';
          }
        });
        return html;
      }
    },
    legend: {
      data: ['净利润', '分红金额', '分红比例'],
      top: 4
    },
    dataZoom: [
      { type: 'slider', start: data.length > 15 ? Math.max(0, 100 - (15 / data.length * 100)) : 0, end: 100, height: 20, bottom: 10 },
      { type: 'inside' }
    ],
    grid: {
      left: 60,
      right: 80,
      top: 60,
      bottom: data.length > 15 ? 50 : 40
    },
    xAxis: {
      type: 'category',
      data: years,
      name: '财年',
      axisLabel: { fontSize: 12 }
    },
    yAxis: [
      {
        type: 'value',
        name: '金额（亿元）',
        axisLabel: { fontSize: 12 }
      },
      {
        type: 'value',
        name: '分红比例（%）',
        axisLabel: { fontSize: 12 },
        splitLine: { show: false }
      }
    ],
    series: [
      {
        name: '净利润',
        type: 'bar',
        yAxisIndex: 0,
        data: netProfits,
        barMaxWidth: 40,
        itemStyle: { color: '#4a6cf7', borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          formatter: p => p.value >= 100 ? p.value.toFixed(0) : p.value.toFixed(2)
        }
      },
      {
        name: '分红金额',
        type: 'bar',
        yAxisIndex: 0,
        data: dividends,
        barMaxWidth: 40,
        itemStyle: { color: '#52c41a', borderRadius: [4, 4, 0, 0] },
        label: {
          show: true,
          position: 'top',
          fontSize: 11,
          formatter: p => p.value >= 100 ? p.value.toFixed(0) : p.value.toFixed(2)
        }
      },
      {
        name: '分红比例',
        type: 'line',
        yAxisIndex: 1,
        data: payoutRatios,
        lineStyle: { color: '#fa8c16', width: 2.5 },
        itemStyle: { color: '#fa8c16' },
        symbol: 'circle',
        symbolSize: 6,
        label: {
          show: true,
          position: 'top',
          fontSize: 10,
          color: '#fa8c16',
          formatter: p => p.value !== null ? p.value + '%' : ''
        }
      }
    ]
  };
  chartInstance.setOption(option);
  window.addEventListener('resize', () => {
    chartInstance && chartInstance.resize();
    valInstance && valInstance.resize();
    pbInstance && pbInstance.resize();
  });
}

// ==================== 融资 ====================

