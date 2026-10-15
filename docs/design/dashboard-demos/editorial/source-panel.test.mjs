import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveSourceSelection, restoreReadingPosition, filterSourceExcerpts} from './source-panel.mjs';
const sources = [
  {id:'contract',title:'Layout contract',text:'Original rule',caption:'Project contract',kind:'local-document',locator:'§ 3',href:'./contract.html'},
  {id:'specimen',title:'Research specimen',text:'Original sample',caption:'Authored specimen',kind:'authored-specimen'}
];
test('source selection uses exact stable identity independent of ordering', () => {
  const selected = resolveSourceSelection([...sources].reverse(), 'contract');
  assert.equal(selected.text,'Original rule'); assert.equal(selected.locator,'§ 3'); assert.equal(selected.href,'./contract.html');
  selected.text = 'Changed'; assert.equal(sources[0].text,'Original rule');
});
test('unknown, blank and duplicate source identities fail instead of choosing another excerpt', () => {
  for(const id of ['missing','',undefined]) assert.throws(() => resolveSourceSelection(sources,id), /Unknown source/);
  assert.throws(() => resolveSourceSelection([...sources,sources[0]],'contract'), /Duplicate/);
});
test('source panel inherits source URL validation', () => {
  assert.throws(() => resolveSourceSelection([{...sources[0],href:'javascript:alert(1)'}],'contract'), /Source URL/);
  assert.throws(() => resolveSourceSelection([{...sources[0],href:'./%2e%2e/private'}],'contract'), /Unsafe/);
});
test('reading return restores both axes including zero', () => {
  const reader = {scrollTop:400,scrollLeft:35};
  restoreReadingPosition(reader,{top:123,left:17}); assert.deepEqual(reader,{scrollTop:123,scrollLeft:17});
  restoreReadingPosition(reader,{top:0,left:0}); assert.deepEqual(reader,{scrollTop:0,scrollLeft:0});
  assert.throws(() => restoreReadingPosition(reader,{top:NaN,left:0}), /finite/);
});
test('directory search matches supplied title, caption, locator and exact excerpt fields', () => {
  assert.deepEqual(filterSourceExcerpts(sources,'LAYOUT').map(s => s.id), ['contract']);
  assert.deepEqual(filterSourceExcerpts(sources,'Project § 3').map(s => s.id), ['contract']);
  assert.deepEqual(filterSourceExcerpts(sources,'original sample').map(s => s.id), ['specimen']);
  assert.deepEqual(filterSourceExcerpts(sources,'unavailable'), []);
});
test('empty and normalized searches retain supplied order without modifying originals', () => {
  const original = JSON.stringify(sources);
  assert.deepEqual(filterSourceExcerpts(sources,' \t '), sources);
  assert.deepEqual(filterSourceExcerpts(sources,'ＬＡＹＯＵＴ').map(s => s.id), ['contract']);
  filterSourceExcerpts(sources,'rule')[0].text = 'changed result';
  assert.equal(JSON.stringify(sources), original);
});
test('directory search handles Chinese and literal markup as text without altering excerpts', () => {
  const records = [{...sources[0],title:'中文来源',text:'正文 <script> 字面原文'}];
  assert.equal(filterSourceExcerpts(records,'中文 正文')[0].text, records[0].text);
  assert.equal(filterSourceExcerpts(records,'<script>')[0].text, records[0].text);
});
test('search rejects invalid queries and invalid identities rather than repairing source scope', () => {
  assert.throws(() => filterSourceExcerpts(sources,null), /query must be text/);
  assert.throws(() => filterSourceExcerpts([...sources,sources[0]],''), /Duplicate/);
  assert.throws(() => resolveSourceSelection(filterSourceExcerpts(sources,'sample'),'contract'), /Unknown source/);
});

test('portal defaults preserve body and scoped themes can share an explicit host',async()=>{const {resolveSourcePortal}=await import('./source-panel.mjs');const doc={};doc.body={ownerDocument:doc,append(){}};const host={ownerDocument:doc,append(){}};assert.equal(resolveSourcePortal(host),doc.body);assert.equal(resolveSourcePortal(host,host),host);assert.throws(()=>resolveSourcePortal(host,{ownerDocument:{},append(){}}),/host document/);assert.throws(()=>resolveSourcePortal(host,{ownerDocument:doc}),/appendable/);});
