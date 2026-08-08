# stock - 架构与业务说明

> 当前版本：v3.4
> 更新日期：2026-08-08
> 技术栈：Python Flask + MySQL + 原生 HTML/CSS/JavaScript  
> 默认访问地址：`http://127.0.0.1:5002`

---

## 1. 项目定位

本项目是一个本地运行的股票分析与投资记录系统。核心目标不是做公开网站，而是服务个人在多台电脑之间长期维护股票池、财务数据、估值参数、持仓数据、便利贴和芒格对话记录。

当前系统已经覆盖：

- 股票池管理：新增、修改、删除、搜索、分页、筛选、拖拽排序；新增股票后自动补全股票详情页数据。
- 财务数据分析：自定义财报、分红、融资、资产负债表、利润表、现金流量表、营收构成、股东、估值、走势、互动易。
- 估值分析：PE/PB、股息率、格雷厄姆估值参数、合理估值、合理价格、PB 扣商誉。
- 持仓管理：买入/卖出、手续费配置、印花税、现金入金/出金、公司行为、持仓成本重算、预计分红、净值快照、净值明细、收益日历和调仓模拟器。
- 净值自动化：A 股交易日收盘后自动记录一次净值，行情不可用时按配置重试，并在成功后触发云备份。
- 辅助分析：基本面驾驶舱、对比页、资本配置、对话芒格、便利贴、图片附件、K 线图。
- 跨电脑使用：本机配置文件 `local_settings.json` + Dropbox/OneDrive 等同步盘云备份。
- 数据安全：手动云备份、延迟自动云备份、恢复前备份、历史版本恢复。

---

## 2. 运行架构

```text
浏览器
  |
  | HTTP / JSON
  v
Flask Web 服务 app.py
  |
  | 创建应用、读取配置、注入 deps、注册 routes
  v
routes/
  |-- pages.py                 页面入口
  |-- stocks.py                首页列表、行情、估值参数
  |-- stock_basic.py           股票基础 CRUD、搜索、删除清理
  |-- custom_financials.py     自定义财报/财务摘要
  |-- balance_sheet.py         资产负债表
  |-- statements.py            利润表、现金流量表
  |-- segments.py              营收构成
  |-- corporate_actions.py     分红、融资
  |-- shareholders.py          股东缓存与查询
  |-- irm.py                   互动易/上证 e 互动
  |-- portfolio.py             我的持仓、交易、现金、净值
  |-- jobs.py                  后台任务
  |-- system.py                配置、云备份、数据库状态
  |
  | 调用业务服务
  v
services/
  |-- database.py              统一数据库访问实现
  |-- background_jobs.py       长耗时任务与日志
  |-- portfolio_auto_snapshot.py 收盘后自动记录持仓净值
  |-- financial_periods.py     财报期间选择
  |-- financial_metrics.py     财务公式
  |-- stock_identity.py        股票代码/市场/行业识别
  |-- market_data.py           行情数据
  |-- portfolio_*.py           持仓、交易、现金、净值、费用
  |-- cloud_backup_*.py        云备份存储与策略
  |-- providers/               东方财富、新浪、腾讯等数据源适配
  |
  | db.py 门面 -> mysql-connector-python
  v
MySQL stock_analysis

前端静态资源
  |-- static/js/core/           API 和通用格式化
  |-- static/js/detail/         股票详情页各 Tab
  |-- static/js/financial/      财务表格/公式/偏好
  |-- static/js/portfolio/      我的持仓页面模块
  |-- static/js/background_jobs.js

本地文件
  |-- local_settings.json        本机私有配置，不提交 Git
  |-- data/sticky_notes.json     便利贴 JSON
  |-- data/images/               便利贴图片
  |-- data/cloud_sync_state.json 本机云同步状态
  |-- auto_cloud_backup.log      自动云备份日志
  |-- portfolio_auto_snapshot.log 收盘自动净值日志

同步盘目录
  |-- stock_analysis_latest.sql
  |-- stock_analysis_YYYYMMDD_HHMMSS.sql
  |-- pre_restore_YYYYMMDD_HHMMSS.sql
  |-- sync_state.json
```

---

## 3. 主要文件

| 文件 | 职责 |
|---|---|
| `app.py` | Flask 入口、全局配置、服务注册、云备份/恢复调度、少量兼容 helper。业务路由已拆分到 `routes/`，通用逻辑逐步下沉到 `services/` |
| `routes/pages.py` | 页面入口路由：`/`、`/stock/<code>` |
| `routes/stocks.py` | 首页股票列表、实时行情列表、年初至今涨跌幅、首页排序、Graham 估值参数接口 |
| `routes/stock_basic.py` | 股票详情、搜索、添加、修改、删除、统计等股票基础接口 |
| `routes/fundamental_dashboard.py` | 基本面驾驶舱接口 |
| `routes/compare_dashboard.py` | 多股票指标对比接口 |
| `routes/capital_allocation.py` | 资本配置分析接口 |
| `routes/custom_financials.py` | 自定义财报/财务摘要查询与更新 |
| `routes/balance_sheet.py` | 资产负债表查询与更新 |
| `routes/statements.py` | 利润表、现金流量表查询与更新 |
| `routes/segments.py` | 营收构成查询与更新 |
| `routes/market_charts.py` | 估值、走势/K 线接口 |
| `routes/corporate_actions.py` | 分红、融资接口 |
| `routes/dividend_update.py` | 分红数据更新接口 |
| `routes/shareholders.py` | 股东数据查询、抓取、缓存 |
| `routes/irm.py` | 互动易/上证 e 互动查询与增量抓取 |
| `routes/jobs.py` | 后台任务列表、详情、最近任务状态接口 |
| `routes/portfolio.py` | 我的持仓、交易、资金流水、净值、快照、手续费配置 |
| `routes/system.py` | 配置、云备份、云恢复、迁移状态、本机设置 |
| `routes/notes_chat.py` | 便利贴、图片附件、对话芒格 |
| `migrations.py` | 轻量数据库迁移执行器，按顺序执行 `migrations/*.sql` 并写入 `schema_migrations` |
| `migrations/001_current_schema.sql` | 当前数据库结构基线迁移，覆盖股票、财务、持仓、芒格、配置等核心表 |
| `migrations/009_add_munger_chat_metadata.sql` | 对话芒格回答上下文元数据字段 |
| `services/app_settings.py` | 应用设置读取与本机配置 helper |
| `services/cloud_backup_service.py` | 云备份保留策略、自动备份延迟策略、SQL 备份文件校验 |
| `services/cloud_backup_storage.py` | 云备份文件、状态文件、备份目录等存储层操作 |
| `services/database.py` | 数据库连接池、统一查询门面、事务、慢 SQL 统计 |
| `services/exchange_rates.py` | 港币等汇率获取与缓存 |
| `services/financial_periods.py` | 财务报告期 helper：可用期间过滤、最新期间、去年同期、年报序列、CAGR 起点 |
| `services/financial_metrics.py` | 财务指标 helper：数字转换、同比、CAGR、核心利润口径、财务摘要派生指标 |
| `services/munger_context.py` | 对话芒格专用财务上下文：期间筛选、核心利润、行情、估值和数据质量提示 |
| `services/http_client.py` | 外部 HTTP 请求统一封装 |
| `services/mysql_tools.py` | MySQL dump/import、可执行文件探测等工具 |
| `services/stock_identity.py` | 股票代码规范化、市场识别、腾讯行情 symbol、东方财富编码、港股识别、行业获取 |
| `services/market_data.py` | 腾讯实时行情、实时价格、年初至今涨跌幅 |
| `services/stock_metrics_service.py` | 首页股票指标增强、Graham 合理估值、合理股价、PB 扣商誉、实时列表指标 |
| `services/portfolio_*.py` | 我的持仓服务族：交易、现金、净值、费用、公司行为、持仓重算、审计 |
| `services/providers/*.py` | 东方财富、新浪、腾讯等数据源适配 |
| `services/sticky_notes_service.py` | 便利贴 JSON 存储、base64 图片落盘、关联图片清理 |
| `services/shareholder_schema.py` | 股东缓存表结构确保 |
| `services/background_jobs.py` | 后台任务表结构、任务创建、进度更新、完成/失败状态落库 |
| `services/portfolio_auto_snapshot.py` | A 股交易日收盘后净值快照调度、工作日判断、重试和运行状态 |
| `services/stock_delete_service.py` | 删除自选股时清理股票详情页相关本地数据，保留持仓数据 |
| `services/ui_preferences.py` | 前端偏好与自定义财报指标配置存储 |
| `templates/index.html` | 股票列表和股票详情 SPA 页面，含图表、估值、便利贴、备份管理弹窗 |
| `templates/portfolio.html` | 我的持仓页面，含持仓、现金、资金流水、净值曲线 |
| `static/css/index.css` | 首页和股票详情页样式 |
| `static/css/portfolio.css` | 我的持仓页样式 |
| `static/css/cloud_backup.css` | 云备份、云恢复、备份管理公共样式 |
| `static/css/background_jobs.css` | 后台任务全局浮窗样式 |
| `static/js/theme.js` | 深色模式和 ECharts 主题适配 |
| `static/js/ui_utils.js` | Toast、HTML 转义、图片查看器等公共 UI 工具 |
| `static/js/core/api.js` | 通用 fetch 封装和 `StockApi` 请求方法 |
| `static/js/core/formatters.js` | 金额、百分比、日期、空值等通用格式化 |
| `static/js/stock_list.js` | 股票列表、搜索、排序、添加编辑删除、默认顺序、格雷厄姆参数 |
| `static/js/stock_detail.js` | 股票详情页主入口、Tab 切换、详情页持仓卡片 |
| `static/js/detail/*.js` | 股票详情页各 Tab：驾驶舱、分红、融资、股东、估值、走势、互动易、对比、资本配置 |
| `static/js/financial/*.js` | 财务模块：自定义财报、三张表、营收构成、指标偏好、前端展示公式 |
| `static/js/financial_tables.js` | 财务模块兼容入口，逐步保留为桥接层 |
| `static/js/notes_chat.js` | 便利贴、图片粘贴、对话芒格 |
| `static/js/cloud_backup.js` | 云备份、云恢复、备份管理、历史版本恢复 |
| `static/js/background_jobs.js` | 后台任务浮窗、轮询、日志、取消、重试 |
| `static/js/local_settings.js` | 本机环境配置读取、测试、保存 |
| `static/js/portfolio/*.js` | 我的持仓页模块：API、状态、布局、持仓、交易、资金流水、净值、收益日历和调仓模拟器 |
| `static/js/portfolio/rebalance_simulator.js` | 调仓模拟器：目标比例滑块、现金平衡、交易股数/费用/现金变化即时估算 |
| `models.py` | `Stock` 模型，封装股票基础 CRUD |
| `db.py` | MySQL 连接池和统一查询入口 |
| `config.py` | 默认数据库连接参数 |
| `config_manager.py` | 系统配置读写，主要用于 API Key 等 |
| `munger.py` | 对话芒格逻辑，包含联网搜索、网页抓取、LLM 调用 |
| `stock_list.py` | 命令行股票导入和维护工具 |
| `main.py` | 命令行菜单入口，已改为相对项目目录运行 |
| `start_stock_system.ps1` | Windows 启动脚本，读取本机配置，自动找 Python/MySQL 并启动服务 |
| `stock.bat` | 快捷启动入口 |
| `setup_local_settings.ps1` | 自动生成/更新 `local_settings.json` |
| `setup_local_settings.bat` | 双击执行本机配置脚本 |
| `local_settings.example.json` | 本机配置模板，提交 Git |
| `.gitignore` | 忽略本机配置、同步状态、临时文件 |

