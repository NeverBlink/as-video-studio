"""Catalogo visual del video: quien sale, donde ocurre y con que tono.

QUE PROBLEMA RESUELVE
---------------------
`p6_assets.planificar()` reparte sets, encuadres y reparto leyendo un `catalogo`.
Toda esa maquinaria existe y esta probada (42 comprobaciones: 44 planos, 44
encuadres distintos, cero repeticiones)... pero NADIE producia el catalogo. Las
suites lo escriben a mano en `guion.json`; en un proyecto de verdad llegaba
vacio, y entonces:

  - `_asignar_sets` deja `set=None` en todos los planos,
  - `_asignar_camaras` empieza con `if not escena.get("set"): continue`, o sea
    que no se ejecuta NI UNA vez y no hay variacion de angulo,
  - `_elegir_personajes` no tiene reparto, asi que no se genera ninguna hoja de
    personaje y cada plano se inventa la cara,
  - `_prompt_visual` se queda en la frase narrada, sin lugar ni encuadre.

Con el prompt asi de vacio, lo unico concreto que le llegaba al modelo eran las
dos imagenes del plano anterior, y devolvia el plano anterior con un cambio
pequeno: la misma persona en la misma posicion, ahora saltando. Ese era el
sintoma; esto es la causa.

POR QUE VIVE EN ASSETS Y NO EN EL GUION
---------------------------------------
Regla de la casa: el paso donde se guarda una decision es aquel cuya salida
cambia. Cambiar como es un personaje cambia las IMAGENES, no el texto ni la voz.
Si el catalogo fuera del guion, retocar el pelo de alguien obligaria a reescribir
el guion y a REGRABAR la voz, y eso se paga. Por eso se aprueba aqui y se guarda
en `params.catalogo` de assets, que ya es un parametro legitimo del paso.

PROPONER NO ES APROBAR
----------------------
Esto devuelve una propuesta. Lo que entra en los params es lo que una persona
aprueba.
"""
import os
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from . import cli_claude, comun, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas

PASO = "catalogo_visual"

MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]
TIEMPO_BASE_S = 420

SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor, sin vallas de markdown y sin usar herramientas.")

HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")

# Tope de planos seguidos en el mismo sitio. No es un capricho: cada plano lleva
# el anterior como referencia, asi que encadenar muchos en el mismo set es lo que
# hace que la escena se repita con un cambio pequeno. El planificador ya penaliza
# a partir del tercero; aqui se le pide al agente que reparta desde el principio.
#
# Bajado de 3 a 2 el 16-08. Un guion documental de dos minutos condensa una
# docena de acontecimientos -- una fecha, una empresa, un robo, un juicio -- y
# salian cuatro sitios para todo el video: doce planos repartidos de tres en
# tres. Con dos, cada giro del relato tiene su sitio, que es lo que hace que un
# documental no parezca rodado en un pasillo.
PLANOS_POR_SET = 2

# Palabras por segundo de una narracion documental. Solo sirve para saber
# CUANTOS planos van a salir antes de que exista el audio con el que medirlo de
# verdad; el mismo numero, y por lo mismo, esta en `conservar._cadencia_de`.
PALABRAS_POR_SEGUNDO = 2.4


def planos_previstos(bloques, min_s, max_s):
    """Cuantos planos va a cortar assets de este guion. Estimado, no medido.

    No es un adorno del prompt: es lo unico que convierte PLANOS_POR_SET en un
    numero de SITIOS. Al catalogo se le pedian «dos planos por sitio» con una
    constante, pero cuantos planos hay lo decide min_s/max_s, que se elige en
    otra tarjeta y que este paso no veia. Con planos de 1-4 s salen unos 48
    planos sobre los 9 sitios que se proponian: casi cinco por sitio en vez de
    dos, y de ahi vienen los encuadres repetidos. Nadie puede repartir de dos en
    dos sin saber entre cuantos.

    Aqui todavia no hay audio -- el catalogo se pide con el guion recien escrito
    -- asi que la duracion se estima por palabras. Sobra precision: lo que se
    hace con esto es pedir un minimo de sitios, no cuadrar un montaje.
    """
    palabras = sum(comun.contar_palabras(b.get("texto", ""))
                   for b in bloques or [])
    if not palabras:
        return 0
    medio = max(0.5, (float(min_s) + float(max_s)) / 2.0)
    return max(1, round(palabras / PALABRAS_POR_SEGUNDO / medio))


# Se le dice al agente cuantos planos van a salir y, de ahi, cuantos sitios
# necesita COMO MINIMO. Sin esto, "dos planos por sitio" era una intencion sin
# aritmetica: proponia nueve sitios para cuarenta y ocho planos y el reparto los
# apilaba de cinco en cinco. Va con su cuenta hecha a proposito -- pedirle que
# divida es pedirle que se equivoque.
CUANTOS_PLANOS = """
  - ESTE video se corta en unos {planos} planos, de {min_s:.0f}-{max_s:.0f} s cada uno.
    A {planos_por_set} planos por sitio, salen {sitios} sitios COMO MINIMO.
    Cuentalos antes de contestar: con menos, los planos se apilan en el mismo
    sitio y acaban siendo el anterior con un retoque, que es exactamente lo que
    este catalogo existe para impedir."""

