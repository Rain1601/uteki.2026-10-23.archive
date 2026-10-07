"""Offline patch boundaries; no provider request and no edits to frozen runs."""
from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('repair_once_under_test',HERE/'repair_once.py')
repair=importlib.util.module_from_spec(spec);spec.loader.exec_module(repair)
from tests.unit.test_business_only_run import fixture
from uteki.agents.business_map.product_contract import validate_draft
from uteki.agents.runtime.run_budget import BudgetExceeded


class PatchBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.packet,self.draft=fixture(Path(self.temp.name))
        self.draft['businesses'][2].update(kind='offering_group',role='application_platform')
        self.draft['relationships'] += [dict(self.draft['relationships'][0],source_id='services',target_id='issuer',kind='reported_under'),
            dict(self.draft['relationships'][0],target_id='issuer',kind='supports')]
        config={'issues':[dict(id='synthetic',problem='Repair only selected fields.',business_indices=[2],
            relationship_indices=[1,2],source_block_ids=['product'])]}
        self.view,self.policy,self.source=repair.make_view(self.draft,self.packet,config)

    def apply(self,*ops):return repair.apply_patch(self.draft,{'operations':list(ops)},self.policy,self.source)

    def test_explicit_patch_preserves_parent_and_validates_complete_candidate(self):
        before=deepcopy(self.draft)
        result,diff=self.apply(dict(op='replace',path='/businesses/2/kind',value='business'))
        self.assertEqual(self.draft,before)
        self.assertEqual(validate_draft(result,self.packet).businesses[2].kind,'business')
        self.assertEqual(diff[0]['before'],'offering_group')
        self.assertEqual(diff[0]['after'],'business')

    def test_identity_nodes_scope_unselected_relationship_and_unseen_claim_are_forbidden(self):
        ops=[dict(op='remove',path='/businesses/2'),dict(op='replace',path='/businesses/2/id',value='other'),
            dict(op='replace',path='/businesses/2/name',value='Other'),dict(op='replace',path='/company_id',value='other'),
            dict(op='replace',path='/period_end',value='2033-01-01'),dict(op='replace',path='/source_sha256',value='0'*64),
            dict(op='remove',path='/relationships/0'),dict(op='replace',path='/businesses/2/claim_evidence/0',value={}),
            dict(op='replace',path='/businesses/2/claim_evidence',value=[]),
            dict(op='replace',path='/businesses/2/evidence_block_ids',value=['product']),
            dict(op='add',path='/businesses/2/evidence_block_ids/-',value='issuer')]
        for op in ops:
            with self.subTest(op=op),self.assertRaises(ValueError):self.apply(op)

    def test_array_removal_cannot_shift_allowlist_onto_unselected_edge_or_claim(self):
        with self.assertRaisesRegex(ValueError,'relationship_not_selected'):
            self.apply(dict(op='remove',path='/relationships/1'),dict(op='remove',path='/relationships/0'))
        with self.assertRaisesRegex(ValueError,'unseen_claim'):
            self.apply(dict(op='remove',path='/businesses/2/claim_evidence/1'),
                       dict(op='replace',path='/businesses/2/claim_evidence/0',value={}))

    def test_unknown_append_allowed_but_new_confirmed_parent_and_hidden_source_rejected(self):
        edge=dict(self.draft['relationships'][0],basis='unknown',rationale='Unresolved.',excerpts=[],evidence_block_ids=[])
        result,_=self.apply(dict(op='add',path='/relationships/-',value=edge))
        self.assertEqual(result['relationships'][-1]['basis'],'unknown')
        for op in [dict(op='add',path='/relationships/-',value=self.draft['relationships'][0]),
            dict(op='replace',path='/relationships/1',value=dict(self.draft['relationships'][1],target_id='beacon')),
            dict(op='replace',path='/businesses/2/claim_evidence/1/excerpts/0/block_id',value='issuer')]:
            with self.subTest(op=op),self.assertRaises(ValueError):self.apply(op)

    def test_projection_preserves_all_facts_and_full_description_claim_values(self):
        selected=self.view['businesses'][0]
        self.assertEqual(selected['value'],{k:v for k,v in self.draft['businesses'][2].items() if k!='claim_evidence'})
        self.assertEqual(selected['full_description_claims']['1'],self.draft['businesses'][2]['claim_evidence'][1])
        self.assertEqual(self.view['source_blocks'],[['product',self.packet['blocks'][3]['text']]])


