import { demo } from './data.mjs';
import { validateDemo, selectChanges, unreadCount, selectTasks, changeContext } from './model.mjs';

const root = document.querySelector('#app');
const storageKey = 'uteki:attention-prototype:v1';
const changeIds = new Set(demo.changes.map(item => item.id));
const noteKinds = new Set(['keep', 'revise', 'watch']);
const noteDrafts = new Map();
const state = {
  lang: 'zh', view: 'research', companyId: null, filter: 'all',
  panel: 'tasks', selectedChangeId: null, selectedReportId: null, selectedTaskId: null,
  detailTab: 'change', managerId: 'manager-a', readIds: [], savedIds: [], notes: {}, noteOpen: false,
};
let toastTimer;
let returnFocus = null;
let storageAvailable = true;

function restore() {
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if (!saved || typeof saved !== 'object') return;
    state.lang = saved.lang === 'en' ? 'en' : 'zh';
    for (const key of ['readIds', 'savedIds']) {
      state[key] = Array.isArray(saved[key]) ? [...new Set(saved[key].filter(id => changeIds.has(id)))] : [];
    }
    if (saved.notes && typeof saved.notes === 'object') {
      state.notes = Object.fromEntries(Object.entries(saved.notes).filter(([id, note]) =>
        changeIds.has(id) && note && noteKinds.has(note.kind) && typeof note.text === 'string',
      ).map(([id, note]) => [id, { kind: note.kind, text: note.text.slice(0, 2000) }]));
    }
  } catch { /* Ignore malformed demo state; do not touch other storage. */ }
}
function persist() {
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      lang: state.lang, readIds: state.readIds, savedIds: state.savedIds, notes: state.notes,
    }));
    storageAvailable = true;
  } catch { storageAvailable = false; }
}
function t(zh, en) { return state.lang === 'en' ? en : zh; }
function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}
function itemById(items, id) {
  const item = items.find(candidate => candidate.id === id);
  if (!item) throw new Error(`Missing selected item: ${id}`);
  return item;
}
function company(id) { return itemById(demo.companies, id); }
function companyReport(id) {
  const reports = demo.reports.filter(report => report.companyId === id);
  if (reports.length !== 1) throw new Error(`Expected one report for ${id}`);
  return reports[0];
}
function kindLabel(kind) {
  return { challenge: t('原判断受挑战', 'Thesis challenged'), support: t('新增支持', 'New support'), watch: t('有待核实', 'Needs context') }[kind];
}
function taskLabel(status) {
  return { running: t('持续追踪', 'Tracking'), waiting: t('等待材料', 'Awaiting evidence'), review: t('待你复核', 'Ready for review') }[status];
}
function noteLabel(kind) {
  return { keep: t('维持判断', 'Keep thesis'), revise: t('考虑修订', 'Consider revision'), watch: t('继续观察', 'Keep watching') }[kind];
}
function signed(value) { return `${value > 0 ? '+' : ''}${value.toFixed(1)}`; }
function notice(message) {
  clearTimeout(toastTimer);
  document.querySelector('#status').textContent = message;
  toastTimer = setTimeout(() => { document.querySelector('#status').textContent = ''; }, 3200);
}
function button(action, id, label, className = 'text-button', extra = '') {
  return `<button type="button" class="${className}" data-action="${action}" data-id="${esc(id)}" ${extra}>${label}</button>`;
}
function icon(item, badge = false) {
  const count = badge ? unreadCount(demo, state.readIds, item.id) : 0;
  return `<span class="company-icon" data-company="${esc(item.id)}" aria-hidden="true">${esc(item.mark)}${count ? `<span class="unread-badge">${count}</span>` : ''}</span>`;
}
function header() {
  return `<header class="masthead">
    <a class="brand" href="./" aria-label="Uteki"><span class="drop"><img src="../logo_studio/assets/uteki-glass.jpeg" alt=""></span><span class="brand-word">uteki</span></a>
    <nav class="mode-nav" aria-label="${t('工作台视角', 'Workspace views')}">
      ${button('view', 'research', t('我的研究', 'My research'), '', `aria-pressed="${state.view === 'research'}"`)}
      ${button('view', 'managers', t('经理与组合', 'Managers & portfolios'), '', `aria-pressed="${state.view === 'managers'}"`)}
    </nav>
    <div class="header-right"><span class="prototype-label">${t('交互结构稿 · 全部内容为示意', 'Prototype · Illustrative content')}</span>${button('language', '', state.lang === 'zh' ? 'EN' : '中文', 'language', `aria-label="${t('切换为英文界面', 'Switch interface to Chinese')}"`)}</div>
  </header>`;
}
function companyStrip() {
  return `<section class="company-strip" data-scroll="companies" aria-label="${t('关注的公司', 'Followed companies')}">
    <div class="strip-label">${t('关注的公司', 'Following')}<br><small>${t('角标为未读变化', 'Badges = unread')}</small></div>
    ${button('company', '', `${t('全部', 'All')} <span class="small-count">${unreadCount(demo, state.readIds)}</span>`, 'company-chip all', `aria-pressed="${state.companyId === null}"`)}
    ${demo.companies.filter(item => item.role === 'followed').map(item => button('company', item.id,
      `${icon(item, true)}<span class="company-name">${esc(item.name)}<span class="ticker">${esc(item.ticker)}</span></span>`,
      'company-chip', `aria-pressed="${state.companyId === item.id}" aria-label="${esc(item.name)}, ${unreadCount(demo, state.readIds, item.id)} ${t('条未读变化', 'unread changes')}"`,
    )).join('')}
  </section>`;
}
function changeCard(change) {
  const context = changeContext(demo, change.id);
  const unread = !state.readIds.includes(change.id);
  const saved = state.savedIds.includes(change.id);
  return `<article class="change-card ${state.selectedChangeId === change.id && state.panel === 'change' ? 'selected' : ''}">
    ${button('change', change.id, `<div class="card-top"><span class="card-company">${esc(context.company.name)}</span>${unread ? `<span class="dot" title="${t('未读', 'Unread')}"></span>` : ''}<span class="state-label ${change.kind}">${kindLabel(change.kind)}</span><span class="card-date">${esc(change.date.slice(5).replace('-', '.'))}</span></div>
      <h3>${esc(change.title)}</h3><p class="why">${esc(change.why)}</p>`, 'change-open', `aria-label="${esc(context.company.name + ' · ' + change.title)}" aria-controls="detail-panel" aria-expanded="${state.selectedChangeId === change.id && state.panel === 'change'}"`)}
    <div class="card-footer"><span>${esc(context.factor.label)}</span><span>${change.evidence.length} ${t('份证据', 'evidence items')}</span>${state.notes[change.id] ? `<span class="card-note">${t('已记笔记', 'Note added')}</span>` : ''}
      ${button('save', change.id, saved ? t('已留待复核', 'Saved for review') : t('留待复核', 'Save for review'), 'text-button', `aria-pressed="${saved}"`)}
    </div>
  </article>`;
}
function emptyChanges() {
  const actual = selectChanges(demo, { companyId: state.companyId });
  const quiet = actual.length === 0 && state.companyId;
  return `<div class="empty"><h3>${quiet ? t('暂时没有新的判断变化', 'No new thesis changes') : t('这里暂时没有变化', 'No changes in this view')}</h3>
    <p>${quiet ? t('当前报告仍可查看。有了值得重新判断的信息，会出现在这里。', 'The current report is available. New material changes will appear here.') : t('切换筛选可以查看其他变化；已读不会自动成为已采纳。', 'Try a different filter. Reading a change does not adopt it.')}</p>
    ${quiet ? button('report', companyReport(state.companyId).id, t('查看主报告 →', 'View main report →')) : ''}</div>`;
}
function discoveries() {
  return `<section class="discoveries"><div class="section-heading"><h2>${t('值得开始研究', 'Worth exploring')}<span class="small-count">${t('2 个新线索', '2 new leads')}</span></h2></div>
    <div class="discovery-grid">${demo.companies.filter(item => item.role === 'discovery').map(item => `<article class="discovery">
      <div class="discovery-top">${icon(item)}<div><h3>${esc(item.name)}</h3><span class="ticker">${esc(item.ticker)}</span></div></div>
      <p>${esc(item.reason)}</p>${button('report', companyReport(item.id).id, t('阅读初步研究 →', 'Read initial research →'))}
    </article>`).join('')}</div></section>`;
}
function panelHeader(title, subtitle = '', closable = true) {
  return `<div class="panel-header"><div><h2 class="panel-title" tabindex="-1">${title}</h2>${subtitle ? `<p>${subtitle}</p>` : ''}</div>${closable ? button('close', '', '×', 'close', `aria-label="${t('返回追踪任务', 'Back to tracking tasks')}"`) : ''}</div>`;
}
function taskLink(task) {
  return button('task', task.id, `${esc(task.title)}<span>↗</span>`, 'mini-link');
}
function tasksPanel() {
  const tasks = selectTasks(demo, state.companyId);
  return `${panelHeader(t('正在替你追踪', 'Tracking for you'), t('每个任务，都连接一个待验证的判断。', 'Each task follows a research question.'), false)}
    ${tasks.length ? tasks.map(task => {
      const report = itemById(demo.reports, task.reportId);
      const factor = itemById(report.factors, task.factorId);
      return `<article class="task"><div class="task-top"><span>${esc(company(task.companyId).name)}</span><span class="task-status"><span class="task-indicator"></span>${taskLabel(task.status)}</span></div>
        ${button('task', task.id, `<h3>${esc(task.title)} <span class="muted">↗</span></h3><p>${esc(task.recent)}</p>`, '')}
        <div class="task-sub">${esc(factor.label)} · ${t('下次检查', 'Next check')} ${esc(task.nextCheck.slice(5).replace('-', '.'))}</div></article>`;
    }).join('') : `<div class="panel-body"><p class="muted">${t('这家公司暂无明确设定的追踪任务。', 'No tracking task is defined for this company.')}</p>${state.companyId ? button('report', companyReport(state.companyId).id, t('查看现有研究 →', 'Open current research →')) : ''}</div>`}
    <div class="panel-note">${t('新材料先成为证据。是否改变原判断，留给你在上下文里复核。', 'New material becomes evidence first. Review it in context before changing your thesis.')}</div>`;
}
function reportBody(report) {
  const related = demo.changes.filter(change => change.reportId === report.id);
  const tasks = demo.tasks.filter(task => task.reportId === report.id);
  return `<div class="detail-block"><div class="detail-label">${t('当前核心判断', 'Current thesis')}</div><p>${esc(report.thesis)}</p></div>
    <p class="report-summary muted">${esc(report.summary)}</p>
    <div class="detail-block"><div class="detail-label">${t('报告里的关键因素', 'Factors in this report')}</div>${report.factors.map(factor => `<div class="factor"><h3>${esc(factor.label)}</h3><p>${esc(factor.conclusion)}</p></div>`).join('')}</div>
    ${related.length ? `<div class="detail-block"><div class="detail-label">${t('关联的判断变化', 'Related changes')}</div>${related.map(change => button('change', change.id, `${esc(change.title)}<span>↗</span>`, 'mini-link')).join('')}</div>` : ''}
    ${tasks.length ? `<div class="detail-block"><div class="detail-label">${t('持续追踪的任务', 'Ongoing tracking')}</div>${tasks.map(taskLink).join('')}</div>` : ''}`;
}
function reportPanel() {
  const report = itemById(demo.reports, state.selectedReportId);
  return `${panelHeader(esc(report.title), `v${esc(report.version)} · ${esc(report.date)} · ${t('示例报告', 'Illustrative report')}`)}
    <div class="panel-body">${reportBody(report)}</div>
    <div class="panel-note">${t('每家公司维护一份主报告，追踪记录与专题研究围绕它积累。这份内容仅用于演示阅读关系。', 'One main report per company, with tracking records and focused research attached. This content illustrates that relationship.')}</div>`;
}
function noteMarkup(change) {
  const note = state.notes[change.id];
  const draft = noteDrafts.get(change.id) || note;
  const saved = note ? `<div class="saved-note"><strong>${t('我的笔记', 'My note')} · ${noteLabel(note.kind)}</strong>${note.text ? `<br>${esc(note.text)}` : ''}</div>` : '';
  if (!state.noteOpen) return saved;
  return `${saved}<form class="note-form" data-change-id="${esc(change.id)}"><label for="note-kind">${t('这条变化对你的判断', 'Your assessment')}</label>
    <select name="kind" id="note-kind">${['keep', 'revise', 'watch'].map(kind => `<option value="${kind}" ${kind === (draft?.kind || 'watch') ? 'selected' : ''}>${noteLabel(kind)}</option>`).join('')}</select>
    <label for="note-text">${t('记录原因（可选）', 'Reason (optional)')}</label><textarea id="note-text" name="text" maxlength="2000" placeholder="${t('还需要什么证据，才能改变你的判断？', 'What evidence would change your view?')}">${esc(draft?.text || '')}</textarea>
    <button type="submit" class="primary">${t('保存笔记', 'Save note')}</button> ${button('cancel-note', '', t('取消', 'Cancel'), 'text-button')}
    <small>${t('笔记保存在本机，不自动改写主报告。', 'Notes stay on this device and do not rewrite the main report.')}</small></form>`;
}
function changePanel() {
  const { change, company: co, report, factor, tasks } = changeContext(demo, state.selectedChangeId);
  let body;
  if (state.detailTab === 'evidence') {
    body = `<div class="detail-label">${t('证据与原判断的关系', 'Evidence and the existing thesis')}</div>${change.evidence.map(evidence => `<article class="evidence"><h3>${esc(evidence.title)}</h3>
      <span class="state-label ${evidence.stance === 'context' ? 'watch' : evidence.stance}">${({ support: t('支持', 'Supports'), challenge: t('挑战', 'Challenges'), context: t('补充背景', 'Context') })[evidence.stance]}</span>
      <blockquote>${esc(evidence.excerpt)}</blockquote><small>${esc(evidence.source)}</small></article>`).join('')}`;
  } else if (state.detailTab === 'report') {
    body = `<div class="detail-label">${esc(report.title)} · v${esc(report.version)}</div>${reportBody(report)}`;
  } else {
    body = `<div class="detail-block comparison"><div class="before"><div class="detail-label">${t('原来的判断', 'Previous view')}</div><p>${esc(change.before)}</p></div>
      <div class="after"><div class="detail-label">${t('新信息带来的变化', 'What new information changes')}</div><p>${esc(change.after)}</p></div></div>
      <div class="detail-block"><div class="detail-label">${t('为什么现在值得看', 'Why this deserves attention')}</div><p>${esc(change.why)}</p></div>
      <div class="detail-block"><div class="detail-label">${t('与持仓判断的关系', 'Relevance to a holding thesis')}</div><p>${esc(change.positionImpact)}</p></div>
      <div class="detail-block"><div class="detail-label">${t('关联主报告', 'Linked main report')}</div>${button('report', report.id, `${esc(factor.label)}<span>v${esc(report.version)} ↗</span>`, 'mini-link')}</div>
      <div class="detail-block"><div class="detail-label">${t('接下来追踪什么', 'What to follow next')}</div>${tasks.map(taskLink).join('')}</div>`;
  }
  return `${panelHeader(esc(change.title), `${esc(co.name)} · ${esc(change.date)} · ${kindLabel(change.kind)}`)}
    <nav class="detail-tabs" aria-label="${t('变化详情', 'Change details')}">${[['change', t('变化', 'Change')], ['evidence', t('证据', 'Evidence')], ['report', t('主报告', 'Main report')]].map(([id, label]) => button('tab', id, `${label}${id === 'evidence' ? ` · ${change.evidence.length}` : ''}`, '', `aria-pressed="${state.detailTab === id}"`)).join('')}</nav>
    <div class="panel-body">${body}${noteMarkup(change)}</div>
    <div class="detail-actions">${button('note', change.id, t('记下我的判断', 'Record my view'), 'primary')}${button('save', change.id, state.savedIds.includes(change.id) ? t('已留待复核', 'Saved for review') : t('留待复核', 'Save for review'), 'secondary', `aria-pressed="${state.savedIds.includes(change.id)}"`)}</div>`;
}
function taskPanel() {
  const task = itemById(demo.tasks, state.selectedTaskId);
  const report = itemById(demo.reports, task.reportId);
  const factor = itemById(report.factors, task.factorId);
  return `${panelHeader(esc(task.title), `${esc(company(task.companyId).name)} · ${taskLabel(task.status)}`)}<div class="panel-body">
    <div class="detail-block"><div class="detail-label">${t('它在验证哪个判断', 'What this task validates')}</div><p>${esc(factor.conclusion)}</p></div>
    <div class="detail-block"><div class="detail-label">${t('最近进展', 'Latest progress')}</div><p>${esc(task.recent)}</p></div>
    <div class="detail-block"><div class="detail-label">${t('还在等待什么', 'Evidence still needed')}</div><p>${esc(task.waitingFor)}</p></div>
    <div class="detail-block"><div class="detail-label">${t('下一次检查', 'Next check')}</div><p>${esc(task.nextCheck)}</p></div>
    <div class="detail-block"><div class="detail-label">${t('来源于主报告', 'From the main report')}</div>${button('report', report.id, `${esc(report.title)}<span>↗</span>`, 'mini-link')}</div>
    ${demo.changes.filter(change => change.taskIds.includes(task.id)).map(change => button('change', change.id, `${esc(change.title)}<span>↗</span>`, 'mini-link')).join('')}
    </div><div class="panel-note">${t('任务状态和日期是示意内容，本页没有运行后台追踪。', 'Task status and dates are illustrative. This page does not run background monitoring.')}</div>`;
}
function researchView() {
  const changes = selectChanges(demo, state);
  const panel = { tasks: tasksPanel, change: changePanel, report: reportPanel, task: taskPanel }[state.panel]();
  return `<div class="page-intro"><div><p class="eyebrow">${t('研究，让判断持续生长', 'Research, kept in context')}</p><h1>${t('今天，哪些判断值得再看？', 'What deserves a second look?')}</h1><p class="intro-sub">${t('从公司的变化出发，回到你的研究与判断。', 'Start with company changes. Revisit the research behind your view.')}</p></div><div class="day">${esc(demo.asOf.replaceAll('-', '.'))}<br>${t('研究工作台', 'Research workspace')}</div></div>
    ${companyStrip()}<main class="workspace"><div><section aria-label="${t('研究判断变化', 'Research changes')}"><div class="section-heading"><h2>${t('判断的变化', 'Changes to your research')}<span class="small-count">${changes.length} ${t('条', 'items')}</span></h2>
      <div class="filters" aria-label="${t('筛选变化', 'Filter changes')}">${[['all', t('全部', 'All')], ['unread', t('未读', 'Unread')], ['challenge', t('受挑战', 'Challenged')], ['saved', t('待复核', 'Saved')]].map(([id, label]) => button('filter', id, label, '', `aria-pressed="${state.filter === id}"`)).join('')}</div></div>
      <div class="feed" data-scroll="feed">${changes.length ? changes.map(changeCard).join('') : emptyChanges()}</div></section>${discoveries()}</div>
      <aside class="side-panel" id="detail-panel" data-scroll="panel" aria-label="${t('研究上下文', 'Research context')}">${panel}</aside></main>`;
}
function managersView() {
  const manager = itemById(demo.managers, state.managerId);
  return `<div class="page-intro"><div><p class="eyebrow">${t('委托决策，持续了解', 'Delegated decisions, in view')}</p><h1>${t('你的资金，正在怎样被管理？', 'How is your capital being managed?')}</h1><p class="intro-sub">${t('看组合的变化，也看经理做出判断的原因。', 'Follow changes to the portfolio, and the decisions behind them.')}</p></div><div class="day">${esc(demo.asOf.replaceAll('-', '.'))}<br>${t('委托组合', 'Delegated portfolios')}</div></div>
    <section class="manager-select" aria-label="${t('选择经理', 'Select a manager')}">${demo.managers.map(item => button('manager', item.id,
      `<div class="manager-top"><h2>${esc(item.name)}</h2><div class="return">${signed(item.returnPct)}%<small>${t('示意累计收益', 'Illustrative return')}</small></div></div><p>${esc(item.mandate)}</p><div class="manager-period">${esc(item.period)}</div>`,
      'manager-card', `aria-pressed="${state.managerId === item.id}"`,
    )).join('')}</section>
    <main class="manager-layout"><section class="holdings"><div class="section-heading"><h2>${esc(manager.name)} · ${t('持仓', 'Holdings')}</h2><span class="small-count">${t('示例组合', 'Illustrative portfolio')}</span></div>
      <p class="muted">${t('仓位变化相对于本次观察期初。', 'Weight changes are measured from the start of this period.')}</p>
      <table class="holdings-table"><thead><tr><th scope="col">${t('公司', 'Company')}</th><th scope="col">${t('当前占比', 'Weight')}</th><th scope="col">${t('变化', 'Change')}</th></tr></thead><tbody>${manager.positions.map(position => {
        const co = company(position.companyId);
        return `<tr><td>${button('holding', co.id, `${esc(co.name)}<span class="ticker">${esc(co.ticker)} ↗</span>`, 'holding-button')}</td><td class="weight">${position.weightPct}%<span class="weight-track" aria-hidden="true"><span class="weight-fill" style="width:${position.weightPct}%"></span></span></td><td>${position.changePp === 0 ? t('持平', 'Unchanged') : `${signed(position.changePp)} ${t('个百分点', 'pp')}`}</td></tr>`;
      }).join('')}</tbody></table><p class="cash-note">${t('现金与等价物', 'Cash & equivalents')} ${manager.cashPct}% · ${t('合计 100%', 'Total 100%')}</p>
      <p class="manager-disclaimer">${t('点击公司可查看同一份公司主报告。这里的仓位属于委托组合。', 'Open a company to read its main report. These holdings belong to the delegated portfolio.')}</p></section>
      <section class="manager-actions"><div class="section-heading"><h2>${t('近期决策与动作', 'Recent decisions & actions')}</h2></div>${[...manager.actions].sort((a, b) => b.date.localeCompare(a.date)).map(action => `<article class="manager-action"><small>${esc(company(action.companyId).name)} · ${esc(action.date)} &nbsp; <span class="state-label ${action.status === 'proposed' ? 'watch' : 'support'}">${action.status === 'proposed' ? t('计划中', 'Proposed') : t('已执行', 'Executed')}</span></small><h3>${esc(action.label)}</h3><p>${esc(action.reason)}</p>${button('holding', action.companyId, t('查看公司研究 →', 'View company research →'))}</article>`).join('')}</section></main>
      <p class="manager-disclaimer">${t('两位经理、组合、决策与收益均为虚构示例。真实收益的计算口径、数据来源与更新频率待接入时明确。', 'Both managers, portfolios, decisions and returns are fictional. Return methodology, sources and update frequency will be defined with real data.')}</p>`;
}
function render({ focusPanel = false, resetPanel = false, resetFeed = false } = {}) {
  const scroll = new Map([...root.querySelectorAll('[data-scroll]')].map(el => [el.dataset.scroll, [el.scrollTop, el.scrollLeft]]));
  const active = document.activeElement;
  const previous = active?.dataset.action ? { action: active.dataset.action, id: active.dataset.id } : null;
  root.innerHTML = `<div class="shell">${header()}${state.view === 'research' ? researchView() : managersView()}<footer class="page-footer"><span class="version-note">UTEKI / WORKSPACE STUDY 01</span><span>${t('阅读、收藏与笔记仅保存于本机', 'Reads, saved items and notes stay on this device')} · ${button('reset', '', t('重置演示', 'Reset demo'), '')}</span></footer></div>`;
  document.documentElement.lang = state.lang === 'en' ? 'en' : 'zh-CN';
  document.title = `Uteki · ${t('研究工作台', 'Research workspace')}`;
  for (const el of root.querySelectorAll('[data-scroll]')) {
    const [top, left] = scroll.get(el.dataset.scroll) || [0, 0];
    el.scrollTop = el.dataset.scroll === 'panel' && resetPanel || el.dataset.scroll === 'feed' && resetFeed ? 0 : top;
    el.scrollLeft = left;
  }
  if (focusPanel) root.querySelector('.panel-title')?.focus({ preventScroll: true });
  else if (previous) findControl(previous)?.focus({ preventScroll: true });
}
function findControl(target) {
  return [...root.querySelectorAll('[data-action]')].find(el => el.dataset.action === target.action && el.dataset.id === target.id);
}
function openPanel(panel, id, control) {
  if (control && !control.closest('#detail-panel')) returnFocus = { action: control.dataset.action, id: control.dataset.id };
  state.panel = panel;
  state.noteOpen = false;
  if (panel === 'change') {
    changeContext(demo, id);
    state.selectedChangeId = id;
    state.detailTab = 'change';
    if (!state.readIds.includes(id)) state.readIds.push(id);
    persist();
  }
  if (panel === 'report') { itemById(demo.reports, id); state.selectedReportId = id; }
  if (panel === 'task') { itemById(demo.tasks, id); state.selectedTaskId = id; }
  render({ focusPanel: true, resetPanel: true });
}

