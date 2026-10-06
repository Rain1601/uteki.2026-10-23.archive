# 有界语义复核循环 v3

工程循环已实现并通过 **117 项定向测试**；真实模型修订仍为 **partial**。最终两次实际延续请求都原样返回已拒绝草稿，不能报告引用修复或语义修订已经跑通。所有失败保留，未放宽验收，也未加入公司、期间或期望答案特判。

## 本轮行为与验收

输入是已封存的记录、来源正文、DOM 位置、明确检查轴及待核验断言。生成器输出带引用的意见；宿主核对身份、来源范围、位置、记录覆盖和上下文声明。有效草稿可交给 critic，critic 指向具体字段、记录和来源，实质错误触发修订，再完整验证。critic pass 仍需独立评分。

验收例：四条记录覆盖两个年度的收入与营业利润，数值恰好相同。只引用表头或收入行不能证明利润记录；宿主一次返回各字段的全部缺失锚点，模型补齐对应原行，保留表头/定义等语义限定，再做语义复核。脚本验证此路径通过；真实延续案例目前未通过。

本轮实现：

- 原 DOM 精确字符映射：表格锚定完整行，段落锚定实际 inline fact，同时保留上下文。修复原先必须引用整段的问题；重复数值、Unicode 空白、隐藏节点和尾部文本分别测试。
- 引用缺项反馈包含未验证原稿、精确字段路径、每个引用组全部缺失 anchors；来源定位信息不提供财务答案。纯 schema 错误仍只回传字段和错误类型。
- proposal 协议纠正及语义修订共用最多三次机会；critic 协议最多两次。无效 critic 不驱动生成器改结论，网络或运行异常停止整个 run。两个角色共用累计账本，SDK 隐式重试关闭。
- critic 绑定归一化意见 hash，区分阻止接受的 error 与不阻止接受的 suggestion。宿主核对协议，独立评分检查 critic 的误报和漏报。
- 每次保留输入、实际 prompt/配置、原始/归一化意见、反馈、审计、逐请求费用、关键实现源码副本和 manifest。MSFT 102 条 candidate 及原件不改写。

## 实际执行

使用 DeepSeek `deepseek-v4-pro`，temperature 0，max output 16,384，timeout 180 秒，SDK retries 0。以下各运行共用 [同一本地账本](../../../data/company_workspace/record_review/semantic-loop-v3/budget.sqlite)，最终 **24/24：18 次模型返回、6 次连接失败**。失败费用保持未知，不能计为免费；历史账本未挪用或重置。

按逐请求记录核算，已知 input **690,076** / output **32,488** tokens，已知估算 **$1.03955280**；6 笔失败费用及实际账单金额未知。未重复累加各次 usage 中的共享账本快照。

| 运行 | 新请求 | 实际结果 |
| --- | ---: | --- |
| real-run-01 | 4 | 两例均未接受，critic 引文位置错误 |
| real-run-02 | 5 | Cloud 接受且独审通过；分部未接受 |
| real-run-03 | 2 | 分部首稿获 critic pass；独审仍 partial，未发生修订 |
| development-run-01 | 3 | 1/2 运行接受；独审 0/2，critic 漏报缺资料声明矛盾 |
| heldout-run-01 | 2 | 0/2 接受；三处引用组缺少对应行，未进入 critic |
| regression-run-02 | 6 | 连接失败，0 次模型返回；由此修复运行故障被当作协议错误重试的问题 |
| continuation-01 | 1 | 重放真实失败稿后新请求一次，回复与原稿完全相同，未进入 critic |
| continuation-02 | 1 | 新版通用反馈指令下再请求一次，仍返回同稿；明确未启用 critic |

两个 continuation 各有一次**历史草稿重放**，不计新调用，不是新样本。输入、旧拒绝原因及旧响应均经 manifest/hash 核对；[延续脚本](continue_rejected.py) 不读取评分答案。它通过原有宿主重新产生反馈，未把独立审核意见或答案注入模型。最后一次只验证协议修复，不具备完整 critic 验收条件。

