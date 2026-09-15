"""
Sacar imagenes de estilo de un video de YouTube.

Para que
--------
El paso de assets manda al generador unas cuantas imagenes de referencia que
definen COMO se dibuja: el trazo, la paleta, la forma de los personajes. Sin
ellas el prompt de estilo es solo texto, y ademas la llamada sale sin adjuntos y
la API la rechaza con un error que no dice nada ("Unsupported content type").

Hasta ahora esas imagenes habia que ponerlas a mano, con rutas absolutas del
disco del servidor. Aqui se automatiza la parte mecanica: se le da la URL de un
video cuyo estilo gusta, se baja con yt-dlp y se trocea en fotogramas, igual que
hace el paso de Origen.

Elegir es del usuario, y a proposito
------------------------------------
Este modulo NO decide cuales son buenas. Extrae los fotogramas, tira los que no
sirven para nada, y los ensena todos para que una persona marque los que quiera.

Se intento elegirlos automaticamente (deteccion de caras y de texto del motor de
ingesta) y **no funciona con dibujo plano**, medido sobre 120 fotogramas:

- el detector de caras esta hecho para caras fotograficas y en personajes de
  trazo devuelve casi cero (0,03 como maximo), asi que no distingue un primer
  plano de un paisaje;
- el detector de texto usa MSER, pensado para texto impreso, y la rotulacion
  dibujada a mano no le dispara: un fotograma con un cartel escrito midio
  densidad 0,0, y a la vez marcaba paisajes limpios como si tuvieran texto.

Etiquetar mal es peor que no etiquetar, porque manda a elegir por una razon
falsa. Lo unico que si se detecta sin fallar es el brillo y el contraste, asi que
lo unico que se descarta son los fotogramas casi negros (transiciones y rotulos
sobre fondo negro), que no ensenan ni trazo ni paleta.

Cuantas elegir: **al menos 3**. Con una o dos, el generador copia esa escena
concreta en vez de quedarse con el estilo; hacen falta varias situaciones
distintas para que lo unico que tengan en comun sea la forma de dibujar. El tope
esta en `p6_assets.MAX_REFERENCIAS_ESTILO`.


El video de estilo NO tiene por que ser el video de referencia del proyecto: lo
normal es que sean distintos, porque uno aporta el CONTENIDO y el otro el LOOK.
Usar los fotogramas de un documental de imagen real como referencia de estilo
empuja el dibujo hacia el fotorrealismo, que es lo contrario de lo que se busca.
"""
import os
import shutil
import time

try:
    from . import cli_claude, comun, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas

CARPETA = "estilo"          # dentro del proyecto
SUBCARPETA_FRAMES = "frames"
FICHA = "estilo.json"

#: CUANTOS FOTOGRAMAS SE SACAN DEL VIDEO DE REFERENCIA.
#:
#: Doscientos, y son muchos a proposito. Esto es ffmpeg local: se paga en
#: segundos de maquina, una sola vez por canal, y lo que sale se reutiliza en
#: TODOS los videos de ese canal. Quedarse corto aqui es lo unico que no se
#: puede arreglar despues sin volver a bajar el video.
MAXIMO_FRAMES = 200
ALTURA_MAX = 720            # de referencia de estilo no hace falta 1080


def raiz(proyecto):
    return os.path.join(proyecto.raiz, CARPETA)


# Por debajo de este brillo el fotograma es una transicion o un rotulo sobre
# negro: no sirve como referencia de estilo porque no ensena ni trazo ni paleta.
BRILLO_MINIMO = 0.06
CONTRASTE_MINIMO = 0.05


# --------------------------------------------------------- guia escrita

PASO_GUIA = "guia_estilo"
TIEMPO_BASE_GUIA_S = 300

# La guia se escribe MIRANDO los fotogramas, asi que aqui el CLI SI necesita
# herramientas: sin Read no puede abrir los PNG y describiria de memoria.
HERRAMIENTAS_GUIA = ("Bash", "Write", "Edit", "NotebookEdit", "WebFetch",
                     "WebSearch", "Task", "TodoWrite")

SISTEMA_GUIA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
                "alrededor y sin vallas de markdown.")

