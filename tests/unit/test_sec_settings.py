"""Synthetic contact values only; never read the workspace's actual .env."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.infrastructure.document_sources.sec_settings import KEY, resolve_sec_contact


class SecSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def write(self, text, mode=0o600):
        path = self.root / '.env'
        if path.exists():
            path.chmod(0o600)
        path.write_text(text)
        path.chmod(mode)
        return path

    def resolve(self, **kwargs):
        return resolve_sec_contact(settings_root=self.root, **kwargs)

    def test_priority_and_lower_priority_file_not_opened(self):
        self.write(f'{KEY}=local@example.test\n', mode=0o644)
        os.environ[KEY] = 'Environment env@example.test'
        self.assertEqual(self.resolve(explicit='CLI cli@example.test', configured='Config cfg@example.test'),
                         ('CLI cli@example.test', 'cli'))
        self.assertEqual(self.resolve(configured='Config cfg@example.test'),
                         ('Environment env@example.test', 'environment'))
        del os.environ[KEY]
        self.assertEqual(self.resolve(configured='Config cfg@example.test'),
                         ('Config cfg@example.test', 'company_config'))

    def test_local_file_persists_across_calls_without_export(self):
        self.write(f'OTHER_KEY=unrelated\nexport {KEY}="Uteki contact@example.test" # contact\n')
        for _ in range(2):
            self.assertEqual(self.resolve(configured='  '), ('Uteki contact@example.test', 'local_env_file'))
        self.assertNotIn(KEY, os.environ)
        self.assertNotIn('OTHER_KEY', os.environ)

    def test_absent_key_or_file_is_unconfigured(self):
        self.assertEqual(self.resolve(), (None, 'unconfigured'))
        self.write('MODEL_API_KEY=do-not-read-or-export\n')
        self.assertEqual(self.resolve(), (None, 'unconfigured'))
        self.assertNotIn('MODEL_API_KEY', os.environ)

    def test_duplicate_even_identical_entries_rejected(self):
        self.write(f'{KEY}=contact@example.test\nexport {KEY}=contact@example.test\n')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.resolve()

    def test_permission_modes_must_be_exactly_600(self):
        for mode in (0o644, 0o640, 0o400, 0o700):
            self.write(f'{KEY}=contact@example.test\n', mode)
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'mode 600'):
                self.resolve()

    def test_symlink_file_parent_and_nonregular_file_rejected(self):
        actual = self.root / 'private'
        actual.write_text(f'{KEY}=contact@example.test\n')
        actual.chmod(0o600)
        (self.root / '.env').symlink_to(actual)
        with self.assertRaises(ValueError):
            self.resolve()
        (self.root / '.env').unlink()
        self.write(f'{KEY}=contact@example.test\n')
        alias = self.root / 'alias'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            resolve_sec_contact(settings_root=alias)
        (self.root / '.env').unlink()
        (self.root / '.env').mkdir(mode=0o600)
        with self.assertRaises(ValueError):
            self.resolve()

    def test_blank_control_and_multiline_assignments_are_errors(self):
        for value in ('', '   ', 'contact@example.test\ninjected', 'contact@example.test\rX', 'contact@example.test\x00'):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                self.resolve(explicit=value)
        for assignment in ('', '   ', '""', '"first\nsecond"', 'contact@example.test\rinjected', '"unterminated'):
            self.write(f'{KEY}={assignment}\n')
            with self.subTest(assignment=repr(assignment)), self.assertRaises(ValueError):
                self.resolve()
        os.environ[KEY] = ''
        with self.assertRaises(ValueError):
            self.resolve(configured='Config contact@example.test')
        del os.environ[KEY]
        with self.assertRaises(ValueError):
            self.resolve(configured='\n')

    def test_shell_and_environment_expansion_are_not_executed(self):
        marker = self.root / 'must-not-exist'
        literal = f'Uteki $(touch {marker}) $OTHER_KEY `false`'
        self.write(f'OTHER_KEY=$(touch {marker})\n{KEY}=\'{literal}\'\n')
        before = dict(os.environ)
        self.assertEqual(self.resolve(), (literal, 'local_env_file'))
        self.assertEqual(dict(os.environ), before)
        self.assertFalse(marker.exists())


if __name__ == '__main__':
    unittest.main()
