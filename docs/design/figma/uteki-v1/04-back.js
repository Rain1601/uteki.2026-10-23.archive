const state={"createdNodeIds":["3:2","3:3","3:32","3:33","3:34","3:35","3:36","3:37","3:38","3:39","3:40","3:41","3:42","3:43","3:44","3:45","3:46","3:47","3:48","3:49","3:50","3:51","3:52","3:53","3:54","3:55","3:56","3:57","3:58","3:59","3:60","3:61"],"mutatedNodeIds":["0:1"],"fileKey":"0SogEfR3y4xLDl9YB5RbOQ","pages":{"overview":"0:1","front":"3:2","back":"3:3"},"cover":"3:43","masters":"3:32","frames":{"U1":"3:44","U2":"3:45","U3":"3:46","U4":"3:47","U5":"3:48","U6":"3:49","U7":"3:50","U8":"3:51","U9":"3:52","E0":"3:53","E1":"3:54","E2":"3:55","E3":"3:56","E4":"3:57","E5":"3:58","E6":"3:59","E7":"3:60","E8":"3:61","U10":"4:2"},"components":{"ObjectRow":{"id":"3:34","titleKey":"Title#3:0","detailKey":"Description#3:1"},"EvidenceCard":{"id":"3:37","titleKey":"Title#3:2","detailKey":"Description#3:3"},"StatusPanel":{"id":"3:40","titleKey":"Title#3:4","detailKey":"Description#3:5"}},"variables":{"surface":"VariableID:3:5","canvas":"VariableID:3:6","ink":"VariableID:3:7","body":"VariableID:3:8","muted":"VariableID:3:9","line":"VariableID:3:10","accent":"VariableID:3:11","wash":"VariableID:3:12","warning":"VariableID:3:13","warningInk":"VariableID:3:14","positive":"VariableID:3:15","positiveInk":"VariableID:3:16","danger":"VariableID:3:17","dangerInk":"VariableID:3:18","radius":"VariableID:3:19","s8":"VariableID:15bb1c0f339146e931cf0dc15f89ed57dcbd907e/564:255","s16":"VariableID:16bc6f84b6e7e20e4234ef79030ee580ec0f4505/564:258","s24":"VariableID:be3115966ea99eef888c9f25751b54695c7e88d2/564:260","s32":"VariableID:9acadea8b7c7c9884455b896e21c88b8bc62d6da/564:261","s48":"VariableID:d1a1caa0985a992cee4da9c73948f850813e97d2/564:252"},"styles":{"caption":"S:484e456b0e79889fb3c2580ffa19af233793329a,","body":"S:1bfdba73493ce0a3ffb8128db1e7df5bc518fb69,","bodyStrong":"S:b924045aadcd52da2db634588f997459357406f2,","section":"S:add3b55fc06800a0b684d254e3a07a0dc650b4c7,","title":"S:076112472bb50649fc588d3158973511cc5ff82e,","display":"S:17ba817d75d857cd901adc8bdc1110655e7f1196,"},"counts":{"screens":18,"components":3,"textStyles":6},"font":"Noto Sans SC"};
const created=[],mutated=[],links=[],scrolls=[];
const page=await figma.getNodeByIdAsync("3:3");await figma.setCurrentPageAsync(page);
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
function evidence(){return {createdNodeIds:created,mutatedNodeIds:mutated,links,scrolls,frames:["E0","E1","E2","E3","E4","E5","E6","E7","E8"].map(k=>{const f=figma.getNodeById(F[k]);return {key:k,id:f.id,name:f.name,width:f.width,height:f.height,descendants:f.findAll(()=>true).length};})};}

