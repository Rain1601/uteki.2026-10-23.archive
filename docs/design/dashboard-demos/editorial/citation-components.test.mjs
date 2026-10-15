import test from 'node:test';
import assert from 'node:assert/strict';
import {Citation,safeCitationHref,validateCitationSource,validateCitationSources} from './citation-components.mjs';
const source={id:'report-p1',title:'Report',text:'Original text',caption:'Author, 2026',kind:'local-document',locator:'Page 1',href:'./report.pdf#page=1'};
test('citation renderer escapes supplied labels and uses native buttons',()=>{
  const html=Citation({id:'report-p1',label:'[1] <img src=x> & "quote"'});
  assert.match(html,/type="button"/);assert.match(html,/aria-expanded="false"/);assert.match(html,/data-citation="report-p1"/);assert.match(html,/&lt;img src=x&gt;/);assert.doesNotMatch(html,/<img/);
  for(const id of ['1','x" onclick="','a b','../x']) assert.throws(()=>Citation({id,label:'1'}));
});
test('source model is detached, preserves original text and explicit provenance',()=>{
  const model=validateCitationSource(source); assert.deepEqual(model,source); model.text='Changed';assert.equal(source.text,'Original text');
  for(const key of ['id','title','text','caption','kind']) assert.throws(()=>validateCitationSource({...source,[key]:''}));
  assert.equal(validateCitationSource({...source,href:undefined,locator:undefined}).href,null);
  assert.throws(()=>validateCitationSource({...source,kind:'unchecked'}));
});
test('source arrays reject missing sources and duplicate identities',()=>{
  assert.throws(()=>validateCitationSources(null));assert.throws(()=>validateCitationSources([source,source]));
  assert.equal(validateCitationSources([source]).length,1);
});
test('source URLs preserve selected local paths and public http(s) links',()=>{
  for(const href of ['./report.pdf#page=1','./source.html?q=source','https://example.org/report#p1','http://localhost:8879/source']) assert.equal(safeCitationHref(href),href);
});
test('source URLs reject active protocols, credentials, traversal and protocol relative URLs',()=>{
  for(const href of ['javascript:alert(1)','data:text/html,x','//evil.test','./../report','./%2e%2e/report','./%252e%252e/report','https://u:p@example.org','./a\\b','./a%5cb','./x%0a','https://example.org/a b','./%zz','/report','https://u%40a@example.org']) assert.throws(()=>safeCitationHref(href),href);
});
