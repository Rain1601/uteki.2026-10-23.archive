import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { catalog, formatRoute, parseRoute, getReport, getInstitution, getManager, getManagerCompanyReport } from './model.mjs';
import { INSTITUTION_DEMO_SCOPE } from './institution-data.mjs';
import { getManagerRisks, getRisk, getFeaturedRiskId } from './risk-register.mjs';
import { getManagerDecisions, getFeaturedDecisionId, getDecision } from './portfolio-decisions.mjs';
import { createRenderer, escapeHTML } from './render.mjs';
import { createManagerViews } from './manager-view.mjs';
import { createController, DEMO_LAUNCH } from './app.mjs';
import { ALLOCATION_PALETTES, allocationPaletteStyle } from './allocation-palettes.mjs';
import { getInvestmentEvents } from './investment-events.mjs';
import { createInvestmentEventViews } from './investment-event-view.mjs';
import { getManagerResearchRows, getManagerExecutionHistory } from './manager-activity.mjs';
import { getManagerCoverage, managerCoverageFixture } from './manager-coverage.mjs';

const registry=JSON.parse(readFileSync(new URL('../../../apps/uteki_zero/assets/companies/registry.json',import.meta.url),'utf8'));
const decode=s=>s.replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/&#39;/g,"'");
const tagAttributes=tag=>Object.fromEntries([...tag.replace(/^<\/?[\w-]+\s*/, '').matchAll(/([\w:-]+)(?:="([^"]*)")?/g)].map(([,name,value])=>[name,value===undefined?'':decode(value)]));
const tags=html=>[...html.matchAll(/<[a-zA-Z][^>]*>/g)].map(match=>tagAttributes(match[0]));

test('typography switches in place and persists across route, language and theme changes without altering research scope',()=>{
  const storage=new Map(),route={companyId:'alphabet',managerId:'north',view:'report',reportId:'alpha-north-main',version:'v1'};
  const h=harness(formatRoute(route),false,storage),content=h.nodes.get('content'),reader=h.nodes.get('report-title');
  const html=content.innerHTML,history=[...h.historyCalls],select=h.nodes.get('typography-select');
  assert.equal(h.controller.getState().typography,'swiss');
  content.scrollTop=310;select.focus();select.value='hybrid';h.listeners.change({target:select});
  assert.equal(h.controller.getState().typography,'hybrid');
  assert.equal(h.document.documentElement.dataset.typography,'hybrid');
  assert.equal(h.document.activeElement,select);assert.equal(h.nodes.get('report-title'),reader);
  assert.equal(content.innerHTML,html);assert.equal(content.scrollTop,310);
  assert.deepEqual(h.controller.getState().route,route);assert.deepEqual(h.historyCalls,history);
  assert.equal(JSON.parse(storage.get('uteki.company-design-swiss-c.display')).typography,'hybrid');
  clickAction(h,'theme-button','theme');clickAction(h,'language-button','language');
  assert.equal(h.controller.getState().typography,'hybrid');
  assert.match(h.nodes.get('toolbar').innerHTML,/value="hybrid" selected/);
  h.controller.navigate({managerId:'field',view:'overview'});
  assert.equal(h.document.documentElement.dataset.typography,'hybrid');
  const reloaded=harness(formatRoute(route),false,storage);
  assert.equal(reloaded.controller.getState().typography,'hybrid');
});

test('unknown typography selections are rejected and unavailable storage does not prevent a temporary display choice',()=>{
  const key='uteki.company-design-swiss-c.display';
  const h=harness('',false,new Map([[key,JSON.stringify({typography:'unavailable'})]]));
  assert.equal(h.controller.getState().typography,'swiss');
  const before={...h.controller.getState()},select=h.nodes.get('typography-select');
  for(const value of ['','unknown',null]) {
    select.value=value;h.listeners.change({target:select});
    assert.deepEqual(h.controller.getState(),before);assert.equal(select.value,'swiss');
  }
  const donut=h.nodes.get('institution-donut');
  h.window.localStorage.setItem=()=>{throw new Error('Storage disabled');};
  select.value='editorial';h.listeners.change({target:select});
  assert.equal(h.controller.getState().typography,'editorial');
  assert.equal(h.nodes.get('institution-donut'),donut);
  assert.match(h.nodes.get('announcement').textContent,/仅本次页面生效/);
});

test('font reflow retains a visible report paragraph instead of rebuilding the reader',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v1'}));
  const content=h.nodes.get('content');content.scrollTop=220;
  const paragraph={isConnected:true,getBoundingClientRect(){const top=content.top+(h.document.documentElement.dataset.typography==='hybrid'?370:310)-content.scrollTop;return {top,bottom:top+45,height:45};}};
  const originalQuery=content.querySelectorAll.bind(content);
  content.querySelectorAll=selector=>selector==='.report-section p,.report-section li,.citation'?[paragraph]:originalQuery(selector);
  const y=paragraph.getBoundingClientRect().top,reader=h.nodes.get('report-title');
  const select=h.nodes.get('typography-select');select.value='hybrid';h.listeners.change({target:select});
  assert.equal(content.scrollTop,280);assert.equal(paragraph.getBoundingClientRect().top,y);
  assert.equal(h.nodes.get('report-title'),reader);
});

test('Agent single clicks preserve targets, double click opens allocation history, and Back restores the same scope',()=>{
  const h=chartHarness(),content=h.nodes.get('content'),history=[...h.historyCalls];
  const legend=h.nodes.get('institution-agent-field'),curve=h.nodes.get('institution-curve-field');
  content.scrollTop=35;
  clickAction(h,legend.id,'institution-agent',{agent:'field'});
  for(const node of [legend,curve]) assert.equal(h.nodes.get(node.id),node,'first click keeps the double-click target alive');
  assert.equal(h.controller.getState().institutionAgent,'field');
  const portfolio=h.nodes.get('institution-donut');
  clickAction(h,legend.id,'institution-agent',{agent:'field'});
  assert.equal(h.nodes.get('institution-donut'),portfolio,'repeat selection is an idempotent no-op');
  h.listeners.dblclick({target:legend,preventDefault(){}});
  assert.equal(h.controller.getState().allocationHistoryOpen,true);
  assert.ok(h.nodes.get('allocation-history'));
  assert.equal(h.nodes.get('institution-donut'),portfolio);
  assert.equal(h.controller.getState().panel,null);
  assert.equal(content.scrollTop,0);assert.deepEqual(h.historyCalls,history);
  clickAction(h,'allocation-history-back','allocation-history-close');
  assert.equal(h.controller.getState().allocationHistoryOpen,false);
  assert.ok(h.nodes.get('investment-chart-surface'));
  assert.equal(h.controller.getState().institutionAgent,'field');
  assert.equal(h.document.activeElement,legend);assert.equal(content.scrollTop,35);
});

test('allocation history date inspection leaves latest holdings unchanged and resets scoped dates on Agent or period switch',()=>{
  const h=chartHarness();
  clickAction(h,'allocation-history-open','allocation-history-open');
  const root=h.nodes.get('allocation-history'),donut=h.nodes.get('institution-donut');
  const dateButton=h.nodes.get('content').querySelectorAll('[data-action="allocation-history-snapshot"]').find(node=>node.tagName==='BUTTON');
  assert.ok(dateButton);
  const before=h.controller.getState().allocationHistoryDate;
  h.listeners.pointerover({target:dateButton,pointerType:'mouse',relatedTarget:null});
  assert.equal(h.controller.getState().allocationHistoryDate,before,'hover does not change the dated allocation');
  clickAction(h,dateButton.id,'allocation-history-snapshot',{date:dateButton.dataset.date});
  assert.equal(h.controller.getState().allocationHistoryDate,dateButton.dataset.date);
  assert.equal(h.nodes.get('institution-donut'),donut);
  assert.equal(h.nodes.get('allocation-history'),root);
  assert.match(h.nodes.get('allocation-history-detail').innerHTML,new RegExp(dateButton.dataset.date));
  clickAction(h,'allocation-palette-vivid','allocation-palette',{palette:'vivid'});
  assert.equal(h.nodes.get('allocation-history'),root);assert.equal(h.controller.getState().allocationHistoryDate,dateButton.dataset.date);
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  assert.equal(h.controller.getState().allocationHistoryOpen,true);assert.equal(h.controller.getState().allocationHistoryDate,null);
  assert.match(h.nodes.get('institution-chart-body').innerHTML,/Eaton/);
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  assert.equal(h.controller.getState().allocationHistoryOpen,true);
  assert.equal(h.nodes.get('allocation-history').dataset.selectedDate,'2026-09-30');
  h.listeners.keydown({key:'Escape',target:h.nodes.get('allocation-history-back'),preventDefault(){}});
  assert.equal(h.controller.getState().allocationHistoryOpen,false);
  assert.equal(h.controller.getState().institutionPeriod,'1m');assert.equal(h.controller.getState().institutionAgent,'field');
});

test('history date arrow navigation is manual, bounded and keeps the current portfolio intact',()=>{
  const h=chartHarness();
  clickAction(h,'allocation-history-open','allocation-history-open');
  const dates=h.nodes.get('content').querySelectorAll('[data-action="allocation-history-snapshot"]');
  const donut=h.nodes.get('institution-donut'),root=h.nodes.get('allocation-history');
  const press=(target,key)=>{let handled=false;h.listeners.keydown({target,key,preventDefault(){handled=true;}});return handled;};
  assert.equal(press(dates.at(-1),'Home'),true);
  assert.equal(h.controller.getState().allocationHistoryDate,dates[0].dataset.date);
  assert.equal(h.document.activeElement,dates[0]);
  assert.match(h.nodes.get('allocation-history-detail').innerHTML,/暂无前序比较/);
  press(dates[0],'ArrowRight');
  assert.equal(h.controller.getState().allocationHistoryDate,dates[1].dataset.date);
  assert.equal(h.document.activeElement,dates[1]);
  assert.match(h.nodes.get('allocation-history-detail').innerHTML,new RegExp(`data-previous-date="${dates[0].dataset.date}"`));
  press(dates[1],'End');press(dates.at(-1),'ArrowRight');
  assert.equal(h.controller.getState().allocationHistoryDate,dates.at(-1).dataset.date);
  assert.equal(h.document.activeElement,dates.at(-1));
  assert.equal(h.nodes.get('institution-donut'),donut);assert.equal(h.nodes.get('allocation-history'),root);
  assert.equal(press(h.nodes.get('content'),'ArrowLeft'),false,'reading keys outside date controls stay native');
});

test('curve trade markers and lower report markers remain separate through filters, resize and Agent switching',()=>{
  const h=chartHarness(),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  const nodes=id=>h.nodes.get(id).querySelectorAll('[data-action="investment-event-group"]');
  const trades=()=>nodes('investment-trades-host'),reports=()=>nodes('investment-timeline-host');
  assert.ok(trades().length);assert.ok(reports().length);
  assert.ok(trades().every(node=>node.dataset.lane==='trade'&&node.dataset.kind!=='report'));
  assert.ok(reports().every(node=>node.dataset.lane==='report'&&node.dataset.kind==='report'));
  clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
  const curve=h.nodes.get('institution-curve-north'),donut=h.nodes.get('institution-donut');
  const marker=trades()[0];
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  const active=h.controller.getState().investmentEvent;
  const period=data.periods.find(item=>item.id===h.controller.getState().institutionPeriod);
  const event=getInvestmentEvents({managerId:'north',start:period.start,end:period.end}).events.find(item=>item.id===active.eventId);
  assert.notEqual(event.kind,'report');
  const card=h.nodes.get('investment-event-popover').innerHTML;
  assert.ok(card.includes(event.date));assert.match(card,/标记位置为组合收益/);
  h.nodes.get('investment-performance-plot').getBoundingClientRect=()=>({top:0,bottom:100,width:500,height:100,left:0,right:500});
  h.triggerResize('content');
  assert.equal(h.nodes.get('investment-event-popover').innerHTML,card);
  assert.ok(trades().some(node=>node.getAttribute('aria-expanded')==='true'));
  clickAction(h,'investment-kind-report','investment-event-kind',{kind:'report'});
  assert.equal(trades().length,0);assert.ok(reports().length);
  clickAction(h,'investment-kind-buy','investment-event-kind',{kind:'buy'});
  assert.equal(reports().length,0);assert.ok(trades().every(node=>node.dataset.kind==='buy'));
  assert.equal(h.nodes.get('institution-curve-north'),curve);assert.equal(h.nodes.get('institution-donut'),donut);assertHoldingSelection(h,'cash');
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  assert.ok(trades().length);assert.ok(trades().every(node=>node.dataset.group.includes('field-')&&!node.dataset.group.includes('north-')));
  assert.equal(h.nodes.get('institution-curve-north'),curve);
});

test('event collision grouping uses the plot column width, not the full two-column dashboard',()=>{
  const h=chartHarness();
  h.geometry.set('institution-dashboard',{top:0,bottom:700,width:1200,height:700,left:0,right:1200});
  h.geometry.set('investment-performance-plot',{top:0,bottom:182.4,width:380,height:182.4,left:0,right:380});
  h.triggerResize('content');
  const state=h.controller.getState(),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  const options={agentId:state.institutionAgent,period:data.periods.find(item=>item.id===state.institutionPeriod),kind:state.eventKind,granularity:state.eventGranularity};
  const view=createInvestmentEventViews({t:(zh,en)=>en,companyIcon:()=>''});
  const narrow=view.groups({...options,width:380}).map(group=>group.id).sort();
  const full=view.groups({...options,width:1200}).map(group=>group.id).sort();
  assert.notDeepEqual(narrow,full,'the sample has enough density to expose a wrong width source');
  const actual=['investment-trades-host','investment-timeline-host'].flatMap(id=>h.nodes.get(id).querySelectorAll('[data-action="investment-event-group"]').map(node=>node.dataset.group)).sort();
  assert.deepEqual(actual,narrow);
});

test('palette selection updates colors in place, persists across visits, and preserves portfolio and report scope',()=>{
  const storage=new Map(),h=harness('',false,storage);
  clickAction(h,'allocation-alphabet','institution-holding',{holding:'alphabet'});
  const content=h.nodes.get('content'),dashboard=h.nodes.get('institution-dashboard'),donut=h.nodes.get('institution-donut');
  const slice=h.nodes.get('allocation-slice-alphabet'),report=h.nodes.get('institution-company-alphabet').getAttribute('href');
  const before=h.controller.getState(),history=[...h.historyCalls];content.scrollTop=270;
  for(const palette of ALLOCATION_PALETTES) {
    const button=h.nodes.get(`allocation-palette-${palette.id}`);button.focus();
    clickAction(h,button.id,'allocation-palette',{palette:palette.id});
    assert.equal(h.controller.getState().allocationPalette,palette.id);
    assert.equal(h.nodes.get('allocation-palette-current').textContent,palette.name);
    assert.equal(h.nodes.get('institution-dashboard'),dashboard);assert.equal(h.nodes.get('institution-donut'),donut);
    assert.equal(h.nodes.get('allocation-slice-alphabet'),slice);assert.equal(content.scrollTop,270);
    assert.equal(h.document.activeElement,button);assertHoldingSelection(h,'alphabet');
    assert.equal(dashboard.getAttribute('style'),allocationPaletteStyle(palette.id));
    assert.equal(h.nodes.get('institution-company-alphabet').getAttribute('href'),report);
    for(const option of ALLOCATION_PALETTES) assert.equal(h.nodes.get(`allocation-palette-${option.id}`).getAttribute('aria-pressed'),String(option.id===palette.id));
    assert.equal(h.controller.getState().institutionAgent,before.institutionAgent);
    assert.equal(h.controller.getState().institutionPeriod,before.institutionPeriod);
  }
  assert.deepEqual(h.historyCalls,history);
  assert.equal(harness('',false,storage).controller.getState().allocationPalette,'vivid');
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  assert.equal(h.nodes.get('institution-dashboard').getAttribute('style'),allocationPaletteStyle('vivid'));
  clickAction(h,'theme-button','theme');assert.equal(h.document.documentElement.dataset.theme,'dark');
  clickAction(h,'language-button','language');assert.equal(h.controller.getState().allocationPalette,'vivid');
  const prior={...h.controller.getState()},style=h.nodes.get('institution-dashboard').getAttribute('style');
  clickAction(h,'allocation-palette-classic','allocation-palette',{palette:'unknown'});
  assert.deepEqual(h.controller.getState(),prior);assert.equal(h.nodes.get('institution-dashboard').getAttribute('style'),style);
});

test('invalid stored palettes use the visual default and unavailable storage retains an honest session-only choice',()=>{
  const storage=new Map([['uteki.company-design-swiss-c.allocation-palette','unknown']]);
  const h=harness('',false,storage);assert.equal(h.controller.getState().allocationPalette,'bright');
  h.window.localStorage.setItem=()=>{throw new Error('Storage disabled');};
  clickAction(h,'allocation-palette-jewel','allocation-palette',{palette:'jewel'});
  assert.equal(h.controller.getState().allocationPalette,'jewel');
  assert.match(h.nodes.get('announcement').textContent,/仅本次页面生效/);
});

test('investment event filters and grouping preserve portfolio selection and reject invalid scope atomically',()=>{
  const h=harness(''),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  const content=h.nodes.get('content');content.scrollTop=225;
  clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
  const donut=h.nodes.get('institution-donut'),curve=h.nodes.get('institution-curve-north'),history=[...h.historyCalls];
  for(const kind of ['buy','sell','report','all']) {
    clickAction(h,`investment-kind-${kind}`,'investment-event-kind',{kind});
    const host=h.nodes.get('investment-timeline-host');
    assert.equal(h.controller.getState().eventKind,kind);
    assert.equal(h.nodes.get(`investment-kind-${kind}`).getAttribute('aria-pressed'),'true');
    assertHoldingSelection(h,'cash');assert.equal(h.nodes.get('institution-donut'),donut);
    assert.equal(h.nodes.get('institution-curve-north'),curve);assert.equal(content.scrollTop,225);
    assert.ok(!host.innerHTML.includes('data-agent="field"'));
  }
  for(const value of ['day','week','month','auto']) {
    const target=h.nodes.get('investment-event-granularity');target.value=value;
    h.listeners.change({target});assert.equal(h.controller.getState().eventGranularity,value);
    assert.equal(h.document.activeElement.id,'investment-event-granularity');
  }
  const before=h.controller.getState(),html=h.nodes.get('investment-timeline-host').innerHTML;
  clickAction(h,'investment-kind-all','investment-event-kind',{kind:'unknown'});
  assert.deepEqual(h.controller.getState(),before);assert.equal(h.nodes.get('investment-timeline-host').innerHTML,html);
  const invalid=h.nodes.get('investment-event-granularity');invalid.value='unknown';h.listeners.change({target:invalid});
  assert.deepEqual(h.controller.getState(),before);assert.equal(invalid.value,'auto');
  assert.deepEqual(h.historyCalls,history);
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  assert.equal(h.nodes.get('investment-timeline').dataset.agent,'field');
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  const period=data.periods.find(item=>item.id==='1m');
  assert.equal(h.nodes.get('investment-timeline').dataset.granularity,'day');
  assert.ok(getInvestmentEvents({managerId:'field',start:period.start,end:period.end}).events.every(event=>event.managerId==='field'));
});

test('investment markers open an anchored card without a sidebar and preserve historical reports and return scope',()=>{
  const h=chartHarness();
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  clickAction(h,'investment-kind-report','investment-event-kind',{kind:'report'});
  const marker=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]')[0];
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  assert.equal(h.controller.getState().panel,null);
  assert.ok(h.controller.getState().investmentEvent);
  assert.equal(h.nodes.get('context-panel').hidden,true);
  assert.equal(h.nodes.get('workspace').classList.contains('panel-open'),false);
  const detail=h.nodes.get('investment-event-popover').innerHTML;
  assert.match(detail,/North/);assert.match(detail,/模拟事件/);
  const link=h.nodes.get('investment-report-north-report-main-v1');assert.ok(link);
  assert.deepEqual(parseRoute(link.getAttribute('href')),{managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v1'});
  const plot=h.nodes.get('investment-performance-plot');
  plot.getBoundingClientRect=()=>({top:0,bottom:100,width:1100,height:100,left:0,right:1100});
  h.triggerResize('content');
  assert.equal(h.nodes.get('investment-event-popover').innerHTML,detail,'resize keeps the card and exact report identity');
  const marked=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]').filter(node=>node.getAttribute('aria-expanded')==='true');
  assert.ok(marked.length,'resized groups still identify the events open in the details panel');
  link.focus();h.listeners.click({button:0,target:link,preventDefault(){}});
  assert.equal(h.controller.getState().route.version,'v1');assert.equal(h.controller.getState().route.managerId,'north');
  h.listeners.click({button:0,target:h.nodes.get('back-to-company'),preventDefault(){}});
  assert.deepEqual(h.controller.getState().route,INSTITUTION_DEMO_SCOPE);
  assert.equal(h.controller.getState().eventKind,'report');assert.equal(h.controller.getState().institutionPeriod,'1m');
  const next=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]')[0];
  clickAction(h,next.id,'investment-event-group',{group:next.dataset.group});
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  assert.equal(h.controller.getState().investmentEvent,null,'switching Agent closes the prior Agent event card');
  assert.equal(h.nodes.get('investment-timeline').dataset.agent,'field');
  const state=h.controller.getState(),visible=h.nodes.get('context-panel').innerHTML;
  const fieldMarker=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]')[0];
  clickAction(h,fieldMarker.id,'investment-event-group',{group:'foreign'});
  assert.deepEqual(h.controller.getState(),state);assert.equal(h.nodes.get('context-panel').innerHTML,visible);
});

