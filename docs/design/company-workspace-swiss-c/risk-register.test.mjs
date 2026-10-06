import test from 'node:test';
import assert from 'node:assert/strict';
import { workspace } from '../../../apps/uteki_zero/catalog.mjs';
import { portfolioDecisionFixture } from './portfolio-decisions.mjs';
import {
  riskRegisterFixture, validateRiskRegister, getManagerRisks, getRisk,
  getFeaturedRiskId, getRiskForDecisionReview,
} from './risk-register.mjs';

const clone = value => structuredClone(value);
const sample = () => ({ data: clone(workspace), fixture: clone(riskRegisterFixture), decisions: clone(portfolioDecisionFixture) });
const validate = ({ data, fixture, decisions }) => validateRiskRegister(fixture, data, decisions);

// Independent issuer, manager, fiscal period and report schema instance. No
// original pilot identifier, source or expected allocation feeds these values.
function independent() {
  const data = {
    companies: [{ id: 'sample-a' }, { id: 'sample-b' }], managers: [{ id: 'pilot' }, { id: 'empty' }],
    evidence: [{ id: 'input-a', companyId: 'sample-a', publishedAt: '2024-02-20', availableAt: '2024-02-21', availability: 'excerpt' }],
    reports: [{ id: 'memo-a', companyId: 'sample-a', managerId: 'pilot', versions: [{
      version: 'review-2', publishedAt: '2024-02-24', cutoff: '2024-02-23',
      sections: [{ id: 'operating', citations: ['input-a'] }],
    }] }],
  };
  const decisions = {
    id: 'independent-decisions', version: 'v1', asOf: '2024-03-01', isSimulated: true,
    label: '独立样稿', labelEn: 'Independent fixture', disclosure: '虚构', disclosureEn: 'Fictional',
    featuredByManager: { pilot: 'keep-a', empty: null }, decisions: [{
      id: 'keep-a', managerId: 'pilot', date: '2024-02-26', kind: 'hold', isSimulated: true,
      title: '维持', titleEn: 'Maintain', summary: '待证据', summaryEn: 'Await evidence', companyIds: ['sample-a'],
      allocations: [
        { assetId: 'sample-a', beforePct: 40, draftPct: 40, targetPct: 40, reason: '维持', reasonEn: 'Maintain' },
        { assetId: 'cash', beforePct: 60, draftPct: 60, targetPct: 60, reason: '维持', reasonEn: 'Maintain' },
      ], reasons: [{ zh: '等待', en: 'Await' }],
      reports: [{ companyId: 'sample-a', reportId: 'memo-a', version: 'review-2', note: '背景', noteEn: 'Context' }],
      risks: [{ id: 'margin-review', title: '利润', titleEn: 'Margin', opinion: '复核', opinionEn: 'Review', response: '维持', responseEn: 'Maintain', followUp: '补资料', followUpEn: 'Obtain data', status: 'monitoring', responseStatus: 'responded' }],
      execution: { status: 'not_required', summary: '维持', summaryEn: 'Maintain' },
    }],
  };
  const fixture = {
    id: 'independent-risks', version: 'v1', asOf: '2024-03-01', isSimulated: true,
    label: '独立样稿', labelEn: 'Independent fixture', disclosure: '虚构', disclosureEn: 'Fictional',
    featuredByManager: { pilot: 'margin-question', empty: null }, risks: [{
      id: 'margin-question', managerId: 'pilot', companyIds: ['sample-a'], status: 'needs_review',
      openedAt: '2024-02-25', updatedAt: '2024-03-01', title: '利润检查', titleEn: 'Margin review',
      summary: '待复核', summaryEn: 'Review needed', impact: '等待单位数据', impactEn: 'Await unit data',
      reviewTrigger: '新材料', reviewTriggerEn: 'New material', isSimulated: true,
      decisionReviews: [{ decisionId: 'keep-a', reviewRiskId: 'margin-review' }],
      observations: [{ id: 'first-observation', date: '2024-02-25', text: '缺口保留', textEn: 'Gap retained', sources: [
        { companyId: 'sample-a', reportId: 'memo-a', version: 'review-2', sectionId: 'operating', evidenceId: 'input-a' },
      ] }], resolution: null,
    }],
  };
  return { data, decisions, fixture };
}

