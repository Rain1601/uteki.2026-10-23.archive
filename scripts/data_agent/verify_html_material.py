"""Acceptance-only source audit. Gold is explicit input, never product input."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from lxml import etree,html
from uteki.data_platform.catalog import Catalog
from uteki.data_platform.contracts.assets import AssetRef
from uteki.data_platform.contracts.evidence import HtmlEvidenceRef
from uteki.data_platform.retrieval.content import HtmlReader


def norm(text):return ' '.join(text.split())
def sha(raw):return hashlib.sha256(raw).hexdigest()


def hidden(node):
    for item in [node]+list(node.iterancestors()):
        name=str(item.tag).lower()
        if name in {'head','script','style','noscript','ix:header','ix:hidden','nav','header','footer'}:return True
        if 'hidden' in item.attrib or item.get('aria-hidden','').lower()=='true':return True
        declarations={}
        for rule in item.get('style','').lower().split(';'):
            if ':' in rule:
                key,value=rule.split(':',1);declarations[key.strip()]=value.replace('!important','').strip()
        if declarations.get('display')=='none' or declarations.get('visibility')=='hidden':return True
    return False


def display(node):
    copied=deepcopy(node)
    for child in list(copied.iterdescendants()):
        if child.getparent() is not None and (not isinstance(child.tag,str) or hidden(child)):
            child.drop_tree()
    for br in copied.iter('br'):br.tail=' '+(br.tail or '')
    etree.strip_tags(copied,'br')
    return norm(copied.text_content())


def audit(root,reference,gold,source_id):
    with Catalog.open(root) as catalog:
        manifest=catalog.read_published(reference)
        reader=HtmlReader(catalog,reference);inventory=reader.inventory()
        raw=catalog.content.read_object(reader.inputs.main)
        expected_source=gold['source_inventory'][source_id]
        assert sha(raw)==expected_source['sha256'],'raw source hash differs from frozen gold'
        document=html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8',no_network=True))
        tree=document.getroottree();nodes=list(document.iter());by_path={tree.getpath(n):n for n in nodes if isinstance(n.tag,str)}
        quality=json.loads(catalog.read_artifact(reference,'quality.json'))
        blocks=inventory['blocks'];tables=inventory['tables'];records=inventory['records']
        exclusions=quality['exclusions']
        source_tables={p for p,n in by_path.items() if n.tag=='table'}
        source_cells={p for p,n in by_path.items() if n.tag in {'td','th'}}
        source_facts={p for p,n in by_path.items() if n.tag.split(':')[-1]=='nonfraction'}
        actual_tables={t['locator']['dom_path'] for t in tables}
        actual_cells={c['locator']['dom_path'] for t in tables for c in t['cells']}
        assert len(actual_cells)==sum(len(t['cells']) for t in tables),'cell duplicated across tables'
        assert len(records)==len(source_facts)==expected_source['nonFraction']
        assert {r['locator']['dom_path'] for r in records}==source_facts
        assert len(source_tables)==expected_source['tables']
        for category,original,actual in [('table',source_tables,actual_tables),('table_cell',source_cells,actual_cells)]:
            omitted={e['path'] for e in exclusions if e['kind']==category}
            assert original==actual|omitted and not actual&omitted,(category,'unaccounted or duplicated source element')
            assert all(hidden(by_path[p]) for p in omitted),(category,'unjustified exclusion')
            assert all(not hidden(by_path[p]) for p in actual),(category,'hidden content included')
        assert {i['dom_path'] for i in inventory['images']}=={p for p,n in by_path.items() if n.tag=='img'}
        for image in inventory['images']:
            if image['status']=='excluded':assert hidden(by_path[image['dom_path']]) or not by_path[image['dom_path']].get('src')
        anchors={}
        for path,node in by_path.items():
            for key in set(filter(None,[node.get('id'),node.get('name') if node.tag=='a' else None])):
                anchors.setdefault(key,[]).append(path)
        checked_links=checked_values=0
        for table in tables:
            for cell in table['cells']:
                original=by_path[cell['locator']['dom_path']]
                source_links={tree.getpath(a):a.get('href') for a in original.iter('a') if a.get('href') and not hidden(a)}
                actual_links={link['link_path']:link for link in cell['footnote_links']}
                assert set(source_links)==set(actual_links)
                for path,href in source_links.items():
                    entry=actual_links[path];assert entry['href']==href
                    targets=anchors.get(href[1:],[]) if href.startswith('#') else []
                    expected='external' if not href.startswith('#') else 'resolved' if len(targets)==1 else 'ambiguous_target' if targets else 'missing_target'
                    assert entry['status']==expected
                    if expected=='resolved':assert entry['target_path']==targets[0] and targets[0] in cell['footnote_paths']
                    checked_links+=1
        # The real source's context IDs, exact periods and printed transformations
        # are checked independently, beyond the selected golden financial facts.
        identifiers={}
        for path,node in by_path.items():
            if node.get('id'):identifiers.setdefault(node.get('id'),[]).append((path,node))
        for record in records:
            source=by_path[record['locator']['dom_path']]
            for field,attr in [('concept','name'),('context_ref','contextref'),('unit_ref','unitref'),('scale','scale'),('sign','sign'),('format','format')]:
                assert record[field]==source.get(attr)
            contexts=identifiers[record['context_ref']];units=identifiers[record['unit_ref']]
            assert len(contexts)==len(units)==1
            assert record['context_path']==contexts[0][0] and record['unit_path']==units[0][0]
            context=contexts[0][1]
            period={key:norm(n.text_content()) for n in context.iter() for local,key in [('startdate','start'),('enddate','end'),('instant','instant')] if str(n.tag).split(':')[-1]==local}
            assert record['period']==period
            typed=any(str(n.tag).split(':')[-1]=='typedmember' for n in context.iter())
            if typed or (source.get('format') or '').endswith(':numwordsen'):
                assert record['status']=='unsupported' and record['value_decimal'] is None
            elif source.get('xsi:nil') in {'true','1'}:
                assert record['status']=='nil' and record['value_decimal'] is None
            else:
                assert record['status']=='parsed'
                printed=norm(source.text_content()).replace(',','').replace(' ','')
                value=Decimal(0) if (source.get('format') or '').endswith(':fixed-zero') else Decimal(printed)
                value*=Decimal(10)**int(source.get('scale','0'))
                if source.get('sign')=='-':value=-value
                assert Decimal(record['value_decimal'])==value
                checked_values+=1
        # Independently inspect every emitted locator and text; the product's
        # verifier is evidence of publication integrity, not our semantic oracle.
        located=blocks+[c for t in tables for c in t['cells']]+records
        for item in located:
            locator=item['locator'];node=by_path[locator['dom_path']]
            full=norm(node.text_content()) if locator['projection']=='raw_text_v1' else display(node)
            assert 0<=locator['char_start']<=locator['char_end']<=len(full)
            text=full[locator['char_start']:locator['char_end']]
            assert sha(text.encode())==locator['text_sha256'],locator
            assert item.get('text',item.get('raw_value'))==text,locator
        # Every visible source text atom belongs to an actual source-bound block.
        excluded_atoms={e['path'] for e in exclusions if e['kind']=='text_atom'}
        visible=covered=excluded_count=0
        for node in nodes:
            for is_tail,value in [(False,node.text),(True,node.tail)]:
                owner=node.getparent() if is_tail else node
                if owner is None or not isinstance(owner.tag,str) or not value or not norm(value):continue
                pointer=tree.getpath(node)+('/tail' if is_tail else '/text')
                if hidden(owner) or not isinstance(node.tag,str) and not is_tail:
                    assert pointer in excluded_atoms,pointer
                    excluded_count+=1;continue
                visible+=1
                ancestors={tree.getpath(n) for n in [owner]+list(owner.iterancestors())}
                candidates=[b for b in blocks if b['locator']['dom_path'] in ancestors and norm(value) in b['text']]
                assert candidates,('visible source atom has no source-bound content',pointer,norm(value)[:80])
                assert pointer not in excluded_atoms
                covered+=1
        assert visible==covered==quality['counts']['visible_text_atoms']==quality['counts']['covered_text_atoms']
        assert excluded_count==quality['counts']['excluded_text_atoms']
        results=[]
        for expected in gold['paragraphs']:
            if expected['source_id']!=source_id:continue
            matches=[b for b in blocks if b['locator']['dom_path']==expected['path']]
            assert len(matches)==1
            result=reader.read(HtmlEvidenceRef(asset_ref=reference,kind='block',item_id=matches[0]['id'],field='text'))
            assert result['source']['raw_node_text']==expected['text']
            assert result['value']==display(by_path[expected['path']])
            results.append({'id':expected['id'],'kind':'paragraph','passed':True,'path':expected['path']})
        for expected in gold['tables']:
            if expected['source_id']!=source_id:continue
            table=next(t for t in tables if t['locator']['dom_path']==expected['path'])
            cells={c['locator']['dom_path']:c for c in table['cells']}
            omitted={e['path'] for e in exclusions if e['kind']=='table_cell'}
            checked=0;excluded_gold=0
            occupied={}
            for cell in table['cells']:
                original=by_path[cell['locator']['dom_path']]
                assert cell['row_span']==int(original.get('rowspan','1')) and cell['col_span']==int(original.get('colspan','1'))
                for row in range(cell['row'],cell['row']+cell['row_span']):
                    for col in range(cell['col'],cell['col']+cell['col_span']):
                        assert (row,col) not in occupied
                        occupied[row,col]=cell['id']
            for cell in expected['cells']:
                assert norm(by_path[cell['path']].text_content())==cell['text']
                if cell['path'] in omitted:
                    assert hidden(by_path[cell['path']]);excluded_gold+=1;continue
                actual=cells[cell['path']]
                result=reader.read(HtmlEvidenceRef(asset_ref=reference,kind='table_cell',item_id=actual['id'],field='text'))
                assert result['source']['raw_node_text']==cell['text']
                assert result['value']==display(by_path[cell['path']])
                assert result['context']['table']['id']==table['id']
                checked+=1
            assert checked+excluded_gold==len(expected['cells'])
            context=' '.join(b['text'] for b in blocks if b['id'] in table['context_block_ids'])
            # Unit context is frozen separately, not inferred from the number.
            assert expected['unit_context'] in context or expected['unit_context'] in display(by_path[expected['path']]),(expected['id'],'unit context missing')
            results.append({'id':expected['id'],'kind':'table','passed':True,'read_cells':checked,'explicitly_excluded_cells':excluded_gold,'path':expected['path']})
        for expected in gold['facts']:
            if expected['source_id']!=source_id:continue
            matches=[r for r in records if r['locator']['dom_path']==expected['path']];assert len(matches)==1
            record=matches[0]
            result=reader.read(HtmlEvidenceRef(asset_ref=reference,kind='record_field',item_id=record['id'],field='value_decimal'))
            assert result['value']==expected['decimal'] and result['source']['raw_node_text']==expected['raw']
            for field in ('concept','context_ref','unit_ref','scale','sign','period','context_path'):assert record[field]==expected[field],field
            assert record['unit']['measures']==['{http://www.xbrl.org/2003/iso4217}USD']
            assert result['context']['xbrl_context']['dom_path']==expected['context_path']
            assert Decimal(expected['raw'].replace(',',''))*(Decimal(10)**int(expected['scale']))==Decimal(expected['decimal'])
            results.append({'id':record['id'],'kind':'fact','passed':True,'value_decimal':result['value'],'period':record['period'],'unit':record['unit'],'path':expected['path']})
        return dict(source_id=source_id,asset_ref=reference.model_dump(mode='json'),source_sha256=sha(raw),gold_checks=results,
            counts=quality['counts'],independent_visible_atoms=visible,independent_excluded_atoms=excluded_count,
            all_source_tables_accounted=len(source_tables),all_source_cells_accounted=len(source_cells),all_inline_facts_accounted=len(source_facts),
            all_locators_checked=len(located),readiness=inventory['schema']['published_readiness'],gaps=inventory['schema']['gaps'],
            independently_checked_numeric_values=checked_values,independently_checked_table_links=checked_links,
            artifact_hashes={f.path:f.object_ref.model_dump(mode='json') for f in manifest.files},passed=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True);parser.add_argument('--gold',type=Path,required=True)
    parser.add_argument('--source-id',required=True);parser.add_argument('--example-result',type=Path,required=True)
    args=parser.parse_args();raw=args.gold.read_bytes();gold=json.loads(raw)
    assert gold['thresholds']=={'mandatory_correct':1.0,'unexplained_omissions':0,'all_facts_accounted':1.0,'old_refs_readable':True}
    reference=AssetRef.model_validate(json.loads(args.example_result.read_text())['asset_ref'])
    result=audit(args.data_root,reference,gold,args.source_id);result['gold_sha256']=sha(raw)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
