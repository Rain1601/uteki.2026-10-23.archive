import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { workspace, findDocument, findVersion, findEvidence } from './catalog.mjs';
import { parseRoute, formatRoute } from './workspace-state.mjs';
import {
  indexRoute, documentRoute, indexReturnRoute, switchEntryRoute, comparisonRoute,
  evidenceReturnRoute, eventsForObject, reportEvents, resolveContext, upgradeRoute,
} from './workspace-model.mjs';
import { shell, directoryView, portfolioView } from './workspace-shell.mjs';
import { reportView, compareView, evidenceView, changesView, errorView } from './workspace-reader-view.mjs';
import { escapeHTML } from './reader-view.mjs';

const registry = JSON.parse(readFileSync(new URL('./assets/companies/registry.json', import.meta.url), 'utf8'));
const personal = language => ({ language, theme: 'system', fontSize: 17, readVersions: {}, readEvents: [], savedEvents: [], notes: {}, positions: {}, entries: { companies: null, managers: null } });
const docRoute = (reportId, version, entry = 'companies', view = 'report') => {
  const document = findDocument(reportId);
  return documentRoute(document, version, indexRoute(entry, entry === 'companies' ? document.companyId : document.managerId), view);
};
const unescape = value => value.replace(/&amp;/g, '&').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');
function anchors(html) {
  return [...html.matchAll(/<a\b([^>]*?)href="([^"]+)"([^>]*)>([\s\S]*?)<\/a>/g)].map(match => ({ attributes: `${match[1]} ${match[3]}`, href: unescape(match[2]), content: match[4] }));
}
function appLinks(html) { return anchors(html).filter(item => item.href.startsWith('#/app/')); }
function viewHTML(route, state) {
  const context = resolveContext(route);
  if (route.page === 'index') return route.view === 'portfolio' ? portfolioView(route, context, state) : directoryView(route, context, state);
  return ({ report: reportView, compare: compareView, evidence: evidenceView, changes: changesView })[route.view](route, context, state);
}

test('company directory groups all reports by Manager, preserving multiple documents per pair', () => {
  const route = indexRoute('companies', 'alphabet');
  const context = resolveContext(route);
  assert.equal(context.object.id, 'alphabet');
  assert.deepEqual(context.groups.map(group => group.manager.id), ['north', 'field']);
  assert.deepEqual(context.groups.map(group => group.company.id), ['alphabet', 'alphabet']);
  assert.deepEqual(context.groups[0].reports.map(doc => doc.id), ['alpha-north-main', 'alpha-north-cloud']);
  assert.deepEqual(context.groups[1].reports.map(doc => doc.id), ['alpha-field-main', 'alpha-field-capacity']);
  assert.equal(context.documents.length, 4);
  const filtered = resolveContext(indexRoute('companies', 'alphabet', 'research', 'north'));
  assert.equal(filtered.groups.length, 1);
  assert.equal(filtered.allGroups.length, 2);
  assert.equal(filtered.documents.length, 2);
});

test('Manager directory groups the same document identities by company and keeps unpublished coverage explicit', () => {
  const context = resolveContext(indexRoute('managers', 'north'));
  assert.equal(context.object.id, 'north');
  assert.equal(context.groups.length, 6);
  assert.ok(context.groups.every(group => group.manager.id === 'north'));
  assert.deepEqual(context.groups.find(group => group.company.id === 'alphabet').reports.map(doc => doc.id), ['alpha-north-main', 'alpha-north-cloud']);
  assert.deepEqual(context.groups.find(group => group.company.id === 'microsoft').reports.map(doc => doc.id), ['ms-north-main']);
  assert.deepEqual(context.groups.find(group => group.company.id === 'nvidia').reports, []);
  assert.equal(context.groups.find(group => group.company.id === 'nvidia').coverage.status, 'researching');
  const filtered = resolveContext(indexRoute('managers', 'north', 'research', 'alphabet'));
  assert.equal(filtered.groups.length, 1);
  assert.equal(filtered.allGroups.length, 6);
  const companyDocs = resolveContext(indexRoute('companies', 'alphabet', 'research', 'north')).documents;
  assert.deepEqual(filtered.documents, companyDocs);
});

