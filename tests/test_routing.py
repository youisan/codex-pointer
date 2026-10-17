"""Target preferences must never send a new object to a previous chat."""
from dataclasses import dataclass
import unittest
from unittest.mock import patch

from codex_pointer.routing import (
    MAX_RECENT_TARGETS, MAX_ROUTES, binding_for, mode_for, recent_targets,
    remember_binding, remember_mode, remember_target, route_key,
)


CHAT_A = "c053ab24-ef0b-4d9a-91de-1e68f6119f23"
CHAT_B = "72ab3dcf-07c5-4b1c-aaab-b7f512ed4dd3"


@dataclass
class Target:
    kind: str = "folder"
    path: str | None = None
    title: str = "资料"
    process_path: str = ""
    process_name: str = ""


class RoutingTests(unittest.TestCase):
    def test_switching_a_b_and_back_only_restores_explicit_target_binding(self):
        a, b = Target(path=r"D:\Projects\A"), Target(path=r"D:\Projects\B")
        settings = {"thread_id": CHAT_B, "thread_title": "Legacy global chat"}
        self.assertIsNone(binding_for(settings, a))
        self.assertEqual(mode_for(settings, a), "new")
        remember_binding(settings, a, CHAT_A, "项目 A")
        self.assertIsNone(binding_for(settings, b))
        self.assertEqual(mode_for(settings, b), "new")
        remember_binding(settings, b, CHAT_B, "项目 B")
        self.assertEqual(binding_for(settings, a)["thread_id"], CHAT_A)
        self.assertEqual(binding_for(settings, b)["thread_id"], CHAT_B)
        self.assertEqual(mode_for(settings, a), "existing")

    def test_routes_do_not_inherit_from_parent_or_similarly_named_folder(self):
        settings = {}
        remember_binding(settings, Target(path=r"C:\work"), CHAT_A)
        self.assertIsNone(binding_for(settings, Target(path=r"C:\work\child")))
        self.assertIsNone(binding_for(settings, Target(path=r"C:\workspace")))

    def test_folder_key_is_case_and_separator_insensitive_without_disk_access(self):
        with patch("pathlib.Path.exists", side_effect=AssertionError("no disk")), \
             patch("pathlib.Path.resolve", side_effect=AssertionError("no disk")):
            expected = route_key(Target(path=r"C:\Users\资料\项目"))
            self.assertEqual(route_key(Target(path="c:/users/资料/项目/")), expected)
            self.assertEqual(route_key(Target(path=r"C:\Users\资料\临时\..\项目")), expected)

    def test_unc_share_root_and_subfolder_are_normalized(self):
        bare = route_key(Target(path=r"\\Server\Shared"))
        self.assertEqual(route_key(Target(path="//server/SHARED/")), bare)
        self.assertEqual(bare, "folder:\\\\server\\shared\\")
        self.assertEqual(route_key(Target(path=r"\\Server\Shared\资料\\")),
                         route_key(Target(path="//server/shared/资料")))
        self.assertNotEqual(route_key(Target(path=r"\\Server\Shared2")), bare)

    def test_drive_root_and_extended_paths_have_consistent_keys(self):
        self.assertEqual(route_key(Target(path="C:/")), "folder:c:\\")
        self.assertEqual(route_key(Target(path=r"\\?\C:\work")), route_key(Target(path=r"C:\work")))
        self.assertEqual(route_key(Target(path=r"\\?\UNC\Server\Share\work")),
                         route_key(Target(path=r"\\server\share\work")))

    def test_file_uses_its_parent_folder_not_its_extension_or_title(self):
        folder = Target(path=r"D:\项目\A")
        file = Target(kind="file", path=r"D:\项目\A\报告.docx", title="报告")
        settings = {}
        remember_binding(settings, folder, CHAT_A, "目录对话")
        self.assertEqual(binding_for(settings, file)["thread_id"], CHAT_A)
        self.assertNotEqual(route_key(file), route_key(Target(path=r"D:\项目\B")))

    def test_application_uses_full_path_and_never_window_title_or_process_name(self):
        app = Target(kind="window", process_path=r"C:\Apps\Editor.exe", title="draft")
        settings = {}
        remember_binding(settings, app, CHAT_A, "编辑器")
        changed_title = Target(kind="window", process_path="c:/apps/EDITOR.EXE", title="other")
        self.assertEqual(binding_for(settings, changed_title)["thread_id"], CHAT_A)
        self.assertIsNone(binding_for(settings, Target(kind="window", process_path=r"D:\Apps\Editor.exe")))
        self.assertIsNone(route_key(Target(kind="window", process_name="Editor.exe", title="draft")))

    def test_ambiguous_paths_and_unknown_kinds_never_produce_a_route(self):
        for path in (None, "", "relative/path", r"C:relative", r"\rooted", r"\\server",
                     r"\\.\PIPE\pointer", "C:\\bad\0path", "C:\\" + "a" * 32768):
            with self.subTest(path=path):
                self.assertIsNone(route_key(Target(path=path)))
        self.assertIsNone(route_key({"kind": [], "path": r"C:\work"}))

    def test_new_mode_preserves_binding_for_explicit_switch_back(self):
        target, settings = Target(path=r"C:\A"), {}
        remember_binding(settings, target, CHAT_A, "A")
        remember_mode(settings, target, "new")
        self.assertEqual(mode_for(settings, target), "new")
        self.assertEqual(binding_for(settings, target)["thread_id"], CHAT_A)
        remember_mode(settings, target, "existing")
        self.assertEqual(mode_for(settings, target), "existing")

    def test_existing_mode_does_not_invent_binding_or_reuse_legacy(self):
        settings, target = {"thread_id": CHAT_A}, Target(path=r"C:\A")
        remember_mode(settings, target, "existing")
        self.assertIsNone(binding_for(settings, target))
        self.assertEqual(mode_for(settings, target), "new")

    def test_invalid_uuid_or_target_does_not_mutate_settings(self):
        settings = {"untouched": True}
        for identifier in ("not-a-uuid", "", None, {}, 14):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                remember_binding(settings, Target(path=r"C:\A"), identifier)
            self.assertEqual(settings, {"untouched": True})
        with self.assertRaises(ValueError):
            remember_binding(settings, Target(path="relative"), CHAT_A)
        with self.assertRaises(ValueError):
            remember_mode(settings, Target(path=r"C:\A"), "unexpected")

    def test_malformed_preferences_are_ignored_and_replaced_on_explicit_save(self):
        target = Target(path=r"C:\A")
        for malformed in (None, [], "old", {route_key(target): []},
                          {route_key(target): {"thread_id": [], "mode": "existing"}}):
            with self.subTest(malformed=malformed):
                settings = {"target_routes": malformed, "recent_targets": malformed}
                self.assertIsNone(binding_for(settings, target))
                self.assertEqual(recent_targets(settings), [])
                remember_binding(settings, target, CHAT_A)
                self.assertEqual(binding_for(settings, target)["thread_id"], CHAT_A)
        settings = {"target_routes": {route_key(target): {"thread_id": CHAT_A, "thread_title": [], "mode": {}}}}
        self.assertEqual(binding_for(settings, target)["thread_title"], CHAT_A)
        self.assertEqual(mode_for(settings, target), "new")

    def test_binding_read_and_returned_save_are_copies(self):
        settings, target = {}, Target(path=r"C:\A")
        saved = remember_binding(settings, target, CHAT_A.upper(), "A")
        saved["thread_id"] = CHAT_B
        value = binding_for(settings, target)
        value["thread_title"] = "mutated"
        self.assertEqual(binding_for(settings, target)["thread_id"], CHAT_A)
        self.assertEqual(binding_for(settings, target)["thread_title"], "A")

    def test_route_cap_evicts_oldest_and_rebinding_keeps_most_recent(self):
        settings = {"target_routes": {"untrusted-key": {"thread_id": CHAT_A}}}
        for index in range(MAX_ROUTES):
            remember_binding(settings, Target(path=rf"C:\Project{index}"), CHAT_A)
        first, second = Target(path=r"C:\Project0"), Target(path=r"C:\Project1")
        remember_binding(settings, first, CHAT_B)
        remember_binding(settings, Target(path=r"C:\New"), CHAT_A)
        self.assertEqual(len(settings["target_routes"]), MAX_ROUTES)
        self.assertIsNone(binding_for(settings, second))
        self.assertEqual(binding_for(settings, first)["thread_id"], CHAT_B)

    def test_recents_are_bounded_and_deduplicate_file_folder_identity(self):
        settings = {}
        for index in range(MAX_RECENT_TARGETS + 2):
            remember_target(settings, Target(path=rf"C:\Project{index}"))
        self.assertEqual(len(recent_targets(settings)), MAX_RECENT_TARGETS)
        self.assertEqual(recent_targets(settings)[0]["path"], rf"C:\Project{MAX_RECENT_TARGETS + 1}")
        remember_target(settings, Target(path=r"C:\Project8"))
        remember_target(settings, Target(kind="file", path=r"C:\Project8\报告.docx"))
        records = recent_targets(settings)
        self.assertEqual(records[0]["kind"], "file")
        self.assertEqual(sum(row["key"] == "folder:c:\\project8" for row in records), 1)

    def test_recents_strip_screenshot_prompt_and_stale_window_data(self):
        settings = {"recent_targets": [
            {"kind": "window", "process_path": r"C:\Editor.exe", "title": "A", "process_name": "Editor.exe",
             "hwnd": 14, "rect": [0, 0, 100, 100], "image_path": r"C:\private.png", "draft": "secret"},
            {"kind": "folder", "path": "relative"}, None,
        ]}
        self.assertEqual(recent_targets(settings), [{"key": "application:c:\\editor.exe", "kind": "window",
            "title": "A", "process_path": r"C:\Editor.exe", "process_name": "Editor.exe"}])
        returned = remember_target(settings, Target(path=r"C:\B"))
        returned[0]["title"] = "changed"
        self.assertEqual(recent_targets(settings)[0]["title"], "资料")


if __name__ == "__main__":
    unittest.main()