---

## 4. 本机配置机制

项目已经去掉关键路径硬编码，使用“默认配置 + 本机配置 + 环境变量”的方式适配不同电脑。

读取优先级：

```text
环境变量 > local_settings.json > 代码默认值
```

常用配置项：

| 配置项 | 环境变量 | 说明 |
|---|---|---|
| `app_port` | `STOCK_APP_PORT` | Flask 端口，默认 `5002` |
| `app_url` | `STOCK_APP_URL` | 启动后打开的地址 |
| `cloud_sync_dir` | `STOCK_CLOUD_SYNC_DIR` | 云同步备份目录，例如 `D:\Dropbox\stock-cloud-sync` |
| `auto_cloud_backup_delay_seconds` | `STOCK_AUTO_CLOUD_BACKUP_DELAY_SECONDS` | 自动云备份延迟，默认 `180` 秒 |
| `auto_portfolio_snapshot_enabled` | `STOCK_AUTO_PORTFOLIO_SNAPSHOT_ENABLED` | 是否开启收盘自动记录净值，默认开启 |
| `auto_portfolio_snapshot_hour` | `STOCK_AUTO_PORTFOLIO_SNAPSHOT_HOUR` | 自动记录时间的小时，默认 `15` |
| `auto_portfolio_snapshot_minute` | `STOCK_AUTO_PORTFOLIO_SNAPSHOT_MINUTE` | 自动记录时间的分钟，默认 `5` |
| `auto_portfolio_snapshot_retry_count` | `STOCK_AUTO_PORTFOLIO_SNAPSHOT_RETRY_COUNT` | 收盘行情不可用时的最大尝试次数，默认 `3` |
| `auto_portfolio_snapshot_retry_seconds` | `STOCK_AUTO_PORTFOLIO_SNAPSHOT_RETRY_SECONDS` | 自动记录重试间隔，默认 `60` 秒 |
| `mysql_service_name` | `MYSQL_SERVICE_NAME` | MySQL Windows 服务名 |
| `mysql_home` | `MYSQL_HOME` | MySQL 安装根目录 |
| `mysql_bin_dir` | `MYSQL_BIN_DIR` | MySQL bin 目录 |
| `python_exe` | `STOCK_PYTHON` | Python 解释器路径 |
| `db_host` | `STOCK_DB_HOST` | 数据库地址 |
| `db_port` | `STOCK_DB_PORT` | 数据库端口 |
| `db_user` | `STOCK_DB_USER` | 数据库用户名 |
| `db_password` | `STOCK_DB_PASSWORD` | 数据库密码 |
| `db_name` | `STOCK_DB_NAME` | 数据库名 |

`local_settings.json` 是本机私有文件，已被 Git 忽略。公司电脑和家里电脑只需要各自维护自己的 `local_settings.json`，同一套代码即可运行在不同路径和不同环境中。

`setup_local_settings.ps1` 会自动探测：

- Dropbox：优先 `用户目录\Dropbox`、`D:\Dropbox`、`E:\Dropbox`、`F:\Dropbox`
- OneDrive：`OneDrive`、`OneDriveConsumer`、`OneDriveCommercial`
- MySQL 服务、`mysql.exe`、`mysqld.exe`
- 项目虚拟环境 Python、系统 Python、Hermes Python

---

## 5. 云备份与恢复

### 5.1 文件类型

云同步目录由 `cloud_sync_dir` 指定，当前推荐为：

```text
D:\Dropbox\stock-cloud-sync
```

目录中主要文件：

| 文件 | 说明 |
|---|---|
| `stock_analysis_latest.sql` | 最新备份，`云恢复` 默认恢复这个文件 |
| `stock_analysis_YYYYMMDD_HHMMSS.sql` | 普通历史备份 |
| `pre_restore_YYYYMMDD_HHMMSS.sql` | 恢复前自动保护备份 |
| `sync_state.json` | 云端备份状态 |

### 5.2 手动云备份

点击页面 `云备份` 会立即执行数据库导出：

- 生成一份 `stock_analysis_YYYYMMDD_HHMMSS.sql`
- 同步更新 `stock_analysis_latest.sql`
- 写入 `sync_state.json`
- 更新本机 `data/cloud_sync_state.json`
- 清理旧备份

后端接口：

```text
POST /api/cloud-backup/backup
```

### 5.3 自动云备份

系统已经加入延迟合并自动备份机制。会修改核心数据的接口成功返回后，会安排一次自动云备份。

默认规则：

```text
数据变化后等待 180 秒再备份。
180 秒内继续修改数据，则取消旧计时并重新开始计时。
连续多次修改最终合并成一次云备份。
```

自动备份仍然生成：

```text
stock_analysis_YYYYMMDD_HHMMSS.sql
stock_analysis_latest.sql
```

自动备份日志：

```text
auto_cloud_backup.log
```

首页和持仓页顶部会显示自动备份状态，包括空闲、等待中、正在备份、上次成功、上次失败和可能冲突。首页的 `备份管理` 会集中展示 latest 状态、自动备份状态、历史备份列表，并提供立即云备份、恢复 latest、恢复选中版本等操作。

当前会触发自动云备份的操作：

| 操作 | 后端 endpoint |
|---|---|
| 添加股票 | `api_add_stock` |
| 修改股票 | `api_update_stock` |
| 删除股票 | `api_delete_stock` |
| 保存首页默认顺序 | `api_stocks_reorder` |
| 修改格雷厄姆估值参数 | `api_graham_valuation_put` |
| 更新分红数据 | `api_update_dividends` |
| 更新财务摘要 | `api_update_financials` |
| 更新资产负债表 | `api_update_balance_sheet` |
| 更新营收构成 | `api_update_segments` |
| 更新利润表 | `api_update_income` |
| 更新现金流量表 | `api_update_cashflow` |
| 修改系统配置 | `api_config_put` |
| 新增/修改持仓 | `api_portfolio_save_position` |
| 删除持仓 | `api_portfolio_delete_position` |
| 修改持仓每股分红 | `api_portfolio_update_dividend` |
| 重置持仓每股分红 | `api_portfolio_reset_dividend` |
| 修改现金 | `api_portfolio_update_cash` |
| 新增资金流水 | `api_portfolio_add_flow` |
| 删除资金流水 | `api_portfolio_delete_flow` |
| 记录持仓快照 | `api_portfolio_snapshot` |

