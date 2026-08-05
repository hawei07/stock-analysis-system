function mountFlowPanel() {
  const body = document.getElementById('flowsBody');
  const sourcePanel = body ? body.closest('.panel') : null;
  const modalBody = document.getElementById('flowModalBody');
  if (!sourcePanel || !modalBody || sourcePanel.dataset.mounted === '1') return;
  sourcePanel.dataset.mounted = '1';
  Array.from(sourcePanel.childNodes).forEach(node => modalBody.appendChild(node));
  const innerHeader = modalBody.querySelector('.panel-header');
  if (innerHeader) innerHeader.remove();
  sourcePanel.remove();
}

function openFlowModal() {
  document.getElementById('flowModalOverlay').classList.add('active');
  loadFlows();
  const flowDate = document.getElementById('flowDate');
  if (flowDate && !flowDate.value) flowDate.value = new Date().toISOString().slice(0, 10);
}

function closeFlowModal() {
  document.getElementById('flowModalOverlay').classList.remove('active');
}

function openFeeConfigModal() {
  document.getElementById('feeConfigModalOverlay').classList.add('active');
  fillFeeConfigForm();
}

function closeFeeConfigModal() {
  document.getElementById('feeConfigModalOverlay').classList.remove('active');
}

function fillFeeConfigForm() {
  document.getElementById('commissionRateInput').value = (Number(latestFeeConfig.commission_rate || 0) * 100).toFixed(4);
  document.getElementById('minCommissionInput').value = Number(latestFeeConfig.min_commission || 0).toFixed(2);
  document.getElementById('stampTaxRateInput').value = (Number(latestFeeConfig.stamp_tax_rate || 0) * 100).toFixed(4);
  document.getElementById('transferFeeRateInput').value = (Number(latestFeeConfig.transfer_fee_rate || 0) * 100).toFixed(4);
}

async function loadFeeConfig() {
  try {
    const data = await StockApi.getJson('/api/portfolio/fee-config');
    if (data.error) throw new Error(data.error || '加载费率失败');
    latestFeeConfig = data;
  } catch (e) {
    showToast(e.message || '加载费率失败', 'error');
  }
}

async function saveFeeConfig() {
  const payload = {
    commission_rate: Number(document.getElementById('commissionRateInput').value || 0) / 100,
    min_commission: Number(document.getElementById('minCommissionInput').value || 0),
    stamp_tax_rate: Number(document.getElementById('stampTaxRateInput').value || 0) / 100,
    transfer_fee_rate: Number(document.getElementById('transferFeeRateInput').value || 0) / 100
  };
  try {
    const data = await StockApi.putJson('/api/portfolio/fee-config', payload);
    if (data.error) throw new Error(data.error || '保存费率失败');
    latestFeeConfig = data;
    closeFeeConfigModal();
    updateTradeFeeEstimate();
    showToast('交易费率已保存', 'success');
  } catch (e) {
    showToast(e.message || '保存费率失败', 'error');
  }
}

async function openAllocationModal() {
  document.getElementById('allocationModalOverlay').classList.add('active');
  if (!latestPortfolioData.positions || !latestPortfolioData.positions.length) {
    await loadPortfolio();
  }
  setTimeout(renderAllocationPie, 0);
}

function closeAllocationModal() {
  document.getElementById('allocationModalOverlay').classList.remove('active');
}

function renderAllocationPie() {
  const el = document.getElementById('allocationPie');
  if (!el) return;
  if (!allocationChart) allocationChart = echarts.init(el);
  const summary = latestPortfolioData.summary || {};
  const rows = (latestPortfolioData.positions || [])
    .filter(p => Number(p.market_value) > 0)
    .map(p => ({
      name: p.name,
      value: Number(p.market_value),
      allocation: p.allocation_pct
    }));
  if (Number(summary.cash_amount || 0) > 0) {
    rows.push({
      name: '现金',
      value: Number(summary.cash_amount),
      allocation: summary.cash_allocation_pct
    });
  }
  if (!rows.length) {
    allocationChart.setOption({
      title: {text: '暂无资产数据', left: 'center', top: 'center', textStyle: {fontSize: 14, color: '#999'}},
      series: []
    }, true);
    return;
  }
  allocationChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: p => `${p.name}<br/>${money(p.value)} (${p.percent.toFixed(2)}%)`
    },
    legend: {type: 'scroll', orient: 'vertical', right: 8, top: 24, bottom: 24},
    series: [{
      name: '资产占比',
      type: 'pie',
      radius: ['42%', '70%'],
      center: ['40%', '52%'],
      minAngle: 3,
      avoidLabelOverlap: true,
      data: rows,
      label: {
        formatter: p => `${p.name}\n${p.percent.toFixed(2)}%`
      },
      emphasis: {
        itemStyle: {shadowBlur: 12, shadowOffsetX: 0, shadowColor: 'rgba(0,0,0,.18)'}
      }
    }]
  }, true);
  allocationChart.resize();
}

