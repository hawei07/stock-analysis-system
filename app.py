"""stock - Web 服务"""

from flask import Flask, jsonify, has_request_context, request
import sys
import re
import time
import json
import os
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
APP_DIR = os.path.dirname(os.path.abspath(__file__))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)


from models import Stock
from db import execute_insert, execute_many, execute_query, execute_update, get_connection, transaction
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
from services import app_settings
from services import cloud_backup_storage
from services import mysql_tools
from services.stock_identity import (
    eastmoney_secu_code as _eastmoney_secu_code,
    eastmoney_web_code as _eastmoney_web_code,
    fetch_stock_industry as _fetch_stock_industry,
    lookup_hk_stock_info as _lookup_hk_stock_info,
    normalize_stock_code as _normalize_stock_code,
    quote_symbol as _quote_symbol,
)
from services.sticky_notes_service import (
    cleanup_images as sticky_cleanup_images,
    extract_images as sticky_extract_images,
    load_notes as sticky_load_notes,
    save_notes as sticky_save_notes,
)
from services import stock_metrics_service
from services.shareholder_schema import ensure_shareholders_table
from services import portfolio_audit
from services import portfolio_cash
from services import portfolio_dividends
from services import portfolio_fees
from services import portfolio_money
from services import portfolio_nav
from services import portfolio_positions
from services import portfolio_records
from services import ui_preferences
from services.portfolio_schema import ensure_portfolio_tables
from services.market_data import (
    fetch_realtime_prices as market_fetch_realtime_prices,
    fetch_realtime_quotes as market_fetch_realtime_quotes,
    fetch_ytd_return as market_fetch_ytd_return,
)
from services.exchange_rates import (
    currency_for_market as _currency_for_market,
    exchange_rate_to_cny as _exchange_rate_to_cny,
)
from routes.portfolio import register_portfolio_routes
from routes.corporate_actions import register_corporate_action_routes
from routes.notes_chat import register_notes_chat_routes
from routes.stock_basic import register_stock_basic_routes
from routes.stocks import register_stock_routes
from routes.system import register_system_routes
from routes.fundamental_dashboard import register_fundamental_dashboard_routes
from routes.compare_dashboard import register_compare_dashboard_routes
from routes.capital_allocation import register_capital_allocation_routes
from routes.custom_financials import register_custom_financial_routes
from routes.balance_sheet import register_balance_sheet_routes
from routes.statements import register_statement_routes
from routes.segments import register_segment_routes
from routes.market_charts import register_market_chart_routes
from routes.shareholders import register_shareholder_routes
from routes.irm import register_irm_routes
from routes.dividend_update import register_dividend_update_routes
from routes.jobs import register_job_routes
from routes.pages import register_page_routes

app = Flask(__name__)

LOCAL_SETTINGS = app_settings.read_local_settings(APP_DIR)
LOCAL_SETTINGS_PATH = app_settings.local_settings_path(APP_DIR)


def _read_local_settings():
    return app_settings.read_local_settings(APP_DIR)


def _set_local_settings(settings):
    global LOCAL_SETTINGS
    LOCAL_SETTINGS = settings


def _setting(name, env_name, default=None):
    return app_settings.setting(LOCAL_SETTINGS, name, env_name, default)


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
    return mysql_tools.tool_path(name, MYSQL_BIN_DIR)


def _cloud_backup_dir():
    return cloud_backup_storage.backup_dir(CLOUD_SYNC_DIR)


def _cloud_state_path():
    return cloud_backup_storage.state_path(CLOUD_SYNC_DIR, CLOUD_STATE_JSON)


def _cloud_latest_path():
    return cloud_backup_storage.latest_path(CLOUD_SYNC_DIR, CLOUD_LATEST_SQL)


def _cloud_backup_files():
    return cloud_backup_storage.backup_files(
        CLOUD_SYNC_DIR,
        backup_file_groups,
        CLOUD_BACKUP_RETAIN_COUNT,
    )


