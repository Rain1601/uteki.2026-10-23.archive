// Named, fictional fixture for the report-reading prototype. None of the text,
// dates, method settings, or publication records below is real investment research.
// This module never loads drafts, calls a model, fetches prices, or creates reports.

const section = (id, kicker, title, paragraphs, citations = [], extra = {}) => ({
  id, kicker, title, paragraphs, citations, ...extra,
});

const alphabetNorthV1 = {
  version: 'v1', publicationId: 'demo-pub-alphabet-north-v1',
  publishedAt: '2026-09-18', cutoff: '2026-09-17', language: 'zh-CN',
  title: 'Alphabet：增长之后，还要看回报',
  subtitle: 'North · 质量成长 / 完整历史报告 · 虚构演示',
  summary: '本演示以现金创造能力为研究起点：新增云需求能否在投入扩张后留下可持续回报？旧版把收入兑现与成本释放视为能够接续发生的过程，这一时间假设后来受到新线索挑战。',
  verdict: '有条件继续研究；回报假设尚未获得完整验证，不形成可执行买入结论。',
  status: 'review',
  reviewNote: '演示中 9 月 24 日出现的扩建线索触及本版投入与估值假设。本版全文按原截止保留，受影响结论待复核；v2 已另行发布，不覆盖本版。',
  affectedSections: ['economics', 'valuation'],
  sections: [
    section('business', '01 / 业务', '把客户需求与现金创造分开看', [
      '这份虚构报告把 Alphabet 的业务放在两个观察层面：一是既有产品如何服务客户并形成现金来源，二是新增计算能力如何进入客户的工作流程。研究不把所有 AI 相关消息合成一个增长数字，也不把业务标签本身当成竞争优势的证据。',
      '当前演示资料只有产品和需求摘要，没有可核验的分部财务表。因此，以下论述是有明确限制的研究样例；各业务的收入规模、利润贡献和相互补贴程度均未量化。',
    ], ['demo-alpha-business']),
    section('thesis', '02 / 核心判断', '需求增长，必须经过回报这一关', [
      'North 的原判断是：如果客户持续使用新增服务，且每单位服务的收入能够覆盖计算、折旧和获客成本，新增投入才可能增强长期价值。这个链条需要逐环验证，不能用客户兴趣替代付费，也不能用订单替代现金回收。',
      '本版暂时假定投入高峰与需求爬坡可以逐步衔接。该假设来自演示情景设定，并不是公开事实；若投入持续提前、客户使用滞后，原先期待的利润释放就可能延后。',
    ], ['demo-alpha-demand-early']),
    section('support', '03 / 正向依据', '试用之外，开始出现持续使用线索', [
      '演示客户记录提到，有项目在试验结束后继续运行。它让需求判断从一次性兴趣向持续使用推进了一步，但记录没有说明客户总体规模，也没有提供统一的收费口径。这里能得到支持的是研究方向，尚不是收入增速或利润率。',
      '后续应把同一客户、同一产品与同一期间连接起来，检查使用是否连续、付款是否发生、优惠是否退出。缺少这些对应关系，几条好消息也无法构成可重复的商业模式。',
    ], ['demo-alpha-demand-early']),
    section('economics', '04 / 反证与成本', '投入时间差是这份判断的薄弱处', [
      '建设支出先发生，服务收入在后发生，两者之间可能隔着设备交付、安装、客户迁移和产能利用的多个阶段。即使最终需求存在，过早投入也会带来低利用率和成本先行。',
      '本版尚无足够材料判断各阶段的长度，因此保留“收入兑现后成本负担逐步消化”的条件性假设。若出现进一步提前建设、项目延期或持续价格让利，应优先复核这一节，不能只调整收入预测。',
    ], ['demo-alpha-business']),
    section('valuation', '05 / 估值条件', '先列门槛，再讨论价格', [
      '没有经过核验的现金流、资本开支明细和观察日市场价格，本版不提供目标价、倍数或预期收益。演示页面中的公司名称与图标不能替代这些输入，也不意味着已经完成估值。',
      '进入估值前，至少需要统一期间的经营现金流、维持性与扩张性支出解释，以及收入兑现的情景区间。估值应同时容纳回报延后与成本上升，而不是把一个乐观增长路径写成唯一答案。',
    ], [], { table: { columns: ['必要输入', '当前状态'], rows: [['经营与投入数据', '演示资料缺失，不能计算'], ['观察日价格与口径', '未接入行情，不能判断买入价'], ['回报兑现区间', '需补充客户和成本证据']] } }),
    section('judgment', '06 / 投资判断', '保持研究，不把条件性观点变成交易', [
      'North 愿意继续检验这条增长路径，但尚不能回答当前价格是否合适。最值得跟踪的是需求质量与投入效率的交叉点，而不是短期新闻数量；任何单条证据都不足以独立形成买入决定。',
      '本报告不指定仓位，也不推导减仓或加仓比例。即使公司判断改善，组合仍需考虑其他机会、集中度与现金约束，这些问题应由对应 Manager 的组合报告说明。',
    ]),
    section('watch', '07 / 观察计划', '围绕同一条回报链补证据', [
      '接下来的观察分成需求与供给两端。需求端关注试验客户是否重复付费；供给端关注已建能力的使用和新建设节奏。只有期间与覆盖对象一致，才能把两端信息放在一起比较。',
      '若后续线索明显改变成本释放时间，保留本版，标出受影响判断并另发新版本。阅读、收藏或个人笔记均不改变研究有效状态，也不会自动触发任务。',
    ], [], { bullets: ['验证持续使用与付费的对应关系。', '补充建设、投产和利用率的同期间资料。', '当回报时间假设改变时，重新审视估值条件。'] }),
    section('limits', '08 / 未知与边界', '这份报告还不能回答什么', [
      '当前缺口包括真实财务口径、客户样本代表性、产品间成本分摊以及可比市场价格。没有这些信息，无法量化盈利变化，也不能判断某项业务是否抵消另一项业务的风险。所有引用均是专门编写的演示摘录。',
      '本版只用于检验完整报告、历史版本与引用返回的阅读体验；方法期限和日期也是命名演示场景的一部分，不是系统默认投资规则。',
    ]),
  ],
};