#: EL CONTRATO DE SALIDA, compartido por los dos caminos que escriben una
#: guia: mirando fotogramas o leyendo una descripcion. Vive aparte porque es
#: lo unico de los dos prompts que TIENE que decir exactamente lo mismo -- es
#: el esquema que despues leen `guia_escrita` (p6), la paleta del grafismo y
#: el resumen del preset. Con el texto duplicado, anadir una clave en un sitio
#: y no en el otro no da error: da una guia a la que le falta media
#: descripcion, y eso no se ve hasta que se generan las imagenes.
CONTRATO_JSON_GUIA = """\
DEVUELVE SOLO ESTE JSON, sin nada alrededor
{{"guia": "el parrafo que se pega DENTRO del prompt de generacion de imagen. En
INGLES, escrito como instrucciones de dibujo en imperativo, no como analisis. Sin
mencionar los fotogramas, sin la palabra 'reference', sin nombres de series ni de
estudios. Entre 260 y 400 palabras: tiene que caber el trazo, el relleno, la
paleta, la construccion del personaje, la cara, las manos, el fondo, la luz y el
acabado, cada uno con su numero. Denso, sin relleno y sin adjetivos vacios.",
  "paleta": ["#rrggbb", "... de diez a dieciseis, dominantes primero"],
  "trazo": "dos o tres frases en INGLES sobre el contorno: grosor en pixeles o
relativo, color exacto, si modula o es uniforme, si lo llevan tambien los
elementos del fondo y si hay linea interior ademas de la silueta",
  "relleno": "una o dos frases en INGLES sobre como se rellenan las superficies:
color plano o degradado, cuantos tonos por superficie, si hay textura (grano,
papel, trama) y si hay sombreado o ninguno",
  "personajes": "dos o tres frases en INGLES sobre como se construyen: altura en
cabezas, forma de cabeza y cuerpo, cuello, hombros, como se resuelven el pelo y
la ropa, y si todos comparten molde o cada uno tiene rasgos propios",
  "caras": "una o dos frases en INGLES sobre como se resuelve la CARA en este
estilo: con que se rellena la piel (dilo explicitamente, tambien si no lleva
color), ojos, cejas, nariz, boca y orejas, y cuanto detalle tiene respecto al
cuerpo",
  "manos": "una o dos frases en INGLES sobre como se dibujan MANOS, brazos, pies
y zapatos en este estilo, con el NUMERO DE DEDOS dicho con una cifra (o
'mitten-shaped, no separate fingers' si es el caso), su color, si llevan
contorno y su tamano relativo a la cabeza. Si en los fotogramas no se ve ninguna
mano de cerca, escribe exactamente 'no close-up hands visible in the reference'
y no te inventes una convencion",
  "fondos": "dos frases en INGLES: cuanto detalle tienen respecto a los
personajes, como se resuelve la profundidad (capas planas, atmosfera, escala),
si hay perspectiva o es plano, y si el fondo lleva el mismo contorno",
  "luz": "una o dos frases en INGLES sobre luz y sombras: de donde viene, como se
representa la sombra (color propio mas oscuro, multiplicado, o ninguna), si hay
luz de recorte y cuanto contraste",
  "composicion": "una frase en INGLES sobre encuadre, aire y donde cae el
horizonte",
  "acabado": "una frase en INGLES sobre textura, grano y limpieza del render",
  "evitar": "de tres a seis frases en INGLES con lo que NO debe aparecer nunca,
en negativo y concreto, empezando por lo que este generador pone por defecto y
que en ESTE estilo lo rompe (por ejemplo: no skin gradients, no cast shadows, no
eye highlights, no outlines thinner than the character line). LAS MANOS van aqui
las primeras y salen de lo que acabas de escribir en 'manos': si ahi has contado
menos de cinco dedos, o una manopla, escribe 'no realistic five-fingered hands,
no photographic hand anatomy'; si el estilo que estas mirando SI dibuja manos
anatomicas de cinco dedos, NO lo escribas -- estarias prohibiendo el estilo del
video, y nadie mas va a corregirlo. Cada frase tiene que salir de algo que hayas
visto en estos fotogramas: una por linea de riesgo, no una lista generica",
  "resumen_es": "una linea en CASTELLANO que describa este estilo para que una
persona lo reconozca en un desplegable, sin tecnicismos"}}
"""

