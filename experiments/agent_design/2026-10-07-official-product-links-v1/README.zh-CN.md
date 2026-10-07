# 官方产品入口与 To Watch：一个节点的小样

用户要求财报梳理后可按需补充官方产品超链与观察点，并将方法放入 Skill。此次选定既有 NVIDIA FY2025 业务图中的 **NVIDIA AI Enterprise**，不更改原图、报告证据、收入数据或 Workflow。

| 读者看到什么 | 本轮实例 |
|---|---|
| 产品入口 | [NVIDIA 产品官网](https://www.nvidia.com/en-us/data-center/products/ai-enterprise/) |
| 后续查阅地点 | [NVIDIA 官方文档](https://docs.nvidia.com/ai-enterprise/index.html)，含发布分支、发布说明、支持和许可入口 |
| To Watch 1 | 产品包含项与许可范围是否变化；关注新增、移除、重新归类与适用条件 |
| To Watch 2 | 版本、支持范围与生命周期是否变化；回读更新的版本范围和生效时间 |

两个网页已实际打开核对。产品页主标题与目标节点匹配；公司官网身份还与原官方 PDF 所列公司入口交叉核对。文档页有匹配的产品标题、NVIDIA Corporation 版权与公司主页链接。身份检查不是只看域名。记录时间为 2026-10-07T08:13:05Z，发布时间未知；仅记录工具观察的最终地址，未单独验证完整重定向链。

公司入口的原件依据：此前冻结的 [NVIDIA 官方 PDF](../2026-10-07-business-map-mermaid-v1/nvidia/source.pdf) 及其 [派生 HTML](../2026-10-07-business-map-mermaid-v1/nvidia/source.html)，定位 `/html/body/section[15]/p[7]`。前者 SHA256 为 `757b344ab62ba282f6e44e0702e8ce5f190d88fb23b5e0a2beaf4cb277a395cc`；后者为 `47daa32ef7787e4d705d55cb2209b383edc2a6a504fbb7cc995ec431bdaaa24b`。

[补充记录](nvidia-ai-enterprise.json)单独绑定原 BusinessMap SHA256 `bcebbd790caa9bb59be5de9a8a1ada0d31f8800d58a37bb68f2fcb6739f84ddd` 和 `nvidia_ai_enterprise` 节点。其中短原文 hash 只校验所保存摘录，不表示已冻结整张当前网页。当前网站与截至 2025-01-26 的财报属于不同时间范围；观察建议也不是已发生变化。

展示接入[原 NVIDIA 验收页](../../../docs/design/data-agent-acceptance/nvidia-business-revenue-v1/index.html)，点“官网补充”下的产品按钮，或选择 NVIDIA AI Enterprise 节点。产品身份、核对依据和短原文可展开，原件和补充文件分别可查。网页展示是可选参数，不触发访问官网或模型调用。

方法保存于 [项目 Skill](../../../skills/uteki-official-product-links/SKILL.md)。本轮是 Codex 人工网页核对与工程展示，新增付费模型调用为 0；系统 Agent 自动发现尚未接入，没有启动持续监控，也没有改动现有 Claude 顾问账本。

实际检查见 [delivery-check.json](delivery-check.json)：补充记录绑定、URL、引用和状态边界与页面静态交互通过，原产物未改，页面 HTTP 200 与本地内容一致。Skill 本地引用、命名及正文已复核；官方 `quick_validate.py` 在当前 Python 环境因缺少 PyYAML 未执行成功，不能记为该工具通过。未做浏览器视觉验收或模型能力评测。

独立复核后补全了公司身份依据的历史源文件路径与 hash，并澄清首次无法读取的候选仅保存为 `gaps`，不伪造最终地址或原文。渲染器没有自动核验域名身份，也没有自动抓取能力。

下一步：让系统 Agent 在显式选定的另一产品上按需加载同一 Skill，保存发现与归属核对记录，再与人工结果比较。当前一个产品的小样不代表整家公司、其他公司或官网自动发现的完整验收。