const alphabetNorthV2 = {
  version: 'v2', publicationId: 'demo-pub-alphabet-north-v2',
  publishedAt: '2026-09-29', cutoff: '2026-09-28', language: 'zh-CN',
  title: 'Alphabet：需求在前进，回报需要更多时间',
  subtitle: 'North · 质量成长 / 当前正式演示报告',
  summary: '新增持续使用线索支持需求方向，扩建安排却使投入与回报的间隔更难确定。North 因此撤回旧版对利润释放节奏的乐观假设，把验证重点转向同期间的使用、收费和成本。',
  verdict: '继续观察需求，暂不确认投入回报改善；缺少估值输入，不能据此形成买入建议。',
  status: 'current', reviewNote: '', affectedSections: [],
  sections: [
    section('business', '01 / 业务', '从产品使用，走到可持续现金流', [
      '本报告用同一个问题组织 Alphabet 的演示研究：客户愿意长期使用的服务，能否在承担计算与建设成本后留下回报？业务规模、技术能力和产品热度各有意义，但都不能直接回答这个问题。',
      '现有演示材料涵盖产品背景、持续使用与扩建安排，没有可核验的财务全貌。业务介绍只帮助读者理解判断涉及哪些环节，不代表已经测算各业务收入或利润。',
    ], ['demo-alpha-business']),
    section('thesis', '02 / 核心判断', '保留需求方向，修改兑现时间', [
      '相对 v1，North 保留对持续需求的观察价值，但不再把需求增长与利润释放写成自然衔接的过程。新增能力何时投入使用、客户何时付费以及成本何时释放，必须分别验证。',
      '这次变化收紧了原有假设，并未证明项目不能创造价值。它说明现有证据无法支持原先的时间预期；在缺口补齐前，任何关于回报改善的表述都应附带这一限制。',
    ], ['demo-alpha-use-later', 'demo-alpha-build-later']),
    section('support', '03 / 正向依据', '持续运行比试验意愿更进一步', [
      '新增演示记录描述部分客户将工作负载转入持续运行，并出现重复使用。这类线索比单次试验更接近可持续需求，但记录仍没有给出客户总体、收费强度或退出优惠后的行为。',
      'North 将其视为对需求判断的补充支持，而非盈利证明。若随后出现付费续用和服务成本同步改善，证据才可能把判断从“值得观察”推进到“回报更有把握”。',
    ], ['demo-alpha-use-later']),
    section('economics', '04 / 反证与风险', '投入扩张，让回报验证更加重要', [
      '另一段演示材料提到扩建安排增加，并存在建设与客户迁移不同步的可能。它改变的是成本先发生、收入后兑现的风险，而不是直接否定客户需求。把两类信息拆开，才能看见真正需要复核的判断。',
      '目前还缺少按项目对应的投产、利用率和单位成本资料。若新增能力长期闲置，或只能靠优惠吸引使用，投入规模越大并不意味着价值越高。该缺口必须留在判断旁边。',
    ], ['demo-alpha-build-later', 'demo-alpha-cost-gap']),
    section('valuation', '05 / 估值条件', '让等待的成本进入判断', [
      '本版没有真实行情，也没有核验后的现金流及支出数据，因此仍不展示目标价或回报数字。需求得到一些支持，并不能弥补价格与成本输入的缺失。',
      '与旧版相比，未来估值应显式考虑兑现较慢的情景：建设先行，收入分批进入，期间仍有持续投入。只有补齐期间、口径和现金回收资料，才能判断价格是否已合理反映这种等待。',
    ], ['demo-alpha-build-later'], { table: { columns: ['判断条件', '本版处理'], rows: [['需求持续性', '补充支持，但样本有限'], ['投入回报时间', '撤回原乐观时间假设'], ['可执行估值', '财务与价格输入缺失，暂不计算']] } }),
    section('judgment', '06 / 投资判断', '方向与买入条件，是两个问题', [
      'North 当前的结论是继续观察，而非确认回报改善。报告对需求的判断比旧版更有依据，对利润兑现的判断却更加谨慎；这两者可以同时成立，不需要合成一个简单的利好或利空标签。',
      '是否买入仍取决于证据完整度与价格条件，仓位大小则由组合报告处理。本页不使用演示持仓或短期收益来倒推公司结论，也不把已有持仓当成判断正确的证据。',
    ]),
    section('watch', '07 / 观察计划', '下一步要拿到可对应的证据', [
      '优先补充同一期间的客户持续付费、产能使用与成本变化。单独获得一份建设公告或一次客户访谈，仍不足以计算项目回报；观察任务应说明其要验证的具体假设。',
      '如果资料显示收费与利用率共同改善，可重新评估回报兑现；如果只见建设加快而客户使用停滞，则需要进一步下修原有假设。页面阅读本身不会启动这些研究动作。',
    ], [], { bullets: ['持续使用是否转化为重复付费？', '新增能力与实际需求能否在同一期间对应？', '成本材料能否解释建设与收益之间的时间差？'] }),
    section('limits', '08 / 未知与边界', '保留明确缺口，避免确定性的错觉', [
      '目前缺少可核验的成本桥接、代表性客户样本和观察日市场价格。部分成本材料仅有演示摘要，因此仍不能推出单位经济性、盈利变化或应支付的价格。',
      '正文与证据均为虚构演示。v1 继续保留原文及旧截止，v2 只表达这一命名样例中的新判断；版本更新不意味着真实研究已完成，也不替用户或 Manager 执行投资。',
    ], ['demo-alpha-cost-gap']),
  ],
};

