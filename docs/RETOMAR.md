# RETOMAR — estado al cerrar el 10-09-2026

**Lo último (10-09, tarde): la guía de inicio y el asistente**, desplegados en
el VPS (ver §7). Las 23 suites en verde y las herramientas de análisis limpias.

**Después (10-09, noche): la parada «Encargo» en la barra de abajo**, desplegada
en `/opt/studio-v2/app` (`app.js`, `estilo.css`, `app.py`; `studio-v2@adrian`
reiniciado; `studio-v2@ramon` nunca se aprovisionó y sigue parado). Con un vídeo
abierto enseña lo que se le pidió al redactor
—nombre, duración, formato, material, indicaciones, llamadas a la acción— leído
de los params de `ingesta`/`brief`/`guion`, editable con autoguardado, y el pie
ofrece «Regenerar el guion» (tanda `guion`, modo `pendientes`). Sólo se escribe
la clave que cambia frente a lo guardado: escribir un defecto movería firmas
(ver `vistaEncargoVideoLight` en `web/app.js`). El botón «Guion» ya no cae en el
formulario de crear un vídeo nuevo cuando no hay guion.

**Y en el repo del login (`studio-videos-ia`), desplegado el mismo día:** el
acceso pasa a pedir solo la contraseña (sin usuario; la contraseña identifica
la cuenta), con la recuperación desde la consola web del panel de Hostinger y el
comando `estudio-clave`. Todo en «El acceso: una contraseña, sin usuario» de su
`CLAUDE.md`. De este lado no cambia nada: `/api/me` y `/api/logout` siguen igual.

Para retomar desde un chat sin contexto: este fichero + `CLAUDE.md` (las reglas
del producto) + `C:\claude_server_workspace\youtube_adrian_saenz\studio-videos-ia\CLAUDE.md`
(el runbook del VPS: claves, `scripts/vps.sh`, `deploy.sh`, y el apartado
«AS Video Studio (v2), en `/v2/`»).

---

## 1. Qué es esto

**AS Video Studio** = una segunda versión, más simple, del Estudio de vídeo de
`C:\IA\estudio`. Fork independiente, NO una rama: código, datos, venv, motores,
puerto y servicio propios.

| | v1 (la de siempre) | v2 (esto) |
|---|---|---|
| local | `C:\IA\estudio` | `C:\claude_server_workspace\youtube_adrian_saenz\as-video-studio` |
| URL | `https://studiovideo.cloud/` | `https://studiovideo.cloud/v2/` |
| VPS | `/opt/studio/app`, `studio-estudio@<cuenta>`, :8010/:8011 | `/opt/studio-v2/app`, `studio-v2@<cuenta>`, :8110/:8111 |

**La v1 sigue viva y no se toca.** Lo único compartido: el login de delante y
las fuentes tipográficas.

### Lo que se quitó respecto de v1 (y no es un olvido)

yt-dlp y todo el material por vídeo (el material es TEXTO + indicaciones), «mis
enlaces», el monitor, el botón Light, «volver a leer estado», «ideas y
referencias», la bitácora, el dictado por voz, los personajes fijos del canal
(el **reparto** por vídeo SÍ está), el producto de las CTA y las integraciones
ARGOS ATLAS. Estilo gráfico = sólo imágenes + indicaciones; tono = sólo texto.
Las **CTA se configuran vídeo por vídeo, nunca en el preset**. Config se queda,
con **una sola clave de OpenAI**.

Ver «Lo que NO hay, y no es un olvido» en `CLAUDE.md`.

### Invariantes que costaron trabajo

- **El formato visual de v1 se respeta**: nomenclaturas, tarjetas y pasos igual
  que el original, porque esto sale en un vídeo explicativo.
- **Cero datos personales, cero claves, cero referencias a proyectos
  anteriores** en el código.
- El grafo de 8 pasos intacto: ingesta → brief → guion → voz → revision_audio →
  assets → callouts → render.

---

## 2. Lo que se hizo, por fases

1. **El fork** (`web/app.js`: 20.338 → 9.878 líneas). Herramientas nuevas en
   `herramientas/`: `sin_llamar_js.py`, `alcanzables_js.py`, `css_sin_usar.py`,
   `atributos_py.py`.
2. **Desplegado en `/v2/`** conviviendo con v1: `deploy/studio-v2@.service`,
   el `map $studio_v2_port` y el `location /v2/` de nginx.
