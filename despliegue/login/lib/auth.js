'use strict';
/**
 * Hash y verificacion de contrasenas con scrypt (crypto nativo de Node).
 *
 * scrypt es memory-hard: encarece mucho el crackeo por GPU/ASIC frente a
 * un simple SHA. No hace falta ninguna dependencia nativa extra.
 *
 * Formato almacenado:  scrypt$N$r$p$saltHex$hashHex
 */
const crypto = require('crypto');
const { promisify } = require('util');

const scrypt = promisify(crypto.scrypt);

// 128 * N * r = 32 MiB de memoria por hash. Coste ~100-200 ms por intento.
const PARAMS = { N: 32768, r: 8, p: 1, keylen: 64, maxmem: 96 * 1024 * 1024 };

async function hashPassword(password) {
  if (typeof password !== 'string' || password.length < 12) {
    throw new Error('La contrasena debe tener al menos 12 caracteres.');
  }
  const salt = crypto.randomBytes(16);
  const derived = await scrypt(password.normalize('NFKC'), salt, PARAMS.keylen, PARAMS);
  return [
    'scrypt', PARAMS.N, PARAMS.r, PARAMS.p,
    salt.toString('hex'), derived.toString('hex'),
  ].join('$');
}

async function verifyPassword(password, stored) {
  if (typeof password !== 'string' || typeof stored !== 'string') return false;

  const parts = stored.split('$');
  if (parts.length !== 6 || parts[0] !== 'scrypt') return false;

  const [, nStr, rStr, pStr, saltHex, hashHex] = parts;
  const N = Number(nStr), r = Number(rStr), p = Number(pStr);
  if (!Number.isInteger(N) || !Number.isInteger(r) || !Number.isInteger(p)) return false;

  let expected;
  try {
    expected = Buffer.from(hashHex, 'hex');
  } catch {
    return false;
  }
  if (expected.length === 0) return false;

  let derived;
  try {
    derived = await scrypt(
      password.normalize('NFKC'),
      Buffer.from(saltHex, 'hex'),
      expected.length,
      { N, r, p, maxmem: PARAMS.maxmem }
    );
  } catch {
    return false;
  }

  // Comparacion en tiempo constante: no filtra informacion por timing.
  return crypto.timingSafeEqual(derived, expected);
}

/**
 * Genera una contrasena aleatoria legible y robusta.
 * Alfabeto sin caracteres ambiguos (0/O, 1/l/I) para poder dictarla o copiarla
 * sin errores. Con 24 caracteres sobre 58 simbolos son ~140 bits de entropia.
 */
function generatePassword(length = 24) {
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789';
  const symbols = '@#%+=?';
  const pool = alphabet + symbols;
  const out = [];
  // Rechazo de modulo: mantiene la distribucion perfectamente uniforme.
  const limit = 256 - (256 % pool.length);
  while (out.length < length) {
    for (const byte of crypto.randomBytes(length)) {
      if (byte >= limit) continue;
      out.push(pool[byte % pool.length]);
      if (out.length === length) break;
    }
  }
  return out.join('');
}

function randomToken(bytes = 32) {
  return crypto.randomBytes(bytes).toString('base64url');
}

module.exports = { hashPassword, verifyPassword, generatePassword, randomToken };
