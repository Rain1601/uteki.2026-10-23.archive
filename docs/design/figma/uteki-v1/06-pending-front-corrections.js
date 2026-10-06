const state={"createdNodeIds":["3:2","3:3","3:32","3:33","3:34","3:35","3:36","3:37","3:38","3:39","3:40","3:41","3:42","3:43","3:44","3:45","3:46","3:47","3:48","3:49","3:50","3:51","3:52","3:53","3:54","3:55","3:56","3:57","3:58","3:59","3:60","3:61"],"mutatedNodeIds":["0:1"],"fileKey":"0SogEfR3y4xLDl9YB5RbOQ","pages":{"overview":"0:1","front":"3:2","back":"3:3"},"cover":"3:43","masters":"3:32","frames":{"U1":"3:44","U2":"3:45","U3":"3:46","U4":"3:47","U5":"3:48","U6":"3:49","U7":"3:50","U8":"3:51","U9":"3:52","E0":"3:53","E1":"3:54","E2":"3:55","E3":"3:56","E4":"3:57","E5":"3:58","E6":"3:59","E7":"3:60","E8":"3:61","U10":"4:2","U11":"11:359","U12":"11:360"},"components":{"ObjectRow":{"id":"3:34","titleKey":"Title#3:0","detailKey":"Description#3:1"},"EvidenceCard":{"id":"3:37","titleKey":"Title#3:2","detailKey":"Description#3:3"},"StatusPanel":{"id":"3:40","titleKey":"Title#3:4","detailKey":"Description#3:5"}},"variables":{"surface":"VariableID:3:5","canvas":"VariableID:3:6","ink":"VariableID:3:7","body":"VariableID:3:8","muted":"VariableID:3:9","line":"VariableID:3:10","accent":"VariableID:3:11","wash":"VariableID:3:12","warning":"VariableID:3:13","warningInk":"VariableID:3:14","positive":"VariableID:3:15","positiveInk":"VariableID:3:16","danger":"VariableID:3:17","dangerInk":"VariableID:3:18","radius":"VariableID:3:19","s8":"VariableID:15bb1c0f339146e931cf0dc15f89ed57dcbd907e/564:255","s16":"VariableID:16bc6f84b6e7e20e4234ef79030ee580ec0f4505/564:258","s24":"VariableID:be3115966ea99eef888c9f25751b54695c7e88d2/564:260","s32":"VariableID:9acadea8b7c7c9884455b896e21c88b8bc62d6da/564:261","s48":"VariableID:d1a1caa0985a992cee4da9c73948f850813e97d2/564:252"},"styles":{"caption":"S:484e456b0e79889fb3c2580ffa19af233793329a,","body":"S:1bfdba73493ce0a3ffb8128db1e7df5bc518fb69,","bodyStrong":"S:b924045aadcd52da2db634588f997459357406f2,","section":"S:add3b55fc06800a0b684d254e3a07a0dc650b4c7,","title":"S:076112472bb50649fc588d3158973511cc5ff82e,","display":"S:17ba817d75d857cd901adc8bdc1110655e7f1196,"},"counts":{"screens":18,"components":3,"textStyles":6},"font":"Noto Sans SC"};
const created=[],mutated=[],links=[],scrolls=[];
const page=await figma.getNodeByIdAsync("3:2");await figma.setCurrentPageAsync(page);
await Promise.all([{family:"Noto Sans SC",style:"Regular"},{family:"Noto Sans SC",style:"Medium"},{family:"Noto Sans SC",style:"Bold"},{family:"Inter",style:"Regular"},{family:"Inter",style:"Medium"},{family:"Inter",style:"Semi Bold"}].map(f=>figma.loadFontAsync(f)));
const varEntries=await Promise.all(Object.entries(state.variables).map(async([k,id])=>[k,await figma.variables.getVariableByIdAsync(id)]));const V=Object.fromEntries(varEntries);
const [buttons,tags,tabs,objectMaster,evidenceMaster,statusMaster]=await Promise.all([figma.importComponentSetByKeyAsync("cc8b558dc7d9684011b6b99ce8e6509399bc836b"),figma.importComponentSetByKeyAsync("0fcd16616b41884b21451ffa4a2fc98a03093b49"),figma.importComponentSetByKeyAsync("18aa207708b43593a2af7096b2dfd531553f3414"),figma.getNodeByIdAsync(state.components.ObjectRow.id),figma.getNodeByIdAsync(state.components.EvidenceCard.id),figma.getNodeByIdAsync(state.components.StatusPanel.id)]);
const variant=(set,name)=>{const n=set.children.find(c=>c.name===name);if(!n)throw new Error("Missing variant "+name);return n;};
const buttonNeutral=variant(buttons,"Variant=Neutral, State=Default, Size=Medium"),buttonPrimary=variant(buttons,"Variant=Primary, State=Default, Size=Medium"),buttonSubtle=variant(buttons,"Variant=Subtle, State=Default, Size=Small"),tagNeutral=variant(tags,"Scheme=Neutral, State=Default, Variant=Secondary"),tagPositive=variant(tags,"Scheme=Positive, State=Default, Variant=Secondary"),tagWarning=variant(tags,"Scheme=Warning, State=Default, Variant=Secondary"),tagDanger=variant(tags,"Scheme=Danger, State=Default, Variant=Secondary"),tabOff=variant(tabs,"State=Default, Active=Off"),tabOn=variant(tabs,"State=Default, Active=On");
const C=state.components,F=state.frames,S=state.styles;
function paint(name){return figma.variables.setBoundVariableForPaint({type:"SOLID",color:{r:1,g:1,b:1}},"color",V[name]);}
function rec(n){created.push(n.id);return n;}
function gap(n,size){n.itemSpacing=size;if(V["s"+size])n.setBoundVariable("itemSpacing",V["s"+size]);}
function pad(n,size){for(const k of ["paddingTop","paddingBottom","paddingLeft","paddingRight"]){n[k]=size;if(V["s"+size])n.setBoundVariable(k,V["s"+size]);}}
function A(parent,name,w,dir="VERTICAL",g=16,p=0,bg=null){const a=rec(figma.createAutoLayout(dir));parent.appendChild(a);a.name=name;a.resize(w,20);a.layoutSizingHorizontal="FIXED";a.layoutSizingVertical="HUG";a.primaryAxisSizingMode="AUTO";a.counterAxisSizingMode="FIXED";gap(a,g);pad(a,p);a.fills=bg?[paint(bg)]:[];a.clipsContent=false;return a;}
function T(parent,chars,w,style="body",color="ink",name=null){const t=rec(figma.createText());parent.appendChild(t);t.name=name||chars.slice(0,48);t.fontName={family:"Noto Sans SC",style:"Regular"};t.textStyleId=S[style];t.characters=chars;t.textAutoResize="HEIGHT";t.resize(w,26);t.fills=[paint(color)];return t;}
function instFonts(n){for(const t of n.findAllWithCriteria({types:["TEXT"]})){created.push(t.id);t.textStyleId=S.bodyStrong;t.fontName={family:"Noto Sans SC",style:"Medium"};}}
function B(parent,label,target=null,kind="neutral"){const master=kind==="primary"?buttonPrimary:kind==="subtle"?buttonSubtle:buttonNeutral;const n=rec(master.createInstance());parent.appendChild(n);n.name="Action / "+label;n.setProperties({"Label#2:0":label,"Has Icon End#4:64":false,"Has Icon Start#4:128":false});instFonts(n);n.fills=[paint(kind==="primary"?"ink":kind==="subtle"?"surface":"wash")];for(const t of n.findAllWithCriteria({types:["TEXT"]})){t.fills=[paint(kind==="primary"?"surface":"ink")];}if(target)links.push({id:n.id,target:F[target]||target});return n;}
function Badge(parent,label,kind="neutral"){const master={neutral:tagNeutral,positive:tagPositive,warning:tagWarning,danger:tagDanger}[kind];const n=rec(master.createInstance());parent.appendChild(n);n.name="Status / "+label;n.setProperties({"Label#9765:0":label,"Removable#147:0":false});instFonts(n);for(const t of n.findAllWithCriteria({types:["TEXT"]})){t.textStyleId=S.caption;}return n;}
function Tab(parent,label,target,on=false){const n=rec((on?tabOn:tabOff).createInstance());parent.appendChild(n);n.name="Tab / "+label;n.setProperties({"Label#157:36":label});instFonts(n);if(target)links.push({id:n.id,target:F[target]||target});return n;}
function Instance(parent,type,title,detail,w=900,kind="neutral"){const master={ObjectRow:objectMaster,EvidenceCard:evidenceMaster,StatusPanel:statusMaster}[type],meta=C[type];const n=rec(master.createInstance());parent.appendChild(n);n.name=type+" / "+title;n.setProperties({[meta.titleKey]:title,[meta.detailKey]:detail});n.resize(w,n.height);n.layoutSizingVertical="HUG";const texts=n.findAllWithCriteria({types:["TEXT"]});for(const t of texts){created.push(t.id);t.resize(w-32,t.height);t.textAutoResize="HEIGHT";}n.fills=[paint(kind==="warning"?"warning":kind==="positive"?"positive":kind==="danger"?"danger":"canvas")];return n;}
function Card(parent,title,body,w=1112,kind="neutral"){const c=A(parent,title,w,"VERTICAL",8,24,kind==="warning"?"warning":kind==="positive"?"positive":kind==="danger"?"danger":"surface");c.strokes=[paint("line")];c.strokeWeight=1;for(const p of ["topLeftRadius","topRightRadius","bottomLeftRadius","bottomRightRadius"])c.setBoundVariable(p,V.radius);if(title)T(c,title,w-48,"section");if(body)T(c,body,w-48,"body","body");return c;}
function Row(parent,widths,cells,header=false){const r=A(parent,header?"Table header":"Table row",widths.reduce((a,b)=>a+b,0)+16*(widths.length-1),"HORIZONTAL",16,0,header?"canvas":null);for(let i=0;i<cells.length;i++)T(r,String(cells[i]),widths[i],header?"bodyStrong":"body",header?"ink":"body");return r;}
function Rule(parent,w){const r=A(parent,"Rule",w,"VERTICAL",0,0,"line");r.resize(w,1);r.layoutSizingVertical="FIXED";return r;}
function Head(parent,title,sub,status,kind="neutral"){T(parent,title,1112,"title");const row=A(parent,"Identity and status",1112,"HORIZONTAL",16);T(row,sub,860,"caption","muted");if(status)Badge(row,status,kind);}
function Step(parent,title,desc,w=1064){T(parent,title,w,"bodyStrong");T(parent,desc,w,"body","body");}
function setup(key,eng=false,selected="company",heading=""){const root=figma.getNodeById(F[key]);if(root.children.length)throw new Error("Refusing duplicate build "+key);mutated.push(root.id);gap(root,0);root.fills=[paint("canvas")];
const top=A(root,"Global navigation",1440,"HORIZONTAL",24,16,"surface");top.resize(1440,72);top.layoutSizingVertical="FIXED";top.counterAxisAlignItems="CENTER";T(top,"uteki",180,"title");const nav=A(top,"View navigation",eng?820:750,"HORIZONTAL",8);if(eng){for(const [l,k] of [["工作队列","E0"],["数据","E1"],["研究","E2"],["评估","E6"],["运行","E7"]])Tab(nav,l,k,k===key);}else{for(const [l,k,s]of[["公司","U1","company"],["Manager","U4","manager"],["行业","U6","industry"]])Tab(nav,l,k,s===selected);}T(top,"交互演示 · 非真实报告",eng?310:380,"caption","muted");
const work=A(root,"Workspace",1440,"HORIZONTAL",0);work.resize(1440,928);work.layoutSizingVertical="FIXED";const side=A(work,"Object navigation",240,"VERTICAL",16,16,"surface");side.resize(240,928);side.layoutSizingVertical="FIXED";T(side,eng?"工程工作区":"研究工作区",208,"section");T(side,eng?"Engineering":"Research",208,"caption","muted");
if(eng){Instance(side,"ObjectRow","GOOGL · 案例 C-01","长期 / 阶段性 · 同一证据底座",208);for(const [l,k]of[["交付问题","E0"],["资料 / 核验 / 共享","E1"],["研究计划与候选","E2"],["独立审阅","E3"],["修订与版本","E4"],["发布预览","E5"],["模型对照评估","E6"],["执行记录","E7"]])B(side,l,k,"subtle");}else{Instance(side,"ObjectRow",selected==="manager"?"长期价值型":selected==="industry"?"云与基础设施":"GOOGL","本次样例仅展开一个研究对象",208);Rule(side,208);T(side,"阅读入口",208,"bodyStrong");for(const [l,k]of[["公司完整报告","U1"],["Manager 对比","U3"],["版本变化","U7"],["关联组合报告","U5"],["行业研究","U6"]])B(side,l,k,"subtle");T(side,"滚动用于阅读。\n点击切换对象或视图。",208,"caption","muted");}
const scroll=A(work,"Scrollable reading area",1200,"VERTICAL",0);scroll.resize(1200,928);scroll.layoutSizingVertical="FIXED";scroll.clipsContent=true;scroll.overflowDirection="VERTICAL";const body=A(scroll,"Reading content",1200,"VERTICAL",24,32);scrolls.push(scroll.id);return {root,body,side,scroll};}
async function connect(){await Promise.all(links.map(async l=>{const n=await figma.getNodeByIdAsync(l.id);let top=n;while(top.parent&&top.parent.type!=="PAGE"){top=top.parent;}if(top.id===l.target){l.skipped="current screen";return;}await n.setReactionsAsync([{trigger:{type:"ON_CLICK"},actions:[{type:"NODE",destinationId:l.target,navigation:"NAVIGATE",transition:null,resetScrollPosition:false}]}]);mutated.push(n.id);}));}
function evidence(){return {createdNodeIds:created,mutatedNodeIds:mutated,links,scrolls,frames:["U11","U12"].map(k=>{const f=figma.getNodeById(F[k]);return {key:k,id:f.id,name:f.name,width:f.width,height:f.height,descendants:f.findAll(()=>true).length};})};}

