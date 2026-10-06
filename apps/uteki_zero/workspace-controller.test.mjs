import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { workspace, validateWorkspace, findDocument, findVersion } from './catalog.mjs';
import { validateBrandRegistry } from './brands.mjs';
import { KEY, createPersonalStore, formatRoute, parseRoute, routeKey, reportKey } from './workspace-state.mjs';
import { resolveContext, indexRoute, documentRoute, upgradeRoute, comparisonRoute } from './workspace-model.mjs';
import { shell, directoryView, portfolioView } from './workspace-shell.mjs';
import { reportView, compareView, evidenceView, changesView, errorView } from './workspace-reader-view.mjs';
import { icon } from './reader-view.mjs';

// Executes the current controller against actual catalog, model, views and personal-state modules.
// The small DOM/history adapter checks navigation behavior, not browser layout.
const controllerSource = (await readFile(new URL('./reader.mjs', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '');
const decode = value => value.replaceAll('&amp;', '&').replaceAll('&quot;', '"')
  .replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>');

class Element {
  constructor(tag, document, attributes = {}) {
    this.tagName = tag.toUpperCase(); this.document = document;
    this.attributes = {}; this.dataset = {}; this.children = []; this.parentElement = null;
    this.listeners = new Map(); this.scrollTop = 0; this._text = ''; this._html = '';
    this.style = { values: {}, setProperty(name, value) { this.values[name] = value; } };
    for (const [name, value] of Object.entries(attributes)) this.setAttribute(name, value);
  }
  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name.startsWith('data-')) this.dataset[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = String(value);
  }
  getAttribute(name) { return this.attributes[name] ?? null; }
  hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
  removeAttribute(name) { delete this.attributes[name]; }
  get id() { return this.attributes.id || ''; }
  set id(value) { this.setAttribute('id', value); }
  get value() {
    if (this._value !== undefined) return this._value;
    if (this.tagName === 'SELECT') return this.children.find(child => child.hasAttribute('selected'))?.value ?? this.children[0]?.value ?? '';
    return this.attributes.value || '';
  }
  set value(value) { this._value = value; }
  set textContent(value) { this._text = String(value); this.children = []; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._html = String(value); this.children = []; this._text = '';
    const stack = [this], voidTags = new Set(['img', 'input', 'meta', 'br', 'hr', 'link']);
    for (const match of this._html.matchAll(/<\/?[A-Za-z][^>]*>|[^<]+/g)) {
      const part = match[0];
      if (!part.startsWith('<')) { stack.at(-1)._text += decode(part); continue; }
      if (part.startsWith('</')) { if (stack.length > 1) stack.pop(); continue; }
      const tag = /^<([\w-]+)/.exec(part)[1].toLowerCase();
      const child = new Element(tag, this.document);
      const attr = part.slice(tag.length + 1, -1);
      for (const item of attr.matchAll(/([\w:-]+)(?:="([^"]*)"|='([^']*)'|=([^\s>]+))?/g)) {
        child.setAttribute(item[1], decode(item[2] ?? item[3] ?? item[4] ?? ''));
      }
      stack.at(-1).append(child);
      if (!voidTags.has(tag) && !part.endsWith('/>')) stack.push(child);
    }
  }
  append(...children) {
    for (const child of children) { child.parentElement = this; this.children.push(child); }
  }
  replaceChildren(...children) { this.children = []; this._text = ''; this.append(...children); }
  contains(target) { return target === this || this.children.some(child => child.contains(target)); }
  matches(selector) {
    if (selector.includes(',')) return selector.split(',').some(part => this.matches(part.trim()));
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector.startsWith('.')) return (this.attributes.class || '').split(/\s+/).includes(selector.slice(1));
    const attribute = /^(?:([\w-]+))?\[([^=\]]+)(?:="([^"]*)")?\]$/.exec(selector);
    if (attribute) return (!attribute[1] || this.tagName === attribute[1].toUpperCase()) &&
      this.hasAttribute(attribute[2]) && (attribute[3] === undefined || this.getAttribute(attribute[2]) === attribute[3]);
    return this.tagName === selector.toUpperCase();
  }
  closest(selector) { return this.matches(selector) ? this : this.parentElement?.closest(selector) ?? null; }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] ?? null; }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? []; listeners.push(listener); this.listeners.set(type, listeners);
  }
  focus() { this.document.activeElement = this; }
  getBoundingClientRect() { return { top: 1000, height: 300, bottom: 1300 }; }
  scrollIntoView() { this.didScrollIntoView = true; }
}

