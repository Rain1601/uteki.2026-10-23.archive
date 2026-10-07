"""Aggregate local attribute-reference failures without accepting a failed audit.

This is a read-only diagnostic view. It neither rewrites model judgments nor
changes the live audit validator or any execution/retry policy.
"""
from collections import Counter
from copy import deepcopy

from . import coverage_contract as inventory_contract
from . import coverage_contract_v2 as contract
from .product_contract import validate_draft

VERSION = 'business-coverage-diagnostics-v1'


def _complete_unique(values, expected, label):
    if len(values) != len(set(values)):
        raise ValueError('diagnostic_duplicate_' + label)
    if set(values) != set(expected):
        raise ValueError('diagnostic_incomplete_' + label)


def _observation(ref, mention, nodes):
    """Only describe text locations within already-bound candidate excerpts."""
    node = nodes.get(ref.node_id)
    claim = next((c for c in node['claim_evidence'] if c['field'] == ref.field
                  and c['item_index'] == ref.item_index), None) if node else None
    quoted = {(e['block_id'], ' '.join(e['quote'].split())) for e in claim['excerpts']} if claim else set()
    bound = bool(claim) and all((e.block_id, ' '.join(e.quote.split())) in quoted for e in ref.excerpts)
    surface = ' '.join(mention['surface'].split())
    matches = [dict(excerpt_index=i, block_id=e.block_id, is_origin_block=e.block_id == mention['block_id'])
               for i, e in enumerate(ref.excerpts) if bound and surface in ' '.join(e.quote.split())]
    here = any(m['is_origin_block'] for m in matches)
    elsewhere = any(not m['is_origin_block'] for m in matches)
    location = ('origin_and_other_blocks' if here and elsewhere else 'origin_block' if here else
                'other_block_only' if elsewhere else 'no_full_surface_match') if bound else 'unbound_reference'
    return dict(evidence_is_existing_candidate_claim=bound, exact_surface_location=location,
                matching_excerpts=matches, derivation='whitespace_normalized_literal_match_only',
                identity_and_scope_equivalence='not_inferred', alias_equivalence='not_inferred',
                automatic_alignment_rewrite=False)


def diagnose_audit(value, packet, inventory, draft):
    """Hard-fail global accounting; enumerate local errors without changing raw.

    Even with valid schema and full accounting, INVALID_WITH_FINDINGS is not an
    accepted audit. A valid reference only proves its structural bindings, not
    that the model's proposed identity or economic interpretation is correct.
    """
    if not isinstance(value, dict):
        raise ValueError('diagnostic_raw_audit_object_required')
    checked_inventory = inventory_contract.validate_inventory(inventory, packet)
    checked_draft = validate_draft(draft, packet, expected_version='business-draft-v2').model_dump()
    audit = contract.Audit.model_validate(value)
    if audit.candidate_sha256 != inventory_contract.canonical_hash(checked_draft):
        raise ValueError('diagnostic_candidate_binding_mismatch')
    if audit.inventory_sha256 != inventory_contract.canonical_hash(checked_inventory):
        raise ValueError('diagnostic_inventory_binding_mismatch')
    mentions = {m['id']:m for m in checked_inventory['mentions']}
    nodes = {n['id']:n for n in checked_draft['businesses']}
    _complete_unique([m.mention_id for m in audit.mappings], mentions, 'mappings')
    _complete_unique([c.check_key for c in audit.checks],
                     [c['check_key'] for c in inventory_contract.check_targets(checked_draft)], 'checks')
    # Keep all non-attribute protocol branches fail-closed. Only the individual
    # attribute-validator failures have a defined aggregate diagnostic behavior.
    for mapping in audit.mappings:
        ids = mapping.node_ids
        if len(ids) != len(set(ids)) or not set(ids) <= nodes.keys():
            raise ValueError('diagnostic_mapping_node_invalid')
        if mapping.disposition == 'node' and not ids:
            raise ValueError('node_mapping_requires_node_ids')
        if mapping.disposition not in ('node', 'unresolved') and ids:
            raise ValueError('non_node_mapping_requires_empty_node_ids')
        if mapping.disposition == 'attribute':
            if not mapping.attribute_refs:
                raise ValueError('attribute_mapping_requires_populated_references')
            targets = [(r.node_id,r.field,r.item_index) for r in mapping.attribute_refs]
            if len(targets) != len(set(targets)):
                raise ValueError('diagnostic_duplicate_attribute_targets')
        elif mapping.attribute_refs:
            raise ValueError('non_attribute_mapping_requires_empty_references')
    findings, mapping_states = [], []
    refs_total = 0
    for mi, mapping in enumerate(audit.mappings):
        invalid = []
        for ri, ref in enumerate(mapping.attribute_refs):
            refs_total += 1
            try:
                contract._validate_attribute(ref, mentions[mapping.mention_id], nodes)
            except ValueError as error:
                finding = dict(path=f'/mappings/{mi}/attribute_refs/{ri}', mapping_index=mi,
                    mention_id=mapping.mention_id, reference_index=ri, code=str(error),
                    declared_alignment=ref.alignment, observation=_observation(ref, mentions[mapping.mention_id], nodes))
                findings.append(finding)
                invalid.append(ri)
        mapping_states.append(dict(mapping_index=mi, mention_id=mapping.mention_id,
            declared_disposition=mapping.disposition, invalid_reference_indices=invalid,
            effective_state='unresolved' if invalid else 'unmodified_model_proposal',
            attribute_reference_protocol='invalid' if invalid else 'valid' if mapping.attribute_refs else 'not_applicable'))
    accepted_contract = None if findings else contract.validate_audit(value, packet, checked_inventory, checked_draft)
    return dict(schema_version=VERSION, status='INVALID_WITH_FINDINGS' if findings else 'contract_valid',
        audit_contract_valid=not findings, computed_status='needs_revision' if findings else accepted_contract['computed_status'],
        semantic_acceptance='not_evaluated', independent_acceptance=False,
        source_packet_sha256=inventory_contract.canonical_hash(packet),
        inventory_sha256=inventory_contract.canonical_hash(checked_inventory),
        candidate_sha256=inventory_contract.canonical_hash(checked_draft),
        raw_audit_canonical_sha256=inventory_contract.canonical_hash(value), raw_audit=deepcopy(value),
        counts=dict(mappings=len(audit.mappings), checks=len(audit.checks), attribute_references=refs_total,
            invalid_attribute_references=len(findings), valid_attribute_references=refs_total-len(findings),
            affected_mappings=sum(bool(m['invalid_reference_indices']) for m in mapping_states)),
        findings=findings, mapping_states=mapping_states,
        model_checks=dict(provenance='raw_model_self_judgments_not_independent_acceptance',
            counts=dict(Counter(c.verdict for c in audit.checks)), checks=deepcopy(value['checks'])),
        validated_contract_result=accepted_contract,
        limits=['Invalid mappings remain in the full accounting denominator and never establish coverage.',
                'Literal text in another source block does not prove identity or scope equivalence.',
                'No alias inference, alignment rewrite, source change or model judgment repair is performed.'])
