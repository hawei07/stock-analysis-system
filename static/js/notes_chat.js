let chatLoaded = false;
let mungerRequestSeq = 0;
let chatCatalogPromise = null;

function chatConfigValue(id, fallback = '') {
  return document.getElementById(id)?.value || fallback;
}

function currentChatConfig() {
  return {
    skill_id: chatConfigValue('chatSkillSelect', 'munger'),
    model_id: chatConfigValue('chatModelSelect', ''),
    forecast_horizon: Number(chatConfigValue('chatForecastHorizon', '3')) || 3,
    forecast_scenario: chatConfigValue('chatForecastScenario', 'base') || 'base'
  };
}

function persistChatConfig() {
  const config = currentChatConfig();
  try { localStorage.setItem('mungerChatConfig', JSON.stringify(config)); } catch (e) { /* private mode */ }
  return config;
}

function restoreChatConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem('mungerChatConfig') || '{}');
    ['chatSkillSelect', 'chatModelSelect', 'chatForecastHorizon', 'chatForecastScenario'].forEach(id => {
      const value = id === 'chatSkillSelect' ? saved.skill_id
        : id === 'chatModelSelect' ? saved.model_id
        : id === 'chatForecastHorizon' ? String(saved.forecast_horizon || '')
        : saved.forecast_scenario;
      const element = document.getElementById(id);
      if (element && value && Array.from(element.options).some(option => option.value === String(value))) {
        element.value = String(value);
      }
    });
  } catch (e) { /* ignore malformed local preference */ }
}

function chatEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[ch]));
}

function renderChatMarkdown(content) {
  const lines = String(content ?? '').replace(/\r/g, '').split('\n');
  const output = [];
  let listType = null;
  let inCode = false;
  let codeLines = [];

  function closeList() {
    if (listType) output.push(`</${listType}>`);
    listType = null;
  }

  function inline(text) {
    return chatEscape(text)
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
      .replace(/\[([A-Za-z0-9_-]*-S\d+|S\d+)\]/gi, '<span class="chat-citation">[$1]</span>');
  }

  lines.forEach(rawLine => {
    if (/^\s*```/.test(rawLine)) {
      if (inCode) {
        output.push(`<pre><code>${chatEscape(codeLines.join('\n'))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        inCode = true;
      }
      return;
    }
    if (inCode) {
      codeLines.push(rawLine);
      return;
    }
    const line = rawLine.trimEnd();
    if (!line.trim()) {
      closeList();
      output.push('<br>');
      return;
    }
    const heading = line.match(/^#{2,4}\s+(.+)$/);
    if (heading) {
      closeList();
      output.push(`<h3>${inline(heading[1])}</h3>`);
      return;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      if (listType !== 'ul') {
        closeList();
        output.push('<ul>');
        listType = 'ul';
      }
      output.push(`<li>${inline(bullet[1])}</li>`);
      return;
    }
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ordered) {
      if (listType !== 'ol') {
        closeList();
        output.push('<ol>');
        listType = 'ol';
      }
      output.push(`<li>${inline(ordered[1])}</li>`);
      return;
    }
    closeList();
    const quote = line.match(/^>\s?(.*)$/);
    output.push(quote ? `<blockquote>${inline(quote[1])}</blockquote>` : `${inline(line)}<br>`);
  });
  if (inCode) output.push(`<pre><code>${chatEscape(codeLines.join('\n'))}</code></pre>`);
  closeList();
  return output.join('').replace(/(<br>){2,}/g, '<br>');
}

function safeChatUrl(url) {
  return /^https?:\/\//i.test(String(url || '')) ? String(url) : '';
}

