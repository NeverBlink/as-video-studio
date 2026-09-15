"""
Utilidades de medios compartidas por los pasos 6, 7 y 8.

Aqui vive lo que los tres pasos visuales necesitan por igual: cargar los motores
de C:\\IA\\motores (que son scripts sueltos, no paquetes), localizar las salidas
de los pasos anteriores, rasterizar SVG con Edge, sembrar la carpeta de trabajo
con la version activa y EMPAREJAR UN TEXTO ESCRITO CON LO QUE DICE LA VOZ.

Lo ultimo esta aqui por la misma razon que lo demas: lo hacen dos sitios por
igual. Un rotulo entra cuando se dice lo que rotula (p6._indice_de) y una cartela
se escribe al ritmo al que la voz dice sus palabras (cartelas.alinear), y con dos
copias de la misma heuristica la que se quedara vieja fallaria en silencio.

Lo de sembrar merece explicacion: el nucleo versiona moviendo TODO lo que hay en
pasos/<id>/trabajo/ a la version nueva. Si un paso solo rehace dos escenas, la
version nueva se quedaria con dos ficheros y perderia el resto. Por eso, antes
de escribir nada, se copia la version activa dentro de trabajo/: lo que no se
regenera sigue estando, y la version nueva es completa de verdad.
"""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unicodedata

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_ESTUDIO not in sys.path:
    sys.path.insert(0, RAIZ_ESTUDIO)

MOTORES = os.environ.get("ESTUDIO_MOTORES") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "motores")
BANCO = os.environ.get("ESTUDIO_BANCO") or os.path.join(RAIZ_ESTUDIO, "banco")

# SIN VENTANA. En Windows, lanzar un proceso de consola desde un servicio abre
# una ventana negra encima de todo, y un video son decenas: un rasterizado por
# SVG, una llamada al CLI por bloque, una captura por fotograma. Trabajando por
# escritorio remoto eso es la pantalla parpadeando y tapandose sola durante
# veinte minutos.
#
# Va en UN sitio y lo usan todos los pasos, en vez de repetir el flag en cada
# llamada: repetirlo es como se queda uno sin poner. `SIN_VENTANA` se pasa como
# **kwargs a subprocess, y en Linux/Mac queda vacio.
SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}

#: Donde buscar el navegador del render, en orden. Las dos primeras son las de
#: Windows; las de Linux van detras para que en Windows no cambie nada. Se puede
#: forzar uno concreto con ESTUDIO_EDGE.
EDGES = tuple(f for f in (os.environ.get("ESTUDIO_EDGE"),) if f) + (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/microsoft-edge",
    "/opt/microsoft/msedge/msedge",
    "/usr/bin/chromium",
)

# escribir_json, leer_json y huella se REEXPORTAN a proposito: los pasos
# visuales entran por 'medios' a todo lo de disco, y asi no tienen que conocer
# el nucleo. `huella` es ADEMAS la misma que usa el grafo de build para las
# firmas de los pasos: tenerla escrita dos veces era una invitacion a que
# alguien "mejorase" una de las dos y la mitad del sistema cambiara de firma.
from nucleo.proyecto import (escribir_json, huella,  # noqa: E402,F401
                             identificador, leer_json)


def identificador_o_vacio(valor):
    """Como identificador(), pero lo vacio se queda vacio.

    identificador() devuelve 'proyecto' cuando no hay nada que normalizar. Para
    el nombre de la carpeta de un proyecto eso es exactamente lo que se quiere;
    en cualquier otro sitio es una trampa, y ya mordio: un set del catalogo SIN
    sitio ('base' vacio) acababa pidiendo uno llamado «proyecto», y el paso de
    assets se negaba a generar por un sitio que nadie habia
    nombrado nunca.
    """
    texto = str(valor or "").strip()
    return identificador(texto) if texto else ""


# ESTE FICHERO SE IMPORTA DOS VECES EN EL MISMO PROCESO
# ------------------------------------------------------
# 'pasos.medios' por el paquete, y 'medios' a secas por p6_assets, p7, p8 y
# moodboard, que tienen pasos/ en sys.path. Son dos objetos modulo distintos con
# dos estados distintos, y `nucleo/coste.py` ya lo documenta porque tiene que
# instrumentar las dos copias del motor de imagen.
#
# Lo que gobierna las recargas tiene que ser UNO SOLO. Con estado por copia, el
# congelado de app.py se ponia en 'pasos.medios' y las recargas pasaban por
# 'medios': o sea que la proteccion no protegia nada. Se guarda en un modulo
# sintetico de sys.modules, que es lo unico compartido de verdad.
_COMPARTIDO = sys.modules.setdefault("_medios_compartido",
                                     types.ModuleType("_medios_compartido"))
if not hasattr(_COMPARTIDO, "motores"):
    _COMPARTIDO.motores = {}            # {clave: (modulo, mtime)}
    _COMPARTIDO.en_marcha = [0]
    _COMPARTIDO.al_cargar = []
    _COMPARTIDO.candado = threading.Lock()

#: {clave: (modulo, mtime con el que se cargo)}
_motores = _COMPARTIDO.motores
#: Cuantos trabajos hay dentro de un paso ahora mismo. Un motor NO se recarga a
#: media tanda: recargar crea un objeto modulo nuevo, y el estado de modulo
#: --el freno del limite de la API, el contador de gasto-- se partiria en dos
#: justo cuando hace falta que sea uno.
_en_marcha = _COMPARTIDO.en_marcha
_candado_marcha = _COMPARTIDO.candado

#: Se avisa aqui despues de cargar o RECARGAR un motor: (clave, modulo).
#:
#: Existe por el medidor de coste, que engancha sus funciones POR NOMBRE sobre
#: el objeto modulo (`nucleo/coste.py`, _envolver). Una recarga deja un objeto
#: nuevo, sin enganchar, y el gasto de imagen dejaria de contarse EN SILENCIO --
#: que es exactamente el fallo que la instrumentacion existe para evitar, dicho
#: con esas palabras en su propio docstring. Es una lista de callbacks y no un
#: import de coste porque la direccion de la dependencia es esa: el medidor
#: conoce los motores, los motores no conocen al medidor.
AL_CARGAR = _COMPARTIDO.al_cargar


def motor(ruta_relativa):
    """Importa un modulo de C:\\IA\\motores por ruta ('guion/segmentar.py').

    Por ruta y no por sys.path: los motores tienen nombres genericos ('voz',
    'imagen', 'mapa') que chocarian entre ellos y con cualquier otro modulo.

    Y SE RECARGA SI EL FICHERO HA CAMBIADO. Esto se cacheaba para siempre, y los
    pasos corren en un HILO del servicio: una vez cargado un motor, ese objeto
    vivia lo que viviera el proceso. Con el servicio levantado desde por la
    manana, arreglar un motor no servia de nada -- se seguia ejecutando la copia
    en memoria, se volvia a ver el mismo fallo exacto, y se depuraba codigo que
    no se estaba ejecutando. Paso de verdad con el limite de la API de imagen:
    el arreglo estaba en disco, escrito hora y media DESPUES de arrancar el
    servicio, y el 429 volvio identico.

    La recarga es la excepcion y no la via normal: solo si cambia el mtime, y
    nunca con un trabajo dentro del paso (ver `_en_marcha`).
    """
    clave = ruta_relativa.replace("/", os.sep)
    ruta = os.path.join(MOTORES, clave)
    guardado = _motores.get(clave)
    if guardado is not None:
        modulo, sello = guardado
        if _en_marcha[0] > 0:
            return modulo
        try:
            if os.path.getmtime(ruta) == sello:
                return modulo
        except OSError:
            return modulo
    if not os.path.exists(ruta):
        raise FileNotFoundError(f"no existe el motor {ruta}")
    nombre = "motor_" + identificador(clave)
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    try:
        sello = os.path.getmtime(ruta)
    except OSError:
        sello = 0
    if guardado is not None:
        print(f"[medios] motor recargado: {clave}", flush=True)
    _motores[clave] = (modulo, sello)
    for aviso in list(AL_CARGAR):
        try:
            aviso(clave, modulo)
        except Exception:                          # noqa: BLE001
            pass          # un gancho roto no puede impedir cargar un motor
    return modulo


class trabajo_en_curso:                            # noqa: N801  (es un with)
    """Mientras dure esto, ningun motor se recarga.

    Un paso carga varios motores y los usa durante minutos. Recargar uno a
    mitad de camino deja dos copias vivas con dos estados de modulo distintos:
    dos frenos del limite de la API en vez de uno, y dos contadores de gasto.
    """

    def __enter__(self):
        # bajo candado: dos pasos a la vez son dos hilos, y leer-modificar-
        # escribir sobre una lista puede perder una de las dos actualizaciones.
        # Si se pierde una BAJADA el congelado no se levanta nunca; si se pierde
        # una SUBIDA, se recarga a media tanda, que es lo que esto evita.
        with _candado_marcha:
            _en_marcha[0] += 1
        return self

    def __exit__(self, *_):
        with _candado_marcha:
            _en_marcha[0] -= 1
            if _en_marcha[0] < 0:      # el clamp, DENTRO del candado: suelto
                _en_marcha[0] = 0      # reabre la misma ventana que cierra
        return False


# ------------------------------------------------------------------ texto

def sin_tildes(texto):
    plano = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in plano if not unicodedata.combining(c))


def normalizar_texto(texto):
    """Minusculas, sin tildes y con los signos convertidos en espacios."""
    return re.sub(r"[^a-z0-9]+", " ", sin_tildes(texto).lower()).strip()


def contiene(texto_normalizado, termino):
    """True si el termino aparece como palabra completa (o frase) en el texto."""
    termino = normalizar_texto(termino)
    if not termino:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(termino) + r"(?![a-z0-9])",
                     texto_normalizado) is not None


