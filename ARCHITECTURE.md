---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3f11eb7fa23d664c4b1c1527387f20fd_84d55351704511f1986d525400d9a7a1
    ReservedCode1: 24yu3eSrwjYxfL/ys2MQrX9sCwzJFdWqnrOQ0GSoA4PyzqyLkJ9pvQ7MlKN9lFSyhnpa5dAYp6SOixVQQUDMW+mHWzlvXJpaHWWx1/BQcMdS+1pgK1jwrz3q2sdzmx26gXQBBcQ1wELR592ImE7+zkdhS3eACkJX+IqbGMtKzUip0ZtUPa0eIa5e4V4=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3f11eb7fa23d664c4b1c1527387f20fd_84d55351704511f1986d525400d9a7a1
    ReservedCode2: 24yu3eSrwjYxfL/ys2MQrX9sCwzJFdWqnrOQ0GSoA4PyzqyLkJ9pvQ7MlKN9lFSyhnpa5dAYp6SOixVQQUDMW+mHWzlvXJpaHWWx1/BQcMdS+1pgK1jwrz3q2sdzmx26gXQBBcQ1wELR592ImE7+zkdhS3eACkJX+IqbGMtKzUip0ZtUPa0eIa5e4V4=
---

# 股票分析系统 — 业务逻辑与技术架构总结

> 版本 v2.8 | 2026-07-05 | Python Flask + MySQL 8.4 + DeepSeek V4 Pro

---

## 一、项目概述

股票分析系统是一个基于 B/S 架构的股票数据管理平台，当前阶段已实现股票基础信息的全生命周期管理，为后续行情接入、技术分析、策略回测等高级功能提供数据底座。

- **技术栈**：Python 3.11 + Flask + MySQL 8.4
- **访问地址**：`http://127.0.0.1:5002`
- **代码仓库**：`E:\stock-analysis-system`（Git 管理，分支策略 `feature/xxx → main`，修改后立即本地 commit，仅在明确指令时 push）

---

## 二、技术架构

```
┌──────────────────────────────────────────┐
│              浏览器 (SPA)                  │
│        Vanilla JS + CSS Variables         │
│         @media 640px 移动端适配            │
└──────────────────┬───────────────────────┘
                   │ HTTP RESTful API
┌──────────────────▼───────────────────────┐
│           Flask Web 服务 (app.py)          │
│  路由: / (页面)  /api/* (数据接口)         │
│  服务: munger.py (对话芒格)                │
└──────────────────┬───────────────────────┘
                   │ Python 调用
┌──────────────────▼───────────────────────┐
│         数据模型层 (models.py)              │
│        Stock 类 — 纯 SQL 封装              │
├──────────────────────────────────────────┤
│         data/sticky_notes.json             │
│         便利贴 JSON 文件存储               │
└──────────────────┬───────────────────────┘
                   │ mysql-connector-python
┌──────────────────▼───────────────────────┐
│            连接池 (db.py)                   │
│   MySQLConnectionPool (pool_size=5)       │
└──────────────────┬───────────────────────┘
                   │ TCP 3306
┌──────────────────▼───────────────────────┐
│          MySQL 8.4 (stock_analysis)       │
│             表: stocks                    │
└──────────────────────────────────────────┘
```

### 分层职责

| 层级 | 文件 | 职责 |
|------|------|------|
| 前端 | `templates/index.html` | 单页应用，表格渲染、表单交互、分页 |
| Web 层 | `app.py` | 路由分发、请求校验、JSON 序列化 |
| 模型层 | `models.py` | Stock CRUD + sticky_notes/munger_chats 查询 |
| 服务层 | `munger.py` | 芒格对话引擎 + Web搜索 + 三层抓取 + DeepSeek |
| 配置层 | `config_manager.py` | API Key 等系统配置读写 |
| 持久层 | `db.py` | 连接池管理、查询/更新统一入口 |
| 数据层 | `data/sticky_notes.json` | 便利贴 JSON 文件存储 |
| 配置 | `config.py` | 数据库连接参数集中管理 |

---

## 三、数据库设计

### 3.1 数据库信息

| 项目 | 值 |
|------|-----|
| 数据库名 | `stock_analysis` |
| 字符集 | `utf8mb4` |
| 排序规则 | `utf8mb4_unicode_ci` |
| 引擎 | InnoDB |
| 端口 | 3306 |

### 3.2 stocks 表结构

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO_INCREMENT | 主键 |
| `code` | VARCHAR(10) | UNIQUE, NOT NULL | 股票代码（如 600519） |
| `name` | VARCHAR(50) | NOT NULL | 股票名称 |
| `market` | ENUM('SH','SZ','BJ') | NOT NULL | 市场：上海/深圳/北京 |
| `industry` | VARCHAR(50) | NULL | 所属行业 |
| `pe_ttm` | DECIMAL(10,2) | NULL | 动态市盈率 |
| `dividend_yield` | DECIMAL(10,4) | NULL | 股息率（%） |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `updated_at` | DATETIME | ON UPDATE CURRENT_TIMESTAMP | 更新时间 |

> code 字段设计为自然键（UNIQUE），API 中通过 code 而非 id 进行资源定位。
> list_date、status 字段保留在数据库结构中，此处不再展开。

### 3.3 dividends 表结构

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO_INCREMENT | 主键 |
| `stock_code` | VARCHAR(10) | NOT NULL | 股票代码 |
| `fiscal_year` | INT | NOT NULL | 财年 |
| `net_profit` | DECIMAL(18,4) | NULL | 净利润（亿元） |
| `dividend_amount` | DECIMAL(18,4) | NULL | 分红总额（亿元） |
| `dividend_per_share` | DECIMAL(10,4) | NULL | 每股分红（元） |
| `ex_date` | DATE | NULL | 除权除息日 |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

> 唯一约束：UNIQUE(stock_code, fiscal_year)，每只股票每个财年仅一条记录。

