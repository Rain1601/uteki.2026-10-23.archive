// Read-only report directory for either a selected company or selected Manager.
// A document appears once at its explicit currentVersion; versions remain in the reader.
import { catalog, getCompany, getManager } from './model.mjs';

const kinds = new Set(['all', 'main', 'topic']);
const fail = message => { throw new Error(`Report directory: ${message}`); };
const text = value => typeof value === 'string' && value.trim().length > 0;
const fold = value => value.normalize('NFKC').replace(/\s+/gu, ' ').toLocaleLowerCase('en-US');
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;

export function paginateRecords(items, page, size) {
  if (!Array.isArray(items) || !Number.isInteger(size) || size < 1) fail('pagination requires records and a positive page size');
  const pages = Math.max(1, Math.ceil(items.length / size));
  if (!Number.isInteger(page) || page < 0 || page >= pages) fail('page is outside the selected result');
  return { rows: items.slice(page * size, (page + 1) * size), page, pages, total: items.length, size };
}

export function getReportDirectory(options, data = catalog) {
  if (!options || typeof options !== 'object' || Array.isArray(options)) fail('an explicit company or Manager scope is required');
  const fields = new Set(['managerId', 'companyId', 'counterpartId', 'kind', 'query', 'page']);
  if (Object.keys(options).some(key => !fields.has(key))) fail('unsupported directory option');
  const hasCompany = Object.hasOwn(options, 'companyId'), hasManager = Object.hasOwn(options, 'managerId');
  if (hasCompany === hasManager) fail('exactly one company or Manager scope is required');
  const { counterpartId = 'all', kind = 'all', query = '', page = 0 } = options;
  if (!text(counterpartId)) fail('counterpart filter must be explicit or all');
  if (!kinds.has(kind)) fail('kind must be all, main or topic');
  if (typeof query !== 'string') fail('title query must be text');
  const context = hasManager ? getManager(options.managerId, data) : getCompany(options.companyId, data);
  const source = context.reports.map(item => ({ ...item, company: hasCompany ? context.company : item.company }));
  const identities = new Set(), counterparts = new Map();
  for (const item of source) {
    if (identities.has(item.document.id)) fail('a report identity is duplicated');
    identities.add(item.document.id);
    if (!['main', 'topic'].includes(item.document.kind)) fail('report kind is unsupported');
    if (!text(item.document.title) || !date(item.report.publishedAt)) fail('report requires a title and valid publication date');
    const entity = hasManager ? item.company : item.manager;
    if (!counterparts.has(entity.id)) counterparts.set(entity.id, { id: entity.id, name: entity.name, entity, count: 0 });
    counterparts.get(entity.id).count += 1;
  }
  if (counterpartId !== 'all' && !counterparts.has(counterpartId)) fail(hasManager ? 'filter company has no reports by this Manager' : 'filter Manager has no reports for this company');
  const related = source.filter(item => counterpartId === 'all' || (hasManager ? item.company.id : item.manager.id) === counterpartId);
  const kindCounts = { all: related.length, main: 0, topic: 0 };
  for (const item of related) kindCounts[item.document.kind] += 1;
  const normalizedQuery = query.trim();
  const rows = related.filter(item => (kind === 'all' || item.document.kind === kind) && (!normalizedQuery || [item.report.title, item.report.titleEn, item.document.title, item.document.titleEn].filter(value => typeof value === 'string').some(value => fold(value).includes(fold(normalizedQuery)))))
    .sort((a, b) => b.report.publishedAt.localeCompare(a.report.publishedAt) || a.document.id.localeCompare(b.document.id, 'en'));
  return {
    ...paginateRecords(rows, page, 8), sourceTotal: source.length,
    counterparts: [...counterparts.values()], kinds: kindCounts,
    filter: { counterpartId, kind, query: normalizedQuery },
    filtered: counterpartId !== 'all' || kind !== 'all' || normalizedQuery !== '',
  };
}
