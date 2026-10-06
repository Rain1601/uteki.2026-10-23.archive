import test from 'node:test';
import assert from 'node:assert/strict';
import { formatRoute, parseRoute, routeContext } from './model.mjs';

test('risk routes preserve selected identity, explicit filter and Manager context', () => {
  for (const route of [
    { managerId: 'north', view: 'risks', riskId: 'north-shared-growth', riskFilter: 'needs_review' },
    { managerId: 'field', view: 'risks', riskId: 'field-delivery-chain', riskFilter: 'monitoring' },
    { managerId: 'north', view: 'risks', riskId: 'north-payment-quality', riskFilter: 'all' },
    { managerId: 'field', view: 'risks', riskId: 'field-delivery-chain' },
  ]) {
    const hash = formatRoute(route);
    assert.ok(hash.includes(`risk=${route.riskId}`));
    assert.deepEqual(parseRoute(hash), route);
    const context = routeContext(route);
    assert.equal(context.entityType, 'manager');
    assert.equal(context.entity.id, route.managerId);
  }
});

test('empty resolved filter and unselected index do not silently select a risk', () => {
  for (const route of [
    { managerId: 'north', view: 'risks', riskFilter: 'resolved' },
    { managerId: 'field', view: 'risks' },
  ]) {
    const hash = formatRoute(route);
    const parsed = parseRoute(hash);
    assert.deepEqual(parsed, route);
    assert.equal(Object.hasOwn(parsed, 'riskId'), false);
    assert.equal(routeContext(parsed).entity.id, route.managerId);
  }
});

test('unknown, blank, wrong-manager and filter-conflicting risk identities fail', () => {
  for (const route of [
    { managerId: 'unknown', view: 'risks' },
    { managerId: '', view: 'risks' },
    { managerId: 'north', view: 'risks', riskId: 'unknown' },
    { managerId: 'north', view: 'risks', riskId: '' },
    { managerId: 'north', view: 'risks', riskId: 'field-delivery-chain' },
    { managerId: 'north', view: 'risks', riskFilter: '' },
    { managerId: 'north', view: 'risks', riskFilter: 'closed' },
    { managerId: 'north', view: 'risks', riskId: 'north-shared-growth', riskFilter: 'monitoring' },
    { managerId: 'field', view: 'risks', riskId: 'field-delivery-chain', riskFilter: 'resolved' },
  ]) {
    assert.throws(() => formatRoute(route));
    assert.throws(() => routeContext(route));
  }
  for (const hash of [
    '#/manager/north?view=risks&risk=',
    '#/manager/north?view=risks&risk=%20',
    '#/manager/north?view=risks&risk=unknown',
    '#/manager/north?view=risks&risk=field-delivery-chain',
    '#/manager/north?view=risks&status=',
    '#/manager/north?view=risks&status=closed',
    '#/manager/north?view=risks&risk=north-shared-growth&status=monitoring',
    '#/manager/field?view=risks&risk=field-delivery-chain&status=resolved',
    '#/manager/north?view=risks&risk=north-shared-growth&risk=north-payment-quality',
    '#/manager/north?view=risks&status=all&status=monitoring',
  ]) assert.throws(() => parseRoute(hash));
});

test('risk routes reject mixed company, report and decision scope in both directions', () => {
  for (const [field, value, parameter] of [
    ['companyId', 'alphabet', 'company'], ['reportId', 'alpha-north-main', 'report'],
    ['version', 'v2', 'version'], ['sectionId', 'economics', 'section'],
    ['decisionId', 'north-20260930-allocation', 'decision'], ['decisionTab', 'risk', 'tab'],
  ]) {
    assert.throws(() => formatRoute({ managerId: 'north', view: 'risks', [field]: value }), /cannot carry/);
    assert.throws(() => parseRoute(`#/manager/north?view=risks&${parameter}=${value}`), /cannot carry/);
  }
  for (const route of [
    { companyId: 'alphabet', view: 'risks' },
    { managerId: 'north', view: 'overview', riskId: 'north-shared-growth' },
    { managerId: 'north', view: 'decisions', decisionId: 'north-20260930-allocation', riskFilter: 'all' },
    { managerId: 'north', companyId: 'alphabet', view: 'report', reportId: 'alpha-north-main', version: 'v2', riskId: 'north-shared-growth' },
  ]) assert.throws(() => formatRoute(route));
  assert.throws(() => parseRoute('#/company/alphabet?view=overview&risk=north-shared-growth'), /unknown route parameter/);
});

