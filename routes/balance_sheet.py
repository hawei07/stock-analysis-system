"""Balance sheet update and query routes."""

import time

import requests
from flask import jsonify, request

from services.background_jobs import start_endpoint_stock_batch


def register_balance_sheet_routes(app, deps):
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _schedule_auto_cloud_backup = deps.get("schedule_auto_cloud_backup")
    _get_update_stocks = deps["get_update_stocks"]

    # 新浪资产负债表 → 数据库字段映射 (中文行名 → DB column)
    BS_ROW_MAP = [
        # 流动资产
        ("货币资金", "monetary_funds"),
        ("交易性金融资产", "trading_fin_assets"),
        ("应收票据", "notes_receivable"),
        ("应收账款", "accounts_receivable"),
        ("应收款项融资", "receivables_financing"),
        ("预付款项", "prepayment"),
        ("其他应收款", "other_receivables"),       # 匹配"其他应收款(合计)"
        ("存货", "inventory"),
        ("一年内到期的非流动资产", "noncurrent_assets_due1y"),
        ("其他流动资产", "other_current_assets"),
        ("流动资产合计", "total_current_assets"),
        # 非流动资产
        ("持有至到期投资", "held_to_maturity_invest"),
        ("长期股权投资", "longterm_equity_invest"),
        ("投资性房地产", "investment_property"),
        ("在建工程", "cip"),                       # 匹配"在建工程(合计)"
        ("固定资产", "fixed_assets"),             # 匹配"固定资产及清理(合计)"
        ("使用权资产", "right_of_use_assets"),
        ("无形资产", "intangible_assets"),
        ("开发支出", "development_expenditure"),
        ("商誉", "goodwill"),
        ("长期待摊费用", "longterm_prepaid_expense"),
        ("递延所得税资产", "deferred_tax_assets"),
        ("其他非流动资产", "other_noncurrent_assets"),
        ("非流动资产合计", "total_noncurrent_assets"),
        ("资产总计", "total_assets"),
        # 流动负债
        ("短期借款", "short_borrow"),
        ("应付票据", "notes_payable"),
        ("应付账款", "accounts_payable"),
        ("预收款项", "advance_receipts"),
        ("应付职工薪酬", "payroll_payable"),
        ("应交税费", "taxes_payable"),
        ("其他应付款", "other_payables"),         # 匹配"其他应付款(合计)"
        ("一年内到期的非流动负债", "noncurrent_liab_due1y"),
        ("其他流动负债", "other_current_liabilities"),
        ("流动负债合计", "total_current_liabilities"),
        # 非流动负债
        ("长期借款", "long_borrow"),
        ("应付债券", "bonds_payable"),
        ("租赁负债", "lease_liabilities"),
        ("递延所得税负债", "deferred_tax_liabilities"),
        ("非流动负债合计", "total_noncurrent_liabilities"),
        ("负债合计", "total_liabilities"),
        # 股东权益
        ("实收资本", "paid_in_capital"),          # 匹配"实收资本(或股本)"
        ("资本公积", "capital_reserve"),
        ("库存股", "treasury_stock"),             # 匹配"减：库存股"
        ("盈余公积", "surplus_reserve"),
        ("未分配利润", "retained_earnings"),
        ("归属于母公司股东权益合计", "parent_equity"),
        ("少数股东权益", "minority_interests"),
        ("所有者权益", "total_equity"),            # 匹配"所有者权益(或股东权益)合计"
    ]

    # 所有 BS 字段列表（用于查询 + INSERT 构建）
    BS_COLUMNS = [col for _, col in BS_ROW_MAP]


    def _period_from_date(date_str):
        """根据日期返回报告期: 03-31→Q1, 06-30→Q2, 09-30→Q3, 12-31→FY"""
        month = int(date_str[5:7])
        day = int(date_str[8:10])
        if month == 3 and day == 31:
            return "Q1"
        elif month == 6 and day == 30:
            return "Q2"
        elif month == 9 and day == 30:
            return "Q3"
        elif month == 12 and day == 31:
            return "FY"
        return None


    def _parse_sina_bs(html):
        """解析新浪资产负债表 HTML，提取各季度科目数据（万元→亿元）。
        返回 {(year, period): {col: val}} 字典，period ∈ {FY, Q1, Q2, Q3}。
        """
        import re as _re

        all_tables = _re.findall(r'<table[^>]*>(.*?)</table>', html, _re.DOTALL)
        all_data = {}  # (year, period) → {col: value}

        for table_html in all_tables:
            if '报表日期' not in table_html or '货币资金' not in table_html:
                continue

            rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, _re.DOTALL)

            # 在表头行中找所有日期列 → (col_idx, year, period, date_str)
            date_cols = []
            for r in rows:
                cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if any('报表日期' in c for c in cells):
                    for idx, c in enumerate(cells):
                        m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', c)
                        if m:
                            year, date_str = int(m.group(1)), m.group(0)
                            period = _period_from_date(date_str)
                            if period:
                                date_cols.append((idx, year, period, date_str))
                    break

            if not date_cols:
                continue

            # 解析每个日期列的数据
            for col_idx, col_year, period, date_str in date_cols:
                values = {}
                for r in rows:
                    cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                    cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                    if not cells or len(cells) <= col_idx:
                        continue

                    row_name = cells[0]
                    raw_val = cells[col_idx]

                    for pattern, col in BS_ROW_MAP:
                        if row_name.startswith(pattern) or (pattern == "库存股" and "库存股" in row_name):
                            if raw_val and raw_val not in ("--", "", "None"):
                                try:
                                    values[col] = round(float(raw_val.replace(",", "")) / 10000, 4)
                                except ValueError:
                                    pass
                            break

                if values:
                    key = (col_year, period)
                    # 同一年同一报告期，保留最新日期的数据
                    existing_key = all_data.get(f"_latest_{col_year}_{period}", "")
                    if key not in all_data or date_str > existing_key:
                        all_data[key] = values
                        all_data[f"_latest_{col_year}_{period}"] = date_str

        # 清理辅助键
        return {k: v for k, v in all_data.items() if isinstance(k, tuple)}


    @app.route("/api/update-balance-sheet", methods=["POST"])
    def api_update_balance_sheet():
        """从新浪财经拉取资产负债表数据并存入 balance_sheets 表"""
        payload = request.get_json(silent=True) if request.is_json else {}
        mode = "full"
        if request.is_json:
            mode = payload.get("mode", "full")
        if request.args.get("mode"):
            mode = request.args["mode"]
        payload = {**payload, "mode": mode}

        try:
            stocks = _get_update_stocks(payload)
            if len(stocks) > 1 or (payload.get("background") and stocks):
                return jsonify(start_endpoint_stock_batch(
                    app,
                    get_connection,
                    execute_query,
                    "update_balance_sheet",
                    "资产负债表更新",
                    payload,
                    stocks,
                    api_update_balance_sheet,
                    "/api/update-balance-sheet",
                    on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("balance-sheet-update"),
                ))
            updated_count = 0
            errors = []

            for s in stocks:
                code = s["code"]
                try:
                    url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_BalanceSheet/stockid/{code}/ctrl/part/displaytype/0.phtml"
                    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    resp.encoding = "gbk"

                    # 增量模式：查询已有 (year, period) 组合
                    existing_keys = set()
                    if mode == "incremental":
                        existing = execute_query(
                            "SELECT fiscal_year, report_period FROM balance_sheets WHERE stock_code=%s", (code,)
                        )
                        existing_keys = {(r["fiscal_year"], r["report_period"]) for r in existing}

                    # 解析所有季度数据
                    all_data = _parse_sina_bs(resp.text)

                    for (year, period), values in sorted(all_data.items()):
                        if mode == "incremental" and (year, period) in existing_keys:
                            continue

                        columns = BS_COLUMNS
                        placeholders = ", ".join(["%s"] * len(columns))
                        col_names = ", ".join(columns)
                        update_clause = ", ".join([f"{c}=VALUES({c})" for c in columns])

                        sql = (
                            f"INSERT INTO balance_sheets (stock_code, fiscal_year, report_period, {col_names}) "
                            f"VALUES (%s, %s, %s, {placeholders}) "
                            f"ON DUPLICATE KEY UPDATE {update_clause}"
                        )
                        params = [code, year, period] + [values.get(c) for c in columns]
                        execute_query(sql, tuple(params), fetch=False)
                        updated_count += 1

                except Exception as e:
                    errors.append(f"{code}: {str(e)}")

                time.sleep(0.3)

            return jsonify({
                "success": True,
                "stocks_processed": len(stocks),
                "records_updated": updated_count,
                "mode": mode,
                "errors": errors[:5] if errors else [],
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


    @app.route("/api/stock/<code>/balance-sheet")
    def api_stock_balance_sheet(code):
        """查询指定股票的资产负债表数据。
        Query params:
          from_year, to_year: 年份范围
          period: FY(年报,默认) / Q1 / Q2 / Q3 / all(全部)
          view: cumulative(累计/快照,默认) / single(单季度)
        """
        from_year = request.args.get("from_year", 2000, type=int)
        to_year = request.args.get("to_year", 2030, type=int)
        period = request.args.get("period", "FY")
        view = request.args.get("view", "cumulative")

        need_single = (view == "single" and period != "FY")
        # 单季度模式下查全部报告期（用于计算差值），否则只查指定报告期
        query_period = None if need_single else (None if period == "all" else period)

        if query_period:
            where_period = "AND report_period = %s"
            params = [code, query_period, from_year, to_year]
        else:
            where_period = ""
            params = [code, from_year, to_year]

        rows = execute_query(
            f"""SELECT * FROM balance_sheets
               WHERE stock_code = %s {where_period}
               AND fiscal_year BETWEEN %s AND %s
               ORDER BY fiscal_year DESC, FIELD(report_period, 'FY','Q3','Q2','Q1') DESC""",
            tuple(params)
        )

        data_by_key = {}
        for r in rows:
            fy, rp = r["fiscal_year"], r["report_period"]
            item = {"fiscal_year": fy, "report_period": rp}
            for col in BS_COLUMNS:
                val = r.get(col)
                item[col] = float(val) if val is not None else None
            data_by_key[(fy, rp)] = item

        if need_single:
            periods_order = ["Q1", "Q2", "Q3", "FY"]
            prev_map = {"Q1": None, "Q2": "Q1", "Q3": "Q2", "FY": "Q3"}
            result = []
            for (fy, rp), item in sorted(data_by_key.items(), key=lambda x: (-x[0][0], periods_order.index(x[0][1]))):
                single = {"fiscal_year": fy, "report_period": rp}
                prev_key = (fy, prev_map[rp]) if prev_map[rp] else None
                prev_item = data_by_key.get(prev_key) if prev_key else None
                for col in BS_COLUMNS:
                    cur = item.get(col)
                    if cur is None:
                        single[col] = None
                    elif prev_item is None or prev_item.get(col) is None:
                        single[col] = cur if rp == "Q1" else None
                    else:
                        single[col] = round(cur - prev_item[col], 4)
                result.append(single)
            # 过滤到请求的报告期
            if period != "all":
                result = [r for r in result if r["report_period"] == period]
        else:
            result = sorted(data_by_key.values(), key=lambda x: (x["fiscal_year"], {"FY": 0, "Q3": 1, "Q2": 2, "Q1": 3}[x["report_period"]]), reverse=True)

        return jsonify(result)


    # ==================== 估值分析 API ====================
