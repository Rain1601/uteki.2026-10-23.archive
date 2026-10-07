"""Reproduce the source locators and validate the manually reviewed candidate."""
from pathlib import Path
import hashlib
import html as escape_html
import json
import re
import sys
from lxml import html

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from uteki.domain.business_map import business_map_from_dict

URL = 'https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-20250630.htm'
DOCUMENT = 'msft-fy2025-10k'
raw = (HERE / 'source.html').read_bytes()
source_sha = hashlib.sha256(raw).hexdigest()
assert source_sha == '0edfaac937bf7042c8cf7901924ccb9cc291ccfab92f83dd0b689b7912089bf6'
tree = html.fromstring(raw)
normalize = lambda text: re.sub(r'\s+', ' ', text).strip()
elements = tree.xpath("//p | //div[contains(concat(' ', normalize-space(@class), ' '), ' item-list-element-wrapper ')]")
blocks = [(el, normalize(el.text_content())) for el in elements if normalize(el.text_content())]
business_start = next(n for n, (_, text) in enumerate(blocks) if text == 'ITEM 1. BUSINESS')
business_end = next(n for n, (_, text) in enumerate(blocks) if n > business_start and text == 'ITEM 1A. RISK FACTORS')
all_text = normalize(tree.text_content())
evidence, locators = [], {}


def ev(identity, start, section, support, quote=None):
    found = [(n, el, text) for n, (el, text) in enumerate(blocks, 1)
             if business_start <= n - 1 < business_end and text.lstrip('• ').startswith(start)]
    assert len(found) == 1, (identity, len(found))
    ordinal, element, text = found[0]
    quote = quote or text
    assert quote in text and quote in all_text
    digest = hashlib.sha256(text.encode()).hexdigest()
    evidence.append(dict(id=identity, document_id=DOCUMENT,
        section_path=['Part I', 'Item 1. Business', section], paragraph_ordinal=ordinal,
        text_hash=digest, source_url=URL, support=support))
    locators[identity] = dict(local_path=str((HERE / 'evidence.html').relative_to(ROOT)),
        fragment=identity, exact_quote=quote, source_dom_xpath=tree.getroottree().getpath(element),
        source_block_ordinal=ordinal, text_hash=digest, full_source_text=text,
        normalization='HTML textContent; whitespace collapsed and trimmed; no paraphrase')
    return identity


ev('e-overview', 'We offer an array of services, including cloud-based solutions', 'General',
   '公司提供云服务、支持及咨询服务，并经营在线广告。')
ev('e-products', 'Our products include operating systems, cross-device', 'General',
   '公司产品范围包括软件、游戏、PC、平板和游戏机等设备。')
ev('e-segments', 'We operate our business and report our financial performance using three segments:',
   'Operating Segments', 'FY2025 三个报告分部的完整名称与归属。')
ev('e-recast', 'In August 2024, we announced changes to the composition',
   'Operating Segments', 'FY2025 分部重组；Microsoft 365 商业组件归入生产力与业务流程。')
ev('e-365-commercial-scope', 'Microsoft 365 Commercial products and cloud services, including',
   'Productivity and Business Processes', '分部清单明确包含 Microsoft 365 商业产品与云服务。')
ev('e-365-commercial', 'Microsoft 365 Commercial is an AI-powered',
   'Productivity and Business Processes', '商业生产力产品范围、用户数和客单价驱动，以及从本地许可转向 Microsoft 365。')
ev('e-cloud-subscription', 'Microsoft Online Subscription Agreements are designed',
   'Licensing Options', 'Microsoft 云服务可通过在线协议按月或按年订阅。')
ev('e-365-consumer-scope', 'Microsoft 365 Consumer products and cloud services, including',
   'Productivity and Business Processes', '分部清单明确包含消费者订阅、本地 Office 与其他消费者服务。')
ev('e-365-consumer', 'Microsoft 365 Consumer is designed', 'Productivity and Business Processes',
   '消费者订阅、本地 Office，以及 Outlook.com/OneDrive 的订阅和广告收入。')
ev('e-linkedin-scope', 'LinkedIn, including Talent Solutions', 'Productivity and Business Processes',
   'LinkedIn 是该报告分部列示的产品组。')
ev('e-linkedin', 'LinkedIn connects the world', 'Productivity and Business Processes',
   '招聘、营销、付费会员和销售解决方案；订阅需求及赞助内容驱动收入。')