{
 const {body}=setup("E0",true);Head(body,"交付工作队列","工程视角 · 演示时间切片 ① · 案例 C-01","2 项阻断","warning");
 const count=A(body,"Delivery summary",1112,"HORIZONTAL",16);Card(count,"数据核验","1 项内容问题",360,"warning");Card(count,"研究质量","1 项推断待修订",360,"warning");Card(count,"对外报告","仍提供旧版 v1",360);
 const list=Card(body,"优先处理影响交付的事项","先定位对象、实际缺口和可继续条件；重复重试归入同一问题。");
 Row(list,[160,340,240,276],["对象","当前问题","状态","下一步"],true);Rule(list,1064);
 Row(list,[160,340,240,276],["D-01 / Data","计划被误写为实际投用","内容核验未通过","核对 E-02 的原文及归属"]);
 B(list,"打开 D-01 与数据修订","E1");
 Row(list,[160,340,240,276],["R-01 / Review","投用延后被写成回报下降","质量问题未解决","定位报告论断并修订"]);
 B(list,"打开 R-01 审阅发现","E3");
 Row(list,[160,340,240,276],["PUB-02","新版尚未完成发布","前台仍为 v1","检查固定版本和发布条件"]);
 B(list,"查看发布预览","E5");
 T(body,"此队列是情景起点。后续画面展示相应任务完成修订后的时间切片。",1112,"caption","muted");
}
{
 const {body}=setup("E1",true);Head(body,"Data · 从候选到核验共享","C-01 / D-01 · 证据 E-02 · B1 → B2","修订后已共享","positive");
 const coverage=Card(body,"01 · 资料覆盖","演示清单：年报、季报、重大公告及公司公开业绩资料。文件可读性、来源身份和历史范围分别检查；本屏用虚构材料演示。");
 Row(coverage,[220,310,220,266],["资料","来源 / 时间","内容可读","范围"],true);Rule(coverage,1064);
 Row(coverage,[220,310,220,266],["示例财报 S-01","原文快照 r1 / 截止 A","正文与表格可读","显式演示期间"]);
 Row(coverage,[220,310,220,266],["示例新说明 S-02","原文快照 r2 / 截止 B","正文可读","F-02 专题补充"]);
 const finance=Card(body,"02 · 核心财务包（全部为虚构示例）","展示指标定义、期间、口径与原文；此表不能作为 Alphabet 财务数据使用。");
 Row(finance,[200,140,260,416],["指标","演示数值","期间 / 单位","口径与来源"],true);Rule(finance,1064);
 for(const row of [["营收","100","演示 FY-A / 虚构单位","合并口径 · S-01 表 A 第 1 行"],["净利润","20","演示 FY-A / 虚构单位","归属口径明确 · S-01 表 A 第 2 行"],["经营现金流","30","演示 FY-A / 虚构单位","现金流量表 · S-01 表 B 第 1 行"],["资本支出","12","演示 FY-A / 虚构单位","购建现金支出 · S-01 表 B 第 2 行"],["现金 / 债务","40 / 10","演示期末 / 虚构单位","定义与合并范围分别保存"],["股本","5","演示期末 / 虚构股数","期末股数，不替代加权平均股数"]])Row(finance,[200,140,260,416],row);
 const issue=Card(body,"03 · D-01：计划被写成实际","引用存在、期间可解析，仍不足以证明提取语义正确。");
 const cols=A(issue,"Before and after data correction",1064,"HORIZONTAL",16);
 const a=Card(cols,"候选 B1 · 未通过","错误提取：“已完成投用”。\n程序检查：通过。\n内容核验：未通过。\n正式分析：不可使用。",524,"danger");
 const b=Card(cols,"修订 B2 · 核验后共享","修正：“管理层预计部分投入延后投用”。\n归属：管理层说法。\n程序与内容核验：通过。\n保留原文、归属和披露时间。",524,"positive");
 const sharing=Card(body,"04 · 共享状态与引用","B2 供所有 Manager 按信息截止读取。长期与阶段性案例各自保存采纳决定；共享不会改写旧任务的 B1 输入。核验原文只证明披露了这个说法，不证明预测会实现。");
 B(sharing,"查看采用 B2 的研究任务","E2");B(sharing,"查看原始取证与运行记录","E7");
 Instance(body,"StatusPanel","失败状态也必须保留","获取失败、解析失败、内容核验未通过分别记录；失败不等于无资料，也不能显示“无新变化”。",1112,"warning");
}
{
 const {body}=setup("E2",true);Head(body,"Analysis · 研究计划与候选","C-01 / A-02 · 输入 B2 · 候选 v2-a","待审阅","warning");
 const plan=Card(body,"研究问题与计划","问题：新说明究竟改变兑现时点，还是证明回报强度变化？\n范围：GOOGL / F-02 / 演示截止 B。");
 Step(plan,"1 · 核查材料实际说了什么","读取 B2 与 E-02@r2，区分事实、归属明确的说法和推断。");
 Step(plan,"2 · 分别检验两种方法","长期侧关注持续回报；阶段侧关注预设窗口的兑现。共享输入，独立采纳。");
 Step(plan,"3 · 重看估值与反证","调整时点假设，检查是否对回报幅度作了超出证据的判断。");
 const draft=Card(body,"候选 v2-a · 尚未发布","问题句：“投用延后说明投入回报已经下降。”\n这一候选用于演示质量问题；不会出现在用户正式报告中。",1112,"warning");
 const map=Card(body,"输入与产物","输入：证据包 B2 / E-02@r2 / 方法 M-L1。\n输出：报告候选 v2-a、假设变化、引用、未知与观察需求。\n执行配置：规划、取证、综合与审阅分别记录实际模型及 Skill 版本。");
 const actions=A(map,"Analysis actions",1064,"HORIZONTAL",16);B(actions,"查看独立审阅","E3");B(actions,"检查输入数据","E1");B(actions,"查看执行记录","E7");
}
{
 const {body}=setup("E3",true);Head(body,"Review · 独立初判与报告对照","C-01 / R-01 · 目标：v2-a / F-02","实质质量问题","warning");
 const phase1=Card(body,"第一阶段 · 已冻结的独立初判","在读取作者报告前，Reviewer 已收到同范围材料、问题和方法期限。初判：材料支持投用时点变化，不能据此判断回报幅度。");
 T(phase1,"阶段输入不含作者报告、摘要或结论；此处展示可见评审结论，不展示隐藏推理。",1064,"caption","muted");
 const phase2=Card(body,"第二阶段 · R-01 对照发现","作者候选：“投用延后说明投入回报已经下降。”\n问题：将时间变化直接升级为回报幅度变化，证据 E-02 不支持该确定性判断。",1112,"danger");
 Step(phase2,"需要修订","将“已经下降”改为有证据支持的时点判断；明确回报幅度仍未知。");
 Step(phase2,"Manager 回应","接受质量问题。长期可能性保留；是否等待以及等待多久，仍按自身方法判断。");
 const status=A(phase2,"Review status",1064,"HORIZONTAL",16);Badge(status,"发现已记录");Badge(status,"修订待复核","warning");B(status,"查看作者修订","E4");
 Card(body,"质量问题与观点分歧分开","事实、引用、计算和推理问题需要处理；预测或风险取舍可以保留分歧，Manager 回应重要质疑并承担判断责任。");
}
{
 const {body}=setup("E4",true);Head(body,"Revision · 新版本与问题处理","父版本 v2-a → 候选 v2-b · 关联 R-01","已处理，待复核","warning");
 const row=A(body,"Revision comparison",1112,"HORIZONTAL",16);
 Card(row,"修订前 · v2-a","“投用延后说明投入回报已经下降。”\n问题：推断超出引用支持范围。",548,"danger");
 Card(row,"修订后 · v2-b","“兑现可能延后；现有资料不足以判断回报幅度。”\n保留正反证据与实质未知。",548,"positive");
 const review=Card(body,"逐项处理记录","R-01：接受并修订。\n定位：F-02 第 2 段，引用 E-02@r2。\n需复核：新措辞、估值时点假设和关联章节是否一致。\n保留：长期与阶段性 Manager 的独立观点。");
 Row(review,[270,400,362],["对象","已完成","仍需完成"],true);Rule(review,1064);Row(review,[270,400,362],["R-01","作者已回应并提交新版本","Reviewer 核对修改及影响"]);
 B(review,"查看复核完成后的发布预览","E5");B(review,"返回审阅记录","E3","subtle");
 T(body,"导航到后续画面只演示状态变化，不执行真实修订、审核或发布。",1112,"caption","muted");
}
{
 const {body}=setup("E5",true);Head(body,"Publication · 用户可见预览","固定版本 v2-b · 证据集 B2 · 演示截止 B","尚未发布");
 const gates=A(body,"Separate publication gates",1112,"HORIZONTAL",16);Card(gates,"数据核验","通过 · B2",360,"positive");Card(gates,"研究审阅","完成 · R-01 已复核",360,"positive");Card(gates,"对外发布","尚未执行",360);
 const preview=Card(body,"用户预览：GOOGL · 长期价值型","投资判断：暂不买，保留观察。\n核心变化：投入兑现可能后移。\n关键未知：回报幅度尚不能判断。\n用户可读：完整报告、正反证据、假设、估值条件与版本变化。");
 const refs=A(preview,"Preview references",1064,"HORIZONTAL",16);Badge(refs,"固定 v2-b");Badge(refs,"E-02@r2");Badge(refs,"未知保留","warning");
 const boundary=Card(body,"发布边界检查","对外字段和证据按固定版本生成。内部 Prompt、候选、工具过程、运行成本及隐藏名义资金不进入用户接口。发布完成才替换前台当前版本，旧版仍保留。");
 const actions=A(boundary,"Publication scenario actions",1064,"HORIZONTAL",16);B(actions,"演示：发布失败","E8");B(actions,"查看版本与修订","E4","subtle");
 Instance(body,"StatusPanel","若预览生成后版本发生变化","提示“预览已失效，请重新生成”；旧预览不能代表新版本发布。常规发布依据既定政策，不新增逐份人工审批。",1112,"warning");
}
{
 const {body}=setup("E6",true);Head(body,"Evaluation · 方法固定，比较模型配置","同问题 / 同资料 / 同截止 / 同评价规则","待执行样例");
 const matrix=Card(body,"同一 Manager 的模型对照","以下为实验结构示例，不代表已完成的实验结果或已接入的新模型。关键规划与推理优先高能力模型，限定子任务再比较性价比。");
 Row(matrix,[240,270,260,246],["配置","规划与综合","取证子任务","状态"],true);Rule(matrix,1064);
 Row(matrix,[240,270,260,246],["混合配置 A","高能力档","经济档","本样例未执行"]);
 Row(matrix,[240,270,260,246],["全量配置 B","同一明确模型","同一明确模型","本样例未执行"]);
 Row(matrix,[240,270,260,246],["单环节替换 C","固定基线","替换指定环节","本样例未执行"]);
 const assess=Card(body,"评什么，如何解释结果","核心问题覆盖、证据忠实度、反证处理、推断强度、修订效果；同时记录成本、延迟和结束原因。研究质量与投资表现分开评价，测试通过不直接等于研究可交付。");
 Instance(body,"StatusPanel","当前没有可比较的结果","不填写占位胜率、费用或收益。达到同条件真实评测后，再解释差异和适用范围。",1112);
 B(assess,"查看运行中实际配置记录","E7");B(assess,"查看质量问题样例","E3");
}
{
 const {body}=setup("E7",true);Head(body,"Runtime · 一次尝试如何结束","C-01 / task A-02 / run R-02 · 演示记录","已封存");
 const chain=Card(body,"任务、尝试与产物","父任务：复核 F-02。\n输入：B2 / E-02@r2 / 方法 M-L1 / 截止 B。\n产物：候选 v2-a、引用检查结果、未解决问题。\n结束：候选已交付；研究审阅尚未完成。");
 const config=Card(body,"实际配置与使用情况","此设计稿未触发模型运行，下列字段展示应记录的结构。");
 Row(config,[240,340,452],["字段","记录方式","当前样例"],true);Rule(config,1064);
 Row(config,[240,340,452],["角色 / 模型","provider + 准确 model + 配置版本","未执行，无实测值"]);
 Row(config,[240,340,452],["Skill","方法名、版本与内容哈希","示意配置引用"]);
 Row(config,[240,340,452],["用量 / 延迟","实际请求、token、费用口径与耗时","未测，不填零"]);
 Row(config,[240,340,452],["结束原因","完成 / 缺资料 / 失败 / 停止","候选完成，后续审阅待进行"]);
 const records=Card(body,"可见执行过程","读取材料 → 补充问题 → 提取候选 → 程序检查 → 内容核验 → 封存产物。保存实际可见输出与工具结果，凭据脱敏，不展示隐藏推理。");
 B(records,"返回候选报告","E2");B(records,"查看独立评估","E6");
 Instance(body,"StatusPanel","重试与恢复","新尝试关联原任务，保留旧输入与失败产物；仅在运行控制接口和权限接通时开放执行操作。",1112);
}
{
 const {body}=setup("E8",true);Head(body,"Publication · 发布失败","PUB-02 / 固定 v2-b · 演示时间切片 ④","发布失败","danger");
 Instance(body,"StatusPanel","新版发布未成功，前台仍为 v1","数据核验和研究审阅已经完成，不能因此显示发布成功。旧报告保留，F-02 的待复核提示也继续保留。",1112,"danger");
 const facts=Card(body,"系统必须返回的真实状态","拟发布版本：v2-b。\n当前正式版本：v1。\n失败阶段：发布提交（演示）。\n已保留：预览、审阅记录和候选版本。\n可继续条件：先核实是否存在成功提交，再使用同一发布身份恢复。");
 B(facts,"返回固定版本预览","E5");B(facts,"查看工作队列","E0","subtle");
 Card(body,"读者看到什么","仍可阅读旧 v1 及原截止时间，并看到受影响的 F-02 待复核提示。不存在一份只在后台完成、前台却被标为已发布的新报告。");
}
await connect();page.flowStartingPoints=[{nodeId:F.E0,name:"后台 · 数据到审阅与发布"},{nodeId:F.E8,name:"后台 · 发布失败"}];mutated.push(page.id);return evidence();
