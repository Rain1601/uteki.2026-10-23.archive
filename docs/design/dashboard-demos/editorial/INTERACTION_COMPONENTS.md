# Editorial v0.5 · 表单、菜单与反馈

当前位置ES04.5。用户认可整体页面风格并授权参考Material UI及其他UI网站完善组件；本轮保留既有编辑设计，沿用vanilla模块，不新增React/MUI运行依赖或付费组件。

## 来源与适配

参考官方 [Text Field](https://mui.com/material-ui/react-text-field/) 的标签/帮助/错误职责、[Menu](https://mui.com/material-ui/react-menu/) 的锚点/边界/焦点/选择关闭、[Dialog](https://mui.com/material-ui/react-dialog/) 的标题/正文/动作与表单容器、[Snackbar](https://mui.com/material-ui/react-snackbar/) 的轻量通知及[Alert](https://mui.com/material-ui/react-alert/)的就地反馈职责。来源是组件行为参考，不称为安装MUI、官方复刻或完整ARIA合规认证。

保留当前字体、细线、语义色与留白。dialog用浏览器原生模态，popover用浏览器原生auto弹出层；抽屉、表格、主题和语言沿用原组件。

## 一条可用流程

点击Header「记录笔记」→显式关联研究记录→填写标题/日期/正文→选择观察/问题/判断与待跟进→保存到当前浏览器→从对应文档查看/编辑→通知中撤销。取消不提交，源研究数值不更改；私人笔记不伪装成原件证据。

顶部「更多操作」支持新笔记、导出本机笔记JSON、导出当前筛选范围JSON、打开中英PDF。ArrowUp/Down/Home/End导航菜单，Escape/Tab关闭并回触发器。弹层锁定原生模态范围，Escape/取消关闭；错误字段附就地说明与aria-invalid，保留其他输入。

## 复用契约

| 模块/组件 | 输入 | 责任 |
| --- | --- | --- |
| TextField | id,label,value,help,error,multiline,required,maxLength | 标签、帮助、错误ID关联；转义文本；显式字符限额 |
| ActionMenu | id,items[{id,label,hint,disabled}],label | 安全且唯一身份、菜单/菜单项角色、禁用状态 |
| Notice | message,tone,action,closeLabel | 成功/信息status、错误alert、可关闭或撤销 |
| InlineAlert | message,tone | 字段集合的就地错误或范围说明 |
| validateNote | input,recordIds | 显式实体范围、严格公历日期、标题1–80码点、正文1–2000码点、类型与布尔值；规范化但不修改输入 |
| readNotes/serializeNotes | version1对象或notes数组、recordIds | 版本与唯一id验证；损坏记录明确失败 |
| createNotesController | records及页面回调 | 笔记状态与本机存储、表单/菜单绑定、单步撤销；独立overlay不随主区重渲染 |

TextField原生maxlength为字符限额的两倍UTF-16容量，业务校验按Unicode码点强制上限，避免一个emoji算两个字符而被过早截断。输入仍可超过声明的ASCII字符限额，提交时明确指出错误，不截断。日期为必需显式输入，不代入报告期间或默认关联首个实体。

## 保存与反馈

存储key `uteki-editorial-notes-v1`，成功localStorage写入后才提示保存。原存储读取/版本/范围失败时保留原内容并阻止覆盖；写入失败保持表单。恢复/撤销也须成功写入才更新页面。各次变更只有当前会话最近一步可撤销；刷新后笔记持久化，但撤销历史不持久化。通知可手动关闭，含撤销和错误的通知不定时消失，与官方temporary示例有所适配。

弹层表单不受主页面语言/主题重渲染影响；模态期间后台不可操作。短暂通知与字段错误区分，错误不冒充保存成功。导出只是浏览器文件下载，无外部服务。

## 已检查与未验收

独立契约测试覆盖日期闰年、空白/非字符串、范围外关联、非法类型、重复身份、版本与输入不可变。浏览器路径：空提交→字段错误；显式NORTH记录→问题/待跟进→保存→对应文档显示→撤销后原列表恢复；菜单ArrowDown/End/Escape恢复触发器。验证样例已撤销清理。

未验收：屏幕阅读器矩阵、移动端视口、存储配额/损坏注入、跨Tab并发写入、附件上传与真实服务器同步。当前是单窗口设计原型，笔记存储不等于生产多人协作；PDF、原实体及数值保持原样。

## 后续队列

| ID | 行动 | 依赖 | 状态 |
| --- | --- | --- | --- |
| ES01–03 | 来源、样册、主题与状态 | 无/前项 | 有边界完成 |
| ES04.1–02 | 四组件及中英PDF | ES02 | 已完成，PDF用户认可 |
| ES04.3 | 长文PDF分页 | ES04.2 | 暂缓 |
| ES04.4 | 完整页面组合 | ES03 | 用户认可风格 |
| ES04.5 | 表单、菜单与反馈 | ES04.4 | v0.5交付；当前位置 |
| ES04.6 | 日期区间、多选与全局检索 | ES04.5 | 下一具体TODO；未开始 |
| ES04.7 | 文件/树/复杂表格及图表交互 | 前项及具体需求 | 队列，未开始 |
| ES05 | 选定生产页面迁移 | ES04及页面范围 | 未开始 |

EC10/14/16/27本轮有实际组合增量，EC28/29下一批；其他EC27–36保持原覆盖缺口，不把MUI目录当作已实现功能。


## 2026-10-10 路线更新

用户要求更广泛探索原站及视频小动效，当前ES01.2交付[设计图谱](anthropic-atlas.html)。下一ES01.3探索客户故事和更多动态图解；ES04.6–07保留未开始状态。MotionFigure本轮只有原创解释样例，不代表通用视频播放器已完成。