test('an event group remains highlighted and can close its card after narrower chart width merges its marker',()=>{
  const h=chartHarness();
  const plot=h.nodes.get('investment-performance-plot');
  let width=1000;
  plot.getBoundingClientRect=()=>({top:0,bottom:100,width,height:100,left:0,right:width});
  h.triggerResize('content');
  const marker=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]')[0];
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  const original=h.nodes.get('investment-event-popover').innerHTML;
  width=600;h.triggerResize('content');
  const marked=h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]').filter(node=>node.getAttribute('aria-expanded')==='true');
  assert.ok(marked.length);assert.equal(h.nodes.get('investment-event-popover').innerHTML,original);
  clickAction(h,marked[0].id,'investment-event-group',{group:marked[0].dataset.group});
  assert.equal(h.controller.getState().investmentEvent,null);
  assert.ok(h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]').every(node=>node.getAttribute('aria-expanded')==='false'));
});

test('event cards support manual paging, outside dismissal and Escape without chart rebuilds or selection changes',()=>{
  const h=chartHarness(),content=h.nodes.get('content');
  clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
  content.scrollTop=40;
  const chart=h.nodes.get('institution-chart-surface'),donut=h.nodes.get('institution-donut'),history=[...h.historyCalls];
  const markers=()=>h.nodes.get('investment-timeline-host').querySelectorAll('[data-action="investment-event-group"]');
  const marker=markers().at(-1);
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  const first=h.controller.getState().investmentEvent.eventId;
  clickAction(h,'investment-popover-next','investment-popover-step',{step:'1'});
  assert.notEqual(h.controller.getState().investmentEvent.eventId,first);
  clickAction(h,'investment-popover-prev','investment-popover-step',{step:'-1'});
  assert.equal(h.controller.getState().investmentEvent.eventId,first);
  assert.equal(h.nodes.get('institution-chart-surface'),chart);assert.equal(h.nodes.get('institution-donut'),donut);
  assert.equal(content.scrollTop,40);assertHoldingSelection(h,'cash');assert.deepEqual(h.historyCalls,history);
  let prevented=false;
  h.listeners.keydown({key:'Escape',target:h.nodes.get('investment-popover-title'),preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(h.controller.getState().investmentEvent,null);
  assert.equal(h.document.activeElement.id,marker.id);
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  h.listeners.click({button:0,target:content,preventDefault(){}});
  assert.equal(h.controller.getState().investmentEvent,null);assert.equal(h.nodes.get('investment-event-popover').hidden,true);
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  h.geometry.set('investment-group-*',{top:-100,bottom:-68,left:200,right:262,width:62,height:32});
  h.listeners.scroll({target:content});
  assert.equal(h.controller.getState().investmentEvent,null,'scrolling the marker out of view dismisses the detached card');
});

test('content navigation stays scoped, marks one active category and coexists with entity menus without duplicate IDs',()=>{
  for(const language of ['zh','en']) {
    const render=createRenderer(language,registry);
    const routes=catalog.companies.flatMap(company=>[
      ...['overview','reports','materials','tracking'].map(view=>({companyId:company.id,view})),
      ...catalog.reports.filter(document=>document.companyId===company.id).map(document=>({companyId:company.id,view:'report',reportId:document.id,version:document.currentVersion})),
    ]);
    for(const route of routes) {
      const navigation=render.contentNavigation(route);
      const links=tags(navigation).filter(item=>item.class?.split(/\s+/).includes('content-tab'));
      assert.deepEqual(links.map(item=>parseRoute(item.href).view),['overview','reports','materials','tracking']);
      const active=links.filter(item=>item['aria-current']==='page');
      assert.equal(active.length,1);
      assert.equal(parseRoute(active[0].href).view,route.view==='report'?'reports':route.view);
      assert.equal(links.filter(item=>item.class.split(/\s+/).includes('active')).length,1);
      for(const item of links) {
        const target=parseRoute(item.href);
        assert.deepEqual(target,{companyId:route.companyId,view:target.view});
        assert.equal(item.id,`content-company-${route.companyId}-${target.view}`);
      }
      const together=navigation+render.sidebar(route)+render.main(route)+render.entityMenu(`company-${route.companyId}`,route)+(route.view==='overview'?render.panel(route,{kind:'changes'}):'');
      const ids=tags(together).filter(item=>item.id).map(item=>item.id);
      assert.equal(new Set(ids).size,ids.length,`overview, content navigation, hover menu and changes panel have distinct IDs for ${route.companyId}/${route.view}`);
    }
  }
});

test('Manager content navigation keeps the Manager dimension for categories and company-report reading',()=>{
  for(const language of ['zh','en']) for(const manager of catalog.managers) {
    const render=createRenderer(language,registry);
    const routes=[
      ...['overview','companies','reports','decisions','risks','holdings','activity'].map(view=>({managerId:manager.id,view})),
      ...catalog.reports.filter(document=>document.managerId===manager.id).map(document=>({managerId:manager.id,companyId:document.companyId,view:'report',reportId:document.id,version:document.currentVersion})),
    ];
    for(const route of routes) {
      const navigation=render.contentNavigation(route);
      const links=tags(navigation).filter(item=>item.class?.split(/\s+/).includes('content-tab'));
      assert.deepEqual(links.map(item=>parseRoute(item.href).view),['overview','companies','reports','decisions','risks','activity']);
      const active=links.filter(item=>item['aria-current']==='page');
      assert.equal(active.length,1);
      assert.equal(parseRoute(active[0].href).view,route.view==='report'?'reports':route.view==='holdings'?'activity':route.view);
      for(const item of links) {
        const target=parseRoute(item.href);
        assert.deepEqual(target,{managerId:manager.id,view:target.view});
        assert.equal(item.id,`content-manager-${manager.id}-${target.view}`);
      }
      const ids=tags(navigation+render.sidebar(route)+render.main(route)+render.entityMenu(`manager-${manager.id}`,route)).filter(item=>item.id).map(item=>item.id);
      assert.equal(new Set(ids).size,ids.length);
    }
  }
});

test('company overview has four bounded previews with full scoped counts, counting reports rather than versions',()=>{
  const render=createRenderer('zh',registry);
  assert.ok(catalog.reports.some(document=>document.versions.length>1),'the fixture distinguishes a report from its versions');
  for(const company of catalog.companies) {
    const html=render.main({companyId:company.id,view:'overview'});
    const modules=new Map([...html.matchAll(/<section\b[^>]*data-module="([^"]+)"[^>]*>([\s\S]*?)<\/section>/g)].map(([,name,body])=>[name,body]));
    assert.deepEqual([...modules.keys()].sort(),['changes','materials','reports','tracking']);
    const events=catalog.events.filter(event=>event.companyId===company.id);
    const reports=catalog.reports.filter(document=>document.companyId===company.id);
    const evidence=catalog.evidence.filter(item=>item.companyId===company.id);
    const expected={changes:events.length,reports:reports.length,materials:evidence.length,tracking:events.filter(event=>event.unresolved).length};
    for(const [name,body] of modules) {
      const elements=tags(body);
      const counts=elements.filter(item=>item['data-count']!==undefined);
      assert.equal(counts.length,1,`${name} exposes one complete count`);
      assert.equal(Number(counts[0]['data-count']),expected[name],`${company.id}/${name} count uses all records in scope`);
      const previews=elements.filter(item=>item.class?.split(/\s+/).includes('overview-item'));
      assert.equal(previews.length,Math.min(2,expected[name]),`${company.id}/${name} has a bounded preview`);
      for(const item of elements) {
        if(item.href?.startsWith('#'))assert.equal(parseRoute(item.href).companyId,company.id);
        if(item['data-event'])assert.ok(events.some(event=>event.id===item['data-event']));
        if(item['data-evidence'])assert.ok(evidence.some(source=>source.id===item['data-evidence']));
      }
    }
    assert.doesNotMatch(html,/\d+\s*(?:条|项|个)?\s*未读|\d+\s+unread\b/i);
    for(const event of catalog.events.filter(event=>event.companyId!==company.id))assert.ok(!html.includes(`data-event="${event.id}"`));
  }
});

const overviewKeys=['changes','research','materials','tracking'];
test('company overview discloses one labeled panel at a time with four accessible section tabs in both languages',()=>{
  for(const language of ['zh','en'])for(const company of catalog.companies)for(const selection of overviewKeys) {
    const render=createRenderer(language,registry);
    const elements=tags(render.main({companyId:company.id,view:'overview'},null,selection));
    const tabs=elements.filter(item=>item.role==='tab'),panels=elements.filter(item=>item.role==='tabpanel');
    assert.deepEqual(tabs.map(item=>item['data-section']),overviewKeys);
    assert.deepEqual(panels.map(item=>item['data-overview-section']),overviewKeys);
    for(const tab of tabs) {
      const key=tab['data-section'],selected=key===selection;
      assert.equal(tab.id,`overview-tab-${key}`);
      assert.equal(tab['data-action'],'overview-section');
      assert.equal(tab['aria-controls'],`overview-panel-${key}`);
      assert.equal(tab['aria-selected'],String(selected));
      assert.equal(tab.tabindex,selected?'0':'-1');
      const panel=panels.find(item=>item.id===tab['aria-controls']);
      assert.equal(panel['aria-labelledby'],tab.id);
      assert.equal('hidden' in panel,!selected);
    }
    assert.deepEqual(panels.filter(item=>!('hidden' in item)).map(item=>item['data-overview-section']),[selection]);
    assert.deepEqual(elements.filter(item=>item['data-action']==='overview-step').map(item=>item['data-step']),['-1','1']);
  }
  assert.throws(()=>createRenderer('zh',registry).main({companyId:'alphabet',view:'overview'},null,'unknown'),/overview section/i);
});

test('rendered entry links preserve the selected company and explicit report identity in both languages',()=>{
  for(const language of ['zh','en']) {
    const render=createRenderer(language,registry);
    for(const company of catalog.companies) {
      for(const view of ['overview','reports','materials','tracking']) {
        const route={companyId:company.id,view};
        const html=render.main(route);
        for(const match of html.matchAll(/href="(#[^"]+)"/g)) {
          const target=parseRoute(decode(match[1]));
          assert.equal(target.companyId,company.id);
          if(target.view==='report') assert.ok(target.reportId&&target.version);
        }
        assert.doesNotMatch(html,/undefined|\[object Object\]/);
      }
    }
  }
});

test('each event links to exactly its declared historical/current report sections',()=>{
  const render=createRenderer('zh',registry);
  for(const event of catalog.events) {
    const html=render.panel({companyId:event.companyId,view:'overview'},{kind:'event',eventId:event.id});
    const links=[...html.matchAll(/href="(#[^"]+)"/g)].map(m=>parseRoute(decode(m[1])));
    assert.deepEqual(links,event.affectedReports.map(link=>({companyId:event.companyId,view:'report',...link})));
  }
});

test('all report versions keep original full text, unique citation anchors and scoped evidence',()=>{
  for(const document of catalog.reports) for(const report of document.versions) {
    const render=createRenderer('zh',registry);
    const route={companyId:document.companyId,view:'report',reportId:document.id,version:report.version};
    const html=render.main(route);
    const ids=[...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]);
    assert.equal(new Set(ids).size,ids.length);
    for(const section of report.sections) {
      assert.ok(html.includes(section.title));
      assert.ok(html.includes(section.paragraphs[0]));
      for(const evidenceId of section.citations) {
        const evidence=catalog.evidence.find(item=>item.id===evidenceId);
        const panel=render.panel(route,{kind:'evidence',evidenceId,origin:'report'});
        assert.ok(panel.includes(evidence.sourceTitle));
        assert.ok(panel.includes(report.version));
      }
    }
    if(report.status==='review') assert.ok(html.includes(report.reviewNote));
  }
});

test('missing materials and unavailable evidence remain explicit',()=>{
  const render=createRenderer('zh',registry);
  assert.match(render.main({companyId:'nvidia',view:'overview'}),/不代表公司没有发生变化/);
  assert.match(render.main({companyId:'nvidia',view:'materials'}),/资料尚未接入/);
  const item=catalog.evidence.find(item=>item.availability==='unavailable');
  const html=render.panel({companyId:item.companyId,view:'materials'},{kind:'evidence',origin:'material',evidenceId:item.id});
  assert.match(html,/原文不可用/);
  assert.doesNotMatch(html,/<blockquote/);
  assert.match(html,/不预设报告采纳关系/);
  assert.match(render.main({companyId:'alphabet',view:'tracking'}),/没有(?:正在运行的任务|运行中的任务)/);
});

test('company detail workspaces start with a scoped directory and no implicit first-item selection',()=>{
  for(const language of ['zh','en'])for(const company of catalog.companies)for(const view of ['reports','materials','tracking']) {
    const html=createRenderer(language,registry).main({companyId:company.id,view}),elements=tags(html);
    assert.ok(elements.some(item=>item.id==='item-directory'));
    assert.ok(elements.some(item=>item.id==='workspace-detail'));
    assert.ok(!elements.some(item=>item.id==='report-title'||item.class?.split(/\s+/).includes('detail-article')));
    assert.ok(elements.some(item=>item.class?.split(/\s+/).includes('detail-placeholder')));
    assert.ok(!elements.some(item=>item.class?.split(/\s+/).includes('directory-row')&&['true','page'].includes(item['aria-current'])));
    const rows=elements.filter(item=>item['data-action']==='item-select');
    const expected=view==='materials'?catalog.evidence.filter(item=>item.companyId===company.id):view==='tracking'?catalog.events.filter(item=>item.companyId===company.id&&item.unresolved):[];
    assert.deepEqual(rows.map(item=>item['data-id']).sort(),expected.map(item=>item.id).sort());
    for(const row of rows)assert.equal(row['data-kind'],view==='materials'?'material':'tracking');
    assert.equal(new Set(elements.filter(item=>item.id).map(item=>item.id)).size,elements.filter(item=>item.id).length);
  }
});

test('material and question details preserve source gaps and exact report/evidence relationships',()=>{
  for(const language of ['zh','en']) {
    const render=createRenderer(language,registry);
    for(const item of catalog.evidence) {
      const route={companyId:item.companyId,view:'materials'},selection={kind:'material',id:item.id};
      const html=render.detail(route,selection);
      assert.ok(tags(html).some(tag=>tag.id==='detail-title'));
      for(const value of [item.sourceTitle,item.locator,item.publishedAt,item.availableAt,item.limitation])assert.ok(html.includes(escapeHTML(value)),`${item.id} preserves source metadata`);
      if(item.availability==='unavailable')assert.doesNotMatch(html,/<blockquote/);
      else {
        assert.ok(html.includes(escapeHTML(item.quote)));
        for(const paragraph of item.context)assert.ok(html.includes(escapeHTML(paragraph)));
      }
      const rows=tags(render.main(route,null,'changes',selection)).filter(tag=>tag['data-action']==='item-select');
      assert.deepEqual(rows.filter(tag=>tag['aria-current']==='true').map(tag=>tag['data-id']),[item.id]);
    }
    for(const event of catalog.events.filter(item=>item.unresolved)) {
      const route={companyId:event.companyId,view:'tracking'},selection={kind:'tracking',id:event.id};
      const html=render.detail(route,selection),elements=tags(html);
      for(const value of [event.title,event.reason,event.before,event.after])assert.ok(html.includes(escapeHTML(value)),`${event.id} preserves event context`);
      const links=elements.filter(item=>item.href?.startsWith('#')).map(item=>parseRoute(item.href));
      assert.deepEqual(links,event.affectedReports.map(link=>({companyId:event.companyId,view:'report',...link})));
      assert.deepEqual(elements.filter(item=>item['data-action']==='evidence').map(item=>item['data-evidence']).sort(),[...event.evidenceIds].sort());
      const rows=tags(render.main(route,null,'changes',selection)).filter(tag=>tag['data-action']==='item-select');
      assert.deepEqual(rows.filter(tag=>tag['aria-current']==='true').map(tag=>tag['data-id']),[event.id]);
    }
    const alpha=catalog.evidence.find(item=>item.companyId==='alphabet');
    for(const [route,selection] of [
      [{companyId:'microsoft',view:'materials'},{kind:'material',id:alpha.id}],
      [{companyId:'alphabet',view:'tracking'},{kind:'material',id:alpha.id}],
      [{companyId:'alphabet',view:'materials'},{kind:'tracking',id:catalog.events[0].id}],
      [{companyId:'alphabet',view:'materials'},{kind:'material',id:''}],
      [{companyId:'alphabet',view:'materials'},{kind:'material',id:'unknown'}],
      [{managerId:'north',view:'overview'},{kind:'material',id:alpha.id}],
    ])assert.throws(()=>render.detail(route,selection));
  }
});

test('company report reading retains its company directory and explicit historical version without changing other report identities',()=>{
  for(const language of ['zh','en'])for(const document of catalog.reports)for(const version of document.versions) {
    const render=createRenderer(language,registry),route={companyId:document.companyId,view:'report',reportId:document.id,version:version.version};
    const html=render.main(route),elements=tags(html),rows=elements.filter(item=>item.class?.split(/\s+/).includes('directory-row'));
    const reports=catalog.reports.filter(item=>item.companyId===document.companyId);
    assert.equal(rows.length,reports.length);
    assert.ok(elements.some(item=>item.id==='workspace-detail'));
    for(const item of reports) {
      const expected={companyId:item.companyId,view:'report',reportId:item.id,version:item.id===document.id?version.version:item.currentVersion};
      const row=rows.find(row=>parseRoute(row.href).reportId===item.id);
      assert.deepEqual(parseRoute(row.href),expected);
      assert.equal(row['aria-current']==='page',item.id===document.id);
    }
    for(const section of version.sections)for(const paragraph of section.paragraphs)assert.ok(html.includes(escapeHTML(paragraph)));
    const managerHtml=render.main({...route,managerId:document.managerId});
    assert.ok(!tags(managerHtml).some(item=>item.id==='item-directory'),'Manager report keeps its existing shared reader entry');
  }
});

// This minimal DOM adapter checks controller state transitions, not browser layout.
function harness(hash=formatRoute(DEMO_LAUNCH),deferRaf=false,values=new Map()) {
  const nodes=new Map(), listeners={}, windowListeners={},geometry=new Map();
  const document={activeElement:null,documentElement:{dataset:{}},getElementById:id=>nodes.get(id)||null,
    addEventListener:(name,fn)=>{listeners[name]=fn;}};
  class Element {
    constructor(id,owner=null) {
      this.id=id;this.owner=owner;this.scrollTop=0;this.dataset={};this.style={};this.attributes={};this.children=[];this.isConnected=true;this.top=0;this._html='';this.hidden=false;
      this.tagName='DIV';this.classes=new Set();
      this.classList={add:(...names)=>names.forEach(name=>this.classes.add(name)),remove:(...names)=>names.forEach(name=>this.classes.delete(name)),contains:name=>this.classes.has(name),toggle:(name,force)=>{
        const enabled=force===undefined?!this.classes.has(name):force;
        if(enabled)this.classes.add(name);else this.classes.delete(name);return enabled;
      }};
      nodes.set(id,this);
    }
    set innerHTML(html) {
      const remove=child=>{for(const nested of child.children)remove(nested);child.isConnected=false;nodes.delete(child.id);};
      for(const child of this.children) remove(child);
      this.children=[];this._html=html;
      // Retain nearest-ID ancestry so hidden panels and focus containment can be tested.
      const stack=[this];
      for(const [tag] of html.matchAll(/<\/?[a-zA-Z][^>]*>/g)) {
        if(tag.startsWith('</')) {if(stack.length>1)stack.pop();continue;}
        const tagName=tag.match(/^<([\w-]+)/)[1].toUpperCase(),attributes=tagAttributes(tag);
        let owner=stack.at(-1);
        if(attributes.id) {
          const child=new Element(attributes.id,owner);child.tagName=tagName;owner.children.push(child);
          for(const [name,value] of Object.entries(attributes))child.setAttribute(name,value);
          owner=child;
        }
        if(!/^(AREA|BASE|BR|COL|EMBED|HR|IMG|INPUT|LINK|META|PARAM|SOURCE|TRACK|WBR)$/.test(tagName)&&!tag.endsWith('/>'))stack.push(owner);
      }
    }
    get innerHTML(){return this._html;}
    focus(){document.activeElement=this;}
    setSelectionRange(start,end){this.selectionStart=start;this.selectionEnd=end;}
    contains(node){for(let current=node;current;current=current.owner)if(current===this)return true;return false;}
    matches(selector) {
      return selector.split(',').some(part=>{
        let value=part.trim();
        const excluded=value.match(/:not\(([^)]+)\)/);
        if(excluded&&this.matches(excluded[1]))return false;
        if(excluded)value=value.replace(excluded[0],'');
        // This adapter supports the simple selectors used by controller interaction handlers.
        if(value.includes(' '))return false;
        const id=value.match(/#([\w-]+)/)?.[1];if(id&&this.id!==id)return false;
        const tag=value.match(/^[a-zA-Z][\w-]*/)?.[0];if(tag&&this.tagName!==tag.toUpperCase())return false;
        for(const [,name] of value.matchAll(/\.([\w-]+)/g))if(!this.classes.has(name))return false;
        for(const [,name,operator,expected] of value.matchAll(/\[([\w-]+)(?:(\^?=)["']?([^\]"']*)["']?)?\]/g)) {
          const actual=name.startsWith('data-')?this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]:this.attributes[name];
          if(actual===undefined)return false;
          if(operator==='='&&actual!==expected)return false;
          if(operator==='^='&&!actual.startsWith(expected))return false;
        }
        return true;
      });
    }
    closest(selector){
      if(selector==='.entity-row')return this.id.startsWith('row-')?this:this.owner?.closest(selector)||null;
      if(selector==='#global-nav')return this.id==='global-nav'?this:this.owner?.closest(selector)||null;
      if(selector==='button[data-action]')return this.tagName==='BUTTON'&&this.dataset.action?this:this.owner?.closest(selector)||null;
      return this.matches(selector)?this:this.owner?.closest(selector)||null;
    }
    querySelectorAll(selector){return this.children.flatMap(child=>[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]);}
    querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
    setAttribute(name,value){
      this.attributes[name]=String(value);
      if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]=String(value);
      if(name==='class')this.classes=new Set(String(value).split(/\s+/));
      if(name==='hidden')this.hidden=true;
      if(name==='inert')this.inert=true;
      if(name==='tabindex')this.tabIndex=Number(value);
      if(name==='value')this.value=String(value);
    }
    getAttribute(name){return this.attributes[name]??null;}
    removeAttribute(name){delete this.attributes[name];if(name==='hidden')this.hidden=false;if(name==='inert')this.inert=false;}
    getBoundingClientRect(){return geometry.get(this.id)||(this.id.startsWith('investment-group-')&&geometry.get('investment-group-*'))||{top:this.top,bottom:this.top+100,height:100,width:250,left:0,right:250};}
  }
  for(const id of ['content','content-nav','context-panel','workspace','global-nav','sidebar','toolbar','company-header','announcement','workarea','entity-flyout','investment-event-popover']) new Element(id);
  const frames=[],resizeObservers=[];
  class FakeResizeObserver {
    constructor(callback){this.callback=callback;this.targets=new Set();resizeObservers.push(this);}
    observe(target){this.targets.add(target);}
    unobserve(target){this.targets.delete(target);}
    disconnect(){this.targets.clear();}
  }
  const historyCalls=[];
  const window={innerWidth:1200,innerHeight:850,location:{hash},history:{pushState(_a,_b,value){historyCalls.push(['push',value]);window.location.hash=value;},replaceState(_a,_b,value){historyCalls.push(['replace',value]);window.location.hash=value;}},
    localStorage:{getItem:key=>values.get(key),setItem:(key,value)=>values.set(key,value)},
    ResizeObserver:FakeResizeObserver,requestAnimationFrame:fn=>deferRaf?frames.push(fn):fn(),addEventListener:(name,fn)=>{windowListeners[name]=fn;}};
  const flushFrames=()=>{while(frames.length) frames.shift()();};
  const triggerResize=id=>{
    const target=nodes.get(id);let notifications=0;
    for(const observer of resizeObservers)if(observer.targets.has(target)){
      observer.callback([{target,contentRect:target.getBoundingClientRect()}],observer);notifications++;
    }
    return notifications;
  };
  const controller=createController({document,window,registry});
  controller.start();
  flushFrames();
  return {controller,document,window,nodes,listeners,windowListeners,flushFrames,triggerResize,historyCalls,geometry};
}