CRITERIO = """
COMO SE DECIDE
Un video de animacion narrada se lee bien cuando cada frase tiene su imagen y
esa imagen NO es la anterior con un retoque. Tu trabajo es dar el andamiaje para
que eso sea posible: quien sale, donde ocurre cada tramo y con que tono.

REPARTO — lo mas importante
Cada persona que aparezca MAS DE UNA VEZ en el guion va en el reparto con un
identificador estable y una descripcion fisica cerrada. De esa descripcion se
dibuja una hoja de personaje que se adjunta despues a cada plano donde sale, y
es lo unico que impide que la misma persona cambie de cara, de pelo y de ropa
entre un plano y el siguiente.

  - El identificador es en minusculas y sin acentos: 'udai', 'saddam', 'qusay'.
  - UNA ENTRADA POR ACTOR DEL RELATO, y esto es lo que mas se rompe. Si el guion
    llama a la misma gente de dos formas -- primero «los atacantes» y despues
    por su nombre propio, o primero por su nombre y despues «el grupo» --, eso
    es UNA entrada, no dos. Dos entradas son dos hojas, y dos hojas son dos
    disenos: el espectador ve dos personajes distintos donde el relato tiene
    uno. Antes de anadir a alguien, mira si ya lo tienes con otro nombre.
  - La descripcion es FISICA y permanente: edad aparente, complexion, pelo,
    vello facial, ropa habitual. Nada de estados de animo ni de acciones, y nada
    de DONDE esta ni de COMO esta iluminado. Con esa frase se dibuja la hoja
    sobre un fondo vacio, asi que «sentados frente a sus pantallas» pinta las
    mesas dentro de la hoja, y «con la cara medio oculta por el brillo del
    monitor» -- sin ningun monitor ahi que lo emita-- acaba dibujado como una
    placa blanca tapandoles los ojos. Una hoja sin cara no fija ninguna cara.
  - SI EL GUION NO LO DESCRIBE, INVENTATELO. Y no es una licencia: es la regla.
    Casi ningun guion documental describe fisicamente a nadie -- dice
    «Nubla», «un empleado», «el investigador» y sigue --, asi que si la
    falta de descripcion fuera motivo para dejarlo fuera, el reparto saldria
    vacio en casi todos los videos. Y un reparto vacio NO significa que no salga
    nadie: significa que no hay hoja de personaje, y entonces CADA PLANO se
    inventa la cara por su cuenta. Una cara inventada una vez y repetida en los
    cuarenta y ocho planos es un personaje; cuarenta y ocho caras inventadas por
    separado no son nadie.
    Inventa lo justo y coherente con lo que SI dice el guion: la epoca, el sitio,
    el oficio, la edad que se deduzca. Sin nombres de personas reales concretas
    -- si el guion nombra a alguien que existe, describelo por su oficio y su
    edad aparente, no por su parecido --, y sin rasgos que el guion contradiga.
    Y ponlo en 'avisos': «se invento la descripcion de X, el guion no la da», que
    es lo que permite corregirla mirando en vez de descubrirla en el video.
  - Si el mismo personaje aparece en dos edades muy distintas (de nino y de
    adulto) son DOS entradas: 'udai_nino' y 'udai'. Dibujar a un nino con la
    hoja del adulto es exactamente el fallo que produce que el hijo aparezca
    donde deberia estar el padre.
  - 'palabras' son las formas con las que el guion se refiere a el, para poder
    reconocerlo en cada frase: nombre, apellido, apodos y perifrasis.
  - Los grupos anonimos (invitados, guardias, multitud) tambien valen, con
    grupo=true. Su descripcion sigue la MISMA regla, y ademas dice como es cada
    miembro uno por uno -- pelo, piel, complexion y ropa de cada uno --, porque la
    hoja tiene que dibujarlos distinguibles entre si: si describes al grupo en
    bloque, en los planos sale el mismo diseno repetido.

SETS — donde ocurre
Un set es un LUGAR, no un plano. Agrupa el guion en los sitios donde de verdad
pasan las cosas, y cambia de sitio cuando el relato cambia de sitio: si el guion
deja de hablar de la fiesta y pasa a la infancia del personaje, eso ya no ocurre
en el mismo salon. Arrastrar el set anterior es lo que deja escenas de infancia
rodadas en el garaje del plano de antes.

  - Apunta a tramos de {planos_por_set} planos como mucho por sitio seguido.{cuantos_planos}
  - SE GENEROSO CON LOS SITIOS. Un documental cambia de sitio constantemente, y
    quedarse corto es el fallo caro: dos sitios para doce planos son doce
    variaciones de la misma habitacion. Si dudas entre meter un tramo en el
    sitio anterior o abrir uno nuevo, abre uno nuevo. Un sitio de mas no cuesta
    nada; un sitio de menos son cuatro planos que se parecen entre si en el
    video terminado.

  - CADA VEZ QUE EL GUION SITUA, ESO ES UN SITIO. Un documental abre cada tramo
    diciendo donde y cuando: «Madrid, mayo de dos mil veinticuatro», «la sede
    del banco», «un juzgado de Nueva York». Esas frases NO se ilustran con el
    interior de la escena siguiente -- piden su propio plano de establecimiento,
    que es lo que orienta al espectador antes de meterlo dentro. Vista aerea de
    la ciudad, fachada del edificio, exterior de la institucion. Dale su set y
    su 'rotulo'.

  - Lo mismo con lo que el guion nombra y no se ve: una empresa, un servidor,
    un foro donde se vende algo robado, un pais al que llegan los datos. Si el
    relato se va ahi aunque sea una frase, eso ocurre en otro sitio.

  - CADA SITIO QUE DECLARES TIENE QUE USARLO ALGUN TRAMO, y cada tramo tiene que
    decir en que sitio ocurre. Son las dos caras de lo mismo y es una regla dura,
    no un consejo: el sitio de un plano lo fija su TRAMO, asi que un sitio que
    ningun tramo nombra no lo puede elegir nadie -- se escribe, se guarda, se
    pinta en la pantalla y no sale en el video. Paso de verdad: 31 sitios
    declarados, 12 usados, 19 que no existian para nadie, y entre ellos la
    fachada del banco del que iba el video.
    Antes de contestar, cruza las dos listas: todo id de 'sets' tiene que
    aparecer en el 'set' de algun tramo. Si un sitio no encaja en ningun tramo,
    no lo declares; si un tramo se queda sin sitio, dale uno.

  - 'luz' fija la hora del dia y la fuente de luz, que es obligatorio en todo
    prompt: 'noche, lamparas calidas de interior' o 'dia, sol duro de ventana'.

  - 'descripcion' es lo que hace que dos planos del mismo sitio PAREZCAN el
    mismo sitio: di como es el lugar en una frase -- que se ve, de que esta
    hecho, que lo distingue --, no que pasa en el. Entra literal en el prompt de
    todos los planos rodados ahi, asi que es lo unico que sostiene el
    reconocimiento del lugar.

REALES — lo que existe de verdad y hay que enseñar, no imaginar
Un documental habla de cosas que existen: una empresa, un edificio, una ciudad,
un modelo de avion, una persona publica. Si nadie dice cuales son, el generador
dibuja lo que se imagina que es eso -- un banco generico con un logo inventado, un
edificio con forma de edificio-- y el espectador que conoce la cosa ve que no es.

Aqui listas esas cosas para que se les busque una imagen real en Wikimedia
Commons y se le adjunte al plano que las nombra.

  - Entran las que un espectador podria RECONOCER: marcas y empresas (tipo
    'logo'), edificios y ciudades identificables (tipo 'lugar'), objetos con
    forma propia -- un modelo concreto de avion, de coche, de arma-- (tipo
    'objeto') y personas publicas de verdad (tipo 'persona').
  - NO entran los personajes del reparto: esos ya tienen su hoja, y una foto
    real compitiendo con la hoja rompe justo lo que la hoja fija. Si alguien es
    a la vez publico y del reparto, va SOLO al reparto.
  - NO entran las cosas genericas: 'un banco', 'un ordenador', 'una carretera'.
    Si no tiene nombre propio, no hay nada real que ensenar.
  - 'buscar' es como se llama en Commons, EN INGLES y sin ambiguedad. Commons es
    un archivo internacional: «Aurora» devuelve la ciudad, «Sede Central»
    el banco. Si el nombre es ambiguo, desambigualo tu.
  - 'palabras' son las formas con las que el guion la nombra, EN EL IDIOMA DEL
    GUION, porque es lo que se cruza con cada frase para saber en que plano
    adjuntarla.
  - Se generoso pero no exhaustivo: entre cinco y quince. Cada una se baja una
    vez y se guarda, pero solo se adjunta al plano que la nombra.

COMPONENTES — cuando lo que hay que ensenar es un MAPA
Hay tramos que no se resuelven dibujando un sitio. Cuando la narracion describe
un recorrido entre dos puntos del mundo, una distancia o una procedencia, lo que
se ve tiene que ser un mapa de verdad, no una ilustracion de un mapa: se dibuja
con geometria real (Natural Earth) y sale mucho mejor que cualquier dibujo.

  - Solo hay estas regiones dibujables: {regiones_mapa}. Si tu recorrido no cabe
    entero en una de ellas, no pongas el componente.
  - 'origen' y 'destino' llevan coordenadas [latitud, longitud] de verdad. Una
    coordenada inventada dibuja una flecha que sale del mar.
  - 'palabras' son las del guion que piden ese mapa. Un componente solo gana el
    plano si el texto lo pide claramente, asi que se especifico: 'ruta',
    'kilometros', 'zarpo de', el nombre de los dos puntos.
  - Como mucho dos o tres en un video. Un mapa cada poco deja de decir nada.

LUGARES — el rotulo que situa
Sitios que la narracion nombra y conviene rotular en pantalla cuando se
mencionan ('manzanillo' -> 'PUERTO DE MANZANILLO'). Es distinto del 'rotulo' del
set, que sale al ENTRAR en el sitio: esto sale cuando se NOMBRA, este donde
este el plano. Solo nombres propios de sitio, y solo los que importen.

CAPITULOS — donde el video cambia de asunto
Si el guion tiene partes claras, marca el bloque donde arranca cada una con su
titulo. Sale como cabecera a pantalla completa. Tres o cuatro en un video, no
uno cada dos minutos; y si el guion es un relato continuo, ninguno.

BEATS — el guion en su contexto
Un beat es un TRAMO de bloques consecutivos que comparten sitio, reparto y tono.
Aqui es donde se lee el guion entero y no frase a frase: 'desde' y 'hasta' son
ids de bloque, y todo lo que caiga dentro hereda ese set, ese reparto y ese tono.
Cubre el guion ENTERO, sin huecos y sin solaparte.

  - 'tono' importa mas de lo que parece. Por defecto los personajes se dibujan
    serios, con la sonrisa prohibida en el negativo del prompt; la unica forma
    de que en una fiesta la gente sonria es que el beat diga que el tono es
    alegre. Los tonos son: alegre, neutro, tenso, triste, solemne.
  - 'accion' es lo que se VE en ese tramo, en una linea, y es una IDEA VISUAL
    propia: dos tramos seguidos no pueden compartirla, aunque compartan sitio.
    Cuando la narracion se pone abstracta -- una cifra, una comparacion, un
    concepto -- no la ilustres con una vista del sitio: pon en escena algo
    concreto que la CUENTE. «Cuestan lo que un piso en Madrid» no es un plano
    del foro donde se venden los datos: es el ladron viviendo a cuerpo de rey
    en ese piso. Esa escenificacion es lo que mantiene el video dinamico justo
    donde el guion deja de describir cosas visibles.
  - Y AL ESCENIFICAR, EL SENTIDO LO FIJA EL RELATO. Si el tramo usa una palabra
    que significa una cosa en la calle y otra en el mundo de este video
    --proveedor, llave, puente, red, cadena, firma, mina--, la accion dice en
    cual va. Paso de verdad: un tramo sobre los proveedores de servicios de una
    empresa salio con furgonetas en un almacen.

  - 'personajes' DE UN BEAT ES QUIEN ESTA FISICAMENTE AHI, no de quien se habla.
    Es la regla que mas cara sale de todas y no se nota hasta ver el video
    montado: la descripcion de cada personaje viaja al modelo de imagen Y su
    hoja va adjunta como referencia, asi que a quien pongas en un beat, sale
    DIBUJADO en sus planos. Dos cosas que ya pasaron:

      · un tramo sobre unos investigadores buscando al atacante llevaba en el
        reparto a los investigadores Y al atacante, y el plano salio con el
        atacante de pie dentro de la oficina que lo estaba buscando;
      · un tramo sobre una persona corriente afectada llevaba en el reparto al
        atacante --porque la frase lo nombraba--, y la victima salio con su cara.

    Asi que: de alguien se puede HABLAR sin que este en la habitacion. Y si un
    tramo necesita a alguien generico (una persona cualquiera, un cliente, un
    empleado sin nombre), NO pongas a nadie del reparto: dejalo vacio y que lo
    dibuje generico.

  - DOS BANDOS NO COMPARTEN BEAT salvo que el relato diga que se encontraron.
    Quien ataca y quien investiga estan en sitios distintos: son dos beats.
"""

