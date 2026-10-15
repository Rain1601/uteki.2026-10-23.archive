import test from 'node:test';
import assert from 'node:assert/strict';
import {Card,ItemList,validateCard,validateItemList} from './compound-components.mjs';
test('cards escape all caller content and separate actions from article',()=>{
 const html=Card({id:'review_81',title:'<script>oops</script>',eyebrow:'A & B',description:'"quoted"',meta:"it's",status:'waiting',actions:[{id:'open',label:'Open <detail>'},{id:'cancel',label:'Cancel',disabled:true}]});
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(html.includes('A &amp; B'));assert.ok(html.includes('&#39;'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('data-card-action="open"'));assert.ok(html.includes(' disabled'));assert.equal((html.match(/<button/g)||[]).length,2);
});
test('list selection follows unrelated identities rather than position',()=>{
 const input={id:'queue',label:'Research',items:[{id:'delta_17',title:'One'},{id:'zebra_98',title:'Two',description:'<x>',meta:'3 files',status:'ready'}],selected:'zebra_98'};
 const html=ItemList(input);assert.ok(html.includes('data-item-id="zebra_98" aria-current="true"'));assert.ok(!html.includes('data-item-id="delta_17" aria-current'));assert.ok(html.includes('&lt;x&gt;'));assert.ok(html.includes('<ul>'));assert.equal(validateItemList(input).items.length,2);
});
test('invalid identities, titles, status, actions and duplicates reject',()=>{
 for(const input of [{id:'x"',title:'A'},{id:'x',title:''},{id:'x',title:'A',status:'invented'},{id:'x',title:'A',selected:'yes'},{id:'x',title:'A',actions:[{id:'execute',label:'X'}]},{id:'x',title:'A',actions:[{id:'open',label:'A'},{id:'open',label:'B'}]}]) assert.throws(()=>Card(input),TypeError);
 assert.throws(()=>ItemList({id:'list',label:'Items',items:[{id:'a',title:'A'},{id:'a',title:'B'}]}),/Duplicate/);
 assert.throws(()=>ItemList({id:'list',label:'Items',items:[],selected:'missing'}),/selected/);
});
test('empty list stays semantic and escapes caller empty copy',()=>{
 const html=ItemList({id:'empty',label:'No attachments',items:[],emptyText:'Drop <files>'});assert.ok(html.includes('aria-label="No attachments"'));assert.ok(html.includes('Drop &lt;files&gt;'));assert.ok(!html.includes('<button'));
});
test('normalized models detach caller action and item records',()=>{
 const action={id:'open',label:'Open'},item={id:'one',title:'One'};
 const card=validateCard({id:'card',title:'Card',actions:[action]}),list=validateItemList({id:'list',label:'List',items:[item]});
 action.label='Changed';item.title='Changed';assert.equal(card.actions[0].label,'Open');assert.equal(list.items[0].title,'One');assert.deepEqual(validateCard({id:'plain',title:'Plain'}).actions,[]);
});

test('status labels localize display while preserving semantic state and escaping',()=>{
 const card=Card({id:'localized',title:'任务',status:'waiting',statusLabel:'待确认 <来源>'});
 const list=ItemList({id:'trace',label:'过程',items:[{id:'done',title:'完成',status:'completed',statusLabel:'已完成 & 已检查'}]});
 assert.ok(card.includes('data-status="waiting">待确认 &lt;来源&gt;'));assert.ok(list.includes('data-status="completed">已完成 &amp; 已检查'));
});
