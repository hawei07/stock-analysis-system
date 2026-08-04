"""Income statement and cash flow routes."""

import re
import time

from flask import jsonify, request

from services.background_jobs import start_endpoint_stock_batch
from services.providers.eastmoney import finance_report
from services.providers.sina import finance_statement_html


def register_statement_routes(app, deps):
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _schedule_auto_cloud_backup = deps.get("schedule_auto_cloud_backup")
    _get_update_stocks = deps["get_update_stocks"]

    INCOME_ROW_MAP = [
        ("营业总收入", "total_revenue"),
        ("营业收入", "operating_revenue"),
        ("营业总成本", "operating_cost"),
        ("营业成本", "cost_of_revenue"),
        ("营业税金及附加", "tax_surcharge"),
        ("利息支出", "interest_expense"),
        ("手续费及佣金支出", "fee_commission_expense"),
        ("销售费用", "selling_expense"),
        ("管理费用", "admin_expense"),
        ("财务费用", "finance_expense"),
        ("利息费用", "finance_interest_expense"),
        ("其中：利息收入", "finance_interest_income"),
        ("研发费用", "rd_expense"),
        ("利息收入", "interest_income"),
        ("公允价值变动收益", "fair_value_change"),
        ("信用减值损失", "credit_impairment_loss"),
        ("资产减值损失", "asset_impairment_loss"),
        ("资产处置收益", "asset_disposal_income"),
        ("其他收益", "other_income"),
        ("投资收益", "invest_income"),
        ("营业利润", "operating_profit"),
        ("营业外收入", "nonop_income"),          # 匹配"加:营业外收入"
        ("减：营业外支出", "nonop_expense"),
        ("利润总额", "total_profit"),
        ("所得税费用", "income_tax"),
        ("净利润", "net_profit"),
        ("归属于母公司所有者的净利润", "parent_net_profit"),
        ("少数股东损益", "minority_profit"),
        ("基本每股收益", "basic_eps"),
        ("稀释每股收益", "diluted_eps"),
        ("其他综合收益", "other_comprehensive"),
        ("综合收益总额", "total_comprehensive"),
        ("归属于母公司所有者的综合收益总额", "parent_comprehensive"),
    ]
    INCOME_COLUMNS = [c for _, c in INCOME_ROW_MAP]
    INCOME_SUPPLEMENT_COLUMNS = [
        "interest_income",
        "finance_interest_expense",
        "finance_interest_income",
        "interest_expense",
        "fee_commission_expense",
        "credit_impairment_loss",
        "asset_impairment_loss",
        "asset_disposal_income",
        "other_income",
    ]

    EASTMONEY_INCOME_FIELD_MAP = {
        "TOTAL_OPERATE_INCOME": ("total_revenue", True),
        "OPERATE_INCOME": ("operating_revenue", True),
        "TOTAL_OPERATE_COST": ("operating_cost", True),
        "OPERATE_COST": ("cost_of_revenue", True),
        "INTEREST_EXPENSE": ("interest_expense", True),
        "FEE_COMMISSION_EXPENSE": ("fee_commission_expense", True),
        "OPERATE_TAX_ADD": ("tax_surcharge", True),
        "SALE_EXPENSE": ("selling_expense", True),
        "MANAGE_EXPENSE": ("admin_expense", True),
        "FINANCE_EXPENSE": ("finance_expense", True),
        "FE_INTEREST_EXPENSE": ("finance_interest_expense", True),
        "FE_INTEREST_INCOME": ("finance_interest_income", True),
        "RESEARCH_EXPENSE": ("rd_expense", True),
        "INTEREST_INCOME": ("interest_income", True),
        "FAIRVALUE_CHANGE_INCOME": ("fair_value_change", True),
        "CREDIT_IMPAIRMENT_LOSS": ("credit_impairment_loss", True),
        "ASSET_IMPAIRMENT_LOSS": ("asset_impairment_loss", True),
        "ASSET_DISPOSAL_INCOME": ("asset_disposal_income", True),
        "OTHER_INCOME": ("other_income", True),
        "INVEST_INCOME": ("invest_income", True),
        "OPERATE_PROFIT": ("operating_profit", True),
        "NONBUSINESS_INCOME": ("nonop_income", True),
        "NONBUSINESS_EXPENSE": ("nonop_expense", True),
        "TOTAL_PROFIT": ("total_profit", True),
        "INCOME_TAX": ("income_tax", True),
        "NETPROFIT": ("net_profit", True),
        "PARENT_NETPROFIT": ("parent_net_profit", True),
        "MINORITY_INTEREST": ("minority_profit", True),
        "BASIC_EPS": ("basic_eps", False),
        "DILUTED_EPS": ("diluted_eps", False),
        "OTHER_COMPRE_INCOME": ("other_comprehensive", True),
        "TOTAL_COMPRE_INCOME": ("total_comprehensive", True),
        "PARENT_TCI": ("parent_comprehensive", True),
    }

    # 现金流量表行映射
    CASHFLOW_ROW_MAP = [
        ("销售商品、提供劳务收到的现金", "cf_sales_goods"),
        ("收到的税费返还", "cf_tax_refund"),
        ("收到的其他与经营活动有关的现金", "cf_other_oper_in"),
        ("经营活动现金流入小计", "cf_oper_inflow"),
        ("购买商品、接受劳务支付的现金", "cf_buy_goods"),
        ("支付给职工以及为职工支付的现金", "cf_payroll"),
        ("支付的各项税费", "cf_tax_pay"),
        ("支付的其他与经营活动有关的现金", "cf_other_oper_out"),
        ("经营活动现金流出小计", "cf_oper_outflow"),
        ("经营活动产生的现金流量净额", "cf_oper_net"),
        ("收回投资所收到的现金", "cf_invest_withdraw"),
        ("取得投资收益所收到的现金", "cf_invest_income"),
        ("处置固定资产、无形资产和其他长期资产所收回的现金净额", "cf_dispose_assets"),
        ("收到的其他与投资活动有关的现金", "cf_other_invest_in"),
        ("投资活动现金流入小计", "cf_invest_inflow"),
        ("购建固定资产、无形资产和其他长期资产所支付的现金", "cf_buy_assets"),
        ("投资所支付的现金", "cf_invest_pay"),
        ("支付的其他与投资活动有关的现金", "cf_other_invest_out"),
        ("投资活动现金流出小计", "cf_invest_outflow"),
        ("投资活动产生的现金流量净额", "cf_invest_net"),
        ("吸收投资收到的现金", "cf_finance_in"),
        ("取得借款收到的现金", "cf_borrow"),
        ("发行债券收到的现金", "cf_bond"),
        ("收到其他与筹资活动有关的现金", "cf_other_finance_in"),
        ("筹资活动现金流入小计", "cf_finance_inflow"),
        ("偿还债务支付的现金", "cf_repay_debt"),
        ("分配股利、利润或偿付利息所支付的现金", "cf_dividend_interest"),
        ("支付其他与筹资活动有关的现金", "cf_other_finance_out"),
        ("筹资活动现金流出小计", "cf_finance_outflow"),
        ("筹资活动产生的现金流量净额", "cf_finance_net"),
    ]
    CASHFLOW_COLUMNS = [c for _, c in CASHFLOW_ROW_MAP]


    def _parse_sina_finance(html, row_map, target_year=None):
        """通用新浪财报HTML解析（资产负债表/利润表/现金流量表共用）。
        返回 {year: {col: val}} 或指定 target_year 时返回单年 dict。
        """
        import re as _re

        all_tables = _re.findall(r'<table[^>]*>(.*?)</table>', html, _re.DOTALL)
        all_year_data = {}

        for table_html in all_tables:
            if '报表日期' not in table_html:
                continue

            # 检查是否有匹配的行——取第一个非表头的行名来验证
            rows = _re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, _re.DOTALL)
            has_match = False
            for r in rows:
                cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if cells:
                    for pattern, _ in row_map:
                        if cells[0].startswith(pattern) or pattern in cells[0]:
                            has_match = True
                            break
                if has_match:
                    break
            if not has_match:
                continue

            # 找所有日期列
            date_cols = []
            for r in rows:
                cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                if any('报表日期' in c for c in cells):
                    for idx, c in enumerate(cells):
                        m = _re.match(r'(\d{4})-(\d{2})-(\d{2})', c)
                        if m:
                            date_cols.append((idx, int(m.group(1)), c))
                    break

            if not date_cols:
                continue

            for col_idx, col_year, col_date in date_cols:
                if target_year is not None and col_year != target_year:
                    continue

                # Map month to report_period: 12→FY, 09→Q3, 06→Q2, 03→Q1, else→FY
                m = _re.match(r'\d{4}-(\d{2})-\d{2}', col_date)
                month = int(m.group(1)) if m else 12
                rp_map = {12: 'FY', 9: 'Q3', 6: 'Q2', 3: 'Q1'}
                rp = rp_map.get(month, 'FY')
                composite_key = (col_year, rp)

                values = {}
                for r in rows:
                    cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                    cells = [_re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                    if not cells or len(cells) <= col_idx:
                        continue

                    row_name = cells[0]
                    raw_val = cells[col_idx]

                    for pattern, col in row_map:
                        if row_name.startswith(pattern) or pattern in row_name:
                            if raw_val and raw_val not in ("--", "", "None"):
                                try:
                                    values[col] = round(float(raw_val.replace(",", "")) / 10000, 4)
                                except ValueError:
                                    pass
                            break

                if values:
                    all_year_data[composite_key] = values

        if target_year is not None:
            return {k: v for k, v in all_year_data.items() if k[0] == target_year}
        return all_year_data


    def _parse_report_period(report_date):
        if not report_date:
            return None
        m = re.match(r"(\d{4})-(\d{2})-\d{2}", str(report_date))
        if not m:
            return None
        year = int(m.group(1))
        month = int(m.group(2))
        return year, {12: "FY", 9: "Q3", 6: "Q2", 3: "Q1"}.get(month, "FY")


    def _fetch_eastmoney_income(stock_code):
        data = finance_report(
            "RPT_F10_FINANCE_GINCOME",
            params={
                "filter": f'(SECURITY_CODE="{stock_code}")',
                "pageNumber": 1,
                "pageSize": 500,
                "sortColumns": "REPORT_DATE",
                "sortTypes": -1,
            },
            timeout=15,
        )
        rows = (data.get("result") or {}).get("data") or []
        result = {}
        for row in rows:
            key = _parse_report_period(row.get("REPORT_DATE"))
            if not key:
                continue
            values = result.setdefault(key, {})
            for source_field, (target_col, is_amount) in EASTMONEY_INCOME_FIELD_MAP.items():
                raw = row.get(source_field)
                if raw in (None, "", "--"):
                    continue
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                if is_amount:
                    value = value / 100000000
                values[target_col] = round(value, 4)
        return {k: v for k, v in result.items() if v}


    def _merge_income_sources(primary, supplement):
        for key, values in supplement.items():
            merged = primary.setdefault(key, {})
            for col, value in values.items():
                if value is not None:
                    merged[col] = value
        return primary


    def _upsert_finance(stock_code, all_years, columns, table):
        """通用财报数据写入。all_years: {(year, report_period): {col: val}}"""
        for (year, rp), values in sorted(all_years.items()):
            placeholders = ", ".join(["%s"] * len(columns))
            col_names = ", ".join(columns)
            update_clause = ", ".join([f"{c}=VALUES({c})" for c in columns])

            sql = (
                f"INSERT INTO {table} (stock_code, fiscal_year, report_period, {col_names}) "
                f"VALUES (%s, %s, %s, {placeholders}) "
                f"ON DUPLICATE KEY UPDATE {update_clause}"
            )
            params = [stock_code, year, rp] + [values.get(c) for c in columns]
            execute_query(sql, tuple(params), fetch=False)


    # ── 利润表 API ──

    # ==================== 营收构成 API ====================


    @app.route("/api/stock/<code>/income")
    def api_stock_income(code):
        period = request.args.get("period", "FY")
        view = request.args.get("view", "cumulative")
        from_year = request.args.get("from_year", 2000, type=int)
        to_year = request.args.get("to_year", 2030, type=int)

        where_period = "AND report_period = %s"
        if period == "all":
            where_period = ""
        elif period != "FY":
            where_period = "AND report_period = %s"

        rows = execute_query(
            f"""SELECT * FROM income_statements
               WHERE stock_code=%s AND fiscal_year BETWEEN %s AND %s {where_period}
               ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC""",
            (code, from_year, to_year, period) if where_period else (code, from_year, to_year)
        )
        result = []
        for r in rows:
            item = {"fiscal_year": r["fiscal_year"], "report_period": r["report_period"]}
            for col in INCOME_COLUMNS:
                item[col] = float(r[col]) if r.get(col) is not None else None
            result.append(item)
        return jsonify(result)


    @app.route("/api/update-income", methods=["POST"])
    def api_update_income():
        payload = request.get_json(silent=True) if request.is_json else {}
        mode = payload.get("mode", "full") if request.is_json else "full"
        if request.args.get("mode"):
            mode = request.args["mode"]
        payload = {**payload, "mode": mode}

        stocks = _get_update_stocks(payload)
        if len(stocks) > 1 or (payload.get("background") and stocks):
            return jsonify(start_endpoint_stock_batch(
                app,
                get_connection,
                execute_query,
                "update_income",
                "利润表更新",
                payload,
                stocks,
                api_update_income,
                "/api/update-income",
                on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("income-update"),
            ))
        updated = 0
        errors = []

        for s in stocks:
            code = s["code"]
            try:
                html = finance_statement_html(code, "vFD_ProfitStatement", timeout=15)
                all_years = _parse_sina_finance(html, INCOME_ROW_MAP)
                eastmoney_years = _fetch_eastmoney_income(code)
                all_years = _merge_income_sources(all_years, eastmoney_years)

                existing = set()
                if mode == "incremental":
                    for r in execute_query("SELECT fiscal_year, report_period FROM income_statements WHERE stock_code=%s", (code,)):
                        existing.add((r["fiscal_year"], r["report_period"]))

                for (year, rp), values in sorted(all_years.items()):
                    has_new_supplement = any(values.get(c) is not None for c in INCOME_SUPPLEMENT_COLUMNS)
                    if mode == "incremental" and (year, rp) in existing and not has_new_supplement:
                        continue
                    _upsert_finance(code, {(year, rp): values}, INCOME_COLUMNS, "income_statements")
                    updated += 1
            except Exception as e:
                errors.append(f"{code}: {str(e)}")
            time.sleep(0.3)

        return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})


    # ── 现金流量表 API ──

    @app.route("/api/stock/<code>/cashflow")
    def api_stock_cashflow(code):
        period = request.args.get("period", "FY")
        view = request.args.get("view", "cumulative")
        from_year = request.args.get("from_year", 2000, type=int)
        to_year = request.args.get("to_year", 2030, type=int)

        where_period = "AND report_period = %s"
        if period == "all":
            where_period = ""
        elif period != "FY":
            where_period = "AND report_period = %s"

        rows = execute_query(
            f"""SELECT * FROM cash_flows
               WHERE stock_code=%s AND fiscal_year BETWEEN %s AND %s {where_period}
               ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC""",
            (code, from_year, to_year, period) if where_period else (code, from_year, to_year)
        )
        result = []
        for r in rows:
            item = {"fiscal_year": r["fiscal_year"], "report_period": r["report_period"]}
            for col in CASHFLOW_COLUMNS:
                item[col] = float(r[col]) if r.get(col) is not None else None
            result.append(item)
        return jsonify(result)


    @app.route("/api/update-cashflow", methods=["POST"])
    def api_update_cashflow():
        payload = request.get_json(silent=True) if request.is_json else {}
        mode = payload.get("mode", "full") if request.is_json else "full"
        if request.args.get("mode"):
            mode = request.args["mode"]
        payload = {**payload, "mode": mode}

        stocks = _get_update_stocks(payload)
        if len(stocks) > 1 or (payload.get("background") and stocks):
            return jsonify(start_endpoint_stock_batch(
                app,
                get_connection,
                execute_query,
                "update_cashflow",
                "现金流量表更新",
                payload,
                stocks,
                api_update_cashflow,
                "/api/update-cashflow",
                on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("cashflow-update"),
            ))
        updated = 0
        errors = []

        for s in stocks:
            code = s["code"]
            try:
                html = finance_statement_html(code, "vFD_CashFlow", timeout=15)
                all_years = _parse_sina_finance(html, CASHFLOW_ROW_MAP)

                existing = set()
                if mode == "incremental":
                    for r in execute_query("SELECT fiscal_year, report_period FROM cash_flows WHERE stock_code=%s", (code,)):
                        existing.add((r["fiscal_year"], r["report_period"]))

                for (year, rp), values in sorted(all_years.items()):
                    if mode == "incremental" and (year, rp) in existing:
                        continue
                    _upsert_finance(code, {(year, rp): values}, CASHFLOW_COLUMNS, "cash_flows")
                    updated += 1
            except Exception as e:
                errors.append(f"{code}: {str(e)}")
            time.sleep(0.3)

        return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})
