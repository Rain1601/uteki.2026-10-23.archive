import { research, findCase, findReport, findEvidence } from './research.mjs';

export function resolveContext(route) {
  const company = research.companies.find(item => item.id === route.companyId);
  const manager = research.managers.find(item => item.id === route.managerId);
  const caseRecord = findCase(route.companyId, route.managerId);
  if (!company || !manager || !caseRecord) throw new Error('case-unavailable');
  const report = route.version === null ? null : findReport(company.id, manager.id, route.version);
  if (route.version !== null && !report) throw new Error('version-unavailable');
  if (route.version === null && caseRecord.status !== 'researching') throw new Error('version-required');
  if (route.section && !report?.sections.some(section => section.id === route.section)) throw new Error('section-unavailable');
  const context = { company, manager, caseRecord, report };
  if (route.view === 'compare' || route.origin === 'compare') {
    if (!route.compare) throw new Error('comparison-required');
    if (route.view === 'compare' && (route.managerId !== route.compare.left.managerId || route.version !== route.compare.left.version)) throw new Error('comparison-context-mismatch');
    if (route.compare.left.managerId === route.compare.right.managerId) throw new Error('comparison-managers-must-differ');
    context.comparison = ['left', 'right'].map(side => {
      const selection = route.compare[side];
      const record = findCase(company.id, selection.managerId);
      const owner = research.managers.find(item => item.id === selection.managerId);
      if (!record || !owner) throw new Error('comparison-unavailable');
      const version = selection.version === null ? null : findReport(company.id, owner.id, selection.version);
      if (selection.version !== null && !version) throw new Error('comparison-version-unavailable');
      if (selection.version === null && record.status !== 'researching') throw new Error('comparison-version-required');
      return { side, manager: owner, caseRecord: record, report: version };
    });
  }
  if (route.view === 'evidence') {
    const evidence = findEvidence(route.evidenceId);
    const inReport = report?.sections.some(section => (!route.section || section.id === route.section) && section.citations.includes(route.evidenceId));
    const inEvent = research.events.some(event => event.companyId === company.id && event.evidenceIds.includes(route.evidenceId)
      && event.affectedCases.some(item => item.managerId === manager.id && item.version === route.version));
    if (!evidence || evidence.companyId !== company.id || !report || !(route.origin === 'changes' ? inEvent : inReport)) throw new Error('evidence-unavailable');
    if (route.origin === 'compare' && !context.comparison.some(item => item.manager.id === manager.id && item.report?.version === report.version)) throw new Error('comparison-evidence-mismatch');
    context.evidence = evidence;
  }
  return context;
}

export function caseEvents(companyId, managerId, version) {
  return research.events.filter(event => event.companyId === companyId && event.affectedCases.some(item => item.managerId === managerId && item.version === version));
}

export function reportRoute(companyId, managerId, version, view = 'report') {
  return { companyId, managerId, version, view };
}

export function comparisonRoute(route) {
  const other = research.managers.find(item => item.id !== route.managerId);
  const peer = findCase(route.companyId, other.id);
  return { ...reportRoute(route.companyId, route.managerId, route.version, 'compare'), compare: {
    left: { managerId: route.managerId, version: route.version },
    right: { managerId: other.id, version: peer.currentVersion },
  } };
}

export function evidenceReturnRoute(route) {
  if (route.origin === 'compare') return { ...reportRoute(route.companyId, route.compare.left.managerId, route.compare.left.version, 'compare'), compare: route.compare };
  return reportRoute(route.companyId, route.managerId, route.version, route.origin === 'changes' ? 'changes' : 'report');
}
