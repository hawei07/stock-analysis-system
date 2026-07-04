---
name: stock-analysis-system
description: Stock analysis system — Flask + MySQL + vanilla JS frontend。Agency Agents 驱动。已移除芒格视角分析，保留对话芒格(DeepSeek V4 Pro+完整芒格Skill+三层网页抓取)+便利贴(标题+内容混排+粘贴图片+点击看原图+下拉选关联股票)。PE-TTM四轮演进：年报→TTM→披露延迟→归母净利润/总股本(8.96=腾讯实时)。
---

# Stock Analysis System

Project: `E:\stock-analysis-system` | Flask 3.x + MySQL 8.4 | Port 5002

## Startup

```bash
cd /e/stock-analysis-system && python app.py
# Runs at http://127.0.0.1:5002
```

## Environment

- **Python**: `python` (3.11, via Hermes venv). Use `uv pip install` for packages.
- **MySQL**: Running on `E:\MySQL\bin\mysqld.exe`, root with NO password (empty string).
- **Shell**: git-bash/MSYS2 — POSIX syntax, MSYS paths like `/e/...` work.
- `config.py` password may differ between local (empty) and remote — never commit the local empty-password change.
- Flask `debug=True` is recommended to avoid Jinja2 template caching (otherwise every HTML edit requires a restart). Auto-reloads on any source change.

## Git 远程同步

```bash
# 从 GitHub 覆盖本地（丢弃本地未推送的改动）
cd /e/stock-analysis-system && git fetch origin && git reset --hard origin/main
```

> 仅本地 commit（未 push）会被丢弃。在 `git reset --hard` 前确认无重要本地改动。

## DeepSeek V4 + 芒格视角分析（已移除）

> ⚠️ 「🧠 芒格视角」标签和 `/api/stock/<code>/munger` 路由已删除。前端 tab 按钮、panel HTML、`loadMunger()` JS、CSS 样式（`.munger-card`/`.munger-score`/`.munger-basket` 等）全部移除。仅保留 `munger.py` 中的共享函数（`_gather_financials`/`_web_search`/`_fetch_url_content`/`_calc_score`）供对话芒格使用。如需恢复，git revert cee17f6。

## 💬 对话芒格 Chat

`POST /api/stock/<code>/munger-chat` — 实时对话，每只股票独立历史（`munger_chats` 表）。

**消息处理流程**:
1. 保存用户消息到 `munger_chats` (role=user)
2. 检测 URL → 三层抓取（Jina → Google Cache → 直接请求）
3. 检测搜索触发词（?/怎么/为什么/查/搜索/新闻 等）→ Web 搜索 "*** 代码} {消息前40字}"
4. **深度抓取**：搜索结果中的前 3 条链接用三层回退获取全文（每篇 2000 字），喂给 DeepSeek
5. 打包：财务摘要(PE/ROE/ROIC/负债率/EPS) + 最近10条历史 + URL内容 + 搜索结果正文
6. DeepSeek V4 Pro (model=`deepseek-v4-pro`, temperature=0.3, max_tokens=1000) ← 曾因 600 过低导致回复截断至 ~165 字
7. 保存回复到 `munger_chats` (role=munger) → 返回前端

**Chat System Prompt**: 完整芒格人格（"你是查理·芒格"），包含 5 大心智模型 + 8 条启发式 + 表达 DNA + Agentic 工作流 + 三筐输出格式 + 评分规则。替换早期 8 行简陋版本。

**API**:
- `GET /api/stock/<code>/munger-chat` → 历史消息 `[{id, role, content}]`
- `POST /api/stock/<code>/munger-chat {message}` → `{reply, role}`
- `DELETE /api/stock/<code>/munger-chat?msg_id=N` → 删单条
- `DELETE /api/stock/<code>/munger-chat` → 清空全部

**前端**: 股票详情页「💬 对话芒格」标签 → 气泡聊天（芒格左灰底 🧠，用户右蓝底 👤）+ Markdown 渲染 + ✕ 悬浮删除 + 发送时加载动画

