"""Offline provenance audit; semantic acceptance stays with independent original review."""
import argparse
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.agents.data_query.answer_handoff import validate_saved_assessment
from uteki.infrastructure.research_data.query_service import QueryDataPort


def read(path):
    return json.loads(path.read_bytes())


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'gold', 'freeze', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'never overwrite an earlier audit'
    _verify_manifest(args.run)
    result = read(args.run / 'result.json')
    packet_path = sorted(args.run.glob('attempt-*/review-packet.json'))[-1]
    packet = read(packet_path)
    gold, freeze = read(args.gold), read(args.freeze)
    experiment = args.freeze.parent.parent
    for relative, expected in freeze['artifact_sha256'].items():
        assert digest(experiment / relative) == expected, relative
    assert packet['question'] == gold['query_zh']
    assert packet['query_plan_origin'] != 'scripted_fixture'
    assert packet['scope']['company_ids'] == [gold['company_id']]
    assert packet['scope']['knowledge_cutoff'] == gold['knowledge_cutoff']
    dataset = Path(packet['dataset_ref']['path'])
    _verify_manifest(dataset, packet['dataset_ref']['manifest_sha256'])
    assert digest(dataset / 'manifest.json') == gold['dataset_manifest_sha256']
    query = Path(packet['query_ref']['path'])
    _verify_manifest(query, packet['query_ref']['manifest_sha256'])
    sources = {s['source_snapshot_id']: s for s in read(dataset / 'sources.json')}
    originals = {}
    for sid in packet['scope']['source_snapshot_ids']:
        source = sources[sid]
        assert source['company_id'] == gold['company_id']
        assert digest(dataset / source['raw_file']) == source['source_sha256']
        tree = html.fromstring((dataset / source['raw_file']).read_bytes())
        nodes = {tree.getroottree().getpath(n): n for n in tree.iter() if isinstance(n.tag, str)}
        blocks = {b['block_id']: b for b in map(json.loads,
            (dataset / source['index_folder'] / 'blocks.jsonl').read_text().splitlines())}
        originals[sid] = (nodes, blocks)
    delivered = []
    for doc in packet['source_documents']:
        sid = doc['source_snapshot_id']; source = sources[sid]
        assert source['available_at'] <= gold['knowledge_cutoff']
        assert doc['source_sha256'] == source['source_sha256']
        assert doc['available_at'] == source['available_at']
        nodes, indexed = originals[sid]
        for block in doc['blocks']:
            expected = indexed[block['block_id']]
            assert block['text'] == expected['text']
            assert block['text'] == ' '.join(nodes[block['dom_path']].text_content().split())
            delivered.append({'source_snapshot_id': sid, 'block_id': block['block_id'],
                'reported_page': block.get('reported_page'), 'chars': len(block['text'])})
    canonical = {r['record_id']: r for r in read(dataset / 'records.json')['rows']}
    with QueryDataPort(dataset) as port:
        entity_companies = {e['entity_id']: e['company_id']
            for e in port.scoped(packet['scope']).get_schema()['entities']}
    record_ids = []
    for fact in packet['facts']:
        if fact['kind'] == 'record':
            record = fact['value']
            assert record == canonical[record['record_id']]
            assert entity_companies[record['entity_id']] == gold['company_id']
            assert record['available_at'] <= gold['knowledge_cutoff']
            record_ids.append(record['record_id'])
        for citation in fact.get('citations', []):
            sid = citation['source_snapshot_id']
            _, indexed = originals[sid]
            text = indexed[citation['block_id']]['text']
            assert citation['source_sha256'] == sources[sid]['source_sha256']
            assert citation['index_id'] == sources[sid]['index_id']
            if fact['kind'] == 'source_block':
                # Whole-block citations deliberately have no character offsets.
                assert citation['quote'] == text == fact['value']['text']
                assert fact['value']['text_hash'] == sha256(text.encode()).hexdigest()
            else:
                assert citation['quote'] == text[citation['char_start']:citation['char_end']]
                assert citation['text_hash'] == sha256(text.encode()).hexdigest()
    eligible = False
    if result['status'] == 'reviewed_data_ready':
        review = Path(result['final_review_ref']['path'])
        _verify_manifest(review, result['final_review_ref']['manifest_sha256'])
        _, eligible = validate_saved_assessment(review, packet)
        assert eligible
    assert result['analysis_called'] is False
    ledger = Path(freeze['ledger_path'])
    with sqlite3.connect('file:' + str(ledger) + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT reserved,actual,state FROM reservations').fetchall()
        cap = db.execute('SELECT usd FROM config').fetchone()[0]
        request_cap = db.execute('SELECT maximum FROM autonomous_request_limit').fetchone()[0]
    assert cap == freeze['shared_budget_usd']
    assert not any(s == 'reserved' for _, _, s in rows)
    output = {'case_id': gold['case_id'], 'criteria_sha256': digest(args.gold),
        'run_manifest_sha256': digest(args.run / 'manifest.json'),
        'packet_sha256': digest(packet_path), 'workflow_status': result['status'],
        'model_review_eligible': eligible,
        'original_fidelity': 'pass' if delivered or record_ids else 'not_evaluable_no_delivered_material',
        'independent_semantic_acceptance': 'pending original review; not inferred from hash/schema/model votes',
        'delivered_blocks': delivered, 'delivered_body_chars': sum(b['chars'] for b in delivered),
        'selected_record_ids': record_ids,
        'shared_costs': {'requests': len(rows),
            'known_estimated_usd': str(sum((Decimal(a) for _, a, s in rows if s == 'settled'), Decimal(0))),
            'unknown_reserved_usd': str(sum((Decimal(r) for r, _, s in rows if s == 'unknown'), Decimal(0))),
            'inflight': 0, 'hard_cap_usd': cap, 'request_cap': request_cap, 'billed_usd': None}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
