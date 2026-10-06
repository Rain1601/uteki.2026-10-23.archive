import { content } from './content.mjs';
import { brandDomain, validateBrandRegistry, resolveBrand } from './brands.mjs';

// Isolated, fictional prototype. No production modules, accounts or research writes.
const root = document.querySelector('#uteki');
const KEY = 'uteki.snap-workspace.v1';
const companies = new Map(content.companies.map(item => [item.id, item]));
const portfolios = new Map(content.managers.map(item => [item.id, item]));
const events = new Map(content.companies.flatMap(company => company.events.map(event => [event.id, { company, event }])));
const drafts = new Map();
let brandRegistry = { version: 1, brands: {} };
const failedBrandImages = new Set();
const views = new Map();
const state = {
  mode: 'companies', language: 'zh',
  selected: { companies: 'alphabet', portfolios: 'north' },
  followed: content.companies.filter(item => item.followed).map(item => item.id),
  read: [], saved: [], notes: {},
};
let storageAvailable = true;
let toastTimer;

function h(value) { return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]); }
function t(zh, en) { return state.language === 'en' ? en : zh; }
function getCompany(id) { const value = companies.get(id); if (!value) throw new Error(`Unknown company: ${id}`); return value; }
function getPortfolio(id) { const value = portfolios.get(id); if (!value) throw new Error(`Unknown portfolio: ${id}`); return value; }
function current() { return state.mode === 'companies' ? getCompany(state.selected.companies) : getPortfolio(state.selected.portfolios); }
function objects() { return state.mode === 'companies' ? content.companies : content.managers; }
function view() {
  const key = `${state.mode}:${current().id}`;
  if (!views.has(key)) views.set(key, { tab: 'overview', pages: {}, detail: null });
  return views.get(key);
}
function tabs() {
  return state.mode === 'companies'
    ? [['overview', t('总览', 'Overview')], ['changes', t('变化', 'Updates')], ['report', t('主报告', 'Report')], ['tracking', t('追踪', 'Tracking')]]
    : [['overview', t('总览', 'Overview')], ['holdings', t('持仓', 'Holdings')], ['actions', t('动作', 'Actions')], ['performance', t('表现', 'Performance')]];
}
function unread(company) { return company.events.filter(event => !state.read.includes(event.id)).length; }
function statusText(kind) { return ({ review: t('判断待复核', 'Revisit the thesis'), support: t('新增支持', 'New support'), watch: t('等待验证', 'Awaiting evidence'), quiet: t('暂无新变化', 'No new updates'), new: t('初步研究', 'Initial research') })[kind]; }
function status(kind) { return `<span class="state ${kind}">${statusText(kind)}</span>`; }
function dateShort(value) { return value.slice(5).replace('-', '.'); }
function signed(value) { return `${value > 0 ? '+' : ''}${value.toFixed(1)}`; }
function portfolioName(item) { return `${item.name.split(' · ')[1]}${t('组合', ' portfolio')}`; }
function managerName(item) { return item.name.split(' · ')[0]; }
function factorFor(company, id) { const factor = company.report.factors.find(item => item.id === id); if (!factor) throw new Error(`Unknown company factor: ${id}`); return factor; }
function eventFor(company, id) { const event = company.events.find(item => item.id === id); if (!event) throw new Error(`Unknown company event: ${id}`); return event; }
function button(action, id, label, className = 'text-link', attrs = '') { return `<button type="button" class="${className}" data-action="${action}" data-id="${h(id)}" ${attrs}>${label}</button>`; }
function icon(name) {
  const paths = {
    company: '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h1m4 0h1M9 11h1m4 0h1M9 15h1m4 0h1M10 21v-3h4v3"/>',
    portfolio: '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M8 8V5h8v3M3 13c6 3 12 3 18 0M12 12v4"/>',
    next: '<path d="m9 5 7 7-7 7"/>',
    prev: '<path d="m15 5-7 7 7 7"/>',
    arrow: '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    back: '<path d="M20 12H4m6-6-6 6 6 6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    bookmark: '<path d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4-6 4V4Z"/>',
  };
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.arrow}</svg>`;
}
function mark(item) {
  if (item.ticker) {
    const brand = resolveBrand(item, brandRegistry);
    if (brand && !failedBrandImages.has(brand.src)) return `<span class="mark company-logo" aria-hidden="true"><img src="${h(brand.src)}" alt="" decoding="async" data-company-logo></span>`;
    return `<span class="mark company-logo logo-missing" title="${t('公司标识暂缺', 'Company logo unavailable')}" aria-hidden="true">${icon('company')}</span>`;
  }
  return `<span class="mark" style="--brand:${h(item.color || '#6f8eb4')}" aria-hidden="true">${h(item.initials)}</span>`;
}
function persist() {
  try { localStorage.setItem(KEY, JSON.stringify({ language: state.language, read: state.read, saved: state.saved, notes: state.notes, followed: state.followed })); storageAvailable = true; }
  catch { storageAvailable = false; }
}
function restore() {
  try {
    const stored = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (!stored || typeof stored !== 'object') return;
    state.language = stored.language === 'en' ? 'en' : 'zh';
    for (const key of ['read', 'saved']) if (Array.isArray(stored[key])) state[key] = [...new Set(stored[key].filter(id => events.has(id)))];
    if (Array.isArray(stored.followed)) state.followed = [...new Set(stored.followed.filter(id => companies.has(id)))];
    if (stored.notes && typeof stored.notes === 'object') state.notes = Object.fromEntries(Object.entries(stored.notes).filter(([id, text]) => events.has(id) && typeof text === 'string').map(([id, text]) => [id, text.slice(0, 2000)]));
  } catch { /* Invalid saved prototype state never changes the source content. */ }
}
function toast(message) {
  clearTimeout(toastTimer);
  const node = document.querySelector('#feedback');
  node.textContent = message;
  toastTimer = setTimeout(() => { node.textContent = ''; }, 3000);
}
function storedToast(message) { toast(storageAvailable ? message : t('本机存储不可用，改动仅在当前页面保留。', 'Storage unavailable; changes remain in this session only.')); }
function rowsPerPage() { return window.innerHeight < 660 ? 4 : 5; }

// Each navigation region has one explicit sequence and stays within its hierarchy.
function sequence() {
  const item = current();
  const active = view();
  if (active.detail?.type === 'note') return { kind: 'detail', index: 0, count: 1, label: t('正在记录判断', 'Writing your note') };
  if (active.detail?.type === 'impact') return { kind: 'detail', index: 0, count: 1, label: t('持仓含义', 'Holding relevance') };
  if (active.detail?.type === 'evidence') {
    const event = eventFor(item, active.detail.eventId);
    return { kind: 'evidence', index: active.detail.index, count: event.evidence.length, label: t('证据', 'Evidence') };
  }
  if (active.tab === 'overview') return { kind: 'object', index: objects().findIndex(entry => entry.id === item.id), count: objects().length, label: state.mode === 'companies' ? t('公司', 'companies') : t('组合', 'portfolios') };
  let count;
  if (state.mode === 'companies') count = active.tab === 'changes' ? item.events.length : active.tab === 'report' ? item.report.factors.length + 1 : item.report.factors.length;
  else count = active.tab === 'holdings' ? Math.ceil((item.positions.length + 1) / rowsPerPage()) : active.tab === 'actions' ? item.actions.length : 1;
  const index = Math.min(active.pages[active.tab] || 0, Math.max(0, count - 1));
  active.pages[active.tab] = index;
  return { kind: 'page', index, count, label: ({ changes: t('变化', 'updates'), report: t('报告章节', 'report sections'), tracking: t('追踪问题', 'research questions'), holdings: t('持仓页', 'holding pages'), actions: t('动作', 'actions'), performance: t('表现', 'performance') })[active.tab] };
}
function setObject(id, direction = 1) {
  state.mode === 'companies' ? getCompany(id) : getPortfolio(id);
  if (state.selected[state.mode] === id) return false;
  state.selected[state.mode] = id;
  render({ animate: true, direction, axis: 'y' });
  return true;
}
function setMode(mode) {
  if (!['companies', 'portfolios'].includes(mode) || mode === state.mode) return false;
  state.mode = mode;
  render({ animate: true, direction: mode === 'portfolios' ? 1 : -1, axis: 'x' });
  return true;
}
function setTab(tab) {
  const choices = tabs().map(item => item[0]);
  if (!choices.includes(tab)) throw new Error(`Unknown tab: ${tab}`);
  const active = view();
  const direction = choices.indexOf(tab) >= choices.indexOf(active.tab) ? 1 : -1;
  if (active.tab === tab && !active.detail) return false;
  active.tab = tab; active.detail = null;
  render({ animate: true, direction, axis: 'x' });
  return true;
}
function step(zone, direction) {
  if (zone === 'modes') return direction > 0 ? setMode('portfolios') : setMode('companies');
  if (zone === 'objects') {
    const list = objects();
    const next = list.findIndex(item => item.id === current().id) + direction;
    return next >= 0 && next < list.length ? setObject(list[next].id, direction) : false;
  }
  if (zone === 'tabs') {
    const list = tabs();
    const next = list.findIndex(item => item[0] === view().tab) + direction;
    return next >= 0 && next < list.length ? setTab(list[next][0]) : false;
  }
  if (zone === 'content') return setPage(sequence().index + direction);
  return false;
}
function setPage(index) {
  const active = view();
  const seq = sequence();
  if (index < 0 || index >= seq.count || index === seq.index || seq.kind === 'detail') return false;
  const direction = index > seq.index ? 1 : -1;
  if (seq.kind === 'object') return setObject(objects()[index].id, direction);
  if (seq.kind === 'evidence') active.detail.index = index;
  else active.pages[active.tab] = index;
  render({ animate: true, direction, axis: 'y' });
  return true;
}
function openEvent(companyId, eventId) {
  const company = getCompany(companyId);
  eventFor(company, eventId);
  state.mode = 'companies'; state.selected.companies = companyId;
  view().tab = 'changes'; view().pages.changes = company.events.findIndex(item => item.id === eventId); view().detail = null;
  render({ animate: true, direction: 1, axis: 'x' });
}
function header() {
  return `<header class="topbar"><div class="brand"><span class="brand-symbol"><img src="assets/brand-source.jpeg" alt=""></span><span class="wordmark">uteki</span></div>
    <nav class="mode-switch" data-nav="modes" aria-label="${t('工作区，点击切换', 'Workspace, click to switch')}">${button('mode', 'companies', `${icon('company')}${t('公司研究', 'Companies')}`, state.mode === 'companies' ? 'active' : '', `aria-pressed="${state.mode === 'companies'}"`)}${button('mode', 'portfolios', `${icon('portfolio')}${t('组合管理', 'Portfolios')}`, state.mode === 'portfolios' ? 'active' : '', `aria-pressed="${state.mode === 'portfolios'}"`)}</nav>
    <div class="topbar-tools"><span class="demo">${t('设计探索 · 全部内容为示意', 'Design study · Fictional content')}</span>${button('language', '', state.language === 'zh' ? 'EN' : '中', 'language', `aria-label="${t('切换为英文界面', 'Switch to Chinese')}"`)}<span class="avatar" aria-hidden="true">R</span></div></header>`;
}
function sidebar() {
  const list = objects();
  const index = list.findIndex(item => item.id === current().id);
  const visibleCount = Math.max(3, Math.min(6, Math.floor((window.innerHeight - 245) / 68)));
  const start = Math.floor(index / visibleCount) * visibleCount;
  const visible = list.slice(start, start + visibleCount);
  return `<aside class="sidebar" data-nav="objects" aria-label="${t('对象列表，点击选择', 'Objects, click to select')}"><div class="sidebar-heading"><h2>${state.mode === 'companies' ? t('我的公司', 'My companies') : t('我的组合', 'My portfolios')}</h2>${state.mode === 'companies' ? button('discover', '', icon('plus'), 'small-action', `aria-label="${t('查看待研究公司', 'Explore a research candidate')}"`) : ''}</div><p class="list-label">${state.mode === 'companies' ? t('关注与研究', 'FOLLOWING & RESEARCH') : t('受托管理', 'DELEGATED CAPITAL')} · ${list.length}</p>
    <nav class="object-list">${visible.map(item => button('object', item.id, `${mark(item)}<span class="object-copy"><span class="object-name">${h(state.mode === 'companies' ? item.name : portfolioName(item))}</span><span class="object-description" style="display:block">${h(state.mode === 'companies' ? state.followed.includes(item.id) ? item.ticker : t('待研究 · ', 'Explore · ') + item.ticker : t('经理 ', 'Manager ') + managerName(item))}</span></span>${state.mode === 'companies' && unread(item) ? `<span class="object-badge">${unread(item)}</span>` : ''}`, `object-row ${item.id === current().id ? 'active' : ''}`, `aria-current="${item.id === current().id}"`)).join('')}</nav>
    <div class="sidebar-spacer"></div><div class="sidebar-context"><p>${state.mode === 'companies' ? t('围绕一家公司，\n让每一次变化回到你的判断。', 'A company in focus. Every change, in context.') : t('从资金的去向，\n理解每个受托决策。', 'Understand the decisions made for your capital.')}</p><small>${t('点击选择公司或组合', 'Click to select a company or portfolio')}</small></div><div class="sidebar-nav"><span>${String(index + 1).padStart(2, '0')} / ${String(list.length).padStart(2, '0')}</span><div class="arrow-pair">${button('object-step', '-1', icon('prev'), 'arrow-button', `${index === 0 ? 'disabled' : ''} aria-label="${t('上一个对象', 'Previous object')}"`)}${button('object-step', '1', icon('next'), 'arrow-button', `${index === list.length - 1 ? 'disabled' : ''} aria-label="${t('下一个对象', 'Next object')}"`)}</div></div></aside>`;
}
function objectHeader() {
  const item = current();
  return `<div class="object-header"><div class="object-title">${mark(item)}<div><h1>${h(state.mode === 'companies' ? item.name : portfolioName(item))}</h1><p>${h(state.mode === 'companies' ? `${item.ticker} · ${item.tagline}` : `${t('受托经理', 'Managed by')} ${managerName(item)} · ${t('独立委托组合', 'Delegated portfolio')}`)}</p></div></div><div class="context-label">${content.asOf.replaceAll('-', '.')}<span>${state.mode === 'companies' ? `${t('主报告', 'Main report')} ${h(item.report.version)}` : t('持仓与决策，持续了解', 'Holdings and decisions, in view')}</span></div></div>`;
}
function tabBar() {
  return `<nav class="tabs" data-nav="tabs" aria-label="${t('内容标签，点击切换', 'Content tabs, click to switch')}">${tabs().map(([id, title]) => button('tab', id, `${title}${id === 'changes' ? `<small>${current().events.length}</small>` : ''}`, `tab ${view().tab === id ? 'active' : ''}`, `aria-pressed="${view().tab === id}"`)).join('')}</nav>`;
}
function overview(company) {
  const newEvents = company.events.slice(0, 2);
  return `<div class="eyebrow"><span class="line"></span>${t('这家公司，正在发生什么', 'A COMPANY IN CONTEXT')}${status(company.status)}</div><div class="overview-head"><div class="overview-copy"><h2 class="overview-title">${h(company.headline)}</h2><p class="overview-description">${h(company.summary)}</p></div><div class="overview-number">${String(company.events.length).padStart(2, '0')}<small>${t('值得了解的变化', 'research updates')}</small></div></div>
    <section class="overview-updates"><h3 class="section-caption">${t('从变化开始', 'Start with what changed')}<span>${t('回到具体的判断', 'Follow it back to your view')}</span></h3>${newEvents.length ? `<div class="update-grid">${newEvents.map(event => button('event', event.id, `${status(event.kind)}<h3>${h(event.title)}</h3><span class="bottom"><span>${h(factorFor(company, event.factorId).label)} · ${dateShort(event.date)}</span>${icon('arrow')}</span>`, 'update-card')).join('')}</div>` : `<div class="quiet-box">${company.status === 'new' ? t('从一个好问题开始。这里已有一份初步研究，等待你进一步了解。', 'Start with a good question. An initial research view is ready to explore.') : t('当前没有改变判断的新证据。留一点空间，等待值得重新思考的信息。', 'No new evidence changes the current view. Leave room for the next meaningful update.')}</div>`}</section>
    <div class="report-strip"><div><small>${t('当前的核心判断', 'YOUR CURRENT THESIS')}</small><p>${h(company.report.thesis)}</p></div>${button('tab', 'report', `${t('主报告', 'Report')} ${icon('arrow')}`)}</div>`;
}
function changePage(company, index) {
  const event = company.events[index];
  if (!event) return emptyPage(t('判断，暂时没有新的变化。', 'No new changes to your view.'), t('当前主报告仍然可读。新的支持、挑战与待验证信息，会在这里逐条出现。', 'The main report remains available. New supporting or conflicting evidence will appear here.'), 'report');
  if (!state.read.includes(event.id)) { state.read.push(event.id); persist(); }
  const factor = factorFor(company, event.factorId);
  const saved = state.saved.includes(event.id);
  return `<div class="eyebrow">${status(event.kind)}<span>·</span>${h(event.date)}<span>·</span>${h(factor.label)}</div><h2 class="reading-title">${h(event.title)}</h2><p class="reading-summary">${h(event.summary)}</p><div class="comparison"><div><small>${t('原来怎么看', 'THE PREVIOUS VIEW')} · ${h(company.report.version)}</small><p>${h(event.before)}</p></div><div><small>${t('这次多了什么', 'WHAT IS NEW')}</small><p>${h(event.after)}</p></div></div>
    <div class="change-bottom"><section><h3>${t('与持有理由的关系', 'HOLDING RELEVANCE')}</h3>${button('impact', event.id, `${t('了解可能的影响', 'Explore the implications')} ${icon('arrow')}`)}</section><section><h3>${t('回到证据', 'BACK TO THE EVIDENCE')} · ${event.evidence.length}</h3>${button('evidence', '0', `${t('阅读证据与出处', 'Read the evidence')} ${icon('arrow')}`)}</section></div>
    <div class="actions">${button('note', event.id, state.notes[event.id] ? t('查看我的判断', 'My note') : t('记下我的判断', 'Record my view'), 'button primary')}${button('save', event.id, `${icon(saved ? 'check' : 'bookmark')}${saved ? t('已留待复核', 'Saved') : t('留待复核', 'Save')}`, 'button', `aria-pressed="${saved}"`)}${button('factor', factor.id, `${t('关联追踪', 'Follow this question')} ${icon('arrow')}`)}</div>`;
}
function reportPage(company, index) {
  const report = company.report;
  if (index === 0) return `<div class="eyebrow"><span class="line"></span>${t('主研究报告', 'MAIN RESEARCH REPORT')}<span>·</span>${h(report.version)}<span>·</span>${h(report.date)}</div><h2 class="reading-title">${h(report.title)}</h2><p class="sheet-quote">${h(report.thesis)}</p><section class="report-cover"><h3 class="section-caption">${t('支撑判断的关键因素', 'FACTORS BEHIND THE THESIS')}<span>${report.factors.length} ${t('项', 'factors')}</span></h3><div class="factor-list">${report.factors.map((factor, i) => button('page', String(i + 1), `${h(factor.label)}${status(factor.status)}`, 'factor-mini')).join('')}</div></section><div class="actions"><span class="subtle-hint">${t('逐章阅读，或点击一个因素。新证据不会自动覆盖原报告。', 'Read by section. New evidence never overwrites this report automatically.')}</span></div>`;
  const factor = report.factors[index - 1];
  return `<div class="eyebrow">${t('主报告', 'MAIN REPORT')}<span>·</span>${String(index).padStart(2, '0')}<span>·</span>${status(factor.status)}</div><h2 class="reading-title">${h(factor.label)}</h2><div class="factor-view">${h(factor.view)}</div><div class="tracking-box"><section><h3>${t('这个判断还需要回答什么', 'THE QUESTION STILL OPEN')}</h3><p>${h(factor.tracking.question)}</p></section><section><h3>${t('正在等待的材料', 'EVIDENCE STILL NEEDED')}</h3><p>${h(factor.tracking.waiting)}</p><small>${t('下次检查', 'Next check')} ${h(factor.tracking.nextDate)}</small></section></div><div class="actions">${button('factor', factor.id, `${t('进入关联追踪', 'Open tracking')} ${icon('arrow')}`, 'button')}${company.events.filter(event => event.factorId === factor.id).map(event => button('event', event.id, t('查看最新变化 →', 'View latest update →'))).join('')}</div>`;
}
function trackingPage(company, index) {
  const factor = company.report.factors[index];
  const tracker = factor.tracking;
  const stateName = ({ ready: t('已有新材料', 'New material available'), running: t('持续追踪', 'Tracking'), waiting: t('等待更新', 'Awaiting new material') })[tracker.state];
  return `<div class="eyebrow"><span class="line"></span>${t('持续追踪', 'ONGOING RESEARCH')}<span>·</span>${h(factor.label)}</div><h2 class="task-question">${h(tracker.question)}</h2><div class="task-body"><h3>${t('我们正在等待', 'WHAT WE ARE WAITING FOR')}</h3><p>${h(tracker.waiting)}</p></div><div class="task-timeline"><span></span><div><small>${t('当前进展', 'CURRENT STATUS')}</small><p>${stateName}</p></div><div><small>${t('下次检查', 'NEXT CHECK')}</small><p>${h(tracker.nextDate)}</p></div></div><div class="report-strip"><div><small>${t('来自主报告中的判断', 'FROM THE MAIN REPORT')}</small><p>${h(factor.view)}</p></div>${button('report-factor', factor.id, `${t('回到报告', 'Back to report')} ${icon('arrow')}`)}</div><div class="actions"><span class="subtle-hint">${t('这是任务状态的演示，本页没有运行后台监控。', 'Illustrative task status. No background monitoring runs in this demo.')}</span></div>`;
}
function evidencePage(company, detail) {
  const event = eventFor(company, detail.eventId);
  const evidence = event.evidence[detail.index];
  if (!evidence) throw new Error('Missing evidence');
  return `${button('close-detail', '', `${icon('back')}${t('返回这条变化', 'Back to the update')}`, 'back-link')}<h2 class="reading-title">${h(evidence.title)}</h2><div class="eyebrow" style="margin-top:17px">${h(evidence.date)}<span>·</span>${h(factorFor(company, event.factorId).label)}</div><blockquote class="evidence-quote">${h(evidence.excerpt)}</blockquote><p class="source-caption">${h(evidence.source)}</p><div class="report-strip" style="margin-top:auto"><div><small>${t('这份证据关联的变化', 'THE UPDATE THIS EVIDENCE RELATES TO')}</small><p>${h(event.title)}</p></div>${button('close-detail', '', t('回到上下文 →', 'Back to context →'))}</div>`;
}
function notePage(company, detail) {
  const event = eventFor(company, detail.eventId);
  const text = drafts.get(event.id) ?? state.notes[event.id] ?? '';
  return `${button('close-detail', '', `${icon('back')}${t('返回这条变化', 'Back to the update')}`, 'back-link')}<h2 class="reading-title">${t('这次变化，会改变你的看法吗？', 'Does this change your view?')}</h2><p class="reading-summary">${h(event.title)}</p><form class="note-area" data-event-id="${h(event.id)}"><label for="note-text">${t('记录判断，或还想确认的问题。', 'Your view, or a question still worth answering.')}</label><textarea id="note-text" name="note" maxlength="2000" required placeholder="${t('我现在的判断是……', 'My current view is…')}">${h(text)}</textarea><div class="note-actions"><button type="submit" class="button primary">${t('保存笔记', 'Save note')}</button>${button('discard-note', event.id, t('取消本次编辑', 'Discard edits'))}<span class="inline-note">${t('仅保存在本机 · 不自动修订主报告', 'Local notes · Main report unchanged')}</span></div></form>`;
}
function impactPage(company, detail) {
  const event = eventFor(company, detail.eventId);
  return `${button('close-detail', '', `${icon('back')}${t('返回这条变化', 'Back to the update')}`, 'back-link')}<h2 class="reading-title">${t('这次变化，对持有理由意味着什么？', 'What does this mean for a holding thesis?')}</h2><p class="reading-summary">${h(event.title)}</p><p class="sheet-quote">${h(event.implication)}</p><div class="report-strip" style="margin-top:auto"><div><small>${t('关联的研究因素', 'RELATED RESEARCH FACTOR')}</small><p>${h(factorFor(company, event.factorId).label)}</p></div>${button('factor', event.factorId, `${t('继续追踪这个问题', 'Follow this question')} ${icon('arrow')}`)}</div>`;
}
function portfolioOverview(item) {
  const action = item.actions[0];
  return `<div class="eyebrow"><span class="line"></span>${t('资金的去向，决策的理由', 'CAPITAL AND THE DECISIONS BEHIND IT')}</div><div class="portfolio-top"><h2 class="portfolio-strategy">${h(item.strategy)}</h2><div class="return-block"><div class="return-value">${signed(item.returnPct)}%</div><small>${t('示意累计收益', 'Illustrative period return')}</small></div></div><div class="portfolio-overview-bottom"><section class="holding-summary"><h3>${t('当前配置', 'CURRENT ALLOCATION')}</h3><div class="allocation" aria-hidden="true">${item.positions.map(position => `<span style="width:${position.weightPct}%;--brand:${h(getCompany(position.companyId).color)}"></span>`).join('')}<span style="width:${item.cashPct}%;--brand:#e1e8f3"></span></div><p>${item.positions.length} ${t('家公司', 'companies')} · ${t('现金', 'Cash')} ${item.cashPct}%</p>${button('tab', 'holdings', `${t('查看持仓', 'View holdings')} ${icon('arrow')}`)}</section><section class="latest-action"><h3>${t('最近的一个动作', 'THE LATEST DECISION')}</h3><p>${h(action.title)}</p>${button('tab', 'actions', `${t('了解原因', 'Understand why')} ${icon('arrow')}`)}</section></div><div class="report-strip"><div><small>${t('观察期间', 'OBSERVATION PERIOD')}</small><p>${h(item.period)}</p></div><span class="subtle-hint">${t('虚构经理与组合', 'Fictional manager & portfolio')}</span></div>`;
}
function holdingsPage(item, index) {
  const rows = [...item.positions, { cash: true, weightPct: item.cashPct }];
  const visible = rows.slice(index * rowsPerPage(), (index + 1) * rowsPerPage());
  return `<div class="eyebrow"><span class="line"></span>${t('组合持仓', 'PORTFOLIO HOLDINGS')}<span>·</span>${h(managerName(item))}</div><h2 class="reading-title">${t('组合，现在的样子。', 'The portfolio, as it stands.')}</h2><div class="table-wrap"><table class="holdings"><thead><tr><th scope="col">${t('公司', 'Company')}</th><th scope="col">${t('当前占比', 'Weight')}</th><th scope="col">${t('期间变化', 'Period change')}</th></tr></thead><tbody>${visible.map(position => {
    if (position.cash) return `<tr><td>${t('现金与等价物', 'Cash & equivalents')}</td><td>${position.weightPct}%</td><td>—</td></tr>`;
    const company = getCompany(position.companyId);
    return `<tr><td>${button('research', company.id, `${mark(company)}<span>${h(company.name)}<small>${h(company.ticker)} ↗</small></span>`, 'holding-name')}</td><td>${position.weightPct}%</td><td>${position.deltaPp ? `${signed(position.deltaPp)} ${t('个百分点', 'pp')}` : t('持平', 'Unchanged')}</td></tr>`;
  }).join('')}</tbody></table></div><p class="holding-subtitle">${t('占比含现金合计 100%；变化相对于观察期初。', 'Weights total 100% including cash. Changes are from the start of the period.')}</p><div class="actions"><span class="subtle-hint">${t('点击公司，进入它的研究。返回组合后保留当前位置。', 'Open a company to read its research. This portfolio keeps your place.')}</span></div>`;
}
function actionPage(item, index) {
  const action = item.actions[index];
  if (!action) return emptyPage(t('暂时没有新的动作。', 'No new actions.'), t('经理的新决策会逐条出现在这里。', 'New manager decisions will appear here.'));
  return `<div class="eyebrow"><span class="line"></span>${h(getCompany(action.companyId).name)}<span>·</span>${h(action.date)}<span>·</span>${action.status === 'done' ? t('已执行', 'Executed') : t('计划中', 'Planned')}</div><h2 class="task-question">${h(action.title)}</h2><section class="task-body"><h3>${t('经理为什么这样做', 'THE REASON BEHIND THE DECISION')}</h3><p>${h(action.reason)}</p></section><div class="report-strip" style="margin-top:auto"><div><small>${t('所属组合', 'PORTFOLIO')}</small><p>${h(portfolioName(item))} · ${t('经理', 'Manager')} ${h(managerName(item))}</p></div>${button('research', action.companyId, `${t('查看公司研究', 'Company research')} ${icon('arrow')}`)}</div>`;
}
function performancePage(item) {
  return `<div class="eyebrow"><span class="line"></span>${t('组合表现', 'PORTFOLIO PERFORMANCE')}<span>·</span>${h(portfolioName(item))}</div><div class="large-return">${signed(item.returnPct)}%</div><p class="return-period">${h(item.period)} · ${t('示意累计收益', 'Illustrative cumulative return')}</p><section class="return-explanation"><div><h3>${t('关于这组数字', 'ABOUT THIS NUMBER')}</h3><p>${t('用于讨论组合页面的信息层次。这里的收益为虚构数据，尚未接入真实账户和收益计算。', 'A fictional return to explore the page structure. Real account data and return calculations are not connected.')}</p></div><div><h3>${t('回到具体决策', 'BACK TO THE DECISIONS')}</h3><p>${t('表现需要结合持仓、动作与观察期间一起理解。', 'Read performance alongside the holdings, decisions and observation period.')}</p>${button('tab', 'actions', `${t('查看经理的动作', 'Review manager actions')} ${icon('arrow')}`)}</div></section>`;
}
function emptyPage(title, description, tab) { return `<div class="eyebrow"><span class="line"></span>UTEKI RESEARCH</div><h2 class="empty-title">${title}</h2><p class="empty-copy">${description}</p>${tab ? `<div class="actions">${button('tab', tab, t('阅读主报告 →', 'Read the main report →'), 'button')}</div>` : ''}`; }
function body() {
  const item = current();
  const active = view();
  const seq = sequence();
  if (active.detail?.type === 'note') return notePage(item, active.detail);
  if (active.detail?.type === 'impact') return impactPage(item, active.detail);
  if (active.detail?.type === 'evidence') return evidencePage(item, active.detail);
  if (state.mode === 'companies') {
    if (active.tab === 'overview') return overview(item);
    if (active.tab === 'changes') return changePage(item, seq.index);
    if (active.tab === 'report') return reportPage(item, seq.index);
    return trackingPage(item, seq.index);
  }
  if (active.tab === 'overview') return portfolioOverview(item);
  if (active.tab === 'holdings') return holdingsPage(item, seq.index);
  if (active.tab === 'actions') return actionPage(item, seq.index);
  return performancePage(item);
}
function footer() {
  const seq = sequence();
  const count = Math.max(1, seq.count);
  const hint = view().detail?.type === 'note' ? t('编辑区内可正常输入与阅读', 'Write and read normally in the editor') : seq.count <= 1 ? `${seq.label} · ${t('当前只有一项', 'One item here')}` : `${t('点击切换', 'Click to browse')} ${seq.label}`;
  return `<footer class="stage-footer" data-nav="content"><span class="navigation-hint">${icon('arrow')}${hint}</span><div class="pager"><div class="dots">${Array.from({ length: count }, (_, index) => button('page', String(index), `<span class="sr-only">${t('第', 'Page')} ${index + 1}</span>`, `page-dot ${seq.index === index ? 'active' : ''}`, `aria-label="${h(seq.label)} ${index + 1}" aria-current="${seq.index === index}"`)).join('')}</div><span class="pager-label">${seq.count ? String(seq.index + 1).padStart(2, '0') : '00'} / ${String(seq.count).padStart(2, '0')}</span><div class="arrow-pair">${button('page-step', '-1', icon('prev'), 'arrow-button', `${seq.index === 0 ? 'disabled' : ''} aria-label="${t('上一项', 'Previous item')}"`)}${button('page-step', '1', icon('next'), 'arrow-button', `${seq.index >= seq.count - 1 ? 'disabled' : ''} aria-label="${t('下一项', 'Next item')}"`)}</div></div></footer>`;
}
function render({ animate = false, direction = 1, axis = 'y' } = {}) {
  const previousPage = animate ? root.querySelector('.stage-page:not(.leaving)') : null;
  const activeElement = document.activeElement;
  const focusedRegion = activeElement?.closest?.('[data-nav]')?.dataset.nav;
  const wasStage = activeElement?.classList?.contains('stage');
  const focusedAction = activeElement?.dataset.action ? { action: activeElement.dataset.action, id: activeElement.dataset.id } : null;
  const wasNote = activeElement?.id === 'note-text';
  const selection = wasNote ? [activeElement.selectionStart, activeElement.selectionEnd] : null;
  const pageContent = body(); // Mark read only after the selected change actually renders.
  root.innerHTML = `${header()}<div class="workspace">${sidebar()}<section class="content" aria-label="${t('研究内容', 'Research content')}">${objectHeader()}${tabBar()}<div class="stage" data-nav="content" tabindex="0" aria-label="${t('阅读画布，方向键切换当前条目', 'Reading canvas, use arrow keys to switch items')}"><div class="stage-page">${pageContent}</div></div>${footer()}</section></div>`;
  document.documentElement.lang = state.language === 'en' ? 'en' : 'zh-CN';
  document.title = `Uteki · ${state.mode === 'companies' ? t('公司研究', 'Company research') : t('组合管理', 'Portfolio management')}`;
  const page = root.querySelector('.stage-page');
  // A safety fallback for browser zoom/very small windows; the document stays fixed.
  if (page.scrollHeight > page.clientHeight + 2) { page.style.overflowY = 'auto'; page.style.scrollbarWidth = 'none'; }
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (previousPage && animate && !reduceMotion && typeof page.animate === 'function') {
    previousPage.classList.add('leaving'); previousPage.setAttribute('inert', ''); previousPage.setAttribute('aria-hidden', 'true');
    for (const node of previousPage.querySelectorAll('[id]')) node.removeAttribute('id');
    root.querySelector('.stage').append(previousPage);
    const delta = axis === 'x' ? `translateX(${direction * 100}%)` : `translateY(${direction * 100}%)`;
    const exit = axis === 'x' ? `translateX(${-direction * 100}%)` : `translateY(${-direction * 100}%)`;
    const options = { duration: 360, easing: 'cubic-bezier(.22,.72,.24,1)', fill: 'both' };
    page.animate([{ transform: delta, opacity: .4 }, { transform: 'translate(0,0)', opacity: 1 }], options).finished.then(() => { page.style.willChange = 'auto'; }).catch(() => {});
    previousPage.animate([{ transform: 'translate(0,0)', opacity: 1 }, { transform: exit, opacity: .15 }], options).finished.then(() => previousPage.remove()).catch(() => previousPage.remove());
  }
  if (wasNote && root.querySelector('#note-text')) { const field = root.querySelector('#note-text'); field.focus({ preventScroll: true }); field.setSelectionRange(...selection); }
  else if (wasStage) root.querySelector('.stage')?.focus({ preventScroll: true });
  else if (focusedAction) {
    const replacement = [...root.querySelectorAll('[data-action]')].find(node => node.dataset.action === focusedAction.action && node.dataset.id === focusedAction.id);
    const regionFallback = ({ objects: '.object-row.active', tabs: '.tab.active', modes: '.mode-switch .active', content: '.stage' })[focusedRegion];
    (replacement || root.querySelector(regionFallback || '.stage'))?.focus({ preventScroll: true });
  }
}

root.addEventListener('error', event => {
  const img = event.target;
  if (!img.matches?.('img[data-company-logo]')) return;
  failedBrandImages.add(img.getAttribute('src'));
  const cell = img.parentElement;
  cell.classList.add('logo-missing');
  cell.title = t('公司标识暂缺', 'Company logo unavailable');
  cell.innerHTML = icon('company');
}, true);
root.addEventListener('keydown', event => {
  if (event.target.closest('textarea,input') || event.altKey || event.ctrlKey || event.metaKey) return;
  if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(event.key)) return;
  const zone = event.target.closest('[data-nav]')?.dataset.nav;
  if (!zone) return;
  event.preventDefault();
  if (step(zone, ['ArrowUp', 'ArrowLeft'].includes(event.key) ? -1 : 1)) {
    const focusTarget = ({ objects: '.object-row.active', tabs: '.tab.active', modes: '.mode-switch .active', content: '.stage' })[zone];
    root.querySelector(focusTarget)?.focus({ preventScroll: true });
  }
});
root.addEventListener('click', event => {
  const target = event.target.closest('button[data-action]');
  if (!target || target.disabled) return;
  const { action, id } = target.dataset;
  if (action === 'mode') return setMode(id);
  if (action === 'object') return setObject(id, objects().findIndex(item => item.id === id) > objects().findIndex(item => item.id === current().id) ? 1 : -1);
  if (action === 'object-step') return step('objects', Number(id));
  if (action === 'tab') return setTab(id);
  if (action === 'page-step') return step('content', Number(id));
  if (action === 'page') return setPage(Number(id));
  if (action === 'event') { const entry = events.get(id); if (entry) return openEvent(entry.company.id, id); }
  if (action === 'evidence') {
    const company = current(); const event = company.events[view().pages.changes || 0];
    if (!event?.evidence[Number(id)]) return;
    view().detail = { type: 'evidence', eventId: event.id, index: Number(id) };
    return render({ animate: true, axis: 'x' });
  }
  if (action === 'note') {
    eventFor(current(), id); view().detail = { type: 'note', eventId: id };
    render(); root.querySelector('#note-text')?.focus({ preventScroll: true }); return;
  }
  if (action === 'impact') { eventFor(current(), id); view().detail = { type: 'impact', eventId: id }; return render({ animate: true, axis: 'x' }); }
  if (action === 'close-detail') { view().detail = null; return render({ animate: true, direction: -1, axis: 'x' }); }
  if (action === 'discard-note') { drafts.delete(id); view().detail = null; return render(); }
  if (action === 'save') {
    eventFor(current(), id);
    state.saved = state.saved.includes(id) ? state.saved.filter(value => value !== id) : [...state.saved, id];
    persist(); render(); storedToast(state.saved.includes(id) ? t('已留待复核，阅读状态与报告版本保持独立。', 'Saved for review; reading status and report versions remain separate.') : t('已移出待复核。', 'Removed from saved items.')); return;
  }
  if (action === 'factor' || action === 'report-factor') {
    const index = current().report.factors.findIndex(factor => factor.id === id);
    if (index < 0) return;
    view().tab = action === 'factor' ? 'tracking' : 'report'; view().pages[view().tab] = action === 'factor' ? index : index + 1; view().detail = null;
    return render({ animate: true, axis: 'x' });
  }
  if (action === 'research') {
    getCompany(id); state.mode = 'companies'; state.selected.companies = id;
    return render({ animate: true, direction: -1, axis: 'x' });
  }
  if (action === 'discover') {
    const candidate = content.companies.find(company => !state.followed.includes(company.id));
    if (candidate) return setObject(candidate.id);
    return toast(t('当前示例中的公司都已加入关注。', 'All companies in this demo are followed.'));
  }
  if (action === 'language') { state.language = state.language === 'zh' ? 'en' : 'zh'; persist(); render(); }
});
root.addEventListener('input', event => {
  if (event.target.name !== 'note') return;
  const id = event.target.closest('form').dataset.eventId;
  if (events.has(id)) drafts.set(id, event.target.value.slice(0, 2000));
});
root.addEventListener('submit', event => {
  if (!event.target.matches('.note-area')) return;
  event.preventDefault();
  const id = event.target.dataset.eventId;
  const text = String(new FormData(event.target).get('note') || '').trim();
  if (!events.has(id) || !text) return;
  state.notes[id] = text.slice(0, 2000); drafts.delete(id); view().detail = null;
  persist(); render(); storedToast(t('笔记已保存，主报告未自动修订。', 'Note saved. The main report is unchanged.'));
});
let resizeTimer;
window.addEventListener('resize', () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => render(), 120); });
function validateContent() {
  const unique = (items, type) => { if (new Set(items.map(item => item.id)).size !== items.length) throw new Error(`Duplicate ${type} id`); };
  unique(content.companies, 'company'); unique(content.managers, 'portfolio');
  const allEvents = content.companies.flatMap(company => company.events); unique(allEvents, 'event'); unique(allEvents.flatMap(event => event.evidence), 'evidence');
  for (const company of content.companies) {
    brandDomain(company.website);
    if (!company.report || !/^#[0-9a-f]{6}$/i.test(company.color)) throw new Error(`Invalid company: ${company.id}`);
    unique(company.report.factors, 'factor');
    for (const event of company.events) factorFor(company, event.factorId);
  }
  for (const item of content.managers) {
    if (!Number.isFinite(item.returnPct) || !Number.isFinite(item.cashPct) || item.cashPct < 0 || item.cashPct > 100) throw new Error('Invalid portfolio values');
    if (new Set(item.positions.map(position => position.companyId)).size !== item.positions.length) throw new Error('Duplicate portfolio holding');
    for (const position of item.positions) { getCompany(position.companyId); if (!Number.isFinite(position.weightPct) || !Number.isFinite(position.deltaPp) || position.weightPct < 0 || position.weightPct > 100) throw new Error('Invalid holding'); }
    if (Math.abs(item.cashPct + item.positions.reduce((sum, position) => sum + position.weightPct, 0) - 100) > 1e-6) throw new Error('Portfolio weights must sum to 100');
    for (const action of item.actions) getCompany(action.companyId);
  }
  getCompany(state.selected.companies); getPortfolio(state.selected.portfolios);
}
try {
  validateContent();
  try {
    const response = await fetch('./assets/companies/registry.json', { cache: 'no-cache' });
    if (!response.ok) throw new Error(`Brand registry HTTP ${response.status}`);
    brandRegistry = validateBrandRegistry(await response.json());
  } catch (error) { console.warn('Company logos unavailable:', error.message); }
  restore(); render();
}
catch (error) { root.innerHTML = `<div class="loading">${t('页面暂时无法载入', 'Unable to load')}<span>${h(error.message)}</span></div>`; }
