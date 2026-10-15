# ES04.6 · 全局范围与快速检索 v0.9

[入口](workspace.html)。记录视图（概览/列表/阅读）顶部共用日期、分类与文字搜索，资源与财务页面各有自己的对象范围，避免将记录过滤误用到文件或发票。

`workspace-state.mjs` 的 `filters` 原子 action 接收 `{categories:[],dateRange:{from:'',to:''}}`；空多选代表全部，开放日期可留空，端点包含在内；日历日期严格验证（0001–9999）。旧 category API兼容，未知/重复类别拒绝。筛选后被隐藏的选中身份清除；resetFilters同时清文字搜索。数据过滤、排序与状态不修改输入。

`createScopeControls({records,getState,tr,titleFor,preview,onApply,onReset,onOpenRecord})` 返回 openFilters/openSearch/close/destroy。筛选窗口保存独立草稿，预览计数；关闭不提交，应用才提交，无效或倒置区间禁用。最近三个记录日来自当前数据集，非机器日期或硬编码财务期间。

快速检索使用native dialog，⌘/Ctrl K、↑↓、Enter、Esc；输入与选中记录分开，中文组合输入不提前提交。搜索限制于日期与分类范围，覆盖标题/摘要/日期；打开记录清除顶部文字搜索、保留日期/分类，使该记录确实在可见范围内。只查本页6条模拟记录，不宣称后台或全站全文搜索。

行为参考：[MUI Autocomplete](https://mui.com/material-ui/react-autocomplete/) 的输入/选中状态区分，[MUI Dialog](https://mui.com/material-ui/react-dialog/) 的聚焦任务；不依赖MUI运行时、不复刻默认皮肤。

实际IAB：倒置日期提示错误并禁用应用；最近三记录日+Research=2条，概览小计146,200；日期检索2026-10-08只匹配田野笔记，键盘打开阅读；⌘K打开且Esc关闭。46项组件检查通过。触屏日历/全读屏矩阵未验收。[截图](study/scope-v09.png)。

当前位置ES04.6已交付。下一ES04.7d资源管理与预览；用户新要求按常用组件和任务/角色页面范式继续，ES06金融与运营页面进入已授权队列。历史v0.8队列保留。
