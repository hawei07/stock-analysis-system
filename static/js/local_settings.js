function collectLocalSettings() {
  return {
    cloud_sync_dir: document.getElementById('localCloudDir').value.trim(),
    mysql_service_name: document.getElementById('localMysqlService').value.trim(),
    mysql_home: document.getElementById('localMysqlHome').value.trim(),
    mysql_bin_dir: document.getElementById('localMysqlBin').value.trim(),
    python_exe: document.getElementById('localPythonExe').value.trim(),
    db_host: document.getElementById('localDbHost').value.trim(),
    db_port: document.getElementById('localDbPort').value.trim(),
    db_user: document.getElementById('localDbUser').value.trim(),
    db_password: document.getElementById('localDbPassword').value,
    db_name: document.getElementById('localDbName').value.trim(),
    auto_cloud_backup_delay_seconds: document.getElementById('localAutoBackupDelay').value.trim()
  };
}

function fillLocalSettings(data) {
  const values = data.values || {};
  document.getElementById('localCloudDir').value = values.cloud_sync_dir || '';
  document.getElementById('localMysqlService').value = values.mysql_service_name || '';
  document.getElementById('localMysqlHome').value = values.mysql_home || '';
  document.getElementById('localMysqlBin').value = values.mysql_bin_dir || '';
  document.getElementById('localPythonExe').value = values.python_exe || '';
  document.getElementById('localDbHost').value = values.db_host || '';
  document.getElementById('localDbPort').value = values.db_port || '';
  document.getElementById('localDbUser').value = values.db_user || '';
  document.getElementById('localDbPassword').value = '';
  document.getElementById('localDbPassword').placeholder = data.db_password_configured ? '已配置，留空不修改' : '数据库密码';
  document.getElementById('localDbName').value = values.db_name || '';
  document.getElementById('localAutoBackupDelay').value = values.auto_cloud_backup_delay_seconds || 180;
  const checks = data.checks || {};
  const latest = checks.cloud_latest_sql || {};
  document.getElementById('localSettingsStatus').innerHTML =
    '配置文件：' + escapeHtml(data.path || '') + '<br>' +
    '云目录：' + (checks.cloud_sync_dir?.exists ? '可访问' : '未检测到') + '；latest：' +
    (latest.exists ? escapeHtml((latest.mtime || '') + ' / ' + formatBackupSize(latest.size || 0)) : '不存在') +
    '<br>保存本机配置后，需要重启项目才会完整生效。';
}

async function loadLocalSettings() {
  try {
    const data = await StockApi.getJson('/api/local-settings');
    fillLocalSettings(data);
  } catch (e) {
    document.getElementById('localSettingsStatus').textContent = e.message || '读取本机配置失败';
  }
}

async function testLocalSettings() {
  showSettingsMsg('正在测试本机环境...', 'success');
  try {
    const data = await StockApi.postJson('/api/local-settings/test', collectLocalSettings());
    const checks = data.checks || {};
    const lines = Object.values(checks).map(item => (item.ok ? '✓ ' : '✗ ') + item.message);
    showSettingsMsg(lines.join('；'), data.ok ? 'success' : 'error');
  } catch (e) {
    showSettingsMsg(e.message || '测试失败', 'error');
  }
}

async function saveLocalSettings() {
  try {
    const data = await StockApi.putJson('/api/local-settings', collectLocalSettings());
    fillLocalSettings(data);
    showSettingsMsg('本机配置已保存，重启项目后完整生效', 'success');
  } catch (e) {
    showSettingsMsg(e.message || '保存失败', 'error');
  }
}

function showSettingsMsg(text, type) {
  const el = document.getElementById('settingsMsg');
  el.textContent = text;
  el.style.display = 'block';
  el.style.color = type === 'success' ? '#52c41a' : '#e74c3c';
}
