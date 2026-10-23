import { catalog, getManager, getReport, formatRoute } from './model.mjs?v=20261006-risk1';
import { getRiskForDecisionReview } from './risk-register.mjs';
import { portfolioDecisionFixture, getManagerDecisions, getDecision, getFeaturedDecisionId } from './portfolio-decisions.mjs';
import { DEFAULT_ALLOCATION_PALETTE, getAllocationPalette, allocationPaletteStyle } from './allocation-palettes.mjs';

const e = value => String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
const weight = value => `${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)}%`;
const delta = value => `${value > 0 ? '+' : ''}${new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value)}`;
const tabNames = [['allocation', '配置变化', 'Allocation'], ['research', '研究依据', 'Research'], ['risk', '风险与回应', 'Risk & response']];

// A read-only decision example. Targets, opinions and responses never establish
// fills or modify the separately authored illustrative holdings.
export function createPortfolioDecisionViews({ t, companyIcon }) {
  const text = (zh, en) => e(t(zh, en));
  const decisionRoute = (managerId, decisionId, decisionTab = 'allocation') => ({ managerId, view: 'decisions', decisionId, decisionTab });
  const link = (route, label, className = '', id = '', attributes = '') => `<a href="${e(formatRoute(route))}" class="${e(className)}"${id ? ` id="${e(id)}"` : ''}${attributes}>${label}</a>`;
  const executionLabel = status => {
    if (status === 'pending') return t('未执行', 'Not executed');
    if (status === 'not_required') return t('无需交易', 'No trade required');
    throw new Error('Decision execution status is unavailable');
  };
  const kindLabel = kind => {
    if (kind === 'rebalance') return t('调整配置', 'Rebalance');
    if (kind === 'hold') return t('维持配置', 'Maintain');
    throw new Error('Decision kind is unavailable');
  };
  const asset = assetId => {
    if (assetId === 'cash') return { name: t('现金', 'Cash'), ticker: 'CASH', color: 'var(--decision-cash)', icon: '<span class="decision-cash-icon" aria-hidden="true">C</span>' };
    const index = catalog.companies.findIndex(company => company.id === assetId);
    if (index < 0) throw new Error('Decision asset is not present in the selected catalog');
    const company = catalog.companies[index];
    return { name: company.name, ticker: company.ticker, color: `var(--decision-holding-${index})`, icon: companyIcon(company) };
  };
  const riskLabel = risk => {
    if (risk.status !== 'monitoring' || risk.responseStatus !== 'responded') throw new Error('Decision risk state is unavailable');
    return `${text('持续观察', 'Monitoring')} · ${text('PM 已回应', 'PM responded')}`;
  };

  function directory(managerId, records, decisionId) {
    return `<nav class="decision-directory" aria-label="${text('组合决策记录', 'Portfolio decision history')}"><div class="decision-directory-heading"><h2>${text('决策记录', 'Decisions')}</h2><span>${records.length}</span></div><p class="decision-directory-note">${text('按决策日期倒序', 'Newest decision first')}</p><ol>${records.map(record => `<li>${link(decisionRoute(managerId, record.id), `<span class="decision-list-meta"><time datetime="${e(record.date)}">${e(record.date)}</time><span>${e(kindLabel(record.kind))}</span></span><strong>${e(t(record.title, record.titleEn))}</strong><span class="decision-list-status">${e(executionLabel(record.execution.status))}<span aria-hidden="true">↗</span></span>`, 'decision-list-link', `decision-select-${record.id}`, record.id === decisionId ? ' aria-current="page"' : '')}</li>`).join('')}</ol></nav>`;
  }

  function allocation(record) {
    const rows = record.allocations.map(row => {
      const company = asset(row.assetId);
      const change = row.targetPct - row.beforePct;
      return `<tr data-decision-asset="${e(row.assetId)}"><th scope="row"><span class="decision-asset">${company.icon}<span><strong>${e(company.name)}</strong><small>${e(company.ticker)}</small></span></span></th><td class="decision-number" data-before-pct="${row.beforePct}">${weight(row.beforePct)}</td><td class="decision-target" data-target-pct="${row.targetPct}"><span class="decision-target-bar" aria-hidden="true"><i style="width:${row.targetPct}%;--asset-color:${company.color}"></i></span><strong>${weight(row.targetPct)}</strong></td><td class="decision-number decision-change" data-change="${change > 0 ? 'increase' : change < 0 ? 'decrease' : 'same'}">${change === 0 ? text('不变', 'No change') : `${delta(change)} <small>${text('个百分点', 'pp')}</small>`}</td></tr>`;
    }).join('');
    const differences = record.allocations.filter(row => row.draftPct !== row.targetPct);
    const draft = differences.length ? `<details class="decision-draft" id="decision-draft-${e(record.id)}"><summary>${text('初稿如何变成最终决定', 'How the draft changed')}<span>${differences.length} ${text('项调整', 'changes')}</span></summary><p>${text('对照提议与最终目标；两者都不是成交记录。', 'Compare the proposal with the final target. Neither is a fill record.')}</p><div class="decision-table-wrap"><table class="decision-draft-table"><caption class="sr-only">${text('初稿与最终配置', 'Draft and final allocation')}</caption><thead><tr><th scope="col">${text('资产', 'Asset')}</th><th scope="col">${text('初稿', 'Draft')}</th><th scope="col">${text('最终目标', 'Final target')}</th><th scope="col">${text('调整原因', 'Reason')}</th></tr></thead><tbody>${differences.map(row => `<tr><th scope="row">${e(asset(row.assetId).name)}</th><td class="decision-number">${weight(row.draftPct)}</td><td class="decision-number">${weight(row.targetPct)}</td><td>${e(t(row.reason, row.reasonEn))}</td></tr>`).join('')}</tbody></table></div></details>` : '';
    return `<section class="decision-allocation" aria-labelledby="decision-allocation-heading"><div class="decision-section-heading"><h3 id="decision-allocation-heading">${text('决策前 → 最终目标', 'Before → final target')}</h3><span>${text('公司与现金合计 100%', 'Companies + cash = 100%')}</span></div><div class="decision-table-wrap"><table class="decision-allocation-table"><caption class="sr-only">${text('各资产的决策前比例与最终目标配置；不是已成交持仓', 'Asset weights before this decision and final targets; not executed holdings')}</caption><thead><tr><th scope="col">${text('资产', 'Asset')}</th><th scope="col">${text('决策前', 'Before')}</th><th scope="col">${text('目标比例', 'Target weight')}</th><th scope="col">${text('变化', 'Change')}</th></tr></thead><tbody>${rows}</tbody></table></div><p class="decision-note">${text('目标比例属于本次决定。当前持仓以已记录的持仓快照为准。', 'Target weights belong to this decision. Current holdings remain those in the recorded portfolio snapshot.')}</p><div class="decision-reasons"><h3>${text('为什么这样配置', 'Why this allocation')}</h3><ol>${record.reasons.map(reason => `<li>${e(t(reason.zh, reason.en))}</li>`).join('')}</ol></div>${draft}</section>`;
  }

  function research(record) {
    const rows = record.reports.map((reference, index) => {
      const context = getReport(reference.companyId, reference.reportId, reference.version);
      if (context.manager.id !== record.managerId) throw new Error('Decision research belongs to another Manager');
      const route = { managerId: record.managerId, companyId: reference.companyId, view: 'report', reportId: reference.reportId, version: reference.version };
      const title = t(context.report.title || context.document.title, context.report.titleEn || context.report.title || context.document.title);
      return `<article class="decision-research-item" data-report-id="${e(reference.reportId)}"><header><span class="decision-asset">${companyIcon(context.company)}<span><strong>${e(context.company.name)}</strong><small>${e(context.company.ticker)}</small></span></span><span class="decision-report-meta"><time datetime="${e(context.report.publishedAt)}">${e(context.report.publishedAt)}</time> · ${e(reference.version)}</span></header>${link(route, `${e(title)} <span aria-hidden="true">↗</span>`, 'decision-report-link', `decision-report-${record.id}-${index}`)}<p>${e(t(reference.note, reference.noteEn))}</p><span class="decision-report-author">${text('研究作者', 'Research author')} · ${e(context.manager.name)}</span></article>`;
    }).join('');
    const unlinked = record.allocations.filter(row => row.assetId !== 'cash' && !record.reports.some(reference => reference.companyId === row.assetId));
    const gaps = unlinked.length ? `<div class="decision-research-gaps"><h4>${text('未附研究报告的配置', 'Allocations without an attached report')}</h4>${unlinked.map(row => `<div><strong>${e(asset(row.assetId).name)}</strong><p>${e(t(row.reason, row.reasonEn))}</p></div>`).join('')}</div>` : '';
    return `<section aria-labelledby="decision-research-heading"><div class="decision-section-heading"><h3 id="decision-research-heading">${text('本次决定参考的研究', 'Research used in this decision')}</h3><span>${record.reports.length} ${text('份固定版本', 'pinned versions')}</span></div><p class="decision-section-intro">${text('先看配置理由，再打开对应报告核对判断与证据。', 'Read the allocation rationale, then open the report to inspect its thesis and evidence.')}</p>${rows || `<p class="decision-empty">${text('此样本未关联研究报告。', 'This sample has no linked research report.')}</p>`}${gaps}</section>`;
  }

  function trackedRiskLink(record, item) {
    const tracked=getRiskForDecisionReview(record.managerId,record.id,item.id);
    return tracked?link({managerId:record.managerId,view:'risks',riskId:tracked.id,riskFilter:'all'},text('查看持续跟踪与最新证据 →','View ongoing tracking and latest evidence →'),'decision-risk-register-link',`decision-risk-track-${record.id}-${item.id}`):'';
  }

  function risk(record) {
    return `<section aria-labelledby="decision-risk-heading"><div class="decision-section-heading"><h3 id="decision-risk-heading">${text('风险意见与组合回应', 'Risk opinion and portfolio response')}</h3><span>${record.risks.length} ${text('项持续观察', 'under monitoring')}</span></div><p class="decision-section-intro">${text('已回应表示 PM 解释了处理方式；风险仍需持续观察。', 'A response records how the PM addressed the opinion. The risk remains under monitoring.')}</p>${record.risks.map(item => `<article class="decision-risk-item" data-risk-id="${e(item.id)}" data-risk-status="${e(item.status)}" data-response-status="${e(item.responseStatus)}"><header><h4>${e(t(item.title, item.titleEn))}</h4><span class="decision-risk-state">${riskLabel(item)}</span></header><div class="decision-risk-columns"><section><h5>${text('Risk Manager · 风险意见', 'Risk Manager · Opinion')}</h5><p>${e(t(item.opinion, item.opinionEn))}</p></section><section><h5>${text('Portfolio Manager · 回应', 'Portfolio Manager · Response')}</h5><p>${e(t(item.response, item.responseEn))}</p></section></div><div class="decision-follow-up"><span>${text('继续观察', 'Follow-up')}</span><p>${e(t(item.followUp, item.followUpEn))}</p></div>${trackedRiskLink(record,item)}</article>`).join('') || `<p class="decision-empty">${text('此样本没有已记录的风险意见；不代表风险为零。', 'This sample has no recorded risk opinion; it does not establish zero risk.')}</p>`}</section>`;
  }

  function main(route, state = {}, returnRoute = null) {
    if (route.view !== 'decisions' || !route.managerId || route.companyId || route.institutionId) throw new Error('An explicit Manager decisions view is required');
    formatRoute(route);
    const manager = getManager(route.managerId).manager;
    const records = getManagerDecisions(manager.id);
    const decisionId = route.decisionId ?? getFeaturedDecisionId(manager.id);
    if (decisionId === null) return `<section class="decision-empty" aria-label="${text('组合决策', 'Portfolio decisions')}"><h2>${text('尚无组合决策样本', 'No portfolio decision sample')}</h2><p>${text('该 Manager 还没有明确登记的组合决定。', 'No portfolio decision has been recorded for this Manager.')}</p></section>`;
    const record = getDecision(manager.id, decisionId);
    const tab = route.decisionTab ?? 'allocation';
    if (!tabNames.some(item => item[0] === tab)) throw new Error('Unknown decision tab');
    const back=returnRoute?.view==='risks'&&returnRoute.managerId===manager.id?link(returnRoute,text('← 返回风险跟踪','← Back to risk tracking'),'decision-return','decision-back-to-risk'):'';
    const paletteId = state.paletteId ?? DEFAULT_ALLOCATION_PALETTE;
    getAllocationPalette(paletteId);
    return `<div id="portfolio-decisions" class="decision-workspace" data-manager="${e(manager.id)}" data-decision="${e(record.id)}" data-decision-tab="${e(tab)}" data-simulated="true" style="${allocationPaletteStyle(paletteId)}">${directory(manager.id, records, record.id)}<article class="decision-detail" aria-labelledby="decision-title">${back}<header class="decision-detail-header"><div class="decision-kicker"><span>${text('组合决策 · 虚构样本', 'Portfolio decision · Fictional sample')}</span><time datetime="${e(record.date)}">${e(record.date)}</time></div><h2 id="decision-title">${e(t(record.title, record.titleEn))}</h2><p class="decision-lead">${e(t(record.summary, record.summaryEn))}</p><div class="decision-execution" data-execution-status="${e(record.execution.status)}"><span>${e(executionLabel(record.execution.status))}</span><p>${e(t(record.execution.summary, record.execution.summaryEn))}</p></div></header><nav class="decision-tabs" aria-label="${text('决策内容', 'Decision sections')}">${tabNames.map(([id, zh, en]) => link(decisionRoute(manager.id, record.id, id), `${text(zh, en)}${id === 'research' ? `<small>${record.reports.length}</small>` : id === 'risk' ? `<small>${record.risks.length}</small>` : ''}`, 'decision-tab', `decision-tab-${id}`, tab === id ? ' aria-current="page"' : '')).join('')}</nav><div class="decision-tab-content" id="decision-panel-${e(tab)}">${({ allocation, research, risk })[tab](record)}</div><p class="decision-source-note">${e(t(portfolioDecisionFixture.disclosure, portfolioDecisionFixture.disclosureEn))}</p></article></div>`;
  }

  function summary(managerId) {
    getManager(managerId);
    const decisionId = getFeaturedDecisionId(managerId);
    if (decisionId === null) return '';
    const record = getDecision(managerId, decisionId);
    return `<section class="decision-summary" data-decision-summary="${e(record.id)}" aria-label="${text('近期组合决策样本', 'Recent portfolio decision sample')}"><div class="decision-summary-main"><span>${text('组合决策', 'Decision')}</span>${link(decisionRoute(managerId, record.id), e(t(record.title, record.titleEn)), 'decision-summary-title', `decision-summary-${record.id}`)}</div><div class="decision-summary-meta"><span>${text('虚构样本', 'Fictional sample')} · ${e(record.date)} · ${e(executionLabel(record.execution.status))}</span>${link(decisionRoute(managerId, record.id, 'risk'), `${text('本次', 'This decision')} ${record.risks.length} ${text('条风险意见', 'risk opinions')}`, 'decision-summary-risk', `decision-summary-risk-${record.id}`)}</div></section>`;
  }

  return { main, summary };
}
