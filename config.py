"""数据库和应用配置"""

import json
import os


APP_DIR = os.path.dirname(os.path.abspath(__file__))


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


def _setting(key, env_name, default=None):
    value = LOCAL_SETTINGS.get(key)
    if value not in (None, ""):
        return value
    return os.environ.get(env_name, default)


def _int_setting(key, env_name, default):
    try:
        return int(_setting(key, env_name, default))
    except (TypeError, ValueError):
        return default


DB_CONFIG = {
    "host": _setting("db_host", "DB_HOST", "127.0.0.1"),
    "port": _int_setting("db_port", "DB_PORT", 3306),
    "user": _setting("db_user", "DB_USER", "root"),
    "password": _setting("db_password", "DB_PASSWORD", ""),
    "database": _setting("db_name", "DB_NAME", "stock_analysis"),
    "charset": "utf8mb4",
    "autocommit": True,
}