### 5.3.1 收盘自动记录持仓净值

持仓净值自动记录由 `services/portfolio_auto_snapshot.py` 在后端独立调度，不依赖浏览器页面是否打开：

- A 股工作日默认在 `15:05` 执行一次；周末跳过。
- 通过腾讯行情返回的 `quote_date` 校验是否拿到当天行情，避免节假日把上一交易日的价格误当成当天快照。
- 行情短暂不可用时按 `auto_portfolio_snapshot_retry_count` 和 `auto_portfolio_snapshot_retry_seconds` 重试。
- 同一天通过 `portfolio_nav_snapshots.snapshot_date` 唯一键幂等更新，只保留一条快照。
- 应用在当天收盘时间后启动时，会执行一次当天补记；如果当天没有有效行情则不保存。
- 自动保存成功后调用现有延迟云备份机制。
- 手动“记录今日净值”仍然保留，页面进入时的实时净值刷新也不等于写入快照。

状态接口：

```text
GET /api/portfolio/auto-snapshot/status
```

### 5.4 云恢复

点击 `云恢复` 会恢复：

```text
stock_analysis_latest.sql
```

恢复前系统会先生成：

```text
pre_restore_YYYYMMDD_HHMMSS.sql
```

这样即使恢复错了，也可以从 `备份管理` 中选择恢复前版本回滚。

后端接口：

```text
POST /api/cloud-backup/restore
```

### 5.5 备份管理与历史版本恢复

首页不再保留单独的 `历史恢复` 按钮。历史版本恢复统一进入 `备份管理`，在项目内弹窗表格中查看 ordinary 备份、latest 备份和 `pre_restore` 备份。用户可以直接选中某个版本，然后点击 `恢复选中版本`。

备份列表接口：

```text
GET /api/cloud-backup/files
```

恢复指定文件接口：

```text
POST /api/cloud-backup/restore-file
```

请求体：

```json
{
  "filename": "stock_analysis_20260726_003236.sql"
}
```

### 5.6 保留策略

为了避免 Dropbox 中备份无限增长：

- `stock_analysis_YYYYMMDD_HHMMSS.sql` 只保留最新 5 份
- `pre_restore_YYYYMMDD_HHMMSS.sql` 只保留最新 5 份
- `stock_analysis_latest.sql` 永远保留，不计入 5 份

清理时机：

- 新建普通云备份后
- 新建恢复前备份后
- 打开备份管理列表时

### 5.7 恢复兼容处理

MySQL 恢复时可能因为不同机器的字符集/排序规则造成外键字段不兼容。当前 `_restore_database()` 会在导入前临时生成预处理 SQL，移除 dump 中的外键约束片段，避免 `ERROR 3780` 一类恢复失败。

---

## 6. 页面结构

### 6.1 首页与详情页

文件：

```text
templates/index.html
```

功能：

- 股票列表、搜索、分页、市场/状态筛选
- 指标排序和拖拽保存默认顺序
- 股票新增、编辑、删除
- 股票详情页 Tab，当前顺序为：自定义财报、分红、营收构成、资产负债表、利润表、现金流量表、融资、股东、估值、走势、互动易、便利贴、对话芒格
- 基本面驾驶舱、对比页、资本配置等详情页分析模块
- 分红图表，柱状图展示金额、折线节点展示分红比例
- 自定义财报表格，支持指标选择和顺序保存，并参与云同步恢复
- 营收构成
- 资产负债表
- 利润表，含核心利润、核心利润率、毛利率和桑基图
- 现金流量表
- 融资分析，含历年累计融资与累计分红对比
- 股东页面，默认最近 3 年并横向滚动到最新数据
- 估值分析，默认最近 3 年
- 走势/K 线图
- 互动易/上证 e 互动问答，只抓有答复内容并按天增量更新
- 对话芒格
- 便利贴
- 云备份、云恢复、备份管理、历史版本恢复
- 深色模式
- 移动端适配

### 6.2 我的持仓

文件：

```text
templates/portfolio.html
```

功能：

- 持仓列表展示代码、名称、股数、成本价、最新价、今日变化、市值、持仓盈亏、占比、每股分红和预期分红，并提供行内买入、卖出、分红操作
- 买入、卖出、交易作废、公司行为记录和持仓重算
- 券商手续费配置，买卖时考虑国内印花税等税费
- 现金通过入金、出金、买入、卖出等流水变化，不再直接修改现金金额
- 净值模块展示净值、总资产、持仓市值、现金、仓位、当日收益、累计收益、累计入金、累计出金
- 净值明细按日期倒序展示净值、涨跌幅、总市值、仓位百分比，支持日期筛选、分页和 Excel 导出
- 持仓明细右上角提供“调仓模拟器”：弹窗展示各股票和现金的当前金额、股数、当前比例；拖动或输入目标比例后，按当前最新股价估算目标金额、建议买入/卖出股数、交易费用和现金变化
- 调仓模拟器的现金比例是平衡项，股票目标比例合计不足 100% 的部分自动分配给现金；股数按 1 股取整，仅模拟，不写入交易记录或持仓
- 调仓模拟器复用 `GET /api/portfolio` 返回的实时行情和手续费配置，不新增持久化数据
- 预计分红和股息率，其中股息率按预期分红除以总市值
- 港股持仓按自动获取的 `HKD -> CNY` 汇率折算进人民币总资产
- 自定义每股分红，输入保留 2 位小数，历史最新分红展示到 3 位小数
- 启动时检测云端更新

---

## 7. 数据库设计

数据库：

```text
stock_analysis
```

连接方式：

- `db.py` 使用 `mysql.connector.pooling.MySQLConnectionPool`
- 默认连接池大小：`5`
- 默认字符集：`utf8mb4`

### 7.1 stocks

股票基础表。

关键字段：

| 字段 | 说明 |
|---|---|
| `id` | 自增主键 |
| `code` | 股票代码，唯一 |
| `name` | 股票名称 |
| `market` | `SH` / `SZ` / `BJ` |
| `industry` | 行业 |
| `list_date` | 上市日期 |
| `status` | 状态 |
| `pe_ttm` | 动态市盈率 |
| `dividend_yield` | 股息率 |
| `display_order` | 首页默认顺序 |
| `created_at` / `updated_at` | 时间戳 |

### 7.2 dividends

分红数据表。

关键字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码 |
| `fiscal_year` | 财年 |
| `net_profit` | 净利润，亿元 |
| `dividend_amount` | 分红总额，亿元 |
| `dividend_per_share` | 每股分红，元 |
| `ex_date` | 除权除息日 |

唯一约束：

```text
stock_code + fiscal_year
```

### 7.3 custom_financials

财务摘要表，数据主要来自东方财富。

核心字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码 |
| `fiscal_year` | 财年 |
| `report_period` | `FY` / `Q1` / `Q2` / `Q3` |
| `total_revenue` | 营业收入，亿元 |
| `operate_profit` | 营业利润，亿元 |
| `parent_profit` | 归母净利润，亿元 |
| `deducted_profit` | 扣非净利润，亿元 |
| `operate_cashflow` | 经营现金流，亿元 |
| `roe` | ROE |
| `deducted_roe` | 扣非 ROE |
| `roic` | ROIC |
| `total_assets` | 总资产，亿元 |
| `total_equity` | 股东权益，亿元 |
| `total_shares` | 总股本，亿股 |
| `basic_eps` | 每股收益 |
| `debt_ratio` | 资产负债率 |
| `short_borrow` / `long_borrow` / `bonds_payable` | 有息负债相关字段 |

前端会动态计算：

- 核心利润率
- 净利润率
- 经营现金流/净利润
- 同比数据
- 单季度视图

### 7.4 balance_sheets

资产负债表，数据主要来自新浪财经 HTML。

特点：

- 支持 `FY` / `Q1` / `Q2` / `Q3`
- 原始单位万元，入库前转换为亿元
- 覆盖货币资金、应收、存货、固定资产、商誉、负债、股东权益等科目
- 前端支持累计/单季度、同比、同行对比、趋势图

### 7.5 income_statements

利润表，数据来自新浪财经 HTML。

特点：

- 后端通用 `_upsert_finance()` 写入
- 支持年报和季报
- 前端与现金流量表共用通用表格渲染逻辑

### 7.6 cash_flows

现金流量表，数据来自新浪财经 HTML。

特点：

- 支持年报和季报
- 支持累计/单季度视图
- 与利润表共用采集和渲染框架

### 7.7 business_segments

主营构成表，数据来自东方财富 F10 主营构成接口。

关键字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码 |
| `fiscal_year` | 财年 |
| `report_period` | 报告期，当前主要使用 `FY` |
| `dimension_type` | `business` / `product` / `region` |
| `segment_name` | 业务、产品或地区名称 |
| `revenue` | 收入，亿元 |
| `cost` | 成本，亿元 |
| `gross_profit` | 毛利，亿元 |
| `gross_margin` | 毛利率 |
| `revenue_ratio` | 收入占比 |
| `profit_ratio` | 毛利占比 |
| `source` | 来源 |