def _cleanup_cloud_backup_files(backup_dir=None, retain_count=CLOUD_BACKUP_RETAIN_COUNT):
    return cloud_backup_storage.cleanup_backup_files(
        backup_dir or CLOUD_SYNC_DIR,
        backup_file_groups,
        retain_count,
    )


def _resolve_backup_file(filename):
    return cloud_backup_storage.resolve_backup_file(CLOUD_SYNC_DIR, filename)


def _read_local_cloud_state():
    return cloud_backup_storage.read_json_file(LOCAL_CLOUD_STATE_JSON)


def _write_local_cloud_state(payload):
    return cloud_backup_storage.write_json_file(LOCAL_CLOUD_STATE_JSON, payload)


def _cloud_latest_mtime():
    return cloud_backup_storage.latest_mtime(CLOUD_SYNC_DIR, CLOUD_LATEST_SQL)


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
    return cloud_backup_storage.read_json_file(_cloud_state_path())


def _write_cloud_state(payload):
    return cloud_backup_storage.write_json_file(_cloud_state_path(), payload)


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
    "api_update_shareholders": "shareholders-update",
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
    "api_financial_indicator_preferences_put": "financial-indicator-preferences-update",
}


@app.after_request
def schedule_auto_cloud_backup_after_change(response):
    is_background_job_start = False
    if response.is_json:
        try:
            body = response.get_json(silent=True) or {}
            is_background_job_start = bool(body.get("background") and body.get("job_id"))
        except Exception:
            is_background_job_start = False
    if (
        request.method in ("POST", "PUT", "DELETE")
        and response.status_code < 400
        and request.endpoint in AUTO_CLOUD_BACKUP_ENDPOINTS
        and not is_background_job_start
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
    return sticky_load_notes(JSON_PATH, DATA_DIR)


def _save_notes(notes):
    sticky_save_notes(notes, JSON_PATH, DATA_DIR)


def _extract_images(content, note_id):
    return sticky_extract_images(content, note_id, IMAGES_DIR)


def _cleanup_images(note):
    sticky_cleanup_images(note, IMAGES_DIR)


register_page_routes(app)


# ==================== API 路由 ====================

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


def _ui_preference_get(pref_key):
    return ui_preferences.ui_preference_get(execute_query, pref_key)


def _ui_preference_set(pref_key, pref_value):
    return ui_preferences.ui_preference_set(execute_query, pref_key, pref_value)


def _fetch_realtime_quotes(stocks):
    return market_fetch_realtime_quotes(stocks, _quote_symbol)


def _fetch_realtime_prices(stocks):
    return market_fetch_realtime_prices(stocks, _quote_symbol)


def _fetch_ytd_return(code, market, current_price=None):
    return market_fetch_ytd_return(code, market, _quote_symbol, current_price)


stock_metrics_service.configure(execute_query, _fetch_realtime_quotes, _fetch_ytd_return)


def _ensure_graham_valuation_table():
    return stock_metrics_service._ensure_graham_valuation_table()


def _ensure_shareholders_table():
    return ensure_shareholders_table(execute_query)


def _latest_total_shares(codes):
    return stock_metrics_service._latest_total_shares(codes)


def _graham_defaults(codes):
    return stock_metrics_service._graham_defaults(codes)


def _graham_custom_params(codes):
    return stock_metrics_service._graham_custom_params(codes)


def _graham_payload(code):
    return stock_metrics_service._graham_payload(code)


def _enrich_stock_list_metrics(stocks, include_ytd=False):
    return stock_metrics_service._enrich_stock_list_metrics(stocks, include_ytd)


def _stock_realtime_list_metrics(codes):
    return stock_metrics_service._stock_realtime_list_metrics(codes)


def _ensure_portfolio_tables():
    return ensure_portfolio_tables(execute_query, _sync_portfolio_cost_basis_from_trades)

def _decimal_value(value, default="0"):
    return portfolio_money.decimal_value(value, default)


def _quantize(value, scale="0.0001"):
    return portfolio_money.quantize(value, scale)


def _decimal_equal(left, right, scale="0.0001"):
    return portfolio_money.decimal_equal(left, right, scale)


def _execute_insert_id(sql, params=None):
    return execute_insert(sql, params)


def _portfolio_fee_config():
    return portfolio_fees.fee_config(execute_query)


def _portfolio_fee_config_payload():
    return portfolio_fees.fee_config_payload(execute_query, _ensure_portfolio_tables)


def _is_domestic_market(market):
    return portfolio_money.is_domestic_market(market)


def _calculate_portfolio_trade_fees(amount, trade_type, market, config=None):
    return portfolio_money.calculate_trade_fees(amount, trade_type, market, config or _portfolio_fee_config())


def _sync_portfolio_cost_basis_from_trades():
    return portfolio_positions.sync_cost_basis_from_trades(execute_query)

def _portfolio_cash_amount():
    return portfolio_cash.cash_amount(execute_query, _ensure_portfolio_tables)


def _portfolio_cash_base_amount():
    return portfolio_cash.base_amount(execute_query, _ensure_portfolio_tables)


def _portfolio_rebuilt_cash_amount():
    return portfolio_cash.rebuilt_amount(execute_query, _portfolio_cash_base_amount)


def _portfolio_flow_rows(limit=100):
    return portfolio_cash.flow_rows(execute_query, _ensure_portfolio_tables, limit)


def _portfolio_flows_payload():
    return portfolio_cash.flows_payload(execute_query, _ensure_portfolio_tables)

def _portfolio_trades_payload(limit=1000):
    return portfolio_records.trades_payload(execute_query, _ensure_portfolio_tables, _currency_for_market, limit)


def _portfolio_actions_payload(limit=100):
    return portfolio_records.actions_payload(execute_query, _ensure_portfolio_tables, _currency_for_market, limit)

def _void_linked_cash_flow(source_type, source_id, flow_source, flow_date, amount, code, void_note):
    return portfolio_cash.void_linked_cash_flow(
        execute_query,
        source_type,
        source_id,
        flow_source,
        flow_date,
        amount,
        code,
        void_note,
    )

def _portfolio_audit_payload():
    return portfolio_audit.audit_payload(
        execute_query,
        _ensure_portfolio_tables,
        _portfolio_cash_amount,
        _portfolio_rebuilt_cash_amount,
        _portfolio_cash_base_amount,
    )

def _latest_dividend_per_share(codes):
    return portfolio_dividends.latest_dividend_per_share(execute_query, codes)

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
    return portfolio_nav.current_state(
        execute_query,
        _ensure_portfolio_tables,
        _portfolio_cash_amount,
        _portfolio_fee_config_payload,
        _fill_missing_stock_industries,
        _fetch_realtime_quotes,
        _latest_dividend_per_share,
        _currency_for_market,
        _exchange_rate_to_cny,
    )


def _save_portfolio_snapshot():
    return portfolio_nav.save_snapshot(execute_query, _portfolio_current_state)


register_portfolio_routes(app, {
    "execute_query": execute_query,
    "execute_insert_id": _execute_insert_id,
    "ensure_portfolio_tables": _ensure_portfolio_tables,
    "portfolio_current_state": _portfolio_current_state,
    "portfolio_fee_config_payload": _portfolio_fee_config_payload,
    "decimal_value": _decimal_value,
    "quantize": _quantize,
    "latest_dividend_per_share": _latest_dividend_per_share,
    "currency_for_market": _currency_for_market,
    "portfolio_trades_payload": _portfolio_trades_payload,
    "portfolio_actions_payload": _portfolio_actions_payload,
    "portfolio_audit_payload": _portfolio_audit_payload,
    "sync_portfolio_cost_basis_from_trades": _sync_portfolio_cost_basis_from_trades,
    "portfolio_rebuilt_cash_amount": _portfolio_rebuilt_cash_amount,
    "save_portfolio_snapshot": _save_portfolio_snapshot,
    "portfolio_flows_payload": _portfolio_flows_payload,
    "resolve_portfolio_stock": _resolve_portfolio_stock,
    "calculate_portfolio_trade_fees": _calculate_portfolio_trade_fees,
    "portfolio_cash_amount": _portfolio_cash_amount,
    "void_linked_cash_flow": _void_linked_cash_flow,
})


register_fundamental_dashboard_routes(app, {
    "execute_query": execute_query,
    "enrich_stock_list_metrics": _enrich_stock_list_metrics,
    "normalize_stock_code": _normalize_stock_code,
})

register_compare_dashboard_routes(app, {
    "execute_query": execute_query,
    "enrich_stock_list_metrics": _enrich_stock_list_metrics,
    "normalize_stock_code": _normalize_stock_code,
})

register_capital_allocation_routes(app, {
    "execute_query": execute_query,
})

register_system_routes(app, {
    "get_all_config": get_all_config,
    "set_config": set_config,
    "ui_preference_get": _ui_preference_get,
    "ui_preference_set": _ui_preference_set,
    "get_local_settings": lambda: LOCAL_SETTINGS,
    "read_local_settings": _read_local_settings,
    "set_local_settings": _set_local_settings,
    "local_settings_path": LOCAL_SETTINGS_PATH,
    "app_port": APP_PORT,
    "auto_cloud_backup_delay_seconds": AUTO_CLOUD_BACKUP_DELAY_SECONDS,
    "cloud_sync_dir": CLOUD_SYNC_DIR,
    "mysql_bin_dir": MYSQL_BIN_DIR,
    "db_config": DB_CONFIG,
    "cloud_latest_sql": CLOUD_LATEST_SQL,
    "migration_status": migration_status,
    "cloud_latest_path": _cloud_latest_path,
    "read_cloud_state": _read_cloud_state,
    "read_local_cloud_state": _read_local_cloud_state,
    "cloud_latest_mtime": _cloud_latest_mtime,
    "to_float": _to_float,
    "cloud_backup_dir": _cloud_backup_dir,
    "auto_backup_status_payload": _auto_backup_status_payload,
    "cloud_backup_files": _cloud_backup_files,
    "cancel_pending_auto_cloud_backup": _cancel_pending_auto_cloud_backup,
    "dump_database": _dump_database,
    "resolve_backup_file": _resolve_backup_file,
    "restore_database": _restore_database,
    "mark_cloud_applied": _mark_cloud_applied,
})


register_stock_routes(app, {
    "Stock": Stock,
    "execute_query": execute_query,
    "ensure_stock_order_column": _ensure_stock_order_column,
    "enrich_stock_list_metrics": _enrich_stock_list_metrics,
    "stock_realtime_list_metrics": _stock_realtime_list_metrics,
    "fetch_ytd_return": _fetch_ytd_return,
    "graham_payload": _graham_payload,
    "ensure_graham_valuation_table": _ensure_graham_valuation_table,
})


register_stock_basic_routes(app, {
    "Stock": Stock,
    "transaction": transaction,
    "execute_query": execute_query,
    "quote_symbol": _quote_symbol,
    "normalize_stock_code": _normalize_stock_code,
    "lookup_hk_stock_info": _lookup_hk_stock_info,
    "fetch_stock_industry": _fetch_stock_industry,
    "load_notes": _load_notes,
    "save_notes": _save_notes,
    "cleanup_images": _cleanup_images,
})


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


register_corporate_action_routes(app, {
    "Stock": Stock,
    "execute_query": execute_query,
    "eastmoney_secu_code": _eastmoney_secu_code,
    "as_list": _as_list,
    "date_only": _date_only,
    "money_yuan": _money_yuan,
    "to_float": _to_float,
})


register_irm_routes(app, {
    "Stock": Stock,
    "execute_query": execute_query,
    "execute_insert": execute_insert,
    "get_connection": get_connection,
    "as_list": _as_list,
    "money_yuan": _money_yuan,
    "to_float": _to_float,
})

register_job_routes(app, {
    "execute_query": execute_query,
    "retry_endpoints": {
        "irm_sync_all": "/api/irm/sync",
        "update_financials": "/api/update-financials",
        "update_dividends": "/api/update-dividends",
        "update_balance_sheet": "/api/update-balance-sheet",
        "update_income": "/api/update-income",
        "update_cashflow": "/api/update-cashflow",
        "update_segments": "/api/update-segments",
        "update_shareholders": "/api/update-shareholders",
    },
})

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
    query_code = request.args.get("code") if has_request_context() else ""
    raw_codes = payload.get("codes")
    if raw_codes:
        if isinstance(raw_codes, str):
            raw_codes = [item.strip() for item in raw_codes.split(",") if item.strip()]
        codes = [_normalize_stock_code(str(item).strip()) for item in raw_codes if str(item).strip()]
        if codes:
            columns = "code, name, market" if include_name_market else "code"
            placeholders = ", ".join(["%s"] * len(codes))
            return execute_query(
                f"SELECT {columns} FROM stocks WHERE code IN ({placeholders}) ORDER BY FIELD(code, {placeholders})",
                tuple(codes + codes),
            )
    code = (payload.get("code") or query_code or "").strip()
    columns = "code, name, market" if include_name_market else "code"
    if code:
        code = _normalize_stock_code(code)
        return execute_query(f"SELECT {columns} FROM stocks WHERE code=%s", (code,))
    return execute_query(f"SELECT {columns} FROM stocks WHERE status='正常'")


register_shareholder_routes(app, {
    "Stock": Stock,
    "execute_query": execute_query,
    "execute_many": execute_many,
    "get_connection": get_connection,
    "get_update_stocks": _get_update_stocks,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "ensure_shareholders_table": _ensure_shareholders_table,
    "eastmoney_secu_code": _eastmoney_secu_code,
    "eastmoney_web_code": _eastmoney_web_code,
    "as_list": _as_list,
    "date_only": _date_only,
    "money_yuan": _money_yuan,
    "to_float": _to_float,
})


register_dividend_update_routes(app, {
    "execute_query": execute_query,
    "get_connection": get_connection,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "get_update_stocks": _get_update_stocks,
    "quote_symbol": _quote_symbol,
})


register_custom_financial_routes(app, {
    "execute_query": execute_query,
    "get_connection": get_connection,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "ensure_financials_columns": _ensure_financials_columns,
    "get_update_stocks": _get_update_stocks,
    "quote_symbol": _quote_symbol,
})


register_balance_sheet_routes(app, {
    "execute_query": execute_query,
    "get_connection": get_connection,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "get_update_stocks": _get_update_stocks,
})

register_market_chart_routes(app, {
    "execute_query": execute_query,
    "quote_symbol": _quote_symbol,
    "valuation_cache": _valuation_cache,
    "valuation_cache_lock": _valuation_cache_lock,
    "valuation_cache_seconds": VALUATION_CACHE_SECONDS,
})


_ensure_segments_table = register_segment_routes(app, {
    "execute_query": execute_query,
    "get_connection": get_connection,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "get_update_stocks": _get_update_stocks,
})


register_statement_routes(app, {
    "execute_query": execute_query,
    "get_connection": get_connection,
    "schedule_auto_cloud_backup": _schedule_auto_cloud_backup,
    "get_update_stocks": _get_update_stocks,
})


register_notes_chat_routes(app, {
    "get_chat_history": get_chat_history,
    "chat_send": chat_send,
    "clear_chat_history": clear_chat_history,
    "delete_chat_msg": delete_chat_msg,
    "load_notes": _load_notes,
    "save_notes": _save_notes,
    "extract_images": _extract_images,
    "cleanup_images": _cleanup_images,
    "images_dir": IMAGES_DIR,
})


if __name__ == "__main__":
    print("stock Web 服务启动: http://127.0.0.1:5002")
    try:
        migration_result = run_migrations()
        if migration_result["count"]:
            print(f"OK 已执行数据库迁移: {', '.join(migration_result['applied'])}")
        else:
            print("OK 数据库迁移已是最新")
        _ensure_financials_columns()
        _ensure_segments_table()
        _ensure_stock_order_column()
        _ensure_portfolio_tables()
        _ensure_graham_valuation_table()
        _ensure_shareholders_table()
        print("OK 已确保 custom_financials 表结构完整")
    except Exception as e:
        print(f"WARN 表结构检查异常: {e}")
    app.run(host="0.0.0.0", port=APP_PORT, debug=True)
