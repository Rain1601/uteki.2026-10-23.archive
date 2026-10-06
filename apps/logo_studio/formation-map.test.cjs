const assert = require("node:assert/strict");
const test = require("node:test");
const { build } = require("./formation-map.js");

const width = 64;
const height = 80;
const bounds = { left: 0, top: 0, width: 1, height: 1 };
function density(sample) {
  return Float32Array.from({ length: width * height }, (_, index) => sample((index % width + 0.5) / width, (Math.floor(index / width) + 0.5) / height));
}
function mesh(source, target, options = {}) {
  return build({ source, target, width, height, bounds, columns: 40, rows: 40, ...options });
}
function uniquePoints({ vertices }) {
  const found = new Map();
  for (let i = 0; i < vertices.length; i += 4) {
    const point = Array.from(vertices.subarray(i, i + 4));
    found.set(`${point[0]},${point[1]}`, point);
  }
  return [...found.values()];
}
function pointAt(result, x, y) {
  return uniquePoints(result).find((point) => Math.abs(point[0] - x) < 1e-6 && Math.abs(point[1] - y) < 1e-6);
}

test("identical pigment preserves geometry, including empty rows and the negative channel", () => {
  const shape = density((x, y) => y < 0.2 || y > 0.85 || Math.abs(x - (0.45 + 0.15 * Math.sin(y * 7))) < 0.07 ? 0 : Math.exp(-Math.pow((x - 0.5) * 3, 2)));
  const result = mesh(shape, shape);
  assert.equal(result.count, 40 * 40 * 6);
  assert.equal(result.vertices.length, result.count * 4);
  for (const [sx, sy, tx, ty] of uniquePoints(result)) {
    assert.ok(Math.abs(sx - tx) < 2e-6);
    assert.ok(Math.abs(sy - ty) < 2e-6);
  }
});

test("transport gathers a uniform sheet into a bounded target and follows mass quantiles", () => {
  const source = density(() => 1);
  const target = density((x, y) => x >= 0.25 && x < 0.75 && y >= 0.3 && y < 0.7 ? 1 : 0);
  const result = mesh(source, target);
  const quarter = pointAt(result, 0.25, 0.25);
  const centre = pointAt(result, 0.5, 0.5);
  const threeQuarter = pointAt(result, 0.75, 0.75);
  assert.ok(Math.abs(quarter[2] - 0.375) < 0.005);
  assert.ok(Math.abs(quarter[3] - 0.4) < 0.005);
  assert.ok(Math.abs(centre[2] - 0.5) < 1e-6);
  assert.ok(Math.abs(centre[3] - 0.5) < 1e-6);
  assert.ok(Math.abs(threeQuarter[2] - 0.625) < 0.005);
  assert.ok(Math.abs(threeQuarter[3] - 0.6) < 0.005);
});

test("thread-to-drop transport is finite, ordered, bounded, and keeps every edge anchored", () => {
  const source = density((x, y) => Math.exp(-Math.pow((x - 0.45 - 0.13 * Math.sin(y * 9)) * 24, 2)) * (y > 0.04 && y < 0.96 ? 1 : 0));
  const target = density((x, y) => {
    const radius = 0.26 * Math.sin(Math.PI * (y - 0.18) / 0.64);
    return y > 0.18 && y < 0.82 && Math.abs(x - 0.52) < radius ? 1 : 0;
  });
  const result = mesh(source, target);
  const points = uniquePoints(result).sort((a, b) => a[1] - b[1] || a[0] - b[0]);
  for (let i = 0; i < points.length; i += 1) {
    const [sx, sy, tx, ty] = points[i];
    assert.ok(Number.isFinite(tx) && Number.isFinite(ty));
    assert.ok(tx >= 0 && tx <= 1 && ty >= 0 && ty <= 1);
    if (sx === 0 || sx === 1) assert.equal(tx, sx);
    if (sy === 0 || sy === 1) assert.equal(ty, sy);
    if (i && points[i - 1][1] === sy) {
      assert.ok(tx > points[i - 1][2], "each row must remain strictly ordered");
      assert.equal(ty, points[i - 1][3]);
    } else if (i) {
      assert.ok(ty > points[i - 1][3], "row order must remain strict");
    }
  }
  // Every triangle has the same signed orientation throughout linear travel.
  for (const progress of [0, 0.25, 0.5, 0.75, 1]) {
    for (let i = 0; i < result.vertices.length; i += 12) {
      const xy = [];
      for (let point = 0; point < 3; point += 1) {
        const at = i + point * 4;
        xy.push([result.vertices[at] * (1 - progress) + result.vertices[at + 2] * progress, result.vertices[at + 1] * (1 - progress) + result.vertices[at + 3] * progress]);
      }
      const cross = (xy[1][0] - xy[0][0]) * (xy[2][1] - xy[0][1]) - (xy[1][1] - xy[0][1]) * (xy[2][0] - xy[0][0]);
      assert.ok(cross < 0, "the mesh must not fold during interpolation");
    }
  }
});

