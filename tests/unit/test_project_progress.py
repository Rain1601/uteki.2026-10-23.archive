"""Read-only project summary in isolated repositories; no model or network calls."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts.check_project_progress import inspect_project, main


class ProjectProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '-q')
        self.write('TODO.md', '| 1 | [x] Implemented claim | [proof](proof.md) |\n- [ ] Needs review\n')
        self.write('proof.md', 'A file is not acceptance evidence by itself.\n')
        self.write('docs/ROADMAP.zh-CN.md', '# Roadmap\n- 状态：工作提案\n')
        self.write('docs/FEATURE_PLAN.md', '# Proposed capability\n状态：提案，未实现\n')
        self.write('openspec/specs/tool/spec.md', '# Tool requirements\nStatus: draft\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '-qm', 'Add proposal')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True, shell=False)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['--root', str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def test_preserves_declarations_without_verifying_proposal_or_checkmarks(self):
        before = self.git('status', '--porcelain').stdout
        report = inspect_project(self.root, 1)
        self.assertEqual(report['verification'], 'not_performed')
        self.assertEqual([r['declared'] for r in report['todo']['tasks']], ['checked', 'unchecked'])
        self.assertEqual([r['line'] for r in report['todo']['tasks']], [1, 2])
        plan = next(d for d in report['documents'] if d['path'] == 'docs/FEATURE_PLAN.md')
        self.assertEqual(plan['declared_status'], [{'line': 2, 'text': '状态：提案，未实现'}])
        self.assertEqual(report['todo']['local_links'][0]['evidence_exists'], True)
        self.assertEqual(report['git']['working_tree'], 'clean')
        self.assertEqual(len(report['git']['recent_commits']), 1)
        self.assertEqual(self.git('status', '--porcelain').stdout, before)
        code, output, _ = self.invoke('--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)['verification'], 'not_performed')

    def test_missing_and_outside_links_are_not_evidence_and_optional_failure(self):
        outside = Path(self.temp.name) / 'private.md'
        outside.write_text('must not appear in summary')
        (self.root / 'escape.md').symlink_to(outside)
        self.write('TODO.md', '[ok](proof.md) [missing](absent.md) [outside](../private.md)\n'
                   '[symlink](escape.md) [remote](https://example.test) [anchor](#heading)\n')
        report = inspect_project(self.root)
        links = report['todo']['local_links']
        self.assertEqual([r['status'] for r in links], ['exists', 'missing', 'outside_root', 'outside_root'])
        self.assertIsNone(links[2]['evidence_exists'])
        self.assertNotIn('must not appear', json.dumps(report))
        self.assertEqual(self.invoke()[0], 0)
        self.assertEqual(self.invoke('--check-links')[0], 1)

    def test_non_git_root_reports_error_without_creating_files(self):
        empty = Path(self.temp.name) / 'empty'
        empty.mkdir()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['--root', str(empty), '--json'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err.getvalue())['verification'], 'not_performed')
        self.assertEqual(list(empty.iterdir()), [])

    def test_invalid_limit_is_rejected(self):
        for value in ('0', '-1', 'no', '1.5'):
            with self.subTest(value=value), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(['--root', str(self.root), '--limit', value])
            self.assertEqual(raised.exception.code, 2)

    def test_document_symlink_outside_root_is_not_read(self):
        outside = Path(self.temp.name) / 'outside.md'
        outside.write_text('# Private title\n状态：secret\n')
        (self.root / 'docs/EXTERNAL_PLAN.md').symlink_to(outside)
        report = inspect_project(self.root)
        document = next(d for d in report['documents'] if d['path'] == 'docs/EXTERNAL_PLAN.md')
        self.assertEqual(document['status'], 'outside_root')
        self.assertIsNone(document['title'])
        self.assertNotIn('Private title', json.dumps(report))

    def test_limit_caps_recent_commits_and_keeps_subject_as_data(self):
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                 'commit', '--allow-empty', '-qm', 'Proposal only; not implemented')
        report = inspect_project(self.root, 1)
        self.assertEqual(len(report['git']['recent_commits']), 1)
        self.assertEqual(report['git']['recent_commits'][0]['subject'], 'Proposal only; not implemented')
        self.assertEqual(report['verification'], 'not_performed')
