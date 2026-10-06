// Routes retain navigation entry and report identity independently. Entity and
// ownership checks belong to the selected dataset, never to an inferred default.
import { formatRoute as formatLegacyRoute, parseRoute as parseLegacyRoute } from './reader-state.mjs';

export const KEY = 'uteki.workspace-prototype.v3';
const OLD_KEY = 'uteki.workspace-prototype.v2';
const ENTRIES = new Set(['companies', 'managers']);
const INDEX_VIEWS = new Set(['research', 'changes', 'portfolio']);
const READER_VIEWS = new Set(['report', 'changes', 'compare', 'evidence']);
const ORIGINS = new Set(['report', 'changes', 'compare']);
const COMPARE_FIELDS = ['leftReport', 'leftVersion', 'rightReport', 'rightVersion'];
const READER_QUERY = new Set(['company', 'manager', 'version', 'entry', 'object', 'view', 'section', 'evidenceId', 'origin', 'filter', 'returnView', ...COMPARE_FIELDS]);
const MAX_RAW_LENGTH = 4 * 1024 * 1024;
const MAX_SCROLL = 100_000_000;
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const copy = value => JSON.parse(JSON.stringify(value));
function fail(message) { throw new Error(`Invalid workspace route: ${message}`); }
function fields(input, allowed, label = 'route') {
  if (!isRecord(input)) fail(`expected ${label} object`);
  for (const key of Object.keys(input)) if (!allowed.includes(key)) fail(`unknown ${label} field ${key}`);
}
function token(value, label) {
  if (typeof value !== 'string' || !value || value.length > 160 ||
      /[\s\u0000-\u001f\u007f/?#]/u.test(value) || value === '.' || value === '..') {
    fail(`${label} must be a non-empty identifier`);
  }
  return value;
}
function version(value) {
  token(value, 'version');
  if (value === 'researching') fail('reader requires a published version');
  return value;
}
function normalizeLegacy(input) {
  fields(input, ['page', 'legacy']);
  fields(input.legacy, ['companyId', 'managerId', 'version', 'view', 'section', 'evidenceId', 'origin', 'compare'], 'legacy route');
  if (input.legacy.compare !== undefined) {
    fields(input.legacy.compare, ['left', 'right'], 'legacy comparison');
    for (const side of ['left', 'right']) fields(input.legacy.compare[side], ['managerId', 'version'], 'legacy comparison side');
  }
  try { return { page: 'legacy', legacy: parseLegacyRoute(formatLegacyRoute(input.legacy)) }; }
  catch (error) { fail(error.message); }
}
function normalizeRoute(input) {
  if (!isRecord(input)) fail('expected a route object');
  if (input.page === 'legacy') return normalizeLegacy(input);
  if (input.page === 'index') {
    fields(input, ['page', 'entry', 'objectId', 'view', 'filterId']);
    if (!ENTRIES.has(input.entry)) fail('unknown entry');
    if (!INDEX_VIEWS.has(input.view)) fail('unknown index view');
    if (input.view === 'portfolio' && input.entry !== 'managers') fail('portfolio belongs to Manager entry');
    if (input.view === 'portfolio' && input.filterId !== undefined) fail('portfolio does not accept a company filter');
    const route = { page: 'index', entry: input.entry, objectId: token(input.objectId, 'objectId'), view: input.view };
    if (input.filterId !== undefined) route.filterId = token(input.filterId, 'filterId');
    return route;
  }
  if (input.page !== 'reader') fail('unknown page');
  fields(input, ['page', 'entry', 'objectId', 'companyId', 'managerId', 'reportId', 'version', 'view', 'section', 'evidenceId', 'origin', 'compare', 'filterId', 'returnView']);
  if (!ENTRIES.has(input.entry)) fail('unknown entry');
  if (!READER_VIEWS.has(input.view)) fail('unknown reader view');
  const route = {
    page: 'reader', entry: input.entry, objectId: token(input.objectId, 'objectId'),
    companyId: token(input.companyId, 'companyId'), managerId: token(input.managerId, 'managerId'),
    reportId: token(input.reportId, 'reportId'), version: version(input.version), view: input.view,
  };
  if (input.section !== undefined) route.section = token(input.section, 'section');
  if (input.filterId !== undefined) route.filterId = token(input.filterId, 'filterId');
  if (input.returnView !== undefined) {
    if (!INDEX_VIEWS.has(input.returnView)) fail('unknown return view');
    if (input.returnView === 'portfolio' && (input.entry !== 'managers' || input.filterId !== undefined)) fail('portfolio return requires an unfiltered Manager entry');
    route.returnView = input.returnView;
  }
  if (input.evidenceId !== undefined) {
    if (route.view !== 'evidence') fail('evidenceId belongs to evidence view');
    route.evidenceId = token(input.evidenceId, 'evidenceId');
  }
  if (route.view === 'evidence' && !route.evidenceId) fail('evidenceId is required');
  if (input.origin !== undefined) {
    if (route.view !== 'evidence' || !ORIGINS.has(input.origin)) fail('invalid evidence origin');
    route.origin = input.origin;
  }
  if (input.compare !== undefined) {
    if (route.view !== 'compare' && !(route.view === 'evidence' && route.origin === 'compare')) fail('comparison context belongs to compare or its evidence view');
    fields(input.compare, ['left', 'right'], 'comparison');
    route.compare = {};
    for (const side of ['left', 'right']) {
      fields(input.compare[side], ['reportId', 'version'], 'comparison side');
      route.compare[side] = { reportId: token(input.compare[side].reportId, `${side} reportId`), version: version(input.compare[side].version) };
    }
  }
  if ((route.view === 'compare' || route.origin === 'compare') && !route.compare) fail('comparison context is required');
  return route;
}

export function formatRoute(input) {
  const route = normalizeRoute(input);
  if (route.page === 'legacy') return formatLegacyRoute(route.legacy);
  let path;
  let query;
  if (route.page === 'index') {
    path = `/app/${route.entry}/${encodeURIComponent(route.objectId)}`;
    query = new URLSearchParams({ view: route.view });
    if (route.filterId !== undefined) query.set(route.entry === 'companies' ? 'manager' : 'company', route.filterId);
  } else {
    path = `/app/reports/${encodeURIComponent(route.reportId)}`;
    query = new URLSearchParams({ company: route.companyId, manager: route.managerId, version: route.version, entry: route.entry, object: route.objectId, view: route.view });
    for (const key of ['section', 'evidenceId', 'origin', 'returnView']) if (route[key] !== undefined) query.set(key, route[key]);
    if (route.filterId !== undefined) query.set('filter', route.filterId);
    if (route.compare) for (const side of ['left', 'right']) {
      query.set(`${side}Report`, route.compare[side].reportId);
      query.set(`${side}Version`, route.compare[side].version);
    }
  }
  const hash = `#${path}?${query}`;
  if (hash.length > 4096) fail('hash is too long');
  return hash;
}
function readQuery(raw, allowed) {
  const query = new URLSearchParams(raw);
  const seen = new Set();
  for (const [key] of query) {
    if (!allowed.has(key)) fail(`unknown parameter ${key}`);
    if (seen.has(key)) fail(`duplicate parameter ${key}`);
    seen.add(key);
  }
  return query;
}
export function parseRoute(hash) {
  if (typeof hash !== 'string') fail('hash must be a string');
  if (hash === '' || hash === '#') return null;
  if (hash.length > 4096) fail('hash is too long');
  const source = hash.startsWith('#') ? hash.slice(1) : hash;
  if (source.includes('#') || /[\u0000-\u0020\u007f]/u.test(source)) fail('invalid hash characters');
  try { decodeURIComponent(source); } catch { fail('invalid URL encoding'); }
  if (/^\/app\/companies\/[^/?]+\/cases\//.test(source)) {
    try { return { page: 'legacy', legacy: parseLegacyRoute(hash) }; }
    catch (error) { fail(error.message); }
  }
  const match = /^\/app\/(companies|managers|reports)\/([^/?]+)\?([^?]*)$/.exec(source);
  if (!match) fail('expected an index or report path');
  const [, scope, identifier, rawQuery] = match;
  if (scope !== 'reports') {
    const filterField = scope === 'companies' ? 'manager' : 'company';
    const query = readQuery(rawQuery, new Set(['view', filterField]));
    const route = { page: 'index', entry: scope, objectId: decodeURIComponent(identifier), view: query.get('view') };
    if (query.has(filterField)) route.filterId = query.get(filterField);
    return normalizeRoute(route);
  }
  const query = readQuery(rawQuery, READER_QUERY);
  const route = {
    page: 'reader', entry: query.get('entry'), objectId: query.get('object'), reportId: decodeURIComponent(identifier),
    companyId: query.get('company'), managerId: query.get('manager'), version: query.get('version'), view: query.get('view'),
  };
  for (const key of ['section', 'evidenceId', 'origin', 'returnView']) if (query.has(key)) route[key] = query.get(key);
  if (query.has('filter')) route.filterId = query.get('filter');
  if (COMPARE_FIELDS.some(key => query.has(key))) {
    if (!COMPARE_FIELDS.every(key => query.has(key))) fail('incomplete comparison parameters');
    route.compare = {
      left: { reportId: query.get('leftReport'), version: query.get('leftVersion') },
      right: { reportId: query.get('rightReport'), version: query.get('rightVersion') },
    };
  }
  return normalizeRoute(route);
}
export function routeKey(route) {
  if (route?.page === 'legacy') return formatRoute({ ...route, legacy: { ...route.legacy, section: undefined } });
  const { section, ...keyRoute } = route ?? {};
  return formatRoute(keyRoute);
}
export function reportKey(reportId) { return token(reportId, 'reportId'); }

function defaults() {
  return {
    theme: 'system', language: 'zh', fontSize: 17, lastRoute: null,
    entries: { companies: null, managers: null }, positions: {}, readVersions: {}, readEvents: [], savedEvents: [], notes: {},
  };
}
const safeKey = key => typeof key === 'string' && key.length > 0 && key.length <= 4096 &&
  !/[\u0000-\u001f\u007f]/u.test(key) && !['__proto__', 'constructor', 'prototype'].includes(key);
const scrollValue = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= MAX_SCROLL;
function validToken(value) { try { token(value, 'identifier'); return true; } catch { return false; } }
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
    try { result.lastRoute = normalizeRoute(input.lastRoute); } catch { /* Keep the prior valid route. */ }
  }
  if (isRecord(input.entries)) for (const entry of ENTRIES) {
    if (input.entries[entry] === null) result.entries[entry] = null;
    else if (input.entries[entry] !== undefined) {
      try {
        const route = normalizeRoute(input.entries[entry]);
        if (route.page === 'index' && route.entry === entry) result.entries[entry] = route;
      } catch { /* Never infer another entry or entity. */ }
    }
  }
  if (isRecord(input.positions)) result.positions = cleanMap(input.positions, 250, (position, key) => {
    try { const route = parseRoute(key); if (!route || routeKey(route) !== key) return; } catch { return; }
    if (!isRecord(position) || !scrollValue(position.main)) return;
    const clean = { main: position.main };
    for (const field of ['left', 'right', 'sidebar']) if (scrollValue(position[field])) clean[field] = position[field];
    if (validToken(position.focusId)) clean.focusId = position.focusId;
    return clean;
  });
  if (isRecord(input.readVersions)) result.readVersions = cleanMap(input.readVersions, 1000, (entry, key) => {
    try { reportKey(key); return version(entry); } catch { return; }
  });
  for (const field of ['readEvents', 'savedEvents']) if (Array.isArray(input[field])) result[field] = [...new Set(input[field].filter(validToken))].slice(-2000);
  if (isRecord(input.notes)) result.notes = cleanMap(input.notes, Number.MAX_SAFE_INTEGER, entry => typeof entry === 'string' ? entry : undefined);
  return result;
}
function errorText(error, action) {
  return `Local storage ${action} failed${error && typeof error.message === 'string' ? `: ${error.message}` : ''}`;
}
function parseStored(raw) {
  if (typeof raw !== 'string' || raw.length > MAX_RAW_LENGTH) throw new Error('Invalid stored data size');
  const parsed = JSON.parse(raw);
  if (!isRecord(parsed)) throw new Error('Invalid stored data');
  return parsed;
}
/** Map fields are top-level patches; callers merge their individual entries. */
export function createPersonalStore(storage) {
  let state = defaults();
  let error = null;
  const resolveStorage = () => {
    const resolved = typeof storage === 'function' ? storage() : storage;
    if (!resolved || typeof resolved.getItem !== 'function' || typeof resolved.setItem !== 'function') throw new Error('Storage unavailable');
    return resolved;
  };
  try {
    const store = resolveStorage();
    const raw = store.getItem(KEY);
    if (raw !== null && raw !== undefined) state = cleanState(parseStored(raw));
    else {
      const old = store.getItem(OLD_KEY);
      if (old !== null && old !== undefined) {
        const { theme, language, fontSize } = parseStored(old);
        state = cleanState({ theme, language, fontSize });
      }
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
      } catch (cause) { error = errorText(cause, 'write'); return false; }
    },
  };
}
