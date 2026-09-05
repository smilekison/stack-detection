(() => {
  const key = 'autodeploy-theme';
  const saved = localStorage.getItem(key);
  const initial = saved === 'light' || saved === 'dark' ? saved : 'dark';
  document.documentElement.dataset.theme = initial;

  const apply = theme => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.classList.add('theme-transition');
    localStorage.setItem(key, theme);
    const button = document.getElementById('theme-toggle');
    if (button) {
      const light = theme === 'light';
      button.setAttribute('aria-label', light ? 'Switch to dark mode' : 'Switch to light mode');
      button.title = light ? 'Switch to dark mode' : 'Switch to light mode';
      button.innerHTML = `<span class="theme-icon">${light ? '☾' : '☀'}</span><span>${light ? 'Dark' : 'Light'}</span>`;
    }
    window.setTimeout(() => document.documentElement.classList.remove('theme-transition'), 250);
  };

  const mount = () => {
    if (document.getElementById('theme-toggle')) return;
    const top = document.querySelector('.top');
    if (!top) return;
    const version = top.querySelector('.version');
    const actions = document.createElement('div');
    actions.className = 'top-actions';
    const button = document.createElement('button');
    button.id = 'theme-toggle';
    button.className = 'theme-toggle';
    button.type = 'button';
    button.addEventListener('click', () => apply(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light'));
    actions.appendChild(button);
    if (version) actions.appendChild(version);
    top.appendChild(actions);
    apply(document.documentElement.dataset.theme);
  };

  new MutationObserver(mount).observe(document.body, { childList: true, subtree: true });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();
})();
