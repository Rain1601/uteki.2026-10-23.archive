"""Relocate the six explicit Data-only cases without rewriting frozen history."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.retrieval_cycle import validate
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.query_service import QueryDataPort


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CASE_IDS = frozenset({'msft-business', 'googl-business', 'msft-revenue',
                      'googl-revenue', 'msft-cloud', 'googl-buyback'})


def build_configs(cases_path, output_dir, ledger):
    """Read-only validation. Paths are selected explicitly, never copied from history."""
    cases_path, output_dir, ledger = (Path(p).resolve() for p in (cases_path, output_dir, ledger))
    if output_dir.exists() or any(output_dir.is_relative_to(HERE/name)
                                  for name in ('datasets', 'configs', 'configs-v2', 'configs-v3', 'runs')):
        raise ValueError('output-dir must be new and outside frozen datasets, configs and runs')
    if ledger.is_relative_to(output_dir) or ledger.is_relative_to(HERE/'datasets'):
        raise ValueError('shared ledger must be outside generated configs and frozen datasets')
    if ledger.exists() and not ledger.is_file():
        raise ValueError('ledger must be a file path')
    cases = json.loads(cases_path.read_text())
    if (not isinstance(cases, list) or len(cases) != 6
            or any(not isinstance(c, dict) or set(c) != {'case_id', 'symbol', 'question'} for c in cases)
            or {c['case_id'] for c in cases} != CASE_IDS):
        raise ValueError('cases must preserve the six explicitly versioned experiment tasks')
    configs, inputs = {}, {}
    for case in cases:
        name, symbol = case['case_id'], case['symbol']
        if symbol not in {'msft', 'googl'} or not name.startswith(symbol + '-'):
            raise ValueError('case company does not match the explicit experiment case')
        template_path = HERE/'configs-v3'/f'{name}.json'
        template = json.loads(template_path.read_text())
        if template['request']['question'] != case['question'] or template['request']['purpose'] != 'analysis_evidence':
            raise ValueError('case question or purpose differs from the frozen template')
        if template['request'].get('review_feedback'):
            raise ValueError('fresh replay cannot import prior review feedback')
        dataset = HERE/'datasets'/symbol
        manifest = _verify_manifest(dataset)
        scope = template['request']['scope']
        if scope['snapshot_id'] != manifest['snapshot_id'] or scope['source_policy_id'] != manifest['source_policy_id']:
            raise ValueError('template scope differs from the selected frozen dataset')
        sources = {s['source_snapshot_id']: s for s in json.loads((dataset/'sources.json').read_text())}
        if any(sid not in sources or sources[sid]['company_id'] not in scope['company_ids']
               for sid in scope['source_snapshot_ids']):
            raise ValueError('template source/company does not belong to the selected dataset')
        with QueryDataPort(dataset) as port:
            port.scoped(scope).discover_data()
        config = deepcopy(template)
        config.pop('initial_query_ref', None)
        config['request']['dataset'] = str(dataset)
        config['credential_root'], config['workspace'] = str(ROOT), str(ROOT/'workspace')
        for role in ('planner', 'worker', 'reviewer'):
            model = config[role]
            if (model['provider'] != 'aihubmix' or model['model'] != 'claude-sonnet-5-5'
                    or model['budget_policy'] != 'record_only' or model['budget_usd'] is not None
                    or model['max_tokens'] != (12000 if role == 'reviewer' else 8192)
                    or model['max_retries'] != 1 or model['request_timeout'] != 120):
                raise ValueError('template differs from the versioned Sonnet replay policy')
            model['budget_ledger'] = str(ledger)
        validate(config, output_dir/f'validation-only-{name}')
        configs[name] = config
        inputs[name] = {'template': str(template_path.relative_to(ROOT)),
            'template_sha256': digest(template_path.read_bytes()),
            'dataset': str(dataset.relative_to(ROOT)),
            'dataset_manifest_sha256': digest((dataset/'manifest.json').read_bytes())}
    provenance = {'schema_version': 'data-replay-configs-v1', 'cases_sha256': digest(cases_path.read_bytes()),
        'generator_sha256': digest(Path(__file__).read_bytes()), 'repo_root': str(ROOT),
        'ledger': str(ledger), 'initial_query_reused': False, 'model_calls': 0, 'inputs': inputs}
    return configs, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--ledger', required=True, type=Path)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    configs, provenance = build_configs(args.cases, args.output_dir, args.ledger)
    if not args.check_only:
        output = args.output_dir.resolve()
        output.mkdir(parents=True, exist_ok=False)
        for name, config in configs.items():
            write_new(output/f'{name}.json', config)
        write_new(output/'replay-inputs.json', provenance)
        write_new(output/'manifest.json', {'files': {p.name: digest(p.read_bytes()) for p in sorted(output.iterdir())}})
    print(json.dumps({'status':'validated' if args.check_only else 'written', 'case_count':len(configs),
        'output_dir':str(args.output_dir.resolve()), 'model_calls':0}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