const alphabetFieldV1 = {
  version: 'v1', publicationId: 'demo-pub-alphabet-field-v1',
  publishedAt: '2026-09-19', cutoff: '2026-09-18', language: 'zh-CN',
  title: 'Alphabet：扩张信号能走多远',
  subtitle: 'Field · 产业观察 / 完整历史报告 · 虚构演示',
  summary: 'Field 从建设、采购与部署节奏研究需求兑现。旧版认为试用向持续运行的迁移值得跟踪，但采购安排尚未与客户部署逐项对应，因此只形成阶段性观察。',
  verdict: '等待建设与客户使用相互印证；不以采购意向替代收入或投资回报。',
  status: 'historical', reviewNote: '', affectedSections: [],
  sections: [
    section('business', '01 / 研究对象', '从一项客户需求，看见多道交付环节', [
      '在这个演示案例中，Field 关注 Alphabet 从服务需求走向实际部署的过程。客户提出需求之后，还要经过资源预订、设备就绪、安装调试与工作负载迁移；不同环节的线索不能直接视为同一笔已兑现收入。',
      '公司整体业务仍然是研究边界，但本版先观察新增部署链条。局部样本的推进不能代表所有客户，也不能替代完整财务分析。',
    ], ['demo-alpha-business']),
    section('thesis', '02 / 核心判断', '建设动作只有与客户进度对应才有意义', [
      'Field 的假设是：若供给准备与客户迁移在相邻阶段持续推进，需求可能正在进入兑现过程。判断依赖事件顺序和对应关系，不依赖新闻中的乐观用词，也不把建设本身当成终点。',
      '这与 North 从长期现金回报出发的提问不同。本版关心未来几个观察节点能否相互验证，但即便阶段性验证成立，也不会自动回答长期回报率或合理买入价格。',
    ], ['demo-alpha-demand-early']),
    section('signals', '03 / 支持线索', '持续运行，为需求增加了一层可见性', [
      '演示客户材料提到试验结束后的继续运行，使需求不再完全停留在意向层面。Field 希望随后看到相同客户的迁移范围、部署时间和重复使用，而不是更多未说明样本的案例数量。',
      '当前证据的价值是提供下一步核对对象。若客户、时间和产品范围对不上，把使用线索与采购消息拼在一起会夸大兑现程度，因此本版仍只保留条件性判断。',
    ], ['demo-alpha-demand-early']),
    section('constraints', '04 / 反向线索', '资源准备不等于收入确认', [
      '演示采购记录只列出资源准备安排，没有对应客户的启用日期。设备可用、项目可用与客户愿意付费是不同门槛；任一环节滞后，都可能使采购增长与收入兑现脱节。',
      '本版尤其警惕把预订看成已经交付，或把试运行看成稳定使用。需要同时保留没有推进的样本，才能避免只从成功案例中选择证据。',
    ], ['demo-alpha-procurement-early']),
    section('valuation', '05 / 价格条件', '阶段性催化，不能跳过价格', [
      '采购和部署线索能够改变兑现预期，但不能单独给出公司价值。当前未接入真实价格、订单金额、收入确认和毛利口径，本版无法计算催化兑现后的收益，也不输出买入区间。',
      '未来需要比较市场价格所要求的兑现程度与证据能够支持的程度。若价格已经隐含顺利交付，新增支持线索也可能缺少安全余地；这在现有材料下仍是未知项。',
    ], [], { table: { columns: ['观察环节', '不能直接推导'], rows: [['资源准备', '不等于客户投产'], ['持续运行', '不等于利润改善'], ['采购线索', '不等于合理买入价格']] } }),
    section('judgment', '06 / 阶段判断', '保留研究机会，等待关键连接', [
      'Field 把本案例放在阶段性观察位置：需求线索有进展，但供给侧与客户侧尚未形成完整对应。下一项有价值的材料，应能连接已有两段信息，而不是再增加一个彼此孤立的故事。',
      '这一结论不对应具体仓位或交易。即便未来形成公司层面的买入条件，组合中的行业敞口与其他公司机会仍需单独审视，不能直接由本报告给出配比。',
    ]),
    section('watch', '07 / 观察节点', '用同一批项目串起进度', [
      '后续记录需要保留项目或客户范围、起止期间和阶段定义。先核对预订是否落地，再核对部署是否启用，最后确认实际使用；不同批次的信息不能被拼成一条连续进度。',
      '若项目取消、启用推迟或样本覆盖变化，应保留原记录并解释影响。没有取得新材料只表示覆盖不足，不能写成“需求没有变化”。',
    ], [], { bullets: ['寻找资源准备与客户启用的同批次记录。', '对照推进、延期与取消的样本。', '把未知节点列出来，不用推测补齐链条。'] }),
    section('limits', '08 / 可比性与未知', '短期节点不能替代长期回报', [
      'Field 的阶段性研究期限与 North 的长期假设不同，两份报告应先比较问题和截止，再比较观点。某个部署节点推进，可以支持 Field 的阶段判断，同时仍不足以改变 North 对现金回报的疑问。',
      '本版所有记录、方法和日期均为演示设置。缺少代表性样本、实际金额与价格资料，结论不能用于真实投资；历史正文保持完整，不随新版本重写。',
    ]),
  ],
};

