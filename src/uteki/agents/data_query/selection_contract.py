"""Validate explicit source selections before any delivery state is mutated."""
from uteki.infrastructure.research_data.financial_records import digest


class SelectionContractError(ValueError):
    def __init__(self, code, guidance, **details):
        super().__init__(guidance)
        self.diagnostic = {'code': code, 'action': 'select_evidence',
                           'action_accepted': False, 'guidance': guidance, **details}


def validate_source_selection(refs, selected, coverage, evidence, delivered_blocks):
    """A list is broadcast to each requirement, never implicitly partitioned."""
    groups = {}
    for rid in refs:
        row = coverage[rid]
        key = (row['source_id'], digest(row['source_scope']))
        group = groups.setdefault(key, {'source_id': row['source_id'],
            'scope_id': key[1], 'requirement_ids': []})
        group['requirement_ids'].append(rid)
    if len(groups) != 1:
        raise SelectionContractError('selection_requirement_scope_mismatch',
            'One select_evidence action applies the same block list to every requirement_id. '
            'Issue separate actions for different source/scope groups; choose the relevant fully '
            'read blocks for each group yourself. No selection changed; no reread is implied.',
            requirement_groups=list(groups.values()))
    if len({(b['context_id'], b['block_id']) for b in selected}) != len(selected):
        raise SelectionContractError('selection_duplicate_block',
            'Each context_id/block_id pair may appear only once. No selection changed.')
    row = coverage[refs[0]]
    for block in selected:
        eid, bid = block['context_id'], block['block_id']
        details = {'requirement_ids': list(refs), 'context_id': eid, 'block_id': bid,
                   'expected_source_id': row['source_id']}
        item = evidence.get(eid)
        if not item or item['kind'] != 'context':
            raise SelectionContractError('selection_context_not_available',
                'Select an existing context evidence ID owned by this role. No selection changed.', **details)
        if item['scope'] != row['source_scope']:
            raise SelectionContractError('selection_context_scope_mismatch',
                'This context belongs to a different pinned scope. Select evidence in the requirement scope. '
                'No selection changed.', actual_scope_id=digest(item['scope']),
                expected_scope_id=digest(row['source_scope']), **details)
        source = item['value']['source_snapshot_id']
        if source != row['source_id']:
            raise SelectionContractError('selection_block_source_mismatch',
                'This block belongs to a different source than the selected requirements. '
                'Choose matching blocks or issue a separate action for their existing requirement. '
                'No selection changed; no reread is implied.', actual_source_id=source, **details)
        if bid not in delivered_blocks.get(eid, set()):
            raise SelectionContractError('selection_block_not_fully_read',
                'This block has not been fully delivered in this context to this role. '
                'Use its pending body read or original read pointer before selecting it. '
                'No selection changed.', **details)
