import test from 'node:test';import assert from 'node:assert/strict';
import {themes} from './tokens.mjs';import {contrastRatio,checkThemeTextRoles} from './theme-contrast.mjs';
test('contrast calculations have known endpoints, symmetry and reject unsupported inputs',()=>{
 assert.equal(contrastRatio('#000000','#ffffff'),21);assert.equal(contrastRatio('#112233','#112233'),1);assert.equal(contrastRatio('#abcdef','#123456'),contrastRatio('#123456','#abcdef'));
 for(const color of ['red','#fff','rgba(0,0,0,.5)',null])assert.throws(()=>contrastRatio(color,'#ffffff'));
});
test('built-in small-text semantic roles pass across supported opaque backgrounds',()=>{
 for(const [name,theme] of Object.entries(themes))for(const result of checkThemeTextRoles(theme))assert.ok(result.pass,`${name}: ${result.foreground}/${result.background} ${result.ratio}`);
 assert.equal(checkThemeTextRoles({...themes.paper,muted:themes.paper.accentSoft}).filter(r=>!r.pass).length,3);
});
