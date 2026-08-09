"""Sticky notes and Munger chat routes."""

import json
from datetime import datetime

from flask import Response, jsonify, request, send_from_directory, stream_with_context


def register_notes_chat_routes(app, deps):
    get_chat_history = deps["get_chat_history"]
    chat_send = deps["chat_send"]
    chat_stream = deps.get("chat_stream")
    chat_regenerate = deps.get("chat_regenerate")
    clear_chat_history = deps["clear_chat_history"]
    delete_chat_msg = deps["delete_chat_msg"]
    delete_chat_turn = deps.get("delete_chat_turn")
    get_chat_memory = deps.get("get_chat_memory")
    clear_chat_memory = deps.get("clear_chat_memory")
    refresh_chat_memory = deps.get("refresh_chat_memory")
    get_chat_skills = deps.get("get_chat_skills", lambda: [])
    get_chat_models = deps.get("get_chat_models", lambda: [])
    get_chat_default_model = deps.get("get_chat_default_model", lambda: "")
    load_notes = deps["load_notes"]
    save_notes = deps["save_notes"]
    extract_images = deps["extract_images"]
    cleanup_images = deps["cleanup_images"]
    images_dir = deps["images_dir"]

    @app.route("/api/chat/skills", methods=["GET"])
    def api_chat_skills():
        return jsonify({"skills": get_chat_skills()})

    @app.route("/api/chat/models", methods=["GET"])
    def api_chat_models():
        # Only public, non-secret model metadata is returned. API keys remain
        # server-side in system_config.
        return jsonify({"models": [
            {key: value for key, value in model.items() if key not in {"api_key", "secret", "token"}}
            for model in get_chat_models()
            if model.get("enabled", True)
        ], "default_model": get_chat_default_model()})

    @app.route("/api/stock/<code>/munger-chat", methods=["GET", "POST", "DELETE"])
    def api_munger_chat(code):
        """对话芒格 API"""
        if request.method == "GET":
            return jsonify(get_chat_history(code))
        if request.method == "DELETE":
            msg_id = request.args.get("msg_id", type=int)
            if msg_id:
                ok = delete_chat_msg(code, msg_id)
                return jsonify({"ok": ok})
            turn_id = request.args.get("turn_id", "")
            if turn_id:
                deleted = delete_chat_turn(code, turn_id) if delete_chat_turn else 0
                return jsonify({"ok": bool(deleted), "deleted": deleted})
            n = clear_chat_history(code)
            return jsonify({"ok": True, "deleted": n})

        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "request body must be an object"}), 400
        raw_message = data.get("message", "")
        if not isinstance(raw_message, str):
            return jsonify({"error": "message must be text"}), 400
        message = raw_message.strip()
        if not message:
            return jsonify({"error": "empty message"}), 400
        result = chat_send(
            code,
            message,
            skill_id=data.get("skill_id"),
            model_id=data.get("model_id"),
            forecast_horizon=data.get("forecast_horizon", 3),
            forecast_scenario=data.get("forecast_scenario", "base"),
        )
        status = result.pop("_http_status", 200)
        return jsonify(result), status

    @app.route("/api/stock/<code>/munger-chat/stream", methods=["POST"])
    def api_munger_chat_stream(code):
        data = request.get_json(silent=True) or {}
        if not isinstance(data, dict):
            return jsonify({"error": "request body must be an object"}), 400
        raw_message = data.get("message", "")
        if not isinstance(raw_message, str):
            return jsonify({"error": "message must be text"}), 400
        message = raw_message.strip()
        turn_id = data.get("turn_id") or None
        is_regenerate = bool(data.get("regenerate"))
        skill_id = data.get("skill_id")
        model_id = data.get("model_id")
        forecast_horizon = data.get("forecast_horizon", 3)
        forecast_scenario = data.get("forecast_scenario", "base")
        if not chat_stream:
            return jsonify({"error": "streaming chat is unavailable"}), 503

        def events():
            for item in chat_stream(
                code,
                message,
                skill_id=skill_id,
                model_id=model_id,
                forecast_horizon=forecast_horizon,
                forecast_scenario=forecast_scenario,
                turn_id=turn_id,
                persist_user=not is_regenerate,
                replace_existing=is_regenerate,
            ):
                event = item.get("event", "message")
                payload = item.get("data") or {}
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"

        response = Response(stream_with_context(events()), mimetype="text/event-stream")
        response.headers["Cache-Control"] = "no-cache, no-transform"
        response.headers["X-Accel-Buffering"] = "no"
        response.headers["Connection"] = "keep-alive"
        return response

    @app.route("/api/stock/<code>/munger-chat/regenerate", methods=["POST"])
    def api_munger_chat_regenerate(code):
        data = request.get_json(silent=True) or {}
        turn_id = data.get("turn_id") if isinstance(data, dict) else None
        if not chat_regenerate:
            return jsonify({"error": "regeneration is unavailable"}), 503
        result = chat_regenerate(code, turn_id or "")
        status = result.pop("_http_status", 200)
        return jsonify(result), status

    @app.route("/api/stock/<code>/munger-chat/memory", methods=["GET", "POST", "DELETE"])
    def api_munger_chat_memory(code):
        if request.method == "GET":
            skill_id = request.args.get("skill_id") or None
            return jsonify({"ok": True, "memory": get_chat_memory(code, skill_id) if get_chat_memory else None})
        if request.method == "DELETE":
            if clear_chat_memory:
                clear_chat_memory(code, request.args.get("skill_id") or None)
            return jsonify({"ok": True})
        if not refresh_chat_memory:
            return jsonify({"error": "memory is unavailable"}), 503
        data = request.get_json(silent=True) or {}
        result = refresh_chat_memory(
            code,
            data.get("skill_id") if isinstance(data, dict) else None,
            data.get("model_id") if isinstance(data, dict) else None,
        )
        status = result.pop("_http_status", 200)
        return jsonify(result), status

    @app.route("/api/sticky-notes", methods=["GET", "POST"])
    def api_sticky_notes():
        if request.method == "GET":
            stock_code = request.args.get("stock_code", "")
            notes = load_notes()
            if stock_code:
                notes = [n for n in notes if n.get("stock_code") == stock_code or not n.get("stock_code")]
            notes.sort(key=lambda n: n.get("id", 0), reverse=True)
            return jsonify(notes)

        data = request.get_json(force=True)
        notes = load_notes()
        new_id = max([n.get("id", 0) for n in notes], default=0) + 1
        content = extract_images(data.get("content", ""), new_id)
        now = datetime.now().isoformat()
        note = {
            "id": new_id,
            "title": data.get("title", ""),
            "content": content,
            "stock_code": data.get("stock_code", "") or "",
            "created_at": now,
            "updated_at": now,
        }
        notes.append(note)
        save_notes(notes)
        return jsonify({"ok": True, "id": new_id})

    @app.route("/api/sticky-notes/<int:note_id>", methods=["PUT", "DELETE"])
    def api_sticky_note(note_id):
        if request.method == "PUT":
            data = request.get_json(force=True)
            notes = load_notes()
            for n in notes:
                if n.get("id") == note_id:
                    cleanup_images(n)
                    n["title"] = data.get("title", "")
                    n["content"] = extract_images(data.get("content", ""), note_id)
                    n["stock_code"] = data.get("stock_code", "") or ""
                    n["updated_at"] = datetime.now().isoformat()
                    save_notes(notes)
                    return jsonify({"ok": True})
            return jsonify({"error": "not found"}), 404

        notes = load_notes()
        for n in notes:
            if n.get("id") == note_id:
                cleanup_images(n)
                notes.remove(n)
                save_notes(notes)
                return jsonify({"ok": True})
        return jsonify({"error": "not found"}), 404

    @app.route("/data/images/<path:filename>")
    def serve_sticky_image(filename):
        return send_from_directory(images_dir, filename)
