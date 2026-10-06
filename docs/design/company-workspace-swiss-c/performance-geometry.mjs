const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

// One coordinate space for the curve, trade anchors and SVG viewport.
export const PERFORMANCE_PLOT = Object.freeze({width:1000,height:480,left:42,right:976,top:36,bottom:434,dateY:472});

function dateStamp(value, label) {
  if (typeof value !== 'string' || !DATE_PATTERN.test(value)) {
    throw new Error(`${label} must be an explicit YYYY-MM-DD date`);
  }
  const stamp = Date.parse(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(stamp) || new Date(stamp).toISOString().slice(0, 10) !== value) {
    throw new Error(`${label} must be a valid calendar date`);
  }
  return stamp;
}

function finite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

function checkedSeries(series, valueKey, label, start, end) {
  if (!Array.isArray(series) || series.length < 2) {
    throw new Error(`${label} requires at least two dated samples`);
  }
  let previous = -Infinity;
  const points = series.map(point => {
    const stamp = dateStamp(point?.date, `${label} sample date`);
    if (stamp <= previous) throw new Error(`${label} dates must be unique and increasing`);
    if (stamp < start || stamp > end) throw new Error(`${label} sample lies outside the selected period`);
    previous = stamp;
    const value = finite(finite(point?.[valueKey], `${label} ${valueKey}`) - 100, `${label} return`);
    return { stamp, value };
  });
  if (points[0].stamp !== start || points.at(-1).stamp !== end) {
    throw new Error(`${label} must cover the full selected period, including both endpoints`);
  }
  return points;
}

// Coordinates describe the displayed performance polyline. Interpolating its
// samples locates an event visually; it does not infer a trade price or daily NAV.
export function createPerformanceGeometry(period, agents) {
  const start = dateStamp(period?.start, 'Period start');
  const end = dateStamp(period?.end, 'Period end');
  if (end <= start) throw new Error('Period end must follow period start');
  if (!Array.isArray(agents) || !agents.length) {
    throw new Error('An explicit nonempty set of Manager performance series is required');
  }
  const benchmark = checkedSeries(period.series, 'benchmarkValue', 'Benchmark', start, end);
  const byManager = new Map();
  for (const agent of agents) {
    const id = agent?.managerId;
    if (typeof id !== 'string' || !id.trim() || id !== id.trim()) {
      throw new Error('Each performance series requires an explicit Manager ID');
    }
    if (byManager.has(id)) throw new Error('Manager performance IDs must be unique');
    byManager.set(id, checkedSeries(agent.series, 'value', `Manager ${id}`, start, end));
  }
  let minimum = 0, maximum = 0;
  for (const series of [benchmark, ...byManager.values()]) {
    for (const { value } of series) {
      minimum = Math.min(minimum, value);
      maximum = Math.max(maximum, value);
    }
  }
  const span = finite(maximum - minimum, 'Performance range') || 1;
  const padding = span * .1;
  const min = finite(minimum - padding, 'Padded minimum');
  const max = finite(maximum + padding, 'Padded maximum');
  const height = finite(max - min, 'Padded performance range');
  const inPeriod = date => {
    const stamp = dateStamp(date, 'Coordinate date');
    if (stamp < start || stamp > end) throw new Error('Coordinate date lies outside the selected period');
    return stamp;
  };
  const xAt = stamp => PERFORMANCE_PLOT.left + (stamp - start) / (end - start) * (PERFORMANCE_PLOT.right - PERFORMANCE_PLOT.left);
  const x = date => xAt(inPeriod(date));
  const y = returnPct => finite(PERFORMANCE_PLOT.bottom - (finite(returnPct, 'Return percentage') - min) / height * (PERFORMANCE_PLOT.bottom - PERFORMANCE_PLOT.top), 'Y coordinate');
  const pointAt = (managerId, date) => {
    const series = byManager.get(managerId);
    if (!series) throw new Error('Manager is not in the selected performance series');
    const stamp = inPeriod(date);
    let upper = series.findIndex(point => point.stamp >= stamp);
    const right = series[upper];
    if (right.stamp === stamp) return { x: xAt(stamp), y: y(right.value) };
    const left = series[upper - 1];
    const fraction = (stamp - left.stamp) / (right.stamp - left.stamp);
    const value = left.value + (right.value - left.value) * fraction;
    return { x: xAt(stamp), y: y(value) };
  };
  return Object.freeze({ minimum, maximum, min, max, x, y, pointAt });
}