const pendingKeys=["U11","U12"];
{
 const {body,side}=setup("U11",false,"manager");Head(body,"阶段性进攻型 · 组合报告","演示版本 P-S2 · 引用阶段性公司报告 v2","组合取舍");
 for(const n of side.findAllWithCriteria({types:["INSTANCE"]}).filter(n=>n.name.startsWith("ObjectRow /")))n.setProperties({[C.ObjectRow.titleKey]:"阶段性进攻型"});
 const c=Card(body,"买多少：在兑现条件满足前保留现金","演示配置：现金 100% · GOOGL 0%。本 Manager 的近期兑现假设尚未获得足够支持，不因长期 Manager 保留关注而提前建仓。");
 B(c,"查看阶段性公司研究","U10");Card(body,"方法内的组合取舍","观察可验证催化、等待期限、流动性和机会成本；触发条件改变后重新判断，集中持仓仍需说明依据。");
 Instance(body,"StatusPanel","ETF 对比：尚无有效样本","不展示名义资金、虚构收益曲线或未经冻结的基准结果。",1112);
}
{
 const {body}=setup("U12");Head(body,"阶段性进攻型 · v1 → v2","GOOGL · 演示截止 A → B","正式版本变化");
 const c=Card(body,"F-02 · 近期兑现假设下调","E-02@r2 表明部分投入预计延后投用，近期催化窗口变得更不确定。此变化属于阶段性 Manager 的独立判断。");
 Row(c,[180,426,426],["比较项","v1 · 截止 A","v2 · 截止 B"],true);Rule(c,1064);
 Row(c,[180,426,426],["证据","E-02@r1：按计划推进","E-02@r2：预计延后投用"]);
 Row(c,[180,426,426],["判断","等待经营改善信号","近期兑现预期下调"]);
 Row(c,[180,426,426],["是否买","暂不买","暂不买，继续等待"]);
 Row(c,[180,426,426],["保留未知","回报强度","回报強度"]);
 B(c,"打开阶段性完整报告","U10");B(c,"查看共同证据","U2");
}
await connect();
for(const key of ["U10","U11","U12"]){
 const root=await figma.getNodeByIdAsync(F[key]);
 for(const n of root.findAllWithCriteria({types:["INSTANCE"]})){
  const actions=n.reactions||[];let change=false;
  const next=actions.map(r=>({...r,actions:(r.actions||[]).map(a=>{
   if(a.type!=="NODE")return a;let target=a.destinationId;
   if(target===F.U5)target=F.U11;
   if(target===F.U7)target=F.U12;
   if(target===F.U1&&["Tab / 公司","Action / 公司完整报告"].includes(n.name))target=F.U10;
   if(target!==a.destinationId){change=true;return {...a,destinationId:target};}return a;
  })}));
  if(change){const valid=next.filter(r=>!(r.actions||[]).some(a=>a.type==="NODE"&&a.destinationId===root.id));await n.setReactionsAsync(valid);mutated.push(n.id);}
 }
}
{
 const root=await figma.getNodeByIdAsync(F.U2);const btn=root.findAllWithCriteria({types:["INSTANCE"]}).find(n=>n.name==="Action / 返回公司报告");
 if(btn){btn.setProperties({"Label#2:0":"返回上一阅读位置"});btn.name="Action / 返回上一阅读位置";await btn.setReactionsAsync([{trigger:{type:"ON_CLICK"},actions:[{type:"BACK"}]}]);mutated.push(btn.id,...btn.findAllWithCriteria({types:["TEXT"]}).map(t=>t.id));}
}
for(const key of ["U1","U10"]){
 const root=await figma.getNodeByIdAsync(F[key]);const body=root.findAllWithCriteria({types:["FRAME"]}).find(n=>n.name==="Reading content");
 if(!body.children.some(n=>n.name==="外部机构研报对照"))Card(body,"外部机构研报对照","本演示尚无可用的机构研报对照。不能据此推断机构是否赞同本报告。后续对照需注明机构、资料时间、核心假设、结论与分歧依据。");
}
{
 const root=await figma.getNodeByIdAsync(F.U8);const body=root.findAllWithCriteria({types:["FRAME"]}).find(n=>n.name==="Reading content");
 for(const n of root.findAllWithCriteria({types:["INSTANCE"]}).filter(n=>["Action / 查看完成后的版本变化","Action / 比较已发布报告"].includes(n.name))){n.visible=false;await n.setReactionsAsync([]);mutated.push(n.id);}
 const full=Card(body,"继续阅读完整旧版 v1","以下正文固定于演示截止 A。更新期间保留原有内容和证据，新的复核提示不修改当时的判断。");
 Step(full,"01 · 业务与价值来源","本虚构情景由成熟业务现金创造与新业务投入构成。研究关注客户需求、竞争优势、资本配置和可持续回报。");
 Step(full,"02 · 核心 Thesis","若现金创造与竞争力保持，新增投入可能增强长期价值；投资判断仍需回报证据及价格余量。");
 Step(full,"03 · 因素、风险与正反证据","F-02：投入兑现时点。E-01 提供现金创造保持的正向线索；E-02@r1 说明投入按计划推进，但未披露回报时点。投入能力不等于投入有效。");
 const original=Card(body,"E-02@r1 · 旧版引用原文（虚构）","“新增投入按计划推进，回报时点尚未披露。”\n上下文：示例披露未单独量化新增投入的回报。来源：演示源 S-02 / r1 / 演示截止 A。");
 const remaining=Card(body,"04–06 · 估值、投资条件与后续观察","估值：演示价 100，情景范围 85–125（虚构单位）。安全余量与兑现时点高度相关。\n是否买：暂不买，保留观察。\n复核条件：投入回报证据补足、价格提供足够余量，或出现经营基础弱化的反证。\n仍未知：回报强度、归因与兑现时间。组合配置独立解释。");
 const scrollButton=B(full,"定位旧版引用原文");
 await scrollButton.setReactionsAsync([{trigger:{type:"ON_CLICK"},actions:[{type:"NODE",destinationId:original.id,navigation:"SCROLL_TO",transition:null}]}]);mutated.push(scrollButton.id);
}
{
 const root=await figma.getNodeByIdAsync(F.U9);
 for(const n of root.findAllWithCriteria({types:["INSTANCE"]}).filter(n=>n.name==="Action / 查看本演示中的完成状态")){n.visible=false;await n.setReactionsAsync([]);mutated.push(n.id);}
}
return {createdNodeIds:created,mutatedNodeIds:mutated,links,completedCorrections:["Manager-specific portfolio/history","contextual evidence return","complete v1 body","external report comparison gap"],frames:pendingKeys.map(k=>({key:k,id:F[k]}))};
