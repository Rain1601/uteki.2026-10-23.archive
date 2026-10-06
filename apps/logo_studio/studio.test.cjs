"use strict";

// Controller behavior only: minimal DOM, image and renderer substitutes.
// These checks do not compile shaders, exercise a GPU, or assess appearance.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const vm = require("node:vm");
const source = fs.readFileSync(path.join(__dirname, "studio.js"), "utf8");

function makeHarness({ reduced = false, rendererPresent = true, initializationFails = false, slideRendererPresent = true, slideInitializationFails = false, inkRendererPresent = true, impactRendererPresent = true, search = "" } = {}) {
  const frames = new Map(), pendingImages = new Map();
  const renders = [], uploads = [], storyboardUploads = [], renderers = [], warnings = [];
  const faults = { initializationFails, slideInitializationFails, uploadFailures: 0, slideUploadFailures: 0, slideRenderFailures: 0 };
  let constructorCalls = 0, frameId = 0, document;
  class Element {
    constructor(dataset = {}) {
      this.dataset = dataset;
      this.listeners = new Map(); this.attributes = new Map(); this.children = new Map();
      this.textContent = ""; this.disabled = false; this.inert = false;
      this.style = { setProperty(name, value) { this[name] = value; } };
      const classes = new Set();
      this.classList = {
        add: (...names) => names.forEach((name) => classes.add(name)),
        remove: (...names) => names.forEach((name) => classes.delete(name)),
        contains: (name) => classes.has(name),
        toggle(name, force) {
          const selected = force === undefined ? !classes.has(name) : force;
          if (selected) classes.add(name); else classes.delete(name);
          return selected;
        },
      };
    }
    addEventListener(name, callback) {
      if (!this.listeners.has(name)) this.listeners.set(name, []);
      this.listeners.get(name).push(callback);
    }
    dispatch(name, fields = {}) {
      const event = { target: this, preventDefault() { this.defaultPrevented = true; }, ...fields };
      for (const callback of this.listeners.get(name) || []) callback(event);
      return event;
    }
    click() { if (!this.disabled) this.dispatch("click"); }
    setAttribute(name, value) { this.attributes.set(name, value); }
    getAttribute(name) { return this.attributes.get(name); }
    querySelector(selector) { return this.children.get(selector) || null; }
    getBoundingClientRect() { return this.rect || { left: 0, top: 0, width: 800, height: 700 }; }
    focus() { document.activeElement = this; }
  }
  const ids = Object.fromEntries([
    "stage", "logo", "wordmark-group", "mark-motion", "mark-area", "mark-fallback", "wordmark", "feedback",
    "focus", "language", "play-label", "play-icon", "play", "state-label", "state-dot",
    "replay", "strength", "strength-output", "effect-description",
    "stage-play", "stage-replay", "motion-progress", "motion-time", "storyboard-link",
  ].map((id) => [id, new Element()]));
  const sections = Object.fromEntries([".masthead", ".controls", ".footer"].map((name) => [name, new Element()]));
  const views = ["original", "flow", "slide", "impact"].map((view) => new Element({ view }));
  const themes = ["light", "dark"].map((theme) => new Element({ theme }));
  const materials = ["glass", "silk", "ink"].map((material) => new Element({ material }));
  const focusText = new Element({ i18n: "focus" }), stageHint = new Element({ i18n: "stageHint" });
  ids.focus.children.set("[data-i18n]", focusText);
  ids["mark-fallback"].children.set("img", new Element());
  ids.wordmark.children.set("img", new Element());
  ids["mark-area"].rect = { left: 200, top: 130, width: 258, height: 342 };
  class Renderer {
    constructor(canvas, kind) {
      constructorCalls++;
      assert.equal(canvas, ids.logo);
      if (kind === "flow" ? faults.initializationFails : faults.slideInitializationFails) throw new Error("Simulated WebGL initialization failure");
      this.kind = kind;
      this.frames = [];
      renderers.push(this);
    }
    setImage(image, crop) {
      if (this.kind === "slide" && faults.slideUploadFailures > 0) {
        faults.slideUploadFailures--;
        throw new Error("Simulated slide image upload failure");
      }
      if (faults.uploadFailures > 0) {
        faults.uploadFailures--;
        throw new Error("Simulated image upload failure");
      }
      this.image = image;
      uploads.push({ src: image.src, crop: [...crop] });
    }
    setStoryboard(image, config) {
      assert.ok(image, "Entrance renderer requires a loaded storyboard");
      this.storyboard = image;
      storyboardUploads.push({ src: image.src, original: this.image.src, config: JSON.parse(JSON.stringify(config)) });
    }
    resize(width, height) { this.size = [width, height]; }
    render(options) {
      assert.equal(this.disposed, undefined, "Disposed renderers must not receive frames");
      if (this.kind === "slide" && faults.slideRenderFailures > 0) {
        faults.slideRenderFailures--;
        throw new Error("Simulated slide rendering failure");
      }
      if (this.kind === "impact") {
        assert.ok(this.storyboard, "Entrance rendering must wait for its storyboard");
        const family = options.material === "ink" ? "ink" : "blue";
        assert.equal(this.storyboard.src, `assets/motion/${family}-study.png`, "Do not render another material's storyboard");
      }
      this.frames.push({ ...options });
      renders.push({ ...options });
    }
    dispose() { this.disposed = true; }
  }
  document = new Element();
  document.hidden = false; document.documentElement = new Element(); document.body = new Element();
  document.activeElement = document.body;
  document.getElementById = (id) => { assert.ok(ids[id], `Missing harness element: ${id}`); return ids[id]; };
  document.querySelector = (selector) => selector === '[data-i18n="stageHint"]' ? stageHint : sections[selector] || null;
  document.querySelectorAll = (selector) => {
    if (selector === "button[data-theme]") return themes;
    if (selector === "[data-view]") return views;
    if (selector === "[data-material]") return materials;
    if (selector === "[data-view], [data-material]") return [...views, ...materials];
    if (selector === "[data-i18n]") return [focusText, stageHint];
    throw new Error(`Missing harness selector: ${selector}`);
  };
  const media = new Element(), window = new Element();
  window.location = { search };
  const saved = new Map();
  window.localStorage = { getItem: key => saved.get(key), setItem: (key, value) => saved.set(key, value) };
  media.matches = reduced; window.matchMedia = () => media; window.devicePixelRatio = 1;
  if (rendererPresent) window.UtekiColorFlowRenderer = class extends Renderer { constructor(canvas) { super(canvas, "flow"); } };
  if (slideRendererPresent) window.UtekiTextureSlideRenderer = class extends Renderer { constructor(canvas) { super(canvas, "slide"); } };
  if (inkRendererPresent) window.UtekiInkFlowRenderer = class extends Renderer { constructor(canvas) { super(canvas, "ink"); } };
  if (impactRendererPresent) window.UtekiImpactRenderer = class extends Renderer { constructor(canvas) { super(canvas, "impact"); } };
  class Image {
    set src(src) { this.source = src; pendingImages.set(src, this); }
    get src() { return this.source; }
  }
  vm.runInContext(source, vm.createContext({
    document, window, Image, URLSearchParams, console: { warn: (...args) => warnings.push(args) },
    requestAnimationFrame(callback) { const id = ++frameId; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
  }), { filename: "studio.js" });
  return {
    ids, views, materials, themes, saved, sections, document, media, faults, renders, uploads, storyboardUploads, renderers, warnings,
    get constructorCalls() { return constructorCalls; },
    get queuedFrames() { return frames.size; },
    get time() { return renders.at(-1)?.time; },
    frame(timestamp) {
      const queued = [...frames.values()]; frames.clear();
      queued.forEach((callback) => callback(timestamp));
    },
    async settleImage(material = "glass", succeeds = true) {
      const src = `assets/uteki-${material}.${material === "ink" ? "png" : "jpeg"}`, image = pendingImages.get(src);
      assert.ok(image, `Expected pending image: ${src}`); pendingImages.delete(src);
      if (succeeds) image.onload(); else image.onerror();
      await new Promise((resolve) => setImmediate(resolve));
    },
    async settleStoryboard(material = "glass", succeeds = true) {
      const family = material === "ink" ? "ink" : "blue";
      const src = `assets/motion/${family}-study.png`, image = pendingImages.get(src);
      assert.ok(image, `Expected pending storyboard: ${src}`); pendingImages.delete(src);
      if (succeeds) image.onload(); else image.onerror();
      await new Promise((resolve) => setImmediate(resolve));
    },
    async flush() { await new Promise((resolve) => setImmediate(resolve)); },
    scrub(value) { ids["motion-progress"].value = String(value); ids["motion-progress"].dispatch("input"); },
    setStrength(value) { ids.strength.value = String(value); ids.strength.dispatch("input"); },
    visibility(hidden) { document.hidden = hidden; document.dispatch("visibilitychange"); },
  };
}
function closeTo(actual, expected) {
  assert.ok(Math.abs(actual - expected) < 1e-10, `${actual} should equal ${expected}`);
}
function assertOriginalPreserved(h, material = "glass") {
  const fallback = h.ids["mark-fallback"];
  assert.equal(fallback.classList.contains("is-hidden"), false);
  for (const property of ["display", "visibility", "opacity"]) assert.equal(fallback.style[property], undefined);
  assert.equal(fallback.querySelector("img").src, `assets/uteki-${material}.${material === "ink" ? "png" : "jpeg"}`);
  assert.equal(h.ids.wordmark.querySelector("img").src, `assets/uteki-${material}.${material === "ink" ? "png" : "jpeg"}`);
  for (const id of ["mark-motion", "mark-area", "mark-fallback", "wordmark", "logo"]) {
    assert.equal(h.ids[id].style.transform, undefined, `${id} should keep its original transform`);
  }
}

test("default original view constructs no GPU renderer and schedules no frames", async () => {
  const h = makeHarness();
  assert.equal(h.constructorCalls, 0); assert.equal(h.queuedFrames, 0);
  await h.settleImage();
  assert.equal(h.constructorCalls, 0); assert.equal(h.renders.length, 0); assert.equal(h.queuedFrames, 0);
  assert.equal(h.document.body.classList.contains("is-original"), true);
  assert.equal(h.ids.play.disabled, true); assert.equal(h.ids.strength.disabled, true);
  assertOriginalPreserved(h);
  h.materials[1].click(); await h.settleImage("silk");
  assertOriginalPreserved(h, "silk");
  assert.equal(h.constructorCalls, 0); assert.equal(h.queuedFrames, 0);
});

test("explicit flow adds an overlay without hiding, moving, or replacing the artwork", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  assert.equal(h.constructorCalls, 1); assert.equal(h.queuedFrames, 1);
  assert.equal(h.ids.logo.classList.contains("is-ready"), true);
  assert.equal(h.document.body.classList.contains("is-original"), false);
  assert.deepEqual(h.uploads[0], { src: "assets/uteki-glass.jpeg", crop: [272, 186, 258, 342] });
  assert.deepEqual(h.renderers[0].size, [258, 342]);
  assert.deepEqual(h.renders.at(-1), { time: 0, strength: 0.8 });
  h.frame(1000); h.frame(1020); closeTo(h.time, 0.02);
  assertOriginalPreserved(h);
  assert.equal(h.views[1].getAttribute("aria-pressed"), "true"); assert.equal(h.ids.play.disabled, false);
});

