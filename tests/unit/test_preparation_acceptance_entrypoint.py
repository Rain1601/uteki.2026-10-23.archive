"""Acquisition entry point uses private settings; replay never needs a contact."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from uteki.infrastructure.document_sources.sec_settings import KEY


class PreparationEntrypointTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        path = Path(__file__).resolve().parents[2] / 'experiments/agent_design/2026-10-12-preparation-acceptance-v1/run.py'
        spec = importlib.util.spec_from_file_location('preparation_acceptance_entrypoint', path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.BASE = self.root / 'output'
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def invoke(self, flags):
        stdout, stderr = StringIO(), StringIO()
        with patch.object(self.module, 'CompanyDataCoordinator') as coordinator, redirect_stdout(stdout), redirect_stderr(stderr):
            coordinator.return_value.prepare.return_value = {'status': 'prepared', 'model_calls': 0}
            coordinator.return_value.prepare_acquisition.return_value = {'status': 'prepared', 'model_calls': 0}
            self.module.main(['--version', 'test', '--settings-root', str(self.root), *flags])
        return coordinator, stdout.getvalue(), stderr.getvalue()

    def test_explicit_environment_and_private_file_reach_both_company_configs(self):
        contact = 'Acquisition synthetic@example.test'
        for origin in ('explicit', 'environment', 'private_file'):
            with self.subTest(origin=origin):
                self.module.BASE = self.root / origin
                os.environ.pop(KEY, None)
                (self.root / '.env').unlink(missing_ok=True)
                flags = []
                if origin == 'explicit':
                    flags = ['--sec-user-agent', contact]
                elif origin == 'environment':
                    os.environ[KEY] = contact
                else:
                    private = self.root / '.env'
                    private.write_text(f'{KEY}="{contact}"\n')
                    private.chmod(0o600)
                coordinator, stdout, stderr = self.invoke(flags)
                calls = coordinator.return_value.prepare.call_args_list
                self.assertEqual(len(calls), 2)
                self.assertEqual({c.args[0]['symbol'] for c in calls}, {'MSFT', 'GOOGL'})
                self.assertTrue(all(c.args[0]['sec_user_agent'] == contact for c in calls))
                self.assertNotIn(contact, stdout + stderr)
                self.assertNotIn(contact, (self.module.BASE / 'test/summary.json').read_text())

    def test_missing_contact_rejected_before_any_output_or_coordinator(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke([])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.module.BASE.exists())

    def test_replay_uses_original_acquisition_without_contact_resolution(self):
        replay = self.root / 'frozen'
        for symbol in ('msft', 'googl'):
            folder = replay / symbol
            folder.mkdir(parents=True)
            (folder / 'acquisition.json').write_text(json.dumps({'documents': [{'source_id': symbol + '-original'}]}))
        with patch.object(self.module, 'resolve_sec_contact', side_effect=AssertionError('Replay must not read private settings')):
            coordinator, stdout, stderr = self.invoke(['--replay', str(replay)])
        self.assertEqual(coordinator.return_value.prepare.call_count, 0)
        calls = coordinator.return_value.prepare_acquisition.call_args_list
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(len(call.kwargs['acquisition_sha256']), 64)
            self.assertEqual(call.kwargs['source_ids'], [call.args[0].parent.name + '-original'])


if __name__ == '__main__':
    unittest.main()
