import { institutionFixture } from './institution-data.mjs';

const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const fail = message => { throw new Error(`Allocation history: ${message}`); };
const require = (condition, message) => { if (!condition) fail(message); };
const close = (left, right) => Math.abs(left - right) < 0.000001;

function identifier(value, label) {
  require(typeof value === 'string' && value.length > 0 && value.length <= 160 &&
    !/[\s\u0000-\u001f\u007f/?#]/u.test(value) && value !== '.' && value !== '..',
  `${label} must be an explicit identifier`);
  return value;
}

function date(value, label) {
  require(typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value), `${label} must be a YYYY-MM-DD date`);
  const time = Date.parse(`${value}T00:00:00Z`);
  require(Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value, `${label} is invalid`);
}

function identifiers(values, label) {
  require(Array.isArray(values) && values.length > 0, `${label} must be a non-empty list`);
  values.forEach(value => identifier(value, label));
  require(new Set(values).size === values.length, `${label} must be unique`);
  return new Set(values);
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

// Each dated row is independently authored for this UI example. The last item
// is explicit cash, not a remainder inferred from other assets. These histories
// are not reconstructed from events, return curves or the current portfolio.
function snapshots(companyIds, rows) {
  return rows.map(([date, ...weights]) => ({
    date,
    holdings: companyIds.map((companyId, index) => ({ companyId, weightPct: weights[index] })),
    cashWeightPct: weights[companyIds.length],
  }));
}

const northCompanies = ['alphabet', 'microsoft', 'nvidia', 'costco'];
const fieldCompanies = ['alphabet', 'microsoft', 'costco', 'arista', 'eaton'];

export const allocationHistoryFixtureV1 = freeze({
  id: 'uteki-allocation-history-ui-2026-09-30', version: 'v1', isSimulated: true,
  label: '模拟配置快照 · 非实盘', labelEn: 'Illustrative allocation snapshots · Not live',
  disclosure: '历史配置是逐期独立编写的界面样本，不从当前持仓、买卖事件或收益反推。仅展示明确日期的快照，末日与当前演示持仓核对；不代表实盘、回测或可核算交易账本。',
  disclosureEn: 'Allocation histories are independently authored UI snapshots, not inferred from current holdings, trade events or returns. Only explicit dates are shown; the final snapshot is checked against the current demo portfolio. This is not live trading, a backtest or an accounting ledger.',
  sampling: 'explicit-snapshots',
  scope: {
    institutionId: 'uteki', managerIds: ['north', 'field'],
    companyIds: ['alphabet', 'microsoft', 'nvidia', 'costco', 'arista', 'eaton'],
  },
  coverage: { start: '2025-09-30', end: '2026-09-30' },
  // This reference validates only the final snapshot. It never supplies missing
  // historical values. Alternative fixtures must provide their own reference.
  currentSnapshot: {
    id: institutionFixture.simulation.id, version: institutionFixture.simulation.version,
    institutionId: institutionFixture.institution.id, asOf: institutionFixture.simulation.asOf,
    agents: institutionFixture.agents.map(agent => ({
      managerId: agent.managerId,
      holdings: agent.portfolio.holdings.map(({ companyId, weightPct }) => ({ companyId, weightPct })),
      cashWeightPct: agent.portfolio.cashWeightPct,
    })),
  },
  histories: [
    { managerId: 'north', companyIds: northCompanies, snapshots: snapshots(northCompanies, [
      ['2025-09-30', 24, 30, 0, 22, 24],
      ['2025-10-31', 28, 28, 4, 21, 19],
      ['2025-11-30', 27, 31, 7, 19, 16],
      ['2025-12-31', 29, 30, 9, 18, 14],
      ['2026-01-31', 28, 27, 14, 18, 13],
      ['2026-02-28', 30, 26, 12, 18, 14],
      ['2026-03-31', 29, 26, 14, 20, 11],
      ['2026-04-30', 32, 25, 15, 18, 10],
      ['2026-05-31', 31, 22, 18, 18, 11],
      ['2026-06-30', 30, 25, 18, 17, 10],
      ['2026-07-31', 29, 25, 22, 15, 9],
      ['2026-08-31', 31, 24, 22, 13, 10],
      ['2026-09-07', 32, 24, 21, 13, 10],
      ['2026-09-14', 31, 24, 19, 14, 12],
      ['2026-09-21', 32, 24, 19, 15, 10],
      ['2026-09-30', 30, 25, 20, 15, 10],
    ]) },
    { managerId: 'field', companyIds: fieldCompanies, snapshots: snapshots(fieldCompanies, [
      ['2025-09-30', 20, 0, 18, 22, 15, 25],
      ['2025-10-31', 19, 0, 17, 27, 17, 20],
      ['2025-11-30', 18, 3, 16, 26, 20, 17],
      ['2025-12-31', 16, 5, 16, 26, 20, 17],
      ['2026-01-31', 17, 7, 20, 24, 18, 14],
      ['2026-02-28', 18, 12, 18, 23, 17, 12],
      ['2026-03-31', 20, 12, 18, 24, 14, 12],
      ['2026-04-30', 23, 12, 17, 23, 14, 11],
      ['2026-05-31', 22, 12, 17, 26, 13, 10],
      ['2026-06-30', 22, 13, 14, 25, 14, 12],
      ['2026-07-31', 21, 14, 14, 23, 17, 11],
      ['2026-08-31', 21, 12, 15, 24, 16, 12],
      ['2026-09-07', 20, 12, 15, 25, 16, 12],
      ['2026-09-14', 21, 13, 15, 23, 13, 15],
      ['2026-09-21', 22, 14, 15, 22, 13, 14],
      ['2026-09-30', 20, 15, 15, 20, 15, 15],
    ]) },
  ],
});

function allocation(point, allowedCompanies, label, complete = false) {
  require(isRecord(point) && Array.isArray(point.holdings), `${label} requires holdings`);
  const validWeight = weight => typeof weight === 'number' && Number.isFinite(weight) && weight >= 0 && weight <= 100;
  require(validWeight(point.cashWeightPct), `${label} cash weight is invalid`);
  const weights = new Map();
  let total = point.cashWeightPct;
  for (const item of point.holdings) {
    require(isRecord(item) && allowedCompanies.has(item.companyId), `${label} has unknown company scope`);
    require(!weights.has(item.companyId), `${label} company must be unique`);
    require(validWeight(item.weightPct), `${label} company weight is invalid`);
    weights.set(item.companyId, item.weightPct);
    total += item.weightPct;
  }
  if (complete) require(weights.size === allowedCompanies.size, `${label} requires every company including explicit zero weights`);
  require(close(total, 100), `${label} company and cash weights must total 100%`);
  return weights;
}

export function validateAllocationHistoryFixture(fixture) {
  require(isRecord(fixture) && fixture.isSimulated === true, 'fixture must explicitly identify simulated data');
  identifier(fixture.id, 'fixture id');
  identifier(fixture.version, 'fixture version');
  for (const key of ['label', 'labelEn', 'disclosure', 'disclosureEn']) {
    require(typeof fixture[key] === 'string' && fixture[key].trim().length > 0, `fixture requires ${key}`);
  }
  require(fixture.sampling === 'explicit-snapshots', 'fixture sampling is unsupported');
  require(isRecord(fixture.scope), 'fixture requires explicit scope');
  identifier(fixture.scope.institutionId, 'fixture institutionId');
  const managerIds = identifiers(fixture.scope.managerIds, 'scope managerIds');
  const companyIds = identifiers(fixture.scope.companyIds, 'scope companyIds');
  require(!companyIds.has('cash'), 'cash is reserved and cannot be a company identifier');
  require(isRecord(fixture.coverage), 'fixture requires explicit coverage');
  date(fixture.coverage.start, 'coverage start');
  date(fixture.coverage.end, 'coverage end');
  require(fixture.coverage.start < fixture.coverage.end, 'coverage start must precede end');

  const reference = fixture.currentSnapshot;
  require(isRecord(reference) && reference.institutionId === fixture.scope.institutionId, 'current reference has conflicting institution scope');
  identifier(reference.id, 'current reference id');
  identifier(reference.version, 'current reference version');
  date(reference.asOf, 'current reference asOf');
  require(reference.asOf === fixture.coverage.end, 'current reference date must match coverage end');
  require(Array.isArray(reference.agents) && reference.agents.length === managerIds.size, 'current reference requires every Manager');
  const references = new Map();
  for (const agent of reference.agents) {
    require(isRecord(agent) && managerIds.has(agent.managerId), 'current reference has unknown Manager scope');
    require(!references.has(agent.managerId), 'current reference Manager must be unique');
    references.set(agent.managerId, { weights: allocation(agent, companyIds, 'current reference'), cashWeightPct: agent.cashWeightPct });
  }

  require(Array.isArray(fixture.histories) && fixture.histories.length === managerIds.size, 'histories require every Manager');
  const seen = new Set();
  for (const history of fixture.histories) {
    require(isRecord(history) && managerIds.has(history.managerId), 'history has unknown Manager scope');
    require(!seen.has(history.managerId), 'history Manager must be unique');
    seen.add(history.managerId);
    const companies = identifiers(history.companyIds, 'history companyIds');
    require([...companies].every(id => companyIds.has(id)), 'history has unknown company scope');
    require(Array.isArray(history.snapshots) && history.snapshots.length >= 2, 'history requires at least two snapshots');
    let previousDate = null, lastWeights;
    for (const point of history.snapshots) {
      require(isRecord(point), 'snapshot must be an object');
      date(point.date, 'snapshot date');
      require(point.date >= fixture.coverage.start && point.date <= fixture.coverage.end &&
        (previousDate === null || point.date > previousDate), 'snapshot dates must be unique and sorted within coverage');
      previousDate = point.date;
      lastWeights = allocation(point, companies, 'snapshot', true);
    }
    const last = history.snapshots.at(-1);
    require(history.snapshots[0].date === fixture.coverage.start && last.date === fixture.coverage.end,
      'history endpoints must match explicit coverage');
    const current = references.get(history.managerId);
    require(close(last.cashWeightPct, current.cashWeightPct), 'final cash weight must match the current reference');
    for (const [companyId, weight] of current.weights) {
      require(lastWeights.has(companyId) && close(lastWeights.get(companyId), weight), 'final company weights must match the current reference');
    }
    // Companies exited before the final reference can appear in the history,
    // but their last historical snapshot must explicitly say zero.
    for (const [companyId, weight] of lastWeights) {
      require(current.weights.has(companyId) || weight === 0, 'a historical company absent from the current reference must end at explicit zero');
    }
  }
  return fixture;
}

export function getAllocationHistory(scope, fixture = allocationHistoryFixtureV1) {
  require(isRecord(scope), 'query requires explicit institutionId, managerId, start and end');
  identifier(scope.institutionId, 'institutionId');
  identifier(scope.managerId, 'managerId');
  date(scope.start, 'start');
  date(scope.end, 'end');
  require(scope.start < scope.end, 'start must precede end');
  validateAllocationHistoryFixture(fixture);
  require(scope.institutionId === fixture.scope.institutionId, 'institution is unknown in the selected fixture');
  const history = fixture.histories.find(item => item.managerId === scope.managerId);
  require(history, 'Manager is unknown in the selected fixture');
  require(scope.start >= fixture.coverage.start && scope.end <= fixture.coverage.end, 'requested dates exceed explicit history coverage');
  const points = history.snapshots.filter(point => point.date >= scope.start && point.date <= scope.end);
  require(points[0]?.date === scope.start && points.at(-1)?.date === scope.end, 'requested endpoints have no explicit snapshot; interpolation is not supplied');
  const { id, version, isSimulated, label, labelEn, disclosure, disclosureEn } = fixture;
  return freeze({
    institutionId: scope.institutionId, managerId: scope.managerId, start: scope.start, end: scope.end,
    companyIds: [...history.companyIds], sampling: fixture.sampling,
    snapshots: points.map(point => ({ date: point.date, cashWeightPct: point.cashWeightPct,
      holdings: history.companyIds.map(companyId => ({ ...point.holdings.find(item => item.companyId === companyId) })),
    })),
    simulation: { id, version, isSimulated, label, labelEn, disclosure, disclosureEn },
  });
}
