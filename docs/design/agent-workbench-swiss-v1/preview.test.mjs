import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { createPreviewControls } from './preview.mjs';
import { createController } from '../agent-workbench-v1/app.mjs';
import { DEMO } from '../agent-workbench-v1/demo-data.mjs';
import { reviewKey } from '../agent-workbench-v1/model.mjs';

// Event harness, not a browser layout or visual acceptance test.
function node(dataset = {}) {
  return { dataset, textContent: '', attributes: {}, setAttribute(name, value) { this.attributes[name] = value; } };
}
function harness() {
  const root = { lang: 'zh-CN', dataset: { previewStyle: 'engineering' } };
  const buttons = ['engineering', 'editorial'].map(variant => node({ previewVariant: variant, previewCopy: variant }));
  const copy = ['title', 'scope', 'baseline'].map(key => node({ previewCopy: key }));
  const options = node(), announcement = node(), listeners = new Map();
  const shell = {
    ...node(),
    querySelector(selector) { return { '[data-preview-options]': options, '[data-preview-announcement]': announcement }[selector] ?? null; },
    querySelectorAll(selector) { return selector === '[data-preview-copy]' ? [...copy, ...buttons] : selector === '[data-preview-variant]' ? buttons : []; },
    contains(element) { return buttons.includes(element); },
    addEventListener(name, handler) { listeners.set(name, handler); },
    removeEventListener(name) { listeners.delete(name); },
  };
  let observer;
  const environment = {
    document: { documentElement: root, querySelector() { throw new Error('Preview must not query application content'); } },
    setTimeout: () => 1, clearTimeout() {},
    MutationObserver: class {
      constructor(callback) { this.callback = callback; observer = this; }
      observe(target, options) { this.target = target; this.options = options; }
      disconnect() { this.disconnected = true; }
    },
  };
  const controls = createPreviewControls(shell, environment);
  return { root, buttons, copy, options, announcement, listeners, shell, environment, controls, observer };
}
function applicationHarness(environment) {
  const nodes = new Map();
  for (const selector of ['.studio', '.sidebar', '.main-workspace', '.inspector', '.inspector-body', '#main-scroll', '#toast']) {
    nodes.set(selector, { innerHTML: '', textContent: '', hidden: false, scrollTop: 0, focus() {}, classList: { toggle() {} } });
  }
  let mounted = false, mounts = 0;
  const application = {
    set innerHTML(value) { mounted = true; mounts++; this.html = value; },
    querySelector(selector) { return selector === '.studio' && !mounted ? null : nodes.get(selector); },
    querySelectorAll() { return []; }, contains() { return true; }, addEventListener() {}, removeEventListener() {},
  };
  return { application, nodes, mounts: () => mounts, controller: createController(application, DEMO, environment) };
}

test('switching typography preserves the shared controller, active artifact and unsaved drafts', () => {
  const h = harness(), app = applicationHarness(h.environment), controller = app.controller;
  controller.dispatch({ type: 'setTab', tab: 'review' });
  controller.dispatch({ type: 'setDraft', text: '请补充单位依据 / Add unit evidence' });
  controller.dispatch({ type: 'setReviewDraft', criterionId: 'evidence', note: '尚未保存 / Unsaved', verdict: 'insufficient' });
  controller.dispatch({ type: 'openArtifact', artifactId: 'googl-record-v2' });
  app.nodes.get('#main-scroll').scrollTop = 187;
  const before = controller.getState(), rendered = [...app.nodes].map(([key, value]) => [key, value.innerHTML]);
  const key = reviewKey(before.taskId, before.runId, 'evidence');
  assert.equal(before.reviewDrafts[key].note, '尚未保存 / Unsaved');
  h.controls.select('editorial');
  h.controls.select('engineering');
  assert.strictEqual(controller.getState(), before);
  assert.equal(controller.getState().artifactId, 'googl-record-v2');
  assert.deepEqual([...app.nodes].map(([key, value]) => [key, value.innerHTML]), rendered);
  assert.equal(app.nodes.get('#main-scroll').scrollTop, 187);
  assert.equal(app.mounts(), 1);
  assert.equal(h.buttons[0].attributes['aria-pressed'], 'true');
  assert.equal(h.buttons[1].attributes['aria-pressed'], 'false');
  controller.dispose(); h.controls.dispose();
});

test('preview labels follow the shared application language without rebuilding the application', () => {
  const h = harness(), app = applicationHarness(h.environment);
  assert.equal(h.copy[0].textContent, '后台排版预览');
  assert.deepEqual(h.observer.options, { attributes: true, attributeFilter: ['lang'] });
  assert.strictEqual(h.observer.target, h.root);
  app.controller.dispatch({ type: 'setLanguage', lang: 'en' });
  h.observer.callback();
  assert.equal(h.copy[0].textContent, 'Workbench typography');
  assert.equal(h.options.attributes['aria-label'], 'Typography option');
  assert.equal(h.buttons[0].textContent, 'Engineering');
  h.controls.select('editorial');
  assert.match(h.announcement.textContent, /^Typography changed/);
  assert.equal(app.controller.getState().lang, 'en');
  assert.equal(app.mounts(), 1);
  app.controller.dispose(); h.controls.dispose();
});

test('only local variant buttons can switch the preview; invalid scope fails explicitly', () => {
  const h = harness();
  const click = target => h.listeners.get('click')({ target });
  const outside = node({ previewVariant: 'editorial' });
  click({ closest: () => outside });
  assert.equal(h.controls.getStyle(), 'engineering');
  click({ closest: () => h.buttons[1] });
  assert.equal(h.controls.getStyle(), 'editorial');
  assert.equal(h.buttons[1].attributes['aria-pressed'], 'true');
  assert.throws(() => h.controls.select('unknown'), /Unknown preview style/);
  assert.equal(h.controls.getStyle(), 'editorial');
  assert.throws(() => createPreviewControls(null, h.environment), /explicit preview shell/);
  h.controls.dispose();
  assert.equal(h.listeners.size, 0);
  assert.equal(h.observer.disconnected, true);
});

test('the standalone entry reuses existing workbench assets and prohibits network connections', () => {
  const entry = new URL('./index.html', import.meta.url);
  const html = readFileSync(entry, 'utf8');
  const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map(match => match[1].split('?')[0]);
  assert.deepEqual(scripts, ['../agent-workbench-v1/app.mjs', './preview.mjs']);
  assert.equal([...html.matchAll(/id="app"/g)].length, 1);
  assert.match(html, /connect-src 'none'/);
  for (const [, path] of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
    const resolved = new URL(path.split('?')[0], entry);
    assert.equal(resolved.protocol, 'file:');
    assert.ok(existsSync(resolved), `Missing local preview asset: ${path}`);
  }
  const css = readFileSync(new URL('./style.css', entry), 'utf8');
  assert.match(css, /^@import url\('\.\.\/agent-workbench-v1\/style\.css'\);/);
});
