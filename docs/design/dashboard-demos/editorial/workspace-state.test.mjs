import test from 'node:test';
import assert from 'node:assert/strict';
import { createState, visibleRecords, transition, validateFilterSelection } from './workspace-state.mjs';

const records = Object.freeze([
  Object.freeze({ id: 'a', title: '阅读研究', category: 'research', date: '2026-10-10', value: 12, change: -2, summary: 'Evidence with Alpha' }),
  Object.freeze({ id: 'b', title: 'Beta note', category: 'notes', date: '2026-10-09', value: 0, change: 4, summary: '资料摘要' }),
  Object.freeze({ id: 'c', title: 'Gamma study', category: 'research', date: '2026-10-08', value: null, change: null, summary: 'Unavailable observation' }),
]);
const ids = rows => rows.map(row => row.id);

test('default and numeric sorting preserve zero, null and original order', () => {
  const state = createState(records);
  assert.deepEqual(state, { view: 'overview', category: 'all', categories: [], dateRange: { from: '', to: '' }, query: '', selected: null, sortKey: 'value', direction: 'desc', theme: 'paper', language: 'zh' });
  assert.deepEqual(ids(visibleRecords(records, state)), ['a', 'b', 'c']);
  assert.deepEqual(ids(visibleRecords(records, transition(records, state, { type: 'sort', value: 'value' }))), ['b', 'a', 'c']);
  assert.deepEqual(ids(records), ['a', 'b', 'c']);
});

test('search matches mixed language content and category filtering clears hidden selection', () => {
  let state = transition(records, createState(records), { type: 'select', value: 'a' });
  state = transition(records, state, { type: 'query', value: ' ALPHA ' });
  assert.deepEqual(ids(visibleRecords(records, state)), ['a']);
  assert.equal(state.selected, 'a');
  state = transition(records, state, { type: 'category', value: 'notes' });
  assert.deepEqual(visibleRecords(records, state), []);
  assert.equal(state.selected, null);
  state = transition(records, state, { type: 'query', value: '资料' });
  assert.deepEqual(ids(visibleRecords(records, state)), ['b']);
});

test('presentation changes retain selected record and do not mutate input state', () => {
  const original = transition(records, createState(records), { type: 'select', value: 'b' });
  let next = transition(records, original, { type: 'view', value: 'reading' });
  next = transition(records, next, { type: 'theme', value: 'plum' });
  next = transition(records, next, { type: 'language', value: 'en' });
  assert.equal(next.selected, 'b');
  assert.equal(original.view, 'overview');
  assert.equal(original.theme, 'paper');
  assert.equal(transition(records, next, { type: 'close' }).selected, null);
});

test('keyboard steps follow filtered sorted rows and clamp at boundaries', () => {
  let state = transition(records, createState(records), { type: 'category', value: 'research' });
  state = transition(records, state, { type: 'step', value: 1 });
  assert.equal(state.selected, 'a');
  state = transition(records, state, { type: 'step', value: 1 });
  assert.equal(state.selected, 'c');
  assert.equal(transition(records, state, { type: 'step', value: 1 }).selected, 'c');
  assert.equal(transition(records, state, { type: 'step', value: -1 }).selected, 'a');
  state = transition(records, state, { type: 'query', value: 'no results' });
  assert.equal(transition(records, state, { type: 'step', value: 1 }).selected, null);
});

test('explicit sorting covers signed values, chronological dates and stable ties', () => {
  const state = createState(records);
  assert.deepEqual(ids(visibleRecords(records, transition(records, state, { type: 'sort', value: { key: 'change', direction: 'asc' } }))), ['a', 'b', 'c']);
  assert.deepEqual(ids(visibleRecords(records, transition(records, state, { type: 'sort', value: { key: 'date', direction: 'asc' } }))), ['c', 'b', 'a']);
  const tied = records.map(row => ({ ...row, value: 10 }));
  assert.deepEqual(ids(visibleRecords(tied, createState(tied))), ['a', 'b', 'c']);
});

