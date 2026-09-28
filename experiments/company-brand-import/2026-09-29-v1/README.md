# 公司图标公开小批次 v1

这份显式清单用于验证通用导入机制，不是业务默认公司池、市场覆盖承诺或品牌授权。
名单在运行前固定，8 家公司均不在原有 Alphabet / Microsoft / NVIDIA / Costco / Arista / Eaton 六家中。
7 个市场、消费电子、汽车、日用品、软件、矿业、医药、银行和游戏各一例。没有按结果替换样本。
`entityId` 是本评估分配的稳定标识，不冒充外部证券主数据 ID。`exchange` 使用清单显式指定的 MIC；
导入器检查清单内部一致性，不自行验证证券仍在上市，也不推断发行人的官网。

## 输入身份依据

以下官方页面在 2026-09-29 研究时核对；网页语言和域名按原始来源保留。

| entityId | exchange:ticker | 显式官网 | 行业 | 身份来源 |
| --- | --- | --- | --- | --- |
| apple | XNAS:AAPL | https://www.apple.com | 消费电子 | [Apple FAQ (EN)](https://investor.apple.com/faq/) |
| toyota-motor | XTYO:7203 | https://global.toyota | 汽车 | [Toyota Stock Overview (EN)](https://global.toyota/en/ir/stock/outline/) |
| unilever | XLON:ULVR | https://www.unilever.com | 日用品 | [London Stock Exchange (EN)](https://www.londonstockexchange.com/stock/ULVR/unilever-plc/company-page)、[Unilever Shares (EN)](https://www.unilever.com/investors/investor-centre/shares/share-prices/) |
| sap | XETR:SAP | https://www.sap.com | 软件 | [SAP FAQ (EN)](https://www.sap.com/investors/en/resources/faq.html) |
| bhp-group | XASX:BHP | https://www.bhp.com | 矿业 | [BHP FAQ (EN)](https://www.bhp.com/investor-centre/shareholder-information/frequently-asked-questions)、[ASX BHP announcements](https://www.asx.com.au/asx/v2/statistics/announcements.do?asxCode=BHP&by=asxCode&period=M6&timeframe=D) |
| roche-holding | XSWX:RO | https://www.roche.com | 医药 | [Roche FAQ (EN)](https://www.roche.com/investors/faq_investors) |
| dbs-group | XSES:D05 | https://www.dbs.com | 银行 | [DBS Investor Relations (EN)](https://www.dbs.com/investors/default.page) |
| nintendo | XTYO:7974 | https://www.nintendo.co.jp | 游戏 | [Nintendo 株式の状況 (JA)](https://www.nintendo.co.jp/ir/stock/information/index.html) |

Roche 选择官方 FAQ 仍列示的 `RO` 普通股。FAQ 当前列出的参与凭证代码为 `ROP`，
没有沿用旧代码 `ROG`。身份来源不进入下载算法，也不作为预期图像答案。

## 执行与输出

输出注册表独立于前端注册表；
现有六家素材与主工作区没有被改写。原图是公司官网公开图标，使用条件仍来自各站点，
本次技术验证不赋予品牌再许可。成功下载只证明本次技术获取成功；`official-site-icon`
保持待品牌审核，不能因来自官网就标成 `reviewed-logo`。

实际运行时间：2026-09-29 00:20 左右（Asia/Shanghai，报告 UTC 时间为 2026-09-28 16:20）。
执行环境是当前机器直连公网 HTTPS；默认沙箱 DNS 不可用，公开只读执行经审批后完成。
未使用代理、浏览器会话、登录 Cookie、额外密钥或反爬绕过。

```sh
python3.13 apps/uteki_zero/tools/import_company_brands.py \
  --manifest experiments/company-brand-import/2026-09-29-v1/manifest.json \
  --registry experiments/company-brand-import/2026-09-29-v1/assets/companies/registry.json \
  --state experiments/company-brand-import/2026-09-29-v1/run.state.json \
  --workers 3 --min-interval 1 --attempts 2 \
  > experiments/company-brand-import/2026-09-29-v1/run.report.json
```

首轮退出码为 **1**，没有把部分成功当作整批成功。实际共 15 次 HTTP 请求，
3 个并发域名上限、全局请求启动间隔至少 1 秒；403 没有重试。