唯一约束：

```text
stock_code + fiscal_year + report_period + dimension_type + segment_name
```

### 7.8 graham_valuations

格雷厄姆估值参数表。

字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码，唯一 |
| `growth_rate` | 增长率 |
| `payout_ratio` | 分红比例 |
| `risk_free_rate` | 无风险利率 |
| `expected_profit` | 当年预期利润 |
| `updated_at` | 更新时间 |

首页列表会基于这些参数计算合理估值、合理价格和高估/低估比例。

### 7.9 portfolio_positions

我的持仓明细表。

字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码，唯一 |
| `shares` | 当前持股数量，由交易和公司行为重算 |
| `cost_price` | 当前成本价，由系统按买卖记录重算，不在持仓明细直接编辑 |
| `custom_dividend_per_share` | 自定义每股分红 |
| `created_at` / `updated_at` | 时间戳 |

### 7.10 portfolio_cash

持仓现金表。

字段：

| 字段 | 说明 |
|---|---|
| `id` | 固定为 `1` |
| `amount` | 当前现金金额，由入金/出金/买入/卖出等流水更新，不再直接手工修改 |
| `updated_at` | 更新时间 |

### 7.11 portfolio_cash_flows

资金流水表。

字段：

| 字段 | 说明 |
|---|---|
| `flow_date` | 流水日期 |
| `flow_source` | `external` / `trade` / `corporate_action` 等流水来源 |
| `source_type` / `source_id` | 关联来源类型和来源记录 ID |
| `amount` | 金额，流入为正、流出为负 |
| `note` | 备注 |
| `created_at` | 创建时间 |

### 7.12 portfolio_nav_snapshots

持仓净值快照表。

字段：

| 字段 | 说明 |
|---|---|
| `snapshot_date` | 快照日期，唯一 |
| `total_market_value` | 股票市值 |
| `expected_dividend` | 预计分红 |
| `cash_amount` | 现金 |
| `total_asset_value` | 总资产 |
| `positions_json` | 当日持仓 JSON |
| `created_at` / `updated_at` | 时间戳 |

`nav_index`、`nav_change_pct`、仓位、当日收益、累计收益、累计入金和累计出金由 `services/portfolio_nav.py` 查询快照和资金流水后动态计算返回。

### 7.13 munger_chats

对话芒格历史记录表，由 `munger.py` 读写。

用途：

- 保存用户提问
- 保存芒格回复
- 支持单条删除和清空

`meta_json` 保存回答生成时的上下文快照元数据，不保存 API Key 或网页正文：

| 元数据 | 说明 |
|---|---|
| `stock_code` / `stock_name` / `industry` | 本次回答对应的股票身份 |
| `latest_period` | 最新有效报告期，例如 `2026 一季报` |
| `latest_annual` | 最新完整年报，和最新季度数据分开 |
| `yoy_base` | 同周期同比基准报告期 |
| `search_used` / `source_count` | 是否联网搜索、引用来源数量 |
| `sources` | 来源编号、标题、URL、来源等级 |
| `warnings` | 财务数据质量提示 |
| `model` / `elapsed_ms` | 使用的模型和本次耗时 |

对应迁移：

```text
migrations/009_add_munger_chat_metadata.sql
```

读取历史时会先尝试读取 `meta_json`；旧数据库尚未执行迁移时自动回退到旧字段查询，不影响已有对话。

### 7.14 便利贴 JSON

便利贴不再使用 MySQL 表，而是文件存储：

```text
data/sticky_notes.json
data/images/
```

保存时会把 base64 图片提取为文件，正文中保留本地图片路径。

### 7.15 schema_migrations

数据库迁移记录表，由 `migrations.py` 自动创建和维护。

字段：

| 字段 | 说明 |
|---|---|
| `version` | 迁移版本，等于 SQL 文件名去掉 `.sql` |
| `name` | SQL 文件名 |
| `checksum` | 文件 SHA-256，用于防止已执行迁移被修改 |
| `applied_at` | 执行时间 |

迁移文件放在：

```text
migrations/*.sql
```

启动 `app.py` 时会先执行 `run_migrations()`，再执行旧的 `_ensure_xxx()` 幂等补齐逻辑。这样新电脑首次运行时能创建完整当前结构，老电脑升级时也能记录已应用版本。当前基线迁移为：

```text
migrations/001_current_schema.sql
```

当前增量迁移还包括：

```text
migrations/009_add_munger_chat_metadata.sql
```

查询迁移状态：

```text
GET /api/db/migrations
```

### 7.16 portfolio_trades

持仓交易记录表。买入、卖出都必须通过该表记录，系统据此重算剩余股数、成本价、现金和盈亏。

关键字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码 |
| `trade_type` | `buy` / `sell` |
| `trade_date` | 成交日期 |
| `shares` | 成交股数 |
| `price` | 成交价 |
| `amount` | 成交金额 |
| `commission` / `stamp_tax` / `transfer_fee` / `total_fee` | 佣金、印花税、过户费、总费用 |
| `cash_delta` | 对现金的影响，买入为负，卖出为正 |
| `shares_before` / `shares_after` | 交易前后股数 |
| `cost_price_before` / `cost_price_after` | 交易前后成本价 |
| `is_void` / `voided_at` / `void_note` | 作废状态和原因 |

### 7.17 portfolio_fee_config

持仓交易费用配置表，固定 `id=1`。

| 字段 | 说明 |
|---|---|
| `commission_rate` | 券商佣金率 |
| `min_commission` | 最低佣金 |
| `stamp_tax_rate` | 印花税率，当前卖出时计入 |
| `transfer_fee_rate` | 过户费率 |

### 7.18 portfolio_corporate_actions

持仓公司行为记录表，当前用于记录分红等会影响现金和成本的事件。分红按系统约定摊薄持仓成本，并计入现金。

关键字段：

| 字段 | 说明 |
|---|---|
| `stock_code` | 股票代码 |
| `action_type` | 公司行为类型，例如 `dividend` |
| `action_date` | 发生日期 |
| `shares` | 对应股数 |
| `cash_amount` | 现金影响金额 |
| `cost_price_before` / `cost_price_after` | 公司行为前后成本价 |
| `is_void` / `voided_at` / `void_note` | 作废状态和原因 |

### 7.19 background_jobs / background_job_logs

后台任务和任务日志表，由 `services/background_jobs.py` 确保结构。用于批量更新财报、分红、三张表、营收构成、股东和互动易等长耗时任务。

### 7.20 irm_interactions

互动易/上证 e 互动问答缓存表。只保存有答复的问答，按 `question_id` 去重，增量抓取时不会重复写入。

### 7.21 stock_shareholders

前十大股东缓存表。按 `stock_code + report_date + holder_rank` 唯一，股东页默认展示最近 3 年并使用本地缓存加速加载。

### 7.22 ui_preferences

用户界面偏好表。用于保存自定义财报指标选择、指标顺序等可跨电脑同步恢复的设置。

---

## 8. REST API 总览

### 8.1 页面

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/` | 首页 |
| `GET` | `/stock/<code>` | 详情页入口，前端按 code 自动打开详情 |
| `GET` | `/portfolio` | 我的持仓 |

### 8.2 股票与列表

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/stocks` | 股票列表，支持分页、筛选、关键字、指标排序 |
| `GET` | `/api/stocks/realtime` | 自选股实时行情列表 |
| `GET` | `/api/stocks/ytd` | 自选股年初至今涨跌幅 |
| `POST` | `/api/stocks/reorder` | 保存默认顺序 |
| `GET` | `/api/stock/<code>` | 股票详情 |
| `POST` | `/api/stock` | 添加股票，支持自动获取名称/市场 |
| `PUT` | `/api/stock/<code>` | 修改股票 |
| `DELETE` | `/api/stock/<code>` | 删除自选股，并清理详情页研究数据；如存在持仓/交易则保留持仓数据 |
| `GET` | `/api/stats` | 统计概览 |
| `GET` | `/api/stock-search` | 本地 + 东方财富搜索 |
| `GET` | `/api/stock-info/<code>` | 东方财富获取股票名称和市场 |

