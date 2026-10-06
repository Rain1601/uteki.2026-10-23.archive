// This isolated prototype uses real company identities from the existing
// candidate universe. Every research claim, evidence item and portfolio is
// fictional interaction content; none is connected to production research.
export const demo = {
  asOf: '2026-09-24',
  label: '交互结构稿 · 全部内容为示意',
  companies: [
    { id: 'alphabet', name: 'Alphabet', ticker: 'GOOGL', mark: 'G', role: 'followed', reason: '持续验证搜索与云业务的长期盈利能力。' },
    { id: 'microsoft', name: 'Microsoft', ticker: 'MSFT', mark: 'M', role: 'followed', reason: '跟踪 AI 投入能否转化为可持续的客户需求。' },
    { id: 'nvidia', name: 'NVIDIA', ticker: 'NVDA', mark: 'N', role: 'followed', reason: '关注算力需求与交付节奏是否匹配。' },
    { id: 'costco', name: 'Costco Wholesale', ticker: 'COST', mark: 'C', role: 'followed', reason: '持续验证会员黏性与长期经营质量。' },
    { id: 'arista', name: 'Arista Networks', ticker: 'ANET', mark: 'A', role: 'discovery', reason: '示例线索：数据中心扩建是否带来新的网络设备需求？' },
    { id: 'eaton', name: 'Eaton', ticker: 'ETN', mark: 'E', role: 'discovery', reason: '示例线索：电力基础设施需求能否转化为持续订单？' },
  ],
  reports: [
    {
      id: 'report-alphabet', companyId: 'alphabet', version: '0.3', date: '2026-09-18',
      title: 'Alphabet · 主研究报告',
      thesis: '搜索的现金创造能力，为云业务的长期投入提供空间。',
      summary: '示例主报告持续维护两项判断：云业务盈利质量，以及搜索业务的商业韧性。新材料尚待复核，当前结论没有自动更新。',
      factors: [
        { id: 'alphabet-cloud-quality', label: '云业务盈利质量', conclusion: '原判断：盈利改善主要来自经营效率，仍需排除一次性因素。' },
        { id: 'alphabet-search-resilience', label: '搜索商业韧性', conclusion: '原判断：新的产品形态尚未明显削弱商业转化能力。' },
      ],
    },
    {
      id: 'report-microsoft', companyId: 'microsoft', version: '0.2', date: '2026-09-16',
      title: 'Microsoft · 主研究报告',
      thesis: '企业客户的持续使用，比产品试用更能验证 AI 需求。',
      summary: '示例研究关注试用、续约与扩展采购之间的关系。单次客户反馈只作为观察材料，尚不能推及整体客户。',
      factors: [
        { id: 'microsoft-retention', label: 'AI 客户持续使用', conclusion: '原判断：AI 付费需求有待续约与扩展采购数据验证。' },
      ],
    },
    {
      id: 'report-nvidia', companyId: 'nvidia', version: '0.4', date: '2026-09-17',
      title: 'NVIDIA · 主研究报告',
      thesis: '需求的持续性，需要通过客户部署和利用率共同验证。',
      summary: '示例研究把订单、交付和实际部署分开追踪。交付时间变化本身不足以说明需求方向。',
      factors: [
        { id: 'nvidia-deployment', label: '交付与部署节奏', conclusion: '原判断：交付扩张能够被客户部署消化，仍需核对项目进度。' },
      ],
    },
    {
      id: 'report-costco', companyId: 'costco', version: '0.2', date: '2026-09-12',
      title: 'Costco · 主研究报告',
      thesis: '稳定的会员关系，是经营质量的重要观察窗口。',
      summary: '示例研究维持原判断。目前没有足以改变结论的新示例证据，等待下一次会员与门店经营信息。',
      factors: [
        { id: 'costco-membership', label: '会员关系稳定性', conclusion: '原判断：会员价值感是长期续费意愿的基础。' },
      ],
    },
    {
      id: 'report-arista', companyId: 'arista', version: '0.1', date: '2026-09-23',
      title: 'Arista · 初步研究报告',
      thesis: '数据中心网络需求，是否提供独立于算力设备的研究机会？',
      summary: '示例初步研究尚未形成投资结论。需要核对需求来源、客户集中度与订单兑现，决定是否加入持续关注。',
      factors: [
        { id: 'arista-network-demand', label: '网络需求可持续性', conclusion: '待研究：新增需求是项目集中采购，还是持续扩建？' },
      ],
    },
    {
      id: 'report-eaton', companyId: 'eaton', version: '0.1', date: '2026-09-22',
      title: 'Eaton · 初步研究报告',
      thesis: '电力基础设施投入，能否带来可验证的长期订单？',
      summary: '示例初步研究尚未形成投资结论。需要理解订单结构、交付约束与现金转化，决定是否进入正式研究。',
      factors: [
        { id: 'eaton-order-quality', label: '电力订单质量', conclusion: '待研究：需求线索能否转化为有质量的交付和回款？' },
      ],
    },
  ],
  changes: [
    {
      id: 'change-alphabet-cloud', companyId: 'alphabet', reportId: 'report-alphabet', factorId: 'alphabet-cloud-quality', kind: 'challenge',
      title: '云业务的盈利改善，需要重新拆解',
      before: '盈利改善主要来自经营效率提升。',
      after: '示例新材料提到一次性收益，需要重算可持续的改善幅度。',
      why: '它直接关系到主报告中的长期盈利判断，值得优先复核。',
      positionImpact: '若该判断是你的持有理由，应先复核其适用范围；尚未形成调仓结论。',
      evidence: [
        { id: 'evidence-alphabet-cloud-1', title: '一次性收益说明', source: '虚构示例 · 财务附注', excerpt: '演示材料假设：当期收益包含非持续项目，影响幅度需要进一步拆分。', stance: 'challenge' },
        { id: 'evidence-alphabet-cloud-2', title: '经营改善的历史依据', source: '虚构示例 · 旧报告摘录', excerpt: '演示中的旧报告将费用效率改善视为主要驱动，未纳入上述项目。', stance: 'context' },
      ],
      taskIds: ['task-alphabet-cloud'], date: '2026-09-24', rank: 1,
    },
    {
      id: 'change-microsoft-retention', companyId: 'microsoft', reportId: 'report-microsoft', factorId: 'microsoft-retention', kind: 'support',
      title: '持续使用的判断，多了一条支持',
      before: '付费试用能否转为持续使用，仍缺少后续观察。',
      after: '示例客户材料出现续约与扩大使用的描述，支持原研究方向。',
      why: '它补充了试用之后的行为，但样本有限，尚不足以提升整体结论。',
      positionImpact: '可补充持有理由的证据；单个示例样本不构成增加仓位的依据。',
      evidence: [
        { id: 'evidence-microsoft-retention-1', title: '续约后的使用情况', source: '虚构示例 · 客户访谈', excerpt: '演示材料假设：某客户续约后扩大了使用团队，尚待更多独立样本交叉验证。', stance: 'support' },
      ],
      taskIds: ['task-microsoft-retention'], date: '2026-09-24', rank: 2,
    },
    {
      id: 'change-nvidia-deployment', companyId: 'nvidia', reportId: 'report-nvidia', factorId: 'nvidia-deployment', kind: 'watch',
      title: '部署时间变化，先确认原因',
      before: '客户部署按预期推进，能够承接设备交付。',
      after: '示例项目调整了部署时间，尚不清楚是配套约束还是需求变化。',
      why: '时间变化可能影响验证节点，需要核对后才能解释其投资意义。',
      positionImpact: '暂不改变原持仓判断，将配套约束与需求走弱分别验证。',
      evidence: [
        { id: 'evidence-nvidia-deployment-1', title: '项目时间调整记录', source: '虚构示例 · 项目进展', excerpt: '演示材料假设：一个部署项目修改了时间安排，但没有给出足够的原因说明。', stance: 'context' },
      ],
      taskIds: ['task-nvidia-deployment'], date: '2026-09-23', rank: 3,
    },
    {
      id: 'change-alphabet-search', companyId: 'alphabet', reportId: 'report-alphabet', factorId: 'alphabet-search-resilience', kind: 'support',
      title: '搜索商业韧性，获得补充证据',
      before: '新产品形态对商业转化的影响尚待观察。',
      after: '示例样本中的商业转化保持稳定，支持原报告的局部判断。',
      why: '新增证据与原因素直接相关，但需要检查样本覆盖和可比口径。',
      positionImpact: '帮助复核原持有理由；需更多时间与样本判断是否适用于整体业务。',
      evidence: [
        { id: 'evidence-alphabet-search-1', title: '商业转化的观察样本', source: '虚构示例 · 样本记录', excerpt: '演示材料假设：在相同观察口径下，一组样本的商业转化没有明显变化。', stance: 'support' },
      ],
      taskIds: ['task-alphabet-search'], date: '2026-09-23', rank: 4,
    },
  ],
  tasks: [
    {
      id: 'task-alphabet-cloud', companyId: 'alphabet', reportId: 'report-alphabet', factorId: 'alphabet-cloud-quality',
      title: '拆分盈利改善的来源', waitingFor: '可持续经营收益与一次性项目的可比拆分。', nextCheck: '2026-09-25', status: 'review',
      recent: '已汇集 2 条示例材料，等待复核后更新主报告。',
    },
    {
      id: 'task-microsoft-retention', companyId: 'microsoft', reportId: 'report-microsoft', factorId: 'microsoft-retention',
      title: '交叉验证续约与使用', waitingFor: '不同客户的续约、扩展采购与持续使用记录。', nextCheck: '2026-09-28', status: 'running',
      recent: '增加 1 条示例支持，样本覆盖仍然不足。',
    },
    {
      id: 'task-nvidia-deployment', companyId: 'nvidia', reportId: 'report-nvidia', factorId: 'nvidia-deployment',
      title: '核对部署延期的原因', waitingFor: '项目配套与最终需求的独立说明。', nextCheck: '2026-09-29', status: 'waiting',
      recent: '等待补充材料，原研究结论保持待验证。',
    },
    {
      id: 'task-alphabet-search', companyId: 'alphabet', reportId: 'report-alphabet', factorId: 'alphabet-search-resilience',
      title: '跟踪商业转化的可比样本', waitingFor: '更长观察期和相同口径下的新增样本。', nextCheck: '2026-09-30', status: 'running',
      recent: '新示例与原判断方向一致，继续检查样本边界。',
    },
  ],
  managers: [
    {
      id: 'manager-a', name: '示例经理 A', mandate: '长期质量 · 示意委托组合', period: '2026-09-01 至 2026-09-24 · 示意累计收益', returnPct: 4.2, cashPct: 12,
      positions: [
        { companyId: 'alphabet', weightPct: 28, changePp: -2 },
        { companyId: 'microsoft', weightPct: 34, changePp: 3 },
        { companyId: 'costco', weightPct: 26, changePp: 0 },
      ],
      actions: [
        { id: 'action-a-alphabet', companyId: 'alphabet', status: 'executed', label: '仓位减少 2 个百分点', reason: '示例决策：控制单一研究判断对组合的影响，保留复核空间。', date: '2026-09-23' },
        { id: 'action-a-microsoft', companyId: 'microsoft', status: 'proposed', label: '提出续约质量复核', reason: '示例计划：扩大客户样本后，再评估是否继续调整仓位。', date: '2026-09-24' },
      ],
    },
    {
      id: 'manager-b', name: '示例经理 B', mandate: '产业成长 · 示意委托组合', period: '2026-09-01 至 2026-09-24 · 示意累计收益', returnPct: -1.3, cashPct: 20,
      positions: [
        { companyId: 'nvidia', weightPct: 35, changePp: -3 },
        { companyId: 'microsoft', weightPct: 25, changePp: 0 },
        { companyId: 'alphabet', weightPct: 20, changePp: 0 },
      ],
      actions: [
        { id: 'action-b-nvidia', companyId: 'nvidia', status: 'executed', label: '仓位减少 3 个百分点', reason: '示例决策：降低组合波动，等待部署节奏的不确定性收敛。', date: '2026-09-22' },
        { id: 'action-b-alphabet', companyId: 'alphabet', status: 'proposed', label: '计划复核云业务判断', reason: '示例计划：拆分盈利来源后，重新说明维持持仓的依据。', date: '2026-09-24' },
      ],
    },
  ],
};

export default demo;
