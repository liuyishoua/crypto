(() => {
  const root = document.documentElement;
  const apply = value => {
    root.dataset.theme = value === 'dark' ? 'dark' : 'light';
    document.querySelector('.theme-toggle')?.setAttribute('aria-label', value === 'dark' ? '切换到白天模式' : '切换到黑夜模式');
    window.dispatchEvent(new Event('workspace-theme-change'));
  };
  let preference;
  try { preference = localStorage.getItem('workspace-theme'); } catch {}
  apply(preference || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
  document.addEventListener('DOMContentLoaded', () => {
    apply(root.dataset.theme);
    document.querySelector('.theme-toggle')?.addEventListener('click', () => {
      const value = root.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(value);
      try { localStorage.setItem('workspace-theme',value); } catch {}
    });
  });
  window.addEventListener('storage', event => { if (event.key === 'workspace-theme') apply(event.newValue); });
})();
