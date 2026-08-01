"""Stock list enrichment and Graham valuation helpers."""

_execute_query = None
fetch_realtime_quotes = None
fetch_ytd_return = None


def configure(execute_query, realtime_quotes_func, ytd_return_func):
    global _execute_query, fetch_realtime_quotes, fetch_ytd_return
    _execute_query = execute_query
    fetch_realtime_quotes = realtime_quotes_func
    fetch_ytd_return = ytd_return_func


def _ensure_graham_valuation_table():
    _execute_query(
        """CREATE TABLE IF NOT EXISTS graham_valuations (
            stock_code VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
            growth_rate DECIMAL(10,4) NULL,
            payout_ratio DECIMAL(10,4) NULL,
            risk_free_rate DECIMAL(10,4) NULL,
            expected_profit DECIMAL(18,4) NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (stock_code),
            CONSTRAINT fk_graham_stock FOREIGN KEY (stock_code)
                REFERENCES stocks (code) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
        fetch=False,
    )


def _latest_total_shares(codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    try:
        rows = _execute_query(
            f"""SELECT stock_code, total_shares
                FROM (
                  SELECT stock_code, total_shares,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM custom_financials
                  WHERE stock_code IN ({placeholders}) AND total_shares IS NOT NULL AND total_shares > 0
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        return {r["stock_code"]: float(r["total_shares"]) for r in rows}
    except Exception:
        return {}


def _graham_defaults(codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    defaults = {code: {
        "growth_rate": 0.0,
        "payout_ratio": None,
        "risk_free_rate": 5.0,
        "expected_profit": None,
        "total_shares": None,
    } for code in codes}

    try:
        rows = _execute_query(
            f"""SELECT stock_code, AVG(ratio) AS avg_payout_ratio
                FROM (
                  SELECT stock_code,
                         dividend_amount / NULLIF(net_profit, 0) * 100 AS ratio,
                         ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY fiscal_year DESC) AS rn
                  FROM dividends
                  WHERE stock_code IN ({placeholders})
                    AND dividend_amount IS NOT NULL
                    AND net_profit IS NOT NULL
                    AND net_profit > 0
                ) t
                WHERE rn <= 3
                GROUP BY stock_code""",
            tuple(codes),
        )
        for r in rows:
            defaults[r["stock_code"]]["payout_ratio"] = (
                round(float(r["avg_payout_ratio"]), 2)
                if r["avg_payout_ratio"] is not None else None
            )
    except Exception:
        pass

    try:
        rows = _execute_query(
            f"""SELECT stock_code, parent_profit
                FROM (
                  SELECT stock_code, parent_profit,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY
                             CASE WHEN report_period='FY' THEN 0 ELSE 1 END,
                             fiscal_year DESC,
                             FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM custom_financials
                  WHERE stock_code IN ({placeholders})
                    AND parent_profit IS NOT NULL
                    AND parent_profit > 0
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        for r in rows:
            defaults[r["stock_code"]]["expected_profit"] = round(float(r["parent_profit"]), 2)
    except Exception:
        pass

    shares = _latest_total_shares(codes)
    for code, value in shares.items():
        defaults.setdefault(code, {})["total_shares"] = value
    return defaults


def _graham_custom_params(codes):
    if not codes:
        return {}
    _ensure_graham_valuation_table()
    placeholders = ",".join(["%s"] * len(codes))
    try:
        rows = _execute_query(
            f"""SELECT stock_code, growth_rate, payout_ratio, risk_free_rate, expected_profit
                FROM graham_valuations
                WHERE stock_code IN ({placeholders})""",
            tuple(codes),
        )
        return {
            r["stock_code"]: {
                "growth_rate": float(r["growth_rate"]) if r["growth_rate"] is not None else None,
                "payout_ratio": float(r["payout_ratio"]) if r["payout_ratio"] is not None else None,
                "risk_free_rate": float(r["risk_free_rate"]) if r["risk_free_rate"] is not None else None,
                "expected_profit": float(r["expected_profit"]) if r["expected_profit"] is not None else None,
            }
            for r in rows
        }
    except Exception:
        return {}


def _graham_payload(code):
    defaults = _graham_defaults([code]).get(code, {})
    custom = _graham_custom_params([code]).get(code, {})
    growth_rate = custom.get("growth_rate")
    payout_ratio = custom.get("payout_ratio")
    risk_free_rate = custom.get("risk_free_rate")
    expected_profit = custom.get("expected_profit")
    params = {
        "growth_rate": growth_rate if growth_rate is not None else defaults.get("growth_rate"),
        "payout_ratio": payout_ratio if payout_ratio is not None else defaults.get("payout_ratio"),
        "risk_free_rate": risk_free_rate if risk_free_rate is not None else defaults.get("risk_free_rate"),
        "expected_profit": expected_profit if expected_profit is not None else defaults.get("expected_profit"),
    }
    total_shares = defaults.get("total_shares")
    fair_valuation = None
    fair_price = None
    if (
        params["payout_ratio"] is not None
        and params["risk_free_rate"] is not None
        and params["risk_free_rate"] > 0
    ):
        fair_valuation = round(params["payout_ratio"] / params["risk_free_rate"] + (params["growth_rate"] or 0), 2)
    if fair_valuation is not None and params["expected_profit"] is not None and total_shares:
        fair_price = round(fair_valuation * params["expected_profit"] / total_shares, 2)
    return {
        "defaults": defaults,
        "custom": custom,
        "params": params,
        "total_shares": total_shares,
        "fair_valuation": fair_valuation,
        "fair_price": fair_price,
    }


def _enrich_stock_list_metrics(stocks, include_ytd=False):
    if not stocks:
        return stocks
    codes = [s["code"] for s in stocks]
    placeholders = ",".join(["%s"] * len(codes))
    quotes = fetch_realtime_quotes(stocks)

    latest_shares = _latest_total_shares(codes)
    graham_defaults = _graham_defaults(codes)
    graham_custom = _graham_custom_params(codes)

    latest_equity = {}
    try:
        rows = _execute_query(
            f"""SELECT stock_code, parent_equity, goodwill
                FROM (
                  SELECT stock_code, parent_equity, goodwill,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM balance_sheets
                  WHERE stock_code IN ({placeholders}) AND parent_equity IS NOT NULL
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        latest_equity = {
            r["stock_code"]: (
                float(r["parent_equity"]),
                float(r["goodwill"]) if r["goodwill"] is not None else 0.0,
            )
            for r in rows
        }
    except Exception:
        latest_equity = {}

    for s in stocks:
        code = s["code"]
        quote = quotes.get(code, {})
        price = quote.get("price")
        day_change_pct = quote.get("day_change_pct")
        s["price"] = round(price, 2) if price is not None else None
        s["day_change_pct"] = round(day_change_pct, 2) if day_change_pct is not None else None
        total_shares = latest_shares.get(code)
        defaults = graham_defaults.get(code, {})
        custom = graham_custom.get(code, {})
        params = {
            "growth_rate": custom.get("growth_rate") if custom.get("growth_rate") is not None else defaults.get("growth_rate"),
            "payout_ratio": custom.get("payout_ratio") if custom.get("payout_ratio") is not None else defaults.get("payout_ratio"),
            "risk_free_rate": custom.get("risk_free_rate") if custom.get("risk_free_rate") is not None else defaults.get("risk_free_rate"),
            "expected_profit": custom.get("expected_profit") if custom.get("expected_profit") is not None else defaults.get("expected_profit"),
        }
        fair_valuation = None
        fair_price = None
        if params["payout_ratio"] is not None and params["risk_free_rate"] is not None and params["risk_free_rate"] > 0:
            fair_valuation = round(params["payout_ratio"] / params["risk_free_rate"] + (params["growth_rate"] or 0), 2)
        if fair_valuation is not None and params["expected_profit"] is not None and total_shares:
            fair_price = round(fair_valuation * params["expected_profit"] / total_shares, 2)
        graham = {
            "defaults": defaults,
            "custom": custom,
            "params": params,
            "total_shares": total_shares,
            "fair_valuation": fair_valuation,
            "fair_price": fair_price,
        }
        s["graham"] = graham
        s["reasonable_valuation"] = graham["fair_valuation"]
        s["reasonable_price"] = graham["fair_price"]
        s["reasonable_discount"] = (
            round((price / graham["fair_price"] - 1) * 100, 2)
            if price is not None and graham["fair_price"] and graham["fair_price"] > 0
            else None
        )
        equity = latest_equity.get(code)
        s["pb_ex_goodwill"] = None
        if price and total_shares and equity:
            parent_equity, goodwill = equity
            net_equity = parent_equity - goodwill
            if net_equity > 0:
                s["pb_ex_goodwill"] = round(price * total_shares / net_equity, 2)
        s["ytd_return"] = fetch_ytd_return(code, s.get("market"), price) if include_ytd else None
    return stocks


def _stock_realtime_list_metrics(codes):
    if not codes:
        return []
    placeholders = ",".join(["%s"] * len(codes))
    stocks = _execute_query(
        f"SELECT code, market FROM stocks WHERE code IN ({placeholders})",
        tuple(codes),
    )
    if not stocks:
        return []

    quotes = fetch_realtime_quotes(stocks)
    latest_shares = _latest_total_shares(codes)
    graham_defaults = _graham_defaults(codes)
    graham_custom = _graham_custom_params(codes)

    latest_equity = {}
    try:
        rows = _execute_query(
            f"""SELECT stock_code, parent_equity, goodwill
                FROM (
                  SELECT stock_code, parent_equity, goodwill,
                         ROW_NUMBER() OVER (
                           PARTITION BY stock_code
                           ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                         ) AS rn
                  FROM balance_sheets
                  WHERE stock_code IN ({placeholders}) AND parent_equity IS NOT NULL
                ) t
                WHERE rn=1""",
            tuple(codes),
        )
        latest_equity = {
            r["stock_code"]: (
                float(r["parent_equity"]),
                float(r["goodwill"]) if r["goodwill"] is not None else 0.0,
            )
            for r in rows
        }
    except Exception:
        latest_equity = {}

    result = []
    for s in stocks:
        code = s["code"]
        quote = quotes.get(code, {})
        price = quote.get("price")
        day_change_pct = quote.get("day_change_pct")
        total_shares = latest_shares.get(code)
        defaults = graham_defaults.get(code, {})
        custom = graham_custom.get(code, {})
        params = {
            "growth_rate": custom.get("growth_rate") if custom.get("growth_rate") is not None else defaults.get("growth_rate"),
            "payout_ratio": custom.get("payout_ratio") if custom.get("payout_ratio") is not None else defaults.get("payout_ratio"),
            "risk_free_rate": custom.get("risk_free_rate") if custom.get("risk_free_rate") is not None else defaults.get("risk_free_rate"),
            "expected_profit": custom.get("expected_profit") if custom.get("expected_profit") is not None else defaults.get("expected_profit"),
        }
        fair_valuation = None
        fair_price = None
        if params["payout_ratio"] is not None and params["risk_free_rate"] is not None and params["risk_free_rate"] > 0:
            fair_valuation = round(params["payout_ratio"] / params["risk_free_rate"] + (params["growth_rate"] or 0), 2)
        if fair_valuation is not None and params["expected_profit"] is not None and total_shares:
            fair_price = round(fair_valuation * params["expected_profit"] / total_shares, 2)

        reasonable_discount = (
            round((price / fair_price - 1) * 100, 2)
            if price is not None and fair_price and fair_price > 0
            else None
        )
        pb_ex_goodwill = None
        equity = latest_equity.get(code)
        if price and total_shares and equity:
            parent_equity, goodwill = equity
            net_equity = parent_equity - goodwill
            if net_equity > 0:
                pb_ex_goodwill = round(price * total_shares / net_equity, 2)

        result.append({
            "code": code,
            "price": round(price, 2) if price is not None else None,
            "day_change_pct": round(day_change_pct, 2) if day_change_pct is not None else None,
            "reasonable_valuation": fair_valuation,
            "reasonable_price": fair_price,
            "reasonable_discount": reasonable_discount,
            "pb_ex_goodwill": pb_ex_goodwill,
        })
    return result

