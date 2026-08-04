"""Sina finance provider helpers."""

from services.http_client import get_text


def finance_statement_html(stock_code, statement_path, *, timeout=15):
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/{statement_path}/stockid/{stock_code}/ctrl/part/displaytype/0.phtml"
    return get_text(url, encoding="gbk", timeout=timeout)


def share_bonus_html(stock_code, *, timeout=15):
    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{stock_code}.phtml"
    return get_text(url, encoding="gbk", timeout=timeout)
