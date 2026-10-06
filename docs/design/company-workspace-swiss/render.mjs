import { catalog, getCompany, getManager, getReport, getEvidence, getMaterial, getInstitution, formatRoute, routeContext } from './model.mjs';
import { resolveBrand } from '../../../apps/uteki_zero/brands.mjs';
import { createManagerViews } from './manager-view.mjs?v=20261004-investment-timeline2';
import { createInstitutionViews } from './institution-view.mjs?v=20261004-investment-timeline2';
import { INSTITUTION_DEMO_SCOPE } from './institution-data.mjs';
import { investmentEventFixture } from './investment-events.mjs';
import { managerCoverageFixture, getManagerCoverage } from './manager-coverage.mjs';

export const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const e = escapeHTML;
const base = new URL('../../../apps/uteki_zero/', import.meta.url);
const paths = {
  home:'<path d="m3 10 9-7 9 7v11H3zM9 21v-8h6v8"/>',
  search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  chevron:'<path d="m9 6 6 6-6 6"/>',
  file:'<path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h6"/>',
  company:'<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M9 4v16M9 10h11"/>',
  manager:'<circle cx="12" cy="8" r="3"/><path d="M5 21v-3a7 7 0 0 1 14 0v3"/>',
  panel:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  moon:'<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>',
  link:'<path d="m10 13 4-4m-5 7-2 2a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0m2 0 2-2a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0"/>',
};
export const icon = name => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.file}</svg>`;

export function createRenderer(lang = 'zh', registry = {brands:{}}) {
  const t = (zh,en) => lang === 'en' ? en : zh;
  const routeLink = (route,label,cls='',id='') => `<a href="${e(formatRoute(route))}" class="${cls}" ${id ? `id="${e(id)}"` : ''}>${label}</a>`;
  const status = value => `<span class="status ${e(value)}">${({current:t('当前版本','Current'),review:t('结论待复核','Needs review'),historical:t('历史版本','Historical')})[value] || e(value)}</span>`;
  const available = value => ({available:t('演示正文可读','Demo text available'),excerpt:t('仅有摘录','Excerpt only'),unavailable:t('资料不可用','Unavailable')})[value] || e(value);
  const kind = value => value === 'main' ? t('主报告','Main report') : t('专题','Topic');
  const signal = value => `<span class="signal ${e(value)}">${({risk:t('假设受挑战','Challenged'),watch:t('仍待验证','Open question'),support:t('补充支持','New support')})[value] || e(value)}</span>`;
  const materialButton = (item,origin='material',cls='panel-source',id='') => `<button ${id?`id="${e(id)}"`:''} class="${cls}" data-action="evidence" data-evidence="${e(item.id)}" data-origin="${origin}">${e(item.sourceTitle)} · ${available(item.availability)}</button>`;
  const companyIcon = company => {
    const brand = resolveBrand(company,registry);
    return brand ? `<img class="company-icon" src="${e(new URL(brand.src,base).href)}" alt="" width="32" height="32">` : `<span class="company-icon icon-missing" aria-label="${t('图标未收录','Icon unavailable')}">—</span>`;
  };
  const managerViews=createManagerViews({t,companyIcon,institutionContext:getInstitution(INSTITUTION_DEMO_SCOPE.institutionId),executionContext:investmentEventFixture,coverageContext:managerCoverageFixture});
  const institutionViews=createInstitutionViews({t,companyIcon});
  const entityKey=route=>route.institutionId?`institution-${route.institutionId}`:route.managerId?`manager-${route.managerId}`:`company-${route.companyId}`;
  const leafRoute=(route,view)=>route.institutionId?{institutionId:route.institutionId,view}:route.managerId?{managerId:route.managerId,view}:{companyId:route.companyId,view};
  function sections(route) {
    if(route.institutionId) return [['overview',t('投资总览','Investment overview'),null]];
    if(route.managerId) {
      const {reports}=getManager(route.managerId);
      const coverage=getManagerCoverage(route.managerId,managerCoverageFixture);
      return [['overview',t('概览','Overview'),null],['companies',t('研究覆盖','Coverage'),coverage.total],['reports',t('研究报告','Reports'),reports.length],['activity',t('操作历史','Activity history'),null]];
    }
    const {reports,evidence,events}=getCompany(route.companyId);
    return [['overview',t('概览','Overview'),null],['reports',t('研究报告','Reports'),reports.length],['materials',t('资料与数据','Materials & data'),evidence.length],['tracking',t('关注点','Open questions'),events.filter(ev=>ev.unresolved).length]];
  }
  function tabs(route,selected=true) {
    return sections(route).map(([view,label,count])=>{
      const active=selected&&(route.view===view||view==='reports'&&route.view==='report'||route.managerId&&view==='activity'&&route.view==='holdings');
      return `<a id="leaf-${entityKey(route)}-${view}" class="entity-child ${active?'active':''}" href="${e(formatRoute(leafRoute(route,view)))}" ${active?'aria-current="page"':''}><span>${label}</span>${count!==null?`<small>${count}</small>`:''}</a>`;
    }).join('');
  }
  function contentNavigation(route) {
    routeContext(route);
    return sections(route).map(([view,label,count])=>{
      const active=route.view===view||view==='reports'&&route.view==='report'||route.managerId&&view==='activity'&&route.view==='holdings';
      return `<a id="content-${entityKey(route)}-${view}" class="content-tab ${active?'active':''}" href="${e(formatRoute(leafRoute(route,view)))}" ${active?'aria-current="page"':''}><span>${label}</span>${count!==null?`<small>${count}</small>`:''}</a>`;
    }).join('');
  }
  function entityRows(route,query='') {
    const isManager=!!route.managerId;
    const items=(isManager?catalog.managers:catalog.companies).filter(item=>`${item.name} ${item.ticker || item.style}`.toLowerCase().includes(query.trim().toLowerCase()));
    return items.map(item=>{
      const target=isManager?{managerId:item.id,view:'overview'}:{companyId:item.id,view:'overview'};
      const key=entityKey(target),selected=entityKey(route)===key;
      const n=isManager?0:new Set(catalog.events.filter(event=>event.companyId===item.id).map(event=>event.id)).size;
      return `<div class="entity-group"><div id="row-${key}" data-key="${key}" class="entity-row ${selected?'selected':''}"><a id="${key}" class="company-row" data-entity-key="${key}" href="${e(formatRoute(target))}" title="${e(item.name)}">${isManager?`<span class="avatar entity-avatar">${e(item.name[0])}</span>`:companyIcon(item)}<span class="company-copy"><strong>${e(item.name)}</strong><small>${e(item.ticker || item.style)}</small></span>${n?`<span class="count" title="${t('演示事件数，非未读数','Demo event count, not unread')}">${n}</span>`:''}</a><button id="menu-${key}" class="entity-menu-button" data-action="entity-menu" data-key="${key}" aria-expanded="false" aria-controls="entity-flyout" aria-label="${e(item.name)} · ${t('打开内容目录','Open contents')}">${icon('chevron')}</button></div></div>`;
    }).join('') || `<p class="note">${t('没有匹配的对象','No matching entities')}</p>`;
  }
  function entityMenu(key,route) {
    const isManager=key.startsWith('manager-');
    const collection=isManager?catalog.managers:catalog.companies;
    const item=collection.find(item=>`${isManager?'manager':'company'}-${item.id}`===key);
    if(!item) throw new Error('Unknown entity menu');
    const target=isManager?{managerId:item.id,view:'overview'}:{companyId:item.id,view:'overview'};
    const selected=entityKey(route)===key;
    return `<div class="flyout-heading"><strong>${e(item.name)}</strong><span>${e(item.ticker || item.style)}</span></div><nav aria-label="${e(item.name)} · ${t('内容目录','Contents')}">${tabs(selected?route:target,selected)}</nav>`;
  }
  function globalNavigation(route,expanded=false) {
    const isManager=!!route.managerId,isInstitution=!!route.institutionId;
    return `<div class="nav-brand"><span class="nav-brand-symbol"><img src="${e(new URL('./assets/uteki-drop.png',import.meta.url).href)}" alt="Uteki" width="258" height="342"></span><span class="nav-label nav-brand-name" aria-hidden="true">uteki</span></div>
      <nav class="global-modes" aria-label="${t('工作台导航','Workspace navigation')}"><button id="mode-institution" class="nav-item ${isInstitution?'active':''}" data-action="mode" data-mode="institution" aria-pressed="${isInstitution}" aria-label="${t('机构总览','Institution overview')}" title="${t('机构总览','Institution overview')}"><span class="nav-glyph">${icon('home')}</span><span class="nav-label">${t('机构总览','Overview')}</span></button><button id="mode-company" class="nav-item ${!isManager&&!isInstitution?'active':''}" data-action="mode" data-mode="company" aria-pressed="${!isManager&&!isInstitution}" aria-label="${t('公司','Companies')}" title="${t('公司','Companies')}"><span class="nav-glyph">${icon('company')}</span><span class="nav-label">${t('公司','Companies')}</span></button><button id="mode-manager" class="nav-item ${isManager?'active':''}" data-action="mode" data-mode="manager" aria-pressed="${isManager}" aria-label="Managers" title="Managers"><span class="nav-glyph">${icon('manager')}</span><span class="nav-label">Managers</span></button></nav>
      <div class="global-nav-footer"><a class="nav-item" href="../page-blueprint/#map" aria-label="${t('页面与交互标注稿','Page & interaction blueprint')}" title="${t('页面与交互标注稿','Page & interaction blueprint')}"><span class="nav-glyph">${icon('file')}</span><span class="nav-label">${t('页面设计稿','Page blueprint')}</span></a><button id="nav-toggle" class="nav-item navigation-toggle" data-action="toggle-navigation" aria-expanded="${expanded}" aria-controls="global-nav" aria-label="${expanded?t('收起导航','Collapse navigation'):t('展开导航','Expand navigation')}" title="${expanded?t('收起导航','Collapse navigation'):t('展开导航','Expand navigation')}"><span class="nav-glyph">${icon('panel')}</span><span id="nav-toggle-label" class="nav-label">${expanded?t('收起导航','Collapse navigation'):t('展开导航','Expand navigation')}</span></button></div>`;
  }
  function sidebar(route,query='') {
    if(route.institutionId) return institutionViews.sidebar(route);
    const isManager=!!route.managerId;
    return `<div class="entity-list-heading"><h2>${isManager?t('投资 Managers','Investment Managers'):t('关注的公司','Following companies')}</h2><span>${isManager?catalog.managers.length:catalog.companies.length}</span></div>
      <label class="search">${icon('search')}<span class="sr-only">${t('搜索当前实体','Search entities')}</span><input id="entity-search" type="search" placeholder="${isManager?t('搜索 Manager','Search Managers'):t('搜索公司或代码','Company or ticker')}" value="${e(query)}" autocomplete="off"></label>
      <nav class="company-list" id="entity-list" aria-label="${t('对象列表与内容目录','Entities and contents')}">${entityRows(route,query)}</nav>
      <p class="entity-sidebar-footer">${t('设计样板 · 虚构资料','Design sample · Fictional data')}</p>`;
  }
  function toolbar(route,theme,panel) {
    const {entity}=routeContext(route);
    const label=route.view==='report'?t('研究报告','Reports'):route.managerId&&['activity','holdings'].includes(route.view)?t('操作历史','Activity history'):sections(route).find(s=>s[0]===route.view)[1];
    return `<div class="toolbar-start"><a class="study-version" href="${e('../company-workspace-v2/'+formatRoute(route))}" title="${t('查看原版同一页面','View the same page in the original study')}"><span class="study-version-mark" aria-hidden="true"></span><span>Swiss study A</span><span class="study-version-return">${t('原版','Original')} ↗</span></a><div class="breadcrumb">${route.institutionId?t('工作台','Workspace'):(route.managerId?'Managers':t('公司','Companies'))}${icon('chevron')}${route.institutionId?'':`<strong>${e(entity.name)}</strong>${icon('chevron')}`}<span class="current-location">${label}</span></div></div><div class="tools">
      <button id="design-button" class="utility" data-action="design" aria-pressed="${panel?.kind==='design'}">${t('设计说明','Design notes')}</button>
      <button id="language-button" class="utility" data-action="language" aria-label="${t('Switch to English','切换中文')}">${t('EN','中文')}</button>
      <button id="theme-button" class="utility" data-action="theme" aria-label="${theme==='dark'?t('切换亮色','Light theme'):t('切换暗色','Dark theme')}">${icon(theme==='dark'?'sun':'moon')}</button>
      <button id="context-button" class="utility" data-action="context" aria-label="${t('研究上下文','Research context')}" aria-pressed="${panel?.kind==='context'}">${icon('panel')}<span class="tool-label">${t('上下文','Context')}</span></button></div>`;
  }
  function header(route) {
    if(route.institutionId) return institutionViews.header(route);
    if(route.managerId) {
      const {manager,reports}=getManager(route.managerId);
      const coverage=getManagerCoverage(route.managerId,managerCoverageFixture);
      return `<span class="avatar entity-avatar hero-avatar">${e(manager.name[0])}</span><div class="company-heading"><h1>${e(manager.name)}</h1><p><span>${e(manager.style)}</span><span>${e(manager.horizon)}</span></p></div><div class="company-summary"><strong>${coverage.counts.current} ${t('家当前关注','companies currently followed')} · ${reports.length} ${t('份报告','reports')}</strong><span>${t('模拟组合 · 非实盘','Illustrative portfolio · Not a live account')}</span></div>`;
    }
    const {company,reports,coverage} = getCompany(route.companyId);
    return `${companyIcon(company)}<div class="company-heading"><h1>${e(company.name)}</h1><p><span>${e(company.ticker)}</span><span>${e(company.tagline)}</span></p></div><div class="company-summary"><strong>${coverage.length} Managers · ${reports.length} ${t('份报告','reports')}</strong><span>${t('当前为虚构研究样本','Fictional research sample')}</span></div>`;
  }
  function reportLinks(companyId,event) {
    return event.affectedReports.map(link => {
      const {document,manager,report}=getReport(companyId,link.reportId,link.version);
      const section=report.sections.find(s=>s.id===link.sectionId);
      return routeLink({companyId,view:'report',...link},`${e(manager.name)} · ${e(document.title)} · ${e(link.version)}<br>${e(section.title)}`,'related-link');
    }).join('');
  }
  function coverageList(context) {
    return `<div class="coverage-list">${context.coverage.map(c=>{const m=catalog.managers.find(i=>i.id===c.managerId);return `<div class="coverage-row"><span>${e(m.name)} · ${e(m.style)}</span><span>${c.status==='published'?t('已有报告','Reports available'):t('尚未发布报告','No published report')}</span></div>`;}).join('')}</div>`;
  }
  const empty = (title,description) => `<div class="empty"><h3>${title}</h3><p>${description}</p></div>`;
  function overview(context,selectedSection='changes') {
    const {company}=context;
    const events=[...new Map(context.events.map(event=>[event.id,event])).values()]
      .sort((a,b)=>b.date.localeCompare(a.date));
    const reports=[...new Map(context.reports.map(item=>[item.document.id,item])).values()]
      .sort((a,b)=>b.report.publishedAt.localeCompare(a.report.publishedAt));
    const evidence=[...new Map(context.evidence.map(item=>[item.id,item])).values()]
      .sort((a,b)=>b.publishedAt.localeCompare(a.publishedAt));
    const questions=events.filter(event=>event.unresolved);
    const authors=new Set(reports.map(item=>item.manager.id)).size;
    const reviewCount=reports.filter(item=>item.report.status==='review').length;
    const historicalReviewCount=reports.reduce((count,item)=>count+item.document.versions.filter(version=>version.version!==item.report.version&&version.status==='review').length,0);
    const questionReportCount=new Set(questions.flatMap(event=>event.affectedReports.map(link=>link.reportId))).size;
    const availability=Object.fromEntries(['available','excerpt','unavailable'].map(value=>[value,evidence.filter(item=>item.availability===value).length]));
    const dot=value=>`<span class="status-dot ${e(value)}" aria-hidden="true"></span>`;
    const sectionKeys=['changes','research','materials','tracking'];
    if(!sectionKeys.includes(selectedSection)) throw new Error('Unknown company overview section');
    const module=(name,label,count,countLabel,state,items,footer)=>{
      const key=name==='reports'?'research':name;
      return `<section id="overview-panel-${key}" class="overview-module" data-module="${name}" data-overview-section="${key}" role="tabpanel" aria-labelledby="overview-tab-${key}" tabindex="0" ${key===selectedSection?'':'hidden'}><div class="overview-module-heading"><h2>${label}</h2><span class="overview-count" data-count="${count}" aria-label="${e(countLabel)}">${count}</span></div><p class="overview-status">${state}</p><div class="overview-items">${items}</div><div class="overview-module-footer">${footer}</div></section>`;
    };
    const preview=(title,meta,state='neutral')=>`${dot(state)}<span class="overview-item-copy"><span class="overview-item-title" lang="zh-CN" title="${e(title)}">${e(title)}</span><span class="overview-item-meta">${meta}</span></span>${icon('chevron')}`;
    const eventState=value=>({risk:t('假设受挑战','Challenged'),watch:t('仍待验证','Unresolved'),support:t('补充支持','New support')})[value]||e(value);
    const noItems=text=>`<p class="overview-empty">${text}</p>`;
    const allLink=(view,label)=>routeLink({companyId:company.id,view},`${label}${icon('arrow')}`,'action-link');

    const changes=module('changes',t('公司变化','Company changes'),events.length,t(`${events.length} 项事件，非未读数`,`${events.length} events, not unread`),
      events.length?t(`最近记录 ${e(events[0].date)}`,`Latest recorded ${e(events[0].date)}`):t('暂无可核对的变化','No changes available to review'),
      events.length?events.slice(0,2).map(event=>`<button id="event-${e(event.id)}" class="overview-item" data-action="event" data-event="${e(event.id)}">${preview(event.title,`${eventState(event.kind)} · ${e(event.date)} · ${event.evidenceIds.length} ${t('条证据','evidence items')}`,event.kind)}</button>`).join(''):
        noItems(t('当前样本尚无事件；这不代表公司没有发生变化。','No events in the current sample; this does not establish that nothing has changed.')),
      `<button id="overview-changes-all" class="action-link" data-action="changes">${t('查看全部变化','View all changes')}${icon('arrow')}</button>`);
    const research=module('reports',t('研究报告','Research reports'),reports.length,t(`${reports.length} 份独立报告`,`${reports.length} distinct reports`),
      reports.length?(reviewCount?t(`${authors} 位 Manager · ${reviewCount} 份当前版本待复核`,`${authors} Managers · ${reviewCount} current versions need review`):historicalReviewCount?t(`${authors} 位 Manager · ${historicalReviewCount} 个历史版本待复核`,`${authors} Managers · ${historicalReviewCount} historical versions need review`):t(`${authors} 位 Manager · 最近发布 ${e(reports[0].report.publishedAt)}`,`${authors} Managers · Latest published ${e(reports[0].report.publishedAt)}`)):t('尚无已发布报告','No published reports'),
      reports.length?reports.slice(0,2).map(({document,manager,report})=>routeLink({companyId:company.id,view:'report',reportId:document.id,version:report.version},
        preview(document.title,`${e(manager.name)} · ${kind(document.kind)} · ${e(report.version)} · ${e(report.publishedAt)}`,report.status==='review'?'watch':'neutral'),
        'overview-item',`open-${document.id}-${report.version}`)).join(''):
        noItems(t('研究覆盖不等于已完成报告。','Research coverage does not mean a report is complete.')),
      allLink('reports',t('查看全部报告','View all reports')));
    const materials=module('materials',t('资料与数据','Materials & data'),evidence.length,t(`${evidence.length} 条证据，非文件份数`,`${evidence.length} evidence items, not files`),
      evidence.length?t(`正文可读 ${availability.available} · 仅摘录 ${availability.excerpt} · 不可用 ${availability.unavailable}`,`Readable ${availability.available} · Excerpts ${availability.excerpt} · Unavailable ${availability.unavailable}`):t('资料尚未接入','Materials are not connected'),
      evidence.length?evidence.slice(0,2).map(item=>`<button id="material-${e(item.id)}" class="overview-item" data-action="evidence" data-evidence="${e(item.id)}" data-origin="material">${preview(item.sourceTitle,`${available(item.availability)} · ${e(item.publishedAt)}`,item.availability==='unavailable'?'risk':item.availability==='excerpt'?'watch':'neutral')}</button>`).join(''):
        noItems(t('原始材料与结构化数据仍有缺口。','Source materials and structured data remain unavailable.')),
      allLink('materials',t('查看资料与缺口','View materials & gaps')));
    const tracking=module('tracking',t('关注点','Open questions'),questions.length,t(`${questions.length} 项待验证事件`,`${questions.length} unresolved events`),
      questions.length?t(`涉及 ${questionReportCount} 份报告 · 仍待验证`,`Across ${questionReportCount} reports · Unresolved`):t('尚无已整理的关注点','No follow-up questions recorded'),
      questions.length?questions.slice(0,2).map(event=>{
        const related=event.affectedReports.map(link=>{
          const {manager,report}=getReport(company.id,link.reportId,link.version);
          const section=report.sections.find(item=>item.id===link.sectionId);
          return {manager,report,section};
        });
        const sectionTitles=[...new Set(related.filter(item=>item.section).map(item=>item.section.title))];
        const title=sectionTitles.length?sectionTitles.join(' / '):event.title;
        const authorsAndVersions=[...new Set(related.map(item=>`${item.manager.name} · ${item.report.version}`))].map(e).join(' / ');
        return `<button id="question-${e(event.id)}" class="overview-item" data-action="event" data-event="${e(event.id)}">${preview(title,`${authorsAndVersions}${authorsAndVersions?' · ':''}${t('仍待验证','Unresolved')}`,'watch')}</button>`;
      }).join(''):noItems(t('自动监控未接入，没有正在运行的任务。','Automated monitoring is not connected; no tasks are running.')),
      allLink('tracking',t('查看全部关注点','View all questions')));
    const tabs=[
      ['changes',t('公司变化','Company changes'),events.length,t('事件与新线索','Events & new signals'),t(`${events.length} 项事件，非未读数`,`${events.length} events, not unread`)],
      ['research',t('研究报告','Research reports'),reports.length,t('各位 Manager 的判断','Views from Managers'),t(`${reports.length} 份独立报告`,`${reports.length} distinct reports`)],
      ['materials',t('资料与数据','Materials & data'),evidence.length,t('证据与可读范围','Evidence & availability'),t(`${evidence.length} 条证据，非文件份数`,`${evidence.length} evidence items, not files`)],
      ['tracking',t('关注点','Open questions'),questions.length,t('尚待验证的问题','Questions to resolve'),t(`${questions.length} 项待验证事件`,`${questions.length} unresolved events`)],
    ];
    const sectionTabs=tabs.map(([key,label,count,detail,countLabel])=>`<button id="overview-tab-${key}" class="overview-tab ${key===selectedSection?'is-active':''}" role="tab" aria-controls="overview-panel-${key}" aria-selected="${key===selectedSection}" tabindex="${key===selectedSection?'0':'-1'}" data-action="overview-section" data-section="${key}"><span class="overview-tab-top"><span>${label}</span><span class="overview-tab-count" aria-label="${e(countLabel)}">${count}</span></span><span class="overview-tab-detail">${detail}</span></button>`).join('');
    return `<div class="company-overview"><div class="overview-heading"><h2>${t('研究概况','Research at a glance')}</h2><span>${t('变化、产出与待验证问题','Changes, outputs and open questions')}</span></div><div id="overview-deck" class="overview-deck"><div class="overview-sections" role="tablist" aria-label="${t('研究概况栏目','Research summary sections')}" aria-orientation="vertical">${sectionTabs}</div><div class="overview-stage"><div class="overview-panels">${changes}${research}${materials}${tracking}</div><div class="overview-controls"><span class="overview-switch-hint">${t('悬停或点击栏目切换','Hover or click a section')}</span><div class="overview-stepper"><button id="overview-prev" class="overview-step" data-action="overview-step" data-step="-1" aria-label="${t('上一栏目','Previous section')}">${icon('chevron')}</button><span id="overview-position" class="overview-position" aria-live="polite" aria-atomic="true">${String(sectionKeys.indexOf(selectedSection)+1).padStart(2,'0')} / 04</span><button id="overview-next" class="overview-step" data-action="overview-step" data-step="1" aria-label="${t('下一栏目','Next section')}">${icon('chevron')}</button></div></div></div></div></div>`;
  }
  function detailPlaceholder(title,description) {
    return `<div class="detail-placeholder"><span class="detail-placeholder-icon">${icon('file')}</span><h2 id="detail-title" tabindex="-1">${title}</h2><p>${description}</p></div>`;
  }
  function directoryHeading(title,count,description) {
    return `<div class="directory-heading"><h2>${title}</h2><span>${count}</span></div><p class="directory-description">${description}</p>`;
  }
  function reportDirectory(context,route) {
    const groups=catalog.managers.filter(manager=>context.coverage.some(item=>item.managerId===manager.id)||context.reports.some(item=>item.manager.id===manager.id));
    return directoryHeading(t('研究报告','Research reports'),context.reports.length,t('按 Manager 整理主报告与专题','Main and topic reports by Manager'))+groups.map(manager=>{
      const reports=context.reports.filter(item=>item.manager.id===manager.id);
      return `<section class="directory-group"><h3><span class="avatar">${e(manager.name[0])}</span><span>${e(manager.name)}<small>${e(manager.style)}</small></span></h3>${reports.length?reports.map(({document,report})=>{
        const active=route.view==='report'&&route.reportId===document.id;
        const selected=active?getReport(context.company.id,document.id,route.version).report:report;
        const target={companyId:context.company.id,view:'report',reportId:document.id,version:selected.version};
        return `<a id="open-${e(document.id)}-${e(selected.version)}" class="directory-row ${active?'is-active':''}" href="${e(formatRoute(target))}" ${active?'aria-current="page"':''}><span class="directory-row-title" lang="zh-CN">${e(document.title)}</span><span class="directory-row-meta">${kind(document.kind)} · ${e(selected.version)} · ${e(selected.publishedAt)}</span><span class="directory-row-state">${status(selected.status)}</span></a>`;
      }).join(''):`<p class="directory-gap">${t('已在研究覆盖中，尚未发布报告。','In research coverage; no report published yet.')}</p>`}</section>`;
    }).join('')+(groups.length?'':`<p class="directory-gap">${t('尚无研究覆盖或报告。','No research coverage or reports yet.')}</p>`);
  }
  function reports(route,returnRoute) {
    const context=getCompany(route.companyId);
    const body=route.view==='report'?fullReport(route,returnRoute):detailPlaceholder(
      context.reports.length?t('选择一份报告，开始阅读','Select a report to begin reading'):t('研究还没有形成报告','No report published yet'),
      context.reports.length?t('左侧按 Manager 整理主报告与专题。报告正文与各自历史版本会在这里打开。','The list groups main and topic reports by Manager. Read the full report and its historical versions here.'):t('研究覆盖不等于已发布报告。报告发布后，会保留作者、公司和独立版本。','Research coverage does not mean a report is published. Published reports will retain their author, company and independent versions.'));
    return `<div class="item-workspace report-workspace" data-workspace-kind="reports"><aside id="item-directory" class="item-directory" aria-label="${t('报告目录','Report directory')}">${reportDirectory(context,route)}</aside><div id="workspace-detail" class="item-detail">${body}</div></div>`;
  }
  function materials(route,selection=null) {
    const context=getCompany(route.companyId),body=detail(route,selection);
    const items=context.evidence.map(item=>`<button id="material-${e(item.id)}" class="directory-row" data-action="item-select" data-kind="material" data-id="${e(item.id)}" aria-current="${selection?.id===item.id}"><span class="directory-row-title" lang="${e(item.language)}">${e(item.sourceTitle)}</span><span class="directory-row-meta">${e(item.publishedAt)} · ${e(item.sourceType)}</span><span class="directory-row-state">${available(item.availability)}</span></button>`).join('');
    return `<div class="item-workspace" data-workspace-kind="materials"><aside id="item-directory" class="item-directory" aria-label="${t('资料与证据列表','Materials and evidence list')}">${directoryHeading(t('资料与证据','Materials & evidence'),context.evidence.length,t('按证据条目展示，非文件份数','Evidence items, not file count'))}<div class="item-list">${items||`<p class="directory-gap">${t('资料尚未接入','Materials are not connected')}</p>`}</div><p class="directory-note">${t('结构化财务数据与查询尚未接入。','Structured financial data and queries are not connected.')}</p></aside><div id="workspace-detail" class="item-detail">${body}</div></div>`;
  }
  function tracking(route,selection=null) {
    const context=getCompany(route.companyId),events=context.events.filter(event=>event.unresolved),body=detail(route,selection);
    const items=events.map(event=>`<button id="tracking-${e(event.id)}" class="directory-row" data-action="item-select" data-kind="tracking" data-id="${e(event.id)}" aria-current="${selection?.id===event.id}"><span class="directory-row-title" lang="zh-CN">${e(event.title)}</span><span class="directory-row-meta">${e(event.date)} · ${event.evidenceIds.length} ${t('条证据','evidence items')}</span><span class="directory-row-state">${signal(event.kind)}</span></button>`).join('');
    return `<div class="item-workspace" data-workspace-kind="tracking"><aside id="item-directory" class="item-directory" aria-label="${t('待验证问题列表','Open question list')}">${directoryHeading(t('关注点','Open questions'),events.length,t('报告中仍需核对的问题','Questions to review in reports'))}<div class="item-list">${items||`<p class="directory-gap">${t('尚无已整理的关注点','No follow-up questions recorded')}</p>`}</div><p class="directory-note">${t('自动监控未接入，没有运行中的任务。','Automated monitoring is not connected; no tasks are running.')}</p></aside><div id="workspace-detail" class="item-detail">${body}</div></div>`;
  }
  function detail(route,selection=null) {
    routeContext(route);
    if(route.managerId||!['materials','tracking'].includes(route.view)) throw new Error('Item details require a company materials or tracking view');
    const context=getCompany(route.companyId);
    if(selection===null) return route.view==='materials'?detailPlaceholder(
      context.evidence.length?t('选择一条资料，核对证据','Select a source to review its evidence'):t('资料尚未接入','Materials are not connected'),
      context.evidence.length?t('查看原文定位、发布日期、可读范围与资料缺口。同一份材料可能支持多条证据。','Review the source location, publication date, readable scope and gaps. One source may support several evidence items.'):t('当前公司尚无可查看的材料。接入后，每条证据会保留公司、日期与原文定位。','No materials are available for this company. Connected evidence will retain its company, dates and source location.')):detailPlaceholder(
      context.events.some(event=>event.unresolved)?t('选择一个关注点，了解判断变化','Select a question to review what changed'):t('待跟踪的问题尚未整理','No follow-up questions yet'),
      context.events.some(event=>event.unresolved)?t('核对此前判断、新增信息，以及受到影响的报告段落与相关材料。','Review the earlier view, new information, affected report sections and supporting evidence.'):t('需要先有明确的研究问题与对应报告，才能建立可追溯的跟踪关系。','A follow-up requires a clear research question and a link to its report.'));
    if(!selection||typeof selection.id!=='string'||!selection.id.trim()) throw new Error('An explicit item identity is required');
    if(route.view==='materials') {
      if(selection.kind!=='material') throw new Error('Materials view requires a material selection');
      const item=getMaterial(route.companyId,selection.id);
      return `<article class="detail-article"><div class="eyebrow"><span>${available(item.availability)}</span><span>${e(item.language)}</span></div><h2 id="detail-title" tabindex="-1" lang="${e(item.language)}">${e(item.sourceTitle)}</h2><p class="detail-subtitle">${e(context.company.name)} · ${e(item.sourceType)}</p><dl class="detail-source-meta"><div><dt>${t('原文定位','Source location')}</dt><dd>${e(item.locator)}</dd></div><div><dt>${t('发布日期','Published')}</dt><dd>${e(item.publishedAt)}</dd></div><div><dt>${t('可取得日期','Available')}</dt><dd>${e(item.availableAt)}</dd></div></dl>${item.availability==='unavailable'?`<p class="notice review">${t('原文不可用。不能将缺失材料解释为判断被证实或反驳。','The source is unavailable. Missing evidence neither confirms nor refutes a judgment.')}</p>`:`<blockquote lang="${e(item.language)}">${e(item.quote)}</blockquote>${item.context.map(paragraph=>`<p lang="${e(item.language)}">${e(paragraph)}</p>`).join('')}`}<section class="detail-section"><h3>${t('使用范围与缺口','Scope & limitations')}</h3><p lang="${e(item.language)}">${e(item.limitation)}</p></section><p class="detail-note">${t('此条为虚构演示资料，没有可打开的外部原始文件。查看资料不代表报告已经引用或采纳。','This is fictional demo evidence with no external source file. Viewing it does not establish report citation or adoption.')}</p></article>`;
    }
    if(selection.kind!=='tracking') throw new Error('Tracking view requires a tracking selection');
    const event=context.events.find(item=>item.id===selection.id&&item.unresolved);
    if(!event) throw new Error('Unresolved event not available for this company');
    return `<article class="detail-article"><div class="eyebrow">${signal(event.kind)}<span>${e(event.date)}</span><span>${e(context.company.name)}</span></div><h2 id="detail-title" tabindex="-1" lang="zh-CN">${e(event.title)}</h2><p class="detail-lead" lang="zh-CN">${e(event.reason)}</p><section class="detail-section"><h3>${t('此前的判断','Earlier view')}</h3><p lang="zh-CN">${e(event.before)}</p></section><section class="detail-section"><h3>${t('新增信息后的变化','What changed')}</h3><p lang="zh-CN">${e(event.after)}</p></section><section class="detail-section"><h3>${t('受影响的报告段落','Affected report sections')}</h3><div class="related-links">${reportLinks(route.companyId,event)}</div></section><section class="detail-section"><h3>${t('相关证据','Related evidence')}</h3>${event.evidenceIds.map(id=>materialButton(getMaterial(route.companyId,id),'material','panel-source',`tracking-evidence-${event.id}-${id}`)).join('')}</section><p class="detail-note">${t('证据支持当前事件，不代表被所有关联报告版本引用。关注点仍待验证；查看内容不会修改研究结论。','Evidence supports this event; it is not necessarily cited by every linked report version. The question remains unresolved; viewing it does not change the research conclusion.')}</p></article>`;
  }
  function fullReport(route,returnRoute) {
    routeContext(route);
    const {company,document,manager,report}=getReport(route.companyId,route.reportId,route.version);
    const back=returnRoute || leafRoute(route,'reports');
    return `<article class="reader" lang="zh-CN"><div class="reader-nav">${routeLink(back,`← ${back.institutionId?t('返回投资总览','Back to investment overview'):t('返回目录','Back to contents')}`,'', 'back-to-company')}<label class="version-control">${t('版本','Version')}<select id="report-version" aria-label="${t('选择报告版本','Choose report version')}">${document.versions.map(v=>`<option value="${e(v.version)}" ${v.version===report.version?'selected':''}>${e(v.version)} · ${e(v.publishedAt)}</option>`).join('')}</select></label></div><div class="eyebrow"><span>${kind(document.kind)}</span><span>${e(manager.name)} · ${e(manager.style)}</span>${status(report.status)}</div><h2 class="report-title" id="report-title" tabindex="-1">${e(document.title)}</h2><p class="report-subtitle">${e(report.subtitle || report.title)}</p><div class="identity-line"><span>${e(company.name)}</span><span>${e(report.version)}</span><span>${t('资料截止','As of')} ${e(report.cutoff)}</span><span>${t('发布','Published')} ${e(report.publishedAt)}</span></div>${report.reviewNote?`<p class="notice review">${e(report.reviewNote)}</p>`:''}${lang==='en'?'<p class="notice">The interface is in English. This fictional report and its evidence remain in their original Chinese edition.</p>':''}<div class="report-abstract"><span>${t('本版判断','This version’s judgment')}</span>${e(report.verdict)}</div><p class="subheading" style="margin-top:20px">${e(report.summary)}</p>${report.sections.map(section=>`<section id="section-${e(section.id)}" class="report-section" tabindex="-1"><div class="kicker">${e(section.kicker)}</div><h2>${e(section.title)}</h2>${section.paragraphs.map(p=>`<p>${e(p)}</p>`).join('')}${section.bullets?`<ul>${section.bullets.map(p=>`<li>${e(p)}</li>`).join('')}</ul>`:''}${section.table?`<div class="table-scroll"><table><thead><tr>${section.table.columns.map(c=>`<th>${e(c)}</th>`).join('')}</tr></thead><tbody>${section.table.rows.map(row=>`<tr>${row.map(c=>`<td>${e(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:''}<div class="citations">${section.citations.map((id,index)=>{const {evidence}=getEvidence(company.id,document.id,report.version,id);return `<button id="cite-${e(section.id)}-${e(id)}" class="citation" data-action="evidence" data-evidence="${e(id)}" data-origin="report">${icon('link')}<span>${index+1} · ${e(evidence.sourceTitle.replace('虚构演示 · ',''))}${evidence.availability==='unavailable'?` · ${available(evidence.availability)}`:''}</span></button>`;}).join('')}</div></section>`).join('')}<footer class="reading-end"><span>${t('虚构研究样本 · 全文保留原版','Fictional sample · Original edition preserved')}</span><button class="action-link" data-action="top">${t('回到顶部','Back to top')} ↑</button></footer></article>`;
  }
  function main(route,returnRoute,overviewSection='changes',itemSelection=null,institutionState={},managerState={}) {
    routeContext(route);
    if(route.institutionId) return institutionViews.main(route,institutionState||{});
    if(route.managerId) return route.view==='report'?fullReport(route,returnRoute):managerViews.main(route,managerState);
    if(route.view==='report'||route.view==='reports') return reports(route,returnRoute);
    if(route.view==='overview') return overview(getCompany(route.companyId),overviewSection);
    return ({materials,tracking})[route.view](route,itemSelection);
  }
  function panel(route,selection) {
    let title='',body='';
    routeContext(route);
    if(route.institutionId) {
      if(!['context','design'].includes(selection.kind)) throw new Error('Institution overview only has overview context');
      const details=institutionViews.context(route);
      return `<div class="panel-title"><h2 id="panel-title" tabindex="-1">${details.title}</h2><button id="close-panel" class="panel-close" data-action="close-panel" aria-label="${t('收起上下文','Close context')}">×</button></div><div class="panel-body">${details.body}</div>`;
    }
    const context=route.managerId?getManager(route.managerId):getCompany(route.companyId);
    if(selection.kind==='design') {
      title=t('这张页面如何工作','How this page works');
      const zones=[
        ['A',t('最左 · 全局导航','Far left · Workspace navigation'),t('公司与 Managers 是全局入口。雨滴和图标始终可见；悬停展开名称，导航变宽时平滑推动后两列。键盘与触屏也可用展开按钮。','Companies and Managers are global destinations. The drop and icons remain visible; hovering reveals labels and smoothly shifts the other columns. A toggle also supports keyboard and touch.')],
        ['B',t('中间 · 独立的对象列表','Middle · A separate entity list'),t('搜索、公司或 Manager 名单始终可见，宽度不随全局导航展开而改变。悬停对象显示内容目录；点击目录才切换右侧正文。切回对象保留阅读位置。','Search and the company or Manager list remain visible at a stable width. Hover an entity for its contents; click a section to change the right pane. Returning restores reading position.')],
        ['C',t('右侧 · 概览与可切换栏目','Right · Overview and content sections'),t('顶部栏目可直接切换。公司概览以左侧四个标签切换右侧一个摘要面板，悬停后保持显示；点击、键盘和前后按钮也可切换，不自动轮播。每栏最多预览两条。报告、资料与关注点延续左侧条目、右侧内容的布局；点击后才打开详细内容，报告正文保留完整阅读宽度和历史版本。数量分别表示事件、独立报告、证据条目和待验证事件，不是未读数；证据数也不是文件份数。Manager 沿用自身栏目。','Use the top navigation to switch sections. Four tags on the left select one summary panel on the right. Hover selection remains visible; click, keyboard and previous/next controls also work, with no automatic rotation. Each summary has up to two previews. Reports, materials and questions use a left list and a right reading area; details open on click, with full report text and historical versions preserved. Counts mean events, distinct reports, evidence items and unresolved events—not unread messages or file counts. Managers retain their own sections.')],
        ['D',t('报告 · 稳定的阅读对象','Report · A stable reading artifact'),t('主报告和专题有各自版本。切换历史版保留原文和审核状态，读过不等于审核或采纳。','Main and topic reports have independent versions. Historical text and review status stay intact; reading does not imply adoption.')]
      ];
      body=zones.map(([code,heading,text])=>`<div class="design-zone"><strong><em>${code}</em>${heading}</strong><p>${text}</p></div>`).join('')+`<p>${t('当前研究内容为虚构样本。账户、交易和自动任务尚未接入；研究覆盖不代表持仓，资料缺失也不代表零收益或零交易。','Research content is fictional. Accounts, trades and automated tasks are not connected. Coverage is not a holding; missing data does not imply zero returns or zero trades.')}</p><a class="action-link" href="../page-blueprint/#map">${t('查看完整标注稿','Open the full blueprint')}${icon('arrow')}</a>`;
    } else if(selection.kind==='changes') {
      if(route.managerId) throw new Error('Company changes require a company entry');
      const events=[...new Map(context.events.map(event=>[event.id,event])).values()];
      title=t('全部公司变化','All company changes');
      body=`<p class="note">${events.length} ${t('项演示事件 · 按事件去重，非未读数','demo events · Distinct events, not unread')}</p>${events.length?`<div class="event-list">${events.map(event=>`<button id="change-${e(event.id)}" class="event-row" data-action="event" data-event="${e(event.id)}">${signal(event.kind)}<div><strong lang="zh-CN">${e(event.title)}</strong><p>${e(event.date)} · ${event.evidenceIds.length} ${t('条证据','evidence items')}</p></div>${icon('chevron')}</button>`).join('')}</div>`:empty(t('暂无可核对的变化','No changes available to review'),t('当前样本尚无事件；这不代表公司没有发生变化。','No events in the current sample; this does not establish that nothing has changed.'))}`;
    } else if(selection.kind==='event') {
      const ev=context.events.find(event=>event.id===selection.eventId);
      if(!ev) throw new Error('Event not available for this company');
      title=t('变化与影响','Change & impact');
      body=`${selection.parent?`<button id="back-to-changes" class="action-link" data-action="panel-back">← ${t('返回变化列表','Back to all changes')}</button>`:''}<div class="eyebrow">${signal(ev.kind)}<span>${e(ev.date)}</span></div><h3 lang="zh-CN">${e(ev.title)}</h3><p class="panel-lead" lang="zh-CN">${e(ev.reason)}</p><h4 class="small-heading">${t('此前的判断','Earlier view')}</h4><p lang="zh-CN">${e(ev.before)}</p><h4 class="small-heading">${t('新增信息后的变化','What changed')}</h4><p lang="zh-CN">${e(ev.after)}</p><h4 class="small-heading">${t('打开受影响的报告段落','Open the affected report section')}</h4><div class="related-links">${reportLinks(route.companyId,ev)}</div><h4 class="small-heading">${t('相关材料','Related evidence')}</h4>${ev.evidenceIds.map(id=>materialButton(getMaterial(route.companyId,id),'material')).join('')}<p>${t('证据支持事件，不代表被所有关联报告版本引用。','Evidence supports this event; it is not necessarily cited in every linked report version.')}</p>`;
    } else if(selection.kind==='evidence') {
      const item=selection.origin==='report'?getEvidence(route.companyId,route.reportId,route.version,selection.evidenceId).evidence:getMaterial(route.companyId,selection.evidenceId);
      title=t('证据与来源','Evidence & source');
      body=`${selection.parent?`<button class="action-link" data-action="panel-back">← ${t('返回变化','Back to change')}</button>`:''}<div class="eyebrow"><span>${available(item.availability)}</span><span>中文 · zh-CN</span></div><h3 lang="zh-CN">${e(item.sourceTitle)}</h3><p>${selection.origin==='report'?`${e(route.reportId)} · ${e(route.version)} · ${t('正文引用','Report citation')}`:t('从公司资料进入 · 不预设报告采纳关系','Company evidence · No report adoption implied')}</p><dl><dt>${t('原文定位','Location')}</dt><dd>${e(item.locator)}</dd><dt>${t('发布日期 / 可取得日期','Published / available date')}</dt><dd>${e(item.publishedAt)} / ${e(item.availableAt)}</dd></dl>${item.availability==='unavailable'?`<div class="notice review">${t('原文不可用。不能将缺失材料解释为判断被证实或反驳。','The source is unavailable. Missing evidence neither confirms nor refutes a judgment.')}</div>`:`<blockquote lang="zh-CN">${e(item.quote)}</blockquote>${item.context.map(p=>`<p lang="zh-CN">${e(p)}</p>`).join('')}`}<h4 class="small-heading">${t('使用范围与缺口','Scope & limitations')}</h4><p lang="zh-CN">${e(item.limitation)}</p><p class="note">${t('此条为虚构演示资料，没有可打开的外部原始文件。','This is fictional demo evidence, with no external source file.')}</p>`;
    } else {
      title=t('研究上下文','Research context');
      if(route.view==='report') {
        const {document,manager,report}=getReport(route.companyId,route.reportId,route.version);
        body=`<div class="eyebrow">${status(report.status)}<span>${e(report.version)}</span></div><h3>${e(document.title)}</h3><p>${e(manager.name)} · ${e(manager.style)}<br>${t('资料截止','As of')} ${e(report.cutoff)}</p><h4 class="small-heading">${t('报告目录','Contents')}</h4>${report.sections.map(s=>`<button class="toc-link" data-action="section" data-section="${e(s.id)}">${e(s.title)}</button>`).join('')}<p>${t('目录只定位正文；证据从对应段落打开。','Contents navigate within this report. Open evidence from its cited section.')}</p>`;
      } else if(route.managerId) {
        ({title,body}=managerViews.context(route));
      } else {
        body=`<div class="eyebrow">${e(context.company.ticker)}</div><h3>${e(context.company.name)}</h3><p>${t('已发布研究按作者整理，待研究关系与已发布报告分别展示。','Published research is grouped by author. Coverage and published reports are distinct.')}</p>${coverageList(context)}<h4 class="small-heading">${t('研究覆盖','Research coverage')}</h4><p>${context.reports.length} ${t('份报告','reports')} · ${context.evidence.length} ${t('条证据','evidence items')}<br>${context.events.filter(ev=>ev.unresolved).length} ${t('项待验证问题','open questions')}</p><h4 class="small-heading">${t('执行状态','Execution status')}</h4><p>${t('本页读取已有演示内容。自动获取、监控与研究任务尚未接入。','This page reads existing sample content. Automated collection, monitoring and research execution are not connected.')}</p>`;
      }
    }
    return `<div class="panel-title"><h2 id="panel-title" tabindex="-1">${title}</h2><button id="close-panel" class="panel-close" data-action="close-panel" aria-label="${t('收起侧栏，返回阅读','Close panel and return to reading')}">×</button></div><div class="panel-body">${body}</div>`;
  }
  return { t, globalNavigation, sidebar, entityRows, entityMenu, contentNavigation, toolbar, header, tabs, main, detail, panel, managerMain:managerViews.main, investmentEvents:institutionViews.events, allocationHistory:institutionViews.history, institutionPortfolio:institutionViews.portfolio, institutionChartBody:institutionViews.chartBody, institutionTrades:institutionViews.trades };
}
