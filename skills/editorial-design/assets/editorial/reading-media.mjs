import {esc} from './components.mjs';
let serial=0;
export function mediaSource(src) {
  if(typeof src!=='string'||!src.trim()||/[\u0000-\u0020]/.test(src))throw new TypeError('Explicit media URL required');
  const url=new URL(src,'https://local.invalid/');
  if(!['http:','https:'].includes(url.protocol))throw new TypeError('Unsupported media URL');
  return src;
}
export function curvePoint(t){
  if(!Number.isFinite(t)||t<0||t>1)throw new TypeError('Progress out of range');
  const u=1-t;
  return {x:u*u*u*70+3*u*u*t*240+3*u*t*t*350+t*t*t*530,y:u*u*u*250+3*u*u*t*248+3*u*t*t*65+t*t*t*60};
}

export function createArticleVideo({src,poster,title,captionSrc,labels}){
  const content=document.createElement('div');content.className='article-video';
  const video=document.createElement('video');video.src=mediaSource(src);video.poster=mediaSource(poster);
  video.controls=true;video.playsInline=true;video.preload='metadata';video.setAttribute('aria-label',title);
  if(captionSrc){const track=document.createElement('track');track.kind='captions';track.label=labels.captions;track.srclang=labels.language;track.src=mediaSource(captionSrc);video.append(track);}
  const error=document.createElement('p');error.className='media-error';error.hidden=true;error.setAttribute('role','alert');error.textContent=labels.error;
  const failed=()=>{error.hidden=false;};video.addEventListener('error',failed);
  content.append(video,error);
  const hidden=()=>{if(document.hidden)video.pause();};document.addEventListener('visibilitychange',hidden);
  return {content,pause:()=>video.pause(),destroy(){video.pause();video.removeEventListener('error',failed);document.removeEventListener('visibilitychange',hidden);video.removeAttribute('src');video.load();content.remove();}};
}

export function createKineticFigure({kind,title,labels,duration=10000}){
  if(!['curve','orbit'].includes(kind)||!Number.isFinite(duration)||duration<1000)throw new TypeError('Invalid motion config');
  const content=document.createElement('div');content.className=`kinetic-content ${kind}`;
  const drawing=kind==='curve'?`<path class="kinetic-grid" d="M70 90H540 M70 170H540 M70 250H540 M190 60V270 M310 60V270 M430 60V270"/><path class="kinetic-axis" d="M70 60V270H540"/><path class="curve-ghost" d="M70 250C240 248 350 65 530 60"/><path data-trace pathLength="100" d="M70 250C240 248 350 65 530 60"/><circle data-dot r="7"/><text x="70" y="300">${esc(labels.start)}</text><text x="480" y="300">${esc(labels.end)}</text>`:`<path class="kinetic-grid" d="M80 160H520 M300 35V285"/><ellipse class="orbit-track" cx="300" cy="160" rx="210" ry="100"/><ellipse class="orbit-inner" cx="300" cy="160" rx="140" ry="65"/><circle class="orbit-core" cx="300" cy="160" r="27"/><path class="orbit-star" d="M300 143V177 M283 160H317 M288 148L312 172 M288 172L312 148"/><circle data-dot r="10"/><text x="50" y="300">${esc(labels.geometric)}</text>`;
  content.innerHTML=`<svg viewBox="0 0 600 320" role="img" aria-label="${esc(title)}">${drawing}</svg><div class="kinetic-controls"><button type="button" data-play>${esc(labels.play)}</button><button type="button" data-replay>${esc(labels.replay)}</button><label>${esc(labels.progress)}<input type="range" min="0" max="1000" value="0"></label><output>0%</output></div>`;
  const play=content.querySelector('[data-play]'),range=content.querySelector('input'),dot=content.querySelector('[data-dot]'),trace=content.querySelector('[data-trace]');
  let progress=0,running=false,frame=null,last=null,dead=false;
  const paint=()=>{content.dataset.running=String(running);play.textContent=running?labels.pause:labels.play;play.setAttribute('aria-pressed',String(running));range.value=Math.round(progress*1000);content.querySelector('output').textContent=`${Math.round(progress*100)}%`;const p=kind==='curve'?curvePoint(progress):{x:300+210*Math.cos(progress*Math.PI*2),y:160+100*Math.sin(progress*Math.PI*2)};dot.setAttribute('cx',p.x);dot.setAttribute('cy',p.y);if(trace)trace.style.strokeDashoffset=100-progress*100;};
  const pause=()=>{running=false;last=null;cancelAnimationFrame(frame);frame=null;paint();};
  const tick=now=>{if(!running||dead)return;if(last!==null)progress=Math.min(1,progress+(now-last)/duration);last=now;paint();if(progress===1){pause();return;}frame=requestAnimationFrame(tick);};
  const start=()=>{if(progress===1)progress=0;running=true;last=null;paint();frame=requestAnimationFrame(tick);};
  play.onclick=()=>running?pause():start();content.querySelector('[data-replay]').onclick=()=>{pause();progress=0;start();};range.oninput=()=>{const next=Number(range.value)/1000;pause();progress=next;paint();};
  const preference=matchMedia('(prefers-reduced-motion: reduce)'),reduced=()=>{if(preference.matches)pause();},hidden=()=>{if(document.hidden)pause();};
  document.addEventListener('visibilitychange',hidden);preference.addEventListener('change',reduced);paint();
  return {content,pause,getState:()=>({progress,running}),destroy(){pause();dead=true;document.removeEventListener('visibilitychange',hidden);preference.removeEventListener('change',reduced);content.remove();}};
}

