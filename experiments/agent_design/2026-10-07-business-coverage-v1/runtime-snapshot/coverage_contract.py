"""Source-only mention inventory and exhaustive, candidate-bound self-audit.

These gates establish accounting and source membership, not semantic truth or
independent completeness. A model still classifies mentions and support.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field

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


class Mapping(Contract):
    mention_id: ID
    disposition: Literal["node", "attribute_deferred", "context_only", "unresolved", "missing"]
    node_ids: list[ID]
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
        elif mapped:
            raise ValueError("non_node_mapping_requires_empty_node_ids")
        if required_mention(mentions[mapping.mention_id]) and mapping.disposition != "node":
            gaps.append(dict(code="required_mention_not_node", mention_id=mapping.mention_id,
                             disposition=mapping.disposition))
        elif mapping.disposition in ("unresolved", "missing"):
            gaps.append(dict(code="mention_" + mapping.disposition, mention_id=mapping.mention_id))
    for node_id in sorted(node_ids - covered_nodes):
        gaps.append(dict(code="node_without_mention_mapping", node_id=node_id))
    for check in audit.checks:
        if check.verdict != "supported":
            gaps.append(dict(code="claim_not_supported", check_key=check.check_key,
                             verdict=check.verdict, rationale=check.rationale))
    return dict(audit.model_dump(), computed_status="needs_revision" if gaps else "pass", gaps=gaps)
