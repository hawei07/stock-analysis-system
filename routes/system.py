"""System configuration, preferences, migrations, and cloud-backup routes."""

import json
import os
import sys
from datetime import datetime

import mysql.connector
from flask import jsonify, request


def register_system_routes(app, deps):
    get_all_config = deps["get_all_config"]
    set_config = deps["set_config"]
    ui_preference_get = deps["ui_preference_get"]
    ui_preference_set = deps["ui_preference_set"]
    get_local_settings = deps["get_local_settings"]
    read_local_settings = deps["read_local_settings"]
    set_local_settings = deps["set_local_settings"]
    local_settings_path = deps["local_settings_path"]
    app_port = deps["app_port"]
    auto_cloud_backup_delay_seconds = deps["auto_cloud_backup_delay_seconds"]
    cloud_sync_dir = deps["cloud_sync_dir"]
    mysql_bin_dir = deps["mysql_bin_dir"]
    db_config = deps["db_config"]
    cloud_latest_sql = deps["cloud_latest_sql"]
    migration_status = deps["migration_status"]
    database_stats = deps["database_stats"]
    reset_database_stats = deps["reset_database_stats"]
    cloud_latest_path = deps["cloud_latest_path"]
    cloud_latest_files_path = deps["cloud_latest_files_path"]
    read_cloud_state = deps["read_cloud_state"]
    read_local_cloud_state = deps["read_local_cloud_state"]
    cloud_latest_mtime = deps["cloud_latest_mtime"]
    to_float = deps["to_float"]
    cloud_backup_dir = deps["cloud_backup_dir"]
    auto_backup_status_payload = deps["auto_backup_status_payload"]
    cloud_backup_files = deps["cloud_backup_files"]
    cancel_pending_auto_cloud_backup = deps["cancel_pending_auto_cloud_backup"]
    dump_database = deps["dump_database"]
    resolve_backup_file = deps["resolve_backup_file"]
    restore_database = deps["restore_database"]
    mark_cloud_applied = deps["mark_cloud_applied"]

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


    @app.route("/api/preferences/financial-indicators", methods=["GET"])
    def api_financial_indicator_preferences_get():
        value, updated_at = ui_preference_get("financial_indicators")
        return jsonify({
            "fields": value.get("fields") if isinstance(value, dict) else None,
            "updated_at": str(updated_at) if updated_at else None,
        })


    @app.route("/api/preferences/financial-indicators", methods=["PUT"])
    def api_financial_indicator_preferences_put():
        data = request.get_json(silent=True) or {}
        fields = data.get("fields")
        if not isinstance(fields, list):
            return jsonify({"error": "fields 必须是数组"}), 400
        cleaned = []
        seen = set()
        for field in fields:
            field = str(field or "").strip()
            if not field or field in seen or len(field) > 80:
                continue
            seen.add(field)
            cleaned.append(field)
        ui_preference_set("financial_indicators", {"fields": cleaned})
        return jsonify({"ok": True, "fields": cleaned})


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
        settings = dict(get_local_settings() if settings is None else settings)
        values = {
            "app_port": int(settings.get("app_port") or app_port),
            "app_url": settings.get("app_url") or f"http://127.0.0.1:{app_port}",
            "auto_cloud_backup_delay_seconds": int(settings.get("auto_cloud_backup_delay_seconds") or auto_cloud_backup_delay_seconds),
            "cloud_sync_dir": settings.get("cloud_sync_dir") or cloud_sync_dir,
            "mysql_service_name": settings.get("mysql_service_name") or "",
            "mysql_home": settings.get("mysql_home") or "",
            "mysql_bin_dir": settings.get("mysql_bin_dir") or mysql_bin_dir,
            "python_exe": settings.get("python_exe") or sys.executable,
            "db_host": settings.get("db_host") or db_config.get("host", "127.0.0.1"),
            "db_port": int(settings.get("db_port") or db_config.get("port", 3306)),
            "db_user": settings.get("db_user") or db_config.get("user", "root"),
            "db_name": settings.get("db_name") or db_config.get("database", "stock_analysis"),
        }
        cloud = _path_status(values["cloud_sync_dir"])
        mysql_bin = _path_status(values["mysql_bin_dir"])
        python_exe = _path_status(values["python_exe"])
        latest_path = os.path.join(cloud["path"], cloud_latest_sql) if cloud["path"] else ""
        latest_exists = os.path.exists(latest_path) if latest_path else False
        return {
            "ok": True,
            "path": local_settings_path,
            "values": values,
            "db_password_configured": bool(settings.get("db_password") or db_config.get("password")),
            "runtime": {
                "cloud_sync_dir": cloud_sync_dir,
                "mysql_bin_dir": mysql_bin_dir,
                "app_port": app_port,
                "auto_cloud_backup_delay_seconds": auto_cloud_backup_delay_seconds,
                "db_host": db_config.get("host"),
                "db_port": db_config.get("port"),
                "db_user": db_config.get("user"),
                "db_name": db_config.get("database"),
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
        data = request.get_json(force=True) or {}
        current = read_local_settings()
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

        with open(local_settings_path, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
        set_local_settings(current)
        return jsonify({"ok": True, "updated": updated, "restart_required": True, **_local_settings_payload(current)})


    @app.route("/api/local-settings/test", methods=["POST"])
    def api_local_settings_test():
        data = request.get_json(force=True) or {}
        current = read_local_settings()
        merged = {**current, **{k: v for k, v in data.items() if k in LOCAL_SETTING_KEYS and v not in (None, "")}}
        if data.get("db_password") in (None, "", "********"):
            merged["db_password"] = current.get("db_password", db_config.get("password", ""))

        cloud_dir = str(merged.get("cloud_sync_dir") or cloud_sync_dir)
        mysql_bin_dir_value = str(merged.get("mysql_bin_dir") or mysql_bin_dir)
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

        mysql_exe = os.path.join(os.path.abspath(os.path.expandvars(mysql_bin_dir_value)), "mysql.exe") if mysql_bin_dir_value else ""
        mysqldump_exe = os.path.join(os.path.abspath(os.path.expandvars(mysql_bin_dir_value)), "mysqldump.exe") if mysql_bin_dir_value else ""
        tools_ok = bool(mysql_exe and os.path.exists(mysql_exe) and os.path.exists(mysqldump_exe))
        result["checks"]["mysql_tools"] = {
            "ok": tools_ok,
            "message": "mysql.exe 和 mysqldump.exe 已找到" if tools_ok else "未同时找到 mysql.exe 和 mysqldump.exe",
        }

        try:
            conn = mysql.connector.connect(
                host=merged.get("db_host") or db_config.get("host"),
                port=int(merged.get("db_port") or db_config.get("port")),
                user=merged.get("db_user") or db_config.get("user"),
                password=merged.get("db_password", db_config.get("password", "")),
                database=merged.get("db_name") or db_config.get("database"),
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


    @app.route("/api/db/stats")
    def api_db_stats():
        return jsonify({"ok": True, "stats": database_stats()})


    @app.route("/api/db/stats/reset", methods=["POST"])
    def api_db_stats_reset():
        reset_database_stats()
        return jsonify({"ok": True, "stats": database_stats()})


    @app.route("/api/cloud-backup/status")
    def api_cloud_backup_status():
        latest_path = cloud_latest_path()
        latest_files_path = cloud_latest_files_path()
        state = read_cloud_state()
        local_state = read_local_cloud_state()
        latest_mtime = cloud_latest_mtime()
        local_mtime = to_float(local_state.get("latest_mtime"))
        cloud_newer = bool(latest_mtime and (local_mtime is None or latest_mtime > local_mtime + 1))
        local_dirty = bool(local_state.get("local_dirty"))
        return jsonify({
            "backup_dir": cloud_backup_dir(),
            "latest_path": latest_path,
            "latest_exists": os.path.exists(latest_path),
            "latest_size": os.path.getsize(latest_path) if os.path.exists(latest_path) else 0,
            "latest_mtime": datetime.fromtimestamp(os.path.getmtime(latest_path)).isoformat(timespec="seconds") if os.path.exists(latest_path) else None,
            "sticky_backup_exists": os.path.exists(latest_files_path),
            "sticky_backup_size": os.path.getsize(latest_files_path) if os.path.exists(latest_files_path) else 0,
            "sticky_backup_file": os.path.basename(latest_files_path),
            "cloud_newer": cloud_newer,
            "local_dirty": local_dirty,
            "possible_conflict": bool(cloud_newer and local_dirty),
            "auto_backup": auto_backup_status_payload(),
            "state": state,
            "local_state": local_state,
        })


    @app.route("/api/cloud-backup/auto-status")
    def api_cloud_backup_auto_status():
        return jsonify(auto_backup_status_payload())


    @app.route("/api/cloud-backup/files")
    def api_cloud_backup_files():
        try:
            return jsonify({
                "backup_dir": cloud_backup_dir(),
                "files": cloud_backup_files(),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route("/api/cloud-backup/backup", methods=["POST"])
    def api_cloud_backup_create():
        try:
            cancel_pending_auto_cloud_backup()
            state = dump_database()
            return jsonify({"ok": True, **state})
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route("/api/cloud-backup/restore-file", methods=["POST"])
    def api_cloud_backup_restore_file():
        try:
            cancel_pending_auto_cloud_backup()
            data = request.get_json(silent=True) or {}
            filename = data.get("filename", "")
            backup_path = resolve_backup_file(filename)
            pre_restore_state = dump_database(prefix="pre_restore", update_latest=False)
            restore_result = restore_database(backup_path)
            mark_cloud_applied("restore-file", {"restored_from": backup_path})
            return jsonify({
                "ok": True,
                "restored_from": backup_path,
                "pre_restore_backup": pre_restore_state.get("latest_backup"),
                "sticky_backup": restore_result.get("sticky_backup") if isinstance(restore_result, dict) else None,
            })
        except FileNotFoundError:
            return jsonify({"error": "Backup file not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    @app.route("/api/cloud-backup/restore", methods=["POST"])
    def api_cloud_backup_restore():
        try:
            cancel_pending_auto_cloud_backup()
            latest_path = cloud_latest_path()
            if not os.path.exists(latest_path):
                return jsonify({"error": "云端 latest 备份不存在"}), 404
            pre_restore_state = dump_database(prefix="pre_restore", update_latest=False)
            restore_result = restore_database(latest_path)
            mark_cloud_applied("restore", {"restored_from": latest_path})
            return jsonify({
                "ok": True,
                "restored_from": latest_path,
                "pre_restore_backup": pre_restore_state.get("latest_backup"),
                "sticky_backup": restore_result.get("sticky_backup") if isinstance(restore_result, dict) else None,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500
