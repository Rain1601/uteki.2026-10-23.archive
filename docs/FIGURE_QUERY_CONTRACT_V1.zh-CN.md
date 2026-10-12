# 03-M3 图片按需消费契约 v1

2026-10-12 冻结。当前目标：给定一个明确的冻结 dataset、公司/来源/截止日期/candidate scope 和图片补充包 manifest SHA，主 Query Agent 自主发现、按需读取并显式选择图片；最终原件重组和双审只消费选择过且实际完整读取的图片。没有补充包的旧文字/数字链保持旧协议。

例子：用户问某份报告中的股价比较图。系统通过 scoped 来源目录发现图片导航，自主读取相关图例、期间、印刷文字与相邻原文假设，将必要图片和原文分别选择。最终展示原图身份、精确文字及位置、原文假设出处和无法从印刷内容获得的点值缺口。范围只由调用者和来源元数据确定，不向运行 Agent 提供参考答案、必需图 ID 或验收批评。

## 工程协议

- 调用者显式 `figure_bundle_ref={path,manifest_sha256}`，只允许以 analysis_evidence 用途绑定一个已冻结 dataset。没有补充包不自动搜索目录、旧实验或模型生成替代材料。准备/重新物化时不隐式继承另一 dataset 的图片。
- `list_figures()` 只返回当前 company/source/cutoff/candidate 权限内的导航和缺口，不能把目录、alt 或 metadata 计为已读。
- `read_figure` 使用 `figure_read={source_snapshot_id,figure_id}`、已有 requirement IDs。返回 `figure-evidence-v1` 类型及已绑定原图/原文/转录/hash/定位/相邻原文。每次读取重验固定 manifest 及材料 hash。
- 图像证据与 HTML 正文证据分开。实际发送的完整图片材料通过独立 `delivered_figures` 记录，不满足旧 `read_node`、数值记录要求或 `delivered_body`。被截断的预览不算完整读取；续读仍受总预算和步数限制。
- `select_figures` 使用非空 `figure_delivery.evidence_ids`、requirement IDs 和理由，仅适用于同来源 `source_evidence`；验证角色已完整读取、scope、来源和补充包一致，错误操作不改此前选择。不根据导航或探索自动选择图片。
- 显式补充包启用 `selected-originals-v5`；最终 `selected_figures` 与旧正文选择分别封存。无补充包保持 v4 输出，无新的默认图片字段。旧封存文件不改写。
- 最终 packet 根据选择重新验证 Reader 与 dataset，保存独立 `source_figures`。`figure_text` / `figure_field` 引用必须绑定精确 figure/text identity、字段和值；不得把转录改写成原始 HTML 引文，坐标和图例不得被当作精确曲线点值。
- 新图像 packet 使用明确新版本，schema 按 packet 类型选择；来源审核检查每张已交付图的真实性、支持与聚焦，独立问题审核只见最终所选原件。公司、期间、原问题身份和原精确引用约束保持，v5 显式要求 delivered-sources-v2 与 independent-question-v2 两审策略，两审通过才具备下游资格。
- 恢复/修订继承同一图片绑定，数据集、补充包、工具和依赖纳入冻结指纹。私密路径、原图、运行及费用保留本机，不写入公开参考答案。

## 验收先后与边界

离线工程验收：独立合成两公司/两来源数据，检查无包、错来源/公司、cutoff、candidate 禁用、缩窄和 hash 篡改；实际 Agent fixture 的目录→读取→显式选择→最终重组→双审精确引用链；预览未完整送出、不经读取选择、探索自动交付、错误引用、同角色/跨角色及旧契约边界。fixture 是程序行为验证，不是模型质量或真实业务验收。

真实原例：沿用 03-M2 两张原图及正文假设和原严格材料标准，由 Codex 独立精读原件后冻结具体问题及逐项必需/可选/冗余，冻结重复次数、运行配置和预算，再让 Agent 自主执行。原图/转录/字段/上下文/出处、遗漏/多余、最终交付和首审/恢复分别评价。不能从工程测试或旧另一机器报告推定本机真实通过。

本机前置缺口：原 `output/figure-materials-20261012`、对应 v5 datasets、原 E1 费用与图片 budget baseline 未迁移。不会重建空账本冒充继承。当前图片生产入口固定使用被用户禁用的 AiHubMix；本轮消费接入不执行该入口，不发起再次 vision 转录。原包恢复前真实运行未执行。
