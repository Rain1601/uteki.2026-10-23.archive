const created=[],mutated=[];
const page=await figma.getNodeByIdAsync("3:3");await figma.setCurrentPageAsync(page);
await Promise.all([{family:"Noto Sans SC",style:"Regular"},{family:"Noto Sans SC",style:"Medium"},{family:"Noto Sans SC",style:"Bold"}].map(f=>figma.loadFontAsync(f)));
const roots=await Promise.all(["3:53","3:54","3:55","3:56","3:57","3:58","3:59","3:60","3:61"].map(id=>figma.getNodeByIdAsync(id)));
for(const root of roots){
 for(const n of root.findAllWithCriteria({types:["TEXT"]})){
  let next=n.characters;
  next=next.replaceAll("GOOGL · 案例 C-01","GOOGL · 长期案例 C-L01").replaceAll("长期 / 阶段性 · 同一证据底座","长期价值型 · 方法 M-L1").replaceAll("C-01","C-L01");
  next=next.replace("2 · 分别检验两种方法","2 · 检验长期方法的关键假设").replace("长期侧关注持续回报；阶段侧关注预设窗口的兑现。共享输入，独立采纳。","本任务只形成长期 Manager 的报告。阶段性案例 C-S01 独立引用共享 B2，不使用本任务的观点作为自身结论。");
  next=next.replace("固定版本 v2-b · 证据集 B2 · 演示截止 B","长期案例 C-L01 · 内部 v2-b / 对外显示 v2 · 证据集 B2");
  if(next!==n.characters){n.characters=next;mutated.push(n.id);}
 }
}
return {createdNodeIds:created,mutatedNodeIds:mutated,scope:"backend Manager ownership"};
