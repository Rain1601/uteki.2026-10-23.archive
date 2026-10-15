import test from 'node:test';
import assert from 'node:assert/strict';
import {REPORT_SPECIMENS,getReportSpecimen,validateReportContent,validateReportFigure} from './report-content.mjs';
const copy=()=>structuredClone(REPORT_SPECIMENS[0]);
test('explicit report specimens have different chapter counts and figure data',()=>{
 assert.equal(getReportSpecimen('editorial-reading').sections.length,3);assert.equal(getReportSpecimen('reading-continuity').sections.length,2);
 assert.equal(getReportSpecimen('reading-continuity').figures.length,2);assert.equal(getReportSpecimen('missing'),null);assert.equal(getReportSpecimen(undefined),null);
 for(const report of REPORT_SPECIMENS){assert.equal(validateReportContent(report).id,report.id);assert.match(report.date,/^\d{4}-\d{2}-\d{2}$/);}
});
test('content requires caller identity, bilingual scope and declared specimen status',()=>{
 for(const field of ['id','kind','title','kicker','deck','scope','date','sections','figures','sources','summaries']){const r=copy();delete r[field];assert.throws(()=>validateReportContent(r),TypeError,field);}
 assert.throws(()=>validateReportContent(null),/Explicit/);const r=copy();r.title={zh:'',en:'Title'};assert.throws(()=>validateReportContent(r),/nonempty/);
});
test('section summary and figure identity do not infer missing or duplicate bindings',()=>{
 let r=copy();r.sections.push(r.sections[0]);assert.throws(()=>validateReportContent(r),/Duplicate section/);
 r=copy();r.summaries[0].sectionId='unknown';assert.throws(()=>validateReportContent(r),/chapter/);
 r=copy();r.summaries[0].kind='fact';assert.throws(()=>validateReportContent(r),/summary kind/);
 r=copy();r.sections[1].blocks.find(b=>b.type==='figure').figureId='unknown';assert.throws(()=>validateReportContent(r),/Unknown figure/);
 r=copy();r.figures.push(r.figures[0]);assert.throws(()=>validateReportContent(r),/Duplicate figure/);
 r=copy();r.sections[1].blocks=r.sections[1].blocks.filter(b=>b.type!=='figure');assert.throws(()=>validateReportContent(r),/Unplaced/);
});
test('sources are explicit safe excerpts; unknown citations are rejected before mounting',()=>{
 let r=copy();r.sections[0].blocks.find(b=>b.sourceIds).sourceIds=['unknown'];assert.throws(()=>validateReportContent(r),/Unknown source/);
 r=copy();r.sources[0].href='javascript:alert(1)';assert.throws(()=>validateReportContent(r),/Source URL/);
 r=copy();r.sources.push(r.sources[0]);assert.throws(()=>validateReportContent(r),/Duplicate citation/);
 r=copy();r.sections[0].blocks[0].sourceIds=['rule-table','rule-table'];assert.throws(()=>validateReportContent(r),/unique sourceIds/);
});
test('values preserve arbitrary record counts, negative, zero, null and detached row copies',()=>{
 const figure=REPORT_SPECIMENS[1].figures[0],checked=validateReportFigure(figure);assert.deepEqual(checked.rows.map(r=>r.value),[-8,0,null,12]);checked.rows[0].value=100;assert.equal(figure.rows[0].value,-8);
 for(const value of [undefined,NaN,Infinity,-Infinity,'0',false])assert.throws(()=>validateReportFigure({...figure,rows:[{id:'sample',value}]}),/finite/);
});
test('unsupported blocks, duplicate details and unsafe identities are rejected',()=>{
 let r=copy();r.sections[0].blocks[0].type='html';assert.throws(()=>validateReportContent(r),/Unknown report block/);
 r=copy();r.sections[0].id='unsafe"';assert.throws(()=>validateReportContent(r),/safe identity/);
 r=copy();r.sections[1].blocks.push(r.sections[1].blocks.find(b=>b.type==='details'));assert.throws(()=>validateReportContent(r),/Duplicate details/);
});
test('validated model is detached from callers and rejects invalid dates and DOM collisions',()=>{
 let r=copy(),checked=validateReportContent(r);checked.title.zh='changed';checked.sections[0].title.zh='changed';checked.sections[0].blocks[0].text.zh='changed';assert.notEqual(r.title.zh,'changed');assert.notEqual(r.sections[0].title.zh,'changed');assert.notEqual(r.sections[0].blocks[0].text.zh,'changed');
 for(const date of ['2026-02-30','today','2026-13-01']){r=copy();r.date=date;assert.throws(()=>validateReportContent(r),/ISO/);}
 r=copy();r.sections[0].id='reading-specimen-title';r.summaries[0].sectionId=r.sections[0].id;assert.throws(()=>validateReportContent(r),/DOM identity/);
});

test('research-method specimen migrates the same contract with four chapters and two distinct figures',()=>{
 const report=validateReportContent(getReportSpecimen('evidence-to-judgment'));assert.equal(report.sections.length,4);assert.equal(report.figures.length,2);assert.deepEqual(report.figures[0].rows.map(r=>r.value),[16,-9,0,7,null,-3]);assert.equal(report.figures[1].rows.length,3);assert.equal(new Set(REPORT_SPECIMENS.map(r=>r.id)).size,REPORT_SPECIMENS.length);
});