三次对应的 provider 原始返回文本哈希相同，解析结果与各自原始返回一致；响应 ID 不同，延续请求的 input tokens 增加。最后实际 prompt 哈希也发生变化。这证明已观察到“新请求返回相同内容”；仅凭这些证据不能认定上游缓存故障或确定模型忽略反馈的内部原因。

独立代理随后用实际归档输入走完整 SDK → HTTP MockTransport 做了四次离线捕获，确认当前最终 HTTP 消息保留全部 feedback 和新版 system prompt；mock 返回不同内容时 raw/final 输出也改变，未发现本地旧回复替换。没有外部调用，历史服务端行为仍无法确认。见[调用链核对](transport-review.md)。

## 独立结果与版本边界

- [真实案例 run02](real-review-02.md)：Cloud 独审通过仍属于该版 prompt/运行。
- [真实分部 run03](real-review-03.md)：历史金额措辞及费用分配覆盖仍有边界；critic pass 没有消除独审问题。
- [四个合成案例首轮](fixture-evaluation-01.md)：原始断言标签 11/11，但独审 case 0/4，不能把标签正确率当总体正确率。
- [第一次延续](fixture-evaluation-02.md)及[第二次延续](fixture-evaluation-03.md)：引用缺项仍在，operating income 被译作营业收入、费用调整方向说明错误也未改；并非仅缺少 critic。

v3 合成集首次运行前冻结；其结果已用于通用反馈改进，后续属于开发回归。预期文件未改，下一轮泛化判断需新未见集。旧 v1 的 12 题没有使用最新版 prompt 全量复跑；三家公司 13 道 query benchmark 仍为 not_run。真实两例也未在最后 prompt 下重跑，不能把不同版本的通过项拼成“当前版本全通过”。

## 复核入口

完整本地归档在 [semantic-loop-v3](../../../data/company_workspace/record_review/semantic-loop-v3/)。原始模型产物和账本不进入 Git；本目录保留可读结果、实验脚本和相对链接。

- [版本与费用核对](../../../data/company_workspace/record_review/semantic-loop-v3/integrity-and-accounting-01.json)
- [模型输入与任务](../../../data/company_workspace/record_review/semantic-loop-v3/real-inputs-01/input-manifest.json)
- [最后实际模型配置](../../../data/company_workspace/record_review/semantic-loop-v3/continuation-02/run/model/model-config.json)
- [最后原始响应](../../../data/company_workspace/record_review/semantic-loop-v3/continuation-02/run/model/review-0001-attempt-01.json)
- [最后宿主反馈](../../../data/company_workspace/record_review/semantic-loop-v3/continuation-02/run/packet-001/attempt-2-rejection.json)
- [CLI 与协议说明](../../../docs/DATA_AGENT_CLI.zh-CN.md)

验证覆盖输入/数据集绑定、锚点、跨公司和期间记录、协议反馈、两个角色的循环/取消/预算/网络边界，以及离线评分。未运行本轮全仓或浏览器回归。源码副本仅覆盖关键实现，尚非完整依赖环境复现包。

最终核对通过：12 个 manifest 的 367 项文件 hash、48 份实现副本、3 个冻结 expected；原 MSFT 数据集 manifest 和文件不变，102/102 条记录仍为 candidate。

## 下一步

1. 当前离线调用链已确认完整传递反馈，下一步用通用消息组织/模型配置对照验证真实修订，保留原始返回，禁止直接补成期望答案。本轮 24 次额度已用完，新增外呼须先明确新增累计范围。
2. 修订可用后，在新未见集上分别评估 host 引用修复、语义修订、critic 误报/漏报，再接入 prepare/查询状态。
3. 随后继续既定 GOOGL/MSFT/AMZN 的跨年、跨材料和 13 题真实 query 验收。当前结果不改变采纳状态，也不证明全文提取完整。