function chartHarness() {
  const h=harness('');
  h.geometry.set('content',{top:88,bottom:830,height:742,width:1140,left:60,right:1200});
  h.geometry.set('investment-event-popover',{top:100,bottom:360,height:260,width:340,left:100,right:440});
  h.geometry.set('investment-group-*',{top:430,bottom:462,height:32,width:62,left:500,right:562});
  h.nodes.get('investment-event-popover').hidden=true;
  return h;
}

test('only an empty sample URL selects the named launch fixture; invalid scope never substitutes content',()=>{
  const initial=harness('');
  assert.deepEqual(initial.controller.getState().route,INSTITUTION_DEMO_SCOPE);
  const invalid=harness('#/company/unknown?view=overview');
  assert.equal(invalid.controller.getState().route,null);
  assert.match(invalid.nodes.get('content').innerHTML,/页面范围无法确认/);
  assert.doesNotMatch(invalid.nodes.get('content').innerHTML,/Manager 的研究/);
});

test('report entry, citation close, version change and return preserve identity, main text, focus and stored scroll',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'reports'}));
  const content=h.nodes.get('content');
  content.scrollTop=420;
  const row=h.nodes.get('open-alpha-north-main-v2');row.focus();
  const reportRoute={companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'};
  h.controller.navigate(reportRoute);
  content.scrollTop=890;
  const cite='cite-business-demo-alpha-business';
  h.nodes.get(cite).focus();
  const originalText=content.innerHTML;
  h.controller.openPanel({kind:'evidence',origin:'report',evidenceId:'demo-alpha-business'},cite);
  assert.equal(content.innerHTML,originalText);
  assert.equal(content.scrollTop,890);
  h.controller.closePanel();
  assert.equal(h.document.activeElement.id,cite);
  assert.equal(content.scrollTop,890);
  h.controller.navigate({...reportRoute,version:'v1'});
  assert.match(content.innerHTML,/结论待复核/);
  assert.equal(h.controller.getState().route.version,'v1');
  h.controller.navigate({companyId:'alphabet',view:'reports'});
  assert.equal(content.scrollTop,420);
  assert.equal(h.document.activeElement.id,'open-alpha-north-main-v2');
});

test('section targets use the exact version and company switches clear evidence context',()=>{
  const h=harness();
  h.controller.navigate({companyId:'alphabet',view:'report',reportId:'alpha-field-main',version:'v1',sectionId:'thesis'});
  assert.equal(h.document.activeElement.id,'section-thesis');
  assert.match(h.nodes.get('content').innerHTML,/Field/);
  assert.match(h.nodes.get('content').innerHTML,/历史版本/);
  h.controller.openPanel({kind:'context'});
  h.controller.navigate({companyId:'microsoft',view:'overview'});
  assert.equal(h.controller.getState().panel,null);
  assert.equal(h.nodes.get('context-panel').hidden,true);
  assert.doesNotMatch(h.nodes.get('content').innerHTML,/Alphabet 公司研究/);
});

test('invalid cross-company evidence is rejected before visible panel state changes',()=>{
  const h=harness();
  const before=h.nodes.get('content').innerHTML;
  assert.throws(()=>h.controller.openPanel({kind:'evidence',origin:'material',evidenceId:'demo-ms-paid'}));
  assert.equal(h.controller.getState().panel,null);
  assert.equal(h.nodes.get('content').innerHTML,before);
});

test('browser hash navigation restores each stored company page rather than choosing a default',()=>{
  const h=harness();
  h.nodes.get('content').scrollTop=350;
  h.controller.navigate({companyId:'microsoft',view:'materials'});
  h.window.location.hash=formatRoute(DEMO_LAUNCH);
  h.windowListeners.hashchange();
  assert.equal(h.controller.getState().route.companyId,'alphabet');
  assert.equal(h.nodes.get('content').scrollTop,350);
  assert.equal(h.windowListeners.wheel,undefined);
  assert.equal(h.listeners.wheel,undefined);
});

function clickAction(h,id,action,fields={}) {
  const button=h.nodes.get(id);
  assert.ok(button,`Button ${id} exists`);
  button.dataset={...button.dataset,action,...fields};button.focus();
  h.listeners.click({button:0,target:{closest:selector=>selector.startsWith('button')?button:null},preventDefault(){}});
}

function clickRenderedAction(h,containerId,action,fields={}) {
  const match=tags(h.nodes.get(containerId).innerHTML).find(item=>item['data-action']===action&&Object.entries(fields).every(([key,value])=>item[`data-${key}`]===value));
  assert.ok(match,`Rendered ${action} action exists in ${containerId}`);
  const dataset=Object.fromEntries(Object.entries(match).filter(([key])=>key.startsWith('data-')).map(([key,value])=>[key.slice(5),value]));
  const button=match.id?h.nodes.get(match.id):{id:'',dataset};
  assert.ok(button);
  button.dataset=dataset;button.focus?.();
  h.listeners.click({button:0,target:{closest:selector=>selector.startsWith('button')?button:null},preventDefault(){}});
}

test('institution home opens the configured Agent portfolio and hides only the middle object sidebar',()=>{
  const data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  for(const hash of ['',formatRoute(INSTITUTION_DEMO_SCOPE)]) {
    const h=harness(hash),state=h.controller.getState();
    assert.deepEqual(state.route,INSTITUTION_DEMO_SCOPE);
    assert.equal(state.institutionPeriod,data.defaultPeriod);assert.equal(state.institutionHolding,null);
    assert.equal(state.institutionAgent,data.defaultAgentId);
    assert.equal(state.overviewSection,null);assert.equal(state.itemSelection,null);
    assert.equal(h.nodes.get('content').dataset.entity,'institution');
    assert.ok(h.nodes.has('institution-dashboard'));
    assert.equal(h.nodes.get('company-header').innerHTML,'');
    assert.match(h.nodes.get('toolbar').innerHTML,/<h1[^>]*>投资总览<\/h1>/);
    assert.match(h.nodes.get('toolbar').innerHTML,/模拟数据 · 非实盘/);
    const modes=tags(h.nodes.get('global-nav').innerHTML).filter(item=>item['data-action']==='mode');
    assert.deepEqual(modes.map(item=>item['data-mode']),['institution','company','manager']);
    assert.deepEqual(modes.filter(item=>item['aria-pressed']==='true').map(item=>item['data-mode']),['institution']);
    assert.equal(h.nodes.get('sidebar').hidden,true);
    assert.equal(h.nodes.get('global-nav').hidden,false);
    assert.ok(!h.nodes.has('entity-search'));
    assert.ok(!h.nodes.has('institution-agents'),'home does not have a separate Agent card section');
    assert.doesNotMatch(h.nodes.get('sidebar').innerHTML,/institution-section/);
    const agent=data.agents.find(item=>item.managerId===data.defaultAgentId);
    const weights=tags(h.nodes.get('content').innerHTML).filter(item=>item.class?.split(/\s+/).includes('holding-weight'));
    assert.deepEqual(weights.map(item=>item['data-holding']),[...agent.portfolio.holdings.map(item=>item.companyId),'cash']);
  }
});

test('institution period and allocation controls update presentation without route, sidebar or research mutations and reject invalid values atomically',()=>{
  const h=harness(''),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId),content=h.nodes.get('content');
  const sidebar=h.nodes.get('sidebar'),sideHTML=sidebar.innerHTML,history=[...h.historyCalls],research=JSON.stringify(catalog);
  content.scrollTop=280;
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  assert.equal(h.controller.getState().institutionPeriod,'1m');
  assert.equal(h.controller.getState().institutionAgent,data.defaultAgentId);
  assert.equal(h.document.activeElement.id,'institution-period-1m');assert.equal(content.scrollTop,280);
  const agent=data.agents.find(item=>item.managerId===data.defaultAgentId);
  assert.ok(content.innerHTML.includes(`${agent.returns['1m'].toFixed(2)}%`));
  clickAction(h,'allocation-alphabet','institution-holding',{holding:'alphabet'});
  assert.equal(h.controller.getState().institutionHolding,'alphabet');
  assert.equal(h.document.activeElement.id,'allocation-alphabet');assert.equal(content.scrollTop,280);
  clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
  assert.equal(h.controller.getState().institutionHolding,'cash');
  const before={state:{...h.controller.getState()},html:content.innerHTML};
  for(const [id,action,fields] of [
    ['institution-period-1m','institution-period',{period:'unknown'}],
    ['institution-period-1m','institution-period',{period:''}],
    ['allocation-cash','institution-holding',{holding:'unknown'}],
    ['allocation-cash','institution-holding',{holding:''}],
    ['allocation-cash','institution-holding',{holding:'arista'}],
    [`institution-agent-${data.defaultAgentId}`,'institution-agent',{agent:'unknown'}],
    [`institution-agent-${data.defaultAgentId}`,'institution-agent',{agent:''}],
  ]) {
    clickAction(h,id,action,fields);
    assert.deepEqual(h.controller.getState(),before.state);assert.equal(content.innerHTML,before.html);
  }
  assert.equal(sidebar.innerHTML,sideHTML);assert.equal(content.scrollTop,280);
  assert.deepEqual(h.historyCalls,history);assert.deepEqual(h.controller.getState().route,INSTITUTION_DEMO_SCOPE);
  assert.equal(JSON.stringify(catalog),research);
});

function assertHoldingSelection(h,selected) {
  assert.equal(h.controller.getState().institutionHolding,selected);
  const agent=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId).agents.find(item=>item.managerId===h.controller.getState().institutionAgent);
  for(const id of [...agent.portfolio.holdings.map(item=>item.companyId),'cash'])for(const prefix of ['allocation','allocation-slice']) {
    assert.equal(h.nodes.get(`${prefix}-${id}`).getAttribute('aria-pressed'),String(id===selected));
  }
}

