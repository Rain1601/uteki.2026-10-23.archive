"""Index derivation only; semantic fields and original answers are immutable."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_business_coverage_contract_v2 import attribute_sample
from uteki.agents.business_map.evidence_projection import (
    project_business_evidence_indexes, project_relationship_evidence,
)
from uteki.agents.business_map.coverage_contract import canonical_hash
from uteki.agents.business_map.product_contract import validate_draft


class BusinessEvidenceProjectionTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.packet,self.draft,_,_=attribute_sample(self.root)
        self.draft['relationships']=[dict(source_id='services',target_id='issuer',kind='part_of',
            description='Services belongs to the issuer.',basis='derived',rationale='Synthetic relation for contract checks.',
            evidence_block_ids=['section','issuer'],excerpts=[dict(block_id=b['id'],quote=b['text'])
                for b in self.packet['blocks'] if b['id'] in ('section','issuer')])]
        validate_draft(self.draft,self.packet,expected_version='business-draft-v2')

    def project(self,value=None,packet=None):
        return project_business_evidence_indexes(value if value is not None else self.draft,
            packet if packet is not None else self.packet,expected_version='business-draft-v2')

    def test_only_missing_indexes_change_node_attributes_quotes_and_order_unchanged(self):
        original=deepcopy(self.draft)
        original['businesses'][1]['evidence_block_ids']=['section','competition']
        original['relationships'][0]['evidence_block_ids']=['section']
        untouched=deepcopy(original)
        projected,report=self.project(original)
        expected=deepcopy(original)
        expected['businesses'][1]['evidence_block_ids']+=['product']
        expected['relationships'][0]['evidence_block_ids']+=['issuer']
        self.assertEqual(projected,expected);self.assertEqual(original,untouched)
        self.assertEqual([c['path'] for c in report['changes']],
            ['/businesses/1/evidence_block_ids','/relationships/0/evidence_block_ids'])
        self.assertEqual(report['original_sha256'],canonical_hash(original))
        self.assertEqual(report['projected_sha256'],canonical_hash(projected))
        self.assertEqual(report['source_packet_sha256'],canonical_hash(self.packet))
        self.assertEqual(projected['businesses'][1]['products_services'],['Beacon support software'])
        self.assertEqual(self.project(projected)[1]['changes'],[])

    def test_empty_explicit_index_can_derive_from_existing_quotes(self):
        draft=deepcopy(self.draft);draft['businesses'][1]['evidence_block_ids']=[]
        projected,report=self.project(draft)
        self.assertEqual(projected['businesses'][1]['evidence_block_ids'],['section','product','competition'])
        self.assertEqual(report['changes'][0]['before'],[])

    def test_node_context_indexes_preserved_but_relationship_extras_rejected(self):
        draft=deepcopy(self.draft)
        draft['businesses'][1]['evidence_block_ids']=['period','section']
        projected,_=self.project(draft)
        self.assertEqual(projected['businesses'][1]['evidence_block_ids'],['period','section','product','competition'])
        draft=deepcopy(self.draft)
        draft['relationships'][0]['evidence_block_ids'].append('period')
        with self.assertRaisesRegex(ValueError,'cannot_remove_uncited'):
            self.project(draft)
        draft=deepcopy(self.draft)
        draft['businesses'][0]['evidence_block_ids'].append('foreign-source')
        with self.assertRaises(ValueError):self.project(draft)

    def test_cross_source_and_wrong_quote_cannot_be_hidden_by_projection(self):
        for mutation in ('outside','wrong-quote','other-company'):
            draft=deepcopy(self.draft)
            draft['businesses'][1]['evidence_block_ids']=['section']
            if mutation=='outside':
                draft['businesses'][1]['claim_evidence'][-1]['excerpts'][0]['block_id']='foreign-source'
            elif mutation=='wrong-quote':
                draft['businesses'][1]['claim_evidence'][-1]['excerpts'][0]['quote']='invented material'
            else:draft['company_id']='another-company'
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.project(draft)

    def test_other_schema_duplicate_and_monetization_errors_remain_errors(self):
        def bad_money(d):
            n=d['businesses'][1]
            n['monetization']=[dict(description='Synthetic statement.',basis='explicit',evidence_block_ids=['section'])]
            n['claim_evidence'].append(dict(field='monetization',item_index=0,excerpts=[dict(block_id='product',quote=self.packet['blocks'][3]['text'])]))
        for mutation in (lambda d:d.update(unexpected='field'),
                         lambda d:d['businesses'][1].update(kind='invented-kind'),
                         lambda d:d['businesses'][1]['evidence_block_ids'].append('section'),
                         lambda d:d['businesses'][1]['customers'].append('Uncited customer'),bad_money):
            draft=deepcopy(self.draft);mutation(draft)
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.project(draft)

    def test_old_relationship_projection_still_does_not_repair_node_indexes(self):
        draft=deepcopy(self.draft);draft['businesses'][1]['evidence_block_ids']=['section']
        with self.assertRaisesRegex(ValueError,'business_claim_not_in_node_evidence'):
            project_relationship_evidence(draft,self.packet,expected_version='business-draft-v2')
