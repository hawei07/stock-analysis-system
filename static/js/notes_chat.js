let chatLoaded = false;
let mungerRequestSeq = 0;

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
      .replace(/\[S(\d+)\]/g, '<span class="chat-citation">[S$1]</span>');
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
  const summary = [identity && chatEscape(identity), intent, period, yoy,
    meta.search_used ? `已参考 ${sourceCount} 个来源` : '未联网搜索'].filter(Boolean).join(' · ');
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
