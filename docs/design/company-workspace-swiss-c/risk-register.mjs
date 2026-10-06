// Named frontend scenario. Continuous issue identity is authored explicitly;
// it is never inferred from similar titles, PM responses or allocation weights.
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';
import { portfolioDecisionFixture, validatePortfolioDecisionFixture } from './portfolio-decisions.mjs';

const source = (companyId, reportId, version, sectionId, evidenceId) => ({ companyId, reportId, version, sectionId, evidenceId });
const review = (decisionId, reviewRiskId) => ({ decisionId, reviewRiskId });
const observation = (id, date, text, textEn, sources) => ({ id, date, text, textEn, sources });

export const riskRegisterFixture = {
  id: 'uteki-continuous-risk-scenarios', version: 'v1', asOf: '2026-09-30', isSimulated: true,
  label: '虚构风险样稿 · 非实盘', labelEn: 'Fictional risk scenarios · Not live trading',
  disclosure: '风险身份、跟踪状态和复查要求均为具名交互样稿，引用既有虚构报告与材料。决策之间的关联用于追踪同一问题，不构成连续账户、真实监控或已执行调仓；PM 已回应不代表风险已解决。',
  disclosureEn: 'Risk identities, tracking states and review requirements are named interaction examples citing existing fictional reports and material. Links between decisions track a question, not a continuous account, live monitoring or executed trades. A PM response does not resolve a risk.',
  featuredByManager: { north: 'north-shared-growth', field: 'field-delivery-chain' },
  risks: [
    {
      id: 'north-shared-growth', managerId: 'north', companyIds: ['alphabet', 'microsoft', 'nvidia'],
      title: '增长兑现的共同假设需要复核', titleEn: 'Review shared assumptions about growth delivery',
      status: 'needs_review', openedAt: '2026-09-30', updatedAt: '2026-09-30', isSimulated: true,
      summary: 'PM 已回应配置方案并缩小初稿增量；组合层面的共同暴露仍需单独复核，当前材料不足以量化。',
      summaryEn: 'The PM answered the allocation review and narrowed the draft increase. Portfolio-wide shared exposure still needs a separate review; current material cannot quantify it.',
      impact: '需要检验多家公司是否依赖相同的增长兑现条件。列出的公司是情景复查范围，不代表已证明相关性，也不推导组合损失。',
      impactEn: 'Test whether several companies rely on the same growth-delivery conditions. The companies define the scenario review scope, not established correlation or a quantified portfolio loss.',
      reviewTrigger: '补齐各公司的需求、投入回报和估值资料，再复核共同假设；对配置初稿的回应不替代这项组合检查。',
      reviewTriggerEn: 'Obtain demand, return-on-investment and valuation material for each company, then revisit shared assumptions. A response to the draft allocation does not replace this portfolio review.',
      decisionReviews: [review('north-20260930-allocation', 'north-common-assumption')],
      observations: [observation('north-shared-20260930', '2026-09-30',
        'Alphabet 报告将扩建与回报验证分开。这只说明该公司的证据边界，其他公司的共同暴露仍待逐一核对。',
        'The Alphabet report separates expansion from verification of returns. This establishes the evidence boundary for that company only; shared exposure across other companies remains to be examined.',
        [source('alphabet', 'alpha-north-main', 'v2', 'economics', 'demo-alpha-build-later')])],
      resolution: null,
    },
    {
      id: 'north-payment-quality', managerId: 'north', companyIds: ['alphabet'],
      title: '持续使用尚未连接到付费质量', titleEn: 'Continued usage is not yet linked to payment quality',
      status: 'monitoring', openedAt: '2026-09-29', updatedAt: '2026-09-29', isSimulated: true,
      summary: '本次决定维持配置，继续等待同期间的收费和服务成本对应材料。',
      summaryEn: 'The decision maintains the allocation while awaiting matched-period customer payments and service costs.',
      impact: '需求线索不能直接证明可持续利润；若依赖这条路径提出新的配置，需要保留当前缺口。',
      impactEn: 'Demand signals do not establish sustainable profit. Any new allocation proposal relying on this path must retain the evidence gap.',
      reviewTrigger: '取得同批客户、同期间的收费、优惠退出及服务成本记录后复查；使用停止也应触发重新研究。',
      reviewTriggerEn: 'Review when matched-customer and matched-period payment, promotion-exit and service-cost records arrive. Discontinued usage should also trigger renewed research.',
      decisionReviews: [review('north-20260929-hold', 'north-payment-gap')],
      observations: [observation('north-payment-20260929', '2026-09-29',
        '公司报告保留成本桥接缺口。现有摘录不能连接建设支出、投用、服务成本和收费，也没有证明成本恶化。',
        'The company report retains the cost-bridge gap. The excerpt cannot connect spending, commissioning, service costs and payments, and does not establish deteriorating costs.',
        [source('alphabet', 'alpha-north-main', 'v2', 'economics', 'demo-alpha-cost-gap')])],
      resolution: null,
    },
    {
      id: 'north-renewal-gap', managerId: 'north', companyIds: ['microsoft'],
      title: '完整周期续约资料仍不可用', titleEn: 'Full-cycle renewal records remain unavailable',
      status: 'monitoring', openedAt: '2026-09-27', updatedAt: '2026-09-27', isSimulated: true,
      summary: '本情景收窄 Microsoft 初稿配置；续约资料缺口继续保留，不能把不可用解释成续约失败。',
      summaryEn: 'This scenario narrows the Microsoft draft allocation. The renewal evidence gap remains; unavailable records do not establish failed renewals.',
      impact: '无法从采购线索推导长期续用和回报。该项是 Microsoft 的证据缺口，不能用另一公司的资料补齐。',
      impactEn: 'Procurement signals cannot establish long-term usage or returns. This is a Microsoft evidence gap and cannot be filled with another company’s material.',
      reviewTrigger: '取得同批客户的完整周期续约与成本资料后重新复查；资料仍不可用时继续显示缺口。',
      reviewTriggerEn: 'Review when full-cycle renewal and cost material for the same customers becomes available. Retain the gap while the material remains unavailable.',
      decisionReviews: [review('north-20260927-allocation', 'north-flexibility')],
      observations: [observation('north-renewal-20260927', '2026-09-27',
        '报告的风险章节引用了不可用的续约记录。此处保留该缺失状态，不提供虚构原文或量化损失。',
        'The report’s risk section cites unavailable renewal records. This retains that missing-source state without inventing source text or a quantified loss.',
        [source('microsoft', 'ms-north-main', 'v1', 'risk', 'demo-ms-renewal-unavailable')])],
      resolution: null,
    },
    {
      id: 'field-delivery-chain', managerId: 'field', companyIds: ['alphabet'],
      title: '部署、验收与客户启用仍未对应', titleEn: 'Deployment, acceptance and activation remain unlinked',
      status: 'monitoring', openedAt: '2026-09-28', updatedAt: '2026-09-30', isSimulated: true,
      summary: '两次决策复查关注同一交付问题。PM 均已回应，但同批项目的节点关系仍待验证。',
      summaryEn: 'Two decision reviews concern the same delivery question. Both have PM responses; links between milestones for the same projects remain unverified.',
      impact: '不能把扩建安排直接视为可收费服务或已兑现收入。两次配置方案是独立样稿，不能累加为连续调仓。',
      impactEn: 'Expansion plans do not establish billable service or realized revenue. The two allocation scenarios are independent examples and cannot be added into a sequence of trades.',
      reviewTrigger: '取得同批项目的部署、验收、客户启用及收费记录后复查，同时记录延期、取消和缺失。',
      reviewTriggerEn: 'Review when matched-project deployment, acceptance, activation and billing records arrive, including delays, cancellations and gaps.',
      decisionReviews: [review('field-20260928-allocation', 'field-evidence'), review('field-20260930-hold', 'field-delivery')],
      observations: [
        observation('field-delivery-20260928', '2026-09-28',
          '公司报告保留扩建与兑现之间的时间约束，现有建设记录不足以证明交付加速。',
          'The company report retains timing constraints between expansion and delivery. Construction records do not establish faster delivery.',
          [source('alphabet', 'alpha-field-main', 'v2', 'constraints', 'demo-alpha-build-later')]),
        observation('field-delivery-20260930', '2026-09-30',
          '本次复核继续采用既有产能专题：客户重复使用与新增能力缺少对应，没有新增材料证明缺口已经关闭。',
          'This review revisits the existing capacity report: repeat customer usage is not matched to added capacity. No new material establishes that the gap has closed.',
          [source('alphabet', 'alpha-field-capacity', 'v1', 'handoff', 'demo-alpha-use-later')]),
      ],
      resolution: null,
    },
  ],
};

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.trim().length > 0;
const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const require = (condition, message) => { if (!condition) throw new Error(`Risk register: ${message}`); };
const identifier = (value, label) => require(text(value) && !/[\s\u0000-\u001f\u007f/?#]/u.test(value) && value.length <= 160 && !['.', '..'].includes(value), `${label} must be an explicit identifier`);
const bilingual = (value, field, label) => require(text(value[field]) && text(value[`${field}En`]), `${label} requires bilingual ${field}`);
const one = (items, id, label) => {
  require(Array.isArray(items), `${label} collection must be an array`);
  const matches = items.filter(item => object(item) && item.id === id);
  require(matches.length === 1, `${label} ${id} is ${matches.length ? 'ambiguous' : 'unknown'}`);
  return matches[0];
};
const mappingKey = (managerId, decisionId, reviewRiskId) => JSON.stringify([managerId, decisionId, reviewRiskId]);

function validateSources(sources, risk, date, data, label, resolution = false) {
  require(Array.isArray(sources) && sources.length > 0, `${label} requires explicit sources`);
  const seen = new Set();
  for (const reference of sources) {
    require(object(reference), `${label} source must be an object`);
    for (const field of ['companyId', 'reportId', 'version', 'sectionId', 'evidenceId']) identifier(reference[field], `source ${field}`);
    const key = JSON.stringify([reference.companyId, reference.reportId, reference.version, reference.sectionId, reference.evidenceId]);
    require(!seen.has(key), `${label} source references must be unique`); seen.add(key);
    require(risk.companyIds.includes(reference.companyId), 'source company must belong to risk scope');
    const report = one(data.reports, reference.reportId, 'report');
    require(report.companyId === reference.companyId && report.managerId === risk.managerId, 'source report ownership must match risk company and manager');
    require(Array.isArray(report.versions), 'source report versions must be an array');
    const versions = report.versions.filter(item => object(item) && item.version === reference.version);
    require(versions.length === 1, 'source report version must be explicit and unambiguous');
    const document = versions[0];
    require(validDate(document.publishedAt) && document.publishedAt <= date, 'source report publication must not follow observation or resolution date');
    require(validDate(document.cutoff) && document.cutoff <= document.publishedAt, 'source report cutoff must be explicit and no later than publication');
    const section = one(document.sections, reference.sectionId, 'report section');
    require(Array.isArray(section.citations) && section.citations.includes(reference.evidenceId), 'source evidence must be cited by the exact report section');
    const evidence = one(data.evidence, reference.evidenceId, 'evidence');
    require(evidence.companyId === reference.companyId, 'source evidence company must match report company');
    require(['available', 'excerpt', 'unavailable'].includes(evidence.availability), 'source evidence availability must remain explicit');
    require(validDate(evidence.publishedAt) && validDate(evidence.availableAt) && evidence.publishedAt <= evidence.availableAt && evidence.availableAt <= document.cutoff && evidence.availableAt <= date, 'source evidence dates must precede report cutoff and observation or resolution');
    if (resolution) require(evidence.availability !== 'unavailable', 'unavailable evidence cannot establish risk resolution');
  }
}

export function validateRiskRegister(fixture, data = workspace, decisions = portfolioDecisionFixture) {
  require(object(data) && ['managers', 'companies', 'reports', 'evidence'].every(key => Array.isArray(data[key])), 'catalog collections are required');
  validatePortfolioDecisionFixture(decisions, data);
  require(object(fixture) && fixture.isSimulated === true, 'fixture must identify fictional data');
  identifier(fixture.id, 'fixture id'); identifier(fixture.version, 'fixture version');
  require(validDate(fixture.asOf), 'fixture asOf must be a valid date');
  bilingual(fixture, 'label', 'fixture'); bilingual(fixture, 'disclosure', 'fixture');
  require(Array.isArray(fixture.risks) && object(fixture.featuredByManager), 'risks and explicit featured map are required');
  const ids = new Set(); const mappings = new Set();
  for (const risk of fixture.risks) {
    require(object(risk) && risk.isSimulated === true, 'risk must identify fictional data');
    identifier(risk.id, 'risk id'); require(!ids.has(risk.id), 'risk ids must be unique'); ids.add(risk.id);
    identifier(risk.managerId, 'manager id'); one(data.managers, risk.managerId, 'manager');
    for (const field of ['title', 'summary', 'impact', 'reviewTrigger']) bilingual(risk, field, 'risk');
    require(['needs_review', 'monitoring', 'resolved'].includes(risk.status), 'risk status is invalid');
    require(validDate(risk.openedAt) && validDate(risk.updatedAt) && risk.openedAt <= risk.updatedAt && risk.updatedAt <= fixture.asOf, 'risk dates must be ordered within fixture asOf');
    require(Array.isArray(risk.companyIds) && risk.companyIds.length > 0 && new Set(risk.companyIds).size === risk.companyIds.length, 'risk companies must be explicit and unique');
    risk.companyIds.forEach(id => { identifier(id, 'risk company'); one(data.companies, id, 'company'); });
    require(Array.isArray(risk.decisionReviews), 'decision reviews must be an array');
    let latestReviewDate = risk.openedAt;
    for (const mapping of risk.decisionReviews) {
      require(object(mapping), 'decision review mapping must be an object');
      identifier(mapping.decisionId, 'decision id'); identifier(mapping.reviewRiskId, 'review risk id');
      const decision = one(decisions.decisions, mapping.decisionId, 'decision');
      require(decision.managerId === risk.managerId, 'decision review manager must match risk owner');
      require(risk.companyIds.every(companyId => decision.companyIds.includes(companyId)), 'risk company scope must belong to every linked decision');
      require(decision.date >= risk.openedAt && decision.date <= risk.updatedAt, 'decision review date must fall within risk dates');
      one(decision.risks, mapping.reviewRiskId, 'decision risk review');
      const key = mappingKey(risk.managerId, mapping.decisionId, mapping.reviewRiskId);
      require(!mappings.has(key), 'a decision risk review can map to only one continuous risk'); mappings.add(key);
      if (decision.date > latestReviewDate) latestReviewDate = decision.date;
    }
    require(Array.isArray(risk.observations) && risk.observations.length > 0, 'risk requires evidence observations');
    const observations = new Set(); let latestObservation = risk.openedAt;
    for (const item of risk.observations) {
      require(object(item), 'observation must be an object'); identifier(item.id, 'observation id');
      require(!observations.has(item.id), 'observation ids must be unique within risk'); observations.add(item.id);
      require(validDate(item.date) && item.date >= risk.openedAt && item.date <= risk.updatedAt, 'observation date must fall within risk dates');
      bilingual(item, 'text', 'observation'); validateSources(item.sources, risk, item.date, data, 'observation');
      if (item.date > latestObservation) latestObservation = item.date;
    }
    if (risk.status === 'resolved') {
      require(object(risk.resolution), 'resolved risk requires explicit resolution');
      bilingual(risk.resolution, 'reason', 'resolution');
      require(validDate(risk.resolution.date) && risk.resolution.date >= latestReviewDate && risk.resolution.date >= latestObservation && risk.resolution.date <= risk.updatedAt, 'resolution date must follow observations and reviews within risk dates');
      validateSources(risk.resolution.sources, risk, risk.resolution.date, data, 'resolution', true);
    } else require(risk.resolution === null, 'open risk must keep resolution null; a PM response is not a resolution');
  }
  for (const [managerId, riskId] of Object.entries(fixture.featuredByManager)) {
    identifier(managerId, 'featured manager'); one(data.managers, managerId, 'manager');
    if (riskId === null) continue;
    identifier(riskId, 'featured risk');
    require(one(fixture.risks, riskId, 'featured risk').managerId === managerId, 'featured risk ownership must match manager');
  }
  return fixture;
}

export function getManagerRisks(managerId, data = workspace, fixture = riskRegisterFixture, decisions = portfolioDecisionFixture) {
  identifier(managerId, 'manager id'); one(data.managers, managerId, 'manager');
  validateRiskRegister(fixture, data, decisions);
  return fixture.risks.filter(item => item.managerId === managerId).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt) || a.id.localeCompare(b.id));
}

