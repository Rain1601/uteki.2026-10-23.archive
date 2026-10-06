import { workspace, findDocument, findVersion, findCoverage, findEvidence } from './catalog.mjs';

export function indexRoute(entry,objectId,view='research',filterId) {
  return {page:'index',entry,objectId,view,...(filterId ? {filterId} : {})};
}
export function documentRoute(document,version,from,view='report') {
  if (!document || !version || !from?.entry) throw new Error('report-scope-required');
  const objectId = from.entry === 'companies' ? document.companyId : (['evidence','compare'].includes(view) ? from.objectId || document.managerId : document.managerId);
  return {page:'reader',entry:from.entry,objectId,companyId:document.companyId,managerId:document.managerId,reportId:document.id,version,view,
    ...(from.filterId ? {filterId:from.filterId} : {}),
    returnView:from.page === 'index' ? from.view : (from.returnView || 'research')};
}
export function indexReturnRoute(route) {
  return indexRoute(route.entry,route.objectId,route.returnView || 'research',route.filterId);
}
export function switchEntryRoute(route,entry,state) {
  if (route.page === 'reader') {
    // The same document remains open; only the object list changes.
    return {...route,entry,objectId:entry === 'companies' ? route.companyId : route.managerId,filterId:undefined,returnView:'research'};
  }
  const saved = state.entries?.[entry];
  return saved || indexRoute(entry,workspace.defaultEntries[entry]);
}
export function reportEvents(reportId,version) {
  return workspace.events.filter(event => event.affectedReports.some(item => item.reportId === reportId && item.version === version));
}
export function eventsForObject(entry,objectId,filterId) {
  const ids = new Set(workspace.reports.filter(doc => (entry === 'companies' ? doc.companyId === objectId : doc.managerId === objectId)
    && (!filterId || (entry === 'companies' ? doc.managerId === filterId : doc.companyId === filterId))).map(doc => doc.id));
  return workspace.events.filter(event => event.affectedReports.some(item => ids.has(item.reportId)));
}
export function comparisonRoute(route,otherReportId) {
  const document = findDocument(route.reportId);
  if (!document || document.kind !== 'main') throw new Error('comparison-unavailable');
  const candidates = workspace.reports.filter(doc => doc.companyId === document.companyId && doc.managerId !== document.managerId && doc.kind === 'main');
  const other = otherReportId ? candidates.find(doc => doc.id === otherReportId) : candidates.length === 1 ? candidates[0] : null;
  if (!other) throw new Error('comparison-selection-required');
  return {...documentRoute(document,route.version,route,'compare'),compare:{left:{reportId:document.id,version:route.version},right:{reportId:other.id,version:other.currentVersion}}};
}
export function evidenceReturnRoute(route) {
  if (route.origin === 'compare') {
    const doc = findDocument(route.compare.left.reportId);
    return {...documentRoute(doc,route.compare.left.version,route,'compare'),compare:route.compare};
  }
  return documentRoute(findDocument(route.reportId),route.version,route,route.origin === 'changes' ? 'changes' : 'report');
}

// Explicit adapter for the published Stage 1 fixture URLs. These identities are
// named historical configuration, not a generic "choose a main report" fallback.
const stageOneMainReports = {'alphabet/north':'alpha-north-main','alphabet/field':'alpha-field-main','microsoft/north':'ms-north-main'};
export function upgradeRoute(route) {
  if (route?.page !== 'legacy') return route;
  const old = route.legacy;
  const coverage = findCoverage(old.companyId,old.managerId);
  if (!coverage) throw new Error('case-unavailable');
  if (old.version === null) {
    if (coverage.status !== 'researching') throw new Error('version-required');
    return indexRoute('companies',old.companyId,'research',old.managerId);
  }
  const reportId = stageOneMainReports[`${old.companyId}/${old.managerId}`];
  const doc = reportId && findDocument(reportId);
  if (!doc || !findVersion(doc.id,old.version)) throw new Error('version-unavailable');
  const next = documentRoute(doc,old.version,{entry:'companies'},old.view);
  for (const field of ['section','evidenceId','origin']) if (old[field]) next[field] = old[field];
  if (old.compare) next.compare = Object.fromEntries(['left','right'].map(side => {
    const selection = old.compare[side];
    const id = stageOneMainReports[`${old.companyId}/${selection.managerId}`];
    if (!id || !findVersion(id,selection.version)) throw new Error('comparison-version-unavailable');
    return [side,{reportId:id,version:selection.version}];
  }));
  return next;
}

