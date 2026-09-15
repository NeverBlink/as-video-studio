# AS Video Studio

Convierte **lo que escribas** —unas notas, un artículo pegado, una cronología, o
tu propio guion— en un vídeo de animación narrada, pasando por ocho fases con
revisión humana entre ellas.

```
ingesta → brief → guion → voz → revision_audio → assets → callouts → render
```

Esos son los ids del grafo y **no cambian**: renombrarlos invalidaría los
proyectos guardados. En pantalla son **cinco paradas**, en la barra de abajo:
los estilos, el encargo (con el material y las llamadas a la acción; se vuelve a
él y se corrige también después de generar el guion), el guion, las imágenes y
el vídeo, con el coste delante en todas.

**No es un asistente: es un sistema de build.** Cada paso es una función de sus
entradas, con hash de contenido. Cambiar algo no regenera todo — deja obsoleto
solo lo que dependía de lo que cambió, con granularidad por unidad (una escena,
un asset). Sin eso, cada retoque obligaría a rehacer el vídeo entero y esto no
serviría para nada: **una tanda de imágenes cuesta dinero de verdad**.

**Nada se confirma a mano.** Editar es decidir: lo que se toca se guarda solo al
dejar de teclear, y el paso siguiente usa la última versión. No hay botones de
«guardar cambios» ni de «aprobar»; pasar al paso siguiente ES la aprobación.

---

## Las dos cosas que se crean

**Un ESTILO** es lo que se decide una vez y se repite en todos los vídeos de un
canal: unas imágenes de referencia con sus indicaciones (cómo se dibuja), cómo se
cuenta (el tono), cada cuánto corta el vídeo (el ritmo), quién lo locuta y en qué
idioma. Se escribe una vez y cada vídeo nace con él puesto.

**Un VÍDEO** es lo que cambia cada vez: cómo se llama, cuánto dura, el material
del que salen los hechos, las indicaciones de cómo contarlo, y las llamadas a la
acción de ESE vídeo. Las llamadas a la acción se deciden vídeo por vídeo a
propósito: es lo que más cambia entre dos vídeos del mismo canal, y guardarlas en
el estilo obligaba a acordarse de cambiarlas en cada encargo.

---

## Ponerlo en un servidor (lo normal)

Una línea en la consola del VPS, cinco minutos, y queda montado con su dirección,
su candado y su contraseña — incluido todo lo que hace falta alrededor (ffmpeg,
el navegador que dibuja los planos, las fuentes, el CLI de Claude):

```bash
curl -fsSL https://raw.githubusercontent.com/NeverBlink/as-video-studio/main/instalar.sh -o instalar.sh && bash instalar.sh
```

Los tres pasos, con qué pulsar y qué hacer si algo falla, están en
**[INSTALAR.md](INSTALAR.md)**. Lo que el instalador hace por dentro, y por qué,
en **[despliegue/LEEME.md](despliegue/LEEME.md)**.

## Arrancar en tu propia máquina

```bash
python app.py --puerto 8020
```

Y abrir `http://127.0.0.1:8020/`. Con `--host 0.0.0.0` escucha en la red local;
**no lo pongas a la vista de internet sin un login delante**: la API no
autentica nada, a propósito (ver «Quién está dentro» más abajo).

### Lo que hace falta tener

| Qué | Para qué | Si falta |
|---|---|---|
| Python 3.12 con `fastapi`, `uvicorn`, `Pillow`, `numpy` | el servicio | no arranca |
| **ffmpeg** y **ffprobe** | la voz, la música y el MP4 | los pasos que los usan lo dicen |
| **Microsoft Edge** (o Chrome) | rasterizar cada plano | igual |
| Las **fuentes** de los subtítulos y las cartelas | medir y dibujar el texto | ver el aviso de `motores/README.md` |
| El **CLI de Claude**, con sesión | el guion, el catálogo visual, los rótulos | no hay vídeo |
| Una **clave de OpenAI** | las imágenes | no hay vídeo |
| Una **clave de Cartesia** | la voz | no hay vídeo |
| Las de **Jamendo** y **FreeSound** | música y efectos | el vídeo sale sin ellos; son las únicas prescindibles |

