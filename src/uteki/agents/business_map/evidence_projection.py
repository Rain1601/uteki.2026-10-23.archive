"""Derive missing redundant relationship indexes from unchanged exact excerpts."""
from copy import deepcopy
from .coverage_contract import canonical_hash
from .product_contract import validate_draft


def project_relationship_evidence(value, packet, *, expected_version):
    """Add only already-cited block IDs; reject extra indexes or any other defect.

    The complete draft validator verifies every quote, reference and business
    contract after projection. This never supplies facts, quotes or new edges.
    """
    projected = deepcopy(value)
    changes = []
    for index, relation in enumerate(projected.get('relationships', [])):
        before = relation.get('evidence_block_ids')
        excerpts = relation.get('excerpts')
        if not isinstance(before, list) or not isinstance(excerpts, list):
            raise ValueError('projection_requires_explicit_indexes_and_excerpts')
        refs = [excerpt['block_id'] for excerpt in excerpts]
        if set(before) - set(refs):
            raise ValueError('projection_cannot_remove_uncited_indexes')
        missing = list(dict.fromkeys(ref for ref in refs if ref not in before))
        if missing:
            relation['evidence_block_ids'] = before + missing
            changes.append(dict(relationship_index=index, source_id=relation['source_id'],
                target_id=relation['target_id'], before=before, after=relation['evidence_block_ids'],
                added=missing, operation='derive_missing_index_from_unchanged_excerpt'))
    validate_draft(projected, packet, expected_version=expected_version)
    return projected, dict(schema_version='business-evidence-index-projection-v1',
        original_sha256=canonical_hash(value), projected_sha256=canonical_hash(projected),
        changes=changes, claims_and_excerpts_unchanged=True, semantic_acceptance='not_evaluated')


def project_business_evidence_indexes(value, packet, *, expected_version):
    """Derive redundant node/relationship indexes only from their own excerpts.

    Preserve every original entry and its order. Nodes can retain valid context
    indexes beyond claim excerpts, per the existing subset contract. Relationship
    index equality, invalid quotes and all other contract errors still reject. Nested
    monetization indexes and all semantic fields remain untouched.
    """
    if not isinstance(value, dict):
        raise ValueError('projection_requires_draft_object')
    projected = deepcopy(value)
    changes = []

    def excerpt_ids(excerpts):
        if not isinstance(excerpts, list) or any(
                not isinstance(e, dict) or not isinstance(e.get('block_id'), str) for e in excerpts):
            raise ValueError('projection_requires_explicit_excerpts')
        return [e['block_id'] for e in excerpts]

    def append_indexes(obj, refs, path, identity, *, allow_context=False):
        before = obj.get('evidence_block_ids')
        if not isinstance(before, list) or any(not isinstance(ref, str) for ref in before):
            raise ValueError('projection_requires_explicit_indexes')
        if not allow_context and set(before) - set(refs):
            raise ValueError('projection_cannot_remove_uncited_indexes')
        missing = list(dict.fromkeys(ref for ref in refs if ref not in before))
        if missing:
            obj['evidence_block_ids'] = before + missing
            changes.append(dict(path=path, **identity, before=before, after=obj['evidence_block_ids'],
                added=missing, operation='derive_missing_index_from_unchanged_excerpt'))

    for collection in ('businesses', 'relationships'):
        if not isinstance(projected.get(collection), list):
            raise ValueError('projection_requires_explicit_businesses_and_relationships')
    for index, node in enumerate(projected['businesses']):
        if not isinstance(node, dict) or not isinstance(node.get('claim_evidence'), list):
            raise ValueError('projection_requires_explicit_claim_evidence')
        refs = []
        for claim in node['claim_evidence']:
            if not isinstance(claim, dict):
                raise ValueError('projection_requires_explicit_claim_evidence')
            refs.extend(excerpt_ids(claim.get('excerpts')))
        append_indexes(node, refs, f'/businesses/{index}/evidence_block_ids', {'node_id': node.get('id')}, allow_context=True)
    for index, relation in enumerate(projected['relationships']):
        if not isinstance(relation, dict):
            raise ValueError('projection_requires_explicit_relationship')
        append_indexes(relation, excerpt_ids(relation.get('excerpts')),
            f'/relationships/{index}/evidence_block_ids',
            {'source_id': relation.get('source_id'), 'target_id': relation.get('target_id')})
    # Validate the complete object, including source scope, quote truth, duplicate
    # entries, block dispositions, attributes and unchanged nested indexes.
    validate_draft(projected, packet, expected_version=expected_version)
    return projected, dict(schema_version='business-evidence-index-projection-v2',
        output_contract_version=expected_version, source_packet_sha256=canonical_hash(packet),
        original_sha256=canonical_hash(value), projected_sha256=canonical_hash(projected),
        changes=changes, claims_and_excerpts_unchanged=True, semantic_acceptance='not_evaluated')
