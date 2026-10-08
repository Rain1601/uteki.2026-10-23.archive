"""Reader contracts, escaping and offline delivery; not a visual review."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from apps.review_workbench.pages.evidence_benchmark import render_page, render_evidence_benchmark


class EvidenceBenchmarkPageTests(unittest.TestCase):
    def setUp(self):
        self.case = dict(case_id='E1-01', status='draft', question='What <revenue>?',
                         gold_sha256='a' * 64, run_sha256=None, review=None, score=None,
                         required=[dict(id='R1', description='The amount and units')],
                         reference_explanation='Use original annual statements.', provided_explanation='Not yet run.',
                         coverage_explanation='Pending independent review.', missing=[], extra=[], limitations=['Synthetic fixture.'],
                         evidence=[dict(label='Original <source>', quote='<script>alert(1)</script>', url='https://example.org/report#block')],
                         process_links=[dict(label='Trace', url='../trace/index.html')])
        self.document = dict(schema_version='evidence-benchmark-page-v1', title='Independent review',
                             introduction='Synthetic fixture, no model call.', back_link=None, cases=[self.case])

    def test_draft_and_html_escaping(self):
        html = render_page(self.document)
        self.assertIn('评审草稿 · 未验收', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertIn('What &lt;revenue&gt;?', html)
        self.assertIn('<details><summary>版本与过程记录', html)
        self.assertNotIn('class="verdict pass"', html)

    def test_link_protocols_and_obfuscation_rejected(self):
        for url in ('javascript:alert(1)', 'data:text/html,test', '//evil.test',
                    'https://u:p@example.org', 'java\nscript:alert(1)', '%6aavascript:alert(1)',
                    'https://example.org/%0aevil', '\\evil.test'):
            with self.subTest(url=url):
                doc = deepcopy(self.document); doc['cases'][0]['evidence'][0]['url'] = url
                with self.assertRaises(ValueError): render_page(doc)

    def test_finished_needs_review_score_and_run_hash(self):
        self.case['status'] = 'finished'
        with self.assertRaises(ValueError): render_page(self.document)
        self.case['run_sha256'] = 'b' * 64
        with self.assertRaises(ValueError): render_page(self.document)

    def finished(self):
        self.case.update(status='finished', run_sha256='b' * 64)
        self.case['review'] = dict(schema_version='evidence-review-v1', case_id='E1-01', question=self.case['question'],
                                  requirements=[dict(id='R1', status='supported', reason='Synthetic support.')],
                                  checks={k: dict(status='pass') for k in ('scope', 'truth', 'provenance', 'focus')})
        self.case['score'] = dict(schema_version='evidence-score-v1', case_id='E1-01', status='pass',
            gates={k: 'pass' for k in ('scope', 'truth', 'provenance', 'focus', 'required_coverage', 'all_characters_assessed')},
            required_coverage=dict(numerator=1, denominator=1),
            characters=dict(unique_source_characters=10, repeated_location_occurrences=0,
                categories={k: dict(numerator=10 if k == 'required' else 0, denominator=10)
                            for k in ('required', 'optional', 'necessary_context', 'duplicate', 'irrelevant', 'unassessed', 'table_structure')}),
            cost=dict(known_estimated_usd='0.1', unknown_reserved_usd='0.2'))

    def test_finished_mapping_and_draft_override(self):
        self.finished()
        html = render_page(self.document)
        self.assertIn('class="verdict pass"', html)
        self.assertIn('$0.1000', html)
        self.case['status'] = 'draft'
        self.assertNotIn('class="verdict pass"', render_page(self.document))
        self.case['score']['gates']['focus'] = 'fail'
        with self.assertRaises(ValueError): render_page(self.document)

    def test_inconsistent_counts_and_question_rejected(self):
        self.finished()
        self.case['score']['required_coverage']['numerator'] = 0
        with self.assertRaises(ValueError): render_page(self.document)
        self.finished()
        self.case['review']['question'] = 'Unrelated question'
        with self.assertRaises(ValueError): render_page(self.document)

    def test_immutable_offline_output_and_bad_input_no_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'page.json'; output = root / 'delivery'
            source.write_text(json.dumps(self.document))
            result = render_evidence_benchmark(source, output)
            self.assertEqual(result['model_calls'], 0)
            self.assertEqual((output / 'input.json').read_bytes(), source.read_bytes())
            with self.assertRaises(ValueError): render_evidence_benchmark(source, output)
            self.document['cases'][0]['gold_sha256'] = 'not-a-hash'
            source.write_text(json.dumps(self.document))
            with self.assertRaises(ValueError): render_evidence_benchmark(source, root / 'invalid')
            self.assertFalse((root / 'invalid').exists())


if __name__ == '__main__':
    unittest.main()