# ----------------------------------------- emparejar un texto con la VOZ
#
# Un rotulo entra CUANDO SE DICE lo que rotula (p6._indice_de) y una cartela se
# escribe al ritmo al que la voz dice sus palabras (cartelas.alinear). Son la
# misma pregunta -- «en que palabra de este plano se dice esto?» --, asi que la
# respuesta vive AQUI, al lado de la normalizacion canonica, y no una copia en
# cada sitio: con dos copias, la que se quedara vieja fallaria en silencio.
#
# Lo que esto sabe, y que un `in` a secas no sabia:
#
#   LA CIFRA EN OTRA NOTACION. Una cartela DESTILA la narracion: escribe «30M»
#   donde la voz dice «thirty million», «4%» donde dice «four percent», «165+»
#   donde dice «a hundred and sixty-five». Es justo la palabra que mas pesa de
#   una cartela de cifra, y en una que SOLO lleve el numero no queda ninguna
#   otra ancla: sin esto se queda sin sincronizar entera.
#
#   QUE UNA PALABRA ESCRITA SEAN VARIAS DICHAS. «30M» es un token y «thirty
#   million» son dos, asi que el ancla no puede ser «la palabra n»: es un TRAMO.
#   Se ancla al INICIO del numero hablado y se consume entero, para que la
#   palabra siguiente de la cartela no ancle dentro de el.
#
#   QUE LA COMPARACION SEA SIMETRICA. Antes casaba si lo escrito era subcadena
#   de lo dicho, asi que «account» casaba con «accounts» pero «accounts» no
#   casaba con «account». En el caso medido daba igual; en otro muerde.

#: Cuantos caracteres tiene que tener la mas corta de las dos para que valga
#: casar por subcadena. Con menos, «de» casaria con «desde» y «la» con «lado».
MINIMO_SUBCADENA = 4

#: Como se dicen los numeros, por idioma. Solo es/en: son los dos idiomas en los
#: que se locuta hoy, y un idioma sin tabla se comporta como se comportaba todo
#: antes de esto (casa por palabra y no por valor), que es degradar y no romper.
_UNIDADES = {
    "es": {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3,
           "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
           "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
           "catorce": 14, "quince": 15, "dieciseis": 16, "diecisiete": 17,
           "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veintiuno": 21,
           "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
           "veinticinco": 25, "veintiseis": 26, "veintisiete": 27,
           "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
           "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
           "noventa": 90, "cien": 100, "ciento": 100, "doscientos": 200,
           "doscientas": 200, "trescientos": 300, "trescientas": 300,
           "cuatrocientos": 400, "cuatrocientas": 400, "quinientos": 500,
           "quinientas": 500, "seiscientos": 600, "seiscientas": 600,
           "setecientos": 700, "setecientas": 700, "ochocientos": 800,
           "ochocientas": 800, "novecientos": 900, "novecientas": 900},
    "en": {"zero": 0, "a": 1, "an": 1, "one": 1, "two": 2, "three": 3,
           "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
           "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
           "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
           "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
           "eighty": 80, "ninety": 90},
}

#: Los multiplicadores EN PLURAL, que no empiezan un numero por si solos:
#: «millones de personas» es una cantidad indefinida, no 1.000.000 de personas.
#: En singular si («mil personas», «un millon»), y por eso la tabla es de
#: palabras y no una regla sobre la ese final.
_MULTIPLOS_PLURAL = {"millones", "millardos", "billones"}

#: Los multiplicadores, que son los que hacen que «treinta millones» sea un
#: tramo de dos palabras y no dos numeros seguidos.
_MULTIPLOS = {
    "es": {"mil": 10 ** 3, "millon": 10 ** 6, "millones": 10 ** 6,
           "millardo": 10 ** 9, "millardos": 10 ** 9,
           "billon": 10 ** 12, "billones": 10 ** 12},
    "en": {"hundred": 100, "thousand": 10 ** 3, "million": 10 ** 6,
           "billion": 10 ** 9, "trillion": 10 ** 12},
}

#: Palabras que unen dos trozos de un mismo numero («a hundred AND sixty-five»).
#: Solo se tragan si detras viene otro trozo de numero: si no, «y» se comeria la
#: mitad de la frase.
_ENLACES = {"es": {"y"}, "en": {"and"}}

#: Lo que se dice DETRAS de la cifra y forma parte de ella al leerla: «four
#: percent» es «4%». Extiende el tramo, no cambia el valor.
_COLAS = {"es": (("por", "ciento"), ("por", "cien")),
          "en": (("percent",), ("per", "cent"))}

#: Palabras que valen 1 pero que NO arrancan un numero por si solas: «one of the
#: systems» no es la cifra 1, y «a password» tampoco. Solo cuentan cuando detras
#: viene un multiplicador («a hundred», «un millon») o cuando detras viene LA
#: COLA («un uno por ciento» es 1 %, y ahi la debil ES el numero).
_DEBILES = {"a", "an", "one", "un", "uno", "una"}

#: La MITAD dicha detras de un numero: «uno y medio por ciento» es 1,5 %. Solo
#: cuenta pegada a un enlace y con un numero ya visto delante, que es la unica
#: forma en que se dice: «medio» suelto («medio segundo») no es una cifra.
_MITADES = {"es": {"medio", "media"}, "en": {"half"}}

#: LAS MONEDAS DICHAS CON DECIMALES: «un dolar con ochenta» se escribe «$1,80»
#: y «tres euros con cincuenta», «3,50 €». Es otra forma de cifra hablada,
#: como el porcentaje: la conversion palabra a palabra dejaba «un dolar con
#: 80», que el canal vio en un subtitulo (02-09-2026). El simbolo va donde lo
#: pone cada moneda en castellano corriente: el dolar delante, el euro detras.
#: Los centimos dichos detras («con ochenta centavos») se tragan.
_MONEDAS = {
    "es": {"dolar": ("$", ""), "dolares": ("$", ""),
           "euro": ("", " €"), "euros": ("", " €")},
    "en": {"dollar": ("$", ""), "dollars": ("$", ""),
           "euro": ("", " €"), "euros": ("", " €")},
}
_CON_DECIMALES = {"es": {"con"}, "en": {"and", "point"}}
_CENTIMOS = {"centavo", "centavos", "centimo", "centimos", "cent", "cents"}

#: La coma decimal de cada idioma. La pone la palabra encontrada --«medio» es
#: castellano, «half» ingles--, igual que el sufijo del ordinal y por lo mismo:
#: los params de callouts no traen idioma (ver `_sufijo_ordinal`).
_DECIMAL = {"es": ",", "en": "."}

#: Palabras que solo aparecen en uno de los dos idiomas, para saber en cual esta
#: escrita una narracion sin tener que preguntarselo a nadie.
_MARCADORES = {
    "es": ("el", "la", "los", "las", "de", "que", "y", "en", "un", "una",
           "por", "con", "para", "se", "del", "no", "es", "su"),
    "en": ("the", "of", "and", "to", "in", "that", "for", "was", "with",
           "on", "it", "is", "as", "at", "by", "from", "an"),
}


def idioma_de(texto, defecto="es"):
    """En que idioma esta escrito esto: 'es' | 'en'. Cuenta palabras vacias.

    Se deduce del TEXTO y no se pide por parametro porque quien alinea tiene la
    narracion delante en TODOS los caminos -- el plan, la vista previa, p7, el
    sonido y un plan viejo que no guardo ningun idioma --, y un parametro que hay
    que ir cableando por cinco sitios se queda sin cablear en uno. Quien lo sepa
    de primera mano (el brief) puede pasarlo igualmente y manda.
    """
    palabras = set(normalizar_texto(texto).split())
    if not palabras:
        return defecto
    puntos = {codigo: sum(1 for m in marcas if m in palabras)
              for codigo, marcas in _MARCADORES.items()}
    mejor = max(puntos, key=lambda c: puntos[c])
    return mejor if puntos[mejor] else defecto


def valor_numerico(token):
    """El numero que representa un token ESCRITO, o None si no es una cifra.

        '30M' -> 30000000.0    '4%' -> 4.0      '165+' -> 165.0
        '1.500' -> 1500.0      '2,5M' -> 2500000.0     '28' -> 28.0

    Se le pasa el token CRUDO y no el normalizado a proposito: normalizar_texto
    se come justo los signos que dicen que esto es una cifra (el %, el +, el
    punto de los miles), asi que sobre el normalizado '1.500' serian dos
    palabras y '4%' un cuatro pelado.
    """
    crudo = str(token or "").strip()
    if not crudo:
        return None
    limpio = re.sub(r"^[\s$€£¥#~<>+-]+", "", sin_tildes(crudo))
    limpio = re.sub(r"[\s$€£¥#~<>+]+$", "", limpio)
    encaje = re.match(r"^(\d[\d.,]*)\s*([a-zA-Z]{0,2})%?$", limpio)
    if not encaje:
        return None
    cifra, sufijo = encaje.group(1), encaje.group(2).lower()
    # El punto y la coma son a la vez separador de miles y coma decimal, y cual
    # es cual depende de quien lo escribiera. El grupo de TRES cifras lo
    # desempata sin preguntar: '1.500' son mil quinientos y '2,5' son dos y
    # medio, se escriban como se escriban.
    trozos = re.split(r"[.,]", cifra.rstrip(".,"))
    if len(trozos) == 1:
        valor = float(trozos[0])
    elif all(len(t) == 3 for t in trozos[1:]):
        valor = float("".join(trozos))
    else:
        valor = float(trozos[0] + "." + "".join(trozos[1:]))
    escala = {"": 1, "k": 10 ** 3, "m": 10 ** 6, "mm": 10 ** 6, "b": 10 ** 9,
              "bn": 10 ** 9, "t": 10 ** 12}.get(sufijo)
    if escala is None:
        return None
    return valor * escala


def _tablas(idioma=None):
    """Como se dicen los numeros en ese idioma. Sin idioma, en TODOS a la vez.

    Juntar las tablas es mejor que adivinar: los dos vocabularios no se pisan en
    ninguna palabra --«million» y «millones» se escriben distinto, y 'a' y 'un'
    no arrancan numero por si solos--, asi que la union no puede leer un numero
    donde no lo hay. Y el idioma se sabe casi siempre; casi no es siempre, y un
    fragmento corto («twenty eight million card numbers») no trae ni un articulo
    con el que decidirlo.
    """
    codigos = [idioma] if idioma in _UNIDADES else list(_UNIDADES)
    unidades, multiplos, enlaces, colas = {}, {}, set(), []
    for codigo in codigos:
        unidades.update(_UNIDADES[codigo])
        multiplos.update(_MULTIPLOS.get(codigo) or {})
        enlaces |= _ENLACES.get(codigo) or set()
        colas.extend(_COLAS.get(codigo) or ())
    return unidades, multiplos, enlaces, tuple(colas)


