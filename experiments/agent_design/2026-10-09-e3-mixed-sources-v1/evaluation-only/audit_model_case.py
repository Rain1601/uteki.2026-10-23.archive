"""Independent multi-source original fidelity checks after the sealed E3 run."""
from collections import Counter
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.answer_handoff import validate_saved_assessment

E = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_bytes())


def h(path):
    return sha256(path.read_bytes()).hexdigest()


def main(name):
    run = E / 'runs' / name
    _verify_manifest(run)
    frozen = read(E / 'evaluation-only/freeze-manifest-v1.json')
    for relative, sha in frozen['artifact_sha256'].items():
        assert h(E / relative) == sha, relative
    gold = read(E / 'evaluation-only/frozen/E3-M1-v1.json')
    result = read(run / 'result.json')
    packet = read(next(iter(sorted(run.glob('attempt-*/review-packet.json'), reverse=True))))
    assert packet['query_plan_origin'] != 'scripted_fixture'
    assert packet['question'] == gold['case']['query_zh']
    dataset = Path(packet['dataset_ref']['path'])
    _verify_manifest(dataset, packet['dataset_ref']['manifest_sha256'])
    assert h(dataset / 'manifest.json') == gold['dataset_manifest_sha256']
    query = Path(packet['query_ref']['path'])
    _verify_manifest(query, packet['query_ref']['manifest_sha256'])
    source_map, delivered = {}, {}
    for s in read(dataset / 'sources.json'):
        assert h(dataset / s['raw_file']) == gold['source_raw_sha256'][s['source_snapshot_id']]
        tree = html.fromstring((dataset / s['raw_file']).read_bytes())
        paths = {tree.getroottree().getpath(n): n for n in tree.iter() if isinstance(n.tag, str)}
        indexed = {b['block_id']: b for b in map(json.loads, (dataset / s['index_folder'] / 'blocks.jsonl').read_text().splitlines())}
        source_map[s['source_snapshot_id']] = (s, tree, paths, indexed)
    assert set(packet['scope']['source_snapshot_ids']) == set(source_map)
    assert packet['scope']['company_ids'] == [gold['case']['company_id']]
    assert packet['scope']['knowledge_cutoff'] == gold['case']['knowledge_cutoff']
    for document in packet['source_documents']:
        sid = document['source_snapshot_id']; s, tree, paths, indexed = source_map[sid]
        assert document['source_sha256'] == s['source_sha256']
        assert s['available_at'] <= packet['scope']['knowledge_cutoff']
        for block in document['blocks']:
            assert block['text'] == indexed[block['block_id']]['text']
            assert block['text'] == ' '.join(paths[block['dom_path']].text_content().split())
            delivered[(sid, block['block_id'])] = block
    canonical = {r['record_id']: r for r in read(dataset / 'records.json')['rows']}
    evidence = read(dataset / 'evidence.json')
    records = []
    for fact in packet['facts']:
        if fact['kind'] != 'record':
            continue
        r = fact['value']; assert r == canonical[r['record_id']]
        s, tree, paths, indexed = source_map[r['source_snapshot_id']]
        assert r['available_at'] <= packet['scope']['knowledge_cutoff']
        assert r['entity_id'] == gold['case']['company_id'] and r['dimensions'] == {}
        for citation in fact['citations']:
            block = delivered[(citation['source_snapshot_id'], citation['block_id'])]
            assert citation['quote'] == block['text'][citation['char_start']:citation['char_end']]
            assert citation['text_hash'] == sha256(block['text'].encode()).hexdigest()
        for eid in r['evidence_ids']:
            ev = evidence[eid]; node = paths[ev['fact_dom_path']]
            assert node.get('contextref') == r['origin']['context_ref'] == ev['context_ref']
            context, = tree.xpath('//*[@id=$id]', id=node.get('contextref'))
            fields = {n.tag.split(':')[-1]: ' '.join(n.itertext()).strip() for n in context.iter() if isinstance(n.tag, str)}
            assert fields['identifier'] == '0000789019' and 'segment' not in fields
            assert fields['startdate'] == r['period']['start'] and fields['enddate'] == r['period']['end']
            unit, = tree.xpath('//*[@id=$id]', id=node.get('unitref'))
            assert unit.text_content() == 'iso4217:USD' and r['unit'] == 'USD'
            value = Decimal(node.text_content().replace(',', '')) * Decimal(10) ** int(node.get('scale', '0'))
            if node.get('sign') == '-': value = -value
            assert value == Decimal(r['value_decimal'])
        records.append(r)
    coverage = []
    for required in gold['required']:
        matching = [r for r in records if r['entity_id'] == required['entity_id'] and r['metric_id'] == required['metric_id']
                    and all(r['period'][k] == required['period'][k] for k in ('kind', 'start', 'end'))
                    and r['unit'] == required['normalized_unit'] and r['value_decimal'] == required['normalized_value_decimal']]
        coverage.append({'requirement_id': required['requirement_id'], 'record_support': bool(matching),
                         'record_ids': [r['record_id'] for r in matching]})
    context_checks = []
    for sid in {r['source_snapshot_id'] for r in records}:
        source = source_map[sid][0]; text = '\n'.join(b['text'] for (s, _), b in delivered.items() if s == sid)
        context_checks.append({'source_snapshot_id': sid, 'unit_caption_present': 'In millions' in text,
            'annual_heading_present': 'Year Ended June 30' in text,
            'quarter_heading_present': 'Three Months' in text, 'nine_month_heading_present': 'Nine Months' in text,
            'year_columns_present': '2025' in text and '2024' in text,
            'conditional_C3': 'independent semantic review required; no generic substring substitution'})
    eligible = False
    if result['status'] == 'reviewed_data_ready':
        review = Path(result['final_review_ref']['path'])
        _verify_manifest(review, result['final_review_ref']['manifest_sha256'])
        _, eligible = validate_saved_assessment(review, packet); assert eligible
    assert result['analysis_called'] is False
    ledger = Path(read(E / 'configs/E3-M1-v1.json')['planner']['budget_ledger'])
    with sqlite3.connect('file:' + str(ledger) + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT reserved,actual,state FROM reservations').fetchall()
        cap = db.execute('SELECT usd FROM config').fetchone()[0]
        request_cap = db.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0]
    known = sum((Decimal(a) for _, a, state in rows if state == 'settled'), Decimal(0))
    unknown = sum((Decimal(r) for r, _, state in rows if state == 'unknown'), Decimal(0))
    assert cap == '3' and request_cap == 100 and not any(state == 'reserved' for _, _, state in rows)
    calls = [read(p) for root in (E / 'runs', E.parent / '2026-10-09-e2-msft-10q-v1/runs')
             for p in root.rglob('*-end.json') if '/calls/' in str(p)]
    assert len(calls) == len(rows)
    assert all(c['provider'] == 'deepseek' and c['configuration_snapshot']['fields']['base_url']['value'] == 'https://api.deepseek.com' for c in calls)
    output = {'case_id': 'E3-M1', 'criteria_sha256': h(E / 'evaluation-only/frozen/E3-M1-v1.json'),
        'workflow_status': result['status'], 'model_review_eligible': eligible,
        'necessary_record_coverage': coverage, 'context_mechanical_checks': context_checks,
        'original_fidelity': 'pass' if records and delivered else 'not_evaluable_no_material',
        'focus_and_context_semantics': 'pending independent review, including conditional C3',
        'delivered_records': len(records), 'delivered_sources': len(packet['source_documents']),
        'delivered_blocks': len(delivered), 'delivered_body_chars': sum(len(b['text']) for b in delivered.values()),
        'shared_costs': {'requests': len(rows), 'known_estimated_usd': str(known), 'unknown_reserved_usd': str(unknown),
            'inflight': 0, 'hard_cap_usd': cap, 'request_cap': request_cap, 'actual_billed_usd': None,
            'statuses': dict(Counter(c['status'] for c in calls))},
        'limits': ['Semantic context/focus still independently reviewed.', 'Known-case interference test, not held-out transfer or strict A/B.',
                   'No full financial package, revision acceptance or Analysis.']}
    target = E / 'evaluation-only' / name; target.mkdir(exist_ok=False)
    save = target / 'independent-audit.json'; save.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main(sys.argv[1])