INSTRUCCION = """Eres el director de arte de un video de animacion narrada.
Lee el guion ENTERO y devuelve su catalogo visual.

TITULO: {titulo}
TEMA: {tema}
{peticion}
{fijos}
{especie}
{criterio}

GUION COMPLETO, BLOQUE A BLOQUE
<<<
{guion}
>>>

DEVUELVE EXACTAMENTE ESTE JSON, sin nada alrededor:

{{
  "reparto": {{
    "<id>": {{
      "nombre": "<como se rotula EN PANTALLA: 'Udai Hussein'>",
      "papel": "<quien es, 3-5 palabras: 'el hijo mayor de Saddam'>",
      "descripcion": "<descripcion fisica permanente, en ingles>",
      "palabras": ["<como lo llama el guion>", "..."],
      "grupo": false
    }}
  }},
  "sets": {{
    "<id>": {{
      "rotulo": "<cabecera de sitio y hora al entrar: 'Bagdad, 23:39'. Vacio si el guion no da sitio ni hora>",
      "descripcion": "<que sitio es, en ingles>",
      "palabras": ["<palabras del guion que lo delatan>", "..."],
      "luz": "<hora del dia y fuente de luz, en ingles>"
    }}
  }},
  "componentes": {{
    "<id del mapa: 'mapa_ruta'>": {{
      "tipo": "mapa",
      "palabras": ["<palabras del guion que piden este mapa>", "..."],
      "config": {{
        "region": "<una de las regiones dibujables>",
        "origen": {{"nombre": "<ROTULO>", "coord": [<lat>, <lon>]}},
        "destino": {{"nombre": "<ROTULO>", "coord": [<lat>, <lon>]}}
      }}
    }}
  }},
  "lugares": {{
    "<palabra del guion>": "<ROTULO EN PANTALLA>"
  }},
  "reales": [
    {{
      "id": "<identificador: 'sede_central', 'pentagono', 'boeing_737'>",
      "tipo": "logo|lugar|objeto|persona",
      "buscar": "<como se llama en Wikimedia Commons, EN INGLES y sin ambiguedad: 'Sede Central', 'The Pentagon', 'Boeing 737-800'>",
      "que_es": "<que es, en ingles y en pocas palabras: 'the bank', 'the building'>",
      "palabras": ["<como lo nombra el guion, EN SU IDIOMA>", "..."]
    }}
  ],
  "capitulos": {{
    "<id de bloque donde abre el capitulo>": {{
      "titulo": "<titulo del capitulo>",
      "subtitulo": "<opcional>"
    }}
  }},
  "beats": [
    {{
      "desde": "<id de bloque>",
      "hasta": "<id de bloque>",
      "set": "<id de set>",
      "personajes": ["<id de reparto>", "..."],
      "tono": "alegre|neutro|tenso|triste|solemne",
      "accion": "<que se ve en este tramo, una linea>"
    }}
  ],
  "avisos": ["<lo que no has podido resolver, si algo>"]
}}

Las descripciones van EN INGLES porque alimentan a un generador de imagen. Los
identificadores, en minusculas, sin acentos y sin espacios.
"""

