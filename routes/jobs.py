"""Background job status routes."""

from flask import jsonify, request

from services.background_jobs import (
    add_job_log,
    ensure_background_jobs_table,
    get_job,
    latest_job,
    list_job_logs,
    list_jobs,
    request_cancel_job,
    response_payload,
)


def register_job_routes(app, deps):
    execute_query = deps["execute_query"]
    retry_endpoints = deps.get("retry_endpoints") or {}
    ensure_background_jobs_table(execute_query)

    def _failed_stock_codes(job_id):
        logs = list_job_logs(execute_query, job_id, limit=1000)
        codes = []
        seen = set()
        for log in logs:
            if log.get("level") != "error":
                continue
            code = log.get("stock_code")
            if code and code not in seen:
                seen.add(code)
                codes.append(code)
        return codes

    @app.route("/api/jobs")
    def api_jobs():
        limit = request.args.get("limit", 50, type=int)
        job_type = request.args.get("job_type") or None
        status = request.args.get("status") or None
        return jsonify({"ok": True, "jobs": list_jobs(execute_query, limit=limit, job_type=job_type, status=status)})

    @app.route("/api/jobs/latest")
    def api_latest_job():
        job_type = request.args.get("job_type") or None
        job = latest_job(execute_query, job_type=job_type)
        return jsonify({"ok": True, "job": job})

    @app.route("/api/jobs/<int:job_id>")
    def api_job_detail(job_id):
        job = get_job(execute_query, job_id)
        if not job:
            return jsonify({"ok": False, "error": "未找到后台任务"}), 404
        return jsonify({"ok": True, "job": job})

    @app.route("/api/jobs/<int:job_id>/logs")
    def api_job_logs(job_id):
        job = get_job(execute_query, job_id)
        if not job:
            return jsonify({"ok": False, "error": "未找到后台任务"}), 404
        limit = request.args.get("limit", 200, type=int)
        return jsonify({"ok": True, "job_id": job_id, "logs": list_job_logs(execute_query, job_id, limit=limit)})

    @app.route("/api/jobs/<int:job_id>/cancel", methods=["POST"])
    def api_cancel_job(job_id):
        job = request_cancel_job(execute_query, job_id)
        if not job:
            return jsonify({"ok": False, "error": "未找到后台任务"}), 404
        return jsonify({"ok": True, "job": job})

    @app.route("/api/jobs/<int:job_id>/retry", methods=["POST"])
    def api_retry_job(job_id):
        job = get_job(execute_query, job_id)
        if not job:
            return jsonify({"ok": False, "error": "未找到后台任务"}), 404
        if job.get("status") not in {"partial", "failed", "cancelled"}:
            return jsonify({"ok": False, "error": "只有部分完成、失败或已取消的任务可以重试"}), 409

        endpoint_path = retry_endpoints.get(job.get("job_type"))
        if not endpoint_path:
            return jsonify({"ok": False, "error": f"任务类型 {job.get('job_type')} 暂不支持重试"}), 400

        body = request.get_json(silent=True) if request.is_json else {}
        failed_only = body.get("failed_only", True)
        payload = dict(job.get("request") or {})
        payload["retry_of"] = job_id
        payload["background"] = True
        payload["force"] = bool(body.get("force", False))

        failed_codes = _failed_stock_codes(job_id)
        if failed_only and failed_codes and job.get("job_type") != "irm_sync_all":
            payload.pop("code", None)
            payload["codes"] = failed_codes

        with app.test_client() as client:
            retry_response = client.post(endpoint_path, json=payload)
        result = response_payload(retry_response)
        if retry_response.status_code >= 400:
            return jsonify({
                "ok": False,
                "error": result.get("error") or result.get("message") or "重试启动失败",
                "retry_response": result,
            }), retry_response.status_code

        new_job_id = result.get("job_id")
        if new_job_id:
            add_job_log(
                execute_query,
                job_id,
                f"已创建重试任务 #{new_job_id}",
                detail={"new_job_id": new_job_id, "failed_only": failed_only, "failed_codes": failed_codes},
            )
        return jsonify({
            "ok": True,
            "retried": True,
            "original_job_id": job_id,
            "new_job_id": new_job_id,
            "failed_only": failed_only,
            "failed_codes": failed_codes,
            "result": result,
        })