function money(v) {
  return StockFormat.number(v, {empty: '--', minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function dividendHistoryMoney(v) {
  return StockFormat.number(v, {empty: '--', minimumFractionDigits: 3, maximumFractionDigits: 3});
}

function maskedMoney() {
  return '******';
}

function privateMoney(v) {
  return amountPrivacyMode ? maskedMoney() : money(v);
}

function signedPrivateMoney(v) {
  if (v == null || Number.isNaN(Number(v))) return '--';
  if (amountPrivacyMode) return maskedMoney();
  const n = Number(v);
  return (n > 0 ? '+' : '') + money(n);
}

function signedPct(v) {
  return StockFormat.signedPercent(v, {empty: '--', minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function profitClass(v) {
  const n = Number(v);
  if (Number.isNaN(n) || n === 0) return '';
  return n > 0 ? 'profit-positive' : 'profit-negative';
}

function updateAmountPrivacyButton() {
  const btn = document.getElementById('amountPrivacyToggle');
  if (btn) {
    btn.innerHTML = amountPrivacyMode
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18"></path><path d="M10.6 10.6a2 2 0 0 0 2.8 2.8"></path><path d="M9.9 4.2A10.8 10.8 0 0 1 12 4c5 0 8.8 3.1 10 8a11.8 11.8 0 0 1-2.1 4.1"></path><path d="M6.1 6.1A11.8 11.8 0 0 0 2 12c1.2 4.9 5 8 10 8a10.8 10.8 0 0 0 4.3-.9"></path></svg>'
      : '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
    btn.setAttribute('aria-label', amountPrivacyMode ? '显示金额' : '隐藏金额');
    btn.title = amountPrivacyMode ? '显示金额' : '隐藏金额';
    btn.classList.toggle('active', amountPrivacyMode);
  }
}

function toggleAmountPrivacy() {
  amountPrivacyMode = !amountPrivacyMode;
  localStorage.setItem('portfolioAmountPrivacy', amountPrivacyMode ? 'hidden' : 'visible');
  updateAmountPrivacyButton();
  renderSummary(latestPortfolioData.summary || {});
}

function plain(v) {
  return StockFormat.number(v, {empty: '--', maximumFractionDigits: 4});
}

function price2(v) {
  if (v == null || Number.isNaN(Number(v))) return '';
  return Number(v).toFixed(2);
}

function inferDomesticMarket(code, row = {}) {
  const market = String(row.market || '').toUpperCase();
  if (['SH', 'SZ', 'BJ'].includes(market)) return true;
  const value = String(code || '').trim();
  return /^(6|0|3|8)\d{5}$/.test(value);
}

function calculateTradeFeeEstimate(amount, type, isDomestic) {
  if (!isDomestic || !amount || amount <= 0) {
    return {commission: 0, stamp_tax: 0, transfer_fee: 0, total_fee: 0, cash_delta: type === 'buy' ? -amount : amount};
  }
  const commissionRaw = amount * Number(latestFeeConfig.commission_rate || 0);
  const minCommission = Number(latestFeeConfig.min_commission || 0);
  const commission = commissionRaw > 0 && commissionRaw < minCommission ? minCommission : commissionRaw;
  const stampTax = type === 'sell' ? amount * Number(latestFeeConfig.stamp_tax_rate || 0) : 0;
  const transferFee = amount * Number(latestFeeConfig.transfer_fee_rate || 0);
  const totalFee = commission + stampTax + transferFee;
  return {
    commission,
    stamp_tax: stampTax,
    transfer_fee: transferFee,
    total_fee: totalFee,
    cash_delta: type === 'buy' ? -(amount + totalFee) : amount - totalFee
  };
}

function updateTradeFeeEstimate() {
  const el = document.getElementById('tradeFeeEstimate');
  if (!el) return;
  const type = document.getElementById('tradeType').value;
  const code = document.getElementById('tradeCodeInput').value.trim();
  const row = (latestPortfolioData.positions || []).find(p => String(p.code) === String(code)) || {};
  const shares = Number(document.getElementById('tradeSharesInput').value || 0);
  const price = Number(document.getElementById('tradePriceInput').value || 0);
  const amount = shares * price;
  if (!shares || !price) {
    el.textContent = '';
    return;
  }
  const fee = calculateTradeFeeEstimate(amount, type, inferDomesticMarket(code, row));
  const cashText = type === 'buy' ? `需扣现金 ${money(Math.abs(fee.cash_delta))}` : `预计到账 ${money(fee.cash_delta)}`;
  el.textContent = `成交金额 ${money(amount)}；税费 ${money(fee.total_fee)}（佣金 ${money(fee.commission)}，印花税 ${money(fee.stamp_tax)}，过户费 ${money(fee.transfer_fee)}）；${cashText}`;
}

function esc(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