def _mitades(idioma=None):
    """Las palabras que valen «y medio» en ese idioma. Sin idioma, todas.

    Va aparte de `_tablas` y no como un quinto elemento de su tupla: la tupla se
    desempaqueta en seis sitios y en cuatro de ellos con `_` de relleno, asi que
    alargarla es tocar todo lo que lee numeros para que tres lineas lean una
    cosa nueva.
    """
    codigos = [idioma] if idioma in _MITADES else list(_MITADES)
    palabras = set()
    for codigo in codigos:
        palabras |= _MITADES.get(codigo) or set()
    return palabras


def _separador_decimal(trozo, idioma=None):
    """La coma decimal que le toca a este tramo. -> ',' o '.'

    MANDA LA PALABRA ENCONTRADA, que es la misma doctrina que `_sufijo_ordinal`:
    si el tramo trae un «medio», ese «medio» solo esta en una de las dos tablas
    y no hay nada que suponer.

    Y SI NO HAY NINGUNA, MANDA EL IDIOMA. Antes se caia al punto, y de ahi salia
    un separador de miles equivocado en cuanto la frase no llevaba mitades:
    «trescientos mil» en castellano salia «300,000», que es como se escribe en
    ingles. El idioma lo sabe quien llama --viene del video-- y solo hacia falta
    dejarlo pasar hasta aqui.
    """
    for codigo, palabras in _MITADES.items():
        if any(p in palabras for p in (trozo or ())):
            return _DECIMAL.get(codigo, ".")
    for codigo in _DECIMAL:
        if str(idioma or "").lower().startswith(codigo):
            return _DECIMAL[codigo]
    return "."


def numeros_dichos(palabras_llanas, idioma=None, cortes=None):
    """Los numeros que se PRONUNCIAN en esa lista, como tramos.

    Devuelve [(indice, cuantas_palabras, valor)], sin solaparse y en orden. El
    tramo es lo que convierte «thirty million» en UNA cosa: ancla en 'thirty' y
    consume tambien 'million', para que la palabra siguiente de la cartela no
    ancle en mitad de la cifra.

    `cortes` son los indices detras de los que el texto CRUDO llevaba
    puntuacion, y su unico trabajo es PARAR el numero ahi. Sin ellos, «en dos
    mil veinticuatro, treinta millones» se leia como UN numero y daba 2.054
    millones: la coma desaparece al normalizar, asi que quien la ha visto tiene
    que decirlo. Opcional: sin `cortes` sale lo mismo que salia antes, que es
    degradar y no romper.
    """
    unidades, multiplos, enlaces, colas = _tablas(idioma)
    cortes = set(cortes or ())
    palabras = list(palabras_llanas or [])

    def numero(palabra):
        if palabra in unidades:
            return float(unidades[palabra])
        return float(palabra) if palabra.isdigit() else None

    mitades = _mitades(idioma)

    def mitad_tras(j):
        """Cuantas palabras ocupa «y medio» detras del enlace de j. -> 0, 2 o 3

        Dos formas, y las dos hacen falta porque las tablas de los dos idiomas
        van juntas: «uno y MEDIO» en castellano y «one and A half» en ingles,
        que mete un articulo por medio. Y ese articulo esta en `_DEBILES`, o sea
        que sin esto vale 1 y se SUMA: «one and a half percent» daba 2.
        """
        resto = palabras[j + 1:j + 3]
        if resto and resto[0] in mitades:
            return 2
        if len(resto) == 2 and resto[0] in _DEBILES and resto[1] in mitades:
            return 3
        return 0

    def empieza_la_debil(i):
        """Esta palabra debil, ¿es el numero o es el articulo? -> bool

        UNA PALABRA DEBIL NO EMPIEZA UN NUMERO SALVO DELANTE DE UN MULTIPLICADOR
        O DE LA COLA. La primera mitad de la regla es la que `_DEBILES` decia
        desde siempre («solo cuentan cuando detras viene un multiplicador») y que
        no estaba implementada: se sumaban. Medido en el video del oro, CINCO
        subtitulos con la cifra mal --y son cifras que el espectador lee mientras
        oye otra--:

            «un dos por ciento»                   -> 3%     (1 + 2)
            «un cuatro por ciento»                -> 5%     (1 + 4)
            «un cuatrocientos ochenta por ciento» -> 481%   (1 + 480)

        La segunda mitad es la que faltaba, y da el caso contrario: cuando la
        debil ES el numero, saltarla dejaba la cola suelta y «ciento» se leia
        como el 100 pelado --«un uno por ciento al ano» salia «un uno por 100 al
        ano»--. Reales en el video del oro: S072 y S083.

        Asi que la debil cuenta cuando detras viene un multiplicador («un
        millon», «a hundred») o cuando lo que viene detras es la COLA, con o sin
        mitad por medio («uno por ciento», «uno y medio por ciento»). Y «treinta
        y uno» no se toca: ese numero no EMPIEZA en la palabra debil.
        """
        # «un UNO por ciento» tiene DOS debiles seguidas y solo la segunda es el
        # numero: si detras viene otra palabra de numero, esta es el articulo.
        sigue = palabras[i + 1] if i + 1 < len(palabras) else ""
        j = i + 1
        if sigue in enlaces:
            j += mitad_tras(i + 1)      # «one and a half million»: el multiplo
        if palabras[j:j + 1] and palabras[j] in multiplos:
            return True
        return any(list(palabras[j:j + len(cola)]) == list(cola) for cola in colas)

    salida, i = [], 0
    while i < len(palabras):
        if palabras[i] in _DEBILES and not empieza_la_debil(i):
            i += 1
            continue
        if palabras[i] in _MULTIPLOS_PLURAL:
            # «millones de personas» no es «1000000 de personas»: un multiplo en
            # plural y sin cifra delante es una cantidad indefinida. Con cifra
            # delante el tramo no EMPIEZA aqui, asi que «treinta millones» no se
            # entera de esto.
            i += 1
            continue
        total, actual, mayor, visto, j = 0.0, 0.0, 0.0, False, i
        while j < len(palabras):
            palabra = palabras[j]
            if palabra in enlaces:
                # 'y' / 'and' solo si detras sigue el numero: si no, se estaria
                # tragando la conjuncion que separa dos frases
                sigue = palabras[j + 1] if j + 1 < len(palabras) else ""
                salto = mitad_tras(j)
                if visto and salto:
                    # «uno y MEDIO por ciento» son 1,5 %. Sin esto el tramo se
                    # cerraba en el «uno», la cola se quedaba huerfana y
                    # «ciento» se leia como el 100 suelto.
                    actual += 0.5
                    j += salto
                    continue
                if visto and (numero(sigue) is not None or sigue in multiplos):
                    j += 1
                    continue
                break
            if palabra in multiplos:
                escala = multiplos[palabra]
                if escala == 100:
                    actual = max(1.0, actual) * 100
                elif escala > mayor:
                    # Sube de orden, asi que se lleva TODO lo acumulado: «mil
                    # quinientos millones» son 1.500 millones y no mil mas
                    # quinientos millones, y «mil millones» son 10^9.
                    actual = (total + actual) or 1.0
                    total = 0.0
                    total += actual * escala
                    actual, mayor = 0.0, escala
                else:
                    total += max(1.0, actual) * escala
                    actual = 0.0
                visto = True
                j += 1
                if j - 1 in cortes:
                    break              # la coma cierra el numero: ver `cortes`
                continue
            valor = numero(palabra)
            if valor is None:
                break
            actual += valor
            visto = True
            j += 1
            if j - 1 in cortes:
                break                  # la coma cierra el numero: ver `cortes`
        if not visto:
            i += 1
            continue
        for cola in colas:
            if list(palabras[j:j + len(cola)]) == list(cola):
                j += len(cola)
                break
        # UNA COLA HUERFANA NO ES UN NUMERO. `subtitulos.limpiar_texto` corre
        # sobre CADA TROZO por separado, y `tramos` puede partir por el sitio mas
        # parejo: un plano largo se corta entre «cuatro» y «por ciento», y el
        # trozo de abajo empezaba en «ciento», que vale 100. Salia «por 100» en
        # pantalla mientras se oye la cifra de arriba. Solo cuando la cola es
        # TODO el tramo: «por ciento veinte» sigue siendo 120.
        #
        # Lo que cuesta, dicho: «por cien euros» se queda en letra en vez de
        # «por 100 euros». Se acepta porque los dos errores no valen lo mismo --
        # ese sigue diciendo lo que se oye, y «por 100» dice otra cifra.
        if j - i == 1 and any(
                len(cola) >= 2 and list(palabras[i - len(cola) + 1:i + 1]) == list(cola)
                for cola in colas):
            i = j
            continue
        salida.append((i, j - i, total + actual))
        i = j
    return salida


# ---------------------------------------------- lo que se DICE y se ESCRIBE
#
# UN SUBTITULO NO ES EL GUION. El guion va con TODO escrito con letras porque lo
# locuta un sintetizador y una cifra la pronuncia como el decida (regla 8 de
# p3_guion). Pero eso es una regla de la VOZ, no de la pantalla:
# leer «one hundred sixty-five companies warned» en un subtitulo de dos lineas
# cuesta mas que oirlo, y «UNC five five three seven» directamente no se
# reconoce como el identificador que es.
#
# Asi que aqui vive la vuelta: de lo dicho a lo escrito. Es DETERMINISTA y no se
# le pregunta a nadie -- las tablas de arriba ya saben como se dicen los numeros
# en cada idioma --, y es la MISMA tabla que usa el alineador, asi que las dos
# no se pueden desincronizar.
#
# Tres formas, y las tres hacen falta porque el parser general se equivoca en
# dos de ellas:
#
#   EL ANO EN DOS MITADES. «twenty twenty-four» no son veinte mas veinticuatro:
#   son dos mil veinticuatro. El parser general suma y devuelve 44. En
#   castellano no hace falta -- «dos mil veinticuatro» ya sale bien --, asi que
#   la tabla es solo del ingles.
#
#   LA SERIE DE DIGITOS. «five five three seven» tampoco se suma: es 5537, el
#   numero de un identificador. El parser general devuelve 20.
#
#   LA CIFRA NORMAL, que si sale del parser general y de la que solo hay que
#   decidir si se escribe con numeros o se deja en letra.
#
# Y DEBAJO DE DIEZ SE DEJA EN LETRA, que es lo que hace cualquier libro de
# estilo: «two systems» escrito «2 systems» no se lee mejor, y ademas es la
# unica forma de que un «one» que no es una cifra no acabe siendo un «1». La
# excepcion es el vecino: en «six out of ten» convertir solo el diez daria «six
# out of 10», que se lee peor que las dos formas puras.

