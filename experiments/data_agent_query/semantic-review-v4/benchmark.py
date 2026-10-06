"""Prepare unseen v4 model inputs or independently score outputs. Never calls a model."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from uteki.agents.data_query.artifacts import write_new
from uteki.infrastructure.research_data.financial_records import digest
from uteki.infrastructure.research_data.semantic_review import validate_semantic_packet


def prepare(cases, output):
    """Read only model-visible cases; never load the scoring key or include its metadata."""
    cases, output = Path(cases).resolve(), Path(output).resolve()
    suite = json.loads(cases.read_text())
    if suite['schema_version'] != 'semantic-review-fixtures-v4' or suite['source_origin'] != 'synthetic_fixture':
        raise ValueError('explicit v4 synthetic fixture suite required')
    ids = [c['case_id'] for c in suite['cases']]
    if not ids or len(set(ids)) != len(ids): raise ValueError('nonempty unique case IDs required')
    for item in suite['cases']: validate_semantic_packet(item['packet'])
    output.mkdir(parents=True, exist_ok=False)
    refs = []
    for number, item in enumerate(suite['cases'], 1):
        packet = item['packet']; name = f'packets/{number:03d}.json'
        write_new(output/name, packet)
        refs.append({'case_id': item['case_id'], 'path': name, 'sha256': digest((output/name).read_bytes()),
                     'packet_id': packet['packet_id'], 'record_ids': [r['record']['record_id'] for r in packet['records']]})
    manifest = {'schema_version': 'semantic-review-input-manifest-v1', 'source_origin': 'synthetic_fixture',
        'dataset': None, 'scope': None, 'packets': refs,
        'record_ids': [rid for ref in refs for rid in ref['record_ids']],
        'fixture_cases_sha256': digest(cases.read_bytes()), 'model_calls': 0}
    write_new(output/'input-manifest.json', manifest)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return manifest


def evaluate(inputs, run, expected, output, notes=None):
    """Scoring-only path; expected answers never feed preparation or a model request."""
    source = ROOT/'experiments/data_agent_query/semantic-review-v3/evaluate_fixtures.py'
    spec = importlib.util.spec_from_file_location('v4_independent_evaluation', source)
    evaluator = importlib.util.module_from_spec(spec); spec.loader.exec_module(evaluator)
    return evaluator.evaluate(inputs, run, expected, output, notes_path=notes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare'); p.add_argument('--cases', required=True); p.add_argument('--output', required=True)
    e = commands.add_parser('evaluate')
    for name in ('inputs', 'run', 'expected', 'output'): e.add_argument('--'+name, required=True)
    e.add_argument('--notes')
    args = vars(parser.parse_args()); command = args.pop('command')
    if command == 'prepare':
        result = prepare(**args)
        print(json.dumps({'case_count': len(result['packets']), 'model_calls': 0, 'output': args['output']}))
    else:
        result = evaluate(**args)
        print(json.dumps({'statuses': result['statuses'], 'output': args['output']}))


if __name__ == '__main__': main()
