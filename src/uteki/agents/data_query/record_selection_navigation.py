"""Lossless record-choice metadata and visible delivery effects, without body reads.

This module never chooses records, merges equal values, changes citations, or
claims that source text has been read. ArtifactStore owns bounded projection.
"""
from copy import deepcopy


def atomic_delivery_block_ids(reader, block_id):
    """V4 closure shared by delivery and its metadata preview; no body read."""
    reader.positions[block_id]  # Unknown anchors fail rather than disappear.
    required = {block_id}
    for group in reader.groups:
        if group.get('kind') == 'table_context' and group.get('table_id') == block_id:
            required.update(group['block_ids'])
    layout_roles = {'running_header', 'reported_page_number', 'repeated_navigation', 'table_of_contents'}
    return [b['block_id'] for b in reader.blocks if b['block_id'] in required
            and (b['block_id'] == block_id or
                 (b.get('layout_role') not in layout_roles and b['type'] != 'page_marker'))]


def delivery_projection(port, anchors):
    """Exact scoped V4 block identities, retaining atomic attachments, without text."""
    projected = {}
    for anchor in anchors:
        sid, bid = anchor['source_snapshot_id'], anchor['block_id']
        reader, _ = port._navigation(port._source(sid))
        projected.setdefault(sid, set()).update(atomic_delivery_block_ids(reader, bid))
    return [{'source_snapshot_id': sid, 'block_ids': [b['block_id'] for b in
             port._navigation(port._source(sid))[0].blocks if b['block_id'] in bids]}
            for sid, bids in projected.items()]


_RECORD_FIELDS = ('record_id', 'record_type', 'entity_id', 'metric_id', 'period',
    'value_decimal', 'upper_decimal', 'value_relation', 'value_kind', 'unit',
    'accounting_basis', 'dimensions', 'denominator', 'modality', 'available_at',
    'source_snapshot_id')
_CITATION_FIELDS = ('source_snapshot_id', 'block_id', 'cell', 'char_start', 'char_end')
_ATOMIC_POLICY = ('Each selected record keeps its immutable citation anchors. The handoff assembler '
    'reopens these originals with required atomic table context. Anchors below do not enumerate '
    'all attachments and do not establish that any source body has been read. Explicit source '
    'selections are additive; they never replace a selected record citation.')


def _record(eid, item, origins):
    row = {'evidence_id': eid, **{k: deepcopy(item['value'][k])
           for k in _RECORD_FIELDS if k in item['value']}}
    row['citations'] = [{k: deepcopy(c[k]) for k in ('citation_id', 'role', *_CITATION_FIELDS)
                        if k in c} for c in origins.get(eid, {}).get('citations', [])]
    return row


def _union(records):
    blocks = {}
    for rid, record in records:
        for citation in record['citations']:
            key = citation['source_snapshot_id'], citation['block_id']
            block = blocks.setdefault(key, {'source_snapshot_id': key[0], 'block_id': key[1],
                'record_evidence_ids': [], 'requirement_ids': [], 'citation_roles': []})
            for field, value in (('record_evidence_ids', record['evidence_id']),
                                 ('requirement_ids', rid), ('citation_roles', citation['role'])):
                if value not in block[field]: block[field].append(value)
    return list(blocks.values())


