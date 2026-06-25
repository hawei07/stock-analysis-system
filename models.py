"""数据模型 — 股票基础信息"""

from db import execute_query, execute_update


class Stock:
    """股票模型"""

    @staticmethod
    def get_all(page=1, page_size=20, market=None, status=None, keyword=None):
        """分页查询股票列表，支持按市场/状态筛选和关键字搜索"""
        conditions = []
        params = []

        if market:
            conditions.append("market = %s")
            params.append(market)
        if status:
            conditions.append("status = %s")
            params.append(status)
        if keyword:
            conditions.append("(code LIKE %s OR name LIKE %s)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        count_sql = f"SELECT COUNT(*) AS total FROM stocks{where}"
        total = execute_query(count_sql, params)[0]["total"]

        offset = (page - 1) * page_size
        data_sql = f"SELECT * FROM stocks{where} ORDER BY code LIMIT %s OFFSET %s"
        rows = execute_query(data_sql, params + [page_size, offset])

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "data": rows,
        }

    @staticmethod
    def get_by_code(code):
        """根据股票代码查询"""
        rows = execute_query("SELECT * FROM stocks WHERE code = %s", (code,))
        return rows[0] if rows else None

    @staticmethod
    def add(code, name, market, industry=None, list_date=None, status="正常"):
        """添加一只股票"""
        sql = """INSERT INTO stocks (code, name, market, industry, list_date, status)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        return execute_update(sql, (code, name, market, industry, list_date, status))

    @staticmethod
    def update(code, **kwargs):
        """更新股票信息，kwargs 为要更新的字段"""
        if not kwargs:
            return 0
        allowed = {"name", "market", "industry", "list_date", "status", "pe_ttm", "dividend_yield"}
        sets = [f"{k} = %s" for k in kwargs if k in allowed]
        values = [v for k, v in kwargs.items() if k in allowed]
        if not sets:
            return 0
        values.append(code)
        sql = f"UPDATE stocks SET {', '.join(sets)} WHERE code = %s"
        return execute_update(sql, values)

    @staticmethod
    def delete(code):
        """删除一只股票"""
        return execute_update("DELETE FROM stocks WHERE code = %s", (code,))

    @staticmethod
    def batch_add(stocks_list):
        """批量导入股票"""
        sql = """INSERT INTO stocks (code, name, market, industry, list_date, status)
                 VALUES (%s, %s, %s, %s, %s, %s)
                 ON DUPLICATE KEY UPDATE name=VALUES(name), market=VALUES(market),
                 industry=VALUES(industry), list_date=VALUES(list_date), status=VALUES(status)"""
        conn = None
        try:
            from db import get_connection
            conn = get_connection()
            cursor = conn.cursor()
            cursor.executemany(sql, stocks_list)
            conn.commit()
            return cursor.rowcount
        finally:
            if conn:
                conn.close()
