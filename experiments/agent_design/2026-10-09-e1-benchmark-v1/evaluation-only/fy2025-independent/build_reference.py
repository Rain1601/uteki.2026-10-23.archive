"""Evaluation-only original-source reading export. Never imported by runtime."""
from pathlib import Path
from lxml import html
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[5]
OUT=Path(__file__).resolve().parent
BASE=ROOT/'experiments/agent_design/2026-10-09-data-agent-completion-v1/datasets/msft'
raw=(BASE/'raw/msft-2025-10k.html').read_bytes()
doc=html.fromstring(raw)
blocks=[json.loads(x) for x in (BASE/'indexes/msft-2025-10k/blocks.jsonl').read_text().splitlines()]
source=json.loads((BASE/'indexes/msft-2025-10k/source.json').read_text())
def original(b):
    path=re.sub(r'(ix:[a-z]+)',lambda m:'*[name()="'+m[1]+'"]',b['dom_path'])
    nodes=doc.xpath(path)
    assert len(nodes)==1,(b['ordinal'],path)
    return ' '.join(nodes[0].text_content().split())
# These ranges were actually opened as original DOM nodes during the review.
read_ranges=[(83,156),(548,566),(570,589),(609,616),(774,784),(811,826),(1180,1230)]
read_ord=sorted({i for lo,hi in read_ranges for i in range(lo,hi+1)})
catalog={}
for i in read_ord:
    b=blocks[i-1];t=original(b)
    catalog[f'E{i:04d}']={'ordinal':i,'candidate_block_id':b['block_id'],'dom_path':b['dom_path'],'source_anchor':b.get('source_anchor'),'reported_page':b.get('reported_page'),'original_text':t,'original_text_sha256':hashlib.sha256(t.encode()).hexdigest(),'index_text_matches_original_normalized':t==b['text']}
# Suggested exact spans are convenience for evaluators, never a unique-block requirement.
span_texts={
781:['(In millions, except per share amounts)','Year Ended June 30, 2025 2024 2023','Total revenue 281,724 245,122 211,915'],
817:['Prior period segment information has been recast to conform to the way we internally manage and monitor our business during fiscal year 2025.'],
818:['The recast of prior period information had no impact on our consolidated balance sheets, consolidated income statements, or consolidated cash flows statements.'],
1217:['(In millions) Year Ended June 30, 2025 2024 2023','Intelligent Cloud Revenue $ 106,265 $ 87,464 $ 72,944','Total Revenue $ 281,724 $ 245,122 $ 211,915'],
1219:['(In millions) Year Ended June 30, 2025 2024 2023','Total $ 281,724 $ 245,122 $ 211,915'],
1226:['(In millions) Year Ended June 30, 2025 2024 2023','Server products and cloud services $ 98,435 $ 79,828 $ 65,007','Total $ 281,724 $ 245,122 $ 211,915'],
613:['Azure and other cloud services revenue grew 34% driven by demand for our portfolio of services.']}
for ordinal,quotes in span_texts.items():
    item=catalog[f'E{ordinal:04d}'];text=item['original_text'];spans=[]
    for q in quotes:
        start=text.index(q);spans.append({'char_start':start,'char_end':start+len(q),'quote':q})
    item['suggested_quote_spans']=spans
# Search result phrases independently checked against original nodes (not delivery files).
terms=['Azure','recast','245,122','Microsoft Cloud','Intelligent Cloud','75 billion']
searches=[]
for term in terms:
    hits=[]
    for b in blocks:
        if term.lower() in b['text'].lower():
            t=original(b)
            if term.lower() in t.lower():hits.append({'ordinal':b['ordinal'],'dom_path':b['dom_path'],'text':t})
    searches.append({'term':term,'hits':hits})
# Visible table and original Inline XBRL bind amount, currency, period and absence of dimensions.
number_facts=[]
for n in doc.xpath('/html/body/div[150]/table')[0].iter():
    if 'nonfraction' not in n.tag or n.get('name')!='us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax':continue
    if ' '.join(n.text_content().split()) not in ['281,724','245,122','211,915']:continue
    context=next(x for x in doc.iter() if x.get('id')==n.get('contextref'))
    number_facts.append({'text':' '.join(n.text_content().split()),'attributes':dict(n.attrib),'context_xml':html.tostring(context,encoding='unicode')})
