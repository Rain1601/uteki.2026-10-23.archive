import test from 'node:test';
import assert from 'node:assert/strict';
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';
import { catalog, getCompany, getManager, getReport, getManagerCompanyReport, getEvidence, getMaterial, formatRoute, parseRoute, routeContext } from './model.mjs';

function synthetic() {
  return {
    companies: [{ id: 'cedar' }, { id: 'pine' }, { id: 'birch' }],
    managers: [{ id: 'scout' }, { id: 'patient' }],
    coverage: [{ companyId: 'cedar', managerId: 'scout' }, { companyId: 'pine', managerId: 'patient' }],
    reports: [
      { id: 'cedar-main', companyId: 'cedar', managerId: 'scout', kind: 'main', currentVersion: 'v3', versions: [
        { version: 'v1', sections: [{ id: 'old', citations: ['cedar-old'] }] },
        { version: 'v3', sections: [{ id: '结论', citations: ['cedar-gap'] }] },
      ] },
      { id: 'cedar-topic', companyId: 'cedar', managerId: 'scout', kind: 'topic', currentVersion: 'v7', versions: [
        { version: 'v7', sections: [{ id: 'topic', citations: ['cedar-old'] }] },
      ] },
      { id: 'pine-main', companyId: 'pine', managerId: 'patient', kind: 'main', currentVersion: 'v2', versions: [
        { version: 'v2', sections: [{ id: 'summary', citations: ['pine-source'] }] },
      ] },
    ],
    evidence: [
      { id: 'cedar-old', companyId: 'cedar', availability: 'available', quote: 'Synthetic source text.' },
      { id: 'cedar-gap', companyId: 'cedar', availability: 'unavailable', quote: '', context: [] },
      { id: 'cedar-unused', companyId: 'cedar', availability: 'excerpt', quote: 'Synthetic uncited material.' },
      { id: 'pine-source', companyId: 'pine', availability: 'available', quote: 'Independent company source.' },
    ],
    events: [
      { id: 'cedar-old-event', companyId: 'cedar', date: '2026-01-01', affectedReports: [{ reportId: 'cedar-main', version: 'v1' }] },
      { id: 'pine-event', companyId: 'pine', date: '2026-01-09', affectedReports: [{ reportId: 'pine-main', version: 'v2' }] },
      { id: 'cedar-current', companyId: 'cedar', date: '2026-01-03', affectedReports: [{ reportId: 'cedar-main', version: 'v3' }] },
      { id: 'cedar-topic-event', companyId: 'cedar', date: '2026-01-02', affectedReports: [{ reportId: 'cedar-topic', version: 'v7' }] },
    ],
  };
}

test('catalog preserves the existing named demo dataset and all six companies', () => {
  assert.equal(catalog, workspace);
  assert.equal(catalog.companies.length, 6);
  const before = JSON.stringify(catalog);
  for (const { id } of catalog.companies) {
    const context = getCompany(id);
    assert.equal(context.company.id, id);
    assert.ok(context.reports.every(item => item.document.companyId === id));
    assert.ok(context.evidence.every(item => item.companyId === id));
    assert.ok(context.events.every(item => item.companyId === id));
    assert.ok(context.coverage.every(item => item.companyId === id));
  }
  assert.equal(JSON.stringify(catalog), before, 'adapter must not mutate the selected dataset');
});

test('company context retains independent main/topic identities and current version pointers', () => {
  const data = synthetic();
  const context = getCompany('cedar', data);
  assert.deepEqual(context.reports.map(({ document, report }) => [document.id, document.kind, report.version]), [
    ['cedar-main', 'main', 'v3'], ['cedar-topic', 'topic', 'v7'],
  ]);
  assert.deepEqual(context.events.map(item => item.id), ['cedar-current', 'cedar-topic-event', 'cedar-old-event']);
  assert.equal(context.coverage[0].managerId, 'scout');
  assert.equal(getCompany('pine', data).reports[0].manager.id, 'patient');
  assert.deepEqual(getCompany('birch', data), { company: data.companies[2], reports: [], events: [], evidence: [], coverage: [] });
});

test('missing, blank and unknown company scopes never fall back to the first company', () => {
  for (const scope of [undefined, null, '', ' ', 'unknown']) assert.throws(() => getCompany(scope));
  assert.throws(() => getCompany('alphabet', synthetic()), /unknown/);
});

