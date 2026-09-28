# 公司图标批量导入移植说明

本任务已在独立 worktree 实现。主工作区仅限读取委派中列出的六个文件，没有修改、提交、推送或部署。
主工作区在任务运行期间新增了 `presentation: icon | wordmark` 和图像比例规则；最终代码已合并这些约定，
不删除 `image_dimensions` / `validate_icon_shape`，不改变人工导入默认 wordmark 的行为。

## 移植文件

将以下 7 个文件的改动带回主工作区即可接入通用批量能力；路径均相对于仓库根目录。

| 文件 | 操作 | 作用 |
| --- | --- | --- |
| `apps/uteki_zero/tools/import_company_brand.py` | 合并修改 | 提取无写入 prepare 接口；共享锁；身份保留；逐 HTTP hook；可分类重试；跨域身份复核；保留主任务的 presentation/比例约定。 |
| `apps/uteki_zero/tools/import_company_brands.py` | 新增 | 显式范围、身份冲突、缓存、去重、有限并发、限流、持久化冷却、断点与逐条报告。 |
| `apps/uteki_zero/tools/test_import_company_brands.py` | 新增 | 独立合成输入的批量控制与单/批入口互操作测试。 |
| `apps/uteki_zero/tools/test_import_company_brand_network.py` | 新增 | mock HTTP/DNS 的限流、重定向、私网及传输边界测试。 |
| `apps/uteki_zero/tools/README.md` | 合并修改 | 批量参数、输入契约、状态/退出码、缓存、续跑和边界。 |
| `apps/uteki_zero/README.md` | 合并修改 | 增加批量入口和调查/评估链接，保留主任务的 icon 要求。 |
| `docs/COMPANY_LOGO_PROVIDERS_2026-09-29.zh-CN.md` | 新增 | 公开官方来源、匹配方式、覆盖声明、费用/密钥及本地保存许可比较。 |

可用补丁：[handoff.patch](../experiments/company-brand-import/2026-09-29-v1/handoff.patch)。
逐文件哈希和修改前参考哈希：[handoff-files.json](../experiments/company-brand-import/2026-09-29-v1/handoff-files.json)。
补丁基于生成时允许读取的主工作区参考文件，在临时副本上通过 `git apply --check` 和实际应用，
应用后的 7 个文件与本 worktree 逐字节一致。主工作区后续若再改这些文件，先检查补丁再合并，避免整文件覆盖。

本 worktree 的 `brands.mjs`、`brands.test.mjs`、`assets/companies/registry.json` 是最新只读参考副本，
不在补丁中，不需要覆盖回主工作区。原有六家图片没有复制，本目录并不是完整可运行前端副本。
没有设计页面、修改 CSS 或做网页截图。

评估资料可选整目录保留：`experiments/company-brand-import/2026-09-29-v1/`。
其中的素材/注册表是独立研究输出，**不能覆盖前端注册表**；无需将这 8 家加入前端公司池。
本移植说明也可一并保留。补丁不包含评估文件，主 README 的评估链接在只移植代码时需要一并带回该目录或调整。

## 已实现与边界

调用者必须提供 version、scope.id、scope.markets、entityId、exchange、ticker、website。
没有默认市场、公司、股票代码到官网的猜测，也没有按公司名加分支。`www` 归一化，其他子域保持独立。
成功下载只产生官网图标；身份/展示/审核分别记录。失败不能冒充成功或覆盖已经审核的素材。
缓存需验哈希、MIME、路径、来源、时间与 icon 形态；字标和未分类旧素材不会进入紧凑 icon 缓存。

重试限于明确瞬态失败；HTTP 403 不重试。全局请求间隔作用于首页、图标、跳转与重试；
共享 CDN 的 Retry-After 作用于其他 worker，并随 checkpoint 保存。超过 60 秒的服务器等待形成明确缺口，
不缩短等待。checkpoint 绑定完整规范化清单；一个 coordinator 写资产、注册表和状态。
锁使用 POSIX `fcntl`，因此当前不支持 Windows 原生运行。

技术成功并不证明输入官网属于目标上市公司。MIC 仅验证格式和显式范围，不提供全球证券主数据。
Logo.dev / Brandfetch / Finnhub 等认证服务没有接入；密钥、合适许可、实际目标市场和该市场覆盖验收仍未完成。
TradingView 未建立受支持的公开批量导出接口，不猜 CDN 路径，也不将手工核实个例当通用 API。

## 验证

使用标准库 Python 3.13 和 Node 运行针对性测试，未运行整个投研系统回归、模型评估或浏览器验收：

```sh
python3.13 -m unittest discover -s apps/uteki_zero/tools -p 'test_*.py' -v
node --test apps/uteki_zero/brands.test.mjs
```

最终测试数量和结果记录在 [评估说明](../experiments/company-brand-import/2026-09-29-v1/README.md)。
原有单公司测试文件不在允许读取范围，本次没有拷贝它或声称运行了它；移植后应运行主目录已有单公司测试。

真实小批次固定 8 家、7 个市场，全部在原六家之外。首轮 **3 成功 / 3 个 HTTP 403 / 2 个跨域待核实**，
官网图标技术成功率 **37.5%**。成功 3 份均待品牌审核，Toyota 是红色 T 站点图标；没有把它升级成企业 Logo。
缓存续跑零网络，失败保留。主目录新增 presentation 后，单独重采集此前成功的 3 家校验新契约，
不重试先前的 403，不改写首轮报告。详见该评估目录的逐条结果和原始 JSON。

## 下一步

1. 立即：将 7 个文件补丁合入主工作区，并运行该目录原有单公司测试；本任务没有代为修改主工作区。
2. 随后：由调用者提供实际市场范围和公司清单，在新冻结版本中检验覆盖与品牌身份。
3. 需要更广覆盖时：取得适用的供应商密钥和本地存储许可，再增加适配器；无需为本次代码交付注册或付费。
