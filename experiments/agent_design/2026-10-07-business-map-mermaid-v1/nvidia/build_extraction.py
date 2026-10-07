"""Package a Codex-reviewed FY2025 candidate; no model or network calls."""
from pathlib import Path
import hashlib
import html as escape_html
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from uteki.domain.business_map import business_map_from_dict

URL = 'https://s201.q4cdn.com/141608511/files/doc_financials/2025/annual/NVIDIA-2025-Annual-Report.pdf'
IR = 'https://investor.nvidia.com/financial-info/annual-reports-and-proxies/default.aspx'
SEC = 'https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/nvda-20250126.htm'
DOCUMENT = 'nvidia-fy2025-annual-report-10k'
original = (HERE / 'source.pdf').read_bytes()
assert original.startswith(b'%PDF-')
original_sha = hashlib.sha256(original).hexdigest()
source_text = (HERE / 'source.txt').read_text()
pages = source_text.split('\f')
assert len(pages) == 182 and 'For the fiscal year ended January 26, 2025' in source_text
normalize = lambda text: re.sub(r'\s+', ' ', text).strip()
esc = escape_html.escape
blocks = []
for page, text in enumerate(pages, 1):
    for page_block, content in enumerate(re.split(r'\n\s*\n', text), 1):
        content = normalize(content)
        if content:
            blocks.append(dict(ordinal=len(blocks)+1, page=page, page_block=page_block, text=content))

style = '<style>body{max-width:950px;margin:40px auto;padding:0 20px;font:17px/1.65 sans-serif}section{padding:24px 0;border-top:1px solid #ddd}code{overflow-wrap:anywhere}blockquote{margin:15px 0}p{overflow-wrap:anywhere}</style>'
source_parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>NVIDIA FY2025 PDF derived text</title>', style,
    '<h1>NVIDIA FY2025 · PDF 派生文本 / PDF-derived text</h1>',
    '<p>这是 pdftotext -layout 的派生阅读视图，不是官方 HTML 原件。已折叠空白，未翻译或改写；跨页段落保留在各自页面，不自动拼接。页号是 PDF 实际页序号。<a href="source.pdf">官方完整 PDF</a></p>']
last_page = None
for block in blocks:
    if block['page'] != last_page:
        if last_page is not None:
            source_parts.append('</section>')
        last_page = block['page']
        source_parts.append(f'<section id="page-{last_page}"><h2>PDF page {last_page}</h2><a href="source.pdf#page={last_page}">查看 PDF 此页 / Open PDF page</a>')
    source_parts.append(f'<p id="p-{block["ordinal"]:05d}" data-page-block="{block["page_block"]}">{esc(block["text"])}</p>')
source_parts.append('</section></html>')
source_html = '\n'.join(source_parts).encode()
(HERE / 'source.html').write_bytes(source_html)
source_sha = hashlib.sha256(source_html).hexdigest()
evidence, locators = [], {}
printed_pages = {97: '5', 98: '6', 99: '7', 149: '57', 150: '58'}


def ev(identity, page, page_block, section, support, quote=None):
    found = [b for b in blocks if b['page'] == page and b['page_block'] == page_block]
    assert len(found) == 1
    block = found[0]
    text = block['text']
    quote = quote or text
    assert quote in text and quote in normalize(pages[page-1])
    digest = hashlib.sha256(text.encode()).hexdigest()
    evidence.append(dict(id=identity, document_id=DOCUMENT, section_path=section,
        paragraph_ordinal=block['ordinal'], text_hash=digest, source_url=URL, support=support))
    locators[identity] = dict(local_path=str((HERE/'evidence.html').relative_to(ROOT)), fragment=identity,
        exact_quote=quote, full_source_text=text, text_hash=digest,
        source_local_path=str((HERE/'source.html').relative_to(ROOT)), source_fragment=f'p-{block["ordinal"]:05d}',
        pdf_page_index=page-1, pdf_page_number=page, printed_page_label=printed_pages[page],
        original_source_path=str((HERE/'source.pdf').relative_to(ROOT)), pdf_fragment=f'page={page}',
        page_block_ordinal=page_block, source_block_ordinal=block['ordinal'],
        normalization='pdftotext -layout; split on blank lines per physical page; whitespace collapsed and trimmed')


