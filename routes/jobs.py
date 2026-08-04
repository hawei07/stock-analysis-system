"""Background job status routes."""

from flask import jsonify, request

from services.background_jobs import (
    ensure_background_jobs_table,
    get_job,
    latest_job,
    list_job_logs,
    list_jobs,
    request_cancel_job,
)


def register_job_routes(app, deps):
    execute_query = deps["execute_query"]
    ensure_background_jobs_table(execute_query)

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
