"""Offline configuration capture: no credentials, model requests or network."""
import asyncio
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import httpx2 as httpx
from agents import ModelSettings, OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from uteki.agents.runtime.call_costs import MeteredModel, pricing_snapshot, summarize
from uteki.agents.runtime.model_configuration import (
    CONFIGURATION_FIELDS, build_configuration_snapshot, capture_model_configuration,
    validate_configuration_snapshot,
)
from uteki.agents.runtime.run_budget import RunBudget


class ConfigurationTests(unittest.TestCase):
    def test_original_sixteen_field_snapshot_keeps_its_frozen_hash(self):
        # Captured with the original helper, before Top-K was introduced.
        keys = ('provider', 'model', 'api_format', 'base_url', 'max_tokens', 'thinking',
                'reasoning_effort', 'temperature', 'top_p', 'seed', 'response_format',
                'tool_choice', 'parallel_tool_calls', 'stream', 'timeout_seconds', 'max_retries')
        fields = {key: {'value': None, 'status': 'not_recorded', 'source': 'not_recorded'} for key in keys}
        for key, value in {'provider': 'deepseek', 'model': 'deepseek-v4-pro', 'max_tokens': 4000}.items():
            fields[key] = {'value': value, 'status': 'explicit', 'source': 'client_request'}
        fields['temperature'] = {'value': None, 'status': 'not_sent', 'source': 'request.omitted'}
        legacy = {'schema_version': 'model-call-config-v1', 'capture_kind': 'before_dispatch',
                  'capture_layer': 'sdk_adapter_before_dispatch', 'effective_configuration': 'unverified',
                  'fields': fields, 'fingerprints': {},
                  'sha256': '580f0e688b4d4c4445230a619fb5eb3feb3caae5ea18f9b7c1cfb0d7b90a5c84'}
        result = validate_configuration_snapshot(legacy)
        self.assertEqual(result, legacy)
        self.assertNotIn('top_k', result['fields'])
        result['fields']['max_tokens']['value'] = 999
        self.assertEqual(legacy['fields']['max_tokens']['value'], 4000)
        with self.assertRaises(ValueError):
            validate_configuration_snapshot(result)
        missing_other_field = deepcopy(legacy)
        del missing_other_field['fields']['top_p']
        with self.assertRaises(ValueError):
            validate_configuration_snapshot(missing_other_field)

    def test_top_k_capture_and_recorded_omission_policy_do_not_change_settings(self):
        settings = SimpleNamespace(max_tokens=4000, extra_args={'top_k': 12}, extra_body={'top_k': 40})
        captured = capture_model_configuration('offline', 'fixture', object(), (), {'model_settings': settings})
        self.assertEqual(captured['fields']['top_k'], {
            'value': 40, 'status': 'explicit', 'source': 'sdk.model_settings.extra_body.top_k'})
        self.assertEqual(settings.extra_body, {'top_k': 40})
        self.assertEqual(validate_configuration_snapshot(captured), captured)
        for value in (0, 40):
            self.assertEqual(build_configuration_snapshot({'top_k': value})['fields']['top_k']['value'], value)
        for value in (True, False, -1, 2.5, '40'):
            self.assertEqual(build_configuration_snapshot({'top_k': value})['fields']['top_k']['status'], 'not_recorded')
        omitted = build_configuration_snapshot({'top_p': .95}, capture_kind='before_dispatch',
            capture_layer='http_request_before_dispatch', statuses={'top_k': 'not_sent', 'temperature': 'not_sent'},
            sources={'top_k': 'policy.deepseek_top_k_unsupported',
                     'temperature': 'policy.deepseek_thinking_sampling_ignored'})
        self.assertEqual(omitted['fields']['top_k']['source'], 'policy.deepseek_top_k_unsupported')
        self.assertEqual(omitted['fields']['top_p']['value'], .95)
        self.assertEqual(validate_configuration_snapshot(omitted), omitted)
        with self.assertRaises(ValueError):
            build_configuration_snapshot({}, statuses={'top_k': 'not_sent'}, sources={'top_k': 'unsafe\nsource'})

    def test_historical_missing_is_not_a_default_and_hash_is_canonical(self):
        snapshot = build_configuration_snapshot({'model': 'deepseek-v4-pro', 'provider': 'deepseek', 'max_tokens': 4000})
        reordered = build_configuration_snapshot({'max_tokens': 4000, 'provider': 'deepseek', 'model': 'deepseek-v4-pro'})
        self.assertEqual(snapshot, reordered)
        self.assertEqual(snapshot['fields']['max_tokens']['status'], 'recorded')
        self.assertEqual(snapshot['fields']['temperature'], {'value': None, 'status': 'not_recorded', 'source': 'not_recorded'})
        body = {key: value for key, value in snapshot.items() if key != 'sha256'}
        self.assertEqual(snapshot['sha256'], hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest())
        self.assertEqual(validate_configuration_snapshot(snapshot), snapshot)

    def test_http_omission_is_distinct_from_unknown_and_zero(self):
        snapshot = build_configuration_snapshot({'max_retries': 0, 'stream': False, 'api_format': 'anthropic_messages'},
            capture_kind='before_dispatch', capture_layer='http_request_before_dispatch', source='client_request',
            statuses={'temperature': 'not_sent'})
        self.assertEqual(snapshot['fields']['temperature'], {'value': None, 'status': 'not_sent', 'source': 'request.omitted'})
        self.assertEqual(snapshot['fields']['top_p']['status'], 'not_recorded')
        self.assertEqual(snapshot['fields']['max_retries']['value'], 0)
        self.assertIs(snapshot['fields']['stream']['value'], False)
        self.assertEqual(validate_configuration_snapshot(snapshot), snapshot)
        with self.assertRaises(ValueError):
            build_configuration_snapshot({'temperature': 0}, statuses={'temperature': 'not_sent'})

    def test_allowlist_does_not_publish_credentials_or_freeform_nested_values(self):
        snapshot = build_configuration_snapshot({
            'provider': 'deepseek', 'model': 'deepseek-v4-pro', 'headers': {'authorization': 'secret-header'},
            'extra_body': {'api_key': 'secret-extra'}, 'base_url': 'https://user:secret-password@api.deepseek.com/v1',
            'thinking': {'type': 'enabled', 'secret': 'secret-thinking'},
            'response_format': {'type': 'json_schema', 'json_schema': {'description': 'secret-schema'}},
            'tool_choice': {'type': 'function', 'function': {'name': 'secret-tool-name', 'credentials': 'secret-tool-credential'}},
        }, fingerprints={'input_sha256': 'a' * 64, 'headers': 'secret-fingerprint'})
        encoded = json.dumps(snapshot)
        self.assertNotIn('secret-', encoded)
        self.assertEqual(set(snapshot['fields']), set(CONFIGURATION_FIELDS))
        self.assertEqual(snapshot['fields']['base_url']['status'], 'not_recorded')
        self.assertEqual(snapshot['fields']['thinking']['value'], {'type': 'enabled'})
        self.assertEqual(snapshot['fields']['response_format']['value'], {'type': 'json_schema'})
        for url in ('https://api.deepseek.com/v1?key=private', 'https://api.deepseek.com/v1#private',
                    'https://proxy.example/credential-path'):
            self.assertIsNone(build_configuration_snapshot({'base_url': url})['fields']['base_url']['value'])
        self.assertEqual(validate_configuration_snapshot(snapshot), snapshot)

    def test_invalid_field_types_and_tampered_snapshots_are_rejected(self):
        snapshot = build_configuration_snapshot({'max_tokens': True, 'seed': False, 'temperature': float('nan'),
                                                  'top_p': float('inf'), 'max_retries': -1})
        self.assertTrue(all(snapshot['fields'][key]['status'] == 'not_recorded'
                            for key in ('max_tokens', 'seed', 'temperature', 'top_p', 'max_retries')))
        for mutate in (lambda s: s.update(authorization='secret'),
                       lambda s: s['fields']['max_tokens'].update(value=100),
                       lambda s: s['fields']['model'].update(status='explicit'),
                       lambda s: s['fingerprints'].update(headers='b' * 64),
                       lambda s: s.update(sha256='f' * 64)):
            modified = deepcopy(snapshot)
            mutate(modified)
            with self.assertRaises(ValueError):
                validate_configuration_snapshot(modified)

    def test_sdk_capture_reads_actual_settings_and_client_without_network(self):
        requests = []
        def reject(request):
            requests.append(request)
            raise AssertionError('Capture cannot send requests')
        client = AsyncOpenAI(api_key='offline-test-key', base_url='https://api.deepseek.com', timeout=60, max_retries=0,
                             http_client=httpx.AsyncClient(transport=httpx.MockTransport(reject)))
        inner = OpenAIChatCompletionsModel('deepseek-v4-pro', client)
        settings = ModelSettings(max_tokens=4096, temperature=0, top_p=0.8,
            extra_body={'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'api_key': 'secret-key'},
            extra_args={'seed': 42, 'unknown': 'secret-extra-argument'},
            extra_headers={'authorization': 'secret-header'})
        try:
            snapshot = capture_model_configuration('deepseek', 'deepseek-v4-pro', inner,
                ('private-system', 'private-input', settings, [SimpleNamespace(name='private-tool')]), {})
        finally:
            asyncio.run(client.close())
        self.assertFalse(requests)
        fields = snapshot['fields']
        self.assertEqual(fields['max_tokens']['value'], 4096)
        self.assertEqual(fields['thinking']['value'], {'type': 'enabled'})
        self.assertEqual(fields['reasoning_effort']['value'], 'high')
        self.assertEqual(fields['api_format']['value'], 'chat_completions')
        self.assertEqual(fields['timeout_seconds']['value'], 60)
        self.assertEqual(fields['max_retries']['value'], 0)
        self.assertEqual(fields['temperature']['value'], 0)
        self.assertEqual(fields['seed']['value'], 42)
        self.assertEqual(snapshot['effective_configuration'], 'unverified')
        self.assertEqual(set(snapshot['fingerprints']), {'system_sha256', 'input_sha256', 'tools_sha256'})
        self.assertNotIn('private-', json.dumps(snapshot))
        self.assertNotIn('secret-', json.dumps(snapshot))
        self.assertEqual(settings.extra_body['api_key'], 'secret-key')
        self.assertEqual(validate_configuration_snapshot(snapshot), snapshot)

    def test_unknown_adapter_does_not_resolve_client_or_guess_provider_defaults(self):
        snapshot = capture_model_configuration('openai', 'fixture-model', 'fixture-model', (), {})
        for key in ('api_format', 'base_url', 'stream', 'thinking', 'temperature', 'max_retries'):
            self.assertEqual(snapshot['fields'][key]['status'], 'not_recorded')

    def test_selected_request_overrides_remain_explicit_without_copying_extras(self):
        client = SimpleNamespace(base_url='https://aihubmix.com/v1', timeout=45, max_retries=0)
        inner = OpenAIChatCompletionsModel('adapter-model', client)
        settings = ModelSettings(max_tokens=10, extra_args={'max_tokens': 20},
            extra_body={'max_tokens': 30, 'stream': True, 'metadata': 'private-value',
                        'provider': 'other-provider', 'model': 'other-model', 'api_format': 'responses',
                        'base_url': 'https://api.deepseek.com', 'timeout_seconds': 1, 'max_retries': 99})
        snapshot = capture_model_configuration('aihubmix', 'meter-model', inner, (), {'model_settings': settings})
        self.assertEqual(snapshot['fields']['model']['value'], 'meter-model')
        self.assertEqual(snapshot['fields']['provider']['value'], 'aihubmix')
        self.assertEqual(snapshot['fields']['api_format']['value'], 'chat_completions')
        self.assertEqual(snapshot['fields']['base_url']['value'], 'https://aihubmix.com/v1')
        self.assertEqual(snapshot['fields']['timeout_seconds']['value'], 45)
        self.assertEqual(snapshot['fields']['max_retries']['value'], 0)
        self.assertEqual(snapshot['fields']['max_tokens']['value'], 30)
        self.assertIs(snapshot['fields']['stream']['value'], True)
        self.assertEqual(snapshot['fields']['stream']['source'], 'sdk.model_settings.extra_body.stream')
        self.assertNotIn('private-value', json.dumps(snapshot))

    def test_meter_preserves_dispatch_snapshot_on_success_or_exception(self):
        @dataclass
        class Usage:
            input_tokens: int = 100
            output_tokens: int = 20
        class Fake:
            async def get_response(self, **kwargs):
                settings = kwargs['model_settings']
                should_fail = settings.max_tokens == 101
                settings.max_tokens = 999
                settings.extra_body['thinking']['type'] = 'disabled'
                if should_fail:
                    raise TimeoutError('secret-failure-message')
                return SimpleNamespace(usage=Usage(), response_id='offline-id')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            budget = RunBudget(folder/'budget.sqlite', '1')
            for limit in (100, 101):
                model = MeteredModel(Fake(), folder/'calls', 'review', 'aihubmix', 'gpt-5.4-mini',
                                     pricing_snapshot('aihubmix', 'gpt-5.4-mini'), budget)
                invocation = model.get_response(model_settings=SimpleNamespace(max_tokens=limit,
                    extra_body={'thinking': {'type': 'enabled'}}))
                if limit == 101:
                    with self.assertRaises(TimeoutError):
                        asyncio.run(invocation)
                else:
                    asyncio.run(invocation)
            for start in (folder/'calls').glob('*-start.json'):
                before = json.loads(start.read_text())['configuration_snapshot']
                after = json.loads(start.with_name(start.name.replace('-start', '-end')).read_text())['configuration_snapshot']
                self.assertEqual(before, after)
                self.assertIn(before['fields']['max_tokens']['value'], (100, 101))
                self.assertEqual(before['fields']['thinking']['value'], {'type': 'enabled'})
                self.assertEqual(validate_configuration_snapshot(after), before)
            self.assertEqual(budget.summary()['in_flight_requests'], 0)
            self.assertEqual(budget.summary()['unknown_requests'], 1)
            self.assertNotIn('secret-failure', json.dumps(summarize(folder/'calls')))
