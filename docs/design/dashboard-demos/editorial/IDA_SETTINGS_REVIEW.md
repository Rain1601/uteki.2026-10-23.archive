# iDA 设置页修复 · IDA-FIX01 · 2026-10-10

用户截图：高级设置展开前后通用设置区域位移，要求通用设置在导航顶部，并询问主题是否随系统。对象是独立iDA扩展设置，不是Editorial配色。

原件位置：独立 `ida` 仓库的 `ida-extension/src/options/`。导航DOM顺序原为comment/assistant/data/general；通用设置继承旧横向卡片的flex-wrap、居中/两端排布，details增加高度改变标题位置。settings-theme.css以prefers-color-scheme:dark成对切换颜色；没有独立手动主题开关，青绿色为既定品牌强调色。

实际修改：index.html把general按钮移到首位并加载advanced-disclosure.js；assistant-settings.css把general-panel改为顶部对齐的标题/语言两列，高级内容下一整行，显式hidden规则与窄屏单列。html预留稳定滚动条空间（水平偏移候选缓解，未在当前视口复现水平偏移）。新增原生details高度/透明度动画，完成回到auto，支持反向点击、收回焦点和减少动态偏好。settings.js、配置存储与主题逻辑未变。

应用前核对两份原件SHA256，拒绝覆盖异步改动；两份原件当时git干净。补丁已实际应用另一个本地项目，未提交/打包/重载已安装扩展。保留test/advanced-disclosure.test.mjs，生命周期3项通过；现有settings-wiring/settings-merge/options-templates共179项通过。

本机DOM/CSS回放使用原版/新版提取的通用设置、导航、标题与同版本样式，不执行存储/网络/诊断功能。旧版标题y=162.25→143.796875，确认垂直位移；新版x=296/y=138、mainX=80在展开前后完全一致，动画结束固定height清空。没有声称该回放等于已安装扩展最终验收。截图study/ida-settings-fixed.png；回放study/ida-settings-regression/after/index.html。

| ID | 状态 |
|---|---|
| ES07.3 集中来源/阅读返回 | 已交付原型，102项检查与双页位置回归 |
| IDA-FIX01 通用设置置顶/展开稳定/主题核对 | 源码已修复；待已安装扩展刷新核对 |
| ES04.3 长文PDF | 暂缓 |
| ES05 真实执行/生产接入 | 未实施 |

下一具体动作：在已安装iDA扩展刷新设置页，确认相同截图场景使用新脚本，标题保持固定；本机回放与源码不代替扩展加载状态。