function renderChatMeta(meta) {
  if (!meta || meta.error) return '';
  const identity = [meta.stock_name, meta.stock_code].filter(Boolean).join(' ');
  const intent = meta.intent_label ? `回答模式：${chatEscape(meta.intent_label)}` : '';
  const period = meta.latest_period ? `最新 ${chatEscape(meta.latest_period)}` : '';
  const yoy = meta.yoy_base ? `同比基准 ${chatEscape(meta.yoy_base)}` : '';
  const sourceCount = Number(meta.source_count) || 0;
  const citationStatus = meta.citation_validation?.status === 'ok'
    ? '引用已校验'
    : meta.citation_validation?.status === 'warning' ? '引用需复核' : '';
  const summary = [identity && chatEscape(identity), intent, period, yoy,
    meta.search_used ? `已参考 ${sourceCount} 个来源` : '未联网搜索', citationStatus]
    .filter(Boolean).join(' · ');
  const warnings = (Array.isArray(meta.warnings) ? meta.warnings : [])
    .map(item => `<li>${chatEscape(item)}</li>`).join('');
  const sources = (Array.isArray(meta.sources) ? meta.sources : []).map(source => {
    const url = safeChatUrl(source.url);
    const title = chatEscape(source.title || url || source.id || '来源');
    const id = chatEscape(source.id || 'S?');
    const reliability = source.reliability ? ` · ${chatEscape(source.reliability)}` : '';
    return `<li><span class="chat-source-id">${id}</span>${url ? ` <a class="chat-source-link" href="${chatEscape(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : ` ${title}`}${reliability}</li>`;
  }).join('');
  const details = sources || warnings ? `<details class="chat-source-list"><summary>上下文详情${sourceCount ? `（${sourceCount} 个来源）` : ''}</summary>${sources ? `<ul>${sources}</ul>` : ''}${warnings ? `<div class="chat-warning-title">数据提示</div><ul class="chat-warnings">${warnings}</ul>` : ''}</details>` : '';
  return `<div class="chat-meta">${summary || '已加载本地分析上下文'}${details}</div>`;
}

async function loadMungerChat() {
  const code = document.getElementById('detailCode').textContent.trim();
  if (!code) return;
  const requestSeq = ++mungerRequestSeq;
  const container = document.getElementById('chatMessages');

  try {
    const msgs = await StockApi.getJson('/api/stock/' + code + '/munger-chat');
    if (requestSeq !== mungerRequestSeq || code !== document.getElementById('detailCode').textContent.trim()) return;
    container.innerHTML = '';
    if (!msgs.length) {
      container.innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
    } else {
      msgs.forEach(m => appendMsg(m.role, m.content, m.id, m.meta));
    }
    chatLoaded = true;
    scrollChatBottom();
  } catch(e) {
    if (requestSeq !== mungerRequestSeq || code !== document.getElementById('detailCode').textContent.trim()) return;
    container.innerHTML = `<div class="chat-empty chat-error">${chatEscape(e.message || '加载失败')}</div>`;
  }
}

function appendMsg(role, content, msgId, meta) {
  const container = document.getElementById('chatMessages');
  const empty = document.getElementById('chatEmpty');
  if (empty) empty.remove();

  const cls = role === 'munger' ? 'munger' : 'user';
  const avatar = role === 'munger' ? '🧠' : '👤';
  const html = renderChatMarkdown(content);
  const delBtn = msgId ? `<button class="chat-delete" onclick="deleteChatMsg(${Number(msgId)},this)" title="删除">✕</button>` : '';

  const div = document.createElement('div');
  div.className = 'chat-msg ' + cls;
  div.innerHTML = `
    <div class="chat-avatar">${avatar}</div>
    <div class="chat-bubble">${html}${renderChatMeta(meta)}${delBtn}</div>`;
  container.appendChild(div);
}

async function sendMungerChat() {
  const code = document.getElementById('detailCode').textContent.trim();
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('chatSendBtn');
  const msg = input.value.trim();
  if (!msg || !code) return;
  const requestSeq = ++mungerRequestSeq;
  const isCurrentRequest = () => (
    requestSeq === mungerRequestSeq &&
    code === document.getElementById('detailCode').textContent.trim()
  );

  appendMsg('user', msg);
  input.value = '';
  input.disabled = true;
  btn.disabled = true;
  scrollChatBottom();

  const container = document.getElementById('chatMessages');
  const typing = document.createElement('div');
  typing.className = 'chat-msg munger';
  typing.id = 'chatTyping';
  typing.innerHTML = '<div class="chat-avatar">🧠</div><div class="chat-bubble"><div class="chat-typing"><span></span><span></span><span></span></div></div>';
  container.appendChild(typing);
  scrollChatBottom();

  try {
    const data = await StockApi.postJson('/api/stock/' + code + '/munger-chat', {message: msg});
    typing.remove();
    if (!isCurrentRequest()) return;
    appendMsg('munger', data.reply || '智能体返回了空内容。', null, data.meta);
  } catch(e) {
    typing.remove();
    if (!isCurrentRequest()) return;
    appendMsg('munger', `⚠️ ${e.message || '请求失败，请稍后重试。'}`, null, {error: true});
  } finally {
    input.disabled = false;
    btn.disabled = false;
    if (isCurrentRequest()) {
      input.focus();
      scrollChatBottom();
    }
  }
}