test('independent document and version scope cannot fall back to a sibling report or another owner', () => {
  const main = resolveContext(docRoute('alpha-north-main', 'v1'));
  const topic = resolveContext(docRoute('alpha-north-cloud', 'v1'));
  assert.notEqual(main.document.id, topic.document.id);
  assert.notEqual(main.report.publicationId, topic.report.publicationId);
  assert.notDeepEqual(main.report.sections, topic.report.sections);
  assert.equal(main.report.cutoff, '2026-09-17');
  assert.equal(topic.report.cutoff, '2026-09-18');
  for (const invalid of [
    { ...docRoute('alpha-north-cloud', 'v1'), managerId: 'field' },
    { ...docRoute('alpha-north-cloud', 'v1'), companyId: 'microsoft' },
    { ...docRoute('alpha-north-cloud', 'v1'), companyId: '' },
    { ...docRoute('alpha-north-cloud', 'v1'), managerId: undefined },
  ]) assert.throws(() => resolveContext(invalid), /report-owner-mismatch/);
  assert.throws(() => resolveContext({ ...docRoute('alpha-north-cloud', 'v1'), reportId: 'unknown' }), /report-unavailable/);
  assert.throws(() => resolveContext({ ...docRoute('alpha-field-capacity', 'v1'), version: 'v2' }), /version-unavailable/);
  assert.throws(() => resolveContext({ ...docRoute('alpha-north-cloud', 'v1'), objectId: 'microsoft' }), /entry-object-mismatch/);
  assert.throws(() => resolveContext(indexRoute('companies', 'unknown')), /object-unavailable/);
  assert.throws(() => resolveContext(indexRoute('managers', 'unknown')), /object-unavailable/);
  assert.throws(() => resolveContext(indexRoute('companies', 'alphabet', 'research', 'unknown')), /filter-unavailable/);
});

test('company and Manager event collections count a matter once across versions and main/topic references', () => {
  const event = workspace.events.find(item => item.id === 'demo-event-alpha-investment');
  const original = event.affectedReports;
  try {
    event.affectedReports = [...original, { reportId: 'alpha-north-cloud', version: 'v2', sectionId: 'payment' }];
    for (const [entry, objectId] of [['companies', 'alphabet'], ['managers', 'north']]) {
      const events = eventsForObject(entry, objectId);
      assert.equal(events.filter(item => item.id === event.id).length, 1);
      const route = indexRoute(entry, objectId, 'changes');
      const html = directoryView(route, resolveContext(route), personal('zh'));
      assert.equal(html.split(`id="event-${event.id}"`).length - 1, 1);
      assert.match(html, /alpha-north-main/);
      assert.match(html, /alpha-north-cloud/);
    }
    assert.equal(reportEvents('alpha-north-cloud', 'v2').filter(item => item.id === event.id).length, 1);
    assert.equal(reportEvents('alpha-north-cloud', 'v1').some(item => item.id === event.id), false);
    assert.equal(eventsForObject('managers', 'north', 'microsoft').some(item => item.id === event.id), false);
  } finally { event.affectedReports = original; }
});

test('full historical and current documents render every paragraph and keep citation scope at their own cutoff', () => {
  for (const document of workspace.reports) for (const version of document.versions) {
    const route = docRoute(document.id, version.version);
    const context = resolveContext(route);
    const html = reportView(route, context, personal('zh'));
    assert.equal(context.report, version);
    for (const section of version.sections) {
      for (const paragraph of section.paragraphs) assert.ok(html.includes(escapeHTML(paragraph)), `${document.id}/${version.version}/${section.id} lost text`);
      for (const id of section.citations) {
        const evidence = findEvidence(id);
        assert.equal(evidence.companyId, document.companyId);
        assert.ok(evidence.availableAt <= version.cutoff);
        const citation = appLinks(html).find(link => link.attributes.includes(`id="ref-${section.id}-${id}"`));
        assert.ok(citation, `missing citation ${document.id}/${version.version}/${id}`);
        const evidenceRoute = parseRoute(citation.href);
        const evidenceContext = resolveContext(evidenceRoute);
        assert.equal(evidenceRoute.reportId, document.id);
        assert.equal(evidenceRoute.version, version.version);
        assert.equal(evidenceContext.evidence.id, id);
        assert.equal(evidenceRoute.section, section.id);
      }
    }
  }
});