### 3.4 custom_financials 表结构

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO_INCREMENT | 主键 |
| `stock_code` | VARCHAR(10) | NOT NULL | 股票代码 |
| `fiscal_year` | INT | NOT NULL | 财年 |
| `total_revenue` | DECIMAL(18,4) | NULL | 营业总收入（亿元） |
| `operating_cost` | DECIMAL(18,4) | NULL | 营业总成本（亿元） |
| `operating_profit` | DECIMAL(18,4) | NULL | 营业利润（亿元） |
| `total_profit` | DECIMAL(18,4) | NULL | 利润总额（亿元） |
| `net_profit` | DECIMAL(18,4) | NULL | 归母净利润（亿元） |
| `total_assets` | DECIMAL(18,4) | NULL | 资产总计（亿元） |
| `total_equity` | DECIMAL(18,4) | NULL | 归母股东权益（亿元） |
| `net_cashflow_oper` | DECIMAL(18,4) | NULL | 经营活动现金流量净额（亿元） |
| `basic_eps` | DECIMAL(10,4) | NULL | 基本每股收益（元） |
| `roe` | DECIMAL(10,4) | NULL | 加权平均净资产收益率（%） |
| `gross_margin` | DECIMAL(10,4) | NULL | 毛利率（%） |
| `net_margin` | DECIMAL(10,4) | NULL | 净利率（%） |
| `debt_ratio` | DECIMAL(10,4) | NULL | 资产负债率（%） |
| `short_borrow` | DECIMAL(18,4) | NULL | 短期借款（亿元） |
| `noncurrent_liab_due1y` | DECIMAL(18,4) | NULL | 一年内到期的非流动负债（亿元） |
| `long_borrow` | DECIMAL(18,4) | NULL | 长期借款（亿元） |
| `bonds_payable` | DECIMAL(18,4) | NULL | 应付债券（亿元） |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

> 唯一约束：UNIQUE(stock_code, fiscal_year, report_period)。`report_period` 为 ENUM('FY','Q1','Q2','Q3')，FY=年报、Q1=一季报、Q2=中报、Q3=三季报。数据来源为东方财富 datacenter-web API，原始单位（元）入库前除以 1e8 转换为亿元。前端查询时动态计算核心利润率、净利润率、现金流利润比三个派生指标。支持累计和单季度两种视图。

### 3.5 balance_sheets 表结构

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | INT | PK, AUTO_INCREMENT | 主键 |
| `stock_code` | VARCHAR(10) | NOT NULL | 股票代码 |
| `fiscal_year` | INT | NOT NULL | 财年 |
| `monetary_funds` | DECIMAL(18,4) | NULL | 货币资金（亿元） |
| `trading_fin_assets` | DECIMAL(18,4) | NULL | 交易性金融资产（亿元） |
| `notes_receivable` | DECIMAL(18,4) | NULL | 应收票据（亿元） |
| `accounts_receivable` | DECIMAL(18,4) | NULL | 应收账款（亿元） |
| `receivables_financing` | DECIMAL(18,4) | NULL | 应收款项融资（亿元） |
| `prepayment` | DECIMAL(18,4) | NULL | 预付款项（亿元） |
| `other_receivables` | DECIMAL(18,4) | NULL | 其他应收款（亿元） |
| `inventory` | DECIMAL(18,4) | NULL | 存货（亿元） |
| `noncurrent_assets_due1y` | DECIMAL(18,4) | NULL | 一年内到期非流动资产（亿元） |
| `other_current_assets` | DECIMAL(18,4) | NULL | 其他流动资产（亿元） |
| `total_current_assets` | DECIMAL(18,4) | NULL | 流动资产合计（亿元） |
| `held_to_maturity_invest` | DECIMAL(18,4) | NULL | 持有至到期投资（亿元） |
| `longterm_equity_invest` | DECIMAL(18,4) | NULL | 长期股权投资（亿元） |
| `investment_property` | DECIMAL(18,4) | NULL | 投资性房地产（亿元） |
| `cip` | DECIMAL(18,4) | NULL | 在建工程（亿元） |
| `fixed_assets` | DECIMAL(18,4) | NULL | 固定资产（亿元） |
| `right_of_use_assets` | DECIMAL(18,4) | NULL | 使用权资产（亿元） |
| `intangible_assets` | DECIMAL(18,4) | NULL | 无形资产（亿元） |
| `development_expenditure` | DECIMAL(18,4) | NULL | 开发支出（亿元） |
| `goodwill` | DECIMAL(18,4) | NULL | 商誉（亿元） |
| `longterm_prepaid_expense` | DECIMAL(18,4) | NULL | 长期待摊费用（亿元） |
| `deferred_tax_assets` | DECIMAL(18,4) | NULL | 递延所得税资产（亿元） |
| `other_noncurrent_assets` | DECIMAL(18,4) | NULL | 其他非流动资产（亿元） |
| `total_noncurrent_assets` | DECIMAL(18,4) | NULL | 非流动资产合计（亿元） |
| `total_assets` | DECIMAL(18,4) | NULL | 资产总计（亿元） |
| `short_borrow` | DECIMAL(18,4) | NULL | 短期借款（亿元） |
| `notes_payable` | DECIMAL(18,4) | NULL | 应付票据（亿元） |
| `accounts_payable` | DECIMAL(18,4) | NULL | 应付账款（亿元） |
| `advance_receipts` | DECIMAL(18,4) | NULL | 预收款项（亿元） |
| `payroll_payable` | DECIMAL(18,4) | NULL | 应付职工薪酬（亿元） |
| `taxes_payable` | DECIMAL(18,4) | NULL | 应交税费（亿元） |
| `other_payables` | DECIMAL(18,4) | NULL | 其他应付款（亿元） |
| `noncurrent_liab_due1y` | DECIMAL(18,4) | NULL | 一年内到期非流动负债（亿元） |
| `other_current_liabilities` | DECIMAL(18,4) | NULL | 其他流动负债（亿元） |
| `total_current_liabilities` | DECIMAL(18,4) | NULL | 流动负债合计（亿元） |
| `long_borrow` | DECIMAL(18,4) | NULL | 长期借款（亿元） |
| `bonds_payable` | DECIMAL(18,4) | NULL | 应付债券（亿元） |
| `lease_liabilities` | DECIMAL(18,4) | NULL | 租赁负债（亿元） |
| `deferred_tax_liabilities` | DECIMAL(18,4) | NULL | 递延所得税负债（亿元） |
| `total_noncurrent_liabilities` | DECIMAL(18,4) | NULL | 非流动负债合计（亿元） |
| `total_liabilities` | DECIMAL(18,4) | NULL | 负债合计（亿元） |
| `paid_in_capital` | DECIMAL(18,4) | NULL | 实收资本（亿元） |
| `capital_reserve` | DECIMAL(18,4) | NULL | 资本公积（亿元） |
| `treasury_stock` | DECIMAL(18,4) | NULL | 库存股（亿元） |
| `surplus_reserve` | DECIMAL(18,4) | NULL | 盈余公积（亿元） |
| `retained_earnings` | DECIMAL(18,4) | NULL | 未分配利润（亿元） |
| `parent_equity` | DECIMAL(18,4) | NULL | 归母股东权益（亿元） |
| `minority_interests` | DECIMAL(18,4) | NULL | 少数股东权益（亿元） |
| `total_equity` | DECIMAL(18,4) | NULL | 股东权益合计（亿元） |
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

