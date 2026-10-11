"""Freeze final reviewed evaluation scripts, runtime and complete inputs before API."""
from datetime import datetime, timezone

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query import retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest
from runtime_helpers import ROOT, EXP, OUTPUT, read, verify_freeze


def freeze():
    assert not (EXP / 'evaluation-only/freeze.v1.json').exists()
    assert (EXP / 'evaluation-only/independent-real-acceptance.v1.py').exists()
    assert (EXP / 'evaluation-only/audit_costs_final.py').exists()
    matrix = read(EXP / 'execution-matrix.v1.json')
    paths = [p for base in (ROOT / 'src/uteki', ROOT / 'skills/data-agent', EXP) for p in base.rglob('*')
             if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc', '.sqlite'}]
    paths.append(OUTPUT / 'ledger-before.v1.json')
    paths.extend(ROOT / 'tests/unit' / name for name in ('test_delivery_boundary_v4.py', 'test_source_revision_feedback.py', 'test_record_selection_navigation.py'))
    for item in matrix['runs']:
        paths.append(ROOT / item['config'])
    for tier in read(EXP / 'gradients.v1.json')['tiers']:
        dataset = ROOT / tier['dataset']
        cycle._verify_manifest(dataset, tier['dataset_manifest_sha256'])
        paths.append(dataset / 'manifest.json')
        paths.extend(dataset / p for p in read(dataset / 'manifest.json')['files'])
    old = ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v1'
    paths.extend([old / 'evaluation-only/collect_metrics.py', old / 'evaluation-only/stop_policy_v3.py',
                  old / 'evaluation-only/standard.v1.json', old / 'execution-matrix.v1.json',
                  ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/collect_metrics.py',
                  ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/standard.v1.json',
                  ROOT / 'experiments/agent_design/2026-10-10-e6-source-citation-v1/evaluation-only/independent_real_audit.py',
                  ROOT / 'experiments/agent_design/2026-10-10-e6-record-selection-v1/evaluation-only/independent_real_acceptance_v2.py',
                  ROOT / 'experiments/agent_design/2026-10-10-e6-repeatability-v2/evaluation-only/independent_acceptance.py'])
    sealed = {}
    for item in read(old / 'execution-matrix.v1.json')['runs']:
        path = ROOT / item['run']
        cycle._verify_manifest(path)
        sealed[str(path.relative_to(ROOT))] = digest((path / 'manifest.json').read_bytes())
    for series in ('e6-repeatability-20261010-r2', 'e6-delivery-boundary-20261010-r1'):
        for manifest in (ROOT / 'output' / series).glob('**/run-r1/manifest.json'):
            path = manifest.parent
            cycle._verify_manifest(path)
            sealed[str(path.relative_to(ROOT))] = digest(manifest.read_bytes())
    snapshot = {'schema_version': 'e6-repeatability-v3-execution-freeze-v1',
                'frozen_before_model_execution': True, 'created_at': datetime.now(timezone.utc).isoformat(),
                'files': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths},
                'sealed_refs': sealed, 'priority': ['effect', 'success_rate', 'cost'], 'planned_fresh_runs': 9}
    write_new(EXP / 'evaluation-only/freeze.v1.json', snapshot)
    verify_freeze()
    print({'frozen_files': len(snapshot['files']), 'historical_sealed_runs': len(sealed), 'api_calls': 0})


if __name__ == '__main__':
    freeze()