3. **Migrados los 2 estilos y el «Vídeo sobre el oro»** (`beats_2`, 55 GB, 302
   planos) con `herramientas/traer_de_v1.py` + `mudar_proyecto.py --sellar-todo`.
   129.047 rutas mudadas, 18.424 firmas re-selladas, 8 pasos `listo`, **0
   obsoletas de 312×3**.
4. **El login pasó a ser de las dos versiones** (ver §4).

Los tres primeros están documentados con sus comandos en el runbook del VPS
(apartado «AS Video Studio (v2)»). El cuarto, en «El login es de las DOS
versiones».

---

## 3. Los fallos que se encontraron y cómo se arreglaron

Lo que hay que leer antes de volver a tocar algo de aquí. Los que empiezan por
**[v1]** ya venían del original.

### Del tijeretazo al front

- **`sin_comentarios` borraba el contenido de `${...}`** y `alcanzables_js`
  daba por muertas 4 funciones vivas (`textoDeCoste`, `nombreIdioma`,
  `textoDeMando`, `ejemploPreset`). Lo cazó `prueba_api.py`. El tokenizador
  ahora **conserva el código de los placeholders**.
- **`alcanzables_js._cierre` contaba TODOS los tipos de corchete**, así que un
  literal de expresión regular con llaves desincronizaba los tramos y `--borrar`
  partió el fichero en dos. Ahora cuenta sólo la pareja que le toca y **lanza si
  dos tramos se solapan**.
- **[v1] `refrescarCosteLight` estaba dos veces.** En JavaScript la segunda se
  lleva la primera por delante sin un solo error: el coste que se enseña ANTES
  de generar no se dibujaba desde el día que se escribió. Se renombró la
  ensombrecida y `sin_llamar_js.py` tiene ahora `repetidas()`.

### Del camino de generación

- **`/api/voces` daba un 500 opaco sin clave de Cartesia**: `SystemExit` no es
  `Exception`. `p4_voz._hay_clave()` pregunta al motor tragándose el `SystemExit`
  y `listar_voces` sirve el catálogo cacheado o el base.
- **[v1] La receta se leía de dos formas distintas**: la pantalla con
  `.get(tid, True)` y el lanzador con `.items() if valor`. Una tarea ausente de
  la receta **salía encendida y no se ejecutaba**. Única fuente de verdad:
  `recetas.puestas_de`, y los 4 sitios de `app.py` la usan.
- **`p6_assets._palabras_narracion`** ahora calcula los muros con
  `tramos_de_bloque` + `_bloque_en` cuando la meta trae el formato actual
  (`bloques` + `palabras` planas). Fuera `_tramo_de_planos`, `_entra_en`,
  `_menciones_seguidas` y el origen `"mencion"`.

### De las pruebas

- **`prueba_piezas` hacía llamadas de pago de verdad**: la firma del caché
  copiada a mano se olvidaba de `tamano`. Ahora el caché se rellena por el código
  real con un motor falso instalado desde la primera línea, y `_prohibir_pagar()`
  se arma en `main()` y se re-arma en el `finally` de
  `prueba_recarga_de_motores`.
- **`prueba_pasos_visuales` leía de una carpeta borrada.** Se hizo
  autosuficiente (`BLOQUES_LOCUCION`, `locucion_falsa()`, `_lamina()`): 229
  comprobaciones. La cartela se movió a S003 porque en S005 no se narraba
  «Cuatro mil»; hay un comentario avisando de que editar `BLOQUES_LOCUCION` la
  mueve. Las láminas llevan grano para no disparar el aviso de tamaño de
  `medios`.
- **`prueba_presets_light` fallaba 3 comprobaciones de frase**: las frases parten
  línea en el prompt. Se comparan con `plano = " ".join(descrito.split())`.
- **`prueba_cache_por_clave`** reventó al añadir el guardián `_hay_clave`: se
  sustituye también en la prueba.
- **`RUTA_MAPA` tenía un `dirname` de más** (tres) y toda región salía «no
  dibujable». Ahora honra `ESTUDIO_MOTORES`.

### De la mudanza de v1 a v2

- **Un proyecto sin normalizar abre `listo`, no obsoleto** — lo predije al revés
  y lo corrigió la medida: `_params_globales` hashea los params **CRUDOS**
  guardados, no la salida de `_normalizar` del paso. O sea que **normalizar es
  justo lo que mueve las firmas**, y de ahí `--sellar-todo`.
- **Los 872 huecos del transcript eran todos de 0,01 s** (los subtítulos
  automáticos de YouTube no traen silencios ni puntuación) → un párrafo de 6.098
  palabras. De ahí el respaldo `PALABRAS_PARRAFO = 90` → 66 párrafos.