> 唯一约束：UNIQUE(stock_code, fiscal_year, report_period)。`report_period` 为 ENUM('FY','Q1','Q2','Q3')。数据来源为新浪财经资产负债表页面 HTML 解析，原始单位（万元）入库前除以 10000 转换为亿元。共 49 个资产负债表科目。支持年报和季报（一季报/中报/三季报），前端可切换累计/单季度视图。

---

## 四、API 接口文档

### 4.1 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/stocks` | 分页查询股票列表 |
| GET | `/api/stock/<code>` | 查询单只股票详情 |
| POST | `/api/stock` | 新增股票（支持代码或名称） |
| PUT | `/api/stock/<code>` | 更新股票 |
| DELETE | `/api/stock/<code>` | 删除股票 |
| GET | `/api/stats` | 统计概览 |
| GET | `/api/stock-search` | 代码或名称搜索（本地DB+东方财富） |
| GET | `/api/stock-info/<code>` | 从东方财富获取股票名称和市场 |
| GET | `/api/stock/<code>/dividends` | 查询分红数据 |
| POST | `/api/update-dividends` | 全量/增量更新分红与PE数据 |
| GET | `/api/stock/<code>/financials` | 查询自定义财报（支持年报/季报/累计/单季度） |
| POST | `/api/update-financials` | 从东方财富拉取并更新财报数据（含季报） |
| GET | `/api/stock/<code>/balance-sheet` | 查询资产负债表（支持年报/季报/累计/单季度） |
| POST | `/api/update-balance-sheet` | 从新浪财经拉取并更新资产负债表数据 |
| GET | `/api/stock/<code>/income` | 查询单只股票利润表数据 |
| POST | `/api/update-income` | 从新浪财经拉取并更新利润表数据 |
| GET | `/api/stock/<code>/cashflow` | 查询单只股票现金流量表数据 |
| POST | `/api/update-cashflow` | 从新浪财经拉取并更新现金流量表数据 |
| GET | `/api/stock/<code>/kline` | 获取日K线数据（蜡烛图） |
| GET | `/api/stock/<code>/valuation` | 获取 PE-TTM 估值数据（历史+股价+分位点） |
| GET | `/api/stock/<code>/realtime-quote` | 查询实时行情 |
| GET | `/api/config` | 获取系统配置（掩码） |
| PUT | `/api/config` | 更新系统配置 |
| GET | `/api/stock/<code>/munger-chat` | 获取对话历史 |
| POST | `/api/stock/<code>/munger-chat` | 发送对话消息 |
| DELETE | `/api/stock/<code>/munger-chat?msg_id=N` | 删除单条消息 |
| DELETE | `/api/stock/<code>/munger-chat` | 清空全部对话 |
| GET | `/api/sticky-notes?stock_code=X` | 获取便利贴 |
| POST | `/api/sticky-notes` | 新建便利贴 |
| PUT | `/api/sticky-notes/<id>` | 编辑便利贴 |
| DELETE | `/api/sticky-notes/<id>` | 删除便利贴 |

### 4.2 接口详情

#### GET /api/stocks

分页查询，支持筛选。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 15 | 每页条数 |
| `keyword` | string | — | 代码或名称模糊搜索（支持名称拼音/汉字搜索） |
| `search_type` | string | `code` | 搜索模式：`code`=代码搜索、`name`=名称搜索 |

**响应**：

