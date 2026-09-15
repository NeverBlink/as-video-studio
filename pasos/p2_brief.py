"""
Paso 2: brief del usuario.

El brief es lo que el usuario escribe en lenguaje natural sobre lo que quiere:
"el mismo video pero con menos tecnicismos", "mas centrado en las cifras",
"empieza por el final". Este paso NO llama a ningun modelo. Solo:

  - normaliza y valida lo que se ha escrito,
  - traduce la duracion objetivo a un presupuesto de palabras CON HORQUILLA,
  - contrasta ese objetivo con el material que dejo la ingesta y avisa de lo
    que no cuadra (pedir 10 minutos de guion sobre un video de 3, por ejemplo).

Duracion y horquilla
--------------------
La duracion objetivo no es una cifra exacta: se admite un margen de +-30%. Un
guion de locucion no se puede clavar al segundo, y perseguir la cifra exacta
produce guiones estirados o mutilados; lo que importa es caer dentro de la
horquilla.

El unico suelo es TECNICO (DURACION_MINIMA_S): lo justo para que haya algo que
segmentar. Aqui hubo un minimo de 10 minutos, que era linea editorial disfrazada
de regla del sistema; se quito. Un video de 40 segundos es legitimo.

UN VIDEO, UN IDIOMA
-------------------
El brief aceptaba una LISTA de idiomas de salida y el guion se producia en todos
ellos con los mismos ids. Se retiro el 24-08-2026 por decision del canal: un
video se hace en un idioma y el mismo video en otro es otro proyecto. La clave
vieja (`idiomas_salida`) se sigue LEYENDO --se coge el primero-- para que un
proyecto guardado antes siga abriendo; no se vuelve a escribir.

Cuantas palabras caben en un minuto
-----------------------------------
La conversion vive en `cadencia`, no aqui, y desde el 24-08-2026 mira tres cosas
en vez de una: el idioma, la VELOCIDAD de la voz y el AIRE que se inserta entre
bloques. Antes eran dos cifras escritas (2,6 en ingles, 2,3 en espanol) que
ignoraban las otras dos, asi que el mismo guion pedido a 'slow' salia un 20 % mas
largo de lo pedido y nadie lo decia.

Por eso `velocidad` y `hueco_minimo` son params DE ESTE PASO. Podrian leerse del
paso voz, pero entonces la firma del brief no los veria: cambiar la voz daria un
presupuesto distinto sin invalidar nada, que es exactamente la clase de dato
deducido que este repo ya pago una vez. Se declaran, y si se separan de los del
paso voz el brief lo dice en sus avisos (`_avisos_de_voz`).
"""
import os
import re
import sys
import time

try:
    from . import cadencia, comun, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cadencia
    import comun
    import estadisticas

PASO = "brief"

PARAMS_POR_DEFECTO = {
    "instrucciones": "",
    "idioma_salida": "es",
    "duracion_objetivo_s": 600,
    "tolerancia": 0.30,
    "palabras_por_bloque": 30,
    # LA VOZ, AQUI, porque de ella depende cuantas palabras caben en la duracion
    # pedida y este paso no hace otra cosa que esa conversion. Estan declaradas
    # como params propios --y no leidas del paso voz por detras-- porque un dato
    # que cambia la salida y que la firma no ve es como se acaba con un brief que
    # dice una cosa y una toma que dura otra sin que nada lo avise. Quien escribe
    # `voz.velocidad` escribe tambien esta; si se separan, `_avisos` lo dice.
    "velocidad": "normal",
    "hueco_minimo": 1.0,
    # Y LA VOZ, por lo mismo. La cadencia no es solo del idioma: MEDIDO, dos
    # voces inglesas con el mismo modelo dan 2,553 y 1,91 palabras/s a velocidad
    # normal -- un 25 % de diferencia --. Sin esto, cambiar de voz dejaba el
    # presupuesto de palabras igual y la toma duraba otra cosa.
    #
    # Vacio = no se sabe cual es y manda la tabla del idioma. Lo escribe quien
    # escribe `voz.voz_id`: `presets_canal.cambios_para` lo copia al aplicar un
    # estilo, igual que `velocidad` y `hueco_minimo`.
    "voz_id": "",
    # EL FORMATO DEL VIDEO: horizontal (16:9) o vertical (9:16). Se decide al
    # crear el video, junto a la duracion, y de aqui lo leen p6 (el tamano de
    # cada imagen y del plan), p7 (las capas) y p8 (el MP4). Va en el brief
    # porque es una decision del VIDEO, no del estilo: el mismo canal hace
    # videos largos en horizontal y cortos en vertical.
    "formato": comun.FORMATO_POR_DEFECTO,
}

