"""Market quote and price history helpers."""

from datetime import datetime

from services.providers.tencent import fq_kline, quote_text


def fetch_realtime_quotes(stocks, quote_symbol):
    symbols = [quote_symbol(s["code"], s.get("market")) for s in stocks]
    if not symbols:
        return {}
    quotes = {}
    try:
        text = quote_text(symbols, timeout=10)
        for line in text.split(";"):
            if "=" not in line:
                continue
            parts = line.split('"')
            if len(parts) < 2:
                continue
            fields = parts[1].split("~")
            if len(fields) >= 4:
                code = fields[2]
                quote = {}
                try:
                    quote["price"] = float(fields[3])
                except (TypeError, ValueError):
                    pass
                if len(fields) > 31:
                    try:
                        quote["day_change"] = float(fields[31])
                    except (TypeError, ValueError):
                        pass
                if len(fields) > 32:
                    try:
                        quote["day_change_pct"] = float(fields[32])
                    except (TypeError, ValueError):
                        pass
                if len(fields) > 30:
                    quote_time = str(fields[30] or "").strip()
                    if len(quote_time) >= 8 and quote_time[:8].isdigit():
                        quote["quote_date"] = quote_time[:8]
                        quote["quote_time"] = quote_time
                if quote:
                    quotes[code] = quote
    except Exception:
        pass
    return quotes


def fetch_realtime_prices(stocks, quote_symbol):
    quotes = fetch_realtime_quotes(stocks, quote_symbol)
    return {
        code: quote.get("price")
        for code, quote in quotes.items()
        if quote.get("price") is not None
    }


def fetch_ytd_return(code, market, quote_symbol, current_price=None):
    try:
        year = datetime.now().year
        symbol = quote_symbol(code, market)
        data = fq_kline(symbol, start=f"{year-1}-12-01", count=360, timeout=8)
        stock_data = (data.get("data") or {}).get(symbol, {})
        rows = stock_data.get("qfqday") or stock_data.get("day") or []
        if not rows:
            return None

        baseline_close = None
        for row in rows:
            if row[0] < f"{year}-01-01":
                baseline_close = float(row[2])
            else:
                break
        if baseline_close is None:
            baseline_close = float(rows[0][1])

        latest_close = current_price if current_price and current_price > 0 else float(rows[-1][2])
        if baseline_close <= 0:
            return None
        return round((latest_close / baseline_close - 1) * 100, 2)
    except Exception:
        return None
