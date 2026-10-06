(() => {
  "use strict";

  // Source artwork is retained for every study. Color studies overlay it;
  // the one-shot entrance temporarily covers it, then restores it exactly.
  const materials = {
    glass: { src: "assets/uteki-glass.jpeg", size: [1376, 768], mark: [272, 186, 258, 342], word: [556, 298, 526, 155] },
    ink: { src: "assets/uteki-ink.png", size: [1024, 1536], mark: [244, 286, 536, 716], word: [230, 1030, 568, 173] },
    silk: { src: "assets/uteki-silk.jpeg", size: [922, 1152], mark: [318, 255, 292, 382], word: [267, 633, 399, 118] },
  };
  const storyboards = {
    ink: { src: "assets/motion/ink-study.png", fall: [12, 104, 465, 615], unfold: [550, 250, 430, 475], unfoldBounds: [500, 0, 540, 910] },
    blue: { src: "assets/motion/blue-study.png", fall: [12, 104, 465, 615], unfold: [550, 250, 430, 475], unfoldBounds: [500, 0, 540, 910] },
  };
  const storyboardImages = new Map();
  const copy = {
    zh: {
      impact: "入水成形", impactDescription: "一滴入水，细流舒展，凝成雨滴。10 秒，播放一次。", impactPlay: "播放入水成形", impactReplay: "再看一次", impactPaused: "已暂停", impactFall: "01 · 入水", impactBloom: "02 · 舒展", impactGather: "03 · 成形", impactDone: "雨滴已成形", impactUnavailable: "入水成形暂不可用，已保留原图。", motionProgress: "动画进度", storyboard: "查看设计分镜 ↗", motionLoading: "正在载入动效原画…", storyboardError: "动效原画未能加载，已保留此前图像，请重试。",
      ink: "墨滴", themeLabel: "明暗", light: "亮色 · 宣纸", dark: "暗色 · 夜墨", inkMarkLabel: "Uteki 水墨雨滴",
      inkFlow: "墨色漫游", inkSlide: "墨纹流转", inkFlowDescription: "浓淡相遇，墨色在两瓣之间缓缓漫游。", inkSlideDescription: "沿雨滴纹理，浓墨与淡墨交替流转。", inkHint: "墨色流转，留白如初", inkPaused: "墨色流动 · 已暂停", inkPlay: "播放墨色流动",
      pageName: "流动的品牌", edition: "Uteki 动态标识", stageHint: "保留原始形态与质感", focus: "纯净欣赏", exitFocus: "退出欣赏",
      introNote: "一滴之间，万象浮现", heading: "滴中，见微。", introCopy: "让信息流动，让洞察浮现。",
      materialLabel: "质感", glass: "琉璃蓝", silk: "丝绸蓝", viewLabel: "效果", original: "原图", colorFlow: "颜色流动", textureSlide: "纹理滑动",
      flowDescription: "冰蓝与深蓝，从水滴尖端缓缓流向底部。", strengthLabel: "变化幅度", subtle: "轻柔", clearer: "明显",
      slideDescription: "大块深浅蓝，顺着两瓣弧线缓缓滑过。", slidePaused: "纹理滑动 · 已暂停", slidePlay: "播放纹理滑动", slideHint: "大色块沿着水滴纹理滑动", slideUnavailable: "当前浏览器无法显示纹理滑动，已保留原图。",
      footerLine: "在流动中，发现清晰。", paused: "颜色流动 · 已暂停", play: "播放颜色流动", pause: "暂停动效", replay: "重新播放",
      reduced: "已遵循减少动态效果偏好，可手动播放。", unavailable: "当前浏览器无法显示颜色流动，已保留原图。", imageError: "原图未能加载，请重试。", loading: "正在载入原图…", stageLabel: "Logo 展示", controlsLabel: "Logo 展示控制", markLabel: "Uteki 蓝色水滴",
      focusHint: "空格暂停或继续 · Esc 退出", exitHint: "Esc 退出", staticHint: "保留原始形态与质感", flowHint: "只有颜色流动，形态保持不变",
    },
    en: {
      impact: "Ink to form", impactDescription: "A drop descends, delicate currents unfold, and the logo settles. A 10-second study.", impactPlay: "Play entrance", impactReplay: "Watch again", impactPaused: "Paused", impactFall: "01 · Descend", impactBloom: "02 · Unfold", impactGather: "03 · Resolve", impactDone: "Logo formed", impactUnavailable: "The entrance is unavailable. The original is preserved.", motionProgress: "Animation progress", storyboard: "View storyboard ↗", motionLoading: "Loading motion artwork…", storyboardError: "The motion artwork could not load. The previous image is preserved. Please try again.",
      ink: "Ink wash", themeLabel: "Appearance", light: "Light · Paper", dark: "Dark · Night", inkMarkLabel: "Uteki ink-wash drop",
      inkFlow: "Ink drift", inkSlide: "Ink currents", inkFlowDescription: "Deep and diluted ink drift slowly through the two ribbons.", inkSlideDescription: "Broad ink tones follow the folds of the drop.", inkHint: "Ink moves. The white river stays.", inkPaused: "Ink flow · Paused", inkPlay: "Play ink flow",
      pageName: "Identity in motion", edition: "Uteki motion study", stageHint: "Original shape and material", focus: "Focus view", exitFocus: "Exit focus",
      introNote: "A little motion. A deeper perspective.", heading: "A drop of insight.", introCopy: "Let information flow. Let insight emerge.",
      materialLabel: "Material", glass: "Blue glass", silk: "Blue silk", viewLabel: "Effect", original: "Original", colorFlow: "Color flow", textureSlide: "Texture slide",
      flowDescription: "Ice blue and deep blue travel from tip to base.", strengthLabel: "Intensity", subtle: "Subtle", clearer: "Pronounced",
      slideDescription: "Broad blue tones slide along the two curved ribbons.", slidePaused: "Texture slide · Paused", slidePlay: "Play texture slide", slideHint: "Broad colours follow the drop's texture", slideUnavailable: "Texture slide is unavailable in this browser. The original is preserved.",
      footerLine: "Find clarity in the flow.", paused: "Color flow · Paused", play: "Play color flow", pause: "Pause motion", replay: "Replay",
      reduced: "Reduced motion is on. Press play when you are ready.", unavailable: "Color flow is unavailable in this browser. The original is preserved.", imageError: "The original image could not load. Please try again.", loading: "Loading the original image…", stageLabel: "Logo preview", controlsLabel: "Logo preview controls", markLabel: "Uteki blue drop",
      focusHint: "Space to pause or play · Esc to exit", exitHint: "Esc to exit", staticHint: "Original shape and material", flowHint: "Color moves. The original shape stays.",
    },
  };
  const $ = (id) => document.getElementById(id);
  const stage = $("stage");
  const canvas = $("logo");
  const mark = $("mark-area");
  const original = $("mark-fallback");
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = { view: "original", material: "glass", theme: "light", lang: "zh", strength: 0.8, paused: true, reduced: media.matches, time: 0, focus: false, loaded: false, loading: false, imageError: false, storyboardError: false, rendererError: false };
  const IMPACT_DURATION = 10;
  const IMPACT_PADDING = 1.6;
  let impactStarted = false;
  let lastImpactPhase = "";
  let renderer = null;
  let rendererView = null;
  let rendererMaterial = null;
  let activeImage = null;
  let sequence = 0;
  let raf = null;
  let lastFrame = null;
  const images = new Map();
  // Each study keeps its own position and intensity when comparing effects.
  const effects = { flow: { time: 0, strength: 0.8 }, slide: { time: 0, strength: 0.8 }, impact: { time: 0, strength: 0.8 } };
  const isAnimated = () => Object.hasOwn(effects, state.view);
  function rememberEffect() {
    if (isAnimated()) effects[state.view] = { time: state.time, strength: state.strength };
  }

  function cancelLoop() {
    if (raf !== null) cancelAnimationFrame(raf);
    raf = null;
    lastFrame = null;
  }

  function impactPhase() {
    return state.time >= IMPACT_DURATION ? "impactDone" : state.time < 2.5 ? "impactFall" : state.time < 6 ? "impactBloom" : "impactGather";
  }

  function render() {
    const impact = state.view === "impact";
    const active = impact && impactStarted && state.time < IMPACT_DURATION && state.strength > 0;
    const show = isAnimated() && renderer && state.loaded && (!impact || active);
    canvas.classList.toggle("is-ready", Boolean(show));
    document.body.classList.toggle("is-impact-active", Boolean(show && active));
    const reveal = Math.max(0, Math.min(1, (state.time - 8) / 1.5));
    $("wordmark-group").style.opacity = show && active ? String(reveal * reveal * (3 - 2 * reveal)) : "1";
    if (impact) {
      $("motion-progress").value = String(state.time);
      $("motion-progress").style.setProperty("--range-fill", `${state.time / IMPACT_DURATION * 100}%`);
      $("motion-time").textContent = `${state.time.toFixed(1)} / 10 s`;
    }
    if (show) {
      try {
        const options = { time: state.time, strength: state.strength };
        if (impact) options.material = state.material;
        else if (state.material === "ink") options.mode = state.view;
        renderer.render(options);
      } catch (error) { console.warn("Logo rendering unavailable:", error.message); dropRenderer(); updateUi(); }
    }
  }

  function schedule() {
    if (raf === null && isAnimated() && !state.paused && !document.hidden && renderer && state.loaded && state.strength > 0) raf = requestAnimationFrame(tick);
  }

  function tick(timestamp) {
    raf = null;
    if (!isAnimated() || state.paused || document.hidden) { lastFrame = null; return; }
    const delta = lastFrame === null ? 0 : Math.min((timestamp - lastFrame) / 1000, 0.05);
    lastFrame = timestamp;
    // The renderer owns its loop period; the controller only tracks play time.
    state.time += delta;
    if (state.view === "impact") {
      if (state.time >= IMPACT_DURATION) { state.time = IMPACT_DURATION; state.paused = true; lastFrame = null; }
      const phase = impactPhase();
      if (phase !== lastImpactPhase) { lastImpactPhase = phase; updateUi(); }
    }
    render();
    schedule();
  }

  function updateUi() {
    const text = copy[state.lang];
    const slide = state.view === "slide";
    const ink = state.material === "ink";
    const moving = isAnimated();
    document.documentElement.setAttribute("data-theme", state.theme);
    document.body.setAttribute("data-palette", state.material);
    document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
    document.body.classList.toggle("is-original", state.view === "original");
    document.body.classList.toggle("is-impact", state.view === "impact");
    document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = text[node.dataset.i18n]; });
    $("language").textContent = state.lang === "zh" ? "EN ↗" : "中文 ↗";
    $("language").setAttribute("aria-label", state.lang === "zh" ? "Switch to English" : "切换中文");
    $("focus").querySelector("[data-i18n]").textContent = state.focus ? text.exitFocus : text.focus;
    document.querySelector('[data-i18n="stageHint"]').textContent = state.focus ? (moving ? text.focusHint : text.exitHint) : (moving ? (slide ? text.slideHint : text.flowHint) : text.staticHint);
    $("effect-description").textContent = ink ? (slide ? text.inkSlideDescription : text.inkFlowDescription) : (slide ? text.slideDescription : text.flowDescription);
    document.querySelectorAll("[data-view]").forEach((button) => {
      const label = button.querySelector("[data-i18n]");
      if (label && !["original", "impact"].includes(button.dataset.view)) label.textContent = ink ? (button.dataset.view === "slide" ? text.inkSlide : text.inkFlow) : (button.dataset.view === "slide" ? text.textureSlide : text.colorFlow);
    });
    $("state-label").textContent = !moving ? text.original : state.paused ? (slide ? text.slidePaused : text.paused) : (slide ? text.textureSlide : text.colorFlow);
    $("state-dot").classList.toggle("is-paused", state.view === "original" || state.paused);
    $("play-label").textContent = state.paused ? (slide ? text.slidePlay : text.play) : text.pause;
    $("play-icon").classList.toggle("is-playing", !state.paused);
    $("play").setAttribute("aria-pressed", String(state.paused));
    $("play").disabled = state.view === "original" || state.loading || !renderer;
    $("replay").disabled = $("play").disabled;
    $("replay").setAttribute("aria-label", text.replay);
    $("replay").title = text.replay;
    $("stage-replay").setAttribute("aria-label", text.replay);
    $("stage-replay").disabled = $("play").disabled;
    $("stage-play").textContent = state.paused ? "▶" : "Ⅱ";
    $("stage-play").setAttribute("aria-label", state.paused ? text.impactPlay : text.pause);
    $("stage-play").disabled = $("play").disabled;
    $("motion-progress").setAttribute("aria-label", text.motionProgress);
    $("motion-progress").disabled = state.view !== "impact" || state.loading || !renderer;
    $("storyboard-link").href = storyboards[ink ? "ink" : "blue"].src;
    $("strength").disabled = state.view === "original";
    $("strength").value = String(state.strength);
    $("strength-output").textContent = `${Math.round(state.strength * 100)}%`;
    $("strength").setAttribute("aria-valuetext", `${Math.round(state.strength * 100)}%`);
    $("strength").style.setProperty("--range-fill", `${state.strength * 100}%`);
    stage.setAttribute("aria-label", text.stageLabel);
    document.querySelector(".controls").setAttribute("aria-label", text.controlsLabel);
    mark.setAttribute("aria-label", ink ? text.inkMarkLabel : text.markLabel);
    if (ink) {
      $("state-label").textContent = !moving ? text.original : state.paused ? text.inkPaused : slide ? text.inkSlide : text.inkFlow;
      $("play-label").textContent = state.paused ? text.inkPlay : text.pause;
      if (!state.focus) document.querySelector('[data-i18n="stageHint"]').textContent = text.inkHint;
    }
    if (state.view === "impact") {
      $("effect-description").textContent = text.impactDescription;
      $("state-label").textContent = state.time >= IMPACT_DURATION ? text.impactDone : state.paused ? `${text[impactPhase()]} · ${text.impactPaused}` : text[impactPhase()];
      $("play-label").textContent = state.time >= IMPACT_DURATION ? text.impactReplay : state.paused ? text.impactPlay : text.pause;
      if (!state.focus) document.querySelector('[data-i18n="stageHint"]').textContent = text.impactDescription;
    }
    document.querySelectorAll("button[data-theme]").forEach((button) => {
      const selected = button.dataset.theme === state.theme;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
    });
    document.querySelectorAll("[data-view], [data-material]").forEach((button) => {
      const selected = button.dataset.view ? button.dataset.view === state.view : button.dataset.material === state.material;
      button.classList.toggle("is-selected", selected);
      button.setAttribute("aria-pressed", String(selected));
      button.disabled = state.loading || (!state.loaded && Boolean(button.dataset.view));
    });
    $("feedback").textContent = state.imageError ? text.imageError : state.storyboardError ? text.storyboardError : state.loading ? text.loading : state.rendererError ? (state.rendererError === "impact" ? text.impactUnavailable : state.rendererError === "slide" ? text.slideUnavailable : text.unavailable) : moving && state.paused && state.reduced ? text.reduced : "";
  }

  function applyCrop(node, material, crop) {
    const image = node.querySelector("img");
    image.src = material.src;
    image.style.width = `${material.size[0] / crop[2] * 100}%`;
    image.style.left = `${-crop[0] / crop[2] * 100}%`;
    image.style.top = `${-crop[1] / crop[3] * 100}%`;
    node.style.aspectRatio = `${crop[2]} / ${crop[3]}`;
  }

  function resize() {
    const rect = mark.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2) * (state.view === "impact" ? IMPACT_PADDING : 1);
    if (renderer) {
      try { renderer.resize(Math.max(1, Math.round(rect.width * ratio)), Math.max(1, Math.round(rect.height * ratio))); }
      catch (error) { console.warn("Color flow sizing unavailable:", error.message); dropRenderer(); updateUi(); }
    }
    render();
  }

  function dropRenderer() {
    rememberEffect();
    const failedView = rendererView || state.view;
    cancelLoop();
    if (renderer) renderer.dispose();
    renderer = null;
    rendererView = null;
    rendererMaterial = null;
    state.view = "original";
    state.paused = true;
    state.rendererError = failedView;
    canvas.classList.remove("is-ready");
    document.body.classList.remove("is-impact", "is-impact-active");
    $("wordmark-group").style.opacity = "1";
  }

  function prepareRenderer(view) {
    const family = state.material === "ink" ? "ink" : "blue";
    if (renderer && rendererView === view && rendererMaterial === family) {
      state.rendererError = false;
      return true;
    }
    if (renderer) renderer.dispose();
    renderer = null;
    rendererView = view;
    rendererMaterial = family;
    try {
      const Renderer = view === "impact" ? window.UtekiImpactRenderer : family === "ink" ? window.UtekiInkFlowRenderer : view === "slide" ? window.UtekiTextureSlideRenderer : window.UtekiColorFlowRenderer;
      renderer = new Renderer(canvas);
      renderer.setImage(activeImage, materials[state.material].mark);
      if (view === "impact") renderer.setStoryboard(storyboardImages.get(family), storyboards[family]);
      resize();
      if (!renderer) return false;
      state.rendererError = false;
      return true;
    } catch (error) {
      console.warn("Color flow unavailable:", error.message);
      dropRenderer();
      return false;
    }
  }

  function loadImage(src) {
    if (!images.has(src)) {
      images.set(src, new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => { images.delete(src); reject(new Error("Image load failed")); };
        image.src = src;
      }));
    }
    return images.get(src);
  }

  async function loadStoryboard(name) {
    const family = name === "ink" ? "ink" : "blue";
    if (!storyboardImages.has(family)) storyboardImages.set(family, await loadImage(storyboards[family].src));
    return storyboardImages.get(family);
  }

  async function selectMaterial(name) {
    if (!materials[name]) return;
    const request = ++sequence;
    state.loading = true;
    state.imageError = false;
    state.storyboardError = false;
    let loadingStoryboard = false;
    updateUi();
    try {
      const image = await loadImage(materials[name].src);
      if (state.view === "impact") {
        loadingStoryboard = true;
        await loadStoryboard(name);
        loadingStoryboard = false;
      }
      if (request !== sequence) return;
      state.material = name;
      activeImage = image;
      state.loaded = true;
      const material = materials[name];
      applyCrop(original, material, material.mark);
      applyCrop($("wordmark"), material, material.word);
      mark.style.aspectRatio = `${material.mark[2]} / ${material.mark[3]}`;
      if (renderer) {
        try {
          const family = name === "ink" ? "ink" : "blue";
          if (rendererMaterial !== family) {
            if (isAnimated()) prepareRenderer(state.view);
            else { renderer.dispose(); renderer = null; rendererView = null; rendererMaterial = null; }
          } else renderer.setImage(image, material.mark);
        }
        catch (error) { console.warn("Color flow image unavailable:", error.message); dropRenderer(); }
      }
      resize();
    } catch (error) {
      if (request === sequence) {
        state.storyboardError = loadingStoryboard;
        state.imageError = !loadingStoryboard;
      }
    } finally {
      if (request === sequence) {
        state.loading = false;
        updateUi();
        render();
        schedule();
      }
    }
  }

  async function selectView(view) {
    if (!state.loaded || state.loading || !["original", "flow", "slide", "impact"].includes(view)) return;
    rememberEffect();
    cancelLoop();
    state.storyboardError = false;
    if (view === "impact") {
      state.loading = true;
      updateUi();
      $("feedback").textContent = copy[state.lang].motionLoading;
      try { await loadStoryboard(state.material); }
      catch (error) {
        state.loading = false;
        state.rendererError = "impact";
        state.storyboardError = true;
        state.paused = true;
        updateUi();
        render();
        return;
      }
      state.loading = false;
    }
    if (view !== "original") {
      state.view = view;
      Object.assign(state, effects[view]);
      if (view === "impact") { state.time = 0; impactStarted = !state.reduced; lastImpactPhase = ""; }
      if (prepareRenderer(view)) state.paused = state.reduced;
    } else {
      state.view = "original";
      state.paused = true;
    }
    updateUi();
    render();
    schedule();
  }

  function setPaused(paused) {
    if (!isAnimated() || !renderer) return;
    state.paused = paused;
    if (state.view === "impact" && !paused) {
      if (state.time >= IMPACT_DURATION) state.time = 0;
      impactStarted = true; lastImpactPhase = "";
    }
    cancelLoop();
    updateUi();
    render();
    schedule();
  }

  function setFocus(focus) {
    state.focus = focus;
    document.body.classList.toggle("is-focused", focus);
    $("focus").setAttribute("aria-pressed", String(focus));
    for (const selector of [".masthead", ".controls", ".footer"]) document.querySelector(selector).inert = focus;
    updateUi();
    resize();
    (focus ? stage : $("focus")).focus({ preventScroll: true });
  }

  document.querySelectorAll("[data-material]").forEach((button) => button.addEventListener("click", () => selectMaterial(button.dataset.material)));
  document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => selectView(button.dataset.view)));
  document.querySelectorAll("button[data-theme]").forEach((button) => button.addEventListener("click", () => {
    state.theme = button.dataset.theme;
    try { window.localStorage.setItem("uteki.logo.theme", state.theme); } catch {}
    updateUi();
  }));
  $("play").addEventListener("click", () => setPaused(!state.paused));
  $("replay").addEventListener("click", () => { state.time = 0; render(); setPaused(false); });
  $("stage-play").addEventListener("click", () => setPaused(!state.paused));
  $("stage-replay").addEventListener("click", () => { state.time = 0; render(); setPaused(false); });
  $("motion-progress").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    if (state.view !== "impact" || !renderer || !Number.isFinite(value)) return;
    cancelLoop();
    state.time = Math.max(0, Math.min(IMPACT_DURATION, value));
    state.paused = true;
    impactStarted = true;
    lastImpactPhase = "";
    updateUi();
    render();
  });
  $("strength").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    if (!Number.isFinite(value)) return;
    state.strength = Math.max(0, Math.min(1, value));
    cancelLoop();
    updateUi();
    render();
    schedule();
  });
  $("language").addEventListener("click", () => { state.lang = state.lang === "zh" ? "en" : "zh"; updateUi(); });
  $("focus").addEventListener("click", () => setFocus(!state.focus));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.focus) setFocus(false);
    if (event.code === "Space" && (event.target === stage || event.target === document.body) && isAnimated()) { event.preventDefault(); setPaused(!state.paused); }
  });
  document.addEventListener("visibilitychange", () => { cancelLoop(); schedule(); });
  media.addEventListener("change", (event) => { state.reduced = event.matches; if (event.matches) setPaused(true); updateUi(); });
  canvas.addEventListener("webglcontextlost", (event) => { event.preventDefault(); dropRenderer(); updateUi(); });
  // On restoration keep the untouched original visible; explicit selection retries.
  canvas.addEventListener("webglcontextrestored", () => { state.rendererError = false; updateUi(); });
  if (typeof ResizeObserver === "function") new ResizeObserver(resize).observe(mark);
  window.addEventListener("resize", resize, { passive: true });
  let initialMaterial = "glass", initialView = "original";
  try { const saved = window.localStorage.getItem("uteki.logo.theme"); if (["light", "dark"].includes(saved)) state.theme = saved; } catch {}
  if (typeof URLSearchParams === "function" && window.location) {
    const params = new URLSearchParams(window.location.search);
    if (materials[params.get("material")]) initialMaterial = params.get("material");
    if (["original", "flow", "slide", "impact"].includes(params.get("view"))) initialView = params.get("view");
    if (["light", "dark"].includes(params.get("theme"))) state.theme = params.get("theme");
  }
  updateUi();
  selectMaterial(initialMaterial).then(() => { if (initialView !== "original" && state.loaded) selectView(initialView); });
})();