async function setup({ initialHash = '', saved, failStorage = false, previousHistory } = {}) {
  const document = {};
  document.documentElement = new Element('html', document);
  document.body = new Element('body', document);
  document.documentElement.append(document.body);
  const root = new Element('div', document, { id: 'uteki' });
  const feedback = new Element('div', document, { id: 'feedback' });
  const storageFeedback = new Element('div', document, { id: 'storage-feedback' });
  document.body.append(root, feedback, storageFeedback);
  document.documentElement.append(new Element('meta', document, { name: 'theme-color' }));
  document.activeElement = document.body;
  document.createElement = tag => new Element(tag, document);
  document.getElementById = id => document.documentElement.querySelector(`#${id}`);
  document.querySelector = selector => document.documentElement.querySelector(selector);
  const data = new Map(saved === undefined ? [] : [[KEY, JSON.stringify(saved)]]);
  const storage = {
    getItem(key) { if (failStorage) throw new Error('Storage blocked'); return data.get(key) ?? null; },
    setItem(key, value) { if (failStorage) throw new Error('QuotaExceededError'); data.set(key, value); },
  };
  const location = { hash: initialHash, get href() { return `http://localhost/uteki_zero/${this.hash}`; } };
  const windowListeners = new Map(), frames = new Map(), timers = new Map();
  let sequence = 0;
  const window = {
    localStorage: storage,
    addEventListener(type, listener) { const list = windowListeners.get(type) ?? []; list.push(listener); windowListeners.set(type, list); },
  };
  const fireWindow = type => { for (const listener of windowListeners.get(type) ?? []) listener({ type }); };
  const entries = previousHistory ? structuredClone(previousHistory.entries) : [{ hash: initialHash, state: null }];
  let entryIndex = previousHistory?.index ?? 0;
  const hashOf = url => String(url).includes('#') ? `#${String(url).split('#').slice(1).join('#')}` : '';
  const history = {
    get state() { return entries[entryIndex].state; },
    replaceState(state, _, url) { entries[entryIndex] = { state, hash: hashOf(url) }; location.hash = hashOf(url); },
    pushState(state, _, url) { entries.splice(entryIndex + 1); entries.push({ state, hash: hashOf(url) }); entryIndex++; location.hash = hashOf(url); },
    back() { if (entryIndex > 0) { entryIndex--; location.hash = entries[entryIndex].hash; fireWindow('popstate'); fireWindow('hashchange'); } },
    forward() { if (entryIndex + 1 < entries.length) { entryIndex++; location.hash = entries[entryIndex].hash; fireWindow('popstate'); fireWindow('hashchange'); } },
  };
  const systemTheme = { matches: false, listeners: [], addEventListener(_, listener) { this.listeners.push(listener); } };
  const context = vm.createContext({
    document, window, location, history, console,
    crypto: { randomUUID: () => `entry-${++sequence}` }, matchMedia: () => systemTheme,
    requestAnimationFrame(callback) { const id = ++sequence; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    setTimeout(callback) { const id = ++sequence; timers.set(id, callback); return id; },
    clearTimeout(id) { timers.delete(id); },
    fetch: async () => { throw new Error('No network in controller test'); },
    workspace, validateWorkspace, findDocument, validateBrandRegistry,
    createPersonalStore, formatRoute, parseRoute, routeKey, reportKey,
    resolveContext, indexRoute, documentRoute, upgradeRoute,
    shell, directoryView, portfolioView, reportView, compareView, evidenceView, changesView, errorView, icon,
  });
  await new vm.Script(`(async () => {\n${controllerSource}\n})()`, { filename: 'reader.mjs' }).runInContext(context);
  const flush = () => { for (let i = 0; frames.size && i < 10; i++) { const pending = [...frames.values()]; frames.clear(); pending.forEach(callback => callback()); } };
  flush();
  const dispatch = (type, target, extra = {}) => {
    const event = { type, target, button: 0, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
    for (const listener of root.listeners.get(type) ?? []) listener(event);
    flush(); return event;
  };
  return {
    root, document, location, history, windowListeners, storageFeedback, data, dispatch, flush,
    state: () => JSON.parse(data.get(KEY)),
    fireWindow,
    route: () => parseRoute(location.hash),
    historySnapshot: () => ({ entries, index: entryIndex }),
    click: target => { target.focus(); return dispatch('click', target); },
    change(id, value) { const node = document.getElementById(id); node.value = value; node.focus(); return dispatch('change', node); },
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); flush(); },
  };
}

