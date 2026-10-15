"""Acceptance-only audit of actual tool responses against frozen original bytes.

No gold or expected values are passed to DataService. This verifier does not use
the product's query, calculation, result-registration or delivery implementation.
"""
from __future__ import annotations

import argparse
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import json
from pathlib import Path
import runpy

from lxml import etree, html
from uteki.data_platform.content import ContentStore
from uteki.data_platform.contracts.content import ObjectRef

SOURCE_AUDIT=runpy.run_path(str(Path(__file__).with_name('verify_html_material.py')))


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def visible(value):
    if isinstance(value,dict):
        if 'result_ref' in value:
            yield value
        for child in value.values():
            yield from visible(child)
    elif isinstance(value,list):
        for child in value:
            yield from visible(child)


def expanded(node,qname):
    if ':' not in qname:
        raise AssertionError('source QName is not explicit')
    prefix,local=qname.split(':',1)
    for owner in [node]+list(node.iterancestors()):
        namespace=owner.get('xmlns:'+prefix)
        if namespace:
            return '{'+namespace+'}'+local
    raise AssertionError('source namespace is missing')


def audit(data_root,result,gold,label):
    assert result['status']=='completed' and result['reopened'] is True
    assert result['model_calls']==0 and result['autonomous_agent_evaluated'] is False
    expected=gold['materials'][label]
    expected_ref=expected['asset_ref']
    store=ContentStore(data_root)
    nodes=None
    all_results={}
    evidence_count=record_count=0
    for step,response in result['responses'].items():
        assert response['status'] in {'ok','partial'},(step,response.get('error'))
        assert response['resource_usage']['model_calls']==response['resource_usage']['external_calls']==0
        assert response['resource_usage']['cost_usd']=='0'
        for item in visible(response):
            ref=item['result_ref']
            assert ref['run_id']==result['context']['run_id'] and ref['operation_id']==response['operation_id']
            key=encoded(ref)
            if key in all_results:
                assert all_results[key]==item
                continue
            all_results[key]=item
            if ref['kind']=='calculation':
                continue
            assert item['asset_ref']==expected_ref
            raw=store.read_object(ObjectRef.model_validate(item['source_object']))
            assert hashlib.sha256(raw).hexdigest()==expected['source_sha256']
            if nodes is None:
                tree=html.document_fromstring(raw,parser=html.HTMLParser(encoding='utf-8',no_network=True)).getroottree()
                nodes={tree.getpath(n):n for n in tree.getroot().iter() if isinstance(n.tag,str)}
            locator=item['locator'];node=nodes[locator['dom_path']]
            text=SOURCE_AUDIT['norm'](node.text_content()) if locator['projection']=='raw_text_v1' else SOURCE_AUDIT['display'](node)
            start,end=locator['char_start'],locator['char_end']
            assert 0<=start<=end<=len(text)
            actual=text[start:end]
            assert hashlib.sha256(actual.encode()).hexdigest()==locator['text_sha256']
            if ref['kind']=='evidence':
                assert item['content']['text']==actual
                evidence_count+=1
                continue
            record_count+=1
            assert item['raw_value']==actual
            assert item['concept_id']==expanded(node,node.get('name'))
            context_id=node.get('contextref');unit_id=node.get('unitref')
            context=[n for n in nodes.values() if n.get('id')==context_id]
            unit=[n for n in nodes.values() if n.get('id')==unit_id]
            assert len(context)==len(unit)==1
            context,unit=context[0],unit[0]
            assert item['context_ref']==context_id
            original_period={key:SOURCE_AUDIT['norm'](n.text_content()) for n in context.iter()
                for local,key in [('startdate','start'),('enddate','end'),('instant','instant')] if str(n.tag).split(':')[-1]==local}
            assert item['period']==original_period
            identity=[n for n in context.iter() if str(n.tag).split(':')[-1]=='identifier']
            assert len(identity)==1
            assert item['entity_identifier']==SOURCE_AUDIT['norm'](identity[0].text_content())
            assert item['entity_scheme']==identity[0].get('scheme')
            expected_dimensions=[]
            for member in context.iter():
                local=str(member.tag).split(':')[-1]
                if local not in {'explicitmember','typedmember'}:
                    continue
                typed=local=='typedmember'
                expected_dimensions.append(dict(dimension=expanded(member,member.get('dimension')),
                    kind='typed' if typed else 'explicit',status='raw_only' if typed else 'parsed',path=tree.getpath(member),
                    value=etree.tostring(member,encoding='unicode',method='html',with_tail=False) if typed else expanded(member,SOURCE_AUDIT['norm'](member.text_content()))))
            assert item['dimensions']==expected_dimensions
            assert item['context_source']['dom_path']==tree.getpath(context)
            assert item['unit_source']['dom_path']==tree.getpath(unit)
            for field,attribute in [('decimals','decimals'),('scale','scale'),('sign','sign')]:
                assert item[field]==node.get(attribute)
            if item['status']=='parsed':
                # Both frozen real materials use decimal iXBRL transformations.
                transformation=(node.get('format') or '').split(':')[-1]
                assert transformation in {'','num-dot-decimal','numdotdecimal','fixed-zero'}
                value=Decimal(0) if transformation=='fixed-zero' else Decimal(actual.replace(',','').replace(' ',''))
                value*=Decimal(10)**int(node.get('scale','0'))
                if node.get('sign')=='-':
                    value=-value
                assert Decimal(item['value'])==value
            elif node.get('xsi:nil') in {'true','1'}:
                assert item['status']=='nil' and item['value'] is None
            else:
                assert item['value'] is None and item['issues']
            divided=any(str(n.tag).split(':')[-1]=='divide' for n in unit.iter())
            if not divided:
                measures=[expanded(n,SOURCE_AUDIT['norm'](n.text_content())) for n in unit.iter() if str(n.tag).split(':')[-1]=='measure']
                assert item['unit']=={'measures':measures}
            else:
                wanted={}
                for part,local in [('numerator','unitnumerator'),('denominator','unitdenominator')]:
                    owner=next(n for n in unit.iter() if str(n.tag).split(':')[-1]==local)
                    wanted[part]=[expanded(n,SOURCE_AUDIT['norm'](n.text_content())) for n in owner.iter() if str(n.tag).split(':')[-1]=='measure']
                assert item['unit']==wanted
    # Every dependency must be part of the actual returned response, not merely
    # somewhere in a database or a hidden intermediate object.
    for item in all_results.values():
        for ref in item.get('dependency_refs',[])+item.get('operand_refs',[]):
            dependency=all_results[encoded(ref)]
            assert ref['operation_id']==item['result_ref']['operation_id']
            assert dependency['result_ref']==ref
    read=result['responses']['read']
    paragraph=expected['paragraph']
    pieces=sorted([v for v in read['items'] if v['locator']['dom_path']==paragraph['path']],key=lambda v:v['locator']['char_start'])
    assert pieces and pieces[0]['locator']['char_start']==0
    for first,second in zip(pieces,pieces[1:]):
        assert first['locator']['char_end']==second['locator']['char_start']
    assert ''.join(v['content']['text'] for v in pieces)==paragraph['text']
    if 'facts' in expected:
        computed=result['responses']['numbers']['calculations']
        assert len(computed)==1
        calc=computed[0]
        assert calc['limitations']==[] and calc['formula']=='(operand[0] - operand[1]) / operand[1]'
        operands=[all_results[encoded(ref)] for ref in calc['operand_refs']]
        assert len(operands)==2
        for record,fact in zip(operands,expected['facts']):
            assert record['value']==fact['decimal'] and record['period']==fact['period']
            assert record['locator']['dom_path']==fact['path']
            assert record['unit']=={'measures':['{http://www.xbrl.org/2003/iso4217}USD']}
        with localcontext() as context:
            context.prec=60
            current,base=[Decimal(v['value']) for v in operands]
            value=((current-base)/base).quantize(Decimal('0.000000000000000001'),rounding=ROUND_HALF_EVEN)
        assert str(value)==calc['value']==expected['growth']
    else:
        assert result['responses']['schema']['items'][0]['records_applicable'] is False
        assert record_count==0
    table_cells=0
    if 'table' in expected:
        response=result['responses']['read-table']
        assert response['next_cursor'] is None and not response['truncated'],'mandatory source table rows were not completely returned'
        wanted={c['path']:c for c in expected['table']['cells']}
        actual={v['locator']['dom_path']:v for v in response['items']}
        assert set(actual)==set(wanted)
        for path,cell in wanted.items():
            assert SOURCE_AUDIT['norm'](nodes[path].text_content())==cell['text']
            assert actual[path]['content']['text']==SOURCE_AUDIT['display'](nodes[path])
            assert actual[path]['content']['row_span']==int(cell['rowspan'])
            assert actual[path]['content']['col_span']==int(cell['colspan'])
        table_cells=len(wanted)
        source_context=' '.join(v['content']['text'] for v in response['items']+response['context_evidence'])
        assert expected['table']['unit_context'] in source_context
    delivery=result['delivery']['delivery']
    included={encoded(v['result_ref']):v for group in ('evidence','records','calculations') for v in delivery[group]}
    visited,active=set(),set()
    def visit(ref):
        key=encoded(ref)
        assert key not in active,'cycle'
        if key in visited:
            return
        active.add(key)
        item=all_results[key]
        assert included[key]==item,'delivery changed a returned result'
        for dependent in item.get('dependency_refs',[])+item.get('operand_refs',[]):
            visit(dependent)
        active.remove(key);visited.add(key)
    for need in delivery['needs']:
        assert need['status']=='supported' and need['gaps']==[]
        for ref in need['result_refs']:
            visit(ref)
    assert set(included)==visited,'unexpected extra or missing delivery result'
    assert delivery['assets_used']==[expected_ref]
    frozen=json.loads(store.read_object(ObjectRef.model_validate(result['delivery']['delivery_object'])))
    assert frozen==delivery
    return dict(passed=True,source_id=label,source_sha256=expected['source_sha256'],evidence_checked=evidence_count,
        records_checked=record_count,mandatory_table_cells_checked=table_cells,delivery_results=len(visited),model_calls=0,new_network_calls=0,
        business_sufficiency_evaluated=False,autonomous_agent_evaluated=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--gold',type=Path,required=True)
    parser.add_argument('--source-id',required=True)
    parser.add_argument('--example-result',type=Path,required=True)
    args=parser.parse_args()
    gold_raw=args.gold.read_bytes()
    result=audit(args.data_root,json.loads(args.example_result.read_bytes()),json.loads(gold_raw),args.source_id)
    result['gold_sha256']=hashlib.sha256(gold_raw).hexdigest()
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
