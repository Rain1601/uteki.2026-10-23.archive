import { formatRoute, parseRoute, getReport, getInstitution, routeContext } from './model.mjs';
import { createRenderer, escapeHTML } from './render.mjs?v=20261004-investment-timeline2';
import { INSTITUTION_DEMO_SCOPE } from './institution-data.mjs';
import { DEFAULT_ALLOCATION_PALETTE, getAllocationPalette, allocationPaletteStyle } from './allocation-palettes.mjs';
import { validateBrandRegistry } from '../../../apps/uteki_zero/brands.mjs';
import { createHoverMenu } from './hover-menu.mjs';
import { placeChartEventPopover } from './chart-event-popover.mjs';

// A named, explicit fixture launch, used only for an empty URL in this design sample.
export const DEMO_LAUNCH = Object.freeze({companyId:'alphabet',view:'overview'});
export const MANAGER_DEMO_LAUNCH = Object.freeze({managerId:'north',view:'overview'});
export const HOME_DEMO_LAUNCH = INSTITUTION_DEMO_SCOPE;
const SETTINGS_KEY = 'uteki.company-design-v2.display';
const PALETTE_KEY = 'uteki.company-design-v2.allocation-palette';
const OVERVIEW_SECTIONS = ['changes','research','materials','tracking'];