```json
{
  "total": 20,
  "page": 1,
  "page_size": 15,
  "total_pages": 2,
  "data": [
    {
      "id": 1,
      "code": "600519",
      "name": "贵州茅台",
      "market": "SH",
      "industry": "白酒",
      "list_date": "2001-08-27",
      "status": "正常",
      "pe_ttm": 25.30,
      "dividend_yield": 0.0235,
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

#### POST /api/stock

新增股票。只需提供 `code`，名称和市场通过东方财富 API 自动获取。

**请求体**：

```json
{
  "code": "600000"
}
```

> 支持输入 6 位代码或股票名称，后端自动匹配并填充 name/market。

**成功响应**：`201` + `{"success": true, "message": "添加成功: 浦发银行(600000)"}`

#### PUT /api/stock/<code>

部分更新，只传需修改的字段。code 不可修改。

#### DELETE /api/stock/<code>

物理删除，返回 `{"success": true}` 或 404。

#### GET /api/stats

**响应**：

```json
{
  "total": 20,
  "markets": {"SH": 10, "SZ": 10, "BJ": 0},
  "industries": {"白酒": 2, "银行": 3, "家电": 2, ...}
}
```

#### POST /api/update-dividends

全量或增量更新分红数据与PE数据。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `mode` | string | `full` | 更新模式：`full`=全量更新所有股票，`incremental`=仅更新缺失/过期的股票 |

**数据来源**：

| 数据 | 来源 |
|------|------|
| 净利润 | 东方财富 datacenter-web API（pageSize=200，覆盖上市以来全部年报） |
| 分红方案 | 新浪财经 vISSUE_ShareBonus 页面 |
| PE（动态市盈率） | 腾讯行情接口 qt.gtimg.cn |

**处理逻辑**：

- 遍历 stocks 表中所有（或增量）股票
- 从东方财富获取历年净利润
- 从新浪财经解析分红方案（送股/转增/派息），仅计入"实施"状态的分红记录
- 从腾讯行情获取最新动态市盈率
- 财年映射：分红日期月份 ≤7 归上一财年（年终分红），≥8 归当年（中期分红）
- 股息率计算：取最近两个财年 dividend_per_share 的最大值，除以当前股价
- dividend_per_share 由新浪每10股数据除以 10 得到
- 写入 dividends 表（upsert 逻辑，UNIQUE(stock_code, fiscal_year)）
- 更新 stocks 表的 pe_ttm 和 dividend_yield

**成功响应**：`200` + `{"success": true, "message": "已更新 295 条分红记录", "stocks_processed": 16}`

#### GET /api/stock/&lt;code&gt;/financials

查询单只股票的自定义财报数据，支持年报/季报切换和累计/单季度视图。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `from_year` | int | 2016 | 起始年份 |
| `to_year` | int | 2025 | 结束年份 |
| `period` | string | `FY` | 报告期：FY/Q1/Q2/Q3/all |
| `view` | string | `cumulative` | 视图：cumulative(累计)/single(单季度) |

> `period=all&view=single` 时后端自动计算单季度数据（流量指标=本期累计-上期累计）。

**响应**：

```json
{
  "data": [
    {
      "stock_code": "600519",
      "fiscal_year": 2025,
      "total_revenue": 1741.44,
      "total_revenue_yoy": 15.66,
      "net_profit": 893.27,
      "net_profit_yoy": 15.45,
      "roe": 29.83,
      "roe_yoy": -2.36,
      "core_profit_rate": 74.60,
      "net_profit_rate": 51.30,
      "cashflow_to_profit": 95.60,
      "dividend_amount": 746.50,
      "dividend_per_share": 59.49,
      "dividend_payout_ratio": 83.57,
      "basic_eps": 71.12,
      "dividend_yield_fin": 3.89,
      "debt_ratio": 19.29,
      "interest_bearing_debt_ratio": 0.52
    }
  ]
}
```

> 派生指标由后端动态计算。除上述三个外，还包括 `dividend_payout_ratio`（分红率）、`interest_bearing_debt_ratio`（有息负债率）、`dividend_yield_fin`（股息率）。`dividend_amount`、`dividend_per_share` 通过 LEFT JOIN dividends 表按 fiscal_year 关联获取。

#### POST /api/update-financials

从东方财富 API 拉取全部报告类型的数据，按财年取 NOTICE_DATE 最晚的报告（已完成财年自然取年报，当年取最新累计季报），进行单位转换后 upsert 写入 custom_financials 表。

**请求体**：

```json
{
  "code": "600519"
}
```

**数据来源**：东方财富 datacenter-web API，pageSize=200 覆盖全部年报。

**字段映射与转换**：

| 东方财富字段 | 目标字段 | 转换 |
|------|------|------|
| TOTALOPERATEREVE | total_revenue | 元 → 亿元（÷1e8） |
| TOTALOPERATEEXP | operating_cost | 元 → 亿元 |
| OPERATEPROFIT | operating_profit | 元 → 亿元 |
| TOTPROFIT | total_profit | 元 → 亿元 |
| PARENTNETPROFIT | net_profit | 元 → 亿元 |
| TOTALASSETS | total_assets | 元 → 亿元 |
| TOTALSHOLDEREQUITY | total_equity | 元 → 亿元 |
| KCFJCXJJE | net_cashflow_oper | 元 → 亿元 |
| BASICEPS | basic_eps | 元，保持原值 |
| ROEJQ | roe | %，保持原值 |
| XSMLL | gross_margin | %，保持原值 |
| XSJLL | net_margin | %，保持原值 |
| ZCFZL | debt_ratio | %，保持原值 |
| STBORROW | short_borrow | 元 → 亿元 |
| NCLDUE1Y | noncurrent_liab_due1y | 元 → 亿元 |
| LTBORROW | long_borrow | 元 → 亿元 |
| BONDSPAYABLE | bonds_payable | 元 → 亿元 |

**派生指标（后端计算）**：

| 派生指标 | 公式 | 说明 |
|------|------|------|
| core_profit_rate | (total_revenue - operating_cost) / total_revenue × 100 | 核心利润率 |
| net_profit_rate | net_profit / total_revenue × 100 | 净利润率 |
| cashflow_to_profit | net_cashflow_oper / net_profit × 100 | 现金流利润比 |
| dividend_payout_ratio | dividend_amount / net_profit × 100 | 分红率 |
| interest_bearing_debt_ratio | (short_borrow + noncurrent_liab_due1y + long_borrow + bonds_payable) / total_assets × 100 | 有息负债率 |
| dividend_yield_fin | dividend_per_share / cur_price × 100 | 股息率（基于腾讯行情实时股价） |

**成功响应**：`200` + `{"success": true, "message": "已更新 19 条年报数据", "stock_code": "600519", "count": 19}`

#### GET /api/stock/&lt;code&gt;/balance-sheet

查询指定股票的资产负债表数据，支持年报/季报切换和累计/单季度（delta）视图。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `from_year` | int | 2000 | 起始年份 |
| `to_year` | int | 2030 | 结束年份 |
| `period` | string | `FY` | 报告期：FY/Q1/Q2/Q3/all |
| `view` | string | `cumulative` | 视图：cumulative(快照)/single(delta) |

> `view=single` 时计算各科目环比差值（本期-上期），可用于观察资产负债表变动。

**响应**：

```json
[
  {
    "fiscal_year": 2025,
    "monetary_funds": 516.9061,
    "inventory": 614.2742,
    "total_assets": 3038.3484,
    "total_liabilities": 498.7559,
    "total_equity": 2539.5925,
    ...
  }
]
```

> 完整包含 49 个资产负债表科目字段（流动资产/非流动资产/流动负债/非流动负债/股东权益），详见 §3.5 表结构。

#### POST /api/update-balance-sheet

从新浪财经资产负债表页面解析并更新数据。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `mode` | string | `full` | `full`=全量拉取所有年份，`incremental`=仅补全缺失年份 |

**数据来源**：`https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_BalanceSheet/stockid/{code}/ctrl/part/displaytype/0.phtml`

**处理逻辑**：
- 解析 HTML 中所有"报表日期"表格，提取所有日期列数据
- 同一财年有多列时优先保留最晚日期（已完财年取 12-31 年报，当年取最新季度）
- 中文科目名前缀匹配 49 个 DB 字段（如"货币资金"→monetary_funds、"在建工程(合计)"→cip）
- 新浪原始单位万元，入库前 ÷ 10000 转为亿元
- upsert 写入 balance_sheets 表（UNIQUE(stock_code, fiscal_year)）

**成功响应**：`200` + `{"success": true, "records_updated": 115, "stocks_processed": 7}`

#### GET /api/stock-search

根据代码或名称搜索股票，优先本地 DB，未命中则调用东方财富 suggest API。

**Query 参数**：`keyword` — 搜索关键词（代码或名称）

**响应**：`[{"code": "600519", "name": "贵州茅台", "market": "SH"}, ...]`

#### GET /api/stock/&lt;code&gt;/realtime-quote

返回实时行情数据（股价、PE、市值、股息率）。

**响应**：`{"price": 1680.50, "pe_ttm": 22.3, "market_cap": 21100.0, "dividend_yield": 3.5}`

---

## 五、业务逻辑

### 5.1 股票管理核心流程

```
添加 → 前端表单(仅需输入代码) → POST /api/stock → 后端自动获取名称/市场
                                         → Stock.add() → INSERT
                                         → 返回 201