INSTRUCCION_GUIA = """\
Eres director de arte. Te doy fotogramas de una produccion animada y tienes que
escribir la guia de estilo que permita dibujar planos NUEVOS que parezcan de esa
misma produccion.

Abre y mira estas imagenes (usa la herramienta de lectura de ficheros):
{imagenes}

Estan en la carpeta {carpeta}.

QUE BUSCAR
Lo que TODAS tienen en comun, que es lo unico que define el estilo. Lo que solo
aparece en una es contenido de esa escena, no estilo, y no debe entrar en la
guia. No describas lo que pasa en los fotogramas: describe COMO estan dibujados.

Escribe como quien redacta la biblia de estilo con la que otro dibujante tiene
que producir un plano que encaje sin que se note el cambio de mano. Cada frase
tiene que ser accionable: "outlines are 3-4 px uniform dark brown, never black"
sirve; "clean cartoon look" no dice nada y no debe aparecer.

COMO SE MIRA
Esta guia la va a leer un generador de imagenes que, en todo lo que tu no fijes,
va a poner lo que pone por defecto: manos realistas de cinco dedos, piel con
degradado, sombra proyectada, ojos con brillo. O sea que CADA HUECO QUE DEJES
sale dibujado como no toca. Por eso:

- CUENTA. Numeros, no adjetivos. Cuantos dedos, cuantos tonos de piel, cuantos
  pixeles de contorno, cuantas cabezas de altura. Un numero se puede obedecer;
  "estilizado" no.
- Di lo que NO hay tanto como lo que hay. Que no haya nariz, que no haya sombra,
  que no haya blanco de ojo, son decisiones de estilo igual de fuertes que las
  otras, y las que mas se pierden al redibujar.
- Describe lo que VES en ESTOS fotogramas, no lo que suele llevar un estilo que
  se parezca a este. Si algo no se ve en ninguno, dilo con esas palabras en vez
  de rellenarlo con lo probable: una convencion inventada se propaga a todo el
  video y no hay forma de saber de donde salio.
- No escatimes. Esto se escribe UNA vez por video y lo reciben todas las
  imagenes que se generen. Una guia corta no es una guia limpia, es una guia con
  huecos.

Fijate en, y contesta a todo lo que puedas afirmar mirando:
- el trazo: hay contorno?, de que grosor relativo al plano?, es uniforme o
  modula?, de que color exacto?, lo llevan tambien los elementos del fondo?
- el relleno: plano o con degradado?, hay textura (grano, papel, halftone)?, hay
  sombreado?, es de una sola pasada o tiene medios tonos?
- la paleta: que colores mandan, que temperatura, que saturacion. Da codigos
  hexadecimales aproximados, ORDENADOS del que mas superficie ocupa al que
  menos. Se AMPLIA a proposito: entre diez y dieciseis colores, contando los
  dominantes, los acentos que aparecen poco pero marcan, y los neutros de
  fondo. Una paleta corta y estricta uniformaba todos los planos del video; lo
  que fija el estilo es la FAMILIA de color y el reparto, no un catalogo
  cerrado de cinco tonos. Di tambien cuales son base y cuales acento, y con
  cuanta libertad varia el tono dentro de cada familia (luminosidad y
  saturacion) de un plano a otro.
- los personajes: proporciones (cabezas de altura), forma de la cabeza y del
  cuerpo, como se resuelve el pelo y la ropa.
- LAS MANOS, aparte y con detalle, por la misma razon que la cara: es lo segundo
  que mas canta cuando falla, y el generador tira SIEMPRE a la mano realista de
  cinco dedos si nadie le dice otra cosa. Cuenta los dedos que ves y dilo con un
  numero: hay cuatro?, tres?, es una manopla sin dedos separados?, hay pulgar?
  Di tambien de que color son (del color de la piel, del color de la manga, un
  color plano distinto), si llevan contorno como el resto, si hay linea que
  separe los dedos o solo silueta, el tamano relativo a la cabeza, y como
  terminan los brazos cuando NO hay mano visible. Y lo mismo con los pies y los
  zapatos. Si en estos fotogramas no se ve ninguna mano de cerca, dilo con esas
  palabras en vez de inventarte una convencion.
- LA CARA, aparte y con detalle, sea cual sea el estilo, porque es lo que mas
  canta cuando falla: como se RELLENA la piel en este estilo concreto (un color
  plano, varios tonos, modelado pictorico, degradado, trama, o ningun color), si
  lleva cejas, orejas, nariz, mejillas y como se resuelve cada una, cuanto
  detalle tiene la cara comparada con el resto del cuerpo, y si todos los
  personajes comparten el mismo molde de cara cambiando pelo y ropa o cada uno
  tiene rasgos propios. Describe lo que VES, no lo que sueles ver: si las caras
  no llevan color de piel, dilo; si llevan cinco tonos y sombra pintada, dilo
  igual. Una hoja de personaje se juzga por la cara, y cualquier estilo se
  reconoce por ella antes que por nada.
- los fondos: nivel de detalle comparado con los personajes, como se resuelve la
  profundidad (capas planas, atmosfera, escala), hay perspectiva o es plano.
- la luz: de donde viene, como se representan las sombras (color propio mas
  oscuro, multiplicado, ausente), hay contraste fuerte?, hay luz de recorte?
- la composicion: como se encuadran los planos, cuanto aire dejan, donde cae el
  horizonte, se usan primeros terminos para enmarcar?
- el acabado: se nota la linea de lapiz, el vector limpio, el grano de pelicula,
  la aberracion, el ruido? O esta absolutamente limpio?

""" + CONTRATO_JSON_GUIA


