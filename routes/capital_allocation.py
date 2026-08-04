"""Capital allocation dashboard route."""

from flask import jsonify, request


def register_capital_allocation_routes(app, deps):
    execute_query = deps["execute_query"]

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

