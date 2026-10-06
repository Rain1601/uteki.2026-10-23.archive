## 1. 规范接入
- [x] 1.1 核验 OpenSpec 官方源码与 npm 版本，固定开发依赖和终端命令。
- [x] 1.2 建立本次 proposal、design、spec 和项目规则，保留旧路线图边界。

## 2. 盘点命令
- [x] 2.1 实现只读 Git、TODO、文档状态及链接盘点，支持 JSON。
- [x] 2.2 用临时仓库验证提案、勾选与证据缺失分离，验证越界和错误输入。

## 3. 交付检查
- [x] 3.1 对本仓库实际运行盘点及 OpenSpec 严格校验，记录结果和限制。
- [x] 3.2 文档列出命令、复核步骤及当前状态差异。

验证依据：`tests/unit/test_project_progress.py` 的 6 项临时仓库测试通过；本仓库 `progress --json --check-links` 退出 0；`spec:check` 严格验证通过。使用与边界见 `docs/PROJECT_PROGRESS_COMMANDS.zh-CN.md`。未运行模型或全量回归，未归档。
