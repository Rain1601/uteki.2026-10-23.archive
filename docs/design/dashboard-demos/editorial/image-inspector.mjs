import {mediaSource} from './reading-media.mjs';
import {esc} from './components.mjs';
export function lensGeometry({width,height,x,y,zoom,diameter=180}){
  if(![width,height,x,y,zoom,diameter].every(Number.isFinite)||width<=0||height<=0||zoom<1||diameter<=0)throw new TypeError('Invalid lens geometry');
  const size=Math.min(diameter,width*.6,height*.8),r=size/2;
  const cx=Math.max(r,Math.min(width-r,x*width)),cy=Math.max(r,Math.min(height-r,y*height));
  return {size,left:cx-r,top:cy-r,backgroundWidth:width*zoom,backgroundHeight:height*zoom,backgroundX:r-cx*zoom,backgroundY:r-cy*zoom,x:cx/width,y:cy/height};
}
export function mountImageInspector(host,{src,alt,title,caption,labels,zoom=2.5,diameter=180}){
  mediaSource(src);
  if(!host||!labels||!Number.isFinite(zoom)||zoom<1.5||zoom>4||!Number.isFinite(diameter)||diameter<60||diameter>300)throw new TypeError('Invalid image inspector config');
  const root=document.createElement('figure');root.className='image-inspector';
  root.innerHTML=`<header><span class="eyebrow">PLATE / 04</span><h4>${esc(title)}</h4></header><div class="image-inspector-stage" tabindex="0" role="region" aria-label="${esc(labels.region)}"><img alt="${esc(alt)}"><span class="image-inspector-lens" aria-hidden="true"></span></div><div class="image-inspector-tools"><label>${esc(labels.zoom)}<input type="range" min="1.5" max="4" step="0.5" value="${zoom}"></label><output>${zoom}×</output><button type="button">${esc(labels.reset)}</button></div><p class="image-inspector-hint">${esc(labels.hint)}</p><p class="image-inspector-error" role="alert" hidden>${esc(labels.error)}</p><figcaption>${esc(caption)}</figcaption>`;
  host.replaceChildren(root);
  const stage=root.querySelector('.image-inspector-stage'),img=root.querySelector('img'),lens=root.querySelector('.image-inspector-lens'),range=root.querySelector('input'),output=root.querySelector('output');
  img.src=src;lens.style.backgroundImage=`url("${new URL(src,document.baseURI).href.replaceAll('"','%22')}")`;
  let x=.5,y=.5,active=false,pinned=false,loaded=false;
  const paint=()=>{
    root.dataset.active=String(active&&loaded);root.dataset.pinned=String(pinned);
    if(!loaded)return;
    const box=img.getBoundingClientRect();if(!box.width||!box.height)return;
    const g=lensGeometry({width:box.width,height:box.height,x,y,zoom,diameter});
    Object.assign(lens.style,{width:`${g.size}px`,height:`${g.size}px`,left:`${g.left}px`,top:`${g.top}px`,backgroundSize:`${g.backgroundWidth}px ${g.backgroundHeight}px`,backgroundPosition:`${g.backgroundX}px ${g.backgroundY}px`});
    output.textContent=`${zoom}×${pinned?` · ${labels.pinned}`:''}`;
  };
  const move=e=>{if(pinned&&e.pointerType==='mouse')return;const b=img.getBoundingClientRect();x=(e.clientX-b.left)/b.width;y=(e.clientY-b.top)/b.height;active=true;paint();};
  stage.addEventListener('pointermove',move);
  stage.onpointerleave=()=>{if(!pinned){active=false;paint();}};
  stage.onpointerdown=e=>{if(e.pointerType!=='mouse'){pinned=false;move(e);stage.setPointerCapture(e.pointerId);}};
  stage.onpointerup=e=>{if(e.pointerType!=='mouse'){pinned=true;paint();}};
  stage.onclick=e=>{if(e.pointerType==='touch')return;pinned=!pinned;active=true;paint();};
  stage.onfocus=()=>{active=true;paint();};stage.onblur=()=>{if(!pinned){active=false;paint();}};
  stage.onkeydown=e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Home','Escape','Enter',' '].includes(e.key)){e.preventDefault();if(e.key==='Escape'){pinned=false;active=false;}else{active=true;if(e.key==='Home'){x=y=.5;}if(e.key==='Enter'||e.key===' ')pinned=!pinned;if(e.key==='ArrowLeft')x-=.05;if(e.key==='ArrowRight')x+=.05;if(e.key==='ArrowUp')y-=.05;if(e.key==='ArrowDown')y+=.05;x=Math.max(0,Math.min(1,x));y=Math.max(0,Math.min(1,y));}paint();}};
  range.oninput=()=>{zoom=Number(range.value);active=true;paint();};root.querySelector('button').onclick=()=>{x=y=.5;pinned=false;active=true;paint();stage.focus({preventScroll:true});};
  img.onload=()=>{loaded=true;paint();};img.onerror=()=>{loaded=false;paint();root.querySelector('.image-inspector-error').hidden=false;range.disabled=true;root.querySelector('button').disabled=true;};
  if(img.complete&&img.naturalWidth){loaded=true;paint();}
  const observer=new ResizeObserver(paint);observer.observe(img);
  return {getState:()=>({x,y,zoom,active,pinned,loaded}),destroy(){observer.disconnect();root.remove();}};
}
