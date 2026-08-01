"""Stock code, market and quote symbol helpers."""

import re

import requests


def market_from_code(code, market=None):
    code = str(code or "")
    if market == "HK" or re.fullmatch(r"\d{5}", code):
        return "HK"
    if code.startswith(("6", "5", "9")):
        return "SH"
    if code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("0", "2", "3")):
        return "SZ"
    return market or "SZ"


def quote_symbol(code, market=None):
    code = str(code or "")
    inferred_market = market_from_code(code, market)
    if inferred_market == "HK":
        return f"hk{code.zfill(5)}"
    if inferred_market == "SH":
        return f"sh{code}"
    if inferred_market == "BJ":
        return f"bj{code}"
    return f"sz{code}"


def normalize_stock_code(code):
    code = str(code or "").strip().upper()
    if code.startswith("HK"):
        code = code[2:]
    return code.zfill(5) if re.fullmatch(r"\d{1,5}", code) else code


def eastmoney_secid(code, market=None):
    market = (market or "").upper()
    if market == "HK" or re.fullmatch(r"\d{5}", str(code or "")):
        return f"116.{normalize_stock_code(code)}"
    if market == "SH" or str(code).startswith(("6", "5", "9")):
        return f"1.{code}"
    return f"0.{code}"


def fetch_stock_industry(code, market=None):
    try:
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": eastmoney_secid(code, market), "fields": "f57,f58,f127"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        data = resp.json().get("data") or {}
        industry = str(data.get("f127") or "").strip()
        return industry or None
    except Exception:
        return None


def lookup_hk_stock_info(code):
    code = normalize_stock_code(code)
    if not re.fullmatch(r"\d{5}", code):
        return None
    try:
        resp = requests.get(
            f"https://qt.gtimg.cn/q=hk{code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8,
        )
        resp.encoding = "gbk"
        text = resp.text or ""
        if not text.startswith("v_hk"):
            return None
        fields = text.split('"')[1].split("~") if '"' in text else []
        name = fields[1].strip() if len(fields) > 1 else ""
        if not name:
            return None
        return {"code": code, "name": name, "market": "HK", "industry": fetch_stock_industry(code, "HK")}
    except Exception:
        return None