## 开发流程约定（强制执行）

> **核心规则：所有开发任务必须通过 Agency Agents 五专家流程执行。Hermes 主会话仅负责流程调度，不直接写代码。**

### 强制工作流

```
用户提出需求
  ↓
1. UI Designer        → agency_agents_load agent=ui-designer       → 设计页面与交互
2. Backend Architect  → agency_agents_load agent=backend-architect → 写后端代码（路由/模型/API）
3. Frontend Developer → agency_agents_load agent=frontend-developer → 实现前端
4. API Tester         → agency_agents_load agent=api-tester        → 测试所有端点
5. Code Reviewer      → agency_agents_load agent=code-reviewer     → 审查代码
6. Git Workflow Master → agency_agents_load agent=git-workflow-master → 分支策略+提交
```

| 阶段 | 专家 | Slug | 部门 | 用途 |
|------|------|------|------|------|
| 🎨 设计 | UI Designer | ui-designer | design | 页面布局、交互设计、组件样式 |
| 🔧 后端 | Backend Architect | backend-architect | engineering | 系统设计、API开发、数据库架构、Python/Flask |
| 💻 前端 | Frontend Developer | frontend-developer | engineering | HTML/CSS/JS 实现、Vanilla JS 单页应用 |
| 🧪 测试 | API Tester | api-tester | testing | Flask API 测试、性能验证 |
| 🔍 审查 | Code Reviewer | code-reviewer | engineering | 代码审查、安全、可维护性 |
| 🌿 分支 | Git Workflow Master | git-workflow-master | engineering | 分支策略、commit 规范、合并流程 |

### 新功能开发：先给方案再看

在动手写任何代码前，先用文字描述：API 设计、数据流、前端布局、交互规格。用户确认后再实现。

### 主会话职责边界

- ✅ 加载专家（`agency_agents_load`）
- ✅ 流程调度（决定先加载哪个专家）
- ✅ 结果汇报
- ❌ 直接写 HTML/CSS/JS
- ❌ 直接写 Python 路由/模型
- ❌ 直接用 `patch()` 改代码
- ❌ 用 `execute_code` 跑临时脚本代替专家执行

## System Config (API Keys)

- **存储**：`system_config` MySQL 表（key-value, `ON DUPLICATE KEY UPDATE`）
- **模块**：`config_manager.py` → `get_config()`/`set_config()`/`get_all_config()`
- **API**：`GET /api/config`（掩码 `****`+末4位） / `PUT /api/config`
- **前端**：⚙ 齿轮按钮 → 弹窗（password 字段）
- **约定**：API Key 永不存 `config.py`（提交 Git 的）

## Project Structure

| File | Role |
|---|---|
| `app.py` | Flask routes (all API + page serving) |
| `models.py` | Stock CRUD (raw SQL, no ORM) |
| `db.py` | MySQL connection pool (pool_size=5) |
| `config.py` | DB connection params |
| `config_manager.py` | System config read/write (system_config table) |
| `munger.py` | 对话芒格引擎（财务打包+Web搜索+三层页面抓取+DeepSeek聊天API） |
| `templates/index.html` | Single-page frontend (Vanilla JS) |

## Agency Agents 开发工作流（强制执行）

每次开发任务必须按需加载以下 Agency 专家：

| 阶段 | 专家 | Slug | 部门 | 用途 |
|------|------|------|------|------|
| 🎨 设计 | UI Designer | ui-designer | design | 页面布局、交互设计、组件样式 |
| 💻 前端 | Frontend Developer | frontend-developer | engineering | HTML/CSS/JS 实现、Vanilla JS 单页应用 |
| 🔍 审查 | Code Reviewer | code-reviewer | engineering | PR/代码审查、安全、可维护性 |
| 🌿 分支 | Git Workflow Master | git-workflow-master | engineering | 分支策略、commit 规范、合并流程 |
| 🧪 测试 | API Tester | api-tester | testing | Flask API 测试、性能验证 |

