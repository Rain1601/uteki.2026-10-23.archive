"""One source-bound extractor revision from program diagnostics; no planner or gold."""
import argparse
import asyncio
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.infrastructure.research_data.direct_extraction import build_extraction_packet, run_direct_extraction
from uteki.infrastructure.research_data.financial_records import digest


def prepare_revision(dataset, parent, prompt):
    parent = Path(parent).resolve()
    _verify_manifest(parent)
    load = lambda name: json.loads((parent/name).read_text())
    result, packet, normalized = load('result.json'), load('packet.json'), load('normalized.json')
    if result.get('plan_origin') != 'model' or result.get('status') != 'candidate':
        raise ValueError('explicit completed real-model parent required')
    job = deepcopy(load('job.json'))
    current = build_extraction_packet(dataset, job)
    for key in ('company_id', 'source', 'blocks', 'entity_catalog', 'metric_catalog', 'period_catalog',
                'dataset_snapshot_id', 'dataset_manifest_sha256', 'record_schema_version'):
        if current[key] != packet[key]:
            raise ValueError('revision source scope differs from frozen parent: '+key)
    by_draft = defaultdict(set)
    for issue in normalized['unresolved']:
        by_draft[issue['draft_id']].add(issue['reason'])
    counts = Counter(issue['reason'] for issue in normalized['unresolved'])
    parent_sha = digest((parent/'manifest.json').read_bytes())
    feedback = {'schema_version': 'direct-extraction-protocol-feedback-v1',
        'parent_run_id': 'direct-run-'+parent_sha[:24],
        'parent_run_ref': {'path': str(parent), 'manifest_sha256': parent_sha},
        'parent_artifacts': {name: {'sha256': digest((parent/name).read_bytes())}
                             for name in ('packet.json', 'extraction.json', 'normalized.json', 'job.json')},
        'source_scope': {key: packet['source'][key] for key in ('company_id', 'source_snapshot_id', 'source_sha256')},
        'findings': [{'code': code, 'count': count} for code, count in sorted(counts.items())],
        'draft_diagnostics': [{'draft_id': key, 'reasons': sorted(value)} for key, value in sorted(by_draft.items())],
        'instructions': [
            'These are program protocol failures, not reviewed financial facts or corrected amounts.',
            'Re-read the same supplied source blocks and return a complete replacement extraction using the revised prompt.',
            'Keep evidence exact and numeric punctuation unchanged. Use supported accounting_basis tokens only when justified.',
            'Retain source wording and leave absent metric/period catalog mappings unresolved; do not invent aliases or IDs.',
            'metric_unit_mismatch on an unmapped metric is a derived diagnostic; never guess a currency or broader metric.'],
        'semantic_review': 'not_evaluated', 'gold_inputs': False}
    job['prompt'] = {'version': Path(prompt).stem, 'text': Path(prompt).read_text()}
    return job, feedback


async def run(args):
    job, feedback = prepare_revision(args.dataset, args.parent, args.prompt)
    config = json.loads(args.model_config.read_text())
    config = {**config, 'model': config['extractor_model'], 'reasoning_effort': config['extractor_reasoning_effort']}
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write_new(output/'protocol-feedback.json', feedback)
    write_new(output/'model-config.input.json', config)
    (output/'runner-frozen.py').write_bytes(Path(__file__).read_bytes())
    job['revision_feedback'] = {**feedback,
        'review_sha256': digest((output/'protocol-feedback.json').read_bytes()),
        'review_ref': {'path': str(output/'protocol-feedback.json'),
                       'sha256': digest((output/'protocol-feedback.json').read_bytes())}}
    write_new(output/'revision-job.json', job)
    try:
        result = await run_direct_extraction(args.dataset, job, output/'extraction-01', strategy='direct',
            model_config=config, credentials_root=args.credentials_root)
        print(json.dumps({key: result.get(key) for key in ('status', 'raw_record_count', 'normalized_record_count',
                                                         'unresolved_count', 'dataset')}, ensure_ascii=False), flush=True)
    finally:
        write_new(output/'manifest.json', {'files': {str(path.relative_to(output)): digest(path.read_bytes())
            for path in output.rglob('*') if path.is_file()}})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('dataset', 'parent', 'model-config', 'credentials-root', 'prompt', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
