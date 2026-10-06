import test from 'node:test';
import assert from 'node:assert/strict';
import { allocationHistoryFixtureV1, getAllocationHistory, validateAllocationHistoryFixture } from './allocation-history.mjs';
import { institutionFixture } from './institution-data.mjs';

const clone = () => structuredClone(allocationHistoryFixtureV1);
const query = { institutionId: 'uteki', managerId: 'north', start: '2025-09-30', end: '2026-09-30' };

test('named mock histories are immutable, independently disclosed and end at the current Agent allocations', () => {
  const before = JSON.stringify(institutionFixture);
  assert.equal(validateAllocationHistoryFixture(allocationHistoryFixtureV1), allocationHistoryFixtureV1);
  assert.equal(allocationHistoryFixtureV1.isSimulated, true);
  assert.equal(allocationHistoryFixtureV1.version, 'v1');
  assert.match(allocationHistoryFixtureV1.disclosure, /不从当前持仓、买卖事件或收益反推/);
  for (const agent of institutionFixture.agents) {
    const result = getAllocationHistory({ ...query, managerId: agent.managerId });
    const last = result.snapshots.at(-1);
    assert.equal(result.snapshots.length, 16);
    assert.equal(Object.isFrozen(result.snapshots[0].holdings[0]), true);
    assert.equal(Object.isFrozen(allocationHistoryFixtureV1.histories[0].snapshots[0]), true);
    assert.equal(last.cashWeightPct, agent.portfolio.cashWeightPct);
    assert.deepEqual(last.holdings, agent.portfolio.holdings.map(({ companyId, weightPct }) => ({ companyId, weightPct })));
    assert.notDeepEqual(result.snapshots[0].holdings, last.holdings);
  }
  assert.equal(JSON.stringify(institutionFixture), before);
});

test('all requested demo periods use exact dates aligned with existing charts', () => {
  for (const agent of institutionFixture.agents) {
    for (const period of institutionFixture.periods) {
      const result = getAllocationHistory({ institutionId: 'uteki', managerId: agent.managerId, start: period.start, end: period.end });
      assert.deepEqual(result.snapshots.map(point => point.date), agent.series[period.id].map(point => point.date));
      assert.equal(result.start, period.start);
      assert.equal(result.end, period.end);
      assert.equal(result.sampling, 'explicit-snapshots');
      assert.equal(result.simulation.isSimulated, true);
    }
  }
  assert.equal(getAllocationHistory({ ...query, start: '2026-08-31' }).snapshots.length, 5);
});

test('every snapshot has every company explicitly represented and totals 100 including cash', () => {
  for (const history of allocationHistoryFixtureV1.histories) {
    for (const point of history.snapshots) {
      assert.deepEqual(point.holdings.map(item => item.companyId), history.companyIds);
      assert.equal(point.holdings.reduce((total, item) => total + item.weightPct, point.cashWeightPct), 100);
    }
  }
  assert.equal(getAllocationHistory(query).snapshots[0].holdings.find(item => item.companyId === 'nvidia').weightPct, 0);
  assert.equal(getAllocationHistory({ ...query, managerId: 'field' }).snapshots[0].holdings.find(item => item.companyId === 'microsoft').weightPct, 0);
});

test('selection never falls back for missing, blank, conflicting or unknown business scope', () => {
  assert.throws(() => getAllocationHistory(), /explicit/);
  for (const key of ['institutionId', 'managerId', 'start', 'end']) {
    for (const value of [undefined, null, '', ' ', 1]) {
      assert.throws(() => getAllocationHistory({ ...query, [key]: value }));
    }
  }
  assert.throws(() => getAllocationHistory({ ...query, institutionId: 'other' }), /institution is unknown/);
  assert.throws(() => getAllocationHistory({ ...query, managerId: 'other' }), /Manager is unknown/);
  assert.throws(() => getAllocationHistory({ ...query, start: '2026-02-30' }), /invalid/);
  assert.throws(() => getAllocationHistory({ ...query, start: query.end }), /precede/);
  assert.throws(() => getAllocationHistory({ ...query, start: '2026-10-01' }), /precede/);
});

test('coverage gaps are explicit rather than interpolated, truncated or filled with current values', () => {
  for (const scope of [
    { ...query, start: '2025-09-29' },
    { ...query, end: '2026-10-01' },
  ]) assert.throws(() => getAllocationHistory(scope), /coverage/);
  for (const scope of [
    { ...query, start: '2026-09-08' },
    { ...query, end: '2026-09-29' },
  ]) assert.throws(() => getAllocationHistory(scope), /no explicit snapshot/);
});

test('invalid weights, totals, missing zeroes and duplicate companies fail validation', () => {
  for (const value of [NaN, Infinity, -1, 101, '24']) {
    const fixture = clone();
    fixture.histories[0].snapshots[0].holdings[0].weightPct = value;
    assert.throws(() => validateAllocationHistoryFixture(fixture), /weight is invalid/);
  }
  const total = clone();
  total.histories[0].snapshots[0].cashWeightPct += 1;
  assert.throws(() => validateAllocationHistoryFixture(total), /total 100/);
  const missingZero = clone();
  missingZero.histories[0].snapshots[0].holdings.splice(2, 1);
  assert.throws(() => validateAllocationHistoryFixture(missingZero), /explicit zero/);
  const duplicate = clone();
  duplicate.histories[0].snapshots[0].holdings.push({ companyId: 'nvidia', weightPct: 0 });
  assert.throws(() => validateAllocationHistoryFixture(duplicate), /company must be unique/);
});

