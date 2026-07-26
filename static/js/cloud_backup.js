let cloudBackupStatusTimer = null;

function secondsText(seconds) {
  const n = Math.max(0, Number(seconds) || 0);
  if (n >= 60) return `${Math.floor(n / 60)}分${String(n % 60).padStart(2, '0')}秒`;
  return `${n}秒`;
}

function setCloudStatusPill(status) {
  const el = document.getElementById('cloudBackupStatus');
  if (!el || !status) return;
  const auto = status.auto_backup || {};
  el.className = 'cloud-status-pill';
  if (status.possible_conflict) {
    el.classList.add('conflict');
    el.textContent = '云备份状态：可能冲突';
    el.title = '云端较新，同时本机还有未上传修改';
    return;
  }
  if (auto.running) {
    el.classList.add('running');
    el.textContent = '云备份状态：正在备份';
    el.title = '自动云备份正在执行';
    return;
  }
  if (auto.pending) {
    el.classList.add('pending');
    el.textContent = `云备份状态：${secondsText(auto.seconds_remaining)}后自动备份`;
    el.title = `原因：${(auto.reasons || []).join(', ') || '数据修改'}`;
    return;
  }
  const last = auto.last_result || {};
  if (last.status === 'failed') {
    el.classList.add('failed');
    el.textContent = '云备份状态：上次失败';
    el.title = last.message || '自动云备份失败';
    return;
  }
  el.classList.add(last.status === 'ok' ? 'ok' : '');
  el.textContent = last.status === 'ok' ? `云备份状态：已完成 ${last.updated_at || ''}` : '云备份状态：空闲';
  el.title = last.message || '';
}

async function refreshCloudBackupStatus() {
  try {
    const res = await fetch('/api/cloud-backup/status');
    const status = await res.json();
    if (res.ok && !status.error) setCloudStatusPill(status);
    return status;
  } catch (e) {
    const el = document.getElementById('cloudBackupStatus');
    if (el) {
      el.className = 'cloud-status-pill failed';
      el.textContent = '云备份状态：检查失败';
    }
    return null;
  }
}

function startCloudBackupStatusPolling() {
  refreshCloudBackupStatus();
  if (cloudBackupStatusTimer) clearInterval(cloudBackupStatusTimer);
  cloudBackupStatusTimer = setInterval(refreshCloudBackupStatus, 5000);
}

function backupManagerRows(files) {
  return files.map((file, index) => {
    const type = backupFileType(file.name);
    return `
      <tr data-index="${index}" class="${index === 0 ? 'selected' : ''}">
        <td><span class="backup-type-badge ${type.cls}">${type.label}</span></td>
        <td class="backup-file-name">${escapeHtml(file.name)}</td>
        <td>${escapeHtml(file.mtime_iso)}</td>
        <td>${formatBackupSize(file.size)}</td>
      </tr>
    `;
  }).join('');
}

async function openBackupManager() {
  try {
    const [statusRes, filesRes] = await Promise.all([
      fetch('/api/cloud-backup/status'),
      fetch('/api/cloud-backup/files')
    ]);
    const status = await statusRes.json();
    const filesData = await filesRes.json();
    if (!statusRes.ok || status.error) throw new Error(status.error || '读取备份状态失败');
    if (!filesRes.ok || filesData.error) throw new Error(filesData.error || '读取备份列表失败');
    showBackupManagerModal(status, filesData.files || []);
  } catch (e) {
    showToast(e.message || '打开备份管理失败', 'error');
  }
}

function closeBackupManagerModal() {
  document.getElementById('backupManagerModal')?.remove();
}

