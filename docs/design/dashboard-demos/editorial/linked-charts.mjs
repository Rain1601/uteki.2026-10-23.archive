/** Two chart forms, one point identity and one reference line. No business defaults. */
const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const text = (value, name) => {
  if (typeof value !== 'string' || !value.trim()) throw new TypeError(`${name} must be non-empty text`);
  return value;
};
const identity = (value, name) => {
  text(value, name);
  if (!/^[a-zA-Z0-9_-]+$/.test(value)) throw new TypeError(`${name} must be a safe identity`);
  return value;
};
const number = value => Number(value.toFixed(3));

export function validateLinkedCharts(input) {
  if (!input || !Array.isArray(input.points) || input.points.length < 3 || input.points.length > 12) throw new TypeError('points must contain 3–12 entries');
  const ids = new Set();
  const points = input.points.map(point => {
    const id = identity(point?.id, 'point.id');
    if (ids.has(id)) throw new TypeError(`Duplicate point: ${id}`);
    ids.add(id);
    return { id, label: text(point.label, 'point.label'), ...(point.detail !== undefined ? { detail: text(point.detail, 'point.detail') } : {}) };
  });
  if (!Array.isArray(input.series) || input.series.length !== 2) throw new TypeError('series must contain two entries');
  const seriesIds = new Set();
  const series = input.series.map(item => {
    const id = identity(item?.id, 'series.id');
    if (seriesIds.has(id)) throw new TypeError(`Duplicate series: ${id}`);
    seriesIds.add(id);
    if (!['line', 'bars'].includes(item.type)) throw new TypeError('series.type must be line or bars');
    if (!Array.isArray(item.values) || item.values.length !== points.length) throw new TypeError(`Every point must have an explicit value in ${id}`);
    const values = new Map();
    for (const entry of item.values) {
      const pointId = identity(entry?.id, 'value.id');
      if (!ids.has(pointId)) throw new TypeError(`Unknown point: ${pointId}`);
      if (values.has(pointId)) throw new TypeError(`Duplicate value: ${pointId}`);
      if (entry.value !== null && (typeof entry.value !== 'number' || !Number.isFinite(entry.value))) throw new TypeError('Values must be finite numbers or explicit null');
      values.set(pointId, entry.value);
    }
    return { id, title: text(item.title, 'series.title'), unit: text(item.unit, 'series.unit'), type: item.type, values: points.map(point => ({ id: point.id, value: values.get(point.id) })) };
  });
  if (new Set(series.map(item => item.type)).size !== 2) throw new TypeError('Use one line and one bars series');
  const labels = Object.fromEntries(['hint', 'clear', 'missing', 'pinned'].map(key => [key, text(input.labels?.[key], `labels.${key}`)]));
  return { points, series, labels };
}

/** Geometry uses canonical point order; null opens a path gap, zero is a real mark. */
export function buildLinkedChartModel(input) {
  const data = validateLinkedCharts(input);
  const width = 720, height = 432, left = 58, right = 686;
  const step = (right - left) / (data.points.length - 1);
  const positions = data.points.map((point, index) => ({ ...point, x: number(left + index * step) }));
  const series = data.series.map((item, index) => {
    const top = 54 + index * 198, bottom = top + 124;
    const present = item.values.filter(entry => entry.value !== null).map(entry => entry.value);
    // Include zero so a negative bar never visually masquerades as a positive bar.
    let min = Math.min(0, ...present), max = Math.max(0, ...present);
    if (min === max) { min = -1; max = 1; }
    const magnitude = Math.max(Math.abs(min), Math.abs(max));
    const y = value => number(bottom - (value / magnitude - min / magnitude) / (max / magnitude - min / magnitude) * (bottom - top));
    const zero = y(0);
    const marks = item.values.map((entry, pointIndex) => ({ ...entry, x: positions[pointIndex].x, y: entry.value === null ? null : y(entry.value), zero }));
    const paths = [];
    let segment = [];
    const close = () => { if (segment.length) paths.push(segment.map((mark, i) => `${i ? 'L' : 'M'}${mark.x},${mark.y}`).join(' ')); segment = []; };
    for (const mark of marks) { if (mark.value === null) close(); else segment.push(mark); }
    close();
    return { ...item, top, bottom, min, max, zero, marks, paths, barWidth: Math.min(36, step * .48) };
  });
  return { ...data, width, height, left, right, positions, series };
}

