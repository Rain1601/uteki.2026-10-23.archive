"""Frozen Data-only HTML delivery; no model API or browser calls."""
from copy import deepcopy
import asyncio
import json
import unittest
from urllib.parse import parse_qs, urlparse

from lxml import html

from apps.review_workbench.pages.data_review_delivery import render_data_review, _quote_coordinates
from tests.unit import test_bounded_answer_handoff as fixtures
from uteki.infrastructure.research_data.financial_records import digest
from uteki.agents.data_query.answer_handoff import review_data_answer
from tests.unit.test_answer_handoff import ScriptedRole


class DataReviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BoundedAnswerHandoffTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        _, query = self.fixture.raw_query()
        self.packet = self.fixture.prepare(query)
        self.result, self.review = self.fixture.review(self.packet)
        self.output = self.fixture.root/'delivery'

    def render(self, **options):
        return render_data_review(self.review, self.output,
            expected_manifest_sha256=self.result['review_ref']['manifest_sha256'], **options)

    def test_local_page_is_bound_original_evidence_with_exact_range_and_frozen_artifacts(self):
        result = self.render()
        page = html.fromstring((self.output/'index.html').read_bytes())
        self.assertIn(self.packet['question'], page.text_content())
        self.assertIn('scripted_fixture', page.text_content())
        self.assertIn('尚未经人工验收', page.text_content())
        self.assertTrue(page.xpath('//mark'))
        self.assertEqual(result['human_acceptance'], 'not_evaluated')
        self.assertIsNone(result['dataset_key'])
        self.assertNotIn('/data-workspace/source?', page.text_content())
        for link in page.xpath('//a/@href'):
            if link.startswith('#'): self.assertTrue(page.xpath('//*[@id=$id]', id=link[1:]))
            elif not urlparse(link).scheme: self.assertTrue((self.output/link).is_file())
        self.assertEqual((self.output/'input.json').read_bytes(), (self.review/'input.json').read_bytes())
        manifest = json.loads((self.output/'manifest.json').read_text())
        for name, sha in manifest['files'].items(): self.assertEqual(digest((self.output/name).read_bytes()), sha)

    def test_explicit_registry_link_carries_precise_location_and_identity(self):
        result = self.render(dataset_key='selected-dataset', source_preview_base_url='http://127.0.0.1:8765/data-workspace/source')
        page = html.fromstring((self.output/'index.html').read_bytes())
        links = [urlparse(url) for url in page.xpath('//a/@href') if '/data-workspace/source?' in url]
        self.assertEqual(len(links), len(result['references']))
        for link, ref in zip(links, result['references']):
            values = parse_qs(link.query)
            self.assertEqual(values['dataset'], ['selected-dataset'])
            self.assertEqual(values['block'], [ref['block_id']])
            self.assertEqual(values['source'], [ref['source_snapshot_id']])
            self.assertEqual(values['char_start'], [str(ref['char_start'])])
            self.assertEqual(values['char_end'], [str(ref['char_end'])])
            self.assertEqual(values['quote'], [ref['quote']])
            self.assertEqual(values['source_sha256'], [ref['source_sha256']])
            self.assertEqual(link.fragment, 'workspace-evidence')

    def test_complete_but_trim_requested_is_visible_and_not_presented_as_reviewed(self):
        def respond(packet):
            response = fixtures.narrow_assessment(packet)
            response['revision_requests'] = ['Remove repeated context.']
            return response
        self.review = self.fixture.root/'trim-review'
        self.result = asyncio.run(review_data_answer(self.packet, self.review,
            reviewer_factory=lambda path: ScriptedRole(respond)))
        result = self.render()
        page = html.fromstring((self.output/'index.html').read_bytes())
        self.assertIn('待修订 / Requested revisions', page.text_content())
        self.assertIn('Remove repeated context.', page.xpath('//li')[0].text_content())
        self.assertEqual(self.result['status'], 'needs_revision')
        self.assertFalse(self.result['analysis_eligible'])

    def test_hash_mismatch_rejected_without_output(self):
        with self.assertRaises(ValueError):
            render_data_review(self.review, self.output, expected_manifest_sha256='0'*64)
        self.assertFalse(self.output.exists())

    def test_resealed_missing_or_foreign_citation_does_not_render_success(self):
        for changes in ({'block_id': 'absent'}, {'source_snapshot_id': 'another-source'}):
            packet = deepcopy(self.packet)
            packet['facts'][0]['citations'][0].update(changes)
            (self.review/'input.json').write_text(json.dumps(packet))
            saved = json.loads((self.review/'result.json').read_text()); saved['input_sha256'] = digest(packet)
            (self.review/'result.json').write_text(json.dumps(saved))
            manifest = json.loads((self.review/'manifest.json').read_text())
            for name in ('input.json', 'result.json'): manifest['files'][name] = digest((self.review/name).read_bytes())
            (self.review/'manifest.json').write_text(json.dumps(manifest))
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                render_data_review(self.review, self.output,
                    expected_manifest_sha256=digest((self.review/'manifest.json').read_bytes()))
            self.assertFalse(self.output.exists())

    def test_no_implicit_registry_or_unsafe_source_endpoint(self):
        for options in ({'dataset_key': 'selected'}, {'source_preview_base_url': 'http://localhost/source'},
                        {'dataset_key': 'selected', 'source_preview_base_url': 'javascript:alert(1)'},
                        {'dataset_key': 'selected', 'source_preview_base_url': 'http://localhost/source?dataset=other'}):
            with self.subTest(options=options), self.assertRaises(ValueError): self.render(**options)
        self.assertFalse(self.output.exists())

    def test_repeat_text_needs_explicit_span_and_foreign_quote_rejected(self):
        source = {'source_snapshot_id': 's', 'source_sha256': 'a'*64, 'index_id': 'i',
                  'blocks': [{'block_id': 'b', 'type': 'paragraph', 'text': 'same. same.'}]}
        quote = {'source_snapshot_id': 's', 'block_id': 'b', 'quote': 'same.'}
        with self.assertRaisesRegex(ValueError, 'unique'): _quote_coordinates(quote, {'s': source})
        self.assertEqual(_quote_coordinates({**quote, 'char_start': 6, 'char_end': 11}, {'s': source})[2], (6, 11))
        with self.assertRaises(ValueError): _quote_coordinates({**quote, 'quote': 'other'}, {'s': source})
