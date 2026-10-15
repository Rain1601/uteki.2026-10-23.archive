import test from 'node:test';
import assert from 'node:assert/strict';
import { validateNote, readNotes, serializeNotes } from './note-contract.mjs';

const recordIds = ['alpha', 'beta'];
const input = Object.freeze({ recordId: 'alpha', title: '  核查需求  ', date: '2024-02-29', body: '  Check evidence.  ', kind: 'question', followUp: false });

test('valid notes normalize prose without modifying source input', () => {
  const result = validateNote(input, recordIds);
  assert.equal(result.ok, true);
  assert.deepEqual(result.errors, {});
  assert.deepEqual(result.value, { ...input, title: '核查需求', body: 'Check evidence.' });
  assert.equal(input.title, '  核查需求  ');
  assert.equal(input.body, '  Check evidence.  ');
  assert.equal(validateNote({ ...input, date: '2099-12-31', followUp: true }, recordIds).ok, true);
});

test('dates use strict calendar validation without relative-date restrictions', () => {
  for (const date of ['2023-02-29', '1900-02-29', '2024-04-31', '2024-00-10', '2024-13-10', '2024-01-00', '2024-2-9', '2024-02-29T00:00:00Z', ' 2024-02-29', '0000-01-01']) {
    const result = validateNote({ ...input, date }, recordIds);
    assert.equal(result.ok, false, date);
    assert.equal(result.value, null);
    assert.equal(result.errors.date, 'Enter a valid YYYY-MM-DD date');
  }
  assert.equal(validateNote({ ...input, date: '2000-02-29' }, recordIds).ok, true);
  assert.equal(validateNote({ ...input, date: '0001-01-01' }, recordIds).ok, true);
});

test('required prose rejects blank and numeric zero but retains literal string zero', () => {
  for (const body of ['', ' \n\t ', 0, null, undefined]) {
    assert.equal(validateNote({ ...input, body }, recordIds).errors.body, 'Body is required');
  }
  assert.equal(validateNote({ ...input, body: '0' }, recordIds).ok, true);
  assert.equal(validateNote({ ...input, title: '😀'.repeat(80), body: '中'.repeat(2000) }, recordIds).ok, true);
  assert.equal(validateNote({ ...input, title: '😀'.repeat(81) }, recordIds).errors.title, 'Title must be at most 80 characters');
  assert.equal(validateNote({ ...input, body: '中'.repeat(2001) }, recordIds).errors.body, 'Body must be at most 2000 characters');
});

test('record scope and explicit enums reject implicit defaults', () => {
  assert.equal(validateNote({ ...input, recordId: 'outside' }, recordIds).errors.recordId, 'Choose a valid record');
  assert.equal(validateNote({ ...input, kind: 'other' }, recordIds).errors.kind, 'Choose a valid note kind');
  assert.equal(validateNote({ ...input, followUp: 0 }, recordIds).errors.followUp, 'Follow-up must be boolean');
  assert.equal(validateNote(null, recordIds).ok, false);
  assert.throws(() => validateNote(input, ['alpha', 'alpha']), /identities/);
});

test('versioned serialization and reads preserve identities and reject corrupted documents', () => {
  const notes = Object.freeze([Object.freeze({ id: 'note-1', ...input })]);
  const json = serializeNotes(notes, recordIds);
  const decoded = JSON.parse(json);
  assert.equal(decoded.version, 1);
  assert.deepEqual(readNotes(decoded, recordIds), [{ id: 'note-1', ...validateNote(input, recordIds).value }]);
  assert.equal(notes[0].title, input.title);
  for (const value of [null, [], { version: 2, notes: [] }, { version: 1, notes: null }, { version: 1, notes: [{ ...input, id: '' }] }, { version: 1, notes: [{ ...input, id: 'x', recordId: 'outside' }] }]) {
    assert.throws(() => readNotes(value, recordIds), TypeError);
  }
  assert.throws(() => serializeNotes([{ id: 'same', ...input }, { id: 'same', ...input }], recordIds), /Duplicate/);
});
