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


@app.route("/api/stock", methods=["POST"])
def api_add_stock():
    data = request.get_json()
    required = ["code", "name", "market"]
    for f in required:
        if f not in data or not data[f]:
            return jsonify({"error": f"缺少必填字段: {f}"}), 400
    if data["market"] not in ("SH", "SZ", "BJ"):
        return jsonify({"error": "市场必须是 SH/SZ/BJ"}), 400

    try:
        Stock.add(
            code=data["code"],
            name=data["name"],
            market=data["market"],
            industry=data.get("industry"),
            list_date=data.get("list_date"),
            status=data.get("status", "正常"),
        )
        return jsonify({"success": True, "message": "添加成功"}), 201
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
    """从东方财富和新浪财经更新所有股票的分红和净利润数据"""
    try:
        stocks = execute_query("SELECT code, name FROM stocks WHERE status='正常'")
        updated_count = 0
        errors = []

        for s in stocks:
            code = s["code"]
            # 1. 获取净利润
            net_profits = {}
            total_share = 0
            try:
                url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                       "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                       f"&filter=(SECURITY_CODE=%22{code}%22)&pageSize=20")
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

            # 2. 获取分红方案
            yearly_dividends = {}
            try:
                url2 = f"https://vip.stock.finance.sina.com.cn/corp/go.php/vISSUE_ShareBonus/stockid/{code}.phtml"
                resp2 = requests.get(url2, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
                resp2.encoding = 'gbk'
                text = resp2.text
                pattern = r'(\d{4}-\d{2}-\d{2})\s*</td>\s*<[^>]*>\s*(\d+)\s*</td>\s*<[^>]*>\s*(\d+)\s*</td>\s*<[^>]*>\s*([\d.]+)\s*</td>.*?实施'
                matches = re.findall(pattern, text, re.DOTALL)
                for m in matches:
                    year = int(m[0][:4])
                    dividend_per_10 = float(m[3])
                    if dividend_per_10 > 0 and total_share > 0:
                        if year not in yearly_dividends:
                            yearly_dividends[year] = 0
                        yearly_dividends[year] += dividend_per_10 * total_share / 10 / 1e8
            except Exception as e:
                errors.append(f"{code}: 分红获取失败 - {str(e)}")

            # 3. 更新数据库
            for year in net_profits:
                np_val = net_profits[year]
                da_val = yearly_dividends.get(year)
                if da_val is not None:
                    execute_query(
                        "INSERT INTO dividends (stock_code, fiscal_year, net_profit, dividend_amount) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE net_profit=VALUES(net_profit), dividend_amount=VALUES(dividend_amount)",
                        (code, year, np_val, da_val),
                        commit=True
                    )
                    updated_count += 1
            time.sleep(0.3)

        return jsonify({
            "success": True,
            "message": f"已更新 {updated_count} 条分红记录",
            "stocks_processed": len(stocks),
            "errors": errors[:5] if errors else []
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    print("股票分析系统 Web 服务启动: http://127.0.0.1:5002")
    app.run(host="127.0.0.1", port=5002, debug=False)