test('named fictional register preserves scopes, dates, deterministic order and explicit featured selection', () => {
  assert.equal(validateRiskRegister(riskRegisterFixture), riskRegisterFixture);
  assert.deepEqual(getManagerRisks('north').map(item => item.id), ['north-shared-growth', 'north-payment-quality', 'north-renewal-gap']);
  assert.deepEqual(getManagerRisks('field').map(item => item.id), ['field-delivery-chain']);
  assert.equal(getFeaturedRiskId('north'), 'north-shared-growth');
  assert.equal(getFeaturedRiskId('field'), 'field-delivery-chain');
  assert.equal(getRisk('north', 'north-renewal-gap').observations[0].sources[0].evidenceId, 'demo-ms-renewal-unavailable');
  assert.equal(workspace.evidence.find(item => item.id === 'demo-ms-renewal-unavailable').availability, 'unavailable');
});

test('a continuing Field issue maps explicitly to two independent decision reviews', () => {
  const risk = getRisk('field', 'field-delivery-chain');
  assert.equal(risk.decisionReviews.length, 2);
  for (const reference of risk.decisionReviews) assert.equal(getRiskForDecisionReview('field', reference.decisionId, reference.reviewRiskId), risk);
  const input = sample(); input.fixture.risks[3].decisionReviews.pop();
  assert.equal(getRiskForDecisionReview('field', 'field-20260930-hold', 'field-delivery', input.data, input.fixture, input.decisions), null);
  input.fixture.risks[3].title = input.fixture.risks[0].title;
  assert.equal(validate(input), input.fixture); // Titles never determine identity or linkage.
});

test('PM responded never closes an issue or prevents a separate needs-review status', () => {
  const risk = getRisk('north', 'north-shared-growth');
  assert.equal(risk.status, 'needs_review'); assert.equal(risk.resolution, null);
  const opinion = portfolioDecisionFixture.decisions[0].risks[0];
  assert.equal(opinion.responseStatus, 'responded');
  assert.equal(opinion.status, 'monitoring');
  const input = sample(); input.fixture.risks[0].status = 'resolved';
  assert.throws(() => validate(input), /requires explicit resolution/);
});

test('missing, unknown and cross-manager identities never select another risk', () => {
  for (const managerId of [undefined, '', 'unknown']) assert.throws(() => getManagerRisks(managerId));
  for (const riskId of [undefined, '', 'unknown', 'field-delivery-chain']) assert.throws(() => getRisk('north', riskId));
  assert.throws(() => getRiskForDecisionReview('north', 'field-20260930-hold', 'field-delivery'), /match requested manager/);
  assert.throws(() => getRiskForDecisionReview('field', 'field-20260930-hold', 'missing'), /unknown/);
  const input = sample(); delete input.fixture.featuredByManager.north;
  assert.throws(() => getFeaturedRiskId('north', input.data, input.fixture, input.decisions), /selection is missing/);
  input.fixture.featuredByManager.north = 'field-delivery-chain';
  assert.throws(() => validate(input), /featured risk ownership/);
});

test('one decision review cannot be duplicated or assigned to multiple continuous risks', () => {
  const input = sample(); input.fixture.risks[0].decisionReviews.push(clone(input.fixture.risks[0].decisionReviews[0]));
  assert.throws(() => validate(input), /only one continuous risk/);
  const another = sample(); const duplicate = clone(another.fixture.risks[0]); duplicate.id = 'duplicate-issue'; another.fixture.risks.push(duplicate);
  assert.throws(() => validate(another), /only one continuous risk/);
});

test('scope is enforced for each decision, company, report author and evidence reference', () => {
  const mutations = [
    input => { input.fixture.risks[3].decisionReviews[0].decisionId = 'north-20260929-hold'; },
    input => { input.fixture.risks[3].companyIds = ['microsoft']; },
    input => { input.fixture.risks[0].observations[0].sources[0].companyId = 'microsoft'; },
    input => { input.data.reports.find(item => item.id === 'alpha-north-main').managerId = 'field'; },
    input => { input.data.evidence.find(item => item.id === 'demo-alpha-build-later').companyId = 'microsoft'; },
    input => { input.fixture.risks[2].companyIds = ['nvidia']; },
  ];
  for (const mutate of mutations) { const input = sample(); mutate(input); assert.throws(() => validate(input)); }
});