def _llamar_claude(instruccion, modelo, esfuerzo, cwd, avance=None):
    """Se llama asi para que el medidor de coste pueda engancharla por nombre."""
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_GUIA_S,
        sistema=SISTEMA_GUIA, herramientas_vetadas=HERRAMIENTAS_GUIA,
        permisos="acceptEdits", avance=avance,
        para="la guia de estilo")


def generar_guia(proyecto, rutas, modelo=None, esfuerzo=None, avisar=None,
                 proyecto_id=None, peticion="", indicaciones=""):
    """Escribe la guia de estilo mirando los fotogramas elegidos.

    Por que ademas de adjuntar las imagenes
    ---------------------------------------
    Las imagenes van adjuntas en cada llamada de generacion, pero el modelo de
    imagen las interpreta de nuevo cada vez y puede fijarse en cosas distintas.
    Una guia ESCRITA fija lo mismo con palabras y viaja dentro del prompt, asi
    que el estilo queda dicho dos veces por dos caminos: se refuerzan, y lo que
    una pasada podria dejar suelto lo sujeta la otra.

    Los dos textos que la acompanan, y NO son lo mismo
    -------------------------------------------------
        indicaciones   lo que escribio al pedir el canal: «este estilo pero mas
                       frio». Es del ENCARGO y vale para todas las pasadas.
        peticion       la correccion de ESTA pasada: «mas contraste». Va la
                       ULTIMA y con precedencia dicha
                       (`comun.bloque_correccion`), asi que gana si chocan.

    `indicaciones` faltaba en la firma, y no fallaba a medias: fallaba entero.
    El modo light lo pasa desde `_correr_light_guia` --es la forma normal de
    pedir un estilo, con una URL y una frase-- y como la firma no lo recibia el
    paso moria con un TypeError antes de llamar a nadie.
    """
    rutas = validar_seleccion(rutas)
    if len(rutas) < 3:
        raise ValueError("hacen falta al menos 3 fotogramas para escribir una "
                         "guia de estilo: con menos se describe una escena, no "
                         "un estilo")
    # El escalon de ESTA fase, no el general del CLI. Llamada sin ajuste -- desde
    # un script, desde una prueba -- caia en el defecto global y escribia la guia
    # con el modelo mas barato del Estudio, que es justo lo que no se quiere para
    # la unica descripcion en palabras del dibujo del video: pasaba, y se colaba
    # sin que nadie lo viera porque el resultado siempre es una guia plausible.
    por_fase = cli_claude.por_defecto_de(PASO_GUIA)
    modelo = cli_claude.normalizar_modelo(modelo or por_fase["modelo"],
                                          estricto=False)
    esfuerzo = cli_claude.normalizar_esfuerzo(esfuerzo or por_fase["esfuerzo"],
                                              estricto=False)
    ajuste = {"modelo": modelo, "esfuerzo": esfuerzo}

    carpeta = os.path.dirname(rutas[0])
    instruccion = INSTRUCCION_GUIA.format(
        imagenes="\n".join(f"  - {r}" for r in rutas), carpeta=carpeta)
    # Lo que escribio al pedir el canal, si escribio algo. MISMO bloque que en
    # `guia_de_descripcion`: los dos caminos escriben la misma guia, y dos
    # formas de decir «y ademas quiero esto» acabarian separandose.
    indicaciones = " ".join(str(indicaciones or "").split())
    if indicaciones:
        instruccion += BLOQUE_INDICACIONES.format(texto=indicaciones)
    # La correccion va la ULTIMA y con precedencia dicha: ver
    # `comun.bloque_correccion`. Vacia no anade nada.
    instruccion += comun.bloque_correccion(peticion, "la guia de estilo")

    prevision = estadisticas.estimar(PASO_GUIA, tamano=len(rutas), ajuste=ajuste)
    avance = None
    if callable(avisar):
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            f"mirando {len(rutas)} fotogramas con {modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    arranque = time.time()
    try:
        texto, sobre = _llamar_claude(instruccion, modelo, esfuerzo, carpeta,
                                      avance)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO_GUIA, time.time() - arranque, ok=False,
                            ajuste=ajuste, proyecto=proyecto_id,
                            resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    datos = comun.extraer_json(texto, "la guia de estilo")
    guia = " ".join(str(datos.get("guia") or "").split())
    if not guia:
        raise RuntimeError("el modelo no ha devuelto ninguna guia de estilo")

    estadisticas.anotar(PASO_GUIA, segundos, tamano=len(rutas), ajuste=ajuste,
                        proyecto=proyecto_id, unidades=len(rutas),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "fotogramas": len(rutas),
                                 "palabras": len(guia.split()),
                                 "tokens_salida": comun.tokens_de_cli(sobre).get("salida")})

    return _ficha_de_guia(datos, guia, rutas, ajuste, segundos)


