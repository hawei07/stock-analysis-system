"""Cloud backup policy and validation helpers."""

import os
import re

CLOUD_BACKUP_RETAIN_COUNT = 5
TIMED_BACKUP_RE = re.compile(r"^stock_analysis_\d{8}_\d{6}\.sql$", re.IGNORECASE)
PRE_RESTORE_BACKUP_RE = re.compile(r"^pre_restore_\d{8}_\d{6}\.sql$", re.IGNORECASE)


def backup_file_groups():
    return {
        "stock_analysis": TIMED_BACKUP_RE,
        "pre_restore": PRE_RESTORE_BACKUP_RE,
    }


def auto_backup_delay_for_reasons(reasons, default_delay):
    if not reasons:
        return default_delay
    if any(reason.startswith("portfolio-") for reason in reasons):
        return min(default_delay, 60)
    bulk_prefixes = {"dividends", "financials", "balance", "segments", "income", "cashflow"}
    if any(reason.endswith("-update") and reason.split("-")[0] in bulk_prefixes for reason in reasons):
        return min(default_delay, 30)
    return default_delay


def validate_sql_backup_file(sql_path):
    size = os.path.getsize(sql_path)
    if size < 1024:
        raise ValueError("备份文件过小，可能不是有效数据库备份")
    with open(sql_path, "rb") as f:
        content = f.read().decode("utf-8", errors="ignore").lower()
    if not any(marker in content for marker in ("create table", "drop table", "insert into")):
        raise ValueError("备份文件内容不像有效 MySQL dump")
    if "stocks" not in content and "`stocks`" not in content:
        raise ValueError("备份文件未检测到 stocks 表内容")
    return {"ok": True, "size": size}
