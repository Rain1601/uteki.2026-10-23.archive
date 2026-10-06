import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
import { research, validateResearch, findCase, findReport } from './research.mjs';
import { validateBrandRegistry } from './brands.mjs';
import { KEY, createPersonalStore, formatRoute, parseRoute, routeKey, caseKey } from './reader-state.mjs';
import { resolveContext, reportRoute, comparisonRoute } from './reader-model.mjs';
import { shell, reportView, compareView, evidenceView, changesView, errorView, icon } from './reader-view.mjs';

// Historical Stage 1 regression. This executes the archived controller with real fixture/model/view/state modules.
// The small DOM/history adapter checks navigation behavior, not browser layout.
const controllerSource = (await readFile(new URL('./reader-v1.mjs', import.meta.url), 'utf8'))
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
    research, validateResearch, findCase, validateBrandRegistry,
    createPersonalStore, formatRoute, parseRoute, routeKey, caseKey,
    resolveContext, reportRoute, comparisonRoute,
    shell, reportView, compareView, evidenceView, changesView, errorView, icon,
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
    route: () => parseRoute(location.hash),
    historySnapshot: () => ({ entries, index: entryIndex }),
    click: target => { target.focus(); return dispatch('click', target); },
    change(id, value) { const node = document.getElementById(id); node.value = value; node.focus(); return dispatch('change', node); },
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); flush(); },
  };
}

const pairedRoute = {
  companyId: 'alphabet', managerId: 'north', version: 'v1', view: 'compare',
  compare: { left: { managerId: 'north', version: 'v1' }, right: { managerId: 'field', version: 'v1' } },
};

test('controller opens the explicit historical route before saved/default reading state', async () => {
  const saved = createPersonalStore(null).get();
  saved.lastRoute = { ...research.defaultRoute, companyId: 'microsoft', version: 'v1' };
  const explicit = { companyId: 'alphabet', managerId: 'north', version: 'v1', view: 'report' };
  const app = await setup({ initialHash: formatRoute(explicit), saved });
  assert.deepEqual(app.route(), explicit);
  assert.equal(app.document.getElementById('version-control').value, 'v1');
  assert.match(app.root.textContent, /历史版本/);
  assert.equal(app.root.querySelectorAll('.report-section').length, findReport('alphabet', 'north', 'v1').sections.length);
});

test('controller restores valid local reading state only when there is no explicit hash', async () => {
  const saved = createPersonalStore(null).get();
  saved.lastRoute = pairedRoute;
  saved.positions[routeKey(pairedRoute)] = { main: 0, left: 312, right: 784 };
  const app = await setup({ saved });
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.root.querySelector('[data-scroll="left"]').scrollTop, 312);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop, 784);
});

test('theme and font preferences leave both report columns and their selected versions intact', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  const left = app.root.querySelector('[data-scroll="left"]');
  const right = app.root.querySelector('[data-scroll="right"]');
  left.scrollTop = 347; right.scrollTop = 926;
  app.change('theme-control', 'dark');
  app.change('font-control', '18');
  assert.equal(app.document.documentElement.dataset.theme, 'dark');
  assert.equal(app.state().fontSize, 18);
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.root.querySelector('[data-scroll="left"]'), left);
  assert.equal(app.root.querySelector('[data-scroll="right"]'), right);
  assert.equal(left.scrollTop, 347); assert.equal(right.scrollTop, 926);
});

test('right-column evidence and browser back/forward restore both historical columns and reference focus', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  app.root.querySelector('[data-scroll="main"]').scrollTop = 37;
  app.root.querySelector('[data-scroll="left"]').scrollTop = 410;
  app.root.querySelector('[data-scroll="right"]').scrollTop = 895;
  const reference = app.root.querySelectorAll('.citation').find(node => node.id.startsWith('right-'));
  const referenceId = reference.id;
  const target = parseRoute(reference.getAttribute('href'));
  assert.equal(target.managerId, 'field'); assert.equal(target.version, 'v1');
  assert.equal(app.click(reference).defaultPrevented, true);
  assert.equal(app.route().view, 'evidence');
  assert.equal(app.route().managerId, 'field');
  app.root.querySelector('[data-scroll="main"]').scrollTop = 166;
  app.click(app.root.querySelector('[data-return]'));
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop, 37);
  assert.equal(app.root.querySelector('[data-scroll="left"]').scrollTop, 410);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop, 895);
  assert.equal(app.document.activeElement.id, referenceId);
  app.history.forward(); app.flush();
  assert.equal(app.route().view, 'evidence');
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop, 166);
  app.history.back(); app.flush();
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop, 895);
  assert.equal(app.document.activeElement.id, referenceId);
});

