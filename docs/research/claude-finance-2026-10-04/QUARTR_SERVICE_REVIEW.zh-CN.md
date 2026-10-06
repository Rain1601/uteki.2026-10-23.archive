# Quartr：自建价值、费用与接入

核对日期：2026 年 10 月 4 日。依据公开官方文档、当前插件目录查询和本地 Codex 命令帮助；尚未登录 Quartr、取得商业样本、购买或实测其服务。本轮没有联系销售。

## 判断

Quartr 的核心功能可以独立实现。REST、MCP、全文检索、公司—事件—材料关系都是可理解的技术。更可能构成壁垒的是历史覆盖、稳定采集、财报季并发处理、纠错和客户长期集成。这是基于公开服务契约的判断，不是对其内部成本、源码或实际准确率的审计。

自建目标需要先声明覆盖范围。例如，为一组明确选择的公司提供会后财报材料服务，与持续覆盖全球公司并交付低延迟直播，是不同规模的工程。不能从一个样例工作流顺利运行，推导出整个商业服务容易复制。

## 哪些容易做，哪些需要长期投入

| 层次 | 公开证据 | 对 Uteki 的含义 |
| --- | --- | --- |
| 接口与对象组织 | 公司 → 事件 → 独立发布的文档、音频、文字稿；支持 REST、MCP、SQL 等出口。[数据模型](https://quartr.com/docs/data-overview) | 可直接研究其公开设计，用我们自己的材料实现同类能力。 |
| 历史库与覆盖 | 官方宣称 16,000+ 公司、65+ 市场、50m+ 文档。[MCP 产品页](https://quartr.com/mcp) | 真正的工作包括公司身份、来源变动、缺失材料和历史回补。总量不能证明每家公司覆盖完整；本轮未独立审计。 |
| 实时交付 | 官方公布直播及会后文字稿的交付时效。[服务时效](https://quartr.com/docs/data-overview) | 单次音频转写可做；财报季大量事件同时开始、断流后恢复、及时纠错，是另一项能力。第一阶段可以先做会后服务。 |
| 内容修订 | 直播包含无法听清、置信度和词级修订；会后从 raw 版到 edited 版，增加说话人信息。[直播结构](https://quartr.com/docs/datasets/live-earnings-call-transcripts) · [会后稿](https://quartr.com/docs/datasets/earnings-call-transcripts) | 准确率要单独评测数字、单位、否定词、专有名词及身份，不能只验证接口成功。 |
| 持续同步 | 文档和事件分别更新；通知可能乱序、重复，需轮询补漏。[同步](https://quartr.com/docs/rest-api/fetching-data) | 软件机制可复刻，长期异常处理需要持续维护。 |
| 研究工具 | MCP 还包含标准化财务主表、全文搜索、摘要与用户工作区等工具。[工具文档](https://mcp.quartr.com/docs) | 试用应观察具体任务的输入和结果；工具数量不等于回答质量。 |

目前没有足够公开证据证明其护城河是某个独家算法，或者所有数据都来自独家来源。反过来，也不能因为原始披露公开，就忽略多年整理、补漏和交付的投入。销售询价是销售方式，无法据此判断服务成熟度。

## 价格、试用与购买

| 产品 | 当前可核实的方式 | 未公开或待确认 |
| --- | --- | --- |
| Mobile | 官方提供免费移动应用，适合先体验电话会、文字稿和研究交互。[移动端](https://quartr.com/products/mobile-app) | 不等于赠送 API 或 MCP 数据权限。 |
| Pro | 面向研究人员的工作台；按多席位、企业方案询价。[价格页](https://quartr.com/pricing) | 单人/月/年金额、最低席位、固定试用天数均未在本轮查看的页面公开。 |
| Pro MCP | 包含在符合条件的 Pro 中，学生计划不适用；用于订阅者自己的研究。[接入文档](https://mcp.quartr.com/docs) | 尚未确认用户账号权限，未完成真实调用。 |
| API | 面向产品集成，按数据包和使用需求洽谈及 pilot。[API 产品页](https://quartr.com/products/quartr-api) | 具体价格、免费额度、试点期限和下载计费需要报价；不能用请求限速推断计费。 |
| Snowflake 样本 | 官方称 Marketplace 有真实文档样本，无需销售电话。[样本入口说明](https://quartr.com/integrations/snowflake) | 本轮未取得样本，也未验证样本大小及账号条件；查询使用自己的 Snowflake 计算资源。 |

[询价表单](https://quartr.com/contact-sales)区分 Pro & MCP 与 API。试点至少应确认单人报价、试用期限、数据覆盖、历史深度、允许用途及调用限制；本轮没有代填或发送表单。

使用范围也影响“试用后自己做”的路径：官方 2026 API 内部使用标准条款 §3.2 限制用 Quartr Data 开发或 benchmark 竞争服务；具体订单及其他产品条款需分别核实。学习公开文档、从 SEC/公司 IR 自取原件并独立实现，可以先推进；不要把获得试用账号理解为获得复制其商业数据集的许可。[标准 API 条款](https://a.storyblok.com/f/182663/x/2e1cfd0563/quartr-api-subscription-terms-international-internal-2026.pdf)

## Codex 和 DeepSeek 能否使用

**Codex：官方支持。** 直接连接地址为 `https://mcp.quartr.com/mcp`，采用 Streamable HTTP 与 OAuth。用户仍需用有权限的 Quartr 账号登录。[Quartr 接入说明](https://mcp.quartr.com/docs#codex) · [OpenAI MCP 说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)

本轮插件搜索没有返回 Quartr，这不等于整个目录永久没有；还可在[插件目录](https://chatgpt.com/plugins)查看。直接 MCP 接入不依赖搜索结果。

本机命令帮助确认的添加方式如下。Quartr 文档中带 `--transport http` 的 Codex 示例与本机语法不一致，应以实际客户端支持的 `--url` 为准：

```bash
codex mcp add quartr --url https://mcp.quartr.com/mcp
codex mcp login quartr
```

这些命令仅记录在文档中，本轮没有执行添加或登录。真正完成接入需验证：认证成功、订阅允许数据访问、至少一次公司搜索和文档读取成功；保存配置不代表可用。

**DeepSeek：可在使用其 API 的应用中接入。** 官方支持工具调用，但模型本身不执行函数。我们的应用需要承担 MCP 连接、OAuth、工具执行及结果回传。未找到足以确认 DeepSeek 官方聊天客户端支持直接安装 Quartr 的依据。[DeepSeek 工具调用](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)

## 下一步

1. 先看免费移动端及公开结果，确认我们究竟需要哪些行为；有 Pro 权限后再验证 Codex 实际连接。没有账号时不把安装步骤当成完成体验。
2. 为自建服务选一个明确公司、期间和财报事件，用原始来源形成材料清单、全文、关键事实和引用；验收完整度、数值、更新时间与缺口。
3. 扩到不同公司和期间，再决定是否需要直播、全球覆盖和商业数据补充。前一轮的本地能力与缺口已整理在[数据服务能力对照](/Users/bytedance/Documents/ChatGPT/uteki/docs/research/claude-finance-2026-10-04/DATA_SERVICE_BENCHMARK.zh-CN.md)。

可以把“更好”的目标落在我们的具体任务上：固定研究范围内，材料更完整、引用更细、旧判断更容易重现、中文研究流程更顺畅。是否超过 Quartr，仍需要实际证据。
