"""Read-only real-run audit. Writes only new evaluation artifacts; zero API calls."""
import argparse
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

from lxml import html
from uteki.agents.data_query import answer_handoff as h, retrieval_cycle as cycle
from uteki.infrastructure.research_data.financial_records import digest

ROOT = Path(__file__).resolve().parents[4]
STANDARD = ROOT / 'experiments/agent_design/2026-10-10-e6-material-scale-v1/evaluation-only/standard.v1.json'
OLD = ROOT / 'output/e6-repeatability-20261010-r1/R3/S3/run-r1/attempt-01'
read = lambda p: json.loads(p.read_bytes())


def literal_values(element, local_name):
    return [e.text for e in element.iter() if str(e.tag).rsplit(':', 1)[-1] == local_name]


def raw_content_check(packet):
    """Re-read raw inline XBRL, rather than accept a model's source verdict."""
    dataset = Path(packet['dataset_ref']['path'])
    sources = {s['source_snapshot_id']: s for s in read(dataset / 'sources.json')}
    trees = {}
    proofs = []
    for mandatory in read(STANDARD)['mandatory']:
        facts = [f for f in packet['facts'] if f.get('kind') == 'record'
                 and f['value']['entity_id'] == mandatory['company_id']
                 and f['value']['period']['start'] == mandatory['period']['start']
                 and f['value']['period']['end'] == mandatory['period']['end']]
        assert len(facts) == 1, mandatory['requirement_id']
        fact = facts[0]['value']
        assert fact['source_snapshot_id'] == mandatory['source_snapshot_id']
        assert fact['value_decimal'] == mandatory['value_usd'] and fact['unit'] == 'USD'
        assert fact['dimensions'] == {} and fact['accounting_basis'] == 'reported_consolidated'
        sid = fact['source_snapshot_id']
        source = sources[sid]
        raw = dataset / source['raw_file']
        assert digest(raw.read_bytes()) == source['source_sha256']
        tree = trees.setdefault(sid, html.fromstring(raw.read_bytes()))
        context_id = fact['origin']['context_ref']
        context = tree.xpath('//*[@id=$id]', id=context_id)
        assert len(context) == 1
        assert literal_values(context[0], 'identifier') == [mandatory['company_id'][4:]]
        assert literal_values(context[0], 'startdate') == [mandatory['period']['start']]
        assert literal_values(context[0], 'enddate') == [mandatory['period']['end']]
        assert not literal_values(context[0], 'explicitmember')
        candidates = tree.xpath('//*[@contextref=$context and @name=$concept]',
                                context=context_id, concept=fact['origin']['concept'])
        matched = []
        for element in candidates:
            value = Decimal(''.join(element.itertext()).replace(',', '').strip()) * Decimal(10) ** int(element.get('scale', '0'))
            if element.get('sign') == '-':
                value = -value
            unit = tree.xpath('//*[@id=$unit]', unit=element.get('unitref'))
            if value == Decimal(mandatory['value_usd']) and len(unit) == 1 and literal_values(unit[0], 'measure') == ['iso4217:USD']:
                matched.append({'dom_path': tree.getroottree().getpath(element),
                                'context_ref': context_id, 'scale': element.get('scale'),
                                'raw_text': ''.join(element.itertext()), 'usd': str(value)})
        assert matched, mandatory['requirement_id']
        proofs.append({'requirement_id': mandatory['requirement_id'], 'record_id': fact['record_id'],
                       'source_snapshot_id': sid, 'raw_original_sha256': source['source_sha256'],
                       'period': mandatory['period'], 'proofs': matched})
    delivered_sources = {d['source_snapshot_id'] for d in packet['source_documents']}
    assert delivered_sources == {m['source_snapshot_id'] for m in read(STANDARD)['mandatory']}
    return {'mandatory_coverage': '4/4', 'scope_truth_provenance': 'pass', 'raw_original_proofs': proofs}