async function deleteChatMsg(msgId, btn) {
  if (!confirm('删除这条消息？')) return;
  try {
    await StockApi.deleteJson('/api/stock/' + document.getElementById('detailCode').textContent + '/munger-chat?msg_id=' + msgId);
    btn.closest('.chat-msg').remove();
    if (!document.querySelector('.chat-msg')) {
      document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
    }
  } catch(e) {
    showToast(e.message || '删除失败', 'error');
  }
}

async function clearMungerChat() {
  const code = document.getElementById('detailCode').textContent;
  if (!confirm('确定清空全部对话？')) return;
  try {
    await StockApi.deleteJson('/api/stock/' + code + '/munger-chat');
    document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
  } catch(e) {
    showToast(e.message || '清空失败', 'error');
  }
}

function scrollChatBottom() {
  const el = document.getElementById('chatMessages');
  if (el) setTimeout(() => el.scrollTop = el.scrollHeight, 100);
}

// ── 便利贴 ──────────────────────────────────────────────────────────────────

/* ── Third-round Munger chat UX ─────────────────────────────────────────── */

let chatStreaming = false;
let mungerStreamController = null;

function ensureChatPhase() {
  let phase = document.getElementById('chatPhase');
  if (phase) return phase;
  const panel = document.querySelector('.chat-panel');
  const messages = document.getElementById('chatMessages');
  if (!panel || !messages) return null;
  phase = document.createElement('div');
  phase.id = 'chatPhase';
  phase.className = 'chat-phase';
  panel.insertBefore(phase, messages);
  return phase;
}

function setChatPhase(label, visible = true) {
  const phase = ensureChatPhase();
  if (!phase) return;
  phase.textContent = label || '';
  phase.classList.toggle('active', Boolean(visible && label));
}

async function loadChatCatalog() {
  if (chatCatalogPromise) return chatCatalogPromise;
  chatCatalogPromise = Promise.all([
    StockApi.getJson('/api/chat/skills'),
    StockApi.getJson('/api/chat/models')
  ]).then(([skillData, modelData]) => {
    const skillSelect = document.getElementById('chatSkillSelect');
    const modelSelect = document.getElementById('chatModelSelect');
    if (skillSelect && Array.isArray(skillData?.skills)) {
      skillSelect.innerHTML = '';
      skillData.skills.forEach(skill => {
        if (!skill?.id) return;
        const option = document.createElement('option');
        option.value = skill.id;
        option.textContent = skill.label || skill.id;
        option.title = [skill.description, skill.version].filter(Boolean).join(' · ');
        skillSelect.appendChild(option);
      });
    }
    if (modelSelect && Array.isArray(modelData?.models)) {
      modelSelect.innerHTML = '';
      modelData.models.forEach(model => {
        if (!model?.id) return;
        const option = document.createElement('option');
        option.value = model.id;
        option.textContent = model.label || model.id;
        option.title = model.purpose || model.id;
        modelSelect.appendChild(option);
      });
      const defaultModel = modelData?.default_model;
      if (defaultModel && Array.from(modelSelect.options).some(option => option.value === defaultModel)) {
        modelSelect.value = defaultModel;
      }
    }
    restoreChatConfig();
    updateForecastControls();
    return {skills: skillData?.skills || [], models: modelData?.models || []};
  }).catch(error => {
    chatCatalogPromise = null;
    setChatPhase(`分析选项加载失败：${error.message || '请稍后重试'}`, true);
    return {skills: [], models: []};
  });
  return chatCatalogPromise;
}

function updateForecastControls() {
  const skill = chatConfigValue('chatSkillSelect', 'munger');
  const supported = skill === 'auto' || skill === 'stock_analyst' || skill === 'valuation';
  document.querySelectorAll('.chat-forecast-control').forEach(node => {
    node.style.display = supported ? 'flex' : 'none';
  });
}

