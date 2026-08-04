"""Shareholder routes for stock detail pages."""

import requests
from flask import jsonify, request

from services.background_jobs import start_endpoint_stock_batch


def register_shareholder_routes(app, deps):
    Stock = deps["Stock"]
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _get_update_stocks = deps["get_update_stocks"]
    _schedule_auto_cloud_backup = deps.get("schedule_auto_cloud_backup")
    _ensure_shareholders_table = deps["ensure_shareholders_table"]
    _eastmoney_secu_code = deps["eastmoney_secu_code"]
    _eastmoney_web_code = deps["eastmoney_web_code"]
    _as_list = deps["as_list"]
    _date_only = deps["date_only"]
    _money_yuan = deps["money_yuan"]
    _to_float = deps["to_float"]

    def _quarter_label(date_str):
        if not date_str:
            return ""
        year = date_str[:4]
        month_day = date_str[5:10]
        quarter_map = {
            "03-31": "Q1",
            "06-30": "Q2",
            "09-30": "Q3",
            "12-31": "Q4",
        }
        return f"{year}-{quarter_map.get(month_day, date_str[5:])}"


    def _change_type(value):
        text = str(value or "").strip()
        if text == "新进":
            return "new"
        if text in {"不变", "持平"}:
            return "unchanged"
        if text in {"增加", "增持"}:
            return "increase"
        if text in {"减少", "减持"}:
            return "decrease"
        n = _to_float(text)
        if n is None:
            return ""
        if n > 0:
            return "increase"
        if n < 0:
            return "decrease"
        return "unchanged"


    def _fetch_shareholder_periods_from_eastmoney(code, stock):
        secu_code = _eastmoney_secu_code(code, stock.get("market"))
        rows = []
        source = "东方财富数据中心 十大股东"

        try:
            params = {
                "sortColumns": "END_DATE,HOLDER_RANK",
                "sortTypes": "-1,1",
                "pageSize": "1000",
                "pageNumber": "1",
                "reportName": "RPT_F10_EH_FREEHOLDERS",
                "columns": "ALL",
                "source": "WEB",
                "client": "WEB",
                "filter": f'(SECURITY_CODE="{code}")',
            }
            resp = requests.get(
                "https://datacenter-web.eastmoney.com/api/data/v1/get",
                params=params,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://data.eastmoney.com/gdfx/HoldingAnalyse.html",
                },
                timeout=12,
            )
            resp.raise_for_status()
            payload = resp.json()
            result = payload.get("result") or {}
            rows = _as_list(result.get("data"))
            pages = int(result.get("pages") or 1)
            for page_number in range(2, min(pages, 5) + 1):
                params["pageNumber"] = str(page_number)
                page_resp = requests.get(
                    "https://datacenter-web.eastmoney.com/api/data/v1/get",
                    params=params,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://data.eastmoney.com/gdfx/HoldingAnalyse.html",
                    },
                    timeout=12,
                )
                page_resp.raise_for_status()
                page_payload = page_resp.json()
                rows.extend(_as_list((page_payload.get("result") or {}).get("data")))
        except Exception as e:
            app.logger.warning("datacenter shareholder fetch failed for %s: %s", code, e)

        rows_by_date = {}
        for row in rows:
            date = _date_only(row.get("END_DATE"))
            if not date:
                continue
            rank = int(_money_yuan(row.get("HOLDER_RANK")) or 0)
            if rank < 1 or rank > 10:
                continue
            change_label = row.get("HOLDNUM_CHANGE_NAME") or row.get("HOLD_CHANGE") or row.get("HOLD_NUM_CHANGE")
            change_num = _to_float(row.get("XZCHANGE"))
            if change_num is None:
                change_num = _to_float(row.get("HOLD_NUM_CHANGE"))
            rows_by_date.setdefault(date, []).append({
                "rank": rank,
                "name": row.get("HOLDER_NAME") or "",
                "shares_type": row.get("SHARES_TYPE") or "",
                "hold_num": _money_yuan(row.get("HOLD_NUM")),
                "hold_ratio": _to_float(row.get("HOLD_RATIO")) or _to_float(row.get("HOLD_NUM_RATIO")) or _to_float(row.get("FREE_HOLDNUM_RATIO")),
                "change": change_num if change_num is not None else change_label,
                "change_ratio": _to_float(row.get("CHANGE_RATIO")),
                "change_type": _change_type(change_label),
            })

        report_dates = {}
        if not rows_by_date:
            web_code = _eastmoney_web_code(code, stock.get("market"))
            try:
                resp = requests.get(
                    "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax",
                    params={"code": secu_code},
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={web_code}&type=web",
                    },
                    timeout=12,
                )
                resp.raise_for_status()
                payload = resp.json()
                report_dates = {
                    _date_only(row.get("END_DATE")): str(row.get("IS_REPORTDATE") or "") == "1"
                    for row in _as_list(payload.get("sdgd_date"))
                    if _date_only(row.get("END_DATE"))
                }
                source = "东方财富 F10 股东研究"
                for date in list(report_dates.keys())[:40]:
                    detail_resp = requests.get(
                        "https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageSDGD",
                        params={"code": web_code, "date": date},
                        headers={
                            "User-Agent": "Mozilla/5.0",
                            "Referer": f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/Index?code={web_code}&type=web",
                        },
                        timeout=8,
                    )
                    detail_resp.raise_for_status()
                    detail_payload = detail_resp.json()
                    for row in _as_list(detail_payload.get("sdgd")):
                        rank = int(_money_yuan(row.get("HOLDER_RANK")) or 0)
                        if rank < 1 or rank > 10:
                            continue
                        change_label = row.get("HOLD_NUM_CHANGE")
                        rows_by_date.setdefault(date, []).append({
                            "rank": rank,
                            "name": row.get("HOLDER_NAME") or "",
                            "shares_type": row.get("SHARES_TYPE") or "",
                            "hold_num": _money_yuan(row.get("HOLD_NUM")),
                            "hold_ratio": _to_float(row.get("HOLD_NUM_RATIO")),
                            "change": row.get("HOLD_NUM_CHANGE"),
                            "change_ratio": _to_float(row.get("CHANGE_RATIO")),
                            "change_type": _change_type(change_label),
                        })
            except Exception as e:
                raise RuntimeError("股东数据获取失败: " + str(e)) from e

        return _build_shareholder_periods(rows_by_date, report_dates), source


    def _build_shareholder_periods(rows_by_date, report_dates=None):
        report_dates = report_dates or {}
        periods = []
        for date in sorted(rows_by_date.keys(), reverse=True):
            holders = sorted(rows_by_date[date], key=lambda item: item["rank"])
            top_ratio = sum(float(item["hold_ratio"] or 0) for item in holders)
            top_shares = sum(float(item["hold_num"] or 0) for item in holders)
            total_shares = None
            for item in holders:
                if item["hold_num"] and item["hold_ratio"] and item["hold_ratio"] > 0:
                    total_shares = item["hold_num"] / (item["hold_ratio"] / 100)
                    break
            periods.append({
                "date": date,
                "label": _quarter_label(date),
                "year": date[:4],
                "month_day": date[5:10],
                "is_report_date": report_dates.get(date, True),
                "total_shares": round(total_shares, 2) if total_shares else None,
                "top10_shares": round(top_shares, 2),
                "top10_ratio": round(top_ratio, 2),
                "holders": holders,
            })
        return periods


    def _load_shareholder_periods_from_db(code):
        _ensure_shareholders_table()
        rows = execute_query(
            """SELECT report_date, holder_rank, holder_name, shares_type, hold_num, hold_ratio,
                      hold_change_label, hold_change_num, change_ratio, change_type,
                      is_report_date, source, fetched_at
               FROM stock_shareholders
               WHERE stock_code = %s
               ORDER BY report_date DESC, holder_rank ASC""",
            (code,),
        )
        rows_by_date = {}
        report_dates = {}
        source = None
        latest_fetched_at = None
        for row in rows:
            date = row["report_date"].strftime("%Y-%m-%d") if hasattr(row["report_date"], "strftime") else str(row["report_date"])
            fetched_at = row.get("fetched_at")
            if fetched_at and (latest_fetched_at is None or fetched_at > latest_fetched_at):
                latest_fetched_at = fetched_at
            if row.get("source") and not source:
                source = row["source"]
            report_dates[date] = bool(row.get("is_report_date"))
            change_num = row.get("hold_change_num")
            change = float(change_num) if change_num is not None else row.get("hold_change_label")
            rows_by_date.setdefault(date, []).append({
                "rank": int(row["holder_rank"]),
                "name": row.get("holder_name") or "",
                "shares_type": row.get("shares_type") or "",
                "hold_num": float(row["hold_num"]) if row.get("hold_num") is not None else None,
                "hold_ratio": float(row["hold_ratio"]) if row.get("hold_ratio") is not None else None,
                "change": change,
                "change_ratio": float(row["change_ratio"]) if row.get("change_ratio") is not None else None,
                "change_type": row.get("change_type") or "",
            })
        fetched_at_text = latest_fetched_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(latest_fetched_at, "strftime") else latest_fetched_at
        return _build_shareholder_periods(rows_by_date, report_dates), source, fetched_at_text


    def _save_shareholder_periods_to_db(code, periods, source):
        if not periods:
            return 0
        _ensure_shareholders_table()
        values = []
        for period in periods:
            date = period.get("date")
            if not date:
                continue
            for holder in period.get("holders") or []:
                rank = int(holder.get("rank") or 0)
                name = holder.get("name") or ""
                if rank < 1 or rank > 10 or not name:
                    continue
                change = holder.get("change")
                change_num = change if isinstance(change, (int, float)) else _to_float(change)
                values.append((
                    code,
                    date,
                    rank,
                    name,
                    holder.get("shares_type") or None,
                    holder.get("hold_num"),
                    holder.get("hold_ratio"),
                    None if change_num is not None else (str(change) if change not in (None, "") else None),
                    change_num,
                    holder.get("change_ratio"),
                    holder.get("change_type") or None,
                    1 if period.get("is_report_date", True) else 0,
                    source,
                ))
        if not values:
            return 0

        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.executemany(
                """INSERT INTO stock_shareholders (
                       stock_code, report_date, holder_rank, holder_name, shares_type,
                       hold_num, hold_ratio, hold_change_label, hold_change_num,
                       change_ratio, change_type, is_report_date, source, fetched_at
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                   ON DUPLICATE KEY UPDATE
                       holder_name = VALUES(holder_name),
                       shares_type = VALUES(shares_type),
                       hold_num = VALUES(hold_num),
                       hold_ratio = VALUES(hold_ratio),
                       hold_change_label = VALUES(hold_change_label),
                       hold_change_num = VALUES(hold_change_num),
                       change_ratio = VALUES(change_ratio),
                       change_type = VALUES(change_type),
                       is_report_date = VALUES(is_report_date),
                       source = VALUES(source),
                       fetched_at = NOW(),
                       updated_at = CURRENT_TIMESTAMP""",
                values,
            )
            conn.commit()
            return len(values)
        finally:
            cursor.close()
            conn.close()


    @app.route("/api/stock/<code>/shareholders")
    def api_stock_shareholders(code):
        stock = Stock.get_by_code(code)
        if not stock:
            return jsonify({"error": "未找到该股票"}), 404
        if (stock.get("market") or "").upper() == "HK":
            return jsonify({
                "source": "港股暂不支持 A 股前十大股东口径",
                "periods": [],
            })

        refresh = request.args.get("refresh") in {"1", "true", "yes"}
        if not refresh:
            periods, source, fetched_at = _load_shareholder_periods_from_db(code)
            if periods:
                return jsonify({
                    "source": f"本地缓存 · {source or '前十大股东'}",
                    "cached": True,
                    "fetched_at": fetched_at,
                    "periods": periods,
                })

        try:
            periods, source = _fetch_shareholder_periods_from_eastmoney(code, stock)
        except Exception as e:
            periods, source, fetched_at = _load_shareholder_periods_from_db(code)
            if periods:
                return jsonify({
                    "source": f"本地缓存 · 外部刷新失败: {e}",
                    "cached": True,
                    "fetched_at": fetched_at,
                    "periods": periods,
                })
            return jsonify({"error": str(e)}), 502

        saved_count = _save_shareholder_periods_to_db(code, periods, source)

        return jsonify({
            "source": source,
            "cached": False,
            "saved_count": saved_count,
            "periods": periods,
        })


    @app.route("/api/update-shareholders", methods=["POST"])
    def api_update_shareholders():
        payload = request.get_json(silent=True) if request.is_json else {}
        stocks = _get_update_stocks(payload, include_name_market=True)
        if len(stocks) > 1:
            return jsonify(start_endpoint_stock_batch(
                app,
                get_connection,
                execute_query,
                "update_shareholders",
                "股东数据更新",
                payload,
                stocks,
                api_update_shareholders,
                "/api/update-shareholders",
                on_finish=lambda result: _schedule_auto_cloud_backup and _schedule_auto_cloud_backup("shareholders-update"),
            ))

        saved_count = 0
        processed = 0
        errors = []
        for stock in stocks:
            code = stock["code"]
            processed += 1
            if (stock.get("market") or "").upper() == "HK":
                continue
            try:
                periods, source = _fetch_shareholder_periods_from_eastmoney(code, stock)
                saved_count += _save_shareholder_periods_to_db(code, periods, source)
            except Exception as e:
                errors.append(f"{code}: {e}")

        return jsonify({
            "success": len(errors) == 0 or saved_count > 0,
            "stocks_processed": processed,
            "saved_count": saved_count,
            "records_updated": saved_count,
            "errors": errors[:5] if errors else [],
        })


    # ==================== 互动易 API ====================
