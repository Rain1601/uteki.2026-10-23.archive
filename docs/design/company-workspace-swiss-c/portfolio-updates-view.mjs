import { getCompany, formatRoute } from './model.mjs?v=20261006-risk1';
import { getManagerDecisions } from './portfolio-decisions.mjs';
import { getManagerRisks } from './risk-register.mjs';

const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

export function createPortfolioUpdatesView({t}) {
  const filters=[['all','全部','All'],['decision','决策','Decisions'],['risk','风险','Risks']];
  const statusLabels={pending:['未执行','Not executed'],not_required:['无需交易','No trade required'],needs_review:['待复核','Needs review'],monitoring:['持续观察','Monitoring'],resolved:['已结束','Closed']};
  return (managerId,filter='all') => {
    if(!filters.some(([id])=>id===filter)) throw new Error('Unknown portfolio follow-up filter');
    const rows=[
      ...getManagerDecisions(managerId).map(record=>({record,kind:'decision',date:record.date,status:record.execution.status,route:{managerId,view:'decisions',decisionId:record.id,decisionTab:'allocation'}})),
      ...getManagerRisks(managerId).map(record=>({record,kind:'risk',date:record.updatedAt,status:record.status,route:{managerId,view:'risks',riskId:record.id,riskFilter:'all'}})),
    ].sort((a,b)=>b.date.localeCompare(a.date)||a.kind.localeCompare(b.kind)||a.record.id.localeCompare(b.record.id));
    const items=rows.map(({record,kind,date,status,route})=>{
      const labels=statusLabels[status];
      if(!labels) throw new Error('Portfolio update status is unavailable');
      const companies=record.companyIds.map(id=>getCompany(id).company.name).join(' · ');
      return `<li id="portfolio-update-${kind}-${escape(record.id)}" data-followup-kind="${kind}" data-update-id="${escape(record.id)}" data-update-status="${escape(status)}" ${filter!=='all'&&filter!==kind?'hidden':''}>
        <a id="portfolio-update-link-${escape(record.id)}" class="portfolio-update-link" href="${escape(formatRoute(route))}">
          <span class="portfolio-update-topline"><span class="portfolio-update-tag">${t(kind==='decision'?'决策':'风险',kind==='decision'?'Decision':'Risk')}</span><time datetime="${date}">${date}</time><span class="portfolio-update-status">${escape(t(...labels))}</span></span>
          <strong class="portfolio-update-title">${escape(t(record.title,record.titleEn))}</strong>
          <span class="portfolio-update-meta">${t('虚构样本','Fictional sample')} · ${escape(companies)}</span>
        </a>
      </li>`;
    }).join('');
    return `<section id="portfolio-followups" class="portfolio-followups" aria-label="${t('组合动态','Portfolio updates')}">
      <header class="portfolio-followups-heading"><h3>${t('组合动态','Portfolio updates')}</h3><div role="group" aria-label="${t('动态类型','Update type')}">${filters.map(([id,zh,en])=>`<button id="portfolio-followup-${id}" data-action="portfolio-followup-filter" data-filter="${id}" aria-pressed="${filter===id}" aria-controls="portfolio-followup-list">${t(zh,en)}</button>`).join('')}</div></header>
      <ul id="portfolio-followup-list" class="portfolio-followup-list" tabindex="0" aria-label="${t('决策与风险记录','Decision and risk records')}">${items}<li id="portfolio-updates-empty" class="portfolio-updates-empty" ${rows.some(row=>filter==='all'||row.kind===filter)?'hidden':''}>${t('暂无对应记录','No matching records')}</li></ul>
    </section>`;
  };
}
