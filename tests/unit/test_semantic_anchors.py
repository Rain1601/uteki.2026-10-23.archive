"""Financial constraints must cite their DOM-bound complete row, not any matching number."""
from copy import deepcopy
import unittest

from lxml import html

from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import _visible_text
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_anchors import SemanticEvidenceError, build_record_anchors, build_record_anchors_v3, validate_record_anchor_coverage


class SemanticAnchorTests(unittest.TestCase):
    def packet(self, body=None):
        raw = ('<html><body>' + (body or '<table><tr><td>Revenue </td><td><span id="revenue">100</span></td></tr>'
            '<tr><td>Operating profit </td><td><span id="profit">100</span></td></tr></table>') + '</body></html>').encode()
        tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
        element = tree.xpath('//table|//p')[0]
        path = tree.getroottree().getpath(element)
        text = normalize_text(_visible_text(element))
        source = {'source_snapshot_id': 'source-a', 'company_id': 'company-a', 'source_sha256': digest(raw), 'available_at': '2025-02-01'}
        packet = {'scope': {'snapshot_id': 'snapshot-a', 'company_ids': ['company-a'], 'source_snapshot_ids': ['source-a'],
                           'source_policy_id': 'local-frozen-v1', 'knowledge_cutoff': '2025-03-01', 'include_candidates': True},
                  'source': source, 'source_blocks': [{'source_snapshot_id': 'source-a', 'block_id': 'block-a',
                     'dom_path': path, 'text': text, 'text_hash': digest(text.encode())}], 'records': []}
        for fact in tree.xpath('//*[@id]'):
            rid = fact.get('id')
            record = {'record_id': rid, 'source_snapshot_id': 'source-a', 'evidence_ids': ['ev-'+rid],
                      'available_at': '2025-02-01', 'status': 'candidate'}
            packet['records'].append({'record': record, 'evidence': {'source_snapshot_id': 'source-a',
                'source_sha256': digest(raw), 'evidence_id': 'ev-'+rid, 'block_id': 'block-a', 'dom_path': path,
                'fact_dom_path': tree.getroottree().getpath(fact), 'quote': normalize_text(_visible_text(fact))}})
        return packet, raw

    def citation(self, anchor):
        return {'source_snapshot_id': anchor['source_snapshot_id'], 'block_id': anchor['block_id'],
                'quote': anchor['text'], 'source_start': anchor['start']}

    def test_identical_numbers_in_other_rows_do_not_cover_profit(self):
        packet, raw = self.packet()
        anchors = packet['record_anchors'] = build_record_anchors(packet, raw)
        self.assertEqual(anchors['revenue']['text'], 'Revenue 100')
        self.assertEqual(anchors['profit']['text'], 'Operating profit 100')
        self.assertEqual(anchors['profit']['kind'], 'table_row')
        constraint = {'record_ids': ['profit'], 'citations': [self.citation(anchors['revenue'])]}
        with self.assertRaisesRegex(ValueError, 'complete record anchor'):
            validate_record_anchor_coverage(packet, constraint)
        constraint['citations'] = [self.citation(anchors['profit'])]
        validate_record_anchor_coverage(packet, constraint)
        constraint['record_ids'] = ['revenue', 'profit']
        with self.assertRaises(ValueError):
            validate_record_anchor_coverage(packet, constraint)
        constraint['citations'].append(self.citation(anchors['revenue']))
        validate_record_anchor_coverage(packet, constraint)

    def test_numeric_substring_wrong_offset_and_joined_fragments_are_rejected(self):
        packet, raw = self.packet()
        packet['record_anchors'] = build_record_anchors(packet, raw)
        anchor = packet['record_anchors']['profit']
        for citation in (
            {**self.citation(anchor), 'quote': '100', 'source_start': anchor['end']-3},
            {**self.citation(anchor), 'source_start': 0},
            {**self.citation(anchor), 'source_start': True},
            {**self.citation(anchor), 'source_start': None},
            {**self.citation(anchor), 'source_snapshot_id': 'other'},
        ):
            with self.subTest(citation=citation), self.assertRaises(ValueError):
                validate_record_anchor_coverage(packet, {'record_ids': ['profit'], 'citations': [citation]})
        first = {**self.citation(anchor), 'quote': anchor['text'][:10]}
        second = {**self.citation(anchor), 'quote': anchor['text'][10:], 'source_start': anchor['start']+10}
        with self.assertRaises(ValueError):
            validate_record_anchor_coverage(packet, {'record_ids': ['profit'], 'citations': [first, second]})

    def test_duplicate_row_text_is_unavailable_without_number_fallback(self):
        packet, raw = self.packet('<table><tr><td>Revenue </td><td><span id="a">100</span></td></tr>'
                                  '<tr><td>Revenue </td><td><span id="b">100</span></td></tr></table>')
        anchors = build_record_anchors(packet, raw)
        self.assertTrue(all(a['status'] == 'unavailable' and a['reason'] == 'row_or_paragraph_not_uniquely_located'
                            for a in anchors.values()))

    def test_non_table_requires_full_visible_source_block(self):
        packet, raw = self.packet('<p>Total income <span style="display:none">SECRET</span><span id="profit">100</span> USD.</p>')
        packet['record_anchors'] = build_record_anchors(packet, raw)
        anchor = packet['record_anchors']['profit']
        self.assertEqual(anchor['kind'], 'paragraph')
        self.assertEqual(anchor['text'], packet['source_blocks'][0]['text'])
        self.assertNotIn('SECRET', anchor['text'])
        validate_record_anchor_coverage(packet, {'record_ids': ['profit'], 'citations': [self.citation(anchor)]})

    def test_missing_locator_quote_mismatch_and_unsupplied_block_are_unavailable(self):
        for change, reason in [({'fact_dom_path': None}, 'fact_or_block_dom_not_unique'),
                               ({'quote': '999'}, 'fact_raw_quote_not_visible_or_mismatched'),
                               ({'block_id': 'not-supplied'}, 'source_block_not_supplied')]:
            packet, raw = self.packet()
            packet['records'][0]['evidence'].update(change)
            with self.subTest(change=change):
                self.assertEqual(build_record_anchors(packet, raw)['revenue']['reason'], reason)

    def test_cross_source_hash_and_dom_outside_block_raise(self):
        original, raw = self.packet()
        for target, changes in [('source', {'company_id': 'other'}), ('source', {'source_sha256': 'wrong'})]:
            packet = deepcopy(original); packet[target].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_record_anchors(packet, raw)
        for changes in ({'source_snapshot_id': 'other'}, {'source_sha256': 'wrong'}, {'dom_path': '/html/body/p'}):
            packet = deepcopy(original); packet['records'][0]['evidence'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                build_record_anchors(packet, raw)
        packet = deepcopy(original)
        packet['records'][0]['evidence']['fact_dom_path'] = '/html/body'
        with self.assertRaisesRegex(ValueError, 'outside its source block'):
            build_record_anchors(packet, raw)

    def test_unavailable_anchor_cannot_be_satisfied_by_arbitrary_citation(self):
        packet, raw = self.packet()
        packet['record_anchors'] = build_record_anchors(packet, raw)
        citation = self.citation(packet['record_anchors']['profit'])
        packet['record_anchors']['profit'] = {'status': 'unavailable', 'reason': 'missing'}
        with self.assertRaisesRegex(ValueError, 'anchor unavailable'):
            validate_record_anchor_coverage(packet, {'record_ids': ['profit'], 'citations': [citation]})

    def test_v3_duplicate_rows_have_distinct_dom_offsets(self):
        packet, raw = self.packet('<table><tr><td>Revenue </td><td><span id="a">100</span></td></tr>'
                                  '<tr><td>Revenue </td><td><span id="b">100</span></td></tr></table>')
        anchors = packet['record_anchors'] = build_record_anchors_v3(packet, raw)
        self.assertEqual(anchors['a']['text'], anchors['b']['text'])
        self.assertEqual(anchors['a']['start'], 0)
        self.assertEqual(anchors['b']['start'], len('Revenue 100'))
        with self.assertRaisesRegex(ValueError, 'complete record anchor'):
            validate_record_anchor_coverage(packet, {'record_ids': ['b'], 'citations': [self.citation(anchors['a'])]})
        validate_record_anchor_coverage(packet, {'record_ids': ['b'], 'citations': [self.citation(anchors['b'])]})

    def test_v3_inline_duplicate_numbers_require_the_correct_occurrence(self):
        packet, raw = self.packet('<p>Revenue <span id="a">100</span>; profit <span id="b">100</span> USD.</p>')
        anchors = packet['record_anchors'] = build_record_anchors_v3(packet, raw)
        self.assertEqual(anchors['b']['kind'], 'inline_fact')
        self.assertEqual(anchors['b']['text'], '100')
        self.assertEqual(anchors['b']['start'], len('Revenue 100; profit '))
        self.assertEqual(anchors['b']['context_text'], packet['source_blocks'][0]['text'])
        with self.assertRaisesRegex(ValueError, 'complete record anchor'):
            validate_record_anchor_coverage(packet, {'record_ids': ['b'], 'citations': [self.citation(anchors['a'])]})
        validate_record_anchor_coverage(packet, {'record_ids': ['b'], 'citations': [self.citation(anchors['b'])]})

    def test_v3_unicode_whitespace_comments_hidden_and_tails(self):
        packet, raw = self.packet('<p>收益😀\u00a0 <span hidden>100</span>\t'
            '<!-- 100 -->尾 <span id="a"> \u00a010<b>0</b><!--secret-->\n'
            '<span style="display: none">999</span>\u2003元 </span>\n'
            '<script>100</script> 后 <span id="b">100</span>。</p>')
        anchors = build_record_anchors_v3(packet, raw)
        self.assertEqual(anchors['a']['text'], '100 元')
        self.assertEqual(anchors['a']['start'], len('收益😀 尾 '))
        self.assertEqual(anchors['b']['start'], len('收益😀 尾 100 元 后 '))
        self.assertEqual(anchors['b']['text'], '100')
        self.assertNotIn('secret', anchors['a']['context_text'])
        self.assertNotIn('999', anchors['a']['context_text'])

    def test_v3_hidden_fact_and_changed_block_are_unavailable(self):
        packet, raw = self.packet('<p>100 <span hidden><span id="a">100</span></span></p>')
        self.assertEqual(build_record_anchors_v3(packet, raw)['a']['status'], 'unavailable')
        packet, raw = self.packet()
        block = packet['source_blocks'][0]
        block['text'] = 'prefix ' + block['text']
        block['text_hash'] = digest(block['text'].encode())
        self.assertTrue(all(a['status'] == 'unavailable' for a in build_record_anchors_v3(packet, raw).values()))

    def test_v3_scope_binding_and_policy_validation(self):
        packet, raw = self.packet()
        with self.assertRaisesRegex(ValueError, 'original bytes hash'):
            build_record_anchors_v3(packet, raw + b' ')
        packet['source']['company_id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'outside execution scope'):
            build_record_anchors_v3(packet, raw)
        with self.assertRaisesRegex(ValueError, 'unsupported record anchor policy'):
            build_record_anchors(packet, raw, policy='unknown')

    def test_coverage_errors_include_bounded_repair_details(self):
        packet, raw = self.packet()
        anchors = packet['record_anchors'] = build_record_anchors_v3(packet, raw)
        constraint = {'record_ids': ['profit'], 'citations': [self.citation(anchors['revenue'])]}
        with self.assertRaisesRegex(SemanticEvidenceError, 'complete record anchor') as caught:
            validate_record_anchor_coverage(packet, constraint)
        expected_first = {
            'code': 'record_anchor_uncovered', 'record_id': 'profit',
            'required_span': {key: anchors['profit'][key] for key in
                              ('source_snapshot_id', 'block_id', 'start', 'end', 'text', 'kind')},
        }
        self.assertEqual({key: caught.exception.details[key] for key in expected_first}, expected_first)
        self.assertEqual(caught.exception.details['missing_anchors'], [expected_first])
        anchors['profit'] = {'status': 'unavailable', 'reason': 'fact_evidence_missing'}
        with self.assertRaisesRegex(SemanticEvidenceError, 'record anchor unavailable') as caught:
            validate_record_anchor_coverage(packet, constraint)
        expected_first = {'code': 'record_anchor_unavailable',
                          'record_id': 'profit', 'reason': 'fact_evidence_missing'}
        self.assertEqual({key: caught.exception.details[key] for key in expected_first}, expected_first)
        self.assertEqual(caught.exception.details['missing_anchors'], [expected_first])
        del anchors['profit']
        with self.assertRaises(SemanticEvidenceError) as caught:
            validate_record_anchor_coverage(packet, constraint)
        self.assertEqual(caught.exception.details['reason'], 'anchor_missing')
        constraint['citations'][0]['source_start'] = -1
        with self.assertRaises(ValueError) as caught:
            validate_record_anchor_coverage(packet, constraint)
        self.assertNotIsInstance(caught.exception, SemanticEvidenceError)

    def test_v3_whitespace_run_crossing_fact_boundary_maps_later_characters(self):
        packet, raw = self.packet('<p>前\u00a0\t<span id="a">\u2003 12\u00a0<b>\u2003\t34 </b>'
                                  '\u2003</span>\n\u00a0后\u2003<span id="b">\u00a056 </span>。</p>')
        anchors = build_record_anchors_v3(packet, raw)
        self.assertEqual(packet['source_blocks'][0]['text'], '前 12 34 后 56 。')
        self.assertEqual((anchors['a']['start'], anchors['a']['end'], anchors['a']['text']), (2, 7, '12 34'))
        self.assertEqual((anchors['b']['start'], anchors['b']['end'], anchors['b']['text']), (10, 12, '56'))

    def test_versioned_line_breaks_bind_complete_rows_and_inline_offsets(self):
        for body, expected in [
            ('<table><tr><td>Revenue<br>net </td><td><span id="a">100</span></td></tr>'
             '<tr><td>Profit<br hidden> </td><td><span id="b">100</span></td></tr></table>',
             ('Revenue net 100', 'Profit 100')),
            ('<p>净额<br>收入 <span id="a">1<b>,200</b></span> / '
             '<span id="b">50<br>万元</span></p>', ('1,200', '50 万元')),
        ]:
            packet, raw = self.packet(body)
            legacy = build_record_anchors_v3(packet, raw)
            self.assertTrue(all(a['status'] == 'located' for a in legacy.values()))
            tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
            block = packet['source_blocks'][0]
            block['text'] = normalize_text(_visible_text(tree.xpath('//table|//p')[0], preserve_line_breaks=True))
            block['text_hash'] = digest(block['text'].encode())
            for item in packet['records']:
                fact = tree.xpath('//*[@id="'+item['record']['record_id']+'"]')[0]
                item['evidence']['quote'] = normalize_text(_visible_text(fact, preserve_line_breaks=True))
            packet['parser_version'] = 'sec-source-blocks-v0.1.12'
            anchors = packet['record_anchors'] = build_record_anchors_v3(packet, raw)
            self.assertEqual(tuple(anchors[k]['text'] for k in ('a', 'b')), expected)
            for key, anchor in anchors.items():
                validate_record_anchor_coverage(packet, {'record_ids': [key], 'citations': [self.citation(anchor)]})
            packet['parser_version'] = 'sec-source-blocks-v0.1.11'
            self.assertTrue(all(a['status'] == 'unavailable' for a in build_record_anchors_v3(packet, raw).values()))
            packet['parser_version'] = 'unsupported'
            with self.assertRaisesRegex(ValueError, 'parser version'):
                build_record_anchors_v3(packet, raw)

    def test_versioned_v2_paragraph_and_table_consumers(self):
        for body in ('<p>Revenue<br>net <span id="a">100</span>.</p>',
                     '<table><tr><td>Revenue<br>net </td><td><span id="a">100</span></td></tr></table>'):
            packet, raw = self.packet(body)
            block = packet['source_blocks'][0]
            block['text'] = block['text'].replace('Revenuenet', 'Revenue net')
            block['text_hash'] = digest(block['text'].encode())
            packet['parser_version'] = 'sec-source-blocks-v0.1.12'
            self.assertEqual(build_record_anchors(packet, raw)['a']['text'], block['text'])