def _ficha_de_guia(datos, guia, rutas, ajuste, segundos):
    """La guia tal y como la guardan los params, venga de donde venga.

    La escriben DOS caminos --mirando fotogramas o leyendo una descripcion-- y
    los dos tienen que dejar la MISMA ficha: p6 la lee por claves, el grafismo
    saca de ella la paleta y el preset saca el resumen. Con dos diccionarios
    escritos a mano, el camino nuevo se olvidaria un campo y lo que fallaria es
    una imagen, tres pasos mas abajo.
    """
    # Los campos nuevos (luz, composicion, acabado, resumen_es) salen vacios en
    # una guia escrita antes de que existieran, y todo lo que los consume los
    # trata como opcionales: una guia vieja sigue valiendo exactamente igual.
    return {
        "guia": guia,
        "paleta": [str(c) for c in (datos.get("paleta") or [])][:8],
        "trazo": str(datos.get("trazo") or "").strip(),
        "relleno": str(datos.get("relleno") or "").strip(),
        "personajes": str(datos.get("personajes") or "").strip(),
        # La cara, aparte del resto del personaje: es lo que se juzga en una hoja
        # de reparto y lo que delata un estilo antes que nada. Una guia escrita
        # antes de que existiera este campo lo deja vacio y todo sigue igual.
        "caras": str(datos.get("caras") or "").strip(),
        # Y las manos, por lo mismo y con el mismo peso. Es lo segundo que mas
        # canta cuando falla, y aqui hay un sesgo que no tiene la cara: el
        # generador dibuja manos realistas de cinco dedos MIENTRAS NADIE LE DIGA
        # LO CONTRARIO, asi que en un estilo de manopla o de tres dedos el hueco
        # no sale neutro, sale mal. Un campo con nombre propio es lo unico que
        # obliga a contarlos.
        "manos": str(datos.get("manos") or "").strip(),
        "fondos": str(datos.get("fondos") or "").strip(),
        "luz": str(datos.get("luz") or "").strip(),
        "composicion": str(datos.get("composicion") or "").strip(),
        "acabado": str(datos.get("acabado") or "").strip(),
        "evitar": str(datos.get("evitar") or "").strip(),
        "resumen_es": " ".join(str(datos.get("resumen_es") or "").split()),
        "fotogramas": [os.path.basename(r) for r in rutas],
        "ajuste": ajuste,
        "segundos": round(segundos, 1),
        "palabras": len(guia.split()),
    }


def validar_seleccion(rutas):
    """Comprueba que lo elegido existe de verdad antes de guardarlo.

    Una ruta que no existe se descarta en silencio mas adelante
    (_referencias_estilo la salta), y entonces el paso vuelve a quedarse sin
    referencias y a fallar con el mismo error incomprensible de siempre.
    """
    limpias, faltan = [], []
    for ruta in (rutas or []):
        ruta = str(ruta or "").strip()
        if not ruta:
            continue
        if os.path.exists(ruta):
            limpias.append(os.path.abspath(ruta))
        else:
            faltan.append(ruta)
    if faltan:
        raise ValueError("estas imagenes de estilo no existen en el disco del "
                         "servidor: " + ", ".join(faltan[:5]))
    return limpias


# ------------------------------------------------- la guia SIN video de origen
#
# El modo light acepta un video de YouTube o UNA DESCRIPCION escrita. Con video
# el camino es el de siempre (extraer, elegir, mirar). Con una descripcion no
# hay nada que mirar, y aqui esta la unica forma honesta de resolverlo: se
# escribe la guia a partir de las palabras, y las REFERENCIAS se dibujan
# despues a partir de esa guia (el moodboard). Al reves --dibujar primero y
# escribir la guia mirando lo dibujado-- seria describir una copia, que es justo
# lo que `moodboard` avisa de no hacer nunca.
#
# El CONTRATO de salida es el mismo, letra por letra: lo que cambia es de donde
# sale el material, no lo que se produce.

