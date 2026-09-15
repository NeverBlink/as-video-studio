# La API

Todo lo que sirve `app.py`, sacado del propio código: ruta, verbo y la primera
frase del docstring de cada endpoint. **Este fichero no se escribe a mano**: lo
escribe `generar_api.py`, y `prueba_api.py` comprueba que no se quede viejo.

Reglas que valen para toda la API y no se repiten en cada fila:

- **Un endpoint por cosa que sabe hacer el núcleo.** La pantalla no calcula
  estado: lo pide. Ver [README.md](../README.md).
- **Los errores hablan castellano.** `ErrorApi(codigo, "frase")` sale como
  `{"error": {...}}` con la frase que lee una persona y el detalle técnico
  aparte.
- **Nada bloquea.** Lo que tarda devuelve `202` con `trabajo_id`, y el progreso
  se sigue por `GET /api/trabajos/{tid}` o por el `eventos` que devuelve.
- **Editar es decidir.** No hay endpoint de «guardar y confirmar»: `PUT` guarda,
  y pasar de paso es aprobar.


## Proyectos y papelera

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos` | Proyectos disponibles, del mas reciente al mas antiguo. |
| `POST` | `/api/proyectos` | Crea un proyecto nuevo a partir de {"nombre"}. |
| `DELETE` | `/api/proyectos/papelera` | Vacia la papelera entera. Tampoco tiene vuelta atras. |
| `GET` | `/api/proyectos/papelera` | Proyectos apartados, del mas recientemente apartado al mas antiguo. |
| `DELETE` | `/api/proyectos/papelera/{carpeta}` | Borra DE VERDAD un proyecto apartado. No hay vuelta atras. |
| `GET` | `/api/proyectos/papelera/{carpeta}` | Que hay dentro de un proyecto apartado, para poder decir que se pierde. |
| `POST` | `/api/proyectos/papelera/{carpeta}/restaurar` | Devuelve a su sitio un proyecto apartado. |
| `DELETE` | `/api/proyectos/{pid}` | Mueve el proyecto a la papelera. No borra nada. |
| `GET` | `/api/proyectos/{pid}` | Estado del proyecto: los ocho pasos, sus params, versiones y trabajos. |
| `PUT` | `/api/proyectos/{pid}` | Cambia el nombre VISIBLE del proyecto. -> la ficha. |
| `POST` | `/api/proyectos/{pid}/duplicar` | Copia un proyecto entero con lo que tiene puesto HOY. -> el nuevo. |
| `POST` | `/api/proyectos/{pid}/escenas/{sid}/vale` | «Este dibujo me vale para lo que dice ahora». -> {ok} |
| `POST` | `/api/proyectos/{pid}/feedback` | Feedback general o sobre una unidad; rehace SOLO lo que apunta. |
| `POST` | `/api/proyectos/{pid}/presets-canal/{preset_id}/aplicar` | Copia los valores del preset a los params de los pasos que toque. |
| `GET` | `/api/proyectos/{pid}/previsualizacion` | Las piezas para ver el video sin montarlo. -> {escenas, audio, ...} |
| `PUT` | `/api/proyectos/{pid}/redactor` | Guarda el prompt escrito de cada plano. Un prompt vacío lo quita. |
| `POST` | `/api/proyectos/{pid}/redactor/proponer` | Escribe el prompt de cada plano, con TODOS los planos delante de una vez. |
| `GET` | `/api/proyectos/{pid}/repaso` | Las notas escritas sobre el vídeo montado, con los cortes para anclarlas. |
| `POST` | `/api/proyectos/{pid}/repaso` | Una nota nueva, anclada al segundo en el que se pausó. |
| `POST` | `/api/proyectos/{pid}/repaso/aplicar` | Aplica las notas del repaso y vuelve a generar SOLO lo que cambian. |
| `POST` | `/api/proyectos/{pid}/repaso/imagenes` | Las imágenes de referencia que acompañan a una nota. |
| `GET` | `/api/proyectos/{pid}/repaso/imagenes/{nombre}` | Una imagen de referencia de una nota. |
| `DELETE` | `/api/proyectos/{pid}/repaso/{nid}` | Quita una nota del repaso. |
| `PUT` | `/api/proyectos/{pid}/repaso/{nid}` | Cambia el texto, el instante o las imágenes de una nota. |

## Pasos: estado, params y ejecución

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos/{pid}/pasos` | Resumen del DAG con el estado de cada paso. |
| `GET` | `/api/proyectos/{pid}/pasos/{paso}` | Detalle de un paso: params, salidas, unidades y versiones. |
| `POST` | `/api/proyectos/{pid}/pasos/{paso}/ejecutar` | Lanza el paso en segundo plano y devuelve el id del trabajo. |
| `PUT` | `/api/proyectos/{pid}/pasos/{paso}/params` | Actualiza los parametros del paso; la obsolescencia cae en cascada sola. |
| `POST` | `/api/proyectos/{pid}/pasos/{paso}/revertir` | Activa una version anterior del paso; nada se borra. |
| `GET` | `/api/proyectos/{pid}/pasos/{paso}/versiones` | Historico de versiones del paso. |

