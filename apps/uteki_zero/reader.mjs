import { workspace, validateWorkspace, findDocument } from './catalog.mjs';
import { validateBrandRegistry } from './brands.mjs';
import { createPersonalStore, formatRoute, parseRoute, routeKey, reportKey } from './workspace-state.mjs';
import { resolveContext, indexRoute, documentRoute, upgradeRoute } from './workspace-model.mjs';
import { shell, directoryView, portfolioView } from './workspace-shell.mjs';
import { reportView, compareView, evidenceView, changesView, errorView } from './workspace-reader-view.mjs';
import { icon } from './reader-view.mjs';

const root = document.getElementById('uteki');
const feedback = document.getElementById('feedback');
const storageFeedback = document.getElementById('storage-feedback');
const store = createPersonalStore(() => window.localStorage);
const systemTheme = matchMedia('(prefers-color-scheme: dark)');
const renderers = { report:reportView, compare:compareView, evidence:evidenceView, changes:changesView };
let route = null, context = null, registry = null, renderedHash = '', renderedEntryId = null;
const entryPositions = new Map();
let restoreFrame = 0, scrollTimer = 0, messageTimer = 0, restoring = false;
const t = (zh,en) => store.get().language === 'en' ? en : zh;
const entryId = () => crypto.randomUUID();
const historyRecord = () => history.state?.utekiReader;

