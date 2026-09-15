"""
Presets de canal: lo que se decide una vez por canal y se repite en cada video.

Para que
--------
Un canal tiene un idioma, un estilo grafico, una cadencia y una voz, y esas
cuatro cosas son las MISMAS en todos sus videos. Hoy hay que volver a tomarlas
en cada proyecto: pegar la URL del video de estilo, extraer 80 fotogramas,
elegir ocho, escribir la guia, buscar la voz entre 864, mover el deslizador de
duracion. Un preset guarda esa decision con un nombre y la vuelve a poner de un
desplegable.

Los tipos son cinco y cada uno declara los pasos del grafo a los que toca:

    guion   -> brief + guion    instrucciones, idioma, duracion, ritmo
    estilo  -> assets           fotogramas, guia escrita, calidad y plano
    rotulos -> callouts         diseno, colores fijados a mano y tamano del
                                subtitulo. El id se quedo en 'rotulos' porque es
                                la clave de los presets ya guardados en disco
    voz     -> voz              modelo, voz, idioma, velocidad, emociones, aire
    canal   -> los cuatro       un paquete con lo de arriba dentro

Un preset por DECISION, no por parametro: hubo un momento en que habia uno de
"idioma" y otro de "estilo de video", y guardar con nombre y miniatura algo que
es un desplegable de una sola opcion es mas ceremonia que la decision que
ahorra.

Aplicar COPIA los valores, no guarda el nombre
----------------------------------------------
Un preset aplicado deja de existir como tal: lo que queda en el proyecto son sus
valores dentro de los params del paso. Es a proposito. Si se guardara el nombre,
borrar un preset romperia un video terminado -- que es justo lo que pasa hoy con
los presets de voz escritos en el codigo (`presets_voz.preset()` lanza
ValueError con los validos). Copiando los valores, tu lista de presets es tuya y
lo que ya esta hecho no depende de ella.

Los fotogramas se COPIAN al banco
---------------------------------
Un preset de estilo apunta a fotogramas concretos del disco. Si apuntara a los
del proyecto donde se creo, extraer estilo otra vez en ese proyecto los borra
(`estilo.extraer` sustituye la carpeta entera) y el preset se queda apuntando a
ficheros que ya no estan. Por eso al guardar se copian a banco/presets/<id>/, que
no lo toca nadie mas, y de ahi sale tambien la miniatura.

Y con ellos van las referencias DIBUJADAS
-----------------------------------------
El moodboard --las laminas de estilo dibujadas a proposito-- es parte del estilo
grafico de un canal, no de un video: se dibuja una vez, se mira una vez y lo
hereda todo lo que venga despues. Por eso un preset de estilo se lo lleva
dentro, en banco/presets/<id>/moodboard/, y al aplicarlo se devuelve al banco de
moodboards si alli ya no esta.

Encontrarlo no depende de eso: la clave de un moodboard sale del CONTENIDO de los
fotogramas, asi que la copia del preset da la misma clave que el original. La
copia es para el dia que el banco se limpie o el preset se lleve a otra maquina,
que es exactamente el motivo por el que tambien se copian los fotogramas.

La papelera es aparte de la de proyectos
----------------------------------------
Un preset borrado va a una papelera propia dentro de este mismo fichero, con su
etiqueta. No se mezcla con la de proyectos porque lo que se pierde al vaciarla
no se parece en nada: un proyecto son gigas de imagenes pagadas, un preset son
unos fotogramas y un parrafo. Se ensenan juntos en la misma pantalla, pero cada
uno dice lo que es.
"""
import copy
import os
import re
import shutil
import sys
import time

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_ESTUDIO not in sys.path:
    sys.path.insert(0, RAIZ_ESTUDIO)

from nucleo.proyecto import ahora, escribir_json, leer_json, lock_de  # noqa: E402

# Redirigibles por entorno para que una prueba no escriba en el banco real:
# prueba_api arranca el servidor contra una carpeta temporal y sin esto sus
# presets de mentira acababan en el presets.json del canal.
FICHERO = os.environ.get("ESTUDIO_PRESETS") \
    or os.path.join(RAIZ_ESTUDIO, "presets.json")
BANCO = os.environ.get("ESTUDIO_BANCO_PRESETS") \
    or os.path.join(RAIZ_ESTUDIO, "banco", "presets")


class ErrorPreset(Exception):
    """Fallo de un preset con mensaje pensado para que lo lea una persona."""


# --------------------------------------------------------------------- tipos

