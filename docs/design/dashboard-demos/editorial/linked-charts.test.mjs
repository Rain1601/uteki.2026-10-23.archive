import test from 'node:test';
import assert from 'node:assert/strict';
import { validateLinkedCharts, buildLinkedChartModel, LinkedCharts } from './linked-charts.mjs';

const sample = () => ({
  points: [{ id: 'first', label: 'First' }, { id: 'second', label: 'Second' }, { id: 'third', label: 'Third' }, { id: 'fourth', label: 'Fourth' }],
  series: [
    { id: 'trend', title: 'Trend', unit: '%', type: 'line', values: [{ id: 'fourth', value: 5 }, { id: 'first', value: 0 }, { id: 'third', value: null }, { id: 'second', value: -10 }] },
    { id: 'change', title: 'Change', unit: 'units', type: 'bars', values: [{ id: 'third', value: 0 }, { id: 'fourth', value: null }, { id: 'first', value: 20 }, { id: 'second', value: -20 }] },
  ],
  labels: { hint: 'Hover, focus, or use arrow keys', clear: 'Clear', missing: 'Unavailable', pinned: 'Pinned' },
});

test('values align by identity rather than payload position; canonical order and input are retained', () => {
  const input = sample(), before = structuredClone(input);
  const model = buildLinkedChartModel(input);
  assert.deepEqual(model.series[0].marks.map(mark => mark.value), [0, -10, null, 5]);
  assert.deepEqual(model.series[1].marks.map(mark => mark.value), [20, -20, 0, null]);
  assert.deepEqual(model.positions.map(point => point.id), input.points.map(point => point.id));
  assert.deepEqual(input, before);
});

test('line paths end before gaps and restart after them, never treating null as zero', () => {
  const model = buildLinkedChartModel(sample());
  const line = model.series[0];
  assert.equal(line.paths.length, 2);
  assert.equal((line.paths[0].match(/L/g) || []).length, 1);
  assert.match(line.paths[1], /^M/);
  assert.doesNotMatch(line.paths.join(' '), new RegExp(`${line.marks[2].x},`));
  assert.equal(line.marks[0].value, 0);
  assert.equal(line.marks[0].y, line.zero);
  assert.equal(line.marks[2].y, null);
});

test('signed bars lie on the correct side of the zero axis, and zero is a line', () => {
  const bars = buildLinkedChartModel(sample()).series[1];
  assert.ok(bars.marks[0].y < bars.zero);
  assert.ok(bars.marks[1].y > bars.zero);
  assert.equal(bars.marks[2].y, bars.zero);
  const html = LinkedCharts(sample());
  assert.match(html, /linked-chart-zero-value/);
  assert.equal((html.match(/class="linked-chart-gap"/g) || []).length, 2);
  assert.match(html, /Second; Trend: -10 %; Change: -20 units/);
  assert.match(html, /Fourth; Trend: 5 %; Change: Unavailable/);
});

test('single-sided, zero, null and extremely large finite values create finite bounded coordinates', () => {
  for (const values of [[0, 0, 0, 0], [null, null, null, null], [1, 2, 3, 4], [-1, -2, -3, -4], [-Number.MAX_VALUE, Number.MAX_VALUE, 0, null]]) {
    const input = sample();
    input.series.forEach(item => { item.values = input.points.map((point, index) => ({ id: point.id, value: values[index] })); });
    const model = buildLinkedChartModel(input);
    for (const item of model.series) for (const mark of item.marks) {
      assert.ok(Number.isFinite(mark.x));
      assert.ok(Number.isFinite(mark.zero));
      if (mark.y !== null) assert.ok(Number.isFinite(mark.y) && mark.y >= item.top && mark.y <= item.bottom);
    }
    assert.doesNotMatch(LinkedCharts(input), /NaN|Infinity/);
  }
});

test('invalid point contracts reject unknown, repeated, omitted and nonnumeric values', () => {
  const edits = [
    input => { input.points[1].id = input.points[0].id; },
    input => { input.points[1].id = 'unsafe"'; },
    input => { input.series[0].id = input.series[1].id; },
    input => { input.series[0].values[0].id = 'unknown'; },
    input => { input.series[0].values[0].id = input.series[0].values[1].id; },
    input => { input.series[0].values.pop(); },
    input => { input.series[0].values[0].value = NaN; },
    input => { input.series[0].values[0].value = Infinity; },
    input => { input.series[0].values[0].value = '3'; },
    input => { delete input.series[0].values[0].value; },
    input => { input.series[0].type = 'pie'; },
    input => { input.series[0].type = 'bars'; },
    input => { input.points = input.points.slice(0, 2); },
    input => { input.labels.missing = ''; },
  ];
  for (const edit of edits) { const input = sample(); edit(input); assert.throws(() => validateLinkedCharts(input)); }
});

test('text escapes, one keyboard entry point, and exactly one shared reference span both plots', () => {
  const input = sample(); input.points[0].label = '<script>bad</script>'; input.series[0].title = '<img src=x>';
  const html = LinkedCharts(input, 'chart-case');
  assert.doesNotMatch(html, /<script>|<img/);
  assert.match(html, /&lt;script&gt;/);
  assert.equal((html.match(/tabindex="0"/g) || []).length, 1);
  assert.equal((html.match(/class="linked-chart-reference"/g) || []).length, 1);
  assert.match(html, /y1="42" y2="390"/);
  assert.equal((html.match(/aria-describedby="chart-case-hint"/g) || []).length, 4);
  assert.equal((html.match(/aria-pressed="false"/g) || []).length, 4);
});

test('a full detail label is accessible while the shared axis stays compact', () => {
  const input = sample(); input.points[0].detail = '2026-10-04 — Full record title';
  const model = buildLinkedChartModel(input), html = LinkedCharts(input);
  assert.equal(model.points[0].detail, '2026-10-04 — Full record title');
  assert.match(html, /aria-label="2026-10-04 — Full record title; Trend/);
  assert.match(html, /class="linked-chart-label"[^>]*>First<\/text>/);
  assert.doesNotMatch(html, /class="linked-chart-label"[^>]*>2026/);
  input.points[0].detail = '';
  assert.throws(() => validateLinkedCharts(input));
});
