"""系统配置管理 — 读写 system_config 表，支持运行时动态读取。"""
from db import execute_query, execute_update


def get_config(key: str, default: str = "") -> str:
    """读取单个配置项"""
    rows = execute_query(
        "SELECT config_value FROM system_config WHERE config_key = %s", (key,)
    )
    return rows[0]["config_value"] if rows else default


def set_config(key: str, value: str) -> None:
    """写入或更新配置项"""
    execute_update(
        """INSERT INTO system_config (config_key, config_value)
           VALUES (%s, %s)
           ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)""",
        (key, value),
    )


def get_all_config() -> dict[str, str]:
    """读取全部配置项，敏感值掩码"""
    rows = execute_query("SELECT config_key, config_value FROM system_config", ())
    result = {}
    for r in rows:
        key = r["config_key"]
        val = r["config_value"]
        # 敏感 key 只显示后 4 位
        if any(s in key.lower() for s in ("api_key", "secret", "token", "password")):
            val = "****" + val[-4:] if len(val) > 4 else "****"
        result[key] = val
    return result


def get_deepseek_api_key() -> str:
    """获取 DeepSeek API Key"""
    return get_config("deepseek_api_key", "")


def get_deepseek_model() -> str:
    """获取 DeepSeek 模型名，允许在 system_config 中切换。"""
    return get_config("deepseek_model", "deepseek-v4-pro")