### 8.3 财务数据

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/stock/<code>/dividends` | 查询分红 |
| `POST` | `/api/update-dividends` | 更新分红和 PE |
| `GET` | `/api/stock/<code>/financials` | 查询财务摘要 |
| `POST` | `/api/update-financials` | 更新财务摘要 |
| `GET` | `/api/stock/<code>/balance-sheet` | 查询资产负债表 |
| `POST` | `/api/update-balance-sheet` | 更新资产负债表 |
| `GET` | `/api/stock/<code>/income` | 查询利润表 |
| `POST` | `/api/update-income` | 更新利润表 |
| `GET` | `/api/stock/<code>/cashflow` | 查询现金流量表 |
| `POST` | `/api/update-cashflow` | 更新现金流量表 |
| `GET` | `/api/stock/<code>/segments` | 查询营收构成 |
| `POST` | `/api/update-segments` | 更新营收构成 |
| `POST` | `/api/update-shareholders` | 批量刷新股东缓存 |
| `GET` | `/api/stock/<code>/shareholders` | 查询前十大股东缓存 |
| `GET` | `/api/stock/<code>/financing` | 查询融资数据 |
| `GET` | `/api/stock/<code>/irm` | 查询互动易/上证 e 互动问答 |
| `POST` | `/api/stock/<code>/irm/sync` | 单只股票增量同步互动问答 |
| `GET` | `/api/irm/status` | 查询互动问答同步状态 |
| `POST` | `/api/irm/sync` | 全部股票互动问答增量同步，后台任务执行 |
| `GET` | `/api/stock/<code>/fundamental-dashboard` | 基本面驾驶舱 |
| `GET` | `/api/stock/<code>/compare-dashboard` | 对比页指标数据 |
| `GET` | `/api/stock/<code>/capital-allocation` | 资本配置分析 |
| `GET` | `/api/stock/<code>/valuation` | 查询估值数据 |
| `GET` | `/api/stock/<code>/kline` | 查询 K 线 |
| `GET` | `/api/stock/<code>/graham-valuation` | 查询格雷厄姆估值参数 |
| `PUT` | `/api/stock/<code>/graham-valuation` | 保存格雷厄姆估值参数 |

### 8.4 我的持仓

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/portfolio` | 当前持仓汇总 |
| `GET` | `/api/portfolio/fee-config` | 查询券商手续费、印花税、过户费配置 |
| `PUT` | `/api/portfolio/fee-config` | 保存交易费用配置 |
| `POST` | `/api/portfolio/positions` | 历史兼容接口，当前返回错误：持仓只能通过买入/卖出变动 |
| `POST` | `/api/portfolio/trades` | 新增买入/卖出交易并自动更新持仓和现金 |
| `GET` | `/api/portfolio/trades` | 查询交易记录 |
| `POST` | `/api/portfolio/trades/<id>/void` | 作废交易并重算持仓 |
| `POST` | `/api/portfolio/actions` | 新增公司行为，例如分红 |
| `GET` | `/api/portfolio/actions` | 查询公司行为记录 |
| `POST` | `/api/portfolio/actions/<id>/void` | 作废公司行为并重算持仓 |
| `GET` | `/api/portfolio/positions/<code>` | 查询单只持仓详情 |
| `DELETE` | `/api/portfolio/positions/<code>` | 历史兼容接口，当前返回错误：不能直接删除持仓 |
| `GET` | `/api/portfolio/audit` | 持仓/现金审计 |
| `POST` | `/api/portfolio/rebuild` | 根据交易和公司行为重算持仓 |
| `PUT` | `/api/portfolio/positions/<code>/dividend` | 保存自定义每股分红 |
| `POST` | `/api/portfolio/positions/<code>/dividend/reset` | 重置每股分红 |
| `PUT` | `/api/portfolio/cash` | 历史兼容接口，不建议直接修改现金 |
| `GET` | `/api/portfolio/flows` | 资金流水 |
| `POST` | `/api/portfolio/flows` | 新增资金流水 |
| `DELETE` | `/api/portfolio/flows/<id>` | 删除资金流水 |
| `POST` | `/api/portfolio/snapshot` | 记录今日快照 |
| `GET` | `/api/portfolio/nav` | 净值曲线和净值明细，支持 `live=1` 进入页面时刷新一次 |
| `GET` | `/api/portfolio/auto-snapshot/status` | 收盘自动记录净值调度器状态 |

### 8.5 云同步

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/cloud-backup/status` | 查询云端 latest 状态 |
| `GET` | `/api/cloud-backup/auto-status` | 查询自动云备份调度状态 |
| `GET` | `/api/cloud-backup/files` | 查询历史备份列表 |
| `POST` | `/api/cloud-backup/backup` | 手动云备份 |
| `POST` | `/api/cloud-backup/restore` | 恢复 latest |
| `POST` | `/api/cloud-backup/restore-file` | 恢复指定历史版本 |

### 8.6 后台任务

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/jobs` | 查询后台任务列表，支持 `job_type`、`status`、`limit` |
| `GET` | `/api/jobs/latest` | 查询最近一个后台任务，可按 `job_type` 过滤 |
| `GET` | `/api/jobs/<job_id>` | 查询单个后台任务详情 |
| `GET` | `/api/jobs/<job_id>/logs` | 查询任务执行日志 |
| `POST` | `/api/jobs/<job_id>/cancel` | 请求取消任务，当前股票处理完后停止 |
| `POST` | `/api/jobs/<job_id>/retry` | 重试部分完成、失败或已取消的任务 |

### 8.7 配置、芒格、便利贴

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/config` | 读取系统配置 |
| `PUT` | `/api/config` | 修改系统配置 |
| `GET` | `/api/db/migrations` | 查询数据库迁移状态 |
| `GET` | `/api/db/stats` | 查询数据库访问统计和慢 SQL |
| `POST` | `/api/db/stats/reset` | 重置数据库访问统计 |
| `GET` | `/api/preferences/financial-indicators` | 查询自定义财报指标偏好 |
| `PUT` | `/api/preferences/financial-indicators` | 保存自定义财报指标偏好 |
| `GET` | `/api/local-settings` | 查询本机设置 |
| `PUT` | `/api/local-settings` | 保存本机设置 |
| `POST` | `/api/local-settings/test` | 测试本机设置 |
| `GET` | `/api/stock/<code>/munger-chat` | 读取对话历史 |
| `POST` | `/api/stock/<code>/munger-chat` | 发送对话 |
| `DELETE` | `/api/stock/<code>/munger-chat` | 删除单条或清空对话 |
| `GET` | `/api/sticky-notes` | 查询便利贴 |
| `POST` | `/api/sticky-notes` | 新建便利贴 |
| `PUT` | `/api/sticky-notes/<id>` | 修改便利贴 |
| `DELETE` | `/api/sticky-notes/<id>` | 删除便利贴 |
| `GET` | `/data/images/<path>` | 便利贴图片服务 |

---

## 9. 数据来源

| 数据 | 来源 |
|---|---|
| 股票名称/市场 | 东方财富 quote/search 接口 |
| 股票搜索 | 本地数据库优先，未命中再查东方财富 suggest |
| 实时股价、PE、PB、市值 | 腾讯行情接口 |
| K 线 | 腾讯 K 线接口 |
| 港币人民币汇率 | Frankfurter API，缓存到 `data/exchange_rates.json` |
| 分红 | 东方财富 datacenter-web |
| 融资 | 东方财富/公开 F10 融资相关数据接口，落库后按年度累计展示 |
| 净利润辅助 | 东方财富 datacenter-web |
| 财务摘要 | 东方财富 datacenter-web |
| 资产负债表 | 新浪财经 HTML |
| 利润表 | 新浪财经 HTML |
| 现金流量表 | 新浪财经 HTML |
| 营收构成 | 东方财富 F10 主营构成接口 |
| 股东 | 东方财富股东研究/前十大股东数据，写入本地缓存 |
| 互动易 | 深交所互动易 `irm.cninfo.com.cn`，只抓有答复问答 |
| 上证 e 互动 | 上交所 e 互动公开问答，支持上证股票 |
| 后台任务 | 本地 MySQL `background_jobs` / `background_job_logs` |
| 用户偏好 | 本地 MySQL `ui_preferences`，随数据库云备份同步 |
| 对话芒格搜索 | 搜索引擎 + 网页抓取 + LLM |

---

## 10. 启动与部署

### 10.1 推荐启动方式

Windows 下推荐双击：

```text
stock.bat
```

或运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_stock_system.ps1
```

启动脚本会：

- 读取 `local_settings.json`
- 设置当前进程环境变量
- 自动查找可用 Python
- 自动尝试启动 MySQL 服务或 `mysqld.exe`
- 检测 Flask 端口
- 启动 `app.py`
- 打开浏览器访问系统

### 10.2 首次配置

首次拉取代码后执行：

```text
setup_local_settings.bat
```

它会生成：

```text
local_settings.json
```

需要人工确认或修改的通常只有：

- MySQL 路径或服务名
- MySQL 密码
- 云同步目录
- Python 路径

### 10.3 Git 注意事项

已忽略：

```text
local_settings.json
data/cloud_sync_state.json
data/images/
temp/
```

不应提交：

- 本机数据库密码
- 本机绝对路径配置
- 临时日志
- 云端 SQL 备份文件

---

## 11. 开发约定

