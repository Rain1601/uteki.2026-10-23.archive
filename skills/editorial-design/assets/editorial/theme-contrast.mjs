/** Opaque sRGB semantic roles only; this is not a rendered-page accessibility audit. */
function luminance(hex){
 if(typeof hex!=='string'||!/^#[0-9a-f]{6}$/i.test(hex))throw new TypeError('Opaque six-digit sRGB color required');
 const [r,g,b]=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
 return .2126*r+.7152*g+.0722*b;
}
export function contrastRatio(a,b){const la=luminance(a),lb=luminance(b);return (Math.max(la,lb)+.05)/(Math.min(la,lb)+.05);}
export function checkThemeTextRoles(theme,{minimum=4.5}={}){
 if(!Number.isFinite(minimum)||minimum<1||minimum>21)throw new TypeError('Valid contrast threshold required');
 return ['ink','muted','accent'].flatMap(foreground=>['canvas','surface','accentSoft'].map(background=>({foreground,background,ratio:contrastRatio(theme[foreground],theme[background]),pass:contrastRatio(theme[foreground],theme[background])>=minimum})));
}
