import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load_module('installer', ROOT / 'install.py')
release = load_module('release', ROOT / 'scripts/build_release.py')


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name) / 'codex home'
        self.stdout = contextlib.redirect_stdout(io.StringIO())
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def write(self, relative, data):
        path = self.home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
        return path

    def snapshot(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob('*') if p.is_file()}

    def test_default_install_and_uninstall(self):
        installer.install(self.home)
        state = installer.load_state(self.home)
        self.assertEqual(state['options'], {'muse': False, 'jev_api': False})
        self.assertEqual(set(state['files']), set(installer.SKILL_FILES))
        self.assertEqual((self.home / 'token-saver/state.json').stat().st_mode & 0o777, 0o600)
        installer.uninstall(self.home)
        self.assertEqual(self.snapshot(), {})

    def test_restore_original_files_and_keep_private_settings(self):
        original = '# My instructions\r\nKeep replies short.'
        self.write('AGENTS.md', original)
        self.write('skills/jev-context/SKILL.md', 'My original skill')
        private = self.write('skills/jev-context/settings.json', '{"key_file":"private-location"}')
        baseline = self.snapshot()
        installer.install(self.home, muse=True, jev=True)
        self.assertEqual(private.read_text(), '{"key_file":"private-location"}')
        installer.uninstall(self.home)
        self.assertEqual(self.snapshot(), baseline)

    def test_update_preserves_choices_and_is_idempotent(self):
        installer.install(self.home, muse=True, jev=True)
        baseline = self.snapshot()
        installer.install(self.home)
        self.assertEqual(self.snapshot(), baseline)
        installer.install(self.home, muse=False)
        self.assertEqual(installer.load_state(self.home)['options'], {'muse': False, 'jev_api': True})
        text = (self.home / 'AGENTS.md').read_text()
        self.assertEqual(text.count(installer.START), 1)
        self.assertNotIn('@@', text)
        self.assertIn(str(self.home / 'skills'), text)

    def test_user_instructions_added_after_install_survive_update_and_uninstall(self):
        self.write('AGENTS.md', 'Original rules')
        installer.install(self.home)
        path = self.home / 'AGENTS.md'
        path.write_text(path.read_text() + '\n\nNew unrelated rules\n')
        installer.install(self.home, muse=True)
        installer.uninstall(self.home)
        self.assertEqual(path.read_text(), 'Original rules\n\nNew unrelated rules\n')

    def test_edited_skill_aborts_before_any_changes(self):
        installer.install(self.home)
        self.write('skills/jev-context/SKILL.md', 'User customized this')
        baseline = self.snapshot()
        with self.assertRaises(ValueError):
            installer.install(self.home, muse=True)
        with self.assertRaises(ValueError):
            installer.uninstall(self.home)
        self.assertEqual(self.snapshot(), baseline)

    def test_edited_managed_instructions_abort_before_any_changes(self):
        installer.install(self.home)
        path = self.home / 'AGENTS.md'
        path.write_text(path.read_text().replace(installer.START, installer.START + '\nUser edit'))
        baseline = self.snapshot()
        with self.assertRaises(ValueError):
            installer.uninstall(self.home)
        self.assertEqual(self.snapshot(), baseline)

    def test_dry_run_makes_no_directory(self):
        installer.install(self.home, muse=True, dry_run=True)
        self.assertFalse(self.home.exists())

    def test_malformed_markers_rejected(self):
        self.write('AGENTS.md', installer.END + '\n' + installer.START)
        baseline = self.snapshot()
        with self.assertRaises(ValueError):
            installer.install(self.home)
        self.assertEqual(self.snapshot(), baseline)

    def test_symlink_targets_rejected(self):
        outside = Path(self.temporary.name) / 'outside.md'
        outside.write_text('Preserve this')
        self.home.mkdir()
        (self.home / 'AGENTS.md').symlink_to(outside)
        with self.assertRaises(ValueError):
            installer.install(self.home)
        self.assertEqual(outside.read_text(), 'Preserve this')
        self.assertFalse((self.home / 'skills').exists())

    def test_failed_write_rolls_back(self):
        self.write('AGENTS.md', 'Original')
        baseline = self.snapshot()
        original_write = installer.write_file
        count = 0

        def fail_once(path, data, mode):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('Simulated write failure')
            return original_write(path, data, mode)

        with patch.object(installer, 'write_file', side_effect=fail_once):
            with self.assertRaises(OSError):
                installer.install(self.home)
        self.assertEqual(self.snapshot(), baseline)


class ReleaseTests(unittest.TestCase):
    def test_archive_excludes_local_state(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            for relative in release.FILES:
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            (source / '.env').write_text('synthetic private value')
            (source / 'skills/jev-context/settings.json').write_text('synthetic settings')
            output = Path(directory) / 'share.zip'
            with patch.object(release, 'ROOT', source), patch.object(sys, 'argv', ['build_release.py', '--output', str(output)]):
                with contextlib.redirect_stdout(io.StringIO()):
                    release.main()
            with zipfile.ZipFile(output) as archive:
                names = archive.namelist()
                self.assertEqual(len(names), len(release.FILES))
                self.assertFalse(any(n.endswith(('.env', 'settings.json')) for n in names))
                self.assertEqual(archive.testzip(), None)


if __name__ == '__main__':
    unittest.main()