item = ['Form 10-K', 'Part I', 'Item 1. Business']
note = ['Form 10-K', 'Part II', 'Item 8', 'Note 1. Organization and Summary of Significant Accounting Policies']
ev('e-reporting',97,5,item+['Our Businesses'],'公司只列两个报告分部。')
ev('e-compute-segment',97,6,item+['Our Businesses'],'Compute & Networking 的产品范围和报告归属。')
ev('e-graphics-segment',97,7,item+['Our Businesses'],'Graphics 的产品范围；包括汽车信息娱乐，与自动驾驶平台区分。')
ev('e-markets',97,8,item+['Our Markets'],'四个终端市场名称；这不是报告分部清单。')
ev('e-data-center',97,9,item+['Data Center'],'数据中心平台的计算、网络、软件及服务，以系统、子系统或模块交付。')
ev('e-compute-products',97,10,item+['Data Center'],'计算产品包括超算平台和服务器、GPU/CPU，以及软件和云服务。')
ev('e-networking',97,11,item+['Data Center'],'InfiniBand/Ethernet、适配器、线缆、DPU、交换芯片/系统及软件栈。')
ev('e-customers',97,12,item+['Data Center'],'终端客户和直接客户渠道；OEM、ODM、集成商及经销商。')
ev('e-paid-software',98,3,item+['Data Center'],'AI Enterprise、vGPU 是付费软件许可；DGX Cloud 是托管训练云服务。')
ev('e-gaming-products',98,7,item+['Gaming'],'游戏市场的 GeForce GPU、GeForce NOW，以及主机 SoC 和开发服务。')
ev('e-professional',98,9,item+['Professional Visualization'],'面向设计、制造和数字内容创作的专业可视化市场。')
ev('e-rtx',98,10,item+['Professional Visualization'],'专业设计/内容应用通过 NVIDIA RTX GPU 和软件加速。')
ev('e-omniverse',98,11,item+['Professional Visualization'],'Omniverse 面向企业采用软件订阅；个人免费。')
ev('e-automotive',99,1,item+['Automotive'],'Automotive 市场的自动驾驶平台方案；不将整个汽车业务归入单一报告分部。')
ev('e-drive',99,2,item+['Automotive'],'DRIVE Hyperion 的计算硬件、DRIVE OS、传感器及软件平台。')
ev('e-auto-simulation',99,3,item+['Automotive'],'基于 Omniverse 的数据中心仿真服务于自动驾驶开发与验证。')
ev('e-revenue-types',149,10,note+['Revenue Recognition'],'公司收入来源包括硬件/系统销售、许可和开发、软件许可及云服务。')
ev('e-product-sales',149,11,note+['Product Sales Revenue'],'产品销售和相关支持服务的收入确认；未提供逐产品独立售价。')
ev('e-software-licenses',150,3,note+['Software Licensing'],'软件许可可为永久或订阅；支持服务单独按期确认。')
ev('e-cloud-services',150,4,note+['Cloud Services'],'托管云服务按订阅，或订阅结合用量收费；非逐产品价目表。')

businesses, relationships, labels, roles = [], [], {}, {}


def node(identity,name,zh,kind,description,refs,money=None,basis='explicit',products=(),role=None):
    businesses.append(dict(id=identity,name=name,kind=kind,description=description,
        products_services=list(products),customers=[],importance_signals=(['终端市场维度；不是报告分部；不可与报告分部直接相加。'] if role=='market' else []),
        monetization=[] if money is None else [dict(description=money,basis=basis,evidence_ids=refs)],
        evidence_ids=refs,review_status='candidate'))
    labels[identity]=dict(en=name,zh=zh)
    roles[identity]=role or kind


def edge(source,target,kind,refs,description):
    relationships.append(dict(source_id=source,target_id=target,kind=kind,description=description,
                              evidence_ids=refs,review_status='candidate'))