def audit_review(path, *, replay_ordinal=None):
    cycle._verify_manifest(path)
    packet = read(path / 'input.json')
    result = read(path / 'result.json')
    report = {'path': str(path.relative_to(ROOT)), 'status': result['status'], 'failures': result['failures'],
              'raw_content': raw_content_check(packet), 'strict_load': 'not_passed'}
    read_inputs = [(file, read(file)) for file in sorted(Path(packet['query_ref']['path']).glob('turn-*/input.json'))]
    body_read_checks = []
    for document in packet['source_documents']:
        for block in document['blocks']:
            delivered = []
            for file, turn in read_inputs:
                retained = turn.get('retained_body', {}).get('items', [])
                if any(item.get('source_snapshot_id') == document['source_snapshot_id']
                       and item.get('block_id') == block['block_id'] and item.get('text') == block['text']
                       for item in retained):
                    delivered.append(str(file.relative_to(ROOT)))
            body_read_checks.append({'source_snapshot_id': document['source_snapshot_id'],
                                     'block_id': block['block_id'], 'exact_full_text_in_query_input': bool(delivered),
                                     'first_input': delivered[0] if delivered else None})
    report['actual_original_body_reading'] = {'checks': body_read_checks,
        'verdict': 'pass' if all(check['exact_full_text_in_query_input'] for check in body_read_checks) else 'fail'}
    if replay_ordinal:
        old = OLD / f'review-{replay_ordinal:02d}'
        cycle._verify_manifest(old)
        bad = read(old / 'source-response.json')
        expected = h.source_review_repair_input(packet, bad, max_bytes=packet['max_packet_bytes'])
        actual_input = read(path / 'model/review-0001-input.json')
        assert digest(packet) == digest(read(old / 'input.json'))
        assert digest(actual_input['packet']) == digest(expected)
        assert digest(json.loads(actual_input['model_input'])) == digest(expected)
        assert actual_input['model_input_sha256'] == digest(actual_input['model_input'])
        assert set(expected['host_protocol_diagnostics'][0]) == {'field_pointer', 'code', 'constraint_pointer'}
        report['input_is_original_rejected_draft_and_mechanical_repair_only'] = True
        report['not_fresh_autonomous_execution'] = True
    if (path / 'source-response.json').exists():
        response = read(path / 'source-response.json')
        try:
            _, eligible = h._validate_source_assessment(packet, response)
            report['source_protocol'] = {'legal': True, 'eligible': eligible}
        except ValueError as error:
            report['source_protocol'] = {'legal': False, 'error_type': type(error).__name__,
                                         'diagnostic': getattr(error, 'diagnostic', None)}
    else:
        report['source_protocol'] = {'legal': None, 'reason': 'No model response produced'}
    if result['status'] == 'reviewed' and result['analysis_eligible']:
        loaded = h.load_reviewed_data(path, expected_scope=packet['scope'],
            expected_review_manifest_sha256=digest((path / 'manifest.json').read_bytes()))
        report.update(strict_load='passed', handoff_id=loaded['handoff_id'])
    report['delivered_blocks'] = [{'source_snapshot_id': d['source_snapshot_id'],
                                  'block_id': b['block_id'], 'type': b['type'], 'text': b['text']}
                                 for d in packet['source_documents'] for b in d['blocks']]
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-root', default='output/e6-source-citation-20261010-r1')
    parser.add_argument('--report-name', default='independent-real-audit.v1.json')
    parser.add_argument('--recovery', action='store_true')
    args = parser.parse_args()
    output = ROOT / args.run_root
    cfg = read(output / 'runtime-config.v1.json')
    report = {'schema_version': 'e6-r1-independent-real-audit-v1', 'assessment_api_calls': 0,
              'run_root': args.run_root, 'original_standard_sha256': digest(STANDARD.read_bytes()),
              'reviews': [], 'missing_steps': [], 'call_costs': []}
    for ordinal in (1, 2):
        name = 'repair-01-network-recovery' if args.recovery and ordinal == 1 else f'repair-{ordinal:02d}'
        path = output / name
        if (path / 'manifest.json').exists():
            report['reviews'].append(audit_review(path, replay_ordinal=ordinal))
        else:
            report['missing_steps'].append(name)
    fresh = output / 'fresh-S3/run-r1'
    if (fresh / 'manifest.json').exists():
        cycle._verify_manifest(fresh)
        final_ref = read(fresh / 'result.json').get('final_review_ref')
        if final_ref:
            report['reviews'].append(audit_review(Path(final_ref['path'])))
        else:
            report['fresh_without_final_review'] = read(fresh / 'result.json')
    else:
        report['missing_steps'].append('fresh-S3')
    db = sqlite3.connect(Path(cfg['planner']['budget_ledger']).as_uri() + '?mode=ro', uri=True)
    ledger = {row[0]: {'reserved': row[1], 'actual': row[2], 'state': row[3]}
              for row in db.execute('SELECT id,reserved,actual,state FROM reservations')}
    db.close()
    baseline = read(output / 'ledger-before.v1.json')
    assert set(baseline['ids']) <= ledger.keys()
    cost_ids = set()
    for file in sorted(output.rglob('calls/*-end.json')):
        call = read(file)
        start = file.with_name(file.name.replace('-end.json', '-start.json'))
        assert start.exists() and read(start)['call_id'] == call['call_id']
        rid = call['budget_reservation_id']
        assert rid not in cost_ids and rid in ledger
        cost_ids.add(rid)
        if call['usage'] is not None:
            usage, price = call['usage'], call['pricing_snapshot']
            value = (Decimal(usage['input_tokens']) * Decimal(price['input_per_million'])
                     + Decimal(usage['output_tokens']) * Decimal(price['output_per_million'])) / Decimal(1000000)
            assert value == Decimal(call['estimated_usd'])
            assert ledger[rid]['state'] == 'settled' and value == Decimal(ledger[rid]['actual'])
        report['call_costs'].append({'call_id': call['call_id'], 'reservation_id': rid,
            'estimated_usd': call['estimated_usd'], 'reserved_usd': call['reserved_usd'],
            'ledger_state': ledger[rid]['state'], 'status': call['status']})
    report['new_ledger_ids'] = list(set(ledger) - set(baseline['ids']))
    assert cost_ids <= set(report['new_ledger_ids'])
    report['old_rejected_drafts_unchanged'] = all(
        digest((ROOT / p).read_bytes()) == sha for p, sha in
        read(Path(__file__).with_name('independent-citation-acceptance.v1.json'))['historical_files_sha256'].items())
    assert report['old_rejected_drafts_unchanged']
    report['real_acceptance_complete'] = not report['missing_steps'] and len(report['reviews']) == 3
    dest = Path(__file__).with_name(args.report_name)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'reviews': len(report['reviews']), 'missing': report['missing_steps'],
                      'calls': len(report['call_costs']), 'report': str(dest.relative_to(ROOT))}))


if __name__ == '__main__':
    main()
