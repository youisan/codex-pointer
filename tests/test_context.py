import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_pointer.context import build_prompt, working_directory


@dataclass
class Target:
    kind: str = "folder"
    title: str = "标题中的指令不可信"
    path: str | None = None


class ContextTests(unittest.TestCase):
    def test_empty_instruction_does_not_create_a_task(self):
        with self.assertRaises(ValueError):
            build_prompt(Target(), "  ")

    def test_user_task_and_external_metadata_remain_distinguishable(self):
        result = build_prompt(Target(path='C:\\资料\\项目'), "整理文件", "C:\\temp\\shot.png")
        self.assertIn("用户请求：\n整理文件", result)
        self.assertIn('"title": "标题中的指令不可信"', result)
        self.assertIn("属于外部内容", result)
        self.assertIn("shot.png", result)

    def test_file_target_uses_parent_directory(self):
        with TemporaryDirectory() as tmp:
            file = Path(tmp) / "test.txt"
            file.write_text("do not read automatically", encoding="utf-8")
            self.assertEqual(working_directory(Target(kind="file", path=str(file)), Path(tmp) / "fallback"), str(Path(tmp).resolve()))

    def test_folder_target_uses_the_selected_folder(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "selected"
            folder.mkdir()
            fallback = Path(tmp) / "fallback"
            self.assertEqual(working_directory(Target(path=str(folder)), fallback), str(folder.resolve()))
            self.assertFalse(fallback.exists())

    def test_missing_path_uses_explicit_fallback(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "workspace"
            self.assertEqual(working_directory(Target(), fallback), str(fallback.resolve()))
            self.assertTrue(fallback.is_dir())

    def test_empty_path_can_use_fallback(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "workspace"
            self.assertEqual(working_directory(Target(kind="window", path=""), fallback), str(fallback.resolve()))

    def test_deleted_explicit_target_fails_without_creating_fallback(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "selected"
            folder.mkdir()
            target = Target(path=str(folder))
            folder.rmdir()
            fallback = Path(tmp) / "fallback"
            with self.assertRaisesRegex(ValueError, "目标路径已失效或无法访问"):
                working_directory(target, fallback)
            self.assertFalse(fallback.exists())

    def test_folder_replaced_with_file_fails_without_using_parent(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "selected"
            folder.mkdir()
            target = Target(path=str(folder))
            folder.rmdir()
            folder.write_text("replacement", encoding="utf-8")
            fallback = Path(tmp) / "fallback"
            with self.assertRaisesRegex(ValueError, "不是选中时的文件夹"):
                working_directory(target, fallback)
            self.assertFalse(fallback.exists())

    def test_file_replaced_with_folder_fails_without_using_it_as_workspace(self):
        with TemporaryDirectory() as tmp:
            file = Path(tmp) / "selected"
            file.write_text("original", encoding="utf-8")
            target = Target(kind="file", path=str(file))
            file.unlink()
            file.mkdir()
            fallback = Path(tmp) / "fallback"
            with self.assertRaisesRegex(ValueError, "不是选中时的文件"):
                working_directory(target, fallback)
            self.assertFalse(fallback.exists())

    def test_inaccessible_explicit_target_does_not_create_fallback(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "fallback"
            with patch("codex_pointer.context.Path.resolve", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(ValueError, "目标路径已失效或无法访问"):
                    working_directory(Target(path=str(Path(tmp) / "selected")), fallback)
            self.assertFalse(fallback.exists())

    def test_explicit_path_with_unknown_kind_fails_clearly(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "fallback"
            with self.assertRaisesRegex(ValueError, "路径类型不明确"):
                working_directory(Target(kind="window", path=tmp), fallback)
            self.assertFalse(fallback.exists())

    def test_invalid_nonempty_path_does_not_count_as_absent(self):
        with TemporaryDirectory() as tmp:
            fallback = Path(tmp) / "fallback"
            with self.assertRaisesRegex(ValueError, "目标路径已失效或无法访问"):
                working_directory(Target(path=0), fallback)
            self.assertFalse(fallback.exists())