test('report lookup preserves the requested historical version and exact event association', () => {
  const data = synthetic();
  const old = getReport('cedar', 'cedar-main', 'v1', data);
  assert.equal(old.report, data.reports[0].versions[0]);
  assert.deepEqual(old.events.map(item => item.id), ['cedar-old-event']);
  assert.deepEqual(getReport('cedar', 'cedar-main', 'v3', data).events.map(item => item.id), ['cedar-current']);
  assert.deepEqual(getReport('cedar', 'cedar-topic', 'v7', data).events.map(item => item.id), ['cedar-topic-event']);
  assert.deepEqual(getReport('pine', 'pine-main', 'v2', data).events.map(item => item.id), ['pine-event']);
});

test('report lookup rejects missing ownership, version and cross-company scope', () => {
  const data = synthetic();
  for (const args of [
    [undefined, 'cedar-main', 'v1'], ['cedar', undefined, 'v1'], ['cedar', 'cedar-main', undefined],
    ['cedar', 'unknown', 'v1'], ['cedar', 'cedar-main', 'v2'], ['cedar', 'pine-main', 'v2'],
    ['cedar', 'cedar-topic', 'v3'],
  ]) assert.throws(() => getReport(...args, data));
  data.managers = [];
  assert.throws(() => getReport('cedar', 'cedar-main', 'v1', data), /Manager.*unknown/);
});

