import { catalog, getInstitution, getCompany, getManager, getManagerCompanyReport, getReport, formatRoute } from './model.mjs';
import { ALLOCATION_PALETTES, DEFAULT_ALLOCATION_PALETTE, getAllocationPalette, allocationPaletteStyle } from './allocation-palettes.mjs';
import { createAllocationHistoryViews } from './allocation-history-view.mjs?v=20261004-investment-timeline2';
import { createPerformanceGeometry } from './performance-geometry.mjs';
import { createInvestmentEventViews } from './investment-event-view.mjs?v=20261004-investment-timeline2';

const e=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const agentColors=['#416aa2','#a67d60','#719581','#8b7ca3','#639ba5','#a57586'];
const pct=value=>`${value>0?'+':''}${value.toFixed(2)}%`;
const tone=value=>value<0?'negative':value>0?'positive':'neutral';
const amount=value=>new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(value);

export function createInstitutionViews({t,companyIcon}) {
  const events=createInvestmentEventViews({t,companyIcon});
  const history=createAllocationHistoryViews({t,companyIcon});
  const link=(route,label,cls='',id='')=>`<a ${id?`id="${e(id)}"`:''} class="${e(cls)}" href="${e(formatRoute(route))}">${label}</a>`;
  const checked=route=>{
    if(!route.institutionId||route.view!=='overview'||route.companyId||route.managerId) throw new Error('An explicit institution overview is required');
    return getInstitution(route.institutionId);
  };
  function display(route,state={}) {
    const data=checked(route),periodId=state.period===undefined?data.defaultPeriod:state.period;
    const palette=getAllocationPalette(state.paletteId===undefined?DEFAULT_ALLOCATION_PALETTE:state.paletteId);
    const period=data.periods.find(item=>item.id===periodId);
    if(!period) throw new Error('Unknown institution display period');
    const agentId=state.agentId===undefined?data.defaultAgentId:state.agentId;
    const agents=data.agents.map((agent,index)=>{
      const value=agent.returns[period.id],series=agent.series?.[period.id];
      if(!Number.isFinite(value)||!Array.isArray(series)||series.length<2) throw new Error('Agent performance is missing for selected period');
      return {...agent,manager:getManager(agent.managerId).manager,value,series,color:agentColors[index%agentColors.length]};
    });
    const agent=agents.find(item=>item.managerId===agentId);
    if(!agent) throw new Error('Agent is not in the institution');
    // Research coverage and the institution's portfolio never supply agent holdings.
    const portfolio=agent.portfolio;
    const holdings=portfolio.holdings.map(holding=>({...holding,id:holding.companyId,company:getCompany(holding.companyId).company,color:`var(--holding-${catalog.companies.findIndex(company=>company.id===holding.companyId)%palette.light.length})`}));
    holdings.push({id:'cash',companyId:null,weightPct:portfolio.cashWeightPct,marketValue:portfolio.cashValue,color:'var(--holding-cash)'});
    const selected=state.holdingId===null||state.holdingId===undefined?null:holdings.find(item=>item.id===state.holdingId);
    if(state.holdingId!==null&&state.holdingId!==undefined&&!selected) throw new Error('Holding is not in the selected Agent portfolio');
    return {data,period,agents,agent,portfolio,holdings,selected,palette};
  }
  function chart(period,agents,selectedId) {
    const benchmark=period.series.map(point=>({date:point.date,value:point.benchmarkValue-100}));
    const {minimum,maximum,x,y}=createPerformanceGeometry(period,agents);
    const path=series=>series.map((point,index)=>`${index?'L':'M'}${x(point.date).toFixed(2)},${y(point.value).toFixed(2)}`).join(' ');
    const grid=[maximum,(maximum+minimum)/2,minimum].filter((value,index,items)=>items.indexOf(value)===index).map(value=>`<line x1="42" x2="976" y1="${y(value)}" y2="${y(value)}" class="chart-grid"/><text x="33" y="${y(value)+4}" text-anchor="end" class="chart-axis-label">${value>0?'+':''}${value.toFixed(1)}%</text>`).join('');
    const curves=agents.map(agent=>{
      const d=path(agent.series.map(point=>({date:point.date,value:point.value-100}))),selected=agent.managerId===selectedId;
      return `<g id="institution-curve-group-${e(agent.managerId)}" class="agent-curve ${selected?'is-selected':''}" data-agent="${e(agent.managerId)}" style="--agent-color:${agent.color}"><path d="${d}" class="agent-line" fill="none"/><circle id="institution-curve-end-${e(agent.managerId)}" cx="976" cy="${y(agent.value)}" r="${selected?3.5:2.5}" class="chart-end"/><path id="institution-curve-${e(agent.managerId)}" d="${d}" class="agent-line-hit" data-action="institution-agent" data-agent="${e(agent.managerId)}" fill="none" stroke="transparent" stroke-width="16" pointer-events="stroke"/></g>`;
    }).join('');
    return `<svg class="institution-chart" viewBox="0 0 1000 140" aria-hidden="true" focusable="false">${grid}<line x1="42" x2="976" y1="${y(0)}" y2="${y(0)}" class="chart-zero"/><path d="${path(benchmark)}" class="benchmark-line" fill="none" pointer-events="none"/>${curves}<text x="42" y="134">${e(period.start)}</text><text x="976" y="134" text-anchor="end">${e(period.end)}</text></svg>`;
  }
  function eventOptionsFor(period,agent,state) {
    return {agentId:agent.managerId,period,kind:state.eventKind===undefined?'all':state.eventKind,granularity:state.eventGranularity===undefined?'auto':state.eventGranularity,width:state.eventWidth===undefined?1000:state.eventWidth};
  }
  function trades(route,state,groupIds=[]) {
    const {period,agents,agent}=display(route,state);
    return events.trades({...eventOptionsFor(period,agent,state),groupIds},createPerformanceGeometry(period,agents));
  }
  function thumbnail(agent,period) {
    const values=agent.series.map(point=>point.value),min=Math.min(...values),span=Math.max(...values)-min||1;
    const first=Date.parse(period.start),duration=Date.parse(period.end)-first;
    const d=agent.series.map((point,index)=>`${index?'L':'M'}${(4+(Date.parse(point.date)-first)/duration*68).toFixed(2)},${(19-(point.value-min)/span*16).toFixed(2)}`).join(' ');
    return `<strong>${e(agent.manager.name)}</strong><svg class="portfolio-thumbnail-chart" viewBox="0 0 76 22" aria-hidden="true" focusable="false"><path d="${d}" fill="none"/></svg><small>${pct(agent.value)}</small>`;
  }
  // Filled annular sectors give every slice its own non-overlapping hit area.
  function sector(start,angle) {
    const point=(radius,degrees)=>{const a=(degrees-90)*Math.PI/180;return [70+radius*Math.cos(a),70+radius*Math.sin(a)].map(n=>n.toFixed(3)).join(',');};
    const gap=angle>=359.999?0:Math.min(.7,angle*.08),a=start+gap/2,b=start+angle-gap/2;
    if(angle>=359.999) return `M${point(61,a)} A61,61 0 1 1 ${point(61,a+180)} A61,61 0 1 1 ${point(61,a+360)} L${point(43,a+360)} A43,43 0 1 0 ${point(43,a+180)} A43,43 0 1 0 ${point(43,a)} Z`;
    const large=b-a>180?1:0;
    return `M${point(61,a)} A61,61 0 ${large} 1 ${point(61,b)} L${point(43,b)} A43,43 0 ${large} 0 ${point(43,a)} Z`;
  }
  function allocation(holdings,selected,currency) {
    let start=0;
    const slices=holdings.map(holding=>{
      const angle=holding.weightPct*3.6,d=angle>0?sector(start,angle):null;start+=angle;
      if(!d) return '';
      const name=holding.company?.name||t('现金','Cash'),weight=holding.weightPct.toFixed(1)+'%',value=t('市值','Value')+' · '+currency+' '+amount(holding.marketValue),active=selected?.id===holding.id;
      return `<path id="allocation-slice-${e(holding.id)}" class="allocation-segment ${active?'is-emphasized':selected?'is-muted':''}" d="${d}" fill="${holding.color}" role="button" tabindex="0" aria-pressed="${active}" aria-label="${e(name+' · '+weight+' · '+value)}" data-action="institution-holding" data-holding="${e(holding.id)}" data-name="${e(name)}" data-weight="${weight}" data-value="${e(value)}"/>`;
    }).join('');
    const name=selected?(selected.company?.name||t('现金','Cash')):t('组合配置','Allocation');
    const value=selected?selected.weightPct.toFixed(1)+'%':'100%';
    const hint=t('悬停查看 · 点击选中','Hover to inspect · Click to select');
    return `<div class="allocation-visual"><svg id="institution-donut" viewBox="0 0 140 140" role="group" aria-label="${e(t('持仓配置；可选择公司或现金查看占比和市值','Portfolio allocation; select a company or cash to inspect its weight and value'))}">${slices}</svg><div class="allocation-center"><strong id="allocation-value" data-default="100%">${value}</strong><span id="allocation-name" data-default="${e(t('组合配置','Allocation'))}">${e(name)}</span></div></div><p id="allocation-caption" class="allocation-caption" data-default="${e(hint)}">${selected?e(t('市值','Value')+' · '+currency+' '+amount(selected.marketValue)):hint}</p>`;
  }
  function holdingResearch(holding,agent) {
    const company=holding.company,body=companyIcon(company)+`<span><strong>${e(company.name)}</strong><small>${e(company.ticker)}</small></span>`;
    const result=getManagerCompanyReport(agent.managerId,company.id);
    if(result.status==='available') return link(result.route,body+'<span class="holding-report-arrow" aria-hidden="true">↗</span>','institution-company-link',`institution-company-${holding.id}`);
    if(result.status==='missing') return `<span id="institution-company-${e(holding.id)}" class="institution-company-link report-unavailable">${body}<small class="holding-report-gap">${t('暂无该 Agent 报告','No report by this agent')}</small></span>`;
    return `<details class="holding-report-options"><summary id="institution-company-${e(holding.id)}" class="institution-company-link">${body}<small>${result.routes.length} ${t('份报告','reports')}</small></summary><div class="holding-report-menu">${result.routes.map(target=>link(target,e(getReport(target.companyId,target.reportId,target.version).document.title)+' · '+e(target.version),'holding-report-option')).join('')}</div></details>`;
  }
  function palettePicker(holdings,selectedPalette) {
    let start=0;
    const slices=holdings.map(holding=>{
      const angle=holding.weightPct*3.6,d=angle>0?sector(start,angle):null;start+=angle;
      return d?`<path d="${d}" fill="${holding.color}"/>`:'';
    }).join('');
    return `<div class="allocation-palette-picker"><span class="allocation-palette-label">${t('配色','Palette')}</span><div class="allocation-palette-options" role="group" aria-label="${t('选择饼图配色','Choose allocation palette')}">${ALLOCATION_PALETTES.map(palette=>{
      const recommended=palette.id===DEFAULT_ALLOCATION_PALETTE;
      return `<button id="allocation-palette-${palette.id}" class="allocation-palette-option" data-action="allocation-palette" data-palette="${palette.id}" aria-pressed="${palette.id===selectedPalette.id}" aria-controls="institution-donut" aria-label="${e(t(palette.name,palette.nameEn)+(recommended?t(' · 推荐',' · Recommended'):''))}"><svg class="allocation-palette-preview" viewBox="0 0 140 140" aria-hidden="true" focusable="false" style="${allocationPaletteStyle(palette.id)}">${slices}</svg><span class="allocation-palette-copy"><span class="allocation-palette-name">${t(palette.name,palette.nameEn)}${recommended?`<small>${t('推荐','Recommended')}</small>`:''}</span><span class="allocation-palette-description">${t(palette.description,palette.descriptionEn)}</span></span><span class="allocation-palette-check" aria-hidden="true">✓</span></button>`;
    }).join('')}</div></div>`;
  }
  function main(route,state={},part=null) {
    const {data,period,agents,agent,portfolio,holdings,selected,palette}=display(route,state),{simulation}=data;
    const eventOptions=eventOptionsFor(period,agent,state);
    const legend=agents.map(item=>`<button id="institution-agent-${e(item.managerId)}" class="institution-agent-selector ${item.managerId===agent.managerId?'is-selected':''}" data-action="institution-agent" data-agent="${e(item.managerId)}" aria-pressed="${item.managerId===agent.managerId}" aria-controls="institution-portfolio" title="${e(t('单击选中 · 双击展开持仓','Click to select · Double-click to explore holdings'))}" style="--agent-color:${item.color}"><i aria-hidden="true"></i><span>${e(item.manager.name)}</span><strong data-agent-return="${e(item.managerId)}">${pct(item.value)}</strong></button>`).join('');
    const thumbnails=agents.map(item=>`<button id="institution-slide-${e(item.managerId)}" class="portfolio-thumbnail ${item.managerId===agent.managerId?'is-selected':''}" data-action="institution-agent" data-agent="${e(item.managerId)}" aria-pressed="${item.managerId===agent.managerId}" aria-controls="portfolio-stage" aria-label="${e(`${item.manager.name} · ${t(period.label,period.labelEn)} ${pct(item.value)} · ${t('查看组合','View portfolio')}`)}" title="${e(item.manager.name+' · '+t('双击展开持仓','Double-click to explore holdings'))}" style="--agent-color:${item.color}">${thumbnail(item,period)}</button>`).join('');
    const rows=holdings.map(holding=>`<div id="institution-holding-${e(holding.id)}" data-allocation-row="${e(holding.id)}" class="institution-holding-row ${selected?.id===holding.id?'is-active':''}"><span class="holding-swatch" style="--holding-color:${holding.color}"></span>${holding.company?holdingResearch(holding,agent):`<span class="institution-company-link"><span class="cash-symbol">${e(simulation.currency==='USD'?'$':simulation.currency)}</span><span><strong>${t('现金','Cash')}</strong><small>${e(simulation.currency)}</small></span></span>`}<button id="allocation-${e(holding.id)}" class="holding-weight" data-action="institution-holding" data-holding="${e(holding.id)}" data-name="${e(holding.company?.name||t('现金','Cash'))}" data-weight="${holding.weightPct.toFixed(1)}%" data-value="${e(t('市值','Value')+' · '+simulation.currency+' '+amount(holding.marketValue))}" aria-pressed="${selected?.id===holding.id}" aria-label="${e(`${holding.company?.name||t('现金','Cash')} · ${holding.weightPct.toFixed(1)}% · ${t('在配置图中查看','Show in allocation')}`)}">${holding.weightPct.toFixed(1)}%<span class="holding-weight-bar" style="--weight:${holding.weightPct}%;--holding-color:${holding.color}"></span></button></div>`).join('');
    const position=agents.findIndex(item=>item.managerId===agent.managerId)+1,disabled=agents.length<2?'disabled':'';
    const historyOptions={institutionId:route.institutionId,managerId:agent.managerId,period,paletteId:palette.id};
    const chartBody=state.historyOpen?history.main(historyOptions,{date:state.historyDate||undefined}):`<div id="investment-controls-host">${events.controls(eventOptions)}</div><div id="investment-chart-surface" class="investment-chart-surface"><div id="investment-performance-plot" class="investment-performance-plot">${chart(period,agents,agent.managerId)}<div id="investment-trades-host" class="investment-trades-host" role="group" aria-label="${t('收益曲线上的买卖记录','Trades on the return curve')}">${events.trades(eventOptions,createPerformanceGeometry(period,agents))}</div></div><div id="investment-timeline-host">${events.timeline({...eventOptions,showControls:false})}</div><div id="investment-event-guide" class="investment-event-guide" hidden aria-hidden="true"></div></div>`;
    const portfolioBody=`<div class="portfolio-stage-heading"><div class="portfolio-stage-identity"><span class="avatar" aria-hidden="true">${e(agent.manager.name[0])}</span><div><h3>${e(agent.manager.name)} <span>Portfolio</span></h3><p lang="zh-CN">${e(agent.manager.style)}</p></div></div><div class="portfolio-stage-return"><strong class="${tone(agent.value)}" data-selected-agent-return="${e(agent.managerId)}">${pct(agent.value)}</strong><small>${e(t(period.label,period.labelEn))} · ${t('模拟收益','Illustrative return')}</small></div>${link({managerId:agent.managerId,view:'overview'},`${t('Agent 详情','Agent details')} ↗`,'portfolio-detail-link','institution-agent-details')}</div><div class="portfolio-snapshot"><span>${t('当前持仓','Current holdings')} · ${e(simulation.asOf)}</span><span> · ${portfolio.holdings.length} ${t('家公司','companies')} + ${t('现金','cash')}</span></div><div class="institution-portfolio-body"><div class="institution-holdings">${rows}</div><div class="institution-allocation">${allocation(holdings,selected,simulation.currency)}<div class="institution-portfolio-value"><span>${t('模拟组合市值','Illustrative portfolio value')}</span><strong>${e(simulation.currency)} ${amount(portfolio.totalValue)}</strong></div></div></div>${palettePicker(holdings,palette)}<p class="institution-section-note">${t('公司名称直达该 Agent 的报告；饼图与持仓比例可联动查看。','Company names open this agent’s report; explore allocation through the chart or weights.')}</p>`;
    if(part==='portfolio') return portfolioBody;
    if(part==='chart') return chartBody;
    return `<div id="institution-dashboard" class="institution-dashboard" data-selected-agent="${e(agent.managerId)}" data-history-open="${!!state.historyOpen}" data-allocation-palette="${palette.id}" style="${allocationPaletteStyle(palette.id)}">
      <section id="institution-performance" class="institution-performance" tabindex="-1"><div class="institution-chart-controls"><div class="institution-comparison-heading"><h2 id="institution-chart-title">${state.historyOpen?t('持仓时间轴','Allocation timeline'):t('投资表现','Investment performance')}</h2><p id="institution-chart-subtitle">${state.historyOpen?t('逐次记录的公司占比与变化','Company weights at each recorded date'):t('同一区间，从 0% 开始比较','Same period, compared from 0%')}</p></div><div class="institution-performance-actions"><button id="allocation-history-open" class="allocation-history-open" data-action="allocation-history-open" aria-expanded="${!!state.historyOpen}">${t('展开持仓','Explore holdings')} ↗</button><div class="institution-periods" role="group" aria-label="${t('收益区间','Performance period')}">${data.periods.map(item=>`<button id="institution-period-${e(item.id)}" data-action="institution-period" data-period="${e(item.id)}" aria-pressed="${item.id===period.id}">${e(t(item.label,item.labelEn))}</button>`).join('')}</div></div></div><div class="institution-agent-legend" role="group" aria-label="${e(t(`${t(period.label,period.labelEn)}模拟收益；选择 Agent 查看持仓`,`${t(period.label,period.labelEn)} illustrative returns; select an agent to view holdings`))}">${legend}<span class="institution-benchmark-legend"><i aria-hidden="true"></i>${t('模拟基准','Simulated benchmark')}<strong data-benchmark-return="${period.benchmarkReturnPct}">${pct(period.benchmarkReturnPct)}</strong></span></div><div id="institution-chart-body">${chartBody}</div></section>
      <section id="institution-portfolio" class="institution-portfolio" tabindex="-1" aria-label="${t('Agent 组合','Agent portfolios')}"><div class="institution-portfolio-layout"><div class="portfolio-thumbnails" aria-label="${t('手动切换 Agent 组合','Select an agent portfolio manually')}"><button id="institution-prev" class="portfolio-step" data-action="institution-step" data-step="-1" aria-label="${t('上一个 Agent','Previous agent')}" ${disabled}><span aria-hidden="true">↑</span></button><div class="portfolio-thumbnail-list" role="group" aria-label="${t('Agent 组合缩略图','Agent portfolio previews')}">${thumbnails}</div><button id="institution-next" class="portfolio-step" data-action="institution-step" data-step="1" aria-label="${t('下一个 Agent','Next agent')}" ${disabled}><span aria-hidden="true">↓</span></button><span id="institution-position" class="portfolio-position" aria-label="${e(t(`第 ${position} 个，共 ${agents.length} 个 Agent`,`Agent ${position} of ${agents.length}`))}">${String(position).padStart(2,'0')} / ${String(agents.length).padStart(2,'0')}</span></div>
      <div id="portfolio-stage" class="portfolio-stage" data-agent="${e(agent.managerId)}" style="--agent-color:${agent.color}">${portfolioBody}</div></div></section>
      <p class="institution-footer-note">${t('收益区间用于比较表现；持仓显示所标日期的最新快照。所有数值仅用于页面设计。','The selected period compares performance; holdings remain the latest snapshot dated above. All figures are for interface design only.')}</p></div>`;
  }
  function sidebar(route) { checked(route);return ''; }
  function header(route) {
    const {institution,simulation}=checked(route);
    return `<div class="company-heading institution-heading"><h1>${e(t(institution.name,institution.nameEn))}</h1><button id="institution-simulation-label" class="simulation-label" data-action="context" title="${e(t('设计模拟数据，非实盘；查看数据说明','Illustrative data, not a live account; view details'))}">${t('模拟数据 · 非实盘','Illustrative · Not live')}</button></div><div class="institution-header-meta">${t('截至','As of')} ${e(simulation.asOf)} <span>· ${e(simulation.currency)}</span></div>`;

  }
  function context(route) {
    const {simulation}=checked(route);
    return {title:t('总览的数据说明','About this overview'),body:`<h3>${t('模拟表现与组合展示','Illustrative performance and portfolios')}</h3><p>${t('收益、持仓与基准均为明确选定的设计样本，不代表实盘账户、历史业绩或投资承诺。','Returns, holdings and benchmarks are explicitly selected design fixtures, not live accounts, historical performance or investment promises.')}</p><dl><dt>${t('样本版本','Fixture version')}</dt><dd>${e(simulation.id)} · ${e(simulation.version)}</dd><dt>${t('持仓日期 / 币种','Holdings date / currency')}</dt><dd>${e(simulation.asOf)} · ${e(simulation.currency)}</dd></dl><p>${t('上方各 Agent 与基准使用相同区间，收益从区间起点的 0% 开始比较。基准只用于参照；点击 Agent 曲线、图例或缩略图，会选择下方对应的独立组合。鼠标经过只辅助辨认，不改变组合。','Agents and the benchmark use the same period and compare returns from 0% at its start. The benchmark is a reference only. Select an agent’s curve, legend or preview to show its independent portfolio below; hovering does not change the selected portfolio.')}</p><p>${t('组合面板显示所标日期的最新快照。双击 Agent 或点展开持仓，可在原位查看独立的模拟配置历史；日期预览不修改当前组合。模拟持仓来自明确的组合样本，不从研究覆盖推断；事件轴单独展示标注为模拟的买入、卖出与报告记录；不提供交易执行操作。','The portfolio panel shows the latest snapshot dated above. Double-click an Agent or choose Explore holdings to inspect an independent simulated allocation history. Previewing a date does not modify the current portfolio. Illustrative portfolios come from explicit fixtures, not research coverage. The event timeline separately shows illustrative buys, sells and reports; it does not execute trades.')}</p>`};
  }
  return {main,sidebar,header,context,events,history,trades,portfolio:(route,state)=>main(route,state,'portfolio'),chartBody:(route,state)=>main(route,state,'chart')};
}
