# Web 抓取三层回退策略

`munger.py::_fetch_url_content()` 实现三层回退：

## 1. Jina Reader（首选）

```python
resp = requests.get(f"https://r.jina.ai/{url}", headers={
    "Accept": "text/markdown",
    "User-Agent": "Mozilla/5.0 (compatible; stock-analysis/1.0)"
}, timeout=15)
```
- 免费，无需 API Key
- 返回纯净 Markdown，自动去广告/导航/脚本
- 效果：公开页面 6000 字纯净 Markdown
- 局限：雪球等需登录页面返回空（~6 chars）→ 自动进入下一层

## 2. Google Cache（雪球救星）

```python
cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
resp = requests.get(cache_url, headers={
    "User-Agent": "Mozilla/5.0..."
}, timeout=10)
```
- 雪球是 JS SPA，直接 HTTP 返回 85KB 框架 HTML，无实际内容
- Google Cache 存储了渲染后的快照，能拿到文章全文
- 效果：雪球文章 4832 chars，含"多方博弈结果"等原文
- 局限：不是所有页面都有缓存

## 3. 直接 HTTP + 正则（兜底）

```python
resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0..."}, timeout=10)
text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
text = re.sub(r'<[^>]+>', ' ', text)
text = re.sub(r'\s+', ' ', text).strip()
```
- 最终兜底，去 script/style 标签后取纯文本

## 效果对比

| | 正则剥 HTML | Jina Reader | Google Cache |
|------|------|------|------|
| 新浪财经 | 杂乱文本 | 6000字 Markdown | N/A |
| 东方财富 | 大量噪音 | 6000字 Markdown | N/A |
| 雪球 xueqiu | 513 chars(框架) | 6 chars(空) | **4832 chars(全文)** |

## SSRF 防护

```python
forbidden = ('127.', 'localhost', '0.0.0.0', '10.', '172.16.', '192.168.')
if any(url.lower().startswith(f'http://{p}') or f'://{p}' in url.lower() for p in forbidden):
    return "(不允许访问内网地址)"
```

禁止用户通过 URL 输入访问内网地址。
