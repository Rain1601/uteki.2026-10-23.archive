// Explicit UI samples, authored independently of holdings and return curves.
// They are not a reconstructed ledger, live executions, or research recommendations.
import { getReport } from './model.mjs';

const DAY = 86400000;
const KINDS = new Set(['buy', 'sell', 'report']);
const GRANULARITIES = new Set(['auto', 'day', 'week', 'month']);
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = message => { throw new Error(`Investment events: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const text = value => typeof value === 'string' && value.trim().length > 0;

function identifier(value, label) {
  require(typeof value === 'string' && value.length > 0 && value.length <= 160 &&
    !/[\s\u0000-\u001f\u007f/?#]/u.test(value) && value !== '.' && value !== '..',
  `${label} must be an explicit non-empty identifier`);
  return value;
}

function dateValue(value, label) {
  require(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value), `${label} must be a YYYY-MM-DD date`);
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  require(Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value, `${label} is not a valid date`);
  return timestamp;
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// Copy only publication identity and date from explicitly selected demo reports.
// getReport verifies each company / report / version; no report prose is copied.
function publication(companyId, reportId, version) {
  const context = getReport(companyId, reportId, version);
  return { companyId, reportId, version, managerId: context.manager.id, publishedAt: context.report.publishedAt };
}

export const investmentEventFixtureV1 = freeze({
  id: 'uteki-investment-events-ui-2026-09-30', version: 'v1', isSimulated: true,
  label: '模拟事件 · 非实盘', labelEn: 'Illustrative events · Not live trading',
  disclosure: '买卖事件为独立编写的界面示例，未从当前持仓或收益反推，不构成可核算交易账本。报告事件引用已有演示报告的实际版本与发布日期。',
  disclosureEn: 'Trade events are independently authored UI examples, not inferred from holdings or returns and not an accounting ledger. Report events reference the publication dates and versions of existing demo reports.',
  scope: {
    managerIds: ['north', 'field'],
    companyIds: ['alphabet', 'microsoft', 'nvidia', 'costco', 'arista', 'eaton'],
  },
  reportPublications: [
    publication('alphabet', 'alpha-north-main', 'v1'),
    publication('alphabet', 'alpha-north-main', 'v2'),
    publication('alphabet', 'alpha-north-cloud', 'v1'),
    publication('alphabet', 'alpha-north-cloud', 'v2'),
    publication('microsoft', 'ms-north-main', 'v1'),
    publication('alphabet', 'alpha-field-main', 'v1'),
    publication('alphabet', 'alpha-field-main', 'v2'),
    publication('alphabet', 'alpha-field-capacity', 'v1'),
  ],
  events: [
    { id: 'north-buy-alphabet-20251008', managerId: 'north', companyId: 'alphabet', date: '2025-10-08', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'north-buy-microsoft-20251112', managerId: 'north', companyId: 'microsoft', date: '2025-11-12', kind: 'buy', title: '买入 Microsoft', titleEn: 'Buy Microsoft' },
    { id: 'north-sell-costco-20251217', managerId: 'north', companyId: 'costco', date: '2025-12-17', kind: 'sell', title: '卖出 Costco', titleEn: 'Sell Costco' },
    { id: 'north-buy-nvidia-20260114', managerId: 'north', companyId: 'nvidia', date: '2026-01-14', kind: 'buy', title: '买入 NVIDIA', titleEn: 'Buy NVIDIA' },
    { id: 'north-sell-nvidia-20260220', managerId: 'north', companyId: 'nvidia', date: '2026-02-20', kind: 'sell', title: '卖出 NVIDIA', titleEn: 'Sell NVIDIA' },
    { id: 'north-buy-costco-20260311', managerId: 'north', companyId: 'costco', date: '2026-03-11', kind: 'buy', title: '买入 Costco', titleEn: 'Buy Costco' },
    { id: 'north-buy-alphabet-20260416', managerId: 'north', companyId: 'alphabet', date: '2026-04-16', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'north-sell-microsoft-20260521', managerId: 'north', companyId: 'microsoft', date: '2026-05-21', kind: 'sell', title: '卖出 Microsoft', titleEn: 'Sell Microsoft' },
    { id: 'north-buy-microsoft-20260618', managerId: 'north', companyId: 'microsoft', date: '2026-06-18', kind: 'buy', title: '买入 Microsoft', titleEn: 'Buy Microsoft' },
    { id: 'north-buy-nvidia-20260715', managerId: 'north', companyId: 'nvidia', date: '2026-07-15', kind: 'buy', title: '买入 NVIDIA', titleEn: 'Buy NVIDIA' },
    { id: 'north-sell-costco-20260812', managerId: 'north', companyId: 'costco', date: '2026-08-12', kind: 'sell', title: '卖出 Costco', titleEn: 'Sell Costco' },
    { id: 'north-buy-alphabet-20260903', managerId: 'north', companyId: 'alphabet', date: '2026-09-03', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'north-sell-nvidia-20260910', managerId: 'north', companyId: 'nvidia', date: '2026-09-10', kind: 'sell', title: '卖出 NVIDIA', titleEn: 'Sell NVIDIA' },
    { id: 'north-report-main-v1', managerId: 'north', companyId: 'alphabet', date: '2026-09-18', kind: 'report', title: 'Alphabet 公司研究 · v1', titleEn: 'Alphabet company research · v1', report: { reportId: 'alpha-north-main', version: 'v1' } },
    { id: 'north-buy-alphabet-20260918', managerId: 'north', companyId: 'alphabet', date: '2026-09-18', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'north-report-cloud-v1', managerId: 'north', companyId: 'alphabet', date: '2026-09-19', kind: 'report', title: 'Alphabet 云业务专题 · v1', titleEn: 'Alphabet cloud research · v1', report: { reportId: 'alpha-north-cloud', version: 'v1' } },
    { id: 'north-buy-costco-20260922', managerId: 'north', companyId: 'costco', date: '2026-09-22', kind: 'buy', title: '买入 Costco', titleEn: 'Buy Costco' },
    { id: 'north-report-microsoft-v1', managerId: 'north', companyId: 'microsoft', date: '2026-09-26', kind: 'report', title: 'Microsoft 公司研究 · v1', titleEn: 'Microsoft company research · v1', report: { reportId: 'ms-north-main', version: 'v1' } },
    { id: 'north-report-cloud-v2', managerId: 'north', companyId: 'alphabet', date: '2026-09-28', kind: 'report', title: 'Alphabet 云业务专题 · v2', titleEn: 'Alphabet cloud research · v2', report: { reportId: 'alpha-north-cloud', version: 'v2' } },
    { id: 'north-buy-microsoft-20260928', managerId: 'north', companyId: 'microsoft', date: '2026-09-28', kind: 'buy', title: '买入 Microsoft', titleEn: 'Buy Microsoft' },
    { id: 'north-sell-nvidia-20260928', managerId: 'north', companyId: 'nvidia', date: '2026-09-28', kind: 'sell', title: '卖出 NVIDIA', titleEn: 'Sell NVIDIA' },
    { id: 'north-report-main-v2', managerId: 'north', companyId: 'alphabet', date: '2026-09-29', kind: 'report', title: 'Alphabet 公司研究 · v2', titleEn: 'Alphabet company research · v2', report: { reportId: 'alpha-north-main', version: 'v2' } },
    { id: 'field-buy-arista-20251015', managerId: 'field', companyId: 'arista', date: '2025-10-15', kind: 'buy', title: '买入 Arista', titleEn: 'Buy Arista' },
    { id: 'field-buy-eaton-20251120', managerId: 'field', companyId: 'eaton', date: '2025-11-20', kind: 'buy', title: '买入 Eaton', titleEn: 'Buy Eaton' },
    { id: 'field-sell-alphabet-20251223', managerId: 'field', companyId: 'alphabet', date: '2025-12-23', kind: 'sell', title: '卖出 Alphabet', titleEn: 'Sell Alphabet' },
    { id: 'field-buy-costco-20260122', managerId: 'field', companyId: 'costco', date: '2026-01-22', kind: 'buy', title: '买入 Costco', titleEn: 'Buy Costco' },
    { id: 'field-buy-microsoft-20260212', managerId: 'field', companyId: 'microsoft', date: '2026-02-12', kind: 'buy', title: '买入 Microsoft', titleEn: 'Buy Microsoft' },
    { id: 'field-sell-eaton-20260319', managerId: 'field', companyId: 'eaton', date: '2026-03-19', kind: 'sell', title: '卖出 Eaton', titleEn: 'Sell Eaton' },
    { id: 'field-buy-alphabet-20260423', managerId: 'field', companyId: 'alphabet', date: '2026-04-23', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'field-buy-arista-20260514', managerId: 'field', companyId: 'arista', date: '2026-05-14', kind: 'buy', title: '买入 Arista', titleEn: 'Buy Arista' },
    { id: 'field-sell-costco-20260625', managerId: 'field', companyId: 'costco', date: '2026-06-25', kind: 'sell', title: '卖出 Costco', titleEn: 'Sell Costco' },
    { id: 'field-buy-eaton-20260709', managerId: 'field', companyId: 'eaton', date: '2026-07-09', kind: 'buy', title: '买入 Eaton', titleEn: 'Buy Eaton' },
    { id: 'field-sell-microsoft-20260820', managerId: 'field', companyId: 'microsoft', date: '2026-08-20', kind: 'sell', title: '卖出 Microsoft', titleEn: 'Sell Microsoft' },
    { id: 'field-buy-arista-20260904', managerId: 'field', companyId: 'arista', date: '2026-09-04', kind: 'buy', title: '买入 Arista', titleEn: 'Buy Arista' },
    { id: 'field-sell-eaton-20260914', managerId: 'field', companyId: 'eaton', date: '2026-09-14', kind: 'sell', title: '卖出 Eaton', titleEn: 'Sell Eaton' },
    { id: 'field-report-main-v1', managerId: 'field', companyId: 'alphabet', date: '2026-09-19', kind: 'report', title: 'Alphabet 公司研究 · v1', titleEn: 'Alphabet company research · v1', report: { reportId: 'alpha-field-main', version: 'v1' } },
    { id: 'field-buy-alphabet-20260919', managerId: 'field', companyId: 'alphabet', date: '2026-09-19', kind: 'buy', title: '买入 Alphabet', titleEn: 'Buy Alphabet' },
    { id: 'field-buy-eaton-20260923', managerId: 'field', companyId: 'eaton', date: '2026-09-23', kind: 'buy', title: '买入 Eaton', titleEn: 'Buy Eaton' },
    { id: 'field-report-capacity-v1', managerId: 'field', companyId: 'alphabet', date: '2026-09-27', kind: 'report', title: 'Alphabet 产能专题 · v1', titleEn: 'Alphabet capacity research · v1', report: { reportId: 'alpha-field-capacity', version: 'v1' } },
    { id: 'field-report-main-v2', managerId: 'field', companyId: 'alphabet', date: '2026-09-28', kind: 'report', title: 'Alphabet 公司研究 · v2', titleEn: 'Alphabet company research · v2', report: { reportId: 'alpha-field-main', version: 'v2' } },
    { id: 'field-sell-arista-20260928', managerId: 'field', companyId: 'arista', date: '2026-09-28', kind: 'sell', title: '卖出 Arista', titleEn: 'Sell Arista' },
  ],
});

export const investmentEventFixture = investmentEventFixtureV1;

function validateFixture(fixture) {
  require(isRecord(fixture) && fixture.isSimulated === true, 'fixture must explicitly identify simulated data');
  identifier(fixture.id, 'fixture id');
  identifier(fixture.version, 'fixture version');
  require(isRecord(fixture.scope), 'fixture requires an explicit scope');
  const ids = key => {
    const values = fixture.scope[key];
    require(Array.isArray(values) && values.length > 0, `fixture scope.${key} must be a non-empty array`);
    values.forEach(value => identifier(value, key));
    require(new Set(values).size === values.length, `fixture scope.${key} contains duplicate identifiers`);
    return new Set(values);
  };
  const managerIds = ids('managerIds'), companyIds = ids('companyIds');
  require(Array.isArray(fixture.reportPublications), 'fixture reportPublications must be an array');
  const publications = new Map();
  const reportOwners = new Map();
  for (const item of fixture.reportPublications) {
    require(isRecord(item), 'publication must be an object');
    identifier(item.reportId, 'publication reportId');
    identifier(item.version, 'publication version');
    require(managerIds.has(item.managerId) && companyIds.has(item.companyId), 'publication has unknown Manager or company scope');
    dateValue(item.publishedAt, 'publication publishedAt');
    const key = JSON.stringify([item.reportId, item.version]);
    require(!publications.has(key), 'publication report/version must be unique');
    const owner = JSON.stringify([item.managerId, item.companyId]);
    require(!reportOwners.has(item.reportId) || reportOwners.get(item.reportId) === owner, 'versions of a report must share one Manager and company');
    reportOwners.set(item.reportId, owner);
    publications.set(key, item);
  }
  require(Array.isArray(fixture.events), 'fixture events must be an array');
  const eventIds = new Set();
  for (const event of fixture.events) {
    require(isRecord(event), 'event must be an object');
    identifier(event.id, 'event id');
    require(!eventIds.has(event.id), 'event ids must be unique');
    eventIds.add(event.id);
    require(managerIds.has(event.managerId) && companyIds.has(event.companyId), 'event has unknown Manager or company scope');
    dateValue(event.date, 'event date');
    require(KINDS.has(event.kind), 'event kind is unsupported');
    require(text(event.title) && text(event.titleEn), 'event requires bilingual titles');
    if (event.kind === 'report') {
      require(isRecord(event.report), 'report event requires a report/version reference');
      identifier(event.report.reportId, 'event reportId');
      identifier(event.report.version, 'event version');
      const entry = publications.get(JSON.stringify([event.report.reportId, event.report.version]));
      require(entry && entry.managerId === event.managerId && entry.companyId === event.companyId,
        'report event does not match the publication Manager/company/version');
      require(entry.publishedAt === event.date, 'report event date must match its publication date');
    } else {
      require(!Object.hasOwn(event, 'report'), 'trade events cannot imply a report publication');
    }
  }
  return managerIds;
}

function bucketFor(date, granularity) {
  const start = new Date(`${date}T00:00:00Z`);
  let end;
  if (granularity === 'week') {
    start.setUTCDate(start.getUTCDate() - (start.getUTCDay() + 6) % 7);
    end = new Date(start.getTime() + 6 * DAY);
  } else if (granularity === 'month') {
    start.setUTCDate(1);
    end = new Date(start);
    end.setUTCMonth(end.getUTCMonth() + 1);
    end.setUTCDate(0);
  } else end = new Date(start);
  return { start: start.toISOString().slice(0, 10), end: end.toISOString().slice(0, 10) };
}

// Dates are inclusive. Empty groups are omitted; events are never aggregated away.
// Group bounds describe calendar buckets clipped to the selected range, while
// every event retains its exact date. Collision handling belongs to the renderer.
export function getInvestmentEvents(input, fixture = investmentEventFixture) {
  require(isRecord(input), 'query must provide an explicit Manager and date range');
  const allowed = new Set(['managerId', 'start', 'end', 'kind', 'granularity']);
  require(Object.keys(input).every(key => allowed.has(key)), 'query contains unsupported scope or fields');
  const { managerId, start, end, kind = 'all', granularity: requested = 'auto' } = input;
  identifier(managerId, 'managerId');
  const first = dateValue(start, 'start'), last = dateValue(end, 'end');
  require(first <= last, 'start must not be after end');
  require(kind === 'all' || KINDS.has(kind), 'kind must be all, buy, sell or report');
  require(GRANULARITIES.has(requested), 'granularity must be auto, day, week or month');
  const managerIds = validateFixture(fixture);
  require(managerIds.has(managerId), `Manager ${managerId} is unknown in the selected fixture`);
  const days = (last - first) / DAY + 1;
  const granularity = requested === 'auto' ? (days <= 45 ? 'day' : days <= 120 ? 'week' : 'month') : requested;
  const events = fixture.events.filter(event => event.managerId === managerId && event.date >= start && event.date <= end &&
    (kind === 'all' || event.kind === kind)).sort((a, b) => a.date.localeCompare(b.date) || a.id.localeCompare(b.id));
  const grouped = new Map();
  for (const event of events) {
    const bucket = bucketFor(event.date, granularity);
    const id = `${managerId}:${granularity}:${bucket.start}`;
    if (!grouped.has(id)) grouped.set(id, { id, start: bucket.start < start ? start : bucket.start, end: bucket.end > end ? end : bucket.end, events: [] });
    grouped.get(id).events.push(event);
  }
  return { events, groups: [...grouped.values()], granularity };
}
