# 图片与图表检查组件 v0.8 · ES04.7c

当前位置：ES04.7c 已交付。入口：[实际阅读页](workspace.html?view=reading&record=north#read-inspect)。不是生产迁移。

## 形式与依据

[Claude Academy 机制可视化示例](https://academy.claude.com/use-cases/visualize-the-mechanism-behind-an-explanation-mid-chat)描述同一控件联动多个视图；[Anthropic circuit tracing 文章](https://www.anthropic.com/research/open-source-circuit-tracing)介绍可探索、注释的图形界面。本轮核查官方文字说明，没有将第三方图形工具或官方动画移植到项目。圆形放大镜和双图悬停是项目适配，不宣称官方组件复刻。

图片采用整幅静态图加圆形局部镜；对照采用上下两图、共享竖线和固定读数栏。继承纸面留白、宋体/衬线叙事标题、无衬线控件、细分隔线；不把图片、视频、轨道和数据图统一为卡片流程图。主题仅映射颜色角色。放大镜直接移动，不加追随延迟；图形只对透明度做180ms过渡，减少动态偏好时关闭过渡。

## 可复用契约

`image-inspector.mjs` 导出 `lensGeometry` 与 `mountImageInspector(host,{src,alt,title,caption,labels,zoom,diameter})`。返回 `getState/destroy`。显式图片、替代文字、图注和控件标签由调用者提供；媒体URL使用既有安全校验。默认2.5倍、直径180px；缩放1.5–4倍，直径60–300px。图像按自然比例铺满阅读宽度，镜片与背景使用同一显示尺寸换算，镜片在小图上自动收缩并保持在图像内。加载失败提示错误并停用控件。

鼠标移入检查，点击锁定/解除；方向键移动、Home居中、Enter/Space锁定、Esc隐藏；倍率输入先读取再重绘。复位回到中心，ResizeObserver重新计算几何。触屏采用指针捕获与松手锁定，但本轮未作设备验收。卸载断开观察器并移除节点。

`linked-charts.mjs` 导出 `buildLinkedChartModel/LinkedCharts/mountLinkedCharts`。挂载返回 `destroy`。输入明确提供3–12个唯一 `points[{id,label,detail?}]`、恰好两条不同类型的 `series[{id,title,unit,type:'line'|'bars',values:[{id,value}]}]`、`labels{hint,clear,missing,pinned}`。值为有限数或显式null；每条系列必须覆盖所有点，不接受重复、未知或遗漏身份。系列按id连接，不依赖数组位置。

同一SVG保证共享x刻度和一条参考线；两条系列独立y尺度。缺失断线并标叉，零保留零轴细线，负柱在零轴下方。悬停/焦点联动、点选锁定、左右/Home/End移动，Esc或清除按钮解除；锁定优先于临时悬停。读数区位置稳定，含完整记录标签；按钮提供数值及缺失文字，无需只靠颜色判读。

## 实际接入与验收

主入口 `mountReadingInspection(list)` 绑定当前筛选范围的原有六条虚构记录；日期是不同实体的记录日期，不是同一对象的时间序列。第二系列刻意反转输入顺序，验证身份连接。少于三点时明确提示调整范围，不制造点。语言/主题/文档重新渲染会先destroy两种组件；不修改源记录、笔记或PDF。

2026-10-10 实际IAB检查：

- 图片ArrowUp移动、Enter锁定；倍率End显示4倍；复位与Esc隐藏。
- 图谱工作室读数为两个“未记录”；方向键下一条为两个0；再下一条共同地带为−51,700 CNY与−3.4%。两个标记同时高亮且参考线只有一条。
- Esc解除；从图外拖动指针进入北线记录区后，两图显示82,400与14.2%，has-active但没有is-pinned，验证指针进入联动。
- 英文/Mineral切换、选择Field Notes后，每种组件只有一个实例，图表无残留选中；恢复中文Paper/北线交付。
- 所有42项现有组件/状态与新增几何/身份契约测试通过；新检查覆盖边界、null断线、zero/negative及乱序身份。没有以测试通过代替用户外观验收。

截图：[图片局部](study/image-inspector-v08.png)、[双图对照](study/linked-charts-v08.png)。未验收：移动设备、跨浏览器、完整读屏矩阵和真实远端图片故障。此组件限定两图/3–12点；大型数据、刷选范围及可编辑标注尚未实现。

## 有序路线

| ID | 项目 | 依赖 | 状态 |
|---|---|---|---|
| ES01–03 | 来源、样册、主题 | 前项 | 已交付；来源按需继续探索 |
| ES04.1–02 | 基础组件与中英PDF | ES02 | 已交付；PDF认可 |
| ES04.3 | 长文PDF | ES04.2 | 暂缓 |
| ES04.4–05 | 完整工作台、表单与反馈 | ES03 | 已交付；风格与交互认可 |
| ES04.7a–b | 案例叙事、动态图解、视频与展开媒体 | ES01.3 | 已交付 |
| ES04.7c | 图片局部与图表联动 | ES04.7b | 本轮完成；当前位置 |
| ES04.6 | 日期区间、多选和全局检索 | ES04.5 | 下一具体项；未开始 |
| ES04.7其余 | 文件树、复杂表格与画布 | 相关前项 | 未开始 |
| ES05 | 生产迁移 | ES04、明确页面范围 | 未开始 |
