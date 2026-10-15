import test from 'node:test';
import assert from 'node:assert/strict';
import { TextField, ActionMenu, Notice, InlineAlert } from './workspace-controls.mjs';

test('text fields escape content and connect required inputs to help and errors', () => {
  const html = TextField({ id: 'note-title', label: '<Title>', value: '" autofocus onfocus="bad', help: '<Help>', error: '<Error>', required: true, maxLength: 80 });
  assert.match(html, /for="note-title"/);
  assert.match(html, /id="note-title" name="note-title" required/);
  assert.match(html, /aria-describedby="note-title-help note-title-error"/);
  assert.match(html, /aria-invalid="true"/);
  assert.match(html, /id="note-title-help"/);
  assert.match(html, /id="note-title-error"/);
  assert.match(html, /&lt;Title&gt; \*/);
  assert.match(html, /value="&quot; autofocus onfocus=&quot;bad"/);
  assert.doesNotMatch(html, /<Help>|<Error>/);
  const multiline = TextField({ id: 'note-body', label: 'Body', value: '</textarea><script>bad</script>', multiline: true, maxLength: 2000 });
  assert.equal((multiline.match(/<textarea /g) || []).length, 1);
  assert.doesNotMatch(multiline, /<script>/);
  assert.match(multiline, /aria-invalid="false"/);
  assert.match(multiline, /id="note-body-error"[^>]*hidden/);
});

test('field limits and identities must be explicit and valid', () => {
  for (const maxLength of [undefined, 0, -1, 1.5, '80']) {
    assert.throws(() => TextField({ id: 'title', label: 'Title', maxLength }));
  }
  for (const id of ['unsafe id', 'unsafe"', undefined, null, 12]) {
    assert.throws(() => TextField({ id, label: 'Title', maxLength: 80 }));
  }
});

test('menus preserve action identities and disabled state while escaping copy', () => {
  const html = ActionMenu({ id: 'actions', label: '<Actions>', items: [
    { id: 'export', label: '<Export>', hint: '"JSON"', disabled: true },
    { id: 'new', label: 'New note' },
  ] });
  assert.match(html, /role="menu" aria-label="&lt;Actions&gt;"/);
  assert.match(html, /role="menuitem" tabindex="-1" data-menu-action="export" disabled/);
  assert.match(html, /role="menuitem" tabindex="-1" data-menu-action="new" >/);
  assert.match(html, /&lt;Export&gt;/);
  assert.match(html, /&quot;JSON&quot;/);
  assert.throws(() => ActionMenu({ id: 'menu', label: 'Menu', items: [{ id: 'a' }, { id: 'a' }] }), /Duplicate/);
  assert.throws(() => ActionMenu({ id: 'menu', label: 'Menu', items: [{ id: undefined }] }));
});

test('feedback errors announce alerts and escape messages and action labels', () => {
  const error = Notice({ message: '<Failure>', tone: 'error', action: { label: '<Retry>' }, closeLabel: '"Close"' });
  assert.match(error, /role="alert"/);
  assert.match(error, /&lt;Failure&gt;/);
  assert.match(error, /data-notice-action>&lt;Retry&gt;/);
  assert.match(error, /aria-label="&quot;Close&quot;"/);
  assert.match(Notice({ message: 'Saved', tone: 'success', closeLabel: 'Close' }), /role="status"/);
  assert.match(InlineAlert({ message: '<Invalid>', tone: 'error' }), /role="alert">&lt;Invalid&gt;/);
  assert.throws(() => Notice({ message: 'Failure', tone: 'unknown' }), /tone/);
});