test("returning to original removes the overlay and stops scheduling", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.frame(1000); h.views[0].click();
  assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.equal(h.document.body.classList.contains("is-original"), true);
  assert.equal(h.queuedFrames, 0); assert.equal(h.ids.play.disabled, true);
  const count = h.renders.length; h.frame(100000); assert.equal(h.renders.length, count);
  assertOriginalPreserved(h);
});

test("elapsed time crosses renderer periods and pause resumes without counting paused time", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.frame(1000);
  for (let step = 1; step <= 500; step++) {
    h.frame(1000 + step * 20);
    if (step === 301 || step === 451) closeTo(h.time, step * 0.02);
  }
  closeTo(h.time, 10);
  h.ids.play.click(); assert.equal(h.queuedFrames, 0);
  const count = h.renders.length; h.frame(100000); assert.equal(h.renders.length, count);
  assert.equal(h.ids.play.getAttribute("aria-pressed"), "true");
  h.ids.play.click(); assert.equal(h.queuedFrames, 1);
  h.frame(100000); closeTo(h.time, 10); h.frame(100020); closeTo(h.time, 10.02);
});

test("hidden tabs stop work and resume without counting hidden time or undoing a pause", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.frame(1000); h.frame(1020);
  h.visibility(true); assert.equal(h.queuedFrames, 0);
  h.visibility(false); assert.equal(h.queuedFrames, 1);
  h.frame(100000); closeTo(h.time, 0.02); h.frame(100020); closeTo(h.time, 0.04);
  h.ids.play.click(); h.visibility(true); h.visibility(false); assert.equal(h.queuedFrames, 0);
});

