# Anthropic 设计图谱 v0.1

核查日期：2026-10-10。当前 ES01.2：扩展不同场景的原设计依据。

## 来源与边界

- AS01 [研究出版 / Research](https://www.anthropic.com/research) — 结构核查；此前对照。栏目、日期、分类和文章列表共同建立出版秩序。 可映射：PublicationList · SectionIndex。

- AS02 [工程文章 / Engineering](https://www.anthropic.com/engineering) — 结构核查。技术内容按主题和文章组织；适合内容入口而非数据卡片堆叠。 可映射：ArticleIndex · FeaturedStory。

- AS03 [新闻 / News](https://www.anthropic.com/news) — 结构核查。重点报道与后续列表分层；日期作为扫描锚点。 可映射：NewsLead · DateRow。

- AS04 [产品总览 / Overview](https://claude.com/product/overview) — 截图与DOM。大衬线标题居中，周围是任务缩略素材；主次按钮区分行动。 可映射：ProductHero · TaskThumbnail。

- AS05 [作品 / Artifacts](https://claude.com/features/artifacts) — 截图与DOM。小标签与大衬线标题分工；示例切换和作品信息可独立组合。 可映射：ExampleSwitcher · ArtifactMeta。

- AS06 [连接器目录 / Directory](https://claude.com/marketplace/connectors-plugins) — 截图、DOM与筛选操作。左侧分类筛选，右侧检索、排序和目录；勾选分类后范围与数量同步变化。 可映射：FilterRail · DirectoryGrid。

- AS07 [下载 / Download](https://claude.com/download) — 截图与DOM。首屏明确主平台行动；下面再展开各端入口。 可映射：PlatformPicker · DownloadCard。

- AS08 [任务委托 / Cowork](https://claude.com/product/cowork) — 截图与DOM；内部未实测。围绕任务和工作成果组织说明；应用内执行过程仍需独立检查。 可映射：TaskBrief · ProgressRail。

- AS09 [作品编辑工作区 / Editor](https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them) — 官方文档；非应用实测。官方说明作品窗口、工具栏、缩略图和属性区域。分区布局由此推导，不声称像素复刻。 可映射：ArtifactCanvas · Inspector · ThumbnailRail。

- AS10 [项目知识 / Projects](https://support.claude.com/en/articles/9519177-how-can-i-create-and-manage-projects) — 官方文档；非应用实测。项目、知识文件、指令和成员有不同职责，适合分别建立导航和编辑区域。 可映射：KnowledgePanel · MemberList · ProjectMenu。

- AS11 [文章动态素材 / Inline media](https://claude.com/blog/claude-builds-visuals) — 截图与媒体DOM。同文组合YouTube视频、GIF操作演示和静态PNG；局部演示留在正文流内。 可映射：ArticleVideo · LoopFigure · MediaCaption。

- AS12 [动态图解文章 / Motion article](https://claude.com/resources/articles/dashboards-and-motion) — 媒体及结构核查。段落先说明用途，再配视频与操作截图；动效承载具体解释任务。 可映射：ExplainerFigure · Walkthrough。

- AS13 [教学任务 / Academy](https://academy.claude.com/use-cases/visualize-the-mechanism-behind-an-explanation-mid-chat) — 截图与DOM。色块导语、时间与主题标签、分步教程、可复制提示和右侧目录，形成教学节奏。 可映射：LessonIntro · PromptBlock · StepIndex。

- AS14 [开发者文档 / Docs](https://code.claude.com/docs/en/overview) — 截图与DOM。左侧分组导航、中间正文、右侧页内目录；安装方式用嵌套标签页，代码有局部工具。 可映射：DocsShell · CodeBlock · PlatformTabs。

## 测量与素材

1280 × 720 视口：Overview 大标题约67.71px / 74.49px，字体 anthropicSerif；Artifacts 的 h1 为17px无衬线标签，视觉主标题是p。角色不能按标签硬编码。不是全站固定token；中文使用原有Noto字体适配。

AS11文章主媒体约564.57 × 317.57px。YouTube iframe与一个1920 ×1080 GIF、一个PNG并存。未播放长视频，未测GIF完整时长，不宣称已掌握完整时序。

公开截图可能含扩展浮层（蓝色小助手），这是浏览环境，不是品牌组件。原站媒体只保留出处，未下载打包；小动画demo为原创CSS示意。

## MotionFigure 复用契约

mountMotionFigure(host, {title, duration})：默认静态，Play/Pause，Replay，离开Tab暂停，减少动态偏好启用时暂停。提供pause/destroy；标题用textContent；duration必须有限且>=1000ms。例示动画为解释流程，非真实业务数据。

尚未接入视频/GIF通用播放器；视频、循环素材和交互图各自的契约留作ES04.7，不能把本次CSS样例称为全部媒体组件完成。

## 设计决策

保留当前工作台认可的出版气质；产品、目录、教学、技术文档按任务组合不同容器。字体角色、间距基础和语义颜色可共享，不能把一种居中Hero复用于所有页面。

应用入口账户状态阻止进入：编辑器与Projects仅官方文档依据。登录、账号操作、Console实际运行、移动端及内部应用未验收。

## 有序路线

| ID | 项目 | 依赖 | 状态 |

|---|---|---|---|

| ES01.2 | 原站多场景与媒体研究 | ES01 | 本轮图谱交付；当前完成边界 |

| ES04.1–02 | 基础组件与中英PDF | ES02 | 已完成；PDF认可 |

| ES04.3 | 长文PDF分页 | ES04.2 | 暂缓 |

| ES04.4–05 | 页面组合、表单、菜单与反馈 | ES03 | 已交付；工作台风格认可 |

| ES01.3 | 客户故事与更多动态图解时序 | ES01.2 | 下一具体项，未开始 |

| ES04.6 | 日期、多选与全局检索 | ES04.5、ES01.2 | 队列，未开始 |

| ES04.7 | 文件树、复杂表格、画布与媒体 | ES04.6、原站依据 | 队列；仅本轮MotionFigure样例完成 |

| ES05 | 生产页面迁移 | ES04、明确页面范围 | 未开始 |

用户要求继续广泛研究，当前先完成ES01.2，ES04.6保留原顺序。客户故事与更多真实应用布局仍在研究队列，不能把14个来源称为全站穷尽。

验证：模块语法检查通过；浏览器动态素材筛选为2项，Play/Pause/Replay状态切换实际检查。后台暂停与减少动态监听已实现，但本轮未做系统设置切换与跨Tab专项验证。