PETICION = """
LO QUE TE PIDE EL EDITOR
Va por delante del criterio general. No cambia las reglas duras.
<<<
{texto}
>>>
"""

#: El motor de mapas solo sabe encuadrar unas regiones concretas, y se leen de
#: el por lo mismo que los sets: una region inventada revienta con KeyError
#: dentro de mapa.construir, o sea a mitad de la generacion y con dinero gastado.
#: LA CARPETA DE MOTORES SE PUEDE MOVER (`ESTUDIO_MOTORES`), asi que la ruta se
#: arma con la misma regla que `medios.MOTORES` y no contando carpetas hacia
#: arriba: eso ultimo se equivoca en silencio --`regiones_de_mapa` devuelve
#: lista vacia si no encuentra el fichero-- y el sintoma es que TODA region se
#: descarta por «no dibujable», que no se parece nada a la causa.
RUTA_MAPA = os.path.join(
    os.environ.get("ESTUDIO_MOTORES")
    or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "motores"),
    "capa_vectorial", "mapa.py")


def regiones_de_mapa(ruta=None):
    """Regiones que el motor de mapas sabe dibujar."""
    import ast
    ruta = ruta or RUTA_MAPA
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            arbol = ast.parse(fh.read())
    except (OSError, SyntaxError):
        return []
    for nodo in arbol.body:
        if not isinstance(nodo, ast.Assign):
            continue
        if not any(isinstance(d, ast.Name) and d.id == "REGIONES"
                   for d in nodo.targets):
            continue
        if isinstance(nodo.value, ast.Dict):
            return [c.value for c in nodo.value.keys
                    if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    return []


def _coordenada(crudo):
    """[lat, lon] de verdad, o None. Una coordenada inventada dibuja en el mar."""
    if not isinstance(crudo, (list, tuple)) or len(crudo) != 2:
        return None
    try:
        lat, lon = float(crudo[0]), float(crudo[1])
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        return None
    return [lat, lon]


def _limpiar_componentes(crudos, regiones, avisos):
    """Mapas y graficos que se pueden dibujar de verdad. Lo demas, fuera.

    Aqui no vale degradar: `mapa.construir` indexa REGIONES sin red y un
    componente mal formado tumbaria el paso de assets a mitad, despues de haber
    pagado las imagenes anteriores.
    """
    limpios = {}
    for crudo, ficha in (crudos or {}).items():
        nombre = _identificador(crudo)
        if not nombre or not isinstance(ficha, dict):
            continue
        config = ficha.get("config") if isinstance(ficha.get("config"), dict) else {}
        region = str(config.get("region") or "").strip().lower()
        if region not in regiones:
            avisos.append(f"componente '{nombre}': la region "
                          f"'{region or '(vacia)'}' no se puede dibujar "
                          f"({', '.join(regiones) or 'ninguna'}), se descarta")
            continue
        puntos, fallo = {}, False
        for extremo in ("origen", "destino"):
            punto = config.get(extremo)
            if not isinstance(punto, dict):
                continue
            coord = _coordenada(punto.get("coord"))
            if coord is None:
                avisos.append(f"componente '{nombre}': el {extremo} no trae unas "
                              f"coordenadas [lat, lon] validas, se descarta")
                fallo = True
                break
            puntos[extremo] = {"nombre": str(punto.get("nombre") or "").strip().upper()
                                         or extremo.upper(),
                               "coord": coord}
        if fallo:
            continue
        if len(puntos) == 1:
            avisos.append(f"componente '{nombre}': un recorrido necesita origen Y "
                          f"destino; solo trae uno, se descarta")
            continue
        limpios[nombre] = {
            "tipo": "mapa" if str(ficha.get("tipo") or "mapa") == "mapa" else "grafico",
            "palabras": _lista_de_palabras(ficha.get("palabras"), nombre),
            "config": {"region": region, **puntos},
            "descripcion": str(ficha.get("descripcion") or "").strip(),
        }
    return limpios


#: Lo que puede ser una cosa real. Cerrado a proposito: `wikimedia.TIPOS` decide
#: como buscar cada uno, y un tipo que no este ahi se buscaria como 'objeto' sin
#: que nadie lo dijera.
TIPOS_REALES = ("logo", "lugar", "objeto", "persona")


def _limpiar_reales(crudos, reparto, avisos):
    """Las cosas del mundo real que se pueden buscar de verdad. Lo demas, fuera.

    Se cae lo que no sirve, y con aviso, porque cada una de estas cosas cuesta
    una busqueda contra un archivo de terceros y una imagen adjunta al prompt:

      - sin 'buscar' no hay nada que consultar en Commons;
      - sin 'palabras' no se puede saber en QUE plano adjuntarla, asi que se
        bajaria para no usarse nunca;
      - y si es alguien del REPARTO se descarta siempre: ese personaje ya tiene
        su hoja, que existe justamente para fijar como es, y una foto real al
        lado compite con ella y la rompe. Es el mismo motivo por el que la
        referencia de continuidad no se coge de otro sitio.
    """
    limpias, vistos = [], set()
    for ficha in (crudos or []):
        if not isinstance(ficha, dict):
            continue
        nombre = _identificador(ficha.get("id"))
        buscar = " ".join(str(ficha.get("buscar") or "").split())
        palabras = [str(p).strip() for p in (ficha.get("palabras") or [])
                    if str(p).strip()]
        if not nombre or not buscar:
            avisos.append(f"real '{nombre or ficha.get('buscar') or '(sin id)'}': "
                          f"sin id o sin termino de busqueda, se descarta")
            continue
        if nombre in vistos:
            continue
        if not palabras:
            avisos.append(f"real '{nombre}': no dice con que palabras lo nombra "
                          f"el guion, asi que no se podria adjuntar a ningun "
                          f"plano; se descarta")
            continue
        if nombre in (reparto or {}):
            avisos.append(f"real '{nombre}': es del reparto y ya tiene hoja de "
                          f"personaje, que es lo que fija como es; una foto real "
                          f"al lado competiria con ella. Se descarta")
            continue
        tipo = str(ficha.get("tipo") or "objeto").strip().lower()
        if tipo not in TIPOS_REALES:
            avisos.append(f"real '{nombre}': tipo '{tipo}' desconocido, se busca "
                          f"como objeto ({', '.join(TIPOS_REALES)})")
            tipo = "objeto"
        vistos.add(nombre)
        limpias.append({"id": nombre, "tipo": tipo, "buscar": buscar,
                        "que_es": " ".join(str(ficha.get("que_es") or "").split()),
                        "palabras": palabras})
    return limpias


def _limpiar_lugares(crudos, avisos):
    """{palabra del guion: ROTULO}. Se rotula cuando se NOMBRA el sitio."""
    limpios = {}
    for crudo, rotulo in (crudos or {}).items():
        clave = " ".join(str(crudo or "").split()).lower()
        texto = " ".join(str(rotulo or "").split())
        if not clave or not texto:
            continue
        if len(clave) < 3:
            # una clave de dos letras casa con media narracion
            avisos.append(f"lugar '{clave}' descartado: la palabra es demasiado "
                          f"corta y saltaria en cualquier frase")
            continue
        limpios[clave] = texto.upper()
    return limpios




def _identificador(crudo):
    """'Udai Hussein' -> 'udai_hussein'.

    Sin acentos a proposito: estos identificadores acaban siendo NOMBRE DE
    FICHERO de la hoja de reparto ('reparto/udai_hussein.png'), y una tilde ahi
    depende de la codificacion del sistema de ficheros.
    """
    plano = unicodedata.normalize("NFKD", str(crudo or ""))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9_]+", "_", plano.strip().lower()).strip("_")


