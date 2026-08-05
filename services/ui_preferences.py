"""Persistence helpers for UI preferences."""

import json


def ensure_ui_preferences_table(execute_query):
    execute_query(
        """CREATE TABLE IF NOT EXISTS ui_preferences (
            pref_key VARCHAR(80) NOT NULL PRIMARY KEY,
            pref_value JSON NOT NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )


def ui_preference_get(execute_query, pref_key):
    ensure_ui_preferences_table(execute_query)
    rows = execute_query(
        "SELECT pref_value, updated_at FROM ui_preferences WHERE pref_key=%s LIMIT 1",
        (pref_key,),
    )
    if not rows:
        return None, None
    value = rows[0].get("pref_value")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            value = None
    return value, rows[0].get("updated_at")


def ui_preference_set(execute_query, pref_key, pref_value):
    ensure_ui_preferences_table(execute_query)
    execute_query(
        """INSERT INTO ui_preferences (pref_key, pref_value)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE pref_value=VALUES(pref_value), updated_at=CURRENT_TIMESTAMP""",
        (pref_key, json.dumps(pref_value, ensure_ascii=False)),
        fetch=False,
    )
