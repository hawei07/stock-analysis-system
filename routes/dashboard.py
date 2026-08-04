"""Dashboard and comparison routes for stock detail pages."""

from flask import jsonify, request

from services.financial_metrics import (
    avg as financial_avg,
    cagr as financial_cagr,
    enrich_financial_summary_item,
    pct_change,
    round_or_none as financial_round_or_none,
    to_float,
)
from services.financial_periods import (
    annual_report_rows,
    cagr_start_row,
    filter_usable_report_rows,
    latest_report_row,
    period_label,
    same_period_last_year,
)


def register_dashboard_routes(app, deps):
    execute_query = deps["execute_query"]
    _enrich_stock_list_metrics = deps["enrich_stock_list_metrics"]
    _normalize_stock_code = deps["normalize_stock_code"]

    @app.route("/api/stock/<code>/fundamental-dashboard")
    def api_stock_fundamental_dashboard(code):
        """股票详情页基本面驾驶舱。"""

        def round_or_none(value, ndigits=2):
            return financial_round_or_none(value, ndigits)

        def clamp_score(score):
            return max(0, min(100, round(score)))

        def status_from_score(score):
            if score is None:
                return {"text": "数据不足", "level": "neutral"}
            if score >= 80:
                return {"text": "优秀", "level": "good"}
            if score >= 65:
                return {"text": "良好", "level": "good"}
            if score >= 45:
                return {"text": "一般", "level": "warn"}
            return {"text": "偏弱", "level": "bad"}

        def score_high(value, excellent, good, ok):
            if value is None:
                return 0
            if value >= excellent:
                return 100
            if value >= good:
                return 75
            if value >= ok:
                return 50
            if value >= 0:
                return 25
            return 0

        def score_low(value, excellent, good, ok):
            if value is None:
                return 0
            if value <= excellent:
                return 100
            if value <= good:
                return 75
            if value <= ok:
                return 50
            return 20

        def verdict_high(value, excellent, good, ok):
            if value is None:
                return "neutral"
            if value >= good:
                return "good"
            if value >= ok:
                return "warn"
            return "bad"

        def verdict_low(value, excellent, good, ok):
            if value is None:
                return "neutral"
            if value <= good:
                return "good"
            if value <= ok:
                return "warn"
            return "bad"

        def metric(name, value, unit="", verdict="neutral", note=""):
            return {
                "name": name,
                "value": round_or_none(value),
                "unit": unit,
                "verdict": verdict,
                "note": note,
            }

        try:
            stock_rows = execute_query(
                "SELECT code, name, market, industry, pe_ttm, dividend_yield FROM stocks WHERE code=%s",
                (code,),
            )
            if not stock_rows:
                return jsonify({"error": "未找到该股票"}), 404

            stock = dict(stock_rows[0])
            enriched = _enrich_stock_list_metrics([dict(stock)], include_ytd=False)
            market_metrics = enriched[0] if enriched else stock

            cagr_years = request.args.get("cagr_years", type=int)
            if cagr_years is not None and cagr_years <= 0:
                cagr_years = None

            rows = execute_query(
                """SELECT cf.fiscal_year, cf.report_period, cf.total_revenue, cf.operate_profit, cf.parent_profit, cf.deducted_profit,
                          cf.operate_cashflow, cf.roe, cf.deducted_roe, cf.roic, cf.total_assets, cf.total_equity,
                          cf.total_shares, cf.basic_eps, cf.debt_ratio, cf.interest_bearing_debt_ratio,
                          inc.total_revenue AS inc_total_revenue,
                          inc.operating_revenue AS inc_operating_revenue,
                          inc.cost_of_revenue AS inc_cost_of_revenue,
                          inc.interest_expense AS inc_interest_expense,
                          inc.fee_commission_expense AS inc_fee_commission_expense,
                          inc.selling_expense AS inc_selling_expense,
                          inc.admin_expense AS inc_admin_expense,
                          inc.finance_expense AS inc_finance_expense,
                          inc.rd_expense AS inc_rd_expense,
                          inc.finance_interest_income AS inc_finance_interest_income,
                          inc.tax_surcharge AS inc_tax_surcharge
                   FROM custom_financials cf
                   LEFT JOIN income_statements inc ON cf.stock_code = inc.stock_code
                        AND cf.fiscal_year = inc.fiscal_year AND cf.report_period = inc.report_period
                   WHERE cf.stock_code=%s
                   ORDER BY cf.fiscal_year ASC, FIELD(cf.report_period,'Q1','Q2','Q3','FY') ASC""",
                (code,),
            )

            if not rows:
                return jsonify({
                    "stock": {"code": stock["code"], "name": stock["name"], "industry": stock.get("industry")},
                    "summary": [],
                    "groups": [],
                    "signals": [],
                    "message": "暂无年报财务数据，请先更新财报数据。",
                })

            data = []
            for r in rows:
                item = {"fiscal_year": int(r["fiscal_year"]), "report_period": r.get("report_period") or "FY"}
                for key in [
                    "total_revenue", "operate_profit", "parent_profit", "deducted_profit",
                    "operate_cashflow", "roe", "deducted_roe", "roic", "total_assets",
                    "total_equity", "total_shares", "basic_eps", "debt_ratio",
                    "interest_bearing_debt_ratio",
                ]:
                    item[key] = to_float(r.get(key))
                data.append(enrich_financial_summary_item(item, r))

            usable_data = filter_usable_report_rows(data)
            latest_period_data = latest_report_row(usable_data)
            yoy_base = same_period_last_year(usable_data, latest_period_data)

            annual_data = annual_report_rows(usable_data)
            if not annual_data:
                return jsonify({
                    "stock": {"code": stock["code"], "name": stock["name"], "industry": stock.get("industry")},
                    "summary": [],
                    "groups": [],
                    "signals": [],
                    "message": "暂无年报财务数据，请先更新财报数据。",
                })

            latest = annual_data[-1]
            recent = annual_data[-5:]
            all_earliest = annual_data[0]
            cagr_earliest = cagr_start_row(annual_data, latest, cagr_years)
            year_span = latest["fiscal_year"] - cagr_earliest["fiscal_year"]

            revenue_cagr = financial_cagr(cagr_earliest["total_revenue"], latest["total_revenue"], year_span)
            profit_cagr = financial_cagr(cagr_earliest["parent_profit"], latest["parent_profit"], year_span)
            revenue_yoy = pct_change(
                latest_period_data["total_revenue"],
                yoy_base["total_revenue"] if yoy_base else None,
            )
            profit_yoy = pct_change(
                latest_period_data["parent_profit"],
                yoy_base["parent_profit"] if yoy_base else None,
            )
            latest_period_note = period_label(latest_period_data["fiscal_year"], latest_period_data.get("report_period"))
            yoy_base_note = period_label(yoy_base["fiscal_year"], yoy_base.get("report_period")) if yoy_base else "缺少去年同周期"
            yoy_note = f"{latest_period_note} vs {yoy_base_note}"
            cagr_note = f"{cagr_earliest['fiscal_year']}-{latest['fiscal_year']}"
            cagr_scope_text = f"近{cagr_years}年" if cagr_years else "上市以来"
            roe_avg_5y = financial_avg([r["roe"] for r in recent])
            roic_avg_5y = financial_avg([r["roic"] for r in recent])
            cf_profit_avg_5y = financial_avg([r["cashflow_to_profit"] for r in recent])
            positive_profit_years = sum(1 for r in recent if (r["parent_profit"] or 0) > 0)
            positive_ocf_years = sum(1 for r in recent if (r["operate_cashflow"] or 0) > 0)

            balance = execute_query(
                """SELECT parent_equity, goodwill
                   FROM balance_sheets
                   WHERE stock_code=%s AND parent_equity IS NOT NULL
                   ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC
                   LIMIT 1""",
                (code,),
            )
            parent_equity = to_float(balance[0]["parent_equity"]) if balance else latest.get("total_equity")
            goodwill = to_float(balance[0]["goodwill"]) if balance and balance[0].get("goodwill") is not None else 0
            goodwill_to_equity = goodwill / parent_equity * 100 if parent_equity and parent_equity > 0 else None

            pe_ttm = to_float(market_metrics.get("pe_ttm"))
            dividend_yield = to_float(market_metrics.get("dividend_yield"))
            pb_ex_goodwill = to_float(market_metrics.get("pb_ex_goodwill"))
            reasonable_discount = to_float(market_metrics.get("reasonable_discount"))
            price = to_float(market_metrics.get("price"))
            reasonable_price = to_float(market_metrics.get("reasonable_price"))

            quality_score = clamp_score(
                score_high(roe_avg_5y, 20, 15, 8) * 0.38
                + score_high(roic_avg_5y, 15, 10, 6) * 0.28
                + score_high(latest.get("net_profit_rate"), 20, 10, 4) * 0.18
                + (positive_profit_years / max(1, len(recent)) * 100) * 0.16
            )
            growth_score = clamp_score(
                score_high(revenue_cagr, 15, 8, 0) * 0.32
                + score_high(profit_cagr, 15, 8, 0) * 0.42
                + score_high(revenue_yoy, 12, 5, 0) * 0.13
                + score_high(profit_yoy, 12, 5, 0) * 0.13
            )
            cashflow_score = clamp_score(
                score_high(cf_profit_avg_5y, 120, 90, 60) * 0.55
                + score_high(latest.get("cashflow_to_profit"), 120, 90, 60) * 0.25
                + (positive_ocf_years / max(1, len(recent)) * 100) * 0.20
            )
            balance_score = clamp_score(
                score_low(latest.get("debt_ratio"), 35, 55, 70) * 0.55
                + score_low(latest.get("interest_bearing_debt_ratio"), 15, 30, 45) * 0.25
                + score_low(goodwill_to_equity, 5, 15, 30) * 0.20
            )

            weighted_value_score = 0
            weight_sum = 0
            for value, weight in [
                (score_low(reasonable_discount, -25, 0, 35), 0.45 if reasonable_discount is not None else 0),
                (score_low(pe_ttm, 10, 20, 35), 0.25 if pe_ttm is not None and pe_ttm > 0 else 0),
                (score_low(pb_ex_goodwill, 1.2, 2.5, 4.0), 0.15 if pb_ex_goodwill is not None and pb_ex_goodwill > 0 else 0),
                (score_high(dividend_yield, 5, 3, 1), 0.15 if dividend_yield is not None else 0),
            ]:
                weighted_value_score += value * weight
                weight_sum += weight
            valuation_score = clamp_score(weighted_value_score / weight_sum) if weight_sum else None

            summary = [
                {"key": "quality", "title": "公司质量", "score": quality_score, **status_from_score(quality_score), "main": f"ROE 5年均值 {round_or_none(roe_avg_5y) if roe_avg_5y is not None else '-'}%", "note": "盈利能力、资本回报和利润稳定性"},
                {"key": "growth", "title": "成长性", "score": growth_score, **status_from_score(growth_score), "main": f"净利润 CAGR {round_or_none(profit_cagr) if profit_cagr is not None else '-'}%", "note": f"营收和归母净利润的{cagr_scope_text}与最新同周期变化"},
                {"key": "cashflow", "title": "现金流质量", "score": cashflow_score, **status_from_score(cashflow_score), "main": f"现金流/净利润 {round_or_none(cf_profit_avg_5y) if cf_profit_avg_5y is not None else '-'}%", "note": "利润能否转化成经营现金流"},
                {"key": "balance", "title": "资产负债", "score": balance_score, **status_from_score(balance_score), "main": f"资产负债率 {round_or_none(latest.get('debt_ratio')) if latest.get('debt_ratio') is not None else '-'}%", "note": "杠杆、有息负债和商誉压力"},
                {"key": "valuation", "title": "估值位置", "score": valuation_score, **status_from_score(valuation_score), "main": f"PE {round_or_none(pe_ttm) if pe_ttm is not None else '-'}", "note": "合理价偏离、PE、PB和股息率"},
            ]

            groups = [
                {"title": "盈利能力", "metrics": [
                    metric("ROE 5年均值", roe_avg_5y, "%", verdict_high(roe_avg_5y, 20, 15, 8), "股东资本回报"),
                    metric("ROIC 5年均值", roic_avg_5y, "%", verdict_high(roic_avg_5y, 15, 10, 6), "投入资本回报"),
                    metric("最新净利率", latest.get("net_profit_rate"), "%", verdict_high(latest.get("net_profit_rate"), 20, 10, 4), f"{latest['fiscal_year']} 年"),
                    metric("最新核心利润率", latest.get("core_profit_rate"), "%", verdict_high(latest.get("core_profit_rate"), 20, 10, 4), f"{latest['fiscal_year']} 年报，利润表口径"),
                ]},
                {"title": "成长性", "metrics": [
                    metric("营收 CAGR", revenue_cagr, "%", verdict_high(revenue_cagr, 15, 8, 0), cagr_note),
                    metric("归母净利 CAGR", profit_cagr, "%", verdict_high(profit_cagr, 15, 8, 0), cagr_note),
                    metric("最新营收累计同比", revenue_yoy, "%", verdict_high(revenue_yoy, 12, 5, 0), yoy_note),
                    metric("最新净利累计同比", profit_yoy, "%", verdict_high(profit_yoy, 12, 5, 0), yoy_note),
                ]},
                {"title": "现金流", "metrics": [
                    metric("现金流/净利润 5年均值", cf_profit_avg_5y, "%", verdict_high(cf_profit_avg_5y, 120, 90, 60), "经营现金流净额/归母净利润"),
                    metric("最新现金流/净利润", latest.get("cashflow_to_profit"), "%", verdict_high(latest.get("cashflow_to_profit"), 120, 90, 60), f"{latest['fiscal_year']} 年"),
                    metric("经营现金流为正", positive_ocf_years, f"/{len(recent)} 年", "good" if positive_ocf_years == len(recent) else "warn", "近5年"),
                    metric("最新经营现金流", latest.get("operate_cashflow"), "亿元", "good" if (latest.get("operate_cashflow") or 0) > 0 else "bad", f"{latest['fiscal_year']} 年"),
                ]},
                {"title": "资产质量", "metrics": [
                    metric("资产负债率", latest.get("debt_ratio"), "%", verdict_low(latest.get("debt_ratio"), 35, 55, 70), f"{latest['fiscal_year']} 年"),
                    metric("有息负债率", latest.get("interest_bearing_debt_ratio"), "%", verdict_low(latest.get("interest_bearing_debt_ratio"), 15, 30, 45), "口径来自财报摘要"),
                    metric("商誉/归母权益", goodwill_to_equity, "%", verdict_low(goodwill_to_equity, 5, 15, 30), "商誉减值压力"),
                    metric("总资产", latest.get("total_assets"), "亿元", "neutral", f"{latest['fiscal_year']} 年"),
                ]},
                {"title": "估值回报", "metrics": [
                    metric("PE(TTM)", pe_ttm, "", verdict_low(pe_ttm, 10, 20, 35), "腾讯行情/本地缓存"),
                    metric("PB(扣商誉)", pb_ex_goodwill, "", verdict_low(pb_ex_goodwill, 1.2, 2.5, 4.0), "按归母权益扣商誉"),
                    metric("股息率", dividend_yield, "%", verdict_high(dividend_yield, 5, 3, 1), "最近更新值"),
                    metric("合理价偏离", reasonable_discount, "%", verdict_low(reasonable_discount, -25, 0, 35), "负数代表低于合理价"),
                ]},
            ]

            signals = []

            def add_signal(level, text, detail):
                signals.append({"level": level, "text": text, "detail": detail})

            if latest.get("cashflow_to_profit") is not None and latest["cashflow_to_profit"] < 60:
                add_signal("bad", "利润现金含量偏弱", f"{latest['fiscal_year']} 年经营现金流/净利润为 {round_or_none(latest['cashflow_to_profit'])}%")
            if cf_profit_avg_5y is not None and cf_profit_avg_5y < 80:
                add_signal("warn", "近5年现金流覆盖不足", f"近5年均值为 {round_or_none(cf_profit_avg_5y)}%")
            if profit_yoy is not None and profit_yoy < -20:
                add_signal("bad", "最新净利润明显下滑", f"{latest_period_note}归母净利润同比 {round_or_none(profit_yoy)}%")
            if revenue_yoy is not None and revenue_yoy < -10:
                add_signal("warn", "最新营收下滑", f"{latest_period_note}营收同比 {round_or_none(revenue_yoy)}%")
            if latest.get("debt_ratio") is not None and latest["debt_ratio"] > 70:
                add_signal("bad", "资产负债率偏高", f"{latest['fiscal_year']} 年资产负债率 {round_or_none(latest['debt_ratio'])}%")
            if goodwill_to_equity is not None and goodwill_to_equity > 30:
                add_signal("warn", "商誉占净资产较高", f"商誉/归母权益为 {round_or_none(goodwill_to_equity)}%")
            if pe_ttm is not None and pe_ttm > 50:
                add_signal("warn", "PE 估值较高", f"当前 PE(TTM) 为 {round_or_none(pe_ttm)}")
            if not signals:
                add_signal("good", "暂无明显红色信号", "基于当前已有年报数据，未触发主要异常规则。")

            return jsonify({
                "stock": {
                    "code": stock["code"],
                    "name": stock["name"],
                    "industry": stock.get("industry"),
                    "price": round_or_none(price),
                    "reasonable_price": round_or_none(reasonable_price),
                },
                "latest_year": latest["fiscal_year"],
                "latest_period": latest_period_note,
                "year_range": f"{all_earliest['fiscal_year']}-{latest['fiscal_year']}",
                "cagr_years": cagr_years,
                "cagr_range": cagr_note,
                "summary": summary,
                "groups": groups,
                "signals": signals,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500




    @app.route("/api/stock/<code>/capital-allocation")
    def api_stock_capital_allocation(code):
        """资本配置分析：经营现金流如何流向再投资、分红、偿债、融资和股本变化。"""

        def to_float(value):
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def round_or_none(value, ndigits=4):
            return round(value, ndigits) if value is not None else None

        def pct(part, whole):
            if part is None or whole in (None, 0):
                return None
            return part / whole * 100

        def get_val(row, key, default=None):
            if not row:
                return default
            value = to_float(row.get(key))
            return default if value is None else value

        stock_rows = execute_query("SELECT code, name, market, industry FROM stocks WHERE code=%s", (code,))
        if not stock_rows:
            return jsonify({"error": "未找到该股票"}), 404

        from_year = request.args.get("from_year", type=int)
        to_year = request.args.get("to_year", type=int)
        selected_year = request.args.get("year", type=int)

        fin_rows = execute_query(
            """SELECT fiscal_year, parent_profit, operate_cashflow, total_shares, interest_bearing_debt_ratio
               FROM custom_financials
               WHERE stock_code=%s AND report_period='FY'
               ORDER BY fiscal_year ASC""",
            (code,),
        )
        if not fin_rows:
            return jsonify({
                "stock": dict(stock_rows[0]),
                "years": [],
                "rows": [],
                "message": "暂无年报财务数据，请先更新财报数据。",
            })

        all_years = [int(r["fiscal_year"]) for r in fin_rows]
        if to_year is None:
            to_year = max(all_years)
        if from_year is None:
            from_year = max(min(all_years), to_year - 9)
        if selected_year is None:
            selected_year = to_year

        needed_years = sorted(set([y for y in all_years if from_year <= y <= to_year] + [from_year - 1]))
        if not needed_years:
            needed_years = all_years[-10:]
        placeholders = ",".join(["%s"] * len(needed_years))
        params = tuple([code] + needed_years)

        div_rows = execute_query(
            f"""SELECT fiscal_year, dividend_amount
                FROM dividends
                WHERE stock_code=%s AND fiscal_year IN ({placeholders})""",
            params,
        )
        cash_rows = execute_query(
            f"""SELECT fiscal_year, cf_oper_net, cf_buy_assets, cf_invest_income, cf_repay_debt, cf_borrow,
                       cf_bond, cf_finance_in, cf_other_finance_in, cf_finance_inflow,
                       cf_finance_net, cf_dividend_interest
                FROM cash_flows
                WHERE stock_code=%s AND report_period='FY' AND fiscal_year IN ({placeholders})""",
            params,
        )
        balance_rows = execute_query(
            f"""SELECT fiscal_year, goodwill, total_liabilities, parent_equity
                FROM balance_sheets
                WHERE stock_code=%s AND report_period='FY' AND fiscal_year IN ({placeholders})""",
            params,
        )

        fin_map = {int(r["fiscal_year"]): r for r in fin_rows}
        div_map = {int(r["fiscal_year"]): r for r in div_rows}
        cash_map = {int(r["fiscal_year"]): r for r in cash_rows}
        balance_map = {int(r["fiscal_year"]): r for r in balance_rows}

        rows = []
        for year in [y for y in all_years if from_year <= y <= to_year]:
            fin = fin_map.get(year)
            prev_fin = fin_map.get(year - 1)
            cash = cash_map.get(year)
            div = div_map.get(year)
            bal = balance_map.get(year)
            prev_bal = balance_map.get(year - 1)

            operating_cashflow = get_val(cash, "cf_oper_net")
            if operating_cashflow is None:
                operating_cashflow = get_val(fin, "operate_cashflow")
            capex = get_val(cash, "cf_buy_assets", 0)
            investment_income_cash = get_val(cash, "cf_invest_income", 0)
            dividend = get_val(div, "dividend_amount", 0)
            buyback = 0
            debt_repayment = get_val(cash, "cf_repay_debt", 0)
            debt_borrow = (get_val(cash, "cf_borrow", 0) or 0) + (get_val(cash, "cf_bond", 0) or 0)
            equity_financing = get_val(cash, "cf_finance_in", 0)
            other_financing = get_val(cash, "cf_other_finance_in", 0)
            financing_inflow = get_val(cash, "cf_finance_inflow")
            financing_sources = debt_borrow + (equity_financing or 0) + (other_financing or 0)
            if financing_inflow is not None and financing_inflow > financing_sources:
                financing_sources = financing_inflow
            finance_net = get_val(cash, "cf_finance_net")
            dividend_interest_paid = get_val(cash, "cf_dividend_interest")

            free_cashflow = (
                operating_cashflow - capex
                if operating_cashflow is not None and capex is not None else None
            )
            remaining_after_allocation = (
                operating_cashflow + investment_income_cash - capex - dividend - buyback - debt_repayment
                if operating_cashflow is not None else None
            )
            financing_remaining_after_allocation = (
                operating_cashflow + investment_income_cash + financing_sources - capex - dividend - buyback - debt_repayment
                if operating_cashflow is not None else None
            )

            goodwill = get_val(bal, "goodwill")
            prev_goodwill = get_val(prev_bal, "goodwill")
            goodwill_change = goodwill - prev_goodwill if goodwill is not None and prev_goodwill is not None else None
            total_shares = get_val(fin, "total_shares")
            prev_total_shares = get_val(prev_fin, "total_shares")
            total_shares_change = total_shares - prev_total_shares if total_shares is not None and prev_total_shares is not None else None
            total_shares_change_pct = pct(total_shares_change, prev_total_shares)
            total_liabilities = get_val(bal, "total_liabilities")
            prev_total_liabilities = get_val(prev_bal, "total_liabilities")
            liabilities_change = total_liabilities - prev_total_liabilities if total_liabilities is not None and prev_total_liabilities is not None else None
            parent_profit = get_val(fin, "parent_profit")

            rows.append({
                "year": year,
                "operating_cashflow": round_or_none(operating_cashflow),
                "capex": round_or_none(capex),
                "investment_income_cash": round_or_none(investment_income_cash),
                "dividend": round_or_none(dividend),
                "buyback": buyback,
                "debt_repayment": round_or_none(debt_repayment),
                "debt_borrow": round_or_none(debt_borrow),
                "equity_financing": round_or_none(equity_financing),
                "other_financing": round_or_none(other_financing),
                "financing_inflow": round_or_none(financing_inflow),
                "financing_sources": round_or_none(financing_sources),
                "finance_net": round_or_none(finance_net),
                "dividend_interest_paid": round_or_none(dividend_interest_paid),
                "free_cashflow": round_or_none(free_cashflow),
                "remaining_after_allocation": round_or_none(remaining_after_allocation),
                "financing_remaining_after_allocation": round_or_none(financing_remaining_after_allocation),
                "parent_profit": round_or_none(parent_profit),
                "dividend_payout_ratio": round_or_none(pct(dividend, parent_profit), 2),
                "capex_to_ocf": round_or_none(pct(capex, operating_cashflow), 2),
                "debt_repay_to_ocf": round_or_none(pct(debt_repayment, operating_cashflow), 2),
                "goodwill": round_or_none(goodwill),
                "goodwill_change": round_or_none(goodwill_change),
                "total_shares": round_or_none(total_shares),
                "total_shares_change": round_or_none(total_shares_change),
                "total_shares_change_pct": round_or_none(total_shares_change_pct, 2),
                "total_liabilities": round_or_none(total_liabilities),
                "liabilities_change": round_or_none(liabilities_change),
            })

        selected = next((r for r in rows if r["year"] == selected_year), rows[-1] if rows else None)

        signals = []
        if selected:
            if selected.get("free_cashflow") is not None and selected["free_cashflow"] < 0:
                signals.append({"level": "warn", "text": "自由现金流为负", "detail": f"{selected['year']} 年经营现金流不足以覆盖资本开支。"})
            if selected.get("dividend") and selected.get("free_cashflow") is not None and selected["dividend"] > selected["free_cashflow"]:
                signals.append({"level": "warn", "text": "分红高于自由现金流", "detail": "需要关注分红是否依赖存量现金或外部融资。"})
            if selected.get("total_shares_change_pct") is not None and selected["total_shares_change_pct"] > 2:
                signals.append({"level": "warn", "text": "股本有摊薄", "detail": f"总股本同比增加 {selected['total_shares_change_pct']}%。"})
            if selected.get("goodwill_change") is not None and selected["goodwill_change"] > 0:
                signals.append({"level": "neutral", "text": "商誉增加", "detail": f"商誉同比增加 {selected['goodwill_change']} 亿元，可能来自并购或口径变动。"})
            if selected.get("remaining_after_allocation") is not None and selected.get("financing_remaining_after_allocation") is not None and selected["remaining_after_allocation"] < 0 <= selected["financing_remaining_after_allocation"]:
                signals.append({"level": "warn", "text": "经营口径为负，融资后转正", "detail": "资本配置依赖外部融资补足现金缺口。"})
            if selected.get("debt_borrow") and selected.get("debt_repayment") and selected["debt_borrow"] > selected["debt_repayment"]:
                signals.append({"level": "neutral", "text": "借款流入高于偿债", "detail": "筹资侧仍在净补充债务资金。"})
        if not signals:
            signals.append({"level": "good", "text": "暂无明显资本配置异常", "detail": "基于当前已有现金流、分红、商誉和股本数据。"})

        return jsonify({
            "stock": dict(stock_rows[0]),
            "years": [y for y in all_years if from_year <= y <= to_year],
            "from_year": from_year,
            "to_year": to_year,
            "selected_year": selected["year"] if selected else selected_year,
            "rows": rows,
            "selected": selected,
            "signals": signals,
            "notes": [
                "回购暂无专项数据表，当前瀑布图按 0 处理并在页面标注。",
                "资本开支使用现金流量表“购建固定资产、无形资产和其他长期资产支付的现金”。",
                "投资收益现金使用现金流量表“取得投资收益所收到的现金”，作为过去资本配置带来的现金回收单独展示。",
                "经营剩余 = 经营现金流 + 投资收益现金 - 资本开支 - 分红 - 回购 - 偿债。",
                "融资后剩余 = 经营现金流 + 投资收益现金 + 借款/发债流入 + 股权融资/其他筹资流入 - 资本开支 - 分红 - 回购 - 偿债。",
                "偿债使用现金流量表“偿还债务支付的现金”，融资流入包含取得借款、发行债券、吸收投资和其他筹资流入。",
            ],
        })
