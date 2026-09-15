'use strict';
/**
 * EL ACCESO ES UNA CONTRASENA, SIN USUARIO (10-09-2026).
 *
 * La pantalla pide solo la contrasena, y LA CONTRASENA IDENTIFICA LA CUENTA: se
 * comprueba contra todas las cuentas activas y la que cuadra es la que entra.
 * Asi no hace falta nombre de usuario en la pantalla y, a la vez, nginx sigue
 * sabiendo de quien es la sesion (`X-Studio-User`) para enrutar a SU proceso
 * de Studio: un VPS con una cuenta tiene una contrasena; este, con dos, tiene
 * dos. Es lo que permite que las contrasenas sean la unica llave y que la
 * recuperacion sea «mira la copia en tu servidor» (ver `deploy/estudio-clave`).
 *
 * Lo que sostiene el diseno: las contrasenas se GENERAN (24 caracteres sobre
 * 58 simbolos, ~140 bits) y `bin/user.js poner` rechaza una contrasena que ya
 * use otra cuenta, asi que dos cuentas no comparten llave. Si aun asi pasara,
 * gana la primera por id, y se dice aqui para que nadie lo busque.
 *
 * SE COMPRUEBAN TODAS, no hasta la primera que cuadra: el tiempo de respuesta
 * no depende de en que posicion esta la cuenta. Con dos o tres cuentas son dos
 * o tres scrypt (~150 ms cada uno), que es un precio de un login y no de una
 * pantalla.
 *
 * Sin base de datos ni servidor: recibe la lista y devuelve la elegida, para
 * poder probarlo con hashes de verdad (`pruebas/acceso.js`).
 */
const { verifyPassword } = require('./auth');

// Un hash con forma valida que no cuadra con nada: sin cuentas se comprueba
// contra el para que «no hay cuentas» tarde lo mismo que «contrasena mal».
const SENUELO = 'scrypt$32768$8$1$00$00';

/**
 * La cuenta cuya contrasena es esta, o null. `cuentas` son filas de `users`
 * (hace falta `password_hash`; el resto viaja tal cual).
 */
async function elegirCuenta(password, cuentas) {
  const lista = Array.isArray(cuentas) ? cuentas : [];
  if (typeof password !== 'string' || !password) return null;
  if (!lista.length) {
    await verifyPassword(password, SENUELO);
    return null;
  }
  let elegida = null;
  for (const cuenta of lista) {
    const cuadra = await verifyPassword(password, (cuenta || {}).password_hash);
    if (cuadra && !elegida) elegida = cuenta;
  }
  return elegida;
}

/**
 * El enlace a la pagina del VPS en el panel de Hostinger, o '' si no se ha
 * configurado el id. El id es un numero (el que sale en la URL del panel y en el
 * nombre de la maquina, `srv<ID>`), y se comprueba antes de meterlo en un
 * enlace: lo que llega del `.env` no tiene por que ser lo que uno espera.
 */
function urlPanelHostinger(id) {
  const limpio = String(id === undefined || id === null ? '' : id).trim();
  if (!/^\d{1,12}$/.test(limpio)) return '';
  return `https://hpanel.hostinger.com/vps/${limpio}/overview`;
}

module.exports = { elegirCuenta, urlPanelHostinger, SENUELO };
