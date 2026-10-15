import test from 'node:test';
import assert from 'node:assert/strict';
import {createReadingSession,validateReadingSession,updateReadingRecord,readSession,writeSession,reportLibraryRows} from './reading-session.mjs';
const ids=['one','two'];
const state={top:320,left:0,chapterId:'second',offset:14,figureViews:{trend:'data'},details:{method:true}};
test('reading identity and independent bookmarks survive serialization without mutating callers',()=>{
 const original=createReadingSession();const next=updateReadingRecord(original,'one',state,{updatedAt:5},ids);
 const another=updateReadingRecord(next,'two',{...state,top:0},{status:'completed',updatedAt:6},ids);
 assert.equal(Object.keys(original.reports).length,0);assert.equal(another.reports.one.state.top,320);assert.equal(another.reports.two.status,'completed');
 let raw;const storage={setItem:(_,v)=>raw=v,getItem:()=>raw};assert.equal(writeSession(storage,another,ids).status,'saved');assert.deepEqual(readSession(storage,ids).value,another);
 state.figureViews.trend='chart';assert.equal(another.reports.one.state.figureViews.trend,'data');state.figureViews.trend='data';
});
test('unknown reports and invalid reading state fail; unavailable or corrupt persistence is explicit',()=>{
 assert.throws(()=>updateReadingRecord(createReadingSession(),'missing',state,{updatedAt:1},ids));
 assert.throws(()=>updateReadingRecord(createReadingSession(),'one',{...state,top:NaN},{updatedAt:1},ids));
 const broken={getItem:()=>'{',setItem:()=>{throw new Error('disabled')}};
 assert.equal(readSession(broken,ids).status,'invalid');assert.equal(writeSession(broken,createReadingSession(),ids).status,'unavailable');
 assert.throws(()=>validateReadingSession({...createReadingSession(),library:{...createReadingSession().library,focus:'missing'}},ids));
});
test('catalog search and status intersect, preserve input and do not imply completion by scrolling',()=>{
 const reports=[{id:'one',title:{zh:'乙',en:'Beta'},deck:{zh:'范围',en:'Scope'},date:'2026-10-09'},{id:'two',title:{zh:'甲',en:'Alpha'},date:'2026-10-10'}];
 const library={...createReadingSession().library,query:'scope'};
 assert.deepEqual(reportLibraryRows(reports,library).map(r=>r.id),['one']);
 assert.deepEqual(reportLibraryRows(reports,{...library,query:'',filter:'completed'},{one:{status:'started'},two:{status:'completed'}}).map(r=>r.id),['two']);
 assert.equal(reports[0].id,'one');assert.deepEqual(reportLibraryRows(reports,{...library,query:'',sort:'title-asc'}).map(r=>r.id),['two','one']);
});

test('Paper Night appearance preserves independent reading records and library state',()=>{
 const session=updateReadingRecord(createReadingSession(),'one',state,{updatedAt:8},ids);session.library.query='scope';session.appearance.palette='paper-night';
 let raw;const storage={setItem:(_,v)=>raw=v,getItem:()=>raw};writeSession(storage,session,ids);const saved=readSession(storage,ids);assert.equal(saved.status,'saved');assert.deepEqual(saved.value,session);
 saved.value.appearance.palette='paper';assert.deepEqual(validateReadingSession(saved.value,ids).reports,session.reports);
});
