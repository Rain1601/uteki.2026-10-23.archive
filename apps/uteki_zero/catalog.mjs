// Named demo catalog. A report has one company and one Manager; its versions
// belong to that report, rather than being reports of the company/Manager pair.
// No data below represents live research, holdings, prices, or publication work.
import { research } from './research.mjs';

const clone = value => structuredClone(value);
const pairKey = (companyId, managerId) => JSON.stringify([companyId, managerId]);
const mainReportMap = new Map([
  [pairKey('alphabet', 'north'), 'alpha-north-main'],
  [pairKey('alphabet', 'field'), 'alpha-field-main'],
  [pairKey('microsoft', 'north'), 'ms-north-main'],
]);

function namedMain(companyId, managerId, title) {
  const id = mainReportMap.get(pairKey(companyId, managerId));
  const source = research.cases.find(item => item.companyId === companyId && item.managerId === managerId);
  if (!id || !source || source.status !== 'published') throw new Error('Named demo main report is missing');
  return { id, companyId, managerId, kind: 'main', title, currentVersion: source.currentVersion, versions: clone(source.reports) };
}

const section = (id, kicker, title, paragraphs, citations = []) => ({ id, kicker, title, paragraphs, citations });
const cloudV1 = {
  version: 'v1', publicationId: 'demo-pub-alpha-north-cloud-v1',
  publishedAt: '2026-09-19', cutoff: '2026-09-18', language: 'zh-CN',
  title: '云业务专题：持续使用之后，谁来付费？',
  subtitle: 'North · 云业务专题 / 完整历史报告 · 虚构演示',
  summary: '本专题只检验云服务需求的质量。试验结束后的继续运行值得关注，但免费额度、客户覆盖与重复付费之间尚未形成完整记录。',
  verdict: '需求信号成立于使用层面，尚不能确认商业回报。',
  status: 'historical', reviewNote: '', affectedSections: [],
  sections: [
    section('question', '01 / 研究问题', '从继续使用，到愿意持续付费', [
      '本专题把研究范围缩小到云服务客户的使用质量。公司整体报告讨论现金回报与投入节奏，这里则只追问一个前置问题：试验结束后仍在运行的项目，是客户主动保留的生产需求，还是优惠和迁移成本共同造成的暂时停留？',
      '演示记录没有客户总体或收费合同，因此无法计算转化率。研究先保留同一客户、同一产品和同一期间的对应要求，避免把不同样本的好消息拼成一条已经完成的商业化路径。',
    ], ['demo-alpha-demand-early']),
    section('signal', '02 / 已有线索', '继续运行提高了观察价值', [
      '部分试验项目结束初次验证后继续运行，使需求不再完全停留在产品兴趣。但运行可以包含低频调用、内部验证或优惠期延长，不能只凭项目存在判断付费强度，更不能由此推导公司的收入规模。',
      '相较寻找更多匿名案例，更有价值的下一步是补充原有客户的运行时长、使用频率与收费状态。只有样本可连续追踪，才有条件区分新增需求、存量迁移与短期试验。',
    ], ['demo-alpha-demand-early']),
    section('test', '03 / 反证条件', '优惠退出，是需要保留的检验', [
      '如果客户在退出优惠后明显减少使用，或者实际付费长期低于资源消耗，原先的需求信号就需要重新解释。当前没有这些资料，所以本版既不把继续运行认定为成功，也不把缺少收费记录认定为客户拒绝付费。',
      '本专题还需记录停止使用的项目。只观察留下来的客户，会让需求显得比真实情况更稳定。建设和采购信息可以说明供给准备，却不能代替上述客户侧检验。',
    ], ['demo-alpha-procurement-early']),
    section('next', '04 / 结论与边界', '先把需求质量查清，再讨论规模', [
      'North 保留这一专题，等待同批客户的使用与付费对应材料。当前判断只覆盖观察方向，不外推收入增速、利润率、目标价或组合仓位；它也不替代公司整体报告中的成本与估值分析。',
      '本版为虚构演示。后续即使形成新结论，也应更新这份云业务专题的版本，保留本版原文和截止；公司整体报告可以继续按自身研究节奏发布，二者版本号互不绑定。',
    ]),
  ],
};