test('exact report version and section citations are required; unavailable stays representable', () => {
  for (const [field, value] of [['version', 'latest'], ['sectionId', 'judgment'], ['evidenceId', 'demo-alpha-cost-gap']]) {
    const input = sample(); input.fixture.risks[2].observations[0].sources[0][field] = value;
    assert.throws(() => validate(input));
  }
  const input = sample(); input.fixture.risks[0].observations[0].sources.push(clone(input.fixture.risks[0].observations[0].sources[0]));
  assert.throws(() => validate(input), /source references must be unique/);
  const duplicateVersion = sample(); const report = duplicateVersion.data.reports.find(item => item.id === 'alpha-north-main'); report.versions.push(clone(report.versions[1]));
  assert.throws(() => validate(duplicateVersion), /unambiguous/);
});

test('risk, observation, decision review and source chronology cannot look ahead', () => {
  const mutations = [
    input => { input.fixture.asOf = '2026-09-29'; },
    input => { input.fixture.risks[0].openedAt = '2026-10-01'; },
    input => { input.fixture.risks[3].openedAt = '2026-09-29'; },
    input => { input.fixture.risks[3].observations[1].date = '2026-10-01'; },
    input => { input.fixture.risks[3].observations[0].date = '2026-09-27'; },
    input => { input.data.evidence.find(item => item.id === 'demo-alpha-build-later').availableAt = '2026-09-29'; },
    input => { input.data.reports.find(item => item.id === 'alpha-field-capacity').versions[0].publishedAt = '2026-10-01'; },
    input => { input.fixture.risks[0].updatedAt = '2026-02-30'; },
  ];
  for (const mutate of mutations) { const input = sample(); mutate(input); assert.throws(() => validate(input)); }
});

test('independent company, manager and earlier period work with no pilot fallback', () => {
  const { data, fixture, decisions } = independent();
  assert.equal(validateRiskRegister(fixture, data, decisions), fixture);
  assert.equal(getRisk('pilot', 'margin-question', data, fixture, decisions).companyIds[0], 'sample-a');
  assert.equal(getRiskForDecisionReview('pilot', 'keep-a', 'margin-review', data, fixture, decisions).id, 'margin-question');
  assert.deepEqual(getManagerRisks('empty', data, fixture, decisions), []);
  assert.equal(getFeaturedRiskId('empty', data, fixture, decisions), null);
  assert.throws(() => getManagerRisks('north', data, fixture, decisions), /unknown/);
  fixture.risks[0].companyIds = ['sample-b'];
  assert.throws(() => validateRiskRegister(fixture, data, decisions), /company scope/);
});

test('resolved is possible only with explicit dated, bilingual, available supporting evidence', () => {
  const input = independent(); const risk = input.fixture.risks[0];
  risk.status = 'resolved'; risk.resolution = { date: '2024-03-01', reason: '已核对样本条件', reasonEn: 'Sample conditions checked', sources: clone(risk.observations[0].sources) };
  assert.equal(validate(input), input.fixture);
  input.data.evidence[0].availability = 'unavailable';
  assert.throws(() => validate(input), /unavailable evidence cannot establish/);
  input.data.evidence[0].availability = 'excerpt'; risk.resolution.date = '2024-02-25';
  assert.throws(() => validate(input), /resolution date/);
  risk.resolution.date = '2024-03-01'; risk.resolution.reasonEn = '';
  assert.throws(() => validate(input), /bilingual reason/);
  risk.resolution.reasonEn = 'Sample conditions checked'; risk.status = 'monitoring';
  assert.throws(() => validate(input), /open risk must keep resolution null/);
});

test('deterministic ties and helpers preserve supplied records without mutation', () => {
  const input = sample(); input.fixture.risks[1].updatedAt = '2026-09-30';
  const before = JSON.stringify(input);
  assert.deepEqual(getManagerRisks('north', input.data, input.fixture, input.decisions).map(item => item.id), ['north-payment-quality', 'north-shared-growth', 'north-renewal-gap']);
  getFeaturedRiskId('north', input.data, input.fixture, input.decisions);
  assert.equal(JSON.stringify(input), before);
});
