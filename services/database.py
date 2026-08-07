"""Unified database access helpers."""

from contextlib import contextmanager
import logging
import os
import re
import threading
import time

from mysql.connector import pooling
from mysql.connector.errors import PoolError

from config import DB_CONFIG

logger = logging.getLogger(__name__)


def _slow_query_seconds():
    try:
        return float(os.environ.get("STOCK_SLOW_SQL_SECONDS") or 1.0)
    except ValueError:
        return 1.0


DEFAULT_SLOW_QUERY_SECONDS = _slow_query_seconds()


def _pool_wait_seconds():
    try:
        return float(os.environ.get("STOCK_DB_POOL_WAIT_SECONDS") or 8.0)
    except ValueError:
        return 8.0


def _sql_summary(sql):
    text = re.sub(r"\s+", " ", str(sql or "")).strip()
    return text[:240] + ("..." if len(text) > 240 else "")


class Database:
    def __init__(self, config, pool_name="stock_pool", pool_size=5, slow_query_seconds=DEFAULT_SLOW_QUERY_SECONDS):
        self.config = config
        self.pool_name = pool_name
        self.pool_size = pool_size
        self.slow_query_seconds = slow_query_seconds
        self._pool = None
        self._stats_lock = threading.Lock()
        self._stats = {
            "queries": 0,
            "total_seconds": 0.0,
            "slow_queries": 0,
            "errors": 0,
            "last_slow_query": None,
            "last_error": None,
        }

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
        deadline = time.time() + _pool_wait_seconds()
        while True:
            try:
                return self.get_pool().get_connection()
            except PoolError as exc:
                if time.time() >= deadline:
                    raise
                time.sleep(0.1)
            except Exception:
                raise

    def stats(self):
        with self._stats_lock:
            payload = dict(self._stats)
        payload["avg_ms"] = round((payload["total_seconds"] / payload["queries"]) * 1000, 2) if payload["queries"] else 0
        payload["total_ms"] = round(payload["total_seconds"] * 1000, 2)
        payload["slow_query_seconds"] = self.slow_query_seconds
        return payload

    def reset_stats(self):
        with self._stats_lock:
            self._stats = {
                "queries": 0,
                "total_seconds": 0.0,
                "slow_queries": 0,
                "errors": 0,
                "last_slow_query": None,
                "last_error": None,
            }

    def _record(self, operation, sql, elapsed, *, rowcount=None, batch_size=None, error=None):
        summary = _sql_summary(sql)
        elapsed_ms = round(elapsed * 1000, 2)
        is_slow = elapsed >= self.slow_query_seconds

        with self._stats_lock:
            self._stats["queries"] += 1
            self._stats["total_seconds"] += elapsed
            if is_slow:
                self._stats["slow_queries"] += 1
                self._stats["last_slow_query"] = {
                    "operation": operation,
                    "elapsed_ms": elapsed_ms,
                    "rowcount": rowcount,
                    "batch_size": batch_size,
                    "sql": summary,
                }
            if error is not None:
                self._stats["errors"] += 1
                self._stats["last_error"] = {
                    "operation": operation,
                    "elapsed_ms": elapsed_ms,
                    "error": str(error),
                    "sql": summary,
                }

        if is_slow:
            logger.warning(
                "slow database %s %.2fms rows=%s batch=%s sql=%s",
                operation,
                elapsed_ms,
                rowcount,
                batch_size,
                summary,
            )

        if error is not None:
            logger.warning(
                "database %s failed %.2fms error=%s sql=%s",
                operation,
                elapsed_ms,
                error,
                summary,
                exc_info=True,
            )

    def execute(self, sql, params=None, *, fetch=True, dictionary=True):
        conn = self.get_connection()
        cursor = None
        start = time.perf_counter()
        error = None
        rowcount = None
        try:
            cursor = conn.cursor(dictionary=dictionary)
            cursor.execute(sql, params or ())
            if fetch:
                rows = cursor.fetchall()
                rowcount = len(rows)
                return rows
            conn.commit()
            rowcount = cursor.rowcount
            return cursor.rowcount
        except Exception as exc:
            error = exc
            if not fetch:
                conn.rollback()
            raise
        finally:
            self._record("query" if fetch else "update", sql, time.perf_counter() - start, rowcount=rowcount, error=error)
            if cursor:
                cursor.close()
            conn.close()

    def execute_update(self, sql, params=None):
        return self.execute(sql, params, fetch=False)

    def execute_insert(self, sql, params=None):
        conn = self.get_connection()
        cursor = None
        start = time.perf_counter()
        error = None
        rowcount = None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(sql, params or ())
            conn.commit()
            rowcount = cursor.rowcount
            return cursor.lastrowid
        except Exception as exc:
            error = exc
            conn.rollback()
            raise
        finally:
            self._record("insert", sql, time.perf_counter() - start, rowcount=rowcount, error=error)
            if cursor:
                cursor.close()
            conn.close()

    def execute_many(self, sql, seq_params):
        if not seq_params:
            return 0
        conn = self.get_connection()
        cursor = None
        start = time.perf_counter()
        error = None
        rowcount = None
        batch_size = len(seq_params)
        try:
            cursor = conn.cursor()
            cursor.executemany(sql, seq_params or [])
            conn.commit()
            rowcount = cursor.rowcount
            return cursor.rowcount
        except Exception as exc:
            error = exc
            conn.rollback()
            raise
        finally:
            self._record("batch", sql, time.perf_counter() - start, rowcount=rowcount, batch_size=batch_size, error=error)
            if cursor:
                cursor.close()
            conn.close()

    @contextmanager
    def transaction(self, *, dictionary=True):
        conn = self.get_connection()
        cursor = None
        start = time.perf_counter()
        error = None
        try:
            cursor = conn.cursor(dictionary=dictionary)
            yield cursor
            conn.commit()
        except Exception as exc:
            error = exc
            conn.rollback()
            raise
        finally:
            self._record("transaction", "transaction", time.perf_counter() - start, error=error)
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


def database_stats():
    return database.stats()


def reset_database_stats():
    return database.reset_stats()