#: LAS INDICACIONES, cuando ademas del material se escribe algo. Con imagenes
#: delante lo escrito NO es la fuente --las imagenes lo son-- sino lo que hay que
#: hacer con ellas: «igual pero mas frio», «esto pero sin personajes». Por eso va
#: al final y con precedencia dicha, como cualquier correccion de esta casa.
BLOQUE_INDICACIONES = """

Y ADEMAS HA ESCRITO ESTO, que manda sobre lo que veas:
"{texto}"

Aplicalo a la guia. Si contradice a las imagenes, gana lo escrito -- por eso lo
ha escrito. Si lo que pide no se ve en ninguna imagen, escribelo igual: te esta
diciendo en que quiere que se aparte del material.
"""

INSTRUCCION_GUIA_DESCRIPCION = """\
Eres director de arte. Te doy en palabras el estilo visual que quiere un canal y
tienes que escribir la guia de estilo que permita dibujar sus planos.

LO QUE HA PEDIDO EL CANAL, entre comillas y tal cual lo escribio:
"{descripcion}"

QUE HACER CON ESO
Convertirlo en decisiones de dibujo. Lo que ha escrito es una intencion --a
menudo tres o cuatro palabras-- y tu trabajo es concretarla hasta que se pueda
obedecer: donde el ha dicho "estilo comic europeo" tu tienes que decir cuantos
pixeles de contorno, de que color y con cuantos tonos por superficie.

Todo lo que el no haya dicho lo eliges TU, y lo eliges de forma coherente con lo
que si ha dicho. No dejes huecos y no digas que algo queda a criterio de nadie:
esta guia va a ser la unica descripcion del dibujo del canal, y lo que no fije lo
pondra el generador por su cuenta.

Escribe como quien redacta la biblia de estilo con la que otro dibujante tiene
que producir un plano que encaje sin que se note el cambio de mano. Cada frase
tiene que ser accionable: "outlines are 3-4 px uniform dark brown, never black"
sirve; "clean cartoon look" no dice nada y no debe aparecer.

COMO SE MIRA
Esta guia la va a leer un generador de imagenes que, en todo lo que tu no fijes,
va a poner lo que pone por defecto: manos realistas de cinco dedos, piel con
degradado, sombra proyectada, ojos con brillo. O sea que CADA HUECO QUE DEJES
sale dibujado como no toca. Por eso:

- CUENTA. Numeros, no adjetivos. Cuantos dedos, cuantos tonos de piel, cuantos
  pixeles de contorno, cuantas cabezas de altura. Un numero se puede obedecer;
  "estilizado" no.
- Di lo que NO hay tanto como lo que hay. Que no haya nariz, que no haya sombra,
  que no haya blanco de ojo, son decisiones de estilo igual de fuertes que las
  otras, y las que mas se pierden al redibujar.
- No nombres series, estudios, autores ni obras concretas, ni siquiera si el
  canal las ha nombrado: describe el DIBUJO que tendrian, con sus numeros. Un
  nombre propio dentro del prompt de imagen no es una instruccion, es una
  loteria.
- No escatimes. Esto se escribe UNA vez por canal y lo reciben todas las
  imagenes que se generen. Una guia corta no es una guia limpia, es una guia con
  huecos.
- Y no te salgas de lo pedido: si el canal ha dicho "blanco y negro", la paleta
  es de grises; si ha dicho "acuarela", no devuelvas vector plano. Lo que el ha
  fijado manda sobre lo que a ti te parezca que queda mejor.

Decide, y escribe con numeros, todo esto:
- el trazo: hay contorno?, de que grosor relativo al plano?, es uniforme o
  modula?, de que color exacto?, lo llevan tambien los elementos del fondo?
- el relleno: plano o con degradado?, hay textura (grano, papel, halftone)?, hay
  sombreado?, es de una sola pasada o tiene medios tonos?
- la paleta: entre diez y dieciseis colores con codigo hexadecimal, ordenados
  del que mas superficie ocupa al que menos, diciendo cuales son base y cuales
  acento, y con cuanta libertad varia el tono dentro de cada familia de un plano
  a otro. Una paleta corta uniforma todos los planos del video.
- los personajes: proporciones (cabezas de altura), forma de la cabeza y del
  cuerpo, como se resuelven el pelo y la ropa.
- LAS MANOS, aparte y con detalle: cuantos dedos (con una cifra), de que color,
  si llevan contorno, su tamano relativo a la cabeza y como terminan los brazos
  cuando no hay mano visible. Es lo segundo que mas canta cuando falla y el
  generador tira SIEMPRE a la mano realista de cinco dedos si nadie le dice otra
  cosa.
- LA CARA, aparte y con detalle: con que se rellena la piel, si lleva cejas,
  orejas, nariz y mejillas y como se resuelve cada una, y cuanto detalle tiene
  comparada con el resto del cuerpo.
- los fondos: cuanto detalle respecto a los personajes y como se resuelve la
  profundidad.
- la luz: de donde viene, como se representan las sombras, cuanto contraste.
- la composicion: como se encuadran los planos y cuanto aire dejan.
- el acabado: grano, limpieza, textura del render.

""" + CONTRATO_JSON_GUIA


