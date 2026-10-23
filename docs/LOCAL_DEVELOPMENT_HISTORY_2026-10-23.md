> **历史记录（2026-10-23 冻结，只读）。** 本文件是 LOCAL_DEVELOPMENT.md 精简前的原文，保留各批次的独立验收步骤、真实运行记录和查看命令。当前环境与命令见 [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md)。文中“核心设计 14.x”指 [设计历史](DATA_AGENT_DESIGN_HISTORY_2026-10-23.zh-CN.md) 的同号章节；其中的命令只适用于当时的批次和账本状态，不要直接重跑。

# 本地开发与资料恢复 / Local development and data recovery

当前 Python 环境安装以本页“从新检出仓库开始”和“M0 独立验证环境”为准。2026-10-08 的 交接说明（已归档：`docs/MACHINE_HANDOFF.zh-CN.md`，恢复方法见[归档说明](REPOSITORY_RETENTION.zh-CN.md)） 保留历史私密状态迁移与资料恢复边界，不作为当前依赖安装入口。

## 当前交付状态

2026-10-15：Data 共享核心前四批与第四批 review 收尾已完成各自限定验收；当前六工具、程序化计算/交付及本地复现方式见本页第四批章节和核心设计 14.12.12–14.12.14。M0 仍限离线，真实模型/网关、Agent 自主业务与工作台不在该完成结论内。

2026-09-22 更新：仓库已包含公司名单、部分完整公开材料与索引、研究数据发布，以及 Data Agent 查询快照和历史样例。后续开发顺序、已知边界和换机器交接见 [开发待办](../TODO.md)。凭据、费用账本和含本机路径的运行元数据不随 Git 同步。

2026-09-18 接手时部分资料尚未取得；下文保留恢复方法供实际缺失时使用，不表示列出的文件现在都缺失。新环境先运行工作区检查确认本次检出的状态。离线检查通过不代表 M0 验收、完整年报核验、模型质量达标或历史人工审核已恢复。

## Data Agent 轻量功能 review（2026-10-15）

本节复用已有入口，只查看正常功能链，不运行整套回归或创建新虚拟环境。**下述 SDK 验收使用本机模拟服务：实际 SDK/CLI 收到脚本预写的模型响应，再执行真实 Data 工具和计算。没有请求 OpenRouter/DeepSeek；模型名字段写着 DeepSeek 不表示它参与了推理。** 这些用例验证接线、工具执行及结果保存，不验证真实模型自主选工具或真实网关兼容。

从仓库根设置路径。当前机器复用检查点 4 的普通安装 SDK 环境；新检出先按本文安装 data + agent，再将 uteki_review_py 指向该环境。源码变化时重装当前项目并核对导入；只改文档不重复安装。以下只创建临时数据/结果目录：

```bash
uteki_review_repo="$PWD"
uteki_review_py="$uteki_review_repo/output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python"
uteki_review_dir="$(mktemp -d "${TMPDIR:-/tmp}/uteki-review.XXXXXX")"
export UTEKI_GATEWAY_OPENAI_EVIDENCE="$uteki_review_dir/openai"
export UTEKI_GATEWAY_CLAUDE_EVIDENCE="$uteki_review_dir/claude"
```

原件存储示例：写入合成主文件、附图及一个未取得附件，重新打开并读回。storage.json 的 main_round_trip 应为 true，不代表来源业务身份已核验。

```bash
mkdir "$uteki_review_dir/storage"
"$uteki_review_py" -I "$uteki_review_repo/tests/fixtures/data_platform/store_worker.py" \
  example "$uteki_review_dir/storage" > "$uteki_review_dir/storage.json"
```

OpenAI SDK 本机模拟正常链：

```bash
"$uteki_review_py" -I -m unittest discover \
  -s "$uteki_review_repo/tests/integration/data_platform_agent" \
  -p test_gateway_openai.py \
  -k test_actual_chat_client_and_runner_deliver_from_eight_shared_tool_requests -v
```

Claude SDK/CLI 本机模拟正常链，需要本机 loopback 和进程观察权限：

```bash
"$uteki_review_py" -I -m unittest discover \
  -s "$uteki_review_repo/tests/integration/data_platform_agent" \
  -p test_gateway_claude.py \
  -k test_native_business_loop_bills_each_original_response_and_replays_delivery -v
```

各自应输出 Ran 1 test / OK。openai/normal.json、claude/normal.json 的 result.delivery.delivery 包含证据和计算。查看简要结果：

```bash
"$uteki_review_py" -I - "$uteki_review_dir" <<'PY'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
print("results:", root)
print("storage round trip:", json.loads((root / "storage.json").read_text())["main_round_trip"])
for kernel in ("openai", "claude"):
    item = json.loads((root / kernel / "normal.json").read_text())
    result = item["result"]
    print(kernel, {k: result[k] for k in ("status", "mode", "real_model_calls")})
    print("calculation:", result["delivery"]["delivery"]["calculations"][0]["value"])
PY
```

2026-10-15 已复跑这三个入口：存储读回为 true；两侧各 8 次本机合成 HTTP 请求，status=completed、mode=gateway_synthetic、real_model_calls=0，合成计算结果均为 -2.250000000000000000。所用普通安装的 70 个源码/SQL 文件与当前源码一致，未新建环境或调用远端模型。实际 OpenRouter + DeepSeek 路径尚未验证，Claude 另有推理参数传递缺口。

真实 HTML/iXBRL 的程序验收已有 examples/data_platform/data_tools.py 和 scripts/data_agent/verify_tool_delivery.py，具体方式见本文“六工具与可追溯交付”段落；需显式的独立数据根、请求及验收材料。这同样不表示 Agent 自主选材；没有材料时使用本节合成入口即可。后续 Sonnet/GPT 的真实链路另需独立 profile 与已授权执行契约。

## 从新检出仓库开始

项目声明 Python 3.11+；本轮环境复现使用 Python 3.13。Node.js 20+ 仅在使用对应前端/开发规范工具时需要，Python 安装与 M0 探针不需要 Node。归档存储使用 POSIX 文件锁。

两套环境安装同一个 Uteki Python 包，但依赖锁分别管理：

| 环境 | 依赖声明 | 安装依据与边界 |
|---|---|---|
| 主开发环境 | 根 `pyproject.toml`，按需选择 analysis/data/mcp/agent extras | 根 `uv.lock`；确定性核心选 data，双 SDK 选 data + agent；agent 显式包含 Claude SDK |
| M0 SDK 验证环境 | 根 `pyproject.toml` 的基础依赖 + `requirements/m0.in` | `requirements/m0.txt` 的 40 个固定版本，Python 3.13；独立环境保留已验证 SDK 组合，不与主锁混用 |

不提供 `m0` extra：该声明已迁到 `requirements/m0.in`，避免主项目元数据声明了一套未进入主锁的独立环境。两个锁允许共同包版本不同；升级须针对对应环境重新验证，不靠合并锁或整体升级消除差异。以下命令均从仓库根运行；首次安装依赖/构建工具可能联网，不请求模型、不需要 API 密钥。

```bash
uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp
uv pip check --python .venv/bin/python
.venv/bin/python -I -c "import uteki, uteki_eval, agents, duckdb, pydantic, lxml.etree, mcp"
```

`uv sync` 默认把项目安装为 editable，适合日常改代码；依赖仍按锁安装，锁与声明不一致时 `--locked` 会报错。首次环境可复现验收或安装机制变化时，使用全新目录和普通安装；后续功能 review 复用已核对的普通安装环境，源码变化时重装，不按检查点新建环境。首次干净安装示例：

```bash
uteki_env_root="$(mktemp -d "${TMPDIR:-/tmp}/uteki-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_env_root/main" uv sync --locked --python 3.13 --extra analysis --extra data --extra mcp --no-editable
uv pip check --python "$uteki_env_root/main/bin/python"
"$uteki_env_root/main/bin/python" -I -c "import uteki, uteki_eval, agents, duckdb, pydantic, lxml.etree, mcp; print(uteki.__file__)"
```

导入位置应在该新环境的 `site-packages`，不能指向仓库 `src/` 或旧虚拟环境；`-I` 排除环境变量、用户 site 和当前目录对 Python 导入的影响。保留实际 Python/平台、安装日志、包版本和未运行检查，不能把一台机器通过表述为所有平台已验证。安装数据依赖不等于存储草稿或业务功能通过验收。

现有离线检查可按需要运行，覆盖范围见 [OFFLINE_TESTS.md](OFFLINE_TESTS.md)：

```bash
.venv/bin/python scripts/run_offline_checks.py
.venv/bin/python scripts/smoke_research_workflow.py
.venv/bin/python scripts/check_workspace.py
```

上述检查不请求模型、不下载资料、不需要 API 密钥。测试和流程演练只向临时目录写审核状态。`analysis` 扩展用于离线假模型及报告契约测试；`data` 扩展提供 DuckDB/Pydantic，`mcp` 提供 MCP 入口依赖。

`check_workspace.py` 在资料缺失时返回 **2**，同时列出必需文件和可选功能缺口；以实际输出为准，不预设新检出一定失败。可用 `--json` 获取结构化清单，或 `--root /path/to/recovered-checkout` 只读检查另一份候选工作区。检查会核对研究发布清单里的文件指纹、材料索引指纹和原文整体指纹；它不替代真实页面验收。

资料恢复后启动：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --check
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app --host 127.0.0.1 --port 8765
```

打开 `http://127.0.0.1:8765/agent-results`。后台主导航只有“运行结果”和“运行过程”。根地址 `/`、`/companies` 和未选择材料的 `/data-workspace` 均以 HTTP 303 转到结果页。显式数据产物、原文、公司报告审核继续作为明细工具保留。启动会先检查必需输入；缺失或损坏时在绑定端口、迁移或初始化审核库之前退出。`--check` 即使检查通过也不启动服务、不写审核状态。完整来源、索引和分析扩展的缺口会单独报告。

完整本地回归的命令和覆盖边界见 [OFFLINE_TESTS.md](OFFLINE_TESTS.md)。`scripts/run_offline_checks.py --integration` 保留原测试失败与跳过结果，不会用占位资料补齐历史实验。

## M0 独立验证环境（2026-10-14）

选择尚不存在的环境路径，保留以前的运行结果。以下以 `output/m0-sdk/.venv` 为例；如已存在，显式更换路径，不覆盖旧环境或证据：

```bash
uv venv output/m0-sdk/.venv --python 3.13
uv pip sync requirements/m0.txt --python output/m0-sdk/.venv/bin/python
uv pip install --reinstall-package uteki-eval --no-deps . --python output/m0-sdk/.venv/bin/python
uv pip check --python output/m0-sdk/.venv/bin/python
output/m0-sdk/.venv/bin/python -I -c "import uteki, agents, openai, claude_agent_sdk, mcp; print(uteki.__file__)"
output/m0-sdk/.venv/bin/python -I scripts/run_sdk_probe.py --python output/m0-sdk/.venv/bin/python --fixture config/sdk_probe/fixture.json --profiles config/sdk_probe --output output/m0-sdk/probe.json
output/m0-sdk/.venv/bin/python -I -m unittest discover -s tests/unit -p test_sdk_probe.py -v
```

