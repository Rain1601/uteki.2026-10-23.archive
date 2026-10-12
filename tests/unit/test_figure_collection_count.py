"""Selected-transcription counts are typed evidence, never array-valued scalars."""
from copy import deepcopy
import unittest

from pydantic import ValidationError

from tests.unit import test_figure_handoff as fixtures
from uteki.agents.data_query.answer_handoff import (
    _validate_source_assessment, _question_projection, review_prompt,
    source_review_repair_input, SourceCitationProtocolError,
)
from uteki.agents.data_query.question_coverage_review import (
    FigureCollectionCountCitation, validate_figure_citation, validate_question_review,
)
from uteki.agents.data_query.question_review_generation import (
    question_generation_schema, question_generation_prompt, project_question_generation,
)


def count_ref(source='source-a', figure='figure-a', count=0, path='transcription.printed_values'):
    return dict(kind='figure_collection_count',source_snapshot_id=source,figure_id=figure,
                field_path=path,count=count)


class FigureCollectionCountTests(unittest.TestCase):
    def setUp(self):
        self.figures=[dict(source_snapshot_id='source-a',figure_id='figure-a',company_id='issuer-a',
            transcription={'printed_values':[]}),
            dict(source_snapshot_id='source-b',figure_id='figure-b',company_id='issuer-b',
            transcription={'printed_values':[{'text_id':'label-1'},{'text_id':'label-2'}]})]

    def test_independent_zero_and_two_label_figures_are_exact(self):
        for ref in (count_ref(),count_ref('source-b','figure-b',2)):
            self.assertEqual(validate_figure_citation(self.figures,ref),ref)
        for ref in (count_ref(count=2),count_ref('source-b','figure-b',0)):
            with self.assertRaisesRegex(ValueError,'differs from selected transcription'):
                validate_figure_citation(self.figures,ref)

    def test_strict_counts_and_single_allowlisted_collection_path(self):
        for count in (True,False,'0',0.0,-1,None):
            with self.subTest(count=count),self.assertRaises(ValidationError):
                FigureCollectionCountCitation.model_validate(count_ref(count=count))
        for path in ('transcription.texts','transcription.series','transcription.printed_values.0',
                     'transcription.texts.0.box','ocr.words','raw_usage','metadata','transcription.kind'):
            with self.subTest(path=path),self.assertRaises(ValidationError):
                validate_figure_citation(self.figures,count_ref(path=path))

    def test_unselected_other_source_company_unknown_or_duplicate_identity_rejected(self):
        for selected,ref in ((self.figures[:1],count_ref('source-b','figure-b',2)),
                             (self.figures,count_ref('source-b','figure-a')),
                             (self.figures,count_ref('source-a','figure-b')),
                             (self.figures,count_ref(figure='unknown')),
                             (self.figures*2,count_ref())):
            with self.assertRaisesRegex(ValueError,'outside selected original figures'):
                validate_figure_citation(selected,ref)

    def test_original_array_figure_field_is_still_rejected(self):
        ref=count_ref();ref.update(kind='figure_field',value='[]');ref.pop('count')
        with self.assertRaisesRegex(ValueError,'not a transcribed scalar'):
            validate_figure_citation(self.figures,ref)


class FigureCountHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.FigureHandoffTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.ref=count_ref(self.fixture.figure['source_snapshot_id'],self.fixture.figure['figure_id'])

    def test_source_all_four_citation_consumers_and_question_projection_accept_count(self):
        response=self.fixture.source_response()
        for field in ('facts','requirements','source_checks','figure_checks'):
            response[field][0]['citations']=[self.ref]
        _validate_source_assessment(self.fixture.packet,response)
        projected=_question_projection(self.fixture.packet)
        answer=self.fixture.question_response(projected)
        answer['checks'][0]['citations']=[self.ref]
        self.assertTrue(validate_question_review(projected,answer)[1])
        generation=deepcopy(answer)
        check=generation['checks'][0]
        request={key:check.pop(key) for key in ('question_quote','requested_subject','requested_dimension')}
        request['scope']={'kind':'self_contained','reason':'One scoped synthetic selected figure.'}
        generation['checks']=[{'request':request,'judgment':check}]
        schema=question_generation_schema(projected)
        schema.model_validate(generation)
        canonical=project_question_generation(generation,projected)
        self.assertEqual(canonical['checks'][0]['citations'],[self.ref])
        for prompt in (review_prompt(self.fixture.packet),question_generation_prompt(projected)):
            self.assertIn('figure_collection_count',prompt)
            self.assertIn('not global nondisclosure',prompt)

    def test_source_wrong_count_diagnostic_and_repair_remain_figure_specific(self):
        response=self.fixture.source_response()
        response['facts'][0]['citations']=[{**self.ref,'count':1}]
        with self.assertRaises(SourceCitationProtocolError) as failure:
            _validate_source_assessment(self.fixture.packet,response)
        repair=source_review_repair_input(self.fixture.packet,response,max_bytes=400000)
        self.assertIn('figure_collection_count',repair['instruction'])
        self.assertIn('citation_figure_not_exact',str(repair['host_protocol_diagnostics']))

    def test_question_wrong_count_fails_and_old_scalar_cannot_replace_it(self):
        projected=_question_projection(self.fixture.packet)
        answer=self.fixture.question_response(projected)
        for ref in ({**self.ref,'count':1},
                    dict(kind='figure_field',source_snapshot_id=self.ref['source_snapshot_id'],
                         figure_id=self.ref['figure_id'],field_path='transcription.printed_values',value='[]')):
            answer['checks'][0]['citations']=[ref]
            with self.assertRaises(ValueError):
                validate_question_review(projected,answer)


if __name__=='__main__':
    unittest.main()