function onChatConfigChange() {
  persistChatConfig();
  updateForecastControls();
}

function renderChatMeta(meta) {
  if (!meta || meta.error) return '';
  const identity = [meta.stock_name, meta.stock_code].filter(Boolean).join(' ');
  const skill = meta.skill_id ? `Skill：${chatEscape(meta.skill_label || meta.skill_id)}${meta.skill_version ? ` ${chatEscape(meta.skill_version)}` : ''}` : '';
  const model = meta.model_id || meta.model ? `模型：${chatEscape(meta.model_id || meta.model)}` : '';
  const intent = meta.intent_label ? `回答模式：${chatEscape(meta.intent_label)}` : '';
  const financial = meta.financial_data_as_of || meta.latest_period;
  const asOf = financial ? `财务截至 ${chatEscape(financial)}` : '';
  const quote = meta.quote_time ? `行情截至 ${chatEscape(meta.quote_time)}` : '';
  const collected = meta.source_collected_at ? `搜索于 ${chatEscape(meta.source_collected_at)}` : '';
  const forecast = meta.forecast_horizon && meta.forecast_scenario
    ? `预测 ${chatEscape(meta.forecast_horizon)} 年/${chatEscape(meta.forecast_scenario)}` : '';
  const sourceCount = Number(meta.source_count) || 0;
  const citationStatus = meta.citation_validation?.status === 'ok'
    ? '引用已校验'
    : meta.citation_validation?.status === 'warning' ? '引用需复核' : '';
  const summary = [identity && chatEscape(identity), skill, model, intent, forecast, asOf, quote, collected,
    meta.search_used ? `参考 ${sourceCount} 个来源` : '未联网搜索', citationStatus]
    .filter(Boolean).join(' · ');
  const warnings = (Array.isArray(meta.warnings) ? meta.warnings : [])
    .map(item => `<li>${chatEscape(item)}</li>`).join('');
  const sources = (Array.isArray(meta.sources) ? meta.sources : []).map(source => {
    const url = safeChatUrl(source.url);
    const title = chatEscape(source.title || url || source.id || '来源');
    const id = chatEscape(source.id || 'S?');
    const reliability = source.reliability ? ` · ${chatEscape(source.reliability)}` : '';
    return `<li><span class="chat-source-id">${id}</span>${url ? ` <a class="chat-source-link" href="${chatEscape(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : ` ${title}`}${reliability}</li>`;
  }).join('');
  const details = sources || warnings ? `<details class="chat-source-list"><summary>上下文详情${sourceCount ? `（${sourceCount} 个来源）` : ''}</summary>${sources ? `<ul>${sources}</ul>` : ''}${warnings ? `<div class="chat-warning-title">数据提示</div><ul class="chat-warnings">${warnings}</ul>` : ''}</details>` : '';
  return `<div class="chat-meta">${summary || '已加载本地分析上下文'}${details}</div>`;
}

function chatActionButton(label, title, handler) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'chat-action';
  button.textContent = label;
  button.title = title;
  button.addEventListener('click', handler);
  return button;
}

function refreshChatMessageActions(div, turnId, content) {
  if (!div || !turnId || div.classList.contains('user')) return;
  div.dataset.turnId = turnId;
  const bubble = div.querySelector('.chat-bubble');
  if (!bubble || bubble.querySelector('.chat-actions')) return;
  const actions = document.createElement('div');
  actions.className = 'chat-actions';
  actions.appendChild(chatActionButton('复制', '复制回答', () => copyChatText(content || div.querySelector('.chat-content')?.textContent || '')));
  actions.appendChild(chatActionButton('重试', '用相同问题重试', () => regenerateChatTurn(turnId, '重试')));
  actions.appendChild(chatActionButton('重新生成', '重新生成这一轮回答', () => regenerateChatTurn(turnId, '重新生成')));
  actions.appendChild(chatActionButton('删除整轮', '删除问题和回答', () => deleteChatTurn(turnId)));
  bubble.appendChild(actions);
}

