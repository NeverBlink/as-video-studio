/* Studio Videos IA — panel principal */
(function () {
  'use strict';

  const userName  = document.getElementById('userName');
  const avatar    = document.getElementById('avatar');
  const logout    = document.getElementById('logout');
  const loginTime = document.getElementById('loginTime');
  const lastLogin = document.getElementById('lastLogin');

  const EMDASH = '—';
  let csrfToken = null;

  function formatDate(iso) {
    if (!iso) return EMDASH;
    // SQLite guarda "YYYY-MM-DD HH:MM:SS" en UTC; lo normalizamos a ISO real.
    const normalized = iso.includes('T') ? iso : iso.replace(' ', 'T') + 'Z';
    const date = new Date(normalized);
    if (isNaN(date.getTime())) return EMDASH;
    return date.toLocaleString('es-ES', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  async function getCsrf() {
    if (csrfToken) return csrfToken;
    try {
      const res = await fetch('/api/csrf', { credentials: 'same-origin' });
      csrfToken = (await res.json()).csrfToken || null;
    } catch (err) {
      csrfToken = null;
    }
    return csrfToken;
  }

  async function load() {
    try {
      const res = await fetch('/api/me', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });

      if (res.status === 401) { window.location.assign('/login'); return; }

      const data = await res.json();
      if (!data.ok) { window.location.assign('/login'); return; }

      const name = data.user.displayName || data.user.username;
      userName.textContent = name;
      avatar.textContent = name.trim().charAt(0).toUpperCase();
      loginTime.textContent = formatDate(data.loggedInAt);
      lastLogin.textContent = formatDate(data.user.lastLoginAt);
    } catch (err) {
      userName.textContent = 'sin conexion';
    }
    getCsrf();
  }

  logout.addEventListener('click', async function () {
    logout.disabled = true;
    logout.textContent = 'Saliendo...';
    try {
      const token = await getCsrf();
      await fetch('/api/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token || '' },
      });
    } catch (err) {
      // Aunque falle la llamada, sacamos al usuario de la pantalla.
    }
    window.location.assign('/login');
  });

  load();
})();
