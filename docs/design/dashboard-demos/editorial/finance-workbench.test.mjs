import test from 'node:test';
import assert from 'node:assert/strict';
import {summarizeInvoices,validateFinanceViewState,FINANCE_INVOICES,FINANCE_AS_OF} from './finance-workbench.mjs';
const row=(id,changes={})=>({id,client:'Synthetic A',date:'2026-09-01',dueDate:'2026-09-30',amount:100,received:0,...changes});
test('cutoff keeps due-today open, partial receipts overdue, future invoices out',()=>{
 const s=summarizeInvoices([row('today'),row('partial',{dueDate:'2026-09-29',received:40}),row('future',{date:'2026-10-01',dueDate:'2026-11-01'})],{asOf:'2026-09-30'});
 assert.equal(s.invoiced,200);assert.equal(s.received,40);assert.equal(s.outstanding,160);assert.equal(s.overdue,60);assert.equal(s.rows[0].status,'open');assert.equal(s.rows[0].overdueDays,0);assert.equal(s.rows[1].overdueDays,1);assert.deepEqual(s.aging.map(a=>a.amount),[100,60,0,0]);
});
test('null amounts stay unknown while zero is an actual settled amount',()=>{
 const s=summarizeInvoices([row('gap',{amount:null,received:12}),row('zero',{amount:0}),row('paid',{received:100})],{asOf:'2026-09-30'});
 assert.equal(s.unknownAmountCount,1);assert.equal(s.knownCount,2);assert.equal(s.received,112);assert.equal(s.outstanding,0);assert.equal(s.rows[0].outstanding,null);assert.equal(s.rows[0].overdueDays,null);assert.equal(s.rows[0].status,'gap');assert.equal(s.rows[1].status,'paid');assert.equal(s.rows[1].amount,0);
});
test('aging boundaries use whole UTC calendar days and unpaid balances',()=>{
 const s=summarizeInvoices([row('d30',{date:'2026-07-01',dueDate:'2026-08-31',received:20}),row('d31',{date:'2026-07-01',dueDate:'2026-08-30'}),row('d60',{date:'2026-07-01',dueDate:'2026-08-01'}),row('d61',{date:'2026-07-01',dueDate:'2026-07-31'}),row('settled',{date:'2026-07-01',dueDate:'2026-07-31',received:100})],{asOf:'2026-09-30'});
 assert.deepEqual(s.aging.map(a=>a.amount),[0,80,200,100]);assert.equal(s.overdue,380);assert.equal(s.rows.at(-1).status,'paid');
});
test('month and client compose as invoice cohorts, never change cutoff receipt interpretation',()=>{
 const input=[row('sep'),row('aug',{date:'2026-08-01'}),row('other',{client:'Synthetic B'})];const s=summarizeInvoices(input,{asOf:'2026-09-30',month:'2026-09',client:'Synthetic A'});assert.deepEqual(s.rows.map(r=>r.id),['sep']);assert.equal(s.invoiced,100);assert.equal(summarizeInvoices(input,{asOf:'2026-09-30',client:'missing'}).rows.length,0);assert.equal(input[0].outstanding,undefined);
});
test('strict dates, duplicate identities, unsupported amounts and excess receipts fail',()=>{
 for(const changes of [{date:'2026-02-30'},{date:'2026-2-01'},{dueDate:'2026-08-31'},{amount:-1},{amount:undefined},{amount:NaN},{received:-1},{received:101},{received:Infinity},{client:''}])assert.throws(()=>summarizeInvoices([row('a',changes)],{asOf:'2026-09-30'}));assert.throws(()=>summarizeInvoices([row('a'),row('a')],{asOf:'2026-09-30'}));assert.throws(()=>summarizeInvoices([],{asOf:'2026-09-31'}));assert.throws(()=>summarizeInvoices([],{asOf:'2026-09-30',month:'2026-13'}));
});
test('fixed synthetic fixture known-subtotal reconciliation',()=>{
 const s=summarizeInvoices(FINANCE_INVOICES,{asOf:FINANCE_AS_OF});assert.equal(s.rows.length,9);assert.equal(s.invoiced,460000);assert.equal(s.received,259000);assert.equal(s.outstanding,201000);assert.equal(s.overdue,102000);assert.equal(s.unknownAmountCount,1);assert.equal(s.invoiced-s.received,s.outstanding);assert.equal(s.aging.reduce((n,a)=>n+a.amount,0),s.outstanding);
});

test('year zero and overflowing financial totals are rejected',()=>{
 assert.throws(()=>summarizeInvoices([row('zeroYear',{date:'0000-01-01'})],{asOf:'2026-09-30'}));
 assert.throws(()=>summarizeInvoices([row('huge1',{amount:Number.MAX_VALUE}),row('huge2',{amount:Number.MAX_VALUE})],{asOf:'2026-09-30'}),/overflow/);
});

test('view state round-trip validates against an independent record list',()=>{
 const rows=[row('independent',{client:'Independent Client',date:'2026-04-01',dueDate:'2026-04-30'})];
 const state={month:'2026-04',client:'Independent Client',sort:'outstanding',ascending:true,selected:'independent'};
 assert.deepEqual(validateFinanceViewState(state,rows),state);
 assert.deepEqual(validateFinanceViewState({},rows),{month:'',client:'',sort:'date',ascending:false,selected:null});
 for(const change of [{month:'2026-09'},{client:'Aster Studio'},{sort:'status'},{ascending:'true'},{selected:'INV-0701'},{unexpected:1}])assert.throws(()=>validateFinanceViewState({...state,...change},rows));
 assert.throws(()=>validateFinanceViewState(null,rows));
 // A known invoice may be outside the currently filtered scope; rendering clears it.
 assert.equal(validateFinanceViewState({month:'2026-09',selected:'INV-0701'}).selected,'INV-0701');
});
