"""
El PRESET DE CANAL entero, decidido en cuatro campos y generado de una tirada.

QUE PROBLEMA RESUELVE
---------------------
El modo editor toma las decisiones de un canal repartidas por cinco pantallas:
pegar la URL del video de estilo, extraer doscientos fotogramas, elegir
veinticuatro, escribir la guia, dibujar el moodboard, aprobarlo mirandolo,
escribir el tono, buscar la voz entre ochocientas. Cada una de esas paradas es
una decision buena --por eso el modo editor sigue entero y no cambia-- pero
para montar un canal NUEVO son ocho paradas antes de haber hecho un solo video.

El modo light hace las mismas ocho cosas y no para en ninguna. Se le dan cuatro
datos:

    estilo grafico    un video de YouTube  o  una descripcion escrita
    tono del guion    un video de YouTube  o  una descripcion escrita
    voz               una descripcion escrita
    idioma            uno, elegido a mano

y de ahi sale el preset de canal completo: fotogramas, guia de estilo,
referencias dibujadas, grafismo, instrucciones de guion, voz y mandos. Lo que se
ensena al final son CUATRO cosas --el estilo grafico, el tono, la voz y el
idioma-- y nada mas. No hay desglose: si algo no convence se pide en una frase
("que los subtitulos sean mas claros") y se rehace ESA de las tres.

POR QUE ES EL TIPO 'canal' Y NO UN TIPO NUEVO
---------------------------------------------
Porque es exactamente lo que el tipo 'canal' ya guardaba: guion + estilo + voz +
grafismo. Un tipo nuevo habria dado dos clases de preset que fijan lo mismo, dos
sitios donde aplicar y dos que mantener, y el dia que se anadiera una clave a
uno el otro se quedaria viejo en silencio. Lo unico que hacia falta era guardar
DE DONDE salio (`presets_canal.CLAVES_ORIGEN`), que es lo que permite rehacer
una parte sin volver a pedirlo todo.

Consecuencia buena: un preset hecho aqui se aplica en el modo editor igual que
cualquier otro, y uno montado a mano alli sale en esta galeria en cuanto sea de
tipo canal.

POR QUE SE GENERA EN UN PROYECTO
--------------------------------
Todo lo que hace falta --extraer, elegir, escribir la guia, dibujar, describir la
voz-- son las MISMAS funciones que corren los botones del modo editor, y todas
trabajan sobre un proyecto: ahi viven los fotogramas, los params y la bitacora.
Asi que el preset se genera en un proyecto TALLER, oculto de la lista, y al
acabar se congela en el preset. No hay un camino "automatico" y otro "a mano":
hay un camino, llamado desde dos sitios.

El taller se queda despues de guardar, y esa es la razon de que rehacer solo el
tono no vuelva a bajar ningun video: los fotogramas siguen ahi. Se borra con el
preset.

EL MOODBOARD SE APRUEBA SOLO, Y AQUI ESTA EL PORQUE
---------------------------------------------------
`moodboard.py` dice --y sigue siendo verdad-- que las laminas dibujadas pueden
derivar, y que por eso nacen PROPUESTAS y las aprueba una persona mirandolas. En
este modo no hay nadie mirando a mitad de camino: pararse ahi seria volver a las
ocho paradas.

Lo que se hace es mover la mirada al FINAL, no quitarla: lo primero que se ve de
un preset recien hecho son LAS PROPIAS LAMINAS del moodboard con la cartela y el
subtitulo puestos encima, o sea exactamente lo que va a salir en los videos. Si
deriva, se ve ahi, y se corrige con una frase. Decidido por el canal el
23-08-2026; que las muestras fueran las laminas y no cuatro planos dibujados
aparte, el 24-08.
"""
import copy
import os
import re
import random

try:
    from . import cartelas, cta, estadisticas, medios, moodboard, p7_callouts
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cartelas
    import cta
    import estadisticas
    import medios
    import moodboard
    import p7_callouts


# ===========================================================================
# LAS TAREAS
#
# Misma forma que `recetas.TAREAS` y por el mismo motivo: aqui viven los DATOS
# --que hay, de que depende cada una, cual cuesta dinero, cuanto tarda-- y en
# app.py vive QUE FUNCION corre cada una, que es la misma que corre su boton del
# modo editor.
#
#   segundos   lo que se espera que tarde, para que la barra sea REALISTA. Si el
#              historial de `estadisticas` tiene medidas de ese paso manda el
#              historial; esto es el respaldo del primer dia. La barra se reparte
#              por TIEMPO y no por numero de tareas: con ocho tareas de las que
#              una dura cuatro minutos y otra dos segundos, contar tareas da una
#              barra que se planta en el 12 % y salta al 90 %.
#   paso       el paso de `estadisticas` del que sacar la medida, si tiene uno
#   cuesta     si gasta dinero de verdad (imagenes). Lo que va por el CLI no
#              cuesta: va por la suscripcion.
#   imagenes   cuantas imagenes paga. Se declara y no se deduce porque es lo
#              unico que se puede decir ANTES de pulsar, y decirlo antes es
#              la regla de esta casa: «Regenerar todo» dice lo que cuesta con
#              la cifra delante, y esto no puede ser menos.
#   solo       'video' o 'prompt' si la tarea solo existe en uno de los dos
#              caminos del estilo grafico
# ===========================================================================

TAREAS = [
    {"id": "guia", "nombre": "La guía de estilo",
     "necesita": [], "segundos": 60, "paso": "guia_estilo",
     "tamano": 24, "cuesta": False,
     "porque": "escribe por escrito cómo tiene que verse el vídeo"},
    {"id": "referencias", "nombre": "Las referencias de estilo",
     "necesita": ["guia"], "segundos": 120, "paso": "moodboard", "tamano": 6,
     "cuesta": True, "imagenes": 6,
     "porque": "genera una cara, unos cuerpos, un interior y un objeto en ese "
               "estilo: es lo que después copia cada plano"},
    {"id": "grafismo", "nombre": "El grafismo",
     "necesita": ["guia"], "segundos": 3, "paso": "", "tamano": 0,
     "cuesta": False,
     "porque": "saca de la guía el set de diseño y la paleta del texto en "
               "pantalla; no llama a ningún modelo"},
    {"id": "tono", "nombre": "El tono del guion",
     "necesita": [], "segundos": 60, "paso": "tono", "tamano": 1, "cuesta": False,
     "porque": "escribe las instrucciones con las que se redactarán los guiones"},
    {"id": "voz", "nombre": "La voz",
     "necesita": [], "segundos": 80, "paso": "voz_descrita", "tamano": 0,
     "cuesta": False,
     "porque": "elige la voz y sus mandos a partir de cómo has dicho que suene"},
    {"id": "muestra", "nombre": "Las muestras del preset",
     "necesita": ["referencias", "grafismo"], "segundos": 45, "paso": "",
     "tamano": 0, "cuesta": False,
     "porque": "pone la cartela y el subtítulo sobre las referencias ya "
               "dibujadas: es lo que se ve en la tarjeta y lo que hay que mirar"},
]

