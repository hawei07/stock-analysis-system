"""股票分析系统 - Web 服务"""

from flask import Flask, jsonify, request, render_template
import sys
import re
import time
import requests
sys.path.insert(0, r"D:\stock-analysis-system")
from models import Stock
from db import execute_query

app = Flask(__name__)


# ==================== 页面路由 ====================

@app.route("/")
@app.route("/stock/<code>")
def index(code=None):
    return render_template("index.html")


# ==================== API 路由 ====================

@app.route("/api/stocks")
def api_stocks():
    page = request.args.get("page", 1, type=int)
    page_size = request.args.get("page_size", 15, type=int)
    market = request.args.get("market", None)
    status = request.args.get("status", None)
    keyword = request.args.get("keyword", None)

    result = Stock.get_all(
        page=page, page_size=page_size,
        market=market or None,
        status=status or None,
        keyword=keyword or None,
    )
    return jsonify(result)


@app.route("/api/stock/<code>")
def api_stock_detail(code):
    stock = Stock.get_by_code(code)
    if stock:
        # 确保日期字段可json序列化
        if stock.get("list_date"):
            stock["list_date"] = str(stock["list_date"])
        stock["created_at"] = str(stock["created_at"]) if stock.get("created_at") else None
        stock["updated_at"] = str(stock["updated_at"]) if stock.get("updated_at") else None

        # 获取实时行情：股价、PE(TTM)、市值
        realtime = {"price": None, "pe_ttm": None, "market_cap": None}
        try:
            market = stock.get("market", "SH")
            prefix = "sh" if market == "SH" else ("sz" if market == "SZ" else "bj")
            url = f"https://qt.gtimg.cn/q={prefix}{code}"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            resp.encoding = "gbk"
            text = resp.text
            if text.startswith("v_"):
                parts = text.split("~")
                if len(parts) >= 4:
                    price_str = parts[3].strip()
                    if price_str and price_str != "-":
                        realtime["price"] = float(price_str)
                if len(parts) >= 40:
                    pe_str = parts[39].strip()
                    if pe_str and pe_str != "-":
                        try:
                            realtime["pe_ttm"] = float(pe_str)
                        except ValueError:
                            pass
                if len(parts) >= 46:
                    cap_str = parts[45].strip()
                    if cap_str and cap_str != "-":
                        try:
                            # 腾讯行情 parts[45] 已是亿元单位
                            realtime["market_cap"] = round(float(cap_str), 2)
                        except ValueError:
                            pass
        except Exception:
            pass

        stock["realtime"] = realtime
        stock["dividend_yield"] = stock.get("dividend_yield")  # 已在 stocks 表中

        return jsonify(stock)
    return jsonify({"error": "未找到该股票"}), 404


@app.route("/api/stock-search")
def api_stock_search():
    """根据代码或名称模糊搜索股票（本地DB）"""
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify([])
    rows = execute_query(
        "SELECT code, name, market FROM stocks WHERE code LIKE %s OR name LIKE %s LIMIT 10",
        (f"%{keyword}%", f"%{keyword}%")
    )
    results = [{"code": r["code"], "name": r["name"], "market": r["market"]} for r in rows]
    # 本地有结果直接返回
    if results:
        return jsonify(results)
    # 本地无结果，尝试东方财富搜索
    try:
        url = "https://searchadapter.eastmoney.com/api/suggest/get?type=14&input=" + keyword
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        data = resp.json()
        ext = data.get("QuotationCodeTable", {}).get("Data", [])
        for r in ext[:8]:
            code = r.get("Code", "")
            name = r.get("Name", "")
            mkt = r.get("MktNum", "")
            market = {"0": "SZ", "1": "SH"}.get(str(mkt), "SH")
            if code and name:
                results.append({"code": code, "name": name, "market": market})
    except Exception:
        pass
    return jsonify(results)