test("zero intensity sends strength zero and stops work; a positive value resumes", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.frame(1000); h.frame(1020);
  h.setStrength(0);
  assert.deepEqual(h.renders.at(-1), { time: 0.02, strength: 0 });
  assert.equal(h.queuedFrames, 0); assert.equal(h.ids["strength-output"].textContent, "0%");
  assertOriginalPreserved(h);
  h.setStrength(0.8); assert.equal(h.queuedFrames, 1); assert.equal(h.renders.at(-1).strength, 0.8);
  h.frame(100000); closeTo(h.time, 0.02); h.frame(100020); closeTo(h.time, 0.04);
  h.setStrength(100); assert.equal(h.renders.at(-1).strength, 1);
  h.setStrength("invalid"); assert.equal(h.renders.at(-1).strength, 1);
  h.setStrength(-5); assert.equal(h.renders.at(-1).strength, 0); assert.equal(h.queuedFrames, 0);
});

test("reduced motion keeps original by default and requires explicit play after selecting flow", async () => {
  const h = makeHarness({ reduced: true }); await h.settleImage();
  assert.equal(h.constructorCalls, 0); assert.equal(h.queuedFrames, 0);
  assert.equal(h.document.body.classList.contains("is-original"), true);
  h.views[1].click();
  assert.equal(h.ids.logo.classList.contains("is-ready"), true); assert.equal(h.queuedFrames, 0);
  assert.equal(h.ids.play.getAttribute("aria-pressed"), "true"); assert.match(h.ids.feedback.textContent, /减少动态效果/);
  h.ids.play.click(); assert.equal(h.queuedFrames, 1);
  h.frame(1000); h.frame(1020); closeTo(h.time, 0.02);
  h.media.dispatch("change", { matches: true }); assert.equal(h.queuedFrames, 0);
});

