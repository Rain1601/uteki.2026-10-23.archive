// Read-only projections of the selected fictional research catalog and event
// fixture. Research coverage is not a running task or an investment execution.
import { catalog, getManager, getReport, formatRoute } from './model.mjs';
import { investmentEventFixture, getInvestmentEvents } from './investment-events.mjs';

const FILTERS = new Set(['all', 'open', 'published']);
const KINDS = new Set(['all', 'buy', 'sell', 'report']);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = message => { throw new Error(`Manager activity: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const text = value => typeof value === 'string' && value.trim().length > 0;

function companyFor(companyId, data) {
  require(record(data) && Array.isArray(data.companies), 'company catalog is required');
  const matches = data.companies.filter(company => company.id === companyId);
  require(matches.length === 1, `company ${companyId} is unknown or ambiguous in the selected catalog`);
  return matches[0];
}

function reportLink(managerId, companyId, reference, data) {
  const result = getReport(companyId, reference.reportId, reference.version, data);
  require(result.manager.id === managerId, 'report belongs to another Manager');
  const route = {
    managerId, companyId, view: 'report', reportId: reference.reportId, version: reference.version,
    ...(reference.sectionId === undefined ? {} : { sectionId: reference.sectionId }),
  };
  return { route, href: formatRoute(route, data), label: `${result.document.title} · ${reference.version}` };
}

const recentFirst = (left, right) => String(right.date || '').localeCompare(String(left.date || '')) || left.id.localeCompare(right.id);

// "Published" is the output category: an already-published report can still
// require review. "Open" includes those reviews as well as unresolved questions
// without manufacturing rows from directory coverage. Filters intentionally overlap.
export function getManagerResearchRows(managerId, filter = 'all', data = catalog) {
  require(FILTERS.has(filter), 'research filter must be all, open or published');
  const context = getManager(managerId, data);
  const questions = context.events.filter(({ event }) => event.unresolved === true).map(({ event, links }) => ({
    id: `question:${event.id}`, type: 'question', kind: 'question', managerId,
    companyId: event.companyId, company: companyFor(event.companyId, data),
    title: event.title, ...(event.titleEn === undefined ? {} : { titleEn: event.titleEn }),
    status: 'unresolved', sourceStatus: event.kind, date: event.date || null,
    links: links.map(reference => reportLink(managerId, event.companyId, reference, data)),
  }));
  const reports = context.reports.map(({ company, document, report }) => ({
    id: `report:${document.id}`, type: 'report', kind: 'report', managerId,
    companyId: company.id, company, title: report.title || document.title,
    ...((report.titleEn || document.titleEn) ? { titleEn: report.titleEn || document.titleEn } : {}),
    status: report.status === 'current' ? 'published' : report.status,
    sourceStatus: report.status, date: report.publishedAt || null,
    reportId: document.id, version: report.version,
    links: [reportLink(managerId, company.id, { reportId: document.id, version: report.version }, data)],
  }));
  return [...questions, ...reports].filter(row => filter === 'all' ||
    (filter === 'published' ? row.type === 'report' : row.type === 'question' || row.status === 'review'))
    .sort(recentFirst);
}

function fixtureRange(fixture) {
  require(record(fixture) && Array.isArray(fixture.events), 'an explicitly selected event fixture is required');
  // A populated fixture can declare its observed range through its exact event
  // dates. A completely empty fixture must supply coverage explicitly; no sample
  // period or current date is substituted to make a query succeed.
  if (fixture.coverage !== undefined) {
    require(record(fixture.coverage), 'fixture coverage must contain start and end dates');
    return { start: fixture.coverage.start, end: fixture.coverage.end };
  }
  require(fixture.events.length > 0, 'empty fixture requires explicit coverage.start and coverage.end');
  const dates = fixture.events.map(event => event?.date).sort();
  return { start: dates[0], end: dates.at(-1) };
}

// Full authored history, independent from chart periods or current allocations.
// null is not an empty connection: callers render their explicit no-source state.
export function getManagerExecutionHistory(input, fixture = investmentEventFixture, data = catalog) {
  require(record(input) && Object.keys(input).every(key => ['managerId', 'kind'].includes(key)), 'execution query requires only managerId and kind');
  const { managerId, kind = 'all' } = input;
  require(KINDS.has(kind), 'execution kind must be all, buy, sell or report');
  getManager(managerId, data);
  const range = fixtureRange(fixture);
  for (const key of ['label', 'labelEn', 'disclosure', 'disclosureEn']) require(text(fixture[key]), `event fixture requires ${key}`);
  const query = getInvestmentEvents({ managerId, ...range, kind: 'all', granularity: 'day' }, fixture);
  require(fixture.events.every(event => event.date >= range.start && event.date <= range.end), 'fixture events fall outside explicit date coverage');
  const counts = { all: query.events.length, buy: 0, sell: 0, report: 0 };
  query.events.forEach(event => { counts[event.kind] += 1; });
  const events = query.events.filter(event => kind === 'all' || event.kind === kind).map(event => {
    if (event.kind === 'report') {
      const source = getReport(event.companyId, event.report.reportId, event.report.version, data);
      require(source.report.publishedAt === event.date, 'report event date differs from the selected catalog publication');
    }
    return {
      id: event.id, managerId: event.managerId, companyId: event.companyId,
      company: companyFor(event.companyId, data), kind: event.kind, type: event.kind,
      title: event.title, titleEn: event.titleEn, date: event.date, isSimulated: true,
      ...(event.kind === 'report' ? { report: { ...event.report } } : {}),
      links: event.kind === 'report' ? [reportLink(managerId, event.companyId, event.report, data)] : [],
    };
  }).sort(recentFirst);
  return {
    events, counts, range, coverage: fixture.coverage === undefined ? 'fixture-events' : 'explicit-range',
    isSimulated: true, fixtureId: fixture.id, fixtureVersion: fixture.version,
    label: fixture.label, labelEn: fixture.labelEn, disclosure: fixture.disclosure, disclosureEn: fixture.disclosureEn,
  };
}
