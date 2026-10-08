"""Offline isolation and protocol boundaries, not a model semantic evaluation."""
from copy import deepcopy
import unittest

from uteki.agents.data_query.question_coverage_review import (
    QUESTION_REVIEW_PROMPT, project_question_review, validate_question_review, question_review_repair_input,
    QuestionReviewProtocolError,
)
from uteki.infrastructure.research_data.financial_records import digest


class QuestionCoverageReviewTests(unittest.TestCase):
    def setUp(self):
        self.text = 'Beacon is a compute platform. The wider Beacon and other services group also includes messaging.'
        self.packet = {'schema_version':'data-answer-review-input-v1', 'packet_id':'frozen-packet',
            'purpose':'analysis_evidence', 'source_delivery':'query_evidence_v1',
            'question':'Define Beacon and give its FY2031 disclosed revenue. Do not estimate missing revenue.',
            'scope':{'execution_schema_version':'research-execution-v1', 'snapshot_id':'dataset',
                'company_ids':['acme'], 'source_snapshot_ids':['annual'], 'source_policy_id':'local-frozen-v1',
                'knowledge_cutoff':'2032-05-01', 'include_candidates':True},
            'source_documents':[{'source_snapshot_id':'annual', 'index_id':'idx', 'source_sha256':'a'*64,
                'company_id':'acme', 'source_url':'https://example.org/annual',
                'source_period_end':'2031-12-31', 'available_at':'2032-02-01',
                'blocks':[{'block_id':'definition', 'type':'paragraph', 'text':self.text,
                    'text_hash':digest(self.text.encode()), 'table':None}],
                'semantic_completeness':'AUTHOR_LABEL', 'reading_groups':['AUTHOR_GROUP']}],
            'requirements':[{'description':'AUTHOR_PLAN'}], 'facts':[{'statement':'AUTHOR_FACT'}],
            'program_gaps':['AUTHOR_CHECK'], 'review_feedback':{'reason':'OLD_REVIEW'}}
        self.projected = project_question_review(self.packet, expected_scope=self.packet['scope'])

    def response(self):
        return {'packet_id':self.projected['packet_id'], 'projection_id':self.projected['projection_id'],
            'checks':[{'question_quote':'Define Beacon', 'requested_subject':'Beacon',
                'requested_dimension':'definition', 'source_subject':'Beacon', 'relation':'same',
                'coverage':'complete', 'support_basis':'direct', 'citations':[{'kind':'block_quote','source_snapshot_id':'annual','block_id':'definition',
                    'quote':'Beacon is a compute platform.'}], 'gap':None, 'rationale':'Platform definition provided.'}],
            'output_constraints':[{'question_quote':'Do not estimate missing revenue.',
                'interpretation':'A prohibition, not a request to prove that revenue does not exist.'}],
            'uncovered_requests':['FY2031 disclosed revenue is not in the selected material.'],
            'question_coverage':'incomplete', 'coverage_reason':'Definition supported; requested metric missing.'}

    def test_projection_retains_full_original_text_but_excludes_author_judgments(self):
        p=self.projected
        self.assertEqual(p['source_documents'][0]['blocks'][0]['text'],self.text)
        self.assertEqual(p['question'],self.packet['question'])
        self.assertEqual(p['packet_id'],self.packet['packet_id'])
        self.assertNotIn('AUTHOR_',str(p));self.assertNotIn('OLD_REVIEW',str(p))
        changed=deepcopy(self.packet);changed['requirements']=[{'description':'REPLACED'}]
        self.assertEqual(project_question_review(changed),p)
        p['source_documents'][0]['blocks'][0]['text']='changed'
        self.assertEqual(self.packet['source_documents'][0]['blocks'][0]['text'],self.text)

    def test_scope_cutoff_text_integrity_duplicates_and_capacity_are_enforced(self):
        mutations = [lambda p:p['source_documents'][0].update(company_id='other'),
            lambda p:p['source_documents'][0].update(source_snapshot_id='unknown'),
            lambda p:p['source_documents'][0].update(available_at='2033-01-01'),
            lambda p:p['source_documents'][0]['blocks'][0].update(text='changed'),
            lambda p:p['source_documents'].append(deepcopy(p['source_documents'][0])),
            lambda p:p['source_documents'][0]['blocks'].append(deepcopy(p['source_documents'][0]['blocks'][0]))]
        for change in mutations:
            p=deepcopy(self.packet);change(p)
            with self.subTest(change=change),self.assertRaises(ValueError):project_question_review(p)
        expected=deepcopy(self.packet['scope']);expected['company_ids']=['other']
        with self.assertRaises(ValueError):project_question_review(self.packet,expected_scope=expected)
        with self.assertRaises(ValueError):project_question_review(self.packet,max_bytes=20)

    def test_table_cells_and_metadata_survive_without_truncation(self):
        p=deepcopy(self.packet);b=p['source_documents'][0]['blocks'][0]
        b.update(type='table',table={'cells':[[0,0,'2031'],[1,0,'2030']], 'column_count':1,
            'row_count':2,'cell_fields':['row','column','text']})
        self.assertEqual(project_question_review(p)['source_documents'][0]['blocks'][0]['table'],b['table'])

    def test_precise_quotes_and_original_identity_cannot_be_forged(self):
        changes=[lambda v:v.update(packet_id='other'),lambda v:v.update(projection_id='other'),
            lambda v:v['checks'][0].update(question_quote='Define another product'),
            lambda v:v['checks'][0].update(requested_subject='Other'),
            lambda v:v['checks'][0]['citations'][0].update(source_snapshot_id='other'),
            lambda v:v['checks'][0]['citations'][0].update(block_id='other'),
            lambda v:v['checks'][0]['citations'][0].update(quote='Beacon is a messaging product.'),
            lambda v:v['output_constraints'][0].update(question_quote='Prove missing revenue.')]
        for change in changes:
            v=self.response();change(v)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_question_review(self.projected,v)
        p=deepcopy(self.projected);p['question']='changed'
        with self.assertRaises(ValueError):validate_question_review(p,self.response())

    def test_related_or_broader_evidence_is_not_automatically_complete(self):
        for relation in ('broader','narrower','related','unclear'):
            v=self.response();v['checks'][0]['relation']=relation
            with self.subTest(relation=relation),self.assertRaises(ValueError):validate_question_review(self.projected,v)
        v=self.response();v['checks'][0].update(relation='broader',coverage='partial',gap='Group membership is not the platform definition.')
        original=deepcopy(v);normalized,eligible=validate_question_review(self.projected,v)
        self.assertFalse(eligible);self.assertEqual(v,original);self.assertEqual(normalized['checks'][0]['relation'],'broader')

    def test_complete_requires_original_support_and_cannot_hide_gaps(self):
        for change in (lambda v:v['checks'][0].update(citations=[]),
                       lambda v:v['checks'][0].update(source_subject=None),
                       lambda v:v['checks'][0].update(gap='Still missing'),
                       lambda v:v.update(question_coverage='complete'),
                       lambda v:v['checks'].append(deepcopy(v['checks'][0]))):
            v=self.response();change(v)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_question_review(self.projected,v)
        v=self.response();v.update(checks=[],uncovered_requests=[],question_coverage='complete')
        with self.assertRaises(ValueError):validate_question_review(self.projected,v)
        self.assertFalse(validate_question_review(self.projected,self.response())[1])

    def test_complete_model_opinion_is_distinct_from_proving_semantic_truth(self):
        # A definition-only task can be complete. The host validates exact
        # provenance and consistency, not the truth of the model's relation label.
        p=deepcopy(self.packet);p['question']='Define Beacon.'
        projected=project_question_review(p);v=self.response()
        v.update(packet_id=projected['packet_id'],projection_id=projected['projection_id'],
                 output_constraints=[],uncovered_requests=[],question_coverage='complete')
        self.assertTrue(validate_question_review(projected,v)[1])

    def test_prompt_separates_numeric_tasks_and_prohibitions_from_definitions(self):
        self.assertIn('Do not add product definitions to a pure numeric question',QUESTION_REVIEW_PROMPT)
        self.assertIn('prohibitions, not',QUESTION_REVIEW_PROMPT)
        self.assertIn('explicitly asks WHETHER',QUESTION_REVIEW_PROMPT)
        self.assertIn('not proof of completeness',QUESTION_REVIEW_PROMPT)

    def test_distinct_period_clauses_can_check_same_subject_and_dimension(self):
        p=deepcopy(self.packet)
        p['question']='Provide Beacon revenue in FY2031 and Beacon revenue in FY2030.'
        text='Beacon revenue in FY2031 was 42; Beacon revenue in FY2030 was 40.'
        p['source_documents'][0]['blocks'][0].update(text=text,text_hash=digest(text.encode()))
        projected=project_question_review(p);v=self.response();v['checks']=[]
        for year,amount in [('2031','42'),('2030','40')]:
            v['checks'].append({'question_quote':'Beacon revenue in FY'+year,'requested_subject':'Beacon',
                'requested_dimension':'metric','source_subject':'Beacon','relation':'same','coverage':'complete',
                'support_basis':'direct', 'citations':[{'kind':'block_quote','source_snapshot_id':'annual','block_id':'definition',
                    'quote':'Beacon revenue in FY'+year+' was '+amount}], 'gap':None,'rationale':'Requested disclosed metric.'})
        v.update(packet_id=projected['packet_id'],projection_id=projected['projection_id'],
            output_constraints=[],uncovered_requests=[],question_coverage='complete')
        self.assertTrue(validate_question_review(projected,v)[1])

    def test_v1_projection_and_response_still_validate_without_new_fields(self):
        projected=project_question_review(self.packet,version='question-coverage-input-v1')
        self.assertNotIn('selected_records',projected)
        v=self.response();v['projection_id']=projected['projection_id']
        for check in v['checks']:
            check.pop('support_basis')
            for citation in check['citations']:citation.pop('kind')
        normalized,eligible=validate_question_review(projected,v)
        self.assertFalse(eligible)
        self.assertNotIn('support_basis',normalized['checks'][0])

    def test_qualified_metric_preserves_group_identity_without_blocking_disclosed_metric(self):
        p=deepcopy(self.packet);p['question']='Provide Beacon corresponding disclosed metrics. Do not estimate missing revenue.'
        projected=project_question_review(p);v=self.response();check=v['checks'][0]
        check.update(question_quote='Beacon corresponding disclosed metrics',requested_dimension='metric',
            source_subject='Beacon and other services',relation='broader',support_basis='qualified_disclosure',
            qualification='Only the wider group metric is supplied, not a standalone Beacon amount.',
            qualification_question_quote='corresponding disclosed metrics',
            qualification_citations=[{'kind':'block_quote','source_snapshot_id':'annual','block_id':'definition',
                'quote':'The wider Beacon and other services group also includes messaging.'}])
        v.update(projection_id=projected['projection_id'],uncovered_requests=[],question_coverage='complete')
        self.assertTrue(validate_question_review(projected,v)[1])
        for change in (lambda c:c.update(requested_dimension='definition'),lambda c:c.update(relation='same'),
                       lambda c:c.update(qualification_citations=[]),lambda c:c.update(qualification=None),
                       lambda c:c.update(qualification_question_quote='Give a standalone amount')):
            modified=deepcopy(v);change(modified['checks'][0])
            with self.subTest(change=change),self.assertRaises(ValueError):validate_question_review(projected,modified)

    def test_relationship_can_be_supported_by_premises_without_verbatim_conclusion(self):
        p=deepcopy(self.packet);p['question']='Explain the relationship between Beacon and the wider group.'
        projected=project_question_review(p);v=self.response();v['checks'][0].update(
            question_quote=p['question'],requested_subject='Beacon',requested_dimension='relationship',
            relation='related',support_basis='analysis_premises',rationale='The platform and wider group definitions supply the premises.')
        v.update(projection_id=projected['projection_id'],output_constraints=[],uncovered_requests=[],question_coverage='complete')
        self.assertTrue(validate_question_review(projected,v)[1])
        v['checks'][0]['requested_dimension']='definition'
        with self.assertRaises(ValueError):validate_question_review(projected,v)

    def record_packet(self):
        p=deepcopy(self.packet);text=self.text+' Revenue 42.'
        p['source_documents'][0]['blocks'][0].update(text=text,text_hash=digest(text.encode()))
        p['question']='Provide Beacon FY2031 revenue and fiscal period.'
        p['facts'].append({'kind':'record','fact_id':'author-fact','requirement_ids':['author-plan'],
            'value':{'schema_version':'research-query-v0.4','record_id':'row-1','record_type':'metric',
                'entity_id':'opaque-segment-id','metric_id':'revenue','period':{'kind':'year','start':'2031-01-01','end':'2031-12-31','basis':'source'},
                'period_resolution':'resolved','value_kind':'actual','value_decimal':'42','value_relation':'eq','unit':'USD',
                'accounting_basis':'reported_segment','dimensions':{'segment':'opaque'},'available_at':'2032-02-01',
                'source_snapshot_id':'annual','evidence_ids':['e-1'],'summary':'AUTHOR_SUMMARY','status':'candidate',
                'origin':{'adapter':'synthetic-inline','context_ref':'context-1','comment':'AUTHOR_NOTE'},
                'normalization_notes':['AUTHOR_NORMALIZATION']},
            'citations':[{'source_snapshot_id':'annual','block_id':'definition','quote':'42'}]})
        return p

    def test_mechanical_record_period_and_segment_identity_retained_without_author_summary(self):
        p=self.record_packet();projected=project_question_review(p)
        record=projected['selected_records'][0]
        self.assertEqual(record['entity_id'],'opaque-segment-id')
        self.assertEqual(record['period']['start'],'2031-01-01')
        self.assertNotIn('AUTHOR_',str(projected));self.assertNotIn('summary',record)
        v=self.response();v['checks'][0].update(question_quote='Beacon FY2031 revenue and fiscal period',
            requested_dimension='metric',citations=[{'kind':'record_field','source_snapshot_id':'annual',
                'record_id':'row-1','field_path':'period.start','value':'2031-01-01'}])
        v.update(projection_id=projected['projection_id'],output_constraints=[],uncovered_requests=[],question_coverage='complete')
        self.assertTrue(validate_question_review(projected,v)[1])
        for change in (lambda c:c.update(record_id='unknown'),lambda c:c.update(source_snapshot_id='other'),
                       lambda c:c.update(field_path='summary'),lambda c:c.update(value='2030-01-01')):
            bad=deepcopy(v);change(bad['checks'][0]['citations'][0])
            with self.subTest(change=change),self.assertRaises(ValueError):validate_question_review(projected,bad)

    def test_foreign_or_future_record_and_wrong_source_quote_rejected(self):
        for change in (lambda f:f['value'].update(source_snapshot_id='other'),
                       lambda f:f['value'].update(available_at='2033-01-01'),
                       lambda f:f['citations'][0].update(source_snapshot_id='other')):
            p=self.record_packet();change(p['facts'][-1])
            with self.subTest(change=change),self.assertRaises(ValueError):project_question_review(p)

    def test_protocol_repair_retains_raw_draft_and_adds_no_semantic_answer(self):
        v=self.response();v['checks'][0].update(relation='broader',support_basis='qualified_disclosure')
        before=deepcopy(v)
        with self.assertRaises(QuestionReviewProtocolError):validate_question_review(self.projected,v)
        repair=question_review_repair_input(self.projected,v)
        self.assertEqual(v,before)
        self.assertEqual(repair['previous_assessment'],before)
        self.assertEqual(repair['projection'],self.projected)
        self.assertEqual(repair['host_protocol_diagnostics'][0]['code'],'definition_requires_direct_same')
        self.assertNotIn('Beacon',str(repair['host_protocol_diagnostics']))
        self.assertEqual(repair['previous_assessment_sha256'],digest(before))
        self.assertEqual(repair['repair_attempt'],1)
        # Host still rejects the same answer: it neither flips coverage to
        # partial nor changes a wider subject into the requested one.
        with self.assertRaises(QuestionReviewProtocolError):validate_question_review(self.projected,v)
        with self.assertRaises(ValueError):question_review_repair_input(self.projected,v,max_bytes=10)
        with self.assertRaises(ValueError):question_review_repair_input(self.projected,self.response())

    def test_one_repair_collects_question_quotes_subjects_and_combinations(self):
        v=self.response()
        v['checks'][0].update(question_quote='Paraphrased question',requested_subject='Paraphrased subject',
            relation='broader',support_basis='qualified_disclosure',qualification_question_quote='Invented permission')
        v['output_constraints'][0]['question_quote']='Paraphrased constraint'
        before=deepcopy(v)
        with self.assertRaises(QuestionReviewProtocolError) as error:
            validate_question_review(self.projected,v)
        self.assertEqual(error.exception.diagnostic['code'],'question_quote_requires_verbatim')
        repair=question_review_repair_input(self.projected,v)
        diagnostics=repair['host_protocol_diagnostics']
        self.assertEqual({d['code'] for d in diagnostics},{'question_quote_requires_verbatim',
            'requested_subject_requires_verbatim','qualification_quote_requires_verbatim',
            'constraint_quote_requires_verbatim','definition_requires_direct_same','qualified_metric_requires_scope'})
        self.assertEqual(diagnostics[-1]['field_group'],'output_constraints')
        self.assertNotIn('Beacon',str(diagnostics))
        self.assertEqual(v,before)
        self.assertEqual(repair['previous_assessment'],before)
        self.assertEqual(repair['repair_attempt'],1)
        self.assertFalse(validate_question_review(self.projected,self.response())[1])

    def test_wrong_subject_is_repairable_but_wrong_evidence_still_is_not(self):
        v=self.response();v['checks'][0]['requested_subject']='Beacon definition'
        with self.assertRaises(QuestionReviewProtocolError) as error:
            validate_question_review(self.projected,v)
        self.assertEqual(error.exception.diagnostic['code'],'requested_subject_requires_verbatim')
        self.assertEqual(len(question_review_repair_input(self.projected,v)['host_protocol_diagnostics']),1)
        v['checks'][0]['citations'][0]['quote']='Invented original evidence'
        with self.assertRaises(ValueError) as error:
            question_review_repair_input(self.projected,v)
        self.assertNotIsInstance(error.exception,QuestionReviewProtocolError)


if __name__=='__main__':unittest.main()
