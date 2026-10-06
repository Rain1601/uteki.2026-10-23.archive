import { catalog, getManager, formatRoute, getReport } from './model.mjs';
import { DEFAULT_ALLOCATION_PALETTE, getAllocationPalette, allocationPaletteStyle } from './allocation-palettes.mjs';
import { getManagerResearchRows, getManagerExecutionHistory } from './manager-activity.mjs?v=20261004-focus-stages1';
import { getManagerCoverage } from './manager-coverage.mjs';

const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ordinaryViews=new Set(['overview','companies','reports','holdings','activity']);
const number=value=>new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(value);
const pct=value=>`${value>0?'+':''}${value.toFixed(2)}%`;

// Read-only projections of explicit design fixtures. Research progress is not a
// running-task feed, and trade examples never supply portfolio accounting.
export function createManagerViews({t,companyIcon,institutionContext=null,executionContext=null,coverageContext=null}) {
  const text=(zh,en)=>e(t(zh,en));
  const link=(route,label,cls='action-link',id='')=>`<a href="${e(formatRoute(route))}" class="${e(cls)}"${id?` id="${e(id)}"`:''}>${label}</a>`;
  const managerRoute=(managerId,view)=>({managerId,view});
  const reportRoute=(managerId,companyId,reportId,version,sectionId)=>({managerId,companyId,view:'report',reportId,version,...(sectionId?{sectionId}:{})});
  const empty=(title,description)=>`<div class="manager-empty"><h3>${e(title)}</h3><p>${e(description)}</p></div>`;
  const companyCell=company=>`<span class="manager-company-cell">${companyIcon(company)}<span><strong>${e(company.name)}</strong><small>${e(company.ticker)}</small></span></span>`;
  const stateLabel=status=>({unresolved:t('待验证','To verify'),review:t('待复核','Needs review'),researching:t('尚无报告','No report yet'),published:t('已发布','Published'),current:t('已发布','Published')})[status]||t('待核对','Needs checking');
  const badge=status=>`<span class="manager-row-state" data-status="${e(status)}">${e(stateLabel(status))}</span>`;
  const reportKind=kind=>kind==='main'?text('主报告','Main report'):text('专题','Topic');
  const reportStatus=status=>badge(status);
  const reportLink=(managerId,item,prefix='manager-report')=>link(reportRoute(managerId,item.company.id,item.document.id,item.report.version),e(item.document.title),'manager-output-link',`${prefix}-${item.document.id}-${item.report.version}`);
  function paging(items,page,size) {
    const pages=Math.max(1,Math.ceil(items.length/size));
    if(!Number.isInteger(page)||page<0||page>=pages) throw new Error('Manager list page is outside the selected result');
    return {rows:items.slice(page*size,(page+1)*size),page,pages,total:items.length,size};
  }
  function pager(result,kind) {
    return `<div class="manager-pagination"><span>${result.total?result.page*result.size+1:0}–${Math.min((result.page+1)*result.size,result.total)} / ${result.total}</span><div><button id="manager-${kind}-prev" data-action="manager-page" data-list="${kind}" data-page="${result.page-1}" ${result.page===0?'disabled':''} aria-label="${text('上一页','Previous page')}">←</button><span>${result.page+1} / ${result.pages}</span><button id="manager-${kind}-next" data-action="manager-page" data-list="${kind}" data-page="${result.page+1}" ${result.page===result.pages-1?'disabled':''} aria-label="${text('下一页','Next page')}">→</button></div></div>`;
  }
  function filters(kind,values,selected) {
    return `<div class="manager-filters" role="group" aria-label="${text('筛选列表','Filter list')}">${values.map(([id,label])=>`<button id="manager-${kind}-${e(id)}" data-action="manager-filter" data-list="${kind}" data-filter="${e(id)}" aria-pressed="${id===selected}">${e(label)}</button>`).join('')}</div>`;
  }
  function simulationFor(context) {
    if(!institutionContext) return null;
    const agent=institutionContext.agents.find(item=>item.managerId===context.manager.id);
    if(!agent) return null;
    const period=institutionContext.periods.find(item=>item.id===institutionContext.defaultPeriod);
    if(!period) throw new Error('Manager performance period is not available');
    return {agent,period,simulation:institutionContext.simulation};
  }
  function portfolioSummary(context) {
    const sample=simulationFor(context);
    if(!sample) return `<div class="manager-empty">${text('收益与持仓未接入；研究覆盖不代表持仓。','Returns and holdings are not connected; research coverage does not establish holdings.')}</div>`;
    const {agent,period,simulation}=sample;
    const holdings=agent.portfolio.holdings.map(item=>{
      const index=catalog.companies.findIndex(company=>company.id===item.companyId);
      if(index<0) throw new Error('Unknown company in selected Manager portfolio');
      return {...item,company:catalog.companies[index],color:`var(--holding-${index})`};
    });
    holdings.push({companyId:'cash',company:null,weightPct:agent.portfolio.cashWeightPct,color:'var(--holding-cash)'});
    return `<section class="manager-summary" aria-label="${text('表现摘要','Performance summary')}"><div class="manager-metrics"><div class="manager-metric"><span>${e(t(period.label,period.labelEn))}</span><strong class="${agent.returns[period.id]<0?'negative':'positive'}">${pct(agent.returns[period.id])}</strong><small>${text('模拟收益','Illustrative return')}</small></div><div class="manager-metric"><span>${text('组合市值','Portfolio value')}</span><strong>${number(agent.portfolio.totalValue)}</strong><small>${e(simulation.currency)}</small></div><div class="manager-metric"><span>${text('持仓公司','Holdings')}</span><strong>${agent.portfolio.holdings.length}</strong><small>${text('现金','Cash')} ${agent.portfolio.cashWeightPct.toFixed(1)}%</small></div></div><div class="manager-summary-identity"><span class="manager-sample-badge">${text('模拟数据 · 非实盘','Illustrative data · Not a live account')}</span><p>${e(period.start)} – ${e(period.end)}</p></div></section><section class="manager-allocation-band"><div class="manager-allocation-head"><span>${text('当前配置','Current allocation')}</span><time>${e(simulation.asOf)}</time></div><div class="manager-weight-strip" role="img" aria-label="${e(t('公司与现金的当前占比，合计 100%','Current company and cash weights, totaling 100%'))}">${holdings.filter(item=>item.weightPct>0).map(item=>`<span class="manager-weight-segment" style="--weight:${item.weightPct}%;--holding-color:${item.color}" title="${e(item.company?.name||t('现金','Cash'))} ${item.weightPct.toFixed(1)}%"></span>`).join('')}</div><div class="manager-weight-legend">${holdings.map(item=>`<span class="manager-weight-item" data-company="${e(item.companyId)}" style="--holding-color:${item.color}"><i aria-hidden="true"></i>${item.company?companyIcon(item.company):''}<span>${e(item.company?.name||t('现金','Cash'))}</span><strong>${item.weightPct.toFixed(1)}%</strong></span>`).join('')}</div></section>`;
  }
  function researchTable(context,state) {
    const filter=state.researchFilter??'all',rows=getManagerResearchRows(context.manager.id,filter),result=paging(rows,state.researchPage??0,6);
    const body=result.rows.map(row=>`<tr data-research-id="${e(row.id)}" data-research-type="${e(row.type)}"><td>${companyCell(row.company)}</td><td class="manager-subject"><strong lang="${row.titleEn?t('zh-CN','en'):'zh-CN'}">${e(t(row.title,row.titleEn||row.title))}</strong><small>${({question:text('跟进已有判断','Follow-up question'),report:text('研究产出','Research output')})[row.type]}</small></td><td>${badge(row.status)}</td><td><time>${e(row.date||'—')}</time></td><td><div class="manager-row-links">${row.links.length?row.links.map((item,index)=>link(item.route,`${reportKind(getReport(item.route.companyId,item.route.reportId,item.route.version).document.kind)} ${e(item.route.version)} ↗`,'manager-output-link',`manager-research-${e(row.id)}-${index}`)).join(''):`<span class="muted">${text('尚无产出','No output yet')}</span>`}</div></td></tr>`).join('');
    return `<section id="manager-research"><div class="manager-section-head"><div><h2>${text('研究进展','Research progress')}</h2><span>${text('关注什么，形成了什么','What is being studied and published')}</span></div>${filters('research',[['all',t('全部','All')],['open',t('待跟进','Follow up')],['published',t('已发布','Published')]],filter)}</div>${body?`<div class="manager-table-wrap"><table class="manager-table manager-research-table"><thead><tr><th>${text('公司','Company')}</th><th>${text('研究事项','Research item')}</th><th>${text('状态','Status')}</th><th>${text('更新','Updated')}</th><th>${text('相关产出','Related output')}</th></tr></thead><tbody>${body}</tbody></table></div>`:empty(t('暂无符合条件的研究事项','No matching research items'),t('切换筛选查看其他已有事项。','Change the filter to see other recorded items.'))}${pager(result,'research')}<p class="manager-footnote">${text('研究事项与报告来自演示资料；未接入实时任务执行。','Research items and reports use demo records; live task execution is not connected.')}</p></section>`;
  }
  function overview(context,state) {return portfolioSummary(context)+researchTable(context,state);}
  function companies(context) {
    if(!coverageContext) return empty(t('关注清单未接入','Focus list is not connected'),t('当前、历史和未来关注需要明确记录，不能从公司目录或持仓推断。','Current, past and planned focus require explicit records; a company directory or portfolio cannot establish them.'));
    const coverage=getManagerCoverage(context.manager.id,coverageContext);
    const stages=[
      ['current',t('当前关注','Current focus'),t('正在持续跟进的公司','Companies being followed now'),t('暂无当前关注的公司','No companies currently followed')],
      ['history',t('历史关注','Past focus'),t('已结束关注，保留研究记录','Past coverage and retained research'),t('暂无历史关注记录','No past focus recorded')],
      ['planned',t('未来关注','Planned focus'),t('已明确列入后续研究计划','Explicitly planned for future research'),t('暂无已登记的关注计划','No future focus recorded')],
    ];
    const groups=stages.map(([stage,label,description,noRecords])=>{
      const cards=coverage.records.filter(item=>item.stage===stage).map(item=>{
        const entries=item.reports;
        const dateLabel=stage==='current'?t('开始关注','Following since'):stage==='history'?t('关注期间','Followed during'):t('加入计划','Planned on');
        const date=stage==='current'?item.since:stage==='history'?`${item.since} – ${item.endedAt}`:item.addedAt;
        const reason=t(item.reason,item.reasonEn);
        return `<article class="manager-coverage-card" data-company="${e(item.companyId)}" data-stage="${stage}"><header>${companyCell(item.company)}<span class="manager-coverage-report-count">${entries.length?`${entries.length} ${text('份报告','reports')}`:text('尚无报告','No report yet')}</span></header><p class="manager-coverage-reason">${e(reason)}</p><div class="manager-coverage-date"><span>${e(dateLabel)}</span><time>${e(date)}</time></div>${entries.length?`<footer class="manager-coverage-footer"><button id="manager-coverage-${e(item.companyId)}" data-action="manager-company-reports" data-company="${e(item.companyId)}">${stage==='history'?text('查阅报告','Read reports'):text('研究产出','View reports')} ↗</button></footer>`:''}</article>`;
      }).join('');
      return `<section class="manager-coverage-group" data-stage="${stage}" aria-labelledby="coverage-heading-${stage}"><div class="manager-coverage-group-head"><h3 id="coverage-heading-${stage}">${e(label)} <span>${coverage.counts[stage]}</span></h3><p>${e(description)}</p></div><div class="manager-coverage-group-body">${cards||`<p class="manager-coverage-empty">${e(noRecords)}</p>`}</div></section>`;
    }).join('');
    return `<div class="manager-section-head"><div><h2>${text('研究覆盖','Research coverage')}</h2><span>${coverage.total} ${text('家公司 · 仅展示明确关注','companies · explicitly recorded focus')}</span></div><span class="manager-sample-badge">${text('模拟关注清单','Illustrative focus list')} · ${e(coverage.asOf)}</span></div><div class="manager-coverage-groups">${groups}</div><p class="manager-footnote">${text('关注阶段与持仓独立；计划关注不代表已产出报告。','Focus stages are independent of holdings; planned focus does not imply a published report.')}</p>`;
  }
  function reports(context,state) {
    const companyId=state.reportCompany??'all';
    const companies=[...new Map(context.reports.map(item=>[item.company.id,item.company])).values()];
    if(companyId!=='all'&&!companies.some(item=>item.id===companyId)) throw new Error('Report filter company has no reports by this Manager');
    const rows=context.reports.filter(item=>companyId==='all'||item.company.id===companyId).sort((a,b)=>b.report.publishedAt.localeCompare(a.report.publishedAt));
    const result=paging(rows,state.reportPage??0,8);
    return `<div class="manager-section-head"><div><h2>${text('研究报告','Research reports')}</h2><span>${rows.length} ${text('份独立产出 · 版本不重复计数','distinct outputs · versions are not counted as separate outputs')}</span></div></div>${filters('reports',[['all',t('全部公司','All companies')],...companies.map(company=>[company.id,company.name])],companyId)}${rows.length?`<div class="manager-table-wrap"><table class="manager-table manager-report-table"><thead><tr><th>${text('公司','Company')}</th><th>${text('报告','Report')}</th><th>${text('版本','Version')}</th><th>${text('发布','Published')}</th><th>${text('状态','Status')}</th></tr></thead><tbody>${result.rows.map(item=>`<tr><td>${companyCell(item.company)}</td><td class="manager-subject">${reportLink(context.manager.id,item)}<small>${reportKind(item.document.kind)}</small></td><td>${e(item.report.version)}</td><td><time>${e(item.report.publishedAt)}</time></td><td>${reportStatus(item.report.status)}</td></tr>`).join('')}</tbody></table></div>`:empty(t('尚无正式报告','No formal reports yet'),t('已覆盖不等于已发布；产出就绪后在这里展示。','Coverage does not imply publication. Reports appear here when available.'))}${pager(result,'reports')}`;
  }
  function activity(context,state) {
    if(!executionContext) return empty(t('操作历史未接入','Activity history is not connected'),t('已有研究覆盖与持仓不能替代买卖记录。','Research coverage and holdings cannot substitute for trade records.'));
    const kind=state.activityKind??'all';
    const data=getManagerExecutionHistory({managerId:context.manager.id,kind},executionContext);
    const result=paging(data.events,state.activityPage??0,8);
    const rows=result.rows.map(event=>`<tr data-execution-id="${e(event.id)}" data-kind="${e(event.kind)}"><td><time>${e(event.date)}</time></td><td>${companyCell(event.company)}</td><td><span class="manager-event-code" data-kind="${e(event.kind)}">${({buy:'B',sell:'S',report:'R'})[event.kind]}</span> ${e(({buy:t('买入','Buy'),sell:t('卖出','Sell'),report:t('报告','Report')})[event.kind])}</td><td class="manager-subject"><strong>${e(t(event.title,event.titleEn||event.title))}</strong></td><td><div class="manager-row-links">${event.links.length?event.links.map((item,index)=>link(item.route,`${text('阅读','Read')} ${e(item.route.version)} ↗`,'manager-output-link',`manager-execution-${event.id}-${index}`)).join(''):`<span class="muted">—</span>`}</div></td></tr>`).join('');
    return `<div class="manager-section-head"><div><h2>${text('操作历史','Activity history')}</h2><span class="manager-sample-badge">${text('模拟事件 · 非实盘','Illustrative events · Not live trading')}</span></div>${filters('activity',[['all',t('全部','All')],['buy',t('买入','Buy')],['sell',t('卖出','Sell')],['report',t('报告','Reports')]],kind)}</div>${rows?`<div class="manager-table-wrap"><table class="manager-table manager-execution-table"><thead><tr><th>${text('日期','Date')}</th><th>${text('公司','Company')}</th><th>${text('动作','Action')}</th><th>${text('记录','Record')}</th><th>${text('产出','Output')}</th></tr></thead><tbody>${rows}</tbody></table></div>`:empty(t('暂无符合筛选的记录','No matching records'),t('当前样本未提供，不代表真实活动为零。','No records in this sample; this does not establish zero real activity.'))}${pager(result,'activity')}<p class="manager-footnote">${text('买卖为独立模拟事件，未提供成交价和数量；报告可打开对应历史版本。','Trades are independent examples without execution price or quantity; reports open their exact historical versions.')}</p>`;
  }
  function main(route,state={}) {
    if(!ordinaryViews.has(route.view)) throw new Error('Manager view: unsupported view; reports use the shared reader');
    const context=getManager(route.managerId),paletteId=state.paletteId??DEFAULT_ALLOCATION_PALETTE;
    getAllocationPalette(paletteId);
    const body=({overview,companies,reports,holdings:activity,activity})[route.view](context,state);
    return `<div id="manager-workspace" class="manager-workspace" data-manager="${e(context.manager.id)}" style="${allocationPaletteStyle(paletteId)}">${body}</div>`;
  }
  function context(route) {
    const result = getManager(route.managerId);
    const { manager, reports, events } = result;
    const coverage=coverageContext?getManagerCoverage(manager.id,coverageContext):null;
    const unresolved = events.filter(item=>item.event.unresolved).length;
    return { title:t('Manager 上下文','Manager context'), body:`<div class="eyebrow">${text('投资角色 · 虚构样本','Investment role · Fictional sample')}</div><h3>${e(manager.name)}</h3><dl><dt>${text('投资风格 / 期限','Style / horizon')}</dt><dd lang="zh-CN">${e(manager.style)} · ${e(manager.horizon)}</dd><dt>${text('方法版本','Method version')}</dt><dd>${e(manager.methodVersion)}</dd><dt>${text('研究覆盖 / 报告','Coverage / reports')}</dt><dd>${coverage?`${coverage.total} ${text('家公司','companies')}`:text('关注清单未接入','Focus list not connected')} · ${reports.length} ${text('份独立报告','distinct reports')}</dd><dt>${text('关联的未解决研究事件','Linked unresolved research events')}</dt><dd>${unresolved} ${text('项演示事件，非未读数','sample events, not unread')}</dd></dl><p lang="zh-CN">${e(manager.description)}</p><h4 class="small-heading">${text('数据与归属','Data & ownership')}</h4><p>${coverage?text('本页关注阶段来自明确登记的模拟清单，关注不代表持仓。','Focus stages use an explicitly recorded sample list; focus does not imply holdings.'):text('关注清单未接入。','Focus list is not connected.')} ${text('组合来自独立机构样本，真实账户未接入。','Portfolios use a separate institution fixture; live accounts are not connected.')}</p><p>${text('报告列表只展示该 Manager 的产物。从此入口阅读报告，保留 Manager 身份和固定版本。','The report list contains this Manager’s research only. Reading preserves the Manager entry and the selected report version.')}</p><div class="related-links">${link(managerRoute(manager.id,'companies'),text('研究公司 →','Research companies →'),'related-link')}${link(managerRoute(manager.id,'reports'),text('研究报告 →','Research reports →'),'related-link')}</div>` };
  }

  return { main, context };
}