## Trabajos en marcha

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/trabajos` | Trabajos conocidos, opcionalmente de un solo proyecto. |
| `GET` | `/api/trabajos/{tid}` | Estado y progreso de un trabajo. |
| `POST` | `/api/trabajos/{tid}/cancelar` | Pide la cancelacion cooperativa de un trabajo. |
| `GET` | `/api/trabajos/{tid}/eventos` | Progreso del trabajo en vivo por Server-Sent Events. |

## Recetas y pestañas

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos/{pid}/generar` | Lo que va a hacer, cuanto tarda y cuanto cuesta. NO lanza nada. |
| `POST` | `/api/proyectos/{pid}/generar` | Recorre varias pestanas seguidas, en orden, en UN trabajo. |
| `GET` | `/api/proyectos/{pid}/pestanas/{pestana}` | Que le falta a esta pestana para estar terminada. |
| `POST` | `/api/proyectos/{pid}/pestanas/{pestana}/generar` | Un boton: hace todo lo de esta pestana, en orden y en paralelo lo que se pueda. |
| `GET` | `/api/recetas` | El catalogo de tareas por pestana y las recetas guardadas. |
| `POST` | `/api/recetas` | — |
| `DELETE` | `/api/recetas/{rid}` | — |

## Coste y bitácora

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/coste/global` | Agregado de todos los videos, con el desglose de cada uno. |
| `GET` | `/api/coste/tarifas` | Tabla de tarifas. Vive en un unico sitio: estudio/tarifas.json. |
| `PUT` | `/api/coste/tarifas` | Actualiza tarifas.json. Sirve para rellenar el precio por caracter. |
| `GET` | `/api/proyectos/{pid}/bitacora` | Historial estructurado del proyecto. |
| `GET` | `/api/proyectos/{pid}/bitacora/llm` | Historial en texto navegable, pensado para darselo a un LLM. |
| `GET` | `/api/proyectos/{pid}/coste` | Total del video, desglosado por proveedor, con la linea de cabecera. |
| `GET` | `/api/proyectos/{pid}/coste/eventos` | Detalle de cada consumo, filtrable por proveedor, paso y unidad. |
| `GET` | `/api/proyectos/{pid}/coste/flujo` | Coste en vivo por SSE, para que la cabecera se mueva mientras corre un paso. |
| `GET` | `/api/proyectos/{pid}/coste/por-paso` | Desglose por paso del pipeline: que fase se come el presupuesto. |
| `PUT` | `/api/proyectos/{pid}/coste/presupuesto` | Fija el presupuesto en dolares del video (null para quitarlo). |

## Origen y guion

| | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/proyectos/{pid}/guion/bloques/reescribir` | Reescribe unos bloques del guion con una frase. Sin tocar el audio. |

## Voz

| | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/proyectos/{pid}/voz/describir` | Describe como quieres que suene y devuelve voz y mandos propuestos. |
| `POST` | `/api/proyectos/{pid}/voz/previsualizar` | Sintetiza unos segundos con estos mandos de voz para escucharlos. |
| `POST` | `/api/proyectos/{pid}/voz/secciones/{seccion_id}/regrabar` | Regraba una seccion de la toma, con microcambio si se pide. |
| `GET` | `/api/voces` | Catalogo de voces de Cartesia, sin atarlo a ningun proyecto. |

## Catálogo, escenarios y piezas

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos/{pid}/assets/hechos` | Los planos que hay generados AHORA en la carpeta de trabajo. |
| `GET` | `/api/proyectos/{pid}/catalogo` | El catalogo APROBADO que hay guardado en los params de assets. |
| `PUT` | `/api/proyectos/{pid}/catalogo` | Guarda el catalogo aprobado en los params de assets. |
| `POST` | `/api/proyectos/{pid}/catalogo/proponer` | Lee el guion ENTERO y propone quien sale, donde y con que tono. |
| `GET` | `/api/proyectos/{pid}/conservacion` | Que se puede mantener del video, sin llamar a nadie y sin gastar. |
| `POST` | `/api/proyectos/{pid}/conservacion/analizar` | Pregunta por los planos dudosos y devuelve el plan definitivo. |
| `POST` | `/api/proyectos/{pid}/conservacion/aplicar` | Conserva lo que se puede conservar y marca el resto para rehacer. |
| `POST` | `/api/proyectos/{pid}/escenarios` | Un clic: deduce del guion quien sale y donde ocurre. |

## Estilo y moodboard

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/moodboard/{clave}/{origen}/{archivo}` | Sirve una lamina del banco de moodboards, que vive fuera de los proyectos. |
| `GET` | `/api/proyectos/{pid}/estilo` | Fotogramas ya extraidos y cuales estan elegidos ahora mismo. |
| `POST` | `/api/proyectos/{pid}/estilo/guia` | Escribe la guia de estilo mirando los fotogramas elegidos. |
| `PUT` | `/api/proyectos/{pid}/estilo/seleccion` | Guarda las imagenes de estilo elegidas en los params de assets. |
| `GET` | `/api/proyectos/{pid}/moodboard` | Las referencias de estilo dibujadas a proposito para este estilo. |
| `POST` | `/api/proyectos/{pid}/moodboard` | Dibuja las laminas de estilo. Quedan PROPUESTAS hasta que alguien las mira. |
| `POST` | `/api/proyectos/{pid}/moodboard/aprobar` | Mete el moodboard en el banco del canal. Es la decision de una persona. |

## Grafismo: subtítulos y cartelas

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos/{pid}/callouts/diseno` | Sets de diseno, el elegido y el que sugiere la guia de estilo del video. |
| `PUT` | `/api/proyectos/{pid}/callouts/plan` | Guarda el GRAFISMO del video en los params de callouts. |
| `GET` | `/api/proyectos/{pid}/callouts/vista` | La capa de ESE plano, dibujada ahora con el código de p7. |
| `GET` | `/api/proyectos/{pid}/cartelas` | Las plantillas de cartela con su muestra dibujada, y el plan guardado. |
| `PUT` | `/api/proyectos/{pid}/cartelas` | Guarda que planos son cartela (POR UNIDAD) y que plantillas se pueden usar. |
| `POST` | `/api/proyectos/{pid}/cartelas/plan` | Lee el guion y decide que tramos se cuentan mejor con texto que con dibujo. |
| `GET` | `/api/proyectos/{pid}/cartelas/vista` | El SVG de la cartela de ESE plano, dibujado ahora con el grafismo de ahora. |
| `GET` | `/api/proyectos/{pid}/direccion` | Qué se ve en cada plano: lo dirigido, y los planos que lo admiten. |
| `PUT` | `/api/proyectos/{pid}/direccion` | Guarda qué se ve en cada plano. Un texto vacío la quita. |
| `POST` | `/api/proyectos/{pid}/direccion/proponer` | Escribe qué se ve en cada plano, con TODOS los planos delante de una vez. |

