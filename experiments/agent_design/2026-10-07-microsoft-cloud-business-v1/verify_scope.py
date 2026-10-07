"""Verify complete DOM text coverage for this explicit subsection, without a model."""
import hashlib
import html as escape_html
import importlib.util
import json
from pathlib import Path
from lxml import html

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('cloud_input',HERE/'prepare_input.py')
source=importlib.util.module_from_spec(spec);spec.loader.exec_module(source)
sha=lambda b:hashlib.sha256(b).hexdigest()
p,manifest,audit=source.make_packet()
assert json.loads((HERE/'input/source_packet.json').read_bytes()) == p
raw=source.SOURCE.read_bytes();dom=html.fromstring(raw);tree=dom.getroottree()
by_path={tree.getpath(e):e for e in dom.iter()}
start=by_path[audit['boundary']['start']['source_dom_path']]
end=by_path[audit['boundary']['end_exclusive']['source_dom_path']]
texts=dom.xpath('//text()')
def start_index(el):
    return next(i for i,t in enumerate(texts) if not t.is_tail and (t.getparent() is el or el in t.getparent().iterancestors()))
left,right=start_index(start),start_index(end)
section=[b for b in p['blocks'] if b['input_role']=='selected_subsection']
elements={by_path[b['source_dom_path']]:b['id'] for b in section}
covered,missing,multiple=[],[],[]
for text in texts[left:right]:
    if not str(text).strip():continue
    parent=text.getparent().getparent() if text.is_tail else text.getparent()
    ancestors={parent,*parent.iterancestors()}
    owners=[bid for el,bid in elements.items() if el in ancestors]
    if not owners:missing.append(dict(parent_path=tree.getpath(parent),text=str(text)))
    elif len(owners)>1:multiple.append(owners)
    else:covered.append(dict(block_id=owners[0],text_sha256=sha(str(text).encode())))
assert not missing and not multiple,'selected_blocks_do_not_cover_unique_original_subsection_text'
# Block boundaries insert explicit LF for readable model input; no non-whitespace
# character is dropped, rearranged or synthesized across the continuous source.
original=''.join(str(t) for t in texts[left:right])
joined='\n'.join(b['text'] for b in section)
nonwhite=lambda s:''.join(s.split())
assert nonwhite(original)==nonwhite(joined)
result=dict(schema_version='subsection-dom-coverage-v1',status='passed',
 source_sha256=sha(raw),source_packet_sha256=sha((HERE/'input/source_packet.json').read_bytes()),
 scope=dict(company_id=p['company_id'],document_id=p['document_id'],period_end=p['period_end']),
 boundary=audit['boundary'],selected_subsection_block_count=len(section),
 nonblank_original_text_nodes=len(covered),uncovered_original_text_nodes=missing,multiply_owned_text_nodes=multiple,
 all_subsection_nonwhitespace_characters_equal=True,
 subsection_nonwhitespace_text_sha256=sha(nonwhite(original).encode()),
 scope_metadata_block_ids=p['extraction_scope']['scope_metadata_block_ids'],
 method='Scan original HTML text nodes in document order from Intelligent Cloud heading inclusive to More Personal Computing heading exclusive. Every nonblank text node must have exactly one selected block ancestor. Independently compare the entire range character-for-character after removing whitespace; block-boundary LF is explicit normalization, not a source character.',
 constraints=['No browser rendering or model call; source text completeness does not prove source semantic interpretation.','Metadata blocks are outside the contiguous subsection and were individually checked against original DOM.'],model_api_calls=0)
source.freeze(HERE/'input/dom-coverage-verification.json',source.json_bytes(result))
E=escape_html.escape
body=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Microsoft FY2025 Intelligent Cloud · 冻结原文</title><style>body{max-width:900px;margin:30px auto;padding:0 24px;font:16px/1.7 system-ui;color:#252a2a;background:#f7f8f5}article{background:white;padding:20px;margin:18px 0;border:1px solid #dce2de;border-radius:10px}code{overflow-wrap:anywhere;font-size:12px}p{white-space:pre-wrap}small{color:#65716b}a{color:#386653}</style><h1>Microsoft FY2025 · Intelligent Cloud</h1><p>完整原文小节（含竞争部分）加 4 块公司 / 期间 / 分部元数据。段落仅折叠空白，模型输入和本页逐块一致。本页没有模型答案或验收期待。</p>']
for b in p['blocks']:
 body.append(f'<article id="{E(b["id"])}"><small>{b["ordinal"]} · {E(b["input_role"])}</small><p>{E(b["text"])}</p><details><summary>原文定位与指纹</summary><code>{E(b["source_dom_path"])}<br>{b["text_sha256"]}</code></details></article>')
body.append('</html>')
source.freeze(HERE/'input/source-evidence.html','\n'.join(body).encode())
print(json.dumps({k:result[k] for k in ('status','nonblank_original_text_nodes','all_subsection_nonwhitespace_characters_equal','subsection_nonwhitespace_text_sha256')}))
