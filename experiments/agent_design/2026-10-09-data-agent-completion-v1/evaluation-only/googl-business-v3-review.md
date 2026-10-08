# Google 业务 v3 独立验收

结论：**尚未通过独立内容验收**。系统运行 `googl-business-r2` 在第二次交付后通过模型复核，但最终材料仍缺 Google Services 的主要产品／平台构成。收入分类齐全不能证明业务构成齐全。

本审查仅在运行封存后读取原件与结果，不调用模型，不参与运行选材，也未修改冻结材料。具体缺失例子仅供离线验收，不得输入执行 Skill 或用作公司专用补丁。

## 绑定的实际结果

- 实际运行：[cycle](../runs/googl-business-r2/result.json)，状态 `reviewed_data_ready`。
- 最终交付：[attempt-02/review-packet.json](../runs/googl-business-r2/attempt-02/review-packet.json)。21 个原文块，5,101 个原文字符，21 个原文事实。
- 最终审阅：[review-01/result.json](../runs/googl-business-r2/attempt-02/review-01/result.json)，模型判定 complete、analysis_eligible=true。
- Packet SHA-256：`f108e3db4431815849718fb90fd97bfb023a352734966874de127800fc36a0ff`。
- Query manifest：`ed117c9a97119c156cbcdd6805d192383174624a32070d94131e047a80514566`。
- Review manifest：`003ba785d6a023b8aaa9ca422b1a4d14f8ec9422bbde142433a38279a20c30a9`。
- 冻结原件：[Alphabet FY2025 10-K](../datasets/googl/raw/googl-2025-10k.html)，SHA-256：`c2f6301004f35411a20611c14ff01d80a85c0bcbab6053c80d8cc7f6fc747161`。
- [机器可读核验记录](googl-business-v3-review.json) 保留精确 DOM 路径、原文、引用及结构元数据。

## 问题要求与独立判定

原题要求：“Alphabet 的 FY2025 10-K 披露了哪些报告分部，各自包括哪些主要业务？请提供足以回答的原始段落和完整的相关列举，保留必要限定。”

| 内容 | 判定 | 依据和边界 |
| --- | --- | --- |
| 报告结构 | 足够 | 原文 64 明确 Google Services、Google Cloud、Other Bets，并保留 Alphabet-level AI 研发限定。无需再次强制提供分部附注。 |
| Services 主营业务 | **缺失** | 最终正文只给广告、订阅、平台销售、设备等收入来源。原件明确列为核心产品的 Android、Chrome、Maps 等未交付。它们不是评测额外要求的外围细节。 |
| Cloud 主营业务 | 足够 | GCP／Workspace 引言和基础设施、开发平台、安全、数据分析、Agents 的完整列表及两个子项均在。 |
| Other Bets | 足够 | 非 Google 集合范围、X／Waymo 阶段差别、独立公司及早期业务限定、自主交通与互联网业务均有原文。无需强制增加单独不重大分部的会计说明。 |
| 精确引用 | 通过 | 21 段正文逐字匹配冻结块与原始 HTML DOM；21 条引用及其字符范围均匹配同源原文。所有数据集文件、最终 packet/query/review 绑定哈希一致。 |
| 最小性 | 基本合理，但不能弥补缺料 | 最终删去四段一般叙述；短标题与相关列表上下文合理。广告类型解释稍详细，未因此拒绝。缩包不能删掉唯一的业务信息却不补足更直接的原文。 |

离线缺口证据：原件 **85** 明确以 “Google Services' core products and platforms include …” 引出业务清单；较短的分部附注 **1233** 也同时列业务与收入来源。两处都是可选证明路径，不要求必须命中某个块、不要求两处都交付。最终包既没有这些原文，也没有等价的完整业务内容。Google Services 收入来自 Google Play 并不能据此推导 Android、Chrome、Maps 等主营平台。

## 两次运行的差异

第一次提供 25 块。复核认为 88–90 的产品叙述 irrelevant、92 的广告技术叙述 redundant，并要求移除。第二次按要求删成 21 块后通过。

移除冗长叙述本身可以合理；问题在于模型没有继续检查原题中的“各主要业务”，也没有寻找更直接的业务清单。首轮的产品叙述并不完整，删去后缺口更明确。两轮 reviewer 都把收入分类列表的完整性当成 Services 业务内容的完整性，形成了错误放行。

## 这轮已解决的结构问题

Cloud 组原文 103 是页码，104 是重复页眉。v3 依据冻结索引的 layout_role 排除二者，所有真实列表项、Agents 父子关系和引言均保留。`all_group_blocks_delivered=false` 与 `all_required_blocks_delivered=true` 可以同时成立，不能据此要求补页码。该结构处理正确。

但 reading group 只能证明**当前列表**的结构闭合，不证明其他业务主题已检索齐全。当前数据也明确标记 semantic_completeness=not_evaluated。

## 通用修复建议

将“业务／产品构成”和“收入来源”作为不同的任务语义。任务需要两者时分别核对；只要求前者时不能用后者替代。复核应回到用户原题检查覆盖，不能只检验执行模型自行写出的较窄 requirement。补充材料由系统 Agent 自行定位、阅读、选择，Codex 不提供预选块。

下一步：通用修复后由系统 Agent 再跑同一问题，另留新版本；保留这轮模型通过、独立未通过的记录。
