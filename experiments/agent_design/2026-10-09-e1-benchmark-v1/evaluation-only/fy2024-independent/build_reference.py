"""Evaluation-only original reference builder. Never load into runtime."""
from pathlib import Path
from lxml import html
import json,re,hashlib
P=Path(__file__).resolve().parent;E=P.parents[1];sid='source-8602d79f703e48c18c2f27c3'
idx=E/'datasets/msft-acquired-fy2024/indexes'/sid
rawpath=E/'acquisition/workspace/sources/objects/cdcc8db91bc8ac88239ffd09c19afc85a65460b0a981604ebcc4dd9ebdac8e76.bin'
raw=rawpath.read_bytes();doc=html.fromstring(raw);source=json.loads((idx/'source.json').read_text());assert hashlib.sha256(raw).hexdigest()==source['raw_sha256']
bs=[json.loads(s) for s in (idx/'blocks.jsonl').read_text().splitlines()]
def node(b):return doc.xpath(re.sub(r'(ix:[a-z]+)',lambda m:'*[name()="'+m[1]+'"]',b['dom_path']))[0]
ranges=[(142,168),(625,639),(646,650),(663,670),(861,867),(894,905),(1302,1349),(1545,1549)]
catalog={}
for i in sorted({i for lo,hi in ranges for i in range(lo,hi+1)}):
 b=bs[i-1];t=' '.join(node(b).text_content().split());assert t==b['text'];catalog[f'F24-{i:04d}']={'ordinal':i,'source_snapshot_id':sid,'candidate_block_id':b['block_id'],'dom_path':b['dom_path'],'source_anchor':b.get('source_anchor'),'reported_page':b.get('reported_page'),'original_text':t,'original_text_sha256':hashlib.sha256(t.encode()).hexdigest()}
fy25=json.loads((P.parent/'fy2025-independent/reference-revalidated.json').read_text())
for k in ['E0781','E1217','E0551','E0817','E0818','E1182','E1187','E1200','E1206']:
 catalog['F25-'+k[1:]]=dict(fy25['evidence_catalog'][k],source_snapshot_id=fy25['source']['source_snapshot_id'])
facts=[]
for i in [865,1337]:
 for n in node(bs[i-1]).iter():
  t=' '.join(n.text_content().split())
  if 'nonfraction' not in n.tag or t not in ['245,122','77,728','105,362','62,032']:continue
  ctx=next(x for x in doc.iter() if x.get('id')==n.get('contextref'))
  facts.append({'evidence_id':f'F24-{i:04d}','value':t,'attributes':dict(n.attrib),'context_xml':html.tostring(ctx,encoding='unicode')})
quotes={865:['(In millions, except per share amounts)','Year Ended June 30, 2024 2023 2022','Total revenue 245,122 211,915 198,270'],1337:['(In millions) Year Ended June 30, 2024 2023 2022','Revenue Productivity and Business Processes $ 77,728 $ 69,274 $ 63,364 Intelligent Cloud 105,362 87,907 74,965 More Personal Computing 62,032 54,734 59,941 Total $ 245,122 $ 211,915 $ 198,270']}
for n,qs in quotes.items():
 item=catalog[f'F24-{n:04d}'];item['suggested_quote_spans']=[]
 for q in qs:
  x=item['original_text'].index(q);item['suggested_quote_spans'].append({'char_start':x,'char_end':x+len(q),'quote':q})
