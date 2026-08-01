"""Dividend and financing routes for stock detail pages."""

import requests
from flask import jsonify, request


def register_corporate_action_routes(app, deps):
    Stock = deps["Stock"]
    execute_query = deps["execute_query"]
    eastmoney_secu_code = deps["eastmoney_secu_code"]
    as_list = deps["as_list"]
    date_only = deps["date_only"]
    money_yuan = deps["money_yuan"]
    to_float = deps["to_float"]

    @app.route("/api/stock/<code>/dividends")
    def api_stock_dividends(code):
        start_year = request.args.get("start_year", type=int)
        end_year = request.args.get("end_year", type=int)
        sql = "SELECT fiscal_year, net_profit, dividend_amount, dividend_per_share, ex_date FROM dividends WHERE stock_code = %s"
        params = [code]
        if start_year is not None:
            sql += " AND fiscal_year >= %s"
            params.append(start_year)
        if end_year is not None:
            sql += " AND fiscal_year <= %s"
            params.append(end_year)
        sql += " ORDER BY fiscal_year"
        rows = execute_query(sql, tuple(params))
        result = []
        for r in rows:
            result.append({
                "fiscal_year": r["fiscal_year"],
                "net_profit": float(r["net_profit"]) if r["net_profit"] else 0,
                "dividend_amount": float(r["dividend_amount"]) if r["dividend_amount"] else 0,
                "dividend_per_share": float(r["dividend_per_share"]) if r["dividend_per_share"] else 0,
                "ex_date": str(r["ex_date"]) if r["ex_date"] else None,
            })
        return jsonify(result)

    @app.route("/api/stock/<code>/financing")
    def api_stock_financing(code):
        stock = Stock.get_by_code(code)
        if not stock:
            return jsonify({"error": "未找到该股票"}), 404
        if (stock.get("market") or "").upper() == "HK":
            return jsonify({
                "source": "港股暂不支持 A 股分红融资口径",
                "annual": [],
                "details": [],
            })

        secu_code = eastmoney_secu_code(code, stock.get("market"))
        try:
            resp = requests.get(
                "https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/PageAjax",
                params={"code": secu_code},
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/BonusFinancing/Index?code={stock.get('market', '')}{code}&type=web",
                },
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            return jsonify({"error": "融资数据获取失败: " + str(e)}), 502

        annual_by_year = {}
        for row in as_list(payload.get("lnfhrz")):
            year = str(row.get("STATISTICS_YEAR") or "").strip()
            if not year:
                continue
            annual_by_year[year] = {
                "year": year,
                "dividend_amount": money_yuan(row.get("TOTAL_DIVIDEND")),
                "financing_amount": 0.0,
                "seo_shares": money_yuan(row.get("SEO_NUM")),
                "allotment_shares": money_yuan(row.get("ALLOTMENT_NUM")),
                "ipo_shares": money_yuan(row.get("IPO_NUM")),
            }

        details = []

        def add_detail(row, financing_type):
            if not row:
                return
            notice_date = date_only(row.get("NOTICE_DATE"))
            year = (notice_date or "")[:4]
            issue_price = to_float(row.get("ISSUE_PRICE"))
            issue_shares = money_yuan(row.get("ISSUE_NUM"))
            if financing_type == "增发":
                amount = money_yuan(row.get("NET_RAISE_FUNDS") or row.get("TOTAL_RAISE_FUNDS"))
                method = row.get("ISSUE_WAY_EXPLAIN")
                price_method = row.get("ISSUE_PRICE_EXPLAIN")
                target = row.get("ISSUE_OBJECT") or row.get("ISSUE_TARGET") or row.get("OBJECT")
                listing_date = date_only(row.get("LISTING_DATE"))
            else:
                amount = money_yuan(row.get("TOTAL_RAISE_FUNDS") or row.get("NET_RAISE_FUNDS"))
                method = row.get("EVENT_EXPLAIN")
                price_method = row.get("ISSUE_PRICE_EXPLAIN")
                target = None
                listing_date = date_only(row.get("EX_DIVIDEND_DATEE") or row.get("EX_DIVIDEND_DATE"))

            if year:
                annual = annual_by_year.setdefault(year, {
                    "year": year,
                    "dividend_amount": 0.0,
                    "financing_amount": 0.0,
                    "seo_shares": 0.0,
                    "allotment_shares": 0.0,
                    "ipo_shares": 0.0,
                })
                annual["financing_amount"] += amount

            details.append({
                "date": notice_date,
                "type": financing_type,
                "issue_price": issue_price,
                "issue_shares": issue_shares,
                "amount": amount,
                "amount_label": "实际募集净额" if financing_type == "增发" else "实际募资总额",
                "method": method,
                "price_method": price_method,
                "target": target,
                "registration_date": date_only(row.get("REG_DATE") or row.get("EQUITY_RECORD_DATE")),
                "listing_date": listing_date,
                "receive_date": date_only(row.get("RECEIVE_DATE")),
            })

        for row in as_list(payload.get("zfmx")):
            add_detail(row, "增发")
        for row in as_list(payload.get("pgmx")):
            add_detail(row, "配股")

        annual = []
        cumulative_dividend = 0.0
        cumulative_financing = 0.0
        for year, row in sorted(annual_by_year.items(), key=lambda item: item[0]):
            cumulative_dividend += row["dividend_amount"]
            cumulative_financing += row["financing_amount"]
            ratio = (cumulative_dividend / cumulative_financing * 100) if cumulative_financing > 0 else None
            annual.append({
                **row,
                "annual_dividend_amount": row["dividend_amount"],
                "annual_financing_amount": row["financing_amount"],
                "dividend_amount": cumulative_dividend,
                "financing_amount": cumulative_financing,
                "ratio": round(ratio, 2) if ratio is not None else None,
            })

        details.sort(key=lambda item: item.get("date") or "", reverse=True)
        return jsonify({
            "source": "东方财富 F10 分红融资",
            "annual": annual,
            "details": details,
        })
