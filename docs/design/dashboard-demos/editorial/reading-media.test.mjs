import test from 'node:test';
import assert from 'node:assert/strict';
import {curvePoint,mediaSource} from './reading-media.mjs';
test('curve geometry reaches endpoints and stays bounded throughout',()=>{
 assert.deepEqual(curvePoint(0),{x:70,y:250});assert.deepEqual(curvePoint(1),{x:530,y:60});
 let previous=0;for(let i=0;i<=100;i++){const p=curvePoint(i/100);assert.ok(p.x>=previous&&p.x<=530);assert.ok(p.y>=60&&p.y<=250);previous=p.x;}
 assert.throws(()=>curvePoint(NaN));assert.throws(()=>curvePoint(-1));
});
test('media input accepts explicit files and rejects executable or blank URLs',()=>{
 assert.equal(mediaSource('media/line-study.mp4'),'media/line-study.mp4');assert.equal(mediaSource('https://example.com/movie.mp4'),'https://example.com/movie.mp4');
 for(const src of ['',null,'javascript:alert(1)','data:text/html,hello','file:///private/file','a b.mp4'])assert.throws(()=>mediaSource(src));
});