# ===========================================================================
# COMO SE CUENTA ESTO EN PUBLICO
#
# La misma tabla que `recetas.PUBLICO` y con las mismas reglas -- se dice QUE se
# esta consiguiendo y no COMO, en gerundio, sin una palabra de la cocina -- pero
# para la creacion de un ESTILO. Esta es ademas la primera barra que se ve al
# entrar en el modo light, o sea la primera que se graba.
#
# La regla de seguridad es la misma: una tarea que no este aqui dice
# «Trabajando» y se calla, nunca el nombre de casa.
# ===========================================================================

PUBLICO = {
    "guia": {
        "nombre": "Entendiendo el concepto visual",
        "fases": ["leyendo la imagen", "escribiendo el criterio"],
    },
    "referencias": {
        "nombre": "Dibujando tu mundo",
        "fases": ["dando cara a la gente", "levantando los lugares",
                  "rematando los detalles"],
    },
    "grafismo": {
        "nombre": "Definiendo la identidad",
        "fases": ["eligiendo colores y letras"],
    },
    "tono": {
        "nombre": "Aprendiendo tu forma de contar",
        "fases": ["leyendo cómo hablas", "escribiendo el criterio del relato"],
    },
    "voz": {
        "nombre": "Buscando la voz",
        "fases": ["escuchando candidatas", "afinando el timbre"],
    },
    "muestra": {
        "nombre": "Preparando las muestras",
        "fases": ["montando el ejemplo que vas a ver"],
    },
}

#: Lo que se dice de una tarea que no esta en la tabla. Igual que en `recetas`.
PUBLICO_GENERICO = "Trabajando"


def publico_de(tid, fraccion=None):
    """Como se cuenta una tarea del estilo en publico. Ver `recetas.publico_de`."""
    ficha = PUBLICO.get(str(tid)) or {}
    titulo = ficha.get("nombre") or PUBLICO_GENERICO
    fases = ficha.get("fases") or []
    if not fases or fraccion is None:
        return titulo
    try:
        valor = min(1.0, max(0.0, float(fraccion)))
    except (TypeError, ValueError):
        return titulo
    indice = min(len(fases) - 1, int(valor * len(fases)))
    return f"{titulo} — {fases[indice]}"


TAREAS_POR_ID = {t["id"]: t for t in TAREAS}

#: Que tareas rehace cada uno de los tres botones de feedback. Son TRES y no
#: ocho a proposito: el canal ve tres cosas, asi que corrige tres cosas.
#:
#: Corregir el estilo grafico NO vuelve a bajar el video ni a elegir fotogramas:
#: eso ya esta hecho en el taller y no ha cambiado. Lo que se rehace es lo que
#: la correccion puede tocar -- la guia escrita, lo dibujado a partir de ella, el
#: grafismo que sale de ella y las muestras.
PARTES = {
    "estilo": {
        "nombre": "el estilo gráfico",
        "tareas": ("guia", "referencias", "grafismo", "muestra"),
    },
    "tono": {"nombre": "el tono del guion", "tareas": ("tono",)},
    "voz": {"nombre": "la voz", "tareas": ("voz",)},
}

def tareas_de_estilo(encargo):
    """Que hay que rehacer para cambiar el estilo grafico. -> tupla

    Son siempre las mismas, y por eso `encargo` no se mira: el estilo sale de
    las imagenes adjuntas y de lo escrito, y las dos cosas ya estan en el
    taller. Se queda como funcion --y con su argumento-- porque es el sitio
    donde declarar una excepcion si algun dia una fuente nueva obliga a
    rehacer algo antes.
    """
    return PARTES["estilo"]["tareas"]


def imagenes_de_parte(parte, encargo=None):
    """Cuantas imagenes paga rehacer esa parte. -> int

    Se suma de la tabla y no se escribe en ningun otro sitio: la pantalla decia
    «10 imágenes» a mano --seis referencias mas cuatro muestras-- y el dia que
    las muestras dejaron de dibujarse el numero se quedo mintiendo. Decir el
    precio antes de pulsar es la regla de esta casa; para eso tiene que salir de
    donde esta el precio.
    """
    ficha = PARTES.get(parte) or {}
    return sum(int((TAREAS_POR_ID.get(t) or {}).get("imagenes") or 0)
               for t in ficha.get("tareas", ()))


#: CAMBIAR EL IDIOMA NO ES REHACER EL ESTILO, y por eso no esta en PARTES: no
#: sale como boton de feedback, lo dispara el desplegable de idioma.
#:
#: Lo que hay que adaptar son las dos cosas que llevan LENGUA dentro:
#:
#:   tono      las instrucciones del guion se escriben en el idioma del canal
#:             (`tono.nombre_de_idioma`), asi que en otro idioma hay que
#:             reescribirlas. Es una llamada al CLI: por suscripcion, gratis.
#:   muestra   el subtitulo y la cartela de las muestras van DIBUJADOS en la
#:             imagen. Pero no hay nada que volver a dibujar: la muestra es una
#:             referencia del estilo con el texto encima, y la referencia limpia
#:             sigue donde estaba. Recomponer es rasterizar, que no cuesta.
#:
#: Lo que NO se toca: la guia de estilo (va en ingles porque la lee un generador
#: de imagenes, no una persona), las referencias dibujadas, el grafismo y la voz
#: --que ya se eligio para el idioma nuevo al escribirlo en los params--.
#:
#: Total: cero imagenes y unos cuarenta segundos. Que es lo que hace que
#: duplicar un estilo y cambiarle el idioma sea una operacion normal y no una
#: regeneracion.
#:
#: CON UNA SALVEDAD, desde el 24-08-2026 por la noche: las referencias dibujadas
#: pueden llevar LETRAS DENTRO --el eje «diagrama» las lleva casi siempre-- y
#: esas se dibujaron en el idioma que tenia el canal ese dia. Al cambiar de
#: idioma se quedan en el anterior, y como esas laminas viajan despues como
#: referencia dentro de cada plano con componentes, ensenan a rotular en el
#: idioma viejo CON UN EJEMPLO DIBUJADO.
#:
#: `referencias` NO se anade aqui a proposito: convertiria cambiar de idioma en
#: una operacion de seis imagenes, que es justo lo que esta tupla existe para
#: evitar. Se DICE, con el precio delante (`aviso_de_idioma`), y lo decide quien
#: mira.
TAREAS_DE_IDIOMA = ("tono", "muestra")

#: Los seis del modo light, en castellano y para leer. Escritos aqui y no
#: importados: este modulo se carga el ULTIMO del paquete y subir el import
#: seria un circulo. Son seis palabras.
_NOMBRES_LLANOS = {"es": "castellano", "en": "inglés", "pt": "portugués",
                   "fr": "francés", "it": "italiano", "de": "alemán"}

