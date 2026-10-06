import test from 'node:test';
import assert from 'node:assert/strict';
import { catalog, getManager, parseRoute } from './model.mjs';
import { investmentEventFixture } from './investment-events.mjs';
import { getManagerResearchRows, getManagerExecutionHistory } from './manager-activity.mjs';

function synthetic() {
  return {
    companies: [{ id: 'cedar', name: 'Cedar' }, { id: 'pine', name: 'Pine' }, { id: 'birch', name: 'Birch' }],
    managers: [{ id: 'scout' }, { id: 'patient' }],
    coverage: [
      { managerId: 'scout', companyId: 'cedar', status: 'published' },
      { managerId: 'scout', companyId: 'birch', status: 'researching' },
      { managerId: 'patient', companyId: 'pine', status: 'published' },
    ],
    reports: [
      { id: 'cedar-main', companyId: 'cedar', managerId: 'scout', title: 'Cedar main', currentVersion: 'v3', versions: [
        { version: 'v1', title: 'First Cedar judgment', status: 'historical', publishedAt: '2024-03-02', sections: [{ id: 'old' }] },
        { version: 'v3', title: 'Cedar judgment needs review', status: 'review', publishedAt: '2024-08-04', sections: [{ id: 'risk' }] },
      ] },
      { id: 'cedar-topic', companyId: 'cedar', managerId: 'scout', title: 'Cedar topic', currentVersion: 'v1', versions: [
        { version: 'v1', title: 'Cedar demand', status: 'current', publishedAt: '2024-08-03', sections: [{ id: 'summary' }] },
      ] },
      { id: 'pine-main', companyId: 'pine', managerId: 'patient', title: 'Pine main', currentVersion: 'v1', versions: [
        { version: 'v1', title: 'Pine judgment', status: 'current', publishedAt: '2024-07-05', sections: [{ id: 'summary' }] },
      ] },
      { id: 'cedar-other', companyId: 'cedar', managerId: 'patient', title: 'Other Cedar main', currentVersion: 'v2', versions: [
        { version: 'v2', title: 'Patient Cedar judgment', status: 'current', publishedAt: '2024-08-06', sections: [{ id: 'summary' }] },
      ] },
    ],
    evidence: [],
    events: [
      { id: 'cedar-open', companyId: 'cedar', date: '2024-08-02', kind: 'risk', title: 'Demand remains uncertain', unresolved: true, affectedReports: [
        { reportId: 'cedar-main', version: 'v1', sectionId: 'old' },
        { reportId: 'cedar-main', version: 'v3', sectionId: 'risk' },
        { reportId: 'cedar-other', version: 'v2' },
      ] },
      { id: 'cedar-resolved', companyId: 'cedar', date: '2024-08-05', title: 'Resolved', unresolved: false, affectedReports: [{ reportId: 'cedar-topic', version: 'v1' }] },
      { id: 'pine-open', companyId: 'pine', date: '2024-08-07', title: 'Pine question', unresolved: true, affectedReports: [{ reportId: 'pine-main', version: 'v1' }] },
    ],
  };
}

function eventFixture() {
  return {
    id: 'independent-event-fixture', version: 'v7', isSimulated: true,
    label: '模拟', labelEn: 'Illustrative', disclosure: '独立演示事件', disclosureEn: 'Independently authored events',
    scope: { managerIds: ['scout', 'patient'], companyIds: ['cedar', 'pine', 'birch'] },
    reportPublications: [{ managerId: 'scout', companyId: 'cedar', reportId: 'cedar-main', version: 'v1', publishedAt: '2024-03-02' }],
    events: [
      { id: 's-buy', managerId: 'scout', companyId: 'birch', date: '2023-12-21', kind: 'buy', title: '买入 Birch', titleEn: 'Buy Birch' },
      { id: 's-report', managerId: 'scout', companyId: 'cedar', date: '2024-03-02', kind: 'report', title: '报告', titleEn: 'Report', report: { reportId: 'cedar-main', version: 'v1' } },
      { id: 's-sell', managerId: 'scout', companyId: 'cedar', date: '2024-08-09', kind: 'sell', title: '卖出 Cedar', titleEn: 'Sell Cedar' },
      { id: 'p-buy', managerId: 'patient', companyId: 'pine', date: '2024-09-10', kind: 'buy', title: '买入 Pine', titleEn: 'Buy Pine' },
    ],
  };
}