node('nvidia','NVIDIA','英伟达','company','提供加速计算平台；本图分开呈现两个报告分部与四个终端市场。',
     ['e-reporting','e-compute-segment','e-graphics-segment','e-markets','e-revenue-types'],
     '硬件与系统销售、许可及开发、软件许可和云服务。')
node('compute-networking','Compute & Networking','计算与网络','reportable_segment',
     '包括数据中心计算与软件、网络、自动驾驶平台、Jetson 和 DGX Cloud。',['e-compute-segment'])
node('graphics','Graphics','图形','reportable_segment',
     '包括 GeForce、工作站 RTX、vGPU、汽车信息娱乐和 Omniverse Enterprise。',['e-graphics-segment'])
edge('compute-networking','nvidia','reported_under',['e-reporting','e-compute-segment'],'年报明确列示的报告分部。')
edge('graphics','nvidia','reported_under',['e-reporting','e-graphics-segment'],'年报明确列示的报告分部。')

specs = [
 ('data-center-compute','Data Center compute platforms','数据中心计算平台','compute-networking',
  'GPU/CPU、超算平台及服务器，与 AI/HPC 软件栈组成计算方案。',['e-compute-segment','e-compute-products','e-data-center','e-product-sales'],
  '硬件及系统产品销售；可附带支持服务，未抽取逐产品价格。','explicit',['GPUs','CPUs','Servers','Supercomputing platforms']),
 ('networking','Networking','网络产品','compute-networking',
  '连接计算节点的 InfiniBand 和 Ethernet 产品与软件。',['e-compute-segment','e-networking','e-product-sales'],
  '网络硬件产品销售；本文未拆分各类组件的收入与售价。','explicit',['InfiniBand','Ethernet','DPUs','Adapters','Switches','Cables']),
 ('ai-software-cloud','NVIDIA AI Enterprise and DGX Cloud','AI 企业软件与 DGX 云','compute-networking',
  '企业级 AI 软件许可与全托管 AI 训练云服务；两者不是同一种收费产品。',['e-compute-segment','e-paid-software','e-software-licenses','e-cloud-services'],
  'AI Enterprise 提供付费软件许可；DGX Cloud 提供托管服务。公司云服务政策为订阅或订阅加用量，未披露此处逐产品价格。','explicit',['NVIDIA AI Enterprise','DGX Cloud']),
 ('drive','NVIDIA DRIVE','自动驾驶平台','compute-networking',
  'DRIVE Hyperion 组合计算硬件、车内操作系统、传感器和自动驾驶软件平台。',['e-compute-segment','e-drive'],
  '本轮原文界定平台产品范围，未单独说明 DRIVE 各组件的收费安排。','unknown',['DRIVE Hyperion','DRIVE AGX','DRIVE OS']),
 ('jetson','Jetson','Jetson 机器人与嵌入式平台','compute-networking',
  '用于机器人及其他嵌入式平台，年报列入 Compute & Networking。',['e-compute-segment'],
  '本轮材料未单列 Jetson 收入或计费方式。','unknown',['Jetson']),
 ('geforce','Gaming offerings: GeForce, cloud gaming and consoles','游戏产品：GeForce、云游戏与主机','graphics',
  '面向游戏 PC 的 GPU、云游戏，以及游戏主机 SoC 和开发服务。',['e-graphics-segment','e-gaming-products','e-product-sales'],
  'GPU 等产品销售及游戏服务；所读业务段落未列示 GeForce NOW 套餐收费方式。','explicit',['GeForce RTX','GeForce GTX','GeForce NOW','Console SoCs']),
 ('rtx-vgpu','Workstation RTX and vGPU','工作站 RTX 与 vGPU','graphics',
  '专业工作站图形 GPU，以及图形密集型虚拟桌面和工作站软件。',['e-graphics-segment','e-rtx','e-paid-software','e-product-sales'],
  '工作站 GPU 产品销售与 vGPU 付费软件许可。','explicit',['Quadro / NVIDIA RTX','NVIDIA vGPU']),
 ('omniverse','Omniverse / Omniverse Enterprise','Omniverse 平台','graphics',
  '用于虚拟世界仿真、工业 AI 和数字孪生的开发平台。',['e-graphics-segment','e-omniverse'],
  'Omniverse 平台以企业订阅变现，对个人免费。','explicit',['Omniverse Enterprise']),
 ('infotainment','Automotive infotainment','汽车信息娱乐','graphics',
  '汽车信息娱乐系统平台，年报明确列入 Graphics。',['e-graphics-segment'],
  '本轮材料未单列信息娱乐平台的收入或计费方式。','unknown',['Automotive infotainment platforms']),
]
for identity,name,zh,parent,description,refs,money,basis,products in specs:
    node(identity,name,zh,'offering_group',description,refs,money,basis,products)
    scope='e-compute-segment' if parent=='compute-networking' else 'e-graphics-segment'
    edge(identity,parent,'reported_under',[scope],'年报 Our Businesses 列示的报告归属。')

