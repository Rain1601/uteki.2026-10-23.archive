import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { research, findCase, findReport } from './research.mjs';
import { createPersonalStore, parseRoute, formatRoute, caseKey } from './reader-state.mjs';
import { resolveContext, caseEvents, reportRoute, comparisonRoute, evidenceReturnRoute } from './reader-model.mjs';
import { shell, reportView, compareView, evidenceView, changesView, escapeHTML, errorView } from './reader-view.mjs';

const registry = JSON.parse(readFileSync(new URL('./assets/companies/registry.json', import.meta.url), 'utf8'));
const state = createPersonalStore({ getItem: () => null, setItem() {} }).get();
const english = { ...state, language: 'en' };
const publications = research.cases.flatMap(record => record.reports.map(report => ({
  record, report, route: reportRoute(record.companyId, record.managerId, report.version),
})));
const decodeAttribute = value => value.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const links = html => [...html.matchAll(/\bhref="([^"]*)"/g)].map(match => decodeAttribute(match[1]));
const appRoutes = html => links(html).filter(value => value.startsWith('#/app/')).map(parseRoute);
const evidenceRoutes = html => appRoutes(html).filter(route => route.view === 'evidence');
const citationRoute = (route, evidenceId, origin = 'report', section) => ({
  ...route, view: 'evidence', evidenceId, origin, ...(section ? { section } : {}),
});

test('each published case resolves its exact company, Manager and immutable version', () => {
  for (const { record, report, route } of publications) {
    const context = resolveContext(parseRoute(formatRoute(route)));
    assert.equal(context.company.id, record.companyId);
    assert.equal(context.manager.id, record.managerId);
    assert.equal(context.caseRecord, record);
    assert.equal(context.report, report);
  }
  assert.notEqual(findReport('alphabet', 'north', 'v1'), findReport('alphabet', 'field', 'v1'));
  assert.notEqual(findReport('alphabet', 'north', 'v1'), findReport('microsoft', 'north', 'v1'));
  for (const companyId of [undefined, '', 'unknown']) {
    assert.throws(() => resolveContext(reportRoute(companyId, 'north', 'v1')), /case-unavailable/);
  }
  for (const managerId of [undefined, '', 'unknown']) {
    assert.throws(() => resolveContext(reportRoute('alphabet', managerId, 'v1')), /case-unavailable/);
  }
  for (const version of [undefined, '', 'v404']) {
    assert.throws(() => resolveContext(reportRoute('alphabet', 'north', version)), /version-unavailable/);
  }
  assert.throws(() => resolveContext(reportRoute('alphabet', 'north', null)), /version-required/);
  assert.throws(() => resolveContext({ ...research.defaultRoute, section: 'unknown' }), /section-unavailable/);
});

test('researching cases stay empty and never borrow a published report', () => {
  for (const record of research.cases.filter(item => item.status === 'researching')) {
    const route = reportRoute(record.companyId, record.managerId, null);
    const context = resolveContext(route);
    assert.equal(context.report, null);
    assert.equal(context.caseRecord, record);
    assert.throws(() => resolveContext({ ...route, version: 'v1' }), /version-unavailable/);
    const html = reportView(route, context, state);
    assert.match(html, /尚未发布/);
    assert.deepEqual(evidenceRoutes(html), []);
    for (const { report } of publications) assert.ok(!html.includes(report.title));
    const emptyChanges = changesView({ ...route, view: 'changes' }, context, english);
    assert.match(emptyChanges, /No completed monitoring record/);
    assert.deepEqual(caseEvents(record.companyId, record.managerId, null), []);
  }
});

test('comparison resolves the same company, different Managers, and explicit side versions', () => {
  for (const record of research.cases) {
    const route = comparisonRoute(reportRoute(record.companyId, record.managerId, record.currentVersion));
    const context = resolveContext(parseRoute(formatRoute(route)));
    assert.equal(route.managerId, route.compare.left.managerId);
    assert.equal(route.version, route.compare.left.version);
    assert.notEqual(route.compare.left.managerId, route.compare.right.managerId);
    for (const side of context.comparison) {
      assert.equal(side.caseRecord.companyId, record.companyId);
      assert.equal(side.report, findReport(record.companyId, side.manager.id, route.compare[side.side].version));
    }
  }
  const route = comparisonRoute(reportRoute('alphabet', 'north', 'v1'));
  const historicalPeer = { ...route, compare: { ...route.compare, right: { managerId: 'field', version: 'v1' } } };
  assert.equal(resolveContext(historicalPeer).comparison[1].report.version, 'v1');
  assert.throws(() => resolveContext({ ...route, managerId: 'field' }), /comparison-context-mismatch/);
  assert.throws(() => resolveContext({ ...route, version: 'v2' }), /comparison-context-mismatch/);
  assert.throws(() => resolveContext({ ...route, compare: undefined }), /comparison-required/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: route.compare.left } }), /comparison-managers-must-differ/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { managerId: 'unknown', version: 'v1' } } }), /comparison-unavailable/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { managerId: 'field', version: 'v404' } } }), /comparison-version-unavailable/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { managerId: 'field', version: null } } }), /comparison-version-required/);
});

