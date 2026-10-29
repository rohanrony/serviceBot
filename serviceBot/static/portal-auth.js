(() => {
  const originalFetch = window.fetch.bind(window);
  let csrfToken = '';
  const ready = originalFetch('/api/v1/auth/session', { credentials: 'same-origin' })
    .then(async response => {
      if (!response.ok) {
        window.location.replace('/');
        return;
      }
      const session = await response.json();
      csrfToken = session.csrf_token;
    })
    .catch(() => window.location.replace('/'));

  window.fetch = async (input, init = {}) => {
    await ready;
    const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.href);
    if (url.origin === window.location.origin && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
      const headers = new Headers(init.headers || (input instanceof Request ? input.headers : undefined));
      if (!headers.has('X-CSRF-Token')) headers.set('X-CSRF-Token', csrfToken);
      init = { ...init, headers, credentials: 'same-origin' };
    }
    return originalFetch(input, init);
  };

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('admin-logout-btn')?.addEventListener('click', async () => {
      const response = await window.fetch('/api/v1/auth/logout', { method: 'POST' });
      if (response.ok) window.location.assign('/');
    });

    const form = document.getElementById('admin-password-form');
    const message = document.getElementById('admin-password-message');
    form?.addEventListener('submit', async event => {
      event.preventDefault();
      message.textContent = '';
      const data = new FormData(form);
      try {
        const response = await window.fetch('/api/v1/auth/password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.fromEntries(data.entries())),
        });
        if (!response.ok) throw new Error('Password change failed. Check your current password and new password confirmation.');
        csrfToken = '';
        window.location.assign('/');
      } catch (error) {
        message.textContent = error.message;
      }
    });
  });
})();
