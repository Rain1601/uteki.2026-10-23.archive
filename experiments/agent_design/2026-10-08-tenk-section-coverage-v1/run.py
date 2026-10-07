"""Explicit three-company frozen HTML 10-K structural audit; no model calls."""
import gzip
import hashlib
import json
from pathlib import Path

from uteki.infrastructure.document_sources.coverage_audit import audit_html_tenk
from uteki.agents.reading.document_reader import DocumentReader

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
CASES = [
    ('Microsoft FY2025', 'msft', 'data/company_workspace/extraction_ab_v1/corpus/msft/dataset'),
    ('Alphabet FY2025', 'googl', 'data/company_workspace/extraction_ab_v1/corpus/googl/dataset'),
    ('AMD FY2023', 'amd', 'experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-amd/dataset'),
]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    summaries = []
    for label, key, dataset in CASES:
        package = ROOT / 'experiments/agent_design/2026-10-07-foundation-parallel-v1/parser/packages' / key
        source = json.loads((package / 'source.json').read_text())
        sources = json.loads((ROOT / dataset / 'sources.json').read_text())
        matches = [s for s in sources if s['source_snapshot_id'] == source['source_snapshot_id']]
        assert len(matches) == 1
        raw_path = ROOT / dataset / matches[0]['raw_file']
        hashes = {str(p.relative_to(ROOT)): digest(p) for p in [raw_path, *(package / n for n in ('source.json','manifest.json','index.json','blocks.jsonl'))]}
        reader = DocumentReader(package)
        result = audit_html_tenk(raw_path.read_bytes(), source, reader.index, reader.blocks)
        result['label'] = label
        result['input_sha256'] = hashes
        result['package_path'] = str(package.relative_to(ROOT))
        result['original_path'] = str(raw_path.relative_to(ROOT))
        result['diagnostics'] = reader.index['diagnostics']
        result['reader_note_links'] = [g for g in reader.groups if g.get('note_links')]
        ledger = result.pop('text_ledger')
        (HERE / f'{key}-text-ledger.jsonl.gz').write_bytes(gzip.compress(''.join(json.dumps(e,ensure_ascii=False,sort_keys=True)+'\n' for e in ledger).encode(), mtime=0))
        result['text_ledger_sha256'] = digest(HERE / f'{key}-text-ledger.jsonl.gz')
        result['originals_unchanged'] = hashes == {p:digest(ROOT / p) for p in hashes}
        assert result['originals_unchanged']
        (HERE / f'{key}-coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        summary = {k:result[k] for k in ('label','source','totals','finding_counts','status','todo03_complete','originals_unchanged')}
        summary['section_count'] = len(result['sections'])
        summaries.append(summary)
        lines = [f'# {label}：逐节结构覆盖核查', '',
                 '仅核对所选冻结 HTML 10-K 的 DOM 与解析文本。所有节的独立语义审阅及视觉阅读顺序审阅均未完成。', '',
                 f'原文：[官方原件]({source["source_url"]})；本机解析底稿：[{key}]({package.relative_to(HERE) if package.is_relative_to(HERE) else "../2026-10-07-foundation-parallel-v1/parser/packages/" + key + "/document.html"})。', '',
                 '| 导航区间 | 块 / 表 | 已覆盖文本段 | 规则排除段 | 未覆盖 / 文本缺失 | 未读图像等 | 跨节引用候选 |',
                 '|---|---:|---:|---:|---:|---:|---:|']
        for s in result['sections']:
            counts = s['counts']
            findings = s['findings']
            title = s['title'].replace('|','/')
            link = f'../2026-10-07-foundation-parallel-v1/parser/packages/{key}/document.html'
            if s['block_ids']:
                link += '#' + s['block_ids'][0]
            lines.append(f'| [{title}]({link}) | {len(s["block_ids"])} / {len(s["table_ids"])} | {counts.get("structurally_represented",0)} | {counts.get("excluded_by_inline_visibility_rule",0)} | {counts.get("uncovered_visible_text",0)} / {counts.get("represented_ancestor_but_text_missing",0)} | {sum(f["code"]=="visual_or_embedded_content_not_read" for f in findings)} | {sum(f["code"]=="cross_reference_candidate_not_resolved" for f in findings)} |')
        lines += ['', f'详单：[{key}-coverage.json]({key}-coverage.json)；完整原文文本处置账：[{key}-text-ledger.jsonl.gz]({key}-text-ledger.jsonl.gz)。', '',
                  '所有表格均保留单位、表头和值、完整脚注适用性的未审状态；“未覆盖为 0”只证明声明规则下的结构覆盖。跨节引用仅为原文模式匹配候选，不等于已解析引用。可见图像、SVG 等保留定位但未解读内容，不能自动认定为装饰。']
        (HERE / f'{key}-sections.zh-CN.md').write_text('\n'.join(lines)+'\n')
    (HERE / 'verification.json').write_text(json.dumps({'schema_version':'selected-tenk-coverage-v1','model_calls':0,'cases':summaries},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