### 使用方式

```
# 搜索匹配的专家
agency_agents_search query="需要设计数据表格的UI"

# 加载专家方法论（加载后我会化身为该专家直接工作）
agency_agents_load agent=ui-designer task="设计股票详情页"
agency_agents_load agent=frontend-developer task="实现股票对比功能"
agency_agents_load agent=code-reviewer task="审查最近3个commit的代码"
agency_agents_load agent=git-workflow-master task="给本次feature设计分支策略"
agency_agents_load agent=api-tester task="测试新增的财务数据接口"
```

> ⚠️ `agency_agents_delegate` 在主会话中不可用（需要子 Agent 上下文）。实际工作流：`search` 找专家 → `load` 加载方法论 → 我化身专家直接执行。

多专家协作顺序：设计 → 前端 → 测试 → 审查 → 分支管理。

> **已知限制**：`agency_agents_delegate` 可能返回 `"delegate_task requires a parent agent context"`，此时改为 `agency_agents_load` 获取专家 prompt，手动按其方法论执行分析。Financial Analyst / Investment Researcher 等分析类专家不建议 delegate，直接 load + 手动执行效果更好。

> 安装与配置详见 `references/agency-agents-setup.md`。

## Database Tables

- **stocks**: core stock info (code UNIQUE)
- **dividends**: yearly dividend data (UNIQUE: stock_code, fiscal_year)
- **custom_financials**: custom financial indicators from eastmoney (UNIQUE: stock_code, fiscal_year, report_period)
- **balance_sheets**: 49-column balance sheet from Sina Finance (UNIQUE: stock_code, fiscal_year, report_period)
- **system_config**: Key-value 配置存储（PK: config_key），存 DeepSeek API Key 等
- **munger_cache**: 芒格分析缓存（PK: stock_code, cache_version），存 `analysis_json` JSON。`cache_version` 字段用于代码升级后自动失效旧缓存。
- **munger_chats**: 对话芒格历史（PK: id），按 `stock_code` 隔离，`role` 区分 user/munger
- **sticky_notes**: 便利贴（PK: id），字段 `title` + `content`(LONGTEXT) + `stock_code`，按股票过滤
- **income_statements**: 利润表（PK: id, UNIQUE: stock_code+fiscal_year+report_period），30列从新浪财经抓取
- **cash_flows**: 现金流量表（PK: id, UNIQUE: stock_code+fiscal_year+report_period），30列从新浪财经抓取。列名由 `CASHFLOW_ROW_MAP` 定义（`cf_sales_goods`/`cf_oper_net`/`cf_invest_net` 等），建表时必须以代码中实际列名为准。
- **valuation_history**: PE 历史数据（PK: id），字段 `stock_code`/`trade_date`/`pe_ttm`/`close_price`

### report_period field

Both `custom_financials` and `balance_sheets` have a `report_period` column:
`ENUM('FY','Q1','Q2','Q3')` — FY=年报, Q1=一季报, Q2=中报, Q3=三季报.

All data stored is **cumulative** (as reported). Single-quarter values are computed on the fly:
- Q1 single = Q1 cumulative
- Q2 single = Q2 cumulative - Q1 cumulative
- Q3 single = Q3 cumulative - Q2 cumulative
- FY single = FY cumulative - Q3 cumulative

## API: Quarterly Report Parameters

Both `/api/stock/<code>/financials` and `/api/stock/<code>/balance-sheet` accept:
- `period`: `FY` (default), `Q1`, `Q2`, `Q3`, or `all` (all quarters)
- `view`: `cumulative` (default, as-reported) or `single` (single-quarter computed)

**Single-quarter backend pattern** (critical):
```
need_single = (view == "single" and period != "FY")
query_period = None if need_single else (None if period == "all" else period)
```
When `need_single` is true, query ALL report periods (not just the requested one),
compute single-quarter by subtracting previous period, then filter to requested period.