# Cada tipo declara QUE claves lleva y a que paso del grafo van. La lista de
# claves es cerrada a proposito: una clave que no este aqui no se guarda y se
# dice en voz alta, porque un preset que arrastra basura la aplicaria en
# silencio sobre los params de un proyecto y ahi ya no hay quien la encuentre.
TIPOS = {
    # Un preset por DECISION, no por parametro. Hubo un momento en que esto
    # tenia un preset de "idioma" y otro de "estilo de video", y no tenian
    # sentido: guardar con nombre y miniatura algo que es un desplegable de una
    # sola opcion es mas ceremonia que la decision que ahorra. Lo que de verdad
    # se repite entre videos de un canal es el GUION entero: en que idioma, con
    # que duracion y con que tono.
    "guion": {
        "nombre": "Guion",
        "que_fija": ("las instrucciones, el idioma, la duracion, "
                     "el tamano de bloque, las anotaciones de voz y el ajuste "
                     "del CLI"),
        # Las anotaciones de voz van aqui y no en el preset de voz: donde para
        # el relato se decide al ESCRIBIR, no al locutar, y es una costumbre del
        # canal -- hay canales que narran seguido y canales que respiran.
        # LO QUE NO ENTRA AQUI, Y ES DELIBERADO: `cta`, o sea la presentacion y
        # las llamadas a la accion (`pasos/cta.py`). Se deciden VIDEO POR VIDEO,
        # asi que no viajan en el estilo: si viajaran, elegir un estilo pisaria
        # lo que se acaba de escribir para ESTE video, que es justo lo contrario
        # de lo que espera quien elige un estilo.
        "claves": ("instrucciones", "idioma_salida", "idiomas_salida",
                   "duracion_objetivo_s",
                   "palabras_por_bloque",
                   "anotaciones_voz", "emocion_en_voz",
                   "modelo", "esfuerzo"),
        "pasos": ("brief", "guion"),
    },
    "estilo": {
        "nombre": "Estilo gráfico",
        "que_fija": ("los fotogramas de referencia, la guia escrita, las "
                     "referencias dibujadas, la calidad de imagen y la duracion "
                     "de plano"),
        # La calidad y la duracion de plano viven AQUI y no en un preset aparte
        # porque son lo mismo que el estilo: como se ve el video. Un canal que
        # dibuja plano y corta cada 3 s no elige esas dos cosas por separado.
        #
        # 'moodboard' NO lo manda la interfaz: lo pone el servidor al guardar,
        # mirando que laminas hay APROBADAS para esos fotogramas. Es un dato
        # derivado, y dejar que viajara desde el navegador seria dejar que el
        # preset dijera que tiene referencias dibujadas que nadie ha mirado.
        "claves": ("referencias", "guia", "url", "moodboard",
                   "calidad", "min_s", "max_s", "min_s_rotulos"),
        "pasos": ("assets",),
    },
    # El id se queda en 'rotulos' aunque ya no haya rotulos: es la clave con la
    # que estan guardados los presets del canal en disco, y renombrarla los
    # dejaria huerfanos. Lo que cambia es lo que se LEE y lo que se guarda.
    "rotulos": {
        "nombre": "Grafismo",
        "que_fija": ("como se dibuja el texto en pantalla: el set de diseno, los "
                     "colores fijados a mano y el tamano del subtitulo"),
        # `arquetipos` se cae: los rotulos se retiraron enteros el 22-08 y esa
        # clave llevaba desde entonces guardandose y aplicandose sin que nadie la
        # leyera. Y entra `subtitulo_tam`, que SI es una decision de grafismo y
        # se quedaba fuera: guardar un preset y aplicarlo perdia el tamano.
        "claves": ("diseno", "paleta", "subtitulo_tam"),
        "pasos": ("callouts",),
    },
    "voz": {
        "nombre": "Voz",
        "que_fija": ("modelo, voz, idioma de locucion, velocidad, emociones y "
                     "aire entre bloques"),
        "claves": ("modelo", "voz_id", "voz_nombre", "idioma", "velocidad",
                   "emociones", "hueco_minimo"),
        "pasos": ("voz",),
    },
    "canal": {
        "nombre": "Canal",
        "que_fija": "de golpe el guion, el estilo grafico y la voz",
        # las claves de un canal son los OTROS tipos: dentro de cada una va el
        # bloque de datos de ese tipo, tal cual. Y ademas 'origen', que no es un
        # tipo: ver ORIGEN mas abajo.
        "claves": ("guion", "estilo", "voz", "rotulos", "origen"),
        "pasos": ("brief", "guion", "assets", "voz", "callouts"),
    },
}

#: DE DONDE SALIO EL PRESET, y no es documentacion: es lo que permite REHACER
#: una de sus tres partes sin volver a pedirlo todo.
#:
#: El modo light crea un canal entero a partir de cuatro campos (un video o una
#: descripcion para el estilo grafico, otro para el tono, una descripcion para la
#: voz y un idioma). Cuando despues se pide «que los subtitulos sean mas claros»,
#: lo que hay que rehacer es el estilo grafico CON SU ENTRADA ORIGINAL mas esa
#: correccion. Sin guardar la entrada, la unica forma de corregir seria volver a
#: pegar la URL, que es justo la ceremonia que este modo quita.
#:
#: `taller` es el id del proyecto oculto donde se genero: ahi siguen las
#: imagenes que se adjuntaron, asi que rehacer la guia no las vuelve a pedir.
CLAVES_ORIGEN = ("estilo_prompt", "estilo_imagenes", "tono_prompt",
                 "voz_prompt", "voz_id", "idioma", "ritmo", "taller", "feedback",
                 # Descripciones cortas de lo que salio, para poder ENSENAR el
                 # estilo sin abrirlo entero. No son params: no se aplican a
                 # ningun paso, solo se leen.
                 "tono_resumen", "estilo_resumen", "muestras")

# Orden en el que se ensenan y en el que se aplican. El guion va primero porque
# el resto se lee en el: la voz hereda el idioma que fija el guion.
ORDEN = ("guion", "estilo", "voz", "rotulos")


def tipos():
    """Catalogo de tipos para pintar la interfaz, en orden."""
    fichas = []
    for clave in list(ORDEN) + ["canal"]:
        ficha = dict(TIPOS[clave])
        ficha["id"] = clave
        ficha["claves"] = list(ficha["claves"])
        ficha["pasos"] = list(ficha["pasos"])
        fichas.append(ficha)
    return fichas


def _validar_tipo(tipo):
    clave = str(tipo or "").strip()
    if clave not in TIPOS:
        raise ErrorPreset(f"tipo de preset desconocido: {tipo!r}. "
                          f"Los tipos son: {', '.join(TIPOS)}")
    return clave


def _limpiar_datos(tipo, datos):
    """Deja solo las claves declaradas del tipo, y protesta por las demas."""
    if not isinstance(datos, dict):
        raise ErrorPreset(f"los datos de un preset de {tipo} tienen que ser un "
                          f"objeto, ha llegado {type(datos).__name__}")
    permitidas = TIPOS[tipo]["claves"]
    sobran = [c for c in datos if c not in permitidas]
    if sobran:
        raise ErrorPreset(
            f"un preset de {tipo} no sabe guardar {', '.join(sorted(sobran))}. "
            f"Lo que guarda es: {', '.join(permitidas)}")
    limpios = {c: copy.deepcopy(v) for c, v in datos.items()
               if v is not None and v != ""}
    if tipo == "canal":
        # un canal es un paquete de los otros tipos: cada bloque se valida con
        # las reglas de SU tipo, o el paquete se convierte en el agujero por
        # donde entra lo que los demas rechazan
        for sub, bloque in list(limpios.items()):
            if sub == "origen":
                # 'origen' NO es un tipo de preset: es de donde salio este. Su
                # lista de claves es igual de cerrada que las demas, por el
                # mismo motivo -- lo que no se declara aqui viajaria sin que
                # nadie lo lea.
                if not isinstance(bloque, dict):
                    raise ErrorPreset("el origen de un preset de canal tiene "
                                      "que ser un objeto")
                sobran = [c for c in bloque if c not in CLAVES_ORIGEN]
                if sobran:
                    raise ErrorPreset(
                        f"el origen de un canal no sabe guardar "
                        f"{', '.join(sorted(sobran))}. Lo que guarda es: "
                        + ", ".join(CLAVES_ORIGEN))
                limpios[sub] = {c: copy.deepcopy(v) for c, v in bloque.items()
                                if v is not None and v != ""}
                continue
            limpios[sub] = _limpiar_datos(sub, bloque)
    if not limpios:
        raise ErrorPreset(f"un preset de {tipo} vacio no fija nada: "
                          f"pon algun valor antes de guardarlo")
    return limpios