# La tabla de cadencia vive en `cadencia`, que es donde tambien esta la cuenta
# inversa (la del modo simulado de la voz). Estuvo aqui, con dos cifras que
# ignoraban la velocidad de la voz y el aire entre bloques: ver esa cabecera.
PALABRAS_POR_SEGUNDO = cadencia.CADENCIA
PALABRAS_POR_SEGUNDO_OTROS = cadencia.CADENCIA_OTROS

# Suelo tecnico, no editorial. Estaba en 600 s porque "un video del estudio dura
# al menos 10 minutos", y eso es una decision de linea editorial que el sistema
# no tiene por que imponer: se quitan los 10 minutos y se deja lo unico que de
# verdad hace falta para que el pipeline produzca algo (un puñado de palabras que
# segmentar en al menos un plano). Un corto de 40 s es un video perfectamente
# legitimo, y ahora se puede pedir.
DURACION_MINIMA_S = 10
DURACION_MAXIMA_S = 7200
TOLERANCIA_MAXIMA = 0.30    # +-30%

NOMBRES_IDIOMA = {
    "es": "espanol", "en": "ingles", "pt": "portugues", "fr": "frances",
    "it": "italiano", "de": "aleman", "ca": "catalan", "gl": "gallego",
    "eu": "euskera",
}

#: Y los mismos, EN INGLES. Van pegados a la tabla de arriba a proposito: dos
#: tablas de idiomas en dos ficheros distintos se desincronizan el dia que se
#: anada uno, y este repo ya tiene seis tablas de nombres de idioma.
#:
#: Existe porque al generador de IMAGEN se le habla en ingles: el prompt entero
#: --la guia de estilo, las reglas de la casa, la descripcion del plano-- va en
#: ingles, y de ahi salio una lamina de un canal espanol con un diagrama
#: rotulado «PLAN / DO / REVIEW». Decirle «espanol» dentro de un encargo en
#: ingles es pedirle que adivine; decirle «Spanish» no.
NOMBRES_IDIOMA_EN = {
    "es": "Spanish", "en": "English", "pt": "Portuguese", "fr": "French",
    "it": "Italian", "de": "German", "ca": "Catalan", "gl": "Galician",
    "eu": "Basque",
}

_ALIAS_IDIOMA = {
    "espanol": "es", "español": "es", "castellano": "es", "spanish": "es",
    "ingles": "en", "inglés": "en", "english": "en",
    "portugues": "pt", "português": "pt", "portuguese": "pt",
    "frances": "fr", "francés": "fr", "french": "fr",
    "italiano": "it", "italian": "it",
    "aleman": "de", "alemán": "de", "german": "de", "deutsch": "de",
}


def describir(params):
    """Resumen de una linea de la configuracion del paso, para la bitacora."""
    opciones = _normalizar(params, estricto=False)
    texto = " ".join(opciones["instrucciones"].split())
    if len(texto) > 60:
        texto = texto[:57] + "..."
    idioma = nombre_idioma(opciones["idioma_salida"])
    presupuesto = presupuesto_de(opciones["duracion_objetivo_s"],
                                 opciones["idioma_salida"],
                                 opciones["velocidad"],
                                 opciones["hueco_minimo"],
                                 opciones["palabras_por_bloque"])
    return (f"brief en {idioma} para {opciones['duracion_objetivo_s']}s "
            f"(~{presupuesto} palabras +-{int(opciones['tolerancia'] * 100)}%): "
            f"{texto or 'sin instrucciones'}")