#: Lo que se le cuenta a quien acaba de cambiar el idioma de un canal, con el
#: precio delante. Aqui hace mas falta que en otros sitios: lo que se acaba de
#: hacer fue gratis y lo que se ofrece cuesta.
AVISO_LAMINAS_EN_OTRO_IDIOMA = (
    "las láminas de estilo se dibujaron en {anterior} y ahí se quedan: si "
    "alguna lleva letras dentro (el diagrama casi siempre las lleva), seguirá "
    "rotulada en {anterior} y los vídeos la copiarán. Para pasarlas a {nuevo} "
    "hay que regenerar el estilo: {imagenes} imágenes, unos {usd} $."
)


def aviso_de_idioma(anterior, nuevo, calidad="medium"):
    """El aviso con su precio, o "" si no hay nada que avisar. -> str"""
    anterior = str(anterior or "").strip().lower()
    nuevo = str(nuevo or "").strip().lower()
    if not anterior or not nuevo or anterior == nuevo:
        return ""
    imagenes = imagenes_de_parte("estilo")
    if not imagenes:
        return ""
    por_imagen = USD_POR_IMAGEN.get(str(calidad or "medium"),
                                    USD_POR_IMAGEN["medium"])
    return AVISO_LAMINAS_EN_OTRO_IDIOMA.format(
        anterior=_NOMBRES_LLANOS.get(anterior, anterior),
        nuevo=_NOMBRES_LLANOS.get(nuevo, nuevo),
        imagenes=imagenes,
        usd=f"{imagenes * por_imagen:.2f}".replace(".", ","))



# ===========================================================================
# EL RITMO DEL VIDEO
#
# UN SOLO MANDO QUE RELLENA CINCO CAMPOS. Los cinco existen ya en el modo editor
# y no cambia ninguno: el ritmo no toca el segmentador, ni las cabeceras, ni el
# corte en planos. Rellena lo que alli se escribe a mano.
#
#     min_s, max_s, min_s_rotulos   la horquilla de duracion de un plano
#     velocidad, hueco_minimo       de la voz -- y con reglas distintas, ver abajo
#
# LOS NUMEROS NO SON REDONDOS, SON LOS QUE EL MOTOR PUEDE CUMPLIR. Dos limites
# del segmentador (motores/guion/segmentar.py) mandan sobre lo que se pida aqui:
#
#   - SUELO_S = 2 y TECHO_S = 8 acotan que corte es LEGAL, y la regla dura
#     --un plano no puede tragarse un punto interior si partir ahi es legal--
#     pesa mas que el ideal. Por eso un min_s de 1 no da planos de un segundo:
#     el suelo real lo pone la propia narracion.
#   - Y por eso la media de un plano se pega al MINIMO y no al punto medio.
#     Medido en el proyecto del video largo con min 3 / max 6: media 3,04 s y
#     mediana 3,01 (y 3,38 de media en la copia). `media_s` sale de ahi.
#
# El escalon es geometrico y no lineal: el ritmo se percibe en proporcion, asi
# que bajar de 6 a 4 se nota lo mismo que bajar de 1,5 a 1.
# ===========================================================================

RITMOS = [
    {"id": "muy_lento", "nombre": "Muy lento",
     "min_s": 6.0, "max_s": 9.0, "min_s_rotulos": 7.5, "media_s": 6.3,
     "velocidad": "slow", "hueco_minimo": 1.4},
    {"id": "lento", "nombre": "Lento",
     "min_s": 4.0, "max_s": 7.5, "min_s_rotulos": 6.0, "media_s": 4.3,
     "velocidad": "normal", "hueco_minimo": 1.2},
    {"id": "medio", "nombre": "Medio",
     "min_s": 2.5, "max_s": 6.0, "min_s_rotulos": 5.0, "media_s": 2.8,
     "velocidad": "normal", "hueco_minimo": 1.0},
    {"id": "rapido", "nombre": "Rápido",
     "min_s": 1.5, "max_s": 5.0, "min_s_rotulos": 4.0, "media_s": 2.0,
     "velocidad": "fast", "hueco_minimo": 0.7},
    {"id": "muy_rapido", "nombre": "Muy rápido",
     "min_s": 1.0, "max_s": 4.0, "min_s_rotulos": 3.0, "media_s": 1.9,
     "velocidad": "fast", "hueco_minimo": 0.5},
]

RITMO_POR_DEFECTO = "medio"
RITMOS_POR_ID = {r["id"]: r for r in RITMOS}

#: CINCO RITMOS, TRES VELOCIDADES. La velocidad de la voz y la duracion de un
#: plano son DOS EJES, no uno: un montaje rapido con voz normal es una
#: combinacion que funciona, y la voz a `fastest` sobre planos de dos segundos
#: es un anuncio de teletienda. Por eso el ritmo mueve la voz UN escalon como
#: mucho, y los extremos de `p4_voz.VELOCIDADES` (slowest, fastest) el ritmo no
#: los usa nunca -- quedan para quien los pida por escrito.
#:
#: Y solo rellena si TU no has dicho nada de velocidad. Quien decide si lo
#: dijiste es el propio modelo que elige la voz (`voz_descrita`, campo
#: `velocidad_pedida`): lo que escribes manda, lo que no escribes lo rellena el
#: ritmo. Es la regla de todo este modo.
#:
#: El AIRE entre bloques si escala directo, y eso es a proposito: no es caracter
#: de la voz, es tiempo muerto de montaje. Un segundo de silencio entre bloques
#: sobre planos de dos segundos es un agujero; sobre planos de seis, respiracion.


def ritmo_de(id_ritmo):
    """La ficha de un ritmo, con el defecto si no se conoce."""
    return RITMOS_POR_ID.get(str(id_ritmo or "").strip().lower()) \
        or RITMOS_POR_ID[RITMO_POR_DEFECTO]


#: LO QUE CUESTA UNA IMAGEN, MEDIDO. No sale de la tabla de tarifas sino del
#: registro real (`coste_global.jsonl`): de las ultimas 120 imagenes de plano,
#: ya con la tarifa por tokens puesta, salen 0,033 $ de media en calidad `low`.
#: El grueso es la ENTRADA --unos 4.600 tokens por imagen entre la lamina de
#: estilo, el reparto y la continuidad-- y no la imagen devuelta, que en `low`
#: son seis milesimas. Por eso subir la calidad no multiplica el coste: le suma
#: la diferencia de salida (0,041 y 0,165 $ segun tarifas.json).
USD_POR_IMAGEN = {"low": 0.033, "medium": 0.074, "high": 0.198}


def coste_por_minuto(id_ritmo, calidad="low"):
    """Lo que cuesta un minuto de video a este ritmo. -> USD

    Es la unica cifra de dinero que este modo ensena, y por eso vale la pena
    decir de que esta hecha: un minuto son 60/media_s planos, y cada plano una
    imagen. No incluye lo que se paga UNA vez por estilo (las referencias
    dibujadas y las muestras): eso ya se dice al crearlo.
    """
    ficha = ritmo_de(id_ritmo)
    por_imagen = USD_POR_IMAGEN.get(str(calidad or "low"), USD_POR_IMAGEN["low"])
    return round((60.0 / max(0.5, float(ficha["media_s"]))) * por_imagen, 3)


