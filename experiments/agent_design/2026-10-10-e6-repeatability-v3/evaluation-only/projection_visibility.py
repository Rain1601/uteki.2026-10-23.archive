"""Evaluate delivery identities from SDK-bound content, never artifact disk bodies.

Conservative pagination support: complete root-entry and delivery_block_ids-item
pages emitted by ArtifactStore.read. Child-pointer fragments are not inferred.
This is evaluation-only and must not be imported into runtime Agent code.
"""
from pathlib import Path

VERSION = 'sdk-projection-visibility-v2'


def projection(rows):
    if not isinstance(rows, list):
        return None
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        source, ids = row.get('source_snapshot_id'), row.get('block_ids')
        if not isinstance(source, str) or not source or source in result:
            return None
        if (not isinstance(ids, list) or any(not isinstance(i, str) or not i for i in ids)
                or len(set(ids)) != len(ids)):
            return None
        result[source] = ids
    return result


def visible_projection(packet, query, inputs, binding, relative=str):
    expected = projection([{'source_snapshot_id': d['source_snapshot_id'],
        'block_ids': [b['block_id'] for b in d['blocks']]} for d in packet['source_documents']])
    candidates, states = [], {}
    scope = packet.get('scope')
    query = Path(query).resolve()

    def add(path, value, kind, **details):
        if not isinstance(value, dict) or value.get('delivery_schema_version') != 'selected-originals-v4':
            return
        actual = projection(value.get('delivery_block_ids'))
        if actual is None:
            return
        candidates.append({'input': relative(path), 'projection': actual,
            'matches_final': expected is not None and actual == expected,
            'complete_direct_sdk_value': kind == 'complete_direct_sdk_value',
            'visibility_evidence': kind, **details})

    # Each chain consists only of the selected query's own turns. Sibling queries
    # and delegated workers cannot supply a planner's missing observation.
    selected = sorted(((Path(p), v) for p, v in inputs
        if Path(p).resolve().parent.parent == query), key=lambda row: str(row[0]))
    for path, model_input in selected:
        if not scope or model_input.get('active_scope') != scope:
            continue
        nav = model_input.get('record_selection_effect', {})
        value = nav.get('value')
        # This verdict covers only projection fields. Equality with every final
        # source/block/order proves these fields were fully visible, even when
        # unrelated fields in the navigation preview were omitted.
        add(path, value, 'complete_direct_sdk_value' if nav.get('complete') is True
            else 'direct_sdk_projection_fields')
        ref = nav.get('artifact', {})
        # The artifact identity is navigation metadata already sent to the SDK.
        # Its bytes, path and hash never constitute proof of body visibility.
        if (ref.get('scope') != scope or not ref.get('artifact_id')
                or not ref.get('sha256') or not ref.get('scope_id')):
            continue
        key = (ref['artifact_id'], ref['sha256'], ref['scope_id'], scope['snapshot_id'])
        state = states.setdefault(key, {'schema': None, 'total': None, 'items': {},
                                       'invalid': False, 'inputs': []})
        if isinstance(value, dict) and value.get('delivery_schema_version'):
            schema = value['delivery_schema_version']
            if state['schema'] not in (None, schema): state['invalid'] = True
            state['schema'] = schema

        observation = model_input.get('observation', {})
        # A fresh planner turn legitimately has no preceding tool observation.
        # It contributes no page evidence; direct fields above remain eligible.
        if not isinstance(observation, dict):
            continue
        page = observation.get('result', {})
        if (observation.get('status') != 'tool_returned' or observation.get('preview_truncated') is not False
                or observation.get('artifact') != ref or not isinstance(page, dict)
                or any(page.get(k) != v for k, v in zip(
                    ('artifact_id', 'sha256', 'scope_id', 'snapshot_id'), key))):
            continue
        start, end, total = (page.get(k) for k in ('offset', 'end_offset', 'total_count'))
        items = page.get('items')
        if (any(type(n) is not int for n in (start, end, total)) or not 0 <= start <= end <= total
                or not isinstance(items, list) or len(items) != end - start
                or page.get('returned_count') != len(items) or page.get('gaps') != []
                or page.get('status') != ('read' if end == total else 'limited')):
            continue
        cursor = page.get('next_cursor')
        if end == total:
            if cursor is not None: continue
        elif (not isinstance(cursor, dict) or cursor.get('offset') != end
                or cursor.get('pointer') != page.get('pointer')
                or any(cursor.get(k) != v for k, v in zip(
                    ('artifact_id', 'sha256', 'scope_id', 'snapshot_id'), key))):
            continue
        state['inputs'].append(relative(path))
        if page.get('pointer') == '' and page.get('unit') == 'entries':
            # Entry values are atomic in ArtifactStore.read. A returned complete
            # field is evidence even if other root fields need another page.
            fields = {i['key']: i['value'] for i in items
                      if isinstance(i, dict) and 'key' in i and 'value' in i}
            if len(fields) != len(items): continue
            if 'delivery_schema_version' in fields:
                if state['schema'] not in (None, fields['delivery_schema_version']): state['invalid'] = True
                state['schema'] = fields['delivery_schema_version']
            if 'delivery_block_ids' in fields:
                rows = fields['delivery_block_ids']
                if not isinstance(rows, list): continue
                if state['total'] not in (None, len(rows)): state['invalid'] = True
                state['total'] = len(rows)
                for i, row in enumerate(rows):
                    if i in state['items'] and state['items'][i] != row: state['invalid'] = True
                    state['items'][i] = row
        elif page.get('pointer') == '/delivery_block_ids' and page.get('unit') == 'items':
            if state['total'] not in (None, total): state['invalid'] = True
            state['total'] = total
            for i, row in enumerate(items, start):
                if i in state['items'] and state['items'][i] != row: state['invalid'] = True
                state['items'][i] = row
        else:
            continue
        if (not state['invalid'] and state['total'] is not None
                and set(state['items']) == set(range(state['total']))):
            add(path, {'delivery_schema_version': state['schema'],
                       'delivery_block_ids': [state['items'][i] for i in range(state['total'])]},
                'complete_sdk_artifact_pages', artifact_id=ref['artifact_id'],
                page_inputs=list(dict.fromkeys(state['inputs'])))
    matches = [row for row in candidates if row['matches_final']]
    return {'verdict': 'pass' if matches and binding['verdict'] == 'pass' else 'fail',
        'visibility_policy_version': VERSION, 'sdk_binding_verdict': binding['verdict'],
        'expected_full_final_block_ids': expected, 'matching_pre_finish_sdk_inputs': matches,
        'candidate_count': len(candidates),
        'boundary': 'SDK-bound identity/order projection only. Stored files and unread navigation references are not visibility. Exact original body exposure and content acceptance remain separate.',
        'unsupported_visibility_forms': ['child-pointer fragment reconstruction']}
