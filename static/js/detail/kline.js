let klineInstance = null;

function calcEMA(values, period) {
  const k = 2 / (period + 1);
  const ema = [];
  values.forEach((value, index) => {
    if (index === 0) {
      ema.push(value);
    } else {
      ema.push(value * k + ema[index - 1] * (1 - k));
    }
  });
  return ema;
}

function calcMACD(closes) {
  const ema12 = calcEMA(closes, 12);
  const ema26 = calcEMA(closes, 26);
  const dif = closes.map((_, i) => ema12[i] - ema26[i]);
  const dea = calcEMA(dif, 9);
  const macd = dif.map((value, i) => 2 * (value - dea[i]));
  return { dif, dea, macd };
}

function formatTurnover(value) {
  if (!Number.isFinite(value)) return '-';
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(2)} 亿`;
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(2)} 万`;
  return value.toFixed(0);
}

function currentKlinePeriod() {
  return document.querySelector('#chartKlinePeriod button.active')?.dataset.period || 'day';
}

function setKlinePeriod(period) {
  document.querySelectorAll('#chartKlinePeriod button').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.period === period);
  });
  loadKline();
}

async function loadKline() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const days = document.getElementById('chartPeriod').value;
  const period = currentKlinePeriod();
  const periodTextMap = { day: '日K', week: '周K', month: '月K', quarter: '季K', year: '年K' };
  const dom = document.getElementById('chartKline');
  const statusEl = document.getElementById('chartStatus');
  statusEl.textContent = '加载中...';

  try {
    const res = await fetch(`/api/stock/${code}/kline?days=${days}&period=${period}`);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (data.error) { statusEl.textContent = data.error; return; }
    if (!data || data.length === 0) { statusEl.textContent = '无数据'; return; }

    const dates = data.map(d => d.date);
    const ohlc = data.map(d => [d.open, d.close, d.low, d.high]);
    const volumes = data.map(d => d.volume);
    const amounts = data.map(d => d.amount || (d.volume * d.close * 100));
    const closes = data.map(d => d.close);
    const macdData = calcMACD(closes);
    const highest = data.reduce((best, item, index) => item.high > best.value ? { value: item.high, index } : best, { value: -Infinity, index: 0 });
    const lowest = data.reduce((best, item, index) => item.low < best.value ? { value: item.low, index } : best, { value: Infinity, index: 0 });

    if (klineInstance) klineInstance.dispose();
    klineInstance = echarts.init(dom);

    klineInstance.setOption({
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
        formatter: function(params) {
          const d = data[params[0].dataIndex];
          return `<strong>${d.date} ${periodTextMap[period]}</strong><br/>
            开盘: ${d.open.toFixed(2)}<br/>
            收盘: ${d.close.toFixed(2)}<br/>
            最高: ${d.high.toFixed(2)}<br/>
            最低: ${d.low.toFixed(2)}<br/>
            成交量: ${(d.volume / 10000).toFixed(0)} 万手<br/>
            成交额: ${formatTurnover(d.amount || (d.volume * d.close * 100))}<br/>
            DIF: ${macdData.dif[params[0].dataIndex].toFixed(3)}<br/>
            DEA: ${macdData.dea[params[0].dataIndex].toFixed(3)}<br/>
            MACD: ${macdData.macd[params[0].dataIndex].toFixed(3)}`;
        }
      },
      grid: [
        { left: '8%', right: '8%', top: '5%', height: '52%' },
        { left: '8%', right: '8%', top: '64%', height: '14%' },
        { left: '8%', right: '8%', top: '84%', height: '11%' }
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false } },
        { type: 'category', data: dates, gridIndex: 2, axisLabel: { formatter: v => v.slice(5) } }
      ],
      yAxis: [
        { type: 'value', gridIndex: 0, scale: true, splitArea: { show: true } },
        { type: 'value', gridIndex: 1, axisLabel: { formatter: v => (v / 10000).toFixed(0) + '万' } },
        {
          type: 'value',
          gridIndex: 1,
          position: 'right',
          splitLine: { show: false },
          axisLabel: { formatter: v => formatTurnover(v).replace(' ', '') }
        },
        {
          type: 'value',
          gridIndex: 2,
          scale: true,
          splitLine: { show: true },
          axisLabel: { formatter: v => v.toFixed(2) }
        }
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: ohlc,
          xAxisIndex: 0, yAxisIndex: 0,
          itemStyle: { color: '#cf1322', color0: '#389e0d', borderColor: '#cf1322', borderColor0: '#389e0d' },
          markPoint: {
            symbol: 'circle',
            symbolSize: 1,
            label: { color: chartTextColor(), fontSize: 12, fontWeight: 600, formatter: p => p.value },
            data: [
              {
                name: '最高价',
                coord: [dates[highest.index], highest.value],
                value: highest.value.toFixed(2),
                label: { position: 'top' },
                itemStyle: { color: 'transparent' }
              },
              {
                name: '最低价',
                coord: [dates[lowest.index], lowest.value],
                value: lowest.value.toFixed(2),
                label: { position: 'bottom' },
                itemStyle: { color: 'transparent' }
              }
            ]
          },
        },
        {
          name: '成交量',
          type: 'bar',
          data: volumes,
          xAxisIndex: 1, yAxisIndex: 1,
          itemStyle: {
            color: function(p) {
              const d = data[p.dataIndex];
              return d.close >= d.open ? '#cf1322' : '#389e0d';
            }
          }
        },
        {
          name: '成交额',
          type: 'line',
          data: amounts,
          xAxisIndex: 1, yAxisIndex: 2,
          symbol: 'none',
          smooth: true,
          lineStyle: { color: '#5470c6', width: 1.8 }
        },
        {
          name: 'MACD',
          type: 'bar',
          data: macdData.macd,
          xAxisIndex: 2, yAxisIndex: 3,
          barMaxWidth: 8,
          itemStyle: {
            color: function(p) {
              return p.value >= 0 ? '#cf1322' : '#389e0d';
            }
          }
        },
        {
          name: 'DIF',
          type: 'line',
          data: macdData.dif,
          xAxisIndex: 2, yAxisIndex: 3,
          symbol: 'none',
          lineStyle: { color: '#fa8c16', width: 1.4 }
        },
        {
          name: 'DEA',
          type: 'line',
          data: macdData.dea,
          xAxisIndex: 2, yAxisIndex: 3,
          symbol: 'none',
          lineStyle: { color: '#4a6cf7', width: 1.4 }
        }
      ]
    });
    statusEl.textContent = `${periodTextMap[period]} · ${data.length} 条数据`;
    statusEl.style.color = '#52c41a';
  } catch (e) {
    statusEl.textContent = '加载失败';
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 估值分析 ====================