- La ingesta queda **reproducible desde sus params**: el shim `_EnLaVersion` hace
  que `p1_ingesta.ejecutar` escriba dentro de la carpeta de versión que ya
  existe.

### Del login (§4)

- **`@al_login` perdía el origen**: un `/login` pelado para las dos versiones.
- **El POST contestaba `redirect: '/'` a pelo** y `redirectIfAuthenticated`
  mandaba siempre a `/studio`.

### De la sesión de trabajo, no del código

- **Los heredoc de Bash destrozan `\n`, `\t`, `\a` y las triples comillas.** Uno
  metió un carácter BEL dentro de una ruta de `CLAUDE.md` (se vio con `cat -A`).
  **Para texto delicado, usar las herramientas Write/Edit**, no heredoc. Y en un
  parche de Python, la cadena de reemplazo va en **raw string** si lleva
  contrabarras: `[\\\s"'<>]` en un `"""..."""` normal sale como `[\\s"'<>]` y el
  regex pasa a rechazar la letra `s`.
- **Un `nginx -t` en la misma orden que el `reload` puede no ver el cambio**:
  comprobar en una segunda llamada.

---

## 4. El login: se vuelve por donde se entró (lo último, 10-09)

Escribir la URL de la v2 llevaba al login y, tras entrar, **a la v1**. Cada
versión tiene ahora su puerta, con la misma pantalla y la misma sesión (la cookie
va con `path=/`):

| | v1 | v2 |
|---|---|---|
| sin sesión, nginx manda a | `@al_login` → `/login` | `@al_login_v2` → `/v2/login` |
| al entrar se vuelve a | `/` | `/v2/` |

Vive en el repo del login (`studio-videos-ia`): `location = /v2/login` pasa a
Node **sin recortar el prefijo** (es lo único de `/v2/` que no se recorta: el
prefijo es lo que le dice a dónde devolver), `login.js` manda `next` y
`destinoTrasLogin` (en `app/lib/middleware.js`) lo **valida** — sin eso sería
una redirección abierta. Prueba: `node app/pruebas/destino.js` (24
comprobaciones).

**De este lado** sólo cambió una línea: al salir, `salirDeStudio` va a
`${BASE}/login` y no a lo que contesta `/api/logout` (que dice `/login` porque
no sabe por cuál de las dos versiones se le llama).

---

## 5. Trabajo del día a día

```powershell
powershell -NoProfile -File pruebas.ps1        # las 22 suites
```

El intérprete con fastapi/requests/PIL es `C:\IA\venvs\cartoon\Scripts\python.exe`
(el `python` del PATH no los tiene):

```bash
/c/IA/venvs/cartoon/Scripts/python.exe prueba_api.py     # 743 comprobaciones
python herramientas/alcanzables_js.py                    # 406/406 vivas
python herramientas/sin_llamar_js.py                     # 0 sin llamar
```

Desplegar (el `tar | ssh` completo está en el runbook del VPS). Un fichero
suelto del front:

```bash
cd /c/claude_server_workspace/youtube_adrian_saenz/studio-videos-ia
scp -i secret/studio-videos-ia_vps -o IdentitiesOnly=yes ../as-video-studio/web/app.js root@la IP del VPS:/opt/studio-v2/app/web/app.js
./scripts/vps.sh "chown studio:studio /opt/studio-v2/app/web/app.js && systemctl restart studio-v2@adrian"
```

`web/app.js` se sirve con `?v=<sello>` calculado del propio fichero: **aquí no
hay ningún número que subir a mano** (eso es sólo de los HTML del login).

---

## 6. Lo que queda abierto

- **Confirmarlo en el navegador con la contraseña**: entrar en
  `https://studiovideo.cloud/v2/` y ver que se aterriza en la v2. Es lo único
  que no se pudo comprobar desde la sesión (no tengo la contraseña); todo lo
  demás se midió, incluido el login completo contra una instancia de usar y
  tirar del mismo código.
- **63 nombres que `css_sin_usar.py` da por muertos** en `estilo.css`. Hay falsos
  positivos (clases que se construyen con plantillas, `cols2`/`cols3`…), así que
  **no se pasó `--borrar`** a ciegas. Si se limpia, de una en una y mirando.
- `banco/atlas` y `banco/commons` no existen aquí: eran de las menciones del mapa
  y de las referencias reales.
- La **CTA de los vídeos nuevos** hay que escribirla una vez: no viaja en los
  presets a propósito.

---

