"""Independent, case-specific review; never imported by runtime code."""
from pathlib import Path
from decimal import Decimal
from collections import Counter
from hashlib import sha256
import json
from lxml import html
from uteki.agents.data_query.coordinator import _verify_manifest
from uteki.evaluation.evidence_benchmark import evaluate

ROOT=Path(__file__).resolve().parents[2]
def read(p): return json.loads(p.read_text())
def digest(p): return sha256(p.read_bytes()).hexdigest()
def save(p,v):
    with p.open('x') as f: json.dump(v,f,ensure_ascii=False,indent=2)
run=ROOT/'runs/E1-02-sonnet-r1'; _verify_manifest(run)
packet=read(run/'attempt-01/review-01/input.json')
_verify_manifest(Path(packet['query_ref']['path']),packet['query_ref']['manifest_sha256'])
dataset=Path(packet['dataset_ref']['path']);_verify_manifest(dataset,packet['dataset_ref']['manifest_sha256'])
freeze=read(ROOT/'evaluation-only/frozen/E1-02-v1.json')
reference=ROOT/freeze['reference_path'];assert digest(reference)==freeze['reference_sha256']
assert packet['question']==freeze['case']['query_zh']
sources=read(dataset/'sources.json');assert len(sources)==1
source=sources[0];sid=source['source_snapshot_id'];raw=dataset/source['raw_file']
assert digest(raw)==source['source_sha256']==read(reference)['source']['raw_sha256']
tree=html.fromstring(raw.read_bytes());et=tree.getroottree();nodes={et.getpath(n):n for n in tree.iter() if isinstance(n.tag,str)}
blocks={b['block_id']:b for b in map(json.loads,(dataset/source['index_folder']/'blocks.jsonl').read_text().splitlines())}
docs=packet['source_documents'];assert len(docs)==1 and docs[0]['source_snapshot_id']==sid
for body in docs[0]['blocks']:
    text=' '.join(nodes[body['dom_path']].text_content().split())
    assert body['text']==blocks[body['block_id']]['text']==text
facts=[f for f in packet['facts'] if f['kind']=='record'];assert len(facts)==1
fact=facts[0]['value'];assert fact['value_decimal']=='245122000000' and fact['unit']=='USD'
assert fact['entity_id']=='sec-0000789019' and fact['dimensions']=={} and fact['metric_id']=='revenue'
ctx=next(n for n in tree.iter() if n.get('id')==fact['origin']['context_ref'])
values={n.tag.split(':')[-1]:' '.join(n.itertext()).strip() for n in ctx.iter() if isinstance(n.tag,str)}
assert values['identifier']=='0000789019' and values['startdate']==fact['period']['start']=='2023-07-01'
assert values['enddate']==fact['period']['end']=='2024-06-30'
assert fact['period']['basis']=='source'
quote=facts[0]['citations'][0];assert quote['quote']=='245,122'
cell=nodes[blocks[quote['block_id']]['dom_path']].xpath('.//tr')[quote['cell']['row']].xpath('./td|./th')[quote['cell']['column']]
assert ' '.join(cell.text_content().split())==quote['quote']
numeric=next(n for n in cell.iter() if n.get('contextref'))
assert numeric.get('contextref')==fact['origin']['context_ref'] and numeric.get('scale')=='6' and numeric.get('unitref')=='U_USD'
metadata={'fiscal_period':fact['period'],'report_period_end':docs[0]['source_period_end']}
assert metadata['report_period_end']==source['period_end']=='2025-06-30'
corpus={sid:{'company_id':source['company_id'],'sha256':source['source_sha256'],'blocks':{k:b['text'] for k,b in blocks.items()},'metadata':metadata}}
requirements=[{'id':r['id'],'description':r['meaning_zh'],'kind':'metadata' if r['id'] in {'R2','R3'} else 'text'} for r in freeze['case']['requirements']]
gold={'schema_version':'evidence-gold-v1','case_id':'E1-02','question':packet['question'],'company_ids':[source['company_id']],'sources':[{'source_id':sid,'company_id':source['company_id'],'sha256':source['source_sha256']}],'required':requirements,'optional':[]}
# Manual annotation: table-level delivery cannot currently select isolated cells.
# Other statement rows are reported separately, not credited as relevant facts.
deliveries=[]
for n,b in enumerate(docs[0]['blocks']):
    text=b['text'];segments=[]
    if b['type']=='table':
        first=text.index('Revenue:'); total=text.index('Total revenue'); end=text.index(' Cost of revenue:')
        spans=[(0,first,'required',['R1']), (first,total,'table_structure',[]), (total,end,'required',['R1']), (end,len(text),'table_structure',[])]
        table=b
        for a,z,category,ids in spans:segments.append({'start':a,'end':z,'category':category,'requirement_ids':ids})
    else:segments=[{'start':0,'end':len(text),'category':'necessary_context','requirement_ids':[]}]
    deliveries.append({'id':f'D{n+1}','source_id':sid,'block_id':b['block_id'],'start':0,'end':len(text),'quote':text,'segments':segments})
