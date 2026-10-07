"""Source-only mention inventory and exhaustive, candidate-bound self-audit.

These gates establish accounting and source membership, not semantic truth or
independent completeness. A model still classifies mentions and support.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .product_contract import Contract, EvidenceExcerptDraft, ID, Text, validate_draft


Hash = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Mention(Contract):
    id: ID
    block_id: ID
    surface: Text
    category: Literal["issuer_entity", "issuer_grouping", "issuer_offering",
                      "generic_capability", "competitor_or_category",
                      "partner_customer", "cross_reference"]
    trigger: Literal["composition", "definition", "self_offering", "other"]
    excerpts: list[EvidenceExcerptDraft] = Field(min_length=1)
    scope_note: Text


class InventoryBlock(Contract):
    block_id: ID
    disposition: Literal["mentions", "context", "layout"]
    reason: Text


class Inventory(Contract):
    schema_version: Literal["business-coverage-inventory-v1"]
    source_packet_sha256: Hash
    mentions: list[Mention]
    blocks: list[InventoryBlock] = Field(min_length=1)


class InventoryRepair(Contract):
    """One source-bound replacement set; the host chooses the eligible IDs."""
    schema_version: Literal["business-coverage-inventory-repair-v1"]
    inventory_sha256: Hash
    source_packet_sha256: Hash
    replacements: list[Mention] = Field(min_length=1)


class Mapping(Contract):
    mention_id: ID
    disposition: Literal["node", "attribute_deferred", "context_only", "unresolved", "missing"]
    node_ids: list[ID] = Field(description=(
        'Confirmed nodes only for disposition node. For unresolved, valid candidate '
        'IDs may identify related possibilities; they never establish coverage. '
        'All other dispositions require an empty list.'))
    rationale: Text


class Check(Contract):
    check_key: ID
    verdict: Literal["supported", "partial", "unsupported", "overstated_basis",
                     "scope_mismatch", "uncertain"]
    rationale: Text


class Audit(Contract):
    schema_version: Literal["business-coverage-audit-v1"]
    candidate_sha256: Hash
    inventory_sha256: Hash
    mappings: list[Mapping]
    checks: list[Check]


def canonical_hash(value) -> str:
    """Hash normalized JSON values; this is deliberately not a raw-file hash."""
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique(values, label):
    values = list(values)
    if len(values) != len(set(values)):
        raise ValueError("duplicate_" + label)
    return set(values)


def _normalized(text):
    return " ".join(text.split())


def required_mention(mention) -> bool:
    """Gate derived from declared category/trigger, not an assertion of truth."""
    if hasattr(mention, "model_dump"):
        mention = mention.model_dump()
    return (mention["category"] == "issuer_entity" or
            (mention["category"] in ("issuer_grouping", "issuer_offering")
             and mention["trigger"] != "other"))


def validate_inventory(value, packet) -> dict:
    inventory = Inventory.model_validate(value)
    if inventory.source_packet_sha256 != canonical_hash(packet):
        raise ValueError("inventory_source_packet_binding_mismatch")
    block_ids = _unique((b["id"] for b in packet["blocks"]), "source_block")
    blocks = {b["id"]: b for b in packet["blocks"]}
    accounted = _unique((b.block_id for b in inventory.blocks), "inventory_block")
    if accounted != block_ids:
        raise ValueError("inventory_block_coverage_mismatch")
    _unique((m.id for m in inventory.mentions), "mention_id")
    mentioned = set()
    for mention in inventory.mentions:
        if mention.block_id not in blocks:
            raise ValueError("mention_block_outside_packet")
        if _normalized(mention.surface) not in _normalized(blocks[mention.block_id]["text"]):
            raise ValueError("mention_surface_not_in_source")
        mentioned.add(mention.block_id)
        _unique(((e.block_id, _normalized(e.quote)) for e in mention.excerpts), "mention_excerpt")
        if mention.block_id not in {e.block_id for e in mention.excerpts}:
            raise ValueError("mention_origin_excerpt_required")
        for excerpt in mention.excerpts:
            if excerpt.block_id not in blocks:
                raise ValueError("mention_excerpt_outside_packet")
            if _normalized(excerpt.quote) not in _normalized(blocks[excerpt.block_id]["text"]):
                raise ValueError("mention_excerpt_not_in_source")
    for block in inventory.blocks:
        if (block.disposition == "mentions") != (block.block_id in mentioned):
            raise ValueError("inventory_block_disposition_mismatch")
    return inventory.model_dump()


def inventory_contract_errors(value, packet) -> dict:
    """Collect contract defects without offering a corrected semantic answer.

    Only literal surface/excerpt faults in an otherwise scoped, complete inventory
    are locally repairable. Schema, identity, membership and block-accounting
    faults need a different bounded action, not a mention patch.
    """
    if hasattr(value, 'model_dump'):
        value = value.model_dump()
    errors = []
    def add(code, path, mention_id=None, *, repairable=False, **details):
        errors.append(dict(code=code, path=list(path), mention_id=mention_id,
                           repairable=repairable, **details))

    def safe_hash(item):
        try:
            return canonical_hash(item)
        except (ValueError, TypeError):
            return None

    result = dict(schema_version='business-coverage-inventory-diagnostics-v1',
        inventory_sha256=safe_hash(value), source_packet_sha256=safe_hash(packet),
        repairable=False, error_mention_ids=[], errors=errors)
    try:
        inventory = Inventory.model_validate(value)
    except ValidationError as error:
        for detail in error.errors(include_input=False, include_url=False, include_context=False):
            path = list(detail['loc'])
            mention_id = None
            if (len(path) > 1 and path[0] == 'mentions' and type(path[1]) is int
                    and isinstance(value, dict) and isinstance(value.get('mentions'), list)
                    and 0 <= path[1] < len(value['mentions'])
                    and isinstance(value['mentions'][path[1]], dict)):
                candidate = value['mentions'][path[1]].get('id')
                mention_id = candidate if isinstance(candidate, str) else None
            add('inventory_schema_invalid', path, mention_id, schema_error_type=detail['type'])
        return result
    if inventory.source_packet_sha256 != result['source_packet_sha256']:
        add('inventory_source_packet_binding_mismatch', ['source_packet_sha256'])
    if (not isinstance(packet, dict) or not isinstance(packet.get('blocks'), list)
            or not packet['blocks'] or any(not isinstance(b, dict)
                or not isinstance(b.get('id'), str) or not b['id']
                or not isinstance(b.get('text'), str) for b in packet['blocks'])):
        add('source_packet_blocks_invalid', ['source_packet', 'blocks'])
        return result
    blocks = {}
    for index, block in enumerate(packet['blocks']):
        if block['id'] in blocks:
            add('duplicate_source_block', ['source_packet', 'blocks', index, 'id'])
        blocks[block['id']] = block
    accounted = set()
    for index, block in enumerate(inventory.blocks):
        if block.block_id in accounted:
            add('duplicate_inventory_block', ['blocks', index, 'block_id'])
        accounted.add(block.block_id)
    if accounted != set(blocks):
        add('inventory_block_coverage_mismatch', ['blocks'],
            missing_block_ids=sorted(set(blocks)-accounted),
            unexpected_block_ids=sorted(accounted-set(blocks)))
    mention_ids, mentioned = set(), set()
    for index, mention in enumerate(inventory.mentions):
        path = ['mentions', index]
        if mention.id in mention_ids:
            add('duplicate_mention_id', path+['id'], mention.id)
        mention_ids.add(mention.id)
        if mention.block_id not in blocks:
            add('mention_block_outside_packet', path+['block_id'], mention.id)
        else:
            mentioned.add(mention.block_id)
            if _normalized(mention.surface) not in _normalized(blocks[mention.block_id]['text']):
                add('mention_surface_not_in_source', path+['surface'], mention.id, repairable=True)
        excerpt_keys = set()
        if mention.block_id not in {e.block_id for e in mention.excerpts}:
            add('mention_origin_excerpt_required', path+['excerpts'], mention.id, repairable=True)
        for excerpt_index, excerpt in enumerate(mention.excerpts):
            excerpt_path = path+['excerpts', excerpt_index]
            key = (excerpt.block_id, _normalized(excerpt.quote))
            if key in excerpt_keys:
                add('duplicate_mention_excerpt', excerpt_path, mention.id, repairable=True)
            excerpt_keys.add(key)
            if excerpt.block_id not in blocks:
                add('mention_excerpt_outside_packet', excerpt_path+['block_id'], mention.id, repairable=True)
            elif _normalized(excerpt.quote) not in _normalized(blocks[excerpt.block_id]['text']):
                add('mention_excerpt_not_in_source', excerpt_path+['quote'], mention.id, repairable=True)
    for index, block in enumerate(inventory.blocks):
        if (block.disposition == 'mentions') != (block.block_id in mentioned):
            add('inventory_block_disposition_mismatch', ['blocks', index, 'disposition'])
    bad_ids = {error['mention_id'] for error in errors if error['repairable']}
    result['error_mention_ids'] = list(dict.fromkeys(m.id for m in inventory.mentions if m.id in bad_ids))
    result['repairable'] = bool(errors) and all(error['repairable'] for error in errors)
    return result


def apply_inventory_repair(value, packet, repair) -> dict:
    """Apply exactly the host-diagnosed mention replacements, then revalidate.

    This is one patch application, not a loop. The execution layer owns the
    one-attempt bound, model input isolation, immutable records and shared budget.
    """
    diagnostics = inventory_contract_errors(value, packet)
    if not diagnostics['repairable']:
        raise ValueError('inventory_not_locally_repairable')
    patch = InventoryRepair.model_validate(repair)
    if patch.inventory_sha256 != diagnostics['inventory_sha256']:
        raise ValueError('inventory_repair_original_binding_mismatch')
    if patch.source_packet_sha256 != diagnostics['source_packet_sha256']:
        raise ValueError('inventory_repair_source_packet_binding_mismatch')
    replacement_ids = _unique((mention.id for mention in patch.replacements), 'inventory_repair_mention')
    if replacement_ids != set(diagnostics['error_mention_ids']):
        raise ValueError('inventory_repair_mention_coverage_mismatch')
    original = Inventory.model_validate(value).model_dump()
    originals = {mention['id']: mention for mention in original['mentions']}
    replacements = {mention.id: mention.model_dump() for mention in patch.replacements}
    for mention_id, replacement in replacements.items():
        # A literal-evidence repair cannot change object identity or classification
        # to make an important issuer object disappear from the required set.
        if any(replacement[field] != originals[mention_id][field]
               for field in ('block_id', 'category', 'trigger', 'scope_note')):
            raise ValueError('inventory_repair_changed_non_evidence_fields')
    original['mentions'] = [replacements.get(mention['id'], mention) for mention in original['mentions']]
    return validate_inventory(original, packet)


def check_targets(draft) -> list[dict]:
    """Enumerate an already validated draft. Keys are scoped to its full hash.

    Evidence is copied from existing candidate claim pointers; the audit model
    cannot substitute easier evidence for the claim it was asked to inspect.
    """
    if hasattr(draft, "model_dump"):
        draft = draft.model_dump()
    nodes = {b["id"]: b for b in draft["businesses"]}
    targets = []
    for node in draft["businesses"]:
        for claim in node["claim_evidence"]:
            field, index = claim["field"], claim["item_index"]
            statement = node[field] if index is None else node[field][index]
            basis = "explicit"
            if field == "monetization":
                basis = statement["basis"]
                statement = statement["description"]
            targets.append(dict(check_key=f"c:{len(targets)}", target_kind="claim",
                node_id=node["id"], node_name=node["name"], field=field, item_index=index,
                statement=statement, excerpts=claim["excerpts"], basis=basis))
    for index, relation in enumerate(draft["relationships"]):
        targets.append(dict(check_key=f"r:{index}", target_kind="relationship",
            relationship_index=index, source_id=relation["source_id"],
            target_id=relation["target_id"], source_name=nodes[relation["source_id"]]["name"],
            target_name=nodes[relation["target_id"]]["name"], kind=relation["kind"],
            statement=relation["description"], rationale=relation["rationale"],
            excerpts=relation["excerpts"], basis=relation["basis"]))
    return targets


def validate_audit(value, packet, inventory, draft) -> dict:
    """Reject invalid accounting; retain semantic failures as needs_revision."""
    inventory = validate_inventory(inventory, packet)
    draft = validate_draft(draft, packet).model_dump()
    audit = Audit.model_validate(value)
    if audit.candidate_sha256 != canonical_hash(draft):
        raise ValueError("audit_candidate_binding_mismatch")
    if audit.inventory_sha256 != canonical_hash(inventory):
        raise ValueError("audit_inventory_binding_mismatch")
    mentions = {m["id"]: m for m in inventory["mentions"]}
    node_ids = {b["id"] for b in draft["businesses"]}
    if _unique((m.mention_id for m in audit.mappings), "mapping") != set(mentions):
        raise ValueError("audit_mapping_coverage_mismatch")
    expected = {t["check_key"] for t in check_targets(draft)}
    if _unique((c.check_key for c in audit.checks), "check") != expected:
        raise ValueError("audit_check_coverage_mismatch")
    gaps, covered_nodes = [], set()
    for mapping in audit.mappings:
        mapped = _unique(mapping.node_ids, "mapping_node")
        if not mapped <= node_ids:
            raise ValueError("mapping_node_outside_candidate")
        if mapping.disposition == "node":
            if not mapped:
                raise ValueError("node_mapping_requires_node_ids")
            covered_nodes.update(mapped)
            if mentions[mapping.mention_id]["category"] not in (
                    "issuer_entity", "issuer_grouping", "issuer_offering"):
                gaps.append(dict(code="non_issuer_mention_mapped_as_business_node",
                                 mention_id=mapping.mention_id,
                                 category=mentions[mapping.mention_id]["category"]))
        elif mapped and mapping.disposition != 'unresolved':
            raise ValueError("non_node_mapping_requires_empty_node_ids")
        if required_mention(mentions[mapping.mention_id]) and mapping.disposition != "node":
            gap = dict(code="required_mention_not_node", mention_id=mapping.mention_id,
                       disposition=mapping.disposition)
            if mapping.disposition == 'unresolved':
                gap['related_node_ids'] = list(mapping.node_ids)
            gaps.append(gap)
        elif mapping.disposition in ("unresolved", "missing"):
            gap = dict(code="mention_" + mapping.disposition, mention_id=mapping.mention_id)
            if mapping.disposition == 'unresolved':
                gap['related_node_ids'] = list(mapping.node_ids)
            gaps.append(gap)
    for node_id in sorted(node_ids - covered_nodes):
        gaps.append(dict(code="node_without_mention_mapping", node_id=node_id))
    for check in audit.checks:
        if check.verdict != "supported":
            gaps.append(dict(code="claim_not_supported", check_key=check.check_key,
                             verdict=check.verdict, rationale=check.rationale))
    return dict(audit.model_dump(), computed_status="needs_revision" if gaps else "pass", gaps=gaps)