ev('e-dynamics-scope', 'Dynamics products and cloud services, including Dynamics 365',
   'Productivity and Business Processes', 'Dynamics 是该报告分部列示的产品组。')
ev('e-dynamics', 'Dynamics provides cloud-based and on-premises', 'Productivity and Business Processes',
   'ERP/CRM 等业务应用；许可用户、应用使用量与客单价，以及向 Dynamics 365 转移。')
ev('e-server-cloud-scope', 'Server products and cloud services, including Azure', 'Intelligent Cloud',
   '该分部包含 Azure/其他云服务与服务器产品；GitHub/Nuance 云服务归入其他云服务。')
ev('e-azure', 'Azure is a comprehensive set of cloud services', 'Intelligent Cloud',
   'Azure 的云能力及 IaaS/PaaS 按使用量收费服务驱动收入。')
ev('e-server', 'Our server products are designed', 'Intelligent Cloud',
   '服务器和开发软件通过批量许可、OEM 与零售销售；CAL 随相关服务器产品列报。')
ev('e-services-scope', 'Enterprise and partner services, including Enterprise Support Services, Industry Solutions, Nuance professional services, Microsoft Partner Network, and Learning Experience.', 'Intelligent Cloud',
   'Enterprise and partner services 是 Intelligent Cloud 分部列示的服务组。')
ev('e-services', 'Enterprise and partner services, including Enterprise Support Services, Industry Solutions, Nuance professional services, Microsoft Partner Network, and Learning Experience, assist',
   'Intelligent Cloud', '支持、行业解决方案、专业服务以及培训认证。')
ev('e-enterprise-contracts', 'Many organizations that license our products and services transact directly',
   'Distribution, Sales, and Marketing', '企业通过 Enterprise Agreements 和 Enterprise Services 合同直接交易。')
ev('e-windows-scope', 'Windows and Devices, including Windows OEM licensing', 'More Personal Computing',
   'Windows OEM 许可和 Surface/PC 配件归入 More Personal Computing。')
ev('e-windows', 'The Windows operating system is designed', 'More Personal Computing',
   'OEM 购买 Windows 许可并预装在其销售的设备上。')
ev('e-devices', 'We design and sell devices, such as Surface', 'More Personal Computing',
   'Microsoft 销售 Surface 和 PC 配件。')
ev('e-gaming-scope', 'Gaming, including Xbox hardware and Xbox content and services', 'More Personal Computing',
   'Gaming 包含 Xbox 硬件、内容、订阅、云游戏和广告。')
ev('e-gaming', 'Xbox enables people to connect and share online gaming experiences', 'More Personal Computing',
   'Xbox 收入主要受内容销售、订阅和广告影响。')
ev('e-search-scope', 'Search and news advertising, comprising Bing', 'More Personal Computing',
   '搜索和新闻广告产品组归属该报告分部。')
ev('e-search', 'Our Search and news advertising business is designed', 'More Personal Computing',
   'Bing/Copilot、Edge 等吸引用户，通过搜索、原生和展示广告变现。')

businesses, relationships, labels = [], [], {}


def node(identity, name, zh, kind, description, refs, money=None, products=(), customers=()):
    businesses.append(dict(id=identity, name=name, kind=kind, description=description,
        products_services=list(products), customers=list(customers), importance_signals=[],
        monetization=[] if money is None else [dict(description=money, basis='explicit', evidence_ids=refs)],
        evidence_ids=refs, review_status='candidate'))
    labels[identity] = dict(en=name, zh=zh)


def edge(child, parent, refs, kind='reported_under'):
    relationships.append(dict(source_id=child, target_id=parent, kind=kind,
        description='FY2025 年报列示的报告归属。', evidence_ids=refs, review_status='candidate'))


node('microsoft', 'Microsoft', '微软', 'company', '提供软件、云服务、设备和在线广告；按 FY2025 三个报告分部组织本图。',
     ['e-overview', 'e-products', 'e-segments'], '通过软件及服务、设备和广告业务取得收入。')
node('productivity', 'Productivity and Business Processes', '生产力与业务流程', 'reportable_segment',
     '生产力、协作和企业业务应用；采用 FY2025 调整后的分部口径。',
     ['e-segments', 'e-recast', 'e-365-commercial-scope', 'e-dynamics-scope'])
node('intelligent-cloud', 'Intelligent Cloud', '智能云', 'reportable_segment',
     '服务器产品、Azure 与其他云服务，以及企业与合作伙伴服务。',
     ['e-segments', 'e-server-cloud-scope', 'e-services-scope'])