test('every evidence lookup is restricted to its selected report or event origin', () => {
  for (const { report, route } of publications) {
    for (const evidence of research.evidence) {
      const fromReport = citationRoute(route, evidence.id);
      const belongsToReport = evidence.companyId === route.companyId && report.sections.some(section => section.citations.includes(evidence.id));
      if (belongsToReport) assert.equal(resolveContext(fromReport).evidence, evidence);
      else assert.throws(() => resolveContext(fromReport), /evidence-unavailable/, `${formatRoute(fromReport)} must not borrow a citation`);

      const fromEvent = citationRoute(route, evidence.id, 'changes');
      const belongsToEvent = research.events.some(event => event.companyId === route.companyId && event.evidenceIds.includes(evidence.id)
        && event.affectedCases.some(affected => affected.managerId === route.managerId && affected.version === route.version));
      if (belongsToEvent) assert.equal(resolveContext(fromEvent).evidence, evidence);
      else assert.throws(() => resolveContext(fromEvent), /evidence-unavailable/, `${formatRoute(fromEvent)} must not borrow an event`);
    }
    for (const section of report.sections) {
      for (const evidenceId of report.sections.flatMap(item => item.citations)) {
        const scoped = citationRoute(route, evidenceId, 'report', section.id);
        if (section.citations.includes(evidenceId)) assert.ok(resolveContext(scoped).evidence);
        else assert.throws(() => resolveContext(scoped), /evidence-unavailable/);
      }
    }
  }
});

test('new event evidence can review an old version without being added to that report', () => {
  const route = reportRoute('alphabet', 'north', 'v1');
  const evidenceId = 'demo-alpha-build-later';
  assert.throws(() => resolveContext(citationRoute(route, evidenceId)), /evidence-unavailable/);
  const eventEvidence = citationRoute(route, evidenceId, 'changes');
  assert.equal(resolveContext(eventEvidence).evidence.id, evidenceId);
  assert.deepEqual(evidenceReturnRoute(eventEvidence), { ...route, view: 'changes' });
  const events = caseEvents(route.companyId, route.managerId, route.version);
  assert.deepEqual(events.map(event => event.id), ['demo-event-alpha-investment']);
  assert.deepEqual(caseEvents('alphabet', 'field', 'v1'), []);
});

test('right-column evidence preserves its Manager and both comparison versions on return', () => {
  const route = { ...comparisonRoute(reportRoute('alphabet', 'north', 'v2')), compare: {
    left: { managerId: 'north', version: 'v2' }, right: { managerId: 'field', version: 'v1' },
  } };
  const rendered = compareView(route, resolveContext(route), state);
  const rightLinks = evidenceRoutes(rendered).filter(item => item.managerId === 'field');
  assert.ok(rightLinks.length > 0);
  for (const target of rightLinks) {
    assert.equal(target.version, 'v1');
    assert.equal(target.origin, 'compare');
    assert.deepEqual(target.compare, route.compare);
    const context = resolveContext(target);
    assert.equal(context.manager.id, 'field');
    assert.equal(context.report.version, 'v1');
    assert.deepEqual(evidenceReturnRoute(target), route);
    const back = appRoutes(evidenceView(target, context, state))[0];
    assert.deepEqual(back, route);
  }
  const mismatched = { ...rightLinks[0], version: 'v2', section: undefined };
  // Both Field versions cite the same business evidence: only the pair identity differs.
  mismatched.evidenceId = 'demo-alpha-business';
  assert.throws(() => resolveContext(mismatched), /comparison-evidence-mismatch/);
});

test('all rendered internal links parse and resolve across companies, versions and both UI languages', () => {
  let checked = 0;
  for (const record of research.cases) {
    for (const version of record.reports.length ? record.reports.map(report => report.version) : [null]) {
      const base = reportRoute(record.companyId, record.managerId, version);
      for (const personal of [state, english]) {
        for (const route of [base, { ...base, view: 'changes' }, comparisonRoute(base)]) {
          const context = resolveContext(route);
          const render = route.view === 'report' ? reportView : route.view === 'compare' ? compareView : changesView;
          const html = shell(route, context, personal, registry) + render(route, context, personal);
          for (const target of appRoutes(html)) {
            const linked = resolveContext(target);
            checked++;
            if (target.view === 'evidence') {
              for (const returnRoute of appRoutes(evidenceView(target, linked, personal))) {
                resolveContext(returnRoute);
                checked++;
              }
            }
          }
        }
      }
    }
  }
  assert.ok(checked > 1000, `expected meaningful full-link coverage, got ${checked}`);
});