test('unknown or hidden identities and malformed actions fail explicitly', () => {
  const state = createState(records);
  for (const action of [
    { type: 'view', value: 'unknown' }, { type: 'theme', value: 'unknown' },
    { type: 'language', value: 'fr' }, { type: 'category', value: 'unknown' },
    { type: 'query', value: null }, { type: 'select', value: 'unknown' },
    { type: 'sort', value: 'id' }, { type: 'sort', value: { key: 'value', direction: 'down' } },
    { type: 'step', value: 0 }, { type: 'unknown' }, null,
  ]) assert.throws(() => transition(records, state, action), TypeError);
  const filtered = transition(records, state, { type: 'category', value: 'notes' });
  assert.throws(() => transition(records, filtered, { type: 'select', value: 'a' }), /visible/);
  assert.throws(() => createState([...records, records[0]]), /duplicate/);
  assert.throws(() => createState([{ ...records[0], value: NaN }]), /finite/);
});

test('title sorting follows the displayed language while search includes explicit translations', () => {
  const bilingual = [
    { ...records[0], title: 'Legacy first', titleZh: '阿尔法', titleEn: 'Zulu', summaryZh: '独立摘要', summaryEn: 'Independent summary' },
    { ...records[1], title: 'Legacy second', titleZh: '佐罗', titleEn: 'Alpha', summaryZh: '另一段说明', summaryEn: 'Another explanation' },
  ];
  let state = transition(bilingual, createState(bilingual), { type: 'sort', value: { key: 'title', direction: 'asc' } });
  assert.deepEqual(ids(visibleRecords(bilingual, state)), ['a', 'b']);
  state = transition(bilingual, state, { type: 'language', value: 'en' });
  assert.deepEqual(ids(visibleRecords(bilingual, state)), ['b', 'a']);
  state = transition(bilingual, state, { type: 'select', value: 'b' });
  assert.equal(transition(bilingual, state, { type: 'step', value: 1 }).selected, 'a');
  for (const query of ['独立摘要', 'Zulu', 'Independent summary', '阿尔法']) {
    assert.deepEqual(ids(visibleRecords(bilingual, transition(bilingual, state, { type: 'query', value: query }))), ['a']);
  }
  assert.throws(() => createState([{ ...records[0], titleZh: '阿尔法' }]), /localized titles/);
  assert.throws(() => createState([{ ...records[0], titleZh: '阿尔法', titleEn: '' }]), /localized titles/);
});


const calendarRecords = [
  { id: 'archive', title: 'Archive', category: 'archive', date: '1900-02-28', value: 4, change: null, summary: 'Old archive' },
  { id: 'lab', title: 'Laboratory', category: 'lab', date: '2000-02-29', value: 3, change: 0, summary: 'Leap study' },
  { id: 'review', title: 'Review', category: 'review', date: '2024-02-29', value: 2, change: -1, summary: 'Independent review' },
  { id: 'next', title: 'Next laboratory', category: 'lab', date: '2024-03-01', value: 1, change: 1, summary: 'Next observation' },
];
const applyFilters = (state, categories, from = '', to = '') => transition(calendarRecords, state,
  { type: 'filters', value: { categories, dateRange: { from, to } } });

test('atomic category and date filters intersect with query and preserve inclusive open bounds', () => {
  const initial = createState(calendarRecords);
  const selected = transition(calendarRecords, initial, { type: 'select', value: 'lab' });
  const categories = ['lab', 'review'];
  const range = { from: '2024-02-29', to: '2024-03-01' };
  const next = transition(calendarRecords, selected, { type: 'filters', value: { categories, dateRange: range } });
  assert.deepEqual(ids(visibleRecords(calendarRecords, next)), ['review', 'next']);
  assert.equal(next.selected, null);
  assert.equal(selected.selected, 'lab');
  categories.push('archive'); range.from = '';
  assert.deepEqual(next.categories, ['lab', 'review']);
  assert.equal(next.dateRange.from, '2024-02-29');
  assert.deepEqual(ids(visibleRecords(calendarRecords, applyFilters(initial, [], '', '2000-02-29'))), ['archive', 'lab']);
  assert.deepEqual(ids(visibleRecords(calendarRecords, applyFilters(initial, [], '2024-03-01'))), ['next']);
  assert.deepEqual(ids(visibleRecords(calendarRecords, applyFilters(initial, [], '2024-02-29', '2024-02-29'))), ['review']);
  const queried = transition(calendarRecords, next, { type: 'query', value: '2024-03' });
  assert.deepEqual(ids(visibleRecords(calendarRecords, queried)), ['next']);
});

