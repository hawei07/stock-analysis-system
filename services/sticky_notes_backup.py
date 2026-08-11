"""Backup and restore helpers for sticky-note JSON and image attachments."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime


ARCHIVE_SUFFIX = ".files.zip"
STICKY_NOTES_MEMBER = "sticky_notes.json"
MANIFEST_MEMBER = "manifest.json"
IMAGES_PREFIX = "images/"
MAX_ARCHIVE_MEMBERS = 10000
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def archive_name_for_sql(sql_filename):
    """Return the sidecar archive name for a SQL backup filename."""
    filename = os.path.basename(str(sql_filename or ""))
    if not filename.lower().endswith(".sql"):
        raise ValueError("SQL backup filename is required")
    return filename[:-4] + ARCHIVE_SUFFIX


def _image_member_name(images_dir, path):
    relative = os.path.relpath(path, images_dir).replace(os.sep, "/")
    if relative in (".", "") or relative.startswith("../") or "/../" in relative:
        raise ValueError("Invalid sticky image path")
    return IMAGES_PREFIX + relative


def _iter_image_files(images_dir):
    if not os.path.isdir(images_dir):
        return
    for root, dirs, files in os.walk(images_dir):
        dirs[:] = sorted(name for name in dirs if not os.path.islink(os.path.join(root, name)))
        for name in sorted(files):
            path = os.path.join(root, name)
            if os.path.isfile(path) and not os.path.islink(path):
                yield path


def create_archive(notes_path, images_dir, archive_path):
    """Create a complete sticky-note snapshot and atomically publish it."""
    archive_path = os.path.abspath(archive_path)
    archive_parent = os.path.dirname(archive_path)
    os.makedirs(archive_parent, exist_ok=True)

    if os.path.exists(notes_path):
        with open(notes_path, "r", encoding="utf-8") as source:
            notes_text = source.read()
        notes = json.loads(notes_text)
    else:
        notes_text = "[]"
        notes = []
    if not isinstance(notes, (list, dict)):
        raise ValueError("sticky_notes.json must contain a JSON list or object")

    image_paths = list(_iter_image_files(images_dir) or [])
    manifest = {
        "format_version": 1,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes_count": len(notes),
        "images_count": len(image_paths),
    }

    fd, temporary_path = tempfile.mkstemp(
        prefix=".sticky_backup_",
        suffix=ARCHIVE_SUFFIX,
        dir=archive_parent,
    )
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                MANIFEST_MEMBER,
                json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"),
            )
            archive.writestr(STICKY_NOTES_MEMBER, notes_text.encode("utf-8"))
            for image_path in image_paths:
                archive.write(image_path, arcname=_image_member_name(images_dir, image_path))
        os.replace(temporary_path, archive_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)

    return {
        "archive": archive_path,
        "notes_count": len(notes),
        "images_count": len(image_paths),
        "size": os.path.getsize(archive_path),
    }


def _safe_member_name(name):
    normalized = str(name or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or ":" in normalized.split("/")[0]:
        raise ValueError("Invalid sticky backup member path")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("Invalid sticky backup member path")
    if normalized not in (MANIFEST_MEMBER, STICKY_NOTES_MEMBER) and not normalized.startswith(IMAGES_PREFIX):
        raise ValueError("Unexpected sticky backup member")
    if normalized.startswith(IMAGES_PREFIX) and normalized == IMAGES_PREFIX:
        raise ValueError("Invalid sticky image member")
    return normalized


def _validate_archive(archive_path):
    if not os.path.exists(archive_path):
        return {"available": False, "notes_count": None, "images_count": None}
    try:
        archive = zipfile.ZipFile(archive_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f"Invalid sticky backup archive: {exc}") from exc

    with archive:
        members = archive.infolist()
        if len(members) > MAX_ARCHIVE_MEMBERS:
            raise ValueError("Sticky backup contains too many files")
        total_size = 0
        names = set()
        image_count = 0
        for info in members:
            name = _safe_member_name(info.filename)
            if name in names:
                raise ValueError("Duplicate sticky backup member")
            names.add(name)
            if info.is_dir():
                raise ValueError("Directory entries are not allowed in sticky backup")
            # ZIP external attributes can mark a member as a symbolic link.
            if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError("Symbolic links are not allowed in sticky backup")
            total_size += info.file_size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("Sticky backup is too large")
            if name.startswith(IMAGES_PREFIX):
                image_count += 1

        if STICKY_NOTES_MEMBER not in names:
            raise ValueError("Sticky backup does not contain sticky_notes.json")
        try:
            notes = json.loads(archive.read(STICKY_NOTES_MEMBER).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Sticky backup contains invalid sticky_notes.json") from exc
        if not isinstance(notes, (list, dict)):
            raise ValueError("sticky_notes.json must contain a JSON list or object")

        manifest = {}
        if MANIFEST_MEMBER in names:
            try:
                manifest = json.loads(archive.read(MANIFEST_MEMBER).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("Sticky backup contains invalid manifest.json") from exc
            if not isinstance(manifest, dict):
                raise ValueError("Sticky backup manifest must be an object")

    return {
        "available": True,
        "notes_count": len(notes),
        "images_count": image_count,
        "manifest": manifest,
    }


def _extract_archive(archive_path, temporary_root):
    metadata = _validate_archive(archive_path)
    with zipfile.ZipFile(archive_path, "r") as archive:
        notes_target = os.path.join(temporary_root, STICKY_NOTES_MEMBER)
        with open(notes_target, "wb") as target:
            target.write(archive.read(STICKY_NOTES_MEMBER))

        images_target = os.path.join(temporary_root, "images")
        os.makedirs(images_target, exist_ok=True)
        for info in archive.infolist():
            name = _safe_member_name(info.filename)
            if not name.startswith(IMAGES_PREFIX):
                continue
            relative = name[len(IMAGES_PREFIX):]
            target_path = os.path.abspath(os.path.join(images_target, *relative.split("/")))
            if os.path.commonpath([os.path.abspath(images_target), target_path]) != os.path.abspath(images_target):
                raise ValueError("Invalid sticky image path")
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            with archive.open(info, "r") as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)
    return metadata


def restore_archive(archive_path, notes_path, images_dir):
    """Restore a sticky snapshot, retaining the old files if installation fails."""
    metadata = _validate_archive(archive_path)
    if not metadata["available"]:
        return metadata

    base_dir = os.path.abspath(os.path.dirname(notes_path))
    os.makedirs(base_dir, exist_ok=True)
    temporary_root = tempfile.mkdtemp(prefix=".sticky_restore_", dir=base_dir)
    previous_root = tempfile.mkdtemp(prefix=".sticky_previous_", dir=base_dir)
    installed_notes = False
    installed_images = False
    moved_previous_notes = False
    moved_previous_images = False
    try:
        extracted_metadata = _extract_archive(archive_path, temporary_root)
        staged_notes = os.path.join(temporary_root, STICKY_NOTES_MEMBER)
        staged_images = os.path.join(temporary_root, "images")
        previous_notes = os.path.join(previous_root, STICKY_NOTES_MEMBER)
        previous_images = os.path.join(previous_root, "images")

        if os.path.exists(notes_path):
            os.replace(notes_path, previous_notes)
            moved_previous_notes = True
        if os.path.exists(images_dir):
            os.replace(images_dir, previous_images)
            moved_previous_images = True

        os.replace(staged_notes, notes_path)
        installed_notes = True
        os.replace(staged_images, images_dir)
        installed_images = True
        return extracted_metadata
    except Exception:
        if installed_notes and os.path.exists(notes_path):
            os.remove(notes_path)
        if installed_images and os.path.exists(images_dir):
            shutil.rmtree(images_dir, ignore_errors=True)
        if moved_previous_notes and os.path.exists(previous_notes):
            os.replace(previous_notes, notes_path)
        if moved_previous_images and os.path.exists(previous_images):
            os.replace(previous_images, images_dir)
        raise
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
        shutil.rmtree(previous_root, ignore_errors=True)


def archive_metadata(archive_path):
    """Return lightweight metadata without changing local sticky-note files."""
    return _validate_archive(archive_path)
