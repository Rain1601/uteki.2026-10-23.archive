// Explicitly authored focus lifecycle for the frontend prototype. Neither
// catalog membership, report ownership nor holdings implies current attention.
import { catalog, getManager } from './model.mjs';

const STAGES = new Set(['current', 'history', 'planned']);
const FIELDS = new Set(['id', 'managerId', 'companyId', 'stage', 'reason', 'reasonEn', 'since', 'endedAt', 'addedAt']);
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.trim().length > 0;
const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
const fail = message => { throw new Error(`Manager coverage: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const identifier = value => text(value) && value.length <= 160 && !/[\s\u0000-\u001f\u007f/?#]/u.test(value) && value !== '.' && value !== '..';

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const item of Object.values(value)) deepFreeze(item);
    Object.freeze(value);
  }
  return value;
}

export const managerCoverageFixture = deepFreeze({
  id: 'uteki-manager-focus-ui-2026-09-30', version: 'v1', asOf: '2026-09-30', isSimulated: true,
  label: '模拟关注清单', labelEn: 'Illustrative focus list',
  disclosure: '独立编写的前台模拟清单；关注阶段不代表持仓、报告状态或真实任务排期。',
  disclosureEn: 'An independently authored frontend fixture. Focus stages do not imply holdings, report status or scheduled tasks.',
  records: [
    { id: 'north-alphabet-current', managerId: 'north', companyId: 'alphabet', stage: 'current', since: '2026-08-18',
      reason: '持续关注云业务的付费质量与资本投入回报。', reasonEn: 'Following cloud monetization quality and returns on capital spending.' },
    { id: 'north-microsoft-history', managerId: 'north', companyId: 'microsoft', stage: 'history', since: '2026-06-05', endedAt: '2026-09-25',
      reason: '本轮研究已归档，保留既有判断与报告供回看。', reasonEn: 'This research cycle is archived; prior judgments and reports remain available.' },
    { id: 'north-arista-planned', managerId: 'north', companyId: 'arista', stage: 'planned', addedAt: '2026-09-29',
      reason: '拟研究 AI 网络需求的持续性，尚未开始本轮研究。', reasonEn: 'Considering the durability of AI networking demand; this research cycle has not started.' },
    { id: 'field-nvidia-current', managerId: 'field', companyId: 'nvidia', stage: 'current', since: '2026-08-28',
      reason: '持续跟踪供给交付、客户投入与新增需求的匹配。', reasonEn: 'Tracking delivery capacity against customer spending and incremental demand.' },
    { id: 'field-alphabet-history', managerId: 'field', companyId: 'alphabet', stage: 'history', since: '2026-08-10', endedAt: '2026-09-29',
      reason: '本轮产能专题已归档，保留发布报告及其证据。', reasonEn: 'This capacity research cycle is archived with its published report and evidence.' },
    { id: 'field-eaton-planned', managerId: 'field', companyId: 'eaton', stage: 'planned', addedAt: '2026-09-30',
      reason: '拟评估电力设备需求与订单兑现，尚未安排执行日期。', reasonEn: 'Considering power equipment demand and order conversion; no execution date is scheduled.' },
  ],
});

function uniqueEntity(id, kind, data) {
  require(identifier(id), `${kind} id must be an explicit non-empty identifier`);
  require(record(data) && Array.isArray(data[kind]), `selected catalog requires ${kind}`);
  const matches = data[kind].filter(item => item?.id === id);
  require(matches.length === 1, `${kind} ${id} is unknown or ambiguous in the selected catalog`);
  return matches[0];
}

// Source selection is mandatory. An empty records array is a connected, empty
// list, while null/undefined is an absent source and must not receive defaults.
export function getManagerCoverage(managerId, fixture, data = catalog) {
  require(identifier(managerId), 'Manager scope must be an explicit non-empty identifier');
  const context = getManager(managerId, data);
  require(record(fixture) && Array.isArray(fixture.records), 'an explicitly selected focus fixture is required; the source is not connected');
  require(identifier(fixture.id) && identifier(fixture.version), 'fixture id and version are required');
  require(fixture.isSimulated === true, 'fixture must explicitly identify simulated data');
  require(date(fixture.asOf), 'fixture requires a valid asOf date');
  for (const key of ['label', 'labelEn', 'disclosure', 'disclosureEn']) require(text(fixture[key]), `fixture requires ${key}`);

  const ids = new Set(), pairs = new Set();
  for (const item of fixture.records) {
    require(record(item) && Object.keys(item).every(key => FIELDS.has(key)), 'focus record contains invalid or unsupported fields');
    require(identifier(item.id) && !ids.has(item.id), 'focus record ids must be valid and unique');
    ids.add(item.id);
    uniqueEntity(item.managerId, 'managers', data);
    uniqueEntity(item.companyId, 'companies', data);
    const pair = JSON.stringify([item.managerId, item.companyId]);
    require(!pairs.has(pair), 'Manager and company must have only one focus stage');
    pairs.add(pair);
    require(STAGES.has(item.stage), 'focus stage must be current, history or planned');
    require(text(item.reason) && text(item.reasonEn), 'focus reason and reasonEn are required');
    const requiredDates = item.stage === 'history' ? ['since', 'endedAt'] : item.stage === 'current' ? ['since'] : ['addedAt'];
    for (const key of ['since', 'endedAt', 'addedAt']) {
      if (requiredDates.includes(key)) {
        require(date(item[key]) && item[key] <= fixture.asOf, `${item.stage}.${key} must be a valid date on or before asOf`);
      } else {
        require(!Object.hasOwn(item, key), `${key} is not valid for the ${item.stage} stage`);
      }
    }
    if (item.stage === 'history') require(item.since <= item.endedAt, 'history.endedAt must be on or after since');
  }

  const records = fixture.records.filter(item => item.managerId === managerId).map(item => ({
    ...item, company: uniqueEntity(item.companyId, 'companies', data),
    reports: context.reports.filter(report => report.company.id === item.companyId),
  }));
  const counts = { current: 0, history: 0, planned: 0 };
  for (const item of records) counts[item.stage] += 1;
  return {
    managerId, records, counts, total: records.length,
    fixtureId: fixture.id, fixtureVersion: fixture.version, asOf: fixture.asOf, isSimulated: true,
    label: fixture.label, labelEn: fixture.labelEn, disclosure: fixture.disclosure, disclosureEn: fixture.disclosureEn,
  };
}