- 后端修改数据库的接口，应接入 `AUTO_CLOUD_BACKUP_ENDPOINTS`，除非该操作不应影响云端 latest。
- 恢复类接口不接入自动云备份，恢复前使用 `pre_restore` 保护备份。
- 新增本机路径配置时，优先放入 `local_settings.example.json`，并通过 `_setting()` 支持环境变量覆盖。
- 新增数据库表或字段时，优先新增 `migrations/*.sql`，已执行迁移不要修改；必要时再保留 `_ensure_xxx_table()` 作为老库兼容兜底。
- 前端备份管理、历史版本恢复等关键操作使用项目内 modal，不使用浏览器原生 `prompt()` 做复杂交互。
- 跨电脑同步以数据库 SQL 备份为主，代码通过 Git 同步，本机配置各自维护。

### 11.1 前端拆分原则

后续新增前端功能时，默认遵守当前的模块拆分方式，不再把大段 JS/CSS 直接堆进 `templates/*.html`。

模板文件只负责页面结构：

| 文件 | 职责 |
|---|---|
| `templates/index.html` | 首页和股票详情页的 HTML 结构、弹窗结构、脚本/样式引用 |
| `templates/portfolio.html` | 我的持仓页 HTML 结构、弹窗结构、脚本/样式引用 |

样式文件按页面或公共能力拆分：

| 文件 | 职责 |
|---|---|
| `static/css/index.css` | 首页、股票详情页样式 |
| `static/css/portfolio.css` | 我的持仓页样式 |
| `static/css/cloud_backup.css` | 云备份、云恢复、备份管理等跨页面公共样式 |

JavaScript 按功能模块拆分：

| 文件 | 职责 |
|---|---|
| `static/js/core/api.js` | 通用 fetch、JSON 请求、错误处理和 `StockApi` |
| `static/js/core/formatters.js` | 金额、百分比、日期、空值等通用格式化 |
| `static/js/theme.js` | 深色模式、ECharts 主题适配 |
| `static/js/ui_utils.js` | Toast、HTML 转义、图片查看器等公共 UI 工具 |
| `static/js/stock_list.js` | 首页股票列表、搜索、排序、添加、编辑、删除、默认顺序、格雷厄姆参数 |
| `static/js/stock_detail.js` | 股票详情页主入口、Tab 路由、股票切换、详情页持仓卡片 |
| `static/js/detail/*.js` | 股票详情页业务 Tab：驾驶舱、分红、融资、股东、估值、走势、互动易、对比、资本配置 |
| `static/js/financial/*.js` | 自定义财报、三张表、营收构成、财务公式、指标偏好 |
| `static/js/financial_tables.js` | 财务旧入口兼容层，新增财务能力优先放到 `static/js/financial/` |
| `static/js/portfolio/*.js` | 我的持仓页面：API、状态、布局、持仓、交易、流水、净值、收益日历和调仓模拟器 |
| `static/js/background_jobs.js` | 后台任务浮窗、轮询、日志、取消、重试 |
| `static/js/notes_chat.js` | 便利贴、图片粘贴、对话芒格 |
| `static/js/cloud_backup.js` | 云备份、云恢复、备份管理、历史版本恢复、云端更新提示 |
| `static/js/local_settings.js` | 本机环境配置读取、测试、保存 |

新增功能放置规则：

- 新增接口请求优先挂到 `StockApi` 或页面自己的语义化 API 包装，不要在多个模块散写 `fetch`。
- 新增股票列表相关能力，优先放入 `stock_list.js`，样式放入 `index.css`。
- 新增股票详情页 Tab 能力，优先新增或维护 `static/js/detail/*.js`，不要继续扩大 `stock_detail.js`。
- 新增财务表格、指标、报表、营收构成能力，优先放入 `static/js/financial/`。
- 新增持仓能力，优先放入 `static/js/portfolio/` 对应模块。
- 新增长耗时更新的前端进度展示，优先复用 `background_jobs.js`，不要每个按钮单独写一套轮询。
- 新增便利贴或对话芒格能力，优先放入 `notes_chat.js`。
- 新增云备份/恢复/同步提示能力，优先放入 `cloud_backup.js`。
- 新增本机环境配置能力，优先放入 `local_settings.js`，后端配置项同步维护 `local_settings.example.json`。
- 多个页面都会用的工具函数放入 `ui_utils.js`、`theme.js`、`core/api.js` 或 `core/formatters.js`，不要在页面内重复定义。
- 页面专属样式放入对应页面 CSS；跨页面样式才抽到公共 CSS。

当前前端仍采用原生 HTML/CSS/JavaScript 和普通 `<script>` 引用方式，未引入打包器。短期内保持这种低门槛结构，但共享脚本要严格维护加载顺序；如果后续前端复杂度继续上升，再考虑升级为 ES Modules 或 Vite。

---

## 12. 当前重点能力总结

当前系统的核心工作流是：

```text
家里电脑改数据
  -> 系统延迟自动云备份到 Dropbox
  -> 公司电脑启动后发现云端更新
  -> 用户点击立即更新或手动云恢复
  -> 公司电脑恢复 latest
```

恢复前系统会自动生成 `pre_restore` 备份，因此误恢复后可以通过 `备份管理` 回到恢复前版本。

这套机制使同一份代码可以在家里和公司两台电脑上运行，各自使用不同的 MySQL、Python 和 Dropbox 路径，同时共享同一份业务数据备份。

---

## 13. 近期界面与数据能力变更

### 13.1 首页列表与顶部工具栏

首页顶部布局已经调整：

- 右上角集中放置 `云备份`、`云恢复`、`备份管理` 和 `云备份状态`。
- 股票数量统计从右上角移动到列表工具栏，紧跟 `更新数据` 后展示。
- 首页股票列表操作列去掉 `编辑` 按钮，只保留垃圾桶图标作为删除入口。
- 删除入口使用轻量图标按钮，默认灰色，悬停时红色提示危险操作，并适配暗色模式。

### 13.2 详情页 Tab 切换股票刷新机制

股票详情页上方切换股票时，当前所在 Tab 会自动重新加载对应股票的数据，避免出现标题已切换但表格或图表仍停留在上一只股票的问题。

当前已覆盖：走势、估值、分红、自定义财报、营收构成、资产负债表、利润表、现金流量表、对话芒格、便利贴。

异步加载函数会在返回后校验当前 `detailCode`，如果请求期间用户已经切换到其他股票，则丢弃旧请求结果，避免旧数据覆盖新页面。

### 13.3 利润表数据源补充

利润表更新不再只依赖新浪财报 HTML。当前 `api_update_income` 会在新浪数据基础上，再使用东方财富利润表接口补充更完整的字段。

重点补充字段包括：

- `parent_net_profit`：归属于母公司普通股股东的净利润
- `minority_profit`：少数股东损益
- `other_income`：其他收益
- `asset_disposal_income`：资产处置收益
- `interest_income`：利息收入
- `credit_impairment_loss`：信用减值损失
- `asset_impairment_loss`：资产减值损失
- `invest_income`：投资收益
- `fair_value_change`：公允价值变动收益

如果东方财富源数据中某个字段本身为 `null`，前端仍显示为空；这表示数据源未披露或该期无该项目。

### 13.4 利润表桑基图

利润表桑基图已经按利润流向重新整理：

- 左侧营收构成按产品流向营业收入。
- 营业收入拆分为毛利和营业成本。
- 毛利流向核心利润、期间费用和税金及附加。
- 投资收益、公允价值变动收益、其他收益等作为营业利润调整项流向营业利润。
- 自动计算 `其他营业利润调整项`，用于补齐 `营业利润 - 核心利润 - 已展示调整项` 的差额。
- 负向的 `其他营业利润调整项` 从核心利润流出，不再从营业利润向外流。
- 营业外收入、营业外支出都从左向右流向净利润，其中营业外支出用绿色表示扣减项。
- 所得税费用从营业利润向右流出，避免出现向下直流的视觉错位。
- 正数同比百分比单独显示为红色，负数同比百分比单独显示为绿色，科目名称和金额仍保持节点自身颜色。
- 少数股东损益为负数时也会显示，并向归母净利润方向流动；为正数时仍按净利润拆分为归母净利润和少数股东损益。
- 节点间距已适当放宽，改善细项较多时的拥挤问题。

### 13.5 资产负债表结构弹窗

资产负债表在年报和季报横轴时间后提供结构图入口。点击后会打开项目内弹窗，展示：

- 总资产结构：权益和负债比例，权益为蓝色、负债为红色。
- 资产结构：流动资产与非流动资产，以及资产细项构成。
- 负债结构：流动负债与非流动负债，以及负债细项构成。

表格颜色与饼图颜色保持一致，鼠标悬停表格科目时会同步高亮饼图扇区，并降低其他扇区亮度。

### 13.6 利润表利息口径拆分

利润表已经拆分两类容易混淆的利息口径：

- 主表收入侧 `interest_income`：利润表主表中的利息收入，用于满足 `营业总收入 = 营业收入 + 利息收入`。
- 财务费用附注侧 `finance_interest_income`：财务费用附注中的利息收入，用于解释 `财务费用 = 利息费用 - 利息收入 + 其他财务收支`。

新增数据库字段：

- `finance_interest_expense`：财务费用附注中的 `(其中) 利息费用`
- `finance_interest_income`：财务费用附注中的 `(其中) 利息收入`
- `interest_expense`：利润表成本侧的利息支出
- `fee_commission_expense`：利润表成本侧的手续费及佣金支出

