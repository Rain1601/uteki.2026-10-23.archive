# Uteki 动效技术路线（2026-09-29）

颜色流动/纹理滑动的蓝色版与水墨版采用 WebGL 1 / GLSL：原图 UV 固定，曲线坐标图让颜色场沿两瓣移动。水墨版增加周期噪声控制墨色浓淡；不是视频、3D 重建或真实液体模拟。

新增的「入水成形」使用另一条路线：以用户认可的黑/蓝分镜原画作为纹理，做有方向的显露、局部 UV 平流以及空间遮罩过渡，最后显示原 Logo。它属于 2.5D 图像动效，实际纹理细节来自原画；不是数值模拟自动生成的墨丝，也不是视频生成或完整三维液体。可以连续播放和拖动时间，但一张图不包含真实的三维体积与被遮挡的墨丝运动。后续若要求每一条墨丝都有自然的体积翻卷，需要另做连续流体素材或离线影片，再接入网页播放器。

针对“后段像换图”的反馈，成形段升级为按源图/目标图颜料密度计算的网格运输。先按纵向累积密度匹配位置，再按相应行的横向密度匹配；对密度和映射平滑以避免照片局部明暗造成锯齿。原画随网格移动，拉伸时降低颜料浓度；接近目标后才约束边缘、留白和材质。这个过程具有明确的几何位移，但没有求解流体速度、压力或三维体积。

## 下一步可以验证的层级

1. **流向图 + 平流**：让内部墨纹沿预设方向移动，最终使用固定形状蒙版约束雨滴外轮廓与白河。针对本 Logo 推荐先做独立实验模式；解决当前“颜色变、纹理本身不动”的边界。
2. **WebGL 多轮离屏 / 双缓冲模拟**：保存速度、压力和墨色浓度，再每帧推进，支持扩散与鼠标扰动。需要调参、资源预算及可控静止状态；水中墨色并不等于宣纸渗透。算法参考 [NVIDIA GPU Gems 第38章](https://developer.nvidia.com/gpugems/gpugems/part-vi-beyond-triangles/chapter-38-fast-fluid-dynamics-simulation-gpu)，这是经典算法资料，非新发布方案。
3. **WebGPU Compute / WGSL**：新一代底层方向，适合更复杂的粒子、速度场等计算。查询时 [MDN WebGPU](https://developer.mozilla.org/en-US/docs/Web/API/WebGPU_API) 仍标 Limited availability / 非 Baseline，需安全上下文与能力检测，保留 WebGL 或静态回退；不能承诺设备上必然更快。
4. **Three.js WebGPURenderer + TSL**：官方说明支持 WebGPU 并能采用 WebGL 2 后端，TSL 面向 WGSL / GLSL。当前手写 GLSL 需迁移，不能把自定义 Compute 的兼容性视为自动等价；见 [官方指南](https://threejs.org/manual/pages/webgpurenderer)。

[WebGL](https://developer.mozilla.org/en-US/docs/Web/API/WebGL_API) 仍适合当前单个 Logo 的实时像素动效。页面淡入/切换可用 [Web Animations API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Animations_API)，这些外部过渡与内部墨色模拟分工不同。后续 idle/thinking/done 若需要设计师控制状态转场，可以单独评估 Rive。

以上路线选择是针对这个 Logo 的工程和设计判断。只有第一段描述本轮已经实现的功能；其余为待验证实验，没有据此宣称流体仿真或 WebGPU 已接入。
