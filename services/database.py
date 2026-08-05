"""Unified database access helpers."""

from contextlib import contextmanager

from mysql.connector import pooling

from config import DB_CONFIG


class Database:
    def __init__(self, config, pool_name="stock_pool", pool_size=5):
        self.config = config
        self.pool_name = pool_name
        self.pool_size = pool_size
        self._pool = None

    def get_pool(self):
        if self._pool is None:
            self._pool = pooling.MySQLConnectionPool(
                pool_name=self.pool_name,
                pool_size=self.pool_size,
                **self.config,
            )
        return self._pool

    def reset_pool(self):
        self._pool = None

    def get_connection(self):
        return self.get_pool().get_connection()

    def execute(self, sql, params=None, *, fetch=True, dictionary=True):
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=dictionary)
            cursor.execute(sql, params or ())
            if fetch:
                return cursor.fetchall()
            conn.commit()
            return cursor.rowcount
        except Exception:
            if not fetch:
                conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            conn.close()

    def execute_update(self, sql, params=None):
        return self.execute(sql, params, fetch=False)

    def execute_insert(self, sql, params=None):
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params or ())
            conn.commit()
            return cursor.lastrowid
        except Exception:
            conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            conn.close()

    def execute_many(self, sql, seq_params):
        if not seq_params:
            return 0
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, seq_params or [])
            conn.commit()
            return cursor.rowcount
        except Exception:
            conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            conn.close()

    @contextmanager
    def transaction(self, *, dictionary=True):
        conn = self.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(dictionary=dictionary)
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if cursor:
                cursor.close()
            conn.close()


database = Database(DB_CONFIG)


def get_pool():
    return database.get_pool()


def reset_pool():
    return database.reset_pool()


def get_connection():
    return database.get_connection()


def execute_query(sql, params=None, fetch=True):
    return database.execute(sql, params, fetch=fetch)


def execute_update(sql, params=None):
    return database.execute_update(sql, params)


def execute_insert(sql, params=None):
    return database.execute_insert(sql, params)


def execute_many(sql, seq_params):
    return database.execute_many(sql, seq_params)


def transaction(*, dictionary=True):
    return database.transaction(dictionary=dictionary)
