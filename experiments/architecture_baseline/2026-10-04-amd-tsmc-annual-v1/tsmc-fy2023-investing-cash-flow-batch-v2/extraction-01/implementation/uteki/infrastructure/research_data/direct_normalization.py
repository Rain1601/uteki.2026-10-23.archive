"""Source-bound normalization of explicit direct-extraction drafts, without model calls."""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
import re

from uteki.domain.research_data.direct_extraction import DirectExtraction, DraftEvidence
from uteki.domain.research_data.query_contract import Period, ResearchRecord, SOURCE_PERIOD_VERSION, SUPPORTED_VERSIONS, validate_period_version
from .financial_records import digest

NORMALIZATION_VERSION = 'direct-normalization-v2'
UNITS = {'USD': ('USD', 1), 'USD_thousands': ('USD', 1000),
         'USD_millions': ('USD', 1000000), 'USD_billions': ('USD', 1000000000),
         'TWD': ('TWD', 1), 'TWD_thousands': ('TWD', 1000),
         'TWD_millions': ('TWD', 1000000), 'TWD_billions': ('TWD', 1000000000),
         'percent': ('percent', 1), 'years': ('years', 1), 'count': ('count', 1),
         'shares': ('shares', 1), 'shares_thousands': ('shares', 1000),
         'shares_millions': ('shares', 1000000)}
ACCOUNTING_BASES = {'reported', 'reported_consolidated', 'reported_dimensioned',
                    'management_guidance', 'attributed_statement'}


def _occurrences(source_id, block, quote):
    results, start = [], 0
    while quote and (start := block['text'].find(quote, start)) >= 0:
        end = start + len(quote)
        results.append({'occurrence_id': 'occ-'+digest([source_id, block['block_id'], block['text_hash'], start, end])[:24],
                        'source_start': start, 'source_end': end, 'quote': quote,
                        'context': block['text'][max(0, start-80):min(len(block['text']), end+80)]})
        start += 1
    return results


def _catalog(items, key, source):
    result = {}
    for item in items:
        identifier = item.get(key)
        if not isinstance(identifier, str) or not identifier.strip() or identifier in result:
            raise ValueError('missing or duplicate explicit catalog identity')
        if item.get('company_id', source['company_id']) != source['company_id'] or item.get(
                'source_snapshot_id', source['source_snapshot_id']) != source['source_snapshot_id']:
            raise ValueError('catalog outside source scope')
        result[identifier] = item
    return result


def _matches(raw, spec):
    names = [spec.get('label'), spec.get('name'), *spec.get('aliases', [])]
    return isinstance(raw, str) and raw.strip().casefold() in {
        name.strip().casefold() for name in names if isinstance(name, str) and name.strip()}


def _decimal(raw):
    # Table layout may separate an accounting parenthesis from its numeral.
    # Preserve the original literal and exact evidence; only parsing may ignore
    # horizontal padding at the inside edges, never between numeral digits.
    number = r'(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?'
    padding = r'[ \t\u00a0]*'
    if not isinstance(raw, str) or not re.fullmatch(r'(?:-?' + number + r'|\(' + padding + number + padding + r'\))', raw.strip()):
        raise ValueError('unsupported_numeric_literal')
    raw = raw.strip().replace(',', '')
    return Decimal('-'+raw[1:-1].strip(' \t\u00a0') if raw.startswith('(') else raw)