def guia_de_descripcion(proyecto, descripcion, modelo=None, esfuerzo=None,
                        avisar=None, proyecto_id=None, peticion="", rutas=None):
    """Escribe la guia de estilo sin un video delante. -> ficha de guia

    Mismo contrato de salida que `generar_guia`, y a proposito: lo que cambia es
    de donde sale el material. Tres combinaciones, y hace falta AL MENOS UNA de
    las dos entradas:

        imagenes y texto   las imagenes son el material y el texto dice que
                           hacer con el («esto pero mas frio»). Es lo que manda
                           el modo light desde el 24-08.
        solo imagenes      se escribe mirandolas, igual que con los fotogramas
                           de un video.
        solo texto         se escribe de la nada. Sigue valiendo --lo usa quien
                           llame por API-- pero es el peor material: la guia se
                           inventa todo lo que el parrafo no diga, que es casi
                           todo. Por eso el modo light ya no lo ofrece.

    Y CAMBIA LA LLAMADA: sin imagenes se le vetan las herramientas de lectura
    --no hay ningun fichero que abrir y dejarselas seria invitarle a rebuscar
    por el disco-- y con imagenes hace falta justamente eso, igual que en el
    camino del video.
    """
    rutas = [r for r in (rutas or []) if os.path.exists(r)]
    descripcion = " ".join(str(descripcion or "").split())
    if not rutas and len(descripcion) < 8:
        raise ValueError("para escribir la guia hace falta material: adjunta "
                         "alguna imagen, o describe el estilo grafico con algo "
                         "mas de detalle (con dos palabras se lo inventa todo)")

    por_fase = cli_claude.por_defecto_de(PASO_GUIA)
    modelo = cli_claude.normalizar_modelo(modelo or por_fase["modelo"],
                                          estricto=False)
    esfuerzo = cli_claude.normalizar_esfuerzo(esfuerzo or por_fase["esfuerzo"],
                                              estricto=False)
    ajuste = {"modelo": modelo, "esfuerzo": esfuerzo}

    if rutas:
        # LA MISMA INSTRUCCION QUE CON UN VIDEO, y no es un atajo: el encargo es
        # identico --mira estas imagenes y escribe como se dibuja lo que sale en
        # ellas-- y lo unico que cambia es de donde salieron. Dos instrucciones
        # para lo mismo acaban separandose.
        # La lista se arma fuera del format(): un join con salto de linea dentro
        # de la llamada se lee fatal y ya se colo roto una vez.
        lista = "\n".join(f"  - {r}" for r in rutas)
        instruccion = INSTRUCCION_GUIA.format(
            imagenes=lista, carpeta=os.path.dirname(rutas[0]))
        if descripcion:
            instruccion += BLOQUE_INDICACIONES.format(texto=descripcion)
    else:
        instruccion = INSTRUCCION_GUIA_DESCRIPCION.format(descripcion=descripcion)
    instruccion += comun.bloque_correccion(peticion, "la guia de estilo")
    carpeta = os.path.dirname(rutas[0]) if rutas else raiz(proyecto)
    os.makedirs(carpeta, exist_ok=True)

    prevision = estadisticas.estimar(PASO_GUIA, tamano=len(rutas), ajuste=ajuste)
    avance = None
    if callable(avisar):
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            "escribiendo la guia a partir de tu descripcion"
            + (f" y {len(rutas)} imagenes de apoyo" if rutas else "")
            + f" con {modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    arranque = time.time()
    try:
        # Con imagenes adjuntas hace falta que pueda ABRIRLAS, igual que en el
        # camino del video. Sin ellas no hay ningun fichero que abrir y se le
        # vetan las herramientas de lectura: dejarselas seria invitarle a buscar
        # imagenes por el disco.
        llamar = _llamar_claude if rutas else _llamar_claude_sin_ficheros
        texto, sobre = llamar(instruccion, modelo, esfuerzo, carpeta, avance)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO_GUIA, time.time() - arranque, ok=False,
                            ajuste=ajuste, proyecto=proyecto_id,
                            resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    datos = comun.extraer_json(texto, "la guia de estilo")
    guia = " ".join(str(datos.get("guia") or "").split())
    if not guia:
        raise RuntimeError("el modelo no ha devuelto ninguna guia de estilo")

    estadisticas.anotar(PASO_GUIA, segundos, tamano=len(rutas), ajuste=ajuste,
                        proyecto=proyecto_id, unidades=len(rutas),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "fotogramas": len(rutas), "de_descripcion": True,
                                 "palabras": len(guia.split()),
                                 "tokens_salida":
                                     comun.tokens_de_cli(sobre).get("salida")})

    ficha_guia = _ficha_de_guia(datos, guia, rutas, ajuste, segundos)
    ficha_guia["descripcion"] = descripcion
    return ficha_guia


