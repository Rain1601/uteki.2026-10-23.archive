# 本机 Claude 对话窗口

用户与 Codex 通过同一个服务继续同一段 Claude 对话。页面能查看完整提问、回答、模型、状态和费用估算。已有轮次保留原文，新轮次追加保存，并记录由用户还是 Codex 发起。

## 打开与使用

当前实例：[打开 Claude 对话](http://127.0.0.1:8770/)。原 Data Agent 页面仍在原端口。

左侧选择历史轮次；右侧独立滚动阅读。长问答可以展开或复制全文。底部输入后点击发送，或按 Cmd / Ctrl + Enter；Enter 换行。页面自动同步 Codex 发起的新轮次，保留阅读位置。

左下角“下一次请求配置与额度”显示当前配置和累计美元上限。修改并保存上限代表用户明确设置本会话后续额度；不会重写原账本。上下文越长，下次请求需要预留的费用越高。页面估算采用会话冻结的单价，不能代替供应商账单。

当前使用 AIHubMix 的 `claude-opus-5-5`，默认下一次请求为 adaptive thinking、high effort、4096 输出上限、非流式。Codex 客户端可显式指定单次输出上限，实际值保存在该轮请求、配置和回执投影中，不改写全局默认或历史窗口配置。读取页面不调用模型，发送才调用模型。

## 维护中的顾问规则

这是 Uteki 项目专用的顾问窗口。新请求的系统提示词按固定顺序组成：

1. 私密会话原有的 `session/system.txt`，作为冻结基础，不改写。
2. 仓库内的 [顾问补充约定 v1](prompts/advisor-v1.md)。
3. 仓库内的 [单一当前重点规则](../../docs/COLLABORATION_FOCUS.zh-CN.md)。这份共享规则由 Codex 与 Claude 使用同一原文。

路径从本应用的仓库位置解析，不从 `credentials_root` 或当前工作目录猜测。测试或显式复用 `DialogueService` 时可传入 `advisor_prompt_path` 与 `focus_policy_path`；共享服务默认加载本项目固定路径，不适合作为任意项目的通用客户端。

每次读取状态、预检和发送都会重新读取维护文件。编辑这些文件后，新的请求加载新内容，不需每轮重启。首次升级运行中的旧版服务需要重启一次。原有 `window/configuration.json`、旧请求与预算事件不修改。

新轮保存 `system-prompt.json`，包含基础提示词哈希、两份规则原文及各自哈希、组合后的系统提示词哈希。该快照同时绑定到新轮授权与回执，配置切面记录实际发出的系统提示词哈希。历史轮次按自己的快照核验；没有新快照的旧轮继续按冻结基础核验，不拿今天的规则重新解释过去的请求。

当前提示词快照哈希参与 revision。规则在预检后改变时，旧 revision 会被拒绝，调用方重新读取状态即可；不增加人工批准。费用预留包括完整新系统提示词。规则文件缺失、为空或格式无效时，新发送停止并返回 `advisor_prompt_unavailable`，已验证的历史仍可查看。

`history` 的配置投影提供 `advisor_prompt.status`、组合与组件哈希；每轮提供 `system_prompt_snapshot_sha256`。这些只读元数据可用于确认规则已加载，不向浏览器公开私密系统提示词或完整规则快照。

## 启动

在仓库根目录执行，显式指定私密会话目录与凭据所在的项目目录：

```sh
PYTHONPATH=src .venv/bin/python -m apps.claude_dialogue \
  --conversation-root /absolute/private/conversation \
  --credentials-root /absolute/project \
  --port 8770
```

现有会话目录是 `/Users/rain/.codex/visualizations/2026/10/06/01a110b1-5b89-71a2-9e33-25b63fd06f2b/private/claude-data-products`。当前凭据项目是 `/Users/rain/Documents/ChatGPT/uteki.beta`。该路径是当前实例选择，不是共享服务默认值。

服务只监听 `127.0.0.1`。私密目录必须为 700，记录文件为 600。API Key 仅在服务端从既有凭据加载；前端与响应不包含 Key。只提供三份公开页面资源，私密目录不作为静态文件根目录。该工具面向同一台电脑的本地协作，不提供远程多人账号管理。

## Codex 继续同一段对话

服务启动后，通过共享客户端读取状态。需要完整可见问答时添加 `--full`：

```sh
.venv/bin/python scripts/claude_chat.py \
  --conversation-root /absolute/private/conversation history --full
```

把本次完整问题写入私密 UTF-8 文件后发送：

```sh
.venv/bin/python scripts/claude_chat.py \
  --conversation-root /absolute/private/conversation send \
  --message-file /absolute/private/question.txt \
  --expected-revision REVISION_FROM_HISTORY \
  --request-id UNIQUE_REQUEST_ID \
  --wait
```

请求 ID 使用 8–100 位字母、数字或连字符。客户端未指定时会生成 UUID。页面与客户端共享 revision、写入锁、完整历史和费用记录。过期 revision 会拒绝提交。相同 ID 和内容重复提交只返回原记录，不再次请求模型。

客户端在发送前输出请求 ID。网络超时后先用 `history` 核对状态，再以原请求 ID 查询提交；不要盲目换新 ID 重试。模型失败、输出不完整或中断会保留提问与已有结果，暂停续发，等待核对本轮与供应商费用。当前版本没有自动修复或自动重试。同一会话只允许启动一个窗口服务；重启后未结的提交标为待核对，不能当作模型失败或零费用。

核对后如需继续，必须显式选择最后一轮失败编号。以下示例的 `FAILED_TURN_NUMBER` 必须替换为实际轮号：

```sh
.venv/bin/python scripts/claude_chat.py \
  --conversation-root /absolute/private/conversation send \
  --message-file /absolute/private/continuation.txt \
  --expected-revision REVISION_FROM_HISTORY \
  --request-id NEW_EXPLICIT_CONTINUATION_ID \
  --continue-after-failed-turn FAILED_TURN_NUMBER \
  --max-tokens 8192 --wait
```

这只适用于服务已收到完整 HTTP 200 响应、记录终止状态、确认返回模型、取得可估价用量的失败，例如 `max_tokens` 耗尽且没有完整正文。费用未知、请求未结束、响应丢失或仍在执行都不能用此选项解除阻塞。新消息仍受当前累计额度和完整上下文预留检查，选项不会提高额度。

新轮追加 `failure-recovery.json`，绑定旧失败回执哈希、明确发起者、轮号、revision 和本次输出上限。旧失败状态、原文与费用不变。发送给模型的上下文用明确标注的用户记录保留失败提问与可见残稿，不将残稿伪装为完整助手回答，也不保存隐藏思考。该功能通过现有共享 API 与客户端提供，页面暂无单独的续发按钮。

提交 ID 同时绑定消息、发起者及这两个配置选项。相同 ID 不会重复调用；修改输出上限或失败轮号而复用 ID 会报冲突。

## 保存与边界

- 原始 `session/turns` 和旧 `continuations` 不改写。新轮次继续追加到 `continuations`。
- `window` 保存本地连接信息、提交回执及显式预算变更。不要将此目录放入仓库、同步到公开位置或交给静态文件服务器。
- 完整上下文发送使用已验证的历史链。旧 Markdown 汇总与 `latest-request.json` 是历史快照；后续以共享服务的历史为准。
- 页面显示可见回答原文；当前不排版 Markdown 表格、不提供模型切换、附件上传或代码执行。既有系统提示保留为冻结基础，新请求加载上面的维护规则。
- 发送是单次非流式请求，等待期间仍可浏览历史和编辑下一条。关闭页面不取消正在执行的请求。

## 验证

2026-10-07 聚焦规则接入：41 项定向模拟检查通过，独立代码复核未发现新增阻断。实际运行服务已重启，读取接口返回 `advisor_prompt.status=ready`，共享规则 hash 与维护原文一致。原会话仍为 11 次尝试，127 个历史文件保持不变，累计估算费用与 $3 额度不变。本轮新增模型调用为 0；这里只验证规则确实加载，未声称模型已经按新规则回答。

2026-10-07：实际 9 轮问答与磁盘原文逐项一致，页面资源和读取接口返回 200，原记录字节未变。浏览器入口 → 共享存储 → Codex 客户端的整合检查使用模拟供应商；确认两种入口携带同一段完整上下文、追加角色记录，重启后同一提交不重复执行。服务、HTTP 边界与页面控制器另有定向检查。未发起真实模型测试，未进行浏览器视觉验收。

本轮显式失败续发：36 项聚焦服务/HTTP/CLI/旧会话检查通过，供应商请求全部使用 mock；包含未知费用拒绝、未结束拒绝、预算/过期 revision 拒绝、8192 单次配置、失败原件保留、审阅事件防篡改、pending 拒绝与配置幂等。HTTP 检查仅使用本机随机端口，不重启现有实例；真实顾问续发由主任务在集成后执行。

维护提示词接入：41 项相关检查通过，包含真实请求 body、配置指纹、规则修改后的 revision、旧轮快照独立核验、缺失/空规则阻止发送、历史防篡改和固定仓库路径。所有供应商请求均为 mock。对当前真实会话另做只读预览：11 次尝试、10 次完成，127 个历史文件字节哈希未变，共享规则状态为 ready；没有付费调用、预算变更或服务重启。这证明加载与历史兼容，不证明真实顾问已遵循新规则回答。
