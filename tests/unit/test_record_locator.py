"""Frozen inline XBRL facts disambiguate equal values by DOM, never first match."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from lxml import html
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _visible_text, _table_structure
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.record_locator import resolve_record_locator

ROOT = Path(__file__).resolve().parents[2]


class RecordLocatorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        raw = b'''<html><body><table>
<tr><th rowspan="2">Item</th><th colspan="2">Period</th></tr>
<tr><td>2031</td><td>2030</td></tr>
<tr><td>Sales</td><td colspan="2"><ix:nonfraction id="first" name="us-gaap:Revenue" contextref="year2031" unitref="USD">42</ix:nonfraction></td></tr>
<tr><td>Other</td><td><ix:nonfraction id="second" name="us-gaap:Revenue" contextref="year2030" unitref="USD">42</ix:nonfraction></td><td>42</td></tr>
</table></body></html>'''
        tree = html.document_fromstring(raw)
        table = tree.xpath('//table')[0]
        text = normalize_text(_visible_text(table, preserve_line_breaks=True))
        grid = asdict(_table_structure(table, visible_only=True, nearest_table=True, preserve_line_breaks=True))
        grid['cells'] = list(grid['cells'])
        self.block = {'block_id': 'table-b', 'source_snapshot_id': 'cedar-2031', 'type': 'table', 'text': text,
            'text_hash': digest(text.encode()), 'dom_path': '/html/body/table', 'table': grid}
        self.source = {'source_snapshot_id': 'cedar-2031', 'company_id': 'cedar', 'source_sha256': digest(raw),
            'index_id': 'index-cedar', 'index_folder': 'index', 'raw_file': 'report.html',
            'raw_file_sha256': digest(raw), 'parsed_mime_type': 'text/html'}
        self.save('sources.json', [self.source])
        self.save('index/index.json', {'index_id': 'index-cedar', 'source_snapshot_id': 'cedar-2031',
            'parser_version': 'sec-source-blocks-v0.1.12'})
        (self.root/'index/blocks.jsonl').write_text(json.dumps(self.block)+'\n')
        self.save('index/manifest.json', {'source_snapshot_id': 'cedar-2031', 'source_sha256': digest(raw),
            'artifacts': {name: {'sha256': digest((self.root/'index'/name).read_bytes())}
                          for name in ('index.json', 'blocks.jsonl')}})
        (self.root/'report.html').write_bytes(raw)
        self.save('manifest.json', {'files': {str(p.relative_to(self.root)): digest(p.read_bytes())
            for p in self.root.rglob('*') if p.is_file()}})
        second = tree.xpath('//*[@id="second"]')[0]
        self.evidence = {'source_snapshot_id': 'cedar-2031', 'source_sha256': digest(raw), 'index_id': 'index-cedar',
            'block_id': 'table-b', 'text_hash': self.block['text_hash'], 'dom_path': '/html/body/table',
            'fact_dom_path': tree.getroottree().getpath(second), 'fact_id': 'second', 'context_ref': 'year2030',
            'unit_ref': 'USD', 'concept': 'us-gaap:Revenue', 'quote': '42'}

    def save(self, relative, value):
        path = self.root/relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_repeated_value_binds_second_fact_and_merged_grid_correctly(self):
        before = (self.root/'report.html').read_bytes()
        result = resolve_record_locator(self.root, self.evidence)
        self.assertEqual(result['cell'], {'row': 3, 'column': 1})
        self.assertEqual(self.block['text'][result['char_start']:result['char_end']], '42')
        self.assertGreater(result['char_start'], self.block['text'].find('42'))
        self.assertEqual((self.root/'report.html').read_bytes(), before)
        first = {**self.evidence, 'fact_id': 'first', 'context_ref': 'year2031',
                 'fact_dom_path': '/html/body/table/tr[3]/td[2]/ix:nonfraction'}
        first_result = resolve_record_locator(self.root, first)
        self.assertEqual(first_result['cell'], {'row': 2, 'column': 1})
        self.assertLess(first_result['char_start'], result['char_start'])

    def test_wrong_fact_identity_span_cell_or_cross_source_is_rejected(self):
        for changes in ({'fact_id': 'first'}, {'context_ref': 'year2031'}, {'source_snapshot_id': 'other'},
                        {'source_sha256': '0'*64}, {'index_id': 'other-index'}, {'text_hash': '0'*64},
                        {'quote': '24'}, {'fact_dom_path': '/html/body/table/tr[99]/td'},
                        {'dom_path': '/html/body/table[2]'}, {'unit_ref': 'EUR'}, {'concept': 'us-gaap:Income'},
                        {'char_start': self.block['text'].find('42'), 'char_end': self.block['text'].find('42')+2},
                        {'cell': {'row': 2, 'column': 1}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                resolve_record_locator(self.root, {**self.evidence, **changes})

    def test_missing_dom_cannot_choose_first_repeated_quote_but_unique_quote_is_valid(self):
        evidence = {k: v for k, v in self.evidence.items() if k != 'fact_dom_path'}
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            resolve_record_locator(self.root, evidence)
        result = resolve_record_locator(self.root, {**evidence, 'quote': 'Sales'})
        self.assertEqual(self.block['text'][result['char_start']:result['char_end']], 'Sales')
        self.assertNotIn('cell', result)

    def test_mutated_raw_or_index_is_rejected_by_frozen_file_hash(self):
        for name in ('report.html', 'index/blocks.jsonl'):
            path = self.root/name; original = path.read_bytes()
            path.write_bytes(original + b'\n ')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'hash'):
                resolve_record_locator(self.root, self.evidence)
            path.write_bytes(original)

    def test_legacy_missing_mime_uses_verified_bytes_without_changing_snapshot(self):
        self.source.pop('parsed_mime_type')
        self.save('sources.json', [self.source])
        manifest=json.loads((self.root/'manifest.json').read_text())
        manifest['files']['sources.json']=digest((self.root/'sources.json').read_bytes())
        self.save('manifest.json',manifest)
        before = {str(p.relative_to(self.root)):digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(resolve_record_locator(self.root,self.evidence)['cell'],{'row':3,'column':1})
        self.assertEqual(before,{str(p.relative_to(self.root)):digest(p.read_bytes()) for p in self.root.rglob('*') if p.is_file()})

    def test_explicit_unsupported_mime_is_not_reinterpreted_as_html(self):
        for mime in ('application/pdf','application/xml','application/octet-stream','',None):
            self.source['parsed_mime_type'] = mime
            self.source['declared_mime_type'] = 'application/pdf'
            self.save('sources.json', [self.source])
            manifest=json.loads((self.root/'manifest.json').read_text())
            manifest['files']['sources.json']=digest((self.root/'sources.json').read_bytes())
            self.save('manifest.json',manifest)
            with self.subTest(mime=mime),self.assertRaisesRegex(ValueError,'requires frozen HTML'):
                resolve_record_locator(self.root,self.evidence)


class RealRecordLocatorTests(unittest.TestCase):
    def test_real_msft_and_googl_fact_dom_and_duplicate_values(self):
        for company in ('msft', 'googl'):
            dataset = ROOT/'experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets'/company
            if not (dataset/'evidence.json').exists(): self.skipTest('Explicit real dataset fixture unavailable')
            sources = {s['source_snapshot_id']: s for s in json.loads((dataset/'sources.json').read_text())}
            blocks = {s['source_snapshot_id']: {b['block_id']: b for b in map(json.loads,
                (dataset/s['index_folder']/'blocks.jsonl').read_text().splitlines())} for s in sources.values()}
            evidence = list(json.loads((dataset/'evidence.json').read_text()).values())
            repeated = [e for e in evidence if e['evidence_id'] != evidence[0]['evidence_id']
                        and blocks[e['source_snapshot_id']][e['block_id']]['text'].count(e['quote']) > 1]
            self.assertTrue(repeated)
            for item in (evidence[0], *repeated[:2]):
                with self.subTest(company=company, evidence=item['evidence_id']):
                    source = sources[item['source_snapshot_id']]
                    rawpath = dataset/source['raw_file']; before = digest(rawpath.read_bytes())
                    result = resolve_record_locator(dataset, item)
                    block = blocks[item['source_snapshot_id']][item['block_id']]
                    self.assertEqual(block['text'][result['char_start']:result['char_end']], item['quote'])
                    self.assertEqual(result['text_hash'], block['text_hash'])
                    cells = [c for c in block['table']['cells'] if all(c[k] == v for k, v in result['cell'].items())]
                    self.assertEqual(len(cells), 1)
                    self.assertIn(item['quote'], cells[0]['text'])
                    self.assertEqual(digest(rawpath.read_bytes()), before)