# ------------------------------------------------------------------ el fichero

def _vacio():
    return {"presets": [], "papelera": []}


def _leer():
    datos = leer_json(FICHERO, None)
    if not isinstance(datos, dict):
        return _vacio()
    salida = _vacio()
    for grupo in salida:
        salida[grupo] = [f for f in (datos.get(grupo) or [])
                         if isinstance(f, dict) and f.get("id")]
    return salida


def _escribir(datos):
    escribir_json(FICHERO, datos)


def _nuevo_id(ocupados=()):
    """Un id que no esté cogido. El reloj SOLO no basta.

    Era `pr{milisegundos:x}` a secas, y dos presets guardados en el mismo
    milisegundo salían con el MISMO id. Y eso no daba error: `guardar` ve un id
    que ya existe, lo toma por una actualización y **sustituye el preset
    anterior**. O sea que guardar dos presets seguidos se llevaba uno por
    delante, en silencio.

    Se veía como una suite intermitente —`prueba_presets` fallaba dos de cada
    tres veces con un `KeyError: 'referencias'`, que era el preset de estilo
    pisado por el siguiente— y en la interfaz habría sido «he guardado dos y
    solo aparece uno». Cuanto más rápida la máquina, más a menudo.

    Con la lista de ocupados delante, el segundo del mismo milisegundo coge el
    siguiente hueco. Sigue siendo un id legible y ordenado por tiempo.
    """
    ocupados = set(ocupados)
    marca = int(time.time() * 1000)
    while f"pr{marca:x}" in ocupados:
        marca += 1
    return f"pr{marca:x}"


def carpeta_de(pid):
    """Donde viven los ficheros propios de un preset (fotogramas, miniatura)."""
    return os.path.join(BANCO, str(pid))


def ruta_de_miniatura(ficha):
    """La miniatura de un preset, resuelta contra ESTA maquina.

    De lo guardado solo vale el NOMBRE. La miniatura vive dentro de la carpeta
    del preset y solo ahi --`_sembrar_ficheros` la copia alli--, asi que la ruta
    entera no aporta nada y ademas estorba: una ficha escrita en otra maquina, o
    en otra cuenta, trae una ruta que aqui no existe y la tarjeta se quedaba sin
    cara sin decir por que. El banco tambien se mueve (ESTUDIO_BANCO_PRESETS), y
    una ruta absoluta guardada el mes pasado no lo sabe.

    Quedarse con el nombre NO afloja lo que protege al endpoint que la sirve: el
    nombre se pega a la carpeta del preset, asi que no puede apuntar fuera.
    """
    cruda = str((ficha or {}).get("miniatura") or "").strip()
    if not cruda:
        return ""
    # se parte por las DOS barras: la ruta pudo escribirla Windows o Linux
    nombre = os.path.basename(cruda.replace("\\", "/"))
    if not nombre or nombre in (".", ".."):
        return ""
    return os.path.join(carpeta_de((ficha or {}).get("id") or ""), nombre)


def carpeta_moodboard_de(pid):
    """Donde guarda un preset de estilo sus referencias dibujadas."""
    return os.path.join(carpeta_de(pid), "moodboard")


def _moodboard():
    """El modulo de moodboards, importado tarde.

    Tarde porque `pasos/__init__` carga presets_canal antes que medios y
    moodboard, y porque un preset de guion o de voz no tiene por que arrastrar
    la cadena de imagen para guardarse.
    """
    import moodboard                                   # noqa: PLC0415
    return moodboard


# -------------------------------------------------------------------- resumen

#: Cache en memoria de {voz_id: nombre}, atada al mtime del fichero de voces:
#: se relee solo cuando el catalogo de disco cambia.
_VOCES_MEMO = {"mtime": None, "por_id": {}}


def _nombre_de_voz(voz_id):
    """Nombre de una voz segun el CATALOGO cacheado en disco, sin tocar la red.

    El resumen del desplegable no puede fiarse del `voz_nombre` que mande el
    navegador: llego podrido cuando el catalogo cargado en la pantalla era el
    de otro idioma y no pudo resolver el id («Crayon Voice» decia el nombre de
    la voz anterior). Tampoco puede costar una descarga, que esto se pinta al
    listar el banco: se lee la cache que mantiene p4_voz y, si el id no esta
    en ella, quien llama cae al nombre guardado.
    """
    if not voz_id:
        return ""
    try:
        import p4_voz                                  # noqa: PLC0415
    except ImportError:
        from . import p4_voz                           # noqa: PLC0415
    try:
        mtime = os.path.getmtime(p4_voz.RUTA_CACHE_VOCES)
    except OSError:
        return ""
    if _VOCES_MEMO["mtime"] != mtime:
        voces = (leer_json(p4_voz.RUTA_CACHE_VOCES, {}) or {}).get("voces") or []
        _VOCES_MEMO["mtime"] = mtime
        _VOCES_MEMO["por_id"] = {v.get("id"): v.get("nombre", "")
                                 for v in voces if v.get("id")}
    return _VOCES_MEMO["por_id"].get(str(voz_id), "")