node('personal-computing', 'More Personal Computing', '更多个人计算', 'reportable_segment',
     'Windows 与设备、游戏，以及搜索和新闻广告。',
     ['e-segments', 'e-windows-scope', 'e-gaming-scope', 'e-search-scope'])
for identity in ('productivity', 'intelligent-cloud', 'personal-computing'):
    edge(identity, 'microsoft', ['e-segments'])

specs = [
 ('m365-commercial', 'Microsoft 365 Commercial', 'Microsoft 365 商业', 'productivity',
  '组织使用的 Office、Windows、Copilot、安全和管理工具。', ['e-365-commercial', 'e-365-commercial-scope', 'e-cloud-subscription'],
  '商业云订阅与本地软件许可；收入受用户规模、每用户收入和向云订阅转移影响。', ['Office', 'Windows Commercial', 'Microsoft 365 Copilot', 'Enterprise Mobility + Security']),
 ('m365-consumer', 'Microsoft 365 Consumer', 'Microsoft 365 消费者', 'productivity',
  '个人生产力产品及 Outlook.com、OneDrive 等消费者服务。', ['e-365-consumer', 'e-365-consumer-scope'],
  'Microsoft 365 消费者订阅、本地 Office；通信和存储服务还由订阅及广告驱动。', ['Microsoft 365 Consumer', 'Office', 'Outlook.com', 'OneDrive']),
 ('linkedin', 'LinkedIn', 'LinkedIn', 'productivity',
  '面向专业人士和企业的招聘、营销、会员与销售平台。', ['e-linkedin', 'e-linkedin-scope'],
  'Talent/Sales/Premium 订阅与 Marketing Solutions 赞助内容。', ['Talent Solutions', 'Marketing Solutions', 'Premium Subscriptions', 'Sales Solutions']),
 ('dynamics', 'Dynamics', 'Dynamics 业务应用', 'productivity',
  'ERP、CRM、供应链及低代码应用平台。', ['e-dynamics', 'e-dynamics-scope'],
  '云端及本地应用许可；收入取决于许可用户、应用使用量及每用户收入。', ['Dynamics 365', 'Power Apps', 'Power Automate']),
 ('azure-cloud', 'Azure and other cloud services', 'Azure 与其他云服务', 'intelligent-cloud',
  '云计算、网络、存储与 AI；包含 GitHub 和 Nuance Healthcare 的云服务。', ['e-azure', 'e-server-cloud-scope'],
  'Azure 主要由 IaaS/PaaS 按使用量收费服务驱动；未将这一方式泛化到所有其他云服务。', ['Azure', 'GitHub cloud services', 'Nuance Healthcare cloud services']),
 ('server-products', 'Server products', '服务器产品', 'intelligent-cloud',
  '服务器操作系统、数据库、开发及管理软件。', ['e-server', 'e-server-cloud-scope'],
  '批量许可、OEM 许可及零售软件；CAL 收入归入对应服务器产品。', ['SQL Server', 'Windows Server', 'Visual Studio', 'System Center', 'CALs']),
 ('enterprise-services', 'Enterprise and partner services', '企业与合作伙伴服务', 'intelligent-cloud',
  '帮助客户开发、部署和管理解决方案，提供支持、专业服务与培训认证。', ['e-services', 'e-services-scope', 'e-enterprise-contracts'],
  '企业服务合同与相关服务；本次原文未拆解各项服务的具体计费单位。', ['Enterprise Support Services', 'Industry Solutions', 'Nuance professional services', 'Learning Experience']),
 ('windows-devices', 'Windows and Devices', 'Windows 与设备', 'personal-computing',
  'Windows OEM 许可，以及 Surface 和 PC 配件。', ['e-windows-scope', 'e-windows', 'e-devices'],
  '向 OEM 销售预装 Windows 许可，并销售 Surface 与 PC 配件。', ['Windows OEM', 'Surface', 'PC accessories']),
 ('gaming', 'Gaming', '游戏', 'personal-computing',
  'Xbox 硬件、第一方与第三方游戏内容、订阅及云游戏。', ['e-gaming-scope', 'e-gaming'],
  '硬件、游戏内容销售、订阅及广告。', ['Xbox', 'Xbox Game Pass', 'Xbox Cloud Gaming']),
 ('search-news', 'Search and news advertising', '搜索与新闻广告', 'personal-computing',
  '利用 Bing/Copilot、Edge、Microsoft News 和合作伙伴触达用户。', ['e-search-scope', 'e-search'],
  '搜索、原生及展示广告，以及合作伙伴搜索服务变现。', ['Bing', 'Copilot', 'Microsoft Edge', 'Microsoft News']),
]
for identity, name, zh, parent, description, refs, money, products in specs:
    node(identity, name, zh, 'offering_group', description, refs, money, products)
    edge(identity, parent, [ref for ref in refs if ref.endswith('-scope')])

