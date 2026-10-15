import {esc} from './components.mjs';

export function StoryLead({eyebrow,title,summary,facts=[]}) {
  return `<header class="story-lead"><div class="eyebrow">${esc(eyebrow)}</div><h2>${esc(title)}</h2><p>${esc(summary)}</p><dl class="story-facts">${facts.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(f.value ?? '—')}</dd></div>`).join('')}</dl></header>`;
}
export function PullQuote({text,attribution}) {
  return `<figure class="story-quote"><blockquote>${esc(text)}</blockquote><figcaption>${esc(attribution)}</figcaption></figure>`;
}

export function validateExplainer({steps,duration=12000}) {
  if (!Array.isArray(steps)||steps.length<2||steps.length>6) throw new TypeError('Supply 2–6 steps');
  const ids=new Set();
  for (const s of steps) {
    if (typeof s.id!=='string'||!s.id||ids.has(s.id)||typeof s.title!=='string'||typeof s.body!=='string') throw new TypeError('Steps need unique IDs, title and body');
    ids.add(s.id);
  }
  if (!Number.isFinite(duration)||duration<1000) throw new TypeError('Duration must be >= 1000 ms');
  return {steps:steps.map(s=>({...s})),duration};
}
export function stepAt(progress,count) {
  if (!Number.isFinite(progress)||!Number.isInteger(count)||count<2||count>6) throw new TypeError('Invalid timeline');
  return Math.min(count-1,Math.floor(Math.max(0,Math.min(1,progress))*count));
}

// One bounded timeline drives the diagram, caption and transport together.
export function mountExplainer(host,config) {
  const {steps,duration}=validateExplainer(config);
  const {title,caption,labels}=config;
  if (!host||!labels) throw new TypeError('Host and localized labels are required');
  const root=document.createElement('figure');root.className='story-explainer';
  const width=steps.length*150;
  root.innerHTML=`<div class="explainer-head"><span class="eyebrow">${esc(labels.kicker)}</span><h4>${esc(title)}</h4></div><div class="explainer-stage"><svg viewBox="0 0 ${width} 210" aria-hidden="true">${steps.slice(1).map((s,i)=>`<path class="explainer-link" data-edge="${i+1}" d="M ${i*150+112} 102 C ${i*150+144} 102, ${i*150+128} 102, ${i*150+164} 102"/>`).join('')}${steps.map((s,i)=>`<g data-node="${i}" transform="translate(${i*150+14},55)"><rect width="98" height="94" rx="9"/><text x="16" y="28" class="node-index">0${i+1}</text><text x="16" y="58">${esc(s.title)}</text><circle cx="79" cy="24" r="4"/></g>`).join('')}</svg><div class="explainer-step-list" role="group" aria-label="${esc(labels.steps)}">${steps.map((s,i)=>`<button type="button" data-seek-step="${i}" aria-pressed="false">0${i+1} / ${esc(s.title)}</button>`).join('')}</div></div><div class="explainer-caption"><b data-step-title></b><p data-step-body></p></div><div class="explainer-transport"><button type="button" data-play></button><button type="button" data-replay>${esc(labels.replay)}</button><label>${esc(labels.progress)}<input type="range" min="0" max="1000" step="1" value="0"></label><output></output></div><figcaption>${esc(caption)}</figcaption>`;
  host.replaceChildren(root);
  const play=root.querySelector('[data-play]'),replay=root.querySelector('[data-replay]'),range=root.querySelector('input'),output=root.querySelector('output');
  const titleEl=root.querySelector('[data-step-title]'),bodyEl=root.querySelector('[data-step-body]');
  const media=matchMedia('(prefers-reduced-motion: reduce)');
  let progress=0,running=false,frame=null,last=null,lastStep=-1,destroyed=false;
  const update=()=>{
    const index=stepAt(progress,steps.length);
    root.dataset.running=String(running);root.dataset.step=String(index);
    root.dataset.reduced=String(media.matches);
    play.textContent=running?labels.pause:labels.play;play.setAttribute('aria-pressed',String(running));
    range.value=String(Math.round(progress*1000));range.setAttribute('aria-valuetext',`${Math.round(progress*100)}% · ${steps[index].title}`);
    output.textContent=`${Math.round(progress*100)}%`;
    if(index!==lastStep){
      root.querySelectorAll('[data-node]').forEach((n,i)=>n.dataset.active=String(i===index));
      root.querySelectorAll('[data-edge]').forEach(n=>n.dataset.active=String(Number(n.dataset.edge)<=index));
      root.querySelectorAll('[data-seek-step]').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));
      titleEl.textContent=steps[index].title;bodyEl.textContent=steps[index].body;lastStep=index;
    }
  };
  const pause=()=>{running=false;last=null;if(frame!==null)cancelAnimationFrame(frame);frame=null;update();};
  const tick=now=>{
    if(!running||destroyed)return;
    if(last!==null)progress=Math.min(1,progress+(now-last)/duration);
    last=now;update();
    if(progress>=1){pause();return;}frame=requestAnimationFrame(tick);
  };
  const start=()=>{if(progress>=1)progress=0;running=true;last=null;update();frame=requestAnimationFrame(tick);};
  const toggle=()=>running?pause():start();
  const restart=()=>{pause();progress=0;start();};
  const seek=e=>{const next=Number(e.target.value)/1000;pause();progress=next;update();};
  const choose=e=>{const b=e.target.closest('[data-seek-step]');if(!b)return;pause();progress=Number(b.dataset.seekStep)/steps.length;update();};
  const hidden=()=>{if(document.hidden)pause();};
  const preference=()=>{if(media.matches)pause();update();};
  play.addEventListener('click',toggle);replay.addEventListener('click',restart);range.addEventListener('input',seek);root.querySelector('.explainer-step-list').addEventListener('click',choose);
  document.addEventListener('visibilitychange',hidden);media.addEventListener('change',preference);
  update();
  return {pause,getState:()=>({progress,running,step:stepAt(progress,steps.length)}),destroy(){pause();destroyed=true;document.removeEventListener('visibilitychange',hidden);media.removeEventListener('change',preference);root.remove();}};
}
