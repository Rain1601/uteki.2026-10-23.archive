"""Offline original-action regression. Never feed this evaluator to the Agent."""
import hashlib
import json
from pathlib import Path

from uteki.agents.data_query.selection_contract import SelectionContractError, validate_source_selection
from uteki.infrastructure.research_data.run_artifacts import load_evidence_bundle

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT/'output/revenue-stability-20261012'


def read(path):
    return json.loads(path.read_bytes())


def main():
    query = BASE/'v1/R3/run/attempt-01/data-query/query'
    frozen = read(query/'manifest.json')
    for name, expected in frozen['files'].items():
        assert hashlib.sha256((query/name).read_bytes()).hexdigest() == expected
    bundle = load_evidence_bundle(query)
    before = read(query/'turn-010/input.json')
    invalid = read(query/'turn-010/decision.json')
    coverage = {row['requirement_id']: row for row in before['coverage']}
    evidence = {row['evidence_id']: row for row in bundle['items']}
    # Reading eligibility is reconstructed ONLY from the actual pre-action input,
    # never from later disk contents or a final delivered_body union.
    read_blocks = {}
    for row in before['read_body_catalog']['items']:
        if row['fully_delivered']:
            read_blocks.setdefault(row['context_id'], set()).add(row['block_id'])
    for block in invalid['delivery']['blocks']:
        assert block['block_id'] in read_blocks.get(block['context_id'], set())
    try:
        validate_source_selection(invalid['requirement_ids'], invalid['delivery']['blocks'],
                                  coverage, evidence, read_blocks)
    except SelectionContractError as error:
        diagnostic = error.diagnostic
        assert diagnostic['code'] == 'selection_requirement_scope_mismatch'
    else:
        raise AssertionError('Original mixed-source action incorrectly accepted')
    for step in (11, 12):
        valid = read(query/f'turn-{step:03}/decision.json')
        validate_source_selection(valid['requirement_ids'], valid['delivery']['blocks'],
                                  coverage, evidence, read_blocks)
    report = {'schema_version': 'source-selection-replay-v1',
        'original_action': str(query.relative_to(ROOT)/'turn-010/decision.json'),
        'original_manifest_sha256': hashlib.sha256((query/'manifest.json').read_bytes()).hexdigest(),
        'all_seven_blocks_read_before_action': True, 'original_action_still_rejected': True,
        'new_diagnostic': diagnostic, 'original_split_actions_pass': True, 'model_calls': 0,
        'limitation': 'Replays validation on frozen input, not a new autonomous model decision'}
    with (BASE/'evaluation-only/ownership-original-replay.v1.json').open('x') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
