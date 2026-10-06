"""Material-first navigation uses scoped saved artifacts, never another source's output."""
from urllib.parse import parse_qs, urlparse
import unittest

from lxml import html

from tests.unit import test_data_evaluation_view as fixtures

UNTRUSTED = fixtures.UNTRUSTED


class MaterialNavigationTests(unittest.TestCase):
    setUp = fixtures.DataEvaluationViewTests.setUp
    patch = fixtures.DataEvaluationViewTests.patch
    load_dataset = fixtures.DataEvaluationViewTests.load_dataset
    load_run = fixtures.DataEvaluationViewTests.load_run
    render = fixtures.DataEvaluationViewTests.render

    def tree(self, **query):
        return html.fromstring(self.render(**query))

    def add_contents(self, company):
        data = self.datasets[company]
        data['indexes'][company + '-source']['nodes'] = [
            {'kind': 'document', 'title': company + '-source'},
            {'kind': 'item', 'title': company + ' Financial statements ' + UNTRUSTED,
             'start_block_id': 'table-1', 'reported_page': 17},
            {'kind': 'item', 'title': 'Unlocated section', 'start_block_id': 'missing'}]

    def test_material_list_requires_selection_and_uses_form_period_and_publication(self):
        load = self.patch('load_dataset_run')
        tree = self.tree(dataset='orchard')
        self.assertFalse(tree.xpath('//*[@id="material-detail"]'))
        load.assert_not_called()
        # Main content is a section, and IDs are retained only in diagnostic disclosures.
        texts = tree.xpath('//section[@class="ev-main"]/div[@class="ev-scroll"]/table/tbody/tr[1]/td/text()')
        self.assertEqual(texts[:3], ['10-K', '2032-12-31', '2033-02-01'])
        action = tree.xpath('//a[contains(., "Inspect material & outputs")]/@href')
        self.assertEqual(len(action), 1)
        self.assertEqual(parse_qs(urlparse(action[0]).query),
                         {'dataset': ['orchard'], 'tab': ['materials'], 'source': ['orchard-source']})

    def test_selected_material_links_original_sections_and_scoped_artifacts_for_two_companies(self):
        for company, other in [('orchard', 'harbor'), ('harbor', 'orchard')]:
            self.add_contents(company)
            tree = self.tree(dataset=company, tab='materials', source=company + '-source')
            detail = tree.xpath('//*[@id="material-detail"]')[0]
            self.assertIn('No financial extraction results are registered', detail.text_content())
            self.assertIn('Not generated', detail.xpath('.//*[@id="material-brief"]')[0].text_content())
            self.assertNotIn('data-fact-id', html.tostring(detail).decode())
            self.assertFalse(detail.xpath('.//script'))
            self.assertNotIn(other + ' Financial', detail.text_content())
            original = detail.xpath('.//a[contains(., "Read saved original")]/@href')[0]
            self.assertEqual(urlparse(original).path, '/evaluation/source')
            self.assertEqual(parse_qs(urlparse(original).query),
                             {'dataset': [company], 'source': [company + '-source']})
            section = detail.xpath('.//a[contains(., "Financial statements")]/@href')[0]
            self.assertEqual(parse_qs(urlparse(section).query),
                             {'dataset': [company], 'tab': ['blocks'], 'source': [company + '-source'], 'block': ['table-1']})
            self.assertEqual(urlparse(section).fragment, 'block-detail')
            self.assertFalse(detail.xpath('.//a[contains(., "Unlocated section")]'))
            self.assertIn('Location unavailable', detail.text_content())
            # Other datasets' raw/source selections are rejected, even with equal local block IDs.
            with self.assertRaises((KeyError, ValueError)):
                self.render(dataset=company, tab='materials', source=other + '-source')

    def test_each_run_keeps_its_own_candidates_and_failed_outputs(self):
        refs = [{'id': identity, 'source_snapshot_id': 'orchard-source'}
                for identity in ('first', 'second', 'failed')]
        refs.append({'id': 'other-material', 'source_snapshot_id': 'orchard-annex'})
        self.patch('dataset_runs', return_value={'runs': refs, 'gaps': []})
        def load(root, data, identity, sid):
            self.assertEqual(sid, 'orchard-source')
            self.assertNotEqual(identity, 'other-material')
            artifacts = {'result.json': {'status': 'failed' if identity == 'failed' else 'candidate'}}
            if identity != 'failed':
                artifacts.update({'extraction.json': {'records': [{'metric': 'Net sales'}, {'metric': 'Operating income'}]},
                                  'normalized.json': {'records': [{'metric_id': 'revenue'}]},
                                  'packet.json': {'task': {'question': 'Extract actual supported rows'},
                                      'metric_catalog': [{'metric_id': 'revenue', 'label': 'Net sales'},
                                                         {'metric_id': 'unused', 'label': 'Unrequested metric'}]}})
            if identity == 'second':
                artifacts['packet.json']['metric_catalog'] = {item['metric_id']: item for item in artifacts['packet.json']['metric_catalog']}
            return {'id': identity, 'path': 'experiments/' + identity, 'manifest_sha256': 'c' * 64,
                    'artifacts': artifacts, 'review': {} if identity == 'second' else None}
        loader = self.patch('load_dataset_run', side_effect=load)
        tree = self.tree(dataset='orchard', tab='materials', source='orchard-source')
        section = tree.xpath('//*[@id="material-financial-facts"]')[0]
        rows = section.xpath('./div[@class="ev-scroll"]/table/tbody/tr')
        self.assertEqual(len(rows), 3)
        for row in rows[:2]:
            self.assertIn('2 reported drafts', row.text_content())
            self.assertIn('1 normalized candidates', row.text_content())
            self.assertIn('Candidates produced', row.text_content())
            self.assertIn('Net sales / Operating income', row.text_content())
            self.assertNotIn('Unrequested metric', row.text_content())
            self.assertIn('Extract actual supported rows', row.text_content())
        self.assertNotIn('4 reported drafts', section.text_content())
        self.assertIn('Reported drafts not saved', rows[2].text_content())
        self.assertIn('Normalized output not saved', rows[2].text_content())
        self.assertIn('No independent review', rows[0].text_content())
        self.assertIn('Review saved; inspect scope & verdicts', rows[1].text_content())
        self.assertEqual(loader.call_count, 3)
        for identity, row in zip(('first', 'second', 'failed'), rows):
            urls = row.xpath('.//a/@href')
            process = next(url for url in urls if urlparse(url).path == '/extractions')
            self.assertEqual(parse_qs(urlparse(process).query), {'run': [identity]})
            self.assertEqual(urlparse(process).fragment, 'processing-record')
            numbers = next(url for url in urls if urlparse(url).path == '/evaluation')
            self.assertEqual(parse_qs(urlparse(numbers).query), {'dataset': ['orchard'],
                'tab': ['records'], 'source': ['orchard-source'], 'run': [identity]})

    def test_source_contents_precede_collapsed_diagnostics_and_block_keeps_return(self):
        self.add_contents('orchard')
        source_tree = self.tree(dataset='orchard', tab='blocks', source='orchard-source')
        self.assertTrue(source_tree.xpath('//section[@class="ev-outline"]//a'))
        technical = source_tree.xpath('//details[summary[contains(., "Parsing diagnostics, source identity")]]')[0]
        self.assertIsNone(technical.get('open'))
        detail_tree = self.tree(dataset='orchard', tab='blocks', source='orchard-source', block='table-1')
        detail = detail_tree.xpath('//*[@id="block-detail"]')[0]
        self.assertNotIn('table-1', detail.xpath('./h3')[0].text_content())
        self.assertTrue(detail.xpath('.//table[contains(@class,"ds-original-table")]'))
        back = detail_tree.xpath('//a[contains(., "Back to this material & outputs")]/@href')[0]
        self.assertEqual(parse_qs(urlparse(back).query), {'dataset': ['orchard'],
            'tab': ['materials'], 'source': ['orchard-source']})

    def test_storage_locations_use_only_registered_dataset_metadata(self):
        self.datasets['orchard']['storage'] = {'dataset_path': 'data/frozen/orchard',
            'records_path': 'data/frozen/orchard/records.json',
            'database_path': 'data/frozen/orchard/research.duckdb'}
        tree = self.tree(dataset='orchard', tab='materials', source='orchard-source')
        disclosure = tree.xpath('//details[summary[contains(., "Material identity & storage")]]')[0]
        self.assertIsNone(disclosure.get('open'))
        for name in ('raw/orchard-source.html', 'indexes/orchard-source/index.json',
                     'indexes/orchard-source/blocks.jsonl', 'records.json', 'research.duckdb'):
            self.assertIn('data/frozen/orchard/' + name, disclosure.text_content())
        self.assertIn('relative to the repository root', disclosure.text_content())
        fallback = self.tree(dataset='harbor', tab='materials', source='harbor-source')
        self.assertIn('relative to this dataset', fallback.text_content())
        self.assertNotIn('data/frozen/orchard', fallback.text_content())


if __name__ == '__main__':
    unittest.main()