root.addEventListener('click', event => {
  const control = event.target.closest('button[data-action]');
  if (!control) return;
  const { action, id } = control.dataset;
  if (['change', 'report', 'task'].includes(action)) return openPanel(action, id, control);
  if (action === 'view') {
    state.view = id;
    state.noteOpen = false;
    return render();
  }
  if (action === 'company') {
    if (id) company(id);
    state.companyId = id || null; state.panel = 'tasks'; state.selectedChangeId = null; state.noteOpen = false;
    return render({ resetPanel: true, resetFeed: true });
  }
  if (action === 'filter') { state.filter = id; return render({ resetFeed: true }); }
  if (action === 'tab') { state.detailTab = id; state.noteOpen = false; return render({ resetPanel: true }); }
  if (action === 'save') {
    itemById(demo.changes, id);
    state.savedIds = state.savedIds.includes(id) ? state.savedIds.filter(value => value !== id) : [...state.savedIds, id];
    persist(); render();
    return notice(storageAvailable ? t('复核清单已更新', 'Review list updated') : t('本机存储不可用，本次状态仅临时保留', 'Storage unavailable; changes last for this session only'));
  }
  if (action === 'note') {
    state.noteOpen = true; render();
    const field = root.querySelector('#note-kind');
    field?.focus({ preventScroll: true });
    field?.scrollIntoView({ block: 'nearest', behavior: 'instant' });
    return;
  }
  if (action === 'cancel-note') { noteDrafts.delete(state.selectedChangeId); state.noteOpen = false; return render(); }
  if (action === 'close') {
    state.panel = 'tasks'; state.noteOpen = false; render({ resetPanel: true });
    if (returnFocus) findControl(returnFocus)?.focus({ preventScroll: true });
    return;
  }
  if (action === 'manager') { itemById(demo.managers, id); state.managerId = id; return render(); }
  if (action === 'holding') {
    state.view = 'research'; state.companyId = id; state.filter = 'all';
    return openPanel('report', companyReport(id).id);
  }
  if (action === 'language') { state.lang = state.lang === 'zh' ? 'en' : 'zh'; persist(); return render(); }
  if (action === 'reset') {
    noteDrafts.clear();
    state.readIds = []; state.savedIds = []; state.notes = {}; state.filter = 'all'; state.companyId = null;
    state.panel = 'tasks'; state.selectedChangeId = null; state.noteOpen = false;
    persist(); render({ resetPanel: true, resetFeed: true });
    return notice(storageAvailable ? t('演示阅读状态已重置', 'Demo reading state reset') : t('本机存储不可用，仅重置本次状态', 'Storage unavailable; only this session was reset'));
  }
});
function rememberDraft(event) {
  const form = event.target.closest('.note-form');
  if (!form) return;
  const values = new FormData(form);
  const kind = values.get('kind');
  if (!changeIds.has(form.dataset.changeId) || !noteKinds.has(kind)) return;
  noteDrafts.set(form.dataset.changeId, { kind, text: String(values.get('text') || '').slice(0, 2000) });
}
root.addEventListener('input', rememberDraft);
root.addEventListener('change', rememberDraft);
root.addEventListener('submit', event => {
  if (!event.target.matches('.note-form')) return;
  event.preventDefault();
  const form = event.target;
  const id = form.dataset.changeId;
  itemById(demo.changes, id);
  const values = new FormData(form);
  const kind = values.get('kind');
  if (!noteKinds.has(kind)) return;
  state.notes[id] = { kind, text: String(values.get('text') || '').trim().slice(0, 2000) };
  noteDrafts.delete(id);
  state.noteOpen = false;
  persist(); render();
  notice(storageAvailable ? t('笔记已保存，主报告保持原版本', 'Note saved; the main report version is unchanged') : t('本机存储不可用，笔记仅临时保留', 'Storage unavailable; note kept for this session only'));
});
root.addEventListener('keydown', event => {
  if (event.key !== 'Escape' || state.panel === 'tasks' || state.noteOpen) return;
  state.panel = 'tasks'; render({ resetPanel: true });
  if (returnFocus) findControl(returnFocus)?.focus({ preventScroll: true });
});

try {
  validateDemo(demo);
  restore();
  render();
} catch (error) {
  root.innerHTML = `<div class="initial"><h1>结构稿暂时无法载入</h1><p>${esc(error.message)}</p><p>请刷新页面重试。示例研究尚未接入真实数据。</p></div>`;
}
