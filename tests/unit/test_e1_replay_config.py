"""Replay relocation must not reset credit, read gold, or silently change scope."""
from contextlib import closing, redirect_stdout
import io
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from uteki.infrastructure.research_data.financial_records import digest
from tests.unit.test_scoped_query_service import make_scoped_dataset

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = ROOT / 'experiments/agent_design/2026-10-09-e1-benchmark-v1'
SPEC = importlib.util.spec_from_file_location('e1_replay', EXPERIMENT / 'make_replay_config.py')
replay = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(replay)


class E1ReplayConfigTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.dataset = self.root / 'dataset'; self.dataset.mkdir(); make_scoped_dataset(self.dataset)
        manifest = json.loads((self.dataset / 'manifest.json').read_text())
        self.config = json.loads((EXPERIMENT / 'configs-v1/E1-02-sonnet.json').read_text())
        self.config['request']['scope'].update(snapshot_id=manifest['snapshot_id'], company_ids=['acme'],
            source_snapshot_ids=['acme-annual'], knowledge_cutoff='2032-05-01')
        self.config['request']['question'] = 'Synthetic replay question; no expected answer.'
        self.templates = self.root / 'configs'; self.templates.mkdir()
        self.template = self.templates / 'E1-02-fixture.json'; self.template.write_text(json.dumps(self.config))
        self.ledger = self.root / 'restored.sqlite'
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute('CREATE TABLE config(id INTEGER PRIMARY KEY,usd TEXT)'); db.execute("INSERT INTO config VALUES(1,'5')")
            db.execute('CREATE TABLE reservations(id TEXT PRIMARY KEY,reserved TEXT,actual TEXT,state TEXT)')
            db.execute("INSERT INTO reservations VALUES('old','1','0.3','settled')")
            db.execute("INSERT INTO reservations VALUES('uncertain','0.4',NULL,'unknown')")
            db.execute('CREATE TABLE autonomous_request_limit(id INTEGER PRIMARY KEY,maximum INTEGER)')
            db.execute('INSERT INTO autonomous_request_limit VALUES(1,500)')
        self.kwargs = dict(case_id='E1-02', template=self.template, dataset=self.dataset,
            dataset_manifest_sha256=digest((self.dataset / 'manifest.json').read_bytes()), ledger=self.ledger,
            credential_root=self.root, workspace=self.root / 'workspace', output_dir=self.root / 'new-config')

    def test_check_only_preserves_files_and_relocates_scope_without_creating_credit(self):
        before = {str(p): digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        config, evidence = replay.build_config(**self.kwargs)
        after = {str(p): digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(config['request']['scope'], self.config['request']['scope'])
        self.assertEqual(config['request']['dataset'], str(self.dataset.resolve()))
        self.assertEqual(evidence['restored_budget']['committed_usd'], '0.7')
        self.assertFalse(evidence['new_allowance_created'])
        arguments = ['--case', self.kwargs['case_id'], '--check-only']
        for key, value in self.kwargs.items():
            if key != 'case_id': arguments.extend(['--' + key.replace('_', '-'), str(value)])
        with redirect_stdout(io.StringIO()): self.assertEqual(replay.main(arguments), 0)
        self.assertEqual(before, {str(p): digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()})

    def test_missing_unlimited_or_overauthorized_ledger_rejected(self):
        with self.assertRaises(ValueError): replay.build_config(**{**self.kwargs, 'ledger': self.root/'missing'})
        for limit in (None, '101'):
            with closing(sqlite3.connect(self.ledger)) as db, db: db.execute('UPDATE config SET usd=?', (limit,))
            with self.assertRaises(ValueError): replay.build_config(**self.kwargs)

    def test_gold_feedback_case_and_dataset_hash_cannot_leak_or_drift(self):
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('must reject gold before reading')):
            with self.assertRaises(ValueError): replay.build_config(**{**self.kwargs, 'template': self.root/'evaluation-only/reference.json'})
        with self.assertRaises(ValueError): replay.build_config(**{**self.kwargs, 'case_id': 'E1-03'})
        with self.assertRaises(ValueError): replay.build_config(**{**self.kwargs, 'dataset_manifest_sha256': 'b'*64})
        self.config['request']['review_feedback'] = {}
        self.template.write_text(json.dumps(self.config))
        with self.assertRaises(ValueError): replay.build_config(**self.kwargs)

    def test_inflight_unknown_and_request_limit_are_not_reset(self):
        with closing(sqlite3.connect(self.ledger)) as db, db: db.execute("UPDATE reservations SET state='reserved' WHERE id='uncertain'")
        with self.assertRaises(ValueError): replay.build_config(**self.kwargs)
        with closing(sqlite3.connect(self.ledger)) as db, db:
            db.execute("UPDATE reservations SET state='unknown' WHERE id='uncertain'")
            db.execute('UPDATE autonomous_request_limit SET maximum=501')
        with self.assertRaises(ValueError): replay.build_config(**self.kwargs)


if __name__ == '__main__':
    unittest.main()