class FrozenPreflight(unittest.IsolatedAsyncioTestCase):
    def test_6000_ready_8192_blocked_and_unknown_cost_never_ignored(self):
        ready=repair.prepare(HERE/'repair-input.json',max_tokens=6000)
        blocked=repair.prepare(HERE/'repair-input.json',max_tokens=8192)
        self.assertEqual(ready['manifest']['remaining_budget_usd'],'0.135348')
        self.assertEqual(ready['manifest']['budget_gate'],'ready')
        self.assertEqual(blocked['manifest']['budget_gate'],'blocked_insufficient_reservation')
        original_parse=repair.parse_json_object
        def unknown(text):
            value=original_parse(text)
            if 'budget' in value:value['budget']['unknown_requests']=1
            return value
        with patch.object(repair,'parse_json_object',side_effect=unknown),self.assertRaisesRegex(ValueError,'prior_cost'):
            repair.prepare(HERE/'repair-input.json',max_tokens=6000)

    async def test_budget_refusal_precedes_dispatch_and_output_creation(self):
        existing=(HERE/'repair-run-01/result.json').read_bytes()
        prepared=repair.prepare(HERE/'repair-input.json',max_tokens=8192)
        prepared['native'].get_response=AsyncMock()
        with self.assertRaises(BudgetExceeded):await repair.execute(prepared,observation_root=None)
        prepared['native'].get_response.assert_not_called()
        self.assertEqual((HERE/'repair-run-01/result.json').read_bytes(),existing)

    def test_preflight_cannot_change_full_unseen_parent_fact_or_remaining_budget(self):
        for target in ('draft','budget','policy'):
            prepared=repair.prepare(HERE/'repair-input.json',max_tokens=6000)
            if target=='draft':prepared['draft']['businesses'][0]['description']='Unauthorised rewrite.'
            elif target=='budget':prepared['manifest']['remaining_budget_usd']='1.0'
            else:prepared['policy']['business_indices'].append(0)
            with self.subTest(target=target),self.assertRaisesRegex(ValueError,'prepared_repair_changed'):
                repair.verify_prepared(prepared)


class BetweenToolsRecovery(unittest.IsolatedAsyncioTestCase):
    def prepare(self):
        return repair.prepare(HERE/'repair-input.json',max_tokens=6000,recovery_profile=repair.RECOVERY_PROFILE)

    def test_only_thinking_changes_and_all_three_costs_are_counted(self):
        prepared=self.prepare();manifest=prepared['manifest']
        old=repair.read(HERE/'repair-run-01/request.json')
        current=repair.parse_json_object(prepared['request'].decode())
        self.assertEqual(current.pop('thinking'),{'type':'between_tools'})
        self.assertEqual(old.pop('thinking'),{'type':'adaptive'})
        self.assertEqual(current,old)
        self.assertEqual([c['run'] for c in manifest['prior_costs']],['run-01','run-02','repair-run-01'])
        self.assertEqual(Decimal(manifest['cumulative_prior_spent_usd']),Decimal('0.537312'))
        self.assertEqual(Decimal(manifest['remaining_budget_usd']),Decimal('0.162688'))
        self.assertEqual(manifest['budget_gate'],'ready')
        self.assertIn('pending',manifest['budget_authorization'])
        snapshot=prepared['native'].request_configuration(**prepared['kwargs'])
        self.assertEqual(snapshot['fields']['thinking']['value'],{'type':'between_tools'})
        repair.verify_prepared(prepared)

    async def test_missing_or_wrong_budget_confirmation_never_dispatches(self):
        prepared=self.prepare();prepared['native'].get_response=AsyncMock()
        for value in (None,'0.60','0.700',0.7):
            with self.subTest(value=value),self.assertRaisesRegex(BudgetExceeded,'confirmed_total_budget'):
                await repair.execute(prepared,observation_root=None,confirmed_total_budget_usd=value)
        prepared['native'].get_response.assert_not_called()
        self.assertFalse((HERE/'repair-run-02').exists())

    def test_unknown_third_cost_and_other_model_or_output_budget_are_rejected(self):
        original_parse=repair.parse_json_object
        def unknown(text):
            value=original_parse(text)
            if value.get('execution_mode')=='model_patch_repair' and 'budget' in value:
                value['budget']['unknown_requests']=1
            return value
        with patch.object(repair,'parse_json_object',side_effect=unknown),self.assertRaisesRegex(ValueError,'prior_cost'):
            self.prepare()
        for model,tokens in [('claude-opus-5-5',6000),('claude-sonnet-5-5',8192)]:
            with self.subTest(model=model,tokens=tokens),self.assertRaisesRegex(ValueError,'same_sonnet'):
                repair.prepare(HERE/'repair-input.json',max_tokens=tokens,model=model,recovery_profile=repair.RECOVERY_PROFILE)



class ContractV2Recovery(BetweenToolsRecovery):
    def prepare(self):
        return repair.prepare(HERE/'repair-input.json',max_tokens=6000,
            recovery_profile=repair.RECOVERY_PROFILE,
            target_contract_version=repair.BUSINESS_DRAFT_V2_VERSION)

    def test_only_thinking_changes_and_all_three_costs_are_counted(self):
        prepared=self.prepare()
        repair.verify_prepared(prepared)
        current=repair.parse_json_object(prepared['request'].decode())
        old=repair.read(HERE/'repair-run-01/request.json')
        self.assertEqual(current['messages'],old['messages'])
        self.assertTrue(current['system'].startswith(old['system']))
        self.assertIn('Target node kind/role schema variants',current['system'])
        self.assertEqual(prepared['manifest']['output_contract_version'],'business-draft-v2')
        self.assertEqual(prepared['manifest']['planned_output_run'],'repair-run-02-contract-v2')
        self.assertEqual(prepared['schema'],repair.draft_model('business-draft-v2').model_json_schema())
        self.assertEqual(prepared['draft']['schema_version'],'business-draft-v1')
        self.assertEqual(Decimal(prepared['manifest']['cumulative_prior_spent_usd']),Decimal('0.537312'))
        self.assertIn('pending',prepared['manifest']['budget_authorization'])

if __name__=='__main__':unittest.main()