function updateChatMessage(div, content, meta, options = {}) {
  if (!div) return;
  const contentNode = div.querySelector('.chat-content');
  if (contentNode) contentNode.innerHTML = renderChatMarkdown(content);
  const oldMeta = div.querySelector('.chat-meta');
  if (oldMeta) oldMeta.remove();
  if (meta && !meta.error) div.querySelector('.chat-bubble')?.insertAdjacentHTML('beforeend', renderChatMeta(meta));
  div.classList.toggle('chat-streaming', Boolean(options.streaming));
  if (!options.streaming && meta?.turn_id) refreshChatMessageActions(div, meta.turn_id, content);
}

function appendMsg(role, content, msgId, meta, turnId, options = {}) {
  const container = document.getElementById('chatMessages');
  const empty = document.getElementById('chatEmpty');
  if (empty) empty.remove();
  const cls = role === 'munger' ? 'munger' : 'user';
  const div = document.createElement('div');
  div.className = `chat-msg ${cls}${options.streaming ? ' chat-streaming' : ''}`;
  if (msgId) div.dataset.messageId = String(msgId);
  if (turnId) div.dataset.turnId = turnId;
  div.innerHTML = `<div class="chat-avatar">${role === 'munger' ? '🧠' : '👤'}</div><div class="chat-bubble"><div class="chat-content">${renderChatMarkdown(content || '')}</div>${meta ? renderChatMeta(meta) : ''}</div>`;
  container.appendChild(div);
  if (role === 'munger' && !options.streaming && turnId && !meta?.error) refreshChatMessageActions(div, turnId, content);
  return div;
}

async function loadChatMemory() {
  const code = document.getElementById('detailCode')?.textContent.trim();
  if (!code) return;
  try {
    const config = currentChatConfig();
    const query = config.skill_id ? `?skill_id=${encodeURIComponent(config.skill_id)}` : '';
    const data = await StockApi.getJson(`/api/stock/${code}/munger-chat/memory${query}`);
    const memory = data?.memory;
    const text = document.getElementById('chatMemoryText');
    const status = document.getElementById('chatMemoryStatus');
    if (text) text.textContent = memory?.summary || '暂无摘要，点击“刷新摘要”生成。';
    if (status) status.textContent = memory?.updated_at ? `（更新于 ${String(memory.updated_at).slice(0, 16)}）` : '（未生成）';
  } catch (e) {
    const status = document.getElementById('chatMemoryStatus');
    if (status) status.textContent = '（暂不可用）';
  }
}

async function refreshChatMemory() {
  const code = document.getElementById('detailCode')?.textContent.trim();
  if (!code || chatStreaming) return;
  setChatPhase('正在整理对话摘要…');
  try {
    const config = currentChatConfig();
    await StockApi.postJson(`/api/stock/${code}/munger-chat/memory`, {
      skill_id: config.skill_id,
      model_id: config.model_id || undefined
    });
    await loadChatMemory();
    setChatPhase('对话摘要已更新', true);
    setTimeout(() => setChatPhase('', false), 1800);
  } catch (e) {
    setChatPhase(e.message || '摘要刷新失败', true);
  }
}

async function consumeMungerSse(response, onEvent) {
  if (!response.ok) {
    const text = await response.text();
    let data = {};
    try { data = JSON.parse(text); } catch (e) { /* keep generic error */ }
    throw new Error(data.error || `请求失败：HTTP ${response.status}`);
  }
  if (!response.body) throw new Error('浏览器不支持流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || '';
    frames.forEach(frame => {
      const lines = frame.split(/\r?\n/);
      const event = (lines.find(line => line.startsWith('event:')) || 'event: message').slice(6).trim();
      const dataLine = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
      if (!dataLine) return;
      try { onEvent(event, JSON.parse(dataLine)); } catch (e) { /* ignore malformed keep-alive frame */ }
    });
    if (done) break;
  }
}