const cloudV2 = {
  version: 'v2', publicationId: 'demo-pub-alpha-north-cloud-v2',
  publishedAt: '2026-09-28', cutoff: '2026-09-27', language: 'zh-CN',
  title: '云业务专题：重复使用增加，付费质量仍待验证',
  subtitle: 'North · 云业务专题 / 当前正式演示报告',
  summary: '新增重复使用线索让需求观察更具体，但仍缺少同批客户的收费和优惠退出记录。本专题更新使用判断，继续保留付费质量这一独立缺口。',
  verdict: '持续需求得到有限支持；不能把重复使用等同于可持续利润。',
  status: 'current', reviewNote: '', affectedSections: [],
  sections: [
    section('question', '01 / 问题延续', '本次只更新需求质量这条线', [
      '相对 v1，演示材料开始描述项目从短期试验转为持续运行，并出现重复使用。本专题因此可以更具体地追踪需求持续性，但核心问题仍是客户是否愿意长期支付足以覆盖服务成本的价格。使用与付费是相邻的两步，不能合并。',
      '本版与公司整体报告共用部分来源，却回答不同问题。这里的结论只覆盖客户侧需求，不因整体报告更新到 v2 就自动变化，也不要求两份报告使用相同的发布日或信息截止。',
    ], ['demo-alpha-use-later']),
    section('signal', '02 / 新增支持', '重复使用，比单次保留更进一步', [
      '新的演示记录减少了“项目只是试验残留”的一种可能解释。若同批项目在多个观察时点持续活跃，研究者就能进一步核对工作负载是否进入日常流程，而不是只依赖一次访谈或一次上线公告。',
      '但目前没有明确的客户总体与收费条件，无法计算留存、付费转化或净收入变化。North 因此只上调需求观察的具体程度，未提高对利润兑现的确定性，也未把有限样本外推到全部客户。',
    ], ['demo-alpha-use-later']),
    section('payment', '03 / 尚未验证', '收费与服务成本之间仍缺一座桥', [
      '成本摘要没有把建设支出、资源使用和客户收费逐项对应。即便客户确实持续使用，也可能因为定价较低、优惠较长或资源成本较高而没有产生理想回报。当前材料无法选择其中任何一种解释。',
      '下一步应取得同期间的客户收费与服务成本，并明确哪些属于维持现有服务、哪些属于未来扩张。缺失材料要继续显示为缺口，不能被几条正向需求线索抵消。',
    ], ['demo-alpha-cost-gap']),
    section('next', '04 / 结论与后续', '下一份证据应连接使用、收费与成本', [
      '本次把需求判断推进到重复使用这一层，继续等待付费质量验证。优先观察同批客户退出优惠后的行为，再核对服务成本；如果使用停止或收费无法覆盖成本，应回到本专题重新检验原因。',
      '当前结论不提供目标价或仓位，也不自动改写 North 的整体公司判断。所有段落与引文均为虚构演示。v1 原文按旧截止保留，读者可以在这份专题内部查看变化，而无需将它与另一份报告混为一谈。',
    ]),
  ],
};