markets=[
 ('market-data-center','Data Center','数据中心市场','云、超大规模、本地及边缘数据中心的计算与网络需求。',['e-markets','e-data-center','e-customers']),
 ('market-gaming','Gaming','游戏市场','游戏桌面/笔记本、云游戏和游戏主机需求。',['e-markets','e-gaming-products']),
 ('market-professional','Professional Visualization','专业可视化市场','设计、制造和数字内容创作工作流。',['e-markets','e-professional','e-rtx']),
 ('market-automotive','Automotive','汽车市场','自动驾驶与车内平台需求；自动驾驶平台与信息娱乐平台分别列在不同报告分部。',['e-markets','e-automotive','e-compute-segment','e-graphics-segment']),
]
for identity,name,zh,description,refs in markets:
    node(identity,name,zh,'business',description,refs,role='market')
    edge('nvidia',identity,'supports',['e-markets'],'公司计算平台服务该终端市场；不是组织隶属或报告分部关系。')
for source,target,refs in [
 ('data-center-compute','market-data-center',['e-data-center','e-compute-products']),
 ('networking','market-data-center',['e-data-center','e-networking']),
 ('ai-software-cloud','market-data-center',['e-compute-products','e-paid-software']),
 ('geforce','market-gaming',['e-gaming-products']),
 ('rtx-vgpu','market-professional',['e-professional','e-rtx','e-paid-software']),
 ('omniverse','market-professional',['e-omniverse']),
 ('drive','market-automotive',['e-drive']),
 ('infotainment','market-automotive',['e-graphics-segment']),
 ('omniverse','market-automotive',['e-auto-simulation'])]:
    edge(source,target,'supports',refs,'产品或平台服务该终端市场；不代表该市场的完整收入映射。')

result=dict(schema_version='0.1',company_id='nvidia',document_id=DOCUMENT,
    summary='FY2025 的两个报告分部、主要产品组与四个终端市场。市场使用 supports 边；不把市场当作报告分部，不计算跨维度合计。',
    businesses=businesses,relationships=relationships,
    unknowns=[dict(id='u-product-pricing',question='DRIVE、Jetson 和汽车信息娱乐各自如何拆分硬件、软件及服务收费？',
        materiality='影响对具体业务收入模式的进一步理解。',related_business_ids=['drive','jetson','infotainment'],
        reason_unanswered='所读业务段落说明产品范围，没有独立收费明细；公司级收入政策不等于逐产品计费表。',
        evidence_ids=['e-compute-segment','e-graphics-segment','e-revenue-types']),
      dict(id='u-market-segment-reconciliation',question='四个市场如何与两个报告分部逐项勾稽？',
        materiality='防止不同披露维度重复相加或把 Automotive 全归到单一分部。',
        related_business_ids=['compute-networking','graphics',*[row[0] for row in markets]],
        reason_unanswered='本图只记录原文明确的产品归属与服务市场关系，不构造完整市场到分部的金额对照。',
        evidence_ids=['e-compute-segment','e-graphics-segment','e-markets'])],
    evidence=evidence,metadata=dict(extraction_method='codex_source_review',report_label='NVIDIA FY2025 Annual Report (Form 10-K portion)',
        period_end='2025-01-26',source_local_path=str((HERE/'source.html').relative_to(ROOT)),source_url=URL,
        source_sha256=source_sha,source_format='html_text_derived_from_official_pdf',
        original_source_path=str((HERE/'source.pdf').relative_to(ROOT)),original_source_sha256=original_sha,
        original_source_url=URL,discovery_source_url=IR,corresponding_sec_html_url=SEC,
        source_html_is_original=False,derived_text_path=str((HERE/'source.txt').relative_to(ROOT)),
        pdf_page_count=181,source_conversion='pdftotext -layout; HTML escaping and whitespace normalization only',
        evidence_locators=locators,node_labels=labels,node_roles=roles,review_status='candidate',financial_numbers_included=False,
        read_pdf_pages=[97,98,99,149,150],printed_page_labels=printed_pages,
        graph_scope='Company -> two reportable segments -> offering groups; four markets are a separate dimension connected with supports.',
        acquisition_limitation='SEC and investor HTML download returned HTTP 403; downloaded the official IR-linked FY2025 PDF instead.',
        source_block_definition='Nonempty blank-line-separated pdftotext -layout blocks in physical page order.'))
