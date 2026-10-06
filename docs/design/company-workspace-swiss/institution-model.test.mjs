import test from 'node:test';
import assert from 'node:assert/strict';
import { institutionFixture, institutionFixtureV1, institutionFixtureV2, INSTITUTION_DEMO_SCOPE } from './institution-data.mjs';
import { catalog, getInstitution, getManager, formatRoute, parseRoute, routeContext } from './model.mjs';

const clone = () => structuredClone(institutionFixture);

test('institution fixture explicitly discloses simulation and stays separate from research and agent examples', () => {
  const before = JSON.stringify(catalog);
  const result = getInstitution('uteki');
  assert.equal(result, institutionFixture);
  assert.equal(result.simulation.isSimulated, true);
  assert.equal(result.simulation.version, 'v2');
  assert.equal(result.defaultAgentId, 'north');
  assert.equal(result.simulation.asOf, '2026-09-30');
  assert.match(result.simulation.disclosure, /模拟数据/);
  assert.match(result.simulation.disclosureEn, /not live or backtested/);
  assert.match(result.simulation.benchmarkLabel, /示意/);
  assert.deepEqual(result.portfolio.holdings.map(item => item.companyId), catalog.companies.map(item => item.id));
  assert.deepEqual(result.agents.map(item => item.managerId), ['north', 'field']);
  assert.equal(result.portfolio.holdings.find(item => item.companyId === 'alphabet').marketValue, 240000);
  assert.notEqual(result.portfolio.holdings.find(item => item.companyId === 'alphabet').marketValue,
    result.agents.reduce((total, agent) => total + agent.portfolio.holdings.find(item => item.companyId === 'alphabet').marketValue, 0));
  assert.ok(Math.abs(result.periods.find(item => item.id === 'ytd').returnPct - 8) < 1e-9);
  assert.notEqual(result.periods.find(item => item.id === 'ytd').returnPct,
    result.agents.reduce((total, agent) => total + agent.returns.ytd, 0) / result.agents.length);
  for (const agent of result.agents) assert.equal(getManager(agent.managerId).portfolio.status, 'unavailable');
  assert.equal(JSON.stringify(catalog), before);
  assert.equal(Object.isFrozen(result.portfolio.holdings), true);
});

test('v2 preserves the immutable v1 snapshot and retains prior holdings and returns', () => {
  assert.equal(institutionFixture, institutionFixtureV2);
  assert.equal(institutionFixtureV1.simulation.version, 'v1');
  assert.equal(institutionFixtureV1.defaultAgentId, undefined);
  assert.ok(institutionFixtureV1.agents.every(agent => agent.series === undefined));
  assert.equal(Object.isFrozen(institutionFixtureV1.agents), true);
  assert.equal(Object.isFrozen(institutionFixtureV2.agents[0].series.ytd), true);
  assert.deepEqual(institutionFixtureV2.portfolio, institutionFixtureV1.portfolio);
  for (const agent of institutionFixtureV2.agents) {
    const old = institutionFixtureV1.agents.find(item => item.managerId === agent.managerId);
    assert.deepEqual(agent.returns, old.returns);
    assert.deepEqual(agent.portfolio, old.portfolio);
  }
});

test('institution periods share a rebased path and each headline equals its exact interval', () => {
  const { periods, defaultPeriod, simulation } = getInstitution('uteki');
  assert.deepEqual(periods.map(item => item.id), ['1m', 'ytd', '1y']);
  assert.equal(defaultPeriod, 'ytd');
  for (const period of periods) {
    const first = period.series[0], last = period.series.at(-1);
    assert.equal(first.date, period.start);
    assert.equal(last.date, period.end);
    assert.equal(period.end, simulation.asOf);
    assert.equal(first.value, 100);
    assert.equal(first.benchmarkValue, 100);
    assert.ok(Math.abs((last.value / first.value - 1) * 100 - period.returnPct) < 1e-9);
    assert.ok(Math.abs((last.benchmarkValue / first.benchmarkValue - 1) * 100 - period.benchmarkReturnPct) < 1e-9);
    for (const other of periods) {
      const overlap = other.series.filter(point => point.date >= period.start);
      for (const point of overlap) {
        const corresponding = period.series.find(item => item.date === point.date);
        if (!corresponding) continue;
        const otherStart = other.series.find(item => item.date === period.start);
        if (!otherStart) continue;
        assert.ok(Math.abs(point.value / otherStart.value * 100 - corresponding.value) < 1e-9);
        assert.ok(Math.abs(point.benchmarkValue / otherStart.benchmarkValue * 100 - corresponding.benchmarkValue) < 1e-9);
      }
    }
  }
});

