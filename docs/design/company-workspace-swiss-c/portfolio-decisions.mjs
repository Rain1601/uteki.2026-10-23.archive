// Versioned fictional interaction fixture. These independent decision scenarios
// do not supply, derive, or overwrite institutional holdings, returns or fills.
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';

const row = (assetId, beforePct, draftPct, targetPct, reason, reasonEn) => ({ assetId, beforePct, draftPct, targetPct, reason, reasonEn });
const ref = (companyId, reportId, version, note, noteEn) => ({ companyId, reportId, version, note, noteEn });
const risk = (id, title, titleEn, opinion, opinionEn, response, responseEn, followUp, followUpEn) => ({
  id, title, titleEn, opinion, opinionEn, response, responseEn, followUp, followUpEn,
  status: 'monitoring', responseStatus: 'responded',
});
const pending = {
  status: 'pending', summary: '待模拟执行 · 仅有目标方案，未提供成交或实际仓位确认。',
  summaryEn: 'Pending simulated execution · Targets only; no fills or actual allocation confirmed.',
};
const unchanged = {
  status: 'not_required', summary: '维持不变 · 本次复核不产生新的执行指令。',
  summaryEn: 'No execution required · This review leaves the scenario allocation unchanged.',
};

export const portfolioDecisionFixture = {
  id: 'uteki-portfolio-decision-scenarios', version: 'v1', asOf: '2026-09-30', isSimulated: true,
  label: '虚构决策样稿 · 非实盘', labelEn: 'Fictional decision scenarios · Not live trading',
  disclosure: '用于体验研究、配置与风险协作的独立情景。调整前、初稿和目标占比均为具名虚构设定，不是实际持仓、成交或连续账户历史；不改写首页的组合展示样本。引用报告本身也为演示材料，不包含估值或交易价格。',
  disclosureEn: 'Independent fictional scenarios for research, allocation and risk review. Before, draft and target weights are authored examples, not holdings, fills or a continuous account history. They do not change the homepage portfolio fixture. Referenced reports are also demo material and supply no valuation or execution prices.',
  featuredByManager: { north: 'north-20260930-allocation', field: 'field-20260930-hold' },
  decisions: [
    {
      id: 'north-20260930-allocation', managerId: 'north', date: '2026-09-30', kind: 'rebalance', isSimulated: true,
      title: '小幅提高 Alphabet 目标占比，保留现金余地', titleEn: 'Modestly increase Alphabet; preserve cash flexibility',
      summary: '初稿拟提高 8 个百分点；风险复核后缩小为 3 个百分点，付费质量问题继续追踪。',
      summaryEn: 'The draft added 8 percentage points. Risk review reduced the increase to 3 points; payment quality remains under review.',
      companyIds: ['alphabet', 'microsoft', 'nvidia'],
      allocations: [
        row('alphabet', 30, 38, 33, '演示较小的配置增量；需求线索不等于利润已兑现。', 'Illustrate a smaller allocation increase; demand signals do not establish realized profit.'),
        row('microsoft', 25, 25, 25, '本次维持，暂无调整理由。', 'Maintain the allocation; no change is proposed.'),
        row('nvidia', 20, 20, 20, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('cash', 25, 17, 22, '缩小加仓方案后，多保留 5 个百分点现金。', 'Retain 5 more percentage points of cash than the draft.'),
      ],
      reasons: [
        { zh: '研究更新把重复使用与付费质量拆开，配置理由须保留这一证据边界。', en: 'Research separates repeat usage from payment quality; allocation reasoning must preserve that distinction.' },
        { zh: '演示经理接受缩小方案，并明确现金与加仓之间的取舍；比例并非报告计算结果。', en: 'The scenario manager accepts a smaller proposal and states the cash trade-off; weights are not calculated from the reports.' },
      ],
      reports: [
        ref('alphabet', 'alpha-north-main', 'v2', '公司判断及资本投入的证据边界。', 'Company assessment and limits of capital-spending evidence.'),
        ref('alphabet', 'alpha-north-cloud', 'v2', '持续使用有支持，付费与服务成本仍缺对应。', 'Repeat usage has support; payment and service costs remain unlinked.'),
        ref('microsoft', 'ms-north-main', 'v1', '查看未调整公司的既有研究背景。', 'Review the research context of an unchanged allocation.'),
      ],
      risks: [risk('north-common-assumption', '共同假设仍需关注', 'Shared assumptions remain under review',
        '初稿进一步增加对增长兑现的依赖；当前材料不足以量化公司之间的共同暴露。',
        'The draft increases reliance on growth delivery; current material cannot quantify shared exposure across companies.',
        '将 Alphabet 目标从初稿 38% 调为 33%，现金从 17% 调为 22%。这只是缩小新增暴露，不代表风险消除。',
        'Reduce Alphabet from the draft 38% to 33% and increase cash from 17% to 22%. This limits the added exposure; it does not eliminate risk.',
        '继续核对同批客户收费、服务成本及投入回报；资料不足时不宣称压力测试通过。',
        'Track matched customer payments, service costs and returns on investment. Missing data does not constitute a passed stress test.')],
      execution: { ...pending },
    },
    {
      id: 'north-20260929-hold', managerId: 'north', date: '2026-09-29', kind: 'hold', isSimulated: true,
      title: '复核研究更新，维持原配置', titleEn: 'Review the research update; keep allocation unchanged',
      summary: '新线索支持继续研究，但未补齐付费与成本对应；本次明确选择不调整。',
      summaryEn: 'New signals support further research, but payment and cost matching remain missing; this review explicitly makes no change.',
      companyIds: ['alphabet', 'microsoft', 'nvidia'],
      allocations: [
        row('alphabet', 30, 30, 30, '更新研究判断，不自动触发加仓。', 'A research update does not automatically trigger an increase.'),
        row('microsoft', 25, 25, 25, '维持原比例。', 'Retain the allocation.'),
        row('nvidia', 20, 20, 20, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('cash', 25, 25, 25, '保留现金，等待能够影响配置的新证据。', 'Retain cash pending evidence that changes the allocation assessment.'),
      ],
      reasons: [{ zh: '维持不变是一次有记录的决定，后续仍需复核未解决的问题。', en: 'Holding unchanged is a recorded decision; unresolved questions still need review.' }],
      reports: [ref('alphabet', 'alpha-north-main', 'v2', '查看这次复核所依据的指定版本。', 'Read the exact version used for this review.')],
      risks: [risk('north-payment-gap', '付费质量尚未验证', 'Payment quality remains unverified',
        '持续使用的正向线索无法代替客户收费与服务成本数据。', 'Positive usage signals cannot replace customer payment and service cost data.',
        '维持各项比例；已回应该意见，未将它标记为已解决。', 'Keep all weights unchanged; the concern has a response but is not resolved.',
        '取得同期间收费和成本材料后重新复核。', 'Review again when matched-period payment and cost material is available.')],
      execution: { ...unchanged },
    },
    {
      id: 'north-20260927-allocation', managerId: 'north', date: '2026-09-27', kind: 'rebalance', isSimulated: true,
      title: '收窄 Microsoft 的加仓方案', titleEn: 'Narrow the Microsoft allocation proposal',
      summary: '演示如何在阅读新报告后保留配置弹性，最终目标低于初稿。',
      summaryEn: 'Illustrate retaining allocation flexibility after a new report; the final target is below the draft.',
      companyIds: ['alphabet', 'microsoft', 'nvidia'],
      allocations: [
        row('alphabet', 30, 30, 30, '此次复核维持原比例。', 'This review leaves the allocation unchanged.'),
        row('microsoft', 25, 32, 28, '把初稿增量从 7 个百分点缩小为 3 个百分点。', 'Reduce the draft increase from 7 to 3 percentage points.'),
        row('nvidia', 20, 20, 20, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('cash', 25, 18, 22, '保留更大的现金缓冲。', 'Retain a larger cash buffer.'),
      ],
      reasons: [{ zh: '用新报告提出比较问题；示例比例用于检验交互，不代表报告给出了交易建议。', en: 'Use the report to frame comparison questions; example weights test the interaction and are not trade advice from the report.' }],
      reports: [ref('microsoft', 'ms-north-main', 'v1', '明确作者、公司和版本的研究入口。', 'Research entry with explicit author, company and version.')],
      risks: [risk('north-flexibility', '为未验证部分保留余地', 'Retain room for unresolved questions',
        '单份报告不能补齐整个组合的风险暴露及交易价格信息。', 'One report does not establish portfolio-wide exposure or execution prices.',
        '降低初稿目标，保留更多现金；待补充材料后再决定是否提出新的方案。', 'Reduce the draft target and retain more cash; further evidence may justify a new proposal.',
        '补齐估值和组合风险资料；本样稿不输出量化损失结论。', 'Obtain valuation and portfolio risk data; this sample provides no quantified loss conclusion.')],
      execution: { ...pending },
    },
    {
      id: 'field-20260930-hold', managerId: 'field', date: '2026-09-30', kind: 'hold', isSimulated: true,
      title: '等待交付证据，维持配置', titleEn: 'Await delivery evidence; keep allocation unchanged',
      summary: '扩建安排不等于客户启用，风险意见已回应，交付问题继续追踪。',
      summaryEn: 'Expansion plans do not establish customer activation. Risk feedback has a response; delivery questions remain open.',
      companyIds: ['alphabet', 'nvidia', 'arista'],
      allocations: [
        row('alphabet', 25, 25, 25, '等待同批项目验收和客户启用的对应材料。', 'Await matched project acceptance and customer activation records.'),
        row('nvidia', 25, 25, 25, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('arista', 20, 20, 20, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('cash', 30, 30, 30, '维持现金比例。', 'Retain the cash allocation.'),
      ],
      reasons: [{ zh: '把进度线索与收入兑现分开，暂不因新增消息改变情景配置。', en: 'Separate progress signals from realized revenue; additional news alone does not change the scenario allocation.' }],
      reports: [
        ref('alphabet', 'alpha-field-main', 'v2', '公司层面的阶段判断。', 'Company-level assessment of progress.'),
        ref('alphabet', 'alpha-field-capacity', 'v1', '验收、启用和客户对应的待验证问题。', 'Open questions about acceptance, activation and customer matching.'),
      ],
      risks: [risk('field-delivery', '交付节点尚未连通', 'Delivery milestones remain unlinked',
        '建设、采购和使用材料缺少同批项目对应，不能拼接为已兑现的增长。', 'Construction, procurement and usage records lack project matching and cannot establish realized growth.',
        '不改变情景配置，并继续保留该风险关注。', 'Leave the scenario allocation unchanged and keep this risk under review.',
        '追踪同批项目的部署、验收和客户启用，记录延期与缺失。', 'Track deployment, acceptance and activation for the same projects, including delays and missing data.')],
      execution: { ...unchanged },
    },
    {
      id: 'field-20260928-allocation', managerId: 'field', date: '2026-09-28', kind: 'rebalance', isSimulated: true,
      title: '缩小 Alphabet 方案，保留等待空间', titleEn: 'Reduce the Alphabet proposal; preserve flexibility',
      summary: '演示初稿与最终目标的差异：新增配置缩小，等待交付节点得到验证。',
      summaryEn: 'Illustrate draft-to-target changes: a smaller increase while awaiting verified delivery milestones.',
      companyIds: ['alphabet', 'nvidia', 'arista'],
      allocations: [
        row('alphabet', 25, 32, 27, '把初稿增量从 7 个百分点缩小为 2 个百分点。', 'Reduce the draft increase from 7 to 2 percentage points.'),
        row('nvidia', 25, 25, 25, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('arista', 20, 20, 20, '本次维持；暂无本经理的新增研究依据。', 'Maintain the allocation; no new research by this manager supports a change.'),
        row('cash', 30, 23, 28, '相较初稿多保留 5 个百分点现金。', 'Retain 5 more percentage points of cash than the draft.'),
      ],
      reasons: [{ zh: '展示阶段性判断下的配置取舍；报告并不提供可执行价格或目标仓位。', en: 'Show allocation trade-offs under a staged assessment; the reports provide no executable price or target allocation.' }],
      reports: [ref('alphabet', 'alpha-field-main', 'v2', '本决定采用的公司报告版本。', 'The exact company report version used for this decision.')],
      risks: [risk('field-evidence', '扩建与兑现之间仍有缺口', 'A gap remains between expansion and delivery',
        '扩建信息不能单独支撑初稿的配置增量。', 'Expansion information alone cannot substantiate the draft allocation increase.',
        '缩小最终方案并保留现金，风险意见仍处于关注中。', 'Reduce the final proposal and retain cash; the concern remains under review.',
        '待项目启用资料补充后，再复核配置理由。', 'Revisit allocation reasoning when project activation records are available.')],
      execution: { ...pending },
    },
  ],
};

const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.trim().length > 0;
const validDate = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const fail = message => { throw new Error(`Portfolio decisions: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const identifier = (value, label) => require(text(value) && !/[\s\u0000-\u001f\u007f/?#]/u.test(value) && value.length <= 160 && !['.', '..'].includes(value), `${label} must be an explicit identifier`);
const one = (items, id, label) => {
  require(Array.isArray(items), `${label} collection must be an array`);
  const matches = items.filter(item => record(item) && item.id === id);
  require(matches.length === 1, `${label} ${id} is ${matches.length ? 'ambiguous' : 'unknown'}`);
  return matches[0];
};
const bilingual = (value, field, label) => require(text(value[field]) && text(value[`${field}En`]), `${label} requires bilingual ${field}`);
const close = (a, b) => Math.abs(a - b) < 0.000001;

// Validates only the explicitly selected fixture and catalog. Report references
// must be available as of the scenario date; no latest-version fallback exists.
export function validatePortfolioDecisionFixture(fixture, data = workspace) {
  require(record(data) && Array.isArray(data.managers) && Array.isArray(data.companies) && Array.isArray(data.reports), 'catalog collections are required');
  require(record(fixture) && fixture.isSimulated === true, 'fixture must identify fictional data');
  identifier(fixture.id, 'fixture id'); identifier(fixture.version, 'fixture version');
  require(validDate(fixture.asOf), 'fixture asOf must be a valid date');
  bilingual(fixture, 'label', 'fixture'); bilingual(fixture, 'disclosure', 'fixture');
  require(Array.isArray(fixture.decisions) && record(fixture.featuredByManager), 'decisions and explicit featured map are required');
  const ids = new Set();
  for (const decision of fixture.decisions) {
    require(record(decision) && decision.isSimulated === true, 'decision must identify fictional data');
    identifier(decision.id, 'decision id'); require(!ids.has(decision.id), 'decision ids must be unique'); ids.add(decision.id);
    identifier(decision.managerId, 'manager id'); one(data.managers, decision.managerId, 'manager');
    require(validDate(decision.date) && decision.date <= fixture.asOf, `decision ${decision.id} exceeds asOf or has invalid date`);
    require(['rebalance', 'hold'].includes(decision.kind), 'decision kind is invalid');
    bilingual(decision, 'title', 'decision'); bilingual(decision, 'summary', 'decision');
    require(Array.isArray(decision.companyIds) && new Set(decision.companyIds).size === decision.companyIds.length && decision.companyIds.length > 0, 'companyIds must be explicit and unique');
    decision.companyIds.forEach(id => { identifier(id, 'company id'); one(data.companies, id, 'company'); });
    require(Array.isArray(decision.allocations), 'allocations must be an array');
    const assets = new Set();
    for (const allocation of decision.allocations) {
      require(record(allocation), 'allocation must be an object'); identifier(allocation.assetId, 'asset id');
      require(!assets.has(allocation.assetId), 'allocation assets must be unique'); assets.add(allocation.assetId);
      require(allocation.assetId === 'cash' || decision.companyIds.includes(allocation.assetId), 'allocation company must belong to decision');
      for (const field of ['beforePct', 'draftPct', 'targetPct']) require(Number.isFinite(allocation[field]) && allocation[field] >= 0 && allocation[field] <= 100, `${field} is invalid`);
      bilingual(allocation, 'reason', 'allocation');
    }
    require(assets.has('cash') && assets.size === decision.companyIds.length + 1, 'allocation must include every company and cash');
    for (const field of ['beforePct', 'draftPct', 'targetPct']) require(close(decision.allocations.reduce((total, item) => total + item[field], 0), 100), `${field} must total 100 including cash`);
    const sameTarget = decision.allocations.every(item => close(item.beforePct, item.targetPct));
    require(decision.kind === 'hold' ? sameTarget : !sameTarget, 'decision kind and final allocation disagree');
    require(Array.isArray(decision.reasons) && decision.reasons.length > 0 && decision.reasons.every(item => record(item) && text(item.zh) && text(item.en)), 'reasons must be bilingual');
    require(Array.isArray(decision.reports) && decision.reports.length > 0, 'explicit report references are required');
    const references = new Set();
    for (const reference of decision.reports) {
      require(record(reference), 'report reference must be an object');
      identifier(reference.companyId, 'report company'); identifier(reference.reportId, 'report id'); identifier(reference.version, 'report version');
      require(decision.companyIds.includes(reference.companyId), 'report company must belong to decision');
      const document = one(data.reports, reference.reportId, 'report');
      require(document.companyId === reference.companyId && document.managerId === decision.managerId, 'report ownership must match decision company and manager');
      require(Array.isArray(document.versions), 'report versions must be an array');
      const versions = document.versions.filter(item => item.version === reference.version);
      require(versions.length === 1, 'report version must be explicit and unambiguous');
      require(validDate(versions[0].publishedAt) && versions[0].publishedAt <= decision.date, 'report publication must not follow decision date');
      const key = JSON.stringify([reference.reportId, reference.version]);
      require(!references.has(key), 'report references must be unique'); references.add(key);
      bilingual(reference, 'note', 'report reference');
    }
    require(Array.isArray(decision.risks) && decision.risks.length > 0, 'risk reviews must be explicit');
    const riskIds = new Set();
    for (const item of decision.risks) {
      require(record(item), 'risk must be an object'); identifier(item.id, 'risk id');
      require(!riskIds.has(item.id), 'risk ids must be unique'); riskIds.add(item.id);
      for (const field of ['title', 'opinion', 'response', 'followUp']) bilingual(item, field, 'risk');
      require(item.status === 'monitoring' && item.responseStatus === 'responded', 'risk response is distinct from resolution; fixture risks remain monitoring');
    }
    require(record(decision.execution) && ['pending', 'not_required'].includes(decision.execution.status), 'execution cannot invent confirmed fills');
    require((decision.kind === 'hold') === (decision.execution.status === 'not_required'), 'execution status must match final decision');
    bilingual(decision.execution, 'summary', 'execution');
    require(!['fills', 'actualWeights', 'executedAt', 'executedPrice'].some(key => Object.hasOwn(decision.execution, key)), 'scenario execution cannot contain unverified fills');
  }
  for (const [managerId, decisionId] of Object.entries(fixture.featuredByManager)) {
    identifier(managerId, 'featured manager'); one(data.managers, managerId, 'manager');
    if (decisionId === null) continue;
    identifier(decisionId, 'featured decision');
    const decision = one(fixture.decisions, decisionId, 'featured decision');
    require(decision.managerId === managerId, 'featured decision ownership must match manager');
  }
  return fixture;
}

export function getManagerDecisions(managerId, data = workspace, fixture = portfolioDecisionFixture) {
  identifier(managerId, 'manager id'); one(data.managers, managerId, 'manager');
  validatePortfolioDecisionFixture(fixture, data);
  return fixture.decisions.filter(item => item.managerId === managerId)
    .sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
}

export function getDecision(managerId, decisionId, data = workspace, fixture = portfolioDecisionFixture) {
  identifier(decisionId, 'decision id');
  const decisions = getManagerDecisions(managerId, data, fixture);
  const matches = decisions.filter(item => item.id === decisionId);
  require(matches.length === 1, `decision ${decisionId} is unknown for manager ${managerId}`);
  return matches[0];
}

export function getFeaturedDecisionId(managerId, data = workspace, fixture = portfolioDecisionFixture) {
  getManagerDecisions(managerId, data, fixture);
  require(Object.hasOwn(fixture.featuredByManager, managerId), `featured decision selection is missing for manager ${managerId}`);
  return fixture.featuredByManager[managerId];
}
