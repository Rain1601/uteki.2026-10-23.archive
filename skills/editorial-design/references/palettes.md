# 可配置色卡

实现见 `../assets/editorial/palette-presets.mjs` 与 `tokens.mjs`。七套内置色卡：paper 暖纸、mineral 冷蓝、plum 灰紫、forest 草木、clay 赤陶、night 深色金、paper-night 柔和暖灰纸本夜间。配色不选布局，也不决定记录、状态或图表数据。

| 角色 | 用途 |
|---|---|
| canvas / surface | 页面与次级表面 |
| ink / muted | 主要与次要文字 |
| line | 非文本分隔 |
| accent / accentSoft | 操作与选中背景 |
| positive / negative | 状态语义，配文字或符号 |
| series1 / series2 / series3 | 图表序列，另需标签、线型或标记 |

每个主题必须提供全部12个角色，值为六位 `#RRGGBB`；缺字段、未知字段、非法颜色明确失败。不要从 accent 自动推导所有状态色；深色使用适合深表面的状态颜色。

```js
import {applyPalette} from './palette-presets.mjs';
// 命名色卡，也可把 JSON.parse(config) 作为完整角色对象传入。
// 只写主题变量，不覆盖宿主尺寸/内联样式，业务实例不重置。
applyPalette(host,'forest');
```

`validatePalette` 做完整角色校验，以及 ink/muted/accent × canvas/surface/accentSoft 的9组不透明sRGB对比度≥4.5检查。它不覆盖整个页面、图形、状态色、焦点和半透明背景，也不证明全部无障碍要求。图表不要把 muted/line 当唯一可辨信息。自定义颜色用于其他背景组合时检查实际组合。

`starter.html` 展示命名色卡选择、JSON草稿应用、无效输入保留最近有效主题、与独立布局切换。色卡可以继续扩展；配色登记与持久化由具体应用明确决定，不写入系统主题设置。

字体也可用角色变量配置：`--font-display`、`--font-reading`、`--font-ui`、`--font-numeric`。组件尺寸用 `componentCSS` 已声明参数；页面自身布局使用命名局部 CSS，不把尺寸挤进颜色 JSON。

用户当前偏好：自然的 Paper 是研究工作台默认起点；其夜间配对用 Paper Night 柔和暖灰、米白文字和低饱和暖棕，不强制所有新页面都用该配色。

## 报告换色与阅读状态

Paper / Paper Night 可配对；夜间 canvas #302e2a、surface #38352f，米白文字、低饱和暖棕。新任务仍可独立定制颜色。

换色只调用 applyPalette 写变量，另设宿主 color-scheme。保持 reader 和 sourcePanel 实例，不 destroy、不重建正文；章节、图表模式、展开状态、焦点与阅读坐标保持。来源 portal 继承同一主题宿主。

来源面板为 modal，背景控件不可操作。mountReportReader 的可选 sourcePanelAction:{label:'切换明暗',onClick:toggleTheme} 透传至 mountSourcePanel 的 headerAction:{label,onClick}。回调由宿主提供，只更新配色，未传则不增加入口。

应用的主题白名单、阅读会话校验和返回列表必须同时识别 paper-night，避免新主题使已有阅读记录判无效。URL 更新保留报告身份、语言和章节 hash。持久化只存外观与阅读元数据，不存报告正文。验收稳定 top/left、图表模式、来源 open、搜索、当前摘录、面板 scrollTop 与关闭后的原引用焦点。