export function mountMediaWindow(host,{title,caption,number,media,labels}){
  if(!host||!media?.content)throw new TypeError('Host and content required');
  const root=document.createElement('figure');root.className='reading-media-window';
  const id=`media-title-${++serial}`;
  root.innerHTML=`<div class="reading-media-head"><span>${esc(number)}</span><h4>${esc(title)}</h4><button type="button" aria-haspopup="dialog">${esc(labels.expand)} ↗</button></div><div class="reading-media-slot"></div><figcaption>${esc(caption)}</figcaption>`;
  host.replaceChildren(root);const slot=root.querySelector('.reading-media-slot'),expand=root.querySelector('button');slot.append(media.content);
  const dialog=document.createElement('dialog');dialog.className='reading-media-dialog';dialog.setAttribute('aria-labelledby',id);
  dialog.innerHTML=`<header><div><span class="eyebrow">${esc(number)}</span><h2 id="${id}">${esc(title)}</h2></div><button type="button">${esc(labels.close)} ×</button></header><div class="reading-media-large"></div><footer>${esc(caption)}</footer>`;
  document.body.append(dialog);const large=dialog.querySelector('.reading-media-large');let timer=null,closing=false;
  const restore=(focus=true)=>{clearTimeout(timer);timer=null;if(dialog.open)dialog.close();slot.append(media.content);closing=false;if(focus&&expand.isConnected)expand.focus({preventScroll:true});};
  const close=()=>{if(closing||!dialog.open)return;closing=true;media.pause();dialog.dataset.phase='closing';timer=setTimeout(()=>restore(),180);};
  expand.onclick=()=>{clearTimeout(timer);timer=null;closing=false;large.append(media.content);dialog.dataset.phase='open';dialog.showModal();dialog.querySelector('button').focus();};
  const cancel=e=>{e.preventDefault();close();};dialog.addEventListener('cancel',cancel);dialog.querySelector('button').onclick=close;
  const backdrop=e=>{const r=dialog.getBoundingClientRect();if(e.target===dialog&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom))close();};dialog.addEventListener('click',backdrop);
  return {destroy(){media.pause();restore(false);media.destroy();dialog.remove();root.remove();},pause:media.pause};
}