@app.route("/api/stock-info/<code>")
def api_stock_info(code):
    """根据股票代码从东方财富获取名称和市场信息"""
    # 尝试上海和深圳两个市场
    markets_to_try = []
    if code.startswith(("6", "5", "9")):
        markets_to_try = [("1", "SH"), ("0", "SZ")]
    else:
        markets_to_try = [("0", "SZ"), ("1", "SH")]

    name = None
    market = None
    for sec_market, our_market in markets_to_try:
        try:
            url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58,f300"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            data = resp.json()
            if data.get("data") and data["data"].get("f58"):
                name = data["data"]["f58"]
                market = our_market
                break
        except Exception:
            continue

    if not name:
        return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

    return jsonify({"code": code, "name": name, "market": market})


@app.route("/api/stock", methods=["POST"])
def api_add_stock():
    data = request.get_json()
    code = data.get("code", "").strip()
    if not code:
        return jsonify({"error": "请输入股票代码"}), 400

    existing = Stock.get_by_code(code)
    if existing:
        return jsonify({"error": f"股票代码 {code} 已存在"}), 409

    # 如果没传名称或市场，自动从东方财富获取
    name = data.get("name", "").strip()
    market = data.get("market", "").strip()
    if not name or not market:
        markets_to_try = [("1", "SH"), ("0", "SZ")] if code.startswith(("6", "5", "9")) else [("0", "SZ"), ("1", "SH")]
        for sec_market, our_market in markets_to_try:
            try:
                url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                resp_data = resp.json()
                if resp_data.get("data") and resp_data["data"].get("f58"):
                    if not name:
                        name = resp_data["data"]["f58"]
                    if not market:
                        market = our_market
                    break
            except Exception:
                continue

        if not name:
            return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

    if market and market not in ("SH", "SZ", "BJ"):
        return jsonify({"error": "市场必须是 SH/SZ/BJ"}), 400

    try:
        Stock.add(
            code=code,
            name=name,
            market=market or "SH",
            industry=data.get("industry"),
            list_date=data.get("list_date"),
            status=data.get("status", "正常"),
        )
        return jsonify({"success": True, "message": f"添加成功: {name}({code})"}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stock/<code>", methods=["PUT"])
def api_update_stock(code):
    data = request.get_json()
    if not data:
        return jsonify({"error": "无更新数据"}), 400
    try:
        cnt = Stock.update(code, **data)
        if cnt:
            return jsonify({"success": True, "message": "更新成功"})
        return jsonify({"error": "未找到该股票"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stock/<code>", methods=["DELETE"])
def api_delete_stock(code):
    try:
        cnt = Stock.delete(code)
        if cnt:
            return jsonify({"success": True, "message": "删除成功"})
        return jsonify({"error": "未找到该股票"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/stats")
def api_stats():
    all_stocks = Stock.get_all(page=1, page_size=1000)
    data = all_stocks["data"]
    markets = {"SH": 0, "SZ": 0, "BJ": 0}
    industries = {}
    for s in data:
        markets[s["market"]] = markets.get(s["market"], 0) + 1
        ind = s.get("industry") or "其他"
        industries[ind] = industries.get(ind, 0) + 1
    return jsonify({
        "total": all_stocks["total"],
        "markets": markets,
        "industries": industries,
    })


# ==================== 分红 API ====================

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


# ==================== 数据更新 API ====================

@app.route("/api/update-dividends", methods=["POST"])
def api_update_dividends():
    """从东方财富和新浪财经更新股票的分红和净利润数据
    mode: full=全量更新, incremental=增量更新(仅更新有缺失的年份)
    """
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = execute_query("SELECT code, name, market FROM stocks WHERE status='正常'")
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
                prefix = "sh" if market == "SH" else "sz"
                url = f"https://qt.gtimg.cn/q={prefix}{code}"
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


def _ensure_financials_columns():
    """确保 custom_financials 包含新增字段（幂等）"""
    new_columns = [
        ("basic_eps", "DECIMAL(18,4) DEFAULT NULL COMMENT '归母普通股每股收益'"),
        ("debt_ratio", "DECIMAL(10,4) DEFAULT NULL COMMENT '资产负债率(%)'"),
        ("short_borrow", "DECIMAL(18,4) DEFAULT NULL COMMENT '短期借款(亿)'"),
        ("noncurrent_liab_due1y", "DECIMAL(18,4) DEFAULT NULL COMMENT '一年内到期非流动负债(亿)'"),
        ("long_borrow", "DECIMAL(18,4) DEFAULT NULL COMMENT '长期借款(亿)'"),
        ("bonds_payable", "DECIMAL(18,4) DEFAULT NULL COMMENT '应付债券(亿)'"),
        ("interest_bearing_debt_ratio", "DECIMAL(10,4) DEFAULT NULL COMMENT '有息负债率(%)'"),
    ]
    for col_name, col_def in new_columns:
        try:
            execute_query(
                f"ALTER TABLE custom_financials ADD COLUMN {col_name} {col_def}",
                fetch=False,
            )
        except Exception:
            pass  # 列已存在则忽略


@app.route("/api/update-financials", methods=["POST"])
def api_update_financials():
    """从东方财富拉取财务数据并存入 custom_financials 表
    mode: full=全量拉取, incremental=增量拉取(仅更新无数据的记录)
    支持年报+季报（全部报告类型）。
    """
    mode = "full"
    if request.is_json:
        mode = request.get_json(silent=True).get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    # 确保新字段列存在
    _ensure_financials_columns()

    # REPORT_TYPE → report_period
    period_map = {"年报": "FY", "三季报": "Q3", "中报": "Q2", "一季报": "Q1"}

    try:
        stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
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

    rows = execute_query(
        f"""SELECT cf.fiscal_year, cf.report_period, cf.total_revenue, cf.operate_profit, cf.parent_profit,
                  cf.deducted_profit, cf.operate_cashflow, cf.roe, cf.deducted_roe, cf.roic,
                  cf.total_assets, cf.total_equity, cf.total_shares,
                  cf.basic_eps, cf.debt_ratio,
                  cf.short_borrow, cf.noncurrent_liab_due1y, cf.long_borrow, cf.bonds_payable,
                  cf.interest_bearing_debt_ratio,
                  d.dividend_amount, d.dividend_per_share
           FROM custom_financials cf
           LEFT JOIN dividends d ON cf.stock_code = d.stock_code COLLATE utf8mb4_unicode_ci AND cf.fiscal_year = d.fiscal_year
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
            market = stock[0].get("market", "SH")
            prefix = "sh" if market == "SH" else "sz"
            url = f"https://qt.gtimg.cn/q={prefix}{code}"
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
            single["core_profit_rate"] = round(op_s / rev_s * 100, 2) if rev_s else None
            single["net_profit_rate"] = round(pp_s / rev_s * 100, 2) if rev_s else None
            single["cashflow_to_profit"] = round(ocf_s / pp_s * 100, 2) if pp_s and pp_s > 0 else None
            single["dividend_payout_ratio"] = round(da_s / pp_s * 100, 2) if (da_s is not None and pp_s and pp_s > 0) else None
            result.append(single)
        # 过滤到请求的报告期
        if period != "all":
            result = [r for r in result if r["report_period"] == period]
    else:
        result = [_build_item(r) for r in rows]

    return jsonify(result)


# ==================== 资产负债表 API（数据源：新浪财经） ====================

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
    mode = "full"
    if request.is_json:
        mode = request.get_json(silent=True).get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

    try:
        stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
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


# ==================== 利润表 & 现金流量表 API（数据源：新浪财经） ====================

# 利润表行映射
INCOME_ROW_MAP = [
    ("营业总收入", "total_revenue"),
    ("营业收入", "operating_revenue"),
    ("营业总成本", "operating_cost"),
    ("营业成本", "cost_of_revenue"),
    ("营业税金及附加", "tax_surcharge"),
    ("销售费用", "selling_expense"),
    ("管理费用", "admin_expense"),
    ("财务费用", "finance_expense"),
    ("研发费用", "rd_expense"),
    ("公允价值变动收益", "fair_value_change"),
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
                existing = all_year_data.get(col_year)
                if existing is None or col_date > (all_year_data.get(f"_max_date_{col_year}", "")):
                    all_year_data[col_year] = values
                    all_year_data[f"_max_date_{col_year}"] = col_date

    if target_year is not None:
        return all_year_data.get(target_year)
    return all_year_data


def _upsert_finance(stock_code, all_years, columns, table):
    """通用财报数据写入"""
    for year, values in sorted((k, v) for k, v in all_years.items() if isinstance(k, int)):
        placeholders = ", ".join(["%s"] * len(columns))
        col_names = ", ".join(columns)
        update_clause = ", ".join([f"{c}=VALUES({c})" for c in columns])

        sql = (
            f"INSERT INTO {table} (stock_code, fiscal_year, report_period, {col_names}) "
            f"VALUES (%s, %s, %s, {placeholders}) "
            f"ON DUPLICATE KEY UPDATE {update_clause}"
        )
        params = [stock_code, year, 'FY'] + [values.get(c) for c in columns]
        execute_query(sql, tuple(params), fetch=False)


# ── 利润表 API ──

@app.route("/api/stock/<code>/income")
def api_stock_income(code):
    rows = execute_query(
        "SELECT * FROM income_statements WHERE stock_code=%s ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC",
        (code,)
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
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
    updated = 0
    errors = []

    for s in stocks:
        code = s["code"]
        try:
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_ProfitStatement/stockid/{code}/ctrl/part/displaytype/0.phtml"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "gbk"
            all_years = _parse_sina_finance(resp.text, INCOME_ROW_MAP)

            existing = set()
            if mode == "incremental":
                for r in execute_query("SELECT fiscal_year FROM income_statements WHERE stock_code=%s", (code,)):
                    existing.add(r["fiscal_year"])

            for year, values in sorted((k, v) for k, v in all_years.items() if isinstance(k, int)):
                if mode == "incremental" and year in existing:
                    continue
                _upsert_finance(code, {year: values}, INCOME_COLUMNS, "income_statements")
                updated += 1
        except Exception as e:
            errors.append(f"{code}: {str(e)}")
        time.sleep(0.3)

    return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})


# ── 现金流量表 API ──

@app.route("/api/stock/<code>/cashflow")
def api_stock_cashflow(code):
    rows = execute_query(
        "SELECT * FROM cash_flows WHERE stock_code=%s ORDER BY fiscal_year DESC, FIELD(report_period,'FY','Q3','Q2','Q1') DESC",
        (code,)
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
    mode = request.get_json(silent=True).get("mode", "full") if request.is_json else "full"
    if request.args.get("mode"):
        mode = request.args["mode"]

    stocks = execute_query("SELECT code FROM stocks WHERE status='正常'")
    updated = 0
    errors = []

    for s in stocks:
        code = s["code"]
        try:
            url = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vFD_CashFlow/stockid/{code}/ctrl/part/displaytype/0.phtml"
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            resp.encoding = "gbk"
            all_years = _parse_sina_finance(resp.text, CASHFLOW_ROW_MAP)

            existing = set()
            if mode == "incremental":
                for r in execute_query("SELECT fiscal_year FROM cash_flows WHERE stock_code=%s", (code,)):
                    existing.add(r["fiscal_year"])

            for year, values in sorted((k, v) for k, v in all_years.items() if isinstance(k, int)):
                if mode == "incremental" and year in existing:
                    continue
                _upsert_finance(code, {year: values}, CASHFLOW_COLUMNS, "cash_flows")
                updated += 1
        except Exception as e:
            errors.append(f"{code}: {str(e)}")
        time.sleep(0.3)

    return jsonify({"success": True, "records_updated": updated, "stocks_processed": len(stocks), "mode": mode, "errors": errors[:5] if errors else []})


if __name__ == "__main__":
    print("股票分析系统 Web 服务启动: http://127.0.0.1:5002")
    try:
        _ensure_financials_columns()
        print("✓ 已确保 custom_financials 表结构完整")
    except Exception as e:
        print(f"⚠ 表结构检查异常: {e}")
    app.run(host="127.0.0.1", port=5002, debug=True)