const companyIndex = indexRoute('companies','alphabet');
const managerIndex = indexRoute('managers','north');
const reader = (reportId = 'alpha-north-main', version = 'v2', from = companyIndex) => documentRoute(findDocument(reportId), version, from);
const groupIds = app => app.root.querySelectorAll('.directory-group').map(node => node.getAttribute('aria-labelledby'));
const readStatus = (app,id) => app.document.getElementById(`open-${id}`).querySelector('.report-read-state').textContent;
function entryLink(app,entry) { return app.root.querySelector(`[data-entry="${entry}"]`); }
function tabLink(app,view) { return app.root.querySelectorAll('.view-tabs')[0].querySelectorAll('a').find(node => parseRoute(node.getAttribute('href')).view === view); }

test('company directory opens every Manager and lists independent report titles, not version rows', async () => {
  const app = await setup();
  assert.deepEqual(app.route(), workspace.defaultRoute);
  assert.deepEqual(groupIds(app), ['group-north','group-field']);
  assert.equal(app.root.querySelectorAll('.report-section').length, 0);
  assert.deepEqual(app.root.querySelectorAll('[data-open-report]').map(node=>node.dataset.openReport),
    ['alpha-north-main','alpha-north-cloud','alpha-field-main','alpha-field-capacity']);
  assert.equal(app.document.getElementById('version-control'), null);
});

test('Manager directory groups all covered companies and switching entries restores each selected directory', async () => {
  const app = await setup();
  app.click(entryLink(app,'managers'));
  assert.deepEqual(app.route(), managerIndex);
  assert.deepEqual(groupIds(app), workspace.companies.map(company=>`group-${company.id}`));
  assert.equal(app.root.querySelectorAll('[data-open-report]').length, 3);
  app.change('directory-filter','alphabet');
  assert.deepEqual(groupIds(app), ['group-alphabet']);
  assert.equal(app.route().filterId,'alphabet');
  app.click(entryLink(app,'companies'));
  assert.deepEqual(app.route(),companyIndex);
  app.click(entryLink(app,'managers'));
  assert.deepEqual(app.route(),{...managerIndex,filterId:'alphabet'});
  app.click(tabLink(app,'portfolio'));
  assert.deepEqual(app.route(),indexRoute('managers','north','portfolio'));
  assert.match(app.root.textContent,/没有已接入的组合记录/);
});

test('main and topic reports under one company and Manager open independent version sets', async () => {
  const app = await setup();
  app.click(app.document.getElementById('open-alpha-north-cloud'));
  assert.equal(app.route().reportId,'alpha-north-cloud');
  assert.equal(app.route().version,'v2');
  assert.match(app.document.title,/云业务/);
  assert.equal(app.root.querySelectorAll('.report-section').length,findVersion('alpha-north-cloud','v2').sections.length);
  app.change('version-control','v1');
  assert.equal(app.route().reportId,'alpha-north-cloud');
  assert.equal(app.route().version,'v1');
  app.click(app.root.querySelector('[data-directory-return]'));
  app.click(app.document.getElementById('open-alpha-north-main'));
  assert.equal(app.route().reportId,'alpha-north-main');
  assert.equal(app.route().version,'v2');
  assert.equal(app.root.querySelectorAll('.report-section').length,findVersion('alpha-north-main','v2').sections.length);
});

