import test from 'node:test';
import assert from 'node:assert/strict';
import { createManagerViews } from './manager-view.mjs';
import { catalog, getInstitution, getManager, getReport, parseRoute } from './model.mjs';
import { getManagerResearchRows, getManagerExecutionHistory } from './manager-activity.mjs';
import { investmentEventFixture } from './investment-events.mjs';
import { managerCoverageFixture, getManagerCoverage } from './manager-coverage.mjs';

const institution = getInstitution('uteki');
const decode = value => value.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const elements = html => [...html.matchAll(/<([a-zA-Z]+)\b[^>]*>/g)].map(([tag, name]) => ({
  tag: name, raw: tag,
  ...Object.fromEntries([...tag.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, key, value]) => [key, decode(value)])),
}));
const create = (language = 'zh', options = {}) => createManagerViews({
  t: (zh, en) => language === 'en' ? en : zh,
  companyIcon: company => `<span data-company-icon="${company.id}"></span>`,
  institutionContext: institution,
  executionContext: investmentEventFixture,
  coverageContext: managerCoverageFixture,
  ...options,
});
const route = (managerId, view) => ({ managerId, view });
const ids = (html, attribute) => elements(html).filter(item => item[attribute] !== undefined).map(item => item[attribute]);
const reportLinks = html => elements(html).filter(item => item.tag === 'a' && item.href?.includes('view=report&')).map(item => parseRoute(item.href));
const selectedFilter = (html, list) => elements(html).filter(item => item['data-list'] === list && item['aria-pressed'] === 'true').map(item => item['data-filter']);
const pageButton = (html, list, direction) => elements(html).find(item => item.id === `manager-${list}-${direction}`);

test('overview lists six research rows per page without dropping or duplicating scoped records', () => {
  for (const manager of catalog.managers) {
    const expected = getManagerResearchRows(manager.id);
    const pages = Math.ceil(expected.length / 6), seen = [];
    for (let page = 0; page < pages; page += 1) {
      const html = create().main(route(manager.id, 'overview'), { researchPage: page });
      const actual = ids(html, 'data-research-id');
      assert.deepEqual(actual, expected.slice(page * 6, (page + 1) * 6).map(row => row.id));
      assert.ok(actual.length <= 6);
      assert.deepEqual(selectedFilter(html, 'research'), ['all']);
      assert.equal(/\sdisabled(?:\s|>)/.test(pageButton(html, 'research', 'prev').raw), page === 0);
      assert.equal(/\sdisabled(?:\s|>)/.test(pageButton(html, 'research', 'next').raw), page === pages - 1);
      seen.push(...actual);
      for (const link of reportLinks(html)) {
        assert.equal(link.managerId, manager.id);
        assert.equal(getReport(link.companyId, link.reportId, link.version).manager.id, manager.id);
      }
    }
    assert.deepEqual(seen, expected.map(row => row.id));
    assert.equal(new Set(seen).size, seen.length);
  }
});

test('overview filters reflect recorded questions and outputs without empty-company placeholders', () => {
  for (const manager of catalog.managers) for (const filter of ['open', 'published']) {
    const expected = getManagerResearchRows(manager.id, filter);
    const html = create().main(route(manager.id, 'overview'), { researchFilter: filter });
    assert.deepEqual(ids(html, 'data-research-id'), expected.slice(0, 6).map(row => row.id));
    assert.deepEqual(selectedFilter(html, 'research'), [filter]);
    assert.ok(html.includes(`1–${Math.min(expected.length, 6)} / ${expected.length}`));
    if (filter === 'published') assert.ok(ids(html, 'data-research-type').every(type => type === 'report'));
    assert.match(html, /未接入实时任务执行/);
  }
});

