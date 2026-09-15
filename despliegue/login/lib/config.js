'use strict';
/**
 * Configuracion central. Todo lo sensible viene de variables de entorno
 * (systemd las inyecta desde /opt/studio-videos-ia/app/.env).
 */
const path = require('path');

function bool(value, fallback) {
  if (value === undefined || value === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(String(value).toLowerCase());
}

const config = {
  env: process.env.NODE_ENV || 'production',
  host: process.env.HOST || '127.0.0.1',
  port: Number(process.env.PORT || 3000),

  // URL publica. La canonica: la que se ensena y a la que se redirige.
  appUrl: process.env.APP_URL || '',

  // TODOS los nombres por los que se puede entrar, para comprobar el Origin de
  // las peticiones (anti-CSRF). Es una lista y no un valor porque el sitio
  // responde por varios nombres a la vez -- su dominio, el `www.` y el de la
  // maquina -- y con uno solo entrar por cualquiera de los otros daba «Origen
  // no permitido». Se declara a mano en APP_ORIGENES (separados por comas):
  // deducirla del Host de la peticion seria dejar que la ponga quien llama.
  origenes: (process.env.APP_ORIGENES || process.env.APP_URL || '')
    .split(',').map((s) => s.trim()).filter(Boolean),

  dataDir: process.env.DATA_DIR || path.join(__dirname, '..', '..', 'data'),

  sessionSecret: process.env.SESSION_SECRET || '',
  sessionName: process.env.SESSION_NAME || 'svi.sid',
  // Duracion de sesion (12 h por defecto), renovada en cada peticion.
  sessionMaxAgeMs: Number(process.env.SESSION_MAX_AGE_MS || 12 * 60 * 60 * 1000),

  // En produccion vamos detras de nginx con TLS: cookies solo por HTTPS.
  secureCookies: bool(process.env.SECURE_COOKIES, true),
  trustProxy: Number(process.env.TRUST_PROXY || 1),

  // Politica de bloqueo. Desde el 10-09-2026 el login no lleva usuario, asi
  // que el bloqueo es DEL ACCESO ENTERO (una sola cuenta de fallos para la
  // instalacion) y no por cuenta: sin nombre no hay a quien apuntar el fallo.
  maxFailedAttempts: Number(process.env.MAX_FAILED_ATTEMPTS || 8),
  lockoutMinutes: Number(process.env.LOCKOUT_MINUTES || 15),

  // El id del VPS en el panel de Hostinger (el numero de la URL del panel y del
  // nombre de la maquina, `srv<ID>`). Solo sirve para el enlace de «he olvidado
  // la contrasena» de la pantalla de acceso: la copia de la contrasena se lee
  // desde la consola web de ese panel. Vacio, la pantalla enlaza al listado de
  // VPS y el resto de las instrucciones vale igual.
  hostingerVpsId: String(process.env.HOSTINGER_VPS_ID || '').trim(),
};

if (!config.sessionSecret || config.sessionSecret.length < 32) {
  console.error(
    '[config] FATAL: falta SESSION_SECRET (o es demasiado corto: minimo 32 caracteres).\n' +
    '         Genera uno con: node -e "console.log(require(\'crypto\').randomBytes(48).toString(\'hex\'))"'
  );
  process.exit(1);
}

module.exports = config;