test('unavailable evidence renders locator and gap but never source body', () => {
  const evidence = research.evidence.find(item => item.availability === 'unavailable');
  assert.ok(evidence);
  const owner = publications.find(({ report }) => report.sections.some(section => section.citations.includes(evidence.id)));
  const route = citationRoute(owner.route, evidence.id);
  const context = resolveContext(route);
  const attemptedLeak = { ...context, evidence: { ...context.evidence, quote: 'DO_NOT_SHOW_QUOTE', context: ['DO_NOT_SHOW_CONTEXT'] } };
  for (const personal of [state, english]) {
    const html = evidenceView(route, attemptedLeak, personal);
    assert.ok(html.includes(escapeHTML(evidence.locator)));
    assert.ok(html.includes(escapeHTML(evidence.limitation)));
    assert.doesNotMatch(html, /DO_NOT_SHOW|<blockquote>/);
    assert.equal(appRoutes(html)[0].companyId, owner.route.companyId);
  }
});

test('review and read states preserve full historical text and unresolved event status', () => {
  const route = reportRoute('alphabet', 'north', 'v1');
  const context = resolveContext(route);
  const readState = { ...state, readVersions: { [caseKey('alphabet', 'north')]: 'v1' }, readEvents: research.events.map(event => event.id) };
  const html = reportView(route, context, readState);
  for (const section of context.report.sections) {
    assert.ok(html.includes(escapeHTML(section.title)));
    for (const paragraph of section.paragraphs) assert.ok(html.includes(escapeHTML(paragraph)));
  }
  for (const id of context.report.affectedSections) assert.ok(html.includes(`data-local-section="section-${id}"`));
  assert.match(html, /结论待复核/);
  assert.match(html, /此版本已标记为已读/);
  const updates = changesView({ ...route, view: 'changes' }, context, readState);
  assert.match(updates, /仍待验证/);
  assert.match(updates, /disabled>已读/);
  assert.equal(context.report.status, 'review');
  assert.ok(caseEvents('alphabet', 'north', 'v1').every(event => event.unresolved));
  const otherCase = resolveContext(reportRoute('alphabet', 'field', 'v1'));
  assert.doesNotMatch(reportView(reportRoute('alphabet', 'field', 'v1'), otherCase, readState), /此版本已标记为已读/);
});

test('report, evidence and error output escape untrusted display text', () => {
  const injection = '<img src=x onerror="alert(1)"> & \'test\'';
  assert.equal(escapeHTML(injection), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;test&#39;');
  const route = research.defaultRoute;
  const context = structuredClone(resolveContext(route));
  Object.assign(context.report, { title: injection, subtitle: injection, summary: injection, verdict: injection });
  context.report.sections[0] = { ...context.report.sections[0], title: injection, paragraphs: [injection], bullets: [injection], table: { columns: [injection], rows: [[injection]] } };
  const html = reportView(route, context, state);
  assert.doesNotMatch(html, /<img src=x/);
  assert.ok(html.includes(escapeHTML(injection)));
  const evidenceId = context.report.sections[0].citations[0];
  const evidenceRoute = citationRoute(route, evidenceId);
  const evidenceContext = structuredClone(resolveContext(evidenceRoute));
  for (const field of ['sourceTitle', 'sourceType', 'locator', 'quote', 'limitation']) evidenceContext.evidence[field] = injection;
  evidenceContext.evidence.context = [injection];
  const evidenceHTML = evidenceView(evidenceRoute, evidenceContext, state);
  assert.doesNotMatch(evidenceHTML, /<img src=x/);
  assert.ok(evidenceHTML.includes(escapeHTML(injection)));
  assert.doesNotMatch(errorView(injection, 'en'), /<img src=x/);
});

test('English report and comparison UI identify preserved Chinese report content', () => {
  for (const { route } of publications) {
    const context = resolveContext(route);
    const reportHTML = reportView(route, context, english);
    assert.match(reportHTML, /Original: Chinese/);
    assert.ok(reportHTML.includes(context.report.title));
    const comparison = comparisonRoute(route);
    const compareHTML = compareView(comparison, resolveContext(comparison), english);
    assert.match(compareHTML, /Original: Chinese/);
    assert.ok(compareHTML.includes(context.report.title));
  }
});