def validate_source_mapping_binding(binding, source, blocks, dataset_manifest_sha256, metrics):
    """An explicitly selected contextual alias cannot escape its reviewed input."""
    if binding is None:
        return {}
    fields = {'adapter_id', 'company_id', 'source_snapshot_id', 'source_sha256',
              'dataset_manifest_sha256', 'block_hashes', 'metric_contexts'}
    if (not isinstance(binding, dict) or set(binding) != fields
            or not isinstance(binding['adapter_id'], str) or not binding['adapter_id'].strip()):
        raise ValueError('source-bound mapping requires explicit identity and complete binding')
    expected = {key: source.get(key) for key in ('company_id', 'source_snapshot_id', 'source_sha256')}
    expected['dataset_manifest_sha256'] = dataset_manifest_sha256
    if any(not value or binding[key] != value for key, value in expected.items()):
        raise ValueError('source-bound mapping source or dataset mismatch')
    actual = {block['block_id']: block['text_hash'] for block in blocks}
    if not actual or binding['block_hashes'] != actual:
        raise ValueError('source-bound mapping delivered block hashes mismatch')
    contexts = binding['metric_contexts']
    if not isinstance(contexts, dict) or not contexts or not set(contexts) <= set(metrics):
        raise ValueError('source-bound mapping requires known contextual metrics')
    lookup = {b['block_id']: b for b in blocks}
    for requirements in contexts.values():
        if not isinstance(requirements, list) or not requirements:
            raise ValueError('source-bound mapping requires evidence context')
        for ref in requirements:
            if (not isinstance(ref, dict) or set(ref) != {'block_id', 'quote'}
                    or ref.get('block_id') not in lookup or not isinstance(ref.get('quote'), str)
                    or not ref['quote'].strip() or ref['quote'] not in lookup[ref['block_id']]['text']):
                raise ValueError('source-bound mapping context is absent from delivered source')
    return contexts


