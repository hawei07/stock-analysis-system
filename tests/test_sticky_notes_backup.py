import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from services.sticky_notes_backup import (
    archive_name_for_sql,
    create_archive,
    restore_archive,
)


class StickyNotesBackupTests(unittest.TestCase):
    def test_archive_name_and_restore_include_notes_and_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_path = root / "data" / "sticky_notes.json"
            images_dir = root / "data" / "images"
            archive_path = root / "cloud" / archive_name_for_sql("stock_analysis_20260811_120000.sql")
            notes_path.parent.mkdir(parents=True)
            images_dir.mkdir(parents=True)
            notes = [{
                "id": 1,
                "title": "测试便利贴",
                "content": "/data/images/1.png",
                "stock_code": "600025",
                "created_at": "2026-08-11T12:00:00",
                "updated_at": "2026-08-11T12:00:00",
            }]
            notes_path.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
            (images_dir / "1.png").write_bytes(b"image-data")

            created = create_archive(str(notes_path), str(images_dir), str(archive_path))
            self.assertEqual(created["notes_count"], 1)
            self.assertEqual(created["images_count"], 1)
            self.assertTrue(archive_path.exists())

            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("sticky_notes.json", archive.namelist())
                self.assertIn("images/1.png", archive.namelist())

            notes_path.write_text("[]", encoding="utf-8")
            (images_dir / "1.png").write_bytes(b"old-image")
            restored = restore_archive(str(archive_path), str(notes_path), str(images_dir))

            self.assertTrue(restored["available"])
            self.assertEqual(restored["notes_count"], 1)
            self.assertEqual(json.loads(notes_path.read_text(encoding="utf-8")), notes)
            self.assertEqual((images_dir / "1.png").read_bytes(), b"image-data")

    def test_missing_archive_does_not_change_local_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes_path = root / "sticky_notes.json"
            images_dir = root / "images"
            notes_path.write_text("[]", encoding="utf-8")
            images_dir.mkdir()
            (images_dir / "keep.png").write_bytes(b"keep")

            result = restore_archive(str(root / "missing.files.zip"), str(notes_path), str(images_dir))

            self.assertFalse(result["available"])
            self.assertEqual(notes_path.read_text(encoding="utf-8"), "[]")
            self.assertEqual((images_dir / "keep.png").read_bytes(), b"keep")

    def test_archive_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive_path = root / "bad.files.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("sticky_notes.json", "[]")
                archive.writestr("images/../escape.txt", "bad")

            with self.assertRaises(ValueError):
                restore_archive(
                    str(archive_path),
                    str(root / "sticky_notes.json"),
                    str(root / "images"),
                )


if __name__ == "__main__":
    unittest.main()
