import test from 'node:test';
import assert from 'node:assert/strict';
import demo from './data.mjs';
import { validateDemo, selectChanges, unreadCount, selectTasks, changeContext } from './model.mjs';

// Deliberately independent of the demo companies and investment prose.
function fixture() {
  return {
    companies: [{ id: 'orchard' }, { id: 'harbor' }, { id: 'quiet' }],
    reports: [
      { id: 'r-orchard', companyId: 'orchard', factors: [{ id: 'f-orchard' }] },
      { id: 'r-harbor', companyId: 'harbor', factors: [{ id: 'f-harbor' }] },
      { id: 'r-quiet', companyId: 'quiet', factors: [{ id: 'f-quiet' }] },
    ],
    changes: [
      { id: 'c-later', companyId: 'orchard', reportId: 'r-orchard', factorId: 'f-orchard', kind: 'support', rank: 20, evidence: [{ id: 'e-one' }, { id: 'e-two' }], taskIds: ['t-orchard'] },
      { id: 'c-first', companyId: 'harbor', reportId: 'r-harbor', factorId: 'f-harbor', kind: 'challenge', rank: 5, evidence: [{ id: 'e-three' }], taskIds: ['t-harbor'] },
      { id: 'c-middle', companyId: 'orchard', reportId: 'r-orchard', factorId: 'f-orchard', kind: 'watch', rank: 10, evidence: [], taskIds: [] },
    ],
    tasks: [
      { id: 't-orchard', companyId: 'orchard', reportId: 'r-orchard', factorId: 'f-orchard' },
      { id: 't-harbor', companyId: 'harbor', reportId: 'r-harbor', factorId: 'f-harbor' },
    ],
    managers: [{ id: 'm-one', cashPct: 35, positions: [{ companyId: 'orchard', weightPct: 40 }, { companyId: 'harbor', weightPct: 25 }], actions: [{ id: 'a-one', companyId: 'orchard' }] }],
  };
}

const ids = (items) => items.map((item) => item.id);

test('shipped illustrative data has valid scoped research and fully accounted portfolios', () => {
  assert.equal(validateDemo(demo), true);
  assert.match(demo.label, /示意/);
  for (const manager of demo.managers) {
    assert.match(manager.name, /示例/);
    assert.match(manager.period, /示意/);
    assert.equal(manager.positions.reduce((sum, item) => sum + item.weightPct, manager.cashPct), 100);
  }
});

test('independent fixture validates without depending on a particular demo company', () => {
  assert.equal(validateDemo(fixture()), true);
});

test('selection sorts by rank without mutating the source and filters by company', () => {
  const data = fixture();
  const before = structuredClone(data);
  assert.deepEqual(ids(selectChanges(data)), ['c-first', 'c-middle', 'c-later']);
  assert.deepEqual(ids(selectChanges(data, { companyId: 'orchard' })), ['c-middle', 'c-later']);
  assert.deepEqual(data, before);
});

test('read and saved states remain independent, including a saved already-read change', () => {
  const data = fixture();
  const state = { readIds: ['c-first'], savedIds: ['c-first', 'c-middle'] };
  assert.deepEqual(ids(selectChanges(data, { ...state, filter: 'unread' })), ['c-middle', 'c-later']);
  assert.deepEqual(ids(selectChanges(data, { ...state, filter: 'saved' })), ['c-first', 'c-middle']);
  assert.deepEqual(ids(selectChanges(data, { ...state, filter: 'challenge' })), ['c-first']);
  assert.equal(unreadCount(data, state.readIds), 2);
});

test('unread badges count distinct changes, never evidence or duplicate input ids', () => {
  const data = fixture();
  data.changes[0].evidence.push({ id: 'e-extra' }, { id: 'e-extra-2' });
  assert.equal(unreadCount(data), 3);
  assert.equal(unreadCount(data, [], 'orchard'), 2);
  data.changes.push(structuredClone(data.changes[0]));
  assert.equal(unreadCount(data), 3);
  assert.equal(unreadCount(data, ['c-later', 'c-later'], 'orchard'), 1);
  assert.throws(() => validateDemo(data), /duplicate change id/);
});

test('known companies with no changes or tasks have genuine empty states', () => {
  const data = fixture();
  assert.deepEqual(selectChanges(data, { companyId: 'quiet' }), []);
  assert.deepEqual(selectChanges(data, { filter: 'saved' }), []);
  assert.deepEqual(selectChanges(data, { filter: 'unread', readIds: ids(data.changes) }), []);
  assert.deepEqual(selectTasks(data, 'quiet'), []);
  assert.equal(unreadCount(data, [], 'quiet'), 0);
  assert.deepEqual(ids(selectTasks(data, 'harbor')), ['t-harbor']);
  assert.equal(selectTasks(data).length, 2);
});

