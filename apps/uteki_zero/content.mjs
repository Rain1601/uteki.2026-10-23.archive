// All reports, events, evidence, portfolios, and returns below are fictional UI content.
// Company names identify the design examples; nothing here is current research or user data.
export const content = {
  asOf: '2026-09-24',
  companies: [
    {
      id: 'alphabet', name: 'Alphabet', ticker: 'GOOGL', website: 'https://www.abc.xyz/', color: '#4285F4',
      followed: true, tagline: '搜索 · 云 · AI', status: 'review',
      headline: '增长逻辑仍在，利润兑现需要复核',
      summary: '云业务需求出现支持信号，但新增投入超出原假设。两条变化指向同一份主报告。',
      report: {
        title: 'Alphabet：AI 投入何时转化为回报', version: 'v0.3', date: '2026-09-18',
        thesis: '搜索业务提供现金流，云业务与 AI 打开增长空间；投资判断取决于新增投入能否转化为持续回报。',
        factors: [
          {
            id: 'alphabet-return', label: 'AI 投入回报',
            view: '新增收入有望逐步覆盖投入，利润率改善需要需求兑现。', status: 'review',
            tracking: {
              question: '新增投入多久能够转化为收入？',
              waiting: '下一次披露中的投入节奏、折旧与新增收入线索',
              nextDate: '2026-10-01', state: 'ready',
            },
          },
          {
            id: 'alphabet-cloud', label: '云业务需求',
            view: 'AI 工作负载增加有望带动云业务，但仍需观察订单转化。', status: 'support',
            tracking: {
              question: '新增需求是否已经转化为持续使用？',
              waiting: '客户续约、实际使用量与订单兑现的后续线索',
              nextDate: '2026-09-30', state: 'running',
            },
          },
        ],
      },
      events: [
        {
          id: 'alphabet-capex', kind: 'review', date: '2026-09-24',
          title: '投入计划扩大，利润兑现可能延后',
          summary: '新披露的扩建计划高于主报告假设，需要重新核对投入和回报之间的时间差。',
          before: '投入增速将逐渐回落，收入增长有望带动利润率改善。',
          after: '新增扩建计划延长了投入周期，原先的利润率改善时间点需要复核。',
          implication: '若已持有，可先复核利润兑现时间和估值假设；是否调整仓位还取决于收入兑现情况。',
          factorId: 'alphabet-return',
          evidence: [
            {
              id: 'alphabet-capex-e1', title: '新增扩建计划与原假设存在差异',
              source: '虚构演示来源 · 基础设施计划摘要', date: '2026-09-24',
              excerpt: '扩建计划增加了后续投入安排，产能投入使用与客户需求兑现之间仍存在时间差。',
            },
          ],
        },
        {
          id: 'alphabet-demand', kind: 'support', date: '2026-09-23',
          title: '云业务新增需求，为增长判断补充证据',
          summary: '客户使用线索支持需求增长，但尚不能单独证明投入回报已改善。',
          before: 'AI 工作负载能够拉动云业务，仍缺少持续使用层面的证据。',
          after: '新增客户使用线索补充了需求证据；订单兑现与利润贡献仍待跟踪。',
          implication: '若已持有，这条证据可支持继续检验增长判断，尚不足以单独支持提高仓位。',
          factorId: 'alphabet-cloud',
          evidence: [
            {
              id: 'alphabet-demand-e1', title: '客户使用场景从试验进入持续运行',
              source: '虚构演示来源 · 云服务客户使用摘要', date: '2026-09-23',
              excerpt: '部分客户将 AI 工作负载从短期试验迁入持续运行，实际收入贡献尚未单独披露。',
            },
          ],
        },
      ],
    },
    {
      id: 'microsoft', name: 'Microsoft', ticker: 'MSFT', website: 'https://www.microsoft.com/', color: '#537B70',
      followed: true, tagline: '企业软件 · 云 · AI', status: 'support',
      headline: '付费使用增加，商业化判断获得支持',
      summary: '企业客户从试用转向付费，下一步关注续约与持续使用。',
      report: {
        title: 'Microsoft：AI 能否成为持续收入', version: 'v0.2', date: '2026-09-16',
        thesis: '企业软件的客户基础有利于 AI 产品分发，长期价值取决于付费转化、续约与使用深度。',
        factors: [
          {
            id: 'microsoft-adoption', label: 'AI 付费转化',
            view: '试用需求有望转化为付费，持续使用程度仍需验证。', status: 'support',
            tracking: {
              question: '付费客户是否持续使用并选择续约？',
              waiting: '客户续约与席位使用情况的后续线索',
              nextDate: '2026-10-02', state: 'running',
            },
          },
        ],
      },
      events: [
        {
          id: 'microsoft-paid', kind: 'support', date: '2026-09-24',
          title: '试用转付费，为 AI 商业化补充证据',
          summary: '企业采购线索显示付费使用增加，商业化方向得到支持。',
          before: '企业有试用意愿，但能否转为长期付费仍需观察。',
          after: '新增采购线索支持付费转化，长期续约与实际使用深度仍待验证。',
          implication: '若已持有，可增强对商业化方向的信心；仓位判断仍需结合续约质量和当前估值。',
          factorId: 'microsoft-adoption',
          evidence: [
            {
              id: 'microsoft-paid-e1', title: '企业采购从试用转入付费阶段',
              source: '虚构演示来源 · 企业软件采购访谈摘要', date: '2026-09-24',
              excerpt: '部分试用客户开始购买付费席位，但尚未经过完整续约周期，日常使用深度仍需跟踪。',
            },
          ],
        },
      ],
    },
    {
      id: 'nvidia', name: 'NVIDIA', ticker: 'NVDA', website: 'https://www.nvidia.com/', color: '#76B900',
      followed: true, tagline: '算力 · 芯片 · 生态', status: 'watch',
      headline: '交付节奏出现分歧，等待后续确认',
      summary: '两条交付线索尚未指向一致结论，暂时保留原判断并继续追踪。',
      report: {
        title: 'NVIDIA：需求与交付能否保持匹配', version: 'v0.4', date: '2026-09-20',
        thesis: '算力需求支持增长，收入兑现同时取决于产品交付和客户部署进度。',
        factors: [
          {
            id: 'nvidia-delivery', label: '交付与部署',
            view: '交付改善有望支持收入兑现，短期节奏可能存在波动。', status: 'watch',
            tracking: {
              question: '交付变化是短期波动还是持续延后？',
              waiting: '同一时间范围内的客户部署与产品交付线索',
              nextDate: '2026-09-29', state: 'waiting',
            },
          },
        ],
      },
      events: [
        {
          id: 'nvidia-timing', kind: 'watch', date: '2026-09-23',
          title: '交付与部署线索不一致，先保留判断',
          summary: '供应侧与客户侧的描述存在差异，当前还不足以判断收入节奏是否改变。',
          before: '交付改善将逐步带动客户部署，支持收入按预期兑现。',
          after: '供应侧提到交付推进，客户侧仍在等待配套条件，两者覆盖范围需要核对。',
          implication: '若已持有，可先保留仓位判断，待覆盖范围与时间口径一致后再评估收入兑现风险。',
          factorId: 'nvidia-delivery',
          evidence: [
            {
              id: 'nvidia-timing-e1', title: '供应侧描述交付推进',
              source: '虚构演示来源 · 供应链访谈摘要', date: '2026-09-23',
              excerpt: '部分产品的交付安排继续推进，但该描述未覆盖客户安装和正式运行的进度。',
            },
            {
              id: 'nvidia-timing-e2', title: '客户部署仍等待配套条件',
              source: '虚构演示来源 · 算力客户部署记录', date: '2026-09-23',
              excerpt: '部分项目仍在等待供电和网络配套，尚不清楚是否与前述交付批次对应。',
            },
          ],
        },
      ],
    },
    {
      id: 'costco', name: 'Costco', ticker: 'COST', website: 'https://www.costco.com/', color: '#A95754',
      followed: true, tagline: '会员零售 · 消费', status: 'quiet',
      headline: '暂无改变核心判断的新证据',
      summary: '会员价值与续费意愿仍是关注重点，等待下一次经营披露。',
      report: {
        title: 'Costco：会员价值能否持续', version: 'v0.2', date: '2026-09-12',
        thesis: '会员制与商品价值形成相互支撑，研究重点是续费意愿和消费者信任能否保持。',
        factors: [
          {
            id: 'costco-renewal', label: '会员续费',
            view: '稳定的会员价值有望支持续费，目前没有新增证据改变判断。', status: 'quiet',
            tracking: {
              question: '会员续费和消费行为是否出现变化？',
              waiting: '下一次经营披露中的会员与同店经营信息',
              nextDate: '2026-10-05', state: 'waiting',
            },
          },
        ],
      },
      events: [],
    },
    {
      id: 'arista', name: 'Arista', ticker: 'ANET', website: 'https://www.arista.com/', color: '#55709B',
      followed: false, tagline: '网络设备 · 数据中心', status: 'new',
      headline: 'AI 网络需求，值得建立初步研究',
      summary: '从算力扩张延伸到网络投入，先确认需求如何转化为订单。',
      report: {
        title: 'Arista：AI 网络需求的初步研究', version: 'v0.1 · 初步', date: '2026-09-24',
        thesis: '算力扩张可能带动网络设备需求，当前仍需确认客户投入如何转化为公司订单。',
        factors: [
          {
            id: 'arista-orders', label: '网络需求与订单',
            view: '存在值得研究的需求关联，尚未形成可采纳的投资结论。', status: 'watch',
            tracking: {
              question: '客户网络投入能否形成可追踪的订单？',
              waiting: '客户网络规划与公司订单披露',
              nextDate: '2026-10-03', state: 'waiting',
            },
          },
        ],
      },
      events: [],
    },
    {
      id: 'eaton', name: 'Eaton', ticker: 'ETN', website: 'https://www.eaton.com/', color: '#82725B',
      followed: false, tagline: '电力管理 · 基础设施', status: 'new',
      headline: '数据中心供电，值得进一步了解',
      summary: '关注电力配套需求与交付能力，先判断机会是否足以影响公司整体经营。',
      report: {
        title: 'Eaton：电力配套机会的初步研究', version: 'v0.1 · 初步', date: '2026-09-24',
        thesis: '数据中心建设可能增加电力管理需求，需要先确认业务占比、订单质量与交付能力。',
        factors: [
          {
            id: 'eaton-power', label: '电力配套需求',
            view: '需求方向值得关注，对整体经营的贡献仍缺少证据。', status: 'watch',
            tracking: {
              question: '数据中心相关订单对整体业务有多大影响？',
              waiting: '订单结构、相关业务占比与交付安排',
              nextDate: '2026-10-06', state: 'waiting',
            },
          },
        ],
      },
      events: [],
    },
  ],
  managers: [
    {
      id: 'north', name: 'North · 质量成长', initials: 'N',
      strategy: '关注现金流与长期竞争力，控制单一公司的集中度。',
      returnPct: 4.2, cashPct: 14, period: '2026.07.01 — 2026.09.24',
      positions: [
        { companyId: 'microsoft', weightPct: 28, deltaPp: 2 },
        { companyId: 'alphabet', weightPct: 24, deltaPp: -3 },
        { companyId: 'costco', weightPct: 18, deltaPp: 0 },
        { companyId: 'nvidia', weightPct: 16, deltaPp: 0 },
      ],
      actions: [
        {
          id: 'north-alphabet', companyId: 'alphabet', date: '2026-09-24',
          title: '降低 Alphabet 配置，保留后续观察',
          reason: '缩小投入回报不确定性带来的组合影响，等待新的收入兑现证据。',
          status: 'done',
        },
        {
          id: 'north-microsoft', companyId: 'microsoft', date: '2026-09-23',
          title: '小幅增加 Microsoft 配置',
          reason: '付费转化线索补充了原有判断，同时保留续约验证要求。',
          status: 'done',
        },
      ],
    },
    {
      id: 'field', name: 'Field · 产业观察', initials: 'F',
      strategy: '沿产业链跟踪需求兑现，分散持有不同环节的公司。',
      returnPct: 2.7, cashPct: 20, period: '2026.07.01 — 2026.09.24',
      positions: [
        { companyId: 'nvidia', weightPct: 26, deltaPp: -2 },
        { companyId: 'arista', weightPct: 24, deltaPp: 2 },
        { companyId: 'eaton', weightPct: 20, deltaPp: 0 },
        { companyId: 'costco', weightPct: 10, deltaPp: 0 },
      ],
      actions: [
        {
          id: 'field-arista', companyId: 'arista', date: '2026-09-24',
          title: '增加 Arista 配置，跟踪订单兑现',
          reason: '在产业链不同环节分散配置，并持续核对网络需求与订单的关系。',
          status: 'done',
        },
        {
          id: 'field-eaton', companyId: 'eaton', date: '2026-09-24',
          title: '评估 Eaton 配置，尚未执行',
          reason: '等待相关订单占比与交付信息，确认机会对整体经营的影响。',
          status: 'planned',
        },
      ],
    },
  ],
};