function selection(reportId,version,companyId) {
  const document = findDocument(reportId);
  if (!document || (companyId && companyId !== document.companyId)) throw new Error('report-unavailable');
  const report = findVersion(reportId,version);
  if (!report) throw new Error('version-unavailable');
  const company = workspace.companies.find(item => item.id === document.companyId);
  const manager = workspace.managers.find(item => item.id === document.managerId);
  return {company,manager,document,report,caseRecord:{reports:document.versions,currentVersion:document.currentVersion}};
}
export function resolveContext(route) {
  if (route.page === 'index') {
    const companies = route.entry === 'companies';
    const object = (companies ? workspace.companies : workspace.managers).find(item => item.id === route.objectId);
    if (!object) throw new Error('object-unavailable');
    const coverage = workspace.coverage.filter(item => companies ? item.companyId === object.id : item.managerId === object.id);
    const grouped = coverage.filter(item => !route.filterId || (companies ? item.managerId === route.filterId : item.companyId === route.filterId));
    if (route.filterId && !grouped.length) throw new Error('filter-unavailable');
    const makeGroup = record => ({
      company:workspace.companies.find(item => item.id === record.companyId),
      manager:workspace.managers.find(item => item.id === record.managerId),coverage:record,
      reports:workspace.reports.filter(doc => doc.companyId === record.companyId && doc.managerId === record.managerId),
    });
    const groups = grouped.map(makeGroup), allGroups = coverage.map(makeGroup);
    const documents = groups.flatMap(group => group.reports);
    const portfolio = route.entry === 'managers' ? workspace.portfolios.find(item => item.managerId === object.id) : null;
    return {object,company:companies ? object : null,manager:companies ? null : object,groups,allGroups,documents,events:eventsForObject(route.entry,object.id,route.filterId),portfolio};
  }
  if (route.page !== 'reader') throw new Error('report-scope-required');
  const context = selection(route.reportId,route.version);
  if (context.company.id !== route.companyId || context.manager.id !== route.managerId) throw new Error('report-owner-mismatch');
  if (route.filterId && !(route.entry === 'companies' ? findCoverage(route.companyId,route.filterId) : route.filterId === route.companyId)) throw new Error('filter-unavailable');
  if (route.returnView === 'portfolio' && route.entry !== 'managers') throw new Error('return-context-invalid');
  if (route.section && !context.report.sections.some(section => section.id === route.section)) throw new Error('section-unavailable');
  context.object = (route.entry === 'companies' ? workspace.companies : workspace.managers).find(item => item.id === route.objectId);
  if (!context.object || (route.entry === 'companies' && route.objectId !== route.companyId)) throw new Error('entry-object-mismatch');
  if (route.view === 'compare' || route.origin === 'compare') {
    if (!route.compare) throw new Error('comparison-required');
    if (route.view === 'compare' && (route.reportId !== route.compare.left.reportId || route.version !== route.compare.left.version)) throw new Error('comparison-context-mismatch');
    context.comparison = ['left','right'].map(side => ({side,...selection(route.compare[side].reportId,route.compare[side].version,route.companyId)}));
    if (context.comparison[0].manager.id === context.comparison[1].manager.id) throw new Error('comparison-managers-must-differ');
    if (context.comparison.some(item => item.document.kind !== 'main')) throw new Error('comparison-kind-unavailable');
  }
  if (route.entry === 'managers' && route.objectId !== route.managerId && !context.comparison?.some(item => item.manager.id === route.objectId)) throw new Error('entry-object-mismatch');
  if (route.view === 'evidence') {
    const evidence = findEvidence(route.evidenceId);
    const inReport = context.report.sections.some(section => (!route.section || section.id === route.section) && section.citations.includes(route.evidenceId));
    const inEvent = reportEvents(route.reportId,route.version).some(event => event.evidenceIds.includes(route.evidenceId));
    if (!evidence || evidence.companyId !== route.companyId || !(route.origin === 'changes' ? inEvent : inReport)) throw new Error('evidence-unavailable');
    if (route.origin === 'compare' && !context.comparison.some(item => item.document.id === route.reportId && item.report.version === route.version)) throw new Error('comparison-evidence-mismatch');
    context.evidence = evidence;
  }
  return context;
}
