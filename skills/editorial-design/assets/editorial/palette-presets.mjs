import {themes,themeCSS} from './tokens.mjs?v=1';
import {checkThemeTextRoles} from './theme-contrast.mjs';
// Color is a separate input. It never selects layout or changes data identity.
export const palettePresets=Object.freeze({...themes,
 forest:Object.freeze({canvas:'#f3f5ef',surface:'#e5ebdf',ink:'#202d24',muted:'#52604f',line:'#c6d0c1',accent:'#355c48',accentSoft:'#d6e3d2',positive:'#356249',negative:'#a33e36',series1:'#355c48',series2:'#526f89',series3:'#897442'}),
 clay:Object.freeze({canvas:'#faf4ee',surface:'#efe3d8',ink:'#30251f',muted:'#67594f',line:'#d6c6b9',accent:'#8b4433',accentSoft:'#eed7cc',positive:'#356249',negative:'#a33e36',series1:'#8b4433',series2:'#506e86',series3:'#777348'}),
 'paper-night':Object.freeze({canvas:'#302e2a',surface:'#38352f',ink:'#eeeae2',muted:'#bbb5aa',line:'#625b50',accent:'#dab99d',accentSoft:'#40382f',positive:'#9fc5ab',negative:'#eab0a4',series1:'#dab99d',series2:'#a7bac7',series3:'#c0b985'}),
 night:Object.freeze({canvas:'#17201f',surface:'#202c29',ink:'#ecefe8',muted:'#a9b5ac',line:'#53655b',accent:'#d6bb8f',accentSoft:'#303d36',positive:'#9bc8ac',negative:'#efaca5',series1:'#d6bb8f',series2:'#99bacb',series3:'#b3c5a3'})
});
export function resolvePalette(input){const palette=typeof input==='string'?palettePresets[input]:input;themeCSS(palette);return {...palette};}
export function validatePalette(input){const palette=resolvePalette(input);const failed=checkThemeTextRoles(palette).filter(x=>!x.pass);if(failed.length)throw new TypeError('Small-text contrast below 4.5: '+failed.map(x=>`${x.foreground}/${x.background}`).join(', '));return palette;}

/** Write semantic roles only; preserve existing inline dimensions and business state. */
export function applyPalette(host,input){
 if(!host?.style||typeof host.style.setProperty!=='function')throw new TypeError('A styled theme host is required');
 const palette=validatePalette(input);
 for(const [key,value] of Object.entries(palette))host.style.setProperty('--'+key.replace(/[A-Z]/g,c=>'-'+c.toLowerCase()),value);
 return palette;
}