test('allocation hover and focus preview a holding without rebuilding or committing it, then restore the clicked selection',()=>{
  const h=harness(''),content=h.nodes.get('content');
  clickAction(h,'allocation-alphabet','institution-holding',{holding:'alphabet'});
  assertHoldingSelection(h,'alphabet');
  const selected=h.nodes.get('allocation-slice-alphabet'),preview=h.nodes.get('allocation-slice-microsoft');
  const dashboard=h.nodes.get('institution-dashboard'),markup=content.innerHTML,history=[...h.historyCalls];
  content.scrollTop=180;
  const assertPreview=target=>{
    assert.equal(h.nodes.get('allocation-value').textContent,target.dataset.weight);
    assert.equal(h.nodes.get('allocation-name').textContent,target.dataset.name);
    assert.equal(h.nodes.get('allocation-caption').textContent,target.dataset.value);
    assert.equal(target.classList.contains('is-emphasized'),true);
    assert.equal(h.nodes.get('institution-dashboard'),dashboard);assert.equal(content.innerHTML,markup);
    assert.equal(content.scrollTop,180);assertHoldingSelection(h,'alphabet');
  };
  h.listeners.pointerover({pointerType:'mouse',target:preview,relatedTarget:content});assertPreview(preview);
  assert.equal(h.nodes.get('institution-holding-microsoft').classList.contains('is-preview'),true);
  assert.equal(h.nodes.get('institution-holding-alphabet').classList.contains('is-active'),true);
  h.listeners.pointerout({pointerType:'mouse',target:preview,relatedTarget:content});assertPreview(selected);
  assert.equal(h.nodes.get('institution-holding-microsoft').classList.contains('is-preview'),false);
  const weight=h.nodes.get('allocation-microsoft'),row=h.nodes.get('institution-holding-microsoft');
  h.listeners.pointerover({pointerType:'mouse',target:weight,relatedTarget:content});assertPreview(preview);
  h.listeners.pointerout({pointerType:'mouse',target:weight,relatedTarget:row});assertPreview(preview);
  h.listeners.pointerout({pointerType:'mouse',target:row,relatedTarget:content});assertPreview(selected);
  h.listeners.pointerover({pointerType:'touch',target:preview,relatedTarget:content});assertPreview(selected);
  h.listeners.keydown({key:'Tab',target:preview});preview.focus();h.listeners.focusin({target:preview});assertPreview(preview);
  content.focus();h.listeners.focusout({target:preview,relatedTarget:content});assertPreview(selected);
  assert.deepEqual(h.historyCalls,history);assert.deepEqual(h.controller.getState().route,INSTITUTION_DEMO_SCOPE);
});

test('allocation SVG sectors support pointer and Enter/Space selection, cash and cancellation without scroll or route jumps',()=>{
  const h=harness(''),content=h.nodes.get('content'),route={...h.controller.getState().route};
  content.scrollTop=240;
  const cash=h.nodes.get('allocation-slice-cash'),alphabet=h.nodes.get('allocation-slice-alphabet');
  const dashboard=h.nodes.get('institution-dashboard');
  h.listeners.click({button:0,target:alphabet,preventDefault(){}});assertHoldingSelection(h,'alphabet');
  assert.equal(h.nodes.get('institution-dashboard'),dashboard);
  h.listeners.click({button:0,target:alphabet,preventDefault(){}});assertHoldingSelection(h,null);
  cash.focus();let prevented=false;
  h.listeners.keydown({key:'Enter',target:cash,preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assertHoldingSelection(h,'cash');
  prevented=false;h.listeners.keydown({key:' ',target:cash,preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assertHoldingSelection(h,null);
  assert.equal(h.document.activeElement,cash);assert.equal(h.nodes.get('allocation-slice-cash'),cash);
  assert.equal(content.scrollTop,240);assert.deepEqual(h.controller.getState().route,route);
  assert.equal(h.nodes.get('institution-dashboard'),dashboard);
  clickAction(h,'allocation-alphabet','institution-holding',{holding:'alphabet'});assertHoldingSelection(h,'alphabet');
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});assertHoldingSelection(h,null);
  const before={...h.controller.getState()},markup=content.innerHTML;
  clickAction(h,'allocation-cash','institution-holding',{holding:'nvidia'});
  assert.deepEqual(h.controller.getState(),before);assert.equal(content.innerHTML,markup);
});

test('holding research opens the selected Agent authored report and returns to the same institution portfolio selection',()=>{
  for(const [managerId,companyId] of [['north','alphabet'],['north','microsoft'],['field','alphabet']]) {
    const h=harness(''),target=getManagerCompanyReport(managerId,companyId);
    assert.equal(target.status,'available');
    clickAction(h,`institution-agent-${managerId}`,'institution-agent',{agent:managerId});
    clickAction(h,'institution-period-1y','institution-period',{period:'1y'});
    clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
    h.nodes.get('content').scrollTop=310;
    const link=h.nodes.get(`institution-company-${companyId}`);link.focus();
    assert.deepEqual(parseRoute(link.getAttribute('href')),target.route);
    h.listeners.click({button:0,target:link,preventDefault(){}});
    assert.deepEqual(h.controller.getState().route,target.route);
    assert.equal(getReport(target.route.companyId,target.route.reportId,target.route.version).manager.id,managerId);
    const back=h.nodes.get('back-to-company');
    assert.deepEqual(parseRoute(back.getAttribute('href')),INSTITUTION_DEMO_SCOPE);
    h.listeners.click({button:0,target:back,preventDefault(){}});
    assert.deepEqual(h.controller.getState().route,INSTITUTION_DEMO_SCOPE);
    assert.equal(h.controller.getState().institutionAgent,managerId);
    assert.equal(h.controller.getState().institutionPeriod,'1y');assertHoldingSelection(h,'cash');
    assert.equal(h.nodes.get('content').scrollTop,310);assert.equal(h.document.activeElement.id,`institution-company-${companyId}`);
    assert.equal(h.nodes.get('sidebar').hidden,true);
  }
});

test('holdings without an authored report remain explicit gaps and cannot open another Manager report or a company fallback',()=>{
  for(const [managerId,companyId] of [['north','nvidia'],['field','microsoft']]) {
    const h=harness('');
    clickAction(h,`institution-agent-${managerId}`,'institution-agent',{agent:managerId});
    const label=h.nodes.get(`institution-company-${companyId}`),history=[...h.historyCalls],before={...h.controller.getState()};
    assert.ok(label);assert.equal(label.getAttribute('href'),null);
    assert.equal(getManagerCompanyReport(managerId,companyId).status,'missing');
    assert.match(h.nodes.get('content').innerHTML,/暂无该\s*Agent\s*报告/);
    h.listeners.click({button:0,target:label,preventDefault(){}});
    assert.deepEqual(h.controller.getState(),before);assert.deepEqual(h.historyCalls,history);
  }
});

test('institution legends, thumbnails and Agent steps switch one portfolio manually and keep the period while clearing holding selection',()=>{
  const h=harness(''),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId),content=h.nodes.get('content');
  const route={...h.controller.getState().route},hash=h.window.location.hash,history=[...h.historyCalls];
  const select=(agentId,id=`institution-agent-${agentId}`)=>{
    clickAction(h,id,'institution-agent',{agent:agentId});
    assert.equal(h.controller.getState().institutionAgent,agentId);
    const agent=data.agents.find(item=>item.managerId===agentId);
    assert.deepEqual(content.querySelectorAll('.holding-weight').map(item=>item.dataset.holding),[...agent.portfolio.holdings.map(item=>item.companyId),'cash']);
  };
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  clickAction(h,'allocation-alphabet','institution-holding',{holding:'alphabet'});
  select('field');
  assert.equal(h.controller.getState().institutionHolding,null);assert.equal(h.controller.getState().institutionPeriod,'1m');
  clickAction(h,'allocation-arista','institution-holding',{holding:'arista'});
  clickAction(h,'institution-period-1y','institution-period',{period:'1y'});
  assert.equal(h.controller.getState().institutionAgent,'field');assert.equal(h.controller.getState().institutionHolding,'arista');
  assert.equal(h.controller.getState().institutionPeriod,'1y','changing the comparison interval keeps the selected Agent and current holding snapshot');
  select('north','institution-agent-north');assert.equal(h.controller.getState().institutionHolding,null);
  clickAction(h,'institution-prev','institution-step',{step:'-1'});
  assert.equal(h.controller.getState().institutionAgent,data.agents.at(-1).managerId);
  for(const agent of data.agents) {
    clickAction(h,'institution-next','institution-step',{step:'1'});
    assert.equal(h.controller.getState().institutionAgent,agent.managerId);
  }
  clickAction(h,'institution-next','institution-step',{step:'1'});
  assert.equal(h.controller.getState().institutionAgent,data.agents[0].managerId);
  const before={...h.controller.getState()},html=content.innerHTML;
  clickAction(h,'institution-next','institution-step',{step:'2'});
  assert.deepEqual(h.controller.getState(),before);assert.equal(content.innerHTML,html);
  assert.deepEqual(h.controller.getState().route,route);assert.equal(h.window.location.hash,hash);assert.deepEqual(h.historyCalls,history);
});

test('institution Agent curves are clickable while hover and wheel leave portfolio selection unchanged',async()=>{
  const h=harness(''),content=h.nodes.get('content');
  const target=h.nodes.get('institution-curve-field');
  assert.ok(target,'the rendered Agent curve has a stable interaction target');
  const original=h.controller.getState().institutionAgent;
  h.listeners.pointerover({pointerType:'mouse',target,relatedTarget:content});
  await pause(170);assert.equal(h.controller.getState().institutionAgent,original);
  h.listeners.click({button:0,target,preventDefault(){}});
  assert.equal(h.controller.getState().institutionAgent,'field');
  assert.deepEqual(content.querySelectorAll('.holding-weight').map(item=>item.dataset.holding),[...getInstitution(INSTITUTION_DEMO_SCOPE.institutionId).agents.find(item=>item.managerId==='field').portfolio.holdings.map(item=>item.companyId),'cash']);
  assert.equal(h.listeners.wheel,undefined);assert.equal(h.windowListeners.wheel,undefined);
});

test('institution thumbnail keyboard navigation stays inside its Agent selector and preserves normal reading keys elsewhere',()=>{
  const h=harness(''),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  const press=(key,target=h.document.activeElement)=>{
    let prevented=false;
    h.listeners.keydown({key,target,preventDefault(){prevented=true;}});
    return prevented;
  };
  h.nodes.get(`institution-agent-${data.defaultAgentId}`).focus();
  for(const [key,expected] of [['End',data.agents.at(-1).managerId],['ArrowRight',data.agents[0].managerId],['ArrowLeft',data.agents.at(-1).managerId],['Home',data.agents[0].managerId]]) {
    assert.equal(press(key),true);assert.equal(h.controller.getState().institutionAgent,expected);
    assert.equal(h.document.activeElement.id,`institution-agent-${expected}`);
  }
  h.nodes.get('content').focus();
  assert.equal(press('ArrowDown'),false);assert.equal(press('Home'),false);
  assert.equal(h.controller.getState().institutionAgent,data.agents[0].managerId);
});

test('institution, company and Manager entries keep one shell and restore their own selections and reading positions',()=>{
  const h=harness(''),shell=['workspace','global-nav','sidebar','toolbar','company-header','content-nav','content','context-panel'].map(id=>h.nodes.get(id));
  clickAction(h,'institution-period-1y','institution-period',{period:'1y'});
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  clickAction(h,'allocation-arista','institution-holding',{holding:'arista'});
  h.nodes.get('content').scrollTop=340;
  clickAction(h,'mode-company','mode',{mode:'company'});
  assert.deepEqual(h.controller.getState().route,DEMO_LAUNCH);
  assert.equal(h.nodes.get('sidebar').hidden,false);
  h.controller.navigate({companyId:'microsoft',view:'materials'});h.nodes.get('content').scrollTop=160;
  clickAction(h,'mode-manager','mode',{mode:'manager'});
  h.controller.navigate({managerId:'field',view:'reports'});h.nodes.get('content').scrollTop=260;
  assert.equal(h.nodes.get('sidebar').hidden,false);
  clickAction(h,'mode-institution','mode',{mode:'institution'});
  assert.deepEqual(h.controller.getState().route,INSTITUTION_DEMO_SCOPE);
  assert.equal(h.controller.getState().institutionPeriod,'1y');assert.equal(h.controller.getState().institutionHolding,'arista');
  assert.equal(h.controller.getState().institutionAgent,'field');assert.equal(h.nodes.get('sidebar').hidden,true);
  assert.equal(h.nodes.get('content').scrollTop,340);
  clickAction(h,'mode-company','mode',{mode:'company'});
  assert.deepEqual(h.controller.getState().route,{companyId:'microsoft',view:'materials'});assert.equal(h.nodes.get('content').scrollTop,160);
  clickAction(h,'mode-manager','mode',{mode:'manager'});
  assert.deepEqual(h.controller.getState().route,{managerId:'field',view:'reports'});assert.equal(h.nodes.get('content').scrollTop,260);
  assert.deepEqual(['workspace','global-nav','sidebar','toolbar','company-header','content-nav','content','context-panel'].map(id=>h.nodes.get(id)),shell);
});

test('institution language, theme and context preserve selection, while invalid institution bookmarks never fall back to a company',()=>{
  const h=harness('');
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  clickAction(h,'allocation-cash','institution-holding',{holding:'cash'});
  clickAction(h,'language-button','language');
  assert.equal(h.controller.getState().institutionPeriod,'1m');assert.equal(h.controller.getState().institutionHolding,'cash');
  assert.equal(h.controller.getState().institutionAgent,'field');
  assert.match(h.nodes.get('toolbar').innerHTML,/Illustrative data|Not a live account/);
  assert.match(h.nodes.get('toolbar').innerHTML,/<h1[^>]*>Investment overview<\/h1>/);
  assert.match(h.nodes.get('toolbar').innerHTML,/Uteki Investment/);
  const main=h.nodes.get('content').innerHTML;
  clickAction(h,'theme-button','theme');assert.equal(h.document.documentElement.dataset.theme,'dark');
  assert.equal(h.nodes.get('content').innerHTML,main);
  clickAction(h,'context-button','context');
  assert.equal(h.controller.getState().panel.kind,'context');
  assert.match(h.nodes.get('context-panel').innerHTML,/uteki-institution-ui-2026-09-30/);
  h.controller.closePanel();assert.equal(h.document.activeElement.id,'context-button');
  assert.equal(h.nodes.get('content').innerHTML,main);
  for(const hash of ['#/institution/unknown?view=overview','#/institution/uteki?view=reports','#/institution/uteki?view=overview&company=alphabet']) {
    const invalid=harness(hash);
    assert.equal(invalid.controller.getState().route,null);
    assert.match(invalid.nodes.get('content').innerHTML,/页面范围无法确认/);
    assert.ok(!invalid.nodes.has('institution-dashboard'));assert.ok(!invalid.nodes.has('overview-deck'));
  }
});

const pause=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
function assertOverview(h,selected) {
  assert.equal(h.controller.getState().overviewSection,selected);
  for(const key of overviewKeys) {
    const tab=h.nodes.get(`overview-tab-${key}`),panel=h.nodes.get(`overview-panel-${key}`);
    assert.ok(tab&&panel,`${key} has its tab and panel`);
    assert.equal(tab.attributes['aria-selected'],String(key===selected));
    assert.equal(tab.tabIndex,key===selected?0:-1);
    assert.equal(tab.classList.contains('is-active'),key===selected);
    assert.equal(panel.hidden,key!==selected);
    if(panel.attributes['aria-hidden']!==undefined)assert.equal(panel.attributes['aria-hidden'],String(key!==selected));
    if(panel.inert!==undefined)assert.equal(panel.inert,key!==selected);
  }
}
function enterOverview(h,key,pointerType='mouse') {
  const target=h.nodes.get(`overview-tab-${key}`);
  h.listeners.pointerover({pointerType,target,relatedTarget:h.nodes.get('content')});
  return target;
}
function pressOverview(h,key,target=h.document.activeElement) {
  let prevented=false;
  h.listeners.keydown({key,target,preventDefault(){prevented=true;}});
  return prevented;
}

test('overview hover waits, cancels a quick pass and retains the chosen section when moving into its content',async()=>{
  const h=harness();assertOverview(h,'changes');
  const tab=enterOverview(h,'research');
  await pause(60);assertOverview(h,'changes');
  h.listeners.pointerout({pointerType:'mouse',target:tab,relatedTarget:h.nodes.get('content')});
  await pause(160);assertOverview(h,'changes');
  enterOverview(h,'research');await pause(165);assertOverview(h,'research');
  h.listeners.pointerout({pointerType:'mouse',target:tab,relatedTarget:h.nodes.get('overview-panel-research')});
  await pause(165);assertOverview(h,'research');
  assert.equal(h.document.activeElement.id,'content','hover keeps keyboard focus in place');
  enterOverview(h,'materials','touch');await pause(165);assertOverview(h,'research');
});

test('overview clicks and previous/next wrap manually without changing routes, history, page identity or research state',()=>{
  const h=harness(),content=h.nodes.get('content'),route={...h.controller.getState().route};
  const markup=content.innerHTML,hash=h.window.location.hash,history=[...h.historyCalls],research=JSON.stringify(catalog);
  const panels=overviewKeys.map(key=>h.nodes.get(`overview-panel-${key}`));content.scrollTop=120;
  clickAction(h,'overview-tab-tracking','overview-section',{section:'tracking'});assertOverview(h,'tracking');
  clickAction(h,'overview-next','overview-step',{step:'1'});assertOverview(h,'changes');
  clickAction(h,'overview-prev','overview-step',{step:'-1'});assertOverview(h,'tracking');
  clickAction(h,'overview-prev','overview-step',{step:'-1'});assertOverview(h,'materials');
  assert.equal(h.nodes.get('overview-position').textContent,'03 / 04');
  clickAction(h,'overview-next','overview-step',{step:'9'});assertOverview(h,'materials');
  clickAction(h,'overview-tab-changes','overview-section',{section:'unknown'});assertOverview(h,'materials');
  assert.equal(content.innerHTML,markup,'switching does not replace panel nodes or their links');
  assert.deepEqual(overviewKeys.map(key=>h.nodes.get(`overview-panel-${key}`)),panels);
  assert.equal(content.scrollTop,120);assert.deepEqual(h.controller.getState().route,route);
  assert.equal(h.window.location.hash,hash);assert.deepEqual(h.historyCalls,history);
  assert.equal(JSON.stringify(catalog),research,'presentation never marks events read or adopts evidence');
  assert.equal(h.listeners.wheel,undefined);assert.equal(h.windowListeners.wheel,undefined);
});

test('overview keyboard controls are scoped to its tabs and preserve each company selection through navigation and language changes',()=>{
  const storage=new Map(),h=harness(formatRoute(DEMO_LAUNCH),false,storage);
  h.nodes.get('overview-tab-changes').focus();
  for(const [key,expected] of [['ArrowDown','research'],['ArrowRight','materials'],['ArrowUp','research'],['ArrowLeft','changes'],['ArrowLeft','tracking'],['Home','changes'],['End','tracking']]) {
    assert.equal(pressOverview(h,key),true);assertOverview(h,expected);
    assert.equal(h.document.activeElement.id,`overview-tab-${expected}`);
  }
  h.nodes.get('overview-panel-tracking').focus();
  assert.equal(pressOverview(h,'ArrowDown'),false,'arrow keys within content retain native reading');assertOverview(h,'tracking');
  assert.equal(pressOverview(h,'Home'),false);assertOverview(h,'tracking');
  h.controller.navigate({companyId:'microsoft',view:'overview'});assertOverview(h,'changes');
  clickAction(h,'overview-tab-materials','overview-section',{section:'materials'});assertOverview(h,'materials');
  h.controller.navigate({managerId:'north',view:'overview'});assert.equal(h.controller.getState().overviewSection,null);
  h.controller.navigate({companyId:'alphabet',view:'reports'});assert.equal(h.controller.getState().overviewSection,null);
  h.controller.navigate({companyId:'alphabet',view:'overview'});assertOverview(h,'tracking');
  clickAction(h,'language-button','language');assertOverview(h,'tracking');
  assert.equal(h.controller.getState().language,'en');
  assert.match(h.nodes.get('content').innerHTML,/Open questions/);
  h.controller.navigate({companyId:'microsoft',view:'overview'});assertOverview(h,'materials');
  assert.deepEqual(JSON.parse(storage.get('uteki.company-design-swiss-c.display')),{language:'en',theme:'light',typography:'swiss'});
  const fresh=harness(formatRoute(DEMO_LAUNCH),false,storage);assertOverview(fresh,'changes');
});

test('overview hover cannot hide keyboard-focused content; explicit selection can move focus safely',async()=>{
  const h=harness();
  const action=h.nodes.get('overview-changes-all');
  assert.equal(h.nodes.get('overview-panel-changes').contains(action),true);
  pressOverview(h,'Tab',action);action.focus();enterOverview(h,'research');await pause(165);
  assertOverview(h,'changes');assert.equal(h.document.activeElement,action);
  const tab=h.nodes.get('overview-tab-research');
  h.listeners.click({button:0,target:tab,preventDefault(){}});
  assertOverview(h,'research');assert.equal(h.document.activeElement,tab);
  assert.equal(h.nodes.get('overview-panel-changes').inert,true);
});

test('pending overview hovers cannot fire after navigation, language rerender, page departure or Escape',async()=>{
  const transitions=[
    h=>h.controller.navigate({companyId:'microsoft',view:'overview'}),
    h=>clickAction(h,'language-button','language'),
    h=>h.windowListeners.pagehide(),
    h=>pressOverview(h,'Escape',h.nodes.get('content')),
  ];
  await Promise.all(transitions.map(async transition=>{
    const h=harness();enterOverview(h,'research');transition(h);await pause(165);assertOverview(h,'changes');
  }));
});

test('evidence context blocks stray overview hover and closing it restores its original visible module and invoker',async()=>{
  const h=harness();
  clickAction(h,'overview-tab-materials','overview-section',{section:'materials'});
  const evidenceId=tags(h.nodes.get('content').innerHTML).find(item=>item['data-action']==='evidence')['data-evidence'];
  const evidence=catalog.evidence.find(item=>item.id===evidenceId);
  pressOverview(h,'Tab',h.nodes.get('overview-panel-materials'));
  clickRenderedAction(h,'content','evidence',{evidence:evidence.id});
  const invoker=h.nodes.get(`material-${evidence.id}`),context={...h.controller.getState().panel};
  enterOverview(h,'tracking');await pause(165);assertOverview(h,'materials');
  assert.equal(h.document.activeElement.id,'panel-title');
  clickAction(h,'overview-tab-tracking','overview-section',{section:'tracking'});assertOverview(h,'tracking');
  assert.deepEqual(h.controller.getState().panel,context,'changing a summary cannot change evidence scope');
  h.controller.closePanel();assertOverview(h,'materials');assert.equal(h.document.activeElement,invoker);
  assert.equal(invoker.closest('[data-overview-section]').hidden,false);
  h.listeners.pointerdown({pointerType:'mouse',target:invoker});
  enterOverview(h,'tracking');await pause(165);assertOverview(h,'tracking');
  assert.equal(h.document.activeElement.id,'overview-tab-tracking','returning to mouse use allows a safe hover transition');
});

function selectWorkspaceItem(h,kind,id) {
  clickAction(h,`${kind==='material'?'material':'tracking'}-${id}`,'item-select',{kind,id});
}

test('company list selection updates only its detail and retains directory position without route or research mutations',()=>{
  for(const [view,kind,items] of [
    ['materials','material',catalog.evidence.filter(item=>item.companyId==='alphabet')],
    ['tracking','tracking',catalog.events.filter(item=>item.companyId==='alphabet'&&item.unresolved)],
  ]) {
    const route={companyId:'alphabet',view},h=harness(formatRoute(route));
    const content=h.nodes.get('content'),directory=h.nodes.get('item-directory'),detail=h.nodes.get('workspace-detail');
    const rows=items.map(item=>h.nodes.get(`${kind==='material'?'material':'tracking'}-${item.id}`));
    const markup=content.innerHTML,history=[...h.historyCalls],research=JSON.stringify(catalog);
    assert.equal(h.controller.getState().itemSelection,null);
    directory.scrollTop=95;content.scrollTop=250;
    for(const item of items.slice(0,2)) {
      selectWorkspaceItem(h,kind,item.id);
      assert.deepEqual(h.controller.getState().itemSelection,{kind,id:item.id});
      assert.equal(h.nodes.get('workspace-detail'),detail);assert.equal(h.nodes.get('item-directory'),directory);
      assert.equal(directory.scrollTop,95);assert.equal(content.scrollTop,0);
      assert.equal(h.document.activeElement.id,'detail-title');
      assert.ok(detail.innerHTML.includes(escapeHTML(kind==='material'?item.sourceTitle:item.title)));
      for(const row of rows)assert.equal(row.getAttribute('aria-current'),String(row.dataset.id===item.id));
    }
    const selected=items[Math.min(1,items.length-1)],title=h.nodes.get('detail-title');
    content.scrollTop=310;selectWorkspaceItem(h,kind,selected.id);
    assert.equal(content.scrollTop,310,'selecting the already open item keeps the reading position');
    assert.equal(h.nodes.get('detail-title'),title,'selecting the same item does not replace the detail');
    assert.equal(content.innerHTML,markup,'the controller changes detail HTML, not the entire company workspace');
    assert.deepEqual(h.controller.getState().route,route);assert.deepEqual(h.historyCalls,history);
    assert.equal(JSON.stringify(catalog),research);
  }
});

test('invalid company detail selection leaves the last valid detail and evidence context intact',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'materials'}));
  const item=catalog.evidence.find(item=>item.companyId==='alphabet'),foreign=catalog.evidence.find(item=>item.companyId==='microsoft');
  selectWorkspaceItem(h,'material',item.id);
  h.controller.openPanel({kind:'evidence',origin:'material',evidenceId:item.id},`material-${item.id}`);
  const before={state:{...h.controller.getState()},detail:h.nodes.get('workspace-detail').innerHTML,panel:h.nodes.get('context-panel').innerHTML};
  for(const selection of [{kind:'material',id:foreign.id},{kind:'material',id:'unknown'},{kind:'material',id:''},{kind:'tracking',id:catalog.events[0].id}]) {
    clickAction(h,`material-${item.id}`,'item-select',selection);
    assert.deepEqual(h.controller.getState(),before.state);
    assert.equal(h.nodes.get('workspace-detail').innerHTML,before.detail);
    assert.equal(h.nodes.get('context-panel').innerHTML,before.panel);
    assert.equal(h.nodes.get('context-panel').hidden,false);
    assert.ok(h.nodes.get('announcement').textContent,'the invalid selection reports an explicit error');
  }
});

