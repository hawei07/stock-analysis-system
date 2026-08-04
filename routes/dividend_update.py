"""Dividend data update route."""

import re
import time

import requests
from flask import jsonify, request

from services.background_jobs import start_endpoint_stock_batch


def register_dividend_update_routes(app, deps):
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _schedule_auto_cloud_backup = deps.get("schedule_auto_cloud_backup")
    _get_update_stocks = deps["get_update_stocks"]
    _quote_symbol = deps["quote_symbol"]

    @app.route("/api/update-dividends", methods=["POST"])
    def api_update_dividends():
        """从东方财富和新浪财经更新股票的分红和净利润数据
        mode: full=全量更新, incremental=增量更新(仅更新有缺失的年份)
        """
        payload = request.get_json(silent=True) if request.is_json else {}
        mode = payload.get("mode", "full") if request.is_json else "full"
        if request.args.get("mode"):
            mode = request.args["mode"]
        payload = {**payload, "mode": mode}

        try:
            stocks = _get_update_stocks(payload, include_name_market=True)
            if len(stocks) > 1 or (payload.get("background") and stocks):
                return jsonify(start_endpoint_stock_batch(
                    app,
                    get_connection,
                    execute_query,
                    "update_dividends",
                    "分红数据更新",
                    payload,
                    stocks,
                    api_update_dividends,
                    "/api/update-dividends",
                    on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("dividends-update"),
                ))
            updated_count = 0
            errors = []

            # 增量模式：找出每只股票已有的分红年份
            existing_years = {}
            if mode == "incremental":
                all_divs = execute_query("SELECT stock_code, fiscal_year FROM dividends")
                for d in all_divs:
                    key = d["stock_code"]
                    if key not in existing_years:
                        existing_years[key] = set()
                    existing_years[key].add(d["fiscal_year"])

            for s in stocks:
                code = s["code"]
                market = s.get("market", "SH")
                net_profits = {}
                total_share = 0

                # 1. 获取净利润
                try:
                    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                           "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                           f"&filter=(SECURITY_CODE=%22{code}%22)&pageSize=200")
                    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                    data = resp.json()
                    if data.get("success"):
                        for item in data["result"]["data"]:
                            if item.get("REPORT_TYPE") == "年报":
                                year = int(item["REPORT_DATE"][:4])
                                profit = item.get("PARENTNETPROFIT")
                                if profit and year not in net_profits:
                                    net_profits[year] = round(profit / 1e8, 4)
                            if item.get("TOTAL_SHARE") and not total_share:
                                total_share = item["TOTAL_SHARE"]
                except Exception as e:
                    errors.append(f"{code}: 净利润获取失败 - {str(e)}")
                    continue

                # 增量模式：跳过已有数据的年份
                if mode == "incremental" and code in existing_years:
                    net_profits = {y: v for y, v in net_profits.items() if y not in existing_years[code]}

                # 2. 获取分红方案（全量模式或增量有缺失数据时）
                yearly_dividends = {}
                yearly_dps = {}
                need_dividend_fetch = mode == "full" or len(net_profits) > 0
                if need_dividend_fetch and total_share > 0:
                    try:
                        url2 = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml"
                        resp2 = requests.get(url2, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                        resp2.encoding = 'gbk'
                        text = resp2.text
                        # 先匹配 tr 块，再提取字段（避免 .*?实施 过滤导致漏掉条目）
                        tr_blocks = re.findall(r'<tr[^>]*>(.*?)</tr>', text, re.DOTALL)
                        for tr in tr_blocks:
                            dm = re.search(r'(\d{4}-\d{2}-\d{2})', tr)
                            if not dm or '实施' not in tr:
                                continue
                            date_str = dm.group(1)
                            nums = re.findall(r'>\s*([\d.]+)\s*<', tr)
                            if len(nums) < 3:
                                continue
                            cal_year = int(date_str[:4])
                            cal_month = int(date_str[5:7])
                            # 财年映射：<=7月发放的属于上一财年（年终分红），>=8月属于当年（中期分红）
                            fiscal_year = cal_year - 1 if cal_month <= 7 else cal_year
                            dividend_per_10 = float(nums[-1])
                            if dividend_per_10 > 0:
                                if fiscal_year not in yearly_dividends:
                                    yearly_dividends[fiscal_year] = 0
                                    yearly_dps[fiscal_year] = 0
                                yearly_dividends[fiscal_year] += dividend_per_10 * total_share / 10 / 1e8
                                yearly_dps[fiscal_year] += dividend_per_10 / 10
                    except Exception as e:
                        errors.append(f"{code}: 分红获取失败 - {str(e)}")

                # 3. 更新分红数据库
                for year in net_profits:
                    np_val = net_profits[year]
                    da_val = yearly_dividends.get(year)
                    if da_val is not None:
                        execute_query(
                            "INSERT INTO dividends (stock_code, fiscal_year, net_profit, dividend_amount, dividend_per_share) "
                            "VALUES (%s, %s, %s, %s, %s) "
                            "ON DUPLICATE KEY UPDATE net_profit=VALUES(net_profit), dividend_amount=VALUES(dividend_amount), dividend_per_share=VALUES(dividend_per_share)",
                            (code, year, np_val, da_val, yearly_dps.get(year)),
                            fetch=False
                        )
                        updated_count += 1

                # 4. 更新 PE TTM 和股息率（腾讯行情接口）
                try:
                    url = f"https://qt.gtimg.cn/q={_quote_symbol(code, market)}"
                    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                    resp.encoding = 'gbk'
                    text = resp.text
                    if text.startswith('v_'):
                        parts = text.split('~')
                        if len(parts) >= 40:
                            pe_ttm = None
                            div_yield = None
                            pe_str = parts[39].strip()
                            if pe_str and pe_str != '' and pe_str != '-':
                                try:
                                    pe_ttm = float(pe_str)
                                except:
                                    pe_ttm = None
                            price_str = parts[3].strip()
                            if price_str and price_str != '' and price_str != '-':
                                try:
                                    cur_price = float(price_str)
                                    div_rows = execute_query(
                                        "SELECT dividend_per_share FROM dividends "
                                        "WHERE stock_code=%s AND dividend_per_share>0 ORDER BY fiscal_year DESC LIMIT 2",
                                        (code,)
                                    )
                                    if div_rows:
                                        dps = max(float(r["dividend_per_share"]) for r in div_rows)
                                        if dps > 0 and cur_price > 0:
                                            div_yield = round(dps / cur_price * 100, 2)
                                except:
                                    div_yield = None
                            execute_query(
                                "UPDATE stocks SET pe_ttm=%s, dividend_yield=%s WHERE code=%s",
                                (pe_ttm, div_yield, code),
                                fetch=False
                            )
                except Exception as e:
                    errors.append(f"{code}: PE/股息率更新失败 - {str(e)}")

                time.sleep(0.3)

            return jsonify({
                "success": True,
                "message": f"已更新 {updated_count} 条分红记录",
                "stocks_processed": len(stocks),
                "mode": mode,
                "errors": errors[:5] if errors else []
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500


    # ==================== 自定义财报 API ====================
