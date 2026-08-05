"""Currency helpers and exchange-rate cache."""

import json
import os
import time

from services.http_client import get_json

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXCHANGE_RATE_CACHE_JSON = os.path.join(APP_DIR, "data", "exchange_rates.json")
EXCHANGE_RATE_CACHE_SECONDS = 12 * 60 * 60


def read_exchange_rate_cache():
    if not os.path.exists(EXCHANGE_RATE_CACHE_JSON):
        return {}
    try:
        with open(EXCHANGE_RATE_CACHE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_exchange_rate_cache(payload):
    os.makedirs(os.path.dirname(EXCHANGE_RATE_CACHE_JSON), exist_ok=True)
    with open(EXCHANGE_RATE_CACHE_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def currency_for_market(market):
    return "HKD" if market == "HK" else "CNY"


def exchange_rate_to_cny(currency):
    currency = (currency or "CNY").upper()
    if currency == "CNY":
        return {"rate": 1.0, "base": "CNY", "target": "CNY", "date": None, "source": "native", "cached": False}

    key = f"{currency}_CNY"
    now = time.time()
    cache = read_exchange_rate_cache()
    cached = (cache.get("rates") or {}).get(key)
    if cached and now - float(cached.get("fetched_at") or 0) < EXCHANGE_RATE_CACHE_SECONDS:
        return {**cached, "cached": True}

    if currency == "HKD":
        try:
            data = get_json("https://api.frankfurter.dev/v2/rate/HKD/CNY", timeout=8)
            rate = float(data.get("rate"))
            payload = {
                "rate": rate,
                "base": "HKD",
                "target": "CNY",
                "date": data.get("date"),
                "source": "Frankfurter",
                "fetched_at": now,
                "cached": False,
            }
            cache.setdefault("rates", {})[key] = payload
            write_exchange_rate_cache(cache)
            return payload
        except Exception:
            if cached:
                return {**cached, "cached": True, "stale": True}

    return None
