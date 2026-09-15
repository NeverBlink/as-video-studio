r"""
LAS LLAMADAS A LA ACCION del video: la presentacion y los dos momentos en que se
le pide algo a quien mira.

Que decide este modulo
----------------------
Tres momentos, y los tres son iguales por dentro: una casilla y lo que se quiere
que se diga.

    cta = {
      "presentacion": {"puesto": false, "texto": ""},
      "cta_medio":    {"puesto": false, "texto": ""},
      "cta_final":    {"puesto": false, "texto": ""},
    }

Son tres casillas INDEPENDIENTES y las tres vienen APAGADAS: se marca solo lo
que se quiera --solo la presentacion, solo el cierre, las tres o ninguna--. Un
video no pide nada mientras nadie diga que lo pida: lo que se cuela solo es lo
que nadie ha decidido. Y los tres son iguales a proposito --la presentacion no
pide nada y las otras dos si, pero desde la pantalla y desde el prompt son el
mismo gesto: se deja de narrar y se habla a quien esta mirando--; separarlos en
dos mecanismos habria dado dos sitios donde escribir lo mismo.

LO QUE SE ESCRIBE ES UNA INDICACION, NO UN TEXTO FINAL
------------------------------------------------------
En la casilla se dice QUE se quiere que pida --«que se suscriba», «que visite mi
web», «que se apunte a la lista»-- y el redactor lo escribe con las palabras de
ESE video. No es una plantilla que se pega tal cual, y por eso el prompt lo
llama patron: una frase identica repetida en cada video se oye como una cuna.

Aqui no se busca nada fuera. Lo que hay es lo que se escribe: ni catalogos de
producto, ni material de la web, ni enlaces que alguien tenga que mantener al
dia. Un desplegable de productos obligaba a acordarse de dos sitios --el ajuste
y el encargo-- y el dia que no coincidieran ganaba el que nadie miraba.

SON DEL VIDEO, Y SOLO DEL VIDEO
-------------------------------
Viven en los params del guion, asi que cambiarlos deja obsoleto el guion y lo
que cuelga de el, que es justo lo que tiene que pasar: el texto que se redacta
depende de ellos.

Y NO viajan en el preset de estilo, a proposito. Se deciden al encargar CADA
video, que es donde se sabe que se quiere pedir esta vez: un video puede querer
mandar a la web y el siguiente solo pedir un comentario. Si el estilo se las
llevara, elegir un estilo pisaria lo que se acaba de escribir para este video
--lo contrario de lo que espera quien elige un estilo--, y habria dos sitios
donde mirar cuando lo que sale no es lo que se pidio.
"""
import copy

PASO = "guion"

#: Los tres momentos, en el orden en que salen en el video.
MOMENTOS = ("presentacion", "cta_medio", "cta_final")

#: Los dos que son una llamada a la accion. La presentacion no lo es --no pide
#: nada-- y por eso se cuenta aparte cuando hay que decir cuantas hay.
LLAMADAS = ("cta_medio", "cta_final")

#: Como se llama cada uno en la pantalla y en los avisos.
ETIQUETA = {
    "presentacion": "la presentacion",
    "cta_medio": "la llamada a la accion de mitad",
    "cta_final": "la llamada a la accion del cierre",
}

#: Donde cae cada uno. Es lo que el redactor necesita para colocarlo, y se dice
#: en terminos del guion --bloques y tramos-- porque es lo unico que el ve.
SITIO = {
    "presentacion": ("EN EL PRIMER BLOQUE DESPUES DEL GANCHO de entrada, nunca "
                     "en el propio gancho: el gancho es lo unico que sujeta a "
                     "quien acaba de llegar."),
    "cta_medio": ("A MITAD DEL VIDEO, en el corte entre dos tramos y justo "
                  "despues de haber contado algo que se sostiene solo. Se apoya "
                  "en lo que se acaba de explicar; no se mete en medio de una "
                  "explicacion."),
    "cta_final": ("EN EL ULTIMO BLOQUE, como cierre. Es la unica que puede "
                  "pedir dos cosas seguidas, y aun asi corta."),
}

#: Lo que se dice en cada momento cuando nadie ha escrito nada. No es un texto
#: prefabricado --el redactor lo escribe con sus palabras-- sino QUE decir.
POR_OMISION = {
    "presentacion": ("quien eres y que se va a ver en este video, en una frase "
                     "y sin curriculum"),
    "cta_medio": "que se suscriba o deje un comentario",
    "cta_final": "que se suscriba y vea otro video del canal",
}

#: Lo que lleva un video que no ha tocado nada: NADA. Las tres apagadas, y es
#: deliberado -- un video no se presenta ni pide nada mientras nadie lo marque.
POR_DEFECTO = {
    "presentacion": {"puesto": False, "texto": ""},
    "cta_medio": {"puesto": False, "texto": ""},
    "cta_final": {"puesto": False, "texto": ""},
}

#: Un parrafo largo describiendo una llamada a la accion no es una llamada a la
#: accion: es un guion escrito en la casilla de al lado. El tope corta ahi.
MAX_TEXTO = 600


