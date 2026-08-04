"""Business segment routes for stock detail pages."""

import re
import time

import requests
from flask import jsonify, request

from services.background_jobs import start_endpoint_stock_batch


def register_segment_routes(app, deps):
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _schedule_auto_cloud_backup = deps.get("schedule_auto_cloud_backup")
    _get_update_stocks = deps["get_update_stocks"]

    SEGMENT_DIMENSIONS = {
        "business": "按业务",
        "product": "按产品",
        "region": "按地区",
    }


    def _ensure_segments_table():
        """Create the business segment table used by the revenue composition tab."""
        execute_query(
            """CREATE TABLE IF NOT EXISTS business_segments (
                id BIGINT NOT NULL AUTO_INCREMENT,
                stock_code VARCHAR(10) NOT NULL,
                fiscal_year INT NOT NULL,
                report_period VARCHAR(8) NOT NULL DEFAULT 'FY',
                dimension_type VARCHAR(20) NOT NULL,
                segment_name VARCHAR(120) NOT NULL,
                revenue DECIMAL(18,4) DEFAULT NULL,
                cost DECIMAL(18,4) DEFAULT NULL,
                gross_profit DECIMAL(18,4) DEFAULT NULL,
                gross_margin DECIMAL(10,4) DEFAULT NULL,
                revenue_ratio DECIMAL(10,4) DEFAULT NULL,
                profit_ratio DECIMAL(10,4) DEFAULT NULL,
                source VARCHAR(50) DEFAULT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uk_segment (stock_code, fiscal_year, report_period, dimension_type, segment_name),
                KEY idx_segment_stock_year (stock_code, fiscal_year),
                KEY idx_segment_dimension (stock_code, dimension_type)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci""",
            fetch=False,
        )


    def _clean_cell(value):
        value = re.sub(r"<[^>]+>", "", value or "")
        value = html_lib.unescape(value)
        return value.replace("\xa0", " ").strip()


    def _to_number(value, percent=False):
        if value is None:
            return None
        text = _clean_cell(str(value)).replace(",", "").replace("，", "")
        text = text.replace("%", "").replace("％", "").strip()
        text = text.replace("--", "").replace("－", "").replace("—", "")
        if not text:
            return None
        match = re.search(r"-?\d+(?:\.\d+)?", text)
        if not match:
            return None
        num = float(match.group(0))
        if percent:
            return round(num, 4)
        if "亿元" in text or "亿" in text:
            return round(num, 4)
        # Sina main-business tables are usually reported in 万元.
        return round(num / 10000, 4)


    def _detect_segment_dimension(text):
        if "按产品" in text or "产品构成" in text:
            return "product"
        if "按地区" in text or "地区构成" in text:
            return "region"
        if "按行业" in text or "业务构成" in text or "行业构成" in text:
            return "business"
        return None


    def _detect_report_period(text):
        match = re.search(r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})?", text)
        if not match:
            match = re.search(r"(20\d{2})", text)
            return (int(match.group(1)), "FY") if match else (None, "FY")
        year = int(match.group(1))
        month = int(match.group(2))
        period = {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")
        return year, period


    def _parse_sina_segments(page_html):
        """Best-effort parser for Sina main-business composition tables."""
        records = []
        table_matches = list(re.finditer(r"<table[^>]*>(.*?)</table>", page_html, re.DOTALL | re.IGNORECASE))

        for match in table_matches:
            table_html = match.group(1)
            context_html = page_html[max(0, match.start() - 1200):match.start()]
            context_text = _clean_cell(context_html)
            table_text = _clean_cell(table_html)
            if "主营" not in table_text and "营业收入" not in table_text:
                continue

            dimension = _detect_segment_dimension(context_text + table_text)
            if not dimension:
                continue

            fiscal_year, report_period = _detect_report_period(context_text + table_text)
            if not fiscal_year:
                continue

            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
            header_cells = []
            col_map = {}
            for row_html in rows:
                cells = [_clean_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE)]
                if not cells:
                    continue
                joined = "".join(cells)
                if ("主营收入" in joined or "营业收入" in joined) and ("项目" in joined or "名称" in joined or "构成" in joined):
                    header_cells = cells
                    break

            if header_cells:
                for idx, label in enumerate(header_cells):
                    if any(k in label for k in ("项目", "名称", "构成")):
                        col_map["name"] = idx
                    elif "收入" in label and "比例" not in label and "占比" not in label:
                        col_map["revenue"] = idx
                    elif "成本" in label:
                        col_map["cost"] = idx
                    elif "利润" in label and "率" not in label and "比例" not in label:
                        col_map["gross_profit"] = idx
                    elif "毛利率" in label or "利润率" in label:
                        col_map["gross_margin"] = idx

            if "name" not in col_map:
                col_map["name"] = 0
            if "revenue" not in col_map:
                col_map["revenue"] = 1
            if "cost" not in col_map:
                col_map["cost"] = 2
            if "gross_profit" not in col_map:
                col_map["gross_profit"] = 3
            if "gross_margin" not in col_map:
                col_map["gross_margin"] = 4

            for row_html in rows:
                cells = [_clean_cell(c) for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, re.DOTALL | re.IGNORECASE)]
                if len(cells) <= col_map.get("revenue", 1):
                    continue
                name = cells[col_map["name"]].strip()
                if not name or any(x in name for x in ("项目", "合计", "总计", "主营业务")):
                    continue
                revenue = _to_number(cells[col_map["revenue"]])
                cost = _to_number(cells[col_map["cost"]]) if len(cells) > col_map["cost"] else None
                gross_profit = _to_number(cells[col_map["gross_profit"]]) if len(cells) > col_map["gross_profit"] else None
                gross_margin = _to_number(cells[col_map["gross_margin"]], percent=True) if len(cells) > col_map["gross_margin"] else None
                if revenue is None:
                    continue
                if gross_profit is None and cost is not None:
                    gross_profit = round(revenue - cost, 4)
                if gross_margin is None and revenue not in (None, 0) and gross_profit is not None:
                    gross_margin = round(gross_profit / revenue * 100, 4)
                records.append({
                    "fiscal_year": fiscal_year,
                    "report_period": report_period,
                    "dimension_type": dimension,
                    "segment_name": name[:120],
                    "revenue": revenue,
                    "cost": cost,
                    "gross_profit": gross_profit,
                    "gross_margin": gross_margin,
                    "source": "sina",
                })

        grouped = {}
        for r in records:
            key = (r["fiscal_year"], r["report_period"], r["dimension_type"])
            grouped.setdefault(key, []).append(r)
        for rows in grouped.values():
            total_revenue = sum((r["revenue"] or 0) for r in rows)
            total_profit = sum((r["gross_profit"] or 0) for r in rows)
            for r in rows:
                r["revenue_ratio"] = round((r["revenue"] or 0) / total_revenue * 100, 4) if total_revenue else None
                r["profit_ratio"] = round((r["gross_profit"] or 0) / total_profit * 100, 4) if total_profit else None
        return records


    def _yuan_to_yi(value):
        if value is None:
            return None
        return round(float(value) / 100000000, 4)


    def _ratio_to_pct(value):
        if value is None:
            return None
        return round(float(value) * 100, 4)


    def _parse_eastmoney_segments(payload):
        type_map = {"1": "business", "2": "product", "3": "region"}
        data = ((payload or {}).get("result") or {}).get("data") or []
        records = []
        for row in data:
            dimension = type_map.get(str(row.get("MAINOP_TYPE") or ""))
            if not dimension:
                continue
            report_date = row.get("REPORT_DATE") or ""
            year_match = re.search(r"(20\d{2})", report_date)
            if not year_match:
                continue
            fiscal_year = int(year_match.group(1))
            month_match = re.search(r"20\d{2}-(\d{2})", report_date)
            month = int(month_match.group(1)) if month_match else 12
            report_period = {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")
            name = (row.get("ITEM_NAME") or "").strip()
            if not name:
                continue
            revenue = _yuan_to_yi(row.get("MAIN_BUSINESS_INCOME"))
            cost = _yuan_to_yi(row.get("MAIN_BUSINESS_COST"))
            gross_profit = _yuan_to_yi(row.get("MAIN_BUSINESS_RPOFIT"))
            gross_margin = _ratio_to_pct(row.get("GROSS_RPOFIT_RATIO"))
            if revenue is None:
                continue
            if gross_profit is None and cost is not None:
                gross_profit = round(revenue - cost, 4)
            if gross_margin is None and revenue and gross_profit is not None:
                gross_margin = round(gross_profit / revenue * 100, 4)
            records.append({
                "fiscal_year": fiscal_year,
                "report_period": report_period,
                "dimension_type": dimension,
                "segment_name": name[:120],
                "revenue": revenue,
                "cost": cost,
                "gross_profit": gross_profit,
                "gross_margin": gross_margin,
                "revenue_ratio": _ratio_to_pct(row.get("MBI_RATIO")),
                "profit_ratio": _ratio_to_pct(row.get("MBR_RATIO")),
                "source": "eastmoney",
            })
        return records


    def _upsert_segments(stock_code, records):
        for r in records:
            execute_query(
                """INSERT INTO business_segments
                   (stock_code, fiscal_year, report_period, dimension_type, segment_name,
                    revenue, cost, gross_profit, gross_margin, revenue_ratio, profit_ratio, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON DUPLICATE KEY UPDATE
                    revenue=VALUES(revenue), cost=VALUES(cost), gross_profit=VALUES(gross_profit),
                    gross_margin=VALUES(gross_margin), revenue_ratio=VALUES(revenue_ratio),
                    profit_ratio=VALUES(profit_ratio), source=VALUES(source)""",
                (
                    stock_code, r["fiscal_year"], r["report_period"], r["dimension_type"], r["segment_name"],
                    r.get("revenue"), r.get("cost"), r.get("gross_profit"), r.get("gross_margin"),
                    r.get("revenue_ratio"), r.get("profit_ratio"), r.get("source"),
                ),
                fetch=False,
            )


    def _segment_summary(rows):
        if not rows:
            return None
        latest_year = max(r["fiscal_year"] for r in rows)
        latest = [r for r in rows if r["fiscal_year"] == latest_year]
        revenue_rows = sorted(latest, key=lambda x: x.get("revenue") or 0, reverse=True)
        profit_rows = sorted(latest, key=lambda x: x.get("gross_profit") or 0, reverse=True)
        total_revenue = sum((r.get("revenue") or 0) for r in latest)
        total_profit = sum((r.get("gross_profit") or 0) for r in latest)
        top3_revenue = sum((r.get("revenue") or 0) for r in revenue_rows[:3])
        return {
            "latest_year": latest_year,
            "top_revenue_segment": revenue_rows[0]["segment_name"] if revenue_rows else None,
            "top_revenue_ratio": revenue_rows[0].get("revenue_ratio") if revenue_rows else None,
            "top_profit_segment": profit_rows[0]["segment_name"] if profit_rows else None,
            "top_profit_ratio": profit_rows[0].get("profit_ratio") if profit_rows else None,
            "top3_revenue_ratio": round(top3_revenue / total_revenue * 100, 2) if total_revenue else None,
            "gross_margin": round(total_profit / total_revenue * 100, 2) if total_revenue and total_profit else None,
        }


    @app.route("/api/stock/<code>/segments")
    def api_stock_segments(code):
        _ensure_segments_table()
        dimension = request.args.get("dimension", "business")
        if dimension not in SEGMENT_DIMENSIONS:
            dimension = "business"
        from_year = request.args.get("from_year", 2000, type=int)
        to_year = request.args.get("to_year", 2030, type=int)
        rows = execute_query(
            """SELECT fiscal_year, report_period, dimension_type, segment_name, revenue, cost,
                      gross_profit, gross_margin, revenue_ratio, profit_ratio, source
               FROM business_segments
               WHERE stock_code=%s AND dimension_type=%s AND report_period='FY'
                 AND fiscal_year BETWEEN %s AND %s
               ORDER BY fiscal_year ASC, revenue DESC""",
            (code, dimension, from_year, to_year),
        )
        result = []
        for r in rows:
            item = dict(r)
            for col in ("revenue", "cost", "gross_profit", "gross_margin", "revenue_ratio", "profit_ratio"):
                item[col] = float(item[col]) if item.get(col) is not None else None
            result.append(item)
        return jsonify({"data": result, "summary": _segment_summary(result)})


    @app.route("/api/update-segments", methods=["POST"])
    def api_update_segments():
        _ensure_segments_table()
        payload = request.get_json(silent=True) or {}
        stocks = _get_update_stocks(payload)
        if len(stocks) > 1 or (payload.get("background") and stocks):
            return jsonify(start_endpoint_stock_batch(
                app,
                get_connection,
                execute_query,
                "update_segments",
                "营收构成更新",
                payload,
                stocks,
                api_update_segments,
                "/api/update-segments",
                on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("segments-update"),
            ))

        updated = 0
        errors = []
        for s in stocks:
            stock_code = s["code"]
            try:
                url = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
                resp = requests.get(
                    url,
                    params={
                        "reportName": "RPT_F10_FN_MAINOP",
                        "columns": "ALL",
                        "filter": f'(SECURITY_CODE="{stock_code}")',
                        "pageNumber": 1,
                        "pageSize": 500,
                        "sortColumns": "REPORT_DATE",
                        "sortTypes": -1,
                    },
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"},
                    timeout=15,
                )
                records = _parse_eastmoney_segments(resp.json())
                if not records:
                    errors.append(f"{stock_code}: 未解析到业务构成数据")
                    continue
                _upsert_segments(stock_code, records)
                updated += len(records)
            except Exception as e:
                errors.append(f"{stock_code}: {str(e)}")
            time.sleep(0.3)

        return jsonify({
            "success": len(errors) == 0 or updated > 0,
            "records_updated": updated,
            "stocks_processed": len(stocks),
            "errors": errors[:5] if errors else [],
        })

    return _ensure_segments_table