test("failed image loading preserves the previous material and permits a fresh retry", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.materials[1].click();
  assert.ok(h.materials.every((button) => button.disabled)); await h.settleImage("silk", false);
  assertOriginalPreserved(h); assert.equal(h.uploads.length, 1);
  assert.equal(h.materials[0].getAttribute("aria-pressed"), "true");
  assert.match(h.ids.feedback.textContent, /原图未能加载/); assert.ok(h.materials.every((button) => !button.disabled));
  h.materials[1].click(); await h.settleImage("silk");
  assertOriginalPreserved(h, "silk"); assert.deepEqual(h.uploads.at(-1).crop, [318, 255, 292, 382]);
  assert.equal(h.materials[1].getAttribute("aria-pressed"), "true");
  assert.equal(h.ids.feedback.textContent, ""); assert.equal(h.queuedFrames, 1);
});

test("renderer initialization failure preserves original and reports a renderer error", async () => {
  for (const options of [{ initializationFails: true }, { rendererPresent: false }]) {
    const h = makeHarness(options); await h.settleImage(); h.views[1].click();
    assertOriginalPreserved(h); assert.equal(h.ids.logo.classList.contains("is-ready"), false);
    assert.equal(h.document.body.classList.contains("is-original"), true);
    assert.equal(h.queuedFrames, 0); assert.equal(h.ids.play.disabled, true);
    assert.match(h.ids.feedback.textContent, /无法显示颜色流动，已保留原图/);
    assert.doesNotMatch(h.ids.feedback.textContent, /原图未能加载/); assert.equal(h.warnings.length, 1);
  }
});

test("initial upload failure disposes the renderer and explicit flow selection can retry", async () => {
  const h = makeHarness(); await h.settleImage(); h.faults.uploadFailures = 1; h.views[1].click();
  assert.equal(h.renderers[0].disposed, true); assertOriginalPreserved(h);
  assert.equal(h.queuedFrames, 0); assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.match(h.ids.feedback.textContent, /无法显示颜色流动/);
  h.views[1].click(); assert.equal(h.constructorCalls, 2);
  assert.equal(h.ids.logo.classList.contains("is-ready"), true);
  assert.equal(h.ids.feedback.textContent, ""); assert.equal(h.queuedFrames, 1);
});

test("upload failure on material change still shows the successfully loaded original", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  h.faults.uploadFailures = 1; h.materials[1].click(); await h.settleImage("silk");
  assertOriginalPreserved(h, "silk"); assert.equal(h.renderers[0].disposed, true);
  assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.equal(h.document.body.classList.contains("is-original"), true); assert.equal(h.queuedFrames, 0);
  assert.match(h.ids.feedback.textContent, /无法显示颜色流动/); assert.doesNotMatch(h.ids.feedback.textContent, /原图未能加载/);
});

test("Escape exits focus, restores controls and returns keyboard focus", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click(); h.ids.focus.click();
  assert.equal(h.document.body.classList.contains("is-focused"), true);
  assert.ok(Object.values(h.sections).every((section) => section.inert)); assert.equal(h.document.activeElement, h.ids.stage);
  const stageKey = h.document.dispatch("keydown", { code: "Space", target: h.ids.stage });
  assert.equal(stageKey.defaultPrevented, true); assert.equal(h.queuedFrames, 0);
  h.document.dispatch("keydown", { key: "Escape", target: h.ids.stage });
  assert.equal(h.document.body.classList.contains("is-focused"), false);
  assert.ok(Object.values(h.sections).every((section) => !section.inert));
  assert.equal(h.ids.focus.getAttribute("aria-pressed"), "false"); assert.equal(h.document.activeElement, h.ids.focus);
  const buttonKey = h.document.dispatch("keydown", { code: "Space", target: h.ids.play });
  assert.equal(buttonKey.defaultPrevented, undefined); assert.equal(h.queuedFrames, 0);
});

test("explicit slide uses its own renderer while keeping the original artwork visible", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[2].click();
  assert.equal(h.constructorCalls, 1); assert.equal(h.renderers[0].kind, "slide");
  assert.equal(h.ids.logo.classList.contains("is-ready"), true); assert.equal(h.queuedFrames, 1);
  assert.equal(h.views[2].getAttribute("aria-pressed"), "true"); assert.equal(h.views[1].getAttribute("aria-pressed"), "false");
  assert.deepEqual(h.uploads[0], { src: "assets/uteki-glass.jpeg", crop: [272, 186, 258, 342] });
  assert.deepEqual(h.renders.at(-1), { time: 0, strength: 0.8 });
  assert.deepEqual(h.renderers[0].size, [258, 342]); assertOriginalPreserved(h);
  const slideDescription = h.ids["effect-description"].textContent;
  assert.ok(slideDescription.length > 0);
  h.materials[1].click(); await h.settleImage("silk");
  assertOriginalPreserved(h, "silk"); assert.deepEqual(h.uploads.at(-1).crop, [318, 255, 292, 382]);
  h.views[1].click();
  assert.ok(h.ids["effect-description"].textContent.length > 0);
  assert.notEqual(h.ids["effect-description"].textContent, slideDescription);
});

