import test from 'node:test';import assert from 'node:assert/strict';import {access} from 'node:fs/promises';
import {COMPONENT_CATALOG,PAGE_CATALOG,filterComponentCatalog} from './system-catalog.mjs';
test('current inventory points to real exported interfaces and local style dependencies',async()=>{
 assert.equal(new Set(COMPONENT_CATALOG.map(c=>c.id)).size,COMPONENT_CATALOG.length);
 for(const item of COMPONENT_CATALOG){const module=await import(`./${item.file}`);for(const api of item.exports)assert.equal(typeof module[api],'function',`${item.id}/${api}`);for(const css of item.css)await access(new URL(css,import.meta.url));}
});
test('catalog search distinguishes reusable APIs from task templates',()=>{
 assert.equal(filterComponentCatalog('mountReportReader','api')[0].id,'report');assert.equal(filterComponentCatalog('mountReportReader','template').length,0);
 assert.equal(filterComponentCatalog('Card')[0].id,'content');assert.throws(()=>filterComponentCatalog('', 'production'));
 for(const item of PAGE_CATALOG)assert.ok(item.href.startsWith('./'));
});