## 7. La guía de inicio y el asistente (10-09, tarde; desplegado)

Dos piezas nuevas, independientes entre sí:

- **La guía de inicio.** Al entrar por primera vez, seis tarjetas piden las
  claves de una en una —Claude (login, no clave), OpenAI, Cartesia, Jamendo y
  FreeSound— con los pasos y el enlace de cada sitio. Guarda en `/api/claves`,
  lo mismo que Configuración, y el login de Claude es el mismo `pasoDelAcceso`.
  La marca `onboarding_visto` es un ajuste del servidor (`pasos/ajustes.py`);
  «Saltar por ahora» también la pone. Se reabre desde Configuración («Volver a
  ver la guía de inicio»). Todo en `web/app.js` a partir de `abrirInicio`.
- **El asistente.** Burbuja abajo a la derecha (encima de la barra de abajo, no
  en la esquina: en móvil la esquina es la parada «Vídeo»). `pasos/asistente.py`
  + `/api/asistente`, `/api/asistente/foto` y `/api/asistente/charlas/...` en
  `app.py`. Contesta el CLI de Claude con la cuenta del Estudio, con Read/Grep/
  Glob sobre el repo, `--add-dir` a la carpeta de proyectos, la documentación en
  el primer turno y `--resume` en los siguientes; delante de cada pregunta va la
  foto del estado (`_foto_para_asistente`) y lo que la pantalla tiene a la vista
  (`ERRORES`). Sin sesión de Claude, la burbuja lo dice y manda a la tarjeta de
  Claude de la guía. Las reglas están en `CLAUDE.md` («El asistente y la guía de
  inicio»).

Medido en local con la sesión por defecto del CLI: «¿qué me falta por
configurar?» contesta en 9,6 s con lo que de verdad falta; pedirle la clave de
OpenAI entera la niega (y por debajo, `Read` sobre `secretos/` devuelve «denied
by your permission settings», comprobado con haiku a pelo).

Pruebas: `pasos/prueba_asistente.py` (nueva, 60 comprobaciones con el CLI
sustituido por un doble) y tres apartados más en `prueba_api.py` (790 en total),
que corre el asistente en modo simulado. `docs/API.md` regenerado: 144 endpoints.

### Fallos y trampas de esta sesión

- **`pintarConfig()` reemplazado en bloque por `repintarClaves()`** se llevó
  también la llamada de DENTRO de `repintarClaves` y la dejó recursiva: nada se
  pintaba y `alcanzables_js` daba por muerta la pantalla de Configuración
  entera (11 funciones). Un reemplazo global sobre un nombre que se define en la
  misma tanda se revisa a mano.
- **Un acento grave dentro de una regex de `app.js`** (`/^\s*```/` y
  `` /(`[^`]+`|...)/ ``) hace que `huerfanas_js` y `sin_llamar_js` se traguen el
  resto del fichero como plantilla. Se escriben `\x60`. Y **el heredoc de Bash
  convierte `\\x60` en el acento grave literal** (otra vez lo de §3): el parche
  se hizo con Edit.
- **`_asistente_listo` decía «sin sesión» con una cuenta añadida y nunca
  logueada**, mientras `cli_claude.cuentas()` habría contestado con la sesión
  por defecto: el asistente estaba cerrado justo en la máquina donde el Estudio
  generaba. Ahora mira `entrada` como el motor.
- **`pruebas.ps1` desde Bash falla por la política de ejecución**: hay que
  pasar `-ExecutionPolicy Bypass` (desde una consola de PowerShell normal no
  hace falta).
- **El puerto 8020 está ocupado en esta máquina por un `pythonw.exe`** (otro
  Estudio); para abrir la interfaz en desarrollo se dejó `.claude/launch.json`
  en el 8021.
- `huerfanas_js` ya traía dos sospechosas antes de tocar nada (`async` y
  `fallar`); no son llamadas y no se han tocado.

### Lo que queda

- **Desplegado el 10-09 a las 12:28 UTC** con el `tar | ssh` del runbook (más
  `--exclude=secretos --exclude=.claude`, que el runbook ya lleva). En el VPS
  `/api/asistente` contesta `listo` con la cuenta de adrian (plan max) y la foto
  sale sin claves. La primera pregunta de verdad **no se pudo ver contestada:
  la cuenta tiene el cupo semanal agotado hasta el 14-09 a las 02:00 UTC**, y el
  asistente lo dice tal cual en el turno (`LimiteAgotado`). Que el CLI de allí
  (2.1.251) aceptó `--allowedTools`, `--add-dir` y los vetos de `Read(...)` se
  sabe porque el error es el del cupo y no el de una opción desconocida. Queda
  pendiente, en cuanto se renueve: una pregunta real desde `/v2/` y pedirle
  `secretos/` para ver la negativa del permiso también allí.
