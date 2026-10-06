import test from "node:test";
import assert from "node:assert/strict";
import { createWheelPager } from "./gesture.mjs";

function setup(options = {}) {
  let clock = 0;
  const steps = [];
  const pager = createWheelPager({
    now: () => clock,
    onStep: (direction) => { steps.push(direction); },
    ...options,
  });
  function wheel(deltaY, advance = 16, extra = {}) {
    clock += advance;
    let prevented = false;
    const consumed = pager.handle({
      deltaX: 0,
      deltaY,
      deltaMode: 0,
      ctrlKey: false,
      preventDefault() { prevented = true; },
      ...extra,
    });
    return { consumed, prevented };
  }
  return { pager, steps, wheel };
}

test("small intentional deltas accumulate to one step only at the threshold", () => {
  const { wheel, steps } = setup();
  assert.deepEqual(wheel(30), { consumed: true, prevented: true });
  wheel(30);
  wheel(29);
  assert.deepEqual(steps, []);
  wheel(1);
  assert.deepEqual(steps, [1]);
});

test("a long inertial tail cannot skip siblings even when it exceeds the threshold", () => {
  const { wheel, steps } = setup();
  wheel(110);
  for (let i = 0; i < 100; i++) wheel(14, 40);
  assert.deepEqual(steps, [1]);
});

test("a pause unlocks the next intentional gesture", () => {
  const { wheel, steps } = setup();
  wheel(90);
  wheel(90, 179);
  assert.deepEqual(steps, [1]);
  wheel(90, 180);
  assert.deepEqual(steps, [1, 1]);
});

test("idle partial movement is not carried into a later gesture", () => {
  const { wheel, steps } = setup();
  wheel(80);
  wheel(20, 180);
  assert.deepEqual(steps, []);
  wheel(70);
  assert.deepEqual(steps, [1]);
});

test("reversal before commitment accumulates only the new direction", () => {
  const { wheel, steps } = setup();
  wheel(70);
  wheel(-45);
  assert.deepEqual(steps, []);
  wheel(-45);
  assert.deepEqual(steps, [-1]);
});

test("a committed gesture cannot reverse until the user pauses", () => {
  const { wheel, steps } = setup();
  wheel(100);
  wheel(-120);
  wheel(-120);
  assert.deepEqual(steps, [1]);
  wheel(-100, 180);
  assert.deepEqual(steps, [1, -1]);
});

test("a rejected boundary step still consumes its inertial gesture", () => {
  let position = 0;
  let attempts = 0;
  const { wheel } = setup({
    onStep(direction) {
      attempts += 1;
      const next = position + direction;
      if (next < 0 || next > 2) return false;
      position = next;
      return true;
    },
  });
  wheel(-120);
  wheel(-120);
  wheel(-120);
  assert.equal(attempts, 1);
  assert.equal(position, 0);
  wheel(120, 180);
  assert.equal(position, 1);
  assert.equal(attempts, 2);
});

test("Ctrl + wheel preserves browser zoom and contributes no paging delta", () => {
  const { wheel, steps } = setup();
  wheel(40);
  assert.deepEqual(wheel(1000, 16, { ctrlKey: true }), {
    consumed: false,
    prevented: false,
  });
  assert.deepEqual(steps, []);
  wheel(50);
  assert.deepEqual(steps, [1]);
});

test("line and page wheel units are normalized to pixels", () => {
  const line = setup();
  line.wheel(5, 16, { deltaMode: 1 });
  assert.deepEqual(line.steps, []);
  line.wheel(1, 16, { deltaMode: 1 });
  assert.deepEqual(line.steps, [1]);

  const page = setup();
  page.wheel(-1, 16, { deltaMode: 2 });
  assert.deepEqual(page.steps, [-1]);
});

test("the dominant axis supplies the gesture direction without double counting", () => {
  const { wheel, steps } = setup();
  wheel(30, 16, { deltaX: -60 });
  assert.deepEqual(steps, []);
  wheel(20, 16, { deltaX: -30 });
  assert.deepEqual(steps, [-1]);
});

test("tiny noise cannot turn pages but keeps an inertial tail locked", () => {
  const { wheel, steps } = setup();
  for (let i = 0; i < 300; i++) wheel(0.4);
  assert.deepEqual(steps, []);
  wheel(90);
  for (let i = 0; i < 10; i++) wheel(0.1, 170);
  wheel(100, 170);
  assert.deepEqual(steps, [1]);
  wheel(100, 180);
  assert.deepEqual(steps, [1, 1]);
});

test("an explicit interaction reset clears both accumulation and the inertia lock", () => {
  const { wheel, steps, pager } = setup();
  wheel(80);
  pager.reset();
  wheel(20);
  assert.deepEqual(steps, []);
  wheel(70);
  assert.deepEqual(steps, [1]);
  pager.reset();
  wheel(-90);
  assert.deepEqual(steps, [1, -1]);
});

test("separate regions keep separate accumulation and locks", () => {
  const left = setup();
  const right = setup();
  left.wheel(60);
  right.wheel(60);
  assert.deepEqual(left.steps, []);
  assert.deepEqual(right.steps, []);
  left.wheel(30);
  assert.deepEqual(left.steps, [1]);
  assert.deepEqual(right.steps, []);
  right.wheel(-90);
  assert.deepEqual(right.steps, [-1]);
});

test("zero or non-finite movement is not consumed", () => {
  const { wheel, steps } = setup();
  assert.deepEqual(wheel(0), { consumed: false, prevented: false });
  assert.deepEqual(wheel(NaN), { consumed: false, prevented: false });
  assert.deepEqual(wheel(Infinity), { consumed: false, prevented: false });
  assert.deepEqual(steps, []);
});

test("invalid pager configuration fails at creation", () => {
  assert.throws(() => createWheelPager(), /onStep/);
  assert.throws(() => setup({ threshold: 0 }), /threshold/);
  assert.throws(() => setup({ idleMs: -1 }), /idleMs/);
  assert.throws(() => setup({ now: null }), /now/);
});
