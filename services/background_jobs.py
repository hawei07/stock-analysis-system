"""Persistent background job helpers."""

import json
import threading
import traceback
from datetime import datetime


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
            result_json JSON NULL,
            error TEXT NULL,
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


def create_job(get_connection, execute_query, job_type, title=None, stock_code=None, progress_total=0, message=None):
    ensure_background_jobs_table(execute_query)
    conn = get_connection()
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """INSERT INTO background_jobs
               (job_type, status, stock_code, title, progress_total, message)
               VALUES (%s, 'queued', %s, %s, %s, %s)""",
            (job_type, stock_code, title, int(progress_total or 0), message),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        if cursor:
            cursor.close()
        conn.close()


def start_job(execute_query, job_id, message=None):
    execute_query(
        """UPDATE background_jobs
           SET status='running', started_at=COALESCE(started_at, %s), message=COALESCE(%s, message), error=NULL
           WHERE id=%s""",
        (_now(), message, job_id),
        fetch=False,
    )


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
    execute_query(
        """UPDATE background_jobs
           SET status=%s, message=COALESCE(%s, message), result_json=COALESCE(%s, result_json),
               finished_at=%s, progress_current=GREATEST(progress_current, progress_total)
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
        "result": _json_loads(row.get("result_json")),
        "error": row.get("error"),
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
