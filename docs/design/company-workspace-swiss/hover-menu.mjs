// A DOM-independent hover lifecycle. show(key) and hide() are the only effects;
// selection, navigation, positioning and focus remain the caller's responsibility.
export function createHoverMenu({
  show,
  hide,
  schedule = setTimeout,
  cancel = clearTimeout,
  openDelay = 160,
  closeDelay = 220,
} = {}) {
  for (const [name, callback] of Object.entries({ show, hide, schedule, cancel })) {
    if (typeof callback !== 'function') throw new TypeError(`${name} must be a function`);
  }
  for (const [name, delay] of Object.entries({ openDelay, closeDelay })) {
    if (!Number.isFinite(delay) || delay < 0) throw new TypeError(`${name} must be a non-negative finite number`);
  }

  let key = null;
  let pendingKey = null;
  let rowKey = null;
  let insideMenu = false;
  let openTimer = null;
  let closeTimer = null;
  let openGeneration = 0;
  let closeGeneration = 0;
  let disposed = false;

  function requireKey(value) {
    if (typeof value !== 'string' || !value.trim()) throw new TypeError('key must be a non-empty string');
    return value;
  }
  function cancelOpening() {
    openGeneration += 1;
    if (openTimer !== null) cancel(openTimer);
    openTimer = null;
    pendingKey = null;
  }
  function cancelClosing() {
    closeGeneration += 1;
    if (closeTimer !== null) cancel(closeTimer);
    closeTimer = null;
  }
  function reveal(nextKey) {
    if (key === nextKey) return;
    key = nextKey;
    show(nextKey);
  }
  function close() {
    cancelOpening();
    cancelClosing();
    rowKey = null;
    insideMenu = false;
    const hadMenu = key !== null;
    key = null;
    if (hadMenu) hide();
  }
  function queueClosing() {
    cancelClosing();
    if (key === null) return;
    const generation = closeGeneration;
    closeTimer = schedule(() => {
      if (disposed || generation !== closeGeneration || insideMenu || rowKey !== null) return;
      closeTimer = null;
      close();
    }, closeDelay);
  }
  function enter(nextKey) {
    if (disposed) return;
    requireKey(nextKey);
    rowKey = nextKey;
    insideMenu = false;
    cancelClosing();
    if (key === nextKey) {
      cancelOpening();
      return;
    }
    if (pendingKey === nextKey) return;
    cancelOpening();
    pendingKey = nextKey;
    const generation = openGeneration;
    openTimer = schedule(() => {
      if (disposed || generation !== openGeneration || rowKey !== nextKey || pendingKey !== nextKey) return;
      openTimer = null;
      pendingKey = null;
      reveal(nextKey);
    }, openDelay);
  }
  function leave(leavingKey) {
    if (disposed) return;
    // A delayed leave from the previous row must not cancel or close its successor.
    if (leavingKey !== undefined && leavingKey !== rowKey) return;
    if (insideMenu) return;
    rowKey = null;
    cancelOpening();
    queueClosing();
  }
  function enterMenu() {
    if (disposed) return;
    insideMenu = true;
    rowKey = null;
    cancelOpening();
    cancelClosing();
  }
  function leaveMenu() {
    if (disposed || !insideMenu) return;
    insideMenu = false;
    queueClosing();
  }
  function open(nextKey) {
    if (disposed) return;
    requireKey(nextKey);
    cancelOpening();
    cancelClosing();
    rowKey = nextKey;
    insideMenu = false;
    reveal(nextKey);
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    close();
  }

  return { enter, leave, enterMenu, leaveMenu, open, close, dispose, getState: () => ({ key, pendingKey }) };
}