test("swapping distributions reverses the transport at sampled transported coordinates", () => {
  const source = density(() => 1);
  const target = density((x, y) => (0.1 + x) * (0.2 + y * y));
  const forward = mesh(source, target, { columns: 100, rows: 100 });
  const inverse = mesh(target, source, { columns: 100, rows: 100 });
  const backPoints = uniquePoints(inverse);
  for (const [sx, sy, tx, ty] of [pointAt(forward, 0.2, 0.2), pointAt(forward, 0.5, 0.5), pointAt(forward, 0.8, 0.8)]) {
    const nearest = backPoints.reduce((best, point) => Math.hypot(point[0] - tx, point[1] - ty) < Math.hypot(best[0] - tx, best[1] - ty) ? point : best);
    assert.ok(Math.abs(nearest[2] - sx) < 0.018);
    assert.ok(Math.abs(nearest[3] - sy) < 0.018);
  }
});

test("changing source, target, or bounds changes the actual mapping", () => {
  const uniform = density(() => 1);
  const left = density((x) => x < 0.5 ? 1 : 0);
  const right = density((x) => x > 0.5 ? 1 : 0);
  assert.ok(pointAt(mesh(uniform, left), 0.5, 0.5)[2] < 0.3);
  assert.ok(pointAt(mesh(uniform, right), 0.5, 0.5)[2] > 0.7);
  // Geometry smoothing and 3% paper mass deliberately leave a soft boundary.
  assert.ok(pointAt(mesh(left, uniform), 0.5, 0.5)[2] > 0.96);
  const padded = uniquePoints(mesh(uniform, uniform, { bounds: { left: -0.3, top: -0.3, width: 1.6, height: 1.6 } }));
  assert.ok(padded.some(([x, y]) => Math.abs(x + 0.3) < 1e-6 && Math.abs(y + 0.3) < 1e-6));
  assert.ok(padded.some(([x, y]) => Math.abs(x - 1.3) < 1e-6 && Math.abs(y - 1.3) < 1e-6));
});

test("scanline pigment fluctuations do not turn the central channel into a zigzag", () => {
  const uniform = density(() => 1);
  const target = density((x, y) => {
    const imbalance = Math.floor(y * height) % 2 ? 0.2 : -0.2;
    const left = Math.exp(-(((x - 0.31) / 0.055) ** 2));
    const right = Math.exp(-(((x - 0.69) / 0.055) ** 2));
    return left * (1 + imbalance) + right * (1 - imbalance);
  });
  const result = mesh(uniform, target, { columns: 60, rows: 120 });
  const channel = uniquePoints(result)
    .filter(([sx, sy]) => Math.abs(sx - 0.5) < 1e-6 && sy > 0.12 && sy < 0.88)
    .sort((a, b) => a[1] - b[1]);
  for (let i = 1; i < channel.length - 1; i += 1) {
    const secondDifference = channel[i + 1][2] - 2 * channel[i][2] + channel[i - 1][2];
    assert.ok(Math.abs(secondDifference) < 0.001, "single-row density changes must not survive as serrations");
    assert.ok(Math.abs(channel[i][2] - 0.5) < 0.01, "the symmetric two-lobe channel should stay centred");
  }
});

test("invalid densities and empty inputs fail explicitly instead of producing NaN meshes", () => {
  const valid = density(() => 1);
  const empty = density(() => 0);
  assert.throws(() => mesh(empty, valid), /source must contain some pigment/);
  assert.throws(() => mesh(valid, empty), /target must contain some pigment/);
  for (const bad of [NaN, Infinity, -1]) {
    const pixels = valid.slice();
    pixels[3] = bad;
    assert.throws(() => mesh(pixels, valid), /finite and non-negative/);
  }
  assert.throws(() => mesh(valid.subarray(1), valid), /width \* height/);
  assert.throws(() => mesh(valid, valid, { columns: 0 }), /columns/);
  assert.throws(() => mesh(valid, valid, { bounds: { left: 0, top: 0, width: 0, height: 1 } }), /bounds/);
});