async function sendMungerChat() {
  const code = document.getElementById('detailCode')?.textContent.trim();
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('chatSendBtn');
  const msg = input?.value.trim();
  if (!msg || !code || chatStreaming) return;
  await loadChatCatalog();
  const config = persistChatConfig();
  const requestSeq = ++mungerRequestSeq;
  const isCurrentRequest = () => requestSeq === mungerRequestSeq && code === document.getElementById('detailCode')?.textContent.trim();
  const userDiv = appendMsg('user', msg);
  const assistantDiv = appendMsg('munger', '', null, null, null, {streaming: true});
  chatStreaming = true;
  if (input) { input.value = ''; input.disabled = true; autoGrowChatInput(input); }
  if (btn) btn.disabled = true;
  let reply = '';
  try {
    mungerStreamController?.abort();
    mungerStreamController = new AbortController();
    const response = await fetch(`/api/stock/${code}/munger-chat/stream`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'Accept': 'text/event-stream'},
      body: JSON.stringify({message: msg, ...config}),
      signal: mungerStreamController.signal
    });
    await consumeMungerSse(response, (event, data) => {
      if (!isCurrentRequest()) return;
      if (event === 'phase') {
        setChatPhase(data.label || '处理中…');
        if (data.financial_data_as_of || data.quote_time) {
          assistantDiv.dataset.context = JSON.stringify(data);
        }
      } else if (event === 'source') {
        setChatPhase(`已找到来源：${data.title || data.id || ''}`);
      } else if (event === 'delta') {
        reply += data.text || '';
        updateChatMessage(assistantDiv, reply, null, {streaming: true});
        scrollChatBottom();
      } else if (event === 'done') {
        reply = data.reply || reply;
        updateChatMessage(assistantDiv, reply, data.meta, {streaming: false});
        assistantDiv.dataset.messageId = data.assistant_message_id || '';
        assistantDiv.dataset.turnId = data.turn_id || '';
        userDiv.dataset.turnId = data.turn_id || '';
        refreshChatMessageActions(assistantDiv, data.turn_id, reply);
        setChatPhase('', false);
      } else if (event === 'error') {
        updateChatMessage(assistantDiv, `⚠️ ${data.error || '请求失败，请稍后重试。'}`, {error: true}, {streaming: false});
        setChatPhase('本轮失败，可稍后重试', true);
      }
    });
  } catch (e) {
    if (isCurrentRequest() && e.name !== 'AbortError') {
      updateChatMessage(assistantDiv, `⚠️ ${e.message || '请求失败，请稍后重试。'}`, {error: true}, {streaming: false});
      setChatPhase('本轮失败，可稍后重试', true);
    }
  } finally {
    chatStreaming = false;
    if (isCurrentRequest()) mungerStreamController = null;
    if (input && isCurrentRequest()) { input.disabled = false; input.focus(); }
    if (btn && isCurrentRequest()) btn.disabled = false;
    if (isCurrentRequest()) scrollChatBottom();
  }
}

async function loadMungerChat() {
  const code = document.getElementById('detailCode')?.textContent.trim();
  if (!code) return;
  mungerStreamController?.abort();
  await loadChatCatalog();
  const requestSeq = ++mungerRequestSeq;
  const container = document.getElementById('chatMessages');
  try {
    const [msgs] = await Promise.all([
      StockApi.getJson(`/api/stock/${code}/munger-chat`),
      loadChatMemory()
    ]);
    if (requestSeq !== mungerRequestSeq || code !== document.getElementById('detailCode')?.textContent.trim()) return;
    container.innerHTML = '';
    if (!msgs.length) container.innerHTML = '<div class="chat-empty" id="chatEmpty">向芒格提问，开始分析这只股票。</div>';
    else msgs.forEach(m => appendMsg(m.role, m.content, m.id, m.meta, m.turn_id));
    chatLoaded = true;
    scrollChatBottom();
  } catch (e) {
    if (requestSeq !== mungerRequestSeq) return;
    container.innerHTML = `<div class="chat-empty chat-error">${chatEscape(e.message || '加载失败')}</div>`;
  }
}

function useChatQuickQuestion(button) {
  const input = document.getElementById('chatInput');
  if (!input || chatStreaming) return;
  input.value = button?.textContent?.trim() || '';
  autoGrowChatInput(input);
  input.focus();
}

function autoGrowChatInput(input) {
  if (!input) return;
  input.style.height = 'auto';
  input.style.height = `${Math.min(Math.max(input.scrollHeight, 42), 130)}px`;
}

function copyChatText(text) {
  const write = navigator.clipboard?.writeText
    ? navigator.clipboard.writeText(text)
    : Promise.reject(new Error('clipboard unavailable'));
  write.then(() => showToast('已复制回答', 'success')).catch(() => showToast('复制失败，请手动选择文本', 'error'));
}

