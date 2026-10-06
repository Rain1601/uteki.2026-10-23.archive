"""Real model source discovery; creates a task input without financial answers.

Uses the verified source-context and short-reference implementation of annual v3.
Source selection is explicit; no company, period, source, or expected value default.
Execution deliberately stops before extraction so registered methods own that phase.
"""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.record_review_model import SdkRecordReviewer
from uteki.agents.runtime.run_budget import RunBudget
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.extraction_batches import load_task_method
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet


def load_discovery_implementation(path):
    spec = importlib.util.spec_from_file_location('annual_discovery_v3', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def run(args):
    impl = load_discovery_implementation(args.discovery_implementation)
    selected = json.loads(args.selection.read_text())
    config = json.loads(args.model_config.read_text())
    target = json.loads(args.target.read_text())
    if set(target) != {'question', 'task_instruction', 'metric_ids', 'task_id', 'max_new_batches'}:
        raise ValueError('explicit target scope fields required')
    if not target['metric_ids'] or not set(target['metric_ids']) <= impl.METRICS.keys():
        raise ValueError('unknown or missing target metric IDs')
    method = load_task_method(args.task_profile, args.method_root,
                              task_type='annual_financial_extraction')
    dataset, out = args.dataset.resolve(), args.output.resolve()
    manifest, spec, source, blocks, dates = impl.prepare_source_inputs(dataset, selected, args.source)
    if source['form'] not in method['method']['supported_forms']:
        raise ValueError('selected source form is outside registered method')
    references = impl.build_source_reference_map(manifest, source, blocks, dates['dataset_manifest_sha256'])
    out.mkdir(parents=True, exist_ok=False)
    write_new(out/'source-period-contexts.json', dates)
    write_new(out/'source-block-references.json', references)
    write_new(out/'model-config.input.json', config)
    write_new(out/'target.input.json', target)
    write_new(out/'selection.input.json', {'selected_source': spec, 'as_of': selected['as_of'],
        'selection_sha256': digest(args.selection.read_bytes())})
    (out/'discovery-implementation.py').write_bytes(args.discovery_implementation.read_bytes())
    (out/'runner.py').write_bytes(Path(__file__).read_bytes())
    periods_ref = {'path': str(out/'source-period-contexts.json'),
        'sha256': digest((out/'source-period-contexts.json').read_bytes()),
        'company_id': spec['company_id'], 'source_snapshot_id': args.source,
        'source_sha256': source['source_sha256']}
    references_ref = {'path': str(out/'source-block-references.json'),
        'sha256': digest((out/'source-block-references.json').read_bytes()),
        'reference_map_id': references['reference_map_id'], 'company_id': spec['company_id'],
        'source_snapshot_id': args.source, 'source_sha256': source['source_sha256']}
    metric_definitions = {k: impl.METRICS[k] for k in target['metric_ids']}
    discovery_input = {'company': manifest['company'], 'source': source, 'as_of': selected['as_of'],
        'task': target['task_instruction'], 'metric_definitions': metric_definitions,
        'source_period_contexts': dates['periods'], 'source_period_contexts_ref': periods_ref,
        'source_block_references_ref': references_ref,
        'catalog': [{'ref': entry['ref'], 'type': b['type'], 'page': b.get('pdf_page'),
                     'characters': len(b['text']), 'preview': b['text'][:360]}
                    for entry, b in zip(references['entries'], blocks, strict=True)],
        'boundary': 'Complete source catalog; navigation previews are not full reading. No expected financial answers supplied.'}
    write_new(out/'discovery-input.json', discovery_input)
    budget = RunBudget(Path(config['budget_ledger']), config['budget_usd'],
                       enforce=config.get('budget_policy') == 'enforced')
    planner = SdkRecordReviewer(config['provider'], config['model'], budget=budget,
        max_requests_total=config['max_requests_total'], output=out/'planner',
        credentials_root=args.credentials_root, prompt=impl.PLANNER_PROMPT,
        output_schema=impl.Discovery, max_tokens=config['max_tokens'],
        request_timeout=config['request_timeout'], max_retries=config['max_retries'],
        reasoning_effort=config['reasoning_effort'], max_request_bytes=2500000)
    try:
        proposal = impl.Discovery.model_validate(await planner.review(discovery_input)).model_dump(mode='json')
        write_new(out/'discovery.json', proposal)
        selected_ids = impl.resolve_selected_refs(proposal['selected_refs'], references, manifest,
                                                  source, blocks, dates['dataset_manifest_sha256'])
        date_pairs = {tuple(sorted(p.items())) for p in dates['periods']}
        periods = []
        for item in proposal['period_catalog']:
            p = item['period']
            pair = {'instant': p['end']} if p['kind']=='instant' else {'startdate': p['start'], 'enddate': p['end']}
            if tuple(sorted(pair.items())) not in date_pairs:
                raise ValueError('model-selected period is absent from verified source dates')
            periods.append({**item, 'company_id': spec['company_id'], 'source_snapshot_id': args.source})
        positions = {b['block_id']: n for n,b in enumerate(blocks)}
        chosen = set()
        for block_id in selected_ids:
            pos = positions[block_id]
            chosen.update(b['block_id'] for b in blocks[max(0,pos-2):pos+3])
        metrics = {key: {'metric_id': key, 'label': label, 'aliases': aliases,
                        'unit': spec['presentation_currency'], 'definition_version': 'annual-core-v1',
                        'aggregation': 'no_implicit_sum'}
                   for key,(label,aliases) in metric_definitions.items()}
        job = {'company_id': spec['company_id'], 'source_snapshot_id': args.source,
            'as_of': selected['as_of'], 'task_type': 'annual_financial_extraction',
            'task': target['task_instruction'] + ' Use the explicitly selected reporting currency ' + spec['presentation_currency'] +
                    '. Preserve source scale, signed numeral and all presented annual comparatives. Candidates require independent source review.',
            'block_ids': [b['block_id'] for b in blocks if b['block_id'] in chosen],
            'dataset_manifest_sha256': dates['dataset_manifest_sha256'],
            'source_period_contexts_ref': periods_ref, 'source_block_references_ref': references_ref,
            'record_schema_version': impl.EXACT_SOURCE_PERIOD_VERSION,
            'entity_catalog': [{'entity_id': spec['company_id'], 'company_id': spec['company_id'],
                'source_snapshot_id': args.source, 'label': spec['company_name'],
                'aliases': [spec['company_name'], spec['symbol'], 'Consolidated', 'Company', 'Group']}],
            'period_catalog': periods, 'normalization_config': {'version': 'annual-core-v1', 'metric_catalog': metrics},
            'discovery_ref': {'path': str(out/'discovery.json'), 'sha256': digest((out/'discovery.json').read_bytes())}}
        build_extraction_packet(dataset, job)
        write_new(out/'selected-job.json', job)
        write_new(out/'query-request.json', {'question': target['question'], 'dataset': str(dataset),
            'scope': {'execution_schema_version': 'research-execution-v1', 'snapshot_id': manifest['snapshot_id'],
                'company_ids': [spec['company_id']], 'source_snapshot_ids': [args.source],
                'source_policy_id': manifest['source_policy_id'], 'knowledge_cutoff': selected['as_of'],
                'include_candidates': True},
            'financial_tasks': [{'task_id': target['task_id'], 'job': job,
                'task_profile': str(args.task_profile), 'task_profile_sha256': digest(args.task_profile.read_bytes()),
                'max_new_batches': target['max_new_batches']}],
            'limits': {'max_steps': 16, 'turn_timeout': 300, 'max_packet_bytes': 300000,
                       'observation_bytes': 24000, 'page_items': 12}})
        print(json.dumps({'status': 'selected_job_ready', 'selected_block_count': len(job['block_ids']),
                          'period_count': len(periods), 'output': str(out)}), flush=True)
    finally:
        await planner.aclose()
        write_new(out/'planner-usage.json', planner.snapshot_usage())
        write_new(out/'manifest.json', {'files': {str(p.relative_to(out)): digest(p.read_bytes())
                                                for p in out.rglob('*') if p.is_file()}})


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('dataset','selection','model-config','credentials-root','target','task-profile',
                 'method-root','discovery-implementation','output'):
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--source', required=True)
    asyncio.run(run(p.parse_args()))
