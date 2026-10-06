import test from 'node:test';
import assert from 'node:assert/strict';
import { getReport } from './model.mjs';
import { getInvestmentEvents, investmentEventFixture, investmentEventFixtureV1 } from './investment-events.mjs';

const query = overrides => ({ managerId: 'north', start: '2025-10-01', end: '2026-09-30', ...overrides });
const copy = () => structuredClone(investmentEventFixture);
const sample = (id, managerId, companyId, date, kind = 'buy', report) => ({
  id, managerId, companyId, date, kind, title: `示例 ${id}`, titleEn: `Example ${id}`,
  ...(report ? { report } : {}),
});
function synthetic() {
  return {
    id: 'independent-test', version: 'v1', isSimulated: true,
    scope: { managerIds: ['first', 'second', 'empty'], companyIds: ['citrus', 'delta'] },
    reportPublications: [{ reportId: 'delta-review', version: 'edition-3', managerId: 'second', companyId: 'delta', publishedAt: '2027-01-01' }],
    events: [
      sample('before', 'first', 'citrus', '2026-12-27'),
      sample('monday', 'first', 'citrus', '2026-12-28'),
      sample('new-year-buy', 'first', 'delta', '2027-01-01'),
      sample('new-year-sell', 'first', 'citrus', '2027-01-01', 'sell'),
      sample('sunday', 'first', 'delta', '2027-01-03'),
      sample('next-week', 'first', 'citrus', '2027-01-04'),
      sample('other-author-buy', 'second', 'citrus', '2027-01-01'),
      sample('other-author-report', 'second', 'delta', '2027-01-01', 'report', { reportId: 'delta-review', version: 'edition-3' }),
    ],
  };
}

test('the named UI fixture is deeply frozen and explicitly discloses independent simulated events', () => {
  assert.equal(investmentEventFixture, investmentEventFixtureV1);
  assert.equal(investmentEventFixture.isSimulated, true);
  assert.match(investmentEventFixture.disclosure, /未从当前持仓或收益反推/);
  const verify = value => {
    if (!value || typeof value !== 'object') return;
    assert.ok(Object.isFrozen(value));
    Object.values(value).forEach(verify);
  };
  verify(investmentEventFixture);
});

test('every report sample agrees with the actual catalog author, company, version and publication date', () => {
  const reports = investmentEventFixture.events.filter(event => event.kind === 'report');
  assert.equal(reports.length, 8);
  for (const event of reports) {
    const context = getReport(event.companyId, event.report.reportId, event.report.version);
    assert.equal(context.manager.id, event.managerId);
    assert.equal(context.document.companyId, event.companyId);
    assert.equal(context.report.version, event.report.version);
    assert.equal(context.report.publishedAt, event.date);
  }
});

test('sample queries isolate the selected Manager, including same-company and same-date events', () => {
  const north = getInvestmentEvents(query());
  const field = getInvestmentEvents(query({ managerId: 'field' }));
  assert.equal(north.events.length + field.events.length, investmentEventFixture.events.length);
  assert.ok(north.events.every(event => event.managerId === 'north'));
  assert.ok(field.events.every(event => event.managerId === 'field'));
  assert.ok(north.events.some(event => event.report?.reportId === 'alpha-north-main'));
  assert.ok(!north.events.some(event => event.report?.reportId === 'alpha-field-main'));
  assert.ok(field.events.some(event => event.report?.reportId === 'alpha-field-main'));
});

test('scope and dates must be explicit; unknown, unsupported and blank values do not fall back', () => {
  for (const value of [undefined, null, {}, query({ managerId: '' }), query({ managerId: ' ' }), query({ managerId: 'unknown' }),
    query({ start: undefined }), query({ end: '' }), query({ start: '2026-10-01' }), query({ companyId: 'alphabet' })]) {
    assert.throws(() => getInvestmentEvents(value), /Investment events/);
  }
  for (const kind of ['', null, 'hold', 'BUY']) assert.throws(() => getInvestmentEvents(query({ kind })), /kind/);
  for (const granularity of ['', null, 'quarter', 'DAY']) assert.throws(() => getInvestmentEvents(query({ granularity })), /granularity/);
});

