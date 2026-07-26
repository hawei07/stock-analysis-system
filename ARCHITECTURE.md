# 股票分析系统 - 架构与业务说明

> 当前版本：v3.1  
> 更新日期：2026-07-26  
> 技术栈：Python Flask + MySQL + 原生 HTML/CSS/JavaScript  
> 默认访问地址：`http://127.0.0.1:5002`

---

## 1. 项目定位

本项目是一个本地运行的股票分析与投资记录系统。核心目标不是做公开网站，而是服务个人在多台电脑之间长期维护股票池、财务数据、估值参数、持仓数据、便利贴和芒格对话记录。

当前系统已经覆盖：

- 股票池管理：新增、修改、删除、搜索、分页、筛选、拖拽排序。
- 财务数据分析：分红、财报摘要、资产负债表、利润表、现金流量表、营收构成。
- 估值分析：PE/PB、格雷厄姆估值参数、合理估值和合理价格。
- 持仓管理：持仓数量、现金、资金流水、预计分红、净值快照。
- 辅助分析：对话芒格、便利贴、图片附件、K 线图。
- 跨电脑使用：本机配置文件 `local_settings.json` + Dropbox/OneDrive 等同步盘云备份。
- 数据安全：手动云备份、延迟自动云备份、恢复前备份、历史版本恢复。

---

## 2. 运行架构

```text
浏览器
  |
  | HTTP
  v
Flask Web 服务 app.py
  |
  | 调用业务函数、数据抓取、备份恢复
  v
Python 服务模块
  |-- models.py              股票基础模型
  |-- db.py                  MySQL 连接池
  |-- config_manager.py      系统配置
  |-- munger.py              对话芒格
  |-- stock_list.py          命令行导入/维护
  |
  | mysql-connector-python
  v
MySQL stock_analysis

本地文件
  |-- local_settings.json        本机私有配置，不提交 Git
  |-- data/sticky_notes.json     便利贴 JSON
  |-- data/images/               便利贴图片
  |-- data/cloud_sync_state.json 本机云同步状态
  |-- auto_cloud_backup.log      自动云备份日志

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
| `app.py` | Flask 入口、页面路由、REST API、数据抓取、云备份/恢复、自动备份调度 |
| `services/cloud_backup_service.py` | 云备份保留策略、自动备份延迟策略、SQL 备份文件校验 |
| `templates/index.html` | 股票列表和股票详情 SPA 页面，含图表、估值、便利贴、历史恢复弹窗 |
| `templates/portfolio.html` | 我的持仓页面，含持仓、现金、资金流水、净值曲线 |
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

### 5.4 云恢复

点击 `云恢复` 会恢复：

```text
stock_analysis_latest.sql
```

恢复前系统会先生成：

```text
pre_restore_YYYYMMDD_HHMMSS.sql
```

这样即使恢复错了，也可以从 `历史恢复` 中选择恢复前版本回滚。

后端接口：

```text
POST /api/cloud-backup/restore
```

### 5.5 历史恢复

点击 `历史恢复` 会打开项目内弹窗表格，不再使用浏览器原生 `prompt()`。用户可以直接选中某个版本，然后点击 `恢复选中版本`。

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
- 打开历史恢复列表时

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
- 股票详情页 Tab
- 分红图表
- 自定义财报表格
- 营收构成
- 资产负债表
- 利润表
- 现金流量表
- 估值分析
- K 线图
- 对话芒格
- 便利贴
- 云备份、云恢复、历史恢复
- 深色模式
- 移动端适配

### 6.2 我的持仓

文件：

```text
templates/portfolio.html
```

功能：

- 持仓列表
- 股票市值
- 现金
- 总资产
- 预计分红
- 股息率
- 自定义每股分红
- 资金流水
- 每日净值快照
- 净值曲线
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
| `shares` | 持股数量 |
| `custom_dividend_per_share` | 自定义每股分红 |
| `created_at` / `updated_at` | 时间戳 |

### 7.10 portfolio_cash

持仓现金表。

字段：

| 字段 | 说明 |
|---|---|
| `id` | 固定为 `1` |
| `amount` | 现金金额 |
| `updated_at` | 更新时间 |

### 7.11 portfolio_cash_flows

资金流水表。

字段：

| 字段 | 说明 |
|---|---|
| `flow_date` | 流水日期 |
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

### 7.13 munger_chats

对话芒格历史记录表，由 `munger.py` 读写。

用途：

- 保存用户提问
- 保存芒格回复
- 支持单条删除和清空

### 7.14 便利贴 JSON

便利贴不再使用 MySQL 表，而是文件存储：

```text
data/sticky_notes.json
data/images/
```

保存时会把 base64 图片提取为文件，正文中保留本地图片路径。

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
| `POST` | `/api/stocks/reorder` | 保存默认顺序 |
| `GET` | `/api/stock/<code>` | 股票详情 |
| `POST` | `/api/stock` | 添加股票，支持自动获取名称/市场 |
| `PUT` | `/api/stock/<code>` | 修改股票 |
| `DELETE` | `/api/stock/<code>` | 删除股票 |
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
| `GET` | `/api/stock/<code>/valuation` | 查询估值数据 |
| `GET` | `/api/stock/<code>/kline` | 查询 K 线 |
| `GET` | `/api/stock/<code>/graham-valuation` | 查询格雷厄姆估值参数 |
| `PUT` | `/api/stock/<code>/graham-valuation` | 保存格雷厄姆估值参数 |

### 8.4 我的持仓

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/portfolio` | 当前持仓汇总 |
| `POST` | `/api/portfolio/positions` | 新增/修改持仓 |
| `DELETE` | `/api/portfolio/positions/<code>` | 删除持仓 |
| `PUT` | `/api/portfolio/positions/<code>/dividend` | 保存自定义每股分红 |
| `POST` | `/api/portfolio/positions/<code>/dividend/reset` | 重置每股分红 |
| `PUT` | `/api/portfolio/cash` | 修改现金 |
| `GET` | `/api/portfolio/flows` | 资金流水 |
| `POST` | `/api/portfolio/flows` | 新增资金流水 |
| `DELETE` | `/api/portfolio/flows/<id>` | 删除资金流水 |
| `POST` | `/api/portfolio/snapshot` | 记录今日快照 |
| `GET` | `/api/portfolio/nav` | 净值曲线 |

