# AS Video Studio — lo que hay que saber antes de tocarlo

Lee primero [README.md](README.md): qué es, cómo se arranca y cómo está montado.
Y si vienes a retomar sin contexto, [docs/RETOMAR.md](docs/RETOMAR.md): el
estado al cerrar, qué está desplegado y **los fallos que se encontraron con su
causa** — el sitio donde mirar antes de volver a tocar algo.

Esto es lo otro — lo que no se deduce leyendo el código y cuesta dinero o una
tarde averiguar.

---

## LO PRIMERO: aquí se paga por generar

Una tanda de imágenes de un vídeo de cuatro minutos son ~126 imágenes y ~4,4 $.
No es un detalle de producto: es la razón de la mitad de las decisiones de este
repo, y de estas tres reglas.

**1. No escribas params «por defecto» al abrir una pantalla.** La firma de un
paso se calcula sobre los params GUARDADOS. Escribir un valor que ese proyecto
nunca tuvo mueve la firma, deja obsoleto el paso y todo lo que cuelga, y la
pantalla ofrece regenerar el vídeo entero sin que nadie haya pedido nada. Las
pantallas editan una copia y solo guardan cuando alguien toca algo.

**2. Las tandas de imágenes se lanzan DE UNA EN UNA.** Dos a la vez tardan el
doble por imagen y pierden el registro del gasto.

**3. Un guardián calibrado sobre un fallo aprende a dar por bueno ese fallo.**
`p6_assets._planos_repetidos` tumba la tanda si dos planos acaban con la MISMA
imagen. Tiene dos excepciones —la cartela y la continuación de un plano largo—
y las dos están explicadas en su docstring. Si añades una tercera, comprueba
antes que lo que la justifica no es un bug.

---

## El grafo, y por qué no se toca

```
ingesta → brief → guion → voz → revision_audio → assets → callouts → render
```

Los ids **no se renombran** y **no se quita ninguno**, ni el que parezca que no
hace nada. `brief` es una cuenta determinista de dos segundos que no llama a
ningún modelo, y aun así sigue en el grafo: su firma encadena la del guion, así
que sacarlo dejaría obsoleto el guion de todos los proyectos guardados, en
cascada hasta el render. Mover su PANTALLA no cuesta nada; mover el PASO es una
migración.

### Lo que hay que saber de `nucleo/estado.py`

- **El manifiesto de cada versión vive fuera de `estado.json`**, en
  `pasos/<paso>/_versiones/v<N>.json`. Antes iba dentro y crecía como versiones
  × unidades: un vídeo de 300 planos llegó a 320 MB de `estado.json` y 9 s por
  petición. `Estado.manifiesto_version` **lanza** si el fichero falta o trae
  menos unidades de las que dice la versión: devolver `{}` vaciaría el mapa vivo
  y la pantalla ofrecería regenerar el vídeo entero. Se sigue leyendo el formato
  antiguo, y eso es permanente: un proyecto que llegue de fuera funciona sin
  migrar.
- **`completar()` escribe el manifiesto ANTES de tocar `datos`.** No es estilo:
  al revés, un fallo dejaría en disco `activa: N` con `versiones` sin la N, y
  «Revertir» enseñaría las imágenes de la versión anterior como si fueran las
  recién pagadas.
- **La carpeta de versiones va FUERA de `v<N>/`**: `sembrar_trabajo` copia la
  carpeta de la versión activa a `trabajo/` y `_recoger_trabajo` la vuelca en la
  SIGUIENTE, así que un manifiesto dentro de `v21` acabaría dentro de `v22` con
  pinta de correcto.
- **No caches el manifiesto en el documento.** `_guardar` filtra las claves con
  guion bajo SOLO en la raíz, así que una cache anidada se escribiría dentro de
  `estado.json` y el fichero recuperaría sus 320 MB en silencio.

---

## Copiar un proyecto o un estilo a otra máquina

**No basta con copiar la carpeta.** Un proyecto guarda rutas absolutas en tres
sitios: las salidas de cada unidad, los manifiestos de cada versión y las
referencias de estilo — y ese último entra en la firma del paso. Copiar y ya
deja `assets`, `callouts` y `render` en obsoleto: la pantalla ofrece regenerar
todos los planos ya pagados.

