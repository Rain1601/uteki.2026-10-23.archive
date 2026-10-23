# 离线回归 / Offline checks

日期：2026-10-23。入口是 `scripts/run_offline_checks.py`：不安装依赖、不下载资料、不调用模型，也不需要 API 密钥。S4 之前的旧测试范围说明见基线提交 `e563d959` 中的本文件（`git show e563d959:docs/OFFLINE_TESTS.md`）。

要求 Python 3.11+、macOS 或 Linux，以及 Node.js 20+。存储测试使用 POSIX 文件锁和真实子进程；不承诺 Windows 支持。环境安装见 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) 第 1 节。

## 两种范围

| 范围 | 命令 | 包含 | 环境 |
|---|---|---|---|
| 核心（默认） | `.venv/bin/python scripts/run_offline_checks.py` | `tests/unit/data_platform`、`tests/integration/data_platform`（排除下表两项）、`tests.test_offline_checks`、claude_dialogue 的 4 个 Python 测试；JS：`tests/claude_dialogue.test.cjs`、`apps/uteki_zero/*.test.mjs` | 主开发环境（`analysis` + `data`） |
| 加上 agent 测试组 | `<SDK 环境>/bin/python scripts/run_offline_checks.py --integration` | 上述全部，加 `tests/unit/data_platform_agent`、`tests/integration/data_platform_agent` 和 `test_gateway_sdk_wire` | 非 editable 的 `data` + `agent` 环境；需要允许监听 127.0.0.1 和启动子进程 |

`--list` 打印实际范围和被排除的测试，`--verbose` 显示每个测试名。Python 与 JS 任一失败，整体返回非零；导入错误、缺依赖都按失败处理，不会自动缩小范围。

## 按环境排除的测试

| 测试 | 原因 | 在哪里运行 |
|---|---|---|
| `test_gateway_sdk_wire` | 需要 Claude Agent SDK | `--integration`（SDK 环境） |
| `test_content_processes` | 断言安装包里**没有** agent SDK，且模块来自非 editable 安装 | 只装 data 的环境，单独运行（LOCAL_DEVELOPMENT 第 2 节） |

## 不在本入口内的检查

- Swiss C 前端：`node --test docs/design/company-workspace-swiss-c/*.test.mjs`（已知 1 项过时测试，见 FRONTEND_DESIGN 待办）。
- OpenSpec：`npm run spec:check`。
- 真实模型运行和真实 SEC 取数：需要授权，见 LOCAL_DEVELOPMENT 第 3 节。

agent 测试组使用本机回环的合成网关（`real_model_calls=0`），只验证接线，不代表真实模型或业务效果。离线检查通过也不代表业务验收通过。