test("flow and slide retain independent time and strength and dispose inactive renderers", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  h.frame(1000); h.frame(1020); h.frame(1040); h.setStrength(0.35);
  const flowRenderer = h.renderers[0], flowFrames = flowRenderer.frames.length;
  h.views[2].click();
  assert.equal(flowRenderer.disposed, true); assert.equal(h.renderers.at(-1).kind, "slide");
  assert.deepEqual(h.renders.at(-1), { time: 0, strength: 0.8 });
  assert.equal(Number(h.ids.strength.value), 0.8); assert.equal(h.queuedFrames, 1);
  h.frame(5000); h.frame(5020); h.frame(5040); h.frame(5060); h.setStrength(0.95);
  closeTo(h.time, 0.06);
  const slideRenderer = h.renderers.at(-1), slideFrames = slideRenderer.frames.length;
  h.views[1].click();
  assert.equal(slideRenderer.disposed, true); assert.equal(h.renderers.at(-1).kind, "flow");
  closeTo(h.time, 0.04); assert.equal(h.renders.at(-1).strength, 0.35);
  assert.equal(Number(h.ids.strength.value), 0.35); assert.equal(h.queuedFrames, 1);
  h.frame(10000); closeTo(h.time, 0.04); h.frame(10020); closeTo(h.time, 0.06);
  assert.equal(flowRenderer.frames.length, flowFrames); assert.equal(slideRenderer.frames.length, slideFrames);
  h.views[0].click(); assert.equal(h.queuedFrames, 0); assertOriginalPreserved(h);
  h.views[2].click();
  closeTo(h.time, 0.06); assert.equal(h.renders.at(-1).strength, 0.95);
  assert.equal(Number(h.ids.strength.value), 0.95); assert.equal(h.queuedFrames, 1);
  assert.equal(h.renderers.filter((renderer) => !renderer.disposed).length, 1);
});

test("slide pauses, resumes, and replays without changing saved flow settings", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  h.frame(1000); h.frame(1040); h.setStrength(0.3); h.views[2].click();
  h.frame(2000); h.frame(2040); h.ids.play.click();
  assert.equal(h.queuedFrames, 0); assert.equal(h.ids.play.getAttribute("aria-pressed"), "true");
  const count = h.renders.length; h.frame(100000); assert.equal(h.renders.length, count);
  h.ids.play.click(); assert.equal(h.queuedFrames, 1);
  h.frame(100000); closeTo(h.time, 0.04); h.frame(100020); closeTo(h.time, 0.06);
  h.ids.replay.click(); closeTo(h.time, 0); assert.equal(h.queuedFrames, 1);
  h.views[1].click(); closeTo(h.time, 0.04); assert.equal(h.renders.at(-1).strength, 0.3);
  assertOriginalPreserved(h);
});

test("slide respects reduced motion on selection and supports explicit playback", async () => {
  const h = makeHarness({ reduced: true }); await h.settleImage(); h.views[2].click();
  assert.equal(h.ids.logo.classList.contains("is-ready"), true); assert.equal(h.queuedFrames, 0);
  assert.match(h.ids.feedback.textContent, /减少动态效果/);
  h.ids.play.click(); assert.equal(h.queuedFrames, 1); h.frame(1000); h.frame(1020); closeTo(h.time, 0.02);
  h.media.dispatch("change", { matches: true }); assert.equal(h.queuedFrames, 0);
  h.views[1].click(); assert.equal(h.queuedFrames, 0);
  h.views[2].click(); assert.equal(h.queuedFrames, 0); closeTo(h.time, 0.02);
});

test("slide initialization failures preserve original and do not prevent using existing flow", async () => {
  for (const options of [{ slideInitializationFails: true }, { slideRendererPresent: false }]) {
    const h = makeHarness(options); await h.settleImage(); h.views[1].click();
    h.frame(1000); h.frame(1020); h.setStrength(0.4); h.views[2].click();
    assertOriginalPreserved(h); assert.equal(h.ids.logo.classList.contains("is-ready"), false);
    assert.equal(h.document.body.classList.contains("is-original"), true); assert.equal(h.queuedFrames, 0);
    assert.match(h.ids.feedback.textContent, /已保留原图/);
    assert.doesNotMatch(h.ids.feedback.textContent, /无法显示颜色流动|原图未能加载/);
    h.views[1].click();
    assert.equal(h.renderers.at(-1).kind, "flow"); assert.equal(h.queuedFrames, 1);
    closeTo(h.time, 0.02); assert.equal(h.renders.at(-1).strength, 0.4);
    assert.equal(h.ids.feedback.textContent, "");
  }
});

test("slide upload and frame failures return to original and allow an explicit retry", async () => {
  for (const fault of ["slideUploadFailures", "slideRenderFailures"]) {
    const h = makeHarness(); await h.settleImage(); h.faults[fault] = 1; h.views[2].click();
    assertOriginalPreserved(h); assert.equal(h.renderers[0].disposed, true);
    assert.equal(h.ids.logo.classList.contains("is-ready"), false); assert.equal(h.queuedFrames, 0);
    assert.match(h.ids.feedback.textContent, /已保留原图/);
    assert.doesNotMatch(h.ids.feedback.textContent, /无法显示颜色流动|原图未能加载/);
    h.views[2].click();
    assert.equal(h.constructorCalls, 2); assert.equal(h.ids.logo.classList.contains("is-ready"), true);
    assert.equal(h.ids.feedback.textContent, ""); assert.equal(h.queuedFrames, 1);
  }
});

