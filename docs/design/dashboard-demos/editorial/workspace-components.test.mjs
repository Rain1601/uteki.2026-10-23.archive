import test from 'node:test';
import assert from 'node:assert/strict';
import { SignedBars, ViewTabs } from './workspace-components.mjs';

const chart = rows => SignedBars({ rows, label: 'Value comparison', unit: 'CNY', locale: 'en-US', selected: 'negative', missingLabel: 'Missing' });
const rowMarkup = (html, id) => html.match(new RegExp(`<button[^>]*data-record="${id}"[^>]*>[\\s\\S]*?</button>`))?.[0];

test('signed bars share a zero axis and retain zero and missing as distinct records', () => {
  const html = chart([
    { id: 'positive', title: 'Positive', value: 30 },
    { id: 'negative', title: 'Negative', value: -20 },
    { id: 'zero', title: 'Zero', value: 0 },
    { id: 'missing', title: 'Gap', value: null },
  ]);
  assert.equal((html.match(/class="edition-zero" style="left:40%"/g) || []).length, 4);
  assert.match(rowMarkup(html, 'positive'), /class="edition-bar " style="left:40%;width:60%"/);
  assert.match(rowMarkup(html, 'negative'), /class="edition-bar negative" style="left:0%;width:40%"/);
  assert.match(rowMarkup(html, 'negative'), /aria-pressed="true"/);
  assert.match(rowMarkup(html, 'zero'), /width:0%/);
  assert.match(rowMarkup(html, 'zero'), /class="numeric">0</);
  assert.doesNotMatch(rowMarkup(html, 'missing'), /class="edition-bar /);
  assert.match(rowMarkup(html, 'missing'), /class="numeric">Missing</);
});

test('single-sided and all-zero charts produce finite bounded geometry', () => {
  for (const rows of [
    [{ id: 'one', title: 'One', value: 10 }],
    [{ id: 'one', title: 'One', value: -10 }],
    [{ id: 'one', title: 'One', value: 0 }, { id: 'two', title: 'Two', value: null }],
  ]) {
    const html = chart(rows);
    assert.doesNotMatch(html, /NaN|Infinity/);
    for (const percent of html.matchAll(/(?:left|width):([-\d.]+)%/g)) {
      assert.ok(Number(percent[1]) >= 0 && Number(percent[1]) <= 100);
    }
  }
});

test('chart text is escaped and unsafe or duplicate identities are rejected', () => {
  const html = chart([{ id: 'safe', title: '<img src=x onerror="boom">', value: 1 }]);
  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
  for (const rows of [
    [{ id: 'unsafe"', title: 'Test', value: 1 }],
    [{ id: 'a', title: 'A', value: 1 }, { id: 'a', title: 'B', value: 2 }],
    [{ id: 'a', title: 'A', value: NaN }],
    [{ id: 'a', title: 'A', value: '1' }],
  ]) assert.throws(() => chart(rows));
});

test('tabs retain logical identities and exactly one keyboard entry point', () => {
  const entries = [{ id: 'overview', label: '<Overview>' }, { id: 'library', label: 'Library' }, { id: 'reading', label: 'Reading' }];
  const html = ViewTabs({ entries, selected: 'library', label: 'Page views', panelId: 'edition-panel' });
  assert.equal((html.match(/aria-selected="true"/g) || []).length, 1);
  assert.equal((html.match(/tabindex="0"/g) || []).length, 1);
  assert.equal((html.match(/aria-controls="edition-panel"/g) || []).length, 3);
  assert.match(html, /id="view-library"[^>]*aria-selected="true"[^>]*tabindex="0"[^>]*data-view="library"/);
  assert.match(html, /&lt;Overview&gt;/);
  for (const props of [
    { entries: [...entries, entries[0]], selected: 'library' },
    { entries, selected: 'unknown' },
    { entries: [{ id: 'bad id', label: 'Bad' }], selected: 'bad id' },
  ]) assert.throws(() => ViewTabs({ ...props, label: 'Tabs', panelId: 'edition-panel' }));
});
