"""Persistent Claude dialogue contracts; every HTTP request uses MockTransport."""
import asyncio
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx2 as httpx

from apps.claude_dialogue.runtime_support import validate_configuration_snapshot


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('claude_dialogue_under_test', ROOT / 'scripts' / 'claude_dialogue.py')
dialogue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = dialogue
SPEC.loader.exec_module(dialogue)


class ClaudeDialogueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.credentials = self.root / 'credentials'
        self.credentials.mkdir()
        self.secret = 'offline-dialogue-secret'
        self.environment = patch.dict(os.environ, {'AIHUBMIX_API_KEY': self.secret}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.requests = []
        self.clients = []
        self.client_options = []
        self.serial = 0
        self.payload = {
            'id': 'msg_dialogue_test', 'model': 'claude-opus-5-5', 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 100, 'output_tokens': 20, 'cache_read_input_tokens': 10},
            'content': [
                {'type': 'thinking', 'thinking': 'HIDDEN_DIALOGUE_THOUGHT', 'signature': 'HIDDEN_DIALOGUE_SIGNATURE'},
                {'type': 'text', 'text': 'First answer.\n第二行。'},
            ],
        }

    def new_session(self, **overrides):
        self.serial += 1
        fixture = self.root / f'fixture-{self.serial}'
        fixture.mkdir()
        system = fixture / 'system.md'
        system.write_text('Discuss the supplied evidence.\n使用清晰的中文。', encoding='utf-8')
        price = fixture / 'price.json'
        price.write_text(json.dumps({
            'model': 'claude-opus-5-5', 'input_per_million': '4',
            'output_per_million': '20', 'cache_read_per_million': '0.2',
            'source_url': 'https://example.invalid/explicit-test-price', 'checked_date': '2026-10-07',
        }), encoding='utf-8')
        self.init_arguments = dict(system_file=system, model='claude-opus-5-5', budget_usd='2.00',
                                   max_calls=4, max_tokens=100, price_file=price) | overrides
        session = fixture / 'session'
        dialogue.init_session(session, **self.init_arguments)
        return session

    def message_file(self, text):
        self.serial += 1
        path = self.root / f'message-{self.serial}.md'
        path.write_text(text, encoding='utf-8')
        return path

    def respond(self, request):
        self.requests.append(request)
        return httpx.Response(200, json=self.payload, headers={'request-id': 'req_dialogue_test'})

    def factory(self, **kwargs):
        self.client_options.append(kwargs.copy())
        kwargs['transport'] = httpx.MockTransport(self.respond)
        client = httpx.AsyncClient(**kwargs)
        self.clients.append(client)
        return client

    def run_turn(self, session, text='First question.\n请解释。'):
        return asyncio.run(dialogue.turn(session, message_file=self.message_file(text),
                                        credentials_root=self.credentials, client_factory=self.factory))

    def session_text(self, session):
        return '\n'.join(path.read_text(encoding='utf-8') for path in session.rglob('*') if path.is_file())

    def test_initialization_is_explicit_and_never_overwrites_existing_session(self):
        session = self.new_session()
        original = {name: (session / name).read_bytes() for name in ('session.json', 'system.txt', 'price.json')}
        summary = dialogue.inspect_session(session)
        self.assertIsInstance(summary, dict)
        self.assertEqual(summary['attempted_turns'], 0)
        self.assertEqual(summary['completed_turns'], 0)
        self.assertEqual(summary['unknown_cost_turns'], 0)
        self.assertNotIn('history', summary)
        self.assertNotIn('Discuss the supplied evidence.', json.dumps(summary))
        with self.assertRaises(dialogue.DialogueError):
            dialogue.init_session(session, **self.init_arguments)
        for name, content in original.items():
            self.assertEqual((session / name).read_bytes(), content)
        self.assertEqual(self.requests, [])

    def test_second_request_replays_exact_visible_history_and_private_artifacts(self):
        session = self.new_session()
        immutable = {name: (session / name).read_bytes() for name in ('session.json', 'system.txt', 'price.json')}
        first_question = 'First question.\n请解释。'
        first_answer = self.payload['content'][-1]['text']
        first_receipt = self.run_turn(session, first_question)
        self.payload['content'][-1]['text'] = 'Second answer.'
        second_question = 'What follows from that?\n保留原文。'
        second_receipt = self.run_turn(session, second_question)
        self.assertEqual(first_receipt['status'], 'completed')
        self.assertEqual(second_receipt['status'], 'completed')
        self.assertEqual(len(self.requests), 2)
        summary = dialogue.inspect_session(session, include_history=True)
        self.assertEqual(summary['completed_turns'], 2)
        self.assertEqual(summary['attempted_turns'], 2)
        self.assertEqual(Decimal(summary['estimated_spent_usd']), Decimal('0.001604'))
        self.assertEqual(Decimal(summary['held_usd']), 0)
        body = json.loads(self.requests[1].content)
        self.assertEqual(body['messages'], [
            {'role': 'user', 'content': first_question},
            {'role': 'assistant', 'content': first_answer},
            {'role': 'user', 'content': second_question},
        ])
        self.assertEqual(summary['history'], body['messages'] + [{'role': 'assistant', 'content': 'Second answer.'}])
        self.assertEqual(body['model'], 'claude-opus-5-5')
        self.assertEqual(body['thinking'], {'type': 'adaptive'})
        self.assertEqual(body['output_config'], {'effort': 'high'})
        self.assertFalse(body['stream'])
        self.assertEqual(set(body), {'model', 'system', 'messages', 'max_tokens', 'thinking', 'output_config', 'stream'})
        for number, request in enumerate(self.requests, 1):
            folder = session / 'turns' / f'{number:04d}'
            for name in ('user.md', 'request.json', 'request.sha256', 'configuration.json', 'started.json', 'answer.md', 'receipt.json'):
                self.assertTrue((folder / name).is_file(), name)
            self.assertEqual((folder / 'request.json').read_bytes(), request.content)
            self.assertEqual((folder / 'request.sha256').read_text().strip(), hashlib.sha256(request.content).hexdigest())
            configuration = validate_configuration_snapshot(json.loads((folder / 'configuration.json').read_text()))
            request_body = json.loads(request.content)
            self.assertEqual(configuration['capture_layer'], 'http_request_before_dispatch')
            self.assertEqual(configuration['fields']['max_retries']['value'], 0)
            self.assertEqual(configuration['fields']['timeout_seconds']['value'], 240)
            self.assertEqual(configuration['fields']['reasoning_effort']['value'], 'high')
            self.assertEqual(configuration['fingerprints']['system_sha256'],
                             hashlib.sha256(request_body['system'].encode()).hexdigest())
            input_bytes = json.dumps(request_body['messages'], ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()
            self.assertEqual(configuration['fingerprints']['input_sha256'], hashlib.sha256(input_bytes).hexdigest())
            for field in ('temperature', 'top_p', 'top_k', 'seed', 'response_format', 'tool_choice', 'parallel_tool_calls'):
                self.assertEqual(configuration['fields'][field]['status'], 'not_sent')
            self.assertEqual(str(request.url), 'https://aihubmix.com/v1/messages')
            self.assertEqual(request.headers['x-api-key'], self.secret)
        self.assertEqual((session / 'turns' / '0001' / 'answer.md').read_text(), first_answer)
        for name, content in immutable.items():
            self.assertEqual((session / name).read_bytes(), content)
        for path in [session, *session.rglob('*')]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600, str(path))
        combined = self.session_text(session) + self.requests[1].content.decode() + json.dumps(second_receipt)
        for hidden in (self.secret, 'HIDDEN_DIALOGUE_THOUGHT', 'HIDDEN_DIALOGUE_SIGNATURE'):
            self.assertNotIn(hidden, combined)
        self.assertFalse((session / 'transcript.json').exists())
        self.assertTrue(all(client.is_closed for client in self.clients))
        for options in self.client_options:
            self.assertEqual(options['timeout'], 240)
            self.assertFalse(options['follow_redirects'])
            self.assertFalse(options['trust_env'])

    def test_truncated_answer_settles_known_cost_and_blocks_continuation(self):
        session = self.new_session()
        self.payload['stop_reason'] = 'max_tokens'
        receipt = self.run_turn(session)
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['stop_reason'], 'max_tokens')
        self.assertEqual(Decimal(str(receipt['estimated_usd'])), Decimal('0.000802'))
        summary = dialogue.inspect_session(session)
        self.assertTrue(summary['blocked'])
        self.assertEqual(Decimal(summary['estimated_spent_usd']), Decimal('0.000802'))
        self.assertEqual(Decimal(summary['held_usd']), 0)
        with self.assertRaises(dialogue.DialogueError):
            self.run_turn(session, 'Continue.')
        self.assertEqual(len(self.requests), 1)

    def test_http_timeout_and_unknown_usage_hold_cost_and_do_not_retry(self):
        for failure in ('http', 'timeout', 'usage_missing', 'usage_malformed', 'cache_write'):
            with self.subTest(failure=failure):
                session = self.new_session()
                before = len(self.requests)
                payload = json.loads(json.dumps(self.payload))
                if failure == 'usage_missing':
                    payload.pop('usage')
                elif failure == 'usage_malformed':
                    payload['usage']['input_tokens'] = True
                elif failure == 'cache_write':
                    payload['usage']['cache_creation_input_tokens'] = 3

                def respond(request):
                    self.requests.append(request)
                    if failure == 'http':
                        return httpx.Response(429, text='PRIVATE_PROVIDER_ERROR ' + self.secret)
                    if failure == 'timeout':
                        raise httpx.ReadTimeout('PRIVATE_PROVIDER_ERROR ' + self.secret, request=request)
                    return httpx.Response(200, json=payload)

                self.respond = respond
                receipt = self.run_turn(session)
                self.assertEqual(receipt['status'], 'failed')
                self.assertIsNone(receipt['estimated_usd'])
                summary = dialogue.inspect_session(session)
                self.assertTrue(summary['blocked'])
                self.assertEqual(summary['unknown_cost_turns'], 1)
                self.assertEqual(Decimal(summary['estimated_spent_usd']), 0)
                self.assertEqual(Decimal(summary['held_usd']), Decimal(receipt['reserved_usd']))
                self.assertGreater(Decimal(summary['held_usd']), 0)
                with self.assertRaises(dialogue.DialogueError):
                    self.run_turn(session, 'Continue.')
                self.assertEqual(len(self.requests), before + 1)
                persisted = self.session_text(session) + json.dumps(receipt)
                self.assertNotIn(self.secret, persisted)
                self.assertNotIn('PRIVATE_PROVIDER_ERROR', persisted)
                self.assertTrue(self.clients[-1].is_closed)

    def test_max_calls_and_insufficient_budget_reject_before_dispatch(self):
        session = self.new_session(max_calls=1)
        self.run_turn(session)
        with self.assertRaises(dialogue.DialogueError):
            self.run_turn(session, 'Exceeds call limit.')
        self.assertEqual(len(self.requests), 1)
        low_budget = self.new_session(budget_usd='0.000001')
        with self.assertRaises(dialogue.DialogueError):
            self.run_turn(low_budget, 'Exceeds worst-case reservation.')
        self.assertEqual(len(self.requests), 1)

    def test_tampered_history_is_rejected_before_next_request(self):
        for filename in ('user.md', 'answer.md', 'request.json'):
            with self.subTest(filename=filename):
                session = self.new_session()
                self.run_turn(session)
                before = len(self.requests)
                path = session / 'turns' / '0001' / filename
                path.write_text(path.read_text() + '\nTAMPERED', encoding='utf-8')
                with self.assertRaises(dialogue.DialogueError):
                    self.run_turn(session, 'Use the prior history.')
                self.assertEqual(len(self.requests), before)

    def test_concurrent_turn_is_rejected_and_lock_is_released_after_completion(self):
        session = self.new_session()

        async def exercise():
            entered, release = asyncio.Event(), asyncio.Event()

            async def respond(request):
                self.requests.append(request)
                entered.set()
                await release.wait()
                return httpx.Response(200, json=self.payload)

            self.respond = respond
            task = asyncio.create_task(dialogue.turn(session, message_file=self.message_file('In flight.'),
                                      credentials_root=self.credentials, client_factory=self.factory))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                with self.assertRaises(dialogue.DialogueError):
                    await asyncio.wait_for(dialogue.turn(session, message_file=self.message_file('Concurrent.'),
                                           credentials_root=self.credentials, client_factory=self.factory), 2)
                self.assertEqual(len(self.requests), 1)
            finally:
                release.set()
                await task
            await dialogue.turn(session, message_file=self.message_file('After completion.'),
                                credentials_root=self.credentials, client_factory=self.factory)

        asyncio.run(exercise())
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(client.is_closed for client in self.clients))

    def test_invalid_model_limits_and_unpriced_snapshot_fail_before_initialization(self):
        for overrides in ({'model': 'claude-sonnet-5-5'}, {'model': 'claude-opus-latest'},
                          {'max_calls': 0}, {'max_tokens': 0}, {'max_tokens': 16001},
                          {'budget_usd': 'NaN'}, {'budget_usd': '-1'}, {'budget_usd': 'INVALID_PRIVATE_VALUE'}):
            with self.subTest(overrides=overrides), self.assertRaises(dialogue.DialogueError):
                self.new_session(**overrides)
        session = self.new_session()
        price = self.init_arguments['price_file']
        payload = json.loads(price.read_text())
        missing_rate = dict(payload)
        missing_rate.pop('cache_read_per_million')
        for index, invalid in enumerate((missing_rate,
                payload | {'input_per_million': 'INVALID_PRIVATE_VALUE'},
                payload | {'checked_date': 'INVALID_PRIVATE_VALUE'})):
            with self.subTest(invalid_price=index):
                price.write_text(json.dumps(invalid), encoding='utf-8')
                with self.assertRaises(dialogue.DialogueError) as error:
                    dialogue.init_session(session.parent / f'unpriced-{index}', **self.init_arguments)
                self.assertNotIn('INVALID_PRIVATE_VALUE', str(error.exception))
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