test('changing browsing entry keeps the identical report, version and reading position open', async () => {
  const explicit = reader('alpha-north-cloud','v1');
  const app = await setup({initialHash:formatRoute(explicit)});
  app.root.querySelector('[data-scroll="main"]').scrollTop = 735;
  app.click(entryLink(app,'managers'));
  assert.equal(app.route().entry,'managers');
  assert.equal(app.route().objectId,'north');
  assert.equal(app.route().reportId,explicit.reportId);
  assert.equal(app.route().version,'v1');
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop,735);
  assert.equal(app.root.querySelectorAll('[data-object]').length,workspace.managers.length);
  app.click(entryLink(app,'companies'));
  assert.equal(app.route().entry,'companies');
  assert.equal(app.route().objectId,'alphabet');
  assert.equal(app.route().reportId,explicit.reportId);
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop,735);
});

test('filtered directory to report to evidence and back restores report, filter, sidebar and focus', async () => {
  const app = await setup();
  app.change('directory-filter','north');
  const filtered={...companyIndex,filterId:'north'};
  assert.deepEqual(app.route(),filtered);
  app.root.querySelector('[data-scroll="main"]').scrollTop=244;
  app.root.querySelector('[data-scroll="sidebar"]').scrollTop=62;
  const reportLink=app.document.getElementById('open-alpha-north-cloud');
  app.click(reportLink);
  app.root.querySelector('[data-scroll="main"]').scrollTop=567;
  const citation=app.root.querySelector('.citation');
  const referenceId=citation.id;
  app.click(citation);
  assert.equal(app.route().view,'evidence');
  assert.equal(app.route().reportId,'alpha-north-cloud');
  assert.equal(app.route().filterId,'north');
  app.click(app.root.querySelector('[data-return]'));
  assert.equal(app.route().view,'report');
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop,567);
  assert.equal(app.document.activeElement.id,referenceId);
  app.click(app.root.querySelector('[data-directory-return]'));
  assert.deepEqual(app.route(),filtered);
  assert.equal(app.document.getElementById('directory-filter').value,'north');
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop,244);
  assert.equal(app.root.querySelector('[data-scroll="sidebar"]').scrollTop,62);
  assert.equal(app.document.activeElement.id,'open-alpha-north-cloud');
});

test('same report read state is shared across entries without marking its sibling topic read', async () => {
  const app=await setup();
  app.click(app.document.getElementById('open-alpha-north-main'));
  app.click(app.root.querySelector('[data-action="read-version"]'));
  assert.deepEqual(app.state().readVersions,{'alpha-north-main':'v2'});
  app.click(entryLink(app,'managers'));
  assert.match(app.root.querySelector('[data-action="read-version"]').textContent,/已标记为已读/);
  app.click(app.root.querySelector('[data-directory-return]'));
  assert.equal(readStatus(app,'alpha-north-main'),'已读');
  assert.equal(readStatus(app,'alpha-north-cloud'),'未读');
  app.click(app.document.getElementById('open-alpha-north-cloud'));
  assert.match(app.root.querySelector('[data-action="read-version"]').textContent,/标记此版本已读/);
  assert.equal(app.state().readVersions['alpha-north-cloud'],undefined);
});

test('known legacy route explicitly maps to its preserved main report and selected historical version', async () => {
  const app=await setup({initialHash:'#/app/companies/alphabet/cases/north?version=v1&view=report'});
  assert.deepEqual(app.route(),reader('alpha-north-main','v1'));
  assert.match(app.root.textContent,/历史版本/);
  assert.equal(app.document.getElementById('version-control').value,'v1');
});