test('evidence cannot cross a report, section, company, or historical version boundary', () => {
  const base = docRoute('alpha-north-cloud', 'v1', 'companies', 'evidence');
  assert.throws(() => resolveContext({ ...base, evidenceId: 'demo-ms-paid', origin: 'report' }), /evidence-unavailable/);
  assert.throws(() => resolveContext({ ...base, evidenceId: 'demo-alpha-use-later', origin: 'report' }), /evidence-unavailable/);
  assert.throws(() => resolveContext({ ...base, evidenceId: 'demo-alpha-demand-early', origin: 'report', section: 'next' }), /evidence-unavailable/);
  const sourceRoute = { ...docRoute('ms-north-main', 'v1', 'companies', 'evidence'), evidenceId: 'demo-ms-renewal-unavailable', origin: 'report', section: 'risk' };
  const html = evidenceView(sourceRoute, resolveContext(sourceRoute), personal('zh'));
  assert.match(html, /原文暂不可读取/);
  assert.doesNotMatch(html, /<blockquote>/);
  const back = parseRoute(appLinks(html).find(link => link.attributes.includes('data-return')).href);
  assert.equal(back.reportId, 'ms-north-main');
  assert.equal(back.version, 'v1');
  assert.equal(back.section, 'risk');
});

test('Manager-origin comparison opens right-side Field evidence without changing the selected North directory', () => {
  const route = comparisonRoute(docRoute('alpha-north-main', 'v1', 'managers'), 'alpha-field-main');
  assert.equal(route.objectId, 'north');
  assert.deepEqual(route.compare, { left: { reportId: 'alpha-north-main', version: 'v1' }, right: { reportId: 'alpha-field-main', version: 'v2' } });
  const html = compareView(route, resolveContext(route), personal('zh'));
  const citation = appLinks(html).find(link => link.attributes.includes('id="right-ref-signals-demo-alpha-use-later"'));
  assert.ok(citation);
  const target = parseRoute(citation.href);
  assert.equal(target.managerId, 'field');
  assert.equal(target.objectId, 'north', 'reading Field evidence must retain the North entry object');
  assert.equal(target.reportId, 'alpha-field-main');
  assert.equal(target.version, 'v2');
  assert.equal(target.origin, 'compare');
  assert.deepEqual(target.compare, route.compare);
  const context = resolveContext(target);
  assert.equal(context.manager.id, 'field');
  assert.equal(context.object.id, 'north');
  const chrome = shell(target, context, personal('zh'), registry);
  const selected = anchors(chrome).filter(link => link.attributes.includes('company-row') && link.attributes.includes('is-selected'));
  assert.equal(selected.length, 1);
  assert.match(selected[0].attributes, /data-object="north"/);
  const back = evidenceReturnRoute(target);
  assert.equal(back.view, 'compare');
  assert.equal(back.managerId, 'north');
  assert.equal(back.objectId, 'north');
  assert.deepEqual(back.compare, route.compare);
  assert.equal(resolveContext(back).report.version, 'v1');
  assert.equal(indexReturnRoute(target).objectId, 'north');
});

test('comparison constraints preserve explicit reports and reject unrelated company, same Manager, or topic pairing', () => {
  const route = comparisonRoute(docRoute('alpha-north-main', 'v1'));
  assert.throws(() => comparisonRoute(docRoute('alpha-north-cloud', 'v1')), /comparison-unavailable/);
  assert.throws(() => comparisonRoute(docRoute('ms-north-main', 'v1')), /comparison-selection-required/);
  assert.throws(() => comparisonRoute(docRoute('alpha-north-main', 'v1'), 'ms-north-main'), /comparison-selection-required/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { reportId: 'ms-north-main', version: 'v1' } } }), /report-unavailable/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { reportId: 'alpha-north-main', version: 'v2' } } }), /comparison-managers-must-differ/);
  assert.throws(() => resolveContext({ ...route, compare: { ...route.compare, right: { reportId: 'alpha-field-capacity', version: 'v1' } } }), /comparison-kind-unavailable/);
});

