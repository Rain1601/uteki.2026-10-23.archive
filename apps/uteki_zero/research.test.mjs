import test from 'node:test';
import assert from 'node:assert/strict';
import { research, findCase, findReport, findEvidence, validateResearch } from './research.mjs';

const fixture = () => structuredClone(research);
const reportIn = (data, companyId, managerId, version) => data.cases
  .find(item => item.companyId === companyId && item.managerId === managerId)
  ?.reports.find(report => report.version === version);

test('the named demo dataset has valid identities, publications, dates, and links', () => {
  assert.equal(validateResearch(), research);
  assert.deepEqual(research.companies.map(item => item.id), ['alphabet', 'microsoft', 'nvidia', 'costco', 'arista', 'eaton']);
  assert.deepEqual(research.managers.map(item => item.id), ['north', 'field']);
});

test('lookups require complete, exact scope and never substitute a default or current version', () => {
  for (const companyId of [undefined, null, '', 'unknown', 'Alphabet', ' alphabet']) {
    assert.equal(findCase(companyId, 'north'), null);
    assert.equal(findReport(companyId, 'north', 'v2'), null);
  }
  for (const managerId of [undefined, null, '', 'unknown', 'North']) {
    assert.equal(findCase('alphabet', managerId), null);
    assert.equal(findReport('alphabet', managerId, 'v2'), null);
  }
  for (const version of [undefined, null, '', 'v9', 'current', 'latest']) {
    assert.equal(findReport('alphabet', 'north', version), null);
  }
  for (const id of [undefined, null, '', 'unknown']) assert.equal(findEvidence(id), null);
});

test('same company and version under two Managers resolves independent complete reports', () => {
  for (const version of ['v1', 'v2']) {
    const north = findReport('alphabet', 'north', version);
    const field = findReport('alphabet', 'field', version);
    assert.notEqual(north, field);
    assert.notEqual(north.publicationId, field.publicationId);
    assert.notEqual(north.sections.find(item => item.id === 'thesis').paragraphs.join(''), field.sections.find(item => item.id === 'thesis').paragraphs.join(''));
    assert.ok(north.sections.length >= 7 && field.sections.length >= 7);
  }
});

test('another company has its own report and never borrows an unpublished Manager report', () => {
  const microsoft = findReport('microsoft', 'north', 'v1');
  const alphabet = findReport('alphabet', 'north', 'v1');
  assert.notEqual(microsoft.publicationId, alphabet.publicationId);
  assert.match(microsoft.title, /Microsoft/);
  assert.equal(findReport('microsoft', 'north', 'v2'), null);
  assert.equal(findReport('microsoft', 'field', 'v1'), null);
  assert.deepEqual(findCase('microsoft', 'field'), {
    companyId: 'microsoft', managerId: 'field', currentVersion: null, status: 'researching', reports: [],
  });
  for (const part of microsoft.sections) for (const id of part.citations) {
    assert.equal(findEvidence(id).companyId, 'microsoft');
  }
});

test('researching cases expose no staged or borrowed research', () => {
  for (const companyId of ['nvidia', 'costco', 'arista', 'eaton']) for (const managerId of ['north', 'field']) {
    const item = findCase(companyId, managerId);
    assert.equal(item.status, 'researching');
    assert.equal(item.currentVersion, null);
    assert.deepEqual(item.reports, []);
    assert.equal(findReport(companyId, managerId, 'v1'), null);
  }
  const data = fixture();
  data.cases.find(item => item.companyId === 'microsoft' && item.managerId === 'field').reports.push(data.cases[0].reports[0]);
  assert.throws(() => validateResearch(data), /unpublished case must not expose reports/);
});

test('historical and review versions retain full arguments rather than a version summary', () => {
  const original = findReport('alphabet', 'north', 'v1');
  assert.equal(original.status, 'review');
  assert.match(original.reviewNote, /全文.*保留/);
  assert.ok(original.affectedSections.includes('economics'));
  assert.equal(findCase('alphabet', 'north').currentVersion, 'v2');
  for (const item of research.cases) for (const report of item.reports) {
    const body = report.sections.flatMap(part => part.paragraphs).join('');
    const chineseLength = (body.match(/[\u4e00-\u9fff]/g) || []).length;
    assert.ok(report.sections.length >= 7, `${item.companyId}/${item.managerId}/${report.version} needs complete sections`);
    assert.ok(chineseLength >= 900 && chineseLength <= 1400, `${item.companyId}/${item.managerId}/${report.version} has ${chineseLength} Chinese characters`);
    assert.ok(report.sections.some(part => /估值|价格/.test(part.kicker)));
    assert.ok(report.sections.some(part => /未知|边界|责任|可比性/.test(part.kicker)));
  }
});

test('unknown, duplicated, and cross-company citations are rejected', () => {
  const missing = fixture();
  reportIn(missing, 'alphabet', 'north', 'v2').sections[0].citations.push('not-found');
  assert.throws(() => validateResearch(missing), /missing citation/);
  const crossed = fixture();
  reportIn(crossed, 'alphabet', 'north', 'v2').sections[0].citations.push('demo-ms-paid');
  assert.throws(() => validateResearch(crossed), /cross-company citation/);
  const duplicated = fixture();
  reportIn(duplicated, 'alphabet', 'north', 'v2').sections[0].citations.push('demo-alpha-business');
  assert.throws(() => validateResearch(duplicated), /section citation is duplicated/);
});