def normalize_direct_candidates(extraction, packet):
    """Return candidate records and unresolved drafts; never mutate the source packet.

    Catalog IDs and source scope must be explicit. Host-generated occurrence IDs
    disambiguate repeated quotes; model-supplied offsets are not part of the schema.
    Source positioning is an engineering check, not a semantic acceptance decision.
    """
    original = extraction.model_dump(mode='json') if isinstance(extraction, DirectExtraction) else deepcopy(extraction)
    parsed = DirectExtraction.model_validate(original)
    source = packet['source']
    record_version = packet.get('record_schema_version', SOURCE_PERIOD_VERSION)
    if record_version not in SUPPORTED_VERSIONS:
        raise ValueError('unsupported direct record schema version')
    if not packet.get('packet_id') or not packet.get('company_id') or source.get('company_id') != packet['company_id']:
        raise ValueError('explicit matching packet/source company required')
    sid = source.get('source_snapshot_id')
    if not sid or not re.fullmatch('[0-9a-f]{64}', source.get('source_sha256', '')):
        raise ValueError('explicit source identity and SHA256 required')
    available = date.fromisoformat(source['available_at'])
    task = packet.get('task')
    if not isinstance(task, dict): raise ValueError('explicit extraction task required')
    if task.get('company_id', packet['company_id']) != packet['company_id']:
        raise ValueError('task company mismatch')
    if 'source_snapshot_ids' in task and sid not in task['source_snapshot_ids']:
        raise ValueError('task source mismatch')
    if task.get('knowledge_cutoff') and available > date.fromisoformat(task['knowledge_cutoff']):
        raise ValueError('source after extraction cutoff')
    blocks = {}
    for block in packet['blocks']:
        if block['block_id'] in blocks or block.get('source_snapshot_id', sid) != sid:
            raise ValueError('duplicate or cross-source block')
        if digest(block['text'].encode()) != block['text_hash']:
            raise ValueError('source block hash mismatch')
        blocks[block['block_id']] = block
    entities = _catalog(packet['entity_catalog'], 'entity_id', source)
    metrics = _catalog([{**v, 'metric_id': k} for k, v in packet['metric_catalog'].items()], 'metric_id', source)
    if any(v.get('metric_id', k) != k for k, v in packet['metric_catalog'].items()):
        raise ValueError('metric catalog identity mismatch')
    metric_contexts = validate_source_mapping_binding(packet.get('source_bound_normalization'),
        source, list(blocks.values()), packet.get('dataset_manifest_sha256'), metrics)
    periods = _catalog(packet['period_catalog'], 'period_id', source)
    for spec in periods.values():
        validate_period_version(Period.model_validate(spec['period']), record_version)
    draft_ids = [r.draft_id for r in parsed.records]
    if len(set(draft_ids)) != len(draft_ids): raise ValueError('duplicate draft identity')
    relation_ids = [r.relation_id for r in parsed.relations]
    if len(set(relation_ids)) != len(relation_ids): raise ValueError('duplicate relation identity')
    records, evidence, unresolved, relations, mapped = [], {}, [], [], {}

    def issue(owner, reason, **details):
        unresolved.append({'draft_id': owner, 'reason': reason, **details})

    def bind(ref, owner):
        block = blocks.get(ref.block_id)
        if not block or not ref.quote.strip():
            issue(owner, 'missing_or_invalid_evidence_block', block_id=ref.block_id); return None
        positions = _occurrences(sid, block, ref.quote)
        selected = [p for p in positions if p['occurrence_id'] == ref.occurrence_id] if ref.occurrence_id else positions
        if len(selected) != 1:
            issue(owner, 'ambiguous_quote' if len(positions)>1 and not ref.occurrence_id else 'unlocated_quote',
                  block_id=ref.block_id, quote=ref.quote, occurrences=positions); return None
        span = selected[0]
        eid = 'ev-'+digest([sid, block['block_id'], block['text_hash'], span['source_start'], span['source_end']])[:24]
        evidence[eid] = {'evidence_id': eid, 'source_snapshot_id': sid, 'source_sha256': source['source_sha256'],
                         'source_url': source['source_url'], 'block_id': block['block_id'], 'text_hash': block['text_hash'],
                         'quote': block['text'][span['source_start']:span['source_end']],
                         'source_start': span['source_start'], 'source_end': span['source_end'],
                         'occurrence_id': span['occurrence_id']}
        for key in ('index_id', 'dom_path', 'page_number'):
            if key in block: evidence[eid][key] = block[key]
            elif key in source: evidence[eid][key] = source[key]
        return eid

    for draft in parsed.records:
        before = len(unresolved)
        eid = [bind(ref, draft.draft_id) for ref in draft.evidence]
        qid = [bind(ref, draft.draft_id) for ref in draft.qualifiers]
        questions = []
        if not eid: issue(draft.draft_id, 'missing_evidence')
        for bid in draft.question_refs:
            block = blocks.get(bid)
            if block is None or block.get('speaker_role') != 'analyst':
                issue(draft.draft_id, 'invalid_question_reference', block_id=bid)
            else:
                questions.append(bind(DraftEvidence(block_id=bid, quote=block['text']), draft.draft_id))
        for ref in draft.evidence:
            block = blocks.get(ref.block_id, {})
            if block.get('speaker_role') == 'analyst': issue(draft.draft_id, 'analyst_question_as_fact')
            if block.get('speaker') and draft.speaker != block['speaker']: issue(draft.draft_id, 'speaker_mismatch')
        for field, identifier, raw, catalog in [('entity', draft.entity_id, draft.entity, entities),
                ('metric', draft.metric_id, draft.metric, metrics), ('period', draft.period_id, draft.period, periods)]:
            if identifier not in catalog or not _matches(raw, catalog[identifier]):
                issue(draft.draft_id, 'unresolved_'+field, raw=raw, selected_id=identifier)
        for required in metric_contexts.get(draft.metric_id, []):
            if not any(ref.block_id == required['block_id'] and required['quote'] in ref.quote
                       for ref in [*draft.evidence, *draft.qualifiers]):
                issue(draft.draft_id, 'missing_required_mapping_context', **required)
        if draft.accounting_basis not in ACCOUNTING_BASES: issue(draft.draft_id, 'unsupported_accounting_basis')
        dimensions = entities.get(draft.entity_id, {}).get('dimensions', {})
        if not isinstance(dimensions, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in dimensions.items()):
            raise ValueError('entity catalog dimensions must be explicit string mappings')
        if draft.accounting_basis == 'reported_dimensioned' and not dimensions:
            issue(draft.draft_id, 'unresolved_dimensions')
        if draft.accounting_basis == 'reported_consolidated' and (draft.entity_id != source['company_id'] or dimensions):
            issue(draft.draft_id, 'consolidated_entity_scope_mismatch')
        if draft.unresolved_fields: issue(draft.draft_id, 'model_unresolved_fields', fields=draft.unresolved_fields)
        value, upper, unit = None, None, None
        if draft.value_relation == 'unresolved': issue(draft.draft_id, 'unresolved_value')
        elif draft.value_relation == 'qualitative':
            if draft.value is not None or draft.upper is not None: issue(draft.draft_id, 'qualitative_has_number')
            if draft.unit is not None: issue(draft.draft_id, 'qualitative_has_unit')
        else:
            if draft.unit not in UNITS: issue(draft.draft_id, 'unsupported_unit', unit=draft.unit)
            else:
                unit, factor = UNITS[draft.unit]
                metric = metrics.get(draft.metric_id, {})
                if metric.get('unit') != unit: issue(draft.draft_id, 'metric_unit_mismatch')
                if unit == 'percent' and (not draft.denominator or metric.get('denominator') != draft.denominator):
                    issue(draft.draft_id, 'unresolved_percent_denominator')
                try:
                    with localcontext() as context:
                        context.prec = 60
                        value = format(_decimal(draft.value)*factor, 'f')
                        upper = format(_decimal(draft.upper)*factor, 'f') if draft.upper is not None else None
                    for raw in (draft.value, draft.upper):
                        if raw is not None and not any(re.search(r'(?<![\d.,])'+re.escape(raw.strip())+r'(?![\d.,])', ref.quote) for ref in draft.evidence):
                            issue(draft.draft_id, 'numeric_literal_not_in_evidence', raw=raw)
                except ValueError as error: issue(draft.draft_id, str(error))
        if len(unresolved) != before: continue
        try:
            record = ResearchRecord(schema_version=record_version,
                record_id='direct-'+digest([packet['packet_id'], draft.model_dump(mode='json'), NORMALIZATION_VERSION])[:24],
                record_type={'financial': 'metric', 'guidance': 'guidance', 'statement': 'statement'}[draft.kind],
                entity_id=draft.entity_id, metric_id=draft.metric_id, period=Period.model_validate(periods[draft.period_id]['period']),
                value_kind={'financial': 'actual', 'guidance': 'management_guidance', 'statement': 'attributed_statement'}[draft.kind],
                value_decimal=value, upper_decimal=upper, value_relation=draft.value_relation, unit=unit,
                denominator=draft.denominator, accounting_basis=draft.accounting_basis, dimensions=dimensions, available_at=available,
                source_snapshot_id=sid, evidence_ids=tuple(eid), qualifier_evidence_ids=tuple(qid),
                question_evidence_ids=tuple(questions), summary=draft.summary, speaker=draft.speaker,
                origin={'adapter': NORMALIZATION_VERSION, 'packet_id': packet['packet_id'], 'draft_id': draft.draft_id,
                        'raw': draft.model_dump(mode='json')}, normalization_notes=('Host source and format checks only; semantic acceptance pending.',))
        except ValueError:
            issue(draft.draft_id, 'research_record_contract_rejected'); continue
        records.append(record.model_dump(mode='json')); mapped[draft.draft_id] = record.record_id
    for relation in parsed.relations:
        before = len(unresolved)
        refs = [bind(ref, relation.relation_id) for ref in relation.evidence]
        if not refs: issue(relation.relation_id, 'missing_relation_evidence')
        if len(set(relation.record_ids)) != len(relation.record_ids) or not set(relation.record_ids) <= set(draft_ids):
            issue(relation.relation_id, 'invalid_relation_record_scope')
        resolved = len(unresolved) == before and all(rid in mapped for rid in relation.record_ids)
        if not resolved and len(unresolved) == before: issue(relation.relation_id, 'relation_targets_unresolved')
        relations.append({**relation.model_dump(mode='json'), 'status': 'candidate' if resolved else 'unresolved',
                          'normalized_record_ids': [mapped[rid] for rid in relation.record_ids if rid in mapped],
                          'evidence_ids': [ref for ref in refs if ref is not None]})
    return {'records': records, 'evidence': evidence, 'raw_candidates': deepcopy(original.get('records', [])),
            'relations': relations, 'unresolved': unresolved,
            'validation': {'normalization_version': NORMALIZATION_VERSION, 'status': 'partial' if unresolved or parsed.gaps else 'source_validated',
                           'input_records': len(parsed.records), 'normalized_records': len(records),
                           'model_gaps': list(parsed.gaps), 'semantic_acceptance': 'not_evaluated', 'adoption': 'unchanged_candidate'}}
