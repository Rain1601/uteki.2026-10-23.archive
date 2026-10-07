"""Bounded graph-consumer rehearsal, separate from an Agent/model evaluation."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from uteki.domain.business_map.models import business_map_from_dict

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def read_relations(payload, *, company_id, document_id, object_id):
    if not all(isinstance(v, str) and v.strip() for v in (company_id, document_id, object_id)):
        raise ValueError('explicit nonblank scope and object required')
    model = business_map_from_dict(payload)
    if model.company_id != company_id or model.document_id != document_id:
        raise ValueError('business map scope mismatch')
    if object_id not in {b.id for b in model.businesses}:
        raise ValueError('object not in selected map')
    relations = []
    for edge in model.relationships:
        if object_id not in (edge.source_id, edge.target_id):
            continue
        evidence = [e for e in payload['evidence'] if e['id'] in edge.evidence_ids]
        relations.append(dict(source_id=edge.source_id, target_id=edge.target_id,
            kind=edge.kind.value, description=edge.description,
            basis=edge.basis.value if edge.basis is not None else 'legacy_unclassified',
            review_status=edge.review_status.value, evidence=evidence))
    return dict(company_id=company_id, document_id=document_id, object_id=object_id,
        status='candidate_relations' if relations else 'no_recorded_relation',
        absent_relationship_meaning='unknown_not_proven_independent',
        relations=relations, gaps=[u for u in payload['unknowns'] if object_id in u['related_business_ids']])


def main():
    # Concrete selection is an experiment input, never a production fallback.
    relative = 'experiments/agent_design/2026-10-07-nvidia-business-revenue-v1/derived-01-single-fence/business_map.json'
    path = ROOT / relative
    payload = json.loads(path.read_bytes())
    scope = dict(company_id='nvidia', document_id='nvidia-fy2025-annual-report-10k')
    results = [read_relations(payload, **scope, object_id=oid) for oid in ('drive_hyperion', 'nvidia_ai_enterprise')]
    for result in results:
        assert result == read_relations(payload, **scope, object_id=result['object_id'])
    rejected = []
    for changed in ({'company_id': ''}, {'company_id': 'another-issuer'}, {'document_id': 'another-period'}):
        try:
            read_relations(payload, **{**scope, **changed}, object_id='drive_hyperion')
        except ValueError:
            rejected.append(changed)
        else:
            raise AssertionError('scope substitution')
    no_edges = deepcopy(payload)
    no_edges['relationships'] = []
    empty = read_relations(no_edges, **scope, object_id='drive_hyperion')
    assert empty['status'] == 'no_recorded_relation'
    receipt = dict(origin='explicit_graph_read_not_model_query', model_calls=0,
        source_path=relative, source_sha256=sha256(path.read_bytes()).hexdigest(), results=results,
        checks=dict(scope_rejections=rejected, empty_graph_is_unknown=True, local_repeat_equal=True),
        limits=['Existing candidate only; no new extraction or semantic correction.',
                'Legacy relationship basis is unclassified, not automatically explicit.',
                'V2 consumption is limited to declared fields; no new v2 model candidate exists in this receipt.'])
    out = HERE / 'business-relations.json'
    data = json.dumps(receipt, ensure_ascii=False, indent=2)+'\n'
    if out.exists() and out.read_text() != data:
        raise ValueError('Preserve the previous receipt; select a new experiment version.')
    out.write_text(data)
    print(json.dumps({r['object_id']: len(r['relations']) for r in results}))


if __name__ == '__main__':
    main()