const alphabetFieldV2 = {
  version: 'v2', publicationId: 'demo-pub-alphabet-field-v2',
  publishedAt: '2026-09-28', cutoff: '2026-09-27', language: 'zh-CN',
  title: 'Alphabet：两端都有进展，中间仍有缺口',
  subtitle: 'Field · 产业观察 / 当前正式演示报告',
  summary: '新材料分别显示持续使用与扩建安排，但尚不能确认它们属于同批项目。Field 因此提高对需求存在的关注，同时维持对具体兑现节奏的保留，不将投入扩张直接解释为收入加速。',
  verdict: '阶段线索有所增加，交付对应关系仍待验证；没有形成可执行的价格与买入条件。',
  status: 'current', reviewNote: '', affectedSections: [],
  sections: [
    section('business', '01 / 业务与链条', '连接客户启用与供给准备', [
      'Field 继续围绕新增服务的部署过程阅读 Alphabet。演示资料中，客户持续运行与供给扩建都出现新线索，研究问题因此更具体：新增能力是否服务了这些客户，还是两组独立的样本？',
      '客户使用、供给建设、公司财务是三种不同层面的材料。只有明确其覆盖范围，才能判断局部变化对整体业务有多大影响；本版尚未具备这一量化条件。',
    ], ['demo-alpha-business']),
    section('thesis', '02 / 核心判断', '更新观察强度，保留时间约束', [
      '相对 v1，Field 认为继续追踪部署链条更有理由，但不认为兑现速度已经得到确认。两端各有进展，不能证明中间的迁移、验收和付费环节已经贯通。',
      '本版把“寻找进展”改为“验证进展是否对应”。若同批客户与资源能够连接，阶段判断可进一步推进；如果样本根本不一致，则需收回由两组信息共同带来的乐观印象。',
    ], ['demo-alpha-use-later', 'demo-alpha-build-later']),
    section('signals', '03 / 正向证据', '从重复使用中寻找下一步核对点', [
      '持续运行的演示记录对需求存在提供了新增支持。Field 最关心的并非消息数量，而是记录能否给出可追踪的客户范围与使用期间，让后续材料能够验证同一个观察对象。',
      '目前仍没有统一收费与客户总体资料。持续使用可以减少“只有试用兴趣”的疑虑，却不能说明贡献规模。正向判断因此只推进到需求线索这一层，不延伸成盈利或价格结论。',
    ], ['demo-alpha-use-later']),
    section('constraints', '04 / 反向与缺口', '扩建增加，也可能拉长兑现链条', [
      '扩建安排既可能为未来需求准备资源，也可能造成供给早于客户启用。Field 不在缺少项目对应关系时选择其中一种解释；新的投入计划只是需要核对的节点，不是已经实现的产出。',
      '演示材料未提供完整的部署验收表，无法识别哪些项目已经就绪、哪些仍在迁移。与 North 更关注长期成本回报不同，这里的首要缺口是同批次进度与收入兑现之间的连接。',
    ], ['demo-alpha-build-later', 'demo-alpha-procurement-early']),
    section('valuation', '05 / 估值与条件', '阶段判断改善，也需要价格门槛', [
      'Field 没有取得真实行情与核验后的收入金额，不能判断当前价格包含多快的兑现预期，也不能计算事件兑现收益。演示中不展示看似精确的目标价，以免把缺失输入藏在结果后面。',
      '后续估值至少要区分按期推进、阶段延后和需求不足三种路径，并解释各路径依赖哪些资料。在证据无法区分这些路径之前，任何单点价格结论都缺乏可审视的依据。',
    ], [], { table: { columns: ['路径', '需要补充的材料'], rows: [['按期推进', '同批客户启用与收费记录'], ['阶段延后', '延期原因、覆盖范围与后续节点'], ['需求不足', '取消、低使用或退出样本']] } }),
    section('judgment', '06 / 当前判断', '保留两个同时成立的结论', [
      '需求方向得到更多支持，兑现时间仍不确定，这是本版同时保留的两个判断。它们分别对应客户使用与项目进度，不能为了形成一个统一信号而相互抵消。',
      '本报告不把 Field 与 North 的差异排成胜负，也不平均两位 Manager 的假设。两者关注的期限和条件不同，读者需要看到这些差异，再进入各自完整论述及其引用。',
    ]),
    section('watch', '07 / 观察计划', '让下一份材料补上中间环节', [
      '最优先的观察是找到同批项目的启用与客户使用记录，明确范围、日期和阶段定义。若能补上这一连接，再评估收入兑现；若仍只有新的建设新闻，应继续标记缺口。',
      '观察还应保留延期与取消样本。只看推进项目会制造进度顺利的假象，而没有更新的项目不能被自动解释为失败；未取得、未披露与确实延后要分别表达。',
    ], [], { bullets: ['连接同批资源、部署与客户使用。', '确认收入兑现所需的验收和收费条件。', '保留推进之外的延期与取消样本。'] }),
    section('limits', '08 / 边界与比较', '结论只覆盖已有证据的范围', [
      '本版缺少项目对应表、代表性客户总体、收入金额与市场价格，因而不能确认部署速度或投资收益。其截止也不同于 North v2，比较时不能假定双方已读取同一批材料。',
      '所有摘录为虚构演示，方法期限属于命名 fixture。版本保留帮助读者追踪假设变化，不代表系统已经实现真实研究或发布治理。',
    ]),
  ],
};