test('every Agent period uses common comparison dates, exact return endpoints and a consistent overlapping history', () => {
  const context = getInstitution('uteki');
  for (const agent of context.agents) {
    assert.deepEqual(Object.keys(agent.series), context.periods.map(period => period.id));
    for (const period of context.periods) {
      const series = agent.series[period.id];
      assert.deepEqual(series.map(point => point.date), period.series.map(point => point.date));
      assert.equal(series[0].value, 100);
      assert.ok(Math.abs(series.at(-1).value - 100 - agent.returns[period.id]) < 1e-9);
      for (const other of context.periods) {
        const otherSeries = agent.series[other.id];
        const otherStart = otherSeries.find(point => point.date === period.start);
        if (!otherStart) continue;
        for (const point of series) {
          const corresponding = otherSeries.find(item => item.date === point.date);
          assert.ok(Math.abs(corresponding.value / otherStart.value * 100 - point.value) < 1e-9);
        }
      }
    }
  }
  const northMonth = context.agents.find(agent => agent.managerId === 'north').series['1m'];
  const fieldMonth = context.agents.find(agent => agent.managerId === 'field').series['1m'];
  assert.ok(northMonth.at(-1).value > 100);
  assert.ok(fieldMonth.at(-1).value < 100);
});

test('all explicitly supplied holdings and cash reconcile to 100 percent and the displayed value', () => {
  const context = getInstitution('uteki');
  for (const portfolio of [context.portfolio, ...context.agents.map(agent => agent.portfolio)]) {
    assert.equal(portfolio.holdings.reduce((sum, holding) => sum + holding.marketValue, portfolio.cashValue), portfolio.totalValue);
    assert.equal(portfolio.holdings.reduce((sum, holding) => sum + holding.weightPct, portfolio.cashWeightPct), 100);
    for (const holding of portfolio.holdings) assert.equal(holding.marketValue / portfolio.totalValue * 100, holding.weightPct);
  }
});

test('institution lookup rejects missing or mismatched scope without choosing the named fixture implicitly', () => {
  for (const id of [undefined, null, '', ' ', 'unknown', 'north', 'alphabet']) assert.throws(() => getInstitution(id));
  assert.throws(() => getInstitution('uteki', { companies: [], managers: [] }), /company.*unknown/);
  assert.throws(() => getInstitution('uteki', catalog, null), /unknown/);
  const data = structuredClone(catalog);
  data.managers = data.managers.filter(item => item.id !== 'field');
  assert.throws(() => getInstitution('uteki', data), /Manager field.*unknown/);
});

