"""Sticky notes and Munger chat routes."""

from datetime import datetime

from flask import jsonify, request, send_from_directory


def register_notes_chat_routes(app, deps):
    get_chat_history = deps["get_chat_history"]
    chat_send = deps["chat_send"]
    clear_chat_history = deps["clear_chat_history"]
    delete_chat_msg = deps["delete_chat_msg"]
    load_notes = deps["load_notes"]
    save_notes = deps["save_notes"]
    extract_images = deps["extract_images"]
    cleanup_images = deps["cleanup_images"]
    images_dir = deps["images_dir"]

    @app.route("/api/stock/<code>/munger-chat", methods=["GET", "POST", "DELETE"])
    def api_munger_chat(code):
        """对话芒格 API"""
        if request.method == "GET":
            return jsonify(get_chat_history(code))
        if request.method == "DELETE":
            msg_id = request.args.get("msg_id", type=int)
            if msg_id:
                ok = delete_chat_msg(msg_id)
                return jsonify({"ok": ok})
            n = clear_chat_history(code)
            return jsonify({"ok": True, "deleted": n})

        data = request.get_json(force=True)
        message = data.get("message", "").strip()
        if not message:
            return jsonify({"error": "empty message"}), 400
        result = chat_send(code, message)
        return jsonify(result)

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
