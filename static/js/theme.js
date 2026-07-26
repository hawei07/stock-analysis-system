(function() {
  const saved = localStorage.getItem('stockTheme') || 'light';
  document.documentElement.dataset.theme = saved === 'dark' ? 'dark' : 'light';
})();

function isDarkTheme() {
  return document.documentElement.dataset.theme === 'dark';
}

function chartTextColor() {
  return isDarkTheme() ? '#d7dde8' : '#333';
}

function chartAxisColor() {
  return isDarkTheme() ? '#8f9aaa' : '#666';
}

function chartSplitColor() {
  return isDarkTheme() ? '#2d3748' : '#e8e8e8';
}

function applyChartThemeOption(option) {
  if (!option || typeof option !== 'object') return option;
  option.backgroundColor = isDarkTheme() ? '#171d27' : '#fff';
  option.textStyle = { color: chartTextColor(), ...(option.textStyle || {}) };
  if (option.tooltip) {
    const tooltips = Array.isArray(option.tooltip) ? option.tooltip : [option.tooltip];
    tooltips.forEach(t => {
      t.backgroundColor = isDarkTheme() ? 'rgba(23,29,39,.96)' : 'rgba(255,255,255,.96)';
      t.borderColor = isDarkTheme() ? '#2d3748' : '#e8e8e8';
      t.textStyle = { color: chartTextColor(), ...(t.textStyle || {}) };
    });
  }
  const axes = [
    ...(Array.isArray(option.xAxis) ? option.xAxis : option.xAxis ? [option.xAxis] : []),
    ...(Array.isArray(option.yAxis) ? option.yAxis : option.yAxis ? [option.yAxis] : [])
  ];
  axes.forEach(axis => {
    axis.axisLabel = { color: chartAxisColor(), ...(axis.axisLabel || {}) };
    axis.axisLine = { lineStyle: { color: chartSplitColor(), ...((axis.axisLine || {}).lineStyle || {}) }, ...(axis.axisLine || {}) };
    axis.splitLine = { lineStyle: { color: chartSplitColor(), ...((axis.splitLine || {}).lineStyle || {}) }, ...(axis.splitLine || {}) };
    if (axis.splitArea) {
      axis.splitArea = {
        areaStyle: {
          color: isDarkTheme() ? ['#171d27', '#1b2330'] : ['rgba(250,250,250,.35)', 'rgba(245,247,250,.35)'],
          ...((axis.splitArea || {}).areaStyle || {})
        },
        ...(axis.splitArea || {})
      };
    }
  });
  if (option.legend) {
    const legends = Array.isArray(option.legend) ? option.legend : [option.legend];
    legends.forEach(l => l.textStyle = { color: chartTextColor(), ...(l.textStyle || {}) });
  }
  if (option.title) {
    const titles = Array.isArray(option.title) ? option.title : [option.title];
    titles.forEach(t => t.textStyle = { color: chartTextColor(), ...(t.textStyle || {}) });
  }
  return option;
}

if (window.echarts && !window.echarts.__themePatched) {
  const rawInit = window.echarts.init.bind(window.echarts);
  window.echarts.init = function(dom, theme, opts) {
    const instance = rawInit(dom, theme, opts);
    if (!instance.__themePatched) {
      const rawSetOption = instance.setOption.bind(instance);
      instance.setOption = function(option, ...args) {
        return rawSetOption(applyChartThemeOption(option), ...args);
      };
      instance.__themePatched = true;
    }
    return instance;
  };
  window.echarts.__themePatched = true;
}

function updateThemeButton() {
  const btn = document.getElementById('themeToggle');
  if (btn) btn.textContent = isDarkTheme() ? '浅色' : '深色';
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
  localStorage.setItem('stockTheme', document.documentElement.dataset.theme);
  updateThemeButton();
  if (typeof window.onThemeChanged === 'function') window.onThemeChanged();
}

function toggleTheme() {
  setTheme(isDarkTheme() ? 'light' : 'dark');
}
