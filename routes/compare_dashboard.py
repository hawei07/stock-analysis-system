"""Stock comparison dashboard route."""

import re
from datetime import datetime

from flask import jsonify, request


def register_compare_dashboard_routes(app, deps):
    execute_query = deps["execute_query"]
    _enrich_stock_list_metrics = deps["enrich_stock_list_metrics"]
    _normalize_stock_code = deps["normalize_stock_code"]

    COMPARE_DEFAULT_METRICS = [
        "market.pe_ttm",
        "market.pb_ex_goodwill",
        "market.dividend_yield",
        "financial.roe",
        "financial.roic",
        "income.gross_margin",
        "financial.net_profit_rate",
        "financial.debt_ratio",
        "financial.revenue_yoy",
        "financial.profit_yoy",
        "financial.cashflow_to_profit",
        "financial.dividend_payout_ratio",
    ]

    COMPARE_METRICS = [
        {"key": "market.pe_ttm", "name": "PE(TTM)", "unit": "", "group": "行情估值"},
        {"key": "market.pb_ex_goodwill", "name": "PB(扣商誉)", "unit": "", "group": "行情估值"},
        {"key": "market.dividend_yield", "name": "股息率", "unit": "%", "group": "行情估值"},
        {"key": "financial.roe", "name": "ROE", "unit": "%", "group": "自定义财报"},
        {"key": "financial.deducted_roe", "name": "扣非ROE", "unit": "%", "group": "自定义财报"},
        {"key": "financial.roic", "name": "ROIC", "unit": "%", "group": "自定义财报"},
        {"key": "financial.total_revenue", "name": "营业总收入", "unit": "亿元", "group": "自定义财报", "flow": True},
        {"key": "financial.operate_profit", "name": "核心利润", "unit": "亿元", "group": "自定义财报", "flow": True},
        {"key": "financial.parent_profit", "name": "归母净利润", "unit": "亿元", "group": "自定义财报", "flow": True},
        {"key": "financial.deducted_profit", "name": "扣非净利润", "unit": "亿元", "group": "自定义财报", "flow": True},
        {"key": "financial.operate_cashflow", "name": "经营现金流净额", "unit": "亿元", "group": "自定义财报", "flow": True},
        {"key": "financial.net_profit_rate", "name": "净利率", "unit": "%", "group": "自定义财报"},
        {"key": "financial.cashflow_to_profit", "name": "现金流/净利润", "unit": "%", "group": "自定义财报"},
        {"key": "financial.revenue_yoy", "name": "营收同比", "unit": "%", "group": "自定义财报"},
        {"key": "financial.profit_yoy", "name": "净利润同比", "unit": "%", "group": "自定义财报"},
        {"key": "financial.debt_ratio", "name": "资产负债率", "unit": "%", "group": "自定义财报"},
        {"key": "financial.interest_bearing_debt_ratio", "name": "有息负债率", "unit": "%", "group": "自定义财报"},
        {"key": "financial.basic_eps", "name": "基本EPS", "unit": "元", "group": "自定义财报"},
        {"key": "financial.total_assets", "name": "总资产", "unit": "亿元", "group": "自定义财报"},
        {"key": "financial.total_equity", "name": "归母权益", "unit": "亿元", "group": "自定义财报"},
        {"key": "financial.dividend_payout_ratio", "name": "分红率", "unit": "%", "group": "自定义财报"},
        {"key": "income.gross_margin", "name": "毛利率", "unit": "%", "group": "利润表"},
        {"key": "income.operating_revenue", "name": "营业收入", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.cost_of_revenue", "name": "营业成本", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.selling_expense", "name": "销售费用", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.admin_expense", "name": "管理费用", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.rd_expense", "name": "研发费用", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.finance_expense", "name": "财务费用", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.operating_profit", "name": "营业利润", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "income.parent_net_profit", "name": "归母净利润(利润表)", "unit": "亿元", "group": "利润表", "flow": True},
        {"key": "balance.total_assets", "name": "总资产(资产负债表)", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.total_liabilities", "name": "负债合计", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.parent_equity", "name": "归母权益(资产负债表)", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.accounts_receivable", "name": "应收账款", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.inventory", "name": "存货", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.goodwill", "name": "商誉", "unit": "亿元", "group": "资产负债表"},
        {"key": "balance.goodwill_to_equity", "name": "商誉/归母权益", "unit": "%", "group": "资产负债表"},
        {"key": "cashflow.cf_oper_net", "name": "经营现金流净额(现金流量表)", "unit": "亿元", "group": "现金流量表", "flow": True},
        {"key": "cashflow.cf_sales_goods", "name": "销售商品收到现金", "unit": "亿元", "group": "现金流量表", "flow": True},
        {"key": "cashflow.cf_buy_assets", "name": "购建固定资产等支付现金", "unit": "亿元", "group": "现金流量表", "flow": True},
        {"key": "cashflow.free_cashflow", "name": "自由现金流", "unit": "亿元", "group": "现金流量表", "flow": True},
        {"key": "cashflow.cf_finance_net", "name": "筹资现金流净额", "unit": "亿元", "group": "现金流量表", "flow": True},
    ]


    @app.route("/api/stock/<code>/compare-dashboard")
    def api_stock_compare_dashboard(code):
        def to_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def pct(cur, base):
            if cur is None or base in (None, 0):
                return None
            return round(cur / base * 100, 4)

        def pct_change(cur, prev):
            if cur is None or prev in (None, 0):
                return None
            return round((cur - prev) / abs(prev) * 100, 4)

        def parse_codes():
            raw = request.args.get("codes", "")
            result = []
            for c in [code] + raw.split(","):
                c = _normalize_stock_code(str(c).strip())
                if re.match(r"^\d{5,6}$", c) and c not in result:
                    result.append(c)
                if len(result) >= 3:
                    break
            return result

        def row_to_float_dict(row):
            if not row:
                return None
            return {k: to_float(v) if k not in ("stock_code", "report_period", "fiscal_year") else v for k, v in row.items()}

        def period_rank(period):
            return {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(period, 4)

        def period_row(source_map, stock_code, fiscal_year, report_period, single_view, flow_fields):
            cur = row_to_float_dict(source_map.get((stock_code, fiscal_year, report_period)))
            if not cur:
                return None
            if not single_view or report_period == "Q1":
                return cur
            prev_period = {"Q2": "Q1", "Q3": "Q2", "FY": "Q3"}.get(report_period)
            prev = row_to_float_dict(source_map.get((stock_code, fiscal_year, prev_period))) if prev_period else None
            if not prev:
                return cur
            result = dict(cur)
            for field in flow_fields:
                if cur.get(field) is not None and prev.get(field) is not None:
                    result[field] = round(cur[field] - prev[field], 4)
            return result

        metric_defs = {m["key"]: m for m in COMPARE_METRICS}
        codes = parse_codes()
        requested_year = request.args.get("year", type=int)
        year = requested_year
        period = request.args.get("period", "FY")
        if period not in ("FY", "Q1", "Q2", "Q3"):
            period = "FY"
        requested_period = period

        if not year:
            latest = execute_query(
                """SELECT fiscal_year, report_period
                   FROM custom_financials
                   WHERE stock_code=%s
                   ORDER BY fiscal_year DESC, FIELD(report_period,'Q1','Q2','Q3','FY') DESC
                   LIMIT 1""",
                (code,),
            )
            if latest:
                year = int(latest[0]["fiscal_year"])
                period = latest[0].get("report_period") or "FY"
            else:
                year = datetime.now().year
        else:
            available_period_rows = execute_query(
                """SELECT report_period
                   FROM custom_financials
                   WHERE stock_code=%s AND fiscal_year=%s
                   ORDER BY FIELD(report_period,'Q1','Q2','Q3','FY') DESC""",
                (code, year),
            )
            available_periods_for_year = [r.get("report_period") or "FY" for r in available_period_rows]
            if available_periods_for_year and period not in available_periods_for_year:
                period = available_periods_for_year[0]

        period_fallback_note = None
        if period != requested_period:
            period_fallback_note = f"{year} {requested_period} 暂无数据，已切换到 {period}"
        view = request.args.get("view", "cumulative")
        single_view = view == "single" and period not in ("FY", "Q1")

        requested_metrics = [
            m.strip() for m in request.args.get("metrics", "").split(",")
            if m.strip() in metric_defs
        ]
        metric_keys = requested_metrics or COMPARE_DEFAULT_METRICS

        placeholders = ",".join(["%s"] * len(codes))
        stocks = execute_query(
            f"SELECT code, name, market, industry, pe_ttm, dividend_yield FROM stocks WHERE code IN ({placeholders})",
            tuple(codes),
        )
        stocks_by_code = {s["code"]: dict(s) for s in stocks}
        ordered_stocks = [stocks_by_code[c] for c in codes if c in stocks_by_code]
        ordered_stocks = _enrich_stock_list_metrics(ordered_stocks, include_ytd=False)
        market_by_code = {s["code"]: s for s in ordered_stocks}

        year_params = tuple(codes + [year, year - 1])
        two_years = "(%s,%s)"
        financial_rows = execute_query(
            f"""SELECT cf.*, d.dividend_amount, d.dividend_per_share
                FROM custom_financials cf
                LEFT JOIN dividends d ON cf.stock_code=d.stock_code AND cf.fiscal_year=d.fiscal_year
                WHERE cf.stock_code IN ({placeholders}) AND cf.fiscal_year IN {two_years}""",
            year_params,
        )
        income_rows = execute_query(
            f"SELECT * FROM income_statements WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
            year_params,
        )
        balance_rows = execute_query(
            f"SELECT * FROM balance_sheets WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
            year_params,
        )
        cash_rows = execute_query(
            f"SELECT * FROM cash_flows WHERE stock_code IN ({placeholders}) AND fiscal_year IN {two_years}",
            year_params,
        )

        def make_map(rows):
            return {(r["stock_code"], int(r["fiscal_year"]), r.get("report_period", "FY")): r for r in rows}

        financial_map = make_map(financial_rows)
        income_map = make_map(income_rows)
        balance_map = make_map(balance_rows)
        cash_map = make_map(cash_rows)
        financial_flow = ["total_revenue", "operate_profit", "parent_profit", "deducted_profit", "operate_cashflow", "dividend_amount"]
        income_flow = ["total_revenue", "operating_revenue", "operating_cost", "cost_of_revenue", "tax_surcharge", "selling_expense", "admin_expense", "finance_expense", "rd_expense", "fair_value_change", "invest_income", "operating_profit", "nonop_income", "nonop_expense", "total_profit", "income_tax", "net_profit", "parent_net_profit"]
        cash_flow = ["cf_sales_goods", "cf_tax_refund", "cf_other_oper_in", "cf_oper_inflow", "cf_buy_goods", "cf_payroll", "cf_tax_pay", "cf_other_oper_out", "cf_oper_outflow", "cf_oper_net", "cf_invest_withdraw", "cf_invest_income", "cf_dispose_assets", "cf_other_invest_in", "cf_invest_inflow", "cf_buy_assets", "cf_invest_pay", "cf_other_invest_out", "cf_invest_outflow", "cf_invest_net", "cf_finance_in", "cf_borrow", "cf_bond", "cf_other_finance_in", "cf_finance_inflow", "cf_repay_debt", "cf_dividend_interest", "cf_other_finance_out", "cf_finance_outflow", "cf_finance_net"]

        def context_for(stock_code, fiscal_year):
            fin = period_row(financial_map, stock_code, fiscal_year, period, single_view, financial_flow)
            inc = period_row(income_map, stock_code, fiscal_year, period, single_view, income_flow)
            bal = period_row(balance_map, stock_code, fiscal_year, period, False, [])
            cf = period_row(cash_map, stock_code, fiscal_year, period, single_view, cash_flow)
            return {"market": market_by_code.get(stock_code, {}), "financial": fin or {}, "income": inc or {}, "balance": bal or {}, "cashflow": cf or {}}

        contexts = {s["code"]: context_for(s["code"], year) for s in ordered_stocks}
        prev_contexts = {s["code"]: context_for(s["code"], year - 1) for s in ordered_stocks}

        def metric_value(key, ctx, prev_ctx):
            source, field = key.split(".", 1)
            if source == "market":
                return to_float(ctx["market"].get(field))
            if key == "financial.net_profit_rate":
                return pct(to_float(ctx["financial"].get("parent_profit")), to_float(ctx["financial"].get("total_revenue")))
            if key == "financial.cashflow_to_profit":
                return pct(to_float(ctx["financial"].get("operate_cashflow")), to_float(ctx["financial"].get("parent_profit")))
            if key == "financial.revenue_yoy":
                return pct_change(to_float(ctx["financial"].get("total_revenue")), to_float(prev_ctx["financial"].get("total_revenue")))
            if key == "financial.profit_yoy":
                return pct_change(to_float(ctx["financial"].get("parent_profit")), to_float(prev_ctx["financial"].get("parent_profit")))
            if key == "financial.dividend_payout_ratio":
                return pct(to_float(ctx["financial"].get("dividend_amount")), to_float(ctx["financial"].get("parent_profit")))
            if key == "income.gross_margin":
                revenue = to_float(ctx["income"].get("operating_revenue")) or to_float(ctx["income"].get("total_revenue"))
                cost = to_float(ctx["income"].get("cost_of_revenue"))
                if cost is None:
                    cost = to_float(ctx["income"].get("operating_cost"))
                return pct(revenue - cost, revenue) if revenue is not None and cost is not None else None
            if key == "balance.goodwill_to_equity":
                return pct(to_float(ctx["balance"].get("goodwill")), to_float(ctx["balance"].get("parent_equity")))
            if key == "cashflow.free_cashflow":
                oper = to_float(ctx["cashflow"].get("cf_oper_net"))
                capex = to_float(ctx["cashflow"].get("cf_buy_assets"))
                return round(oper - capex, 4) if oper is not None and capex is not None else None
            return to_float(ctx[source].get(field))

        rows = []
        for key in metric_keys:
            meta = metric_defs[key]
            values = []
            for stock in ordered_stocks:
                stock_code = stock["code"]
                value = metric_value(key, contexts[stock_code], prev_contexts[stock_code])
                values.append({"code": stock_code, "value": round(value, 4) if value is not None else None})
            rows.append({
                "key": key,
                "name": meta["name"],
                "unit": meta.get("unit", ""),
                "group": meta.get("group", ""),
                "values": values,
            })

        available_years = execute_query(
            "SELECT DISTINCT fiscal_year FROM custom_financials WHERE stock_code=%s ORDER BY fiscal_year DESC",
            (code,),
        )

        return jsonify({
            "stocks": [
                {"code": s["code"], "name": s["name"], "market": s.get("market"), "industry": s.get("industry")}
                for s in ordered_stocks
            ],
            "year": year,
            "period": period,
            "view": "single" if single_view else "cumulative",
            "period_fallback_note": period_fallback_note,
            "available_years": [int(r["fiscal_year"]) for r in available_years],
            "default_metrics": COMPARE_DEFAULT_METRICS,
            "metric_options": COMPARE_METRICS,
            "rows": rows,
        })

