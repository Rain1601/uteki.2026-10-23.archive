import test from 'node:test';
import assert from 'node:assert/strict';
import { catalog } from './model.mjs';
import { managerCoverageFixture, getManagerCoverage } from './manager-coverage.mjs';

function synthetic() {
  return {
    companies: [{ id: 'cedar', name: 'Cedar' }, { id: 'pine', name: 'Pine' }, { id: 'birch', name: 'Birch' }, { id: 'elm', name: 'Elm' }],
    managers: [{ id: 'scout' }, { id: 'patient' }],
    coverage: [
      { managerId: 'scout', companyId: 'cedar', status: 'published' },
      { managerId: 'scout', companyId: 'elm', status: 'researching' },
    ],
    reports: [
      { id: 'cedar-scout', managerId: 'scout', companyId: 'cedar', currentVersion: 'v2', versions: [
        { version: 'v1', title: 'Earlier Cedar', publishedAt: '2023-05-03', sections: [] },
        { version: 'v2', title: 'Current Cedar', publishedAt: '2024-02-17', sections: [] },
      ] },
      { id: 'cedar-patient', managerId: 'patient', companyId: 'cedar', currentVersion: 'v1', versions: [
        { version: 'v1', title: 'Patient Cedar', publishedAt: '2024-04-17', sections: [] },
      ] },
      { id: 'elm-scout', managerId: 'scout', companyId: 'elm', currentVersion: 'v1', versions: [
        { version: 'v1', title: 'Unselected Elm', publishedAt: '2024-06-17', sections: [] },
      ] },
    ], events: [], evidence: [],
  };
}

function fixture() {
  return {
    id: 'independent-focus-fixture', version: 'v5', asOf: '2024-06-30', isSimulated: true,
    label: '模拟清单', labelEn: 'Example list', disclosure: '独立关注清单', disclosureEn: 'Independent focus list',
    records: [
      { id: 'scout-cedar', managerId: 'scout', companyId: 'cedar', stage: 'history', since: '2023-04-30', endedAt: '2024-03-15', reason: '已归档', reasonEn: 'Archived' },
      { id: 'scout-pine', managerId: 'scout', companyId: 'pine', stage: 'current', since: '2024-04-01', reason: '当前关注', reasonEn: 'Currently following' },
      { id: 'scout-birch', managerId: 'scout', companyId: 'birch', stage: 'planned', addedAt: '2024-06-29', reason: '拟研究', reasonEn: 'Considering research' },
      { id: 'patient-cedar', managerId: 'patient', companyId: 'cedar', stage: 'current', since: '2024-04-12', reason: '持续跟踪', reasonEn: 'Following' },
    ],
  };
}

test('coverage uses only the selected focus list and matches reports to the selected author', () => {
  const data = synthetic(), source = fixture(), before = JSON.stringify({ data, source });
  const result = getManagerCoverage('scout', source, data);
  assert.deepEqual(result.counts, { current: 1, history: 1, planned: 1 });
  assert.equal(result.total, 3);
  assert.deepEqual(result.records.map(item => item.companyId), ['cedar', 'pine', 'birch']);
  assert.ok(!result.records.some(item => item.companyId === 'elm'), 'neither legacy coverage nor a report auto-adds a company');
  const archived = result.records[0];
  assert.deepEqual(archived.reports.map(item => [item.document.id, item.manager.id, item.report.version]), [['cedar-scout', 'scout', 'v2']]);
  assert.equal(archived.since, '2023-04-30');
  assert.equal(archived.endedAt, '2024-03-15');
  assert.equal(archived.reasonEn, 'Archived');
  assert.equal(result.fixtureId, source.id);
  assert.equal(result.fixtureVersion, 'v5');
  assert.equal(result.asOf, '2024-06-30');
  assert.equal(result.isSimulated, true);
  assert.equal(result.disclosure, source.disclosure);
  assert.equal(JSON.stringify({ data, source }), before);
});

test('explicit current or planned attention does not require an existing report or legacy coverage', () => {
  const result = getManagerCoverage('scout', fixture(), synthetic());
  const current = result.records.find(item => item.stage === 'current');
  const planned = result.records.find(item => item.stage === 'planned');
  assert.equal(current.company.name, 'Pine');
  assert.deepEqual(current.reports, []);
  assert.equal(planned.company.name, 'Birch');
  assert.deepEqual(planned.reports, []);
  assert.equal(planned.addedAt, '2024-06-29');
  assert.equal(Object.hasOwn(planned, 'since'), false);
});

test('one company may have different stages under different Managers without crossing reports', () => {
  const source = fixture(), data = synthetic();
  const patient = getManagerCoverage('patient', source, data);
  assert.deepEqual(patient.counts, { current: 1, history: 0, planned: 0 });
  assert.deepEqual(patient.records.map(item => [item.managerId, item.companyId, item.stage]), [['patient', 'cedar', 'current']]);
  assert.equal(patient.records[0].reports[0].document.id, 'cedar-patient');
});