const microsoftNorthV1 = {
  version: 'v1', publicationId: 'demo-pub-microsoft-north-v1',
  publishedAt: '2026-09-26', cutoff: '2026-09-25', language: 'zh-CN',
  title: 'Microsoft：付费是起点，续用才是检验',
  subtitle: 'North · 质量成长 / 当前正式演示报告',
  summary: '演示采购线索显示试用向付费转化，但还没有完整续约周期与实际使用深度。North 关注付费能否持续，并明确保留一项无法取得的续约证据，不借其他公司材料补齐。',
  verdict: '付费转化值得继续研究；留存、单位成本与估值输入不足，不能确认可持续回报。',
  status: 'current', reviewNote: '', affectedSections: [],
  sections: [
    section('business', '01 / 业务背景', '企业采购之后，还要走进日常工作', [
      '这份虚构报告把 Microsoft 的企业软件与新增 AI 使用场景作为研究背景。已有客户关系可能提供接触新产品的机会，但用户接受、采购流程和日常使用仍是不同环节，不能从分发机会直接推导盈利。',
      '目前资料是演示采购摘要和使用记录，不包含真实分部财务、客户总体或价格。业务介绍只定义研究问题，不声称已验证客户基础能带来多少新增收入。',
    ], ['demo-ms-business']),
    section('thesis', '02 / 核心判断', '长期价值取决于续用质量', [
      'North 的核心假设是：若客户在购买后持续使用，并愿意在完整周期结束时续约，新增产品才可能形成稳定收入。付费席位的存在只完成了第一步，闲置、低频使用或依赖优惠都可能削弱这一假设。',
      '因此，本版把试用转付费和长期留存分开表达。新的采购线索支持商业化路径开始被验证，但尚不足以支持持续回报已经形成的结论。',
    ], ['demo-ms-paid']),
    section('support', '03 / 正向证据', '真实使用前，需要先确认采购口径', [
      '演示摘要提到有客户从试用进入付费席位采购。North 认为这比兴趣调查更接近商业化，但还需要确认采购覆盖、优惠条件以及席位是否投入日常使用。',
      '不同部门的采购、试点扩围和全公司部署不能合并统计。如果后续证据能够在同批客户中连接采购、使用与续约，商业化判断才会获得更完整支持。',
    ], ['demo-ms-paid']),
    section('risk', '04 / 反证与材料缺口', '续约记录无法取得，结论停在这里', [
      '本演示刻意保留一条不可用的续约记录，以呈现真实产品需要面对的资料缺失状态。现有摘要不足以说明客户是否经过完整续约周期，不能用采购成功反推留存，也不能借 Alphabet 的客户材料作为补证。',
      '缺失并不等于客户不续约，更不代表研究已被否定。它只限制当前结论：可以讨论转化线索，不能确认收入持续性；读者打开该引用时应看到明确的不可用说明。',
    ], ['demo-ms-renewal-unavailable']),
    section('valuation', '05 / 估值条件', '缺少续用与成本，不能给出价格答案', [
      '本页没有行情供应源，也没有经核验的收入、服务成本和续约数据，不提供目标价或预期收益。付费转化具有研究意义，但尚不能据此判断当前市场价格便宜或昂贵。',
      '后续至少需要留存区间、使用强度、单位服务成本及现金回收口径。只有这些条件能一起审视，才有理由估计新增收入是否转化为对股东有价值的回报。',
    ], [], { table: { columns: ['条件', '证据状态'], rows: [['试用转付费', '有虚构演示摘要，范围有限'], ['完整周期续约', '演示来源不可用，不能验证'], ['成本与市场价格', '未接入，不能估值']] } }),
    section('judgment', '06 / 投资判断', '认可验证方向，保留买入条件', [
      'North 当前愿意继续跟踪商业化，但不把付费消息等同于回报确定。真正需要回答的是客户长期保留什么、为其支付多少，以及服务这些使用需要多少成本。',
      '本报告没有给出买入或仓位指令；是否配置仍要等待估值条件与组合取舍。Field 在本演示中尚未发布 Microsoft 报告，比较页应显示研究中，不能补入另一位 Manager 的文本。',
    ]),
    section('watch', '07 / 观察计划', '围绕同批客户检查三个节点', [
      '后续优先核对采购后的使用、完整周期续约和续约后的席位变化。三项资料需要覆盖同批客户和明确期间，才能分辨新增采购、席位闲置与留存质量。',
      '若续约材料仍不可用，就维持缺口并说明下一次可验证的条件；不因为页面被打开或个人标记已读而宣称验证完成，也不自动启动后台研究。',
    ], [], { bullets: ['采购的席位是否投入持续使用？', '完整周期之后是否续约，优惠条件是否改变？', '服务成本与收费能否在相同口径下对应？'] }),
    section('limits', '08 / 未知与责任', '每家公司只使用自己的证据', [
      '本版缺少续约全文、代表性客户总体、单位成本和市场价格。部分资料不可用的限制与受影响结论同时展示，不会被界面中的完整章节或“已发布”标识掩盖。',
      '所有内容均为虚构演示，发布仅表示这个原型可以阅读固定正文，不代表真实研究质量或投资批准。公司、Manager 和版本共同标识案例，任何未知身份都不能回退到这一份样例。',
    ], ['demo-ms-renewal-unavailable']),
  ],
};

