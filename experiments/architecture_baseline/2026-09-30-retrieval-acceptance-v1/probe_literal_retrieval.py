"""Offline tool probe; this is not an LLM paraphrase evaluation."""
import argparse
import hashlib
import json
from pathlib import Path

from lxml import html
from uteki.infrastructure.research_data.query_service import QueryDataPort


def load(path):
    return json.loads(path.read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--query-run', type=Path, required=True)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    config, probe = load(args.config), load(args.probe)
    request = config['request']
    owner = QueryDataPort(Path(request['dataset']))
    try:
        port = owner.scoped(request['scope'])
        search = load(args.query_run / probe['search_decision'])['search']
        original = load(args.query_run / probe['search_feedback'])['result']
        replay = port.search_source(search)
        assert replay['hits'] == original['hits']
        cases = []
        for phrase in probe['phrases']:
            result = port.search_source({**search, 'phrase': phrase})
            cases.append({'phrase': phrase, 'total': result['total'],
                          'status': result['status'], 'not_disclosed': result['not_disclosed'],
                          'hits': result['hits'], 'next_cursor': result['next_cursor']})
        read = load(args.query_run / probe['read_decision'])['read']
        original_read = load(args.query_run / probe['read_feedback'])['result']
        replay_read = port.read_source(read)
        assert replay_read['blocks'] == original_read['blocks']
        candidate = load(args.query_run / probe['answer_decision'])['answer']
        source = next(s for s in owner.sources if s['source_snapshot_id'] == search['source_snapshot_id'])
        raw = (Path(request['dataset']) / source['raw_file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source['source_sha256']
        tree = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8'))
        blocks = {b['block_id']: b for b in replay_read['blocks']}
        citations = []
        for claim in candidate['claims']:
            for cite in claim['citations']:
                block = blocks[cite['block_id']]
                elements = tree.xpath(block['dom_path'])
                raw_matches = len(elements) == 1 and ' '.join(elements[0].text_content().split()) == block['text']
                assert raw_matches and cite['quote'] in block['text']
                citations.append({'block_id': block['block_id'], 'quote': cite['quote'],
                                  'quote_matches_block': True, 'raw_html_matches_block': True})
        group = port.read_context(source_snapshot_id=search['source_snapshot_id'],
                                  block_id=probe['single_list_item'])
        result = {'evaluation_type': 'offline_tool_replay', 'model_calls': 0,
                  'scope': request['scope'], 'original_search_replayed': True,
                  'original_read_replayed': True, 'literal_cases': cases,
                  'original_read_block_ids': [b['block_id'] for b in replay_read['blocks']],
                  'single_item_read_expands_to': group['block_ids'],
                  'raw_sha256': source['source_sha256'], 'citations_checked': citations,
                  'limitations': ['Search terms are evaluator-selected, not model-selected.',
                                  'No statistical recall claim; one source and one topic.']}
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({'replays': 'matched', 'citations': len(citations),
                          'cases': [{k:c[k] for k in ('phrase','total','status')} for c in cases]}, ensure_ascii=False))
    finally:
        owner.close()