#: A partir de esta cifra, lo dicho se escribe con numeros. Ver arriba.
MINIMO_EN_CIFRA_SUELTA = 10

#: Y a partir de esta, tambien cuando lleva multiplicador: «30 million».
#: DE UN MILLON PARA ARRIBA, y no de mil. Esta regla conserva la palabra dicha
#: --«treinta millones» sale «30 millones» y no «30000000»-- y con el umbral en
#: mil se llevaba tambien los millares: «dos mil anos» salia «2 mil anos», que no
#: lo escribe nadie. Ademas se contradecia sola, porque un millar con resto no
#: entra en esta rama: «tres mil quinientos» ya salia «3500». Los millares caben
#: en cifras y se leen bien; los millones, no.
MINIMO_CON_MULTIPLO = 10.0 ** 6

#: Desde cuantos digitos lleva separador de miles. CINCO Y NO CUATRO, y no es
#: una preferencia: con cuatro, los anos saldrian «1.999» y «2.024». Dejandolo
#: en cinco los anos quedan fuera solos, sin una regla especial para anos que
#: alguien tendria que acordarse de mantener.
MINIMO_CON_SEPARADOR = 10000

#: A cuantos tokens de distancia arrastra un vecino convertido. Tres es lo que
#: separa dos cifras de la misma expresion («six out of ten», «de dos a cinco»)
#: sin llegar a juntar dos frases distintas.
VECINDAD_CIFRA = 3

#: Las cabezas de un ano dicho en dos mitades, por idioma. Solo el ingles: en
#: castellano un ano se dice entero («mil novecientos noventa y nueve») y el
#: parser general ya lo resuelve.
_ANOS_CABEZA = {"en": {"seventeen": 1700, "eighteen": 1800, "nineteen": 1900,
                       "twenty": 2000}}

#: La horquilla de lo que puede ser un ano dicho asi. Fuera de ella lo mas
#: probable es que fuera una suma de verdad.
ANO_MINIMO, ANO_MAXIMO = 1700, 2099

#: Cuantos digitos sueltos seguidos hacen una SERIE. Con dos («five five») el
#: riesgo de tragarse dos cifras de frases distintas es real; con tres ya es un
#: identificador dictado, que es lo unico que se dice asi.
DIGITOS_MINIMOS_EN_SERIE = 3

# ---------------------------------------------------------------- ordinales
#
# «On August fifth, 2026» se escribe «On August 5th, 2026», y eso NO lo resuelve
# el parser general: 'fifth' no es una unidad, asi que se queda en letra al lado
# de un 2026 en cifra. Lo mismo con «May thirtieth» y con «October
# twenty-seventh», que ademas el general partiria por la mitad ('twenty' -> 20).
#
# DONDE SI Y DONDE NO, porque un ordinal en ingles es traicionero:
#
#     detras de un mes           SIEMPRE. Es una fecha: «June second» -> «June 2nd»
#     suelto y de diez para      SI. «the thirtieth time» -> «the 30th time»
#     arriba
#     suelto y por debajo        NO. «the second step» NO es «the 2nd step», y
#     de diez                    «first» casi nunca es una cifra. Es la misma
#                                doctrina que MINIMO_EN_CIFRA_SUELTA, y aqui
#                                pesa mas: 'second' es ademas la unidad de
#                                tiempo, y 'first/second/third' viven casi
#                                siempre dentro de una frase, no de una fecha.
#
# EN CASTELLANO UNA FECHA NO LLEVA ORDINAL: se dice «el cinco de agosto», con
# cardinal, y ese cinco se quedaba en letra por ser menor que diez. Asi que ahi
# lo que se reconoce es el DIA: un cardinal pegado a «de <mes>».
_ORDINALES = {
    "en": {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
           "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
           "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
           "fifteenth": 15, "sixteenth": 16, "seventeenth": 17,
           "eighteenth": 18, "nineteenth": 19, "twentieth": 20,
           "thirtieth": 30, "fortieth": 40, "fiftieth": 50, "sixtieth": 60,
           "seventieth": 70, "eightieth": 80, "ninetieth": 90},
    "es": {"primero": 1, "primer": 1, "primera": 1, "segundo": 2, "segunda": 2,
           "tercero": 3, "tercer": 3, "tercera": 3, "cuarto": 4, "cuarta": 4,
           "quinto": 5, "quinta": 5, "sexto": 6, "sexta": 6, "septimo": 7,
           "septima": 7, "octavo": 8, "octava": 8, "noveno": 9, "novena": 9,
           "decimo": 10, "decima": 10},
}

#: Las DECENAS que pueden encabezar un ordinal compuesto: «twenty-seventh» llega
#: aqui aplanado en dos palabras ('twenty', 'seventh') porque `cifras_en` parte
#: los guiones antes de mirar.
_DECENAS_ORDINAL = {"en": {"twenty": 20, "thirty": 30, "forty": 40,
                           "fifty": 50, "sixty": 60, "seventy": 70,
                           "eighty": 80, "ninety": 90}}

#: Los meses, que son lo que convierte un ordinal en una FECHA.
_MESES = {
    "en": {"january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december"},
    "es": {"enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "setiembre", "octubre", "noviembre",
           "diciembre"},
}


def _sufijo_ordinal(valor, idioma=None):
    """'5' -> '5th'. En castellano una fecha va con cardinal pelado.

    EL IDIOMA LO PONE LA PALABRA QUE SE ENCONTRO, no el que venga de fuera, y
    eso no es un detalle: `subtitulos.de_escena` lo recibe de
    `p7.p.get("idioma")` y **los params de callouts no tienen esa clave**, asi
    que llega None SIEMPRE. Con None esto devolvia el cardinal pelado y en el
    video salia «On August 5, 2026» en vez de «On August 5th, 2026».

    Con la palabra delante no hace falta preguntar: 'fifth' solo esta en la
    tabla inglesa y 'quinto' solo en la castellana, asi que el idioma del ordinal
    es un dato y no una suposicion.
    """
    if not str(idioma or "").lower().startswith("en"):
        return _entero(valor)
    centena = int(valor) % 100
    if 11 <= centena <= 13:
        cola = "th"
    else:
        cola = {1: "st", 2: "nd", 3: "rd"}.get(int(valor) % 10, "th")
    return "%d%s" % (int(valor), cola)


def _ordinales_dichos(palabras, idioma=None, cortes=None):
    """Los ordinales que se escriben con cifra. -> [(indice, cuantas, texto)]

    Ver el bloque de arriba para el porque de cada caso. `cortes` para aqui un
    compuesto: «twenty, seventh» no es 27.
    """
    codigos = ([idioma] if idioma in _ORDINALES else list(_ORDINALES))
    # CADA PALABRA SE LLEVA SU IDIOMA. 'fifth' solo esta en la tabla inglesa y
    # 'quinto' solo en la castellana, asi que el sufijo no depende de que
    # alguien haya sabido decir en que idioma va el video -- que es justo lo que
    # fallaba: a `subtitulos` le llega None siempre (ver `_sufijo_ordinal`).
    ordinales, decenas, meses = {}, {}, set()
    for codigo in codigos:
        for palabra, valor in _ORDINALES[codigo].items():
            ordinales.setdefault(palabra, (valor, codigo))
        decenas.update(_DECENAS_ORDINAL.get(codigo) or {})
        meses |= _MESES.get(codigo) or set()
    cortes = set(cortes or ())
    palabras = list(palabras or [])
    llanas = [normalizar_texto(p).strip(".,;:!?()«»\"'") for p in palabras]
    salida, indice = [], 0
    while indice < len(llanas):
        palabra = llanas[indice]
        # 1 · el DIA de una fecha en castellano: «cinco de agosto»
        unidades, _, enlaces, _ = _tablas(idioma)
        # Y NO SI ESE DIA ES LA COLA DE UN NUMERO MAS GRANDE. «treinta y uno de
        # agosto» salia «treinta y 1 de agosto»: esta regla corre antes que el
        # parser general y se llevaba el «uno», asi que el 31 que el general si
        # sabe leer se quedaba sin sitio. Un dia no empieza nunca detras de una
        # 'y', y ese es el unico caso en que pasa.
        if (palabra in unidades and 1 <= unidades[palabra] <= 31
                and indice + 2 < len(llanas)
                and llanas[indice + 1] == "de" and llanas[indice + 2] in meses
                and not (indice and llanas[indice - 1] in enlaces)
                and indice not in cortes):
            salida.append((indice, 1, _entero(unidades[palabra])))
            indice += 3
            continue
        # 2 · un ordinal compuesto: «twenty seventh»
        cuantas, valor, codigo = 0, None, idioma
        siguiente = ordinales.get(llanas[indice + 1]) if indice + 1 < len(llanas) \
            else None
        if (palabra in decenas and siguiente and siguiente[0] < 10
                and indice not in cortes):
            cuantas, valor, codigo = 2, decenas[palabra] + siguiente[0], siguiente[1]
        elif palabra in ordinales:
            cuantas, valor, codigo = 1, ordinales[palabra][0], ordinales[palabra][1]
        if not cuantas:
            indice += 1
            continue
        # 3 · y si ese ordinal se escribe o no: detras de un mes, siempre
        detras_de_mes = bool(indice and llanas[indice - 1] in meses)
        # UN ORDINAL CASTELLANO NO SE ESCRIBE CON CIFRA PELADA. «el 10 paso» no
        # lo escribe nadie: en castellano o va en letra o va con su volada
        # (10.º), y ninguna de las dos es lo que el ingles hace con «10th».
        # Del primero al noveno ya salian en letra, pero por casualidad --valen
        # menos que `MINIMO_EN_CIFRA_SUELTA`--, no por una regla: «decimo» era
        # el primero que llegaba al minimo y se dibujaba con cifra. Medido en el
        # video del oro: «a un decimo de onza» salio «a un 10 de onza», que
        # ademas ahi es una FRACCION y no un ordinal.
        # El codigo lo pone la palabra encontrada, asi que esto no depende de
        # que nadie sepa decir el idioma del video (ver `_sufijo_ordinal`).
        if str(codigo or "").lower().startswith("es") and not detras_de_mes:
            indice += cuantas
            continue
        if detras_de_mes or valor >= MINIMO_EN_CIFRA_SUELTA:
            salida.append((indice, cuantas, _sufijo_ordinal(valor, codigo)))
        indice += cuantas
    return salida


