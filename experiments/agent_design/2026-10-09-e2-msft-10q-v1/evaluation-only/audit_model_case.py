"""Independent original checks after a sealed E2-Q1 run; never runtime input."""
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


def read(p):
    return json.loads(p.read_text())


def h(p):
    return sha256(p.read_bytes()).hexdigest()


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def main():
    run = E / 'runs' / sys.argv[1]
    _verify_manifest(run)
    freeze = E/'evaluation-only/frozen/E2-Q1-v1.json'
    gold = read(freeze)
    frozen = read(E/'evaluation-only/freeze-manifest-v1.json')
    assert frozen['artifact_sha256']['evaluation-only/frozen/E2-Q1-v1.json'] == h(freeze)
    result = read(run/'result.json')
    packet_path = next(p for p in sorted(run.glob('attempt-*/review-packet.json'), reverse=True))
    packet = read(packet_path)
    assert packet['query_plan_origin'] != 'scripted_fixture'
    assert packet['question'] == gold['case']['query_zh']
    dataset = Path(packet['dataset_ref']['path'])
    _verify_manifest(dataset, packet['dataset_ref']['manifest_sha256'])
    assert h(dataset/'manifest.json') == gold['dataset_manifest_sha256']
    query = Path(packet['query_ref']['path'])
    _verify_manifest(query, packet['query_ref']['manifest_sha256'])
    source, = read(dataset/'sources.json')
    raw = dataset/source['raw_file']
    assert h(raw) == gold['source_raw_sha256'] == source['source_sha256']
    tree = html.fromstring(raw.read_bytes())
    paths = {tree.getroottree().getpath(n): n for n in tree.iter() if isinstance(n.tag, str)}
    indexed = {b['block_id']: b for b in map(json.loads, (dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
    canonical = {r['record_id']: r for r in read(dataset/'records.json')['rows']}
    evidence = read(dataset/'evidence.json')
    delivered = {}
    for document in packet['source_documents']:
        assert document['source_snapshot_id'] == source['source_snapshot_id']
        assert document['source_sha256'] == h(raw)
        for block in document['blocks']:
            assert block['text'] == indexed[block['block_id']]['text']
            assert block['text'] == ' '.join(paths[block['dom_path']].text_content().split())
            delivered[block['block_id']] = block
    records = []
    for fact in packet['facts']:
        if fact['kind'] != 'record':
            continue
        record = fact['value']
        assert record == canonical[record['record_id']]
        assert record['source_snapshot_id'] == source['source_snapshot_id']
        assert record['available_at'] <= packet['scope']['knowledge_cutoff']
        for citation in fact['citations']:
            block = delivered[citation['block_id']]
            assert citation['quote'] == block['text'][citation['char_start']:citation['char_end']]
            assert citation['text_hash'] == sha256(block['text'].encode()).hexdigest()
        for eid in record['evidence_ids']:
            ev = evidence[eid]
            node = paths[ev['fact_dom_path']]
            assert node.get('contextref') == record['origin']['context_ref'] == ev['context_ref']
            context, = tree.xpath('//*[@id=$id]', id=node.get('contextref'))
            fields = {n.tag.split(':')[-1]: ' '.join(n.itertext()).strip() for n in context.iter() if isinstance(n.tag, str)}
            assert fields['identifier'] == '0000789019'
            assert fields['startdate'] == record['period']['start'] and fields['enddate'] == record['period']['end']
            assert 'segment' not in fields and record['dimensions'] == {}
            unit, = tree.xpath('//*[@id=$id]', id=node.get('unitref'))
            assert unit.text_content() == 'iso4217:USD' and record['unit'] == 'USD'
            value = Decimal(node.text_content().replace(',', '')) * (Decimal(10) ** int(node.get('scale', '0')))
            if node.get('sign') == '-':
                value = -value
            assert value == Decimal(record['value_decimal'])
        records.append(record)
    coverage = []
    for required in gold['required']:
        matching = [r for r in records if r['entity_id'] == required['entity_id'] and r['metric_id'] == required['metric_id']
                    and all(r['period'][k] == required['period'][k] for k in ('kind', 'start', 'end'))
                    and r['unit'] == required['normalized_unit'] and r['value_decimal'] == required['normalized_value_decimal']]
        coverage.append({'requirement_id': required['requirement_id'], 'supported': bool(matching),
                         'record_ids': [r['record_id'] for r in matching]})
    text = '\n'.join(b['text'] for b in delivered.values())
    context_check = {'original_unit_caption': 'In millions' in text,
        'three_month_heading': 'Three Months' in text, 'nine_month_heading': 'Nine Months' in text,
        'year_alignment': '2025' in text and '2024' in text,
        'end_date_heading': 'March 31' in text, 'precise_context_dates_verified': bool(records)}
    files = body_instances = 0
    for path in query.rglob('*.json'):
        files += 1
        for obj in walk(read(path)):
            if obj.get('block_id') and isinstance(obj.get('text'), str):
                assert obj['block_id'] in indexed and obj['text'] == indexed[obj['block_id']]['text']
                body_instances += 1
            if obj.get('record_id') and obj.get('available_at'):
                assert obj['available_at'] <= packet['scope']['knowledge_cutoff']
            if obj.get('source_snapshot_id') and any(k in obj for k in ('text', 'value_decimal')):
                assert obj['source_snapshot_id'] == source['source_snapshot_id']
    eligible = False
    if result['status'] == 'reviewed_data_ready':
        review = Path(result['final_review_ref']['path'])
        _verify_manifest(review, result['final_review_ref']['manifest_sha256'])
        _, eligible = validate_saved_assessment(review, packet)
        assert eligible
    assert result['analysis_called'] is False
    calls = [read(p) for p in (E/'runs').rglob('*-end.json') if '/calls/' in str(p)]
    assert all(c['provider'] == 'deepseek' and c['configuration_snapshot']['fields']['base_url']['value'] == 'https://api.deepseek.com' for c in calls)
    with sqlite3.connect('file:' + str(E/'costs.sqlite') + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT reserved,actual,state FROM reservations').fetchall()
        limit = db.execute('SELECT usd FROM config').fetchone()[0]
    known = sum((Decimal(a) for _, a, state in rows if state == 'settled'), Decimal(0))
    unknown = sum((Decimal(r) for r, _, state in rows if state == 'unknown'), Decimal(0))
    assert limit == '3' and len(rows) == len(calls)
    assert not any(state == 'reserved' for _, _, state in rows)
    output = {'case_id': 'E2-Q1', 'criteria_sha256': h(freeze), 'run_manifest_sha256': h(run/'manifest.json'),
        'workflow_status': result['status'], 'model_review_eligible': eligible, 'necessary_coverage': coverage,
        'necessary_context_checks': context_check, 'scope_truth_provenance': 'pass' if records and delivered else 'not_evaluable_no_material',
        'delivered_record_count': len(records), 'delivered_original_blocks': list(delivered),
        'delivered_body_chars': sum(len(b['text']) for b in delivered.values()),
        'query_json_files_audited': files, 'original_body_instances_checked': body_instances,
        'focus': 'pending separate semantic review; numeric/text fidelity does not prove relevance',
        'costs': {'task_requests': len(rows), 'known_estimated_usd': str(known), 'unknown_reserved_usd': str(unknown),
                  'inflight': 0, 'hard_cap_usd': limit, 'actual_billed_usd': None, 'statuses': dict(Counter(c['status'] for c in calls))},
        'limitations': ['One known-source quarterly case, not held-out transfer or a strict A/B.',
                        'Dataset/source scope supplied by caller; semantic navigation and selection performed by model.',
                        'No full quarterly financial-package coverage or Analysis report acceptance.']}
    target = E/'evaluation-only'/run.name
    target.mkdir(exist_ok=False)
    with (target/'independent-audit.json').open('x') as f:
        json.dump(output, f, ensure_ascii=False, indent=2); f.write('\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