business_map_from_dict(result)
assert len(businesses)==16
assert all(b['evidence_ids'] for b in businesses) and all(r['evidence_ids'] for r in relationships)
assert len([b for b in businesses if b['kind']=='reportable_segment'])==2
assert all(r['kind']=='supports' for r in relationships if roles[r['target_id']]=='market')
(HERE/'business_map.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
evidence_parts=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>NVIDIA FY2025 原文证据</title>',style,
    '<h1>NVIDIA FY2025 原文证据</h1><p>候选解释与原文分开。原文来自官方完整 PDF；HTML 为文本派生，非官方 HTML。只规范空白，不改写证据。页索引从 0 起，打开 PDF 的页号从 1 起。</p>']
for e in evidence:
    loc=locators[e['id']]
    evidence_parts.append(f'<section id="{e["id"]}"><h2>{e["id"]}</h2><p>{esc(e["support"])}</p><p>PDF 实际第 {loc["pdf_page_number"]} 页（索引 {loc["pdf_page_index"]}），原印页 {loc["printed_page_label"]} · <a href="source.pdf#page={loc["pdf_page_number"]}">原始 PDF</a> · <a href="source.html#{loc["source_fragment"]}">派生文本完整页</a></p><blockquote lang="en">{esc(loc["full_source_text"])}</blockquote><p>原文块 {e["paragraph_ordinal"]} / 页面块 {loc["page_block_ordinal"]}<br>SHA256: <code>{e["text_hash"]}</code></p></section>')
evidence_parts.append('</html>')
(HERE/'evidence.html').write_text('\n'.join(evidence_parts))
(HERE/'source_acquisition.json').write_text(json.dumps(dict(source_url=URL,discovery_source_url=IR,
    original_source_path=result['metadata']['original_source_path'],original_source_sha256=original_sha,
    bytes=len(original),report_period_end='2025-01-26',source_pdf_pages=181,
    acquisition='download_official_ir_linked_pdf',sec_html_attempt=dict(url=SEC,http_status=403),
    derived_html_path=result['metadata']['source_local_path'],derived_html_sha256=source_sha),indent=2)+'\n')
(HERE/'validation.json').write_text(json.dumps(dict(status='passed',contract='BusinessMap schema 0.1',nodes=len(businesses),
    edges=len(relationships),evidence=len(evidence),reportable_segments=2,market_nodes=4,
    all_exact_quotes_found_in_pdf_extracted_page_text=True,all_nodes_and_edges_cited=True,
    market_edges_are_supports=True,pdf_pages_visually_checked=[97,98,99,149,150],
    semantic_review='Codex source review; not independent human review'),indent=2)+'\n')
print(json.dumps({'nodes':len(businesses),'edges':len(relationships),'evidence':len(evidence),'original_sha256':original_sha}))