test('company detail selections remain separate by company and category through language changes and returning from reports',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'materials'}));
  const alpha=catalog.evidence.find(item=>item.companyId==='alphabet'),ms=catalog.evidence.find(item=>item.companyId==='microsoft');
  const event=catalog.events.find(item=>item.companyId==='alphabet'&&item.unresolved);
  selectWorkspaceItem(h,'material',alpha.id);h.nodes.get('item-directory').scrollTop=45;
  h.controller.navigate({companyId:'alphabet',view:'tracking'});
  assert.equal(h.controller.getState().itemSelection,null);selectWorkspaceItem(h,'tracking',event.id);
  h.nodes.get('item-directory').scrollTop=75;
  h.controller.navigate({companyId:'microsoft',view:'materials'});
  assert.equal(h.controller.getState().itemSelection,null);selectWorkspaceItem(h,'material',ms.id);
  h.controller.navigate({companyId:'alphabet',view:'materials'});
  assert.deepEqual(h.controller.getState().itemSelection,{kind:'material',id:alpha.id});
  assert.equal(h.nodes.get('item-directory').scrollTop,45);
  clickAction(h,'language-button','language');
  assert.deepEqual(h.controller.getState().itemSelection,{kind:'material',id:alpha.id});
  assert.equal(h.nodes.get('item-directory').scrollTop,45);
  const link=event.affectedReports[0];
  h.controller.navigate({companyId:'alphabet',view:'report',...link});
  assert.equal(h.controller.getState().itemSelection,null);
  h.controller.navigate({managerId:'north',view:'overview'});assert.equal(h.controller.getState().itemSelection,null);
  h.controller.navigate({companyId:'alphabet',view:'tracking'});
  assert.deepEqual(h.controller.getState().itemSelection,{kind:'tracking',id:event.id});
  assert.equal(h.nodes.get('item-directory').scrollTop,75);
  h.controller.navigate({companyId:'microsoft',view:'materials'});
  assert.deepEqual(h.controller.getState().itemSelection,{kind:'material',id:ms.id});
});

test('question evidence opens beside the selected detail and closing returns to its precise source button',()=>{
  const event=catalog.events.find(item=>item.companyId==='alphabet'&&item.unresolved&&item.evidenceIds.length);
  const h=harness(formatRoute({companyId:'alphabet',view:'tracking'}));
  selectWorkspaceItem(h,'tracking',event.id);
  const detail=h.nodes.get('workspace-detail'),directory=h.nodes.get('item-directory'),html=detail.innerHTML;
  const source=tags(html).find(item=>item['data-action']==='evidence'&&item['data-evidence']===event.evidenceIds[0]);
  assert.ok(source.id,'each detail source has a stable return-focus target');
  h.nodes.get('content').scrollTop=180;directory.scrollTop=45;
  clickRenderedAction(h,'workspace-detail','evidence',{evidence:event.evidenceIds[0]});
  assert.equal(h.controller.getState().panel.evidenceId,event.evidenceIds[0]);
  assert.equal(h.controller.getState().panel.origin,'material');
  assert.equal(h.nodes.get('workspace-detail'),detail);assert.equal(detail.innerHTML,html);
  h.controller.closePanel();
  assert.equal(h.document.activeElement.id,source.id);
  assert.deepEqual(h.controller.getState().itemSelection,{kind:'tracking',id:event.id});
  assert.equal(h.nodes.get('content').scrollTop,180);assert.equal(directory.scrollTop,45);
});

test('company report directory keeps its own scroll across reader versions and returns while the full reader keeps its own position',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'reports'}));
  h.nodes.get('item-directory').scrollTop=65;h.nodes.get('content').scrollTop=220;
  const route={companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'};
  h.controller.navigate(route);
  assert.equal(h.nodes.get('item-directory').scrollTop,65);
  h.nodes.get('item-directory').scrollTop=95;h.nodes.get('content').scrollTop=630;
  h.listeners.change({target:{id:'report-version',value:'v1'}});
  assert.equal(h.nodes.get('item-directory').scrollTop,95);
  assert.match(h.nodes.get('content').innerHTML,/结论待复核/);
  assert.equal(h.controller.getState().route.version,'v1');
  h.controller.navigate(route);
  assert.equal(h.nodes.get('item-directory').scrollTop,95);assert.equal(h.nodes.get('content').scrollTop,630);
  h.controller.navigate({companyId:'alphabet',view:'reports'});
  assert.equal(h.nodes.get('item-directory').scrollTop,95);assert.equal(h.nodes.get('content').scrollTop,220);
  assert.equal(h.nodes.has('report-title'),false,'returning to directory does not auto-open the last report');
});

test('the full changes list reaches every company event and panel backtracking retains scope and the untouched overview',()=>{
  const render=createRenderer('zh',registry);
  for(const company of catalog.companies) {
    const html=render.panel({companyId:company.id,view:'overview'},{kind:'changes'});
    const buttons=tags(html).filter(item=>item['data-action']==='event');
    const expected=catalog.events.filter(event=>event.companyId===company.id).map(event=>event.id).sort();
    assert.deepEqual(buttons.map(item=>item['data-event']).sort(),expected);
    assert.equal(new Set(buttons.map(item=>item.id)).size,buttons.length);
  }

  const route={companyId:'alphabet',view:'overview'};
  const h=harness(formatRoute(route));
  const content=h.nodes.get('content'),navigation=h.nodes.get('content-nav');
  const originalContent=content.innerHTML,originalNavigation=navigation.innerHTML;
  content.scrollTop=315;
  assert.equal(content.dataset.entity,'company');assert.equal(content.dataset.view,'overview');
  clickAction(h,'overview-changes-all','changes');
  assert.equal(h.controller.getState().panel.kind,'changes');
  const event=catalog.events.find(item=>item.companyId===route.companyId&&item.evidenceIds.length);
  clickRenderedAction(h,'context-panel','event',{event:event.id});
  assert.equal(h.controller.getState().panel.eventId,event.id);
  assert.equal(h.controller.getState().panel.parent.kind,'changes');
  clickRenderedAction(h,'context-panel','evidence',{evidence:event.evidenceIds[0]});
  assert.equal(h.controller.getState().panel.evidenceId,event.evidenceIds[0]);
  assert.equal(h.controller.getState().panel.parent.eventId,event.id);
  assert.equal(h.controller.getState().panel.parent.parent.kind,'changes');
  clickRenderedAction(h,'context-panel','panel-back');
  assert.equal(h.controller.getState().panel.kind,'event');
  assert.equal(h.controller.getState().panel.eventId,event.id);
  clickAction(h,'back-to-changes','panel-back');
  assert.equal(h.controller.getState().panel.kind,'changes');
  const restored=tags(h.nodes.get('context-panel').innerHTML).filter(item=>item['data-action']==='event').map(item=>item['data-event']).sort();
  assert.deepEqual(restored,catalog.events.filter(item=>item.companyId===route.companyId).map(item=>item.id).sort());
  assert.equal(content.innerHTML,originalContent);assert.equal(content.scrollTop,315);
  assert.equal(navigation.innerHTML,originalNavigation);
  assert.deepEqual(h.controller.getState().route,route);
  h.controller.closePanel();
  assert.equal(h.document.activeElement.id,'overview-changes-all');
  assert.equal(content.innerHTML,originalContent);assert.equal(content.scrollTop,315);
});

test('company and Manager modes share the shell and restore the last entity page with its reading position',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'materials'}));
  const shell=['workspace','global-nav','sidebar','toolbar','company-header','content-nav','content','context-panel'].map(id=>h.nodes.get(id));
  h.nodes.get('content').scrollTop=410;
  clickAction(h,'mode-manager','mode',{mode:'manager'});
  assert.deepEqual(h.controller.getState().route,{managerId:'north',view:'overview'});
  assert.equal(h.nodes.get('content').dataset.entity,'manager');
  assert.equal(h.nodes.get('content').dataset.view,'overview');
  h.controller.navigate({managerId:'field',view:'reports'});
  h.nodes.get('content').scrollTop=265;
  clickAction(h,'mode-company','mode',{mode:'company'});
  assert.deepEqual(h.controller.getState().route,{companyId:'alphabet',view:'materials'});
  assert.equal(h.nodes.get('content').dataset.entity,'company');
  assert.equal(h.nodes.get('content').dataset.view,'materials');
  assert.equal(h.nodes.get('content').scrollTop,410);
  clickAction(h,'mode-manager','mode',{mode:'manager'});
  assert.deepEqual(h.controller.getState().route,{managerId:'field',view:'reports'});
  assert.equal(h.nodes.get('content').scrollTop,265);
  assert.deepEqual(['workspace','global-nav','sidebar','toolbar','company-header','content-nav','content','context-panel'].map(id=>h.nodes.get(id)),shell);
  assert.doesNotMatch(h.nodes.get('sidebar').innerHTML,/page-blueprint\/#managers/);
});

