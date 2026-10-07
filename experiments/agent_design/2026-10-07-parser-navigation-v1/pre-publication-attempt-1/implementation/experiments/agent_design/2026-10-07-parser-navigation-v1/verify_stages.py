#!/usr/bin/env python3
"""Offline A/B acceptance. --build exclusively creates new packages/reports.

--check preserves stored outputs and rebuilds four packages in temporary folders.
Original HTML and all preceding packages are read-only. No model/HTTP calls.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import io
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT))
from uteki.agents.reading.document_reader import DocumentReader
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline

FOUNDATION = HERE.parent/'2026-10-07-data-foundation-v1'
CASES = runpy.run_path(str(FOUNDATION/'audit_parser.py'))['CASES']
STAGES = {'a':'sec-source-blocks-v0.1.9', 'b':'sec-source-blocks-v0.1.10'}
IMPLEMENTATION = ['src/uteki/infrastructure/document_sources/sec_index.py',
    'src/uteki/infrastructure/document_sources/parsed_package.py',
    'src/uteki/agents/reading/document_reader.py',
    'src/uteki/infrastructure/research_data/query_service.py']
TESTS = ['test_sec_navigation_stages', 'test_sec_parser_versions', 'test_parsed_package',
    'test_sec_anchor_ownership', 'test_sec_visible_outline', 'test_sec_index_tables',
    'test_document_reader', 'test_reading_groups', 'test_compact_source_read',
    'test_scoped_query_service', 'test_company_materialization', 'test_sec_document_index',
    'test_nested_source_blocks', 'test_sec_index_comments']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def ref(path):
    return {'path':path.relative_to(ROOT).as_posix(), 'sha256':sha(path.read_bytes())}


def files(folder):
    return {p.relative_to(folder).as_posix():sha(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}


def blocks(folder):
    return [json.loads(line) for line in (folder/'blocks.jsonl').read_bytes().splitlines()]


def node_shape(node):
    return {k:v for k,v in node.items() if k not in {'node_id','parent_id'}}


def test_suite():
    suite = unittest.TestLoader().loadTestsFromNames(['tests.unit.'+name for name in TESTS])
    output = io.StringIO()
    result = unittest.TextTestRunner(stream=output, verbosity=1).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(output.getvalue())
    return {'status':'passed', 'tests_run':result.testsRun, 'modules':TESTS,
            'kind':'offline deterministic program checks; no model evaluation'}


def preserve_and_replay(label, config):
    dataset = ROOT/config['dataset']
    source = next(s for s in read(dataset/'sources.json') if s['source_snapshot_id'] == config['source_id'])
    raw_path, old = dataset/source['raw_file'], dataset/source['index_folder']
    raw = raw_path.read_bytes()
    assert sha(raw) == config['raw_sha256']
    assert sha((old/'manifest.json').read_bytes()) == config['package_manifest_sha256']
    identity = {k:v for k,v in read(old/'source.json').items() if k in package.SourceIdentity.model_fields}
    prior = [old, FOUNDATION/('anchor-fix-'+label), FOUNDATION/('anchor-fix-v2-'+label)]
    preserved = {folder.relative_to(ROOT).as_posix():files(folder) for folder in prior}
    replay = {}
    for version, folder in [('sec-source-blocks-v0.1.7',old), ('sec-source-blocks-v0.1.8',prior[-1])]:
        package.verify_parsed_package(folder)
        parsed = parse_sec_source(identity['document_id'], identity['source_url'], raw,
            source_snapshot_id=identity['source_snapshot_id'], form_type=identity['form_type'], parser_version=version)
        expected = {'blocks.jsonl':b''.join(package.canonical(asdict(b)) for b in parsed.blocks),
            'anchors.json':package.canonical([asdict(a) for a in parsed.anchors]),
            'toc.json':package.canonical([asdict(t) for t in parsed.toc_entries]),
            'index.json':package.canonical(asdict(build_legal_outline(parsed)))}
        replay[version] = {name:data == (folder/name).read_bytes() for name,data in expected.items()}
        assert all(replay[version].values()), f'{label} historical behavior changed'
    return raw, identity, prior[-1], {'raw':ref(raw_path), 'legacy_content_replay':replay,
        'historical_packages_sha256':preserved,
        'manifest_rebuild_policy':'Old complete manifests require their original implementation/environment. Stored old package bytes remain intact; original content semantics replay under current code.'}


def run_stage(stage, label, raw, identity, baseline, historical, oracle, build):
    folder = HERE/f'stage-{stage}-{label}'
    selected = {**identity, 'parser_version':STAGES[stage]}
    if build:
        package.build_parsed_package(raw, selected, folder)
    verified = package.verify_parsed_package(folder, expected_source=selected)
    with tempfile.TemporaryDirectory(prefix='uteki-navigation-replay-') as temp:
        rebuilt = Path(temp)/'package'
        package.build_parsed_package(raw, selected, rebuilt)
        assert files(rebuilt) == files(folder), 'current package byte replay differs'
    before, after = blocks(baseline), blocks(folder)
    assert len(before) == len(after)
    assert [{k:v for k,v in b.items() if k != 'layout_role'} for b in before] == [
           {k:v for k,v in b.items() if k != 'layout_role'} for b in after]
    assert (folder/'anchors.json').read_bytes() == (baseline/'anchors.json').read_bytes()
    assert (folder/'assets.json').read_bytes() == (baseline/'assets.json').read_bytes()
    nav = [b for b in after if b['layout_role'] == 'repeated_navigation']
    expected_nav = oracle['navigation']['occurrences']
    assert {b['block_id'] for b in nav} == {b['block_id'] for b in expected_nav}, 'independent navigation oracle differs'
    reader, old_reader = DocumentReader(folder), DocumentReader(baseline)
    root_node, old_root = reader.index['nodes'][0]['node_id'], old_reader.index['nodes'][0]['node_id']
    search = reader.search(root_node, 'Table of Contents', limit=8)
    old_search = old_reader.search(old_root, 'Table of Contents', limit=8)
    assert old_search['total'] - search['total'] == len(nav)
    assert search['omitted_block_count'] == len(nav)
    examples = []
    for b in [nav[0], nav[len(nav)//2], nav[-1]]:
        result = reader.read(root_node, b['block_id'], count=1)
        assert result['blocks'] == [] and result['omitted_block_ids'] == [b['block_id']]
        examples.append({'requested_block_id':b['block_id'], 'result':result})
    nodes = [n for n in reader.index['nodes'] if n['kind']=='item']
    by_id = {b['block_id']:b for b in after}
    old_index = read(baseline/'index.json')
    boundary_checks = []
    if stage == 'a' or label == 'amd':
        old_nodes = [n for n in old_index['nodes'] if n['kind']=='item']
        assert len(nodes) == len(old_nodes)
        for old, new in zip(old_nodes,nodes,strict=True):
            assert all(old[key] == new[key] for key in ('title','part_number','item_number','start_block_id','source_anchor','reported_page'))
            left, right = by_id[new['end_block_id']]['ordinal'], by_id[old['end_block_id']]['ordinal']
            assert left <= right and all(b['layout_role'] for b in after[left:right])
    else:
        expected_items = oracle['outline']['items']
        assert len(nodes) == len(expected_items)
        for new, expected in zip(nodes,expected_items,strict=True):
            assert (new['part_number'],new['item_number'],new['title'],new['start_block_id'],new['source_anchor'],new['reported_page']) == (
                expected['part'],expected['item_number'],expected['title'],expected['start_block_id'],expected['source_anchor'],expected['reported_page'])
            left = by_id[new['end_block_id']]['ordinal']
            right = expected['expected_contiguous_navigation_end_ordinal']
            assert left <= right and all(b['layout_role'] for b in after[left:right]), 'body omitted from legal navigation interval'
            boundary_checks.append({'item_number':new['item_number'], 'published_end_block_id':new['end_block_id'],
                'oracle_untrimmed_end_block_id':expected['expected_contiguous_navigation_end_block_id'],
                'trimmed_only_layout':True})
        assert (folder/'blocks.jsonl').read_bytes() == (HERE/f'stage-a-{label}'/'blocks.jsonl').read_bytes()
    for old_path, hashes in historical['historical_packages_sha256'].items():
        assert files(ROOT/old_path) == hashes
    locators = [{**n, 'start_dom_path':by_id[n['start_block_id']]['dom_path'],
        'start_ordinal':by_id[n['start_block_id']]['ordinal'], 'end_ordinal':by_id[n['end_block_id']]['ordinal'],
        'html_fragment':'#'+n['start_block_id'], 'range_semantics':'contiguous navigation interval; not semantic membership'} for n in nodes]
    return {'company_id':identity['company_id'], 'period_end':identity['report_period_end'],
        'package_path':folder.relative_to(ROOT).as_posix(), 'manifest':ref(folder/'manifest.json'),
        'files_sha256':files(folder), 'package_verification':verified, 'rebuild_identical':True,
        'source_blocks_equal_except_layout_role':True, 'anchors_and_assets_identical_to_v018':True,
        'historical_packages_preserved':True, 'historical':historical,
        'counts':{'blocks':len(after), 'tables':sum(bool(b['table']) for b in after),
            'cells':sum(len(b['table']['cells']) for b in after if b['table']), 'navigation_blocks':len(nav),
            'navigation_text_characters':sum(len(b['text']) for b in nav),
            'item_nodes':len(nodes), 'part_nodes':sum(n['kind']=='part' for n in reader.index['nodes']),
            'search_hits_before':old_search['total'], 'search_hits_after':search['total']},
        'navigation_blocks':[{key:b[key] for key in ('block_id','ordinal','dom_path','text','text_hash','layout_role','style_signature')} for b in nav],
        'navigation_target':oracle['navigation']['expected_target_id'],
        'reader_examples':{'search_before':old_search, 'search_after':search, 'read_navigation':examples},
        'item_nodes':locators, 'boundary_checks':boundary_checks,
        'diagnostics':reader.index['diagnostics'],
        'limits':['Full source blocks remain accessible to explicit extraction packets and document.html.',
                  'Only default DocumentReader search/read and their Query consumers apply the navigation filter.',
                  'No actual model call, token savings measurement, complete semantic review, PDF or OCR verification.']}


def markdown(report):
    stage = report['stage'].upper()
    rows = [f"| {name.upper()} | {r['counts']['navigation_blocks']} | {r['counts']['search_hits_before']} → {r['counts']['search_hits_after']} | {r['counts']['item_nodes']} | {r['counts']['blocks']} / {r['counts']['cells']} |"
            for name,r in report['documents'].items()]
    return '\n'.join([f'# 阶段 {stage} 验收：{report["parser_version"]}', '',
        '状态：本地实现和程序验收完成；没有模型或网络请求。全文件结构扫描不等于逐段金融语义核验。', '',
        '| 材料 | 标记导航块 | 实际搜索命中 旧→新 | Item 节点 | 保留块 / 单元格 |',
        '|---|---:|---:|---:|---:|', *rows, '',
        '## 算法与消费者', '',
        'A：完整短 Table of Contents 链接必须回到唯一、可见、已核对的目录位置，并按相同目标、标签和版式重复至少两次。字体大小/行高不参与版式分组，不推断 em/px 换算。目录本身、叙事句、单次链接、带页码变体、未知/隐藏/重复目标与整文 wrapper 回链保守保留。原文仅增 repeated_navigation 角色；块 ID、表格、单元格与锚点不变。', '',
        '默认 DocumentReader search/read 实际省略这些块。search 返回省略总数及最多 12 个 ID；read 返回本页全部省略 ID。单块导航读取返回空正文，不自动改读其他块。Scoped Query 返回 layout_only、not_disclosed=false 和来源遍历 cursor；不计入已读正文。原始 document.html、reader.blocks 和显式提取 packet 仍保留全部块，不宣称所有模型入口均过滤。', '',
        'B：v0.1.10 保留表格 type/ID/cells，只将单行两格的短 ITEM 编号/拉丁字母标题，与当前 Part、唯一目录身份、目录标题及准确源锚点共同核对。目录空 spacer 不再当成标题/页码；已核对目录锚点和页码用于新节点。嵌套、非拉丁标题、未知 Part、复杂财务表与冲突不发布 Item；正确目录标题但错误锚点仍留下边界，避免前一章吞入未确认内容。非表格长叙事中的 Item 引用不作为新版本边界。', '',
        'Part/Item 范围只表示源文件连续导航区间，尾部布局块可收缩。TSMC Item 17 引用 Item 18，Item 18 引向 F-1；Item 19 后的签名、财务索引及 F 页不因落在连续范围内就属于 Exhibits 语义。', '',
        '## 验证与复跑', '',
        f"本脚本执行 {report['tests']['tests_run']} 项聚焦离线检查。独立合成 Orion/2031 与 Acme/2031–2032 验证正反例、空导航、末尾/跨节点、cursor、另一公司作用域，以及版本拒绝。真实 AMD/TSMC 对照独立原 DOM oracle；每个新包 15 文件验证并在临时目录完整字节重建。", '',
        'v0.1.7 和 v0.1.8 的 blocks、anchors、toc、index 四项按旧输入重放一致。旧包和原始 HTML 全部保持原哈希。旧完整 manifest 含当时实现指纹，完整字节重建仍需当时代码/环境；新包使用本轮最终共享实现指纹。两个新阶段分别选 .9 与 .10，不覆盖旧产物。', '',
        '```sh', '.venv/bin/python experiments/agent_design/2026-10-07-parser-navigation-v1/verify_stages.py --check', '```', '',
        f'细节、样例响应、逐节点边界和文件 SHA-256 见 [stage-{report["stage"]}-verification.json](stage-{report["stage"]}-verification.json)。', '',
        f'[AMD document.html](stage-{report["stage"]}-amd/document.html) · [TSMC document.html](stage-{report["stage"]}-tsmc/document.html)', '',
        '下一步：用户查看阶段验收页和源文件位置；之后再评估简报/结构化抽取。未覆盖格式应保留缺口，不根据这两份材料宣称所有发行人通用。', ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build',action='store_true')
    mode.add_argument('--check',action='store_true')
    args = parser.parse_args()
    paths = [HERE/f'stage-{stage}-{label}' for stage in STAGES for label in CASES]
    outputs = [HERE/f'stage-{stage}-verification{suffix}' for stage in STAGES for suffix in ('.json','.zh-CN.md')] + [HERE/'verification.json']
    if args.build and any(p.exists() for p in paths+outputs):
        raise FileExistsError('preserve existing stage artifacts')
    tests = test_suite()
    oracle = read(HERE/'independent-oracle.json')
    cases = {label:preserve_and_replay(label, config) for label,config in CASES.items()}
    stage_reports = {}
    for stage, version in STAGES.items():
        report = {'schema_version':'parser-navigation-stage-verification-v1', 'stage':stage,
            'parser_version':version, 'status':'local_program_checks_passed', 'model_calls':0, 'network_calls':0,
            'runner':ref(Path(__file__).resolve()), 'implementation':[ref(ROOT/name) for name in IMPLEMENTATION],
            'independent_oracle':ref(HERE/'independent-oracle.json'), 'tests':tests,
            'documents':{label:run_stage(stage,label,*values,oracle['companies'][label],args.build) for label,values in cases.items()}}
        stage_reports[stage] = report
    for stage,report in stage_reports.items():
        for path,data in [(HERE/f'stage-{stage}-verification.json',package.canonical(report)),
                          (HERE/f'stage-{stage}-verification.zh-CN.md',markdown(report).encode())]:
            if args.build:
                with path.open('xb') as stream: stream.write(data)
            else:
                assert path.read_bytes() == data, 'stored stage verification differs'
    summary = {'schema_version':'parser-navigation-verification-v1','status':'passed', 'tests':tests,
        'stages':{stage:{'parser_version':STAGES[stage], 'report':ref(HERE/f'stage-{stage}-verification.json'),
            'documents':{label:{'package_path':r['package_path'],'counts':r['counts'],'manifest':r['manifest']}
                         for label,r in report['documents'].items()}} for stage,report in stage_reports.items()},
        'model_calls':0,'network_calls':0}
    if args.build:
        with (HERE/'verification.json').open('xb') as stream: stream.write(package.canonical(summary))
    else:
        assert (HERE/'verification.json').read_bytes() == package.canonical(summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
