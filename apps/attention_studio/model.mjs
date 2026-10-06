const FILTERS = new Set(['all', 'unread', 'challenge', 'saved']);

function fail(message) {
  throw new Error(`Invalid attention demo: ${message}`);
}

function list(value, label) {
  if (!Array.isArray(value)) fail(`${label} must be an array`);
  return value;
}

function indexById(items, label) {
  const result = new Map();
  for (const item of list(items, label)) {
    if (!item || typeof item.id !== 'string' || !item.id.trim()) fail(`${label} requires a nonblank id`);
    if (result.has(item.id)) fail(`duplicate ${label} id: ${item.id}`);
    result.set(item.id, item);
  }
  return result;
}

function requireRef(index, id, label) {
  if (typeof id !== 'string' || !index.has(id)) fail(`${label} references unknown id: ${String(id)}`);
  return index.get(id);
}

function indexes(demo) {
  if (!demo || typeof demo !== 'object') fail('demo must be an object');
  return {
    companies: indexById(demo.companies, 'company'),
    reports: indexById(demo.reports, 'report'),
    changes: indexById(demo.changes, 'change'),
    tasks: indexById(demo.tasks, 'task'),
    managers: indexById(demo.managers, 'manager'),
  };
}

function researchContext(index, item, label) {
  const company = requireRef(index.companies, item.companyId, `${label}.companyId`);
  const report = requireRef(index.reports, item.reportId, `${label}.reportId`);
  if (report.companyId !== company.id) fail(`${label} references a report from another company`);
  const factor = requireRef(indexById(report.factors, `report ${report.id} factor`), item.factorId, `${label}.factorId`);
  checkInheritedScope(factor, { companyId: company.id, reportId: report.id }, `factor ${factor.id}`);
  return { company, report, factor };
}

// Embedded factors/evidence inherit their parent's scope. If they explicitly
// declare a scope, it must agree with that parent rather than overriding it.
function checkInheritedScope(item, scope, label) {
  for (const [key, expected] of Object.entries(scope)) {
    if (Object.hasOwn(item, key) && item[key] !== expected) fail(`${label}.${key} conflicts with its parent`);
  }
}

function linkedTasks(index, change) {
  const ids = list(change.taskIds, `change ${change.id}.taskIds`);
  if (new Set(ids).size !== ids.length) fail(`change ${change.id} contains duplicate task references`);
  return ids.map((id) => {
    const task = requireRef(index.tasks, id, `change ${change.id}.taskIds`);
    researchContext(index, task, `task ${task.id}`);
    if (task.companyId !== change.companyId || task.reportId !== change.reportId) {
      fail(`change ${change.id} references a task from another company or report`);
    }
    return task;
  });
}

function checkCompany(demo, companyId) {
  if (companyId !== null) requireRef(indexById(demo.companies, 'company'), companyId, 'company filter');
}

function percentage(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) {
    fail(`${label} must be an explicit percentage between 0 and 100`);
  }
}

export function validateDemo(demo) {
  const index = indexes(demo);
  const reportCounts = new Map([...index.companies.keys()].map((id) => [id, 0]));
  const factors = [];
  const evidence = [];
  const actions = [];

  for (const report of index.reports.values()) {
    requireRef(index.companies, report.companyId, `report ${report.id}.companyId`);
    reportCounts.set(report.companyId, reportCounts.get(report.companyId) + 1);
    for (const factor of list(report.factors, `report ${report.id}.factors`)) {
      checkInheritedScope(factor, { companyId: report.companyId, reportId: report.id }, `factor ${factor.id}`);
      factors.push(factor);
    }
  }
  for (const [companyId, count] of reportCounts) {
    if (count !== 1) fail(`company ${companyId} must have exactly one main report; found ${count}`);
  }
  indexById(factors, 'factor');

  for (const task of index.tasks.values()) researchContext(index, task, `task ${task.id}`);

  for (const change of index.changes.values()) {
    researchContext(index, change, `change ${change.id}`);
    if (!['challenge', 'support', 'watch'].includes(change.kind)) fail(`change ${change.id} has unknown kind`);
    if (typeof change.rank !== 'number' || !Number.isFinite(change.rank)) fail(`change ${change.id} requires a finite rank`);
    linkedTasks(index, change);
    for (const item of list(change.evidence, `change ${change.id}.evidence`)) {
      checkInheritedScope(item, {
        companyId: change.companyId, reportId: change.reportId, factorId: change.factorId,
      }, `evidence ${item.id}`);
      evidence.push(item);
    }
  }
  indexById(evidence, 'evidence');

  for (const manager of index.managers.values()) {
    percentage(manager.cashPct, `manager ${manager.id}.cashPct`);
    let total = manager.cashPct;
    const held = new Set();
    for (const position of list(manager.positions, `manager ${manager.id}.positions`)) {
      requireRef(index.companies, position.companyId, `manager ${manager.id} position.companyId`);
      if (held.has(position.companyId)) fail(`manager ${manager.id} contains duplicate company positions`);
      held.add(position.companyId);
      percentage(position.weightPct, `manager ${manager.id} position.weightPct`);
      total += position.weightPct;
    }
    if (Math.abs(total - 100) > 0.000001) fail(`manager ${manager.id} weights plus cash must total 100; found ${total}`);
    for (const action of list(manager.actions, `manager ${manager.id}.actions`)) {
      requireRef(index.companies, action.companyId, `action ${action.id}.companyId`);
      actions.push(action);
    }
  }
  indexById(actions, 'action');
  return true;
}

export function selectChanges(demo, { companyId = null, filter = 'all', readIds = [], savedIds = [] } = {}) {
  checkCompany(demo, companyId);
  if (!FILTERS.has(filter)) fail(`unknown change filter: ${filter}`);
  const read = new Set(readIds);
  const saved = new Set(savedIds);
  return demo.changes.filter((change) => {
    if (companyId !== null && change.companyId !== companyId) return false;
    if (filter === 'unread') return !read.has(change.id);
    if (filter === 'challenge') return change.kind === 'challenge';
    if (filter === 'saved') return saved.has(change.id);
    return true;
  }).sort((left, right) => left.rank - right.rank);
}

export function unreadCount(demo, readIds = [], companyId = null) {
  checkCompany(demo, companyId);
  const read = new Set(readIds);
  return new Set(demo.changes
    .filter((change) => (companyId === null || change.companyId === companyId) && !read.has(change.id))
    .map((change) => change.id)).size;
}

export function selectTasks(demo, companyId = null) {
  checkCompany(demo, companyId);
  return demo.tasks.filter((task) => companyId === null || task.companyId === companyId);
}

export function changeContext(demo, changeId) {
  const index = indexes(demo);
  const change = requireRef(index.changes, changeId, 'change context');
  const { company, report, factor } = researchContext(index, change, `change ${change.id}`);
  for (const item of list(change.evidence, `change ${change.id}.evidence`)) {
    checkInheritedScope(item, { companyId: company.id, reportId: report.id, factorId: factor.id }, `evidence ${item.id}`);
  }
  return { change, company, report, factor, tasks: linkedTasks(index, change) };
}
