import test from 'node:test';
import assert from 'node:assert/strict';
import {StoryLead,PullQuote,stepAt,validateExplainer} from './story-components.mjs';
test('timeline boundaries and end remain on valid steps',()=>{
 assert.equal(stepAt(-1,4),0);assert.equal(stepAt(.249,4),0);assert.equal(stepAt(.25,4),1);assert.equal(stepAt(1,4),3);assert.equal(stepAt(10,4),3);assert.throws(()=>stepAt(NaN,4));
});
test('contract rejects ambiguous identity and invalid duration',()=>{
 const steps=[{id:'a',title:'A',body:'A'},{id:'b',title:'B',body:'B'}];
 const c=validateExplainer({steps});c.steps[0].title='Changed';assert.equal(steps[0].title,'A');
 assert.throws(()=>validateExplainer({steps:[steps[0],steps[0]]}));assert.throws(()=>validateExplainer({steps,duration:Infinity}));assert.throws(()=>validateExplainer({steps:[]}));
});
test('story facts preserve zero, negatives and missing; text is escaped',()=>{
 const html=StoryLead({eyebrow:'Test',title:'<img>',summary:'A & B',facts:[{label:'zero',value:0},{label:'negative',value:-3},{label:'missing',value:null}]});
 assert.match(html,/&lt;img&gt;/);assert.match(html,/>0</);assert.match(html,/>-3</);assert.match(html,/>—</);
 assert.doesNotMatch(PullQuote({text:'<script>',attribution:'<b>'}),/<script>/);
});
