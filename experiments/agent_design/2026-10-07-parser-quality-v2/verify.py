#!/usr/bin/env python3
"""Offline page-label repair acceptance for explicitly selected frozen sources.

--build creates new packages and receipts; --check verifies and rebuilds them in
temporary directories. No source edits, network access, model calls or SQL.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT)]

from lxml import html
from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline

VERSION = 'sec-source-blocks-v0.1.11'
PREVIOUS = HERE.parent/'2026-10-07-parser-navigation-v1'
RUNTIME = HERE.parent/'2026-10-07-parser-runtime-v1'
# Explicit experiment scope and independently reviewed source positions. These
# expectations never feed the parser or downstream extraction/model input.
CASES = {
    'amd': {'company_id':'sec-0000002488', 'period_end':'2023-12-30',
        'snapshot':'source-291485b98a75d8cfabe47571',
        'raw_sha256':'47955f5d3d309e40c53ac7243dc955c8c1b594605fa938db1b5c411aaf2aa808',
        'probe':'block-000633-f1230e84', 'query':'Net cash provided by operating activities was $1.7 billion in 2023',
        'page':51, 'changed_ordinals':[], 'footer_path':'/html/body/div[555]/div/div', 'footer_text':'43'},
    'tsmc': {'company_id':'sec-0001046179', 'period_end':'2023-12-31',
        'snapshot':'source-6719837a8d24b2b7df359f29',
        'raw_sha256':'8ab4ee8c621d4d7bc804d08bd5cfe494b91dc09a63a4c7decfad4e5f8b9961c1',
        'probe':'block-000997-8d2882d6', 'query':'Audit Fees 56,040 83,635',
        'page':70, 'changed_ordinals':list(range(994,1004)),
        'footer_path':'/html/body/div[75]/div/div/div[11]/div/div', 'footer_text':'70'},
}
TESTS = ['test_sec_inherited_page_markers', 'test_sec_parser_versions', 'test_parsed_package',
    'test_sec_navigation_stages', 'test_sec_document_index', 'test_sec_index_tables',
    'test_document_reader', 'test_company_materialization']


def read(path):
    return json.loads(path.read_bytes())


def ref(path):
    return {'path':path.relative_to(ROOT).as_posix(), 'sha256':package.sha(path.read_bytes())}


def files(folder):
    return {p.relative_to(folder).as_posix():package.sha(p.read_bytes())
            for p in sorted(folder.rglob('*')) if p.is_file()}


def blocks(folder):
    return [json.loads(line) for line in (folder/'blocks.jsonl').read_bytes().splitlines()]


def tests():
    suite = unittest.TestLoader().loadTestsFromNames(['tests.unit.'+name for name in TESTS])
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output,verbosity=1).run(suite)
    assert result.wasSuccessful(), output.getvalue()
    return {'kind':'offline program checks, not model evaluation', 'passed':True,
            'tests_run':result.testsRun, 'modules':TESTS}


def run(label, case, build):
    old, output = PREVIOUS/f'stage-b-{label}', HERE/label
    historical = files(old)
    source = read(old/'source.json')
    assert (source['company_id'], source['report_period_end'], source['source_snapshot_id']) == (
        case['company_id'], case['period_end'], case['snapshot'])
    raw_path = RUNTIME/f'prepare-{label}'/'dataset'/'raw'/f'{case["snapshot"]}.html'
    raw = raw_path.read_bytes()
    assert package.sha(raw) == source['raw_sha256'] == case['raw_sha256']
    identity = {k:v for k,v in source.items() if k in package.SourceIdentity.model_fields}
    # Historical content remains replayable; its full manifest pins older code.
    parsed_old = parse_sec_source(identity['document_id'],identity['source_url'],raw,
        source_snapshot_id=identity['source_snapshot_id'],form_type=identity['form_type'],
        parser_version=identity['parser_version'])
    replay_old = {'blocks.jsonl':b''.join(package.canonical(asdict(b)) for b in parsed_old.blocks),
        'anchors.json':package.canonical([asdict(a) for a in parsed_old.anchors]),
        'toc.json':package.canonical([asdict(t) for t in parsed_old.toc_entries]),
        'index.json':package.canonical(asdict(build_legal_outline(parsed_old)))}
    assert all(data == (old/name).read_bytes() for name,data in replay_old.items())
    selected = {**identity,'parser_version':VERSION}
    if build:
        package.build_parsed_package(raw,selected,output)
    verified = package.verify_parsed_package(output,expected_source=selected)
    with tempfile.TemporaryDirectory(prefix='uteki-page-label-replay-') as temp:
        rebuilt = Path(temp)/'package'
        package.build_parsed_package(raw,selected,rebuilt)
        assert files(rebuilt) == files(output), 'new package byte replay differs'
    before, after = blocks(old), blocks(output)
    assert len(before) == len(after)
    changes = []
    for a,b in zip(before,after,strict=True):
        delta = {k:{'before':a[k],'after':v} for k,v in b.items() if a[k] != v}
        if delta:
            assert set(delta) <= {'reported_page','type','layout_role'}
            assert a['reported_page'] == 71 and b['reported_page'] == 70
            if set(delta) != {'reported_page'}:
                assert a['ordinal'] == 1003 and a['text'] == '70'
                assert b['type'] == 'page_marker' and b['layout_role'] == 'reported_page_number'
            changes.append({'block_id':b['block_id'],'ordinal':b['ordinal'],
                'dom_path':b['dom_path'],'text_hash':b['text_hash'],'delta':delta})
    assert [c['ordinal'] for c in changes] == case['changed_ordinals']
    for name in ('anchors.json','assets.json','toc.json'):
        assert (old/name).read_bytes() == (output/name).read_bytes()
    # Direct DOM inspection is separate from the page-classification function.
    dom = html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8'))
    footer, = dom.xpath(case['footer_path'])
    assert normalize_text(''.join(footer.itertext())) == case['footer_text']
    chain = [{'dom_path':dom.getroottree().getpath(n),'style':n.get('style'),
              'text_prefix':normalize_text(''.join(n.itertext()))[:140]}
             for n in [footer,*list(footer.iterancestors())[:3]]]
    reader = DocumentReader(output)
    node = next(n['node_id'] for n in reader.index['nodes'] if n['kind']=='document')
    search = reader.search(node,case['query'])
    hit, = search['hits']
    assert hit['block_id'] == case['probe'] and hit['reported_page'] == case['page']
    context = reader.read(node,case['probe'],count=1)
    selected_block, = [b for b in context['blocks'] if b['block_id']==case['probe']]
    assert selected_block['reported_page'] == case['page']
    expected_block, = [b for b in before if b['block_id']==case['probe']]
    assert selected_block['text'] == expected_block['text'] and selected_block['table'] == expected_block['table']
    raw_probe, = dom.xpath(selected_block['dom_path'])
    assert normalize_text(''.join(raw_probe.itertext())) == selected_block['text']
    if label == 'tsmc':
        assert '2022 2023 NT$ NT$ (In thousands)' in selected_block['text']
        assert 'Total 79,149 87,236' in selected_block['text']
        unchanged_next, = [b for b in after if b['block_id']=='block-001005-e2755fd5']
        assert unchanged_next['reported_page']==71
    assert reader.filter_navigation
    assert files(old)==historical and package.sha(raw_path.read_bytes())==case['raw_sha256']
    return {'company_id':case['company_id'],'period_end':case['period_end'],
        'source':ref(raw_path),'source_snapshot_id':case['snapshot'],'new_package':str(output.relative_to(ROOT)),
        'manifest':ref(output/'manifest.json'),'package_verification':verified,'byte_replay_identical':True,
        'historical_files_unchanged':True,'legacy_core_content_replay_identical':True,
        'old_files':historical,'new_files':files(output), 'changes':changes,
        'source_text_ids_dom_hashes_tables_cells_style_signatures_unchanged':True,
        'anchors_assets_toc_unchanged':True,
        'counts':{'blocks':len(after),'tables':sum(b['table'] is not None for b in after),
            'cells':sum(len(b['table']['cells']) for b in after if b['table']),
            'reported_page_changes':len(changes),
            'page_markers_before':sum(b['type']=='page_marker' for b in before),
            'page_markers_after':sum(b['type']=='page_marker' for b in after),
            'unknown_page_blocks':sum(b['reported_page'] is None for b in after)},
        'footer_dom_observation':chain,'reader_receipt':{'search':search,'read':context},
        'migration':{'block_identity':'stable for both selected sources',
            'index_id_before':read(old/'index.json')['index_id'],'index_id_after':reader.index['index_id'],
            'package_id_before':read(old/'manifest.json')['package_id'],
            'package_id_after':read(output/'manifest.json')['package_id'],
            'rule':'Select and pin the new package explicitly; do not replace historical manifests or reuse an old index_id.'},
        'limits':['Only direct DocumentReader consumers exercised here; root separately checks scoped Query and numeric calculation.',
            'Original source text is not a normalized financial observation; no SQL, model or semantic scoring ran.',
            'Unit/footnote association, cross-section references, F-page labels, CSS stylesheets and full semantic omissions remain unaccepted.']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--build',action='store_true')
    group.add_argument('--check',action='store_true')
    args=parser.parse_args()
    target=HERE/'verification.json'
    if args.build and any(p.exists() for p in [target,*[HERE/k for k in CASES]]):
        raise FileExistsError('preserve existing packages and receipts')
    report={'schema_version':'parser-quality-v2-acceptance-v1','status':'passed_for_selected_repair',
        'parser_version':VERSION,'model_calls':0,'network_calls':0,'runner':ref(Path(__file__)),
        'acceptance_kind':'non-blind source-grounded deterministic acceptance, not complete parsing quality',
        'implementation':[ref(ROOT/name) for name in (
            'src/uteki/infrastructure/document_sources/sec_index.py',
            'src/uteki/infrastructure/document_sources/parsed_package.py')],
        'tests':tests(),'documents':{k:run(k,v,args.build) for k,v in CASES.items()}}
    if args.build:
        with target.open('xb') as stream:
            stream.write(package.canonical(report))
    else:
        assert target.read_bytes()==package.canonical(report),'stored receipt differs'
    print(json.dumps({'status':report['status'],'tests':report['tests']['tests_run'],
        'documents':{k:v['counts'] for k,v in report['documents'].items()}},ensure_ascii=False))


if __name__=='__main__':
    main()
