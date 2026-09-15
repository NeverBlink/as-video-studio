'use strict';
/**
 * Rutas de autenticacion: /api/csrf, /api/login, /api/logout, /api/me
 *
 * EL LOGIN NO LLEVA USUARIO (10-09-2026). Se manda solo la contrasena y ella
 * dice de que cuenta es (`lib/acceso.elegirCuenta`). Lo demas --sesion, CSRF,
 * limites, auditoria-- es lo que habia; lo que cambia es que el bloqueo por
 * intentos es del acceso entero y no de una cuenta, porque sin nombre no hay a
 * quien apuntarselo.
 */
const express = require('express');
const rateLimit = require('express-rate-limit');

const config = require('../lib/config');
const { elegirCuenta, urlPanelHostinger } = require('../lib/acceso');
const {
  stmt, minutosDeBloqueo, registrarFallo, bloquearAcceso, limpiarBloqueo,
} = require('../lib/db');
const {
  ensureCsrfToken, verifyCsrf, requireAuth, destinoTrasLogin,
} = require('../lib/middleware');

const router = express.Router();

// Limite por IP: frena el fuerza bruta distribuido.
const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 20,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: {
    ok: false,
    error: 'Demasiados intentos desde esta IP. Espera 15 minutos e intentalo de nuevo.',
  },
});

/** Registra el intento en la tabla de auditoria. Nunca debe tumbar el login. */
function audit(req, { username, userId, success, reason }) {
  try {
    stmt.insertLoginEvent.run({
      username: username || null,
      user_id: userId || null,
      ip: req.ip || null,
      user_agent: (req.get('user-agent') || '').slice(0, 300),
      success: success ? 1 : 0,
      reason: reason || null,
    });
  } catch (err) {
    console.error('[audit] no se pudo registrar el evento:', err.message);
  }
}

function publicUser(user) {
  return {
    id: user.id,
    username: user.username,
    displayName: user.display_name || user.username,
    email: user.email || null,
    role: user.role,
    lastLoginAt: user.last_login_at || null,
  };
}

// El cliente pide el token antes de enviar el formulario. Viaja con el ADEMAS
// lo que la pantalla necesita para el «he olvidado la contrasena»: el enlace al
// VPS en el panel de Hostinger. Va aqui y no en una ruta propia porque nginx
// solo pasa a Node las rutas que tiene declaradas una a una, y esta ya lo esta.
router.get('/csrf', (req, res) => {
  res.json({
    ok: true,
    csrfToken: ensureCsrfToken(req),
    recuperacion: { panel: urlPanelHostinger(config.hostingerVpsId) },
  });
});

router.post('/login', loginLimiter, verifyCsrf, async (req, res) => {
  const password = String((req.body && req.body.password) || '');

  // POR DONDE SE ENTRO. Lo manda la pantalla del login (lo saca de su propia
  // direccion) y aqui se valida: de fabrica, la raiz. Se calcula ANTES de
  // regenerar la sesion, que es lo que se lleva por delante el cuerpo.
  const destino = destinoTrasLogin(req.body && req.body.next, '/');

  if (!password) {
    audit(req, { success: false, reason: 'campos_vacios' });
    return res.status(400).json({ ok: false, error: 'Escribe la contrasena.' });
  }

  const bloqueado = minutosDeBloqueo();
  if (bloqueado > 0) {
    audit(req, { success: false, reason: 'acceso_bloqueado' });
    return res.status(429).json({
      ok: false,
      error: `Acceso bloqueado temporalmente. Vuelve a intentarlo en ${bloqueado} min.`,
    });
  }

  const cuentas = stmt.listActive.all();
  const user = await elegirCuenta(password, cuentas);

  if (!user) {
    const intentos = registrarFallo();
    let error = 'Contrasena incorrecta.';
    if (intentos >= config.maxFailedAttempts) {
      bloquearAcceso(config.lockoutMinutes);
      error = `Demasiados intentos fallidos. Acceso bloqueado ${config.lockoutMinutes} minutos.`;
    }
    // Sin cuentas no hay contrasena que pueda cuadrar: se apunta como lo que
    // es, que es lo que se ve en el `log` cuando un despliegue nuevo no llego a
    // crear la cuenta.
    audit(req, { success: false, reason: cuentas.length ? 'password_incorrecta' : 'sin_cuentas' });
    return res.status(401).json({ ok: false, error });
  }

  // Login correcto. Regeneramos la sesion para evitar session fixation:
  // el identificador que tuviera el atacante antes del login deja de valer.
  req.session.regenerate((err) => {
    if (err) {
      console.error('[login] fallo al regenerar la sesion:', err);
      return res.status(500).json({ ok: false, error: 'Error interno. Intentalo de nuevo.' });
    }
    req.session.userId = user.id;
    req.session.username = user.username;
    req.session.loggedInAt = new Date().toISOString();
    ensureCsrfToken(req);

    stmt.registerSuccess.run(user.id);
    limpiarBloqueo();
    audit(req, { username: user.username, userId: user.id, success: true, reason: 'ok' });

    req.session.save((saveErr) => {
      if (saveErr) {
        console.error('[login] fallo al guardar la sesion:', saveErr);
        return res.status(500).json({ ok: false, error: 'Error interno. Intentalo de nuevo.' });
      }
      // A la raiz -- ahi es donde nginx sirve Studio, el proceso de esta
      // cuenta --, o a la version por la que se haya entrado.
      res.json({ ok: true, redirect: destino, user: publicUser(user) });
    });
  });
});

router.post('/logout', verifyCsrf, (req, res) => {
  req.session.destroy(() => {
    res.clearCookie(config.sessionName);
    res.json({ ok: true, redirect: '/login' });
  });
});

router.get('/me', requireAuth, (req, res) => {
  const user = stmt.findById.get(req.session.userId);
  if (!user || !user.is_active) {
    return req.session.destroy(() =>
      res.status(401).json({ ok: false, error: 'Sesion no valida.' })
    );
  }
  res.json({ ok: true, user: publicUser(user), loggedInAt: req.session.loggedInAt || null });
});

module.exports = router;
