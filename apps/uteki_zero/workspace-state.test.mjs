import test from 'node:test';
import assert from 'node:assert/strict';
import { KEY, formatRoute, parseRoute, routeKey, reportKey, createPersonalStore } from './workspace-state.mjs';

const index = { page: 'index', entry: 'companies', objectId: 'issuer-a', view: 'research' };
const report = { page: 'reader', entry: 'companies', objectId: 'issuer-a', companyId: 'issuer-a', managerId: 'manager-one', reportId: 'report-main', version: 'v2', view: 'report' };
const compare = { ...report, view: 'compare', compare: { left: { reportId: 'report-main', version: 'v2' }, right: { reportId: 'report-topic', version: 'v1' } } };
const legacy = { page: 'legacy', legacy: { companyId: 'issuer-a', managerId: 'manager-one', version: 'v2', view: 'report' } };
const OLD_KEY = 'uteki.workspace-prototype.v2';
function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  const reads = [];
  return { values, reads, getItem(key) { reads.push(key); return values.get(key) ?? null; }, setItem(key, value) { values.set(key, value); } };
}

test('both independent entry indexes round-trip including explicit counterpart filters', () => {
  for (const route of [index, { ...index, filterId: 'manager-one' }, { ...index, view: 'changes' },
    { page: 'index', entry: 'managers', objectId: 'manager-one', view: 'research', filterId: 'issuer-a' },
    { page: 'index', entry: 'managers', objectId: 'manager-one', view: 'portfolio' }]) {
    assert.deepEqual(parseRoute(formatRoute(route)), route);
  }
  assert.equal(formatRoute({ ...index, filterId: 'manager-one' }), '#/app/companies/issuer-a?view=research&manager=manager-one');
  assert.equal(parseRoute(''), null);
  assert.equal(parseRoute('#'), null);
});

test('reader retains report identity, versions and directory return context', () => {
  for (const route of [report, { ...report, entry: 'managers', objectId: 'manager-one', returnView: 'changes', filterId: 'issuer-a' },
    { ...report, reportId: '报告甲', version: 'v1+review', section: 'thesis' }, compare,
    { ...compare, view: 'evidence', evidenceId: 'source-one', origin: 'compare', returnView: 'research' },
    { ...report, view: 'evidence', evidenceId: 'source-one', origin: 'changes' },
    { ...report, entry: 'managers', objectId: 'manager-one', returnView: 'portfolio' }]) {
    assert.deepEqual(parseRoute(formatRoute(route)), route);
    assert.deepEqual(parseRoute(formatRoute(route).slice(1)), route);
  }
});

test('missing report scope is never repaired by a default report or null version', () => {
  for (const field of ['companyId', 'managerId', 'reportId', 'entry', 'objectId', 'version', 'view']) {
    const route = { ...report };
    delete route[field];
    assert.throws(() => formatRoute(route), /Invalid workspace route/, field);
  }
  for (const route of [{ ...report, version: null }, { ...report, version: 'researching' }, { ...report, version: '' }]) assert.throws(() => formatRoute(route));
  const hash = formatRoute(report);
  for (const field of ['company', 'manager', 'entry', 'object', 'version', 'view']) {
    const [path, raw] = hash.split('?');
    const query = new URLSearchParams(raw); query.delete(field);
    assert.throws(() => parseRoute(`${path}?${query}`), /Invalid workspace route/, field);
  }
});

test('duplicate, unknown, unrelated and malformed URL fields fail explicitly', () => {
  const hash = formatRoute(report);
  for (const invalid of [
    `${hash}&view=changes`, `${hash}&%76ersion=v3`, `${hash}&surprise=1`, `${hash}&companyId=issuer-a`,
    `${hash}&section=%FF`, `${hash}&section=%`, `${hash}&section=%00`, `${hash}#other`,
    '#/app/reports/r%2Fx?company=a&manager=b&version=v1&entry=companies&view=report',
    '#/app/companies/issuer-a?view=research&company=issuer-b',
    '#/app/managers/manager-one?view=research&manager=manager-two',
    '#/app/companies/issuer-a?view=research&version=v2',
    '#/app/companies/issuer-a?view=portfolio',
    '#/app/managers/manager-one?view=portfolio&company=issuer-a',
    '#/app/companies/..?view=research', '#/app/companies/issuer-a',
  ]) assert.throws(() => parseRoute(invalid), /Invalid workspace route/, invalid);
  for (const route of [
    { ...report, extra: true }, { ...index, companyId: 'issuer-a' }, { ...report, evidenceId: 'source-one' },
    { ...report, origin: 'report' }, { ...index, entry: 'other' },
    { ...report, returnView: 'portfolio' }, { ...report, entry: 'managers', objectId: 'manager-one', filterId: 'issuer-a', returnView: 'portfolio' },
    { ...compare, compare: { ...compare.compare, extra: 1 } },
    { ...compare, compare: { left: { ...compare.compare.left, managerId: 'one' }, right: compare.compare.right } },
  ]) assert.throws(() => formatRoute(route), /Invalid workspace route/);
});