test('independently selected fixture supports three Agents, explicit non-first default, other companies and negative returns', () => {
  const data = { companies: [{ id: 'cedar' }, { id: 'pine' }], managers: [{ id: 'scout' }, { id: 'patient' }, { id: 'steady' }] };
  const fixture = {
    institution: { id: 'grove', name: 'Grove', description: 'Independent synthetic example.' },
    simulation: { id: 'grove-example', version: 'v2', isSimulated: true, asOf: '2024-06-30', currency: 'EUR', label: 'Illustrative', benchmarkLabel: 'Synthetic comparison', disclosure: 'Independent synthetic fixture.' },
    defaultPeriod: 'quarter', defaultAgentId: 'patient',
    periods: [{ id: 'quarter', label: 'Quarter', start: '2024-03-31', end: '2024-06-30', returnPct: -5, benchmarkReturnPct: -2,
      series: [{ date: '2024-03-31', value: 100, benchmarkValue: 100 }, { date: '2024-06-30', value: 95, benchmarkValue: 98 }] }],
    portfolio: { totalValue: 500, cashValue: 100, cashWeightPct: 20, holdings: [{ companyId: 'cedar', marketValue: 400, weightPct: 80 }] },
    agents: [
      { managerId: 'scout', returns: { quarter: -1 }, series: { quarter: [{ date: '2024-03-31', value: 100 }, { date: '2024-06-30', value: 99 }] }, portfolio: { totalValue: 100, cashValue: 100, cashWeightPct: 100, holdings: [] } },
      { managerId: 'patient', returns: { quarter: 3 }, series: { quarter: [{ date: '2024-03-31', value: 100 }, { date: '2024-06-30', value: 103 }] }, portfolio: { totalValue: 200, cashValue: 200, cashWeightPct: 100, holdings: [] } },
      { managerId: 'steady', returns: { quarter: 0 }, series: { quarter: [{ date: '2024-03-31', value: 100 }, { date: '2024-06-30', value: 100 }] }, portfolio: { totalValue: 300, cashValue: 300, cashWeightPct: 100, holdings: [] } },
    ],
  };
  assert.equal(getInstitution('grove', data, fixture), fixture);
  assert.equal(getInstitution('grove', data, fixture).defaultAgentId, 'patient');
  assert.equal(getInstitution('grove', data, fixture).agents.length, 3);
  assert.throws(() => getInstitution('uteki', data, fixture), /unknown/);
  fixture.portfolio.holdings[0].companyId = 'alphabet';
  assert.throws(() => getInstitution('grove', data, fixture), /company alphabet.*unknown/);
});

test('Agent selection and comparison paths reject gaps, foreign periods, mismatched dates and rewritten overlapping values', () => {
  for (const mutate of [
    fixture => { delete fixture.defaultAgentId; },
    fixture => { fixture.defaultAgentId = ''; },
    fixture => { fixture.defaultAgentId = 'unknown'; },
    fixture => { delete fixture.agents[0].series; },
    fixture => { delete fixture.agents[0].series.ytd; },
    fixture => { fixture.agents[0].series['5y'] = fixture.agents[0].series['1y']; },
    fixture => { fixture.agents[0].series.ytd.pop(); },
    fixture => { fixture.agents[0].series.ytd.reverse(); },
    fixture => { fixture.agents[0].series.ytd[1].date = '2026-01-30'; },
    fixture => { fixture.agents[0].series.ytd[1].date = fixture.agents[0].series.ytd[0].date; },
    fixture => { fixture.agents[0].series.ytd[1].value = NaN; },
    fixture => { fixture.agents[0].series.ytd[1].value = 0; },
    fixture => { fixture.agents[0].series.ytd.forEach(point => { point.value *= 2; }); },
    fixture => { fixture.agents[0].series.ytd.at(-1).value += 1; },
    fixture => { fixture.agents[0].series.ytd[1].value += 1; },
  ]) {
    const fixture = clone();
    mutate(fixture);
    assert.throws(() => getInstitution('uteki', catalog, fixture));
  }
});

test('corrupt disclosures, references and portfolio arithmetic reject rather than borrowing research data', () => {
  for (const mutate of [
    fixture => { fixture.simulation.isSimulated = false; },
    fixture => { delete fixture.simulation.version; },
    fixture => { fixture.simulation.currency = ''; },
    fixture => { fixture.simulation.disclosure = ''; },
    fixture => { fixture.simulation.asOf = '2026-02-30'; },
    fixture => { fixture.portfolio.holdings[0].companyId = 'unknown'; },
    fixture => { fixture.portfolio.holdings[0].companyId = fixture.portfolio.holdings[1].companyId; },
    fixture => { fixture.portfolio.holdings[0].weightPct = 25; },
    fixture => { fixture.portfolio.holdings[0].marketValue = 230000; },
    fixture => { fixture.portfolio.cashWeightPct = 9; },
    fixture => { fixture.portfolio.cashValue = -100; },
    fixture => { fixture.portfolio.totalValue = 0; },
    fixture => { fixture.portfolio.holdings.pop(); },
    fixture => { fixture.agents[0].managerId = 'unknown'; },
    fixture => { fixture.agents[0].managerId = fixture.agents[1].managerId; },
    fixture => { fixture.agents[0].portfolio.holdings[0].weightPct = 0; },
    fixture => { delete fixture.agents[0].returns.ytd; },
    fixture => { fixture.agents[0].returns['5y'] = 8; },
    fixture => { fixture.agents[0].returns.ytd = NaN; },
  ]) {
    const fixture = clone();
    mutate(fixture);
    assert.throws(() => getInstitution('uteki', catalog, fixture));
  }
});

