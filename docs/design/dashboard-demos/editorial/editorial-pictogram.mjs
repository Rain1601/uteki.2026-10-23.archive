// Original SVG illustration, not Anthropic's artwork or Lottie asset.
export function createEditorialPictogram({label='Archive illustration',motion=true}={}){
 if(typeof label!=='string'||!label.trim()||typeof motion!=='boolean')throw new TypeError('A label and boolean motion are required');
 const root=document.createElement('figure');root.className='editorial-pictogram';
 root.innerHTML=`<svg viewBox="0 0 160 140" role="img"><g fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M26 81 Q23 75 28 70 L130 70 Q138 72 136 80 L132 120 Q81 123 29 118 Z" fill="var(--surface,var(--bg,#f5f3ed))"/><g class="pictogram-pages"><path d="M48 90 L43 44 L76 40 L81 89" fill="var(--bg,#f5f3ed)"/><path d="M57 53 L69 52 M58 61 L70 60 M59 69 L71 68"/><path d="M88 90 L93 38 L122 45 L116 92" fill="var(--bg,#f5f3ed)"/><path d="M100 52 L113 55 M99 62 L112 65"/></g><path class="pictogram-lid" d="M26 80 Q24 44 54 41 L108 40 Q137 43 136 80 Z" fill="var(--bg,#f5f3ed)"/><path class="pictogram-handle" d="M60 40 L61 31 Q61 21 72 21 L92 21 Q103 21 104 32 L104 40 M69 40 L69 32 Q69 29 75 29 L90 29 Q96 29 96 40"/><path d="M47 76 L47 91 L55 91 L55 76 M109 76 L109 91 L117 91 L117 76" fill="var(--accent-soft,#e4e1d5)"/></g></svg><button type="button"></button>`;
 const svg=root.querySelector('svg');svg.setAttribute('aria-label',label);const button=root.querySelector('button');let playing=motion;
 const paint=()=>{root.dataset.playing=String(playing);button.textContent=playing?'Ⅱ':'▷';button.setAttribute('aria-label',`${playing?'Pause / 暂停':'Play / 播放'} · ${label}`);button.setAttribute('aria-pressed',String(playing));};
 button.onclick=()=>{playing=!playing;paint()};paint();return {content:root,destroy(){button.onclick=null;root.remove()}};
}
