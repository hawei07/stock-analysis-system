# Web 抓取三层回退策略

## 为什么需要三层

不同网站需要不同的抓取策略：

| 网站类型 | 直接 HTTP | Jina Reader | Google Cache |
|---------|----------|-------------|-------------|
| 新浪财经/东方财富 | ✅ HTML + 正则 | ✅ 纯净 Markdown | ✅ |
| 雪球 (xueqiu) | ❌ JS SPA，85KB 框架 HTML | ❌ 只拿到导航栏 | ✅ 渲染后快照 |
| 其他 SPA | ❌ | ❌ | ✅ |

## 实现（Python）

```python
def fetch_url_content(url: str) -> str:
    # 1. Jina Reader — 纯净 Markdown，免费无 Key
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", headers={
            "Accept": "text/markdown"
        }, timeout=15)
        if resp.status_code == 200 and len(resp.text) > 100:
            return resp.text[:6000]
    except Exception: pass

    # 2. Google Cache — JS 渲染页面的救星
    try:
        cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
        r = requests.get(cache_url, timeout=10)
        if r.status_code == 200 and len(r.text) > 500:
            return strip_html(r.text)[:6000]
    except Exception: pass

    # 3. 直接请求 + 正则剥 HTML — 兜底
    try:
        r = requests.get(url, timeout=10)
        return strip_html(r.text)[:6000]
    except Exception as e:
        return f"(抓取失败: {e})"
```

## DuckDuckGo 搜索解析

DuckDuckGo Lite HTML 结构会变化。当前（2026-07）有效匹配：

```python
links = re.findall(r'<a[^>]*href="([^"]+)"[^>]*>\s*(.+?)\s*</a>', text, re.DOTALL)
# 过滤内部链接: 'duckduckgo' in href, href.startswith('//')
```

旧版 `class="result-link"` / `class="result-snippet"` 已废弃。如果搜索突然全空，先 `curl https://lite.duckduckgo.com/lite/ -d 'q=test'` 看实际 HTML。
