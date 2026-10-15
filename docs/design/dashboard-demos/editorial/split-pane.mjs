export const clampPane=(value,total,min=210,max=420)=>{if(![value,total,min,max].every(Number.isFinite)||total<=0||min<=0||max<min)throw new TypeError('Invalid pane bounds');return Math.max(Math.min(min,total/2),Math.min(value,max,total-260));};
export function mountSplitPane(root,{value=260,label,onChange=()=>{}}){
 const handle=root.querySelector('[data-split-handle]');if(!handle||!label)throw new TypeError('Split pane needs a handle and label');
 let width=value,dragging=false;
 handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');handle.setAttribute('aria-label',label);handle.tabIndex=0;
 function paint(v){width=clampPane(v,root.getBoundingClientRect().width);root.style.setProperty('--archive-rail',`${width}px`);handle.setAttribute('aria-valuenow',String(Math.round(width)));handle.setAttribute('aria-valuemin',String(Math.round(Math.min(210,root.getBoundingClientRect().width/2))));handle.setAttribute('aria-valuemax',String(Math.round(Math.min(420,Math.max(210,root.getBoundingClientRect().width-260)))));onChange(width);}
 handle.onpointerdown=e=>{dragging=true;handle.setPointerCapture(e.pointerId)};handle.onpointermove=e=>{if(dragging)paint(e.clientX-root.getBoundingClientRect().left)};handle.onpointerup=handle.onpointercancel=()=>{dragging=false};handle.ondblclick=()=>paint(260);
 handle.onkeydown=e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();paint(e.key==='Home'?210:e.key==='End'?420:width+(e.key==='ArrowRight'?20:-20))}};
 const observer=new ResizeObserver(()=>paint(width));observer.observe(root);paint(width);
 return {destroy(){observer.disconnect();handle.onpointerdown=handle.onpointermove=handle.onpointerup=handle.onpointercancel=handle.onkeydown=handle.ondblclick=null;}};
}