test('unknown or blank scope and unknown filters fail instead of selecting the first company', () => {
  const data = fixture();
  for (const companyId of ['unknown', '']) {
    assert.throws(() => selectChanges(data, { companyId }), /unknown id/);
    assert.throws(() => selectTasks(data, companyId), /unknown id/);
    assert.throws(() => unreadCount(data, [], companyId), /unknown id/);
  }
  assert.throws(() => selectChanges(data, { filter: 'everything' }), /unknown change filter/);
  assert.throws(() => changeContext(data, 'missing'), /unknown id/);
});

test('change context follows its exact company, report, factor and linked task', () => {
  const context = changeContext(fixture(), 'c-first');
  assert.equal(context.change.id, 'c-first');
  assert.equal(context.company.id, 'harbor');
  assert.equal(context.report.id, 'r-harbor');
  assert.equal(context.factor.id, 'f-harbor');
  assert.deepEqual(ids(context.tasks), ['t-harbor']);
});

test('every company requires exactly one main report', () => {
  const missing = fixture();
  missing.reports.pop();
  assert.throws(() => validateDemo(missing), /exactly one main report/);
  const duplicate = fixture();
  duplicate.reports.push({ id: 'r-second', companyId: 'quiet', factors: [] });
  assert.throws(() => validateDemo(duplicate), /exactly one main report/);
});

test('duplicate entity, factor, evidence and action identities are rejected', () => {
  for (const collection of ['companies', 'reports', 'tasks', 'changes', 'managers']) {
    const data = fixture();
    data[collection].push(structuredClone(data[collection][0]));
    assert.throws(() => validateDemo(data), /duplicate/);
  }
  const factor = fixture();
  factor.reports[1].factors.push({ id: 'f-orchard' });
  assert.throws(() => validateDemo(factor), /duplicate factor/);
  const evidence = fixture();
  evidence.changes[1].evidence.push({ id: 'e-one' });
  assert.throws(() => validateDemo(evidence), /duplicate evidence/);
  const action = fixture();
  action.managers[0].actions.push({ id: 'a-one', companyId: 'harbor' });
  assert.throws(() => validateDemo(action), /duplicate action/);
});

test('changes cannot borrow another company report, factor, task or evidence scope', () => {
  const corruptions = [
    (data) => { data.changes[0].reportId = 'r-harbor'; },
    (data) => { data.changes[0].factorId = 'f-harbor'; },
    (data) => { data.changes[0].taskIds = ['t-harbor']; },
    (data) => { data.changes[0].evidence[0].companyId = 'harbor'; },
    (data) => { data.changes[0].evidence[0].reportId = 'r-harbor'; },
    (data) => { data.changes[0].evidence[0].factorId = 'f-harbor'; },
  ];
  for (const corrupt of corruptions) {
    const data = fixture();
    corrupt(data);
    assert.throws(() => validateDemo(data), /another company|unknown id|conflicts/);
    assert.throws(() => changeContext(data, 'c-later'), /another company|unknown id|conflicts/);
  }
});

test('broken report and task references and duplicate task links are rejected', () => {
  const mutations = [
    (data) => { data.reports[0].companyId = 'unknown'; },
    (data) => { data.tasks[0].reportId = 'r-harbor'; },
    (data) => { data.tasks[0].factorId = 'missing'; },
    (data) => { data.changes[0].taskIds = ['missing']; },
    (data) => { data.changes[0].taskIds.push('t-orchard'); },
    (data) => { data.reports[0].factors[0].companyId = 'harbor'; },
  ];
  for (const mutate of mutations) {
    const data = fixture();
    mutate(data);
    assert.throws(() => validateDemo(data), /unknown id|another company|duplicate task|conflicts/);
  }
});

test('manager portfolios require known companies, explicit cash and a total of 100', () => {
  const mutations = [
    (manager) => { delete manager.cashPct; },
    (manager) => { manager.cashPct = 34; },
    (manager) => { manager.cashPct = NaN; },
    (manager) => { manager.positions[0].weightPct = -1; },
    (manager) => { manager.positions[0].companyId = 'unknown'; },
    (manager) => { manager.positions.push({ companyId: 'orchard', weightPct: 0 }); },
    (manager) => { manager.actions[0].companyId = 'unknown'; },
  ];
  for (const mutate of mutations) {
    const data = fixture();
    mutate(data.managers[0]);
    assert.throws(() => validateDemo(data), /explicit percentage|total 100|unknown id|duplicate company/);
  }
});