## Frontend Quarter Selectors

Each tab's toolbar has:
- `finPeriod/bsPeriod`: 年报|季报 dropdown
- `finQuarter/bsQuarter`: 全部|一季报|中报|三季报 (visible when 季报 selected)
- `finView/bsView`: 累计|单季度 (visible when 季报 selected)

`actualPeriod = period === 'all' ? quarter : period` — sent to API.

## Frontend Rendering Pitfalls

1. **`isQuarterly` detection**: `data[0].report_period` is WRONG — sorted data puts FY first. Use `new Set(data.map(d => d.report_period))` and check `!(periods.size === 1 && periods.has('FY'))`.

2. **YoY for quarterly**: compare same period across years: `prevKey = (d.fiscal_year - 1) + '|' + d.report_period`. Data map must use composite keys `year|period`.

3. **Quarterly table**: Uses same "原值 | 同比%" column pairs as annual mode. Sort/drag handles hidden in quarterly mode.

## Stock Comparison Feature

Both tabs support comparing two stocks in a dual-row layout:
- **Input**: `finCompare` / `bsCompare` — placeholder "对比代码或名称", supports names via `resolveStockCode()`
- **Trigger**: `onchange` + `onkeypress="if(event.key==='Enter')..."` + "查询" button

**Dual-Row Table Layout**: When `cmpCode` is set, each indicator occupies TWO rows:
- Row 1: indicator name (`rowspan="2"`) + main stock values
- Row 2: comparison stock values (`background:#fff7e6; color:#fa8c16`)

Column structure stays 2 per year (原值 + 同比%), no extra columns. Header colspan is always 2.

**Comparison YoY**: Separate `cmpYoyMap` computed independently using same-report-period cross-year comparison. Never hardcode `-`.

## Name-Based Stock Search

Endpoint: `GET /api/stock-search?keyword=xxx`
1. Search local `stocks` table by code or name (`LIKE %keyword%`)
2. **Fallback**: If no local results, query 东方财富 suggest API: `searchadapter.eastmoney.com/api/suggest/get?type=14&input=xxx`
3. Returns `[{code, name, market}]`

`resolveStockCode(input)`: if 6-digit code return as-is, else search via API, return first match's code.

Add-stock `lookupStock()`: tries local search first, then 东方财富 `api/stock-info/<code>` for code lookup.

## ECharts Modal Charts

Both `openIndicatorChart` (financials) and `openBSChart` (balance sheet) use ECharts with:
- **Bar chart** (blue `#4a6cf7`) for main stock metric on left Y-axis
- **Bar chart** (orange `#fa8c16`) for comparison stock on left Y-axis (when comparing)
- **Line chart** (green `#52c41a`, dashed) for YoY growth rate on right Y-axis (only when ≥2 data points with valid YoY)
- **CAGR** in chart title: `Math.pow(lastV / firstV, 1 / n) - 1` from first/last non-null values
- **Right Y-axis**: MUST have `splitLine: { show: false }` to avoid duplicate grid lines
- **Data order**: Sort ascending (oldest→newest) — `[...years].sort((a, b) => a - b)`. For quarterly charts, use composite keys from `renderFinancialsTable` directly.

## Common Pitfalls

