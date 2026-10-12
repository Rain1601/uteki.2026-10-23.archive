"""Independent synthetic acceptance boundaries; these are not model runs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from lxml import html

spec = importlib.util.spec_from_file_location('e6_r4_evaluation', Path(__file__).with_name('evaluate_run.py'))
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def fixture(base):
    sources, required, facts, documents = [], [], [], []
    for n in (1, 2):
        company = f'sec-000{n}'; sid = f'source-{n}'
        periods = [{'kind': 'year', 'start': f'{year}-01-01', 'end': f'{year}-12-31'} for year in (2024, 2025)]
        displays = [str(n * 100 + 7), str(n * 100 + 19)]
        body = '<html><body><xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
        for i, period in enumerate(periods):
            body += f'<xbrli:context id="c{i}"><xbrli:identifier>000{n}</xbrli:identifier><xbrli:startdate>{period["start"]}</xbrli:startdate><xbrli:enddate>{period["end"]}</xbrli:enddate></xbrli:context>'
        body += '<table><tr><td>In millions of USD. Company total revenue 2024 2025</td></tr><tr>'
        for i, display in enumerate(displays):
            body += f'<td><ix:nonfraction contextref="c{i}" unitref="USD" name="us-gaap:Revenues" scale="6">{display}</ix:nonfraction></td>'
        body += '</tr></table></body></html>'
        folder = base / 'sources' / sid; folder.mkdir(parents=True)
        raw = folder / 'original.html'; raw.write_text(body)
        tree = html.fromstring(raw.read_bytes()); table = tree.xpath('//table')[0]
        text = ' '.join(table.itertext()); text_hash = e.hashlib.sha256(text.encode()).hexdigest()
        block = {'block_id': f'block-{n}', 'type': 'table', 'text': text, 'text_hash': text_hash}
        (folder / 'blocks.jsonl').write_text(json.dumps(block) + '\n')
        source = {'source_snapshot_id': sid, 'company_id': company, 'source_sha256': e.sha(raw),
            'source_url': f'https://example.org/company{n}/annual2025', 'raw_file': f'sources/{sid}/original.html',
            'index_folder': f'sources/{sid}', 'form': '10-K', 'available_at': '2026-01-15',
            'fiscal_periods': [{'fiscal_year': year, 'period': periods[i]} for i, year in enumerate((2024, 2025))]}
        sources.append(source)
        documents.append({key: source[key] for key in ('source_snapshot_id', 'company_id', 'source_sha256', 'source_url')} | {'blocks': [block]})
        for i, year in enumerate((2024, 2025)):
            element = tree.xpath('//*[@contextref=$id]', id=f'c{i}')[0]
            expected = {'company_id': company, 'source_snapshot_id': sid, 'fiscal_year': year,
                'period': periods[i], 'value_decimal': str(int(displays[i]) * 1000000), 'unit': 'USD',
                'source_url': source['source_url'], 'source_sha256': source['source_sha256'],
                'original_references': [{'fact_dom_path': tree.getroottree().getpath(element), 'table_block_id': block['block_id']}]}
            required.append(expected)
            value = {'entity_id': company, 'source_snapshot_id': sid, 'metric_id': 'revenue',
                'period': periods[i], 'value_decimal': expected['value_decimal'], 'unit': 'USD',
                'dimensions': {}, 'value_kind': 'actual', 'accounting_basis': 'reported_consolidated',
                'origin': {'context_ref': f'c{i}', 'concept': 'us-gaap:Revenues'}}
            facts.append({'fact_id': f'fact-{n}-{year}', 'kind': 'record', 'value': value,
                'citations': [{'source_snapshot_id': sid, 'block_id': block['block_id'],
                    'text_hash': text_hash, 'source_sha256': source['source_sha256'],
                    'char_start': 0, 'char_end': len(text), 'quote': text}]})
    write(base / 'sources.json', sources)
    scope = {'snapshot_id': 'synthetic', 'knowledge_cutoff': '2026-02-06'}
    return {'facts': facts, 'source_documents': documents, 'scope': scope}, {'required': required, 'focus_standard': 'Necessary context only; equivalent originals allowed.'}


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.base = Path(self.temp.name)
        self.packet, self.gold = fixture(self.base)

    def tearDown(self):
        self.temp.cleanup()

    def test_four_required_values_and_original_semantics(self):
        self.assertEqual(e.numeric_coverage(self.packet, self.gold)['verdict'], 'pass')
        self.assertEqual(e.original_semantics(self.packet, self.gold, self.base)['verdict'], 'pass')
        self.assertEqual(e.semantic_focus(self.packet, self.gold)['verdict'], 'pass')

    def test_missing_value_not_offset_by_optional_document(self):
        packet = deepcopy(self.packet); packet['facts'].pop()
        packet['facts'].append({'kind': 'document', 'fact_id': 'optional'})
        result = e.numeric_coverage(packet, self.gold)
        self.assertEqual(result['coverage'], '3/4'); self.assertEqual(result['verdict'], 'fail')

    def test_wrong_values_currency_dates_and_segment_scope(self):
        for field, value in [('value_decimal', '123'), ('unit', 'EUR'), ('entity_id', 'sec-0002'),
                             ('dimensions', {'Axis': 'Segment'}), ('metric_id', 'profit')]:
            with self.subTest(field=field):
                packet = deepcopy(self.packet); packet['facts'][0]['value'][field] = value
                self.assertEqual(e.numeric_coverage(packet, self.gold)['verdict'], 'fail')
        packet = deepcopy(self.packet); packet['facts'][0]['value']['period']['start'] = '2024-07-01'
        self.assertEqual(e.numeric_coverage(packet, self.gold)['verdict'], 'fail')

    def test_duplicate_fact_is_extra(self):
        packet = deepcopy(self.packet); extra = deepcopy(packet['facts'][0]); extra['fact_id'] = 'duplicate'
        packet['facts'].append(extra)
        result = e.numeric_coverage(packet, self.gold)
        self.assertEqual(result['verdict'], 'fail'); self.assertIn('duplicate', result['extra_fact_ids'])

    def test_false_original_context_or_altered_citation_is_rejected(self):
        packet = deepcopy(self.packet); packet['facts'][0]['value']['origin']['context_ref'] = 'c1'
        self.assertEqual(e.original_semantics(packet, self.gold, self.base)['verdict'], 'fail')
        packet = deepcopy(self.packet); packet['facts'][0]['citations'][0]['quote'] = 'invented'
        self.assertEqual(e.original_semantics(packet, self.gold, self.base)['verdict'], 'fail')

    def test_changed_selected_original_is_rejected(self):
        packet = deepcopy(self.packet); packet['source_documents'][0]['blocks'][0]['text'] += ' invented'
        with self.assertRaisesRegex(ValueError, 'text changed'):
            e.original_semantics(packet, self.gold, self.base)

    def test_equivalent_total_table_duplicate_requires_independent_judgment(self):
        packet = deepcopy(self.packet); gold = deepcopy(self.gold)
        another = deepcopy(packet['source_documents'][0]['blocks'][0]); another['block_id'] = 'equivalent-table'
        packet['source_documents'][0]['blocks'].append(another)
        for required in gold['required'][:2]:
            required['original_references'].append({'fact_dom_path': '/other', 'table_block_id': another['block_id']})
        focused = e.semantic_focus(packet, gold)
        self.assertEqual(focused['verdict'], 'manual_review_required')
        self.assertTrue(any('Repeated equivalent' in r['reason'] for r in focused['manual_review_items']))

    def test_unrelated_table_does_not_receive_automatic_context_credit(self):
        packet = deepcopy(self.packet)
        packet['source_documents'][0]['blocks'].append({'block_id': 'segment', 'type': 'table',
            'text': 'Segment profit and expenses', 'text_hash': 'fixture'})
        self.assertEqual(e.semantic_focus(packet, self.gold)['verdict'], 'manual_review_required')

    def test_sdk_body_and_final_projection_are_separate(self):
        query = self.base / 'data-query/query'; path = query / 'turn-001/input.json'
        projection = [{'source_snapshot_id': d['source_snapshot_id'], 'block_ids': [b['block_id'] for b in d['blocks']]}
                      for d in self.packet['source_documents']]
        sdk = {'active_scope': self.packet['scope'], 'observation': None,
            'record_selection_effect': {'value': {'delivery_schema_version': 'selected-originals-v4', 'delivery_block_ids': projection}}}
        self.assertEqual(e.projection.visible_projection(self.packet, query, [], {'verdict': 'pass'})['verdict'], 'fail')
        inputs = [(path, sdk)]
        self.assertEqual(e.projection.visible_projection(self.packet, query, inputs, {'verdict': 'pass'})['verdict'], 'pass')
        self.assertEqual(e.protocol.body_exposure(self.packet, inputs)['verdict'], 'fail')
        sdk['retained_body'] = {'items': [dict(b, source_snapshot_id=d['source_snapshot_id'])
            for d in self.packet['source_documents'] for b in d['blocks']]}
        self.assertEqual(e.protocol.body_exposure(self.packet, inputs)['verdict'], 'pass')
        self.assertEqual(e.projection.visible_projection(self.packet, query, inputs, {'verdict': 'fail'})['verdict'], 'fail')

    def test_sdk_packet_binding_rejects_disk_only_and_gold(self):
        query = self.base / 'data-query/query'; input_path = query / 'turn-001/input.json'
        packet = {'active_scope': self.packet['scope'], 'observation': None}
        write(input_path, packet)
        self.assertEqual(e.actual_inputs(query)[1]['verdict'], 'fail')
        model = query.parent / 'model'; call = model / 'calls/fixture-end.json'
        write(call, {'status': 'synthetic-protocol-fixture'})
        def decision(value):
            write(input_path, value)
            write(model / 'decision-0001-attempt-01.json', {'plan_origin': 'model', 'role': 'planner',
                'packet_sha256': e.protocol.digest(json.dumps(value, ensure_ascii=False)),
                'calls': [{'path': 'calls/fixture-end.json', 'sha256': e.sha(call)}]})
        decision(packet)
        self.assertEqual(e.actual_inputs(query)[1]['verdict'], 'pass')
        decision(dict(packet, skill_body='Preserve independent_acceptance, coordinate_status and gaps; protocol validation does not prove business acceptance.'))
        self.assertEqual(e.actual_inputs(query)[1]['verdict'], 'pass')
        for marker in ('expected.v1.json', 'evaluation-only', 'standard.v1.json', 'root-original-review',
                       'withheld_standard_sha256', 'raw-original-precheck'):
            with self.subTest(private_marker=marker):
                decision(dict(packet, leaked=marker))
                self.assertEqual(e.actual_inputs(query)[1]['verdict'], 'fail')


if __name__ == '__main__':
    unittest.main()
