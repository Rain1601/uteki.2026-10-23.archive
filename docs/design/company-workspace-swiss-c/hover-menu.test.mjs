import test from 'node:test';
import assert from 'node:assert/strict';
import { createHoverMenu } from './hover-menu.mjs';

function setup(options = {}) {
  let now = 0;
  let nextId = 0; // Zero is deliberately a valid timer handle.
  const timers = new Map();
  const calls = [];
  const schedule = (callback, delay) => {
    const id = nextId++;
    timers.set(id, { callback, due: now + delay, cancelled: false, fired: false });
    return id;
  };
  const cancel = id => {
    const timer = timers.get(id);
    if (timer) timer.cancelled = true;
  };
  const tick = elapsed => {
    const target = now + elapsed;
    for (;;) {
      const entry = [...timers.entries()]
        .filter(([, timer]) => !timer.cancelled && !timer.fired && timer.due <= target)
        .sort((a, b) => a[1].due - b[1].due || a[0] - b[0])[0];
      if (!entry) break;
      const [, timer] = entry;
      now = timer.due;
      timer.fired = true;
      timer.callback();
    }
    now = target;
  };
  // Simulate callbacks already delivered by an event loop before cancellation.
  const flushCancelledCallbacks = () => {
    for (const timer of timers.values()) {
      if (timer.cancelled && !timer.fired) {
        timer.fired = true;
        timer.callback();
      }
    }
  };
  const menu = createHoverMenu({
    show: key => calls.push(['show', key]),
    hide: () => calls.push(['hide']),
    schedule, cancel, ...options,
  });
  return { menu, calls, tick, flushCancelledCallbacks,
    pendingTimers: () => [...timers.values()].filter(timer => !timer.cancelled && !timer.fired).length };
}

test('hover opens after the configured delay without changing any selected entity', () => {
  const { menu, calls, tick } = setup();
  menu.enter('company:cedar');
  assert.deepEqual(menu.getState(), {key:null, pendingKey:'company:cedar'});
  tick(159);
  assert.deepEqual(calls, []);
  tick(1);
  assert.deepEqual(calls, [['show', 'company:cedar']]);
  assert.deepEqual(menu.getState(), {key:'company:cedar', pendingKey:null});
  // There is no selection or navigation callback in this lifecycle API.
  assert.deepEqual(Object.keys(menu.getState()).sort(), ['key', 'pendingKey']);
});

test('crossing the gap into the menu cancels closing; leaving the menu closes later', () => {
  const { menu, calls, tick, flushCancelledCallbacks } = setup();
  menu.open('manager:scout');
  menu.leave('manager:scout');
  tick(100);
  menu.enterMenu();
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, [['show', 'manager:scout']]);
  assert.equal(menu.getState().key, 'manager:scout');
  menu.leaveMenu();
  tick(219);
  assert.equal(menu.getState().key, 'manager:scout');
  tick(1);
  assert.deepEqual(calls, [['show', 'manager:scout'], ['hide']]);
  assert.deepEqual(menu.getState(), {key:null, pendingKey:null});
});

test('rapid row switches open only the last row and ignore stale earlier leaves', () => {
  const { menu, calls, tick, flushCancelledCallbacks } = setup();
  menu.enter('company:cedar');
  tick(40);
  menu.enter('company:pine');
  menu.leave('company:cedar');
  tick(40);
  menu.enter('manager:scout');
  menu.leave('company:pine');
  flushCancelledCallbacks();
  tick(159);
  assert.deepEqual(calls, []);
  tick(1);
  assert.deepEqual(calls, [['show', 'manager:scout']]);
});

test('leaving an older visible row cannot close the new pending or visible menu', () => {
  const { menu, calls, tick, flushCancelledCallbacks } = setup();
  menu.open('company:cedar');
  menu.enter('company:pine');
  menu.leave('company:cedar');
  tick(160);
  assert.deepEqual(calls, [['show', 'company:cedar'], ['show', 'company:pine']]);
  menu.leave('company:cedar');
  flushCancelledCallbacks();
  tick(1000);
  assert.equal(menu.getState().key, 'company:pine');
  menu.leave('company:pine');
  tick(220);
  assert.deepEqual(calls.at(-1), ['hide']);
});