Hay que **mudar las rutas y volver a sellar las firmas**, y el sellado tiene dos
trampas:

1. **No se re-sella todo, solo lo que la mudanza movió.** `guion` guarda a
   propósito una `firma` que no cuadra con la calculada (cuando alguien corrige
   el guion a mano manda `firma_propia` y la otra se queda atrás). «Arreglarla»
   mueve el sello de salida del guion, que entra en la firma de la voz, y la
   cascada deja obsoleto todo lo de abajo. La regla es comparar contra la firma
   **calculada ANTES de mudar**.
2. **Los manifiestos del histórico también llevan firmas de unidad.** Sin
   re-sellarlos el estado vivo queda perfecto y cada «Revertir» enseña todas las
   unidades en obsoleto.

Y la comprobación es la mitad del trabajo: hay que contar **cuántos de los
ficheros que el estado dice haber producido están de verdad en disco**, en las
dos máquinas, y comparar. Una mudanza a medias no da ningún error al abrir el
proyecto; se ve al pedir una miniatura.

---

## La interfaz: una pantalla, y sin dependencias

`web/app.js` son ~10.000 líneas de JavaScript a pelo — sin framework y sin
`npm install`. Se sirve con `?v=<sello>` calculado del propio fichero, así que
**no hay ningún número que subir a mano** al cambiarlo.

**HAY UNA SOLA PANTALLA.** Hubo dos modos (uno guiado y uno desglosado en
pestañas) y aquí solo está el guiado. Si te encuentras algo que parece del otro
—una tabla de pestañas, un panel por paso— comprueba antes si lo alcanza
alguien:

```bash
python herramientas/alcanzables_js.py            # qué está vivo y qué no
python herramientas/alcanzables_js.py --quien X  # quién nombra a X
python herramientas/alcanzables_js.py --borrar   # una vuelta, y vuelve a correrla
```

**Dos funciones con el mismo nombre es un fallo silencioso.** En JavaScript la
segunda se lleva la primera por delante, sin un solo error, y la de arriba deja
de ejecutarse leyéndose como si funcionara. Pasó: el coste que se enseña antes
de generar compartía nombre con el medidor del vídeo ya empezado, y el hueco de
al lado del botón llevaba vacío desde el día que se escribió. Lo canta
`sin_llamar_js.py`.

Y por la CSP del proxy, **no se pueden usar atributos `style=""` en el HTML**:
el navegador los bloquea. Todo estilo va en `estilo.css`.

**El login vive DELANTE, y no es de aquí.** La interfaz le pregunta quién ha
entrado (`/api/me`) y le pide salir (`/api/logout`) a un servicio aparte; en
local esas rutas no existen, la pastilla de la cuenta se queda oculta y no pasa
nada. Lo único a tener en cuenta si se despliega detrás de él: **al salir se va
a `${BASE}/login`**, no a donde diga la respuesta. Ese servicio contesta
`/login` a secas porque atiende a dos versiones del estudio y no sabe por cuál
se le está llamando; quien sí lo sabe es esta página. Con la respuesta a pelo,
salir desde `/v2/` te dejaba en el login de la otra versión.

---

## El asistente y la guía de inicio

La burbuja de abajo a la derecha es `pasos/asistente.py` más las rutas
`/api/asistente/*` de `app.py`; la guía de la primera vez son las tarjetas de
`abrirInicio` en `web/app.js`. Lo que no se ve leyendo el código:

- **El asistente corre el CLI con `Read`, `Grep` y `Glob` sobre la carpeta del
  Estudio, y con las HERRAMIENTAS DEL ESTUDIO** (`pasos/mcp_estudio.py`, un
  servidor MCP mínimo que el CLI carga con `--mcp-config` y que van
  pre-autorizadas como `mcp__estudio__*`): probar las claves de verdad, ver el
  estado, los trabajos, la bitácora, cancelar un trabajo. Cada herramienta
  habla con la API del Estudio por HTTP (`ESTUDIO_API`, que pone `app.py` al
  arrancar), nunca importando código: lo que hace es lo que haría la
  pantalla. Sin Bash, sin escribir, sin internet. `secretos/` queda
  fuera por REGLA DE PERMISO del CLI (`Read(./secretos/**)`, en
  `asistente.vetos_de_lectura`), y está medido: pedirle que lo abra devuelve
  «File is in a directory that is denied by your permission settings». El
  prompt de sistema también se lo dice, pero la regla es la que manda. Si
  alguna vez las claves se guardan en otra carpeta DENTRO del repo, se añade a
  `CARPETAS_VETADAS` antes que nada.
- **Contesta con sonnet/medium a propósito**, no con el defecto del canal
  (opus/xhigh): un chat pide segundos. No pasa por `cli_claude.por_defecto_de`,
  que subiría al defecto del canal. Se cambia con `ESTUDIO_ASISTENTE_MODELO` y
  `ESTUDIO_ASISTENTE_ESFUERZO`.
- **Una charla es una sesión del CLI** (`--resume` con el `session_id` del
  sobre). Vive en memoria: recargar la página la reencuentra, reiniciar el
  servicio la pierde y la pantalla abre otra sin ruido. Si reanudar falla se
  vuelve a empezar con los últimos turnos pegados; un cupo agotado o un plazo
  vencido NO se reintentan.
- **La respuesta se sigue preguntando, no con una petición larga**: detrás del
  proxy una petición de un minuto se corta a los sesenta segundos. Un turno por
  charla; el segundo a la vez es un 409.
- **`_asistente_listo` tiene que decir lo mismo que `cli_claude.cuentas()`**:
  sin ninguna cuenta con `entrada`, el motor habla con la sesión por defecto
  del CLI, y el asistente también. Una cuenta añadida y nunca logueada no
  cuenta en ninguno de los dos sitios.
- **«Con sesión» no es «funciona».** `pasos/salud_cli.py` apunta cómo
  respondió cada cuenta la última vez (ok, cupo, sesión, tiempo, error) y lo
  escribe `cli_claude._una_pasada`, el único sitio por el que pasa toda
  llamada. La pantalla lo enseña al lado de la sesión (burbuja, Configuración,
  guía) y «Probar» le habla con haiku y una palabra. Un estado malo se queda
  hasta que una llamada vuelve a salir bien: nadie adivina cuándo se renueva
  un cupo, el mensaje del CLI ya trae la fecha. Toda suite que doble el CLI
  redirige `ESTUDIO_SECRETOS`, o la salud de sus dobles acaba en el almacén.
- **Las claves se prueban contra su servicio** (`pasos/comprobar_claves.py`)
  con llamadas que no cuestan dinero. Lo único que no puede saber es si OpenAI
  tiene saldo, y lo dice. FreeSound va con el token de la columna «Client
  secret/Api key», no con el Client id.
- **En la guía hay UNA cuenta de Claude** y el acceso arranca solo al abrir la
  tarjeta; el código se envía al pegarlo. La cadena de cuentas de respaldo
  sigue en Configuración, que es donde se necesita.
- **La foto del estado la hace `app.py`** (`_foto_para_asistente`) y se puede
  mirar en `GET /api/asistente/foto`. No lleva ninguna clave; lo comprueba
  `prueba_api`.
- **La marca de la guía (`onboarding_visto`) es un ajuste del servidor.** Toda
  suite que la toque redirige `ESTUDIO_AJUSTES`, o la marca acaba en el
  `ajustes.json` de verdad.
- **Configuración y la guía comparten estado** (`estadoConfig()`): quien
  guarde una clave llama a `repintarClaves()`, no a `pintarConfig()`, y las dos
  pantallas se enteran.
- **En `app.js`, un acento grave dentro de una expresión regular** parte por la
  mitad los tokenizadores de `herramientas/` (se creen que empieza una
  plantilla) y dan por muerto todo lo que venga detrás. Se escribe `\x60`.

---

## Lo que NO hay, y no es un olvido

Este producto sale de uno más grande, y estas piezas se quitaron a propósito.
Si echas una en falta, esto es por qué no está:

| Qué | Por qué no está |
|---|---|
| El modo editor, con sus pestañas por paso | una sola pantalla; lo demás era el mismo motor visto en detalle |
| Vídeos de YouTube como material | el material es lo que se escribe, y vive en `ingesta.texto` |
| El documentalista (buscar en internet) | con una sola vía para el material no hay nada que decidir |
| Los personajes fijos del canal | el **reparto** de cada vídeo sí está: es lo que sostiene la consistencia visual |
| Las menciones ilustradas de un producto | con ellas se fue todo lo que llevaba el nombre de un patrocinador |
| El dictado por voz | pedía un modelo aparte y su propio entorno |
| El bloc de enlaces, la bitácora, el monitor | notas y telemetría que no hacen un vídeo |

**Y no vuelvas a meter ninguna sin mirar `pasos/recetas.py`:** una tarea que no
está en la receta no corre, y una pantalla que la ofrece llama a una ruta que ya
no existe. Es exactamente lo que había que arreglar aquí — la interfaz seguía
pintando el micrófono y el mapa después de que el motor dejara de servirlos.

---

## Las medidas que hay, para no volver a medirlas

**El render** (`pasos/medir_render.py --reparto`), en 8 vCPU:

| Procesos | fotogramas/s |
|---|---|
| 1 | 1,98 |
| 4 (lo que elige `cpu_count()//2`) | 6,75 |
| **8 (`ESTUDIO_LOTES=8`)** | **10,40** |
| 16 | 10,85 — ya no escala |

La regla automática pide 4 y deja media máquina parada: en un servidor de ocho
hilos, `ESTUDIO_LOTES=8`.

**Lo que cuesta una imagen** no es el precio de OpenAI: es la factura. A cada
imagen se le adjuntan sus referencias de estilo, reparto y continuidad, y esas
se pagan como tokens de entrada — el 87 % del gasto en calidad baja. Medido
sobre 1.439 imágenes (mediana 5.114 tokens de entrada por imagen):

| Calidad | Imagen | Referencias | Total | Real | Aparente |
|---|---|---|---|---|---|
| low | 0,006 $ | 0,041 $ | **0,047 $** | — | — |
| medium | 0,041 $ | 0,041 $ | **0,082 $** | **1,7×** | 6,8× |
| high | 0,165 $ | 0,041 $ | **0,206 $** | **4,4×** | 27,5× |

El número de tokens vive en `pasos/ajustes.py:TOKENS_ENTRADA_POR_IMAGEN`. Si
cambia cuántas referencias se adjuntan, se vuelve a medir con el campo
`tokens.entrada` de las operaciones `imagen` de `coste_global.jsonl`.

**La calidad se elige en Configuración y es el punto de partida de los vídeos
NUEVOS**: se escribe en el param `calidad` de `assets` al crear el proyecto y no
se lee al generar. A propósito — `calidad` entra en la firma de cada imagen, así
que un defecto retroactivo dejaría obsoletas las imágenes de todos los proyectos
que nunca la fijaron, y regenerarlas se paga.

---

## Antes de dar algo por terminado

```bash
powershell -NoProfile -File pruebas.ps1
```

Las veintitrés en verde, y las herramientas de análisis sin nada que decir
(`huerfanas_js` trae dos sospechosas de siempre, `async` y `fallar`, que no son
llamadas).
Y si has tocado la interfaz, **ábrela**: una regla de CSS de menos o un bloque
que no se pinta no da ningún error en ningún sitio.

Tres cosas que ahorran perseguir fallos que no existen:

- `prueba_pasos_visuales` reutiliza `%TEMP%\estudio_prueba_visual` entre
  ejecuciones; si una pasada se corta a medias, la siguiente falla por el estado
  sucio. `pruebas.ps1` la borra.
- `prueba_pasos_voz` sale a Cartesia de verdad **si hay clave**; si no, omite esa
  parte y lo dice. No es un fallo.
- `prueba_login` llama al CLI de Claude de verdad. Es la única que comprueba que
  el CLI sigue dejando entrar sin terminal y sin abrir un navegador.
