// Read-only adapter for the workspace design sample. The catalog is an explicitly
// named fictional dataset; no route or lookup chooses an implicit business scope.
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';
import { institutionFixture } from './institution-data.mjs';
import { getDecision, portfolioDecisionFixture } from './portfolio-decisions.mjs';
import { getRisk, riskRegisterFixture } from './risk-register.mjs';

export const catalog = workspace;

const COMPANY_VIEWS = new Set(['overview', 'reports', 'materials', 'tracking', 'report']);
const MANAGER_VIEWS = new Set(['overview', 'companies', 'reports', 'holdings', 'activity', 'report', 'decisions', 'risks']);
const ROUTE_FIELDS = new Set(['institutionId', 'companyId', 'managerId', 'view', 'reportId', 'version', 'sectionId', 'decisionId', 'decisionTab', 'riskId', 'riskFilter']);
const INSTITUTION_QUERY_FIELDS = new Set(['view']);
const COMPANY_QUERY_FIELDS = new Set(['view', 'report', 'version', 'section']);
const MANAGER_QUERY_FIELDS = new Set([...COMPANY_QUERY_FIELDS, 'company', 'decision', 'tab', 'risk', 'status']);
const DECISION_TABS = new Set(['allocation', 'research', 'risk']);
const RISK_FILTERS = new Set(['all', 'needs_review', 'monitoring', 'resolved']);
const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function fail(message) { throw new Error(`Company sample: ${message}`); }
function identifier(value, label) {
  if (typeof value !== 'string' || !value || value.length > 160 ||
      /[\s\u0000-\u001f\u007f/?#]/u.test(value) || value === '.' || value === '..') {
    fail(`${label} must be an explicit non-empty identifier`);
  }
  return value;
}
function list(data, name) {
  if (!isRecord(data) || !Array.isArray(data[name])) fail(`dataset ${name} must be an array`);
  return data[name];
}
function exactlyOne(items, predicate, label) {
  const matches = items.filter(predicate);
  if (matches.length !== 1) fail(`${label} is ${matches.length ? 'ambiguous' : 'unknown'}`);
  return matches[0];
}
function companyFor(companyId, data) {
  identifier(companyId, 'companyId');
  return exactlyOne(list(data, 'companies'), item => item.id === companyId, `company ${companyId}`);
}
function managerFor(managerId, data) {
  identifier(managerId, 'managerId');
  return exactlyOne(list(data, 'managers'), item => item.id === managerId, `Manager ${managerId}`);
}
function newestFirst(items) {
  return [...items].sort((a, b) => String(b.date).localeCompare(String(a.date)));
}

// This validator is intentionally separate from research coverage: research is
// neither a holding nor a transaction, and never supplies missing portfolio data.
export function getInstitution(institutionId, data = workspace, fixture = institutionFixture) {
  identifier(institutionId, 'institutionId');
  if (!isRecord(fixture) || !isRecord(fixture.institution) || fixture.institution.id !== institutionId) {
    fail(`institution ${institutionId} is unknown in the selected fixture`);
  }
  const require = (condition, message) => { if (!condition) fail(`institution fixture ${message}`); };
  const text = value => typeof value === 'string' && value.trim().length > 0;
  const date = value => typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const close = (a, b) => Math.abs(a - b) < 0.000001;
  const validReturn = value => finite(value) && value > -100;
  require(text(fixture.institution.name) && text(fixture.institution.description), 'requires institution metadata');
  const simulation = fixture.simulation;
  require(isRecord(simulation) && simulation.isSimulated === true, 'must explicitly identify simulated data');
  identifier(simulation.id, 'simulation id');
  identifier(simulation.version, 'simulation version');
  require(date(simulation.asOf), 'requires a valid as-of date');
  require(/^[A-Z]{3}$/.test(simulation.currency || ''), 'requires an explicit currency');
  require(text(simulation.label) && text(simulation.disclosure) && text(simulation.benchmarkLabel), 'requires simulation and benchmark disclosures');
  require(Array.isArray(fixture.periods) && fixture.periods.length > 0, 'requires explicit periods');
  const periodIds = new Set();
  for (const period of fixture.periods) {
    require(isRecord(period), 'period must be an object');
    identifier(period.id, 'period id');
    require(!periodIds.has(period.id), 'period ids must be unique');
    periodIds.add(period.id);
    require(text(period.label) && date(period.start) && date(period.end) && period.start < period.end && period.end <= simulation.asOf, 'period dates and label are invalid');
    require(validReturn(period.returnPct) && validReturn(period.benchmarkReturnPct), 'period returns are invalid');
    require(Array.isArray(period.series) && period.series.length >= 2, 'period requires an index series');
    let previousDate = null;
    for (const point of period.series) {
      require(isRecord(point) && date(point.date) && point.date >= period.start && point.date <= period.end &&
        (previousDate === null || point.date > previousDate), 'series dates must be ordered within the period');
      require(finite(point.value) && point.value > 0 && finite(point.benchmarkValue) && point.benchmarkValue > 0, 'series index values must be positive');
      previousDate = point.date;
    }
    const first = period.series[0], last = period.series.at(-1);
    require(first.date === period.start && last.date === period.end, 'series endpoints must match the period');
    require(close(first.value, 100) && close(first.benchmarkValue, 100), 'institution and benchmark series must start at index 100');
    require(close((last.value / first.value - 1) * 100, period.returnPct) &&
      close((last.benchmarkValue / first.benchmarkValue - 1) * 100, period.benchmarkReturnPct), 'series and headline returns disagree');
  }
  require(periodIds.has(fixture.defaultPeriod), 'defaultPeriod must name a supplied period');

  function portfolio(value, owner) {
    require(isRecord(value) && finite(value.totalValue) && value.totalValue > 0 &&
      finite(value.cashValue) && value.cashValue >= 0 && value.cashValue <= value.totalValue &&
      finite(value.cashWeightPct) && value.cashWeightPct >= 0 && value.cashWeightPct <= 100 &&
      Array.isArray(value.holdings), `${owner} portfolio is invalid`);
    require(close(value.cashValue / value.totalValue * 100, value.cashWeightPct), `${owner} cash value and weight disagree`);
    let totalValue = value.cashValue, totalWeight = value.cashWeightPct;
    const companyIds = new Set();
    for (const holding of value.holdings) {
      require(isRecord(holding), `${owner} holding must be an object`);
      companyFor(holding.companyId, data);
      require(!companyIds.has(holding.companyId), `${owner} holding company must be unique`);
      companyIds.add(holding.companyId);
      require(finite(holding.marketValue) && holding.marketValue >= 0 && finite(holding.weightPct) &&
        holding.weightPct >= 0 && holding.weightPct <= 100, `${owner} holding values are invalid`);
      require(close(holding.marketValue / value.totalValue * 100, holding.weightPct), `${owner} holding value and weight disagree`);
      totalValue += holding.marketValue;
      totalWeight += holding.weightPct;
    }
    require(close(totalValue, value.totalValue) && close(totalWeight, 100), `${owner} holdings and cash must equal the full portfolio`);
  }
  portfolio(fixture.portfolio, 'institution');
  require(Array.isArray(fixture.agents), 'agents must be an array');
  const managerIds = new Set();
  for (const agent of fixture.agents) {
    require(isRecord(agent), 'agent must be an object');
    managerFor(agent.managerId, data);
    require(!managerIds.has(agent.managerId), 'agent Manager must be unique');
    managerIds.add(agent.managerId);
    portfolio(agent.portfolio, `agent ${agent.managerId}`);
    require(isRecord(agent.returns) && Object.keys(agent.returns).length === periodIds.size &&
      Object.keys(agent.returns).every(id => periodIds.has(id)) &&
      [...periodIds].every(id => validReturn(agent.returns[id])), 'agent returns must match the explicit periods');
    require(isRecord(agent.series) && Object.keys(agent.series).length === periodIds.size &&
      Object.keys(agent.series).every(id => periodIds.has(id)), 'agent series must match the explicit periods');
    for (const period of fixture.periods) {
      const series = agent.series[period.id];
      require(Array.isArray(series) && series.length === period.series.length,
        `agent ${agent.managerId} series must cover the benchmark dates for ${period.id}`);
      for (const [index, point] of series.entries()) {
        require(isRecord(point) && point.date === period.series[index].date && finite(point.value) && point.value > 0,
          `agent ${agent.managerId} series dates and values are invalid for ${period.id}`);
      }
      require(close(series[0].value, 100), `agent ${agent.managerId} series must start at index 100`);
      require(close((series.at(-1).value / series[0].value - 1) * 100, agent.returns[period.id]),
        `agent ${agent.managerId} series and headline returns disagree for ${period.id}`);
    }
    // A date shown in two display periods must represent the same underlying
    // authored path after rebasing; period switching cannot rewrite history.
    for (let left = 0; left < fixture.periods.length; left += 1) {
      for (let right = left + 1; right < fixture.periods.length; right += 1) {
        const leftSeries = agent.series[fixture.periods[left].id];
        const rightByDate = new Map(agent.series[fixture.periods[right].id].map(point => [point.date, point.value]));
        let scale;
        for (const point of leftSeries) {
          if (!rightByDate.has(point.date)) continue;
          const ratio = point.value / rightByDate.get(point.date);
          if (scale === undefined) scale = ratio;
          else require(close(ratio, scale), `agent ${agent.managerId} overlapping period paths disagree`);
        }
      }
    }
  }
  identifier(fixture.defaultAgentId, 'defaultAgentId');
  require(managerIds.has(fixture.defaultAgentId), 'defaultAgentId must name a supplied agent');
  return fixture;
}

export function getCompany(companyId, data = workspace) {
  const company = companyFor(companyId, data);
  const reports = list(data, 'reports').filter(item => item.companyId === companyId).map(document => {
    const context = getReport(companyId, document.id, document.currentVersion, data);
    return { document: context.document, manager: context.manager, report: context.report };
  });
  return {
    company, reports,
    events: newestFirst(list(data, 'events').filter(item => item.companyId === companyId)),
    evidence: list(data, 'evidence').filter(item => item.companyId === companyId),
    coverage: list(data, 'coverage').filter(item => item.companyId === companyId),
  };
}

export function getManager(managerId, data = workspace) {
  const manager = managerFor(managerId, data);
  const documents = list(data, 'reports').filter(item => item.managerId === managerId);
  const reportIds = new Set(documents.map(item => item.id));
  const reports = documents.map(document => {
    const context = getReport(document.companyId, document.id, document.currentVersion, data);
    return { company: context.company, document: context.document, manager: context.manager, report: context.report };
  });
  const coverage = list(data, 'coverage').filter(item => item.managerId === managerId)
    .map(item => ({ ...item, company: companyFor(item.companyId, data) }));
  const portfolios = data.portfolios === undefined ? [] : list(data, 'portfolios');
  const matchingPortfolios = portfolios.filter(item => item.managerId === managerId);
  if (matchingPortfolios.length > 1) fail(`portfolio for Manager ${managerId} is ambiguous`);
  const portfolio = matchingPortfolios[0] || {
    managerId, status: 'unavailable',
    reason: '尚未接入这位 Manager 的组合记录；研究覆盖不代表持仓，研究事件不代表交易。',
  };
  // Keep event identity intact, but only expose this author's precise report links
  // as the navigation targets. Neither an event nor research coverage is a trade.
  const events = newestFirst(list(data, 'events')).flatMap(event => {
    const links = (Array.isArray(event.affectedReports) ? event.affectedReports : [])
      .filter(link => reportIds.has(link.reportId));
    for (const link of links) {
      const context = getReport(event.companyId, link.reportId, link.version, data);
      if (context.manager.id !== managerId) fail(`event report ${link.reportId} belongs to a different Manager`);
      if (link.sectionId !== undefined) {
        identifier(link.sectionId, 'event sectionId');
        exactlyOne(context.report.sections, item => item.id === link.sectionId, `event section ${link.sectionId}`);
      }
    }
    return links.length ? [{ event, links }] : [];
  });
  return { manager, reports, coverage, portfolio, events };
}

export function getReport(companyId, reportId, version, data = workspace) {
  const company = companyFor(companyId, data);
  identifier(reportId, 'reportId');
  identifier(version, 'version');
  const document = exactlyOne(list(data, 'reports'), item => item.id === reportId, `report ${reportId}`);
  if (document.companyId !== companyId) fail(`report ${reportId} belongs to a different company`);
  const manager = managerFor(document.managerId, data);
  if (!Array.isArray(document.versions)) fail(`report ${reportId} has no version collection`);
  const report = exactlyOne(document.versions, item => item.version === version, `version ${reportId}/${version}`);
  if (!Array.isArray(report.sections)) fail(`version ${reportId}/${version} has no sections`);
  const events = newestFirst(list(data, 'events').filter(item => item.companyId === companyId &&
    Array.isArray(item.affectedReports) && item.affectedReports.some(link => link.reportId === reportId && link.version === version)));
  return { company, document, manager, report, events };
}

// Resolve a holding's research within its selected author and company. A main
// report is an explicit document kind; dates and catalog order never select it.
export function getManagerCompanyReport(managerId, companyId, data = catalog) {
  managerFor(managerId, data);
  companyFor(companyId, data);
  const candidates = list(data, 'reports')
    .filter(document => document.managerId === managerId && document.companyId === companyId)
    .map(document => {
      const context = getReport(companyId, document.id, document.currentVersion, data);
      if (context.manager.id !== managerId) fail(`report ${document.id} belongs to a different Manager`);
      return {
        kind: context.document.kind,
        route: { managerId, companyId, view: 'report', reportId: context.document.id, version: context.report.version },
      };
    });
  if (!candidates.length) return { status: 'missing' };
  const mainReports = candidates.filter(candidate => candidate.kind === 'main');
  const selected = mainReports.length === 1 ? mainReports[0] : candidates.length === 1 ? candidates[0] : null;
  return selected ? { status: 'available', route: selected.route } :
    { status: 'choice_required', routes: candidates.map(candidate => candidate.route) };
}

export function getMaterial(companyId, evidenceId, data = workspace) {
  companyFor(companyId, data);
  identifier(evidenceId, 'evidenceId');
  const evidence = exactlyOne(list(data, 'evidence'), item => item.id === evidenceId, `evidence ${evidenceId}`);
  if (evidence.companyId !== companyId) fail(`evidence ${evidenceId} belongs to a different company`);
  return evidence;
}

export function getEvidence(companyId, reportId, version, evidenceId, data = workspace) {
  const context = getReport(companyId, reportId, version, data);
  const evidence = getMaterial(companyId, evidenceId, data);
  const cited = context.report.sections.some(section => Array.isArray(section.citations) && section.citations.includes(evidenceId));
  if (!cited) fail(`evidence ${evidenceId} is not cited by version ${reportId}/${version}`);
  return { ...context, evidence };
}

function normalizeRoute(input, data, decisions = portfolioDecisionFixture, risks = riskRegisterFixture) {
  if (!isRecord(input)) fail('route must be an object');
  for (const key of Object.keys(input)) if (!ROUTE_FIELDS.has(key)) fail(`unknown route field ${key}`);
  if (Object.hasOwn(input, 'institutionId')) {
    getInstitution(input.institutionId, data);
    if (Object.keys(input).some(key => !['institutionId', 'view'].includes(key))) fail('institution routes cannot carry company, Manager or report fields');
    if (input.view !== 'overview') fail('institution route view is missing or unsupported');
    return { institutionId: input.institutionId, view: input.view };
  }
  const isManager = Object.hasOwn(input, 'managerId');
  if (isManager) managerFor(input.managerId, data);
  else companyFor(input.companyId, data);
  if (!(isManager ? MANAGER_VIEWS : COMPANY_VIEWS).has(input.view)) fail('route view is missing or unsupported');
  const route = isManager ? { managerId: input.managerId, view: input.view } : { companyId: input.companyId, view: input.view };
  if (route.view === 'risks') {
    if (['companyId', 'reportId', 'version', 'sectionId', 'decisionId', 'decisionTab'].some(key => Object.hasOwn(input, key))) {
      fail('risk routes cannot carry company, decision or report fields');
    }
    if (Object.hasOwn(input, 'riskFilter')) {
      if (!RISK_FILTERS.has(input.riskFilter)) fail('risk filter is missing or unsupported');
      route.riskFilter = input.riskFilter;
    }
    if (Object.hasOwn(input, 'riskId')) {
      const risk = getRisk(route.managerId, input.riskId, data, risks, decisions);
      if (route.riskFilter && route.riskFilter !== 'all' && risk.status !== route.riskFilter) fail('selected risk is outside the requested filter');
      route.riskId = input.riskId;
    }
    return route;
  }
  if (['riskId', 'riskFilter'].some(key => Object.hasOwn(input, key))) fail('risk identity and filter belong only to risks view');
  if (route.view === 'decisions') {
    if (['companyId', 'reportId', 'version', 'sectionId'].some(key => Object.hasOwn(input, key))) {
      fail('decision routes cannot carry company or report fields');
    }
    if (Object.hasOwn(input, 'decisionId')) {
      getDecision(route.managerId, input.decisionId, data, decisions);
      route.decisionId = input.decisionId;
    }
    if (Object.hasOwn(input, 'decisionTab')) {
      if (!Object.hasOwn(input, 'decisionId')) fail('decision tab requires an explicit decision');
      if (!DECISION_TABS.has(input.decisionTab)) fail('decision tab is missing or unsupported');
      route.decisionTab = input.decisionTab;
    }
    return route;
  }
  if (['decisionId', 'decisionTab'].some(key => Object.hasOwn(input, key))) {
    fail('decision identity and tab belong only to decisions view');
  }
  if (route.view !== 'report') {
    if (isManager && Object.hasOwn(input, 'companyId')) fail('companyId belongs only to a Manager report route');
    if (['reportId', 'version', 'sectionId'].some(key => Object.hasOwn(input, key))) {
      fail('report identity, version and section belong only to report view');
    }
    return route;
  }
  const context = getReport(input.companyId, input.reportId, input.version, data);
  if (isManager) {
    if (context.manager.id !== route.managerId) fail(`report ${input.reportId} belongs to a different Manager`);
    route.companyId = input.companyId;
  }
  route.reportId = input.reportId;
  route.version = input.version;
  if (input.sectionId !== undefined) {
    identifier(input.sectionId, 'sectionId');
    exactlyOne(context.report.sections, section => section.id === input.sectionId, `section ${input.sectionId}`);
    route.sectionId = input.sectionId;
  }
  return route;
}

export function formatRoute(input, data = workspace, decisions = portfolioDecisionFixture, risks = riskRegisterFixture) {
  const route = normalizeRoute(input, data, decisions, risks);
  const isManager = Object.hasOwn(route, 'managerId');
  const isInstitution = Object.hasOwn(route, 'institutionId');
  const query = new URLSearchParams({ view: route.view });
  if (route.view === 'report') {
    if (isManager) query.set('company', route.companyId);
    query.set('report', route.reportId);
    query.set('version', route.version);
    if (route.sectionId !== undefined) query.set('section', route.sectionId);
  }
  if (route.view === 'decisions') {
    if (route.decisionId !== undefined) query.set('decision', route.decisionId);
    if (route.decisionTab !== undefined) query.set('tab', route.decisionTab);
  }
  if (route.view === 'risks') {
    if (route.riskId !== undefined) query.set('risk', route.riskId);
    if (route.riskFilter !== undefined) query.set('status', route.riskFilter);
  }
  const hash = `#/${isInstitution ? 'institution' : isManager ? 'manager' : 'company'}/${encodeURIComponent(isInstitution ? route.institutionId : isManager ? route.managerId : route.companyId)}?${query}`;
  if (hash.length > 4096) fail('route hash is too long');
  return hash;
}

export function parseRoute(hash, data = workspace, decisions = portfolioDecisionFixture, risks = riskRegisterFixture) {
  if (typeof hash !== 'string' || !hash || hash.length > 4096 || /[\s\u0000-\u001f\u007f]/u.test(hash)) {
    fail('route hash must be explicit and valid');
  }
  try { decodeURIComponent(hash); } catch { fail('route contains invalid URL encoding'); }
  const match = /^#\/(company|manager|institution)\/([^/?#]+)\?([^?#]+)$/.exec(hash);
  if (!match) fail('route must use an explicit company, manager or institution identifier and view');
  const isManager = match[1] === 'manager';
  const isInstitution = match[1] === 'institution';
  const allowed = isInstitution ? INSTITUTION_QUERY_FIELDS : isManager ? MANAGER_QUERY_FIELDS : COMPANY_QUERY_FIELDS;
  const query = new URLSearchParams(match[3]);
  const seen = new Set();
  for (const [key] of query) {
    if (!allowed.has(key)) fail(`unknown route parameter ${key}`);
    if (seen.has(key)) fail(`duplicate route parameter ${key}`);
    seen.add(key);
  }
  const route = { [isInstitution ? 'institutionId' : isManager ? 'managerId' : 'companyId']: decodeURIComponent(match[2]), view: query.get('view') };
  if (query.has('company')) route.companyId = query.get('company');
  for (const [parameter, field] of [['report', 'reportId'], ['version', 'version'], ['section', 'sectionId'], ['decision', 'decisionId'], ['tab', 'decisionTab'], ['risk', 'riskId'], ['status', 'riskFilter']]) {
    if (query.has(parameter)) route[field] = query.get(parameter);
  }
  return normalizeRoute(route, data, decisions, risks);
}

export function routeContext(input, data = workspace, decisions = portfolioDecisionFixture, risks = riskRegisterFixture) {
  const route = normalizeRoute(input, data, decisions, risks);
  if (Object.hasOwn(route, 'institutionId')) return { entityType: 'institution', entity: getInstitution(route.institutionId, data).institution };
  return Object.hasOwn(route, 'managerId')
    ? { entityType: 'manager', entity: managerFor(route.managerId, data) }
    : { entityType: 'company', entity: companyFor(route.companyId, data) };
}
