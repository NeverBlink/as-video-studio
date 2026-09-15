# Cómo queda montado, y por qué así

Esto es lo que hace `instalar.sh` y las razones de lo que no es evidente. Para
instalarlo no hace falta leer nada de aquí: está en [INSTALAR.md](../INSTALAR.md).

## El reparto

```
nginx (443, con el certificado de Let's Encrypt)
├── /login /api/{csrf,login,logout,me,health} /css/ /js/ /assets/  →  el acceso (Node, :3000)
├── = /_auth   (interna, en CADA petición)                         →  el acceso :3000/api/_auth
└── /  (todo lo demás)  → auth_request → si hay sesión             →  el estudio (Python, :8110)
                                       → si no la hay              →  302 a /login
```

**El estudio no sabe lo que es un usuario, y no se le enseñó a propósito.** No
hay cuentas, ni sesiones, ni permisos: sirve a quien llame. El aislamiento va
por delante, en una pieza aparte. Enseñarle al código lo que es un usuario sería
un concepto nuevo en las ocho fases, en las firmas y en cada ruta, para resolver
algo que un proxy resuelve sin tocar nada.

La consecuencia práctica: **sin ese proxy delante, el estudio abierto a internet
es cualquiera gastando tus claves**. Por eso el instalador monta las dos cosas a
la vez y el cortafuegos sólo deja entrar por el 80 y el 443.

## Qué queda en el disco

```
/opt/as-video-studio/
├── app/            el código (se reemplaza entero al actualizar)
├── venv/           Python y sus librerías
├── login/          el acceso (Node) + su .env y su base de datos
├── datos/          TUS COSAS: proyectos, estilos, claves, gasto, ajustes
│   ├── entorno     qué variable manda cada cosa a su sitio
│   └── secretos/   las claves de API y las sesiones del CLI de Claude (chmod 700)
└── home/           el HOME del servicio — lo necesita el navegador
```

**Los datos viven fuera del código a propósito**: `asvs actualizar` borra y
reemplaza `app/` entera y no toca `datos/`. Si estuvieran dentro, actualizar
sería un riesgo cada vez.

Y se reemplaza con `rsync --delete`, no con un `tar` por encima. Un tar
*superpone*: un fichero que llegó ahí por accidente no se va nunca, y acabas con
basura acumulada dentro del árbol de código sin que ninguna actualización la
limpie. Ha pasado, y por eso está escrito aquí.

## Las cuatro cosas que no son obvias

### 1. Las fuentes: se mide con una y se dibuja con otra

El estudio **mide** el texto con Python (PIL) y lo **dibuja** con el navegador.
Si no son el mismo fichero, la cuenta sale bien y el número mal: las cajas de
los rótulos se quedan cortas y el texto se sale. **No da ningún error**; se ve
mirando un PNG.

El instalador fuerza el invariante en dos sitios a la vez:

- copia (por enlace) las fuentes a `/usr/local/share/fonts/estudio` con los
  nombres que espera el código (`verdana.ttf`, `verdanab.ttf`, …), que es de
  donde las lee PIL;
- y escribe `/etc/fonts/conf.d/61-as-video-studio.conf` con un alias por familia
  **calculado de lo que haya quedado enlazado**, para que el navegador resuelva
  al mismo fichero. Calculado y no escrito a mano: a mano, el día que cambia un
  enlace los dos lados se separan en silencio.

Las de Microsoft (Verdana, Georgia, Arial) son las que se usaron para medir y se
instalan del paquete oficial de Ubuntu, que las descarga con su licencia —
**no viajan dentro de este repositorio**. Si esa descarga falla, se usan las
libres de DejaVu: los textos se ven con otra letra, pero **cuadrados**, que es lo
que importa. El instalador lo dice cuando pasa, y `asvs estado` lo comprueba.

### 2. El navegador necesita `--no-sandbox`, y no es dejadez

Ubuntu 24.04 restringe por AppArmor los espacios de nombres sin privilegios, y
sin ese parámetro el navegador **no arranca** bajo el servicio; falla con un
error de *zygote* que no menciona AppArmor por ningún lado. El aislamiento no se
pierde: el proceso corre como un usuario sin permisos, con `PrivateTmp` y sin
capacidades. Por eso se llama a `/usr/local/bin/estudio-edge` y no al navegador
directamente.

`HOME` también tiene que existir y ser del usuario del servicio, o el navegador
muere con «cannot create directory» — otro error que no dice qué le falta.

### 3. Sin HTTPS, la cookie de sesión no puede ser segura

La cookie del acceso va marcada como `secure`. Por HTTP el navegador la tira, y
entonces **se entra bien y se vuelve a la pantalla de acceso**, sin un solo
error a la vista. Si el certificado no se puede sacar (porque el nombre todavía
no apunta a la máquina), el instalador baja esa marca para que el sitio funcione
y lo dice; `asvs https` saca el certificado y la vuelve a subir.

Lo mismo con `X-Forwarded-Proto` en el proxy: sin esa cabecera, el acceso cree
que la conexión vino por HTTP aunque venga por HTTPS, y pasa exactamente igual.

### 4. Un dominio nuevo son TRES sitios

`server_name` de nginx, el certificado (`certbot --expand`) y **`APP_ORIGENES`
del `.env` del acceso**. Si falta el último, el navegador entra sin avisos pero
el login contesta «Origen no permitido»: la comprobación anti-CSRF compara
contra esa lista, y a propósito **no** contra el `Host` de la petición — ese lo
pone quien llama.

## Por qué el nombre del propio servidor vale como dominio

En un VPS de Hostinger, `srvXXXXXXX.hstgr.cloud` ya resuelve a la máquina desde
el primer minuto. O sea que hay certificado de verdad **sin comprar ningún
dominio**, que es lo que permite que la instalación termine con HTTPS sin
preguntar nada. Si luego se pone un dominio propio, se cambia con
`ASVS_DOMINIO=...` y se vuelve a lanzar el instalador (o `asvs https`), y hay
que acordarse de los tres sitios del punto 4.

## Los ficheros de esta carpeta

| Fichero | Qué es |
|---|---|
| `as-video-studio.service` | el estudio, como servicio del sistema |
| `as-video-login.service` | el acceso, como servicio del sistema |
| `nginx-sitio.conf` | el sitio (se le sustituye `__DOMINIO__`) |
| `asvs-proxy.conf` | cabeceras de proxy comunes |
| `asvs-proxy-largo.conf` | lo mismo, con 3600 s de espera: un render pasa de la hora |
| `estudio-edge` | el envoltorio del navegador |
| `estudio-clave` | ver y cambiar la contraseña de acceso, desde la consola |
| `asvs` | el mando: estado, registro, actualizar, https |
| `login/` | la aplicación del acceso (Node) |

## Probar un cambio antes de publicarlo

`instalar.sh` mira si está dentro del árbol (junto a `app.py`). Si lo está,
instala **lo que tiene al lado** en vez de bajar nada de GitHub:

```bash
# desde tu máquina, a un VPS limpio
scp -r . root@IP:/root/asvs-prueba
ssh root@IP "cd /root/asvs-prueba && bash instalar.sh"
```

## Lo único del código que la aplicación reescribe

`motores/reglas/reglas.json` — las reglas de dibujo que el destilador aprende de
tu feedback. Viaja una por defecto en el repositorio, pero **el instalador y
`asvs actualizar` la excluyen si ya existe**: si no, cada actualización borraría
lo que ha aprendido tu estudio, en silencio y sin forma de recuperarlo.
