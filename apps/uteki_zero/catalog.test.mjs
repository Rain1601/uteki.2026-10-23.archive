import test from 'node:test';
import assert from 'node:assert/strict';
import { research } from './research.mjs';
import { workspace, findDocument, findVersion, findCoverage, findEvidence, validateWorkspace } from './catalog.mjs';

const fixture = () => structuredClone(workspace);

test('catalog preserves all six companies, both Managers, and twelve explicit coverage pairs', () => {
  assert.equal(validateWorkspace(), workspace);
  assert.deepEqual(workspace.companies, research.companies);
  assert.deepEqual(workspace.managers, research.managers);
  assert.equal(workspace.coverage.length, 12);
  assert.deepEqual(workspace.defaultEntries, { companies: 'alphabet', managers: 'north' });
  assert.deepEqual(workspace.defaultRoute, { page: 'index', entry: 'companies', objectId: 'alphabet', view: 'research' });
});

test('main reports retain the exact prior text and source cutoff without aliasing the legacy fixture', () => {
  for (const [id, companyId, managerId] of [
    ['alpha-north-main', 'alphabet', 'north'],
    ['alpha-field-main', 'alphabet', 'field'],
    ['ms-north-main', 'microsoft', 'north'],
  ]) {
    const report = findDocument(id);
    const original = research.cases.find(item => item.companyId === companyId && item.managerId === managerId);
    assert.equal(report.companyId, companyId);
    assert.equal(report.managerId, managerId);
    assert.equal(report.currentVersion, original.currentVersion);
    assert.deepEqual(report.versions, original.reports);
    assert.notEqual(report.versions, original.reports);
    assert.notEqual(report.versions[0].sections, original.reports[0].sections);
  }
});

test('a company/Manager pair contains separate main and topic reports with independent versions', () => {
  assert.equal(findDocument('alpha-north-cloud').kind, 'topic');
  assert.equal(findDocument('alpha-field-capacity').currentVersion, 'v1');
  assert.equal(findDocument('alpha-field-main').currentVersion, 'v2');
  const main = findVersion('alpha-north-main', 'v2');
  const topic = findVersion('alpha-north-cloud', 'v2');
  assert.notEqual(main.publicationId, topic.publicationId);
  assert.notDeepEqual(main.sections, topic.sections);
  assert.notEqual(main.cutoff, topic.cutoff);
  assert.equal(findVersion('alpha-field-capacity', 'v2'), null);
  for (const id of ['alpha-north-cloud', 'alpha-field-capacity']) for (const version of findDocument(id).versions) {
    assert.equal(version.sections.length, 4);
    const chars = (version.sections.flatMap(part => part.paragraphs).join('').match(/[\u4e00-\u9fff]/g) ?? []).length;
    assert.ok(chars >= 550 && chars <= 950, `${id}/${version.version}: ${chars} Chinese characters`);
  }
});

test('missing, blank, and unknown lookup scope never selects a report or current version', () => {
  for (const missing of [undefined, null, '', 'unknown', 'North', ' north']) {
    assert.equal(findDocument(missing), null);
    assert.equal(findVersion(missing, 'v1'), null);
    assert.equal(findVersion('alpha-north-main', missing), null);
    assert.equal(findCoverage('alphabet', missing), null);
    assert.equal(findCoverage(missing, 'north'), null);
    assert.equal(findEvidence(missing), null);
  }
  assert.equal(findVersion('alpha-north-main', 'latest'), null);
  assert.equal(findVersion('ms-north-main', 'v2'), null);
  assert.equal(findCoverage('microsoft', 'field').status, 'researching');
  assert.equal(workspace.reports.some(item => item.companyId === 'microsoft' && item.managerId === 'field'), false);
});

