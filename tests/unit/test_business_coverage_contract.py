"""Coverage accounting tests use independent synthetic issuers and no model."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from uteki.agents.business_map.coverage_contract import (
    canonical_hash, check_targets, required_mention, validate_audit, validate_inventory,
    inventory_contract_errors, apply_inventory_repair, InventoryRepair,
)
from uteki.agents.business_map.product_contract import validate_draft


spec = importlib.util.spec_from_file_location(
    "coverage_source_fixture", Path(__file__).with_name("test_business_only_run.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def sample(root, company="quartz", period="2020-09-30"):
    packet, raw_draft = fixture.fixture(root, company, period)
    draft = validate_draft(raw_draft, packet).model_dump()
    blocks = {b["id"]: b for b in packet["blocks"]}
    def mention(key, block, surface, category, trigger):
        return dict(id=key, block_id=block, surface=surface, category=category,
                    trigger=trigger, excerpts=[dict(block_id=block, quote=blocks[block]["text"])],
                    scope_note="Selected issuer business statement.")
    mentions = [mention("m1", "issuer", company + " Systems", "issuer_entity", "other"),
                mention("m2", "section", "Services", "issuer_grouping", "definition"),
                mention("m3", "product", "Beacon support software", "issuer_offering", "composition"),
                mention("m4", "competition", "Beacon support software", "issuer_offering", "self_offering"),
                mention("m5", "competition", "rivals", "competitor_or_category", "definition")]
    mentioned = {m["block_id"] for m in mentions}
    inventory = dict(schema_version="business-coverage-inventory-v1",
                     source_packet_sha256=canonical_hash(packet), mentions=mentions,
                     blocks=[dict(block_id=b["id"], disposition="mentions" if b["id"] in mentioned
                                  else "layout" if b["id"] == "layout" else "context",
                                  reason="Source accounting.") for b in packet["blocks"]])
    inventory = validate_inventory(inventory, packet)
    mappings = [dict(mention_id=m["id"], disposition="context_only" if m["id"] == "m5" else "node",
                     node_ids=[] if m["id"] == "m5" else
                     [dict(m1="issuer", m2="services", m3="beacon", m4="beacon")[m["id"]]],
                     rationale="Own source mention mapped to candidate.") for m in mentions]
    audit = dict(schema_version="business-coverage-audit-v1", candidate_sha256=canonical_hash(draft),
                 inventory_sha256=canonical_hash(inventory), mappings=mappings,
                 checks=[dict(check_key=t["check_key"], verdict="supported", rationale="Supported by cited source.")
                         for t in check_targets(draft)])
    return packet, draft, inventory, audit


class CoverageContractTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.packet, self.draft, self.inventory, self.audit = sample(self.root)

    def evaluate(self, audit=None, inventory=None, draft=None):
        return validate_audit(audit if audit is not None else self.audit, self.packet,
                              inventory if inventory is not None else self.inventory,
                              draft if draft is not None else self.draft)

    def test_accounting_for_two_issuers_and_periods(self):
        for company, period in [("quartz", "2020-09-30"), ("cobalt", "2023-03-31")]:
            packet, draft, inventory, audit = sample(self.root, company, period)
            result = validate_audit(audit, packet, inventory, draft)
            self.assertEqual(result["computed_status"], "pass")
            self.assertEqual(result["gaps"], [])
            self.assertNotIn("semantic_acceptance", result)

    def test_all_blocks_exactly_once_and_dispositions_agree(self):
        for mutate in [lambda i: i["blocks"].pop(),
                       lambda i: i["blocks"].append(copy.deepcopy(i["blocks"][0])),
                       lambda i: i["blocks"][0].update(block_id="foreign"),
                       lambda i: i["blocks"][0].update(disposition="context"),
                       lambda i: i["blocks"][1].update(disposition="mentions")]:
            value = copy.deepcopy(self.inventory)
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_inventory(value, self.packet)

    def test_mentions_and_excerpts_cannot_cross_scope_or_fabricate_text(self):
        for mutate in [lambda i: i["mentions"][0].update(block_id="foreign"),
                       lambda i: i["mentions"][0].update(surface="Invented company"),
                       lambda i: i["mentions"][0]["excerpts"][0].update(block_id="foreign"),
                       lambda i: i["mentions"][0]["excerpts"][0].update(quote="Invented quote"),
                       lambda i: i["mentions"].append(copy.deepcopy(i["mentions"][0])),
                       lambda i: i.update(source_packet_sha256="0" * 64)]:
            value = copy.deepcopy(self.inventory)
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_inventory(value, self.packet)

    def test_whitespace_is_normalized_without_other_quote_rewriting(self):
        value = copy.deepcopy(self.inventory)
        value["mentions"][0]["surface"] = "quartz\n  Systems"
        value["mentions"][0]["excerpts"][0]["quote"] = "quartz\n Systems is the reporting company."
        validate_inventory(value, self.packet)
        value["mentions"][0]["surface"] = "Quartz Systems"
        with self.assertRaisesRegex(ValueError, "surface_not_in_source"):
            validate_inventory(value, self.packet)

    def test_required_is_per_mention_not_competition_heading(self):
        own, competitor = self.inventory["mentions"][3:5]
        self.assertTrue(required_mention(own))
        self.assertFalse(required_mention(competitor))
        for category in ("generic_capability", "partner_customer", "cross_reference"):
            self.assertFalse(required_mention(dict(category=category, trigger="definition")))
        audit = copy.deepcopy(self.audit)
        audit["mappings"][3].update(disposition="context_only", node_ids=[])
        result = self.evaluate(audit)
        self.assertEqual(result["computed_status"], "needs_revision")
        self.assertIn(dict(code="required_mention_not_node", mention_id="m4", disposition="context_only"), result["gaps"])

    def test_mapping_and_check_sets_are_complete_and_unique(self):
        for mutate in [lambda a: a["mappings"].pop(),
                       lambda a: a["mappings"].append(copy.deepcopy(a["mappings"][0])),
                       lambda a: a["checks"].pop(),
                       lambda a: a["checks"].append(copy.deepcopy(a["checks"][0])),
                       lambda a: a["checks"][0].update(check_key="c:999"),
                       lambda a: a["mappings"][0].update(mention_id="outside"),
                       lambda a: a["mappings"][0].update(node_ids=["outside"]),
                       lambda a: a["mappings"][0].update(node_ids=[]),
                       lambda a: a["mappings"][-1].update(node_ids=["issuer"]),
                       lambda a: a["mappings"][0].update(node_ids=["issuer", "issuer"])]:
            value = copy.deepcopy(self.audit)
            mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.evaluate(value)

    def test_partial_and_other_semantic_failures_are_recorded_not_erased(self):
        for verdict in ("partial", "unsupported", "overstated_basis", "scope_mismatch", "uncertain"):
            audit = copy.deepcopy(self.audit)
            audit["checks"][0].update(verdict=verdict)
            result = self.evaluate(audit)
            self.assertEqual(result["computed_status"], "needs_revision")
            self.assertEqual(result["gaps"][0]["verdict"], verdict)
        self.audit["mappings"][-1]["disposition"] = "unresolved"
        self.assertEqual(self.evaluate()["computed_status"], "needs_revision")

    def test_other_party_or_generic_mention_cannot_make_own_business_graph_pass(self):
        for category in ("competitor_or_category", "partner_customer", "generic_capability", "cross_reference"):
            inventory = copy.deepcopy(self.inventory)
            inventory["mentions"][-1]["category"] = category
            audit = copy.deepcopy(self.audit)
            audit["inventory_sha256"] = canonical_hash(inventory)
            audit["mappings"][-1].update(disposition="node", node_ids=["beacon"])
            result = self.evaluate(audit, inventory)
            self.assertEqual(result["computed_status"], "needs_revision")
            self.assertIn(dict(code="non_issuer_mention_mapped_as_business_node",
                               mention_id="m5", category=category), result["gaps"])

    def test_every_node_needs_a_node_mapping(self):
        # Existing, valid node is not covered merely because some other node was mapped.
        audit = copy.deepcopy(self.audit)
        audit["mappings"][1]["node_ids"] = ["issuer"]
        result = self.evaluate(audit)
        self.assertIn(dict(code="node_without_mention_mapping", node_id="services"), result["gaps"])

    def test_unresolved_candidates_are_retained_without_becoming_coverage(self):
        audit = copy.deepcopy(self.audit)
        audit['mappings'][1].update(disposition='unresolved', node_ids=['services'])
        result = self.evaluate(audit)
        self.assertEqual(result['computed_status'], 'needs_revision')
        self.assertIn(dict(code='required_mention_not_node', mention_id='m2',
            disposition='unresolved', related_node_ids=['services']), result['gaps'])
        self.assertIn(dict(code='node_without_mention_mapping', node_id='services'), result['gaps'])
        self.assertEqual(audit['mappings'][1]['node_ids'], ['services'])
        # Even a non-required competitor mention remains unresolved when it names
        # a possible related node; it cannot turn uncertainty into a pass.
        audit = copy.deepcopy(self.audit)
        audit['mappings'][-1].update(disposition='unresolved', node_ids=['beacon'])
        result = self.evaluate(audit)
        self.assertEqual(result['computed_status'], 'needs_revision')
        self.assertIn(dict(code='mention_unresolved', mention_id='m5',
            related_node_ids=['beacon']), result['gaps'])

    def test_related_candidates_still_reject_foreign_duplicate_and_other_dispositions(self):
        for disposition, ids in [('unresolved', ['foreign']), ('unresolved', ['beacon', 'beacon']),
                                 ('missing', ['beacon']), ('context_only', ['beacon']),
                                 ('attribute_deferred', ['beacon'])]:
            audit = copy.deepcopy(self.audit)
            audit['mappings'][2].update(disposition=disposition, node_ids=ids)
            with self.subTest(disposition=disposition, ids=ids), self.assertRaises(ValueError):
                self.evaluate(audit)

    def test_old_audit_cannot_attach_to_revised_candidate_or_inventory(self):
        draft = copy.deepcopy(self.draft)
        draft["businesses"][0]["description"] += " Revised description."
        with self.assertRaisesRegex(ValueError, "candidate_binding"):
            self.evaluate(draft=draft)
        inventory = copy.deepcopy(self.inventory)
        inventory["mentions"][0]["scope_note"] += " Revised scope."
        with self.assertRaisesRegex(ValueError, "inventory_binding"):
            self.evaluate(inventory=inventory)
        other_packet = copy.deepcopy(self.packet)
        other_packet["company_id"] = "different"
        with self.assertRaisesRegex(ValueError, "source_packet_binding"):
            validate_inventory(self.inventory, other_packet)

    def test_model_cannot_supply_status_or_replace_claim_evidence(self):
        for mutate in [lambda a: a.update(computed_status="pass"),
                       lambda a: a["checks"][0].update(excerpts=[]),
                       lambda a: a["checks"][0].update(verdict="looks_good")]:
            audit = copy.deepcopy(self.audit)
            mutate(audit)
            with self.assertRaises(ValueError):
                self.evaluate(audit)

    def test_targets_cover_list_indices_and_relationship_endpoints(self):
        draft = copy.deepcopy(self.draft)
        node = draft["businesses"][2]
        node["products_services"] = ["Beacon software", "Support"]
        for index in range(2):
            node["claim_evidence"].append(dict(field="products_services", item_index=index,
                                              excerpts=copy.deepcopy(node["claim_evidence"][0]["excerpts"])))
        draft = validate_draft(draft, self.packet).model_dump()
        targets = check_targets(draft)
        fields = [t for t in targets if t.get("field") == "products_services"]
        self.assertEqual([t["item_index"] for t in fields], [0, 1])
        self.assertEqual([t["statement"] for t in fields], ["Beacon software", "Support"])
        relation = targets[-1]
        self.assertEqual(relation["check_key"], "r:0")
        self.assertEqual(relation["source_name"], "Beacon support software")
        self.assertEqual(relation["target_name"], "Services")
        self.assertEqual(relation["excerpts"], draft["relationships"][0]["excerpts"])
        self.assertEqual(len({t["check_key"] for t in targets}), len(targets))

    def test_hash_is_order_independent_but_value_sensitive(self):
        self.assertEqual(canonical_hash(dict(a=1, b=2)), canonical_hash(dict(b=2, a=1)))
        self.assertNotEqual(canonical_hash(dict(a=1)), canonical_hash(dict(a=2)))

    def broken_inventory(self):
        value = copy.deepcopy(self.inventory)
        value['mentions'][0]['surface'] = 'unsupported paraphrase'
        value['mentions'][0]['excerpts'] = copy.deepcopy(value['mentions'][1]['excerpts'])
        value['mentions'][2]['excerpts'][0]['quote'] = 'not a literal excerpt'
        return value

    def repair(self, original):
        return dict(schema_version='business-coverage-inventory-repair-v1',
            inventory_sha256=canonical_hash(original), source_packet_sha256=canonical_hash(self.packet),
            replacements=copy.deepcopy([self.inventory['mentions'][0], self.inventory['mentions'][2]]))

    def test_aggregate_literal_errors_include_all_locations_and_eligible_ids(self):
        value = self.broken_inventory()
        result = inventory_contract_errors(value, self.packet)
        self.assertTrue(result['repairable'])
        self.assertEqual(result['error_mention_ids'], ['m1', 'm3'])
        self.assertEqual([(e['code'], e['path'], e['mention_id']) for e in result['errors']], [
            ('mention_surface_not_in_source', ['mentions', 0, 'surface'], 'm1'),
            ('mention_origin_excerpt_required', ['mentions', 0, 'excerpts'], 'm1'),
            ('mention_excerpt_not_in_source', ['mentions', 2, 'excerpts', 0, 'quote'], 'm3')])
        self.assertEqual(result['inventory_sha256'], canonical_hash(value))
        self.assertEqual(result['source_packet_sha256'], canonical_hash(self.packet))

    def test_local_patch_keeps_other_mentions_and_blocks_immutable(self):
        value = self.broken_inventory()
        before = copy.deepcopy(value)
        repaired = apply_inventory_repair(value, self.packet, self.repair(value))
        self.assertEqual(repaired, self.inventory)
        self.assertEqual(value, before)
        self.assertEqual(repaired['blocks'], value['blocks'])
        self.assertEqual([m['id'] for m in repaired['mentions']], [m['id'] for m in value['mentions']])
        self.assertFalse(inventory_contract_errors(repaired, self.packet)['repairable'])
        self.assertEqual(inventory_contract_errors(repaired, self.packet)['errors'], [])

    def test_patch_rejects_missing_extra_duplicate_or_unbound_replacements(self):
        value = self.broken_inventory()
        for mutation in [lambda r:r['replacements'].pop(),
                         lambda r:r['replacements'].append(copy.deepcopy(self.inventory['mentions'][1])),
                         lambda r:r['replacements'].append(copy.deepcopy(r['replacements'][0])),
                         lambda r:r.update(inventory_sha256='0'*64),
                         lambda r:r.update(source_packet_sha256='0'*64),
                         lambda r:r.update(blocks=copy.deepcopy(value['blocks'])),
                         lambda r:r.update(computed_status='pass')]:
            patch = self.repair(value)
            mutation(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                apply_inventory_repair(value, self.packet, patch)

    def test_local_repair_cannot_change_classification_or_scope_to_evade_coverage(self):
        value = self.broken_inventory()
        for field, replacement in [('category', 'cross_reference'), ('trigger', 'composition'),
                                   ('block_id', 'product'), ('scope_note', 'Altered scope')]:
            patch = self.repair(value)
            patch['replacements'][0][field] = replacement
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'changed_non_evidence_fields'):
                apply_inventory_repair(value, self.packet, patch)
        patch = self.repair(value)
        patch['replacements'][0]['surface'] = 'still unsupported'
        with self.assertRaisesRegex(ValueError, 'mention_surface_not_in_source'):
            apply_inventory_repair(value, self.packet, patch)

    def test_global_faults_are_not_repaired_as_local_mentions(self):
        for mutate in [lambda i:i.update(source_packet_sha256='0'*64),
                       lambda i:i['blocks'].pop(),
                       lambda i:i['blocks'].append(copy.deepcopy(i['blocks'][0])),
                       lambda i:i['blocks'][0].update(disposition='context'),
                       lambda i:i['mentions'].append(copy.deepcopy(i['mentions'][0])),
                       lambda i:i['mentions'][0].update(block_id='outside'),
                       lambda i:i['mentions'][0].pop('category')]:
            value = self.broken_inventory()
            mutate(value)
            result = inventory_contract_errors(value, self.packet)
            self.assertFalse(result['repairable'])
            self.assertTrue(any(not e['repairable'] for e in result['errors']))
            with self.assertRaisesRegex(ValueError, 'not_locally_repairable'):
                apply_inventory_repair(value, self.packet, self.repair(value))

    def test_schema_faults_aggregate_without_embedding_source_or_untrusted_messages(self):
        value = copy.deepcopy(self.inventory)
        del value['mentions'][0]['category']
        del value['mentions'][2]['scope_note']
        value['mentions'][2]['excerpts'][0]['quote'] = 123
        result = inventory_contract_errors(value, self.packet)
        self.assertEqual(len(result['errors']), 3)
        self.assertFalse(result['repairable'])
        self.assertEqual([e['mention_id'] for e in result['errors']], ['m1', 'm3', 'm3'])
        self.assertTrue(all(e['code'] == 'inventory_schema_invalid' for e in result['errors']))
        self.assertTrue(all('input' not in e and 'msg' not in e for e in result['errors']))

    def test_duplicate_and_out_of_scope_excerpts_are_aggregated_and_locally_repairable(self):
        value = copy.deepcopy(self.inventory)
        value['mentions'][0]['excerpts'].append(copy.deepcopy(value['mentions'][0]['excerpts'][0]))
        value['mentions'][2]['excerpts'].append(dict(block_id='outside', quote='Unavailable source'))
        result = inventory_contract_errors(value, self.packet)
        self.assertTrue(result['repairable'])
        self.assertEqual(result['error_mention_ids'], ['m1', 'm3'])
        self.assertEqual({e['code'] for e in result['errors']},
                         {'duplicate_mention_excerpt', 'mention_excerpt_outside_packet'})
        self.assertEqual(apply_inventory_repair(value, self.packet, self.repair(value)), self.inventory)

    def test_repair_is_source_bound_for_two_independent_issuers_and_periods(self):
        for company, period in [('quartz', '2020-09-30'), ('cobalt', '2023-03-31')]:
            packet, _, inventory, _ = sample(self.root, company, period)
            bad = copy.deepcopy(inventory)
            bad['mentions'][0]['surface'] = 'paraphrased issuer'
            patch = InventoryRepair(schema_version='business-coverage-inventory-repair-v1',
                inventory_sha256=canonical_hash(bad), source_packet_sha256=canonical_hash(packet),
                replacements=[inventory['mentions'][0]])
            self.assertEqual(apply_inventory_repair(bad, packet, patch), inventory)


if __name__ == "__main__":
    unittest.main()
