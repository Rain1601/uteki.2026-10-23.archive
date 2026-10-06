import test from 'node:test';
import assert from 'node:assert/strict';
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';
import { portfolioDecisionFixture, validatePortfolioDecisionFixture, getManagerDecisions, getDecision, getFeaturedDecisionId } from './portfolio-decisions.mjs';
import { formatRoute, parseRoute, routeContext } from './model.mjs';

const clone = value => structuredClone(value);
function synthetic() {
  const data = {
    companies: [{ id: 'cedar' }, { id: 'pine' }],
    managers: [{ id: 'patient' }, { id: 'scout' }, { id: 'new-manager' }],
    reports: [
      { id: 'cedar-study', companyId: 'cedar', managerId: 'patient', versions: [{ version: 'edition-1', publishedAt: '2025-02-03' }] },
      { id: 'pine-study', companyId: 'pine', managerId: 'scout', versions: [{ version: 'edition-2', publishedAt: '2025-02-04' }] },
    ],
  };
  const decision = (id, managerId, companyId, reportId, version, date) => ({
    id, managerId, date, kind: 'rebalance', isSimulated: true,
    title: '示例决定', titleEn: 'Example decision', summary: '独立情景', summaryEn: 'Independent scenario', companyIds: [companyId],
    allocations: [
      { assetId: companyId, beforePct: 25, draftPct: 40, targetPct: 30, reason: '情景权重', reasonEn: 'Scenario weight' },
      { assetId: 'cash', beforePct: 75, draftPct: 60, targetPct: 70, reason: '情景现金', reasonEn: 'Scenario cash' },
    ],
    reasons: [{ zh: '测试选择', en: 'Test selection' }],
    reports: [{ companyId, reportId, version, note: '指定版本', noteEn: 'Explicit edition' }],
    risks: [{ id: 'concentration', title: '集中度', titleEn: 'Concentration', opinion: '需要关注', opinionEn: 'Review needed', response: '缩小方案', responseEn: 'Smaller proposal', followUp: '等待证据', followUpEn: 'Await evidence', status: 'monitoring', responseStatus: 'responded' }],
    execution: { status: 'pending', summary: '没有成交', summaryEn: 'No fills' },
  });
  const fixture = {
    id: 'synthetic-independent-decisions', version: 'edition-3', asOf: '2025-02-07', isSimulated: true,
    label: '测试', labelEn: 'Test', disclosure: '独立虚构情景', disclosureEn: 'Independent fictional scenarios',
    featuredByManager: { patient: 'patient-older', scout: 'scout-only', 'new-manager': null },
    decisions: [
      decision('patient-newer', 'patient', 'cedar', 'cedar-study', 'edition-1', '2025-02-06'),
      decision('scout-only', 'scout', 'pine', 'pine-study', 'edition-2', '2025-02-05'),
      decision('patient-older', 'patient', 'cedar', 'cedar-study', 'edition-1', '2025-02-04'),
    ],
  };
  return { data, fixture };
}

test('named scenarios are independent fictional data with exact historical references and full allocations', () => {
  const before = JSON.stringify(workspace);
  assert.equal(validatePortfolioDecisionFixture(portfolioDecisionFixture), portfolioDecisionFixture);
  assert.equal(getManagerDecisions('north').length, 3);
  assert.equal(getManagerDecisions('field').length, 2);
  assert.equal(getFeaturedDecisionId('north'), 'north-20260930-allocation');
  assert.equal(getFeaturedDecisionId('field'), 'field-20260930-hold');
  for (const decision of portfolioDecisionFixture.decisions) {
    assert.ok(decision.date <= portfolioDecisionFixture.asOf);
    for (const field of ['beforePct', 'draftPct', 'targetPct']) assert.equal(decision.allocations.reduce((sum, row) => sum + row[field], 0), 100);
    assert.ok(decision.risks.every(item => item.status === 'monitoring' && item.responseStatus === 'responded'));
    assert.ok(['pending', 'not_required'].includes(decision.execution.status));
    for (const ref of decision.reports) {
      const document = workspace.reports.find(item => item.id === ref.reportId);
      assert.equal(document.companyId, ref.companyId);
      assert.equal(document.managerId, decision.managerId);
      assert.ok(document.versions.find(item => item.version === ref.version).publishedAt <= decision.date);
    }
  }
  assert.equal(JSON.stringify(workspace), before, 'scenario reads never change company, report, holding or account data');
});