def normalizar_idioma(valor):
    """'Espanol', 'es-ES', 'spanish' -> 'es'."""
    crudo = str(valor or "").strip().lower()
    if not crudo:
        return ""
    if crudo in _ALIAS_IDIOMA:
        return _ALIAS_IDIOMA[crudo]
    codigo = re.split(r"[-_]", crudo)[0]
    return _ALIAS_IDIOMA.get(codigo, codigo)


def nombre_idioma(codigo):
    """Codigo de idioma -> nombre en castellano, para hablarle al guionista."""
    return NOMBRES_IDIOMA.get(codigo, codigo)


def nombre_idioma_en(codigo):
    """Codigo -> nombre EN INGLES, para hablarle al generador de imagen.

    Devuelve "" si no lo conoce, y eso es deliberado: mas vale no decir nada que
    colarle un codigo de dos letras a un generador de imagenes, que lo dibujaria
    tan tranquilo. Quien lo llama ya sabe callarse cuando esto viene vacio.
    """
    return NOMBRES_IDIOMA_EN.get(str(codigo or "").strip().lower(), "")


def palabras_por_segundo(idioma, velocidad=None, voz=None):
    """Cadencia de locucion del idioma de salida con esa velocidad de voz."""
    valor, _origen = cadencia.cadencia_de(normalizar_idioma(idioma), velocidad,
                                          voz)
    return round(valor, 3)


def presupuesto_de(duracion_s, idioma, velocidad=None, hueco_minimo=0.0,
                   palabras_por_bloque=30, voz=None):
    """Palabras que caben en esa duracion dichas por esta voz."""
    return cadencia.palabras_para(duracion_s, normalizar_idioma(idioma),
                                  velocidad, hueco_minimo,
                                  palabras_por_bloque, voz)["palabras"]


def horquilla_de(duracion_s, idioma, tolerancia=TOLERANCIA_MAXIMA,
                 velocidad=None, hueco_minimo=0.0, palabras_por_bloque=30,
                 voz=None):
    """Presupuesto de palabras con su minimo y su maximo.

    Y con los SEGUNDOS de vuelta en los dos extremos, que es lo que permite
    decirle a quien pide la duracion cuanto se puede desviar de verdad: la
    horquilla es de palabras, pero lo que se pidio son segundos.
    """
    ficha = cadencia.palabras_para(duracion_s, normalizar_idioma(idioma),
                                   velocidad, hueco_minimo, palabras_por_bloque,
                                   voz)
    presupuesto = ficha["palabras"]
    holgura = max(0.0, min(float(tolerancia), TOLERANCIA_MAXIMA))
    minimo = int(round(presupuesto * (1.0 - holgura)))
    maximo = int(round(presupuesto * (1.0 + holgura)))
    return {
        "idioma": idioma,
        "palabras_por_segundo": ficha["cadencia_palabras_s"],
        "cadencia_origen": ficha["cadencia_origen"],
        "velocidad": ficha["velocidad"],
        "hueco_minimo": ficha["hueco_minimo"],
        "aire_s": ficha["aire_s"],
        "presupuesto_palabras": presupuesto,
        "palabras_minimo": minimo,
        "palabras_maximo": maximo,
        "segundos_minimo": cadencia.segundos_para(
            minimo, normalizar_idioma(idioma), velocidad, hueco_minimo,
            palabras_por_bloque, voz),
        "segundos_maximo": cadencia.segundos_para(
            maximo, normalizar_idioma(idioma), velocidad, hueco_minimo,
            palabras_por_bloque, voz),
        "tolerancia": holgura,
    }


