"""Codex language discovery against temporary files and mocked Windows APIs."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from codex_pointer import codex_language as locales


class CodexLanguageReaderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "config.toml"
        self.modified = 1_700_000_000_000_000_000

    def write(self, text):
        self.path.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        self.modified += 1_000_000_000
        os.utime(self.path, ns=(self.modified, self.modified))

    def reader(self, system="zh-CN"):
        return locales.CodexLanguageReader(self.path, system_language=lambda: system)

    def test_generated_desktop_table_overrides_system_language(self):
        self.write('model = "example"\n[desktop]\nlocaleOverride = "en-US" # comment\n')
        self.assertEqual(self.reader().read(), "en-US")

    def test_root_dotted_key_and_normalized_language_families(self):
        self.write("desktop.localeOverride = 'en_GB'\n[other]\nlocaleOverride='zh-CN'\n")
        self.assertEqual(self.reader().read(), "en-US")
        self.write('desktop . localeOverride = "zh-TW"')
        self.assertEqual(self.reader(system="en-US").read(), "zh-CN")

    def test_comments_multiline_strings_and_other_tables_do_not_impersonate_the_setting(self):
        documents = [
            '# [desktop]\n# localeOverride="en-US"\n',
            'notes = """\n[desktop]\nlocaleOverride="en-US"\n"""\n',
            "notes = '''\n[desktop]\nlocaleOverride='en-US'\n'''\n",
            '[other]\nlocaleOverride="en-US"\ndesktop.localeOverride="en-US"\n',
            '[desktop.other]\nlocaleOverride="en-US"\n',
            '"desktop.localeOverride" = "en-US"\n',
        ]
        for document in documents:
            with self.subTest(document=document):
                self.write(document)
                self.assertEqual(self.reader().read(), "zh-CN")

    def test_automatic_or_missing_override_uses_system_ui_language(self):
        for value in (None, "", "auto", "system"):
            with self.subTest(value=value):
                self.write("[desktop]\n" + (f'localeOverride="{value}"\n' if value is not None else ""))
                self.assertEqual(self.reader(system="zh-HK").read(), "zh-CN")
        self.assertEqual(locales.CodexLanguageReader(self.path.with_name("missing"),
                                                    system_language=lambda: "en-US").read(), "en-US")

    def test_unsupported_codex_or_system_language_falls_back_to_english(self):
        self.write('[desktop]\nlocaleOverride="fr-FR"\n')
        self.assertEqual(self.reader().read(), "en-US")
        self.write('[desktop]\nlocaleOverride="auto"\n')
        self.assertEqual(self.reader(system="ja-JP").read(), "en-US")

    def test_invalid_partial_duplicate_and_oversize_changes_keep_last_valid_language(self):
        self.write('[desktop]\nlocaleOverride="en-US"\n')
        reader = self.reader()
        self.assertEqual(reader.read(), "en-US")
        documents = [
            '[desktop]\nlocaleOverride="zh-CN',
            '[desktop]\nlocaleOverride="zh-CN"\nbroken=[1,\n',
            '[desktop]\nlocaleOverride="zh-CN"\ninvalid bare text\n',
            '[desktop]\nlocaleOverride="zh-CN"\nlocaleOverride="en-US"\n',
            '[desktop]\nlocaleOverride=true\n',
            '[desktop]\nlocaleOverride="zh-CN"\nnotes="""bad\\q"""\n',
            b'\xff\xfeinvalid',
            b'#' * (1024 * 1024 + 1),
        ]
        for document in documents:
            with self.subTest(document=str(document)[:80]):
                self.write(document)
                self.assertEqual(reader.read(), "en-US")
        self.write('[desktop]\nlocaleOverride="zh-CN"\n')
        self.assertEqual(reader.read(), "zh-CN")

    def test_missing_or_unreadable_changed_config_preserves_last_valid_language(self):
        self.write('[desktop]\nlocaleOverride="en-US"\n')
        reader = self.reader()
        self.assertEqual(reader.read(), "en-US")
        self.path.unlink()
        self.assertEqual(reader.read(), "en-US")
        self.write('[desktop]\nlocaleOverride="zh-CN"\n')
        with patch.object(Path, "open", side_effect=PermissionError("Owned fixture")):
            self.assertEqual(reader.read(), "en-US")
        # A temporary lock must not pin the failure to the file's unchanged
        # timestamp/size. The next read retries and applies the valid change.
        self.assertEqual(reader.read(), "zh-CN")

    def test_missing_config_keeps_following_changes_to_system_ui_language(self):
        system = Mock(return_value="zh-CN")
        reader = locales.CodexLanguageReader(self.path, system_language=system)
        self.assertEqual(reader.read(), "zh-CN")
        system.return_value = "en-US"
        self.assertEqual(reader.read(), "en-US")

    def test_unchanged_file_is_not_reopened_and_live_system_mode_can_follow_ui_preference(self):
        self.write('[desktop]\nlocaleOverride="auto"\n')
        system = Mock(return_value="zh-CN")
        reader = locales.CodexLanguageReader(self.path, system_language=system)
        self.assertEqual(reader.read(), "zh-CN")
        system.return_value = "en-US"
        with patch.object(Path, "open", side_effect=AssertionError("Config should stay cached")):
            self.assertEqual(reader.read(), "en-US")

    def test_explicit_locale_does_not_follow_system_or_reopen_an_unchanged_file(self):
        self.write('[desktop]\nlocaleOverride="en-US"\n')
        system = Mock(return_value="zh-CN")
        reader = locales.CodexLanguageReader(self.path, system_language=system)
        self.assertEqual(reader.read(), "en-US")
        system.reset_mock()
        with patch.object(Path, "open", side_effect=AssertionError("Config should stay cached")):
            self.assertEqual(reader.read(), "en-US")
        system.assert_not_called()

    def test_default_config_path_honors_codex_home_without_reading_real_config(self):
        with patch.dict(os.environ, {"CODEX_HOME": self.temporary.name}):
            reader = locales.CodexLanguageReader(system_language=lambda: "en-US")
        self.assertEqual(reader.config_path, self.path)

    def test_python310_reader_handles_codex_tables_arrays_and_quoted_project_paths(self):
        self.write(r'''model="example"
features={fast=true, count=2}
trusted_dirs=["C:/One", "D:/Two",]
[[skills.config]]
path='C:\Skills\one\SKILL.md'
enabled=false
[[skills.config]]
path='D:\Skills\two\SKILL.md'
enabled=true
[projects.'C:\A path']
trust_level='trusted'
[desktop]
localeOverride="en-US"
''')
        with patch.object(locales, "_tomllib", None):
            self.assertEqual(self.reader().read(), "en-US")

    def test_python310_reader_supports_unrelated_array_tables_before_and_after_desktop(self):
        with patch.object(locales, "_tomllib", None):
            arrays = '''[[skills.config]]
path='C:/one/SKILL.md'
enabled=false
desktop.localeOverride='zh-CN'
[[skills.config]]
path='C:/two/SKILL.md'
enabled=true
[skills.config.options]
desktop.localeOverride='zh-CN'
[[mcp_servers.example.entries]]
name='one'
[mcp_servers.example.entries.desktop]
localeOverride='zh-CN'
[[mcp_servers.example.entries]]
name='two'
[mcp_servers.example.entries.desktop]
localeOverride='zh-CN'
'''
            desktop = '[desktop]\nlocaleOverride="en-US"\n'
            for document in (arrays + desktop, desktop + arrays):
                with self.subTest(document=document):
                    self.write(document)
                    self.assertEqual(self.reader().read(), "en-US")

    def test_python310_array_entries_cannot_forge_a_root_desktop_override(self):
        self.write('''[[anything]]
desktop.localeOverride='en-US'
[[anything]]
[anything.desktop]
localeOverride='en-US'
[[anything]]
desktop.localeOverride='en-US'
''')
        with patch.object(locales, "_tomllib", None):
            self.assertEqual(self.reader(system="zh-CN").read(), "zh-CN")

    def test_python310_reader_rejects_ambiguous_desktop_structures_and_invalid_redefinitions(self):
        with patch.object(locales, "_tomllib", None):
            self.write('[desktop]\nlocaleOverride="en-US"\n')
            reader = self.reader()
            self.assertEqual(reader.read(), "en-US")
            for document in [
                'desktop={localeOverride="zh-CN"}',
                '[desktop.localeOverride]\nx=1',
                'desktop.localeOverride.child="zh-CN"',
                'desktop.localeOverride="zh-CN"\n[desktop]\nfoo=1',
                '[desktop]\nlocaleOverride="zh-CN"\nfoo={x=1, x.y=2}',
                '[[desktop]]\nlocaleOverride="zh-CN"',
                '[desktop]\nlocaleOverride="zh-CN"\n[[items]]\nkey=1\nkey=2',
                '[desktop]\nlocaleOverride="zh-CN"\n[items]\nkey=1\n[[items]]\nkey=2',
            ]:
                with self.subTest(document=document):
                    self.write(document)
                    self.assertEqual(reader.read(), "en-US")


class WindowsUiPreferenceTests(unittest.TestCase):
    def test_preferred_ui_language_order_wins_over_default_language(self):
        def preferred(flags, count, buffer, size):
            count._obj.value = 2
            if buffer is None:
                size._obj.value = 13
            else:
                buffer.value = "en-US\0zh-CN\0"
            return True
        kernel = SimpleNamespace(GetUserPreferredUILanguages=Mock(side_effect=preferred),
                                 GetUserDefaultUILanguage=Mock(return_value=0x0804))
        with patch.object(locales.os, "name", "nt"), \
                patch.object(locales.ctypes, "WinDLL", return_value=kernel, create=True):
            self.assertEqual(locales.preferred_ui_language(), "en-US")
        kernel.GetUserDefaultUILanguage.assert_not_called()

    def test_default_ui_language_is_used_when_preferred_list_is_unavailable(self):
        kernel = SimpleNamespace(GetUserPreferredUILanguages=Mock(return_value=False),
                                 GetUserDefaultUILanguage=Mock(return_value=0x0404))
        with patch.object(locales.os, "name", "nt"), \
                patch.object(locales.ctypes, "WinDLL", return_value=kernel, create=True):
            self.assertEqual(locales.preferred_ui_language(), "zh-CN")


if __name__ == "__main__":
    unittest.main()