test('overview combines explicitly simulated portfolio information and research without borrowing another Agent', () => {
  for (const agent of institution.agents) for (const language of ['zh', 'en']) {
    const html = create(language).main(route(agent.managerId, 'overview'));
    const weights = elements(html).filter(item => item.class === 'manager-weight-item');
    assert.deepEqual(weights.map(item => item['data-company']), [...agent.portfolio.holdings.map(item => item.companyId), 'cash']);
    assert.ok(html.includes(institution.simulation.asOf));
    assert.ok(html.includes(institution.simulation.currency));
    assert.match(html, language === 'en' ? /Illustrative data · Not a live account/ : /模拟数据 · 非实盘/);
    assert.doesNotMatch(html, /NaN|undefined|Infinity/);
  }
});

test('coverage defaults to all with only recorded companies and four counted focus filters', () => {
  for (const manager of catalog.managers) for (const language of ['zh','en']) {
    const context = getManagerCoverage(manager.id, managerCoverageFixture);
    const html = create(language).main(route(manager.id, 'companies'));
    const cards = elements(html).filter(item => item.tag === 'article' && item['data-company']);
    assert.deepEqual(cards.map(item => [item['data-company'],item['data-stage']]), context.records.map(item => [item.companyId,item.stage]));
    assert.deepEqual(ids(html, 'data-company-icon'), context.records.map(item => item.companyId));
    const filters=elements(html).filter(item=>item['data-list']==='coverage'&&item['data-action']==='manager-filter');
    assert.deepEqual(filters.map(item=>item['data-filter']),['all','current','history','planned']);
    assert.deepEqual(selectedFilter(html,'coverage'),['all']);
    assert.ok(cards.length<=6);
    assert.deepEqual(elements(html).filter(item=>item['data-action']==='manager-coverage-detail').map(item=>item['data-company']),context.records.map(item=>item.companyId));
    const reportButtons=elements(html).filter(item=>item['data-action']==='manager-company-reports');
    assert.deepEqual(reportButtons.map(item=>item['data-company']),context.records.filter(item=>item.reports.length).map(item=>item.companyId));
    const unlisted=catalog.companies.filter(company=>!context.records.some(item=>item.companyId===company.id));
    for(const company of unlisted) assert.ok(!ids(html,'data-company').includes(company.id));
    assert.match(html,language==='en'?/Illustrative focus list/:/模拟关注清单/);
  }
});

test('missing focus source is distinct from an explicitly empty focus list and never falls back to catalog companies',()=>{
  const disconnected=create('en',{coverageContext:null}).main(route('north','companies'));
  assert.match(disconnected,/Focus list is not connected/);
  const empty=create('en',{coverageContext:{...managerCoverageFixture,records:[]}}).main(route('north','companies'));
  assert.match(empty,/No explicitly recorded focus companies/);
  assert.equal(ids(empty,'data-company').length,0);
  assert.doesNotMatch(empty,/not connected/);
});

test('report company filters preserve independent report identities and current versions', () => {
  for (const manager of catalog.managers) {
    const context = getManager(manager.id);
    const allowedCompanies=[...new Set(context.reports.map(item=>item.company.id))];
    const allHtml=create().main(route(manager.id,'reports'));
    assert.deepEqual(elements(allHtml).filter(item=>item['data-action']==='manager-filter'&&item['data-list']==='reports').map(item=>item['data-filter']),['all',...allowedCompanies]);
    for (const companyId of ['all', ...new Set(context.reports.map(item => item.company.id))]) {
      const expected = context.reports.filter(item => companyId === 'all' || item.company.id === companyId)
        .sort((a, b) => b.report.publishedAt.localeCompare(a.report.publishedAt));
      const html = create().main(route(manager.id, 'reports'), { reportCompany: companyId });
      assert.deepEqual(selectedFilter(html, 'reports'), [companyId]);
      assert.deepEqual(reportLinks(html), expected.map(item => ({
        managerId: manager.id, companyId: item.company.id, view: 'report', reportId: item.document.id, version: item.report.version,
      })));
      assert.equal(new Set(reportLinks(html).map(item => item.reportId)).size, expected.length);
      if (!expected.length) assert.match(html, /尚无正式报告/);
      assert.ok(html.includes(`${expected.length} 份独立产出`));
    }
  }
});