test('holding report resolution prefers the unique authored main and its explicit current pointer over order or recency', () => {
  const data = synthetic();
  data.reports[0].versions.push({ version: 'v99', publishedAt: '2099-01-01', sections: [] });
  data.reports.push({ id: 'cedar-patient-main', companyId: 'cedar', managerId: 'patient', kind: 'main', currentVersion: 'v4', versions: [{ version: 'v4', sections: [] }] });
  data.reports.reverse();
  const before = JSON.stringify(data);
  assert.deepEqual(getManagerCompanyReport('scout', 'cedar', data), {
    status: 'available', route: { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v3' },
  });
  assert.deepEqual(getManagerCompanyReport('patient', 'cedar', data), {
    status: 'available', route: { managerId: 'patient', companyId: 'cedar', view: 'report', reportId: 'cedar-patient-main', version: 'v4' },
  });
  assert.deepEqual(getManagerCompanyReport('patient', 'pine', data), {
    status: 'available', route: { managerId: 'patient', companyId: 'pine', view: 'report', reportId: 'pine-main', version: 'v2' },
  });
  assert.equal(JSON.stringify(data), before, 'navigation resolution does not change report versions or research state');
});

test('one authored topic can open when that company and Manager have no main report', () => {
  const data = synthetic();
  data.reports = data.reports.filter(document => document.id !== 'cedar-main');
  const result = getManagerCompanyReport('scout', 'cedar', data);
  assert.deepEqual(result, {
    status: 'available', route: { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-topic', version: 'v7' },
  });
  assert.deepEqual(parseRoute(formatRoute(result.route, data), data), result.route);
});

test('multiple topics or multiple mains require an explicit choice among scoped reports', () => {
  for (const kind of ['topic', 'main']) {
    const data = synthetic();
    data.reports.filter(document => document.companyId === 'cedar').forEach(document => { document.kind = kind; });
    data.reports.push({ id: 'other-author-main', companyId: 'cedar', managerId: 'patient', kind: 'main', currentVersion: 'v9', versions: [{ version: 'v9', sections: [] }] });
    const expected = [
      { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v3' },
      { managerId: 'scout', companyId: 'cedar', view: 'report', reportId: 'cedar-topic', version: 'v7' },
    ];
    const result = getManagerCompanyReport('scout', 'cedar', data);
    assert.deepEqual(result, { status: 'choice_required', routes: expected });
    assert.equal(result.route, undefined, 'ambiguity never chooses one route implicitly');
    for (const route of result.routes) assert.deepEqual(parseRoute(formatRoute(route, data), data), route);
    data.reports.reverse();
    const reversed = getManagerCompanyReport('scout', 'cedar', data);
    assert.equal(reversed.status, 'choice_required', 'catalog order cannot resolve ambiguity');
    assert.deepEqual(new Set(reversed.routes.map(route => route.reportId)), new Set(expected.map(route => route.reportId)));
  }
});

test('valid scopes without authored company research return a gap without borrowing coverage or another author', () => {
  const data = synthetic();
  data.coverage.push({ companyId: 'cedar', managerId: 'patient', status: 'researching' });
  for (const [managerId, companyId] of [['patient', 'cedar'], ['scout', 'pine'], ['scout', 'birch']]) {
    assert.deepEqual(getManagerCompanyReport(managerId, companyId, data), { status: 'missing' });
  }
});

test('holding report resolution rejects invalid company or Manager scope even when there are no reports', () => {
  const data = synthetic();
  data.reports = [];
  for (const value of [undefined, null, '', ' ', 'unknown']) {
    assert.throws(() => getManagerCompanyReport(value, 'cedar', data));
    assert.throws(() => getManagerCompanyReport('scout', value, data));
  }
  data.managers.push({ id: 'scout' });
  assert.throws(() => getManagerCompanyReport('scout', 'cedar', data), /ambiguous/);
  data.managers.pop();
  data.companies.push({ id: 'cedar' });
  assert.throws(() => getManagerCompanyReport('scout', 'cedar', data), /ambiguous/);
});

test('malformed current pointers and duplicate identities are errors, not gaps or latest-version fallbacks', () => {
  for (const version of [undefined, '', 'v404']) {
    const data = synthetic();
    data.reports[0].currentVersion = version;
    assert.throws(() => getManagerCompanyReport('scout', 'cedar', data));
  }
  const data = synthetic();
  data.reports.push({ ...data.reports[0] });
  assert.throws(() => getManagerCompanyReport('scout', 'cedar', data), /ambiguous/);
  data.reports.pop();
  data.reports[0].versions.push({ ...data.reports[0].versions[1] });
  assert.throws(() => getManagerCompanyReport('scout', 'cedar', data), /ambiguous/);
});

test('the six-company fixture resolves only its three authored main report relationships', () => {
  const expected = new Map([
    ['north/alphabet', ['alpha-north-main', 'v2']],
    ['north/microsoft', ['ms-north-main', 'v1']],
    ['field/alphabet', ['alpha-field-main', 'v2']],
  ]);
  for (const manager of catalog.managers) for (const company of catalog.companies) {
    const result = getManagerCompanyReport(manager.id, company.id), pair = expected.get(`${manager.id}/${company.id}`);
    if (!pair) assert.deepEqual(result, { status: 'missing' });
    else {
      assert.deepEqual(result, { status: 'available', route: { managerId: manager.id, companyId: company.id, view: 'report', reportId: pair[0], version: pair[1] } });
      assert.deepEqual(parseRoute(formatRoute(result.route)), result.route);
    }
  }
});

test('ambiguous company, report and version records are explicit conflicts', () => {
  const data = synthetic();
  data.companies.push({ id: 'cedar' });
  assert.throws(() => getCompany('cedar', data), /ambiguous/);
  data.companies.pop();
  data.reports.push({ ...data.reports[0] });
  assert.throws(() => getReport('cedar', 'cedar-main', 'v3', data), /ambiguous/);
  data.reports.pop();
  data.reports[0].versions.push({ ...data.reports[0].versions[1] });
  assert.throws(() => getReport('cedar', 'cedar-main', 'v3', data), /ambiguous/);
});

test('evidence must be cited by the selected report version and owned by its company', () => {
  const data = synthetic();
  assert.equal(getEvidence('cedar', 'cedar-main', 'v1', 'cedar-old', data).evidence, data.evidence[0]);
  assert.throws(() => getEvidence('cedar', 'cedar-main', 'v3', 'cedar-old', data), /not cited/);
  assert.throws(() => getEvidence('cedar', 'cedar-main', 'v3', 'cedar-unused', data), /not cited/);
  assert.throws(() => getEvidence('cedar', 'cedar-main', 'v3', 'pine-source', data), /different company/);
  // Even an incorrectly cross-linked citation cannot establish company coverage.
  data.reports[0].versions[1].sections[0].citations.push('pine-source');
  assert.throws(() => getEvidence('cedar', 'cedar-main', 'v3', 'pine-source', data), /different company/);
  assert.throws(() => getEvidence('pine', 'pine-main', 'v2', 'cedar-gap', data), /different company/);
});

test('unavailable evidence remains unavailable and no excerpt is synthesized', () => {
  const data = synthetic();
  const { evidence } = getEvidence('cedar', 'cedar-main', 'v3', 'cedar-gap', data);
  assert.equal(evidence.availability, 'unavailable');
  assert.equal(evidence.quote, '');
  assert.deepEqual(evidence.context, []);
});

test('material lookup does not invent a report context or require a citation', () => {
  const data = synthetic();
  assert.equal(getMaterial('cedar', 'cedar-unused', data), data.evidence[2]);
  assert.equal(getMaterial('cedar', 'cedar-unused', data).report, undefined);
  assert.throws(() => getMaterial('cedar', 'pine-source', data), /different company/);
  assert.throws(() => getMaterial('cedar', '', data));
  assert.throws(() => getMaterial('', 'cedar-unused', data));
  assert.throws(() => getMaterial('cedar', 'unknown', data));
});

test('routes round-trip all company views for every current demo company', () => {
  for (const { id } of catalog.companies) {
    for (const view of ['overview', 'reports', 'materials', 'tracking']) {
      const route = { companyId: id, view };
      assert.deepEqual(parseRoute(formatRoute(route)), route);
    }
  }
});

test('routes round-trip every existing report, version and section without switching identity', () => {
  for (const document of catalog.reports) {
    for (const report of document.versions) {
      for (const section of report.sections) {
        const route = { companyId: document.companyId, view: 'report', reportId: document.id, version: report.version, sectionId: section.id };
        assert.deepEqual(parseRoute(formatRoute(route)), route);
      }
    }
  }
});

test('independent synthetic routes include encoded section names and retain historical versions', () => {
  const data = synthetic();
  for (const route of [
    { companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v1' },
    { companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v3', sectionId: '结论' },
    { companyId: 'cedar', view: 'report', reportId: 'cedar-topic', version: 'v7', sectionId: 'topic' },
    { companyId: 'pine', view: 'report', reportId: 'pine-main', version: 'v2' },
  ]) assert.deepEqual(parseRoute(formatRoute(route, data), data), route);
});

test('empty and malformed routes reject instead of choosing a launch company or view', () => {
  for (const hash of [undefined, null, '', '#', '#/company/alphabet', '#/company/?view=overview',
    '#/company/alphabet?view=', '#/company/alphabet?version=v2', '#/company/unknown?view=overview',
    '#/company/alphabet?view=other', '#/company/alphabet?view=overview&view=reports',
    '#/company/alphabet?view=overview&unknown=x', '#/company/%ZZ?view=overview',
    '#/company/alphabet?view=over%ZZview', '#/company/alphabet?view=overview#extra',
    '#/company/alphabet?view=overview?view=reports', '#/company/alphabet ?view=overview',
  ]) assert.throws(() => parseRoute(hash), `must reject ${String(hash)}`);
});

test('non-report routes reject report-only fields in object and hash forms', () => {
  for (const field of ['reportId', 'version', 'sectionId']) {
    assert.throws(() => formatRoute({ companyId: 'alphabet', view: 'overview', [field]: 'v1' }));
    assert.throws(() => formatRoute({ companyId: 'alphabet', view: 'overview', [field]: undefined }));
  }
  for (const parameter of ['report=alpha-north-main', 'version=v2', 'section=summary']) {
    assert.throws(() => parseRoute(`#/company/alphabet?view=reports&${parameter}`));
  }
});

test('report routes reject missing version, wrong company, unrelated version and absent section', () => {
  const data = synthetic();
  for (const route of [
    { companyId: 'cedar', view: 'report' },
    { companyId: 'cedar', view: 'report', reportId: 'cedar-main' },
    { companyId: 'cedar', view: 'report', reportId: 'pine-main', version: 'v2' },
    { companyId: 'cedar', view: 'report', reportId: 'cedar-topic', version: 'v3' },
    { companyId: 'cedar', view: 'report', reportId: 'cedar-main', version: 'v3', sectionId: 'old' },
    { companyId: 'cedar', view: 'overview', managerId: 'scout' },
  ]) assert.throws(() => formatRoute(route, data));
  assert.throws(() => parseRoute('#/company/cedar?view=report&report=cedar-main', data));
  assert.throws(() => parseRoute('#/company/cedar?view=report&report=cedar-main&version=v3&section=old', data));
});

test('Manager contexts preserve their own reports, companies and explicit portfolio gaps', () => {
  const before = JSON.stringify(catalog);
  for (const manager of catalog.managers) {
    const context = getManager(manager.id);
    assert.equal(context.manager, manager);
    assert.equal(context.portfolio, catalog.portfolios.find(item => item.managerId === manager.id));
    assert.equal(context.portfolio.status, 'unavailable');
    assert.ok(context.reports.every(item => item.manager.id === manager.id && item.document.managerId === manager.id));
    assert.ok(context.reports.every(item => item.company.id === item.document.companyId && item.report.version === item.document.currentVersion));
    assert.ok(context.coverage.every(item => item.managerId === manager.id && item.company.id === item.companyId));
    assert.equal(context.holdings, undefined);
    assert.equal(context.transactions, undefined);
    for (const {event, links} of context.events) {
      assert.ok(links.length > 0);
      for (const link of links) {
        assert.ok(event.affectedReports.includes(link));
        assert.equal(getReport(event.companyId, link.reportId, link.version).manager.id, manager.id);
      }
    }
  }
  assert.equal(JSON.stringify(catalog), before);
});

test('independent Manager coverage does not become holdings and missing portfolios are explicit', () => {
  const data = synthetic();
  data.coverage.push({ companyId: 'birch', managerId: 'scout', status: 'researching' });
  const scout = getManager('scout', data);
  assert.deepEqual(scout.reports.map(item => [item.company.id, item.document.id, item.report.version]), [
    ['cedar', 'cedar-main', 'v3'], ['cedar', 'cedar-topic', 'v7'],
  ]);
  assert.deepEqual(scout.coverage.map(item => item.company.id), ['cedar', 'birch']);
  assert.equal(scout.coverage[1].status, 'researching');
  assert.deepEqual(Object.keys(scout.portfolio).sort(), ['managerId', 'reason', 'status']);
  assert.equal(scout.portfolio.status, 'unavailable');
  assert.equal(scout.portfolio.managerId, 'scout');
  assert.equal(scout.portfolio.holdings, undefined);
  assert.equal(scout.portfolio.returns, undefined);
  assert.equal(scout.portfolio.transactions, undefined);
  assert.deepEqual(getManager('patient', data).reports.map(item => item.company.id), ['pine']);
  // An explicitly supplied record is preserved, not inferred from research scope.
  const portfolio = { managerId: 'patient', status: 'unavailable', reason: 'Independent synthetic gap.' };
  data.portfolios = [portfolio];
  assert.equal(getManager('patient', data).portfolio, portfolio);
  assert.equal(getManager('scout', data).portfolio.status, 'unavailable');
});

test('Manager events retain precise author/version links across a shared company event', () => {
  const data = synthetic();
  data.reports.push({ id: 'cedar-patient', companyId: 'cedar', managerId: 'patient', currentVersion: 'v8', versions: [
    { version: 'v8', sections: [{ id: 'patient-section', citations: [] }] },
  ] });
  data.coverage.push({ companyId: 'cedar', managerId: 'patient' });
  const shared = { id: 'shared', companyId: 'cedar', date: '2026-01-10', affectedReports: [
    { reportId: 'cedar-main', version: 'v1', sectionId: 'old' },
    { reportId: 'cedar-patient', version: 'v8', sectionId: 'patient-section' },
  ] };
  data.events.push(shared);
  const scout = getManager('scout', data).events;
  assert.equal(scout[0].event, shared);
  assert.deepEqual(scout[0].links, [shared.affectedReports[0]]);
  assert.equal(scout[0].links[0].version, 'v1', 'historical event must not silently use v3');
  assert.deepEqual(getManager('patient', data).events[0].links, [shared.affectedReports[1]]);
  assert.ok(scout.every(({event}) => event.companyId === 'cedar'));
  assert.equal(scout[0].trade, undefined);
  assert.equal(scout[0].transaction, undefined);
});

test('Manager lookup rejects missing, unknown, ambiguous and inconsistent business scope', () => {
  const data = synthetic();
  for (const managerId of [undefined, '', ' ', 'unknown', 'north']) assert.throws(() => getManager(managerId, data));
  data.managers.push({ id: 'scout' });
  assert.throws(() => getManager('scout', data), /ambiguous/);
  data.managers.pop();
  data.portfolios = [{managerId:'scout'}, {managerId:'scout'}];
  assert.throws(() => getManager('scout', data), /ambiguous/);
  data.portfolios = [];
  data.events[0].companyId = 'pine';
  assert.throws(() => getManager('scout', data), /different company/);
  data.events[0].companyId = 'cedar';
  data.events[0].affectedReports[0].version = 'v9';
  assert.throws(() => getManager('scout', data), /unknown/);
  data.events[0].affectedReports[0].version = 'v1';
  data.events[0].affectedReports[0].sectionId = 'missing';
  assert.throws(() => getManager('scout', data), /unknown/);
});

test('Manager routes round-trip every entity view and retain the Manager as route context', () => {
  for (const manager of catalog.managers) {
    for (const view of ['overview', 'companies', 'reports', 'holdings', 'activity']) {
      const route = {managerId:manager.id, view};
      assert.deepEqual(parseRoute(formatRoute(route)), route);
      assert.deepEqual(routeContext(route), {entityType:'manager', entity:manager});
    }
  }
  const data = synthetic();
  assert.deepEqual(routeContext({companyId:'cedar',view:'overview'}, data), {entityType:'company',entity:data.companies[0]});
  assert.deepEqual(routeContext({managerId:'patient',view:'holdings'}, data), {entityType:'manager',entity:data.managers[1]});
});

test('Manager report routes require explicit company and preserve author, report, version and section', () => {
  for (const document of catalog.reports) {
    for (const report of document.versions) {
      const route = {managerId:document.managerId, companyId:document.companyId, view:'report', reportId:document.id, version:report.version, sectionId:report.sections[0].id};
      const hash = formatRoute(route);
      assert.match(hash, new RegExp(`^#/manager/${document.managerId}\\?`));
      assert.ok(hash.includes(`company=${document.companyId}`));
      assert.deepEqual(parseRoute(hash), route);
      assert.equal(routeContext(route).entity.id, document.managerId);
      assert.equal(routeContext(route).entityType, 'manager');
    }
  }
  const data = synthetic();
  const old = {managerId:'scout',companyId:'cedar',view:'report',reportId:'cedar-main',version:'v1',sectionId:'old'};
  assert.deepEqual(parseRoute(formatRoute(old, data), data), old);
  assert.equal(routeContext(old, data).entity, data.managers[0]);
});

test('Manager routes reject foreign authors, missing scope and company fields on ordinary views', () => {
  const data = synthetic();
  const valid = {managerId:'scout',companyId:'cedar',view:'report',reportId:'cedar-main',version:'v3'};
  for (const route of [
    {...valid, managerId:'patient'}, {...valid, companyId:'pine'}, {...valid, version:'v8'},
    {...valid, companyId:undefined}, {...valid, version:undefined}, {...valid, managerId:undefined},
    {...valid, sectionId:'old'}, {managerId:'scout',view:'overview',companyId:'cedar'},
    {managerId:'scout',view:'companies',companyId:undefined}, {managerId:'scout',view:'materials'},
    {managerId:'scout',view:'holdings',reportId:'cedar-main'},
    {companyId:'cedar',view:'activity'}, {companyId:'cedar',view:'companies'},
  ]) {
    assert.throws(() => formatRoute(route, data));
    assert.throws(() => routeContext(route, data));
  }
  for (const hash of [
    '#/manager/scout?view=report&report=cedar-main&version=v3',
    '#/manager/patient?view=report&company=cedar&report=cedar-main&version=v3',
    '#/manager/scout?view=report&company=cedar&report=cedar-main',
    '#/manager/scout?view=overview&company=cedar',
    '#/manager/scout?view=overview&manager=patient',
    '#/manager/scout?view=holdings&view=reports',
    '#/manager/scout?view=report&company=cedar&company=pine&report=cedar-main&version=v3',
    '#/company/cedar?view=report&manager=scout&report=cedar-main&version=v3',
    '#/company/cedar?view=overview&company=pine',
    '#/manager/unknown?view=overview', '#/manager/?view=overview', '#/unknown/scout?view=overview',
  ]) assert.throws(() => parseRoute(hash, data), `must reject ${hash}`);
});