def _digitos_de(idioma=None):
    """Las palabras que valen un digito suelto (0-9) en ese idioma."""
    unidades, _, _, _ = _tablas(idioma)
    return {p: int(v) for p, v in unidades.items() if 0 <= v <= 9}


def _anos_dichos(palabras, idioma=None):
    """Los anos dichos en DOS MITADES. -> [(indice, cuantas, ano)]

    «twenty twenty-four» -> 2024, «nineteen eighty-four» -> 1984.

    Las dos guardas que lo separan de una suma normal, y las dos hicieron falta:
    la segunda mitad tiene que valer DIEZ O MAS -- si no, «twenty five» (que son
    veinticinco) se leeria como el ano 2005 -- y el resultado tiene que caer
    dentro de la horquilla de anos. Con eso, «twenty five people» se queda como
    esta y «twenty twenty-four» sale con sus cuatro cifras.
    """
    unidades, multiplos, enlaces, _ = _tablas(idioma)
    cabezas = dict(_ANOS_CABEZA.get(idioma) or {})
    if not cabezas:
        for codigo in _ANOS_CABEZA:
            cabezas.update(_ANOS_CABEZA[codigo])
    palabras = list(palabras or [])
    salida, i = [], 0
    while i < len(palabras):
        base = cabezas.get(palabras[i])
        if base is None:
            i += 1
            continue
        mejor = None
        # la segunda mitad: dos palabras («eighty four») o una («ten»)
        for cuantas in (2, 1):
            trozo = palabras[i + 1:i + 1 + cuantas]
            if len(trozo) < cuantas or any(p in multiplos or p in enlaces
                                           for p in trozo):
                continue
            valores = [unidades.get(p) for p in trozo]
            if any(v is None for v in valores):
                continue
            if cuantas == 2 and not (valores[0] % 10 == 0 and valores[0] >= 20
                                     and 1 <= valores[1] <= 9):
                continue
            resto = int(sum(valores))
            if not (10 <= resto <= 99):
                continue
            ano = base + resto
            if ANO_MINIMO <= ano <= ANO_MAXIMO:
                mejor = (cuantas, ano)
                break
        if mejor is None:
            i += 1
            continue
        # y no puede seguir un multiplicador: «nineteen eighty thousand» no es
        # un ano, es una cifra
        sigue = (palabras[i + 1 + mejor[0]]
                 if i + 1 + mejor[0] < len(palabras) else "")
        if sigue in multiplos:
            i += 1
            continue
        salida.append((i, 1 + mejor[0], mejor[1]))
        i += 1 + mejor[0]
    return salida


def _series_de_digitos(palabras, idioma=None, cortes=None):
    """Los identificadores dictados digito a digito. -> [(indice, cuantas, texto)]

    «five five three seven» -> «5537». `cortes` es el conjunto de indices
    DESPUES de los cuales el texto crudo llevaba puntuacion: una coma parte la
    serie, porque «two, three, four times» son tres cosas y no el numero 234.
    """
    digitos = _digitos_de(idioma)
    cortes = set(cortes or ())
    palabras = list(palabras or [])
    salida, i = [], 0
    while i < len(palabras):
        if palabras[i] not in digitos:
            i += 1
            continue
        j = i
        while j < len(palabras) and palabras[j] in digitos:
            j += 1
            if j - 1 in cortes:
                break
        if j - i >= DIGITOS_MINIMOS_EN_SERIE:
            salida.append((i, j - i,
                           "".join(str(digitos[p]) for p in palabras[i:j])))
            i = j
            continue
        i += 1
    return salida


def _acaba_en_cola(trozo, colas):
    """True si el tramo termina con una cola de porcentaje ('per cent')."""
    for cola in colas:
        if len(trozo) >= len(cola) and list(trozo[-len(cola):]) == list(cola):
            return True
    return False


def _miles(entero, decimal="."):
    """El entero con separador de miles, si es lo bastante largo.

    EL SEPARADOR DE MILES ES EL CONTRARIO DEL DECIMAL: en castellano la coma
    marca los decimales y el punto los miles, y en ingles al reves. Se deduce
    del decimal en vez de pedir otro parametro porque quien llama ya lo ha
    decidido mirando la palabra dicha (`_separador_decimal`), y dos parametros
    que siempre van juntos son dos sitios donde discrepar.
    """
    texto = str(abs(int(entero)))
    if len(texto) < len(str(MINIMO_CON_SEPARADOR)):
        return str(int(entero))
    miles = "," if decimal == "." else "."
    trozos = []
    while len(texto) > 3:
        trozos.insert(0, texto[-3:])
        texto = texto[:-3]
    trozos.insert(0, texto)
    return ("-" if entero < 0 else "") + miles.join(trozos)


def _entero(valor, separador="."):
    """La cifra tal y como se escribe, sin decimales de mentira."""
    if abs(valor - round(valor)) < 1e-9:
        return _miles(round(valor), separador)
    return f"{valor:.2f}".rstrip("0").rstrip(".").replace(".", separador)


def _monedas_con_decimales(palabras, candidatos, idioma=None):
    """Funde «<entero> <moneda> con <decimales>» en UNA cifra con su simbolo.

    Trabaja sobre los candidatos que ya hay (in situ): el entero puede ser una
    cifra convertida o una debil («un», «una», «one»), y los decimales tienen
    que ser una cifra convertida de dos digitos como mucho. Ver _MONEDAS.
    """
    # sin idioma (p7 no siempre lo trae) se deduce del texto, como el alineador
    lengua = idioma if idioma in _MONEDAS else idioma_de(" ".join(palabras))
    monedas = _MONEDAS.get(lengua) or _MONEDAS["es"]
    conectores = _CON_DECIMALES.get(lengua) or _CON_DECIMALES["es"]
    coma = _DECIMAL.get(lengua, ",")
    por_inicio = {c[0]: c for c in candidatos}
    n = len(palabras)
    i = 0
    while i < n:
        ficha = por_inicio.get(i)
        if ficha:
            fin_entero = ficha[0] + ficha[1]
            entero = ficha[2]
        elif palabras[i] in _DEBILES and palabras[i] not in ("a", "an"):
            fin_entero = i + 1
            entero = "1"
        else:
            i += 1
            continue
        if not entero.isdigit():
            i += 1
            continue
        j = fin_entero
        if j >= n or palabras[j] not in monedas:
            i += 1
            continue
        moneda = palabras[j]
        j += 1
        if j >= n or palabras[j] not in conectores:
            i += 1
            continue
        j += 1
        decimales = por_inicio.get(j)
        if not decimales or not decimales[2].isdigit() or len(decimales[2]) > 2:
            i += 1
            continue
        fin = decimales[0] + decimales[1]
        if fin < n and palabras[fin] in _CENTIMOS:
            fin += 1
        delante, detras = monedas[moneda]
        texto = f"{delante}{entero}{coma}{int(decimales[2]):02d}{detras}"
        # se quitan los candidatos que quedan dentro y se pone el fundido
        candidatos[:] = [c for c in candidatos
                         if not (i <= c[0] < fin)]
        candidatos.append([i, fin - i, texto, True])
        candidatos.sort(key=lambda c: c[0])
        por_inicio = {c[0]: c for c in candidatos}
        i = fin
    return candidatos


def cifras_dichas(palabras, idioma=None, cortes=None):
    """Lo dicho que se ESCRIBE con numeros. -> [(indice, cuantas, texto)]

    Sobre la lista de palabras HABLADAS ya normalizadas (una por elemento). Los
    tramos no se solapan, van en orden, y lo que no se convierte no sale.
    """
    _, multiplos, _, colas = _tablas(idioma)
    palabras = list(palabras or [])
    tomados, candidatos = set(), []

    def libre(inicio, cuantas):
        return not any(k in tomados for k in range(inicio, inicio + cuantas))

    def tomar(inicio, cuantas, texto, forzado=True):
        if cuantas <= 0 or not libre(inicio, cuantas):
            return
        tomados.update(range(inicio, inicio + cuantas))
        candidatos.append([inicio, cuantas, texto, forzado])

    # 1 · el ano en dos mitades, primero: el parser general lo sumaria
    for inicio, cuantas, ano in _anos_dichos(palabras, idioma):
        tomar(inicio, cuantas, str(ano))
    # 2 · la serie de digitos, que el parser general tambien sumaria
    for inicio, cuantas, texto in _series_de_digitos(palabras, idioma, cortes):
        tomar(inicio, cuantas, texto)
    # 3 · los ordinales, ANTES que el parser general porque un compuesto empieza
    # por una decena que el general si conoce: sin esto «twenty seventh» sale
    # «20 seventh», que es peor que dejarlo entero en letra
    for inicio, cuantas, texto in _ordinales_dichos(palabras, idioma, cortes):
        tomar(inicio, cuantas, texto)
    # 4 · y las cifras normales
    for inicio, cuantas, valor in numeros_dichos(palabras, idioma, cortes):
        if not libre(inicio, cuantas):
            continue
        trozo = palabras[inicio:inicio + cuantas]
        escala = multiplos.get(trozo[-1]) if trozo else None
        coma = _separador_decimal(trozo, idioma)
        if (cuantas >= 2 and escala and escala >= MINIMO_CON_MULTIPLO
                and float(valor) >= MINIMO_CON_MULTIPLO):
            # la palabra del multiplicador se conserva TAL Y COMO SE DIJO: es la
            # que hace que «30 million» siga sonando a lo que se oye
            tomar(inicio, cuantas - 1, _entero(float(valor) / escala, coma))
            continue
        if _acaba_en_cola(trozo, colas):
            tomar(inicio, cuantas, _entero(float(valor), coma) + "%")
            continue
        tomar(inicio, cuantas, _entero(float(valor), coma),
              forzado=float(valor) >= MINIMO_EN_CIFRA_SUELTA)

    # EL VECINO ARRASTRA. Una cifra pequena sola se queda en letra, pero dentro
    # de una expresion con otra que si se convierte, dejarla en letra es peor
    # que las dos formas puras: «six out of 10» no lo escribe nadie.
    candidatos.sort(key=lambda c: c[0])
    _monedas_con_decimales(palabras, candidatos, idioma)
    for _ in range(len(candidatos)):
        cambio = False
        for indice, ficha in enumerate(candidatos):
            if ficha[3]:
                continue
            vecinos = []
            if indice:
                vecinos.append(candidatos[indice - 1])
            if indice + 1 < len(candidatos):
                vecinos.append(candidatos[indice + 1])
            for vecino in vecinos:
                if not vecino[3]:
                    continue
                hueco = (ficha[0] - (vecino[0] + vecino[1])
                         if vecino[0] < ficha[0]
                         else vecino[0] - (ficha[0] + ficha[1]))
                if 0 <= hueco <= VECINDAD_CIFRA:
                    ficha[3] = True
                    cambio = True
                    break
        if not cambio:
            break
    return [(c[0], c[1], c[2]) for c in candidatos if c[3]]


