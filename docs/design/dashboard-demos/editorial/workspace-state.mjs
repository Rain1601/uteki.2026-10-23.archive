const VIEWS = new Set(['overview', 'library', 'reading', 'resources', 'finance', 'workflow', 'portfolio', 'review', 'agent']);
const THEMES = new Set(['paper', 'mineral', 'plum']);
const LANGUAGES = new Set(['zh', 'en']);
const SORT_KEYS = new Set(['title', 'category', 'date', 'value', 'change']);

function validateDate(value, name, allowEmpty = false) {
  if (allowEmpty && value === '') return;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new TypeError(`${name} must be YYYY-MM-DD`);
  const [year, month, day] = value.split('-').map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) throw new TypeError(`${name} must be a real calendar date`);
}

function validateFilters(records, categories, dateRange) {
  if (!Array.isArray(categories)) throw new TypeError('categories must be an array');
  const known = new Set(records.map(record => record.category));
  const seen = new Set();
  for (const category of categories) {
    if (typeof category !== 'string' || !known.has(category)) throw new TypeError('unknown category');
    if (seen.has(category)) throw new TypeError('duplicate category');
    seen.add(category);
  }
  if (!dateRange || typeof dateRange !== 'object' || Array.isArray(dateRange)) throw new TypeError('dateRange must be an object');
  validateDate(dateRange.from, 'dateRange.from', true);
  validateDate(dateRange.to, 'dateRange.to', true);
  if (dateRange.from && dateRange.to && dateRange.from > dateRange.to) throw new TypeError('dateRange.from must not follow dateRange.to');
}

export function validateFilterSelection(records, selection) {
  validateRecords(records);
  if (!selection || typeof selection !== 'object' || Array.isArray(selection)) throw new TypeError('filter selection must be an object');
  const { categories, dateRange } = selection;
  validateFilters(records, categories, dateRange);
  return { categories: [...categories], dateRange: { from: dateRange.from, to: dateRange.to } };
}

function filtersOf(state) {
  return { categories: state.categories === undefined ? [] : state.categories,
    dateRange: state.dateRange === undefined ? { from: '', to: '' } : state.dateRange };
}

function validateRecords(records) {
  if (!Array.isArray(records)) throw new TypeError('records must be an array');
  const ids = new Set();
  for (const record of records) {
    if (!record || typeof record !== 'object') throw new TypeError('record must be an object');
    for (const key of ['id', 'title', 'category', 'date', 'summary']) {
      if (typeof record[key] !== 'string' || !record[key].trim()) throw new TypeError(`record.${key} must be a nonempty string`);
    }
    if ('titleZh' in record || 'titleEn' in record) {
      for (const key of ['titleZh', 'titleEn']) {
        if (typeof record[key] !== 'string' || !record[key].trim()) throw new TypeError(`record.${key} must be a nonempty string when localized titles are supplied`);
      }
    }
    validateDate(record.date, 'record.date');
    if (record.category === 'all') throw new TypeError('record.category cannot use reserved all value');
    if (ids.has(record.id)) throw new TypeError(`duplicate record id: ${record.id}`);
    ids.add(record.id);
    for (const key of ['value', 'change']) {
      if (record[key] !== null && (typeof record[key] !== 'number' || !Number.isFinite(record[key]))) {
        throw new TypeError(`record.${key} must be finite or null`);
      }
    }
  }
}

function validateState(records, state) {
  if (!state || !VIEWS.has(state.view)) throw new TypeError('invalid view');
  if (!THEMES.has(state.theme)) throw new TypeError('invalid theme');
  if (!LANGUAGES.has(state.language)) throw new TypeError('invalid language');
  if (!SORT_KEYS.has(state.sortKey)) throw new TypeError('invalid sort key');
  if (!['asc', 'desc'].includes(state.direction)) throw new TypeError('invalid sort direction');
  if (typeof state.query !== 'string') throw new TypeError('query must be a string');
  if (state.category !== 'all' && !records.some(record => record.category === state.category)) throw new TypeError('unknown category');
  const filters = filtersOf(state);
  validateFilters(records, filters.categories, filters.dateRange);
  if (state.category !== 'all' && filters.categories.length) throw new TypeError('single and multiple category filters cannot coexist');
  if (state.selected !== null && !records.some(record => record.id === state.selected)) throw new TypeError('unknown selected id');
}

