let irmAutoSyncStarted = false;
const IRM_AUTO_SYNC_DATE_KEY = 'irmAutoSyncDate';

function todayKey() {
  const d = new Date();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

async function startIrmAutoSync() {
  if (irmAutoSyncStarted) return;
  const today = todayKey();
  if (localStorage.getItem(IRM_AUTO_SYNC_DATE_KEY) === today) return;
  irmAutoSyncStarted = true;
  try {
    const res = await fetch('/api/irm/sync', { method: 'POST' });
    const data = await res.json();
    if (res.ok && (data.started || data.already_running || data.ok)) {
      localStorage.setItem(IRM_AUTO_SYNC_DATE_KEY, today);
    }
    if (window.BackgroundJobs) BackgroundJobs.watchResponse(data, { open: false });
    pollIrmStatus();
  } catch (e) {
    // 自动抓取静默失败，不影响正常打开系统。
  }
}

async function pollIrmStatus() {
  try {
    const res = await fetch('/api/irm/status');
    const data = await res.json();
    const statusEl = document.getElementById('irmStatus');
    if (statusEl && data.message) statusEl.textContent = data.message;
    if (data.running) {
      setTimeout(pollIrmStatus, 4000);
    } else if (currentTab === 'irm') {
      loadIrm(getCurrentCode(), { silent: true });
    }
  } catch (e) {
    // 状态轮询失败时不打扰页面。
  }
}

async function loadIrm(code, options = {}) {
  if (!code) return;
  const statusEl = document.getElementById('irmStatus');
  const list = document.getElementById('irmList');
  if (statusEl && !options.silent) statusEl.textContent = '加载中...';
  if (list && !options.silent) list.innerHTML = '<div class="empty" id="irmEmpty">正在加载互动易问答...</div>';
  try {
    const res = await fetch('/api/stock/' + code + '/irm');
    const data = await res.json();
    if (code !== getCurrentCode()) return;
    if (!res.ok || data.error) throw new Error(data.error || '加载失败');
    renderIrm(data);
  } catch (e) {
    if (list) list.innerHTML = '<div class="empty" id="irmEmpty">互动易问答加载失败</div>';
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '加载互动易失败', 'error');
  }
}

async function syncCurrentIrm() {
  const code = getCurrentCode();
  if (!code) return;
  const statusEl = document.getElementById('irmStatus');
  if (statusEl) statusEl.textContent = '抓取中...';
  try {
    const res = await fetch('/api/stock/' + code + '/irm/sync', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || '抓取失败');
    if (statusEl) statusEl.textContent = data.message || ('本次新增 ' + (data.inserted || 0) + ' 条');
    await loadIrm(code, { silent: true });
  } catch (e) {
    if (statusEl) statusEl.textContent = '';
    showToast(e.message || '互动易抓取失败', 'error');
  }
}

function formatIrmTime(value) {
  if (!value) return '--';
  const text = String(value);
  return text.length >= 16 ? text.slice(0, 16) : text;
}

function renderIrm(data) {
  const list = document.getElementById('irmList');
  const statusEl = document.getElementById('irmStatus');
  if (!list) return;
  const items = data.items || [];
  const sync = data.sync || {};
  if (statusEl) {
    const parts = [];
    if (data.source) parts.push(data.source);
    if (sync.running) parts.push('后台抓取中');
    else if (sync.message) parts.push(sync.message);
    statusEl.textContent = parts.join(' | ');
  }
  if (!data.supported) {
    list.innerHTML = '<div class="empty" id="irmEmpty">互动问答目前支持沪深股票，其他市场暂不支持。</div>';
    return;
  }
  if (!items.length) {
    list.innerHTML = '<div class="empty" id="irmEmpty">暂无已答复的互动易问答，点击“立即抓取”试试。</div>';
    return;
  }
  list.innerHTML = items.map(item => `
    <article class="irm-item">
      <div class="irm-line">
        <span class="irm-badge question">提问</span>
        <span class="irm-content">${esc(item.question || '')}</span>
        <span class="irm-time">提问于 ${formatIrmTime(item.question_time)}</span>
        ${item.original_url ? `<a class="irm-link" href="${esc(item.original_url)}" target="_blank" rel="noopener">原文链接</a>` : ''}
      </div>
      <div class="irm-line">
        <span class="irm-badge answer">回答</span>
        <span class="irm-content">${esc(item.answer || '')}</span>
        <span class="irm-time">回答于 ${formatIrmTime(item.answer_time || item.update_time)}</span>
      </div>
      <div class="irm-actions">
        <span>转发(${Number(item.forward_count || 0)})</span>
        <span>赞(${Number(item.praise_count || 0)})</span>
        <span>收藏(${Number(item.favorite_count || 0)})</span>
        ${item.source ? `<span>${esc(item.source)}</span>` : ''}
      </div>
    </article>
  `).join('');
}

// ==================== K线图 ====================