test("zero slide intensity and hidden tabs suspend work without resetting its clock", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[2].click(); h.frame(1000); h.frame(1020);
  h.setStrength(0); assert.equal(h.queuedFrames, 0); assert.equal(h.renders.at(-1).strength, 0);
  h.setStrength(0.9); assert.equal(h.queuedFrames, 1);
  h.visibility(true); assert.equal(h.queuedFrames, 0); h.visibility(false); assert.equal(h.queuedFrames, 1);
  h.frame(100000); closeTo(h.time, 0.02); h.frame(100020); closeTo(h.time, 0.04);
  assertOriginalPreserved(h);
});

test("the existing color flow renderer is preserved byte for byte", () => {
  const contents = fs.readFileSync(path.join(__dirname, "color-flow-renderer.js"));
  assert.equal(crypto.createHash("sha256").update(contents).digest("hex"), "33da549522e26d1ee0cf4f284cdead81b30ee7a8f31c9b3df75e51aa9ef9d575");
});

test("every frozen V1 artifact retains its recorded SHA256 and byte length", () => {
  const releaseDir = path.join(__dirname, "releases", "v1-original-2026-09-24");
  const manifest = JSON.parse(fs.readFileSync(path.join(releaseDir, "manifest.json"), "utf8"));
  assert.equal(manifest.status, "user_accepted_frozen"); assert.ok(manifest.files.length > 0);
  for (const file of manifest.files) {
    const contents = fs.readFileSync(path.join(releaseDir, file.path));
    assert.equal(contents.length, file.bytes, `${file.path} byte length changed`);
    assert.equal(crypto.createHash("sha256").update(contents).digest("hex"), file.sha256, `${file.path} content changed`);
  }
});


test("ink uses its independent renderer, preserving blue source and paused time", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[2].click();
  h.frame(0); h.frame(32); h.ids.play.click();
  const blue = h.renderers.at(-1), time = h.time;
  h.materials[2].click(); await h.settleImage("ink");
  assert.equal(blue.disposed, true);
  assert.equal(h.renderers.at(-1).kind, "ink");
  assert.equal(h.uploads.at(-1).src, "assets/uteki-ink.png");
  assert.deepEqual(h.uploads.at(-1).crop, [244, 286, 536, 716]);
  assert.equal(h.renders.at(-1).mode, "slide");
  assert.equal(h.time, time); assert.equal(h.queuedFrames, 0);
  h.materials[0].click(); await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.renderers.at(-1).kind, "slide");
  assertOriginalPreserved(h);
});

test("theme changes preserve playback and persist only appearance", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  h.frame(0); h.frame(32); const time = h.time, renderer = h.renderers.at(-1);
  h.themes[1].click();
  assert.equal(h.document.documentElement.getAttribute("data-theme"), "dark");
  assert.equal(h.saved.get("uteki.logo.theme"), "dark");
  assert.equal(h.themes[1].getAttribute("aria-pressed"), "true");
  assert.equal(h.renderers.at(-1), renderer); assert.equal(h.time, time);
  assert.equal(h.queuedFrames, 1);
  h.themes[0].click();
  assert.equal(h.document.documentElement.getAttribute("data-theme"), "light");
});

test("ink direct link selects material, effect and night; reduced motion remains paused", async () => {
  const h = makeHarness({ reduced: true, search: "?material=ink&view=slide&theme=dark" });
  await h.settleImage("ink");
  assert.equal(h.document.body.getAttribute("data-palette"), "ink");
  assert.equal(h.document.documentElement.getAttribute("data-theme"), "dark");
  assert.equal(h.renderers.at(-1).kind, "ink");
  assert.equal(h.queuedFrames, 0);
  h.ids.play.click(); assert.equal(h.queuedFrames, 1);
  h.setStrength(0); assert.equal(h.queuedFrames, 0);
  assert.equal(h.renders.at(-1).strength, 0);
});

test("unavailable ink renderer preserves the ink original and can return to blue flow", async () => {
  const h = makeHarness({ inkRendererPresent: false }); await h.settleImage();
  h.materials[2].click(); await h.settleImage("ink"); h.views[2].click();
  assert.equal(h.document.body.classList.contains("is-original"), true);
  assert.equal(h.ids["mark-fallback"].querySelector("img").src, "assets/uteki-ink.png");
  assert.equal(h.queuedFrames, 0);
  h.materials[0].click(); await new Promise(resolve => setImmediate(resolve)); h.views[1].click();
  assert.equal(h.renderers.at(-1).kind, "flow"); assert.equal(h.queuedFrames, 1);
});