对应迁移：

```text
migrations/005_add_income_finance_interest_fields.sql
migrations/006_add_income_operating_cost_detail_fields.sql
```

利润表前端展示规则：

- `收入` 部分展示 `营业总收入`、`营业收入`、`利息收入`。
- `成本与费用` 部分在 `营业税金及附加` 上方展示 `利息支出`、`手续费及佣金支出`。
- `财务费用` 下方展示 `(其中) 利息费用`、`(其中) 利息收入`。

利润表桑基图展示规则：

- 第一列加入主表 `利息收入`，与产品收入共同流向 `营业总收入`。
- `营业总收入` 向右流出到 `毛利`、`营业成本`、`利息支出`、`手续费及佣金支出`。
- 第 4 列上方的 `（财务费用）利息收入` 使用 `finance_interest_income`，不是主表收入侧的 `interest_income`。
- 当桑基图单独展示 `finance_interest_income` 时，期间费用中的财务费用按“扣除利息收入前”的费用端口径计算，即 `finance_expense + finance_interest_income`，避免利息收入被重复计算。

以贵州茅台 2025 年为例：

```text
营业收入 1688.3810 亿 + 主表利息收入 32.1607 亿 = 营业总收入 1720.5417 亿
财务费用 -8.1524 亿 ≈ 财务费用利息费用 0.2873 亿 - 财务费用利息收入 8.4299 亿
```

---

## 14. 2026-08-01 架构拆分与对比页修正

### 14.1 后端模块化拆分

`app.py` 已完成第一阶段瘦身：业务路由不再直接堆在入口文件中，而是按业务域注册到 `routes/` 模块。当前 `app.py` 主要保留：

- Flask 应用创建、全局配置读取、本机配置覆盖
- 数据库、模型、服务和路由模块的依赖注入注册
- 云备份/恢复调度相关胶水逻辑
- 少量仍待继续下沉的兼容 helper

已拆分出的路由模块包括：

- `routes/pages.py`：页面入口
- `routes/stocks.py`、`routes/stock_basic.py`：股票列表与股票基础 CRUD
- `routes/fundamental_dashboard.py`：基本面驾驶舱
- `routes/compare_dashboard.py`：对比页
- `routes/capital_allocation.py`：资本配置
- `routes/custom_financials.py`、`routes/balance_sheet.py`、`routes/statements.py`：财报摘要、资产负债表、利润表、现金流量表
- `routes/segments.py`：营收构成
- `routes/market_charts.py`：估值、走势/K 线
- `routes/corporate_actions.py`、`routes/dividend_update.py`：分红、融资、分红更新
- `routes/shareholders.py`：股东
- `routes/irm.py`：互动易/上证 e 互动
- `routes/portfolio.py`：我的持仓
- `routes/system.py`：配置、云备份、本机设置、迁移状态
- `routes/notes_chat.py`：便利贴、图片、对话芒格

### 14.2 服务层抽取

已抽取的服务模块包括：

- `services/financial_periods.py`：财务报告期选择逻辑，避免把当前年只有 Q1 的数据误当作 FY 年报使用。
- `services/financial_metrics.py`：通用财务指标计算，包含同比、CAGR、核心利润口径等。
- `services/stock_identity.py`：股票代码、市场、腾讯 symbol、东方财富编码、港股识别、行业获取。
- `services/market_data.py`：腾讯实时行情、实时价格、年初至今涨跌幅。
- `services/stock_metrics_service.py`：首页股票列表指标增强、Graham 合理估值、合理股价、PB 扣商誉等。
- `services/sticky_notes_service.py`：便利贴 JSON 存储和图片附件处理。
- `services/shareholder_schema.py`：股东缓存表结构确保。
- `services/background_jobs.py`：后台任务表、任务创建、状态/进度更新、批量股票后台执行器。

### 14.3 后台任务系统

长耗时的批量更新接口已开始迁入统一后台任务系统。批量请求会立即返回 `job_id`，任务状态可通过 `/api/jobs/<job_id>` 查询。

后台任务行为：

- 同一种批量任务在 `queued` / `running` 状态时会复用已有任务，避免重复启动多个全量抓取线程。
- 传入 `force: true` 可绕过防重复保护，用于确实需要强制再开一次任务的维护场景。
- 批量任务创建成功时不会立刻触发自动云备份；任务真正写入数据并完成后，才按对应业务原因安排延迟备份。
- 单只股票更新仍保持同步返回，并继续沿用原来的请求成功后自动云备份机制。
- 任务支持取消请求；后台循环会在每只股票处理前检查取消标记，并保留真实进度。
- 任务日志记录到 `background_job_logs`，用于前端展示每只股票的开始、完成、失败和取消原因。
- 任务支持重试；默认从错误日志中提取失败股票代码并只重试失败股票，提取不到失败股票时使用原请求参数重跑。
- 重试会创建新任务，不会复活或覆盖旧任务；旧任务日志会记录新任务编号。
- 前端通过 `static/js/background_jobs.js` 和 `static/css/background_jobs.css` 提供全局任务浮窗，可展示进度、日志，并支持取消/重试。

当前已接入的任务类型：

- `irm_sync_all`：互动易/上证 e 互动全量增量抓取。
- `update_financials`：自定义财报/财务摘要更新。
- `update_dividends`：分红数据更新。
- `update_balance_sheet`：资产负债表更新。
- `update_income`：利润表更新。
- `update_cashflow`：现金流量表更新。
- `update_segments`：营收构成更新。
- `update_shareholders`：股东数据缓存刷新。

后续如果继续拆分，优先方向是把 `app.py` 中剩余的持仓 helper、云备份 helper、表结构确保逻辑进一步迁入 `services/`。

### 14.4 对比页期间选择修正

对比页 `/api/stock/<code>/compare-dashboard` 已调整报告期选择逻辑：

- 如果没有显式选择年份，默认使用该股票最新已有财报期间，而不是简单取 `MAX(fiscal_year)` 后强制使用 `FY`。
- 如果用户选择了某年某期间，但该期间暂无数据，会自动回退到该年最新已有期间。
- 例如当前 `2026` 年只有 `Q1`，用户选 `2026 年报/FY` 时，接口会自动回退到 `2026 Q1`，并返回 `period_fallback_note`。
- 前端收到 `period_fallback_note` 后，会同步更新期间下拉框并提示用户，避免页面显示“年报”但财务指标为空。

这可以避免 PE、PB、股息率等行情指标有值，但 ROE、ROIC、毛利率、净利率、资产负债率等财报指标全部为空的误解。

### 14.5 删除股票数据清理

删除股票接口 `/api/stock/<code>` 会通过 `services/stock_delete_service.py` 清理该股票的详情页/研究数据，但保留我的持仓数据：

- 删除财报、分红、估值参数、股东、互动易、便利贴、芒格对话等详情页/研究数据。
- 不删除 `portfolio_positions`、`portfolio_trades`、`portfolio_corporate_actions`，也不删除或调整 `portfolio_cash_flows`。
- 如果该股票仍有持仓/交易/公司行为记录，`stocks` 主表不物理删除，只设置 `is_watchlist=0` 从自选股列表隐藏，避免数据库外键级联删除持仓。
- 如果该股票没有任何持仓相关记录，则物理删除 `stocks` 主表记录。
- 删除 `data/sticky_notes.json` 中绑定该股票的便利贴，并清理便利贴图片附件。
- 重新添加曾经隐藏的股票时，会把 `is_watchlist` 恢复为 `1`，重新显示在自选股列表。

---

## 15. 当前开发规范（2026-08-08）

本节记录系统当前已经形成的架构、前端和接口约定。后续迭代优先遵守这些约定，避免把已经拆开的职责重新堆回 `app.py`、模板内联脚本或重复公式里。

### 15.1 后端分层

- `app.py` 是应用装配入口，只负责 Flask 创建、全局配置、依赖注入、路由注册、云备份/恢复调度等根级编排；新增业务逻辑不要直接堆在 `app.py`。
- `routes/` 按业务域承载页面和 API 路由，例如股票、自定义财报、三张表、营收构成、分红/融资、股东、互动易、组合持仓、系统设置、后台任务等。
- `services/` 承载业务服务、领域 helper、外部接口封装和跨路由复用逻辑。路由层只做参数校验、调用服务、组织响应。
- `db.py` 是数据库访问门面，具体实现集中在 `services/database.py`。业务代码应通过门面函数访问数据库。
- `models.py`、`migrations.py`、`migrations/` 负责表结构、迁移和历史兼容，新增字段应同步补充迁移脚本或启动期 schema ensure 逻辑。

### 15.2 路由模块规范

