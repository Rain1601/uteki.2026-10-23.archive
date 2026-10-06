(() => {
  "use strict";

  // Only the user's two original JPEGs are used. Crops are display coordinates;
  // the source files stay byte-for-byte intact. There is no SVG or remote asset.
  const materials = {
    glass: { src: "assets/uteki-glass.jpeg", size: [1376, 768], mark: [272, 186, 258, 342], word: [556, 298, 526, 155] },
    silk: { src: "assets/uteki-silk.jpeg", size: [922, 1152], mark: [318, 255, 292, 382], word: [267, 633, 399, 118] },
  };
  const copy = {
    zh: {
      pageName: "流动的品牌", edition: "Uteki 动态标识", stageHint: "移动光标，改变光的方向", focusHint: "空格暂停或继续 · Esc 退出", focus: "纯净欣赏", exitFocus: "退出欣赏",
      introNote: "一滴之间，万象浮现", heading: "滴中，见微。", introCopy: "让信息流动，让洞察浮现。<br>给一滴蓝，一点呼吸的空间。",
      motionLabel: "动效", materialLabel: "质感", speedLabel: "节奏", drift: "流动", ripple: "涟漪", breathe: "呼吸", glass: "琉璃蓝", silk: "丝绸蓝",
      slower: "舒缓", faster: "轻快", footerLine: "在流动中，发现清晰。", playing: "流动中", paused: "已暂停", play: "播放动效", pause: "暂停动效", replay: "重新播放",
      driftDescription: "宽幅光影沿着蓝色曲面缓缓流转。", rippleDescription: "柔和的起伏，从水滴的曲面掠过。", breatheDescription: "体积轻轻舒展，明暗随一次呼吸变化。",
      reduced: "已遵循减少动态效果偏好，可手动播放。", fallback: "当前显示轻量动效；此浏览器未启用液态光影。", imageError: "原图未能加载，请刷新页面重试。", loading: "正在载入原图…", speedSuffix: " 倍速", stageLabel: "Logo 动态展示", controlsLabel: "动效控制", markLabel: "Uteki 蓝色水滴",
    },
    en: {
      pageName: "Identity in motion", edition: "Uteki motion study", stageHint: "Move your cursor. Follow the light.", focusHint: "Space to pause or play · Esc to exit", focus: "Focus view", exitFocus: "Exit focus",
      introNote: "A little motion. A deeper perspective.", heading: "A drop of insight.", introCopy: "Let information flow. Let insight emerge.<br>A little room for blue to breathe.",
      motionLabel: "Motion", materialLabel: "Material", speedLabel: "Tempo", drift: "Flow", ripple: "Ripple", breathe: "Breathe", glass: "Blue glass", silk: "Blue silk",
      slower: "Unhurried", faster: "Lively", footerLine: "Find clarity in the flow.", playing: "In motion", paused: "Paused", play: "Play motion", pause: "Pause motion", replay: "Replay",
      driftDescription: "Broad reflections travel along the blue surface.", rippleDescription: "A gentle swell moves through the curved surface.", breatheDescription: "Volume expands gently. Light follows each breath.",
      reduced: "Reduced motion is on. Press play when you are ready.", fallback: "Lightweight motion is active. Liquid shading is unavailable in this browser.", imageError: "The original image could not load. Refresh to try again.", loading: "Loading the original image…", speedSuffix: " times speed", stageLabel: "Animated logo preview", controlsLabel: "Motion controls", markLabel: "Uteki blue drop",
    },
  };

  const $ = (id) => document.getElementById(id);
  // The volume experiment was rejected. The public page loads only the
  // original-image viewer; the experimental renderer is deliberately unlinked.
  const originalOnly = typeof window.UtekiVolumeRenderer !== "function";
  const stage = $("stage");
  const canvas = $("logo");
  const ambient = $("atmosphere");
  const ctx = ambient.getContext("2d");
  const motion = $("mark-motion");
  const markArea = $("mark-area");
  const fallback = $("mark-fallback");
  const media = window.matchMedia("(prefers-reduced-motion: reduce)");
  const state = { effect: "drift", material: "glass", speed: 1, time: 0, paused: originalOnly || media.matches, reduced: media.matches, lang: "zh", focus: false, loaded: false, failed: false, width: 0, height: 0, pointer: { x: 0, y: 0 }, target: { x: 0, y: 0 } };
  let lastFrame = null;
  let raf = null;
  let gpu = null;
  let activeImage = null;
  let loadSequence = 0;
  let surface = { x: 0, y: 0, width: 0, height: 0 };
  const images = new Map();

  function initGpu() {
    if (originalOnly) return null;
    try {
      return new window.UtekiVolumeRenderer(canvas);
    } catch (error) {
      console.warn("Uteki volume renderer unavailable:", error.message);
      return null;
    }
  }

  function dropGpu() {
    if (gpu) gpu.dispose();
    gpu = null;
    canvas.classList.remove("is-ready");
    fallback.classList.remove("is-hidden");
  }

  function applyCrop(element, material, crop) {
    const img = element.querySelector("img");
    img.src = material.src;
    img.style.width = `${material.size[0] / crop[2] * 100}%`;
    img.style.left = `${-crop[0] / crop[2] * 100}%`;
    img.style.top = `${-crop[1] / crop[3] * 100}%`;
    element.style.aspectRatio = `${crop[2]} / ${crop[3]}`;
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

  function uploadImage(image, material) {
    if (!gpu) return;
    try {
      gpu.setImage(image, material.mark, state.material);
      canvas.classList.add("is-ready");
      fallback.classList.add("is-hidden");
    } catch (error) {
      console.warn("Uteki volume initialization unavailable:", error.message);
      dropGpu();
    }
  }

  async function selectMaterial(name) {
    if (!materials[name]) return;
    const sequence = ++loadSequence;
    state.failed = false;
    const buttons = document.querySelectorAll("[data-material]");
    buttons.forEach((button) => { button.disabled = true; });
    $("feedback").textContent = copy[state.lang].loading;
    try {
      const image = await loadImage(materials[name].src);
      if (sequence !== loadSequence) return;
      state.material = name;
      activeImage = image;
      state.loaded = true;
      const material = materials[name];
      applyCrop(fallback, material, material.mark);
      applyCrop($("wordmark"), material, material.word);
      markArea.style.aspectRatio = `${material.mark[2]} / ${material.mark[3]}`;
      uploadImage(image, material);
      resize();
    } catch (error) {
      if (sequence === loadSequence) state.failed = true;
    } finally {
      if (sequence === loadSequence) {
        buttons.forEach((button) => { button.disabled = false; });
        updateUi();
        render();
        schedule();
      }
    }
  }

  function updateUi() {
    const strings = copy[state.lang];
    document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach((element) => {
      const key = element.dataset.i18n;
      // All translated HTML is static, authored here (only introCopy uses <br>).
      if (key === "introCopy") element.innerHTML = strings[key];
      else element.textContent = strings[key];
    });
    $("focus").querySelector("[data-i18n]").textContent = state.focus ? strings.exitFocus : strings.focus;
    if (state.focus) document.querySelector('[data-i18n="stageHint"]').textContent = strings.focusHint;
    $("language").innerHTML = `${state.lang === "zh" ? "EN" : "中文"} <span aria-hidden="true">↗</span>`;
    $("language").setAttribute("aria-label", state.lang === "zh" ? "Switch to English" : "切换中文");
    $("effect-description").textContent = strings[`${state.effect}Description`];
    $("play-label").textContent = state.paused ? strings.play : strings.pause;
    $("play-icon").classList.toggle("is-playing", !state.paused);
    $("play").setAttribute("aria-pressed", String(state.paused));
    $("state-label").textContent = state.paused ? strings.paused : strings.playing;
    $("state-dot").classList.toggle("is-paused", state.paused);
    $("replay").setAttribute("aria-label", strings.replay);
    $("replay").title = strings.replay;
    $("speed").setAttribute("aria-valuetext", `${state.speed}${strings.speedSuffix}`);
    stage.setAttribute("aria-label", strings.stageLabel);
    document.querySelector(".controls").setAttribute("aria-label", strings.controlsLabel);
    markArea.setAttribute("aria-label", strings.markLabel);
    document.querySelectorAll("[data-effect], [data-material]").forEach((button) => {
      const active = button.dataset.effect ? button.dataset.effect === state.effect : button.dataset.material === state.material;
      button.classList.toggle("is-selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    $("feedback").textContent = state.failed ? strings.imageError : !state.loaded ? strings.loading : !gpu ? strings.fallback : state.reduced && state.paused ? strings.reduced : "";
    document.body.classList.toggle("is-original", originalOnly);
    if (originalOnly) {
      $("state-label").textContent = state.lang === "zh" ? "原图" : "Original";
      document.querySelector('[data-i18n="stageHint"]').textContent = state.focus ? (state.lang === "zh" ? "Esc 退出" : "Esc to exit") : (state.lang === "zh" ? "保留原始形态与质感" : "Original shape and material");
      if (state.loaded && !state.failed) $("feedback").textContent = state.lang === "zh" ? "已恢复原图。动态版本待重新制作。" : "Original artwork restored. Motion is being reconsidered.";
    }
  }

  function resize() {
    const stageRect = stage.getBoundingClientRect();
    state.width = stageRect.width;
    state.height = stageRect.height;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    ambient.width = Math.round(state.width * ratio);
    ambient.height = Math.round(state.height * ratio);
    if (ctx) ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    const markRect = markArea.getBoundingClientRect();
    surface = { x: markRect.left - stageRect.left, y: markRect.top - stageRect.top, width: markRect.width, height: markRect.height };
    canvas.width = Math.max(1, Math.round(markRect.width * ratio));
    canvas.height = Math.max(1, Math.round(markRect.height * ratio));
    if (gpu) gpu.resize(canvas.width, canvas.height);
    render();
  }

  function drawAtmosphere() {
    if (!ctx) return;
    ctx.clearRect(0, 0, state.width, state.height);
    const cx = surface.x + surface.width / 2;
    const floor = surface.y + surface.height + 9;
    const pulse = state.effect === "breathe" ? Math.sin(state.time * 0.72) : 0;
    const radius = surface.width * (0.42 + pulse * 0.012);
    const shadow = ctx.createRadialGradient(cx, floor, 0, cx, floor, radius);
    shadow.addColorStop(0, "rgba(35, 92, 148, 0.13)");
    shadow.addColorStop(0.35, "rgba(81, 136, 181, 0.07)");
    shadow.addColorStop(1, "rgba(140, 179, 216, 0)");
    ctx.save();
    ctx.translate(cx, floor);
    ctx.scale(1, 0.1);
    ctx.translate(-cx, -floor);
    ctx.fillStyle = shadow;
    ctx.fillRect(cx - radius, floor - radius, radius * 2, radius * 2);
    ctx.restore();
  }

  function render() {
    if (originalOnly) {
      motion.style.transform = "none";
      if (ctx) ctx.clearRect(0, 0, state.width, state.height);
      return;
    }
    const t = state.time;
    const breath = Math.sin(t * 0.72);
    const floating = state.effect === "breathe" ? breath * -1.4 : Math.sin(t * 0.48) * 1.8;
    // Volume, normals and perspective are rendered inside WebGL, not CSS tilt.
    const fallbackScale = !gpu && state.effect === "breathe" ? 1 + breath * 0.014 : 1;
    motion.style.transform = `translate3d(0, ${floating.toFixed(3)}px, 0) scale(${fallbackScale.toFixed(5)})`;
    if (gpu && state.loaded) gpu.render({ time: t, mode: state.effect, pointer: state.pointer });
    drawAtmosphere();
  }

  function schedule() {
    if (originalOnly) return;
    if (raf === null && !state.paused && !document.hidden && state.loaded) raf = requestAnimationFrame(tick);
  }

  function tick(timestamp) {
    raf = null;
    if (state.paused || document.hidden) { lastFrame = null; return; }
    const elapsed = lastFrame === null ? 0 : Math.min((timestamp - lastFrame) / 1000, 0.05);
    lastFrame = timestamp;
    state.time += elapsed * state.speed;
    const damping = 1 - Math.exp(-elapsed * 4);
    state.pointer.x += (state.target.x - state.pointer.x) * damping;
    state.pointer.y += (state.target.y - state.pointer.y) * damping;
    render();
    schedule();
  }

  function cancelLoop() {
    if (raf !== null) cancelAnimationFrame(raf);
    raf = null;
    lastFrame = null;
  }

  function setPaused(paused) {
    state.paused = originalOnly || paused;
    cancelLoop();
    updateUi();
    if (!paused) schedule();
  }

  function setFocus(focus) {
    state.focus = focus;
    document.body.classList.toggle("is-focused", focus);
    $("focus").setAttribute("aria-pressed", String(focus));
    // Keep keyboard focus in the visible surface while the studio fills the window.
    for (const selector of [".masthead", ".controls", ".footer"]) document.querySelector(selector).inert = focus;
    updateUi();
    resize();
    (focus ? stage : $("focus")).focus({ preventScroll: true });
  }

  document.querySelectorAll("[data-effect]").forEach((button) => button.addEventListener("click", () => {
    state.effect = button.dataset.effect;
    updateUi();
    render();
  }));
  document.querySelectorAll("[data-material]").forEach((button) => button.addEventListener("click", () => selectMaterial(button.dataset.material)));
  $("play").addEventListener("click", () => setPaused(!state.paused));
  $("replay").addEventListener("click", () => {
    state.time = 0;
    state.pointer = { x: 0, y: 0 };
    state.target = { x: 0, y: 0 };
    render();
    setPaused(false);
  });
  $("speed").addEventListener("input", (event) => {
    const value = Number(event.target.value);
    if (!Number.isFinite(value)) return;
    state.speed = Math.max(0.5, Math.min(1.5, value));
    $("speed-output").textContent = `${state.speed}×`;
    event.target.style.setProperty("--range-fill", `${(state.speed - 0.5) * 100}%`);
    event.target.setAttribute("aria-valuetext", `${state.speed}${copy[state.lang].speedSuffix}`);
  });
  $("language").addEventListener("click", () => { state.lang = state.lang === "zh" ? "en" : "zh"; updateUi(); });
  $("focus").addEventListener("click", () => setFocus(!state.focus));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.focus) setFocus(false);
    // Native button and slider keys remain untouched. Space on the stage pauses.
    if (event.code === "Space" && (event.target === document.body || event.target === stage)) { event.preventDefault(); setPaused(!state.paused); }
  });
  stage.addEventListener("pointermove", (event) => {
    if (event.pointerType === "touch" || state.paused) return;
    const rect = stage.getBoundingClientRect();
    state.target.x = Math.max(-1, Math.min(1, (event.clientX - rect.left) / rect.width * 2 - 1));
    state.target.y = Math.max(-1, Math.min(1, (event.clientY - rect.top) / rect.height * 2 - 1));
  });
  stage.addEventListener("pointerleave", () => { state.target = { x: 0, y: 0 }; });
  document.addEventListener("visibilitychange", () => { cancelLoop(); schedule(); });
  media.addEventListener("change", (event) => { state.reduced = event.matches; if (event.matches) setPaused(true); else updateUi(); });
  canvas.addEventListener("webglcontextlost", (event) => {
    event.preventDefault();
    dropGpu();
    updateUi();
  });
  canvas.addEventListener("webglcontextrestored", () => {
    gpu = initGpu();
    if (activeImage) uploadImage(activeImage, materials[state.material]);
    resize();
    updateUi();
  });

  gpu = initGpu();
  if (typeof ResizeObserver === "function") new ResizeObserver(resize).observe(stage);
  window.addEventListener("resize", resize, { passive: true });
  updateUi();
  resize();
  selectMaterial("glass");
})();
