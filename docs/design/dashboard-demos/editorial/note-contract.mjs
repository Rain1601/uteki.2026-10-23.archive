const KINDS = new Set(['observation', 'question', 'decision']);

function identities(recordIds) {
  if (!Array.isArray(recordIds) || recordIds.some(id => typeof id !== 'string' || !id.trim()) || new Set(recordIds).size !== recordIds.length) {
    throw new TypeError('Invalid record identities');
  }
  return new Set(recordIds);
}

function realDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split('-').map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= days[month - 1];
}

export function validateNote(input, recordIds) {
  const allowedIds = identities(recordIds);
  const source = input && typeof input === 'object' && !Array.isArray(input) ? input : {};
  const errors = {};
  const title = typeof source.title === 'string' ? source.title.trim() : '';
  const body = typeof source.body === 'string' ? source.body.trim() : '';
  if (typeof source.recordId !== 'string' || !allowedIds.has(source.recordId)) errors.recordId = 'Choose a valid record';
  if (!title) errors.title = 'Title is required';
  else if ([...title].length > 80) errors.title = 'Title must be at most 80 characters';
  if (!realDate(source.date)) errors.date = 'Enter a valid YYYY-MM-DD date';
  if (!body) errors.body = 'Body is required';
  else if ([...body].length > 2000) errors.body = 'Body must be at most 2000 characters';
  if (!KINDS.has(source.kind)) errors.kind = 'Choose a valid note kind';
  if (typeof source.followUp !== 'boolean') errors.followUp = 'Follow-up must be boolean';
  const ok = Object.keys(errors).length === 0;
  return { ok, errors, value: ok ? { recordId: source.recordId, title, date: source.date, body, kind: source.kind, followUp: source.followUp } : null };
}

export function readNotes(value, recordIds) {
  identities(recordIds);
  if (!value || typeof value !== 'object' || Array.isArray(value) || value.version !== 1 || !Array.isArray(value.notes)) {
    throw new TypeError('Invalid notes document');
  }
  const ids = new Set();
  return value.notes.map((note, index) => {
    if (!note || typeof note !== 'object' || typeof note.id !== 'string' || !note.id.trim()) throw new TypeError(`Invalid note identity at index ${index}`);
    if (ids.has(note.id)) throw new TypeError(`Duplicate note identity: ${note.id}`);
    ids.add(note.id);
    const result = validateNote(note, recordIds);
    if (!result.ok) throw new TypeError(`Invalid note at index ${index}: ${Object.keys(result.errors).join(', ')}`);
    return { id: note.id, ...result.value };
  });
}

export function serializeNotes(notes, recordIds) {
  return JSON.stringify({ version: 1, notes: readNotes({ version: 1, notes }, recordIds) });
}