def _llamar_claude_sin_ficheros(instruccion, modelo, esfuerzo, cwd, avance=None):
    """Como `_llamar_claude` pero sin dejarle abrir nada del disco."""
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        base_tiempo_s=TIEMPO_BASE_GUIA_S, sistema=SISTEMA_GUIA,
        herramientas_vetadas=HERRAMIENTAS_GUIA + ("Read", "Glob", "Grep"),
        extra=["--no-session-persistence"], avance=avance,
        para="la guia de estilo")


# ----------------------------------------------------- elegir los fotogramas
#
# ELEGIR ERA DEL USUARIO, Y AQUI DEJA DE SERLO PARA EL MODO LIGHT.
#
# La cabecera de este modulo dice --y sigue siendo verdad-- que elegir a ojo con
# los DETECTORES del motor de ingesta no funciona con dibujo plano: el de caras
# devuelve casi cero y el de texto marca paisajes limpios. Eso se midio sobre
# 120 fotogramas y no ha cambiado.
#
# Lo que ha cambiado es que ahora hay OTRA forma de mirar: el CLI abre imagenes.
# No es un detector de rasgos, es alguien que ve el fotograma y sabe para que se
# va a usar. Va por suscripcion, asi que mirar no cuesta dinero.
#
# Se le dan CONTACTOS numerados y no los 200 ficheros sueltos: abrir doscientas
# imagenes de una en una son doscientas herramientas y varios minutos, y para
# decidir "esta si, esta no" con una rejilla basta. La eleccion FINA --que
# fotograma va en la lamina-- ya la hace despues el moodboard, que si mira los
# elegidos a tamano completo.

PASO_ELECCION = "estilo_eleccion"
TIEMPO_BASE_ELECCION_S = 240

#: Cuantos fotogramas por hoja de contactos. Con 24 cada celda queda a ~320x180
#: en una hoja de 1920x1080: se distingue el trazo, la paleta y si hay una cara,
#: que es todo lo que hay que decidir aqui.
POR_CONTACTO = 24

INSTRUCCION_ELECCION = """\
Eres director de arte y estas eligiendo los fotogramas de referencia con los que
se va a definir el estilo grafico de un canal de video.

Abre y mira estas hojas de contactos (usa la herramienta de lectura de ficheros):
{hojas}

Cada hoja lleva {por_hoja} fotogramas en cuadricula, y cada uno lleva su NUMERO
escrito en la esquina. Los numeros son continuos entre hojas.

PARA QUE SIRVEN LOS QUE ELIJAS
Dos cosas, y las dos importan:
  1. escribir la guia de estilo, que se redacta MIRANDOLOS a tamano completo;
  2. dibujar las laminas de referencia que despues viajan en cada imagen.
O sea que lo que buscas no es el fotograma mas bonito: es el que mejor ENSENA
como se dibuja en esta produccion.

QUE ELEGIR
- variedad de SITUACION, que es lo que hace que lo unico en comun sea el estilo:
  caras de cerca, cuerpos enteros, dos o mas personajes juntos, interiores,
  exteriores, objetos, y algun plano general.
- fotogramas LIMPIOS y bien expuestos, con el dibujo claro y grande.
- si hay manos visibles de cerca, mete al menos uno: es lo que peor se resuelve
  solo y lo que la guia mas necesita poder contar.

QUE NO ELEGIR
- fotogramas con TEXTO grande, rotulos, logotipos o creditos encima.
- transiciones, fundidos, desenfoques y cualquiera que este a medio cambio.
- imagen real o fotografia si el resto es dibujo (y al reves).
- dos fotogramas casi iguales: uno de los dos no anade nada y ocupa el sitio de
  una situacion que falta.

DEVUELVE SOLO ESTE JSON, sin nada alrededor
{{"elegidos": [numeros de los {cuantas} fotogramas elegidos, del mejor al peor,
exactamente {cuantas} numeros y sin repetir],
  "por_que": "una linea en CASTELLANO diciendo que criterio has seguido"}}
"""