export function getRisk(managerId, riskId, data = workspace, fixture = riskRegisterFixture, decisions = portfolioDecisionFixture) {
  identifier(riskId, 'risk id');
  return one(getManagerRisks(managerId, data, fixture, decisions), riskId, `risk for manager ${managerId}`);
}

export function getFeaturedRiskId(managerId, data = workspace, fixture = riskRegisterFixture, decisions = portfolioDecisionFixture) {
  getManagerRisks(managerId, data, fixture, decisions);
  require(Object.hasOwn(fixture.featuredByManager, managerId), `featured risk selection is missing for manager ${managerId}`);
  return fixture.featuredByManager[managerId];
}

export function getRiskForDecisionReview(managerId, decisionId, reviewRiskId, data = workspace, fixture = riskRegisterFixture, decisions = portfolioDecisionFixture) {
  identifier(decisionId, 'decision id'); identifier(reviewRiskId, 'review risk id');
  const risks = getManagerRisks(managerId, data, fixture, decisions);
  const decision = one(decisions.decisions, decisionId, 'decision');
  require(decision.managerId === managerId, 'decision review manager must match requested manager');
  one(decision.risks, reviewRiskId, 'decision risk review');
  return risks.find(item => item.decisionReviews.some(reference => reference.decisionId === decisionId && reference.reviewRiskId === reviewRiskId)) ?? null;
}
