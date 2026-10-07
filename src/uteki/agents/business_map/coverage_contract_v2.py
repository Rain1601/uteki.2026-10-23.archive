"""Source-bound coverage of business identities AND populated attributes.

V1 remains immutable. This version accounts for every source mention without
requiring every named offering to become a graph node. Structural accounting,
model self-review and independent semantic acceptance are separate outcomes.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .coverage_contract import (
    Check, Hash, canonical_hash, check_targets, validate_inventory,
)
from .product_contract import (
    BUSINESS_DRAFT_V2_VERSION, Contract, EvidenceExcerptDraft, ID, Text,
    validate_draft,
)


class AttributeRef(Contract):
    node_id: ID
    field: Literal['products_services', 'customers', 'monetization']
    item_index: Annotated[int, Field(ge=0)]
    alignment: Literal['same_source_span', 'same_identity_elsewhere'] = Field(description=(
        'Required explicit alignment. same_source_span locates this mention in '
        'its inventory block. same_identity_elsewhere uses the same surface in '
        'an existing claim quote from another block in this frozen source; explain '
        'why identity and scope agree in mapping rationale. String equality is not semantic proof.'))
    excerpts: list[EvidenceExcerptDraft] = Field(min_length=1, description=(
        'Copy exact existing claim excerpts for this populated attribute. At '
        'least one must contain this inventory mention surface, with the declared alignment. '
        'Do not replace the candidate claim evidence with new supporting text.'))


class Mapping(Contract):
    mention_id: ID
    disposition: Literal['node', 'attribute', 'context', 'unresolved', 'missing']
    node_ids: list[ID] = Field(description=(
        'Identity nodes only for node; related possibilities for unresolved. '
        'Empty for attribute, context and missing. Attribute hosts go in attribute_refs.'))
    attribute_refs: list[AttributeRef] = Field(default_factory=list)
    identity_requirement: Literal['independent_node', 'attribute_sufficient', 'context', 'unresolved'] = Field(
        description='Source-grounded semantic assessment: reporting company/segment and material '
        'business groups may require independent identity; merely being a named offering does '
        'not. Explain in rationale. This is a model judgment, not an engineering truth assertion.')
    rationale: Text = Field(description=(
        'Explain the source-grounded identity/attribute decision. For each '
        'same_identity_elsewhere reference, justify the same object and scope '
        'across the inventory occurrence and existing attribute evidence; do '
        'not infer identity merely from the same name.'))


class Audit(Contract):
    schema_version: Literal['business-coverage-audit-v2']
    candidate_sha256: Hash
    inventory_sha256: Hash
    mappings: list[Mapping]
    checks: list[Check]


def _unique(values, label):
    values = list(values)
    if len(values) != len(set(values)):
        raise ValueError('duplicate_' + label)
    return set(values)


def _quote_key(excerpt):
    return excerpt['block_id'], ' '.join(excerpt['quote'].split())


def _validate_attribute(ref, mention, nodes):
    if ref.node_id not in nodes:
        raise ValueError('attribute_host_outside_candidate')
    node = nodes[ref.node_id]
    values = node[ref.field]
    if ref.item_index >= len(values):
        raise ValueError('attribute_index_outside_populated_field')
    value = values[ref.item_index]
    statement = value['description'] if ref.field == 'monetization' else value
    if not statement.strip():
        raise ValueError('attribute_value_empty')
    if ref.field == 'monetization' and value['basis'] != 'explicit':
        raise ValueError('unknown_monetization_cannot_establish_coverage')
    claims = [claim for claim in node['claim_evidence']
              if claim['field'] == ref.field and claim['item_index'] == ref.item_index]
    if len(claims) != 1:
        raise ValueError('attribute_existing_claim_required')
    # validate_draft has already checked every original claim quote against the
    # frozen packet. The audit cannot swap in a more convenient quote.
    claim_quotes = {_quote_key(excerpt) for excerpt in claims[0]['excerpts']}
    quotes = _unique((_quote_key(e.model_dump()) for e in ref.excerpts), 'attribute_excerpt')
    if not quotes <= claim_quotes:
        raise ValueError('attribute_excerpt_not_in_existing_claim')
    surface = ' '.join(mention['surface'].split())
    located_here = any(block == mention['block_id'] and surface in quote for block, quote in quotes)
    located_elsewhere = any(block != mention['block_id'] and surface in quote for block, quote in quotes)
    if ref.alignment == 'same_source_span' and not located_here:
        raise ValueError('attribute_excerpt_does_not_locate_mention')
    if ref.alignment == 'same_identity_elsewhere' and (located_here or not located_elsewhere):
        raise ValueError('attribute_elsewhere_alignment_mismatch')
    # Inventory independently locates the original occurrence. Matching a surface
    # in another existing claim is only a structural guard; the model rationale
    # and later independent review must establish identity and scope equivalence.


def validate_audit(value, packet, inventory, draft) -> dict:
    """Validate v2 accounting; preserve model semantic failures as needs_revision.

    Inputs and return signatures intentionally match the v1 entry point. The
    caller must explicitly select this module and freeze schema/version hashes.
    No v1 migration or source/period fallback occurs here.
    """
    inventory = validate_inventory(inventory, packet)
    draft = validate_draft(draft, packet, expected_version=BUSINESS_DRAFT_V2_VERSION).model_dump()
    audit = Audit.model_validate(value)
    if audit.candidate_sha256 != canonical_hash(draft):
        raise ValueError('audit_candidate_binding_mismatch')
    if audit.inventory_sha256 != canonical_hash(inventory):
        raise ValueError('audit_inventory_binding_mismatch')
    mentions = {m['id']: m for m in inventory['mentions']}
    nodes = {node['id']: node for node in draft['businesses']}
    if _unique((m.mention_id for m in audit.mappings), 'mapping') != set(mentions):
        raise ValueError('audit_mapping_coverage_mismatch')
    if _unique((c.check_key for c in audit.checks), 'check') != {t['check_key'] for t in check_targets(draft)}:
        raise ValueError('audit_check_coverage_mismatch')
    gaps, covered_nodes = [], set()
    issuer_categories = {'issuer_entity', 'issuer_grouping', 'issuer_offering'}
    for mapping in audit.mappings:
        mention = mentions[mapping.mention_id]
        mapped = _unique(mapping.node_ids, 'mapping_node')
        if not mapped <= nodes.keys():
            raise ValueError('mapping_node_outside_candidate')
        if mapping.disposition == 'node':
            if not mapped:
                raise ValueError('node_mapping_requires_node_ids')
            covered_nodes.update(mapped)
            if mention['category'] not in issuer_categories:
                gaps.append(dict(code='non_issuer_mention_mapped_as_business_node',
                                 mention_id=mapping.mention_id, category=mention['category']))
        elif mapped and mapping.disposition != 'unresolved':
            raise ValueError('non_node_mapping_requires_empty_node_ids')
        if mapping.disposition == 'attribute':
            if not mapping.attribute_refs:
                raise ValueError('attribute_mapping_requires_populated_references')
            _unique(((r.node_id, r.field, r.item_index) for r in mapping.attribute_refs), 'attribute_target')
            for ref in mapping.attribute_refs:
                _validate_attribute(ref, mention, nodes)
        elif mapping.attribute_refs:
            raise ValueError('non_attribute_mapping_requires_empty_references')
        if mention['category'] in issuer_categories and mapping.disposition not in {'node', 'attribute'}:
            gaps.append(dict(code='issuer_mention_not_represented', mention_id=mapping.mention_id,
                             disposition=mapping.disposition))
        if mapping.disposition in {'unresolved', 'missing'}:
            gaps.append(dict(code='mention_' + mapping.disposition, mention_id=mapping.mention_id,
                             related_node_ids=mapping.node_ids))
        if mapping.identity_requirement == 'independent_node' and mapping.disposition != 'node':
            gaps.append(dict(code='independent_identity_not_represented', mention_id=mapping.mention_id))
        elif mapping.identity_requirement == 'unresolved':
            gaps.append(dict(code='identity_requirement_unresolved', mention_id=mapping.mention_id))
        elif ((mapping.identity_requirement == 'context') != (mapping.disposition == 'context')
              and mapping.disposition not in {'unresolved', 'missing'}):
            gaps.append(dict(code='identity_disposition_mismatch', mention_id=mapping.mention_id))
    for node_id in sorted(nodes.keys() - covered_nodes):
        gaps.append(dict(code='node_without_mention_mapping', node_id=node_id))
    for check in audit.checks:
        if check.verdict != 'supported':
            gaps.append(dict(code='claim_not_supported', check_key=check.check_key,
                             verdict=check.verdict, rationale=check.rationale))
    return dict(audit.model_dump(), computed_status='needs_revision' if gaps else 'pass', gaps=gaps,
                semantic_acceptance='not_evaluated',
                acceptance_basis='source_bound_accounting_and_model_self_review_only')
