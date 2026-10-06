// Routes describe an explicitly selected research case. Entity existence is
// checked by the workspace's data layer, never inferred by this module.
export const KEY = 'uteki.workspace-prototype.v2';

const VIEWS = new Set(['report', 'changes', 'compare', 'evidence']);
const ORIGINS = new Set(['report', 'changes', 'compare']);
const QUERY_FIELDS = new Set([
  'version', 'view', 'section', 'evidenceId', 'origin',
  'leftManager', 'leftVersion', 'rightManager', 'rightVersion',
]);
const COMPARE_FIELDS = ['leftManager', 'leftVersion', 'rightManager', 'rightVersion'];
const MAX_RAW_LENGTH = 4 * 1024 * 1024;
const MAX_SCROLL = 100_000_000;
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const copy = value => JSON.parse(JSON.stringify(value));

function fail(message) { throw new Error(`Invalid reader route: ${message}`); }

function token(value, label) {
  if (typeof value !== 'string' || !value || value.length > 160 ||
      /[\s\u0000-\u001f\u007f/?#]/u.test(value) || value === '.' || value === '..') {
    fail(`${label} must be a non-empty identifier`);
  }
  return value;
}

function version(value) {
  if (value === null) return null;
  token(value, 'version');
  if (value === 'researching') fail('researching is reserved for a null version');
  return value;
}

function normalizeRoute(input) {
  if (!isRecord(input)) fail('expected a route object');
  const route = {
    companyId: token(input.companyId, 'companyId'),
    managerId: token(input.managerId, 'managerId'),
    version: version(input.version),
    view: input.view,
  };
  if (!VIEWS.has(route.view)) fail('unknown view');
  if (input.section !== undefined) route.section = token(input.section, 'section');
  if (input.evidenceId !== undefined) {
    if (route.view !== 'evidence') fail('evidenceId belongs to the evidence view');
    route.evidenceId = token(input.evidenceId, 'evidenceId');
  }
  if (route.view === 'evidence' && !route.evidenceId) fail('evidenceId is required');
  if (input.origin !== undefined) {
    if (route.view !== 'evidence' || !ORIGINS.has(input.origin)) fail('invalid evidence origin');
    route.origin = input.origin;
  }
  if (input.compare !== undefined) {
    if (route.view !== 'compare' && !(route.view === 'evidence' && route.origin === 'compare')) {
      fail('comparison context belongs to compare or its evidence view');
    }
    if (!isRecord(input.compare) || !isRecord(input.compare.left) || !isRecord(input.compare.right)) {
      fail('both comparison sides are required');
    }
    route.compare = Object.fromEntries(['left', 'right'].map(side => [side, {
      managerId: token(input.compare[side].managerId, `${side} managerId`),
      version: version(input.compare[side].version),
    }]));
  }
  if ((route.view === 'compare' || route.origin === 'compare') && !route.compare) {
    fail('comparison context is required');
  }
  return route;
}

/** A canonical hash, suitable for location.hash or a link's href. */
export function formatRoute(input) {
  const route = normalizeRoute(input);
  const query = new URLSearchParams({ version: route.version ?? 'researching', view: route.view });
  if (route.section !== undefined) query.set('section', route.section);
  if (route.evidenceId !== undefined) query.set('evidenceId', route.evidenceId);
  if (route.origin !== undefined) query.set('origin', route.origin);
  if (route.compare) {
    for (const side of ['left', 'right']) {
      query.set(`${side}Manager`, route.compare[side].managerId);
      query.set(`${side}Version`, route.compare[side].version ?? 'researching');
    }
  }
  const hash = `#/app/companies/${encodeURIComponent(route.companyId)}/cases/${encodeURIComponent(route.managerId)}?${query}`;
  if (hash.length > 4096) fail('hash is too long');
  return hash;
}

/** Empty hashes have no selected route; malformed scope never picks a default. */
export function parseRoute(hash) {
  if (typeof hash !== 'string') fail('hash must be a string');
  if (hash === '' || hash === '#') return null;
  if (hash.length > 4096) fail('hash is too long');
  const source = hash.startsWith('#') ? hash.slice(1) : hash;
  if (source.includes('#') || /[\u0000-\u0020\u007f]/u.test(source)) fail('invalid hash characters');
  try {
    // URLSearchParams otherwise accepts malformed escapes and replaces invalid UTF-8.
    decodeURIComponent(source);
  } catch { fail('invalid URL encoding'); }
  const match = /^\/app\/companies\/([^/?]+)\/cases\/([^/?]+)\?([^?]*)$/.exec(source);
  if (!match) fail('expected a company and Manager case path');
  const query = new URLSearchParams(match[3]);
  const seen = new Set();
  for (const [key] of query) {
    if (!QUERY_FIELDS.has(key)) fail(`unknown parameter ${key}`);
    if (seen.has(key)) fail(`duplicate parameter ${key}`);
    seen.add(key);
  }
  if (!query.has('version') || !query.has('view')) fail('version and view are required');
  const decodeVersion = value => value === 'researching' ? null : value;
  const route = {
    companyId: decodeURIComponent(match[1]), managerId: decodeURIComponent(match[2]),
    version: decodeVersion(query.get('version')), view: query.get('view'),
  };
  for (const field of ['section', 'evidenceId', 'origin']) {
    if (query.has(field)) route[field] = query.get(field);
  }
  if (COMPARE_FIELDS.some(field => query.has(field))) {
    if (!COMPARE_FIELDS.every(field => query.has(field))) fail('incomplete comparison parameters');
    route.compare = {
      left: { managerId: query.get('leftManager'), version: decodeVersion(query.get('leftVersion')) },
      right: { managerId: query.get('rightManager'), version: decodeVersion(query.get('rightVersion')) },
    };
  }
  return normalizeRoute(route);
}

/** Anchors share one reading position; every company, Manager and version stays scoped. */
export function routeKey(route) {
  return formatRoute({ ...route, section: undefined });
}

export function caseKey(companyId, managerId) {
  return JSON.stringify([token(companyId, 'companyId'), token(managerId, 'managerId')]);
}

function defaults() {
  return {
    theme: 'system', language: 'zh', fontSize: 17, lastRoute: null,
    positions: {}, readVersions: {}, readEvents: [], savedEvents: [], notes: {},
  };
}

const safeKey = key => typeof key === 'string' && key.length > 0 && key.length <= 2048 &&
  !/[\u0000-\u001f\u007f]/u.test(key) && !['__proto__', 'constructor', 'prototype'].includes(key);
const scrollValue = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= MAX_SCROLL;

function validToken(value) {
  try { token(value, 'identifier'); return true; } catch { return false; }
}

function cleanMap(value, maxEntries, cleanEntry) {
  const result = {};
  for (const [key, entry] of Object.entries(value).slice(-maxEntries)) {
    if (!safeKey(key)) continue;
    const clean = cleanEntry(entry, key);
    if (clean !== undefined) result[key] = clean;
  }
  return result;
}

function cleanState(input, base = defaults()) {
  const result = copy(base);
  if (!isRecord(input)) return result;
  if (['system', 'light', 'dark'].includes(input.theme)) result.theme = input.theme;
  if (['zh', 'en'].includes(input.language)) result.language = input.language;
  if ([16, 17, 18].includes(input.fontSize)) result.fontSize = input.fontSize;
  if (input.lastRoute === null) result.lastRoute = null;
  else if (input.lastRoute !== undefined) {
    try { result.lastRoute = normalizeRoute(input.lastRoute); } catch { /* Keep the valid previous/default route. */ }
  }
  if (isRecord(input.positions)) {
    result.positions = cleanMap(input.positions, 250, (entry, key) => {
      try {
        const route = parseRoute(key);
        if (!route || routeKey(route) !== key) return;
      } catch { return; }
      if (!isRecord(entry) || !scrollValue(entry.main)) return;
      const position = { main: entry.main };
      for (const side of ['left', 'right']) if (scrollValue(entry[side])) position[side] = entry[side];
      if (validToken(entry.focusId)) position.focusId = entry.focusId;
      return position;
    });
  }
  if (isRecord(input.readVersions)) {
    result.readVersions = cleanMap(input.readVersions, 1000, (entry, key) => {
      try {
        const tuple = JSON.parse(key);
        if (!Array.isArray(tuple) || tuple.length !== 2 || caseKey(...tuple) !== key || entry === null) return;
        return version(entry);
      } catch { return; }
    });
  }
  for (const field of ['readEvents', 'savedEvents']) {
    if (Array.isArray(input[field])) result[field] = [...new Set(input[field].filter(validToken))].slice(-2000);
  }
  if (isRecord(input.notes)) {
    // Unlike disposable position history, drafts must not be silently truncated.
    // The serialized-store limit below reports failure while keeping all text in memory.
    result.notes = cleanMap(input.notes, Number.MAX_SAFE_INTEGER, entry => typeof entry === 'string' ? entry : undefined);
  }
  return result;
}

function errorText(error, action) {
  return `Local storage ${action} failed${error && typeof error.message === 'string' ? `: ${error.message}` : ''}`;
}

/**
 * Top-level patch API: merge individual map entries at the call site.
 * Pass storage itself, null, or () => window.localStorage to catch access errors.
 * Memory is updated before persistence, so a failed write does not discard drafts.
 */
export function createPersonalStore(storage) {
  let state = defaults();
  let error = null;
  const resolveStorage = () => {
    const resolved = typeof storage === 'function' ? storage() : storage;
    if (!resolved || typeof resolved.getItem !== 'function' || typeof resolved.setItem !== 'function') {
      throw new Error('Storage unavailable');
    }
    return resolved;
  };
  try {
    const raw = resolveStorage().getItem(KEY);
    if (raw !== null && raw !== undefined) {
      if (typeof raw !== 'string' || raw.length > MAX_RAW_LENGTH) throw new Error('Invalid stored data size');
      const parsed = JSON.parse(raw);
      if (!isRecord(parsed)) throw new Error('Invalid stored data');
      state = cleanState(parsed);
    }
  } catch (cause) { error = errorText(cause, 'read'); }
  return {
    get() { return copy(state); },
    get error() { return error; },
    save(patch) {
      if (!isRecord(patch)) throw new TypeError('Personal state patch must be an object');
      state = cleanState(patch, state);
      try {
        const serialized = JSON.stringify(state);
        if (serialized.length > MAX_RAW_LENGTH) throw new Error('Local state exceeds storage limit');
        resolveStorage().setItem(KEY, serialized);
        error = null;
        return true;
      } catch (cause) {
        error = errorText(cause, 'write');
        return false;
      }
    },
  };
}