def params_de_ritmo(id_ritmo):
    """Que se escribe en los params de cada paso. -> {paso: {clave: valor}}

    Se devuelve por PASO y no suelto por la misma razon que
    `presets_canal.cambios_para`: quien sabe que clave va a que paso es esta
    tabla, y repartir esa regla entre la pantalla y el servidor es como se acaba
    con dos versiones que se contradicen.
    """
    ficha = ritmo_de(id_ritmo)
    return {
        "assets": {"min_s": ficha["min_s"], "max_s": ficha["max_s"],
                   "min_s_rotulos": ficha["min_s_rotulos"]},
        # la velocidad NO va aqui: la pone `voz_descrita` y solo si no la
        # pediste tu. El aire si, que es de montaje y no de la voz.
        "voz": {"hueco_minimo": ficha["hueco_minimo"]},
    }


def ritmo_parecido(min_s=None, max_s=None):
    """El ritmo cuya horquilla de plano se parece mas a esa. -> ficha

    Hace falta para el modo EDITOR, que no guarda ningun ritmo: alli se escriben
    `assets.min_s` y `assets.max_s` a mano. Para decir cuantos planos va a tener
    un video hace falta la duracion MEDIA de un plano, y esa esta medida por
    ritmo (`media_s`) y no se deduce de la horquilla -- el segmentador pega la
    media al minimo, pero cuanto depende de la propia narracion.

    Asi que en vez de inventar una formula se busca el ritmo mas parecido y se
    usa SU media medida. Un solo sitio con las cifras, que es la regla de esta
    tabla desde que existe.
    """
    if min_s is None and max_s is None:
        return ritmo_de(RITMO_POR_DEFECTO)
    minimo = float(min_s if min_s is not None else max_s)
    maximo = float(max_s if max_s is not None else min_s)
    return min(RITMOS, key=lambda r: (abs(r["min_s"] - minimo)
                                      + abs(r["max_s"] - maximo)))


def contexto_de_ritmo(id_ritmo):
    """Como se le cuenta el ritmo al que elige la voz. -> una frase, o ''."""
    ficha = ritmo_de(id_ritmo)
    return (f"El montaje va a ir a planos de unos {ficha['media_s']:.1f} s de "
            f"media (ritmo «{ficha['nombre'].lower()}»).")


def ficha_de_ritmo(id_ritmo, calidad="low"):
    """El ritmo tal y como lo ensena la pantalla: solo dos cifras."""
    ficha = dict(ritmo_de(id_ritmo))
    ficha["usd_por_minuto"] = coste_por_minuto(ficha["id"], calidad)
    return ficha

class ErrorEncargo(ValueError):
    """Lo que ha llegado del navegador no vale, y se dice por que."""


# ===========================================================================
# EL ENCARGO: los cuatro campos
# ===========================================================================

IDIOMAS = ("es", "en", "pt", "fr", "it", "de")

#: Cuantos videos de referencia admite el tono. Tiene que ser el MISMO que
#: `tono.MAX_VIDEOS`, que es quien de verdad los lee y quien levanta si se pasa;
#: aqui esta escrito aparte para que la validacion del encargo no tenga que
#: importar `tono` --y con el, los motores-- solo para mirar un numero. Que los
#: dos coincidan lo comprueba la suite: una promesa que nadie comprueba se
#: rompe el dia que alguien mueva uno de los dos.
MAX_VIDEOS_TONO = 5


def validar_encargo(crudo):
    """Deja el encargo limpio, o levanta diciendo que falta. -> dict

    Las dos fuentes del estilo grafico --video y descripcion-- son EXCLUYENTES a
    proposito. Con las dos puestas habria que decidir cual manda, y esa decision
    no la puede tomar el programa: una URL y un parrafo pueden describir estilos
    distintos, y el que perdiera se habria escrito para nada.
    """
    datos = crudo if isinstance(crudo, dict) else {}
    limpio = {}

    nombre = " ".join(str(datos.get("nombre") or "").split())
    if not nombre:
        raise ErrorEncargo("ponle un nombre al canal: es lo que se lee en la "
                           "tarjeta y lo único que distingue un preset de otro")
    limpio["nombre"] = nombre[:80]

    idioma = str(datos.get("idioma") or "").strip().lower()
    if idioma not in IDIOMAS:
        raise ErrorEncargo(
            f"idioma desconocido: {idioma!r}. Los que hay son: "
            + ", ".join(IDIOMAS))
    limpio["idioma"] = idioma

    # El ritmo tiene defecto y no se exige: es un deslizador, y un deslizador
    # siempre esta en algun sitio. Uno desconocido cae en el de en medio en vez
    # de tumbar el encargo -- un preset guardado antes de que esto existiera no
    # trae ninguno, y tiene que poder rehacerse igual.
    limpio["ritmo"] = ritmo_de(datos.get("ritmo"))["id"]

    # EL ESTILO GRAFICO: UN VIDEO O UNAS IMAGENES, y el texto acompana a
    # cualquiera de los dos.
    #
    # El estilo se COPIA de algo que ya existe -- de los fotogramas de un video o
    # de unas imagenes sueltas -- porque una guia escrita a partir de un parrafo
    # se inventa todo lo que el parrafo no diga, que es casi todo. Lo escrito
    # sirve para lo que un material no puede decir por si solo: «igual pero mas
    # frio», «esto pero sin personajes». De ahi que sea OPCIONAL y que valga en
    # los dos caminos.
    #
    imagenes = [str(x).strip() for x in (datos.get("estilo_imagenes") or [])
                if str(x).strip()]
    prompt = " ".join(str(datos.get("estilo_prompt") or "").split())
    if not imagenes:
        raise ErrorEncargo(
            "falta el estilo gráfico: adjunta al menos una imagen que ya tenga "
            "el aspecto que quieres. Lo escrito acompaña, pero de un párrafo "
            "solo se inventa todo lo que el párrafo no diga")
    tope = max_imagenes_estilo()
    if len(imagenes) > tope:
        raise ErrorEncargo(
            f"has adjuntado {len(imagenes)} imágenes y el tope son {tope}")
    if prompt and len(prompt) < 8:
        raise ErrorEncargo(
            "las indicaciones del estilo gráfico son opcionales, pero con dos "
            "palabras no dicen nada: escríbelas enteras o déjalo en blanco")
    limpio["estilo_prompt"] = prompt
    limpio["estilo_imagenes"] = imagenes

    # EL TONO SIGUE SIENDO VIDEO O DESCRIPCION, y aqui si son excluyentes: no
    # hay imagenes que adjuntar a un tono, y un parrafo sobre como se cuenta una
    # historia SI basta para escribir las instrucciones -- no hay nada que
    # copiar, hay algo que decidir.
    # HASTA CINCO VIDEOS, no uno. Una sola referencia describe a UNA persona
    # teniendo un dia; con cuatro o cinco lo que queda descrito es lo que tienen
    # en comun, que es justamente el tono del canal y no el de un video. Y las
    # transcripciones se quedan guardadas para acompañar despues al redactor
    # (`tono.guardar_referencia`), asi que cada una que se añade se nota dos
    # veces: en la guia que se escribe y en lo que el guionista puede leer.
    #
    # Se sigue admitiendo `tono_url` en singular porque un encargo guardado
    # antes de esto lo trae asi, y el modo light se abre desde una tarjeta que
    # puede tener meses.
    prompt = " ".join(str(datos.get("tono_prompt") or "").split())
    if not prompt:
        raise ErrorEncargo("falta el tono del guion: describe con tus palabras "
                           "cómo quieres que suene («seco y sin adjetivos, que "
                           "los datos hablen solos»)")
    if len(prompt) < 8:
        raise ErrorEncargo(
            "describe el tono del guion con algo más de detalle: con dos "
            "palabras se lo inventa entero")
    limpio["tono_prompt"] = prompt

    voz = " ".join(str(datos.get("voz_prompt") or "").split())
    if not voz:
        raise ErrorEncargo("falta la voz: describe cómo quieres que suene "
                           "(«grave, pausada, sin dramatismo»)")
    limpio["voz_prompt"] = voz
    # LA VOZ ELEGIDA A MANO, opcional: el id de una voz del catalogo (lo
    # normal, la clonada del canal). Con ella la descripcion sigue valiendo
    # --pone la velocidad y el color-- pero la voz no se elige: es esa.
    voz_id = " ".join(str(datos.get("voz_id") or "").split())
    if voz_id and not re.match(r"^[A-Za-z0-9_-]{8,64}$", voz_id):
        raise ErrorEncargo("«voz_id» no parece un id de voz de Cartesia")
    limpio["voz_id"] = voz_id

    # AQUI NO HAY PERSONAJES DEL CANAL NI LLAMADAS A LA ACCION, y las dos
    # ausencias son decisiones:
    #
    #   * los personajes fijos del canal se retiraron enteros. Lo que queda es
    #     el REPARTO de cada video (`p6_assets`, `catalogo_visual`), que es
    #     donde vive la gente que sale en los planos y lo que sostiene que
    #     alguien se parezca a si mismo entre dos escenas.
    #   * las llamadas a la accion se deciden VIDEO POR VIDEO (`pasos/cta.py`),
    #     no en el estilo: es lo que mas cambia entre dos videos del mismo canal
    #     --uno manda a una web, el siguiente pide una suscripcion-- y en el
    #     estilo obligaba a acordarse de cambiarlas en cada encargo.
    return limpio


