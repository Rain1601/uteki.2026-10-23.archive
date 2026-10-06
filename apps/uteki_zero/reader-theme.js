// Runs before the stylesheet to avoid showing the wrong theme for a frame.
(() => {
  let preference = 'system', fontSize = 17;
  try {
    const saved = JSON.parse(localStorage.getItem('uteki.workspace-prototype.v3') || localStorage.getItem('uteki.workspace-prototype.v2') || 'null');
    if (['system', 'light', 'dark'].includes(saved?.theme)) preference = saved.theme;
    if ([16, 17, 18].includes(saved?.fontSize)) fontSize = saved.fontSize;
  } catch { /* The reader reports unavailable storage after initialization. */ }
  const theme = preference === 'system' ? (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light') : preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.setProperty('--reading-size', `${fontSize}px`);
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#15181d' : '#f5f6f7');
})();