test('events resolve report identity, version, and section without confusing documents sharing v1', () => {
  const event = workspace.events.find(item => item.id === 'demo-event-alpha-cloud-payment');
  assert.deepEqual(event.affectedReports, [{ reportId: 'alpha-north-cloud', version: 'v2', sectionId: 'payment' }]);
  assert.equal(workspace.events.filter(item => item.id === event.id).length, 1);
  assert.ok(workspace.events.every(item => !Object.hasOwn(item, 'affectedCases')));
  const investment = workspace.events.find(item => item.id === 'demo-event-alpha-investment');
  assert.equal(investment.affectedReports.filter(ref => ref.reportId === 'alpha-north-main').length, 2);
  const missing = fixture();
  missing.events[0].affectedReports[0].reportId = 'unknown';
  assert.throws(() => validateWorkspace(missing), /event report, version, section, or company/);
  const wrongSection = fixture();
  wrongSection.events.at(-1).affectedReports[0].reportId = 'alpha-north-main';
  assert.throws(() => validateWorkspace(wrongSection), /event report, version, section, or company/);
  const cross = fixture();
  cross.events[0].affectedReports[0] = { reportId: 'ms-north-main', version: 'v1', sectionId: 'business' };
  assert.throws(() => validateWorkspace(cross), /event report, version, section, or company/);
});

test('every report has exactly one valid owner pair and current version', () => {
  for (const mutate of [
    data => { findDocument('alpha-north-cloud', data).companyId = 'unknown'; },
    data => { findDocument('alpha-north-cloud', data).managerId = 'unknown'; },
    data => { data.coverage = data.coverage.filter(item => !(item.companyId === 'alphabet' && item.managerId === 'north')); },
  ]) {
    const data = fixture(); mutate(data);
    assert.throws(() => validateWorkspace(data), /report ownership is unknown/);
  }
  const missing = fixture();
  findDocument('alpha-north-cloud', missing).currentVersion = 'v9';
  assert.throws(() => validateWorkspace(missing), /current version is missing/);
  const shared = fixture();
  findVersion('alpha-north-cloud', 'v2', shared).publicationId = findVersion('alpha-north-main', 'v2', shared).publicationId;
  assert.throws(() => validateWorkspace(shared), /publication identity/);
  const duplicated = fixture();
  findDocument('alpha-north-cloud', duplicated).versions.push(structuredClone(findVersion('alpha-north-cloud', 'v2')));
  assert.throws(() => validateWorkspace(duplicated), /version in.*identity/);
});

test('one main report per pair is enforced while topics are not limited to one', () => {
  const duplicateMain = fixture();
  findDocument('alpha-north-cloud', duplicateMain).kind = 'main';
  assert.throws(() => validateWorkspace(duplicateMain), /multiple main reports/);
  const anotherTopic = fixture();
  const topic = structuredClone(findDocument('alpha-north-cloud'));
  topic.id = 'independent-extra-topic';
  topic.versions.forEach(item => { item.publicationId = `extra-${item.publicationId}`; });
  anotherTopic.reports.push(topic);
  assert.equal(validateWorkspace(anotherTopic), anotherTopic);
});

test('citations cannot use another company or evidence beyond the exact report version cutoff', () => {
  const cross = fixture();
  findVersion('alpha-north-cloud', 'v2', cross).sections[0].citations.push('demo-ms-paid');
  assert.throws(() => validateWorkspace(cross), /cross-company citation/);
  const future = fixture();
  findVersion('alpha-north-cloud', 'v1', future).sections[0].citations.push('demo-alpha-use-later');
  assert.throws(() => validateWorkspace(future), /citation exceeds version cutoff/);
  const missing = fixture();
  findVersion('alpha-north-cloud', 'v2', missing).sections[0].citations.push('missing');
  assert.throws(() => validateWorkspace(missing), /citation is missing/);
  const event = fixture();
  event.events.at(-1).date = '2026-09-25';
  assert.throws(() => validateWorkspace(event), /event evidence exceeds event date/);
});

test('unavailable source and portfolio records retain explicit gaps without invented returns', () => {
  const gap = findEvidence('demo-ms-renewal-unavailable');
  assert.equal(gap.availability, 'unavailable');
  assert.equal(gap.quote, '');
  assert.deepEqual(gap.context, []);
  assert.deepEqual(workspace.portfolios.map(item => item.managerId), workspace.managers.map(item => item.id));
  for (const portfolio of workspace.portfolios) {
    assert.equal(portfolio.status, 'unavailable');
    assert.ok(portfolio.reason);
    assert.equal(Object.hasOwn(portfolio, 'return'), false);
    assert.equal(Object.hasOwn(portfolio, 'holdings'), false);
  }
  const invalid = fixture();
  invalid.portfolios[0].managerId = 'unknown';
  assert.throws(() => validateWorkspace(invalid), /portfolio scope/);
});

