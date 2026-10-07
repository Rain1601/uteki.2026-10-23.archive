"""Evaluation-only inventory, written before any model response. Never sent to extraction."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
EXP=HERE.parent
raw=(EXP/'input/source_packet.json').read_bytes(); packet=json.loads(raw)
by_ord={b['ordinal']:b for b in packet['blocks']}
sha=lambda b:hashlib.sha256(b).hexdigest()

def quote(ordinal,text):
    block=by_ord[ordinal]
    assert text in block['text'], (ordinal,text)
    return dict(block_id=block['id'],ordinal=ordinal,quote=text,quote_sha256=sha(text.encode()),source_dom_path=block['source_dom_path'])

def item(identity, label, excerpts, obligations, qualifiers, disposition='business_fact'):
    return dict(id=identity,label=label,disposition=disposition,source_excerpts=[quote(o,t) for o,t in excerpts],
                review_obligations=obligations,qualifiers_and_non_inferences=qualifiers)

entries=[
 item('IC-01','报告分部身份与范围',[(86,'We operate our business and report our financial performance using three segments: Productivity and Business Processes, Intelligent Cloud, and More Personal Computing.'),(118,'Our Intelligent Cloud segment consists of our public, private, and hybrid server products and cloud services that power modern business and developers.')],
      ['辨认 Intelligent Cloud 的 reportable segment 身份；公司和分部层级分开。','主体与开发者 / 现代业务服务范围有原文依据。'],
      ['本例仅提取 Intelligent Cloud；另外两个分部只作范围元数据，不扩展它们的业务。']),
 item('IC-02','当前报告口径',[(87,'Beginning in fiscal year 2025, the information that our chief operating decision maker is regularly provided and reviews for purposes of allocating resources and assessing performance reflects these segment changes.')],
      ['按这份 FY2025 报告的当前口径阅读分部，保留期间。'],
      ['Microsoft 365 变化属于上下文；不据此给 Intelligent Cloud 加入 Microsoft 365。'],'scope_metadata'),
 item('IC-03','两类主要业务组',[(118,'This segment primarily comprises:'),(120,'Server products and cloud services, including Azure and other cloud services'),(122,'Enterprise and partner services, including Enterprise Support Services, Industry Solutions, Nuance professional services, Microsoft Partner Network, and Learning Experience.')],
      ['保留 Server products and cloud services 与 Enterprise and partner services 的不同身份 / 报告归属。','分部到业务组的方向和依据可追溯；若边类型带会计含义，必须解释选择。'],
      ['primarily 不是所有业务穷尽承诺。','本清单不要求固定节点数，组可以有具名节点或明确且可查询的层级表达。']),
 item('IC-04','Cloud 组与本地 Server products 的显式区别',[(120,'Azure and other cloud services, comprising cloud and AI consumption-based services, GitHub cloud services, Nuance Healthcare cloud services, virtual desktop offerings, and other cloud services; and Server products, comprising SQL Server, Windows Server, Visual Studio, System Center, related Client Access Licenses (“CALs”), and other on-premises offerings.')],
      ['云服务列举和本地 Server products 列举不能合并成单一 Azure 子清单。','重要具名对象、虚拟桌面和 other 限定至少在节点详情或明确遗漏中可核对。','SQL Server / Windows Server / Visual Studio / System Center / CALs 的原文位置保留。'],
      ['GitHub cloud services 与 GitHub 整体身份范围不同。','Nuance Healthcare cloud services 与 Nuance professional services 不混同。','不要求每个泛称或 other 成为独立节点。']),
 item('IC-05','Azure 的作用、客户和交付范围',[(127,'Azure is a comprehensive set of cloud services that offer developers, IT professionals, and enterprises freedom to build, deploy, and manage applications on any platform or device.'),(127,'Customers can use Azure through our global network of datacenters for computing, networking, storage, mobile and web application services, AI, Internet of Things, cognitive services, and machine learning.')],
      ['Azure 保留具名独立业务入口，开发者 / IT 专业人员 / 企业客户与服务作用逐项绑定。','各能力可保留在详情；不得将一串功能自动当作互斥子公司或报告分部。'],
      ['原文支持应用可运行平台 / 设备的广度，不证明每个产品收费。']),
 item('IC-06','Azure 收入驱动的限定',[(127,'Azure revenue is mainly affected by infrastructure-as-a-service and platform-as-a-service consumption-based services.')],
      ['如表达收费 / 收入驱动，保留 IaaS / PaaS 用量型服务与 mainly 限定。'],
      ['不是 Azure 所有产品均按用量收费；不能生成收入金额、占比或单项财务披露。']),
 item('IC-07','Azure AI 与 Foundry',[(128,'We offer supercomputing power for AI at scale to run large workloads, complemented by our rapidly expanding portfolio of AI cloud services (including the latest models) and hardware, which includes custom-built silicon and strong partnerships with chip manufacturers.'),(128,'Azure AI Foundry is a unified platform for developers to design, customize, and manage AI applications and agents.')],
      ['Azure AI Foundry 是具名平台入口，说明开发者和应用 / agent 设计定制管理能力。','AI 计算、服务与硬件可保留为能力 / 详情，关系依据分级可检查。'],
      ['段落语境可支持分类推断，但不能把每一种 Azure AI / Foundry 归属关系都宣称逐句明示。','无芯片厂商名，不补 NVIDIA / OpenAI 等外部实体。']),
 item('IC-08','Server products 的能力与用户',[(129,'Our server products are designed to make IT professionals, developers, and their systems more productive and efficient.'),(129,'Server software is integrated server infrastructure and middleware designed to support software applications built on the Windows Server operating system.'),(129,'We also license standalone and software development lifecycle tools for software architects, developers, testers, and project managers.')],
      ['本地 Server products 能力、Windows Server 支持语义、工具许可及相应用户有原文依据。'],
      ['支持 Windows Server 应用不是所有列举产品都属于 Windows Server。','不会据背景泛称另造未经披露的产品 / 法律实体。']),
 item('IC-09','Server 收入驱动与 CALs 权利',[(129,'Server products revenue is mainly affected by purchases through volume licensing programs, licenses sold to OEMs, and retail packaged products.'),(129,'CALs provide access rights to certain server products, including SQL Server and Windows Server, and revenue is reported along with the associated server product.')],
      ['渠道 / 许可表述保留主体和 mainly。','CALs 与 SQL Server / Windows Server 的权利关系若建边，方向、类型及证据符合这段文字。'],
      ['access rights 不等于产品包含或支持关系；契约无对应边类型时留说明 / 缺口，不强塞。','没有合同价格或单独 CALs 收入金额。']),
 item('IC-10','GitHub 与 Nuance Healthcare 的双形态',[(130,'GitHub and Nuance Healthcare include both cloud and on-premises offerings.'),(130,'GitHub provides a collaboration platform for developers to manage code and incorporate AI and agent-based tools across the software development lifecycle.'),(130,'Nuance Healthcare provides AI solutions to the healthcare industry.')],
      ['两个具名业务的身份、功能 / 客户保留且相互区分。','cloud 和 on-premises 同时存在的限定不能因 120 的 cloud 清单丢失。'],
      ['不把全部 GitHub / Nuance Healthcare 确定归属为 cloud-only。','需要区分实体与云产品形态；一个共享实体可连接多个合理视图，不能复制造成两个不同公司。']),
 item('IC-11','Enterprise and partner services 的组成',[(132,'Enterprise and partner services, including Enterprise Support Services, Industry Solutions, Nuance professional services, Microsoft Partner Network, and Learning Experience,')],
      ['五项具名服务 / 计划至少可在组详情或明确coverage缺口中检索。'],
      ['列举计划、服务、学习能力不等于五个报告分部；无需固定五个节点。','Nuance professional services 不能改名成 Nuance Healthcare cloud services。']),
 item('IC-12','服务的作用和培训对象',[(132,'assist customers in developing, deploying, and managing Microsoft server solutions, Microsoft desktop solutions, and Nuance conversational AI and ambient intelligent solutions, along with providing training and certification to developers and IT professionals on various Microsoft products.')],
      ['部署 / 管理服务与培训认证两种作用保留，客户 / 开发者 / IT 人员绑定原文。'],
      ['全文未说各个成员独立承担全部这些作用，不能把组级功能不加限定复制给每个成员。','服务支持 Microsoft desktop solutions 不把其他分部桌面业务并入 Intelligent Cloud。']),
 item('IC-13','竞争段仍包含 Azure Security 业务事实',[(134,'Our Azure Security offerings include our cloud security solution and security information and event management solution, which compete with providers in the cybersecurity and cloud security space.')],
      ['Azure Security 及云安全 / SIEM 方案不可因标题 Competition 而被静默丢掉；可做具名入口或清楚的详情。'],
      ['Azure Security 与 broader identity/security portfolio 的包含关系不能凭相邻语句无限扩展。','竞争类别不是我方产品成员。']),
 item('IC-14','竞争段关于 Azure / AI 的边界',[(134,'Azure faces diverse competition from cloud service providers and open source offerings.'),(134,'Azure’s competitive advantage includes enabling a hybrid cloud, allowing deployment of existing datacenters with our public cloud into a single, cohesive infrastructure, and the ability to run at a scale that meets the needs of businesses of all sizes and complexities.'),(134,'Our AI offerings compete with AI products from hyperscalers, as well as products from other emerging competitors and other open source offerings, many of which are also current or potential partners.')],
      ['混合云能力可在相关业务说明保留，竞争和潜在合作须分别标注主体与限定。'],
      ['没有具名对手，不根据常识填 AWS / Google。','competitive advantage、We believe 是公司自述，不能呈现独立验证的优势。','potential partners 不是已建立合作关系。'],'context_with_business_facts'),
 item('IC-15','其他竞争背景与不可成立的归属',[(135,'Vertically integrated computer manufacturers offer their own versions of the Unix operating system preinstalled on server hardware and nearly all computer manufacturers offer server hardware for the Linux operating system.'),(136,'We compete to provide enterprise-wide computing and point solutions with numerous commercial software vendors'),(140,'Our database, business intelligence, and data warehousing solutions offerings compete with products from providers in the data and analytics industry.'),(140,'Our system management solutions compete with server management and server virtualization platform providers.'),(140,'Our products for software developers compete against offerings from major technology providers, as well as open source alternatives.'),(142,'Our Enterprise and partner services business competes with a wide range of companies that provide strategy and business planning, application development, and infrastructure services, including multinational consulting firms and small niche businesses focused on specific technologies.')],
      ['竞争背景读过并在范围清单说明处理；如保留能力描述，其我方主体需与外部厂商分开。'],
      ['Unix / Linux 在该句为外部厂商描述，不能作为 Microsoft 产品归属节点。','外部咨询商 / 厂商类别不是我方旗下业务。','本任务业务图可不建 competitor 边，但必须说明当前契约/任务未呈现此关系，不称源文无竞争信息。'],'competition_context'),
 item('IC-16','公司自述优势与未披露内容',[(141,'We believe our server products provide customers with advantages in performance, total costs of ownership, and productivity by delivering superior applications, development tools, compatibility with a broad base of hardware and software applications, security, and manageability.')],
      ['若展示这一段，保留公司自述 / We believe 语气。'],
      ['不将优势当独立事实评价或质量打分。','本节没有收入金额、市场份额、成本或每个产品的定价；这些均不适用此次业务图抽取。'],'issuer_claim')
]
layout={119:'isolated_bullet',121:'isolated_bullet',123:'printed_page_number',124:'running_part_header',125:'running_item_header',137:'printed_page_number',138:'running_part_header',139:'running_item_header'}
headings={117,126,131,133}
block_inventory=[]
for b in packet['blocks']:
 ordinal=b['ordinal']; refs=[i['id'] for i in entries if any(q['ordinal']==ordinal for q in i['source_excerpts'])]
 role=('scope_metadata' if b['input_role']=='scope_metadata' else 'layout_retained' if ordinal in layout else 'section_heading' if ordinal in headings else 'source_content')
 note=(layout[ordinal] if ordinal in layout else 'source bound heading, not independent operating entity' if ordinal in headings else
       'issuer identity or period metadata' if ordinal in (6,8) else 'see evaluation items')
 block_inventory.append(dict(block_id=b['id'],ordinal=ordinal,disposition=role,coverage_item_ids=refs,note=note))
assert all(i['coverage_item_ids'] or i['disposition']!='source_content' for i in block_inventory)
assert not list(EXP.glob('run-*/response.txt')) and not list(EXP.glob('run-*/business_map.json')), 'coverage_must_precede_response'
out=dict(schema_version='business-subsection-coverage-inventory-v1',purpose='evaluation_only_do_not_send_to_extraction',
 frozen_before_any_response_in_this_experiment=True, company_id=packet['company_id'],document_id=packet['document_id'],period_end=packet['period_end'],
 binding=dict(source_packet_sha256=sha(raw),source_sha256=packet['source_sha256']),
 method='Codex source-first inventory of every selected content block. No prior generated map or model response used. This is a review checklist, not a fixed expected node count or a sole canonical taxonomy.',
 inclusion_policy='Every source-supported material named object and relationship qualifier must be represented at a defensible level or explicitly identified as omitted; long subsidiary lists may be details. Schema validity, excerpt validity, semantic entailment and coverage are separate checks.',
 entries=entries,block_inventory=block_inventory,
 grading=dict(no_fixed_node_count=True,node_or_detail_allowed=True,absence_means='not recorded, not proof of independence or exclusion',
     relationship_basis=['explicit source typed relationship','derived with stated source premises and limits','unknown recorded as a gap, not established edge'],
     outcome_categories=['covered','partially_covered','missing','incorrect','not_applicable'],semantic_acceptance_not_implied_by_parser=True),
 limitations=['Single source and subsection; not full-company or full-report coverage.','Scope metadata does not enlarge extraction target.','Inventory author is Codex and not an independent anonymous judge.','Company was discussed previously; this is not a blind company holdout.'],model_api_calls=0)
output=HERE/'source-coverage-inventory.json'; encoded=(json.dumps(out,ensure_ascii=False,indent=2)+'\n').encode()
if output.exists():assert output.read_bytes()==encoded,'frozen_inventory_changed'
else:output.write_bytes(encoded)
print(json.dumps({'inventory_sha256':sha(encoded),'entries':len(entries),'block_inventory':len(block_inventory),'quote_checks':'all exact substrings passed'}))
