# v0.1.8 锚点修复与版本门禁：最终 v2 核验

状态：本地程序实现与结构核验完成；无网络或模型请求。没有完整金融语义或正文漏项验收。

## 行为与版本

v1 的 anchor-fix-amd/tsmc 包与 verify_anchor_fix.py、报告均保持原字节。v1 是补版本门禁之前的实现快照；其 manifest 含当时的实现指纹，因此完整字节重建需要当时的代码与环境。v2 是当前实现的可重建版本，新增包为 anchor-fix-v2-amd/tsmc。

低层 parse_sec_source 与旧 build_index_artifacts 入口现在拒绝未知版本、空串和空白；省略旧入口参数仍保持旧默认。白名单保留实际出现过的 0.1.1、0.1.2-quarterly、0.1.3、0.1.3-quarterly、0.1.4-quarterly、0.1.5、0.1.6、0.1.7、0.1.8；新增版本须显式登记行为。

仅 v0.1.8 使用自身/最近包含块优先，块外才找后继块；hidden/script/style/noscript 锚点保留但 target=null；重复 id/name 保留首次 DOM 出现并写 duplicate_source_anchor 诊断。v0.1.7 及更早分支保留原算法。

生产 HTML package 默认改为 v0.1.8；SourceIdentity/Manifest 同时接受 v0.1.7/v0.1.8，清单使用显式选择版本。未知版本仍由 package 契约拒绝。company_materialization 既有 HTML_PARSER 导入直接使用新默认，无需改其源码。

## 两份真实冻结 HTML 的程序核验

| 材料 | 锚点数 旧→新 | 改变的锚点 | 不变的块数 | 不变的单元格数 |
|---|---:|---:|---:|---:|
| AMD | 1950 → 1950 | 1778 | 1184 | 7429 |
| TSMC | 5536 → 5536 | 5055 | 1929 | 67764 |

两份 v1 的 v0.1.8 包、v0.1.7 旧包和原件哈希均未变；v1/v2 除 manifest.json 中实现指纹及包身份外，其他 14 个文件均逐字节相同。重新调用 v0.1.7 得到的 anchors/blocks 与旧冻结字节一致；v0.1.8 的 blocks.jsonl、assets.json 与旧包逐字节一致。正文目录标题与块范围保持一致。每份新包 15 个文件通过结构校验，并在临时目录再次构建后逐字节一致。

逐锚点旧目标、新目标、原 DOM 位置及变化原因见 [anchor-fix-v2-verification.json](anchor-fix-v2-verification.json)。统计分母为全部原始锚点；隐藏源锚点变成 null 属于明确纠错，不能计作丢失正文。

AMD f-313 现在指向 block-000686-a6e8806b，其 1,667 单元格仍为零基 r25/c3；原先错误的 block-000688-a9360e02 不再作为该源锚点目标。

## 保留的缺口

AMD 105 个、TSMC 163 个 Table of Contents 段落仍未标布局角色。TSMC 的 Item 节点仍为 0；这些问题不在此次锚点补丁内。图片/OCR、PDF、单位/脚注语义关系仍不由本检查证明。

## 复跑

```sh
.venv/bin/python experiments/agent_design/2026-10-07-data-foundation-v1/verify_anchor_fix_v2.py --check
.venv/bin/python -m unittest tests.unit.test_sec_parser_versions tests.unit.test_sec_anchor_ownership tests.unit.test_parsed_package tests.unit.test_sec_index_tables tests.unit.test_sec_visible_outline tests.unit.test_sec_document_index tests.unit.test_nested_source_blocks tests.unit.test_company_materialization
```

首次使用 --build 创建新包及报告，拒绝覆盖。--check 只校验已有产物并在临时目录重建；对比失败会终止。

下一步：分别处理重复导航与表格形式的法律标题，再用独立验收样本检查正文过滤、章节边界与漏项；本次结果不自动完成 TODO 04 的全部任务。
