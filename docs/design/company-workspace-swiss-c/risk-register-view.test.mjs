import test from 'node:test';
import assert from 'node:assert/strict';
import { createRiskRegisterViews } from './risk-register-view.mjs';
import { riskRegisterFixture, getManagerRisks, getFeaturedRiskId } from './risk-register.mjs';
import { portfolioDecisionFixture, getDecision } from './portfolio-decisions.mjs';
import { catalog, getEvidence, parseRoute } from './model.mjs';

const decode = value => value.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
const elements = html => [...html.matchAll(/<([a-zA-Z]+)\b[^>]*>/g)].map(([raw, tag]) => ({ tag, raw, ...Object.fromEntries([...raw.matchAll(/([\w:-]+)="([^"]*)"/g)].map(([, key, value]) => [key, decode(value)])) }));
const create = language => createRiskRegisterViews({ t: (zh, en) => language === 'en' ? en : zh, companyIcon: company => `<span class="company-icon" data-company-icon="${company.id}"></span>` });
const route = risk => ({ managerId: risk.managerId, view: 'risks', riskId: risk.id });
const risks = riskRegisterFixture.risks;

test('Manager registers show only their authored issues, order by update and use explicit featured IDs', () => {
  for (const manager of catalog.managers) {
    const expected = getManagerRisks(manager.id);
    const html = create('zh').main({ managerId: manager.id, view: 'risks' });
    const nodes = elements(html);
    assert.equal(nodes.find(item => item.id === 'risk-register')['data-risk'], getFeaturedRiskId(manager.id));
    const items = nodes.filter(item => item.id?.startsWith('risk-select-'));
    assert.deepEqual(items.map(item => parseRoute(item.href).riskId), expected.map(item => item.id));
    assert.ok(items.every(item => parseRoute(item.href).managerId === manager.id));
    assert.equal(items.filter(item => item['aria-current'] === 'page').length, 1);
    assert.match(html, /Risk Manager/);
    assert.match(html, /虚构样本/);
    assert.match(html, new RegExp(riskRegisterFixture.asOf));
  }
});

test('status filters show independent totals and retain selection only when it belongs to the new filter', () => {
  for (const risk of risks) {
    const html = create('en').main(route(risk));
    const nodes = elements(html), records = getManagerRisks(risk.managerId);
    for (const filter of ['all', 'needs_review', 'monitoring', 'resolved']) {
      const link = nodes.find(item => item.id === `risk-filter-${filter}`);
      const parsed = parseRoute(link.href);
      assert.equal(parsed.managerId, risk.managerId);
      assert.equal(parsed.riskFilter, filter);
      assert.equal(parsed.riskId, filter === 'all' || filter === risk.status ? risk.id : undefined);
      const expected = filter === 'all' ? records.length : records.filter(item => item.status === filter).length;
      assert.match(html, new RegExp(`data-risk-count="${filter}">${expected}</span>`));
    }
  }
  const filtered = create('en').main({ managerId: 'north', view: 'risks', riskFilter: 'monitoring' });
  const nodes = elements(filtered);
  assert.equal(nodes.find(item => item.id === 'risk-register')['data-risk'], '');
  assert.equal(nodes.filter(item => item.id?.startsWith('risk-select-')).length, 2);
  assert.match(filtered, /Select a risk to continue/);
  assert.equal(nodes.filter(item => item.class?.includes('risk-list-link') && item['aria-current'] === 'page').length, 0);
});

test('empty filtered results keep the full status counts, scope and clear-filter link', () => {
  const html = create('zh').main({ managerId: 'field', view: 'risks', riskFilter: 'resolved' });
  assert.match(html, /该状态下暂无记录/);
  assert.match(html, /其他状态的风险仍保留在清单中/);
  assert.doesNotMatch(html, /组合没有风险/);
  const link = elements(html).find(item => item.id === 'risk-filter-clear');
  assert.deepEqual(parseRoute(link.href), { managerId: 'field', view: 'risks', riskFilter: 'all' });
  assert.match(html, /data-risk-count="all">1<\/span>/);
  assert.match(html, /data-risk-count="monitoring">1<\/span>/);
});

test('evidence update links preserve exact author, company, report version, section and evidence identity', () => {
  for (const risk of risks) {
    const html = create('en').main(route(risk));
    const nodes = elements(html), links = nodes.filter(item => item.id?.startsWith('risk-source-'));
    const observations = [...risk.observations].sort((a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id));
    const references = observations.flatMap(item => item.sources);
    assert.deepEqual(nodes.filter(item => item['data-observation-id']).map(item => item['data-observation-id']), observations.map(item => item.id));
    assert.equal(links.length, references.length);
    for (const [index, link] of links.entries()) {
      const reference = references[index];
      assert.deepEqual(parseRoute(link.href), { managerId: risk.managerId, view: 'report', companyId: reference.companyId, reportId: reference.reportId, version: reference.version, sectionId: reference.sectionId });
      assert.equal(link['data-risk-evidence'], reference.evidenceId);
      const { evidence } = getEvidence(reference.companyId, reference.reportId, reference.version, reference.evidenceId);
      assert.ok(nodes.some(item => item['data-evidence-id'] === reference.evidenceId && item['data-source-availability'] === evidence.availability));
      assert.ok(html.includes(evidence.sourceTitle));
      if (evidence.availability === 'unavailable') {
        assert.match(html, /Source unavailable/);
        assert.doesNotMatch(html, /<blockquote|download=/);
        if (evidence.quote) assert.ok(!html.includes(evidence.quote));
      }
    }
  }
});

test('one ongoing issue can retain two dated decision reviews without double-counting the risk', () => {
  const risk = risks.find(item => item.managerId === 'field');
  const html = create('en').main(route(risk)), nodes = elements(html);
  const reviews = nodes.filter(item => item['data-review-risk-id']);
  assert.equal(reviews.length, risk.decisionReviews.length);
  assert.equal(reviews.length, 2);
  assert.equal(nodes.find(item => item.id === 'risk-register')['data-risk'], risk.id);
  assert.match(html, /data-risk-count="monitoring">1<\/span>/);
  assert.deepEqual(reviews.map(item => item['data-decision-id']), ['field-20260930-hold', 'field-20260928-allocation']);
  for (const link of nodes.filter(item => item.id?.startsWith('risk-decision-'))) {
    const parsed = parseRoute(link.href);
    assert.equal(parsed.managerId, risk.managerId);
    assert.equal(parsed.decisionTab, 'risk');
    assert.ok(risk.decisionReviews.some(item => item.decisionId === parsed.decisionId));
  }
});

test('current risk state is distinct from a PM response and allocation comparisons use authored values', () => {
  for (const risk of risks) {
    const html = create('en').main(route(risk));
    const articles = [...html.matchAll(/<article class="risk-decision-review[^>]*>[\s\S]*?<\/article>/g)].map(([value]) => value);
    assert.match(html, /A response does not resolve a risk/);
    assert.match(html, new RegExp(`data-risk-status="${risk.status}"`));
    for (const article of articles) {
      const nodes = elements(article), reviewNode = nodes[0];
      const decision = getDecision(risk.managerId, reviewNode['data-decision-id']);
      const review = decision.risks.find(item => item.id === reviewNode['data-review-risk-id']);
      assert.equal(reviewNode['data-response-status'], review.responseStatus);
      assert.ok(article.includes(review.opinionEn));
      assert.ok(article.includes(review.responseEn));
      assert.ok(article.includes(review.followUpEn));
      const changed = decision.allocations.filter(row => row.draftPct !== row.targetPct);
      const expected = changed.length ? changed : decision.allocations;
      assert.deepEqual(nodes.filter(item => item['data-review-asset']).map(item => item['data-review-asset']), expected.map(item => item.assetId));
      assert.deepEqual(nodes.filter(item => item['data-draft-pct']).map(item => Number(item['data-draft-pct'])), expected.map(item => item.draftPct));
      assert.deepEqual(nodes.filter(item => item['data-target-pct']).map(item => Number(item['data-target-pct'])), expected.map(item => item.targetPct));
      assert.match(article, decision.execution.status === 'pending' ? /Target not executed/ : /No trade required/);
      assert.match(article, /not execution records/);
    }
  }
});

test('an accepted rebalance draft does not become a maintain decision when draft equals target', () => {
  const risk = risks.find(item => item.id === 'north-shared-growth');
  const decision = portfolioDecisionFixture.decisions.find(item => item.id === risk.decisionReviews[0].decisionId);
  const allocations = decision.allocations;
  assert.equal(decision.kind, 'rebalance');
  assert.ok(allocations.some(row => row.beforePct !== row.targetPct));
  try {
    decision.allocations = allocations.map(row => ({ ...row, draftPct: row.targetPct }));
    const html = create('en').main(route(risk));
    assert.match(html, /The final target retains the draft allocation/);
    assert.doesNotMatch(html, /This decision maintains the allocation|View maintained target weights/);
    assert.match(html, /View retained draft targets/);
  } finally {
    decision.allocations = allocations;
  }
});

test('summary reports registered issue counts, links the featured risk and states its follow-up condition', () => {
  for (const manager of catalog.managers) {
    const html = create('zh').summary(manager.id), nodes = elements(html);
    const records = getManagerRisks(manager.id), featured = records.find(item => item.id === getFeaturedRiskId(manager.id));
    for (const link of nodes.filter(item => item.tag === 'a')) {
      const parsed = parseRoute(link.href);
      assert.equal(parsed.managerId, manager.id);
      assert.equal(parsed.view, 'risks');
      assert.equal(parsed.riskId, featured.id);
    }
    assert.ok(html.includes(featured.title));
    assert.ok(html.includes(featured.reviewTrigger));
    assert.match(html, /Risk Manager/);
    assert.match(html, /虚构样本/);
    assert.match(html, new RegExp(`data-status-count="monitoring">持续观察 <strong>${records.filter(item => item.status === 'monitoring').length}</strong>`));
  }
});

test('unknown or conflicting route scope fails without selecting an alternate issue', () => {
  for (const input of [
    { view: 'risks' }, { managerId: 'unknown', view: 'risks' },
    { managerId: 'north', view: 'overview' }, { managerId: 'north', companyId: 'alphabet', view: 'risks' },
    { managerId: 'north', view: 'risks', riskId: 'missing' },
    { managerId: 'north', view: 'risks', riskId: 'field-delivery-chain' },
    { managerId: 'north', view: 'risks', riskFilter: 'unknown' },
    { managerId: 'north', view: 'risks', riskId: 'north-shared-growth', riskFilter: 'resolved' },
  ]) assert.throws(() => create('en').main(input));
  assert.throws(() => create('en').summary('unknown'));
});

test('both languages render all registered states without changing research, decisions or risk records', () => {
  const before = JSON.stringify({ catalog, portfolioDecisionFixture, riskRegisterFixture });
  for (const language of ['zh', 'en']) for (const risk of risks) {
    const html = create(language).main(route(risk));
    assert.doesNotMatch(html, /undefined|NaN|Infinity/);
    assert.ok(html.includes(language === 'en' ? risk.reviewTriggerEn : risk.reviewTrigger));
    assert.ok(html.includes(language === 'en' ? risk.summaryEn : risk.summary));
    assert.ok(html.includes(language === 'en' ? risk.impactEn : risk.impact));
  }
  assert.equal(JSON.stringify({ catalog, portfolioDecisionFixture, riskRegisterFixture }), before);
});

test('missing registered records state an explicit gap and never infer zero portfolio risk', () => {
  const originalRisks = riskRegisterFixture.risks, originalFeatured = riskRegisterFixture.featuredByManager.field;
  try {
    riskRegisterFixture.risks = originalRisks.filter(item => item.managerId !== 'field');
    riskRegisterFixture.featuredByManager.field = null;
    const html = create('en').main({ managerId: 'field', view: 'risks' });
    assert.match(html, /No risk records available/);
    assert.match(html, /does not establish that the portfolio has no risk/);
    assert.equal(elements(html).filter(item => item.id?.startsWith('risk-select-')).length, 0);
    const summary = create('en').summary('field');
    assert.match(summary, /No records; risk is not established as zero/);
    assert.deepEqual(parseRoute(elements(summary).find(item => item.id === 'risk-summary-open-field').href), { managerId: 'field', view: 'risks', riskFilter: 'all' });
  } finally {
    riskRegisterFixture.risks = originalRisks;
    riskRegisterFixture.featuredByManager.field = originalFeatured;
  }
});

test('an explicitly closed sample displays dated resolution evidence separately from historic responses', () => {
  const original = riskRegisterFixture.risks;
  const risk = original.find(item => item.id === 'field-delivery-chain');
  const resolved = { ...risk, status: 'resolved', resolution: { date: risk.updatedAt, reason: '测试用具名结束说明', reasonEn: 'Named test closure explanation', sources: risk.observations.at(-1).sources } };
  try {
    riskRegisterFixture.risks = original.map(item => item.id === resolved.id ? resolved : item);
    const html = create('en').main({ ...route(resolved), riskFilter: 'resolved' });
    assert.match(html, /Closure record/);
    assert.match(html, /Named test closure explanation/);
    assert.match(html, /Original review condition/);
    const nodes = elements(html);
    assert.equal(nodes.filter(item => item['data-response-status'] === 'responded').length, 2);
    assert.equal(nodes.filter(item => item.id?.startsWith(`risk-source-${risk.id}-resolution-`)).length, 1);
    assert.match(html, /data-risk-count="resolved">1<\/span>/);
    assert.match(html, /data-risk-count="monitoring">0<\/span>/);
  } finally {
    riskRegisterFixture.risks = original;
  }
});