Las claves se ponen en **Configuración** (el engranaje de arriba a la derecha) y
se guardan en `secretos/claves.json`, fuera del control de versiones. Ninguna
clave baja entera al navegador: la pantalla ve la etiqueta, los cuatro últimos
caracteres y el estado.

**La primera vez, una guía de inicio** las pide de una en una —Claude la
primera, porque es un login y no una clave— con los pasos y el enlace de donde
se consigue cada una. Se ve una vez por instalación (la marca vive en los
ajustes del servidor, no en el navegador) y se vuelve a abrir desde
Configuración.

**Y abajo a la derecha hay un asistente.** Es un chat que contesta con tu propia
cuenta de Claude —la misma con la que se escribe el guion— y que tiene delante
la documentación del producto, el código (sólo lectura: Read, Grep y Glob) y una
foto del estado del Estudio en el momento de cada pregunta: qué claves hay, qué
vídeo está abierto, qué paso está parado y con qué error. Y tiene manos:
prueba las claves contra su servicio, mira los trabajos y la bitácora, y para
un trabajo colgado, sin pedir permisos (`pasos/mcp_estudio.py`). Sin sesión de
Claude lo dice y manda a entrar; con el cupo agotado, dice hasta cuándo. Lo
que puede y no puede leer —`secretos/` no, por regla de permiso del CLI— está
en `pasos/asistente.py`.

**«Puesta» no es «funciona».** Configuración tiene «Probar todas las claves»
(cada una contra su servicio, sin gastar) y cada cuenta de Claude enseña, al
lado de la sesión, cómo respondió la última vez: funciona, sin cupo, sesión
caducada. Lo apunta cada llamada al CLI (`pasos/salud_cli.py`).

---

## Cómo está montado

```
app.py            el servicio HTTP. Una ruta por cosa que sabe hacer el núcleo.
nucleo/           el grafo de estado: versiones, firmas, obsolescencia, trabajos
pasos/            los ocho pasos y lo que deciden (prompts, params, presets)
motores/          el trabajo pesado: voz, imagen, mapas, movimiento, montaje
web/              la interfaz: index.html + app.js + estilo.css, sin dependencias
herramientas/     análisis estático propio (ver más abajo)
docs/API.md       los 147 endpoints, generados del código
```

**`nucleo/` no sabe de vídeo.** Es un grafo de pasos con versiones y firmas: se
le podría poner otra cosa encima. **`pasos/` no sabe de HTTP** y **`motores/` no
importa código de la aplicación** — leen lo que necesitan por contrato (una ruta
y una forma de fichero), que es lo que permite recargarlos sin reiniciar.

### La firma, que es la pieza que hay que entender

Cada paso guarda la **huella** de sus params y de las salidas de los pasos de
los que depende. Si la huella calculada no cuadra con la guardada, el paso está
**obsoleto** — y lo están, en cascada, los que dependen de él.

De ahí salen dos reglas que parecen arbitrarias y no lo son:

- **Escribir un param «por defecto» al abrir una pantalla mueve la firma.** Un
  proyecto que nunca tuvo ese param pasaría a estar obsoleto entero sin que
  nadie pidiera nada, y eso son imágenes que se vuelven a pagar. Por eso las
  pantallas editan una copia y solo guardan cuando alguien toca algo.
- **Las rutas absolutas están DENTRO de las firmas.** Copiar la carpeta de un
  proyecto a otra máquina no basta: hay que mudar las rutas y volver a sellar
  las firmas, o el vídeo entero aparece obsoleto.

---

## Las pruebas

```bash
powershell -NoProfile -File pruebas.ps1
```

Veinticuatro suites, y **por PowerShell y no por bash**: Edge headless devuelve
código 0 y no escribe el PNG cuando se lanza desde un shell sandboxeado, así que
`prueba_pasos_visuales` falla con «Edge no generó ...png» sin que nada esté roto.

