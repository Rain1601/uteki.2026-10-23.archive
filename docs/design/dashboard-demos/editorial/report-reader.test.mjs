import test from 'node:test';
import assert from 'node:assert/strict';
import {REPORT_FIGURE,validateReportFigure,resolveReportSection} from './report-reader.mjs';
test('chart and data representation preserve zero and unknown without coercion',()=>{
 const copy=validateReportFigure(REPORT_FIGURE);
 assert.equal(copy.rows.find(r=>r.id==='C').value,null);
 assert.equal(copy.rows.find(r=>r.id==='D').value,0);
 copy.rows[0].value=99;assert.equal(REPORT_FIGURE.rows[0].value,12);
 for(const value of [undefined,NaN,Infinity,'12'])assert.throws(()=>validateReportFigure({...REPORT_FIGURE,rows:[{id:'X',value}]}),/finite/);
});
test('figure requires explicit scope and unique records; no fallback identity or units',()=>{
 for(const name of ['id','unit','scope'])assert.throws(()=>validateReportFigure({...REPORT_FIGURE,[name]:''}),/Explicit/);
 assert.throws(()=>validateReportFigure({...REPORT_FIGURE,rows:[{id:'A',value:1},{id:'A',value:2}]}),/Unique/);
 assert.throws(()=>validateReportFigure({...REPORT_FIGURE,kind:'external-document'}),/Explicit/);
});
test('report hash resolution isolates report chapters and accepts encoded native anchors',()=>{
 assert.equal(resolveReportSection('#report-numbers'),'report-numbers');
 assert.equal(resolveReportSection('#report%2Dboundaries'),'report-boundaries');
 for(const hash of ['#rule-table','#report-other','#%QQ','',null])assert.equal(resolveReportSection(hash),null);
});

import {reportFigureGeometry,normalizeReportState,mountReportReader} from './report-reader.mjs';
import {REPORT_SPECIMENS} from './report-content.mjs';
test('signed geometry uses shared zero, positive/negative directions and dynamic slots',()=>{
 const geometry=reportFigureGeometry(REPORT_SPECIMENS[1].figures[0]);const [negative,zero,missing,positive]=geometry.rows;
 assert.equal(negative.y,geometry.zero);assert(negative.height>0);assert(negative.labelY>geometry.zero);
 assert.equal(zero.height,0);assert.equal(zero.value,0);assert.equal(missing.value,null);assert.equal(missing.height,0);
 assert(positive.y<geometry.zero);assert.equal(positive.y+positive.height,geometry.zero);
 const many=reportFigureGeometry({...REPORT_FIGURE,rows:Array.from({length:12},(_,i)=>({id:String(i),value:i}))});assert(many.width>560);assert.equal(many.rows.length,12);assert(new Set(many.rows.map(row=>row.x)).size===12);
});
test('zero-only, negative-only and extreme finite data produce finite geometry',()=>{
 for(const values of [[0,0],[null,null],[-8,-4],[1e308,-1e308],[1e-308,-1e-308]]){
  const geometry=reportFigureGeometry({...REPORT_FIGURE,rows:values.map((value,i)=>({id:String(i),value}))});
  assert(Number.isFinite(geometry.zero));for(const row of geometry.rows){for(const key of ['x','width','y','height','labelY'])assert(Number.isFinite(row[key]),key);assert(row.height>=0);}
 }
});
test('section resolver uses explicit different report chapter sets without fallback',()=>{
 const report=REPORT_SPECIMENS[1];assert.equal(resolveReportSection('#continuity-position',report),'continuity-position');assert.equal(resolveReportSection('#report-numbers',report),null);
});
test('reading state retains independent figures, chapter offset and details; old state supported',()=>{
 const report=REPORT_SPECIMENS[1],state=normalizeReportState({reportId:report.id,figureViews:{'signed-reading':'data','second-reading':'chart'},details:{'continuity-definitions':true},chapterId:'continuity-representation',offset:90,top:800,left:0},report);
 assert.equal(state.figureViews['signed-reading'],'data');assert.equal(state.figureViews['second-reading'],'chart');assert.equal(state.offset,90);assert.equal(state.details['continuity-definitions'],true);
 assert.equal(normalizeReportState({figureView:'data',top:1,left:0},report).figureViews['signed-reading'],'data');
});
test('unknown state identities or malformed coordinates fail explicitly',()=>{
 const report=REPORT_SPECIMENS[1],base={top:0,left:0};
 for(const invalid of [{...base,reportId:'other'},{...base,chapterId:'other'},{...base,offset:NaN},{...base,figureViews:{other:'chart'}},{...base,figureViews:{'signed-reading':'other'}},{...base,details:{other:true}},{...base,details:{'continuity-definitions':'open'}},{...base,top:Infinity}])assert.throws(()=>normalizeReportState(invalid,report),TypeError);
});
test('explicit null report fails before render; does not silently use specimen',()=>{assert.throws(()=>mountReportReader({ownerDocument:{}},{report:null}),/Explicit authored/);});
test('reading state rejects inherited object keys as unknown figures',()=>{assert.throws(()=>normalizeReportState({top:0,left:0,figureViews:{constructor:'data'}},REPORT_SPECIMENS[1]),/Known figure/);});