- La guía de inicio saldrá UNA vez a adrian en el VPS (`onboarding_visto` no
  existía allí): con las claves ya puestas, cada tarjeta dice «puesta» y se
  pasa con «Empezar» o «Saltar por ahora».
- Decidir si el asistente merece su propia línea en el medidor de coste: hoy
  consume la suscripción del CLI y no se anota en `coste_global.jsonl`.

---

## 8. La salud de las cuentas, las claves probadas y las manos del asistente (10-09, noche)

Lo que se vio en el VPS: la cuenta de Claude tenía el cupo semanal agotado y
la pantalla la pintaba en verde («con sesión»), porque lo único que sabía
preguntar era `claude auth status`. Y el asistente decía «no puedo probar las
claves, no tengo acceso». Tres piezas:

- **`pasos/salud_cli.py`**: lo último que pasó al hablar con cada cuenta (ok,
  cupo, sesión, tiempo, error), escrito por `cli_claude._una_pasada` en TODA
  llamada y por «Probar» (haiku, una palabra, 2,8 s si no hay cupo). En
  `<secretos>/salud_cli.json`. La burbuja, Configuración y la guía lo enseñan
  al lado de la sesión, y `/api/asistente` sólo dice `listo` con una cuenta
  con sesión y sin fallo apuntado; al abrir la burbuja se prueba sola una vez
  si no se sabe nada. Rutas: `POST /api/claves/cli/{cid}/probar`,
  `POST /api/asistente/probar`.
- **`pasos/comprobar_claves.py`** y `POST /api/claves/probar`: cada clave
  contra su servicio (OpenAI `/v1/models`, Cartesia `/voices`, Jamendo y
  FreeSound una búsqueda), sin gastar. Botón «Probar todas las claves» arriba
  de Configuración y en la última tarjeta de la guía.
- **`pasos/mcp_estudio.py`**: un servidor MCP escrito a mano (JSON-RPC por
  stdio, cinco métodos) con `probar_claves`, `probar_claude`,
  `estado_estudio`, `trabajos`, `ficha_paso`, `bitacora`, `cancelar_trabajo`
  y `salud_servicio`. El asistente lo carga con `--mcp-config <fichero
  temporal>` (el JSON no sobrevive a claude.cmd como argumento) y las
  herramientas van pre-autorizadas en `--allowedTools`. Cada una habla con la
  API en `ESTUDIO_API` (lo pone `app.py` con su puerto). Medido en local:
  «¿puedes probar mis claves?» → usa `probar_claves` y contesta con el
  resultado real en 10 s.

Y la guía: **una sola cuenta de Claude**, el acceso arranca solo al abrir la
tarjeta (enlace grande, código que se envía al pegarlo) y, entrado, se prueba
solo. Las cuentas de respaldo siguen en Configuración.

Pruebas: `pasos/prueba_salud_cli.py` (nueva) y un apartado más en
`prueba_api.py` (805). `docs/API.md`: 147 endpoints.

Dos cosas más de la misma tarde: **el feedback de cada imagen admite
referencias adjuntas**, con la misma zona que el repaso del vídeo montado
(`zonaDeImagenes` en `app.js`, una para las dos pantallas); van en la nota
(`imagenes`) y el corrector las adjunta al generador como `[adjunta]`
(`p6_assets._adjuntos_de_la_nota`, que ya lo hacía para las del vídeo). Y el
botón «Generar las diapositivas» se llama «Generar imágenes».

### Trampas de esta parte

- **Las suites que doblan `subprocess.Popen`** (`prueba_ajustes`, `prueba_p3`,
  `prueba_coste_capturas`) escribían la salud de sus dobles en el `secretos/`
  de verdad: `salud_cli.fichero()` mira `ESTUDIO_SECRETOS` en cada llamada y
  esas tres suites lo redirigen a una carpeta temporal antes de nada.
- **Un heredoc de Bash con un `\\` a final de línea** (continuación de Python)
  rompe el parche entero («unexpected EOF while looking for matching»). Los
  parches largos van en un fichero escrito con Write y se ejecutan con Python.
- El `--mcp-config` va como FICHERO en `%TEMP%/estudio_mcp_<pid>.json`,
  reescrito en cada turno porque lleva el proyecto abierto.
