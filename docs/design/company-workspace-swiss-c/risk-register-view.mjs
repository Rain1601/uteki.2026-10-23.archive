import { catalog, getManager, getEvidence, formatRoute } from './model.mjs?v=20261006-risk1';
import { riskRegisterFixture, getManagerRisks, getRisk, getFeaturedRiskId } from './risk-register.mjs';
import { getDecision } from './portfolio-decisions.mjs';

const e = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const filters = [['all', '全部', 'All'], ['needs_review', '待复核', 'Needs review'], ['monitoring', '持续观察', 'Monitoring'], ['resolved', '已结束', 'Closed']];
const weight = value => `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)}%`;

// Persistent risk issues and individual decision reviews have separate identities.
// Opening a record never acknowledges, resolves or executes it.
export function createRiskRegisterViews({ t, companyIcon }) {
  const text = (zh, en) => e(t(zh, en));
  const localized = (value, field) => e(t(value[field], value[`${field}En`]));
  const routeFor = (managerId, riskId, riskFilter = 'all') => ({ managerId, view: 'risks', ...(riskId ? { riskId } : {}), riskFilter });
  const link = (route, label, className, id, attributes = '') => `<a href="${e(formatRoute(route))}" class="${e(className)}" id="${e(id)}"${attributes}>${label}</a>`;
  const statusLabel = status => {
    const entry = filters.find(([id]) => id === status && id !== 'all');
    if (!entry) throw new Error('Risk status is unavailable');
    return text(entry[1], entry[2]);
  };
  const companyFor = companyId => {
    const company = catalog.companies.find(item => item.id === companyId);
    if (!company) throw new Error('Risk company is not present in the selected catalog');
    return company;
  };
  const companyIdentity = companyId => {
    const company = companyFor(companyId);
    return `<span class="risk-company">${companyIcon(company)}<span>${e(company.name)}</span></span>`;
  };
  const countsFor = records => Object.fromEntries(filters.map(([id]) => [id, id === 'all' ? records.length : records.filter(record => record.status === id).length]));
  const status = record => `<span class="risk-state" data-risk-status="${e(record.status)}">${statusLabel(record.status)}</span>`;
  const availability = value => {
    const labels = { available: ['样本摘录可读', 'Sample excerpt available'], excerpt: ['仅样本摘录', 'Sample excerpt only'], unavailable: ['原文不可用', 'Source unavailable'] };
    if (!labels[value]) throw new Error('Evidence availability is unknown');
    return text(...labels[value]);
  };

  function sourceLink(record, reference, id) {
    const { company, manager, report, evidence } = getEvidence(reference.companyId, reference.reportId, reference.version, reference.evidenceId);
    const section = report.sections.find(item => item.id === reference.sectionId);
    if (manager.id !== record.managerId || !section?.citations?.includes(reference.evidenceId)) throw new Error('Risk source is outside its explicit Manager or section scope');
    const route = { managerId: record.managerId, companyId: reference.companyId, view: 'report', reportId: reference.reportId, version: reference.version, sectionId: reference.sectionId };
    return `<div class="risk-source" data-evidence-id="${e(reference.evidenceId)}" data-source-availability="${e(evidence.availability)}"><div>${link(route, `${e(company.name)} · ${e(reference.version)} <span aria-hidden="true">↗</span>`, 'risk-source-link', `risk-source-${id}`, ` data-risk-evidence="${e(reference.evidenceId)}"`)}<span class="risk-source-state">${availability(evidence.availability)}</span></div><p lang="${e(evidence.language)}">${e(evidence.sourceTitle)} · ${e(evidence.locator)}</p></div>`;
  }

  function directory(managerId, records, filter, selectedId, counts) {
    return `<aside class="risk-directory"><div class="risk-directory-heading"><h2>${text('风险跟踪', 'Risk register')}</h2><span>${counts.all}</span></div><p class="risk-directory-byline">Risk Manager · ${text('按更新时间', 'By update date')}</p><nav class="risk-filters" aria-label="${text('筛选风险状态', 'Filter risk status')}">${filters.map(([id, zh, en]) => {
      const selected = records.find(record => record.id === selectedId);
      const keptId = selected && (id === 'all' || selected.status === id) ? selected.id : undefined;
      return link(routeFor(managerId, keptId, id), `${text(zh, en)}<span data-risk-count="${id}">${counts[id]}</span>`, 'risk-filter', `risk-filter-${id}`, filter === id ? ' aria-current="page"' : '');
    }).join('')}</nav><nav aria-label="${text('风险条目', 'Risk issues')}"><ol class="risk-directory-list">${records.filter(record => filter === 'all' || record.status === filter).map(record => `<li>${link(routeFor(managerId, record.id, filter), `<span class="risk-list-meta">${status(record)}<time datetime="${e(record.updatedAt)}">${e(record.updatedAt)}</time></span><strong>${localized(record, 'title')}</strong><span class="risk-list-companies">${record.companyIds.map(companyId => e(companyFor(companyId).ticker)).join(' · ')}</span>`, 'risk-list-link', `risk-select-${record.id}`, selectedId === record.id ? ' aria-current="page"' : '')}</li>`).join('')}</ol></nav></aside>`;
  }

  function observations(record) {
    return `<section class="risk-detail-section" aria-labelledby="risk-updates-title"><div class="risk-section-heading"><h3 id="risk-updates-title">${text('证据与复查记录', 'Evidence & review updates')}</h3><span>${record.observations.length} ${text('条记录', 'updates')}</span></div><ol class="risk-observations">${[...record.observations].sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id)).map(observation => `<li class="risk-observation" data-observation-id="${e(observation.id)}"><time datetime="${e(observation.date)}">${e(observation.date)}</time><div><p>${localized(observation, 'text')}</p>${observation.sources.map((reference, index) => sourceLink(record, reference, `${record.id}-${observation.id}-${index}`)).join('') || `<p class="risk-note">${text('本次为复查记录，未附新的来源。', 'This is a review note with no new source attached.')}</p>`}</div></li>`).join('')}</ol></section>`;
  }

  function decisionReview(record, reference) {
    const decision = getDecision(record.managerId, reference.decisionId);
    const review = decision.risks.find(item => item.id === reference.reviewRiskId);
    if (!review) throw new Error('Risk decision review is unavailable');
    const changed = decision.allocations.filter(row => row.draftPct !== row.targetPct);
    const rows = changed.length ? changed : decision.allocations;
    const maintainsAllocation = decision.kind === 'hold';
    const compare = `<div class="risk-allocation-table-wrap"><table class="risk-allocation-table"><caption class="sr-only">${text('决策初稿与最终目标，不是成交记录', 'Decision draft and final target, not execution records')}</caption><thead><tr><th scope="col">${text('资产', 'Asset')}</th><th scope="col">${text('初稿', 'Draft')}</th><th scope="col">${text('最终目标', 'Final target')}</th></tr></thead><tbody>${rows.map(row => `<tr data-review-asset="${e(row.assetId)}"><th scope="row">${row.assetId === 'cash' ? text('现金', 'Cash') : e(companyFor(row.assetId).name)}</th><td data-draft-pct="${row.draftPct}">${weight(row.draftPct)}</td><td data-target-pct="${row.targetPct}">${weight(row.targetPct)}</td></tr>`).join('')}</tbody></table></div>`;
    const decisionRoute = { managerId: record.managerId, view: 'decisions', decisionId: decision.id, decisionTab: 'risk' };
    return `<article class="risk-decision-review risk-review-block" data-decision-id="${e(decision.id)}" data-review-risk-id="${e(review.id)}" data-response-status="${e(review.responseStatus)}"><header><time datetime="${e(decision.date)}">${e(decision.date)}</time>${link(decisionRoute, `${localized(decision, 'title')} <span aria-hidden="true">↗</span>`, 'risk-decision-link', `risk-decision-${record.id}-${decision.id}`)}</header><div class="risk-review-columns"><section><h4>Risk Manager · ${text('风险意见', 'Opinion')}</h4><p>${localized(review, 'opinion')}</p></section><section><h4>Portfolio Manager · ${text('已回应', 'Responded')}</h4><p>${localized(review, 'response')}</p></section></div><div class="risk-decision-impact"><div><h4>${text('相关决策的配置对照', 'Allocation comparison for this decision')}</h4><p>${changed.length ? text('以下对照本次初稿与最终目标，可能包含多项考虑；这条风险如何影响决定，以 PM 回应为准。', 'The draft-to-target comparison may reflect several considerations. The PM response explains how this risk informed the decision.') : maintainsAllocation ? text('本次维持配置。PM 回应保留了后续观察条件。', 'This decision maintains the allocation. The PM response retains the follow-up conditions.') : text('最终目标保留了初稿配置。方案未修改，但目标配置仍可能与决策前不同。', 'The final target retains the draft allocation. The proposal is unchanged, but its target can differ from the allocation before the decision.')}</p><span class="risk-execution-note">${decision.execution.status === 'pending' ? text('目标未执行', 'Target not executed') : text('无需交易', 'No trade required')}</span></div>${changed.length ? compare : `<details class="risk-maintained-target"><summary>${maintainsAllocation ? text('查看维持的目标比例', 'View maintained target weights') : text('查看保留的初稿目标', 'View retained draft targets')}</summary>${compare}</details>`}</div><p class="risk-review-followup"><span>${text('当时的后续条件', 'Follow-up at this decision')}</span>${localized(review, 'followUp')}</p></article>`;
  }

  function detail(record) {
    const reviews = [...record.decisionReviews].sort((a, b) => getDecision(record.managerId, b.decisionId).date.localeCompare(getDecision(record.managerId, a.decisionId).date) || a.decisionId.localeCompare(b.decisionId));
    return `<article class="risk-detail" aria-labelledby="risk-title"><header class="risk-detail-header risk-detail-summary"><div class="risk-detail-kicker">${status(record)}<span>${text('开始跟踪', 'Opened')} <time datetime="${e(record.openedAt)}">${e(record.openedAt)}</time> · ${text('更新', 'Updated')} <time datetime="${e(record.updatedAt)}">${e(record.updatedAt)}</time></span></div><h2 id="risk-title">${localized(record, 'title')}</h2><p class="risk-lead">${localized(record, 'summary')}</p><div class="risk-companies" aria-label="${text('涉及公司', 'Affected companies')}">${record.companyIds.map(companyIdentity).join('')}</div></header><dl class="risk-implications"><div><dt>${text('对组合的影响', 'Portfolio implications')}</dt><dd>${localized(record, 'impact')}</dd></div><div class="risk-review-trigger"><dt>${record.status === 'resolved' ? text('原复查条件', 'Original review condition') : text('何时重新审查', 'When to review again')}</dt><dd>${localized(record, 'reviewTrigger')}</dd></div></dl>${record.resolution ? `<section class="risk-resolution"><h3>${text('结束记录', 'Closure record')} · ${e(record.resolution.date)}</h3><p>${localized(record.resolution, 'reason')}</p>${record.resolution.sources.map((reference, index) => sourceLink(record, reference, `${record.id}-resolution-${index}`)).join('')}</section>` : ''}${observations(record)}<section class="risk-detail-section" aria-labelledby="risk-decisions-title"><div class="risk-section-heading"><h3 id="risk-decisions-title">${text('如何影响组合决定', 'How this informed decisions')}</h3><span>${reviews.length} ${text('次审查', 'reviews')}</span></div><p class="risk-note">${text('PM 回应与风险状态分别记录。已回应不代表风险已解决；各次配置属于独立决策样本。', 'PM responses and risk status are recorded separately. A response does not resolve a risk. Allocations belong to separate decision samples.')}</p>${reviews.map(reference => decisionReview(record, reference)).join('') || `<p class="risk-note">${text('尚无关联的组合决策审查。', 'No linked portfolio decision review has been recorded.')}</p>`}</section></article>`;
  }

  function main(route) {
    if (route.view !== 'risks' || !route.managerId || route.companyId || route.institutionId) throw new Error('An explicit Manager risks view is required');
    formatRoute(route);
    const manager = getManager(route.managerId).manager;
    const records = getManagerRisks(manager.id);
    const filter = route.riskFilter ?? 'all';
    if (!filters.some(([id]) => id === filter)) throw new Error('Unknown risk filter');
    const counts = countsFor(records);
    const requestedId = route.riskId ?? getFeaturedRiskId(manager.id);
    const requested = requestedId === null ? null : getRisk(manager.id, requestedId);
    const selected = requested && (filter === 'all' || requested.status === filter) ? requested : null;
    const visible = records.filter(record => filter === 'all' || record.status === filter);
    const placeholder = !records.length ? `<h2>${text('尚无风险跟踪记录', 'No risk records available')}</h2><p>${text('当前样本尚未登记风险条目。这不代表组合没有风险。', 'No risk issues are registered in this sample. This does not establish that the portfolio has no risk.')}</p>` : !visible.length ? `<h2>${text('该状态下暂无记录', 'No records in this status')}</h2><p>${text('其他状态的风险仍保留在清单中。', 'Risk issues under other statuses remain in the register.')}</p>${link(routeFor(manager.id, undefined, 'all'), text('查看全部风险 →', 'View all risks →'), 'risk-empty-link', 'risk-filter-clear')}` : `<h2>${text('选择一项风险继续阅读', 'Select a risk to continue')}</h2><p>${requested ? text('当前选中的风险不属于这个筛选条件，请从列表选择。', 'The selected risk is outside this filter. Choose an issue from the list.') : text('从列表选择，查看证据、组合回应与复查条件。', 'Choose from the list to read evidence, portfolio responses and review conditions.')}</p>`;
    return `<section id="risk-register" class="risk-register" data-manager="${e(manager.id)}" data-risk="${e(selected?.id || '')}" data-risk-filter="${e(filter)}" data-simulated="true"><header class="risk-register-meta"><span>Risk Manager · ${e(manager.name)} ${text('组合', 'portfolio')}</span><span>${text('虚构样本', 'Fictional sample')} · ${text('截至', 'As of')} ${e(riskRegisterFixture.asOf)}</span></header><div class="risk-workspace">${directory(manager.id, records, filter, selected?.id, counts)}${selected ? detail(selected) : `<div class="risk-empty" role="status">${placeholder}</div>`}</div><p class="risk-disclosure">${localized(riskRegisterFixture, 'disclosure')}</p></section>`;
  }

  function summary(managerId) {
    const manager = getManager(managerId).manager;
    const records = getManagerRisks(managerId), counts = countsFor(records);
    const featuredId = getFeaturedRiskId(managerId);
    const featured = featuredId === null ? null : getRisk(managerId, featuredId);
    return `<section class="risk-summary" data-risk-summary="${e(managerId)}" aria-label="${text('组合风险跟踪', 'Portfolio risk tracking')}"><div class="risk-summary-heading"><span><strong>${text('风险跟踪', 'Risk tracking')}</strong><small>Risk Manager</small></span>${link(routeFor(managerId, featured?.id), text('查看全部', 'View all'), 'risk-summary-open', `risk-summary-open-${managerId}`)}</div><div class="risk-summary-counts">${records.length ? `<span data-status-count="needs_review">${text('待复核', 'Needs review')} <strong>${counts.needs_review}</strong></span><span data-status-count="monitoring">${text('持续观察', 'Monitoring')} <strong>${counts.monitoring}</strong></span>` : `<span>${text('尚无记录，不代表风险为零', 'No records; risk is not established as zero')}</span>`}<small>${text('虚构样本', 'Fictional sample')} · ${e(manager.name)}</small></div>${featured ? `<div class="risk-summary-featured">${link(routeFor(managerId, featured.id), localized(featured, 'title'), 'risk-summary-title', `risk-summary-${featured.id}`)}<p title="${localized(featured, 'reviewTrigger')}">${text('复查条件', 'Review trigger')} · ${localized(featured, 'reviewTrigger')}</p></div>` : ''}</section>`;
  }

  return { main, summary };
}
