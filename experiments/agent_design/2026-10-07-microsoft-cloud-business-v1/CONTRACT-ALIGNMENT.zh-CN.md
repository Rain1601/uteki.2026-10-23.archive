# 类型契约对齐：本地验收

当前行动：修正模型可见 Schema 与主机 kind/role 校验不一致。

## 已完成

新增显式版本 `business-draft-v2`。公司、报告分部、业务、产品组使用各自的节点 Schema；同一类型定义同时生成模型可见 JSON Schema 和本地校验。CLI 必须显式选择新版，旧默认版本不变。

| kind | 合法 role |
|---|---|
| company | null 或不填写 |
| reportable_segment | null 或不填写 |
| business | market、application_platform、null 或不填写 |
| offering_group | offering_group、null 或不填写 |

提示词要求 kind 与 role 联合满足一个 Schema 分支。分类仍须来自原文，不自动改类型、删角色或接受语义结论。原有范围、逐声明证据、关系、全块处理记录校验继续执行。

## 实际检查

- 55 项相关本地测试通过，包括模拟 HTTP 的新版完整执行。没有调用真实模型。
- 穷举 4 种 kind × 5 种 role（包括 null 与非法值），JSON Schema 与 Pydantic 对接受/拒绝判断一致；省略 role 也通过。
- 两个独立合成公司/期间检查请求冻结、公司范围与无效证据拒绝。
- 修改前后比对三个历史契约的 Schema 与固定输入生成的提示词，内容未变。实现文件哈希已改变，旧预检不能直接重放，须生成新预检。
- run-02 原始正文保持不变。仅在内存切换契约版本，新 Schema 定位到 businesses[6] 的 kind/role 冲突。两种结构合法的替代值只做离线检查，没有采纳任何一种，也不代表语义正确。
- `contract-v2-preflight.*` 保存同一冻结输入的新版本请求与 Schema，只做离线预检，未执行。仍是提示词传 Schema；没有宣称 AIHubMix 已启用服务端 Structured Outputs。

## 剩余缺口与下一步

尚无合格真实业务图。GitHub/Nuance 归属范围、声明引文和遗漏要点仍须处理。下一步仅准备与新版契约一致的局部内容修复并按原评价清单验收，不把格式通过当成质量通过。

本轮新增 API 费用为零，历史估算累计仍为 $0.537312。此前提出的实验总限 $0.60 → $0.70 尚未明确确认；原 between_tools 修复预检留作历史，不能作为新版已执行证据。