test('unknown report, owner mismatch, wrong object and legacy scope never substitute a default', async () => {
  const saved=createPersonalStore(null).get(); saved.lastRoute=companyIndex;
  const valid=reader();
  const hashes=[
    formatRoute({...valid,reportId:'does-not-exist'}),
    formatRoute({...valid,managerId:'field'}),
    formatRoute({...valid,companyId:'microsoft'}),
    formatRoute({...valid,objectId:'microsoft'}),
    formatRoute({...valid,version:'v990'}),
    '#/app/companies/unknown/cases/north?version=v1&view=report',
    '#/app/reports/alpha-north-main?company=alphabet&manager=north&version=v1&entry=companies&view=report',
  ];
  for(const initialHash of hashes){
    const app=await setup({initialHash,saved});
    assert.equal(app.location.hash,initialHash);
    assert.equal(app.root.querySelectorAll('.report-section').length,0);
    assert.equal(app.root.querySelectorAll('.directory-group').length,0);
    assert.match(app.root.textContent,/页面没有替换为其他公司或版本/);
  }
});

test('comparison evidence keeps the selected Manager sidebar object and restores both exact report versions', async () => {
  const base=reader('alpha-north-main','v1',managerIndex);
  const paired=comparisonRoute(base,'alpha-field-main');
  paired.compare.right.version='v1';
  const app=await setup({initialHash:formatRoute(paired)});
  app.root.querySelector('[data-scroll="left"]').scrollTop=288;
  app.root.querySelector('[data-scroll="right"]').scrollTop=933;
  const citation=app.root.querySelectorAll('.citation').find(node=>node.id.startsWith('right-'));
  app.click(citation);
  assert.equal(app.route().managerId,'field');
  assert.equal(app.route().reportId,'alpha-field-main');
  assert.equal(app.route().objectId,'north');
  assert.equal(app.root.querySelector('[data-object="north"]').getAttribute('aria-current'),'page');
  assert.equal(app.root.querySelector('[data-object="field"]').getAttribute('aria-current'),null);
  app.click(app.root.querySelector('[data-return]'));
  assert.deepEqual(app.route(),paired);
  assert.equal(app.root.querySelector('[data-scroll="left"]').scrollTop,288);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop,933);
  assert.equal(app.document.activeElement.id,citation.id);
});

test('refreshing evidence preserves its exact history return; fast browser back preserves departing evidence position', async () => {
  const app=await setup({initialHash:formatRoute(reader('alpha-north-cloud','v1'))});
  app.root.querySelector('[data-scroll="main"]').scrollTop=389;
  const citation=app.root.querySelector('.citation'); app.click(citation);
  const refreshed=await setup({initialHash:app.location.hash,saved:app.state(),previousHistory:app.historySnapshot()});
  const pane=refreshed.root.querySelector('[data-scroll="main"]');pane.scrollTop=281;
  refreshed.dispatch('scroll',pane);
  refreshed.history.back();refreshed.flush();
  assert.equal(refreshed.route().reportId,'alpha-north-cloud');
  assert.equal(refreshed.route().view,'report');
  assert.equal(refreshed.root.querySelector('[data-scroll="main"]').scrollTop,389);
  assert.equal(refreshed.document.activeElement.id,citation.id);
  refreshed.history.forward();refreshed.flush();
  assert.equal(refreshed.route().view,'evidence');
  assert.equal(refreshed.root.querySelector('[data-scroll="main"]').scrollTop,281);
});

test('native scroll is not consumed and all report/sidebar positions persist', async () => {
  const explicit=reader();
  const app=await setup({initialHash:formatRoute(explicit)});
  for(const owner of [app.root.listeners,app.windowListeners]){
    assert.equal(owner.has('wheel'),false);assert.equal(owner.has('keydown'),false);
  }
  const main=app.root.querySelector('[data-scroll="main"]'),side=app.root.querySelector('[data-scroll="sidebar"]');
  main.scrollTop=1360;side.scrollTop=71;
  assert.equal(app.dispatch('scroll',main).defaultPrevented,false);app.flushTimers();
  assert.deepEqual(app.route(),explicit);
  assert.equal(app.state().positions[routeKey(explicit)].main,1360);
  assert.equal(app.state().positions[routeKey(explicit)].sidebar,71);
});