test("entrance plays once, settles to the retained artwork, and can replay", async () => {
  const h = makeHarness({ search: "?material=ink&view=impact&theme=dark" });
  await h.settleImage("ink");
  assert.equal(h.queuedFrames, 0); assert.equal(h.ids["motion-progress"].disabled, true);
  await h.settleStoryboard("ink");
  assert.equal(h.renderers.at(-1).kind, "impact");
  assert.deepEqual(h.renderers.at(-1).size, [413, 547]);
  assert.equal(h.document.body.classList.contains("is-impact-active"), true);
  assert.equal(h.ids["wordmark-group"].style.opacity, "0");
  h.frame(0); for (let i = 1; i <= 205; i++) h.frame(i * 50);
  assert.equal(h.queuedFrames, 0);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.equal(h.ids["wordmark-group"].style.opacity, "1");
  assert.equal(h.ids["state-label"].textContent, "雨滴已成形");
  assert.equal(h.ids["mark-fallback"].querySelector("img").src, "assets/uteki-ink.png");
  h.ids.play.click();
  assert.equal(h.queuedFrames, 1);
  assert.equal(h.renders.at(-1).time, 0);
  assert.equal(h.document.body.classList.contains("is-impact-active"), true);
});

test("reduced motion holds original until entrance explicitly starts", async () => {
  const h = makeHarness({ reduced: true, search: "?material=ink&view=impact" });
  await h.settleImage("ink"); await h.settleStoryboard("ink");
  assert.equal(h.queuedFrames, 0);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  h.ids.play.click(); h.frame(0); h.frame(50); h.ids.play.click();
  const t = h.time; assert.equal(h.queuedFrames, 0);
  h.themes[1].click(); assert.equal(h.time, t);
  h.ids.play.click(); assert.equal(h.queuedFrames, 1);
  h.setStrength(0);
  assert.equal(h.queuedFrames, 0);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assert.equal(h.ids["wordmark-group"].style.opacity, "1");
});

test("entrance renderer failure never hides original and switching effects restores sizing", async () => {
  const bad = makeHarness({ impactRendererPresent: false }); await bad.settleImage(); bad.views[3].click(); await bad.settleStoryboard();
  assertOriginalPreserved(bad);
  assert.equal(bad.document.body.classList.contains("is-impact-active"), false);
  assert.equal(bad.queuedFrames, 0);
  const h = makeHarness(); await h.settleImage(); h.views[3].click(); await h.settleStoryboard(); h.views[2].click();
  assert.equal(h.renderers.at(-1).kind, "slide");
  assert.deepEqual(h.renderers.at(-1).size, [258, 342]);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assertOriginalPreserved(h);
});

test("missing storyboard preserves source artwork and other effects remain usable", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  h.frame(0); h.frame(50); const flowTime = h.time;
  h.views[3].click();
  assert.equal(h.queuedFrames, 0);
  assert.equal(h.ids["motion-progress"].disabled, true);
  assert.match(h.ids.feedback.textContent, /载入动效原画/);
  await h.settleStoryboard("glass", false);
  assertOriginalPreserved(h);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assert.match(h.ids.feedback.textContent, /动效原画未能加载/);
  assert.equal(h.renderers.some(renderer => renderer.kind === "impact"), false);
  h.views[0].click(); assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  h.views[1].click(); closeTo(h.time, flowTime); assert.equal(h.queuedFrames, 1);
  h.views[3].click(); await h.settleStoryboard();
  assert.equal(h.renderers.at(-1).kind, "impact"); assert.equal(h.queuedFrames, 1);
  assert.equal(h.ids.feedback.textContent, "");
});

test("entrance progress scrubs to bounded frames, pauses, and replay starts from zero", async () => {
  const h = makeHarness({ search: "?material=ink&view=impact" });
  await h.settleImage("ink"); await h.settleStoryboard("ink");
  h.scrub(5);
  closeTo(h.time, 5); assert.equal(h.queuedFrames, 0);
  assert.equal(h.ids.play.getAttribute("aria-pressed"), "true");
  assert.equal(h.ids["motion-progress"].value, "5");
  assert.equal(h.ids["motion-time"].textContent, "5.0 / 10 s");
  assert.equal(h.ids["state-label"].textContent, "02 · 舒展 · 已暂停");
  h.ids.language.click(); assert.equal(h.ids["state-label"].textContent, "02 · Unfold · Paused");
  h.ids.language.click();
  assert.equal(h.ids["motion-progress"].style["--range-fill"], "50%");
  assert.equal(h.ids["wordmark-group"].style.opacity, "0");
  h.scrub(-8);
  closeTo(h.time, 0); assert.equal(h.queuedFrames, 0);
  assert.equal(h.ids["motion-progress"].value, "0");
  assert.equal(h.ids["state-label"].textContent, "01 · 入水 · 已暂停");
  h.scrub(8.75); closeTo(Number(h.ids["wordmark-group"].style.opacity), 0.5);
  h.scrub(15);
  assert.equal(h.ids["motion-progress"].value, "10");
  assert.equal(h.ids["motion-time"].textContent, "10.0 / 10 s");
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.equal(h.ids["wordmark-group"].style.opacity, "1");
  assert.equal(h.ids["state-label"].textContent, "雨滴已成形");
  assertOriginalPreserved(h, "ink");
  h.scrub("not-a-number");
  assert.equal(h.ids["motion-time"].textContent, "10.0 / 10 s");
  h.ids["stage-replay"].click();
  closeTo(h.time, 0); assert.equal(h.queuedFrames, 1);
  assert.equal(h.ids["motion-time"].textContent, "0.0 / 10 s");
  assert.equal(h.document.body.classList.contains("is-impact-active"), true);
  h.ids["stage-play"].click(); assert.equal(h.queuedFrames, 0);
  h.ids["stage-play"].click(); assert.equal(h.queuedFrames, 1);
});

