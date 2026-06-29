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

> 版本 v1.0 | 2026-06-25 | Python Flask + MySQL 8.4

---

## 一、项目概述

股票分析系统是一个基于 B/S 架构的股票数据管理平台，当前阶段已实现股票基础信息的全生命周期管理，为后续行情接入、技术分析、策略回测等高级功能提供数据底座。

- **技术栈**：Python 3.11 + Flask + MySQL 8.4
- **访问地址**：`http://127.0.0.1:5002`
- **代码仓库**：`D:\stock-analysis-system`（Git 管理，分支策略 `feature/xxx → main`）

---

## 二、技术架构

```
┌──────────────────────────────────────────┐
│              浏览器 (SPA)                  │
│        Vanilla JS + CSS Variables         │
└──────────────────┬───────────────────────┘
                   │ HTTP RESTful API
┌──────────────────▼───────────────────────┐
│           Flask Web 服务 (app.py)          │
│  路由: / (页面)  /api/* (数据接口)         │
└──────────────────┬───────────────────────┘
                   │ Python 调用
┌──────────────────▼───────────────────────┐
│         数据模型层 (models.py)              │
│        Stock 类 — 纯 SQL 封装              │
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
| 模型层 | `models.py` | 数据库 CRUD 封装（无 ORM，手写 SQL） |
| 持久层 | `db.py` | 连接池管理、查询/更新统一入口 |
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
| `created_at` | DATETIME | DEFAULT CURRENT_TIMESTAMP | 创建时间 |

> 唯一约束：UNIQUE(stock_code, fiscal_year)。数据来源为东方财富 datacenter-web API，原始单位（元）入库前除以 1e8 转换为亿元。前端查询时动态计算核心利润率、净利润率、现金流利润比三个派生指标。

---

## 四、API 接口文档

### 4.1 接口总览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/stocks` | 分页查询股票列表 |
| GET | `/api/stock/<code>` | 查询单只股票详情 |
| POST | `/api/stock` | 新增股票 |
| PUT | `/api/stock/<code>` | 更新股票 |
| DELETE | `/api/stock/<code>` | 删除股票 |
| GET | `/api/stats` | 统计概览 |
| POST | `/api/update-dividends` | 全量/增量更新分红与PE数据 |
| GET | `/api/stock/<code>/financials` | 查询单只股票自定义财报数据 |
| POST | `/api/update-financials` | 从东方财富拉取并更新财报数据 |

### 4.2 接口详情

#### GET /api/stocks

分页查询，支持筛选。

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `page_size` | int | 15 | 每页条数 |
| `market` | string | — | 市场筛选：SH / SZ / BJ |
| `status` | string | — | 状态筛选 |
| `keyword` | string | — | 代码或名称模糊搜索 |

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

新增股票。必填字段：`code`、`name`、`market`。

**请求体**：

```json
{
  "code": "600000",
  "name": "浦发银行",
  "market": "SH",
  "industry": "银行",
  "list_date": "1999-11-10",
  "status": "正常"
}
```

**成功响应**：`201` + `{"success": true, "message": "添加成功"}`

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

查询单只股票的自定义财报数据，返回历年财务指标及同比变化。

**Path 参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | string | 股票代码（如 600519） |

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
      "cashflow_to_profit": 95.60
    }
  ]
}
```

> 派生指标由后端动态计算：`core_profit_rate`（核心利润率）= (营业总收入 - 营业总成本) / 营业总收入 × 100，`net_profit_rate`（净利润率）= 归母净利润 / 营业总收入 × 100，`cashflow_to_profit`（现金流利润比）= 经营现金流净额 / 归母净利润 × 100。

#### POST /api/update-financials

从东方财富 API 拉取单只股票的全部年报数据，进行单位转换后 upsert 写入 custom_financials 表。

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

**成功响应**：`200` + `{"success": true, "message": "已更新 19 条年报数据", "stock_code": "600519", "count": 19}`

---

## 五、业务逻辑

### 5.1 股票管理核心流程

```
添加 → 前端表单 → POST /api/stock → 参数校验(market ∈ {SH,SZ,BJ})
                                         → Stock.add() → INSERT
                                         → 返回 201

