"""Offline fixture preparation and independent scoring; this module never calls models."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.domain.research_data.execution_scope import ExecutionScope
from uteki.infrastructure.research_data.financial_records import digest


def prepare(cases_path, output, *, case_ids=None, output_schema=None):
    """Only cases_path is read: expected answers never enter model inputs."""
    cases_path, output = Path(cases_path).resolve(), Path(output).resolve()
    suite = json.loads(cases_path.read_text())
    if suite['source_origin'] != 'synthetic_fixture': raise ValueError('synthetic fixtures required')
    available = {c['case_id']: c for c in suite['cases']}
    if len(available) != len(suite['cases']): raise ValueError('duplicate fixture IDs')
    chosen = list(available) if case_ids is None else list(case_ids)
    if not chosen or len(set(chosen)) != len(chosen) or not set(chosen) <= set(available):
        raise ValueError('explicit case selection is invalid')
    selected = [available[c] for c in chosen]
    scopes = [ExecutionScope.model_validate(c['scope']) for c in selected]
    if len({s.knowledge_cutoff for s in scopes}) != 1: raise ValueError('fixture cutoffs disagree')
    if output_schema is None:
        from uteki.domain.research_data.semantic_review import SemanticAssessment
        output_schema = SemanticAssessment.model_json_schema()
    packets = []
    for case in selected:
        packet = deepcopy({k: v for k, v in case.items() if k != 'case_id'})
        packet['scope'] = ExecutionScope.model_validate(case['scope']).model_dump(mode='json')
        packet['source_origin'] = 'synthetic_fixture'
        packet['schema_version'] = 'semantic-review-input-v1'
        packet['output_schema'] = deepcopy(output_schema)
        packet['source']['source_sha256'] = digest('\n'.join(b['text'] for b in packet['source_blocks']).encode())
        for block in packet['source_blocks']: block['text_hash'] = digest(block['text'].encode('utf-8'))
        for item in packet['records']: item['record_sha256'] = digest(item['record'])
        packet['packet_id'] = 'semantic-'+digest(packet)[:24]
        from uteki.infrastructure.research_data.semantic_review import validate_semantic_packet
        validate_semantic_packet(packet)
        packets.append((case['case_id'], packet))
    output.mkdir(parents=True, exist_ok=False)
    references = []
    for number, (case_id, packet) in enumerate(packets, 1):
        name = f'packets/{number:03d}.json'
        write_new(output/name, packet)
        references.append({'case_id': case_id, 'path': name, 'sha256': digest((output/name).read_bytes()),
            'packet_id': packet['packet_id'], 'record_ids': [r['record']['record_id'] for r in packet['records']]})
    spec = {'schema_version': 'semantic-review-input-manifest-v1', 'dataset': None,
        'dataset_manifest_sha256': None, 'source_origin': 'synthetic_fixture', 'scope': None,
        'fixtures': {'path': str(cases_path), 'sha256': digest(cases_path.read_bytes())},
        'record_ids': [r for ref in references for r in ref['record_ids']], 'packets': references,
        'status': 'prepared_not_reviewed', 'model_calls': 0}
    write_new(output/'input-manifest.json', spec)
    write_new(output/'manifest.json', {'files': {str(p.relative_to(output)): digest(p.read_bytes())
        for p in sorted(output.rglob('*')) if p.is_file()}})
    return spec


def score_case(packet, response, expected, *, validator=None):
    """Exact fixed verdicts plus authenticated source citations; no judge-model grading."""
    if validator is None:
        from uteki.infrastructure.research_data.semantic_review import validate_semantic_assessment
        validator = validate_semantic_assessment
    try:
        checked = validator(packet, response)
    except Exception as error:
        return {'passed': False, 'status': 'invalid_response', 'error_type': type(error).__name__}
    issues = []
    checks = {c['axis']: c['status'] for c in checked['checks']}
    assertions = {a['assertion_id']: a['verdict'] for a in checked['assertions']}
    allowed = {axis: rule['allowed_statuses'] for axis, rule in expected['checks'].items()}
    if set(checks) != set(allowed) or any(checks.get(axis) not in statuses for axis, statuses in allowed.items()):
        issues.append('axis_status_mismatch')
    if assertions != expected['assertions']: issues.append('assertion_verdict_mismatch')
    # Gold anchors are checked only here, after the model's response exists.
    assertion_quotes = [c['quote'] for a in checked['assertions'] for c in a['citations']]
    missing = [anchor for anchor in expected['citation_anchors']
               if not any(anchor in quote for quote in assertion_quotes)]
    if missing: issues.append('required_assertion_evidence_missing')
    return {'passed': not issues, 'status': 'scored', 'issues': issues,
            'missing_citation_anchors': missing, 'observed_checks': checks, 'observed_assertions': assertions}


def evaluate(inputs, responses, expected_path, output):
    """Read sealed prepared inputs and a runner result.json or per-packet assessments."""
    inputs, responses, expected_path, output = map(lambda p: Path(p).resolve(), (inputs, responses, expected_path, output))
    _verify_manifest(inputs)
    spec = json.loads((inputs/'input-manifest.json').read_text())
    expected = json.loads(expected_path.read_text())['cases']
    references = spec['packets']
    if not {r['case_id'] for r in references} <= set(expected): raise ValueError('missing independent expected case')
    response_map = {}
    result_path = responses/'result.json'
    if result_path.exists():
        if (responses/'manifest.json').exists(): _verify_manifest(responses)
        result = json.loads(result_path.read_text())
        for assessment in result.get('assessments', []):
            if assessment['packet_id'] in response_map: raise ValueError('duplicate response packet')
            response_map[assessment['packet_id']] = assessment
    scores = []
    for number, ref in enumerate(references, 1):
        packet = json.loads((inputs/ref['path']).read_text())
        response = response_map.get(ref['packet_id'])
        per_packet = responses/f'packet-{number:03d}/assessment.json'
        if response is None and per_packet.exists(): response = json.loads(per_packet.read_text())
        score = {'passed': False, 'status': 'not_run'} if response is None else score_case(packet, response, expected[ref['case_id']])
        scores.append({'case_id': ref['case_id'], 'packet_id': ref['packet_id'], **score})
    counts = dict(Counter(s['status'] for s in scores))
    report = {'schema_version': 'semantic-review-benchmark-score-v1', 'source_origin': 'synthetic_fixture',
        'inputs_manifest_sha256': digest((inputs/'manifest.json').read_bytes()),
        'expected_sha256': digest(expected_path.read_bytes()), 'case_count': len(scores),
        'passed': sum(s['passed'] for s in scores), 'statuses': counts, 'cases': scores,
        'limitations': ['Fixed synthetic cases do not establish real-company research correctness.',
                        'Exact evidence anchors intentionally require the relevant source wording.']}
    write_new(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('prepare')
    p.add_argument('--cases', required=True); p.add_argument('--output', required=True)
    p.add_argument('--case-id', action='append', dest='case_ids')
    e = commands.add_parser('evaluate')
    for name in ('inputs', 'responses', 'expected', 'output'): e.add_argument('--'+name, required=True)
    args = vars(parser.parse_args()); command = args.pop('command')
    if command == 'prepare': args['cases_path'] = args.pop('cases'); result = prepare(**args)
    else: args['expected_path'] = args.pop('expected'); result = evaluate(**args)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
