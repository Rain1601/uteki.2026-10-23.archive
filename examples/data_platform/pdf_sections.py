"""Export an existing parsed version for review; never runs inference or downloads.

python -I examples/data_platform/pdf_sections.py --data-root /absolute/data \
    --parse-id <published-id> --export-dir /absolute/review
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from uteki.data_platform.documents import DocumentStore


def export(store, parse_id, destination):
    destination.mkdir(parents=True,exist_ok=True)
    package = store.export_package(parse_id)
    if package.parse.schema_version not in ('document-v2','document-v3'):
        raise ValueError('section review requires document-v2 with recorded body selection')
    schema = store.get_schema(parse_id)
    raw = json.loads(store.content.read_object(package.parse.parser_output_ref))
    lines = [f'# {package.material.name}', '', f'解析版本：`{parse_id}`', '',
             f'实际处理的物理页：{raw.get("processed_pages", "unknown")}', '',
             ('状态：目录沿用 PDF 原生书签，passages 按正文排版分组，分组质量须对照原文审阅。'
              if package.parse.schema_version=='document-v3' else
              '状态：目录含规则推断，须对照原文审阅；页覆盖不代表内容质量已全部验收。'), '',
             f'原件：{package.source.source_url or "未登记来源 URL"}', '',
             '## 目录', '', '| 原文标题 | code 路径 | 层级依据 |', '|---|---|---|']
    nodes=[]
    def visit(node):
        nodes.append(node)
        lines.append(f'| {node["title"].replace("|", "/")} | `{node["code_path"]}` | {node.get("hierarchy_basis") or "未观测祖先"} |')
        for child in node['children']:
            visit(child)
    for node in schema['directory']['nodes']:
        visit(node)
    uncertain=[n for n in nodes if n.get('hierarchy_basis') in
               ('bookmark_destination_only','unresolved_parent_candidate')]
    if uncertain:
        lines += ['', '## 待核对的目录', '',
                  '位置已登记不等于正文标题已匹配；以下内容保留，但最细层级尚未验收。', '',
                  '| 原始标题 | 物理页 | 当前依据 |', '|---|---|---|']
        for n in uncertain:
            pages=sorted({loc['page_number'] for loc in n['locations'] if 'page_number' in loc})
            lines.append(f'| {n["title"].replace("|", "/")} | {pages} | {n["hierarchy_basis"]} |')
    lines += ['', '## 正文', '']
    assigned=set()
    passage_export=[]
    for node in nodes:
        section=store.read_section(parse_id,node_id=node['node_id'],include_descendants=False)
        if not section['blocks']:
            continue
        lines += [f'### {node["title"]}', '', f'路径：`{node["code_path"]}`', '']
        groups=section.get('passages',[])
        starts={p['block_ids'][0]:p for p in groups}
        block_lookup={b['ref']['block_id']:b['block'] for b in section['blocks']}
        passage_export.append(dict(node_id=node['node_id'],title=node['title'],code_path=node['code_path'],passages=[
            dict(**p,path=f'{node["code_path"]}.passages[{p["index"]}]',
                 text='\n\n'.join(block_lookup[bid]['text'] for bid in p['block_ids'] if block_lookup[bid]['type']=='text'),
                 locations=[loc for bid in p['block_ids'] for loc in block_lookup[bid]['locations']]) for p in groups]))
        for item in section['blocks']:
            b=item['block'];assigned.add(b['block_id'])
            if b['block_id'] in starts:
                group=starts[b['block_id']]
                lines += [f'#### passages[{group["index"]}]', '',
                          f'读取地址：`{node["code_path"]}.passages[{group["index"]}]`', '',
                          f'分组依据：`{group["grouping_basis"]}`；原始块：`{", ".join(group["block_ids"])}`', '']
            pages=sorted({loc['page_number'] for loc in b['locations'] if 'page_number' in loc})
            lines += [f'来源块：`{b["block_id"]}`；物理页：{pages}', '']
            if b['type']=='text':
                if b['block_id']!=node.get('heading_block_id') or b['text']!=node['title']:
                    lines += [b['text'], '']
            elif b['type']=='table':
                table=b['table']
                if table['status']=='failed':
                    lines += ['**表格结构失败：** '+ '; '.join(table['issues']), '',
                              '原始单元格冲突保留在解析器原始输出中，不作为可靠结构化数据返回。', '']
                    for resource in b['resources']:
                        if resource['mime_type']=='image/png':
                            folder=destination/'resources';folder.mkdir(exist_ok=True)
                            filename=b['block_id']+'.png'
                            (folder/filename).write_bytes(store.read_resource(item['ref'],resource['resource_id']))
                            lines += [f'![原始表格区域](resources/{filename})', '']
                    continue
                grid=[['']*table['column_count'] for _ in range(table['row_count'])]
                for cell in table['cells']:
                    grid[cell['row']][cell['column']]=cell['text'].replace('|','/').replace('\n',' ')
                lines += ['表格内容（合并单元格只在起点展示；完整跨度和位置见 package.json）：', '',
                          '| '+' | '.join(f'列 {i+1}' for i in range(table['column_count']))+' |',
                          '| '+' | '.join(['---']*table['column_count'])+' |']
                lines += ['| '+' | '.join(row)+' |' for row in grid]
                lines.append('')
            else:
                lines += ['图片资源引用：`'+json.dumps(b['resources'],ensure_ascii=False)+'`', '']
    outside=[b for b in package.blocks if b.block_id not in assigned and b.body_selection.decision!='exclude']
    if outside:
        lines += ['## 未归属小节的内容（保留，须核对）', '']
        for b in outside:
            lines += [f'`{b.block_id}`：{b.text if b.text is not None else b.type}', '']
    lines += ['## 从默认正文排除的内容', '', '| 块 | 原文 | 理由 |', '|---|---|---|']
    for b in package.blocks:
        if b.body_selection.decision=='exclude':
            lines.append(f'| `{b.block_id}` | {(b.text or b.type).replace("|", "/")} | {b.body_selection.reason} |')
    lines += ['', '## 已知缺口', '']+[f'- {issue}' for issue in [*schema['directory']['issues'],*schema['issues']]]
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'sections.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (destination/'package.json').write_bytes(package.canonical_bytes())
    (destination/'schema.json').write_text(json.dumps(schema,ensure_ascii=False,indent=2),encoding='utf-8')
    if package.parse.passages is not None:
        (destination/'passages.json').write_text(json.dumps(dict(material_id=package.material.material_id,
            parse_id=parse_id,sections=passage_export),ensure_ascii=False,indent=2),encoding='utf-8')
    return dict(parse_id=parse_id,sections=len(nodes),blocks=len(package.blocks),
                passages=len(package.parse.passages or ()),review=str(destination/'sections.md'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--parse-id',required=True)
    parser.add_argument('--export-dir',type=Path,required=True)
    args=parser.parse_args()
    if not args.export_dir.is_absolute():
        parser.error('--export-dir must be absolute')
    with DocumentStore.open(args.data_root) as store:
        print(json.dumps(export(store,args.parse_id,args.export_dir),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
