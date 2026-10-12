"""Pinned selected-figure delivery and independent-review boundaries; offline fixtures only."""
import asyncio
from copy import deepcopy
import hashlib
import unittest

from agents import AgentOutputSchema

from tests.unit import test_figure_materials as figure_fixtures
from uteki.agents.data_query.answer_handoff import (
    _selected_figure_materials, _validate_source_assessment, _question_projection,
    compose_audited_assessment, source_assessment_schema, review_prompt, QUESTION_REVIEW_POLICY, prepare_review_packet, source_review_repair_input, _source_revision, review_data_answer, load_reviewed_data, validate_source_revision_feedback, validate_assessment, validate_saved_assessment,
)
from uteki.agents.data_query.question_coverage_review import (
    validate_figure_citation, validate_question_review, question_review_repair_input,
    project_question_review,
)
from uteki.agents.data_query.question_review_generation import (
    question_generation_schema, question_generation_prompt, project_question_generation,
    QuestionCoverageGeneration, PROJECTION_FIGURES,
)
from uteki.domain.research_data.execution_scope import ExecutionScope


class ReopenedFigurePort:
    """Exercise the production Reader, while isolating irrelevant query DB setup."""
    def __init__(self, fixture, scope, header):
        self.fixture, self.scope, self.header = fixture, scope, header
        self.figure_bundle_ref = None

    def bind_figures(self, ref):
        from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader
        if hashlib.sha256((self.fixture.bundle / 'manifest.json').read_bytes()).hexdigest() != ref['manifest_sha256']:
            raise ValueError('changed bundle manifest')
        self.reader = FigureMaterialReader(self.fixture.bundle, self.fixture.dataset)
        self.figure_bundle_ref = {**ref, 'path': str(self.fixture.bundle.resolve())}
        return self

    def scoped(self, scope):
        if scope != self.scope:
            raise ValueError('wrong scope')
        return self

    def read_figure(self, request):
        figure = self.reader.read(request['figure_id'])
        if figure['source_snapshot_id'] != request['source_snapshot_id']:
            raise ValueError('wrong source')
        return {**self.header, 'scope': self.scope.model_dump(mode='json'), 'status':'read',
            'material_type':'figure-evidence-v1', 'figure':figure, 'figure_bundle_ref':self.figure_bundle_ref}


