import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const root='/Users/rain/Documents/ChatGPT/uteki.beta';
const out=new URL('.',import.meta.url).pathname;
const text=await fs.readFile(`${root}/docs/DATA_AGENT_THREE_WORKSTREAMS.zh-CN.md`,'utf8');
const tables=[];let rows=[];
for(const line of text.split('\n')){
 if(line.startsWith('|'))rows.push(line.split('|').slice(1,-1).map(c=>c.trim().replaceAll('**','')));
 else if(rows.length){tables.push(rows.filter(r=>!r.every(c=>/^-+$/.test(c))));rows=[];}
}
if(rows.length)tables.push(rows);
if(tables.length!==5)throw new Error('Unexpected module structure');
const wb=Workbook.create(), main=wb.worksheets.add('三个主待办'), detail=wb.worksheets.add('模块与问题');
function setup(sheet,title,note,widths,last){
 sheet.showGridLines=false;
 sheet.getRange(`A1:F${last}`).format.font={name:'Arial',size:11,color:'#233746'};
 widths.forEach((w,i)=>sheet.getRangeByIndexes(0,i,last,1).format.columnWidthPx=w);
 sheet.getRange('A2').values=[[title]];sheet.getRange('A2').format.font={size:17,bold:true};
 sheet.getRange('A2:F2').format.rowHeight=31;
 sheet.getRange('A3').values=[[note]];sheet.getRange('A3:F3').format.rowHeight=25;
}
function table(sheet,range,matrix,name,height){
 sheet.getRange(range).values=matrix;const t=sheet.tables.add(range,true,name);
 t.showBandedRows=false;t.showFilterButton=true;
 const [first,last]=range.split(':');const row=Number(first.match(/\d+/)[0]);
 sheet.getRange(range).format={fill:'#FFFFFF',wrapText:true,rowHeight:height,verticalAlignment:'top'};
 sheet.getRange(`A${row}:F${row}`).format={fill:'#283F55',font:{color:'#FFFFFF',bold:true},rowHeight:30,verticalAlignment:'center',horizontalAlignment:'center'};
}
setup(main,'Uteki：只保留三个主 To-Do','2026-10-13。开发暂停，先明确模块和设计；旧公司案例与 Bug 已归类。',[170,280,320,305,280,220],22);
const mainRows=tables[0].slice(1).map(r=>[r[0],r[1],r[2],r[3],r[4],'']);
table(main,'A5:F8', [['主任务','业务目标','应交付什么','当前状态','建议顺序','讨论决定'],...mainRows],'MainTasks',98);
main.getRange('F6:F8').format.fill='#FFF1D6';
main.getRange('A10').values=[['分析 Agent 后置']];
main.getRange('B10').values=[['分析计划与补数反馈；精编/报告；业务图/收入图；关系与观察建议。']];
main.getRange('C10').values=[['Data 提供证据，Analysis 形成结论。真实消费闭环尚未验收。']];
main.getRange('A10:F10').format={wrapText:true,rowHeight:55,verticalAlignment:'top'};
main.getRange('A12').values=[['公司和旧问题放在哪里']];main.getRange('A12').format.font={bold:true};
table(main,'A13:F18',[
 ['原记录','归属','记录性质','已确认','仍未确认','当前处理'],
 ['台积电 T01','DA-01 获取','获取验收案例','冻结目录 31/31 件取得','实时目录完整性、首次公开日期','缺口保留'],
 ['台积电 T02','DA-02 解析','PDF 验收案例','文字块/页码/坐标有基础实现','章节/表格解析与完整材料验收','先设计'],
 ['谷歌两张图片','DA-02 + DA-03','图片解析及查询消费案例','指定图题最终 3/3','新图与更广泛化','旧通过封存'],
 ['微软/谷歌两年收入','DA-03 查询','自主交付验收案例','原题三次首审和最终通过','跨题稳定性、记录 ID 误用','按模块验证'],
 ['旧包缺失 R22-H','DA-03 评测','历史证据缺失','缺失项已登记','12 次旧运行不能重审','后置，不阻断设计'],
 ],'CaseOwnership',66);
main.getRange('A20').values=[['本轮快速核验']];
main.getRange('B20').values=[['49 项离线检查通过。']];
main.getRange('C20').values=[['只确认相应工程机制；未调用模型或重新验收全链。']];
main.getRange('A20:F20').format={wrapText:true,rowHeight:45};
main.getRange('A22').values=[['下一步：只讨论获取模块的公司输入、来源范围和产物。']];
main.tabColor='#283F55';

const data=[];
for(let i=1;i<=3;i++)for(const r of tables[i].slice(1))data.push([`DA-0${i}`,r[0],r[1],r[2],r[3],i===1&&r[0]==='更新与监控'?'后续范围':i===2&&r[0]==='导航索引与搜索'?'优先设计':'模块内梳理']);
for(const r of tables[4].slice(1))data.push(['分析 Agent 后置',r[0],r[1],r[2],'先明确消费 Data 的边界；不进入当前主待办。','后置']);
setup(detail,'模块、问题和验收归属','按归属筛选。模块是三个主任务的组成部分，不再生成独立执行队列。',[170,180,350,360,335,135],data.length+6);
table(detail,`A5:F${5+data.length}`,[['归属','模块','职责 / 已有功能','现状与问题','交付 / 验收','建议安排'],...data],'ModuleMap',91);
detail.getRange(`F6:F${5+data.length}`).dataValidation={rule:{type:'list',values:['优先设计','模块内梳理','随后验证','后续范围','后置']}};
detail.freezePanes.freezeRows(5);detail.freezePanes.freezeColumns(1);
wb.recalculate();
await fs.writeFile(`${out}/three-streams-inspect.json`,(await wb.inspect({kind:'region',sheetId:'三个主待办',range:'A5:F8',maxChars:3000,tableMaxRows:4,tableMaxCols:6})).ndjson);
for(const [sheetName,range,name] of [['三个主待办','A1:F10','three-main'],['模块与问题','A1:F13','three-modules'],['模块与问题','A18:F23','analysis-modules']]){
 const img=await wb.render({sheetName,range,scale:1,format:'png'});
 await fs.writeFile(`${out}/${name}.png`,new Uint8Array(await img.arrayBuffer()));
}
const file=await SpreadsheetFile.exportXlsx(wb);await file.save(`${out}/Uteki-三个主待办-2026-10-13.xlsx`);
console.log(JSON.stringify({mainTasks:mainRows.length,modules:data.length,output:`${out}/Uteki-三个主待办-2026-10-13.xlsx`}));
