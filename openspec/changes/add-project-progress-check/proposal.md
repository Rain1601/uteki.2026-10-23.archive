## Why

TODO、技术提案、Git 提交和实验报告分散，容易把“有文档/目录/提交”误判为功能完成。需要可重复的只读盘点，并让后续变更使用统一规范。

## What Changes

- 固定 OpenSpec 版本，提供规范列表、详情、状态、结构验证和新建变更命令。
- 提供项目进度盘点：Git、TODO 声明、规范记录、证据链接，输出中文或 JSON。
- 不自动执行模型、测试、联网、勾选待办或采纳研究结果。

## Capabilities

### New Capabilities
- `project-progress-check`: 只读汇总进度依据，区分声明和验证。

### Modified Capabilities
无。

## Impact

新增开发命令、OpenSpec 配置、Python 盘点脚本与定向测试。现有 TODO/路线图仍保留，历史实验及金融能力状态不迁移或重写。