查询 → 列表页加载 → GET /api/stocks?page=&keyword=&market=&status=
                     → 动态拼接 WHERE + LIMIT/OFFSET
                     → 返回分页数据

编辑 → 点击编辑 → GET /api/stock/<code> 获取详情 → 修改字段
                  → PUT /api/stock/<code> → 白名单字段校验
                                           → 动态 UPDATE SET

删除 → 确认弹窗 → DELETE /api/stock/<code> → 物理删除
```

### 5.2 数据过滤规则

- **市场**：精确匹配，SH=上海、SZ=深圳、BJ=北京
- **关键字搜索**：同时对 `code` 和 `name` 做模糊匹配（LIKE %xxx%）
- **状态**：精确匹配 ENUM 值
- **分页**：默认每页 15 条，超范围页码自动由 `total_pages` 限制

### 5.3 连接的线程安全

- 每次请求从连接池获取连接，`try-finally` 确保归还
- 连接池大小 `pool_size=5`，适合单机小规模并发

### 5.4 前端交互逻辑

- 搜索框 400ms 防抖，减少无效请求
- 编辑时 code 字段锁定（不可修改主键）
- 删除前 `confirm()` 二次确认
- 操作结果 Toast 提示（2.5 秒自动消失）

### 5.5 数据源与采集逻辑

#### 自定义财报标签页

前端横向滚动表格展示多年财务指标对比，支持指标行拖拽排序：

| 特性 | 实现方式 |
|------|------|
| 指标行排序 | HTML5 Drag and Drop API，拖拽上下移动指标行 |
| 顺序持久化 | localStorage key `financials-indicator-order` |
| 视觉反馈 | 拖拽行半透明（opacity:0.35），目标位置蓝色边框高亮 |
| 年份排列 | 倒序（最近年份在前），SQL ORDER BY fiscal_year DESC |
| 同比着色 | 正值红色 `.fin-yoy-up`，负值绿色 `.fin-yoy-down` |
| 表格滚动 | 横向滚动，首列（指标名）sticky 固定 |

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
D:\stock-analysis-system\
├── .gitignore            # Git 忽略规则
├── app.py                # Flask 入口 + RESTful API
├── config.py             # 数据库配置
├── db.py                 # 连接池 + 查询封装
├── main.py               # CLI 交互入口（旧版，已由 Web 替代）
├── models.py             # Stock 数据模型
├── requirements.txt      # Python 依赖
├── stock_list.py         # CLI 工具（旧版，保留备用）
└── templates\
    └── index.html        # 前端单页应用
```

---

## 七、部署与运行

### 环境要求

| 组件 | 版本 | 路径 |
|------|------|------|
| Python | 3.11.8 | 系统 PATH |
| MySQL | 8.4.9 | `D:\devtools\mysql`（junction to `D:\开发工具\mysql`） |
| Git | 2.54.0 | `D:\Git\bin\git.exe` |

### 启动步骤

```powershell
# 1. 确保 MySQL 运行
Start-Process "D:\开发工具\mysql\bin\mysqld.exe" `
  -ArgumentList "--defaults-file=D:\devtools\mysql\my.ini" -WindowStyle Hidden

# 2. 安装依赖（首次）
pip install -r requirements.txt

# 3. 启动 Web 服务
python D:\stock-analysis-system\app.py
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

## 八、后续扩展规划

### 8.1 当前数据规模

| 指标 | 数值 |
|------|------|
| 股票总数 | 16 只（SH 7 只，SZ 9 只） |
| 分红记录 | 298 条 |
| 财报记录 | 191 条（7只股票，2016-2025） |
| 覆盖财年 | 完整覆盖各股票上市以来全部分红（最早 1997 年） |

| 阶段 | 模块 | 说明 |
|------|------|------|
| 一期（已完成） | 股票列表 | CRUD + 搜索筛选 |
| 二期 | 行情数据 | 接入实时/历史行情，K线数据存储 |
| 三期 | 技术分析 | MACD/KDJ/均线等指标计算与可视化 |
| 四期 | 策略回测 | 自定义策略引擎 + 收益曲线 |
| 五期 | 选股筛选 | 多条件组合筛选 + 排序 |
*（内容由AI生成，仅供参考）*
