import { mountMotionFigure } from './motion-figure.mjs';
mountMotionFigure(document.querySelector('#motion-demo'), { duration: 6000 });
const buttons = [...document.querySelectorAll('[data-filter]')];
const cards = [...document.querySelectorAll('[data-family]')];
for (const b of buttons) b.addEventListener('click', () => {
 for (const other of buttons) other.setAttribute('aria-pressed', String(other === b));
 let count = 0;
 for (const card of cards) { card.hidden = b.dataset.filter !== 'all' && card.dataset.family !== b.dataset.filter; if (!card.hidden) count++; }
 document.querySelector('#count').textContent = `${count} 个来源 / sources`;
});