function storageStatus() {
  storageFeedback.replaceChildren();
  if (!store.error) return;
  const message = document.createElement('span');
  message.textContent = t('本机保存失败，当前操作仍保留在本页。关闭页面可能丢失。','Local save failed. Changes remain in this page but may be lost when it closes.');
  const retry = document.createElement('button');
  retry.type = 'button';
  retry.textContent = t('重试保存','Retry save');
  retry.addEventListener('click', () => {
    const saved = persist({});
    if (saved) announce(t('已保存到本机','Saved on this device'));
  });
  storageFeedback.append(message,retry);
}
function persist(patch) {
  const saved = store.save(patch);
  storageStatus();
  return saved;
}
function announce(message) {
  clearTimeout(messageTimer);
  feedback.textContent = message;
  messageTimer = setTimeout(() => { feedback.textContent = ''; },4000);
}
function applyPreferences() {
  const state = store.get();
  const theme = state.theme === 'system' ? (systemTheme.matches ? 'dark' : 'light') : state.theme;
  document.documentElement.dataset.theme = theme;
  document.documentElement.lang = state.language === 'en' ? 'en' : 'zh-CN';
  document.documentElement.style.setProperty('--reading-size',`${state.fontSize}px`);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content',theme === 'dark' ? '#15181d' : '#f5f6f7');
}
function readPosition() {
  const position = {main:0};
  root.querySelectorAll('[data-scroll]').forEach(pane => { position[pane.dataset.scroll] = pane.scrollTop; });
  const active = document.activeElement;
  if (active?.id && root.contains(active)) position.focusId = active.id;
  return position;
}
function capture({updateHistory = true} = {}) {
  clearTimeout(scrollTimer);
  if (!route || restoring) return null;
  const position = readPosition(), state = store.get();
  if (renderedEntryId) entryPositions.set(renderedEntryId,position);
  persist({ lastRoute:route, positions:{...state.positions,[routeKey(route)]:position} });
  if (updateHistory && location.hash === renderedHash) {
    history.replaceState({...history.state,utekiReader:{...historyRecord(),id:historyRecord()?.id || entryId(),hash:renderedHash,position}},'',location.href);
  }
  return position;
}
function updateContents() {
  const pane = root.querySelector('[data-scroll="main"]');
  if (!pane || route?.view !== 'report') return;
  const threshold = pane.getBoundingClientRect().top + 90;
  let current = null;
  root.querySelectorAll('[data-section]').forEach(section => {
    if (section.getBoundingClientRect().top <= threshold) current = section.dataset.section;
  });
  root.querySelectorAll('.toc-link').forEach(link => {
    if (link.dataset.anchor === current) link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
}
function restore(position, section, focus = false, anchorId) {
  cancelAnimationFrame(restoreFrame);
  restoring = true;
  restoreFrame = requestAnimationFrame(() => {
    root.querySelectorAll('[data-scroll]').forEach(pane => { pane.scrollTop = position?.[pane.dataset.scroll] || 0; });
    const anchor = anchorId ? document.getElementById(anchorId) : section ? document.getElementById(`section-${section}`) : null;
    if (anchor) {
      anchor.scrollIntoView({block:'start',behavior:'instant'});
      anchor.focus({preventScroll:true});
    } else if (focus) {
      (position?.focusId && document.getElementById(position.focusId) || document.getElementById('reading-area'))?.focus({preventScroll:true});
    }
    restoring = false;
    updateContents();
    capture();
  });
}
function render(next, {position, anchor = false, focus = true, anchorId} = {}) {
  cancelAnimationFrame(restoreFrame);
  try {
    const normalized = upgradeRoute(parseRoute(formatRoute(next)));
    const resolved = resolveContext(normalized);
    route = normalized; context = resolved;
    const state = store.get();
    applyPreferences();
    root.innerHTML = shell(route,context,state,registry);
    document.getElementById('view-outlet').innerHTML = route.page === 'index' ? (route.view === 'portfolio' ? portfolioView : directoryView)(route,context,state) : renderers[route.view](route,context,state);
    document.title = route.page === 'index' ? `${context.object.name} · Uteki` : `${context.document.title} · ${context.manager.name} · Uteki`;
    root.querySelectorAll('[data-brand-image]').forEach(img => {
      img.addEventListener('error', () => { img.parentElement.innerHTML = icon('company'); },{once:true});
    });
    renderedHash = location.hash;
    renderedEntryId = historyRecord()?.id;
    const savedPosition = position ?? state.positions[routeKey(route)];
    restore(savedPosition,anchor ? route.section : undefined,focus,anchorId);
    persist({lastRoute:route,...(route.page === 'index' ? {entries:{...state.entries,[route.entry]:route}} : {})});
  } catch (error) {
    route = null; context = null; restoring = false; renderedHash = location.hash;
    root.innerHTML = errorView(error.message,store.get().language);
    applyPreferences(); storageStatus();
    document.title = t('阅读位置不可用 · Uteki','Reading location unavailable · Uteki');
    if (focus) document.getElementById('reading-area')?.focus();
  }
}
function navigate(next, {anchor = false, replace = false, position, anchorId} = {}) {
  next = upgradeRoute(next);
  const hash = formatRoute(next);
  if (hash === location.hash && !anchor) return;
  const fromPosition = capture();
  const previous = historyRecord();
  const record = {id:entryId(),hash};
  const savedPosition = store.get().positions[routeKey(next)];
  if (!position && route?.entry === next.entry && fromPosition) position = {...(savedPosition || {main:0}),sidebar:fromPosition.sidebar || 0};
  if (position) record.position = position;
  if (next.view === 'evidence' && route && route.view !== 'evidence') {
    record.from = {id:previous?.id,hash:location.hash,position:fromPosition};
  }
  history[replace ? 'replaceState' : 'pushState']({utekiReader:record},'',hash);
  render(next,{position,anchor,anchorId,focus:true});
}
function revisit() {
  if (location.hash === renderedHash) return;
  // The browser has already moved to another history entry. Save the old DOM
  // without writing its state into the newly selected history entry.
  capture({updateHistory:false});
  let next;
  try { next = upgradeRoute(parseRoute(location.hash)); }
  catch { render({}); return; }
  if (!next) {
    render({}); return;
  }
  const canonical = formatRoute(next);
  if (canonical !== location.hash) history.replaceState({utekiReader:{id:entryId(),hash:canonical}},'',canonical);
  const record = historyRecord();
  const position = record?.hash === location.hash ? (entryPositions.get(record.id) ?? record.position) : undefined;
  render(next,{position,anchor:!position && !!next.section});
}
function returnFromEvidence(fallback) {
  const from = historyRecord()?.from;
  if (from?.id && from.hash && from.hash !== location.hash) {
    // This marker is only written when an in-app link pushes the evidence entry.
    capture();
    history.back();
  } else {
    const section = route.section || context.report?.sections.find(item => item.citations.includes(route.evidenceId))?.id;
    let anchorId;
    if (section && route.origin !== 'changes') {
      const side = route.origin === 'compare' ? ['left','right'].find(key => route.compare[key].reportId === route.reportId && route.compare[key].version === route.version) : null;
      anchorId = `${side ? side + '-' : ''}ref-${section}-${route.evidenceId}`;
    }
    navigate(fallback,{anchor:!anchorId && !!fallback.section,anchorId});
  }
}
root.addEventListener('click',event => {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = event.target.closest('a,button');
  if (!target || !root.contains(target)) return;
  if (target.hasAttribute('data-skip')) {
    event.preventDefault(); document.getElementById('reading-area')?.focus(); return;
  }
  if (target.tagName === 'A') {
    const href = target.getAttribute('href');
    if (!href?.startsWith('#/app/')) return;
    event.preventDefault();
    const next = upgradeRoute(parseRoute(href));
    target.focus({preventScroll:true});
    if (target.hasAttribute('data-return')) { returnFromEvidence(next); return; }
    if (target.hasAttribute('data-anchor')) {
      const details = target.closest('details');
      if (details) details.open = false;
    }
    const position = target.hasAttribute('data-entry') && route?.page === 'reader' && next.page === 'reader' ? readPosition() : undefined;
    navigate(next,{anchor:!!next.section,position}); return;
  }
  if (target.dataset.localSection) {
    const section = document.getElementById(target.dataset.localSection);
    section?.scrollIntoView({block:'start',behavior:'instant'});
    section?.focus({preventScroll:true}); capture(); return;
  }
  const action = target.dataset.action;
  if (action === 'history-back') { history.back(); return; }
  if (!route) return;
  if (action === 'language') {
    const position = capture();
    persist({language:store.get().language === 'zh' ? 'en' : 'zh'});
    render(route,{position});
  } else if (action === 'read-version' && context.report) {
    const state = store.get();
    const saved = persist({readVersions:{...state.readVersions,[reportKey(route.reportId)]:route.version}});
    target.innerHTML = `${icon('check')}${t('此版本已标记为已读','This version is marked as read')}`;
    root.querySelector('.read-feedback').textContent = saved ? t('已保存到本机','Saved on this device') : t('仅本页生效，尚未保存','Applied here; not yet saved');
  } else if (action === 'read-event') {
    target.id = `read-event-${target.dataset.id}`;
    const position = capture(), state = store.get();
    const saved = persist({readEvents:[...new Set([...state.readEvents,target.dataset.id])]});
    render(route,{position});
    announce(saved ? t('已标记为已读；待验证的问题仍保留。','Marked as read; unresolved issues remain.') : t('已读仅本页生效，尚未保存。','Marked as read in this page; not yet saved.'));
  }
});
root.addEventListener('change',event => {
  const target = event.target;
  if (target.id === 'theme-control') { persist({theme:target.value}); applyPreferences(); return; }
  if (target.id === 'font-control') { persist({fontSize:Number(target.value)}); applyPreferences(); return; }
  if (!route) return;
  if (target.id === 'object-control') {
    navigate(indexRoute(route.entry,target.value));
  } else if (target.id === 'directory-filter' && route.page === 'index') {
    navigate({...route,filterId:target.value || undefined});
  } else if (target.id === 'version-control' && route.page === 'reader') {
    const view = route.view === 'evidence' ? 'report' : route.view;
    const next = documentRoute(context.document,target.value,route,view);
    if (view === 'compare') next.compare = {...route.compare,left:{reportId:route.reportId,version:target.value}};
    navigate(next);
  } else if (target.dataset.compareVersion && route.page === 'reader') {
    const side = target.dataset.compareVersion;
    const compare = {...route.compare,[side]:{...route.compare[side],version:target.value}};
    const next = {...documentRoute(findDocument(compare.left.reportId),compare.left.version,route,'compare'),compare};
    const position = readPosition(); position[side] = 0; delete position.focusId;
    navigate(next,{position});
  }
});
root.addEventListener('scroll',event => {
  if (!event.target.matches?.('[data-scroll]') || restoring || !route) return;
  clearTimeout(scrollTimer);
  scrollTimer = setTimeout(() => { updateContents(); capture(); },180);
},{capture:true,passive:true});
window.addEventListener('popstate',revisit);
window.addEventListener('hashchange',revisit);
window.addEventListener('pagehide',() => capture());
systemTheme.addEventListener('change',applyPreferences);
history.scrollRestoration = 'manual';

applyPreferences(); storageStatus();
try {
  validateWorkspace();
  try {
    const response = await fetch('./assets/companies/registry.json');
    if (!response.ok) throw new Error('Brand registry unavailable');
    const loaded = await response.json();
    validateBrandRegistry(loaded); registry = loaded;
  } catch {
    announce(t('本地图标暂不可用，显示公司名称。','Local icons are unavailable; company names remain visible.'));
  }
  const explicit = upgradeRoute(parseRoute(location.hash));
  const next = explicit || store.get().lastRoute || workspace.defaultRoute;
  const hash = formatRoute(next);
  const previous = historyRecord();
  history.replaceState({utekiReader:previous?.hash === hash ? previous : {id:entryId(),hash}},'',hash);
  render(next,{position:previous?.hash === hash ? previous.position : undefined,anchor:!!explicit?.section && !previous?.position,focus:false});
} catch (error) {
  root.innerHTML = errorView(error.message,store.get().language);
  renderedHash = location.hash;
}