export function createState(records) {
  validateRecords(records);
  return { view: 'overview', category: 'all', categories: [], dateRange: { from: '', to: '' }, query: '', selected: null,
    sortKey: 'value', direction: 'desc', theme: 'paper', language: 'zh' };
}

export function visibleRecords(records, state) {
  validateRecords(records);
  validateState(records, state);
  const { categories, dateRange } = filtersOf(state);
  const query = state.query.trim().toLocaleLowerCase();
  const direction = state.direction === 'asc' ? 1 : -1;
  return records.filter(record =>
    (state.category === 'all' || record.category === state.category) &&
    (!categories.length || categories.includes(record.category)) &&
    (!dateRange.from || record.date >= dateRange.from) &&
    (!dateRange.to || record.date <= dateRange.to) &&
    (!query || [record.title, record.category, record.date, record.summary, record.titleZh, record.titleEn, record.summaryZh, record.summaryEn]
      .some(value => typeof value === 'string' && value.toLocaleLowerCase().includes(query)))
  ).sort((a, b) => {
    const key = state.sortKey === 'title' && 'titleZh' in a ? (state.language === 'zh' ? 'titleZh' : 'titleEn') : state.sortKey;
    const otherKey = state.sortKey === 'title' && 'titleZh' in b ? (state.language === 'zh' ? 'titleZh' : 'titleEn') : state.sortKey;
    const left = a[key], right = b[otherKey];
    if (left === null || right === null) return left === right ? 0 : left === null ? 1 : -1;
    if (typeof left === 'number') return (left - right) * direction;
    return left.localeCompare(right, state.language === 'zh' ? 'zh-CN' : 'en') * direction;
  });
}

export function transition(records, state, action) {
  validateRecords(records);
  validateState(records, state);
  if (!action || typeof action !== 'object') throw new TypeError('action must be an object');
  const next = { ...state };
  switch (action.type) {
    case 'view':
      if (!VIEWS.has(action.value)) throw new TypeError('invalid view');
      next.view = action.value;
      break;
    case 'theme':
      if (!THEMES.has(action.value)) throw new TypeError('invalid theme');
      next.theme = action.value;
      break;
    case 'language':
      if (!LANGUAGES.has(action.value)) throw new TypeError('invalid language');
      next.language = action.value;
      break;
    case 'category':
      if (action.value !== 'all' && !records.some(record => record.category === action.value)) throw new TypeError('unknown category');
      next.category = action.value;
      next.categories = [];
      break;
    case 'filters': {
      const { categories, dateRange } = validateFilterSelection(records, action.value);
      next.category = 'all';
      next.categories = [...categories];
      next.dateRange = { from: dateRange.from, to: dateRange.to };
      break;
    }
    case 'resetFilters':
      next.category = 'all';
      next.categories = [];
      next.dateRange = { from: '', to: '' };
      next.query = '';
      break;
    case 'query':
      if (typeof action.value !== 'string') throw new TypeError('query must be a string');
      next.query = action.value;
      break;
    case 'select':
      if (!visibleRecords(records, state).some(record => record.id === action.value)) throw new TypeError('selected id must be visible');
      next.selected = action.value;
      break;
    case 'sort': {
      const key = typeof action.value === 'string' ? action.value : action.value?.key;
      const direction = typeof action.value === 'string'
        ? (state.sortKey === key && state.direction === 'desc' ? 'asc' : 'desc') : action.value?.direction;
      if (!SORT_KEYS.has(key) || !['asc', 'desc'].includes(direction)) throw new TypeError('invalid sort');
      next.sortKey = key;
      next.direction = direction;
      break;
    }
    case 'step': {
      if (![1, -1].includes(action.value)) throw new TypeError('step must be +1 or -1');
      const rows = visibleRecords(records, state);
      if (!rows.length) { next.selected = null; break; }
      const current = rows.findIndex(row => row.id === state.selected);
      const index = current < 0 ? (action.value === 1 ? 0 : rows.length - 1)
        : Math.max(0, Math.min(rows.length - 1, current + action.value));
      next.selected = rows[index].id;
      break;
    }
    case 'close': next.selected = null; break;
    default: throw new TypeError(`unknown action: ${action.type}`);
  }
  if (next.selected !== null && !visibleRecords(records, next).some(record => record.id === next.selected)) next.selected = null;
  return next;
}