test('duplicate, unsorted, invalid and truncated snapshot dates fail validation', () => {
  const duplicate = clone();
  duplicate.histories[0].snapshots[1].date = duplicate.histories[0].snapshots[0].date;
  assert.throws(() => validateAllocationHistoryFixture(duplicate), /unique and sorted/);
  const reversed = clone();
  reversed.histories[0].snapshots.reverse();
  assert.throws(() => validateAllocationHistoryFixture(reversed), /unique and sorted/);
  const invalid = clone();
  invalid.histories[0].snapshots[0].date = '2025-09-31';
  assert.throws(() => validateAllocationHistoryFixture(invalid), /invalid/);
  const truncated = clone();
  truncated.histories[0].snapshots.shift();
  assert.throws(() => validateAllocationHistoryFixture(truncated), /endpoints/);
});

test('final snapshot is checked against the named current reference, including the correct Agent', () => {
  const fixture = clone();
  const last = fixture.histories[0].snapshots.at(-1);
  last.holdings[0].weightPct += 1;
  last.holdings[1].weightPct -= 1;
  assert.throws(() => validateAllocationHistoryFixture(fixture), /final company weights/);
  const cash = clone();
  cash.histories[0].snapshots.at(-1).cashWeightPct += 1;
  cash.histories[0].snapshots.at(-1).holdings[0].weightPct -= 1;
  assert.throws(() => validateAllocationHistoryFixture(cash), /final cash/);
  const wrongDate = clone();
  wrongDate.currentSnapshot.asOf = '2026-09-29';
  assert.throws(() => validateAllocationHistoryFixture(wrongDate), /date must match/);
  const wrongAgent = clone();
  wrongAgent.currentSnapshot.agents[1].managerId = 'north';
  assert.throws(() => validateAllocationHistoryFixture(wrongAgent), /Manager must be unique/);
});

test('fixture scope and simulation identity are required and cannot borrow another reference', () => {
  const mutations = [
    fixture => { fixture.isSimulated = false; },
    fixture => { fixture.scope.institutionId = 'other'; },
    fixture => { fixture.scope.managerIds = ['north']; },
    fixture => { fixture.histories[0].managerId = 'unknown'; },
    fixture => { fixture.histories[0].snapshots[0].holdings[0].companyId = 'unknown'; },
    fixture => { fixture.scope.companyIds.push('cash'); },
    fixture => { delete fixture.currentSnapshot; },
  ];
  for (const mutate of mutations) {
    const fixture = clone(); mutate(fixture);
    assert.throws(() => validateAllocationHistoryFixture(fixture));
  }
});

function syntheticFixture() {
  return {
    id: 'synthetic-allocation', version: 'test-v1', isSimulated: true,
    label: '测试快照', labelEn: 'Synthetic snapshots', disclosure: '独立测试数据', disclosureEn: 'Independent test data',
    sampling: 'explicit-snapshots',
    scope: { institutionId: 'independent-fund', managerIds: ['independent-manager'], companyIds: ['issuer-x', 'issuer-y'] },
    coverage: { start: '2024-01-01', end: '2024-03-01' },
    currentSnapshot: { id: 'independent-current', version: 'test-v1', institutionId: 'independent-fund', asOf: '2024-03-01',
      agents: [{ managerId: 'independent-manager', holdings: [{ companyId: 'issuer-x', weightPct: 65 }], cashWeightPct: 35 }],
    },
    histories: [{ managerId: 'independent-manager', companyIds: ['issuer-x', 'issuer-y'], snapshots: [
      { date: '2024-01-01', holdings: [{ companyId: 'issuer-x', weightPct: 40 }, { companyId: 'issuer-y', weightPct: 40 }], cashWeightPct: 20 },
      { date: '2024-02-01', holdings: [{ companyId: 'issuer-x', weightPct: 60 }, { companyId: 'issuer-y', weightPct: 20 }], cashWeightPct: 20 },
      { date: '2024-03-01', holdings: [{ companyId: 'issuer-x', weightPct: 65 }, { companyId: 'issuer-y', weightPct: 0 }], cashWeightPct: 35 },
    ] }],
  };
}

test('another explicit institution, Manager, companies and period work without Uteki defaults', () => {
  const fixture = syntheticFixture();
  const before = structuredClone(fixture);
  const scope = { institutionId: 'independent-fund', managerId: 'independent-manager', start: '2024-02-01', end: '2024-03-01' };
  const result = getAllocationHistory(scope, fixture);
  assert.deepEqual(result.companyIds, ['issuer-x', 'issuer-y']);
  assert.deepEqual(result.snapshots.map(item => item.date), ['2024-02-01', '2024-03-01']);
  assert.equal(result.snapshots[1].holdings[1].weightPct, 0);
  assert.equal(result.simulation.id, 'synthetic-allocation');
  assert.deepEqual(fixture, before);
  assert.equal(Object.isFrozen(fixture.histories), false);
  assert.equal(Object.isFrozen(result.snapshots), true);
  assert.throws(() => getAllocationHistory(query, fixture), /institution is unknown/);
  assert.throws(() => getAllocationHistory(scope), /institution is unknown/);
});

test('an exited historical company must explicitly end at zero if absent from the current reference', () => {
  const fixture = syntheticFixture();
  assert.doesNotThrow(() => validateAllocationHistoryFixture(fixture));
  // Even a tiny residual within the comparison tolerance is not explicit zero.
  fixture.histories[0].snapshots.at(-1).holdings[1].weightPct = 0.0000001;
  fixture.histories[0].snapshots.at(-1).holdings[0].weightPct -= 0.0000001;
  assert.throws(() => validateAllocationHistoryFixture(fixture), /must end at explicit zero/);
});
