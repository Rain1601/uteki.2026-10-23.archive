import test from 'node:test';
import assert from 'node:assert/strict';
import { createPerformanceGeometry } from './performance-geometry.mjs';

function fixture() {
  return {
    period: {
      start: '2026-01-01', end: '2026-01-11',
      series: [
        { date: '2026-01-01', benchmarkValue: 100 },
        { date: '2026-01-05', benchmarkValue: 102 },
        { date: '2026-01-11', benchmarkValue: 110 },
      ],
    },
    agents: [
      { managerId: 'synthetic-growth', series: [
        { date: '2026-01-01', value: 100 },
        { date: '2026-01-03', value: 105 },
        { date: '2026-01-11', value: 120 },
      ] },
      { managerId: 'synthetic-value', series: [
        { date: '2026-01-01', value: 100 },
        { date: '2026-01-08', value: 90 },
        { date: '2026-01-11', value: 98 },
      ] },
    ],
  };
}
const close = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} != ${expected}`);
const geometry = () => { const { period, agents } = fixture(); return createPerformanceGeometry(period, agents); };

test('all selected Managers and benchmark share the existing padded return scale and date axis', () => {
  const chart = geometry();
  assert.deepEqual([chart.minimum, chart.maximum, chart.min, chart.max], [-10, 20, -13, 23]);
  assert.equal(chart.x('2026-01-01'), 42);
  assert.equal(chart.x('2026-01-11'), 976);
  close(chart.x('2026-01-03'), 228.8);
  close(chart.y(-10), 434 - 3 / 36 * 398);
  close(chart.y(20), 434 - 33 / 36 * 398);
});

test('pointAt interpolates unequal sample intervals using actual dates and the selected Manager only', () => {
  const chart = geometry();
  // Jan 7 is four of the eight days from Jan 3 to Jan 11, so the plotted return is 12.5%.
  assert.deepEqual(chart.pointAt('synthetic-growth', '2026-01-07'), { x: chart.x('2026-01-07'), y: chart.y(12.5) });
  close(chart.pointAt('synthetic-value', '2026-01-07').y, chart.y(-60 / 7));
  for (const [id, endReturn] of [['synthetic-growth', 20], ['synthetic-value', -2]]) {
    assert.deepEqual(chart.pointAt(id, '2026-01-01'), { x: 42, y: chart.y(0) });
    assert.deepEqual(chart.pointAt(id, '2026-01-11'), { x: 976, y: chart.y(endReturn) });
  }
  assert.deepEqual(chart.pointAt('synthetic-value', '2026-01-08'), { x: chart.x('2026-01-08'), y: chart.y(-10) });
});

test('benchmark alone can set extrema, and flat series retain the original nonzero padding', () => {
  const { period, agents } = fixture();
  period.series[1].benchmarkValue = 160;
  period.series[2].benchmarkValue = 70;
  const comparison = createPerformanceGeometry(period, agents);
  assert.deepEqual([comparison.minimum, comparison.maximum, comparison.min, comparison.max], [-30, 60, -39, 69]);
  period.series.forEach(point => { point.benchmarkValue = 100; });
  agents.forEach(agent => agent.series.forEach(point => { point.value = 100; }));
  const flat = createPerformanceGeometry(period, agents);
  assert.deepEqual([flat.minimum, flat.maximum, flat.min, flat.max], [0, 0, -.1, .1]);
  assert.equal(flat.y(0), 235);
});

test('period and Manager scopes are mandatory; unknown or duplicate Managers never select a fallback', () => {
  const { period, agents } = fixture();
  for (const missing of [undefined, null, {}, { start: period.start }, { end: period.end }]) {
    assert.throws(() => createPerformanceGeometry(missing, agents), /date/);
  }
  for (const missing of [undefined, null, []]) assert.throws(() => createPerformanceGeometry(period, missing), /explicit/);
  for (const id of [undefined, null, '', ' ', ' synthetic-growth ', 1]) {
    assert.throws(() => createPerformanceGeometry(period, [{ ...agents[0], managerId: id }]), /Manager ID/);
  }
  assert.throws(() => createPerformanceGeometry(period, [agents[0], agents[0]]), /unique/);
  for (const id of [undefined, null, '', 'unknown', 'synthetic-growth ']) {
    assert.throws(() => geometry().pointAt(id, '2026-01-07'), /Manager/);
  }
});

test('date inputs are calendar-valid ISO days, bounded to the explicit nonempty period', () => {
  const chart = geometry(), { period, agents } = fixture();
  for (const date of [null, undefined, '', 0, '2026-1-01', '2026-02-30', '2026-01-01T00:00:00Z', ' 2026-01-01']) {
    assert.throws(() => chart.x(date), /date/);
    assert.throws(() => chart.pointAt('synthetic-growth', date), /date/);
    assert.throws(() => createPerformanceGeometry({ ...period, start: date }, agents), /date/);
  }
  for (const date of ['2025-12-31', '2026-01-12']) {
    assert.throws(() => chart.x(date), /outside/);
    assert.throws(() => chart.pointAt('synthetic-value', date), /outside/);
  }
  for (const end of [period.start, '2025-12-31']) {
    assert.throws(() => createPerformanceGeometry({ ...period, end }, agents), /follow/);
  }
  const leap = { start: '2024-02-28', end: '2024-03-01', series: [{ date: '2024-02-28', benchmarkValue: 100 }, { date: '2024-03-01', benchmarkValue: 101 }] };
  const leapAgent = [{ managerId: 'leap', series: leap.series.map(({ date, benchmarkValue }) => ({ date, value: benchmarkValue })) }];
  assert.equal(createPerformanceGeometry(leap, leapAgent).x('2024-02-29'), 509);
});

test('each series must have ordered unique valid samples and cover both period endpoints without extrapolation', () => {
  const mutations = [
    rows => rows.slice(0, 1),
    rows => [rows[0], rows[0], rows[2]],
    rows => [rows[1], rows[0], rows[2]],
    rows => rows.slice(1),
    rows => rows.slice(0, -1),
    rows => [{ ...rows[0], date: '2025-12-31' }, ...rows.slice(1)],
    rows => [...rows.slice(0, -1), { ...rows.at(-1), date: '2026-01-12' }],
    rows => [rows[0], { ...rows[1], date: '2026-02-30' }, rows[2]],
  ];
  for (const mutate of mutations) {
    const { period, agents } = fixture();
    assert.throws(() => createPerformanceGeometry(period, [{ ...agents[0], series: mutate(agents[0].series) }, agents[1]]));
    assert.throws(() => createPerformanceGeometry({ ...period, series: mutate(period.series) }, agents));
  }
  const { period, agents } = fixture();
  for (const missing of [undefined, null, []]) {
    assert.throws(() => createPerformanceGeometry({ ...period, series: missing }, agents), /samples/);
    assert.throws(() => createPerformanceGeometry(period, [{ ...agents[0], series: missing }]), /samples/);
  }
});

test('nonfinite values and overflowing coordinate scales fail explicitly, without number coercion', () => {
  for (const value of [NaN, Infinity, -Infinity, undefined, null, '100']) {
    const { period, agents } = fixture();
    agents[1].series[1].value = value;
    assert.throws(() => createPerformanceGeometry(period, agents), /finite/);
    const valid = fixture();
    valid.period.series[1].benchmarkValue = value;
    assert.throws(() => createPerformanceGeometry(valid.period, valid.agents), /finite/);
    assert.throws(() => geometry().y(value), /finite/);
  }
  const { period, agents } = fixture();
  agents[0].series[1].value = Number.MAX_VALUE;
  agents[1].series[1].value = -Number.MAX_VALUE;
  assert.throws(() => createPerformanceGeometry(period, agents), /range.*finite/i);
});

test('geometry snapshots its validated input and does not mutate fixtures', () => {
  const { period, agents } = fixture(), before = structuredClone({ period, agents });
  const chart = createPerformanceGeometry(period, agents);
  assert.deepEqual({ period, agents }, before);
  const expected = chart.pointAt('synthetic-growth', '2026-01-07');
  agents[0].series[1].date = '2026-01-10';
  agents[0].series[1].value = 500;
  period.start = '2025-01-01';
  assert.deepEqual(chart.pointAt('synthetic-growth', '2026-01-07'), expected);
});
