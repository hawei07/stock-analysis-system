"""Cloud backup file and state storage helpers."""

import json
import os
from datetime import datetime


def backup_dir(cloud_sync_dir):
    os.makedirs(cloud_sync_dir, exist_ok=True)
    return cloud_sync_dir


def state_path(cloud_sync_dir, cloud_state_json):
    return os.path.join(backup_dir(cloud_sync_dir), cloud_state_json)


def latest_path(cloud_sync_dir, cloud_latest_sql):
    return os.path.join(backup_dir(cloud_sync_dir), cloud_latest_sql)


def backup_file_payload(path):
    stat = os.stat(path)
    return {
        "name": os.path.basename(path),
        "path": path,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def cleanup_backup_files(cloud_sync_dir, backup_file_groups, retain_count):
    cloud_dir = backup_dir(cloud_sync_dir)
    deleted = []

    for group_name, pattern in backup_file_groups().items():
        files = []
        for name in os.listdir(cloud_dir):
            if not pattern.match(name):
                continue
            path = os.path.join(cloud_dir, name)
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


def backup_files(cloud_sync_dir, backup_file_groups, retain_count):
    cloud_dir = backup_dir(cloud_sync_dir)
    cleanup_backup_files(cloud_dir, backup_file_groups, retain_count)
    files = []
    for name in os.listdir(cloud_dir):
        path = os.path.join(cloud_dir, name)
        if os.path.isfile(path) and name.lower().endswith(".sql"):
            files.append(backup_file_payload(path))
    return sorted(files, key=lambda item: item["mtime"], reverse=True)


def resolve_backup_file(cloud_sync_dir, filename):
    if not filename or os.path.basename(filename) != filename or not filename.lower().endswith(".sql"):
        raise ValueError("Invalid backup filename")
    cloud_dir = os.path.abspath(backup_dir(cloud_sync_dir))
    path = os.path.abspath(os.path.join(cloud_dir, filename))
    if os.path.commonpath([cloud_dir, path]) != cloud_dir or not os.path.exists(path):
        raise FileNotFoundError(filename)
    return path


def read_json_file(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_json_file(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def latest_mtime(cloud_sync_dir, cloud_latest_sql):
    path = latest_path(cloud_sync_dir, cloud_latest_sql)
    return os.path.getmtime(path) if os.path.exists(path) else None