def resumen_de(ficha):
    """Una linea que dice lo que hay dentro sin tener que abrirlo.

    Es la misma regla que los plegables de la interfaz: nada se esconde sin
    resumen. Un desplegable de presets donde solo se lee el nombre obliga a
    aplicar uno para saber que hace.

    Esta es de las pocas cadenas de este repositorio que van CON tildes: no se
    imprime en una consola, se pinta en el desplegable de la interfaz, y ahi
    «guia de 42 palabras» se lee como una errata. Lo de escribir sin tildes es
    por compatibilidad de consolas, no una regla del idioma.
    """
    tipo = ficha.get("tipo")
    datos = ficha.get("datos") or {}
    if tipo == "guion":
        trozos = [_idioma_de_guion(datos) or "sin idioma"]
        if datos.get("duracion_objetivo_s"):
            segundos = int(datos["duracion_objetivo_s"])
            trozos.append(f"{segundos // 60}m {segundos % 60:02d}s")
        if datos.get("instrucciones"):
            trozos.append("con instrucciones")
        return " · ".join(trozos)
    if tipo == "estilo":
        cuantas = len(datos.get("referencias") or [])
        guia = datos.get("guia") or {}
        trozos = [f"{cuantas} fotograma(s)"]
        trozos.append(f"guía de {guia.get('palabras', '?')} palabras" if guia
                      else "sin guía escrita")
        dibujadas = len((datos.get("moodboard") or {}).get("ejes") or [])
        if dibujadas:
            trozos.append(f"{dibujadas} referencias dibujadas")
        if datos.get("min_s") or datos.get("max_s"):
            trozos.append(f"planos {datos.get('min_s', '?')}-{datos.get('max_s', '?')}s")
        if datos.get("calidad"):
            trozos.append(f"calidad {datos['calidad']}")
        return " · ".join(trozos)
    if tipo == "voz":
        emociones = datos.get("emociones") or []
        return " · ".join(x for x in [
            _nombre_de_voz(datos.get("voz_id"))
            or datos.get("voz_nombre") or datos.get("voz_id", "")[:8],
            datos.get("modelo"), datos.get("idioma"),
            str(datos.get("velocidad") or "normal"),
            ", ".join(emociones) if emociones else "sin color",
        ] if x)
    if tipo == "rotulos":
        fijados = len((datos.get("paleta") or {}).get("fijados") or {})
        return " · ".join(x for x in [
            datos.get("diseno") or "diseño por defecto",
            f"subtítulo {datos['subtitulo_tam']}" if datos.get("subtitulo_tam") else "",
            f"{fijados} color(es) a mano" if fijados else "",
        ] if x)
    if tipo == "canal":
        # Un canal del modo light se lee por VINETAS (ver `vinetas_de`), no por
        # esta linea. La linea sigue existiendo para el desplegable del modo
        # editor, que es donde nacio.
        vinetas = vinetas_de(ficha)
        if vinetas:
            return " · ".join(v["texto"] for v in vinetas)
        dentro = [TIPOS[s]["nombre"].lower() for s in ORDEN if datos.get(s)]
        return ("lleva " + ", ".join(dentro)) if dentro else "vacío"
    return ""


#: Los idiomas por nombre, para la tarjeta. Es la misma tabla que la pantalla
#: (`IDIOMAS_SALIDA` + `NOMBRES_IDIOMA` en app.js) y por eso lleva tildes: se
#: lee, no se imprime en una consola.
NOMBRES_IDIOMA = {
    "es": "Español", "en": "Inglés", "pt": "Portugués", "fr": "Francés",
    "it": "Italiano", "de": "Alemán", "ca": "Catalán", "gl": "Gallego",
    "eu": "Euskera",
}


def _idioma_de_guion(bloque):
    """El idioma de un bloque de guion, venga en la clave nueva o en la vieja.

    UN VIDEO, UN IDIOMA desde el 24-08-2026: la clave es `idioma_salida`. La
    lista `idiomas_salida` se sigue leyendo --el primero era el principal--
    porque hay presets guardados con ella; no se vuelve a escribir.
    """
    bloque = bloque or {}
    codigo = str(bloque.get("idioma_salida") or "").strip().lower()
    if codigo:
        return codigo
    lista = bloque.get("idiomas_salida") or []
    if isinstance(lista, str):
        lista = [lista]
    return str((lista or [""])[0]).strip().lower()


def idioma_de(ficha):
    """El idioma del canal. Sale del guion, que es quien lo decide.

    No se guarda como clave propia a proposito: ya vive en `guion.idioma_salida`
    y en `voz.idioma`, y una tercera copia seria una tercera cosa que puede
    contradecir a las otras dos.
    """
    datos = (ficha.get("datos") or {})
    codigo = _idioma_de_guion(datos.get("guion"))
    if codigo:
        return codigo
    return str((datos.get("voz") or {}).get("idioma") or "").strip().lower()


def vinetas_de(ficha):
    """Las lineas cortas que dicen QUE es este preset. -> [{icono, texto}]

    Es lo que se lee debajo de la miniatura en la galeria del modo light. Cortas
    a proposito: la tarjeta se mira, no se estudia. Lo largo --la guia entera,
    las instrucciones de tono-- vive dentro, al editarlo.

    EL ICONO LO PONE AQUI Y NO LA PANTALLA. La pantalla recibe una lista de
    lineas y no sabe cual es el idioma y cual la voz; ponerle el icono alli
    obligaria a deducirlo por el orden, que es exactamente lo que se rompe el
    dia que una linea no salga -- un preset sin voz, o uno sin guia escrita.
    """
    if ficha.get("tipo") != "canal":
        return []
    datos = ficha.get("datos") or {}
    origen = datos.get("origen") or {}
    estilo = datos.get("estilo") or {}
    lineas = []

    def poner(icono, texto):
        texto = " ".join(str(texto or "").split())
        if texto:
            lineas.append({"icono": icono, "texto": texto})

    idioma = idioma_de(ficha)
    poner("🌐", NOMBRES_IDIOMA.get(idioma, idioma) if idioma else "")

    guia = estilo.get("guia") if isinstance(estilo.get("guia"), dict) else {}
    resumen_estilo = " ".join(str((guia or {}).get("resumen_es") or "").split())
    if resumen_estilo:
        poner("🎨", _recortar(resumen_estilo, 70))
    elif estilo:
        poner("🎨", f"{len(estilo.get('referencias') or [])} referencias de estilo")

    tono = " ".join(str((datos.get("guion") or {}).get("instrucciones") or "").split())
    poner("🗣️", _recortar(str(origen.get("tono_prompt") or tono), 70))

    voz = datos.get("voz") or {}
    if voz:
        nombre = (_nombre_de_voz(voz.get("voz_id")) or voz.get("voz_nombre")
                  or str(voz.get("voz_id") or "")[:8])
        poner("🎙️", " · ".join(x for x in [nombre, str(voz.get("velocidad") or "").strip()] if x))

    # El ritmo se lee de los VALORES y no del `origen`: es lo que de verdad
    # tiene puesto el preset, y asi un canal montado a mano en el modo editor
    # tambien dice a que ritmo va.
    minimo = estilo.get("min_s")
    if minimo is not None:
        poner("⏱️", f"planos de {float(minimo):g}-{float(estilo.get('max_s') or 0):g} s")

    return lineas[:5]


def _recortar(texto, tope):
    texto = str(texto or "").strip()
    if len(texto) <= tope:
        return texto
    return texto[:tope - 1].rstrip(" ,.;:") + "…"