1. **`write_file` DESTROYS index.html**: This tool overwrites the ENTIRE file, not a section. A single accidental `write_file` call destroyed all session changes, requiring `git checkout -- templates/index.html` to recover. ONLY use `patch()` for index.html edits. This is the single most dangerous mistake in this project.
2. **Template caching**: `debug=False` caches Jinja2. Use `debug=True` during development.
3. **Missing tables**: `balance_sheets` or `custom_financials` may not exist in fresh DB.
4. **MySQL password**: Local is empty, remote has password. Don't commit config.py changes.
5. **Cumulative vs single identical**: When `period != "all"` and `view=single`, must query all periods, compute single, then filter.
6. **Comparison YoY missing**: Must compute separate `cmpYoyMap` for comparison stock.
7. **Chart grid lines doubled**: Right Y-axis needs `splitLine: { show: false }`.
8. **Chart x-axis reversed**: Always `.reverse()` values/labels/yoyVals before ECharts.
9. **Name search empty**: Local DB may not have the stock — external 东方财富 API provides fallback.
10. **`html` variable ordering**: Render functions that conditionally `html += ...` before the main table (e.g. comparison title) MUST declare `let html = ''` BEFORE those blocks. Putting `let html = '<table>...'` after a `html +=` block causes `ReferenceError: Cannot access 'html' before initialization`.
11. **onchange does not fire on Enter**: Text input onchange only fires on blur. Always add `onkeypress="if(event.key==='Enter')..."` handler alongside onchange for Enter key support.
12. **YoY prevKey = sequential vs cross-year**: `makePrevKey` for YoY MUST use `(year-1)|period` (same period last year). The sequential-quarter pattern `Q1→lastFY, Q2→Q1` is WRONG for YoY — it's for single-quarter subtraction only. For YoY comparison, Q1 2025 should compare with Q1 2024, not FY 2024.
13. **Subagent restoration bugs**: When dispatching subagents to restore/re-write code, they frequently introduce subtle bugs. ALWAYS verify with a full grep sweep after subagent completion. Common subagent mistakes:
    - Wrong API parameter names (e.g. `?q=` instead of `?keyword=`)
    - Parsing report_period as a date string instead of using the ENUM value directly (`d.report_period || 'FY'`)
    - Missing rowspan on indicator cells in comparison layout
    - Chart data not sorted ASC for x-axis
    - CAGR using buggy reduceRight instead of simple filter + first/last
    - Using composite keys directly as column labels instead of friendly `keyLabels`
    - Deleting the `periods` Set variable needed by `isQuarterly` and `keyLabels`
    - `isQuarterly` checking `.endsWith('-12-31')` when `report_period` is 'FY'/'Q1' etc (always true despite check)
    - `makeKey` not using `d.report_period` directly — must be `d.report_period || 'FY'`, return composite only when quarterly
    - Simplifying BS table to remove YoY columns — BS needs same colspan="2" + 同比% headers as financials
