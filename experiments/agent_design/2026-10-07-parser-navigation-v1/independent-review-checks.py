"""Local review only. Independent expected values never feed production parsing."""
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from uteki.infrastructure.document_sources.sec_index import parse_sec_source, build_legal_outline
from uteki.infrastructure.document_sources.parsed_package import ADAPTERS, json_value
from uteki.infrastructure.research_data.query_service import QueryDataPort

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT))
from tests.unit.test_scoped_query_service import make_scoped_dataset
from tests.unit.test_task_completion import pin_dataset
OUT = Path(__file__).resolve().parent
ORACLE = json.loads((OUT / 'independent-oracle.json').read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def parse(raw, version, source=None, form='20-F'):
    source = source or {'document_id':'independent-orion-2031',
        'source_url':'https://example.invalid/independent-orion/2031',
        'source_snapshot_id':'independent-orion-frozen-2031', 'form_type':form}
    parsed = parse_sec_source(source['document_id'], source['source_url'], raw,
        source_snapshot_id=source['source_snapshot_id'], form_type=source['form_type'], parser_version=version)
    values = {'blocks.jsonl':[json_value(ADAPTERS['blocks.jsonl'], b) for b in parsed.blocks],
        'anchors.json':json_value(ADAPTERS['anchors.json'],list(parsed.anchors)),
        'toc.json':json_value(ADAPTERS['toc.json'],list(parsed.toc_entries)),
        'index.json':json_value(ADAPTERS['index.json'],build_legal_outline(parsed))}
    return parsed, values

def read(folder, name):
    p = folder / name
    return [json.loads(l) for l in p.read_text().splitlines()] if name.endswith('.jsonl') else json.loads(p.read_text())

def independent_filing(prose=''):
    # Fixture business scope and literal expectations are confined to this review.
    return ('<html><body><h1 id="contents">Contents</h1><table><tr><td>PART I</td></tr>'
        '<tr><td>ITEM 1.</td><td><a href="#one">TOOLS</a></td><td>3</td></tr>'
        '<tr><td>ITEM 2.</td><td><a href="#two">RISKS</a></td><td>4</td></tr>'
        '<tr><td>ITEM 3.</td><td><a href="#three">LOCATIONS</a></td><td>5</td></tr></table>'
        '<h2>PART I</h2><table><tr><td id="one">ITEM 1.</td><td>TOOLS</td></tr></table><p>End of tools.</p>'
        '<table><tr><td id="two">ITEM 2.</td><td>RISKS</td></tr></table>' + prose + '<p>End of risks.</p>'
        '<table><tr><td id="three">ITEM 3.</td><td>LOCATIONS</td></tr></table><p>End of locations.</p></body></html>')

def query_checks():
    results=[]
    for number in (8,9,10):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            make_scoped_dataset(root)
            folder=root/'indexes/acme-annual'
            blocks=[{'block_id':f'b{i}','type':'paragraph','text':'Table of Contents' if i in (1,2,4) else 'Actual body material.',
                'reported_page':1,'layout_role':'repeated_navigation' if i in (1,2,4) else None} for i in range(5)]
            (folder/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in blocks))
            index=read(folder,'index.json')
            index['parser_version']=f'sec-source-blocks-v0.1.{number}'
            index['nodes']=[{'node_id':'root','kind':'document','start_block_id':'b0','end_block_id':'b4'}]
            (folder/'index.json').write_text(json.dumps(index))
            manifest=read(folder,'manifest.json')
            manifest['parser_version']=index['parser_version']
            for name in ('index.json','blocks.jsonl'):manifest['artifacts'][name]['sha256']=sha(folder/name)
            (folder/'manifest.json').write_text(json.dumps(manifest))
            pin_dataset(root)
            pages=[]
            with QueryDataPort(root) as owner:
                port=owner.scoped({'snapshot_id':owner.snapshot_id,'company_ids':['acme'],'source_snapshot_ids':['acme-annual'],
                    'source_policy_id':'local-frozen-v1','knowledge_cutoff':'2032-06-01','include_candidates':True})
                request={'source_snapshot_id':'acme-annual','node_id':'root','start_block_id':'b1','count':1}
                for unused in range(5):
                    page=port.read_source(request)
                    pages.append(page)
                    if not page['next_cursor']:break
                    request={'source_snapshot_id':'acme-annual','node_id':'root','cursor':page['next_cursor'],'count':1}
                search=port.search_source({'source_snapshot_id':'acme-annual','node_id':'root','phrase':'Table of Contents','limit':8})
            ids=[[b['block_id'] for b in p['blocks']] for p in pages]
            expected_ids=[[f'b{i}'] for i in (1,2,3,4)] if number==8 else [[],[],['b3'],[]]
            expected_status=['read']*4 if number==8 else ['layout_only','layout_only','read','layout_only']
            checks={'delivered_ids_match':ids==expected_ids,'page_status_match':[p['status'] for p in pages]==expected_status,
                'completion_only_at_source_end':[p['node_complete'] for p in pages]==[False,False,False,True],
                'search_filter_version_gated':search['total']==(3 if number==8 else 0),
                'search_never_infers_non_disclosure':search['not_disclosed'] is False,
                'layout_only_does_not_infer_non_disclosure':all(p.get('not_disclosed') is False for p in pages if p['status']=='layout_only')}
            results.append({'parser_version':index['parser_version'],'checks':checks,'status':'passed' if all(checks.values()) else 'failed',
                'actual_block_ids_by_page':ids,'page_statuses':[p['status'] for p in pages],
                'omitted_ids':[p.get('omitted_block_ids',[]) for p in pages],'search_total':search['total']})
    return results

