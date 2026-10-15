/** Current v1 inventory; explicit distinction between reusable API and fixed task template. */
const bi=(zh,en)=>({zh,en});
export const COMPONENT_CATALOG=[
 {id:'structure',title:bi('结构与导航','Structure and navigation'),file:'editorial-primitives.mjs',exports:['Header','Sidebar','DataTable','PDFPreview'],kind:'api',css:['style.css'],demo:'./comparison.html'},
 {id:'content',title:bi('卡片与列表','Cards and lists'),file:'compound-components.mjs',exports:['Card','ItemList'],kind:'api',css:['compound-components.css'],demo:'./workspace.html?view=agent'},
 {id:'utilities',title:bi('提示、展开、分页与进度','Hints, disclosure, pagination and progress'),file:'utility-components.mjs',exports:['Tooltip','mountTooltips','Accordion','Breadcrumb','Pagination','Loading'],kind:'api',css:['utility-components.css'],demo:'./#actions'},
 {id:'controls',title:bi('字段、菜单与反馈','Fields, menus and feedback'),file:'workspace-controls.mjs',exports:['TextField','ActionMenu','Notice','InlineAlert'],kind:'api',css:['workspace.css'],demo:'./workspace.html'},
 {id:'comparison',title:bi('选中、详情与数值','Selection, detail and values'),file:'workspace-components.mjs',exports:['ViewTabs','RecordDetail','SignedBars'],kind:'api',css:['workspace.css'],demo:'./workspace.html?view=library'},
 {id:'story',title:bi('文章层级与图解','Story hierarchy and explanation'),file:'story-components.mjs',exports:['StoryLead','PullQuote','mountExplainer'],kind:'api',css:['story-components.css'],demo:'./workspace.html?view=reading&record=north'},
 {id:'media',title:bi('视频与展开媒体','Video and expandable media'),file:'reading-media.mjs',exports:['createArticleVideo','createKineticFigure','mountMediaWindow'],kind:'api',css:['reading-media.css'],demo:'./workspace.html?view=reading&record=north#read-media'},
 {id:'inspection',title:bi('图片局部检查','Image inspection'),file:'image-inspector.mjs',exports:['mountImageInspector'],kind:'api',css:['image-inspector.css'],demo:'./workspace.html?view=reading&record=north#read-inspect'},
 {id:'linked',title:bi('图表同步对照','Linked chart comparison'),file:'linked-charts.mjs',exports:['mountLinkedCharts'],kind:'api',css:['linked-charts.css'],demo:'./workspace.html?view=reading&record=north#read-inspect'},
 {id:'source',title:bi('引用与集中来源','Citations and sources'),file:'source-panel.mjs',exports:['mountSourcePanel','filterSourceExcerpts'],kind:'api',css:['source-panel.css','citation-components.css'],demo:'./research-report.html?report=editorial-reading'},
 {id:'report',title:bi('报告内容与阅读','Report content and reading'),file:'report-reader.mjs',exports:['mountReportReader','normalizeReportState','reportFigureGeometry'],kind:'api',css:['report-reader.css','source-panel.css','citation-components.css'],demo:'./report-library.html'},
 {id:'scope',title:bi('范围筛选与快速查找','Scope and quick find'),file:'scope-controls.mjs',exports:['createScopeControls'],kind:'api',css:['scope-controls.css'],demo:'./workspace.html'},
 {id:'agent',title:bi('Agent 任务模板','Agent task template'),file:'agent-task-page.mjs',exports:['mountAgentTaskPage','reduceAgentTask'],kind:'template',css:['agent-task-page.css','compound-components.css'],demo:'./workspace.html?view=agent'},
 {id:'finance',title:bi('财务运营模板','Finance operations template'),file:'finance-workbench.mjs',exports:['mountFinanceWorkbench','summarizeInvoices'],kind:'template',css:['finance-workbench.css'],demo:'./workspace.html?view=finance'},
 {id:'portfolio',title:bi('投资研究模板','Portfolio research template'),file:'portfolio-workbench.mjs',exports:['mountPortfolioWorkbench','summarizePortfolio'],kind:'template',css:['portfolio-workbench.css'],demo:'./workspace.html?view=portfolio'},
 {id:'workflow',title:bi('工作项看板模板','Workflow template'),file:'workflow-board.mjs',exports:['mountWorkflowBoard','moveTask'],kind:'template',css:['workflow-board.css'],demo:'./workspace.html?view=workflow'},
 {id:'review',title:bi('证据复核模板','Evidence review template'),file:'exception-review-workbench.mjs',exports:['mountExceptionReviewWorkbench','computeEvidenceBridge'],kind:'template',css:['exception-review-workbench.css'],demo:'./workspace.html?view=review'},
 {id:'archive',title:bi('素材档案模板','Resource archive template'),file:'resource-archive.mjs',exports:['mountResourceArchive'],kind:'template',css:['resource-archive.css'],demo:'./workspace.html?view=resources'}
];
export const PAGE_CATALOG=[
 {id:'desk',title:bi('研究任务工作台 · Skill 应用','Research task desk · Skill application'),href:'./research-desk.html',description:bi('筛选、详情、笔记、手动确认与来源回程；六色卡独立配置。','Filtering, details, notes, manual decisions and source return; six independent palettes.')},
 {id:'reports',title:bi('报告列表与完整阅读','Report library and reader'),href:'./report-library.html',description:bi('摘要、章节、图表／数据与来源往返；两份独立内容样稿。','Briefs, chapters, chart/data and evidence return across two independent specimens.')},
 {id:'dashboard',title:bi('研究概览','Research overview'),href:'./workspace.html',description:bi('主次布局、指标、筛选与数值对照。','Hierarchy, metrics, shared filters and value comparison.')},
 {id:'agent',title:bi('Agent 任务','Agent task'),href:'./workspace.html?view=agent',description:bi('输入、附件元信息、过程、待确认与产物；固定模拟。','Input, attachment metadata, progress, confirmation and outputs; fixed demo.')},
 {id:'finance',title:bi('财务运营与投资研究','Finance and portfolio research'),href:'./workspace.html?view=finance',description:bi('应收单据与计算口径；另有组合贡献与估值联动。','Invoices and definitions; separate portfolio contribution and valuation views.')},
 {id:'settings',title:bi('设置与偏好','Settings and preferences'),href:'./editorial-settings.html',description:bi('通用优先、阅读偏好、草稿与保存、高级项渐进展开。','General first, reading preferences, draft/save and advanced disclosure.')},
 {id:'pdf',title:bi('中英 PDF 出版模板','Bilingual PDF template'),href:'./pdf-bilingual.html',description:bi('两页明确版式、字体、表格、图注与页脚边界。','An explicit two-page layout with fonts, tables, captions and footers.')}
];
export function filterComponentCatalog(query='',kind='all'){
 if(typeof query!=='string'||!['all','api','template'].includes(kind))throw new TypeError('Supported component filters required');
 const q=query.trim().toLowerCase();return COMPONENT_CATALOG.filter(c=>(kind==='all'||kind===c.kind)&&(!q||[c.title.zh,c.title.en,c.file,...c.exports].some(v=>v.toLowerCase().includes(q))));
}
