// A read-only presentation projection of an explicitly selected report edition.
// The web reader and static PDF consume this same object; no research is rewritten.
import { catalog, getReport, getEvidence } from './model.mjs';

const fields = ['companyId', 'managerId', 'reportId', 'version', 'language'];
const fail = message => { throw new Error(`Report presentation: ${message}`); };
const text = value => typeof value === 'string' && value.trim().length > 0;
const e = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export const REPORT_PDF_SAMPLE_SCOPE = Object.freeze({companyId:'alphabet', managerId:'north', reportId:'alpha-north-main', version:'v2', language:'zh-CN'});

export function getReportSamplePdf(scope) {
  if (!scope || !fields.every(key => scope[key] === REPORT_PDF_SAMPLE_SCOPE[key])) return null;
  return {href:'../../../output/pdf/uteki-research-sample.pdf', filename:'uteki-research-sample.pdf'};
}

export function buildReportPresentation(scope, data = catalog, {tables = {}} = {}) {
  if (!scope || !fields.every(key => text(scope[key]))) fail('company, Manager, report, version and language must be explicit');
  const context = getReport(scope.companyId, scope.reportId, scope.version, data);
  if (context.manager.id !== scope.managerId) fail('report belongs to a different Manager');
  if (context.report.language !== scope.language) fail('requested language is not this report edition');
  if (!tables || typeof tables !== 'object' || Array.isArray(tables)) fail('table presentation must be an object');
  const copy = structuredClone(context), evidence = [], byEvidence = new Map();
  const tableIds = new Set(copy.report.sections.filter(section => section.table).map(section => section.id));
  for (const id of Object.keys(tables)) if (!tableIds.has(id)) fail(`unknown table section ${id}`);
  const sections = copy.report.sections.map(section => {
    const citations = section.citations.map(id => {
      if (!byEvidence.has(id)) {
        const item = structuredClone(getEvidence(scope.companyId, scope.reportId, scope.version, id, data).evidence);
        const entry = {...item, number:evidence.length + 1, sectionIds:[]};
        evidence.push(entry); byEvidence.set(id, entry);
      }
      const entry = byEvidence.get(id);
      if (!entry.sectionIds.includes(section.id)) entry.sectionIds.push(section.id);
      return {id, number:entry.number, sourceTitle:entry.sourceTitle, availability:entry.availability};
    });
    if (!section.table) return {...section, citations};
    const declaration = tables[section.id]?.columns;
    if (declaration !== undefined && (!Array.isArray(declaration) || declaration.length !== section.table.columns.length)) fail(`column declaration count differs in ${section.id}`);
    if (!section.table.rows.every(row => Array.isArray(row) && row.length === section.table.columns.length)) fail(`table row width differs in ${section.id}`);
    const columns = section.table.columns.map((label, index) => {
      // Text is the presentation default. Numbers never get inferred from strings.
      const kind = declaration?.[index]?.kind ?? 'text';
      if (!['text','numeric'].includes(kind)) fail(`unsupported column kind in ${section.id}`);
      return {label, kind, align:kind === 'numeric' ? 'right' : 'left'};
    });
    return {...section, citations, table:{columns, rows:section.table.rows}};
  });
  return {schemaVersion:1, scope:Object.fromEntries(fields.map(key => [key, scope[key]])), company:copy.company,
    manager:copy.manager, document:copy.document, report:copy.report, sections, evidence};
}

const labels = uiLanguage => {
  const t = (zh,en) => uiLanguage === 'en' ? en : zh;
  return {t, available:value => ({available:t('演示正文可读','Demo text available'),excerpt:t('仅有摘录','Excerpt only'),unavailable:t('资料不可用','Unavailable')})[value] || value};
};

export function renderReportSections(presentation, {uiLanguage = 'zh', icon = () => ''} = {}) {
  const {available} = labels(uiLanguage);
  return presentation.sections.map(section => `<section id="section-${e(section.id)}" class="report-section" tabindex="-1"><div class="kicker">${e(section.kicker)}</div><h2>${e(section.title)}</h2>${section.paragraphs.map(p => `<p>${e(p)}</p>`).join('')}${section.bullets ? `<ul>${section.bullets.map(p => `<li>${e(p)}</li>`).join('')}</ul>` : ''}${section.table ? `<div class="table-scroll"><table><thead><tr>${section.table.columns.map(c => `<th scope="col" data-column-kind="${c.kind}" style="text-align:${c.align}">${e(c.label)}</th>`).join('')}</tr></thead><tbody>${section.table.rows.map(row => `<tr>${row.map((c,index) => `<td data-column-kind="${section.table.columns[index].kind}" style="text-align:${section.table.columns[index].align}">${e(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}<div class="citations">${section.citations.map(citation => `<button id="cite-${e(section.id)}-${e(citation.id)}" class="citation" data-action="evidence" data-evidence="${e(citation.id)}" data-origin="report">${icon('link')}<span>${citation.number} · ${e(citation.sourceTitle.replace('虚构演示 · ',''))}${citation.availability === 'unavailable' ? ` · ${e(available(citation.availability))}` : ''}</span></button>`).join('')}</div></section>`).join('');
}

export function renderEvidenceAppendix(presentation, {uiLanguage = 'zh'} = {}) {
  const {t,available} = labels(uiLanguage);
  if (!presentation.evidence.length) return '';
  return `<details class="report-evidence-appendix"><summary>${t('引用与来源','References & sources')} <span>${presentation.evidence.length} ${t('条','items')}</span></summary><p class="report-source-notice">${t('以下为当前版本引用的虚构演示资料，按首次引用排序；同名来源的不同原文位置分别保留。没有外部原始文件可供下载。','Fictional evidence cited by this edition, in first-citation order. Distinct locations within a source are retained. No external original files are available to download.')}</p>${presentation.evidence.map(item => `<section class="report-reference" id="reference-${e(item.id)}" lang="${e(item.language)}"><h3><span class="reference-number">${item.number}</span>${e(item.sourceTitle)}</h3><dl><div><dt>${t('原文定位','Source location')}</dt><dd>${e(item.locator)}</dd></div><div><dt>${t('资料状态','Availability')}</dt><dd>${e(available(item.availability))} · ${e(item.sourceType)}</dd></div><div><dt>${t('日期','Dates')}</dt><dd>${t('发布','Published')} ${e(item.publishedAt)} / ${t('可取得','Available')} ${e(item.availableAt)}</dd></div></dl>${item.availability === 'unavailable' ? `<p class="report-source-notice">${t('原文不可用，不能用材料缺失证明或反驳判断。','The source is unavailable. Missing material neither confirms nor refutes a judgment.')}</p>` : `<blockquote>${e(item.quote)}</blockquote>${item.context.map(p => `<p>${e(p)}</p>`).join('')}`}<p class="reference-limitation"><strong>${t('使用边界','Limitations')}</strong>${e(item.limitation)}</p></section>`).join('')}</details>`;
}