export function createController({document:doc,window:win,registry}) {
  const el = id => doc.getElementById(id);
  const content=el('content'), panelElement=el('context-panel');
  const investmentPopover=el('investment-event-popover');
  const positions=new Map(), returns=new Map(), entityRoutes=new Map();
  const globalNav=el('global-nav'),sidebar=el('sidebar'),flyout=el('entity-flyout');
  const modeRoutes=new Map([['institution',HOME_DEMO_LAUNCH],['company',DEMO_LAUNCH],['manager',MANAGER_DEMO_LAUNCH]]);
  const queries=new Map([['institution',''],['company',''],['manager','']]);
  const overviewSelections=new Map();
  const itemSelections=new Map(),directoryPositions=new Map();
  const institutionSelections=new Map();
  const managerSelections=new Map();
  let route=null, panel=null, query='', invokerId='', lastHash='', view;
  let language='zh',theme='light';
  let allocationPalette=DEFAULT_ALLOCATION_PALETTE;
  let navigationExpanded=false,flyoutKey=null;
  let navigationPointerInside=false,navigationKeyboardFocus=false,keyboardInput=false;
  let navigationAnchor=null,navigationEnd=null;
  let overviewTimer=null;
  let allocationHover=null,allocationFocus=null;
  let lastTimelineWidth=0;
  let investmentEvent=null;
  try {
    const saved=JSON.parse(win.localStorage.getItem(SETTINGS_KEY) || '{}');
    if(saved.language==='en') language='en';
    if(saved.theme==='dark') theme='dark';
  } catch { /* Display preferences are optional; research state is never stored here. */ }
  try {
    const saved=win.localStorage.getItem(PALETTE_KEY);
    if(saved) allocationPalette=getAllocationPalette(saved).id;
  } catch { /* Missing, stale or unavailable display preferences keep the declared visual default. */ }

  function saveDisplay() {
    try { win.localStorage.setItem(SETTINGS_KEY,JSON.stringify({language,theme})); } catch {}
  }
  const announce = text => { el('announcement').textContent=text; };
  const mode = target => target.institutionId?'institution':target.managerId?'manager':'company';
  const entityKey = target => `${mode(target)}-${target.institutionId||target.managerId||target.companyId}`;
  const reportKey = target => `${entityKey(target)}/${target.companyId}/${target.reportId}`;
  const directoryKey = () => route&&mode(route)==='company'?`${route.companyId}/${route.view==='report'?'reports':route.view}`:null;
  const itemSelection = () => route&&mode(route)==='company'&&['materials','tracking'].includes(route.view)?itemSelections.get(directoryKey())||null:null;
  const overviewSection = () => route&&mode(route)==='company'&&route.view==='overview'?(overviewSelections.get(route.companyId)||'changes'):null;
  const institutionState = () => {
    if(!route?.institutionId) return null;
    const data=getInstitution(route.institutionId);
    return {...(institutionSelections.get(route.institutionId)||{period:data.defaultPeriod,agentId:data.defaultAgentId,holdingId:null,eventKind:'all',eventGranularity:'auto'}),paletteId:allocationPalette,eventWidth:timelineWidth()};
  };
  const managerState = () => route?.managerId?{researchFilter:'all',researchPage:0,reportCompany:'all',reportPage:0,activityKind:'all',activityPage:0,...managerSelections.get(route.managerId),paletteId:allocationPalette}:null;
  function selectManagerList(button) {
    const lists={research:{views:['overview'],filter:'researchFilter',page:'researchPage'},reports:{views:['reports'],filter:'reportCompany',page:'reportPage'},activity:{views:['activity','holdings'],filter:'activityKind',page:'activityPage'}};
    const list=lists[button.dataset.list];
    if(!route?.managerId||!list?.views.includes(route.view)) throw new Error('Manager list is outside the current view');
    if(button.dataset.action==='manager-filter'&&(typeof button.dataset.filter!=='string'||!button.dataset.filter)) throw new Error('Manager list filter is required');
    if(button.dataset.action==='manager-page'&&!/^(0|[1-9]\d*)$/.test(button.dataset.page??'')) throw new Error('Manager list page is required');
    const patch=button.dataset.action==='manager-filter'?{[list.filter]:button.dataset.filter,[list.page]:0}:{[list.page]:Number(button.dataset.page)};
    const next={...managerState(),...patch};
    // Resolve the selected author, filter and page before changing the visible state.
    const html=view.managerMain(route,next);
    managerSelections.set(route.managerId,next);
    content.innerHTML=html;content.scrollTop=0;
    const focus=[el(button.id),el(`manager-${button.dataset.list}-prev`),el(`manager-${button.dataset.list}-next`)].find(node=>node&&node.getAttribute('disabled')===null);
    (focus||content).focus({preventScroll:true});
    announce(view.t('列表已更新','List updated'));
  }
  function openManagerCompanyReports(companyId) {
    if(!route?.managerId||route.view!=='companies') throw new Error('Company report selection requires Manager coverage');
    if(typeof companyId!=='string'||!companyId||companyId==='all') throw new Error('Select an explicit covered company');
    const target={managerId:route.managerId,view:'reports'};
    const next={...managerState(),reportCompany:companyId,reportPage:0};
    view.managerMain(target,next);
    managerSelections.set(route.managerId,next);
    positions.set(formatRoute(target),{top:0,focus:''});
    navigate(target);
  }
  function timelineWidth() { return el('institution-dashboard')?.getBoundingClientRect().width||content.clientWidth||1000; }
  function investmentEventOptions() {
    const state=institutionState();
    if(!state) throw new Error('Investment events require an institution overview');
    return {agentId:state.agentId,period:getInstitution(route.institutionId).periods.find(item=>item.id===state.period),kind:state.eventKind,granularity:state.eventGranularity,width:state.eventWidth};
  }
  function selectedInvestmentGroups(options) {
    if(!investmentEvent) return [];
    const original=view.investmentEvents.groups(investmentEvent.options).find(group=>group.id===investmentEvent.groupId);
    if(!original) return [];
    const ids=new Set(original.events.map(event=>event.id));
    return view.investmentEvents.groups(options).filter(group=>group.events.some(event=>ids.has(event.id))).map(group=>group.id);
  }
  function updateInvestmentMarkers() {
    if(!route?.institutionId) return;
    const selected=new Set(selectedInvestmentGroups(investmentEventOptions()));
    for(const marker of content.querySelectorAll('[data-action="investment-event-group"]')) marker.setAttribute('aria-expanded',String(selected.has(marker.dataset.group)));
    const guide=el('investment-event-guide');
    if(guide) guide.hidden=!investmentEvent;
  }
  function closeInvestmentPopover({restoreFocus=true}={}) {
    if(!investmentEvent) return;
    const old=investmentEvent;
    const replacement=selectedInvestmentGroups(investmentEventOptions())[0];
    investmentEvent=null;investmentPopover.hidden=true;investmentPopover.innerHTML='';
    updateInvestmentMarkers();
    if(restoreFocus) (el(old.invokerId)||el(`investment-group-${replacement}`)||content).focus({preventScroll:true});
  }
  function positionInvestmentPopover() {
    if(!investmentEvent||!route?.institutionId) return;
    const group=view.investmentEvents.groups(investmentEventOptions()).find(item=>item.events.some(event=>event.id===investmentEvent.eventId));
    const anchor=group&&el(`investment-group-${group.id}`);
    if(!anchor) {closeInvestmentPopover({restoreFocus:false});return;}
    const a=anchor.getBoundingClientRect(),c=content.getBoundingClientRect();
    const bounds={left:Math.max(0,c.left),right:Math.min(win.innerWidth,c.right),top:Math.max(0,c.top),bottom:Math.min(win.innerHeight,c.bottom)};
    if(a.bottom<=bounds.top||a.top>=bounds.bottom||bounds.right<=bounds.left||bounds.bottom<=bounds.top) {closeInvestmentPopover({restoreFocus:false});return;}
    investmentPopover.style.width=`${Math.min(340,Math.max(1,bounds.right-bounds.left-16))}px`;
    investmentPopover.style.maxHeight='';
    const size=investmentPopover.getBoundingClientRect();
    // The decorative arrow contributes to scrollHeight; measure the uncapped
    // card rectangle so it does not incorrectly force an otherwise fitting card below.
    const position=placeChartEventPopover({anchor:a,bounds,size:{width:size.width,height:size.height}});
    if(position.maxHeight<=0) {closeInvestmentPopover({restoreFocus:false});return;}
    investmentPopover.style.left=`${position.left}px`;investmentPopover.style.top=`${position.top}px`;
    investmentPopover.style.width=`${position.width}px`;investmentPopover.style.maxHeight=`${position.maxHeight}px`;
    investmentPopover.style.setProperty?.('--event-arrow-x',`${position.arrowX}px`);
    investmentPopover.dataset.placement=position.placement;
    const guide=el('investment-event-guide');
    if(guide) {guide.hidden=false;guide.style.left=`${group.x}%`;}
  }
  function renderInvestmentPopover({focus=true,focusId='investment-popover-title'}={}) {
    if(!investmentEvent) return;
    const {options,groupId,eventId}=investmentEvent;
    const html=view.investmentEvents.popover(options,groupId,eventId);
    const event=view.investmentEvents.groups(options).find(group=>group.id===groupId).events.find(item=>item.id===eventId);
    investmentPopover.innerHTML=html;investmentPopover.hidden=false;investmentPopover.dataset.kind=event.kind;
    updateInvestmentMarkers();positionInvestmentPopover();
    if(focus&&!investmentPopover.hidden) {
      const target=el(focusId);
      (target&&target.getAttribute('disabled')===null?target:el('investment-popover-title')).focus({preventScroll:true});
    }
  }
  function openInvestmentPopover(groupId,invokerId) {
    const options=investmentEventOptions(),group=view.investmentEvents.groups(options).find(item=>item.id===groupId);
    if(!group) throw new Error('Investment event group is outside the current selection');
    // Validate all data before changing the visible card or selection.
    view.investmentEvents.popover(options,groupId,group.events[0].id);
    investmentEvent={options,groupId,eventId:group.events[0].id,invokerId};
    renderInvestmentPopover();
  }
  function stepInvestmentPopover(step,focusId) {
    if(!investmentEvent||![1,-1].includes(step)) return;
    const {options,groupId,eventId}=investmentEvent;
    const events=view.investmentEvents.groups(options).find(group=>group.id===groupId).events;
    const next=events.findIndex(item=>item.id===eventId)+step;
    if(next<0||next>=events.length) return;
    view.investmentEvents.popover(options,groupId,events[next].id);
    investmentEvent={...investmentEvent,eventId:events[next].id};
    renderInvestmentPopover({focusId});
  }
  function refreshInvestmentTimeline(force=false) {
    const host=el('investment-timeline-host');
    if(!route?.institutionId||!host) return;
    const options=investmentEventOptions();
    if(!force&&Math.abs(options.width-lastTimelineWidth)<10) {positionInvestmentPopover();return;}
    const controls=el('investment-controls-host');
    const trades=el('investment-trades-host');
    const focusId=(host.contains(doc.activeElement)||controls?.contains(doc.activeElement)||trades?.contains(doc.activeElement))?doc.activeElement.id:null;
    const groupIds=selectedInvestmentGroups(options);
    const html=view.investmentEvents.timeline({...options,showControls:false,groupIds});
    const tradeHTML=view.institutionTrades(route,institutionState(),groupIds);
    host.innerHTML=html;
    if(trades) trades.innerHTML=tradeHTML;
    lastTimelineWidth=options.width;
    if(force&&controls) controls.innerHTML=view.investmentEvents.controls(options);
    if(focusId) (el(focusId)||el('investment-event-granularity')||content).focus({preventScroll:true});
    updateInvestmentMarkers();positionInvestmentPopover();
  }
  function selectAllocationPalette(id) {
    if(!route?.institutionId) throw new Error('Palette selection requires an institution overview');
    const palette=getAllocationPalette(id),style=allocationPaletteStyle(id);
    allocationPalette=palette.id;
    // Update shared color tokens in place so chart selection, focus and reading position survive.
    const dashboard=el('institution-dashboard');
    dashboard.setAttribute('style',style);
    dashboard.setAttribute('data-allocation-palette',id);
    for(const button of content.querySelectorAll('[data-action="allocation-palette"]')) button.setAttribute('aria-pressed',String(button.dataset.palette===id));
    let saved=true;
    try { win.localStorage.setItem(PALETTE_KEY,id); } catch { saved=false; }
    announce(view.t(`已切换为${palette.name}配色${saved?'':'，仅本次页面生效'}`,`${palette.nameEn} palette applied${saved?'':' for this visit only'}`));
  }
  const allocationTarget = target => target?.closest?.('[data-action="institution-holding"]')||target?.closest?.('[data-allocation-row]');
  function updateAllocationDisplay() {
    if(!route?.institutionId) return;
    const selected=institutionState().holdingId,preview=allocationHover||allocationFocus;
    const shown=preview||selected,item=shown?el(`allocation-${shown}`):null;
    for(const slice of content.querySelectorAll('.allocation-segment')) {
      const id=slice.dataset.holding;
      slice.setAttribute('aria-pressed',String(id===selected));
      slice.classList.toggle('is-emphasized',id===shown);
      slice.classList.toggle('is-muted',!!shown&&id!==shown);
    }
    for(const row of content.querySelectorAll('[data-allocation-row]')) {
      const id=row.dataset.allocationRow;
      row.classList.toggle('is-active',id===selected);
      row.classList.toggle('is-preview',id===preview);
      el(`allocation-${id}`)?.setAttribute('aria-pressed',String(id===selected));
    }
    for(const [id,value] of [['allocation-value',item?.dataset.weight],['allocation-name',item?.dataset.name],['allocation-caption',item?.dataset.value]]) {
      const node=el(id);
      if(node) node.textContent=value||node.dataset.default;
    }
  }
  function previewAllocation(node,source) {
    const id=node?.dataset.holding||node?.dataset.allocationRow||null;
    if(id&&!el(`allocation-${id}`)) return;
    if(source==='focus') allocationFocus=id;else allocationHover=id;
    updateAllocationDisplay();
  }
  function selectInstitution(patch,focusId) {
    if(!route?.institutionId) throw new Error('Institution selection requires an institution overview');
    const previous=institutionState(),next={...previous,...patch};
    const changedAgent=next.agentId!==previous.agentId;
    if(Object.keys(patch).length===1&&Object.hasOwn(patch,'agentId')&&!changedAgent) return;
    if(changedAgent) {next.holdingId=null;next.historyDate=null;}
    if(next.period!==previous.period) next.historyDate=null;
    // Resolve all three scopes before any state or DOM changes.
    const html=view.main(route,null,'changes',null,next);
    const top=content.scrollTop,railTop=content.querySelector('.portfolio-thumbnail-list')?.scrollTop||0;
    if(investmentEvent&&(changedAgent||next.period!==previous.period||next.eventKind!==previous.eventKind||next.eventGranularity!==previous.eventGranularity)) closeInvestmentPopover({restoreFocus:false});
    institutionSelections.set(route.institutionId,next);
    allocationHover=null;allocationFocus=null;
    // Preserve slice nodes during a click: replacing them would break pointer and focus continuity.
    if(Object.keys(patch).length===1&&Object.hasOwn(patch,'holdingId')) {
      updateAllocationDisplay();
      if(focusId&&doc.activeElement!==el(focusId)) el(focusId)?.focus({preventScroll:true});
      return;
    }
    if(Object.keys(patch).every(key=>['eventKind','eventGranularity'].includes(key))) {
      refreshInvestmentTimeline(true);
      if(focusId) el(focusId)?.focus({preventScroll:true});
      return;
    }
    // Agent targets stay in the DOM across the first click, allowing a native
    // double-click on either an already selected or a different Agent.
    if(Object.keys(patch).length===1&&Object.hasOwn(patch,'agentId')) {
      const agents=getInstitution(route.institutionId).agents;
      const index=agents.findIndex(agent=>agent.managerId===next.agentId);
      el('institution-dashboard').dataset.selectedAgent=next.agentId;
      for(const target of content.querySelectorAll('[data-action="institution-agent"]')) {
        const selected=target.dataset.agent===next.agentId;
        target.classList.toggle('is-selected',selected);
        if(target.tagName==='BUTTON') target.setAttribute('aria-pressed',String(selected));
      }
      for(const agent of agents) {
        const selected=agent.managerId===next.agentId;
        el(`institution-curve-group-${agent.managerId}`)?.classList.toggle('is-selected',selected);
        el(`institution-curve-end-${agent.managerId}`)?.setAttribute('r',selected?'3.5':'2.5');
      }
      const stage=el('portfolio-stage');
      stage.innerHTML=view.institutionPortfolio(route,next);stage.dataset.agent=next.agentId;
      stage.style.setProperty?.('--agent-color',el(`institution-agent-${next.agentId}`).style.getPropertyValue('--agent-color'));
      const position=el('institution-position');
      position.textContent=`${String(index+1).padStart(2,'0')} / ${String(agents.length).padStart(2,'0')}`;
      position.setAttribute('aria-label',view.t(`第 ${index+1} 个，共 ${agents.length} 个 Agent`,`Agent ${index+1} of ${agents.length}`));
      if(next.historyOpen) el('institution-chart-body').innerHTML=view.institutionChartBody(route,next);
    } else {
      content.innerHTML=html;content.scrollTop=top;
    }
    refreshInvestmentTimeline(true);
    const rail=content.querySelector('.portfolio-thumbnail-list');
    if(rail) rail.scrollTop=railTop;
    if(changedAgent) {
      const agents=getInstitution(route.institutionId).agents;
      const direction=agents.findIndex(a=>a.managerId===next.agentId)>agents.findIndex(a=>a.managerId===previous.agentId)?'next':'previous';
      const stage=content.querySelector('.portfolio-stage');
      if(stage) stage.dataset.transition=direction;
      const thumb=el(`institution-slide-${next.agentId}`);
      if(rail&&thumb) {
        const r=rail.getBoundingClientRect(),b=thumb.getBoundingClientRect();
        if(b.bottom>r.bottom) rail.scrollTop+=b.bottom-r.bottom+4;
        else if(b.top<r.top) rail.scrollTop-=r.top-b.top+4;
      }
      announce(view.t('已切换至所选 Agent 的持仓','Selected Agent portfolio opened'));
    }
    if(focusId) el(focusId)?.focus({preventScroll:true});
  }
  function setAllocationHistory(open,invoker) {
    const previous=institutionState();
    if(!previous) throw new Error('Holdings history requires an institution overview');
    const next={...previous,historyOpen:open,historyDate:null,historyReturnScroll:open&&!previous.historyOpen?content.scrollTop:previous.historyReturnScroll};
    const html=view.institutionChartBody(route,next);
    closeInvestmentPopover({restoreFocus:false});
    institutionSelections.set(route.institutionId,next);
    el('institution-chart-body').innerHTML=html;
    el('institution-dashboard').dataset.historyOpen=String(open);
    el('institution-chart-title').textContent=open?view.t('持仓时间轴','Allocation timeline'):view.t('投资表现','Investment performance');
    el('institution-chart-subtitle').textContent=open?view.t('逐次记录的公司占比与变化','Company weights at each recorded date'):view.t('同一区间，从 0% 开始比较','Same period, compared from 0%');
    el('allocation-history-open').setAttribute('aria-expanded',String(open));
    content.scrollTop=open?0:(previous.historyReturnScroll||0);
    if(!open) refreshInvestmentTimeline(true);
    (open?el('allocation-history-back'):el(invoker||`institution-agent-${next.agentId}`))?.focus({preventScroll:true});
    announce(open?view.t('已展开所选 Agent 的模拟持仓变化','Illustrative allocation history opened'):view.t('已返回投资表现','Returned to investment performance'));
  }
  function selectHistorySnapshot(target,{focus=false}={}) {
    const previous=institutionState(),date=target?.dataset.date;
    if(!previous?.historyOpen||!date) return;
    if(previous.historyDate===date) {if(focus) target.focus({preventScroll:true});return;}
    const period=getInstitution(route.institutionId).periods.find(item=>item.id===previous.period);
    const html=view.allocationHistory.snapshot({institutionId:route.institutionId,managerId:previous.agentId,period,paletteId:allocationPalette},date);
    institutionSelections.set(route.institutionId,{...previous,historyDate:date});
    el('allocation-history-detail').innerHTML=html;
    el('allocation-history').dataset.selectedDate=date;
    for(const item of content.querySelectorAll('[data-action="allocation-history-snapshot"]')) {
      if(item.tagName==='BUTTON') item.setAttribute('aria-pressed',String(item.dataset.date===date));
      if(item.dataset.date===date&&item.dataset.x!==undefined) {
        el('allocation-history-guide')?.setAttribute('x1',item.dataset.x);
        el('allocation-history-guide')?.setAttribute('x2',item.dataset.x);
      }
    }
    if(focus) target.focus({preventScroll:true});
  }
  const overviewTab = target => {
    const button=target?.closest?.('button[data-action="overview-section"]');
    return button?.dataset.action==='overview-section'?button:null;
  };
  function cancelOverviewHover() {
    if(overviewTimer!==null) clearTimeout(overviewTimer);
    overviewTimer=null;
  }
  function selectOverview(section,{source='click',focus=false}={}) {
    cancelOverviewHover();
    const previous=overviewSection();
    if(!previous||!OVERVIEW_SECTIONS.includes(section)) return;
    const previousPanel=el(`overview-panel-${previous}`);
    // A mouse passing over the tags must not hide a keyboard user's reading target.
    if(source==='hover'&&keyboardInput&&(previousPanel?.contains(doc.activeElement)||panelElement.contains(doc.activeElement))) return;
    const focusWouldHide=previous!==section&&previousPanel?.contains(doc.activeElement);
    overviewSelections.set(route.companyId,section);
    for(const key of OVERVIEW_SECTIONS) {
      const selected=key===section,tab=el(`overview-tab-${key}`),body=el(`overview-panel-${key}`);
      tab?.setAttribute('aria-selected',String(selected));
      tab?.setAttribute('tabindex',selected?'0':'-1');
      tab?.classList.toggle('is-active',selected);
      if(body) {body.hidden=!selected;body.inert=!selected;body.setAttribute('aria-hidden',String(!selected));}
    }
    const position=el('overview-position');
    if(position) position.textContent=`${String(OVERVIEW_SECTIONS.indexOf(section)+1).padStart(2,'0')} / 04`;
    if(focus||focusWouldHide) el(`overview-tab-${section}`)?.focus({preventScroll:true});
  }
  function queueOverviewHover(button) {
    cancelOverviewHover();
    if(!overviewSection()||button.dataset.section===overviewSection()) return;
    const companyId=route.companyId,section=button.dataset.section;
    overviewTimer=setTimeout(()=>{
      overviewTimer=null;
      if(route?.companyId===companyId&&button.isConnected) selectOverview(section,{source:'hover'});
    },140);
  }
  function selectItem(selection) {
    // Resolve the requested company and item before replacing either content or state.
    const html=view.detail(route,selection);
    const previous=itemSelection();
    if(previous?.kind===selection.kind&&previous.id===selection.id) return;
    closePanel();
    itemSelections.set(directoryKey(),{...selection});
    el('workspace-detail').innerHTML=html;
    for(const button of content.querySelectorAll('button[data-action="item-select"]')) {
      const selected=button.dataset.kind===selection.kind&&button.dataset.id===selection.id;
      button.setAttribute('aria-current',String(selected));
      button.classList.toggle('is-active',selected);
    }
    content.scrollTop=0;
    el('detail-title')?.focus({preventScroll:true});
    announce(view.t('已打开所选内容','Selected item opened'));
  }
  function savePosition() {
    if(!route) return;
    const active=doc.activeElement;
    const eventAnchor=investmentEvent&&investmentPopover.contains(active)?`investment-group-${selectedInvestmentGroups(investmentEventOptions())[0]}`:null;
    positions.set(formatRoute(route),{top:content.scrollTop,focus:eventAnchor||(content.contains(active)?active.id:'')});
    if(el('item-directory')) directoryPositions.set(directoryKey(),el('item-directory').scrollTop);
  }
  function restorePosition() {
    const saved=positions.get(formatRoute(route));
    win.requestAnimationFrame(()=>{
      if(el('item-directory')) el('item-directory').scrollTop=directoryPositions.get(directoryKey())||0;
      if(saved) {
        content.scrollTop=saved.top;
        const focus=saved.focus && el(saved.focus);
        (focus || content).focus({preventScroll:true});
      } else if(route.sectionId) {
        scrollSection(route.sectionId);
      } else {
        content.scrollTop=0;
        content.focus({preventScroll:true});
      }
    });
  }
  function setDisplay() {
    doc.documentElement.dataset.theme=theme;
    doc.documentElement.lang=language==='en'?'en':'zh-CN';
    view=createRenderer(language,registry);
  }
  function renderToolbar() { if(route) el('toolbar').innerHTML=view.toolbar(route,theme,panel); }
  function renderSidebar() {
    globalNav.innerHTML=view.globalNavigation(route,navigationExpanded);
    el('workspace').dataset.mode=mode(route);
    sidebar.hidden=mode(route)==='institution';
    sidebar.innerHTML=view.sidebar(route,query);
  }
  function syncNavigation() {
    el('workspace').dataset.navigation=navigationExpanded?'expanded':'collapsed';
    const toggle=el('nav-toggle');
    if(toggle) {
      toggle.setAttribute('aria-expanded',String(navigationExpanded));
      const label=navigationExpanded?view.t('收起工作台导航','Collapse workspace navigation'):view.t('展开工作台导航','Expand workspace navigation');
      toggle.setAttribute('aria-label',label);toggle.setAttribute('title',label);
      const visibleLabel=el('nav-toggle-label');
      if(visibleLabel) visibleLabel.textContent=navigationExpanded?view.t('收起导航','Collapse navigation'):view.t('展开导航','Expand navigation');
    }
  }
  function finishNavigationLayout() {
    retainAnchor(navigationAnchor);navigationAnchor=null;
    if(navigationEnd!==null) clearTimeout(navigationEnd);
    navigationEnd=null;
    positionFlyout();
  }
  function setNavigation(expanded) {
    if(navigationExpanded===expanded) return;
    navigationAnchor=anchorPosition();
    navigationExpanded=expanded;syncNavigation();
    retainAnchor(navigationAnchor);
    if(navigationEnd!==null) clearTimeout(navigationEnd);
    navigationEnd=setTimeout(finishNavigationLayout,280);
  }
  function hideFlyout() {
    if(flyoutKey) {
      el(`menu-${flyoutKey}`)?.setAttribute('aria-expanded','false');
      el(`row-${flyoutKey}`)?.classList.remove('menu-open');
    }
    flyoutKey=null;flyout.hidden=true;flyout.innerHTML='';
  }
  function showFlyout(key) {
    const row=el(`row-${key}`);
    if(!route||!row) return;
    const markup=view.entityMenu(key,route);
    hideFlyout();flyoutKey=key;
    flyout.innerHTML=markup;flyout.hidden=false;
    el(`menu-${key}`).setAttribute('aria-expanded','true');row.classList.add('menu-open');
    positionFlyout();
  }
  function positionFlyout() {
    if(!flyoutKey||flyout.hidden) return;
    const row=el(`row-${flyoutKey}`);
    if(!row) return;
    const bounds=sidebar.getBoundingClientRect(),rowBounds=row.getBoundingClientRect();
    const width=flyout.getBoundingClientRect().width,height=flyout.getBoundingClientRect().height;
    flyout.style.left=`${Math.max(8,Math.min(bounds.right+8,win.innerWidth-width-12))}px`;
    flyout.style.top=`${Math.max(8,Math.min(rowBounds.top,win.innerHeight-height-12))}px`;
  }
  const hover=createHoverMenu({show:showFlyout,hide:hideFlyout});
  const navigationHover=createHoverMenu({show:()=>setNavigation(true),hide:()=>setNavigation(false),openDelay:80,closeDelay:180});
  function renderFrame() {
    navigationAnchor=null;hover.close();cancelOverviewHover();
    allocationHover=null;allocationFocus=null;
    setDisplay();
    renderSidebar();
    renderToolbar();
    syncNavigation();
    el('company-header').innerHTML=view.header(route);
    el('content-nav').innerHTML=view.contentNavigation(route);
    content.dataset.entity=mode(route);content.dataset.view=route.view;
    content.innerHTML=view.main(route,route.view==='report'?returns.get(reportKey(route)):null,overviewSection()||'changes',itemSelection(),institutionState(),managerState());
    panelElement.hidden=!panel;
    el('workspace').classList.toggle('panel-open',!!panel);
    panelElement.innerHTML=panel?view.panel(route,panel):'';
    refreshInvestmentTimeline(true);
    renderInvestmentPopover({focus:false});
    doc.title=`${route.view==='report'?getReport(route.companyId,route.reportId,route.version).document.title:routeContext(route).entity.name} · Uteki`;
    restorePosition();
  }
  function showRouteError(error) {
    hover.close();cancelOverviewHover();
    closeInvestmentPopover({restoreFocus:false});
    route=null; panel=null; lastHash=win.location.hash;
    navigationHover.close();navigationAnchor=null;
    setDisplay();
    panelElement.hidden=true;
    el('workspace').classList.remove('panel-open');
    for(const id of ['global-nav','sidebar','company-header','content-nav','toolbar']) el(id).innerHTML='';
    content.innerHTML=`<div class="error-page"><h2>${view.t('页面范围无法确认','Page scope is invalid')}</h2><p>${view.t('链接中的公司、报告或版本无效，未打开其他内容。','The company, report or version in this link is invalid. No substitute content was opened.')}</p><p>${escapeHTML(error.message)}</p><a class="plain-button" href="${formatRoute(DEMO_LAUNCH)}">${view.t('打开 Alphabet 演示入口','Open the Alphabet sample')}</a></div>`;
    content.focus({preventScroll:true});
  }
  function load(hash) {
    try {
      closeInvestmentPopover({restoreFocus:false});
      route=parseRoute(hash);lastHash=hash;panel=null;invokerId='';
      entityRoutes.set(entityKey(route),{...route});
      modeRoutes.set(mode(route),{...route});
      query=queries.get(mode(route));
      renderFrame();announce(view.t('页面已打开','Page opened'));
    } catch(error) { showRouteError(error); }
  }
  function navigate(target) {
    const hash=formatRoute(target);
    hover.close();
    if(hash===lastHash) return;
    savePosition();
    if(target.view==='report'&&route&&route.view!=='report') returns.set(reportKey(target),{...route});
    win.history.pushState(null,'',hash);
    load(hash);
  }
  function scrollSection(sectionId) {
    if(route.view!=='report') return;
    const context=getReport(route.companyId,route.reportId,route.version);
    if(!context.report.sections.some(s=>s.id===sectionId)) throw new Error('Unknown report section');
    const section=el(`section-${sectionId}`);
    content.scrollTop+=section.getBoundingClientRect().top-content.getBoundingClientRect().top-20;
    section.focus({preventScroll:true});
  }
  // Keep a visible text anchor at the same vertical position when the panel changes width.
  function anchorPosition(preferredId) {
    const preferred=preferredId&&el(preferredId);
    const rect=content.getBoundingClientRect();
    const visible=item=>{const r=item.getBoundingClientRect();return r.bottom>rect.top&&r.top<rect.bottom;};
    const selector=route?.institutionId?'.institution-section-heading,.portfolio-stage-heading,.institution-holding-row':route?.view==='report'?'.report-section p,.report-section li,.citation':route?.managerId?'.manager-table tbody tr,.manager-coverage-card,.manager-allocation-band':'.overview-module:not([hidden]),#workspace-detail p,.material-row,.tracking-item';
    const anchor=preferred&&content.contains(preferred)&&visible(preferred)?preferred:
      [...content.querySelectorAll(selector)].find(visible);
    return anchor?{element:anchor,y:anchor.getBoundingClientRect().top}:null;
  }
  function retainAnchor(anchor) {
    if(anchor?.element.isConnected) content.scrollTop+=anchor.element.getBoundingClientRect().top-anchor.y;
  }
  function openPanel(selection,fromId='') {
    // Resolve all scope before changing any visible state.
    const html=view.panel(route,selection);
    closeInvestmentPopover({restoreFocus:false});
    cancelOverviewHover();
    const anchor=anchorPosition(fromId);
    if(!panel) invokerId=fromId || doc.activeElement?.id || '';
    panel=selection;
    panelElement.innerHTML=html;panelElement.hidden=false;panelElement.scrollTop=0;
    el('workspace').classList.add('panel-open');renderToolbar();retainAnchor(anchor);
    refreshInvestmentTimeline(true);
    el('panel-title').focus({preventScroll:true});
    announce(view.t('已展开研究上下文','Research context opened'));
  }
  function closePanel() {
    if(!panel) return;
    const anchor=anchorPosition(invokerId);
    panel=null;panelElement.hidden=true;panelElement.innerHTML='';
    el('workspace').classList.remove('panel-open');renderToolbar();retainAnchor(anchor);
    refreshInvestmentTimeline(true);
    const returnTarget=el(invokerId),returnSection=returnTarget?.closest('[data-overview-section]');
    if(returnSection?.hidden) selectOverview(returnSection.dataset.overviewSection);
    (returnTarget||content).focus({preventScroll:true});
    invokerId='';
    announce(view.t('已返回阅读位置','Returned to reading'));
  }
  function perform(button,event={}) {
    const action=button.dataset.action;
    if(action==='mode') {
      navigate(modeRoutes.get(button.dataset.mode));
      win.requestAnimationFrame(()=>el(`mode-${button.dataset.mode}`).focus({preventScroll:true}));
    }
    else if(action==='entity-menu') {
      const key=button.dataset.key;
      if(flyoutKey===key&&event.detail!==0) hover.close();
      else {
        hover.open(key);
        if(event.detail===0) flyout.querySelector('a')?.focus({preventScroll:true});
      }
    }
    else if(action==='toggle-navigation') {
      if(navigationExpanded) {navigationKeyboardFocus=false;keyboardInput=false;navigationHover.close();}
      else navigationHover.open('navigation');
    }
    else if(action==='overview-section') selectOverview(button.dataset.section);
    else if(action==='overview-step') {
      const current=overviewSection(),step=Number(button.dataset.step);
      if(current&&(step===-1||step===1)) selectOverview(OVERVIEW_SECTIONS[(OVERVIEW_SECTIONS.indexOf(current)+step+4)%4]);
    }
    else if(action==='item-select') selectItem({kind:button.dataset.kind,id:button.dataset.id});
    else if(action==='manager-filter'||action==='manager-page') selectManagerList(button);
    else if(action==='manager-company-reports') openManagerCompanyReports(button.dataset.company);
    else if(action==='institution-period') selectInstitution({period:button.dataset.period},button.id);
    else if(action==='allocation-palette') selectAllocationPalette(button.dataset.palette);
    else if(action==='investment-event-kind') selectInstitution({eventKind:button.dataset.kind},button.id);
    else if(action==='investment-event-group') {
      const groupId=button.dataset.group;
      if(selectedInvestmentGroups(investmentEventOptions()).includes(groupId)) closeInvestmentPopover();
      else openInvestmentPopover(groupId,button.id);
    }
    else if(action==='investment-popover-close') closeInvestmentPopover();
    else if(action==='investment-popover-step') stepInvestmentPopover(Number(button.dataset.step),button.id);
    else if(action==='allocation-history-open') setAllocationHistory(!institutionState()?.historyOpen,button.id);
    else if(action==='allocation-history-close') setAllocationHistory(false);
    else if(action==='allocation-history-snapshot') selectHistorySnapshot(button);
    else if(action==='institution-agent') selectInstitution({agentId:button.dataset.agent},button.id?.startsWith('institution-slide-')?button.id:`institution-agent-${button.dataset.agent}`);
    else if(action==='institution-step') {
      if(!route?.institutionId) throw new Error('Agent selection requires an institution overview');
      const step=Number(button.dataset.step);
      if(step!==-1&&step!==1) throw new Error('Unknown portfolio step');
      const agents=getInstitution(route.institutionId).agents;
      const index=agents.findIndex(a=>a.managerId===institutionState().agentId);
      selectInstitution({agentId:agents[(index+step+agents.length)%agents.length].managerId},button.id);
    }
    else if(action==='institution-holding') selectInstitution({holdingId:institutionState()?.holdingId===button.dataset.holding?null:button.dataset.holding},button.id);
    else if(action==='institution-section') {
      if(!route?.institutionId||!['performance','portfolio','agents'].includes(button.dataset.section)) throw new Error('Unknown institution section');
      const section=el(`institution-${button.dataset.section}`);
      content.scrollTop+=section.getBoundingClientRect().top-content.getBoundingClientRect().top-18;
      section.focus({preventScroll:true});
    }
    else if(action==='close-panel') closePanel();
    else if(action==='panel-back') openPanel(panel.parent,invokerId);
    else if(action==='design'||action==='context') panel?.kind===action?closePanel():openPanel({kind:action},button.id);
    else if(action==='changes') openPanel({kind:'changes'},button.id);
    else if(action==='event') openPanel({kind:'event',eventId:button.dataset.event,...(panel?.kind==='changes'?{parent:panel}:{})},panel?.kind==='changes'?invokerId:button.id);
    else if(action==='evidence') openPanel({kind:'evidence',evidenceId:button.dataset.evidence,origin:button.dataset.origin,...(panel?.kind==='event'?{parent:panel}:{})},button.id);
    else if(action==='section') {
      const sectionId=button.dataset.section;
      closePanel();scrollSection(sectionId);
    } else if(action==='top') {content.scrollTop=0;el('report-title')?.focus({preventScroll:true});}
    else if(action==='language') {savePosition();language=language==='zh'?'en':'zh';saveDisplay();renderFrame();win.requestAnimationFrame(()=>el('language-button').focus({preventScroll:true}));}
    else if(action==='theme') {theme=theme==='light'?'dark':'light';saveDisplay();setDisplay();renderToolbar();el('theme-button').focus({preventScroll:true});}
  }
  function start() {
    if(!win.location.hash) win.history.replaceState(null,'',formatRoute(HOME_DEMO_LAUNCH));
    load(win.location.hash);
    doc.addEventListener('click',event=>{
      const button=event.target.closest('button[data-action]')||event.target.closest('[data-action="institution-agent"]')||event.target.closest('[data-action="institution-holding"]')||event.target.closest('[data-action="allocation-history-snapshot"]');
      if(investmentEvent&&!investmentPopover.contains(event.target)&&!button?.dataset.action?.startsWith('investment-popover-')&&button?.dataset.action!=='investment-event-group') closeInvestmentPopover({restoreFocus:false});
      if(event.target.closest('.skip-link')) {
        event.preventDefault();hover.close();
        content.focus({preventScroll:true});return;
      }
      const link=event.target.closest('a[href^="#/company/"],a[href^="#/manager/"],a[href^="#/institution/"]');
      if(link&&!event.metaKey&&!event.ctrlKey&&!event.shiftKey&&!event.altKey&&event.button===0) {
        event.preventDefault();
        try {navigate(link.dataset.entityKey&&entityRoutes.has(link.dataset.entityKey)?entityRoutes.get(link.dataset.entityKey):parseRoute(link.getAttribute('href')));} catch(error) {announce(error.message);}
        return;
      }
      if(button) {try {perform(button,event);} catch(error) {announce(error.message);}}
    });
    doc.addEventListener('dblclick',event=>{
      const target=event.target.closest('[data-action="institution-agent"]');
      if(!target||!route?.institutionId) return;
      event.preventDefault();
      try {
        selectInstitution({agentId:target.dataset.agent},target.id);
        setAllocationHistory(true,target.id);
      } catch(error) {announce(error.message);}
    });
    doc.addEventListener('input',event=>{
      if(event.target.id==='entity-search') {hover.close();query=event.target.value;queries.set(mode(route),query);el('entity-list').innerHTML=view.entityRows(route,query);}
    });
    doc.addEventListener('change',event=>{
      if(event.target.id==='report-version') navigate({...(route.managerId?{managerId:route.managerId}:{}),companyId:route.companyId,view:'report',reportId:route.reportId,version:event.target.value});
      if(event.target.id==='investment-event-granularity') {
        try { selectInstitution({eventGranularity:event.target.value},event.target.id); }
        catch(error) {event.target.value=institutionState()?.eventGranularity;announce(error.message);}
      }
    });
    doc.addEventListener('keydown',event=>{
      if(event.key==='Tab') keyboardInput=true;
      const snapshot=(event.target||doc.activeElement)?.closest?.('button[data-action="allocation-history-snapshot"]');
      if(snapshot&&institutionState()?.historyOpen&&['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        event.preventDefault();keyboardInput=true;
        const dates=[...content.querySelectorAll('button[data-action="allocation-history-snapshot"]')];
        const index=dates.indexOf(snapshot);
        const next=event.key==='Home'?0:event.key==='End'?dates.length-1:Math.max(0,Math.min(dates.length-1,index+(event.key==='ArrowLeft'?-1:1)));
        selectHistorySnapshot(dates[next],{focus:true});
        dates[next]?.scrollIntoView?.({block:'nearest',inline:'nearest'});
        return;
      }
      const slice=(event.target||doc.activeElement)?.closest?.('.allocation-segment');
      if(slice&&['Enter',' ','Spacebar'].includes(event.key)) {
        event.preventDefault();keyboardInput=true;
        if(!event.repeat) {try {perform(slice,event);} catch(error) {announce(error.message);}}
        return;
      }
      const slide=(event.target||doc.activeElement)?.closest?.('.portfolio-thumbnail');
      if(slide&&route?.institutionId&&['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
        event.preventDefault();keyboardInput=true;
        const agents=getInstitution(route.institutionId).agents;
        const index=agents.findIndex(a=>a.managerId===slide.dataset.agent);
        const next=event.key==='Home'?0:event.key==='End'?agents.length-1:(index+(event.key==='ArrowUp'?-1:1)+agents.length)%agents.length;
        const agentId=agents[next].managerId;
        selectInstitution({agentId},`institution-slide-${agentId}`);
        return;
      }
      const tab=overviewTab(event.target||doc.activeElement);
      if(tab&&['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {
        keyboardInput=true;
        event.preventDefault();
        const index=OVERVIEW_SECTIONS.indexOf(tab.dataset.section);
        const next=event.key==='Home'?0:event.key==='End'?3:(index+(['ArrowUp','ArrowLeft'].includes(event.key)?-1:1)+4)%4;
        selectOverview(OVERVIEW_SECTIONS[next],{source:'keyboard',focus:true});
        return;
      }
      if(event.key==='Escape') {
        cancelOverviewHover();
        if(investmentEvent) {event.preventDefault();closeInvestmentPopover();}
        else if(flyoutKey||hover.getState().pendingKey) {event.preventDefault();const key=flyoutKey;hover.close();if(key) el(`menu-${key}`)?.focus({preventScroll:true});}
        else if(navigationExpanded||navigationHover.getState().pendingKey) {
          event.preventDefault();navigationKeyboardFocus=false;keyboardInput=false;navigationHover.close();
          if(globalNav.contains(doc.activeElement)) el('nav-toggle')?.focus({preventScroll:true});
        }
        else if(panel) {event.preventDefault();closePanel();}
        else if(institutionState()?.historyOpen) {event.preventDefault();setAllocationHistory(false);}
      }
    });
    doc.addEventListener('pointerdown',event=>{
      keyboardInput=false;navigationKeyboardFocus=false;
      if(globalNav.contains(event.target)) {
        navigationPointerInside=event.pointerType!=='touch';navigationHover.enter('navigation');
      } else {navigationHover.leaveMenu();navigationHover.leave('navigation');}
    });
    doc.addEventListener('pointerover',event=>{
      if(event.pointerType==='touch') return;
      const allocation=allocationTarget(event.target);
      if(allocation&&!allocation.contains(event.relatedTarget)) previewAllocation(allocation,'hover');
      const tab=overviewTab(event.target);
      if(tab&&!tab.contains(event.relatedTarget)) {queueOverviewHover(tab);return;}
      if(globalNav.contains(event.target)) {
        if(!globalNav.contains(event.relatedTarget)) {navigationPointerInside=true;navigationHover.enter('navigation');}
        return;
      }
      if(flyout.contains(event.target)) {hover.enterMenu();return;}
      if(flyout.contains(doc.activeElement)) return;
      const row=event.target.closest('.entity-row');
      if(row&&!row.contains(event.relatedTarget)) hover.enter(row.dataset.key);
    });
    doc.addEventListener('pointerout',event=>{
      if(event.pointerType==='touch') return;
      const allocation=allocationTarget(event.target);
      if(allocation&&!allocation.contains(event.relatedTarget)) previewAllocation(allocationTarget(event.relatedTarget),'hover');
      const tab=overviewTab(event.target);
      if(tab&&!tab.contains(event.relatedTarget)) {cancelOverviewHover();return;}
      if(globalNav.contains(event.target)) {
        if(!globalNav.contains(event.relatedTarget)) {navigationPointerInside=false;if(!navigationKeyboardFocus) navigationHover.leave('navigation');}
        return;
      }
      if(flyout.contains(event.target)&&!flyout.contains(event.relatedTarget)) {
        if(!flyout.contains(doc.activeElement)) hover.leaveMenu();
        return;
      }
      const row=event.target.closest('.entity-row');
      if(row&&!row.contains(event.relatedTarget)) {
        if(flyout.contains(event.relatedTarget)) hover.enterMenu();
        else if(!flyout.contains(doc.activeElement)) hover.leave(row.dataset.key);
      }
    });
    doc.addEventListener('focusin',event=>{
      const allocation=event.target.closest?.('[data-action="institution-holding"]');
      if(allocation&&keyboardInput) previewAllocation(allocation,'focus');
      if(el(`overview-panel-${overviewSection()}`)?.contains(event.target)||panelElement.contains(event.target)) cancelOverviewHover();
      if(globalNav.contains(event.target)&&keyboardInput) {
        navigationKeyboardFocus=true;navigationHover.open('navigation');navigationHover.enterMenu();
      }
      if(flyout.contains(event.target)) hover.enterMenu();
    });
    doc.addEventListener('focusout',event=>{
      if(event.target.closest?.('[data-action="institution-holding"]')) previewAllocation(null,'focus');
      if(globalNav.contains(event.target)&&!globalNav.contains(event.relatedTarget)) {
        navigationKeyboardFocus=false;
        if(navigationPointerInside) navigationHover.enter('navigation');
        else {navigationHover.leaveMenu();navigationHover.leave('navigation');}
      }
      if(flyout.contains(event.target)&&!flyout.contains(event.relatedTarget)) hover.leaveMenu();
    });
    doc.addEventListener('scroll',event=>{
      if(event.target===el('entity-list')) hover.close();
      if(event.target===content) positionInvestmentPopover();
    },true);
    // Follow the continuously changing grid width without rebuilding the reader.
    if(win.ResizeObserver) {
      const observer=new win.ResizeObserver(()=>{retainAnchor(navigationAnchor);positionFlyout();refreshInvestmentTimeline();});
      observer.observe(content);
    }
    doc.addEventListener('transitionend',event=>{
      if(event.target===el('workspace')&&event.propertyName==='grid-template-columns') finishNavigationLayout();
    });
    win.addEventListener('resize',()=>{hover.close();refreshInvestmentTimeline();});
    win.addEventListener('pagehide',()=>{closeInvestmentPopover({restoreFocus:false});cancelOverviewHover();hover.close();navigationHover.close();finishNavigationLayout();});
    win.addEventListener('hashchange',()=>{
      if(win.location.hash!==lastHash) {savePosition();load(win.location.hash);}
    });
  }
  return {start,navigate,openPanel,closePanel,getState:()=>({route,panel,investmentEvent,language,theme,query,navigationExpanded,flyoutKey,overviewSection:overviewSection(),itemSelection:itemSelection(),institutionPeriod:institutionState()?.period||null,institutionAgent:institutionState()?.agentId||null,institutionHolding:institutionState()?.holdingId||null,allocationPalette,managerSelection:managerState(),allocationHistoryOpen:!!institutionState()?.historyOpen,allocationHistoryDate:institutionState()?.historyDate||null,eventKind:institutionState()?.eventKind||null,eventGranularity:institutionState()?.eventGranularity||null})};
}

if(typeof window!=='undefined'&&typeof document!=='undefined') {
  let registry={brands:{}};
  try {
    const response=await fetch(new URL('../../../apps/uteki_zero/assets/companies/registry.json',import.meta.url));
    if(!response.ok) throw new Error(`Icon registry: ${response.status}`);
    registry=validateBrandRegistry(await response.json());
  } catch(error) { console.warn('Local company icons unavailable:',error.message); }
  createController({document,window,registry}).start();
}
