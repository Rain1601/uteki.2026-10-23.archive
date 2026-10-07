"""Object patch invariants over independent synthetic sources; no model calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch as mock_patch

from tests.unit.test_business_coverage_contract_v2 import attribute_sample
from uteki.agents.business_map import critic_revision as run, product_run as base
from uteki.agents.business_map.coverage_contract import canonical_hash, check_targets
from uteki.agents.business_map.product_contract import validate_draft


class CriticRevisionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve()
        self.packet,self.candidate,_,_=attribute_sample(self.root)
        self.bind_critic()

    def bind_critic(self):
        targets=check_targets(self.candidate)
        issue=dict(category='claim_support',target_keys=[targets[0]['check_key']],node_ids=['issuer'],
            excerpts=[dict(block_id=self.packet['blocks'][0]['id'],quote=self.packet['blocks'][0]['text'])],
            explanation='Synthetic uncertainty for protocol tests.')
        self.critic=dict(schema_version='business-semantic-critic-v1',candidate_sha256=canonical_hash(self.candidate),
            reviewed_check_keys=[t['check_key'] for t in targets],status='needs_revision',issues=[issue,deepcopy(issue)])

    def patch(self,operations):
        return dict(schema_version='business-critic-revision-patch-v1',source_packet_sha256=canonical_hash(self.packet),
            candidate_sha256=canonical_hash(self.candidate),critic_sha256=canonical_hash(self.critic),operations=operations)

    def operation(self,op,**kwargs):
        return dict(op=op,issue_indices=[0],explanation='Source-bound correction; synthetic protocol fixture.',**kwargs)

    def apply(self,value):
        return run.apply_patch(value,self.packet,self.candidate,self.critic)

    def test_summary_patch_preserves_all_objects_and_records_unaddressed_issue(self):
        value=self.patch([self.operation('replace_summary',value='Source-grounded fixture summary.')])
        originals=deepcopy((self.packet,self.candidate,self.critic,value))
        revised,receipt=self.apply(value)
        self.assertEqual(revised['businesses'],self.candidate['businesses'])
        self.assertEqual(revised['relationships'],self.candidate['relationships'])
        self.assertEqual((self.packet,self.candidate,self.critic,value),originals)
        self.assertEqual(receipt['unaddressed_issue_indices'],[1])
        self.assertEqual(receipt['issue_resolution'],'not_evaluated')
        self.assertTrue(receipt['requires_fresh_review']);self.assertFalse(receipt['independent_acceptance'])
        self.assertEqual(receipt['changes'][0]['before'],self.candidate['summary'])
        self.assertEqual(receipt['revised_candidate_sha256'],canonical_hash(revised))

    def test_node_replacement_retains_other_data_and_derives_only_redundant_indexes(self):
        node=deepcopy(self.candidate['businesses'][1])
        node['description']='Services with supported product detail.'
        node['evidence_block_ids']=['section']
        value=self.patch([self.operation('upsert_business',value=node)])
        revised,receipt=self.apply(value)
        self.assertEqual(revised['businesses'][0],self.candidate['businesses'][0])
        self.assertEqual(revised['businesses'][1]['products_services'],node['products_services'])
        self.assertEqual(revised['businesses'][1]['claim_evidence'],node['claim_evidence'])
        self.assertTrue(receipt['projection']['changes'])
        self.assertEqual(revised['unknowns'],self.candidate['unknowns'])
        self.assertEqual(revised['block_disposition'],self.candidate['block_disposition'])

    def test_all_hashes_issue_indices_duplicate_and_scope_writes_reject(self):
        base_value=self.patch([self.operation('replace_summary',value='Updated summary')])
        mutations=[lambda p:p.update(source_packet_sha256='0'*64),lambda p:p.update(candidate_sha256='0'*64),
            lambda p:p.update(critic_sha256='0'*64),lambda p:p.update(company_id='other'),
            lambda p:p['operations'][0].update(issue_indices=[]),lambda p:p['operations'][0].update(issue_indices=[2]),
            lambda p:p['operations'][0].update(issue_indices=[0,0]),lambda p:p['operations'][0].update(issue_indices=[True]),
            lambda p:p['operations'].append(deepcopy(p['operations'][0])),
            lambda p:p['operations'][0].update(op='replace_source'),lambda p:p['operations'][0].update(value=self.candidate['summary'])]
        for mutate in mutations:
            value=deepcopy(base_value);mutate(value)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.apply(value)
        self.critic['issues']=[];self.critic['status']='pass'
        with self.assertRaisesRegex(ValueError,'requires_issues'):self.apply(base_value)

    def test_invalid_quotes_cross_scope_and_untyped_fields_remain_errors(self):
        original=deepcopy(self.candidate)
        for mutate in [lambda n:n['claim_evidence'][0]['excerpts'][0].update(quote='fabricated'),
            lambda n:n['claim_evidence'][0]['excerpts'][0].update(block_id='foreign'),
            lambda n:n.update(company_id='foreign'),lambda n:n.update(kind='reportable_segment',role='market')]:
            node=deepcopy(self.candidate['businesses'][1]);mutate(node)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):self.apply(self.patch([self.operation('upsert_business',value=node)]))
            self.assertEqual(self.candidate,original)

    def test_relationship_identity_changes_require_explicit_removal_and_references_do_not_cascade(self):
        block=next(b for b in self.packet['blocks'] if b['id']=='section')
        relation=dict(source_id='services',target_id='issuer',kind='reported_under',description='Reported segment.',
            evidence_block_ids=['section'],basis='explicit',rationale='Synthetic fixture.',
            excerpts=[dict(block_id='section',quote=block['text'])])
        self.candidate['relationships']=[relation]
        self.candidate['unknowns']=[dict(id='u',question='Unknown terms?',reason_unanswered='Not disclosed.',related_business_ids=['services'])]
        self.candidate=validate_draft(self.candidate,self.packet,expected_version='business-draft-v2').model_dump();self.bind_critic()
        before=deepcopy(self.candidate)
        with self.assertRaises(ValueError):self.apply(self.patch([self.operation('remove_business',id='services')]))
        self.assertEqual(before,self.candidate)
        operations=[self.operation('remove_business',id='services'),self.operation('remove_relationship',
            key=dict(source_id='services',kind='reported_under',target_id='issuer')),self.operation('remove_unknown',id='u')]
        revised,receipt=self.apply(self.patch(operations))
        self.assertEqual(len(revised['businesses']),1);self.assertEqual(revised['relationships'],[])
        self.assertEqual(revised['unknowns'],[]);self.assertEqual(len(receipt['changes']),3)
        changed=deepcopy(relation);changed['kind']='supports'
        revised,_=self.apply(self.patch([self.operation('remove_relationship',key=dict(source_id='services',kind='reported_under',target_id='issuer')),
            self.operation('upsert_relationship',value=changed)]))
        self.assertEqual([r['kind'] for r in revised['relationships']],['supports'])

    def test_unknown_upsert_and_disposition_replacement_without_new_blocks(self):
        unknown=dict(id='new_unknown',question='Undisclosed term?',reason_unanswered='Source does not specify.',related_business_ids=['services'])
        disposition=deepcopy(self.candidate['block_disposition'][0]);disposition['reason']='Rechecked relevant source.'
        revised,_=self.apply(self.patch([self.operation('upsert_unknown',value=unknown),self.operation('replace_block_disposition',value=disposition)]))
        self.assertIn(unknown,revised['unknowns'])
        for op in [self.operation('remove_unknown',id='absent'),self.operation('replace_block_disposition',value=dict(disposition,block_id='absent')),
            self.operation('replace_block_disposition',value=dict(disposition,disposition='not_used'))]:
            with self.subTest(op=op),self.assertRaises(ValueError):self.apply(self.patch([op]))

    def test_another_source_and_projection_only_no_effect(self):
        self.packet,self.candidate,_,_=attribute_sample(self.root,'cobalt','2023-03-31')
        self.bind_critic()
        value=self.patch([self.operation('replace_summary',value='Another selected source summary.')])
        revised,receipt=self.apply(value)
        self.assertEqual(revised['company_id'],self.packet['company_id'])
        self.assertEqual(revised['period_end'],'2023-03-31')
        self.assertEqual(receipt['source_packet_sha256'],canonical_hash(self.packet))
        node=deepcopy(self.candidate['businesses'][1]);node['evidence_block_ids']=['section']
        with self.assertRaisesRegex(ValueError,'no_effect_after_projection'):
            self.apply(self.patch([self.operation('upsert_business',value=node)]))

    def test_request_has_only_source_candidate_critic_and_hashes(self):
        (self.root/'packet.json').write_text(json.dumps(self.packet));(self.root/'skill.md').write_text('Frozen generic extraction rules.')
        with mock_patch.dict(os.environ,{'AIHUBMIX_API_KEY':'mock-key'}):
            prepared=base.prepare(root=self.root,packet_path='packet.json',skill_path='skill.md',
                company_id=self.packet['company_id'],document_id=self.packet['document_id'],period_end=self.packet['period_end'],
                model='claude-sonnet-5-5',effort='high',max_tokens=12000,timeout_seconds=30,contract_version='business-draft-v2')
        kwargs,schema=run.request_for(prepared,candidate=self.candidate,critic=self.critic)
        payload=json.loads(kwargs['input'])
        self.assertEqual(set(payload),{'frozen_source_packet','candidate','critic','source_packet_sha256','candidate_sha256','critic_sha256'})
        self.assertEqual(payload['critic'],self.critic);self.assertEqual(schema,run.RevisionPatch.model_json_schema())
        self.assertEqual(kwargs['tools'],[])
        self.assertIn('Frozen generic extraction rules.',kwargs['system_instructions'])
        foreign=deepcopy(self.candidate);foreign['company_id']='foreign'
        with self.assertRaises(ValueError):run.request_for(prepared,candidate=foreign,critic=self.critic)


if __name__=='__main__':unittest.main()