test('leaving before opening cancels a passing hover, including timer handle zero', () => {
  const { menu, calls, tick, flushCancelledCallbacks, pendingTimers } = setup();
  menu.enter('company:cedar');
  tick(70);
  menu.leave('company:cedar');
  assert.equal(pendingTimers(), 0);
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, []);
  assert.deepEqual(menu.getState(), {key:null, pendingKey:null});
});

test('explicit open is immediate and cancels both pending hover and delayed closing', () => {
  const { menu, calls, tick, flushCancelledCallbacks } = setup();
  menu.enter('company:cedar');
  menu.open('manager:scout');
  assert.deepEqual(calls, [['show', 'manager:scout']]);
  menu.leave('manager:scout');
  tick(100);
  menu.open('manager:patient');
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, [['show', 'manager:scout'], ['show', 'manager:patient']]);
  assert.equal(menu.getState().key, 'manager:patient');
});

test('close before opening or while switching cancels all outstanding work', () => {
  const { menu, calls, tick, flushCancelledCallbacks, pendingTimers } = setup();
  menu.enter('company:cedar');
  menu.close();
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, []);
  menu.open('company:pine');
  menu.enter('manager:scout');
  menu.close();
  menu.close();
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, [['show', 'company:pine'], ['hide']]);
  assert.equal(pendingTimers(), 0);
});

test('returning to an existing menu cancels a different pending row instead of replacing it', () => {
  const { menu, calls, tick, flushCancelledCallbacks } = setup();
  menu.open('company:cedar');
  menu.enter('company:pine');
  tick(60);
  menu.enterMenu();
  menu.leave('company:pine');
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, [['show', 'company:cedar']]);
  assert.deepEqual(menu.getState(), {key:'company:cedar', pendingKey:null});
});

test('same-row reentry neither restarts its pending delay nor renders it repeatedly', () => {
  const { menu, calls, tick } = setup();
  menu.enter('company:cedar');
  tick(100);
  menu.enter('company:cedar');
  tick(60);
  assert.deepEqual(calls, [['show', 'company:cedar']]);
  menu.leave();
  tick(100);
  menu.enter('company:cedar');
  tick(1000);
  menu.open('company:cedar');
  assert.deepEqual(calls, [['show', 'company:cedar']]);
});

test('a stale menu leave after entering a row does not close that row', () => {
  const { menu, calls, tick } = setup();
  menu.open('company:cedar');
  menu.enterMenu();
  menu.enter('manager:scout');
  menu.leaveMenu();
  tick(1000);
  assert.deepEqual(calls, [['show', 'company:cedar'], ['show', 'manager:scout']]);
  assert.equal(menu.getState().key, 'manager:scout');
});

test('dispose hides once, cancels pending work and prevents future callbacks or opens', () => {
  const { menu, calls, tick, flushCancelledCallbacks, pendingTimers } = setup();
  menu.open('company:cedar');
  menu.enter('company:pine');
  menu.dispose();
  menu.dispose();
  menu.enter('manager:scout');
  menu.open('manager:patient');
  menu.enterMenu();
  menu.leaveMenu();
  menu.leave();
  menu.close();
  flushCancelledCallbacks();
  tick(1000);
  assert.deepEqual(calls, [['show', 'company:cedar'], ['hide']]);
  assert.equal(pendingTimers(), 0);
  assert.deepEqual(menu.getState(), {key:null, pendingKey:null});
});

test('custom delays and independent instances have isolated state', () => {
  const first = setup({openDelay:0, closeDelay:10});
  const second = setup();
  first.menu.enter('company:cedar');
  first.tick(0);
  assert.equal(first.menu.getState().key, 'company:cedar');
  assert.deepEqual(second.menu.getState(), {key:null, pendingKey:null});
  const snapshot = first.menu.getState();
  snapshot.key = 'manager:scout';
  assert.equal(first.menu.getState().key, 'company:cedar');
  first.menu.leave();
  first.tick(10);
  assert.deepEqual(first.calls, [['show', 'company:cedar'], ['hide']]);
});
