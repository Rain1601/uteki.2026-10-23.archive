"""Company-first workspace behavior using independent, synthetic source scopes."""
from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from lxml import html

from apps.review_workbench.pages import data_workspace as view
from tests.unit.test_data_evaluation_view import dataset, DECIMAL, UNTRUSTED


class DataWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/synthetic/data-workspace')
        self.datasets = {name: dataset(name) for name in ('orchard', 'harbor')}
        self.catalog = {'datasets': [
            {'id': name, 'company_id': name, 'company_name': name.title(),
             'symbol': name.upper()} for name in self.datasets]}
        self.tasks = {name: {'revision': 7, 'tasks': [], 'unassigned_runs': [], 'gaps': []}
                      for name in self.datasets}
        self.state = {'revision': 7, 'selections': {}, 'archived_versions': {}}
        self.runs = {}
        self.load_catalog = patch.object(view, 'load_catalog', return_value=self.catalog).start()
        self.load_dataset = patch.object(view, 'load_dataset', side_effect=lambda root, identity: deepcopy(self.datasets[identity])).start()
        self.read_state = patch.object(view, 'read_state', side_effect=lambda root: deepcopy(self.state)).start()
        self.material_tasks = patch.object(view, 'material_tasks', side_effect=lambda root, data, sid, state: deepcopy(self.tasks[data['id']])).start()
        self.run_loader = patch.object(view, 'load_dataset_run', side_effect=self.load_run).start()
        self.addCleanup(patch.stopall)

    def load_run(self, root, data, run_id, source_id):
        run = self.runs.get((data['id'], run_id))
        if not run or run['source_snapshot_id'] != source_id:
            raise ValueError('Run outside selected source')
        return deepcopy(run)

    def register_run(self, company, run_id, *, amount=DECIMAL, selected=False, archived=False):
        data = self.datasets[company]
        record = deepcopy(data['records'][0])
        record['value_decimal'] = amount
        run = {'id': run_id, 'company_id': company, 'source_snapshot_id': company + '-source',
               'source_sha256': data['sources'][0]['source_sha256'], 'manifest_sha256': 'c' * 64,
               'path': 'synthetic/runs/' + run_id, 'db_check': 'payload_matches_normalized',
               'db_rows': [record], 'review': None,
               'dataset': {'id': company, 'manifest_sha256': data['manifest_sha256']},
               'artifacts': {'packet.json': {'metric_catalog': deepcopy(data['metrics']), 'blocks': []},
                             'normalized.json': {'records': [record], 'evidence': deepcopy(data['evidence']), 'unresolved': []},
                             'extraction.json': {'records': [record], 'gaps': []},
                             'result.json': {'status': 'complete'}}}
        self.runs[company, run_id] = run
        version = {'run_id': run_id, 'label': '已保存版本 ' + run_id,
                   'label_zh': '已保存版本 ' + run_id, 'label_en': 'Saved version ' + run_id,
                   'selected': selected,
                   'archived': archived, 'available': True, 'selectable': not archived}
        return version

    def register_task(self, company, versions, task_id='financial-task'):
        self.tasks[company]['tasks'].append({'task_id': task_id, 'label_zh': '财务数据任务',
            'label_en': 'Financial extraction task', 'versions': versions,
            'selected_run_id': next((v['run_id'] for v in versions if v['selected']), None)})

    def render(self, **selection):
        text = view.render_data_workspace(self.root, {key: [value] for key, value in selection.items()})
        return text, html.fromstring(text)

    @staticmethod
    def config(doc):
        return json.loads(doc.get_element_by_id('dw-config').text)

    def test_first_visit_does_not_select_company_material_or_load_data(self):
        _, doc = self.render()
        self.load_dataset.assert_not_called()
        self.run_loader.assert_not_called()
        self.read_state.assert_not_called()
        self.assertFalse(doc.xpath('//iframe'))
        self.assertNotIn('dataset', self.config(doc)['selection'])
        self.assertIn('Start with a company', doc.text_content())
        self.assertEqual(len(doc.xpath('//div[@class="dw-company"]')), 2)

    def test_company_with_multiple_datasets_requires_explicit_dataset_choice(self):
        self.catalog['datasets'].append({'id': 'orchard-history', 'company_id': 'orchard',
                                        'company_name': 'Orchard', 'symbol': 'ORCHARD'})
        _, doc = self.render(company='orchard')
        self.load_dataset.assert_not_called()
        company_link = doc.xpath('//div[@class="dw-company"]/a[strong="ORCHARD"]')[0]
        self.assertEqual(parse_qs(urlparse(company_link.get('href')).query), {'company': ['orchard']})
        datasets = doc.xpath('//a[@class="dw-dataset"]')
        self.assertEqual(len(datasets), 2)
        self.assertFalse(doc.xpath('//iframe'))

    def test_material_directory_orders_report_period_not_publication_date(self):
        data = self.datasets['orchard']
        data['sources'][0]['available_at'] = '2035-03-04'
        data['sources'].extend([
            {**data['sources'][0], 'source_snapshot_id': 'orchard-newer-period',
             'period_end': '2033-12-31', 'available_at': '2034-02-05', 'form': '10-Q'},
            {**data['sources'][0], 'source_snapshot_id': 'orchard-unknown-period',
             'period_end': None, 'available_at': '2036-01-02'}])
        _, doc = self.render(dataset='orchard')
        self.material_tasks.assert_not_called()
        rows = doc.xpath('//a[@class="dw-material"]')
        self.assertEqual([row.get('data-year') for row in rows], ['2033', '2032', ''])
        self.assertIn('2032-12-31', rows[1].text_content())
        self.assertIn('2035-03-04', rows[1].text_content())
        self.assertIn('Period unknown', rows[2].text_content())
        self.assertFalse(doc.xpath('//iframe'))

    def test_invalid_ambiguous_and_conflicting_selection_is_rejected(self):
        invalid = ({'dataset': ['orchard', 'harbor']}, {'dataset': ['']},
                   {'source': ['orchard-source']}, {'dataset': ['orchard'], 'fact': ['shared-local-record']},
                   {'dataset': ['orchard'], 'source': ['orchard-source'], 'tab': ['unsupported']},
                   {'dataset': ['orchard'], 'source': ['orchard-source'], 'offset': ['-1']},
                   {'dataset': ['orchard'], 'source': ['orchard-source'], 'offset': ['3']},
                   {'dataset': ['orchard'], 'source': ['orchard-source'], 'base': ['1'], 'run': ['some-run']})
        for selection in invalid:
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                view.parse_selection(selection)
        for selection in ({'dataset': 'unknown'}, {'dataset': 'orchard', 'company': 'harbor'},
                          {'dataset': 'orchard', 'source': 'harbor-source'},
                          {'dataset': 'orchard', 'source': 'orchard-source', 'block': 'foreign-block'}):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                self.render(**selection)

    def test_material_has_five_tabs_and_strict_sandboxed_same_source_reader(self):
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='blocks')
        tabs = doc.xpath('//nav[@class="dw-tabs"]/a')
        self.assertEqual([tab.get('data-tab') for tab in tabs], list(view.TABS))
        self.assertEqual([tab.get('data-tab') for tab in tabs if tab.get('aria-current')], ['blocks'])
        for tab in tabs:
            query = parse_qs(urlparse(tab.get('href')).query)
            self.assertEqual(query['dataset'], ['orchard'])
            self.assertEqual(query['source'], ['orchard-source'])
        reader = doc.get_element_by_id('dw-source-frame')
        self.assertEqual(reader.get('sandbox'), '')
        self.assertEqual(parse_qs(urlparse(reader.get('src')).query),
                         {'dataset': ['orchard'], 'source': ['orchard-source']})
        separator = doc.get_element_by_id('dw-divider')
        self.assertEqual(separator.get('role'), 'separator')
        self.assertEqual(separator.get('tabindex'), '0')

    def test_base_records_are_not_implicitly_mixed_with_selected_extractions(self):
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        panel = doc.xpath('//*[@data-panel="financials"]')[0]
        self.assertFalse(panel.xpath('.//button[@data-fact-target]'))
        self.assertIn('No financial records in this view', panel.text_content())
        self.assertTrue(panel.xpath('.//a[contains(@href,"base=1")]'))
        self.run_loader.assert_not_called()

    def test_financial_values_share_one_inspector_with_explicit_close_and_return_actions(self):
        self.register_task('orchard', [self.register_run('orchard', 'current', selected=True)])
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        panel = doc.xpath('//*[@data-panel="financials"]')[0]
        inspector = doc.get_element_by_id('dw-fact-inspector')
        self.assertIn(panel, inspector.iterancestors())
        self.assertEqual(len(panel.xpath('.//*[@id="dw-fact-inspector"]')), 1)
        self.assertTrue(inspector.xpath('.//*[@id="dw-inspector-empty"]'))
        for identity in ('dw-close-inspector', 'dw-return-fact'):
            control = doc.get_element_by_id(identity)
            self.assertIn(inspector, control.iterancestors())
            self.assertEqual(control.tag, 'button')
        details = panel.xpath('.//*[@class="dw-fact-detail"]')
        self.assertTrue(details)
        self.assertTrue(all(inspector in detail.iterancestors() for detail in details))
        self.assertFalse(inspector.xpath('.//button[@data-fact-target]'))
        for button in panel.xpath('.//button[@data-fact-target]'):
            self.assertTrue(button.xpath('ancestor::td'))
            self.assertTrue(button.xpath('ancestor::tr[@data-financial-row]'))
            self.assertEqual(len(doc.xpath('//*[@id="fact-' + button.get('data-fact-target') + '"]')), 1)

    def test_source_expansion_control_has_bilingual_expand_and_return_labels(self):
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        button = doc.get_element_by_id('dw-expand-source')
        expand = button.xpath('.//*[@data-expand-label]')
        collapse = button.xpath('.//*[@data-collapse-label]')
        self.assertEqual(len(expand), 1)
        self.assertEqual(len(collapse), 1)
        self.assertTrue(expand[0].text_content().strip())
        self.assertTrue(collapse[0].text_content().strip())
        self.assertNotEqual(expand[0].text_content(), collapse[0].text_content())
        self.assertIn('Expand', expand[0].text_content())
        self.assertIn('Return', collapse[0].text_content())

    def test_same_local_ids_keep_financial_evidence_in_selected_company(self):
        # The independent fixtures intentionally share table-1 and shared-local-record.
        for company, other in (('orchard', 'harbor'), ('harbor', 'orchard')):
            with self.subTest(company=company):
                _, doc = self.render(dataset=company, source=company + '-source', tab='financials', base='1')
                panel = doc.xpath('//*[@data-panel="financials"]')[0]
                self.assertIn(company + ' evidence', panel.text_content())
                self.assertNotIn(other + ' evidence', panel.text_content())
                self.assertIn(DECIMAL, panel.text_content())
                self.assertEqual(panel.xpath('.//button[@data-fact-target]')[0].get('data-fact'), 'shared-local-record')
                self.assertEqual(panel.xpath('.//button[@data-locate]')[0].get('data-locate'), 'table-1')
                self.assertEqual(self.config(doc)['selection']['source'], company + '-source')

    def test_source_text_and_search_query_are_escaped_in_markup_and_config(self):
        attack = '</script><script>alert("query")</script>'
        text, doc = self.render(dataset='orchard', source='orchard-source', tab='blocks', q=attack)
        scripts = doc.xpath('//script')
        self.assertEqual(len(scripts), 2)  # Configuration and the reviewed application script only.
        self.assertNotIn(UNTRUSTED, text)
        self.assertNotIn(attack, text)
        self.assertEqual(doc.xpath('//input[@name="q"]')[0].get('value'), attack)
        self.assertEqual(self.config(doc)['selection']['q'], attack)
        _, block_doc = self.render(dataset='orchard', source='orchard-source', tab='blocks', block='table-1')
        selected = block_doc.xpath('//*[@class="dw-selected-block"]')[0]
        self.assertIn(UNTRUSTED, selected.text_content())
        self.assertFalse(selected.xpath('.//script'))

    def test_missing_brief_data_and_trace_are_distinct_explicit_states(self):
        self.datasets['orchard']['records'] = []
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='brief')
        self.assertIn('Not generated.', doc.xpath('//*[@data-panel="brief"]')[0].text_content())
        self.assertIn('No financial records', doc.xpath('//*[@data-panel="financials"]')[0].text_content())
        self.assertIn('No model extraction runs', doc.xpath('//*[@data-panel="process"]')[0].text_content())
        self.assertFalse(doc.xpath('//*[@data-panel="financials"]//a[contains(@href,"base=1")]'))

    def test_display_version_and_archive_controls_do_not_hide_history(self):
        versions = [self.register_run('orchard', 'current', selected=True),
                    self.register_run('orchard', 'previous'),
                    self.register_run('orchard', 'archived', archived=True)]
        self.register_task('orchard', versions)
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        panel = doc.xpath('//*[@data-panel="financials"]')[0]
        options = panel.xpath('.//select[@data-task-choice]/option')
        self.assertEqual([option.get('value') for option in options], ['', 'current', 'previous'])
        self.assertEqual([option.get('value') for option in options if option.get('selected') is not None], ['current'])
        self.assertFalse(panel.xpath('.//*[@data-run="current" and @data-state-action="archive"]'))
        self.assertTrue(panel.xpath('.//*[@data-run="previous" and @data-state-action="archive"]'))
        self.assertTrue(panel.xpath('.//*[@data-run="archived" and @data-state-action="restore"]'))
        archived_link = panel.xpath('.//a[contains(@href,"run=archived")]')[0]
        self.assertFalse(any(node.get('open') is not None for node in archived_link.iterancestors('details')))
        self.assertIn('This changes the view, not adoption', panel.text_content())
        self.assertEqual({call.args[2] for call in self.run_loader.call_args_list}, {'current'})

    def test_scope_summary_describes_only_selected_tasks_and_keeps_history_collapsed(self):
        self.register_task('orchard', [self.register_run('orchard', 'income-current', selected=True),
                                      self.register_run('orchard', 'income-old')], 'income-task')
        self.register_task('orchard', [self.register_run('orchard', 'cash-current', selected=True)], 'cash-task')
        self.tasks['orchard']['tasks'][0].update(label_zh='利润提取', label_en='Income extraction')
        self.tasks['orchard']['tasks'][1].update(label_zh='现金流提取', label_en='Cash-flow extraction')
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        scope = doc.xpath('//*[@class="dw-scope-summary"]')[0].text_content()
        self.assertIn('2 selected tasks', scope)
        self.assertIn('Income extraction / Saved version income-current', scope)
        self.assertIn('Cash-flow extraction / Saved version cash-current', scope)
        self.assertNotIn('income-old', scope)
        self.assertNotIn('registered base database', scope)
        self.assertNotIn('Historical version preview', scope)
        versions = doc.xpath('//details[@class="dw-versions"]')
        self.assertEqual(len(versions), 1)
        self.assertIsNone(versions[0].get('open'))

    def test_base_scope_is_explicit_even_when_current_extraction_versions_exist(self):
        self.register_task('orchard', [self.register_run('orchard', 'current', selected=True)])
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials', base='1')
        scope = doc.xpath('//*[@class="dw-scope-summary"]')[0].text_content()
        self.assertIn('Showing the registered base database.', scope)
        self.assertNotIn('selected tasks', scope)
        self.assertNotIn('Saved version current', scope)
        self.assertIsNone(doc.xpath('//details[@class="dw-versions"]')[0].get('open'))

    def test_missing_display_selection_prompts_version_choice_without_inventing_default(self):
        self.register_task('orchard', [self.register_run('orchard', 'available-unselected')])
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        scope = doc.xpath('//*[@class="dw-scope-summary"]')[0].text_content()
        self.assertIn('No extraction version selected', scope)
        self.assertIsNotNone(doc.xpath('//details[@class="dw-versions"]')[0].get('open'))
        self.assertFalse(doc.xpath('//button[@data-fact-target]'))
        self.run_loader.assert_not_called()

    def test_unavailable_pinned_version_is_not_selectable_or_archivable(self):
        invalid = {'run_id': 'changed-pin', 'label': 'Changed source pin', 'selected': False,
                   'archived': False, 'available': False, 'selectable': False, 'gap': 'Source hash changed'}
        self.register_task('orchard', [invalid])
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        panel = doc.xpath('//*[@data-panel="financials"]')[0]
        options = panel.xpath('.//option[@value="changed-pin"]')
        self.assertTrue(not options or all(option.get('disabled') is not None for option in options))
        self.assertFalse(panel.xpath('.//*[@data-run="changed-pin" and @data-state-action]'))
        self.assertIn('Source validation failed', panel.text_content())

    def test_historical_fact_is_readable_without_changing_current_selection_or_adoption(self):
        versions = [self.register_run('orchard', 'current', selected=True),
                    self.register_run('orchard', 'history', archived=True, amount='41')]
        self.register_task('orchard', versions)
        before = deepcopy(self.tasks)
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials',
                             run='history', fact='shared-local-record')
        panel = doc.xpath('//*[@data-panel="financials"]')[0]
        self.assertTrue(self.config(doc)['historical_fact'])
        self.assertIn('Historical version preview', panel.text_content())
        scope = doc.xpath('//*[@class="dw-scope-summary"]')[0].text_content()
        self.assertIn('Financial extraction task / Saved version history', scope)
        self.assertIn('Display selections are unchanged.', scope)
        self.assertNotIn('Saved version current', scope)
        self.assertNotIn('selected tasks', scope)
        self.assertIsNone(doc.xpath('//details[@class="dw-versions"]')[0].get('open'))
        self.assertEqual(panel.xpath('.//button[@data-fact-target]')[0].get('data-run'), 'history')
        self.assertEqual(panel.xpath('.//button[@data-fact-target]')[0].text_content(), '41')
        self.assertIn('Candidate display does not mean adoption', panel.text_content())
        self.assertIn('This version is archived', doc.xpath('//*[@data-panel="process"]')[0].text_content())
        self.assertEqual(self.tasks, before)
        with self.assertRaisesRegex(ValueError, 'Run outside selected source'):
            self.render(dataset='harbor', source='harbor-source', run='history', fact='shared-local-record')

    def test_conflicting_financial_candidates_remain_visible_and_traceable(self):
        self.register_task('orchard', [self.register_run('orchard', 'run-a', selected=True, amount='41')], 'task-a')
        self.register_task('orchard', [self.register_run('orchard', 'run-b', selected=True, amount='42')], 'task-b')
        _, doc = self.render(dataset='orchard', source='orchard-source', tab='financials')
        rows = doc.xpath('//tr[@data-financial-row]')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].get('data-conflict'), 'true')
        self.assertIn('Conflicting candidates', rows[0].text_content())
        self.assertEqual([node.text_content() for node in rows[0].xpath('.//button[@data-fact-target]')], ['41', '42'])
        self.assertEqual(len(doc.xpath('//*[@class="dw-fact-detail"]')), 2)


if __name__ == '__main__':
    unittest.main()
