let chatLoaded = false;

async function loadMungerChat() {
  const code = document.getElementById('detailCode').textContent;
  if (!code) return;
  const container = document.getElementById('chatMessages');

  try {
    const res = await fetch('/api/stock/' + code + '/munger-chat');
    const msgs = await res.json();
    container.innerHTML = '';
    if (!msgs.length) {
      container.innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
    } else {
      msgs.forEach(m => appendMsg(m.role, m.content, m.id));
    }
    chatLoaded = true;
    scrollChatBottom();
  } catch(e) {
    container.innerHTML = '<div class="chat-empty" style="color:#e74c3c">加载失败</div>';
  }
}

function appendMsg(role, content, msgId) {
  const container = document.getElementById('chatMessages');
  const empty = document.getElementById('chatEmpty');
  if (empty) empty.remove();

  const cls = role === 'munger' ? 'munger' : 'user';
  const avatar = role === 'munger' ? '🧠' : '👤';

  // Simple markdown render
  let html = esc(content);
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\n\n/g, '<br><br>');

  const delBtn = msgId ? `<button class="chat-delete" onclick="deleteChatMsg(${msgId},this)" title="删除">✕</button>` : '';

  const div = document.createElement('div');
  div.className = 'chat-msg ' + cls;
  div.innerHTML = `
    <div class="chat-avatar">${avatar}</div>
    <div class="chat-bubble">${html}${delBtn}</div>`;
  container.appendChild(div);
}

async function sendMungerChat() {
  const code = document.getElementById('detailCode').textContent;
  const input = document.getElementById('chatInput');
  const btn = document.getElementById('chatSendBtn');
  const msg = input.value.trim();
  if (!msg || !code) return;

  // Show user message immediately
  appendMsg('user', msg);
  input.value = '';
  input.disabled = true;
  btn.disabled = true;
  scrollChatBottom();

  // Typing indicator
  const container = document.getElementById('chatMessages');
  const typing = document.createElement('div');
  typing.className = 'chat-msg munger';
  typing.id = 'chatTyping';
  typing.innerHTML = '<div class="chat-avatar">🧠</div><div class="chat-bubble"><div class="chat-typing"><span></span><span></span><span></span></div></div>';
  container.appendChild(typing);
  scrollChatBottom();

  try {
    const res = await fetch('/api/stock/' + code + '/munger-chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: msg})
    });
    const data = await res.json();
    // Remove typing
    const t = document.getElementById('chatTyping');
    if (t) t.remove();
    appendMsg('munger', data.reply || data.error || '...');
  } catch(e) {
    const t = document.getElementById('chatTyping');
    if (t) t.remove();
    appendMsg('munger', '网络错误，请重试。');
  }
  input.disabled = false;
  btn.disabled = false;
  input.focus();
  scrollChatBottom();
}

async function deleteChatMsg(msgId, btn) {
  if (!confirm('删除这条消息？')) return;
  try {
    await fetch('/api/stock/' + document.getElementById('detailCode').textContent + '/munger-chat?msg_id=' + msgId, {method: 'DELETE'});
    btn.closest('.chat-msg').remove();
    // Show empty if no messages left
    if (!document.querySelector('.chat-msg')) {
      document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
    }
  } catch(e) {}
}

async function clearMungerChat() {
  const code = document.getElementById('detailCode').textContent;
  if (!confirm('确定清空全部对话？')) return;
  try {
    await fetch('/api/stock/' + code + '/munger-chat', {method: 'DELETE'});
    document.getElementById('chatMessages').innerHTML = '<div class="chat-empty">向芒格提问，开始分析这只股票。</div>';
  } catch(e) {}
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
  const code = document.getElementById('detailCode') ? document.getElementById('detailCode').textContent : '';
  if (!code) return;
  try {
    const res = await fetch('/api/sticky-notes?stock_code=' + code);
    const notes = await res.json();
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
    fetch('/api/stocks?page=1&page_size=200').then(r => r.json()).then(d => {
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
  const res = await fetch('/api/sticky-notes?stock_code=' + (document.getElementById('detailCode')?.textContent || ''));
  const notes = await res.json();
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
    await fetch(url, { method, headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    closeStickyModal();
    loadStickyNotes();
  } catch(e) {}
}

async function deleteSticky(id, btn) {
  if (!confirm('确定删除？')) return;
  try {
    await fetch('/api/sticky-notes/' + id, { method: 'DELETE' });
    btn.closest('.sticky-card').style.opacity = '0';
    setTimeout(loadStickyNotes, 300);
  } catch(e) {}
}