def cifras_en(dichas, idioma=None, cortes=None):
    """Como `cifras_dichas`, pero contando en TOKENS y no en palabras sueltas.

    Existe por lo mismo que `numeros_en`: 'sixty-five' es UN token escrito y DOS
    palabras habladas, asi que sin aplanar primero el parser rompe justo en las
    cifras compuestas -- que son las que mas falta hace convertir.

    `cortes` son los indices de TOKEN detras de los cuales habia puntuacion.
    """
    plano, de_quien = [], []
    for indice, entrada in enumerate(dichas or []):
        for trozo in (str(entrada or "").split() or [""]):
            plano.append(trozo)
            de_quien.append(indice)
    cortes_planos = set()
    for indice in (cortes or ()):
        # el corte cae detras de la ULTIMA palabra plana de ese token
        posiciones = [k for k, quien in enumerate(de_quien) if quien == indice]
        if posiciones:
            cortes_planos.add(posiciones[-1])
    salida = []
    for inicio, cuantas, texto in cifras_dichas(plano, idioma, cortes_planos):
        primera = de_quien[inicio]
        ultima = de_quien[min(inicio + cuantas, len(de_quien)) - 1]
        if salida and salida[-1][0] + salida[-1][1] > primera:
            continue            # ya lo cubre el tramo anterior: no se solapan
        # SOLO SI EL TRAMO CUBRE TOKENS ENTEROS. Media palabra convertida
        # («sixty-five» -> «60 five») se lee peor que no convertir ninguna.
        cubre = [k for k, quien in enumerate(de_quien) if primera <= quien <= ultima]
        if cubre != list(range(inicio, inicio + cuantas)):
            continue
        salida.append((primera, ultima - primera + 1, texto))
    return salida


def numeros_en(dichas, idioma=None):
    """Como `numeros_dichos`, pero contando en MARCAS DE TIEMPO y no en palabras.

    No son la misma cuenta: 'sixty-five' es UNA marca de la voz y DOS palabras
    habladas, asi que un numero puede ocupar tres marcas y cinco palabras. Quien
    alinea trabaja en marcas -- la posicion n de la lista es la marca n --, asi
    que el tramo se devuelve en marcas o el ancla caeria en el sitio de al lado.
    """
    plano, de_quien = [], []
    for indice, entrada in enumerate(dichas or []):
        for trozo in (str(entrada or "").split() or [""]):
            plano.append(trozo)
            de_quien.append(indice)
    salida = []
    for inicio, cuantas, valor in numeros_dichos(plano, idioma):
        primera = de_quien[inicio]
        ultima = de_quien[min(inicio + cuantas, len(de_quien)) - 1]
        if salida and salida[-1][0] + salida[-1][1] > primera:
            continue                    # ya lo cubre el tramo anterior: no se solapan
        salida.append((primera, ultima - primera + 1, valor))
    return salida


def casan(escrita, dicha):
    """Si esta palabra escrita y esta palabra dicha son la misma. SIMETRICO.

    Casa el plural con el singular en los dos sentidos, que es lo que una
    cartela hace todo el rato: escribe «accounts» donde se dice «account» y al
    reves. El minimo lo mide la MAS CORTA de las dos, o 'de' casaria con medio
    guion.
    """
    escrita, dicha = str(escrita or ""), str(dicha or "")
    if not escrita or not dicha:
        return False
    if escrita == dicha:
        return True
    corta, larga = ((escrita, dicha) if len(escrita) <= len(dicha)
                    else (dicha, escrita))
    return len(corta) >= MINIMO_SUBCADENA and corta in larga


def piezas_de(termino):
    """Las palabras de un termino escrito, cada una con su valor de cifra.

    [(palabra_llana, valor_o_None)]. El valor sale del token CRUDO por lo que
    dice `valor_numerico`: sobre el normalizado ya no queda ni % ni punto de
    miles con que reconocer una cifra.
    """
    piezas = []
    for crudo in str(termino or "").split():
        llanas = normalizar_texto(crudo).split()
        valor = valor_numerico(crudo)
        if valor is not None:
            # UNA pieza aunque se parta al normalizar: '4.000' es una palabra
            # escrita y vale cuatro mil, no un cuatro seguido de un cero.
            piezas.append((" ".join(llanas), valor))
        elif len(llanas) == 1:
            piezas.append((llanas[0], None))
        else:
            piezas.extend((llana, valor_numerico(llana)) for llana in llanas)
    return piezas


def _tramo_numerico(numeros, desde):
    """El tramo de numero hablado que EMPIEZA justo en `desde`, si lo hay."""
    for inicio, cuantas, valor in numeros:
        if inicio == desde:
            return cuantas, valor
        if inicio > desde:
            break
    return None


def casar_desde(piezas, dichas, desde, numeros=()):
    """Cuantas palabras DICHAS ocupa este termino si empieza justo en `desde`.

    0 si no empieza ahi. Devuelve palabras dichas y no piezas escritas porque
    las dos cuentas dejaron de ser la misma en cuanto «30M» paso a ocupar dos.
    """
    j = desde
    for llana, valor in piezas:
        if j >= len(dichas):
            return 0
        tramo = _tramo_numerico(numeros, j)
        if valor is not None and tramo and abs(tramo[1] - valor) < 1e-6:
            j += tramo[0]                  # la cifra ENTERA, no su primera palabra
            continue
        if not casan(llana, dichas[j]):
            return 0
        j += 1
    return j - desde


def indice_de(palabras, termino, idioma=None):
    """En que palabra de este plano empieza ese termino. (indice, cuantas) o None.

    Es lo que permite que un rotulo entre CUANDO SE DICE lo que rotula y no al
    empezar el plano. Se trabaja en espacio de PALABRAS y no de caracteres
    porque las palabras del plano son exactamente las marcas de tiempo que
    devolvio la voz: la posicion n de esta lista es la marca n.

    `cuantas` son palabras DICHAS: un rotulo de «30M» sobre «thirty million»
    devuelve 2, para que quien escriba palabra a palabra no se salga del tramo.
    """
    piezas = piezas_de(termino)
    if not piezas or not palabras:
        return None
    dichas = [normalizar_texto(p) for p in palabras]
    numeros = (numeros_en(dichas, idioma)
               if any(v is not None for _, v in piezas) else [])
    for i in range(len(dichas)):
        cuantas = casar_desde(piezas, dichas, i, numeros)
        if cuantas:
            return i, cuantas
    return None


def huella_fichero(ruta, bloque=1 << 20):
    """Hash del contenido de un fichero (cadena vacia si no existe)."""
    if not ruta or not os.path.exists(ruta):
        return ""
    resumen = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(bloque), b""):
            resumen.update(trozo)
    return resumen.hexdigest()[:16]


def desempatar(*partes):
    """Entero estable a partir de varias claves: desempata sin usar random."""
    return int(hashlib.sha256("|".join(str(p) for p in partes)
                              .encode("utf-8")).hexdigest()[:8], 16)


# ------------------------------------------------------------------ ficheros

def escribir_texto(ruta, texto):
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return ruta


# ----------------------------------------------------- copiar con Windows en medio
#
# En Windows, un fichero que otro proceso tiene abierto NO SE PUEDE BORRAR, pero
# SI SE PUEDE SOBRESCRIBIR: el modo de comparticion con el que abre Python
# permite lectura y escritura y solo prohibe el borrado.
#
# Eso no es teorico aqui. La interfaz ensena las imagenes de los planos
# leyendolas de la MISMA carpeta de trabajo que se rehace al regenerar los
# assets. Con esa pantalla abierta, el navegador tiene pedidas esas imagenes y
# el servidor las esta sirviendo; y copiar lo recien generado empezaba por
# `shutil.rmtree(destino)`, o sea por borrar exactamente los ficheros que se
# estan mirando. De ahi salia:
#
#     [WinError 32] The process cannot access the file because it is being used
#     by another process
#
# y se caia el paso entero despues de haber pagado el render. Por eso ya no se
# borra para volver a copiar: se copia ENCIMA, que es la operacion que Windows
# si permite, y solo se retira lo que sobra --que ademas casi nunca es nada,
# porque un set rehecho suele traer las mismas camaras--.

#: Cuanto se insiste ante un fichero bloqueado antes de darlo por perdido. Un
#: bloqueo asi casi siempre es una respuesta HTTP terminando de enviarse: dura
#: milisegundos. Esperar dos segundos es barato al lado de un render tirado.
ESPERAS_BLOQUEO = (0.1, 0.25, 0.5, 1.0)


def _insistiendo(tarea):
    """Ejecuta algo que puede chocar con un fichero abierto. -> (valor, fallo)."""
    fallo = None
    for espera in ESPERAS_BLOQUEO + (0,):
        try:
            return tarea(), None
        except PermissionError as choque:     # WinError 32
            fallo = choque
            if espera:
                time.sleep(espera)
    return None, fallo


