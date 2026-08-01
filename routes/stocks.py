"""Homepage stock list and Graham valuation routes."""

import re

from flask import jsonify, request


def register_stock_routes(app, deps):
    """Register stock-list routes without changing their public endpoint names."""
    Stock = deps["Stock"]
    execute_query = deps["execute_query"]
    ensure_stock_order_column = deps["ensure_stock_order_column"]
    enrich_stock_list_metrics = deps["enrich_stock_list_metrics"]
    stock_realtime_list_metrics = deps["stock_realtime_list_metrics"]
    fetch_ytd_return = deps["fetch_ytd_return"]
    graham_payload = deps["graham_payload"]
    ensure_graham_valuation_table = deps["ensure_graham_valuation_table"]

    @app.route("/api/stocks")
    def api_stocks():
        ensure_stock_order_column()
        page = request.args.get("page", 1, type=int)
        page_size = request.args.get("page_size", 15, type=int)
        market = request.args.get("market", None)
        status = request.args.get("status", None)
        keyword = request.args.get("keyword", None)
        light = request.args.get("light") == "1"
        sort_by = request.args.get("sort_by", "").strip()
        sort_dir = request.args.get("sort_dir", "asc").lower()
        sort_fields = {
            "code", "name", "day_change_pct", "price", "pe_ttm",
            "pb_ex_goodwill", "dividend_yield", "ytd_return",
            "reasonable_valuation", "reasonable_price", "reasonable_discount",
        }

        if sort_by in sort_fields:
            all_result = Stock.get_all(
                page=1, page_size=10000,
                market=market or None,
                status=status or None,
                keyword=keyword or None,
            )
            rows = enrich_stock_list_metrics(
                all_result.get("data") or [],
                include_ytd=sort_by == "ytd_return",
            )
            reverse = sort_dir == "desc"

            def sort_value(row):
                value = row.get(sort_by)
                if sort_by in {"code", "name"}:
                    return str(value or "")
                return float(value) if value is not None else 0

            rows.sort(key=sort_value, reverse=reverse)
            rows.sort(key=lambda row: row.get(sort_by) is None)
            total = len(rows)
            start = (page - 1) * page_size
            end = start + page_size
            return jsonify({
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": max(1, (total + page_size - 1) // page_size),
                "data": rows[start:end],
                "sort_by": sort_by,
                "sort_dir": sort_dir,
            })

        result = Stock.get_all(
            page=page, page_size=page_size,
            market=market or None,
            status=status or None,
            keyword=keyword or None,
        )
        if not light:
            result["data"] = enrich_stock_list_metrics(result.get("data") or [])
        result["sort_by"] = ""
        result["sort_dir"] = ""
        return jsonify(result)

    @app.route("/api/stocks/realtime")
    def api_stocks_realtime():
        raw_codes = request.args.get("codes", "")
        codes = []
        for code in raw_codes.split(","):
            code = code.strip()
            if re.match(r"^\d{5,6}$", code) and code not in codes:
                codes.append(code)
        if not codes:
            return jsonify({"data": []})
        return jsonify({"data": stock_realtime_list_metrics(codes[:200])})

    @app.route("/api/stocks/ytd")
    def api_stocks_ytd():
        raw_codes = request.args.get("codes", "")
        codes = []
        for code in raw_codes.split(","):
            code = code.strip()
            if re.match(r"^\d{5,6}$", code) and code not in codes:
                codes.append(code)
        if not codes:
            return jsonify({"data": []})

        placeholders = ",".join(["%s"] * len(codes[:200]))
        stocks = execute_query(
            f"SELECT code, market FROM stocks WHERE code IN ({placeholders})",
            tuple(codes[:200]),
        )
        return jsonify({
            "data": [
                {
                    "code": s["code"],
                    "ytd_return": fetch_ytd_return(s["code"], s.get("market")),
                }
                for s in stocks
            ]
        })

    @app.route("/api/stock/<code>/graham-valuation", methods=["GET"])
    def api_graham_valuation_get(code):
        return jsonify(graham_payload(code))

    @app.route("/api/stock/<code>/graham-valuation", methods=["PUT"])
    def api_graham_valuation_put(code):
        ensure_graham_valuation_table()
        data = request.get_json(force=True)

        def parse_optional_number(name):
            value = data.get(name)
            if value in (None, ""):
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                raise ValueError(name)

        try:
            growth_rate = parse_optional_number("growth_rate")
            payout_ratio = parse_optional_number("payout_ratio")
            risk_free_rate = parse_optional_number("risk_free_rate")
            expected_profit = parse_optional_number("expected_profit")
        except ValueError as e:
            return jsonify({"error": f"{e.args[0]} 必须是数字"}), 400

        if payout_ratio is not None and payout_ratio < 0:
            return jsonify({"error": "分红比例不能小于 0"}), 400
        if risk_free_rate is not None and risk_free_rate <= 0:
            return jsonify({"error": "无风险利率必须大于 0"}), 400
        if expected_profit is not None and expected_profit < 0:
            return jsonify({"error": "当年预期利润不能小于 0"}), 400

        execute_query(
            """INSERT INTO graham_valuations
               (stock_code, growth_rate, payout_ratio, risk_free_rate, expected_profit)
               VALUES (%s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                 growth_rate=VALUES(growth_rate),
                 payout_ratio=VALUES(payout_ratio),
                 risk_free_rate=VALUES(risk_free_rate),
                 expected_profit=VALUES(expected_profit),
                 updated_at=CURRENT_TIMESTAMP""",
            (code, growth_rate, payout_ratio, risk_free_rate, expected_profit),
            fetch=False,
        )
        return jsonify({"ok": True, **graham_payload(code)})

    @app.route("/api/stocks/reorder", methods=["POST"])
    def api_stocks_reorder():
        ensure_stock_order_column()
        data = request.get_json(force=True)
        codes = data.get("codes") or []
        if not codes:
            return jsonify({"error": "empty codes"}), 400
        for idx, code in enumerate(codes, start=1):
            execute_query(
                "UPDATE stocks SET display_order=%s WHERE code=%s",
                (idx, code),
                fetch=False,
            )
        return jsonify({"ok": True, "updated": len(codes)})
