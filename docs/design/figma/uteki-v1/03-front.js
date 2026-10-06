
const state={"createdNodeIds":["3:2","3:3","3:32","3:33","3:34","3:35","3:36","3:37","3:38","3:39","3:40","3:41","3:42","3:43","3:44","3:45","3:46","3:47","3:48","3:49","3:50","3:51","3:52","3:53","3:54","3:55","3:56","3:57","3:58","3:59","3:60","3:61"],"mutatedNodeIds":["0:1"],"fileKey":"0SogEfR3y4xLDl9YB5RbOQ","pages":{"overview":"0:1","front":"3:2","back":"3:3"},"cover":"3:43","masters":"3:32","frames":{"U1":"3:44","U2":"3:45","U3":"3:46","U4":"3:47","U5":"3:48","U6":"3:49","U7":"3:50","U8":"3:51","U9":"3:52","E0":"3:53","E1":"3:54","E2":"3:55","E3":"3:56","E4":"3:57","E5":"3:58","E6":"3:59","E7":"3:60","E8":"3:61","U10":"4:2"},"components":{"ObjectRow":{"id":"3:34","titleKey":"Title#3:0","detailKey":"Description#3:1"},"EvidenceCard":{"id":"3:37","titleKey":"Title#3:2","detailKey":"Description#3:3"},"StatusPanel":{"id":"3:40","titleKey":"Title#3:4","detailKey":"Description#3:5"}},"variables":{"surface":"VariableID:3:5","canvas":"VariableID:3:6","ink":"VariableID:3:7","body":"VariableID:3:8","muted":"VariableID:3:9","line":"VariableID:3:10","accent":"VariableID:3:11","wash":"VariableID:3:12","warning":"VariableID:3:13","warningInk":"VariableID:3:14","positive":"VariableID:3:15","positiveInk":"VariableID:3:16","danger":"VariableID:3:17","dangerInk":"VariableID:3:18","radius":"VariableID:3:19","s8":"VariableID:15bb1c0f339146e931cf0dc15f89ed57dcbd907e/564:255","s16":"VariableID:16bc6f84b6e7e20e4234ef79030ee580ec0f4505/564:258","s24":"VariableID:be3115966ea99eef888c9f25751b54695c7e88d2/564:260","s32":"VariableID:9acadea8b7c7c9884455b896e21c88b8bc62d6da/564:261","s48":"VariableID:d1a1caa0985a992cee4da9c73948f850813e97d2/564:252"},"styles":{"caption":"S:484e456b0e79889fb3c2580ffa19af233793329a,","body":"S:1bfdba73493ce0a3ffb8128db1e7df5bc518fb69,","bodyStrong":"S:b924045aadcd52da2db634588f997459357406f2,","section":"S:add3b55fc06800a0b684d254e3a07a0dc650b4c7,","title":"S:076112472bb50649fc588d3158973511cc5ff82e,","display":"S:17ba817d75d857cd901adc8bdc1110655e7f1196,"},"counts":{"screens":18,"components":3,"textStyles":6},"font":"Noto Sans SC"};
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
function evidence(){return {createdNodeIds:created,mutatedNodeIds:mutated,links,scrolls,frames:["U1","U2","U3","U4","U5","U6","U7","U8","U9","U10"].map(k=>{const f=figma.getNodeById(F[k]);return {key:k,id:f.id,name:f.name,width:f.width,height:f.height,descendants:f.findAll(()=>true).length};})};}

