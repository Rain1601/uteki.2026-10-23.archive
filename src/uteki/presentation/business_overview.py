"""Select a report-axis overview without changing the candidate's facts.

This is a display projection, not a judgment of economic importance. Full
identities, attributes, relationships and unresolved questions stay in the input.
"""
from collections import deque


def overview_selection(data):
    if data.get('schema_version') != 'business-map-v0.2':
        raise ValueError('business_map_v2_required')
    nodes = {node['id']: node for node in data['businesses']}
    if len(nodes) != len(data['businesses']):
        raise ValueError('duplicate_business_id')
    roots = [nid for nid, node in nodes.items() if node['kind'] == 'company']
    if len(roots) != 1:
        raise ValueError('one_company_root_required')
    children = {nid: set() for nid in nodes}
    for edge in data['relationships']:
        if edge.get('basis') not in {'explicit', 'derived', 'unknown'}:
            raise ValueError('relationship_basis_required')
        if edge['source_id'] not in nodes or edge['target_id'] not in nodes:
            raise ValueError('relationship_endpoint_missing')
        if edge['basis'] in {'explicit', 'derived'} and edge['kind'] in {'part_of', 'reported_under'}:
            children[edge['target_id']].add(edge['source_id'])
    root = roots[0]
    # Shortest membership depth also terminates on cyclic/multi-parent graphs.
    depth, pending = {root: 0}, deque([root])
    while pending:
        parent = pending.popleft()
        for child in children[parent]:
            if child not in depth:
                depth[child] = depth[parent] + 1
                pending.append(child)
    segments = {nid for nid, n in nodes.items()
                if n['kind'] == 'reportable_segment' and nid in depth}
    selected = {root} | children[root]
    # Include segment ancestry already present in the graph. Never invent a
    # shortcut edge from a segment to the company or infer an unknown parent.
    if segments:
        selected |= segments
        selected |= {child for sid in segments for child in children[sid]}
        todo = list(segments)
        while todo:
            child = todo.pop()
            for parent in nodes:
                if (child in children[parent] and parent in depth
                        and depth[parent] < depth[child] and parent not in selected):
                    selected.add(parent)
                    todo.append(parent)
    ordered = lambda ids: [nid for nid in nodes if nid in ids]
    reached = set(depth)
    return {
        'schema_version': 'business-overview-projection-v1',
        'policy': 'reported_segments_and_direct_constituents' if segments else 'company_direct_constituents',
        'selected_node_ids': ordered(selected),
        'folded_node_ids': ordered(reached - selected),
        'unplaced_node_ids': ordered(set(nodes) - reached),
        'total_nodes': len(nodes),
        'semantic_changes': 0,
        'importance_ranking': False,
    }