test('a newer evidence item cannot silently change an earlier report cutoff', () => {
  const data = fixture();
  reportIn(data, 'alphabet', 'north', 'v1').sections[0].citations.push('demo-alpha-use-later');
  assert.throws(() => validateResearch(data), /citation exceeds report cutoff/);
  assert.equal(findReport('alphabet', 'north', 'v1').cutoff, '2026-09-17');
  assert.equal(findReport('alphabet', 'north', 'v2').cutoff, '2026-09-28');
});

test('unavailable evidence stays a scoped gap with no replacement quote or context', () => {
  const missing = findEvidence('demo-ms-renewal-unavailable');
  assert.equal(missing.companyId, 'microsoft');
  assert.equal(missing.availability, 'unavailable');
  assert.equal(missing.quote, '');
  assert.deepEqual(missing.context, []);
  assert.ok(findReport('microsoft', 'north', 'v1').sections.find(part => part.id === 'risk').citations.includes(missing.id));
  const data = fixture();
  data.evidence.find(item => item.id === missing.id).quote = '演示摘录：借用其他材料。';
  assert.throws(() => validateResearch(data), /quote does not match availability/);
});

test('one matter retains one event with multiple citations and same-source different matters remain separate', () => {
  const investment = research.events.find(item => item.id === 'demo-event-alpha-investment');
  const usage = research.events.find(item => item.id === 'demo-event-alpha-usage');
  assert.equal(investment.evidenceIds.length, 2);
  assert.equal(research.events.filter(item => item.evidenceIds.includes('demo-alpha-build-later')).length, 1);
  assert.notEqual(investment.id, usage.id);
  assert.equal(findEvidence('demo-alpha-build-later').sourceTitle, findEvidence('demo-alpha-use-later').sourceTitle);
  assert.notEqual(findEvidence('demo-alpha-build-later').locator, findEvidence('demo-alpha-use-later').locator);
  assert.equal(investment.unresolved, true);
});

test('event references must resolve the exact company, Manager, version, and section', () => {
  const wrongManager = fixture();
  wrongManager.events.find(item => item.companyId === 'microsoft').affectedCases[0].managerId = 'field';
  assert.throws(() => validateResearch(wrongManager), /unknown case, version, or section/);
  const wrongVersion = fixture();
  wrongVersion.events[0].affectedCases[0].version = 'v404';
  assert.throws(() => validateResearch(wrongVersion), /unknown case, version, or section/);
  const wrongSection = fixture();
  wrongSection.events[0].affectedCases[0].sectionId = 'not-in-this-report';
  assert.throws(() => validateResearch(wrongSection), /unknown case, version, or section/);
  const wrongEvidence = fixture();
  wrongEvidence.events[0].evidenceIds = ['demo-ms-paid'];
  assert.throws(() => validateResearch(wrongEvidence), /cross-company event evidence/);
});

test('publication identities are unique and current pointers cannot target absent or historical versions', () => {
  const duplicate = fixture();
  reportIn(duplicate, 'microsoft', 'north', 'v1').publicationId = reportIn(duplicate, 'alphabet', 'north', 'v1').publicationId;
  assert.throws(() => validateResearch(duplicate), /publication identity/);
  const missing = fixture();
  missing.cases[0].currentVersion = 'v404';
  assert.throws(() => validateResearch(missing), /current version is missing/);
  const historical = fixture();
  reportIn(historical, 'alphabet', 'north', 'v2').status = 'historical';
  assert.throws(() => validateResearch(historical), /points to historical report/);
});

test('review status identifies an actual affected section and does not replace the original body', () => {
  const unknown = fixture();
  reportIn(unknown, 'alphabet', 'north', 'v1').affectedSections.push('not-found');
  assert.throws(() => validateResearch(unknown), /affected section is invalid/);
  const empty = fixture();
  reportIn(empty, 'alphabet', 'north', 'v1').reviewNote = '';
  assert.throws(() => validateResearch(empty), /review report must state/);
});

test('evidence identities, demo attribution, date ordering, and table dimensions are validated', () => {
  const duplicate = fixture();
  duplicate.evidence.push(structuredClone(duplicate.evidence[0]));
  assert.throws(() => validateResearch(duplicate), /evidence identity/);
  const attribution = fixture();
  attribution.evidence[0].sourceTitle = 'Real earnings release';
  assert.throws(() => validateResearch(attribution), /visibly fictional/);
  const dates = fixture();
  dates.evidence[0].availableAt = '2026-02-30';
  assert.throws(() => validateResearch(dates), /evidence dates/);
  const table = fixture();
  reportIn(table, 'alphabet', 'north', 'v2').sections.find(part => part.table).table.rows[0].push('wrong column');
  assert.throws(() => validateResearch(table), /table shape/);
});

test('the first experience is explicit fixture configuration, never a lookup fallback', () => {
  const { companyId, managerId, version, view } = research.defaultRoute;
  assert.equal(view, 'report');
  assert.ok(findReport(companyId, managerId, version));
  assert.equal(findReport(undefined, undefined, undefined), null);
  const invalid = fixture();
  invalid.defaultRoute.companyId = 'unknown';
  assert.throws(() => validateResearch(invalid), /named demo route does not resolve/);
});
