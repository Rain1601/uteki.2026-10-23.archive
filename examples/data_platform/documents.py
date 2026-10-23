"""Synthetic parser-output demonstration, not PDF/OCR/model acceptance.

python -I examples/data_platform/documents.py --data-root /absolute/existing/dir
The same root can be reused: immutable publication is idempotent.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

from uteki.data_platform.contracts.common import digest
from uteki.data_platform.contracts.documents import BlockQuery, BlockRef, DocumentPackage
from uteki.data_platform.documents import DocumentStore


SOURCE = '''<!doctype html><html><body><nav><a href="#operations">经营情况</a>
<a href="#revenue">收入构成</a></nav><h1 id="operations">经营情况</h1><h2 id="revenue">收入构成</h2>
<p>收入构成 / Revenue by region (USD millions)</p><table><tr><th>Region</th><th>Revenue</th></tr>
<tr><td>East</td><td>120</td></tr><tr><td>West</td><td>80</td></tr></table>
<p>合并口径，排除内部销售。Consolidated scope; excludes intersegment sales.</p><img src="chart.png" alt="Synthetic image placeholder">
<p><a href="https://example.invalid/report">Report link</a></p></body></html>'''.encode('utf-8')
IMAGE = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN2cAAAAASUVORK5CYII=')


def fixture(store):
    """An explicit synthetic parser's output, with a test-only fixed taxonomy."""
    original=store.content.put_object(SOURCE).model_dump(mode='json')
    image=store.content.put_object(IMAGE).model_dump(mode='json')
    stamp='2026-01-10T10:00:00Z'
    none={'status':'not_applicable'}
    def locator(path):return {'kind':'html_node','dom_path':path}
    def block(identity,order,kind,path,**extra):
        return dict(block_id=identity,order=order,type=kind,processor_ref='synthetic-parser',
            locations=[locator(path)],directory_node_ids=['revenue'],directory_assignment='assigned',
            ocr=none,description=none,tagging={'status':'complete','tag_ids':[],'processor_ref':'synthetic-tags'},
            status='complete',**extra)
    cells=[dict(row=r,column=c,text=text,is_header=r==0) for r,row in enumerate([['Region','Revenue'],['East','120'],['West','80']]) for c,text in enumerate(row)]
    title=block('caption',1,'text','/html/body/p[1]',text='收入构成 / Revenue by region (USD millions)')
    table=block('table',2,'table','/html/body/table',table=dict(status='complete',processor_ref='synthetic-parser',row_count=3,column_count=2,cells=cells),
        related_blocks=[{'block_id':'caption','relation':'caption'},{'block_id':'footnote','relation':'footnote'}])
    table['tagging']['tag_ids']=['finance.revenue','business.region']
    note=block('footnote',3,'text','/html/body/p[2]',text='合并口径，排除内部销售。Consolidated scope; excludes intersegment sales.')
    chart=block('chart',4,'image','/html/body/img',resources=[dict(resource_id='chart-original',role='original_image',mime_type='image/png',object_ref=image)])
    chart['ocr']={'status':'complete','text':'收入 East 120 West 80','processor_ref':'synthetic-parser'}
    chart['description']={'status':'complete','text':'合成图片描述：趋势图。synthetic trend description','processor_ref':'synthetic-parser'}
    link=block('link',5,'text','/html/body/p[3]',text='Report link',links=[{'text':'Report link','target_url':'https://example.invalid/report'}])
    return DocumentPackage.model_validate_json(json.dumps(dict(
        material=dict(material_id='demo-material',name='合成年度材料',material_type='synthetic-report',language='zh-CN',
            related_entities=[dict(entity_id='demo-company',name='合成公司',role='subject')],
            reporting_period=dict(label='FY2025',fiscal_year=2025,fiscal_quarter=None,start='2025-01-01',end='2025-12-31',basis='source'),
            published_at=dict(value=dict(value='2026-01-10',precision='date'),basis='synthetic fixture',unknown_reason=None),created_at=stamp),
        source=dict(source_version_id='demo-source-v1',material_id='demo-material',format='html',object_ref=original,
            source_url='https://example.invalid/report',acquisition_method='manual_upload',acquired_at=stamp,ingested_at=stamp),
        parse=dict(parse_id='demo-parse-v1',material_id='demo-material',source_version_id='demo-source-v1',config_hash=digest(b'synthetic-document-fixture-v1'),
            processors=[dict(processor_id='synthetic-parser',step='synthetic_output',tool_name='fixture',tool_version='1'),dict(processor_id='synthetic-tags',step='tagging',tool_name='fixture',tool_version='1')],
            started_at=stamp,completed_at=stamp,status='complete',
            directory_schema=dict(has_source_directory=True,status='complete',nodes=[
                dict(node_id='operations',parent_id=None,title='经营情况',order=1,basis='source_directory',locations=[locator('/html/body/h1')]),
                dict(node_id='revenue',parent_id='operations',title='收入构成',order=1,basis='source_directory',locations=[locator('/html/body/h2')])]),
            taxonomy=dict(taxonomy_id='synthetic-business',version='1',tags=[
                dict(tag_id='finance.revenue',name='收入',description='Synthetic revenue label',applicable_material_types=['synthetic-report']),
                dict(tag_id='business.region',name='地区',description='Synthetic regional label') ])),blocks=[title,table,note,chart,link])))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--data-root',type=Path,required=True)
    args=parser.parse_args()
    opener=DocumentStore.open if (args.data_root/'documents.sqlite').exists() else DocumentStore.initialize
    with opener(args.data_root) as store:
        package=fixture(store);publication=store.publish(package)
        request=BlockQuery(parse_id=package.parse.parse_id,directory_path=('经营情况',),include_descendants=True,
            tags=('finance.revenue','business.region'),tag_match='all',types=('table',))
        found=store.query_blocks(request)
        reference=BlockRef.model_validate(found['items'][0]['ref'])
        result=dict(publication=publication,materials=store.find_materials(entity_id='demo-company',reporting_period='FY2025'),
            schema=store.get_schema(package.parse.parse_id),query=found,delivery=store.read_block(reference),
            source_bytes_match=store.read_source(package.parse.parse_id)==SOURCE,model_calls=0)
    with DocumentStore.open(args.data_root) as store:
        result['old_reference_after_reopen']=store.read_block(reference)['block']==result['delivery']['block']
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
