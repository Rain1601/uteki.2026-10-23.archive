"""Typed brief and two-way self-review. Location checks do not prove semantics."""
from __future__ import annotations

from datetime import date
import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field
from ..business_map.product_contract import Contract, ID, Text

Hash = Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class Task(Contract):
    company_id: ID
    document_id: ID
    period_end: Text
    cutoff: Text
    source_language: Text
    reading_purpose: Text
    reading_mode: Literal['first_read']


class Bilingual(Contract):
    zh: Text
    en: Text


class Excerpt(Contract):
    block_id: ID
    quote: Text


class Item(Contract):
    id: ID
    kind: Literal['reported_fact', 'management_statement', 'forecast_or_target', 'interpretation']
    priority: Literal['must_read', 'watch', 'background']
    priority_reason: Bilingual
    statement: Bilingual
    attribution: Bilingual
    period_scope: Bilingual
    qualifications: list[Bilingual]
    uncertainty: Literal['source_statement', 'conditional', 'inference', 'uncertain']
    excerpts: list[Excerpt] = Field(min_length=1)


class Coverage(Contract):
    block_id: ID
    disposition: Literal['included', 'compressed', 'context', 'layout_noise', 'unprocessed', 'unsupported']
    item_ids: list[ID]
    reason: Bilingual


class Gap(Contract):
    id: ID
    status: Literal['unknown', 'unprocessed', 'unsupported', 'not_disclosed', 'not_applicable']
    question: Bilingual
    explanation: Bilingual
    block_ids: list[ID]
    excerpts: list[Excerpt]


class Brief(Contract):
    schema_version: Literal['filing-brief-v1']
    company_id: ID
    document_id: ID
    period_end: Text
    source_sha256: Hash
    source_packet_sha256: Hash
    task_sha256: Hash
    title: Bilingual
    scope_limitation: Bilingual
    items: list[Item] = Field(min_length=1)
    coverage: list[Coverage] = Field(min_length=1)
    gaps: list[Gap]


class ClaimCheck(Contract):
    item_id: ID
    verdict: Literal['supported', 'partial', 'unsupported', 'scope_mismatch', 'translation_mismatch', 'uncertain']
    rationale: Text


class CoverageCheck(Contract):
    block_id: ID
    verdict: Literal['adequate', 'material_omission', 'uncertain']
    rationale: Text


class GapCheck(Contract):
    gap_id: ID
    verdict: Literal['supported', 'unsupported_absence', 'scope_mismatch', 'uncertain']
    rationale: Text


class Review(Contract):
    schema_version: Literal['filing-brief-review-v1']
    brief_sha256: Hash
    claims: list[ClaimCheck]
    coverage: list[CoverageCheck]
    gaps: list[GapCheck]


def validate_task(value, packet):
    task = Task.model_validate(value)
    for key in ('company_id', 'document_id', 'period_end'):
        if getattr(task, key) != packet.get(key):
            raise ValueError('task_packet_scope_mismatch:' + key)
    if date.fromisoformat(task.cutoff) < date.fromisoformat(task.period_end):
        raise ValueError('cutoff_before_period_end')
    return task.model_dump()


def _exact_ids(actual, expected, name):
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise ValueError(name + '_must_account_exactly_once')


def validate_brief(value, packet, task, packet_sha):
    brief = Brief.model_validate(value)
    blocks = {b['id']: b for b in packet['blocks']}
    for key in ('company_id', 'document_id', 'period_end', 'source_sha256'):
        if getattr(brief, key) != packet[key]:
            raise ValueError('brief_source_scope_mismatch:' + key)
    if brief.source_packet_sha256 != packet_sha or brief.task_sha256 != digest(task):
        raise ValueError('brief_frozen_input_hash_mismatch')
    items = {i.id: i for i in brief.items}
    if len(items) != len(brief.items) or len({g.id for g in brief.gaps}) != len(brief.gaps):
        raise ValueError('duplicate_item_or_gap_id')

    def excerpts(values):
        for ref in values:
            if ref.block_id not in blocks or ' '.join(ref.quote.split()) not in ' '.join(blocks[ref.block_id]['text'].split()):
                raise ValueError('excerpt_not_in_selected_source')
    for item in brief.items:
        excerpts(item.excerpts)
        if item.kind == 'interpretation' and item.uncertainty != 'inference':
            raise ValueError('interpretation_requires_inference_label')
        if item.kind == 'forecast_or_target' and item.uncertainty not in ('conditional', 'uncertain'):
            raise ValueError('forecast_requires_uncertainty_label')
    _exact_ids([c.block_id for c in brief.coverage], blocks, 'coverage')
    missing_links = []
    for row in brief.coverage:
        if len(set(row.item_ids)) != len(row.item_ids) or any(i not in items for i in row.item_ids):
            raise ValueError('coverage_item_id_invalid')
        if row.disposition == 'included' and not row.item_ids:
            raise ValueError('included_block_requires_items')
        if row.disposition in ('unprocessed', 'unsupported', 'layout_noise') and row.item_ids:
            raise ValueError('unprocessed_or_noise_must_not_claim_items')
        for item_id in row.item_ids:
            if row.block_id not in {r.block_id for r in items[item_id].excerpts}:
                missing_links.append(dict(block_id=row.block_id, item_id=item_id))
    if missing_links:
        raise ValueError('coverage_item_requires_same_block_evidence:' + json.dumps(missing_links))
    mapped = {i for row in brief.coverage for i in row.item_ids}
    if mapped != set(items):
        raise ValueError('every_item_requires_coverage_mapping')
    for gap in brief.gaps:
        if not set(gap.block_ids) <= set(blocks):
            raise ValueError('gap_source_out_of_scope')
        excerpts(gap.excerpts)
        if gap.status in ('not_disclosed', 'not_applicable') and not gap.excerpts:
            raise ValueError('absence_assertion_requires_explicit_source_evidence')
        if not {e.block_id for e in gap.excerpts} <= set(gap.block_ids):
            raise ValueError('gap_excerpt_not_bound_to_gap_blocks')
    return brief.model_dump()


def validate_review(value, brief, packet):
    review = Review.model_validate(value)
    if review.brief_sha256 != digest(brief):
        raise ValueError('review_candidate_hash_mismatch')
    _exact_ids([c.item_id for c in review.claims], [i['id'] for i in brief['items']], 'claim_checks')
    _exact_ids([c.block_id for c in review.coverage], [b['id'] for b in packet['blocks']], 'coverage_checks')
    _exact_ids([c.gap_id for c in review.gaps], [g['id'] for g in brief['gaps']], 'gap_checks')
    unresolved = any(c['disposition'] in ('unprocessed', 'unsupported') for c in brief['coverage'])
    value = review.model_dump()
    value['computed_status'] = 'pass' if (not unresolved and all(c.verdict == 'supported' for c in review.claims)
        and all(c.verdict == 'adequate' for c in review.coverage)
        and all(c.verdict == 'supported' for c in review.gaps)) else 'needs_revision'
    value['independent_acceptance'] = False
    return value
