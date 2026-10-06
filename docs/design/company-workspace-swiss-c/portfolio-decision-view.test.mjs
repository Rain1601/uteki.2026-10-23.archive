import test from 'node:test';
import assert from 'node:assert/strict';
import { createPortfolioDecisionViews } from './portfolio-decision-view.mjs';
import { portfolioDecisionFixture, getManagerDecisions, getFeaturedDecisionId } from './portfolio-decisions.mjs';
import { catalog, getReport, parseRoute } from './model.mjs';

const decode = value => value.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const elements = html => [...html.matchAll(/<([a-zA-Z]+)\b[^>]*>/g)].map(([raw, tag]) => ({
  tag, raw, ...Object.fromEntries([...raw.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, key, value]) => [key, decode(value)])),
}));
const create = language => createPortfolioDecisionViews({
  t: (zh, en) => language === 'en' ? en : zh,
  companyIcon: company => `<span class="company-icon" data-company-icon="${company.id}"></span>`,
});
const route = (record, tab = 'allocation') => ({ managerId: record.managerId, view: 'decisions', decisionId: record.id, decisionTab: tab });

test('each Manager decision directory is scoped, chronological and explicitly featured on first entry', () => {
  for (const manager of catalog.managers) {
    const records = getManagerDecisions(manager.id);
    const html = create('zh').main({ managerId: manager.id, view: 'decisions' });
    const nodes = elements(html);
    const links = nodes.filter(item => item.id?.startsWith('decision-select-'));
    assert.deepEqual(links.map(item => parseRoute(item.href).decisionId), records.map(record => record.id));
    assert.ok(links.every(item => parseRoute(item.href).managerId === manager.id));
    assert.equal(links.find(item => item['aria-current'] === 'page').id, `decision-select-${getFeaturedDecisionId(manager.id)}`);
    assert.equal(nodes.find(item => item.id === 'portfolio-decisions')['data-decision'], getFeaturedDecisionId(manager.id));
    assert.equal(nodes.find(item => item.id === 'portfolio-decisions')['data-simulated'], 'true');
  }
});

test('explicit selected decision and tab survive rendering without selecting a newer decision', () => {
  for (const record of portfolioDecisionFixture.decisions) for (const tab of ['allocation', 'research', 'risk']) {
    const nodes = elements(create('zh').main(route(record, tab)));
    const workspace = nodes.find(item => item.id === 'portfolio-decisions');
    assert.equal(workspace['data-decision'], record.id);
    assert.equal(workspace['data-decision-tab'], tab);
    assert.equal(nodes.find(item => item.id?.startsWith('decision-tab-') && item['aria-current'] === 'page').id, `decision-tab-${tab}`);
    for (const link of nodes.filter(item => item.id?.startsWith('decision-tab-'))) {
      const target = parseRoute(link.href);
      assert.equal(target.managerId, record.managerId);
      assert.equal(target.decisionId, record.id);
    }
  }
});

test('allocation columns preserve authored before/target weights and distinguish pending from executed holdings', () => {
  for (const record of portfolioDecisionFixture.decisions) for (const language of ['zh', 'en']) {
    const html = create(language).main(route(record));
    const nodes = elements(html);
    assert.deepEqual(nodes.filter(item => item['data-decision-asset']).map(item => item['data-decision-asset']), record.allocations.map(row => row.assetId));
    assert.deepEqual(nodes.filter(item => item['data-before-pct']).map(item => Number(item['data-before-pct'])), record.allocations.map(row => row.beforePct));
    assert.deepEqual(nodes.filter(item => item['data-target-pct']).map(item => Number(item['data-target-pct'])), record.allocations.map(row => row.targetPct));
    assert.equal(nodes.find(item => item['data-execution-status'])['data-execution-status'], record.execution.status);
    assert.ok(html.includes(language === 'en' ? record.execution.summaryEn : record.execution.summary));
    assert.match(html, language === 'en' ? /not executed holdings/ : /不是已成交持仓/);
    assert.equal(nodes.some(item => item.tag === 'details'), record.allocations.some(row => row.draftPct !== row.targetPct));
    assert.ok(nodes.filter(item => item.tag === 'th').some(item => item.scope === 'col'));
  }
});