class FigureHandoffTests(unittest.TestCase):
    def setUp(self):
        self.fixture = figure_fixtures.FigureMaterialsTests()
        self.fixture.setUp()
        self.fixture.run_materials()
        from uteki.infrastructure.document_sources.figure_reader import FigureMaterialReader
        reader = FigureMaterialReader(self.fixture.bundle, self.fixture.dataset)
        self.figure = reader.read(reader.list()[0]['figure_id'])
        sid, company = self.figure['source_snapshot_id'], self.figure['company_id']
        self.scope = ExecutionScope.model_validate(dict(execution_schema_version='research-execution-v1',
            snapshot_id='synthetic', company_ids=[company], source_snapshot_ids=[sid],
            source_policy_id='local-frozen-v1', knowledge_cutoff='2032-05-01', include_candidates=True))
        self.header = dict(source_snapshot_id=sid, company_id=company, index_id='idx',
            source_sha256=self.figure['source_sha256'], source_url=self.figure['document_source_url'],
            source_period_end='2031-12-31', available_at='2032-02-01')
        self.ref = dict(path=str(self.fixture.bundle.resolve()),
            manifest_sha256=hashlib.sha256((self.fixture.bundle/'manifest.json').read_bytes()).hexdigest())
        self.port = ReopenedFigurePort(self.fixture, self.scope, self.header)
        self.port.bind_figures(self.ref)
        self.choice = dict(evidence_id='selected', figure_id=self.figure['figure_id'],
            source_snapshot_id=sid, figure_bundle_ref=self.ref)
        value = self.port.read_figure(dict(source_snapshot_id=sid, figure_id=self.figure['figure_id']))
        contract = dict(version='selected-originals-v5', figure_bundle_ref=self.ref, selected_figures=[self.choice])
        self.result = dict(role='planner', purpose='analysis_evidence', figure_bundle_ref=self.ref,
            request={'figure_bundle_ref':self.ref}, figure_delivery_selection={'r':[self.choice]},
            source_selection_contract=contract, coverage=[dict(requirement_id='r', kind='source_evidence',
                source_id=sid, evidence_ids=['selected'], selected_figures=[self.choice])])
        self.bundle = dict(items=[dict(evidence_id='selected', kind='figure', value=value,
            scope=self.scope.model_dump(mode='json')), dict(evidence_id='exploration', kind='figure',
                value={'not':'a selected figure'}, scope=self.scope.model_dump(mode='json'))],
            delivered_figures=['selected','exploration'], selected_figures=[self.choice], source_selection_contract=contract)
        documents=[]
        figures = _selected_figure_materials(self.port, self.scope, self.result, self.bundle, documents)
        self.packet = dict(schema_version='data-answer-review-input-v1', packet_id='packet',
            purpose='analysis_evidence', source_delivery='query_evidence_v1', delivery_schema_version='selected-originals-v5',
            question='Name the chart series.', scope=self.scope.model_dump(mode='json'), source_documents=documents,
            source_figures=figures, figure_bundle_ref=self.ref, facts=[{'fact_id':'f','kind':'figure_material','value':figures[0]}],
            requirements=[dict(requirement_id='r',source_id=sid)], query_status='evidence_ready', query_gaps=[], program_gaps=[],
            question_review_policy=QUESTION_REVIEW_POLICY, source_review_policy='delivered-sources-v2',
            scope_source_availability=[dict(source_snapshot_id=sid,company_id=company,source_period_end='2031-12-31',
                available_at='2032-02-01',status='available_candidate')],source_check_ids=[sid],max_packet_bytes=400000)
        self.citation = dict(kind='figure_text',source_snapshot_id=sid,figure_id=self.figure['figure_id'],text_id='legend',quote='Series A')

    def tearDown(self):
        self.fixture.tearDown()

    def source_response(self):
        c = self.citation
        return dict(packet_id='packet', facts=[dict(fact_id='f',verdict='supported',rationale='Transcribed series.',citations=[c],relevance='necessary')],
            requirements=[dict(requirement_id='r',verdict='complete',rationale='Named series.',citations=[c])],
            source_checks=[dict(source_snapshot_id=c['source_snapshot_id'],verdict='text_sufficient',rationale='Selected chart labels.',citations=[c])],
            figure_checks=[dict(source_snapshot_id=c['source_snapshot_id'],figure_id=c['figure_id'],authenticity='source_bound',
                support='supported',relevance='necessary',rationale='Bound transcription supports labels.',citations=[c])],
            question_coverage='complete',coverage_reason='Series supplied.',missing_information=[],limitations=['Independent visual acceptance pending.'],body_checks=[])

    def question_response(self, projected):
        return dict(packet_id=projected['packet_id'],projection_id=projected['projection_id'],
            checks=[dict(question_quote='Name the chart series',requested_subject='chart series',requested_dimension='other',
                source_subject='chart series',relation='same',coverage='complete',support_basis='direct',citations=[self.citation],gap=None,rationale='Exact legend.')],
            output_constraints=[],uncovered_requests=[],question_coverage='complete',coverage_reason='Requested legend present.')

    def test_only_final_read_selection_enters_projection_with_distinct_hashes_and_pending_state(self):
        p = _question_projection(self.packet)
        self.assertEqual(len(p['source_figures']),1)
        self.assertNotIn('exploration',str(p))
        self.assertNotIn('requirement_ids',str(p)); self.assertNotIn('evidence_id',str(p))
        f=p['source_figures'][0]
        self.assertNotIn('original_image_path',f)
        self.assertEqual(f['independent_acceptance'],'pending')
        self.assertEqual(f['figure_bundle_manifest_sha256'],self.ref['manifest_sha256'])
        self.assertNotEqual(f['transcription_sha256'],f['image_sha256'])
        self.assertTrue(validate_question_review(p,self.question_response(p))[1])
        weak=deepcopy(self.packet);weak['source_figures'][0]['coordinate_status']='unverified_model_coordinates'
        with self.assertRaises(ValueError):_question_projection(weak)

    def test_v5_direct_or_saved_packet_cannot_downgrade_either_review_policy(self):
        mutations=[lambda p:p.pop('question_review_policy'),lambda p:p.update(question_review_policy=None),
            lambda p:p.pop('source_review_policy'),lambda p:p.update(source_review_policy=None),
            lambda p:p.update(source_review_policy='delivered-sources-v1')]
        for mutate in mutations:
            packet=deepcopy(self.packet);mutate(packet)
            for validate in (lambda:_validate_source_assessment(packet,self.source_response()),
                             lambda:validate_assessment(packet,self.source_response()),
                             lambda:validate_saved_assessment(self.fixture.fixture.root/'absent',packet)):
                with self.subTest(mutate=mutate),self.assertRaisesRegex(ValueError,'requires delivered-sources-v2'):
                    validate()

    def test_figure_only_delivery_still_requires_real_source_index_identity(self):
        original=self.port.header
        self.port.header={k:v for k,v in original.items() if k != 'index_id'}
        bundle=deepcopy(self.bundle)
        bundle['items'][0]['value'].pop('index_id')
        with self.assertRaisesRegex(ValueError,'required dataset/index metadata'):
            _selected_figure_materials(self.port,self.scope,self.result,bundle,[])
        for version in ('question-coverage-input-v1','question-coverage-input-v2','question-coverage-input-v3'):
            packet=deepcopy(self.packet);packet['source_documents'][0].pop('index_id')
            with self.subTest(version=version),self.assertRaises((ValueError,KeyError)):
                project_question_review(packet,version=version)

    def test_read_role_source_scope_manifest_and_transcription_cannot_be_forged(self):
        cases=[lambda r,b:r.update(role='researcher'),
            lambda r,b:b.update(delivered_figures=[]),
            lambda r,b:r['coverage'][0].update(kind='definition'),
            lambda r,b:b['items'][0]['value']['figure']['transcription']['texts'][0].update(text='Invented'),
            lambda r,b:b['items'][0].update(scope={}),
            lambda r,b:r['request']['figure_bundle_ref'].update(manifest_sha256='b'*64),
            lambda r,b:r['coverage'][0].update(source_id='another-source')]
        for mutate in cases:
            result,bundle=deepcopy(self.result),deepcopy(self.bundle);mutate(result,bundle)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):
                _selected_figure_materials(self.port,self.scope,result,bundle,[])
        manifest=self.fixture.bundle/'manifest.json';manifest.write_text(manifest.read_text()+' ')
        with self.assertRaises(ValueError):_selected_figure_materials(self.port,self.scope,self.result,self.bundle,[])

    def test_precise_figure_quotes_paths_and_values_exclude_estimates_and_cross_identity(self):
        figure=self.packet['source_figures']
        validate_figure_citation(figure,self.citation)
        valid=dict(kind='figure_field',source_snapshot_id=self.citation['source_snapshot_id'],figure_id=self.citation['figure_id'],
            field_path='transcription.series.0.color',value='blue')
        validate_figure_citation(figure,valid)
        for change in [dict(field_path='transcription.texts.0.box.x0',value='100'),
                       dict(field_path='transcription.printed_values.0.text_id',value='tick'),
                       dict(field_path='transcription.series.0.color',value='red'),dict(figure_id='unselected')]:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_figure_citation(figure,{**valid,**change})
        for change in [dict(text_id='tick',quote='Series A'),dict(quote='Series A and B'),dict(source_snapshot_id='other')]:
            with self.subTest(change=change),self.assertRaises(ValueError):validate_figure_citation(figure,{**self.citation,**change})

    def test_dual_review_intersection_and_per_figure_focus_gate(self):
        projected=_question_projection(self.packet);source=self.source_response();question=self.question_response(projected)
        _,ok=compose_audited_assessment(self.packet,source,question,projected);self.assertTrue(ok)
        for field,value in [('relevance','redundant'),('support','insufficient_evidence'),('authenticity','insufficient_evidence')]:
            response=deepcopy(source);response['figure_checks'][0][field]=value
            self.assertFalse(_validate_source_assessment(self.packet,response)[1])
        response=deepcopy(source);response['figure_checks']=[]
        with self.assertRaises(ValueError):_validate_source_assessment(self.packet,response)
        missing=deepcopy(question);missing['checks'][0].update(coverage='partial',gap='Needed period is missing.')
        missing.update(question_coverage='incomplete',uncovered_requests=['Missing period'])
        self.assertFalse(compose_audited_assessment(self.packet,source,missing,projected)[1])

    def test_only_figure_negative_verdict_can_supply_revision_but_never_approval(self):
        for field,value in [('authenticity','insufficient_evidence'),('support','insufficient_evidence'),('relevance','redundant')]:
            response=self.source_response();response['figure_checks'][0][field]=value
            source,eligible=_validate_source_assessment(self.packet,response)
            self.assertFalse(eligible)
            feedback=_source_revision(source,eligible,{'code':'question_quote_requires_verbatim'})
            self.assertEqual(feedback['source_assessment'],source)
            self.assertFalse(feedback['analysis_eligible'])
        source,eligible=_validate_source_assessment(self.packet,self.source_response())
        with self.assertRaises(ValueError):_source_revision(source,eligible,{'code':'question_quote_requires_verbatim'})

    def test_source_figure_check_bad_citation_gets_bounded_neutral_feedback(self):
        response=self.source_response()
        response['figure_checks'][0]['citations'][0]=dict(self.citation,quote='Imagined series')
        repair=source_review_repair_input(self.packet,response,max_bytes=400000)
        self.assertEqual(repair['host_protocol_diagnostics'],[dict(
            field_pointer='/figure_checks/0/citations/0',code='citation_figure_not_exact')])
        self.assertNotIn('replacement_quote',repair)
        self.assertEqual(repair['packet'],self.packet)

    def test_real_port_runtime_seal_and_prepare_packet_roundtrip(self):
        from tests.unit import test_query_figures as port_fixtures
        from tests.unit.test_autonomous_data_agent import ScriptedPlanner
        from uteki.agents.data_query.autonomous import AutonomousDataAgent
        fixture=port_fixtures.QueryFiguresTests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        port=fixture.first_only();source=fixture.sources[0]['source_snapshot_id']
        figure=port.list_figures()['figures'][0]
        plan={'action':'plan','reason':'Read explicitly requested chart.', 'requirements':[
            dict(requirement_id='chart',kind='source_evidence',source_id=source,description='Original chart labels.') ]}
        read={'action':'read_figure','requirement_ids':['chart'],'figure_read':
            {'source_snapshot_id':source,'figure_id':figure['figure_id']}}
        def select(packet):
            return {'action':'select_figures','requirement_ids':['chart'],'figure_delivery':
                {'evidence_ids':packet['observation']['evidence_ids']},'reason':'Explicit final figure.'}
        actions=[plan,read,select,{'action':'finish'}]
        run=fixture.fixture.fixture.root/'main-agent-run'
        result=asyncio.run(AutonomousDataAgent(port,ScriptedPlanner(actions),purpose='analysis_evidence',
            limits={'max_steps':4,'max_packet_bytes':128000,'observation_bytes':32000,'page_items':30}).run(
            {'question':'Name the chart series.','scope':port.scope.model_dump(mode='json'),
             'figure_bundle_ref':fixture.ref},output=run))
        self.assertEqual(result['status'],'evidence_ready',result['trace'])
        for policies in (dict(question_review_policy=None),dict(question_review_policy=QUESTION_REVIEW_POLICY,source_review_policy=None),
                         dict(question_review_policy=QUESTION_REVIEW_POLICY,source_review_policy='delivered-sources-v1')):
            with self.subTest(policies=policies),self.assertRaisesRegex(ValueError,'requires delivered-sources-v2'):
                prepare_review_packet(run,fixture.dataset,expected_scope=port.scope,max_packet_bytes=128000,
                    source_delivery='query_evidence_v1',**policies)
        packet=prepare_review_packet(run,fixture.dataset,expected_scope=port.scope,max_packet_bytes=128000,
            source_delivery='query_evidence_v1',question_review_policy=QUESTION_REVIEW_POLICY)
        self.assertEqual(packet['program_gaps'],[])
        self.assertEqual(packet['source_documents'][0]['blocks'],[])
        self.assertEqual(packet['facts'][0]['kind'],'figure_material')
        self.assertEqual(packet['source_figures'][0]['figure_id'],figure['figure_id'])
        self.assertEqual(_question_projection(packet)['source_figures'][0]['independent_acceptance'],'pending')
        from tests.unit.test_answer_handoff import ScriptedRole
        actual=packet['source_figures'][0]
        citation=dict(self.citation,source_snapshot_id=actual['source_snapshot_id'],figure_id=actual['figure_id'])
        def assess(p, negative=False):
            response=self.source_response();response['packet_id']=p['packet_id']
            response['facts'][0].update(fact_id=p['facts'][0]['fact_id'],citations=[citation])
            response['requirements'][0].update(requirement_id='chart',citations=[citation])
            response['source_checks'][0].update(source_snapshot_id=actual['source_snapshot_id'],citations=[citation])
            response['figure_checks'][0].update(source_snapshot_id=actual['source_snapshot_id'],figure_id=actual['figure_id'],
                citations=[citation],relevance='redundant' if negative else 'necessary')
            return response
        def question_assess(p, broken=False):
            p=p.get('projection',p)
            response=self.question_response(p);response['checks'][0]['citations']=[citation]
            if broken:response['checks'][0]['question_quote']='Name chart series'
            return response
        review=run.parent/'dual-review'
        reviewed=asyncio.run(review_data_answer(packet,review,
            reviewer_factory=lambda _:ScriptedRole(assess),
            question_reviewer_factory=lambda _:ScriptedRole(question_assess)))
        self.assertTrue(reviewed['analysis_eligible'],reviewed['failures'])
        handoff=load_reviewed_data(review,expected_scope=port.scope,
            expected_review_manifest_sha256=reviewed['review_ref']['manifest_sha256'],allow_fixture=True)
        self.assertEqual(handoff['source_figures'],packet['source_figures'])
        self.assertEqual(handoff['figure_bundle_ref'],fixture.ref)
        failed=run.parent/'negative-figure-broken-question'
        source_role=ScriptedRole(lambda p:assess(p,negative=True))
        question_role=ScriptedRole(lambda p:question_assess(p,broken=True))
        rejected=asyncio.run(review_data_answer(packet,failed,
            reviewer_factory=lambda _:source_role,question_reviewer_factory=lambda _:question_role))
        self.assertFalse(rejected['analysis_eligible'])
        self.assertEqual(len(question_role.packets),2)
        feedback=validate_source_revision_feedback(failed,packet)
        self.assertEqual(feedback,rejected['revision_feedback'])
        self.assertEqual(feedback['source_assessment']['figure_checks'][0]['relevance'],'redundant')
        with self.assertRaises(ValueError):load_reviewed_data(failed,expected_scope=port.scope,
            expected_review_manifest_sha256=rejected['review_ref']['manifest_sha256'],allow_fixture=True)
        unselected=fixture.fixture.fixture.root/'unselected-run'
        unselected_result=asyncio.run(AutonomousDataAgent(port,ScriptedPlanner([plan,read,{'action':'finish'}]),
            purpose='analysis_evidence',limits={'max_steps':3,'max_packet_bytes':128000,'observation_bytes':32000,
                'page_items':30}).run({'question':'Name the chart series.','scope':port.scope.model_dump(mode='json'),
                'figure_bundle_ref':fixture.ref},output=unselected))
        self.assertNotEqual(unselected_result['status'],'evidence_ready')
        unselected_packet=prepare_review_packet(unselected,fixture.dataset,expected_scope=port.scope,max_packet_bytes=128000,
            source_delivery='query_evidence_v1',question_review_policy=QUESTION_REVIEW_POLICY)
        self.assertEqual(unselected_packet['source_figures'],[])
        self.assertIn('delivery_selection_missing:chart',unselected_packet['program_gaps'])
        self.assertIn('no_reviewable_facts',unselected_packet['program_gaps'])

    def test_versioned_generation_is_cached_and_mechanical_repair_accepts_typed_citations(self):
        p=_question_projection(self.packet);model=question_generation_schema(p)
        self.assertIs(model,question_generation_schema(p))
        self.assertIs(question_generation_schema({}),QuestionCoverageGeneration)
        self.assertIn(PROJECTION_FIGURES,question_generation_prompt(p))
        AgentOutputSchema(model,strict_json_schema=False).json_schema()
        AgentOutputSchema(source_assessment_schema(self.packet),strict_json_schema=False).json_schema()
        response=self.question_response(p);check=response['checks'][0]
        flat={k:v for k,v in check.items() if k not in ('question_quote','requested_subject','requested_dimension')}
        nested={**response,'checks':[dict(request={k:check[k] for k in ('question_quote','requested_subject','requested_dimension')}
            | {'scope':dict(kind='self_contained',reason='The subject is the requested label.')},judgment=flat)]}
        canonical=project_question_generation(nested,p)
        self.assertTrue(validate_question_review(p,canonical)[1])
        response['checks'][0]['question_quote']='Name chart series'
        repair=question_review_repair_input(p,response)
        self.assertEqual(repair['projection'],p)
        self.assertEqual(repair['previous_assessment']['checks'][0]['citations'],[self.citation])
        self.assertIn('pending',review_prompt(self.packet))

if __name__=='__main__':unittest.main()