period={'start':'2023-07-01','end':'2024-06-30'}
def req(id,meaning,sets,why,**kwargs):return {'id':id,'required':True,'meaning_zh':meaning,'acceptable_evidence_sets':sets,'why_omission_hurts_zh':why,**kwargs}
amount_sets=[['F24-0865'],['F24-1337'],['F24-1338','F24-1339'],['F24-1345','F24-1346']]
base_amount=req('A1','FY2024公司总收入为245,122 million USD，来自FY2024原年报的公司总额行。',amount_sets,'缺金额、单位、总额身份或原报告版本，无法可靠回答。',fact={'value_usd':'245122000000','observation_period':period})
base_period=req('A2','FY2024期间为2023-07-01至2024-06-30。',[['F24-0865'],['F24-1337']], '只有2024标签不能区分财年、自然年或季度。',metadata_requirement='The selected value must bind to validated fiscal start/end metadata; original XBRL context C_6dbdb3a2-9baf-41b4-922d-f59879124337 gives start/end. Header Year Ended June30 gives end, not literal start date.')
common_excess=['所有同额出处重复附上。','公司产品功能、增长原因、现金流、完整会计政策。','为单个总额问题加入三分部数字与长篇重列说明。']
cases=[
{'case_id':'E1-01','query_zh':'请仅依据 Microsoft FY2024 10-K 原年报，提供 FY2024 公司总收入、金额单位、财年起止及原文出处。','requirements':[base_amount,base_period,req('A3','使用FY2024原件，不能借用FY2025比较列替代。',[],'同额不能证明读过指定版本。',metadata_requirement=f'source_snapshot_id={sid}; report_period_end=2024-06-30; raw hash verified')],'alternative_context':[{'sets':[['F24-0649'],['F24-0666']],'condition_zh':'MD&A只有2024列，允许补充分部/总额身份及已验证财年起止元数据后作为等价出处。'}],'conditional_context':[{'trigger':'明确提问GAAP与合并范围','sets':[['F24-0897','F24-0900']]},{'trigger':'解释FY2024本身历史重列','sets':[['F24-0898']],'note_zh':'这是FY2024原件对其更早比较期的表述，不能拿来替代FY2025分部重列原因。'}],'excess_zh':common_excess,'misleading_zh':['FY2025比较列冒充FY2024原件','把收入总额换成分部金额','单位或期间错误']},
{'case_id':'E1-03','query_zh':'请分别提供 Microsoft FY2024 与 FY2025 两份10-K各自披露的FY2024公司总收入，保留两份出处、单位与期间，核对是否一致；不要把重复披露相加。','requirements':[req('D1','FY2024原件的FY2024总额245,122 million USD。',amount_sets,'只有后年版本不能完成两源比较。'),req('D2','FY2025原件的FY2024比较总额245,122 million USD。',[['F25-0781'],['F25-1217']],'只有原年版本不能证明后续披露是否一致。'),req('D3','两份记录各自绑定来源、同一财年期间和单位；值一致，不相加。',[],'重复披露若只保留一个出处，无法核对；若相加，则把一个期间算了两遍。',metadata_requirement='two distinct source IDs/raw hashes; each FY2024 fiscal period 2023-07-01 to2024-06-30; USD million',derived_judgment=True)],'conditional_context':[{'trigger':'说明为何分部重列但总额不变','sets':[['F25-0817','F25-0818']]}],'optional_zh':['可附FY2025原文明确说重列不影响合并利润表；仅核对两数相同不强制。'],'excess_zh':['每份年报的六处同额位置全部交付。','完整FY2024和FY2025两份财报。','对季度/产品收入做无必要推算。'],'misleading_zh':['将两数相加为490,244 million','因为值相同就只保留一份引用','将FY2025报告总收入281,724当作其FY2024比较值']},
{'case_id':'E1-04','query_zh':'以2024-08-01为资料可得截止日，提供Microsoft FY2024公司总收入及金额单位、财年起止、原文出处，不使用截止日之后发布的材料。','requirements':[base_amount,base_period,req('T1','财报发布时间2024-07-30不晚于2024-08-01；FY2025年报2025-07-30为未来材料，不能作为交付证据。',[],'只判断report_period_end会错误纳入后续发表的比较列，造成前视偏差。',metadata_requirement='available_at cutoff validation per source, not report_period_end; FY2024 allowed; FY2025 forbidden')],'optional_zh':['原件签署段F24-1546可作辅助日期旁证；签署日不能单独替代SEC公开可得日期。'],'excess_zh':common_excess,'misleading_zh':['同额便认为未来披露可用','只用报告期结束日判断可得性','将抓取日期误作首次公开日期'],'required_runtime_audit_zh':'最终交付、所有已读正文和查询输出都不得将未来FY2025内容提供给模型；目录只出现未来source的发布/可得日期作排除说明可以，不能读其财务正文后再在最终删掉伪装合规。'},
{'case_id':'E1-07','query_zh':'请对比Microsoft FY2024与FY2025两份10-K各自披露的FY2024三个报告分部收入，分别保留来源版本、单位、期间和解释差异的原文；不要将重列差异当成自然业务增长。','requirements':[req('S1','FY2024原年报：PBP77728、IntelligentCloud105362、MPC62032，单位millionUSD，均为FY2024。',[['F24-1337'],['F24-0666']],'缺任一分部或年份，会无法做完整同期间跨版本比较。',facts_usd_million={'Productivity and Business Processes':'77728','Intelligent Cloud':'105362','More Personal Computing':'62032'}),req('S2','FY2025年报FY2024比较列：PBP106820、IntelligentCloud87464、MPC50838，单位millionUSD。',[['F25-1217']],'不能用FY2025本年数字或旧口径冒充重列后比较数。',facts_usd_million={'Productivity and Business Processes':'106820','Intelligent Cloud':'87464','More Personal Computing':'50838'}),req('S3','FY2025原件明确2024年8月宣布分部组成变化，特别把Microsoft365商业组成集中到PBP，前期分部数字按FY2025管理口径重列。',[['F25-0817'],['F25-0551']],'仅见数字不同，无法区分口径调整与业务增长。'),req('S4','两组数同为FY2024，来源版本必须分开，不覆盖旧数、不相加、不计算自然同比增长。',[],'同分部名和同期间不代表同口径；覆盖会销毁历史披露。',metadata_requirement='same observation period; distinct source publication/report vintage; retain as-reported versus recast basis',derived_judgment=True)],'conditional_context':[{'trigger':'说明分部变了但公司总额不变','sets':[['F25-0818']],'note_zh':'两张分部表的合计都245122；E0818直接限定重列对合并表无影响。'},{'trigger':'需要解释具体业务移动而非仅概括公告','sets':[['F24-1324','F25-1187'],['F24-1318','F25-1200']],'note_zh':'原先WindowsCommercial在MPC；新商业组合含WindowsCommercial。原文描述可支撑归属变化，但不能由此杜撰每项迁移金额。'}],'optional_zh':['列重列后减重列前差额：PBP+29092、IC-17898、MPC-11194 million；合计0。必须标重列差额，不叫增长。'],'excess_zh':['把两年所有产品功能列表都拿来。','所有费用、利润、毛利、区域和每产品收入。','同年报MD&A和附注两套相同表全部重复。'],'misleading_zh':['PBP增长37.4%（把同期间重列差异说成增长）','沿用FY2024旧分部定义解释FY2025重列金额','假定全部29092都来自WindowsCommercial，原件没有这种迁移金额分解'],'alternative_context':[{'sets':[['F25-0587']],'condition_zh':'FY2025 MD&A分部表也可等价；该证据在FY2025 reference-revalidated.json中，使用时需导入并提供财年起止。'}]}
]
for c in cases:c['equivalence_policy_zh']='按语义及来源身份判定。这里列已验证候选，不锁死单一块ID。其他原文出现可复核后加入；结构化结果须能返回原始位置。'
# Include FY2025 MD&A equivalent explicitly, and keep all referenced evidence self-contained.
catalog['F25-0587']=dict(fy25['evidence_catalog']['E0587'],source_snapshot_id=fy25['source']['source_snapshot_id'])
searches=[]
for term in ['245,122','recast','77,728','105,362','62,032','Microsoft Cloud revenue']:
 hits=[]
 for b in bs:
  if term.lower() in b['text'].lower():
   t=' '.join(node(b).text_content().split());hits.append({'ordinal':b['ordinal'],'dom_path':b['dom_path'],'original_text':t})
 searches.append({'term':term,'hits':hits})
