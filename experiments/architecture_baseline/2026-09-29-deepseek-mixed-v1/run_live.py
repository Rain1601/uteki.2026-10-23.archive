"""Explicit real-model experiment; scope and both models come only from input JSON."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, inspect_run, _verify_manifest
from uteki.domain.research_data.company_agent import CompanyQueryInput
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


async def run(config_path, output):
    config = json.loads(config_path.read_text())
    if set(config) != {'request', 'planner', 'worker', 'credential_root', 'workspace'}:
        raise ValueError('Explicit request, both role configs, credential root and workspace required')
    request = CompanyQueryInput.model_validate(config['request'])
    if request.dataset is None:
        raise ValueError('This frozen-source experiment requires an explicit dataset and scope')
    CompanyDataCoordinator._validate_shared_model_configs(config['planner'], config['worker'])
    dataset = Path(request.dataset)
    manifest = _verify_manifest(dataset)
    with QueryDataPort(dataset) as port:
        scoped = port.scoped(request.scope)
        scoped.discover_data()
    workspace = Path(config['workspace']).resolve()
    code = {str(p.relative_to(workspace)): digest(p.read_bytes())
            for p in sorted((workspace / 'src/uteki').rglob('*.py'))}
    preflight = {'started_at': datetime.now(timezone.utc).isoformat(), 'plan_origin': 'model',
        'config_path': str(config_path.resolve()), 'config_sha256': digest(config_path.read_bytes()),
        'request': request.model_dump(mode='json'), 'dataset_manifest_sha256': digest((dataset/'manifest.json').read_bytes()),
        'dataset_snapshot_id': manifest['snapshot_id'], 'dataset_files_verified': len(manifest['files']),
        'code_hashes': code, 'runner_sha256': digest(Path(__file__).read_bytes()),
        'old_model_answers_loaded': False, 'reference_answers_loaded': False,
        'scope': 'Real Planner/Worker retrieval and source verification; no adoption or investment decision.'}
    write_new(output.with_name(output.name + '-preflight.json'), preflight)
    print(json.dumps({'phase': 'preflight_passed', 'output': str(output),
        'planner': config['planner']['model'], 'worker': config['worker']['model']}, ensure_ascii=False), flush=True)
    result = await CompanyDataCoordinator(workspace).query(request, output=output,
        model_config=config['planner'], worker_model_config=config['worker'],
        credential_root=config['credential_root'])
    verified = inspect_run(output)
    after = _verify_manifest(dataset)
    if after != manifest:
        raise ValueError('Frozen dataset changed during research')
    print(json.dumps({'phase': 'finished', 'status': result['status'], 'reason': result.get('stop_reason'),
        'manifest_status': verified['status'], 'gap_count': len(result.get('gaps', []))}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    asyncio.run(run(arguments.config, arguments.output.resolve()))
