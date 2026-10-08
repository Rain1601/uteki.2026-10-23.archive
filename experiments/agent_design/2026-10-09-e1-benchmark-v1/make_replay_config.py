"""Relocate one explicitly selected E1 task; never create or expand API credit."""
import argparse
from contextlib import closing
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import re
import sqlite3

from uteki.agents.data_query.artifacts import write_new
from uteki.agents.data_query.coordinator import CompanyDataCoordinator, _verify_manifest
from uteki.agents.data_query.retrieval_cycle import validate, review_roles
from uteki.infrastructure.research_data.financial_records import digest


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _path(value):
    selected = Path(value)
    _need('evaluation-only' not in selected.parts and 'evaluation-only' not in selected.resolve().parts,
          'evaluation-only material cannot enter replay configuration')
    _need(not selected.is_symlink(), 'select a regular path, not a symlink')
    return selected.resolve()


def restored_budget(ledger):
    """Read an idle, restored SQLite ledger without constructing RunBudget."""
    ledger = _path(ledger)
    _need(ledger.is_file(), 'existing restored ledger required; no new allowance is created')
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(ledger) + suffix)
        _need(not sidecar.exists() or sidecar.stat().st_size == 0,
              'checkpoint/finish ledger writes before generating a replay')
    before = digest(ledger.read_bytes())
    with closing(sqlite3.connect(ledger.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        row = db.execute('SELECT usd FROM config WHERE id=1').fetchone()
        _need(row is not None and row[0] is not None, 'restored ledger must have an enforced finite limit')
        limit = Decimal(row[0])
        _need(limit.is_finite() and 0 < limit <= 100, 'E1 released cumulative limit must be within USD 100')
        maximum = db.execute('SELECT maximum FROM autonomous_request_limit WHERE id=1').fetchone()
        _need(maximum and type(maximum[0]) is int and maximum[0] > 0, 'restored shared request limit required')
        rows = db.execute('SELECT reserved,actual,state FROM reservations').fetchall()
    committed = Decimal(0)
    for reserved, actual, state in rows:
        _need(state in {'settled', 'unknown'}, 'ledger has unfinished/in-flight requests; reconcile first')
        amount = Decimal(actual if state == 'settled' else reserved)
        _need(amount.is_finite() and amount >= 0, 'invalid ledger amount')
        committed += amount
    _need(committed < limit and len(rows) < maximum[0], 'restored allowance already exhausted')
    _need(digest(ledger.read_bytes()) == before, 'ledger changed during read; retry after calls finish')
    return {'path': str(ledger), 'sha256_at_check': before, 'limit_usd': str(limit),
            'committed_usd': str(committed), 'max_requests_total': maximum[0],
            'requests': len(rows), 'unknown_requests': sum(r[2] == 'unknown' for r in rows)}


def build_config(*, case_id, template, dataset, dataset_manifest_sha256, ledger,
                 credential_root, workspace, output_dir):
    _need(isinstance(case_id, str) and re.fullmatch('E1-[0-9]{2}', case_id), 'explicit E1 case ID required')
    template, dataset, ledger, credential_root, workspace, output_dir = map(
        _path, (template, dataset, ledger, credential_root, workspace, output_dir))
    _need(template.is_file() and template.name.startswith(case_id + '-') and template.suffix == '.json',
          'template filename must identify the explicitly selected case')
    _need(not output_dir.exists() and not any(output_dir.is_relative_to(p) for p in
          (dataset, template.parent, workspace)) and not ledger.is_relative_to(output_dir),
          'output must be new and outside frozen inputs, ledger and runtime workspace')
    _need(credential_root.is_dir(), 'existing credential root required; keys are not read here')
    _need(isinstance(dataset_manifest_sha256, str) and re.fullmatch('[a-f0-9]{64}', dataset_manifest_sha256),
          'explicit frozen dataset manifest hash required')
    raw = template.read_bytes()
    config = deepcopy(json.loads(raw))
    _need('initial_query_ref' not in config and not config.get('request', {}).get('review_feedback'),
          'fresh replay cannot import old query results or review feedback')
    # Reject even empty feedback: do not silently remove a feedback field.
    _need('review_feedback' not in config['request'], 'fresh request must omit review_feedback')
    # Validate the original roles before relocation replaces ledger paths/limits.
    # Otherwise a mismatched reviewer ledger could be silently concealed.
    roles = review_roles(config)
    for role in roles:
        CompanyDataCoordinator._validate_shared_model_configs(config['planner'], config[role])
    _verify_manifest(dataset, dataset_manifest_sha256)
    budget = restored_budget(ledger)
    original_request = deepcopy(config['request'])
    config['request']['dataset'] = str(dataset)
    config['credential_root'], config['workspace'] = str(credential_root), str(workspace)
    for role in roles:
        model = config[role]
        _need(model.get('budget_policy') == 'enforced' and model.get('budget_usd') is not None,
              'template must already use enforced budgeting')
        old = Decimal(str(model['budget_usd']))
        _need(old.is_finite() and 0 < old <= 100, 'template budget exceeds E1 authorization')
        _need(model.get('max_requests_total') == budget['max_requests_total'],
              'template request limit differs from restored ledger')
        model['budget_ledger'], model['budget_usd'] = str(ledger), budget['limit_usd']
    validate(config, output_dir / 'validation-only-run')
    # Relocation is allowed to change paths/budget release only, never task scope.
    expected = deepcopy(original_request); expected['dataset'] = str(dataset)
    _need(config['request'] == expected, 'replay unexpectedly changed task')
    provenance = {'schema_version': 'e1-replay-config-v1', 'case_id': case_id,
        'template_sha256': digest(raw), 'dataset_manifest_sha256': dataset_manifest_sha256,
        'generator_sha256': digest(Path(__file__).read_bytes()), 'restored_budget': budget,
        'model_calls': 0, 'new_allowance_created': False, 'old_results_or_feedback_reused': False,
        'evaluation_only_read': False}
    return config, provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', dest='case_id', required=True)
    for name in ('template', 'dataset', 'ledger', 'credential-root', 'workspace', 'output-dir'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--dataset-manifest-sha256', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = vars(parser.parse_args(argv))
    check_only = args.pop('check_only')
    config, provenance = build_config(**args)
    if not check_only:
        output = args['output_dir'].resolve()
        output.mkdir(parents=True, exist_ok=False)
        write_new(output / (args['case_id'] + '-replay.json'), config)
        write_new(output / 'provenance.json', provenance)
        write_new(output / 'manifest.json', {'files': {
            p.name: digest(p.read_bytes()) for p in sorted(output.iterdir())}})
    print(json.dumps({'status': 'checked' if check_only else 'written', 'case_id': args['case_id'],
                      'model_calls': 0, 'new_allowance_created': False,
                      'restored_budget': provenance['restored_budget']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