def max_imagenes_estilo():
    """Cuantas imagenes se pueden adjuntar a una descripcion. -> int

    LAS MISMAS QUE SE ELIGEN DE UN VIDEO, y sale de alli en vez de escribirse
    aqui: las dos listas alimentan a la MISMA funcion --la que escribe la guia
    mirando imagenes-- asi que un tope propio se quedaria viejo el dia que
    cambiara el otro. Se importa tarde porque p6_assets importa moodboard y
    moodboard importa p6_assets: arriba seria un circulo.
    """
    import p6_assets                                        # noqa: PLC0415
    return p6_assets.REFERENCIAS_A_ELEGIR


def tareas_de(encargo, solo=None):
    """Las tareas que aplican a este encargo, en orden de declaracion.

    `solo` recorta a un subconjunto (los tres botones de feedback), arrastrando
    lo que dependa de ello dentro del propio subconjunto.
    """
    tareas = list(TAREAS)
    if solo is not None:
        pedidas = set(solo)
        tareas = [t for t in tareas if t["id"] in pedidas]
    return tareas


def tandas_de(encargo, solo=None):
    """Las tareas agrupadas en TANDAS: lo de una tanda puede correr a la vez.

    Es lo que hace que el tono y la voz --que no dependen de nada-- corran
    mientras se estan bajando los fotogramas, que es la tarea larga. Sin esto la
    creacion de un preset seria la suma de los ocho tiempos en vez del camino
    critico: catorce minutos contra ocho.
    """
    tareas = tareas_de(encargo, solo)
    disponibles = {t["id"] for t in tareas}
    nivel, orden = {}, []
    pendientes = list(tareas)
    while pendientes:
        antes = len(pendientes)
        for tarea in list(pendientes):
            faltan = [d for d in tarea["necesita"]
                      if d in disponibles and d not in nivel]
            if faltan:
                continue
            previos = [nivel[d] for d in tarea["necesita"] if d in nivel]
            nivel[tarea["id"]] = (max(previos) + 1) if previos else 0
            orden.append(tarea)
            pendientes.remove(tarea)
        if len(pendientes) == antes:
            raise ErrorEncargo("ciclo en las dependencias del preset: "
                               + ", ".join(t["id"] for t in pendientes))
    tandas = []
    for tarea in orden:
        indice = nivel[tarea["id"]]
        while len(tandas) <= indice:
            tandas.append([])
        tandas[indice].append(tarea)
    return tandas


def segundos_de(tarea):
    """Lo que se espera que tarde ESTA tarea, con el historial delante.

    El historial manda cuando lo hay: las cifras escritas en la tabla son del
    primer dia y esta maquina ya lleva medidas. Solo se acepta si esta MEDIDO
    de verdad (`medida`), porque `estimar` siempre devuelve algo -- y su ultimo
    escalon es otra cifra escrita a mano, que no anade nada sobre la de aqui.
    """
    paso = tarea.get("paso")
    if not paso:
        return float(tarea["segundos"])
    try:
        prevision = estadisticas.estimar(paso, tamano=tarea.get("tamano") or 0)
    except Exception:                                       # noqa: BLE001
        return float(tarea["segundos"])
    if prevision.get("medida"):
        return max(3.0, float(prevision["segundos"]))
    return float(tarea["segundos"])


def plan_de(encargo, solo=None):
    """El plan completo, con los tiempos con los que se pinta la barra.

    Devuelve {tandas: [[tarea...]], segundos: total, camino_critico: [...]}.
    El total es la suma del MAXIMO de cada tanda, no la suma de todo: lo de una
    tanda corre a la vez, y una barra que suma tiempos paralelos promete el
    doble de lo que va a tardar.
    """
    tandas = tandas_de(encargo, solo)
    fichas, total = [], 0.0
    for tanda in tandas:
        conjunto = []
        for tarea in tanda:
            ficha = dict(tarea)
            ficha["segundos"] = round(segundos_de(tarea), 1)
            ficha["publico"] = publico_de(tarea["id"])
            conjunto.append(ficha)
        duracion = max([f["segundos"] for f in conjunto] or [0.0])
        for ficha in conjunto:
            ficha["desde"] = round(total, 1)
            ficha["tanda_segundos"] = duracion
        total += duracion
        fichas.append(conjunto)
    sueltas = [t for tanda in fichas for t in tanda]
    return {"tandas": fichas, "segundos": round(total, 1),
            "imagenes": sum(int(t.get("imagenes") or 0) for t in sueltas),
            "tareas": sueltas}


