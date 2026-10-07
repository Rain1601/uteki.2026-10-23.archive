"""Run inspection uses explicit identities and keeps distinct result states."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from lxml import html
from apps.review_workbench.pages import agent_runs as view


def run(identity='orchard-2033'):
    ref = {'id': 'artifact-one', 'run_id': identity, 'label': 'Candidate </script><script>bad()</script>',
           'kind': 'candidate', 'availability': 'available', 'size_bytes': 0, 'sha256': 'a' * 64}
    return {'schema_version': 'agent-run-view-v1', 'id': identity, 'root_run_id': identity,
        'agent': 'data', 'title': 'Orchard <img src=x onerror=bad()>', 'origin': 'scripted_fixture',
        'live': False, 'root_terminal': True, 'revision': 6,
        'state': {'execution': 'ended', 'connection': 'historical', 'delivery': 'candidate_ready',
                  'quality': 'not_evaluated', 'adoption': 'unchanged_candidate', 'stop_reason': 'host_reference_checks_passed'},
        'scope': {'company_id': 'orchard', 'periods': ['2033'], 'knowledge_cutoff': '2034-03-02',
                  'source_snapshot_ids': ['orchard-source'], 'snapshot_id': 'orchard-snapshot'},
        'steps': [{'id': 'step-1', 'run_id': identity, 'ordinal': 1, 'action': 'invalid',
                   'status': 'rejected', 'phase': 'decision', 'elapsed_seconds': None,
                   'files': [ref], 'call_ids': ['call-one'], 'child_run_ids': []}],
        'artifacts': [ref], 'inputs': [], 'configs': [], 'diagnostics': [], 'links': [],
        'calls': [{'call_id': 'call-one', 'run_id': identity, 'step_id': 'step-1', 'role': 'planner',
                   'requested_model': 'example', 'status': 'succeeded', 'input_tokens': 0,
                   'output_tokens': 7, 'cached_tokens': None, 'reasoning_tokens': None,
                   'elapsed_seconds': None, 'estimated_usd': None, 'files': []}],
        'usage': {'requests': 1, 'input_tokens': 0, 'output_tokens': 7, 'unknown_usage_calls': 0,
                  'known_estimated_usd': None, 'actual_billed_usd': None,
                  'roles': [{'role': 'planner', 'input_tokens': 0}]}}


class AgentRunsPageTests(unittest.TestCase):
    def setUp(self):
        self.example = run()
        self.listing = patch.object(view, 'list_runs', return_value=[deepcopy(self.example)]).start()
        self.loader = patch.object(view, 'load_run', return_value=deepcopy(self.example)).start()
        self.addCleanup(patch.stopall)

    def render(self, **selection):
        text = view.render_agent_runs(Path('/synthetic'), {key:[value] for key,value in selection.items()})
        return text, html.fromstring(text)

    def test_no_run_is_implicitly_selected(self):
        _, doc = self.render()
        self.loader.assert_not_called()
        self.assertIn('Select a run', doc.text_content())
        self.assertFalse(doc.xpath('//*[@data-panel]'))
        config = json.loads(doc.get_element_by_id('ar-config').text)
        self.assertIsNone(config['detail'])

    def test_other_agents_do_not_borrow_data_runs(self):
        for agent in ('analysis','risk','portfolio'):
            with self.subTest(agent=agent):
                self.listing.reset_mock()
                _, doc = self.render(agent=agent)
                self.listing.assert_not_called()
                self.assertFalse(doc.xpath('//*[@data-run-row]'))
                self.assertIn('Not connected' if agent == 'analysis' else 'Backend not implemented',doc.text_content())

    def test_states_failures_unknowns_and_zero_are_not_conflated(self):
        self.loader.return_value['usage'].update(own={'requests': 1, 'input_tokens': 0, 'actual_billed_usd': None}, unknown_cost_requests=1)
        _, doc = self.render(run=self.example['id'],step='step-1',tab='usage')
        for key,value in self.example['state'].items():
            if key != 'connection': self.assertIn(value,doc.xpath(f'//*[@data-state="{key}"]')[0].text_content())
        self.assertIn('rejected',doc.get_element_by_id('ar-step-detail').text_content())
        self.assertIn('Not recorded',doc.get_element_by_id('ar-step-detail').text_content())
        self.assertEqual(doc.xpath('//*[@data-usage="input_tokens"]')[0].text_content(),'0')
        self.assertIn('Not recorded',doc.xpath('//*[@data-usage="actual_billed_usd"]')[0].text_content())
        self.assertEqual(doc.xpath('//*[@data-own-usage="requests"]')[0].text_content(),'1')
        self.assertEqual(doc.xpath('//*[@data-usage="unknown_cost_requests"]')[0].text_content(),'1')
        self.assertEqual([n.get('data-panel') for n in doc.xpath('//*[@data-panel][not(@hidden)]')],['usage'])

    def test_scope_and_child_identity_are_not_inferred_from_titles(self):
        self.example['steps'][0]['child_run_ids'] = ['harbor-named-but-explicit-child']
        self.loader.return_value = self.example
        _,doc=self.render(run=self.example['id'],step='step-1')
        self.assertIn('orchard · 2033 · 2034-03-02',doc.text_content())
        self.assertTrue(doc.xpath('//button[@data-child-run="harbor-named-but-explicit-child"]'))
        self.assertFalse(doc.xpath('//a[contains(@href,"harbor-named-but-explicit-child")]'))
        with self.assertRaises(ValueError): self.render(run=self.example['id'],step='foreign-step')
        with self.assertRaises(ValueError): self.render(run=self.example['id'],artifact='foreign-artifact')

    def test_trace_links_to_result_and_step_shows_only_its_model_calls(self):
        self.example['calls'][0].update(provider='fixture-provider', reasoning_effort='high', request_id='provider-request-one')
        self.example['calls'].append({**self.example['calls'][0], 'call_id': 'other-call', 'requested_model': 'other-model', 'step_id': 'other-step'})
        self.loader.return_value = self.example
        _, doc = self.render(run=self.example['id'], step='step-1')
        self.assertTrue(doc.xpath('//a[contains(@href,"/agent-results?") and contains(text(),"Trace ID:")]'))
        text = doc.get_element_by_id('ar-step-detail').text_content()
        self.assertIn('fixture-provider', text)
        self.assertIn('high', text)
        self.assertIn('provider-request-one', text)
        self.assertNotIn('other-model', text)

    def test_untrusted_titles_artifacts_and_json_cannot_create_html(self):
        self.example['links']=[{'label':'unsafe','href':'javascript:bad()'},{'label':'remote','href':'//bad.test/path'},
                               {'label':'allowed','href':'/data-workspace?dataset=orchard'}]
        self.loader.return_value=self.example
        text,doc=self.render(run=self.example['id'])
        self.assertFalse(doc.xpath('//img'))
        self.assertFalse(doc.xpath('//script[text()="bad()"]'))
        self.assertFalse(doc.xpath('//a[starts-with(@href,"javascript:") or starts-with(@href,"//")]'))
        config=json.loads(doc.get_element_by_id('ar-config').text)
        self.assertEqual(config['detail']['title'],self.example['title'])
        self.assertIn('\\u003c/script',text)

    def test_bounded_directory_exposes_more_without_autoselection(self):
        self.listing.return_value=[run('run-'+str(i)) for i in range(55)]
        _,doc=self.render()
        self.assertEqual(len(doc.xpath('//*[@data-run-row]')),50)
        self.assertNotIn('hidden',doc.get_element_by_id('ar-list-more').attrib)
        self.assertIn('55 total',doc.get_element_by_id('ar-list-count').text_content())
        self.loader.assert_not_called()

    def test_invalid_ambiguous_or_wrong_agent_scope_is_rejected(self):
        for selection in ({'run':['']},{'run':['a','b']},{'step':['s']},{'agent':['risk'],'run':['x']},
                          {'tab':['unknown']},{'path':['/tmp/private']},{'agent':['unknown']}):
            with self.subTest(selection=selection),self.assertRaises(ValueError): view.parse_selection(selection)
        self.loader.return_value=run('different-run')
        with self.assertRaises(ValueError): self.render(run='requested-run')

    def test_timing_uses_only_recorded_live_intervals_and_keeps_untimed_steps(self):
        step = self.example['steps'][0]
        step.update(started_at='2034-03-02T01:00:00Z', ended_at='2034-03-02T01:00:02Z', elapsed_seconds=1.9)
        self.loader.return_value = self.example
        _, doc = self.render(run=self.example['id'])
        self.assertFalse(doc.xpath('//*[@data-timing-row]'))
        self.assertIn('disabled', doc.xpath('//*[@data-process-mode="timing"]')[0].attrib)
        self.example['live'] = True
        self.example['steps'].append({**step, 'id': 'unfinished', 'ended_at': None})
        _, doc = self.render(run=self.example['id'])
        self.assertEqual(len(doc.xpath('//*[@data-timing-row]')), 1)
        self.assertEqual(len(doc.xpath('//*[@data-step-row]')), 2)
        self.assertIn('1 / 2 steps', doc.get_element_by_id('ar-timing-note').text_content())
        self.assertIn('1.9 s', doc.xpath('//*[@data-timing-row]')[0].text_content())

    def test_call_snapshot_preserves_recorded_values_sources_and_unknowns(self):
        call = self.example['calls'][0]
        call.update(started_at='2034-03-02T16:06:05.123456Z', ended_at='2034-03-02T16:06:09Z',
            configuration_snapshot={'schema_version': 'model-call-config-v1', 'capture_kind': 'before_dispatch',
                'sha256': 'a' * 64, 'effective_configuration': 'unverified',
                'fields': {'seed': {'status': 'explicit', 'value': 0, 'source': 'request'},
                    'stream': {'status': 'explicit', 'value': False, 'source': 'request'},
                    'tool_choice': {'status': 'explicit', 'value': None, 'source': 'request'},
                    'temperature': {'status': 'not_sent', 'value': None, 'source': 'request field absent'},
                    'base_url': {'status': 'recorded', 'value': 'https://example.test/v1', 'source': '<img src=x>'},
                    'api_key': {'status': 'explicit', 'value': 'must-not-render', 'source': 'private'}},
                'fingerprints': {'request_sha256': 'b' * 64}})
        self.loader.return_value = self.example
        _, doc = self.render(run=self.example['id'], step='step-1', tab='config')
        snapshot = doc.get_element_by_id('ar-call-snapshots')
        self.assertEqual(snapshot.xpath('.//tr[@data-config-field="seed"]/td[2]')[0].text_content(), '0')
        self.assertEqual(snapshot.xpath('.//tr[@data-config-field="stream"]/td[2]')[0].text_content(), 'false')
        self.assertEqual(snapshot.xpath('.//tr[@data-config-field="tool_choice"]/td[2]')[0].text_content(), 'null')
        self.assertIn('Not sent', snapshot.xpath('.//tr[@data-config-field="temperature"]/td[2]')[0].text_content())
        self.assertIn('Not recorded', snapshot.xpath('.//tr[@data-config-field="top_p"]/td[2]')[0].text_content())
        self.assertIn('2034-03-03 00:06:05 UTC+08:00', snapshot.text_content())
        self.assertIn('2034-03-02T16:06:05.123456Z', snapshot.text_content())
        self.assertIn('effective configuration is unverified', snapshot.text_content())
        self.assertIn('a' * 64, snapshot.text_content())
        self.assertIn('b' * 64, snapshot.text_content())
        self.assertNotIn('must-not-render', snapshot.text_content())
        self.assertFalse(snapshot.xpath('.//img'))
        self.assertTrue(doc.get_element_by_id('ar-step-detail').xpath('.//*[@data-call-snapshot]'))

    def test_unknown_snapshot_and_timezone_never_infer_defaults_or_time(self):
        for value in (None, '', '2034-03-02T16:06:05', '2034-02-30T16:06:05Z', 'bad'):
            with self.subTest(value=value): self.assertIsNone(view.observed_time(value))
        self.assertEqual(view.observed_time('2034-03-03T00:06:05+08:00')['beijing'], '2034-03-03 00:06:05 UTC+08:00')
        _, doc = self.render(run=self.example['id'], tab='config')
        snapshot = doc.get_element_by_id('ar-call-snapshots')
        self.assertIn('Configuration snapshot not recorded', snapshot.text_content())
        self.assertFalse(snapshot.xpath('.//time'))
        self.assertEqual(len(snapshot.xpath('.//tr[@data-config-field]')), len(view.CONFIG_FIELDS))

    def test_sampling_policy_comes_from_saved_sources_and_top_p_remains_explicit(self):
        from uteki.agents.runtime.model_configuration import build_configuration_snapshot
        snapshot = build_configuration_snapshot({'top_p': .95}, capture_kind='before_dispatch',
            sources={'temperature': 'policy.deepseek_thinking_sampling_ignored',
                     'top_k': 'policy.deepseek_top_k_unsupported', 'seed': 'policy.seed_not_documented'},
            statuses={'temperature': 'not_sent', 'top_k': 'not_sent', 'seed': 'not_sent'})
        doc = html.fromstring(view.configuration_snapshot({'call_id': 'sampling', 'configuration_snapshot': snapshot}))
        top_p = doc.xpath('.//tr[@data-config-field="top_p"]')[0].text_content()
        top_k = doc.xpath('.//tr[@data-config-field="top_k"]')[0].text_content()
        self.assertIn('0.95', top_p)
        self.assertNotIn('ignores', top_p)
        self.assertIn('Top-K', top_k)
        self.assertIn('does not list Top-K', top_k)
        self.assertIn('ignores temperature in thinking mode', doc.text_content())
        self.assertIn('not provider echoes', doc.text_content())
        unknown = html.fromstring(view.configuration_snapshot({'call_id': 'old', 'requested_model': 'deepseek-v4-pro'}))
        self.assertIn('Not recorded', unknown.xpath('.//tr[@data-config-field="top_k"]')[0].text_content())
        self.assertNotIn('ignores temperature in thinking mode', unknown.text_content())


if __name__ == '__main__':
    unittest.main()
