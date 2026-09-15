'use strict';
/**
 * `destinoTrasLogin`: a donde se vuelve tras entrar, y lo que NO se acepta.
 *
 *     node app/pruebas/destino.js
 *
 * Es la pieza que sostiene que el login sirva a las DOS versiones del estudio
 * (la 1 en `/`, la 2 en `/v2/`) sin convertirse en una redireccion abierta: el
 * destino lo dice el cliente, asi que aqui se comprueba que solo pasen rutas de
 * este sitio. Es la mitad del arreglo, no un adorno -- ver el apartado «El
 * login es de las DOS versiones» del CLAUDE.md.
 *
 * Sin red, sin base de datos y sin servidor: `config` solo pide un secreto para
 * poder cargarse, y aqui se le da uno de mentira.
 */
process.env.SESSION_SECRET = process.env.SESSION_SECRET
  || 'prueba'.repeat(8);   // 48 caracteres: config exige 32 como minimo

const { destinoTrasLogin, loginDe } = require('../lib/middleware');

let fallos = 0;
function igual(que, dio, esperaba) {
  const ok = dio === esperaba;
  if (!ok) fallos += 1;
  console.log(`${ok ? '  ok  ' : ' FALLO'} ${que}  ->  ${JSON.stringify(dio)}`
              + (ok ? '' : `  (esperaba ${JSON.stringify(esperaba)})`));
}

console.log('-- lo que tiene que pasar');
igual("'/v2/'",              destinoTrasLogin('/v2/', '/'), '/v2/');
igual("'/studio'",           destinoTrasLogin('/studio', '/'), '/studio');
igual("'/'",                 destinoTrasLogin('/', '/v2/'), '/');
igual("'/v2/?x=1'",          destinoTrasLogin('/v2/?x=1', '/'), '/v2/?x=1');
igual("'/v2/#proyecto/oro'", destinoTrasLogin('/v2/#proyecto/oro', '/'), '/v2/#proyecto/oro');

console.log('-- lo que no, y vuelve al respaldo (la puerta por la que se entro)');
igual('vacio',            destinoTrasLogin('', '/v2/'), '/v2/');
igual('null',             destinoTrasLogin(null, '/'), '/');
igual('otro host //',     destinoTrasLogin('//otro.com/', '/'), '/');
igual('otro host /\\',    destinoTrasLogin('/\\otro.com/', '/'), '/');
igual('absoluta http',    destinoTrasLogin('https://otro.com/', '/'), '/');
igual('sin barra',        destinoTrasLogin('otro.com', '/'), '/');
igual('javascript:',      destinoTrasLogin('javascript:alert(1)', '/'), '/');
igual('con espacio',      destinoTrasLogin('/v2/ x', '/'), '/');
igual('con comilla',      destinoTrasLogin('/v2/"x', '/'), '/');
igual('el propio login',  destinoTrasLogin('/login', '/v2/'), '/v2/');
igual('el login de la 2', destinoTrasLogin('/v2/login?next=/', '/'), '/');
igual('una llamada api',  destinoTrasLogin('/v2/api/proyectos', '/'), '/');
igual('salto de linea',   destinoTrasLogin('/v2/\nSet-Cookie: x', '/'), '/');

console.log('-- que login le toca a cada direccion');
igual("'/v2/'",      loginDe('/v2/'), '/v2/login');
igual("'/v2'",       loginDe('/v2'), '/v2/login');
igual("'/v2/api/x'", loginDe('/v2/api/x'), '/v2/login');
igual("'/'",         loginDe('/'), '/login');
igual("'/studio'",   loginDe('/studio'), '/login');
igual("'/v2loco'",   loginDe('/v2loco'), '/login');

console.log(fallos ? `${fallos} FALLOS` : 'las 24 comprobaciones, bien');
process.exit(fallos ? 1 : 0);
