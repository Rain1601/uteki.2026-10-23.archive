## Context

现有自由文本不能可靠转换成完成百分比。OpenSpec status 检查产物状态，validate 检查规范结构；代码符合性仍需 Agent 或人逐条复核。

## Goals / Non-Goals

提供可定位到文件行号的事实汇总。首轮不做自动任务核销、全库历史规范迁移、运行模型、Git 写入或自动研究验收。

## Decisions

- 直接采用 OpenSpec 1.13.2 默认 spec-driven 流程，不自建规范引擎。
- npm scripts 统一终端入口，Python 标准库做现有项目资料盘点。
- 声明状态、证据文件存在性、未执行的验证分开输出；不生成完成百分比。
- Git 只读且使用参数列表；本地链接不得越过仓库边界读取。
- 初始 change 保持可 review 状态。openspec/specs 当前不代表已有全部产品能力。

## Risks / Trade-offs

自由文本盘点只能发现显式声明和链接，无法理解全部冲突。报告可能遗漏未登记文档；需结合原文、代码与运行证据人工复核。Git 远端引用只反映最后 fetch，盘点不联网刷新。

## Migration Plan

先覆盖本次进度命令，后续有实际变更再加入相应规范。旧文档继续作为历史和范围依据。
