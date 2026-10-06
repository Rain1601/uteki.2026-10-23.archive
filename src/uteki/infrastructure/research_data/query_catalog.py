"""Small catalog projections over the existing scoped, read-only query port."""
import json

from uteki.domain.research_data.query_catalog import CatalogRequest, SchemaProbeRequest
from .financial_records import digest


def _bytes(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def _page(port, operation, request, items):
    filters = request.model_dump(mode='json', exclude={'cursor', 'limit', 'max_bytes'})
    binding = {'snapshot_id': port.snapshot_id, 'scope_id': port.scope_id,
               'filter_hash': digest([operation, filters]), 'content_hash': digest(items)}

    def cursor(offset):
        value = {'version': 'query-catalog-cursor-v1', **binding, 'offset': offset}
        return {**value, 'checksum': digest(value)}

    offset = 0
    if request.cursor is not None:
        offset = request.cursor.offset
        if request.cursor.model_dump(mode='json') != cursor(offset) or offset >= len(items):
            raise ValueError('catalog cursor does not match scope, filters, content or position')
    returned, gaps = [], []
    while offset < len(items) and len(returned) < request.limit:
        item = items[offset]
        required = _bytes([item])
        if required > request.max_bytes:
            gaps.append({'reason': 'item_too_large', 'item_id': item['item_id'], 'required_bytes': required,
                         'retry': {'operation': operation, 'cursor': cursor(offset),
                                   'filters': filters, 'max_bytes_required': required}})
            break
        if _bytes([*returned, item]) > request.max_bytes:
            break
        returned.append(item)
        offset += 1
    return {'status': 'item_too_large' if gaps and not returned else 'limited' if offset < len(items) else 'complete',
            'snapshot_id': port.snapshot_id, 'scope_id': port.scope_id, 'items': returned,
            'returned_count': len(returned), 'total_count': len(items), 'bytes_returned': _bytes(returned),
            'byte_budget_scope': 'items_json_utf8', 'next_cursor': cursor(offset) if offset < len(items) else None,
            'gaps': gaps}


def _view(port, source_ids=()):
    scope = port.scope
    available = {s['source_snapshot_id']: s for s in port.sources if s['available_at'] <= str(scope.knowledge_cutoff)}
    if set(source_ids) - available.keys():
        raise ValueError('probe source is outside available execution scope')
    sources = [available[sid] for sid in sorted(source_ids or available)]
    selected = {s['source_snapshot_id'] for s in sources}
    clause, args = port._source_restriction('s.')
    rows = port._db.execute(
        'SELECT o.entity_id, o.metric_id, o.source_snapshot_id, o.payload FROM observations o '
        'JOIN sources s USING(source_snapshot_id) WHERE o.available_at <= ? AND s.available_at <= ? '
        "AND o.status = 'candidate'" + clause + ' ORDER BY o.record_id',
        [scope.knowledge_cutoff, scope.knowledge_cutoff, *args]).fetchall()
    rows = [(entity, metric, sid, json.loads(payload)) for entity, metric, sid, payload in rows if sid in selected]
    entities = {s['company_id']: {'entity_id': s['company_id'], 'company_id': s['company_id'],
                                'source_snapshot_ids': [], 'accounting_bases': [], 'reported_dimensions': []}
                for s in sources}
    for source in sources:
        entities[source['company_id']]['source_snapshot_ids'].append(source['source_snapshot_id'])
    for entity, metric, sid, payload in rows:
        entry = entities.setdefault(entity, {'entity_id': entity, 'company_id': available[sid]['company_id'],
                                            'source_snapshot_ids': [], 'accounting_bases': [], 'reported_dimensions': []})
        if sid not in entry['source_snapshot_ids']:
            entry['source_snapshot_ids'].append(sid)
        if scope.include_candidates:
            for key, value in [('accounting_bases', payload.get('accounting_basis')),
                               ('reported_dimensions', payload.get('dimensions'))]:
                if value and value not in entry[key]:
                    entry[key].append(value)
    return sources, rows, entities


def discover_catalog(port, request):
    request = CatalogRequest.model_validate(request)
    sources, rows, entities = _view(port)
    status = 'available_candidate' if port.scope.include_candidates else 'quality_filtered'
    items = []
    if request.kind == 'sources':
        for source in sources:
            metadata = {k: v for k, v in source.items() if k != 'fiscal_periods' or port.scope.include_candidates}
            items.append({'item_id': source['source_snapshot_id'], 'kind': 'source', 'status': status,
                          'metadata': metadata})
    elif request.kind == 'entities':
        items = [{'item_id': eid, 'kind': 'entity', 'status': status, **entry} for eid, entry in sorted(entities.items())]
    elif request.kind == 'metrics':
        for mid in sorted({metric for _, metric, _, _ in rows}):
            items.append({'item_id': mid, 'kind': 'metric', 'status': status, 'metric_id': mid,
                          'definition': port.metrics[mid],
                          'source_snapshot_ids': sorted({sid for _, metric, sid, _ in rows if metric == mid})})
    elif request.kind == 'fiscal_periods':
        if port.scope.include_candidates:
            for source in sources:
                for period in source.get('fiscal_periods', []):
                    value = {**period, 'company_id': source['company_id'], 'source_snapshot_id': source['source_snapshot_id']}
                    items.append({'item_id': 'fiscal-' + digest(value), 'kind': 'fiscal_period', 'status': status, **value})
    else:
        groups = {}
        for entity, metric, sid, payload in rows:
            value = {'entity_id': entity, 'metric_id': metric, 'source_snapshot_id': sid,
                     'period': payload.get('period'), 'value_kind': payload.get('value_kind'), 'status': status}
            key = 'coverage-' + digest(value)
            entry = groups.setdefault(key, {'item_id': key, 'kind': 'coverage', **value, 'occurrence_count': 0})
            entry['occurrence_count'] += 1
        items = [groups[key] for key in sorted(groups)]
    if request.ids:
        by_id = {item['item_id']: item for item in items}
        if set(request.ids) - by_id.keys():
            raise ValueError('catalog ID is outside available execution scope')
        items = [by_id[key] for key in sorted(set(request.ids))]
    return _page(port, 'discover_catalog', request, items)


def probe_schema(port, request):
    request = SchemaProbeRequest.model_validate(request)
    sources, rows, entities = _view(port, request.source_snapshot_ids)
    metrics = {mid for _, mid, _, _ in rows}
    if set(request.metric_ids) - metrics or set(request.entity_ids) - entities.keys():
        raise ValueError('probe metric/entity is outside available execution scope')
    rows = [row for row in rows if (not request.metric_ids or row[1] in request.metric_ids)
            and (not request.entity_ids or row[0] in request.entity_ids)]
    status = 'available_candidate' if port.scope.include_candidates else 'quality_filtered'
    items = [{'item_id': 'structure', 'kind': 'structure', 'schema_version': port.manifest['schema_version'],
              'query_types': ['records', 'documents', 'registered_calculations'],
              'record_fields': {'entity_id': 'string', 'metric_id': 'string', 'period': 'typed period or null',
                                'value_decimal': 'decimal string or null', 'unit': 'string or null',
                                'accounting_basis': 'string', 'dimensions': 'string map',
                                'source_snapshot_id': 'string', 'evidence_ids': 'string array'},
              'notes': ['No implicit aggregation.', 'Examples do not establish complete coverage.']}]
    for source in sources:
        metadata = {k: v for k, v in source.items() if k != 'fiscal_periods' or port.scope.include_candidates}
        items.append({'item_id': 'source-' + source['source_snapshot_id'], 'kind': 'source', 'status': status,
                      'metadata': metadata})
    for mid in sorted({row[1] for row in rows}):
        items.append({'item_id': 'metric-' + mid, 'kind': 'metric', 'status': status, 'metric_id': mid,
                      'definition': port.metrics[mid], 'source_snapshot_ids': sorted({r[2] for r in rows if r[1] == mid})})
    for eid in sorted(request.entity_ids or {row[0] for row in rows}):
        items.append({'item_id': 'entity-' + eid, 'kind': 'entity', 'status': status, **entities[eid]})
    if port.scope.include_candidates:
        for source in sources:
            for period in source.get('fiscal_periods', []):
                value = {**period, 'company_id': source['company_id'], 'source_snapshot_id': source['source_snapshot_id']}
                items.append({'item_id': 'fiscal-' + digest(value), 'kind': 'fiscal_period', **value})
        # One deterministic example per entity/metric/source; value and evidence
        # are taken from exactly the same selected observation, never a global sample.
        seen = set()
        for entity, metric, sid, payload in rows:
            key = (entity, metric, sid)
            if key in seen:
                continue
            seen.add(key)
            items.append({'item_id': 'example-' + digest([sid, payload['record_id']]), 'kind': 'example',
                          'status': payload['status'], 'source_snapshot_id': sid, 'entity_id': entity,
                          'metric_id': metric, 'period': payload['period'], 'record': payload})
    return _page(port, 'probe_schema', request, items)
