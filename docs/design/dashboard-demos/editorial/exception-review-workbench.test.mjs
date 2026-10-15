import test from 'node:test';
import assert from 'node:assert/strict';
import {computeEvidenceBridge,evidenceBridgeBars,validateExceptionReviewState,reduceExceptionReviewState,REVIEW_RECORDS} from './exception-review-workbench.mjs';
test('complete bridge preserves signed and zero adjustments, matches final value',()=>{
 const result=computeEvidenceBridge({start:12,deltas:[{label:'growth',value:5},{label:'adjustment',value:-2},{label:'zero',value:0}],end:15});assert.deepEqual(result,{status:'reconciled',gaps:0,computed:15,residual:0,canDistribute:true});
});
test('missing values cannot be inferred from ending total or distributed',()=>{
 for(const input of [{start:80,deltas:[{label:'known',value:15},{label:'missing',value:null}],end:90},{start:null,deltas:[],end:90},{start:80,deltas:[],end:null}]){const result=computeEvidenceBridge(input);assert.equal(result.status,'gap');assert.equal(result.computed,null);assert.equal(result.residual,null);assert.equal(result.canDistribute,false);}
});
test('complete but mismatched bridge blocks distribution',()=>{const result=computeEvidenceBridge({start:80,deltas:[{label:'change',value:15}],end:90});assert.equal(result.status,'mismatch');assert.equal(result.computed,95);assert.equal(result.residual,-5);assert.equal(result.canDistribute,false);});
test('invalid numeric contracts and arithmetic overflow are rejected',()=>{
 for(const input of [{start:'80',deltas:[],end:80},{start:80,deltas:[{label:'missing'}],end:80},{start:NaN,deltas:[],end:80},{start:80,deltas:[{label:'x',value:Infinity}],end:80},{start:80,deltas:[{label:'',value:0}],end:80},{start:Number.MAX_VALUE,deltas:[{label:'x',value:Number.MAX_VALUE}],end:80}])assert.throws(()=>computeEvidenceBridge(input));
});
test('state transitions select, open excerpts, demonstrate completion and reset without mutating',()=>{
 const original=validateExceptionReviewState();const opened=reduceExceptionReviewState(original,{type:'open-source',id:'field-base'});assert.equal(original.source,null);assert.equal(opened.source,'field-base');const resolved=reduceExceptionReviewState(opened,{type:'show-resolved'});assert.equal(resolved.resolved,true);assert.equal(resolved.source,null);const resolvedExcerpt=reduceExceptionReviewState(resolved,{type:'open-source',id:'field-resolved'});assert.equal(resolvedExcerpt.source,'field-resolved');const selected=reduceExceptionReviewState(resolvedExcerpt,{type:'select',id:'common'});assert.equal(selected.resolved,true);assert.equal(selected.source,null);assert.equal(selected.selected,'common');assert.equal(reduceExceptionReviewState(selected,{type:'reset-example'}).resolved,false);assert.equal(reduceExceptionReviewState(opened,{type:'close-source'}).source,null);
});
test('strict state rejects unknown records, inaccessible excerpts and coercion',()=>{
 for(const input of [null,[],{selected:'unknown'},{resolved:'true'},{source:'aster-base'},{source:'field-resolved'},{extra:1}])assert.throws(()=>validateExceptionReviewState(input));assert.throws(()=>reduceExceptionReviewState({}, {type:'invented'}));assert.deepEqual(validateExceptionReviewState({selected:'aster',resolved:true,source:'aster-base'}),{selected:'aster',resolved:true,source:'aster-base'});
});
test('authored missing and completed examples differ only through explicit completion',()=>{
 const record=REVIEW_RECORDS.find(r=>r.id==='field');assert.equal(computeEvidenceBridge(record.bridge).canDistribute,false);assert.equal(computeEvidenceBridge(record.resolvedBridge).canDistribute,true);assert.equal(record.bridge.deltas[1].value,null);assert.equal(record.resolvedBridge.deltas[1].value,-5);assert.equal(REVIEW_RECORDS.filter(r=>computeEvidenceBridge(r.bridge).canDistribute).length,2);
});

test('proportional bridge uses running totals and one shared scale for signed deltas',()=>{
 const model=evidenceBridgeBars({start:80,deltas:[{label:'operations',value:15},{label:'adjustments',value:-5}],end:90});
 assert.equal(model.computed,90);assert.equal(model.max,95);assert.deepEqual(model.bars.map(b=>[b.from,b.to]),[[0,80],[80,95],[95,90],[0,90]]);
 assert.equal(model.bars[1].width,15/95*100);assert.equal(model.bars[2].width,5/95*100);assert.equal(model.bars[2].value,-5);
 assert.equal(evidenceBridgeBars({start:80,deltas:[{label:'missing',value:null}],end:90}),null);
 const signed=evidenceBridgeBars({start:-10,deltas:[{label:'change',value:30}],end:20});assert.equal(signed.min,-10);assert.equal(signed.max,20);assert.ok(signed.bars.every(b=>b.left>=0&&b.left+b.width<=100.000001));
});
