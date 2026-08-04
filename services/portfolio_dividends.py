"""Portfolio dividend lookup helpers."""


def latest_dividend_per_share(execute_query, codes):
    if not codes:
        return {}
    placeholders = ",".join(["%s"] * len(codes))
    rows = execute_query(
        f"""SELECT stock_code, dividend_per_share, fiscal_year
            FROM (
              SELECT stock_code, dividend_per_share, fiscal_year,
                     ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY fiscal_year DESC) AS rn
              FROM dividends
              WHERE stock_code IN ({placeholders}) AND dividend_per_share IS NOT NULL
            ) t
            WHERE rn=1
            ORDER BY stock_code, fiscal_year DESC""",
        tuple(codes),
    )
    result = {}
    for r in rows:
        code = r["stock_code"]
        item = result.setdefault(code, {})
        if "dividend_per_share" not in item:
            item["dividend_per_share"] = float(r["dividend_per_share"])
            item["fiscal_year"] = int(r["fiscal_year"])
    return result