const keys=["U1","U2","U3","U4","U5","U6","U7","U8","U9","U10"];
function report(key,short=false){
 const {body}=setup(key,false,"company");Head(body,"GOOGL / Alphabet",short?"阶段性进攻型 · 3–6 个月 · 报告 v2 · 演示截止 B":"长期价值型 · 3–5 年 · 报告 v2 · 演示截止 B","正式报告","positive");
 const managerNav=A(body,"Manager selection",1112,"HORIZONTAL",16);Tab(managerNav,"长期价值型","U1",!short);Tab(managerNav,"阶段性进攻型","U10",short);B(managerNav,"比较两位 Manager","U3");
 const intro=Card(body,short?"等待可验证的兑现信号":"业务价值与回报时点分别判断",short?"近期兑现假设受到新说明影响。在投入投用与经营改善之间建立证据前，暂不买入。":"在本虚构情景中，核心业务仍可创造现金，新增投入可能增强长期竞争力。回报强度和时点仍不明确，因此暂不买入，保留有条件观察。");
 const pills=A(intro,"Report summary",1064,"HORIZONTAL",16);Badge(pills,"判断：观察");Badge(pills,"关键未知：投入回报","warning");B(pills,"查看 v1 → v2 的变化","U7");
 const toc=A(body,"Report reading navigation",1112,"HORIZONTAL",16);T(toc,"本文：业务 / Thesis / 因素与风险 / 估值 / 投资条件",810,"caption","muted");B(toc,"关联组合报告","U5","subtle");
 const business=Card(body,"01 · 业务与价值来源","本示例将业务分为成熟业务现金创造与新业务投入两部分。研究要解释客户为什么付费、竞争优势如何维持，以及新增资本是否能形成可持续回报。这里仅演示报告表达，不构成对 Alphabet 的真实业务研究。");
 const thesis=Card(body,"02 · 核心 Thesis",short?"T-S：短期机会取决于经营改善能够在预设窗口内被证实。投用延后削弱近期催化，保留观察，等待时间与验证条件同时满足。":"T-L：若核心现金创造能力保持、投入形成持续竞争力，长期价值仍可能增长；但不能用长期叙事跳过投入回报的检验。");
 Step(thesis,"什么会推翻判断","经营基础明显弱化；新增投入缺乏可验证回报；或价格要求的增长显著高于可支持情景。");
 const factor=Card(body,"03 · 因素与风险：F-02 投入兑现时点","新证据支持“投用可能延后”，尚不足以支持“回报率已经下降”。对回报幅度保持未知。");
 const evrow=A(factor,"Support and counterevidence",1064,"HORIZONTAL",16);
 Instance(evrow,"EvidenceCard","E-01 · 正向线索","虚构摘录：核心业务现金创造保持稳定。只支持投入能力，不证明新增投入有效。",524);
 const neg=Instance(evrow,"EvidenceCard","E-02@r2 · 反向证据","虚构摘录：预计部分投入延后投用，尚无法单独评估回报。",524,"warning");
 links.push({id:neg.id,target:F.U2});B(factor,"打开 E-02 原文与上下文","U2");
 const value=Card(body,"04 · 估值与价格条件","演示价格为 100，情景价值区间为 85–125（均为虚构单位，不是 GOOGL 股价或目标价）。当前区间对回报时点敏感，不足以支持立即买入。");
 Row(value,[260,330,442],["情景","关键假设","判断影响"],true);Rule(value,1064);
 Row(value,[260,330,442],["保守：85","投入增加，兑现继续延后","缺乏安全余量"]);
 Row(value,[260,330,442],["中性：105","现金基础保持，逐步兑现","吸引力有限"]);
 Row(value,[260,330,442],["积极：125","增量回报得到后续证据支持","需验证假设，不能提前视为事实"]);
 T(value,"此估值表仅用于交互占位；尚无真实模型、现金流计算或投资结论。",1064,"caption","muted");
 const decision=Card(body,"05 · 是否买，与什么条件下重看","当前：暂不买。若投入兑现证据补足、价格提供足够余量，再重新评估；反证增强则下调判断。仓位大小在组合报告中单独解释。");
 B(decision,"查看买多少的组合取舍","U5");const watch=Card(body,"06 · 后续观察与未知","跟踪投用时间、投入对应的经营改善、现金创造变化及竞争压力。无法归因的回报继续保留未知；不因报告发布就把未知标记为已解决。");
 B(watch,"查看相关行业因素","U6");B(watch,"阅读另一位 Manager 的完整报告",short?"U1":"U10");
}
report("U1",false);report("U10",true);
{
 const {body}=setup("U2");Head(body,"E-02 · 原文与判断依据","GOOGL · 演示源 S-02 · r2 · 演示披露时点 B","已核验出处","positive");
 B(body,"返回公司报告","U1","subtle");
 const q=Card(body,"来源摘录（虚构）","“预计部分投入延后投用，尚无法单独评估回报。”");
 T(q,"原文上下文：新增投入仍在推进，项目投用安排存在变化。本段未披露单项投入的回报幅度。",1064);
 const row=A(body,"Evidence interpretation",1112,"HORIZONTAL",16);
 Card(row,"能够支持","投入投用时点存在变化；近期兑现假设需要复核。",548);
 Card(row,"不能支持","已经发生回报下降；全部投入失效；或公司价值已发生确定幅度变化。",548,"warning");
 const use=Card(body,"关联判断","长期 Manager：保留长期可能性，继续核验回报。\n阶段性 Manager：近期兑现条件未满足，维持等待。\n共同引用：F-02 / E-02@r2。");
 B(use,"查看两位 Manager 的分歧","U3");B(use,"查看证据修订前后的报告变化","U7");T(body,"历史 r1 保留在 v1 的证据链。阅读原文不会触发新研究。",1112,"caption","muted");
}
{
 const {body}=setup("U3");Head(body,"同一公司，不同判断方法","GOOGL · 同一演示截止 B · 两份正式 v2","可比较");
 const cols=A(body,"Manager comparison",1112,"HORIZONTAL",24);
 const l=Card(cols,"长期价值型","3–5 年 · 关注长期现金创造与竞争力",544),r=Card(cols,"阶段性进攻型","3–6 个月 · 关注可验证的近期兑现",544);
 Step(l,"Thesis","投入仍可能增强长期竞争力；回报时点后移不直接等于价值消失。",496);
 Step(r,"Thesis","催化兑现窗口缩窄；近期投入改善证据不足，保持等待。",496);
 Step(l,"对 E-02 的解释","调整兑现假设，保留长期可能性；未知仍需核验。",496);
 Step(r,"对 E-02 的解释","下调近期兑现预期；条件满足前不支持买入。",496);
 Step(l,"是否买","暂不买，等待证据与价格条件。",496);
 Step(r,"是否买","暂不买，等待经营改善信号。",496);
 B(l,"打开长期完整报告","U1");B(r,"打开阶段性完整报告","U10");
 const shared=Card(body,"共享事实，独立采纳","两位 Manager 均可使用核验后的 E-02@r2。差异来自期限、假设与风险取舍，页面不平均两份估值，也不自动选出“赢家”。");
 B(shared,"查看共同证据 E-02","U2");Instance(body,"StatusPanel","若一侧未发布","对应栏目显示“尚未发布”，不使用内部草稿补齐比较。",1112);
}
{
 const {body}=setup("U4",false,"manager");Head(body,"长期价值型 Manager","标准 Manager · 方法版本 M-L1 · 演示账户","方法已说明");
 const method=Card(body,"方法与约束","关注 3–5 年内可持续现金创造、竞争优势与资本配置。个股、只做多、无杠杆；允许现金与有依据的集中持仓。日频跟踪重要变化。");
 const research=Card(body,"正在覆盖的公司","GOOGL · 正式报告 v2 · F-02 投入兑现时点已更新 · 回报幅度仍未知。");
 B(research,"打开 GOOGL 公司报告","U1");B(research,"查看本次判断变化","U7");
 const portfolio=Card(body,"组合与表现","本次演示：现金 100%，个股 0%。组合报告说明为何保持现金。ETF 对比尚无有效样本，不展示虚构收益曲线。");
 B(portfolio,"打开组合报告","U5");
 Instance(body,"StatusPanel","账户、研究、表现分别表达","无持仓不等于没有研究；全现金可以是明确决策；样本不足不等于收益为零。",1112);
}
{
 const {body}=setup("U5",false,"manager");Head(body,"长期价值型 · 组合报告","演示版本 P-L2 · 引用公司报告 v2","组合取舍");
 const sum=Card(body,"买多少：本轮保持现金","演示配置：现金 100% · GOOGL 0%。公司报告尚不支持当前买入，组合中等待条件满足；本页只展示比例。");
 Row(sum,[350,330,352],["项目","权重","原因"],true);Rule(sum,1064);
 Row(sum,[350,330,352],["现金","100%（演示）","等待可验证机会"]);Row(sum,[350,330,352],["GOOGL","0%（演示）","价格和兑现证据未满足"]);
 B(sum,"查看是否买的公司研究","U1");
 Card(body,"如果未来买入，如何说明配置","解释新增持仓相对于现金和其他机会的吸引力、集中度、共同风险及退出条件。当前样例不增加公司池或给出真实调仓建议。");
 Instance(body,"StatusPanel","ETF 对比：尚无有效样本","对应基准与模拟成交规则尚待冻结。展示实际覆盖后再比较，不用占位曲线表现收益。",1112);
}
{
 const {body}=setup("U6",false,"industry");Head(body,"云与基础设施 · 行业专题","演示档案 I-01 · 版本 2 · 研究责任：行业研究","共享研究");
 const thesis=Card(body,"共同问题：投入增长何时带来回报","在本虚构情景中，扩张带来长期能力，也使兑现时点与需求匹配成为共同风险。行业判断有作者和版本，不能自动成为各 Manager 的公司结论。");
 const table=Card(body,"向公司的传导","F-02：投用安排 → 利用率与收入兑现 → 现金回报。每一环都需证据，不跨过中间环节直接推断最终收益。");
 Row(table,[240,370,422],["对象","采纳方式","仍然未知"],true);Rule(table,1064);Row(table,[240,370,422],["长期 Manager","保留长期竞争力假设","回报强度与归因"]);Row(table,[240,370,422],["阶段性 Manager","下调近期兑现预期","改善何时可被验证"]);
 B(table,"查看 GOOGL 的不同解释","U3");B(table,"打开关联证据","U2");
 Card(body,"研究范围","本稿展示行业判断与公司报告的引用关系。池外资料使用范围、外部机构研报必需程度仍待确认。");
}
{
 const {body}=setup("U7");Head(body,"v1 → v2：哪些判断改变了","GOOGL · 长期价值型 · 演示截止 A → B","正式版本变化");
 const t=Card(body,"F-02 · 投入兑现时点","新说明改变了兑现时点的依据；并未证明回报幅度已经下降。");
 Row(t,[180,426,426],["比较项","v1 · 截止 A","v2 · 截止 B"],true);Rule(t,1064);
 Row(t,[180,426,426],["证据","E-02@r1：投入按计划推进","E-02@r2：预计部分投入延后投用"]);
 Row(t,[180,426,426],["判断","兑现时点仍待验证","兑现可能后移"]);
 Row(t,[180,426,426],["保留未知","新增投入回报","新增投入回报"]);
 Row(t,[180,426,426],["投资结论","暂不买，保留观察","暂不买，继续观察"]);
 const actions=A(t,"Version actions",1064,"HORIZONTAL",16);B(actions,"查看当前完整 v2","U1");B(actions,"查看引用原文","U2");B(actions,"查看旧版待复核状态","U8","subtle");
 T(body,"结论未变，也保留重要证据与假设的变化。历史内容保持固定。",1112,"body","body");
}
{
 const {body}=setup("U8");Head(body,"GOOGL / Alphabet","长期价值型 · 当前展示旧版 v1 · 演示截止 A","结论待复核","warning");
 Instance(body,"StatusPanel","F-02 受到新说明影响","新材料可能改变投入兑现假设。旧版正文与信息截止 A 保留，请结合这项提示阅读。",1112,"warning");
 Card(body,"旧版 Thesis（固定 v1）","假设核心业务能够持续创造现金；新增投入可能增强竞争力，投入回报时点仍待验证。此处保留当时的判断，不用新资料静默重写。");
 Card(body,"本次需注意","受影响：投入兑现时点、相关估值假设。当前仅说明正在复核的范围；修订完成前不展示内部草稿。");
 const r=A(body,"Read existing version",1112,"HORIZONTAL",16);B(r,"查看完成后的版本变化","U7");B(r,"比较已发布报告","U3");T(body,"这是更新期间的状态演示；点击仅切换样例画面。",1112,"caption","muted");
}
{
 const {body}=setup("U9");Head(body,"GOOGL / Alphabet","阶段性进攻型 · 首次研究 · 尚无正式报告","研究中");
 Instance(body,"StatusPanel","正式报告准备中","资料准备、核心研究与审阅完成后，这里会提供完整报告。当前不展示阶段性草稿或推测结论。",1112);
 const alt=Card(body,"已有内容仍可阅读","若另一位 Manager 已发布报告，可独立阅读；不把另一位的判断作为本 Manager 的结论。");
 B(alt,"查看长期 Manager 报告","U1");B(alt,"查看本演示中的完成状态","U10","subtle");
}
await connect();page.flowStartingPoints=[{nodeId:F.U1,name:"前台 · 公司报告与证据"},{nodeId:F.U8,name:"前台 · 更新期间"},{nodeId:F.U9,name:"前台 · 首次研究中"}];mutated.push(page.id);
return evidence();
