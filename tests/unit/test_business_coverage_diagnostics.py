"""Aggregate diagnostics preserve bad audits; do not promote them to acceptance."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tests.unit.test_business_coverage_contract_v2 import attribute_sample
from uteki.agents.business_map import coverage_diagnostics as diag
from uteki.agents.business_map import coverage_contract_v2 as contract
from uteki.agents.business_map.coverage_contract import canonical_hash


class CoverageDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.packet,self.draft,self.inventory,self.audit=attribute_sample(self.root)

    def diagnose(self,audit=None,packet=None,inventory=None,draft=None):
        return diag.diagnose_audit(audit if audit is not None else self.audit,
            packet if packet is not None else self.packet,inventory if inventory is not None else self.inventory,
            draft if draft is not None else self.draft)

    def two_failures(self):
        audit=deepcopy(self.audit)
        for m in audit['mappings']:
            if m['mention_id']=='m3':
                ref=m['attribute_refs'][0];ref['alignment']='same_source_span'
                ref['excerpts']=[e for e in ref['excerpts'] if e['block_id']=='competition']
            if m['mention_id']=='m4':m['attribute_refs'][0]['item_index']=99
        return audit

    def test_all_local_failures_collected_raw_unchanged_and_no_acceptance(self):
        audit=self.two_failures();before=deepcopy((audit,self.packet,self.inventory,self.draft))
        result=self.diagnose(audit)
        self.assertEqual(result['status'],'INVALID_WITH_FINDINGS')
        self.assertFalse(result['audit_contract_valid']);self.assertFalse(result['independent_acceptance'])
        self.assertEqual(result['semantic_acceptance'],'not_evaluated')
        self.assertEqual(result['computed_status'],'needs_revision')
        self.assertIsNone(result['validated_contract_result'])
        self.assertEqual(len(result['findings']),2)
        self.assertEqual({f['code'] for f in result['findings']},
                         {'attribute_excerpt_does_not_locate_mention','attribute_index_outside_populated_field'})
        self.assertEqual(result['raw_audit'],audit)
        self.assertEqual(result['raw_audit_canonical_sha256'],canonical_hash(audit))
        self.assertEqual(result['model_checks']['checks'],audit['checks'])
        self.assertEqual(result['counts']['mappings'],len(audit['mappings']))
        self.assertEqual([m['mention_id'] for m in result['mapping_states'] if m['effective_state']=='unresolved'],['m3','m4'])
        self.assertEqual(result['findings'][0]['observation']['exact_surface_location'],'other_block_only')
        self.assertFalse(result['findings'][0]['observation']['automatic_alignment_rewrite'])
        self.assertEqual(result['findings'][0]['observation']['identity_and_scope_equivalence'],'not_inferred')
        self.assertEqual(result['findings'][1]['observation']['exact_surface_location'],'unbound_reference')
        self.assertEqual((audit,self.packet,self.inventory,self.draft),before)

    def test_valid_audit_delegates_existing_validator_without_independent_pass(self):
        result=self.diagnose()
        self.assertEqual(result['status'],'contract_valid')
        self.assertEqual(result['validated_contract_result'],contract.validate_audit(self.audit,self.packet,self.inventory,self.draft))
        self.assertFalse(result['independent_acceptance'])
        self.assertEqual(result['semantic_acceptance'],'not_evaluated')
        negative=deepcopy(self.audit);negative['checks'][0]['verdict']='partial'
        self.assertEqual(self.diagnose(negative)['computed_status'],'needs_revision')

    def test_global_bindings_accounting_schema_and_scope_still_hard_fail(self):
        changes=[lambda a:a.update(candidate_sha256='0'*64),lambda a:a.update(inventory_sha256='0'*64),
                 lambda a:a['mappings'].pop(),lambda a:a['mappings'].append(deepcopy(a['mappings'][0])),
                 lambda a:a['checks'].pop(),lambda a:a['checks'].append(deepcopy(a['checks'][0])),
                 lambda a:a.update(injected_answer='not allowed')]
        for change in changes:
            value=self.two_failures();change(value)
            with self.subTest(change=change),self.assertRaises(ValueError):self.diagnose(value)
        for key in ('company_id','document_id','period_end','source_sha256'):
            value=deepcopy(self.draft);value[key]='another-scope'
            with self.subTest(key=key),self.assertRaises(ValueError):self.diagnose(draft=value)

    def test_no_alias_or_partial_surface_match_is_inferred(self):
        inventory=deepcopy(self.inventory)
        mention=next(m for m in inventory['mentions'] if m['id']=='m3')
        mention['surface']='The Services segment includes Beacon support software for engineers.'
        draft=deepcopy(self.draft)
        target=draft['businesses'][1]['claim_evidence'][-1]
        target['excerpts']=[dict(block_id='product',quote='Beacon support software'),
                            dict(block_id='competition',quote='Beacon support software')]
        audit=deepcopy(self.audit)
        audit['inventory_sha256']=canonical_hash(inventory);audit['candidate_sha256']=canonical_hash(draft)
        for m in audit['mappings']:
            if m['attribute_refs']:m['attribute_refs'][0]['excerpts']=deepcopy(target['excerpts'])
        result=self.diagnose(audit,inventory=inventory,draft=draft)
        finding=next(f for f in result['findings'] if f['mention_id']=='m3')
        self.assertEqual(finding['observation']['exact_surface_location'],'no_full_surface_match')
        self.assertEqual(finding['observation']['alias_equivalence'],'not_inferred')
        self.assertEqual(result['raw_audit']['mappings'],audit['mappings'])
