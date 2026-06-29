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
        return jsonify(stock)
    return jsonify({"error": "未找到该股票"}), 404


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
    rows = execute_query(
        "SELECT fiscal_year, net_profit, dividend_amount, dividend_per_share, ex_date "
        "FROM dividends WHERE stock_code = %s ORDER BY fiscal_year",
        (code,)
    )
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

@app.route("/api/update-financials", methods=["POST"])
def api_update_financials():
    """从东方财富拉取年报财务数据并存入 custom_financials 表
    mode: full=全量拉取, incremental=增量拉取(仅更新无数据的年份)
    """
    mode = "full"
    if request.is_json:
        mode = request.get_json(silent=True).get("mode", "full")
    if request.args.get("mode"):
        mode = request.args["mode"]

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
                       f"&filter=(SECURITY_CODE=%22{code}%22)(REPORT_TYPE=%22%E5%B9%B4%E6%8A%A5%22)"
                       "&pageSize=200&sortColumns=REPORT_DATE&sortTypes=-1")
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                data = resp.json()
                if not data.get("success"):
                    errors.append(f"{code}: API返回失败")
                    continue

                records = data["result"]["data"]
                # 按 fiscal_year 分组，同一财年取 NOTICE_DATE 更晚的
                year_best = {}
                for item in records:
                    rd = item.get("REPORT_DATE", "")
                    if not rd:
                        continue
                    year = int(rd[:4])
                    notice = item.get("NOTICE_DATE", "")
                    if year not in year_best or notice > year_best[year][0]:
                        year_best[year] = (notice, item)

                # 增量模式：查询已有年份
                existing_years = set()
                if mode == "incremental":
                    existing = execute_query(
                        "SELECT fiscal_year FROM custom_financials WHERE stock_code=%s", (code,)
                    )
                    existing_years = {r["fiscal_year"] for r in existing}

                for year, (_, item) in year_best.items():
                    if mode == "incremental" and year in existing_years:
                        continue

                    total_share = item.get("TOTAL_SHARE")
                    total_shares_val = round(total_share / 1e8, 4) if total_share else None

                    execute_query(
                        """INSERT INTO custom_financials
                        (stock_code, fiscal_year, total_revenue, operate_profit, parent_profit,
                         deducted_profit, operate_cashflow, roe, deducted_roe, roic,
                         total_assets, total_equity, total_shares, audit_opinion)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON DUPLICATE KEY UPDATE
                         total_revenue=VALUES(total_revenue), operate_profit=VALUES(operate_profit),
                         parent_profit=VALUES(parent_profit), deducted_profit=VALUES(deducted_profit),
                         operate_cashflow=VALUES(operate_cashflow), roe=VALUES(roe),
                         deducted_roe=VALUES(deducted_roe), roic=VALUES(roic),
                         total_assets=VALUES(total_assets), total_equity=VALUES(total_equity),
                         total_shares=VALUES(total_shares), audit_opinion=VALUES(audit_opinion)""",
                        (
                            code, year,
                            round(item["TOTALOPERATEREVE"] / 1e8, 4) if item.get("TOTALOPERATEREVE") else None,
                            round(item.get("OPERATE_PROFIT_PK", 0) / 1e8, 4) if item.get("OPERATE_PROFIT_PK") else None,
                            round(item["PARENTNETPROFIT"] / 1e8, 4) if item.get("PARENTNETPROFIT") else None,
                            round(item["KCFJCXSYJLR"] / 1e8, 4) if item.get("KCFJCXSYJLR") else None,
                            round(item.get("NETCASH_OPERATE_PK", 0) / 1e8, 4) if item.get("NETCASH_OPERATE_PK") else None,
                            round(item["ROEJQ"], 4) if item.get("ROEJQ") else None,
                            round(item["ROEKCJQ"], 4) if item.get("ROEKCJQ") else None,
                            round(item["ROIC"], 4) if item.get("ROIC") else None,
                            round(item.get("TOTAL_ASSETS_PK", 0) / 1e8, 4) if item.get("TOTAL_ASSETS_PK") else None,
                            round(item.get("TOTAL_EQUITY_PK", 0) / 1e8, 4) if item.get("TOTAL_EQUITY_PK") else None,
                            total_shares_val,
                            None,  # audit_opinion not available in this API
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
    """查询指定股票的多年财务数据，含后端计算的派生指标"""
    from_year = request.args.get("from_year", 2016, type=int)
    to_year = request.args.get("to_year", 2025, type=int)

    rows = execute_query(
        """SELECT fiscal_year, total_revenue, operate_profit, parent_profit, deducted_profit,
                  operate_cashflow, roe, deducted_roe, roic, total_assets, total_equity,
                  total_shares, audit_opinion
           FROM custom_financials
           WHERE stock_code = %s AND fiscal_year BETWEEN %s AND %s
           ORDER BY fiscal_year DESC""",
        (code, from_year, to_year)
    )

    result = []
    for r in rows:
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

        # 派生指标
        core_profit_rate = round(op / rev * 100, 2) if rev else None
        net_profit_rate = round(pp / rev * 100, 2) if rev else None
        cashflow_to_profit = round(ocf / pp * 100, 2) if pp and pp > 0 else None

        result.append({
            "fiscal_year": r["fiscal_year"],
            "total_revenue": rev,
            "operate_profit": op,
            "parent_profit": pp,
            "deducted_profit": dp,
            "operate_cashflow": ocf,
            "roe": roe_v,
            "deducted_roe": droe_v,
            "roic": roic_v,
            "total_assets": ta,
            "total_equity": te,
            "total_shares": ts,
            "audit_opinion": r.get("audit_opinion"),
            "core_profit_rate": core_profit_rate,
            "net_profit_rate": net_profit_rate,
            "cashflow_to_profit": cashflow_to_profit,
        })
    return jsonify(result)


if __name__ == "__main__":
    print("股票分析系统 Web 服务启动: http://127.0.0.1:5002")
    app.run(host="127.0.0.1", port=5002, debug=False)
