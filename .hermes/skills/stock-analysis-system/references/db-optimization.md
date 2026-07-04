# 数据库优化记录

## COLLATE 统一（2026-07-04，二次修复）

### 问题
第一轮统一了 `stock_code`，但 JOIN 仍然报 `Illegal mix of collations`。深入排查发现 **`report_period` ENUM 列** 也不一致：
- `balance_sheets.report_period`: `utf8mb4_0900_ai_ci`
- `custom_financials.report_period`: `utf8mb4_unicode_ci`
- `custom_financials.audit_opinion`: `utf8mb4_unicode_ci`

JOIN 条件 `cf.report_period = bs.report_period` 触发了 COLLATE 冲突。

### 最终修复
```sql
-- report_period ENUM
ALTER TABLE custom_financials MODIFY report_period 
  ENUM('FY','Q1','Q2','Q3') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- audit_opinion
ALTER TABLE custom_financials MODIFY audit_opinion 
  VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- 有 FK 的表（balance_sheets 的 stock_code 已经是 0900_ai_ci，但若有偏差）：
-- ALTER TABLE balance_sheets DROP FOREIGN KEY bs_ibfk_1;
-- ALTER TABLE balance_sheets MODIFY stock_code VARCHAR(10) ...;
-- ALTER TABLE balance_sheets ADD CONSTRAINT bs_ibfk_1 FOREIGN KEY (stock_code) REFERENCES stocks(code);

-- 验证
SELECT TABLE_NAME, COLUMN_NAME, COLLATION_NAME 
FROM information_schema.COLUMNS 
WHERE TABLE_SCHEMA='stock_analysis' AND COLUMN_NAME IN ('stock_code','code','report_period','audit_opinion')
ORDER BY COLLATION_NAME, TABLE_NAME;
-- 全部应为 utf8mb4_0900_ai_ci
```

### 排查技巧
报 `Illegal mix of collations` 时，检查组 ALL string/ENUM 列，不仅是 JOIN 的 ON 列。运行：
```sql
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, COLLATION_NAME
FROM information_schema.COLUMNS 
WHERE TABLE_SCHEMA='stock_analysis' AND COLLATION_NAME IS NOT NULL
ORDER BY COLLATION_NAME, TABLE_NAME;
-- 分组看哪些表用了不同的 COLLATION
```

## 三表数据一致性验证（Financial Analyst, 2026-07-04）

### 验证方法
使用 Agency Agents 中的 Financial Analyst（Morgan）方法论，对 233 条 FY 数据行进行四项验证。

### 结果

| 检查项 | 结果 | 详情 |
|--------|------|------|
| debt_ratio 公式一致性 | ✅ 完美 | 存储值 = `(TA-TE)/TA*100`，零偏差 |
| 资产负债表 A=L+E | ✅ 1条异常 | BS 内部数据高度自洽 |
| TA 跨表一致 | ⚠️ 14% 偏差 | `custom_financials`(东方财富) vs `balance_sheets`(新浪财经) |
| TE 跨表一致 | ⚠️ 10% 偏差 | 同上，数据源口径差异 |
| 经营性现金流/净利润 | ⚠️ 8% 负值 | 多为亏损年份的正常现象 |

### 结论
- 核心计算逻辑无 bug；`debt_ratio`、`A=L+E` 均正确
- 跨表 `total_assets`/`total_equity` 不一致是**数据源不同**导致的（东方财富 vs 新浪财经），非系统错误
- 建议：前端优先从 `balance_sheets` 取资产负债表数据，`custom_financials` 中的 TA/TE 仅作冗余

## FULLTEXT 索引

### 用途
替代 `LIKE %keyword%` 前导通配符搜索（无法使用 B-tree 索引）。

### DDL
```sql
ALTER TABLE stocks ADD FULLTEXT INDEX ft_code_name (code, name);
```

### 注意事项
- MySQL 默认 `innodb_ft_min_token_size=3`，短于 3 字符的词不索引
- 中文需 ngram parser（`WITH PARSER ngram`），否则分词无效
- 当前数据量小（<20行），LIKE 足够；FULLTEXT 是数据量增长后的预备方案

## SELECT 列优化

### 变更
`Stock.get_all()` 列表查询从 `SELECT *` 改为指定列：
```python
# 旧
SELECT * FROM stocks WHERE ... ORDER BY code LIMIT %s OFFSET %s
# 新
SELECT id, code, name, market, industry, list_date, status FROM stocks ...
```

`get_by_code()` 未改——单行查询，`SELECT *` 性能差异可忽略。

## 当前索引概览

| 表 | 行数 | 列数 | 索引 |
|------|------|------|------|
| stocks | ~10 | 11 | PRIMARY(id), UNIQUE(code), FULLTEXT(code,name) |
| dividends | ~200 | 8 | PRIMARY(id), UNIQUE(stock_code, fiscal_year) |
| custom_financials | ~1000 | 24 | PRIMARY(id), UNIQUE(stock_code, fiscal_year, report_period) |
| balance_sheets | ~900 | 54 | PRIMARY(id), UNIQUE(stock_code, fiscal_year, report_period) |

核心查询 `WHERE stock_code=? AND fiscal_year BETWEEN ? AND ?` 可命中 UNIQUE 索引前缀。当前数据量下无需额外索引。