const capacityV1 = {
  version: 'v1', publicationId: 'demo-pub-alpha-field-capacity-v1',
  publishedAt: '2026-09-27', cutoff: '2026-09-26', language: 'zh-CN',
  title: '产能专题：扩建之后，还差哪些交付节点？',
  subtitle: 'Field · 产能与部署专题 / 当前正式演示报告',
  summary: '本专题按资源准备、部署、验收和客户启用拆解扩建线索。现有材料缺少同批项目对应关系，不能确认新增能力何时转化为可收费服务。',
  verdict: '扩建安排增加了可追踪节点，尚未证明交付加速。',
  status: 'current', reviewNote: '', affectedSections: [],
  sections: [
    section('scope', '01 / 研究范围', '把一条扩建消息拆成四个节点', [
      'Field 将这份专题限定在供给侧交付进度。资源准备、设备部署、项目验收和客户启用是四种不同状态，扩建公告可能只证明第一种；若把它直接解释为收入增加，就跳过了最需要验证的中间过程。',
      '本专题关注节点顺序和项目对应，整体报告则继续讨论这些变化对公司判断的意义。二者可以使用同一份来源，但章节、结论和版本独立保存，避免一项局部进展被误认为全部研究已经更新。',
    ], ['demo-alpha-build-later']),
    section('ready', '02 / 现有证据', '准备中的资源，还不是已启用的项目', [
      '早期资源记录包含准备安排，新材料又增加扩建线索，两者共同提高了进一步核对进度的必要性。但目前无法确认两段材料是否涉及同一批项目，更不能从出现先后推导真实的建设速度。',
      '可用记录应至少包括项目范围、原定节点和实际状态。观察不应只保留按期推进的项目，还需列出延期、取消与信息缺失，才能避免从成功样本中得出过于顺利的部署印象。',
    ], ['demo-alpha-procurement-early', 'demo-alpha-build-later']),
    section('handoff', '03 / 关键缺口', '客户使用与新增能力还没有对应起来', [
      '另一条线索描述部分客户重复使用，但未提供这些客户与新增计算资源的对应关系。供给端和需求端各有进展，不能证明新增能力恰好服务于这些客户；它们也可能来自不同产品或不同观察范围。',
      'Field 暂不把两端信息拼成已贯通的交付链。下一份材料应补充同批项目验收、启用和客户迁移记录，解释延迟发生在哪一步；只有这样，阶段变化才具备可复核的依据。',
    ], ['demo-alpha-use-later']),
    section('watch', '04 / 后续观察', '用节点证据检验节奏，而不是消息数量', [
      '本专题继续跟踪明确的项目对应关系。如果取得同批次启用与收费记录，可以进一步讨论兑现节奏；如果只出现更多建设消息，应保持当前缺口，不把新闻密度当成进度证据。',
      '目前没有真实项目金额、利用率或行情，不能计算收益与合理价格。本文属于虚构演示；其 v1 是独立专题的首次发布，并不意味着 Field 的公司整体研究回到 v1，也不产生任何组合动作。',
    ]),
  ],
};

export const workspace = {
  defaultRoute: { page: 'index', entry: 'companies', objectId: 'alphabet', view: 'research' },
  defaultEntries: { companies: 'alphabet', managers: 'north' },
  companies: clone(research.companies), managers: clone(research.managers),
  coverage: research.cases.map(({ companyId, managerId, status }) => ({ companyId, managerId, status })),
  reports: [
    namedMain('alphabet', 'north', 'Alphabet 公司研究'),
    namedMain('alphabet', 'field', 'Alphabet 公司研究'),
    namedMain('microsoft', 'north', 'Microsoft 公司研究'),
    { id: 'alpha-north-cloud', companyId: 'alphabet', managerId: 'north', kind: 'topic', title: '云业务：持续使用与付费质量', currentVersion: 'v2', versions: [cloudV1, cloudV2] },
    { id: 'alpha-field-capacity', companyId: 'alphabet', managerId: 'field', kind: 'topic', title: '产能：扩建与交付节点', currentVersion: 'v1', versions: [capacityV1] },
  ],
  evidence: clone(research.evidence),
  events: [
    ...research.events.map(({ affectedCases, ...event }) => ({
      ...clone(event), affectedReports: affectedCases.map(({ managerId, version, sectionId }) => {
        const reportId = mainReportMap.get(pairKey(event.companyId, managerId));
        if (!reportId) throw new Error('Named demo event has no main report mapping');
        return { reportId, version, sectionId };
      }),
    })),
    {
      id: 'demo-event-alpha-cloud-payment', companyId: 'alphabet', date: '2026-09-26', kind: 'watch',
      title: '重复使用之后，付费与成本仍没有接上',
      summary: '云业务专题把需求支持与付费质量拆开，明确后续所需的客户和成本对应材料。',
      reason: '这项缺口直接限制云业务专题的利润推断；它不等于需求失败，也不替代整体投入回报事件。',
      before: '专题 v1 主要等待持续使用与优惠退出的可追踪记录。',
      after: '专题 v2 接受重复使用线索，但仍无法把使用连接到收费及服务成本。',
      evidenceIds: ['demo-alpha-use-later', 'demo-alpha-cost-gap'], unresolved: true,
      affectedReports: [{ reportId: 'alpha-north-cloud', version: 'v2', sectionId: 'payment' }],
    },
  ],
  portfolios: research.managers.map(({ id }) => ({
    managerId: id, status: 'unavailable', reason: '尚未接入这位 Manager 的持仓、交易与收益记录；研究报告不代表实际持仓。',
  })),
};