Lo que se comprueba de verdad, y no es humo:

- `prueba_api.py` (743) levanta el servicio y recorre la API entera.
- `prueba_pasos_visuales.py` (229) monta un proyecto de verdad sobre el núcleo y
  ejecuta la cadena de imágenes, rótulos y montaje **hasta el MP4**. Se fabrica
  su propio material: no depende de ningún proyecto.
- `prueba_piezas.py` (1035) las piezas una a una. **No puede pagar una imagen**:
  deja el motor sin `generar` antes de empezar, así que una firma de cache que
  deje de acertar sale como un fallo con su traza y no como una factura.
- `nucleo/prueba_adversarial.py` mata el proceso a mitad de una escritura, cruza
  hilos y procesos, y prueba a salirse de la carpeta con `../`.

`pruebas.ps1` corre además las **herramientas de análisis**, que cantan lo que
ninguna prueba ve porque nadie ejecuta esa línea:

| Herramienta | Qué encuentra |
|---|---|
| `indefinidos_py.py` / `indefinidos_js.py` | un nombre que no está declarado |
| `atributos_py.py` | `modulo.algo()` donde `algo` ya no existe en ese módulo |
| `huerfanas_js.py` | una llamada a una función que ya no está |
| `sin_llamar_js.py` | una función que nadie nombra, y dos con el MISMO nombre |
| `alcanzables_js.py` | funciones y tablas que no se pueden alcanzar desde ningún sitio |
| `css_sin_usar.py` | reglas de CSS de pantallas que ya no existen |

---

## Quién está dentro

**Este servicio no sabe de cuentas, y es deliberado.** No hay usuarios, ni
sesiones, ni permisos: se sirve a quien llame. El aislamiento, cuando hace
falta, va **por proceso**: un `app.py` por cuenta, cada uno con sus variables de
entorno apuntando a sus datos, y un proxy con login delante que decide a cuál
enruta.

Se hace así porque la alternativa —enseñarle al código lo que es un usuario— es
un concepto nuevo en las ocho fases, en las firmas y en cada ruta, para resolver
algo que un proceso aparte resuelve sin tocar nada. Si el proxy contesta
`/api/me`, la interfaz enseña el nombre de la cuenta; si no contesta, no pasa
nada y no se enseña.

### Dónde viven los datos

Todo se puede mover con variables de entorno, y es lo que hace posible el
aislamiento por proceso:

| Variable | Qué mueve |
|---|---|
| `ESTUDIO_PROYECTOS` | los vídeos |
| `ESTUDIO_PRESETS` | los estilos |
| `ESTUDIO_BANCO`, `ESTUDIO_BANCO_PRESETS` | las imágenes y el audio de stock |
| `ESTUDIO_SECRETOS` | las claves de API |
| `ESTUDIO_AJUSTES`, `ESTUDIO_RECETAS`, `ESTUDIO_TARIFAS` | la configuración |
| `ESTUDIO_ESTADISTICAS`, `ESTUDIO_COSTE_GLOBAL`, `ESTUDIO_BITACORA_GLOBAL` | lo medido y lo gastado |
| `ESTUDIO_MOTORES`, `ESTUDIO_FUENTES` | los motores y las tipografías |
| `ESTUDIO_EDGE`, `ESTUDIO_FFMPEG`, `ESTUDIO_FFPROBE` | los ejecutables |
| `ESTUDIO_LOTES` | cuántos planos se renderizan a la vez |
| `ESTUDIO_SIMULAR=1` | no sale a ninguna API de pago: lo usan las pruebas |

**`ESTUDIO_ESTADISTICAS` importa más de lo que parece.** El histórico guarda 30
muestras por paso, y de ahí sale lo que promete la barra de progreso. Una suite
que escriba en el de verdad expulsa las medidas reales por antigüedad, y la
barra empieza a prometer la mitad del tiempo. Por eso todas las suites lo
redirigen, y `pruebas.ps1` lo redirige otra vez por si alguna se olvida.