test('legacy category API clears multi-select, and reset restores all rows without changing presentation', () => {
  let state = applyFilters(createState(calendarRecords), ['lab', 'review'], '2000-02-29', '2024-02-29');
  state = transition(calendarRecords, state, { type: 'category', value: 'archive' });
  assert.deepEqual(state.categories, []);
  assert.equal(state.dateRange.from, '2000-02-29');
  assert.deepEqual(visibleRecords(calendarRecords, state), []);
  state = transition(calendarRecords, state, { type: 'query', value: 'missing' });
  state = transition(calendarRecords, state, { type: 'theme', value: 'plum' });
  const reset = transition(calendarRecords, state, { type: 'resetFilters' });
  assert.deepEqual(ids(visibleRecords(calendarRecords, reset)), ['archive', 'lab', 'review', 'next']);
  assert.equal(reset.theme, 'plum');
  assert.equal(reset.query, '');
  const { categories, dateRange, ...legacy } = createState(calendarRecords);
  assert.deepEqual(ids(visibleRecords(calendarRecords, legacy)), ['archive', 'lab', 'review', 'next']);
});

test('calendar validation rejects impossible dates, malformed endpoints and unsupported category selections', () => {
  const initial = createState(calendarRecords);
  for (const date of ['1900-02-29', '2023-02-29', '2024-04-31', '0000-01-01', '2024-00-01', '2024-13-01', '2024-1-01', '2024-01-00', '2024-01-01T00:00:00Z']) {
    assert.throws(() => createState([{ ...calendarRecords[0], date }]), TypeError);
    assert.throws(() => applyFilters(initial, [], date), TypeError);
  }
  for (const date of ['0001-01-01', '0099-12-31', '2000-02-29', '9999-12-31']) {
    assert.doesNotThrow(() => createState([{ ...calendarRecords[0], date }]));
  }
  for (const value of [
    { categories: ['lab', 'lab'], dateRange: { from: '', to: '' } },
    { categories: ['unknown'], dateRange: { from: '', to: '' } },
    { categories: ['all'], dateRange: { from: '', to: '' } },
    { categories: 'lab', dateRange: { from: '', to: '' } },
    { categories: [], dateRange: { from: '2024-03-01', to: '2024-02-29' } },
    { categories: [], dateRange: { from: '', to: null } },
    { categories: [] }, {}, null,
  ]) assert.throws(() => transition(calendarRecords, initial, { type: 'filters', value }), TypeError);
  assert.throws(() => visibleRecords(calendarRecords, { ...initial, category: 'lab', categories: ['review'] }), /coexist/);
  assert.deepEqual(initial.categories, []);
  assert.deepEqual(initial.dateRange, { from: '', to: '' });
});


test('draft validation returns detached filters and never applies a draft', () => {
  const draft = { categories: ['lab'], dateRange: { from: '2000-02-29', to: '' } };
  const validated = validateFilterSelection(calendarRecords, draft);
  validated.categories.push('review');
  validated.dateRange.to = '2024-03-01';
  assert.deepEqual(draft, { categories: ['lab'], dateRange: { from: '2000-02-29', to: '' } });
  assert.throws(() => validateFilterSelection(calendarRecords, { ...draft, categories: ['unknown'] }), /unknown/);
  assert.throws(() => validateFilterSelection(calendarRecords, []), TypeError);
});
