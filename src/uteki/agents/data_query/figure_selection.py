"""Role-local figure consumption and atomic, explicit supplement selection."""
from copy import deepcopy

from uteki.domain.research_data.figure_evidence import FIGURE_EVIDENCE_VERSION, FigureBundleRef
from uteki.infrastructure.research_data.run_artifacts import child_pointer


def bundle_reference(value):
    if value is None:
        return None
    return FigureBundleRef.model_validate(value).model_dump(mode='json')


def validate_figure_result(value, request, scope, bundle_ref):
    """Validate returned identity before this role stores or attaches anything."""
    if bundle_ref is None:
        raise ValueError('read_figure requires an explicitly pinned figure bundle')
    figure = value.get('figure', {})
    if (value.get('status') != 'read' or value.get('material_type') != FIGURE_EVIDENCE_VERSION
            or value.get('scope') != scope or value.get('source_snapshot_id') != request.source_snapshot_id
            or figure.get('source_snapshot_id') != request.source_snapshot_id
            or figure.get('figure_id') != request.figure_id
            or bundle_reference(value.get('figure_bundle_ref')) != bundle_ref
            or figure.get('figure_bundle_manifest_sha256') != bundle_ref['manifest_sha256']):
        raise ValueError('Figure result source, scope, identity or bundle binding mismatch')


def validate_figure_requirements(refs, coverage, scope, source_id):
    if any(coverage[rid]['kind'] != 'source_evidence'
           or coverage[rid]['source_id'] != source_id
           or coverage[rid]['source_scope'] != scope for rid in refs):
        raise ValueError('Figure evidence requires matching source_evidence requirements in the pinned scope')


def fully_consumed(progress, artifact_id, value):
    """All stored leaves must have actually been sent; parent pages may cover them.

    Arbitrary partial JSON does not imply completion. Separate exact child reads
    may cover the entire object, including transcription, context and provenance.
    """
    def complete(pointer):
        return any(aid == artifact_id and (parent == '' or pointer == parent
            or pointer.startswith(parent + '/')) for aid, parent in progress.complete)
    def visit(node, pointer):
        if complete(pointer):
            return True
        if isinstance(node, (dict, list)) and node:
            entries = node.items() if isinstance(node, dict) else enumerate(node)
            return all(visit(child, child_pointer(pointer, key)) for key, child in entries)
        return False
    return visit(value, '')


def validate_figure_selection(refs, selected, coverage, evidence, delivered, scope, bundle_ref):
    if bundle_ref is None or len(selected) != len(set(selected)):
        raise ValueError('Figure selection requires a pinned bundle and unique evidence IDs')
    results = []
    for eid in selected:
        item = evidence.get(eid)
        if not item or item['kind'] != 'figure' or item['scope'] != scope or eid not in delivered:
            raise ValueError('Figure selection requires complete role-local figure reading in the pinned scope')
        value = item['value']
        figure = value['figure']
        validate_figure_requirements(refs, coverage, scope, figure['source_snapshot_id'])
        if (bundle_reference(value['figure_bundle_ref']) != bundle_ref
                or figure['figure_bundle_manifest_sha256'] != bundle_ref['manifest_sha256']
                or any(eid not in coverage[rid]['evidence_ids'] for rid in refs)):
            raise ValueError('Figure selection differs from this requirement or pinned supplement bundle')
        results.append({'evidence_id': eid, 'figure_id': figure['figure_id'],
            'source_snapshot_id': figure['source_snapshot_id'], 'figure_bundle_ref': deepcopy(bundle_ref)})
    return results