test('synthetic managers and periods are independent and explicitly featured, not latest-selected', () => {
  const { data, fixture } = synthetic();
  const original = JSON.stringify(fixture);
  assert.deepEqual(getManagerDecisions('patient', data, fixture).map(item => item.id), ['patient-newer', 'patient-older']);
  assert.equal(getFeaturedDecisionId('patient', data, fixture), 'patient-older');
  assert.equal(getDecision('scout', 'scout-only', data, fixture).companyIds[0], 'pine');
  assert.deepEqual(getManagerDecisions('new-manager', data, fixture), []);
  assert.equal(getFeaturedDecisionId('new-manager', data, fixture), null);
  fixture.decisions.reverse();
  assert.equal(getFeaturedDecisionId('patient', data, fixture), 'patient-older');
  fixture.decisions.reverse();
  assert.equal(JSON.stringify(fixture), original);
});

test('same-day list ordering is deterministic by decision id', () => {
  const { data, fixture } = synthetic();
  fixture.decisions[2].date = fixture.decisions[0].date;
  assert.deepEqual(getManagerDecisions('patient', data, fixture).map(item => item.id), ['patient-newer', 'patient-older']);
  fixture.decisions.reverse();
  assert.deepEqual(getManagerDecisions('patient', data, fixture).map(item => item.id), ['patient-newer', 'patient-older']);
});

test('missing, unknown and cross-manager decision scope never selects another record', () => {
  const { data, fixture } = synthetic();
  for (const bad of [undefined, null, '', ' ', 'unknown']) {
    assert.throws(() => getManagerDecisions(bad, data, fixture));
    assert.throws(() => getDecision('patient', bad, data, fixture));
  }
  assert.throws(() => getDecision('patient', 'scout-only', data, fixture), /unknown for manager/);
  delete fixture.featuredByManager.patient;
  assert.throws(() => getFeaturedDecisionId('patient', data, fixture), /selection is missing/);
  fixture.featuredByManager.patient = 'scout-only';
  assert.throws(() => getFeaturedDecisionId('patient', data, fixture), /ownership/);
});

test('reports reject wrong company, author, version, future publication and duplicates', () => {
  const mutations = [
    ({ fixture }) => { fixture.decisions[0].reports[0].companyId = 'pine'; },
    ({ data }) => { data.reports[0].managerId = 'scout'; },
    ({ data }) => { data.reports[0].companyId = 'pine'; },
    ({ fixture }) => { fixture.decisions[0].reports[0].version = 'latest'; },
    ({ data }) => { data.reports[0].versions[0].publishedAt = '2025-02-07'; },
    ({ data }) => { data.reports[0].versions.push({ ...data.reports[0].versions[0] }); },
    ({ fixture }) => { fixture.decisions[0].reports.push({ ...fixture.decisions[0].reports[0] }); },
  ];
  for (const change of mutations) {
    const example = synthetic(); change(example);
    assert.throws(() => validatePortfolioDecisionFixture(example.fixture, example.data));
  }
});

test('scenario dates, identities, cash and allocation totals are validated', () => {
  const mutations = [
    ({ fixture }) => { fixture.decisions[0].date = '2025-02-08'; },
    ({ fixture }) => { fixture.asOf = '2025-02-30'; },
    ({ fixture }) => { fixture.decisions.push(clone(fixture.decisions[0])); },
    ({ fixture }) => { fixture.decisions[0].allocations[0].targetPct = 31; },
    ({ fixture }) => { fixture.decisions[0].allocations[0].beforePct = -1; },
    ({ fixture }) => { fixture.decisions[0].allocations[0].draftPct = NaN; },
    ({ fixture }) => { fixture.decisions[0].allocations.pop(); },
    ({ fixture }) => { fixture.decisions[0].allocations[1].assetId = 'cedar'; },
    ({ fixture }) => { fixture.decisions[0].companyIds.push('pine'); },
    ({ fixture }) => { fixture.decisions[0].companyIds.push('cedar'); },
    ({ fixture }) => { fixture.decisions[0].companyIds[0] = 'unknown'; },
  ];
  for (const change of mutations) {
    const example = synthetic(); change(example);
    assert.throws(() => validatePortfolioDecisionFixture(example.fixture, example.data));
  }
});