export function findDocument(reportId, data = workspace) {
  return data.reports.find(report => report.id === reportId) ?? null;
}
export function findVersion(reportId, version, data = workspace) {
  return findDocument(reportId, data)?.versions.find(item => item.version === version) ?? null;
}
export function findCoverage(companyId, managerId, data = workspace) {
  return data.coverage.find(item => item.companyId === companyId && item.managerId === managerId) ?? null;
}
export function findEvidence(id, data = workspace) {
  return data.evidence.find(item => item.id === id) ?? null;
}

/** Validate the explicit catalog contract, including independently supplied data. */
export function validateWorkspace(data = workspace) {
  const requireValue = (ok, message) => { if (!ok) throw new Error(`Workspace catalog: ${message}`); };
  const text = value => typeof value === 'string' && value.trim().length > 0;
  const strings = value => Array.isArray(value) && value.every(text);
  const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().startsWith(value);
  const unique = (items, label, key = item => item.id) => {
    requireValue(Array.isArray(items), `${label} must be an array`);
    const seen = new Set();
    for (const item of items) {
      requireValue(item && typeof item === 'object', `${label} item is invalid`);
      const id = key(item);
      requireValue(text(id) && !seen.has(id), `${label} identity is missing or duplicated: ${id}`);
      seen.add(id);
    }
    return seen;
  };
  requireValue(data && typeof data === 'object', 'dataset is required');
  const companies = unique(data.companies, 'company');
  const managers = unique(data.managers, 'manager');
  unique(data.coverage, 'coverage', item => pairKey(item.companyId, item.managerId));
  const reportIds = unique(data.reports, 'report');
  const evidenceIds = unique(data.evidence, 'evidence');
  unique(data.events, 'event');
  unique(data.portfolios, 'portfolio', item => item.managerId);
  for (const company of data.companies) requireValue(['name', 'ticker', 'website', 'tagline'].every(key => text(company[key])), `company metadata is incomplete: ${company.id}`);
  for (const manager of data.managers) requireValue(['name', 'style', 'methodVersion', 'horizon', 'description'].every(key => text(manager[key])), `manager metadata is incomplete: ${manager.id}`);
  for (const item of data.coverage) {
    requireValue(companies.has(item.companyId) && managers.has(item.managerId), 'coverage scope is unknown');
    requireValue(['published', 'researching'].includes(item.status), 'coverage status is invalid');
    const reports = data.reports.filter(report => report.companyId === item.companyId && report.managerId === item.managerId);
    requireValue(item.status === 'published' ? reports.length > 0 : reports.length === 0, 'coverage status disagrees with published reports');
  }
  for (const evidence of data.evidence) {
    requireValue(companies.has(evidence.companyId), `evidence company is unknown: ${evidence.id}`);
    requireValue(evidence.isDemo === true && evidence.language === 'zh-CN', `evidence demo identity is invalid: ${evidence.id}`);
    requireValue(['available', 'excerpt', 'unavailable'].includes(evidence.availability), `evidence availability is invalid: ${evidence.id}`);
    requireValue(['sourceTitle', 'sourceType', 'locator', 'limitation'].every(key => text(evidence[key])) && evidence.sourceTitle.startsWith('虚构演示'), `evidence metadata must identify the fictional source: ${evidence.id}`);
    requireValue(date(evidence.publishedAt) && date(evidence.availableAt) && evidence.availableAt >= evidence.publishedAt, `evidence dates are invalid: ${evidence.id}`);
    requireValue(strings(evidence.context), `evidence context is invalid: ${evidence.id}`);
    requireValue(evidence.availability === 'unavailable' ? evidence.quote === '' && evidence.context.length === 0 : text(evidence.quote) && evidence.quote.startsWith('演示摘录：'), `evidence quote does not match availability: ${evidence.id}`);
  }
  const publications = new Set();
  const mainPairs = new Set();
  for (const report of data.reports) {
    const pair = pairKey(report.companyId, report.managerId);
    requireValue(companies.has(report.companyId) && managers.has(report.managerId) && findCoverage(report.companyId, report.managerId, data), `report ownership is unknown: ${report.id}`);
    requireValue(['main', 'topic'].includes(report.kind) && text(report.title), `report metadata is invalid: ${report.id}`);
    if (report.kind === 'main') {
      requireValue(!mainPairs.has(pair), `multiple main reports for the same company and Manager: ${pair}`);
      mainPairs.add(pair);
    }
    unique(report.versions, `version in ${report.id}`, version => version.version);
    requireValue(text(report.currentVersion) && findVersion(report.id, report.currentVersion, data), `current version is missing: ${report.id}`);
    for (const version of report.versions) {
      const label = `${report.id}/${version.version}`;
      requireValue(text(version.publicationId) && !publications.has(version.publicationId), `publication identity is missing or duplicated: ${label}`);
      publications.add(version.publicationId);
      requireValue(version.language === 'zh-CN' && ['current', 'review', 'historical'].includes(version.status), `version status or language is invalid: ${label}`);
      requireValue(date(version.publishedAt) && date(version.cutoff) && version.cutoff <= version.publishedAt, `version dates are invalid: ${label}`);
      requireValue(['title', 'subtitle', 'summary', 'verdict'].every(key => text(version[key])), `version text is incomplete: ${label}`);
      requireValue(version.status !== 'current' || version.version === report.currentVersion, `current status disagrees with report pointer: ${label}`);
      requireValue(version.version !== report.currentVersion || version.status !== 'historical', `current pointer targets historical version: ${label}`);
      const sections = unique(version.sections, `section in ${label}`);
      requireValue(version.sections.length > 0 && typeof version.reviewNote === 'string' && strings(version.affectedSections), `version structure is incomplete: ${label}`);
      requireValue(version.affectedSections.every(id => sections.has(id)) && new Set(version.affectedSections).size === version.affectedSections.length, `affected section is invalid: ${label}`);
      requireValue(version.status !== 'review' || text(version.reviewNote) && version.affectedSections.length > 0, `review requires a note and affected sections: ${label}`);
      for (const part of version.sections) {
        requireValue(text(part.kicker) && text(part.title) && strings(part.paragraphs) && part.paragraphs.length > 0 && strings(part.citations), `section text is incomplete: ${label}/${part.id}`);
        requireValue(new Set(part.citations).size === part.citations.length, `section citation is duplicated: ${label}/${part.id}`);
        requireValue(part.bullets === undefined || strings(part.bullets), `section bullets are invalid: ${label}/${part.id}`);
        if (part.table !== undefined) requireValue(strings(part.table.columns) && part.table.columns.length > 0 && Array.isArray(part.table.rows) && part.table.rows.every(row => strings(row) && row.length === part.table.columns.length), `section table shape is invalid: ${label}/${part.id}`);
        for (const id of part.citations) {
          requireValue(evidenceIds.has(id), `citation is missing: ${label}/${id}`);
          const evidence = findEvidence(id, data);
          requireValue(evidence.companyId === report.companyId, `cross-company citation: ${label}/${id}`);
          requireValue(evidence.availableAt <= version.cutoff, `citation exceeds version cutoff: ${label}/${id}`);
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
      const evidence = findEvidence(id, data);
      requireValue(evidence && evidence.companyId === event.companyId, `missing or cross-company event evidence: ${event.id}/${id}`);
      requireValue(evidence.availableAt <= event.date, `event evidence exceeds event date: ${event.id}/${id}`);
    }
    unique(event.affectedReports, `event report link in ${event.id}`, ref => JSON.stringify([ref.reportId, ref.version, ref.sectionId]));
    requireValue(event.affectedReports.length > 0, `event report links are missing: ${event.id}`);
    for (const ref of event.affectedReports) {
      const report = findDocument(ref.reportId, data);
      const version = findVersion(ref.reportId, ref.version, data);
      requireValue(reportIds.has(ref.reportId) && report.companyId === event.companyId && version?.sections.some(part => part.id === ref.sectionId), `event report, version, section, or company is invalid: ${event.id}`);
    }
  }
  for (const portfolio of data.portfolios) requireValue(managers.has(portfolio.managerId) && portfolio.status === 'unavailable' && text(portfolio.reason), 'portfolio scope or unavailable state is invalid');
  const route = data.defaultRoute;
  requireValue(companies.has(data.defaultEntries?.companies) && managers.has(data.defaultEntries?.managers), 'named entry defaults do not resolve');
  requireValue(route?.page === 'index' && route.view === 'research' && (route.entry === 'companies' ? companies.has(route.objectId) : route.entry === 'managers' && managers.has(route.objectId)), 'named index route does not resolve');
  return data;
}
