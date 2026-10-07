"""Create reviewer-only, pre-run checks from explicitly frozen source packets.

Never import this file or its output into extraction/model request construction.
No candidate output is read, no model or network is called.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
OUTPUT = Path(__file__).with_name('acceptance-v1.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def case(packet_path, checks, scope_note):
    path = ROOT / packet_path
    packet = json.loads(path.read_text())
    blocks = {b['id']: b for b in packet['blocks']}
    items = []
    for key, title, acceptance, anchors in checks:
        refs = []
        for block_id, quote in anchors:
            assert quote in blocks[block_id]['text'], (key, block_id, quote)
            refs.append(dict(block_id=block_id, quote=quote,
                source_block_text_sha256=hashlib.sha256(blocks[block_id]['text'].encode()).hexdigest()))
        items.append(dict(id=key, title=title, acceptance=acceptance,
            source_anchors=refs, verdict='not_evaluated', candidate_read=False))
    return dict(company_id=packet['company_id'], document_id=packet['document_id'],
        period_end=packet['period_end'], source_sha256=packet['source_sha256'],
        source_url=packet['source_url'], packet_path=packet_path,
        packet_file_sha256=sha(path), selected_block_count=len(blocks), scope_note=scope_note,
        checks=items)


MS = [
    ('MS-01', '报告分部与主要构成不遗漏',
     '保留三个报告分部的独立身份。PBP 下 Commercial、Consumer、LinkedIn、Dynamics；IC 下 Server products and cloud services、Enterprise and partner services；MPC 下 Windows and Devices、Gaming、Search and news advertising 均可定位，关系由所在段落支持。允许不同合理由来命名，不规定最终节点数量。', [
        ('block-000086-935d6090', 'three segments: Productivity and Business Processes, Intelligent Cloud, and More Personal Computing.'),
        ('block-000091-d993f813', 'This segment primarily comprises:'),
        ('block-000093-7018adaa', 'Microsoft 365 Commercial products and cloud services'),
        ('block-000095-61bd513b', 'Microsoft 365 Consumer products and cloud services'),
        ('block-000097-13124fb7', 'LinkedIn, including'),
        ('block-000099-da3d48eb', 'Dynamics products and cloud services'),
        ('block-000118-5e917062', 'This segment primarily comprises:'),
        ('block-000120-c34f7245', 'Server products and cloud services'),
        ('block-000122-c07a987e', 'Enterprise and partner services'),
        ('block-000144-6e0ae0c4', 'This segment primarily comprises:'),
        ('block-000146-c641cfcd', 'Windows and Devices'),
        ('block-000148-2f215a60', 'Gaming, including Xbox hardware and Xbox content and services'),
        ('block-000150-9577a591', 'Search and news advertising')]),
    ('MS-02', 'Microsoft 365 整体与云/本地口径分清',
     'Commercial/Consumer 业务组、云收入或产品子集、平台整体不因名字接近而合并。保留 on-premises 限定；若给平台整体与 cloud-only 子集建立包含边，必须解释完整原文支持，不能把列示语境提升为无条件整体归属。', [
        ('block-000093-7018adaa', 'the cloud portion of Windows Commercial, the per-user portion of Power BI'),
        ('block-000093-7018adaa', 'Microsoft 365 Commercial products, comprising Windows Commercial on-premises and Office licensed on-premises.'),
        ('block-000101-67803298', 'Microsoft 365 Commercial is an AI-powered business and productivity solutions platform that brings together Office, Windows, Microsoft 365 Copilot, and Enterprise Mobility + Security'),
        ('block-000103-a597bcd9', 'Microsoft 365 Consumer cloud revenue and Office Consumer products revenue')]),
    ('MS-03', 'Azure 与 AI 产品能够定位且不虚构层级',
     'Azure 的云服务定义、Azure AI offerings、Azure AI Foundry 的应用和代理开发平台说明均可定位。用独立身份或带精确出处的宿主属性表达，选择须解释；不能将原文名称改成 Azure AI Factory，也不能给原文不明确的组织层级加 explicit 边。通用 compute/network/storage 不因列举自动成为业务节点。', [
        ('block-000127-93a9159b', 'Azure is a comprehensive set of cloud services'),
        ('block-000127-93a9159b', 'computing, networking, storage, mobile and web application services, AI, Internet of Things, cognitive services, and machine learning.'),
        ('block-000128-edef168d', 'Azure AI offerings provide a competitive advantage'),
        ('block-000128-edef168d', 'Azure AI Foundry is a unified platform for developers to design, customize, and manage AI applications and agents.')]),
    ('MS-04', 'GitHub、Nuance 的整体不被云子集替代',
     '两者 cloud services 的分部列示和两者整体同时有 cloud/on-premises offerings 的说明均保留。整体定义可独立定位，不以 cloud 节点假装完成整体覆盖；整体到报告组的直接归属若材料不足，标明推断或具体未知，不为连通而造边。', [
        ('block-000120-c34f7245', 'GitHub cloud services, Nuance Healthcare cloud services'),
        ('block-000130-8d7ff1f7', 'GitHub and Nuance Healthcare include both cloud and on-premises offerings.'),
        ('block-000130-8d7ff1f7', 'GitHub provides a collaboration platform for developers to manage code and incorporate AI and agent-based tools across the software development lifecycle.'),
        ('block-000130-8d7ff1f7', 'Nuance Healthcare provides AI solutions to the healthcare industry.')]),
    ('MS-05', '清单细项折叠后仍有真实属性与引用',
     '抽查 Teams、SQL Server、CALs、Surface/PC accessories、Xbox Game Pass 等细项，均能通过节点或非空宿主属性找到。属性应有 item_index 与专属 claim_evidence。可保留合理独立节点，不设少于多少节点的硬门槛；不得只是把所有细项删除或改写进摘要。', [
        ('block-000093-7018adaa', 'Exchange, SharePoint, Microsoft Teams'),
        ('block-000120-c34f7245', 'SQL Server, Windows Server, Visual Studio, System Center, related Client Access Licenses'),
        ('block-000129-264fa06b', 'CALs provide access rights to certain server products, including SQL Server and Windows Server'),
        ('block-000146-c641cfcd', 'Devices, comprising Surface and PC accessories.'),
        ('block-000176-a1bfeea9', 'Xbox Game Pass, a subscription service and gaming community')]),
    ('MS-06', '产品、客户、收费来自本公司的具体披露',
     '抽查 Azure 的开发者/IT professionals/enterprises 与 consumption-based IaaS/PaaS、LinkedIn 的 enterprises/professionals 与订阅、Dynamics 的客户范围、Xbox 内容/订阅/广告。应在正确宿主上出现有据属性或具体未处理缺口。收入驱动因素不能伪装成独立收费方式；不得给每个子产品复制整个分部的客户。', [
        ('block-000127-93a9159b', 'developers, IT professionals, and enterprises'),
        ('block-000127-93a9159b', 'Azure revenue is mainly affected by infrastructure-as-a-service and platform-as-a-service consumption-based services.'),
        ('block-000108-ec73690d', 'demand from enterprises and professionals for subscriptions to Talent Solutions, Sales Solutions, and Premium Subscriptions offerings'),
        ('block-000110-99cc951e', 'for small and medium businesses, large organizations, and divisions of global enterprises.'),
        ('block-000178-51f06755', 'Xbox revenue is mainly affected by subscriptions and sales of first- and third-party content, as well as advertising.')]),
    ('MS-07', '竞争段落中的自有产品保留、竞对不冒充自有业务',
     'Microsoft Defender for Endpoint、Azure Security offerings 等在 Competition 段落出现，仍须由节点、属性或明确缺口覆盖。没有归属证据就保留未知。rival categories、合作伙伴与客户不自动变成发行人的 business 节点。', [
        ('block-000113-bc876fa1', 'Microsoft Defender for Endpoint competes with endpoint security solution providers.'),
        ('block-000134-9ca2b5c6', 'Our Azure Security offerings include our cloud security solution and security information and event management solution'),
        ('block-000183-dcc9edaa', 'Many of these manufacturers are also current or potential partners and customers, including our Windows OEMs.')]),
    ('MS-08', '精确引用足以证明整条声明、历史与不确定性保留',
     '逐声明核对主语、作用范围与限定词，不能用字符串出现当作语义证明。若提 FY2025 分部调整，引用包含相应时间。每个指定输入块有处置；未决事项、inferred 边及 unsupported 项不能被程序格式 pass 覆盖；不宣称整份报告已验收。', [
        ('block-000087-44aabdcd', 'Beginning in fiscal year 2025'),
        ('block-000087-44aabdcd', 'bringing the commercial components of Microsoft 365 together in the Productivity and Business Processes segment.'),
        ('block-000088-8339c382', 'Note 18 – Segment Information and Geographic Data')]),
]

GOOGLE = [
    ('GO-01', 'Alphabet / Google / 报告分部的身份区分',
     '保留 Alphabet、Google 及两个报告分部的层级；Other Bets 是非 Google 业务集合，不能只因与两分部并列列示就强称相同会计身份。Alphabet-level AI activities 的支持关系与报告归属区分，不发明第三种业务收入。', [
        ('block-000065-ab2556c8', 'Alphabet is a collection of businesses — the largest of which is Google.'),
        ('block-000065-ab2556c8', 'We report Google in two segments, Google Services and Google Cloud, and all non-Google businesses collectively as Other Bets.'),
        ('block-000065-ab2556c8', 'which is reported in Alphabet-level activities.')]),
    ('GO-02', 'Services 具名产品不遗漏，也不全部强制变节点',
     'Search、YouTube、Android、Chrome、Gmail、Drive、Gemini、Maps、Photos、Play 和设备等所选列举均可按节点或正确宿主属性定位。清单产品不强制每个建 business；定义清晰、有跨视角关系的产品按语义保留身份，不能仅按广告/订阅金额行替代实际业务。', [
        ('block-000086-7bd7f443', "Google Services' core products and platforms include ads, Android, Chrome, devices, Gmail, Google Drive, Google Gemini, Google Maps, Google Photos, Google Play, Search, and YouTube"),
        ('block-000068-ab181097', 'Google Search helps people find information and make sense of the world'),
        ('block-000068-ab181097', 'YouTube provides people with entertainment, information, and opportunities to learn something new')]),
    ('GO-03', 'YouTube 等业务身份与多种赚钱方式分开',
     'YouTube 的广告与订阅不能被拆成互不相认的两个完整业务，YouTube ads 也不能等同全部 YouTube。保留有据的共享身份或明确属性关联；Google One、Google Play、设备的收费描述不编造产品收入金额。', [
        ('block-000094-0c7f9036', 'performance and brand advertising that appears on Google Search & other properties, YouTube, and Google Network'),
        ('block-000099-9da7e695', 'YouTube TV, YouTube Music and Premium, and NFL Sunday Ticket, as well as Google One'),
        ('block-000100-0a4cdc1c', 'Google Play sales of apps and in-app purchases')]),
    ('GO-04', 'Cloud 平台/Workspace 与产品功能边界清楚',
     'GCP 与 Workspace 可独立定位，Cloud 收费以 consumption-based fees/subscriptions 原文为准。Vertex AI/Gemini/数据分析等能力或产品按正确宿主与具体证据表达；不得把整个Cloud客户或收费方式无条件复制给每个功能。', [
        ('block-000103-d95e78b6', 'Through our Google Cloud Platform and Google Workspace offerings, Google Cloud generates revenues primarily from consumption-based fees and subscriptions'),
        ('block-000112-6e57c03e', 'Gemini for Google Workspace: brings our AI-powered agents into Gmail, Docs, Sheets, and more')]),
    ('GO-05', 'Other Bets 具体活动与归属确定性分开',
     'Waymo 的付费无人驾驶服务、X 的研发活动、Isomorphic Labs 的AI药物发现活动有依据即可保留；同段出现不足以为所有对象生成明示 Other Bets 归属。不能为避免归属风险删除已知活动，也不虚构未披露收入。', [
        ('block-000079-1028dedb', 'In Other Bets, our fully autonomous driving technology company, Waymo, is now providing fully autonomous, paid ride-hailing services'),
        ('block-000079-1028dedb', 'Isomorphic Labs is reimagining the drug discovery process from first principles, applying AI to accelerate the development of new medicines.'),
        ('block-000114-f5db1f8d', 'such as X, our moonshot factory focused on developing breakthrough technologies')]),
    ('GO-06', '客户、收费与每条精确引用相互对应',
     '广告客户的 advertisers/agencies/publishers 应引用直接描述客户的段落；品牌/效果广告、订阅和消费收费分开。每项属性引用证明整个声明，不借产品名命中掩盖错误分类。仅检查新执行实际交付范围；旧包的财务附注不能偷偷补进新Business-only输入的证据。', [
        ('block-000093-02c6e3d3', 'advertising technologies for advertisers, agencies, and publishers'),
        ('block-000095-e4c14dea', 'Performance advertising creates and delivers relevant ads'),
        ('block-000096-9dac0973', 'Brand advertising helps enhance'),
        ('block-000103-d95e78b6', 'consumption-based fees and subscriptions')]),
]


def main():
    result = dict(schema_version='business-granularity-pre-run-acceptance-v1',
        created_on='2026-10-08', purpose='reviewer_only_pre_run_regression_acceptance',
        execution_input_allowed=False, evaluation_kind='regression_not_holdout',
        new_candidate_outputs_read=False, paid_model_calls=0, status='criteria_frozen_not_evaluated',
        isolation_policy='Do not include this file, its case names, expected classifications or reviewer conclusions in model execution inputs. Evaluation only; no automatic answer repair.',
        comparison_limits='These companies and historical errors have been discussed before. A new run tests implementation of the revised method, not unseen-company generalization or blinded model ranking.',
        skill_review=dict(path='skills/uteki-business-diagrams/references/business-products-v1.md',
            sha256=sha(ROOT/'skills/uteki-business-diagrams/references/business-products-v1.md'),
            verdict='aligned_with_two_interface_boundaries',
            aligned=['Identity versus populated attribute is a semantic choice, not a named-offering node quota.',
                     'Unresolved/missing items remain gaps; source accounting and self-review are not independent acceptance.',
                     'Exact existing claim evidence and source-bound indices are required for attribute coverage.'],
            boundaries=[dict(id='SK-01', issue='Skill requires every monetization attribute to have claim evidence, while existing BusinessOnlyDraftV2 supports unknown monetization without a claim and rejects extra claims for that unknown item.',
                             handling='For this capability emit only explicit, cited monetization. Put unknown charging mechanisms in unknowns; make this prompt wording explicit before execution.'),
                        dict(id='SK-02', issue='The historical Alphabet 78-block packet is a discontinuous fragment_scope containing Business and financial notes, not the complete_report_subsection required by the new Skill.',
                             handling='Freeze a new, explicitly bounded complete Business subsection and issuer/period metadata before v2 execution. Rebind evaluation excerpts only when actually included; do not relabel the old fragmented packet.')]),
        cases=[case('experiments/agent_design/2026-10-07-microsoft-agent-independent-v1/run-01/attempt-01/source_packet.json', MS,
                    'All 103 supplied blocks read before new candidate execution. Complete Operating Segments subsection plus issuer/period context, FY2025. This is not the full report.'),
               case('experiments/agent_design/2026-10-07-agent-business-revenue-v1/run-01/source_packet.json', GOOGLE,
                    'Historical 78-block mixed packet used only as reviewer source provenance. Six checks use Business excerpts, not financial amounts. A new complete-subsection packet is required for execution and must be bound separately.')])
    if OUTPUT.exists():
        raise FileExistsError('pre-run acceptance is frozen; publish a new version to revise')
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'path':str(OUTPUT.relative_to(ROOT)), 'checks':[len(c['checks']) for c in result['cases']],
                      'new_candidate_outputs_read':False, 'sha256':sha(OUTPUT)}))


if __name__ == '__main__': main()