const displayValue = (item, value, missing) => value === null ? missing : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(value)} ${item.unit}`;
let sequence = 0;

export function LinkedCharts(input, prefix = 'linked-chart') {
  identity(prefix, 'prefix');
  const model = buildLinkedChartModel(input);
  const { width, height, positions, series, labels, left, right } = model;
  const plots = series.map(item => {
    const paths = item.type === 'line' ? item.paths.map(path => `<path class="linked-chart-path" d="${path}"/>`).join('') : '';
    const marks = item.marks.map((mark, index) => {
      if (mark.value === null) return `<g class="linked-chart-mark" data-index="${index}"><path class="linked-chart-gap" d="M${mark.x - 4},${item.bottom - 4}l8,8m-8,0l8,-8"/></g>`;
      if (item.type === 'line') return `<g class="linked-chart-mark" data-index="${index}"><circle cx="${mark.x}" cy="${mark.y}" r="4"/></g>`;
      const y = Math.min(mark.y, mark.zero), barHeight = Math.abs(mark.y - mark.zero);
      // A zero value is deliberately a thin mark, not a fabricated positive rectangle.
      return `<g class="linked-chart-mark${mark.value < 0 ? ' negative' : ''}" data-index="${index}">${mark.value === 0 ? `<line class="linked-chart-zero-value" x1="${mark.x - item.barWidth / 2}" x2="${mark.x + item.barWidth / 2}" y1="${mark.zero}" y2="${mark.zero}"/>` : `<rect x="${number(mark.x - item.barWidth / 2)}" y="${y}" width="${item.barWidth}" height="${number(barHeight)}"/>`}</g>`;
    }).join('');
    return `<g class="linked-chart-series ${item.type}"><text class="linked-chart-title" x="${left}" y="${item.top - 26}">${esc(item.title)}</text><text class="linked-chart-unit" x="${right}" y="${item.top - 26}" text-anchor="end">${esc(item.unit)}</text><line class="linked-chart-baseline" x1="${left - 16}" x2="${right + 16}" y1="${item.zero}" y2="${item.zero}"/><text class="linked-chart-tick" x="${left - 24}" y="${item.zero + 4}" text-anchor="end">0</text>${paths}${marks}</g>`;
  }).join('');
  const buttons = positions.map((point, index) => {
    const description = series.map(item => `${item.title}: ${displayValue(item, item.values[index].value, labels.missing)}`).join('; ');
    // Each button spans its nearest-point region, including both chart plots.
    const start = index === 0 ? 0 : (positions[index - 1].x + point.x) / 2 / width * 100;
    const end = index === positions.length - 1 ? 100 : (point.x + positions[index + 1].x) / 2 / width * 100;
    return `<button type="button" class="linked-chart-point" data-point="${index}" style="left:${start}%;width:${end - start}%" aria-pressed="false" aria-label="${esc(`${point.detail ?? point.label}; ${description}`)}" tabindex="${index === 0 ? 0 : -1}" aria-describedby="${prefix}-hint"><span class="linked-chart-sr">${esc(point.label)}</span></button>`;
  }).join('');
  return `<figure class="linked-charts" data-linked-charts><div class="linked-chart-instructions"><span id="${prefix}-hint">${esc(labels.hint)}</span><button type="button" class="linked-chart-clear" disabled>${esc(labels.clear)}</button></div><div class="linked-chart-stage"><svg viewBox="0 0 ${width} ${height}" aria-hidden="true" focusable="false">${plots}<line class="linked-chart-reference" x1="${positions[0].x}" x2="${positions[0].x}" y1="42" y2="390" visibility="hidden"/>${positions.map(point => `<text class="linked-chart-label" x="${point.x}" y="417" text-anchor="middle">${esc(point.label)}</text>`).join('')}</svg><div class="linked-chart-hit-area">${buttons}</div></div><figcaption class="linked-chart-caption"><span class="linked-chart-detail" hidden></span><strong class="linked-chart-selected">—</strong><span class="linked-chart-readout">${series.map(item => `<span><b>${esc(item.title)}</b><span data-readout="${item.id}">—</span></span>`).join('')}</span><span class="linked-chart-pin-status" aria-live="polite"></span></figcaption></figure>`;
}

export function mountLinkedCharts(host, input) {
  if (!host?.ownerDocument || typeof host.replaceChildren !== 'function') throw new TypeError('A DOM host is required');
  const model = buildLinkedChartModel(input);
  host.innerHTML = LinkedCharts(input, `linked-chart-${++sequence}`);
  const root = host.querySelector('[data-linked-charts]');
  const buttons = [...root.querySelectorAll('[data-point]')];
  const reference = root.querySelector('.linked-chart-reference');
  const clearButton = root.querySelector('.linked-chart-clear');
  let hovered = null, focused = null, pinned = null, destroyed = false;
  const listeners = [];
  const on = (target, event, handler) => { target.addEventListener(event, handler); listeners.push(() => target.removeEventListener(event, handler)); };
  const paint = () => {
    const index = pinned ?? hovered ?? focused;
    root.classList.toggle('has-active', index !== null);
    root.classList.toggle('is-pinned', pinned !== null);
    reference.setAttribute('visibility', index === null ? 'hidden' : 'visible');
    if (index !== null) { reference.setAttribute('x1', model.positions[index].x); reference.setAttribute('x2', model.positions[index].x); }
    root.querySelectorAll('.linked-chart-mark').forEach(mark => mark.classList.toggle('is-active', Number(mark.dataset.index) === index));
    buttons.forEach((button, i) => { button.setAttribute('aria-pressed', String(pinned === i)); button.tabIndex = i === (index ?? 0) ? 0 : -1; });
    root.querySelector('.linked-chart-selected').textContent = index === null ? '—' : model.points[index].label;
    const detail = root.querySelector('.linked-chart-detail');
    detail.textContent = index === null ? '' : (model.points[index].detail ?? '');
    detail.hidden = !detail.textContent;
    for (const item of model.series) root.querySelector(`[data-readout="${item.id}"]`).textContent = index === null ? '—' : displayValue(item, item.values[index].value, model.labels.missing);
    root.querySelector('.linked-chart-pin-status').textContent = pinned === null ? '' : model.labels.pinned;
    clearButton.disabled = index === null;
  };
  const clear = () => { hovered = null; focused = null; pinned = null; paint(); };
  buttons.forEach((button, index) => {
    on(button, 'pointerenter', () => { hovered = index; paint(); });
    on(button, 'pointerleave', () => { hovered = null; paint(); });
    on(button, 'focus', () => { focused = index; paint(); });
    on(button, 'blur', () => { focused = null; paint(); });
    on(button, 'click', () => { if (pinned === index) clear(); else { pinned = index; paint(); } });
    on(button, 'keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === 'ArrowLeft') next = Math.max(0, index - 1);
      if (event.key === 'ArrowRight') next = Math.min(buttons.length - 1, index + 1);
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = buttons.length - 1;
      // Keyboard navigation intentionally moves a pinned inspection too.
      if (pinned !== null) pinned = next;
      hovered = null;
      buttons[next].focus();
      paint();
    });
  });
  on(clearButton, 'click', clear);
  on(root, 'keydown', event => { if (event.key === 'Escape') { event.preventDefault(); clear(); } });
  paint();
  return { destroy() { if (destroyed) return; destroyed = true; listeners.forEach(remove => remove()); if (root.parentNode === host) root.remove(); } };
}
