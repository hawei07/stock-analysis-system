"""Investor interaction routes and sync jobs."""

import html as html_lib
import json
import re
import threading
import time
from datetime import datetime

import requests
from flask import jsonify

from services.background_jobs import (
    create_job,
    fail_job,
    finish_job,
    start_job,
    update_job,
)

_irm_sync_lock = threading.Lock()
_irm_sync_running = False
_irm_sync_started_at = None
_irm_sync_finished_at = None
_irm_sync_job_id = None
_irm_sync_last_result = {
    "status": "idle",
    "message": "\u5c1a\u672a\u6293\u53d6\u4e92\u52a8\u6613",
    "updated_at": None,
    "scope": None,
    "total": 0,
    "inserted": 0,
    "skipped": 0,
    "errors": [],
}


def register_irm_routes(app, deps):
    Stock = deps["Stock"]
    execute_query = deps["execute_query"]
    get_connection = deps["get_connection"]
    _as_list = deps["as_list"]
    _money_yuan = deps["money_yuan"]
    _to_float = deps["to_float"]

    def _irm_source_label(value):
        return {
            "2": "APP",
            "4": "网站",
            "5": "公众号",
            "6": "网站",
        }.get(str(value or ""), "网站")


    def _irm_dt(value):
        n = _to_float(value)
        if not n:
            return None
        try:
            return datetime.fromtimestamp(n / 1000).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


    def _sse_dt(value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.strptime(text, "%Y年%m月%d日 %H:%M").strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None


    def _first_item(value):
        if isinstance(value, list) and value:
            return value[0]
        return value or ""


    def _irm_headers():
        return {
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://irm.cninfo.com.cn/",
            "Origin": "https://irm.cninfo.com.cn",
        }


    def _irm_request_json(session, method, url, **kwargs):
        resp = session.request(method, url, headers=_irm_headers(), timeout=12, **kwargs)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        return resp.json()


    def _clean_html_text(value):
        text = re.sub(r"<script[\s\S]*?</script>", " ", str(value or ""), flags=re.I)
        text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


    def _irm_fetch_org_id(session, code):
        payload = _irm_request_json(
            session,
            "POST",
            "https://irm.cninfo.com.cn/newircs/index/queryKeyboardInfo",
            params={"_t": str(int(time.time()))},
            data={"keyWord": code},
        )
        candidates = _as_list(payload.get("data"))
        exact = [item for item in candidates if str(item.get("stockCode") or "") == code]
        candidates = exact or candidates
        for item in candidates:
            secid = str(item.get("secid") or "")
            if secid.startswith("gssz"):
                return secid
        return str(candidates[0].get("secid") or "") if candidates else ""


    def _insert_irm_row(row_data):
        execute_query(
            """INSERT INTO irm_interactions (
                stock_code, stock_name, org_id, question_id, answer_id, industry, board_type,
                question, answer, questioner, answerer, source, question_time, answer_time,
                update_time, praise_count, favorite_count, forward_count, original_url, raw_json
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            ) ON DUPLICATE KEY UPDATE
                answer=VALUES(answer),
                answer_id=VALUES(answer_id),
                answerer=VALUES(answerer),
                answer_time=VALUES(answer_time),
                update_time=VALUES(update_time),
                praise_count=VALUES(praise_count),
                favorite_count=VALUES(favorite_count),
                forward_count=VALUES(forward_count),
                raw_json=VALUES(raw_json)""",
            (
                row_data.get("stock_code"),
                row_data.get("stock_name"),
                row_data.get("org_id"),
                row_data.get("question_id"),
                row_data.get("answer_id"),
                row_data.get("industry"),
                row_data.get("board_type"),
                row_data.get("question") or "",
                row_data.get("answer") or "",
                row_data.get("questioner"),
                row_data.get("answerer"),
                row_data.get("source"),
                row_data.get("question_time"),
                row_data.get("answer_time"),
                row_data.get("update_time"),
                int(_money_yuan(row_data.get("praise_count")) or 0),
                int(_money_yuan(row_data.get("favorite_count")) or 0),
                int(_money_yuan(row_data.get("forward_count")) or 0),
                row_data.get("original_url"),
                json.dumps(row_data.get("raw") or {}, ensure_ascii=False),
            ),
            fetch=False,
        )


    def _sync_cninfo_irm_stock(code, stock_name=None, max_pages=2, stop_on_duplicate=True):
        session = requests.Session()
        org_id = _irm_fetch_org_id(session, code)
        if not org_id:
            return {"code": code, "inserted": 0, "skipped": 0, "message": "未找到互动易组织代码"}

        existing_rows = execute_query("SELECT question_id FROM irm_interactions WHERE stock_code=%s", (code,))
        existing_ids = {str(row["question_id"]) for row in existing_rows}
        inserted = 0
        skipped = 0
        duplicate_seen = 0
        total_rows = 0
        total_pages = max_pages

        for page_num in range(1, max_pages + 1):
            payload = _irm_request_json(
                session,
                "POST",
                "https://irm.cninfo.com.cn/newircs/company/question",
                params={
                    "_t": str(int(time.time())),
                    "stockcode": code,
                    "orgId": org_id,
                    "pageSize": "20",
                    "pageNum": str(page_num),
                    "keyWord": "",
                    "startDay": "",
                    "endDay": "",
                },
            )
            total_pages = min(int(payload.get("totalPage") or max_pages), max_pages)
            rows = _as_list(payload.get("rows"))
            if not rows:
                break

            for row in rows:
                total_rows += 1
                question_id = str(row.get("indexId") or "")
                answer = str(row.get("attachedContent") or "").strip()
                if not question_id or not answer:
                    skipped += 1
                    continue
                if question_id in existing_ids:
                    duplicate_seen += 1
                    skipped += 1
                    continue

                _insert_irm_row({
                    "stock_code": code,
                    "stock_name": row.get("companyShortName") or stock_name,
                    "org_id": org_id,
                    "question_id": question_id,
                    "answer_id": row.get("attachedId"),
                    "industry": _first_item(row.get("trade")),
                    "board_type": _first_item(row.get("boardType")),
                    "question": row.get("mainContent") or "",
                    "answer": answer,
                    "questioner": row.get("authorName") or row.get("author"),
                    "answerer": row.get("attachedAuthor"),
                    "source": _irm_source_label(row.get("pubClient")),
                    "question_time": _irm_dt(row.get("pubDate")),
                    "answer_time": _irm_dt(row.get("attachedPubDate")) or _irm_dt(row.get("updateDate")),
                    "update_time": _irm_dt(row.get("updateDate")),
                    "praise_count": row.get("praiseCount"),
                    "favorite_count": row.get("favoriteCount"),
                    "forward_count": row.get("forwardCount"),
                    "original_url": f"https://irm.cninfo.com.cn/ircs/question/questionDetail?questionId={question_id}",
                    "raw": row,
                })
                existing_ids.add(question_id)
                inserted += 1

            if page_num >= total_pages:
                break
            if stop_on_duplicate and duplicate_seen and inserted == 0:
                break

        return {
            "code": code,
            "org_id": org_id,
            "inserted": inserted,
            "skipped": skipped,
            "total_rows": total_rows,
        }


    def _parse_sse_items(html_text, code, stock_name, com_id):
        items = re.findall(r'<div class="m_feed_item"[\s\S]*?(?=<div class="m_feed_item"|$)', html_text or "")
        parsed = []
        for item in items:
            if "answer_ico" not in item:
                continue
            mid = re.search(r'id="item-(\d+)"', item)
            if not mid:
                continue
            txt_blocks = re.findall(r'<div class="m_feed_txt"[^>]*>([\s\S]*?)</div>', item)
            if len(txt_blocks) < 2:
                continue
            question = _clean_html_text(txt_blocks[0])
            answer = _clean_html_text(txt_blocks[1])
            if not question or not answer:
                continue
            question = re.sub(rf"^:?{re.escape(stock_name or '')}\({code}\)", "", question).strip()
            question = re.sub(rf"^:?.*?\({code}\)", "", question).strip()
            author_blocks = re.findall(r'<div class="m_feed_face">([\s\S]*?)</div>', item)
            questioner = _clean_html_text(author_blocks[0]) if author_blocks else None
            answerer = _clean_html_text(author_blocks[1]) if len(author_blocks) > 1 else stock_name
            time_blocks = re.findall(r'<div class="m_feed_from"[^>]*>[\s\S]*?<span>([\s\S]*?)</span>', item)
            question_time = _sse_dt(_clean_html_text(time_blocks[0])) if time_blocks else None
            answer_time = _sse_dt(_clean_html_text(time_blocks[1])) if len(time_blocks) > 1 else None
            source_match = re.findall(r'<div class="m_feed_from"[^>]*>[\s\S]*?<a href="javascript:;">([\s\S]*?)</a>', item)
            parsed.append({
                "stock_code": code,
                "stock_name": stock_name,
                "org_id": str(com_id),
                "question_id": f"sse-{mid.group(1)}",
                "answer_id": f"sse-answer-{mid.group(1)}",
                "industry": None,
                "board_type": "SSE",
                "question": question,
                "answer": answer,
                "questioner": questioner,
                "answerer": answerer,
                "source": _clean_html_text(source_match[-1]) if source_match else "上证e互动",
                "question_time": question_time,
                "answer_time": answer_time,
                "update_time": answer_time or question_time,
                "praise_count": 0,
                "favorite_count": 0,
                "forward_count": 0,
                "original_url": f"https://sns.sseinfo.com/company.do?stockcode={code}",
                "raw": {"item_id": mid.group(1), "platform": "sse"},
            })
        return parsed


    def _sync_sse_irm_stock(code, stock_name=None, max_pages=2, stop_on_duplicate=True):
        session = requests.Session()
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://sns.sseinfo.com/qa.do"}
        resp = session.post(
            "https://sns.sseinfo.com/ajax/getCompany.do",
            data={"data": code},
            headers=headers,
            timeout=12,
        )
        resp.encoding = "utf-8"
        resp.raise_for_status()
        com_id = (resp.text or "").strip()
        if not com_id:
            return {"code": code, "inserted": 0, "skipped": 0, "message": "未找到上证 e 互动公司代码"}

        existing_rows = execute_query("SELECT question_id FROM irm_interactions WHERE stock_code=%s", (code,))
        existing_ids = {str(row["question_id"]) for row in existing_rows}
        inserted = 0
        skipped = 0
        duplicate_seen = 0
        total_rows = 0

        for page_num in range(1, max_pages + 1):
            resp = session.post(
                "https://sns.sseinfo.com/getNewDataFullText.do",
                data={"sdate": "", "edate": "", "keyword": "", "type": "1", "page": str(page_num), "comId": com_id},
                headers=headers,
                timeout=12,
            )
            resp.encoding = "utf-8"
            resp.raise_for_status()
            rows = _parse_sse_items(resp.text, code, stock_name, com_id)
            if not rows:
                if page_num == 1:
                    total_rows += len(re.findall(r'<div class="m_feed_item"', resp.text or ""))
                break
            total_rows += len(rows)
            for row in rows:
                question_id = row["question_id"]
                if question_id in existing_ids:
                    duplicate_seen += 1
                    skipped += 1
                    continue
                _insert_irm_row(row)
                existing_ids.add(question_id)
                inserted += 1
            if stop_on_duplicate and duplicate_seen and inserted == 0:
                break
        return {
            "code": code,
            "org_id": str(com_id),
            "inserted": inserted,
            "skipped": skipped,
            "total_rows": total_rows,
        }


    def _sync_irm_stock(code, stock_name=None, market=None, max_pages=2, stop_on_duplicate=True):
        market = (market or "").upper()
        if market == "SH":
            return _sync_sse_irm_stock(code, stock_name, max_pages=max_pages, stop_on_duplicate=stop_on_duplicate)
        return _sync_cninfo_irm_stock(code, stock_name, max_pages=max_pages, stop_on_duplicate=stop_on_duplicate)


    def _sync_irm_all_background(max_pages=2, job_id=None):
        global _irm_sync_running, _irm_sync_started_at, _irm_sync_finished_at, _irm_sync_job_id, _irm_sync_last_result
        total = 0
        inserted = 0
        skipped = 0
        errors = []
        with _irm_sync_lock:
            if _irm_sync_running:
                return
            _irm_sync_running = True
            _irm_sync_started_at = datetime.now().isoformat(timespec="seconds")
            _irm_sync_finished_at = None
            _irm_sync_job_id = job_id
            _irm_sync_last_result = {
                "status": "running",
                "message": "正在抓取互动易",
                "updated_at": _irm_sync_started_at,
                "scope": "all",
                "job_id": job_id,
                "total": 0,
                "inserted": 0,
                "skipped": 0,
                "errors": [],
            }
        if job_id:
            start_job(execute_query, job_id, "正在抓取互动易")

        try:
            stocks = execute_query("SELECT code, name, market FROM stocks WHERE status='正常' ORDER BY display_order IS NULL, display_order, code")
            eligible_total = len([stock for stock in stocks if (stock.get("market") or "").upper() in {"SZ", "SH"}])
            if job_id:
                update_job(execute_query, job_id, progress_total=eligible_total, message=f"准备抓取 {eligible_total} 只股票的互动易")
            for stock in stocks:
                code = stock["code"]
                market = (stock.get("market") or "").upper()
                if market not in {"SZ", "SH"}:
                    skipped += 1
                    continue
                total += 1
                if job_id:
                    update_job(
                        execute_query,
                        job_id,
                        progress_current=total - 1,
                        progress_total=eligible_total,
                        message=f"正在抓取 {code} {stock.get('name') or ''}".strip(),
                        result={"total": total, "inserted": inserted, "skipped": skipped, "errors": errors[:20]},
                    )
                try:
                    result = _sync_irm_stock(code, stock.get("name"), market=market, max_pages=max_pages)
                    inserted += result.get("inserted", 0)
                    skipped += result.get("skipped", 0)
                except Exception as e:
                    errors.append(f"{code}: {e}")
                if job_id:
                    update_job(
                        execute_query,
                        job_id,
                        progress_current=total,
                        progress_total=eligible_total,
                        message=f"已抓取 {total}/{eligible_total}，新增 {inserted} 条",
                        result={"total": total, "inserted": inserted, "skipped": skipped, "errors": errors[:20]},
                    )
                time.sleep(0.25)
        except Exception as e:
            errors.append(str(e))
        finally:
            finished_at = datetime.now().isoformat(timespec="seconds")
            status = "done" if not errors else "partial"
            message = f"互动易抓取完成，新增 {inserted} 条" if not errors else f"互动易抓取部分完成，新增 {inserted} 条，失败 {len(errors)} 只"
            result_payload = {
                "scope": "all",
                "total": total,
                "inserted": inserted,
                "skipped": skipped,
                "errors": errors[:20],
            }
            with _irm_sync_lock:
                _irm_sync_running = False
                _irm_sync_finished_at = finished_at
                _irm_sync_last_result = {
                    "status": status,
                    "message": message,
                    "updated_at": finished_at,
                    "scope": "all",
                    "job_id": job_id,
                    "total": total,
                    "inserted": inserted,
                    "skipped": skipped,
                    "errors": errors[:20],
                }
            if job_id:
                if errors and total == 0:
                    fail_job(execute_query, job_id, "\n".join(errors[:20]), message=message, result=result_payload)
                else:
                    finish_job(execute_query, job_id, status=status, message=message, result=result_payload)


    def _irm_status():
        with _irm_sync_lock:
            return {
                **_irm_sync_last_result,
                "running": _irm_sync_running,
                "started_at": _irm_sync_started_at,
                "finished_at": _irm_sync_finished_at,
                "job_id": _irm_sync_job_id,
            }


    @app.route("/api/irm/status")
    def api_irm_status():
        return jsonify(_irm_status())


    @app.route("/api/irm/sync", methods=["POST"])
    def api_irm_sync_all():
        if _irm_status().get("running"):
            return jsonify({"ok": True, "already_running": True, **_irm_status()})
        job_id = create_job(
            get_connection,
            execute_query,
            "irm_sync_all",
            title="互动易全量增量抓取",
            message="等待开始抓取互动易",
        )
        thread = threading.Thread(target=_sync_irm_all_background, kwargs={"max_pages": 2, "job_id": job_id}, daemon=True)
        thread.start()
        return jsonify({**_irm_status(), "ok": True, "started": True, "job_id": job_id})


    @app.route("/api/stock/<code>/irm")
    def api_stock_irm(code):
        stock = Stock.get_by_code(code)
        if not stock:
            return jsonify({"error": "未找到该股票"}), 404
        rows = execute_query(
            """SELECT question_id, answer_id, stock_code, stock_name, industry, question, answer,
                      questioner, answerer, source, question_time, answer_time, update_time,
                      praise_count, favorite_count, forward_count, original_url
               FROM irm_interactions
               WHERE stock_code=%s
               ORDER BY COALESCE(answer_time, update_time, question_time) DESC, id DESC
               LIMIT 200""",
            (code,),
        )
        items = []
        for row in rows:
            items.append({
                **row,
                "question_time": str(row["question_time"]) if row.get("question_time") else None,
                "answer_time": str(row["answer_time"]) if row.get("answer_time") else None,
                "update_time": str(row["update_time"]) if row.get("update_time") else None,
            })
        return jsonify({
            "source": "互动问答",
            "items": items,
            "sync": _irm_status(),
            "supported": (stock.get("market") or "").upper() in {"SZ", "SH"},
        })


    @app.route("/api/stock/<code>/irm/sync", methods=["POST"])
    def api_stock_irm_sync(code):
        stock = Stock.get_by_code(code)
        if not stock:
            return jsonify({"error": "未找到该股票"}), 404
        market = (stock.get("market") or "").upper()
        if market not in {"SZ", "SH"}:
            return jsonify({"ok": True, "inserted": 0, "skipped": 0, "message": "互动问答暂只支持沪深股票"})
        try:
            result = _sync_irm_stock(code, stock.get("name"), market=market, max_pages=5, stop_on_duplicate=False)
            return jsonify({"ok": True, **result})
        except Exception as e:
            return jsonify({"error": "互动易抓取失败: " + str(e)}), 502


    # ==================== 数据更新 API ====================
