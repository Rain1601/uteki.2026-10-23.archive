"""Versioned HTML line-break repair on explicitly selected frozen reports.

Creates only new packages; --check re-parses without changing saved artifacts.
No model calls, network calls, source rewriting or financial interpretation.
"""
from __future__ import annotations
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'src'))
from lxml import html
from uteki.infrastructure.document_sources import parsed_package as package
from uteki.infrastructure.document_sources.sec_index import parse_sec_source, _visible_text, _hidden
from uteki.infrastructure.document_sources.sec import normalize_text
from uteki.agents.reading.document_reader import DocumentReader

HERE=Path(__file__).resolve().parent
VERSION='sec-source-blocks-v0.1.12'
PREVIOUS='sec-source-blocks-v0.1.11'

def read(p): return json.loads(p.read_bytes())
def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def inputs():
    cases={}
    for label in ('amd','tsmc'):
        source=read(ROOT/f'experiments/agent_design/2026-10-07-parser-quality-v2/{label}/source.json')
        identity={k:source[k] for k in package.SourceIdentity.model_fields}
        raw=ROOT/f'experiments/agent_design/2026-10-07-parser-runtime-v1/prepare-{label}/dataset/raw/{source["source_snapshot_id"]}.html'
        cases[label]=(raw,identity)
    for label,snapshot in (('msft','msft-2025-10k'),('googl','googl-2025-10k')):
        folder=ROOT/f'data/company_workspace/extraction_ab_v1/corpus/{label}/dataset'
        source=next(s for s in read(folder/'sources.json') if s['source_snapshot_id']==snapshot)
        identity={'company_id':source['company_id'],'document_id':source['document_id'],
          'source_snapshot_id':source['source_snapshot_id'],'source_url':source['source_url'],
          'raw_sha256':source['raw_file_sha256'],'form_type':source['form'],
          'report_period_end':source['period_end'],'available_at':source['available_at'],
          'parser_version':VERSION,'export_version':package.EXPORT}
        cases[label]=(folder/source['raw_file'],identity)
    return cases