## Sonido y transiciones

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/efectos/{archivo}` | Sirve un efecto del banco del canal, para poder oírlo antes de vetarlo. |
| `GET` | `/api/proyectos/{pid}/sonido` | Qué suena en este vídeo: el tema puesto, los efectos surtidos y el catálogo. |
| `PUT` | `/api/proyectos/{pid}/sonido` | Fija el tema (bajándolo al banco), el interruptor o el nivel de música. |
| `GET` | `/api/proyectos/{pid}/sonido/arco` | El arco que sale del RITMO del montaje. Gratis, sin salir a la red. |
| `POST` | `/api/proyectos/{pid}/sonido/banda` | Monta la banda sonora SOLA: un tema por tramo, elegido por el ritmo. |
| `POST` | `/api/proyectos/{pid}/sonido/efectos` | Llena el banco de efectos del canal para los papeles que se pidan. |
| `POST` | `/api/proyectos/{pid}/sonido/musica` | Temas de Jamendo que pegan con el tono. Devuelve candidatos, no elige. |
| `POST` | `/api/proyectos/{pid}/sonido/vetados` | Prohíbe un efecto en TODO el canal, o levanta el veto con `quitar`. |
| `GET` | `/api/proyectos/{pid}/transiciones` | Las transiciones que existen, con su GLSL, y cuales entran en este video. |

## Render y montaje

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/proyectos/{pid}/capturas` | Capturas del proyecto, filtrables por paso y escena. |
| `POST` | `/api/proyectos/{pid}/capturas` | Guarda una captura anotada de los pasos callouts o render. |
| `POST` | `/api/proyectos/{pid}/capturas/aplicar` | Traduce las capturas a instruccion y rehace SOLO las escenas tocadas. |
| `GET` | `/api/proyectos/{pid}/capturas/contexto` | Donde cae un instante y con que material se compone ese fotograma. |
| `DELETE` | `/api/proyectos/{pid}/capturas/{cid}` | Borra una captura y su PNG. |
| `GET` | `/api/proyectos/{pid}/montaje/notas` | Lo escrito sobre el vídeo terminado. No toca ninguna firma. |
| `PUT` | `/api/proyectos/{pid}/montaje/notas` | Guarda la nota del vídeo entero. Autoguardado, como todo lo demás. |

## Presets del canal

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/presets` | Presets de estilo de locucion. |
| `GET` | `/api/presets-canal` | Presets guardados, agrupados por tipo, mas su papelera y el catalogo. |
| `POST` | `/api/presets-canal` | Guarda un preset nuevo, o sustituye el contenido de uno que ya existe. |
| `DELETE` | `/api/presets-canal/papelera/{pid}` | Borrado definitivo. Solo alcanza a lo que ya esta en la papelera. |
| `GET` | `/api/presets-canal/papelera/{pid}` | Que hay dentro de un preset apartado, para decir que se pierde. |
| `POST` | `/api/presets-canal/papelera/{pid}/restaurar` | Devuelve a la lista un preset apartado. |
| `DELETE` | `/api/presets-canal/{pid}` | A la papelera. No borra nada: la ficha y sus fotogramas siguen enteros. |
| `PATCH` | `/api/presets-canal/{pid}` | Cambia solo el nombre o la nota. Lo que el preset guarda no se toca. |
| `GET` | `/api/presets-canal/{pid}/fichero/{archivo:path}` | Un fichero de la carpeta del preset (fotogramas, laminas del moodboard). |
| `GET` | `/api/presets-canal/{pid}/miniatura` | La cara del preset en el desplegable: uno de sus propios fotogramas. |

## Modo light: estilos y vídeo

| | Ruta | Qué hace |
|---|---|---|
| `POST` | `/api/estimacion` | Lo que va a salir de esa duracion: palabras, planos y dolares. |
| `GET` | `/api/presets-light` | Los presets de canal, con sus viñetas y su plan de generacion. |
| `POST` | `/api/presets-light` | Crea el estilo entero a partir de los cuatro campos. |
| `POST` | `/api/presets-light/imagenes` | Guarda las imagenes que acompanan a una descripcion de estilo. |
| `DELETE` | `/api/presets-light/imagenes/{nombre}` | Quita una imagen de la carpeta de espera. Quitarla de la lista es esto. |
| `GET` | `/api/presets-light/imagenes/{nombre}` | La miniatura de una imagen que espera en el buzon. |
| `POST` | `/api/presets-light/plan` | Lo que va a hacer, en orden y con sus tiempos. No lanza nada. |
| `DELETE` | `/api/presets-light/talleres/{taller_id}` | Tira un intento a medias. A la papelera de proyectos, no al vacio. |
| `DELETE` | `/api/presets-light/{preset_id}` | A la papelera de presets, y su taller con el. |
| `PUT` | `/api/presets-light/{preset_id}` | El nombre, el idioma y la guia de tono: lo que se cambia a mano. |
| `POST` | `/api/presets-light/{preset_id}/duplicar` | Una copia del estilo, con su taller. |
| `POST` | `/api/presets-light/{preset_id}/regenerar` | Rehace UNA de las tres partes con una frase de feedback. |
| `POST` | `/api/presets-light/{preset_id}/video` | Un proyecto de video nuevo con ese estilo ya aplicado. -> la ficha. |
| `POST` | `/api/presets-light/{preset_id}/voz/previsualizar` | Unos segundos con la voz de este estilo, para escucharla. |

## Ajustes del CLI y estadísticas

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/ajustes` | Lo que hay puesto, y lo que cuesta cada calidad de imagen. |
| `PUT` | `/api/ajustes` | Cambia ajustes. NO toca ningun proyecto: es el valor de los NUEVOS. |
| `GET` | `/api/ajustes-cli` | Catalogo de modelos y esfuerzos, y en que pasos se puede elegir. |
| `GET` | `/api/estadisticas` | Historico de tiempos reales, entre todos los proyectos. |
| `POST` | `/api/estadisticas/valoracion` | Anota si el resultado de un ajuste gusto o no. |