test('refreshing an evidence entry preserves comparison ownership and its exact history return', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  app.root.querySelector('[data-scroll="left"]').scrollTop = 205;
  app.root.querySelector('[data-scroll="right"]').scrollTop = 765;
  const reference = app.root.querySelectorAll('.citation').find(node => node.id.startsWith('right-'));
  app.click(reference);
  const refreshed = await setup({ initialHash: app.location.hash, saved: app.state(), previousHistory: app.historySnapshot() });
  assert.equal(refreshed.route().managerId, 'field');
  assert.equal(refreshed.route().version, 'v1');
  refreshed.click(refreshed.root.querySelector('[data-return]'));
  assert.deepEqual(refreshed.route(), pairedRoute);
  assert.equal(refreshed.root.querySelector('[data-scroll="left"]').scrollTop, 205);
  assert.equal(refreshed.root.querySelector('[data-scroll="right"]').scrollTop, 765);
  assert.equal(refreshed.document.activeElement.id, reference.id);
});

test('native browser back before the scroll debounce still restores the departed evidence entry on forward', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  app.root.querySelector('[data-scroll="left"]').scrollTop = 122;
  app.root.querySelector('[data-scroll="right"]').scrollTop = 789;
  const reference = app.root.querySelectorAll('.citation').find(node => node.id.startsWith('right-'));
  app.click(reference);
  const pane = app.root.querySelector('[data-scroll="main"]');
  pane.scrollTop = 433;
  app.dispatch('scroll', pane);
  // Do not flush the 180 ms scroll timer: the browser changes history first.
  app.history.back(); app.flush();
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.root.querySelector('[data-scroll="left"]').scrollTop, 122);
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop, 789);
  app.history.forward(); app.flush();
  assert.equal(app.route().view, 'evidence');
  assert.equal(app.root.querySelector('[data-scroll="main"]').scrollTop, 433);
});

test('native reading scroll is never consumed and installs no wheel or key paging listeners', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  assert.equal(app.root.listeners.has('wheel'), false);
  assert.equal(app.root.listeners.has('keydown'), false);
  assert.equal(app.windowListeners.has('wheel'), false);
  assert.equal(app.windowListeners.has('keydown'), false);
  const pane = app.root.querySelector('[data-scroll="right"]');
  pane.scrollTop = 2080;
  const event = app.dispatch('scroll', pane);
  app.flushTimers();
  assert.equal(event.defaultPrevented, false);
  assert.deepEqual(app.route(), pairedRoute);
  assert.equal(app.state().positions[routeKey(pairedRoute)].right, 2080);
});

test('direct comparison-evidence links return to the matching right-column reference', async () => {
  const published = findReport('alphabet', 'field', 'v1');
  const section = published.sections.find(item => item.citations.length);
  const evidence = {
    ...pairedRoute, managerId: 'field', view: 'evidence', origin: 'compare',
    evidenceId: section.citations[0], section: section.id,
  };
  const app = await setup({ initialHash: formatRoute(evidence) });
  app.click(app.root.querySelector('[data-return]'));
  assert.deepEqual(app.route(), pairedRoute);
  const expectedId = `right-ref-${section.id}-${section.citations[0]}`;
  assert.equal(app.document.activeElement.id, expectedId);
  assert.equal(app.document.getElementById(expectedId).didScrollIntoView, true);
});

test('invalid explicit deep links do not substitute a saved or default company/version', async () => {
  const saved = createPersonalStore(null).get();
  saved.lastRoute = research.defaultRoute;
  const hashes = [
    '#/app/companies/unknown/cases/north?version=v1&view=report',
    '#/app/companies/alphabet/cases/north?version=v900&view=report',
    '#/app/companies/alphabet/cases/north?view=report',
    '#/app/companies/alphabet/cases/north?version=v1&view=report&version=v2',
  ];
  for (const initialHash of hashes) {
    const app = await setup({ initialHash, saved });
    assert.equal(app.location.hash, initialHash);
    assert.equal(app.root.querySelectorAll('.report-section').length, 0);
    assert.match(app.root.textContent, /页面没有替换为其他公司或版本/);
  }
});

test('modified anchor clicks retain native new-tab behavior', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute) });
  const reference = app.root.querySelector('.citation');
  for (const modifiers of [{ metaKey: true }, { ctrlKey: true }, { shiftKey: true }, { button: 1 }]) {
    const event = app.dispatch('click', reference, modifiers);
    assert.equal(event.defaultPrevented, false);
    assert.deepEqual(app.route(), pairedRoute);
  }
});

test('storage failure keeps navigation and theme usable and presents an honest failure state', async () => {
  const app = await setup({ initialHash: formatRoute(pairedRoute), failStorage: true });
  assert.match(app.storageFeedback.textContent, /本机保存失败/);
  app.change('theme-control', 'dark');
  assert.equal(app.document.documentElement.dataset.theme, 'dark');
  const reference = app.root.querySelectorAll('.citation').find(node => node.id.startsWith('right-'));
  app.root.querySelector('[data-scroll="right"]').scrollTop = 544;
  app.click(reference);
  assert.equal(app.route().view, 'evidence');
  app.click(app.root.querySelector('[data-return]'));
  assert.equal(app.root.querySelector('[data-scroll="right"]').scrollTop, 544);
  assert.equal(app.document.documentElement.dataset.theme, 'dark');
  assert.match(app.storageFeedback.textContent, /本机保存失败/);
  assert.equal(app.data.has(KEY), false);
});