查询 → 列表页加载 → GET /api/stocks?page=&keyword=
                     → 动态拼接 WHERE + LIMIT/OFFSET
                     → 返回分页数据（关键字支持代码/名称模糊搜索）

编辑 → 点击编辑 → GET /api/stock/<code> 获取详情 → 修改字段
                  → PUT /api/stock/<code> → 白名单字段校验
                                           → 动态 UPDATE SET

删除 → 确认弹窗 → DELETE /api/stock/<code> → 物理删除
```

### 5.2 数据过滤规则

- **关键字搜索**：同时对 `code` 和 `name` 做模糊匹配（LIKE %xxx%），支持股票名称拼音搜索
- **分页**：默认每页 15 条，超范围页码自动由 `total_pages` 限制

### 5.3 添加股票

- 弹窗只需输入股票代码（支持 6 位代码或名称搜索），名称和市-场通过东方财富 API 自动获取
- 编辑时 code 字段锁定（不可修改主键）
- 操作结果 Toast 提示（2.5 秒自动消失）

### 5.4 前端交互逻辑

- 搜索框 400ms 防抖，减少无效请求
- 详情页切换股票时保留当前标签页（分红/自定义财报/资产负债表）
- 图表弹窗复用共享模态窗，对比股票时显示双方 CAGR
- 删除前 `confirm()` 二次确认
- 添加股票支持输入代码或名称，自动匹配
- 详情页顶部下拉框可切换自选股

### 5.5 季报与同比

- 自定义财报和资产负债表支持年报/季报切换
- 季报可选择全部/Q1/Q2/Q3，视图可选累计/单季度
- 单季度数据由后端计算：流量指标（营收/利润/现金流）= 本期累计 - 上期累计
- 同比（YoY）：同报告期跨年比较，如 Q2 2025 vs Q2 2024
- 表格中原值和同比%双列展示，同比正值红色、负值绿色

### 5.6 股票对比

- 在自定义财报和资产负债表标签页输入对比股票代码或名称
- 表格上方显示"主股票 vs 对比股票"
- 每个指标名占两行（rowspan=2），上行主股票、下行对比股票（橙色背景）
- 对比股票也展示同比数据（同季度跨年）
- 图表弹窗同时展示两支股票的柱状图 + 同比折线

### 5.7 图表可视化

- 点击指标旁的小图表图标弹出 ECharts 弹窗
- 柱状图展示指标数值（蓝色主股票、橙色对比股票）
- 折线图展示同比增速（绿色，右轴百分比）
- 标题显示 CAGR（年化复合增长率）
- 横轴 oldest→newest 时序排列
- 遮罩/ESC 关闭弹窗

### 5.8 K线走势图

| 特性 | 实现方式 |
|------|------|
| 图表类型 | ECharts K线图（candlestick）+ 成交量柱状图 |
| 数据源 | 腾讯 K线 API（前复权日线） |
| 周期选择 | 近一年 / 两年 / 五年 / 全部 |
| 颜色 | 红涨绿跌蜡烛，成交量同色联动 |
| 双网格 | 上方 K线（65%）+ 下方成交量（15%） |
| 提示框 | 横轴十字线，显示 OHLCV 五要素 |

### 5.9 估值分析（PE-TTM 四轮演进）

PE-TTM 历史走势 + 分位点 + 股价联动，支持时间范围切换。

**计算演进**：

| 轮次 | 方法 | 问题 |
|------|------|------|
| R1 | 股价 / 年报 EPS | 2026年仍用2024EPS，PE虚高12.81 |
| R2 | TTM = 年报 - 去年同期 + 今年累计 | 9月30日提前用了Q3数据 |
| R3 | R2 + 披露延迟（年报5月/Q3 11月生效） | 基本准确 |
| R4 | R3 + 归母净利润/总股本（替代EPSJB） | **当前方法，最新PE=8.96与腾讯完全一致** |

**当前算法**：
```
TTM_EPS = PARENTNETPROFIT / TOTAL_SHARE  （每期独立获取总股本）
PE = 前复权股价 / TTM_EPS
```
数据源：东方财富「全部报告类型」+ 腾讯前复权K线。分位点在前端基于筛后数据实时计算。

| 特性 | 实现方式 |
|------|------|
| PE-TTM 计算 | 股价（前复权）/ TTM EPS（归母净利润÷总股本），披露延迟后生效 |
| 当前 PE | 图表和侧边栏统一为 归母净利润计算值，同时传 realtime_pe 供参考 |
| 分位点 | 80%/50%/20% 基于所选时间范围在**前端实时计算** |
| 股价数据 | 腾讯 K线 API 分批拉取（最多 8 批 ≈ 20 年），去重后排序 |
| 时间范围 | 上市以来 / 20年 / 10年 / 5年 / 3年 / 1年 |
| 图表 | 双Y轴折线：PE-TTM（蓝）+ 分位虚线（红/灰/绿）+ 股价（橙），Y轴 padding 1% |
| 标记点 | 蓝色大头针标最高 PE，绿色标最低 PE |

### 5.10 对话芒格（💬）

每只股票独立的实时对话，芒格人格（Full Munger Skill），支持 Web 搜索和链接分析。

| 特性 | 实现方式 |
|------|------|
| System Prompt | 完整芒格人格：5大心智模型 + 8条启发式 + Agentic 工作流 |
| 模型 | DeepSeek V4 Pro，temperature=0.3，max_tokens=1000 |
| Web 搜索 | DuckDuckGo Lite → 标题捕获，触发词（?/怎么/为什么/查/搜索） |
| 链接分析 | 三层抓取（Jina Reader → Google 缓存 → 直接请求） |
| 上下文 | 财务摘要(PE/ROE/ROIC/负债率) + 最近10条历史 + 搜索结果前3条全文 |
| 消息管理 | 单条删除 + 清空全部，GET/POST/DELETE API |
| 存储 | `munger_chats` 表，按 stock_code 隔离 |

### 5.11 便利贴（📌）

股票详情页标签，每只股票独立笔记。标题 + 内容两个字段，内容支持文字/链接/图片混排自动识别。

> ⚠️ v2.8 起便利贴从 MySQL `sticky_notes` 表迁移到 JSON 文件存储（`data/sticky_notes.json`），base64 图片自动提取为独立文件（`data/images/`），实现 Git + Syncthing 跨设备同步。

| 特性 | 实现方式 |
|------|------|
| 输入 | 标题 + 内容 textarea（无类型选择器），关联股票下拉选择 |
| 粘贴图片 | Ctrl+V 自动转 base64 data URI 插入，保存时后端提取为文件 |
| 查看原图 | 点击图片全屏深色浮层查看（`background:rgba(0,0,0,.85)`） |
| 存储 | `data/sticky_notes.json`（文字）+ `data/images/*.png`（图片，.gitignore） |
| API | GET(按stock_code过滤)/POST/PUT/DELETE，图片服务 `/data/images/<path>` |
| 切换股票 | 自动检测 `panel-sticky` 显示状态 → 调用 `loadStickyNotes()` |
| 串号防护 | 下拉未填充时兜底取 `detailCode.textContent`，防止存为错误 stock_code |
| 图片渲染 | 新增 `/data/images/` 路径正则匹配，本地图片路径自动转 `<img>` |

### 5.12 Web 页面抓取三层回退

```
Jina Reader (r.jina.ai) → Google Cache → 直接HTTP + 正则剥HTML
```

雪球等 JS SPA 页面通过 Google 缓存绕过 JS 渲染瓶颈。
| 侧边栏 | 当前值 / 分位点 / 80%-50%-20% / 最大-平均-最小，联动时间范围 |

### 5.13 移动端响应式适配（v2.8）

纯 CSS 渐进增强，两个断点（768px + 640px），不改 JS。640px 块覆盖 15 个模块：

| 模块 | 适配策略 |
|------|------|
| Header | 竖排堆叠，标题缩小 |
| Toolbar | 搜索框 `flex:1` 占满，按钮缩小 |
| Tab 栏 | `overflow-x:auto` 左右滑动，隐藏滚动条 |
| 实时卡片 | 一行两列 (`flex:1 1 calc(50%-6px)`) |
| 财务表格 | sticky 列缩至 120px，整体 `thead` 吸顶 |
| 估值侧边栏 | 侧边栏变横向 flex 条，图表高度 300px |
| 图表 | K线/估值/分红 高度 500→300px |
| 对话芒格 | 聊天气泡间距缩小，输入栏紧凑 |
| 弹窗 | `.row` 改为 `flex-direction:column` |
| Toast | 顶部→底部居中 |

> `thead { position:sticky;top:0 }` + `border-collapse:separate;border-spacing:0` 替代逐 `<th>` 方案，解决年份表头滚动时不冻结问题。

### 5.14 跨设备同步（v2.8）

家庭/公司电脑间的便利贴同步方案：

| 数据类型 | 存储 | 同步方式 |
|----------|------|----------|
| 文字内容 | `data/sticky_notes.json` | Git push/pull |
| 图片文件 | `data/images/*.png` | Syncthing / 坚果云 / OneDrive |

手机局域网访问：改 `app.run(host="0.0.0.0")` + 防火墙放行 TCP 5002。

### 5.10 利润表 & 现金流量表

与资产负债表共享通用渲染逻辑（`renderFinanceTable`），支持：

| 特性 | 利润表 | 现金流量表 |
|------|--------|------------|
| 科目分组 | 收入/成本费用/其他收益/利润/每股指标/综合收益 | 经营/投资/筹资活动现金流 |
| 年报/季报 | ✓ 支持 FY/all 切换 | ✓ |
| 同比列 | ✓ 涨红跌绿 | ✓ |
| 对比股票 | ✓ 橙色子行 | ✓ |
| 图表弹窗 | ✓ 柱状图+YoY折线+CAGR | ✓ |

### 5.11 统一数据更新

首页「⟳ 更新数据」按钮弹出模式选择弹窗：

| 模式 | 说明 |
|------|------|
| 增量更新 | 补全缺失年份数据（快速） |
| 全量更新 | 重新拉取全部历史数据（较慢） |

点击后一次性调用 5 个 API（分红/财报/资产负债表/利润表/现金流量表），Toast 汇总结果。

### 5.8 数据源与采集逻辑

#### 股票详情页实时行情卡片（v1.2 新增）

进入任意股票详情页时，页面顶部展示一行 4 张横向排列的实时行情指标卡片，数据通过腾讯行情接口 `qt.gtimg.cn` 实时拉取：

| 卡片 | 指标 | 数据来源 | 说明 |
|------|------|------|------|
| 最新股价 | `cur_price` | `qt.gtimg.cn` `parts[3]` | 实时成交价（元），保留 2 位小数 |
| PE(TTM) | `pe_ttm` | `qt.gtimg.cn` `parts[39]` | 动态市盈率，与 stocks 表 pe_ttm 字段联动更新 |
| 股息率 | `dividend_yield` | 后端计算 | MAX(最近两财年每股分红) / cur_price，前端格式化显示百分比 |
| 最新市值 | `market_cap` | `qt.gtimg.cn` `parts[45]` | 总市值（亿元），原始单位（元）÷ 1e8 |

**技术实现**：

- **后端接口**：`GET /api/stock/<code>/realtime-quote`，解析 `qt.gtimg.cn` 返回的 `~` 分隔字符串，提取 `parts[3]`（股价）、`parts[39]`（PE）、`parts[45]`（市值），结合 dividends 表计算股息率后返回 JSON。
- **前端渲染**：CSS Grid 横向排列 4 张卡片，每张卡片包含标签、数值和单位，响应式布局自动适配窗口宽度。
- **数据刷新**：页面加载时异步请求实时行情，不影响详情页主体数据渲染；后续可扩展定时轮询。

#### 自定义财报标签页

前端横向滚动表格展示多年财务指标对比，支持指标行拖拽排序：

| 特性 | 实现方式 |
|------|------|
| 排序入口 | 工具栏"调整排序"按钮，点击进入排序模式，再次点击退出 |
| 拖拽方式 | 排序模式下指标行首列显示 ⋮⋮ 手柄，mousedown 拖拽手柄上下移动 |
| 视觉反馈 | 浮动 ghost 行跟随鼠标 + 蓝色插入线指示目标位置 |
| 顺序持久化 | localStorage key `financials-indicator-order` |
| 年份排列 | 倒序（最近年份在前），SQL ORDER BY fiscal_year DESC |
| 同比着色 | 正值红色 `.fin-yoy-up`，负值绿色 `.fin-yoy-down` |
| 表格滚动 | 横向滚动，首列（指标名）sticky 固定 |
| 图表弹窗 | 指标名后带小图表图标，点击弹出 ECharts 折线图模态窗（数据点标签、百分比Y轴带%号、遮罩/ESC关闭） |

#### 资产负债表标签页

前端横向滚动表格展示多年资产负债表对比，按 流动资产/非流动资产/流动负债/非流动负债/股东权益 分组：

| 特性 | 实现方式 |
|------|------|
| 分组标题 | 每组第一行为蓝色背景的类别标题行（如"流动资产"） |
| 年份排列 | 倒序（最近年份在前），SQL ORDER BY fiscal_year DESC |
| 合计行 | 流动资产合计/非流动资产合计/资产总计等加粗显示 |
| 表格滚动 | 横向滚动，首列（科目名）sticky 固定 |
| 图表弹窗 | 每科目名后带小图表图标，点击弹出 ECharts 折线图弹窗（Y轴单位亿元、遮罩/ESC关闭） |
| 数据源 | 新浪财经资产负债表页面 `displaytype/0`，覆盖上市以来全部年份 |
| 当前年份 | 已完成财年取 12-31 年报列，当前未完成财年取最新季度列（如 Q1） |

#### PE 数据源

- **接口**：`https://qt.gtimg.cn/q={prefix}{code}`
- **prefix 规则**：SH → `sh`，SZ → `sz`
- **解析**：返回字符串按 `~` 分割，`parts[39]` 为动态市盈率

#### 分红数据源

- **接口**：`https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml`
- **解析**：解析 HTML 中的 `<tr>` 块，提取送股/转增/派息（每10股数据）
- **过滤**：仅计入"实施"状态的分红记录
- **换算**：每10股派息数据除以 10 得到 dividend_per_share（每股分红/元）

#### 净利润数据源

- **接口**：东方财富 datacenter-web API
- **参数**：`pageSize=200`，确保覆盖上市以来全部年报数据（A股最老约30年）
- **用途**：获取历年净利润（亿元），写入 dividends.net_profit

#### 分红图表可视化

分红详情页使用 ECharts 柱状图+折线图混合图表，双 Y 轴布局：

| 系列 | 图表类型 | Y 轴 | 颜色 | 说明 |
|------|------|------|------|------|
| 净利润 | 柱状图 | 左轴（亿元） | 蓝色 `#4a6cf7` | 各财年归母净利润 |
| 分红金额 | 柱状图 | 左轴（亿元） | 绿色 `#52c41a` | 各财年分红总额 |
| 分红比例 | 折线图 | 右轴（%） | 橙色 `#fa8c16` | 分红金额 ÷ 净利润 × 100% |

前端直接计算 `payout_ratio = dividend_amount / net_profit * 100`，无需额外后端接口。

此外，分红页面顶部提供**起始年/结束年下拉框**，用户选择年份范围后自动筛选该区间内的分红数据，图表和表格同步更新。默认覆盖全部可用年份，无需手动清空范围即可查看全量数据。

#### 财年映射规则

| 除权除息日月份 | 归属财年 | 说明 |
|------|------|------|
| 1月 ~ 7月 | 上一年 | 年终分红 |
| 8月 ~ 12月 | 当前年 | 中期分红 |

#### 股息率计算

取最近两个财年 dividend_per_share 的最大值，除以当前股价，公式：

```
dividend_yield = MAX(dps_last_year, dps_year_before) / current_price
```

---

## 六、项目结构

```
D:\\stock-analysis-system\\
├── .gitignore            # Git 忽略规则（含 data/images/）
├── app.py                # Flask 入口 + RESTful API
├── config.py             # 数据库配置
├── config_manager.py     # 系统配置管理（API Key）
├── db.py                 # 连接池 + 查询封装
├── munger.py             # 对话芒格引擎
├── models.py             # Stock 数据模型
├── requirements.txt      # Python 依赖
├── data\
│   ├── sticky_notes.json # 便利贴数据（JSON，Git 追踪）
│   └── images\           # 便利贴图片（.gitignore，Syncthing 同步）
└── templates\
    └── index.html        # 前端 SPA（单页应用，~3130行）
```

---

## 七、部署与运行

### 环境要求

| 组件 | 版本 | 路径 |
|------|------|------|
| Python | 3.11.8 | 系统 PATH |
| MySQL | 8.4.9 | `E:\MySQL` |
| Git | 2.54.0 | 系统 PATH |

### Git 远程与 SSH 配置

> 当前网络环境 HTTPS 443 端口被阻断，已将远程地址切换为 SSH 方式。

| 配置项 | 值 | 说明 |
|------|------|------|
| 远程地址 | `git@github.com:hawei07/stock-analysis-system.git` | SSH 协议，替代原 HTTPS 地址 |
| SSH 密钥 | `%USERPROFILE%\.ssh\id_ed25519` | ED25519 密钥对，对应 GitHub 公钥 |
| 本地 SSH 命令 | `core.sshCommand` 固化 | 已通过 `git config` 固化，后续直接 `git push` 即可 |

### 启动步骤

```powershell
# 1. 确保 MySQL 运行
# MySQL 8.4 位于 E:\MySQL\bin\，mysqld.exe 已在后台运行

# 2. 安装依赖（首次）
pip install -r requirements.txt

# 3. 启动 Web 服务
python E:\stock-analysis-system\app.py
# 访问 http://127.0.0.1:5002
```

### 数据库初始化

```sql
CREATE DATABASE IF NOT EXISTS stock_analysis
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- stocks 表由 models.py 首次运行时通过 stock_list.py import 自动创建
-- 导入示例数据：python stock_list.py import
```

---

## 八、开发流程规范

> 遵循 **Agency Agents 七专家流程**，强制产品经理前置分析 + 用户确认门禁。

### 流程

```
用户需求
  ↓
0️⃣ Product Manager (product-manager)     → 需求分析 + 产品设计
  ↓  ⛔ 用户必须确认后才能继续
1️⃣ UI Designer (ui-designer)             → 页面设计
2️⃣ Backend Architect (backend-architect) → 后端/API/数据库
3️⃣ Frontend Developer (frontend-developer)→ 前端实现
4️⃣ API Tester (api-tester)               → 接口测试
5️⃣ Code Reviewer (code-reviewer)         → 代码审查
6️⃣ Git Workflow Master (git-workflow-master) → 提交规范
```

### 规则

| 规则 | 说明 |
|------|------|
| 派发方式 | `delegate_task` 派发子 Agent，禁止 `agency_agents_load` 化身 |
| 第 0 步强制 | 任何需求必须先经产品经理分析，输出需求文档 |
| 用户确认门禁 | 第 0 步后必须等待用户明确确认（"可以"/"开始"），才进入开发 |
| 禁止跳过 | 绝不允许跳过产品经理步骤直接写代码 |

---

## 九、后续扩展规划

### 9.1 当前数据规模

| 指标 | 数值 |
|------|------|
| 股票总数 | 7 只 |
| 分红记录 | 298 条 |
| 财报记录 | 191 条（含季报 670 条） |
| 资产负债表记录 | 157 条 |
| 利润表记录 | 670 条（含 FY/Q1/Q2/Q3） |
| 现金流量表记录 | 652 条（含 FY/Q1/Q2/Q3） |
| K线数据 | 按需实时拉取（腾讯 API） |
| PE 估值数据 | 按需计算，股价分批拉取最多 20 年 |
| 覆盖财年 | 完整覆盖各股票上市以来全部数据 |

| 阶段 | 模块 | 说明 |
|------|------|------|
| 一期（已完成） | 股票列表 | CRUD + 搜索筛选 |
| 二期 | 行情数据 | 接入实时/历史行情，K线数据存储 |
| 三期 | 技术分析 | MACD/KDJ/均线等指标计算与可视化 |
| 四期 | 策略回测 | 自定义策略引擎 + 收益曲线 |
| 五期 | 选股筛选 | 多条件组合筛选 + 排序 |

### 8.2 近期完成 (v2.8)

| 功能 | 说明 |
|------|------|
| 移动端适配 | `@media (max-width:640px)` 纯 CSS，15 模块手机可用 |
| 便利贴 JSON 化 | MySQL → 文件存储，base64 图片分离，支持跨设备同步 |
| 表格表头冻结 | `thead position:sticky` + `border-collapse:separate` |
| 便利贴串号修复 | 下拉异步填充竞态兜底 |
| 分红图表 resize | `switchTab` 遗漏分支补齐 |
*（内容由AI生成，仅供参考）*
