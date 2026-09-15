'use strict';
/**
 * Capa de datos (SQLite via better-sqlite3, sincrono y sin servidor aparte).
 * Dos ficheros: app.db (usuarios y auditoria) y sessions.db (sesiones).
 */
const fs = require('fs');
const path = require('path');
const Database = require('better-sqlite3');
const config = require('./config');

fs.mkdirSync(config.dataDir, { recursive: true, mode: 0o700 });

const db = new Database(path.join(config.dataDir, 'app.db'));
db.pragma('journal_mode = WAL');   // mejor concurrencia lectura/escritura
db.pragma('foreign_keys = ON');
db.pragma('busy_timeout = 5000');

db.exec(`
  CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    display_name    TEXT,
    email           TEXT,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL DEFAULT 'user',
    is_active       INTEGER NOT NULL DEFAULT 1,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    last_login_at   TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS login_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username   TEXT,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ip         TEXT,
    user_agent TEXT,
    success    INTEGER NOT NULL,
    reason     TEXT,
    at         TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS idx_login_events_at ON login_events(at DESC);

  -- EL BLOQUEO DEL ACCESO, UNA SOLA FILA. Desde que el login no pide usuario
  -- (10-09-2026) un intento fallido no es de ninguna cuenta --la contrasena no
  -- cuadro con ninguna--, asi que los fallos se cuentan para la instalacion
  -- entera. Las columnas de bloqueo de la tabla users se quedan (las usa el
  -- CLI y no hacen dano), pero el login ya no las mira.
  CREATE TABLE IF NOT EXISTS bloqueo (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until    TEXT,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
  );
  INSERT OR IGNORE INTO bloqueo (id) VALUES (1);
`);

const stmt = {
  findByUsername: db.prepare('SELECT * FROM users WHERE username = ?'),
  findById:       db.prepare('SELECT * FROM users WHERE id = ?'),
  countUsers:     db.prepare('SELECT COUNT(*) AS n FROM users'),
  listUsers:      db.prepare(
    'SELECT id, username, display_name, email, role, is_active, last_login_at, created_at ' +
    'FROM users ORDER BY id'
  ),
  insertUser: db.prepare(`
    INSERT INTO users (username, display_name, email, password_hash, role)
    VALUES (@username, @display_name, @email, @password_hash, @role)
  `),
  updatePassword: db.prepare(`
    UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL,
                     updated_at = datetime('now')
    WHERE id = ?
  `),
  registerSuccess: db.prepare(`
    UPDATE users SET failed_attempts = 0, locked_until = NULL,
                     last_login_at = datetime('now'), updated_at = datetime('now')
    WHERE id = ?
  `),
  registerFailure: db.prepare(`
    UPDATE users SET failed_attempts = failed_attempts + 1, updated_at = datetime('now')
    WHERE id = ?
  `),
  lockAccount: db.prepare(`
    UPDATE users SET locked_until = datetime('now', ?), updated_at = datetime('now')
    WHERE id = ?
  `),
  insertLoginEvent: db.prepare(`
    INSERT INTO login_events (username, user_id, ip, user_agent, success, reason)
    VALUES (@username, @user_id, @ip, @user_agent, @success, @reason)
  `),
  recentEvents: db.prepare(
    'SELECT username, ip, success, reason, at FROM login_events ORDER BY id DESC LIMIT ?'
  ),
  // Las cuentas contra las que se comprueba la contrasena (ver lib/acceso.js).
  listActive: db.prepare('SELECT * FROM users WHERE is_active = 1 ORDER BY id'),
  // El bloqueo del acceso entero.
  bloqueoLeer:  db.prepare('SELECT * FROM bloqueo WHERE id = 1'),
  bloqueoFallo: db.prepare(`
    UPDATE bloqueo SET failed_attempts = failed_attempts + 1, updated_at = datetime('now')
    WHERE id = 1
  `),
  // Un bloqueo que ya vencio: se empieza a contar de cero (este fallo es el 1).
  bloqueoReiniciar: db.prepare(`
    UPDATE bloqueo SET failed_attempts = 1, locked_until = NULL, updated_at = datetime('now')
    WHERE id = 1
  `),
  bloqueoBloquear: db.prepare(`
    UPDATE bloqueo SET locked_until = datetime('now', ?), updated_at = datetime('now')
    WHERE id = 1
  `),
  bloqueoLimpiar: db.prepare(`
    UPDATE bloqueo SET failed_attempts = 0, locked_until = NULL, updated_at = datetime('now')
    WHERE id = 1
  `),
};

/** Devuelve los minutos que le quedan de bloqueo, o 0 si no esta bloqueado. */
function lockRemainingMinutes(user) {
  if (!user || !user.locked_until) return 0;
  const until = new Date(user.locked_until.replace(' ', 'T') + 'Z').getTime();
  if (Number.isNaN(until)) return 0;
  const diffMs = until - Date.now();
  return diffMs > 0 ? Math.ceil(diffMs / 60000) : 0;
}

/* ------------------------------------------------ el bloqueo del acceso ----
 * Una sola cuenta de fallos para toda la instalacion (ver la tabla `bloqueo`).
 * Es el mismo comportamiento que tenia el bloqueo por cuenta --N fallos, M
 * minutos, configurables en el .env-- aplicado a la unica puerta que hay. */

/** Minutos que le quedan al bloqueo del acceso, o 0. */
function minutosDeBloqueo() {
  return lockRemainingMinutes(stmt.bloqueoLeer.get());
}

/** Apunta un fallo y devuelve cuantos van seguidos. */
function registrarFallo() {
  const fila = stmt.bloqueoLeer.get() || {};
  // Si habia un bloqueo y ya ha vencido, la racha anterior no cuenta: esto es
  // el primer fallo de la nueva.
  if (fila.locked_until && lockRemainingMinutes(fila) === 0) {
    stmt.bloqueoReiniciar.run();
    return 1;
  }
  stmt.bloqueoFallo.run();
  return (stmt.bloqueoLeer.get() || {}).failed_attempts || 0;
}

function bloquearAcceso(minutos) {
  stmt.bloqueoBloquear.run(`+${Number(minutos) || 15} minutes`);
}

function limpiarBloqueo() {
  stmt.bloqueoLimpiar.run();
}

module.exports = {
  db, stmt, lockRemainingMinutes,
  minutosDeBloqueo, registrarFallo, bloquearAcceso, limpiarBloqueo,
};