def _publicar(ficha):
    """Copia de la ficha con lo calculado que necesita la interfaz."""
    salida = copy.deepcopy(ficha)
    salida["resumen"] = resumen_de(ficha)
    salida["tipo_nombre"] = TIPOS.get(ficha.get("tipo"), {}).get("nombre", "")
    # Las vinetas y el idioma son de la tarjeta del modo light. Se calculan aqui
    # y no en el navegador porque quien sabe donde vive el idioma de un canal es
    # la tabla de tipos, igual que con `cambios_para`.
    salida["vinetas"] = vinetas_de(ficha)
    salida["idioma"] = idioma_de(ficha)
    # El ritmo con el que se creo, para que el deslizador de la pantalla sepa
    # donde ponerse. Vive en `origen` porque es la ENTRADA que se dio; lo que el
    # preset fija de verdad son los min_s/max_s que hay en `estilo`.
    salida["origen_ritmo"] = str(
        ((ficha.get("datos") or {}).get("origen") or {}).get("ritmo") or "")
    # que la miniatura este en el disco no se da por hecho: el banco es una
    # carpeta que alguien puede limpiar a mano, y una miniatura rota deja un
    # hueco raro en el desplegable sin decir por que
    salida["hay_miniatura"] = os.path.isfile(ruta_de_miniatura(ficha))
    return salida


def publicar(ficha):
    """La ficha tal y como la ve la interfaz: con resumen y sin sorpresas."""
    return _publicar(ficha)


# ------------------------------------------------------------------ operaciones

def listar():
    """Todo lo guardado, agrupado por tipo, mas la papelera de presets."""
    datos = _leer()
    por_tipo = {clave: [] for clave in TIPOS}
    for ficha in datos["presets"]:
        tipo = ficha.get("tipo")
        if tipo in por_tipo:
            por_tipo[tipo].append(_publicar(ficha))
    for lista in por_tipo.values():
        lista.sort(key=lambda f: str(f.get("nombre") or "").lower())
    return {
        "presets": por_tipo,
        "papelera": [_publicar(f) for f in datos["papelera"]],
        "tipos": tipos(),
        "total": sum(len(v) for v in por_tipo.values()),
    }


def leer(pid):
    """Una ficha por id, mire donde mire (activos o papelera)."""
    datos = _leer()
    for grupo in ("presets", "papelera"):
        for ficha in datos[grupo]:
            if ficha.get("id") == str(pid):
                return copy.deepcopy(ficha)
    raise ErrorPreset(f"no hay ningun preset con id {pid!r}")


def guardar(tipo, nombre, datos, nota="", miniatura="", pid=None):
    """Guarda un preset nuevo, o sustituye el contenido de uno que ya existe.

    `miniatura` es una de las rutas de `datos['referencias']` (solo tipo
    estilo). Si no se dice, se coge la primera: un preset sin cara en el
    desplegable obliga a leer el nombre para saber cual es cual, y el nombre lo
    escribio alguien con prisa.
    """
    tipo = _validar_tipo(tipo)
    nombre = str(nombre or "").strip()
    if not nombre:
        raise ErrorPreset("un preset necesita un nombre: es lo unico que se ve "
                          "en el desplegable")
    limpios = _limpiar_datos(tipo, datos)

    with lock_de(FICHERO):
        guardado = _leer()
        anterior = None
        if pid:
            anterior = next((f for f in guardado["presets"] if f.get("id") == pid), None)
            if anterior is None:
                raise ErrorPreset(f"no hay ningun preset con id {pid!r} que actualizar")
            if anterior.get("tipo") != tipo:
                raise ErrorPreset(
                    f"el preset {pid} es de tipo {anterior.get('tipo')}, no de "
                    f"{tipo}: cambiarle el tipo lo convertiria en otra cosa con "
                    f"el mismo nombre")
        # con los ya guardados delante: sin eso, dos presets del mismo
        # milisegundo comparten id y el segundo SUSTITUYE al primero
        identificador = pid or _nuevo_id(
            f.get("id") for f in guardado["presets"])

        limpios, ruta_miniatura = _sembrar_ficheros(tipo, identificador, limpios,
                                                    miniatura, anterior)

        ficha = {
            "id": identificador,
            "tipo": tipo,
            "nombre": nombre,
            "nota": str(nota or "").strip(),
            "fecha": (anterior or {}).get("fecha") or ahora(),
            "modificado": ahora(),
            "miniatura": ruta_miniatura,
            "datos": limpios,
        }
        if anterior is not None:
            guardado["presets"] = [ficha if f.get("id") == identificador else f
                                   for f in guardado["presets"]]
        else:
            guardado["presets"].append(ficha)
        _escribir(guardado)
    return _publicar(ficha)


def es_propio_de_canal(nombre):
    """Ficheros que un canal tiene en propiedad y NO salen de sus fotogramas.

    Son la miniatura 2x2 y las cuatro muestras sueltas: se dibujaron a proposito
    para ese preset --con sus cartelas y su subtitulo encima-- y no estan en
    `estilo.referencias` ni en ningun otro sitio de donde recuperarlas.
    """
    return (nombre == "miniatura.png"
            or (nombre.startswith("muestra") and nombre.endswith(".png")))


def _apartar_propios(pid):
    """Se lleva a un lado lo que el canal tiene en propiedad. -> carpeta o ''.

    SEMBRAR EL ESTILO BORRA LA CARPETA ENTERA y la rehace desde los fotogramas
    (el `shutil.rmtree(destino)` de mas abajo), asi que todo lo que no sea un
    fotograma se pierde en cada guardado. En el PRIMERO no se nota --las muestras
    se copian despues, al congelar el preset-- pero el segundo se las llevaba por
    delante: cambiar el nombre, mover el ritmo o tocar un mando de voz dejaba la
    ficha diciendo `muestra1.png` con la carpeta sin ninguna. O sea el banner del
    estilo en blanco, y la tarjeta de la galeria con un fotograma crudo en vez de
    con su 2x2.
    """
    carpeta = carpeta_de(pid)
    if not os.path.isdir(carpeta):
        return ""
    nombres = [n for n in sorted(os.listdir(carpeta)) if es_propio_de_canal(n)]
    if not nombres:
        return ""
    aparte = f"{carpeta}.propios"
    shutil.rmtree(aparte, ignore_errors=True)
    try:
        os.makedirs(aparte, exist_ok=True)
        for nombre in nombres:
            shutil.copyfile(os.path.join(carpeta, nombre),
                            os.path.join(aparte, nombre))
    except OSError:
        shutil.rmtree(aparte, ignore_errors=True)
        return ""
    return aparte


