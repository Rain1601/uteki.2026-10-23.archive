import test from 'node:test';
import assert from 'node:assert/strict';
import { KEY, formatRoute, parseRoute, routeKey, caseKey, createPersonalStore } from './reader-state.mjs';

const report = { companyId: 'issuer-a', managerId: 'manager-growth', version: 'v1.2', view: 'report' };
const comparison = {
  ...report, view: 'compare', section: 'investment-thesis',
  compare: {
    left: { managerId: 'manager-growth', version: 'v1.2' },
    right: { managerId: 'manager-quality', version: 'v2' },
  },
};

function memoryStorage(raw) {
  const values = new Map(raw === undefined ? [] : [[KEY, raw]]);
  const reads = [];
  return {
    reads, values,
    getItem(key) { reads.push(key); return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
  };
}

test('report, changes, comparison and evidence routes round-trip without inferred scope', () => {
  const cases = [
    report,
    { ...report, version: null },
    { ...report, view: 'changes', section: 'change-01' },
    comparison,
    { ...comparison, view: 'evidence', evidenceId: 'material-01', origin: 'compare' },
    { ...report, view: 'evidence', evidenceId: 'material-02', origin: 'report', section: 'thesis' },
    { ...report, view: 'evidence', evidenceId: 'material-03', origin: 'changes' },
    { ...report, companyId: '公司甲', managerId: 'manager:income', version: 'v1+review' },
  ];
  for (const route of cases) {
    assert.deepEqual(parseRoute(formatRoute(route)), route);
    assert.deepEqual(parseRoute(formatRoute(route).slice(1)), route);
  }
  assert.equal(parseRoute(''), null);
  assert.equal(parseRoute('#'), null);
  assert.equal(formatRoute({ ...report, version: null }),
    '#/app/companies/issuer-a/cases/manager-growth?version=researching&view=report');
});

test('unknown entity identifiers remain explicit for the data layer to validate', () => {
  const route = { companyId: 'unknown-company', managerId: 'unknown-manager', version: 'v99', view: 'report' };
  assert.deepEqual(parseRoute(formatRoute(route)), route);
});

test('missing scopes, duplicate or unknown parameters and malformed encodings fail explicitly', () => {
  const path = '#/app/companies/issuer-a/cases/manager-growth';
  const invalid = [
    '#/app/companies/', '#/app/companies/issuer-a/cases/',
    `${path}?view=report`, `${path}?version=v1`, `${path}?version=&view=report`,
    `${path}?version=v1&view=unknown`, `${path}?version=v1&view=report&view=changes`,
    `${path}?version=v1&view=report&%76ersion=v2`,
    `${path}?version=v1&view=report&surprise=1`,
    `${path}?version=v1&view=evidence`,
    `${path}?version=v1&view=compare`,
    `${path}?version=v1&view=report&section=%`,
    `${path}?version=v1&view=report&section=%FF`,
    `${path}?version=v1&view=report&section=%00`,
    `${path}?version=v1&view=report#other`,
    '#/app/companies/issuer%2Fa/cases/manager-growth?version=v1&view=report',
    '#/app/companies/../cases/manager-growth?version=v1&view=report',
  ];
  for (const hash of invalid) assert.throws(() => parseRoute(hash), /Invalid reader route/, hash);
  for (const route of [
    { ...report, companyId: '' }, { ...report, managerId: undefined },
    { ...report, version: undefined }, { ...report, version: 'researching' },
    { ...report, version: ' ' }, { ...report, evidenceId: 'evidence-1' },
  ]) assert.throws(() => formatRoute(route), /Invalid reader route/);
});

test('evidence retains both Manager versions and origin for an exact comparison return', () => {
  const evidence = { ...comparison, view: 'evidence', evidenceId: 'source-row-03', origin: 'compare' };
  const loaded = parseRoute(formatRoute(evidence));
  const { evidenceId, origin, ...context } = loaded;
  assert.equal(evidenceId, 'source-row-03');
  const restored = { ...context, view: origin };
  assert.deepEqual(restored, comparison);
  assert.equal(routeKey(restored), routeKey(comparison));
  assert.throws(() => parseRoute(formatRoute(evidence).replace('&rightVersion=v2', '')), /incomplete comparison/);
  assert.throws(() => formatRoute({ ...evidence, compare: undefined }), /comparison context/);
  assert.throws(() => formatRoute({ ...evidence, origin: 'report' }), /comparison context/);
});

test('position and case keys distinguish entities, versions and compare sides but ignore anchors', () => {
  assert.equal(routeKey({ ...report, section: 'first' }), routeKey({ ...report, section: 'second' }));
  assert.notEqual(routeKey(report), routeKey({ ...report, companyId: 'issuer-b' }));
  assert.notEqual(routeKey(report), routeKey({ ...report, managerId: 'manager-quality' }));
  assert.notEqual(routeKey(report), routeKey({ ...report, version: 'v1.3' }));
  assert.notEqual(routeKey(comparison), routeKey({ ...comparison, compare: {
    left: comparison.compare.right, right: comparison.compare.left,
  } }));
  assert.equal(caseKey('issuer-a', 'manager-growth'), '["issuer-a","manager-growth"]');
  assert.notEqual(caseKey('a:b', 'c'), caseKey('a', 'b:c'));
  assert.throws(() => caseKey('', 'manager-growth'));
});

test('preferences, exact return positions and independent read/saved state persist in the v2 key', () => {
  const storage = memoryStorage();
  storage.values.set('uteki.snap-workspace.v1', JSON.stringify({ language: 'en' }));
  const store = createPersonalStore(storage);
  assert.deepEqual(store.get(), {
    theme: 'system', language: 'zh', fontSize: 17, lastRoute: null,
    positions: {}, readVersions: {}, readEvents: [], savedEvents: [], notes: {},
  });
  const position = { main: 321.5, left: 120, right: 920, focusId: 'source-row-03' };
  assert.equal(store.save({
    theme: 'dark', language: 'en', fontSize: 18, lastRoute: comparison,
    positions: { [routeKey(comparison)]: position },
    readVersions: { [caseKey('issuer-a', 'manager-growth')]: 'v1.2' },
    readEvents: ['event-one'], savedEvents: ['event-two'], notes: { 'case:one': '待核对新证据。' },
  }), true);
  assert.equal(store.error, null);
  const restored = createPersonalStore(storage);
  assert.deepEqual(restored.get(), store.get());
  assert.deepEqual(restored.get().positions[routeKey(comparison)], position);
  assert.deepEqual(storage.reads, [KEY, KEY]);
  const outside = restored.get();
  outside.positions[routeKey(comparison)].main = 0;
  outside.readEvents.push('injected-event');
  assert.equal(restored.get().positions[routeKey(comparison)].main, 321.5);
  assert.deepEqual(restored.get().readEvents, ['event-one']);
});

test('stored fields are validated independently and malformed positions never cross report scopes', () => {
  const source = {
    theme: 'purple', language: 'en', fontSize: 200,
    lastRoute: { companyId: 'issuer-a', view: 'report' },
    positions: {
      [routeKey(report)]: { main: 23, left: -3, right: '40', focusId: 'citation-1' },
      [routeKey({ ...report, version: 'v2' })]: { main: -2 },
      [formatRoute({ ...report, section: 'not-a-position-key' })]: { main: 20 },
      invalid: { main: 32 },
    },
    readVersions: { [caseKey('issuer-a', 'manager-growth')]: 'v1.2', unscoped: 'v4' },
    readEvents: ['event-a', 'event-a', '', null, 'event b'],
    savedEvents: 'event-b', notes: { 'case-one': 'valid note', 'case-two': 123 },
  };
  const store = createPersonalStore(memoryStorage(JSON.stringify(source)));
  assert.deepEqual(store.get(), {
    theme: 'system', language: 'en', fontSize: 17, lastRoute: null,
    positions: { [routeKey(report)]: { main: 23, focusId: 'citation-1' } },
    readVersions: { [caseKey('issuer-a', 'manager-growth')]: 'v1.2' },
    readEvents: ['event-a'], savedEvents: [], notes: { 'case-one': 'valid note' },
  });
  assert.equal(store.save({ theme: 'light', fontSize: '16' }), true);
  assert.equal(store.get().theme, 'light');
  assert.equal(store.get().fontSize, 17);
});

test('corrupt JSON and unavailable storage fall back safely while exposing the error', () => {
  for (const storage of [memoryStorage('{bad json'), memoryStorage('[]'), null,
    () => { throw new Error('Storage access blocked'); },
    { getItem() { throw new Error('Read blocked'); }, setItem() {} },
  ]) {
    const store = createPersonalStore(storage);
    assert.equal(store.get().lastRoute, null);
    assert.match(store.error, /read failed/);
  }
  const unavailable = createPersonalStore(null);
  assert.equal(unavailable.save({ language: 'en' }), false);
  assert.equal(unavailable.get().language, 'en');
  assert.match(unavailable.error, /write failed/);
});

test('Quota failures retain in-memory drafts and can recover on a later save', () => {
  const storage = memoryStorage();
  const setItem = storage.setItem.bind(storage);
  storage.setItem = () => { throw new Error('QuotaExceededError'); };
  const store = createPersonalStore(storage);
  assert.equal(store.save({ notes: { 'report-note': 'Do not discard this draft.' }, theme: 'dark' }), false);
  assert.equal(store.get().notes['report-note'], 'Do not discard this draft.');
  assert.equal(store.get().theme, 'dark');
  assert.match(store.error, /QuotaExceededError/);
  assert.equal(storage.values.has(KEY), false);
  storage.setItem = setItem;
  assert.equal(store.save({ fontSize: 16 }), true);
  assert.equal(store.error, null);
  assert.equal(createPersonalStore(storage).get().notes['report-note'], 'Do not discard this draft.');
});

test('oversize drafts fail persistence without truncating text or claiming a successful save', () => {
  const store = createPersonalStore(memoryStorage());
  const longNote = 'x'.repeat(4 * 1024 * 1024);
  assert.equal(store.save({ notes: { 'large-draft': longNote } }), false);
  assert.equal(store.get().notes['large-draft'].length, longNote.length);
  assert.match(store.error, /exceeds storage limit/);
});

test('hostile object keys cannot pollute personal state', () => {
  const storage = memoryStorage('{"notes":{"__proto__":{"polluted":true},"constructor":"bad","safe":"ok"}}');
  const store = createPersonalStore(storage);
  assert.deepEqual(store.get().notes, { safe: 'ok' });
  assert.equal({}.polluted, undefined);
});
