'use strict';
/**
 * Studio Videos IA - servidor HTTP.
 *
 * Escucha solo en localhost: nginx hace de proxy inverso y termina el TLS.
 */
const path = require('path');
const express = require('express');
const helmet = require('helmet');
const session = require('express-session');
const Database = require('better-sqlite3');
const SqliteStore = require('better-sqlite3-session-store')(session);

const config = require('./lib/config');
const { stmt } = require('./lib/db');
const authRoutes = require('./routes/auth');
const { requireAuth, redirectIfAuthenticated } = require('./lib/middleware');

const app = express();
const PUBLIC_DIR = path.join(__dirname, 'public');

// Vamos detras de nginx: hace falta para que req.ip, req.protocol y las
// cookies "secure" reflejen la peticion original y no la del proxy.
app.set('trust proxy', config.trustProxy);
app.disable('x-powered-by');

// ---------------------------------------------------------------- seguridad
app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      styleSrc: ["'self'", 'https://fonts.googleapis.com'],
      fontSrc: ["'self'", 'https://fonts.gstatic.com'],
      imgSrc: ["'self'", 'data:'],
      connectSrc: ["'self'"],
      objectSrc: ["'none'"],
      frameAncestors: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
      upgradeInsecureRequests: config.secureCookies ? [] : null,
    },
  },
  hsts: config.secureCookies
    ? { maxAge: 15552000, includeSubDomains: true }
    : false,
  referrerPolicy: { policy: 'same-origin' },
  crossOriginEmbedderPolicy: false,
}));

app.use(express.json({ limit: '32kb' }));
app.use(express.urlencoded({ extended: false, limit: '32kb' }));

// ---------------------------------------------------------------- sesiones
const sessionDb = new Database(path.join(config.dataDir, 'sessions.db'));
sessionDb.pragma('journal_mode = WAL');

app.use(session({
  name: config.sessionName,
  secret: config.sessionSecret,
  resave: false,
  saveUninitialized: false,
  rolling: true,                 // renueva la caducidad en cada peticion
  store: new SqliteStore({
    client: sessionDb,
    expired: { clear: true, intervalMs: 15 * 60 * 1000 },
  }),
  cookie: {
    httpOnly: true,              // invisible para JavaScript: mitiga XSS
    secure: config.secureCookies,
    sameSite: 'lax',             // no viaja en peticiones cross-site
    maxAge: config.sessionMaxAgeMs,
    path: '/',
  },
}));

// ---------------------------------------------------------------- estaticos
// CSS y JS: sin cache ciega. El navegador revalida y recibe un 304 si no ha
// cambiado nada, asi un despliegue se ve al instante sin forzar recarga.
const STATIC_REVALIDATE = { maxAge: 0, etag: true, lastModified: true, cacheControl: true };
app.use('/assets', express.static(path.join(PUBLIC_DIR, 'assets'), {
  maxAge: '7d',
  index: false,
}));
app.use('/css', express.static(path.join(PUBLIC_DIR, 'css'), STATIC_REVALIDATE));
app.use('/js',  express.static(path.join(PUBLIC_DIR, 'js'),  STATIC_REVALIDATE));

// ---------------------------------------------------------------- API
app.use('/api', authRoutes);

app.get('/api/health', (req, res) => {
  let users = null;
  try { users = stmt.countUsers.get().n; } catch { /* ignorado */ }
  res.json({ ok: true, service: 'studio-videos-ia', users, uptimeSec: Math.round(process.uptime()) });
});

// Punto interno para el `auth_request` de nginx. No lo llama un navegador: lo
// llama nginx en cada peticion para saber DOS cosas de una vez -- si hay sesion
// y DE QUIEN es --, porque cada cuenta tiene su propio proceso de Studio y hay
// que enrutar al suyo. El nombre viaja en una cabecera que nginx recoge con
// `auth_request_set`; el cuerpo va vacio a proposito.
app.get('/api/_auth', (req, res) => {
  if (!req.session || !req.session.userId || !req.session.username) {
    return res.status(401).end();
  }
  res.set('X-Studio-User', req.session.username);
  return res.status(200).end();
});

// ---------------------------------------------------------------- paginas
app.get('/', (req, res) => {
  res.redirect(req.session && req.session.userId ? '/studio' : '/login');
});

// El login, uno por version. Es LA MISMA pantalla y la misma sesion: lo unico
// que cambia es la direccion por la que se entra, y con ella a donde se vuelve
// al terminar. Node tiene que ver la direccion ENTERA para saberlo, asi que
// nginx le pasa `/v2/login` sin recortar el prefijo -- al contrario que el
// resto de `/v2/`, que va al proceso de la version 2 ya recortado.
for (const puerta of ['/login', '/v2/login']) {
  app.get(puerta, redirectIfAuthenticated, (req, res) => {
    res.sendFile(path.join(PUBLIC_DIR, 'login.html'));
  });
}

app.get('/studio', requireAuth, (req, res) => {
  res.sendFile(path.join(PUBLIC_DIR, 'studio.html'));
});

// ---------------------------------------------------------------- errores
app.use((req, res) => {
  if (req.path.startsWith('/api/')) {
    return res.status(404).json({ ok: false, error: 'Recurso no encontrado.' });
  }
  res.status(404).sendFile(path.join(PUBLIC_DIR, '404.html'));
});

app.use((err, req, res, _next) => {
  console.error('[error]', err);
  if (res.headersSent) return;
  if (req.path.startsWith('/api/')) {
    return res.status(500).json({ ok: false, error: 'Error interno del servidor.' });
  }
  res.status(500).send('Error interno del servidor.');
});

// ---------------------------------------------------------------- arranque
const server = app.listen(config.port, config.host, () => {
  const n = (() => { try { return stmt.countUsers.get().n; } catch { return '?'; } })();
  console.log(`[studio-videos-ia] escuchando en http://${config.host}:${config.port}`);
  console.log(`[studio-videos-ia] entorno=${config.env}  usuarios=${n}  datos=${config.dataDir}`);
  if (n === 0) {
    console.warn('[studio-videos-ia] AVISO: no hay usuarios. Crea uno con: npm run user -- create <usuario>');
  }
});

for (const signal of ['SIGTERM', 'SIGINT']) {
  process.on(signal, () => {
    console.log(`[studio-videos-ia] ${signal} recibido, cerrando...`);
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 8000).unref();
  });
}
