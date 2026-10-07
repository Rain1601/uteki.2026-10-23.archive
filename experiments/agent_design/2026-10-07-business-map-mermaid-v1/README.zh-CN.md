# 财报业务图 · 第一轮可见产物

[打开四家公司图页](http://127.0.0.1:8769/docs/design/data-agent-acceptance/business-map-mermaid-v1/)。可以切换关系图与分层总览、点击节点查看业务描述和赚钱方式、展开原文片段，并下载 SVG 与 Mermaid 源码。

## 本轮范围与产物

| 公司 | 明确的财报范围 | 节点 / 关系 / 证据 | 主要口径 |
|---|---|---:|---|
| [台积电](tsmc/README.zh-CN.md) | FY2023 20-F；期末 2023-12-31 | 14 / 15 / 13 | 五个应用平台；共享技术服务多个平台。不能当作五个报告分部 |
| [谷歌 / Alphabet](alphabet/README.zh-CN.md) | FY2025 10-K；期末 2025-12-31 | 15 / 14 / 20 | Services、Cloud、Other Bets；收入分类与产品组合分别标记 |
| [微软](microsoft/README.zh-CN.md) | FY2025 10-K；期末 2025-06-30 | 14 / 13 / 26 | 三个报告分部，保留当期调整后的产品归属 |
| [英伟达](nvidia/README.zh-CN.md) | FY2025 10-K；期末 2025-01-26 | 16 / 24 / 20 | 两个报告分部与四个市场维度分开，跨市场支持关系保留 |

合计 59 个节点、66 条关系、79 条来源片段。不同报告期的案例用于检验表达与取证，不作同期间财务规模比较。第一轮没有添加收入金额、占比或以面积表示权重。

这些是 Codex 对明确材料的原文审阅候选，复用现有 BusinessMap 契约。`build_extraction.py`（微软、英伟达）只包装本轮已整理的数据，不是通用语义提取器。原文下载、局部阅读、候选加工与图形生成不能合并称为全报告解析已完成。生产 Agent 尚未自动消费本轮 Skill。

## 两种表达，同一份数据

- **关系图：** Mermaid 生成真实 SVG，展示归属及共享支持关系。领域 JSON 保留子→父语义；为了从左至右展开，显示对应逆关系，例如“包含”。产品面向市场的关系保持产品→市场，并使用虚线。关系表仍显示原始领域语义。
- **分层总览：** 同一节点按关系展开层次，卡片显示它来自哪个上级/支持关系。共享服务仍是同一个 ID，列出多个上级。含环关系不强制转成层级，也不删除边。
- **金字塔：** 先在 Skill 中明确有序层次的适用条件。当前案例没有量化权重，未用面积伪装收入或重要性，也未声称金字塔一定更好。

节点大小不表示财务权重。两种视图均可打开同一节点的信息和证据；完整关系可展开核对。视图只是候选表达，用户尚未进行本页视觉验收。

## 检查与审阅

程序检查现有域契约、节点/边引用、来源内容哈希、原件与派生文件身份、精确引文在来源及定位片段中存在、HTML 锚点、实际 SVG 节点/标签及 JavaScript 语法。另有独立合成公司测试，覆盖缺范围、跨文档证据、伪造引文、来源变更、Mermaid 标签转义和带环关系。生成回执在 [verification.json](../../../docs/design/data-agent-acceptance/business-map-mermaid-v1/verification.json)。

最终交付检查：59 个 SVG 节点与 66 条关系匹配；104 个本地链接、79 个片段锚点可定位；181 个 DOM ID 无重复；脚本语法通过。图页与 4 组 SVG/Mermaid 共 9 个本机地址均返回 HTTP 200。详见 [delivery-check.json](../../../docs/design/data-agent-acceptance/business-map-mermaid-v1/delivery-check.json)；检查程序为 [verify_delivery.py](verify_delivery.py)。

独立内容复核覆盖 Alphabet 的分类和赚钱方式、NVIDIA 的分部/市场/产品归属。NVIDIA 根据复核扩清 GeForce 节点标题以包含主机产品，并明确 Omniverse 的个人免费指平台范围，避免误读为 Enterprise 产品免费。没有依据此复核自动采纳数据。

独立代理使用 Skill 对一家合成公司做了前向试用：[输入与结果](skill-forward-check/README.zh-CN.md)。结果保留 6 个节点、6 条关系，包括同一共享组件的 2 条支持关系；没有为了金字塔删边，也没有把合并收入拆成虚构的独立金额。该试用由 Codex 执行，不是系统 Agent 已绑定的证明；原运行路径与 Skill hash 保留在冻结回执中，后续规则文字有补充。

Claude 请求已经真实执行。用户将同一会话累计上限调至 $2.00 后，第 10 轮携带历史、Skill 初稿和四份 Mermaid 提交。模型返回 `max_tokens`，达到单次 4,096 token 输出上限，可见正文为空，**没有取得顾问意见**。本次估算 $0.251636，累计 $1.637160，非供应商账单；没有自动重试。见 [请求状态](claude-review-status.json)，完整私密问答仍在[共享窗口](http://127.0.0.1:8770/)。这次请求未提供截图，亦不构成视觉审阅。图形生成没有调用模型，没有进行浏览器视觉/交互验收。

## 重建

在仓库根目录，明确传入四个候选，不读取默认公司或最近报告：

```sh
PYTHONPATH=src .venv/bin/python experiments/agent_design/2026-10-07-business-map-mermaid-v1/build_view.py \
  --maps experiments/agent_design/2026-10-07-business-map-mermaid-v1/tsmc/business_map.json \
    experiments/agent_design/2026-10-07-business-map-mermaid-v1/alphabet/business_map.json \
    experiments/agent_design/2026-10-07-business-map-mermaid-v1/microsoft/business_map.json \
    experiments/agent_design/2026-10-07-business-map-mermaid-v1/nvidia/business_map.json \
  --output docs/design/data-agent-acceptance/business-map-mermaid-v1
```

使用 Mermaid CLI 11.12.0、Mermaid 11.12.0，将输出 `assets/*.mmd` 分别渲染成同名 SVG，配置为 [mermaid-config.json](mermaid-config.json)。随后用相同生成命令加 `--with-svg` 生成含图的页面。渲染器按 [Mermaid CLI 官方用法](https://github.com/mermaid-js/mermaid-cli) 使用本地隔离浏览器；图页运行不依赖 CDN。字体和绘图环境会影响 SVG 排版，不承诺跨环境逐字节一致。

## 下一步

1. 根据读者反馈调整图的层级、密度和主图/辅图分工，保持事实和证据不变。
2. 用 [业务图 Skill](../../../skills/uteki-business-diagrams/SKILL.md) 整理有效方法，经实际顾问审阅与案例验收后再完善；静态 Skill 不等于 Agent 已学会。
3. 接系统 Agent 时，显式绑定版本、输入、渲染和检查，再跑独立公司的实际结果；09 整项继续未完成，04 的页码/单位/脚注核验也继续保留。
