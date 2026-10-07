from copy import deepcopy
from dataclasses import asdict
import hashlib
import unittest

from uteki.infrastructure.document_sources.coverage_audit import audit_html_tenk
from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline


class CoverageAuditTests(unittest.TestCase):
    def fixture(self):
        raw = b'''<html><body><h1>PART I</h1><h2>ITEM 1. BUSINESS</h2>
        <p>All services<!-- retained tail --> include tools.</p><p hidden>Hidden duplicate</p><p>Retained section end.</p>
        <h2>ITEM 2. PROPERTIES</h2><table><tr><td>USD millions</td><td>32</td></tr></table>
        <p>See Note 4 for related disclosures.</p><img src="chart.png" alt="Chart"/>
        <p>Closing text.</p></body></html>'''
        parsed = parse_sec_source('orion-2040', 'https://example.invalid/orion-2040', raw,
            source_snapshot_id='orion-freeze', form_type='10-K', parser_version='sec-source-blocks-v0.1.12')
        source = dict(company_id='orion', document_id='orion-2040', source_snapshot_id='orion-freeze',
                      report_period_end='2040-12-31', source_url=parsed.source_url,
                      raw_sha256=hashlib.sha256(raw).hexdigest(), form_type='10-K', parser_version=parsed.parser_version)
        return raw, source, asdict(build_legal_outline(parsed)), [asdict(b) for b in parsed.blocks]

    def test_complete_text_never_certifies_semantics_or_unread_image(self):
        values = self.fixture()
        original = deepcopy(values)
        result = audit_html_tenk(*values)
        self.assertFalse(result['todo03_complete'])
        self.assertEqual(result['block_dom_order']['status'], 'monotonic')
        self.assertEqual(result['totals'].get('uncovered_visible_text', 0), 0)
        self.assertEqual(result['totals']['excluded_by_inline_visibility_rule'], 1)
        self.assertTrue(any(e['text_kind'] == 'tail' and e['text'] == 'include tools.' for e in result['text_ledger']))
        self.assertEqual(result['finding_counts']['visual_or_embedded_content_not_read'], 1)
        self.assertEqual(result['finding_counts']['table_semantics_not_reviewed'], 1)
        self.assertEqual(result['finding_counts']['cross_reference_candidate_not_resolved'], 1)
        self.assertTrue(all(s['independent_semantic_review'] == 'not_performed' for s in result['sections']))
        ids = [b for s in result['sections'] for b in s['block_ids']]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {b['block_id'] for b in values[3]})
        self.assertEqual(values, original)
        self.assertEqual(audit_html_tenk(*values), result)

    def test_missing_block_is_detected_from_original_not_block_inventory(self):
        raw, source, index, blocks = self.fixture()
        blocks = [b for b in blocks if not b['text'].startswith('All services')]
        result = audit_html_tenk(raw, source, index, blocks)
        self.assertGreater(result['totals']['uncovered_visible_text'], 0)
        self.assertTrue(any(s['structural_text_status'] == 'defects_found' for s in result['sections']))

    def test_present_block_with_missing_text_is_detected(self):
        raw, source, index, blocks = self.fixture()
        next(b for b in blocks if b['text'].startswith('All services'))['text'] = 'All services'
        result = audit_html_tenk(raw, source, index, blocks)
        self.assertEqual(result['finding_counts']['block_text_mismatch'], 1)
        self.assertEqual(result['totals']['represented_ancestor_but_text_missing'], 1)

    def test_scope_missing_tampered_original_and_other_form_fail_closed(self):
        raw, source, index, blocks = self.fixture()
        for missing in ('company_id', 'report_period_end', 'source_snapshot_id'):
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                audit_html_tenk(raw, {k:v for k,v in source.items() if k != missing}, index, blocks)
        for other in ({**source, 'form_type': '20-F'}, {**source, 'source_snapshot_id': 'other'},
                      {**source, 'raw_sha256': '0' * 64}):
            with self.assertRaises(ValueError):
                audit_html_tenk(raw, other, index, blocks)
        with self.assertRaises(ValueError):
            audit_html_tenk(raw + b'changed', source, index, blocks)