def borrar(ruta):
    """Borra un fichero aguantando un bloqueo momentaneo. -> se pudo o no.

    QUE UN FICHERO YA NO ESTE ES EXITO, no un error, y por eso el
    FileNotFoundError se traga aqui y no en `_insistiendo`. Entre el `os.walk`
    de `_retirar_sobrantes` y este `os.remove` puede pasar cualquier cosa --el
    navegador que suelta la ultima referencia y Windows completa un borrado que
    tenia pendiente, otra tanda barriendo la misma carpeta-- y el fichero se
    esfuma en medio. La lista que se recorre es una FOTO, no la carpeta.

    Sin esto sube un WinError 2 desde `borrar`, que es la unica funcion del
    modulo que promete no tirar nada (`copiar_carpeta`: «un sobrante no es
    motivo para tumbar el paso»), y se lleva por delante el paso entero DESPUES
    de haber pagado lo que ese paso genera. Visto el 25-08 tumbando
    prueba_piezas con un `fantasma__vista.png` que ya no existia.

    En `_insistiendo` no se puede tragar: de ahi cuelga tambien `copiar`, y ahi
    un fichero que falta es el ORIGEN que no esta, que si es un error de verdad.
    """
    if not os.path.exists(ruta):
        return True
    try:
        _, fallo = _insistiendo(lambda: os.remove(ruta))
    except FileNotFoundError:
        return True
    return fallo is None


def reemplazar(origen, destino):
    """`os.replace` aguantando un bloqueo momentaneo del destino. -> destino.

    ES LA MISMA HISTORIA QUE `borrar`, y por eso comparte la espera: en Windows
    un fichero que otro proceso tiene abierto no se puede ni borrar ni sustituir
    de golpe, y `os.replace` hace las dos cosas a la vez.

    Aqui el «otro proceso» no es una pantalla abierta: es el propio EDGE del
    render. La pagina de las transiciones carga el fotograma que entra como
    TEXTURA por `file://` (`transiciones.componer`) y acto seguido se escribe el
    resultado encima de ese mismo PNG; y el antivirus, que analiza cada fichero
    al cerrarlo, tiene abierto el temporal recien escrito. Los dos bloqueos
    duran milisegundos --medido: se resuelven en el primer reintento-- pero sin
    insistir tumban un lote entero, y con el un render de cuatro minutos ya
    pagado:

        PermissionError: [WinError 32] The process cannot access the file
        because it is being used by another process:
        '...frames\\S003\\f00002.png.tmp.png' -> '...frames\\S003\\f00002.png'

    Si despues de todas las esperas sigue bloqueado, SUBE el fallo original: un
    bloqueo que dura dos segundos no es una carrera, es otra cosa, y taparlo
    dejaria el fotograma sin transicion sin que nadie lo supiera.
    """
    _, fallo = _insistiendo(lambda: os.replace(origen, destino))
    if fallo is not None:
        raise fallo
    return destino


def rehacer_carpeta(ruta):
    """Deja la carpeta VACIA Y EXISTIENDO. -> [lo que se resistio a borrarse].

    `shutil.rmtree(...); os.makedirs(..., exist_ok=True)` parece lo mismo y no
    lo es. Cuando alguien conserva un handle abierto de un fichero de dentro
    --otra vez Edge con sus texturas, o el antivirus analizando el ultimo PNG--
    Windows marca la carpeta como BORRADO PENDIENTE en vez de quitarla: sigue
    saliendo en `os.path.exists`, asi que `makedirs(exist_ok=True)` no hace
    nada, y cuando el handle se suelta la carpeta desaparece **con el render a
    medias**. Lo que se ve es un fotograma cualquiera reventando asi:

        FileNotFoundError: [Errno 2] No such file or directory:
        '...frames\\S008\\f00027.png'

    o sea el sintoma mas confuso posible: la carpeta se creo bien y aun asi no
    esta.

    La cura es no borrar NUNCA la carpeta: se vacia por dentro, fichero a
    fichero y con la misma insistencia que `borrar`. Un fichero en borrado
    pendiente desaparece solo y no arrastra a la carpeta que lo contiene, asi
    que el sitio donde se escribe existe de principio a fin. Lo que resista se
    DICE en la lista que se devuelve --un PNG viejo que sobrevive dentro de una
    secuencia f00001..fNNNNN se colaria en el clip-- en vez de callarse.
    """
    os.makedirs(ruta, exist_ok=True)
    resisten = []
    for raiz, carpetas, nombres in os.walk(ruta, topdown=False):
        for nombre in nombres:
            if not borrar(os.path.join(raiz, nombre)):
                resisten.append(os.path.join(raiz, nombre))
        for carpeta in carpetas:
            shutil.rmtree(os.path.join(raiz, carpeta), ignore_errors=True)
    return resisten


def copiar(origen, destino):
    """Copia fichero o carpeta, creando el destino y pisando lo que hubiera.

    Una carpeta se copia ENCIMA de lo que haya, sin borrarla antes; lo que
    sobre se retira despues. Lo que no se pueda retirar por estar abierto se
    devuelve en la lista de sobrantes de `copiar_carpeta`, que es la version de
    esto que si los mira.
    """
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    if os.path.isdir(origen):
        copiar_carpeta(origen, destino)
    else:
        _, fallo = _insistiendo(lambda: shutil.copy2(origen, destino))
        if fallo is not None:
            raise PermissionError(
                f"no se ha podido escribir {destino}: sigue abierto por otro "
                f"proceso ({fallo})")
    return destino


def copiar_carpeta(origen, destino):
    """Deja `destino` con el contenido de `origen` SIN borrarlo antes.

    Devuelve la lista de ficheros sobrantes que no se han podido retirar por
    estar abiertos. Un sobrante no es motivo para tumbar el paso --lo que se
    acaba de generar esta entero y en su sitio--, pero tampoco se calla: una
    lamina vieja que se queda en la carpeta de un set es una camara fantasma.
    """
    os.makedirs(destino, exist_ok=True)
    for raiz, _, nombres in os.walk(origen):
        relativa = os.path.relpath(raiz, origen)
        carpeta = destino if relativa == "." else os.path.join(destino, relativa)
        os.makedirs(carpeta, exist_ok=True)
        for nombre in nombres:
            desde = os.path.join(raiz, nombre)
            hasta = os.path.join(carpeta, nombre)
            _, fallo = _insistiendo(lambda d=desde, h=hasta: shutil.copy2(d, h))
            if fallo is not None:
                raise PermissionError(
                    f"no se ha podido escribir {hasta}: sigue abierto por otro "
                    f"proceso ({fallo})")
    return _retirar_sobrantes(origen, destino)


def _retirar_sobrantes(origen, destino):
    """Lo que hay en `destino` y ya no esta en `origen`. -> los que resisten."""
    sobrantes = []
    for raiz, carpetas, nombres in os.walk(destino, topdown=False):
        relativa = os.path.relpath(raiz, destino)
        espejo = origen if relativa == "." else os.path.join(origen, relativa)
        for nombre in nombres:
            if os.path.exists(os.path.join(espejo, nombre)):
                continue
            ruta = os.path.join(raiz, nombre)
            if not borrar(ruta):
                sobrantes.append(ruta)
        for carpeta in carpetas:
            if os.path.isdir(os.path.join(espejo, carpeta)):
                continue
            shutil.rmtree(os.path.join(raiz, carpeta), ignore_errors=True)
    return sobrantes


def _sembrar_carpeta(origen, destino):
    """Trae de `origen` lo que falte en `destino`, sin pisar nada de lo que hay.

    FICHERO A FICHERO Y NO CARPETA A CARPETA, y la diferencia costo dinero.
    Aqui habia un `if os.path.exists(destino): continue` antes del `copytree`,
    o sea que si la carpeta de destino EXISTIA --aunque tuviera tres ficheros y
    la version doscientos veintidos-- no se copiaba ni uno.

    Lo que pasaba con eso: `assets` sella su version y la carpeta de trabajo se
    queda con cuatro cosas sueltas. En la pasada siguiente, `escenas` ya existe,
    los 222 PNG no cruzan, y el bucle de planos ve que NINGUNO esta hecho: los
    genera todos otra vez. No se pagan los que la cache del banco devuelve, pero
    si todos los que cambiaron de prompt -- que despues de retocar el audio son
    unos cuantos. Visto el 27-08 pagando imagenes de un video ya dibujado.

    Lo de trabajo GANA cuando existe: es lo que se acaba de escribir en esta
    pasada, y la version es lo de antes.
    """
    os.makedirs(destino, exist_ok=True)
    for nombre in os.listdir(origen):
        uno = os.path.join(origen, nombre)
        otro = os.path.join(destino, nombre)
        if os.path.isdir(uno):
            _sembrar_carpeta(uno, otro)
        elif not os.path.exists(otro):
            shutil.copy2(uno, otro)


def sembrar_trabajo(proyecto, paso_id):
    """Copia la version activa dentro de trabajo/ para no perder lo no rehecho."""
    trabajo = proyecto.ruta_trabajo(paso_id, crear=True)
    if proyecto.version_activa(paso_id) is None:
        return trabajo
    activa = proyecto.ruta_paso(paso_id)
    if not os.path.isdir(activa) or os.path.abspath(activa) == os.path.abspath(trabajo):
        return trabajo
    _sembrar_carpeta(activa, trabajo)
    return trabajo


def salida_de(proyecto, paso_id, claves=(), patrones=(), estado=None):
    """Ruta de un fichero producido por otro paso.

    Se mira primero lo que ese paso registro en estado.json y, si no dice nada
    util, se busca por nombre en la carpeta de su version activa. Asi un paso no
    depende de como haya bautizado sus salidas el paso anterior.

    `estado` es el Estado YA CARGADO de quien llama, y no es un adorno de
    comodidad: sin el, esta funcion se construye uno, y construir un Estado es
    reparsear estado.json ENTERO. En un proyecto con historico son 320 MB y
    ~1,8 s POR LLAMADA -- y pintar la ficha de un paso llama tres veces, asi que
    abrir un video tardaba 6 s leyendo tres veces un fichero que ya estaba en
    memoria. Quien tenga uno cargado que lo pase: leen lo mismo, porque el
    Estado se resincroniza solo cuando el fichero cambia en disco
    (Estado._sincronizar), asi que pasarlo no sirve una foto vieja.
    """
    from nucleo.estado import Estado

    carpeta = proyecto.ruta_paso(paso_id)
    try:
        salidas = (estado if estado is not None else Estado(proyecto)).salidas(paso_id)
    except Exception:
        salidas = {}
    for clave in claves:
        valor = salidas.get(clave)
        if not isinstance(valor, str):
            continue
        candidata = valor if os.path.isabs(valor) else os.path.join(carpeta, valor)
        if os.path.exists(candidata):
            return candidata
    if not os.path.isdir(carpeta):
        return None
    for patron in patrones:
        for raiz, _, ficheros in os.walk(carpeta):
            for fichero in sorted(ficheros):
                if re.fullmatch(patron, fichero, re.IGNORECASE):
                    return os.path.join(raiz, fichero)
    return None


