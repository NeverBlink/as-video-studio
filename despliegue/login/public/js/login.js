/* Studio Videos IA — logica del formulario de acceso.
   Solo se pide la contraseña: ella dice de qué cuenta es (lib/acceso.js). */
(function () {
  'use strict';

  const form       = document.getElementById('loginForm');
  const password   = document.getElementById('password');
  const submit     = document.getElementById('submit');
  const submitText = document.getElementById('submitText');
  const errorBox   = document.getElementById('error');
  const errorText  = document.getElementById('errorText');
  const reveal     = document.getElementById('reveal');
  const eyeOpen    = document.getElementById('eyeOpen');
  const eyeClosed  = document.getElementById('eyeClosed');
  const panelLink  = document.getElementById('panelLink');

  let csrfToken = null;
  let saliendo  = false;

  /* --- por donde se ha entrado -------------------------------------------- */
  /* Hay dos versiones del estudio en el mismo dominio (la 1 en la raiz, la 2 en
     /v2/) y un solo login. Lo que dice a cual se vuelve es la direccion por la
     que se llego: quien pide algo de /v2/ acaba en /v2/login, y de ahi se
     vuelve a /v2/. nginx puede ademas apuntar la pagina exacta en `?next=`.
     El servidor no se lo cree sin mirar: valida la ruta antes de devolverla. */
  function destino() {
    const pedido = new URLSearchParams(window.location.search).get('next');
    if (pedido) return pedido;
    return window.location.pathname.startsWith('/v2/') ? '/v2/' : '';
  }

  /* Y se dice cual es, que si no el login de la v2 no se distingue del de la v1. */
  (function marcarVersion() {
    if (!window.location.pathname.startsWith('/v2/')) return;
    document.title = 'Acceso · AS Video Studio';
    const sub = document.querySelector('.card__sub');
    if (sub) sub.textContent = 'AS Video Studio';
  })();

  /* --- token anti-CSRF: se pide al cargar y se refresca si caduca ---------- */
  /* Con el token viaja el enlace al VPS en el panel de Hostinger, para el «he
     olvidado la contraseña»: el id del VPS lo sabe el servidor (.env), no esta
     pagina. Sin id se queda el enlace al listado de VPS, que tambien sirve. */
  async function fetchCsrf() {
    try {
      const res  = await fetch('/api/csrf', { credentials: 'same-origin' });
      const data = await res.json();
      csrfToken = data.csrfToken || null;
      const panel = (data.recuperacion || {}).panel;
      if (panelLink && panel && /^https:\/\/hpanel\.hostinger\.com\//.test(panel)) {
        panelLink.href = panel;
      }
    } catch {
      csrfToken = null;
    }
    return csrfToken;
  }
  fetchCsrf();

  /* --- avisos ------------------------------------------------------------- */
  function showError(message) {
    errorText.textContent = message;
    errorBox.classList.add('is-visible');
  }
  function clearError() {
    errorBox.classList.remove('is-visible');
  }

  /* --- estado del boton --------------------------------------------------- */
  function setLoading(loading) {
    submit.disabled = loading;
    password.disabled = loading;
    submitText.textContent = loading ? 'Comprobando…' : 'Entrar';

    const old = submit.querySelector('.spinner');
    if (old) old.remove();
    if (loading) {
      const sp = document.createElement('span');
      sp.className = 'spinner';
      submit.prepend(sp);
    }
  }

  /* --- mostrar / ocultar contraseña --------------------------------------- */
  reveal.addEventListener('click', function () {
    const isText = password.type === 'text';
    password.type = isText ? 'password' : 'text';
    eyeOpen.classList.toggle('is-hidden', !isText);
    eyeClosed.classList.toggle('is-hidden', isText);
    reveal.setAttribute('aria-pressed', String(!isText));
    reveal.setAttribute('aria-label', isText ? 'Mostrar contraseña' : 'Ocultar contraseña');
    password.focus();
  });

  password.addEventListener('input', clearError);

  /* --- envío -------------------------------------------------------------- */
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    clearError();

    const pass = password.value;

    if (!pass) {
      showError('Escribe tu contraseña.');
      password.focus();
      return;
    }

    setLoading(true);

    try {
      if (!csrfToken) await fetchCsrf();

      let res = await send(pass);

      // Si el token había caducado (sesión reiniciada), lo renovamos y reintentamos una vez.
      if (res.status === 403) {
        await fetchCsrf();
        res = await send(pass);
      }

      const data = await res.json().catch(() => ({}));

      if (res.ok && data.ok) {
        saliendo = true;
        submitText.textContent = 'Entrando…';
        // Redirección dura: que la página la sirva el servidor con la sesión ya
        // activa. A dónde, lo dice él (ver `destinoTrasLogin`).
        window.location.assign(data.redirect || '/studio');
        return;
      }

      showError(data.error || 'No se ha podido iniciar sesión. Inténtalo de nuevo.');
      password.value = '';
      password.focus();
    } catch {
      showError('No hay conexión con el servidor. Comprueba tu red e inténtalo de nuevo.');
    } finally {
      // Mientras el navegador va a la página siguiente el botón se queda como
      // está: volver a habilitarlo sólo deja un parpadeo de «Entrar» encima de
      // una pantalla que ya se ha ido.
      if (!saliendo) setLoading(false);
    }
  });

  function send(pass) {
    return fetch('/api/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken || '',
      },
      body: JSON.stringify({ password: pass, next: destino() }),
    });
  }
})();
