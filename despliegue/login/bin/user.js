#!/usr/bin/env node
'use strict';
/**
 * Gestion de cuentas desde la linea de comandos.
 *
 *   node bin/user.js poner <cuenta> [--password <pw> | --password-stdin]
 *   node bin/user.js create <cuenta> [--password <pw> | --password-stdin] [--name "Nombre"] [--email x] [--role admin]
 *   node bin/user.js passwd <cuenta> [--password <pw> | --password-stdin]
 *   node bin/user.js list
 *   node bin/user.js unlock [cuenta]
 *   node bin/user.js log [n]
 *
 * Si no se pasa contrasena se genera una robusta y se imprime UNA sola vez.
 *
 * `poner` es lo que usa `estudio-clave` desde la consola del servidor: deja la
 * cuenta con esa contrasena, creandola si no existe. `--password-stdin` la lee
 * de la entrada estandar (una linea) para que no pase por la lista de procesos.
 *
 * LA CONTRASENA IDENTIFICA LA CUENTA (ver lib/acceso.js), asi que dos cuentas
 * no pueden compartirla: `poner`, `create` y `passwd` la comprueban contra las
 * demas y se niegan si ya la usa otra.
 */
const { hashPassword, verifyPassword, generatePassword } = require('../lib/auth');
const { stmt, db, limpiarBloqueo } = require('../lib/db');

function parseArgs(argv) {
  const flags = {};
  const positional = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      const key = argv[i].slice(2);
      const val = argv[i + 1] && !argv[i + 1].startsWith('--') ? argv[++i] : 'true';
      flags[key] = val;
    } else {
      positional.push(argv[i]);
    }
  }
  return { flags, positional };
}

/** La primera linea de la entrada estandar, sin el salto. */
function leerStdin() {
  return new Promise((resolve, reject) => {
    let datos = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (trozo) => { datos += trozo; });
    process.stdin.on('end', () => resolve(datos.split(/\r?\n/)[0] || ''));
    process.stdin.on('error', reject);
  });
}

/** La contrasena pedida: la del flag, la de stdin, o una generada. -> {password, generated} */
async function contrasenaPedida(flags) {
  if (flags['password-stdin']) {
    const password = await leerStdin();
    if (!password) throw new Error('No ha llegado ninguna contrasena por la entrada estandar.');
    return { password, generated: false };
  }
  if (flags.password && flags.password !== 'true') {
    return { password: flags.password, generated: false };
  }
  return { password: generatePassword(24), generated: true };
}

/** Se niega si otra cuenta ya usa esa contrasena: la contrasena es la llave, y una llave abre una puerta. */
async function exigirUnica(password, salvoId) {
  for (const otra of stmt.listActive.all()) {
    if (otra.id === salvoId) continue;
    if (await verifyPassword(password, otra.password_hash)) {
      throw new Error(`Esa contrasena ya la usa la cuenta "${otra.username}": elige otra.`);
    }
  }
}

function imprimirContrasena(password, generated) {
  if (generated) {
    console.log(`  Contrasena    : ${password}`);
    console.log('  Guardala ahora: no vuelve a mostrarse.\n');
  } else {
    console.log('  Contrasena    : la que has indicado.\n');
  }
}

