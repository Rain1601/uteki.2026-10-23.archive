import test from 'node:test';import assert from 'node:assert/strict';import {lensGeometry} from './image-inspector.mjs';
test('lens clamps to image edges and magnified coordinates show the same point',()=>{
 for(const [x,y] of [[.5,.5],[-1,-2],[2,3]]){
 const g=lensGeometry({width:640,height:360,x,y,zoom:3});assert.ok(g.left>=0&&g.top>=0&&g.left+g.size<=640&&g.top+g.size<=360);
 assert.equal(g.backgroundX+g.x*640*3,g.size/2);assert.equal(g.backgroundY+g.y*360*3,g.size/2);
 }
});
test('small images constrain lens size; invalid geometry fails explicitly',()=>{
 assert.ok(lensGeometry({width:80,height:45,x:.5,y:.5,zoom:2}).size<=36);
 assert.throws(()=>lensGeometry({width:0,height:300,x:0,y:0,zoom:2}));assert.throws(()=>lensGeometry({width:500,height:300,x:NaN,y:0,zoom:2}));
});