def _lista_de_palabras(crudo, por_defecto):
    palabras = [str(p).strip() for p in (crudo or []) if str(p).strip()]
    return palabras or [str(por_defecto).replace("_", " ")]


def _limpiar(datos, ids_bloque):
    """Valida la propuesta y la deja en la forma que espera p6_assets.

    Lo que no cuadra se DESCARTA y se dice en 'avisos'. Un beat que apunta a un
    bloque que no existe, o a un set que no se ha declarado, no se puede aplicar:
    dejarlo pasar lo convertiria en un plano sin sitio a mitad del video, que es
    justo el fallo que este modulo viene a arreglar.
    """
    avisos = [str(a) for a in (datos.get("avisos") or []) if str(a).strip()]
    orden = {bid: i for i, bid in enumerate(ids_bloque)}

    reparto = {}
    for crudo, ficha in (datos.get("reparto") or {}).items():
        nombre = _identificador(crudo)
        if not nombre or not isinstance(ficha, dict):
            continue
        reparto[nombre] = {
            # 'nombre' es como se ROTULA en pantalla y 'descripcion' como se
            # DIBUJA: son dos cosas distintas y por eso van separadas.
            "nombre": str(ficha.get("nombre") or "").strip()
                      or nombre.replace("_", " ").title(),
            "papel": str(ficha.get("papel") or "").strip(),
            "descripcion": str(ficha.get("descripcion") or nombre).strip(),
            "palabras": _lista_de_palabras(ficha.get("palabras"), nombre),
            "grupo": bool(ficha.get("grupo")),
        }

    sets = {}
    for crudo, ficha in (datos.get("sets") or {}).items():
        nombre = _identificador(crudo)
        if not nombre or not isinstance(ficha, dict):
            continue
        sets[nombre] = {
            # el rotulo de cabecera ("Bagdad, 23:39") al entrar en el sitio
            "rotulo": str(ficha.get("rotulo") or "").strip(),
            "descripcion": str(ficha.get("descripcion") or nombre).strip(),
            "palabras": _lista_de_palabras(ficha.get("palabras"), nombre),
            "luz": str(ficha.get("luz") or "").strip(),
        }
    capitulos = {}
    for bloque, ficha in (datos.get("capitulos") or {}).items():
        bid = str(bloque or "").strip().upper()
        if bid not in orden or not isinstance(ficha, dict):
            if bid:
                avisos.append(f"capitulo descartado: el bloque {bid} no existe")
            continue
        titulo = str(ficha.get("titulo") or "").strip()
        if titulo:
            capitulos[bid] = {"titulo": titulo,
                              "subtitulo": str(ficha.get("subtitulo") or "").strip()}

    beats = []
    for ficha in (datos.get("beats") or []):
        if not isinstance(ficha, dict):
            continue
        desde = str(ficha.get("desde") or "").strip().upper()
        hasta = str(ficha.get("hasta") or desde).strip().upper()
        if desde not in orden:
            avisos.append(f"beat descartado: el bloque {desde or '(vacio)'} no existe")
            continue
        if hasta not in orden:
            hasta = desde
        if orden[hasta] < orden[desde]:
            desde, hasta = hasta, desde
        set_nombre = _identificador(ficha.get("set")) or None
        if set_nombre and set_nombre not in sets:
            avisos.append(f"beat {desde}-{hasta}: el set '{set_nombre}' no estaba "
                          f"declarado, se ignora el sitio")
            set_nombre = None
        personajes = []
        for crudo in (ficha.get("personajes") or []):
            nombre = _identificador(crudo)
            if nombre in reparto:
                personajes.append(nombre)
            elif nombre:
                avisos.append(f"beat {desde}-{hasta}: '{nombre}' no esta en el reparto")
        beats.append({
            "desde": desde, "hasta": hasta,
            "set": set_nombre,
            "personajes": personajes,
            "tono": str(ficha.get("tono") or "neutro").strip().lower(),
            "accion": str(ficha.get("accion") or "").strip(),
            # p6 empareja por palabras cuando un beat no trae rango; los nuestros
            # SI lo traen, pero se deja la clave para no romper el emparejado
            # antiguo de los catalogos escritos a mano.
            "palabras": [],
        })
    beats.sort(key=lambda b: orden[b["desde"]])

    # CUANTOS beats cubren cada bloque, no solo si lo cubre alguno: los huecos
    # son los que no cubre ninguno y los solapes los que cubren dos o mas.
    cuantos_por_bloque = {}
    for beat in beats:
        for bid in ids_bloque[orden[beat["desde"]]:orden[beat["hasta"]] + 1]:
            cuantos_por_bloque[bid] = cuantos_por_bloque.get(bid, 0) + 1
    cubiertos = set(cuantos_por_bloque)
    huecos = [bid for bid in ids_bloque if bid not in cubiertos]
    if huecos:
        avisos.append(f"{len(huecos)} bloque(s) sin beat: {', '.join(huecos[:8])}"
                      + ("…" if len(huecos) > 8 else "")
                      + ". Esos planos se resolveran sin sitio ni reparto.")

    # LOS SOLAPES SE DICEN, Y NO SE RECHAZAN (07-09-2026).
    #
    # La instruccion pide el guion entero «sin huecos y sin solaparte», y esto
    # comprobaba los huecos y no los solapes: el solape pasaba en silencio. Y
    # pasa mucho, porque un bloque es un parrafo y cabe mas de una idea visual
    # dentro: en el video del oro, 41 bloques de 95 traian mas de un beat, uno
    # de ellos cuatro (el quiosco, el parque de la bolsa, la acera del banco y
    # el monedero, uno por frase).
    #
    # No se rechazan porque son buenos: son 51 ideas visuales de mas por video,
    # y desde el reparto de beats (`p6_assets._beats_por_escena`) se usan de
    # verdad, repartidas entre los planos de ese tramo. Antes de eso el motor se
    # quedaba siempre con el primero y los demas eran codigo muerto -- que es de
    # donde salieron cuatro planos seguidos del mismo quiosco.
    #
    # Se dice para que se vea cuando un tramo trae MAS beats que planos: ahi
    # sobra alguno de verdad, y el aviso es lo unico que lo cuenta.
    compartidos = [bid for bid in ids_bloque
                   if cuantos_por_bloque.get(bid, 0) > 1]
    if compartidos:
        techo = max(cuantos_por_bloque[bid] for bid in compartidos)
        avisos.append(
            f"{len(compartidos)} bloque(s) con mas de un beat "
            f"(hasta {techo} en uno): {', '.join(compartidos[:8])}"
            + ("…" if len(compartidos) > 8 else "")
            + ". No es un fallo: se reparten entre los planos de ese tramo. "
              "Pero un bloque con mas beats que planos deja alguno sin usar.")

    # LOS SITIOS QUE NO PUEDE USAR NADIE SE QUITAN AQUI, sin volver a preguntar.
    #
    # El sitio de un plano lo fija su TRAMO: `p6_assets._asignar_sets` calcula
    # uno por palabras y acto seguido lo pisa con `beat["set"]` si el tramo trae
    # uno. Asi que si TODOS los tramos traen sitio, un sitio que ningun tramo
    # nombra no lo puede elegir nadie. Salieron 19 de 31 asi en un catalogo real.
    #
    # Y se quitan en vez de volver a pedir el catalogo, que fue lo primero que se
    # intento: reintentar es pagar otra tirada esperando que salga distinto, y lo
    # que sobra se puede quitar con una linea y sin gastar nada. La inconsistencia
    # no es de criterio -- el video tiene los tramos que tiene --, es que se
    # describieron sitios de mas.
    #
    # SOLO los que no puede usar nadie. Si queda algun tramo sin sitio, o algun
    # bloque sin tramo, esos planos los resuelve `_elegir_set` por palabras y ahi
    # un sitio suelto SI es un candidato legitimo: quitarlo seria quitarle una
    # opcion al motor.
    sin_sitio = [b for b in beats if not b.get("set")]
    if not sin_sitio and not huecos:
        sobran = sorted(set(sets) - {b["set"] for b in beats if b.get("set")})
        for nombre in sobran:
            sets.pop(nombre, None)
        if sobran:
            avisos.append(
                f"se han quitado {len(sobran)} sitio(s) que ningun tramo usaba "
                f"({', '.join(sobran[:8])}" + ("…" if len(sobran) > 8 else "")
                + "): con todos los tramos con sitio, ningun plano podia "
                  "elegirlos. Si querias alguno, dale un tramo en la tabla.")
    elif set(sets) - {b["set"] for b in beats if b.get("set")}:
        sueltos = sorted(set(sets) - {b["set"] for b in beats if b.get("set")})
        avisos.append(
            f"{len(sueltos)} sitio(s) sin tramo propio ({', '.join(sueltos[:8])}"
            + ("…" if len(sueltos) > 8 else "")
            + f"). Se quedan porque hay {len(sin_sitio) + len(huecos)} tramo(s) "
              f"sin sitio y ahi se pueden elegir por sus palabras.")

    return {"reparto": reparto, "sets": sets, "beats": beats,
            "capitulos": capitulos,
            "componentes": _limpiar_componentes(datos.get("componentes"),
                                                regiones_de_mapa(), avisos),
            "lugares": _limpiar_lugares(datos.get("lugares"), avisos),
            # lo que existe de verdad y hay que ensenar en vez de imaginar; de
            # aqui salen las imagenes que se bajan de Commons (pasos/wikimedia.py)
            "reales": _limpiar_reales(datos.get("reales"), reparto, avisos),
            "avisos": avisos,
            "cobertura": round(len(cubiertos) / max(1, len(ids_bloque)), 3)}


