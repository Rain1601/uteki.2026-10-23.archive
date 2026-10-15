import {mountResourceTree} from './resource-tree.mjs';
import {mountSplitPane} from './split-pane.mjs';
import {mountImageInspector} from './image-inspector.mjs';
import {createArticleVideo} from './reading-media.mjs';
import {esc} from './components.mjs';
import {createEditorialPictogram} from './editorial-pictogram.mjs';
export const archiveAssets=[
 {id:'pdf-zh',kind:'PDF',labelZh:'中文研究样稿',labelEn:'Chinese research specimen',href:'output/pdf/editorial-zh-v0.3.pdf',pages:['comparison/pdf-v03/zh-1.png','comparison/pdf-v03/zh-2.png']},
 {id:'pdf-en',kind:'PDF',labelZh:'English research specimen',labelEn:'English research specimen',href:'output/pdf/editorial-en-v0.3.pdf',pages:['comparison/pdf-v03/en-1.png','comparison/pdf-v03/en-2.png']},
 {id:'film',kind:'MP4',labelZh:'轮廓线短片',labelEn:'A line in motion',href:'media/line-study.mp4'},
 {id:'poster',kind:'PNG',labelZh:'短片海报',labelEn:'Film poster',href:'media/line-study-poster.png'}
];
export function mountResourceArchive(host,{tr,selected='pdf-zh',width=260,onChange=()=>{}}){
 let selectedId=selected,child=null,page=0,scale=1;
 const titleFor=a=>tr(a.labelZh,a.labelEn);
 const nodes=[{id:'editions',label:tr('研究出版物','Research editions'),children:archiveAssets.filter(a=>a.kind==='PDF').map(a=>({...a,label:titleFor(a)}))},{id:'motion',label:tr('动态图像','Motion & imagery'),children:archiveAssets.filter(a=>a.kind!=='PDF').map(a=>({...a,label:titleFor(a)}))}];
 host.innerHTML=`<div class="resource-archive"><aside class="archive-rail"><div class="eyebrow">ARCHIVE / 04</div><h2>${tr('每份素材，<br>都有位置。','A place for<br>every resource.')}</h2><p>${tr('已生成的文件与原创素材。不是用户上传目录。','Generated files and original imagery, not uploaded user documents.')}</p><div class="archive-tree-host"></div></aside><div class="archive-divider" data-split-handle></div><section class="archive-preview" aria-label="${tr('资源预览','Resource preview')}"></section></div>`;
 const root=host.firstElementChild,preview=root.querySelector('.archive-preview');
 const pictogram=createEditorialPictogram({label:tr('素材箱 · 原创线稿','Resource case · Original line illustration')});root.querySelector('.archive-rail').prepend(pictogram.content);
 const paint=()=>{child?.destroy();child=null;const a=archiveAssets.find(x=>x.id===selectedId);if(!a)throw new TypeError('Unknown archive selection');preview.innerHTML=`<header class="archive-preview-head"><div><div class="eyebrow">${a.kind} / ${tr('本地素材','LOCAL ASSET')}</div><h2>${esc(titleFor(a))}</h2></div><a href="${esc(a.href)}" target="_blank" rel="noopener">${tr('打开文件','Open file')} ↗</a></header><div class="archive-preview-body"></div>`;const body=preview.querySelector('.archive-preview-body');
 if(a.kind==='PDF'){body.innerHTML=`<div class="archive-pdf-tools"><button data-page-back aria-label="${tr('上一页','Previous page')}" ${page===0?'disabled':''}>←</button><span>${page+1} / ${a.pages.length}</span><button data-page-next aria-label="${tr('下一页','Next page')}" ${page===a.pages.length-1?'disabled':''}>→</button><label>${tr('缩放','Zoom')} <select aria-label="${tr('PDF缩放','PDF zoom')}"><option value="1">${tr('适合宽度','Fit width')}</option><option value="1.25">125%</option><option value="1.5">150%</option></select></label></div><div class="archive-pdf-scroll"><img style="width:${scale*100}%" src="${a.pages[page]}" alt="${esc(titleFor(a))} · ${tr('第','Page ')}${page+1}${tr('页','')}"></div><p class="archive-caption">${tr('预览来自已验收PDF的逐页渲染。原件入口保留文字层；本预览不提供批注或文本搜索。','Preview uses renders of the reviewed PDF. The original retains text; this image viewer offers no annotations or text search.')}</p>`;
 body.querySelector('[data-page-back]').onclick=()=>{page--;paint()};body.querySelector('[data-page-next]').onclick=()=>{page++;paint()};const zoom=body.querySelector('select');zoom.value=String(scale);zoom.onchange=e=>{scale=Number(e.target.value);body.querySelector('img').style.width=`${scale*100}%`};
 }else if(a.kind==='MP4'){child=createArticleVideo({src:a.href,poster:'media/line-study-poster.png',title:titleFor(a),captionSrc:`media/line-study-${tr('zh','en')}.vtt`,labels:{captions:tr('中文字幕','English captions'),error:tr('视频未能加载。','Video unavailable.')}});body.append(child.content);body.insertAdjacentHTML('beforeend',`<p class="archive-caption">${tr('原创7秒无声短片 · 与阅读页共用播放器接口。','Original seven-second silent film · Reuses the reader video API.')}</p>`);
 }else{child=mountImageInspector(body,{src:a.href,alt:titleFor(a),title:titleFor(a),caption:tr('原创图像；可检查局部。','Original imagery; inspect the details.'),labels:{region:tr('档案图片局部放大','Archive image magnifier'),zoom:tr('放大倍数','Magnification'),reset:tr('复位','Reset'),pinned:tr('已锁定','Pinned'),hint:tr('移入或方向键检查，回车锁定，Esc隐藏。','Move over or use arrows; Enter pins; Esc hides.'),error:tr('图片未能加载。','Image unavailable.')}});}
 onChange({selected:selectedId,width});};
 const tree=mountResourceTree(root.querySelector('.archive-tree-host'),{nodes,selected:selectedId,labels:{region:tr('素材目录','Resource directory'),empty:tr('目录为空','Empty directory')},onSelect:id=>{selectedId=id;page=0;scale=1;paint()}});
 const split=mountSplitPane(root,{value:width,label:tr('调整目录宽度','Resize directory'),onChange:v=>{width=v;onChange({selected:selectedId,width})}});paint();
 return {destroy(){child?.destroy();pictogram.destroy();tree.destroy();split.destroy();root.remove()}};
}