### 8.5 云同步

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/cloud-backup/status` | 查询云端 latest 状态 |
| `GET` | `/api/cloud-backup/auto-status` | 查询自动云备份调度状态 |
| `GET` | `/api/cloud-backup/files` | 查询历史备份列表 |
| `POST` | `/api/cloud-backup/backup` | 手动云备份 |
| `POST` | `/api/cloud-backup/restore` | 恢复 latest |
| `POST` | `/api/cloud-backup/restore-file` | 恢复指定历史版本 |

### 8.6 配置、芒格、便利贴

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/config` | 读取系统配置 |
| `PUT` | `/api/config` | 修改系统配置 |
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
| 分红 | 东方财富 datacenter-web |
| 净利润辅助 | 东方财富 datacenter-web |
| 财务摘要 | 东方财富 datacenter-web |
| 资产负债表 | 新浪财经 HTML |
| 利润表 | 新浪财经 HTML |
| 现金流量表 | 新浪财经 HTML |
| 营收构成 | 东方财富 F10 主营构成接口 |
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
- 新增数据库表时，优先使用幂等 `_ensure_xxx_table()` 或迁移函数，保证老电脑启动时可自动补齐结构。
- 前端历史恢复等关键操作使用项目内 modal，不使用浏览器原生 `prompt()` 做复杂交互。
- 跨电脑同步以数据库 SQL 备份为主，代码通过 Git 同步，本机配置各自维护。

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

恢复前系统会自动生成 `pre_restore` 备份，因此误恢复后可以通过 `历史恢复` 回到恢复前版本。

这套机制使同一份代码可以在家里和公司两台电脑上运行，各自使用不同的 MySQL、Python 和 Dropbox 路径，同时共享同一份业务数据备份。