test("material changes await matching storyboard and never render another material's board", async () => {
  const h = makeHarness({ search: "?material=ink&view=impact" });
  await h.settleImage("ink"); await h.settleStoryboard("ink");
  assert.equal(h.storyboardUploads[0].src, "assets/motion/ink-study.png");
  assert.equal(h.storyboardUploads[0].original, "assets/uteki-ink.png");
  assert.equal(h.ids["storyboard-link"].href, "assets/motion/ink-study.png");
  const ink = h.renderers.at(-1);
  h.materials[0].click(); await h.settleImage("glass");
  assert.equal(h.document.body.getAttribute("data-palette"), "ink");
  assert.equal(h.ids["motion-progress"].disabled, true);
  assert.equal(h.renderers.at(-1), ink);
  assertOriginalPreserved(h, "ink");
  h.frame(0); h.frame(50);
  assert.equal(h.renders.at(-1).material, "ink");
  await h.settleStoryboard("glass");
  assert.equal(ink.disposed, true);
  assert.equal(h.document.body.getAttribute("data-palette"), "glass");
  assert.equal(h.storyboardUploads.at(-1).src, "assets/motion/blue-study.png");
  assert.equal(h.storyboardUploads.at(-1).original, "assets/uteki-glass.jpeg");
  assert.equal(h.ids["storyboard-link"].href, "assets/motion/blue-study.png");
  assert.equal(h.renders.at(-1).material, "glass");
  assertOriginalPreserved(h);
  h.materials[1].click(); await h.settleImage("silk");
  assert.equal(h.renders.at(-1).material, "silk");
  assert.equal(h.renderers.at(-1).storyboard.src, "assets/motion/blue-study.png");
  assertOriginalPreserved(h, "silk");
  h.materials[2].click(); await h.flush();
  assert.equal(h.renders.at(-1).material, "ink");
  assert.equal(h.renderers.at(-1).storyboard.src, "assets/motion/ink-study.png");
});

test("loaded storyboard does not hide artwork when entrance GPU initialization fails", async () => {
  const h = makeHarness({ impactRendererPresent: false, search: "?material=ink&view=impact" });
  await h.settleImage("ink"); await h.settleStoryboard("ink");
  assertOriginalPreserved(h, "ink");
  assert.equal(h.ids.logo.classList.contains("is-ready"), false);
  assert.equal(h.document.body.classList.contains("is-impact-active"), false);
  assert.equal(h.ids["wordmark-group"].style.opacity, "1");
  assert.equal(h.ids["motion-progress"].disabled, true);
  assert.equal(h.queuedFrames, 0);
  assert.match(h.ids.feedback.textContent, /入水成形暂不可用/);
  h.views[2].click(); assert.equal(h.renderers.at(-1).kind, "ink");
  assert.equal(h.queuedFrames, 1);
});

test("failed material storyboard reports artwork failure, retains previous material, and retries", async () => {
  const h = makeHarness({ search: "?material=ink&view=impact" });
  await h.settleImage("ink"); await h.settleStoryboard("ink");
  h.materials[0].click(); await h.settleImage("glass"); await h.settleStoryboard("glass", false);
  assertOriginalPreserved(h, "ink");
  assert.equal(h.document.body.getAttribute("data-palette"), "ink");
  assert.equal(h.renderers.at(-1).storyboard.src, "assets/motion/ink-study.png");
  assert.match(h.ids.feedback.textContent, /动效原画未能加载/);
  assert.doesNotMatch(h.ids.feedback.textContent, /原图未能加载/);
  assert.equal(h.materials[2].getAttribute("aria-pressed"), "true");
  assert.ok(h.materials.every(button => !button.disabled));
  h.ids.language.click();
  assert.match(h.ids.feedback.textContent, /motion artwork could not load/i);
  assert.match(h.ids.feedback.textContent, /previous image is preserved/i);
  h.materials[0].click(); await h.flush(); await h.settleStoryboard("glass");
  assertOriginalPreserved(h);
  assert.equal(h.renders.at(-1).material, "glass");
  assert.equal(h.ids.feedback.textContent, "");
});

test("resuming the same flow renderer after failed entrance load clears its warning", async () => {
  const h = makeHarness(); await h.settleImage(); h.views[1].click();
  const flow = h.renderers.at(-1);
  h.views[3].click(); await h.settleStoryboard("glass", false);
  assert.notEqual(h.ids.feedback.textContent, "");
  h.views[1].click();
  assert.equal(h.renderers.at(-1), flow);
  assert.equal(h.queuedFrames, 1);
  assert.equal(h.ids.feedback.textContent, "");
});
