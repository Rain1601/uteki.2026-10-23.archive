import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from apps.review_workbench.data import agent_run_results as results
from apps.review_workbench.data import agent_runs, agent_runs_experiments as experiments
from tests.unit.test_agent_runs_live import LiveRunFixture
from uteki.agents.runtime.model_configuration import build_configuration_snapshot
from apps.review_workbench.data.agent_runs_shared import call_configuration_snapshot

ROOT = Path(__file__).resolve().parents[2]


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode()


class ExperimentFixture:
    def __init__(self, root):
        self.root = root
        self.rows = []

    def file(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = value if isinstance(value, bytes) else encode(value)
        target.write_bytes(raw)
        return {'path': path, 'sha256': digest(raw)}

    def add(self, identity, *, company='cedar', year=2031, provider='aihubmix', model='sonnet', truncated=False, unknown=False,
            packet_schema='bounded-model-comparison-packet-v1'):
        base = 'experiments/fixture/' + identity
        sid = company + '-source'
        scope = {'company_id': company, 'source_snapshot_ids': [sid], 'comparison_years': [year],
                 'comparison_periods': [{'fiscal_year': year, 'period_end': f'{year}-06-30'}],
                 'report_period_end': f'{year}-06-30', 'currency': 'USD'}
        raw_source = f'{company}: cash flow 12 in {year}'.encode()
        source = {'source_snapshot_id': sid, 'source_sha256': digest(raw_source)}
        text = f'Cash flow {year}: 12'
        block = {'block_id': 'b1', 'text': text, 'text_hash': digest(text.encode()), 'company_id': company, 'source_snapshot_id': sid}
        packet = {'schema_version': packet_schema, 'scope': scope, 'source': source,
                  'task': {'instruction': 'Extract cash flow and explain the supplied evidence.'}, 'blocks': [block]}
        files = {'packet': self.file(base + '/packet.json', packet)}
        manifest = {'schema_version': 'bounded-model-comparison-prepared-manifest-v1', 'packet_sha256': files['packet']['sha256'],
                    'source_sha256': source['source_sha256'], 'input_block_ids': ['b1']}
        files['prepared_manifest'] = self.file(base + '/manifest.json', manifest)
        messages = [{'role': 'system', 'content': 'Return facts, analysis and gaps with source citations.'},
                    {'role': 'user', 'content': encode(packet).decode()}]
        files['request'] = self.file(base + '/request.json', {'messages': messages})
        inp = {'packet_sha256': files['packet']['sha256'], 'manifest_sha256': files['prepared_manifest']['sha256'],
               'system_sha256': digest(messages[0]['content'].encode()), 'messages_sha256': digest(encode(messages)),
               'scope': scope, 'source': source}
        start = {'provider': provider, 'requested_model': model, 'reasoning_configuration': 'thinking_enabled_high' if truncated else 'provider_default_unspecified',
                 'started_at': '2032-01-01T00:00:00+00:00', 'input': inp, 'status': 'started'}
        response = {**start, 'status': 'received', 'ended_at': '2032-01-01T00:00:02+00:00', 'elapsed_seconds': 2,
                    'returned_model': model, 'request_id': 'provider-request-1', 'finish_reason': 'length' if truncated else 'stop',
                    'usage_presence': 'absent' if unknown else 'reported', 'estimated_usd': None if unknown else '0.01',
                    'raw_usage': None if unknown else {'prompt_tokens': 100, 'completion_tokens': 50,
                                                      'completion_tokens_details': {'reasoning_tokens': 50 if truncated else 0}}}
        files['experiment_start'] = self.file(base + '/experiment-start.json', {'schema_version': 'small-model-comparison-v1', 'input': inp,
            'limits': {'max_output_tokens_per_arm': 50}, 'origin': 'independent_bounded_model_experiment'})
        files['start'] = self.file(base + '/start.json', start)
        files['response'] = self.file(base + '/response.json', response)
        files['validation'] = self.file(base + '/validation.json', {'status': 'invalid' if truncated else 'structure_and_citations_valid',
            'errors': ['non_stop_finish_reason', 'invalid_json'] if truncated else [], 'semantic_correctness': 'not_evaluated'})
        parsed = {'facts': [{'metric': 'cash_flow', 'period': str(year), 'period_end': f'{year}-06-30', 'value': 12,
                  'currency': 'USD', 'unit': 'USD million', 'block_id': 'b1', 'row': 1, 'column': 'c1', 'quote': text}],
                  'analysis': [{'claim': 'Reported cash flow is 12.', 'block_ids': ['b1']}], 'gaps': ['Only selected material was read.']}
        files['visible_output'] = self.file(base + '/visible-output.txt', b'' if truncated else encode(parsed))
        if not truncated:
            files['parsed'] = self.file(base + '/parsed.json', parsed)
        files['source_catalog'] = self.file(base + '/sources.json', [{**source, 'company_id': company, 'period_end': f'{year}-06-30'}])
        files['source_bytes'] = self.file(base + '/source.html', raw_source)
        row = {'id': identity, 'adapter': experiments.ADAPTER, 'agent': 'data', 'role': 'bounded_extraction_analysis',
               'title': f'{company} {year} · {model}', 'provider': provider, 'model': model, 'scope': scope, 'files': files}
        self.rows.append(row)
        self.save()
        return row

    def save(self):
        self.file(experiments.REGISTRATION, {'schema_version': 'model-trials-registration-v1', 'runs': self.rows})

    def mutate(self, row, key, change, *, repin=True):
        pin = row['files'][key]
        path = self.root / pin['path']
        value = json.loads(path.read_text())
        change(value)
        raw = encode(value)
        path.write_bytes(raw)
        if repin:
            pin['sha256'] = digest(raw)
        self.save()


class AgentResultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = ExperimentFixture(self.root)
        self.a = self.fixture.add('cedar-sonnet')
        self.b = self.fixture.add('cedar-deepseek', provider='deepseek', model='pro', truncated=True)

    def test_trace_identity_and_one_step_trial(self):
        run = agent_runs.load_run(self.root, self.a['id'])
        result = results.load_result(self.root, self.a['id'])
        self.assertEqual(result['trace_id'], self.a['id'])
        self.assertEqual(len(run['steps']), 1)
        self.assertEqual(run['origin'], 'independent_bounded_model_experiment')
        self.assertEqual(result['calls'][0]['request_id'], 'provider-request-1')
        self.assertNotEqual(result['calls'][0]['request_id'], result['trace_id'])
        self.assertEqual(result['result_view']['facts'][0]['value'], 12)
        self.assertIsNone(result['models'][0]['reasoning_effort'])
        self.assertEqual(len(result['binding']['result_sha256']), 64)
        self.assertEqual(results.load_result(self.root, self.a['id'])['binding'], result['binding'])

    def test_truncated_reasoning_is_not_a_visible_report(self):
        result = results.load_result(self.root, self.b['id'])
        self.assertEqual(result['result_view']['kind'], 'no_visible_output')
        self.assertEqual(result['result_view']['facts'], [])
        self.assertEqual(result['state']['delivery'], 'output_limited')
        self.assertEqual(result['usage']['output_tokens'], 50)
        self.assertEqual(result['models'][0]['reasoning_effort'], 'high')
        self.assertEqual(result['usage']['reasoning_tokens'], 50)

    def test_configurations_can_compare_same_task_and_input(self):
        value = results.compare_results(self.root, self.a['id'], self.b['id'])
        self.assertTrue(value['comparable'])
        self.assertIsNotNone(value['comparison_key'])
        self.assertFalse(results.compare_results(self.root, self.a['id'], self.a['id'])['comparable'])

    def test_other_company_and_period_never_fall_back(self):
        other = self.fixture.add('birch-model', company='birch', year=2030)
        result = results.load_result(self.root, other['id'])
        self.assertEqual(result['scope']['company_id'], 'birch')
        self.assertEqual(result['scope']['periods'], ['2030-06-30'])
        self.assertEqual(result['result_view']['facts'][0]['period'], '2030')
        self.assertFalse(results.compare_results(self.root, self.a['id'], other['id'])['comparable'])
        year = self.fixture.add('cedar-other-year', year=2030)
        self.assertFalse(results.compare_results(self.root, self.a['id'], year['id'])['comparable'])

    def test_named_pilot_packet_contract_is_supported_unknown_versions_are_not(self):
        row = self.fixture.add('birch-pilot', company='birch', year=2030, packet_schema='reproducibility-pilot-packet-v1')
        result = results.load_result(self.root, row['id'])
        self.assertEqual(result['scope']['company_id'], 'birch')
        self.assertEqual(result['result_view']['facts'][0]['period'], '2030')
        unsupported = self.fixture.add('unknown-packet', packet_schema='unregistered-packet-v9')
        with self.assertRaisesRegex(ValueError, 'scope differs'):
            results.load_result(self.root, unsupported['id'])

    def test_missing_unknown_blank_scope_fails(self):
        for replacement in (None, {}, {'company_id': ''}, {**self.a['scope'], 'company_id': 'unknown'}):
            with self.subTest(scope=replacement):
                old = self.a['scope']
                self.a['scope'] = replacement
                self.fixture.save()
                with self.assertRaises(ValueError):
                    results.load_result(self.root, self.a['id'])
                self.a['scope'] = old
        self.fixture.save()
        with self.assertRaises(KeyError):
            results.load_result(self.root, 'not-registered')

    def test_changed_pinned_response_is_rejected(self):
        self.fixture.mutate(self.a, 'response', lambda value: value.update(estimated_usd='5'), repin=False)
        with self.assertRaisesRegex(ValueError, 'integrity'):
            results.load_result(self.root, self.a['id'])

    def test_repin_changed_configuration_changes_binding(self):
        before = results.load_result(self.root, self.a['id'])['binding']
        self.fixture.mutate(self.a, 'response', lambda value: value.update(estimated_usd='0.02'))
        after = results.load_result(self.root, self.a['id'])['binding']
        self.assertNotEqual(before, after)

    def test_same_bytes_cannot_cross_artifact_owner(self):
        a, b = [agent_runs.load_run(self.root, r['id']) for r in (self.a, self.b)]
        ref = next(r for r in a['artifacts'] if r['label'] == 'packet.json')
        with self.assertRaises(ValueError):
            agent_runs.read_artifact(self.root, b['id'], ref['id'])
        page = agent_runs.read_artifact(self.root, a['id'], ref['id'])
        self.assertEqual(page['run_id'], a['id'])
        with self.assertRaises(ValueError):
            agent_runs.load_step(self.root, b['id'], a['steps'][0]['id'])

    def test_file_traversal_and_symlink_rejected(self):
        pin = self.a['files']['response']
        old = pin['path']
        pin['path'] = '../response.json'
        self.fixture.save()
        with self.assertRaises(ValueError):
            results.load_result(self.root, self.a['id'])
        pin['path'] = old
        self.fixture.save()
        path = self.root / old
        target = self.root / 'response-copy.json'
        target.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            results.load_result(self.root, self.a['id'])

    def test_cross_company_source_cannot_establish_scope(self):
        self.fixture.mutate(self.a, 'source_catalog', lambda values: values[0].update(company_id='birch'))
        with self.assertRaisesRegex(ValueError, 'company'):
            results.load_result(self.root, self.a['id'])

    def test_cross_period_fact_rejected_even_with_new_pin(self):
        self.fixture.mutate(self.a, 'parsed', lambda values: values['facts'][0].update(period='2030'))
        pin = self.a['files']['visible_output']
        raw = (self.root / self.a['files']['parsed']['path']).read_bytes()
        (self.root / pin['path']).write_bytes(raw)
        pin['sha256'] = digest(raw)
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, 'period'):
            results.load_result(self.root, self.a['id'])

    def test_analysis_reference_outside_selected_source_is_rejected(self):
        self.fixture.mutate(self.a, 'parsed', lambda value: value['analysis'][0].update(block_ids=['birch-block']))
        pin = self.a['files']['visible_output']
        raw = (self.root / self.a['files']['parsed']['path']).read_bytes()
        (self.root / pin['path']).write_bytes(raw)
        pin['sha256'] = digest(raw)
        self.fixture.save()
        with self.assertRaisesRegex(ValueError, 'citation'):
            results.load_result(self.root, self.a['id'])

    def test_unknown_usage_never_becomes_free(self):
        row = self.fixture.add('cedar-unknown', unknown=True)
        result = results.load_result(self.root, row['id'])
        self.assertIsNone(result['usage']['input_tokens'])
        self.assertEqual(result['usage']['unknown_usage_calls'], 1)
        self.assertEqual(result['usage']['unknown_cost_requests'], 1)

    def test_private_metadata_excluded_from_result_and_artifact(self):
        self.fixture.mutate(self.a, 'response', lambda value: value.update(api_key='do-not-display', headers={'authorization': 'private'}))
        result = results.load_result(self.root, self.a['id'])
        ref = next(r for r in result['artifacts'] if r['label'] == 'response.json')
        page = agent_runs.read_artifact(self.root, self.a['id'], ref['id'])
        for value in (result, page):
            text = json.dumps(value)
            self.assertNotIn('do-not-display', text)
            self.assertNotIn('authorization', text)
            self.assertNotIn('reservation_id', text)
        self.assertEqual(results.list_results(self.root, agent='risk')['results'], [])

    def test_registered_revision_required(self):
        with self.assertRaises(ValueError):
            results.load_result(self.root, self.a['id'], revision='0' * 64)
        with self.assertRaises(ValueError):
            agent_runs.read_events(self.root, self.a['id'])

    def test_response_id_does_not_substitute_for_provider_request_id(self):
        self.fixture.mutate(self.a, 'response', lambda value: value.update(request_id=None, response_id='response-42'))
        result = results.load_result(self.root, self.a['id'])
        self.assertIsNone(result['calls'][0]['request_id'])
        self.assertEqual(result['calls'][0]['response_id'], 'response-42')
        ref = next(r for r in result['artifacts'] if r['label'] == 'response.json')
        page = agent_runs.read_artifact(self.root, self.a['id'], ref['id'])
        self.assertEqual(page['content']['response_id'], 'response-42')

    def snapshot(self, **overrides):
        return build_configuration_snapshot({'provider': 'aihubmix', 'model': 'sonnet', 'max_tokens': 1024,
            'thinking': 'adaptive', 'reasoning_effort': 'medium', **overrides}, capture_kind='before_dispatch',
            capture_layer='http_request_before_dispatch', source='request.body',
            statuses={'temperature': 'not_sent'}, fingerprints={'input_sha256': self.a['files']['packet']['sha256']})

    def add_snapshot(self, snapshot):
        for key in ('start', 'response'):
            self.fixture.mutate(self.a, key, lambda value: value.update(configuration_snapshot=snapshot))

    def test_new_snapshot_controls_configuration_and_preserves_omitted_parameters(self):
        self.add_snapshot(self.snapshot())
        result = results.load_result(self.root, self.a['id'])
        call = result['calls'][0]
        self.assertEqual(call['thinking_mode'], 'adaptive')
        self.assertEqual(call['reasoning_effort'], 'medium')
        self.assertEqual(call['configuration_snapshot']['fields']['max_tokens']['value'], 1024)
        self.assertEqual(call['configuration_snapshot']['fields']['temperature']['status'], 'not_sent')
        self.assertEqual(result['models'][0]['configuration_snapshot'], call['configuration_snapshot'])
        ref = next(r for r in result['artifacts'] if r['label'] == 'response.json')
        page = agent_runs.read_artifact(self.root, self.a['id'], ref['id'])
        self.assertEqual(page['content']['configuration_snapshot'], call['configuration_snapshot'])

    def test_start_end_configuration_drift_is_rejected(self):
        self.add_snapshot(self.snapshot())
        self.fixture.mutate(self.a, 'response', lambda value: value.update(configuration_snapshot=self.snapshot(max_tokens=2048)))
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            results.load_result(self.root, self.a['id'])

    def test_snapshot_hash_and_private_fields_rejected(self):
        for mutate in (lambda snap: snap['fields']['max_tokens'].update(value=2048),
                       lambda snap: snap.update(api_key='must-not-display')):
            snapshot = self.snapshot()
            mutate(snapshot)
            self.add_snapshot(snapshot)
            with self.assertRaisesRegex(ValueError, 'Invalid model configuration snapshot'):
                results.load_result(self.root, self.a['id'])

    def test_snapshot_identity_cannot_override_call_model(self):
        self.add_snapshot(self.snapshot(model='different-model'))
        with self.assertRaisesRegex(ValueError, 'call identity'):
            results.load_result(self.root, self.a['id'])

    def test_historical_snapshot_does_not_guess_provider_defaults_or_sdk_retry(self):
        result = results.load_result(self.root, self.a['id'])
        fields = result['calls'][0]['configuration_snapshot']['fields']
        self.assertEqual(fields['max_tokens']['value'], 50)
        self.assertEqual(fields['max_tokens']['status'], 'recorded')
        for key in ('reasoning_effort', 'thinking', 'temperature', 'max_retries', 'base_url', 'api_format'):
            self.assertIsNone(fields[key]['value'])
            self.assertEqual(fields[key]['status'], 'not_recorded')
        self.assertIsNone(result['models'][0]['thinking_mode'])
        self.assertIsNone(result['models'][0]['reasoning_effort'])
        snapshot = call_configuration_snapshot({'provider': 'offline', 'requested_model': 'fixture'},
            config={'max_tokens': 12, 'api_key': 'never-display', 'base_url': 'https://private:secret@proxy.example'},
            limits={'automatic_retries': 7})
        self.assertEqual(snapshot['fields']['max_tokens']['value'], 12)
        self.assertIsNone(snapshot['fields']['base_url']['value'])
        self.assertIsNone(snapshot['fields']['max_retries']['value'])
        self.assertNotIn('never-display', json.dumps(snapshot))
        self.assertNotIn('private:secret', json.dumps(snapshot))

    def test_derived_historical_snapshot_keeps_existing_score_binding(self):
        result = results.load_result(self.root, self.a['id'])
        # Reproduce the published result-v1 fingerprint before configuration
        # snapshots existed. Derived display fields must not invalidate scores.
        legacy_models = copy.deepcopy(result['models'])
        for model in legacy_models:
            model.pop('configuration_snapshot')
            model['thinking_mode'] = 'provider_default_unspecified'
        stable = {k: result[k] for k in ('trace_id', 'revision', 'task', 'scope', 'configs', 'result_view')}
        stable['models'] = legacy_models
        stable['state'] = {k: result['state'].get(k) for k in ('execution', 'delivery', 'quality', 'adoption', 'stop_reason')}
        self.assertEqual(result['binding']['result_sha256'], results._digest(stable))

    def test_captured_configuration_hash_changes_score_binding(self):
        self.add_snapshot(self.snapshot())
        before = results.load_result(self.root, self.a['id'])['binding']
        self.add_snapshot(self.snapshot(max_tokens=2048))
        after = results.load_result(self.root, self.a['id'])['binding']
        self.assertNotEqual(before['result_sha256'], after['result_sha256'])


