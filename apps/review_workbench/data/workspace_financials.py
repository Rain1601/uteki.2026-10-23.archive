"""Read-only financial tables for explicitly selected, validated artifacts.

This is a presentation adapter, not a selection, reconciliation or adoption
engine. Every supplied candidate survives; incompatible scopes get separate
rows, and disagreeing values occupy the same cell without a preferred value.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _identity(prefix, value):
    return prefix + hashlib.sha256(_json(value).encode()).hexdigest()[:24]


def _required(mapping, key):
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Explicit financial ' + key + ' required')
    return value


def _decimal(value):
    """Keep source decimal spelling and precision; never pass through float."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError('Financial values must be exact decimal strings or integers')
    text = str(value)
    try:
        number = Decimal(text)
    except InvalidOperation as error:
        raise ValueError('Invalid financial decimal') from error
    if not number.is_finite():
        raise ValueError('Non-finite financial decimal')
    return text


def _display_decimal(value):
    """Group integer digits without quantizing or changing stored precision."""
    whole, point, fraction = format(Decimal(value), ',f').partition('.')
    fraction = fraction.rstrip('0')
    return whole + (point + fraction if fraction else '')


def _period(record, context):
    raw = record.get('period')
    if not isinstance(raw, dict) or not raw.get('kind') or not raw.get('end'):
        return {'id': _identity('period-', [context, record['record_id'], raw]),
                'kind': None, 'start': None, 'end': None, 'basis': None,
                'label': '期间未解析 / Unresolved period', 'raw': deepcopy(raw),
                'resolved': False}
    period = deepcopy(raw)
    label = (str(raw['start']) + ' — ' if raw.get('start') else '') + str(raw['end'])
    label += ' · ' + ' / '.join(str(raw[k]) for k in ('kind', 'basis') if raw.get(k))
    return {**period, 'id': _identity('period-', raw), 'start': raw.get('start'),
            'basis': raw.get('basis'), 'label': label, 'resolved': True}


def _scope(record, company_id, definition):
    # Missing metadata remains missing. In particular, do not borrow a source
    # presentation currency for a per-share, percentage or foreign-currency fact.
    fields = ('entity_id', 'metric_id', 'unit', 'currency', 'value_scale',
              'accounting_basis', 'dimensions', 'denominator', 'value_kind',
              'record_type', 'modality', 'speaker')
    scope = {key: deepcopy(record.get(key)) for key in fields}
    for key in ('currency', 'value_scale'):
        if key not in record and key in definition:
            scope[key] = deepcopy(definition[key])
    scope['company_id'] = company_id
    # A metric ID alone does not establish that two definition versions mean
    # the same thing. Retain the registered definition in the grouping key.
    scope['metric_definition'] = deepcopy(definition)
    return scope


def _refs(record, field, evidence, source_id, source_sha):
    refs = []
    for identity in record.get(field, []):
        ref = evidence.get(identity)
        if not isinstance(ref, dict):
            raise ValueError('Financial record references missing evidence')
        if ref.get('source_snapshot_id') != source_id or ref.get('source_sha256') != source_sha:
            raise ValueError('Financial evidence outside selected source/hash')
        if ref.get('evidence_id', identity) != identity:
            raise ValueError('Financial evidence identity mismatch')
        refs.append(deepcopy(ref))
    return refs


def _review(run, record, gaps):
    review = run.get('review')
    if review is None:
        return None
    expected = {'run_id': run['id'], 'company_id': run['company_id'],
                'source_snapshot_id': run['source_snapshot_id']}
    if (not isinstance(review, dict) or any(review.get(k) != v for k, v in expected.items())
            or review.get('source_sha256', run['source_sha256']) != run['source_sha256']):
        gap = {'run_id': run['id'], 'reason': 'review_binding_mismatch'}
        if gap not in gaps:
            gaps.append(gap)
        return None
    matches = [item for item in review.get('facts', [])
               if isinstance(item, dict) and item.get('record_id') == record['record_id']]
    if len(matches) > 1:
        gaps.append({'run_id': run['id'], 'record_id': record['record_id'],
                     'reason': 'ambiguous_record_review'})
        return None
    return deepcopy(matches[0]) if matches else None