# --------------------------------------------------------------------- params

def _idioma_de(params, opciones):
    """El idioma de salida, normalizado.

    Manda `idioma_salida` SI VIENE ESCRITO; si no, se mira la lista vieja y se
    coge el primero, que era el principal. Los demas se pierden, que es
    exactamente lo que significa haber retirado el eje.

    Se mira en `params` y no en `opciones` porque ahi `idioma_salida` ya trae su
    valor de fabrica ('es'): preguntandole a `opciones` nunca esta vacio, y un
    proyecto guardado en ingles con la clave vieja se abriria en castellano sin
    que nadie lo dijera.
    """
    codigo = normalizar_idioma((params or {}).get("idioma_salida"))
    if codigo:
        return codigo
    vieja = (params or {}).get("idiomas_salida")
    if isinstance(vieja, str):
        vieja = [vieja]
    for valor in (vieja or []):
        codigo = normalizar_idioma(valor)
        if codigo:
            return codigo
    return normalizar_idioma(opciones.get("idioma_salida")) or "es"


def _normalizar(params, estricto=True):
    """Params completos y con los tipos correctos; valida si estricto."""
    opciones = dict(PARAMS_POR_DEFECTO)
    for clave, valor in (params or {}).items():
        if clave in PARAMS_POR_DEFECTO:
            opciones[clave] = valor

    opciones["instrucciones"] = str(opciones.get("instrucciones") or "").strip()
    opciones["idioma_salida"] = _idioma_de(params, opciones)
    opciones["formato"] = comun.normalizar_formato(opciones.get("formato"))

    try:
        opciones["duracion_objetivo_s"] = int(round(float(opciones["duracion_objetivo_s"])))
    except (TypeError, ValueError):
        if estricto:
            raise ValueError("duracion_objetivo_s tiene que ser un numero de segundos")
        opciones["duracion_objetivo_s"] = PARAMS_POR_DEFECTO["duracion_objetivo_s"]

    # el minimo se sube aqui y no en ejecutar() para que lo que describe el paso
    # sea lo mismo que despues hace: pedir 3 minutos y ver un brief de 10 sin que
    # nada lo diga es peor que el aviso
    opciones["duracion_pedida_s"] = opciones["duracion_objetivo_s"]
    opciones["duracion_objetivo_s"] = max(opciones["duracion_objetivo_s"],
                                          DURACION_MINIMA_S)

    try:
        opciones["tolerancia"] = float(opciones["tolerancia"])
    except (TypeError, ValueError):
        opciones["tolerancia"] = PARAMS_POR_DEFECTO["tolerancia"]
    opciones["tolerancia"] = max(0.0, min(opciones["tolerancia"], TOLERANCIA_MAXIMA))

    try:
        opciones["palabras_por_bloque"] = int(opciones["palabras_por_bloque"])
    except (TypeError, ValueError):
        opciones["palabras_por_bloque"] = PARAMS_POR_DEFECTO["palabras_por_bloque"]

    # La velocidad se acepta como nombre o como numero, igual que en p4_voz: una
    # forma distinta en cada sitio para el mismo mando es como se guarda 'slow'
    # donde se lee -0.2 y la cuenta sale del reves.
    velocidad = opciones.get("velocidad")
    if isinstance(velocidad, bool) or velocidad in (None, ""):
        opciones["velocidad"] = PARAMS_POR_DEFECTO["velocidad"]
    elif isinstance(velocidad, (int, float)):
        opciones["velocidad"] = max(-1.0, min(1.0, float(velocidad)))
    else:
        texto = str(velocidad).strip().lower()
        opciones["velocidad"] = texto if texto in cadencia.FACTOR_VELOCIDAD             else PARAMS_POR_DEFECTO["velocidad"]

    opciones["voz_id"] = str(opciones.get("voz_id") or "").strip()
    try:
        opciones["hueco_minimo"] = max(0.0, float(opciones["hueco_minimo"]))
    except (TypeError, ValueError):
        opciones["hueco_minimo"] = PARAMS_POR_DEFECTO["hueco_minimo"]

    if not estricto:
        return opciones

    if not opciones["instrucciones"]:
        raise ValueError("el brief esta vacio: escribe que quieres de este video")
    if opciones["duracion_objetivo_s"] > DURACION_MAXIMA_S:
        raise ValueError(
            f"duracion_objetivo_s fuera de rango: {opciones['duracion_objetivo_s']}s "
            f"(el maximo son {DURACION_MAXIMA_S}s)")
    if opciones["palabras_por_bloque"] < 5:
        raise ValueError("palabras_por_bloque tiene que ser al menos 5")
    return opciones