# ===========================================================================
# LAS MUESTRAS: la cara del preset
#
# Las laminas de referencia del estilo, con su cartela y su subtitulo puestos por
# el MISMO codigo que dibuja el video (`p7_callouts`, `cartelas`). Es lo unico
# que se ve de un preset recien hecho, asi que tiene que ser lo que va a salir:
# una miniatura pintada aparte con otra tipografia seria una promesa que el
# render no cumple.
#
# NO SE DIBUJA NADA NUEVO PARA ESTO. Antes eran cuatro escenas genericas de
# documental, generadas a proposito, y las laminas iban aparte y limpias en una
# segunda fila. Eran cuatro imagenes pagadas por estilo para ensenar lo mismo que
# ya ensenaban las laminas -- que ademas son las que el generador copia de
# verdad en cada plano, o sea la promesa mas honesta que se puede hacer.
# ===========================================================================

#: EL TEXTO DE LAS MUESTRAS, EN EL IDIOMA DEL ESTILO.
#:
#: Estaba solo en castellano y salia asi en un estilo en ingles: la muestra
#: existe para ENSENAR como va a quedar el video, y un subtitulo en otro idioma
#: ya no ensena eso -- ni la longitud de linea, ni donde parte, ni como se ve la
#: caja con esa cantidad de texto.
#:
#: Las cartelas NO se sacan de `cartelas.PLANTILLAS[x]["ejemplo"]`, que son
#: castellano fijo y son de la pantalla de plantillas del modo editor. Aqui hay
#: un juego propio y traducido, corto a proposito: tres plantillas por idioma
#: bastan para ver la tipografia, la paleta y el velo, que es lo que se juzga.
#: Un idioma que no este cae en castellano.
MUESTRAS_POR_IDIOMA = {
    "es": {
        "locucion": (
            "Una tarde de octubre, alguien abrió una puerta que llevaba años "
            "cerrada. Nadie lo notó hasta seis meses después. Para entonces, "
            "lo que había dentro ya estaba a la venta, y el precio era "
            "ridículo."),
        "frases": (
            "Así es como se ve un plano de este canal con su subtítulo debajo",
            "El texto entra cuando se dice y se va cuando termina la frase",
            "Cada palabra aparece sincronizada con la locución",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "Lo que se llevaron",
                       "lineas": ["Seis millones de cuentas",
                                  "Veintiocho millones de tarjetas",
                                  "La nómina entera"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10.000.000", "label": "cuentas a la venta",
                       "nota": "octubre de 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "Una contraseña era toda la cerradura",
                       "icono": "candado_abierto"}},
        ),
    },
    "en": {
        "locucion": (
            "One October afternoon, someone opened a door that had been shut "
            "for years. Nobody noticed for six months. By then, what was "
            "inside had already been put up for sale, and the price was absurd."),
        "frases": (
            "This is how a shot of this channel looks with its subtitle below",
            "The text comes in when it is said and leaves when the line ends",
            "Every word appears in sync with the narration",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "What they took",
                       "lineas": ["Six million accounts",
                                  "Twenty-eight million cards",
                                  "The entire payroll"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10,000,000", "label": "accounts up for sale",
                       "nota": "October 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "One password was the whole lock",
                       "icono": "candado_abierto"}},
        ),
    },
    "pt": {
        "locucion": (
            "Numa tarde de outubro, alguém abriu uma porta que estava fechada "
            "há anos. Ninguém reparou durante seis meses. A essa altura, o que "
            "estava lá dentro já estava à venda, e o preço era ridículo."),
        "frases": (
            "É assim que fica um plano deste canal com a legenda por baixo",
            "O texto entra quando é dito e sai quando a frase termina",
            "Cada palavra aparece sincronizada com a narração",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "O que levaram",
                       "lineas": ["Seis milhões de contas",
                                  "Vinte e oito milhões de cartões",
                                  "A folha de pagamento inteira"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10.000.000", "label": "contas à venda",
                       "nota": "outubro de 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "Uma senha era a fechadura inteira",
                       "icono": "candado_abierto"}},
        ),
    },
    "fr": {
        "locucion": (
            "Un après-midi d'octobre, quelqu'un a ouvert une porte fermée "
            "depuis des années. Personne ne l'a remarqué pendant six mois. À "
            "ce moment-là, ce qu'il y avait dedans était déjà en vente, à un "
            "prix dérisoire."),
        "frases": (
            "Voilà à quoi ressemble un plan de cette chaîne avec son sous-titre",
            "Le texte entre quand il est dit et sort à la fin de la phrase",
            "Chaque mot apparaît synchronisé avec la narration",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "Ce qu'ils ont emporté",
                       "lineas": ["Six millions de comptes",
                                  "Vingt-huit millions de cartes",
                                  "Toute la masse salariale"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10 000 000", "label": "comptes en vente",
                       "nota": "octobre 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "Un seul mot de passe était toute la serrure",
                       "icono": "candado_abierto"}},
        ),
    },
    "it": {
        "locucion": (
            "Un pomeriggio di ottobre, qualcuno ha aperto una porta chiusa da "
            "anni. Nessuno se ne è accorto per sei mesi. A quel punto, quello "
            "che c'era dentro era già in vendita, a un prezzo ridicolo."),
        "frases": (
            "Ecco come si vede un piano di questo canale con il suo sottotitolo",
            "Il testo entra quando viene detto ed esce quando la frase finisce",
            "Ogni parola appare sincronizzata con la narrazione",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "Quello che hanno preso",
                       "lineas": ["Sei milioni di conti",
                                  "Ventotto milioni di carte",
                                  "L'intero libro paga"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10.000.000", "label": "conti in vendita",
                       "nota": "ottobre 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "Una sola password era tutta la serratura",
                       "icono": "candado_abierto"}},
        ),
    },
    "de": {
        "locucion": (
            "An einem Nachmittag im Oktober öffnete jemand eine Tür, die seit "
            "Jahren verschlossen war. Sechs Monate lang bemerkte es niemand. "
            "Da war das, was drinnen lag, längst zum Verkauf angeboten, zu "
            "einem lächerlichen Preis."),
        "frases": (
            "So sieht eine Einstellung dieses Kanals mit Untertitel darunter aus",
            "Der Text kommt, wenn er gesprochen wird, und geht am Satzende",
            "Jedes Wort erscheint synchron zur Erzählung",
        ),
        "cartelas": (
            {"plantilla": "enumeracion",
             "datos": {"titulo": "Was sie mitnahmen",
                       "lineas": ["Sechs Millionen Konten",
                                  "Achtundzwanzig Millionen Karten",
                                  "Die gesamte Gehaltsliste"]}},
            {"plantilla": "cifra",
             "datos": {"cifra": "10.000.000", "label": "Konten zum Verkauf",
                       "nota": "Oktober 2007", "icono": "base_datos"}},
            {"plantilla": "tesis",
             "datos": {"texto": "Ein Passwort war das ganze Schloss",
                       "icono": "candado_abierto"}},
        ),
    },
}