14. **Backend debug=True auto-reloads**: Server detects file changes and restarts, no manual restart needed after patching.
15. **MySQL COLLATE 字符集冲突（含 ENUM 列）**: 不仅是 `stock_code`，`report_period` ENUM 列也可能跨表不一致（`custom_financials` 为 utf8mb4_unicode_ci，`balance_sheets` 为 utf8mb4_0900_ai_ci），导致 JOIN 报错 `Illegal mix of collations`。**根治方案**：所有表的 `stock_code`、`report_period`、`audit_opinion` 等字符串列统一为 `utf8mb4_0900_ai_ci`（匹配 `stocks.code` 原生 COLLATE）。有 FK 约束的表需先 `DROP FOREIGN KEY` → `MODIFY` → `ADD CONSTRAINT` 回加。
16. **跨表数据源不一致**: `custom_financials`（东方财富）和 `balance_sheets`（新浪财经）的数据来源不同，约 14% 的行存在 `total_assets`/`total_equity` 偏差（大到几十亿）。这不是 bug，是数据源口径差异。**原则**：资产负债表数据以 `balance_sheets` 为准，`custom_financials` 中的 `total_assets`/`total_equity` 仅作冗余参考。前端应优先从 `balance_sheets` 取资产负债表数据。
17. **`git reset --hard origin/main` 会删除 `.hermes/skills/`**: 远程仓库没有 `.hermes/` 目录，reset 后项目 Skill 被清空。每次 `reset --hard` 后必须重新复制：`cp -R ~/AppData/Local/hermes/skills/software-development/stock-analysis-system/* /e/stock-analysis-system/.hermes/skills/stock-analysis-system/`。建议考虑将 `.hermes/` push 到远程。
18. **LLM 编造财务数据**: DeepSeek 会凭训练数据虚构 PE、估值等数字。**所有估值数据必须从 DB 显式传入 User Prompt**，并标注"来自数据库实时数据"。茅台的教训：DB 中 PE=18.05，AI 却反复说"30倍PE"，直接扭曲了评分（65→85）和 YES/NO 筐判定。不要信任 AI 自己"算"出来的任何财务数字。
19. **芒格分析 `temperature` 必须 0.3**: 0.7 会导致同股同数据两次分析天差地别。0.3 确保输出基本稳定，配合缓存实现一致性回放。代码升级后记得递增 `CACHE_VERSION` 防旧缓存污染。
20. **DuckDuckGo Lite HTML 改版导致搜索全部空**: 2026-07 发现 `class="result-link"` / `class="result-snippet"` 已从 DuckDuckGo Lite 页面消失。所有搜索返回空结果，芒格分析退化到仅凭训练数据编造。修复：改为匹配所有 `<a href="...">title</a>` 标签，过滤内部链接。如果将来搜索又全空，先 curl 看下实际 HTML 结构是否再次变化。
21. **深度抓取是分析质量的唯一出路**: 仅用搜索标题（~200字/维度）喂给 LLM，分析质量泛泛而谈（~800字）。改为抓取 Top 2 搜索结果页面全文（各1500字）后，分析质变——出现具体数据（12.54亿减值、和成煤矿停产、4500万吨天花板）且字数跃升至 2600+。代价：每次分析额外 12 次页面抓取，耗时从 20s → 65s。原则：分析质量 = 输入数据深度。搜索标题 < 页面摘要 < 页面全文。
22. **对话芒格 max_tokens 过低导致截断**: max_tokens=600 不够芒格风格（他的回复每句都有数据支撑），实际只输出 ~165 字就被截断，后半段分析丢失。改为 1000 后正常（~500 字完整回复）。芒格分析 max_tokens 保持 4000。
23. **JS模板字符串内嵌 `onerror` 四层引号转义 → 整页 JS 崩溃**: （已记录）
24. **Sticky notes 粘贴图片的 `onerror` 回退规则**: `<img>` 的 onerror 只能用 `this.style.display='none'` 潜默失败，严禁用 `this.outerHTML='...'` 动态替换 DOM。原因同 #23：在便利贴的 map() 回调中（非 template literal），`outerHTML` 替换包含 `<span>` 等 HTML 标签，导致正则匹配异常。
25. **`git reset --hard` 后新增表缺失**: `income_statements` / `cash_flows` 等表由远程代码引用但 GitHub 仓库无 DDL，`git reset --hard` 不会建表。同步代码后需检查 `app.py` 中引用的表是否全部存在于本地 MySQL，缺失的需从 `app.py` 的 COLUMNS 常量自动生成 CREATE TABLE。
26. **估值 PE 页面上方和图表不一致**: `api_stock_valuation()` 曾用 `realtime_pe`（腾讯实时行情）覆盖 `current_pe`，导致页面上方/侧边栏显示 stocks.pe_ttm（8.96），图表 tooltip 却是 valuation_history 的实际值（12.81）。修复：移除实时覆盖，`current_pe` 统一取 valuation_history 最新值。如果日后再出现图表和摘要数字不一致，先检查是否有多数据源覆盖。
27. **`sys.path.insert` 路径硬编码**: `app.py` 第 8 行有 `sys.path.insert(0, r"E:\stock-analysis-system")`。项目迁移（如 D→E 盘）或 git reset 后需检查此路径是否匹配当前项目根目录。路径错误表现为 `ModuleNotFoundError: No module named 'config'`。
28. **`models.py` SELECT 列遗漏**: 之前将 `get_all()` 的 `SELECT *` 优化为指定列，但漏加 `pe_ttm` 和 `dividend_yield`，导致首页 PE 和股息率全部显示 `-`。`stocks` 表新增字段后必须同步更新 models.py 的 SELECT 列清单。
29. **估值 PE 数据源不一致（年报 EPS vs TTM EPS）**: 图表曾用 `股价 / 最新年报 EPS` 计算 PE，导致当前值 12.81（用 2024 年报 EPS）vs 实时 PE=8.96（腾讯 TTM EPS）。**修复**：改用四季度滚动 TTM EPS = `股价 / TTM_EPS`，其中 `TTM_EPS = 最新年报EPS - 去年同期累计EPS + 今年最新累计EPS`。需拉取全部四种报告类型（年报/一季报/半年报/三季报），而非仅年报。修复后图表 PE≈8.94，与实时 8.96 仅差 0.02。
30. **估值页 `current_pe` 被实时行情覆盖导致图表与侧边栏不一致**: `api_stock_valuation()` 曾用腾讯实时 `realtime_pe` 覆盖计算出的 `current_pe`，导致侧边栏显示 8.96 而图表 tooltip 显示 12.81。修复后 `current_pe` 统一为 TTM 计算值，同时传 `realtime_pe` 给前端供参考。前端侧边栏优先使用 `realtime_pe`（`const currentPE = data.realtime_pe || data.current_pe`）。
31. **`cash_flows` 表列名必须以 `CASHFLOW_ROW_MAP` 为准**: 建表时若手写列名易与代码定义不符（如代码用 `cf_other_invest_in` 而非 `cf_invest_other_in`）。**正确做法**：从 `app.py` 提取 `CASHFLOW_ROW_MAP` 的动态列名生成 CREATE TABLE，不要凭记忆手写。同样规则适用于 `income_statements`。
32. **便利贴粘贴图片 `onerror` 回退规则**: `<img>` 的 onerror 只能用 `this.style.display='none'` 静默失败，严禁用 `this.outerHTML='...'` 动态替换 DOM。`outerHTML` 包含 `<span>` 等 HTML 标签时，在 `notes.map()` 回调的字符串拼接中四层转义引发整页 JS 崩溃（`missing ) after argument list`），导致首页 `loadStats` 未定义、表格无数据。便利贴和对话芒格聊天气泡的图片渲染均适用此规则。
33. **便利贴切换股票不刷新**: 切换股票后若便利贴标签页处于激活状态，不会自动加载新股票的笔记。修复：在 `loadDetail()` 末尾检测 `panel-sticky.style.display === 'block'` 时调用 `loadStickyNotes()`。
34. **估值 PE 优先用归母净利润/总股本而非 EPSJB**: `EPSJB`（基本每股收益）是公司自行披露的加权平均每股收益，可能与 `PARENTNETPROFIT / TOTAL_SHARE` 存在差额（股本变动、四舍五入等）。改用 `PARENTNETPROFIT / TOTAL_SHARE` 作为每股收益后，最新 PE 从 8.94 → 8.96 **与腾讯实时 PE-TTM 完全一致**。公式等价于 `市值 / TTM归母净利润`，即 `市值 / (期末归母 + 期初全年归母 - 期初归母)`。`TOTAL_SHARE` 每个报告期都从 API 独立获取，确保各期股本准确。
35. **估值图表 Y 轴留白过大**: ECharts 配置 `min: Math.floor(fmin*0.9), max: Math.ceil(fmax*1.1)` 留了 10% 上下空白，且股价右轴无 min/max 导致两条曲线各走各的不对齐。**修复**：PE 轴 padding 缩到 `fmin*0.99 ~ fmax*1.01`，股价轴同样设 `pMin*0.99 ~ pMax*1.01`，两侧均 `splitNumber:5`。`pMin/pMax` 从 `priceValues` 数组计算（`Math.min/Math.max`），写在 yAxis 配置之前。

