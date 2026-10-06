"""Read-only, explicitly registered direct extraction artifacts.

Hashes prove artifact integrity, not semantic correctness or adoption.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import PurePosixPath

import duckdb

from apps.review_workbench.data.evaluation_artifacts import (
    _path, _json, _hash, _manifest, _ID, _SHA, _public,
)

REGISTRATION = 'data/evaluation_views/direct-extraction-v1.json'
ARTIFACTS = ('result.json', 'job.json', 'prompt.json', 'system-prompt-effective.json',
             'packet.json', 'extraction.json', 'normalized.json', 'dataset/research.duckdb')


def _registered_path(root, relative):
    path = _path(root, relative)
    if PurePosixPath(relative).parts[0] not in {'experiments', 'data'}:
        raise ValueError('Extraction artifacts must be under experiments/ or data/')
    return path


def _registration(root):
    config = _json(_path(root, REGISTRATION))
    if config.get('schema_version') != 'direct-extraction-view-v1' or not isinstance(config.get('runs'), list):
        raise ValueError('Unsupported direct extraction registration')
    ids = set()
    for entry in config['runs']:
        identity = entry.get('id')
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in ids:
            raise ValueError('Invalid or duplicate extraction run ID')
        ids.add(identity)
        _registered_path(root, entry['path'])
        if 'dataset' in entry:
            pin = entry['dataset']
            if (not isinstance(pin, dict) or set(pin) != {'id', 'manifest_sha256'}
                    or not _ID.fullmatch(pin.get('id', '')) or not _SHA.fullmatch(pin.get('manifest_sha256', ''))):
                raise ValueError('Extraction dataset requires an explicit ID and manifest SHA256')
    return config['runs']


def _identity(packet, job):
    if packet is None:
        return {'company_id': job.get('company_id', ''), 'source_snapshot_id': job.get('source_snapshot_id', ''),
                'source_sha256': '', 'period_end': '', 'scope_status': 'packet_missing'}
    source = packet['source']
    company, sid = packet.get('company_id'), source.get('source_snapshot_id')
    if not company or source.get('company_id') != company or not sid or not _SHA.fullmatch(source.get('source_sha256', '')):
        raise ValueError('Explicit matching company, source and source SHA256 required')
    for scope in (job, packet.get('task', {})):
        if scope.get('company_id', company) != company or scope.get('source_snapshot_id', sid) != sid:
            raise ValueError('Job or task company/source mismatch')
        if 'source_snapshot_ids' in scope and sid not in scope['source_snapshot_ids']:
            raise ValueError('Task source is outside packet scope')
    return {'company_id': company, 'source_snapshot_id': sid, 'period_end': source.get('period_end', ''),
            'source_sha256': source['source_sha256'], 'scope_status': 'matched'}


def _load(root, entry):
    folder = _registered_path(root, entry['path'])
    manifest = _manifest(folder, entry['manifest_sha256'])
    artifacts = {name: _json(_path(folder, name)) for name in ARTIFACTS
                 if name.endswith('.json') and name in manifest['files']}
    packet = artifacts.get('packet.json')
    job = artifacts.get('job.json', {})
    scope = _identity(packet, job)
    source_check = 'packet_reference_only'
    if packet and packet['source'].get('raw_file'):
        raw_name = 'dataset/' + packet['source']['raw_file']
        if raw_name in manifest['files']:
            raw_hash = _hash(_path(folder, raw_name))
            if raw_hash != packet['source']['source_sha256'] or raw_hash != packet['source'].get('raw_file_sha256'):
                raise ValueError('Source/raw hash association mismatch or unsupported compressed source')
            source_check = 'raw_file_hash_matches'
    blocks = {}
    if packet:
        for block in packet.get('blocks', []):
            if block['block_id'] in blocks or block.get('source_snapshot_id', scope['source_snapshot_id']) != scope['source_snapshot_id']:
                raise ValueError('Duplicate or cross-source block')
            if hashlib.sha256(block['text'].encode()).hexdigest() != block['text_hash']:
                raise ValueError('Packet block hash mismatch')
            blocks[block['block_id']] = block
    normalized = artifacts.get('normalized.json')
    draft_contexts = []
    for draft in artifacts.get('extraction.json', {}).get('records', []):
        for role in ('evidence', 'qualifiers'):
            for ref in draft.get(role, []):
                block = blocks.get(ref.get('block_id'))
                quote = ref.get('quote', '')
                draft_contexts.append({'draft_id': draft.get('draft_id'), 'role': role, **ref,
                    'quote_found': bool(block and quote and quote in block['text']),
                    'context': block['text'] if block else None,
                    'note': 'Draft evidence only; presence of text does not establish semantic support.'})
    evidence_checks = []
    if normalized is not None:
        if packet is None:
            raise ValueError('Normalized records require their source packet')
        entities = {x['entity_id'] for x in packet.get('entity_catalog', [])}
        for entity in packet.get('entity_catalog', []):
            if (entity.get('company_id', scope['company_id']) != scope['company_id'] or
                    entity.get('source_snapshot_id', scope['source_snapshot_id']) != scope['source_snapshot_id']):
                raise ValueError('Entity catalog outside company/source scope')
        for record in normalized.get('records', []):
            if record.get('source_snapshot_id') != scope['source_snapshot_id'] or record.get('entity_id') not in entities:
                raise ValueError('Normalized record outside company/source scope')
            for field in ('evidence_ids', 'qualifier_evidence_ids', 'question_evidence_ids'):
                if not set(record.get(field, [])) <= normalized.get('evidence', {}).keys():
                    raise ValueError('Normalized record references missing evidence')
        for eid, evidence in normalized.get('evidence', {}).items():
            if (evidence.get('source_snapshot_id') != scope['source_snapshot_id'] or
                    evidence.get('source_sha256') != packet['source']['source_sha256']):
                raise ValueError('Normalized evidence outside source/hash scope')
            block = blocks.get(evidence.get('block_id'))
            if block is None or evidence.get('text_hash') != block['text_hash']:
                raise ValueError('Evidence block identity mismatch')
            start, end = evidence.get('source_start'), evidence.get('source_end')
            if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(block['text']) or block['text'][start:end] != evidence.get('quote'):
                raise ValueError('Evidence quote/offset mismatch')
            evidence_checks.append({'evidence_id': eid, **evidence, 'context': block['text'], 'check': 'exact_quote_and_hash'})
    db_check = 'not_available'
    db_rows = []
    db_name = 'dataset/research.duckdb'
    if db_name in manifest['files']:
        if normalized is None or packet is None:
            raise ValueError('Database requires normalized records and source packet')
        with duckdb.connect(str(_path(folder, db_name)), read_only=True, config={'enable_external_access': False}) as connection:
            for rid, entity, sid, payload in connection.execute('SELECT record_id, entity_id, source_snapshot_id, payload FROM observations').fetchall():
                row = json.loads(payload) if isinstance(payload, str) else payload
                if (row.get('record_id'), row.get('entity_id'), row.get('source_snapshot_id')) != (rid, entity, sid):
                    raise ValueError('Database columns/payload mismatch')
                db_rows.append(row)
            sources = connection.execute('SELECT source_snapshot_id, company_id, payload FROM sources').fetchall()
            if len(sources) != 1 or sources[0][:2] != (scope['source_snapshot_id'], scope['company_id']) or json.loads(sources[0][2]) != packet['source']:
                raise ValueError('Database source differs from packet source')
            db_evidence = {}
            for eid, sid, payload in connection.execute('SELECT evidence_id, source_snapshot_id, payload FROM evidence').fetchall():
                if eid in db_evidence or sid != scope['source_snapshot_id']:
                    raise ValueError('Database evidence identity mismatch')
                db_evidence[eid] = json.loads(payload)
            if db_evidence != normalized.get('evidence', {}):
                raise ValueError('Database evidence payload differs from normalized evidence')
        expected = normalized.get('records', [])
        if len({r['record_id'] for r in db_rows}) != len(db_rows) or sorted(db_rows, key=lambda r: r['record_id']) != sorted(expected, key=lambda r: r['record_id']):
            raise ValueError('Database payload differs from normalized records')
        db_check = 'payload_matches_normalized'
    review = None
    if entry.get('review'):
        ref = entry['review']
        review_path = _registered_path(root, ref['path'])
        if not _SHA.fullmatch(ref.get('sha256', '')) or _hash(review_path) != ref['sha256']:
            raise ValueError('External review integrity mismatch')
        review = _json(review_path)
        if isinstance(review, dict):
            for key, expected in (('run_id', entry['id']), ('company_id', scope['company_id']),
                                  ('source_snapshot_id', scope['source_snapshot_id']),
                                  ('source_sha256', scope['source_sha256'])):
                if key in review and review[key] != expected:
                    raise ValueError('External review scope mismatch: ' + key)
    return {'id': entry['id'], 'path': entry['path'], 'manifest_sha256': entry['manifest_sha256'],
            'dataset': entry.get('dataset'),
            **scope, 'source_check': source_check, 'artifacts': artifacts, 'missing': [n for n in ARTIFACTS if n not in manifest['files']],
            'blocks': list(blocks.values()), 'evidence_checks': evidence_checks, 'draft_contexts': draft_contexts,
            'db_check': db_check, 'db_rows': db_rows, 'review': review,
            'parent_run_id': job.get('parent_run_id') or (packet or {}).get('revision_feedback', {}).get('parent_run_id') or manifest.get('parent_run_id'),
            'integrity': 'verified'}


@_public
def load_catalog(root):
    rows = []
    for entry in _registration(root):
        try:
            run = _load(root, entry)
            rows.append({k: run[k] for k in ('id', 'company_id', 'source_snapshot_id', 'source_sha256', 'period_end', 'missing', 'integrity', 'dataset')})
        except (ValueError, KeyError, TypeError, OSError, duckdb.Error) as error:
            rows.append({'id': entry['id'], 'company_id': '', 'source_snapshot_id': '', 'period_end': '',
                         'source_sha256': '', 'integrity': 'invalid', 'error': str(error), 'missing': [],
                         'dataset': entry.get('dataset')})
    return rows


@_public
def load_run(root, identity):
    matches = [e for e in _registration(root) if e['id'] == identity]
    if len(matches) != 1:
        raise ValueError('Select an explicitly registered extraction run')
    return _load(root, matches[0])


@_public
def dataset_runs(root, dataset):
    """Join only explicit dataset pins and the selected immutable source identity."""
    if not _path(root, REGISTRATION).is_file():
        return {'runs': [], 'gaps': [{'reason': 'extraction_registry_missing'}]}
    sources = {source['source_snapshot_id']: source for source in dataset['sources']}
    matched, gaps = [], []
    for run in load_catalog(root):
        pin = run.get('dataset')
        sid = run['source_snapshot_id']
        if not pin:
            if run['company_id'] == dataset['company']['company_id'] and sid in sources:
                gaps.append({'run_id': run['id'], 'reason': 'dataset_manifest_not_bound'})
            continue
        if pin['id'] != dataset['id']:
            continue
        if (run['integrity'] != 'verified' or pin['manifest_sha256'] != dataset['manifest_sha256']
                or run['company_id'] != dataset['company']['company_id'] or sid not in sources
                or run['source_sha256'] != sources[sid]['source_sha256']):
            gaps.append({'run_id': run['id'], 'reason': 'dataset_or_source_binding_mismatch'})
            continue
        matched.append(run)
    return {'runs': matched, 'gaps': gaps}


@_public
def load_dataset_run(root, dataset, identity, source_id):
    if not source_id or source_id not in {s['source_snapshot_id'] for s in dataset['sources']}:
        raise ValueError('Explicit source in selected dataset required')
    allowed = dataset_runs(root, dataset)['runs']
    if not any(r['id'] == identity and r['source_snapshot_id'] == source_id for r in allowed):
        raise ValueError('Extraction run outside selected dataset/source')
    run = load_run(root, identity)
    source_blocks = {b['block_id']: b for b in dataset['blocks'][source_id]}
    for block in run['blocks']:
        original = source_blocks.get(block['block_id'])
        if original is None or original.get('text_hash') != block['text_hash']:
            raise ValueError('Extraction packet block differs from selected dataset source')
    return run
