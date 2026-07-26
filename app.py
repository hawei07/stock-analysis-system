"""股票分析系统 - Web 服务"""

from flask import Flask, jsonify, request, render_template, send_from_directory
import sys
import re
import time
import requests
import json
import os
import shutil
import subprocess
import tempfile
import threading
import base64
import uuid
import html as html_lib
from datetime import datetime
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _read_local_settings():
    path = os.path.join(APP_DIR, "local_settings.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


LOCAL_SETTINGS = _read_local_settings()


def _setting(name, env_name, default=None):
    value = os.environ.get(env_name)
    if value not in (None, ""):
        return value
    value = LOCAL_SETTINGS.get(name)
    return default if value in (None, "") else value


from models import Stock
from db import execute_query, execute_update
from config import DB_CONFIG
from config_manager import get_all_config, set_config, get_deepseek_api_key
from munger import get_chat_history, chat_send, clear_chat_history, delete_chat_msg
from migrations import run_migrations, migration_status
from services.cloud_backup_service import (
    CLOUD_BACKUP_RETAIN_COUNT,
    auto_backup_delay_for_reasons,
    backup_file_groups,
    validate_sql_backup_file,
)

app = Flask(__name__)

CLOUD_SYNC_DIR = _setting("cloud_sync_dir", "STOCK_CLOUD_SYNC_DIR", r"D:\stock-cloud-sync")
MYSQL_BIN_DIR = _setting("mysql_bin_dir", "MYSQL_BIN_DIR", "")
APP_PORT = int(_setting("app_port", "STOCK_APP_PORT", 5002))
CLOUD_LATEST_SQL = "stock_analysis_latest.sql"
CLOUD_STATE_JSON = "sync_state.json"
LOCAL_CLOUD_STATE_JSON = os.path.join(APP_DIR, "data", "cloud_sync_state.json")
AUTO_CLOUD_BACKUP_DELAY_SECONDS = int(_setting("auto_cloud_backup_delay_seconds", "STOCK_AUTO_CLOUD_BACKUP_DELAY_SECONDS", 180))
_auto_backup_lock = threading.Lock()
_auto_backup_timer = None
_auto_backup_reasons = set()
_auto_backup_running = False
_auto_backup_scheduled_at = None
_auto_backup_due_at = None
_auto_backup_last_result = {
    "status": "idle",
    "message": "尚未执行自动云备份",
    "updated_at": None,
}

_db_overrides = {
    "host": _setting("db_host", "STOCK_DB_HOST"),
    "port": _setting("db_port", "STOCK_DB_PORT"),
    "user": _setting("db_user", "STOCK_DB_USER"),
    "password": _setting("db_password", "STOCK_DB_PASSWORD"),
    "database": _setting("db_name", "STOCK_DB_NAME"),
}
for _key, _value in _db_overrides.items():
    if _value not in (None, ""):
        DB_CONFIG[_key] = int(_value) if _key == "port" else _value


def _mysql_tool_path(name):
    exe = f"{name}.exe" if os.name == "nt" else name
    candidates = []
    if MYSQL_BIN_DIR:
        candidates.append(os.path.join(MYSQL_BIN_DIR, exe))

    resolved = shutil.which(exe)
    if resolved:
        candidates.append(resolved)

    if os.name == "nt":
        candidates.extend([
            os.path.join(r"E:\MySQL\bin", exe),
            os.path.join(r"D:\MySQL\bin", exe),
            os.path.join(r"D:\mysql\bin", exe),
            os.path.join(r"D:\dvptool\mysql\bin", exe),
            os.path.join(r"C:\Program Files\MySQL\MySQL Server 8.4\bin", exe),
            os.path.join(r"C:\Program Files\MySQL\MySQL Server 8.0\bin", exe),
        ])

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return exe


def _cloud_backup_dir():
    os.makedirs(CLOUD_SYNC_DIR, exist_ok=True)
    return CLOUD_SYNC_DIR


def _cloud_state_path():
    return os.path.join(_cloud_backup_dir(), CLOUD_STATE_JSON)


def _cloud_latest_path():
    return os.path.join(_cloud_backup_dir(), CLOUD_LATEST_SQL)


def _backup_file_payload(path):
    stat = os.stat(path)
    return {
        "name": os.path.basename(path),
        "path": path,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def _cloud_backup_files():
    backup_dir = _cloud_backup_dir()
    _cleanup_cloud_backup_files(backup_dir)
    files = []
    for name in os.listdir(backup_dir):
        path = os.path.join(backup_dir, name)
        if os.path.isfile(path) and name.lower().endswith(".sql"):
            files.append(_backup_file_payload(path))
    return sorted(files, key=lambda item: item["mtime"], reverse=True)


def _cleanup_cloud_backup_files(backup_dir=None, retain_count=CLOUD_BACKUP_RETAIN_COUNT):
    backup_dir = backup_dir or _cloud_backup_dir()
    groups = backup_file_groups()
    deleted = []

    for group_name, pattern in groups.items():
        files = []
        for name in os.listdir(backup_dir):
            if not pattern.match(name):
                continue
            path = os.path.join(backup_dir, name)
            if os.path.isfile(path):
                files.append((os.path.getmtime(path), name, path))

        files.sort(reverse=True)
        for _, name, path in files[retain_count:]:
            try:
                os.remove(path)
                deleted.append({"type": group_name, "name": name})
            except OSError:
                pass

    return deleted


def _resolve_backup_file(filename):
    if not filename or os.path.basename(filename) != filename or not filename.lower().endswith(".sql"):
        raise ValueError("Invalid backup filename")
    path = os.path.abspath(os.path.join(_cloud_backup_dir(), filename))
    backup_dir = os.path.abspath(_cloud_backup_dir())
    if os.path.commonpath([backup_dir, path]) != backup_dir or not os.path.exists(path):
        raise FileNotFoundError(filename)
    return path


def _read_local_cloud_state():
    if not os.path.exists(LOCAL_CLOUD_STATE_JSON):
        return {}
    try:
        with open(LOCAL_CLOUD_STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_local_cloud_state(payload):
    os.makedirs(os.path.dirname(LOCAL_CLOUD_STATE_JSON), exist_ok=True)
    with open(LOCAL_CLOUD_STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _cloud_latest_mtime():
    path = _cloud_latest_path()
    return os.path.getmtime(path) if os.path.exists(path) else None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mark_cloud_applied(action, extra=None):
    latest_mtime = _cloud_latest_mtime()
    state = {
        "action": action,
        "latest_path": _cloud_latest_path(),
        "latest_mtime": latest_mtime,
        "latest_mtime_iso": datetime.fromtimestamp(latest_mtime).isoformat(timespec="seconds") if latest_mtime else None,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "local_dirty": False,
        "dirty_since": None,
        "dirty_reasons": [],
    }
    if extra:
        state.update(extra)
    _write_local_cloud_state(state)
    return state


def _mark_local_dirty(reason):
    state = _read_local_cloud_state()
    reasons = set(state.get("dirty_reasons") or [])
    reasons.add(reason)
    state.update({
        "local_dirty": True,
        "dirty_since": state.get("dirty_since") or datetime.now().isoformat(timespec="seconds"),
        "dirty_reasons": sorted(reasons),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    _write_local_cloud_state(state)


def _read_cloud_state():
    path = _cloud_state_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_cloud_state(payload):
    with open(_cloud_state_path(), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _write_auto_backup_log(message):
    try:
        with open(os.path.join(APP_DIR, "auto_cloud_backup.log"), "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def _auto_backup_delay_for_reasons(reasons):
    return auto_backup_delay_for_reasons(reasons, AUTO_CLOUD_BACKUP_DELAY_SECONDS)


def _auto_backup_status_payload():
    now_ts = time.time()
    with _auto_backup_lock:
        pending = bool(_auto_backup_timer and _auto_backup_timer.is_alive())
        reasons = sorted(_auto_backup_reasons)
        due_at = _auto_backup_due_at
        scheduled_at = _auto_backup_scheduled_at
        running = _auto_backup_running
        last_result = dict(_auto_backup_last_result)
    return {
        "pending": pending,
        "running": running,
        "reasons": reasons,
        "scheduled_at": datetime.fromtimestamp(scheduled_at).isoformat(timespec="seconds") if scheduled_at else None,
        "due_at": datetime.fromtimestamp(due_at).isoformat(timespec="seconds") if due_at else None,
        "seconds_remaining": max(0, int(due_at - now_ts)) if pending and due_at else 0,
        "last_result": last_result,
    }


def _run_auto_cloud_backup():
    global _auto_backup_running, _auto_backup_timer, _auto_backup_scheduled_at, _auto_backup_due_at, _auto_backup_last_result
    with _auto_backup_lock:
        reasons = sorted(_auto_backup_reasons)
        _auto_backup_reasons.clear()
        _auto_backup_timer = None
        _auto_backup_scheduled_at = None
        _auto_backup_due_at = None
        _auto_backup_running = True
        _auto_backup_last_result = {
            "status": "running",
            "message": "自动云备份正在执行",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "reasons": reasons,
        }
    try:
        state = _dump_database()
        _auto_backup_last_result = {
            "status": "ok",
            "message": f"自动云备份完成: {state.get('latest_backup')}",
            "latest_backup": state.get("latest_backup"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "reasons": reasons,
        }
        _write_auto_backup_log(f"ok latest_backup={state.get('latest_backup')} reasons={','.join(reasons)}")
    except Exception as e:
        _auto_backup_last_result = {
            "status": "failed",
            "message": str(e),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "reasons": reasons,
        }
        _write_auto_backup_log(f"failed error={e} reasons={','.join(reasons)}")
    finally:
        with _auto_backup_lock:
            _auto_backup_running = False


def _schedule_auto_cloud_backup(reason):
    global _auto_backup_timer, _auto_backup_scheduled_at, _auto_backup_due_at, _auto_backup_last_result
    if AUTO_CLOUD_BACKUP_DELAY_SECONDS <= 0:
        return {"scheduled": False, "delay_seconds": 0}

    _mark_local_dirty(reason)
    with _auto_backup_lock:
        _auto_backup_reasons.add(reason)
        delay_seconds = _auto_backup_delay_for_reasons(_auto_backup_reasons)
        if _auto_backup_timer and _auto_backup_timer.is_alive():
            _auto_backup_timer.cancel()
        now_ts = time.time()
        _auto_backup_scheduled_at = now_ts
        _auto_backup_due_at = now_ts + delay_seconds
        _auto_backup_last_result = {
            "status": "pending",
            "message": f"自动云备份已安排，约 {delay_seconds} 秒后执行",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "reasons": sorted(_auto_backup_reasons),
        }
        _auto_backup_timer = threading.Timer(delay_seconds, _run_auto_cloud_backup)
        _auto_backup_timer.daemon = True
        _auto_backup_timer.start()
    return {"scheduled": True, "delay_seconds": delay_seconds}


def _cancel_pending_auto_cloud_backup():
    global _auto_backup_timer, _auto_backup_scheduled_at, _auto_backup_due_at
    with _auto_backup_lock:
        if _auto_backup_timer and _auto_backup_timer.is_alive():
            _auto_backup_timer.cancel()
        _auto_backup_timer = None
        _auto_backup_scheduled_at = None
        _auto_backup_due_at = None
        _auto_backup_reasons.clear()


AUTO_CLOUD_BACKUP_ENDPOINTS = {
    "api_add_stock": "stock-add",
    "api_update_stock": "stock-update",
    "api_delete_stock": "stock-delete",
    "api_stocks_reorder": "stocks-reorder",
    "api_graham_valuation_put": "graham-valuation-update",
    "api_update_dividends": "dividends-update",
    "api_update_financials": "financials-update",
    "api_update_balance_sheet": "balance-sheet-update",
    "api_update_segments": "segments-update",
    "api_update_income": "income-update",
    "api_update_cashflow": "cashflow-update",
    "api_portfolio_save_position": "portfolio-position-save",
    "api_portfolio_delete_position": "portfolio-position-delete",
    "api_portfolio_update_dividend": "portfolio-dividend-update",
    "api_portfolio_reset_dividend": "portfolio-dividend-reset",
    "api_portfolio_update_cash": "portfolio-cash-update",
    "api_portfolio_add_flow": "portfolio-flow-add",
    "api_portfolio_delete_flow": "portfolio-flow-delete",
    "api_portfolio_snapshot": "portfolio-snapshot",
    "api_config_put": "config-update",
}


@app.after_request
def schedule_auto_cloud_backup_after_change(response):
    if (
        request.method in ("POST", "PUT", "DELETE")
        and response.status_code < 400
        and request.endpoint in AUTO_CLOUD_BACKUP_ENDPOINTS
    ):
        _schedule_auto_cloud_backup(AUTO_CLOUD_BACKUP_ENDPOINTS[request.endpoint])
    return response


def _dump_database(prefix="stock_analysis", update_latest=True):
    backup_dir = _cloud_backup_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{prefix}_{ts}.sql"
    path = os.path.join(backup_dir, filename)
    cmd = [
        _mysql_tool_path("mysqldump"),
        "--host", DB_CONFIG.get("host", "127.0.0.1"),
        "--port", str(DB_CONFIG.get("port", 3306)),
        "--user", DB_CONFIG.get("user", "root"),
        f"--password={DB_CONFIG.get('password', '')}",
        "--default-character-set=utf8mb4",
        "--single-transaction",
        "--quick",
        "--routines",
        "--triggers",
        "--add-drop-table",
        DB_CONFIG.get("database", "stock_analysis"),
    ]
    with open(path, "wb") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, cwd=os.path.dirname(os.path.abspath(__file__)), timeout=120)
    if result.returncode != 0:
        try:
            os.remove(path)
        except OSError:
            pass
        raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "mysqldump failed")
    latest_path = _cloud_latest_path()
    if update_latest:
        shutil.copyfile(path, latest_path)
    deleted = _cleanup_cloud_backup_files(backup_dir)
    state = {
        "backup_dir": backup_dir,
        "latest_file": CLOUD_LATEST_SQL if update_latest else None,
        "latest_backup": filename,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "database": DB_CONFIG.get("database", "stock_analysis"),
        "size": os.path.getsize(latest_path) if update_latest and os.path.exists(latest_path) else os.path.getsize(path),
        "cleanup_deleted": deleted,
    }
    if update_latest:
        _write_cloud_state(state)
        _mark_cloud_applied("backup", {"latest_backup": filename})
    return state


def _restore_database(sql_path):
    if not os.path.exists(sql_path):
        raise FileNotFoundError(sql_path)
    _validate_sql_backup(sql_path)

    cmd = [
        _mysql_tool_path("mysql"),
        "--host", DB_CONFIG.get("host", "127.0.0.1"),
        "--port", str(DB_CONFIG.get("port", 3306)),
        "--user", DB_CONFIG.get("user", "root"),
        f"--password={DB_CONFIG.get('password', '')}",
        "--default-character-set=utf8mb4",
        DB_CONFIG.get("database", "stock_analysis"),
    ]
    prepared_path = None
    try:
        with open(sql_path, "r", encoding="utf-8") as f:
            sql = f.read()
        sql = re.sub(
            r",\s*\r?\n\s*CONSTRAINT\s+`[^`]+`\s+FOREIGN KEY\s+\([^)]+\)\s+REFERENCES\s+`[^`]+`\s+\([^)]+\)"
            r"(?:\s+ON\s+DELETE\s+\w+)?(?:\s+ON\s+UPDATE\s+\w+)?",
            "",
            sql,
            flags=re.IGNORECASE,
        )
        fd, prepared_path = tempfile.mkstemp(prefix="stock_restore_", suffix=".sql")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(sql)
        with open(prepared_path, "rb") as f:
            result = subprocess.run(cmd, stdin=f, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=os.path.dirname(os.path.abspath(__file__)), timeout=180)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", errors="ignore") or "mysql restore failed")
        validation = _validate_database_after_restore()
        if not validation["ok"]:
            raise RuntimeError("restore validation failed: " + "; ".join(validation["errors"]))
        return True
    finally:
        if prepared_path:
            try:
                os.remove(prepared_path)
            except OSError:
                pass


def _validate_sql_backup(sql_path):
    return validate_sql_backup_file(sql_path)


def _validate_database_after_restore():
    checks = [
        ("stocks", "SELECT COUNT(*) AS n FROM stocks"),
        ("custom_financials", "SELECT COUNT(*) AS n FROM custom_financials"),
        ("portfolio_positions", "SELECT COUNT(*) AS n FROM portfolio_positions"),
    ]
    errors = []
    counts = {}
    for name, sql in checks:
        try:
            rows = execute_query(sql)
            counts[name] = int(rows[0]["n"]) if rows else 0
        except Exception as e:
            errors.append(f"{name}: {e}")
    return {"ok": not errors, "errors": errors, "counts": counts}


# ==================== 便利贴 JSON 文件存储 ====================

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
JSON_PATH = os.path.join(DATA_DIR, 'sticky_notes.json')
IMAGES_DIR = os.path.join(DATA_DIR, 'images')
_json_lock = threading.Lock()


def _load_notes():
    """从 JSON 文件加载所有便利贴"""
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(JSON_PATH):
        return []
    try:
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            return json.loads(content) if content else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_notes(notes):
    """保存便利贴到 JSON 文件（线程安全）"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with _json_lock:
        with open(JSON_PATH, 'w', encoding='utf-8') as f:
            json.dump(notes, f, ensure_ascii=False, indent=2)


def _extract_images(content, note_id):
    """提取 content 中的 base64 图片到文件，替换为文件路径"""
    os.makedirs(IMAGES_DIR, exist_ok=True)

    def replace_base64(match):
        data_uri = match.group(0)
        try:
            header, b64data = data_uri.split(',', 1)
        except ValueError:
            return data_uri
        if 'image/png' in header:
            ext = 'png'
        elif 'image/jpeg' in header or 'image/jpg' in header:
            ext = 'jpg'
        elif 'image/gif' in header:
            ext = 'gif'
        elif 'image/webp' in header:
            ext = 'webp'
        else:
            ext = 'png'
        filename = f'{note_id}_{uuid.uuid4().hex[:8]}.{ext}'
        filepath = os.path.join(IMAGES_DIR, filename)
        try:
            with open(filepath, 'wb') as f:
                f.write(base64.b64decode(b64data))
        except Exception:
            return data_uri
        return f'/data/images/{filename}'

    return re.sub(r'data:image/[^;]+;base64,[a-zA-Z0-9+/=]+', replace_base64, content)


def _cleanup_images(note):
    """删除便利贴关联的图片文件"""
    paths = re.findall(r'/data/images/([^"\')\s]+)', note.get('content', ''))
    for fname in paths:
        fpath = os.path.join(IMAGES_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass


# ==================== 页面路由 ====================

@app.route("/")
@app.route("/stock/<code>")
def index(code=None):
    return render_template("index.html")


@app.route("/portfolio")
def portfolio_page():
    return render_template("portfolio.html")


# ==================== API 路由 ====================

def _market_from_code(code, market=None):
    code = str(code or "")
    if code.startswith(("6", "5", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    return market or "SZ"


def _quote_symbol(code, market=None):
    inferred_market = _market_from_code(code, market)
    if inferred_market == "SH":
        return f"sh{code}"
    if inferred_market == "BJ":
        return f"bj{code}"
    return f"sz{code}"


def _ensure_stock_order_column():
    try:
        rows = execute_query("SHOW COLUMNS FROM stocks LIKE 'display_order'")
        if not rows:
            execute_query(
                "ALTER TABLE stocks ADD COLUMN display_order INT DEFAULT NULL COMMENT '首页默认展示顺序'",
                fetch=False,
            )
        execute_query(
            "UPDATE stocks SET display_order = id WHERE display_order IS NULL",
            fetch=False,
        )
    except Exception:
        pass


def _ensure_graham_valuation_table():
    execute_query(
        """CREATE TABLE IF NOT EXISTS graham_valuations (
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            growth_rate DECIMAL(10,4) NULL,
            payout_ratio DECIMAL(10,4) NULL,
            risk_free_rate DECIMAL(10,4) NULL,
            expected_profit DECIMAL(18,4) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code),
            CONSTRAINT fk_graham_stock FOREIGN KEY (stock_code)
                REFERENCES stocks (code) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )


def _latest_total_shares(codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    try:
        rows = execute_query(
            f"""SELECT stock_code, total_shares
                FROM (
                  SELECT stock_code, total_shares,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM custom_financials
                  WHERE stock_code IN ({placeholders}) AND total_shares IS NOT NULL AND total_shares > 0
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        return {r["stock_code"]: float(r["total_shares"]) for r in rows}
    except Exception:
        return {}


def _graham_defaults(codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    defaults = {code: {
        "growth_rate": 0.0,
        "payout_ratio": None,
        "risk_free_rate": 5.0,
        "expected_profit": None,
        "total_shares": None,
    } for code in codes}

    try:
        rows = execute_query(
            f"""SELECT stock_code, AVG(ratio) AS avg_payout_ratio
                FROM (
                  SELECT stock_code,
                         dividend_amount / NULLIF(net_profit, 0) * 100 AS ratio,
                         ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY fiscal_year DESC) AS rn
                  FROM dividends
                  WHERE stock_code IN ({placeholders})
                    AND dividend_amount IS NOT NULL
                    AND net_profit IS NOT NULL
                    AND net_profit > 0
                ) t
                WHERE rn <= 3
                GROUP BY stock_code""",
            tuple(codes),
        )
        for r in rows:
            defaults[r["stock_code"]]["payout_ratio"] = (
                round(float(r["avg_payout_ratio"]), 2)
                if r["avg_payout_ratio"] is not None else None
            )
    except Exception:
        pass

    try:
        rows = execute_query(
            f"""SELECT stock_code, parent_profit
                FROM (
                  SELECT stock_code, parent_profit,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY
                             CASE WHEN report_period='FY' THEN 0 ELSE 1 END,
                             fiscal_year DESC,
                             FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM custom_financials
                  WHERE stock_code IN ({placeholders})
                    AND parent_profit IS NOT NULL
                    AND parent_profit > 0
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        for r in rows:
            defaults[r["stock_code"]]["expected_profit"] = round(float(r["parent_profit"]), 2)
    except Exception:
        pass

    shares = _latest_total_shares(codes)
    for code, value in shares.items():
        defaults.setdefault(code, {})["total_shares"] = value
    return defaults


def _graham_custom_params(codes):
    if not codes:
        return {}
    _ensure_graham_valuation_table()
    placeholders = ",".join(["%s"] * len(codes))
    try:
        rows = execute_query(
            f"""SELECT stock_code, growth_rate, payout_ratio, risk_free_rate, expected_profit
                FROM graham_valuations
                WHERE stock_code IN ({placeholders})""",
            tuple(codes),
        )
        return {
            r["stock_code"]: {
                "growth_rate": float(r["growth_rate"]) if r["growth_rate"] is not None else None,
                "payout_ratio": float(r["payout_ratio"]) if r["payout_ratio"] is not None else None,
                "risk_free_rate": float(r["risk_free_rate"]) if r["risk_free_rate"] is not None else None,
                "expected_profit": float(r["expected_profit"]) if r["expected_profit"] is not None else None,
            }
            for r in rows
        }
    except Exception:
        return {}


def _graham_payload(code):
    defaults = _graham_defaults([code]).get(code, {})
    custom = _graham_custom_params([code]).get(code, {})
    growth_rate = custom.get("growth_rate")
    payout_ratio = custom.get("payout_ratio")
    risk_free_rate = custom.get("risk_free_rate")
    expected_profit = custom.get("expected_profit")
    params = {
        "growth_rate": growth_rate if growth_rate is not None else defaults.get("growth_rate"),
        "payout_ratio": payout_ratio if payout_ratio is not None else defaults.get("payout_ratio"),
        "risk_free_rate": risk_free_rate if risk_free_rate is not None else defaults.get("risk_free_rate"),
        "expected_profit": expected_profit if expected_profit is not None else defaults.get("expected_profit"),
    }
    total_shares = defaults.get("total_shares")
    fair_valuation = None
    fair_price = None
    if (
        params["payout_ratio"] is not None
        and params["risk_free_rate"] is not None
        and params["risk_free_rate"] > 0
    ):
        fair_valuation = round(params["payout_ratio"] / params["risk_free_rate"] + (params["growth_rate"] or 0), 2)
    if fair_valuation is not None and params["expected_profit"] is not None and total_shares:
        fair_price = round(fair_valuation * params["expected_profit"] / total_shares, 2)
    return {
        "defaults": defaults,
        "custom": custom,
        "params": params,
        "total_shares": total_shares,
        "fair_valuation": fair_valuation,
        "fair_price": fair_price,
    }


def _fetch_realtime_prices(stocks):
    symbols = [_quote_symbol(s["code"], s.get("market")) for s in stocks]
    if not symbols:
        return {}
    prices = {}
    try:
        resp = requests.get(
            "https://qt.gtimg.cn/q=" + ",".join(symbols),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        resp.encoding = "gbk"
        for line in resp.text.split(";"):
            if "=" not in line:
                continue
            parts = line.split('"')
            if len(parts) < 2:
                continue
            fields = parts[1].split("~")
            if len(fields) >= 4:
                code = fields[2]
                try:
                    prices[code] = float(fields[3])
                except (TypeError, ValueError):
                    pass
    except Exception:
        pass
    return prices


def _fetch_ytd_return(code, market, current_price=None):
    try:
        year = datetime.now().year
        symbol = _quote_symbol(code, market)
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{year-1}-12-01,,360,qfq"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        data = resp.json()
        stock_data = (data.get("data") or {}).get(symbol, {})
        rows = stock_data.get("qfqday") or stock_data.get("day") or []
        if not rows:
            return None

        baseline_close = None
        for row in rows:
            if row[0] < f"{year}-01-01":
                baseline_close = float(row[2])
            else:
                break
        if baseline_close is None:
            baseline_close = float(rows[0][1])

        latest_close = current_price if current_price and current_price > 0 else float(rows[-1][2])
        if baseline_close <= 0:
            return None
        return round((latest_close / baseline_close - 1) * 100, 2)
    except Exception:
        return None


def _enrich_stock_list_metrics(stocks):
    if not stocks:
        return stocks
    codes = [s["code"] for s in stocks]
    placeholders = ",".join(["%s"] * len(codes))
    prices = _fetch_realtime_prices(stocks)

    latest_shares = _latest_total_shares(codes)
    graham_defaults = _graham_defaults(codes)
    graham_custom = _graham_custom_params(codes)

    latest_equity = {}
    try:
        rows = execute_query(
            f"""SELECT stock_code, parent_equity, goodwill
                FROM (
                  SELECT stock_code, parent_equity, goodwill,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM balance_sheets
                  WHERE stock_code IN ({placeholders}) AND parent_equity IS NOT NULL
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        latest_equity = {
            r["stock_code"]: (
                float(r["parent_equity"]),
                float(r["goodwill"]) if r["goodwill"] is not None else 0.0,
            )
            for r in rows
        }
    except Exception:
        latest_equity = {}

    for s in stocks:
        code = s["code"]
        price = prices.get(code)
        s["price"] = round(price, 2) if price is not None else None
        total_shares = latest_shares.get(code)
        defaults = graham_defaults.get(code, {})
        custom = graham_custom.get(code, {})
        params = {
            "growth_rate": custom.get("growth_rate") if custom.get("growth_rate") is not None else defaults.get("growth_rate"),
            "payout_ratio": custom.get("payout_ratio") if custom.get("payout_ratio") is not None else defaults.get("payout_ratio"),
            "risk_free_rate": custom.get("risk_free_rate") if custom.get("risk_free_rate") is not None else defaults.get("risk_free_rate"),
            "expected_profit": custom.get("expected_profit") if custom.get("expected_profit") is not None else defaults.get("expected_profit"),
        }
        fair_valuation = None
        fair_price = None
        if params["payout_ratio"] is not None and params["risk_free_rate"] is not None and params["risk_free_rate"] > 0:
            fair_valuation = round(params["payout_ratio"] / params["risk_free_rate"] + (params["growth_rate"] or 0), 2)
        if fair_valuation is not None and params["expected_profit"] is not None and total_shares:
            fair_price = round(fair_valuation * params["expected_profit"] / total_shares, 2)
        graham = {
            "defaults": defaults,
            "custom": custom,
            "params": params,
            "total_shares": total_shares,
            "fair_valuation": fair_valuation,
            "fair_price": fair_price,
        }
        s["graham"] = graham
        s["reasonable_valuation"] = graham["fair_valuation"]
        s["reasonable_price"] = graham["fair_price"]
        s["reasonable_discount"] = (
            round((price / graham["fair_price"] - 1) * 100, 2)
            if price is not None and graham["fair_price"] and graham["fair_price"] > 0
            else None
        )
        equity = latest_equity.get(code)
        s["pb_ex_goodwill"] = None
        if price and total_shares and equity:
            parent_equity, goodwill = equity
            net_equity = parent_equity - goodwill
            if net_equity > 0:
                s["pb_ex_goodwill"] = round(price * total_shares / net_equity, 2)
        s["ytd_return"] = _fetch_ytd_return(code, s.get("market"), price)
    return stocks


def _ensure_portfolio_tables():
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_positions (
            id INT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            shares DECIMAL(18,4) NOT NULL DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_portfolio_stock (stock_code),
            CONSTRAINT fk_portfolio_stock FOREIGN KEY (stock_code)
                REFERENCES stocks (code) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_nav_snapshots (
            id INT NOT NULL AUTO_INCREMENT,
            snapshot_date DATE NOT NULL,
            total_market_value DECIMAL(18,2) NOT NULL DEFAULT 0,
            expected_dividend DECIMAL(18,2) NOT NULL DEFAULT 0,
            positions_json JSON NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_snapshot_date (snapshot_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_cash (
            id TINYINT NOT NULL PRIMARY KEY,
            amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        "INSERT IGNORE INTO portfolio_cash (id, amount) VALUES (1, 0)",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_cash_flows (
            id INT NOT NULL AUTO_INCREMENT,
            flow_date DATE NOT NULL,
            amount DECIMAL(18,2) NOT NULL,
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_flow_date (flow_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    try:
        rows = execute_query("SHOW COLUMNS FROM portfolio_positions LIKE 'custom_dividend_per_share'")
        if not rows:
            execute_query(
                "ALTER TABLE portfolio_positions ADD COLUMN custom_dividend_per_share DECIMAL(10,4) NULL AFTER shares",
                fetch=False,
            )
    except Exception:
        pass
    for column_name, column_def in (
        ("cash_amount", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER expected_dividend"),
        ("total_asset_value", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER cash_amount"),
    ):
        try:
            rows = execute_query(f"SHOW COLUMNS FROM portfolio_nav_snapshots LIKE '{column_name}'")
            if not rows:
                execute_query(
                    f"ALTER TABLE portfolio_nav_snapshots ADD COLUMN {column_name} {column_def}",
                    fetch=False,
                )
        except Exception:
            pass


def _portfolio_cash_amount():
    _ensure_portfolio_tables()
    rows = execute_query("SELECT amount FROM portfolio_cash WHERE id=1")
    return float(rows[0]["amount"]) if rows else 0.0


def _portfolio_flow_rows(limit=100):
    _ensure_portfolio_tables()
    return execute_query(
        """SELECT id, flow_date, amount, note, created_at
           FROM portfolio_cash_flows
           ORDER BY flow_date DESC, id DESC
           LIMIT %s""",
        (limit,),
    )


def _portfolio_flows_payload():
    return [
        {
            "id": r["id"],
            "flow_date": str(r["flow_date"]),
            "amount": round(float(r["amount"]), 2),
            "note": r.get("note") or "",
            "created_at": str(r["created_at"]) if r.get("created_at") else None,
        }
        for r in _portfolio_flow_rows()
    ]


def _latest_dividend_per_share(codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    rows = execute_query(
        f"""SELECT stock_code, dividend_per_share, fiscal_year
            FROM (
              SELECT stock_code, dividend_per_share, fiscal_year,
                     ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY fiscal_year DESC) AS rn
              FROM dividends
              WHERE stock_code IN ({placeholders}) AND dividend_per_share IS NOT NULL
            ) t
            WHERE rn=1
            ORDER BY stock_code, fiscal_year DESC""",
        tuple(codes),
    )
    result = {}
    for r in rows:
        code = r["stock_code"]
        item = result.setdefault(code, {})
        if "dividend_per_share" not in item:
            item["dividend_per_share"] = float(r["dividend_per_share"])
            item["fiscal_year"] = int(r["fiscal_year"])
    return result


def _resolve_portfolio_stock(identifier):
    ident = str(identifier or "").strip()
    if not ident:
        return None
    if re.fullmatch(r"\d{6}", ident):
        rows = execute_query(
            "SELECT code, name, market FROM stocks WHERE code=%s LIMIT 1",
            (ident,),
        )
        return rows[0] if rows else None

    rows = execute_query(
        "SELECT code, name, market FROM stocks WHERE name=%s LIMIT 1",
        (ident,),
    )
    if rows:
        return rows[0]

    rows = execute_query(
        """SELECT code, name, market
           FROM stocks
           WHERE code LIKE %s OR name LIKE %s
           ORDER BY CASE WHEN name LIKE %s THEN 0 ELSE 1 END, display_order IS NULL, display_order, id
           LIMIT 10""",
        (f"%{ident}%", f"%{ident}%", ident),
    )
    return rows[0] if rows else None


def _portfolio_current_state():
    _ensure_portfolio_tables()
    cash_amount = _portfolio_cash_amount()
    rows = execute_query(
        """SELECT p.id, p.stock_code, p.shares, p.custom_dividend_per_share,
                  s.name, s.market, s.industry
           FROM portfolio_positions p
           JOIN stocks s ON s.code = p.stock_code
           ORDER BY p.updated_at DESC, p.id DESC"""
    )
    positions = []
    if not rows:
        return {
            "positions": [],
            "summary": {
                "total_market_value": 0,
                "cash_amount": round(cash_amount, 2),
                "total_asset_value": round(cash_amount, 2),
                "cash_allocation_pct": 100.0 if cash_amount > 0 else 0,
                "expected_dividend": 0,
                "count": 0,
            },
        }

    stock_refs = [{"code": r["stock_code"], "market": r["market"]} for r in rows]
    prices = _fetch_realtime_prices(stock_refs)
    dividends = _latest_dividend_per_share([r["stock_code"] for r in rows])
    total_market_value = 0.0
    expected_dividend = 0.0

    for r in rows:
        code = r["stock_code"]
        shares = float(r["shares"])
        price = prices.get(code)
        div = dividends.get(code, {})
        custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
        dividend_per_share = custom_dividend if custom_dividend is not None else div.get("dividend_per_share")
        market_value = shares * price if price is not None else None
        dividend_amount = shares * dividend_per_share if dividend_per_share is not None else None
        if market_value is not None:
            total_market_value += market_value
        if dividend_amount is not None:
            expected_dividend += dividend_amount
        positions.append({
            "id": r["id"],
            "code": code,
            "name": r["name"],
            "market": r["market"],
            "industry": r.get("industry"),
            "shares": shares,
            "price": round(price, 2) if price is not None else None,
            "market_value": round(market_value, 2) if market_value is not None else None,
            "dividend_per_share": round(dividend_per_share, 4) if dividend_per_share is not None else None,
            "dividend_year": div.get("fiscal_year"),
            "auto_dividend_per_share": round(div.get("dividend_per_share"), 4) if div.get("dividend_per_share") is not None else None,
            "custom_dividend_per_share": round(custom_dividend, 4) if custom_dividend is not None else None,
            "dividend_source": "custom" if custom_dividend is not None else "auto",
            "expected_dividend": round(dividend_amount, 2) if dividend_amount is not None else None,
        })

    total_asset_value = total_market_value + cash_amount
    for p in positions:
        value = p.get("market_value")
        p["allocation_pct"] = round(value / total_asset_value * 100, 2) if value is not None and total_asset_value > 0 else None
    positions.sort(key=lambda p: p.get("allocation_pct") or 0, reverse=True)

    return {
        "positions": positions,
        "summary": {
            "total_market_value": round(total_market_value, 2),
            "cash_amount": round(cash_amount, 2),
            "total_asset_value": round(total_asset_value, 2),
            "cash_allocation_pct": round(cash_amount / total_asset_value * 100, 2) if total_asset_value > 0 else 0,
            "expected_dividend": round(expected_dividend, 2),
            "count": len(positions),
        },
    }


def _save_portfolio_snapshot():
    state = _portfolio_current_state()
    summary = state["summary"]
    execute_query(
        """INSERT INTO portfolio_nav_snapshots
           (snapshot_date, total_market_value, expected_dividend, cash_amount, total_asset_value, positions_json)
           VALUES (CURDATE(), %s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             total_market_value=VALUES(total_market_value),
             expected_dividend=VALUES(expected_dividend),
             cash_amount=VALUES(cash_amount),
             total_asset_value=VALUES(total_asset_value),
             positions_json=VALUES(positions_json),
             updated_at=CURRENT_TIMESTAMP""",
        (
            summary["total_market_value"],
            summary["expected_dividend"],
            summary["cash_amount"],
            summary["total_asset_value"],
            json.dumps(state["positions"], ensure_ascii=False),
        ),
        fetch=False,
    )
    return state


@app.route("/api/portfolio", methods=["GET"])
def api_portfolio_get():
    return jsonify(_portfolio_current_state())


@app.route("/api/portfolio/positions", methods=["POST"])
def api_portfolio_save_position():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    identifier = str(data.get("code", data.get("identifier", ""))).strip()
    shares = data.get("shares")
    try:
        shares = float(shares)
    except (TypeError, ValueError):
        return jsonify({"error": "股数必须是数字"}), 400
    if shares <= 0:
        return jsonify({"error": "股数必须大于 0"}), 400
    stock = _resolve_portfolio_stock(identifier)
    if not stock:
        return jsonify({"error": "未找到匹配的股票，请输入代码或更准确的名称"}), 404
    code = stock["code"]
    execute_query(
        """INSERT INTO portfolio_positions (stock_code, shares)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE shares=VALUES(shares), updated_at=CURRENT_TIMESTAMP""",
        (code, shares),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    state["resolved_stock"] = {"code": stock["code"], "name": stock["name"], "market": stock["market"]}
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/positions/<code>", methods=["DELETE"])
def api_portfolio_delete_position(code):
    _ensure_portfolio_tables()
    execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)
    return jsonify({"ok": True, **_save_portfolio_snapshot()})


@app.route("/api/portfolio/positions/<code>/dividend", methods=["PUT"])
def api_portfolio_update_dividend(code):
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    value = data.get("dividend_per_share")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return jsonify({"error": "每股分红必须是数字"}), 400
    if value < 0:
        return jsonify({"error": "每股分红不能小于 0"}), 400
    rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
    if not rows:
        return jsonify({"error": "持仓中没有这只股票"}), 404
    execute_query(
        "UPDATE portfolio_positions SET custom_dividend_per_share=%s WHERE stock_code=%s",
        (value, code),
        fetch=False,
    )
    return jsonify({"ok": True, **_save_portfolio_snapshot()})


@app.route("/api/portfolio/positions/<code>/dividend/reset", methods=["POST"])
def api_portfolio_reset_dividend(code):
    _ensure_portfolio_tables()
    position_rows = execute_query("SELECT id FROM portfolio_positions WHERE stock_code=%s", (code,))
    if not position_rows:
        return jsonify({"error": "持仓中没有这只股票"}), 404
    execute_query(
        "UPDATE portfolio_positions SET custom_dividend_per_share=NULL WHERE stock_code=%s",
        (code,),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    reset_row = next((p for p in state["positions"] if p["code"] == code), None)
    if reset_row:
        state["reset_to"] = {
            "fiscal_year": reset_row.get("dividend_year"),
            "dividend_per_share": reset_row.get("auto_dividend_per_share"),
        }
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/cash", methods=["PUT"])
def api_portfolio_update_cash():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    value = data.get("amount")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return jsonify({"error": "现金必须是数字"}), 400
    if value < 0:
        return jsonify({"error": "现金不能小于 0"}), 400
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (round(value, 2),),
        fetch=False,
    )
    return jsonify({"ok": True, **_save_portfolio_snapshot()})


@app.route("/api/portfolio/flows", methods=["GET"])
def api_portfolio_flows():
    return jsonify(_portfolio_flows_payload())


@app.route("/api/portfolio/flows", methods=["POST"])
def api_portfolio_add_flow():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    flow_date = str(data.get("flow_date") or datetime.now().date()).strip()
    try:
        datetime.strptime(flow_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "日期格式必须是 YYYY-MM-DD"}), 400
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return jsonify({"error": "资金金额必须是数字"}), 400
    if amount == 0:
        return jsonify({"error": "资金金额不能为 0"}), 400
    note = str(data.get("note") or "").strip()[:255]
    cash_amount = _portfolio_cash_amount()
    new_cash = cash_amount + amount
    if new_cash < 0:
        return jsonify({"error": "现金不足，无法记录这笔流出"}), 400
    execute_query(
        "INSERT INTO portfolio_cash_flows (flow_date, amount, note) VALUES (%s, %s, %s)",
        (flow_date, round(amount, 2), note),
        fetch=False,
    )
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (round(new_cash, 2),),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/flows/<int:flow_id>", methods=["DELETE"])
def api_portfolio_delete_flow(flow_id):
    _ensure_portfolio_tables()
    rows = execute_query("SELECT amount FROM portfolio_cash_flows WHERE id=%s", (flow_id,))
    if not rows:
        return jsonify({"error": "未找到这笔资金流水"}), 404
    amount = float(rows[0]["amount"])
    cash_amount = _portfolio_cash_amount()
    new_cash = cash_amount - amount
    if new_cash < 0:
        return jsonify({"error": "删除后现金会小于 0，无法删除"}), 400
    execute_query("DELETE FROM portfolio_cash_flows WHERE id=%s", (flow_id,), fetch=False)
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (round(new_cash, 2),),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/snapshot", methods=["POST"])
def api_portfolio_snapshot():
    return jsonify({"ok": True, **_save_portfolio_snapshot()})


@app.route("/api/portfolio/nav")
def api_portfolio_nav():
    _ensure_portfolio_tables()
    rows = execute_query(
        """SELECT snapshot_date, total_market_value, expected_dividend,
                  cash_amount, total_asset_value
           FROM portfolio_nav_snapshots
           ORDER BY snapshot_date ASC"""
    )
    flow_rows = execute_query(
        """SELECT flow_date, SUM(amount) AS net_flow
           FROM portfolio_cash_flows
           GROUP BY flow_date"""
    )
    flow_by_date = {str(r["flow_date"]): float(r["net_flow"] or 0) for r in flow_rows}
    nav_index = None
    prev_value = None
    result = []
    for r in rows:
        date_str = str(r["snapshot_date"])
        value = float(r.get("total_asset_value") or r["total_market_value"])
        net_flow = flow_by_date.get(date_str, 0.0)
        if nav_index is None:
            nav_index = 1.0 if value > 0 else None
        elif prev_value and prev_value > 0:
            adjusted_value = max(0.0, value - net_flow)
            nav_index = nav_index * (adjusted_value / prev_value)
        result.append({
            "date": date_str,
            "total_market_value": round(value, 2),
            "stock_market_value": round(float(r["total_market_value"]), 2),
            "cash_amount": round(float(r.get("cash_amount") or 0), 2),
            "total_asset_value": round(value, 2),
            "net_flow": round(net_flow, 2),
            "expected_dividend": round(float(r["expected_dividend"]), 2),
            "nav_index": round(nav_index, 4) if nav_index is not None else None,
        })
        prev_value = value
    return jsonify(result)


@app.route("/api/config", methods=["GET"])
def api_config_get():
    """获取系统配置（API key 掩码）"""
    return jsonify(get_all_config())


@app.route("/api/config", methods=["PUT"])
def api_config_put():
    """更新系统配置"""
    data = request.get_json(force=True)
    updated = []
    for k, v in data.items():
        set_config(k, str(v))
        updated.append(k)
    return jsonify({"ok": True, "updated": updated})


@app.route("/api/db/migrations")
def api_db_migrations():
    try:
        return jsonify(migration_status())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cloud-backup/status")
def api_cloud_backup_status():
    latest_path = _cloud_latest_path()
    state = _read_cloud_state()
    local_state = _read_local_cloud_state()
    latest_mtime = _cloud_latest_mtime()
    local_mtime = _to_float(local_state.get("latest_mtime"))
    cloud_newer = bool(latest_mtime and (local_mtime is None or latest_mtime > local_mtime + 1))
    local_dirty = bool(local_state.get("local_dirty"))
    return jsonify({
        "backup_dir": _cloud_backup_dir(),
        "latest_path": latest_path,
        "latest_exists": os.path.exists(latest_path),
        "latest_size": os.path.getsize(latest_path) if os.path.exists(latest_path) else 0,
        "latest_mtime": datetime.fromtimestamp(os.path.getmtime(latest_path)).isoformat(timespec="seconds") if os.path.exists(latest_path) else None,
        "cloud_newer": cloud_newer,
        "local_dirty": local_dirty,
        "possible_conflict": bool(cloud_newer and local_dirty),
        "auto_backup": _auto_backup_status_payload(),
        "state": state,
        "local_state": local_state,
    })


@app.route("/api/cloud-backup/auto-status")
def api_cloud_backup_auto_status():
    return jsonify(_auto_backup_status_payload())


@app.route("/api/cloud-backup/files")
def api_cloud_backup_files():
    try:
        return jsonify({
            "backup_dir": _cloud_backup_dir(),
            "files": _cloud_backup_files(),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cloud-backup/backup", methods=["POST"])
def api_cloud_backup_create():
    try:
        _cancel_pending_auto_cloud_backup()
        state = _dump_database()
        return jsonify({"ok": True, **state})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cloud-backup/restore-file", methods=["POST"])
def api_cloud_backup_restore_file():
    try:
        _cancel_pending_auto_cloud_backup()
        data = request.get_json(silent=True) or {}
        filename = data.get("filename", "")
        backup_path = _resolve_backup_file(filename)
        pre_restore_state = _dump_database(prefix="pre_restore", update_latest=False)
        _restore_database(backup_path)
        _mark_cloud_applied("restore-file", {"restored_from": backup_path})
        return jsonify({
            "ok": True,
            "restored_from": backup_path,
            "pre_restore_backup": pre_restore_state.get("latest_backup"),
        })
    except FileNotFoundError:
        return jsonify({"error": "Backup file not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/cloud-backup/restore", methods=["POST"])
def api_cloud_backup_restore():
    try:
        _cancel_pending_auto_cloud_backup()
        latest_path = _cloud_latest_path()
        if not os.path.exists(latest_path):
            return jsonify({"error": "云端 latest 备份不存在"}), 404
        pre_restore_state = _dump_database(prefix="pre_restore", update_latest=False)
        _restore_database(latest_path)
        _mark_cloud_applied("restore", {"restored_from": latest_path})
        return jsonify({
            "ok": True,
            "restored_from": latest_path,
            "pre_restore_backup": pre_restore_state.get("latest_backup"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stocks")
def api_stocks():
    _ensure_stock_order_column()
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 15, type=int)
    market = request.args.get("market", None)
    status = request.args.get("status", None)
    keyword = request.args.get("keyword", None)
    sort_by = request.args.get("sort_by", "").strip()
    sort_dir = request.args.get("sort_dir", "asc").lower()
    sort_fields = {"code", "name", "price", "pe_ttm", "pb_ex_goodwill", "dividend_yield", "ytd_return", "reasonable_valuation", "reasonable_price", "reasonable_discount"}

    if sort_by in sort_fields:
        all_result = Stock.get_all(
            page=1, page_size=10000,
            market=market or None,
            status=status or None,
            keyword=keyword or None,
        )
        rows = _enrich_stock_list_metrics(all_result.get("data") or [])
        reverse = sort_dir == "desc"

        def sort_value(row):
            value = row.get(sort_by)
            if sort_by in {"code", "name"}:
                return str(value or "")
            return float(value) if value is not None else 0

        rows.sort(key=sort_value, reverse=reverse)
        rows.sort(key=lambda row: row.get(sort_by) is None)
        total = len(rows)
        start = (page - 1) * page_size
        end = start + page_size
        return jsonify({
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "data": rows[start:end],
            "sort_by": sort_by,
            "sort_dir": sort_dir,
        })

    result = Stock.get_all(
        page=page, page_size=page_size,
        market=market or None,
        status=status or None,
        keyword=keyword or None,
    )
    result["data"] = _enrich_stock_list_metrics(result.get("data") or [])
    result["sort_by"] = ""
    result["sort_dir"] = ""
    return jsonify(result)


@app.route("/api/stock/<code>/graham-valuation", methods=["GET"])
def api_graham_valuation_get(code):
    return jsonify(_graham_payload(code))


@app.route("/api/stock/<code>/graham-valuation", methods=["PUT"])
def api_graham_valuation_put(code):
    _ensure_graham_valuation_table()
    data = request.get_json(force=True)

    def parse_optional_number(name):
        value = data.get(name)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(name)

    try:
        growth_rate = parse_optional_number("growth_rate")
        payout_ratio = parse_optional_number("payout_ratio")
        risk_free_rate = parse_optional_number("risk_free_rate")
        expected_profit = parse_optional_number("expected_profit")
    except ValueError as e:
        return jsonify({"error": f"{e.args[0]} 必须是数字"}), 400

    if payout_ratio is not None and payout_ratio < 0:
        return jsonify({"error": "分红比例不能小于 0"}), 400
    if risk_free_rate is not None and risk_free_rate <= 0:
        return jsonify({"error": "无风险利率必须大于 0"}), 400
    if expected_profit is not None and expected_profit < 0:
        return jsonify({"error": "当年预期利润不能小于 0"}), 400

    execute_query(
        """INSERT INTO graham_valuations
           (stock_code, growth_rate, payout_ratio, risk_free_rate, expected_profit)
           VALUES (%s, %s, %s, %s, %s)
           ON DUPLICATE KEY UPDATE
             growth_rate=VALUES(growth_rate),
             payout_ratio=VALUES(payout_ratio),
             risk_free_rate=VALUES(risk_free_rate),
             expected_profit=VALUES(expected_profit),
             updated_at=CURRENT_TIMESTAMP""",
        (code, growth_rate, payout_ratio, risk_free_rate, expected_profit),
        fetch=False,
    )
    return jsonify({"ok": True, **_graham_payload(code)})


@app.route("/api/stocks/reorder", methods=["POST"])
def api_stocks_reorder():
    _ensure_stock_order_column()
    data = request.get_json(force=True)
    codes = data.get("codes") or []
    if not codes:
        return jsonify({"error": "empty codes"}), 400
    for idx, code in enumerate(codes, start=1):
        execute_query(
            "UPDATE stocks SET display_order=%s WHERE code=%s",
            (idx, code),
            fetch=False,
        )
    return jsonify({"ok": True, "updated": len(codes)})


@app.route("/api/stock/<code>")
def api_stock_detail(code):
    stock = Stock.get_by_code(code)
    if stock:
        # 确保日期字段可json序列化
        if stock.get("list_date"):
            stock["list_date"] = str(stock["list_date"])
        stock["created_at"] = str(stock["created_at"]) if stock.get("created_at") else None
        stock["updated_at"] = str(stock["updated_at"]) if stock.get("updated_at") else None

        # 获取实时行情：股价、PE(TTM)、PB、市值
        realtime = {"price": None, "pe_ttm": None, "pb": None, "market_cap": None}
        try:
            url = f"https://qt.gtimg.cn/q={_quote_symbol(code, stock.get('market'))}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            resp.encoding = "gbk"
            text = resp.text
            if text.startswith("v_"):
                parts = text.split("~")
                if len(parts) >= 4:
                    price_str = parts[3].strip()
                    if price_str and price_str != "-":
                        realtime["price"] = float(price_str)
                if len(parts) >= 40:
                    pe_str = parts[39].strip()
                    if pe_str and pe_str != "-":
                        try:
                            realtime["pe_ttm"] = float(pe_str)
                        except ValueError:
                            pass
                if len(parts) >= 44:
                    pb_str = parts[43].strip()
                    if pb_str and pb_str != "-":
                        try:
                            realtime["pb"] = float(pb_str)
                        except ValueError:
                            pass
                if len(parts) >= 46:
                    cap_str = parts[45].strip()
                    if cap_str and cap_str != "-":
                        try:
                            # 腾讯行情 parts[45] 已是亿元单位
                            realtime["market_cap"] = round(float(cap_str), 2)
                        except ValueError:
                            pass
        except Exception:
            pass

        stock["realtime"] = realtime
        stock["dividend_yield"] = stock.get("dividend_yield")  # 已在 stocks 表中

        return jsonify(stock)
    return jsonify({"error": "未找到该股票"}), 404


@app.route("/api/stock-search")
def api_stock_search():
    """根据代码或名称模糊搜索股票（本地DB）"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify([])
    rows = execute_query(
        "SELECT code, name, market FROM stocks WHERE code LIKE %s OR name LIKE %s LIMIT 10",
        (f"%{keyword}%", f"%{keyword}%")
    )
    results = [{"code": r["code"], "name": r["name"], "market": r["market"]} for r in rows]
    # 本地有结果直接返回
    if results:
        return jsonify(results)
    # 本地无结果，尝试东方财富搜索
    try:
        url = "https://searchadapter.eastmoney.com/api/suggest/get?type=14&input=" + keyword
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        data = resp.json()
        ext = data.get("QuotationCodeTable", {}).get("Data", [])
        for r in ext[:8]:
            code = r.get("Code", "")
            name = r.get("Name", "")
            mkt = r.get("MktNum", "")
            market = {"0": "SZ", "1": "SH"}.get(str(mkt), "SH")
            if code and name:
                results.append({"code": code, "name": name, "market": market})
    except Exception:
        pass
    return jsonify(results)


@app.route("/api/stock-info/<code>")
def api_stock_info(code):
    """根据股票代码从东方财富获取名称和市场信息"""
    # 尝试上海和深圳两个市场
    markets_to_try = []
    if code.startswith(("6", "5", "9")):
        markets_to_try = [("1", "SH"), ("0", "SZ")]
    else:
        markets_to_try = [("0", "SZ"), ("1", "SH")]

    name = None
    market = None
    for sec_market, our_market in markets_to_try:
        try:
            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58,f300"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            if data.get("data") and data["data"].get("f58"):
                name = data["data"]["f58"]
                market = our_market
                break
        except Exception:
            continue

    if not name:
        return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

    return jsonify({"code": code, "name": name, "market": market})


@app.route("/api/stock", methods=["POST"])
def api_add_stock():
    data = request.get_json()
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "请输入股票代码"}), 400

    existing = Stock.get_by_code(code)
    if existing:
        return jsonify({"error": f"股票代码 {code} 已存在"}), 409

    # 如果没传名称或市场，自动从东方财富获取
    name = data.get("name", "").strip()
    market = data.get("market", "").strip()
    if not name or not market:
        markets_to_try = [("1", "SH"), ("0", "SZ")] if code.startswith(("6", "5", "9")) else [("0", "SZ"), ("1", "SH")]
        for sec_market, our_market in markets_to_try:
            try:
                url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                resp_data = resp.json()
                if resp_data.get("data") and resp_data["data"].get("f58"):
                    if not name:
                        name = resp_data["data"]["f58"]
                    if not market:
                        market = our_market
                    break
            except Exception:
                continue

        if not name:
            return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

    if market and market not in ("SH", "SZ", "BJ"):
        return jsonify({"error": "市场必须是 SH/SZ/BJ"}), 400

    try:
        Stock.add(
            code=code,
            name=name,
            market=market or "SH",
            industry=data.get("industry"),
            list_date=data.get("list_date"),
            status=data.get("status", "正常"),
        )
        return jsonify({"success": True, "message": f"添加成功: {name}({code})"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stock/<code>", methods=["PUT"])
def api_update_stock(code):
    data = request.get_json()
    if not data:
        return jsonify({"error": "无更新数据"}), 400
    try:
        cnt = Stock.update(code, **data)
        if cnt:
            return jsonify({"success": True, "message": "更新成功"})
        return jsonify({"error": "未找到该股票"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stock/<code>", methods=["DELETE"])
def api_delete_stock(code):
    try:
        cnt = Stock.delete(code)
        if cnt:
            return jsonify({"success": True, "message": "删除成功"})
        return jsonify({"error": "未找到该股票"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stats")
def api_stats():
    all_stocks = Stock.get_all(page=1, page_size=1000)
    data = all_stocks["data"]
    markets = {"SH": 0, "SZ": 0, "BJ": 0}
    industries = {}
    for s in data:
        markets[s["market"]] = markets.get(s["market"], 0) + 1
        ind = s.get("industry") or "其他"
        industries[ind] = industries.get(ind, 0) + 1
    return jsonify({
        "total": all_stocks["total"],
        "markets": markets,
        "industries": industries,
    })


# ==================== 分红 API ====================

@app.route("/api/stock/<code>/dividends")
def api_stock_dividends(code):
    start_year = request.args.get("start_year", type=int)
    end_year = request.args.get("end_year", type=int)
    sql = "SELECT fiscal_year, net_profit, dividend_amount, dividend_per_share, ex_date FROM dividends WHERE stock_code = %s"
    params = [code]
    if start_year is not None:
        sql += " AND fiscal_year >= %s"
        params.append(start_year)
    if end_year is not None:
        sql += " AND fiscal_year <= %s"
        params.append(end_year)
    sql += " ORDER BY fiscal_year"
    rows = execute_query(sql, tuple(params))
    result = []
    for r in rows:
        result.append({
            "fiscal_year": r["fiscal_year"],
            "net_profit": float(r["net_profit"]) if r["net_profit"] else 0,
            "dividend_amount": float(r["dividend_amount"]) if r["dividend_amount"] else 0,
            "dividend_per_share": float(r["dividend_per_share"]) if r["dividend_per_share"] else 0,
            "ex_date": str(r["ex_date"]) if r["ex_date"] else None,
        })
    return jsonify(result)


# ==================== 数据更新 API ====================

@app.route("/api/update-dividends", methods=["POST"])
def api_update_dividends():
    """从东方财富和新浪财经更新股票的分红和净利润数据
    mode: full=全量更新, incremental=增量更新(仅更新有缺失的年份)
    """
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = execute_query("SELECT code, name, market FROM stocks WHERE status='正常'")
        updated_count = 0
        errors = []

        # 增量模式：找出每只股票已有的分红年份
        existing_years = {}
        if mode == "incremental":
            all_divs = execute_query("SELECT stock_code, fiscal_year FROM dividends")
            for d in all_divs:
                key = d["stock_code"]
                if key not in existing_years:
                    existing_years[key] = set()
                existing_years[key].add(d["fiscal_year"])

        for s in stocks:
            code = s["code"]
            market = s.get("market", "SH")
            net_profits = {}
            total_share = 0

            # 1. 获取净利润
            try:
                url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                       "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                       f"&filter=(SECURITY_CODE=%22{code}%22)&pageSize=200")
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                data = resp.json()
                if data.get("success"):
                    for item in data["result"]["data"]:
                        if item.get("REPORT_TYPE") == "年报":
                            year = int(item["REPORT_DATE"][:4])
                            profit = item.get("PARENTNETPROFIT")
                            if profit and year not in net_profits:
                                net_profits[year] = round(profit / 1e8, 4)
                        if item.get("TOTAL_SHARE") and not total_share:
                            total_share = item["TOTAL_SHARE"]
            except Exception as e:
                errors.append(f"{code}: 净利润获取失败 - {str(e)}")
                continue

            # 增量模式：跳过已有数据的年份
            if mode == "incremental" and code in existing_years:
                net_profits = {y: v for y, v in net_profits.items() if y not in existing_years[code]}

            # 2. 获取分红方案（全量模式或增量有缺失数据时）
            yearly_dividends = {}
            yearly_dps = {}
            need_dividend_fetch = mode == "full" or len(net_profits) > 0
            if need_dividend_fetch and total_share > 0:
                try:
                    url2 = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml"
                    resp2 = requests.get(url2, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    resp2.encoding = 'gbk'
                    text = resp2.text
                    # 先匹配 tr 块，再提取字段（避免 .*?实施 过滤导致漏掉条目）
                    tr_blocks = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
                    for tr in tr_blocks:
                        dm = re.search(r'(\d{4}-\d{2}-\d{2})', tr)
                        if not dm or '实施' not in tr:
                            continue
                        date_str = dm.group(1)
                        nums = re.findall(r'>\s*([\d.]+)\s*<', tr)
                        if len(nums) < 3:
                            continue
                        cal_year = int(date_str[:4])
                        cal_month = int(date_str[5:7])
                        # 财年映射：<=7月发放的属于上一财年（年终分红），>=8月属于当年（中期分红）
                        fiscal_year = cal_year - 1 if cal_month <= 7 else cal_year
                        dividend_per_10 = float(nums[-1])
                        if dividend_per_10 > 0:
                            if fiscal_year not in yearly_dividends:
                                yearly_dividends[fiscal_year] = 0
                                yearly_dps[fiscal_year] = 0
                            yearly_dividends[fiscal_year] += dividend_per_10 * total_share / 10 / 1e8
                            yearly_dps[fiscal_year] += dividend_per_10 / 10
                except Exception as e:
                    errors.append(f"{code}: 分红获取失败 - {str(e)}")

            # 3. 更新分红数据库
            for year in net_profits:
                np_val = net_profits[year]
                da_val = yearly_dividends.get(year)
                if da_val is not None:
                    execute_query(
                        "INSERT INTO dividends (stock_code, fiscal_year, net_profit, dividend_amount, dividend_per_share) "
                        "VALUES (%s, %s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE net_profit=VALUES(net_profit), dividend_amount=VALUES(dividend_amount), dividend_per_share=VALUES(dividend_per_share)",
                        (code, year, np_val, da_val, yearly_dps.get(year)),
                        fetch=False
                    )
                    updated_count += 1

            # 4. 更新 PE TTM 和股息率（腾讯行情接口）
            try:
                url = f"https://qt.gtimg.cn/q={_quote_symbol(code, market)}"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                resp.encoding = 'gbk'
                text = resp.text
                if text.startswith('v_'):
                    parts = text.split('~')
                    if len(parts) >= 40:
                        pe_ttm = None
                        div_yield = None
                        pe_str = parts[39].strip()
                        if pe_str and pe_str != '' and pe_str != '-':
                            try:
                                pe_ttm = float(pe_str)
                            except:
                                pe_ttm = None
                        price_str = parts[3].strip()
                        if price_str and price_str != '' and price_str != '-':
                            try:
                                cur_price = float(price_str)
                                div_rows = execute_query(
                                    "SELECT dividend_per_share FROM dividends "
                                    "WHERE stock_code=%s AND dividend_per_share>0 ORDER BY fiscal_year DESC LIMIT 2",
                                    (code,)
                                )
                                if div_rows:
                                    dps = max(float(r["dividend_per_share"]) for r in div_rows)
                                    if dps > 0 and cur_price > 0:
                                        div_yield = round(dps / cur_price * 100, 2)
                            except:
                                div_yield = None
                        execute_query(
                            "UPDATE stocks SET pe_ttm=%s, dividend_yield=%s WHERE code=%s",
                            (pe_ttm, div_yield, code),
                            fetch=False
                        )
            except Exception as e:
                errors.append(f"{code}: PE/股息率更新失败 - {str(e)}")

            time.sleep(0.3)

        return jsonify({
            "success": True,
            "message": f"已更新 {updated_count} 条分红记录",
            "stocks_processed": len(stocks),
            "mode": mode,
            "errors": errors[:5] if errors else []
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ==================== 自定义财报 API ====================


def _ensure_financials_columns():
    """确保 custom_financials 包含新增字段（幂等）"""
    new_columns = [
        ("basic_eps", "DECIMAL(18,4) DEFAULT NULL COMMENT '归母普通股每股收益'"),
        ("debt_ratio", "DECIMAL(10,4) DEFAULT NULL COMMENT '资产负债率(%)'"),
        ("short_borrow", "DECIMAL(18,4) DEFAULT NULL COMMENT '短期借款(亿)'"),
        ("noncurrent_liab_due1y", "DECIMAL(18,4) DEFAULT NULL COMMENT '一年内到期非流动负债(亿)'"),
        ("long_borrow", "DECIMAL(18,4) DEFAULT NULL COMMENT '长期借款(亿)'"),
        ("bonds_payable", "DECIMAL(18,4) DEFAULT NULL COMMENT '应付债券(亿)'"),
        ("interest_bearing_debt_ratio", "DECIMAL(10,4) DEFAULT NULL COMMENT '有息负债率(%)'"),
    ]
    for col_name, col_def in new_columns:
        try:
            execute_query(
                f"ALTER TABLE custom_financials ADD COLUMN {col_name} {col_def}",
                fetch=False,
            )
        except Exception:
            pass  # 列已存在则忽略


@app.route("/api/update-financials", methods=["POST"])
def api_update_financials():
    """从东方财富拉取财务数据并存入 custom_financials 表
    mode: full=全量拉取, incremental=增量拉取(仅更新无数据的记录)
    支持年报+季报（全部报告类型）。
    """
    mode = "full"
    if request.is_json:
        mode = request.get_json(silent=True).get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    # 确保新字段列存在
    _ensure_financials_columns()

    # REPORT_TYPE → report_period
    period_map = {"年报": "FY", "三季报": "Q3", "中报": "Q2", "一季报": "Q1"}

    try:
        stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
        updated_count = 0
        stocks_processed = 0
        errors = []

        for s in stocks:
            code = s["code"]
            stocks_processed += 1
            try:
                url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                       "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                       f"&filter=(SECURITY_CODE=%22{code}%22)"
                       "&pageSize=200&sortColumns=REPORT_DATE&sortTypes=-1")
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                data = resp.json()
                if not data.get("success"):
                    errors.append(f"{code}: API返回失败")
                    continue

                records = data["result"]["data"]
                # 按 (fiscal_year, report_period) 分组，取 NOTICE_DATE 更晚的
                key_best = {}
                for item in records:
                    rd = item.get("REPORT_DATE", "")
                    rt = item.get("REPORT_TYPE", "")
                    period = period_map.get(rt)
                    if not rd or not period:
                        continue
                    year = int(rd[:4])
                    notice = item.get("NOTICE_DATE", "")
                    key = (year, period)
                    if key not in key_best or notice > key_best[key][0]:
                        key_best[key] = (notice, item)

                # 增量模式：查询已有 (year, period) 组合
                existing_keys = set()
                if mode == "incremental":
                    existing = execute_query(
                        "SELECT fiscal_year, report_period FROM custom_financials WHERE stock_code=%s", (code,)
                    )
                    existing_keys = {(r["fiscal_year"], r["report_period"]) for r in existing}

                for (year, period), (_, item) in key_best.items():
                    if mode == "incremental" and (year, period) in existing_keys:
                        continue

                    total_share = item.get("TOTAL_SHARE")
                    total_shares_val = round(total_share / 1e8, 4) if total_share else None

                    basic_eps = item.get("EPSJB")
                    basic_eps_val = round(float(basic_eps), 4) if basic_eps else None

                    ta_raw = item.get("TOTAL_ASSETS_PK", 0)
                    te_raw = item.get("TOTAL_EQUITY_PK", 0)
                    ta_val = round(ta_raw / 1e8, 4) if ta_raw else None
                    te_val = round(te_raw / 1e8, 4) if te_raw else None
                    debt_ratio_val = round((ta_raw - te_raw) / ta_raw * 100, 2) if (ta_raw and te_raw and ta_raw > 0) else None

                    idr_raw = item.get("INTEREST_DEBT_RATIO")
                    interest_bearing_debt_ratio_val = round(float(idr_raw), 4) if idr_raw else None

                    short_borrow_val = None
                    ncl_due1y_val = None
                    long_borrow_val = None
                    bonds_val = None

                    execute_query(
                        """INSERT INTO custom_financials
                        (stock_code, fiscal_year, report_period, total_revenue, operate_profit, parent_profit,
                         deducted_profit, operate_cashflow, roe, deducted_roe, roic,
                         total_assets, total_equity, total_shares, audit_opinion,
                         basic_eps, debt_ratio,
                         short_borrow, noncurrent_liab_due1y, long_borrow, bonds_payable,
                         interest_bearing_debt_ratio)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                         total_revenue=VALUES(total_revenue), operate_profit=VALUES(operate_profit),
                         parent_profit=VALUES(parent_profit), deducted_profit=VALUES(deducted_profit),
                         operate_cashflow=VALUES(operate_cashflow), roe=VALUES(roe),
                         deducted_roe=VALUES(deducted_roe), roic=VALUES(roic),
                         total_assets=VALUES(total_assets), total_equity=VALUES(total_equity),
                         total_shares=VALUES(total_shares), audit_opinion=VALUES(audit_opinion),
                         basic_eps=VALUES(basic_eps), debt_ratio=VALUES(debt_ratio),
                         short_borrow=VALUES(short_borrow), noncurrent_liab_due1y=VALUES(noncurrent_liab_due1y),
                         long_borrow=VALUES(long_borrow), bonds_payable=VALUES(bonds_payable),
                         interest_bearing_debt_ratio=VALUES(interest_bearing_debt_ratio)""",
                        (
                            code, year, period,
                            round(item["TOTALOPERATEREVE"] / 1e8, 4) if item.get("TOTALOPERATEREVE") else None,
                            round(item.get("OPERATE_PROFIT_PK", 0) / 1e8, 4) if item.get("OPERATE_PROFIT_PK") else None,
                            round(item["PARENTNETPROFIT"] / 1e8, 4) if item.get("PARENTNETPROFIT") else None,
                            round(item["KCFJCXSYJLR"] / 1e8, 4) if item.get("KCFJCXSYJLR") else None,
                            round(item.get("NETCASH_OPERATE_PK", 0) / 1e8, 4) if item.get("NETCASH_OPERATE_PK") else None,
                            round(item["ROEJQ"], 4) if item.get("ROEJQ") else None,
                            round(item["ROEKCJQ"], 4) if item.get("ROEKCJQ") else None,
                            round(item["ROIC"], 4) if item.get("ROIC") else None,
                            ta_val,
                            te_val,
                            total_shares_val,
                            None,
                            basic_eps_val,
                            debt_ratio_val,
                            short_borrow_val,
                            ncl_due1y_val,
                            long_borrow_val,
                            bonds_val,
                            interest_bearing_debt_ratio_val,
                        ),
                        fetch=False
                    )
                    updated_count += 1

            except Exception as e:
                errors.append(f"{code}: {str(e)}")

            time.sleep(0.3)

        return jsonify({
            "success": True,
            "stocks_processed": stocks_processed,
            "records_updated": updated_count,
            "mode": mode,
            "errors": errors[:5] if errors else [],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stock/<code>/financials")
def api_stock_financials(code):
    """查询指定股票的多年财务数据，含后端计算的派生指标。
    Query params:
      from_year, to_year: 年份范围
      period: FY(年报,默认) / Q1 / Q2 / Q3 / all(全部)
      view: cumulative(累计,默认) / single(单季度)
    """
    from_year = request.args.get("from_year", 2016, type=int)
    to_year = request.args.get("to_year", 2025, type=int)
    period = request.args.get("period", "FY")
    view = request.args.get("view", "cumulative")

    need_single = (view == "single" and period != "FY")
    query_period = None if need_single else (None if period == "all" else period)

    if query_period:
        where_period = "AND cf.report_period = %s"
        params = [code, query_period, from_year, to_year]
    else:
        where_period = ""
        params = [code, from_year, to_year]

    rows = execute_query(
        f"""SELECT cf.fiscal_year, cf.report_period, cf.total_revenue, cf.operate_profit, cf.parent_profit,
                  cf.deducted_profit, cf.operate_cashflow, cf.roe, cf.deducted_roe, cf.roic,
                  cf.total_assets, cf.total_equity, cf.total_shares,
                  cf.basic_eps, cf.debt_ratio,
                  cf.short_borrow, cf.noncurrent_liab_due1y, cf.long_borrow, cf.bonds_payable,
                  cf.interest_bearing_debt_ratio,
                  d.dividend_amount, d.dividend_per_share
           FROM custom_financials cf
           LEFT JOIN dividends d ON cf.stock_code = d.stock_code AND cf.fiscal_year = d.fiscal_year
           WHERE cf.stock_code = %s {where_period}
           AND cf.fiscal_year BETWEEN %s AND %s
           ORDER BY cf.fiscal_year DESC, FIELD(cf.report_period, 'FY','Q3','Q2','Q1') DESC""",
        tuple(params)
    )

    # 获取当前股价
    cur_price = None
    try:
        stock = execute_query("SELECT market FROM stocks WHERE code=%s", (code,))
        if stock:
            url = f"https://qt.gtimg.cn/q={_quote_symbol(code, stock[0].get('market'))}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            resp.encoding = "gbk"
            text = resp.text
            if text.startswith("v_"):
                parts = text.split("~")
                if len(parts) >= 4:
                    price_str = parts[3].strip()
                    if price_str and price_str not in ("", "-"):
                        cur_price = float(price_str)
    except Exception:
        pass

    def _build_item(r):
        rev = float(r["total_revenue"]) if r["total_revenue"] else 0
        op = float(r["operate_profit"]) if r["operate_profit"] else 0
        pp = float(r["parent_profit"]) if r["parent_profit"] else 0
        dp = float(r["deducted_profit"]) if r["deducted_profit"] else 0
        ocf = float(r["operate_cashflow"]) if r["operate_cashflow"] else 0
        roe_v = float(r["roe"]) if r["roe"] else None
        droe_v = float(r["deducted_roe"]) if r["deducted_roe"] else None
        roic_v = float(r["roic"]) if r["roic"] else None
        ta = float(r["total_assets"]) if r["total_assets"] else 0
        te = float(r["total_equity"]) if r["total_equity"] else 0
        ts = float(r["total_shares"]) if r["total_shares"] else 0
        basic_eps = float(r["basic_eps"]) if r.get("basic_eps") else None
        debt_ratio_raw = float(r["debt_ratio"]) if r.get("debt_ratio") else None
        debt_ratio = (
            debt_ratio_raw if debt_ratio_raw is not None
            else (round((ta - te) / ta * 100, 2) if ta > 0 else None)
        )
        short_borrow = float(r["short_borrow"]) if r.get("short_borrow") else None
        ncl_due1y = float(r["noncurrent_liab_due1y"]) if r.get("noncurrent_liab_due1y") else None
        long_borrow = float(r["long_borrow"]) if r.get("long_borrow") else None
        bonds_payable = float(r["bonds_payable"]) if r.get("bonds_payable") else None
        dividend_amount = float(r["dividend_amount"]) if r.get("dividend_amount") else None
        dividend_per_share = float(r["dividend_per_share"]) if r.get("dividend_per_share") else None
        core_profit_rate = round(op / rev * 100, 2) if rev else None
        net_profit_rate = round(pp / rev * 100, 2) if rev else None
        cashflow_to_profit = round(ocf / pp * 100, 2) if pp and pp > 0 else None
        dividend_payout_ratio = (
            round(dividend_amount / pp * 100, 2)
            if (dividend_amount is not None and pp and pp > 0) else None
        )
        interest_bearing_debt_ratio = (
            round(float(r["interest_bearing_debt_ratio"]), 2)
            if r.get("interest_bearing_debt_ratio") else None
        )
        dividend_yield_fin = (
            round(dividend_per_share / cur_price * 100, 2)
            if (dividend_per_share is not None and dividend_per_share > 0
                and cur_price and cur_price > 0) else None
        )
        return {
            "fiscal_year": r["fiscal_year"],
            "report_period": r.get("report_period", "FY"),
            "total_revenue": rev, "operate_profit": op, "parent_profit": pp,
            "deducted_profit": dp, "operate_cashflow": ocf,
            "roe": roe_v, "deducted_roe": droe_v, "roic": roic_v,
            "total_assets": ta, "total_equity": te, "total_shares": ts,
            "core_profit_rate": core_profit_rate, "net_profit_rate": net_profit_rate,
            "cashflow_to_profit": cashflow_to_profit,
            "basic_eps": basic_eps, "debt_ratio": debt_ratio,
            "dividend_amount": dividend_amount, "dividend_per_share": dividend_per_share,
            "dividend_payout_ratio": dividend_payout_ratio,
            "interest_bearing_debt_ratio": interest_bearing_debt_ratio,
            "dividend_yield_fin": dividend_yield_fin,
        }

    # 单季度模式：本期累计 - 上期累计
    if need_single:
        data_by_key = {}
        for r in rows:
            fy, rp = r["fiscal_year"], r.get("report_period", "FY")
            data_by_key[(fy, rp)] = _build_item(r)

        periods_order = ["Q1", "Q2", "Q3", "FY"]
        prev_map = {"Q1": None, "Q2": "Q1", "Q3": "Q2", "FY": "Q3"}
        flow_fields = ["total_revenue", "operate_profit", "parent_profit", "deducted_profit",
                       "operate_cashflow", "dividend_amount"]

        result = []
        for (fy, rp), item in sorted(data_by_key.items(), key=lambda x: (-x[0][0], periods_order.index(x[0][1]))):
            prev_key = (fy, prev_map[rp]) if prev_map[rp] else None
            prev_item = data_by_key.get(prev_key) if prev_key else None
            single = {"fiscal_year": fy, "report_period": rp}
            for k, v in item.items():
                if k in ("fiscal_year", "report_period"):
                    single[k] = v
                elif v is None:
                    single[k] = None
                elif k in flow_fields:
                    if prev_item is None or prev_item.get(k) is None:
                        single[k] = v if rp == "Q1" else None
                    else:
                        single[k] = round(v - prev_item[k], 4)
                else:
                    single[k] = v
            # 重新计算派生指标
            rev_s = single.get("total_revenue") or 0
            op_s = single.get("operate_profit") or 0
            pp_s = single.get("parent_profit") or 0
            ocf_s = single.get("operate_cashflow") or 0
            da_s = single.get("dividend_amount")
            single["core_profit_rate"] = round(op_s / rev_s * 100, 2) if rev_s else None
            single["net_profit_rate"] = round(pp_s / rev_s * 100, 2) if rev_s else None
            single["cashflow_to_profit"] = round(ocf_s / pp_s * 100, 2) if pp_s and pp_s > 0 else None
            single["dividend_payout_ratio"] = round(da_s / pp_s * 100, 2) if (da_s is not None and pp_s and pp_s > 0) else None
            result.append(single)
        # 过滤到请求的报告期
        if period != "all":
            result = [r for r in result if r["report_period"] == period]
    else:
        result = [_build_item(r) for r in rows]

    return jsonify(result)


# ==================== 资产负债表 API（数据源：新浪财经） ====================

# 新浪资产负债表 → 数据库字段映射 (中文行名 → DB column)
BS_ROW_MAP = [
    # 流动资产
    ("货币资金", "monetary_funds"),
    ("交易性金融资产", "trading_fin_assets"),
    ("应收票据", "notes_receivable"),
    ("应收账款", "accounts_receivable"),
    ("应收款项融资", "receivables_financing"),
    ("预付款项", "prepayment"),
    ("其他应收款", "other_receivables"),       # 匹配"其他应收款(合计)"
    ("存货", "inventory"),
    ("一年内到期的非流动资产", "noncurrent_assets_due1y"),
    ("其他流动资产", "other_current_assets"),
    ("流动资产合计", "total_current_assets"),
    # 非流动资产
    ("持有至到期投资", "held_to_maturity_invest"),
    ("长期股权投资", "longterm_equity_invest"),
    ("投资性房地产", "investment_property"),
    ("在建工程", "cip"),                       # 匹配"在建工程(合计)"
    ("固定资产", "fixed_assets"),             # 匹配"固定资产及清理(合计)"
    ("使用权资产", "right_of_use_assets"),
    ("无形资产", "intangible_assets"),
    ("开发支出", "development_expenditure"),
    ("商誉", "goodwill"),
    ("长期待摊费用", "longterm_prepaid_expense"),
    ("递延所得税资产", "deferred_tax_assets"),
    ("其他非流动资产", "other_noncurrent_assets"),
    ("非流动资产合计", "total_noncurrent_assets"),
    ("资产总计", "total_assets"),
    # 流动负债
    ("短期借款", "short_borrow"),
    ("应付票据", "notes_payable"),
    ("应付账款", "accounts_payable"),
    ("预收款项", "advance_receipts"),
    ("应付职工薪酬", "payroll_payable"),
    ("应交税费", "taxes_payable"),
    ("其他应付款", "other_payables"),         # 匹配"其他应付款(合计)"
    ("一年内到期的非流动负债", "noncurrent_liab_due1y"),
    ("其他流动负债", "other_current_liabilities"),
    ("流动负债合计", "total_current_liabilities"),
    # 非流动负债
    ("长期借款", "long_borrow"),
    ("应付债券", "bonds_payable"),
    ("租赁负债", "lease_liabilities"),
    ("递延所得税负债", "deferred_tax_liabilities"),
    ("非流动负债合计", "total_noncurrent_liabilities"),
    ("负债合计", "total_liabilities"),
    # 股东权益
    ("实收资本", "paid_in_capital"),          # 匹配"实收资本(或股本)"
    ("资本公积", "capital_reserve"),
    ("库存股", "treasury_stock"),             # 匹配"减：库存股"
    ("盈余公积", "surplus_reserve"),
    ("未分配利润", "retained_earnings"),
    ("归属于母公司股东权益合计", "parent_equity"),
    ("少数股东权益", "minority_interests"),
    ("所有者权益", "total_equity"),            # 匹配"所有者权益(或股东权益)合计"
]

# 所有 BS 字段列表（用于查询 + INSERT 构建）
BS_COLUMNS = [col for _, col in BS_ROW_MAP]


def _period_from_date(date_str):
    """根据日期返回报告期: 03-31→Q1, 06-30→Q2, 09-30→Q3, 12-31→FY"""
    month = int(date_str[5:7])
    day = int(date_str[8:10])
    if month == 3 and day == 31:
        return "Q1"
    elif month == 6 and day == 30:
        return "Q2"
    elif month == 9 and day == 30:
        return "Q3"
    elif month == 12 and day == 31:
        return "FY"
    return None


def _parse_sina_bs(html):
    """解析新浪资产负债表 HTML，提取各季度科目数据（万元→亿元）。
    返回 {(year, period): {col: val}} 字典，period ∈ {FY, Q1, Q2, Q3}。
    """
    import re as _re

    all_tables = _re.findall(r'<table[^>]*>(.*?)</table>', html, _re.DOTALL)
    all_data = {}  # (year, period) → {col: value}

    for table_html in all_tables:
        if '报表日期' not in table_html or '货币资金' not in table_html:
            continue

        rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, _re.DOTALL)

        # 在表头行中找所有日期列 → (col_idx, year, period, date_str)
        date_cols = []
        for r in rows:
            cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
            cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if any('报表日期' in c for c in cells):
                for idx, c in enumerate(cells):
                    m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', c)
                    if m:
                        year, date_str = int(m.group(1)), m.group(0)
                        period = _period_from_date(date_str)
                        if period:
                            date_cols.append((idx, year, period, date_str))
                break

        if not date_cols:
            continue

        # 解析每个日期列的数据
        for col_idx, col_year, period, date_str in date_cols:
            values = {}
            for r in rows:
                cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if not cells or len(cells) <= col_idx:
                    continue

                row_name = cells[0]
                raw_val = cells[col_idx]

                for pattern, col in BS_ROW_MAP:
                    if row_name.startswith(pattern) or (pattern == "库存股" and "库存股" in row_name):
                        if raw_val and raw_val not in ("--", "", "None"):
                            try:
                                values[col] = round(float(raw_val.replace(",", "")) / 10000, 4)
                            except ValueError:
                                pass
                        break

            if values:
                key = (col_year, period)
                # 同一年同一报告期，保留最新日期的数据
                existing_key = all_data.get(f"_latest_{col_year}_{period}", "")
                if key not in all_data or date_str > existing_key:
                    all_data[key] = values
                    all_data[f"_latest_{col_year}_{period}"] = date_str

    # 清理辅助键
    return {k: v for k, v in all_data.items() if isinstance(k, tuple)}


@app.route("/api/update-balance-sheet", methods=["POST"])
def api_update_balance_sheet():
    """从新浪财经拉取资产负债表数据并存入 balance_sheets 表"""
    mode = "full"
    if request.is_json:
        mode = request.get_json(silent=True).get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
        updated_count = 0
        errors = []

        for s in stocks:
            code = s["code"]
            try:
                url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_BalanceSheet/stockid/{code}/ctrl/part/displaytype/0.phtml"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                resp.encoding = "gbk"

                # 增量模式：查询已有 (year, period) 组合
                existing_keys = set()
                if mode == "incremental":
                    existing = execute_query(
                        "SELECT fiscal_year, report_period FROM balance_sheets WHERE stock_code=%s", (code,)
                    )
                    existing_keys = {(r["fiscal_year"], r["report_period"]) for r in existing}

                # 解析所有季度数据
                all_data = _parse_sina_bs(resp.text)

                for (year, period), values in sorted(all_data.items()):
                    if mode == "incremental" and (year, period) in existing_keys:
                        continue

                    columns = BS_COLUMNS
                    placeholders = ", ".join(["%s"] * len(columns))
                    col_names = ", ".join(columns)
                    update_clause = ", ".join([f"{c}=VALUES({c})" for c in columns])

                    sql = (
                        f"INSERT INTO balance_sheets (stock_code, fiscal_year, report_period, {col_names}) "
                        f"VALUES (%s, %s, %s, {placeholders}) "
                        f"ON DUPLICATE KEY UPDATE {update_clause}"
                    )
                    params = [code, year, period] + [values.get(c) for c in columns]
                    execute_query(sql, tuple(params), fetch=False)
                    updated_count += 1

            except Exception as e:
                errors.append(f"{code}: {str(e)}")

            time.sleep(0.3)

        return jsonify({
            "success": True,
            "stocks_processed": len(stocks),
            "records_updated": updated_count,
            "mode": mode,
            "errors": errors[:5] if errors else [],
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stock/<code>/balance-sheet")
def api_stock_balance_sheet(code):
    """查询指定股票的资产负债表数据。
    Query params:
      from_year, to_year: 年份范围
      period: FY(年报,默认) / Q1 / Q2 / Q3 / all(全部)
      view: cumulative(累计/快照,默认) / single(单季度)
    """
    from_year = request.args.get("from_year", 2000, type=int)
    to_year = request.args.get("to_year", 2030, type=int)
    period = request.args.get("period", "FY")
    view = request.args.get("view", "cumulative")

    need_single = (view == "single" and period != "FY")
    # 单季度模式下查全部报告期（用于计算差值），否则只查指定报告期
    query_period = None if need_single else (None if period == "all" else period)

    if query_period:
        where_period = "AND report_period = %s"
        params = [code, query_period, from_year, to_year]
    else:
        where_period = ""
        params = [code, from_year, to_year]

    rows = execute_query(
        f"""SELECT * FROM balance_sheets
           WHERE stock_code = %s {where_period}
           AND fiscal_year BETWEEN %s AND %s
           ORDER BY fiscal_year DESC, FIELD(report_period, 'FY','Q3','Q2','Q1') DESC""",
        tuple(params)
    )

    data_by_key = {}
    for r in rows:
        fy, rp = r["fiscal_year"], r["report_period"]
        item = {"fiscal_year": fy, "report_period": rp}
        for col in BS_COLUMNS:
            val = r.get(col)
            item[col] = float(val) if val is not None else None
        data_by_key[(fy, rp)] = item

    if need_single:
        periods_order = ["Q1", "Q2", "Q3", "FY"]
        prev_map = {"Q1": None, "Q2": "Q1", "Q3": "Q2", "FY": "Q3"}
        result = []
        for (fy, rp), item in sorted(data_by_key.items(), key=lambda x: (-x[0][0], periods_order.index(x[0][1]))):
            single = {"fiscal_year": fy, "report_period": rp}
            prev_key = (fy, prev_map[rp]) if prev_map[rp] else None
            prev_item = data_by_key.get(prev_key) if prev_key else None
            for col in BS_COLUMNS:
                cur = item.get(col)
                if cur is None:
                    single[col] = None
                elif prev_item is None or prev_item.get(col) is None:
                    single[col] = cur if rp == "Q1" else None
                else:
                    single[col] = round(cur - prev_item[col], 4)
            result.append(single)
        # 过滤到请求的报告期
        if period != "all":
            result = [r for r in result if r["report_period"] == period]
    else:
        result = sorted(data_by_key.values(), key=lambda x: (x["fiscal_year"], {"FY": 0, "Q3": 1, "Q2": 2, "Q1": 3}[x["report_period"]]), reverse=True)

    return jsonify(result)


# ==================== 估值分析 API ====================

@app.route("/api/stock/<code>/valuation")
def api_stock_valuation(code):
    """PE-TTM 历史 + 股价 + 分位点"""
    import sys as _sys2
    _sys2.stderr.write(f"[VALUATION] Starting for {code}\n")
    _sys2.stderr.flush()
    try:
        # 1. 获取所有财报季度的归母净利润 + 总股本，用于 TTM PE 计算
        # PE = 市值 / TTM归母净利润（比EPSJB更精确，避免股本变动和四舍五入误差）
        eps_records = []  # [(report_date, report_type, fiscal_year, parent_eps), ...]
        for report_type in ["%E5%B9%B4%E6%8A%A5", "%E4%B8%80%E5%AD%A3%E6%8A%A5", 
                            "%E5%8D%8A%E5%B9%B4%E6%8A%A5", "%E4%B8%89%E5%AD%A3%E6%8A%A5"]:
            url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                   "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                   f"&filter=(SECURITY_CODE=%22{code}%22)(REPORT_TYPE=%22{report_type}%22)"
                   "&pageSize=50&sortColumns=REPORT_DATE&sortTypes=-1")
            try:
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                data = resp.json()
                if data.get("success"):
                    for item in data["result"]["data"]:
                        rd = item.get("REPORT_DATE", "")
                        parent_np = item.get("PARENTNETPROFIT")  # 归母净利润
                        total_share = item.get("TOTAL_SHARE")    # 总股本
                        fy = int(item.get("REPORT_YEAR")) if item.get("REPORT_YEAR") else (int(rd[:4]) if rd[:4].isdigit() else 0)
                        if rd and parent_np and total_share and float(parent_np) > 0 and int(total_share) > 0 and fy:
                            parent_eps = float(parent_np) / int(total_share)
                            eps_records.append((rd[:10], report_type, fy, parent_eps))
            except Exception:
                pass
        eps_records.sort(key=lambda x: x[0])  # 按日期排序

        # 构建 TTM EPS 函数：给定日期，计算最近12个月每股收益
        # TTM = 最新年报EPS - 去年同期累计EPS + 今年最新累计EPS
        # 季报在财季结束后45天才实际披露，因此延迟生效
        def calc_ttm_eps(target_date, records):
            """target_date: 'YYYY-MM-DD'"""
            from datetime import datetime, timedelta
            target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            
            # 找到 target_date 当天或之前的最新有效财务报告（考虑披露延迟）
            latest = None
            for r in records:
                rd_dt = datetime.strptime(r[0], "%Y-%m-%d")
                # 年报: 次年4月30日前披露 → 从5月1日起生效
                # 半年报: 8月31日前披露 → 从9月1日起生效
                # Q3季报: 10月31日前披露 → 从11月1日起生效
                # Q1季报: 4月30日前披露 → 从5月1日起生效
                _, rtype, fy, _ = r
                if "%E5%B9%B4" in rtype:  # 年报
                    effective = datetime(fy + 1, 5, 1)
                elif "%E5%8D%8A%E5%B9%B4" in rtype:  # 半年报
                    effective = datetime(fy, 9, 1)
                elif "%E4%B8%89%E5%AD%A3" in rtype:  # Q3季报
                    effective = datetime(fy, 11, 1)
                else:  # Q1季报
                    effective = datetime(fy, 5, 1)
                
                if effective <= target_dt:
                    latest = r
                else:
                    break
            if not latest:
                return None
            
            rd, rtype, fy, eps = latest
            
            # 年报：直接用作 TTM
            if "%E5%B9%B4" in rtype:  # 年报
                # 检查是否有更新的季报在同一财年之后
                # 年报日期通常是最新的，直接返回
                return eps
            
            # 找到最近的一份年报
            latest_annual_eps = None
            for r in records:
                if "%E5%B9%B4" in r[1] and r[0] <= target_date:
                    latest_annual_eps = r[3]
            
            if not latest_annual_eps:
                return eps  # 无年报时直接用累计EPS
            
            # 找到去年同期的累计EPS
            # 同一 REPORT_TYPE，fiscal_year - 1
            last_year_same = None
            for r in records:
                if r[1] == rtype and r[2] == fy - 1:
                    last_year_same = r[3]
                    break
            
            if last_year_same is None:
                return latest_annual_eps
            
            # TTM = 去年年报EPS - 去年同期EPS + 今年最新累计EPS
            ttm = latest_annual_eps - last_year_same + eps
            return max(ttm, 0) if ttm > 0 else None

        # 2. 获取股价（前复权）—— 分批拉取以覆盖更长历史
        market = "sh" if code.startswith(("6", "5", "9")) else "sz"
        symbol = f"{market}{code}"
        price_data = []
        try:
            # 第一段：最近数据
            urls = [f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,640,qfq"]
            # 追加更早的批次（每批约2-3年）
            for y in range(2023, 2000, -3):
                urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{y-3}-01-01,{y}-12-31,640,qfq")
            seen = set()
            for u in urls[:8]:  # 最多8批 ≈ 20年
                try:
                    r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    d2 = r.json()
                    stock_data = d2.get("data", {})
                    if isinstance(stock_data, dict):
                        stock_data = stock_data.get(symbol, {})
                        raw = stock_data.get("day") or stock_data.get("qfqday") or []
                    else:
                        raw = []
                    for row in raw:
                        if row[0] not in seen:
                            seen.add(row[0])
                            price_data.append({"date": row[0], "close": float(row[2])})
                except Exception:
                    pass
            price_data.sort(key=lambda x: x["date"])
        except Exception:
            pass

        # 股息率需要未复权价格，否则未复权每股分红除以前复权老股价会显著失真。
        raw_price_data = []
        try:
            raw_urls = [f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,,,640"]
            for y in range(2023, 2000, -3):
                raw_urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,{y-3}-01-01,{y}-12-31,640")
            seen_raw = set()
            for u in raw_urls[:8]:
                try:
                    r = requests.get(u, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    d2 = r.json()
                    stock_data = d2.get("data", {})
                    if isinstance(stock_data, dict):
                        stock_data = stock_data.get(symbol, {})
                        raw = stock_data.get("day") or []
                    else:
                        raw = []
                    for row in raw:
                        if row[0] not in seen_raw:
                            seen_raw.add(row[0])
                            raw_price_data.append({"date": row[0], "close": float(row[2])})
                except Exception:
                    pass
            raw_price_data.sort(key=lambda x: x["date"])
        except Exception:
            pass

        # 3. 计算每日 PE-TTM：前复权股价 / TTM EPS
        pe_data = []
        if price_data and eps_records:
            for p in price_data:
                ttm_eps = calc_ttm_eps(p["date"], eps_records)
                if ttm_eps and ttm_eps > 0:
                    pe = round(p["close"] / ttm_eps, 2)
                    if 0 < pe < 9999:
                        pe_data.append({"date": p["date"], "pe": pe})

        # 4. 计算分位点
        pe_values = [p["pe"] for p in pe_data if p["pe"] > 0]
        pe_values.sort()
        if pe_values:
            n = len(pe_values)
            p80 = pe_values[int(n * 0.8)] if n > 0 else None
            p50 = pe_values[int(n * 0.5)] if n > 0 else None
            p20 = pe_values[int(n * 0.2)] if n > 0 else None
            # 当前 PE 取最新日期值，非排序后最大值
            cur_pe = pe_data[-1]["pe"] if pe_data else None
            cur_pct = round(sum(1 for v in pe_values if v <= cur_pe) / n * 100, 2) if cur_pe and n > 0 else None
        else:
            p80 = p50 = p20 = cur_pe = cur_pct = None

        # 5. 获取实时 PE-TTM 和 PB（qt.gtimg.cn，比计算值更精确）
        realtime_pe = None
        realtime_pb = None
        try:
            prefix = "sh" if code.startswith(("6", "5", "9")) else "sz"
            url3 = f"https://qt.gtimg.cn/q={prefix}{code}"
            resp3 = requests.get(url3, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            resp3.encoding = "gbk"
            text = resp3.text
            if text.startswith("v_"):
                parts = text.split("~")
                if len(parts) >= 40:
                    pe_str = parts[39].strip()
                    if pe_str and pe_str not in ("", "-"):
                        realtime_pe = float(pe_str)
                # 腾讯行情 parts[43] = 市净率 PB
                if len(parts) >= 44:
                    pb_str = parts[43].strip()
                    if pb_str and pb_str not in ("", "-"):
                        try:
                            realtime_pb = float(pb_str)
                        except ValueError:
                            pass
        except Exception:
            pass

        # ==================== PB 估值（扣商誉）====================
        # PB = 前复权股价 / 每股净资产（扣商誉）
        # 每股净资产 = (归母股东权益 - 商誉) / 总股本
        # 数据源：balance_sheets.parent_equity + balance_sheets.goodwill + 东方财富 TOTAL_SHARE
        # 披露延迟规则与 PE 一致：年报→次年5/1，半年报→9/1，三季报→11/1，一季报→5/1
        # ==================== 股息率估值 ====================
        # 股息率 = 最近已知年度每股分红 / 当日前复权收盘价。
        # 分红数据来自本地 dividends 表；ex_date 缺失时使用次年 7 月 1 日作为保守生效日。
        dividend_yield_data = []
        current_dividend_yield = None
        try:
            div_rows = execute_query(
                """SELECT fiscal_year, dividend_per_share, ex_date
                   FROM dividends
                   WHERE stock_code=%s AND dividend_per_share IS NOT NULL AND dividend_per_share > 0
                   ORDER BY fiscal_year ASC""",
                (code,)
            )
            div_records = []
            for r in div_rows:
                dps = float(r["dividend_per_share"]) if r["dividend_per_share"] is not None else 0
                if dps <= 0:
                    continue
                if r.get("ex_date"):
                    effective = datetime.strptime(str(r["ex_date"])[:10], "%Y-%m-%d")
                else:
                    effective = datetime(int(r["fiscal_year"]) + 1, 7, 1)
                div_records.append((effective, dps))
            div_records.sort(key=lambda x: x[0])

            dividend_prices = raw_price_data or price_data
            if dividend_prices and div_records:
                for p in dividend_prices:
                    p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                    latest_dps = None
                    for effective, dps in div_records:
                        if effective <= p_date:
                            latest_dps = dps
                        else:
                            break
                    if latest_dps and p["close"] > 0:
                        dy = round(latest_dps / p["close"] * 100, 4)
                        if 0 < dy < 100:
                            dividend_yield_data.append({"date": p["date"], "dividend_yield": dy})
                if dividend_yield_data:
                    current_dividend_yield = dividend_yield_data[-1]["dividend_yield"]
        except Exception:
            pass

        import sys as _sys
        _sys.stderr.write(f"[PB] Starting PB computation for {code}\n")
        _sys.stderr.flush()
        pb_data = []
        try:
            # 获取东方财富财报数据（含 TOTAL_SHARE），同时匹配 balance_sheets 的归母权益和商誉
            report_type_map = {
                "%E5%B9%B4%E6%8A%A5": "FY",
                "%E4%B8%80%E5%AD%A3%E6%8A%A5": "Q1",
                "%E5%8D%8A%E5%B9%B4%E6%8A%A5": "Q2",
                "%E4%B8%89%E5%AD%A3%E6%8A%A5": "Q3",
            }
            # 从 balance_sheets 加载归母权益和商誉
            bs_rows = execute_query(
                "SELECT fiscal_year, report_period, parent_equity, goodwill "
                "FROM balance_sheets WHERE stock_code=%s AND parent_equity IS NOT NULL "
                "ORDER BY fiscal_year, FIELD(report_period,'Q1','Q2','Q3','FY')",
                (code,)
            )
            bs_map = {}  # {(fiscal_year, report_period): (parent_equity_亿, goodwill_亿)}
            for r in bs_rows:
                pe_val = float(r["parent_equity"]) if r["parent_equity"] is not None else None
                gw_val = float(r["goodwill"]) if r["goodwill"] is not None else 0.0
                if pe_val is not None:
                    bs_map[(r["fiscal_year"], r["report_period"])] = (pe_val, gw_val)
            print(f"[PB DEBUG] bs_map has {len(bs_map)} keys, sample: {list(bs_map.keys())[:3]}", flush=True)

            # 从东方财富获取 total_share 并匹配 balance_sheets 构建 每股净资产
            bv_records = []  # [(report_date, effective_date, bvps), ...]
            for report_type in ["%E5%B9%B4%E6%8A%A5", "%E4%B8%80%E5%AD%A3%E6%8A%A5",
                                "%E5%8D%8A%E5%B9%B4%E6%8A%A5", "%E4%B8%89%E5%AD%A3%E6%8A%A5"]:
                url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                       "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                       f"&filter=(SECURITY_CODE=%22{code}%22)(REPORT_TYPE=%22{report_type}%22)"
                       "&pageSize=50&sortColumns=REPORT_DATE&sortTypes=-1")
                try:
                    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    data = resp.json()
                    if data.get("success"):
                        for item in data["result"]["data"]:
                            rd = item.get("REPORT_DATE", "")
                            total_share = item.get("TOTAL_SHARE")
                            fy = int(item.get("REPORT_YEAR")) if item.get("REPORT_YEAR") else (int(rd[:4]) if rd[:4].isdigit() else 0)
                            rp = report_type_map.get(report_type, "FY")
                            if not rd or not total_share or int(total_share) <= 0 or not fy:
                                continue
                            # 匹配 balance_sheets
                            bs_key = (fy, rp)
                            if bs_key in bs_map:
                                parent_eq_亿, goodwill_亿 = bs_map[bs_key]
                                # 归母权益(元) = parent_equity_亿 * 1e8
                                # 商誉(元) = goodwill_亿 * 1e8
                                net_equity = (parent_eq_亿 - goodwill_亿) * 1e8
                                if net_equity > 0:
                                    bvps = net_equity / int(total_share)
                                    # 披露延迟
                                    rd_dt = datetime.strptime(rd[:10], "%Y-%m-%d")
                                    if rp == "FY":
                                        effective = datetime(fy + 1, 5, 1)
                                    elif rp == "Q2":
                                        effective = datetime(fy, 9, 1)
                                    elif rp == "Q3":
                                        effective = datetime(fy, 11, 1)
                                    else:  # Q1
                                        effective = datetime(fy, 5, 1)
                                    bv_records.append((rd[:10], effective, bvps))
                except Exception:
                    pass

            bv_records.sort(key=lambda x: x[1])  # 按生效日期排序
            print(f"[PB DEBUG] bv_records count: {len(bv_records)}", flush=True)

            # 对每个交易日，取最新生效的 每股净资产，计算 PB
            if price_data and bv_records:
                bv_idx = 0
                for p in price_data:
                    p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                    # 找到最新的生效 每股净资产
                    latest_bvps = None
                    for bv in bv_records:
                        if bv[1] <= p_date:
                            latest_bvps = bv[2]
                        else:
                            break
                    if latest_bvps and latest_bvps > 0:
                        pb = round(p["close"] / latest_bvps, 2)
                        if 0 < pb < 9999:
                            pb_data.append({"date": p["date"], "pb": pb})
        except Exception as e:
            import traceback
            print(f"[PB计算异常] {code}: {e}")
            traceback.print_exc()
            pass

        # PB 分位点
        pb_values = [p["pb"] for p in pb_data if p["pb"] > 0]
        pb_values.sort()
        if pb_values:
            n_pb = len(pb_values)
            p80_pb = pb_values[int(n_pb * 0.8)] if n_pb > 0 else None
            p50_pb = pb_values[int(n_pb * 0.5)] if n_pb > 0 else None
            p20_pb = pb_values[int(n_pb * 0.2)] if n_pb > 0 else None
            cur_pb = pb_data[-1]["pb"] if pb_data else None
            cur_pb_pct = round(sum(1 for v in pb_values if v <= cur_pb) / n_pb * 100, 2) if cur_pb and n_pb > 0 else None
            max_pb = max(pb_values)
            min_pb = min(pb_values)
            avg_pb = round(sum(pb_values) / n_pb, 2)
        else:
            p80_pb = p50_pb = p20_pb = cur_pb = cur_pb_pct = max_pb = min_pb = avg_pb = None

        return jsonify({
            "pe_data": pe_data,
            "pb_data": pb_data,
            "price_data": price_data,
            "current_pe": cur_pe,
            "current_pe_pct": cur_pct,
            "p80_pe": p80, "p50_pe": p50, "p20_pe": p20,
            "max_pe": max(pe_values) if pe_values else None,
            "min_pe": min(pe_values) if pe_values else None,
            "avg_pe": round(sum(pe_values) / len(pe_values), 2) if pe_values else None,
            "realtime_pe": realtime_pe,
            "current_pb": cur_pb,
            "current_pb_pct": cur_pb_pct,
            "p80_pb": p80_pb, "p50_pb": p50_pb, "p20_pb": p20_pb,
            "max_pb": max_pb,
            "min_pb": min_pb,
            "avg_pb": avg_pb,
            "realtime_pb": realtime_pb,
            "dividend_yield_data": dividend_yield_data,
            "current_dividend_yield": current_dividend_yield,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== K线图 API ====================

@app.route("/api/stock/<code>/kline")
def api_stock_kline(code):
    """获取股票K线数据（腾讯API，前复权）"""
    days = request.args.get("days", 365, type=int)
    period = request.args.get("period", "day")
    if period not in {"day", "week", "month", "quarter", "year"}:
        period = "day"
    symbol = _quote_symbol(code)

    def row_to_item(row):
        volume = float(row[5]) if len(row) > 5 else 0
        close = float(row[2])
        return {
            "date": row[0],
            "open": float(row[1]),
            "close": close,
            "high": float(row[3]),
            "low": float(row[4]),
            "volume": volume,
            "amount": round(volume * close * 100, 2),
        }

    def period_key(date_str):
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        if period == "week":
            iso_year, iso_week, _ = dt.isocalendar()
            return (iso_year, iso_week)
        if period == "month":
            return (dt.year, dt.month)
        if period == "quarter":
            return (dt.year, (dt.month - 1) // 3 + 1)
        return (dt.year,)

    def aggregate_items(items):
        if period == "day":
            return items
        groups = []
        current_key = None
        current = None
        for item in items:
            key = period_key(item["date"])
            if key != current_key:
                if current:
                    groups.append(current)
                current_key = key
                current = {
                    "date": item["date"],
                    "open": item["open"],
                    "close": item["close"],
                    "high": item["high"],
                    "low": item["low"],
                    "volume": item["volume"],
                    "amount": item["amount"],
                }
                continue
            current["date"] = item["date"]
            current["close"] = item["close"]
            current["high"] = max(current["high"], item["high"])
            current["low"] = min(current["low"], item["low"])
            current["volume"] += item["volume"]
            current["amount"] += item["amount"]
        if current:
            groups.append(current)
        for item in groups:
            item["volume"] = round(item["volume"], 2)
            item["amount"] = round(item["amount"], 2)
        return groups

    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{days},qfq"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = resp.json()
        stock_data = data.get("data", {}).get(symbol, {})
        raw = stock_data.get("day") or stock_data.get("qfqday") or []
        result = aggregate_items([row_to_item(row) for row in raw])
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 利润表 & 现金流量表 API（数据源：新浪财经） ====================

# 利润表行映射
INCOME_ROW_MAP = [
    ("营业总收入", "total_revenue"),
    ("营业收入", "operating_revenue"),
    ("营业总成本", "operating_cost"),
    ("营业成本", "cost_of_revenue"),
    ("营业税金及附加", "tax_surcharge"),
    ("销售费用", "selling_expense"),
    ("管理费用", "admin_expense"),
    ("财务费用", "finance_expense"),
    ("研发费用", "rd_expense"),
    ("公允价值变动收益", "fair_value_change"),
    ("投资收益", "invest_income"),
    ("营业利润", "operating_profit"),
    ("营业外收入", "nonop_income"),          # 匹配"加:营业外收入"
    ("减：营业外支出", "nonop_expense"),
    ("利润总额", "total_profit"),
    ("所得税费用", "income_tax"),
    ("净利润", "net_profit"),
    ("归属于母公司所有者的净利润", "parent_net_profit"),
    ("少数股东损益", "minority_profit"),
    ("基本每股收益", "basic_eps"),
    ("稀释每股收益", "diluted_eps"),
    ("其他综合收益", "other_comprehensive"),
    ("综合收益总额", "total_comprehensive"),
    ("归属于母公司所有者的综合收益总额", "parent_comprehensive"),
]
INCOME_COLUMNS = [c for _, c in INCOME_ROW_MAP]

# 现金流量表行映射
CASHFLOW_ROW_MAP = [
    ("销售商品、提供劳务收到的现金", "cf_sales_goods"),
    ("收到的税费返还", "cf_tax_refund"),
    ("收到的其他与经营活动有关的现金", "cf_other_oper_in"),
    ("经营活动现金流入小计", "cf_oper_inflow"),
    ("购买商品、接受劳务支付的现金", "cf_buy_goods"),
    ("支付给职工以及为职工支付的现金", "cf_payroll"),
    ("支付的各项税费", "cf_tax_pay"),
    ("支付的其他与经营活动有关的现金", "cf_other_oper_out"),
    ("经营活动现金流出小计", "cf_oper_outflow"),
    ("经营活动产生的现金流量净额", "cf_oper_net"),
    ("收回投资所收到的现金", "cf_invest_withdraw"),
    ("取得投资收益所收到的现金", "cf_invest_income"),
    ("处置固定资产、无形资产和其他长期资产所收回的现金净额", "cf_dispose_assets"),
    ("收到的其他与投资活动有关的现金", "cf_other_invest_in"),
    ("投资活动现金流入小计", "cf_invest_inflow"),
    ("购建固定资产、无形资产和其他长期资产所支付的现金", "cf_buy_assets"),
    ("投资所支付的现金", "cf_invest_pay"),
    ("支付的其他与投资活动有关的现金", "cf_other_invest_out"),
    ("投资活动现金流出小计", "cf_invest_outflow"),
    ("投资活动产生的现金流量净额", "cf_invest_net"),
    ("吸收投资收到的现金", "cf_finance_in"),
    ("取得借款收到的现金", "cf_borrow"),
    ("发行债券收到的现金", "cf_bond"),
    ("收到其他与筹资活动有关的现金", "cf_other_finance_in"),
    ("筹资活动现金流入小计", "cf_finance_inflow"),
    ("偿还债务支付的现金", "cf_repay_debt"),
    ("分配股利、利润或偿付利息所支付的现金", "cf_dividend_interest"),
    ("支付其他与筹资活动有关的现金", "cf_other_finance_out"),
    ("筹资活动现金流出小计", "cf_finance_outflow"),
    ("筹资活动产生的现金流量净额", "cf_finance_net"),
]
CASHFLOW_COLUMNS = [c for _, c in CASHFLOW_ROW_MAP]


def _parse_sina_finance(html, row_map, target_year=None):
    """通用新浪财报HTML解析（资产负债表/利润表/现金流量表共用）。
    返回 {year: {col: val}} 或指定 target_year 时返回单年 dict。
    """
    import re as _re

    all_tables = _re.findall(r'<table[^>]*>(.*?)</table>', html, _re.DOTALL)
    all_year_data = {}

    for table_html in all_tables:
        if '报表日期' not in table_html:
            continue

        # 检查是否有匹配的行——取第一个非表头的行名来验证
        rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, _re.DOTALL)
        has_match = False
        for r in rows:
            cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
            cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if cells:
                for pattern, _ in row_map:
                    if cells[0].startswith(pattern) or pattern in cells[0]:
                        has_match = True
                        break
            if has_match:
                break
        if not has_match:
            continue

        # 找所有日期列
        date_cols = []
        for r in rows:
            cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
            cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if any('报表日期' in c for c in cells):
                for idx, c in enumerate(cells):
                    m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', c)
                    if m:
                        date_cols.append((idx, int(m.group(1)), c))
                break

        if not date_cols:
            continue

        for col_idx, col_year, col_date in date_cols:
            if target_year is not None and col_year != target_year:
                continue

            # Map month to report_period: 12→FY, 09→Q3, 06→Q2, 03→Q1, else→FY
            m = _re.match(r'\d{4}-(\d{2})-\d{2}', col_date)
            month = int(m.group(1)) if m else 12
            rp_map = {12: 'FY', 9: 'Q3', 6: 'Q2', 3: 'Q1'}
            rp = rp_map.get(month, 'FY')
            composite_key = (col_year, rp)

            values = {}
            for r in rows:
                cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if not cells or len(cells) <= col_idx:
                    continue

                row_name = cells[0]
                raw_val = cells[col_idx]

                for pattern, col in row_map:
                    if row_name.startswith(pattern) or pattern in row_name:
                        if raw_val and raw_val not in ("--", "", "None"):
                            try:
                                values[col] = round(float(raw_val.replace(",", "")) / 10000, 4)
                            except ValueError:
                                pass
                        break

            if values:
                all_year_data[composite_key] = values

    if target_year is not None:
        return {k: v for k, v in all_year_data.items() if k[0] == target_year}
    return all_year_data


def _upsert_finance(stock_code, all_years, columns, table):
    """通用财报数据写入。all_years: {(year, report_period): {col: val}}"""
    for (year, rp), values in sorted(all_years.items()):
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)
        update_clause = ", ".join([f"{c}=VALUES({c})" for c in columns])

        sql = (
            f"INSERT INTO {table} (stock_code, fiscal_year, report_period, {col_names}) "
            f"VALUES (%s, %s, %s, {placeholders}) "
            f"ON DUPLICATE KEY UPDATE {update_clause}"
        )
        params = [stock_code, year, rp] + [values.get(c) for c in columns]
        execute_query(sql, tuple(params), fetch=False)


# ── 利润表 API ──

# ==================== 营收构成 API ====================

SEGMENT_DIMENSIONS = {
    "business": "按业务",
    "product": "按产品",
    "region": "按地区",
}


def _ensure_segments_table():
    """Create the business segment table used by the revenue composition tab."""
    execute_query(
        """CREATE TABLE IF NOT EXISTS business_segments (
            id BIGINT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) NOT NULL,
            fiscal_year INT NOT NULL,
            report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
            dimension_type VARCHAR(20) NOT NULL,
            segment_name VARCHAR(120) NOT NULL,
            revenue DECIMAL(18,4) DEFAULT NULL,
            cost DECIMAL(18,4) DEFAULT NULL,
            gross_profit DECIMAL(18,4) DEFAULT NULL,
            gross_margin DECIMAL(10,4) DEFAULT NULL,
            revenue_ratio DECIMAL(10,4) DEFAULT NULL,
            profit_ratio DECIMAL(10,4) DEFAULT NULL,
            source VARCHAR(50) DEFAULT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_segment (stock_code, fiscal_year, report_period, dimension_type, segment_name),
            KEY idx_segment_stock_year (stock_code, fiscal_year),
            KEY idx_segment_dimension (stock_code, dimension_type)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )


def _clean_cell(value):
    value = re.sub(r"<[^>]+>", "", value or "")
    value = html_lib.unescape(value)
    return value.replace("\xa0", " ").strip()


def _to_number(value, percent=False):
    if value is None:
        return None
    text = _clean_cell(str(value)).replace(",", "").replace("，", "")
    text = text.replace("%", "").replace("％", "").strip()
    text = text.replace("--", "").replace("－", "").replace("—", "")
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    num = float(match.group(0))
    if percent:
        return round(num, 4)
    if "亿元" in text or "亿" in text:
        return round(num, 4)
    # Sina main-business tables are usually reported in 万元.
    return round(num / 10000, 4)


def _detect_segment_dimension(text):
    if "按产品" in text or "产品构成" in text:
        return "product"
    if "按地区" in text or "地区构成" in text:
        return "region"
    if "按行业" in text or "业务构成" in text or "行业构成" in text:
        return "business"
    return None


def _detect_report_period(text):
    match = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})?", text)
    if not match:
        match = re.search(r"(20\d{2})", text)
        return (int(match.group(1)), "FY") if match else (None, "FY")
    year = int(match.group(1))
    month = int(match.group(2))
    period = {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")
    return year, period


def _parse_sina_segments(page_html):
    """Best-effort parser for Sina main-business composition tables."""
    records = []
    table_matches = list(re.finditer(r"<table[^>]*>(.*?)</table>", page_html, re.DOTALL | re.IGNORECASE))

    for match in table_matches:
        table_html = match.group(1)
        context_html = page_html[max(0, match.start() - 1200):match.start()]
        context_text = _clean_cell(context_html)
        table_text = _clean_cell(table_html)
        if "主营" not in table_text and "营业收入" not in table_text:
            continue

        dimension = _detect_segment_dimension(context_text + table_text)
        if not dimension:
            continue

        fiscal_year, report_period = _detect_report_period(context_text + table_text)
        if not fiscal_year:
            continue

        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
        header_cells = []
        col_map = {}
        for row_html in rows:
            cells = [_clean_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE)]
            if not cells:
                continue
            joined = "".join(cells)
            if ("主营收入" in joined or "营业收入" in joined) and ("项目" in joined or "名称" in joined or "构成" in joined):
                header_cells = cells
                break

        if header_cells:
            for idx, label in enumerate(header_cells):
                if any(k in label for k in ("项目", "名称", "构成")):
                    col_map["name"] = idx
                elif "收入" in label and "比例" not in label and "占比" not in label:
                    col_map["revenue"] = idx
                elif "成本" in label:
                    col_map["cost"] = idx
                elif "利润" in label and "率" not in label and "比例" not in label:
                    col_map["gross_profit"] = idx
                elif "毛利率" in label or "利润率" in label:
                    col_map["gross_margin"] = idx

        if "name" not in col_map:
            col_map["name"] = 0
        if "revenue" not in col_map:
            col_map["revenue"] = 1
        if "cost" not in col_map:
            col_map["cost"] = 2
        if "gross_profit" not in col_map:
            col_map["gross_profit"] = 3
        if "gross_margin" not in col_map:
            col_map["gross_margin"] = 4

        for row_html in rows:
            cells = [_clean_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE)]
            if len(cells) <= col_map.get("revenue", 1):
                continue
            name = cells[col_map["name"]].strip()
            if not name or any(x in name for x in ("项目", "合计", "总计", "主营业务")):
                continue
            revenue = _to_number(cells[col_map["revenue"]])
            cost = _to_number(cells[col_map["cost"]]) if len(cells) > col_map["cost"] else None
            gross_profit = _to_number(cells[col_map["gross_profit"]]) if len(cells) > col_map["gross_profit"] else None
            gross_margin = _to_number(cells[col_map["gross_margin"]], percent=True) if len(cells) > col_map["gross_margin"] else None
            if revenue is None:
                continue
            if gross_profit is None and cost is not None:
                gross_profit = round(revenue - cost, 4)
            if gross_margin is None and revenue not in (None, 0) and gross_profit is not None:
                gross_margin = round(gross_profit / revenue * 100, 4)
            records.append({
                "fiscal_year": fiscal_year,
                "report_period": report_period,
                "dimension_type": dimension,
                "segment_name": name[:120],
                "revenue": revenue,
                "cost": cost,
                "gross_profit": gross_profit,
                "gross_margin": gross_margin,
                "source": "sina",
            })

    grouped = {}
    for r in records:
        key = (r["fiscal_year"], r["report_period"], r["dimension_type"])
        grouped.setdefault(key, []).append(r)
    for rows in grouped.values():
        total_revenue = sum((r["revenue"] or 0) for r in rows)
        total_profit = sum((r["gross_profit"] or 0) for r in rows)
        for r in rows:
            r["revenue_ratio"] = round((r["revenue"] or 0) / total_revenue * 100, 4) if total_revenue else None
            r["profit_ratio"] = round((r["gross_profit"] or 0) / total_profit * 100, 4) if total_profit else None
    return records


def _yuan_to_yi(value):
    if value is None:
        return None
    return round(float(value) / 100000000, 4)


def _ratio_to_pct(value):
    if value is None:
        return None
    return round(float(value) * 100, 4)


def _parse_eastmoney_segments(payload):
    type_map = {"1": "business", "2": "product", "3": "region"}
    data = ((payload or {}).get("result") or {}).get("data") or []
    records = []
    for row in data:
        dimension = type_map.get(str(row.get("MAINOP_TYPE") or ""))
        if not dimension:
            continue
        report_date = row.get("REPORT_DATE") or ""
        year_match = re.search(r"(20\d{2})", report_date)
        if not year_match:
            continue
        fiscal_year = int(year_match.group(1))
        month_match = re.search(r"20\d{2}-(\d{2})", report_date)
        month = int(month_match.group(1)) if month_match else 12
        report_period = {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")
        name = (row.get("ITEM_NAME") or "").strip()
        if not name:
            continue
        revenue = _yuan_to_yi(row.get("MAIN_BUSINESS_INCOME"))
        cost = _yuan_to_yi(row.get("MAIN_BUSINESS_COST"))
        gross_profit = _yuan_to_yi(row.get("MAIN_BUSINESS_RPOFIT"))
        gross_margin = _ratio_to_pct(row.get("GROSS_RPOFIT_RATIO"))
        if revenue is None:
            continue
        if gross_profit is None and cost is not None:
            gross_profit = round(revenue - cost, 4)
        if gross_margin is None and revenue and gross_profit is not None:
            gross_margin = round(gross_profit / revenue * 100, 4)
        records.append({
            "fiscal_year": fiscal_year,
            "report_period": report_period,
            "dimension_type": dimension,
            "segment_name": name[:120],
            "revenue": revenue,
            "cost": cost,
            "gross_profit": gross_profit,
            "gross_margin": gross_margin,
            "revenue_ratio": _ratio_to_pct(row.get("MBI_RATIO")),
            "profit_ratio": _ratio_to_pct(row.get("MBR_RATIO")),
            "source": "eastmoney",
        })
    return records


def _upsert_segments(stock_code, records):
    for r in records:
        execute_query(
            """INSERT INTO business_segments
               (stock_code, fiscal_year, report_period, dimension_type, segment_name,
                revenue, cost, gross_profit, gross_margin, revenue_ratio, profit_ratio, source)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE
                revenue=VALUES(revenue), cost=VALUES(cost), gross_profit=VALUES(gross_profit),
                gross_margin=VALUES(gross_margin), revenue_ratio=VALUES(revenue_ratio),
                profit_ratio=VALUES(profit_ratio), source=VALUES(source)""",
            (
                stock_code, r["fiscal_year"], r["report_period"], r["dimension_type"], r["segment_name"],
                r.get("revenue"), r.get("cost"), r.get("gross_profit"), r.get("gross_margin"),
                r.get("revenue_ratio"), r.get("profit_ratio"), r.get("source"),
            ),
            fetch=False,
        )


def _segment_summary(rows):
    if not rows:
        return None
    latest_year = max(r["fiscal_year"] for r in rows)
    latest = [r for r in rows if r["fiscal_year"] == latest_year]
    revenue_rows = sorted(latest, key=lambda x: x.get("revenue") or 0, reverse=True)
    profit_rows = sorted(latest, key=lambda x: x.get("gross_profit") or 0, reverse=True)
    total_revenue = sum((r.get("revenue") or 0) for r in latest)
    total_profit = sum((r.get("gross_profit") or 0) for r in latest)
    top3_revenue = sum((r.get("revenue") or 0) for r in revenue_rows[:3])
    return {
        "latest_year": latest_year,
        "top_revenue_segment": revenue_rows[0]["segment_name"] if revenue_rows else None,
        "top_revenue_ratio": revenue_rows[0].get("revenue_ratio") if revenue_rows else None,
        "top_profit_segment": profit_rows[0]["segment_name"] if profit_rows else None,
        "top_profit_ratio": profit_rows[0].get("profit_ratio") if profit_rows else None,
        "top3_revenue_ratio": round(top3_revenue / total_revenue * 100, 2) if total_revenue else None,
        "gross_margin": round(total_profit / total_revenue * 100, 2) if total_revenue and total_profit else None,
    }


@app.route("/api/stock/<code>/segments")
def api_stock_segments(code):
    _ensure_segments_table()
    dimension = request.args.get("dimension", "business")
    if dimension not in SEGMENT_DIMENSIONS:
        dimension = "business"
    from_year = request.args.get("from_year", 2000, type=int)
    to_year = request.args.get("to_year", 2030, type=int)
    rows = execute_query(
        """SELECT fiscal_year, report_period, dimension_type, segment_name, revenue, cost,
                  gross_profit, gross_margin, revenue_ratio, profit_ratio, source
           FROM business_segments
           WHERE stock_code=%s AND dimension_type=%s AND report_period='FY'
             AND fiscal_year BETWEEN %s AND %s
           ORDER BY fiscal_year ASC, revenue DESC""",
        (code, dimension, from_year, to_year),
    )
    result = []
    for r in rows:
        item = dict(r)
        for col in ("revenue", "cost", "gross_profit", "gross_margin", "revenue_ratio", "profit_ratio"):
            item[col] = float(item[col]) if item.get(col) is not None else None
        result.append(item)
    return jsonify({"data": result, "summary": _segment_summary(result)})


@app.route("/api/update-segments", methods=["POST"])
def api_update_segments():
    _ensure_segments_table()
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or request.args.get("code") or "").strip()
    if code:
        stocks = [{"code": code}]
    else:
        stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")

    updated = 0
    errors = []
    for s in stocks:
        stock_code = s["code"]
        try:
            url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
            resp = requests.get(
                url,
                params={
                    "reportName": "RPT_F10_FN_MAINOP",
                    "columns": "ALL",
                    "filter": f'(SECURITY_CODE="{stock_code}")',
                    "pageNumber": 1,
                    "pageSize": 500,
                    "sortColumns": "REPORT_DATE",
                    "sortTypes": -1,
                },
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
                timeout=15,
            )
            records = _parse_eastmoney_segments(resp.json())
            if not records:
                errors.append(f"{stock_code}: 未解析到业务构成数据")
                continue
            _upsert_segments(stock_code, records)
            updated += len(records)
        except Exception as e:
            errors.append(f"{stock_code}: {str(e)}")
        time.sleep(0.3)

    return jsonify({
        "success": len(errors) == 0 or updated > 0,
        "records_updated": updated,
        "stocks_processed": len(stocks),
        "errors": errors[:5] if errors else [],
    })


@app.route("/api/stock/<code>/income")
def api_stock_income(code):
    period = request.args.get("period", "FY")
    view = request.args.get("view", "cumulative")
    from_year = request.args.get("from_year", 2000, type=int)
    to_year = request.args.get("to_year", 2030, type=int)

    where_period = "AND report_period = %s"
    if period == "all":
        where_period = ""
    elif period != "FY":
        where_period = "AND report_period = %s"

    rows = execute_query(
        f"""SELECT * FROM income_statements
           WHERE stock_code=%s AND fiscal_year BETWEEN %s AND %s {where_period}
           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC""",
        (code, from_year, to_year, period) if where_period else (code, from_year, to_year)
    )
    result = []
    for r in rows:
        item = {"fiscal_year": r["fiscal_year"], "report_period": r["report_period"]}
        for col in INCOME_COLUMNS:
            item[col] = float(r[col]) if r.get(col) is not None else None
        result.append(item)
    return jsonify(result)


@app.route("/api/update-income", methods=["POST"])
def api_update_income():
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
    updated = 0
    errors = []

    for s in stocks:
        code = s["code"]
        try:
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/part/displaytype/0.phtml"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "gbk"
            all_years = _parse_sina_finance(resp.text, INCOME_ROW_MAP)

            existing = set()
            if mode == "incremental":
                for r in execute_query("SELECT fiscal_year FROM income_statements WHERE stock_code=%s", (code,)):
                    existing.add(r["fiscal_year"])

            for (year, rp), values in sorted(all_years.items()):
                if mode == "incremental" and year in existing:
                    continue
                _upsert_finance(code, {(year, rp): values}, INCOME_COLUMNS, "income_statements")
                updated += 1
        except Exception as e:
            errors.append(f"{code}: {str(e)}")
        time.sleep(0.3)

    return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})


# ── 现金流量表 API ──

@app.route("/api/stock/<code>/cashflow")
def api_stock_cashflow(code):
    period = request.args.get("period", "FY")
    view = request.args.get("view", "cumulative")
    from_year = request.args.get("from_year", 2000, type=int)
    to_year = request.args.get("to_year", 2030, type=int)

    where_period = "AND report_period = %s"
    if period == "all":
        where_period = ""
    elif period != "FY":
        where_period = "AND report_period = %s"

    rows = execute_query(
        f"""SELECT * FROM cash_flows
           WHERE stock_code=%s AND fiscal_year BETWEEN %s AND %s {where_period}
           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC""",
        (code, from_year, to_year, period) if where_period else (code, from_year, to_year)
    )
    result = []
    for r in rows:
        item = {"fiscal_year": r["fiscal_year"], "report_period": r["report_period"]}
        for col in CASHFLOW_COLUMNS:
            item[col] = float(r[col]) if r.get(col) is not None else None
        result.append(item)
    return jsonify(result)


@app.route("/api/update-cashflow", methods=["POST"])
def api_update_cashflow():
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
    updated = 0
    errors = []

    for s in stocks:
        code = s["code"]
        try:
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_CashFlow/stockid/{code}/ctrl/part/displaytype/0.phtml"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "gbk"
            all_years = _parse_sina_finance(resp.text, CASHFLOW_ROW_MAP)

            existing = set()
            if mode == "incremental":
                for r in execute_query("SELECT fiscal_year FROM cash_flows WHERE stock_code=%s", (code,)):
                    existing.add(r["fiscal_year"])

            for (year, rp), values in sorted(all_years.items()):
                if mode == "incremental" and year in existing:
                    continue
                _upsert_finance(code, {(year, rp): values}, CASHFLOW_COLUMNS, "cash_flows")
                updated += 1
        except Exception as e:
            errors.append(f"{code}: {str(e)}")
        time.sleep(0.3)

    return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})


@app.route("/api/stock/<code>/munger-chat", methods=["GET", "POST", "DELETE"])
def api_munger_chat(code):
    """对话芒格 API"""
    if request.method == "GET":
        return jsonify(get_chat_history(code))
    elif request.method == "DELETE":
        msg_id = request.args.get("msg_id", type=int)
        if msg_id:
            ok = delete_chat_msg(msg_id)
            return jsonify({"ok": ok})
        else:
            n = clear_chat_history(code)
            return jsonify({"ok": True, "deleted": n})
    elif request.method == "POST":
        data = request.get_json(force=True)
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "empty message"}), 400
        result = chat_send(code, message)
        return jsonify(result)


# ==================== 便利贴 API ====================

@app.route("/api/sticky-notes", methods=["GET", "POST"])
def api_sticky_notes():
    if request.method == "GET":
        stock_code = request.args.get("stock_code", "")
        notes = _load_notes()
        if stock_code:
            notes = [n for n in notes if n.get('stock_code') == stock_code or not n.get('stock_code')]
        # 按 id 倒序
        notes.sort(key=lambda n: n.get('id', 0), reverse=True)
        return jsonify(notes)
    elif request.method == "POST":
        data = request.get_json(force=True)
        notes = _load_notes()
        new_id = max([n.get('id', 0) for n in notes], default=0) + 1
        content = _extract_images(data.get('content', ''), new_id)
        now = datetime.now().isoformat()
        note = {
            'id': new_id,
            'title': data.get('title', ''),
            'content': content,
            'stock_code': data.get('stock_code', '') or '',
            'created_at': now,
            'updated_at': now
        }
        notes.append(note)
        _save_notes(notes)
        return jsonify({"ok": True, "id": new_id})


@app.route("/api/sticky-notes/<int:note_id>", methods=["PUT", "DELETE"])
def api_sticky_note(note_id):
    if request.method == "PUT":
        data = request.get_json(force=True)
        notes = _load_notes()
        for n in notes:
            if n.get('id') == note_id:
                _cleanup_images(n)
                n['title'] = data.get('title', '')
                n['content'] = _extract_images(data.get('content', ''), note_id)
                n['stock_code'] = data.get('stock_code', '') or ''
                n['updated_at'] = datetime.now().isoformat()
                _save_notes(notes)
                return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404
    elif request.method == "DELETE":
        notes = _load_notes()
        for n in notes:
            if n.get('id') == note_id:
                _cleanup_images(n)
                notes.remove(n)
                _save_notes(notes)
                return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404


@app.route('/data/images/<path:filename>')
def serve_sticky_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


if __name__ == "__main__":
    print("股票分析系统 Web 服务启动: http://127.0.0.1:5002")
    try:
        migration_result = run_migrations()
        if migration_result["count"]:
            print(f"✓ 已执行数据库迁移: {', '.join(migration_result['applied'])}")
        else:
            print("✓ 数据库迁移已是最新")
        _ensure_financials_columns()
        _ensure_segments_table()
        _ensure_stock_order_column()
        _ensure_portfolio_tables()
        _ensure_graham_valuation_table()
        print("✓ 已确保 custom_financials 表结构完整")
    except Exception as e:
        print(f"⚠ 表结构检查异常: {e}")
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