## Color Convention

Consistent colors across tables AND charts:
- **Main stock**: blue `#4a6cf7` (text, bars, table values)
- **Comparison stock**: orange `#fa8c16` (text, bars, table comparison row, comparison series in charts)
- **YoY growth line**: green `#52c41a` (line + labels in charts)
- **Comparison row background**: `#fff7e6` (light orange tint)
- **YoY coloring in table**: `.fin-yoy-up` (red positive), `.fin-yoy-down` (green negative), `.fin-yoy-neutral` (gray for 0/null)

## Default Year Range

Initialized in `loadDetail()`: last 10 years (`curYear-9` through `curYear`), or from `list_date` if listed <10 years ago. Applies to `finFromYear/finToYear` and `bsFromYear/bsToYear`.

## Verification

Run `scripts/verify-functions.sh` to confirm all key JS functions exist with correct signatures and braces/parens are balanced.

## 📌 便利贴 (Sticky Notes)

股票详情页标签「📌 便利贴」，每只股票独立笔记。

**UX**: 两个输入框——标题 + 内容。内容支持混排：文字、链接（`https://...`）和图片 URL（`.png/.jpg`），自动识别渲染。无类型选择器。关联股票用**下拉选择**（从 `/api/stocks` 加载列表），非文本框。

**Ctrl+V 粘贴图片**: 监听 content textarea 的 paste 事件，自动将剪贴板图片转为 base64 data URI 插入文本区。渲染时 `data:image/...` 自动转为 `<img>` 标签，`cursor:pointer` + `onclick="viewImage(this.src)"` 点击全屏查看原图（深色浮层 `background:rgba(0,0,0,.85)`）。