## Claves y enlaces

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/claves` | Que claves hay puestas, sin ninguna clave dentro. |
| `PUT` | `/api/claves` | Guarda las claves y espeja el .env que leen los motores. |
| `GET` | `/api/claves/cli` | Las cuentas del CLI en orden, con quién hay logueado en cada una. |
| `POST` | `/api/claves/cli/{cid}/codigo` | Le pasa al CLI el código que devolvió la página de acceso. |
| `DELETE` | `/api/claves/cli/{cid}/entrar` | Tira el acceso a medias de esa cuenta. |
| `POST` | `/api/claves/cli/{cid}/entrar` | Arranca el acceso de esa cuenta y devuelve el enlace donde entrar. |
| `POST` | `/api/claves/cli/{cid}/probar` | Le habla a esa cuenta con una llamada mínima y apunta cómo responde. |
| `POST` | `/api/claves/cli/{cid}/salir` | Cierra la sesión de esa cuenta, sin quitarla de la lista. |
| `POST` | `/api/claves/probar` | Prueba cada clave contra su servicio y dice cuál funciona de verdad. |

## El asistente

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/api/asistente` | Si el asistente puede contestar ahora, y con qué cuenta. |
| `POST` | `/api/asistente/charlas` | Abre una charla vacía con el asistente. |
| `DELETE` | `/api/asistente/charlas/{cid}` | Cierra una charla; lo que estuviera contestando se cancela. |
| `GET` | `/api/asistente/charlas/{cid}` | Los turnos de una charla; el último dice si sigue pensando. |
| `POST` | `/api/asistente/charlas/{cid}/cancelar` | Para la respuesta que esté en marcha en esa charla. |
| `POST` | `/api/asistente/charlas/{cid}/mensajes` | Manda una pregunta; la respuesta se sigue con GET de la charla. |
| `GET` | `/api/asistente/foto` | Lo que el asistente ve del Estudio ahora mismo, en texto y sin claves. |
| `POST` | `/api/asistente/probar` | Prueba las cuentas con las que contestaría el asistente y dice cómo están. |

## Ficheros y salud

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/a/{pid}/{ruta:path}` | Sirve un archivo del proyecto (imagen, wav, svg, mp4) con proteccion. |
| `GET` | `/api/salud` | Estado del servicio. |

## Lo demás

| | Ruta | Qué hace |
|---|---|---|
| `GET` | `/` | La interfaz del Estudio. |
| `GET` | `/{fichero}` | Sirve un fichero suelto de web/ (app.js, estilo.css...). |

---

**147 endpoints.** Escrito por `generar_api.py` desde `app.py`.
