'use strict';
/**
 * El acceso sin usuario: `elegirCuenta` y el enlace de recuperacion.
 *
 *     node app/pruebas/acceso.js
 *
 * Con hashes scrypt DE VERDAD (los mismos parametros que produccion, ~150 ms
 * cada uno): lo que se comprueba es que la contrasena elige la cuenta que le
 * toca, que una que no cuadra con ninguna no elige nada, y que sin cuentas no
 * revienta. Sin red, sin base de datos y sin servidor.
 */
process.env.SESSION_SECRET = process.env.SESSION_SECRET
  || 'prueba'.repeat(8);   // 48 caracteres: config exige 32 como minimo

const { hashPassword } = require('../lib/auth');
const { elegirCuenta, urlPanelHostinger } = require('../lib/acceso');

let fallos = 0;
function igual(que, dio, esperaba) {
  const ok = dio === esperaba;
  if (!ok) fallos += 1;
  console.log(`${ok ? '  ok  ' : ' FALLO'} ${que}  ->  ${JSON.stringify(dio)}`
              + (ok ? '' : `  (esperaba ${JSON.stringify(esperaba)})`));
}

(async () => {
  console.log('-- la contrasena elige la cuenta');
  const cuentas = [
    { id: 1, username: 'adrian', password_hash: await hashPassword('llave-de-adrian-123') },
    { id: 2, username: 'ramon',  password_hash: await hashPassword('llave-de-ramon-456') },
  ];
  igual('la de adrian', ((await elegirCuenta('llave-de-adrian-123', cuentas)) || {}).username, 'adrian');
  igual('la de ramon',  ((await elegirCuenta('llave-de-ramon-456', cuentas)) || {}).username, 'ramon');
  igual('una que no es de nadie', await elegirCuenta('otra-cosa-distinta-789', cuentas), null);
  igual('vacia', await elegirCuenta('', cuentas), null);
  igual('casi (un caracter menos)', await elegirCuenta('llave-de-adrian-12', cuentas), null);

  console.log('-- sin cuentas, o con filas raras, no revienta');
  igual('sin cuentas', await elegirCuenta('llave-de-adrian-123', []), null);
  igual('lista nula', await elegirCuenta('llave-de-adrian-123', null), null);
  igual('fila sin hash', await elegirCuenta('x'.repeat(12), [{ id: 3, username: 'roto' }]), null);
  igual('hash de otro formato',
        await elegirCuenta('x'.repeat(12), [{ id: 4, username: 'viejo', password_hash: 'bcrypt$...' }]),
        null);

  console.log('-- si dos cuentas compartieran llave, gana la primera (user.js lo impide)');
  const repetido = await hashPassword('la-misma-llave-000');
  const dobles = [
    { id: 7, username: 'primera', password_hash: repetido },
    { id: 8, username: 'segunda', password_hash: repetido },
  ];
  igual('la primera por orden', ((await elegirCuenta('la-misma-llave-000', dobles)) || {}).username, 'primera');

  console.log('-- el enlace al panel de Hostinger');
  igual('id normal', urlPanelHostinger('1944562'), 'https://hpanel.hostinger.com/vps/1944562/overview');
  igual('id como numero', urlPanelHostinger(1944562), 'https://hpanel.hostinger.com/vps/1944562/overview');
  igual('con espacios', urlPanelHostinger(' 1944562 '), 'https://hpanel.hostinger.com/vps/1944562/overview');
  igual('vacio', urlPanelHostinger(''), '');
  igual('sin configurar', urlPanelHostinger(undefined), '');
  igual('con letras', urlPanelHostinger('1944562/../otra'), '');
  igual('demasiado largo', urlPanelHostinger('1'.repeat(13)), '');

  console.log(fallos ? `${fallos} FALLOS` : 'las 17 comprobaciones, bien');
  process.exit(fallos ? 1 : 0);
})().catch((err) => {
  console.error('FALLO inesperado:', err);
  process.exit(1);
});
