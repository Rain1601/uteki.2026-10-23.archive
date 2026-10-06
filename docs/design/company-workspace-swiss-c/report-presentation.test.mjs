import test from 'node:test';
import assert from 'node:assert/strict';
import { catalog, getReport } from './model.mjs';
import { buildReportPresentation, getReportSamplePdf, REPORT_PDF_SAMPLE_SCOPE, renderReportSections, renderEvidenceAppendix } from './report-presentation.mjs';

const scope = {...REPORT_PDF_SAMPLE_SCOPE};
test('presentation retains every report field and leaves the original dataset unchanged', () => {
  const before = JSON.stringify(catalog), p = buildReportPresentation(scope);
  assert.deepEqual(p.report, getReport(scope.companyId,scope.reportId,scope.version).report);
  assert.equal(JSON.stringify(catalog),before);
  for (let i=0;i<p.sections.length;i++) {
    assert.deepEqual(p.sections[i].paragraphs,p.report.sections[i].paragraphs);
    assert.deepEqual(p.sections[i].bullets,p.report.sections[i].bullets);
    assert.deepEqual(p.sections[i].table?.rows,p.report.sections[i].table?.rows);
  }
});
test('evidence numbers stay stable across sections; same title with different location is not merged', () => {
  const p = buildReportPresentation(scope);
  assert.equal(p.evidence.length,4);
  assert.deepEqual(p.evidence.map(e=>e.number),[1,2,3,4]);
  const sameTitle=p.evidence.filter(e=>e.sourceTitle==='虚构演示 · 需求与建设联合简报');
  assert.equal(sameTitle.length,2); assert.notEqual(sameTitle[0].locator,sameTitle[1].locator);
  assert.equal(p.sections.find(s=>s.id==='thesis').citations[0].number,p.sections.find(s=>s.id==='support').citations[0].number);
  assert.equal(renderReportSections(p).match(/id="cite-support-demo-alpha-use-later"/g).length,1);
});
test('missing, blank, wrong company, Manager, report version and language are rejected', () => {
  for (const key of Object.keys(scope)) {
    const missing={...scope}; delete missing[key]; assert.throws(()=>buildReportPresentation(missing),/explicit/);
    assert.throws(()=>buildReportPresentation({...scope,[key]:' '}),/explicit/);
  }
  assert.throws(()=>buildReportPresentation({...scope,companyId:'microsoft'}),/different company/);
  assert.throws(()=>buildReportPresentation({...scope,managerId:'field'}),/different Manager/);
  assert.throws(()=>buildReportPresentation({...scope,reportId:'no-report'}),/unknown/);
  assert.throws(()=>buildReportPresentation({...scope,version:'v900'}),/unknown/);
  assert.throws(()=>buildReportPresentation({...scope,language:'en'}),/language/);
});
test('other reports and historical editions remain independently readable without a sample download', () => {
  for(const s of [{...scope,version:'v1'},{...scope,managerId:'field',reportId:'alpha-field-main'},{...scope,companyId:'microsoft',reportId:'ms-north-main',version:'v1'}]) {
    const p=buildReportPresentation(s); assert.deepEqual(p.scope,s); assert.equal(getReportSamplePdf(s),null);
  }
  assert.match(getReportSamplePdf(scope).href,/output\/pdf\/uteki-research-sample\.pdf$/);
  assert.equal(getReportSamplePdf({...scope,language:'en'}),null);
  assert.equal(getReportSamplePdf({}),null);
});

function independentFixture() {
  return {companies:[{id:'independent-company',name:'Independent'}],managers:[{id:'independent-analyst',name:'Analyst'}],events:[],
    reports:[{id:'independent-report',companyId:'independent-company',managerId:'independent-analyst',kind:'topic',title:'Independent report',versions:[{version:'r1',language:'zh-CN',title:'A & B',sections:[{id:'sample',kicker:'Sample',title:'<Title>',paragraphs:['Keep <every> paragraph.'],citations:['independent-source'],table:{columns:['Code','Amount'],rows:[['100','42.5']]}}]}]}],
    evidence:[{id:'independent-source',companyId:'independent-company',sourceTitle:'<Source>',language:'zh-CN',availability:'excerpt',locator:'Section 1',quote:'<Quote>',context:['Context & limit'],limitation:'No inference',publishedAt:'2026-01-01',availableAt:'2026-01-02',isDemo:true}]};
}
const independentScope={companyId:'independent-company',managerId:'independent-analyst',reportId:'independent-report',version:'r1',language:'zh-CN'};
test('independent data uses declared column semantics, never infers a numeric-looking code', () => {
  const data=independentFixture();
  const p=buildReportPresentation(independentScope,data,{tables:{sample:{columns:[{kind:'text'},{kind:'numeric'}]}}});
  assert.deepEqual(p.sections[0].table.columns.map(c=>c.align),['left','right']);
  const html=renderReportSections(p);
  assert.match(html,/text-align:left">100<\/td>/); assert.match(html,/text-align:right">42\.5<\/td>/);
  assert.match(html,/&lt;Title&gt;/); assert.doesNotMatch(html,/<Title>/);
  assert.match(renderEvidenceAppendix(p),/&lt;Quote&gt;/);
  assert.equal(buildReportPresentation(independentScope,data).sections[0].table.columns[1].kind,'text');
});
test('declared columns and table shapes must agree; unused presentation configs are rejected', () => {
  assert.throws(()=>buildReportPresentation(independentScope,independentFixture(),{tables:{sample:{columns:[{kind:'text'}]}}}),/count differs/);
  assert.throws(()=>buildReportPresentation(independentScope,independentFixture(),{tables:{sample:{columns:[{kind:'text'},{kind:'guess'}]}}}),/unsupported/);
  assert.throws(()=>buildReportPresentation(independentScope,independentFixture(),{tables:{missing:{columns:[]}}}),/unknown table/);
  const data=independentFixture();data.reports[0].versions[0].sections[0].table.rows[0].pop();
  assert.throws(()=>buildReportPresentation(independentScope,data),/row width/);
});
test('cross-company citations fail rather than borrowing evidence', () => {
  const data=independentFixture();data.evidence[0].companyId='another-company';
  assert.throws(()=>buildReportPresentation(independentScope,data),/different company/);
});
test('unavailable evidence keeps the explicit gap; no fabricated quote or download', () => {
  const p=buildReportPresentation({...scope,companyId:'microsoft',reportId:'ms-north-main',version:'v1'});
  const gap=p.evidence.find(e=>e.availability==='unavailable');
  assert.equal(gap.quote,'');assert.deepEqual(gap.context,[]);
  const html=renderEvidenceAppendix(p,{uiLanguage:'en'});
  assert.match(html,/The source is unavailable/);assert.doesNotMatch(html,/download=/);
  assert.match(renderReportSections(p,{uiLanguage:'en'}),new RegExp(p.sections[0].paragraphs[0]));
});
