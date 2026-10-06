// Display preferences only. Colors never encode returns, risk or portfolio weights.
export const DEFAULT_ALLOCATION_PALETTE = 'bright';
export const ALLOCATION_PALETTES = Object.freeze([
  {id:'classic',name:'经典',nameEn:'Classic',description:'正色 · 清晰自然',descriptionEn:'Familiar & distinct',
    light:['#4285F4','#34A853','#FBBC04','#EA4335','#9C59D1','#26AFC2'],
    dark:['#5C9DFF','#4FC478','#FFD15C','#FF7368','#B58BFF','#42CDDA']},
  {id:'bright',name:'明快',nameEn:'Bright',description:'鲜亮 · 轻快通透',descriptionEn:'Bright & fresh',
    light:['#3478F6','#2DBB88','#FFB340','#FA6B6B','#A17BF7','#39BDD0'],
    dark:['#5798FF','#40D19D','#FFC35A','#FF8282','#B799FF','#50D5E3']},
  {id:'jewel',name:'宝石',nameEn:'Jewel',description:'浓郁 · 色彩分明',descriptionEn:'Rich & defined',
    light:['#2563C9','#138D75','#D99918','#C23B55','#7847B7','#008EA8'],
    dark:['#508DE8','#24B396','#F0B52D','#EA627C','#A074DE','#21B7CF']},
  {id:'vivid',name:'活力',nameEn:'Vivid',description:'明艳 · 跳跃有序',descriptionEn:'Vibrant & energetic',
    light:['#5C63F2','#16B891','#FF8A32','#F04F82','#B35DDB','#17A9CF'],
    dark:['#838AFF','#32D4AC','#FFA24F','#FF75A0','#CC83EC','#39C6EB']},
].map(palette=>Object.freeze({...palette,light:Object.freeze(palette.light),dark:Object.freeze(palette.dark)})));

export function getAllocationPalette(id) {
  const palette=ALLOCATION_PALETTES.find(item=>item.id===id);
  if(!palette) throw new Error('Unknown allocation palette');
  return palette;
}

export function allocationPaletteStyle(id) {
  const palette=getAllocationPalette(id);
  return ['light','dark'].flatMap(theme=>palette[theme].map((color,index)=>`--holding-${index}-${theme}:${color}`)).join(';');
}
