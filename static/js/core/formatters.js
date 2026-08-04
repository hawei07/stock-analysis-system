(function () {
  function isMissing(value) {
    return value == null || Number.isNaN(Number(value));
  }

  function number(value, options = {}) {
    if (isMissing(value)) return options.empty || '-';
    const num = Number(value);
    const maximumFractionDigits = options.maximumFractionDigits ?? (Math.abs(num) >= 100 ? 1 : 2);
    const minimumFractionDigits = options.minimumFractionDigits ?? 0;
    return num.toLocaleString('zh-CN', { minimumFractionDigits, maximumFractionDigits });
  }

  function moneyYi(value, options = {}) {
    return number(value, options) + (isMissing(value) ? '' : '亿');
  }

  function percent(value, options = {}) {
    return number(value, { maximumFractionDigits: 2, ...options }) + (isMissing(value) ? '' : '%');
  }

  function shares(value, options = {}) {
    return number(value, { maximumFractionDigits: 2, ...options }) + (isMissing(value) ? '' : ' 股');
  }

  function signedPercent(value, options = {}) {
    if (isMissing(value)) return options.empty || '-';
    const num = Number(value);
    return (num > 0 ? '+' : '') + percent(num, options);
  }

  function dateTime(value) {
    if (!value) return '-';
    return String(value).replace('T', ' ').slice(0, 19);
  }

  window.StockFormat = {
    isMissing,
    number,
    moneyYi,
    percent,
    shares,
    signedPercent,
    dateTime
  };
})();