def candidate_index(coverage, evidence, origins, active_scope):
    """Preserve every eligible occurrence and criterion, with no equivalence inference."""
    criteria, candidates, references = [], {}, []
    for rid, row in coverage.items():
        if row['kind'] != 'query': continue
        eligible = [eid for eid in row['evidence_ids'] if eid in origins
                    and evidence[eid]['kind'] == 'record'
                    and evidence[eid]['scope'] == row['query_scope'] == active_scope]
        for index, criterion in enumerate(row['query']['records']):
            matching = [eid for eid in eligible
                        if all(evidence[eid]['value'].get(k) == v for k, v in criterion.items())]
            criteria.append({'requirement_id': rid, 'criterion_index': index,
                'source_id': row.get('source_id'), 'query_scope': deepcopy(row['query_scope']),
                'criterion': deepcopy(criterion), 'candidate_count': len(matching),
                'candidate_evidence_ids': matching})
            for eid in matching:
                record = candidates.setdefault(eid, _record(eid, evidence[eid], origins))
                refs = record.setdefault('criterion_references', [])
                refs.append({'requirement_id': rid, 'criterion_index': index})
                references.append((rid, record))
    # Normalize repeated metadata instead of dropping fields or giving a preferred
    # occurrence more preview space. Full semantics and scopes remain explicit.
    scopes, semantics, compact = [], [], []
    for row in criteria:
        query_scope = row.pop('query_scope')
        if query_scope not in scopes: scopes.append(query_scope)
        row['query_scope_index'] = scopes.index(query_scope)
    for record in candidates.values():
        fields = {k: deepcopy(record[k]) for k in _RECORD_FIELDS
                  if k != 'record_id' and k in record}
        if fields not in semantics: semantics.append(fields)
        compact.append({'evidence_id': record['evidence_id'], 'record_id': record['record_id'],
            'semantics_index': semantics.index(fields), 'citations': record['citations'],
            'criterion_references': record['criterion_references']})
    return {'query_scopes': scopes, 'criteria': criteria, 'record_semantics': semantics,
            'candidates': compact, 'source_blocks': _union(references)}


def selection_effect(coverage, evidence, origins, record_selection, delivery_selection, delivered_body=None):
    """Report both independent selections and their actual union of citation anchors."""
    numeric, records, explicit = [], [], {}
    for rid, eids in record_selection.items():
        row = coverage[rid]
        selected = [_record(eid, evidence[eid], origins) for eid in eids]
        numeric.append({'requirement_id': rid, 'query_scope': deepcopy(row['query_scope']),
            'source_id': row.get('source_id'), 'criteria': deepcopy(row['query']['records']),
            'selected_records': selected})
        records.extend((rid, record) for record in selected)
    for rid, blocks in delivery_selection.items():
        for selected in blocks:
            item = evidence[selected['context_id']]
            key = item['value']['source_snapshot_id'], selected['block_id']
            entry = explicit.setdefault(key, {'source_snapshot_id': key[0], 'block_id': key[1],
                'requirement_ids': [], 'context_evidence_ids': []})
            if rid not in entry['requirement_ids']: entry['requirement_ids'].append(rid)
            if selected['context_id'] not in entry['context_evidence_ids']:
                entry['context_evidence_ids'].append(selected['context_id'])
    declared = {}
    for rid, row in coverage.items():
        if row['kind'] != 'read_node':
            continue
        for eid in row['evidence_ids']:
            item = evidence[eid]
            if (item['kind'] != 'context' or item['value']['source_snapshot_id'] != row['source_id']
                    or item['scope'] != row.get('source_scope', item['scope'])):
                continue
            delivered = (delivered_body or {}).get(eid, [])
            for bid in delivered:
                if bid in row.get('required_block_ids', delivered):
                    sid = item['value']['source_snapshot_id']
                    declared[(sid, bid)] = {'source_snapshot_id': sid, 'block_id': bid}
    record_blocks = _union(records)
    combined = {}
    for kind, rows in (('record_citation', record_blocks), ('explicit_source_selection', explicit.values()),
                       ('declared_node_body', declared.values())):
        for row in rows:
            key = row['source_snapshot_id'], row['block_id']
            entry = combined.setdefault(key, {'source_snapshot_id': key[0], 'block_id': key[1],
                                             'introduced_by': []})
            entry['introduced_by'].append(kind)
    return {'numeric_selections': numeric, 'record_citation_anchors': record_blocks,
            'explicit_source_blocks': list(explicit.values()), 'declared_body_blocks': list(declared.values()),
            'combined_anchor_blocks': list(combined.values())}


def navigation_page(artifacts, kind, value, *, scope, step, max_bytes):
    """Persist complete metadata and expose explicit omissions/continuation pointers."""
    ref = artifacts.put(kind, value, scope=scope, step=step)
    view = artifacts.preview(ref['artifact_id'], max_bytes=max_bytes, limit=1000)
    return {'schema_version': kind + '-v1', 'navigation_only': True,
        'source_body_reading_established': False,
        'atomic_context_policy': _ATOMIC_POLICY,
        'choice_policy': 'No preferred occurrence or equal-value equivalence is inferred; the Agent chooses.',
        'artifact': ref, 'complete': not view['truncated'], **view}