先同步锁定依赖，再以 `--no-deps` 普通安装当前项目，避免项目安装重新解析/升级已冻结依赖。源码修改后须用 `--reinstall-package uteki-eval` 强制重新构建并安装项目：本批曾观察到普通 sync 复用旧 wheel，安装成功本身不能证明测试的是当前源码。主环境使用普通安装验收时同样适用，替换 `--python` 为该环境解释器，并核对模块来源和文件 hash。`uv pip sync` 会移除未列在 requirements 中的包，因此每次重新同步后仍须重新安装 Uteki。不再用 `PYTHONPATH=src` 或入口脚本修改 `sys.path` 代替安装；独立 worker 使用 `-I` 从所选环境加载已安装包，父进程凭据/设置仍按原规则隔离。

M0 入口只接受合成 fixture/profile，并在场景内禁止网络与子进程；此命令不运行真实模型或原生 Claude CLI 循环。安装验证、15 项已有离线测试、9 个 SDK 合成场景与业务验收分别报告。输出路径已存在时会失败，须选新路径保留旧结果。

仅检查声明能否解析为现有 M0 锁、不升级版本时，可生成临时结果并比较包名/版本集合（不能覆盖原锁来消除差异）：

```bash
uv pip compile pyproject.toml requirements/m0.in --python-version 3.13 --constraint requirements/m0.txt --no-header --no-annotate --output-file output/m0-sdk/resolved-check.txt
```