class FrozenResultIntegrationTests(unittest.TestCase):
    def test_three_frozen_trials_keep_recorded_limits_and_explicit_gaps(self):
        for identity, max_tokens, timeout in (
                ('amd-cash-flow-small-20261006-sonnet', 4000, 90),
                ('amd-cash-flow-small-20261006-deepseek', 4000, 90),
                ('amd-cash-flow-small-20261007-deepseek-24k', 24000, 180)):
            with self.subTest(identity=identity):
                call = results.load_result(ROOT, identity)['calls'][0]
                snapshot = call['configuration_snapshot']
                self.assertEqual(snapshot['capture_kind'], 'historical_partial')
                self.assertEqual(snapshot['effective_configuration'], 'unverified')
                self.assertEqual(snapshot['fields']['max_tokens']['value'], max_tokens)
                self.assertEqual(snapshot['fields']['timeout_seconds']['value'], timeout)
                self.assertEqual(snapshot['fields']['api_format']['status'], 'not_recorded')
                self.assertEqual(snapshot['fields']['reasoning_effort']['value'], None if identity.endswith('sonnet') else 'high')
                self.assertEqual(snapshot['fields']['thinking']['value'], None if identity.endswith('sonnet') else 'enabled')

    def test_real_small_trial_outputs_and_compare(self):
        sonnet = 'amd-cash-flow-small-20261006-sonnet'
        deepseek = 'amd-cash-flow-small-20261006-deepseek'
        pair = results.compare_results(ROOT, sonnet, deepseek)
        self.assertTrue(pair['comparable'])
        self.assertEqual(len(pair['left']['result_view']['facts']), 6)
        self.assertEqual(len(pair['left']['result_view']['analysis']), 3)
        self.assertEqual(pair['right']['result_view']['kind'], 'no_visible_output')
        self.assertEqual(pair['left']['usage']['input_tokens'], 5131)
        self.assertEqual(pair['right']['usage']['reasoning_tokens'], 4000)
        self.assertIsNone(pair['left']['calls'][0]['request_id'])
        self.assertIsNone(pair['left']['calls'][0]['response_id'])
        self.assertIsNone(pair['right']['calls'][0]['response_id'])

    def test_historical_final_refs_and_links_are_preserved_not_claimed_report(self):
        pair = results.compare_results(ROOT, 'amd-fy2023-main-agent-v2-parent', 'amd-fy2023-cash-flow-main-agent-v2-parent')
        self.assertFalse(pair['comparable'])
        self.assertEqual(pair['left']['result_view']['kind'], 'data_artifacts')
        self.assertEqual(pair['left']['result_view']['facts'], [])
        self.assertTrue(pair['left']['result_view']['artifacts'])
        self.assertTrue(pair['left']['links'])
        self.assertEqual(pair['left']['usage']['requests'], 7)
        self.assertNotEqual(pair['left']['task'], pair['right']['task'])


