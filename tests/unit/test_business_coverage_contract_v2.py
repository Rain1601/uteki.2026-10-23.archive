"""Independent synthetic companies: attribute coverage is not semantic proof."""
import copy
from pathlib import Path
import tempfile
import unittest

from uteki.agents.business_map import coverage_contract as v1
from uteki.agents.business_map import coverage_contract_v2 as v2
from uteki.agents.business_map.product_contract import validate_draft
from tests.unit.test_business_coverage_contract import sample


def attribute_sample(root, company='quartz', period='2020-09-30'):
    packet, draft, inventory, _ = sample(root, company, period)
    draft['schema_version'] = 'business-draft-v2'
    draft['businesses'] = draft['businesses'][:2]
    draft['relationships'] = []
    node = draft['businesses'][1]
    node['products_services'] = ['Beacon support software']
    node['evidence_block_ids'] += ['product', 'competition']
    refs = [dict(block_id=b['id'], quote=b['text']) for b in packet['blocks']
            if b['id'] in {'product', 'competition'}]
    node['claim_evidence'].append(dict(field='products_services', item_index=0, excerpts=refs))
    draft = validate_draft(draft, packet).model_dump()
    mappings = []
    for mention in inventory['mentions']:
        key = mention['id']
        disposition = 'node' if key in {'m1', 'm2'} else 'context' if key == 'm5' else 'attribute'
        mappings.append(dict(mention_id=key, disposition=disposition,
            node_ids=[{'m1': 'issuer', 'm2': 'services'}[key]] if disposition == 'node' else [],
            attribute_refs=[dict(node_id='services', field='products_services', item_index=0,
                                 alignment='same_source_span',
                                 excerpts=copy.deepcopy(refs))] if disposition == 'attribute' else [],
            identity_requirement='independent_node' if disposition == 'node' else
                'context' if disposition == 'context' else 'attribute_sufficient',
            rationale='Synthetic source-based identity assessment.'))
    audit = dict(schema_version='business-coverage-audit-v2',
        candidate_sha256=v1.canonical_hash(draft), inventory_sha256=v1.canonical_hash(inventory),
        mappings=mappings, checks=[dict(check_key=t['check_key'], verdict='supported',
            rationale='Scripted review; not an independent semantic acceptance.') for t in v1.check_targets(draft)])
    return packet, draft, inventory, audit