def _candidate(record, context, evidence, review, origin_kind):
    value, upper = _decimal(record.get('value_decimal')), _decimal(record.get('upper_decimal'))
    relation = record.get('value_relation')
    display = _display_decimal(value) if value is not None else '未解析 / Unresolved'
    prefix = {'gt': '> ', 'gte': '≥ ', 'lt': '< ', 'lte': '≤ ', 'approx': '≈ ',
              'eq': '', 'range': ''}.get(relation)
    if prefix is None:
        prefix = '[' + str(relation) + '] ' if relation is not None else ''
    display = prefix + display + (' – ' + _display_decimal(upper) if upper is not None else '')
    source_id, source_sha = context['source_snapshot_id'], context['source_sha256']
    return {'id': _identity('candidate-', [context, record['record_id']]),
            **context, 'record_id': record['record_id'], 'value': value, 'upper': upper,
            'value_relation': relation, 'display_value': display,
            'evidence_refs': _refs(record, 'evidence_ids', evidence, source_id, source_sha),
            'qualifier_refs': _refs(record, 'qualifier_evidence_ids', evidence, source_id, source_sha),
            'question_refs': _refs(record, 'question_evidence_ids', evidence, source_id, source_sha),
            'review_status': review.get('verdict', 'not_reviewed') if review else 'not_reviewed',
            'review': review, 'record_status': record.get('status'), 'origin_kind': origin_kind,
            'raw': deepcopy(record), 'record': deepcopy(record)}


def _cell(candidates):
    if not candidates:
        return {'status': 'missing', 'conflict': False, 'conflict_reasons': [], 'candidates': []}
    reasons = []
    for key in ('value', 'upper', 'value_relation'):
        # Decimal equality ignores formatting (1.0 versus 1.00) without rounding
        # or normalizing the stored candidate value.
        values = {Decimal(c[key]) if key != 'value_relation' and c[key] is not None
                  else c[key] for c in candidates}
        if len(values) > 1:
            reasons.append('different_' + key)
    statuses = {c['review_status'] for c in candidates if c['review_status'] != 'not_reviewed'}
    if len(statuses) > 1:
        reasons.append('different_review_verdicts')
    return {'status': 'conflict' if reasons else 'multiple' if len(candidates) > 1 else 'candidate',
            'conflict': bool(reasons), 'conflict_reasons': reasons, 'candidates': candidates}


def _assemble(items, gaps, run_count):
    groups, periods = {}, {}
    for record, context, metrics, evidence, review, origin_kind in items:
        for key in ('record_id', 'entity_id', 'metric_id', 'source_snapshot_id'):
            _required(record, key)
        if record['source_snapshot_id'] != context['source_snapshot_id']:
            raise ValueError('Financial record outside selected source')
        if record.get('company_id', context['company_id']) != context['company_id']:
            raise ValueError('Financial record outside selected company')
        definition = metrics.get(record['metric_id'], {})
        if not isinstance(definition, dict):
            raise ValueError('Invalid registered metric definition')
        scope = _scope(record, context['company_id'], definition)
        key = _identity('row-', scope)
        label = definition.get('label') or record['metric_id']
        row = groups.setdefault(key, {'id': key, 'label': label, 'scope': scope, 'cells': {}})
        period = _period(record, context)
        periods[period['id']] = period
        if not period['resolved']:
            gaps.append({**context, 'record_id': record['record_id'], 'reason': 'unresolved_period'})
        if record.get('value_decimal') is None:
            gaps.append({**context, 'record_id': record['record_id'], 'reason': 'unresolved_value'})
        candidate = _candidate(record, context, evidence, review, origin_kind)
        row['cells'].setdefault(period['id'], []).append(candidate)
    period_list = sorted(periods.values(), key=lambda p: (p.get('end') or '', p.get('start') or '',
                                                        p.get('kind') or '', p['id']), reverse=True)
    rows = sorted(groups.values(), key=lambda r: (str(r['label']).casefold(), r['id']))
    counts = {'runs': run_count, 'records': len(items), 'candidates': len(items), 'rows': len(rows),
              'periods': len(period_list), 'missing_cells': 0, 'conflict_cells': 0,
              'multiple_cells': 0, 'reviewed_candidates': 0, 'unreviewed_candidates': 0}
    for row in rows:
        row['cells'] = {p['id']: _cell(row['cells'].get(p['id'], [])) for p in period_list}
        for cell in row['cells'].values():
            if cell['status'] in {'missing', 'multiple', 'conflict'}:
                counts[cell['status'] + '_cells'] += 1
            for candidate in cell['candidates']:
                counts['unreviewed_candidates' if candidate['review_status'] == 'not_reviewed'
                       else 'reviewed_candidates'] += 1
    return {'periods': period_list, 'rows': rows, 'gaps': gaps, 'counts': counts}


