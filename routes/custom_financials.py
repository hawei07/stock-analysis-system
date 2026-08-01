"""Custom financial summary update and query routes."""

import time

import requests
from flask import jsonify, request


def register_custom_financial_routes(app, deps):
    execute_query = deps["execute_query"]
    _ensure_financials_columns = deps["ensure_financials_columns"]
    _get_update_stocks = deps["get_update_stocks"]
    _quote_symbol = deps["quote_symbol"]

    @app.route("/api/update-financials", methods=["POST"])
    def api_update_financials():
        """从东方财富拉取财务数据并存入 custom_financials 表
        mode: full=全量拉取, incremental=增量拉取(仅更新无数据的记录)
        支持年报+季报（全部报告类型）。
        """
        payload = request.get_json(silent=True) if request.is_json else {}
        mode = "full"
        if request.is_json:
            mode = payload.get("mode", "full")
        if request.args.get("mode"):
            mode = request.args["mode"]

        # 确保新字段列存在
        _ensure_financials_columns()

        # REPORT_TYPE → report_period
        period_map = {"年报": "FY", "三季报": "Q3", "中报": "Q2", "一季报": "Q1"}

        try:
            stocks = _get_update_stocks(payload)
            updated_count = 0
            stocks_processed = 0
            errors = []

            for s in stocks:
                code = s["code"]
                stocks_processed += 1
                try:
                    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                           "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                           f"&filter=(SECURITY_CODE=%22{code}%22)"
                           "&pageSize=200&sortColumns=REPORT_DATE&sortTypes=-1")
                    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    data = resp.json()
                    if not data.get("success"):
                        errors.append(f"{code}: API返回失败")
                        continue

                    records = data["result"]["data"]
                    # 按 (fiscal_year, report_period) 分组，取 NOTICE_DATE 更晚的
                    key_best = {}
                    for item in records:
                        rd = item.get("REPORT_DATE", "")
                        rt = item.get("REPORT_TYPE", "")
                        period = period_map.get(rt)
                        if not rd or not period:
                            continue
                        year = int(rd[:4])
                        notice = item.get("NOTICE_DATE", "")
                        key = (year, period)
                        if key not in key_best or notice > key_best[key][0]:
                            key_best[key] = (notice, item)

                    # 增量模式：查询已有 (year, period) 组合
                    existing_keys = set()
                    if mode == "incremental":
                        existing = execute_query(
                            "SELECT fiscal_year, report_period FROM custom_financials WHERE stock_code=%s", (code,)
                        )
                        existing_keys = {(r["fiscal_year"], r["report_period"]) for r in existing}

                    for (year, period), (_, item) in key_best.items():
                        if mode == "incremental" and (year, period) in existing_keys:
                            continue

                        total_share = item.get("TOTAL_SHARE")
                        total_shares_val = round(total_share / 1e8, 4) if total_share else None

                        basic_eps = item.get("EPSJB")
                        basic_eps_val = round(float(basic_eps), 4) if basic_eps else None

                        ta_raw = item.get("TOTAL_ASSETS_PK", 0)
                        te_raw = item.get("TOTAL_EQUITY_PK", 0)
                        ta_val = round(ta_raw / 1e8, 4) if ta_raw else None
                        te_val = round(te_raw / 1e8, 4) if te_raw else None
                        debt_ratio_val = round((ta_raw - te_raw) / ta_raw * 100, 2) if (ta_raw and te_raw and ta_raw > 0) else None

                        idr_raw = item.get("INTEREST_DEBT_RATIO")
                        interest_bearing_debt_ratio_val = round(float(idr_raw), 4) if idr_raw else None

                        short_borrow_val = None
                        ncl_due1y_val = None
                        long_borrow_val = None
                        bonds_val = None

                        execute_query(
                            """INSERT INTO custom_financials
                            (stock_code, fiscal_year, report_period, total_revenue, operate_profit, parent_profit,
                             deducted_profit, operate_cashflow, roe, deducted_roe, roic,
                             total_assets, total_equity, total_shares, audit_opinion,
                             basic_eps, debt_ratio,
                             short_borrow, noncurrent_liab_due1y, long_borrow, bonds_payable,
                             interest_bearing_debt_ratio)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE
                             total_revenue=VALUES(total_revenue), operate_profit=VALUES(operate_profit),
                             parent_profit=VALUES(parent_profit), deducted_profit=VALUES(deducted_profit),
                             operate_cashflow=VALUES(operate_cashflow), roe=VALUES(roe),
                             deducted_roe=VALUES(deducted_roe), roic=VALUES(roic),
                             total_assets=VALUES(total_assets), total_equity=VALUES(total_equity),
                             total_shares=VALUES(total_shares), audit_opinion=VALUES(audit_opinion),
                             basic_eps=VALUES(basic_eps), debt_ratio=VALUES(debt_ratio),
                             short_borrow=VALUES(short_borrow), noncurrent_liab_due1y=VALUES(noncurrent_liab_due1y),
                             long_borrow=VALUES(long_borrow), bonds_payable=VALUES(bonds_payable),
                             interest_bearing_debt_ratio=VALUES(interest_bearing_debt_ratio)""",
                            (
                                code, year, period,
                                round(item["TOTALOPERATEREVE"] / 1e8, 4) if item.get("TOTALOPERATEREVE") else None,
                                round(item.get("OPERATE_PROFIT_PK", 0) / 1e8, 4) if item.get("OPERATE_PROFIT_PK") else None,
                                round(item["PARENTNETPROFIT"] / 1e8, 4) if item.get("PARENTNETPROFIT") else None,
                                round(item["KCFJCXSYJLR"] / 1e8, 4) if item.get("KCFJCXSYJLR") else None,
                                round(item.get("NETCASH_OPERATE_PK", 0) / 1e8, 4) if item.get("NETCASH_OPERATE_PK") else None,
                                round(item["ROEJQ"], 4) if item.get("ROEJQ") else None,
                                round(item["ROEKCJQ"], 4) if item.get("ROEKCJQ") else None,
                                round(item["ROIC"], 4) if item.get("ROIC") else None,
                                ta_val,
                                te_val,
                                total_shares_val,
                                None,
                                basic_eps_val,
                                debt_ratio_val,
                                short_borrow_val,
                                ncl_due1y_val,
                                long_borrow_val,
                                bonds_val,
                                interest_bearing_debt_ratio_val,
                            ),
                            fetch=False
                        )
                        updated_count += 1

                except Exception as e:
                    errors.append(f"{code}: {str(e)}")

                time.sleep(0.3)

            return jsonify({
                "success": True,
                "stocks_processed": stocks_processed,
                "records_updated": updated_count,
                "mode": mode,
                "errors": errors[:5] if errors else [],
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


    @app.route("/api/stock/<code>/financials")
    def api_stock_financials(code):
        """查询指定股票的多年财务数据，含后端计算的派生指标。
        Query params:
          from_year, to_year: 年份范围
          period: FY(年报,默认) / Q1 / Q2 / Q3 / all(全部)
          view: cumulative(累计,默认) / single(单季度)
        """
        from_year = request.args.get("from_year", 2016, type=int)
        to_year = request.args.get("to_year", 2025, type=int)
        period = request.args.get("period", "FY")
        view = request.args.get("view", "cumulative")

        need_single = (view == "single" and period != "FY")
        query_period = None if need_single else (None if period == "all" else period)

        if query_period:
            where_period = "AND cf.report_period = %s"
            params = [code, query_period, from_year, to_year]
        else:
            where_period = ""
            params = [code, from_year, to_year]

        balance_extra_fields = [
            "monetary_funds", "accounts_receivable", "inventory", "fixed_assets", "goodwill",
            "total_assets", "short_borrow", "long_borrow", "bonds_payable", "total_liabilities",
            "parent_equity", "total_equity",
        ]
        income_extra_fields = [
            "total_revenue", "operating_revenue", "operating_cost", "cost_of_revenue",
            "tax_surcharge", "interest_expense", "fee_commission_expense",
            "selling_expense", "admin_expense", "finance_expense", "rd_expense",
            "finance_interest_income",
            "invest_income", "operating_profit", "total_profit", "net_profit",
            "parent_net_profit", "basic_eps",
        ]
        cashflow_extra_fields = [
            "cf_sales_goods", "cf_oper_inflow", "cf_oper_outflow", "cf_oper_net",
            "cf_invest_net", "cf_buy_assets", "cf_finance_inflow", "cf_repay_debt",
            "cf_dividend_interest", "cf_finance_net",
        ]
        extra_select = ",\n                  " + ",\n                  ".join(
            [f"bs.{f} AS bs_{f}" for f in balance_extra_fields]
            + [f"inc.{f} AS inc_{f}" for f in income_extra_fields]
            + [f"cfs.{f} AS cf_{f}" for f in cashflow_extra_fields]
        )

        rows = execute_query(
            f"""SELECT cf.fiscal_year, cf.report_period, cf.total_revenue, cf.operate_profit, cf.parent_profit,
                      cf.deducted_profit, cf.operate_cashflow, cf.roe, cf.deducted_roe, cf.roic,
                      cf.total_assets, cf.total_equity, cf.total_shares,
                      cf.basic_eps, cf.debt_ratio,
                      cf.short_borrow, cf.noncurrent_liab_due1y, cf.long_borrow, cf.bonds_payable,
                      cf.interest_bearing_debt_ratio,
                      d.dividend_amount, d.dividend_per_share
                      {extra_select}
               FROM custom_financials cf
               LEFT JOIN dividends d ON cf.stock_code = d.stock_code AND cf.fiscal_year = d.fiscal_year
               LEFT JOIN balance_sheets bs ON cf.stock_code = bs.stock_code
                    AND cf.fiscal_year = bs.fiscal_year AND cf.report_period = bs.report_period
               LEFT JOIN income_statements inc ON cf.stock_code = inc.stock_code
                    AND cf.fiscal_year = inc.fiscal_year AND cf.report_period = inc.report_period
               LEFT JOIN cash_flows cfs ON cf.stock_code = cfs.stock_code
                    AND cf.fiscal_year = cfs.fiscal_year AND cf.report_period = cfs.report_period
               WHERE cf.stock_code = %s {where_period}
               AND cf.fiscal_year BETWEEN %s AND %s
               ORDER BY cf.fiscal_year DESC, FIELD(cf.report_period, 'FY','Q3','Q2','Q1') DESC""",
            tuple(params)
        )

        # 获取当前股价
        cur_price = None
        try:
            stock = execute_query("SELECT market FROM stocks WHERE code=%s", (code,))
            if stock:
                url = f"https://qt.gtimg.cn/q={_quote_symbol(code, stock[0].get('market'))}"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                resp.encoding = "gbk"
                text = resp.text
                if text.startswith("v_"):
                    parts = text.split("~")
                    if len(parts) >= 4:
                        price_str = parts[3].strip()
                        if price_str and price_str not in ("", "-"):
                            cur_price = float(price_str)
        except Exception:
            pass

        def _build_item(r):
            rev = float(r["total_revenue"]) if r["total_revenue"] else 0
            op = float(r["operate_profit"]) if r["operate_profit"] else 0
            pp = float(r["parent_profit"]) if r["parent_profit"] else 0
            dp = float(r["deducted_profit"]) if r["deducted_profit"] else 0
            ocf = float(r["operate_cashflow"]) if r["operate_cashflow"] else 0
            roe_v = float(r["roe"]) if r["roe"] else None
            droe_v = float(r["deducted_roe"]) if r["deducted_roe"] else None
            roic_v = float(r["roic"]) if r["roic"] else None
            ta = float(r["total_assets"]) if r["total_assets"] else 0
            te = float(r["total_equity"]) if r["total_equity"] else 0
            ts = float(r["total_shares"]) if r["total_shares"] else 0
            basic_eps = float(r["basic_eps"]) if r.get("basic_eps") else None
            debt_ratio_raw = float(r["debt_ratio"]) if r.get("debt_ratio") else None
            debt_ratio = (
                debt_ratio_raw if debt_ratio_raw is not None
                else (round((ta - te) / ta * 100, 2) if ta > 0 else None)
            )
            short_borrow = float(r["short_borrow"]) if r.get("short_borrow") else None
            ncl_due1y = float(r["noncurrent_liab_due1y"]) if r.get("noncurrent_liab_due1y") else None
            long_borrow = float(r["long_borrow"]) if r.get("long_borrow") else None
            bonds_payable = float(r["bonds_payable"]) if r.get("bonds_payable") else None
            dividend_amount = float(r["dividend_amount"]) if r.get("dividend_amount") else None
            dividend_per_share = float(r["dividend_per_share"]) if r.get("dividend_per_share") else None

            def income_alias_value(field):
                value = r.get(f"inc_{field}")
                return float(value) if value is not None else 0

            def positive_income_alias_value(field):
                return max(income_alias_value(field), 0)

            def income_revenue_value():
                return income_alias_value("total_revenue") or income_alias_value("operating_revenue")

            def income_finance_expense_before_interest_income_value():
                finance_expense = income_alias_value("finance_expense")
                finance_interest_income = positive_income_alias_value("finance_interest_income")
                if finance_interest_income > 0:
                    return max(finance_expense + finance_interest_income, 0)
                return max(finance_expense, 0)

            def income_period_expense_value():
                return (
                    positive_income_alias_value("selling_expense")
                    + positive_income_alias_value("admin_expense")
                    + positive_income_alias_value("rd_expense")
                    + income_finance_expense_before_interest_income_value()
                )

            def income_gross_value():
                return max(
                    income_revenue_value()
                    - positive_income_alias_value("cost_of_revenue")
                    - positive_income_alias_value("interest_expense")
                    - positive_income_alias_value("fee_commission_expense"),
                    0,
                )

            income_has_core_fields = any(
                r.get(f"inc_{field}") is not None
                for field in (
                    "total_revenue", "operating_revenue", "cost_of_revenue",
                    "selling_expense", "admin_expense", "finance_expense", "rd_expense",
                )
            )
            if income_has_core_fields:
                op = income_gross_value() - income_period_expense_value() - positive_income_alias_value("tax_surcharge")
                core_profit_rate = round(op / income_revenue_value() * 100, 2) if income_revenue_value() else None
            else:
                core_profit_rate = round(op / rev * 100, 2) if rev else None
            net_profit_rate = round(pp / rev * 100, 2) if rev else None
            cashflow_to_profit = round(ocf / pp * 100, 2) if pp and pp > 0 else None
            dividend_payout_ratio = (
                round(dividend_amount / pp * 100, 2)
                if (dividend_amount is not None and pp and pp > 0) else None
            )
            interest_bearing_debt_ratio = (
                round(float(r["interest_bearing_debt_ratio"]), 2)
                if r.get("interest_bearing_debt_ratio") else None
            )
            dividend_yield_fin = (
                round(dividend_per_share / cur_price * 100, 2)
                if (dividend_per_share is not None and dividend_per_share > 0
                    and cur_price and cur_price > 0) else None
            )

            def extra_val(prefix, field):
                value = r.get(f"{prefix}_{field}")
                return float(value) if value is not None else None

            extras = {}
            for field in balance_extra_fields:
                extras[f"bs_{field}"] = extra_val("bs", field)
            for field in income_extra_fields:
                extras[f"inc_{field}"] = extra_val("inc", field)
            for field in cashflow_extra_fields:
                extras[f"cf_{field}"] = extra_val("cf", field)

            inc_revenue = extras.get("inc_operating_revenue") or extras.get("inc_total_revenue")
            inc_cost = extras.get("inc_cost_of_revenue")
            if inc_cost is None:
                inc_cost = extras.get("inc_operating_cost")
            extras["inc_gross_margin"] = (
                round((inc_revenue - inc_cost) / inc_revenue * 100, 2)
                if inc_revenue and inc_cost is not None else None
            )
            extras["bs_goodwill_to_parent_equity"] = (
                round(extras.get("bs_goodwill") / extras.get("bs_parent_equity") * 100, 2)
                if extras.get("bs_goodwill") is not None and extras.get("bs_parent_equity") else None
            )
            extras["cf_free_cashflow"] = (
                round(extras.get("cf_cf_oper_net") - extras.get("cf_cf_buy_assets"), 4)
                if extras.get("cf_cf_oper_net") is not None and extras.get("cf_cf_buy_assets") is not None else None
            )

            return {
                "fiscal_year": r["fiscal_year"],
                "report_period": r.get("report_period", "FY"),
                "total_revenue": rev, "operate_profit": op, "parent_profit": pp,
                "deducted_profit": dp, "operate_cashflow": ocf,
                "roe": roe_v, "deducted_roe": droe_v, "roic": roic_v,
                "total_assets": ta, "total_equity": te, "total_shares": ts,
                "core_profit_rate": core_profit_rate, "net_profit_rate": net_profit_rate,
                "cashflow_to_profit": cashflow_to_profit,
                "basic_eps": basic_eps, "debt_ratio": debt_ratio,
                "dividend_amount": dividend_amount, "dividend_per_share": dividend_per_share,
                "dividend_payout_ratio": dividend_payout_ratio,
                "interest_bearing_debt_ratio": interest_bearing_debt_ratio,
                "dividend_yield_fin": dividend_yield_fin,
                **extras,
            }

        # 单季度模式：本期累计 - 上期累计
        if need_single:
            data_by_key = {}
            for r in rows:
                fy, rp = r["fiscal_year"], r.get("report_period", "FY")
                data_by_key[(fy, rp)] = _build_item(r)

            periods_order = ["Q1", "Q2", "Q3", "FY"]
            prev_map = {"Q1": None, "Q2": "Q1", "Q3": "Q2", "FY": "Q3"}
            flow_fields = ["total_revenue", "operate_profit", "parent_profit", "deducted_profit",
                           "operate_cashflow", "dividend_amount"]
            flow_fields += [f"inc_{f}" for f in income_extra_fields if f != "basic_eps"]
            flow_fields += [f"cf_{f}" for f in cashflow_extra_fields]

            result = []
            for (fy, rp), item in sorted(data_by_key.items(), key=lambda x: (-x[0][0], periods_order.index(x[0][1]))):
                prev_key = (fy, prev_map[rp]) if prev_map[rp] else None
                prev_item = data_by_key.get(prev_key) if prev_key else None
                single = {"fiscal_year": fy, "report_period": rp}
                for k, v in item.items():
                    if k in ("fiscal_year", "report_period"):
                        single[k] = v
                    elif v is None:
                        single[k] = None
                    elif k in flow_fields:
                        if prev_item is None or prev_item.get(k) is None:
                            single[k] = v if rp == "Q1" else None
                        else:
                            single[k] = round(v - prev_item[k], 4)
                    else:
                        single[k] = v
                # 重新计算派生指标
                rev_s = single.get("total_revenue") or 0
                op_s = single.get("operate_profit") or 0
                pp_s = single.get("parent_profit") or 0
                ocf_s = single.get("operate_cashflow") or 0
                da_s = single.get("dividend_amount")
                core_revenue_s = single.get("inc_total_revenue") or single.get("inc_operating_revenue") or rev_s
                single["core_profit_rate"] = round(op_s / core_revenue_s * 100, 2) if core_revenue_s else None
                single["net_profit_rate"] = round(pp_s / rev_s * 100, 2) if rev_s else None
                single["cashflow_to_profit"] = round(ocf_s / pp_s * 100, 2) if pp_s and pp_s > 0 else None
                single["dividend_payout_ratio"] = round(da_s / pp_s * 100, 2) if (da_s is not None and pp_s and pp_s > 0) else None
                inc_rev_s = single.get("inc_operating_revenue") or single.get("inc_total_revenue")
                inc_cost_s = single.get("inc_cost_of_revenue")
                if inc_cost_s is None:
                    inc_cost_s = single.get("inc_operating_cost")
                single["inc_gross_margin"] = (
                    round((inc_rev_s - inc_cost_s) / inc_rev_s * 100, 2)
                    if inc_rev_s and inc_cost_s is not None else None
                )
                single["cf_free_cashflow"] = (
                    round(single.get("cf_cf_oper_net") - single.get("cf_cf_buy_assets"), 4)
                    if single.get("cf_cf_oper_net") is not None and single.get("cf_cf_buy_assets") is not None else None
                )
                result.append(single)
            # 过滤到请求的报告期
            if period != "all":
                result = [r for r in result if r["report_period"] == period]
        else:
            result = [_build_item(r) for r in rows]

        return jsonify(result)


    # ==================== 资产负债表 API（数据源：新浪财经） ====================