test('existing decision, report and company links retain their exact URL contract', () => {
  const cases = [
    ['#/manager/field?view=decisions&decision=field-20260930-hold&tab=risk', { managerId: 'field', view: 'decisions', decisionId: 'field-20260930-hold', decisionTab: 'risk' }],
    ['#/manager/north?view=report&company=alphabet&report=alpha-north-main&version=v2&section=economics', { managerId: 'north', companyId: 'alphabet', view: 'report', reportId: 'alpha-north-main', version: 'v2', sectionId: 'economics' }],
    ['#/company/alphabet?view=report&report=alpha-field-main&version=v2', { companyId: 'alphabet', view: 'report', reportId: 'alpha-field-main', version: 'v2' }],
    ['#/manager/north?view=companies', { managerId: 'north', view: 'companies' }],
  ];
  for (const [hash, route] of cases) {
    assert.deepEqual(parseRoute(hash), route);
    assert.equal(formatRoute(route), hash);
  }
});

test('all three route APIs validate the explicitly supplied fourth risk fixture argument', () => {
  const data = {
    companies: [{ id: 'elm' }], managers: [{ id: 'ridge', name: 'Ridge' }],
    reports: [{ id: 'elm-notes', companyId: 'elm', managerId: 'ridge', versions: [{
      version: 'first', publishedAt: '2025-01-10', cutoff: '2025-01-09',
      sections: [{ id: 'limits', citations: ['elm-source'] }],
    }] }],
    evidence: [{ id: 'elm-source', companyId: 'elm', publishedAt: '2025-01-08', availableAt: '2025-01-09', availability: 'excerpt' }],
  };
  // A continuous research risk may exist before any allocation decision.
  const decisions = {
    id: 'ridge-empty-decisions', version: 'v1', asOf: '2025-01-12', isSimulated: true,
    label: '样稿', labelEn: 'Sample', disclosure: '独立样稿', disclosureEn: 'Independent sample',
    decisions: [], featuredByManager: { ridge: null },
  };
  const risks = {
    id: 'ridge-risks', version: 'v1', asOf: '2025-01-12', isSimulated: true,
    label: '样稿', labelEn: 'Sample', disclosure: '独立样稿', disclosureEn: 'Independent sample',
    featuredByManager: { ridge: 'elm-margin' }, risks: [{
      id: 'elm-margin', managerId: 'ridge', companyIds: ['elm'], status: 'monitoring', isSimulated: true,
      title: '利润资料', titleEn: 'Margin material', summary: '继续追踪', summaryEn: 'Keep tracking',
      impact: '判断保留', impactEn: 'Keep judgment conditional', reviewTrigger: '补充资料', reviewTriggerEn: 'Further material',
      openedAt: '2025-01-11', updatedAt: '2025-01-12', decisionReviews: [], resolution: null,
      observations: [{ id: 'elm-observation', date: '2025-01-11', text: '保留缺口', textEn: 'Retain gap', sources: [{
        companyId: 'elm', reportId: 'elm-notes', version: 'first', sectionId: 'limits', evidenceId: 'elm-source',
      }] }],
    }],
  };
  const route = { managerId: 'ridge', view: 'risks', riskId: 'elm-margin', riskFilter: 'monitoring' };
  const hash = '#/manager/ridge?view=risks&risk=elm-margin&status=monitoring';
  assert.equal(formatRoute(route, data, decisions, risks), hash);
  assert.deepEqual(parseRoute(hash, data, decisions, risks), route);
  assert.equal(routeContext(route, data, decisions, risks).entity, data.managers[0]);
  const missing = structuredClone(risks); missing.risks = []; missing.featuredByManager.ridge = null;
  for (const fixture of [missing, { ...risks, asOf: '2025-01-10' }]) {
    assert.throws(() => formatRoute(route, data, decisions, fixture));
    assert.throws(() => parseRoute(hash, data, decisions, fixture));
    assert.throws(() => routeContext(route, data, decisions, fixture));
  }
  assert.throws(() => formatRoute(route, data, decisions), /unknown/);
  assert.throws(() => parseRoute(hash, data, decisions), /unknown/);
  assert.throws(() => routeContext(route, data, decisions), /unknown/);
});
