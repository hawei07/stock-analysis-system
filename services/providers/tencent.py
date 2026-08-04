"""Tencent quote and K-line provider helpers."""

from services.http_client import get_json, get_text


def quote_text(symbols, *, timeout=10):
    if isinstance(symbols, str):
        query = symbols
    else:
        query = ",".join(symbols)
    return get_text(f"https://qt.gtimg.cn/q={query}", encoding="gbk", timeout=timeout)


def fq_kline(symbol, *, start="", count=365, timeout=10):
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{start},,{count},qfq"
    return get_json(url, timeout=timeout)