class CoverageV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet, self.draft, self.inventory, self.audit = attribute_sample(self.root)

    def evaluate(self, audit=None, packet=None, inventory=None, draft=None):
        return v2.validate_audit(audit if audit is not None else self.audit,
            packet if packet is not None else self.packet,
            inventory if inventory is not None else self.inventory,
            draft if draft is not None else self.draft)

    def rebound(self, draft, inventory=None):
        audit = copy.deepcopy(self.audit)
        audit['candidate_sha256'] = v1.canonical_hash(validate_draft(draft, self.packet).model_dump())
        audit['checks'] = [dict(check_key=t['check_key'], verdict='supported', rationale='Scripted review.')
                           for t in v1.check_targets(draft)]
        if inventory is not None:
            audit['inventory_sha256'] = v1.canonical_hash(inventory)
        return audit

    def test_two_issuers_periods_can_cover_product_without_promoting_it_to_node(self):
        for company, period in [('quartz', '2020-09-30'), ('cobalt', '2023-03-31')]:
            inputs = attribute_sample(self.root, company, period)
            packet, draft, inventory, audit = inputs
            before = copy.deepcopy(inputs)
            result = v2.validate_audit(audit, packet, inventory, draft)
            self.assertEqual(result['computed_status'], 'pass')
            self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
            self.assertEqual(len(draft['businesses']), 2)
            self.assertEqual(before, inputs)

    def test_missing_hosts_fields_indices_values_or_references_cannot_count(self):
        for mutation in [lambda r:r.update(node_id='foreign'), lambda r:r.update(field='description'),
                         lambda r:r.update(item_index=4), lambda r:r.update(item_index=-1),
                         lambda r:r.update(item_index=True), lambda r:r.pop('item_index'),
                         lambda r:r.pop('alignment'), lambda r:r.update(alignment='automatic'),
                         lambda r:r.pop('node_id'), lambda r:r.update(excerpts=[])]:
            audit = copy.deepcopy(self.audit); mutation(audit['mappings'][2]['attribute_refs'][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): self.evaluate(audit)
        for refs in [[], None]:
            audit = copy.deepcopy(self.audit); audit['mappings'][2]['attribute_refs'] = refs
            with self.assertRaises(ValueError): self.evaluate(audit)
        draft = copy.deepcopy(self.draft); draft['businesses'][1]['products_services'] = [' ']
        with self.assertRaises(ValueError): self.evaluate(draft=draft)
        draft = copy.deepcopy(self.draft); draft['businesses'][1]['products_services'] = []
        with self.assertRaises(ValueError): self.evaluate(draft=draft)

    def test_exact_attribute_claim_and_current_mention_origin_are_required(self):
        for excerpts in [[dict(block_id='product', quote='Invented quote')],
                         [dict(block_id='foreign', quote='Beacon support software')],
                         [dict(block_id='section', quote='Services is a reportable segment.')],
                         [dict(block_id='product', quote='Beacon support software')],
                         [dict(block_id='competition', quote=self.packet['blocks'][-1]['text'])]]:
            audit = copy.deepcopy(self.audit); audit['mappings'][2]['attribute_refs'][0]['excerpts'] = excerpts
            with self.subTest(excerpts=excerpts), self.assertRaises(ValueError): self.evaluate(audit)
        # same_source_span needs this location; a cross-block reference must
        # instead declare same_identity_elsewhere and explain its alignment.
        audit = copy.deepcopy(self.audit)
        ref = audit['mappings'][2]['attribute_refs'][0]
        ref['excerpts'] = [e for e in ref['excerpts'] if e['block_id'] == 'product']
        self.assertEqual(self.evaluate(audit)['computed_status'], 'pass')

    def test_repeated_mention_can_share_existing_attribute_with_explicit_elsewhere_alignment(self):
        # One attribute and ONE existing defining excerpt cover two separately
        # located inventory occurrences; no duplicate candidate evidence needed.
        claim = self.draft['businesses'][1]['claim_evidence'][-1]
        claim['excerpts'] = [e for e in claim['excerpts'] if e['block_id'] == 'product']
        before = copy.deepcopy(self.draft)
        audit = self.rebound(self.draft)
        for item in audit['mappings'][2:4]:
            item['attribute_refs'][0]['excerpts'] = copy.deepcopy(claim['excerpts'])
        mapping = audit['mappings'][3]
        ref = mapping['attribute_refs'][0]
        ref['alignment'] = 'same_identity_elsewhere'
        mapping['rationale'] = ('The original product occurrence and the competition paragraph both '
            'refer to the issuer\'s Beacon support software, with no different cloud or regional '
            'qualifier; use the existing Services attribute without a duplicate.')
        result = self.evaluate(audit)
        self.assertEqual(result['computed_status'], 'pass')
        self.assertEqual(result['semantic_acceptance'], 'not_evaluated')
        self.assertEqual(self.draft, before)
        self.assertEqual(len(self.draft['businesses'][1]['products_services']), 1)
        # Merely changing the flag cannot turn a same-block quote into an
        # elsewhere justification, and no field omission activates a fallback.
        audit['mappings'][2]['attribute_refs'][0]['alignment'] = 'same_identity_elsewhere'
        with self.assertRaisesRegex(ValueError, 'elsewhere_alignment_mismatch'): self.evaluate(audit)
        audit['mappings'][2]['attribute_refs'][0]['alignment'] = 'same_source_span'
        ref['excerpts'] = [dict(block_id='foreign', quote='Beacon support software')]
        with self.assertRaisesRegex(ValueError, 'existing_claim'): self.evaluate(audit)

    def test_attribute_evidence_cannot_be_duplicated_or_attached_to_other_disposition(self):
        audit = copy.deepcopy(self.audit)
        audit['mappings'][2]['attribute_refs'].append(copy.deepcopy(audit['mappings'][2]['attribute_refs'][0]))
        with self.assertRaisesRegex(ValueError, 'duplicate_attribute_target'): self.evaluate(audit)
        audit = copy.deepcopy(self.audit)
        audit['mappings'][2]['attribute_refs'][0]['excerpts'] *= 2
        with self.assertRaisesRegex(ValueError, 'duplicate_attribute_excerpt'): self.evaluate(audit)
        audit = copy.deepcopy(self.audit); audit['mappings'][2].update(disposition='node', node_ids=['services'])
        with self.assertRaisesRegex(ValueError, 'non_attribute'): self.evaluate(audit)

    def test_scope_candidate_inventory_and_check_sets_are_bound(self):
        for key in ['candidate_sha256', 'inventory_sha256']:
            audit = copy.deepcopy(self.audit); audit[key] = '0'*64
            with self.assertRaises(ValueError): self.evaluate(audit)
        for key in ['company_id', 'period_end', 'source_sha256']:
            packet = copy.deepcopy(self.packet); packet[key] = 'foreign'
            with self.assertRaisesRegex(ValueError, 'source_packet_binding'): self.evaluate(packet=packet)
        for collection in ['mappings', 'checks']:
            for duplicate in [False, True]:
                audit = copy.deepcopy(self.audit)
                if duplicate: audit[collection].append(copy.deepcopy(audit[collection][0]))
                else: audit[collection].pop()
                with self.assertRaises(ValueError): self.evaluate(audit)
        draft = copy.deepcopy(self.draft); draft['company_id'] = 'different'
        with self.assertRaisesRegex(ValueError, 'scope_mismatch'): self.evaluate(draft=draft)

    def test_context_cannot_hide_issuer_even_with_other_trigger(self):
        for index in [0, 1, 2, 3]:
            inventory = copy.deepcopy(self.inventory); inventory['mentions'][index]['trigger'] = 'other'
            audit = copy.deepcopy(self.audit); audit['inventory_sha256'] = v1.canonical_hash(inventory)
            audit['mappings'][index].update(disposition='context', node_ids=[], attribute_refs=[], identity_requirement='context')
            result = self.evaluate(audit, inventory=inventory)
            self.assertEqual(result['computed_status'], 'needs_revision')
            self.assertIn('issuer_mention_not_represented', [g['code'] for g in result['gaps']])

    def test_unresolved_missing_and_deferred_cannot_pass(self):
        for disposition in ['unresolved', 'missing']:
            # Even a non-issuer mention's uncertainty must remain visible.
            audit = copy.deepcopy(self.audit); audit['mappings'][-1]['disposition'] = disposition
            self.assertEqual(self.evaluate(audit)['computed_status'], 'needs_revision')
        audit = copy.deepcopy(self.audit); audit['mappings'][2].update(disposition='attribute_deferred', attribute_refs=[])
        with self.assertRaises(ValueError): self.evaluate(audit)

    def test_identity_requirement_is_a_separate_model_judgment_not_trigger_rule(self):
        audit = copy.deepcopy(self.audit); audit['mappings'][2]['identity_requirement'] = 'independent_node'
        result = self.evaluate(audit)
        self.assertIn('independent_identity_not_represented', [g['code'] for g in result['gaps']])
        audit['mappings'][2]['identity_requirement'] = 'unresolved'
        self.assertEqual(self.evaluate(audit)['computed_status'], 'needs_revision')
        audit['mappings'][2]['identity_requirement'] = 'attribute_sufficient'
        self.assertEqual(self.evaluate(audit)['computed_status'], 'pass')

    def test_real_attribute_presence_is_not_semantic_truth(self):
        draft = copy.deepcopy(self.draft)
        draft['businesses'][1]['products_services'][0] = 'Unjustified synthetic product interpretation'
        audit = self.rebound(draft)
        # A real string plus a real source quote cannot establish entailment.
        # Therefore even an all-supported scripted/model audit stays unaccepted.
        self.assertEqual(self.evaluate(audit, draft=draft)['semantic_acceptance'], 'not_evaluated')
        target = next(t for t in v1.check_targets(draft) if t.get('field') == 'products_services')
        next(c for c in audit['checks'] if c['check_key'] == target['check_key'])['verdict'] = 'unsupported'
        self.assertEqual(self.evaluate(audit, draft=draft)['computed_status'], 'needs_revision')

    def test_customers_and_explicit_monetization_are_legal_but_unknown_is_not_coverage(self):
        for field in ['customers', 'monetization']:
            draft = copy.deepcopy(self.draft); node = draft['businesses'][1]
            claim = node['claim_evidence'][-1]; claim['field'] = field
            node['products_services'] = []
            node[field] = ['Beacon support software'] if field == 'customers' else [dict(
                description='Beacon support software', basis='explicit', evidence_block_ids=['product', 'competition'])]
            audit = self.rebound(draft)
            for mapping in audit['mappings'][2:4]: mapping['attribute_refs'][0]['field'] = field
            self.assertEqual(self.evaluate(audit, draft=draft)['computed_status'], 'pass')
            self.assertEqual(self.evaluate(audit, draft=draft)['semantic_acceptance'], 'not_evaluated')
            if field == 'monetization':
                node['monetization'][0]['basis'] = 'unknown'; node['claim_evidence'].pop()
                audit = self.rebound(draft)
                for mapping in audit['mappings'][2:4]: mapping['attribute_refs'][0]['field'] = field
                with self.assertRaisesRegex(ValueError, 'unknown_monetization'): self.evaluate(audit, draft=draft)

    def test_attribute_host_is_not_a_substitute_for_own_node_identity_mapping(self):
        audit = copy.deepcopy(self.audit); audit['mappings'][1].update(disposition='unresolved', node_ids=['services'], identity_requirement='unresolved')
        result = self.evaluate(audit)
        self.assertIn(dict(code='node_without_mention_mapping', node_id='services'), result['gaps'])

    def test_v1_is_unchanged_and_never_silently_migrated(self):
        packet, draft, inventory, audit = sample(self.root)
        self.assertEqual(v1.validate_audit(audit, packet, inventory, draft)['computed_status'], 'pass')
        with self.assertRaises(ValueError): v2.validate_audit(audit, packet, inventory, draft)
        draft = copy.deepcopy(self.draft); draft['schema_version'] = 'business-draft-v1'
        with self.assertRaisesRegex(ValueError, 'contract_version'): self.evaluate(draft=draft)
        with self.assertRaises(ValueError): v1.validate_audit(self.audit, self.packet, self.inventory, self.draft)


if __name__ == '__main__': unittest.main()