def citation(a,z): return {'source_id':sid,'block_id':table['block_id'],'start':a,'end':z,'quote':table['text'][a:z]}
calls=[read(p) for p in run.rglob('*-end.json')]
known=sum((Decimal(c['estimated_usd']) for c in calls if c.get('estimated_usd') is not None),Decimal(0))
unknown=sum((Decimal(c['reserved_usd']) for c in calls if c.get('estimated_usd') is None),Decimal(0))
review={'schema_version':'evidence-review-v1','case_id':'E1-02','question':packet['question'],'reviewer':'Codex root; independent original-source review after frozen reference','requirements':[
 {'id':'R1','status':'supported','reason':'原表FY2024公司总收入245,122百万美元；已核原始数值节点、USD单位、百万倍数、无分部维度及表头。','citations':[citation(0,table['text'].index('Revenue:')),citation(table['text'].index('Total revenue'),table['text'].index(' Cost of revenue:'))]},
 {'id':'R2','status':'supported','reason':'表头给出截至6月30日财年，实际交付的记录给出起止日；已回原件XBRL context核对2023-07-01至2024-06-30。不是仅凭表头猜起日。','citations':[{'kind':'metadata','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']}]},
 {'id':'R3','status':'supported','reason':'交付source_documents明确报告期2025-06-30和FY2025原件hash，未将比较列称为FY2024原年报。','citations':[{'kind':'metadata','source_id':sid,'field':'report_period_end','value':metadata['report_period_end']}]}],
 'checks':{k:{'status':'pass','reason':v} for k,v in {'scope':'仅指定Microsoft FY2025原件、FY2024事实期间。','truth':'数值、期间和USD单位已核对原件XBRL；所有正文与原DOM一致。','provenance':'运行、数据集、原件hash及数字所在表格单元格均核对。','focus':'只交付一张利润表及两个简短标题，没有附加无关章节或重复数字表。原表中本题不需要的行单列为可优化附带内容；不声称唯一最小。'}.items()},
 'deliveries':deliveries,'metadata_deliveries':[{'id':'M1','source_id':sid,'field':'fiscal_period','value':metadata['fiscal_period']},{'id':'M2','source_id':sid,'field':'report_period_end','value':metadata['report_period_end']}],
 'cost':{'known_usd':str(known),'unknown_reserved_usd':str(unknown)}}
score=evaluate(gold,review,corpus)
usage=Counter()
for c in calls:
    for k,v in (c.get('usage') or {}).items():
        if type(v) is int:usage[k]+=v
output=ROOT/'evaluation-only/reviews/E1-02-sonnet-r1';output.mkdir()
for name,value in [('gold-projection.json',gold),('review.json',review),('score.json',score),('original-check.json',{'source_sha256':digest(raw),'dataset_manifest_sha256':packet['dataset_ref']['manifest_sha256'],'run_manifest_sha256':digest(run/'manifest.json'),'gold_freeze_sha256':digest(ROOT/'evaluation-only/frozen/E1-02-v1.json'),'packet_sha256':digest(run/'attempt-01/review-01/input.json'),'body_dom_matches':len(deliveries),'xbrl_context_verified':True,'cell_verified':True,'model_calls':len(calls),'call_statuses':dict(Counter(c['status'] for c in calls)),'usage':dict(usage),'reviewer_explanation_correction':'System model described fiscal start as derived. Independent check confirms the delivered period is source-bound XBRL. This correction is review-only, not back-fed to runtime.','gold_projection_note':'R1-R3 semantics preserved from pre-run frozen reference. R2 verifies header in R1 text checks plus source-bound metadata; R3 verifies source metadata. No criterion relaxed after seeing output.'})]:save(output/name,value)
print(json.dumps({'status':score['status'],'coverage':score['required_coverage'],'characters':score['characters'],'cost':score['cost']},ensure_ascii=False))