def req(id,meaning,paths,**kw):return {'id':id,'meaning_zh':meaning,'required':True,'acceptable_evidence_sets':paths,**kw}
def ref(*nums):return [f'E{x:04d}' for x in nums]
cases=[
{'case_id':'E1-02','query_zh':'请仅依据 Microsoft FY2025 10-K 中的比较披露，提供 FY2024 公司总收入及单位、财年起止和原文出处；不要求分析增长。','scope':{'company_id':'sec-0000789019','report_year':2025,'observation_period_start':'2023-07-01','observation_period_end':'2024-06-30','source_policy':'specified_report_comparative_disclosure'},'requirements':[
req('R1','FY2024 公司总收入为 USD 245,122 million；这是全年合并总收入，不能用某分部或产品类别替代。',[ref(781),ref(1217),ref(1218,1219),ref(1225,1226)],fact={'decimal':'245122000000','currency':'USD','period_start':'2023-07-01','period_end':'2024-06-30','entity':'Microsoft Corporation and subsidiaries','value_kind':'actual'}),
req('R2','金额必须与 FY2024 列、Year Ended June 30 年度表头和 In millions 单位绑定；仅裸数字不算命中。',[ref(781),ref(1217),ref(1218,1219),ref(1225,1226)],allow_header_metadata_equivalence=True,metadata_requirement='Record-linked validated fiscal period start=2023-07-01,end=2024-06-30; exact original XBRL context C_c19fe6c0-0e87-44b0-aa2a-d9c6e40a5862 is provided in inline_xbrl_total_revenue_check. Year Ended June 30 table text alone does not literally state start date.'),
req('R3','明确原件属于 FY2025 10-K，数据为其中 FY2024 比较列；不得说已读取 FY2024 年报原件。',[],metadata_requirement='frozen source manifest with report_period_end=2025-06-30 and original hash')],
'alternative_paths_requiring_context':[{'evidence':ref(572),'condition_zh':'表头只有 2024 而没有 June 30；额外提供已验证的公司财年期间元数据或原文期间表头，可作为等价简明出处。'},{'evidence':ref(587),'condition_zh':'同样需要补全 June 30 财年期间，且必须使用 Total Revenue 行。'}],
'conditional_context':[{'trigger':'解释跨年原始披露与重列是否影响总收入','required_evidence_sets':[ref(817,818)],'reason_zh':'先交代重列对象为分部，再保留其未影响合并利润表的限定；不能仅说有重列便认为总收入变化。'},{'trigger':'对合并范围或 GAAP 有明确问题','required_evidence_sets':[ref(813,815)],'reason_zh':'合并报表包含公司及子公司并抵消内部交易。不是一个总收入数字查询必取的整份政策。'}],
'optional_evidence':[{'sets':[ref(781)],'note_zh':'同一表中的 FY2025/FY2023 比较列可以作为表格上下文。'}],
'excess_zh':['获取六处重复的同一总收入；没有增加解释能力。','整份会计政策、现金流表、各产品介绍与竞争章节。','为回答单个数字追加完整分部利润分析。'],
'misleading_zh':['把 245,122 当美元而非百万美元。','把 FY2024 错当 2024-01-01 至 2024-12-31。','用后续 FY2025 比较披露回答截至 2024 年的已知信息问题。','把分部重列说成合并总收入重列。'],
'footnote_review_zh':'利润表 Total revenue 行没有单独脚注标记。Refer to accompanying notes 不意味着必须附上所有附注。地理表 (a) 指向 United States 行，并不改变 Total 行；若选择地理表作总额出处，不强制读取其 OEM 地理分配脚注。'},
{'case_id':'E1-05','query_zh':'请依据 Microsoft FY2025 10-K，提供三个报告分部及各自核心业务的原始材料，保留所属关系与必要限定，不要求所有产品清单。','scope':{'company_id':'sec-0000789019','report_year':2025,'source_policy':'specified_report_business_scope'},'requirements':[
req('B1','三个报告分部：Productivity and Business Processes、Intelligent Cloud、More Personal Computing；不能把产品或跨分部指标当成第四个分部。',[ref(86),ref(550),ref(1181)]),
req('B2','PBP：Microsoft 365 Commercial、Microsoft 365 Consumer、LinkedIn、Dynamics 四个核心组合，并保留其归属。',[ref(90,91,93,95,97,99),ref(1184,1185,1187,1189,1191,1193)],facets=['Microsoft 365 Commercial products and cloud services','Microsoft 365 Consumer products and cloud services','LinkedIn','Dynamics products and cloud services']),
req('B3','Intelligent Cloud：Server products and cloud services（含 Azure and other cloud services 及服务器产品）和 Enterprise and partner services 两类；不能只给 Azure。',[ref(117,118,120,122),ref(1197,1198,1200,1202)],facets=['Server products and cloud services','Azure and other cloud services','Server products','Enterprise and partner services']),
req('B4','More Personal Computing：Windows and Devices、Gaming、Search and news advertising 三类，并保留其归属。',[ref(143,144,146,148,150),ref(1203,1204,1206,1208,1210)],facets=['Windows and Devices','Gaming','Search and news advertising'] )],
'conditional_context':[{'trigger':'与 FY2024 的分部对比，或解释 Windows 商业成分归属变化','required_evidence_sets':[ref(87),ref(551),ref(817)],'reason_zh':'FY2025 分部口径重排，Microsoft 365 的商业组成集中到 PBP。'},{'trigger':'交付表中含 FY2024 分部金额','required_evidence_sets':[ref(551),ref(817)],'reason_zh':'必须提示前期分部数字已按 FY2025 内部管理口径重列。'}],
'optional_evidence':[{'sets':[ref(127)],'note_zh':'用一个段落帮助解释 Azure 的业务作用。'},{'sets':[ref(101),ref(103),ref(108),ref(110),ref(132)],'note_zh':'用户不熟悉业务名称时可少量补充功能，不能机械全部追加。'}],
'excess_zh':['Item 1 和 Note 18 同一份完整分部列表各交付一次。','所有竞对、所有增长驱动、费用分配或每个产品功能。','仅因出现 AI 而额外加入整段 AI 战略、OpenAI 合作和 Azure AI Foundry。'],
'misleading_zh':['把 Microsoft Cloud 当成报告分部。','只给收入类别表而不交代业务功能和分部归属。','把 Windows 所有产品都归 MPC，忽略 Windows Commercial 的区分。','把 GitHub、Azure AI Foundry 等全部提升为独立报告分部。'],
'granularity_policy_zh':'必需覆盖的是三个分部及其九个顶层业务组合。原文列表包含更细的产品名，完整保留原始段落可以接受；不按每个子产品强制新增独立节点，不以遗漏每个子产品名判整题失败。九组中 M365 Commercial、Consumer 各算一组；Intelligent Cloud 的两组、MPC 三组。'},
{'case_id':'E1-06','query_zh':'请依据 Microsoft FY2025 10-K，提供 Microsoft Cloud、Intelligent Cloud 与 Azure 的口径定义及 FY2025 对应披露指标，明确金额/增长率差异，不推算未披露Azure收入。','scope':{'company_id':'sec-0000789019','report_year':2025,'observation_period_ends':['2025-06-30'],'source_policy':'specified_report_metrics_and_segments'},'requirements':[
req('C1','Microsoft Cloud 是包含 M365 Commercial cloud、Azure and other cloud services、LinkedIn 商业部分、Dynamics 365 的跨业务指标；FY2025 168.9 billion USD；不强制附 FY2024 金额。',[ref(1227)],fact={'fy2025_usd_billion':'168.9'}),
req('C2','Intelligent Cloud 是报告分部，范围包括 Server products and cloud services 以及 Enterprise and partner services；不能等同 Microsoft Cloud。',[ref(117,118,120,122),ref(1197,1198,1200,1202)]),
req('C3','Intelligent Cloud 分部 FY2025 106,265 million USD，按 June 30 财年；不强制附 FY2024 金额。',[ref(1217),ref(587)],fact={'fy2025_usd_million':'106265'},alternative_context_note='E0587 需要另外保留 June 30 年度元数据。'),
req('C4','Azure and other cloud services 包含 cloud/AI consumption、GitHub cloud、Nuance Healthcare cloud、virtual desktop 和其他云服务；范围不是 Azure 单体，也不包括整个服务器产品组。',[ref(120),ref(1200),ref(564)]),
req('C5','该文件明确披露 Azure and other cloud services FY2025 收入增长 34%；不能把增长率当美元金额。',[ref(613)],fact={'metric':'Azure and other cloud services revenue growth','fy2025_percent':'34','comparison':'corresponding previous fiscal year'}),
req('C7','Azure 是供开发者、IT 专业人员及企业构建、部署、管理应用的云服务平台；其收入主要受 IaaS/PaaS 消费影响。Azure 产品定义与 Azure and other cloud services 财务组合定义分开。',[ref(127)]),
req('C6','区分指标重叠与可加总：这三个口径有包含/重叠，不是可相加得到公司收入的三个并列分部。',[ref(1227,120,122),ref(1227,1200,1202)],derived_judgment=True)],
'conditional_context':[{'trigger':'展示 FY2024 与 FY2025 分部可比性','required_evidence_sets':[ref(551),ref(817)],'reason_zh':'FY2024 分部数字在 FY2025 报告中为重列口径。'},{'trigger':'解释 98,435 / 79,828 million 是否等于 Azure 收入','required_evidence_sets':[ref(1226,120),ref(1226,1200)],'reason_zh':'这是 Server products and cloud services 大类，含服务器产品，不是 Azure 的单独金额。'},{'trigger':'把 34% 标为实际同比而非固定汇率增长','required_evidence_sets':[ref(557,613)],'reason_zh':'Metrics 说明增长对应上一财年期间；这里没有 constant currency 标签。'}],
'optional_evidence':[{'sets':[ref(561)],'note_zh':'Microsoft Cloud 定义表，是 E1227 的定义部分等价出处，但表本身没有收入金额。'},{'sets':[ref(128)],'note_zh':'只有需进一步解释 Azure AI/Foundry 时有用，本题不强制。'}],
'excess_zh':['Azure 全部产品功能及竞争说明。','完整 PBP/MPC 产品名录。','所有收入、利润、毛利和费用表；只为口径区分没有必要。','将同一段 Microsoft Cloud 定义在 MD&A 与 Note 18 重复附上。'],
'misleading_zh':['Microsoft Cloud=Intelligent Cloud=Azure。','98,435 million 是 Azure FY2025 收入。','把 34% 应用于 Intelligent Cloud 或整个 Microsoft Cloud。','将 168.9、106.265 和未披露的 Azure 金额相加。'],
'negative_finding_zh':'本轮在选定 10-K 内的 Azure 全文匹配、业务说明、指标定义、MD&A、Note 18 数字表中，未找到 Azure 或 Azure and other cloud services 单独绝对金额；这是此原件内的有范围负面查找结论，不等于公司在财报新闻稿或其他官方渠道从未披露。不得给“负面事实”编造单一证明块。'}]
omission_reasons={
'R1':'去掉金额、总额标签或单位，不能确定答的是哪个值。','R2':'去掉年度表头/期间元数据，FY2024可能被误读为自然年或季度。','R3':'没有报告身份，无法证明回答遵守FY2025比较披露范围。',
'B1':'缺分部身份，产品、组合指标可能被误升为分部。','B2':'四个顶层组合缺一个，就会遗漏该分部的一项核心业务；不要求每个子产品各建节点。','B3':'只保留Azure会漏本地服务器产品及企业伙伴服务两部分。','B4':'只给Windows或Gaming会漏另外核心组合，无法覆盖分部全貌。',
'C1':'没有组成与金额，跨分部Microsoft Cloud可能被误当Intelligent Cloud。','C2':'没有服务器及伙伴服务边界，无法区分分部和云指标。','C3':'缺分部金额，无法对应题目要求的FY2025指标。','C4':'没有组合定义，34%容易被错误称为Azure单体增长。','C5':'缺指标/单位，无法区分披露增长与未披露绝对金额。','C6':'没有包含关系，使用者可能把重叠指标当可加总分部；这是从原文组成推导的检查，不要求原文恰好写不可相加。','C7':'Azure本身和Azure and other cloud services不是同一个命名对象，只有组合定义不能完整回答产品平台定义。'}
for case in cases:
    for requirement in case['requirements']:
        requirement['why_omission_hurts_zh']=omission_reasons[requirement['id']]
    case['equivalence_rule_zh']='证据集合是已核验候选包，不强制每个标题块都出现。由来源元数据或可靠章节路径保留同等归属/期间上下文可以替代标题；新出处原文复核后可扩充。'
