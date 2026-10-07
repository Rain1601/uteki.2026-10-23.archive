"""Maintained advisor policy loading; provider transport is always mocked."""
import asyncio
import json
import unittest

from apps.claude_dialogue.app import project_history
from apps.claude_dialogue.service import DialogueError, DialogueService
from scripts import claude_dialogue as d
from tests.unit import test_claude_dialogue_service as fixtures


class AdvisorPromptTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.DialogueServiceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.advisor=self.fixture.root/'advisor-v1.md'
        self.policy=self.fixture.root/'focus-policy.md'
        self.advisor.write_text('Act as an advisor. Codex implements and checks evidence.')
        self.policy.write_text('Version: focus-v1. Exactly ONE current action; backlog remains ranked.')
        self.service=DialogueService(self.fixture.base,credentials_root=self.fixture.root,
            client_factory=self.fixture.factory,advisor_prompt_path=self.advisor,focus_policy_path=self.policy)

    def send(self,message):
        return asyncio.run(self.service.send(message,self.service.history()['revision']))

    def test_request_snapshot_and_fingerprint_use_loaded_rules_and_keep_base_frozen(self):
        self.fixture.legacy('Original frozen question.')
        frozen={p:p.read_bytes() for p in (self.fixture.base/'session').rglob('*') if p.is_file()}
        state=self.send('Choose the current action.')
        body=json.loads(self.fixture.requests[-1].content)
        self.assertTrue(body['system'].startswith('PRIVATE_SYSTEM_INSTRUCTIONS\n\n'))
        self.assertIn(self.advisor.read_text(),body['system'])
        self.assertIn(self.policy.read_text(),body['system'])
        folder=self.fixture.base/'continuations/0002'
        snapshot=json.loads((folder/'system-prompt.json').read_bytes())
        fingerprint=json.loads((folder/'configuration.json').read_bytes())['fingerprints']['system_sha256']
        self.assertEqual(fingerprint,d._sha(body['system'].encode()))
        self.assertEqual(fingerprint,snapshot['effective_system_sha256'])
        receipt=json.loads((folder/'receipt.json').read_bytes())
        authorization=json.loads((folder/'authorization.json').read_bytes())
        self.assertEqual(receipt['system_prompt_snapshot_sha256'],d._sha((folder/'system-prompt.json').read_bytes()))
        self.assertEqual(authorization['system_prompt_snapshot_sha256'],receipt['system_prompt_snapshot_sha256'])
        self.assertEqual(state['turns'][-1]['system_prompt_snapshot_sha256'],receipt['system_prompt_snapshot_sha256'])
        self.assertEqual(frozen,{p:p.read_bytes() for p in frozen})
        projected=project_history(state)
        self.assertEqual(projected['configuration']['advisor_prompt']['status'],'ready')
        self.assertEqual(projected['configuration']['advisor_prompt']['component_sha256']['collaboration_focus'],
            d._sha(self.policy.read_bytes()))
        for private in ('PRIVATE_SYSTEM_INSTRUCTIONS',self.policy.read_text(),str(self.fixture.root)):
            self.assertNotIn(private,json.dumps(projected))

    def test_policy_edit_changes_next_revision_but_old_turn_checks_its_own_snapshot(self):
        first=self.send('First policy.')
        folder=self.fixture.base/'continuations/0001'
        frozen={p:p.read_bytes() for p in folder.iterdir()}
        window=(self.fixture.base/'window/configuration.json').read_bytes()
        self.policy.write_text('Version: focus-v2. One current action with observable acceptance.')
        refreshed=self.service.history()
        self.assertNotEqual(first['revision'],refreshed['revision'])
        self.assertEqual(refreshed['turns'][0]['status'],'completed')
        with self.assertRaisesRegex(DialogueError,'revision_conflict'):
            asyncio.run(self.service.send('Stale configuration.',first['revision']))
        self.send('Second policy.')
        body=json.loads(self.fixture.requests[-1].content)
        self.assertIn('Version: focus-v2',body['system'])
        self.assertNotIn('Version: focus-v1',body['system'])
        self.assertEqual(len(self.fixture.requests),2)
        self.assertEqual(frozen,{p:p.read_bytes() for p in frozen})
        self.assertEqual(window,(self.fixture.base/'window/configuration.json').read_bytes())
        self.assertEqual(self.service.history()['summary']['completed_turns'],2)

    def test_missing_or_blank_policy_blocks_send_without_hiding_verified_history(self):
        self.send('Existing complete turn.')
        original=self.policy.read_bytes()
        before={p:p.read_bytes() for p in self.fixture.base.rglob('*') if p.is_file()}
        calls=len(self.fixture.requests)
        for invalid in (None,b'',b' \n'):
            if invalid is None:self.policy.unlink()
            else:self.policy.write_bytes(invalid)
            with self.subTest(invalid=invalid):
                state=self.service.history()
                self.assertEqual(state['configuration']['advisor_prompt']['status'],'unavailable')
                self.assertEqual(state['turns'][0]['answer'],'Visible reply.\n第二行。')
                self.assertEqual(self.service.preflight('No implicit fallback.',state['revision'])['reason'],
                    'advisor_prompt_unavailable')
                with self.assertRaisesRegex(DialogueError,'advisor_prompt_unavailable'):
                    asyncio.run(self.service.send('No implicit fallback.',state['revision']))
        self.policy.write_bytes(original)
        self.assertEqual(len(self.fixture.requests),calls)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertEqual(self.service.history()['configuration']['advisor_prompt']['status'],'ready')

    def test_changed_historical_prompt_snapshot_is_rejected(self):
        self.send('Pinned prompt.')
        path=self.fixture.base/'continuations/0001/system-prompt.json'
        snapshot=json.loads(path.read_bytes())
        snapshot['components']['collaboration_focus']['text']='Changed historical rule.'
        path.write_bytes(d._json(snapshot))
        with self.assertRaisesRegex(DialogueError,'system_prompt_snapshot_changed'):
            self.service.history()

    def test_repository_default_is_not_resolved_from_credentials_directory(self):
        docs=self.fixture.root/'docs'
        docs.mkdir()
        (docs/'COLLABORATION_FOCUS.zh-CN.md').write_text('WRONG_CREDENTIALS_DIRECTORY_POLICY')
        service=DialogueService(self.fixture.base,credentials_root=self.fixture.root,client_factory=self.fixture.factory)
        state=service.history()
        self.assertEqual(state['configuration']['advisor_prompt']['status'],'ready')
        asyncio.run(service.send('Repository policy.',state['revision']))
        body=json.loads(self.fixture.requests[-1].content)
        self.assertIn('collaboration-focus-v1',body['system'])
        self.assertIn('每轮只设一个当前行动',body['system'])
        self.assertNotIn('WRONG_CREDENTIALS_DIRECTORY_POLICY',body['system'])


if __name__=='__main__':
    unittest.main()