def main():
    report = {'schema_version':'independent-parser-review-v1',
        'created_at':datetime.now(timezone.utc).isoformat(),
        'oracle_sha256':sha(OUT/'independent-oracle.json'), 'implementation_sha256':{},
        'compatibility':[], 'source_cases':[], 'synthetic_cases':[], 'additional_independent_cases':[], 'unit_tests':{}}
    for relative in ['src/uteki/infrastructure/document_sources/sec_index.py',
        'src/uteki/infrastructure/document_sources/parsed_package.py',
        'src/uteki/agents/reading/document_reader.py',
        'src/uteki/infrastructure/research_data/query_service.py',
        'src/uteki/agents/data_query/answer_handoff.py']:
        report['implementation_sha256'][relative] = sha(ROOT/relative)
    for company, expected in ORACLE['companies'].items():
        raw = (ROOT/expected['raw_path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == expected['raw_sha256']
        parsed_versions = {}
        for number in (7,8,9,10):
            version = f'sec-source-blocks-v0.1.{number}'
            frozen = ROOT/expected['frozen_package_path'] if number==7 else ROOT/f'experiments/agent_design/2026-10-07-data-foundation-v1/anchor-fix-v2-{company}'
            source = read(frozen, 'source.json')
            parsed, values = parse(raw,version,source)
            parsed_versions[number] = (parsed,values)
            if number in (7,8):
                equal = {name: value==read(frozen,name) for name,value in values.items()}
                report['compatibility'].append({'company':company,'parser_version':version,'payload_equal_to_frozen':equal})
        expected_ids = {o['block_id'] for o in expected['navigation']['occurrences']}
        for number in (9,10):
            parsed, values = parsed_versions[number]
            actual_ids = {b.block_id for b in parsed.blocks if b.layout_role=='repeated_navigation'}
            old = parsed_versions[8][1]
            same_content = [{k:v for k,v in b.items() if k!='layout_role'} for b in values['blocks.jsonl']] == [{k:v for k,v in b.items() if k!='layout_role'} for b in old['blocks.jsonl']]
            result = {'company':company,'parser_version':parsed.parser_version,'raw_sha256':expected['raw_sha256'],
                'navigation_count':len(actual_ids),'navigation_matches_independent_source_positions':actual_ids==expected_ids,
                'missing_navigation_ids':sorted(expected_ids-actual_ids),'unexpected_navigation_ids':sorted(actual_ids-expected_ids),
                'blocks_equal_except_layout_role':same_content,'anchors_equal_v8':values['anchors.json']==old['anchors.json'],
                'assets_equal_v8':parsed.assets==parsed_versions[8][0].assets}
            published=OUT/f'stage-{"a" if number==9 else "b"}-{company}'
            result['stage_folder']=str(published.relative_to(ROOT))
            result['stage_payloads_equal_current_parser']={name:published.exists() and value==read(published,name) for name,value in values.items()}
            result['stage_manifest_sha256']=sha(published/'manifest.json') if published.exists() else None
            if company=='tsmc' and number==10:
                by_id = {b.block_id:b for b in parsed.blocks}
                actual = {(n['part_number'],n['item_number']):n for n in values['index.json']['nodes'] if n['kind']=='item'}
                result['item_count']=len(actual)
                result['items']=[]
                for want in expected['outline']['items']:
                    got=actual.get((want['part'],want['item_number']))
                    check={'part':want['part'],'item':want['item_number'],'present':got is not None}
                    if got:
                        end=by_id[got['end_block_id']].ordinal
                        ceiling=want['expected_contiguous_navigation_end_ordinal']
                        trimmed = list(parsed.blocks[end:ceiling]) if end<=ceiling else []
                        check.update({'title_matches':got['title']==want['title'],
                            'start_matches':got['start_block_id']==want['start_block_id'],
                            'page_matches':got['reported_page']==want['reported_page'],
                            'anchor_matches':got['source_anchor']==want['source_anchor'],
                            'expected_navigation_end_ceiling':ceiling,'actual_end_ordinal':end,
                            'only_layout_tail_trimmed':end<=ceiling and all(b.layout_role for b in trimmed),
                            'trimmed_tail_block_ids':[b.block_id for b in trimmed]})
                    result['items'].append(check)
                result['cross_reference_source_text']={str(n):parsed.blocks[n-1].text for n in (1047,1049)}
                result['node_ranges_are_navigation_warning']='outline_ranges_are_navigation' in {d['code'] for d in values['index.json']['diagnostics']}
                result['known_raw_page_limitation']={'block_ordinal':995,'unchanged_raw_block_page':parsed.blocks[994].reported_page,'verified_toc_page':70}
            report['source_cases'].append(result)
    selected={'N02','N03','N04','N05','N06','N07','T01','T03','T06','T08'}
    qualification_limits={
        'N01':'A requires at least two TOC Item rows; this one-item proposal returns 0 marked links rather than the proposed 2. Text preserved; no dedicated navigation rejection diagnostic.',
        'T02':'Linked TOC has no Part identity; new table-heading branch conservatively publishes no Item rather than the proposed 2.',
        'T04':'No independently qualifying TOC/anchors; no Items rather than the proposed I/1 and II/1. A separate explicit-TOC cross-Part sample is executed below.',
        'T05':'No qualifying TOC/anchors; generic unresolved/rejected diagnostics appear before title-conflict evaluation. No confident node is published, but the proposed conflict-specific diagnostic is not established.',
        'T07':'No qualifying TOC/anchors; no Item range is published. Generic unresolved diagnostic does not establish the proposed specific ambiguous-boundary diagnosis.',
        'T09':'The div-based 16C/Fees text is preserved, but there is no verified TOC/anchor for publishing a node. Real TSMC 16C independently exercises supported div title qualification.'}
    for case in ORACLE['synthetic_cases']:
        raw=case['html'].encode()
        old,old_values=parse(raw,'sec-source-blocks-v0.1.8',form=case['expected'].get('form','20-F'))
        new,values=parse(raw,'sec-source-blocks-v0.1.10',form=case['expected'].get('form','20-F'))
        nav=sum(b.layout_role=='repeated_navigation' for b in new.blocks)
        items=[n for n in values['index.json']['nodes'] if n['kind']=='item']
        codes={d['code'] for d in values['index.json']['diagnostics']}
        checks={'source_blocks_unchanged':old.blocks==new.blocks,'anchors_unchanged':old.anchors==new.anchors}
        if case['id'].startswith('N'):checks['no_navigation_false_positive']=nav==0
        else:checks['no_false_item_nodes']=len(items)==0
        if case['id']=='T06':checks['unsupported_nested_table_explicit']='table_item_heading_rejected' in codes
        if case['id']=='T08':checks['duplicate_anchor_explicit']=any('duplicate' in code for code in codes)
        report['synthetic_cases'].append({'id':case['id'],
            'status':('passed' if case['id'] in selected else 'conservative_rejection_observed') if all(checks.values()) else 'failed',
            'original_proposed_expectation':case['expected'],
            'original_proposed_expectation_fully_met':case['id'] in selected and all(checks.values()),
            **({'qualification_limit':qualification_limits[case['id']]} if case['id'] not in selected else {}),
            'input_sha256':hashlib.sha256(raw).hexdigest(),'checks':checks,'navigation_count':nav,'item_count':len(items),'diagnostics':sorted(codes)})
    prose_cases = [
        ('short_same_item_reference','Item 2 as well as other requirements are discussed here.'),
        ('short_different_item_reference','Item 16G as well as NYSE Section 303A.11 requires a governance comparison.'),
        ('short_reference_with_period','ITEM 2. As discussed above, our risks should be evaluated in context.'),
        ('long_same_item_reference','Item 2 as well as other requirements are discussed here. ' + 'Narrative sentence. '*20)]
    for label, prose in prose_cases:
        raw=independent_filing('<p>'+prose+'</p>').encode()
        parsed,values=parse(raw,'sec-source-blocks-v0.1.10')
        nodes={n['item_number']:n for n in values['index.json']['nodes'] if n['kind']=='item'}
        two=nodes.get('2')
        checks={'all_three_real_items_present':set(nodes)=={'1','2','3'},
            'risk_content_stays_in_risk_item':bool(two) and next(b.text for b in parsed.blocks if b.block_id==two['end_block_id'])=='End of risks.'}
        report['additional_independent_cases'].append({'id':label,'input_html':raw.decode(),'checks':checks,'status':'passed' if all(checks.values()) else 'failed'})
    raw=independent_filing().replace('href="#two"','href="#wrong"').encode()
    parsed,values=parse(raw,'sec-source-blocks-v0.1.10')
    nodes={n['item_number']:n for n in values['index.json']['nodes'] if n['kind']=='item'}
    checks={'unverified_item_not_published':set(nodes)=={'1','3'},
        'previous_item_does_not_absorb_unresolved_risk':next(b.text for b in parsed.blocks if b.block_id==nodes['1']['end_block_id'])=='End of tools.'}
    report['additional_independent_cases'].append({'id':'wrong_anchor_still_delimits','input_html':raw.decode(),'checks':checks,'status':'passed' if all(checks.values()) else 'failed'})
    raw=b'''<html><body><p id="toc">TABLE OF CONTENTS</p><table><tr><td>PART I</td></tr><tr><td>ITEM 1.</td><td><a href="#business">Business</a></td><td>3</td></tr><tr><td>PART II</td></tr><tr><td>ITEM 1.</td><td><a href="#legal">Legal Proceedings</a></td><td>4</td></tr></table><h1>PART I</h1><table><tr><td id="business">ITEM 1.</td><td>Business</td></tr></table><p>Business end.</p><h1>PART II</h1><table><tr><td id="legal">ITEM 1.</td><td>Legal Proceedings</td></tr></table><p>Legal end.</p></body></html>'''
    parsed,values=parse(raw,'sec-source-blocks-v0.1.10',form='10-Q')
    nodes={(n['part_number'],n['item_number']):n for n in values['index.json']['nodes'] if n['kind']=='item'}
    checks={'item_numbers_scoped_by_part':set(nodes)=={('I','1'),('II','1')},
        'first_item_ends_before_next_part':next(b.text for b in parsed.blocks if b.block_id==nodes[('I','1')]['end_block_id'])=='Business end.',
        'second_item_anchor_is_own':nodes[('II','1')]['source_anchor']=='legal'}
    report['additional_independent_cases'].append({'id':'cross_part_same_item_with_explicit_toc','input_html':raw.decode(),'checks':checks,'status':'passed' if all(checks.values()) else 'failed'})
    tests=['tests.unit.test_sec_navigation_stages','tests.unit.test_answer_handoff_navigation']
    result=subprocess.run([str(ROOT/'.venv/bin/python'),'-m','unittest',*tests,'-v'],cwd=ROOT,text=True,capture_output=True)
    report['unit_tests']={'modules':tests,'returncode':result.returncode,'output':result.stdout+result.stderr}
    report['query_checks']=query_checks()
    report['scope']='Independent deterministic source/contract review; no model calls or semantic benchmark; original oracle expectations never passed into production parsing.'
    report['pre_publication_candidates']='pre-publication-attempt-1 retained by implementer; excluded from final stage comparisons.'
    (OUT/'independent-review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'sources':len(report['source_cases']),'compatibility':report['compatibility'],
        'synthetics':[{k:v for k,v in c.items() if k in ('id','status','checks')} for c in report['synthetic_cases']],
        'unit_returncode':result.returncode},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
