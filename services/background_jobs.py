"""Persistent background job helpers."""

import json
import threading
import traceback
from datetime import datetime

from flask import Response


ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"done", "partial", "failed", "cancelled"}


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_dumps(value):
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def _json_loads(value):
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return None


def _ensure_column(execute_query, table, column, definition):
    try:
        rows = execute_query(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
        if not rows:
            execute_query(f"ALTER TABLE {table} ADD COLUMN {column} {definition}", fetch=False)
    except Exception:
        pass


def ensure_background_jobs_table(execute_query):
    execute_query(
        """CREATE TABLE IF NOT EXISTS background_jobs (
            id BIGINT NOT NULL AUTO_INCREMENT,
            job_type VARCHAR(80) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'queued',
            stock_code VARCHAR(20) NULL,
            title VARCHAR(255) NULL,
            progress_current INT NOT NULL DEFAULT 0,
            progress_total INT NOT NULL DEFAULT 0,
            message VARCHAR(500) NULL,
            request_json JSON NULL,
            result_json JSON NULL,
            error TEXT NULL,
            cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_background_jobs_type_status (job_type, status),
            KEY idx_background_jobs_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    _ensure_column(execute_query, "background_jobs", "request_json", "JSON NULL")
    _ensure_column(execute_query, "background_jobs", "cancel_requested", "TINYINT(1) NOT NULL DEFAULT 0")
    execute_query(
        """CREATE TABLE IF NOT EXISTS background_job_logs (
            id BIGINT NOT NULL AUTO_INCREMENT,
            job_id BIGINT NOT NULL,
            level VARCHAR(20) NOT NULL DEFAULT 'info',
            stock_code VARCHAR(20) NULL,
            message VARCHAR(500) NOT NULL,
            detail_json JSON NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_background_job_logs_job_id (job_id),
            KEY idx_background_job_logs_created_at (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )


def create_job(get_connection, execute_query, job_type, title=None, stock_code=None, progress_total=0, message=None, request_payload=None):
    ensure_background_jobs_table(execute_query)
    conn = get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """INSERT INTO background_jobs
               (job_type, status, stock_code, title, progress_total, message, request_json)
               VALUES (%s, 'queued', %s, %s, %s, %s, %s)""",
            (job_type, stock_code, title, int(progress_total or 0), message, _json_dumps(request_payload)),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        if cursor:
            cursor.close()
        conn.close()


def active_job(execute_query, job_type, stock_code=None):
    ensure_background_jobs_table(execute_query)
    if stock_code:
        rows = execute_query(
            """SELECT * FROM background_jobs
               WHERE job_type=%s AND stock_code=%s AND status IN ('queued', 'running')
               ORDER BY id DESC LIMIT 1""",
            (job_type, stock_code),
        )
    else:
        rows = execute_query(
            """SELECT * FROM background_jobs
               WHERE job_type=%s AND stock_code IS NULL AND status IN ('queued', 'running')
               ORDER BY id DESC LIMIT 1""",
            (job_type,),
        )
    return job_payload(rows[0]) if rows else None


def start_job(execute_query, job_id, message=None):
    execute_query(
        """UPDATE background_jobs
           SET status='running', started_at=COALESCE(started_at, %s), message=COALESCE(%s, message), error=NULL
           WHERE id=%s""",
        (_now(), message, job_id),
        fetch=False,
    )


def add_job_log(execute_query, job_id, message, level="info", stock_code=None, detail=None):
    ensure_background_jobs_table(execute_query)
    return execute_query(
        """INSERT INTO background_job_logs (job_id, level, stock_code, message, detail_json)
           VALUES (%s, %s, %s, %s, %s)""",
        (job_id, level, stock_code, str(message)[:500], _json_dumps(detail)),
        fetch=False,
    )


def log_payload(row):
    return {
        "id": row.get("id"),
        "job_id": row.get("job_id"),
        "level": row.get("level"),
        "stock_code": row.get("stock_code"),
        "message": row.get("message"),
        "detail": _json_loads(row.get("detail_json")),
        "created_at": row.get("created_at"),
    }


def list_job_logs(execute_query, job_id, limit=200):
    ensure_background_jobs_table(execute_query)
    rows = execute_query(
        """SELECT id, job_id, level, stock_code, message, detail_json, created_at
           FROM background_job_logs
           WHERE job_id=%s
           ORDER BY id ASC
           LIMIT %s""",
        (job_id, max(1, min(int(limit or 200), 1000))),
    )
    return [log_payload(row) for row in rows]


def request_cancel_job(execute_query, job_id):
    job = get_job(execute_query, job_id)
    if not job:
        return None
    if job["status"] in TERMINAL_STATUSES:
        return job
    execute_query(
        """UPDATE background_jobs
           SET cancel_requested=1, message='正在取消，当前股票处理完后停止'
           WHERE id=%s""",
        (job_id,),
        fetch=False,
    )
    add_job_log(execute_query, job_id, "收到取消请求，当前股票处理完后停止", level="warning")
    return get_job(execute_query, job_id)


def is_cancel_requested(execute_query, job_id):
    rows = execute_query("SELECT cancel_requested FROM background_jobs WHERE id=%s LIMIT 1", (job_id,))
    return bool(rows and rows[0].get("cancel_requested"))


def update_job(execute_query, job_id, progress_current=None, progress_total=None, message=None, result=None):
    sets = []
    params = []
    if progress_current is not None:
        sets.append("progress_current=%s")
        params.append(int(progress_current))
    if progress_total is not None:
        sets.append("progress_total=%s")
        params.append(int(progress_total))
    if message is not None:
        sets.append("message=%s")
        params.append(str(message)[:500])
    if result is not None:
        sets.append("result_json=%s")
        params.append(_json_dumps(result))
    if not sets:
        return 0
    params.append(job_id)
    return execute_query(
        f"UPDATE background_jobs SET {', '.join(sets)} WHERE id=%s",
        tuple(params),
        fetch=False,
    )


def finish_job(execute_query, job_id, status="done", message=None, result=None):
    if status not in TERMINAL_STATUSES:
        status = "done"
    progress_clause = ", progress_current=GREATEST(progress_current, progress_total)" if status == "done" else ""
    execute_query(
        f"""UPDATE background_jobs
           SET status=%s, message=COALESCE(%s, message), result_json=COALESCE(%s, result_json),
               finished_at=%s{progress_clause}
           WHERE id=%s""",
        (status, message, _json_dumps(result), _now(), job_id),
        fetch=False,
    )


def fail_job(execute_query, job_id, error, message=None, result=None):
    error_text = str(error)
    execute_query(
        """UPDATE background_jobs
           SET status='failed', message=COALESCE(%s, message), result_json=COALESCE(%s, result_json),
               error=%s, finished_at=%s
           WHERE id=%s""",
        (message or "后台任务执行失败", _json_dumps(result), error_text, _now(), job_id),
        fetch=False,
    )


def job_payload(row):
    if not row:
        return None
    total = int(row.get("progress_total") or 0)
    current = int(row.get("progress_current") or 0)
    progress_percent = round(current * 100 / total, 2) if total > 0 else None
    return {
        "id": row.get("id"),
        "job_type": row.get("job_type"),
        "status": row.get("status"),
        "stock_code": row.get("stock_code"),
        "title": row.get("title"),
        "progress_current": current,
        "progress_total": total,
        "progress_percent": progress_percent,
        "message": row.get("message"),
        "request": _json_loads(row.get("request_json")),
        "result": _json_loads(row.get("result_json")),
        "error": row.get("error"),
        "cancel_requested": bool(row.get("cancel_requested")),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def get_job(execute_query, job_id):
    ensure_background_jobs_table(execute_query)
    rows = execute_query("SELECT * FROM background_jobs WHERE id=%s LIMIT 1", (job_id,))
    return job_payload(rows[0]) if rows else None


def list_jobs(execute_query, limit=50, job_type=None, status=None):
    ensure_background_jobs_table(execute_query)
    where = []
    params = []
    if job_type:
        where.append("job_type=%s")
        params.append(job_type)
    if status:
        where.append("status=%s")
        params.append(status)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = execute_query(
        f"SELECT * FROM background_jobs {where_sql} ORDER BY id DESC LIMIT %s",
        tuple(params + [max(1, min(int(limit or 50), 200))]),
    )
    return [job_payload(row) for row in rows]


def latest_job(execute_query, job_type=None):
    jobs = list_jobs(execute_query, limit=1, job_type=job_type)
    return jobs[0] if jobs else None


def run_in_thread(execute_query, job_id, target, *args, **kwargs):
    def runner():
        try:
            target(*args, **kwargs)
        except Exception as exc:
            fail_job(execute_query, job_id, traceback.format_exc(), message=str(exc)[:500])

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    return thread


def response_payload(response):
    if isinstance(response, tuple):
        response = response[0]
    if isinstance(response, Response):
        try:
            return response.get_json(silent=True) or {}
        except Exception:
            return {}
    return response if isinstance(response, dict) else {}


def start_endpoint_stock_batch(
    app,
    get_connection,
    execute_query,
    job_type,
    title,
    payload,
    stocks,
    endpoint_func,
    endpoint_path,
    on_finish=None,
):
    payload = dict(payload or {})
    stocks = list(stocks or [])
    if not payload.get("force"):
        running_job = active_job(execute_query, job_type)
        if running_job:
            return {
                "success": True,
                "already_running": True,
                "background": True,
                "job_id": running_job["id"],
                "job_type": job_type,
                "stocks_processed": running_job.get("progress_current") or 0,
                "stocks_total": running_job.get("progress_total") or len(stocks),
                "message": running_job.get("message") or f"{title}正在后台执行",
            }
    job_id = create_job(
        get_connection,
        execute_query,
        job_type,
        title=title,
        progress_total=len(stocks),
        message="等待开始",
        request_payload=payload,
    )

    def runner():
        updated = 0
        processed = 0
        errors = []
        start_job(execute_query, job_id, "后台任务已开始")
        add_job_log(execute_query, job_id, f"{title}开始，共 {len(stocks)} 只股票")
        try:
            for stock in stocks:
                if is_cancel_requested(execute_query, job_id):
                    message = f"{title}已取消，已处理 {processed}/{len(stocks)}"
                    add_job_log(execute_query, job_id, message, level="warning")
                    finish_job(
                        execute_query,
                        job_id,
                        status="cancelled",
                        message=message,
                        result={"stocks_processed": processed, "records_updated": updated, "errors": errors[:20]},
                    )
                    return
                processed += 1
                code = stock["code"]
                stock_payload = {**payload, "code": code}
                add_job_log(execute_query, job_id, f"开始更新 {code}", stock_code=code)
                update_job(
                    execute_query,
                    job_id,
                    progress_current=processed - 1,
                    progress_total=len(stocks),
                    message=f"正在更新 {code}",
                    result={"stocks_processed": processed - 1, "records_updated": updated, "errors": errors[:20]},
                )
                try:
                    with app.test_request_context(endpoint_path, method="POST", json=stock_payload):
                        result = response_payload(endpoint_func())
                    if result.get("records_updated") is not None:
                        updated += int(result.get("records_updated") or 0)
                    elif result.get("saved_count") is not None:
                        updated += int(result.get("saved_count") or 0)
                    if result.get("errors"):
                        errors.extend(f"{code}: {err}" for err in result.get("errors")[:5])
                    if result.get("success") is False:
                        errors.append(f"{code}: {result.get('error') or result.get('message') or '更新失败'}")
                    add_job_log(
                        execute_query,
                        job_id,
                        f"{code} 更新完成",
                        stock_code=code,
                        detail={"records_updated": result.get("records_updated") or result.get("saved_count") or 0, "errors": result.get("errors") or []},
                    )
                except Exception as exc:
                    errors.append(f"{code}: {exc}")
                    add_job_log(execute_query, job_id, f"{code} 更新失败: {exc}", level="error", stock_code=code)
                update_job(
                    execute_query,
                    job_id,
                    progress_current=processed,
                    progress_total=len(stocks),
                    message=f"已更新 {processed}/{len(stocks)}",
                    result={"stocks_processed": processed, "records_updated": updated, "errors": errors[:20]},
                )
            status = "done" if not errors else "partial"
            message = f"{title}完成" if not errors else f"{title}部分完成，失败 {len(errors)} 项"
            add_job_log(execute_query, job_id, message, level="info" if status == "done" else "warning")
            finish_job(
                execute_query,
                job_id,
                status=status,
                message=message,
                result={"stocks_processed": processed, "records_updated": updated, "errors": errors[:20]},
            )
            if on_finish and updated > 0:
                on_finish({
                    "job_id": job_id,
                    "job_type": job_type,
                    "status": status,
                    "stocks_processed": processed,
                    "records_updated": updated,
                    "errors": errors[:20],
                })
        except Exception:
            add_job_log(execute_query, job_id, f"{title}失败", level="error", detail={"traceback": traceback.format_exc()})
            fail_job(execute_query, job_id, traceback.format_exc(), message=f"{title}失败")

    threading.Thread(target=runner, daemon=True).start()
    return {
        "success": True,
        "started": True,
        "background": True,
        "job_id": job_id,
        "job_type": job_type,
        "stocks_processed": 0,
        "stocks_total": len(stocks),
        "message": f"{title}已转入后台任务",
    }