test('connected empty lists and a Manager with no listed companies are distinct from a missing source', () => {
  const source = fixture(), data = synthetic();
  source.records = [];
  const empty = getManagerCoverage('scout', source, data);
  assert.deepEqual(empty.records, []);
  assert.deepEqual(empty.counts, { current: 0, history: 0, planned: 0 });
  assert.equal(empty.total, 0);
  source.records = fixture().records.filter(item => item.managerId === 'patient');
  assert.equal(getManagerCoverage('scout', source, data).total, 0);
  for (const missing of [undefined, null]) assert.throws(() => getManagerCoverage('scout', missing, data), /not connected/);
});

test('invalid or unknown scope is rejected instead of selecting another Manager or company', () => {
  for (const id of [undefined, null, '', ' ', 'unknown']) assert.throws(() => getManagerCoverage(id, fixture(), synthetic()));
  for (const [key, value] of [['managerId', 'unknown'], ['companyId', 'unknown'], ['managerId', ''], ['companyId', ' ']]) {
    const source = fixture();
    source.records[0][key] = value;
    assert.throws(() => getManagerCoverage('scout', source, synthetic()), /identifier|unknown/);
  }
  const ambiguous = synthetic();
  ambiguous.companies.push({ id: 'cedar' });
  assert.throws(() => getManagerCoverage('patient', fixture(), ambiguous), /ambiguous/);
});

test('a company has a single explicit stage per Manager and stage names are validated', () => {
  const duplicate = fixture();
  duplicate.records.push({ ...duplicate.records[0], id: 'duplicate-company' });
  assert.throws(() => getManagerCoverage('scout', duplicate, synthetic()), /only one focus stage/);
  const duplicateId = fixture();
  duplicateId.records[1].id = duplicateId.records[0].id;
  assert.throws(() => getManagerCoverage('scout', duplicateId, synthetic()), /ids.*unique/);
  const stage = fixture();
  stage.records[0].stage = 'published';
  assert.throws(() => getManagerCoverage('scout', stage, synthetic()), /stage must/);
});

test('stage dates are calendar-valid, complete, ordered and bounded by the fixture snapshot', () => {
  const cases = [
    [0, 'since', undefined], [0, 'endedAt', undefined], [0, 'since', '2024-02-30'],
    [0, 'endedAt', '2023-01-01'], [0, 'endedAt', '2024-07-01'],
    [1, 'since', '2024-07-01'], [1, 'endedAt', '2024-05-01'], [1, 'addedAt', '2024-01-01'],
    [2, 'addedAt', undefined], [2, 'addedAt', '2024-07-01'], [2, 'since', '2024-01-01'],
  ];
  for (const [index, key, value] of cases) {
    const source = fixture();
    if (value === undefined) delete source.records[index][key]; else source.records[index][key] = value;
    assert.throws(() => getManagerCoverage('scout', source, synthetic()), /date|since|valid for/, `${index}.${key}=${value}`);
  }
  const invalidSnapshot = fixture();
  invalidSnapshot.asOf = '2024-13-01';
  assert.throws(() => getManagerCoverage('scout', invalidSnapshot, synthetic()), /asOf/);
});

test('invalid metadata and unknown record fields fail without silently repairing the fixture', () => {
  for (const key of ['id', 'version', 'label', 'labelEn', 'disclosure', 'disclosureEn', 'isSimulated']) {
    const source = fixture();
    delete source[key];
    assert.throws(() => getManagerCoverage('scout', source, synthetic()));
  }
  const noReason = fixture();
  noReason.records[0].reasonEn = ' ';
  assert.throws(() => getManagerCoverage('scout', noReason, synthetic()), /reason/);
  const unknown = fixture();
  unknown.records[2].scheduledAt = '2024-07-01';
  assert.throws(() => getManagerCoverage('scout', unknown, synthetic()), /unsupported fields/);
});

test('the named frontend fixture is deeply frozen and independent from the catalog', () => {
  const before = JSON.stringify(catalog);
  assert.equal(managerCoverageFixture.id, 'uteki-manager-focus-ui-2026-09-30');
  assert.equal(managerCoverageFixture.version, 'v1');
  assert.equal(managerCoverageFixture.asOf, '2026-09-30');
  assert.ok(Object.isFrozen(managerCoverageFixture) && Object.isFrozen(managerCoverageFixture.records));
  assert.ok(managerCoverageFixture.records.every(item => Object.isFrozen(item)));
  assert.deepEqual(getManagerCoverage('north', managerCoverageFixture).records.map(item => [item.companyId, item.stage]), [
    ['alphabet', 'current'], ['microsoft', 'history'], ['arista', 'planned'],
  ]);
  assert.deepEqual(getManagerCoverage('field', managerCoverageFixture).records.map(item => [item.companyId, item.stage]), [
    ['nvidia', 'current'], ['alphabet', 'history'], ['eaton', 'planned'],
  ]);
  assert.equal(JSON.stringify(catalog), before);
});