test('activity displays eight events per page and supports exact buy, sell and publication filters', () => {
  for (const manager of catalog.managers) for (const kind of ['all', 'buy', 'sell', 'report']) {
    const expected = getManagerExecutionHistory({ managerId: manager.id, kind }).events;
    const pages = Math.ceil(expected.length / 8), seen = [];
    for (let page = 0; page < pages; page += 1) {
      const html = create().main(route(manager.id, 'activity'), { activityKind: kind, activityPage: page });
      const actual = ids(html, 'data-execution-id');
      assert.deepEqual(actual, expected.slice(page * 8, (page + 1) * 8).map(event => event.id));
      assert.ok(actual.length <= 8);
      assert.deepEqual(selectedFilter(html, 'activity'), [kind]);
      assert.equal(/\sdisabled(?:\s|>)/.test(pageButton(html, 'activity', 'prev').raw), page === 0);
      assert.equal(/\sdisabled(?:\s|>)/.test(pageButton(html, 'activity', 'next').raw), page === pages - 1);
      assert.match(html, /模拟事件 · 非实盘/);
      assert.match(html, /未提供成交价和数量/);
      const reports = expected.slice(page * 8, (page + 1) * 8).filter(event => event.kind === 'report');
      assert.deepEqual(reportLinks(html), reports.map(event => event.links[0].route));
      seen.push(...actual);
    }
    assert.deepEqual(seen, expected.map(event => event.id));
    assert.equal(new Set(seen).size, seen.length);
  }
});

test('legacy holdings route is an activity-history alias, with unchanged scoped filtering', () => {
  for (const manager of catalog.managers) {
    const state = { activityKind: 'report', activityPage: 0 };
    assert.equal(create().main(route(manager.id, 'holdings'), state), create().main(route(manager.id, 'activity'), state));
  }
});

test('missing portfolio and execution contexts retain distinct explicit gaps instead of implicit fixture connections', () => {
  for (const language of ['zh', 'en']) {
    const renderer = create(language, { institutionContext: null, executionContext: null });
    const overview = renderer.main(route('north', 'overview'));
    assert.match(overview, language === 'en' ? /Returns and holdings are not connected/ : /收益与持仓未接入/);
    assert.equal(ids(overview, 'data-research-id').length, 6, 'research remains available without an account');
    const activity = renderer.main(route('north', 'activity'));
    assert.match(activity, language === 'en' ? /Activity history is not connected/ : /操作历史未接入/);
    assert.equal(ids(activity, 'data-execution-id').length, 0);
    assert.equal(elements(activity).some(item => item['data-action'] === 'manager-page'), false);
  }
});

test('invalid filters, pages, company scope, Manager and reader routes are rejected', () => {
  const renderer = create();
  for (const page of [-1, 0.5, '1', NaN, Infinity, 999]) {
    assert.throws(() => renderer.main(route('north', 'companies'), { coveragePage: page }), /page/);
    assert.throws(() => renderer.main(route('north', 'overview'), { researchPage: page }), /page/);
    assert.throws(() => renderer.main(route('north', 'reports'), { reportPage: page }), /page/);
    assert.throws(() => renderer.main(route('north', 'activity'), { activityPage: page }), /page/);
  }
  assert.throws(() => renderer.main(route('north', 'companies'), { coverageStage: 'unknown' }), /filter/);
  assert.throws(() => renderer.main(route('north', 'reports'), { reportKind: 'unknown' }), /kind/);
  assert.throws(() => renderer.main(route('north', 'reports'), { reportQuery: 1 }), /query/);
  assert.throws(() => renderer.main(route('north', 'overview'), { researchFilter: 'running' }), /filter/);
  assert.throws(() => renderer.main(route('north', 'activity'), { activityKind: 'trade' }), /kind/);
  assert.throws(() => renderer.main(route('north', 'reports'), { reportCompany: 'unknown' }), /has no reports by this Manager/);
  assert.throws(() => renderer.main(route('north', 'reports'), { reportCompany: '' }), /filter/);
  assert.throws(() => renderer.main(route('north', 'reports'), { reportCompany: 'arista' }), /has no reports by this Manager/);
  assert.throws(() => renderer.main(route('unknown', 'overview')), /unknown/);
  assert.throws(() => renderer.main(route('north', 'report')), /shared reader/);
});