def _devolver_propios(pid, aparte):
    """Las devuelve a la carpeta ya rehecha, y limpia el rincon."""
    if not aparte or not os.path.isdir(aparte):
        return
    carpeta = carpeta_de(pid)
    try:
        os.makedirs(carpeta, exist_ok=True)
        for nombre in sorted(os.listdir(aparte)):
            shutil.copyfile(os.path.join(aparte, nombre),
                            os.path.join(carpeta, nombre))
    except OSError:
        pass            # lo que se pierde es el banner, no el preset
    shutil.rmtree(aparte, ignore_errors=True)


def _sembrar_ficheros(tipo, pid, datos, miniatura, anterior):
    """Copia al banco lo que el preset necesita tener en propiedad.

    Hoy solo el estilo: sus fotogramas viven en la carpeta de un proyecto y esa
    carpeta se borra entera cada vez que se extrae estilo otra vez ahi.
    """
    if tipo == "canal":
        ruta = ""
        # apartadas ANTES de sembrar el estilo --que es quien borra la carpeta--
        # y devueltas justo despues. El porque, en `_apartar_propios`. En un
        # preset nuevo no hay carpeta todavia y devuelve '' sin hacer nada.
        aparte = _apartar_propios(pid)
        if datos.get("estilo"):
            # el estilo de dentro de un canal necesita lo mismo que uno suelto
            dentro, ruta = _sembrar_ficheros("estilo", pid, datos["estilo"],
                                             miniatura, None)
            datos = dict(datos, estilo=dentro)
        _devolver_propios(pid, aparte)
        # LA MINIATURA PROPIA. Un canal del modo light no se ensena con uno de
        # sus fotogramas de referencia: se ensena con la muestra 2x2 que se
        # genero a proposito, con sus cartelas y su subtitulo puestos. O sea que
        # la miniatura NO esta entre las referencias, y hay que copiarla aparte.
        # Va DESPUES de sembrar el estilo porque esa siembra rehace la carpeta
        # entera del preset.
        propia = str(miniatura or "").strip()
        destino = os.path.join(carpeta_de(pid), "miniatura.png")
        if propia and os.path.exists(propia) and propia not in (
                datos.get("estilo") or {}).get("referencias", []):
            if os.path.abspath(propia) == os.path.abspath(destino):
                # la que acabamos de devolver: copiar un fichero sobre si mismo
                # revienta con SameFileError. Ya esta donde tiene que estar.
                ruta = destino
            else:
                os.makedirs(os.path.dirname(destino), exist_ok=True)
                try:
                    shutil.copyfile(propia, destino)
                    ruta = destino
                except OSError:
                    pass     # sin cara se sigue: el preset vale igual
        elif os.path.isfile(destino):
            # la 2x2 que se aparto y volvio: la ficha vuelve a apuntar a ella en
            # vez de caer al primer fotograma, que es lo que hacia antes
            ruta = destino
        return datos, ruta
    if tipo != "estilo":
        return datos, ""

    rutas = [str(r) for r in (datos.get("referencias") or []) if str(r).strip()]
    if len(rutas) < 3:
        raise ErrorPreset(
            f"un preset de estilo necesita al menos 3 fotogramas y han llegado "
            f"{len(rutas)}: con menos se describe una escena, no un estilo")
    faltan = [r for r in rutas if not os.path.exists(r)]
    if faltan:
        raise ErrorPreset("estos fotogramas no estan en el disco del servidor: "
                          + ", ".join(faltan[:5]))

    destino = carpeta_de(pid)
    # se copia a un lado y solo se sustituye al final: si algo falla a mitad, el
    # preset anterior sigue entero. Es la misma regla que estilo.extraer
    trabajo = f"{destino}.nuevo"
    shutil.rmtree(trabajo, ignore_errors=True)
    os.makedirs(trabajo, exist_ok=True)
    copiadas, elegida = [], ""
    referencia_miniatura = str(miniatura or "").strip() or rutas[0]
    try:
        for indice, origen in enumerate(rutas):
            nombre = f"{indice:02d}_{os.path.basename(origen)}"
            final = os.path.join(trabajo, nombre)
            shutil.copyfile(origen, final)
            copiadas.append(final)
            if os.path.abspath(origen) == os.path.abspath(referencia_miniatura):
                elegida = final
    except OSError as fallo:
        shutil.rmtree(trabajo, ignore_errors=True)
        raise ErrorPreset(f"no se han podido copiar los fotogramas al banco: {fallo}")

    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    shutil.move(trabajo, destino)
    # las rutas definitivas son las del banco, no las de donde salieron
    finales = [os.path.join(destino, os.path.basename(r)) for r in copiadas]
    elegida = os.path.join(destino, os.path.basename(elegida)) if elegida else finales[0]
    datos = dict(datos, referencias=finales)

    # Las laminas dibujadas se guardan CON el preset, no solo se referencian.
    # Falla en silencio a proposito: no poder copiarlas no puede impedir guardar
    # el estilo, y lo que se pierde es una copia de respaldo de algo que sigue
    # en el banco global.
    datos.pop("moodboard", None)
    try:
        hecho = _moodboard().exportar(finales, carpeta_moodboard_de(pid))
    except Exception:                                   # noqa: BLE001
        hecho = None
    if hecho:
        datos["moodboard"] = {"clave": hecho["clave"], "ejes": list(hecho["ejes"])}
    return datos, elegida


def restaurar_moodboard(ficha):
    """Devuelve al banco las referencias dibujadas que guarda un preset.

    Se llama al APLICAR. Normalmente no hace nada --el moodboard sigue en el
    banco global y se encuentra solo por la huella de los fotogramas--; sirve
    para la maquina nueva y para el banco que alguien ha limpiado.
    """
    tipo = str(ficha.get("tipo") or "")
    datos = ficha.get("datos") or {}
    if tipo == "canal":
        return restaurar_moodboard({"id": ficha.get("id"), "tipo": "estilo",
                                    "datos": datos.get("estilo") or {}})
    guardado = datos.get("moodboard") or {}
    if tipo != "estilo" or not guardado.get("clave"):
        return {"clave": "", "ejes": []}
    try:
        return _moodboard().importar(carpeta_moodboard_de(ficha.get("id")),
                                     guardado["clave"])
    except Exception:                                   # noqa: BLE001
        # lo mismo que al guardar: esto es una red de seguridad, no la via
        # normal, y no puede impedir que se aplique el estilo
        return {"clave": guardado.get("clave") or "", "ejes": []}