async function deleteChatMsg(msgId, btn) {
  if (!confirm('删除这条消息？')) return;
  try {
    await StockApi.deleteJson(`/api/stock/${document.getElementById('detailCode').textContent.trim()}/munger-chat?msg_id=${Number(msgId)}`);
    btn?.closest('.chat-msg')?.remove();
  } catch (e) { showToast(e.message || '删除失败', 'error'); }
}

async function deleteChatTurn(turnId) {
  if (!turnId || !confirm('删除这一轮问题和回答？')) return;
  try {
    const code = document.getElementById('detailCode').textContent.trim();
    await StockApi.deleteJson(`/api/stock/${code}/munger-chat?turn_id=${encodeURIComponent(turnId)}`);
    document.querySelectorAll('.chat-msg').forEach(node => {
      if (node.dataset.turnId === turnId) node.remove();
    });
  } catch (e) { showToast(e.message || '删除整轮失败', 'error'); }
}

async function regenerateChatTurn(turnId, label = '重新生成') {
  if (!turnId || chatStreaming) return;
  const code = document.getElementById('detailCode').textContent.trim();
  setChatPhase(`正在${label}…`);
  try {
    await StockApi.postJson(`/api/stock/${code}/munger-chat/regenerate`, {turn_id: turnId});
    await loadMungerChat();
    setChatPhase('', false);
  } catch (e) { setChatPhase(e.message || `${label}失败`, true); }
}

async function clearMungerChat() {
  const code = document.getElementById('detailCode')?.textContent.trim();
  if (!code || !confirm('确定清空全部对话和长期摘要？')) return;
  try {
    await StockApi.deleteJson(`/api/stock/${code}/munger-chat`);
    await loadMungerChat();
  } catch (e) { showToast(e.message || '清空失败', 'error'); }
}

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('chatInput');
  if (!input) return;
  ['chatSkillSelect', 'chatModelSelect', 'chatForecastHorizon', 'chatForecastScenario']
    .forEach(id => document.getElementById(id)?.addEventListener('change', onChatConfigChange));
  loadChatCatalog();
  input.addEventListener('input', () => autoGrowChatInput(input));
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && !chatStreaming) {
      event.preventDefault();
      sendMungerChat();
    }
  });
  autoGrowChatInput(input);
});

let stickyEditId = null;

function goSticky() {
  // Legacy - kept for potential reference but no longer used standalone
  loadStickyNotes();
}

async function loadStickyNotes() {
  const code = document.getElementById('detailCode') ? document.getElementById('detailCode').textContent.trim() : '';
  if (!code) return;
  try {
    const notes = await StockApi.getJson('/api/sticky-notes?stock_code=' + code);
    if (code !== (document.getElementById('detailCode')?.textContent.trim() || '')) return;
    const list = document.getElementById('stickyList');
    if (!notes.length) {
      list.innerHTML = '<div style="text-align:center;color:#bbb;padding:60px">还没有便利贴，点击「+ 新建」开始</div>';
      return;
    }
    list.innerHTML = notes.map(n => {
      const time = (n.created_at || '').replace('T',' ').substring(0,16);
      const stockTag = n.stock_code ? `<span style="font-size:11px;color:#4a6cf7;background:#f0f5ff;padding:2px 8px;border-radius:10px">${esc(n.stock_code)}</span>` : '';
      const titleHtml = n.title ? `<div style="font-weight:600;font-size:15px;margin-bottom:8px">${esc(n.title)}</div>` : '';
      // Auto-detect images and links in content
      let body = esc(n.content);
      // data:image → img tags
      body = body.replace(/(data:image\/[^;]+;base64,[a-zA-Z0-9+/=]+)/gi,
        '<img src="$1" style="max-width:100%;max-height:300px;border-radius:8px;margin:4px 0;display:block;cursor:pointer" onclick="viewImage(this.src)" onerror="this.style.display=none">');
      // Image URLs → img tags
      body = body.replace(/(https?:\/\/\S+\.(?:png|jpg|jpeg|gif|webp|svg)(?:\?\S*)?)/gi,
        '<img src="$1" style="max-width:100%;max-height:300px;border-radius:8px;margin:4px 0;display:block;cursor:pointer" onclick="viewImage(this.src)" onerror="this.style.display=\'none\'">');
      // Local image paths → img tags
      body = body.replace(/(\/data\/images\/\S+\.(?:png|jpg|jpeg|gif|webp|svg))/gi,
        '<img src="$1" style="max-width:100%;max-height:300px;border-radius:8px;margin:4px 0;display:block;cursor:pointer" onclick="viewImage(this.src)" onerror="this.style.display=\'none\'">');
      // Other URLs → clickable links
      body = body.replace(/(https?:\/\/[^\s<>]+)/g,
        '<a href="$1" target="_blank" style="color:#4a6cf7">$1</a>');
      body = body.replace(/\n/g, '<br>');

      return `<div class="sticky-card" style="background:#fffbe6">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px">
          <span style="font-size:13px;color:#999">${time}</span>
          <div class="sticky-actions">
            <button onclick="editSticky(${n.id},this)" title="编辑" style="background:none;border:none;cursor:pointer;color:#bbb;font-size:14px;padding:2px 6px">✎</button>
            <button onclick="deleteSticky(${n.id},this)" title="删除" style="background:none;border:none;cursor:pointer;color:#bbb;font-size:14px;padding:2px 6px">✕</button>
          </div>
        </div>
        ${titleHtml}
        ${stockTag ? `<div style="margin-bottom:8px">${stockTag}</div>` : ''}
        <div style="font-size:14px;line-height:1.7;word-break:break-word">${body}</div>
      </div>`;
    }).join('');
  } catch(e) {
    document.getElementById('stickyList').innerHTML = '<div style="text-align:center;color:#e74c3c;padding:40px">加载失败</div>';
  }
}

