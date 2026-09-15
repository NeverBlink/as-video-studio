# Los motores

Las piezas que hacen el trabajo pesado, cada una con su API y sin saber nada de
la aplicación que las llama. **Aquí no vive ningún vídeo**: los datos de cada uno
viven en su carpeta de `proyectos/`.

## Por qué están fuera de `pasos/`

Un paso del grafo decide QUÉ hay que hacer; un motor sabe CÓMO. La frontera no es
de estilo: los motores **se recargan solos cuando su fichero cambia**
(`pasos/medios.motor` y `pasos/comun.cargar_motor` miran el sello del fichero),
así que se puede corregir el prompt de una imagen o el grafo de mezcla sin
reiniciar el servicio y sin perder la tanda que está corriendo.

Lo que eso impone: **un motor no importa código de la aplicación**. Lo que
necesita del entorno lo lee por CONTRATO — una ruta y una forma de fichero, no un
`import`. Ejemplo: el almacén de claves que escribe la pantalla de Configuración
lo leen `imagen_openai` y `voz_cartesia` abriendo `secretos/claves.json`, nunca
llamando a `pasos/claves.py`.

| Carpeta | Qué hace |
|---|---|
| `guion/` | Corta la narración en planos a partir de las marcas de palabra (`segmentar`) y mide la cadencia real de una toma (`medir_ritmo`). |
| `voz_cartesia/` | Sintetiza la locución con Cartesia y devuelve las marcas de tiempo con las que se sincroniza todo lo demás (`voz`, `sincronizar`). |
| `imagen_openai/` | Genera cada plano. Lleva dentro el freno del límite de la API, la cuenta del gasto y el reparto entre cuentas. |
| `capa_vectorial/` | Lo que se dibuja ENCIMA del plano: cabeceras de capítulo (`cabecera`) y mapas encuadrados por región (`mapa`, con `datos/paises_110m.geojson`). |
| `render_video/` | El recorrido de cámara de cada plano (`movimiento`): la ventana que se mueve por encima de una imagen quieta. |
| `reglas/` | Las reglas de dibujo aprendidas del feedback, con su procedencia (`reglas.json`) y el destilador que las escribe (`reglas.py`). |
| `revision/` | Traduce a palabras lo que se ha pintado sobre una captura, para poder rehacer un plano con esa nota delante (`regenerar`). |

## Dónde se instalan

En el árbol del producto, en esta misma carpeta. Se pueden mover con
**`ESTUDIO_MOTORES`**, y hace falta cuando varias cuentas comparten una máquina y
los motores se instalan una sola vez: es lo que leen `pasos/medios.MOTORES` y
`pasos/catalogo_visual.RUTA_MAPA`.

## Lo que hace falta tener instalado

- **ffmpeg y ffprobe** en el `PATH`, o `ESTUDIO_FFMPEG` apuntando al ejecutable.
  Los usan la voz, la banda sonora y el montaje del MP4.
- **Microsoft Edge** (o Chrome), que es quien rasteriza cada plano. Se puede
  fijar con `ESTUDIO_EDGE`.
- **Las fuentes** de los subtítulos y las cartelas, en `ESTUDIO_FUENTES`. Que
  midan y dibujen el MISMO fichero no es una casualidad de la instalación: es el
  invariante. Con una fuente sustituida por otra, la cuenta sale bien y el número
  mal, y eso solo se ve mirando un PNG.