# ------------------------------------------------------------------- params

#: Lo que este modulo aporta a los params del guion: un solo sitio donde estan
#: escritos los defectos.
PARAMS_POR_DEFECTO = {"cta": copy.deepcopy(POR_DEFECTO)}


def normalizar(crudo, estricto=True):
    """Los tres momentos, completos y con los tipos correctos.

    SIN NADA GUARDADO, LOS TRES APAGADOS. La pantalla lee lo GUARDADO, asi que
    no se deduce nada aqui: una pantalla que dice una cosa y un video que hace
    otra es peor que una casilla que se marca en un clic.
    """
    ficha = copy.deepcopy(POR_DEFECTO)
    if crudo in (None, ""):
        return ficha
    if not isinstance(crudo, dict):
        if estricto:
            raise ValueError("cta tiene que ser un objeto con presentacion, "
                             "cta_medio y cta_final")
        return ficha
    for momento in MOMENTOS:
        ranura = crudo.get(momento)
        if ranura in (None, ""):
            continue
        if not isinstance(ranura, dict):
            if estricto:
                raise ValueError(f"cta.{momento} tiene que ser un objeto con "
                                 f"puesto y texto")
            continue
        destino = ficha[momento]
        if "puesto" in ranura:
            destino["puesto"] = bool(ranura["puesto"])
        texto = " ".join(str(ranura.get("texto") or "").split())
        if estricto and len(texto) > MAX_TEXTO:
            raise ValueError(f"lo que se pide en {ETIQUETA[momento]} son "
                             f"{len(texto)} caracteres y el tope son "
                             f"{MAX_TEXTO}: es una frase, no un guion")
        destino["texto"] = texto[:MAX_TEXTO]
    return ficha


def _normalizar(params, estricto=True):
    """Lo que este modulo aporta a los params ya normalizados del guion."""
    return {"cta": normalizar((params or {}).get("cta"), estricto=estricto)}


def activos(ficha):
    """Los momentos que este video lleva de verdad. -> [(momento, ranura)]"""
    ficha = ficha if isinstance(ficha, dict) else {}
    return [(m, ficha[m]) for m in MOMENTOS
            if isinstance(ficha.get(m), dict) and ficha[m].get("puesto")]


def describir(ficha):
    """Una linea para la bitacora: que momentos lleva el video."""
    puestos = [ETIQUETA[m] for m, _ in activos(ficha)]
    if not puestos:
        return "sin presentacion ni llamadas a la accion"
    return ", ".join(puestos)


# ------------------------------------------------------- el bloque del prompt

def bloque_para_guion(ficha):
    """El trozo del prompt que explica los tres momentos. -> str o ""

    Se escribe ANTES de redactar y no se cose despues: una llamada a la accion
    cosida sobre un guion terminado se nota porque el bloque anterior no la
    prepara. Aqui el redactor sabe desde el principio cuantas hay y donde caen,
    y puede rematar el bloque de antes para que la peticion caiga en su sitio.
    """
    puestos = activos(ficha)
    if not puestos:
        return ""
    lineas = [
        "== LA PRESENTACION Y LAS LLAMADAS A LA ACCION ==",
        "Estos bloques son bloques del guion como los demas --misma voz, primera "
        "persona, mismo tono y las mismas palabras por bloque--; lo unico que "
        "los distingue es que en ellos se deja de narrar y se habla a quien esta "
        "mirando. Se te dicen ahora, y no despues, para que el bloque anterior "
        "los prepare: una peticion que cae de golpe se nota.",
        "",
    ]
    for momento, ranura in puestos:
        lineas.append(f"  · {ETIQUETA[momento].upper()} -- {SITIO[momento]}")
        pedido = str(ranura.get("texto") or "").strip()
        if momento == "presentacion":
            if pedido:
                lineas.append(f"    Asi se presenta este canal (es el PATRON, no "
                              f"el texto: adaptalo a lo que se ensena en ESTE "
                              f"video, sin copiarlo palabra por palabra): "
                              f"«{pedido}»")
            else:
                lineas.append(f"    Que dice: {POR_OMISION[momento]}. Del tipo "
                              f"«en este video te voy a contar...».")
        else:
            lineas.append(f"    Que pide: {pedido or POR_OMISION[momento]}")
    lineas.extend([
        "",
        "COMO SE ESCRIBEN: una o dos frases, en primera persona, con las "
        "palabras del video y no con las de un anuncio. Se pide UNA cosa por "
        "bloque (la del cierre puede pedir dos). Nada de «no olvides», «dale a "
        "la campanita» ni superlativos. Si el video acaba de contar algo que da "
        "pie a la peticion, se usa: esa es la unica forma de que no suene "
        "pegada.",
    ])
    if len([m for m, _ in puestos if m in LLAMADAS]) > 1:
        lineas.append(
            "NO SE REPITEN ENTRE SI. Las dos llamadas de este video no piden lo "
            "mismo con las mismas palabras; si las dos acaban siendo "
            "«suscribete», cambia una por otra cosa (comentar, ver otro video).")
    return "\n".join(lineas)