# --------------------------------------------------------------------- avisos

def _avisos(opciones, horquilla, referencia, subida):
    """Contrasta lo pedido con el material real de la ingesta."""
    avisos = []
    if subida:
        avisos.append(
            f"la duracion pedida ({subida}s) esta por debajo del suelo tecnico "
            f"({DURACION_MINIMA_S}s: por debajo no hay ni un plano que montar) "
            f"y se ha subido a {opciones['duracion_objetivo_s']}s")
    if len(opciones["instrucciones"]) < 15:
        avisos.append("el brief es muy escueto: el guion saldra generico")

    if not referencia:
        avisos.append("no hay ingesta.json de referencia: no se ha podido "
                      "contrastar el objetivo con el video de partida")
        return avisos

    metadatos = referencia.get("metadatos") or {}
    duracion_origen = float(metadatos.get("duracion_s") or 0)
    palabras_origen = int(metadatos.get("palabras_transcript") or 0)
    idioma_origen = normalizar_idioma(metadatos.get("idioma_transcript"))
    presupuesto = horquilla["presupuesto_palabras"]

    if duracion_origen and opciones["duracion_objetivo_s"] > duracion_origen * 1.2:
        avisos.append(
            f"pides {opciones['duracion_objetivo_s']}s sobre un video de "
            f"{int(duracion_origen)}s: habra que estirar o buscar mas material")
    if palabras_origen and horquilla["palabras_minimo"] > palabras_origen:
        avisos.append(
            f"el minimo de la horquilla ({horquilla['palabras_minimo']} palabras) "
            f"supera al transcript de partida ({palabras_origen}): no hay hechos "
            f"suficientes para tanto")
    elif palabras_origen and presupuesto > palabras_origen:
        avisos.append(
            f"el objetivo ({presupuesto} palabras) supera al transcript de "
            f"partida ({palabras_origen}), pero la horquilla llega hasta "
            f"{horquilla['palabras_minimo']} y eso si cabe")
    if idioma_origen and idioma_origen != opciones["idioma_salida"]:
        avisos.append(
            f"el material esta en {nombre_idioma(idioma_origen)} y el guion se "
            f"pide en {nombre_idioma(opciones['idioma_salida'])}")
    if not _frames_utiles(referencia):
        avisos.append("la ingesta no dejo ningun frame util: no hay referencia visual")
    return avisos