def run(label,raw_path,identity,check):
    raw=raw_path.read_bytes(); assert package.sha(raw)==identity['raw_sha256']
    args=dict(source_snapshot_id=identity['source_snapshot_id'],form_type=identity['form_type'])
    old=parse_sec_source(identity['document_id'],identity['source_url'],raw,parser_version=PREVIOUS,**args)
    new=parse_sec_source(identity['document_id'],identity['source_url'],raw,parser_version=VERSION,**args)
    assert len(old.blocks)==len(new.blocks)
    changes=[]; cell_changes=[]
    for a,b in zip(old.blocks,new.blocks,strict=True):
        assert (a.dom_path,a.ordinal,a.style_signature,a.reported_page)==(b.dom_path,b.ordinal,b.style_signature,b.reported_page)
        if a.text != b.text:
            changes.append({'ordinal':b.ordinal,'dom_path':b.dom_path,'before_block_id':a.block_id,
                            'after_block_id':b.block_id,'before':a.text,'after':b.text})
        if a.table:
            assert a.table.row_count==b.table.row_count and a.table.column_count==b.table.column_count
            assert len(a.table.cells)==len(b.table.cells)
            for ac,bc in zip(a.table.cells,b.table.cells,strict=True):
                assert (ac.row,ac.column,ac.rowspan,ac.colspan,ac.is_header)==(bc.row,bc.column,bc.rowspan,bc.colspan,bc.is_header)
                if ac.text != bc.text:
                    cell_changes.append({'ordinal':b.ordinal,'dom_path':b.dom_path,'block_id':b.block_id,
                                         'row':bc.row,'column':bc.column,'before':ac.text,'after':bc.text})
    root=html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8',recover=True,remove_comments=False));tree=root.getroottree()
    elements={tree.getpath(e):e for e in root.iter() if isinstance(e.tag,str)}
    represented={b.dom_path for b in new.blocks}; counts=Counter(); uncovered=[]
    for b in new.blocks:
        expected=normalize_text(elements[b.dom_path].get('alt','')) if b.type=='image' else normalize_text(_visible_text(elements[b.dom_path],preserve_line_breaks=True))
        assert expected==b.text
    for element in root.find('body').iter():
        for text,owner,kind in ((element.text,element,'text'),(element.tail,element.getparent(),'tail')):
            if not text or not normalize_text(text) or owner is None or not isinstance(owner.tag,str): continue
            ancestors=[owner,*owner.iterancestors()]
            if kind=='text' and not isinstance(element.tag,str): continue
            if _hidden(owner) or any(str(e.tag).lower() in {'script','style','noscript'} for e in ancestors):
                counts['excluded_hidden_or_script_segments']+=1;continue
            counts['visible_text_segments']+=1
            owners=[e for e in ancestors if tree.getpath(e) in represented]
            if not owners:
                counts['uncovered_visible_text_segments']+=1
                uncovered.append({'dom_path':tree.getpath(owner),'kind':kind,'text':normalize_text(text)[:160]})
            elif len(owners)>1: counts['multiply_covered_visible_text_segments']+=1
    selected={**identity,'parser_version':VERSION}
    folder=HERE/'packages'/label
    if not check: package.build_parsed_package(raw,selected,folder)
    verified=package.verify_parsed_package(folder,expected_source=selected)
    assert (folder/'blocks.jsonl').read_bytes()==b''.join(package.canonical(asdict(b)) for b in new.blocks)
    reader=DocumentReader(folder); document=next(n for n in reader.index['nodes'] if n['kind']=='document')
    probe=next((c for c in cell_changes if len(c['after'])>=8 and len(c['after'])<100),None)
    if probe:
        response=reader.search(document['node_id'],probe['after'],limit=20)
        assert any(h['block_id']==probe['block_id'] for h in response['hits'])
    result={'source':selected,'raw_path':str(raw_path.relative_to(ROOT)),
        'blocks':len(new.blocks),'tables':sum(b.table is not None for b in new.blocks),
        'changed_blocks':len(changes),'changed_cells':len(cell_changes),'cell_changes':cell_changes,
        'changes':changes,'dom_text_representation_mismatches':0,'dom_segment_coverage':dict(counts),
        'uncovered_samples':uncovered[:20], 'package_verification':verified,
        'reader_probe':probe,'original_hash_unchanged':digest(raw_path)==identity['raw_sha256'],
        'layout_coordinates_and_table_spans_unchanged':True,
        'scope':'structural text representation only; not complete semantic parsing acceptance'}
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    result={label:run(label,*case,args.check) for label,case in inputs().items()}
    report={'schema_version':'parser-line-break-acceptance-v1','parser_version':VERSION,'previous_version':PREVIOUS,
        'cases':result,'excluded':{'nvidia':'Existing frozen original is PDF. Derived example HTML is not an independent full-report parser test; PDF adapter remains separate.'},
        'model_calls':0,'cost_usd':0,'semantic_completeness':'not_established',
        'limitations':['Unit and footnote text are retained, but complete numeric-to-unit/note associations are not established.',
        'Cross-section prose references (e.g. Item 17/18 to statements) are not resolved by this repair.',
        'DOM containment is not reading order, CSS/browser visibility, OCR, table semantics or financial correctness.',
        'Changed normalized text changes affected block IDs/hashes; do not rebind frozen evidence silently.']}
    path=HERE/'verification.json'
    if args.check:
        assert read(path)==report,'frozen verification report differs'
    else: path.write_bytes(package.canonical(report))
    print(json.dumps({k:{f:v[f] for f in ('blocks','tables','changed_blocks','changed_cells','dom_segment_coverage')} for k,v in result.items()},indent=2))

if __name__=='__main__': main()