test('research references open only the exact authored company, Manager, report and version', () => {
  for (const record of portfolioDecisionFixture.decisions) {
    const html = create('en').main(route(record, 'research'));
    const links = elements(html).filter(item => item.id?.startsWith('decision-report-'));
    assert.equal(links.length, record.reports.length);
    for (const [index, item] of links.entries()) {
      const actual = parseRoute(item.href), expected = record.reports[index];
      assert.deepEqual(actual, { managerId: record.managerId, view: 'report', companyId: expected.companyId, reportId: expected.reportId, version: expected.version });
      assert.equal(getReport(actual.companyId, actual.reportId, actual.version).manager.id, record.managerId);
      assert.ok(html.includes(expected.noteEn));
    }
    for (const row of record.allocations.filter(row => row.assetId !== 'cash' && !record.reports.some(reference => reference.companyId === row.assetId))) {
      assert.ok(html.includes(row.reasonEn), `Missing research gap for ${record.id}/${row.assetId}`);
    }
  }
});

test('each risk opinion and PM response stays together and a response remains an open monitoring state', () => {
  for (const record of portfolioDecisionFixture.decisions) for (const language of ['zh', 'en']) {
    const html = create(language).main(route(record, 'risk'));
    const articles = [...html.matchAll(/<article class="decision-risk-item"[^>]*>[\s\S]*?<\/article>/g)].map(([article]) => article);
    assert.equal(articles.length, record.risks.length);
    for (const [index, article] of articles.entries()) {
      const expected = record.risks[index], attrs = elements(article)[0];
      assert.equal(attrs['data-risk-id'], expected.id);
      assert.equal(attrs['data-risk-status'], 'monitoring');
      assert.equal(attrs['data-response-status'], 'responded');
      assert.ok(article.includes(language === 'en' ? expected.opinionEn : expected.opinion));
      assert.ok(article.includes(language === 'en' ? expected.responseEn : expected.response));
      assert.ok(article.includes(language === 'en' ? expected.followUpEn : expected.followUp));
    }
    assert.match(html, language === 'en' ? /risk remains under monitoring/ : /风险仍需持续观察/);
  }
});

test('summary links use explicitly featured decisions and keep risk separate from execution status', () => {
  for (const manager of catalog.managers) {
    const html = create('en').summary(manager.id), nodes = elements(html);
    const links = nodes.filter(item => item.tag === 'a');
    assert.equal(links.length, 2);
    assert.deepEqual(links.map(item => parseRoute(item.href).decisionTab), ['allocation', 'risk']);
    assert.ok(links.every(item => parseRoute(item.href).decisionId === getFeaturedDecisionId(manager.id)));
    assert.match(html, /Fictional sample/);
  }
});

test('missing or cross-Manager scope, invalid view and invalid tabs fail without alternate content', () => {
  const view = create('en'), north = portfolioDecisionFixture.decisions.find(item => item.managerId === 'north');
  for (const input of [
    { view: 'decisions' }, { managerId: 'unknown', view: 'decisions' },
    { managerId: 'north', view: 'overview' },
    { managerId: 'north', companyId: 'alphabet', view: 'decisions' },
    { managerId: 'north', view: 'decisions', decisionId: 'missing' },
    { managerId: 'field', view: 'decisions', decisionId: north.id },
    { ...route(north), decisionTab: 'unknown' },
  ]) assert.throws(() => view.main(input));
  assert.throws(() => view.summary('unknown'));
});

test('rendering both languages and all sections leaves the decision fixture and research catalog unchanged', () => {
  const before = JSON.stringify({ fixture: portfolioDecisionFixture, catalog });
  for (const record of portfolioDecisionFixture.decisions) for (const language of ['zh', 'en']) for (const tab of ['allocation', 'research', 'risk']) {
    assert.doesNotMatch(create(language).main(route(record, tab)), /undefined|NaN|Infinity/);
  }
  assert.equal(JSON.stringify({ fixture: portfolioDecisionFixture, catalog }), before);
});
