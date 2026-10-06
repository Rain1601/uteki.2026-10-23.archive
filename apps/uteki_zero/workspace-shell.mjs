import { workspace, findVersion } from './catalog.mjs';
import { resolveBrand } from './brands.mjs';
import { formatRoute } from './workspace-state.mjs';
import { indexRoute, documentRoute, indexReturnRoute, switchEntryRoute, comparisonRoute, evidenceReturnRoute } from './workspace-model.mjs';
import { escapeHTML as h, icon } from './reader-view.mjs';

const text = (language, zh, en) => language === 'en' ? en : zh;
const date = (value, language) => value ? new Intl.DateTimeFormat(language === 'en' ? 'en-GB' : 'zh-CN', { year:'numeric', month:'short', day:'numeric', timeZone:'UTC' }).format(new Date(value)) : '—';
const link = (route, label, className = '', extra = '') => `<a href="${h(formatRoute(route))}" class="${className}" ${extra}>${label}</a>`;
const kind = (document, language) => document.kind === 'main' ? text(language,'主报告','Main report') : text(language,'专题','Topic');
const reportsFor = (entry, objectId) => workspace.reports.filter(document => (entry === 'companies' ? document.companyId : document.managerId) === objectId);
const eventsFor = documents => {
  const ids = new Set(documents.map(document => document.id));
  return workspace.events.filter(event => event.affectedReports.some(ref => ids.has(ref.reportId)));
};
function mark(company, registry) {
  const brand = resolveBrand(company, registry);
  return `<span class="company-icon" aria-hidden="true">${brand ? `<img src="${h(brand.src)}" width="36" height="36" alt="" data-brand-image>` : icon('company')}</span>`;
}
const managerMark = manager => `<span class="manager-initial" aria-hidden="true">${h(manager.name.slice(0,1))}</span>`;
const currentObjectId = route => route.objectId;
const readVersions = state => state.readVersions || {};
const readEvents = state => state.readEvents || [];
function entryLinks(route, state, extraClass = '') {
  const t = (zh,en) => text(state.language,zh,en);
  return `<nav class="entry-switch ${extraClass}" aria-label="${t('浏览方式','Browse by')}">${[['companies',t('公司','Companies')],['managers','Manager']].map(([entry,label])=>link(switchEntryRoute(route,entry,state),label,entry === route.entry ? 'is-active' : '',`data-entry="${entry}" ${entry === route.entry ? 'aria-current="true"' : ''}`)).join('')}</nav>`;
}
function sidebar(route, context, state, registry) {
  const t = (zh,en)=>text(state.language,zh,en), companies = route.entry === 'companies';
  const items = companies ? workspace.companies : workspace.managers;
  const rows = items.map(item => {
    const documents = reportsFor(route.entry,item.id);
    const unread = eventsFor(documents).filter(event => !readEvents(state).includes(event.id)).length;
    const published = documents.filter(document => document.currentVersion).length;
    const label = companies ? `${h(item.ticker)}<span class="row-state">${published ? `${published} ${t('份报告','reports')}` : t('研究中','In research')}</span>` : h(item.style);
    return link(indexRoute(route.entry,item.id),`${companies ? mark(item,registry) : managerMark(item)}<span class="company-copy"><strong>${h(item.name)}</strong><span>${label}</span></span>${unread ? `<span class="unread-count" aria-label="${unread} ${t('条未读变化','unread updates')}">${unread}</span>` : ''}`,`company-row ${currentObjectId(route) === item.id ? 'is-selected' : ''}`,`data-object="${h(item.id)}" ${currentObjectId(route) === item.id ? 'aria-current="page"' : ''}`);
  }).join('');
  return `<aside class="company-sidebar directory-sidebar" aria-label="${companies ? t('公司列表','Companies') : t('Manager 列表','Managers')}">${entryLinks(route,state)}<div class="sidebar-title"><span>${companies ? t('关注的公司','Following') : t('投资视角','Research perspectives')}</span><span>${String(items.length).padStart(2,'0')}</span></div><nav class="companies" data-scroll="sidebar" aria-label="${t('选择对象','Select an object')}">${rows}</nav><div class="sidebar-bottom"><p>${t('从信息，到判断。','From information to insight.')}</p><span class="local-save-state">${t('阅读记录仅保存在本机','Reading history stays on this device')}</span><a class="legacy-link" href="legacy.html">${t('上一版工作台','Previous workspace')} ${icon('source')}</a></div></aside>`;
}
function mobileObject(route, state) {
  const t=(zh,en)=>text(state.language,zh,en), items=route.entry === 'companies' ? workspace.companies : workspace.managers;
  return `<div class="mobile-object-navigation">${entryLinks(route,state,'is-mobile')}<label><span class="sr-only">${route.entry === 'companies' ? t('选择公司','Select company') : t('选择 Manager','Select manager')}</span><select id="object-control">${items.map(item=>`<option value="${h(item.id)}" ${item.id === currentObjectId(route) ? 'selected' : ''}>${h(item.name)}</option>`).join('')}</select></label></div>`;
}
function directoryHeader(route, context, state, registry) {
  const l=state.language,t=(zh,en)=>text(l,zh,en),company=route.entry === 'companies',object=context.object;
  const documents=reportsFor(route.entry,route.objectId).filter(document=>document.currentVersion);
  const associated=new Set(context.allGroups?.map(group=>company ? group.manager.id : group.company.id) || context.groups.map(group=>company ? group.manager.id : group.company.id));
  const eventCount=eventsFor(reportsFor(route.entry,route.objectId)).length;
  const tabs=[['research',t('研究报告','Research reports')],['changes',`${t('变化','Changes')}${eventCount ? `<span>${eventCount}</span>` : ''}`]];
  if(!company) tabs.push(['portfolio',t('组合与表现','Portfolio & performance')]);
  return `<header class="case-header directory-header">${mobileObject(route,state)}<div class="directory-heading"><div class="case-title">${company ? mark(object,registry) : managerMark(object)}<div><div class="breadcrumb">${company ? t('公司研究','Company research') : t('Manager 研究','Manager research')}${company ? `<span>/</span>${h(object.ticker)}` : ''}</div><h1>${h(object.name)}</h1></div></div><div class="directory-counts"><span><strong>${associated.size}</strong>${company ? t('位 Manager','managers') : t('家公司','companies')}</span><span><strong>${documents.length}</strong>${t('份报告','reports')}</span></div></div><p class="directory-description">${h(company ? object.tagline : object.description)}</p>${!company ? `<div class="manager-method"><span>${h(object.style)}</span><span>${t('研究期限','Horizon')} ${h(object.horizon)}</span><span>${h(object.methodVersion)}</span></div>` : ''}<div class="case-toolbar"><nav class="view-tabs" aria-label="${t('目录内容','Directory views')}">${tabs.map(([view,label])=>link(indexRoute(route.entry,route.objectId,view,view === 'portfolio' ? undefined : route.filterId),label,route.view === view ? 'is-active' : '',route.view === view ? 'aria-current="page"' : '')).join('')}</nav><span class="directory-origin-label">${t('示例研究 · 原文中文','Demo research · original Chinese')}</span></div></header>`;
}
function versionOptions(document, selected, language) {
  return [...document.versions].reverse().map(report=>`<option value="${h(report.version)}" ${report.version === selected ? 'selected' : ''}>${h(report.version)} · ${report.status === 'review' ? text(language,'待复核','Under review') : report.version === document.currentVersion ? text(language,'当前正式版','Current') : text(language,'历史版本','History')}</option>`).join('');
}
function comparisonControl(route, context, state) {
  const t=(zh,en)=>text(state.language,zh,en);
  if(route.view === 'compare' || (route.view === 'evidence' && route.origin === 'compare')) return link(route.view === 'compare' ? route : evidenceReturnRoute(route),t('比较观点','Compare views'),'is-active','aria-current="page"');
  if(context.document.kind !== 'main') return '';
  const candidates=workspace.reports.filter(document=>document.companyId === route.companyId && document.managerId !== route.managerId && document.kind === 'main' && document.currentVersion);
  if(!candidates.length) return '';
  const active=route.view === 'compare' || (route.view === 'evidence' && route.origin === 'compare');
  const candidateLink=document=>link(comparisonRoute(route,document.id),candidates.length === 1 ? t('比较观点','Compare views') : h(workspace.managers.find(manager=>manager.id===document.managerId)?.name || document.managerId),active ? 'is-active' : '',active ? 'aria-current="page"' : '');
  if(candidates.length === 1) return candidateLink(candidates[0]);
  return `<details class="comparison-choices"><summary>${t('比较观点','Compare views')}</summary><div>${candidates.map(candidateLink).join('')}</div></details>`;
}
function readerHeader(route, context, state) {
  const l=state.language,t=(zh,en)=>text(l,zh,en), {company,manager,document,report}=context;
  const view=route.view === 'evidence' ? route.origin || 'report' : route.view;
  const eventCount=workspace.events.filter(event=>event.affectedReports.some(ref=>ref.reportId===document.id&&ref.version===route.version)).length;
  return `<header class="case-header document-header">${mobileObject(route,state)}<div class="document-navigation">${link(indexReturnRoute(route),`${icon('back')}${t('返回报告目录','Back to report directory')}`,'directory-return','data-directory-return')}<span>${kind(document,l)}<span>·</span>${h(document.title)}</span></div><div class="case-heading"><div class="case-title"><div><div class="breadcrumb">${route.entry === 'companies' ? t('从公司浏览','Browsing by company') : t('从 Manager 浏览','Browsing by manager')}</div><h1 class="report-owner-heading">${h(company.name)}<span>/</span>${h(manager.name)}</h1></div></div><label class="reader-version"><span>${t('版本','Version')}</span><select id="version-control">${versionOptions(document,route.version,l)}</select></label></div><div class="reader-context"><span>${h(manager.style)}</span><span class="context-status ${report?.status === 'review' ? 'is-warning' : ''}"><i></i>${report?.status === 'review' ? t('结论待复核','Thesis under review') : report?.version !== document.currentVersion ? t('历史报告','Historical report') : t('已发布 · 示例','Published · demo')}</span><span>${t('信息截止','Information as of')} <time>${date(report?.cutoff,l)}</time></span></div><div class="case-toolbar"><nav class="view-tabs" aria-label="${t('阅读视图','Reading views')}">${link(documentRoute(document,route.version,route),t('报告','Report'),view === 'report' ? 'is-active' : '',view === 'report' ? 'aria-current="page"' : '')}${link(documentRoute(document,route.version,route,'changes'),`${t('变化','Changes')}${eventCount ? `<span>${eventCount}</span>` : ''}`,view === 'changes' ? 'is-active' : '',view === 'changes' ? 'aria-current="page"' : '')}${comparisonControl(route,context,state)}</nav><label class="font-control"><span aria-hidden="true">Aa</span><span class="sr-only">${t('正文字号','Reading font size')}</span><select id="font-control">${[16,17,18].map(size=>`<option value="${size}" ${size === state.fontSize ? 'selected' : ''}>${size} px</option>`).join('')}</select></label></div></header>`;
}
export function shell(route, context, state, registry) {
  const l=state.language,t=(zh,en)=>text(l,zh,en);
  const home=indexRoute(route.entry,currentObjectId(route));
  return `<a class="skip-link" href="#reading-area" data-skip>${t('跳到正文','Skip to content')}</a><header class="global-header">${link(home,'<span class="brand-symbol"><img src="assets/brand-source.jpeg" width="138" height="77" alt=""></span><span class="brand-name">uteki</span>','brand','aria-label="Uteki"')}<span class="workspace-title">${t('研究工作台','Research workspace')}</span><div class="global-tools"><span class="prototype-label">${t('演示原型','Prototype')}</span><button id="language-control" class="quiet-button" data-action="language" aria-label="${t('切换为英文界面','Switch interface to Chinese')}">${l === 'en' ? '中文' : 'EN'}</button><label class="theme-control">${icon('sun')}<span class="sr-only">${t('主题','Theme')}</span><select id="theme-control" name="theme">${[['system',t('跟随系统','System')],['light',t('日间','Light')],['dark',t('夜间','Dark')]].map(([value,label])=>`<option value="${value}" ${state.theme === value ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div></header><div class="workspace-layout">${sidebar(route,context,state,registry)}<main class="research-main">${route.page === 'index' ? directoryHeader(route,context,state,registry) : readerHeader(route,context,state)}<div id="view-outlet" class="view-outlet"></div></main></div>`;
}

function reportRow(document, route, state) {
  const l=state.language,t=(zh,en)=>text(l,zh,en),report=findVersion(document.id,document.currentVersion);
  if(!report) return '';
  const read=readVersions(state)[document.id] === report.version;
  return link(documentRoute(document,report.version,route),`<span class="directory-report-type">${kind(document,l)}</span><span class="directory-report-copy"><strong>${h(document.title)}</strong><span>${h(report.verdict || report.summary)}</span></span><span class="directory-report-meta"><span>${report.status === 'review' ? `<span class="is-warning">${t('待复核','Under review')}</span>` : h(report.version)}<span class="report-read-state ${read ? '' : 'is-unread'}">${read ? t('已读','Read') : t('未读','Unread')}</span></span><time datetime="${h(report.publishedAt)}">${date(report.publishedAt,l)}</time></span><span class="directory-report-arrow">${icon('arrow')}</span>`,'directory-report-row',`id="open-${h(document.id)}" data-open-report="${h(document.id)}"`);
}
function directoryFilter(route, context, state) {
  const t=(zh,en)=>text(state.language,zh,en),company=route.entry === 'companies';
  const groups=context.allGroups || context.groups;
  const options=[...new Map(groups.map(group=>{const object=company?group.manager:group.company;return [object.id,object]})).values()];
  return `<label class="directory-filter"><span>${company ? 'Manager' : t('公司','Company')}</span><select id="directory-filter"><option value="">${company ? t('全部 Manager','All managers') : t('全部公司','All companies')}</option>${options.map(object=>`<option value="${h(object.id)}" ${route.filterId === object.id ? 'selected' : ''}>${h(object.name)}</option>`).join('')}</select></label>`;
}
function groupedReports(route, context, state) {
  const l=state.language,t=(zh,en)=>text(l,zh,en),company=route.entry === 'companies';
  return context.groups.map(group=>{
    const object=company ? group.manager : group.company;
    const documents=group.reports.filter(document=>document.currentVersion);
    const otherEntry=company ? 'managers' : 'companies';
    return `<section class="directory-group" aria-labelledby="group-${h(object.id)}"><header class="directory-group-heading"><div><h2 id="group-${h(object.id)}">${link(indexRoute(otherEntry,object.id),h(object.name))}</h2><span>${h(company ? object.style : object.ticker)}</span></div><span class="directory-group-count">${documents.length ? `${documents.length} ${t('份报告','reports')}` : t('研究中','In research')}</span></header>${documents.length ? `<div class="directory-report-list">${documents.map(document=>reportRow(document,route,state)).join('')}</div>` : `<div class="directory-pending"><span>${icon('book')}</span><div><strong>${t('正式报告尚未发布','No published report yet')}</strong><p>${t('这项公司研究正在进行，完成后会出现在这里。','This company research is in progress. A published report will appear here when available.')}</p></div></div>`}</section>`;
  }).join('');
}
function changesDirectory(route, context, state) {
  const l=state.language,t=(zh,en)=>text(l,zh,en), ids=new Set(context.documents.map(document=>document.id));
  const events=[...new Map(context.events.map(event=>[event.id,event])).values()];
  if(!events.length) return `<div class="directory-empty"><span class="pending-symbol">${icon('list')}</span><h2>${t('暂无关联变化','No related updates')}</h2><p>${t('当前示例未提供这个范围的变化记录，也没有表示检查已完成。','This demo has no updates in the selected scope. It does not indicate a completed monitoring check.')}</p></div>`;
  return `<div class="directory-changes">${events.map(event=>{
    const refs=event.affectedReports.filter(ref=>ids.has(ref.reportId));
    const read=readEvents(state).includes(event.id);
    return `<section class="change-entry directory-change" id="event-${h(event.id)}"><div class="change-meta"><time datetime="${h(event.date)}">${date(event.date,l)}</time><span class="event-state ${event.unresolved ? 'is-warning' : ''}">${event.unresolved ? t('仍待验证','Unresolved') : t('已有新依据','New evidence')}</span>${read ? `<span>${t('已读','Read')}</span>` : `<span class="is-unread">${t('未读','Unread')}</span>`}</div><h2>${h(event.title)}</h2><p>${h(event.summary)}</p><p class="change-reason"><strong>${t('为何值得关注','Why it matters')}</strong>${h(event.reason)}</p><div class="affected-report-list"><span>${t('影响的报告与判断','Affected reports and arguments')}</span>${refs.map(ref=>{
      const document=workspace.reports.find(item=>item.id===ref.reportId),version=findVersion(ref.reportId,ref.version);
      const manager=workspace.managers.find(item=>item.id===document.managerId),company=workspace.companies.find(item=>item.id===document.companyId);
      const section=version.sections.find(item=>item.id===ref.sectionId);
      return link({...documentRoute(document,ref.version,route),section:ref.sectionId},`<span>${h(company.name)} <span>·</span> ${h(manager.name)} <span>·</span> ${h(ref.version)}</span><strong>${h(document.title)}</strong><span>${h(section.title)} ${icon('arrow')}</span>`,'affected-report-link');
    }).join('')}</div><div class="change-actions"><span class="demo-footnote">${t('已读状态不会改变问题是否解决。','Reading does not resolve this question.')}</span><button class="quiet-button" id="read-event-${h(event.id)}" data-action="read-event" data-id="${h(event.id)}" ${read ? 'disabled' : ''}>${read ? t('已读','Read') : t('标记已读','Mark as read')}</button></div></section>`;
  }).join('')}</div>`;
}
export function directoryView(route, context, state) {
  const t=(zh,en)=>text(state.language,zh,en),changes=route.view === 'changes';
  return `<div id="reading-area" class="reading-scroll" data-scroll="main" tabindex="-1"><div class="directory-content"><div class="directory-content-heading"><div><h2>${changes ? t('判断的新变化','Changes in the research') : route.entry === 'companies' ? t('不同视角，同一家公司','Research perspectives') : t('覆盖的公司研究','Company coverage')}</h2><p>${changes ? t('每条变化连接到具体报告和受影响的判断。','Every update links to a specific report and argument.') : route.entry === 'companies' ? t('按 Manager 浏览主报告与专题。','Browse main reports and topics by manager.') : t('按公司浏览主报告与专题。','Browse main reports and topics by company.')}</p></div>${directoryFilter(route,context,state)}</div>${changes ? changesDirectory(route,context,state) : groupedReports(route,context,state)}<p class="directory-footnote">${t('以上报告与日期均为演示内容。报告数量按独立报告计数，历史版本收录在各报告内。','Reports and dates are fictional demo content. Report counts exclude historical versions, which stay inside each report.')}</p></div></div>`;
}
export function portfolioView(route, context, state) {
  const t=(zh,en)=>text(state.language,zh,en);
  return `<div id="reading-area" class="reading-scroll" data-scroll="main" tabindex="-1"><div class="directory-content"><div class="directory-content-heading"><div><h2>${t('组合与表现','Portfolio & performance')}</h2><p>${h(context.object.name)} · ${t('独立的投资决策维度','An independent view of investment decisions')}</p></div></div><div class="portfolio-unavailable"><span class="pending-symbol">${icon('list')}</span><p class="eyebrow">${t('尚未接入','NOT CONNECTED')}</p><h2>${t('研究观点之外，看实际的投资决策。','See the decisions behind the research.')}</h2><p>${t('这里将展示这位 Manager 的持仓、调仓动作与收益。目前没有已接入的组合记录。','This view is for the manager’s holdings, portfolio actions and returns. No portfolio records are connected yet.')}</p><div class="portfolio-availability"><div><span>${t('持仓','Holdings')}</span><strong>${t('暂无数据','Not available')}</strong></div><div><span>${t('投资动作','Actions')}</span><strong>${t('暂无数据','Not available')}</strong></div><div><span>${t('收益与归因','Returns & attribution')}</span><strong>${t('暂无数据','Not available')}</strong></div></div><p class="demo-footnote">${t('报告中的判断不等于真实持仓或已执行的交易。','Research views do not establish actual holdings or executed trades.')}</p></div></div></div>`;
}