test('entity flyouts leave the sidebar rows, selected report and reader scroll unchanged',()=>{
  const h=harness(formatRoute({managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'}));
  const original=h.nodes.get('content').innerHTML;
  h.nodes.get('content').scrollTop=600;
  const sidebarHTML=h.nodes.get('sidebar').innerHTML;
  clickAction(h,'menu-manager-north','entity-menu',{key:'manager-north'});
  assert.equal(h.nodes.get('content').innerHTML,original);
  assert.equal(h.nodes.get('content').scrollTop,600);
  assert.equal(h.controller.getState().route.reportId,'alpha-north-main');
  assert.equal(h.nodes.get('sidebar').innerHTML,sidebarHTML);
  assert.equal(h.controller.getState().flyoutKey,'manager-north');
  assert.match(h.nodes.get('entity-flyout').innerHTML,/操作历史/);
  h.listeners.keydown({key:'Escape',preventDefault(){}});
  assert.equal(h.nodes.get('entity-flyout').hidden,true);
  assert.equal(h.document.activeElement.id,'menu-manager-north');
});

test('all Manager views and their sidebar links retain author scope in both languages',()=>{
  for(const language of ['zh','en']) for(const manager of catalog.managers) {
    const render=createRenderer(language,registry);
    for(const view of ['overview','companies','reports','holdings','activity']) {
      const route={managerId:manager.id,view};
      const content=render.main(route);
      render.header(route);render.toolbar(route,'light',null);render.panel(route,{kind:'context'});render.panel(route,{kind:'design'});
      for(const [_,value] of content.matchAll(/href="(#[^"]+)"/g)) {
        const destination=parseRoute(decode(value));
        if(destination.view==='report') {
          assert.equal(destination.managerId,manager.id);
          assert.equal(getReport(destination.companyId,destination.reportId,destination.version).manager.id,manager.id);
        } else if(destination.managerId) assert.equal(destination.managerId,manager.id);
      }
      const sidebar=render.sidebar(route);
      assert.match(sidebar,/entity-menu-button/);
      assert.match(render.entityMenu(`manager-${manager.id}`,route),new RegExp(`leaf-manager-${manager.id}-${view==='holdings'?'activity':view}" class="entity-child active"`));
      assert.doesNotMatch(sidebar,/page-blueprint\/#managers/);
    }
  }
});

test('Manager report, historical version, evidence and return retain the Manager entry and directory position',()=>{
  const h=harness(formatRoute({managerId:'north',view:'reports'}));
  const content=h.nodes.get('content');content.scrollTop=390;
  h.nodes.get('manager-report-alpha-north-main-v2').focus();
  h.controller.navigate({managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'});
  assert.match(h.nodes.get('toolbar').innerHTML,/<h1>North<\/h1>/);
  h.listeners.change({target:{id:'report-version',value:'v1'}});
  assert.equal(h.controller.getState().route.managerId,'north');
  assert.equal(h.controller.getState().route.version,'v1');
  assert.match(content.innerHTML,/结论待复核/);
  const evidenceId=catalog.reports.find(d=>d.id==='alpha-north-main').versions.find(v=>v.version==='v1').sections[0].citations[0];
  h.controller.openPanel({kind:'evidence',origin:'report',evidenceId});
  assert.match(h.nodes.get('context-panel').innerHTML,/alpha-north-main · v1/);
  h.controller.closePanel();
  const back=parseRoute(decode(content.innerHTML.match(/href="(#[^"]+)"/)[1]));
  assert.deepEqual(back,{managerId:'north',view:'reports'});
  h.controller.navigate(back);
  assert.equal(content.scrollTop,390);
  assert.equal(h.document.activeElement.id,'manager-report-alpha-north-main-v2');
});

test('Manager overview combines the explicit simulated portfolio with research while old holdings links show read-only activity',()=>{
  const institution=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId);
  for(const language of ['zh','en'])for(const manager of catalog.managers) {
    const render=createRenderer(language,registry),agent=institution.agents.find(item=>item.managerId===manager.id);
    const overview=render.main({managerId:manager.id,view:'overview'});
    assert.match(overview,language==='en'?/Illustrative data · Not a live account/:/模拟数据 · 非实盘/);
    assert.ok(overview.includes(`${agent.returns[institution.defaultPeriod].toFixed(2)}%`));
    const weights=tags(overview).filter(item=>item.class==='manager-weight-item');
    assert.deepEqual(weights.map(item=>item['data-company']),[...agent.portfolio.holdings.map(item=>item.companyId),'cash']);
    for(const item of agent.portfolio.holdings) assert.ok(overview.includes(`${item.weightPct.toFixed(1)}%`));
    assert.ok(overview.includes(`${agent.portfolio.cashWeightPct.toFixed(1)}%`));
    assert.equal(getManager(manager.id).portfolio.status,'unavailable','simulation does not establish live-account coverage');
    const missing=createManagerViews({t:(zh,en)=>language==='en'?en:zh,companyIcon:()=>''});
    assert.match(missing.main({managerId:manager.id,view:'overview'}),language==='en'?/not connected/:/未接入/);
    assert.match(missing.main({managerId:manager.id,view:'activity'}),language==='en'?/not connected/:/未接入/);
    const activity=render.main({managerId:manager.id,view:'activity'});
    assert.equal(activity,render.main({managerId:manager.id,view:'holdings'}));
    assert.match(activity,language==='en'?/Activity history/:/操作历史/);
    assert.match(activity,/data-execution-id=/);
    assert.doesNotMatch(activity,/data-action="(?:trade|buy|sell)"/);
    assert.match(activity,language==='en'?/Illustrative events · Not live trading/:/模拟事件 · 非实盘/);
  }
});

test('Manager research filters and pagination retain each author selection without rebuilding the shared shell',()=>{
  const h=harness(formatRoute({managerId:'north',view:'overview'}));
  const content=h.nodes.get('content'),sidebar=h.nodes.get('sidebar'),nav=h.nodes.get('content-nav');
  const sidebarHTML=sidebar.innerHTML,navHTML=nav.innerHTML,history=[...h.historyCalls];
  const rowIds=()=>tags(content.innerHTML).filter(item=>item['data-research-id']).map(item=>item['data-research-id']);
  assert.deepEqual(rowIds(),getManagerResearchRows('north').slice(0,6).map(row=>row.id));
  clickAction(h,'manager-research-next','manager-page',{list:'research',page:'1'});
  assert.deepEqual(rowIds(),getManagerResearchRows('north').slice(6,12).map(row=>row.id));
  assert.equal(h.document.activeElement.id,'manager-research-prev','last-page focus moves to the enabled paging control');
  assert.equal(h.document.activeElement.getAttribute('disabled'),null);
  clickAction(h,'manager-research-open','manager-filter',{list:'research',filter:'open'});
  assert.equal(h.controller.getState().managerSelection.researchPage,0);
  assert.deepEqual(rowIds(),getManagerResearchRows('north','open').slice(0,6).map(row=>row.id));
  assert.equal(sidebar.innerHTML,sidebarHTML);assert.equal(nav.innerHTML,navHTML);
  assert.deepEqual(h.historyCalls,history);
  h.controller.navigate({managerId:'field',view:'overview'});
  assert.equal(h.controller.getState().managerSelection.researchFilter,'all');
  assert.equal(h.controller.getState().managerSelection.researchPage,0);
  clickAction(h,'manager-research-published','manager-filter',{list:'research',filter:'published'});
  h.controller.navigate({managerId:'north',view:'overview'});
  assert.equal(h.controller.getState().managerSelection.researchFilter,'open');
  assert.equal(h.controller.getState().managerSelection.researchPage,0);
  clickAction(h,'language-button','language');
  assert.deepEqual(rowIds(),getManagerResearchRows('north','open').slice(0,6).map(row=>row.id));
  assert.match(content.innerHTML,/Research progress/);
  assert.equal(h.listeners.wheel,undefined);
});

test('Manager company coverage opens scoped outputs and report return restores the company filter, focus and scroll',()=>{
  const h=harness(formatRoute({managerId:'north',view:'companies'})),content=h.nodes.get('content');
  const focus=getManagerCoverage('north',managerCoverageFixture);
  assert.match(h.nodes.get('content-nav').innerHTML,new RegExp(`${focus.counts.current} 家当前关注`));
  const coverageTab=tags(h.nodes.get('content-nav').innerHTML).find(item=>item.id==='content-manager-north-companies');
  assert.equal(parseRoute(coverageTab.href).view,'companies');
  assert.match(h.nodes.get('content-nav').innerHTML,new RegExp(`研究覆盖</span><small>${focus.total}</small>`));
  assert.equal(tags(content.innerHTML).filter(item=>item['data-company']&&item.class==='manager-coverage-card').length,focus.total);
  assert.doesNotMatch(content.innerHTML,/data-company="(?:nvidia|costco|eaton)"/);
  clickAction(h,'manager-coverage-alphabet','manager-company-reports',{company:'alphabet'});
  assert.deepEqual(h.controller.getState().route,{managerId:'north',view:'reports'});
  assert.equal(h.controller.getState().managerSelection.reportCompany,'alphabet');
  const links=tags(content.innerHTML).filter(item=>item.href&&item.id?.startsWith('manager-report-'));
  assert.equal(links.length,2);
  for(const link of links) {assert.equal(parseRoute(link.href).companyId,'alphabet');assert.equal(parseRoute(link.href).managerId,'north');}
  const id='manager-report-alpha-north-cloud-v2',target=h.nodes.get(id);
  content.scrollTop=120;target.focus();
  h.listeners.click({button:0,target,preventDefault(){}});
  assert.equal(h.controller.getState().route.reportId,'alpha-north-cloud');
  h.listeners.click({button:0,target:h.nodes.get('back-to-company'),preventDefault(){}});
  assert.equal(h.controller.getState().managerSelection.reportCompany,'alphabet');
  assert.equal(content.scrollTop,120);assert.equal(h.document.activeElement.id,id);
  h.controller.navigate({managerId:'field',view:'reports'});
  assert.equal(h.controller.getState().managerSelection.reportCompany,'all');
});

test('Manager activity filters and pages match full dated records while invalid input leaves visible selection intact',()=>{
  const h=harness(formatRoute({managerId:'north',view:'holdings'})),content=h.nodes.get('content');
  const eventIds=()=>tags(content.innerHTML).filter(item=>item['data-execution-id']).map(item=>item['data-execution-id']);
  clickAction(h,'manager-activity-buy','manager-filter',{list:'activity',filter:'buy'});
  const expected=getManagerExecutionHistory({managerId:'north',kind:'buy'}).events;
  assert.deepEqual(eventIds(),expected.slice(0,8).map(item=>item.id));
  clickAction(h,'manager-activity-next','manager-page',{list:'activity',page:'1'});
  assert.deepEqual(eventIds(),expected.slice(8,16).map(item=>item.id));
  clickAction(h,'manager-activity-report','manager-filter',{list:'activity',filter:'report'});
  assert.equal(h.controller.getState().managerSelection.activityPage,0);
  assert.deepEqual(eventIds(),getManagerExecutionHistory({managerId:'north',kind:'report'}).events.map(item=>item.id));
  const before=content.innerHTML,state=h.controller.getState().managerSelection;
  for(const fields of [{list:'activity',filter:'unknown'},{list:'reports',filter:'alphabet'},{list:'activity',filter:''}]) {
    clickAction(h,'manager-activity-all','manager-filter',fields);
    assert.equal(content.innerHTML,before);assert.deepEqual(h.controller.getState().managerSelection,state);
  }
  for(const page of ['999','-1','0.5','']) {
    clickAction(h,'manager-activity-next','manager-page',{list:'activity',page});
    assert.equal(content.innerHTML,before);assert.deepEqual(h.controller.getState().managerSelection,state);
  }
  h.controller.navigate({managerId:'north',view:'companies'});
  const coverage=content.innerHTML;
  clickAction(h,'manager-coverage-alphabet','manager-company-reports',{company:'uncovered-company'});
  assert.equal(content.innerHTML,coverage);assert.equal(h.controller.getState().route.view,'companies');
});

test('opening company-scoped Manager reports clears an earlier report-list scroll before deferred restoration',()=>{
  const h=harness(formatRoute({managerId:'north',view:'reports'}),true),content=h.nodes.get('content');
  content.scrollTop=420;h.nodes.get('manager-report-alpha-north-main-v2').focus();
  h.controller.navigate({managerId:'north',view:'companies'});h.flushFrames();
  clickAction(h,'manager-coverage-microsoft','manager-company-reports',{company:'microsoft'});
  h.flushFrames();
  assert.equal(content.scrollTop,0);
  assert.equal(h.controller.getState().managerSelection.reportCompany,'microsoft');
  assert.equal(h.document.activeElement,content);
  const outputs=tags(content.innerHTML).filter(item=>item.href&&item.id?.startsWith('manager-report-'));
  assert.equal(outputs.length,1);assert.equal(parseRoute(outputs[0].href).companyId,'microsoft');
});

test('coverage stage tabs show only registered matches and retain each Manager selection independently',()=>{
  const h=harness(formatRoute({managerId:'north',view:'companies'})),content=h.nodes.get('content');
  const coverage=getManagerCoverage('north',managerCoverageFixture);
  const companies=()=>tags(content.innerHTML).filter(item=>item.class==='manager-coverage-card').map(item=>item['data-company']);
  const originalSidebar=h.nodes.get('sidebar').innerHTML,history=[...h.historyCalls];
  for(const stage of ['current','history','planned','all']) {
    clickAction(h,`manager-coverage-${stage}`,'manager-filter',{list:'coverage',filter:stage});
    const expected=stage==='all'?coverage.records:coverage.records.filter(item=>item.stage===stage);
    assert.deepEqual(companies(),expected.slice(0,6).map(item=>item.companyId));
    assert.equal(h.controller.getState().managerSelection.coverageStage,stage);
    assert.equal(h.document.activeElement.id,`manager-coverage-${stage}`);
    assert.equal(h.nodes.get(`manager-coverage-${stage}`).getAttribute('aria-pressed'),'true');
  }
  clickAction(h,'manager-coverage-history','manager-filter',{list:'coverage',filter:'history'});
  const state=h.controller.getState().managerSelection,html=content.innerHTML;
  clickAction(h,'manager-coverage-all','manager-filter',{list:'coverage',filter:'unknown'});
  assert.equal(content.innerHTML,html);assert.deepEqual(h.controller.getState().managerSelection,state);
  assert.equal(h.nodes.get('sidebar').innerHTML,originalSidebar);assert.deepEqual(h.historyCalls,history);
  h.controller.navigate({managerId:'field',view:'companies'});
  assert.equal(h.controller.getState().managerSelection.coverageStage,'all');
  clickAction(h,'manager-coverage-planned','manager-filter',{list:'coverage',filter:'planned'});
  h.controller.navigate({managerId:'north',view:'companies'});
  assert.equal(h.controller.getState().managerSelection.coverageStage,'history');
});

test('Manager report company, type and title filters combine and restore exact report return focus and scroll',()=>{
  const h=harness(formatRoute({managerId:'north',view:'reports'})),content=h.nodes.get('content');
  const sidebar=h.nodes.get('sidebar').innerHTML,nav=h.nodes.get('content-nav').innerHTML,history=[...h.historyCalls];
  const rows=()=>tags(content.innerHTML).filter(item=>item['data-report-id']).map(item=>item['data-report-id']);
  clickAction(h,'manager-reports-alphabet','manager-filter',{list:'reports',filter:'alphabet'});
  clickAction(h,'manager-report-kind-topic','manager-filter',{list:'report-kind',filter:'topic'});
  const input=h.nodes.get('manager-report-query');input.focus();input.value='云业务';input.setSelectionRange(2,2);
  h.listeners.input({target:input,isComposing:false});
  assert.deepEqual(rows(),['alpha-north-cloud']);
  assert.equal(h.document.activeElement.id,'manager-report-query');
  assert.equal(h.document.activeElement.selectionStart,2);assert.equal(h.document.activeElement.selectionEnd,2);
  const selection=h.controller.getState().managerSelection;
  assert.equal(selection.reportCompany,'alphabet');assert.equal(selection.reportKind,'topic');assert.equal(selection.reportQuery,'云业务');
  assert.equal(h.nodes.get('sidebar').innerHTML,sidebar);assert.equal(h.nodes.get('content-nav').innerHTML,nav);assert.deepEqual(h.historyCalls,history);
  const reportId='manager-report-alpha-north-cloud-v2',report=h.nodes.get(reportId);content.scrollTop=145;report.focus();
  h.listeners.click({button:0,target:report,preventDefault(){}});
  assert.deepEqual(h.controller.getState().route,{managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-cloud',version:'v2'});
  h.listeners.click({button:0,target:h.nodes.get('back-to-company'),preventDefault(){}});
  assert.deepEqual(h.controller.getState().managerSelection,selection);
  assert.equal(content.scrollTop,145);assert.equal(h.document.activeElement.id,reportId);assert.deepEqual(rows(),['alpha-north-cloud']);
  const query=h.nodes.get('manager-report-query');query.value='不存在的报告';h.listeners.input({target:query,isComposing:false});
  assert.deepEqual(rows(),[]);assert.match(content.innerHTML,/没有匹配的报告/);
  clickAction(h,'manager-report-clear','manager-report-clear');
  assert.equal(h.controller.getState().managerSelection.reportCompany,'all');assert.equal(h.controller.getState().managerSelection.reportKind,'all');
  assert.equal(h.controller.getState().managerSelection.reportQuery,'');assert.equal(rows().length,3);
  assert.equal(h.document.activeElement.id,'manager-report-query');
});

test('company report author, type and query remain separate from other companies and Manager report selections',()=>{
  const h=harness(formatRoute({managerId:'north',view:'reports'}));
  clickAction(h,'manager-reports-microsoft','manager-filter',{list:'reports',filter:'microsoft'});
  const managerSelection=h.controller.getState().managerSelection;
  h.controller.navigate({companyId:'alphabet',view:'reports'});
  assert.deepEqual(h.controller.getState().companyReportSelection,{counterpartId:'all',kind:'all',query:'',page:0});
  clickAction(h,'company-report-counterpartId-north','company-report-filter',{field:'counterpartId',value:'north'});
  clickAction(h,'company-report-kind-topic','company-report-filter',{field:'kind',value:'topic'});
  const input=h.nodes.get('company-report-query');input.value='云业务';h.listeners.input({target:input,isComposing:false});
  const selection=h.controller.getState().companyReportSelection;
  const rows=()=>tags(h.nodes.get('item-directory').innerHTML).filter(item=>item.href&&item.class?.split(' ').includes('directory-row'));
  assert.deepEqual(rows().map(row=>parseRoute(row.href).reportId),['alpha-north-cloud']);
  const link=h.nodes.get('open-alpha-north-cloud-v2');link.focus();h.nodes.get('content').scrollTop=180;h.nodes.get('item-directory').scrollTop=75;
  h.listeners.click({button:0,target:link,preventDefault(){}});
  const reader=h.nodes.get('report-title'),route={...h.controller.getState().route};h.nodes.get('content').scrollTop=410;
  clickAction(h,'company-report-counterpartId-field','company-report-filter',{field:'counterpartId',value:'field'});
  assert.deepEqual(rows(),[]);assert.equal(h.nodes.get('report-title'),reader);
  assert.equal(h.nodes.get('content').scrollTop,410);assert.deepEqual(h.controller.getState().route,route,'filtering does not silently replace the report being read');
  clickAction(h,'company-report-counterpartId-north','company-report-filter',{field:'counterpartId',value:'north'});
  h.nodes.get('item-directory').scrollTop=75;
  h.listeners.click({button:0,target:h.nodes.get('back-to-company'),preventDefault(){}});
  assert.deepEqual(h.controller.getState().companyReportSelection,selection);
  assert.equal(h.nodes.get('content').scrollTop,180);assert.equal(h.nodes.get('item-directory').scrollTop,75);
  assert.equal(h.document.activeElement.id,'open-alpha-north-cloud-v2');
  h.controller.navigate({companyId:'microsoft',view:'reports'});
  assert.deepEqual(h.controller.getState().companyReportSelection,{counterpartId:'all',kind:'all',query:'',page:0});
  h.controller.navigate({managerId:'north',view:'reports'});
  assert.deepEqual(h.controller.getState().managerSelection,managerSelection);
  h.controller.navigate({managerId:'field',view:'reports'});
  assert.equal(h.controller.getState().managerSelection.reportCompany,'all');assert.equal(h.controller.getState().managerSelection.reportQuery,'');
  h.controller.navigate({companyId:'alphabet',view:'reports'});
  assert.deepEqual(h.controller.getState().companyReportSelection,selection);
});

test('report title search preserves Chinese composition until commit and restores the caret in both entry dimensions',()=>{
  for(const entry of [{managerId:'north',view:'reports'},{companyId:'alphabet',view:'reports'}]) {
    const h=harness(formatRoute(entry)),manager=!!entry.managerId,id=manager?'manager-report-query':'company-report-query';
    const input=h.nodes.get(id),container=h.nodes.get(manager?'content':'item-directory'),originalHTML=container.innerHTML;
    const query=()=>manager?h.controller.getState().managerSelection.reportQuery:h.controller.getState().companyReportSelection.query;
    input.focus();h.listeners.compositionstart({target:input});input.value='云';
    h.listeners.input({target:input,isComposing:true});
    assert.equal(query(),'');assert.equal(h.nodes.get(id),input);assert.equal(container.innerHTML,originalHTML);
    input.value='云业务';input.setSelectionRange(3,3);h.listeners.compositionend({target:input});
    assert.equal(query(),'云业务');assert.equal(h.document.activeElement.id,id);
    assert.equal(h.document.activeElement.value,'云业务');assert.equal(h.document.activeElement.selectionStart,3);
    assert.match(container.innerHTML,/alpha-north-cloud/);assert.doesNotMatch(container.innerHTML,/id="(?:manager-report-|open-)alpha-field/);
  }
});

test('a detached composition cannot apply a previous Manager query to the newly selected Manager',()=>{
  const h=harness(formatRoute({managerId:'north',view:'reports'})),old=h.nodes.get('manager-report-query');
  h.listeners.compositionstart({target:old});old.value='云业务';
  h.controller.navigate({managerId:'field',view:'reports'});
  assert.equal(old.isConnected,false);
  const current=h.nodes.get('manager-report-query');current.value='产能';h.listeners.input({target:current,isComposing:false});
  assert.equal(h.controller.getState().managerSelection.reportQuery,'产能','navigation releases the previous composition lock even without an old compositionend');
  h.listeners.compositionend({target:old});
  assert.equal(h.controller.getState().managerSelection.reportQuery,'产能','a late event belongs to the detached author scope');
  h.controller.navigate({managerId:'north',view:'reports'});
  assert.equal(h.controller.getState().managerSelection.reportQuery,'');
});

test('navigation animation keeps event targets alive through resize frames and refreshes once at transition end without replacing the open card',async()=>{
  const h=chartHarness(),content=h.nodes.get('content');
  h.geometry.set('investment-performance-plot',{top:100,bottom:450,height:350,width:760,left:90,right:850});h.triggerResize('content');
  const markers=()=>['investment-trades-host','investment-timeline-host'].flatMap(id=>h.nodes.get(id).querySelectorAll('[data-action="investment-event-group"]'));
  const marker=markers()[0];clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  const originalMarkers=markers(),card=h.nodes.get('investment-popover-title'),popover=h.nodes.get('investment-event-popover');
  const html=popover.innerHTML,event={...h.controller.getState().investmentEvent},chart=h.nodes.get('institution-chart-surface'),donut=h.nodes.get('institution-donut');
  content.scrollTop=40;
  h.listeners.pointerover({pointerType:'mouse',target:h.nodes.get('global-nav'),relatedTarget:content});
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(h.controller.getState().navigationAnimating,true);
  for(const width of [710,660,620]) {
    h.geometry.set('investment-performance-plot',{top:100,bottom:400,height:300,width,left:160,right:160+width});h.triggerResize('content');
    assert.deepEqual(markers(),originalMarkers,'intermediate widths do not replace clickable event targets');
    assert.ok(originalMarkers.every(node=>node.isConnected));assert.equal(popover.innerHTML,html);
  }
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'opacity'});
  assert.equal(h.controller.getState().navigationAnimating,true,'unrelated transitions cannot end the layout transaction');
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(h.controller.getState().navigationAnimating,false);assert.ok(originalMarkers.every(node=>!node.isConnected));
  const after=markers();assert.ok(after.some(node=>node.getAttribute('aria-expanded')==='true'));
  assert.equal(popover.hidden,false);assert.equal(popover.innerHTML,html);assert.equal(h.nodes.get('investment-popover-title'),card);
  assert.deepEqual(h.controller.getState().investmentEvent,event);assert.equal(h.nodes.get('institution-chart-surface'),chart);assert.equal(h.nodes.get('institution-donut'),donut);
  assert.equal(content.scrollTop,40);
  h.triggerResize('content');assert.deepEqual(markers(),after,'same-width observer delivery does not trigger a second rebuild');
  clickAction(h,'nav-toggle','toggle-navigation');
  assert.equal(h.controller.getState().navigationAnimating,true);assert.equal(h.controller.getState().navigationExpanded,false);
  assert.equal(popover.hidden,false);assert.deepEqual(h.controller.getState().investmentEvent,event,'the explicit navigation toggle is not an outside-dismiss action');
  h.geometry.set('investment-performance-plot',{top:100,bottom:450,height:350,width:760,left:90,right:850});h.triggerResize('content');
  assert.deepEqual(markers(),after);assert.equal(popover.innerHTML,html);
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(h.controller.getState().navigationAnimating,false);assert.equal(popover.hidden,false);
  assert.equal(h.nodes.get('investment-popover-title'),card);assert.deepEqual(h.controller.getState().investmentEvent,event);
});

test('reduced motion completes navigation and refreshes event geometry once without waiting for transitionend',()=>{
  const h=chartHarness();
  h.window.matchMedia=query=>({matches:query==='(prefers-reduced-motion: reduce)'});
  h.nodes.get('investment-performance-plot').getBoundingClientRect=()=>{
    const width=h.nodes.get('workspace').dataset.navigation==='expanded'?620:760;
    return {top:100,bottom:450,height:350,width,left:90,right:90+width};
  };
  h.triggerResize('content');
  const host=h.nodes.get('investment-trades-host'),before=host.querySelectorAll('[data-action="investment-event-group"]');
  const htmlProperty=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(host),'innerHTML');
  let replacements=0;
  Object.defineProperty(host,'innerHTML',{get(){return htmlProperty.get.call(this);},set(value){replacements++;htmlProperty.set.call(this,value);}});
  clickAction(h,'nav-toggle','toggle-navigation');
  assert.equal(h.controller.getState().navigationExpanded,true);
  assert.equal(h.controller.getState().navigationAnimating,false,'reduced motion completes synchronously without a CSS event');
  assert.equal(replacements,1);assert.ok(before.every(node=>!node.isConnected));
  const after=host.querySelectorAll('[data-action="investment-event-group"]');
  assert.ok(after.length);
  h.triggerResize('content');h.windowListeners.resize();
  assert.equal(replacements,1,'same final geometry does not rebuild again on observer or window delivery');
  assert.deepEqual(host.querySelectorAll('[data-action="investment-event-group"]'),after);
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(replacements,1,'a redundant transition event cannot replay a completed update');
});

test('an open dense trade group stays attached during navigation even when intermediate widths would regroup every event',()=>{
  const h=chartHarness(),plot=h.nodes.get('investment-performance-plot');let width=1000;
  plot.getBoundingClientRect=()=>({top:100,bottom:450,height:350,width,left:90,right:90+width});h.triggerResize('content');
  const marker=h.nodes.get('investment-trades-host').querySelectorAll('[data-action="investment-event-group"]').at(-1);
  clickAction(h,marker.id,'investment-event-group',{group:marker.dataset.group});
  const state=h.controller.getState(),selected=state.investmentEvent,popover=h.nodes.get('investment-event-popover'),card=h.nodes.get('investment-popover-title'),html=popover.innerHTML;
  const data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId),view=createInvestmentEventViews({t:(zh,en)=>en,companyIcon:()=>''});
  const options={agentId:state.institutionAgent,period:data.periods.find(item=>item.id===state.institutionPeriod),kind:state.eventKind,granularity:state.eventGranularity};
  const original=view.groups({...options,width}).find(item=>item.id===marker.dataset.group);
  assert.ok(original.events.length>1,'exercise an already grouped, dense September cluster rather than a stable early-year marker');
  clickAction(h,'nav-toggle','toggle-navigation');
  for(width of [760,620,500]) {
    const next=view.groups({...options,width}).find(item=>item.events.some(event=>event.id===selected.eventId));
    assert.notEqual(next.id,original.id,'the test width genuinely changes the active event group');
    h.triggerResize('content');
    assert.equal(h.nodes.get(marker.id),marker);assert.equal(marker.isConnected,true);
    assert.deepEqual(h.controller.getState().investmentEvent,selected);assert.equal(popover.hidden,false);
    assert.equal(popover.innerHTML,html);assert.equal(h.nodes.get('investment-popover-title'),card);
  }
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  const finalGroup=view.groups({...options,width}).find(item=>item.events.some(event=>event.id===selected.eventId));
  const anchor=h.nodes.get(`investment-group-${finalGroup.id}`);
  assert.ok(anchor);assert.notEqual(anchor,marker);assert.equal(anchor.getAttribute('aria-expanded'),'true');
  assert.deepEqual(h.controller.getState().investmentEvent,selected);assert.equal(popover.hidden,false);assert.equal(popover.innerHTML,html);
});

test('regrouping moves keyboard focus to the new marker containing the same event instead of an unrelated chart control',()=>{
  const h=chartHarness(),plot=h.nodes.get('investment-performance-plot');let width=1000;
  plot.getBoundingClientRect=()=>({top:100,bottom:450,height:350,width,left:90,right:90+width});h.triggerResize('content');
  const marker=h.nodes.get('investment-trades-host').querySelectorAll('[data-action="investment-event-group"]').at(-1);
  const state=h.controller.getState(),data=getInstitution(INSTITUTION_DEMO_SCOPE.institutionId),view=createInvestmentEventViews({t:(zh,en)=>en,companyIcon:()=>''});
  const options={agentId:state.institutionAgent,period:data.periods.find(item=>item.id===state.institutionPeriod),kind:state.eventKind,granularity:state.eventGranularity};
  const eventId=view.groups({...options,width}).find(group=>group.id===marker.dataset.group).events[0].id;
  marker.focus();width=620;h.triggerResize('content');
  const next=view.groups({...options,width}).find(group=>group.events.some(event=>event.id===eventId));
  assert.notEqual(next.id,marker.dataset.group);
  assert.equal(marker.isConnected,false);assert.equal(h.document.activeElement,h.nodes.get(`investment-group-${next.id}`));
  assert.equal(h.document.activeElement.dataset.action,'investment-event-group');assert.equal(h.controller.getState().investmentEvent,null);
});

test('global navigation, the persistent object sidebar and content form three separate layers',()=>{
  const h=harness(formatRoute({companyId:'alphabet',view:'reports'}));
  const navigation=h.nodes.get('global-nav'),sidebar=h.nodes.get('sidebar'),content=h.nodes.get('content');
  assert.equal(typeof createRenderer('zh',registry).globalNavigation,'function');
  assert.equal(h.controller.getState().navigationExpanded,false);
  assert.equal(h.nodes.get('workspace').dataset.navigation,'collapsed');
  assert.equal('sidebarOpen' in h.controller.getState(),false);
  assert.equal('sidebarPinned' in h.controller.getState(),false);
  assert.match(navigation.innerHTML,/id="mode-company"/);
  assert.match(navigation.innerHTML,/id="mode-manager"/);
  assert.match(navigation.innerHTML,/id="nav-toggle"[^>]*data-action="toggle-navigation"|data-action="toggle-navigation"[^>]*id="nav-toggle"/);
  assert.equal(navigation.contains(h.nodes.get('mode-company')),true);
  assert.equal(sidebar.contains(h.nodes.get('mode-company')),false);
  assert.equal(sidebar.contains(h.nodes.get('row-company-alphabet')),true);
  assert.equal(navigation.contains(h.nodes.get('row-company-alphabet')),false);
  assert.match(sidebar.innerHTML,/id="entity-list"/);
  assert.doesNotMatch(sidebar.innerHTML,/mode-company|mode-manager|nav-toggle|close-sidebar|toggle-sidebar|pin-sidebar|sidebar-backdrop/);
  assert.equal(h.nodes.has('sidebar-backdrop'),false);
  assert.equal(h.nodes.has('sidebar-pin'),false);
  assert.equal(sidebar.hidden,false);
  assert.notEqual(sidebar.inert,true);
  assert.notEqual(h.nodes.get('workarea').inert,true);
  assert.notEqual(sidebar.attributes['aria-modal'],'true');
  assert.equal(h.controller.getState().route.view,'reports');
  assert.match(content.innerHTML,/Alphabet/);
});

test('only global-navigation hover expands its labels; leaving collapses it without changing object rows, content or route',async()=>{
  const h=harness(formatRoute({managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'}));
  const navigation=h.nodes.get('global-nav'),sidebar=h.nodes.get('sidebar'),content=h.nodes.get('content');
  const originalContent=content.innerHTML,originalSidebar=sidebar.innerHTML,originalRoute={...h.controller.getState().route};
  content.scrollTop=625;sidebar.scrollTop=35;
  const row=h.nodes.get('row-manager-north');row.dataset.key='manager-north';
  h.listeners.pointerover({pointerType:'mouse',target:row,relatedTarget:null});
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().navigationExpanded,false,'object-row hover does not expand global navigation');
  assert.equal(h.controller.getState().flyoutKey,'manager-north','object-row hover retains its own menu interaction');
  h.listeners.keydown({key:'Escape',preventDefault(){}});

  h.listeners.pointerover({pointerType:'mouse',target:navigation,relatedTarget:row});
  assert.equal(h.controller.getState().navigationExpanded,false,'global hover expansion is delayed');
  await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(h.controller.getState().navigationExpanded,true);
  assert.equal(h.nodes.get('workspace').dataset.navigation,'expanded');
  assert.equal(sidebar.hidden,false);
  assert.equal(sidebar.innerHTML,originalSidebar);
  assert.equal(content.innerHTML,originalContent);
  assert.equal(content.scrollTop,625);assert.equal(sidebar.scrollTop,35);
  assert.deepEqual(h.controller.getState().route,originalRoute);

  h.listeners.pointerout({pointerType:'mouse',target:navigation,relatedTarget:row});
  assert.equal(h.controller.getState().navigationExpanded,true,'global hover collapse is delayed');
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().navigationExpanded,false);
  assert.equal(h.nodes.get('workspace').dataset.navigation,'collapsed');
  assert.equal(sidebar.hidden,false);
  assert.equal(sidebar.innerHTML,originalSidebar);
  assert.equal(content.innerHTML,originalContent);
  assert.equal(content.scrollTop,625);assert.equal(sidebar.scrollTop,35);
  assert.deepEqual(h.controller.getState().route,originalRoute);
  assert.notEqual(sidebar.inert,true);
  assert.notEqual(h.nodes.get('workarea').inert,true);
});

test('click toggles global navigation immediately and old sidebar preferences cannot hide the object list',()=>{
  const key='uteki.company-design-swiss-c.display';
  const storage=new Map([[key,JSON.stringify({sidebarPinned:false,sidebarOpen:false,navigationExpanded:true,language:'en',theme:'dark'})]]);
  const initial=harness(formatRoute(DEMO_LAUNCH),false,storage);
  const sidebar=initial.nodes.get('sidebar'),content=initial.nodes.get('content');
  const originalSidebar=sidebar.innerHTML,originalContent=content.innerHTML,originalRoute={...initial.controller.getState().route};
  content.scrollTop=415;
  assert.equal(initial.controller.getState().navigationExpanded,false,'navigation expansion is transient');
  assert.equal(initial.nodes.get('workspace').dataset.navigation,'collapsed');
  assert.equal(sidebar.hidden,false,'legacy closed or unpinned preferences never hide the object list');
  assert.equal('sidebarOpen' in initial.controller.getState(),false);
  assert.equal('sidebarPinned' in initial.controller.getState(),false);
  assert.equal(initial.controller.getState().language,'en');
  assert.equal(initial.controller.getState().theme,'dark');
  clickAction(initial,'nav-toggle','toggle-navigation');
  assert.equal(initial.controller.getState().navigationExpanded,true,'click works without hover or a timer');
  assert.equal(initial.nodes.get('workspace').dataset.navigation,'expanded');
  clickAction(initial,'nav-toggle','toggle-navigation');
  assert.equal(initial.controller.getState().navigationExpanded,false);
  assert.equal(initial.nodes.get('workspace').dataset.navigation,'collapsed');
  assert.equal(sidebar.hidden,false);
  assert.notEqual(sidebar.inert,true);
  assert.notEqual(initial.nodes.get('workarea').inert,true);
  assert.equal(sidebar.innerHTML,originalSidebar);assert.equal(content.innerHTML,originalContent);
  assert.equal(content.scrollTop,415);assert.deepEqual(initial.controller.getState().route,originalRoute);

  clickAction(initial,'theme-button','theme');
  assert.deepEqual(JSON.parse(storage.get(key)),{language:'en',theme:'light',typography:'swiss'},'only language, theme and typography preferences are persisted');
  const refreshed=harness(formatRoute(DEMO_LAUNCH),false,storage);
  assert.equal(refreshed.controller.getState().navigationExpanded,false);
  assert.equal(refreshed.nodes.get('sidebar').hidden,false);
  assert.equal(refreshed.controller.getState().language,'en');
  assert.equal(refreshed.controller.getState().theme,'light');
});

test('navigation-width reflow compensates a visible reading anchor across successive resize frames without rebuilding the report',()=>{
  const route={managerId:'north',companyId:'alphabet',view:'report',reportId:'alpha-north-main',version:'v2'};
  const h=harness(formatRoute(route));
  const content=h.nodes.get('content'),anchor=h.nodes.get('section-business');
  const originalContent=content.innerHTML;
  content.top=30;content.scrollTop=650;anchor.top=700;
  anchor.getBoundingClientRect=()=>{
    const top=content.top+anchor.top-content.scrollTop;
    return {top,bottom:top+40,height:40,width:220,left:0,right:220};
  };
  content.querySelectorAll=()=>[anchor];
  const originalY=anchor.getBoundingClientRect().top;
  clickAction(h,'nav-toggle','toggle-navigation');
  assert.equal(h.controller.getState().navigationExpanded,true);

  anchor.top=742;
  assert.equal(h.triggerResize('content'),1,'the controller observes the reading content');
  assert.equal(content.scrollTop,692);
  assert.equal(anchor.getBoundingClientRect().top,originalY);
  anchor.top=812;
  h.triggerResize('content');
  assert.equal(content.scrollTop,762);
  assert.equal(anchor.getBoundingClientRect().top,originalY);
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(content.scrollTop,762);
  assert.equal(content.innerHTML,originalContent);
  assert.equal(h.nodes.get('section-business'),anchor);
  assert.equal(anchor.isConnected,true);
  assert.deepEqual(h.controller.getState().route,route);
});

test('institution navigation reflow retains a visible holding row without rebuilding or changing the selected portfolio view',()=>{
  const h=harness(''),content=h.nodes.get('content');
  clickAction(h,'institution-period-1m','institution-period',{period:'1m'});
  clickAction(h,'allocation-nvidia','institution-holding',{holding:'nvidia'});
  const originalContent=content.innerHTML,originalRoute={...h.controller.getState().route};
  content.top=20;content.scrollTop=450;
  // The small adapter omits un-ID'd wrappers; model the rendered holding row's geometry.
  const holdingRow={isConnected:true,top:490,getBoundingClientRect(){const top=content.top+this.top-content.scrollTop;return {top,bottom:top+35,height:35,width:220,left:0,right:220};}};
  content.querySelectorAll=selector=>selector.split(',').includes('.institution-holding-row')?[holdingRow]:[];
  const originalY=holdingRow.getBoundingClientRect().top;
  clickAction(h,'nav-toggle','toggle-navigation');
  holdingRow.top=550;
  assert.equal(h.triggerResize('content'),1);
  assert.equal(content.scrollTop,510);assert.equal(holdingRow.getBoundingClientRect().top,originalY);
  holdingRow.top=580;h.triggerResize('content');
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(content.scrollTop,540);assert.equal(holdingRow.getBoundingClientRect().top,originalY);
  assert.equal(content.innerHTML,originalContent);assert.deepEqual(h.controller.getState().route,originalRoute);
  assert.equal(h.controller.getState().institutionPeriod,'1m');assert.equal(h.controller.getState().institutionHolding,'nvidia');
});

test('Manager navigation reflow retains visible table or coverage content without resetting the selection',()=>{
  for(const [view,selector] of [['overview','.manager-table tbody tr'],['companies','.manager-coverage-card'],['reports','.manager-table tbody tr'],['activity','.manager-table tbody tr']]) {
    const h=harness(formatRoute({managerId:'north',view})),content=h.nodes.get('content');
    const html=content.innerHTML,state=h.controller.getState().managerSelection;
    content.top=20;content.scrollTop=200;
    // Model the un-ID'd rendered row/card with geometry, as with institution rows.
    const row={isConnected:true,top:240,getBoundingClientRect(){const top=content.top+this.top-content.scrollTop;return {top,bottom:top+35,height:35,width:500,left:0,right:500};}};
    content.querySelectorAll=query=>query.split(',').includes(selector)?[row]:[];
    const y=row.getBoundingClientRect().top;
    clickAction(h,'nav-toggle','toggle-navigation');
    row.top+=42;h.triggerResize('content');
    assert.equal(content.scrollTop,242);assert.equal(row.getBoundingClientRect().top,y);
    h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
    assert.equal(content.innerHTML,html);assert.deepEqual(h.controller.getState().managerSelection,state);
  }
});

test('Escape cancels a pending hover before it becomes visible',async()=>{
  const h=harness();
  const row=h.nodes.get('row-company-alphabet');row.dataset.key='company-alphabet';
  h.listeners.pointerover({pointerType:'mouse',target:{closest:()=>row},relatedTarget:null});
  h.listeners.keydown({key:'Escape',preventDefault(){}});
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().flyoutKey,null);
});

test('hovering another row never replaces a menu containing keyboard focus',async()=>{
  const h=harness();
  clickAction(h,'menu-company-alphabet','entity-menu',{key:'company-alphabet'});
  h.nodes.get('leaf-company-alphabet-reports').focus();
  const row=h.nodes.get('row-company-microsoft');row.dataset.key='company-microsoft';
  h.listeners.pointerover({pointerType:'mouse',target:{closest:()=>row},relatedTarget:null});
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().flyoutKey,'company-alphabet');
  assert.equal(h.document.activeElement.id,'leaf-company-alphabet-reports');
});

test('deferred render focus does not overwrite the selected mode button in global navigation',()=>{
  const h=harness(formatRoute(DEMO_LAUNCH),true);
  clickAction(h,'nav-toggle','toggle-navigation');
  clickAction(h,'mode-manager','mode',{mode:'manager'});
  h.flushFrames();
  assert.equal(h.document.activeElement.id,'mode-manager');
});

test('keyboard navigation stays expanded until focus leaves or pointer input takes over; Escape can dismiss it',async()=>{
  const h=harness();const navigation=h.nodes.get('global-nav'),toggle=h.nodes.get('nav-toggle');
  h.listeners.keydown({key:'Tab'});toggle.focus();
  h.listeners.focusin({target:toggle});
  assert.equal(h.controller.getState().navigationExpanded,true);
  h.listeners.pointerout({pointerType:'mouse',target:navigation,relatedTarget:h.nodes.get('sidebar')});
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().navigationExpanded,true,'keyboard focus holds navigation open');
  h.listeners.pointerdown({pointerType:'mouse',target:toggle});
  h.listeners.pointerout({pointerType:'mouse',target:navigation,relatedTarget:h.nodes.get('sidebar')});
  await new Promise(resolve=>setTimeout(resolve,200));
  assert.equal(h.controller.getState().navigationExpanded,false,'pointer departure releases the previous keyboard hold');
  h.listeners.keydown({key:'Tab'});h.listeners.focusin({target:toggle});
  h.listeners.keydown({key:'Escape',preventDefault(){}});
  assert.equal(h.controller.getState().navigationExpanded,false);
  assert.equal(h.document.activeElement.id,'nav-toggle');
  assert.deepEqual(h.controller.getState().route,DEMO_LAUNCH);
});

test('skip to content preserves the business route instead of navigating to an invalid hash',()=>{
  const h=harness();const before=h.window.location.hash;let prevented=false;
  h.listeners.click({target:{closest:selector=>selector==='.skip-link'?{}:null},preventDefault(){prevented=true;}});
  assert.equal(prevented,true);
  assert.equal(h.window.location.hash,before);
  assert.equal(h.document.activeElement.id,'content');
});


test('company author summary counts published contributors instead of legacy placeholder relationships',()=>{
  const render=createRenderer('en',registry);
  for(const company of catalog.companies) {
    const route={companyId:company.id,view:'reports'};
    const authors=[...new Set(catalog.reports.filter(report=>report.companyId===company.id).map(report=>report.managerId))];
    assert.ok(render.contentNavigation(route).includes(`${authors.length} report authors`));
    const panel=render.panel(route,{kind:'context'});
    if(!authors.length) assert.match(panel,/No report authors yet/);
    for(const manager of catalog.managers.filter(manager=>!authors.includes(manager.id))) assert.ok(!panel.includes(manager.name));
  }
});


test('portfolio decision research returns to the exact decision, tab, scroll and report-link focus after reading another version',()=>{
  const decision=getDecision('north',getFeaturedDecisionId('north'));
  const origin={managerId:'north',view:'decisions',decisionId:decision.id,decisionTab:'research'};
  const h=harness(formatRoute(origin)),content=h.nodes.get('content');
  const source=tags(content.innerHTML).find(item=>item.id?.startsWith('decision-report-')&&item.href);
  assert.ok(source,'A visible research link is available');
  const reference=parseRoute(source.href);
  assert.equal(reference.managerId,'north');
  assert.ok(decision.reports.some(item=>item.companyId===reference.companyId&&item.reportId===reference.reportId&&item.version===reference.version));
  content.scrollTop=276;h.nodes.get(source.id).focus();
  h.listeners.click({button:0,target:h.nodes.get(source.id),preventDefault(){}});
  assert.deepEqual(h.controller.getState().route,reference);
  const previous=getReport(reference.companyId,reference.reportId,reference.version).document.versions.find(item=>item.version!==reference.version);
  if(previous)h.listeners.change({target:{id:'report-version',value:previous.version}});
  const back=h.nodes.get('back-to-company');
  assert.deepEqual(parseRoute(back.getAttribute('href')),origin);
  assert.match(content.innerHTML,/返回组合决策/);
  h.listeners.click({button:0,target:back,preventDefault(){}});
  assert.deepEqual(h.controller.getState().route,origin);
  assert.equal(content.scrollTop,276);
  assert.equal(h.document.activeElement.id,source.id);
});

test('each manager remembers the selected decision and tab when returning from another workspace section',()=>{
  const north=getManagerDecisions('north')[1],field=getManagerDecisions('field')[0];
  const a={managerId:'north',view:'decisions',decisionId:north.id,decisionTab:'risk'};
  const b={managerId:'field',view:'decisions',decisionId:field.id,decisionTab:'research'};
  const h=harness(formatRoute(a));
  h.nodes.get('content').scrollTop=140;
  h.controller.navigate({managerId:'north',view:'activity'});
  h.controller.navigate(b);
  h.controller.navigate({managerId:'field',view:'companies'});
  h.controller.navigate({managerId:'north',view:'decisions'});
  assert.deepEqual(h.controller.getState().route,a);
  assert.equal(h.nodes.get('content').scrollTop,140);
  h.controller.navigate({managerId:'field',view:'decisions'});
  assert.deepEqual(h.controller.getState().route,b);
  const explicit={managerId:'north',view:'decisions',decisionId:getFeaturedDecisionId('north'),decisionTab:'allocation'};
  h.controller.navigate(explicit);
  assert.deepEqual(h.controller.getState().route,explicit,'An explicit new link overrides remembered selection');
});

test('homepage decision entry follows the selected portfolio without assigning its targets to holdings',()=>{
  const h=harness('');
  clickAction(h,'institution-agent-field','institution-agent',{agent:'field'});
  const stage=h.nodes.get('portfolio-stage');
  const decisionLinks=tags(stage.innerHTML).filter(item=>item.href?.includes('view=decisions'));
  assert.ok(decisionLinks.length>0);
  decisionLinks.forEach(item=>{
    const route=parseRoute(item.href);
    assert.equal(route.managerId,'field');
    assert.equal(route.decisionId,getFeaturedDecisionId('field'));
  });
  const holdingBefore=h.controller.getState().institutionHolding;
  h.controller.navigate(parseRoute(decisionLinks[0].href));
  h.controller.navigate(INSTITUTION_DEMO_SCOPE);
  assert.equal(h.controller.getState().institutionAgent,'field');
  assert.equal(h.controller.getState().institutionHolding,holdingBefore);
  assert.equal(h.nodes.get('portfolio-stage').dataset.agent,'field');
});

test('a cross-manager decision URL renders a scope error without substituting the other manager decision',()=>{
  const h=harness(`#/manager/field?view=decisions&decision=${getFeaturedDecisionId('north')}&tab=allocation`);
  assert.equal(h.controller.getState().route,null);
  assert.match(h.nodes.get('content').innerHTML,/页面范围无法确认/);
  assert.doesNotMatch(h.nodes.get('content').innerHTML,/class="decision-workspace/);
});


test('portfolio decisions inherit the chosen portfolio palette and retain a reading anchor during typography changes',()=>{
  const key='uteki.company-design-swiss-c.allocation-palette',palette=ALLOCATION_PALETTES.find(item=>item.id!=='bright');
  const route={managerId:'north',view:'decisions',decisionId:getFeaturedDecisionId('north'),decisionTab:'risk'};
  const h=harness(formatRoute(route),false,new Map([[key,palette.id]]));
  const content=h.nodes.get('content'),workspace=h.nodes.get('portfolio-decisions');
  assert.equal(workspace.getAttribute('style'),allocationPaletteStyle(palette.id));
  content.scrollTop=220;
  const paragraph={isConnected:true,getBoundingClientRect(){const top=content.top+(h.document.documentElement.dataset.typography==='hybrid'?370:310)-content.scrollTop;return {top,bottom:top+45,height:45};}};
  const originalQuery=content.querySelectorAll.bind(content);
  content.querySelectorAll=selector=>selector.includes('.decision-risk-item')?[paragraph]:originalQuery(selector);
  const y=paragraph.getBoundingClientRect().top;
  const select=h.nodes.get('typography-select');select.value='hybrid';h.listeners.change({target:select});
  assert.equal(content.scrollTop,280);assert.equal(paragraph.getBoundingClientRect().top,y);
  assert.equal(h.nodes.get('portfolio-decisions'),workspace);
  assert.deepEqual(h.controller.getState().route,route);
});


test('navigation reflow retains the decision reading position without replacing content or changing its selected tab',()=>{
  for(const [tab,selector] of [['allocation','.decision-allocation-table tbody tr'],['research','.decision-research-item'],['risk','.decision-risk-item']]) {
    const route={managerId:'north',view:'decisions',decisionId:getFeaturedDecisionId('north'),decisionTab:tab};
    const h=harness(formatRoute(route)),content=h.nodes.get('content'),workspace=h.nodes.get('portfolio-decisions');
    const html=content.innerHTML;
    content.top=20;content.scrollTop=200;
    const row={isConnected:true,top:240,getBoundingClientRect(){const top=content.top+this.top-content.scrollTop;return {top,bottom:top+35,height:35,width:500,left:0,right:500};}};
    const originalQuery=content.querySelectorAll.bind(content);
    content.querySelectorAll=query=>query.split(',').includes(selector)?[row]:originalQuery(query);
    const y=row.getBoundingClientRect().top;
    clickAction(h,'nav-toggle','toggle-navigation');
    row.top+=42;h.triggerResize('content');
    assert.equal(content.scrollTop,242);assert.equal(row.getBoundingClientRect().top,y);
    h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
    assert.equal(content.innerHTML,html);assert.equal(h.nodes.get('portfolio-decisions'),workspace);
    assert.deepEqual(h.controller.getState().route,route);
  }
});


function followRiskLink(h,id) {
  const node=h.nodes.get(id);assert.ok(node,`Link ${id} exists`);node.focus();
  h.listeners.click({button:0,target:node,preventDefault(){}});
}

test('risk source reading preserves exact evidence section and returns to filtered risk, scroll and focus',()=>{
  const origin={managerId:'north',view:'risks',riskId:'north-renewal-gap',riskFilter:'monitoring'};
  const h=harness(formatRoute(origin)),content=h.nodes.get('content');
  const reference=getRisk('north',origin.riskId).observations[0].sources[0];
  const source=tags(content.innerHTML).find(item=>item.id?.startsWith('risk-source-')&&item.href);
  assert.ok(source);assert.match(content.innerHTML,/原文不可用/);
  content.scrollTop=305;followRiskLink(h,source.id);
  assert.deepEqual(h.controller.getState().route,{managerId:'north',view:'report',companyId:reference.companyId,reportId:reference.reportId,version:reference.version,sectionId:reference.sectionId});
  assert.deepEqual(parseRoute(h.nodes.get('back-to-company').getAttribute('href')),origin);
  assert.match(content.innerHTML,/返回风险跟踪/);
  followRiskLink(h,'back-to-company');
  assert.deepEqual(h.controller.getState().route,origin);
  assert.equal(content.scrollTop,305);assert.equal(h.document.activeElement.id,source.id);
});

test('risk to decision to report and back retains each origin rather than replacing the risk with the decision list',()=>{
  const origin={managerId:'field',view:'risks',riskId:'field-delivery-chain',riskFilter:'monitoring'};
  const h=harness(formatRoute(origin)),content=h.nodes.get('content');
  const reference=tags(content.innerHTML).find(item=>item.id?.startsWith('risk-decision-')&&item.href);
  assert.ok(reference);content.scrollTop=470;followRiskLink(h,reference.id);
  assert.equal(h.controller.getState().route.view,'decisions');
  assert.deepEqual(parseRoute(h.nodes.get('decision-back-to-risk').getAttribute('href')),origin);
  followRiskLink(h,'decision-tab-research');
  const decisionOrigin={...h.controller.getState().route};
  const source=tags(content.innerHTML).find(item=>item.id?.startsWith('decision-report-')&&item.href);
  content.scrollTop=235;followRiskLink(h,source.id);
  followRiskLink(h,'back-to-company');
  assert.deepEqual(h.controller.getState().route,decisionOrigin);
  assert.equal(content.scrollTop,235);assert.equal(h.document.activeElement.id,source.id);
  followRiskLink(h,'decision-back-to-risk');
  assert.deepEqual(h.controller.getState().route,origin);
  assert.equal(content.scrollTop,470);assert.equal(h.document.activeElement.id,reference.id);
});

test('risk filters exclude old selection and have honest empty states while per-manager risk selections stay separate',()=>{
  const h=harness(formatRoute({managerId:'north',view:'risks',riskId:'north-shared-growth',riskFilter:'all'}));
  followRiskLink(h,'risk-filter-monitoring');
  assert.equal(h.controller.getState().route.riskId,undefined);
  assert.equal(h.nodes.get('risk-register').dataset.risk,'');
  assert.match(h.nodes.get('content').innerHTML,/选择一项风险继续阅读/);
  followRiskLink(h,'risk-select-north-payment-quality');
  const north={...h.controller.getState().route};h.nodes.get('content').scrollTop=146;
  h.controller.navigate({managerId:'field',view:'risks',riskId:'field-delivery-chain',riskFilter:'monitoring'});
  const field={...h.controller.getState().route};
  h.controller.navigate({managerId:'north',view:'risks'});
  assert.deepEqual(h.controller.getState().route,north);assert.equal(h.nodes.get('content').scrollTop,146);
  followRiskLink(h,'risk-filter-resolved');
  assert.equal(h.nodes.get('risk-register').dataset.risk,'');
  assert.match(h.nodes.get('content').innerHTML,/该状态下暂无记录/);
  assert.match(h.nodes.get('content').innerHTML,/其他状态的风险仍保留/);
  assert.equal(h.nodes.has('risk-title'),false);
  followRiskLink(h,'risk-filter-clear');assert.equal(h.controller.getState().route.riskFilter,'all');
  h.controller.navigate({managerId:'field',view:'risks'});assert.deepEqual(h.controller.getState().route,field);
});

test('homepage risk summary follows selected Agent and counts persistent risks rather than the latest decision opinions',()=>{
  const h=harness('');
  assert.ok(tags(h.nodes.get('content').innerHTML).some(item=>item['data-risk-summary']==='north'));
  for(const managerId of ['field','north']) {
    clickAction(h,`institution-agent-${managerId}`,'institution-agent',{agent:managerId});
    const html=h.nodes.get('portfolio-stage').innerHTML;
    const risks=getManagerRisks(managerId);
    assert.ok(tags(html).some(item=>item['data-risk-summary']===managerId));
    const links=tags(html).filter(item=>item.href?.includes('view=risks'));
    assert.ok(links.length>=1);links.forEach(item=>assert.equal(parseRoute(item.href).managerId,managerId));
    assert.ok(risks.some(item=>item.id===getFeaturedRiskId(managerId)));
    const counters=[...html.matchAll(/data-status-count="([^"]+)"[^>]*>[^<]*<strong>([0-9]+)<\/strong>/g)];
    assert.equal(counters.length,2);
    for(const [,status,count] of counters)assert.equal(Number(count),risks.filter(item=>item.status===status).length);
  }
});

test('risk navigation and typography reflow retain visible content without changing risk state or rebuilding it',()=>{
  const route={managerId:'field',view:'risks',riskId:'field-delivery-chain',riskFilter:'monitoring'};
  const h=harness(formatRoute(route)),content=h.nodes.get('content'),workspace=h.nodes.get('risk-register');
  content.top=20;content.scrollTop=200;
  const row={isConnected:true,top:240,getBoundingClientRect(){const top=content.top+this.top-content.scrollTop;return {top,bottom:top+35,height:35,width:500,left:0,right:500};}};
  const originalQuery=content.querySelectorAll.bind(content);
  content.querySelectorAll=query=>query.includes('.risk-observation')?[row]:originalQuery(query);
  const y=row.getBoundingClientRect().top;
  clickAction(h,'nav-toggle','toggle-navigation');row.top+=42;h.triggerResize('content');
  h.listeners.transitionend({target:h.nodes.get('workspace'),propertyName:'grid-template-columns'});
  assert.equal(row.getBoundingClientRect().top,y);assert.equal(content.scrollTop,242);
  assert.equal(h.nodes.get('risk-register'),workspace);assert.deepEqual(h.controller.getState().route,route);
  clickAction(h,'theme-button','theme');clickAction(h,'language-button','language');
  assert.deepEqual(h.controller.getState().route,route);assert.equal(content.scrollTop,242);
  assert.match(content.innerHTML,/Risk Manager/);assert.equal(h.document.documentElement.dataset.theme,'dark');
});