class LiveResultIntegrationTests(LiveRunFixture):
    def test_business_and_revenue_products_are_visible_scoped_candidates(self):
        context = self.step()
        products = {
            'business_map.json': {'company_id': 'cedar', 'businesses': [{'id': 'tools', 'name': 'Tools'}],
                                  'relationships': [], 'unknowns': [], 'api_key': 'must-not-display'},
            'revenue.json': {'company_id': 'cedar', 'charts': [{'id': 'revenue', 'total': 100,
                             'parts': [{'label': 'Tools', 'value': 100, 'secret': 'must-not-display'}]}],
                             'reported_subtotals': []},
        }
        for name, value in products.items():
            self.write(context, name, value)
        self.write(context, 'unregistered-private.json', {'businesses': [{'name': 'not-public'}]})
        self.rec.finish(self.context, result={'status': 'candidate'})
        options = {'observation_root': self.store, 'output_roots': (self.outputs,)}
        value = results.load_result(self.root, self.rec.root_run_id, **options)
        refs = value['result_view']['artifacts']
        self.assertEqual({r['label'] for r in refs}, set(products))
        self.assertEqual(value['state']['adoption'], 'not_recorded')
        self.assertFalse(value['comparison']['eligible'])
        for ref in refs:
            page = agent_runs.read_artifact(self.root, value['id'], ref['id'], **options)
            content = page['content']
            self.assertEqual(content['company_id'], 'cedar')
            self.assertIn('businesses' if ref['label'] == 'business_map.json' else 'charts', content)
            self.assertNotIn('must-not-display', json.dumps(content))
        private = next(r for r in value['artifacts'] if r['label'] == 'unregistered-private.json')
        self.assertNotEqual(private['availability'], 'available')

    def configured_call(self, context, snapshot, *, end=False):
        record = {'call_id': 'configured', 'provider': 'offline', 'requested_model': 'fixture-model',
                  'configuration_snapshot': snapshot, 'status': 'succeeded' if end else 'started',
                  'usage': None, 'usage_presence': 'unknown'}
        ref = self.write(context, 'model/calls/configured-' + ('end' if end else 'start') + '.json', record)
        context.emit('model_call.finished' if end else 'model_call.started', call_id='configured', record_ref=ref)

    def test_live_configuration_is_bound_to_dispatch_and_rejects_drift(self):
        context = self.step()
        snapshot = build_configuration_snapshot({'provider': 'offline', 'model': 'fixture-model',
            'max_tokens': 200, 'thinking': 'disabled'}, capture_kind='before_dispatch')
        self.configured_call(context, snapshot)
        options = {'observation_root': self.store, 'output_roots': (self.outputs,)}
        before = results.load_result(self.root, self.rec.root_run_id, **options)
        self.assertEqual(before['calls'][0]['configuration_snapshot'], snapshot)
        self.assertEqual(before['models'][0]['thinking_mode'], 'disabled')
        changed = build_configuration_snapshot({'provider': 'offline', 'model': 'fixture-model',
            'max_tokens': 300, 'thinking': 'disabled'}, capture_kind='before_dispatch')
        self.configured_call(context, changed, end=True)
        with self.assertRaisesRegex(ValueError, 'configuration changed'):
            results.load_result(self.root, self.rec.root_run_id, **options)
        historical = results.load_result(self.root, self.rec.root_run_id, revision=before['revision'], **options)
        self.assertEqual(before['binding'], historical['binding'])

    def test_live_result_binding_is_pinned_to_revision_and_keeps_candidate_owner(self):
        context = self.step()
        self.call(context, terminal=True)
        options = {'observation_root': self.store, 'output_roots': (self.outputs,)}
        before = results.load_result(self.root, self.rec.root_run_id, **options)
        child = self.rec.child(context, self.rec.output / 'child', kind='extraction', role='extractor',
                              origin='scripted_fixture', scope=self.scope)
        child.output.mkdir()
        self.write(child, 'result.json', {'status': 'candidate', 'records': [{'value': 7}]})
        self.rec.finish(child, result={'status': 'candidate'})
        self.rec.finish(self.context, result={'status': 'candidate_ready'})
        after = results.load_result(self.root, self.rec.root_run_id, **options)
        old = results.load_result(self.root, self.rec.root_run_id, revision=before['revision'], **options)
        self.assertEqual(type(after['binding']['revision']), int)
        self.assertEqual(old['binding'], before['binding'])
        self.assertNotEqual(after['binding'], before['binding'])
        self.assertEqual(after['usage']['requests'], 1)
        self.assertEqual(after['result_view']['artifacts'][0]['run_id'], child.run_id)
        self.assertEqual(after['result_view']['facts'], [])
        self.assertFalse(after['comparison']['eligible'])


if __name__ == '__main__':
    unittest.main()