def renombrar(pid, nombre=None, nota=None):
    """Cambia el nombre o la nota de un preset SIN tocar lo que guarda.

    Existe como operacion aparte y no como un guardar() con los mismos datos
    porque guardar() vuelve a sembrar los ficheros del preset: en uno de estilo
    eso borra su carpeta del banco y recopia los fotogramas desde las rutas de
    la ficha, que ya apuntan a esa misma carpeta. Funcionar, funciona; pero es
    borrar y rehacer trece ficheros para cambiar una letra, y si algo falla a
    mitad el preset se queda sin fotogramas por haberle corregido una errata al
    nombre.

    Un argumento a None se deja como estaba: renombrar sin tocar la nota es lo
    normal, y mandar "" para conservarla seria una trampa.
    """
    with lock_de(FICHERO):
        guardado = _leer()
        ficha = next((f for f in guardado["presets"] if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningun preset con id {pid!r}")
        if nombre is not None:
            limpio = str(nombre).strip()
            if not limpio:
                raise ErrorPreset("un preset necesita un nombre: es lo unico "
                                  "que se ve en el desplegable")
            ficha["nombre"] = limpio
        if nota is not None:
            ficha["nota"] = str(nota).strip()
        ficha["modificado"] = ahora()
        _escribir(guardado)
    return _publicar(ficha)


def apartar(pid):
    """A la papelera. No borra nada: la ficha y su carpeta siguen enteras."""
    with lock_de(FICHERO):
        guardado = _leer()
        ficha = next((f for f in guardado["presets"] if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningun preset con id {pid!r}")
        guardado["presets"] = [f for f in guardado["presets"] if f.get("id") != str(pid)]
        ficha["apartado"] = ahora()
        guardado["papelera"].insert(0, ficha)
        _escribir(guardado)
    return _publicar(ficha)


def restaurar(pid):
    """Devuelve a la lista un preset apartado."""
    with lock_de(FICHERO):
        guardado = _leer()
        ficha = next((f for f in guardado["papelera"] if f.get("id") == str(pid)), None)
        if ficha is None:
            raise ErrorPreset(f"no hay ningun preset apartado con id {pid!r}")
        guardado["papelera"] = [f for f in guardado["papelera"] if f.get("id") != str(pid)]
        ficha.pop("apartado", None)
        guardado["presets"].append(ficha)
        _escribir(guardado)
    return _publicar(ficha)


def peso(pid):
    """Que hay dentro de un preset apartado, para poder decir que se pierde."""
    ficha = leer(pid)
    carpeta = carpeta_de(pid)
    ficheros = bytes_totales = 0
    for raiz, _, nombres in os.walk(carpeta):
        for nombre in nombres:
            ruta = os.path.join(raiz, nombre)
            ficheros += 1
            try:
                bytes_totales += os.path.getsize(ruta)
            except OSError:
                pass
    return {"id": pid, "nombre": ficha.get("nombre"), "tipo": ficha.get("tipo"),
            "carpeta": carpeta, "ficheros": ficheros, "bytes": bytes_totales,
            "megas": round(bytes_totales / (1024 * 1024), 2)}


def borrar(pid, confirmar=False):
    """Borrado definitivo. Solo alcanza a lo que YA esta en la papelera.

    Un preset vivo hay que apartarlo antes, que es un paso mas y reversible: es
    la misma regla que los proyectos.
    """
    if not confirmar:
        raise ErrorPreset("el borrado definitivo necesita confirmar=true")
    with lock_de(FICHERO):
        guardado = _leer()
        ficha = next((f for f in guardado["papelera"] if f.get("id") == str(pid)), None)
        if ficha is None:
            vivo = any(f.get("id") == str(pid) for f in guardado["presets"])
            if vivo:
                raise ErrorPreset(
                    f"el preset {pid} no esta en la papelera: apartalo primero. "
                    f"Borrar de verdad solo se puede hacer desde la papelera")
            raise ErrorPreset(f"no hay ningun preset apartado con id {pid!r}")
        guardado["papelera"] = [f for f in guardado["papelera"] if f.get("id") != str(pid)]
        _escribir(guardado)
    shutil.rmtree(carpeta_de(pid), ignore_errors=True)
    return {"borrado": pid, "nombre": ficha.get("nombre"), "tipo": ficha.get("tipo")}


# -------------------------------------------------------------------- aplicar

def cambios_para(ficha, params_actuales=None):
    """Que hay que escribir en los params de cada paso para aplicar un preset.

    Devuelve {paso: {clave: valor}}, listo para `estado.actualizar_params`.

    `params_actuales` es {paso: params} y hace falta para el estilo: sus dos
    claves viven DENTRO del diccionario 'estilo' de assets, junto al prompt
    escrito a mano de los proyectos antiguos. Escribir el diccionario entero sin
    mirar lo que habia se llevaria ese prompt por delante sin decirlo, que es
    exactamente la degradacion silenciosa que este sistema no se permite.
    """
    tipo = _validar_tipo(ficha.get("tipo"))
    datos = ficha.get("datos") or {}
    actuales = params_actuales or {}
    cambios = {}

    if tipo == "canal":
        for sub in ORDEN:
            if not datos.get(sub):
                continue
            parcial = cambios_para({"tipo": sub, "datos": datos[sub]}, actuales)
            for paso, valores in parcial.items():
                cambios.setdefault(paso, {}).update(valores)
        return cambios

    if tipo == "guion":
        de_brief = {c: copy.deepcopy(datos[c])
                    for c in ("instrucciones", "duracion_objetivo_s",
                              "palabras_por_bloque") if c in datos}
        codigo = _idioma_de_guion(datos)
        if codigo:
            de_brief["idioma_salida"] = codigo
        # LA VOZ TAMBIEN VA AL BRIEF, y sale del bloque `voz` de ESTE preset.
        #
        # El brief necesita la velocidad y el aire para convertir segundos en
        # palabras (ver p2_brief). Podrian guardarse tambien en el bloque
        # `guion`, y seria una segunda copia dentro del mismo fichero que puede
        # contradecir a la primera. Asi hay UN valor y dos destinos, que es lo
        # que garantiza que el guion se escriba para la voz que despues lo dice.
        #
        # Y `voz_id` con ellas, por la misma razon y por una que se MIDIO: dos
        # voces inglesas con el mismo modelo dan 2,553 y 1,91 palabras/s a
        # velocidad normal, un 25 % de diferencia. Sin el, cambiar de voz dejaba
        # el presupuesto de palabras igual y la toma duraba otra cosa.
        voz = (ficha.get("datos") or {}).get("voz") or {}
        for clave in ("velocidad", "hueco_minimo", "voz_id"):
            if voz.get(clave) not in (None, ""):
                de_brief[clave] = copy.deepcopy(voz[clave])
        # LO QUE VA AL GUION. Tiene que ser lo que `p3_guion` entiende: una
        # clave de aqui que su paso no declare se guarda en el preset, se ve en
        # la ficha y no hace nada -- se escribe una vez y se olvida sola.
        de_guion = {c: copy.deepcopy(datos[c])
                    for c in ("anotaciones_voz", "emocion_en_voz",
                              "modelo", "esfuerzo")
                    if c in datos}
        if de_brief:
            cambios["brief"] = de_brief
        if de_guion:
            cambios["guion"] = de_guion
        return cambios

    if tipo == "estilo":
        rutas = [str(r) for r in (datos.get("referencias") or [])]
        faltan = [r for r in rutas if not os.path.exists(r)]
        if faltan:
            raise ErrorPreset(
                "este preset apunta a fotogramas que ya no estan en el disco: "
                + ", ".join(os.path.basename(r) for r in faltan[:5])
                + ". Vuelve a guardarlo desde un proyecto que los tenga.")
        estilo = dict((actuales.get("assets") or {}).get("estilo") or {})
        if rutas:
            estilo["referencias"] = rutas
        if datos.get("guia"):
            estilo["guia"] = copy.deepcopy(datos["guia"])
        cambios["assets"] = {"estilo": estilo}
        # la calidad y la duracion de plano son params sueltos de assets, no van
        # dentro del diccionario 'estilo'
        for clave in ("calidad", "min_s", "max_s", "min_s_rotulos"):
            if clave in datos:
                cambios["assets"][clave] = datos[clave]
        return cambios

    if tipo == "rotulos":
        de_callouts = {}
        if datos.get("diseno"):
            de_callouts["diseno"] = datos["diseno"]
        if datos.get("subtitulo_tam"):
            de_callouts["subtitulo_tam"] = datos["subtitulo_tam"]
        if datos.get("paleta"):
            # solo viajan los papeles FIJADOS a mano: el resto se deriva de la
            # guia de estilo de CADA video, que es lo que hace que el rotulo
            # pertenezca a ese dibujo y no al del video donde se guardo
            actual = dict((actuales.get("callouts") or {}).get("paleta") or {})
            actual["fijados"] = copy.deepcopy(datos["paleta"].get("fijados") or {})
            de_callouts["paleta"] = actual
        if de_callouts:
            cambios["callouts"] = de_callouts
        return cambios

    if tipo == "voz":
        # voz_nombre es solo para el resumen del desplegable: no es un param del
        # paso y meterlo cambiaria la firma sin cambiar lo que suena
        cambios["voz"] = {c: copy.deepcopy(v) for c, v in datos.items()
                          if c != "voz_nombre"}
        return cambios

    raise ErrorPreset(f"no se sabe aplicar un preset de tipo {tipo}")


# ------------------------------------------------ de un proyecto a un preset
#
# EL INVERSO DE `cambios_para`, y vive pegado a el a proposito: los dos usan la
# MISMA tabla de claves, y separarlos en dos ficheros es como se acaba con un
# preset que guarda una clave que aplicar no escribe (o al reves), que es un
# fallo mudo -- el preset se guarda, se aplica, y falta media decision.
#
# Lo usa el modo light: alli el canal se genera en un proyecto taller y despues
# se congela en un preset. En el modo editor esto lo hacia el navegador, campo a
# campo, porque alli el usuario elige que meter; aqui no elige nada, se lleva
# todo lo que el taller produjo.

def datos_de_params(params_por_paso, incluir=ORDEN):
    """Los datos de un preset de canal leidos de los params de un proyecto.

    `params_por_paso` es {paso: params}. Devuelve {tipo: {clave: valor}} con
    solo los bloques que de verdad tienen algo: un bloque vacio no se guarda
    porque `_limpiar_datos` lo rechaza, y con razon -- un preset que no fija
    nada no es un preset.
    """
    params = {k: (v or {}) for k, v in (params_por_paso or {}).items()}
    brief = params.get("brief") or {}
    guion = params.get("guion") or {}
    assets = params.get("assets") or {}
    voz = params.get("voz") or {}
    callouts = params.get("callouts") or {}
    estilo = assets.get("estilo") or {}
    datos = {}

    if "guion" in incluir:
        bloque = {}
        for clave in ("instrucciones", "duracion_objetivo_s",
                      "palabras_por_bloque"):
            if brief.get(clave):
                bloque[clave] = copy.deepcopy(brief[clave])
        codigo = (str(brief.get("idioma_salida") or "").strip()
                  or _idioma_de_guion(brief))
        if codigo:
            bloque["idioma_salida"] = codigo
        for clave in ("anotaciones_voz", "emocion_en_voz", "modelo",
                      "esfuerzo"):
            if guion.get(clave) not in (None, ""):
                bloque[clave] = copy.deepcopy(guion[clave])
        if bloque:
            datos["guion"] = bloque

    if "estilo" in incluir:
        bloque = {}
        for clave in ("referencias", "guia", "url"):
            if estilo.get(clave):
                bloque[clave] = copy.deepcopy(estilo[clave])
        for clave in ("calidad", "min_s", "max_s", "min_s_rotulos"):
            if assets.get(clave) not in (None, ""):
                bloque[clave] = copy.deepcopy(assets[clave])
        if bloque:
            datos["estilo"] = bloque

    if "voz" in incluir:
        bloque = {c: copy.deepcopy(voz[c]) for c in TIPOS["voz"]["claves"]
                  if voz.get(c) not in (None, "")}
        if bloque:
            datos["voz"] = bloque

    if "rotulos" in incluir:
        bloque = {c: copy.deepcopy(callouts[c]) for c in TIPOS["rotulos"]["claves"]
                  if callouts.get(c) not in (None, "")}
        if bloque:
            datos["rotulos"] = bloque

    return datos