result = dict(schema_version='0.1', company_id='microsoft', document_id=DOCUMENT,
    summary='FY2025 三个报告分部及其主要产品与服务组；所有内容为按官方原文人工阅读的候选，不含估算金额。',
    businesses=businesses, relationships=relationships,
    unknowns=[dict(id='u-billing-detail', question='其他云服务和企业服务的具体计费单位如何分别构成？',
        materiality='影响对各业务收入驱动的进一步理解。', related_business_ids=['azure-cloud', 'enterprise-services'],
        reason_unanswered='本轮仅覆盖业务说明；所读段落没有逐产品完整收费表。', evidence_ids=['e-server-cloud-scope', 'e-services'])],
    evidence=evidence, metadata=dict(extraction_method='codex_source_review',
        report_label='Microsoft FY2025 Form 10-K', period_end='2025-06-30', filed_at='2025-07-30',
        source_local_path=str((HERE / 'source.html').relative_to(ROOT)), source_url=URL, source_sha256=source_sha,
        original_source_path=str((HERE / 'source.html').relative_to(ROOT)), original_source_sha256=source_sha,
        source_format='original_sec_html', evidence_locators=locators, node_labels=labels,
        source_reused_from='data/company_workspace/extraction_ab_v1/corpus/msft/originals/msft-2025-10k.html',
        review_status='candidate', financial_numbers_included=False,
        graph_scope='Company -> reportable segment -> offering group; FY2025 segment composition.',
        source_block_definition='Nonempty HTML p and div.item-list-element-wrapper nodes in document order; whitespace-normalized text.'))
business_map_from_dict(result)
assert len(businesses) == 14 and len(relationships) == 13
assert all(b['evidence_ids'] for b in businesses)
assert all(r['evidence_ids'] for r in relationships)
for r in relationships:
    assert r['source_id'] != r['target_id']
(HERE / 'business_map.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
esc = escape_html.escape
parts = ['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Microsoft FY2025 原文证据</title>',
         '<style>body{max-width:900px;margin:40px auto;font:17px/1.65 sans-serif;padding:0 20px}section{padding:20px 0;border-top:1px solid #ddd}code{overflow-wrap:anywhere}blockquote{margin:16px 0}</style>',
         '<h1>Microsoft FY2025 原文证据</h1><p>原始 SEC HTML 的精确文本摘录；只折叠空白。候选解释与原文分开。<a href="source.html">打开完整原文</a></p>']
for e in evidence:
    loc = locators[e['id']]
    parts.append(f'<section id="{e["id"]}"><h2>{esc(e["id"])} · 原文块 {e["paragraph_ordinal"]}</h2><p>{esc(e["support"])}</p><blockquote lang="en">{esc(loc["full_source_text"])}</blockquote><p>XPath: <code>{esc(loc["source_dom_xpath"])}</code><br>SHA256: <code>{e["text_hash"]}</code></p></section>')
parts.append('</html>')
(HERE / 'evidence.html').write_text('\n'.join(parts))
(HERE / 'source_acquisition.json').write_text(json.dumps(dict(source_url=URL, source_sha256=source_sha,
    bytes=len(raw), acquisition='reuse_existing_frozen_official_sec_html', report_period_end='2025-06-30',
    reused_from=result['metadata']['source_reused_from']), ensure_ascii=False, indent=2)+'\n')
(HERE / 'validation.json').write_text(json.dumps(dict(status='passed', contract='BusinessMap schema 0.1',
    nodes=len(businesses), edges=len(relationships), evidence=len(evidence), source_sha256_verified=True,
    all_exact_quotes_found_in_source=True, all_nodes_and_edges_cited=True,
    semantic_review='Codex source review; not independent human review'), ensure_ascii=False, indent=2)+'\n')
print(json.dumps({'nodes':len(businesses), 'edges':len(relationships), 'evidence':len(evidence), 'source_sha256':source_sha}))
