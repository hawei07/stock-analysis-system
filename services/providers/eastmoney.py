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


def stock_suggest(keyword, *, timeout=8):
    return get_json(
        "https://searchadapter.eastmoney.com/api/suggest/get",
        params={"type": 14, "input": keyword},
        timeout=timeout,
    )


def stock_snapshot_web(secid, fields, *, timeout=10):
    return get_json(
        "https://push2.eastmoney.com/api/qt/stock/get",
        params={"secid": secid, "fields": fields},
        timeout=timeout,
    )


def segment_report(stock_code, *, timeout=15):
    return get_json(
        "https://datacenter.eastmoney.com/securities/api/data/v1/get",
        params={
            "reportName": "RPT_F10_FN_MAINOP",
            "columns": "ALL",
            "filter": f'(SECURITY_CODE="{stock_code}")',
            "pageNumber": 1,
            "pageSize": 500,
            "sortColumns": "REPORT_DATE",
            "sortTypes": -1,
        },
        headers={"Referer": "https://data.eastmoney.com/"},
        timeout=timeout,
    )


def shareholder_freeholders(stock_code, *, page_number=1, timeout=12):
    return get_json(
        "https://datacenter-web.eastmoney.com/api/data/v1/get",
        params={
            "sortColumns": "END_DATE,HOLDER_RANK",
            "sortTypes": "-1,1",
            "pageSize": "1000",
            "pageNumber": str(page_number),
            "reportName": "RPT_F10_EH_FREEHOLDERS",
            "columns": "ALL",
            "source": "WEB",
            "client": "WEB",
            "filter": f'(SECURITY_CODE="{stock_code}")',
        },
        headers={"Referer": "https://data.eastmoney.com/gdfx/HoldingAnalyse.html"},
        timeout=timeout,
    )


def shareholder_research_index(code, *, referer_code=None, timeout=12):
    referer_code = referer_code or code
    return get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax",
        params={"code": code},
        headers={"Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={referer_code}&type=web"},
        timeout=timeout,
    )


def shareholder_research_detail(code, date, *, timeout=8):
    return get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDGD",
        params={"code": code, "date": date},
        headers={"Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={code}&type=web"},
        timeout=timeout,
    )


def bonus_financing(code, *, referer_code=None, timeout=12):
    referer_code = referer_code or code
    return get_json(
        "https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax",
        params={"code": code},
        headers={"Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/Index?code={referer_code}&type=web"},
        timeout=timeout,
    )