test('coverage stage selection retains report-independent future cards and scoped full-detail reading', () => {
  for (const manager of catalog.managers) for (const stage of ['current','history','planned']) {
    const expected=getManagerCoverage(manager.id,managerCoverageFixture).records.filter(item=>item.stage===stage);
    const renderer=create(),html=renderer.main(route(manager.id,'companies'),{coverageStage:stage});
    assert.deepEqual(elements(html).filter(item=>item.tag==='article').map(item=>item['data-company']),expected.map(item=>item.companyId));
    assert.deepEqual(selectedFilter(html,'coverage'),[stage]);
    for(const item of expected){
      const detail=renderer.coverageDetail(manager.id,item.companyId);
      assert.ok(detail.body.includes(item.reason));
      assert.ok(detail.body.includes(item.company.name));
      for(const link of reportLinks(detail.body)) assert.equal(link.managerId,manager.id);
      if(!item.reports.length){
        assert.equal(elements(html).some(element=>element['data-action']==='manager-company-reports'&&element['data-company']===item.companyId),false);
        assert.match(detail.body,/尚无报告/);
      }
    }
  }
  assert.throws(()=>create().coverageDetail('north','eaton'),/no explicitly recorded focus/);
  assert.throws(()=>create().coverageDetail('unknown','alphabet'),/unknown/);
});

test('report directory company icons, title query and kind filters cooperate and distinguish no matches',()=>{
  const renderer=create();
  const html=renderer.main(route('north','reports'),{reportCompany:'alphabet',reportKind:'topic',reportQuery:'云业务'});
  assert.deepEqual(reportLinks(html).map(item=>item.reportId),['alpha-north-cloud']);
  assert.deepEqual(selectedFilter(html,'report-kind'),['topic']);
  assert.deepEqual(selectedFilter(html,'reports'),['alphabet']);
  assert.equal(elements(html).find(item=>item.id==='manager-report-query').value,'云业务');
  assert.ok(ids(html,'data-company-icon').includes('alphabet'));
  assert.equal(elements(html).filter(item=>item['data-action']==='manager-report-clear').length,1);
  const noResults=renderer.main(route('north','reports'),{reportCompany:'alphabet',reportKind:'main',reportQuery:'不存在的标题'});
  assert.match(noResults,/没有匹配的报告/);
  assert.match(noResults,/Alphabet · 主报告 · “不存在的标题”/);
  assert.equal(reportLinks(noResults).length,0);
  assert.equal(elements(noResults).filter(item=>item['data-action']==='manager-report-clear').length,1);
  const en=create('en').main(route('field','reports'),{reportKind:'main',reportQuery:'does not exist'});
  assert.match(en,/No matching reports/);
  assert.match(en,/Clear filters/);
});


test('Manager directory displays the selected edition title and preserves the original title language', () => {
  const item=getManager('north').reports.find(item=>item.document.id==='alpha-north-main');
  for(const language of ['zh','en']) {
    const html=create(language).main(route('north','reports'),{reportQuery:'回报需要更多时间'});
    assert.deepEqual(reportLinks(html).map(item=>item.reportId),['alpha-north-main']);
    assert.ok(html.includes(`<span lang="zh-CN">${item.report.title}</span>`));
    if(language==='en') assert.match(html,/Report titles are shown in their original language/);
  }
});