有意升级 M0 时才重新生成 `requirements/m0.txt` 并复验；主锁仍由主项目维护。安装依赖的下载缓存可复用，旧虚拟环境的已安装包不能充当新环境验收结果。当前机制遵循 [uv 锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/) 及 [requirements 锁定流程](https://docs.astral.sh/uv/pip/compile/)。

## 第五批双 SDK 离线接入（2026-10-15）

正式 runtime 使用主锁的 `agent` extra，与 `data` 一起安装。2026-10-15 按官方最新稳定版升级为 OpenAI Agents SDK 0.24.0、openai 3.31.0、Claude Agent SDK 0.2.167 / CLI 2.1.300；MCP 保持 2.2.0。主锁仅另变更新版 SDK 必需的 pyjwt、urllib3。M0 独立声明与锁保留原已验证 SDK 组合，继续用于历史探针复现，不作为正式 runtime 的隐式依赖来源。后续 SDK 升级先核对官方发布，再同步主锁、当前 profile 和必要回归，不使用浮动版本，也不改写旧运行绑定。

```bash
uteki_sdk_repo="$PWD"
uteki_sdk_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-sdk.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_sdk_env/venv" uv sync --locked --python 3.13 --extra data --extra agent --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_sdk_env/venv/bin/python"
uv pip check --python "$uteki_sdk_env/venv/bin/python"
(
  cd "$uteki_sdk_env"
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_sdk_repo/tests/unit/data_platform_agent" -p 'test_*.py' -v
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_sdk_repo/tests/integration/data_platform_agent" -p 'test_*.py' -v
)
```

第二组会启动本机回环服务和随包 Claude CLI，需允许监听 127.0.0.1。worker 使用独立临时配置、虚拟令牌及拒绝外部连接的代理；没有真实模型推理或 OpenRouter 请求。OpenAI 使用实际 Runner 和脚本 Model；Claude 使用实际 SDK/CLI 与脚本 Messages 服务。缺少本机端口/子进程权限时明确记未运行，不能以 scripted CLI Transport 的结果替代此组。

当前 `agent.openai_runtime.run_offline` / `agent.claude_runtime.run_offline` 接受调用者提供的 DataService、context_ref 和精确 profile；不提供默认模型或付费入口。运行只接受明确标为 `offline_fixture_only` 的 fixture profile。2026-10-15 新增两侧 DeepSeek `unverified` profile 与 `gateway-contract.draft.v1.json`，仅用于执行契约 review 和隔离请求装配预检；现有 runtime 继续拒绝它们，修改配置状态不产生调用授权。推理配置未经对应能力验证会拒绝；不是已完成真实路由或 prompt 业务调优。当前 OpenAI 3.31.0 的锁定传输依赖仍是 `httpx2`，离线捕获须使用实际安装的客户端类型，不为历史示例另加旧 `httpx`。准备证据及限制见核心设计 14.12.17。

确定性核心的进程测试包含“SDK 未安装”的安装边界断言，必须在仅安装 `data` 的另一干净环境运行，不能在 agent 环境中删除或放宽该断言。第五批第一步限定验收及已知差异见核心设计 14.12.15。

## 原件存储与输入清单的独立验收（2026-10-14）

此切片只需要主锁的 `data` extra；不另设依赖锁，也不改变主开发环境与 M0 的关系。使用普通安装、独立进程和合成数据验证；这组检查使用以下专用入口，未加入依赖源码路径注入的旧离线 runner。以下命令从仓库根运行，临时环境与数据根均显式指定：

```bash
uteki_content_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-content-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_content_env/venv" uv sync --locked --python 3.13 --extra data --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_content_env/venv/bin/python"
uv pip check --python "$uteki_content_env/venv/bin/python"
"$uteki_content_env/venv/bin/python" -I - <<'PY'
import hashlib
import importlib
from pathlib import Path
import sys

for name in ("uteki.data_platform.contracts.content", "uteki.data_platform.content.store"):
    origin = Path(importlib.import_module(name).__file__).resolve()
    source = Path("src").joinpath(*name.split(".")).with_suffix(".py")
    assert origin.is_relative_to(Path(sys.prefix).resolve()), origin
    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(origin.read_bytes()).digest(), name
    print(name, origin)
PY
"$uteki_content_env/venv/bin/python" -I -m unittest discover -s tests/unit/data_platform -p test_content.py -v
"$uteki_content_env/venv/bin/python" -I -m unittest discover -s tests/integration/data_platform -p test_content_processes.py -v
uteki_content_root="$(mktemp -d "${TMPDIR:-/tmp}/uteki-content-data.XXXXXX")"
"$uteki_content_env/venv/bin/python" -I tests/fixtures/data_platform/store_worker.py example "$uteki_content_root"
```

示例写入合成 HTML、附图及一个明确缺失的附件，保存清单后重新打开存储并读回。完整契约、错误码、25 项测试的覆盖及未验证边界见核心设计 14.3.1、14.12.9；对象/清单可读不等于来源身份已核验或快照已发布。该切片要求支持硬链接和目录 fsync 的本地 POSIX 文件系统。

## 目录、快照与发布的独立验收（2026-10-14）

第二批继续使用主锁的 `data` extra，不需要 Agent SDK 或模型凭据。仅在临时根运行合成数据；不要指向已有生产目录。以下从仓库根开始，普通安装后核对全部 Data 包文件及 SQL，测试切换到仓库外目录。首次初始化要求调用者提供已有绝对目录；已有目录使用 `Catalog.open`，恢复需显式 `recover=True`。一个 Catalog 上下文持有整根排他锁，须先关闭才能再次打开。

```bash
uteki_catalog_repo="$PWD"
uteki_catalog_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-catalog-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_catalog_env/venv" uv sync --locked --python 3.13 --extra data --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_catalog_env/venv/bin/python"
uv pip check --python "$uteki_catalog_env/venv/bin/python"
"$uteki_catalog_env/venv/bin/python" -I - <<'PY'
import hashlib
import sys
from pathlib import Path
import uteki.data_platform

source = Path("src/uteki/data_platform")
installed = Path(uteki.data_platform.__file__).resolve().parent
assert installed.is_relative_to(Path(sys.prefix).resolve()), installed
for path in sorted(source.rglob("*")):
    if path.suffix not in {".py", ".sql"}:
        continue
    target = installed / path.relative_to(source)
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(target.read_bytes()).digest(), path
    print(path.relative_to(source), target)
assert (installed / "catalog/migrations/0001_catalog.sql").is_file()
PY
(
  cd "$uteki_catalog_env"
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_catalog_repo/tests/unit/data_platform" -p test_catalog.py -v
  ./venv/bin/python -I -m unittest discover -s "$uteki_catalog_repo/tests/integration/data_platform" -p test_catalog_processes.py -v
  ./venv/bin/python -I -m unittest discover -s "$uteki_catalog_repo/tests/unit/data_platform" -p test_content.py -v
  ./venv/bin/python -I -m unittest discover -s "$uteki_catalog_repo/tests/integration/data_platform" -p test_content_processes.py -v
)
uteki_catalog_root="$(mktemp -d "${TMPDIR:-/tmp}/uteki-catalog-data.XXXXXX")"
"$uteki_catalog_env/venv/bin/python" -I tests/fixtures/data_platform/catalog_worker.py example "$uteki_catalog_root"
```

示例执行登记→冻结→两版发布→关闭重开→旧引用读回；输出包含旧/新 AssetRef、冻结快照和 `business_verified=false`。四文件产物及字节 locator 只验证存储发布，不能当作真实 HTML/PDF 解析。参考核心设计 14.5.1、14.12.10：第二批 32+4 项测试、第一批 21+4 项回归；无模型调用。离线复现可为 uv 指定包含锁定依赖与构建依赖的缓存并加 `--offline`；缺缓存时应明确报告未运行，不更换依赖版本。

本地备份只支持：关闭所有 Catalog 句柄、完成 checkpoint 且停止其他写入后，复制完整 data_root 到另一显式根，再用 `Catalog.open` 完整核验。不要单独恢复 SQLite；其 head/文件不一致会被拒绝。失败 staging/未知残留保留，不通过删除或覆盖它们伪装恢复成功。本批只验证 macOS arm64 本地 POSIX，其他平台、网络文件系统和真实断电尚未验证。

## 官方 HTML/iXBRL 材料链的独立验收（2026-10-14）

第三批仍只用主锁 `data` extra，普通安装，不加载 Agent SDK 或调用模型。下例从仓库根开始；先安装并核对当前包，再从仓库外运行测试。首次同步可以下载锁定依赖，已有完整缓存时可加 `--offline`，不能用更换版本解决缺缓存。

```bash
uteki_html_repo="$PWD"
uteki_html_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-html-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_html_env/venv" uv --cache-dir "$uteki_html_env/cache" sync --locked --python 3.13 --extra data --no-editable
uv --cache-dir "$uteki_html_env/cache" pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_html_env/venv/bin/python"
uv --cache-dir "$uteki_html_env/cache" pip check --python "$uteki_html_env/venv/bin/python"
"$uteki_html_env/venv/bin/python" -I - <<'PY'
import hashlib
import sys
from pathlib import Path
import uteki.data_platform

source = Path('src/uteki')
installed = Path(uteki.data_platform.__file__).resolve().parents[1]
assert installed.is_relative_to(Path(sys.prefix).resolve()) and 'site-packages' in installed.parts
paths = [p for p in (source/'data_platform').rglob('*') if p.suffix in {'.py', '.sql'}]
paths += [source/p for p in (
    'infrastructure/document_sources/company_acquisition.py',
    'infrastructure/document_sources/official_discovery.py',
    'infrastructure/document_sources/sec_index.py',
    'infrastructure/document_sources/sec.py',
    'infrastructure/document_sources/sec_settings.py',
    'infrastructure/document_sources/filing_integrity.py',
    'domain/documents/__init__.py', 'domain/documents/models.py')]
for path in sorted(paths):
    target = installed/path.relative_to(source)
    assert path.read_bytes() == target.read_bytes(), path
    print(path.relative_to(source), hashlib.sha256(target.read_bytes()).hexdigest())
assert (installed/'data_platform/catalog/migrations/0001_catalog.sql').is_file()
PY
(
  cd "$uteki_html_env"
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_html_repo/tests/unit/data_platform" -p 'test_*.py' -v
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_html_repo/tests/integration/data_platform" -p 'test_*_processes.py' -v
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_html_repo/tests/unit" -p test_company_acquisition.py -v
)
```

真实材料示例为 [official_html.py](../examples/data_platform/official_html.py)。输入是显式审阅的公司/材料/期间/来源策略、编码及未知时间声明；验收 gold 不传入产品入口。已有本次本地证据时，以下复用已成功获取的冻结原件，不再次联网：

```bash
uteki_html_evidence="$uteki_html_repo/output/data-agent-html-20261014"
uteki_html_data="$(mktemp -d "${TMPDIR:-/tmp}/uteki-html-data.XXXXXX")"
"$uteki_html_env/venv/bin/python" -I "$uteki_html_repo/examples/data_platform/official_html.py" \
  --request "$uteki_html_evidence/request-A24-K.json" \
  --data-root "$uteki_html_data" --initialize \
  --acquisition-root "$uteki_html_evidence/acquisition-A24-K" \
  --receipt "$uteki_html_evidence/acquisition-A24-K/result-final.json" \
  > "$uteki_html_env/example-A24.json"
"$uteki_html_env/venv/bin/python" -I "$uteki_html_repo/scripts/data_agent/verify_html_material.py" \
  --data-root "$uteki_html_data" \
  --gold "$uteki_html_evidence/acceptance/frozen.v1.json" \
  --source-id A24-K --example-result "$uteki_html_env/example-A24.json"
```

示例关闭并重新打开 Catalog，再沿完整 AssetRef 读回正文与可解析数值；Microsoft 将 request、acquisition-root、receipt、source-id 换成对应 M25-K，使用另一个新根。其 HTML 没有 inline facts，因此只读回正文/表格，不补造数值记录。实际验收结果见核心设计 14.12.11。

`output/` 原件、收据与 gold 是本地证据，不随 Git 安装；新检出须先恢复完整证据目录，不能将缺文件记为通过。另行获准获取时，可将 `--receipt` 换为 `--acquire --settings-root <已有私密设置目录>`，并提供新的显式 acquisition-root、核对 request 中精确 URL 清单及请求/字节/时间限制。SEC 联系信息继续由 `resolve_sec_contact` 读取，不能写进公开 request。当前批次网络验收已完成，不因复现说明自动追加请求；下载版本变化须重新独立核验，不能覆盖冻结预期。

当前支持 UTF-8 静态 HTML 和声明的 iXBRL 数字转换子集。HTML 恢复、推断章节、nil、未支持转换/维度和未取得图片均可观察；不支持 PDF/OCR、外部 CSS/脚本渲染、图片理解、结构化查询或搜索。`HtmlReader` 是构造时验证的字节视图，重新构造才重新检查磁盘完整性。Catalog 单根排他；不得并行打开同一 data_root。旧四文件 build、HTML v1/v2 各按其版本复验。

## 六工具与可追溯交付的独立验收（第四批）

本批使用同一主锁的 `data` extra，通过普通安装运行，不需要任何 Agent SDK、模型凭据或新增网络取数。上节的格式限制属于第三批；第四批新增 HTML 搜索、结构化查询、确定性计算及交付，仍不包含 PDF/OCR、图片理解或 Agent 自主执行。具体参数与不支持的模式见 [API 0.0](DATA_AGENT_API.zh-CN.md)。

第四批收尾的行为测试位于 tests/unit/data_platform/test_review_fixes.py，创建恢复进程场景位于 test_tools_processes.py；它们随下述全量 Data 测试一起执行。create_context 创建失败后，使用相同请求及 request_key、显式 recover=True 完成恢复，不能换键绕过。仅对创建恢复生效，不重执行中断的补数。同步预算与实时 readiness 口径见 API 0.0/0.8。最新限定证据为 output/data-agent-review-fix-20261015/verification-final.json；其中旧版本兼容脚本需要保留的旧安装包，本地证据缺失不记为通过。

从仓库根创建一个新环境，重装当前项目，再切到仓库外执行测试：

```bash
uteki_tools_repo="$PWD"
uteki_tools_env="$(mktemp -d "${TMPDIR:-/tmp}/uteki-tools-env.XXXXXX")"
UV_PROJECT_ENVIRONMENT="$uteki_tools_env/venv" uv sync --locked --python 3.13 --extra data --no-editable
uv pip install --reinstall-package uteki-eval --no-deps . --python "$uteki_tools_env/venv/bin/python"
uv pip check --python "$uteki_tools_env/venv/bin/python"
( cd "$uteki_tools_env"
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_tools_repo/tests/unit/data_platform" -p 'test_*.py' -v
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_tools_repo/tests/integration/data_platform" -p 'test_*.py' -v
  ./venv/bin/python -I -W error::ResourceWarning -m unittest discover -s "$uteki_tools_repo/tests/unit" -p test_company_acquisition.py -v
)
```

仍须按上节方式核对实际包来源与源码/安装文件 hash；不能仅凭安装成功认定没有复用旧 wheel。此次核验包含全部 Data Python/SQL 以及复用的获取模块。行为测试只写临时目录和合成数据，acquire 通过既有 `prepare_sources` 链路注入合成传输，未启用真实网络。进程测试在子进程用明确退出点验证不完整响应、索引 head 切换与持久化后重放。

程序调用示例为 [data_tools.py](../examples/data_platform/data_tools.py)。它接收显式主体、来源策略、需求计划、工具参数及交付选择器，没有默认公司、期间、路径或预期答案。只操作已有独立 Data 根；重建派生索引也须在请求中显式提交 process。需要在其他目录复现已有真实材料时，先恢复第三批完整冻结证据并复制到独立测试根，再运行：

```bash
"$uteki_tools_env/venv/bin/python" -I "$uteki_tools_repo/examples/data_platform/data_tools.py" \
  --data-root /absolute/path/isolated-data-copy \
  --request /absolute/path/reviewed-tool-request.json \
  --output /absolute/path/new-tool-result.json
"$uteki_tools_env/venv/bin/python" -I "$uteki_tools_repo/scripts/data_agent/verify_tool_delivery.py" \
  --data-root /absolute/path/isolated-data-copy \
  --gold /absolute/path/frozen-tools-gold.json \
  --source-id A24-K --example-result /absolute/path/new-tool-result.json
```

示例拒绝覆盖已有输出；相同 request_key 和请求在同一根内重放已完成响应，不重新取数/处理。要验证修改后的代码路径，须采用新的 request_key，而不是用旧响应冒充新执行。gold 仅进入独立核验器，不传入产品入口；M25-K 的记录不适用，不能补造 inline facts。原始请求、失败、不同版本的 gold 与安装证据保留于 `output/data-agent-tools-20261014/`；这些本地材料不随 Git 发布，缺少时不能把真实材料核验记为通过。

宿主可单独装配 `OfficialAcquisitionAdapter`，其网络默认关闭；只有明确批准的精确请求、已登记主体/资产/来源、时间依据与 URL 清单能执行。不要在 JSON 放 SEC 联系人，继续使用私密设置与现有解析入口。中断且未保存响应的操作需先检查，工具不会自动重放副作用；已落盘交付通过 `read_delivery` 读回，重复 deliver 不改写交付。当前平台验收为本地 POSIX/macOS arm64/Python 3.13，其他平台、真实断电与网络文件系统不在已验收结论内。

## Agent 执行监控（2026-10-06）

启动工作台后打开 [Agent 运行](http://127.0.0.1:8765/agent-runs)。默认可回看两次已登记真实历史运行：`amd-fy2023-main-agent-v2-parent`（6 个父步骤、1 个提取任务、7 次调用）和 `amd-fy2023-cash-flow-main-agent-v2-parent`（7 个父步骤、1 个提取任务、8 次调用，以 `no_progress_limit` 停止）。从步骤展开子任务、输入、候选与用量；查看不会调用模型或改变采纳状态。历史记录没有心跳，也不会补造未保存的工具耗时。

要观察新的本地执行，工作台启动时同时提供观测目录和允许读取的业务输出父目录：

```bash
PYTHONPATH=src:. .venv/bin/python -m apps.review_workbench.app \
  --host 127.0.0.1 --port 8765 \
  --observation-root "$HOME/.local/state/uteki/observations" \
  --observation-output-root "$HOME/.local/state/uteki/runs"
```

`--observation-output-root` 可以重复指定；它是新运行目录的父目录，而非某个运行的目录。Data CLI 的 `agent query / extract / extract-batch` 使用同一个 `--observation-root`，输出例如 `--output "$HOME/.local/state/uteki/runs/query-001"`。具体请求、模型与批次参数见 [Data Agent CLI](DATA_AGENT_CLI.zh-CN.md#执行监控与历史导入2026-10-06)。这些执行命令仍按显式配置调用模型；开启工作台或读取历史本身不调用模型。

观测目录、业务输出和冻结数据须分开，输出必须是新目录，路径中不能含符号链接。观测目录保存本机运行位置，应放在仓库之外，或使用已忽略的 `data/agent_observability/local/`。每棵执行树只由一个本机进程写入；当前不支持跨进程续写同一执行树、多机调度或中断续跑。未加观测参数的执行不会自动成为实时运行。

页面可见时每 2 秒增量读取，隐藏时暂停。未结束运行的心跳超过 15 秒未更新，会显示连接中断、执行状态未知；已完成运行保持完成。只有开始记录或供应商用量未确认时，Token 和费用保留未知；界面分别显示本运行与含子任务的已知用量，估算费用不等于实际账单。

新增历史记录使用显式导入，不从实验目录自动选择：

```bash
./.venv/bin/python scripts/import_agent_run.py \
  --root "$PWD" --spec /absolute/path/new-run-spec.json
```

spec 的字段与适配范围见 [历史导入说明](DATA_AGENT_CLI.zh-CN.md#执行监控与历史导入2026-10-06)。导入只新增 `data/evaluation_views/agent-runs-v1.json` 的登记和展示摘要，保留原 manifest、产物和失败记录。来源、哈希、父子关系不匹配或 ID 已存在时拒绝；导入工程页也不代表已经登记到旧财务查看页。

## AiHubMix 最小连接测试

在项目根目录的 `.env` 中填写 `AIHUBMIX_API_KEY`，文件权限须为 `600`。也可通过环境变量配置；已有的 `AI_HUB_MIX_API_KEY` 别名仍受支持。脚本不会输出密钥，`.env` 已被 Git 忽略。

安装 `analysis` 扩展后，可显式指定模型和一个全新的结果目录：

```bash
.venv/bin/python scripts/smoke_aihubmix.py \
  --model gpt-5.4-mini \
  --output-dir /private/tmp/uteki-aihubmix-probe-001
```

此命令会调用真实模型。验收仅包含：模型调用一个本地工具取得随机校验码，再通过结构化字段返回同一校验码。最多两轮模型响应，每轮最多 1000 个输出 Token，总超时 90 秒；不会读取公司资料或运行研究任务。结果与请求费用记录写入指定目录，已有目录不可覆盖，失败返回非零退出码。

默认本地估算预算为 0.10 USD。当前登记的 `aihubmix/gpt-5.4-mini` 价格快照日期是 2026-09-13；估算不是实际账单，也不是服务商强制扣费上限。其他模型须先有明确价格记录。失败且用量未知时保留未知费用，不自动重试。离线脚本测试不能代替这次真实连接验证。

Claude 5.5 使用明确的版本名：`--model claude-opus-5-5` 或 `--model claude-sonnet-5-5`，每次使用新的输出目录。2026-10-06 核对的 AiHubMix 标价为：[Opus 5.5](https://aihubmix.com/model/claude-opus-5-5) 输入 4 USD / 百万 Token、输出 20 USD / 百万 Token；[Sonnet 5.5](https://aihubmix.com/model/claude-sonnet-5-5) 输入 2 USD / 百万 Token、输出 10 USD / 百万 Token。本地估算按普通输入/输出价格计算，不计缓存读折扣、缓存写费用或账户优惠。测试仍通过当前 OpenAI 兼容适配器执行，结果只说明指定端点的兼容性，不证明模型身份或研究质量。

2026-10-06 真实测试：两款 Claude 5.5 首次均调用了工具，但最终输出在 SDK 结构校验时出现 `ModelBehaviorError`。测试脚本补充明确的 JSON 格式及字段定义后，两款均通过随机工具值与结构化结果的一致性检查。该结果证明“明确格式提示 + 本地校验”链路可用，尚不能确认网关是否强制执行 `response_format=json_schema`。首次失败与复测共 8 次请求，按登记价格估算 0.014390 USD；不等于实际账单。每款只验证一个合成任务，没有评估财务研究质量或长期稳定性。

## 资料清单与恢复方式

路径均相对仓库根目录。恢复已有文件时保留原字节、版本目录、清单和审核记录，不重新赋予 frozen/adopted 状态。

| 内容 | 路径 | 用途与恢复方式 |
| --- | --- | --- |
| 原公司名单 | `data/company_universe/v0.1-candidate/companies.json` | 公司导航与报告审核必需；从原环境恢复，沿用原公司集合 |
| 材料目录 | `data/document_library/alphabet/catalog.json`，以及可选 `earnings.json` | Alphabet 所有正式子页都会加载；目录中的相对路径须保持可解析 |
| 已发布研究数据 | `data/research_data/alphabet_2025_10k/v0.2-candidate/` | 业务图、指标和公司页面必需；恢复 `manifest.json`、`evidence_bundle.json`、`business_map.json` 及清单声明的全部文件，例如 `query.json` |
| 完整年报及图片 | `data/source_documents/alphabet_2025_10k/source.html.gz`、`assets/` | 原文阅读、索引重建及独立验证；解压后的 HTML 须匹配现有来源清单 SHA-256 |
| 版本化索引 | 上述来源目录的 `indexes/`，以及材料目录各条记录指向的 `index_folder` | 目录导航和精确证据链接；保持 `manifest.json`、`index.json`、`blocks.jsonl`、`assets.json` 及引用图片一致 |
| 候选与审核决定 | `benchmarks/alphabet_2025_business_map/v0.2-candidate/`、`v0.3-candidate/` | 后续研究数据构建需要对应候选及 `review_decisions.json`；已提交的 v0.1 不能代替这些版本 |
| 历史报告及读取轨迹 | `experiments/analysis_comparison/`、`experiments/document_reader/` 及相应 Cloud 实验目录 | 恢复原报告、成本、校验与精确引用；没有实验时允许空报告列表，但历史回归不能据此通过 |
| PDF 资料 | `data/reading_library/alphabet/download_manifest.json` 及声明 downloaded 的文件 | 可选阅读功能；保持清单中的相对文件路径 |
| 个人审核历史 | `data/research_archive/state.json` | 可选；只从可信原状态恢复。没有该文件可以开始新的空档案，但无法据此还原过去的修订、采纳或撤回 |

建议先将原工作区恢复到单独目录，用 `check_workspace.py --root ... --json` 检查和比对；再按文件清单补齐当前工作区中缺失的路径。若同一路径已有不同字节，先核对版本和来源，保留两份以待审查。凭证不属于资料恢复包，模型执行前另行配置。

恢复后从运行结果进入已登记产物，明确选择公司、数据集和材料，核对原件、财务候选与证据。历史公司报告保留显式 `/companies/<company>/reports` 地址。真实人工采纳仍由研究者执行；离线演练的模拟采纳不会被导入。

## 历史恢复边界（2026-09-18 记录）

以下记录当时缺失输入带来的限制；部分输入现已提交，当前是否具备构建条件须检查实际文件及其指纹。已存在的产物不可覆盖，新构建使用显式配置和新目录。

- `build_alphabet_business_benchmark_v0_2.py` 可从已提交的 v0.1 候选生成后续候选文件，但不产生人工审核决定。
- `build_business_map_v03_candidate.py` 需要缺失的 v0.2 `review_decisions.json`。不能用空决定文件声称已还原原审核。
- `build_research_data_bundle.py` 需要 v0.3 候选和原 `indexes/v0.1/manifest.json`。当前公开文件不足以重建既有 v0.2 EvidenceBundle。
- `build_document_index.py` 需要完整、指纹一致的源 HTML 及图片。取得原始字节后可在**新的候选目录**重建索引；新构建不能冒充过去已审核的冻结版本。
- 公司名单、历史工具轨迹、模型输出和人的采纳意见不能从年报重新推导为原记录。资料找不回时，需要另行建立有明确来源的新研究版本。

## 已知证据完整性缺口

已提交摘录的第 **90** 段，其当前文本按项目 `sec.text_hash` 规则计算的指纹，与存储指纹不一致：

```text
stored:     2e86b1ceb5f574619bc1b27515bb8ac52df965b71257bae7dd0834bdf5ce9cc4
recomputed: 113296d3ee15d4cdb5ef858a780812ac2f8e7bafcd68608ae3cdd88d13e62cba
```

相关证据为 `e-platforms`，涉及 `spd-composition`、`spd-platforms`。尚未取得完整固定源文件，因此这次没有修改原文、摘录或指纹。恢复原资料后，应核对到底是文本、指纹还是版本混用问题，并通过新候选及复核解决。

默认 smoke 只验证明确选定的 `alphabet-definition → e-overview → paragraph 55`，并同时输出全集指纹缺口。检查全部候选链可运行：

```bash
.venv/bin/python scripts/smoke_research_workflow.py --strict-all
```

当前该命令因第 90 段问题返回 **1**；这个失败应保留。默认模式成功仅表示所选局部证据和临时存储的生命周期检查通过。

## 尚未随仓库发布的设计文档

旧 README 提及下列六组文档，每组均包含英文 `.md` 与中文 `.zh-CN.md` 两份。目前均未提供；应恢复原文件，再核对其批准状态和当前适用范围：

- `M1_10K_THESIS_SCOPE`
- `DATA_ANALYSIS_AGENT_CONTRACT`
- `GOOGLE_CLOUD_SPIKE`
- `CLOUD_ANALYSIS_A0`
- `CLOUD_ANALYSIS_A1`
- `GOOGLE_CLOUD_LLM_SPIKE`

旧 README 对 M1 与交接契约只直接链接了中文版本，因此共有十个失效链接。此清单记录缺失事实，不重建或代替原设计决定。


## 四路径真实接入的运行与复核（2026-10-15）

用户随后明确批准本批累计 $3 / 80 请求、每路 20 次。已在原账本应用一次追加授权，旧 33 个请求及费用逐项未变；新运行入口使用 `output/data-agent-live-20261015/extended-batch.json`。该 manifest 的四个上下文属于新执行，旧结果保留在旧 manifest 中，累计账本相同。查看最新运行：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-live-20261015/extended-batch.json
```

追加额度使用 `extend-allowance --manifest <原 manifest> --authorization <显式用户决定 JSON> --output <新 manifest>`；没有授权不能调用。该入口已执行，无需重做；中断后用同一授权 ID 恢复，不能更换 ID 重置累计或解除取消。此次授权文件为 `continuation-fix/allowance-authorization.json`（相对本批输出目录）。正常运行仍用 `run --manifest <新 manifest> --lane <原 lane> --work <尚不存在的私密目录> --env-file .env`；已有运行目录拒绝覆盖。行为检查命令为 `python -I -m unittest discover -s tests/integration/data_platform_agent -p test_gateway_extension.py -v`，使用合成数据、不调用真实模型。

**本地请求字节上限修正：**实际 A/C 执行曾因累计工具历史超过项目的 200,000 字节上限而在发送前失败，这不是供应商网络错误。`prepare-attempt` 现支持显式 `--max-request-bytes 512000`，只登记新执行的请求字节上限及按原价格计算的保守单次预留上界；原请求、业务输入、prompt、路由、输出限制、累计金额/次数及取消状态保持。每次请求仍按真实请求大小预留，余额不足即停止。扩大此项不意味着模型上下文无限，也不保证余下次数足以完成业务。新 manifest 不覆盖旧文件。

已登记的 C/D 修正版本分别为 `C-luna-openai/request-bound-manifest.json` 和 `D-sonnet-openai/request-bound-manifest.json`（相对本批输出目录）；对应运行结果位于同 lane 的 `request-bound-run/`。C 已达到累计 20 次，不得照示例再跑。先执行上方 `inspect` 查看原账本；不要仅凭新的 `--work` 目录判断还有额度。

本轮已停止重复调用，四路未完成完整验收。最新累计 A/B/C/D＝20/17/20/16；已报告收费 $1.26415393、未核账预留 $1.4361136，可用 $0.29973247。D 最新交付仍是 partial、计算为空；不能仅凭命令完成、JSON 存在或 native_success=true 记业务通过。结果、原文独立核验、安装包 hash 和剩余项汇总在 `continuation-fix/extended-verification.json`。

`inspect` 的次数/费用是原账本累计，`session_status`/`session_requests` 则属于传入 manifest 绑定的会话，不会自动跳到另一 manifest 的新执行。查看 C/D 最新会话时分别将 `--manifest` 换成 `C-luna-openai/request-bound-manifest.json` / `D-sonnet-openai/request-bound-manifest.json` 的完整路径；旧 manifest 保留历史含义。

记录查询必须使用 schema 返回的完整 `{namespace}local-name`，不能把 `prefix:name` 的零匹配当作原件缺数据。`select.fields` 的可选字段已写入工具 schema，非法字段返回具体名称与允许列表；`period`、`locator` 是嵌套字段，不能自造 `entity_scope`、`source_locator`。这些修正不填入任何样本答案。Claude SDK 合成 API 错误现在保留其 `error` 及已知本地拒绝码，不再误报为主会话身份缺失；原失败记录不改写。

以下保留追加授权前的停止位置及旧命令说明。

最新恢复执行已新增 A 5 次、D 2 次真实请求，均未完成计算/交付；A/B/C 累计各 10 次，D 累计 3 次，原 $1 额度剩余 $0.16029964，不足以覆盖 D 下一请求的保守预留。A/B/C 次数也已耗尽，以下运行命令不能作为重新获得额度的方式。当前结果与逐请求费用见 `output/data-agent-live-20261015/continuation-fix/resume-verification.json`。只读查看当前 A/D 新会话：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-live-20261015/A-deepseek-openai/tool-contract-manifest.json

output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-live-20261015/D-sonnet-openai/tool-contract-manifest.json
```

各 manifest 的对应 lane 指向最新会话，其他 lane 仍是原冻结会话；累计费用和次数均来自同一原账本。结果分别在对应目录的 `tool-contract-run/result.json`，原始请求/响应证据为 `tool-contract-run/evidence.json`。两路均未进入 search_asset，本轮分页能力仍只有离线验证。

本轮工具契约/搜索预算修复可先用合成数据验证，不读取凭据、不调用模型：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I -m unittest discover \
  -s tests/unit/data_platform -p test_tool_contract_feedback.py -v
```

覆盖计划失败后的准确反馈、筛选错误、历史截止日不放宽、搜索按字节分页、依赖不拆分和游标继续/过期。原真实参数的离线重放记录见 `output/data-agent-live-20261015/continuation-fix/tool-contract-replay-final.json`，复核脚本在同目录 `replay_tool_contract.py`（使用临时完整副本，不改原账本；已有输出拒绝覆盖）。两套实际 SDK 各完成一条本机合成工具/计算/交付链，真实模型理解新说明的效果仍未验证。原次数与总预算保持。

入口是 `examples/data_platform/live_function.py`，安装包来自主锁 `data + agent`。本批旧实跑 SDK 为 Agents 0.22.2 / openai 3.13.0 / Claude SDK 0.2.166；主环境已升级，**读取结果不要求旧 SDK，恢复旧原生会话则必须匹配原冻结版本**。当前 profile 与旧批次不匹配时运行应拒绝，不通过改 batch.json 继续。配置 key 不能代替调用授权；不自动复跑已失败路径、重建预算或将原额度授予另一个批次。

用户已确认后续使用当前主锁版本（Agents 0.24.0 / openai 3.31.0 / Claude SDK 0.2.167），以新会话启动，不做旧 SDK 会话的跨版本恢复。上面的匹配要求是本项目当前冻结绑定的校验，不是已证实的官方 SDK 兼容性限制。现有 `prepare-attempt` 可为原 lane 登记当前 profile 的新会话，沿用同一账本与原次数；只有已确认的 SDK 版本、parallel_tool_calls、mcp_max_result_chars 可变，模型、路由、prompt、业务输入及限额保持。新会话结果中的 `real_model_calls` 是该会话的请求数，`runtime.control_scope` 和 `runtime.budget` 仍显示原 lane/整批累计。

本批已准备好 Luna 的 `output/data-agent-live-20261015/C-luna-openai/current-sdk-manifest.json`。以下展示创建方式（该输出已存在，无需重建；已有文件会被拒绝覆盖）：

```bash
.venv/bin/python -I examples/data_platform/live_function.py prepare-attempt \
  --manifest output/data-agent-live-20261015/batch.json --lane C-luna-openai \
  --attempt-key a0a41db1-93a3-46b7-ab8e-e2d866dc0dad:C-luna-openai:current-sdk \
  --output output/data-agent-live-20261015/C-luna-openai/current-sdk-manifest.json
```

准备过程无需凭据、不调用模型、不创建账本。明确使用同一 attempt-key 可返回同一登记，但不能通过换 key 重置次数或停止状态。查看已准备会话：

```bash
.venv/bin/python -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-live-20261015/C-luna-openai/current-sdk-manifest.json
```

真正执行仍通过 `run --manifest <新 manifest> --lane C-luna-openai --work <新的私密运行目录> --env-file .env`。用户已于 2026-10-15 明确放行两笔完整 404 的未核账费用：保留全部 $0.0921616 预留，在原额度/次数内继续。已通过 `retain-reservation --manifest <manifest> --lane <lane> --request-key <已完整响应的请求> --confirmation <已有用户决定>` 写入原账本，无需再次确认或执行。该入口不查询账单、不发模型请求，只把指定响应记为已确认保留预留；实际收费仍未核实，不释放资金、不重发旧请求。未来新增未知账单及不完整响应不会被这次记录自动放行。原预算和次数不因更换 manifest 清零，B 的停止状态也不解除。新会话本地合成闭环及必要边界可用以下命令复核（需允许本机监听）：

```bash
.venv/bin/python -I -m unittest discover -s tests/integration/data_platform_agent -p test_gateway_attempt.py -v
```

先阅读现有结果（无模型调用、无需凭据）：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-live-20261015/batch.json
```

如使用自己的主开发环境，把上方 Python 替换为 `.venv/bin/python`。本机 `output/.../sdk-env` 是本轮复用的验收环境，并非产品安装目录要求。最新原子能力复核见 `output/data-agent-live-20261015/continuation-fix/capability-audit.json`，推理回传修复见同目录 `verification.json`；原 `verification-final.json` / `inspection-final.json` 保留初次实跑状态。状态分开显示业务结果与宿主 session 状态，Claude 的宿主 completed 不等于业务完成。最新累计 26 POST：A/B/C/D 分别为 5/10/10/1。Luna 当前 SDK 新会话新增 6 次均 HTTP 200，响应费用 $0.00783161；因工具参数错误消耗前 4 轮，随后成功执行 find_assets（partial）及 get_asset_schema（ok），到原次数上限停止，未产生计算或交付。结果在 `C-luna-openai/current-sdk-run/result.json`，请求和工具记录在同目录 `evidence.json`；查看该会话用上方新 manifest，旧 manifest 仍只显示旧会话业务结果和最新累计费用。无需重跑模型。

以下仅保留四条路径的原启动命令形式，**不是当前可直接续跑的命令**：A/B/C 已有终态，B 次数耗尽；D 仅完成另行授权的单请求诊断。当前 SDK/profile 与原批次不同，旧 `--work` 目录也已存在。新版新会话使用上方 `prepare-attempt` 入口，并继续服从原账本准入；不能删除目录或改旧 manifest 强行重跑。`--work` 是显式私密运行目录；`.env` 在本地配置 `DEEPSEEK_API_KEY` / `OPENROUTER_API_KEY`，不在命令行传密钥值。

```bash
.venv/bin/python -I examples/data_platform/live_function.py run --manifest output/data-agent-live-20261015/batch.json --lane A-deepseek-openai --work output/data-agent-live-20261015/A-deepseek-openai --env-file .env
.venv/bin/python -I examples/data_platform/live_function.py run --manifest output/data-agent-live-20261015/batch.json --lane B-deepseek-claude --work output/data-agent-live-20261015/B-deepseek-claude --env-file .env
.venv/bin/python -I examples/data_platform/live_function.py run --manifest output/data-agent-live-20261015/batch.json --lane C-luna-openai --work output/data-agent-live-20261015/C-luna-openai --env-file .env
.venv/bin/python -I examples/data_platform/live_function.py run --manifest output/data-agent-live-20261015/batch.json --lane D-sonnet-openai --work output/data-agent-live-20261015/D-sonnet-openai --env-file .env
```

`prepare` 只为已有明确授权的批次冻结业务 context/profile/限额并复制指定数据根一次；不能用它绕过旧批次的未知费用或请求上限。本批配置、原件和账本已经准备，不再初始化另一份。`reconcile` 只查询既有 OpenRouter 请求的账单，沿用原每请求最多两次观察上限，不发模型 POST；原 404 请求已耗尽两次观察且仍未知，不能继续轮询或记作 0 费用。下方只保留核费入口形式，不是当前重试建议；执行时需原批次 manifest、lane 和一个尚不存在的输出路径：

```bash
.venv/bin/python -I examples/data_platform/live_function.py reconcile --manifest output/data-agent-live-20261015/batch.json --lane C-luna-openai --env-file .env --output output/data-agent-live-20261015/C-luna-openai/billing-observations-next.json
```

最新 SDK 的原生请求捕获仍可在本机验证（合成响应、真实模型调用 0，Claude 用临时隔离配置和回环服务）：

```bash
.venv/bin/python -I -m unittest discover -s tests/integration/data_platform_agent -p test_live_capture.py -v
```

不含项目适配的官方 Chat adapter 仍可用保留的两轮探针复现字段丢失；它不经过 `GatewayOpenAIModel`，因此仍失败不能证明项目修复失效。输出路径须尚不存在，字段未原样保留时退出码 1：

```bash
.venv/bin/python -I output/data-agent-live-20261015/check_reasoning_compatibility.py \
  output/data-agent-live-20261015/openrouter-reasoning-compatibility.json \
  output/data-agent-live-20261015/openrouter-reasoning-review.json
```

项目网关的原样回传及持久恢复已用下面的本机检查验证；包含 3 个实际进程退出位置，连接本机合成服务，真实模型调用为 0：

```bash
.venv/bin/python -I -m unittest discover -s tests/integration/data_platform_agent -p test_gateway_openai.py -k observed_exit -v
```

Claude 工具结果转文件阈值现由当前 B profile 的 `mcp_max_result_chars: 200000` 显式设置，经官方 `ToolAnnotations(maxResultSizeChars=...)` 传给 CLI。未设置的旧 profile 保持默认行为及原身份。这个单位是字符，与整请求的 200,000 字节限制不同；也不增加真实调用次数或费用额度。可在已按本说明安装当前源码的主环境复核（仅本机合成服务，无真实模型调用）：

```bash
.venv/bin/python -I -m unittest discover -s tests/integration/data_platform_agent -p test_claude_mcp_output.py -v
```

需要允许监听 `127.0.0.1`。测试覆盖默认转存、配置后完整回传、超限仍转存，以及旧 profile 身份/配置校验；fixture 单独处理 CLI 的 `/v1/messages/count_tokens` 辅助端点，不把计数响应当成推理回合。当前验证见 `output/data-agent-live-20261015/continuation-fix/claude-inline-verification.json`，原失败日志保留。真实 B 路径仍因原 10 次上限停止，未用新配置追加调用。

探针和示例测试证明的是指定 SDK 的序列化/本地功能，不证明真实模型完成了问题。当前四路径无完整业务通过，详情与费用见核心设计 14.17.11；版本核对依据为 [Agents SDK 0.24.0](https://github.com/openai/openai-agents-python/releases/tag/v0.24.0)、[openai 3.31.0](https://github.com/openai/openai-python/releases/tag/v3.31.0)、[Claude Agent SDK 0.2.167](https://github.com/anthropics/claude-agent-sdk-python/releases/tag/v0.2.167)。


## 配置化 Skill 获取与限定离线验证

加载器不调用模型、不启动 SDK，不读取密钥。配置根目录、Skill、模型和 SDK 均由调用方明确提供；输出包含公共正文、选中的指导和共用资源。模型版本未知时可省略，按明确的默认规则选择，不猜具体快照。模型×SDK 指导当前标为 unverified。

在已普通安装当前源码的环境中，可直接查看完整正文：

```bash
.venv/bin/python -I examples/data_platform/skill.py \
  --config-root config/data_platform --name financial-data-query \
  --model deepseek-flash --sdk openai --sdk-version 0.24.0
```

如需生成文件，加 `--output /absolute/path/to/new-skill-directory`；目标必须是新的绝对目录，重复运行不会覆盖旧包。SDK 版本参数用于选择指导，不会安装或切换 SDK。程序接口为 `from uteki.data_platform.agent.skills import get_skill`；返回 `content`、`files`、`selection`、`sha256`，通过 `write_to()` 输出 SDK 可加载的标准目录。源码入口见 [skills.py](../src/uteki/data_platform/agent/skills.py)，配置见 [mapping.json](../config/data_platform/skills/financial-data-query/mapping.json)。

限定复跑命令（真实模型调用为 0）：

```bash
.venv/bin/python -I tests/unit/data_platform/test_skills.py -v
.venv/bin/python -I tests/integration/data_platform_agent/test_financial_skill.py -v
```

可将 `.venv/bin/python` 换成既有 `output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python`；本批使用该环境普通重装并核对源文件/安装文件一致。SDK 测试需本机回环服务和原生 sandbox 权限，不需要供应商凭据；OpenAI 测试只给生成包和所用 Python 环境添加必要只读路径。测试先用 DataService 合成材料生成交付，再验证两侧动态正文进入输入及只读检查脚本执行，模型响应由脚本提供。这组独立测试不覆盖正式 runtime；自动装配及恢复的后续检查见下节，也不称为真实模型自主业务验收。

可用 Skill 目录由 SDK 原生生成：OpenAI 的 `LocalDirLazySkillSource.list_skill_metadata()` 返回名称、描述和路径，`Skills` 将目录加入模型指令；Claude 从本次项目目录按 `skills` 白名单发现。模型随后分别通过 `load_skill`＋读取文件、`Skill` 工具获取正文。`get_skill` 是宿主的配置组装方法，不是要模型自行调用的工具。本项目未新增 `list_available_skills` FunctionTool。

只复跑这次“发现→加载→执行”验证：

```bash
.venv/bin/python -I tests/integration/data_platform_agent/test_financial_skill.py \
  FinancialSkillTests.test_openai_native_skill_load_read_and_execute \
  FinancialSkillTests.test_claude_native_skill_body_and_script -v
```

这两项会检查首个模型输入的名称/描述、完整正文尚未加载、原生加载后的正文及脚本结果，以及 Claude 未启用 Skill 不出现在目录。模型选择由脚本提供；未验证真实模型能否根据描述自主选择合适的 Skill。

40 条自动选择基线的用例与离线评分入口（当前不会调用模型）：

```bash
.venv/bin/python -I scripts/data_agent/skill_trigger_baseline.py \
  --cases tests/fixtures/data_platform/skill_trigger_queries.json --show
.venv/bin/python -I tests/unit/data_platform/test_skill_trigger_baseline.py -v
```

用例共 30 条预期加载、10 条预期不加载，交错排列；`--show` 包含评测标签，不能将其输出交给被测 Agent。真实请求只接收每条 query。已有原生观察文件可通过 `--observations /absolute/path/to/observations.json` 评分；文件需包含用例 hash、SDK/模型/路由/prompt/Skill 版本及每条 `id/status/selected_skills/loaded_skills`。缺失、请求异常记为 unknown。真实批量采集入口尚未接通，当前不会生成模型基线分数；运行设计见核心文档 14.17.14。


## 正式 runtime 的 Skill 装配与恢复

新增示例配置：`config/data_platform/model-profiles/openai/fixture-skill-query/query.json` 和 `claude/fixture-skill-query/query.json`。每份绑定独立 prompt，配置 `skills: ["financial-data-query"]`；`model_version` 可选。旧配置省略这两个字段时保持原路径和身份。

重新安装当前源码后运行（复用现有环境，无真实模型调用）：

```bash
uv --cache-dir /tmp/uteki-skill-uv-cache pip install --reinstall-package uteki-eval --no-deps . \
  --python output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  tests/integration/data_platform_agent/test_skill_runtime.py -v
```

这组测试从正式 `run_offline` 入口执行：OpenAI 原生 `load_skill → exec_command(cat)`，Claude 原生 `Skill → Read`，随后调用现有 8 次 Data 工具完成取数、代码计算和交付。另检查进程中断恢复、冻结内容不从新模板重建、缺失/修改拒绝、Claude 恢复正文篡改，以及旧 OpenAI 配置兼容。两套原生 SDK 均实际运行，模型响应由脚本提供；这证明接线与恢复行为，不证明真实模型会选择 Skill 或自主完成业务。

OpenAI 原生 Skill 能力属于 SandboxAgent；这里使用本机 `UnixLocalSandboxClient`，不创建远程容器或新虚拟环境。生成目录仅包含本次所选 Skill 的正文和资源；业务查询、计算、交付仍走宿主 DataService。OpenAI Shell 仅可 `cat` 本包文件，Claude 仅开放 Skill 和受控 Read，不因 Skill 中提到脚本而自动开放执行权限。运行中的小型包目录用于稳定恢复，随原运行目录管理；合成测试使用临时目录并清理。

本轮 7 项 runtime 检查全部通过；另有 5 项加载器检查和 1 条旧 Claude 正常链通过。6 个相关安装模块已与源码逐字节核对，旧模型配置与 prompt 未变。

40 条自主选择基线尚未运行；真实批量采集入口及 SDK/模型组合确认仍是独立后续任务，旧四路 goal 未恢复。


补充检查 OpenRouter Chat 协议链（本机合成 HTTP，真实模型调用为 0）：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  tests/integration/data_platform_agent/test_gateway_openai.py \
  GatewaySkillTests \
  GatewayOpenAITests.test_actual_chat_client_and_runner_deliver_from_eight_shared_tool_requests -v
```

该入口实际运行 SandboxAgent、官方 OpenAI Chat 客户端及现有网关；检查原生 Skill function tools、正文回传、路由参数、reasoning_details、进程恢复、越界读取拒绝和旧配置兼容。合成配置只用于测试，不修改真实模型 profile，不需要密钥。正常与恢复链均为 10 次本机 HTTP；`.10` 等费用数值是 fixture，不能作为实际价格估算。此入口不访问 OpenRouter 实际服务，也不替代 40 条真实模型自主选择基线。

### 真实 Skill 配置的追加准备

`config/data_platform/model-profiles/openai/live-C-luna-skill-openai/query.json` 是独立候选配置，保留 Luna/OpenRouter 路由，启用 `financial-data-query`；原 live-C 配置保持历史含义。旧 prompt 曾明确禁止 Skill，不能只在运行时添加工具后直接复跑旧配置。

现有 `extend-allowance` 的授权文件可包含 `profile_revisions`，按 lane 记录 `previous_sha256/current_sha256`（规范 JSON profile 摘要）。仅匹配这两个指纹的 prompt/skills 修订可进入新会话；模型和路由仍不可借此改变。金额允许保持原值、只显式增加次数；旧请求、费用和结果保持，不创建新账本。此前 $3、40/120 次调整未获确认；后续用户另行明确批准累计 $6 和三条各最多新增 30 次的比较，已按下一节应用。不要直接修改旧 manifest 或以新工作目录重置次数。

本次相关行为检查（无真实模型）：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I -m unittest discover \
  -s tests/integration/data_platform_agent -p test_gateway_extension.py -v
```

### 查看三模型真实 Skill 对照（2026-10-16）

比较已完成并停止，不需再次调用模型。查看同一原账本和实际结果（以下命令不发出推理请求）：

```bash
output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-skill-20261016/comparison-manifest.json

output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I - <<'PY'
import json
from pathlib import Path
root = Path('output/data-agent-skill-20261016')
for name in ('luna', 'sol', 'sonnet'):
    result = json.loads((root / f'{name}-live/result.json').read_bytes())
    print(name, {key: result[key] for key in ('status', 'real_model_calls', 'gateway_cost_usd')})
    print('结果：', root / f'{name}-live/result.json')
audit = json.loads((root / 'configured-verification.json').read_bytes())['model_comparison']
for result in audit['results']:
    print(result['model'], result['skill'], result['source_audit']['gap'])
PY
```

真实调用为 Luna 15、Sol 12、Sonnet 12 次；程序 completed/partial 不等于独立业务验收通过，已核验的 Skill 暴露、错误轮次、用量、原件检查和缺口见 `configured-verification.json.model_comparison`。没有重置原 73 次请求或旧费用。具体诊断见核心设计 14.17.13 第 9 项。

本轮扩展复用 `extend-allowance --add-scopes <JSON>`；数组项为 `scope_id/source_scope_id/entry`，entry 使用现有 profile、limits、transport、pricing 格式，授权绑定展开配置的 `additional_scopes_sha256` 和明确的新 scope/次数。新模型使用独立 scope，继承原问题及材料，与旧路共用累计账本；不是修改原 lane 的模型。此次已执行，授权和 manifest 为本机私密证据，不重复初始化或再次追加额度。运行目录和审计文件含私密会话/机器路径，不纳入公开提交。

### 通用 Harness 修复的离线验收

2026-10-16：合法 workdir 的 Skill 读取和新资产/schema 元数据进展已修复。以下使用普通安装后的包、临时合成材料和脚本模型，无需 API Key，不调用真实模型：

```bash
uv --cache-dir /tmp/uteki-skill-uv-cache pip install --offline --reinstall-package uteki-eval --no-deps . \
  --python output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python

output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  tests/unit/data_platform/test_queries.py \
  DataToolTests.test_schema_pagination_progress_survives_reopen_and_legacy_history \
  DataToolTests.test_metadata_reordering_and_new_query_do_not_manufacture_progress \
  DataToolTests.test_metadata_history_commits_with_response_and_idempotent_replay \
  DataToolTests.test_no_progress_limit_counts_same_evidence_despite_new_references \
  DataToolTests.test_repeated_rebuild_without_new_material_is_not_new_progress -v

output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  tests/integration/data_platform_agent/test_skill_runtime.py \
  SkillRuntimeTests.test_openai_explicit_workspace_reads_body_and_completes_business \
  SkillRuntimeTests.test_skill_workdir_is_same_directory_and_never_a_symlink_or_subdirectory \
  SkillRuntimeTests.test_snapshot_resume_ignores_changed_sources_and_rejects_bad_files \
  SkillRuntimeTests.test_openai_process_resume_keeps_skill_and_exact_native_results \
  SkillRuntimeTests.test_openai_denied_and_truncated_reads_do_not_report_full_body \
  SkillRuntimeTests.test_claude_discovery_loading_read_and_business_delivery -v

output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python -I \
  tests/integration/data_platform_agent/test_gateway_openai.py \
  GatewaySkillTests.test_native_file_read_denial_returns_to_model_without_exposing_other_files -v
```

本机 SDK 验收需要系统允许 `sandbox-exec`、读取启动时钟及回环监听；外层执行沙盒拒绝时不能记作测试通过，也不通过关闭 SDK Sandbox 绕过。上述 12 项已在允许这些本机能力后通过。程序状态、完整正文返回、后续模型输入确含正文分别检查；对照案例及原件位置见核心设计 14.17.13 第 9 项，修复证据见第 10 项和 `configured-verification.json.harness_fix`。

## 文档解析结果的查询存储

新入口接收已生成的规范解析结果，存入 SQLite 并复用不可变对象库。原件、图片和冻结解析包在显式 `data_root/objects/`，查询表在 `data_root/documents.sqlite`；不默认使用 output，不依赖旧 catalog 或 SDK 会话。正式数据根由调用方指定并持久保存，下面只用临时合成数据演示，无网络和模型费用。

从仓库根执行（也可将 `document_python` 换为按本文安装好的主环境 Python）：

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
uv --cache-dir /tmp/uteki-skill-uv-cache pip install --offline --reinstall-package uteki-eval --no-deps . \
  --python "$document_python"

document_data_root=$(mktemp -d /private/tmp/uteki-documents.XXXXXX)
"$document_python" -I examples/data_platform/documents.py --data-root "$document_data_root"

"$document_python" -I -m uteki.data_platform.documents --data-root "$document_data_root" \
  schema --parse-id demo-parse-v1

"$document_python" -I tests/unit/data_platform/test_documents.py -v
```

示例返回 1 篇合成材料、5 个块（3 文本、1 表格、1 图片），按「经营情况」子树＋收入/地区标签交集定位表格，并读出标题、脚注。`source_bytes_match` 和 `old_reference_after_reopen` 应为 true，`model_calls` 为 0。再次对同一目录运行同一示例返回 `publication.reused=true`，不会新增解析版本。OCR 与图片描述由 fixture 填入，不是识别结果；目前没有接入 OCR 服务提供方。

可直接操作现有库的 CLI 命令为 `find/schema/browse/query/read/export/reindex`；新库须显式 `init`，原件或图片用 `put-object --file` 取得对象引用，再通过 `publish --package` 提交规范解析 JSON。`--data-root` 必须是已存在的绝对目录。`--no-default` 可发布但不设为材料默认版本；精确版本读取始终用 parse_id。`export --parse-id` 输出规范包，`reindex --parse-id` 从冻结包显式重建查询索引，不运行解析器。

例如将以下查询保存到任意 JSON 文件，用 `query --request /absolute/path/query.json` 运行：

```json
{
  "parse_id": "demo-parse-v1",
  "directory_path": ["经营情况"],
  "include_descendants": true,
  "tags": ["finance.revenue", "business.region"],
  "tag_match": "all",
  "types": ["table"]
}
```

结果中的 `items[0].ref` 可原样存为 JSON，交给 `read --reference /absolute/path/ref.json`，返回块正文/表格、位置和明确的上下文。有 `next_cursor` 时保持查询 JSON 不变，以 `--cursor` 续页；更改查询或版本会拒绝旧游标。Python 使用 `DocumentStore.open(root)`、`BlockQuery`、`BlockRef` 同一套方法；`read_source(parse_id)` 和 `read_resource(ref, resource_id)` 读取并校验实际字节。缺失、损坏、同名目录歧义和版本冲突不会降级为成功。

本轮 14 项行为测试及上述 CLI 正常链已通过，6 个新安装模块已与当前源码逐字节核对。没有设置 PYTHONPATH 或注入 sys.path。旧 Agent runtime 仍走原 DataService，本入口不代表 PDF/OCR、真实自动打标或 Agent 业务验收已完成；详情见核心设计 14.18。


## 真实 PDF 本地解析与数据库查看

解析入口：`python -m uteki.data_platform.documents.pdf`。标准主环境可用 `uv sync --locked --extra data --extra pdf` 安装；已有环境使用相同锁定的 pdf 可选依赖，并从源码重装项目。首次需显式下载本地模型，转换本身不调用收费 API：

```python
from pathlib import Path
from docling.utils.model_downloader import download_models
model_root = Path("data/model_cache/docling").resolve()
model_root.mkdir(parents=True, exist_ok=True)
download_models(output_dir=model_root, with_layout=True, with_tableformer=True,
                with_code_formula=False, with_picture_classifier=False,
                with_rapidocr=True, rapidocr_models=["onnxruntime:en"], progress=True)
```

此前已运行的材料为 **Alphabet 2024 Q4 业绩稿，并非 Apple 10-K**。原件、元数据与数据库均已在本机。以下读取冻结版本，不运行解析；新版适配器的 recipe 已变化，不能用旧 parse_id 重跑新解析：

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m uteki.data_platform.documents \
  --data-root "$PWD/data/data_agent_documents" \
  schema --parse-id alphabet-2024-q4-docling-auto-v1
```

新库先创建明确的目录，再执行已有 `documents --data-root /absolute/root init`；材料 JSON 遵守 Material 契约，不能以本例公司/日期为默认。`--ocr-mode full_page` 强制 OCR，必须使用另一 parse_id；`--no-default` 保留已有默认版本。当前只声明 en 支持，缺少本地权重明确失败。SourceVersion 的取得时间是本次本地导入事件；原下载时间未知时不能由文件 mtime 补造。

使用独立轻量工具环境，不修改项目 SDK 的依赖：

```bash
UV_TOOL_DIR=/tmp/uteki-viewer-tools uv --cache-dir /tmp/uteki-skill-uv-cache \
  tool run --from datasette==0.65.5 datasette serve \
  data/data_agent_documents/documents.sqlite \
  --host 127.0.0.1 --port 8001 --metadata data/data_agent_documents/viewer.json
```

若 8001 已在运行则直接打开，不重复启动。材料、目录、正文/表格与单元格分别见 `http://127.0.0.1:8001/documents/inspect_materials`、`inspect_directory`、`inspect_blocks`、`inspect_table_cells`。用 parse_id 筛选版本；本次默认版是 `alphabet-2024-q4-docling-auto-v1`，OCR 对照是 `alphabet-2024-q4-docling-v1`。首表 block_id=tables-0；概览 content_preview 展示行文本，精确合并/行列/位置见 cells。目录与块显示 material_name，避免不同材料混看；directory_paths 是关联的完整标题路径数组。block_relations 当前为空，表示语义关联未生成，不能据此判断正文为空。

数据在 `data/data_agent_documents/documents.sqlite` 与 `objects/`；可审阅导出 `normalized-auto.json`、`docling-auto.json`，强制 OCR 初次输出保留 `docling-real.json/md`。本地模型权重在 `data/model_cache/docling`。普通 find/schema/query/read 和数据库浏览不重新运行解析器。业务标签、语义描述、正文小标题层级及 Apple 原案例目录仍未验收；目前不代表完整 Data Agent 已接通。


## 带书签 10-K 的小节与过滤视图（2026-10-17）

当前已真实运行 Apple 2025 的物理页 4–5、11–12、32–33，以及 Alphabet 2025 的物理页 4–7；均为完整原件的选定页范围，不是全文验收。原件、Docling 输出、规范包在现有 `data/data_agent_documents/objects/`，查询在同一 SQLite；新增版本未设为默认。选定页有原生文字，本轮运行本地布局/表格模型，OCR auto 未产生 OCR 文字，远程付费调用为 0。不要把这些结果称为扫描件 OCR 验收。

直接查看 `data/data_agent_documents/reviews/` 下各版本的 `sections.md`（目录、完整小节、表格、过滤记录）及 `schema.json` / `package.json`（实际结构、每块位置和不可变引用）：

| parse_id | 处理页 | review 内容 |
|---|---|---|
| `apple-2025-business-sections-v1` | 4–5 | Products / Services 及其正文小标题 |
| `apple-2025-risks-sections-v1` | 11–12 | Business Risks 下的长标题与各自段落 |
| `alphabet-2025-business-sections-v2` | 4–7 | Google Services 子层级、两处跨页小节、普通强调列表 |
| `apple-2025-financial-sections-v3` | 32–33 | 两张报表、标题、单位、附注与页脚 |

查询已有解析结果，不需要导入 Docling 或重新推理：

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m uteki.data_platform.documents --data-root "$PWD/data/data_agent_documents" \
  section --parse-id apple-2025-business-sections-v1 \
  --code-path PART_I.Business.Services.AppleCare

"$document_python" -I examples/data_platform/pdf_sections.py \
  --data-root "$PWD/data/data_agent_documents" \
  --parse-id alphabet-2025-business-sections-v2 \
  --export-dir "$PWD/data/data_agent_documents/reviews/alphabet-2025-business-sections-v2"
```

`section` 的默认正文视图排除已记录的 header/footer，并聚合后代；`--direct-only` 只读当前节点直接内容。`--content-view all` 读取该目录中全部已登记块；噪声可能没有目录归属，查看全部噪声请使用导出的过滤记录或无目录限制的 `query`，精确 `read` 引用也始终能取回。`BlockQuery.content_view` 为兼容旧调用默认 `all`，正文搜索须显式传 `body`；旧 document-v1 请求 body 时返回 `FILTER_NOT_AVAILABLE`，不伪装已有过滤政策。路径只能在指定 parse_id 中解释；同名标题可用节点 ID 区分。旧包不补写新字段，旧引用可读。

`section` 返回完整的已登记小节块，超过字节上限报错，不截断为成功；`truncated=false` 仅指响应未截断，`source_completeness=not_verified` 和 partial 页范围仍须保留，不能解释成源文档完整。`text` 是文本块的段落拼接，表格结构在 `blocks[].block.table`，图片在资源引用；Markdown 只作审阅视图。

再次解析自己的 PDF 时使用现有 `documents.pdf` 入口并提供原件、材料 JSON、model-root、source-version-id 与新的 parse-id；`--page-start N --page-end M` 必须成对传入，指物理页，原件字节仍完整存储。相同 ID/原件/recipe 才能返回 reused；页范围或解析策略变化必须新版本，不覆盖旧包。当前策略版本为 `pdf-sections-4`、适配器版本为 `3`，此前观察记录继续保留。

全文审阅版本为 `apple-2025-full-sections-v2`（80 页）与 `alphabet-2025-full-sections-v2`（99 页）。现有 section / 导出命令换用这两个 parse-id 即可，不需重新解析；`data/data_agent_documents/reviews/<parse_id>/sections.md` 已包含目录、正文、表格和待核对目录，schema.json / package.json 保存实际结构。两版均为 partial、未设默认；Alphabet 第 99 页失败签字表以明确错误和原页截图展示，不能当作已恢复结构化表格。

限定测试：

```bash
"$document_python" -I tests/unit/data_platform/test_pdf_sections.py -v
"$document_python" -I tests/unit/data_platform/test_documents.py -v
```

本批 4 项小节/兼容边界与 16 项存储测试通过；真实原文检查、已知缺口与停止点见核心设计 14.18.2 第十二部分。全文、纸面目录页识别、无书签材料、扫描件、复杂合订材料与模型消歧没有因此完成。


## 原生目录与 passages（2026-10-19）

新版本使用 `document-v3`、适配器 `4`、策略 `pdf-native-passages-1`。只以 PDF 原生书签建立目录，主题句及其连续说明组成平面 passages；旧 document-v1/v2 保持原样。当前两份输入不变，发布为 `apple-2025-native-passages-v1` / `alphabet-2025-native-passages-v1`，不切默认版本。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m uteki.data_platform.documents \
  --data-root "$PWD/data/data_agent_documents" passage \
  --parse-id apple-2025-native-passages-v1 \
  --path 'PART_I.Risk_Factors.Business_Risks.passages[0]'
```

改成 `passages[1]` 读取第二条风险及其全部说明。命令返回原文、成员 blocks、文字行位置、表格结构和版本引用；索引只在指定章节/解析版本内有效。也可使用 `--passage-id` 读取冻结组 ID。Python 用 `store.list_passages(parse_id, code_path=...)` 列出该章节的组，用 `store.read_passage(parse_id, path=...)` 或 `passage_id=...` 读取；无分组的旧版本明确返回 PASSAGES_NOT_AVAILABLE。

`section --parse-id ... --code-path ...` 仍可读取整个章节及子章节，新版增加 passages 元数据；每个组的 block_ids 引用原始块，不用字符长度或页边界切组。`text_lines[].char_range` 是 block.text 内 Unicode 字符下标（左闭右开），源行与正文无法唯一对齐时为 null；原文行文字和 PDF 页/矩形仍保留。表格单元格 row/column 为零起始，连同跨度和已观测位置返回。上述引用均须绑定 parse_id，不能跨版本只用数字索引。

使用原 `examples/data_platform/pdf_sections.py` 导出，新版目录中额外有 `passages.json`，包含章节、passage 路径、完整文本、块 ID 和区域；`package.json` 保存含文字行/单元格的完整结构，`sections.md` 仅为便于人阅读的同源视图。读取或导出不重新运行模型。

## 新版文档库的 Agent 交付与只读复核（2026-10-19）

本批复验后停止，四条真实 case 中 C1/C3 通过；OpenAI 与 Claude 的 C2 各累计 24 次后仍未完成数值记录和代码计算。完整范围与核验见核心设计 14.19。沿用既有 SDK 环境，源码变化后按前文安装方式普通重装；不依赖 PYTHONPATH。以下查看和导出均不调用模型。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
document_manifest=output/data-agent-documents-20261019/manifest-requests-v3.json

# 查看每条 case、原累计账本及未核账预留，不请求供应商接口。
"$document_python" -I examples/data_platform/live_function.py inspect \
  --manifest "$document_manifest"

# 已有交付及独立原件核验。
cat output/data-agent-documents-20261019/H-C1-delivery/delivery.md
cat output/data-agent-documents-20261019/J-C3-delivery/delivery.md
"$document_python" -I -m json.tool output/data-agent-documents-20261019/review.json

# 从已保存交付重新导出到一个尚不存在的绝对路径；不重跑 Agent。
"$document_python" -I examples/data_platform/live_function.py export \
  --manifest "$document_manifest" --lane H-C1 \
  --output "$PWD/output/data-agent-documents-20261019/H-C1-delivery-review"

# 合成输入的工程边界检查，不替代真实业务验收。
"$document_python" -I tests/unit/data_platform/test_document_tools.py
```

`delivery.json` 是完整机器交付；`delivery.md` 是同源人读视图；有数值记录时另有 `records.csv`。C1/C3 是文本任务，不生成空 CSV。`manifest.json` 记录导出文件 hash，并作为写入完成标志；已有目录会明确报错，不覆盖旧文件。`engineering-export/` 里的数值产物来自真实原件的宿主指定工具链，仅供工程 review，不能当作 Agent 自主 C2 的结果。

配置入口为 `config/data_platform/model-profiles/{openai,claude}/document-deepseek/query.json`、各自 prompt 和共享 `skills/document-data-query/`。执行契约绑定现有两个解析版本及新问题，原件/解析继续位于 `data/data_agent_documents`，运行证据在 output，不为运行复制解析库。

本次 `manifest-requests-v3.json` 用于查看原累计控制账本；两条新执行的精确 context 分别在 `manifest-I-C2-v2.json`、`manifest-K-C2-v2.json`。失败明细为 `I-C2-v2/{result,evidence}.json`、`K-C2-claude-v2/{result,evidence}.json`，不能从不存在的完整交付导出 CSV。两条路线次数均已用满，不重跑 `run`；已通过 C1/C3 不重跑。

本轮发现 Claude 模型输入混入仓库开发 AGENTS.md，当前未修复。先完成业务指令隔离与原生请求捕获 review，再决定后续真实运行。累计 $12／本批 $6 仍有效，全额预留保留；本次截止状态与未核账金额以 review.json 和 inspect 为准，不把额度余额当业务通过。无付费的原失败回放证据为 `I-C2-tool-replay.json`、`numeric-context-tool-replay.json`、`read-cursor-tool-replay.json`。


## 目录与完整内容组修复的真实结果（2026-10-19）

当前限定结果见核心设计 14.21.2：Flash 两 SDK 原失败 Q1 通过，Luna/Claude 找到正文但引用/状态交付失败。本轮 23 次真实请求已停止；下列命令仅查看保存结果，不调用模型、不重新解析。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python

# 查看完整业务交付；JSON 为机器结果，Markdown 为同源人读视图。
cat output/data-agent-sdk-matrix-20261019/deliveries/MX-Q1-flash-claude-navigation-v1/delivery.md
"$document_python" -I -m json.tool \
  output/data-agent-sdk-matrix-20261019/deliveries/MX-Q1-flash-claude-navigation-v1/delivery.json

# 查看业务核验、失败定位与各 attempt 的轮次/费用/耗时。
"$document_python" -I -m json.tool output/data-agent-sdk-matrix-20261019/business-review.json
"$document_python" -I -m json.tool output/data-agent-sdk-matrix-20261019/execution-metrics.json

# 读取现有运行/累计账本；不发供应商请求。
"$document_python" -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-sdk-matrix-20261019/manifest-navigation-v3.json
```

两份 Flash 交付的精确运行绑定在 `manifest-navigation-v2.json`；Luna 失败运行绑定在 `manifest-navigation-v3.json`，三者均沿用同一原账本。文件名版本并不表示覆盖所有 attempt，不能由 v3 推断 Flash 的 context。Luna 的原路线累计 24 次已尽，不直接重跑 `run`。解析存储仍位于 `data/data_agent_documents`，output 只保存运行、导出及核验证据。

## 公司 symbol 与父目录分页的真实验证（2026-10-19）

用户确认：在 `find_assets` 传 `filters.securities:[{ticker:"AAPL",exchange_mic:"XNAS"}]`，后续 `get_asset_schema/read_evidence` 使用返回的精确 asset_ref。正文读取使用单个 `targets:[{section_path:"PART_I.Risk_Factors",include_descendants:true}]`；保持目标及 context，只续传 next_cursor，不拼子目录路径。

本次真实 Flash × Claude 会话已停止，限定结果见核心设计 14.21.3。四页 107 块正文已进入模型，交付因引用拼接错误被拒绝；额外封面读取和 symbol 发现阻力照实保留。下列命令只查看已有结果，不发模型请求：

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python

# 实际模型已看到的正文；这是核验导出，不是成功业务交付。
cat output/data-agent-subtree-20261019/agent-read-body.md
"$document_python" -I -m json.tool output/data-agent-subtree-20261019/review.json

# 真实工具参数/结果摘要（含 find_assets、四次同父路径读取及失败 deliver）。
"$document_python" -I -m json.tool output/data-agent-subtree-20261019/agent-call-trace.json

# 读取本次会话和原累计账本，不重新运行。
"$document_python" -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-subtree-20261019/manifest.json
```

`agent-read-body.json` 保留实际读取响应、目录和逐块出处。解析库仍为原 `data/data_agent_documents`，没有为本次调用重新解析。12 次本轮上限已满，不直接重复 run；下一批修复和真实复验须保持旧失败/费用及显式范围。


## 父目录同题四路结果查看（2026-10-19）

四路已运行结束；当前只读下面的保存结果，不会调用模型。正文均为四页 107 块，三路最终 partial 的具体原因及严格路径偏差见核心设计 14.21.4，不以导出成功代替业务状态。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m json.tool output/data-agent-subtree-compare-20261019/review.json
cat output/data-agent-subtree-compare-20261019/deliveries/SUBTREE2-sonnet-claude/delivery.md
"$document_python" -I -m json.tool output/data-agent-subtree-compare-20261019/runs/SUBTREE2-sonnet-claude/call-trace.json
"$document_python" -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-subtree-compare-20261019/manifest-ready.json
```

同目录另外三条 lane 为 `SUBTREE2-flash-claude`、`SUBTREE2-flash-openai`、`SUBTREE2-luna-openai`。每条都有 `delivery.json`、人读 `delivery.md` 和导出 hash manifest。机器交付保留完整 ResultRef，模型调用参数使用 `{handle:"rr_…"}`；文档 deliver 不再重复填写 state。原解析仍在 `data/data_agent_documents`，output 仅保存本轮运行/对照/导出。`manifest-ready.json` 为四路实际运行绑定；初始 manifest 与 0 调用配置失败另保留，不能混用。当前不直接重复 run 或创建下一批。

## 元数据引用修复后的同题四路查看（2026-10-20）

四路已结束并停止新增调用，结果与说明准确性问题见核心设计 14.21.5。下列入口只查看已有结果；Luna 交付含独立 metadata、完整正文 evidence 和来源 limitations，原 PDF 质量仍未认证。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m json.tool output/data-agent-metadata-20261020/review.json
cat output/data-agent-metadata-20261020/deliveries/META-luna-openai/delivery.md
"$document_python" -I -m json.tool output/data-agent-metadata-20261020/deliveries/META-luna-openai/delivery.json
"$document_python" -I -m json.tool output/data-agent-metadata-20261020/runs/META-luna-openai/call-trace.json
"$document_python" -I examples/data_platform/live_function.py inspect \
  --manifest output/data-agent-metadata-20261020/manifest.json
```

其他 lane 为 `META-flash-claude`、`META-flash-openai`、`META-sonnet-claude`，目录形式相同。`inspect-final.json` 是收尾账本快照，review 保留修复前后的请求/耗时/错误和原始说明问题。元数据不能作为财务数值原文；gaps 表示未完成请求，limitations 表示披露的限定。四路声明 completed 不代表所有自由文本说明均正确；不要以此直接重跑或启动其他 query。

## 分页范围与原文声明修复后的 Flash 两路查看（2026-10-20）

两条真实会话均已结束。本批只读入口如下，不会调用模型；把 `CLAIM-flash-openai` 换为 `CLAIM-flash-claude` 可看另一条。详细结论及尚未收口的自由说明见核心设计 14.21.6。

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m json.tool output/data-agent-claims-20261020/review.json
cat output/data-agent-claims-20261020/deliveries/CLAIM-flash-openai/delivery.md
"$document_python" -I -m json.tool output/data-agent-claims-20261020/deliveries/CLAIM-flash-openai/delivery.json
"$document_python" -I -m json.tool output/data-agent-claims-20261020/runs/CLAIM-flash-openai/call-trace.json
```

JSON 的 `read_coverage` 与 Markdown 的 `Stored section coverage (code-generated)` 由实际交付页面生成，使用零起始半开区间 `[start,end)`，本题为 `[0,107)`；不是模型自行写的编号。`source_claims` 要求原文引用和逐字摘录，代码只检查摘录存在，语义正确性仍未认证；本题两路未提交此类声明。`limitations` 和公开过程消息仍有字段使用/范围措辞问题，详见 review，不把最终 coverage 通过扩大为所有文字均通过。`inspect-final.json` 保存最终费用/请求快照，`timing-observations.json` 保留前后耗时观察。不要直接重复真实运行或恢复旧 goal。

## 两年营收与代码计算的真实链路查看（2026-10-20）

Flash/OpenAI 已真实运行并导出；数值、期间、合并口径、代码增长率和导出一致性通过独立核对，但没有执行要求的 symbol 查找，USD 确认只给解释而未取得明确引用，严格业务门槛未全过。Flash/Claude 按先通过后继续的约定未运行，不能写作两路均通过。当前已停止。下列命令只读取保存结果，不会调用模型：

```bash
document_python=output/data-agent-gateway-runtime-20261015/checkpoint-4/sdk-env/bin/python
"$document_python" -I -m json.tool output/data-agent-revenue-20261020/review.json
cat output/data-agent-revenue-20261020/deliveries/REV-flash-openai/delivery.md
cat output/data-agent-revenue-20261020/deliveries/REV-flash-openai/records.csv
cat output/data-agent-revenue-20261020/deliveries/REV-flash-openai/calculations.csv
"$document_python" -I -m json.tool output/data-agent-revenue-20261020/runs/REV-flash-openai/call-trace.json
```

当前公共导出除原有 JSON/Markdown/records.csv 外，有计算时另生成 calculations.csv，包含精确结果、公式和操作数引用。它直接来自同一个 committed delivery，没有模型重写、心算或补填事实；原历史导出不会自动补文件。`review.json` 与交付分开保留：原交付声明 completed，独立 review 明确两处未通过，不能用验收侧原 PDF 补查改写原生产结果。完整证据和停止边界见核心设计 14.21.7。