# ------------------------------------------------------------------ externos

def reubicar(ruta):
    """Una ruta del banco escrita en OTRA maquina, traida a esta.

    Devuelve la ruta tal cual si el fichero esta donde dice -- que es lo normal
    y lo que pasa siempre en local -- y, si no esta, la busca en el banco de
    AHORA por los tramos que van despues de `banco/`.

    Existe porque los params guardan rutas ABSOLUTAS de las imagenes de estilo,
    y una ruta absoluta solo vale en la maquina que la escribio: al traer un
    proyecto a otro sitio -- o al mover el banco de sitio -- los ficheros siguen
    ahi y el param apunta al vacio. El sintoma es «ninguna de las imagenes de
    estilo existe en el disco del servidor» con los ficheros delante.

    Y NO SE ARREGLA REESCRIBIENDO EL PARAM, a proposito: esa ruta entra en la
    firma de cada imagen (`_producir_imagen`), asi que cambiarla dejaria
    obsoletas de golpe todas las imagenes ya pagadas del proyecto. Se resuelve
    al leer, que no toca ninguna firma.
    """
    texto = str(ruta or "").strip()
    if not texto or os.path.exists(texto):
        return texto
    # se parte por las DOS barras: no se sabe quien la escribio
    trozos = [t for t in texto.replace("\\", "/").split("/")
              if t and t != "."]
    if ".." in trozos:
        return texto
    nombres = {"banco", os.path.basename(BANCO).lower()}
    for i in range(len(trozos) - 1, -1, -1):
        if trozos[i].lower() in nombres:
            candidato = os.path.join(BANCO, *trozos[i + 1:])
            return candidato if os.path.exists(candidato) else texto
    return texto


def reubicar_todas(rutas):
    """`reubicar` sobre una lista, conservando el orden."""
    return [reubicar(r) for r in (rutas or [])]


def edge():
    for ruta in EDGES:
        if os.path.exists(ruta):
            return ruta
    raise RuntimeError("no se encuentra msedge.exe")


def ffmpeg():
    """El ejecutable de ffmpeg. `ESTUDIO_FFMPEG` manda sobre el PATH.

    La variable existe por lo mismo que `ESTUDIO_EDGE`: ffmpeg se instala de
    veinte maneras y en un servidor recien puesto a veces esta donde esta y no
    en el PATH del servicio. Sin ella, la unica salida era tocar el PATH de
    systemd, que es un sitio raro para configurar un programa.
    """
    puesto = (os.environ.get("ESTUDIO_FFMPEG") or "").strip().strip('"')
    if puesto:
        if os.path.isfile(puesto):
            return puesto
        raise RuntimeError(
            f"ESTUDIO_FFMPEG apunta a {puesto} y ahi no hay nada: quitala o "
            f"corrigela (si no, se busca ffmpeg en el PATH)")
    ruta = shutil.which("ffmpeg")
    if not ruta:
        raise RuntimeError("no se encuentra ffmpeg en el PATH: instalalo o pon "
                           "ESTUDIO_FFMPEG con la ruta del ejecutable")
    return ruta


def ffprobe():
    """Y su hermano. Va donde vaya ffmpeg: se instalan juntos."""
    puesto = (os.environ.get("ESTUDIO_FFPROBE") or "").strip().strip('"')
    if puesto and os.path.isfile(puesto):
        return puesto
    encontrado = shutil.which("ffprobe")
    if encontrado:
        return encontrado
    # al lado de ffmpeg, que es donde lo deja cualquier instalador
    cerca = ffmpeg()
    for nombre in ("ffprobe.exe", "ffprobe"):
        vecino = os.path.join(os.path.dirname(cerca), nombre)
        if os.path.isfile(vecino):
            return vecino
    return cerca.replace("ffmpeg.exe", "ffprobe.exe")


#: Cuantas veces se le pide un PNG a Edge antes de darlo por imposible, y
#: cuanto se espera entre una y otra. Tres y medio segundo: el fallo suelto se
#: resuelve en el primer reintento, y tres intentos de algo que de verdad no se
#: puede pintar cuestan un segundo y medio, no una tanda.
INTENTOS_RASTERIZAR = 3
ESPERA_RASTERIZAR_S = 0.5

#: Por debajo de esto, un rasterizado A CUADRO COMPLETO huele a pagina de error.
#: Los cuadros compuestos de verdad rondan 1,5 MB y los malos salieron de 27 KB.
#: Solo se mira a partir de 1280 de ancho: una capa suelta de 40x20 pesa 113
#: bytes con toda la razon, y avisar de eso seria ruido en cada plano.
MINIMO_RASTERIZADO_BYTES = 40000


def rasterizar(svg, destino, ancho, alto, transparente=True, espera_ms=1800):
    """SVG (ruta o texto) -> PNG con Edge headless.

    Se usa el navegador y no cairosvg porque en esta maquina cairo no esta
    instalado y, sobre todo, porque el navegador es el mismo motor que pinta el
    render final: lo que se ve aqui es lo que se vera en el video.
    """
    destino = os.path.abspath(destino)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    temporal = None
    if "<svg" in str(svg)[:2000]:
        temporal = tempfile.NamedTemporaryFile("w", suffix=".svg", delete=False,
                                               encoding="utf-8")
        temporal.write(svg)
        temporal.close()
        ruta_svg = temporal.name
    else:
        ruta_svg = os.path.abspath(svg)
        # QUE EL FICHERO ESTE, ANTES DE ABRIR EDGE.
        #
        # Edge no falla cuando no encuentra lo que le pides: pinta SU pagina de
        # error --«File not found»-- y la fotografia tan contento. O sea que el
        # PNG aparece, `rasterizar` lo da por bueno, y lo que se guarda como
        # fotograma es una captura de un mensaje de error de un navegador.
        #
        # Se vio el 28-08 en el previsualizador: doscientos siete cuadros
        # compuestos de 27 KB, todos con la misma pantalla blanca puesta donde
        # tenia que ir el plano. Nadie levanto en ningun sitio.
        # SE ESPERA UN POCO ANTES DE RENDIRSE. Lo normal es que este; lo que se
        # cubre aqui es el caso en que se ACABA de escribir y todavia no ha
        # aterrizado -- el antivirus lo tiene abierto al cerrarlo, o el disco
        # va justo. `previsualizar` escribe su HTML y lanza Edge acto seguido,
        # y una maquina desatendida y a tope es donde eso se nota.
        for espera in ESPERAS_BLOQUEO:
            if os.path.exists(ruta_svg):
                break
            time.sleep(espera)
        if not os.path.exists(ruta_svg):
            raise RuntimeError(
                f"no existe lo que hay que rasterizar: {ruta_svg}")

    # SE INSISTE, PORQUE EDGE FALLA SUELTO Y NO POR EL SVG.
    #
    # Una llamada, un perfil nuevo y un proceso nuevo cada vez: en una maquina
    # ocupada --y aqui lo esta, con el render y las imagenes a la vez-- de
    # ciento y pico rasterizados uno se cae sin dar motivo, y el PNG no aparece.
    # Visto el 27-08 tumbando una tanda entera en `previo/S003.png`, con los
    # 222 planos ya calculados.
    #
    # Con el MISMO SVG el segundo intento va: si el SVG estuviera mal fallarian
    # los tres igual, asi que insistir no tapa un error de verdad -- solo
    # distingue "esto no se puede pintar" de "esta vez no salio".
    ultimo = ""
    for intento in range(1, INTENTOS_RASTERIZAR + 1):
        perfil = tempfile.mkdtemp(prefix="edge_ras_")
        orden = [edge(), "--headless", "--disable-gpu", "--no-first-run",
                 "--disable-extensions", "--hide-scrollbars",
                 f"--user-data-dir={perfil}",
                 f"--screenshot={destino}",
                 f"--window-size={int(ancho)},{int(alto)}",
                 f"--virtual-time-budget={int(espera_ms)}"]
        if transparente:
            orden.append("--default-background-color=00000000")
        orden.append("file:///" + ruta_svg.replace("\\", "/"))
        try:
            hecho = subprocess.run(orden, capture_output=True, timeout=180,
                                   **SIN_VENTANA)
            ultimo = (hecho.stderr or b"").decode("utf-8", "replace")[-300:]
        except subprocess.TimeoutExpired:
            ultimo = "Edge no contesto en 180 s"
        finally:
            shutil.rmtree(perfil, ignore_errors=True)
        if os.path.exists(destino):
            break
        if intento < INTENTOS_RASTERIZAR:
            time.sleep(ESPERA_RASTERIZAR_S)
    if temporal:
        os.unlink(temporal.name)
    if not os.path.exists(destino):
        raise RuntimeError(
            f"Edge no genero {destino} en {INTENTOS_RASTERIZAR} intentos"
            + (f": {ultimo.strip()}" if ultimo.strip() else ""))
    # Y QUE NO SEA LA PAGINA DE ERROR. Con el guardian de arriba no deberia
    # pasar --lo que se abre existe-- pero un `file://` roto DENTRO de la pagina
    # (una imagen que no esta) da el mismo dibujo: casi todo blanco y muy poco
    # peso. Un fotograma de verdad de 1920x1080 no baja de unas decenas de KB;
    # los que salieron mal pesaban 27 KB con una pantalla blanca dentro.
    #
    # Es un olfato, no una prueba, asi que solo AVISA por consola: levantar aqui
    # tumbaria un render por un cuadro plano legitimo (un fundido a negro).
    if (int(ancho) >= 1280 and os.path.getsize(destino)
            < MINIMO_RASTERIZADO_BYTES):
        print(f"[medios] aviso: {os.path.basename(destino)} ha salido de "
              f"{os.path.getsize(destino)} bytes; comprueba que no sea una "
              f"pagina de error", flush=True)
    return destino


def duracion_media(ruta):
    """Duracion en segundos de un audio o un video, leida con ffprobe."""
    orden = [ffprobe(), "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", ruta]
    salida = subprocess.run(orden, capture_output=True, text=True, timeout=120,
                            **SIN_VENTANA)
    try:
        return float(salida.stdout.strip())
    except ValueError:
        return 0.0

