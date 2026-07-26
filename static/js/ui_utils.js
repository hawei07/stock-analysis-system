function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast toast-' + type + ' show';
  setTimeout(() => { t.className = 'toast'; }, 2500);
}


function esc(s) { return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// 图片查看器
function viewImage(src) {
  const overlay = document.createElement('div');
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.85);z-index:200;display:flex;align-items:center;justify-content:center;cursor:pointer';
  overlay.innerHTML = '<img src="' + src + '" style="max-width:95vw;max-height:95vh;border-radius:8px">';
  overlay.onclick = function() { overlay.remove(); };
  document.body.appendChild(overlay);
}

// 便利贴内容区粘贴图片支持
document.addEventListener('DOMContentLoaded', function() {
  const ta = document.getElementById('stickyContent');
  if (ta) {
    ta.addEventListener('paste', function(e) {
      const items = e.clipboardData?.items;
      if (!items) return;
      for (let item of items) {
        if (item.type.startsWith('image/')) {
          e.preventDefault();
          const blob = item.getAsFile();
          const reader = new FileReader();
          reader.onload = function(ev) {
            const imgTag = '\n[图片]\n';
            const cursor = ta.selectionStart;
            const before = ta.value.substring(0, cursor);
            const after = ta.value.substring(cursor);
            ta.value = before + ev.target.result + after;
          };
          reader.readAsDataURL(blob);
          break;
        }
      }
    });
  }
});
