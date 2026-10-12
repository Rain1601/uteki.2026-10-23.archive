"""Result pages preserve explicit scope, real outputs and independent review identities."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from lxml import html
from apps.review_workbench.pages import agent_results as view


def result(identity='orchard-2033'):
    ref = {'id': 'file-output', 'run_id': identity + '-worker', 'label': 'Candidate',
           'availability': 'available', 'sha256': 'b' * 64}
    return {'id': identity, 'agent': 'data', 'title': 'Orchard cash flow', 'origin': 'scripted_fixture',
        'revision': 3, 'live': False, 'scope': {'company_id': 'orchard', 'periods': ['2033']},
        'task': 'Explain cash flow with citations',
        'state': {'execution': 'ended', 'delivery': 'candidate_ready', 'quality': 'not_evaluated',
                  'adoption': 'unchanged_candidate', 'stop_reason': 'completed'},
        'models': [{'model': 'example-model', 'provider': 'example-provider', 'role': 'analyst',
                    'reasoning_effort': 'high', 'thinking_mode': 'enabled', 'call_count': 1}],
        'usage': {'input_tokens': 0, 'output_tokens': 100, 'known_estimated_usd': None},
        'artifacts': [ref], 'configs': [], 'links': [],
        'result_view': {'kind': 'bounded_facts_analysis', 'facts': [{'metric': 'Operating cash flow',
            'period': '2033', 'period_end': '2033-12-30', 'value': -42, 'unit': 'million', 'currency': 'USD',
            'block_id': 'source-orchard-2033', 'row': 5, 'column': 'c2', 'quote': 'Operating cash flow (42)'}],
            'analysis': [{'claim': 'Cash outflow needs review.', 'block_ids': ['source-orchard-2033']}],
            'gaps': ['Only a cash flow excerpt is available.'], 'artifacts': [ref]},
        'binding': {'trace_id': identity, 'revision': 'revision-3', 'result_sha256': 'a' * 64}}


class AgentResultsPageTests(unittest.TestCase):
    def setUp(self):
        self.left, self.right = result(), result('harbor-2034')
        self.listing = patch.object(view, 'list_results', return_value={'results': [self.left, self.right], 'total': 2}).start()
        self.loader = patch.object(view, 'load_result', return_value=self.left).start()
        self.compare = patch.object(view, 'compare_results', return_value={'left': self.left, 'right': self.right,
            'comparable': False, 'reasons': ['Different company and period'], 'comparison_key': None}).start()
        self.addCleanup(patch.stopall)

    def render(self, **args):
        text = view.render_agent_results(Path('/synthetic'), {key: [value] for key, value in args.items()})
        return text, html.fromstring(text)

    def test_no_implicit_run_and_other_agents_do_not_borrow_data_outputs(self):
        _, doc = self.render()
        self.loader.assert_not_called()
        self.assertFalse(doc.xpath('//*[@data-result]'))
        self.assertIn('Select a run', doc.text_content())
        for agent in ('analysis', 'risk', 'portfolio'):
            self.listing.reset_mock()
            _, doc = self.render(agent=agent)
            self.listing.assert_not_called()
            self.assertFalse(doc.xpath('//*[@data-result-row]'))

    def test_readable_output_links_exact_trace_and_keeps_negative_zero_unknown(self):
        _, doc = self.render(run=self.left['id'])
        self.assertIn('Orchard cash flow', doc.text_content())
        self.assertIn('Operating cash flow', doc.text_content())
        self.assertIn('-42', doc.text_content())
        cells = doc.xpath('//table[contains(@class,"rr-facts")]/tbody/tr/td')
        self.assertIn('2033-12-30', cells[1].text_content())
        self.assertIn('million · USD', cells[2].text_content())
        self.assertIn('example-model', doc.text_content())
        self.assertIn('example-provider', doc.text_content())
        self.assertIn('high', doc.text_content())
        self.assertIn('source-orchard-2033', doc.text_content())
        self.assertEqual(doc.xpath('//a[@class="rr-trace"]')[0].get('href'), '/agent-runs?agent=data&run=orchard-2033')
        self.assertEqual(doc.xpath('//dl[@class="rr-metrics"]/div[1]/dd')[0].text_content(), '0')
        self.assertIn('Not recorded', doc.xpath('//dl[@class="rr-metrics"]/div[3]/dd')[0].text_content())
        self.assertEqual(doc.xpath('//button[@data-artifact]')[0].get('data-artifact-owner'), 'orchard-2033-worker')

    def test_fact_units_and_periods_support_both_explicit_shapes_without_inference(self):
        fact = self.left['result_view']['facts'][0]
        for period in ({'start': '2033-01-01', 'end': '2033-12-30'}, '2033-01-01 → 2033-12-30'):
            fact.update(period=period, unit='EUR', currency='EUR', value='0')
            _, doc = self.render(run=self.left['id'])
            cells = doc.xpath('//table[contains(@class,"rr-facts")]/tbody/tr/td')
            self.assertEqual(cells[1].text_content().count('2033-12-30'), 1)
            self.assertEqual(cells[2].text_content(), '0EUR')
        fact.update(unit=None, currency='JPY', period='2033', period_end='2033-09-30')
        _, doc = self.render(run=self.left['id'])
        cells = doc.xpath('//table[contains(@class,"rr-facts")]/tbody/tr/td')
        self.assertIn('JPY', cells[2].text_content())
        self.assertIn('2033-09-30', cells[1].text_content())
        fact.update(unit=None, currency=None)
        _, doc = self.render(run=self.left['id'])
        self.assertIn('Not recorded', doc.xpath('//table[contains(@class,"rr-facts")]/tbody/tr/td')[2].text_content())
        fact.update(unit='<script>x</script>', currency='<img src=x>', period_end='<svg>x</svg>')
        _, doc = self.render(run=self.left['id'])
        self.assertFalse(doc.xpath('//table[contains(@class,"rr-facts")]//script|//img|//svg'))

    def test_comparison_retains_independent_bindings_and_never_declares_mismatch_fair(self):
        _, doc = self.render(run=self.left['id'], compare=self.right['id'])
        self.assertEqual(len(doc.xpath('//*[@data-result]')), 2)
        self.assertEqual(len(doc.xpath('//*[@data-score-form]')), 2)
        self.assertEqual(doc.xpath('//*[@data-comparable]')[0].get('data-comparable'), 'false')
        self.assertIn('not a like-for-like A/B', doc.text_content())
        config = json.loads(doc.get_element_by_id('rr-config').text)
        self.assertEqual([d['binding']['trace_id'] for d in config['details']], [self.left['id'], self.right['id']])
        self.assertFalse(doc.xpath('//select[@name="accuracy"]/option[@selected]'))
        self.compare.return_value['comparable'] = True
        self.compare.return_value['reasons'] = []
        self.compare.return_value['limitations'] = ['One sample cannot establish a model ranking.']
        _, doc = self.render(run=self.left['id'], compare=self.right['id'])
        self.assertEqual(doc.xpath('//*[@data-comparable]')[0].get('data-comparable'), 'true')
        self.assertIn('no automatic total or ranking', doc.text_content())
        self.assertIn('One sample cannot establish a model ranking.', doc.text_content())

    def test_missing_output_cannot_appear_as_completed_report(self):
        self.left['result_view'] = {'kind': 'no_visible_output', 'facts': [], 'analysis': [], 'gaps': ['Output limit'], 'artifacts': []}
        self.left['state']['stop_reason'] = 'length'
        self.left['usage'].update(output_tokens=4000, reasoning_tokens=4000)
        _, doc = self.render(run=self.left['id'])
        self.assertTrue(doc.xpath('//*[@data-no-output]'))
        self.assertFalse(doc.xpath('//table[contains(@class,"rr-facts")]'))
        self.assertIn('not a completed report', doc.text_content())
        self.assertIn('length', doc.text_content())
        notice = doc.xpath('//*[@data-delivery-notice]')[0]
        self.assertIn('Not delivered: no visible answer', notice.text_content())
        self.assertIn('4,000', notice.text_content())
        self.assertIn('were reasoning tokens', notice.text_content())
        self.assertTrue(notice.xpath('following-sibling::div[@data-workspace-panel="config"]//section[contains(@class,"rr-models")]'))
        self.assertIn('Not delivered', doc.xpath('//*[@data-state="delivery"]')[0].text_content())
        for reasoning in (None, 2000):
            self.left['usage']['reasoning_tokens'] = reasoning
            _, doc = self.render(run=self.left['id'])
            self.assertNotIn('were reasoning tokens', doc.xpath('//*[@data-delivery-notice]')[0].text_content())

    def test_untrusted_output_and_links_do_not_create_html_or_scripts(self):
        self.left['title'] = '</script><script>bad()</script><img src=x>'
        self.left['result_view']['analysis'][0]['claim'] = '<svg onload=bad()>'
        self.left['links'] = [{'label': 'safe', 'href': '/data-workspace?company=orchard&dataset=2033'},
                              {'label': 'bad', 'href': 'javascript:bad()'}, {'label': 'remote', 'href': '//bad.test'}]
        text, doc = self.render(run=self.left['id'])
        self.assertFalse(doc.xpath('//img|//svg|//script[text()="bad()"]'))
        self.assertFalse(doc.xpath('//a[starts-with(@href,"javascript:") or starts-with(@href,"//")]'))
        self.assertTrue(doc.xpath('//a[starts-with(@href,"/data-workspace?")]'))
        self.assertIn('\\u003c/script', text)

    def test_invalid_ambiguous_cross_agent_and_foreign_artifact_are_rejected(self):
        for args in ({'run': ['']}, {'run': ['x', 'y']}, {'compare': ['y']}, {'run': ['x'], 'compare': ['x']},
                     {'artifact': ['a']}, {'run': ['x'], 'agent': ['risk']}, {'path': ['/tmp/file']}, {'agent': ['unknown']}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                view.parse_selection(args)
        with self.assertRaises(ValueError): self.render(run=self.left['id'], artifact='foreign')
        with self.assertRaises(ValueError): self.render(run='another-run')
        self.compare.return_value['right'] = result('wrong-run')
        with self.assertRaises(ValueError): self.render(run=self.left['id'], compare=self.right['id'])

    def test_saved_comparison_shows_actual_call_dates_without_claiming_fresh_calls(self):
        self.left['calls'] = [{'call_id': 'old-call', 'requested_model': 'old-model',
                              'started_at': '2034-03-02T14:30:00Z', 'ended_at': '2034-03-02T14:30:15Z'}]
        self.right['calls'] = [{'call_id': 'new-call', 'requested_model': 'new-model',
                               'started_at': '2034-03-02T16:06:00Z', 'ended_at': None,
                               'configuration_snapshot': {'schema_version': 'model-call-config-v1',
                                   'capture_kind': 'historical_partial', 'sha256': 'f' * 64,
                                   'fields': {'max_tokens': {'value': 4000, 'status': 'recorded', 'source': 'start.json'}}}}]
        _, doc = self.render(run=self.left['id'], compare=self.right['id'])
        self.assertIn('does not start a new model call', doc.xpath('//*[@data-saved-comparison]')[0].text_content())
        cards = doc.xpath('//*[@data-result]')
        self.assertIn('2034-03-02 22:30:00 UTC+08:00', cards[0].text_content())
        self.assertIn('2034-03-03 00:06:00 UTC+08:00', cards[1].text_content())
        for card in cards:
            for stamp in card.xpath('.//time'):
                self.assertFalse(stamp.xpath('ancestor::details'))
        self.assertIn('Partial historical record', cards[1].text_content())
        self.assertEqual(cards[1].xpath('.//tr[@data-config-field="max_tokens"]/td[2]')[0].text_content(), '4000')
        self.assertIn('Not recorded', cards[1].xpath('.//*[@data-call-time]/dl/div[2]/dd')[0].text_content())

    def test_three_panes_keep_process_evaluation_and_artifacts_on_same_trace(self):
        ref = self.left['artifacts'][0]
        self.left['steps'] = [{'id': 'step-01', 'ordinal': 1, 'run_id': self.left['id'],
            'action': 'query', 'status': 'rejected', 'error_code': 'quote_mismatch', 'files': [ref], 'call_ids': []}]
        self.left['evaluation'] = {'summary': 'Failed original, recovered delivery',
            'program_checks': {'strict_load': 'pass'}, 'model_reviews': {'source': 'pass'},
            'independent_assessment': {'mandatory_coverage': {'required': 4, 'correct': 4}, 'focus': 'fail'},
            'standard': {'version': 'frozen-v1'}, 'limitations': ['One question only'], 'artifacts': [ref]}
        _, doc = self.render(run=self.left['id'], tab='process')
        card = doc.xpath('//*[@data-result]')[0]
        self.assertEqual(len(card.xpath('./div[@class="rr-center-pane"]')), 1)
        pane = card.xpath('./aside[@class="rr-evaluation-pane"]')[0]
        self.assertIn(self.left['id'], pane.text_content())
        self.assertIn('4', pane.text_content())
        self.assertIn('focus', pane.text_content().lower())
        self.assertIn('One question only', pane.text_content())
        self.assertTrue(pane.xpath('.//*[@data-score-form]'))
        self.assertFalse(card.xpath('.//*[@data-workspace-panel="process"]')[0].get('hidden'))
        self.assertIsNotNone(card.xpath('.//*[@data-workspace-panel="result"]')[0].get('hidden'))
        self.assertIn('quote_mismatch', card.xpath('.//*[@data-process-step]')[0].text_content())
        self.assertEqual(pane.xpath('.//*[@data-artifact]')[0].get('data-artifact-owner'), ref['run_id'])
        with self.assertRaises(ValueError): self.render(run=self.left['id'], tab='unknown')

    def test_evaluation_text_cannot_inject_markup(self):
        self.left['evaluation'] = {'summary': '<script>bad()</script>',
            'independent_assessment': {'<img>': ['<svg onload=bad()>']}}
        _, doc = self.render(run=self.left['id'])
        self.assertFalse(doc.xpath('//img|//svg|//script[text()="bad()"]'))


if __name__ == '__main__':
    unittest.main()