def muestras_de_idioma(idioma):
    """El juego de textos de ese idioma, con el castellano de respaldo."""
    return MUESTRAS_POR_IDIOMA.get(str(idioma or "").strip().lower()) \
        or MUESTRAS_POR_IDIOMA["es"]


def bloques_de_escucha(idioma):
    """El parrafo que se sintetiza al pulsar «Escuchar». -> [{id, texto}]

    Va con la forma que `p4_voz.cargar_guion` ya lee de los params, que es lo
    que permite escuchar una voz en un TALLER: alli no hay guion --no es un
    video, es el sitio donde se monta un estilo-- y sin esto la escucha moria
    con «no encuentro el guion». Ninguna logica nueva: se le da por params el
    texto que en un video sale del paso 3.
    """
    return [{"id": "M001", "texto": muestras_de_idioma(idioma)["locucion"]}]


#: LA MUESTRA DE UN ESTILO ES SU PROPIA REFERENCIA, CON EL TEXTO ENCIMA.
#:
#: Antes eran cuatro planos dibujados a proposito --cuatro imagenes pagadas por
#: estilo-- y las seis referencias iban debajo en una segunda fila, limpias. Dos
#: filas de lo mismo, y ademas la de arriba ensenaba cartela en UNA de las
#: cuatro: las otras tres eran dibujo pelado.
#:
#: Ahora es UNA fila: las mismas seis laminas que copia cada plano del video,
#: cada una con su cartela y su subtitulo puestos por el codigo que monta el
#: video. Se ve el dibujo, la tipografia, el velo y la caja del subtitulo sobre
#: los seis fondos distintos que el canal va a usar de verdad, que es mas de lo
#: que ensenaban las cuatro.
#:
#: LAS LIMPIAS NO SE TOCAN. Siguen donde estaban (`moodboard/<eje>.png`,
#: `estilo.referencias`) y son las que viajan al generador de imagenes: lo que no
#: puede volver al prompt son los ROTULOS de la casa --cartela y subtitulo,
#: puestos aparte con tipografia de verdad--, que el generador copiaria como si
#: fueran parte del dibujo. El texto que la escena tiene de por si es otra cosa y
#: si se dibuja (regla `texto-en-imagen-permitido-pero-raro`). La compuesta se
#: escribe aparte, en `muestraN.png`, y no entra en ninguna lista de
#: referencias. Por eso ademas cambiar de idioma sigue siendo gratis: la limpia
#: esta siempre, no hay nada que volver a pagar.
#:
#: Y de paso: la tarea «muestra» deja de costar cuatro imagenes. Es rasterizar.

#: En cuantas columnas se apila la cara de la tarjeta. DOS, y las filas salen de
#: cuantas muestras haya: la hoja crece hacia abajo en vez de dejar fuera las que
#: no caben, que es lo que hacia el 2x2 con seis muestras.
COLUMNAS_MINIATURA = 2

#: Hasta cuantas muestras puede tener un estilo. NO es una decision de diseno
#: --son las que tenga el moodboard, hoy seis-- sino el tope al que buscarlas en
#: el disco: `muestra1.png`, `muestra2.png`... Estaba escrito a mano como 4 en
#: tres sitios distintos, que es como se queda una fila a medias cuando cambia.
MUESTRAS_MAX = 8


def nombres_de_muestra():
    """Como se pueden llamar las muestras sueltas, en orden. -> [nombres]"""
    return [f"muestra{n}.png" for n in range(1, MUESTRAS_MAX + 1)]


#: Cuantas de las muestras llevan cartela. DOS de seis: la fila tiene que
#: parecerse al video terminado, y en un video la narracion no para --subtitulo
#: en casi todos los planos-- pero una cartela sale cada varios. Con las seis
#: encarteladas no se ensena el canal, se ensena una promo del rotulador.
CARTELAS_EN_MUESTRAS = 2

#: Palabras por segundo con las que se fabrican las marcas de la frase de
#: ejemplo. No se mide nada: es una muestra, y lo unico que tiene que salir bien
#: es la CAJA y la tipografia, que no dependen del reloj.
CADENCIA_MUESTRA = 2.6


def _marcas_de(frase, desde=0.4):
    """Marcas [inicio, fin] por palabra, a cadencia fija."""
    marcas, t = [], float(desde)
    for _ in frase.split():
        marcas.append([round(t, 3), round(t + 1.0 / CADENCIA_MUESTRA, 3)])
        t += 1.0 / CADENCIA_MUESTRA
    return marcas


