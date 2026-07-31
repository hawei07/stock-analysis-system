"""stock - Web 服务"""

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
import mysql.connector
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


def _read_local_settings():
    path = os.path.join(APP_DIR, "local_settings.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
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


LOCAL_SETTINGS_PATH = os.path.join(APP_DIR, "local_settings.json")


from models import Stock
from db import get_connection, execute_query, execute_update
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
EXCHANGE_RATE_CACHE_JSON = os.path.join(APP_DIR, "data", "exchange_rates.json")
EXCHANGE_RATE_CACHE_SECONDS = 12 * 60 * 60
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
_irm_sync_lock = threading.Lock()
_irm_sync_running = False
_irm_sync_started_at = None
_irm_sync_finished_at = None
_irm_sync_last_result = {
    "status": "idle",
    "message": "尚未抓取互动易",
    "updated_at": None,
    "scope": None,
    "total": 0,
    "inserted": 0,
    "skipped": 0,
    "errors": [],
}
_valuation_cache = {}
_valuation_cache_lock = threading.Lock()
VALUATION_CACHE_SECONDS = 6 * 60 * 60

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


def _read_exchange_rate_cache():
    if not os.path.exists(EXCHANGE_RATE_CACHE_JSON):
        return {}
    try:
        with open(EXCHANGE_RATE_CACHE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_exchange_rate_cache(payload):
    os.makedirs(os.path.dirname(EXCHANGE_RATE_CACHE_JSON), exist_ok=True)
    with open(EXCHANGE_RATE_CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _currency_for_market(market):
    return "HKD" if market == "HK" else "CNY"


def _exchange_rate_to_cny(currency):
    currency = (currency or "CNY").upper()
    if currency == "CNY":
        return {"rate": 1.0, "base": "CNY", "target": "CNY", "date": None, "source": "native", "cached": False}

    key = f"{currency}_CNY"
    now = time.time()
    cache = _read_exchange_rate_cache()
    cached = (cache.get("rates") or {}).get(key)
    if cached and now - float(cached.get("fetched_at") or 0) < EXCHANGE_RATE_CACHE_SECONDS:
        return {**cached, "cached": True}

    if currency == "HKD":
        try:
            resp = requests.get(
                "https://api.frankfurter.dev/v2/rate/HKD/CNY",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=8,
            )
            data = resp.json()
            rate = float(data.get("rate"))
            payload = {
                "rate": rate,
                "base": "HKD",
                "target": "CNY",
                "date": data.get("date"),
                "source": "Frankfurter",
                "fetched_at": now,
                "cached": False,
            }
            cache.setdefault("rates", {})[key] = payload
            _write_exchange_rate_cache(cache)
            return payload
        except Exception:
            if cached:
                return {**cached, "cached": True, "stale": True}

    return None


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
    "api_portfolio_update_fee_config": "portfolio-fee-config-update",
    "api_portfolio_add_trade": "portfolio-trade-add",
    "api_portfolio_void_trade": "portfolio-trade-void",
    "api_portfolio_add_corporate_action": "portfolio-action-add",
    "api_portfolio_void_corporate_action": "portfolio-action-void",
    "api_portfolio_audit": "portfolio-audit",
    "api_portfolio_rebuild": "portfolio-rebuild",
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
        if request.endpoint in {
            "api_update_stock",
            "api_update_dividends",
            "api_update_financials",
            "api_update_balance_sheet",
            "api_update_income",
            "api_update_cashflow",
        }:
            with _valuation_cache_lock:
                _valuation_cache.clear()
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
    if market == "HK" or re.fullmatch(r"\d{5}", code):
        return "HK"
    if code.startswith(("6", "5", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    return market or "SZ"


def _quote_symbol(code, market=None):
    code = str(code or "")
    inferred_market = _market_from_code(code, market)
    if inferred_market == "HK":
        return f"hk{code.zfill(5)}"
    if inferred_market == "SH":
        return f"sh{code}"
    if inferred_market == "BJ":
        return f"bj{code}"
    return f"sz{code}"


def _normalize_stock_code(code):
    code = str(code or "").strip().upper()
    if code.startswith("HK"):
        code = code[2:]
    return code.zfill(5) if re.fullmatch(r"\d{1,5}", code) else code


def _lookup_hk_stock_info(code):
    code = _normalize_stock_code(code)
    if not re.fullmatch(r"\d{5}", code):
        return None
    try:
        resp = requests.get(
            f"https://qt.gtimg.cn/q=hk{code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.encoding = "gbk"
        text = resp.text or ""
        if not text.startswith("v_hk"):
            return None
        fields = text.split('"')[1].split("~") if '"' in text else []
        name = fields[1].strip() if len(fields) > 1 else ""
        if not name:
            return None
        return {"code": code, "name": name, "market": "HK", "industry": _fetch_stock_industry(code, "HK")}
    except Exception:
        return None


def _eastmoney_secid(code, market=None):
    market = (market or "").upper()
    if market == "HK" or re.fullmatch(r"\d{5}", str(code or "")):
        return f"116.{_normalize_stock_code(code)}"
    if market == "SH" or str(code).startswith(("6", "5", "9")):
        return f"1.{code}"
    return f"0.{code}"


def _fetch_stock_industry(code, market=None):
    try:
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": _eastmoney_secid(code, market), "fields": "f57,f58,f127"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data = resp.json().get("data") or {}
        industry = str(data.get("f127") or "").strip()
        return industry or None
    except Exception:
        return None


def _fill_missing_stock_industries(stock_rows):
    changed = {}
    for row in stock_rows or []:
        code = row.get("stock_code") or row.get("code")
        if not code or row.get("industry"):
            continue
        industry = _fetch_stock_industry(code, row.get("market"))
        if not industry:
            continue
        changed[code] = industry
        row["industry"] = industry
        try:
            execute_query(
                "UPDATE stocks SET industry=%s WHERE code=%s AND (industry IS NULL OR industry='')",
                (industry, code),
                fetch=False,
            )
        except Exception:
            pass
    return changed


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


def _ensure_shareholders_table():
    execute_query(
        """CREATE TABLE IF NOT EXISTS stock_shareholders (
            id BIGINT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            report_date DATE NOT NULL,
            holder_rank INT NOT NULL,
            holder_name VARCHAR(255) NOT NULL,
            shares_type VARCHAR(80) DEFAULT NULL,
            hold_num DECIMAL(24,4) DEFAULT NULL,
            hold_ratio DECIMAL(10,4) DEFAULT NULL,
            hold_change_label VARCHAR(80) DEFAULT NULL,
            hold_change_num DECIMAL(24,4) DEFAULT NULL,
            change_ratio DECIMAL(10,4) DEFAULT NULL,
            change_type VARCHAR(20) DEFAULT NULL,
            is_report_date TINYINT(1) DEFAULT 1,
            source VARCHAR(80) DEFAULT NULL,
            fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uk_stock_shareholder_period_rank (stock_code, report_date, holder_rank),
            KEY idx_stock_shareholders_stock_date (stock_code, report_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
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


def _fetch_realtime_quotes(stocks):
    symbols = [_quote_symbol(s["code"], s.get("market")) for s in stocks]
    if not symbols:
        return {}
    quotes = {}
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
                quote = {}
                try:
                    quote["price"] = float(fields[3])
                except (TypeError, ValueError):
                    pass
                if len(fields) > 31:
                    try:
                        quote["day_change"] = float(fields[31])
                    except (TypeError, ValueError):
                        pass
                if len(fields) > 32:
                    try:
                        quote["day_change_pct"] = float(fields[32])
                    except (TypeError, ValueError):
                        pass
                if quote:
                    quotes[code] = quote
    except Exception:
        pass
    return quotes


def _fetch_realtime_prices(stocks):
    quotes = _fetch_realtime_quotes(stocks)
    return {
        code: quote.get("price")
        for code, quote in quotes.items()
        if quote.get("price") is not None
    }


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


def _enrich_stock_list_metrics(stocks, include_ytd=False):
    if not stocks:
        return stocks
    codes = [s["code"] for s in stocks]
    placeholders = ",".join(["%s"] * len(codes))
    quotes = _fetch_realtime_quotes(stocks)

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
        quote = quotes.get(code, {})
        price = quote.get("price")
        day_change_pct = quote.get("day_change_pct")
        s["price"] = round(price, 2) if price is not None else None
        s["day_change_pct"] = round(day_change_pct, 2) if day_change_pct is not None else None
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
        s["ytd_return"] = _fetch_ytd_return(code, s.get("market"), price) if include_ytd else None
    return stocks


def _stock_realtime_list_metrics(codes):
    if not codes:
        return []
    placeholders = ",".join(["%s"] * len(codes))
    stocks = execute_query(
        f"SELECT code, market FROM stocks WHERE code IN ({placeholders})",
        tuple(codes),
    )
    if not stocks:
        return []

    quotes = _fetch_realtime_quotes(stocks)
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

    result = []
    for s in stocks:
        code = s["code"]
        quote = quotes.get(code, {})
        price = quote.get("price")
        day_change_pct = quote.get("day_change_pct")
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

        reasonable_discount = (
            round((price / fair_price - 1) * 100, 2)
            if price is not None and fair_price and fair_price > 0
            else None
        )
        pb_ex_goodwill = None
        equity = latest_equity.get(code)
        if price and total_shares and equity:
            parent_equity, goodwill = equity
            net_equity = parent_equity - goodwill
            if net_equity > 0:
                pb_ex_goodwill = round(price * total_shares / net_equity, 2)

        result.append({
            "code": code,
            "price": round(price, 2) if price is not None else None,
            "day_change_pct": round(day_change_pct, 2) if day_change_pct is not None else None,
            "reasonable_discount": reasonable_discount,
            "pb_ex_goodwill": pb_ex_goodwill,
        })
    return result


def _ensure_portfolio_tables():
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_positions (
            id INT NOT NULL AUTO_INCREMENT,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            shares DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price DECIMAL(18,4) NULL,
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
    try:
        rows = execute_query("SHOW COLUMNS FROM portfolio_cash LIKE 'base_amount'")
        if not rows:
            execute_query(
                "ALTER TABLE portfolio_cash ADD COLUMN base_amount DECIMAL(18,2) NULL AFTER amount",
                fetch=False,
            )
    except Exception:
        pass
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_cash_flows (
            id INT NOT NULL AUTO_INCREMENT,
            flow_date DATE NOT NULL,
            amount DECIMAL(18,2) NOT NULL,
            flow_source VARCHAR(20) NOT NULL DEFAULT 'external',
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_flow_date (flow_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    try:
        rows = execute_query("SHOW COLUMNS FROM portfolio_cash_flows LIKE 'flow_source'")
        if not rows:
            execute_query(
                "ALTER TABLE portfolio_cash_flows ADD COLUMN flow_source VARCHAR(20) NOT NULL DEFAULT 'external' AFTER amount",
                fetch=False,
            )
    except Exception:
        pass
    for column_name, column_def in (
        ("source_type", "VARCHAR(20) NULL AFTER flow_source"),
        ("source_id", "INT NULL AFTER source_type"),
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        try:
            rows = execute_query(f"SHOW COLUMNS FROM portfolio_cash_flows LIKE '{column_name}'")
            if not rows:
                execute_query(
                    f"ALTER TABLE portfolio_cash_flows ADD COLUMN {column_name} {column_def}",
                    fetch=False,
                )
        except Exception:
            pass
    try:
        execute_query(
            """UPDATE portfolio_cash_flows f
               JOIN portfolio_trades t
                 ON f.flow_date = t.trade_date
                AND ABS(f.amount) = t.amount
                AND ((t.trade_type='buy' AND f.amount < 0) OR (t.trade_type='sell' AND f.amount > 0))
               SET f.flow_source='trade'
               WHERE f.flow_source='external'""",
            fetch=False,
        )
    except Exception:
        pass
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_trades (
            id INT NOT NULL AUTO_INCREMENT,
            trade_date DATE NOT NULL,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
            trade_type VARCHAR(8) NOT NULL,
            shares DECIMAL(18,4) NOT NULL,
            price DECIMAL(18,4) NOT NULL,
            amount DECIMAL(18,2) NOT NULL,
            shares_before DECIMAL(18,4) NOT NULL DEFAULT 0,
            shares_after DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price_before DECIMAL(18,4) NULL,
            cost_price_after DECIMAL(18,4) NULL,
            realized_profit DECIMAL(18,2) NULL,
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_trade_stock_date (stock_code, trade_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_fee_config (
            id TINYINT NOT NULL PRIMARY KEY,
            commission_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000250,
            min_commission DECIMAL(18,2) NOT NULL DEFAULT 5.00,
            stamp_tax_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000500,
            transfer_fee_rate DECIMAL(10,6) NOT NULL DEFAULT 0.000010,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """CREATE TABLE IF NOT EXISTS portfolio_corporate_actions (
            id INT NOT NULL AUTO_INCREMENT,
            action_date DATE NOT NULL,
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
            action_type VARCHAR(20) NOT NULL,
            cash_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            shares DECIMAL(18,4) NOT NULL DEFAULT 0,
            price DECIMAL(18,4) NULL,
            amount DECIMAL(18,2) NOT NULL DEFAULT 0,
            cash_delta DECIMAL(18,2) NOT NULL DEFAULT 0,
            shares_before DECIMAL(18,4) NOT NULL DEFAULT 0,
            shares_after DECIMAL(18,4) NOT NULL DEFAULT 0,
            cost_price_before DECIMAL(18,4) NULL,
            cost_price_after DECIMAL(18,4) NULL,
            note VARCHAR(255) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            KEY idx_action_stock_date (stock_code, action_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )
    execute_query(
        """INSERT IGNORE INTO portfolio_fee_config
           (id, commission_rate, min_commission, stamp_tax_rate, transfer_fee_rate)
           VALUES (1, 0.000250, 5.00, 0.000500, 0.000010)""",
        fetch=False,
    )
    for column_name, column_def in (
        ("commission", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER amount"),
        ("stamp_tax", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER commission"),
        ("transfer_fee", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER stamp_tax"),
        ("total_fee", "DECIMAL(18,2) NOT NULL DEFAULT 0 AFTER transfer_fee"),
        ("cash_delta", "DECIMAL(18,2) NULL AFTER total_fee"),
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        try:
            rows = execute_query(f"SHOW COLUMNS FROM portfolio_trades LIKE '{column_name}'")
            if not rows:
                execute_query(
                    f"ALTER TABLE portfolio_trades ADD COLUMN {column_name} {column_def}",
                    fetch=False,
                )
        except Exception:
            pass
    for column_name, column_def in (
        ("is_void", "TINYINT NOT NULL DEFAULT 0 AFTER note"),
        ("voided_at", "DATETIME NULL AFTER is_void"),
        ("void_note", "VARCHAR(255) NULL AFTER voided_at"),
    ):
        try:
            rows = execute_query(f"SHOW COLUMNS FROM portfolio_corporate_actions LIKE '{column_name}'")
            if not rows:
                execute_query(
                    f"ALTER TABLE portfolio_corporate_actions ADD COLUMN {column_name} {column_def}",
                    fetch=False,
                )
        except Exception:
            pass
    try:
        rows = execute_query("SELECT amount, base_amount FROM portfolio_cash WHERE id=1")
        if rows and rows[0].get("base_amount") is None:
            flow_rows = execute_query("SELECT COALESCE(SUM(amount), 0) AS total FROM portfolio_cash_flows WHERE is_void=0")
            base_amount = _decimal_value(rows[0]["amount"]) - _decimal_value(flow_rows[0]["total"] if flow_rows else 0)
            execute_query(
                "UPDATE portfolio_cash SET base_amount=%s WHERE id=1",
                (_quantize(base_amount, "0.01"),),
                fetch=False,
            )
    except Exception:
        pass
    try:
        execute_query(
            """UPDATE portfolio_trades
               SET cash_delta = CASE
                   WHEN trade_type='buy' THEN -(amount + total_fee)
                   ELSE amount - total_fee
               END
               WHERE cash_delta IS NULL""",
            fetch=False,
        )
    except Exception:
        pass
    try:
        rows = execute_query("SHOW FULL COLUMNS FROM portfolio_trades LIKE 'stock_code'")
        if rows and rows[0].get("Collation") != "utf8mb4_unicode_ci":
            execute_query(
                "ALTER TABLE portfolio_trades MODIFY stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL",
                fetch=False,
            )
    except Exception:
        pass
    try:
        rows = execute_query("SHOW COLUMNS FROM portfolio_positions LIKE 'cost_price'")
        if not rows:
            execute_query(
                "ALTER TABLE portfolio_positions ADD COLUMN cost_price DECIMAL(18,4) NULL AFTER shares",
                fetch=False,
            )
    except Exception:
        pass
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
    try:
        _sync_portfolio_cost_basis_from_trades()
    except Exception:
        pass


def _decimal_value(value, default="0"):
    if value is None:
        value = default
    return Decimal(str(value))


def _quantize(value, scale="0.0001"):
    return _decimal_value(value).quantize(Decimal(scale), rounding=ROUND_HALF_UP)


def _decimal_equal(left, right, scale="0.0001"):
    if left is None or right is None:
        return left is None and right is None
    return _quantize(left, scale) == _quantize(right, scale)


def _execute_insert_id(sql, params=None):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(sql, params or ())
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


def _portfolio_fee_config():
    rows = execute_query(
        """SELECT commission_rate, min_commission, stamp_tax_rate, transfer_fee_rate
           FROM portfolio_fee_config
           WHERE id=1"""
    )
    if not rows:
        return {
            "commission_rate": Decimal("0.000250"),
            "min_commission": Decimal("5.00"),
            "stamp_tax_rate": Decimal("0.000500"),
            "transfer_fee_rate": Decimal("0.000010"),
        }
    row = rows[0]
    return {
        "commission_rate": _decimal_value(row.get("commission_rate")),
        "min_commission": _decimal_value(row.get("min_commission")),
        "stamp_tax_rate": _decimal_value(row.get("stamp_tax_rate")),
        "transfer_fee_rate": _decimal_value(row.get("transfer_fee_rate")),
    }


def _portfolio_fee_config_payload():
    _ensure_portfolio_tables()
    config = _portfolio_fee_config()
    return {
        "commission_rate": float(config["commission_rate"]),
        "min_commission": float(config["min_commission"]),
        "stamp_tax_rate": float(config["stamp_tax_rate"]),
        "transfer_fee_rate": float(config["transfer_fee_rate"]),
    }


def _is_domestic_market(market):
    return str(market or "").upper() in {"SH", "SZ", "BJ"}


def _calculate_portfolio_trade_fees(amount, trade_type, market, config=None):
    amount = _decimal_value(amount)
    if not _is_domestic_market(market):
        return {
            "commission": Decimal("0.00"),
            "stamp_tax": Decimal("0.00"),
            "transfer_fee": Decimal("0.00"),
            "total_fee": Decimal("0.00"),
        }

    config = config or _portfolio_fee_config()
    commission_rate = config["commission_rate"]
    min_commission = config["min_commission"]
    commission = amount * commission_rate
    if commission > 0 and commission < min_commission:
        commission = min_commission
    stamp_tax = amount * config["stamp_tax_rate"] if trade_type == "sell" else Decimal("0")
    transfer_fee = amount * config["transfer_fee_rate"]
    commission = _quantize(commission, "0.01")
    stamp_tax = _quantize(stamp_tax, "0.01")
    transfer_fee = _quantize(transfer_fee, "0.01")
    return {
        "commission": commission,
        "stamp_tax": stamp_tax,
        "transfer_fee": transfer_fee,
        "total_fee": commission + stamp_tax + transfer_fee,
    }


def _sync_portfolio_cost_basis_from_trades():
    trade_rows = execute_query(
        """SELECT id, stock_code, trade_date, trade_type, shares, price, amount,
                  commission, stamp_tax, transfer_fee, total_fee, cash_delta,
                  shares_before, shares_after, cost_price_before, cost_price_after, realized_profit
           FROM portfolio_trades
           WHERE is_void=0
           ORDER BY stock_code, trade_date, id"""
    )
    action_rows = execute_query(
        """SELECT id, action_date, stock_code, action_type, cash_amount, shares, price, amount, cash_delta,
                  shares_before, shares_after, cost_price_before, cost_price_after, note
           FROM portfolio_corporate_actions
           WHERE is_void=0
           ORDER BY stock_code, action_date, id"""
    )
    if not trade_rows and not action_rows:
        return False

    changed = False
    grouped = {}
    for row in trade_rows:
        item = dict(row)
        item["_kind"] = "trade"
        item["_date"] = row["trade_date"]
        grouped.setdefault(row["stock_code"], []).append(item)
    for row in action_rows:
        item = dict(row)
        item["_kind"] = "action"
        item["_date"] = row["action_date"]
        grouped.setdefault(row["stock_code"], []).append(item)

    for code, items in grouped.items():
        items.sort(key=lambda item: (item["_date"], 0 if item["_kind"] == "trade" else 1, item["id"]))
        first = items[0]
        shares = _decimal_value(first.get("shares_before"))
        cost = _decimal_value(first.get("cost_price_before")) if first.get("cost_price_before") is not None else None
        if cost is None and shares == 0:
            cost = Decimal("0")
        if cost is None:
            continue

        for item in items:
            before_shares = shares
            before_cost = cost if before_shares > 0 else None
            realized_profit = None
            next_cash_delta = Decimal("0.00")

            if item["_kind"] == "trade":
                trade_shares = _decimal_value(item["shares"])
                price = _decimal_value(item["price"])
                amount = _decimal_value(item["amount"])
                total_fee = _decimal_value(item.get("total_fee"))
                cash_delta = _decimal_value(item.get("cash_delta")) if item.get("cash_delta") is not None else None
                if item["trade_type"] == "buy":
                    buy_cost = amount + total_fee
                    shares = before_shares + trade_shares
                    cost = ((before_shares * cost) + buy_cost) / shares if before_shares > 0 and shares > 0 else buy_cost / trade_shares
                    next_cash_delta = -buy_cost
                else:
                    if before_cost is None:
                        break
                    sell_proceeds = amount - total_fee
                    realized_profit = sell_proceeds - (before_cost * trade_shares)
                    shares = before_shares - trade_shares
                    cost = ((before_shares * before_cost) - sell_proceeds) / shares if shares > 0 else None
                    next_cash_delta = sell_proceeds

                trade_changed = (
                    not _decimal_equal(item.get("shares_before"), before_shares)
                    or not _decimal_equal(item.get("shares_after"), shares)
                    or not _decimal_equal(item.get("cost_price_before"), before_cost)
                    or not _decimal_equal(item.get("cost_price_after"), cost)
                    or not _decimal_equal(item.get("realized_profit"), realized_profit, "0.01")
                    or not _decimal_equal(cash_delta, next_cash_delta, "0.01")
                )
                if trade_changed:
                    execute_query(
                        """UPDATE portfolio_trades
                           SET shares_before=%s, shares_after=%s,
                               cost_price_before=%s, cost_price_after=%s, realized_profit=%s,
                               cash_delta=%s
                           WHERE id=%s""",
                        (
                            _quantize(before_shares),
                            _quantize(shares),
                            _quantize(before_cost) if before_cost is not None else None,
                            _quantize(cost) if cost is not None else None,
                            _quantize(realized_profit, "0.01") if realized_profit is not None else None,
                            _quantize(next_cash_delta, "0.01"),
                            item["id"],
                        ),
                        fetch=False,
                    )
                    changed = True
                continue

            action_type = item["action_type"]
            if before_cost is None:
                break
            if action_type == "cash_dividend":
                cash_amount = _decimal_value(item["cash_amount"])
                shares = before_shares
                cost = ((before_shares * before_cost) - cash_amount) / shares if shares > 0 else None
                next_cash_delta = cash_amount
            elif action_type == "bonus_share":
                bonus_shares = _decimal_value(item["shares"])
                shares = before_shares + bonus_shares
                cost = (before_shares * before_cost) / shares if shares > 0 else None
            elif action_type == "rights_issue":
                issue_shares = _decimal_value(item["shares"])
                amount = _decimal_value(item["amount"])
                shares = before_shares + issue_shares
                cost = ((before_shares * before_cost) + amount) / shares if shares > 0 else None
                next_cash_delta = -amount
            else:
                continue

            action_changed = (
                not _decimal_equal(item.get("shares_before"), before_shares)
                or not _decimal_equal(item.get("shares_after"), shares)
                or not _decimal_equal(item.get("cost_price_before"), before_cost)
                or not _decimal_equal(item.get("cost_price_after"), cost)
                or not _decimal_equal(item.get("cash_delta"), next_cash_delta, "0.01")
            )
            if action_changed:
                execute_query(
                    """UPDATE portfolio_corporate_actions
                       SET shares_before=%s, shares_after=%s,
                           cost_price_before=%s, cost_price_after=%s, cash_delta=%s
                       WHERE id=%s""",
                    (
                        _quantize(before_shares),
                        _quantize(shares),
                        _quantize(before_cost) if before_cost is not None else None,
                        _quantize(cost) if cost is not None else None,
                        _quantize(next_cash_delta, "0.01"),
                        item["id"],
                    ),
                    fetch=False,
                )
                changed = True

        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (code,),
        )
        if shares > 0:
            if position_rows:
                current = position_rows[0]
                position_changed = (
                    not _decimal_equal(current.get("shares"), shares)
                    or not _decimal_equal(current.get("cost_price"), cost)
                )
                if position_changed:
                    execute_query(
                        "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                        (_quantize(shares), _quantize(cost) if cost is not None else None, code),
                        fetch=False,
                    )
                    changed = True
            else:
                execute_query(
                    "INSERT INTO portfolio_positions (stock_code, shares, cost_price) VALUES (%s, %s, %s)",
                    (code, _quantize(shares), _quantize(cost) if cost is not None else None),
                    fetch=False,
                )
                changed = True
        elif position_rows:
            execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)
            changed = True

    return changed


def _portfolio_cash_amount():
    _ensure_portfolio_tables()
    rows = execute_query("SELECT amount FROM portfolio_cash WHERE id=1")
    return float(rows[0]["amount"]) if rows else 0.0


def _portfolio_cash_base_amount():
    _ensure_portfolio_tables()
    rows = execute_query("SELECT base_amount FROM portfolio_cash WHERE id=1")
    return _decimal_value(rows[0]["base_amount"]) if rows and rows[0].get("base_amount") is not None else Decimal("0")


def _portfolio_rebuilt_cash_amount():
    base_amount = _portfolio_cash_base_amount()
    rows = execute_query("SELECT COALESCE(SUM(amount), 0) AS total FROM portfolio_cash_flows WHERE is_void=0")
    return base_amount + _decimal_value(rows[0]["total"] if rows else 0)


def _portfolio_flow_rows(limit=100):
    _ensure_portfolio_tables()
    return execute_query(
        """SELECT id, flow_date, amount, flow_source, source_type, source_id, note,
                  is_void, voided_at, void_note, created_at
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
            "flow_source": r.get("flow_source") or "external",
            "source_type": r.get("source_type"),
            "source_id": r.get("source_id"),
            "is_void": bool(r.get("is_void")),
            "voided_at": str(r["voided_at"]) if r.get("voided_at") else None,
            "void_note": r.get("void_note") or "",
            "note": r.get("note") or "",
            "created_at": str(r["created_at"]) if r.get("created_at") else None,
        }
        for r in _portfolio_flow_rows()
    ]


def _portfolio_trades_payload(limit=1000):
    _ensure_portfolio_tables()
    rows = execute_query(
        """SELECT t.id, t.trade_date, t.stock_code, s.name, s.market, t.trade_type,
                  t.shares, t.price, t.amount, t.commission, t.stamp_tax, t.transfer_fee,
                  t.total_fee, t.cash_delta, t.shares_before, t.shares_after,
                  t.cost_price_before, t.cost_price_after, t.realized_profit, t.note,
                  t.is_void, t.voided_at, t.void_note
           FROM portfolio_trades t
           JOIN stocks s ON s.code = t.stock_code
           ORDER BY t.trade_date DESC, t.id DESC
           LIMIT %s""",
        (limit,),
    )
    result = []
    for r in rows:
        item = dict(r)
        item["trade_date"] = str(r["trade_date"])
        item["currency"] = _currency_for_market(r.get("market"))
        for field in ("shares", "price", "amount", "commission", "stamp_tax", "transfer_fee", "total_fee", "cash_delta", "shares_before", "shares_after"):
            item[field] = float(r[field])
        for field in ("cost_price_before", "cost_price_after", "realized_profit"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        item["is_void"] = bool(r.get("is_void"))
        item["voided_at"] = str(r["voided_at"]) if r.get("voided_at") else None
        item["void_note"] = r.get("void_note") or ""
        result.append(item)
    return result


def _portfolio_actions_payload(limit=100):
    _ensure_portfolio_tables()
    rows = execute_query(
        """SELECT a.id, a.action_date, a.stock_code, s.name, s.market, a.action_type,
                  a.cash_amount, a.shares, a.price, a.amount, a.cash_delta,
                  a.shares_before, a.shares_after, a.cost_price_before, a.cost_price_after, a.note,
                  a.is_void, a.voided_at, a.void_note
           FROM portfolio_corporate_actions a
           JOIN stocks s ON s.code = a.stock_code
           ORDER BY a.action_date DESC, a.id DESC
           LIMIT %s""",
        (limit,),
    )
    result = []
    for r in rows:
        item = dict(r)
        item["action_date"] = str(r["action_date"])
        item["currency"] = _currency_for_market(r.get("market"))
        for field in ("cash_amount", "shares", "price", "amount", "cash_delta", "shares_before", "shares_after"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        for field in ("cost_price_before", "cost_price_after"):
            item[field] = float(r[field]) if r.get(field) is not None else None
        item["is_void"] = bool(r.get("is_void"))
        item["voided_at"] = str(r["voided_at"]) if r.get("voided_at") else None
        item["void_note"] = r.get("void_note") or ""
        result.append(item)
    return result


def _void_linked_cash_flow(source_type, source_id, flow_source, flow_date, amount, code, void_note):
    rows = execute_query(
        """SELECT id, amount
           FROM portfolio_cash_flows
           WHERE is_void=0 AND source_type=%s AND source_id=%s
           LIMIT 1""",
        (source_type, source_id),
    )
    if not rows:
        rows = execute_query(
            """SELECT id, amount
               FROM portfolio_cash_flows
               WHERE is_void=0 AND flow_source=%s AND flow_date=%s
                 AND amount=%s AND (note LIKE %s OR note IS NULL OR note='')
               ORDER BY id DESC
               LIMIT 1""",
            (flow_source, flow_date, amount, f"%{code}%"),
        )
    if not rows:
        return Decimal("0")
    row = rows[0]
    execute_query(
        "UPDATE portfolio_cash_flows SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
        (void_note, row["id"]),
        fetch=False,
    )
    return _decimal_value(row["amount"])


def _portfolio_audit_payload():
    _ensure_portfolio_tables()
    issues = []
    current_cash = _decimal_value(_portfolio_cash_amount())
    rebuilt_cash = _portfolio_rebuilt_cash_amount()
    if not _decimal_equal(current_cash, rebuilt_cash, "0.01"):
        issues.append({
            "type": "cash",
            "message": f"现金与流水推导不一致，相差 {float(_quantize(current_cash - rebuilt_cash, '0.01')):.2f}",
            "current": float(_quantize(current_cash, "0.01")),
            "expected": float(_quantize(rebuilt_cash, "0.01")),
        })

    rows = execute_query(
        """SELECT stock_code, shares_after, cost_price_after
           FROM (
             SELECT stock_code, shares_after, cost_price_after,
                    ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY d DESC, sort_id DESC) AS rn
             FROM (
               SELECT stock_code, shares_after, cost_price_after, trade_date AS d, id AS sort_id
               FROM portfolio_trades WHERE is_void=0
               UNION ALL
               SELECT stock_code, shares_after, cost_price_after, action_date AS d, id AS sort_id
               FROM portfolio_corporate_actions WHERE is_void=0
             ) x
           ) y
           WHERE rn=1"""
    )
    for row in rows:
        position_rows = execute_query(
            "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
            (row["stock_code"],),
        )
        if not position_rows:
            issues.append({"type": "position", "code": row["stock_code"], "message": "账本有记录但当前持仓缺失"})
            continue
        pos = position_rows[0]
        if (
            not _decimal_equal(pos.get("shares"), row.get("shares_after"))
            or not _decimal_equal(pos.get("cost_price"), row.get("cost_price_after"))
        ):
            issues.append({
                "type": "position",
                "code": row["stock_code"],
                "message": "当前持仓与账本回放结果不一致",
                "current_shares": float(_quantize(pos.get("shares"))),
                "expected_shares": float(_quantize(row.get("shares_after"))),
                "current_cost": float(_quantize(pos.get("cost_price"))) if pos.get("cost_price") is not None else None,
                "expected_cost": float(_quantize(row.get("cost_price_after"))) if row.get("cost_price_after") is not None else None,
            })

    return {
        "ok": not issues,
        "issues": issues,
        "cash": {
            "current": float(_quantize(current_cash, "0.01")),
            "expected": float(_quantize(rebuilt_cash, "0.01")),
            "base_amount": float(_quantize(_portfolio_cash_base_amount(), "0.01")),
        },
    }


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
    ident = _normalize_stock_code(identifier)
    if not ident:
        return None
    if re.fullmatch(r"\d{5,6}", ident):
        rows = execute_query(
            "SELECT code, name, market FROM stocks WHERE code=%s LIMIT 1",
            (ident,),
        )
        if rows:
            return rows[0]
        if re.fullmatch(r"\d{5}", ident):
            hk = _lookup_hk_stock_info(ident)
            if hk:
                Stock.add(code=hk["code"], name=hk["name"], market=hk["market"])
                return hk

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
        """SELECT p.id, p.stock_code, p.shares, p.cost_price, p.custom_dividend_per_share,
                  s.name, s.market, s.industry
           FROM portfolio_positions p
           JOIN stocks s ON s.code = p.stock_code
           ORDER BY p.updated_at DESC, p.id DESC"""
    )
    _fill_missing_stock_industries(rows)
    positions = []
    if not rows:
        return {
            "positions": [],
            "fee_config": _portfolio_fee_config_payload(),
            "summary": {
                "total_market_value": 0,
                "cash_amount": round(cash_amount, 2),
                "total_asset_value": round(cash_amount, 2),
                "cash_allocation_pct": 100.0 if cash_amount > 0 else 0,
                "total_cost_value": 0,
                "unrealized_profit": None,
                "unrealized_profit_pct": None,
                "expected_dividend": 0,
                "count": 0,
                "industry_allocations": [],
            },
        }

    stock_refs = [{"code": r["stock_code"], "market": r["market"]} for r in rows]
    quotes = _fetch_realtime_quotes(stock_refs)
    prices = {
        code: quote.get("price")
        for code, quote in quotes.items()
        if quote.get("price") is not None
    }
    dividends = _latest_dividend_per_share([r["stock_code"] for r in rows])
    exchange_rates = {}
    total_market_value = 0.0
    total_cost_value = 0.0
    total_costed_market_value = 0.0
    expected_dividend = 0.0
    total_day_change_value = 0.0
    industry_values = {}

    for r in rows:
        code = r["stock_code"]
        shares = float(r["shares"])
        cost_price = float(r["cost_price"]) if r.get("cost_price") is not None else None
        price = prices.get(code)
        quote = quotes.get(code, {})
        currency = _currency_for_market(r.get("market"))
        fx = exchange_rates.get(currency)
        if fx is None:
            fx = _exchange_rate_to_cny(currency)
            exchange_rates[currency] = fx
        fx_rate = float(fx["rate"]) if fx and fx.get("rate") is not None else None
        div = dividends.get(code, {})
        custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
        dividend_per_share = custom_dividend if custom_dividend is not None else div.get("dividend_per_share")
        original_market_value = shares * price if price is not None else None
        original_day_change = shares * quote.get("day_change") if quote.get("day_change") is not None else None
        day_change_value = original_day_change * fx_rate if original_day_change is not None and fx_rate is not None else None
        market_value = original_market_value * fx_rate if original_market_value is not None and fx_rate is not None else None
        original_cost_value = shares * cost_price if cost_price is not None else None
        cost_value = original_cost_value * fx_rate if original_cost_value is not None and fx_rate is not None else None
        unrealized_profit = market_value - cost_value if market_value is not None and cost_value is not None else None
        unrealized_profit_pct = unrealized_profit / cost_value * 100 if unrealized_profit is not None and cost_value and cost_value > 0 else None
        original_dividend_amount = shares * dividend_per_share if dividend_per_share is not None else None
        dividend_amount = original_dividend_amount * fx_rate if original_dividend_amount is not None and fx_rate is not None else None
        if market_value is not None:
            total_market_value += market_value
            industry = r.get("industry") or "未分类"
            industry_values[industry] = industry_values.get(industry, 0.0) + market_value
        if day_change_value is not None:
            total_day_change_value += day_change_value
        if cost_value is not None:
            total_cost_value += cost_value
            if market_value is not None:
                total_costed_market_value += market_value
        if dividend_amount is not None:
            expected_dividend += dividend_amount
        positions.append({
            "id": r["id"],
            "code": code,
            "name": r["name"],
            "market": r["market"],
            "industry": r.get("industry"),
            "shares": shares,
            "cost_price": round(cost_price, 4) if cost_price is not None else None,
            "cost_price_currency": currency,
            "price": round(price, 2) if price is not None else None,
            "day_change": round(float(quote.get("day_change")), 2) if quote.get("day_change") is not None else None,
            "day_change_pct": round(float(quote.get("day_change_pct")), 2) if quote.get("day_change_pct") is not None else None,
            "day_change_value": round(day_change_value, 2) if day_change_value is not None else None,
            "price_currency": currency,
            "fx_rate_to_cny": round(fx_rate, 6) if fx_rate is not None else None,
            "fx_rate_date": fx.get("date") if fx else None,
            "fx_rate_source": fx.get("source") if fx else None,
            "original_market_value": round(original_market_value, 2) if original_market_value is not None else None,
            "original_market_value_currency": currency,
            "market_value": round(market_value, 2) if market_value is not None else None,
            "market_value_currency": "CNY",
            "original_cost_value": round(original_cost_value, 2) if original_cost_value is not None else None,
            "original_cost_value_currency": currency,
            "cost_value": round(cost_value, 2) if cost_value is not None else None,
            "cost_value_currency": "CNY",
            "unrealized_profit": round(unrealized_profit, 2) if unrealized_profit is not None else None,
            "unrealized_profit_pct": round(unrealized_profit_pct, 2) if unrealized_profit_pct is not None else None,
            "dividend_per_share": round(dividend_per_share, 4) if dividend_per_share is not None else None,
            "dividend_year": div.get("fiscal_year"),
            "auto_dividend_per_share": round(div.get("dividend_per_share"), 4) if div.get("dividend_per_share") is not None else None,
            "custom_dividend_per_share": round(custom_dividend, 4) if custom_dividend is not None else None,
            "dividend_source": "custom" if custom_dividend is not None else "auto",
            "original_expected_dividend": round(original_dividend_amount, 2) if original_dividend_amount is not None else None,
            "original_expected_dividend_currency": currency,
            "expected_dividend": round(dividend_amount, 2) if dividend_amount is not None else None,
            "expected_dividend_currency": "CNY",
        })

    total_asset_value = total_market_value + cash_amount
    for p in positions:
        value = p.get("market_value")
        p["allocation_pct"] = round(value / total_asset_value * 100, 2) if value is not None and total_asset_value > 0 else None
    positions.sort(key=lambda p: p.get("allocation_pct") or 0, reverse=True)

    industry_allocations = [
        {
            "industry": industry,
            "market_value": round(value, 2),
            "allocation_pct": round(value / total_market_value * 100, 2) if total_market_value > 0 else 0,
        }
        for industry, value in sorted(industry_values.items(), key=lambda item: item[1], reverse=True)
    ]

    return {
        "positions": positions,
        "fee_config": _portfolio_fee_config_payload(),
        "summary": {
            "total_market_value": round(total_market_value, 2),
            "cash_amount": round(cash_amount, 2),
            "total_asset_value": round(total_asset_value, 2),
            "cash_allocation_pct": round(cash_amount / total_asset_value * 100, 2) if total_asset_value > 0 else 0,
            "total_cost_value": round(total_cost_value, 2),
            "unrealized_profit": round(total_costed_market_value - total_cost_value, 2) if total_cost_value > 0 else None,
            "unrealized_profit_pct": round((total_costed_market_value - total_cost_value) / total_cost_value * 100, 2) if total_cost_value > 0 else None,
            "expected_dividend": round(expected_dividend, 2),
            "day_change_value": round(total_day_change_value, 2),
            "day_change_pct": round(total_day_change_value / total_market_value * 100, 2) if total_market_value > 0 else None,
            "count": len(positions),
            "currency": "CNY",
            "exchange_rates": {
                f"{currency}_CNY": {
                    "rate": round(info["rate"], 6) if info and info.get("rate") is not None else None,
                    "date": info.get("date") if info else None,
                    "source": info.get("source") if info else None,
                    "cached": bool(info.get("cached")) if info else False,
                    "stale": bool(info.get("stale")) if info else False,
                }
                for currency, info in exchange_rates.items()
                if currency != "CNY"
            },
            "industry_allocations": industry_allocations[:8],
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


@app.route("/api/portfolio/fee-config", methods=["GET"])
def api_portfolio_fee_config():
    return jsonify(_portfolio_fee_config_payload())


@app.route("/api/portfolio/fee-config", methods=["PUT"])
def api_portfolio_update_fee_config():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    values = {}
    for key in ("commission_rate", "min_commission", "stamp_tax_rate", "transfer_fee_rate"):
        try:
            value = _decimal_value(data.get(key))
        except Exception:
            return jsonify({"error": "费率配置必须是数字"}), 400
        if value < 0:
            return jsonify({"error": "费率配置不能小于 0"}), 400
        values[key] = value
    execute_query(
        """UPDATE portfolio_fee_config
           SET commission_rate=%s, min_commission=%s, stamp_tax_rate=%s, transfer_fee_rate=%s
           WHERE id=1""",
        (
            values["commission_rate"],
            values["min_commission"],
            values["stamp_tax_rate"],
            values["transfer_fee_rate"],
        ),
        fetch=False,
    )
    return jsonify({"ok": True, **_portfolio_fee_config_payload()})


@app.route("/api/portfolio/positions", methods=["POST"])
def api_portfolio_save_position():
    return jsonify({"error": "持仓只能通过买入/卖出交易变动，不能直接录入或修改"}), 400


@app.route("/api/portfolio/positions/<code>", methods=["GET"])
def api_portfolio_position_get(code):
    _ensure_portfolio_tables()
    rows = execute_query(
        """SELECT p.stock_code, p.shares, p.cost_price, p.custom_dividend_per_share,
                  s.name, s.market, s.industry
           FROM portfolio_positions p
           JOIN stocks s ON s.code = p.stock_code
           WHERE p.stock_code=%s
           LIMIT 1""",
        (code,),
    )
    if not rows:
        return jsonify({"ok": True, "held": False, "code": code})

    r = rows[0]
    shares = float(r["shares"])
    dividends = _latest_dividend_per_share([code]).get(code, {})
    custom_dividend = float(r["custom_dividend_per_share"]) if r.get("custom_dividend_per_share") is not None else None
    auto_dividend = dividends.get("dividend_per_share")
    dividend_per_share = custom_dividend if custom_dividend is not None else auto_dividend
    return jsonify({
        "ok": True,
        "held": True,
        "code": r["stock_code"],
        "name": r["name"],
        "market": r["market"],
        "industry": r.get("industry"),
        "shares": shares,
        "cost_price": round(float(r["cost_price"]), 4) if r.get("cost_price") is not None else None,
        "cost_price_currency": _currency_for_market(r.get("market")),
        "custom_dividend_per_share": round(custom_dividend, 4) if custom_dividend is not None else None,
        "auto_dividend_per_share": round(auto_dividend, 4) if auto_dividend is not None else None,
        "dividend_per_share": round(dividend_per_share, 4) if dividend_per_share is not None else None,
        "dividend_year": dividends.get("fiscal_year"),
        "dividend_source": "custom" if custom_dividend is not None else "auto",
    })


@app.route("/api/portfolio/positions/<code>", methods=["DELETE"])
def api_portfolio_delete_position(code):
    return jsonify({"error": "持仓只能通过买入/卖出交易变动，不能直接删除"}), 400


@app.route("/api/portfolio/trades", methods=["GET"])
def api_portfolio_trades():
    return jsonify(_portfolio_trades_payload())


@app.route("/api/portfolio/actions", methods=["GET"])
def api_portfolio_actions():
    return jsonify(_portfolio_actions_payload())


@app.route("/api/portfolio/audit", methods=["GET"])
def api_portfolio_audit():
    return jsonify(_portfolio_audit_payload())


@app.route("/api/portfolio/rebuild", methods=["POST"])
def api_portfolio_rebuild():
    _ensure_portfolio_tables()
    _sync_portfolio_cost_basis_from_trades()
    rebuilt_cash = _portfolio_rebuilt_cash_amount()
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (_quantize(rebuilt_cash, "0.01"),),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    state["audit"] = _portfolio_audit_payload()
    state["trades"] = _portfolio_trades_payload()
    state["actions"] = _portfolio_actions_payload()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/trades", methods=["POST"])
def api_portfolio_add_trade():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    trade_date = str(data.get("trade_date") or datetime.now().date()).strip()
    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "日期格式必须是 YYYY-MM-DD"}), 400

    trade_type = str(data.get("trade_type") or "").strip().lower()
    if trade_type not in ("buy", "sell"):
        return jsonify({"error": "交易方向必须是买入或卖出"}), 400

    stock = _resolve_portfolio_stock(str(data.get("code", data.get("identifier", ""))).strip())
    if not stock:
        return jsonify({"error": "未找到匹配的股票，请输入代码或更准确的名称"}), 404
    code = stock["code"]

    try:
        shares = float(data.get("shares"))
    except (TypeError, ValueError):
        return jsonify({"error": "交易股数必须是数字"}), 400
    if shares <= 0:
        return jsonify({"error": "交易股数必须大于 0"}), 400

    try:
        price = float(data.get("price"))
    except (TypeError, ValueError):
        return jsonify({"error": "成交价必须是数字"}), 400
    if price <= 0:
        return jsonify({"error": "成交价必须大于 0"}), 400

    note = str(data.get("note") or "").strip()[:255]
    position_rows = execute_query(
        "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
        (code,),
    )
    old_shares = float(position_rows[0]["shares"]) if position_rows else 0.0
    old_cost = float(position_rows[0]["cost_price"]) if position_rows and position_rows[0].get("cost_price") is not None else None

    amount = shares * price
    amount_dec = _quantize(amount, "0.01")
    fees = _calculate_portfolio_trade_fees(amount_dec, trade_type, stock.get("market"))
    total_fee = fees["total_fee"]
    cash_delta_dec = -(amount_dec + total_fee) if trade_type == "buy" else amount_dec - total_fee
    cash_delta = float(cash_delta_dec)
    cash_amount = _portfolio_cash_amount()
    new_cash = cash_amount + cash_delta
    if new_cash < 0:
        return jsonify({"error": "现金不足，无法买入"}), 400

    realized_profit = None
    if trade_type == "buy":
        if old_shares > 0 and old_cost is None:
            return jsonify({"error": "这只股票已有持仓但缺少历史成本，无法继续自动计算成本价"}), 400
        new_shares = old_shares + shares
        buy_cost = float(amount_dec + total_fee)
        new_cost = ((old_shares * old_cost) + buy_cost) / new_shares if old_shares > 0 else buy_cost / shares
        execute_query(
            """INSERT INTO portfolio_positions (stock_code, shares, cost_price)
               VALUES (%s, %s, %s)
               ON DUPLICATE KEY UPDATE shares=VALUES(shares), cost_price=VALUES(cost_price), updated_at=CURRENT_TIMESTAMP""",
            (code, round(new_shares, 4), round(new_cost, 4)),
            fetch=False,
        )
    else:
        if old_shares <= 0:
            return jsonify({"error": "当前没有这只股票的持仓，无法卖出"}), 400
        if shares > old_shares:
            return jsonify({"error": f"卖出股数不能超过当前持仓 {old_shares:g} 股"}), 400
        new_shares = old_shares - shares
        sell_proceeds = float(amount_dec - total_fee)
        realized_profit = sell_proceeds - (old_cost * shares) if old_cost is not None else None
        new_cost = ((old_shares * old_cost) - sell_proceeds) / new_shares if new_shares > 0 and old_cost is not None else None
        if new_shares > 0:
            execute_query(
                "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
                (round(new_shares, 4), round(new_cost, 4) if new_cost is not None else None, code),
                fetch=False,
            )
        else:
            execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

    trade_id = _execute_insert_id(
        """INSERT INTO portfolio_trades
           (trade_date, stock_code, trade_type, shares, price, amount,
            commission, stamp_tax, transfer_fee, total_fee, cash_delta,
            shares_before, shares_after, cost_price_before, cost_price_after, realized_profit, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            trade_date,
            code,
            trade_type,
            round(shares, 4),
            round(price, 4),
            round(amount, 2),
            fees["commission"],
            fees["stamp_tax"],
            fees["transfer_fee"],
            fees["total_fee"],
            cash_delta_dec,
            round(old_shares, 4),
            round(new_shares, 4),
            round(old_cost, 4) if old_cost is not None else None,
            round(new_cost, 4) if new_cost is not None else None,
            round(realized_profit, 2) if realized_profit is not None else None,
            note,
        ),
    )
    flow_note = note or f"{stock['name']}({code}) {'买入' if trade_type == 'buy' else '卖出'}"
    execute_query(
        """INSERT INTO portfolio_cash_flows
           (flow_date, amount, flow_source, source_type, source_id, note)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (trade_date, cash_delta_dec, "trade", "trade", trade_id, flow_note[:255]),
        fetch=False,
    )
    execute_query(
        "UPDATE portfolio_cash SET amount=%s WHERE id=1",
        (round(new_cash, 2),),
        fetch=False,
    )
    state = _save_portfolio_snapshot()
    state["trades"] = _portfolio_trades_payload()
    state["actions"] = _portfolio_actions_payload()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/trades/<int:trade_id>/void", methods=["POST"])
def api_portfolio_void_trade(trade_id):
    _ensure_portfolio_tables()
    data = request.get_json(silent=True) or {}
    void_note = str(data.get("void_note") or "作废交易").strip()[:255]
    rows = execute_query(
        """SELECT id, trade_date, stock_code, cash_delta, is_void
           FROM portfolio_trades
           WHERE id=%s
           LIMIT 1""",
        (trade_id,),
    )
    if not rows:
        return jsonify({"error": "未找到这笔交易"}), 404
    row = rows[0]
    if row.get("is_void"):
        return jsonify({"error": "这笔交易已作废"}), 400
    execute_query(
        "UPDATE portfolio_trades SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
        (void_note, trade_id),
        fetch=False,
    )
    voided_flow_amount = _void_linked_cash_flow(
        "trade",
        trade_id,
        "trade",
        row["trade_date"],
        row["cash_delta"],
        row["stock_code"],
        void_note,
    )
    if voided_flow_amount != 0:
        current_cash = _decimal_value(_portfolio_cash_amount())
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (_quantize(current_cash - voided_flow_amount, "0.01"),),
            fetch=False,
        )
    _sync_portfolio_cost_basis_from_trades()
    state = _save_portfolio_snapshot()
    state["audit"] = _portfolio_audit_payload()
    state["trades"] = _portfolio_trades_payload()
    state["actions"] = _portfolio_actions_payload()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/actions", methods=["POST"])
def api_portfolio_add_corporate_action():
    _ensure_portfolio_tables()
    data = request.get_json(force=True)
    action_date = str(data.get("action_date") or datetime.now().date()).strip()
    try:
        datetime.strptime(action_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "日期格式必须是 YYYY-MM-DD"}), 400

    action_type = str(data.get("action_type") or "").strip().lower()
    if action_type not in ("cash_dividend", "bonus_share", "rights_issue"):
        return jsonify({"error": "权益类型必须是现金分红、送股/转增或配股"}), 400

    stock = _resolve_portfolio_stock(str(data.get("code", data.get("identifier", ""))).strip())
    if not stock:
        return jsonify({"error": "未找到匹配的股票，请输入代码或更准确的名称"}), 404
    code = stock["code"]

    position_rows = execute_query(
        "SELECT shares, cost_price FROM portfolio_positions WHERE stock_code=%s LIMIT 1",
        (code,),
    )
    if not position_rows:
        return jsonify({"error": "当前没有这只股票的持仓，无法记录权益事件"}), 400
    old_shares = _decimal_value(position_rows[0]["shares"])
    old_cost = _decimal_value(position_rows[0]["cost_price"]) if position_rows[0].get("cost_price") is not None else None
    if old_shares <= 0 or old_cost is None:
        return jsonify({"error": "这只股票缺少有效持仓或成本，无法记录权益事件"}), 400

    note = str(data.get("note") or "").strip()[:255]
    cash_amount = Decimal("0.00")
    action_shares = Decimal("0.0000")
    price = None
    amount = Decimal("0.00")
    cash_delta = Decimal("0.00")
    new_shares = old_shares
    new_cost = old_cost

    if action_type == "cash_dividend":
        raw_cash = data.get("cash_amount")
        if raw_cash in (None, ""):
            try:
                cash_amount = _decimal_value(data.get("dividend_per_share")) * old_shares
            except Exception:
                return jsonify({"error": "现金分红金额必须是数字"}), 400
        else:
            try:
                cash_amount = _decimal_value(raw_cash)
            except Exception:
                return jsonify({"error": "现金分红金额必须是数字"}), 400
        if cash_amount <= 0:
            return jsonify({"error": "现金分红金额必须大于 0"}), 400
        cash_amount = _quantize(cash_amount, "0.01")
        amount = cash_amount
        cash_delta = cash_amount
        new_cost = ((old_shares * old_cost) - cash_amount) / old_shares
    elif action_type == "bonus_share":
        try:
            action_shares = _decimal_value(data.get("shares"))
        except Exception:
            return jsonify({"error": "送股/转增股数必须是数字"}), 400
        if action_shares <= 0:
            return jsonify({"error": "送股/转增股数必须大于 0"}), 400
        new_shares = old_shares + action_shares
        new_cost = (old_shares * old_cost) / new_shares
    else:
        try:
            action_shares = _decimal_value(data.get("shares"))
            price = _decimal_value(data.get("price"))
        except Exception:
            return jsonify({"error": "配股股数和价格必须是数字"}), 400
        if action_shares <= 0:
            return jsonify({"error": "配股股数必须大于 0"}), 400
        if price < 0:
            return jsonify({"error": "配股价格不能小于 0"}), 400
        amount = _quantize(action_shares * price, "0.01")
        cash_delta = -amount
        cash_amount_now = _decimal_value(_portfolio_cash_amount())
        if cash_amount_now + cash_delta < 0:
            return jsonify({"error": "现金不足，无法记录配股"}), 400
        new_shares = old_shares + action_shares
        new_cost = ((old_shares * old_cost) + amount) / new_shares

    action_id = _execute_insert_id(
        """INSERT INTO portfolio_corporate_actions
           (action_date, stock_code, action_type, cash_amount, shares, price, amount, cash_delta,
            shares_before, shares_after, cost_price_before, cost_price_after, note)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            action_date,
            code,
            action_type,
            cash_amount,
            _quantize(action_shares),
            _quantize(price) if price is not None else None,
            amount,
            cash_delta,
            _quantize(old_shares),
            _quantize(new_shares),
            _quantize(old_cost),
            _quantize(new_cost) if new_cost is not None else None,
            note,
        ),
    )
    if new_shares > 0:
        execute_query(
            "UPDATE portfolio_positions SET shares=%s, cost_price=%s, updated_at=CURRENT_TIMESTAMP WHERE stock_code=%s",
            (_quantize(new_shares), _quantize(new_cost) if new_cost is not None else None, code),
            fetch=False,
        )
    else:
        execute_query("DELETE FROM portfolio_positions WHERE stock_code=%s", (code,), fetch=False)

    if cash_delta != 0:
        cash_amount_now = _decimal_value(_portfolio_cash_amount())
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (_quantize(cash_amount_now + cash_delta, "0.01"),),
            fetch=False,
        )
        flow_label = {"cash_dividend": "分红到账", "rights_issue": "配股扣款"}.get(action_type, "权益现金")
        flow_note = note or f"{stock['name']}({code}) {flow_label}"
        execute_query(
            """INSERT INTO portfolio_cash_flows
               (flow_date, amount, flow_source, source_type, source_id, note)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (action_date, _quantize(cash_delta, "0.01"), "action", "action", action_id, flow_note[:255]),
            fetch=False,
        )

    state = _save_portfolio_snapshot()
    state["trades"] = _portfolio_trades_payload()
    state["actions"] = _portfolio_actions_payload()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


@app.route("/api/portfolio/actions/<int:action_id>/void", methods=["POST"])
def api_portfolio_void_corporate_action(action_id):
    _ensure_portfolio_tables()
    data = request.get_json(silent=True) or {}
    void_note = str(data.get("void_note") or "作废权益事件").strip()[:255]
    rows = execute_query(
        """SELECT id, action_date, stock_code, cash_delta, is_void
           FROM portfolio_corporate_actions
           WHERE id=%s
           LIMIT 1""",
        (action_id,),
    )
    if not rows:
        return jsonify({"error": "未找到这笔权益记录"}), 404
    row = rows[0]
    if row.get("is_void"):
        return jsonify({"error": "这笔权益记录已作废"}), 400
    execute_query(
        "UPDATE portfolio_corporate_actions SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note=%s WHERE id=%s",
        (void_note, action_id),
        fetch=False,
    )
    voided_flow_amount = _void_linked_cash_flow(
        "action",
        action_id,
        "action",
        row["action_date"],
        row["cash_delta"],
        row["stock_code"],
        void_note,
    )
    if voided_flow_amount != 0:
        current_cash = _decimal_value(_portfolio_cash_amount())
        execute_query(
            "UPDATE portfolio_cash SET amount=%s WHERE id=1",
            (_quantize(current_cash - voided_flow_amount, "0.01"),),
            fetch=False,
        )
    _sync_portfolio_cost_basis_from_trades()
    state = _save_portfolio_snapshot()
    state["audit"] = _portfolio_audit_payload()
    state["trades"] = _portfolio_trades_payload()
    state["actions"] = _portfolio_actions_payload()
    state["flows"] = _portfolio_flows_payload()
    return jsonify({"ok": True, **state})


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
    return jsonify({"error": "现金只能通过资金流水入金/出金变动"}), 400


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
        "INSERT INTO portfolio_cash_flows (flow_date, amount, flow_source, note) VALUES (%s, %s, %s, %s)",
        (flow_date, round(amount, 2), "external", note),
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
    rows = execute_query("SELECT amount, flow_source, is_void FROM portfolio_cash_flows WHERE id=%s", (flow_id,))
    if not rows:
        return jsonify({"error": "未找到这笔资金流水"}), 404
    if rows[0].get("is_void"):
        return jsonify({"error": "这笔资金流水已作废"}), 400
    if rows[0].get("flow_source") in ("trade", "action"):
        return jsonify({"error": "交易或权益产生的资金流水不能单独作废，请作废原始记录"}), 400
    amount = float(rows[0]["amount"])
    cash_amount = _portfolio_cash_amount()
    new_cash = cash_amount - amount
    if new_cash < 0:
        return jsonify({"error": "作废后现金会小于 0，无法作废"}), 400
    execute_query(
        "UPDATE portfolio_cash_flows SET is_void=1, voided_at=CURRENT_TIMESTAMP, void_note='作废资金流水' WHERE id=%s",
        (flow_id,),
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
    if request.args.get("live") == "1":
        summary = _portfolio_current_state()["summary"]
        today = datetime.now().date().isoformat()
        live_row = {
            "snapshot_date": today,
            "total_market_value": summary["total_market_value"],
            "expected_dividend": summary["expected_dividend"],
            "cash_amount": summary["cash_amount"],
            "total_asset_value": summary["total_asset_value"],
        }
        rows = [r for r in rows if str(r["snapshot_date"]) != today]
        rows.append(live_row)
    flow_rows = execute_query(
        """SELECT flow_date,
                  SUM(amount) AS net_flow,
                  SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) AS flow_in,
                  SUM(CASE WHEN amount < 0 THEN -amount ELSE 0 END) AS flow_out
           FROM portfolio_cash_flows
           WHERE flow_source='external' AND is_void=0
           GROUP BY flow_date"""
    )
    flow_by_date = {
        str(r["flow_date"]): {
            "net": float(r["net_flow"] or 0),
            "in": float(r["flow_in"] or 0),
            "out": float(r["flow_out"] or 0),
        }
        for r in flow_rows
    }
    nav_index = None
    prev_value = None
    cumulative_in = 0.0
    cumulative_out = 0.0
    cumulative_return = 0.0
    result = []
    for r in rows:
        date_str = str(r["snapshot_date"])
        value = float(r.get("total_asset_value") or r["total_market_value"])
        flow = flow_by_date.get(date_str, {"net": 0.0, "in": 0.0, "out": 0.0})
        net_flow = flow["net"]
        cumulative_in += flow["in"]
        cumulative_out += flow["out"]
        daily_return = 0.0
        if nav_index is None:
            nav_index = 1.0 if value > 0 else None
        elif prev_value and prev_value > 0:
            adjusted_value = max(0.0, value - net_flow)
            daily_return = value - prev_value - net_flow
            cumulative_return += daily_return
            nav_index = nav_index * (adjusted_value / prev_value)
        result.append({
            "date": date_str,
            "total_market_value": round(value, 2),
            "stock_market_value": round(float(r["total_market_value"]), 2),
            "cash_amount": round(float(r.get("cash_amount") or 0), 2),
            "total_asset_value": round(value, 2),
            "net_flow": round(net_flow, 2),
            "flow_in": round(flow["in"], 2),
            "flow_out": round(flow["out"], 2),
            "cumulative_in": round(cumulative_in, 2),
            "cumulative_out": round(cumulative_out, 2),
            "daily_return": round(daily_return, 2),
            "cumulative_return": round(cumulative_return, 2),
            "expected_dividend": round(float(r["expected_dividend"]), 2),
            "nav_index": round(nav_index, 4) if nav_index is not None else None,
        })
        prev_value = value
    return jsonify(result)


@app.route("/api/stock/<code>/fundamental-dashboard")
def api_stock_fundamental_dashboard(code):
    """股票详情页基本面驾驶舱。"""

    def to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def round_or_none(value, ndigits=2):
        return round(value, ndigits) if value is not None else None

    def avg(values):
        values = [v for v in values if v is not None]
        return sum(values) / len(values) if values else None

    def pct_change(cur, prev):
        if cur is None or prev in (None, 0):
            return None
        return (cur - prev) / abs(prev) * 100

    def cagr(old, new, years):
        if old is None or new is None or years <= 0 or old <= 0 or new <= 0:
            return None
        return ((new / old) ** (1 / years) - 1) * 100

    def clamp_score(score):
        return max(0, min(100, round(score)))

    def status_from_score(score):
        if score is None:
            return {"text": "数据不足", "level": "neutral"}
        if score >= 80:
            return {"text": "优秀", "level": "good"}
        if score >= 65:
            return {"text": "良好", "level": "good"}
        if score >= 45:
            return {"text": "一般", "level": "warn"}
        return {"text": "偏弱", "level": "bad"}

    def score_high(value, excellent, good, ok):
        if value is None:
            return 0
        if value >= excellent:
            return 100
        if value >= good:
            return 75
        if value >= ok:
            return 50
        if value >= 0:
            return 25
        return 0

    def score_low(value, excellent, good, ok):
        if value is None:
            return 0
        if value <= excellent:
            return 100
        if value <= good:
            return 75
        if value <= ok:
            return 50
        return 20

    def verdict_high(value, excellent, good, ok):
        if value is None:
            return "neutral"
        if value >= good:
            return "good"
        if value >= ok:
            return "warn"
        return "bad"

    def verdict_low(value, excellent, good, ok):
        if value is None:
            return "neutral"
        if value <= good:
            return "good"
        if value <= ok:
            return "warn"
        return "bad"

    def metric(name, value, unit="", verdict="neutral", note=""):
        return {
            "name": name,
            "value": round_or_none(value),
            "unit": unit,
            "verdict": verdict,
            "note": note,
        }

    try:
        stock_rows = execute_query(
            "SELECT code, name, market, industry, pe_ttm, dividend_yield FROM stocks WHERE code=%s",
            (code,),
        )
        if not stock_rows:
            return jsonify({"error": "未找到该股票"}), 404

        stock = dict(stock_rows[0])
        enriched = _enrich_stock_list_metrics([dict(stock)], include_ytd=False)
        market_metrics = enriched[0] if enriched else stock

        rows = execute_query(
            """SELECT fiscal_year, total_revenue, operate_profit, parent_profit, deducted_profit,
                      operate_cashflow, roe, deducted_roe, roic, total_assets, total_equity,
                      total_shares, basic_eps, debt_ratio, interest_bearing_debt_ratio
               FROM custom_financials
               WHERE stock_code=%s AND report_period='FY'
               ORDER BY fiscal_year ASC""",
            (code,),
        )

        if not rows:
            return jsonify({
                "stock": {"code": stock["code"], "name": stock["name"], "industry": stock.get("industry")},
                "summary": [],
                "groups": [],
                "signals": [],
                "message": "暂无年报财务数据，请先更新财报数据。",
            })

        data = []
        for r in rows:
            item = {"fiscal_year": int(r["fiscal_year"])}
            for key in [
                "total_revenue", "operate_profit", "parent_profit", "deducted_profit",
                "operate_cashflow", "roe", "deducted_roe", "roic", "total_assets",
                "total_equity", "total_shares", "basic_eps", "debt_ratio",
                "interest_bearing_debt_ratio",
            ]:
                item[key] = to_float(r.get(key))
            revenue = item["total_revenue"]
            parent_profit = item["parent_profit"]
            operate_profit = item["operate_profit"]
            operate_cashflow = item["operate_cashflow"]
            item["core_profit_rate"] = operate_profit / revenue * 100 if revenue else None
            item["net_profit_rate"] = parent_profit / revenue * 100 if revenue else None
            item["cashflow_to_profit"] = (
                operate_cashflow / parent_profit * 100
                if parent_profit and parent_profit > 0 and operate_cashflow is not None else None
            )
            data.append(item)

        latest = data[-1]
        prev = data[-2] if len(data) >= 2 else None
        recent = data[-5:]
        earliest = data[0]
        year_span = latest["fiscal_year"] - earliest["fiscal_year"]

        revenue_cagr = cagr(earliest["total_revenue"], latest["total_revenue"], year_span)
        profit_cagr = cagr(earliest["parent_profit"], latest["parent_profit"], year_span)
        revenue_yoy = pct_change(latest["total_revenue"], prev["total_revenue"] if prev else None)
        profit_yoy = pct_change(latest["parent_profit"], prev["parent_profit"] if prev else None)
        roe_avg_5y = avg([r["roe"] for r in recent])
        roic_avg_5y = avg([r["roic"] for r in recent])
        cf_profit_avg_5y = avg([r["cashflow_to_profit"] for r in recent])
        positive_profit_years = sum(1 for r in recent if (r["parent_profit"] or 0) > 0)
        positive_ocf_years = sum(1 for r in recent if (r["operate_cashflow"] or 0) > 0)

        balance = execute_query(
            """SELECT parent_equity, goodwill
               FROM balance_sheets
               WHERE stock_code=%s AND parent_equity IS NOT NULL
               ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
               LIMIT 1""",
            (code,),
        )
        parent_equity = to_float(balance[0]["parent_equity"]) if balance else latest.get("total_equity")
        goodwill = to_float(balance[0]["goodwill"]) if balance and balance[0].get("goodwill") is not None else 0
        goodwill_to_equity = goodwill / parent_equity * 100 if parent_equity and parent_equity > 0 else None

        pe_ttm = to_float(market_metrics.get("pe_ttm"))
        dividend_yield = to_float(market_metrics.get("dividend_yield"))
        pb_ex_goodwill = to_float(market_metrics.get("pb_ex_goodwill"))
        reasonable_discount = to_float(market_metrics.get("reasonable_discount"))
        price = to_float(market_metrics.get("price"))
        reasonable_price = to_float(market_metrics.get("reasonable_price"))

        quality_score = clamp_score(
            score_high(roe_avg_5y, 20, 15, 8) * 0.38
            + score_high(roic_avg_5y, 15, 10, 6) * 0.28
            + score_high(latest.get("net_profit_rate"), 20, 10, 4) * 0.18
            + (positive_profit_years / max(1, len(recent)) * 100) * 0.16
        )
        growth_score = clamp_score(
            score_high(revenue_cagr, 15, 8, 0) * 0.32
            + score_high(profit_cagr, 15, 8, 0) * 0.42
            + score_high(revenue_yoy, 12, 5, 0) * 0.13
            + score_high(profit_yoy, 12, 5, 0) * 0.13
        )
        cashflow_score = clamp_score(
            score_high(cf_profit_avg_5y, 120, 90, 60) * 0.55
            + score_high(latest.get("cashflow_to_profit"), 120, 90, 60) * 0.25
            + (positive_ocf_years / max(1, len(recent)) * 100) * 0.20
        )
        balance_score = clamp_score(
            score_low(latest.get("debt_ratio"), 35, 55, 70) * 0.55
            + score_low(latest.get("interest_bearing_debt_ratio"), 15, 30, 45) * 0.25
            + score_low(goodwill_to_equity, 5, 15, 30) * 0.20
        )

        weighted_value_score = 0
        weight_sum = 0
        for value, weight in [
            (score_low(reasonable_discount, -25, 0, 35), 0.45 if reasonable_discount is not None else 0),
            (score_low(pe_ttm, 10, 20, 35), 0.25 if pe_ttm is not None and pe_ttm > 0 else 0),
            (score_low(pb_ex_goodwill, 1.2, 2.5, 4.0), 0.15 if pb_ex_goodwill is not None and pb_ex_goodwill > 0 else 0),
            (score_high(dividend_yield, 5, 3, 1), 0.15 if dividend_yield is not None else 0),
        ]:
            weighted_value_score += value * weight
            weight_sum += weight
        valuation_score = clamp_score(weighted_value_score / weight_sum) if weight_sum else None

        summary = [
            {"key": "quality", "title": "公司质量", "score": quality_score, **status_from_score(quality_score), "main": f"ROE 5年均值 {round_or_none(roe_avg_5y) if roe_avg_5y is not None else '-'}%", "note": "盈利能力、资本回报和利润稳定性"},
            {"key": "growth", "title": "成长性", "score": growth_score, **status_from_score(growth_score), "main": f"净利润 CAGR {round_or_none(profit_cagr) if profit_cagr is not None else '-'}%", "note": "营收和归母净利润的长期与最新变化"},
            {"key": "cashflow", "title": "现金流质量", "score": cashflow_score, **status_from_score(cashflow_score), "main": f"现金流/净利润 {round_or_none(cf_profit_avg_5y) if cf_profit_avg_5y is not None else '-'}%", "note": "利润能否转化成经营现金流"},
            {"key": "balance", "title": "资产负债", "score": balance_score, **status_from_score(balance_score), "main": f"资产负债率 {round_or_none(latest.get('debt_ratio')) if latest.get('debt_ratio') is not None else '-'}%", "note": "杠杆、有息负债和商誉压力"},
            {"key": "valuation", "title": "估值位置", "score": valuation_score, **status_from_score(valuation_score), "main": f"PE {round_or_none(pe_ttm) if pe_ttm is not None else '-'}", "note": "合理价偏离、PE、PB和股息率"},
        ]

        groups = [
            {"title": "盈利能力", "metrics": [
                metric("ROE 5年均值", roe_avg_5y, "%", verdict_high(roe_avg_5y, 20, 15, 8), "股东资本回报"),
                metric("ROIC 5年均值", roic_avg_5y, "%", verdict_high(roic_avg_5y, 15, 10, 6), "投入资本回报"),
                metric("最新净利率", latest.get("net_profit_rate"), "%", verdict_high(latest.get("net_profit_rate"), 20, 10, 4), f"{latest['fiscal_year']} 年"),
                metric("最新核心利润率", latest.get("core_profit_rate"), "%", verdict_high(latest.get("core_profit_rate"), 20, 10, 4), "营业利润/营收"),
            ]},
            {"title": "成长性", "metrics": [
                metric("营收 CAGR", revenue_cagr, "%", verdict_high(revenue_cagr, 15, 8, 0), f"{earliest['fiscal_year']}-{latest['fiscal_year']}"),
                metric("归母净利 CAGR", profit_cagr, "%", verdict_high(profit_cagr, 15, 8, 0), f"{earliest['fiscal_year']}-{latest['fiscal_year']}"),
                metric("最新营收同比", revenue_yoy, "%", verdict_high(revenue_yoy, 12, 5, 0), f"{latest['fiscal_year']} 年"),
                metric("最新净利同比", profit_yoy, "%", verdict_high(profit_yoy, 12, 5, 0), f"{latest['fiscal_year']} 年"),
            ]},
            {"title": "现金流", "metrics": [
                metric("现金流/净利润 5年均值", cf_profit_avg_5y, "%", verdict_high(cf_profit_avg_5y, 120, 90, 60), "经营现金流净额/归母净利润"),
                metric("最新现金流/净利润", latest.get("cashflow_to_profit"), "%", verdict_high(latest.get("cashflow_to_profit"), 120, 90, 60), f"{latest['fiscal_year']} 年"),
                metric("经营现金流为正", positive_ocf_years, f"/{len(recent)} 年", "good" if positive_ocf_years == len(recent) else "warn", "近5年"),
                metric("最新经营现金流", latest.get("operate_cashflow"), "亿元", "good" if (latest.get("operate_cashflow") or 0) > 0 else "bad", f"{latest['fiscal_year']} 年"),
            ]},
            {"title": "资产质量", "metrics": [
                metric("资产负债率", latest.get("debt_ratio"), "%", verdict_low(latest.get("debt_ratio"), 35, 55, 70), f"{latest['fiscal_year']} 年"),
                metric("有息负债率", latest.get("interest_bearing_debt_ratio"), "%", verdict_low(latest.get("interest_bearing_debt_ratio"), 15, 30, 45), "口径来自财报摘要"),
                metric("商誉/归母权益", goodwill_to_equity, "%", verdict_low(goodwill_to_equity, 5, 15, 30), "商誉减值压力"),
                metric("总资产", latest.get("total_assets"), "亿元", "neutral", f"{latest['fiscal_year']} 年"),
            ]},
            {"title": "估值回报", "metrics": [
                metric("PE(TTM)", pe_ttm, "", verdict_low(pe_ttm, 10, 20, 35), "腾讯行情/本地缓存"),
                metric("PB(扣商誉)", pb_ex_goodwill, "", verdict_low(pb_ex_goodwill, 1.2, 2.5, 4.0), "按归母权益扣商誉"),
                metric("股息率", dividend_yield, "%", verdict_high(dividend_yield, 5, 3, 1), "最近更新值"),
                metric("合理价偏离", reasonable_discount, "%", verdict_low(reasonable_discount, -25, 0, 35), "负数代表低于合理价"),
            ]},
        ]

        signals = []

        def add_signal(level, text, detail):
            signals.append({"level": level, "text": text, "detail": detail})

        if latest.get("cashflow_to_profit") is not None and latest["cashflow_to_profit"] < 60:
            add_signal("bad", "利润现金含量偏弱", f"{latest['fiscal_year']} 年经营现金流/净利润为 {round_or_none(latest['cashflow_to_profit'])}%")
        if cf_profit_avg_5y is not None and cf_profit_avg_5y < 80:
            add_signal("warn", "近5年现金流覆盖不足", f"近5年均值为 {round_or_none(cf_profit_avg_5y)}%")
        if profit_yoy is not None and profit_yoy < -20:
            add_signal("bad", "最新净利润明显下滑", f"{latest['fiscal_year']} 年归母净利润同比 {round_or_none(profit_yoy)}%")
        if revenue_yoy is not None and revenue_yoy < -10:
            add_signal("warn", "最新营收下滑", f"{latest['fiscal_year']} 年营收同比 {round_or_none(revenue_yoy)}%")
        if latest.get("debt_ratio") is not None and latest["debt_ratio"] > 70:
            add_signal("bad", "资产负债率偏高", f"{latest['fiscal_year']} 年资产负债率 {round_or_none(latest['debt_ratio'])}%")
        if goodwill_to_equity is not None and goodwill_to_equity > 30:
            add_signal("warn", "商誉占净资产较高", f"商誉/归母权益为 {round_or_none(goodwill_to_equity)}%")
        if pe_ttm is not None and pe_ttm > 50:
            add_signal("warn", "PE 估值较高", f"当前 PE(TTM) 为 {round_or_none(pe_ttm)}")
        if not signals:
            add_signal("good", "暂无明显红色信号", "基于当前已有年报数据，未触发主要异常规则。")

        return jsonify({
            "stock": {
                "code": stock["code"],
                "name": stock["name"],
                "industry": stock.get("industry"),
                "price": round_or_none(price),
                "reasonable_price": round_or_none(reasonable_price),
            },
            "latest_year": latest["fiscal_year"],
            "year_range": f"{earliest['fiscal_year']}-{latest['fiscal_year']}",
            "summary": summary,
            "groups": groups,
            "signals": signals,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


COMPARE_DEFAULT_METRICS = [
    "market.pe_ttm",
    "market.pb_ex_goodwill",
    "market.dividend_yield",
    "financial.roe",
    "financial.roic",
    "income.gross_margin",
    "financial.net_profit_rate",
    "financial.debt_ratio",
    "financial.revenue_yoy",
    "financial.profit_yoy",
    "financial.cashflow_to_profit",
    "financial.dividend_payout_ratio",
]

COMPARE_METRICS = [
    {"key": "market.pe_ttm", "name": "PE(TTM)", "unit": "", "group": "行情估值"},
    {"key": "market.pb_ex_goodwill", "name": "PB(扣商誉)", "unit": "", "group": "行情估值"},
    {"key": "market.dividend_yield", "name": "股息率", "unit": "%", "group": "行情估值"},
    {"key": "financial.roe", "name": "ROE", "unit": "%", "group": "自定义财报"},
    {"key": "financial.deducted_roe", "name": "扣非ROE", "unit": "%", "group": "自定义财报"},
    {"key": "financial.roic", "name": "ROIC", "unit": "%", "group": "自定义财报"},
    {"key": "financial.total_revenue", "name": "营业总收入", "unit": "亿元", "group": "自定义财报", "flow": True},
    {"key": "financial.operate_profit", "name": "核心利润", "unit": "亿元", "group": "自定义财报", "flow": True},
    {"key": "financial.parent_profit", "name": "归母净利润", "unit": "亿元", "group": "自定义财报", "flow": True},
    {"key": "financial.deducted_profit", "name": "扣非净利润", "unit": "亿元", "group": "自定义财报", "flow": True},
    {"key": "financial.operate_cashflow", "name": "经营现金流净额", "unit": "亿元", "group": "自定义财报", "flow": True},
    {"key": "financial.net_profit_rate", "name": "净利率", "unit": "%", "group": "自定义财报"},
    {"key": "financial.cashflow_to_profit", "name": "现金流/净利润", "unit": "%", "group": "自定义财报"},
    {"key": "financial.revenue_yoy", "name": "营收同比", "unit": "%", "group": "自定义财报"},
    {"key": "financial.profit_yoy", "name": "净利润同比", "unit": "%", "group": "自定义财报"},
    {"key": "financial.debt_ratio", "name": "资产负债率", "unit": "%", "group": "自定义财报"},
    {"key": "financial.interest_bearing_debt_ratio", "name": "有息负债率", "unit": "%", "group": "自定义财报"},
    {"key": "financial.basic_eps", "name": "基本EPS", "unit": "元", "group": "自定义财报"},
    {"key": "financial.total_assets", "name": "总资产", "unit": "亿元", "group": "自定义财报"},
    {"key": "financial.total_equity", "name": "归母权益", "unit": "亿元", "group": "自定义财报"},
    {"key": "financial.dividend_payout_ratio", "name": "分红率", "unit": "%", "group": "自定义财报"},
    {"key": "income.gross_margin", "name": "毛利率", "unit": "%", "group": "利润表"},
    {"key": "income.operating_revenue", "name": "营业收入", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.cost_of_revenue", "name": "营业成本", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.selling_expense", "name": "销售费用", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.admin_expense", "name": "管理费用", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.rd_expense", "name": "研发费用", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.finance_expense", "name": "财务费用", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.operating_profit", "name": "营业利润", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "income.parent_net_profit", "name": "归母净利润(利润表)", "unit": "亿元", "group": "利润表", "flow": True},
    {"key": "balance.total_assets", "name": "总资产(资产负债表)", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.total_liabilities", "name": "负债合计", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.parent_equity", "name": "归母权益(资产负债表)", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.accounts_receivable", "name": "应收账款", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.inventory", "name": "存货", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.goodwill", "name": "商誉", "unit": "亿元", "group": "资产负债表"},
    {"key": "balance.goodwill_to_equity", "name": "商誉/归母权益", "unit": "%", "group": "资产负债表"},
    {"key": "cashflow.cf_oper_net", "name": "经营现金流净额(现金流量表)", "unit": "亿元", "group": "现金流量表", "flow": True},
    {"key": "cashflow.cf_sales_goods", "name": "销售商品收到现金", "unit": "亿元", "group": "现金流量表", "flow": True},
    {"key": "cashflow.cf_buy_assets", "name": "购建固定资产等支付现金", "unit": "亿元", "group": "现金流量表", "flow": True},
    {"key": "cashflow.free_cashflow", "name": "自由现金流", "unit": "亿元", "group": "现金流量表", "flow": True},
    {"key": "cashflow.cf_finance_net", "name": "筹资现金流净额", "unit": "亿元", "group": "现金流量表", "flow": True},
]


@app.route("/api/stock/<code>/compare-dashboard")
def api_stock_compare_dashboard(code):
    def to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def pct(cur, base):
        if cur is None or base in (None, 0):
            return None
        return round(cur / base * 100, 4)

    def pct_change(cur, prev):
        if cur is None or prev in (None, 0):
            return None
        return round((cur - prev) / abs(prev) * 100, 4)

    def parse_codes():
        raw = request.args.get("codes", "")
        result = []
        for c in [code] + raw.split(","):
            c = _normalize_stock_code(str(c).strip())
            if re.match(r"^\d{5,6}$", c) and c not in result:
                result.append(c)
            if len(result) >= 3:
                break
        return result

    def row_to_float_dict(row):
        if not row:
            return None
        return {k: to_float(v) if k not in ("stock_code", "report_period", "fiscal_year") else v for k, v in row.items()}

    def period_rank(period):
        return {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(period, 4)

    def period_row(source_map, stock_code, fiscal_year, report_period, single_view, flow_fields):
        cur = row_to_float_dict(source_map.get((stock_code, fiscal_year, report_period)))
        if not cur:
            return None
        if not single_view or report_period == "Q1":
            return cur
        prev_period = {"Q2": "Q1", "Q3": "Q2", "FY": "Q3"}.get(report_period)
        prev = row_to_float_dict(source_map.get((stock_code, fiscal_year, prev_period))) if prev_period else None
        if not prev:
            return cur
        result = dict(cur)
        for field in flow_fields:
            if cur.get(field) is not None and prev.get(field) is not None:
                result[field] = round(cur[field] - prev[field], 4)
        return result

    metric_defs = {m["key"]: m for m in COMPARE_METRICS}
    codes = parse_codes()
    year = request.args.get("year", type=int)
    if not year:
        latest = execute_query("SELECT MAX(fiscal_year) AS y FROM custom_financials WHERE stock_code=%s", (code,))
        year = int(latest[0]["y"]) if latest and latest[0].get("y") else datetime.now().year
    period = request.args.get("period", "FY")
    if period not in ("FY", "Q1", "Q2", "Q3"):
        period = "FY"
    view = request.args.get("view", "cumulative")
    single_view = view == "single" and period not in ("FY", "Q1")

    requested_metrics = [
        m.strip() for m in request.args.get("metrics", "").split(",")
        if m.strip() in metric_defs
    ]
    metric_keys = requested_metrics or COMPARE_DEFAULT_METRICS

    placeholders = ",".join(["%s"] * len(codes))
    stocks = execute_query(
        f"SELECT code, name, market, industry, pe_ttm, dividend_yield FROM stocks WHERE code IN ({placeholders})",
        tuple(codes),
    )
    stocks_by_code = {s["code"]: dict(s) for s in stocks}
    ordered_stocks = [stocks_by_code[c] for c in codes if c in stocks_by_code]
    ordered_stocks = _enrich_stock_list_metrics(ordered_stocks, include_ytd=False)
    market_by_code = {s["code"]: s for s in ordered_stocks}

    year_params = tuple(codes + [year, year - 1])
    two_years = "(%s,%s)"
    financial_rows = execute_query(
        f"""SELECT cf.*, d.dividend_amount, d.dividend_per_share
            FROM custom_financials cf
            LEFT JOIN dividends d ON cf.stock_code=d.stock_code AND cf.fiscal_year=d.fiscal_year
            WHERE cf.stock_code IN ({placeholders}) AND cf.fiscal_year IN {two_years}""",
        year_params,
    )
    income_rows = execute_query(
        f"SELECT * FROM income_statements WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
        year_params,
    )
    balance_rows = execute_query(
        f"SELECT * FROM balance_sheets WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
        year_params,
    )
    cash_rows = execute_query(
        f"SELECT * FROM cash_flows WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
        year_params,
    )

    def make_map(rows):
        return {(r["stock_code"], int(r["fiscal_year"]), r.get("report_period", "FY")): r for r in rows}

    financial_map = make_map(financial_rows)
    income_map = make_map(income_rows)
    balance_map = make_map(balance_rows)
    cash_map = make_map(cash_rows)
    financial_flow = ["total_revenue", "operate_profit", "parent_profit", "deducted_profit", "operate_cashflow", "dividend_amount"]
    income_flow = ["total_revenue", "operating_revenue", "operating_cost", "cost_of_revenue", "tax_surcharge", "selling_expense", "admin_expense", "finance_expense", "rd_expense", "fair_value_change", "invest_income", "operating_profit", "nonop_income", "nonop_expense", "total_profit", "income_tax", "net_profit", "parent_net_profit"]
    cash_flow = ["cf_sales_goods", "cf_tax_refund", "cf_other_oper_in", "cf_oper_inflow", "cf_buy_goods", "cf_payroll", "cf_tax_pay", "cf_other_oper_out", "cf_oper_outflow", "cf_oper_net", "cf_invest_withdraw", "cf_invest_income", "cf_dispose_assets", "cf_other_invest_in", "cf_invest_inflow", "cf_buy_assets", "cf_invest_pay", "cf_other_invest_out", "cf_invest_outflow", "cf_invest_net", "cf_finance_in", "cf_borrow", "cf_bond", "cf_other_finance_in", "cf_finance_inflow", "cf_repay_debt", "cf_dividend_interest", "cf_other_finance_out", "cf_finance_outflow", "cf_finance_net"]

    def context_for(stock_code, fiscal_year):
        fin = period_row(financial_map, stock_code, fiscal_year, period, single_view, financial_flow)
        inc = period_row(income_map, stock_code, fiscal_year, period, single_view, income_flow)
        bal = period_row(balance_map, stock_code, fiscal_year, period, False, [])
        cf = period_row(cash_map, stock_code, fiscal_year, period, single_view, cash_flow)
        return {"market": market_by_code.get(stock_code, {}), "financial": fin or {}, "income": inc or {}, "balance": bal or {}, "cashflow": cf or {}}

    contexts = {s["code"]: context_for(s["code"], year) for s in ordered_stocks}
    prev_contexts = {s["code"]: context_for(s["code"], year - 1) for s in ordered_stocks}

    def metric_value(key, ctx, prev_ctx):
        source, field = key.split(".", 1)
        if source == "market":
            return to_float(ctx["market"].get(field))
        if key == "financial.net_profit_rate":
            return pct(to_float(ctx["financial"].get("parent_profit")), to_float(ctx["financial"].get("total_revenue")))
        if key == "financial.cashflow_to_profit":
            return pct(to_float(ctx["financial"].get("operate_cashflow")), to_float(ctx["financial"].get("parent_profit")))
        if key == "financial.revenue_yoy":
            return pct_change(to_float(ctx["financial"].get("total_revenue")), to_float(prev_ctx["financial"].get("total_revenue")))
        if key == "financial.profit_yoy":
            return pct_change(to_float(ctx["financial"].get("parent_profit")), to_float(prev_ctx["financial"].get("parent_profit")))
        if key == "financial.dividend_payout_ratio":
            return pct(to_float(ctx["financial"].get("dividend_amount")), to_float(ctx["financial"].get("parent_profit")))
        if key == "income.gross_margin":
            revenue = to_float(ctx["income"].get("operating_revenue")) or to_float(ctx["income"].get("total_revenue"))
            cost = to_float(ctx["income"].get("cost_of_revenue"))
            if cost is None:
                cost = to_float(ctx["income"].get("operating_cost"))
            return pct(revenue - cost, revenue) if revenue is not None and cost is not None else None
        if key == "balance.goodwill_to_equity":
            return pct(to_float(ctx["balance"].get("goodwill")), to_float(ctx["balance"].get("parent_equity")))
        if key == "cashflow.free_cashflow":
            oper = to_float(ctx["cashflow"].get("cf_oper_net"))
            capex = to_float(ctx["cashflow"].get("cf_buy_assets"))
            return round(oper - capex, 4) if oper is not None and capex is not None else None
        return to_float(ctx[source].get(field))

    rows = []
    for key in metric_keys:
        meta = metric_defs[key]
        values = []
        for stock in ordered_stocks:
            stock_code = stock["code"]
            value = metric_value(key, contexts[stock_code], prev_contexts[stock_code])
            values.append({"code": stock_code, "value": round(value, 4) if value is not None else None})
        rows.append({
            "key": key,
            "name": meta["name"],
            "unit": meta.get("unit", ""),
            "group": meta.get("group", ""),
            "values": values,
        })

    available_years = execute_query(
        "SELECT DISTINCT fiscal_year FROM custom_financials WHERE stock_code=%s ORDER BY fiscal_year DESC",
        (code,),
    )

    return jsonify({
        "stocks": [
            {"code": s["code"], "name": s["name"], "market": s.get("market"), "industry": s.get("industry")}
            for s in ordered_stocks
        ],
        "year": year,
        "period": period,
        "view": "single" if single_view else "cumulative",
        "available_years": [int(r["fiscal_year"]) for r in available_years],
        "default_metrics": COMPARE_DEFAULT_METRICS,
        "metric_options": COMPARE_METRICS,
        "rows": rows,
    })


@app.route("/api/stock/<code>/capital-allocation")
def api_stock_capital_allocation(code):
    """资本配置分析：经营现金流如何流向再投资、分红、偿债、融资和股本变化。"""

    def to_float(value):
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def round_or_none(value, ndigits=4):
        return round(value, ndigits) if value is not None else None

    def pct(part, whole):
        if part is None or whole in (None, 0):
            return None
        return part / whole * 100

    def get_val(row, key, default=None):
        if not row:
            return default
        value = to_float(row.get(key))
        return default if value is None else value

    stock_rows = execute_query("SELECT code, name, market, industry FROM stocks WHERE code=%s", (code,))
    if not stock_rows:
        return jsonify({"error": "未找到该股票"}), 404

    from_year = request.args.get("from_year", type=int)
    to_year = request.args.get("to_year", type=int)
    selected_year = request.args.get("year", type=int)

    fin_rows = execute_query(
        """SELECT fiscal_year, parent_profit, operate_cashflow, total_shares, interest_bearing_debt_ratio
           FROM custom_financials
           WHERE stock_code=%s AND report_period='FY'
           ORDER BY fiscal_year ASC""",
        (code,),
    )
    if not fin_rows:
        return jsonify({
            "stock": dict(stock_rows[0]),
            "years": [],
            "rows": [],
            "message": "暂无年报财务数据，请先更新财报数据。",
        })

    all_years = [int(r["fiscal_year"]) for r in fin_rows]
    if to_year is None:
        to_year = max(all_years)
    if from_year is None:
        from_year = max(min(all_years), to_year - 9)
    if selected_year is None:
        selected_year = to_year

    needed_years = sorted(set([y for y in all_years if from_year <= y <= to_year] + [from_year - 1]))
    if not needed_years:
        needed_years = all_years[-10:]
    placeholders = ",".join(["%s"] * len(needed_years))
    params = tuple([code] + needed_years)

    div_rows = execute_query(
        f"""SELECT fiscal_year, dividend_amount
            FROM dividends
            WHERE stock_code=%s AND fiscal_year IN ({placeholders})""",
        params,
    )
    cash_rows = execute_query(
        f"""SELECT fiscal_year, cf_oper_net, cf_buy_assets, cf_repay_debt, cf_borrow,
                   cf_bond, cf_finance_in, cf_other_finance_in, cf_finance_inflow,
                   cf_finance_net, cf_dividend_interest
            FROM cash_flows
            WHERE stock_code=%s AND report_period='FY' AND fiscal_year IN ({placeholders})""",
        params,
    )
    balance_rows = execute_query(
        f"""SELECT fiscal_year, goodwill, total_liabilities, parent_equity
            FROM balance_sheets
            WHERE stock_code=%s AND report_period='FY' AND fiscal_year IN ({placeholders})""",
        params,
    )

    fin_map = {int(r["fiscal_year"]): r for r in fin_rows}
    div_map = {int(r["fiscal_year"]): r for r in div_rows}
    cash_map = {int(r["fiscal_year"]): r for r in cash_rows}
    balance_map = {int(r["fiscal_year"]): r for r in balance_rows}

    rows = []
    for year in [y for y in all_years if from_year <= y <= to_year]:
        fin = fin_map.get(year)
        prev_fin = fin_map.get(year - 1)
        cash = cash_map.get(year)
        div = div_map.get(year)
        bal = balance_map.get(year)
        prev_bal = balance_map.get(year - 1)

        operating_cashflow = get_val(cash, "cf_oper_net")
        if operating_cashflow is None:
            operating_cashflow = get_val(fin, "operate_cashflow")
        capex = get_val(cash, "cf_buy_assets", 0)
        dividend = get_val(div, "dividend_amount", 0)
        buyback = 0
        debt_repayment = get_val(cash, "cf_repay_debt", 0)
        debt_borrow = (get_val(cash, "cf_borrow", 0) or 0) + (get_val(cash, "cf_bond", 0) or 0)
        equity_financing = get_val(cash, "cf_finance_in", 0)
        other_financing = get_val(cash, "cf_other_finance_in", 0)
        financing_inflow = get_val(cash, "cf_finance_inflow")
        financing_sources = debt_borrow + (equity_financing or 0) + (other_financing or 0)
        if financing_inflow is not None and financing_inflow > financing_sources:
            financing_sources = financing_inflow
        finance_net = get_val(cash, "cf_finance_net")
        dividend_interest_paid = get_val(cash, "cf_dividend_interest")

        free_cashflow = (
            operating_cashflow - capex
            if operating_cashflow is not None and capex is not None else None
        )
        remaining_after_allocation = (
            operating_cashflow - capex - dividend - buyback - debt_repayment
            if operating_cashflow is not None else None
        )
        financing_remaining_after_allocation = (
            operating_cashflow + financing_sources - capex - dividend - buyback - debt_repayment
            if operating_cashflow is not None else None
        )

        goodwill = get_val(bal, "goodwill")
        prev_goodwill = get_val(prev_bal, "goodwill")
        goodwill_change = goodwill - prev_goodwill if goodwill is not None and prev_goodwill is not None else None
        total_shares = get_val(fin, "total_shares")
        prev_total_shares = get_val(prev_fin, "total_shares")
        total_shares_change = total_shares - prev_total_shares if total_shares is not None and prev_total_shares is not None else None
        total_shares_change_pct = pct(total_shares_change, prev_total_shares)
        total_liabilities = get_val(bal, "total_liabilities")
        prev_total_liabilities = get_val(prev_bal, "total_liabilities")
        liabilities_change = total_liabilities - prev_total_liabilities if total_liabilities is not None and prev_total_liabilities is not None else None
        parent_profit = get_val(fin, "parent_profit")

        rows.append({
            "year": year,
            "operating_cashflow": round_or_none(operating_cashflow),
            "capex": round_or_none(capex),
            "dividend": round_or_none(dividend),
            "buyback": buyback,
            "debt_repayment": round_or_none(debt_repayment),
            "debt_borrow": round_or_none(debt_borrow),
            "equity_financing": round_or_none(equity_financing),
            "other_financing": round_or_none(other_financing),
            "financing_inflow": round_or_none(financing_inflow),
            "financing_sources": round_or_none(financing_sources),
            "finance_net": round_or_none(finance_net),
            "dividend_interest_paid": round_or_none(dividend_interest_paid),
            "free_cashflow": round_or_none(free_cashflow),
            "remaining_after_allocation": round_or_none(remaining_after_allocation),
            "financing_remaining_after_allocation": round_or_none(financing_remaining_after_allocation),
            "parent_profit": round_or_none(parent_profit),
            "dividend_payout_ratio": round_or_none(pct(dividend, parent_profit), 2),
            "capex_to_ocf": round_or_none(pct(capex, operating_cashflow), 2),
            "debt_repay_to_ocf": round_or_none(pct(debt_repayment, operating_cashflow), 2),
            "goodwill": round_or_none(goodwill),
            "goodwill_change": round_or_none(goodwill_change),
            "total_shares": round_or_none(total_shares),
            "total_shares_change": round_or_none(total_shares_change),
            "total_shares_change_pct": round_or_none(total_shares_change_pct, 2),
            "total_liabilities": round_or_none(total_liabilities),
            "liabilities_change": round_or_none(liabilities_change),
        })

    selected = next((r for r in rows if r["year"] == selected_year), rows[-1] if rows else None)

    signals = []
    if selected:
        if selected.get("free_cashflow") is not None and selected["free_cashflow"] < 0:
            signals.append({"level": "warn", "text": "自由现金流为负", "detail": f"{selected['year']} 年经营现金流不足以覆盖资本开支。"})
        if selected.get("dividend") and selected.get("free_cashflow") is not None and selected["dividend"] > selected["free_cashflow"]:
            signals.append({"level": "warn", "text": "分红高于自由现金流", "detail": "需要关注分红是否依赖存量现金或外部融资。"})
        if selected.get("total_shares_change_pct") is not None and selected["total_shares_change_pct"] > 2:
            signals.append({"level": "warn", "text": "股本有摊薄", "detail": f"总股本同比增加 {selected['total_shares_change_pct']}%。"})
        if selected.get("goodwill_change") is not None and selected["goodwill_change"] > 0:
            signals.append({"level": "neutral", "text": "商誉增加", "detail": f"商誉同比增加 {selected['goodwill_change']} 亿元，可能来自并购或口径变动。"})
        if selected.get("remaining_after_allocation") is not None and selected.get("financing_remaining_after_allocation") is not None and selected["remaining_after_allocation"] < 0 <= selected["financing_remaining_after_allocation"]:
            signals.append({"level": "warn", "text": "经营口径为负，融资后转正", "detail": "资本配置依赖外部融资补足现金缺口。"})
        if selected.get("debt_borrow") and selected.get("debt_repayment") and selected["debt_borrow"] > selected["debt_repayment"]:
            signals.append({"level": "neutral", "text": "借款流入高于偿债", "detail": "筹资侧仍在净补充债务资金。"})
    if not signals:
        signals.append({"level": "good", "text": "暂无明显资本配置异常", "detail": "基于当前已有现金流、分红、商誉和股本数据。"})

    return jsonify({
        "stock": dict(stock_rows[0]),
        "years": [y for y in all_years if from_year <= y <= to_year],
        "from_year": from_year,
        "to_year": to_year,
        "selected_year": selected["year"] if selected else selected_year,
        "rows": rows,
        "selected": selected,
        "signals": signals,
        "notes": [
            "回购暂无专项数据表，当前瀑布图按 0 处理并在页面标注。",
            "资本开支使用现金流量表“购建固定资产、无形资产和其他长期资产支付的现金”。",
            "经营剩余 = 经营现金流 - 资本开支 - 分红 - 回购 - 偿债。",
            "融资后剩余 = 经营现金流 + 借款/发债流入 + 股权融资/其他筹资流入 - 资本开支 - 分红 - 回购 - 偿债。",
            "偿债使用现金流量表“偿还债务支付的现金”，融资流入包含取得借款、发行债券、吸收投资和其他筹资流入。",
        ],
    })


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


LOCAL_SETTING_KEYS = {
    "app_port",
    "app_url",
    "auto_cloud_backup_delay_seconds",
    "cloud_sync_dir",
    "mysql_service_name",
    "mysql_home",
    "mysql_bin_dir",
    "python_exe",
    "db_host",
    "db_port",
    "db_user",
    "db_password",
    "db_name",
}


def _path_status(path):
    raw = str(path or "").strip()
    if not raw:
        return {"path": "", "exists": False, "is_dir": False, "is_file": False}
    expanded = os.path.abspath(os.path.expandvars(raw))
    return {
        "path": expanded,
        "exists": os.path.exists(expanded),
        "is_dir": os.path.isdir(expanded),
        "is_file": os.path.isfile(expanded),
    }


def _local_settings_payload(settings=None):
    settings = dict(LOCAL_SETTINGS if settings is None else settings)
    values = {
        "app_port": int(settings.get("app_port") or APP_PORT),
        "app_url": settings.get("app_url") or f"http://127.0.0.1:{APP_PORT}",
        "auto_cloud_backup_delay_seconds": int(settings.get("auto_cloud_backup_delay_seconds") or AUTO_CLOUD_BACKUP_DELAY_SECONDS),
        "cloud_sync_dir": settings.get("cloud_sync_dir") or CLOUD_SYNC_DIR,
        "mysql_service_name": settings.get("mysql_service_name") or "",
        "mysql_home": settings.get("mysql_home") or "",
        "mysql_bin_dir": settings.get("mysql_bin_dir") or MYSQL_BIN_DIR,
        "python_exe": settings.get("python_exe") or sys.executable,
        "db_host": settings.get("db_host") or DB_CONFIG.get("host", "127.0.0.1"),
        "db_port": int(settings.get("db_port") or DB_CONFIG.get("port", 3306)),
        "db_user": settings.get("db_user") or DB_CONFIG.get("user", "root"),
        "db_name": settings.get("db_name") or DB_CONFIG.get("database", "stock_analysis"),
    }
    cloud = _path_status(values["cloud_sync_dir"])
    mysql_bin = _path_status(values["mysql_bin_dir"])
    python_exe = _path_status(values["python_exe"])
    latest_path = os.path.join(cloud["path"], CLOUD_LATEST_SQL) if cloud["path"] else ""
    latest_exists = os.path.exists(latest_path) if latest_path else False
    return {
        "ok": True,
        "path": LOCAL_SETTINGS_PATH,
        "values": values,
        "db_password_configured": bool(settings.get("db_password") or DB_CONFIG.get("password")),
        "runtime": {
            "cloud_sync_dir": CLOUD_SYNC_DIR,
            "mysql_bin_dir": MYSQL_BIN_DIR,
            "app_port": APP_PORT,
            "auto_cloud_backup_delay_seconds": AUTO_CLOUD_BACKUP_DELAY_SECONDS,
            "db_host": DB_CONFIG.get("host"),
            "db_port": DB_CONFIG.get("port"),
            "db_user": DB_CONFIG.get("user"),
            "db_name": DB_CONFIG.get("database"),
        },
        "checks": {
            "cloud_sync_dir": cloud,
            "cloud_latest_sql": {
                "path": latest_path,
                "exists": latest_exists,
                "mtime": datetime.fromtimestamp(os.path.getmtime(latest_path)).isoformat(timespec="seconds") if latest_exists else None,
                "size": os.path.getsize(latest_path) if latest_exists else 0,
            },
            "mysql_bin_dir": mysql_bin,
            "mysql_exe": _path_status(os.path.join(mysql_bin["path"], "mysql.exe") if mysql_bin["path"] else ""),
            "mysqldump_exe": _path_status(os.path.join(mysql_bin["path"], "mysqldump.exe") if mysql_bin["path"] else ""),
            "python_exe": python_exe,
        },
        "restart_required_after_save": True,
    }


@app.route("/api/local-settings", methods=["GET"])
def api_local_settings_get():
    return jsonify(_local_settings_payload())


@app.route("/api/local-settings", methods=["PUT"])
def api_local_settings_put():
    global LOCAL_SETTINGS
    data = request.get_json(force=True) or {}
    current = _read_local_settings()
    updated = []
    for key in LOCAL_SETTING_KEYS:
        if key not in data:
            continue
        value = data.get(key)
        if key == "db_password" and (value is None or str(value).strip() in ("", "********")):
            continue
        if key in ("app_port", "auto_cloud_backup_delay_seconds", "db_port"):
            try:
                value = int(value)
            except Exception:
                return jsonify({"error": f"{key} 必须是数字"}), 400
        elif value is not None:
            value = str(value).strip()
        current[key] = value
        updated.append(key)

    with open(LOCAL_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
    LOCAL_SETTINGS = current
    return jsonify({"ok": True, "updated": updated, "restart_required": True, **_local_settings_payload(current)})


@app.route("/api/local-settings/test", methods=["POST"])
def api_local_settings_test():
    data = request.get_json(force=True) or {}
    current = _read_local_settings()
    merged = {**current, **{k: v for k, v in data.items() if k in LOCAL_SETTING_KEYS and v not in (None, "")}}
    if data.get("db_password") in (None, "", "********"):
        merged["db_password"] = current.get("db_password", DB_CONFIG.get("password", ""))

    cloud_dir = str(merged.get("cloud_sync_dir") or CLOUD_SYNC_DIR)
    mysql_bin_dir = str(merged.get("mysql_bin_dir") or MYSQL_BIN_DIR)
    result = {
        "ok": True,
        "checks": {
            "cloud_sync_dir": {"ok": False, "message": ""},
            "mysql_tools": {"ok": False, "message": ""},
            "database": {"ok": False, "message": ""},
        },
    }

    try:
        os.makedirs(os.path.abspath(os.path.expandvars(cloud_dir)), exist_ok=True)
        result["checks"]["cloud_sync_dir"] = {"ok": True, "message": "云同步目录可访问"}
    except Exception as e:
        result["checks"]["cloud_sync_dir"] = {"ok": False, "message": str(e)}

    mysql_exe = os.path.join(os.path.abspath(os.path.expandvars(mysql_bin_dir)), "mysql.exe") if mysql_bin_dir else ""
    mysqldump_exe = os.path.join(os.path.abspath(os.path.expandvars(mysql_bin_dir)), "mysqldump.exe") if mysql_bin_dir else ""
    tools_ok = bool(mysql_exe and os.path.exists(mysql_exe) and os.path.exists(mysqldump_exe))
    result["checks"]["mysql_tools"] = {
        "ok": tools_ok,
        "message": "mysql.exe 和 mysqldump.exe 已找到" if tools_ok else "未同时找到 mysql.exe 和 mysqldump.exe",
    }

    try:
        conn = mysql.connector.connect(
            host=merged.get("db_host") or DB_CONFIG.get("host"),
            port=int(merged.get("db_port") or DB_CONFIG.get("port")),
            user=merged.get("db_user") or DB_CONFIG.get("user"),
            password=merged.get("db_password", DB_CONFIG.get("password", "")),
            database=merged.get("db_name") or DB_CONFIG.get("database"),
            connection_timeout=3,
        )
        conn.close()
        result["checks"]["database"] = {"ok": True, "message": "数据库连接成功"}
    except Exception as e:
        result["checks"]["database"] = {"ok": False, "message": str(e)}

    result["ok"] = all(item["ok"] for item in result["checks"].values())
    return jsonify(result)


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
    light = request.args.get("light") == "1"
    sort_by = request.args.get("sort_by", "").strip()
    sort_dir = request.args.get("sort_dir", "asc").lower()
    sort_fields = {"code", "name", "day_change_pct", "price", "pe_ttm", "pb_ex_goodwill", "dividend_yield", "ytd_return", "reasonable_valuation", "reasonable_price", "reasonable_discount"}

    if sort_by in sort_fields:
        all_result = Stock.get_all(
            page=1, page_size=10000,
            market=market or None,
            status=status or None,
            keyword=keyword or None,
        )
        rows = _enrich_stock_list_metrics(
            all_result.get("data") or [],
            include_ytd=sort_by == "ytd_return",
        )
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
    if not light:
        result["data"] = _enrich_stock_list_metrics(result.get("data") or [])
    result["sort_by"] = ""
    result["sort_dir"] = ""
    return jsonify(result)


@app.route("/api/stocks/realtime")
def api_stocks_realtime():
    raw_codes = request.args.get("codes", "")
    codes = []
    for code in raw_codes.split(","):
        code = code.strip()
        if re.match(r"^\d{5,6}$", code) and code not in codes:
            codes.append(code)
    if not codes:
        return jsonify({"data": []})
    return jsonify({"data": _stock_realtime_list_metrics(codes[:200])})


@app.route("/api/stocks/ytd")
def api_stocks_ytd():
    raw_codes = request.args.get("codes", "")
    codes = []
    for code in raw_codes.split(","):
        code = code.strip()
        if re.match(r"^\d{5,6}$", code) and code not in codes:
            codes.append(code)
    if not codes:
        return jsonify({"data": []})

    placeholders = ",".join(["%s"] * len(codes[:200]))
    stocks = execute_query(
        f"SELECT code, market FROM stocks WHERE code IN ({placeholders})",
        tuple(codes[:200]),
    )
    return jsonify({
        "data": [
            {
                "code": s["code"],
                "ytd_return": _fetch_ytd_return(s["code"], s.get("market")),
            }
            for s in stocks
        ]
    })


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
    keyword = _normalize_stock_code(request.args.get("keyword", "").strip())
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
    if re.fullmatch(r"\d{1,5}", keyword):
        hk = _lookup_hk_stock_info(keyword)
        if hk:
            return jsonify([hk])
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
            market = {"0": "SZ", "1": "SH", "116": "HK"}.get(str(mkt), "SH")
            if code and name:
                results.append({"code": _normalize_stock_code(code) if market == "HK" else code, "name": name, "market": market})
    except Exception:
        pass
    return jsonify(results)


@app.route("/api/stock-info/<code>")
def api_stock_info(code):
    code = _normalize_stock_code(code)
    if re.fullmatch(r"\d{5}", code):
        hk = _lookup_hk_stock_info(code)
        if hk:
            return jsonify(hk)
        return jsonify({"error": f"未找到港股代码 {code} 的信息"}), 404
    """根据股票代码从东方财富获取名称和市场信息"""
    # 尝试上海和深圳两个市场
    markets_to_try = []
    if code.startswith(("6", "5", "9")):
        markets_to_try = [("1", "SH"), ("0", "SZ")]
    else:
        markets_to_try = [("0", "SZ"), ("1", "SH")]

    name = None
    market = None
    industry = None
    for sec_market, our_market in markets_to_try:
        try:
            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58,f127,f300"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            if data.get("data") and data["data"].get("f58"):
                name = data["data"]["f58"]
                market = our_market
                industry = data["data"].get("f127")
                break
        except Exception:
            continue

    if not name:
        return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

    return jsonify({"code": code, "name": name, "market": market, "industry": industry})


@app.route("/api/stock", methods=["POST"])
def api_add_stock():
    data = request.get_json()
    code = _normalize_stock_code(data.get("code", "").strip())
    if not code:
        return jsonify({"error": "请输入股票代码"}), 400

    existing = Stock.get_by_code(code)
    if existing:
        return jsonify({"error": f"股票代码 {code} 已存在"}), 409

    # 如果没传名称或市场，自动从东方财富获取
    name = data.get("name", "").strip()
    market = data.get("market", "").strip()
    if not name or not market:
        if re.fullmatch(r"\d{5}", code):
            hk = _lookup_hk_stock_info(code)
            if hk:
                name = name or hk["name"]
                market = market or hk["market"]
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

    if market and market not in ("SH", "SZ", "BJ", "HK"):
        return jsonify({"error": "市场必须是 SH/SZ/BJ/HK"}), 400

    industry = data.get("industry") or _fetch_stock_industry(code, market or "SH")
    try:
        Stock.add(
            code=code,
            name=name,
            market=market or "SH",
            industry=industry,
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
    markets = {"SH": 0, "SZ": 0, "BJ": 0, "HK": 0}
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


def _eastmoney_secu_code(code, market=None):
    market = (market or "").upper()
    if market in {"SH", "SZ", "BJ"}:
        return f"{code}.{market}"
    if code.startswith(("6", "5", "9")):
        return f"{code}.SH"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _eastmoney_web_code(code, market=None):
    secu_code = _eastmoney_secu_code(code, market)
    code_part, market_part = secu_code.split(".")
    return f"{market_part}{code_part}"


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _date_only(value):
    if not value:
        return None
    return str(value)[:10]


def _money_yuan(value):
    n = _to_float(value)
    return n if n is not None else 0.0


@app.route("/api/stock/<code>/financing")
def api_stock_financing(code):
    stock = Stock.get_by_code(code)
    if not stock:
        return jsonify({"error": "未找到该股票"}), 404
    if (stock.get("market") or "").upper() == "HK":
        return jsonify({
            "source": "港股暂不支持 A 股分红融资口径",
            "annual": [],
            "details": [],
        })

    secu_code = _eastmoney_secu_code(code, stock.get("market"))
    try:
        resp = requests.get(
            "https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax",
            params={"code": secu_code},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/Index?code={stock.get('market', '')}{code}&type=web",
            },
            timeout=12,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        return jsonify({"error": "融资数据获取失败: " + str(e)}), 502

    annual_by_year = {}
    for row in _as_list(payload.get("lnfhrz")):
        year = str(row.get("STATISTICS_YEAR") or "").strip()
        if not year:
            continue
        annual_by_year[year] = {
            "year": year,
            "dividend_amount": _money_yuan(row.get("TOTAL_DIVIDEND")),
            "financing_amount": 0.0,
            "seo_shares": _money_yuan(row.get("SEO_NUM")),
            "allotment_shares": _money_yuan(row.get("ALLOTMENT_NUM")),
            "ipo_shares": _money_yuan(row.get("IPO_NUM")),
        }

    details = []

    def add_detail(row, financing_type):
        if not row:
            return
        notice_date = _date_only(row.get("NOTICE_DATE"))
        year = (notice_date or "")[:4]
        issue_price = _to_float(row.get("ISSUE_PRICE"))
        issue_shares = _money_yuan(row.get("ISSUE_NUM"))
        if financing_type == "增发":
            amount = _money_yuan(row.get("NET_RAISE_FUNDS") or row.get("TOTAL_RAISE_FUNDS"))
            method = row.get("ISSUE_WAY_EXPLAIN")
            price_method = row.get("ISSUE_PRICE_EXPLAIN")
            target = row.get("ISSUE_OBJECT") or row.get("ISSUE_TARGET") or row.get("OBJECT")
            listing_date = _date_only(row.get("LISTING_DATE"))
        else:
            amount = _money_yuan(row.get("TOTAL_RAISE_FUNDS") or row.get("NET_RAISE_FUNDS"))
            method = row.get("EVENT_EXPLAIN")
            price_method = row.get("ISSUE_PRICE_EXPLAIN")
            target = None
            listing_date = _date_only(row.get("EX_DIVIDEND_DATEE") or row.get("EX_DIVIDEND_DATE"))

        if year:
            annual = annual_by_year.setdefault(year, {
                "year": year,
                "dividend_amount": 0.0,
                "financing_amount": 0.0,
                "seo_shares": 0.0,
                "allotment_shares": 0.0,
                "ipo_shares": 0.0,
            })
            annual["financing_amount"] += amount

        details.append({
            "date": notice_date,
            "type": financing_type,
            "issue_price": issue_price,
            "issue_shares": issue_shares,
            "amount": amount,
            "amount_label": "实际募集净额" if financing_type == "增发" else "实际募资总额",
            "method": method,
            "price_method": price_method,
            "target": target,
            "registration_date": _date_only(row.get("REG_DATE") or row.get("EQUITY_RECORD_DATE")),
            "listing_date": listing_date,
            "receive_date": _date_only(row.get("RECEIVE_DATE")),
        })

    for row in _as_list(payload.get("zfmx")):
        add_detail(row, "增发")
    for row in _as_list(payload.get("pgmx")):
        add_detail(row, "配股")

    annual = []
    cumulative_dividend = 0.0
    cumulative_financing = 0.0
    for year, row in sorted(annual_by_year.items(), key=lambda item: item[0]):
        cumulative_dividend += row["dividend_amount"]
        cumulative_financing += row["financing_amount"]
        ratio = (cumulative_dividend / cumulative_financing * 100) if cumulative_financing > 0 else None
        annual.append({
            **row,
            "annual_dividend_amount": row["dividend_amount"],
            "annual_financing_amount": row["financing_amount"],
            "dividend_amount": cumulative_dividend,
            "financing_amount": cumulative_financing,
            "ratio": round(ratio, 2) if ratio is not None else None,
        })

    details.sort(key=lambda item: item.get("date") or "", reverse=True)
    return jsonify({
        "source": "东方财富 F10 分红融资",
        "annual": annual,
        "details": details,
    })


def _quarter_label(date_str):
    if not date_str:
        return ""
    year = date_str[:4]
    month_day = date_str[5:10]
    quarter_map = {
        "03-31": "Q1",
        "06-30": "Q2",
        "09-30": "Q3",
        "12-31": "Q4",
    }
    return f"{year}-{quarter_map.get(month_day, date_str[5:])}"


def _change_type(value):
    text = str(value or "").strip()
    if text == "新进":
        return "new"
    if text in {"不变", "持平"}:
        return "unchanged"
    if text in {"增加", "增持"}:
        return "increase"
    if text in {"减少", "减持"}:
        return "decrease"
    n = _to_float(text)
    if n is None:
        return ""
    if n > 0:
        return "increase"
    if n < 0:
        return "decrease"
    return "unchanged"


def _fetch_shareholder_periods_from_eastmoney(code, stock):
    secu_code = _eastmoney_secu_code(code, stock.get("market"))
    rows = []
    source = "东方财富数据中心 十大股东"

    try:
        params = {
            "sortColumns": "END_DATE,HOLDER_RANK",
            "sortTypes": "-1,1",
            "pageSize": "1000",
            "pageNumber": "1",
            "reportName": "RPT_F10_EH_FREEHOLDERS",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(SECURITY_CODE="{code}")',
        }
        resp = requests.get(
            "https://datacenter-web.eastmoney.com/api/data/v1/get",
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://data.eastmoney.com/gdfx/HoldingAnalyse.html",
            },
            timeout=12,
        )
        resp.raise_for_status()
        payload = resp.json()
        result = payload.get("result") or {}
        rows = _as_list(result.get("data"))
        pages = int(result.get("pages") or 1)
        for page_number in range(2, min(pages, 5) + 1):
            params["pageNumber"] = str(page_number)
            page_resp = requests.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://data.eastmoney.com/gdfx/HoldingAnalyse.html",
                },
                timeout=12,
            )
            page_resp.raise_for_status()
            page_payload = page_resp.json()
            rows.extend(_as_list((page_payload.get("result") or {}).get("data")))
    except Exception as e:
        app.logger.warning("datacenter shareholder fetch failed for %s: %s", code, e)

    rows_by_date = {}
    for row in rows:
        date = _date_only(row.get("END_DATE"))
        if not date:
            continue
        rank = int(_money_yuan(row.get("HOLDER_RANK")) or 0)
        if rank < 1 or rank > 10:
            continue
        change_label = row.get("HOLDNUM_CHANGE_NAME") or row.get("HOLD_CHANGE") or row.get("HOLD_NUM_CHANGE")
        change_num = _to_float(row.get("XZCHANGE"))
        if change_num is None:
            change_num = _to_float(row.get("HOLD_NUM_CHANGE"))
        rows_by_date.setdefault(date, []).append({
            "rank": rank,
            "name": row.get("HOLDER_NAME") or "",
            "shares_type": row.get("SHARES_TYPE") or "",
            "hold_num": _money_yuan(row.get("HOLD_NUM")),
            "hold_ratio": _to_float(row.get("HOLD_RATIO")) or _to_float(row.get("HOLD_NUM_RATIO")) or _to_float(row.get("FREE_HOLDNUM_RATIO")),
            "change": change_num if change_num is not None else change_label,
            "change_ratio": _to_float(row.get("CHANGE_RATIO")),
            "change_type": _change_type(change_label),
        })

    report_dates = {}
    if not rows_by_date:
        web_code = _eastmoney_web_code(code, stock.get("market"))
        try:
            resp = requests.get(
                "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax",
                params={"code": secu_code},
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={web_code}&type=web",
                },
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            report_dates = {
                _date_only(row.get("END_DATE")): str(row.get("IS_REPORTDATE") or "") == "1"
                for row in _as_list(payload.get("sdgd_date"))
                if _date_only(row.get("END_DATE"))
            }
            source = "东方财富 F10 股东研究"
            for date in list(report_dates.keys())[:40]:
                detail_resp = requests.get(
                    "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDGD",
                    params={"code": web_code, "date": date},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={web_code}&type=web",
                    },
                    timeout=8,
                )
                detail_resp.raise_for_status()
                detail_payload = detail_resp.json()
                for row in _as_list(detail_payload.get("sdgd")):
                    rank = int(_money_yuan(row.get("HOLDER_RANK")) or 0)
                    if rank < 1 or rank > 10:
                        continue
                    change_label = row.get("HOLD_NUM_CHANGE")
                    rows_by_date.setdefault(date, []).append({
                        "rank": rank,
                        "name": row.get("HOLDER_NAME") or "",
                        "shares_type": row.get("SHARES_TYPE") or "",
                        "hold_num": _money_yuan(row.get("HOLD_NUM")),
                        "hold_ratio": _to_float(row.get("HOLD_NUM_RATIO")),
                        "change": row.get("HOLD_NUM_CHANGE"),
                        "change_ratio": _to_float(row.get("CHANGE_RATIO")),
                        "change_type": _change_type(change_label),
                    })
        except Exception as e:
            raise RuntimeError("股东数据获取失败: " + str(e)) from e

    return _build_shareholder_periods(rows_by_date, report_dates), source


def _build_shareholder_periods(rows_by_date, report_dates=None):
    report_dates = report_dates or {}
    periods = []
    for date in sorted(rows_by_date.keys(), reverse=True):
        holders = sorted(rows_by_date[date], key=lambda item: item["rank"])
        top_ratio = sum(float(item["hold_ratio"] or 0) for item in holders)
        top_shares = sum(float(item["hold_num"] or 0) for item in holders)
        total_shares = None
        for item in holders:
            if item["hold_num"] and item["hold_ratio"] and item["hold_ratio"] > 0:
                total_shares = item["hold_num"] / (item["hold_ratio"] / 100)
                break
        periods.append({
            "date": date,
            "label": _quarter_label(date),
            "year": date[:4],
            "month_day": date[5:10],
            "is_report_date": report_dates.get(date, True),
            "total_shares": round(total_shares, 2) if total_shares else None,
            "top10_shares": round(top_shares, 2),
            "top10_ratio": round(top_ratio, 2),
            "holders": holders,
        })
    return periods


def _load_shareholder_periods_from_db(code):
    _ensure_shareholders_table()
    rows = execute_query(
        """SELECT report_date, holder_rank, holder_name, shares_type, hold_num, hold_ratio,
                  hold_change_label, hold_change_num, change_ratio, change_type,
                  is_report_date, source, fetched_at
           FROM stock_shareholders
           WHERE stock_code = %s
           ORDER BY report_date DESC, holder_rank ASC""",
        (code,),
    )
    rows_by_date = {}
    report_dates = {}
    source = None
    latest_fetched_at = None
    for row in rows:
        date = row["report_date"].strftime("%Y-%m-%d") if hasattr(row["report_date"], "strftime") else str(row["report_date"])
        fetched_at = row.get("fetched_at")
        if fetched_at and (latest_fetched_at is None or fetched_at > latest_fetched_at):
            latest_fetched_at = fetched_at
        if row.get("source") and not source:
            source = row["source"]
        report_dates[date] = bool(row.get("is_report_date"))
        change_num = row.get("hold_change_num")
        change = float(change_num) if change_num is not None else row.get("hold_change_label")
        rows_by_date.setdefault(date, []).append({
            "rank": int(row["holder_rank"]),
            "name": row.get("holder_name") or "",
            "shares_type": row.get("shares_type") or "",
            "hold_num": float(row["hold_num"]) if row.get("hold_num") is not None else None,
            "hold_ratio": float(row["hold_ratio"]) if row.get("hold_ratio") is not None else None,
            "change": change,
            "change_ratio": float(row["change_ratio"]) if row.get("change_ratio") is not None else None,
            "change_type": row.get("change_type") or "",
        })
    fetched_at_text = latest_fetched_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(latest_fetched_at, "strftime") else latest_fetched_at
    return _build_shareholder_periods(rows_by_date, report_dates), source, fetched_at_text


def _save_shareholder_periods_to_db(code, periods, source):
    if not periods:
        return 0
    _ensure_shareholders_table()
    values = []
    for period in periods:
        date = period.get("date")
        if not date:
            continue
        for holder in period.get("holders") or []:
            rank = int(holder.get("rank") or 0)
            name = holder.get("name") or ""
            if rank < 1 or rank > 10 or not name:
                continue
            change = holder.get("change")
            change_num = change if isinstance(change, (int, float)) else _to_float(change)
            values.append((
                code,
                date,
                rank,
                name,
                holder.get("shares_type") or None,
                holder.get("hold_num"),
                holder.get("hold_ratio"),
                None if change_num is not None else (str(change) if change not in (None, "") else None),
                change_num,
                holder.get("change_ratio"),
                holder.get("change_type") or None,
                1 if period.get("is_report_date", True) else 0,
                source,
            ))
    if not values:
        return 0

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany(
            """INSERT INTO stock_shareholders (
                   stock_code, report_date, holder_rank, holder_name, shares_type,
                   hold_num, hold_ratio, hold_change_label, hold_change_num,
                   change_ratio, change_type, is_report_date, source, fetched_at
               ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
               ON DUPLICATE KEY UPDATE
                   holder_name = VALUES(holder_name),
                   shares_type = VALUES(shares_type),
                   hold_num = VALUES(hold_num),
                   hold_ratio = VALUES(hold_ratio),
                   hold_change_label = VALUES(hold_change_label),
                   hold_change_num = VALUES(hold_change_num),
                   change_ratio = VALUES(change_ratio),
                   change_type = VALUES(change_type),
                   is_report_date = VALUES(is_report_date),
                   source = VALUES(source),
                   fetched_at = NOW(),
                   updated_at = CURRENT_TIMESTAMP""",
            values,
        )
        conn.commit()
        return len(values)
    finally:
        cursor.close()
        conn.close()


@app.route("/api/stock/<code>/shareholders")
def api_stock_shareholders(code):
    stock = Stock.get_by_code(code)
    if not stock:
        return jsonify({"error": "未找到该股票"}), 404
    if (stock.get("market") or "").upper() == "HK":
        return jsonify({
            "source": "港股暂不支持 A 股前十大股东口径",
            "periods": [],
        })

    refresh = request.args.get("refresh") in {"1", "true", "yes"}
    if not refresh:
        periods, source, fetched_at = _load_shareholder_periods_from_db(code)
        if periods:
            return jsonify({
                "source": f"本地缓存 · {source or '前十大股东'}",
                "cached": True,
                "fetched_at": fetched_at,
                "periods": periods,
            })

    try:
        periods, source = _fetch_shareholder_periods_from_eastmoney(code, stock)
    except Exception as e:
        periods, source, fetched_at = _load_shareholder_periods_from_db(code)
        if periods:
            return jsonify({
                "source": f"本地缓存 · 外部刷新失败: {e}",
                "cached": True,
                "fetched_at": fetched_at,
                "periods": periods,
            })
        return jsonify({"error": str(e)}), 502

    saved_count = _save_shareholder_periods_to_db(code, periods, source)

    return jsonify({
        "source": source,
        "cached": False,
        "saved_count": saved_count,
        "periods": periods,
    })


# ==================== 互动易 API ====================

def _irm_source_label(value):
    return {
        "2": "APP",
        "4": "网站",
        "5": "公众号",
        "6": "网站",
    }.get(str(value or ""), "网站")


def _irm_dt(value):
    n = _to_float(value)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _sse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y年%m月%d日 %H:%M").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _first_item(value):
    if isinstance(value, list) and value:
        return value[0]
    return value or ""


def _irm_headers():
    return {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://irm.cninfo.com.cn/",
        "Origin": "https://irm.cninfo.com.cn",
    }


def _irm_request_json(session, method, url, **kwargs):
    resp = session.request(method, url, headers=_irm_headers(), timeout=12, **kwargs)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.json()


def _clean_html_text(value):
    text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _irm_fetch_org_id(session, code):
    payload = _irm_request_json(
        session,
        "POST",
        "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
        params={"_t": str(int(time.time()))},
        data={"keyWord": code},
    )
    candidates = _as_list(payload.get("data"))
    exact = [item for item in candidates if str(item.get("stockCode") or "") == code]
    candidates = exact or candidates
    for item in candidates:
        secid = str(item.get("secid") or "")
        if secid.startswith("gssz"):
            return secid
    return str(candidates[0].get("secid") or "") if candidates else ""


def _insert_irm_row(row_data):
    execute_query(
        """INSERT INTO irm_interactions (
            stock_code, stock_name, org_id, question_id, answer_id, industry, board_type,
            question, answer, questioner, answerer, source, question_time, answer_time,
            update_time, praise_count, favorite_count, forward_count, original_url, raw_json
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
        ) ON DUPLICATE KEY UPDATE
            answer=VALUES(answer),
            answer_id=VALUES(answer_id),
            answerer=VALUES(answerer),
            answer_time=VALUES(answer_time),
            update_time=VALUES(update_time),
            praise_count=VALUES(praise_count),
            favorite_count=VALUES(favorite_count),
            forward_count=VALUES(forward_count),
            raw_json=VALUES(raw_json)""",
        (
            row_data.get("stock_code"),
            row_data.get("stock_name"),
            row_data.get("org_id"),
            row_data.get("question_id"),
            row_data.get("answer_id"),
            row_data.get("industry"),
            row_data.get("board_type"),
            row_data.get("question") or "",
            row_data.get("answer") or "",
            row_data.get("questioner"),
            row_data.get("answerer"),
            row_data.get("source"),
            row_data.get("question_time"),
            row_data.get("answer_time"),
            row_data.get("update_time"),
            int(_money_yuan(row_data.get("praise_count")) or 0),
            int(_money_yuan(row_data.get("favorite_count")) or 0),
            int(_money_yuan(row_data.get("forward_count")) or 0),
            row_data.get("original_url"),
            json.dumps(row_data.get("raw") or {}, ensure_ascii=False),
        ),
        fetch=False,
    )


def _sync_cninfo_irm_stock(code, stock_name=None, max_pages=2, stop_on_duplicate=True):
    session = requests.Session()
    org_id = _irm_fetch_org_id(session, code)
    if not org_id:
        return {"code": code, "inserted": 0, "skipped": 0, "message": "未找到互动易组织代码"}

    existing_rows = execute_query("SELECT question_id FROM irm_interactions WHERE stock_code=%s", (code,))
    existing_ids = {str(row["question_id"]) for row in existing_rows}
    inserted = 0
    skipped = 0
    duplicate_seen = 0
    total_rows = 0
    total_pages = max_pages

    for page_num in range(1, max_pages + 1):
        payload = _irm_request_json(
            session,
            "POST",
            "https://irm.cninfo.com.cn/newircs/company/question",
            params={
                "_t": str(int(time.time())),
                "stockcode": code,
                "orgId": org_id,
                "pageSize": "20",
                "pageNum": str(page_num),
                "keyWord": "",
                "startDay": "",
                "endDay": "",
            },
        )
        total_pages = min(int(payload.get("totalPage") or max_pages), max_pages)
        rows = _as_list(payload.get("rows"))
        if not rows:
            break

        for row in rows:
            total_rows += 1
            question_id = str(row.get("indexId") or "")
            answer = str(row.get("attachedContent") or "").strip()
            if not question_id or not answer:
                skipped += 1
                continue
            if question_id in existing_ids:
                duplicate_seen += 1
                skipped += 1
                continue

            _insert_irm_row({
                "stock_code": code,
                "stock_name": row.get("companyShortName") or stock_name,
                "org_id": org_id,
                "question_id": question_id,
                "answer_id": row.get("attachedId"),
                "industry": _first_item(row.get("trade")),
                "board_type": _first_item(row.get("boardType")),
                "question": row.get("mainContent") or "",
                "answer": answer,
                "questioner": row.get("authorName") or row.get("author"),
                "answerer": row.get("attachedAuthor"),
                "source": _irm_source_label(row.get("pubClient")),
                "question_time": _irm_dt(row.get("pubDate")),
                "answer_time": _irm_dt(row.get("attachedPubDate")) or _irm_dt(row.get("updateDate")),
                "update_time": _irm_dt(row.get("updateDate")),
                "praise_count": row.get("praiseCount"),
                "favorite_count": row.get("favoriteCount"),
                "forward_count": row.get("forwardCount"),
                "original_url": f"https://irm.cninfo.com.cn/ircs/question/questionDetail?questionId={question_id}",
                "raw": row,
            })
            existing_ids.add(question_id)
            inserted += 1

        if page_num >= total_pages:
            break
        if stop_on_duplicate and duplicate_seen and inserted == 0:
            break

    return {
        "code": code,
        "org_id": org_id,
        "inserted": inserted,
        "skipped": skipped,
        "total_rows": total_rows,
    }


def _parse_sse_items(html_text, code, stock_name, com_id):
    items = re.findall(r'<div class="m_feed_item"[\s\S]*?(?=<div class="m_feed_item"|$)', html_text or "")
    parsed = []
    for item in items:
        if "answer_ico" not in item:
            continue
        mid = re.search(r'id="item-(\d+)"', item)
        if not mid:
            continue
        txt_blocks = re.findall(r'<div class="m_feed_txt"[^>]*>([\s\S]*?)</div>', item)
        if len(txt_blocks) < 2:
            continue
        question = _clean_html_text(txt_blocks[0])
        answer = _clean_html_text(txt_blocks[1])
        if not question or not answer:
            continue
        question = re.sub(rf"^:?{re.escape(stock_name or '')}\({code}\)", "", question).strip()
        question = re.sub(rf"^:?.*?\({code}\)", "", question).strip()
        author_blocks = re.findall(r'<div class="m_feed_face">([\s\S]*?)</div>', item)
        questioner = _clean_html_text(author_blocks[0]) if author_blocks else None
        answerer = _clean_html_text(author_blocks[1]) if len(author_blocks) > 1 else stock_name
        time_blocks = re.findall(r'<div class="m_feed_from"[^>]*>[\s\S]*?<span>([\s\S]*?)</span>', item)
        question_time = _sse_dt(_clean_html_text(time_blocks[0])) if time_blocks else None
        answer_time = _sse_dt(_clean_html_text(time_blocks[1])) if len(time_blocks) > 1 else None
        source_match = re.findall(r'<div class="m_feed_from"[^>]*>[\s\S]*?<a href="javascript:;">([\s\S]*?)</a>', item)
        parsed.append({
            "stock_code": code,
            "stock_name": stock_name,
            "org_id": str(com_id),
            "question_id": f"sse-{mid.group(1)}",
            "answer_id": f"sse-answer-{mid.group(1)}",
            "industry": None,
            "board_type": "SSE",
            "question": question,
            "answer": answer,
            "questioner": questioner,
            "answerer": answerer,
            "source": _clean_html_text(source_match[-1]) if source_match else "上证e互动",
            "question_time": question_time,
            "answer_time": answer_time,
            "update_time": answer_time or question_time,
            "praise_count": 0,
            "favorite_count": 0,
            "forward_count": 0,
            "original_url": f"https://sns.sseinfo.com/company.do?stockcode={code}",
            "raw": {"item_id": mid.group(1), "platform": "sse"},
        })
    return parsed


def _sync_sse_irm_stock(code, stock_name=None, max_pages=2, stop_on_duplicate=True):
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://sns.sseinfo.com/qa.do"}
    resp = session.post(
        "https://sns.sseinfo.com/ajax/getCompany.do",
        data={"data": code},
        headers=headers,
        timeout=12,
    )
    resp.encoding = "utf-8"
    resp.raise_for_status()
    com_id = (resp.text or "").strip()
    if not com_id:
        return {"code": code, "inserted": 0, "skipped": 0, "message": "未找到上证 e 互动公司代码"}

    existing_rows = execute_query("SELECT question_id FROM irm_interactions WHERE stock_code=%s", (code,))
    existing_ids = {str(row["question_id"]) for row in existing_rows}
    inserted = 0
    skipped = 0
    duplicate_seen = 0
    total_rows = 0

    for page_num in range(1, max_pages + 1):
        resp = session.post(
            "https://sns.sseinfo.com/getNewDataFullText.do",
            data={"sdate": "", "edate": "", "keyword": "", "type": "1", "page": str(page_num), "comId": com_id},
            headers=headers,
            timeout=12,
        )
        resp.encoding = "utf-8"
        resp.raise_for_status()
        rows = _parse_sse_items(resp.text, code, stock_name, com_id)
        if not rows:
            if page_num == 1:
                total_rows += len(re.findall(r'<div class="m_feed_item"', resp.text or ""))
            break
        total_rows += len(rows)
        for row in rows:
            question_id = row["question_id"]
            if question_id in existing_ids:
                duplicate_seen += 1
                skipped += 1
                continue
            _insert_irm_row(row)
            existing_ids.add(question_id)
            inserted += 1
        if stop_on_duplicate and duplicate_seen and inserted == 0:
            break
    return {
        "code": code,
        "org_id": str(com_id),
        "inserted": inserted,
        "skipped": skipped,
        "total_rows": total_rows,
    }


def _sync_irm_stock(code, stock_name=None, market=None, max_pages=2, stop_on_duplicate=True):
    market = (market or "").upper()
    if market == "SH":
        return _sync_sse_irm_stock(code, stock_name, max_pages=max_pages, stop_on_duplicate=stop_on_duplicate)
    return _sync_cninfo_irm_stock(code, stock_name, max_pages=max_pages, stop_on_duplicate=stop_on_duplicate)


def _sync_irm_all_background(max_pages=2):
    global _irm_sync_running, _irm_sync_started_at, _irm_sync_finished_at, _irm_sync_last_result
    total = 0
    inserted = 0
    skipped = 0
    errors = []
    with _irm_sync_lock:
        if _irm_sync_running:
            return
        _irm_sync_running = True
        _irm_sync_started_at = datetime.now().isoformat(timespec="seconds")
        _irm_sync_finished_at = None
        _irm_sync_last_result = {
            "status": "running",
            "message": "正在抓取互动易",
            "updated_at": _irm_sync_started_at,
            "scope": "all",
            "total": 0,
            "inserted": 0,
            "skipped": 0,
            "errors": [],
        }

    try:
        stocks = execute_query("SELECT code, name, market FROM stocks WHERE status='正常' ORDER BY display_order IS NULL, display_order, code")
        for stock in stocks:
            code = stock["code"]
            market = (stock.get("market") or "").upper()
            if market not in {"SZ", "SH"}:
                skipped += 1
                continue
            total += 1
            try:
                result = _sync_irm_stock(code, stock.get("name"), market=market, max_pages=max_pages)
                inserted += result.get("inserted", 0)
                skipped += result.get("skipped", 0)
            except Exception as e:
                errors.append(f"{code}: {e}")
            time.sleep(0.25)
    except Exception as e:
        errors.append(str(e))
    finally:
        finished_at = datetime.now().isoformat(timespec="seconds")
        with _irm_sync_lock:
            _irm_sync_running = False
            _irm_sync_finished_at = finished_at
            _irm_sync_last_result = {
                "status": "done" if not errors else "partial",
                "message": f"互动易抓取完成，新增 {inserted} 条" if not errors else f"互动易抓取部分完成，新增 {inserted} 条，失败 {len(errors)} 只",
                "updated_at": finished_at,
                "scope": "all",
                "total": total,
                "inserted": inserted,
                "skipped": skipped,
                "errors": errors[:20],
            }


def _irm_status():
    with _irm_sync_lock:
        return {
            **_irm_sync_last_result,
            "running": _irm_sync_running,
            "started_at": _irm_sync_started_at,
            "finished_at": _irm_sync_finished_at,
        }


@app.route("/api/irm/status")
def api_irm_status():
    return jsonify(_irm_status())


@app.route("/api/irm/sync", methods=["POST"])
def api_irm_sync_all():
    if _irm_status().get("running"):
        return jsonify({"ok": True, "already_running": True, **_irm_status()})
    thread = threading.Thread(target=_sync_irm_all_background, kwargs={"max_pages": 2}, daemon=True)
    thread.start()
    return jsonify({"ok": True, "started": True, **_irm_status()})


@app.route("/api/stock/<code>/irm")
def api_stock_irm(code):
    stock = Stock.get_by_code(code)
    if not stock:
        return jsonify({"error": "未找到该股票"}), 404
    rows = execute_query(
        """SELECT question_id, answer_id, stock_code, stock_name, industry, question, answer,
                  questioner, answerer, source, question_time, answer_time, update_time,
                  praise_count, favorite_count, forward_count, original_url
           FROM irm_interactions
           WHERE stock_code=%s
           ORDER BY COALESCE(answer_time, update_time, question_time) DESC, id DESC
           LIMIT 200""",
        (code,),
    )
    items = []
    for row in rows:
        items.append({
            **row,
            "question_time": str(row["question_time"]) if row.get("question_time") else None,
            "answer_time": str(row["answer_time"]) if row.get("answer_time") else None,
            "update_time": str(row["update_time"]) if row.get("update_time") else None,
        })
    return jsonify({
        "source": "互动问答",
        "items": items,
        "sync": _irm_status(),
        "supported": (stock.get("market") or "").upper() in {"SZ", "SH"},
    })


@app.route("/api/stock/<code>/irm/sync", methods=["POST"])
def api_stock_irm_sync(code):
    stock = Stock.get_by_code(code)
    if not stock:
        return jsonify({"error": "未找到该股票"}), 404
    market = (stock.get("market") or "").upper()
    if market not in {"SZ", "SH"}:
        return jsonify({"ok": True, "inserted": 0, "skipped": 0, "message": "互动问答暂只支持沪深股票"})
    try:
        result = _sync_irm_stock(code, stock.get("name"), market=market, max_pages=5, stop_on_duplicate=False)
        return jsonify({"ok": True, **result})
    except Exception as e:
        return jsonify({"error": "互动易抓取失败: " + str(e)}), 502


# ==================== 数据更新 API ====================

@app.route("/api/update-dividends", methods=["POST"])
def api_update_dividends():
    """从东方财富和新浪财经更新股票的分红和净利润数据
    mode: full=全量更新, incremental=增量更新(仅更新有缺失的年份)
    """
    payload = request.get_json(silent=True) if request.is_json else {}
    mode = payload.get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = _get_update_stocks(payload, include_name_market=True)
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


def _get_update_stocks(payload=None, include_name_market=False):
    """Return all active stocks, or one explicit stock when code is provided."""
    payload = payload or {}
    code = (payload.get("code") or request.args.get("code") or "").strip()
    columns = "code, name, market" if include_name_market else "code"
    if code:
        code = _normalize_stock_code(code)
        return execute_query(f"SELECT {columns} FROM stocks WHERE code=%s", (code,))
    return execute_query(f"SELECT {columns} FROM stocks WHERE status='正常'")


@app.route("/api/update-financials", methods=["POST"])
def api_update_financials():
    """从东方财富拉取财务数据并存入 custom_financials 表
    mode: full=全量拉取, incremental=增量拉取(仅更新无数据的记录)
    支持年报+季报（全部报告类型）。
    """
    payload = request.get_json(silent=True) if request.is_json else {}
    mode = "full"
    if request.is_json:
        mode = payload.get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    # 确保新字段列存在
    _ensure_financials_columns()

    # REPORT_TYPE → report_period
    period_map = {"年报": "FY", "三季报": "Q3", "中报": "Q2", "一季报": "Q1"}

    try:
        stocks = _get_update_stocks(payload)
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

    balance_extra_fields = [
        "monetary_funds", "accounts_receivable", "inventory", "fixed_assets", "goodwill",
        "total_assets", "short_borrow", "long_borrow", "bonds_payable", "total_liabilities",
        "parent_equity", "total_equity",
    ]
    income_extra_fields = [
        "total_revenue", "operating_revenue", "operating_cost", "cost_of_revenue",
        "selling_expense", "admin_expense", "finance_expense", "rd_expense",
        "invest_income", "operating_profit", "total_profit", "net_profit",
        "parent_net_profit", "basic_eps",
    ]
    cashflow_extra_fields = [
        "cf_sales_goods", "cf_oper_inflow", "cf_oper_outflow", "cf_oper_net",
        "cf_invest_net", "cf_buy_assets", "cf_finance_inflow", "cf_repay_debt",
        "cf_dividend_interest", "cf_finance_net",
    ]
    extra_select = ",\n                  " + ",\n                  ".join(
        [f"bs.{f} AS bs_{f}" for f in balance_extra_fields]
        + [f"inc.{f} AS inc_{f}" for f in income_extra_fields]
        + [f"cfs.{f} AS cf_{f}" for f in cashflow_extra_fields]
    )

    rows = execute_query(
        f"""SELECT cf.fiscal_year, cf.report_period, cf.total_revenue, cf.operate_profit, cf.parent_profit,
                  cf.deducted_profit, cf.operate_cashflow, cf.roe, cf.deducted_roe, cf.roic,
                  cf.total_assets, cf.total_equity, cf.total_shares,
                  cf.basic_eps, cf.debt_ratio,
                  cf.short_borrow, cf.noncurrent_liab_due1y, cf.long_borrow, cf.bonds_payable,
                  cf.interest_bearing_debt_ratio,
                  d.dividend_amount, d.dividend_per_share
                  {extra_select}
           FROM custom_financials cf
           LEFT JOIN dividends d ON cf.stock_code = d.stock_code AND cf.fiscal_year = d.fiscal_year
           LEFT JOIN balance_sheets bs ON cf.stock_code = bs.stock_code
                AND cf.fiscal_year = bs.fiscal_year AND cf.report_period = bs.report_period
           LEFT JOIN income_statements inc ON cf.stock_code = inc.stock_code
                AND cf.fiscal_year = inc.fiscal_year AND cf.report_period = inc.report_period
           LEFT JOIN cash_flows cfs ON cf.stock_code = cfs.stock_code
                AND cf.fiscal_year = cfs.fiscal_year AND cf.report_period = cfs.report_period
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

        def extra_val(prefix, field):
            value = r.get(f"{prefix}_{field}")
            return float(value) if value is not None else None

        extras = {}
        for field in balance_extra_fields:
            extras[f"bs_{field}"] = extra_val("bs", field)
        for field in income_extra_fields:
            extras[f"inc_{field}"] = extra_val("inc", field)
        for field in cashflow_extra_fields:
            extras[f"cf_{field}"] = extra_val("cf", field)

        inc_revenue = extras.get("inc_operating_revenue") or extras.get("inc_total_revenue")
        inc_cost = extras.get("inc_cost_of_revenue")
        if inc_cost is None:
            inc_cost = extras.get("inc_operating_cost")
        extras["inc_gross_margin"] = (
            round((inc_revenue - inc_cost) / inc_revenue * 100, 2)
            if inc_revenue and inc_cost is not None else None
        )
        extras["bs_goodwill_to_parent_equity"] = (
            round(extras.get("bs_goodwill") / extras.get("bs_parent_equity") * 100, 2)
            if extras.get("bs_goodwill") is not None and extras.get("bs_parent_equity") else None
        )
        extras["cf_free_cashflow"] = (
            round(extras.get("cf_cf_oper_net") - extras.get("cf_cf_buy_assets"), 4)
            if extras.get("cf_cf_oper_net") is not None and extras.get("cf_cf_buy_assets") is not None else None
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
            **extras,
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
        flow_fields += [f"inc_{f}" for f in income_extra_fields if f != "basic_eps"]
        flow_fields += [f"cf_{f}" for f in cashflow_extra_fields]

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
            inc_rev_s = single.get("inc_operating_revenue") or single.get("inc_total_revenue")
            inc_cost_s = single.get("inc_cost_of_revenue")
            if inc_cost_s is None:
                inc_cost_s = single.get("inc_operating_cost")
            single["inc_gross_margin"] = (
                round((inc_rev_s - inc_cost_s) / inc_rev_s * 100, 2)
                if inc_rev_s and inc_cost_s is not None else None
            )
            single["cf_free_cashflow"] = (
                round(single.get("cf_cf_oper_net") - single.get("cf_cf_buy_assets"), 4)
                if single.get("cf_cf_oper_net") is not None and single.get("cf_cf_buy_assets") is not None else None
            )
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
    payload = request.get_json(silent=True) if request.is_json else {}
    mode = "full"
    if request.is_json:
        mode = payload.get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = _get_update_stocks(payload)
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
    days = request.args.get("days", 1095, type=int) or 1095
    days = max(365, min(days, 36500))
    cache_key = (code, days)
    with _valuation_cache_lock:
        cached = _valuation_cache.get(cache_key)
        if cached and time.time() - cached["time"] < VALUATION_CACHE_SECONDS:
            return jsonify({**cached["data"], "cached": True})

    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _get_json(url, timeout=12):
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            return resp.json()

        report_type_map = {
            "%E5%B9%B4%E6%8A%A5": "FY",
            "%E4%B8%80%E5%AD%A3%E6%8A%A5": "Q1",
            "%E5%8D%8A%E5%B9%B4%E6%8A%A5": "Q2",
            "%E4%B8%89%E5%AD%A3%E6%8A%A5": "Q3",
        }
        finance_rows_by_type = {}
        # 1. 获取所有财报季度的归母净利润 + 总股本，用于 TTM PE 计算
        # PE = 市值 / TTM归母净利润（比EPSJB更精确，避免股本变动和四舍五入误差）
        eps_records = []  # [(report_date, report_type, fiscal_year, parent_eps), ...]
        finance_urls = {}
        for report_type in report_type_map.keys():
            url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                   "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                   f"&filter=(SECURITY_CODE=%22{code}%22)(REPORT_TYPE=%22{report_type}%22)"
                   "&pageSize=50&sortColumns=REPORT_DATE&sortTypes=-1")
            finance_urls[report_type] = url
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {executor.submit(_get_json, url, 15): report_type for report_type, url in finance_urls.items()}
            for future in as_completed(future_map):
                report_type = future_map[future]
                try:
                    data = future.result()
                    if data.get("success"):
                        rows = data["result"]["data"]
                        finance_rows_by_type[report_type] = rows
                        for item in rows:
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
        current_year = datetime.now().year
        history_years = max(1, int(days / 365) + 1)
        start_year = current_year - history_years
        max_batches = 3 if days <= 1825 else (5 if days <= 3650 else 10)
        price_data = []
        try:
            # 第一段：最近数据
            urls = [f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,640,qfq"]
            for y in range(current_year - 1, start_year - 1, -2):
                urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{max(start_year, y-1)}-01-01,{y}-12-31,640,qfq")
            seen = set()
            with ThreadPoolExecutor(max_workers=min(6, len(urls[:max_batches]))) as executor:
                futures = [executor.submit(_get_json, u, 10) for u in urls[:max_batches]]
                results = []
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception:
                        pass
            for d2 in results:
                try:
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
            for y in range(current_year - 1, start_year - 1, -2):
                raw_urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,{max(start_year, y-1)}-01-01,{y}-12-31,640")
            seen_raw = set()
            with ThreadPoolExecutor(max_workers=min(6, len(raw_urls[:max_batches]))) as executor:
                futures = [executor.submit(_get_json, u, 10) for u in raw_urls[:max_batches]]
                results = []
                for future in as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception:
                        pass
            for d2 in results:
                try:
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

        pb_data = []
        try:
            # 获取东方财富财报数据（含 TOTAL_SHARE），同时匹配 balance_sheets 的归母权益和商誉
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

            # 从东方财富获取 total_share 并匹配 balance_sheets 构建 每股净资产
            bv_records = []  # [(report_date, effective_date, bvps), ...]
            for report_type, rows in finance_rows_by_type.items():
                for item in rows:
                    rd = item.get("REPORT_DATE", "")
                    total_share = item.get("TOTAL_SHARE")
                    fy = int(item.get("REPORT_YEAR")) if item.get("REPORT_YEAR") else (int(rd[:4]) if rd[:4].isdigit() else 0)
                    rp = report_type_map.get(report_type, "FY")
                    if not rd or not total_share or int(total_share) <= 0 or not fy:
                        continue
                    bs_key = (fy, rp)
                    if bs_key in bs_map:
                        parent_eq_亿, goodwill_亿 = bs_map[bs_key]
                        net_equity = (parent_eq_亿 - goodwill_亿) * 1e8
                        if net_equity > 0:
                            bvps = net_equity / int(total_share)
                            if rp == "FY":
                                effective = datetime(fy + 1, 5, 1)
                            elif rp == "Q2":
                                effective = datetime(fy, 9, 1)
                            elif rp == "Q3":
                                effective = datetime(fy, 11, 1)
                            else:
                                effective = datetime(fy, 5, 1)
                            bv_records.append((rd[:10], effective, bvps))

            bv_records.sort(key=lambda x: x[1])  # 按生效日期排序

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

        cutoff_date = datetime.fromtimestamp(time.time() - days * 86400).strftime("%Y-%m-%d")
        if days <= 3650:
            pe_data = [item for item in pe_data if item["date"] >= cutoff_date]
            pb_data = [item for item in pb_data if item["date"] >= cutoff_date]
            price_data = [item for item in price_data if item["date"] >= cutoff_date]
            dividend_yield_data = [item for item in dividend_yield_data if item["date"] >= cutoff_date]

        payload = {
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
            "cached": False,
        }
        with _valuation_cache_lock:
            _valuation_cache[cache_key] = {"time": time.time(), "data": payload}
        return jsonify(payload)
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
    ("利息支出", "interest_expense"),
    ("手续费及佣金支出", "fee_commission_expense"),
    ("销售费用", "selling_expense"),
    ("管理费用", "admin_expense"),
    ("财务费用", "finance_expense"),
    ("利息费用", "finance_interest_expense"),
    ("其中：利息收入", "finance_interest_income"),
    ("研发费用", "rd_expense"),
    ("利息收入", "interest_income"),
    ("公允价值变动收益", "fair_value_change"),
    ("信用减值损失", "credit_impairment_loss"),
    ("资产减值损失", "asset_impairment_loss"),
    ("资产处置收益", "asset_disposal_income"),
    ("其他收益", "other_income"),
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
INCOME_SUPPLEMENT_COLUMNS = [
    "interest_income",
    "finance_interest_expense",
    "finance_interest_income",
    "interest_expense",
    "fee_commission_expense",
    "credit_impairment_loss",
    "asset_impairment_loss",
    "asset_disposal_income",
    "other_income",
]

EASTMONEY_INCOME_FIELD_MAP = {
    "TOTAL_OPERATE_INCOME": ("total_revenue", True),
    "OPERATE_INCOME": ("operating_revenue", True),
    "TOTAL_OPERATE_COST": ("operating_cost", True),
    "OPERATE_COST": ("cost_of_revenue", True),
    "INTEREST_EXPENSE": ("interest_expense", True),
    "FEE_COMMISSION_EXPENSE": ("fee_commission_expense", True),
    "OPERATE_TAX_ADD": ("tax_surcharge", True),
    "SALE_EXPENSE": ("selling_expense", True),
    "MANAGE_EXPENSE": ("admin_expense", True),
    "FINANCE_EXPENSE": ("finance_expense", True),
    "FE_INTEREST_EXPENSE": ("finance_interest_expense", True),
    "FE_INTEREST_INCOME": ("finance_interest_income", True),
    "RESEARCH_EXPENSE": ("rd_expense", True),
    "INTEREST_INCOME": ("interest_income", True),
    "FAIRVALUE_CHANGE_INCOME": ("fair_value_change", True),
    "CREDIT_IMPAIRMENT_LOSS": ("credit_impairment_loss", True),
    "ASSET_IMPAIRMENT_LOSS": ("asset_impairment_loss", True),
    "ASSET_DISPOSAL_INCOME": ("asset_disposal_income", True),
    "OTHER_INCOME": ("other_income", True),
    "INVEST_INCOME": ("invest_income", True),
    "OPERATE_PROFIT": ("operating_profit", True),
    "NONBUSINESS_INCOME": ("nonop_income", True),
    "NONBUSINESS_EXPENSE": ("nonop_expense", True),
    "TOTAL_PROFIT": ("total_profit", True),
    "INCOME_TAX": ("income_tax", True),
    "NETPROFIT": ("net_profit", True),
    "PARENT_NETPROFIT": ("parent_net_profit", True),
    "MINORITY_INTEREST": ("minority_profit", True),
    "BASIC_EPS": ("basic_eps", False),
    "DILUTED_EPS": ("diluted_eps", False),
    "OTHER_COMPRE_INCOME": ("other_comprehensive", True),
    "TOTAL_COMPRE_INCOME": ("total_comprehensive", True),
    "PARENT_TCI": ("parent_comprehensive", True),
}

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


def _parse_report_period(report_date):
    if not report_date:
        return None
    m = re.match(r"(\d{4})-(\d{2})-\d{2}", str(report_date))
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2))
    return year, {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")


def _fetch_eastmoney_income(stock_code):
    url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    resp = requests.get(
        url,
        params={
            "reportName": "RPT_F10_FINANCE_GINCOME",
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
    data = resp.json()
    rows = (data.get("result") or {}).get("data") or []
    result = {}
    for row in rows:
        key = _parse_report_period(row.get("REPORT_DATE"))
        if not key:
            continue
        values = result.setdefault(key, {})
        for source_field, (target_col, is_amount) in EASTMONEY_INCOME_FIELD_MAP.items():
            raw = row.get(source_field)
            if raw in (None, "", "--"):
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if is_amount:
                value = value / 100000000
            values[target_col] = round(value, 4)
    return {k: v for k, v in result.items() if v}


def _merge_income_sources(primary, supplement):
    for key, values in supplement.items():
        merged = primary.setdefault(key, {})
        for col, value in values.items():
            if value is not None:
                merged[col] = value
    return primary


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
    stocks = _get_update_stocks(payload)

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
    payload = request.get_json(silent=True) if request.is_json else {}
    mode = payload.get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = _get_update_stocks(payload)
    updated = 0
    errors = []

    for s in stocks:
        code = s["code"]
        try:
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/part/displaytype/0.phtml"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "gbk"
            all_years = _parse_sina_finance(resp.text, INCOME_ROW_MAP)
            eastmoney_years = _fetch_eastmoney_income(code)
            all_years = _merge_income_sources(all_years, eastmoney_years)

            existing = set()
            if mode == "incremental":
                for r in execute_query("SELECT fiscal_year, report_period FROM income_statements WHERE stock_code=%s", (code,)):
                    existing.add((r["fiscal_year"], r["report_period"]))

            for (year, rp), values in sorted(all_years.items()):
                has_new_supplement = any(values.get(c) is not None for c in INCOME_SUPPLEMENT_COLUMNS)
                if mode == "incremental" and (year, rp) in existing and not has_new_supplement:
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
    payload = request.get_json(silent=True) if request.is_json else {}
    mode = payload.get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = _get_update_stocks(payload)
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
    print("stock Web 服务启动: http://127.0.0.1:5002")
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
        _ensure_shareholders_table()
        print("✓ 已确保 custom_financials 表结构完整")
    except Exception as e:
        print(f"⚠ 表结构检查异常: {e}")
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
