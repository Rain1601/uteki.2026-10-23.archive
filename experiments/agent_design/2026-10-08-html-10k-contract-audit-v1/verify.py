"""Offline contract/consumer audit of explicit historical HTML 10-K candidates.

No extraction, candidate editing, adoption, semantic review, or model request.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile

import duckdb

from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources.parsed_package import verify_parsed_package
from uteki.domain.research_data.query_contract import ResearchRecord
from uteki.agents.filing_brief.consume import render
from uteki.agents.business_map.product_contract import validate_draft
from uteki.presentation.business_map_view import mermaid

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT / 'experiments/agent_design'


def read(path):
    return json.loads(path.read_text())


def ref(path):
    return dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def rejected(call):
    try:
        call()
    except (ValueError, KeyError):
        return True
    raise AssertionError('Invalid consumer input was accepted')


def main():
    checks = []
    acquisition = BASE / '2026-10-08-acquisition-reuse-v1'
    selections = [acquisition / p for p in (
        'msft/dataset/indexes/msft-2025-10k',
        'googl/dataset/indexes/googl-2025-10k',
        'amd/preparation/dataset/indexes/source-291485b98a75d8cfabe47571')]
    for package in selections:
        source = read(package / 'source.json')
        assert source['form_type'] == '10-K'
        result = verify_parsed_package(package)
        reader = DocumentReader(package)
        node = reader.outline()['nodes'][0]
        consumed = reader.read(node['node_id'], node['start_block_id'], count=1)
        assert consumed['blocks'] or consumed.get('omitted_block_count')
        checks.append(dict(kind='parsed_package', source=ref(package/'source.json'),
                           manifest=ref(package/'manifest.json'), checks=result,
                           consumer='DocumentReader.outline/read', quality='candidate; not_reviewed'))
        expected = {k: source[k] for k in (
            'company_id', 'document_id', 'source_snapshot_id', 'source_url', 'raw_sha256',
            'form_type', 'report_period_end', 'available_at', 'parser_version', 'export_version')}
        expected['company_id'] = 'unselected-company'
        assert rejected(lambda: verify_parsed_package(package, expected_source=expected))

    numeric = BASE/'2026-10-08-required-facts-completion-v1/run-03-normalized'
    facts = read(numeric/'normalized.json')
    rows = [ResearchRecord.model_validate(r) for r in facts['records']]
    with duckdb.connect(str(numeric/'dataset/research.duckdb'), read_only=True) as db:
        saved = dict(db.execute('SELECT record_id,value_decimal FROM observations').fetchall())
    from decimal import Decimal
    assert all(saved[r.record_id] == Decimal(r.value_decimal) for r in rows)
    bad = dict(facts['records'][0], schema_version='unsupported-version')
    assert rejected(lambda: ResearchRecord.model_validate(bad))
    checks.append(dict(kind='financial_candidates', artifact=ref(numeric/'normalized.json'),
                       consumer='ResearchRecord validation + read-only SQL', records=len(rows),
                       quality='candidate; selected six facts checked previously; not whole report'))

    brief_dir = BASE/'2026-10-07-filing-brief-v1/run-04/revision'
    brief, packet, task = [read(brief_dir/f) for f in ('brief.json','packet.json','task.json')]
    packet_sha = ref(brief_dir/'packet.json')['sha256']
    with tempfile.TemporaryDirectory() as temp:
        result = render(brief, packet, task, packet_sha, temp)
        for lang in ('zh','en'):
            markdown = (Path(temp)/f'brief.{lang}.md').read_text()
            assert all(f"## {item['id']} ·" in markdown for item in brief['items'])
            assert 'semantic acceptance pending' in markdown
        bad_task = dict(task, company_id='unselected-company')
        assert rejected(lambda: render(brief, packet, bad_task, packet_sha, temp))
        bad = copy.deepcopy(brief)
        bad['items'][0]['excerpts'][0]['quote'] = 'UNSUPPORTED QUOTE SENTINEL'
        assert rejected(lambda: render(bad, packet, task, packet_sha, temp))
    checks.append(dict(kind='filing_brief', artifact=ref(brief_dir/'brief.json'),
                       consumer='validated bilingual Markdown + evidence HTML', checks=result,
                       quality='candidate; independent review needs_revision; final model review not run'))

    graph_dir = BASE/'2026-10-07-business-coverage-v1/run-09/revision'
    draft, packet, graph = [read(graph_dir/f) for f in ('draft.json','source_packet.json','business_map.json')]
    validate_draft(draft, packet, expected_version='business-draft-v2')
    text, view = mermaid(graph)
    assert len(view['ids']) == len(graph['businesses'])
    assert all(f'  {node_id}["' in text for node_id in view['ids'].values())
    bad = dict(graph, schema_version='unsupported-version')
    assert rejected(lambda: mermaid(bad))
    bad = dict(draft, company_id='unselected-company')
    assert rejected(lambda: validate_draft(bad, packet, expected_version='business-draft-v2'))
    checks.append(dict(kind='business_graph', artifact=ref(graph_dir/'business_map.json'),
                       draft=ref(graph_dir/'draft.json'), consumer='validate_draft + Mermaid',
                       nodes=len(view['ids']), rendered_edges=len(view['edges']),
                       explicit_unresolved=len(view['unresolved']),
                       quality='candidate; graph-only; content review needs_revision'))
    output = dict(scope='Selected HTML 10-K contract/consumer checks only', model_calls=0,
                  semantic_acceptance='not_evaluated_by_this_audit',
                  checks=checks, consumer_checks='passed',
                  exclusions=['PDF','20-F','full-report extraction quality','unseen-company model generalization'])
    (HERE/'verification.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(consumer_checks='passed', entries=len(checks), model_calls=0)))


if __name__ == '__main__':
    main()
