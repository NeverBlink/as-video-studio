'use strict';
/**
 * Middleware de seguridad: guardas de sesion y proteccion CSRF.
 *
 * Estrategia anti-CSRF, tres capas independientes:
 *   1. Cookie de sesion con SameSite=Lax  -> el navegador no la manda en POST cross-site.
 *   2. Comprobacion de la cabecera Origin -> debe coincidir con la URL publica.
 *   3. Token sincronizador en sesion      -> el cliente lo repite en X-CSRF-Token.
 */
const crypto = require('crypto');
const config = require('./config');
const { randomToken } = require('./auth');

function ensureCsrfToken(req) {
  if (!req.session.csrfToken) req.session.csrfToken = randomToken(32);
  return req.session.csrfToken;
}

/** Compara dos strings en tiempo constante, tolerando longitudes distintas. */
function safeEqual(a, b) {
  const bufA = Buffer.from(String(a || ''), 'utf8');
  const bufB = Buffer.from(String(b || ''), 'utf8');
  if (bufA.length !== bufB.length || bufA.length === 0) return false;
  return crypto.timingSafeEqual(bufA, bufB);
}

function verifyCsrf(req, res, next) {
  if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) return next();

  // Capa 2: el Origin debe ser el nuestro.
  //
  // UNO NO BASTA: EL SITIO TIENE VARIOS NOMBRES. Se comparaba contra `appUrl` y
  // nada mas, asi que al darle un dominio propio al servidor entrar por el
  // devolvia «Origen no permitido» -- la peticion venia de studiovideo.cloud y
  // aqui solo valia srv1944562.hstgr.cloud, que es el nombre de la maquina.
  //
  // Se comprueba contra una LISTA declarada (config.origenes), no contra el
  // Host de la peticion: el Host lo pone quien llama, asi que aceptarlo sin
  // mas seria no comprobar nada. Anadir un dominio es meterlo en el .env, del
  // mismo modo que hay que meterlo en el certificado.
  const origin = req.get('origin');
  if (origin) {
    // SIN LISTA DECLARADA se cae al host de la peticion, que es lo que hacia
    // antes: sin configurar (un portatil, una prueba) no hay nombre publico
    // contra el que comparar, y rechazarlo todo dejaria el login inservible.
    // En produccion la lista SIEMPRE esta puesta, asi que este camino no se usa.
    const permitidos = config.origenes.length
      ? config.origenes
      : [`${req.protocol}://${req.get('host')}`];
    let ok = false;
    try {
      const suyo = new URL(origin).origin;
      ok = permitidos.some((permitido) => {
        try { return new URL(permitido).origin === suyo; } catch { return false; }
      });
    } catch { ok = false; }
    if (!ok) {
      return res.status(403).json({ ok: false, error: 'Origen no permitido.' });
    }
  }

  // Capa 3: token sincronizador.
  const sent = req.get('x-csrf-token') || (req.body && req.body._csrf);
  if (!req.session.csrfToken || !safeEqual(sent, req.session.csrfToken)) {
    return res.status(403).json({
      ok: false,
      error: 'Token de seguridad caducado. Recarga la pagina e intentalo de nuevo.',
    });
  }
  return next();
}

/* ------------------------------------------------------ las dos puertas ----
 * El sitio sirve DOS versiones del estudio en el mismo dominio: la 1 en la raiz
 * y la 2 en `/v2/`, cada una con su proceso detras (eso lo enruta nginx). El
 * login es UNO -- misma pantalla, misma sesion, y la cookie vale para las dos
 * porque va con `path=/` --, asi que lo unico que hay que recordar es POR DONDE
 * SE ENTRO, o quien pide la v2 acaba entrando en la v1.
 *
 * Se recuerda en la direccion, no en la sesion: cada version tiene su login
 * (`/login` y `/v2/login`) y el destino viaja en `?next=`. Una sesion con
 * memoria mandaria a la v2 a quien tuviera la v1 abierta en otra pestana.
 */
const LOGIN_V2 = '/v2/login';

/** El login que le toca a una direccion: el de la v2 si la direccion es de la v2. */
function loginDe(ruta) {
  const texto = String(ruta || '');
  return (texto === '/v2' || texto.startsWith('/v2/')) ? LOGIN_V2 : '/login';
}

/**
 * A donde se va tras entrar. `crudo` es lo que dice el cliente, y NO se cree
 * sin mirar: solo se acepta una ruta de ESTE sitio. Lo que no encaja no es un
 * error -- se vuelve al `respaldo`, que es la puerta por la que se entro.
 *
 * LO QUE HAY QUE DESCARTAR, y por que:
 *
 *   * `//otro.com` y su version con barra invertida **no son rutas**: el
 *     navegador las lee como un HOST. Devolverlas seria una redireccion
 *     abierta -- se reparte un enlace a `/login?next=//otro.com`, la victima
 *     escribe su contrasena en el login de VERDAD y acaba en una copia con
 *     pinta de haber entrado bien.
 *   * los espacios, las comillas y las barras invertidas no aparecen en una
 *     ruta legitima (viajan codificados), asi que ninguno tiene que pasar.
 *   * `/api/...` no es una pagina: es JSON, y acabar mirandolo no es entrar.
 */
function destinoTrasLogin(crudo, respaldo) {
  const texto = String(crudo || '').trim();
  if (!texto || texto[0] !== '/' || texto[1] === '/') return respaldo;
  if (/[\\\s"'<>]/.test(texto)) return respaldo;
  const ruta = texto.split('?')[0].split('#')[0];
  if (ruta === '/login' || ruta === LOGIN_V2) return respaldo;
  if (ruta.includes('/api/')) return respaldo;
  return texto;
}

/** Exige sesion iniciada. Responde JSON o redirige segun lo que pida el cliente. */
function requireAuth(req, res, next) {
  if (req.session && req.session.userId) return next();

  const wantsJson = req.originalUrl.startsWith('/api/') ||
    (req.get('accept') || '').includes('application/json');

  if (wantsJson) {
    return res.status(401).json({ ok: false, error: 'No has iniciado sesion.' });
  }
  const next_ = encodeURIComponent(req.originalUrl);
  return res.redirect(`${loginDe(req.path)}?next=${next_}`);
}

/** Si ya hay sesion, el login no tiene nada que preguntar: a su sitio. */
function redirectIfAuthenticated(req, res, next) {
  if (!req.session || !req.session.userId) return next();
  // El defecto de la v1 se queda como estaba (`/studio`, el panel de Node); el
  // de la v2 es su portada, que es lo unico que sirve por ahi.
  const casa = loginDe(req.path) === LOGIN_V2 ? '/v2/' : '/studio';
  return res.redirect(destinoTrasLogin(req.query && req.query.next, casa));
}

module.exports = {
  ensureCsrfToken, verifyCsrf, requireAuth, redirectIfAuthenticated, safeEqual,
  loginDe, destinoTrasLogin, LOGIN_V2,
};
