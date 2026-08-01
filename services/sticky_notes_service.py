"""Sticky note storage and inline image helpers."""

import base64
import json
import os
import re
import uuid


def load_notes(json_path, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    if not os.path.exists(json_path):
        return {}
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_notes(notes, json_path, data_dir):
    os.makedirs(data_dir, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def extract_images(content, note_id, images_dir):
    os.makedirs(images_dir, exist_ok=True)

    def replace_base64(match):
        data_url = match.group(0)
        header, b64data = data_url.split(",", 1)
        ext = "png"
        if "image/jpeg" in header:
            ext = "jpg"
        elif "image/gif" in header:
            ext = "gif"
        elif "image/webp" in header:
            ext = "webp"
        filename = f"{note_id}_{uuid.uuid4().hex[:8]}.{ext}"
        filepath = os.path.join(images_dir, filename)
        try:
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(b64data))
            return f"/data/images/{filename}"
        except Exception:
            return data_url

    return re.sub(r"data:image/[^;]+;base64,[a-zA-Z0-9+/=]+", replace_base64, content)


def cleanup_images(note, images_dir):
    paths = re.findall(r"/data/images/([^\"')\s]+)", note.get("content", ""))
    for fname in paths:
        fpath = os.path.join(images_dir, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass
