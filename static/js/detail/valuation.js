let valInstance = null;
let pbInstance = null;
let dyInstance = null;

async function loadValuation(days) {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const dom = document.getElementById('chartValuation');
  const sidebar = document.getElementById('valSidebar');
  const statusEl = document.getElementById('valStatus');
  statusEl.textContent = '加载中...';

  // Highlight active button
  document.querySelectorAll('#panel-valuation .btn-sm').forEach(b => {
    b.style.background = b.onclick && b.onclick.toString().includes(days) ? '#333' : '#f0f0f0';
    b.style.color = b.onclick && b.onclick.toString().includes(days) ? '#fff' : '#333';
  });

  try {
    const res = await fetch(`/api/stock/${code}/valuation?days=${days}`);
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (data.error) { statusEl.textContent = data.error; return; }

    // Filter by days
    const cutoff = days > 3650 ? '2000-01-01' : new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    const peFiltered = data.pe_data.filter(p => p.date >= cutoff);
    const priceFiltered = data.price_data.filter(p => p.date >= cutoff);

    // Build chart - use price dates as unified x-axis, align PE via date map
    const peMap = {}; peFiltered.forEach(p => peMap[p.date] = p.pe);
    const dates = priceFiltered.map(p => p.date);
    const peValues = dates.map(d => peMap[d] != null ? peMap[d] : null);
    const priceValues = priceFiltered.map(p => p.close);
    const pMin = priceValues.length ? Math.min(...priceValues) : null;
    const pMax = priceValues.length ? Math.max(...priceValues) : null;

    // Recalculate percentiles & stats from filtered PE data
    const filteredPeVals = peValues.filter(v => v != null).sort((a, b) => a - b);
    const n = filteredPeVals.length;
    const fp80 = n > 0 ? filteredPeVals[Math.floor(n * 0.8)] : null;
    const fp50 = n > 0 ? filteredPeVals[Math.floor(n * 0.5)] : null;
    const fp20 = n > 0 ? filteredPeVals[Math.floor(n * 0.2)] : null;
    const fmax = n > 0 ? filteredPeVals[n - 1] : null;
    const fmin = n > 0 ? filteredPeVals[0] : null;
    const favg = n > 0 ? +(filteredPeVals.reduce((a, b) => a + b, 0) / n).toFixed(2) : null;
    // Current PE and its percentile (优先使用腾讯实时 PE-TTM)
    const currentPE = data.realtime_pe || data.current_pe;
    const fpct = currentPE && n > 0 ? +(filteredPeVals.filter(v => v <= currentPE).length / n * 100).toFixed(2) : null;

    // Percentile lines
    const p80Line = dates.map(() => fp80);
    const p50Line = dates.map(() => fp50);
    const p20Line = dates.map(() => fp20);

    if (valInstance) valInstance.dispose();
    valInstance = echarts.init(dom);
    valInstance.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['PE-TTM', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) } },
      yAxis: [
        { type: 'value', name: 'PE', min: fmin ? +(fmin * 0.99).toFixed(2) : 0, max: fmax ? +(fmax * 1.01).toFixed(2) : undefined, splitNumber: 5 },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: 'PE-TTM', type: 'line', data: peValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#4a6cf7' }, label: { formatter: '{c}' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#389e0d' }, label: { formatter: '{c}' } }] } },
        { name: '80%分位', type: 'line', data: p80Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: p50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: p20Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    // Sidebar
    sidebar.innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">PE-TTM</div>
      <div style="margin-bottom:4px">当前值: <b style="color:#4a6cf7">${currentPE || '-'}</b></div>
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${fpct != null ? fpct + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">80%: <b>${fp80 || '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${fp50 || '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:8px">20%: <b>${fp20 || '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">最大: <b>${fmax || '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${favg || '-'}</b></div>
      <div style="color:#389e0d">最小: <b>${fmin || '-'}</b></div>`;

    // ===== PB 估值（扣商誉）=====
    const pbFiltered = (data.pb_data || []).filter(p => p.date >= cutoff);
    const pbMap = {}; pbFiltered.forEach(p => pbMap[p.date] = p.pb);
    const pbValues = dates.map(d => pbMap[d] != null ? pbMap[d] : null);
    const filteredPbVals = pbValues.filter(v => v != null).sort((a, b) => a - b);
    const pbn = filteredPbVals.length;
    const bp80 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.8)] : null;
    const bp50 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.5)] : null;
    const bp20 = pbn > 0 ? filteredPbVals[Math.floor(pbn * 0.2)] : null;
    const bmax = pbn > 0 ? filteredPbVals[pbn - 1] : null;
    const bmin = pbn > 0 ? filteredPbVals[0] : null;
    const bavg = pbn > 0 ? +(filteredPbVals.reduce((a, b) => a + b, 0) / pbn).toFixed(2) : null;
    // 优先使用计算 PB，实时 PB 仅作参考（腾讯行情 PB 可能与扣商誉后的计算值偏差较大）
    const currentPB = data.current_pb;
    const realtimePB = data.realtime_pb;
    const bpct = currentPB && pbn > 0 ? +(filteredPbVals.filter(v => v <= currentPB).length / pbn * 100).toFixed(2) : null;

    // PB Y轴 padding: fmin<1 时扩到 5%，PE 的 1% 对 PB 太紧
    const pbPad = (bmin != null && bmin < 1) ? 0.05 : 0.01;
    const pb80Line = dates.map(() => bp80);
    const pb50Line = dates.map(() => bp50);
    const pb20Line = dates.map(() => bp20);

    if (pbInstance) pbInstance.dispose();
    pbInstance = echarts.init(document.getElementById('chartPb'));
    pbInstance.setOption({
      tooltip: { trigger: 'axis' },
      legend: { data: ['PB(扣商誉)', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) }, boundaryGap: false },
      yAxis: [
        { type: 'value', name: 'PB', min: bmin ? +(bmin * (1 - pbPad)).toFixed(2) : 0, max: bmax ? +(bmax * (1 + pbPad)).toFixed(2) : undefined, splitNumber: 5 },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: 'PB(扣商誉)', type: 'line', data: pbValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', connectNulls: false, markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#4a6cf7' }, label: { formatter: '{c}' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#389e0d' }, label: { formatter: '{c}' } }] } },
        { name: '80%分位', type: 'line', data: pb80Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: pb50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: pb20Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    // PB 侧边栏 — 显示计算 PB（主值）和实时 PB（参考）
    const realtimePBText = (realtimePB != null && realtimePB !== currentPB) 
      ? `<div style="font-size:11px;color:#999;margin-top:2px">实时 PB: <b style="color:#999">${realtimePB.toFixed(2)}</b>（腾讯行情）</div>` 
      : '';
    document.getElementById('pbSidebar').innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">PB(扣商誉)</div>
      <div style="margin-bottom:4px">计算 PB: <b style="color:#4a6cf7">${currentPB ? currentPB.toFixed(2) : '-'}</b></div>
      ${realtimePBText}
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${bpct != null ? bpct + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">80%: <b>${bp80 || '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${bp50 || '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:8px">20%: <b>${bp20 || '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:2px">最大: <b>${bmax || '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${bavg || '-'}</b></div>
      <div style="color:#389e0d">最小: <b>${bmin || '-'}</b></div>`;

    // ===== 股息率估值 =====
    const dyFiltered = (data.dividend_yield_data || []).filter(p => p.date >= cutoff);
    const dyMap = {}; dyFiltered.forEach(p => dyMap[p.date] = p.dividend_yield);
    const dyValues = dates.map(d => dyMap[d] != null ? dyMap[d] : null);
    const filteredDyVals = dyValues.filter(v => v != null).sort((a, b) => a - b);
    const dyn = filteredDyVals.length;
    const dy80 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.8)] : null;
    const dy50 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.5)] : null;
    const dy20 = dyn > 0 ? filteredDyVals[Math.floor(dyn * 0.2)] : null;
    const dymax = dyn > 0 ? filteredDyVals[dyn - 1] : null;
    const dymin = dyn > 0 ? filteredDyVals[0] : null;
    const dyavg = dyn > 0 ? +(filteredDyVals.reduce((a, b) => a + b, 0) / dyn).toFixed(2) : null;
    const currentDY = data.current_dividend_yield || (dyFiltered.length ? dyFiltered[dyFiltered.length - 1].dividend_yield : null);
    const dypct = currentDY && dyn > 0 ? +(filteredDyVals.filter(v => v <= currentDY).length / dyn * 100).toFixed(2) : null;
    const dy80Line = dates.map(() => dy80);
    const dy50Line = dates.map(() => dy50);
    const dy20Line = dates.map(() => dy20);
    const dyPad = (dymin != null && dymin < 1) ? 0.08 : 0.04;

    if (dyInstance) dyInstance.dispose();
    dyInstance = echarts.init(document.getElementById('chartDividendYield'));
    dyInstance.setOption({
      tooltip: {
        trigger: 'axis',
        valueFormatter: v => v == null ? '-' : Number(v).toFixed(2) + '%'
      },
      legend: { data: ['股息率', '80%分位', '50%分位', '20%分位', '股价(前复权)'], top: 4 },
      grid: { left: 60, right: 80, top: 40, bottom: 30 },
      xAxis: { type: 'category', data: dates, axisLabel: { formatter: v => v.slice(0, 7) }, boundaryGap: false },
      yAxis: [
        { type: 'value', name: '股息率(%)', min: dymin ? Math.max(0, +(dymin * (1 - dyPad)).toFixed(2)) : 0, max: dymax ? +(dymax * (1 + dyPad)).toFixed(2) : undefined, splitNumber: 5, axisLabel: { formatter: v => v + '%' } },
        { type: 'value', name: '股价(元)', splitLine: { show: false }, min: pMin ? +(pMin * 0.99).toFixed(2) : undefined, max: pMax ? +(pMax * 1.01).toFixed(2) : undefined, splitNumber: 5 }
      ],
      series: [
        { name: '股息率', type: 'line', data: dyValues, yAxisIndex: 0, lineStyle: { color: '#4a6cf7', width: 2 }, itemStyle: { color: '#4a6cf7' }, symbol: 'none', connectNulls: false, markPoint: { data: [{ type: 'max', name: '最高', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#52c41a' }, label: { formatter: p => Number(p.value).toFixed(2) + '%' } }, { type: 'min', name: '最低', symbol: 'pin', symbolSize: 40, itemStyle: { color: '#ff4d4f' }, label: { formatter: p => Number(p.value).toFixed(2) + '%' } }] } },
        { name: '80%分位', type: 'line', data: dy80Line, yAxisIndex: 0, lineStyle: { color: '#389e0d', type: 'dashed', width: 1 }, itemStyle: { color: '#389e0d' }, symbol: 'none' },
        { name: '50%分位', type: 'line', data: dy50Line, yAxisIndex: 0, lineStyle: { color: '#666', type: 'dashed', width: 1 }, itemStyle: { color: '#666' }, symbol: 'none' },
        { name: '20%分位', type: 'line', data: dy20Line, yAxisIndex: 0, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, itemStyle: { color: '#cf1322' }, symbol: 'none' },
        { name: '股价(前复权)', type: 'line', data: priceValues, yAxisIndex: 1, lineStyle: { color: '#fa8c16', width: 1.5 }, itemStyle: { color: '#fa8c16' }, symbol: 'none' },
      ]
    });

    document.getElementById('dySidebar').innerHTML = `
      <div style="color:#4a6cf7;font-weight:700;margin-bottom:8px">股息率</div>
      <div style="margin-bottom:4px">当前值: <b style="color:#4a6cf7">${currentDY != null ? currentDY.toFixed(2) + '%' : '-'}</b></div>
      <div style="margin-bottom:8px">分位点: <b style="color:#4a6cf7">${dypct != null ? dypct + '%' : '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:2px">80%: <b>${dy80 != null ? dy80.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#666;margin-bottom:2px">50%: <b>${dy50 != null ? dy50.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#cf1322;margin-bottom:8px">20%: <b>${dy20 != null ? dy20.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#389e0d;margin-bottom:2px">最大: <b>${dymax != null ? dymax.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#333;margin-bottom:2px">平均: <b>${dyavg != null ? dyavg.toFixed(2) + '%' : '-'}</b></div>
      <div style="color:#cf1322">最小: <b>${dymin != null ? dymin.toFixed(2) + '%' : '-'}</b></div>`;

    statusEl.textContent = `${peFiltered.length} 个数据点`;
    statusEl.style.color = '#52c41a';
  } catch (e) {
    statusEl.textContent = '加载失败';
    statusEl.style.color = '#ff4d4f';
  }
}

// ==================== 列表页 ====================
