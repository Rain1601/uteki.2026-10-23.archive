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

    def scoped_grid(self):
        packet=deepcopy(self.packet)
        question='For divisions Beacon and Cinder, provide revenue and cash flow in FY2031 and FY2030.'
        packet['question']=question
        rows=[(entity,metric,year,f'{entity} {metric} in FY{year} was {amount}.')
            for entity in ('Beacon','Cinder') for metric in ('revenue','cash flow')
            for year,amount in (('2031','42'),('2030','40'))]
        text=' '.join(row[3] for row in rows)
        packet['source_documents'][0]['blocks'][0].update(text=text,text_hash=digest(text.encode()))
        projected=project_question_review(packet)
        value=self.response()
        value.update(projection_id=projected['projection_id'],checks=[],output_constraints=[],
                     uncovered_requests=[],question_coverage='complete')
        for entity,metric,year,quote in rows:
            value['checks'].append({'question_quote':question,'requested_subject':metric,
                'requested_dimension':'metric','requested_scope_quotes':[entity,'FY'+year],
                'source_subject':entity+' '+metric,'relation':'same','coverage':'complete',
                'support_basis':'direct','citations':[{'kind':'block_quote','source_snapshot_id':'annual',
                    'block_id':'definition','quote':quote}], 'gap':None,
                'rationale':'The requested division, metric and period are disclosed.'})
        return projected,value

    def test_shared_clause_supports_entity_period_metric_grid_without_joined_subject(self):
        projected,value=self.scoped_grid()
        before=deepcopy(value)
        normalized,eligible=validate_question_review(projected,value)
        self.assertTrue(eligible)
        self.assertEqual(len(normalized['checks']),8)
        self.assertEqual(value,before)
        self.assertIn('do not replace a requested metric with its period',QUESTION_REVIEW_PROMPT)
        for check in normalized['checks']:
            self.assertIn(check['requested_subject'],projected['question'])
            self.assertTrue(all(scope in projected['question'] for scope in check['requested_scope_quotes']))

    def test_scope_quotes_reject_unknown_joined_empty_and_repeated_qualifiers(self):
        for scopes,code in ((['Other','FY2031'],'scope_quotes_require_verbatim'),
                            (['Beacon FY2031'],'scope_quotes_require_verbatim'),
                            ([''],'scope_quotes_require_verbatim'),
                            (['Beacon','Beacon'],'scope_quotes_require_unique')):
            projected,value=self.scoped_grid()
            value['checks'][0]['requested_scope_quotes']=scopes
            with self.subTest(scopes=scopes),self.assertRaises(QuestionReviewProtocolError) as error:
                validate_question_review(projected,value)
            self.assertEqual(error.exception.diagnostic['code'],code)
            repair=question_review_repair_input(projected,value)
            self.assertIn(code,{d['code'] for d in repair['host_protocol_diagnostics']})
            self.assertEqual(repair['projection'],projected)
            self.assertEqual(repair['previous_assessment'],value)

    def test_scope_order_and_repetition_cannot_hide_duplicate_checks(self):
        for scopes in (['FY2031','Beacon'],['Beacon','FY2031','Beacon']):
            projected,value=self.scoped_grid()
            duplicate=deepcopy(value['checks'][0]);duplicate['requested_scope_quotes']=scopes
            value['checks'].append(duplicate)
            with self.subTest(scopes=scopes),self.assertRaises(QuestionReviewProtocolError):
                validate_question_review(projected,value)
            diagnostics=question_review_repair_input(projected,value)['host_protocol_diagnostics']
            self.assertIn('duplicate_check_requires_distinct_scope',{d['code'] for d in diagnostics})

    def test_cross_clause_entity_scope_survives_local_subject_quote_repair(self):
        projected,value=self.scoped_grid()
        # Entity names are outside the shared metric clause. A field-local
        # quote repair must still allow their exact full-question qualifiers.
        for check in value['checks']:
            check['question_quote']='provide revenue and cash flow in FY2031 and FY2030'
        self.assertTrue(validate_question_review(projected,value)[1])
        draft=deepcopy(value)
        for check in draft['checks']:
            entity,period=check['requested_scope_quotes']
            check['requested_subject']=entity+' '+period+' '+check['requested_subject']
            check['requested_scope_quotes']=[period]
        before=deepcopy(draft)
        repair=question_review_repair_input(projected,draft)
        self.assertEqual(repair['previous_assessment'],before)
        self.assertEqual(repair['projection'],projected)
        self.assertEqual(repair['schema_version'],'question-review-protocol-repair-v3')
        self.assertTrue(all(d['code']=='requested_subject_requires_verbatim'
                            for d in repair['host_protocol_diagnostics']))
        self.assertTrue(validate_question_review(projected,value)[1])
        # Keeping different source subjects, citations and rationales does not
        # recover requested identity after removing the entity qualifier.
        collapsed=deepcopy(value)
        for check in collapsed['checks']:
            check['requested_scope_quotes']=check['requested_scope_quotes'][1:]
        with self.assertRaises(QuestionReviewProtocolError) as error:
            validate_question_review(projected,collapsed)
        self.assertEqual(error.exception.diagnostic['code'],'duplicate_check_requires_distinct_scope')
        self.assertEqual(draft,before)

    def test_scopes_never_relax_source_quotes_or_record_fields(self):
        projected,value=self.scoped_grid()
        value['checks'][0]['citations'][0]['quote']='Beacon revenue ... 42.'
        with self.assertRaises(ValueError) as error:
            question_review_repair_input(projected,value)
        self.assertNotIsInstance(error.exception,QuestionReviewProtocolError)
        packet=self.record_packet();projected=project_question_review(packet)
        value=self.response();check=value['checks'][0]
        check.update(question_quote=packet['question'],requested_subject='revenue',requested_dimension='metric',
            requested_scope_quotes=['Beacon','FY2031'],citations=[{'kind':'record_field',
                'source_snapshot_id':'annual','record_id':'row-1','field_path':'period.start','value':'2030-01-01'}])
        value.update(projection_id=projected['projection_id'],output_constraints=[])
        with self.assertRaises(ValueError) as error:
            validate_question_review(projected,value)
        self.assertNotIsInstance(error.exception,QuestionReviewProtocolError)

    def test_old_response_keeps_optional_scope_absent_and_duplicate_is_repairable(self):
        value=self.response()
        normalized,_=validate_question_review(self.projected,value)
        self.assertNotIn('requested_scope_quotes',normalized['checks'][0])
        value['checks'].append(deepcopy(value['checks'][0]))
        with self.assertRaises(QuestionReviewProtocolError) as error:
            validate_question_review(self.projected,value)
        self.assertEqual(error.exception.diagnostic['code'],'duplicate_check_requires_distinct_scope')
        self.assertEqual(question_review_repair_input(self.projected,value)['previous_assessment'],value)

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

    def test_enumeration_repair_locates_rejected_subject_and_scope_without_replacement(self):
        packet=deepcopy(self.packet)
        packet['question']='Preserve units, timing and evidence labels.'
        projected=project_question_review(packet)
        value=self.response();check=value['checks'][0]
        check.update(question_quote=packet['question'],requested_subject='units and evidence labels',
            requested_dimension='other',requested_scope_quotes=['units and evidence labels'])
        value.update(projection_id=projected['projection_id'],output_constraints=[],
                     uncovered_requests=[],question_coverage='complete')
        before=deepcopy(value)
        with self.assertRaises(QuestionReviewProtocolError) as error:
            validate_question_review(projected,value)
        self.assertEqual(error.exception.diagnostic['field_pointer'],
                         '/previous_assessment/checks/0/requested_subject')
        repair=question_review_repair_input(projected,value)
        diagnostics=repair['host_protocol_diagnostics']
        self.assertEqual([d['field_pointer'] for d in diagnostics],[
            '/previous_assessment/checks/0/requested_subject',
            '/previous_assessment/checks/0/requested_scope_quotes/0'])
        self.assertEqual([d['constraint_pointer'] for d in diagnostics],[
            '/previous_assessment/checks/0/question_quote','/projection/question'])
        self.assertTrue(all(d['rejected_value']=='units and evidence labels' for d in diagnostics))
        self.assertTrue(all(set(d)=={'check_index','code','rule','field_pointer','rejected_value',
                                    'constraint_pointer'} for d in diagnostics))
        self.assertEqual(repair['previous_assessment'],before)
        self.assertEqual(repair['projection'],projected)
        self.assertEqual(repair['repair_attempt'],1)
        self.assertIn('separate checks for individual continuous entries',repair['instruction'])
        self.assertIn('not suggested answers',repair['instruction'])
        self.assertNotIn('replacement_value',str(repair))
        # Both representations are chosen by a reviewer, not generated by the host.
        for subjects in (['units, timing and evidence labels'],['units','evidence labels']):
            fixed=deepcopy(value);fixed['checks']=[]
            for subject in subjects:
                item=deepcopy(check);item.update(requested_subject=subject,requested_scope_quotes=[])
                fixed['checks'].append(item)
            self.assertTrue(validate_question_review(projected,fixed)[1])
        self.assertEqual(value,before)

    def test_exact_diagnostic_does_not_turn_invalid_evidence_into_a_repairable_quote(self):
        value=self.response();value['checks'][0]['requested_subject']='Beacon definition'
        value['checks'][0]['citations'][0]['quote']='Beacon ... compute platform.'
        with self.assertRaises(ValueError) as error:
            question_review_repair_input(self.projected,value)
        self.assertNotIsInstance(error.exception,QuestionReviewProtocolError)


if __name__=='__main__':unittest.main()