export const research = {
  defaultRoute: { companyId: 'alphabet', managerId: 'north', version: 'v2', view: 'report' },
  companies: [
    { id: 'alphabet', name: 'Alphabet', ticker: 'GOOGL', website: 'https://www.abc.xyz/', tagline: '搜索 · 云 · AI' },
    { id: 'microsoft', name: 'Microsoft', ticker: 'MSFT', website: 'https://www.microsoft.com/', tagline: '企业软件 · 云 · AI' },
    { id: 'nvidia', name: 'NVIDIA', ticker: 'NVDA', website: 'https://www.nvidia.com/', tagline: '算力 · 芯片 · 生态' },
    { id: 'costco', name: 'Costco', ticker: 'COST', website: 'https://www.costco.com/', tagline: '会员零售 · 消费' },
    { id: 'arista', name: 'Arista', ticker: 'ANET', website: 'https://www.arista.com/', tagline: '网络设备 · 数据中心' },
    { id: 'eaton', name: 'Eaton', ticker: 'ETN', website: 'https://www.eaton.com/', tagline: '电力管理 · 基础设施' },
  ],
  managers: [
    {
      id: 'north', name: 'North', style: '质量成长', methodVersion: 'demo-quality-v1', horizon: '3—5 年 · 演示设定',
      description: '从长期现金创造能力、竞争力与投入回报出发。方法及期限仅是本原型的虚构设置，不构成系统默认策略。',
    },
    {
      id: 'field', name: 'Field', style: '产业观察', methodVersion: 'demo-industry-v1', horizon: '6—18 个月 · 演示设定',
      description: '沿需求、采购、部署与收入兑现追踪阶段线索。方法及期限仅是本原型的虚构设置，不能与长期方法直接比较胜负。',
    },
  ],
  cases: [
    { companyId: 'alphabet', managerId: 'north', currentVersion: 'v2', status: 'published', reports: [alphabetNorthV1, alphabetNorthV2] },
    { companyId: 'alphabet', managerId: 'field', currentVersion: 'v2', status: 'published', reports: [alphabetFieldV1, alphabetFieldV2] },
    { companyId: 'microsoft', managerId: 'north', currentVersion: 'v1', status: 'published', reports: [microsoftNorthV1] },
    { companyId: 'microsoft', managerId: 'field', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'nvidia', managerId: 'north', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'nvidia', managerId: 'field', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'costco', managerId: 'north', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'costco', managerId: 'field', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'arista', managerId: 'north', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'arista', managerId: 'field', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'eaton', managerId: 'north', currentVersion: null, status: 'researching', reports: [] },
    { companyId: 'eaton', managerId: 'field', currentVersion: null, status: 'researching', reports: [] },
  ],
  evidence: [
    {
      id: 'demo-alpha-business', companyId: 'alphabet', sourceTitle: '虚构演示 · 业务与资源安排简报', sourceType: '演示背景材料',
      publishedAt: '2026-09-15', availableAt: '2026-09-15', locator: '演示文档 A · 第 1 节，第 2—3 段',
      quote: '演示摘录：本研究场景分别观察既有服务的现金来源与新增计算能力的客户使用；两部分的规模、成本分摊与现金回收尚未提供。',
      context: ['这段文字是为界面编写的背景材料，并非公司公告或真实访谈。', '资源建设、客户使用与经营回报应分别核对，背景说明本身不证明盈利。'],
      limitation: '没有真实分部财务、金额或统一期间，只能用于说明研究范围。', language: 'zh-CN', availability: 'available', isDemo: true,
    },
    {
      id: 'demo-alpha-demand-early', companyId: 'alphabet', sourceTitle: '虚构演示 · 客户使用观察简报', sourceType: '演示客户记录',
      publishedAt: '2026-09-16', availableAt: '2026-09-17', locator: '演示文档 B · 第 2 节，第 4 段',
      quote: '演示摘录：部分试验项目在初次验证结束后继续运行；记录尚未给出总体客户覆盖、收费强度或完整续用周期。',
      context: ['继续运行是这个命名情景中的观察线索，不表示真实客户的行为。', '记录未对一次性兴趣、优惠使用与长期付费进行完整区分。'],
      limitation: '样本与收费口径缺失，不能推导收入增速或利润。', language: 'zh-CN', availability: 'excerpt', isDemo: true,
    },
    {
      id: 'demo-alpha-procurement-early', companyId: 'alphabet', sourceTitle: '虚构演示 · 资源准备记录', sourceType: '演示采购材料',
      publishedAt: '2026-09-17', availableAt: '2026-09-18', locator: '演示文档 C · 进度说明，第 2 段',
      quote: '演示摘录：资源准备安排已列入观察记录，但客户启用日期、部署验收和对应项目清单尚未包含在本次资料中。',
      context: ['本记录是固定演示数据，不存在真实采购金额。', '预订、交付、部署、启用和收入兑现的阶段定义不可互换。'],
      limitation: '无法确认建设与客户使用属于相同批次，也不能证明订单已变成收入。', language: 'zh-CN', availability: 'excerpt', isDemo: true,
    },
    {
      id: 'demo-alpha-use-later', companyId: 'alphabet', sourceTitle: '虚构演示 · 需求与建设联合简报', sourceType: '演示更新简报',
      publishedAt: '2026-09-24', availableAt: '2026-09-24', locator: '演示文档 D · 客户使用部分，第 2—3 段',
      quote: '演示摘录：部分项目从短期试验进入持续运行，并出现重复使用；客户总体、收费条件与新增计算资源的对应关系仍未披露。',
      context: ['本条描述客户使用事项；同一份演示简报另有建设事项，两者不应合成一个事件。', '重复使用对需求存在提供有限支持，对利润率与投入回报没有直接证明力。'],
      limitation: '不含客户总体与统一收费数据；不能确认新增资源是否服务于这些客户。', language: 'zh-CN', availability: 'available', isDemo: true,
    },
    {
      id: 'demo-alpha-build-later', companyId: 'alphabet', sourceTitle: '虚构演示 · 需求与建设联合简报', sourceType: '演示更新简报',
      publishedAt: '2026-09-24', availableAt: '2026-09-24', locator: '演示文档 D · 建设安排部分，第 6—7 段',
      quote: '演示摘录：观察情景中的扩建安排增加，建设投用与客户迁移可能分批发生；当前没有完整的项目对应和成本桥接材料。',
      context: ['本条描述建设事项，与同源客户使用记录属于不同事件。', '增加建设可能用于未来需求，也可能产生较长空置期；资料不能判定哪一种结果将发生。'],
      limitation: '没有项目金额、投产进度与利用率，不能计算投资回报。', language: 'zh-CN', availability: 'available', isDemo: true,
    },
    {
      id: 'demo-alpha-cost-gap', companyId: 'alphabet', sourceTitle: '虚构演示 · 成本桥接摘要', sourceType: '演示材料摘录',
      publishedAt: '2026-09-25', availableAt: '2026-09-26', locator: '演示文档 E · 可用摘要，第 1 段',
      quote: '演示摘录：当前摘要不能逐项连接建设支出、设备投用、服务成本与客户收费，回报兑现的时间差仍需补充资料。',
      context: ['此处仅提供专门编写的摘要，没有可展开的完整原件。', '它用于标明研究边界，不是“成本恶化”或“需求消失”的证据。'],
      limitation: '仅摘录可用；缺少完整财务口径，无法核验单位经济性。', language: 'zh-CN', availability: 'excerpt', isDemo: true,
    },
    {
      id: 'demo-ms-business', companyId: 'microsoft', sourceTitle: '虚构演示 · 企业软件使用背景', sourceType: '演示背景材料',
      publishedAt: '2026-09-20', availableAt: '2026-09-20', locator: '演示文档 M · 第 1 节，第 1—2 段',
      quote: '演示摘录：已有客户关系能够提供接触新产品的机会；采购、实际使用与续约分别发生，不能将其中一项替代其余环节。',
      context: ['这是一份用于 Microsoft 演示案例的范围说明，不是公司披露。', '没有真实客户总体、分部数据或经营金额。'],
      limitation: '只能定义研究问题，不能量化业务贡献。', language: 'zh-CN', availability: 'available', isDemo: true,
    },
    {
      id: 'demo-ms-paid', companyId: 'microsoft', sourceTitle: '虚构演示 · 企业采购观察摘要', sourceType: '演示客户记录',
      publishedAt: '2026-09-23', availableAt: '2026-09-24', locator: '演示文档 N · 采购阶段，第 3 段',
      quote: '演示摘录：部分试用客户开始购买付费席位；采购覆盖、优惠条件和日常使用深度尚未完整记录，也未覆盖完整续约周期。',
      context: ['本材料仅对应 Microsoft 的虚构案例，不可用于另一家公司。', '付费转化支持商业化路径的研究，但并不证明长期留存或盈利。'],
      limitation: '样本有限，缺少续约与单位成本，不足以推导回报。', language: 'zh-CN', availability: 'excerpt', isDemo: true,
    },
    {
      id: 'demo-ms-renewal-unavailable', companyId: 'microsoft', sourceTitle: '虚构演示 · 完整周期续约记录（不可用）', sourceType: '演示缺失材料',
      publishedAt: '2026-09-24', availableAt: '2026-09-25', locator: '演示文档 O · 请求的续约记录，无可用正文',
      quote: '', context: [],
      limitation: '固定失败场景：资料正文不可用，尚不能验证完整周期续约。保留缺口，不加载其他公司的材料，也不把不可用解释为续约失败。',
      language: 'zh-CN', availability: 'unavailable', isDemo: true,
    },
  ],
  events: [
    {
      id: 'demo-event-alpha-investment', companyId: 'alphabet', date: '2026-09-26', kind: 'risk',
      title: '扩建与成本缺口，使回报时间需要重新检验',
      summary: '同一投入回报事项由建设安排和成本摘要共同支持，按一个事件计数。',
      reason: '直接触及旧版利润兑现时间与估值条件，且项目和成本资料仍不完整。',
      before: 'North v1 暂时假定投入高峰与需求爬坡可以逐步衔接。',
      after: 'North v2 撤回乐观时间假设；Field v2 继续等待建设与客户启用的对应。',
      affectedCases: [{ managerId: 'north', version: 'v1', sectionId: 'economics' }, { managerId: 'north', version: 'v2', sectionId: 'economics' }, { managerId: 'field', version: 'v2', sectionId: 'constraints' }],
      evidenceIds: ['demo-alpha-build-later', 'demo-alpha-cost-gap'], unresolved: true,
    },
    {
      id: 'demo-event-alpha-usage', companyId: 'alphabet', date: '2026-09-24', kind: 'support',
      title: '持续运行线索，为需求方向补充支持',
      summary: '与扩建事项来自同份演示简报，但对应不同判断，保留独立事件。',
      reason: '对需求存在提供新增支持，尚不能单独证明利润或兑现速度。',
      before: '已有记录主要说明试验结束后的继续运行，覆盖范围有限。',
      after: '两位 Manager 分别更新需求判断，同时保留收费、样本与项目对应缺口。',
      affectedCases: [{ managerId: 'north', version: 'v2', sectionId: 'support' }, { managerId: 'field', version: 'v2', sectionId: 'signals' }],
      evidenceIds: ['demo-alpha-use-later'], unresolved: true,
    },
    {
      id: 'demo-event-ms-paid', companyId: 'microsoft', date: '2026-09-24', kind: 'support',
      title: '试用转付费，商业化路径向前一步',
      summary: '付费采购线索支持继续研究，但不能代替持续使用与续约。',
      reason: '影响 North 对商业化路径的判断，尚不构成留存或回报验证。',
      before: '现有材料不足以确认试用需求已进入付费。',
      after: 'North v1 接受有限的转化线索，同时明确保留长期续用限制。',
      affectedCases: [{ managerId: 'north', version: 'v1', sectionId: 'support' }],
      evidenceIds: ['demo-ms-paid'], unresolved: true,
    },
    {
      id: 'demo-event-ms-renewal', companyId: 'microsoft', date: '2026-09-25', kind: 'watch',
      title: '续约材料不可用，收入持续性仍有缺口',
      summary: '资料不可用会限制判断，但不能解释为续约失败。',
      reason: '直接限制对长期留存的推断，阅读或标记已读不消除该缺口。',
      before: '需要完整周期续约记录来验证付费之后的留存。',
      after: 'North v1 保留这一限制，不使用其他公司或 Manager 的材料补齐。',
      affectedCases: [{ managerId: 'north', version: 'v1', sectionId: 'risk' }],
      evidenceIds: ['demo-ms-renewal-unavailable'], unresolved: true,
    },
  ],
};

