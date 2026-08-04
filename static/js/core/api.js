(function () {
  async function parseJsonResponse(res) {
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error('接口返回格式异常');
      }
    }
    if (!res.ok) {
      const msg = data && (data.error || data.message);
      throw new Error(msg || ('请求失败: HTTP ' + res.status));
    }
    return data;
  }

  async function request(url, options = {}) {
    const res = await fetch(url, options);
    return parseJsonResponse(res);
  }

  function jsonOptions(method, body, options = {}) {
    return {
      ...options,
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      body: body == null ? undefined : JSON.stringify(body)
    };
  }

  async function getJson(url, options = {}) {
    return request(url, options);
  }

  async function postJson(url, body, options = {}) {
    return request(url, jsonOptions('POST', body, options));
  }

  async function putJson(url, body, options = {}) {
    return request(url, jsonOptions('PUT', body, options));
  }

  async function deleteJson(url, options = {}) {
    return request(url, { ...options, method: 'DELETE' });
  }

  function watchJob(data, options = { open: true }) {
    if (window.BackgroundJobs) window.BackgroundJobs.watchResponse(data, options);
    return data;
  }

  window.StockApi = {
    request,
    getJson,
    postJson,
    putJson,
    deleteJson,
    watchJob
  };
})();