test('storage failures preserve navigability and in-memory reading positions with honest feedback', async () => {
  const app=await setup({initialHash:formatRoute(reader('alpha-north-cloud','v1')),failStorage:true});
  assert.match(app.storageFeedback.textContent,/本机保存失败/);
  app.change('theme-control','dark');
  const pane=app.root.querySelector('[data-scroll="main"]');pane.scrollTop=643;
  app.click(app.root.querySelector('.citation'));
  app.click(app.root.querySelector('[data-return]'));
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop,643);
  assert.equal(app.document.documentElement.dataset.theme,'dark');
  app.click(app.root.querySelector('[data-action="read-version"]'));
  assert.match(app.root.querySelector('.read-feedback').textContent,/尚未保存/);
  assert.equal(app.data.has(KEY),false);
});

test('modified clicks retain native new-tab semantics on directory and citation links', async () => {
  for(const start of [companyIndex,reader()]){
    const app=await setup({initialHash:formatRoute(start)});
    const target=app.root.querySelector('[data-open-report]') || app.root.querySelector('.citation');
    for(const extra of [{metaKey:true},{ctrlKey:true},{shiftKey:true},{button:1}]){
      assert.equal(app.dispatch('click',target,extra).defaultPrevented,false);
      assert.deepEqual(app.route(),start);
    }
  }
});

test('company filter survives inspecting another Manager in comparison and returning to the original directory', async () => {
  const directory=indexRoute('companies','alphabet','research','north');
  const app=await setup({initialHash:formatRoute(directory)});
  app.click(app.document.getElementById('open-alpha-north-main'));
  app.click(tabLink(app,'compare'));
  const citation=app.root.querySelectorAll('.citation').find(node=>node.id.startsWith('right-'));
  app.click(citation);
  assert.equal(app.route().managerId,'field');
  assert.equal(app.route().filterId,'north');
  assert.equal(app.route().objectId,'alphabet');
  assert.ok(app.root.querySelector('[data-return]'));
  app.click(app.root.querySelector('[data-return]'));
  assert.equal(app.route().view,'compare');
  app.click(app.root.querySelector('[data-directory-return]'));
  assert.deepEqual(app.route(),directory);
  assert.deepEqual(groupIds(app),['group-north']);
});

test('changing one comparison version preserves the other column and theme/font changes preserve both DOM panes', async () => {
  const paired=comparisonRoute(reader(),'alpha-field-main');
  const app=await setup({initialHash:formatRoute(paired)});
  app.root.querySelector('[data-scroll="left"]').scrollTop=318;
  app.root.querySelector('[data-scroll="right"]').scrollTop=714;
  const select=app.root.querySelector('[data-compare-version="right"]');
  select.value='v1'; app.dispatch('change',select);
  assert.equal(app.route().compare.left.version,'v2');
  assert.equal(app.route().compare.right.version,'v1');
  assert.equal(app.root.querySelector('[data-scroll="left"]').scrollTop,318);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop,0);
  const left=app.root.querySelector('[data-scroll="left"]'),right=app.root.querySelector('[data-scroll="right"]');
  right.scrollTop=640;
  app.change('theme-control','dark');app.change('font-control','18');
  assert.equal(app.root.querySelector('[data-scroll="left"]'),left);
  assert.equal(app.root.querySelector('[data-scroll="right"]'),right);
  assert.equal(left.scrollTop,318);assert.equal(right.scrollTop,640);
  assert.equal(app.state().fontSize,18);
  assert.equal(app.document.documentElement.dataset.theme,'dark');
});

test('direct comparison evidence links reconstruct both versions and focus the originating reference', async () => {
  const paired=comparisonRoute(reader('alpha-north-main','v1',managerIndex),'alpha-field-main');
  paired.compare.right.version='v1';
  const source=await setup({initialHash:formatRoute(paired)});
  const reference=source.root.querySelectorAll('.citation').find(node=>node.id.startsWith('right-'));
  const app=await setup({initialHash:reference.getAttribute('href')});
  assert.equal(app.route().objectId,'north');
  assert.equal(app.route().managerId,'field');
  app.click(app.root.querySelector('[data-return]'));
  assert.deepEqual(app.route(),paired);
  assert.equal(app.document.activeElement.id,reference.id);
  assert.equal(app.document.getElementById(reference.id).didScrollIntoView,true);
});
