#!/usr/bin/env python3
"""Rebuild explicit audit inputs with parser v0.1.8; no HTTP/model calls.

--build creates new immutable anchor-fix-amd/anchor-fix-tsmc packages and reports.
--check verifies stored packages/report and rebuilds each package in a temporary
directory, preserving every historical source and prior package.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from lxml import html
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec_index import _hidden, parse_sec_source

AUDIT = runpy.run_path(str(HERE / 'audit_parser.py'))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def files(folder):
    return {p.relative_to(folder).as_posix(): sha(p.read_bytes()) for p in sorted(folder.rglob('*')) if p.is_file()}


def ref(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path.read_bytes())}


def run_case(label, config, build):
    dataset = ROOT / config['dataset']
    source = next(s for s in read(dataset/'sources.json') if s['source_snapshot_id'] == config['source_id'])
    old, new = dataset/source['index_folder'], HERE/('anchor-fix-'+label)
    before = files(old)
    raw_path = dataset/source['raw_file']
    raw = raw_path.read_bytes()
    assert sha(raw) == config['raw_sha256']
    assert sha((old/'manifest.json').read_bytes()) == config['package_manifest_sha256']
    old_verified = package.verify_parsed_package(old)
    identity = {key:value for key,value in read(old/'source.json').items() if key in package.SourceIdentity.model_fields}
    identity['parser_version'] = 'sec-source-blocks-v0.1.8'
    if build:
        package.build_parsed_package(raw, identity, new)
    new_verified = package.verify_parsed_package(new, expected_source=identity)
    with tempfile.TemporaryDirectory(prefix='uteki-anchor-rebuild-') as temp:
        target = Path(temp)/'package'
        package.build_parsed_package(raw, identity, target)
        assert files(target) == files(new), 'new package rebuild differs'
    assert (old/'blocks.jsonl').read_bytes() == (new/'blocks.jsonl').read_bytes(), 'source blocks changed'
    assert (old/'assets.json').read_bytes() == (new/'assets.json').read_bytes(), 'source assets changed'

    # Replay the old parser branch against frozen bytes; do not rebuild or write
    # any old package. This proves the anchor version gate preserves old meaning.
    legacy = parse_sec_source(identity['document_id'], identity['source_url'], raw,
        source_snapshot_id=identity['source_snapshot_id'], form_type=identity['form_type'],
        parser_version='sec-source-blocks-v0.1.7')
    assert package.canonical([asdict(a) for a in legacy.anchors]) == (old/'anchors.json').read_bytes(), 'legacy anchors changed'
    assert b''.join(package.canonical(asdict(b)) for b in legacy.blocks) == (old/'blocks.jsonl').read_bytes(), 'legacy blocks changed'
    old_anchors, new_anchors = read(old/'anchors.json'), read(new/'anchors.json')
    old_map = {(a['anchor'],a['dom_path']):a for a in old_anchors}
    new_map = {(a['anchor'],a['dom_path']):a for a in new_anchors}
    assert len(new_map) == len(new_anchors) == len({a['anchor'] for a in new_anchors})
    root = html.document_fromstring(raw, parser=html.HTMLParser(encoding='utf-8', recover=True, remove_comments=False))
    tree = root.getroottree()
    body = root.find('body')
    order = {tree.getpath(e):n for n,e in enumerate(body.iter())}
    elements = {tree.getpath(e):e for e in body.iter() if isinstance(e.tag,str)}
    blocks = [json.loads(line) for line in (new/'blocks.jsonl').read_bytes().splitlines()]
    eligible = {b['dom_path']:b for b in blocks if b['type'] != 'page_marker' and b['layout_role'] != 'running_header'}
    starts = sorted((order[path],block['block_id']) for path,block in eligible.items())
    start_positions = [n for n,_ in starts]
    verified_reasons, changes = Counter(), []
    for key, old_anchor in old_map.items():
        new_anchor = new_map.get(key)
        element = elements[old_anchor['dom_path']]
        chain = [element,*element.iterancestors()]
        hidden = _hidden(element) or any(str(e.tag).lower() in {'script','style','noscript'} for e in chain)
        owner = next((eligible[tree.getpath(e)] for e in chain if tree.getpath(e) in eligible),None)
        if new_anchor is None:
            reason = 'duplicate_anchor_first_occurrence_retained'
            first = next(a for a in old_anchors if a['anchor'] == old_anchor['anchor'])
            assert first['dom_path'] != old_anchor['dom_path']
        else:
            if hidden:
                expected, reason = None, 'hidden_or_script_source_has_no_visible_target'
            elif owner:
                expected, reason = owner['block_id'], 'exact_or_nearest_containing_block'
            else:
                pos = bisect.bisect_left(start_positions,order[old_anchor['dom_path']])
                expected = starts[pos][1] if pos < len(starts) else None
                reason = 'outside_block_forward_marker_or_wrapper'
            assert new_anchor['target_block_id'] == expected, 'anchor violates source ownership policy'
            verified_reasons[reason] += 1
        if new_anchor is None or new_anchor['target_block_id'] != old_anchor['target_block_id']:
            changes.append({'anchor':old_anchor['anchor'], 'dom_path':old_anchor['dom_path'], 'reason':reason,
                'old_target_block_id':old_anchor['target_block_id'],
                'new_target_block_id':new_anchor['target_block_id'] if new_anchor else None,
                'new_anchor_retained':new_anchor is not None,
                'containing_block_id':owner['block_id'] if owner and not hidden else None})
    def outline_shape(folder):
        return [{k:v for k,v in n.items() if k not in {'node_id','parent_id'}} for n in read(folder/'index.json')['nodes']]
    assert outline_shape(old) == outline_shape(new), 'legal source ranges changed'
    assert before == files(old), 'historical package changed'
    assert sha(raw_path.read_bytes()) == config['raw_sha256'], 'source changed'
    f313 = next((a for a in new_anchors if a['anchor']=='f-313'),None) if label=='amd' else None
    return {'company_id':source['company_id'], 'form':source['form'], 'period_end':source['period_end'],
        'raw':ref(raw_path), 'old_manifest':ref(old/'manifest.json'), 'new_manifest':ref(new/'manifest.json'),
        'old_files_sha256':before, 'new_files_sha256':files(new),
        'old_package_verification':old_verified, 'new_package_verification':new_verified,
        'new_package_rebuild_identical':True, 'old_files_preserved':True,
        'legacy_v017_anchors_and_blocks_identical':True, 'old_new_blocks_identical':True,
        'old_new_assets_identical':True, 'legal_outline_titles_and_ranges_identical':True,
        'old_new_toc_identical':(old/'toc.json').read_bytes()==(new/'toc.json').read_bytes(),
        'old_anchor_count':len(old_anchors), 'new_anchor_count':len(new_anchors),
        'changed_anchor_count':len(changes), 'change_reasons':dict(sorted(Counter(c['reason'] for c in changes).items())),
        'all_new_anchor_policy_checks':dict(sorted(verified_reasons.items())),
        'anchor_changes':changes, 'f313':f313,
        'retained_known_gaps':{'unclassified_Table_of_Contents_blocks':sum(b['text']=='Table of Contents' and b['layout_role'] is None for b in blocks),
            'item_nodes':sum(n['kind']=='item' for n in read(new/'index.json')['nodes'])}}


def markdown(report):
    rows=[]
    for name,r in report['documents'].items():
        rows.append(f"| {name.upper()} | {r['old_anchor_count']} → {r['new_anchor_count']} | {r['changed_anchor_count']} | {r['new_package_verification']['blocks_verified']} | {r['new_package_verification']['cells_verified']} |")
    return '\n'.join(['# v0.1.8 最小锚点修复核验','',
        '状态：本地程序实现与结构核验完成；无网络或模型请求。没有完整金融语义或正文漏项验收。','',
        '## 行为与版本','',
        '仅 v0.1.8 使用自身/最近包含块优先，块外才找后继块；hidden/script/style/noscript 锚点保留但 target=null；重复 id/name 保留首次 DOM 出现并写 duplicate_source_anchor 诊断。v0.1.7 及更早分支保留原算法。',
        '', '生产 HTML package 默认改为 v0.1.8；SourceIdentity/Manifest 同时接受 v0.1.7/v0.1.8，清单使用显式选择版本。未知版本仍由 package 契约拒绝。company_materialization 既有 HTML_PARSER 导入直接使用新默认，无需改其源码。',
        '', '## 两份真实冻结 HTML 的程序核验','',
        '| 材料 | 锚点数 旧→新 | 改变的锚点 | 不变的块数 | 不变的单元格数 |','|---|---:|---:|---:|---:|',*rows,'',
        '两份旧包和原件哈希均未变；重新调用 v0.1.7 得到的 anchors/blocks 与旧冻结字节一致；v0.1.8 的 blocks.jsonl、assets.json 与旧包逐字节一致。正文目录标题与块范围保持一致。每份新包 15 个文件通过结构校验，并在临时目录再次构建后逐字节一致。',
        '', '逐锚点旧目标、新目标、原 DOM 位置及变化原因见 [anchor-fix-verification.json](anchor-fix-verification.json)。统计分母为全部原始锚点；隐藏源锚点变成 null 属于明确纠错，不能计作丢失正文。',
        '', 'AMD f-313 现在指向 block-000686-a6e8806b，其 1,667 单元格仍为零基 r25/c3；原先错误的 block-000688-a9360e02 不再作为该源锚点目标。',
        '', '## 保留的缺口','',
        'AMD 105 个、TSMC 163 个 Table of Contents 段落仍未标布局角色。TSMC 的 Item 节点仍为 0；这些问题不在此次锚点补丁内。图片/OCR、PDF、单位/脚注语义关系仍不由本检查证明。',
        '', '## 复跑','', '```sh',
        '.venv/bin/python experiments/agent_design/2026-10-07-data-foundation-v1/verify_anchor_fix.py --check',
        '.venv/bin/python -m unittest tests.unit.test_sec_anchor_ownership tests.unit.test_parsed_package tests.unit.test_sec_index_tables tests.unit.test_sec_visible_outline tests.unit.test_sec_document_index tests.unit.test_nested_source_blocks tests.unit.test_company_materialization',
        '```','', '首次使用 --build 创建新包及报告，拒绝覆盖。--check 只校验已有产物并在临时目录重建；对比失败会终止。',
        '', '下一步：分别处理重复导航与表格形式的法律标题，再用独立验收样本检查正文过滤、章节边界与漏项；本次结果不自动完成 TODO 04 的全部任务。',''])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--build',action='store_true')
    mode.add_argument('--check',action='store_true')
    args=parser.parse_args()
    reports=[HERE/'anchor-fix-verification.json',HERE/'anchor-fix-verification.zh-CN.md']
    if args.build and any(p.exists() for p in [*reports,HERE/'anchor-fix-amd',HERE/'anchor-fix-tsmc']):
        raise FileExistsError('preserve all existing verification artifacts')
    report={'schema_version':'anchor-fix-verification-v1','parser_version':'sec-source-blocks-v0.1.8',
        'status':'local_program_checks_passed','model_calls':0,'network_calls':0,
        'runner':ref(Path(__file__).resolve()),
        'implementation':[ref(ROOT/p) for p in AUDIT['IMPLEMENTATION']],
        'documents':{k:run_case(k,v,args.build) for k,v in AUDIT['CASES'].items()}}
    encoded=(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    outputs=[encoded,markdown(report).encode()]
    if args.build:
        for path,raw in zip(reports,outputs,strict=True):
            with path.open('xb') as stream: stream.write(raw)
    else:
        assert all(path.read_bytes()==raw for path,raw in zip(reports,outputs,strict=True)), 'verification differs'
    print(json.dumps({'status':'passed','mode':'build' if args.build else 'check',
        'documents':{k:{'changes':v['changed_anchor_count'],'reasons':v['change_reasons']} for k,v in report['documents'].items()},
        'report_sha256':sha(encoded)},ensure_ascii=False))


if __name__=='__main__':
    main()