- 每个 `routes/*.py` 只处理一个清晰业务域，避免跨域互相塞逻辑。
- 路由模块优先暴露 `register_*_routes(app, deps)` 风格的注册函数，由 `app.py` 统一注入依赖。
- 新接口需要复用既有 service，不要在路由里直接复制抓取、计算、格式化或 SQL 片段。
- 页面入口放在 `routes/pages.py`；业务数据接口放在对应业务路由模块。
- 长耗时批量接口不要同步阻塞请求，应迁入后台任务系统并返回 `job_id`。

### 15.3 服务层规范

- 财务期间选择统一放在 `services/financial_periods.py`，例如“当前年只有 Q1 时不能误当 FY 年报”这类逻辑不得散落在接口里。
- 财务指标和公式统一放在 `services/financial_metrics.py`，包括同比、CAGR、核心利润、核心利润率、毛利率等。
- 股票代码、市场、腾讯 symbol、东方财富编码、港股识别和行业信息优先使用 `services/stock_identity.py`。
- 行情、实时价格、年初至今涨跌幅等外部市场数据优先通过 `services/market_data.py`。
- 外部 HTTP 请求优先通过 `services/http_client.py`，统一超时、重试、headers 和异常处理口径。
- 云备份的存储和策略分开：本地/远端存储细节放在 `services/cloud_backup_storage.py`，业务编排放在 `services/cloud_backup_service.py` 或系统路由中。
- 股票删除清理逻辑放在 `services/stock_delete_service.py`，删除自选股详情数据时不能误删我的持仓交易、现金流水和公司行为数据。

### 15.4 数据库访问规范

- 业务代码使用 `execute_query`、`execute_update`、`execute_insert`、`execute_many`、`transaction` 等门面函数。
- 除 `services/database.py` 或底层基础设施外，不要直接写 `conn.cursor()`、`commit()`、`rollback()`。
- 多步写入必须使用 `transaction`，保证失败时整体回滚。
- 查询结果优先返回 dict/list 结构，避免路由层依赖裸 tuple 下标。
- 慢 SQL 和数据库统计已经接入观测接口：`GET /api/db/stats`、`POST /api/db/stats/reset`。
- 慢 SQL 阈值通过环境变量 `STOCK_SLOW_SQL_SECONDS` 控制。

### 15.5 后台任务规范

- 批量更新、全量抓取、股东刷新、互动易同步、财报/分红/三张表/营收构成等长耗时操作应接入 `services/background_jobs.py`。
- 后台任务接口返回结构应包含 `background: true`、`job_id`、`job_type`、`message`。
- 同类任务在 `queued` / `running` 时默认复用已有任务，确需重跑时再支持 `force: true`。
- 任务循环应在每只股票处理前检查取消标记，并把开始、完成、失败、取消原因写入 `background_job_logs`。
- 重试应创建新任务，不复活旧任务；优先只重试失败股票，无法提取失败股票时才使用原参数重跑。
- 任务真正完成并发生数据写入后，再按业务原因安排云备份；不要因为“任务已创建”就触发云备份。
- 前端统一通过 `static/js/background_jobs.js` 的任务浮窗展示进度、日志、取消和重试；没有任务执行时浮窗应自动隐藏。

### 15.6 API 响应规范

- 新读接口优先返回 `{"ok": true, ...}`；历史接口如果已经返回数组或对象，可保持兼容，不要为了形式统一破坏前端。
- 新写接口优先返回 `{"ok": true}` 或 `{"success": true}`，并附带 `created`、`updated`、`deleted`、`count`、`errors` 等可诊断字段。
- 错误响应统一包含 `{"error": "可读错误信息"}`，必要时补充 `details`，HTTP 状态码应与错误类型匹配。
- 股票详情类接口优先使用 `GET /api/stock/<code>/...`。
- 数据更新类接口优先使用 `POST /api/update-...` 或对应业务域下的 `POST`。
- 后台任务状态接口使用 `GET /api/jobs/<job_id>`，取消和重试使用任务域接口，不要为每种业务任务另起一套轮询协议。
- 接口字段名保持 snake_case，前端展示层再决定中文名称和格式。

### 15.7 前端模块规范

- `static/js/core/api.js` 是通用 fetch 封装，新增请求优先挂到 `StockApi.*`，不要在页面里散写 `fetch`。
- `static/js/core/formatters.js` 放通用格式化能力，例如金额、百分比、日期、数字空值展示。
- 股票详情页 tab 逻辑放在 `static/js/detail/*.js`，一个 tab 或一组强相关 tab 一个模块。
- 财务表格和财务图表相关逻辑放在 `static/js/financial/`；前端展示侧公式放在 `static/js/financial/metrics.js`。
- 我的持仓页面使用 `static/js/portfolio/` 下的模块，语义化接口封装放在 `static/js/portfolio/api.js`，状态集中在 `state.js`。
- 调仓模拟器等持仓页纯前端计算能力放入独立模块，复用 `/api/portfolio` 已返回的行情、汇率和费用配置；模拟功能不得直接写入交易记录。
- 模板中避免新增大段内联脚本；模板只负责 DOM 骨架和脚本加载顺序。
- 修改共享 JS 后要检查模板中的加载顺序。依赖关系通常是 `core/api.js`、`core/formatters.js`、财务公式/业务模块、页面入口脚本。
- 对已有页面兼容风险较高的共享脚本变更，可以同步更新查询串版本号，避免浏览器缓存导致旧脚本和新脚本混用。

### 15.8 财务公式规范

- 后端 `services/financial_metrics.py` 是业务/API 数据的公式事实来源。
- 前端 `static/js/financial/metrics.js` 只用于展示侧派生值、图表节点和无需落库的即时计算。
- 同一指标不能在多个路由或多个 JS 模块里各写一份公式；新增指标先补公式 helper，再由路由和前端调用。
- 核心利润、核心利润率、毛利率、同比和 CAGR 的口径要保持后端、表格、图表、自定义财报一致。
- 核心利润为负数时也要展示；桑基图中负核心利润按既有约定保留可见流向，不得被空值过滤。

### 15.9 云备份和同步规范

- 会改变本地数据的同步接口，应登记到自动云备份机制中，或在任务完成后显式安排备份。
- 后台任务只在实际完成写入后触发备份；创建任务、查询任务、取消任务不应触发备份。
- 用户偏好、财务自定义指标、排序和 UI 设置应通过可同步的存储服务保存，保证换电脑云恢复后仍能复原。
- 云恢复/覆盖本地属于高风险操作，保留现有确认和版本判断机制，避免静默覆盖用户本地新数据。

### 15.10 验证规范

后端改动至少运行 Python 编译检查：

```powershell
$files = @('app.py','db.py','models.py','migrations.py') + (Get-ChildItem routes,services -Filter *.py -Recurse | ForEach-Object { $_.FullName })
.\.venv\Scripts\python.exe -m py_compile @files
```

前端改动至少对改过的 JS 文件运行语法检查。当前本机可用的 Node 路径示例：

```powershell
& 'C:\Users\吴赛\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe' --check static\js\financial\metrics.js
```

提交前运行：

```powershell
git diff --check
```

涉及页面布局、图表、弹窗、表格对齐和深色模式时，应启动本地服务并用浏览器实际检查关键页面。

### 15.11 Git 工作流

- 后续每次代码或文档改动完成后自动 `commit`。
- 只在用户明确说 `push` 时推送到 GitHub。
- 提交前先看 `git status --short`，不要把无关的用户改动混入同一个提交。
- 不使用 `git reset --hard`、`git checkout --` 等会覆盖用户工作的命令，除非用户明确要求。

### 15.12 对话芒格上下文规范

- `services/munger_context.py` 是对话芒格的财务上下文入口，必须复用 `financial_periods.py` 和 `financial_metrics.py`，不能在提示词或路由里重新实现报告期和核心利润公式。
- 最新有效报告期和最新完整年报必须分开：当前年度只有 Q1/Q2/Q3 时，当前年度疑似误标的 FY 行会被忽略；同比基准使用去年同报告期。
- 对话上下文至少包含股票名称、代码、行业、最新有效报告期、最新完整年报、同比基准、近十年有效年报、核心利润/核心利润率、资产负债表、现金流、行情和用户估值配置；缺失项明确标为缺失。
- 纯框架问题（例如“什么是护城河”）不联网搜索；涉及当前股票的最新业绩、行业、公告、风险、估值或用户提供链接时，才按主题搜索有限数量来源。
- 外部网页正文必须放在 `<untrusted_source>` 标记中，仅作为未验证材料；提示词引用来源使用 `[S1]`、`[S2]` 编号，来源等级和链接写入 `munger_chats.meta_json`。
- DeepSeek 模型从 `system_config.deepseek_model` 读取，默认 `deepseek-v4-pro`；调用使用超时和有限重试，API Key 不写日志、不写聊天元数据。
- API 失败返回 400/500/502 等真实 HTTP 状态和可读错误，不得把异常文本伪装成助手回复，也不得在失败时写入一条假的 `munger` 消息。
- 前端 `static/js/notes_chat.js` 只渲染经过转义的 Markdown，来源链接只允许 `http://` 和 `https://`，来源和数据质量提示在回答下方折叠展示。