function openStickyModal(id, title, content) {
  stickyEditId = id || null;
  document.getElementById('stickyModalTitle').textContent = id ? '编辑便利贴' : '新建便利贴';
  document.getElementById('stickyTitle').value = title || '';
  document.getElementById('stickyContent').value = content || '';
  // 填充股票下拉 + 选中当前股票
  const sel = document.getElementById('stickyStock');
  const curCode = document.getElementById('detailCode') ? document.getElementById('detailCode').textContent : '';
  if (sel.options.length <= 1) {
    StockApi.getJson('/api/stocks?page=1&page_size=200').then(d => {
      d.data.forEach(s => { const o = document.createElement('option'); o.value = s.code; o.textContent = s.code + ' ' + s.name; sel.appendChild(o); });
      sel.value = curCode;
    });
  } else {
    sel.value = curCode;
  }
  document.getElementById('stickyModalOverlay').classList.add('active');
}

async function editSticky(id, btn) {
  // Fetch notes to find this one
  const notes = await StockApi.getJson('/api/sticky-notes?stock_code=' + (document.getElementById('detailCode')?.textContent || ''));
  const n = notes.find(x => x.id === id);
  if (n) openStickyModal(n.id, n.title, n.content);
}

function closeStickyModal() { document.getElementById('stickyModalOverlay').classList.remove('active'); stickyEditId = null; }

async function saveSticky() {
  const title = document.getElementById('stickyTitle').value.trim();
  const content = document.getElementById('stickyContent').value.trim();
  const stock = document.getElementById('stickyStock').value.trim();
  // 兜底：如果下拉未填充（仅"不关联"一项），自动用当前股票代码
  const finalStock = stock || (document.getElementById('stickyStock').options.length <= 1 ? (document.getElementById('detailCode')?.textContent || '') : stock);
  if (!content && !title) { alert('请输入内容'); return; }
  const body = { note_type: 'text', title, content, stock_code: finalStock };
  const method = stickyEditId ? 'PUT' : 'POST';
  const url = '/api/sticky-notes' + (stickyEditId ? '/' + stickyEditId : '');
  try {
    if (stickyEditId) {
      await StockApi.putJson(url, body);
    } else {
      await StockApi.postJson(url, body);
    }
    closeStickyModal();
    loadStickyNotes();
  } catch(e) {}
}

async function deleteSticky(id, btn) {
  if (!confirm('确定删除？')) return;
  try {
    await StockApi.deleteJson('/api/sticky-notes/' + id);
    btn.closest('.sticky-card').style.opacity = '0';
    setTimeout(loadStickyNotes, 300);
  } catch(e) {}
}