def _avisos_de_voz(proyecto, opciones):
    """Dice en voz alta si la voz de verdad no es la que se uso para la cuenta.

    La velocidad y el aire estan declarados como params de ESTE paso para que la
    firma los vea (ver PARAMS_POR_DEFECTO). El precio de esa decision es que
    pueden separarse de los del paso voz, y una separacion muda seria lo peor de
    los dos mundos: el guion escrito para 10 minutos y una toma de 12 sin que
    nada lo dijera. Asi que se comprueba y se cuenta.
    """
    estado = _estado_de(proyecto)
    if estado is None:
        return []
    try:
        voz = estado.params("voz") or {}
    except Exception:                                       # noqa: BLE001
        return []
    avisos = []
    suya = voz.get("velocidad")
    if suya not in (None, "") and str(suya) != str(opciones["velocidad"]):
        avisos.append(
            f"la voz esta puesta a velocidad '{suya}' y la cuenta de palabras se "
            f"ha hecho con '{opciones['velocidad']}': el guion saldra "
            f"{'largo' if cadencia.factor_velocidad(suya) > cadencia.factor_velocidad(opciones['velocidad']) else 'corto'} "
            f"de duracion. Iguala las dos o vuelve a aplicar el estilo")
    aire = voz.get("hueco_minimo")
    if aire is not None and abs(float(aire) - float(opciones["hueco_minimo"])) > 0.01:
        avisos.append(
            f"el aire entre bloques de la voz es {aire}s y la cuenta se ha hecho "
            f"con {opciones['hueco_minimo']}s")
    quien = str(voz.get("voz_id") or "").strip()
    if quien and quien != str(opciones["voz_id"] or "").strip():
        avisos.append(
            f"la cuenta de palabras se ha hecho para la voz "
            f"'{opciones['voz_id'] or 'sin elegir'}' y la que va a locutar es "
            f"'{quien}': si esa voz tiene tomas medidas, el guion saldra de otra "
            f"duracion. Vuelve a aplicar el estilo")
    return avisos


def _estado_de(proyecto):
    """Estado del proyecto, o None si el nucleo no esta disponible.

    Igual que en `p4_voz`: este paso corre tambien desde las pruebas con un
    proyecto de mentira, y no poder leer el estado no puede tumbarlo.
    """
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if raiz not in sys.path:
        sys.path.insert(0, raiz)
    try:
        from nucleo.estado import Estado                     # noqa: PLC0415
    except ImportError:
        return None
    try:
        return Estado(proyecto)
    except Exception:                                       # noqa: BLE001
        return None


def _frames_utiles(referencia):
    """Cuantos frames utiles dejo la ingesta, venga como venga en su JSON."""
    if not referencia:
        return 0
    for clave in ("frames_utiles_n", "frames_utiles"):
        valor = referencia.get(clave)
        if isinstance(valor, int):
            return valor
        if isinstance(valor, list):
            return len(valor)
    return int((referencia.get("metadatos") or {}).get("frames_utiles") or 0)


# --------------------------------------------------------------------- salida

