import test from 'node:test';
import assert from 'node:assert/strict';
import { placeChartEventPopover } from './chart-event-popover.mjs';

const base = {
  bounds: { left: 100, right: 1100, top: 80, bottom: 680 },
  anchor: { left: 580, right: 620, top: 520, bottom: 550 },
  size: { width: 340, height: 280 },
};

function withinBounds(result, bounds) {
  for (const key of ['left', 'top', 'width', 'maxHeight', 'arrowX']) assert.ok(Number.isFinite(result[key]), key);
  assert.ok(result.width >= 0 && result.maxHeight >= 0);
  assert.ok(result.left >= bounds.left && result.left + result.width <= bounds.right);
  assert.ok(result.top >= bounds.top && result.top + result.maxHeight <= bounds.bottom);
  assert.ok(result.arrowX >= 0 && result.arrowX <= result.width);
}

test('opens above the marker in client coordinates with the arrow centered', () => {
  const result = placeChartEventPopover(base);
  assert.deepEqual(result, { left: 430, top: 228, width: 340, maxHeight: 280, placement: 'above', arrowX: 170 });
  withinBounds(result, base.bounds);
  assert.equal(result.top + result.maxHeight + 12, base.anchor.top);
});

test('prefers a complete card above even when below has more available room', () => {
  const result = placeChartEventPopover({ ...base, anchor: { left: 580, right: 620, top: 260, bottom: 290 }, size: { width: 340, height: 150 } });
  assert.equal(result.placement, 'above');
  assert.equal(result.maxHeight, 150);
});

test('translates at both horizontal edges without scaling the card or losing its marker', () => {
  for (const anchor of [
    { left: 108, right: 140, top: 520, bottom: 550 },
    { left: 1060, right: 1092, top: 520, bottom: 550 },
  ]) {
    const result = placeChartEventPopover({ ...base, anchor });
    assert.equal(result.width, base.size.width);
    assert.equal(result.maxHeight, base.size.height);
    assert.equal(result.left + result.arrowX, (anchor.left + anchor.right) / 2);
    withinBounds(result, base.bounds);
  }
});

test('uses the space below a marker near the visible top after scrolling', () => {
  const bounds = { left: 100, right: 1100, top: 360, bottom: 680 };
  const anchor = { left: 580, right: 620, top: 375, bottom: 405 };
  const result = placeChartEventPopover({ ...base, anchor, bounds });
  assert.equal(result.placement, 'below');
  assert.equal(result.top, 417);
  assert.equal(result.maxHeight, 255);
  withinBounds(result, bounds);
});

test('uses the larger vertical space and caps height when neither side fits', () => {
  const bounds = { left: 0, right: 390, top: 0, bottom: 240 };
  const anchor = { left: 170, right: 210, top: 140, bottom: 170 };
  const result = placeChartEventPopover({ ...base, anchor, bounds });
  assert.equal(result.placement, 'above');
  assert.equal(result.top, 8);
  assert.equal(result.maxHeight, 120);
  assert.equal(result.top + result.maxHeight, anchor.top - 12);
  withinBounds(result, bounds);
});

test('caps width for narrow windows and keeps fractional coordinates', () => {
  const bounds = { left: 0.25, right: 280.75, top: 10.5, bottom: 700.5 };
  const result = placeChartEventPopover({ ...base, bounds, anchor: { left: 249.5, right: 270.5, top: 510.5, bottom: 530.5 } });
  assert.equal(result.width, 264.5);
  assert.equal(result.left, 8.25);
  assert.equal(result.top, 218.5);
  assert.equal(result.left + result.arrowX, 260);
  withinBounds(result, bounds);
});

test('zero available vertical space returns a zero height instead of covering the marker', () => {
  const bounds = { left: 0, right: 300, top: 0, bottom: 100 };
  const result = placeChartEventPopover({ ...base, bounds, anchor: { left: 100, right: 130, top: 0, bottom: 100 } });
  assert.equal(result.maxHeight, 0);
  withinBounds(result, bounds);
});

test('handles tiny positive bounds and oversized padding without negative dimensions', () => {
  const bounds = { left: 2, right: 3, top: 4, bottom: 5 };
  const result = placeChartEventPopover({ ...base, bounds, padding: 100 });
  assert.equal(result.width, 0);
  assert.equal(result.maxHeight, 0);
  withinBounds(result, bounds);
});

test('keeps a partially clipped anchor within bounds and clamps the arrow at a card corner', () => {
  const result = placeChartEventPopover({ ...base, anchor: { left: 75, right: 105, top: 520, bottom: 550 } });
  assert.equal(result.left, 108);
  assert.equal(result.arrowX, 8);
  withinBounds(result, base.bounds);
});

test('accepts point anchors, zero gaps and padding without mutating input', () => {
  const input = { ...base, anchor: { left: 600, right: 600, top: 520, bottom: 520 }, gap: 0, padding: 0 };
  const before = structuredClone(input);
  const result = placeChartEventPopover(input);
  assert.equal(result.top + result.maxHeight, 520);
  assert.equal(result.arrowX, 170);
  assert.deepEqual(input, before);
});

test('rejects missing, nonfinite, reversed and nonpositive required geometry', () => {
  assert.throws(() => placeChartEventPopover(), /anchor/);
  for (const label of ['anchor', 'bounds']) {
    for (const edge of ['left', 'right', 'top', 'bottom']) {
      for (const value of [NaN, Infinity, -Infinity, '10', undefined]) {
        assert.throws(() => placeChartEventPopover({ ...base, [label]: { ...base[label], [edge]: value } }), new RegExp(`${label}.${edge}`));
      }
    }
    assert.throws(() => placeChartEventPopover({ ...base, [label]: { ...base[label], left: 1200 } }), /ordered edges/);
    assert.throws(() => placeChartEventPopover({ ...base, [label]: { ...base[label], bottom: 0 } }), /ordered edges/);
  }
  assert.throws(() => placeChartEventPopover({ ...base, bounds: { ...base.bounds, right: 100 } }), /positive dimensions/);
  for (const dimension of ['width', 'height']) {
    for (const value of [0, -1, NaN, Infinity, '340']) {
      assert.throws(() => placeChartEventPopover({ ...base, size: { ...base.size, [dimension]: value } }), new RegExp(`size.${dimension}`));
    }
  }
  for (const dimension of ['gap', 'padding']) {
    for (const value of [-1, NaN, Infinity, '8']) assert.throws(() => placeChartEventPopover({ ...base, [dimension]: value }), new RegExp(dimension));
  }
});

test('supports large finite coordinates and rejects overflowing rectangle dimensions', () => {
  const bounds = { left: 1e9, right: 1e9 + 1000, top: 1e9, bottom: 1e9 + 700 };
  const anchor = { left: 1e9 + 480, right: 1e9 + 520, top: 1e9 + 600, bottom: 1e9 + 630 };
  const result = placeChartEventPopover({ ...base, bounds, anchor });
  withinBounds(result, bounds);
  assert.equal(result.width, 340);
  assert.equal(result.maxHeight, 280);
  assert.throws(() => placeChartEventPopover({ ...base, bounds: { ...bounds, left: -1e308, right: 1e308 } }), /ordered edges/);
});
