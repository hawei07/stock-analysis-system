# 芒格视角分析 — 集成模式参考

## 架构

```
Flask API → 查 DB 财务数据 → 6 维度 Web 搜索 → DeepSeek V4 API → 缓存 → 前端渲染
```

## 关键技术点

### DuckDuckGo Web 搜索（免 API Key）

当 `pip install duckduckgo-search` 在 Windows 上失败时，直接用 requests 抓取 Lite 页面：

```python
def _web_search(query):
    resp = requests.post("https://lite.duckduckgo.com/lite/",
        data={"q": query},
        headers={"User-Agent": "Mozilla/5.0..."}, timeout=12)
    # 正则提取 result-link + result-snippet
    results = re.findall(r'<a[^>]*class="result-link"[^>]*>([^<]+)</a>.*?'
                         r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
                         resp.text, re.DOTALL | re.IGNORECASE)
```

### DeepSeek API 调用（OpenAI 兼容 SDK）

```python
from openai import OpenAI
client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role":"system","content":SYSTEM_PROMPT},
              {"role":"user","content":user_prompt}],
    temperature=0.7, max_tokens=4000)
```

### API Key 存储模式

- MySQL `system_config` 表（key-value）
- `config_manager.py` 读写，API 返回时掩码（`****` + 末4位）
- 前端 ⚙ 按钮 → 弹窗输入 → `PUT /api/config`
- 不依赖 `config.py`，不提交 Git

### 缓存策略

- `munger_cache` 表，按 `stock_code` 唯一键
- 分析结果写 JSON，下次命中直接返回
- 缓存命中标记 `cached: true`，前端显示"(缓存)"
- `?refresh=1` 强制重新分析

## 深度分析的 Prompt 工程

### System Prompt 设计

必须包含完整分析框架，不是简版：
- 5大心智模型（逆向思考、多元思维、Lollapalooza、能力圈、激励结构）
- 护城河评估维度（品牌/成本/网络效应/转换成本/政策/资源壁垒）
- 输出结构要求（直接结论→护城河拆解→逆向思考→激励结构→Lollapalooza→三筐分类）
- 表达风格指令（短句、否定优先、中文）

### 数据打包

User Prompt 必须结构化：
1. 股票基本信息
2. 近10年财务数据表格（营收/利润/ROE/ROIC/负债率/EPS）
3. 关键指标摘要（ROE均值/趋势、现金流质量、CAGR）
4. 6维度Web搜索结果（护城河/管理层/财务/风险/行业/估值）
5. 明确的分析指令

### 输出处理

- DeepSeek 返回 Markdown，最后一行嵌入 JSON `{"score":80,"basket":"YES"}`
- 前端简单 Markdown→HTML 转换（`##`→h3, `**`→strong, `-`→li）
- 评分圆环颜色：≥70绿色/≥40橙色/<40红色

## 对话芒格 Chat 架构

### 数据模型

```sql
CREATE TABLE munger_chats (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stock_code VARCHAR(10) NOT NULL,
    role ENUM('user','munger') NOT NULL,
    content LONGTEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX(stock_code)
);
```

每只股票独立对话历史，ID 全局递增支持消息级删除。

### API 设计（三合一路由）

```
GET  /api/stock/<code>/munger-chat          → [{id, role, content}]
POST /api/stock/<code>/munger-chat {message} → {reply, role}
DELETE /api/stock/<code>/munger-chat?msg_id=N → {ok: true/false}
DELETE /api/stock/<code>/munger-chat           → {ok: true, deleted: N}
```

### 消息处理流程

1. 保存 user 消息 → 检测 URL（抓取） → 检测搜索触发词（Web 搜索） → 打包上下文 → DeepSeek → 保存 munger 回复
2. 上下文打包：财务摘要(PE/ROE/ROIC/负债率/EPS) + 最近10条历史 + URL内容 + 搜索结果
3. Chat System Prompt = 芒格分析 System Prompt + 对话模式指令（150-300字/回复、直接称呼"你"）

### URL 抓取 + SSRF 防护

```python
def _fetch_url_content(url):
    # SSRF 防护：禁止内网/本地地址
    forbidden = ('127.', 'localhost', '0.0.0.0', '10.', '172.16.', '192.168.')
    if any(f'://{p}' in url.lower() for p in forbidden):
        return "(不允许访问内网地址)"
    # 抓取 → 去 script/style 标签 → 去 HTML → 限 6000 字
    resp = requests.get(url, ...)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    return text[:6000]
```

### 前端 Chat UI 规范

- 聊天面板: `display:flex; flex-direction:column; height:calc(100vh-260px); max-height:700px`
- 芒格气泡: 靠左、灰底 `#f5f5f5`、🧠 头像
- 用户气泡: 靠右、蓝底 `#4a6cf7` 白字、👤 头像
- 删除按钮: 始终可见的 ✕ 圆形图标（20x20px、白色圆形底、右上角绝对定位、悬浮变红）
- 发送中: 输入框禁用 + 三个点 typing 动画
- Markdown 渲染: `##`→h3, `**`→strong, `-`→li, `\n\n`→`<br><br>`

- **Web 搜索超时**：DuckDuckGo 偶尔限流，加 0.5s 间隔，超时设为 12s
- **DeepSeek 返回非 JSON**：用正则提取最后一行 JSON，解析失败 fallback 到本地评分
- **分析太浅**：检查 max_tokens（至少 3000）、System Prompt 是否完整、搜索维度是否 ≥ 4
- **PE/估值数据编造（严重）**: DeepSeek 会根据训练数据自行编造 PE 值。必须将 `stocks.pe_ttm`（数据库实时 PE）明确写入 User Prompt，并标注"来自数据库实时数据"。茅台的教训：DB 里 PE=18.05，AI 编了个"30倍PE"，直接扭曲了 YES/NO 筐判定
- **两次分析结果不一致**: `temperature` 必须设为 0.3（不是 0.7）以确保输出稳定。0.7 的随机性导致同股同数据但结论天差地别
- **代码升级后旧缓存污染**: 必须用 `CACHE_VERSION` 字符串（如 `"v2.2"`）作为缓存键一部分。每次改 munger.py 时递增版本号，旧版本缓存自动失效。不加版本号会导致 v1 的"30倍PE"分析在新代码下继续返回

## 分析质量 Checklist

开发/调试芒格分析时，逐项检查：

- [ ] `_gather_financials` 是否包含了 `pe_ttm`（从 stocks 表，不是 hardcode）
- [ ] User Prompt 是否包含 PE(TTM) 行，标注"来自数据库实时数据"
- [ ] `temperature` 是否为 0.3（不是 0.7）
- [ ] `max_tokens` 是否 ≥ 4000
- [ ] 搜索维度是否 ≥ 4（护城河/管理层/风险/行业/估值）
- [ ] `CACHE_VERSION` 是否已递增（如果改了 System Prompt 或数据结构）
- [ ] 缓存是否存在 v2.1 旧数据（用 `TRUNCATE munger_cache` 清空重来）
- [ ] 分析输出中 PE 是否匹配数据库实际值（不应出现 AI 编造的数字）