test('acknowledged concerns cannot become resolved and scenario targets cannot masquerade as fills', () => {
  const mutations = [
    ({ fixture }) => { fixture.decisions[0].risks[0].status = 'resolved'; },
    ({ fixture }) => { fixture.decisions[0].execution.status = 'executed'; },
    ({ fixture }) => { fixture.decisions[0].execution.fills = []; },
    ({ fixture }) => { fixture.decisions[0].execution.actualWeights = []; },
    ({ fixture }) => { fixture.decisions[0].execution.status = 'not_required'; },
    ({ fixture }) => { fixture.decisions[0].kind = 'hold'; },
  ];
  for (const change of mutations) {
    const example = synthetic(); change(example);
    assert.throws(() => validatePortfolioDecisionFixture(example.fixture, example.data));
  }
  const hold = getDecision('north', 'north-20260929-hold');
  assert.ok(hold.allocations.every(row => row.beforePct === row.targetPct));
  assert.equal(hold.execution.status, 'not_required');
});

test('decisions routes round-trip list, exact decision and each tab', () => {
  assert.deepEqual(parseRoute(formatRoute({ managerId: 'north', view: 'decisions' })), { managerId: 'north', view: 'decisions' });
  for (const decision of portfolioDecisionFixture.decisions) {
    for (const tab of [undefined, 'allocation', 'research', 'risk']) {
      const route = { managerId: decision.managerId, view: 'decisions', decisionId: decision.id };
      if (tab !== undefined) route.decisionTab = tab;
      assert.deepEqual(parseRoute(formatRoute(route)), route);
      assert.equal(routeContext(route).entity.id, decision.managerId);
    }
  }
});

test('synthetic decision routes validate the caller dataset and fixture, not named sample fallbacks', () => {
  const { data, fixture } = synthetic();
  const route = { managerId: 'scout', view: 'decisions', decisionId: 'scout-only', decisionTab: 'risk' };
  assert.deepEqual(parseRoute(formatRoute(route, data, fixture), data, fixture), route);
  assert.equal(routeContext(route, data, fixture).entity.id, 'scout');
  assert.throws(() => formatRoute({ ...route, decisionId: 'north-20260930-allocation' }, data, fixture));
});

test('decision routes reject mixed scopes, wrong owners, unknown tabs and blank identities', () => {
  const base = { managerId: 'north', view: 'decisions', decisionId: 'north-20260930-allocation' };
  for (const route of [
    { ...base, managerId: 'field' }, { ...base, decisionId: '' }, { ...base, decisionId: 'unknown' },
    { ...base, decisionTab: '' }, { ...base, decisionTab: 'unknown' },
    { managerId: 'north', view: 'decisions', decisionTab: 'risk' },
    { ...base, companyId: 'alphabet' }, { ...base, reportId: 'alpha-north-main' },
    { ...base, version: 'v2' }, { ...base, sectionId: 'summary' },
    { ...base, view: 'overview' }, { companyId: 'alphabet', view: 'reports', decisionId: base.decisionId },
    { ...base, mode: 'allocation' },
  ]) assert.throws(() => formatRoute(route));
  for (const hash of [
    '#/manager/north?view=decisions&decision=unknown',
    '#/manager/field?view=decisions&decision=north-20260930-allocation',
    '#/manager/north?view=overview&decision=north-20260930-allocation',
    '#/manager/north?view=decisions&tab=risk',
    '#/manager/north?view=decisions&decision=north-20260930-allocation&tab=unknown',
    '#/manager/north?view=decisions&decision=north-20260930-allocation&decision=north-20260929-hold',
    '#/manager/north?view=decisions&decision=north-20260930-allocation&tab=risk&tab=research',
    '#/company/alphabet?view=decisions',
  ]) assert.throws(() => parseRoute(hash));
});
