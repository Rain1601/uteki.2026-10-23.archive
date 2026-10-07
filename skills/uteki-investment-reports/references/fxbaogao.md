# 发现报告接入参考

核查日期：2026-10-08。以下是公开文档核查，尚非已认证接口实测。

## 选择入口

- [官方接入页](https://www.fxbaogao.com/agent-interface)：Skill、CLI、MCP；页面将 API Key 与高级 VIP 关联。具体账户权限、价格和额度须另核对。
- [官方 CLI](https://github.com/fxbaogao/fxbaogao-cli)：适合脚本化获取；有 search、paragraph、pdf-url、download。新接入先固定版本并核对发布校验值。
- [官方 MCP](https://github.com/fxbaogao/fxbaogao-mcp)：适合支持 MCP 的客户端；线上入口为 `https://api.fxbaogao.com/mcp/`。工具和参数以连接后的实际声明为准。
- [官方 Skill](https://github.com/fxbaogao/fxbaogao-deep-research)：研究流程可供参考。本候选不声称已安装或继承其全部流程。

## 认证

执行前重读[官方认证与 API 文档](https://github.com/fxbaogao/fxbaogao-deep-research/blob/main/references/api-usage.md)，检查版本变化。该文档提供网页授权：取得 state，用户在官网完成登录授权，随后用同一个 state 换取密钥。不要向聊天、日志或交付物输出兑换响应；文档称该响应是纯文本。用户未完成授权前不轮询。

优先使用已有运行环境凭据。新凭据存储位置必须明确、私密并被版本控制忽略，权限仅限当前用户；不要覆盖项目现有 .env。密钥只交给核验过的提供商 API，不随 PDF 下载的跨域跳转转发。

## 接口验证重点

官方文档列出 search / paragraph / download；搜索支持机构、时间及 1–10 页。下载接口返回地址，不直接等于已取得 PDF。需要分别核验业务返回状态及文件内容。

已观察到文档差异：API 参数表把相对时间放在 startTime，示例却放在 endTime。首次实测用明确的起止毫秒时间戳，并核验返回报告日期；未实测前不替提供商决定哪一处正确。官方单篇阅读参考允许摘录底稿，而顶层 Skill 对正式精读要求 PDF；本方法把摘录限定为初筛。

不假定 Morgan Stanley / 摩根士丹利与 JPMorgan / 摩根大通的机构筛选字符串相同，也不把报告正文提及某投行当成该投行出具的报告。实际搜索后核对 orgName 与原件署名。

## 最小真实验收

2026-10-08 授权预检：`state/fetch` 实际返回 `text/plain` 数字串，不是带 agent_state 字段的 JSON 对象；保留为字符串生成链接。初次按文档解析失败，未兑换密钥。后续兼容响应时只接受明确的非空 state，错误页不能作为授权编号。已生成授权链接，等待用户在官网完成操作；不代表业务接口已通过。

在用户选择的对象、发表日期范围和机构范围内检索，选一份结果读取片段并取得 PDF，核对身份，回查一个数字和一个观点。保存去除凭据的请求参数、状态、报告 ID、文件哈希、页码和缺口。再用另一机构或材料检查方法迁移。权限/配额未知时先查账户说明，不启动批量下载。

## 已验证的单篇访问基线

2026-10-08 用户完成网页授权后，密钥兑换成功。此工作区使用根目录 `.env.fxbaogao`（0600，Git 忽略）存放独立凭据，未覆盖现有 .env；运行时须显式读取该路径或已配置环境，不依赖当前目录猜测。

明确样例：报告 5429854，2026-05-19，摩根士丹利台湾&亚洲。机构与关键词过滤、明确起止毫秒时间戳的搜索成功；返回 pubTime 是秒级时间戳，不能与请求参数单位混用。标题含 em 高亮标签，展示前需要清理。

paragraph 成功返回 3 个带页码片段，但 summary 只有空白；应按空值处理。download 成功返回带签名的临时 URL；不把它写进公开回执，持久引用使用报告 ID 和官网阅读页。PDF 下载不带 API Authorization。18 页 PDF 可解析，第 1、5 页经图像回读抽查；这不代表整份内容正确或所有机构均可下载。

该 PDF 带平台与第三方水印，只能表述为“平台提供的研报副本”。标题/机构/日期匹配不等于已向原发布机构验证真实性。接口未提供剩余额度或计费字段；不要据单次成功宣称无限下载或零费用。

补充核查：[官方完整指南](https://www.fxbaogao.com/agent-interface-document)明确下载会扣减会员下载权益；本次取得一份 PDF，实际扣减数量和余额未核对。该指南声明远程 MCP 仅提供 search_reports、get_paragraphs、get_pdf_url 三工具；本地源码中的 download_pdf 不能推定远程也有。