result={'schema_version':'uteki-evaluation-reference-candidate-v1','status':'candidate_needs_root_review_and_freeze','usage':'evaluation_only_never_runtime_input','created_date':'2026-10-09','reviewer':'Codex subagent e1_gold_reading','independence':{'agent_deliveries_opened':False,'prior_evaluation_files_opened':False,'inherited_context_contains_prior_result_summary':True,'claim':'original-first reconstruction; not fully blind independent gold'},'source':source,'original_sha256_verified':hashlib.sha256(raw).hexdigest(),'read_coverage':{'ranges_in_prepared_ordinal_navigation':read_ranges,'original_nodes_read':len(read_ord),'method':'Resolve navigation DOM paths in original SEC HTML; all quotes are original DOM normalized-visible text. Colon-named ix elements resolved with name(), not by trusting extracted quote.','not_claimed':['every paragraph manually read','perfect exhaustive minimal evidence','other FY originals reviewed']},'cases':cases,'evidence_catalog':catalog,'search_log':searches,'inline_xbrl_total_revenue_check':number_facts,'grading_policy':{'unit':'semantic requirement; alternative source occurrences accepted','hard_fail':['wrong company/source/vintage','wrong number/unit/period','missing required semantics','fabricated or non-verifiable citation','materially misleading metric substitution'],'no_unique_block_lock':True,'unlisted_valid_evidence':'manual original verification then add as equivalent with revision audit','duplicate_policy':'same fact at several origins earns coverage once; unrelated excess and repeat text recorded separately','excess_policy':'Separate semantic irrelevant content from unavoidable whole-block/table overhead; no arbitrary length cutoff in this candidate.','optional_credit':'optional evidence does not repair missing required evidence','conditional_requirements':'activate only when answer/query makes the triggering assertion; do not inflate minimal sets by blindly collecting all optional context','next_review':'Second reviewer should inspect original and resolve granularity/conditional context before freeze; no runtime run scored by this candidate yet.'}}
(OUT/'reference.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print('wrote',OUT/'reference.json','cases',len(cases),'original nodes',len(catalog))
