"""Valuation and K-line routes for stock detail pages."""

import time
from datetime import datetime

from flask import jsonify, request

from services.http_client import get_json
from services.providers.tencent import fq_kline, quote_text


def register_market_chart_routes(app, deps):
    execute_query = deps["execute_query"]
    _quote_symbol = deps["quote_symbol"]
    _valuation_cache = deps["valuation_cache"]
    _valuation_cache_lock = deps["valuation_cache_lock"]
    VALUATION_CACHE_SECONDS = deps["valuation_cache_seconds"]

    @app.route("/api/stock/<code>/valuation")
    def api_stock_valuation(code):
        """PE-TTM 历史 + 股价 + 分位点"""
        days = request.args.get("days", 1095, type=int) or 1095
        days = max(365, min(days, 36500))
        cache_key = (code, days)
        with _valuation_cache_lock:
            cached = _valuation_cache.get(cache_key)
            if cached and time.time() - cached["time"] < VALUATION_CACHE_SECONDS:
                return jsonify({**cached["data"], "cached": True})

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _get_json(url, timeout=12):
                return get_json(url, timeout=timeout)

            report_type_map = {
                "%E5%B9%B4%E6%8A%A5": "FY",
                "%E4%B8%80%E5%AD%A3%E6%8A%A5": "Q1",
                "%E5%8D%8A%E5%B9%B4%E6%8A%A5": "Q2",
                "%E4%B8%89%E5%AD%A3%E6%8A%A5": "Q3",
            }
            finance_rows_by_type = {}
            # 1. 获取所有财报季度的归母净利润 + 总股本，用于 TTM PE 计算
            # PE = 市值 / TTM归母净利润（比EPSJB更精确，避免股本变动和四舍五入误差）
            eps_records = []  # [(report_date, report_type, fiscal_year, parent_eps), ...]
            finance_urls = {}
            for report_type in report_type_map.keys():
                url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
                       "?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL"
                       f"&filter=(SECURITY_CODE=%22{code}%22)(REPORT_TYPE=%22{report_type}%22)"
                       "&pageSize=50&sortColumns=REPORT_DATE&sortTypes=-1")
                finance_urls[report_type] = url
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_map = {executor.submit(_get_json, url, 15): report_type for report_type, url in finance_urls.items()}
                for future in as_completed(future_map):
                    report_type = future_map[future]
                    try:
                        data = future.result()
                        if data.get("success"):
                            rows = data["result"]["data"]
                            finance_rows_by_type[report_type] = rows
                            for item in rows:
                                rd = item.get("REPORT_DATE", "")
                                parent_np = item.get("PARENTNETPROFIT")  # 归母净利润
                                total_share = item.get("TOTAL_SHARE")    # 总股本
                                fy = int(item.get("REPORT_YEAR")) if item.get("REPORT_YEAR") else (int(rd[:4]) if rd[:4].isdigit() else 0)
                                if rd and parent_np and total_share and float(parent_np) > 0 and int(total_share) > 0 and fy:
                                    parent_eps = float(parent_np) / int(total_share)
                                    eps_records.append((rd[:10], report_type, fy, parent_eps))
                    except Exception:
                        pass
            eps_records.sort(key=lambda x: x[0])  # 按日期排序

            # 构建 TTM EPS 函数：给定日期，计算最近12个月每股收益
            # TTM = 最新年报EPS - 去年同期累计EPS + 今年最新累计EPS
            # 季报在财季结束后45天才实际披露，因此延迟生效
            def calc_ttm_eps(target_date, records):
                """target_date: 'YYYY-MM-DD'"""
                from datetime import datetime, timedelta
                target_dt = datetime.strptime(target_date, "%Y-%m-%d")
            
                # 找到 target_date 当天或之前的最新有效财务报告（考虑披露延迟）
                latest = None
                for r in records:
                    rd_dt = datetime.strptime(r[0], "%Y-%m-%d")
                    # 年报: 次年4月30日前披露 → 从5月1日起生效
                    # 半年报: 8月31日前披露 → 从9月1日起生效
                    # Q3季报: 10月31日前披露 → 从11月1日起生效
                    # Q1季报: 4月30日前披露 → 从5月1日起生效
                    _, rtype, fy, _ = r
                    if "%E5%B9%B4" in rtype:  # 年报
                        effective = datetime(fy + 1, 5, 1)
                    elif "%E5%8D%8A%E5%B9%B4" in rtype:  # 半年报
                        effective = datetime(fy, 9, 1)
                    elif "%E4%B8%89%E5%AD%A3" in rtype:  # Q3季报
                        effective = datetime(fy, 11, 1)
                    else:  # Q1季报
                        effective = datetime(fy, 5, 1)
                
                    if effective <= target_dt:
                        latest = r
                    else:
                        break
                if not latest:
                    return None
            
                rd, rtype, fy, eps = latest
            
                # 年报：直接用作 TTM
                if "%E5%B9%B4" in rtype:  # 年报
                    # 检查是否有更新的季报在同一财年之后
                    # 年报日期通常是最新的，直接返回
                    return eps
            
                # 找到最近的一份年报
                latest_annual_eps = None
                for r in records:
                    if "%E5%B9%B4" in r[1] and r[0] <= target_date:
                        latest_annual_eps = r[3]
            
                if not latest_annual_eps:
                    return eps  # 无年报时直接用累计EPS
            
                # 找到去年同期的累计EPS
                # 同一 REPORT_TYPE，fiscal_year - 1
                last_year_same = None
                for r in records:
                    if r[1] == rtype and r[2] == fy - 1:
                        last_year_same = r[3]
                        break
            
                if last_year_same is None:
                    return latest_annual_eps
            
                # TTM = 去年年报EPS - 去年同期EPS + 今年最新累计EPS
                ttm = latest_annual_eps - last_year_same + eps
                return max(ttm, 0) if ttm > 0 else None

            # 2. 获取股价（前复权）—— 分批拉取以覆盖更长历史
            market = "sh" if code.startswith(("6", "5", "9")) else "sz"
            symbol = f"{market}{code}"
            current_year = datetime.now().year
            history_years = max(1, int(days / 365) + 1)
            start_year = current_year - history_years
            max_batches = 3 if days <= 1825 else (5 if days <= 3650 else 10)
            price_data = []
            try:
                # 第一段：最近数据
                urls = [f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,640,qfq"]
                for y in range(current_year - 1, start_year - 1, -2):
                    urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,{max(start_year, y-1)}-01-01,{y}-12-31,640,qfq")
                seen = set()
                with ThreadPoolExecutor(max_workers=min(6, len(urls[:max_batches]))) as executor:
                    futures = [executor.submit(_get_json, u, 10) for u in urls[:max_batches]]
                    results = []
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception:
                            pass
                for d2 in results:
                    try:
                        stock_data = d2.get("data", {})
                        if isinstance(stock_data, dict):
                            stock_data = stock_data.get(symbol, {})
                            raw = stock_data.get("day") or stock_data.get("qfqday") or []
                        else:
                            raw = []
                        for row in raw:
                            if row[0] not in seen:
                                seen.add(row[0])
                                price_data.append({"date": row[0], "close": float(row[2])})
                    except Exception:
                        pass
                price_data.sort(key=lambda x: x["date"])
            except Exception:
                pass

            # 股息率需要未复权价格，否则未复权每股分红除以前复权老股价会显著失真。
            raw_price_data = []
            try:
                raw_urls = [f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,,,640"]
                for y in range(current_year - 1, start_year - 1, -2):
                    raw_urls.append(f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={symbol},day,{max(start_year, y-1)}-01-01,{y}-12-31,640")
                seen_raw = set()
                with ThreadPoolExecutor(max_workers=min(6, len(raw_urls[:max_batches]))) as executor:
                    futures = [executor.submit(_get_json, u, 10) for u in raw_urls[:max_batches]]
                    results = []
                    for future in as_completed(futures):
                        try:
                            results.append(future.result())
                        except Exception:
                            pass
                for d2 in results:
                    try:
                        stock_data = d2.get("data", {})
                        if isinstance(stock_data, dict):
                            stock_data = stock_data.get(symbol, {})
                            raw = stock_data.get("day") or []
                        else:
                            raw = []
                        for row in raw:
                            if row[0] not in seen_raw:
                                seen_raw.add(row[0])
                                raw_price_data.append({"date": row[0], "close": float(row[2])})
                    except Exception:
                        pass
                raw_price_data.sort(key=lambda x: x["date"])
            except Exception:
                pass

            # 3. 计算每日 PE-TTM：前复权股价 / TTM EPS
            pe_data = []
            if price_data and eps_records:
                for p in price_data:
                    ttm_eps = calc_ttm_eps(p["date"], eps_records)
                    if ttm_eps and ttm_eps > 0:
                        pe = round(p["close"] / ttm_eps, 2)
                        if 0 < pe < 9999:
                            pe_data.append({"date": p["date"], "pe": pe})

            # 4. 计算分位点
            pe_values = [p["pe"] for p in pe_data if p["pe"] > 0]
            pe_values.sort()
            if pe_values:
                n = len(pe_values)
                p80 = pe_values[int(n * 0.8)] if n > 0 else None
                p50 = pe_values[int(n * 0.5)] if n > 0 else None
                p20 = pe_values[int(n * 0.2)] if n > 0 else None
                # 当前 PE 取最新日期值，非排序后最大值
                cur_pe = pe_data[-1]["pe"] if pe_data else None
                cur_pct = round(sum(1 for v in pe_values if v <= cur_pe) / n * 100, 2) if cur_pe and n > 0 else None
            else:
                p80 = p50 = p20 = cur_pe = cur_pct = None

            # 5. 获取实时 PE-TTM 和 PB（qt.gtimg.cn，比计算值更精确）
            realtime_pe = None
            realtime_pb = None
            try:
                prefix = "sh" if code.startswith(("6", "5", "9")) else "sz"
                text = quote_text(f"{prefix}{code}", timeout=8)
                if text.startswith("v_"):
                    parts = text.split("~")
                    if len(parts) >= 40:
                        pe_str = parts[39].strip()
                        if pe_str and pe_str not in ("", "-"):
                            realtime_pe = float(pe_str)
                    # 腾讯行情 parts[43] = 市净率 PB
                    if len(parts) >= 44:
                        pb_str = parts[43].strip()
                        if pb_str and pb_str not in ("", "-"):
                            try:
                                realtime_pb = float(pb_str)
                            except ValueError:
                                pass
            except Exception:
                pass

            # ==================== PB 估值（扣商誉）====================
            # PB = 前复权股价 / 每股净资产（扣商誉）
            # 每股净资产 = (归母股东权益 - 商誉) / 总股本
            # 数据源：balance_sheets.parent_equity + balance_sheets.goodwill + 东方财富 TOTAL_SHARE
            # 披露延迟规则与 PE 一致：年报→次年5/1，半年报→9/1，三季报→11/1，一季报→5/1
            # ==================== 股息率估值 ====================
            # 股息率 = 最近已知年度每股分红 / 当日前复权收盘价。
            # 分红数据来自本地 dividends 表；ex_date 缺失时使用次年 7 月 1 日作为保守生效日。
            dividend_yield_data = []
            current_dividend_yield = None
            try:
                div_rows = execute_query(
                    """SELECT fiscal_year, dividend_per_share, ex_date
                       FROM dividends
                       WHERE stock_code=%s AND dividend_per_share IS NOT NULL AND dividend_per_share > 0
                       ORDER BY fiscal_year ASC""",
                    (code,)
                )
                div_records = []
                for r in div_rows:
                    dps = float(r["dividend_per_share"]) if r["dividend_per_share"] is not None else 0
                    if dps <= 0:
                        continue
                    if r.get("ex_date"):
                        effective = datetime.strptime(str(r["ex_date"])[:10], "%Y-%m-%d")
                    else:
                        effective = datetime(int(r["fiscal_year"]) + 1, 7, 1)
                    div_records.append((effective, dps))
                div_records.sort(key=lambda x: x[0])

                dividend_prices = raw_price_data or price_data
                if dividend_prices and div_records:
                    for p in dividend_prices:
                        p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                        latest_dps = None
                        for effective, dps in div_records:
                            if effective <= p_date:
                                latest_dps = dps
                            else:
                                break
                        if latest_dps and p["close"] > 0:
                            dy = round(latest_dps / p["close"] * 100, 4)
                            if 0 < dy < 100:
                                dividend_yield_data.append({"date": p["date"], "dividend_yield": dy})
                    if dividend_yield_data:
                        current_dividend_yield = dividend_yield_data[-1]["dividend_yield"]
            except Exception:
                pass

            pb_data = []
            try:
                # 获取东方财富财报数据（含 TOTAL_SHARE），同时匹配 balance_sheets 的归母权益和商誉
                # 从 balance_sheets 加载归母权益和商誉
                bs_rows = execute_query(
                    "SELECT fiscal_year, report_period, parent_equity, goodwill "
                    "FROM balance_sheets WHERE stock_code=%s AND parent_equity IS NOT NULL "
                    "ORDER BY fiscal_year, FIELD(report_period,'Q1','Q2','Q3','FY')",
                    (code,)
                )
                bs_map = {}  # {(fiscal_year, report_period): (parent_equity_亿, goodwill_亿)}
                for r in bs_rows:
                    pe_val = float(r["parent_equity"]) if r["parent_equity"] is not None else None
                    gw_val = float(r["goodwill"]) if r["goodwill"] is not None else 0.0
                    if pe_val is not None:
                        bs_map[(r["fiscal_year"], r["report_period"])] = (pe_val, gw_val)

                # 从东方财富获取 total_share 并匹配 balance_sheets 构建 每股净资产
                bv_records = []  # [(report_date, effective_date, bvps), ...]
                for report_type, rows in finance_rows_by_type.items():
                    for item in rows:
                        rd = item.get("REPORT_DATE", "")
                        total_share = item.get("TOTAL_SHARE")
                        fy = int(item.get("REPORT_YEAR")) if item.get("REPORT_YEAR") else (int(rd[:4]) if rd[:4].isdigit() else 0)
                        rp = report_type_map.get(report_type, "FY")
                        if not rd or not total_share or int(total_share) <= 0 or not fy:
                            continue
                        bs_key = (fy, rp)
                        if bs_key in bs_map:
                            parent_eq_亿, goodwill_亿 = bs_map[bs_key]
                            net_equity = (parent_eq_亿 - goodwill_亿) * 1e8
                            if net_equity > 0:
                                bvps = net_equity / int(total_share)
                                if rp == "FY":
                                    effective = datetime(fy + 1, 5, 1)
                                elif rp == "Q2":
                                    effective = datetime(fy, 9, 1)
                                elif rp == "Q3":
                                    effective = datetime(fy, 11, 1)
                                else:
                                    effective = datetime(fy, 5, 1)
                                bv_records.append((rd[:10], effective, bvps))

                bv_records.sort(key=lambda x: x[1])  # 按生效日期排序

                # 对每个交易日，取最新生效的 每股净资产，计算 PB
                if price_data and bv_records:
                    bv_idx = 0
                    for p in price_data:
                        p_date = datetime.strptime(p["date"], "%Y-%m-%d")
                        # 找到最新的生效 每股净资产
                        latest_bvps = None
                        for bv in bv_records:
                            if bv[1] <= p_date:
                                latest_bvps = bv[2]
                            else:
                                break
                        if latest_bvps and latest_bvps > 0:
                            pb = round(p["close"] / latest_bvps, 2)
                            if 0 < pb < 9999:
                                pb_data.append({"date": p["date"], "pb": pb})
            except Exception as e:
                import traceback
                print(f"[PB计算异常] {code}: {e}")
                traceback.print_exc()
                pass

            # PB 分位点
            pb_values = [p["pb"] for p in pb_data if p["pb"] > 0]
            pb_values.sort()
            if pb_values:
                n_pb = len(pb_values)
                p80_pb = pb_values[int(n_pb * 0.8)] if n_pb > 0 else None
                p50_pb = pb_values[int(n_pb * 0.5)] if n_pb > 0 else None
                p20_pb = pb_values[int(n_pb * 0.2)] if n_pb > 0 else None
                cur_pb = pb_data[-1]["pb"] if pb_data else None
                cur_pb_pct = round(sum(1 for v in pb_values if v <= cur_pb) / n_pb * 100, 2) if cur_pb and n_pb > 0 else None
                max_pb = max(pb_values)
                min_pb = min(pb_values)
                avg_pb = round(sum(pb_values) / n_pb, 2)
            else:
                p80_pb = p50_pb = p20_pb = cur_pb = cur_pb_pct = max_pb = min_pb = avg_pb = None

            cutoff_date = datetime.fromtimestamp(time.time() - days * 86400).strftime("%Y-%m-%d")
            if days <= 3650:
                pe_data = [item for item in pe_data if item["date"] >= cutoff_date]
                pb_data = [item for item in pb_data if item["date"] >= cutoff_date]
                price_data = [item for item in price_data if item["date"] >= cutoff_date]
                dividend_yield_data = [item for item in dividend_yield_data if item["date"] >= cutoff_date]

            payload = {
                "pe_data": pe_data,
                "pb_data": pb_data,
                "price_data": price_data,
                "current_pe": cur_pe,
                "current_pe_pct": cur_pct,
                "p80_pe": p80, "p50_pe": p50, "p20_pe": p20,
                "max_pe": max(pe_values) if pe_values else None,
                "min_pe": min(pe_values) if pe_values else None,
                "avg_pe": round(sum(pe_values) / len(pe_values), 2) if pe_values else None,
                "realtime_pe": realtime_pe,
                "current_pb": cur_pb,
                "current_pb_pct": cur_pb_pct,
                "p80_pb": p80_pb, "p50_pb": p50_pb, "p20_pb": p20_pb,
                "max_pb": max_pb,
                "min_pb": min_pb,
                "avg_pb": avg_pb,
                "realtime_pb": realtime_pb,
                "dividend_yield_data": dividend_yield_data,
                "current_dividend_yield": current_dividend_yield,
                "cached": False,
            }
            with _valuation_cache_lock:
                _valuation_cache[cache_key] = {"time": time.time(), "data": payload}
            return jsonify(payload)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # ==================== K线图 API ====================

    @app.route("/api/stock/<code>/kline")
    def api_stock_kline(code):
        """获取股票K线数据（腾讯API，前复权）"""
        days = request.args.get("days", 365, type=int)
        period = request.args.get("period", "day")
        if period not in {"day", "week", "month", "quarter", "year"}:
            period = "day"
        symbol = _quote_symbol(code)

        def row_to_item(row):
            volume = float(row[5]) if len(row) > 5 else 0
            close = float(row[2])
            return {
                "date": row[0],
                "open": float(row[1]),
                "close": close,
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": volume,
                "amount": round(volume * close * 100, 2),
            }

        def period_key(date_str):
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
            if period == "week":
                iso_year, iso_week, _ = dt.isocalendar()
                return (iso_year, iso_week)
            if period == "month":
                return (dt.year, dt.month)
            if period == "quarter":
                return (dt.year, (dt.month - 1) // 3 + 1)
            return (dt.year,)

        def aggregate_items(items):
            if period == "day":
                return items
            groups = []
            current_key = None
            current = None
            for item in items:
                key = period_key(item["date"])
                if key != current_key:
                    if current:
                        groups.append(current)
                    current_key = key
                    current = {
                        "date": item["date"],
                        "open": item["open"],
                        "close": item["close"],
                        "high": item["high"],
                        "low": item["low"],
                        "volume": item["volume"],
                        "amount": item["amount"],
                    }
                    continue
                current["date"] = item["date"]
                current["close"] = item["close"]
                current["high"] = max(current["high"], item["high"])
                current["low"] = min(current["low"], item["low"])
                current["volume"] += item["volume"]
                current["amount"] += item["amount"]
            if current:
                groups.append(current)
            for item in groups:
                item["volume"] = round(item["volume"], 2)
                item["amount"] = round(item["amount"], 2)
            return groups

        try:
            data = fq_kline(symbol, count=days, timeout=10)
            stock_data = data.get("data", {}).get(symbol, {})
            raw = stock_data.get("day") or stock_data.get("qfqday") or []
            result = aggregate_items([row_to_item(row) for row in raw])
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500


    # ==================== 利润表 & 现金流量表 API（数据源：新浪财经） ====================

    # 利润表行映射