function independentFixture() {
  const company = id => ({ id, name: `Company ${id}`, ticker: id.toUpperCase(), website: `https://${id}.example/`, tagline: 'Independent synthetic scope' });
  const manager = id => ({ id, name: `Manager ${id}`, style: 'Synthetic', methodVersion: `synthetic-${id}`, horizon: 'Named test period', description: 'Independent fixture' });
  const evidence = companyId => ({ id: `e-${companyId}`, companyId, sourceTitle: '虚构演示 · 独立测试材料', sourceType: 'fixture', publishedAt: '2024-04-01', availableAt: '2024-04-02', locator: 'section 1', quote: '演示摘录：独立合成资料。', context: [], limitation: 'Synthetic only', language: 'zh-CN', availability: 'available', isDemo: true });
  const report = (id, companyId, managerId, kind = 'main') => ({
    id, companyId, managerId, kind, title: `Independent ${id}`, currentVersion: 'edition-7',
    versions: [{ version: 'edition-7', publicationId: `publication-${id}`, publishedAt: '2024-04-06', cutoff: '2024-04-05', language: 'zh-CN', title: 'Independent title', subtitle: 'Independent scope', summary: 'Independent summary', verdict: 'Unresolved', status: 'current', reviewNote: '', affectedSections: [], sections: [{ id: 'independent-section', kicker: '01', title: 'Independent section', paragraphs: ['Independently authored test text.'], citations: [`e-${companyId}`] }] }],
  });
  return {
    defaultRoute: { page: 'index', entry: 'managers', objectId: 'third', view: 'research' },
    defaultEntries: { companies: 'beta', managers: 'third' },
    companies: ['alpha', 'beta'].map(company), managers: ['first', 'second', 'third'].map(manager),
    coverage: [
      { companyId: 'alpha', managerId: 'first', status: 'published' },
      { companyId: 'beta', managerId: 'first', status: 'published' },
      { companyId: 'alpha', managerId: 'second', status: 'researching' },
      { companyId: 'alpha', managerId: 'third', status: 'published' },
    ],
    reports: [report('r-a', 'alpha', 'first'), report('r-b', 'beta', 'first'), report('r-c', 'alpha', 'third'), report('r-d', 'alpha', 'third', 'topic'), report('r-e', 'alpha', 'third', 'topic')],
    evidence: ['alpha', 'beta'].map(evidence),
    events: [{ id: 'independent-event', companyId: 'alpha', date: '2024-04-07', kind: 'watch', title: 'Independent event', summary: 'Two documents, one event', reason: 'Test document ownership', before: 'Old question', after: 'New question', evidenceIds: ['e-alpha'], unresolved: true, affectedReports: [{ reportId: 'r-d', version: 'edition-7', sectionId: 'independent-section' }, { reportId: 'r-e', version: 'edition-7', sectionId: 'independent-section' }] }],
    portfolios: ['first', 'second', 'third'].map(managerId => ({ managerId, status: 'unavailable', reason: 'Not connected' })),
  };
}

test('independent two-company, three-Manager data validates n:m ownership and multiple topics', () => {
  const data = independentFixture();
  assert.equal(validateWorkspace(data), data);
  assert.equal(findDocument('r-c', data).managerId, 'third');
  assert.equal(findVersion('r-b', 'edition-7', data).cutoff, '2024-04-05');
  assert.equal(findCoverage('alpha', 'second', data).status, 'researching');
  assert.equal(findCoverage('beta', 'second', data), null);
  assert.equal(findDocument('alpha-north-main', data), null);
  assert.equal(findVersion('r-a', 'v2', data), null);
  data.reports[1].versions[0].sections[0].citations = ['e-alpha'];
  assert.throws(() => validateWorkspace(data), /cross-company citation/);
});

test('entry defaults and coverage cannot silently fall back to a first entity or another Manager', () => {
  const defaults = independentFixture();
  defaults.defaultEntries.managers = 'north';
  assert.throws(() => validateWorkspace(defaults), /named entry defaults/);
  const route = independentFixture();
  route.defaultRoute.objectId = 'missing';
  assert.throws(() => validateWorkspace(route), /named index route/);
  const coverage = independentFixture();
  coverage.coverage.find(item => item.companyId === 'alpha' && item.managerId === 'second').status = 'published';
  assert.throws(() => validateWorkspace(coverage), /coverage status disagrees/);
});