def ejecutar(proyecto, params, avisar):
    """Normaliza y valida el brief, y calcula la horquilla de palabras."""
    arranque = time.time()
    avisar(0.05, "leyendo el brief")
    opciones = _normalizar(params)
    trabajo = comun.preparar_trabajo(proyecto, PASO)

    pedida = opciones["duracion_pedida_s"]
    subida = pedida if pedida < DURACION_MINIMA_S else 0

    avisar(0.35, "calculando la horquilla de palabras")
    principal = opciones["idioma_salida"]
    horquilla = horquilla_de(opciones["duracion_objetivo_s"], principal,
                             opciones["tolerancia"], opciones["velocidad"],
                             opciones["hueco_minimo"],
                             opciones["palabras_por_bloque"],
                             opciones["voz_id"])

    avisar(0.60, "contrastando con el material de la ingesta")
    referencia = comun.leer_salida(proyecto, "ingesta", "ingesta.json", obligatorio=False)
    avisos = _avisos(opciones, horquilla, referencia, subida)
    avisos.extend(_avisos_de_voz(proyecto, opciones))

    metadatos = (referencia or {}).get("metadatos") or {}
    brief = {
        "instrucciones": opciones["instrucciones"],
        "idioma_salida": principal,
        "idioma_salida_nombre": nombre_idioma(principal),
        "formato": opciones["formato"],
        "duracion_objetivo_s": opciones["duracion_objetivo_s"],
        "duracion_pedida_s": pedida,
        "duracion_minima_s": DURACION_MINIMA_S,
        "palabras_por_segundo": horquilla["palabras_por_segundo"],
        "cadencia_origen": horquilla["cadencia_origen"],
        "velocidad": opciones["velocidad"],
        "hueco_minimo": opciones["hueco_minimo"],
        "voz_id": opciones["voz_id"],
        "aire_s": horquilla["aire_s"],
        "segundos_minimo": horquilla["segundos_minimo"],
        "segundos_maximo": horquilla["segundos_maximo"],
        "presupuesto_palabras": horquilla["presupuesto_palabras"],
        "palabras_minimo": horquilla["palabras_minimo"],
        "palabras_maximo": horquilla["palabras_maximo"],
        "margen": {"minimo": horquilla["palabras_minimo"],
                   "maximo": horquilla["palabras_maximo"],
                   "tolerancia": opciones["tolerancia"]},
        "bloques_estimados": max(1, int(round(horquilla["presupuesto_palabras"]
                                              / opciones["palabras_por_bloque"]))),
        "palabras_por_bloque": opciones["palabras_por_bloque"],
        "referencia": {
            "titulo": metadatos.get("titulo", ""),
            "url": metadatos.get("url", ""),
            "duracion_s": metadatos.get("duracion_s", 0),
            "palabras_transcript": metadatos.get("palabras_transcript", 0),
            "idioma_transcript": metadatos.get("idioma_transcript", ""),
            "frames_utiles": _frames_utiles(referencia),
        },
        "avisos": avisos,
    }

    avisar(0.85, "escribiendo brief.json")
    comun.escribir_json(os.path.join(trabajo, "brief.json"), brief)
    comun.escribir_texto(os.path.join(trabajo, "brief.txt"), _legible(brief))

    salidas = {
        "brief": brief,
        "brief_fichero": "brief.json",
        "idioma_salida": principal,
        "duracion_objetivo_s": opciones["duracion_objetivo_s"],
        "presupuesto_palabras": horquilla["presupuesto_palabras"],
        "palabras_minimo": horquilla["palabras_minimo"],
        "palabras_maximo": horquilla["palabras_maximo"],
        "bloques_previstos": brief["bloques_estimados"],
        "avisos": avisos,
        "resumen": (f"{opciones['duracion_objetivo_s']}s en "
                    f"{brief['idioma_salida_nombre']} -> entre "
                    f"{horquilla['palabras_minimo']} y {horquilla['palabras_maximo']} "
                    f"palabras (objetivo {horquilla['presupuesto_palabras']})"
                    + (f"; {len(avisos)} aviso(s)" if avisos else "")),
    }
    estadisticas.anotar(PASO, time.time() - arranque,
                        tamano=int(metadatos.get("palabras_transcript") or 0))
    avisar(1.0, salidas["resumen"])
    return salidas


def _legible(brief):
    """El brief en texto plano, que es lo que se le ensena al guionista."""
    lineas = [
        f"Idioma: {brief['idioma_salida_nombre']}",
        f"Voz: velocidad {brief['velocidad']}, aire {brief['hueco_minimo']}s "
        f"({brief['palabras_por_segundo']} palabras/s, {brief['cadencia_origen']})",
        f"Duracion objetivo: {brief['duracion_objetivo_s']} s "
        f"(+-{int(brief['margen']['tolerancia'] * 100)}%)",
        f"Presupuesto: {brief['presupuesto_palabras']} palabras "
        f"(entre {brief['palabras_minimo']} y {brief['palabras_maximo']})",
        f"Bloques estimados: {brief['bloques_estimados']} de unas "
        f"{brief['palabras_por_bloque']} palabras",
        "",
        "Lo que pide el usuario:",
        brief["instrucciones"],
    ]
    if brief["avisos"]:
        lineas.append("")
        lineas.append("Avisos:")
        lineas.extend(f"  - {aviso}" for aviso in brief["avisos"])
    return "\n".join(lineas) + "\n"