test('date validation rejects rollover, timestamps and non-ISO input, but accepts leap days', () => {
  for (const start of ['2026-02-29', '2026-02-30', '2026-04-31', '2026-00-01', '2026-13-01', '2026-1-01', '2026-01-01T00:00:00Z', 'invalid']) {
    assert.throws(() => getInvestmentEvents(query({ start })), /date/);
  }
  assert.deepEqual(getInvestmentEvents(query({ start: '2024-02-29', end: '2024-02-29' })).events, []);
});

test('auto granularity uses inclusive 45-day and 120-day boundaries', () => {
  const endForDays = days => new Date(Date.parse('2026-01-01T00:00:00Z') + (days - 1) * 86400000).toISOString().slice(0, 10);
  for (const [days, expected] of [[1, 'day'], [45, 'day'], [46, 'week'], [120, 'week'], [121, 'month'], [365, 'month']]) {
    assert.equal(getInvestmentEvents(query({ start: '2026-01-01', end: endForDays(days) })).granularity, expected);
  }
});

test('manual granularity overrides auto without changing event membership', () => {
  const expected = getInvestmentEvents(query()).events.map(event => event.id);
  for (const granularity of ['day', 'week', 'month']) {
    const result = getInvestmentEvents(query({ granularity }));
    assert.equal(result.granularity, granularity);
    assert.deepEqual(result.events.map(event => event.id), expected);
  }
});

test('known Managers may have no events; an empty interval does not substitute another period or author', () => {
  assert.deepEqual(getInvestmentEvents(query({ start: '2024-01-01', end: '2024-01-31' })), { events: [], groups: [], granularity: 'day' });
  assert.deepEqual(getInvestmentEvents({ managerId: 'empty', start: '2026-12-01', end: '2027-01-31' }, synthetic()),
    { events: [], groups: [], granularity: 'week' });
});

test('an independent dataset supports another author, company and report version without hardcoded mappings', () => {
  const result = getInvestmentEvents({ managerId: 'second', start: '2027-01-01', end: '2027-01-01' }, synthetic());
  assert.equal(result.events.length, 2);
  assert.deepEqual(new Set(result.events.map(event => event.companyId)), new Set(['citrus', 'delta']));
  assert.equal(result.groups.length, 1);
  assert.deepEqual(result.events.find(event => event.kind === 'report').report, { reportId: 'delta-review', version: 'edition-3' });
});

test('weeks start on UTC Monday across the year boundary, retaining exact event dates', () => {
  const result = getInvestmentEvents({ managerId: 'first', start: '2026-12-27', end: '2027-01-05', granularity: 'week' }, synthetic());
  assert.deepEqual(result.groups.map(group => [group.start, group.end, group.events.map(event => event.date)]), [
    ['2026-12-27', '2026-12-27', ['2026-12-27']],
    ['2026-12-28', '2027-01-03', ['2026-12-28', '2027-01-01', '2027-01-01', '2027-01-03']],
    ['2027-01-04', '2027-01-05', ['2027-01-04']],
  ]);
  assert.match(result.groups[1].id, /week:2026-12-28$/);
});

test('calendar group bounds and event membership are clipped to the exact inclusive requested range', () => {
  const fixture = synthetic();
  const narrow = getInvestmentEvents({ managerId: 'first', start: '2027-01-01', end: '2027-01-01', granularity: 'week' }, fixture);
  assert.equal(narrow.events.length, 2);
  assert.equal(narrow.groups.length, 1);
  assert.equal(narrow.groups[0].start, '2027-01-01');
  assert.equal(narrow.groups[0].end, '2027-01-01');
  const monthly = getInvestmentEvents({ managerId: 'first', start: '2026-12-28', end: '2027-01-03', granularity: 'month' }, fixture);
  assert.deepEqual(monthly.groups.map(({ start, end }) => [start, end]), [['2026-12-28', '2026-12-31'], ['2027-01-01', '2027-01-03']]);
  assert.ok(!monthly.events.some(event => ['before', 'next-week'].includes(event.id)));
});