def build_financial_table(runs):
    """Present every normalized candidate from the supplied selected runs only.

    Callers first resolve runs with ``load_dataset_run``. This function does no
    filesystem or database reads and never substitutes a run with newer data.
    """
    items, gaps, seen = [], [], set()
    runs = list(runs)
    for run in runs:
        for key in ('id', 'company_id', 'source_snapshot_id', 'source_sha256'):
            _required(run, key)
        key = (run['company_id'], run['source_snapshot_id'], run['id'])
        if key in seen:
            raise ValueError('Duplicate selected financial run')
        seen.add(key)
        context = {'run_id': run['id'], 'company_id': run['company_id'],
                   'source_snapshot_id': run['source_snapshot_id'], 'source_sha256': run['source_sha256'],
                   'run_manifest_sha256': run.get('manifest_sha256'), 'dataset': deepcopy(run.get('dataset'))}
        artifacts = run['artifacts']
        normalized = artifacts.get('normalized.json')
        for field, payload in (('extraction_gaps', artifacts.get('extraction.json', {}).get('gaps', [])),
                               ('normalization_unresolved', (normalized or {}).get('unresolved', []))):
            gaps.extend({'run_id': run['id'], 'reason': field, 'detail': deepcopy(item)} for item in payload)
        if normalized is None:
            gaps.append({'run_id': run['id'], 'reason': 'normalized_artifact_missing',
                         'run_status': artifacts.get('result.json', {}).get('status')})
            continue
        records = normalized.get('records', [])
        if not records:
            gaps.append({'run_id': run['id'], 'reason': 'no_normalized_records',
                         'run_status': artifacts.get('result.json', {}).get('status')})
        ids = set()
        for record in records:
            rid = _required(record, 'record_id')
            if rid in ids:
                raise ValueError('Duplicate financial record in selected run')
            ids.add(rid)
            items.append((record, context, artifacts.get('packet.json', {}).get('metric_catalog', {}),
                          normalized.get('evidence', {}), _review(run, record, gaps), 'normalized'))
    return _assemble(items, gaps, len(runs))


def build_dataset_table(dataset, source_id):
    """Explicit base-dataset view, never mixed into selected extraction runs."""
    company_id = _required(dataset['company'], 'company_id')
    sources = [source for source in dataset['sources'] if source.get('source_snapshot_id') == source_id]
    if not isinstance(source_id, str) or not source_id.strip() or len(sources) != 1:
        raise ValueError('Explicit source in selected dataset required')
    source = sources[0]
    if source.get('company_id') != company_id:
        raise ValueError('Financial source outside selected company')
    context = {'run_id': None, 'company_id': company_id, 'source_snapshot_id': source_id,
               'source_sha256': _required(source, 'source_sha256'), 'run_manifest_sha256': None,
               'dataset': {'id': _required(dataset, 'id'), 'manifest_sha256': dataset.get('manifest_sha256')}}
    records = [record for record in dataset['records'] if record.get('source_snapshot_id') == source_id]
    ids = [_required(record, 'record_id') for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate financial record in selected dataset source')
    gaps = [deepcopy(gap) for gap in dataset.get('gaps', [])
            if gap.get('source_snapshot_id') in (None, source_id)]
    if not records:
        gaps.append({'source_snapshot_id': source_id, 'reason': 'no_dataset_records'})
    items = [(record, context, dataset['metrics'], dataset['evidence'], None, 'dataset') for record in records]
    return _assemble(items, gaps, 0)
