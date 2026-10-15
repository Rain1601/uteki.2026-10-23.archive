import {AGENT_CITATION_SOURCES} from './citation-sources.mjs';
import {validateCitationSources} from './citation-components.mjs';

const text=(v,name)=>{if(typeof v!=='string'||!v.trim())throw new TypeError(`${name} requires explicit nonempty text`);return v;};
const identity=(v,name)=>{text(v,name);if(!/^[A-Za-z][A-Za-z0-9_-]*$/.test(v))throw new TypeError(`${name} requires a safe identity`);return v;};
const bilingual=(v,name)=>{if(!v||typeof v!=='object'||Array.isArray(v))throw new TypeError(`${name} requires zh/en text`);text(v.zh,name);text(v.en,name);return {...v};};
const unique=(items,name)=>{const ids=new Set();items.forEach(x=>{identity(x.id,name);if(ids.has(x.id))throw new TypeError(`Duplicate ${name}`);ids.add(x.id);});return ids;};
export function validateReportFigure(input){
 if(!input||input.kind!=='authored-specimen'||!Array.isArray(input.rows)||!input.rows.length)throw new TypeError('Explicit figure identity, scope, unit and specimen rows required');
 for(const name of ['id','unit','scope'])text(input[name],'Explicit '+name);identity(input.id,'figure id');
 const ids=new Set();const rows=input.rows.map(row=>{if(!row||typeof row.id!=='string'||!row.id||ids.has(row.id)||(row.value!==null&&(typeof row.value!=='number'||!Number.isFinite(row.value))))throw new TypeError('Unique row identity and finite number or null required');ids.add(row.id);return {id:row.id,value:row.value};});
 return {...input,rows};
}
/** Explicit authored report contract. No source inference, retrieval or HTML content. */
export function validateReportContent(input){
 if(!input||input.kind!=='authored-specimen')throw new TypeError('Explicit authored report required');identity(input.id,'report id');
 const localized=Object.fromEntries(['title','kicker','deck','scope'].map(key=>[key,bilingual(input[key],key)]));text(input.date,'date');if(!/^\d{4}-\d{2}-\d{2}$/.test(input.date)||Number.isNaN(Date.parse(input.date+'T00:00:00Z'))||new Date(input.date+'T00:00:00Z').toISOString().slice(0,10)!==input.date)throw new TypeError('Valid ISO report date required');
 if(!Array.isArray(input.sections)||!input.sections.length)throw new TypeError('Report sections required');
 const sectionIds=unique(input.sections,'section id');const sources=validateCitationSources(input.sources);const sourceIds=new Set(sources.map(s=>s.id));
 if(!Array.isArray(input.figures)||!Array.isArray(input.summaries)||!input.summaries.length)throw new TypeError('Explicit figures and summary required');
 const figures=input.figures.map(figure=>{const copy=validateReportFigure(figure);return {...copy,title:bilingual(copy.title,'figure title'),caption:bilingual(copy.caption,'figure caption'),...(copy.unitLabel?{unitLabel:bilingual(copy.unitLabel,'unit label')}:{})};});const figureIds=unique(figures,'figure id');
 const referenced=new Set(),detailsIds=new Set();const domIds=new Set(['rr-brief-title',...sectionIds]);for(const figure of figures)for(const id of [figure.id+'-title',figure.id+'-desc']){if(domIds.has(id))throw new TypeError('Duplicate report DOM identity');domIds.add(id);}
 function checkSources(ids){if(ids===undefined)return; if(!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length)throw new TypeError('Explicit unique sourceIds required');ids.forEach(id=>{if(!sourceIds.has(id))throw new TypeError(`Unknown source: ${id}`);});}
 const sections=input.sections.map(section=>{bilingual(section.title,'section title');bilingual(section.label,'section label');if(!Array.isArray(section.blocks)||!section.blocks.length)throw new TypeError('Section blocks required');
 const blocks=section.blocks.map(block=>{if(!block||!['paragraph','quote','figure','details','boundary','sources'].includes(block.type))throw new TypeError('Unknown report block');checkSources(block.sourceIds);
 if(block.type==='figure'){if(!figureIds.has(block.figureId))throw new TypeError('Unknown figure');if(referenced.has(block.figureId))throw new TypeError('Duplicate figure placement');referenced.add(block.figureId);}
 else if(block.type==='sources'){if(!block.sourceIds)throw new TypeError('Explicit sourceIds required');}
 else {bilingual(block.text,'block text');if(['details','boundary'].includes(block.type))bilingual(block.title,'block title');if(block.type==='details'){identity(block.id,'details id');if(detailsIds.has(block.id))throw new TypeError('Duplicate details id');detailsIds.add(block.id);}}
 return {...block,...(block.text?{text:bilingual(block.text,'block text')}:{ }),...(block.title?{title:bilingual(block.title,'block title')}:{ }),sourceIds:block.sourceIds?[...block.sourceIds]:undefined};});return {...section,title:bilingual(section.title,'section title'),label:bilingual(section.label,'section label'),blocks};});
 if(referenced.size!==figureIds.size)throw new TypeError('Unplaced report figure');
 const summaries=input.summaries.map(item=>{if(!['proposal','specimen','contract'].includes(item.kind)||!sectionIds.has(item.sectionId))throw new TypeError('Valid summary kind and chapter required');bilingual(item.text,'summary text');return {...item,text:{...item.text}};});
 return {...input,...localized,sources,figures,sections,summaries};
}
const first={
  "id": "editorial-reading",
  "kind": "authored-specimen",
  "title": {
    "zh": "让研究变得容易阅读",
    "en": "Make research easier to read"
  },
  "kicker": {
    "zh": "设计研究 · 原创样稿 / 01",
    "en": "DESIGN RESEARCH · AUTHORED SPECIMEN / 01"
  },
  "deck": {
    "zh": "从一条结论开始，沿着清楚的章节，走到可以核对的依据。",
    "en": "Begin with a finding. Follow a clear chapter. Reach evidence you can check."
  },
  "date": "2026-10-10",
  "scope": {
    "zh": "范围：阅读体验与本地排版契约",
    "en": "Scope: reading experience and local layout contracts"
  },
  "figures": [
    {
      "id": "reading-specimen",
      "kind": "authored-specimen",
      "unit": "specimen-count",
      "unitLabel": {"zh":"样稿计数","en":"specimen count"},
      "scope": "A–E",
      "title": {
        "zh": "五条样稿记录的数量分布",
        "en": "Counts across five specimen records"
      },
      "caption": {
        "zh": "数字为原创排版样稿，不是研究结果。C 未记录；D 明确为零。",
        "en": "Authored layout values, not research results. C is not recorded; D is explicitly zero."
      },
      "rows": [
        {
          "id": "A",
          "value": 12
        },
        {
          "id": "B",
          "value": 18
        },
        {
          "id": "C",
          "value": null
        },
        {
          "id": "D",
          "value": 0
        },
        {
          "id": "E",
          "value": 15
        }
      ]
    }
  ],
  "sections": [
    {
      "id": "report-orientation",
      "title": {
        "zh": "先给阅读一个方向",
        "en": "Give reading a direction"
      },
      "label": {
        "zh": "阅读结构",
        "en": "READING STRUCTURE"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "阅读报告有两种速度：先判断是否相关，再认真理解依据。首屏给出范围和简短结论，正文保留完整推理；点击摘要可以直接进入相关章节。",
            "en": "A report is read at two speeds: first to judge relevance, then to understand the evidence. The opening establishes scope and concise findings; the body preserves the reasoning. Each summary links to its chapter."
          }
        },
        {
          "type": "paragraph",
          "text": {
            "zh": "这是一份原创设计样稿。正文说明我们的阅读设计建议，引用只指向项目已经存在的排版契约，不代表外部研究结论。",
            "en": "This is an authored design specimen. The prose presents our reading design proposals. Citations point only to existing project layout contracts, not external research findings."
          }
        },
        {
          "type": "quote",
          "text": {
            "zh": "让文字建立层级，\n让操作出现在需要的位置。",
            "en": "Let typography establish hierarchy.\nLet controls appear where they are needed."
          }
        },
        {
          "type": "paragraph",
          "text": {
            "zh": "本地工作台契约把段落与操作、数字区分为不同字体角色。这是复用的依据；本报告更窄的正文版心则是当前阅读页的设计建议。",
            "en": "The local workspace contract distinguishes prose from controls and numbers through type roles. That is our reuse basis; this report’s narrower text measure is a design proposal for the reading page."
          },
          "sourceIds": [
            "rule-hierarchy"
          ]
        }
      ]
    },
    {
      "id": "report-numbers",
      "title": {
        "zh": "让图形与数字互相解释",
        "en": "Let charts and numbers explain each other"
      },
      "label": {
        "zh": "图表与数字",
        "en": "CHARTS AND NUMBERS"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "图形适合观察差异，表格适合查清数值。二者保持相同的记录顺序、单位与范围。切换只更换表达方式，不改写数据。",
            "en": "Charts reveal differences; tables make values explicit. Both preserve record order, units and scope. Switching changes the representation, not the data."
          }
        },
        {
          "type": "figure",
          "figureId": "reading-specimen"
        },
        {
          "type": "details",
          "id": "definitions-reading",
          "title": {
            "zh": "口径与缺失值说明",
            "en": "Definitions and missing values"
          },
          "text": {
            "zh": "A–E 是稳定记录标识，没有筛选或合计。未记录不是零，不能从视觉空白推断数值。本地 PDF 表格契约要求 0、null、负数分别呈现；这里借用语义规则，不照搬 PDF 的页面尺寸。",
            "en": "A–E are stable record identifiers, with no filters or totals. Missing is not zero; an empty visual does not imply a value. The local PDF table contract requires distinct presentation for zero, null and negative numbers. We reuse that semantic rule, not PDF page dimensions."
          },
          "sourceIds": [
            "rule-table"
          ]
        }
      ]
    },
    {
      "id": "report-boundaries",
      "title": {
        "zh": "核对之后，回到正文",
        "en": "Verify, then return to the story"
      },
      "label": {
        "zh": "来源与边界",
        "en": "SOURCES AND BOUNDARIES"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "引用是一次短暂的核对。来源面板呈现原文摘录、出处和定位信息；关闭后回到打开时的滚动位置与引用按钮。你可以继续当前句子，不必重新寻找段落。",
            "en": "A citation is a brief verification detour. The source panel shows the original excerpt, provenance and locator. Closing it restores the scroll position and citation focus so you can continue the same sentence."
          }
        },
        {
          "type": "paragraph",
          "text": {
            "zh": "网页图注紧邻图形；PDF 则另有页脚与安全区域契约。两种媒介保留相同的来源身份，但布局约束需要分别处理。",
            "en": "Web captions remain close to figures; PDFs have a separate footer and safe-area contract. Both media retain source identity, while their layout constraints are handled separately."
          },
          "sourceIds": [
            "rule-footer"
          ]
        },
        {
          "type": "boundary",
          "title": {
            "zh": "仍需验证",
            "en": "Still to verify"
          },
          "text": {
            "zh": "这份样稿验证阅读结构和组件衔接。真实报告接入、长文 PDF 分页和跨报告对比尚未实施；不能将样稿数字或设计建议当作实证结论。",
            "en": "This specimen demonstrates reading structure and component integration. Real-report ingestion, long PDF pagination and cross-report comparison remain unimplemented. Specimen values and design proposals are not empirical findings."
          }
        },
        {
          "type": "sources",
          "sourceIds": [
            "rule-hierarchy",
            "rule-table",
            "rule-footer"
          ]
        }
      ]
    }
  ],
  "summaries": [
    {
      "kind": "proposal",
      "sectionId": "report-orientation",
      "text": {
        "zh": "摘要负责建立方向，章节负责展开理由。",
        "en": "The brief establishes direction; chapters develop the reasoning."
      }
    },
    {
      "kind": "specimen",
      "sectionId": "report-numbers",
      "text": {
        "zh": "图表与表格共享同一组数字，缺失值保留原意。",
        "en": "Charts and tables share the same values, including missing entries."
      }
    },
    {
      "kind": "contract",
      "sectionId": "report-boundaries",
      "text": {
        "zh": "正文、结构与数据分别使用合适的字体角色。",
        "en": "Prose, structure and data use distinct typographic roles."
      }
    }
  ]
};
export const DESIGN_READING_REPORT=validateReportContent({...first,sources:AGENT_CITATION_SOURCES});
const bi=(zh,en)=>({zh,en});
export const READING_CONTINUITY_REPORT=validateReportContent({
 id:'reading-continuity',kind:'authored-specimen',date:'2026-10-10',
 kicker:bi('交互研究 · 原创样稿 / 02','INTERACTION RESEARCH · AUTHORED SPECIMEN / 02'),title:bi('阅读可以从停下的地方继续','Continue where reading paused'),
 deck:bi('在报告、证据与列表之间往返，保留当前位置和表达方式。','Move between report, evidence and list while retaining position and representation.'),
 scope:bi('范围：阅读状态与多图样稿，不是用户实验','Scope: reading state and multiple specimen figures, not a user study'),
 summaries:[{kind:'proposal',sectionId:'continuity-position',text:bi('章节与段内位置一起记录，回程才有明确落点。','Keep chapter identity and within-chapter position for a precise return.')},{kind:'specimen',sectionId:'continuity-representation',text:bi('每张图独立保存表达方式，负值和缺失值保留原意。','Each figure retains its representation; negative and missing values keep their meaning.')}],
 sources:AGENT_CITATION_SOURCES,
 figures:[{id:'signed-reading',kind:'authored-specimen',unit:'specimen-change',unitLabel:bi('样稿变化','specimen change'),scope:'draft records A–D',title:bi('有正负变化的样稿','A signed specimen'),caption:bi('原创演示值，不是实测时间或效果。','Authored demonstration values, not measured time or performance.'),rows:[{id:'A',value:-8},{id:'B',value:0},{id:'C',value:null},{id:'D',value:12}]},
 {id:'second-reading',kind:'authored-specimen',unit:'specimen-count',unitLabel:bi('样稿计数','specimen count'),scope:'draft records X–Z',title:bi('另一张图保持自己的模式','A second figure keeps its own mode'),caption:bi('独立图表状态示例，没有实验结论。','An independent figure-state specimen, with no experimental findings.'),rows:[{id:'X',value:4},{id:'Y',value:7},{id:'Z',value:2}]}],
 sections:[{id:'continuity-position',title:bi('为阅读留下位置','Keep a place in reading'),label:bi('位置与返回','POSITION AND RETURN'),blocks:[{type:'paragraph',text:bi('报告保存章节标识、段内偏移和滚动坐标。回到同一内容时恢复原位置；内容版本变化时，章节仍是可以检查的定位依据。','The report records chapter identity, within-chapter offset and scroll coordinates. Returning to unchanged content restores position; after revisions the chapter remains an inspectable anchor.')},{type:'quote',text:bi('记住读者的上下文，\n让返回成为阅读的一部分。','Remember the reader’s context.\nMake returning part of reading.')},{type:'paragraph',text:bi('来源是核对入口。原文、出处与定位信息由调用方明确提供，组件不生成缺失依据。','Sources are verification entry points. Callers supply excerpts, provenance and locators explicitly; the component does not invent missing evidence.'),sourceIds:['rule-hierarchy']},{type:'details',id:'continuity-definitions',title:bi('状态保存的范围','What state is preserved'),text:bi('这里保存报告阅读状态。来源面板暂时打开的状态不作为阅读进度，外部列表筛选由列表负责。','This reader stores reading state. A temporarily open source panel is not reading progress; the surrounding list owns its filters.'),sourceIds:['rule-footer']}]},
 {id:'continuity-representation',title:bi('表达方式不改写数据','Representation preserves data'),label:bi('多图与口径','FIGURES AND DEFINITIONS'),blocks:[{type:'paragraph',text:bi('两张图使用不同记录数量与数值范围。负值从零线向下，零显示零，缺失显示未记录。表格直接使用同一记录数组。','The figures have different record counts and value ranges. Negative bars extend below zero; zero is shown as zero, and missing as unrecorded. Tables use the same record arrays.')},{type:'figure',figureId:'signed-reading'},{type:'figure',figureId:'second-reading'},{type:'paragraph',text:bi('本地表格契约提供数值语义规则。这里的数字只是排版样稿，不能用于评估真实阅读效果。','The local table contract supplies numeric presentation rules. These values are layout specimens and cannot evaluate actual reading effectiveness.'),sourceIds:['rule-table']},{type:'sources',sourceIds:['rule-hierarchy','rule-table','rule-footer']}]}]
});
export const EVIDENCE_JUDGMENT_REPORT=validateReportContent({...{
  "id": "evidence-to-judgment",
  "kind": "authored-specimen",
  "date": "2026-10-12",
  "title": {
    "zh": "研究结论如何站得住",
    "en": "What makes a research conclusion hold up"
  },
  "kicker": {
    "zh": "研究方法 · 原创样稿 / 03",
    "en": "RESEARCH METHODS · AUTHORED SPECIMEN / 03"
  },
  "deck": {
    "zh": "从一条明确的问题出发，把证据、分歧与下一步放在同一条阅读路径里。",
    "en": "Begin with a precise question. Read the evidence, competing interpretations and next step together."
  },
  "scope": {
    "zh": "范围：研究方法建议与排版示例，不含真实公司分析",
    "en": "Scope: research-method proposals and layout specimens, without company analysis"
  },
  "summaries": [
    {
      "kind": "proposal",
      "sectionId": "evidence-question",
      "text": {
        "zh": "先明确要解释的变化，再约定期间、对象与必要证据。",
        "en": "Define the change to explain, then fix the period, object and required evidence."
      }
    },
    {
      "kind": "specimen",
      "sectionId": "evidence-comparison",
      "text": {
        "zh": "比较保持相同口径：正负变化、零与未记录分别表达；两张图各自保留图表或数据模式。",
        "en": "Use a consistent scope: distinguish signed changes, zero and missing entries; each figure retains its own chart or data mode."
      }
    },
    {
      "kind": "proposal",
      "sectionId": "evidence-alternatives",
      "text": {
        "zh": "把支持判断的理由和可能推翻判断的条件一起写出来。",
        "en": "State both the supporting reasons and the conditions that could overturn the interpretation."
      }
    }
  ],
  "figures": [
    {
      "id": "evidence-change",
      "kind": "authored-specimen",
      "unit": "specimen-point",
      "unitLabel": {
        "zh": "示例点数",
        "en": "specimen points"
      },
      "scope": "synthetic records A–F",
      "title": {
        "zh": "变化的方向，比总量更值得先看",
        "en": "Read direction before totals"
      },
      "caption": {
        "zh": "原创示例：A–F 不是公司或实测样本，C 明确为零，E 未记录。",
        "en": "Authored examples: A–F are neither companies nor measured samples; C is zero and E is unrecorded."
      },
      "rows": [
        {
          "id": "A",
          "value": 16
        },
        {
          "id": "B",
          "value": -9
        },
        {
          "id": "C",
          "value": 0
        },
        {
          "id": "D",
          "value": 7
        },
        {
          "id": "E",
          "value": null
        },
        {
          "id": "F",
          "value": -3
        }
      ]
    },
    {
      "id": "evidence-material",
      "kind": "authored-specimen",
      "unit": "specimen-count",
      "unitLabel": {
        "zh": "示例条数",
        "en": "specimen count"
      },
      "scope": "synthetic records P–R",
      "title": {
        "zh": "另一组材料，保留自己的表达方式",
        "en": "A separate set keeps its own representation"
      },
      "caption": {
        "zh": "原创排版数字，不代表证据覆盖率或研究质量。",
        "en": "Authored layout values, not evidence coverage or research quality."
      },
      "rows": [
        {
          "id": "P",
          "value": 8
        },
        {
          "id": "Q",
          "value": 3
        },
        {
          "id": "R",
          "value": 5
        }
      ]
    }
  ],
  "sections": [
    {
      "id": "evidence-question",
      "title": {
        "zh": "先把问题问清楚",
        "en": "Start with a precise question"
      },
      "label": {
        "zh": "问题与范围",
        "en": "QUESTION AND SCOPE"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "“发生了什么”与“为什么发生”需要不同的材料。前者先确认期间和变化，后者需要比较解释。把问题写成一句可以核对的话，才能判断哪些资料是必要的。",
            "en": "“What happened” and “why it happened” require different evidence. Establish the period and change first, then compare explanations. A verifiable question makes the required material clear."
          }
        },
        {
          "type": "quote",
          "text": {
            "zh": "先确定要回答什么，\n再决定应该读什么。",
            "en": "Decide what to answer,\nthen decide what to read."
          }
        },
        {
          "type": "details",
          "id": "evidence-scope-note",
          "title": {
            "zh": "展开：一份研究任务的最小范围",
            "en": "Expand: the minimum scope for a research task"
          },
          "text": {
            "zh": "写清对象、观察期间、来源范围和预期输出。这里是研究方法建议，不表示本页已经检索、读取或分析外部资料。",
            "en": "State the subject, observation period, source scope and expected output. This is a method proposal; the page has not retrieved, read or analyzed external material."
          }
        }
      ]
    },
    {
      "id": "evidence-comparison",
      "title": {
        "zh": "让比较保留原来的含义",
        "en": "Keep the meaning of a comparison"
      },
      "label": {
        "zh": "比较与数据",
        "en": "COMPARISON AND DATA"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "一张图帮助观察方向，另一张图展示不同数量的记录。每张图都有独立的稳定身份；切换数据视图只改变表达，不改变输入的值、顺序和缺口。",
            "en": "One figure helps compare direction; another contains a different number of records. Each has a stable identity. Switching to data changes only the representation, preserving values, order and gaps."
          }
        },
        {
          "type": "figure",
          "figureId": "evidence-change"
        },
        {
          "type": "figure",
          "figureId": "evidence-material"
        },
        {
          "type": "paragraph",
          "text": {
            "zh": "数值呈现沿用项目现有的表格契约。引用供核对原文；它支持数值排版规则，不为本页的方法建议提供实证结论。",
            "en": "Numeric presentation follows the existing project table contract. The citation verifies that layout rule; it does not establish empirical findings for these method proposals."
          },
          "sourceIds": [
            "rule-table"
          ]
        }
      ]
    },
    {
      "id": "evidence-alternatives",
      "title": {
        "zh": "给判断留下被推翻的条件",
        "en": "Make room for disconfirming evidence"
      },
      "label": {
        "zh": "分歧与边界",
        "en": "ALTERNATIVES AND LIMITS"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "资料一致时，也要问是否存在共同遗漏。把可能的解释分别列清，再指出哪条新增证据可以区分它们。证据尚未充分时，保留“待确认”比给出整齐的结论更有用。",
            "en": "Agreement across sources may still hide a shared omission. Separate the candidate explanations and identify new evidence that would distinguish them. When evidence is incomplete, an explicit uncertainty is more useful than a neat conclusion."
          }
        },
        {
          "type": "boundary",
          "title": {
            "zh": "这份报告的边界",
            "en": "Limits of this report"
          },
          "text": {
            "zh": "正文为原创方法建议，图表为合成排版样稿。没有公司事实、外部检索或用户实验。引用只指向项目已有的设计原文，不把设计契约当作研究效果证据。",
            "en": "The prose contains authored method proposals and the figures contain synthetic layout data. There are no company facts, external retrievals or user experiments. Citations refer only to existing project design originals and are not evidence of research effectiveness."
          }
        }
      ]
    },
    {
      "id": "evidence-next",
      "title": {
        "zh": "核对，然后继续推进",
        "en": "Verify, then keep going"
      },
      "label": {
        "zh": "回程与下一步",
        "en": "RETURN AND NEXT STEP"
      },
      "blocks": [
        {
          "type": "paragraph",
          "text": {
            "zh": "读者应能从引用进入原文，核对之后回到刚才那一句。目录负责找章节，来源面板负责短暂核对；二者共同保持阅读的连续性。",
            "en": "Readers should reach an excerpt from a citation and return to the same sentence. The outline locates chapters; the source panel supports a brief verification detour. Both preserve reading continuity."
          }
        },
        {
          "type": "paragraph",
          "text": {
            "zh": "此页沿用已有字体角色与层级契约，长段落、控件和数值分别使用适合的表达。明暗配色独立于内容和布局。",
            "en": "This page reuses the existing typography and hierarchy contract. Prose, controls and numeric values retain distinct roles. Appearance remains independent of content and layout."
          },
          "sourceIds": [
            "rule-hierarchy"
          ]
        },
        {
          "type": "sources",
          "sourceIds": [
            "rule-table",
            "rule-hierarchy",
            "rule-footer"
          ]
        }
      ]
    }
  ]
},sources:AGENT_CITATION_SOURCES});
export const REPORT_SPECIMENS=Object.freeze([DESIGN_READING_REPORT,READING_CONTINUITY_REPORT,EVIDENCE_JUDGMENT_REPORT]);
export function getReportSpecimen(id){return REPORT_SPECIMENS.find(report=>report.id===id)??null;}
