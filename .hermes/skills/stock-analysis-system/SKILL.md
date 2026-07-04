---
name: stock-analysis-system
description: Stock analysis system — Flask + MySQL + vanilla JS frontend. Agency Agents 驱动（UI Designer / Frontend Developer / Code Reviewer / Git Workflow Master / API Tester）。Covers project structure, quarterly reports, comparison stocks, chart patterns, and pitfalls.
---

# Stock Analysis System

Project: `E:\stock-analysis-system` | Flask 3.x + MySQL 8.4 | Port 5002

## Startup

```bash
cd /d/stock-analysis-system && python app.py
# Runs at http://127.0.0.1:5002
```

## Environment

- **Python**: `python` (3.11, via Hermes venv). Use `uv pip install` for packages.
- **MySQL**: Running on `E:\MySQL\bin\mysqld.exe`, root with NO password (empty string).
- **Shell**: git-bash/MSYS2 — POSIX syntax, MSYS paths like `/d/...` work.
- `config.py` password may differ between local (empty) and remote — never commit the local empty-password change.
- Flask `debug=True` is recommended to avoid Jinja2 template caching (otherwise every HTML edit requires a restart). Auto-reloads on any source change.

## Project Structure

| File | Role |
|---|---|
| `app.py` | Flask routes (all API + page serving) |
| `models.py` | Stock CRUD (raw SQL, no ORM) |
| `db.py` | MySQL connection pool (pool_size=5) |
| `config.py` | DB connection params |
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
# 加载单个专家到当前会话
agency_agents_load agent=ui-designer task="设计股票详情页"

# 委派任务给专家（后台执行）
agency_agents_delegate agent=api-tester task="测试新增的财务数据接口"

# 搜索匹配的专家
agency_agents_search query="需要设计数据表格的UI"
```

多专家协作顺序：设计 → 前端 → 测试 → 审查 → 分支管理。

## Database Tables

- **stocks**: core stock info (code UNIQUE)
- **dividends**: yearly dividend data (UNIQUE: stock_code, fiscal_year)
- **custom_financials**: custom financial indicators from eastmoney (UNIQUE: stock_code, fiscal_year, report_period)
- **balance_sheets**: 49-column balance sheet from Sina Finance (UNIQUE: stock_code, fiscal_year, report_period)

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