def _escena_muestra(indice, semilla, idioma="es", cuantas=6):
    """Una escena de mentira con lo justo para que p7 dibuje sus capas.

    SUBTITULO EN TODAS, CARTELA EN DOS. La narracion no para, asi que un plano
    con subtitulo es lo normal; una cartela cada varios planos es lo que hace un
    video de verdad. Con las seis encarteladas la fila ensenaba un canal que no
    existe -- y encima tapaba el dibujo, que es la mitad de lo que se juzga.

    LA SEMILLA CORRE EL JUEGO, NO LO SORTEA. Decide DONDE empieza la rueda: que
    dos de las seis llevan cartela y con que plantilla. Sorteandolo salian dos
    cartelas seguidas, o las dos con la misma plantilla.
    """
    textos = muestras_de_idioma(idioma)
    frases, fichas = textos["frases"], textos["cartelas"]
    salto = random.Random(f"{semilla}:muestras").randrange(max(1, len(fichas)))
    frase = frases[(indice + salto) % len(frases)]
    escena = {"id": f"M{indice + 1:03d}", "t_in": 0.0,
              "t_out": 0.4 + len(frase.split()) / CADENCIA_MUESTRA + 0.6,
              "narracion": frase, "marcas": _marcas_de(frase)}
    # Una cada `paso`, o sea repartidas y nunca dos seguidas.
    paso = max(1, cuantas // CARTELAS_EN_MUESTRAS)
    if (indice + salto) % paso:
        return escena
    # El texto sale de MUESTRAS_POR_IDIOMA y no de `cartelas.PLANTILLAS[x]
    # ["ejemplo"]`: esos son castellano fijo y son de la pantalla de plantillas
    # del modo editor. Va SOBRE IMAGEN, que ademas hoy es lo unico que hay
    # (`cartelas.TODAS_SOBRE_IMAGEN`): lo que hay que mirar es como queda el velo
    # encima del dibujo de ESTE canal.
    # dividido por `paso` y no en crudo: en crudo, los indices que llegan hasta
    # aqui son todos multiplos de `paso` y las dos cartelas salian iguales
    ficha = fichas[((indice + salto) // paso) % len(fichas)]
    escena["cartela"] = {
        "plantilla": ficha["plantilla"],
        "datos": copy.deepcopy(ficha["datos"]),
        "fondo": "imagen",
    }
    return escena


def componer(imagenes, destino, params, semilla=""):
    """Monta las muestras con sus capas puestas. -> {miniatura, celdas}.

    Salen las DOS cosas del mismo trabajo y por eso se hacen a la vez:

        celdas      las sueltas, que es como se miran al editar el estilo --
                    una tras otra, a lo ancho, y cada una legible
        miniatura   cuatro de ellas en 2x2, que es la cara de la tarjeta de la
                    galeria, donde hace falta una sola imagen 16:9

    Componer dos veces seria pagar dos veces el navegador para dibujar lo
    mismo.

    `imagenes` son las laminas LIMPIAS del estilo --las mismas que copia cada
    plano del video-- en el orden en que se van a ensenar. Cada una se compone
    con `p7_callouts.previsualizar`, que es EXACTAMENTE lo que compone el repaso
    del montaje y lo que replica el render: la imagen dentro del grupo del zoom,
    la capa movil con ella y la quieta fuera. Componer aqui a mano con PIL habria
    dado una miniatura que no se parece al video.
    """
    from PIL import Image                                   # noqa: PLC0415
    trabajo = os.path.join(os.path.dirname(destino), "_muestras")
    os.makedirs(trabajo, exist_ok=True)
    p = p7_callouts._con_defectos(params or {})
    idioma = str((params or {}).get("idioma") or "es")
    celdas = []
    for indice, ruta in enumerate(imagenes):
        if not ruta or not os.path.exists(ruta):
            continue
        escena = _escena_muestra(indice, semilla, idioma, len(imagenes))
        movil, fija, _ = p7_callouts.capa_de_escena(escena, p)
        # LA CARTELA SE PIDE APARTE, y solo en las que la llevan. `capa_de_escena`
        # devuelve la capa movil del plano, que en una escena de mentira sin plan
        # no lleva cartela: hay que dibujarla con `cartelas.svg_capa`, que es lo
        # que hace el render.
        if escena.get("cartela"):
            movil = cartelas.svg_capa(
                escena["cartela"],
                p7_callouts.paleta_de_guia((p.get("estilo") or {}).get("guia"),
                                           p.get("paleta")),
                p7_callouts.diseno_de(p, (p.get("estilo") or {}).get("guia"))[1],
                duracion=float(escena["t_out"]) - float(escena["t_in"]))
        base = os.path.join(trabajo, f"celda{indice + 1}")
        ruta_movil = medios.escribir_texto(base + ".movil.svg", movil)
        ruta_fija = medios.escribir_texto(base + ".fija.svg", fija)
        celdas.append(p7_callouts.previsualizar(
            ruta, ruta_movil, base + ".png", ruta_fija, None))

    if not celdas:
        raise RuntimeError("no ha salido ninguna muestra que componer")
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    # las SUELTAS, con su nombre definitivo, para poder servirlas una a una y
    # ponerlas en fila al editar el estilo.
    #
    # `muestraN.png` es la lamina CON su cartela y su subtitulo encima. NO es una
    # referencia de estilo y no puede serlo nunca: si entrara en el prompt de un
    # plano, el generador copiaria esos rotulos --que son grafismo de la casa, no
    # de la escena-- como si fueran parte del dibujo. Las referencias son la lamina LIMPIA, que sigue intacta
    # donde estaba y sale de una lista explicita (`estilo.referencias` ->
    # `p6._referencias_estilo`), nunca de barrer esta carpeta.
    sueltas = []
    for indice, ruta in enumerate(celdas, start=1):
        final = os.path.join(os.path.dirname(destino), f"muestra{indice}.png")
        try:
            Image.open(ruta).convert("RGB").save(final, "PNG")
            sueltas.append(final)
        except Exception:                                   # noqa: BLE001
            continue

    # LA CARA DE LA TARJETA: LAS MISMAS, TODAS, EN DOS COLUMNAS.
    #
    # Era un 2x2 con cuatro de ellas, y ensenar cuatro de seis hacia pensar que
    # esas cuatro eran algo aparte. Con dos columnas caben las que haya --tres
    # filas para las seis de hoy-- y cada celda sigue siendo 16:9 entero, o sea
    # que ninguna se recorta. La hoja deja de ser 16:9 y pasa a ser 32:27, que es
    # lo que la tarjeta reserva (`.galeria-estilos .cara`).
    celda_w = p7_callouts.SALIDA[0] // COLUMNAS_MINIATURA
    celda_h = round(celda_w * p7_callouts.SALIDA[1] / p7_callouts.SALIDA[0])
    filas = max(1, -(-len(celdas) // COLUMNAS_MINIATURA))    # techo de la division
    hoja = Image.new("RGB", (celda_w * COLUMNAS_MINIATURA, celda_h * filas),
                     (11, 12, 9))
    for indice, ruta in enumerate(celdas):
        try:
            foto = Image.open(ruta).convert("RGB")
        except Exception:                                   # noqa: BLE001
            continue
        foto = foto.resize((celda_w, celda_h), Image.LANCZOS)
        hoja.paste(foto, ((indice % COLUMNAS_MINIATURA) * celda_w,
                          (indice // COLUMNAS_MINIATURA) * celda_h))
    hoja.save(destino, "PNG")
    return {"miniatura": destino, "celdas": sueltas}


def partir_miniatura(hoja_2col, destino):
    """Parte una hoja de muestras en sus muestras sueltas. -> [rutas]

    PARA LOS ESTILOS DE ANTES de que se guardaran sueltas. Son las mismas que ya
    estan pagadas; lo unico que falta es tenerlas en ficheros separados para
    poder ponerlas en fila.

    LAS FILAS SE CUENTAN, NO SE SUPONEN. La hoja fue 2x2 y hoy son dos columnas
    con las filas que hagan falta, asi que partir siempre en cuatro habria
    cortado por la mitad las de seis. Se deducen del alto: dos columnas de celdas
    16:9 dan una altura por fila conocida.

    Se hizo primero con CSS --el mismo fichero varias veces con el fondo
    desplazado a su cuadrante-- y era un truco: cuando la regla no llegaba a
    aplicarse se veia un recorte gigante de la esquina, y aunque llegara, lo que
    hay en pantalla sigue siendo UNA imagen partida y se nota. Ficheros de verdad
    no tienen ese problema y no cuestan nada: es un recorte, no una generacion.
    """
    from PIL import Image                                   # noqa: PLC0415
    os.makedirs(destino, exist_ok=True)
    salida = []
    with Image.open(hoja_2col) as hoja:
        hoja = hoja.convert("RGB")
        ancho, alto = hoja.size
        celda_w = ancho // COLUMNAS_MINIATURA
        celda_h = round(celda_w * p7_callouts.SALIDA[1] / p7_callouts.SALIDA[0])
        filas = max(1, round(alto / max(1, celda_h)))
        celda_h = alto // filas
        for fila in range(filas):
            for columna in range(COLUMNAS_MINIATURA):
                x, y = columna * celda_w, fila * celda_h
                trozo = hoja.crop((x, y, x + celda_w, y + celda_h))
                ruta = os.path.join(destino, f"muestra{len(salida) + 1}.png")
                trozo.save(ruta, "PNG")
                salida.append(ruta)
    return salida
