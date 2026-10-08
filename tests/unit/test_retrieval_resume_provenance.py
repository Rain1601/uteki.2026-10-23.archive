"""Resume and feedback must bind actual frozen execution, not asserted labels."""
import asyncio
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, _verify_review_feedback
from uteki.agents.data_query.answer_handoff import prepare_review_packet, validate_assessment
from uteki.agents.data_query.artifacts import write_new
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest
from uteki.agents.runtime.run_budget import RunBudget
from tests.unit import test_retrieval_cycle as fixtures
from tests.unit.test_autonomous_data_agent import ScriptedPlanner
from tests.unit.test_autonomous_source_evidence import source_plan, context_read
from tests.unit.test_analysis_evidence_runtime import choose
from tests.unit.test_task_completion import pin_dataset


class RetrievalResumeProvenanceTests(unittest.TestCase):
    def setUp(self):
        fixtures.RetrievalCycleTests.setUp(self)
        self.config['request']['limits']={'max_steps':4,'max_packet_bytes':64000}
        self.coordinator_run=self.root/'prior-coordinator'
        result=asyncio.run(CompanyDataCoordinator(self.root/'workspace').query(self.config['request'],
            output=self.coordinator_run,
            planner=ScriptedPlanner([source_plan(),context_read(),choose('b1'),{'action':'finish'}])))
        self.assertEqual(result['status'],'evidence_ready')
        # Explicit fixture role config snapshots stand in for live coordinator
        # snapshots; no model or credential loader is called by these tests.
        write_new(self.coordinator_run/'model-config.input.json',self.config['planner'])
        write_new(self.coordinator_run/'worker-model-config.input.json',self.config['worker'])
        pin_dataset(self.coordinator_run)
        self.config['initial_query_ref']=cycle._reference(self.coordinator_run)
        self.request=CompanyQueryInput.model_validate(self.config['request'])
        self.query=self.coordinator_run/'query'

    def increased_budget(self):
        for role in ('planner', 'worker', 'reviewer'):
            self.config[role].update(budget_usd='10', budget_policy='enforced', max_requests_total=100)
        for role, name in [('planner','model-config.input.json'), ('worker','worker-model-config.input.json')]:
            (self.coordinator_run/name).write_text(json.dumps(self.config[role]))
        pin_dataset(self.coordinator_run)
        self.config['initial_query_ref'] = cycle._reference(self.coordinator_run)
        budget = RunBudget(self.config['planner']['budget_ledger'], '10')
        token = budget.reserve('1')
        budget.settle(token, None)
        for old, new in [('10', '15'), ('15', '20')]:
            budget.increase_limit(new, expected_current=old, authorization={
                'authorized_by':'user', 'authorization_id':'increase-'+new,
                'confirmation':'Explicitly authorized cumulative extension.', 'scope':'same test task',
                'old_limit_usd':old, 'new_limit_usd':new})
        for role in ('planner', 'worker', 'reviewer'):
            self.config[role]['budget_usd'] = '20'
        return budget

    def test_resume_accepts_only_recorded_budget_increase_and_preserves_unknown_cost(self):
        budget = self.increased_budget()
        before = Path(budget.path).read_bytes()
        initial = cycle.prepare_initial_query(self.config, self.request, self.output)
        change = initial['budget_changes']['planner']
        self.assertEqual((change['old_limit_usd'], change['new_limit_usd']), ('10', '20'))
        self.assertEqual(len(change['authorization_records']), 2)
        self.assertEqual(Path(budget.path).read_bytes(), before)
        self.assertEqual(budget.summary()['held_usd'], '1')
        self.assertEqual(budget.summary()['unknown_requests'], 1)
        async def review(packet,output,**kwargs):
            output.mkdir();write_new(output/'input.json',packet);write_new(output/'result.json',{'status':'reviewed'});cycle._seal(output)
            return {'status':'reviewed','analysis_eligible':True,'review_ref':cycle._reference(output)}
        with patch.object(cycle.CompanyDataCoordinator,'query') as paid,patch.object(cycle,'review_data_answer',side_effect=review):
            result=asyncio.run(cycle.run_retrieval_cycle(self.config,self.output))
        paid.assert_not_called()
        self.assertEqual(result['attempts'][0]['resume_budget_changes']['planner'], change)

    def test_budget_increase_does_not_unlock_scope_model_ledger_policy_or_decrease(self):
        self.increased_budget()
        changes = [lambda c:c['request']['scope'].update(knowledge_cutoff='2030-12-31'),
            lambda c:c['planner'].update(model='deepseek-v4-pro'),
            lambda c:c['planner'].update(budget_ledger=str(self.root/'other.sqlite')),
            lambda c:c['planner'].update(budget_policy='record_only'),
            lambda c:c['planner'].update(budget_usd='5'),
            lambda c:c['planner'].update(budget_usd='15'),
            lambda c:c['planner'].update(max_requests_total=101),
            lambda c:c['planner'].update(allow_unknown_reservations=True)]
        for change in changes:
            config=deepcopy(self.config);change(config)
            request=CompanyQueryInput.model_validate(config['request'])
            with self.subTest(config=config),self.assertRaises(ValueError):
                cycle.prepare_initial_query(config,request,self.output)

    def test_resume_rejects_missing_forged_or_incomplete_budget_authorizations(self):
        budget = self.increased_budget()
        with closing(sqlite3.connect(budget.path)) as db, db:
            # Simulate corrupt/restored data, not a supported authorization API.
            db.execute('DROP TRIGGER limit_auth_no_update')
            db.execute('DROP TRIGGER limit_auth_no_delete')
            original = db.execute("SELECT record FROM limit_authorizations WHERE id='increase-15'").fetchone()[0]
            altered=json.loads(original);altered['authorization']['confirmation']='changed'
            db.execute("UPDATE limit_authorizations SET record=? WHERE id='increase-15'",(json.dumps(altered),))
        with self.assertRaises(ValueError):cycle.prepare_initial_query(self.config,self.request,self.output)
        with closing(sqlite3.connect(budget.path)) as db, db:
            db.execute("DELETE FROM limit_authorizations WHERE id='increase-15'")
        with self.assertRaises(ValueError):cycle.prepare_initial_query(self.config,self.request,self.output)
        with closing(sqlite3.connect(budget.path)) as db, db:
            db.execute('DROP TABLE limit_authorizations')
        with self.assertRaises(ValueError):cycle.prepare_initial_query(self.config,self.request,self.output)

    def feedback(self):
        packet=prepare_review_packet(self.query,self.request.dataset,expected_scope=self.request.scope,
            max_packet_bytes=1000000,source_delivery='query_evidence_v1')
        assessment={'packet_id':packet['packet_id'],
            'facts':[{'fact_id':f['fact_id'],'verdict':'supported','relevance':'necessary','rationale':'Supports the task.',
                'citations':[{k:f['citations'][0][k] for k in ('source_snapshot_id','block_id','quote')}]} for f in packet['facts']],
            'requirements':[{'requirement_id':r['requirement_id'],'verdict':'needs_revision','rationale':'More context needed.'} for r in packet['requirements']],
            'source_checks':[{'source_snapshot_id':s,'verdict':'requires_more_source_content','rationale':'Needs context.'} for s in packet['scope']['source_snapshot_ids']],
            'body_checks':[{'source_snapshot_id':d['source_snapshot_id'],'block_id':b['block_id'],
                'relevance':'necessary','rationale':'Relevant original evidence.'}
                for d in packet['source_documents'] for b in d['blocks']],
            'question_coverage':'incomplete','coverage_reason':'Needs context.','missing_information':['One more relevant passage.'],'limitations':[]}
        assessment,_=validate_assessment(packet,assessment)
        review=self.root/'prior-review';review.mkdir()
        write_new(review/'input.json',packet)
        write_new(review/'result.json',{'status':'needs_revision','input_sha256':digest(packet),
            'packet_id':packet['packet_id'],'assessment':assessment,'failures':[]})
        cycle._seal(review)
        return {'prior_query_ref':cycle._reference(self.query),'prior_review_ref':cycle._reference(review),'assessment':assessment}

    def test_valid_feedback_is_reconstructed_from_actual_query_and_dataset(self):
        feedback=self.feedback()
        _verify_review_feedback(feedback,self.request,self.request.scope,Path(self.request.dataset))

    def test_sealed_review_cannot_relabel_other_company_period_or_purpose_query(self):
        feedback=self.feedback()
        original=json.loads((self.query/'result.json').read_text())
        review=Path(feedback['prior_review_ref']['path'])
        original_input=json.loads((review/'input.json').read_text())
        original_review=json.loads((review/'result.json').read_text())
        changes=[('company',lambda q:q['request']['scope'].update(company_ids=['other'])),
                 ('period_source',lambda q:q['request']['scope'].update(source_snapshot_ids=['acme-2030-annual'])),
                 ('cutoff',lambda q:q['request']['scope'].update(knowledge_cutoff='2030-12-31')),
                 ('question',lambda q:q['request'].update(question='Revenue in 2030.')),
                 ('purpose',lambda q:q.update(purpose='question_answer'))]
        for name,change in changes:
            with self.subTest(name=name):
                query=deepcopy(original);change(query)
                (self.query/'result.json').write_text(json.dumps(query));pin_dataset(self.query)
                altered=deepcopy(original_input);altered['query_ref']=cycle._reference(self.query)
                result=deepcopy(original_review);result['input_sha256']=digest(altered)
                (review/'input.json').write_text(json.dumps(altered));(review/'result.json').write_text(json.dumps(result));pin_dataset(review)
                supplied={**feedback,'prior_query_ref':cycle._reference(self.query),'prior_review_ref':cycle._reference(review)}
                with self.assertRaisesRegex(ValueError,'prior query does not match'):
                    _verify_review_feedback(supplied,self.request,self.request.scope,Path(self.request.dataset))

    def test_dataset_and_rebuilt_packet_cannot_be_replaced_by_review_self_description(self):
        feedback=self.feedback();review=Path(feedback['prior_review_ref']['path'])
        packet=json.loads((review/'input.json').read_text());result=json.loads((review/'result.json').read_text())
        for name in ('dataset','question_coverage'):
            altered=deepcopy(packet)
            if name=='dataset':altered['dataset_ref']['manifest_sha256']='0'*64
            else:altered['query_status']='partial'
            changed=deepcopy(result);changed['input_sha256']=digest(altered)
            (review/'input.json').write_text(json.dumps(altered));(review/'result.json').write_text(json.dumps(changed));pin_dataset(review)
            supplied={**feedback,'prior_review_ref':cycle._reference(review)}
            with self.subTest(name=name),self.assertRaises(ValueError):
                _verify_review_feedback(supplied,self.request,self.request.scope,Path(self.request.dataset))

    def test_resume_skips_paid_query_keeps_history_and_marks_reuse(self):
        before={str(p.relative_to(self.coordinator_run)):p.read_bytes() for p in self.coordinator_run.rglob('*') if p.is_file()}
        async def review(packet,output,**kwargs):
            output.mkdir();write_new(output/'input.json',packet);write_new(output/'result.json',{'status':'reviewed'});cycle._seal(output)
            return {'status':'reviewed','analysis_eligible':True,'review_ref':cycle._reference(output)}
        with patch.object(cycle.CompanyDataCoordinator,'query') as paid,patch.object(cycle,'review_data_answer',side_effect=review):
            result=asyncio.run(cycle.run_retrieval_cycle(self.config,self.output))
        paid.assert_not_called()
        self.assertEqual(result['status'],'reviewed_data_ready')
        self.assertEqual(result['attempts'][0]['execution'],'reused_frozen')
        self.assertEqual(result['final_query_ref'],cycle._reference(self.query))
        self.assertEqual({str(p.relative_to(self.coordinator_run)):p.read_bytes() for p in self.coordinator_run.rglob('*') if p.is_file()},before)
        self.assertFalse((self.output/'attempt-01/data-query').exists())

    def test_incomplete_resumed_review_starts_fresh_query_with_pinned_feedback(self):
        saved=self.feedback()
        assessment=saved['assessment']
        original_query=CompanyDataCoordinator.query
        calls=[]
        async def new_query(request,*,output,**kwargs):
            calls.append(deepcopy(request))
            return await original_query(CompanyDataCoordinator(self.root/'workspace'),request,output=output,
                planner=ScriptedPlanner([source_plan(),context_read(),choose('b1'),{'action':'finish'}]))
        reviews=[]
        async def review(packet,output,**kwargs):
            reviews.append(output)
            output.mkdir()
            status='needs_revision' if len(reviews)==1 else 'reviewed'
            current=deepcopy(assessment);current['packet_id']=packet['packet_id']
            value={'status':status,'assessment':current,'analysis_eligible':status=='reviewed',
                'input_sha256':digest(packet),'packet_id':packet['packet_id'],'failures':[]}
            write_new(output/'input.json',packet);write_new(output/'result.json',value);cycle._seal(output)
            return {**value,'review_ref':cycle._reference(output)}
        with patch.object(cycle.CompanyDataCoordinator,'query',side_effect=new_query),patch.object(cycle,'review_data_answer',side_effect=review):
            result=asyncio.run(cycle.run_retrieval_cycle(self.config,self.output))
        self.assertEqual(result['status'],'reviewed_data_ready',result)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0]['question'],self.config['request']['question'])
        self.assertEqual(calls[0]['scope'],self.request.scope.model_dump(mode='json'))
        self.assertEqual(calls[0]['review_feedback']['prior_query_ref'],cycle._reference(self.query))
        self.assertEqual([a['execution'] for a in result['attempts']],['reused_frozen','new'])

    def test_resume_rejects_child_directory_changed_request_role_and_unpinned_manifest(self):
        cases=[]
        child=deepcopy(self.config);child['initial_query_ref']=cycle._reference(self.query);cases.append(child)
        question=deepcopy(self.config);question['request']['question']='Revenue in 2030.';cases.append(question)
        role=deepcopy(self.config);role['planner']['max_tokens']=2048;cases.append(role)
        pin=deepcopy(self.config);pin['initial_query_ref']['manifest_sha256']='0'*64;cases.append(pin)
        company=deepcopy(self.config);company['request']['scope'].update(company_ids=['other'],source_snapshot_ids=['other-annual']);cases.append(company)
        for config in cases:
            with self.subTest(config=config),self.assertRaises(ValueError):cycle.validate(config,self.output)
        self.assertFalse(self.output.exists())


if __name__=='__main__':unittest.main()
