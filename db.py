"""数据库连接管理"""

import mysql.connector
from mysql.connector import pooling
from config import DB_CONFIG

_pool = None


def get_pool():
    """获取连接池（懒加载）"""
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="stock_pool",
            pool_size=5,
            **DB_CONFIG,
        )
    return _pool


def get_connection():
    """从连接池获取一个连接"""
    return get_pool().get_connection()


def execute_query(sql, params=None, fetch=True):
    """执行查询，返回结果列表"""
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        if fetch:
            return cursor.fetchall()
        conn.commit()
        return cursor.rowcount
    finally:
        cursor.close()
        conn.close()


def execute_update(sql, params=None):
    """执行增删改，返回影响行数"""
    return execute_query(sql, params, fetch=False)
