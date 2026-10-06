/**
 * Turn one deliberate wheel/trackpad gesture into at most one sibling step.
 * A pause, not a timeout callback, begins the next gesture. Keep one instance
 * per paging region across page changes and redraws so its inertia lock survives.
 * Call reset() only to explicitly discard the region's interaction state;
 * never reset or recreate the pager in response to onStep or a redraw.
 *
 * handle(event) returns whether the event was consumed. The callback receives
 * +1 (next) or -1 (previous); returning false indicates a boundary, which still
 * consumes this gesture. Reversing a locked gesture requires the same pause.
 */
export function createWheelPager({
  onStep,
  threshold = 90,
  idleMs = 180,
  now = () => performance.now(),
} = {}) {
  if (typeof onStep !== "function") {
    throw new TypeError("onStep must be a function");
  }
  if (!Number.isFinite(threshold) || threshold <= 0) {
    throw new RangeError("threshold must be a positive finite number");
  }
  if (!Number.isFinite(idleMs) || idleMs <= 0) {
    throw new RangeError("idleMs must be a positive finite number");
  }
  if (typeof now !== "function") {
    throw new TypeError("now must be a function");
  }

  let lastEventAt = null;
  let accumulated = 0;
  let direction = 0;
  let locked = false;

  function reset() {
    lastEventAt = null;
    accumulated = 0;
    direction = 0;
    locked = false;
  }

  function handle(event) {
    // Browsers represent trackpad pinch-to-zoom as a Ctrl + wheel event.
    if (event.ctrlKey) return false;

    const dx = Number.isFinite(event.deltaX) ? event.deltaX : 0;
    const dy = Number.isFinite(event.deltaY) ? event.deltaY : 0;
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 800 : 1;
    const delta = (Math.abs(dx) > Math.abs(dy) ? dx : dy) * unit;
    if (delta === 0 || !Number.isFinite(delta)) return false;

    const time = now();
    if (lastEventAt === null || time - lastEventAt >= idleMs || time < lastEventAt) {
      accumulated = 0;
      direction = 0;
      locked = false;
    }
    // Even the tiny tail of an inertial gesture keeps it in the same gesture.
    lastEventAt = time;
    event.preventDefault();

    if (locked || Math.abs(delta) < 0.5) return true;

    const nextDirection = Math.sign(delta);
    if (nextDirection !== direction) {
      // Before committing, a reversal starts a fresh directional intention.
      accumulated = 0;
      direction = nextDirection;
    }
    accumulated += Math.abs(delta);

    if (accumulated >= threshold) {
      locked = true;
      onStep(direction);
    }
    return true;
  }

  return { handle, reset };
}
