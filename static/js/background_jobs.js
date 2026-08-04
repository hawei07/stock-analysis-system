(function () {
  const JOB_LABELS = {
    irm_sync_all: '互动易抓取',
    update_financials: '财报摘要更新',
    update_dividends: '分红数据更新',
    update_balance_sheet: '资产负债表更新',
    update_income: '利润表更新',
    update_cashflow: '现金流量表更新',
    update_segments: '营收构成更新',
    update_shareholders: '股东数据更新'
  };
  const STATUS_LABELS = {
    queued: '排队中',
    running: '运行中',
    done: '已完成',
    partial: '部分完成',
    failed: '失败',
    cancelled: '已取消'
  };
  const ACTIVE = new Set(['queued', 'running']);
  const TERMINAL_WITH_ACTION = new Set(['partial', 'failed', 'cancelled']);

  const state = {
    jobs: [],
    tracked: new Set(),
    open: false,
    timer: null,
    logOpen: new Set(),
    logs: {}
  };

  function labelJob(job) {
    return job.title || JOB_LABELS[job.job_type] || job.job_type || '后台任务';
  }

  function statusText(status) {
    return STATUS_LABELS[status] || status || '-';
  }

  function progressText(job) {
    const current = Number(job.progress_current || 0);
    const total = Number(job.progress_total || 0);
    if (!total) return job.status === 'running' ? '运行中' : '';
    const pct = job.progress_percent == null ? Math.round(current * 100 / total) : job.progress_percent;
    return `${current}/${total} · ${pct}%`;
  }

  function ensureDock() {
    let dock = document.getElementById('jobDock');
    if (dock) return dock;
    dock = document.createElement('div');
    dock.id = 'jobDock';
    dock.className = 'job-dock is-empty';
    dock.innerHTML = `
      <button class="job-dock-toggle" type="button" id="jobDockToggle">
        <span class="job-dock-title"><strong id="jobDockTitle">后台任务</strong><span id="jobDockSub">暂无任务</span></span>
        <span class="job-dock-badge" id="jobDockBadge">0</span>
      </button>
      <div class="job-dock-panel">
        <div class="job-panel-head">
          <strong>后台任务</strong>
          <div class="job-panel-actions">
            <button class="job-icon-btn" type="button" id="jobRefreshBtn" title="刷新">⟳</button>
            <button class="job-icon-btn" type="button" id="jobCloseBtn" title="收起">×</button>
          </div>
        </div>
        <div class="job-list" id="jobList"><div class="job-empty">暂无后台任务</div></div>
      </div>`;
    document.body.appendChild(dock);
    document.getElementById('jobDockToggle').addEventListener('click', () => setOpen(!state.open));
    document.getElementById('jobCloseBtn').addEventListener('click', () => setOpen(false));
    document.getElementById('jobRefreshBtn').addEventListener('click', () => refreshJobs(true));
    return dock;
  }

  function setOpen(open) {
    state.open = open;
    ensureDock().classList.toggle('is-open', open);
    if (open) refreshJobs(true);
  }

  function render() {
    const dock = ensureDock();
    const jobs = state.jobs || [];
    const activeJobs = jobs.filter(job => ACTIVE.has(job.status));
    dock.classList.toggle('is-empty', jobs.length === 0);
    dock.classList.toggle('has-jobs', jobs.length > 0);
    dock.classList.toggle('is-open', state.open);

    const top = activeJobs[0] || jobs[0];
    document.getElementById('jobDockTitle').textContent = top ? labelJob(top) : '后台任务';
    document.getElementById('jobDockSub').textContent = top ? `${statusText(top.status)} ${progressText(top)}` : '暂无任务';
    document.getElementById('jobDockBadge').textContent = activeJobs.length || jobs.length;

    const list = document.getElementById('jobList');
    if (!jobs.length) {
      list.innerHTML = '<div class="job-empty">暂无后台任务</div>';
      return;
    }
    list.innerHTML = jobs.slice(0, 12).map(renderJob).join('');
    list.querySelectorAll('[data-job-action]').forEach(btn => {
      btn.addEventListener('click', () => handleAction(btn.dataset.jobAction, Number(btn.dataset.jobId)));
    });
  }

  function renderJob(job) {
    const pct = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));
    const logs = state.logs[job.id] || [];
    const logHtml = logs.length ? logs.map(log => `
      <div class="job-log-line job-log-level-${log.level || 'info'}">
        <span>${log.stock_code || log.level || ''}</span>
        <span>${escapeHtml(log.message || '')}</span>
      </div>`).join('') : '<div class="job-log-line"><span></span><span>暂无日志</span></div>';
    const canCancel = ACTIVE.has(job.status) && !job.cancel_requested;
    const canRetry = TERMINAL_WITH_ACTION.has(job.status);
    return `
      <div class="job-item" data-job-id="${job.id}">
        <div class="job-item-title">
          <strong>${escapeHtml(labelJob(job))}</strong>
          <span class="job-status job-status-${job.status}">${statusText(job.status)}</span>
        </div>
        <div class="job-item-message">${escapeHtml(job.message || '')}</div>
        <div class="job-progress"><div class="job-progress-fill" style="width:${pct}%"></div></div>
        <div class="job-item-meta"><span>${progressText(job)}</span><span>#${job.id}</span></div>
        <div class="job-item-actions">
          ${canCancel ? `<button class="job-action-btn job-action-danger" type="button" data-job-action="cancel" data-job-id="${job.id}">取消</button>` : ''}
          ${canRetry ? `<button class="job-action-btn" type="button" data-job-action="retry" data-job-id="${job.id}">重试</button>` : ''}
          <button class="job-action-btn" type="button" data-job-action="logs" data-job-id="${job.id}">日志</button>
        </div>
        <div class="job-log ${state.logOpen.has(job.id) ? 'is-open' : ''}" id="jobLog${job.id}">${logHtml}</div>
      </div>`;
  }

  function escapeHtml(text) {
    return String(text || '').replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[ch]));
  }

  async function handleAction(action, jobId) {
    if (action === 'logs') {
      if (state.logOpen.has(jobId)) {
        state.logOpen.delete(jobId);
        render();
        return;
      }
      await loadLogs(jobId);
      state.logOpen.add(jobId);
      render();
      return;
    }
    if (action === 'cancel') {
      await fetch(`/api/jobs/${jobId}/cancel`, { method: 'POST' });
      await refreshJobs(true);
      return;
    }
    if (action === 'retry') {
      const res = await fetch(`/api/jobs/${jobId}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ failed_only: true })
      });
      const data = await res.json();
      if (data.new_job_id) watchJob(data.new_job_id, { open: true });
      await refreshJobs(true);
    }
  }

  async function loadLogs(jobId) {
    const res = await fetch(`/api/jobs/${jobId}/logs?limit=200`);
    const data = await res.json();
    state.logs[jobId] = data.logs || [];
  }

  async function refreshJobs(openOnActive) {
    try {
      const res = await fetch('/api/jobs?limit=20');
      const data = await res.json();
      state.jobs = data.jobs || [];
      const hasActive = state.jobs.some(job => ACTIVE.has(job.status));
      if (openOnActive && hasActive) state.open = true;
      render();
      schedule(hasActive);
    } catch (e) {
      schedule(false);
    }
  }

  function schedule(hasActive) {
    if (state.timer) clearTimeout(state.timer);
    state.timer = setTimeout(() => refreshJobs(false), hasActive ? 2500 : 12000);
  }

  function watchJob(jobId, options) {
    if (!jobId) return;
    state.tracked.add(Number(jobId));
    if (options && options.open) state.open = true;
    refreshJobs(true);
  }

  function watchResponse(data, options) {
    if (data && data.job_id) watchJob(data.job_id, options || { open: true });
  }

  window.BackgroundJobs = {
    watchJob,
    watchResponse,
    refresh: () => refreshJobs(true),
    open: () => setOpen(true)
  };

  document.addEventListener('DOMContentLoaded', () => {
    ensureDock();
    refreshJobs(false);
  });
})();
