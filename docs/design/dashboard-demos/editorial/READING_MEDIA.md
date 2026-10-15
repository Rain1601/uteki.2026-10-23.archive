# 正文媒体组件 v0.7 · ES04.7b

入口：[阅读页](workspace.html?view=reading&record=north#read-media)。本轮实现正文内媒体、中心展开窗口、本地视频、曲线绘制与轨道几何动效。旧分步图解保留在可收起区域。页面使用原有模拟记录，新的几何素材独立于记录数值；未迁移生产页。

## 参考与边界

核查 [Claude 内嵌图解文章](https://claude.com/resources/articles/claude-builds-visuals) 的正文媒体位置；[Academy教学案例](https://academy.claude.com/use-cases/visualize-the-mechanism-behind-an-explanation-mid-chat)官方说明包括曲线/轨道与可调控件。这次参考它们的内容与操作组织，曲线、轨道和短片都是原创素材，不是原站动画复刻；轨道只是匀角速度的椭圆几何示意，不是开普勒物理模拟或真实模型活动。

## 复用接口

`reading-media.mjs`：

- `createArticleVideo({src,poster,title,captionSrc,labels})` 返回`content/pause/destroy`。原生video，controls、playsinline、metadata预载，无自动播放；支持显式字幕轨道，加载错误单独提示。只接受显式HTTP(S)或相对资源，拒绝空值、可执行协议与控制字符。
- `createKineticFigure({kind,title,labels,duration})`：kind为curve/orbit；时长>=1000ms；播放、暂停、重播、键盘/拖动进度。默认静态，结束停止，后台和减少动态偏好事件暂停；返回`content/pause/getState/destroy`。
- `mountMediaWindow(host,{title,caption,number,media,labels})`：同一内容节点在正文slot与native dialog之间移动，不复制播放器。关闭先暂停，再移回正文，恢复触发器焦点；支持按钮、Esc与窗口外点击。卸载立即清理对话框、定时器、动画帧和子组件监听。

正文与展开态共用内容；窗口为居中渐显/收回，不宣称原位几何变形。样式独立作用域，使用现有字体和主题tokens。图注始终显示素材用途和边界。语言/主题/记录重新渲染后媒体恢复静态初始状态，关闭窗口则保留当前进度。native视频控件语言由浏览器控制；片内英文为原创素材固定文案，中文/英文字幕可选择。

本地资源：`media/line-study.mp4`，H.264 MP4，960×540，24fps，7秒，168帧，无音轨；静态PNG海报；中英VTT。原创字体来自已固定Liberation字体。Python逐帧生成+系统AVFoundation编码，未下载或安装软件。视频全量解码验证记录见media/README.md；主页面实测readyState=4、duration=7，Space实际播放。

## 原问题与回归

现象：在新图形和旧分步图解中改变进度时，暂停函数先重绘input，覆盖刚输入的值。机制修复：读取输入值后再暂停与重绘。最小回归：静态0%→PageUp→10%，End→100%；旧图解同样验证0%→10%。不是针对某一记录的特例。

实际浏览器检查：视频播放；关闭后paused=true、currentTime保留0.194884s；重新展开仍只有1个video且时间保留；关闭焦点回到展开按钮。轨道0%→20%→播放后约22%，Esc后停止；曲线End到100%；旧图解收起后停止；英文标题和Mineral主题展开检查。33项组件/状态测试通过，新增验证几何边界和危险媒体URL。

未验收：字幕控件选择/无障碍矩阵、触屏和移动端、系统减少动态偏好切换、后台专项检查、真实外部网络故障注入；不将上述实现代码称为全平台验收。图片缩放、图表数据联动和更多动效仍未实现。

## 有序队列

| ID | 项目 | 依赖 | 状态 |
|---|---|---|---|
| ES01.2–03 | 来源图谱、案例与文章研究 | ES01 | 已交付，继续按需扩展 |
| ES04.1–02 | 基础组件与中英PDF | ES02 | 已交付，PDF认可 |
| ES04.3 | 长文PDF | ES04.2 | 暂缓 |
| ES04.4–05 | 工作台、表单与反馈 | ES03 | 已交付，风格/交互认可 |
| ES04.7a | 案例叙事和分步图解 | ES01.3 | 已交付；本轮修复拖动 |
| ES04.7b | 展开媒体、视频、曲线和轨道 | ES04.7a | 本轮完成；当前位置 |
| ES04.7c | 图片局部放大与图表悬停 | ES04.7b | 下一具体项，未开始 |
| ES04.6 | 日期、多选、全局检索 | ES04.5 | 保留队列，未开始 |
| ES04.7其余 | 文件树、复杂表格与画布 | 相关前项 | 未开始 |
| ES05 | 生产迁移 | ES04、明确页面范围 | 未开始 |


后续状态：ES04.7c图片与图表已交付；上文未实现与队列为v0.7历史。最新接口、验收与路线见[检查组件说明](INSPECTION_COMPONENTS.md)。
