const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../apps/review_workbench/static/js/data_workspace.js'), 'utf8');

// Deliberately small DOM surface: enough for user actions and state isolation,
// without a browser or a dependency on the page's implementation structure.
class Element {
  constructor(tag = 'div', attrs = {}, text = '') {
    this.tagName = tag.toUpperCase(); this.attrs = {}; this.dataset = {}; this.children = [];
    this.listeners = {}; this.hidden = false; this.scrollTop = 0; this.scrollLeft = 0;
    this.value = ''; this.disabled = false; this.open = false; this._text = text;
    this.focusCalls = []; this.scrollCalls = [];
    this.style = {setProperty: (key, value) => { this.style[key] = value; }};
    for (const [key, value] of Object.entries(attrs)) this.setAttribute(key, value);
    this.classList = {add: (...names) => { this.className = [...new Set([...this.classes(), ...names])].join(' '); },
      remove: (...names) => { this.className = this.classes().filter(n => !names.includes(n)).join(' '); },
      contains: name => this.classes().includes(name),
      toggle: (name, force) => { const state = force ?? !this.classes().includes(name); this.classList[state ? 'add' : 'remove'](name); return state; }};
  }
  classes() { return (this.className || '').split(/\s+/).filter(Boolean); }
  setAttribute(key, value) {
    value = String(value); this.attrs[key] = value;
    if (key === 'id') this.id = value;
    if (key === 'class') this.className = value;
    if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
  }
  getAttribute(key) { return this.attrs[key] ?? null; }
  removeAttribute(key) { delete this.attrs[key]; }
  get parentElement() { return this.parent || null; }
  get ownerDocument() { return this.tagName === 'DOCUMENT' ? this : this.parent?.ownerDocument; }
  get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  append(...nodes) { for (const node of nodes) { node.remove(); this.children.push(node); node.parent = this; } }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); this.parent = null; }
  addEventListener(type, fn, options) { (this.listeners[type] ||= []).push({fn, once: options?.once}); }
  removeEventListener(type, fn) { this.listeners[type] = (this.listeners[type] || []).filter(item => item.fn !== fn); }
  dispatch(type, extra = {}) {
    const event = {target: this, key: '', preventDefault() { this.defaultPrevented = true; }, ...extra};
    for (const item of [...(this.listeners[type] || [])]) { item.fn(event); if (item.once) this.removeEventListener(type, item.fn); }
    return event;
  }
  querySelectorAll(selector) {
    const nodes = []; const visit = node => { for (const child of node.children) { nodes.push(child); visit(child); } }; visit(this);
    return nodes.filter(n => selector.split(',').some(s => n.matches(s.trim())));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  matches(selector) {
    if (selector.startsWith('#')) return this.id === selector.slice(1);
    if (selector.startsWith('.')) return this.classes().includes(selector.slice(1));
    const match = selector.match(/^(\w+)?\[([^\]=]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
    if (match) return (!match[1] || this.tagName === match[1].toUpperCase()) && this.getAttribute(match[2]) !== null && (match[3] === undefined || this.getAttribute(match[2]) === match[3]);
    return this.tagName === selector.toUpperCase();
  }
  closest(selector) { return this.matches(selector) ? this : this.parent?.closest(selector) || null; }
  contains(node) { return node === this || this.children.some(child => child.contains(node)); }
  focus(options = {}) { this.focusCalls.push(options); if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  scrollIntoView(options = {}) { this.scrolled = true; this.scrollCalls.push(options); }
  setPointerCapture() {}
  getBoundingClientRect() { return {left: 0, width: 1000}; }
}

function harness({selection = {dataset: 'cedar', source: 'cedar-report', tab: 'financials'}, storage = new Map(), fetcher} = {}) {
  const document = new Element('document');
  document.documentElement = new Element('html'); document.body = new Element('body');
  document.append(document.documentElement); document.documentElement.append(document.body);
  document.createElement = tag => new Element(tag);
  document.getElementById = id => document.querySelector('#' + id);
  const add = (id, tag = 'div', attrs = {}, parent = document.body, text = '') => {
    const element = new Element(tag, {...attrs, ...(id ? {id} : {})}, text); parent.append(element); return element;
  };
  add('dw-config', 'script', {}, document.body, JSON.stringify({selection, revision: 7}));
  add('dw-language', 'button'); add('dw-company-search', 'input'); add('dw-company-empty'); add('dw-message');
  const companies = ['cedar', 'harbor'].map(name => add('', 'a', {'data-company-search': name}, document.body, name));
  const reader = add('dw-reader');
  const expand = add('dw-expand-source', 'button');
  const expandLabel = add('', 'span', {'data-expand-label': ''}, expand, 'Expand reader');
  const collapseLabel = add('', 'span', {'data-collapse-label': ''}, expand, 'Return to comparison');
  collapseLabel.hidden = true;
  add('dw-divider', 'div', {'aria-valuenow': '50'});
  const frame = add('dw-source-frame', 'iframe'); frame.src = '/data-workspace/source?' + new URLSearchParams({dataset: selection.dataset || '', source: selection.source || ''});
  add('dw-source-status'); add('dw-source-context');
  const citation = add('dw-source-quote', 'details'); citation.hidden = true; add('', 'blockquote', {}, citation);
  add('dw-financial-search', 'input'); const filter = add('dw-financial-filter', 'select'); filter.value = 'all';
  const outputs = add('', 'div', {'data-scroll-key': 'outputs'});
  const table = add('', 'div', {'data-scroll-key': 'financial-table'});
  const tabs = {}; const panels = {};
  for (const name of ['original', 'financials', 'blocks', 'brief', 'process']) {
    tabs[name] = add('', 'a', {'data-tab': name}); panels[name] = add('', 'section', {'data-panel': name});
  }
  panels.financials.append(table);
  const inspector = add('dw-fact-inspector', 'section', {}, panels.financials);
  const inspectorEmpty = add('dw-inspector-empty', 'p', {}, inspector, 'Select a value to inspect');
  const closeInspector = add('dw-close-inspector', 'button', {}, inspector, 'Close details');
  const returnFact = add('dw-return-fact', 'button', {}, inspector, 'Return to value');
  closeInspector.hidden = true; returnFact.hidden = true;
  const factDetails = add('dw-fact-details', 'div', {}, inspector);
  const facts = [], details = [], rows = [];
  function fact({id, run = 'run-one', block, review = 'not_reviewed', conflict = false, label = id}) {
    const row = add('', 'tr', {'data-financial-row': '', 'data-conflict': String(conflict)}, table, label);
    const cell = add('', 'td', {}, row);
    const button = add('', 'button', {'data-fact-target': id, 'data-fact': id, 'data-run': run,
      'data-fact-label': label, 'data-fact-period': '2032-01-01 — 2032-12-31'}, cell);
    add('', 'small', {'data-review-status': review}, cell);
    const detail = add('fact-' + id, 'section', {class: 'dw-fact-detail'}, factDetails); detail.hidden = true;
    if (block) add('', 'button', {'data-locate': block, 'data-quote': 'Quoted ' + id}, detail);
    facts.push(button); details.push(detail); rows.push(row); return {button, detail, row, cell};
  }
  const first = fact({id: 'first', block: 'block-a', review: 'supported', label: 'Operating cash flow'});
  const second = fact({id: 'second', block: 'block-b', conflict: true, label: 'Cash balance'});
  const noEvidence = fact({id: 'no-evidence', label: 'Unresolved amount'});
  const base = fact({id: 'base-record', run: '', block: 'base-block', label: 'Base revenue'});
  const task = add('', 'select', {'data-task-choice': 'cash-task'}); task.value = 'run-two';
  const archive = add('', 'button', {'data-state-action': 'archive', 'data-task': 'cash-task', 'data-run': 'run-old'});
  const globalEvents = new Element();
  const location = {href: 'http://local.test/data-workspace?' + new URLSearchParams(selection), reloads: 0,
    reload() { this.reloads++; }, replace(url) { this.href = String(url); this.replaced = true; }};
  const history = {pushState(_state, _unused, url) { location.href = String(url); }, replaceState(_state, _unused, url) { location.href = String(url); }};
  const calls = [];
  const fetch = (url, options = {}) => {
    calls.push({url: String(url), options});
    if (fetcher) return fetcher(url, options);
    const params = new URL(String(url), 'http://local.test').searchParams;
    return Promise.resolve({ok: true, json: async () => ({dataset_id: selection.dataset,
      source_snapshot_id: selection.source, block_id: params.get('block'), fragment: params.get('block'),
      locator_status: 'located', notice: {zh: '原文位置已定位', en: 'Source located'}})});
  };
  vm.runInNewContext(source, {document, sessionStorage: {getItem: key => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value)}, location, history, URL, URLSearchParams, AbortController,
    fetch, addEventListener: (...args) => globalEvents.addEventListener(...args), requestAnimationFrame: fn => fn()});
  return {document, storage, location, globalEvents, calls, companies, outputs, table, tabs, panels, reader,
    facts, details, rows, first, second, noEvidence, base, task, archive, frame,
    inspector, inspectorEmpty, closeInspector, returnFact, expandLabel, collapseLabel,
    get: id => document.getElementById(id), flush: async () => { await new Promise(resolve => setImmediate(resolve)); }};
}

test('company-only view filters without selecting a source or issuing a request', () => {
  const h = harness({selection: {}});
  h.get('dw-company-search').value = 'harbor'; h.get('dw-company-search').dispatch('input');
  assert.deepEqual(h.companies.map(n => n.hidden), [true, false]);
  assert.equal(h.calls.length, 0);
});

test('fact click binds URL and evidence request to the selected material', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush();
  const current = new URL(h.location.href), fetched = new URL(h.calls[0].url, 'http://local.test');
  assert.equal(current.searchParams.get('fact'), 'first'); assert.equal(current.searchParams.get('run'), 'run-one');
  assert.equal(fetched.searchParams.get('dataset'), 'cedar'); assert.equal(fetched.searchParams.get('source'), 'cedar-report');
  assert.equal(fetched.searchParams.get('block'), 'block-a'); assert.match(h.frame.src, /#block-a$/);
  assert.equal(h.first.detail.hidden, false); assert.equal(h.second.detail.hidden, true);
});

test('source status distinguishes checking and loading, then reports the locator result after frame load', async () => {
  const h = harness(); const status = h.get('dw-source-status');
  h.first.button.dispatch('click');
  assert.equal(status.dataset.state, 'checking');
  await h.flush();
  assert.equal(status.dataset.state, 'loading');
  assert.match(h.get('dw-source-context').textContent, /Operating cash flow.*2032-01-01/);
  assert.equal(h.get('dw-source-context').hidden, false);
  h.get('dw-language').dispatch('click');
  assert.equal(status.textContent, 'Location checked; loading the original…');
  h.frame.dispatch('load');
  assert.equal(status.dataset.state, 'located');
  assert.equal(status.textContent, 'Source located');
  h.get('dw-language').dispatch('click');
  assert.equal(status.textContent, '原文位置已定位');
  h.closeInspector.dispatch('click'); h.frame.dispatch('load');
  assert.equal(status.dataset.state, 'idle');
  assert.equal(h.get('dw-source-context').hidden, true);
  assert.equal(h.get('dw-source-context').textContent, '');
});

test('unavailable source precision and source load failure are explicit statuses', async () => {
  const h = harness({fetcher: async () => ({ok: true, json: async () => ({dataset_id: 'cedar', source_snapshot_id: 'cedar-report',
    block_id: 'block-a', fragment: '', locator_status: 'unavailable', notice: {zh: '缺少原文定位', en: 'No source location'}})})});
  h.first.button.dispatch('click'); await h.flush(); h.frame.dispatch('load');
  assert.equal(h.get('dw-source-status').dataset.state, 'unavailable');
  assert.equal(h.get('dw-source-status').classList.contains('dw-locator-error'), true);
  assert.doesNotMatch(h.frame.src, /#/);
  h.first.button.dispatch('click'); await h.flush(); h.frame.dispatch('error');
  assert.equal(h.get('dw-source-status').dataset.state, 'error');
  assert.equal(h.get('dw-source-status').classList.contains('dw-locator-error'), true);
});

test('selecting values opens the fixed inspector and marks their row and cell without moving the table', async () => {
  const h = harness();
  h.table.scrollLeft = 128; h.table.scrollTop = 212; h.outputs.scrollTop = 75;
  h.first.button.focus(); h.first.button.dispatch('click'); await h.flush();
  assert.equal(h.inspector.classList.contains('has-selection'), true);
  assert.equal(h.inspectorEmpty.hidden, true);
  assert.equal(h.closeInspector.hidden, false); assert.equal(h.returnFact.hidden, false);
  assert.equal(h.first.row.classList.contains('dw-selected-row'), true);
  assert.equal(h.first.cell.classList.contains('dw-selected-cell'), true);
  assert.equal(h.document.activeElement, h.first.button);
  assert.equal(h.first.detail.scrollCalls.length, 0);
  assert.equal(h.first.button.scrollCalls.length, 0);
  assert.equal(h.table.scrollLeft, 128); assert.equal(h.table.scrollTop, 212); assert.equal(h.outputs.scrollTop, 75);

  h.second.button.focus(); h.second.button.dispatch('click'); await h.flush();
  assert.equal(h.first.row.classList.contains('dw-selected-row'), false);
  assert.equal(h.first.cell.classList.contains('dw-selected-cell'), false);
  assert.equal(h.first.button.getAttribute('aria-pressed'), 'false');
  assert.equal(h.second.row.classList.contains('dw-selected-row'), true);
  assert.equal(h.second.cell.classList.contains('dw-selected-cell'), true);
  assert.equal(h.second.button.getAttribute('aria-pressed'), 'true');
  assert.equal(h.first.detail.hidden, true); assert.equal(h.second.detail.hidden, false);
  assert.equal(h.document.activeElement, h.second.button);
  assert.equal(h.details.every(n => n.scrollCalls.length === 0), true);
});

test('closing the inspector clears evidence and URL selection while restoring value focus without scrolling', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush();
  h.location.href += '&block=block-a';
  h.table.scrollLeft = 128; h.table.scrollTop = 212;
  h.closeInspector.focus(); h.closeInspector.dispatch('click'); await h.flush();
  assert.equal(h.inspector.classList.contains('has-selection'), false);
  assert.equal(h.inspectorEmpty.hidden, false);
  assert.equal(h.closeInspector.hidden, true); assert.equal(h.returnFact.hidden, true);
  assert.equal(h.details.every(n => n.hidden), true);
  assert.equal(h.rows.every(n => !n.classList.contains('dw-selected-row')), true);
  assert.equal(h.first.cell.classList.contains('dw-selected-cell'), false);
  assert.equal(h.document.activeElement, h.first.button);
  assert.equal(h.first.button.focusCalls.at(-1).preventScroll, true);
  assert.equal(h.first.button.scrollCalls.length, 0);
  assert.equal(h.table.scrollLeft, 128); assert.equal(h.table.scrollTop, 212);
  assert.equal(new URL(h.location.href).searchParams.has('fact'), false);
  assert.equal(new URL(h.location.href).searchParams.has('block'), false);
  assert.doesNotMatch(h.frame.src, /#/);
  assert.equal(h.get('dw-source-quote').hidden, true);
});

test('only explicit return-to-value action brings the selected table value into view', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush();
  assert.equal(h.first.button.scrollCalls.length, 0);
  h.returnFact.focus(); h.returnFact.dispatch('click');
  assert.equal(h.document.activeElement, h.first.button);
  assert.equal(h.first.button.focusCalls.at(-1).preventScroll, true);
  assert.equal(h.first.button.scrollCalls.length, 1);
  assert.equal(h.first.button.scrollCalls[0].block, 'nearest');
  assert.equal(h.first.detail.hidden, false);
  assert.equal(h.first.button.getAttribute('aria-pressed'), 'true');
  assert.equal(h.first.detail.scrollCalls.length, 0);
});

test('reader expansion reports its action and is unavailable on the full-width original tab', () => {
  const h = harness(); const toggle = h.get('dw-expand-source');
  assert.equal(toggle.hidden, false); assert.equal(toggle.getAttribute('aria-pressed'), 'false');
  assert.equal(h.expandLabel.hidden, false); assert.equal(h.collapseLabel.hidden, true);
  toggle.dispatch('click');
  assert.equal(h.reader.classList.contains('dw-expanded'), true);
  assert.equal(toggle.getAttribute('aria-pressed'), 'true');
  assert.equal(h.expandLabel.hidden, true); assert.equal(h.collapseLabel.hidden, false);
  toggle.dispatch('click');
  assert.equal(h.reader.classList.contains('dw-expanded'), false);
  assert.equal(toggle.getAttribute('aria-pressed'), 'false');
  assert.equal(h.expandLabel.hidden, false); assert.equal(h.collapseLabel.hidden, true);
  h.tabs.original.dispatch('click');
  assert.equal(toggle.hidden, true);
  toggle.dispatch('click');
  assert.equal(h.reader.classList.contains('dw-expanded'), false);
  h.tabs.financials.dispatch('click');
  assert.equal(toggle.hidden, false); assert.equal(toggle.getAttribute('aria-pressed'), 'false');
});

test('base dataset fact keeps explicit base mode and does not invent a run ID', async () => {
  const h = harness({selection: {dataset: 'cedar', source: 'cedar-report', tab: 'financials', base: '1'}});
  h.base.button.dispatch('click'); await h.flush();
  const current = new URL(h.location.href);
  assert.equal(current.searchParams.get('base'), '1'); assert.equal(current.searchParams.get('run'), null);
  assert.equal(current.searchParams.get('fact'), 'base-record'); assert.match(h.frame.src, /#base-block$/);
});

test('foreign source metadata is rejected and previous highlight is removed', async () => {
  const h = harness({fetcher: async () => ({ok: true, json: async () => ({dataset_id: 'harbor', source_snapshot_id: 'harbor-report', block_id: 'block-a'})})});
  h.frame.src += '#old-evidence'; h.first.button.dispatch('click'); await h.flush();
  assert.doesNotMatch(h.frame.src, /#/); assert.match(h.frame.src, /source=cedar-report/);
  assert.equal(h.get('dw-source-status').classList.contains('dw-locator-error'), true);
});

test('late evidence responses cannot overwrite a newer fact selection', async () => {
  const pending = [];
  const h = harness({fetcher: (url, options) => new Promise(resolve => pending.push({url, options, resolve}))});
  h.first.button.dispatch('click'); h.second.button.dispatch('click');
  assert.equal(pending[0].options.signal.aborted, true);
  const response = block => ({ok: true, json: async () => ({dataset_id: 'cedar', source_snapshot_id: 'cedar-report', block_id: block,
    fragment: block, locator_status: 'located', notice: {zh: '定位', en: 'Located'}})});
  pending[1].resolve(response('block-b')); await h.flush(); pending[0].resolve(response('block-a')); await h.flush();
  assert.match(h.frame.src, /#block-b$/); assert.equal(h.second.detail.hidden, false);
});

test('closing during source lookup prevents its late response from reopening evidence', async () => {
  let pending;
  const h = harness({fetcher: (url, options) => new Promise(resolve => { pending = {url, options, resolve}; })});
  h.first.button.dispatch('click');
  h.closeInspector.dispatch('click');
  assert.equal(pending.options.signal.aborted, true);
  pending.resolve({ok: true, json: async () => ({dataset_id: 'cedar', source_snapshot_id: 'cedar-report', block_id: 'block-a',
    fragment: 'block-a', locator_status: 'located', notice: {zh: '定位', en: 'Located'}})});
  await h.flush();
  assert.equal(h.inspector.classList.contains('has-selection'), false);
  assert.equal(h.first.detail.hidden, true);
  assert.equal(h.get('dw-source-quote').hidden, true);
  assert.doesNotMatch(h.frame.src, /#/);
});

test('selecting a fact without evidence clears the previous source highlight and citation', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush(); h.noEvidence.button.dispatch('click'); await h.flush();
  assert.equal(h.noEvidence.detail.hidden, false); assert.doesNotMatch(h.frame.src, /#/);
  assert.equal(h.get('dw-source-quote').hidden, true);
});

test('popstate without a fact clears stale detail; another material requires reload', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush();
  h.location.href = 'http://local.test/data-workspace?dataset=cedar&source=cedar-report&tab=financials';
  h.globalEvents.dispatch('popstate'); await h.flush();
  assert.equal(h.details.every(n => n.hidden), true);
  assert.equal(h.facts.every(n => n.getAttribute('aria-pressed') !== 'true'), true);
  assert.doesNotMatch(h.frame.src, /#/);
  h.location.href = 'http://local.test/data-workspace?dataset=harbor&source=harbor-report&tab=financials';
  h.globalEvents.dispatch('popstate'); assert.equal(h.location.reloads, 1);
});

test('initial render restores stored offsets before tab transitions save new positions', () => {
  const storage = new Map([['uteki-data-workspace:cedar:cedar-report:financials:outputs', '[17,245]'],
    ['uteki-data-workspace:cedar:cedar-report:financials:financial-table', '[120,0]']]);
  const h = harness({storage}); assert.equal(h.outputs.scrollTop, 245); assert.equal(h.table.scrollLeft, 120);
  h.outputs.scrollTop = 300; h.tabs.blocks.dispatch('click'); h.tabs.financials.dispatch('click');
  assert.equal(h.outputs.scrollTop, 300); assert.equal(h.panels.financials.hidden, false);
});

test('review and conflict filters are material-scoped and keyboard resizing stays bounded', () => {
  const h = harness(); h.get('dw-financial-filter').value = 'conflict'; h.get('dw-financial-filter').dispatch('change');
  assert.equal(h.first.row.hidden, true); assert.equal(h.second.row.hidden, false);
  h.get('dw-financial-filter').value = 'review'; h.get('dw-financial-filter').dispatch('change');
  assert.equal(h.first.row.hidden, true); assert.equal(h.noEvidence.row.hidden, false);
  const other = harness({selection: {dataset: 'harbor', source: 'harbor-report', tab: 'financials'}, storage: h.storage});
  assert.equal(other.get('dw-financial-filter').value, 'all');
  for (let i = 0; i < 20; i++) h.get('dw-divider').dispatch('keydown', {key: 'ArrowRight'});
  assert.equal(h.get('dw-divider').getAttribute('aria-valuenow'), '75');
  for (let i = 0; i < 20; i++) h.get('dw-divider').dispatch('keydown', {key: 'ArrowLeft'});
  assert.equal(h.get('dw-divider').getAttribute('aria-valuenow'), '25');
});

test('filters retain matching inspection but clear a hidden selection and its source evidence', async () => {
  const h = harness(); h.first.button.dispatch('click'); await h.flush();
  const location = h.location.href, requestCount = h.calls.length;
  h.get('dw-financial-search').value = 'Operating'; h.get('dw-financial-search').dispatch('input');
  assert.equal(h.first.row.hidden, false); assert.equal(h.second.row.hidden, true);
  assert.equal(h.first.detail.hidden, false);
  assert.equal(h.location.href, location); assert.equal(h.calls.length, requestCount);
  assert.match(h.frame.src, /#block-a$/);

  h.get('dw-financial-search').value = ''; h.get('dw-financial-filter').value = 'conflict';
  h.get('dw-financial-filter').dispatch('change'); await h.flush();
  assert.equal(h.first.row.hidden, true); assert.equal(h.second.row.hidden, false);
  assert.equal(h.inspector.classList.contains('has-selection'), false);
  assert.equal(h.inspectorEmpty.hidden, false);
  assert.equal(h.first.detail.hidden, true); assert.equal(h.first.button.getAttribute('aria-pressed'), 'false');
  assert.equal(new URL(h.location.href).searchParams.has('fact'), false);
  assert.equal(new URL(h.location.href).searchParams.has('block'), false);
  assert.doesNotMatch(h.frame.src, /#/);
  assert.equal(h.get('dw-source-quote').hidden, true);
});

test('a persisted filter does not restore an invisible fact from a deep link or leave its evidence active', async () => {
  const storage = new Map([['uteki-data-workspace:cedar:cedar-report:financial-filter',
    JSON.stringify({query: 'Cash balance', filter: 'all'})]]);
  const h = harness({selection: {dataset: 'cedar', source: 'cedar-report', tab: 'financials', fact: 'first', run: 'run-one'}, storage});
  await h.flush();
  assert.equal(h.first.row.hidden, true);
  assert.equal(h.first.detail.hidden, true);
  assert.equal(h.inspector.classList.contains('has-selection'), false);
  assert.equal(new URL(h.location.href).searchParams.has('fact'), false);
  assert.doesNotMatch(h.frame.src, /#/);
});

test('version update sends exact scope and revision; conflict does not reload or disable controls forever', async () => {
  const h = harness({fetcher: async () => ({ok: false, status: 409, json: async () => ({error: 'conflict'})})});
  h.task.value = 'run-attempted'; h.task.dispatch('change'); await h.flush();
  const call = h.calls[0], payload = JSON.parse(call.options.body);
  assert.equal(call.url, '/api/data-workspace/state'); assert.equal(payload.action, 'select_version');
  assert.equal(payload.expected_revision, 7); assert.equal(payload.dataset_id, 'cedar');
  assert.equal(payload.source_snapshot_id, 'cedar-report'); assert.equal(payload.run_id, 'run-attempted');
  assert.equal(h.task.value, 'run-two');
  assert.equal(h.location.replaced, undefined); assert.equal(h.task.disabled, false); assert.equal(h.archive.disabled, false);
  assert.equal(h.get('dw-message').hidden, false);
});

test('precise source request forwards explicit coordinates and persists them without searching the quote', async () => {
  const h = harness({fetcher: async url => {
    const p = new URL(url, 'http://local.test').searchParams;
    return {ok: true, json: async () => ({dataset_id: 'cedar', source_snapshot_id: 'cedar-report',
      block_id: 'block-a', char_start: Number(p.get('char_start')), char_end: Number(p.get('char_end')),
      cell_row: 2, cell_column: 3, source_sha256: 'a'.repeat(64), locator_status: 'located',
      locator_precision: 'character', fragment: 'workspace-evidence', notice: {zh: '精确引用', en: 'Exact range'}})};
  }});
  const button = h.first.detail.querySelector('[data-locate]');
  for (const [key, value] of Object.entries({'char-start': '15', 'char-end': '27', 'cell-row': '2', 'cell-column': '3',
    'text-hash': 'b'.repeat(64), 'source-sha256': 'a'.repeat(64)})) button.setAttribute('data-' + key, value);
  h.first.button.dispatch('click'); await h.flush(); h.frame.dispatch('load');
  const params = new URL(h.calls[0].url, 'http://local.test').searchParams;
  assert.equal(params.get('char_start'), '15'); assert.equal(params.get('char_end'), '27');
  assert.equal(params.get('cell_row'), '2'); assert.equal(params.get('cell_column'), '3');
  assert.equal(params.get('quote'), 'Quoted first');
  assert.equal(params.get('source_sha256'), 'a'.repeat(64));
  assert.equal(h.get('dw-source-status').dataset.state, 'located');
  const saved = JSON.parse(h.storage.get('uteki-data-workspace:cedar:cedar-report:evidence'));
  assert.equal(saved.locator.charStart, '15');
  assert.equal(saved.locator.cellColumn, '3');
  assert.match(h.frame.src, /char_start=15/);
});

test('precise source request refuses silent block downgrade or different coordinates', async () => {
  for (const change of [{locator_precision: 'block'}, {char_start: 0}]) {
    const h = harness({fetcher: async () => ({ok: true, json: async () => ({dataset_id: 'cedar',
      source_snapshot_id: 'cedar-report', block_id: 'block-a', char_start: 15, char_end: 27,
      locator_status: 'located', locator_precision: 'character', fragment: 'workspace-evidence', ...change})})});
    const button = h.first.detail.querySelector('[data-locate]');
    button.setAttribute('data-char-start', '15'); button.setAttribute('data-char-end', '27');
    h.first.button.dispatch('click'); await h.flush();
    assert.equal(h.get('dw-source-status').dataset.state, 'error');
    assert.doesNotMatch(h.frame.src, /#/);
  }
});