**切换股票自动刷新**: 如果便利贴标签页已激活，切换股票后自动调用 `loadStickyNotes()`。

**DB**: `sticky_notes` (id, title VARCHAR(200), note_type ENUM('text','image','link'), content LONGTEXT, stock_code, created_at, updated_at)

**API**: `GET /api/sticky-notes?stock_code=X` | `POST /api/sticky-notes` | `PUT/DELETE /api/sticky-notes/<id>`
- GET 支持 `stock_code` 查询参数过滤当前股票笔记
- POST/PUT 自动关联当前 `detailCode`

**前端**: 黄底卡片 `#fffbe6`，hover 显示 ✎✕ 按钮，新建/编辑弹窗。新建时自动填入当前股票代码。内容中链接自动转为可点击外链，图片 URL 和 base64 data:image 自动渲染为 `<img>`（支持 `cursor:pointer` + `onclick="viewImage(this.src)"` 点击全屏查看原图）。

## Web 抓取三层回退策略

`munger.py::_fetch_url_content()` 实现三层回退：

1. **Jina Reader** (`https://r.jina.ai/{url}`) → 纯净 Markdown，公开页面效果最好，免费无 Key
2. **Google Cache** (`https://webcache.googleusercontent.com/search?q=cache:{url}`) → 雪球等 JS 动态渲染页面的救星（这些页面的 HTML 全文是 JS 框架代码，无实际内容）
3. **直接 HTTP 请求 + 正则剥 HTML** → 最终兜底，去 script/style 标签后取纯文本

> 为什么雪球需要 Google Cache：雪球是 JS SPA，直接 HTTP 请求返回 85KB 框架 HTML 但 `content=False`。Google Cache 存储了渲染后的快照，能拿到实际文章内容（如"多方博弈结果"原文）。

## Related References

- `references/jina-reader.md` — Jina Reader 集成详解
- `references/munger-integration.md` — 芒格分析完整模式
- `references/munger-chat.md` — 对话芒格系统
- `references/ai-input-depth-pattern.md` — AI 分析数据输入深度三阶段演进
- `references/agency-agents-setup.md` — Agency Agents 插件配置
- `references/db-optimization.md` — COLLATE 统一、索引优化
- `references/pe-ttm-calculation.md` — PE-TTM 估值四轮迭代：年报→TTM→披露延迟→归母净利润