def _guion_legible(bloques):
    """El guion entero con sus ids, que es lo que hace posible leerlo en contexto.

    Los bloques en los que el personaje del canal da la cara (se presenta,
    cierra) van marcados: es lo que le dice al director de arte donde tiene
    que salir el solo (ver FIJOS).
    """
    lineas = []
    for bloque in bloques or []:
        bid = str(bloque.get("id") or "").strip()
        texto = " ".join(str(bloque.get("texto") or "").split())
        marca = " (EL PERSONAJE DA LA CARA)" if bloque.get("personaje") else ""
        lineas.append(f"[{bid}]{marca} {texto}")
    return "\n".join(lineas)


def _cuantos_planos(planos, min_s, max_s):
    """El parrafo con la cuenta de sitios, o vacio si no se sabe cuantos planos hay.

    Vacio y no una cuenta a ojo: un minimo de sitios inventado se obedece igual
    de bien que uno cierto, y entonces el fallo pasa a ser invisible.
    """
    try:
        planos = int(planos or 0)
        minimo, maximo = float(min_s), float(max_s)
    except (TypeError, ValueError):
        return ""
    if planos <= 0 or minimo <= 0 or maximo <= 0:
        return ""
    sitios = max(1, -(-planos // max(1, PLANOS_POR_SET)))     # techo de la division
    return CUANTOS_PLANOS.format(planos=planos, min_s=minimo, max_s=maximo,
                                 planos_por_set=PLANOS_POR_SET, sitios=sitios)


#: LA REGLA DE ESPECIE DEL ESTILO, para que el reparto se describa ya convertido.
#: El estilo Monos dibuja a todo el mundo como un mono; si el catalogo describe
#: a Jensen como «un hombre asiatico con chaqueta de cuero», el generador
#: dibuja a un hombre (paso, 02-09-2026). Se pide aqui, en la fuente de las
#: descripciones, ademas de imponerse en cada prompt (p6.clausula_de_especie).
ESPECIE = """
COMO SON LOS PERSONAJES EN ESTE ESTILO (regla del estilo grafico; manda sobre
la realidad historica):
  {regla}
Describe a CADA entrada del reparto YA CONVERTIDA a esa regla, en ingles y en
una frase: si la regla dice que todos son monos, Jensen Huang es «a monkey in
his early thirties with short straight black hair, wearing a black leather
jacket», nunca «a man». Conserva lo que identifica a cada uno --edad, pelo,
barba, gafas, ropa, complexion-- y cambia la especie, el cuerpo y las
proporciones a lo que diga la regla. Lo mismo con los grupos.
"""


def _especie_legible(regla):
    regla = " ".join(str(regla or "").split())
    return ESPECIE.format(regla=regla) if regla else ""


def proponer(bloques, brief=None, ajuste=None, avisar=None, proyecto_id=None,
             cwd=None, peticion="", planos=0, min_s=None, max_s=None,
             regla_personajes=""):
    """Propone el catalogo visual del video. NO lo guarda: eso lo hace una persona.

    'bloques' son los del guion, con id y texto, EN ORDEN. Se manda el guion
    entero de una vez a proposito: asignar sitios frase a frase es lo que hace
    que una escena de infancia acabe rodada en el garaje del plano anterior.

    'planos' son los que va a cortar assets con SU duracion de plano (min_s,
    max_s), que se elige en otra tarjeta. Se pasa desde fuera y no se supone
    aqui: es lo que convierte «dos planos por sitio» en un numero de sitios (ver
    `planos_previstos`). En 0 el prompt se queda como estaba, sin la cuenta.
    """
    ajuste = ajuste or {}
    modelo = ajuste.get("modelo") or MODELO_POR_DEFECTO
    esfuerzo = ajuste.get("esfuerzo") or ESFUERZO_POR_DEFECTO
    elegido = {"modelo": modelo, "esfuerzo": esfuerzo}

    bloques = [b for b in (bloques or []) if str(b.get("id") or "").strip()]
    if not bloques:
        raise RuntimeError("no hay guion que leer: genera el guion antes")
    ids_bloque = [str(b["id"]).strip().upper() for b in bloques]

    guion, _ = comun.recortar(_guion_legible(bloques), 90000,
                              "[...guion recortado por longitud...]")
    peticion = " ".join(str(peticion or "").split())
    instruccion = INSTRUCCION.format(
        titulo=(brief or {}).get("titulo") or "sin titulo",
        tema=(brief or {}).get("resumen") or (brief or {}).get("tema") or "sin brief",
        peticion=PETICION.format(texto=peticion) if peticion else "",
        especie=_especie_legible(regla_personajes),
        criterio=CRITERIO.format(planos_por_set=PLANOS_POR_SET,
                                 cuantos_planos=_cuantos_planos(planos, min_s,
                                                                max_s),
                                 regiones_mapa=", ".join(regiones_de_mapa())
                                               or "ninguna"),
        guion=guion)

    palabras = sum(comun.contar_palabras(b.get("texto", "")) for b in bloques)
    prevision = estadisticas.estimar(PASO, tamano=palabras, ajuste=elegido)
    avance = None
    if avisar is not None:
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            f"leyendo el guion entero para repartir sitios y personajes, "
            f"con {modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    arranque = time.time()
    try:
        texto, sobre = _llamar_claude(instruccion, modelo, esfuerzo, cwd, avance)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO, time.time() - arranque, ok=False, ajuste=elegido,
                            proyecto=proyecto_id, resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    catalogo = _limpiar(comun.extraer_json(texto, "el catalogo"), ids_bloque)
    estadisticas.anotar(PASO, segundos, tamano=palabras, ajuste=elegido,
                        proyecto=proyecto_id, unidades=len(catalogo["beats"]),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "personajes": len(catalogo["reparto"]),
                                 "sets": len(catalogo["sets"]),
                                 "beats": len(catalogo["beats"]),
                                 "cobertura": catalogo["cobertura"],
                                 "tokens_salida": comun.tokens_de_cli(sobre).get("salida")})

    catalogo["ajuste"] = elegido
    catalogo["segundos"] = round(segundos, 1)
    catalogo["estimacion_s"] = prevision["segundos"]
    catalogo["bloques"] = len(ids_bloque)
    return catalogo








def _llamar_claude(instruccion, modelo, esfuerzo, cwd, avance=None):
    """Se llama asi, y no en linea, para poder engancharle el medidor de coste.

    El medidor engancha POR NOMBRE (nucleo/coste.py). Renombrarla desconecta el
    contador en silencio, que es la peor forma de romperlo.
    """
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        sistema=SISTEMA, herramientas_vetadas=HERRAMIENTAS_VETADAS,
        extra=["--no-session-persistence"], avance=avance,
        para="el catalogo visual")
