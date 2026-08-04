"""Basic stock detail, search, CRUD, and stats routes."""

import re

import requests
from flask import jsonify, request

from services.stock_delete_service import delete_stock_sticky_notes, delete_stock_with_related_data


def register_stock_basic_routes(app, deps):
    Stock = deps["Stock"]
    get_connection = deps["get_connection"]
    execute_query = deps["execute_query"]
    quote_symbol = deps["quote_symbol"]
    normalize_stock_code = deps["normalize_stock_code"]
    lookup_hk_stock_info = deps["lookup_hk_stock_info"]
    fetch_stock_industry = deps["fetch_stock_industry"]
    load_notes = deps["load_notes"]
    save_notes = deps["save_notes"]
    cleanup_images = deps["cleanup_images"]

    @app.route("/api/stock/<code>")
    def api_stock_detail(code):
        stock = Stock.get_by_code(code)
        if stock:
            # 确保日期字段可json序列化
            if stock.get("list_date"):
                stock["list_date"] = str(stock["list_date"])
            stock["created_at"] = str(stock["created_at"]) if stock.get("created_at") else None
            stock["updated_at"] = str(stock["updated_at"]) if stock.get("updated_at") else None

            # 获取实时行情：股价、PE(TTM)、PB、市值
            realtime = {"price": None, "pe_ttm": None, "pb": None, "market_cap": None}
            try:
                url = f"https://qt.gtimg.cn/q={quote_symbol(code, stock.get('market'))}"
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
                    if len(parts) >= 44:
                        pb_str = parts[43].strip()
                        if pb_str and pb_str != "-":
                            try:
                                realtime["pb"] = float(pb_str)
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
        keyword = normalize_stock_code(request.args.get("keyword", "").strip())
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
        if re.fullmatch(r"\d{1,5}", keyword):
            hk = lookup_hk_stock_info(keyword)
            if hk:
                return jsonify([hk])
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
                market = {"0": "SZ", "1": "SH", "116": "HK"}.get(str(mkt), "SH")
                if code and name:
                    results.append({"code": normalize_stock_code(code) if market == "HK" else code, "name": name, "market": market})
        except Exception:
            pass
        return jsonify(results)


    @app.route("/api/stock-info/<code>")
    def api_stock_info(code):
        code = normalize_stock_code(code)
        if re.fullmatch(r"\d{5}", code):
            hk = lookup_hk_stock_info(code)
            if hk:
                return jsonify(hk)
            return jsonify({"error": f"未找到港股代码 {code} 的信息"}), 404
        """根据股票代码从东方财富获取名称和市场信息"""
        # 尝试上海和深圳两个市场
        markets_to_try = []
        if code.startswith(("6", "5", "9")):
            markets_to_try = [("1", "SH"), ("0", "SZ")]
        else:
            markets_to_try = [("0", "SZ"), ("1", "SH")]

        name = None
        market = None
        industry = None
        for sec_market, our_market in markets_to_try:
            try:
                url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={sec_market}.{code}&fields=f57,f58,f127,f300"
                resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
                data = resp.json()
                if data.get("data") and data["data"].get("f58"):
                    name = data["data"]["f58"]
                    market = our_market
                    industry = data["data"].get("f127")
                    break
            except Exception:
                continue

        if not name:
            return jsonify({"error": f"未找到股票代码 {code} 的信息"}), 404

        return jsonify({"code": code, "name": name, "market": market, "industry": industry})


    @app.route("/api/stock", methods=["POST"])
    def api_add_stock():
        data = request.get_json()
        code = normalize_stock_code(data.get("code", "").strip())
        if not code:
            return jsonify({"error": "请输入股票代码"}), 400

        existing = Stock.get_by_code(code)
        if existing:
            return jsonify({"error": f"股票代码 {code} 已存在"}), 409

        # 如果没传名称或市场，自动从东方财富获取
        name = data.get("name", "").strip()
        market = data.get("market", "").strip()
        if not name or not market:
            if re.fullmatch(r"\d{5}", code):
                hk = lookup_hk_stock_info(code)
                if hk:
                    name = name or hk["name"]
                    market = market or hk["market"]
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

        if market and market not in ("SH", "SZ", "BJ", "HK"):
            return jsonify({"error": "市场必须是 SH/SZ/BJ/HK"}), 400

        industry = data.get("industry") or fetch_stock_industry(code, market or "SH")
        try:
            Stock.add(
                code=code,
                name=name,
                market=market or "SH",
                industry=industry,
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
        code = normalize_stock_code(code)
        try:
            result = delete_stock_with_related_data(get_connection, code)
            if result.get("deleted_stock"):
                result["sticky_json_deleted"] = delete_stock_sticky_notes(load_notes, save_notes, cleanup_images, code)
                return jsonify({"success": True, "message": "删除成功，相关数据已清理", **result})
            return jsonify({"error": "未找到该股票"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 400


    @app.route("/api/stats")
    def api_stats():
        all_stocks = Stock.get_all(page=1, page_size=1000)
        data = all_stocks["data"]
        markets = {"SH": 0, "SZ": 0, "BJ": 0, "HK": 0}
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