test('invalid period scope, ordering and headline calculations reject explicitly', () => {
  for (const mutate of [
    fixture => { fixture.defaultPeriod = 'unknown'; },
    fixture => { fixture.periods[0].id = fixture.periods[1].id; },
    fixture => { fixture.periods[0].start = '2026-02-30'; },
    fixture => { fixture.periods[0].end = '2026-10-01'; },
    fixture => { fixture.periods[0].start = fixture.periods[0].end; },
    fixture => { fixture.periods[0].series.reverse(); },
    fixture => { fixture.periods[0].series[1].date = fixture.periods[0].start; },
    fixture => { fixture.periods[0].series.pop(); },
    fixture => { fixture.periods[0].series[0].value = 0; },
    fixture => { fixture.periods[0].series.forEach(point => { point.value *= 2; }); },
    fixture => { fixture.periods[0].series.forEach(point => { point.benchmarkValue *= 2; }); },
    fixture => { fixture.periods[0].returnPct += 1; },
    fixture => { fixture.periods[0].benchmarkReturnPct += 1; },
    fixture => { fixture.periods[0].series.at(-1).benchmarkValue += 1; },
  ]) {
    const fixture = clone();
    mutate(fixture);
    assert.throws(() => getInstitution('uteki', catalog, fixture));
  }
});

test('institution route is explicit, round-trips and has an institution context', () => {
  assert.deepEqual(INSTITUTION_DEMO_SCOPE, { institutionId: 'uteki', view: 'overview' });
  assert.equal(formatRoute(INSTITUTION_DEMO_SCOPE), '#/institution/uteki?view=overview');
  assert.deepEqual(parseRoute('#/institution/uteki?view=overview'), INSTITUTION_DEMO_SCOPE);
  assert.deepEqual(routeContext(INSTITUTION_DEMO_SCOPE), { entityType: 'institution', entity: institutionFixture.institution });
});

test('institution routes reject ambiguous entity/report fields, unsupported views and query parameters', () => {
  for (const field of ['companyId', 'managerId', 'reportId', 'version', 'sectionId']) {
    for (const value of [undefined, '', 'alphabet']) {
      assert.throws(() => formatRoute({ ...INSTITUTION_DEMO_SCOPE, [field]: value }));
      assert.throws(() => routeContext({ ...INSTITUTION_DEMO_SCOPE, [field]: value }));
    }
  }
  for (const route of [
    { institutionId: undefined, view: 'overview' }, { institutionId: 'unknown', view: 'overview' },
    { institutionId: 'uteki' }, { institutionId: 'uteki', view: 'reports' },
    { institutionId: 'uteki', view: 'report' }, { ...INSTITUTION_DEMO_SCOPE, period: 'ytd' },
  ]) assert.throws(() => formatRoute(route));
  for (const hash of [
    '#/institution/uteki', '#/institution/?view=overview', '#/institution/unknown?view=overview',
    '#/institution/uteki?view=reports', '#/institution/uteki?view=overview&view=overview',
    '#/institution/uteki?view=overview&company=alphabet', '#/institution/uteki?view=overview&manager=north',
    '#/institution/uteki?view=overview&report=alpha-north-main', '#/institution/uteki?view=overview&version=v1',
    '#/institution/uteki?view=overview&period=ytd', '#/company/alphabet?view=overview&institution=uteki',
  ]) assert.throws(() => parseRoute(hash), `must reject ${hash}`);
});