async function main() {
  const { flags, positional } = parseArgs(process.argv.slice(2));
  const [command, target, extra] = positional;

  switch (command) {
    case 'create': {
      if (!target) throw new Error('Falta el nombre de la cuenta: user.js create <cuenta>');
      if (stmt.findByUsername.get(target)) throw new Error(`La cuenta "${target}" ya existe.`);

      const { password, generated } = await contrasenaPedida(flags);
      await exigirUnica(password, null);
      stmt.insertUser.run({
        username: target,
        display_name: flags.name || null,
        email: flags.email || null,
        password_hash: await hashPassword(password),
        role: flags.role || 'user',
      });

      console.log(`\n  Cuenta creada: ${target}  (rol: ${flags.role || 'user'})`);
      imprimirContrasena(password, generated);
      break;
    }

    case 'passwd': {
      if (!target) throw new Error('Falta la cuenta: user.js passwd <cuenta>');
      const user = stmt.findByUsername.get(target);
      if (!user) throw new Error(`No existe la cuenta "${target}".`);

      const { password, generated } = await contrasenaPedida(flags);
      await exigirUnica(password, user.id);
      stmt.updatePassword.run(await hashPassword(password), user.id);

      console.log(`\n  Contrasena actualizada para ${user.username}.`);
      if (generated) console.log(`  Nueva contrasena: ${password}\n`);
      else console.log('');
      break;
    }

    // Deja la cuenta con esa contrasena, exista o no. Es lo que llama
    // `estudio-clave`: desde la consola no hay que saber si es la primera vez.
    case 'poner': {
      if (!target) throw new Error('Falta la cuenta: user.js poner <cuenta>');
      const { password, generated } = await contrasenaPedida(flags);
      const user = stmt.findByUsername.get(target);
      await exigirUnica(password, user ? user.id : null);
      const hash = await hashPassword(password);
      if (user) {
        stmt.updatePassword.run(hash, user.id);
        console.log(`\n  Contrasena puesta a la cuenta ${user.username}.`);
      } else {
        stmt.insertUser.run({
          username: target, display_name: flags.name || null, email: flags.email || null,
          password_hash: hash, role: flags.role || 'user',
        });
        console.log(`\n  Cuenta creada: ${target}, con su contrasena puesta.`);
      }
      // Cambiar la llave es la salida natural de un bloqueo por intentos.
      limpiarBloqueo();
      imprimirContrasena(password, generated);
      break;
    }

    // Sin cuenta levanta el bloqueo DEL ACCESO (el que aplica el login desde el
    // 10-09-2026); con cuenta, ademas, el contador viejo de esa fila.
    case 'unlock': {
      limpiarBloqueo();
      if (target) {
        const user = stmt.findByUsername.get(target);
        if (!user) throw new Error(`No existe la cuenta "${target}".`);
        db.prepare('UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?')
          .run(user.id);
        console.log(`Acceso desbloqueado (y el contador de ${user.username}, a cero).`);
      } else {
        console.log('Acceso desbloqueado.');
      }
      break;
    }

    case 'list': {
      const users = stmt.listUsers.all();
      if (!users.length) { console.log('No hay cuentas.'); break; }
      console.log('');
      console.log('  ID  CUENTA            ROL     ACTIVA  ULTIMO ACCESO        CREADA');
      console.log('  --  ----------------  ------  ------  -------------------  -------------------');
      for (const u of users) {
        console.log(
          '  ' + String(u.id).padEnd(4) +
          String(u.username).padEnd(18) +
          String(u.role).padEnd(8) +
          (u.is_active ? 'si' : 'no').padEnd(8) +
          String(u.last_login_at || '-').padEnd(21) +
          String(u.created_at)
        );
      }
      console.log('');
      break;
    }

    case 'log': {
      const limit = Number(target || extra || 20);
      const events = stmt.recentEvents.all(Number.isFinite(limit) ? limit : 20);
      console.log('');
      for (const e of events) {
        console.log(
          `  ${e.at}  ${e.success ? 'OK   ' : 'FALLO'}  ` +
          `${String(e.username || '-').padEnd(16)} ${String(e.ip || '-').padEnd(16)} ${e.reason || ''}`
        );
      }
      console.log('');
      break;
    }

    default:
      console.log(`
Gestion de cuentas de Studio Videos IA

  node bin/user.js poner <cuenta> [--password <pw> | --password-stdin]
  node bin/user.js create <cuenta> [--password <pw> | --password-stdin] [--name "Nombre"] [--email <mail>] [--role admin|user]
  node bin/user.js passwd <cuenta> [--password <pw> | --password-stdin]
  node bin/user.js unlock [cuenta]
  node bin/user.js list
  node bin/user.js log [n]

Sin contrasena se genera una robusta de 24 caracteres. El login no pide
usuario: la contrasena dice de que cuenta es, asi que no puede repetirse.
Desde la consola del servidor, lo comodo es \`estudio-clave\`.
`);
      process.exitCode = command ? 1 : 0;
  }
}

main().catch((err) => {
  console.error(`\n  Error: ${err.message}\n`);
  process.exit(1);
});
