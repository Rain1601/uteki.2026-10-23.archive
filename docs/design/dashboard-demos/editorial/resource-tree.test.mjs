import test from 'node:test';
import assert from 'node:assert/strict';
import {validateResourceTree, flattenVisible, safeResourceHref, ResourceTree} from './resource-tree.mjs';
const leaf = (id = 'pdf') => ({id,label:'报告',kind:'PDF',href:'media/report.pdf'});
const input = () => ({nodes:[{id:'docs',label:'Documents',children:[leaf(),{id:'other',label:'Other',children:[leaf('video')]}]}],selected:'pdf',labels:{region:'目录',empty:'暂无资源'}});
test('visible navigation includes only children of open folders and retains parent identity', () => {
 const nodes = validateResourceTree(input()).nodes;
 assert.deepEqual(flattenVisible(nodes).map(row=>row.node.id), ['docs']);
 const visible = flattenVisible(nodes,new Set(['docs']));
 assert.deepEqual(visible.map(row=>row.node.id), ['docs','pdf','other']);
 assert.equal(visible[1].parent,'docs');
 assert.deepEqual(flattenVisible(nodes,new Set(['docs','other'])).map(row=>row.node.id), ['docs','pdf','other','video']);
});
test('duplicate and invalid identities, malformed folders, invalid selection rejected', () => {
 const data=input(); data.nodes[0].children.push(leaf());
 assert.throws(()=>validateResourceTree(data), /duplicate/);
 assert.throws(()=>validateResourceTree({...input(),selected:'docs'}), /leaf/);
 assert.throws(()=>validateResourceTree({ ...input(),nodes:[{...leaf(),id:'bad"id'}]}), /identity/);
 assert.throws(()=>validateResourceTree({...input(),nodes:[{id:'folder',label:'F',children:[],href:'a.pdf'}]}), /Folders/);
});
test('safe sources are explicit local paths or HTTP(S); active and ambiguous URLs rejected', () => {
 for(const url of ['media/a.pdf','/editorial/a.pdf','../a.pdf','https://example.com/a.pdf','http://127.0.0.1:8879/a.pdf']) assert.equal(safeResourceHref(url),url);
 for(const url of ['javascript:alert(1)','data:text/html,x','file:///a.pdf','//example.com/a',' https://a.test','a\\b','https://user:pass@example.com/a']) assert.throws(()=>safeResourceHref(url));
});
test('markup escapes labels, derives counts, opens selected ancestors and never renders navigation href', () => {
 const data=input(); data.nodes[0].label='<script>&"'; data.nodes[0].children[0].description='a<b';
 const html=ResourceTree(data);
 assert.match(html,/&lt;script&gt;&amp;&quot;/);
 assert.match(html,/a&lt;b/);
 assert.match(html,/data-folder="docs" open/);
 assert.match(html,/resource-tree-count" aria-label="2"/);
 assert.match(html,/aria-current="true"/);
 assert.doesNotMatch(html,/href=|<script>/);
 assert.equal((html.match(/<details/g)||[]).length,(html.match(/<\/details>/g)||[]).length);
 assert.equal((html.match(/<ul>/g)||[]).length,(html.match(/<\/ul>/g)||[]).length);
});
test('empty root and empty folder stay explicit',()=>{
 assert.match(ResourceTree({...input(),nodes:[],selected:null}),/暂无资源/);
 assert.match(ResourceTree({...input(),nodes:[{id:'folder',label:'F',children:[]}],selected:null}),/aria-label="0"/);
});
