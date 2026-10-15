// Original study specimen: no Anthropic media is bundled or copied here.
export function mountMotionFigure(host, { title = '从记录到解释', duration = 6000 } = {}) {
  if (!host || !Number.isFinite(duration) || duration < 1000) throw new TypeError('MotionFigure needs a host and duration >= 1000 ms');
  const root = document.createElement('figure');
  root.className = 'motion-figure';
  root.innerHTML = `<div class="motion-stage"><div class="motion-label">EXPLAINER / 原创示意</div><div class="motion-flow"><span>01<br>记录</span><i>→</i><span>02<br>比较</span><i>→</i><span>03<br>解释</span></div><div class="motion-bars" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><p class="motion-status" aria-live="polite">静态预览</p></div><figcaption><span></span><button type="button">播放 / Play</button><button type="button">重播 / Replay</button></figcaption>`;
  root.querySelector('figcaption span').textContent = title;
  root.style.setProperty('--demo-duration', `${duration}ms`);
  host.replaceChildren(root);
  const [play, replay] = root.querySelectorAll('button');
  const status = root.querySelector('.motion-status');
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let running = false;
  const update = () => { root.dataset.running = String(running); play.textContent = running ? '暂停 / Pause' : '播放 / Play'; play.setAttribute('aria-pressed', String(running)); status.textContent = running ? '记录 → 比较 → 解释 · 循环示意' : '已暂停 · 记录、比较、解释'; };
  const toggle = () => { running = !running; update(); };
  const restart = () => { for (const a of root.getAnimations({ subtree: true })) a.currentTime = 0; running = true; update(); };
  const pause = () => { running = false; update(); };
  const visibility = () => { if (document.hidden) pause(); };
  const preference = () => { if (reduced.matches) pause(); };
  play.addEventListener('click', toggle); replay.addEventListener('click', restart);
  document.addEventListener('visibilitychange', visibility); reduced.addEventListener('change', preference);
  update();
  return { pause, destroy() { play.removeEventListener('click', toggle); replay.removeEventListener('click', restart); document.removeEventListener('visibilitychange', visibility); reduced.removeEventListener('change', preference); root.remove(); } };
}