result={'schema_version':'uteki-evaluation-reference-candidate-v1','status':'candidate_needs_root_review_and_freeze','usage':'evaluation_only_never_runtime_input','independence':{'no_agent_deliveries_opened':True,'prior_result_summary_inherited':True,'method':'original-first reconstruction; not fully blind'},'sources':[source,fy25['source']],'original_sha256_verified':hashlib.sha256(raw).hexdigest(),'read_coverage':{'fy2024_ranges':ranges,'fy2024_original_nodes_read':sum(z-a+1 for a,z in ranges),'fy2025_reuse':'original nodes previously re-read and rebound to freshly acquired source; no Agent output used'},'cases':cases,'evidence_catalog':catalog,'inline_xbrl_facts':facts,'search_log':searches,'additional_not_scored_observation':{'topic':'MicrosoftCloud FY2024 cross-vintage differs','fy2024_original_usd_billion':'137.4','fy2025_comparative_usd_billion':'137.7','note':'Do not silently canonicalize cloud revenue across reports; not an added requirement for E1-01/03/04/07. Definition difference merits separate future question.'},'grading_policy':{'required_coverage':'semantic requirement with correct report vintage, observation period, units and provenance','irrelevance':'per-unit why removable, distinct from necessary table/paragraph context','duplicate':'same-source equivalent occurrences count coverage once; E1-03/07 explicitly need both source vintages even when values equal','scope_failures':'wrong issuer, wrong report vintage, unsupported metadata, future information leakage, dropped conflicting vintage','no_unique_minimum_claim':True}}
(P/'reference.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('Wrote',len(cases),'cases;',result['read_coverage']['fy2024_original_nodes_read'],'FY24 original nodes')