test('multiple event types on one date are retained and type filtering preserves group identity', () => {
  const fixture = synthetic();
  const options = { managerId: 'second', start: '2027-01-01', end: '2027-01-01' };
  const all = getInvestmentEvents(options, fixture);
  assert.equal(all.groups[0].events.length, 2);
  for (const kind of ['buy', 'report']) {
    const result = getInvestmentEvents({ ...options, kind }, fixture);
    assert.equal(result.events.length, 1);
    assert.equal(result.events[0].kind, kind);
    assert.equal(result.groups[0].id, all.groups[0].id);
  }
  assert.deepEqual(getInvestmentEvents({ ...options, kind: 'sell' }, fixture).groups, []);
});

test('grouping and filtering never lose or duplicate events and do not mutate source ordering', () => {
  const fixture = copy();
  fixture.events.reverse();
  const before = JSON.stringify(fixture);
  for (const managerId of fixture.scope.managerIds) {
    for (const granularity of ['auto', 'day', 'week', 'month']) {
      for (const kind of ['all', 'buy', 'sell', 'report']) {
        const result = getInvestmentEvents(query({ managerId, granularity, kind }), fixture);
        const flattened = result.groups.flatMap(group => group.events.map(event => event.id));
        assert.deepEqual(flattened, result.events.map(event => event.id));
        assert.equal(new Set(flattened).size, flattened.length);
        assert.ok(result.events.every((event, index) => index === 0 || event.date >= result.events[index - 1].date));
      }
    }
  }
  assert.equal(JSON.stringify(fixture), before);
});

test('report events reject another author, another company, missing versions and changed publication dates', () => {
  const changes = [
    event => { event.managerId = 'field'; },
    event => { event.companyId = 'microsoft'; },
    event => { event.report.version = 'v99'; },
    event => { event.report.reportId = 'alpha-field-main'; },
    event => { event.date = '2026-09-17'; },
    event => { delete event.report; },
  ];
  for (const change of changes) {
    const fixture = copy();
    change(fixture.events.find(event => event.id === 'north-report-main-v1'));
    assert.throws(() => getInvestmentEvents(query(), fixture), /report event/);
  }
});

test('publication metadata rejects duplicate versions and ownership changes within a report', () => {
  const duplicate = copy();
  duplicate.reportPublications.push({ ...duplicate.reportPublications[0] });
  assert.throws(() => getInvestmentEvents(query(), duplicate), /unique/);
  const owner = copy();
  owner.reportPublications.find(entry => entry.reportId === 'alpha-north-main' && entry.version === 'v2').managerId = 'field';
  assert.throws(() => getInvestmentEvents(query(), owner), /share one Manager/);
});

test('invalid event scopes, duplicate ids, invalid types and accidental trade/report links fail explicitly', () => {
  const changes = [
    fixture => { fixture.events[0].managerId = 'unknown'; },
    fixture => { fixture.events[0].companyId = 'unknown'; },
    fixture => { fixture.events[0].date = '2026-02-30'; },
    fixture => { fixture.events[0].kind = 'dividend'; },
    fixture => { fixture.events[0].titleEn = ''; },
    fixture => { fixture.events[0].report = { reportId: 'alpha-north-main', version: 'v1' }; },
    fixture => { fixture.events.push({ ...fixture.events[0] }); },
    fixture => { fixture.scope.managerIds.push('north'); },
    fixture => { fixture.isSimulated = false; },
  ];
  for (const change of changes) {
    const fixture = copy();
    change(fixture);
    assert.throws(() => getInvestmentEvents(query(), fixture), /Investment events/);
  }
});

test('a missing or unknown selected fixture never falls back to the named demo', () => {
  for (const fixture of [null, {}, { ...synthetic(), scope: {} }]) assert.throws(() => getInvestmentEvents(query(), fixture), /Investment events/);
  assert.throws(() => getInvestmentEvents(query(), synthetic()), /unknown in the selected fixture/);
});