test('research rows retain author-scoped questions and exact report versions', () => {
  const data = synthetic(), before = JSON.stringify(data);
  const rows = getManagerResearchRows('scout', 'all', data);
  assert.deepEqual(rows.map(row => row.type), ['report', 'report', 'question']);
  const question = rows.find(row => row.type === 'question');
  assert.equal(question.company.id, 'cedar');
  assert.equal(question.status, 'unresolved');
  assert.equal(question.date, '2024-08-02');
  assert.deepEqual(question.links.map(link => parseRoute(link.href, data)), [
    { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v1', sectionId: 'old' },
    { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v3', sectionId: 'risk' },
  ]);
  assert.ok(rows.every(row => row.managerId === 'scout'));
  assert.ok(!rows.some(row => row.title === 'Resolved' || row.companyId === 'pine'));
  assert.equal(JSON.stringify(data), before);
});

test('published means current independent outputs; review reports also remain open', () => {
  const data = synthetic();
  const published = getManagerResearchRows('scout', 'published', data);
  assert.equal(published.length, 2, 'historical versions are not additional reports');
  assert.deepEqual(published.map(row => [row.reportId, row.version, row.status, row.sourceStatus]), [
    ['cedar-main', 'v3', 'review', 'review'], ['cedar-topic', 'v1', 'published', 'current'],
  ]);
  const open = getManagerResearchRows('scout', 'open', data);
  assert.deepEqual(open.map(row => row.type), ['report', 'question']);
  assert.ok(!open.some(row => row.reportId === 'cedar-topic'));
});

test('directory coverage without a report does not create a placeholder research task', () => {
  const rows = getManagerResearchRows('scout', 'all', synthetic());
  assert.ok(rows.every(row => row.companyId !== 'birch'));
  assert.ok(rows.every(row => row.type !== 'coverage'));
  assert.equal(getManager('scout', synthetic()).portfolio.status, 'unavailable');
});

test('default catalog counts remain current, isolated and independent from account availability', () => {
  for (const manager of catalog.managers) {
    const context = getManager(manager.id);
    const all = getManagerResearchRows(manager.id);
    assert.equal(all.filter(row => row.type === 'report').length, context.reports.length);
    assert.equal(all.filter(row => row.type === 'question').length, context.events.filter(item => item.event.unresolved).length);
    assert.ok(all.flatMap(row => row.links).every(link => link.route.managerId === manager.id));
    assert.equal(getManagerExecutionHistory({ managerId: manager.id }).counts.all,
      investmentEventFixture.events.filter(event => event.managerId === manager.id).length);
  }
});

test('execution history uses the full selected fixture range and preserves historical report identity', () => {
  const fixture = eventFixture(), data = synthetic(), before = JSON.stringify(fixture);
  const history = getManagerExecutionHistory({ managerId: 'scout' }, fixture, data);
  assert.deepEqual(history.range, { start: '2023-12-21', end: '2024-09-10' });
  assert.deepEqual(history.events.map(event => event.id), ['s-sell', 's-report', 's-buy']);
  assert.deepEqual(history.counts, { all: 3, buy: 1, sell: 1, report: 1 });
  const report = history.events[1];
  assert.equal(report.company.id, 'cedar');
  assert.equal(report.links[0].route.version, 'v1', 'never replaces a historical publication with the current version');
  assert.equal(report.links[0].route.managerId, 'scout');
  assert.ok(history.events.every(event => event.isSimulated && !Object.hasOwn(event, 'price') && !Object.hasOwn(event, 'quantity')));
  assert.deepEqual(history.events[0].links, []);
  assert.equal(history.fixtureId, fixture.id);
  assert.equal(history.disclosure, fixture.disclosure);
  assert.equal(JSON.stringify(fixture), before);
});

test('kind filtering does not alter full-range coverage or totals', () => {
  const history = getManagerExecutionHistory({ managerId: 'patient', kind: 'sell' }, eventFixture(), synthetic());
  assert.deepEqual(history.events, []);
  assert.deepEqual(history.counts, { all: 1, buy: 1, sell: 0, report: 0 });
  assert.deepEqual(history.range, { start: '2023-12-21', end: '2024-09-10' });
});

test('explicitly covered empty history differs from an unconnected source or missing dates', () => {
  const fixture = eventFixture();
  fixture.events = [];
  fixture.coverage = { start: '2024-01-01', end: '2024-12-31' };
  const history = getManagerExecutionHistory({ managerId: 'scout' }, fixture, synthetic());
  assert.deepEqual(history.events, []);
  assert.equal(history.coverage, 'explicit-range');
  assert.equal(history.counts.all, 0);
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout' }, null, synthetic()), /explicitly selected/);
  delete fixture.coverage;
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout' }, fixture, synthetic()), /empty fixture requires explicit coverage/);
});

test('unknown scopes, unsupported filters and invalid publication ownership fail instead of substituting data', () => {
  for (const id of [undefined, null, '', ' ', 'unknown']) {
    assert.throws(() => getManagerResearchRows(id));
    assert.throws(() => getManagerExecutionHistory({ managerId: id }));
  }
  assert.throws(() => getManagerResearchRows('scout', 'finished', synthetic()), /filter/);
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout', kind: 'trade' }, eventFixture(), synthetic()), /kind/);
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout', companyId: 'cedar' }, eventFixture(), synthetic()), /query/);
  assert.throws(() => getManagerExecutionHistory({ managerId: 'north' }, eventFixture()), /unknown in the selected fixture/);
  const wrongAuthor = eventFixture();
  wrongAuthor.reportPublications[0].managerId = 'patient';
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout' }, wrongAuthor, synthetic()), /publication Manager/);
  const wrongDate = eventFixture();
  wrongDate.reportPublications[0].publishedAt = '2024-03-03';
  wrongDate.events.find(event => event.kind === 'report').date = '2024-03-03';
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout' }, wrongDate, synthetic()), /selected catalog publication/);
  const badCoverage = eventFixture();
  badCoverage.coverage = { start: '2024-01-01', end: '2024-12-31' };
  assert.throws(() => getManagerExecutionHistory({ managerId: 'scout' }, badCoverage, synthetic()), /outside explicit date coverage/);
});
