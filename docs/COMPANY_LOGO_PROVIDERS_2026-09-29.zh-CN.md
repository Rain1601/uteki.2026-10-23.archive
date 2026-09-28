# 公司 Logo 批量来源调查

查询日期：2026-09-29。范围：TradingView、公司官网图标、Logo.dev、Brandfetch、Finnhub。只核对公开官方文档；未注册账号、购买套餐、使用他人密钥或调用需要认证的素材接口。以下价格与条款是本次查询快照，覆盖数字是供应商声明，不是 Uteki 实测覆盖率。

## 建议与当前边界

当前批量导入采用调用者明确提供的公司官网，从网页声明中发现 `rel=icon` / `apple-touch-icon`，保存为 `official-site-icon`。这条路径无需供应商账号，可在现有本地注册表上完成缓存、去重、重试和续跑；官网声明只能证明它是站点图标，不能自动升级为已审核企业 Logo。HTML 标准将 `icon` 定义为代表页面或站点的图标，Apple 文档则定义主页图标声明方式。[HTML 标准](https://html.spec.whatwg.org/multipage/links.html#rel-icon)、[Apple Web Clip 图标文档](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html)

未来若需要减少官网解析失败并保留本地素材，优先评估 **Logo.dev 的 Pro 或带自托管许可的合同**：它明确描述了批量下载和自有存储流程。订阅有效期、密钥与目标市场验收仍是接入前的真实缺口；本轮不启用收费路径。[Logo.dev 自托管许可](https://www.logo.dev/docs/platform/self-hosting)

TradingView 暂不作为导入源。Brandfetch 免费 Logo CDN 不适合当前脚本下载到本地的方式。Finnhub 可在已有合适数据许可时辅助核对证券身份，但不能把免费行情账号视为素材再分发许可。下面说明证据与边界。

## 来源比较

| 来源 | 批量与身份匹配 | 覆盖与缺失 | 价格、密钥 | 本地保存条件与本轮决定 |
| --- | --- | --- | --- | --- |
| 公司官网声明图标 | 对显式 `website` 逐站执行；站点域名匹配，不提供 `exchange/ticker → website` 身份解析。`rel=icon` 与 Apple 图标声明有公开规范。[HTML](https://html.spec.whatwg.org/multipage/links.html#rel-icon)、[Apple](https://developer.apple.com/library/archive/documentation/AppleApplications/Reference/SafariWebContent/ConfiguringWebApplications/ConfiguringWebApplications.html) | 依赖站点提供可访问的合适格式；不能从有限样本推出任何市场覆盖率。图标可能代表产品、集团或区域网站，需要保留未审核状态。 | 没有统一供应商费用或密钥；具体站点可能要求认证或拒绝自动请求。遇到这些情况记录缺口，不绕过。 | 没有统一的再使用许可；各站点素材条件需分别遵守。技术规范不授予商标许可。本轮实现这一公开来源路径，保留来源与哈希，不把技术下载成功当品牌审核通过。 |
| TradingView | 已核对的 Advanced Charts 文档要求**调用方提供** `logo_urls` 与 `exchange_logo`；这不是供应商 Logo 导出接口。[图表文档](https://www.tradingview.com/charting-library-docs/latest/ui_elements/Symbol-Search/) | 未找到支持外部批量下载 Logo 的公开接口、覆盖保证或 SLA。此结论限于本次公开文档调查，不表示不存在商务合作产品。 | 未找到可用于该用途的公开 API 定价和密钥流程；普通 TradingView 订阅不据此视为已授权。 | 不猜测或遍历 CDN 路径，不使用非公开扫描接口。使用条款没有为本任务给出通用 Logo 下载/再分发许可。[条款](https://www.tradingview.com/policies/) |
| Logo.dev | 单域名/单证券图像请求；官方自托管页给出循环并发批量示例。支持域名、ticker、ISIN；ticker 可加交易所后缀，裸 ticker 默认搜索美国交易所。[ticker 文档](https://www.logo.dev/docs/logo-images/ticker)、[自托管](https://www.logo.dev/docs/platform/self-hosting) | 股票产品页声称 70,000+ 股票/ETF/基金及 60+ 交易所。未知 ticker 默认可返回占位图，须显式 `fallback=404` 识别缺失；不能以 HTTP 200 作为品牌匹配证明。[覆盖声明](https://www.logo.dev/products/stock-ticker-logos)、[错误处理](https://www.logo.dev/docs/platform/errors) | Community $0、500,000 图像请求/月；Pro 页面价 $150/月、5,000,000 图像请求/月，包含自托管；Enterprise 可协商文件交付。图像使用自有 `pk_` 密钥，REST JSON 使用 `sk_`。[价格](https://www.logo.dev/pricing)、[认证](https://www.logo.dev/docs/api-reference/introduction) | Pro / Enterprise / custom 在订阅有效期内可保存到自有基础设施；免费浏览器缓存不是脚本批量落盘许可。[缓存](https://www.logo.dev/docs/platform/caching)、[自托管](https://www.logo.dev/docs/platform/self-hosting) 本轮缺少密钥和许可，保留为后续候选。 |
| Brandfetch | Logo API 有显式 `domain/`、`ticker/`、`isin/` 路由；每次一个标识符。官方称批量数据集可联系商务确认范围；未确认公开多条输入的批量下载端点。[Logo API](https://docs.brandfetch.com/logo-api/overview)、[产品/批量 FAQ](https://brandfetch.com/developers/products) | 定价页声称 50M+ 品牌。默认可能用 HTTP 200 返回替代图，需 `fallback/404`。品牌覆盖声明不保证每个市场证券与官网都正确映射。[价格/覆盖](https://brandfetch.com/developers/pricing)、[错误与缺失](https://docs.brandfetch.com/logo-api/overview#errors) | 每请求需自有 Client ID。定价主表列免费 1M Logo 请求/月与 100 次一次性 Brand fetch；Growth 展示 $99/月并标示年付条件。真实账单周期需接入时确认。[定价](https://brandfetch.com/developers/pricing) | Logo API 使用指南要求热链，禁止程序化抓取，缓存需 custom setup；不能用于当前免费脚本批量保存。Brand API 条款另有最长 30 天缓存并需重新调用续期。[使用指南](https://docs.brandfetch.com/logo-api/overview#usage-guidelines)、[条款](https://brandfetch.com/terms) |
| Finnhub Company Profile 2 | `/stock/profile2` 按单个 symbol / ISIN / CUSIP 查询，返回 `ticker`、`exchange`、`weburl`、`logo`；已查 schema 未给出多 symbol 的 profile2 批量参数，需按条调度。[官方 API](https://finnhub.io/docs/api/company-profile2)、[官方 OpenAPI](https://github.com/Finnhub-Stock-API/finnhub-go/blob/master/api/openapi.yaml) | 产品提供全球证券数据，但本轮没有 profile2 Logo 完整率或逐市场免费权限的可靠验收结果；不能把企业套餐的“所有交易所”声明当免费 Logo 覆盖。[企业方案](https://api.finnhub.io/pricing-startups-and-enterprise) | profile2 文档称免费版本，所有 GET 均需 API key；除套餐限额外还有 30 次/秒上限。企业方案询价。本轮未从可读取官方价格页确认免费账户当前每分钟限额，配置不得依赖网上常见旧数字。[API 认证/限额](https://finnhub.io/docs/api)、[企业价格](https://api.finnhub.io/pricing-startups-and-enterprise) | 普通方案按条款限个人用途，向第三方共享数据/派生结果需书面批准，订阅结束需删除对应数据；一般条款未给出永久本地 Logo 素材库授权。[条款](https://finnhub.io/terms-of-service) 本轮不接入。 |

## 会影响实现的核实结果

### TradingView：展示能力与素材获取要分开

TradingView 官方帮助页明确说当前没有供用户获取数据的 API，其 REST API 服务于券商接入；该表述针对数据访问，不能单凭它断言所有 Logo 合作渠道均不存在。更直接的证据是 Advanced Charts `SearchSymbolResultItem.logo_urls` 接收调用方的 URL，官方示例也是自有服务器路径。因此本轮结论是：**公开资料不足以建立受支持、可授权本地保存的批量 Logo 接口**，不把网页可见图标或可猜出的 CDN URL 当成可靠供应商。[API 帮助页](https://www.tradingview.com/support/solutions/43000474413-i-need-access-to-your-api-in-order-to-get-data-or-indicator-values/)、[SearchSymbolResultItem](https://www.tradingview.com/charting-library-docs/latest/api/interfaces/Datafeed.SearchSymbolResultItem/)

### Brandfetch：官方缓存表述存在冲突

查询时，定价 FAQ 写 Logo API 图像可按指南本地缓存；产品页却写 Logo API 不可存储；Logo API 使用指南进一步明确禁止程序化访问，并指出有效 Client ID 也不会豁免自动化流量检查。这是同一供应商公开页面之间的差异，不能以较宽泛的营销 FAQ 覆盖更具体的接口限制。本轮按使用指南处理，未来必须先取得适用于服务端下载和缓存的明确方案。[定价 FAQ](https://brandfetch.com/developers/pricing)、[产品页](https://brandfetch.com/developers/products)、[接口指南与 automated_traffic](https://docs.brandfetch.com/logo-api/overview#usage-guidelines)

文档还列出每 IP 每 5 分钟 1,000 次、每客户每 5 分钟 2,400 次的吞吐限制。它们不构成脚本抓取授权。Brand API 的 30 天缓存条件属于另一个接口与合同问题，不能直接套用于免费 CDN。[Logo API 限额](https://docs.brandfetch.com/logo-api/overview#rate-limits)、[缓存条款](https://brandfetch.com/terms)

### Logo.dev：有明确批量路径，但需套餐许可

自托管指南直接给出按域名批量下载、保存字节并从自有 CDN/文件系统提供的示例；fair-use 指南将该用途限定为 Pro、Enterprise 或定制许可下的自有应用。浏览器默认 24 小时缓存不能替代这一许可。官方文档的批量示例是客户端编排多个请求，不是一次请求返回整个市场素材库。[自托管](https://www.logo.dev/docs/platform/self-hosting)、[fair use](https://www.logo.dev/docs/platform/fair-use)、[浏览器缓存](https://www.logo.dev/docs/platform/caching)

供应商 ticker 格式需要独立、版本化映射：例如文档列 `.L`、`.T`、`.HK`、`.SS`、`.SZ`。不能直接去掉交易所后传裸 ticker，因为该接口会将裸 ticker 按美股解释。候选匹配仍需核对调用方 `website` 与实体；下载图片本身不能完成证券身份验证。官方允许报告错误 Logo，也说明错误/缺失是必须保留的状态。[ticker 规则](https://www.logo.dev/docs/logo-images/ticker)

### 官网图标：当前输入契约的意义

本轮实现不承担全球证券主数据解析。调用者提交 `entityId`、`exchange`、`ticker`、HTTPS `website` 和明确市场范围；程序能检查缺失、格式和同批冲突，但不能仅凭这些字段证明网站属于该上市实体。若调用方把错误官网填给了公司，页面返回有效图标仍可能语义误匹配。这类情况应进入人工核实，不能统计成“已审核 Logo”。

采用域名作为现有注册表键时，只按已约定规则归一化 `www`；保留其他子域。多个证券共享集团官网可能是合法情况，但需要输入中明确的身份关系；不自动把子品牌、母公司、ADR 或地区站合并。`sourcePage`、`assetUrl`、`fetchedAt`、`sha256` 与 `kind` 应保留，原图下载成功仅更新 `official-site-icon`，不得覆盖 `reviewed-logo`。

## 验收口径与后续接入

真实小批次结果由对应运行报告记录，本供应商调查未调用需认证服务，也没有供应商 API 成功率数据。官网验证名单必须是显式、版本化测试输入；它既不是生产默认名单，也不是未指定市场范围的替代。报告分母包含所有提交记录，同时分开列出输入错误、技术获取失败、待人工核实、官网图标成功和已审核素材保留，避免用占位图或跳过项抬高成功率。

优先后续动作：

1. 完成无密钥官网路径的小批次验证，逐条保留缺失和失败原因；成功案例仍标为站点图标。
2. 当市场范围确定后，使用该范围内冻结的公司清单验收身份匹配与覆盖，并审核代表性图标。
3. 只有用户选择供应商并提供合适密钥/许可后，再实现对应适配器；Logo.dev 优先验证自托管订阅，Brandfetch 先解决服务端下载许可冲突，Finnhub 先确认使用与分发权。

本轮没有部署、推送、付费、注册账号或写入外部服务；没有使用供应商文档中的演示密钥。方案选择不改变已有六家公司名单，不宣称覆盖全市场。