test('comparison and its evidence require both explicit report-version pairs', () => {
  assert.throws(() => formatRoute({ ...report, view: 'compare' }), /comparison context/);
  assert.throws(() => formatRoute({ ...report, view: 'evidence' }), /evidenceId/);
  assert.throws(() => formatRoute({ ...report, view: 'evidence', evidenceId: 'e', origin: 'compare' }), /comparison context/);
  assert.throws(() => formatRoute({ ...compare, view: 'evidence', evidenceId: 'e', origin: 'report' }), /comparison context/);
  for (const field of ['leftReport', 'leftVersion', 'rightReport', 'rightVersion']) {
    const [path, raw] = formatRoute(compare).split('?');
    const query = new URLSearchParams(raw); query.delete(field);
    assert.throws(() => parseRoute(`${path}?${query}`), /incomplete comparison/);
  }
});

test('same company and Manager can own multiple report keys without state collisions', () => {
  const topic = { ...report, reportId: 'report-topic' };
  assert.notEqual(reportKey(report.reportId), reportKey(topic.reportId));
  assert.notEqual(routeKey(report), routeKey(topic));
  assert.notEqual(routeKey(report), routeKey({ ...report, entry: 'managers', objectId: 'manager-one' }));
  assert.notEqual(routeKey(report), routeKey({ ...report, version: 'v1' }));
  assert.equal(routeKey(report), routeKey({ ...report, section: 'thesis' }));
  assert.notEqual(routeKey(compare), routeKey({ ...compare, compare: { left: compare.compare.right, right: compare.compare.left } }));
  assert.notEqual(routeKey(index), routeKey({ ...index, filterId: 'manager-one' }));
  assert.throws(() => reportKey(''));
});

test('legacy hashes are preserved for explicit dataset mapping, including unknown legacy scope', () => {
  for (const route of [legacy, { ...legacy, legacy: { ...legacy.legacy, companyId: 'unknown', version: null } }]) {
    assert.deepEqual(parseRoute(formatRoute(route)), route);
    assert.equal(routeKey(route), routeKey({ ...route, legacy: { ...route.legacy, section: 'thesis' } }));
  }
  assert.throws(() => parseRoute(formatRoute(legacy).replace('&view=report', '')), /Invalid workspace route/);
  assert.throws(() => formatRoute({ ...legacy, ignored: true }), /unknown/);
  assert.throws(() => formatRoute({ ...legacy, legacy: { ...legacy.legacy, reportId: 'inferred' } }), /unknown/);
});

test('v3 persists separate entries, sidebar positions and per-report read versions', () => {
  const disk = storage();
  const store = createPersonalStore(disk);
  const managerIndex = { page: 'index', entry: 'managers', objectId: 'manager-one', view: 'research', filterId: 'issuer-a' };
  const position = { main: 300, left: 100, right: 1200, sidebar: 50, focusId: 'report-topic-link' };
  assert.equal(store.save({
    theme: 'dark', language: 'en', fontSize: 18, lastRoute: compare,
    entries: { companies: index, managers: managerIndex }, positions: { [routeKey(compare)]: position },
    readVersions: { 'report-main': 'v2', 'report-topic': 'v1' }, readEvents: ['e1'], savedEvents: ['e2'], notes: { 'report-main': 'Independent note' },
  }), true);
  assert.deepEqual(createPersonalStore(disk).get(), store.get());
  assert.deepEqual(store.get().positions[routeKey(compare)], position);
  const external = store.get(); external.entries.companies.objectId = 'other'; external.positions[routeKey(compare)].main = 0;
  assert.equal(store.get().entries.companies.objectId, 'issuer-a');
  assert.equal(store.get().positions[routeKey(compare)].main, 300);
});