test('entry switching preserves a document and otherwise uses saved selection or named defaults', () => {
  const route = docRoute('alpha-north-cloud', 'v1');
  const next = switchEntryRoute(route, 'managers', personal('zh'));
  assert.equal(next.reportId, route.reportId);
  assert.equal(next.version, 'v1');
  assert.equal(next.objectId, 'north');
  assert.equal(resolveContext(next).document.id, route.reportId);
  const state = personal('zh');
  state.entries.managers = indexRoute('managers', 'field', 'changes', 'alphabet');
  assert.deepEqual(switchEntryRoute(indexRoute('companies', 'microsoft'), 'managers', state), state.entries.managers);
  assert.deepEqual(switchEntryRoute(indexRoute('companies', 'microsoft'), 'managers', personal('zh')), indexRoute('managers', workspace.defaultEntries.managers));
});

test('all generated bilingual links round-trip and resolve, including filtered directories and portfolio tabs', () => {
  const routes = [];
  for (const company of workspace.companies) for (const view of ['research', 'changes']) {
    routes.push(indexRoute('companies', company.id, view));
    for (const manager of workspace.managers) routes.push(indexRoute('companies', company.id, view, manager.id));
  }
  for (const manager of workspace.managers) {
    routes.push(indexRoute('managers', manager.id, 'portfolio'));
    for (const view of ['research', 'changes']) {
      routes.push(indexRoute('managers', manager.id, view));
      for (const company of workspace.companies) routes.push(indexRoute('managers', manager.id, view, company.id));
    }
  }
  for (const document of workspace.reports) for (const version of document.versions) for (const entry of ['companies', 'managers']) for (const view of ['report', 'changes']) routes.push(docRoute(document.id, version.version, entry, view));
  for (const entry of ['companies', 'managers']) routes.push(comparisonRoute(docRoute('alpha-north-main', 'v1', entry)));
  let checked = 0;
  for (const language of ['zh', 'en']) {
    const state = personal(language);
    for (const route of routes) {
      const context = resolveContext(route);
      const html = shell(route, context, state, registry) + viewHTML(route, state);
      for (const link of appLinks(html)) {
        const target = parseRoute(link.href);
        assert.ok(target, `${route.entry}/${route.objectId} produced an empty link`);
        assert.equal(formatRoute(target), link.href);
        resolveContext(upgradeRoute(target));
        if (target.page === 'index' && target.view === 'portfolio') assert.equal(target.filterId, undefined);
        checked += 1;
        if (target.page === 'reader' && target.view === 'evidence') {
          const evidenceHTML = evidenceView(target, resolveContext(target), state) + shell(target, resolveContext(target), state, registry);
          for (const returned of appLinks(evidenceHTML)) resolveContext(upgradeRoute(parseRoute(returned.href)));
        }
      }
    }
    for (const link of appLinks(errorView('report-unavailable', language))) resolveContext(parseRoute(link.href));
  }
  assert.ok(checked > 1000, `only ${checked} links checked`);
});

test('legacy case URLs map only named reports and preserve exact historical versions and citation scope', () => {
  const legacy = parseRoute('#/app/companies/alphabet/cases/north?version=v1&view=report');
  assert.equal(legacy.page, 'legacy');
  const upgraded = upgradeRoute(legacy);
  assert.equal(upgraded.reportId, 'alpha-north-main');
  assert.equal(upgraded.version, 'v1');
  assert.equal(upgraded.objectId, 'alphabet');
  assert.equal(resolveContext(upgraded).report.cutoff, '2026-09-17');
  const pending = upgradeRoute(parseRoute('#/app/companies/microsoft/cases/field?version=researching&view=report'));
  assert.deepEqual(pending, indexRoute('companies', 'microsoft', 'research', 'field'));
  assert.equal(resolveContext(pending).documents.length, 0);
  assert.throws(() => upgradeRoute(parseRoute('#/app/companies/unknown/cases/north?version=v1&view=report')), /case-unavailable/);
  assert.throws(() => upgradeRoute(parseRoute('#/app/companies/alphabet/cases/unknown?version=v1&view=report')), /case-unavailable/);
  assert.throws(() => upgradeRoute(parseRoute('#/app/companies/alphabet/cases/north?version=v999&view=report')), /version-unavailable/);
  assert.throws(() => upgradeRoute(parseRoute('#/app/companies/microsoft/cases/field?version=v1&view=report')), /version-unavailable/);
  const native = docRoute('alpha-north-cloud', 'v1');
  assert.equal(upgradeRoute(native), native);
});
