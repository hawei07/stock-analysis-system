"""Eastmoney provider helpers."""

from services.http_client import get_json


def stock_snapshot(secid, fields, *, timeout=8):
    return get_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={"secid": secid, "fields": fields},
        timeout=timeout,
    )


def finance_report(report_name, *, params=None, timeout=15):
    query = {
        "reportName": report_name,
        "columns": "ALL",
    }
    if params:
        query.update(params)
    return get_json(
        "https://datacenter.eastmoney.com/securities/api/data/v1/get",
        params=query,
        headers={"Referer": "https://data.eastmoney.com/"},
        timeout=timeout,
    )


def finance_web_report(report_name, *, params=None, timeout=15):
    query = {
        "reportName": report_name,
        "columns": "ALL",
    }
    if params:
        query.update(params)
    return get_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params=query,
        headers={"Referer": "https://data.eastmoney.com/"},
        timeout=timeout,
    )