| 公司 | 输入代码 | 本次结果 | HTTP 次数 | 说明 |
| --- | --- | --- | ---: | --- |
| Apple | XNAS:AAPL | success | 2 | 官网 `/favicon.ico`，ICO 原图本地保存。 |
| Toyota Motor | XTYO:7203 | success | 2 | 官网 `apple-touch-icon-precomposed.png`。 |
| Unilever | XLON:ULVR | failed | 1 | 官网返回 HTTP 403。 |
| SAP | XETR:SAP | failed | 1 | 官网返回 HTTP 403。 |
| BHP | XASX:BHP | failed | 1 | 官网返回 HTTP 403。 |
| Roche | XSWX:RO | success | 2 | 官网 Android Chrome PNG 图标。 |
| DBS | XSES:D05 | needs_review | 3 | `dbs.com` 跳转到 `dbs.com.cn`，没有自动合并地区站身份。 |
| Nintendo | XTYO:7974 | needs_review | 3 | `nintendo.co.jp` 跳转到 `nintendo.com`，没有自动合并域名。 |

- 技术获取成功：**3/8 = 37.5%**。返回值为 `official-site-icon`，全部 `brandReview: pending`。
- 获取失败：**3/8 = 37.5%**。记录原始 403，没有增加人工补图来修改首轮成绩。
- 身份待核实：**2/8 = 25%**。跨域跳转目标没有进入注册表。
- 本轮新增已审核品牌 Logo：**0/8**。不能将前三项的技术成功率当作企业品牌 Logo 验收率。

已直接查看三份本地素材（没有打开或截图网页）：Apple 是苹果图形，Roche 是带边框的字标；
Toyota 是官网提供的红色 **T** 站点图标。这一例说明网站图标不一定是期望的企业品牌图形。
Apple 的 ICO 仅在 `/tmp` 转成 PNG 供查看，注册表仍保留原始 ICO 与原始哈希。
这次目视检查没有发现明显的跨公司借图（0/3 已获取样本），但它不是独立品牌审核，
也不能据此报告全市场误匹配率为零。调用方误填官网仍是未自动解决的身份风险。

同一输入、同一 checkpoint 再执行一次，注入“任何联网调用都会抛错”的 fetcher：
结果 **3 cached / 3 failed / 2 needs_review，0 网络调用**。失败与待核实记录没有被改成成功。
真实首轮报告：[run.report.json](run.report.json)；首轮 checkpoint 快照：[first-run.state.json](first-run.state.json)；
续跑报告：[resume.report.json](resume.report.json)；当前续跑 checkpoint：[run.state.json](run.state.json)；
原图与来源：[assets/companies/registry.json](assets/companies/registry.json)。

### 主工作区后续 icon 契约兼容

任务运行期间，允许读取的主工作区接口新增了 `presentation: icon | wordmark` 和图像比例校验。
最终实现保留这些改动：自动发现输出 icon，人工导入默认为 wordmark；宽高比仅是图标的必要格式条件，
不代表品牌语义审核。已审核 wordmark 或缺分类素材不会被自动降级、补分类或塞进紧凑图标槽。

此前 3 个成功缓存没有 presentation，因此按新接口**重新采集**这 3 家，共 6 次 HTTP 请求；
另 5 家沿用失败/待核实 checkpoint，HTTP 次数均为 0。最终仍是 **3 success / 3 failed / 2 needs_review**，
三个成功素材的原始 SHA-256 与首轮完全相同，全部明确为 `presentation: icon`。
第二次零联网续跑为 **3 cached / 3 failed / 2 needs_review**。

对应报告：[presentation-refresh.report.json](presentation-refresh.report.json)、
[presentation-resume.report.json](presentation-resume.report.json)。
为保留历史，第一轮注册表另存为 [first-run.registry.json](first-run.registry.json)，
第一次缓存续跑状态另存为 [resume.state.json](resume.state.json)；当前 assets 注册表与 run.state 是最终兼容后的版本。
兼容复测不改变首轮 37.5% 的分母/结论，也不是为提高成绩重试 403。

最终针对性验证：**62 项 Python 离线测试 + 8 项 JavaScript 域名/注册表/icon 解析测试通过**。
另以最终 renderer 的 `validateBrandRegistry` / `resolveBrand` 检查了 3 份新输出。
Python 测试含独立的合成多市场/多实体输入；没有模型调用，未运行整个投研系统回归，未做浏览器视觉验收。

这些文件保留首轮结果；重新评估应创建新的版本化运行目录，不覆盖本次报告。
403 和跳转可能与运行位置、站点策略和时点有关，本次没有证明其原因。
样本规模很小、均是大型公开公司，没有覆盖小盘股、全市场、已退市证券或无官网实体。

## 后续顺序

1. 将通用代码与文档按移植清单带回主工作区；不将本评估注册表覆盖到前端。
2. 用户确定实际市场/公司清单后，建立新的冻结评估输入；对失败和地域跳转逐项核实。
3. 如需第三方提升覆盖率，先取得与本地存储用途匹配的密钥和许可，再实现适配器。
