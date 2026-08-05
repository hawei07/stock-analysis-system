"""Local runtime settings helpers."""

import json
import os


def local_settings_path(app_dir):
    return os.path.join(app_dir, "local_settings.json")


def read_local_settings(app_dir):
    path = local_settings_path(app_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def setting(local_settings, name, env_name, default=None):
    value = os.environ.get(env_name)
    if value not in (None, ""):
        return value
    value = (local_settings or {}).get(name)
    return default if value in (None, "") else value