test('only display preferences migrate when v3 is absent, preserving v2 unchanged', () => {
  const oldValue = JSON.stringify({ theme: 'dark', language: 'en', fontSize: 18,
    lastRoute: legacy.legacy, readVersions: { '["issuer-a","manager-one"]': 'v2' }, positions: { old: { main: 8 } }, notes: { old: 'Old draft' }, readEvents: ['old-event'] });
  const disk = storage({ [OLD_KEY]: oldValue });
  const store = createPersonalStore(disk);
  assert.deepEqual(store.get(), {
    theme: 'dark', language: 'en', fontSize: 18, lastRoute: null, entries: { companies: null, managers: null },
    positions: {}, readVersions: {}, readEvents: [], savedEvents: [], notes: {},
  });
  assert.deepEqual(disk.reads, [KEY, OLD_KEY]);
  assert.equal(disk.values.has(KEY), false);
  assert.equal(store.save({ lastRoute: index }), true);
  assert.equal(disk.values.get(OLD_KEY), oldValue);
  assert.deepEqual(createPersonalStore(disk).get().lastRoute, index);
});

test('existing v3 preferences win, and corrupted v3 never silently loads legacy scope', () => {
  const oldValue = JSON.stringify({ theme: 'dark', language: 'en' });
  const disk = storage({ [KEY]: JSON.stringify({ theme: 'light' }), [OLD_KEY]: oldValue });
  assert.equal(createPersonalStore(disk).get().theme, 'light');
  assert.deepEqual(disk.reads, [KEY]);
  const corrupted = storage({ [KEY]: '{invalid', [OLD_KEY]: oldValue });
  const store = createPersonalStore(corrupted);
  assert.match(store.error, /read failed/);
  assert.equal(store.get().theme, 'system');
  assert.deepEqual(corrupted.reads, [KEY]);
});

test('invalid stored routes, entry crossover and unsafe position fields are discarded', () => {
  const disk = storage({ [KEY]: JSON.stringify({
    lastRoute: { ...report, version: null },
    entries: { companies: { ...index, entry: 'managers' }, managers: report },
    positions: {
      [routeKey(report)]: { main: 20, sidebar: -1, left: '4', right: 45 },
      [formatRoute({ ...report, section: 'anchor' })]: { main: 4 },
      arbitrary: { main: 3 },
    },
    readVersions: { 'report-main': 'v2', 'bad report': 'v1', 'report-topic': null },
    readEvents: ['e1', 'e1', '', 'bad event'],
  }) });
  const state = createPersonalStore(disk).get();
  assert.equal(state.lastRoute, null);
  assert.deepEqual(state.entries, { companies: null, managers: null });
  assert.deepEqual(state.positions, { [routeKey(report)]: { main: 20, right: 45 } });
  assert.deepEqual(state.readVersions, { 'report-main': 'v2' });
  assert.deepEqual(state.readEvents, ['e1']);
});

test('storage failures keep drafts and preferences in memory and recover on retry', () => {
  for (const unavailable of [null, () => { throw new Error('Access denied'); }, storage({ [KEY]: '[]' })]) {
    const store = createPersonalStore(unavailable);
    assert.match(store.error, /read failed/);
  }
  const disk = storage();
  const originalSet = disk.setItem.bind(disk);
  disk.setItem = () => { throw new Error('Quota exceeded'); };
  const store = createPersonalStore(disk);
  assert.equal(store.save({ theme: 'dark', notes: { 'report-main': 'Keep this note' } }), false);
  assert.equal(store.get().notes['report-main'], 'Keep this note');
  assert.equal(store.get().theme, 'dark');
  assert.match(store.error, /Quota exceeded/);
  disk.setItem = originalSet;
  assert.equal(store.save({ fontSize: 16 }), true);
  assert.equal(store.error, null);
  assert.equal(createPersonalStore(disk).get().notes['report-main'], 'Keep this note');
});

test('oversize notes remain in memory without claiming persistence or truncating text', () => {
  const store = createPersonalStore(storage());
  const note = 'x'.repeat(4 * 1024 * 1024);
  assert.equal(store.save({ notes: { 'report-main': note } }), false);
  assert.equal(store.get().notes['report-main'].length, note.length);
  assert.match(store.error, /exceeds storage limit/);
});

test('hostile map keys cannot pollute personal state', () => {
  const store = createPersonalStore(storage({ [KEY]: '{"notes":{"__proto__":{"polluted":true},"constructor":"bad","report-main":"good"}}' }));
  assert.deepEqual(store.get().notes, { 'report-main': 'good' });
  assert.equal({}.polluted, undefined);
});