function showBackupManagerModal(status, files) {
  closeBackupManagerModal();
  let selectedIndex = 0;
  const auto = status.auto_backup || {};
  const latestSize = status.latest_exists ? formatBackupSize(status.latest_size) : '不存在';
  const local = status.local_state || {};
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay active';
  overlay.id = 'backupManagerModal';
  overlay.innerHTML = `
    <div class="modal backup-restore-modal">
      <div class="modal-header">
        <h3>备份管理</h3>
        <button class="modal-close" type="button" aria-label="关闭">&times;</button>
      </div>
      <div class="modal-body">
        ${status.possible_conflict ? '<div class="backup-warning">检测到云端备份比本机记录更新，同时本机存在未上传修改。建议先不要直接覆盖，先确认两边最近操作，再从历史版本中选择。</div>' : ''}
        <div class="backup-manager-grid">
          <div class="backup-manager-card"><div class="label">云同步目录</div><div class="value">${escapeHtml(status.backup_dir || '')}</div></div>
          <div class="backup-manager-card"><div class="label">latest 时间</div><div class="value">${escapeHtml(status.latest_mtime || '未检测到')}</div></div>
          <div class="backup-manager-card"><div class="label">latest 大小</div><div class="value">${latestSize}</div></div>
          <div class="backup-manager-card"><div class="label">本机最后应用</div><div class="value">${escapeHtml(local.latest_mtime_iso || local.updated_at || '暂无记录')}</div></div>
          <div class="backup-manager-card"><div class="label">自动备份</div><div class="value">${auto.running ? '正在备份' : auto.pending ? secondsText(auto.seconds_remaining) + '后执行' : (auto.last_result?.message || '空闲')}</div></div>
          <div class="backup-manager-card"><div class="label">触发原因</div><div class="value">${escapeHtml((auto.reasons || auto.last_result?.reasons || []).join(', ') || '无')}</div></div>
        </div>
        <div class="backup-restore-table-wrap">
          <table class="backup-restore-table">
            <thead><tr><th style="width:90px">类型</th><th>文件名</th><th style="width:170px">备份时间</th><th style="width:100px">大小</th></tr></thead>
            <tbody>${backupManagerRows(files)}</tbody>
          </table>
        </div>
        <div class="backup-restore-hint">普通备份和恢复前备份各保留最新 5 份。恢复前系统仍会自动生成 pre_restore 保护备份。</div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" type="button" data-action="refresh">刷新</button>
        <button class="btn btn-outline" type="button" data-action="backup">立即云备份</button>
        <button class="btn btn-outline" type="button" data-action="restore-latest">恢复 latest</button>
        <button class="btn btn-primary" type="button" data-action="restore-selected">恢复选中版本</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => closeBackupManagerModal();
  overlay.querySelector('.modal-close').onclick = close;
  overlay.onclick = e => { if (e.target === overlay) close(); };
  overlay.querySelectorAll('tbody tr').forEach(row => {
    row.onclick = () => {
      selectedIndex = Number(row.dataset.index);
      overlay.querySelectorAll('tbody tr').forEach(item => item.classList.remove('selected'));
      row.classList.add('selected');
    };
  });
  overlay.querySelector('[data-action="refresh"]').onclick = () => { close(); openBackupManager(); };
  overlay.querySelector('[data-action="backup"]').onclick = async () => { await backupCloud(); close(); openBackupManager(); };
  overlay.querySelector('[data-action="restore-latest"]').onclick = () => restoreCloud();
  overlay.querySelector('[data-action="restore-selected"]').onclick = async () => {
    const file = files[selectedIndex];
    if (!file) return;
    await restoreSelectedBackupFile(file.name, overlay.querySelector('[data-action="restore-selected"]'));
  };
}

async function backupCloud() {
  showToast('正在备份到云同步目录...', 'success');
  try {
    const res = await fetch('/api/cloud-backup/backup', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.error) {
      showToast(data.error || '云备份失败', 'error');
      return;
    }
    showToast(`云备份完成: ${data.latest_backup}`, 'success');
    refreshCloudBackupStatus();
  } catch (e) {
    showToast('云备份失败', 'error');
  }
}

async function restoreCloud() {
  let statusText = '';
  try {
    const statusRes = await fetch('/api/cloud-backup/status');
    const status = await statusRes.json();
    statusText = status.latest_mtime ? `\n云端备份时间：${status.latest_mtime}\n目录：${status.backup_dir}` : '\n未检测到云端备份';
    if (status.possible_conflict) {
      statusText += '\n\n注意：检测到云端较新，同时本机有未上传修改，可能存在同步冲突。';
    }
    if (!status.latest_exists) {
      showToast('云端 latest 备份不存在', 'error');
      return;
    }
  } catch (e) {}
  if (!confirm('从云端备份恢复会覆盖本地数据库。系统会先自动备份当前本地数据。确认恢复？' + statusText)) return;
  showToast('正在从云端恢复，请稍候...', 'success');
  try {
    const res = await fetch('/api/cloud-backup/restore', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.error) {
      showToast(data.error || '云恢复失败', 'error');
      return;
    }
    showToast('云恢复完成，正在刷新页面...', 'success');
    setTimeout(() => location.reload(), 1200);
  } catch (e) {
    showToast('云恢复失败', 'error');
  }
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}

function backupFileType(name) {
  if (name === 'stock_analysis_latest.sql') return { label: '最新', cls: 'latest' };
  if (name.startsWith('pre_restore_')) return { label: '恢复前', cls: 'pre' };
  return { label: '备份', cls: '' };
}

function formatBackupSize(bytes) {
  return `${((Number(bytes) || 0) / 1024 / 1024).toFixed(2)} MB`;
}

async function restoreSelectedBackupFile(filename, btn) {
  if (!filename || (btn && btn.disabled)) return;
  if (btn) {
    btn.disabled = true;
    btn.textContent = '恢复中...';
  }
  showToast('正在恢复历史备份，请稍候...', 'success');
  try {
    const restoreRes = await fetch('/api/cloud-backup/restore-file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename })
    });
    const restoreData = await restoreRes.json();
    if (!restoreRes.ok || restoreData.error) {
      showToast(restoreData.error || '历史恢复失败', 'error');
      if (btn) {
        btn.disabled = false;
        btn.textContent = '恢复选中版本';
      }
      return;
    }
    showToast('历史恢复完成，正在刷新页面...', 'success');
    setTimeout(() => location.reload(), 1200);
  } catch (e) {
    showToast('历史恢复失败', 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '恢复选中版本';
    }
  }
}

async function checkCloudUpdateOnStartup() {
  try {
    const res = await fetch('/api/cloud-backup/status?startup=1');
    const status = await res.json();
    if (!status.cloud_newer) return;
    showCloudUpdatePrompt(status);
  } catch (e) {
    // 启动检查静默失败，不影响正常打开系统。
  }
}

function showCloudUpdatePrompt(status) {
  if (document.getElementById('cloudUpdatePrompt')) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay active';
  overlay.id = 'cloudUpdatePrompt';
  overlay.innerHTML = `
    <div class="modal" style="width:420px">
      <div class="modal-header">
        <h3>发现云端数据更新</h3>
        <button class="modal-close" type="button">&times;</button>
      </div>
      <div class="modal-body" style="padding:24px;line-height:1.8;color:#555;font-size:14px">
        ${status.possible_conflict ? '<div class="backup-warning">可能存在同步冲突：云端备份较新，同时本机还有未上传修改。建议先点“稍后”，进入备份管理查看历史版本。</div>' : '<div>云端备份比本地记录更新，建议先更新本地数据再继续使用。</div>'}
        <div style="margin-top:12px;font-size:13px;color:#777">
          云端时间：${status.latest_mtime || '未知'}<br>
          云端目录：${status.backup_dir || ''}
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" type="button" data-action="later">稍后</button>
        <button class="btn btn-primary" type="button" data-action="update">立即更新</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector('.modal-close').onclick = close;
  overlay.querySelector('[data-action="later"]').onclick = close;
  overlay.querySelector('[data-action="update"]').onclick = () => restoreCloudFromStartup(overlay);
}

async function restoreCloudFromStartup(overlay) {
  const btn = overlay.querySelector('[data-action="update"]');
  btn.disabled = true;
  btn.textContent = '更新中...';
  showToast('正在从云端更新本地数据，请稍候...', 'success');
  try {
    const res = await fetch('/api/cloud-backup/restore', { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.error) {
      showToast(data.error || '云端更新失败', 'error');
      btn.disabled = false;
      btn.textContent = '立即更新';
      return;
    }
    showToast('云端更新完成，正在刷新页面...', 'success');
    setTimeout(() => location.reload(), 1200);
  } catch (e) {
    showToast('云端更新失败', 'error');
    btn.disabled = false;
    btn.textContent = '立即更新';
  }
}


