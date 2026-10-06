import test from 'node:test';
import assert from 'node:assert/strict';
import { catalog, getManager, getCompany } from './model.mjs';
import { getReportDirectory, paginateRecords } from './report-directory.mjs';

function synthetic() {
  const document = (id, companyId, managerId, title, kind, publishedAt) => ({
    id, companyId, managerId, title, kind, currentVersion: 'v2',
    versions: [{ version: 'v1', publishedAt: '2020-01-01', sections: [] }, { version: 'v2', publishedAt, sections: [] }],
  });
  return {
    companies: [{ id: 'cedar', name: 'Cedar' }, { id: 'pine', name: 'Pine' }, { id: 'birch', name: 'Birch' }],
    managers: [{ id: 'patient', name: 'Patient' }, { id: 'scout', name: 'Scout' }],
    coverage: [], evidence: [], events: [],
    reports: [
      document('cedar-scout', 'cedar', 'scout', 'Cedar economics', 'main', '2025-03-01'),
      document('pine-scout', 'pine', 'scout', 'Pine demand', 'topic', '2025-02-01'),
      ...Array.from({ length: 11 }, (_, index) => document(`cedar-${String(index).padStart(2, '0')}`, 'cedar', 'patient', `Cedar quality ${index}`, index % 2 ? 'topic' : 'main', index < 3 ? '2025-03-01' : '2025-02-01')),
    ],
  };
}

test('the named fixture has one current-version entry per scoped document and counterpart counts', () => {
  for (const manager of catalog.managers) {
    const expected = getManager(manager.id).reports;
    const result = getReportDirectory({ managerId: manager.id });
    assert.equal(result.sourceTotal, expected.length);
    assert.equal(result.counterparts.reduce((sum, item) => sum + item.count, 0), result.sourceTotal);
    assert.equal(new Set(result.rows.map(item => item.document.id)).size, expected.length);
    assert.ok(result.rows.every(item => item.manager.id === manager.id && item.report.version === item.document.currentVersion));
  }
  for (const company of catalog.companies) {
    const result = getReportDirectory({ companyId: company.id });
    assert.equal(result.total, getCompany(company.id).reports.length);
    assert.ok(result.rows.every(item => item.company.id === company.id));
    if (!result.total) assert.deepEqual(result.counterparts, [], 'no authored reports means no invented author coverage');
  }
});

test('synthetic data combines counterpart, kind and title conditions without cross-company or cross-author matches', () => {
  const data = synthetic();
  const manager = getReportDirectory({ managerId: 'scout', counterpartId: 'pine', kind: 'topic', query: 'ＰＩＮＥ' }, data);
  assert.deepEqual(manager.rows.map(item => item.document.id), ['pine-scout']);
  assert.deepEqual(manager.kinds, { all: 1, main: 0, topic: 1 });
  const company = getReportDirectory({ companyId: 'cedar', counterpartId: 'patient', kind: 'topic', query: ' QUALITY ' }, data);
  assert.equal(company.total, 5);
  assert.ok(company.rows.every(item => item.document.companyId === 'cedar' && item.manager.id === 'patient' && item.document.kind === 'topic'));
  assert.equal(company.filter.query, 'QUALITY');
  assert.equal(getReportDirectory({ companyId: 'cedar', counterpartId: 'scout', query: 'Pine' }, data).total, 0);
  assert.equal(getReportDirectory({ managerId: 'patient', kind: 'topic', query: 'economics' }, data).total, 0);
});

test('eight-item report pages preserve stable date plus report ID order and never mutate the dataset', () => {
  const data = synthetic(), before = JSON.stringify(data), seen = [];
  for (const page of [0, 1]) {
    const result = getReportDirectory({ managerId: 'patient', page }, data);
    assert.equal(result.pages, 2);
    assert.equal(result.size, 8);
    assert.ok(result.rows.length <= 8);
    seen.push(...result.rows.map(item => item.document.id));
  }
  assert.deepEqual(seen, Array.from({ length: 11 }, (_, index) => `cedar-${String(index).padStart(2, '0')}`));
  assert.equal(new Set(seen).size, 11);
  assert.equal(JSON.stringify(data), before);
  assert.throws(() => getReportDirectory({ managerId: 'patient', page: 2 }, data), /page/);
});

test('no search matches differs from a connected empty directory and both offer a valid empty first page', () => {
  const data = synthetic();
  const search = getReportDirectory({ managerId: 'scout', query: 'missing' }, data);
  assert.equal(search.total, 0);
  assert.equal(search.sourceTotal, 2);
  assert.equal(search.filtered, true);
  assert.equal(search.pages, 1);
  const empty = getReportDirectory({ companyId: 'birch' }, data);
  assert.equal(empty.sourceTotal, 0);
  assert.equal(empty.filtered, false);
  assert.deepEqual(empty.counterparts, []);
});

test('missing, conflicting and unsupported scope or filters fail rather than choosing another entity', () => {
  const data = synthetic();
  for (const options of [undefined, null, {}, { managerId: '' }, { companyId: 'unknown' }, { companyId: 'cedar', managerId: 'scout' }, { managerId: 'scout', kind: 'research' }, { managerId: 'scout', query: 12 }, { managerId: 'scout', counterpartId: '' }, { companyId: 'cedar', counterpartId: 'unknown' }, { managerId: 'patient', counterpartId: 'pine' }, { managerId: 'scout', page: '0' }, { managerId: 'scout', page: -1 }, { managerId: 'scout', source: 'implicit' }]) {
    assert.throws(() => getReportDirectory(options, data));
  }
  assert.throws(() => getReportDirectory({ managerId: 'north' }, data), /unknown/);
  data.reports.find(item => item.id === 'pine-scout').kind = 'unknown';
  assert.throws(() => getReportDirectory({ managerId: 'scout' }, data), /kind/);
});

test('the six-item coverage paginator keeps independent page boundaries and rejects stale pages', () => {
  const records = Array.from({ length: 13 }, (_, index) => ({ id: index }));
  assert.deepEqual([0, 1, 2].flatMap(page => paginateRecords(records, page, 6).rows), records);
  assert.deepEqual(paginateRecords([], 0, 6), { rows: [], page: 0, pages: 1, total: 0, size: 6 });
  for (const page of [-1, 0.5, '1', NaN, Infinity, 3]) assert.throws(() => paginateRecords(records, page, 6), /page/);
  assert.throws(() => paginateRecords(records.slice(0, 2), 1, 6), /page/);
});


test('title search covers the selected edition and document title, including available translations only', () => {
  const data=synthetic(), document=data.reports.find(item=>item.id==='cedar-scout');
  document.titleEn='Cedar company research';
  document.versions[0].title='Superseded view';
  document.versions[1].title='需求仍在增长，回报有待验证';
  document.versions[1].titleEn='Demand ahead of returns';
  for(const query of ['需求仍在增长','RETURNS','company research','economics']) {
    const result=getReportDirectory({companyId:'cedar',counterpartId:'scout',query},data);
    assert.deepEqual(result.rows.map(item=>item.document.id),['cedar-scout']);
    assert.equal(result.rows[0].report.version,'v2');
  }
  assert.equal(getReportDirectory({managerId:'scout',query:'Superseded view'},data).total,0,'old edition titles are not the current report result');
  assert.equal(getReportDirectory({companyId:'pine',query:'returns'},data).total,0,'a translated title does not cross company scope');
});
