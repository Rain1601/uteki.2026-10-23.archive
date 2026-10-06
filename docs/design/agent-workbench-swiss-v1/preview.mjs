// Presentation controls only. Never reload or rerender the shared #app.
const COPY = {
  zh: {
    title: '后台排版预览', scope: '同一组演示任务', engineering: '工程阅读型', editorial: '编辑排版型',
    baseline: '打开现版对照', options: '排版方案', shell: '独立视觉预览',
    announcement: '已切换排版；任务、草稿与打开的产物保持不变。',
  },
  en: {
    title: 'Workbench typography', scope: 'Same demo tasks', engineering: 'Engineering', editorial: 'Editorial',
    baseline: 'Compare current version', options: 'Typography option', shell: 'Independent visual preview',
    announcement: 'Typography changed. Your task, drafts and open artifact are unchanged.',
  },
};
const VARIANTS = ['engineering', 'editorial'];

export function createPreviewControls(shell, environment = globalThis) {
  if (!shell) throw new Error('An explicit preview shell is required');
  const document = environment.document;
  if (!document?.documentElement) throw new Error('A document root is required');
  const root = document.documentElement;
  let observer = null;
  const lang = () => root.lang?.toLowerCase().startsWith('en') ? 'en' : 'zh';
  const current = () => root.dataset.previewStyle;
  if (!VARIANTS.includes(current())) throw new Error('Unknown preview style');

  function sync() {
    const copy = COPY[lang()];
    shell.setAttribute('aria-label', copy.shell);
    shell.querySelector('[data-preview-options]')?.setAttribute('aria-label', copy.options);
    for (const element of shell.querySelectorAll('[data-preview-copy]')) {
      const key = element.dataset.previewCopy;
      if (!Object.hasOwn(copy, key)) throw new Error(`Unknown preview text: ${key}`);
      element.textContent = copy[key];
    }
    for (const button of shell.querySelectorAll('[data-preview-variant]')) {
      button.setAttribute('aria-pressed', String(button.dataset.previewVariant === current()));
    }
  }

  function select(variant) {
    if (!VARIANTS.includes(variant)) throw new Error('Unknown preview style');
    if (current() === variant) return;
    root.dataset.previewStyle = variant;
    sync();
    const announcement = shell.querySelector('[data-preview-announcement]');
    if (announcement) announcement.textContent = COPY[lang()].announcement;
  }

  function click(event) {
    const button = event.target.closest?.('[data-preview-variant]');
    if (button && shell.contains(button)) select(button.dataset.previewVariant);
  }
  sync();
  shell.addEventListener('click', click);
  if (environment.MutationObserver) {
    observer = new environment.MutationObserver(() => {
      sync();
      const announcement = shell.querySelector('[data-preview-announcement]');
      if (announcement) announcement.textContent = '';
    });
    observer.observe(root, { attributes: true, attributeFilter: ['lang'] });
  }
  return {
    select, sync, getStyle: current,
    dispose() { shell.removeEventListener('click', click); observer?.disconnect(); },
  };
}

if (typeof document !== 'undefined') {
  const shell = document.querySelector('[data-preview-shell]');
  if (shell) createPreviewControls(shell);
}