/** Exact, explicit identity lookup. Missing or unknown scope is never substituted. */
export function findCase(companyId, managerId) {
  return research.cases.find(item => item.companyId === companyId && item.managerId === managerId) ?? null;
}

/** Version is required, including when a case has only one published report. */
export function findReport(companyId, managerId, version) {
  return findCase(companyId, managerId)?.reports.find(report => report.version === version) ?? null;
}

export function findEvidence(id) {
  return research.evidence.find(item => item.id === id) ?? null;
}

/** Validate fixture identity and references; accepts a separate fixture for contract tests. */
export function validateResearch(data = research) {
  const requireValue = (ok, message) => { if (!ok) throw new Error(`Research fixture: ${message}`); };
  const text = value => typeof value === 'string' && value.trim().length > 0;
  const strings = value => Array.isArray(value) && value.every(text);
  const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().startsWith(value);
  const unique = (items, label, key = item => item.id) => {
    requireValue(Array.isArray(items), `${label} must be an array`);
    const seen = new Set();
    for (const item of items) {
      const id = key(item);
      requireValue(text(id) && !seen.has(id), `${label} identity is missing or duplicated: ${id}`);
      seen.add(id);
    }
    return seen;
  };
  requireValue(data && typeof data === 'object', 'dataset is required');
  const companies = unique(data.companies, 'company');
  const managers = unique(data.managers, 'manager');
  unique(data.cases, 'case', item => `${item.companyId}/${item.managerId}`);
  const evidenceIds = unique(data.evidence, 'evidence');
  unique(data.events, 'event');
  const evidenceById = new Map(data.evidence.map(item => [item.id, item]));
  const casesById = new Map(data.cases.map(item => [`${item.companyId}/${item.managerId}`, item]));
  const publicationIds = new Set();
  for (const company of data.companies) {
    requireValue(['name', 'ticker', 'website', 'tagline'].every(key => text(company[key])), `company fields are incomplete: ${company.id}`);
  }
  for (const manager of data.managers) {
    requireValue(['name', 'style', 'methodVersion', 'horizon', 'description'].every(key => text(manager[key])), `manager fields are incomplete: ${manager.id}`);
  }
  for (const evidence of data.evidence) {
    requireValue(companies.has(evidence.companyId), `evidence company is unknown: ${evidence.id}`);
    requireValue(evidence.isDemo === true && evidence.language === 'zh-CN', `evidence demo identity is invalid: ${evidence.id}`);
    requireValue(['available', 'excerpt', 'unavailable'].includes(evidence.availability), `evidence availability is invalid: ${evidence.id}`);
    requireValue(['sourceTitle', 'sourceType', 'locator', 'limitation'].every(key => text(evidence[key])), `evidence metadata is incomplete: ${evidence.id}`);
    requireValue(evidence.sourceTitle.startsWith('虚构演示'), `evidence source must be visibly fictional: ${evidence.id}`);
    requireValue(date(evidence.publishedAt) && date(evidence.availableAt) && evidence.availableAt >= evidence.publishedAt, `evidence dates are invalid: ${evidence.id}`);
    requireValue(strings(evidence.context), `evidence context is invalid: ${evidence.id}`);
    requireValue(evidence.availability === 'unavailable' ? evidence.quote === '' && evidence.context.length === 0 : text(evidence.quote) && evidence.quote.startsWith('演示摘录：'), `evidence quote does not match availability: ${evidence.id}`);
  }
  for (const item of data.cases) {
    const identity = `${item.companyId}/${item.managerId}`;
    requireValue(companies.has(item.companyId) && managers.has(item.managerId), `case identity is unknown: ${identity}`);
    unique(item.reports, `report in ${identity}`, report => report.version);
    requireValue(['published', 'researching'].includes(item.status), `case status is invalid: ${identity}`);
    if (item.status === 'researching') {
      requireValue(item.currentVersion === null && item.reports.length === 0, `unpublished case must not expose reports: ${identity}`);
      continue;
    }
    requireValue(text(item.currentVersion) && item.reports.some(report => report.version === item.currentVersion), `current version is missing: ${identity}`);
    for (const report of item.reports) {
      const label = `${identity}/${report.version}`;
      requireValue(text(report.publicationId) && !publicationIds.has(report.publicationId), `publication identity is duplicated or missing: ${label}`);
      publicationIds.add(report.publicationId);
      requireValue(report.language === 'zh-CN' && ['current', 'review', 'historical'].includes(report.status), `report status or language is invalid: ${label}`);
      requireValue(date(report.publishedAt) && date(report.cutoff) && report.cutoff <= report.publishedAt, `report dates are invalid: ${label}`);
      requireValue(['title', 'subtitle', 'summary', 'verdict'].every(key => text(report[key])), `report text is incomplete: ${label}`);
      requireValue(report.status !== 'current' || report.version === item.currentVersion, `current report disagrees with case version: ${label}`);
      requireValue(report.version !== item.currentVersion || report.status !== 'historical', `current case points to historical report: ${label}`);
      const sections = unique(report.sections, `section in ${label}`);
      requireValue(report.sections.length > 0 && typeof report.reviewNote === 'string' && strings(report.affectedSections), `report structure is incomplete: ${label}`);
      requireValue(report.affectedSections.every(id => sections.has(id)) && new Set(report.affectedSections).size === report.affectedSections.length, `affected section is invalid: ${label}`);
      requireValue(report.status !== 'review' || text(report.reviewNote) && report.affectedSections.length > 0, `review report must state its affected sections: ${label}`);
      for (const part of report.sections) {
        requireValue(text(part.kicker) && text(part.title) && strings(part.paragraphs) && part.paragraphs.length > 0 && strings(part.citations), `section text is incomplete: ${label}/${part.id}`);
        requireValue(new Set(part.citations).size === part.citations.length, `section citation is duplicated: ${label}/${part.id}`);
        requireValue(part.bullets === undefined || strings(part.bullets), `section bullets are invalid: ${label}/${part.id}`);
        if (part.table !== undefined) requireValue(strings(part.table.columns) && part.table.columns.length > 0 && Array.isArray(part.table.rows) && part.table.rows.every(row => strings(row) && row.length === part.table.columns.length), `section table shape is invalid: ${label}/${part.id}`);
        for (const reference of part.citations) {
          requireValue(evidenceIds.has(reference), `missing citation: ${label}/${part.id}/${reference}`);
          const evidence = evidenceById.get(reference);
          requireValue(evidence.companyId === item.companyId, `cross-company citation: ${label}/${reference}`);
          requireValue(evidence.availableAt <= report.cutoff, `citation exceeds report cutoff: ${label}/${reference}`);
        }
      }
    }
  }
  for (const event of data.events) {
    requireValue(companies.has(event.companyId), `event company is unknown: ${event.id}`);
    requireValue(date(event.date) && ['risk', 'support', 'watch'].includes(event.kind) && typeof event.unresolved === 'boolean', `event status is invalid: ${event.id}`);
    requireValue(['title', 'summary', 'reason', 'before', 'after'].every(key => text(event[key])), `event text is incomplete: ${event.id}`);
    requireValue(strings(event.evidenceIds) && event.evidenceIds.length > 0 && new Set(event.evidenceIds).size === event.evidenceIds.length, `event evidence list is invalid: ${event.id}`);
    for (const id of event.evidenceIds) {
      requireValue(evidenceIds.has(id) && evidenceById.get(id).companyId === event.companyId, `missing or cross-company event evidence: ${event.id}/${id}`);
      requireValue(evidenceById.get(id).availableAt <= event.date, `event evidence exceeds event date: ${event.id}/${id}`);
    }
    requireValue(Array.isArray(event.affectedCases) && event.affectedCases.length > 0, `event case references are missing: ${event.id}`);
    unique(event.affectedCases, `event case link in ${event.id}`, ref => `${ref.managerId}/${ref.version}/${ref.sectionId}`);
    for (const ref of event.affectedCases) {
      const linkedCase = casesById.get(`${event.companyId}/${ref.managerId}`);
      const report = linkedCase?.reports.find(item => item.version === ref.version);
      requireValue(report && report.sections.some(part => part.id === ref.sectionId), `event refers to unknown case, version, or section: ${event.id}`);
    }
  }
  const route = data.defaultRoute;
  requireValue(route && route.view === 'report', 'named demo route is required');
  const first = casesById.get(`${route.companyId}/${route.managerId}`);
  requireValue(first?.reports.some(report => report.version === route.version), 'named demo route does not resolve');
  return data;
}
