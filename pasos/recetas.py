"""Las RECETAS: lo que hay que hacer en cada pestana, en orden, de una tirada.

QUE PROBLEMA RESUELVE
---------------------
Hasta el 20-08-2026 generar un video era pulsar entre quince y veinte botones en
el orden correcto, sabiendose el orden. Y el orden importa de verdad: las
cartelas se deciden ANTES de generar los planos o se paga una imagen para
tirarla, y los rotulos se deciden DESPUES o el agente no tiene imagenes que
antes o el agente no tiene imagenes que mirar. Eso no es una decision
creativa: es una tuberia, y una tuberia la recorre
el programa.

Una receta es la lista de tareas de UNA pestana, con sus dependencias. Con ella:

    Generar toda la pestana   corre todo lo que falta, en orden, y en paralelo
                              lo que no depende de nada
    Generar lo pendiente      lo mismo pero saltandose lo que ya esta hecho y
                              al dia -- para cuando has hecho tres pasos a mano
                              y quieres que el resto se termine solo

Lo que NO cambia: cada tarea sigue teniendo su boton, su ficha y su revision.
Una receta no esconde nada, adelanta trabajo.

QUE VIVE AQUI Y QUE VIVE EN app.py
-----------------------------------
Aqui, los DATOS: que tareas hay, como se llaman, de que dependen, cual cuesta
dinero y cual es opcional. Alli, el codigo: que funcion corre cada tarea, que es
la misma que ya corre su boton. Se parten asi porque la tabla se lee (y se
sirve a la pantalla) sin cargar los motores pesados, y porque una tarea nueva se
declara en un sitio y se implementa en otro sin poder olvidarse ninguno de los
dos: el ejecutor levanta si una tarea declarada no tiene funcion.

LOS AJUSTES DE LA RECETA
------------------------
El modelo y el esfuerzo de cada fase del CLI viajaban POR INVOCACION (nunca en
params, porque moverian la firma del paso y dejarian obsoleto el video entero:
docs/AJUSTES-CLI.md §81). En la pantalla eso eran objetos de JavaScript que se
perdian al recargar. La receta es donde por fin tienen sitio: se guardan aqui,
que es del CANAL y no del video, y por eso no tocan ninguna firma.
"""
import json
import os
import tempfile
import threading

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FICHERO = os.environ.get("ESTUDIO_RECETAS") or os.path.join(RAIZ, "recetas.json")

_LOCK = threading.RLock()


class ErrorReceta(ValueError):
    """Lo que manda la pantalla no vale, y se dice por que."""


# ===========================================================================
# LAS TAREAS
#
#   id          el que usa la API y el que implementa app.py
#   nombre      lo que se lee en pantalla. ES UN SUSTANTIVO, no un verbo, y eso
#               es la mitad de la regla de los dos verbos: el
#               boton dice SIEMPRE «Generar» o «Regenerar» y la tarjeta dice QUE.
#               Con verbos aqui, la barra decia «Grabar la locucion» donde el
#               boton decia «Generar toma completa», para la misma accion.
#   pestana     donde vive
#   necesita    ids de tareas de SU MISMA pestana que tienen que ir antes
#   paso        el paso del grafo al que pertenece (para el estado y la barra)
#   cuesta      si gasta dinero. Lo que cuesta se dice antes de pulsar.
#   opcional    si se puede correr sin ella (y entonces la receta la ofrece
#               con un interruptor). Lo no opcional siempre va.
#   fase        la fase de cli_claude cuyo ajuste usa, si usa alguno
#
# EL ORDEN NO ES ESTETICO. Dos reglas que cuestan dinero si se rompen:
#   - las CARTELAS van antes que los planos: un plano que va a ser cartela no
#     se genera, y decidirlo despues es pagar una imagen para tirarla.
#   - los ROTULOS van despues de los planos: el agente mira las imagenes.
# ===========================================================================

TAREAS = [
    # ------------------------------------------------------------- Origen
    {"id": "ingesta", "nombre": "El material de origen", "pestana": "origen",
     "paso": "ingesta", "necesita": [], "cuesta": False, "opcional": False,
     "porque": "baja el vídeo y los subtítulos, y saca los fotogramas"},

    # -------------------------------------------------------------- Guion
    {"id": "brief", "nombre": "El presupuesto de palabras", "pestana": "guion",
     "paso": "brief", "necesita": [], "cuesta": False, "opcional": False,
     "porque": "cuenta cuántas palabras caben en la duración que has pedido"},
    {"id": "guion", "nombre": "El guion", "pestana": "guion",
     "paso": "guion", "necesita": ["brief"],
     "cuesta": True,
     "opcional": False, "fase": "guion",
     "porque": "redacta el guion con las instrucciones del brief"},

    # ---------------------------------------------------------------- Voz
    {"id": "voz", "nombre": "La locución", "pestana": "voz",
     "paso": "voz", "necesita": [], "cuesta": True, "opcional": False,
     "porque": "sintetiza la toma completa con la voz elegida"},
    {"id": "revision_audio", "nombre": "La revisión por secciones", "pestana": "voz",
     "paso": "revision_audio", "necesita": ["voz"], "cuesta": False,
     "opcional": False,
     "porque": "alinea el guion con el audio para poder escucharlo por secciones"},

    # -------------------------------------------------------------- Video
    {"id": "escenarios", "nombre": "El reparto y los sitios",
     "pestana": "video", "paso": "assets", "necesita": [], "cuesta": True,
     "opcional": False, "fase": "catalogo_visual",
     "porque": "deduce quién sale, dónde ocurre y qué se ve en cada tramo"},
    {"id": "guia_estilo", "nombre": "La guía de estilo",
     "pestana": "video", "paso": "assets", "necesita": [], "cuesta": True,
     "opcional": True, "fase": "guia_estilo",
     "porque": "describe por escrito cómo tiene que verse el vídeo, mirando "
               "los fotogramas de referencia"},
    # EL CORTE EN PLANOS, y es un paso de verdad aunque no cueste nada: reparte
    # la narracion en planos con las marcas de la voz. Lo que viene despues
    # --las cartelas y la direccion-- se decide POR PLANO, asi que sin el corte
    # no hay sobre que decidir. En un video ya generado el plan estaba ahi y
    # esto no hacia falta; en uno NUEVO la tanda entera se plantaba a la mitad
    # con «no hay planos todavia».
    {"id": "corte", "nombre": "El corte en planos", "pestana": "video",
     "paso": "assets", "necesita": ["escenarios"], "cuesta": False,
     "opcional": False,
     "porque": "reparte la narración en planos con las marcas de la voz: es lo "
               "que las cartelas y la dirección necesitan saber para decidir "
               "plano a plano. No llama a ningún modelo"},
    {"id": "plan_cartelas", "nombre": "Las cartelas", "pestana": "video",
     "paso": "assets", "necesita": ["escenarios", "corte"], "cuesta": True,
     "opcional": True, "fase": "plan_cartelas",
     "porque": "un plano que va a ser cartela NO se genera: decidirlo después "
               "sería pagar una imagen para tirarla"},
    # QUE SE VE EN CADA PLANO. Va DESPUES de las cartelas --un plano que va a ser
    # texto no se dirige-- y ANTES de generar: la direccion es una linea mas del
    # prompt, asi que escribirla despues seria pagar la imagen sin ella.
    {"id": "direccion", "nombre": "La dirección de cada plano", "pestana": "video",
     "paso": "assets", "necesita": ["escenarios", "corte", "plan_cartelas"],
     "cuesta": True, "opcional": True, "fase": "direccion",
     # APAGADA DE FABRICA, y es lo que la hace segura de anadir: la primera vez
     # que se dirige un video cambia el prompt de TODOS sus planos, o sea que la
     # cache falla y se vuelven a pagar las imagenes. Encenderla es un clic.
     "de_fabrica": False,
     "porque": "el sitio y la accion del tramo son los mismos para varios "
               "planos seguidos: esto es lo unico que los distingue"},
    # DESPUES DE LAS CARTELAS, y por la misma razon que los planos: un plano que
    # se convierte en cartela pierde su sitio y su gente (`_vaciar_plano`), asi
    # que la pieza que ese plano pedia deja de hacer falta. Generarla antes es
    # pagar un mapa para tirarlo. Y de paso deja de haber dos tareas
    # replanificando a la vez sobre la misma carpeta de trabajo.
    {"id": "piezas", "nombre": "Los personajes y las piezas", "pestana": "video",
     "paso": "assets", "necesita": ["escenarios", "guia_estilo", "corte",
                                    "plan_cartelas"], "cuesta": True,
     "opcional": True,
     "porque": "las hojas de personaje y los mapas que luego usan los planos"},
    {"id": "assets", "nombre": "Los planos", "pestana": "video",
     "paso": "assets", "necesita": ["escenarios", "guia_estilo", "corte",
                                    "plan_cartelas", "direccion", "piezas"],
     "cuesta": True, "opcional": False,
     "porque": "es la parte cara: una imagen por plano"},
    {"id": "callouts", "nombre": "Los subtítulos y el movimiento", "pestana": "video",
     "paso": "callouts", "necesita": ["assets"],
     "cuesta": False, "opcional": False,
     "porque": "escribe los subtítulos con la voz y calcula el movimiento de "
               "cámara: no llama a ningún modelo"},

    # ------------------------------------------------------------- Render
    #
    # LAS DOS DE SONIDO SON ENTRADAS DEL MP4, NO HERMANAS SUYAS. Se leian como
    # tres cosas del mismo tipo -- «La banda sonora / Los efectos de sonido / El
    # MP4»-- y eso invitaba justo a la pregunta que las agrupo: «¿banda sonora y
    # efectos ya no tienen nada que ver con el render final?». Si tienen, y
    # mucho: `sonido.pista_de_efectos` y `sonido.construir_cama` se mezclan
    # DENTRO del MP4, y quitarlas deja el video mudo de todo salvo la locucion.
    #
    # Lo que las distingue de renderizar es de donde sacan el material: las dos
    # SALEN A LA RED (Jamendo, Freesound) para traerlo al banco del canal, y eso
    # se hace una vez y sirve para varios videos. Renderizar no sale a la red
    # nunca: coge del banco lo que digan los params y reparte por semilla, que
    # es lo que hace que el mismo plan suene igual siempre.
    {"id": "banda_sonora", "nombre": "La banda sonora", "pestana": "render",
     "paso": "render", "necesita": [], "cuesta": False, "opcional": True,
     "familia": "sonido",
     "porque": "busca la música de cada tramo en Jamendo y la baja al banco"},
    {"id": "efectos", "nombre": "Los efectos de sonido", "pestana": "render",
     "paso": "render", "necesita": [], "cuesta": False, "opcional": True,
     "familia": "sonido",
     "porque": "los golpes de transición y las teclas, de Freesound al banco"},
    {"id": "render", "nombre": "El MP4", "pestana": "render",
     "paso": "render", "necesita": ["banda_sonora", "efectos"], "cuesta": False,
     "opcional": False,
     "porque": "compone los clips y los muxea con la voz y la banda"},
]

# ===========================================================================
# LAS FAMILIAS
#
# Un grupo de tareas que son LA MISMA COSA vista por partes, y que la pantalla
# pinta junto en vez de como hermanas de las demas. Es el patron que el diseno
# de la interfaz llamaba «familias».
#
# UNA FAMILIA NO ES UNA DECISION. Las dos de sonido son `opcional: True` y
# `de_fabrica: True`: corren solas, no cuestan dinero, y el canal pidio
# expresamente que no se le pregunte -- «musica y sonido casi siempre aciertas,
# no hace falta que de primeras se le pida eso al usuario». Agrupar es cambiar
# como se LEEN, nunca convertirlas en algo que haya que decidir.
# ===========================================================================

FAMILIAS = {
    "sonido": {
        "nombre": "El sonido",
        "porque": "lo que se trae de la red para que el MP4 tenga con qué "
                  "sonar. Se baja una vez al banco del canal y sirve para "
                  "varios vídeos; renderizar ya no sale a la red.",
    },
}

# ===========================================================================
# COMO SE CUENTA ESTO EN PUBLICO
#
# La misma tuberia, dicha para que se entienda SIN ensenar como esta hecha. El
# modo light se graba y se ensena, y ahi la barra decia «3 de 7 · Los planos —
# plano S035 · 41 de 44»: eso es el plano de obra del Estudio, y quien mira el
# video no tiene por que llevarselo.
#
# NO ES TRADUCIR LOS NOMBRES. `nombre` es el sustantivo de la tarjeta (la regla
# de los dos verbos) y sigue siendo lo que lee el modo editor,
# que es de casa. Esto es OTRO vocabulario, con otras reglas:
#
#   · se dice QUE se esta consiguiendo, no COMO. «Escribiendo la historia», no
#     «llamando al redactor con el dosier delante».
#   · ni una palabra de la cocina: nada de prompts, modelos, cartelas, callouts,
#     assets, ficheros, ids de plano ni nombres de motor.
#   · en gerundio, porque es lo que esta pasando AHORA. Aqui no hay ningun boton
#     al lado con el que pueda chocar: los botones siguen diciendo Generar.
#   · `fases` reparte el tramo de la tarea en dos o tres frases. Es lo que hace
#     que una tarea de seis minutos siga contando algo mientras corre, que era
#     justo lo que se perdia al quitar el detalle de dentro.
#
# Y una regla de seguridad: si una tarea nueva no aparece aqui, la barra publica
# NO cae en el mensaje de casa -- dice «Trabajando» y se calla. Un mapeo que
# falla tiene que fallar tapando, no destapando. `prueba_api` lo comprueba.
# ===========================================================================

PUBLICO = {
    "ingesta": {
        "nombre": "Extrayendo el vídeo",
        "fases": ["recogiendo el vídeo", "separando lo que se ve y lo que se dice",
                  "guardando los momentos que sirven"],
    },
    "brief": {
        "nombre": "Midiendo el vídeo",
        "fases": ["calculando cuánto cabe en ese tiempo"],
    },
    "guion": {
        "nombre": "Escribiendo la historia",
        "fases": ["buscando por dónde empezar", "redactando el relato",
                  "rematando el cierre"],
    },
    "voz": {
        "nombre": "Poniéndole voz",
        "fases": ["preparando la lectura", "narrando el relato",
                  "afinando el ritmo"],
    },
    "revision_audio": {
        "nombre": "Escuchando la narración",
        "fases": ["siguiendo la voz palabra por palabra"],
    },
    "escenarios": {
        "nombre": "Entendiendo el concepto visual",
        "fases": ["viendo quién aparece", "viendo dónde ocurre"],
    },
    "guia_estilo": {
        "nombre": "Definiendo la estética",
        "fases": ["mirando las referencias", "escribiendo el criterio visual"],
    },
    "corte": {
        "nombre": "Repartiendo el relato en escenas",
        "fases": ["marcando dónde cambia la imagen"],
    },
    "plan_cartelas": {
        "nombre": "Eligiendo los momentos de texto",
        "fases": ["buscando las frases que se leen"],
    },
    "direccion": {
        "nombre": "Imaginando cada escena",
        "fases": ["decidiendo qué se ve en cada momento"],
    },
    # `unidad` ES EL NOMBRE DE LO QUE SE CUENTA, y solo lo llevan las tareas que
    # trabajan pieza a pieza. Cuando el paso dice por cuantas va, la barra
    # publica ensena esa cuenta EN LUGAR de la fase: «34 de 216 planos» es algo
    # medido y «rematando los detalles» es una frase elegida por tramos.
    "piezas": {
        "nombre": "Creando los personajes",
        "unidad": "piezas",
        "fases": ["dando cara a quien aparece",
                  "preparando lo que se repite en pantalla"],
    },
    "assets": {
        "nombre": "Dibujando las escenas",
        "unidad": "planos",
        "fases": ["componiendo cada imagen", "dando color y luz",
                  "rematando los detalles"],
    },
    "callouts": {
        "nombre": "Sincronizando texto y movimiento",
        "unidad": "planos",
        "fases": ["colocando lo que se lee", "dando movimiento a la cámara"],
    },
    "banda_sonora": {
        "nombre": "Eligiendo la música",
        "fases": ["buscando el tema de cada tramo"],
    },
    "efectos": {
        "nombre": "Añadiendo el sonido",
        "fases": ["recogiendo los golpes y las texturas"],
    },
    "render": {
        "nombre": "Montando el vídeo",
        "unidad": "planos",
        "fases": ["uniendo las escenas", "mezclando voz y música",
                  "cerrando el archivo final"],
    },
}

#: Lo que dice la barra publica cuando no sabe de que tarea le estan hablando.
PUBLICO_GENERICO = "Trabajando"


def publico_de(tid, fraccion=None, unidades=None):
    """Como se cuenta una tarea en publico, con su fase si se sabe por donde va.

    `fraccion` es lo avanzado DENTRO de la tarea (0..1). Sin ella -- o con una
    tarea que no esta en la tabla -- se devuelve solo el titulo, que es el
    comportamiento seguro: antes tapar de mas que destapar de menos.

    `unidades` es (hechas, total) cuando el paso trabaja pieza a pieza y sabe
    por cuantas va. MANDA SOBRE LA FASE, y no es un capricho de formato: la fase
    se elige partiendo la fraccion en tres tramos, asi que «rematando los
    detalles» solo significa «va por el ultimo tercio». Con doscientos dieciseis
    planos delante eso no dice nada y «34 de 216 planos» lo dice todo -- ademas
    de ser lo unico de la linea que esta medido.
    """
    ficha = PUBLICO.get(str(tid)) or {}
    titulo = ficha.get("nombre") or PUBLICO_GENERICO
    cuenta = _cuenta_legible(ficha, unidades)
    if cuenta:
        return f"{titulo} — {cuenta}"
    fases = ficha.get("fases") or []
    if not fases or fraccion is None:
        return titulo
    try:
        valor = min(1.0, max(0.0, float(fraccion)))
    except (TypeError, ValueError):
        return titulo
    indice = min(len(fases) - 1, int(valor * len(fases)))
    return f"{titulo} — {fases[indice]}"


def _cuenta_legible(ficha, unidades):
    """«34 de 216 planos», o "" si no hay una cuenta que ensenar.

    Se calla ante un total de uno: «1 de 1 planos» ocupa una linea para decir
    que hay un plano, y ademas suena a error.
    """
    if not unidades:
        return ""
    try:
        hechas, total = int(unidades[0]), int(unidades[1])
    except (TypeError, ValueError, IndexError):
        return ""
    if total <= 1 or hechas < 0:
        return ""
    return f"{min(hechas, total)} de {total} {ficha.get('unidad') or 'pasos'}"


TAREAS_POR_ID = {t["id"]: t for t in TAREAS}

#: Las pestanas que tienen receta, en el orden en que se recorren.
PESTANAS = ("origen", "guion", "voz", "video", "render")


def tareas_de(pestana):
    """Las tareas de una pestana, en orden de declaracion."""
    return [t for t in TAREAS if t["pestana"] == str(pestana)]


def orden_de(pestana, incluidas=None):
    """Las tareas de una pestana ordenadas por dependencias (topologico).

    `incluidas` recorta la lista; una dependencia que no esta incluida
    simplemente no espera a nadie, que es lo correcto: si has decidido no
    generar el catalogo visual, el guion no tiene que esperarlo.
    """
    tareas = tareas_de(pestana)
    if incluidas is not None:
        tareas = [t for t in tareas if t["id"] in set(incluidas)]
    disponibles = {t["id"] for t in tareas}
    pendientes = list(tareas)
    hechas, salida = set(), []
    while pendientes:
        antes = len(pendientes)
        for tarea in list(pendientes):
            faltan = [d for d in tarea["necesita"]
                      if d in disponibles and d not in hechas]
            if faltan:
                continue
            salida.append(tarea)
            hechas.add(tarea["id"])
            pendientes.remove(tarea)
        if len(pendientes) == antes:
            # Un ciclo en la tabla es un error de programacion, no de datos: se
            # dice en voz alta en vez de colgar la generacion para siempre.
            raise ErrorReceta("ciclo en las dependencias de la receta: "
                              + ", ".join(t["id"] for t in pendientes))
    return salida


def tandas_de(pestana, incluidas=None):
    """Las tareas agrupadas en TANDAS: lo de una tanda puede correr a la vez.

    Es lo que permite que 'Leer el guion' y 'Escribir la guia de estilo' corran
    en paralelo -- no dependen la una de la otra -- y que 'Generar los planos'
    espere a las dos.
    """
    orden = orden_de(pestana, incluidas)
    disponibles = {t["id"] for t in orden}
    nivel = {}
    for tarea in orden:
        previos = [nivel[d] for d in tarea["necesita"]
                   if d in disponibles and d in nivel]
        nivel[tarea["id"]] = (max(previos) + 1) if previos else 0
    tandas = []
    for tarea in orden:
        indice = nivel[tarea["id"]]
        while len(tandas) <= indice:
            tandas.append([])
        tandas[indice].append(tarea)
    return tandas


# ===========================================================================
# EL ALMACEN
# ===========================================================================

def _vacio():
    return {"recetas": [], "por_defecto": {}}


def leer():
    with _LOCK:
        try:
            with open(FICHERO, "r", encoding="utf-8-sig") as fh:
                datos = json.load(fh)
        except (OSError, ValueError):
            return _vacio()
        if not isinstance(datos, dict):
            return _vacio()
        base = _vacio()
        base["recetas"] = [r for r in (datos.get("recetas") or [])
                           if isinstance(r, dict) and r.get("id")]
        defecto = datos.get("por_defecto")
        base["por_defecto"] = {k: str(v) for k, v in (defecto or {}).items()
                               if isinstance(defecto, dict)}
        return base


def _escribir(datos):
    os.makedirs(os.path.dirname(FICHERO) or ".", exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=os.path.dirname(FICHERO) or ".",
                prefix=".recetas-", suffix=".tmp", delete=False) as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
            temporal = fh.name
        os.replace(temporal, FICHERO)
        temporal = None
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def listar(pestana=None):
    recetas = leer()["recetas"]
    if pestana:
        recetas = [r for r in recetas if r.get("pestana") == str(pestana)]
    return recetas


def obtener(rid):
    for receta in leer()["recetas"]:
        if receta["id"] == str(rid):
            return receta
    return None


def _nuevo_id(ocupados):
    indice = 1
    while f"rc{indice}" in ocupados:
        indice += 1
    return f"rc{indice}"


def guardar(peticion):
    """Crea o sobreescribe una receta. Devuelve la ficha guardada."""
    if not isinstance(peticion, dict):
        raise ErrorReceta("se esperaba un objeto con la receta")
    pestana = str(peticion.get("pestana") or "").strip()
    if pestana not in PESTANAS:
        raise ErrorReceta(f"pestana desconocida: {pestana!r}. Son "
                          + ", ".join(PESTANAS))
    nombre = str(peticion.get("nombre") or "").strip()
    if not nombre:
        raise ErrorReceta("una receta sin nombre no se puede elegir despues")

    validas = {t["id"] for t in tareas_de(pestana)}
    tareas = {}
    for tid, puesta in (peticion.get("tareas") or {}).items():
        if tid not in validas:
            raise ErrorReceta(f"la tarea '{tid}' no es de la pestana {pestana}")
        tareas[tid] = bool(puesta)
    # Lo no opcional va siempre, se diga lo que se diga: una receta que se salta
    # 'generar los planos' no es una receta de video. Y lo que no venga se
    # escribe con su valor por defecto: una receta guardada tiene que decir lo
    # que hace ENTERA, no una parte y el resto adivinado al leerla.
    for tarea in tareas_de(pestana):
        if not tarea["opcional"]:
            tareas[tarea["id"]] = True
        else:
            tareas.setdefault(tarea["id"], True)

    ajustes = {}
    for fase, ficha in (peticion.get("ajustes") or {}).items():
        if not isinstance(ficha, dict):
            raise ErrorReceta(f"el ajuste de '{fase}' tiene que ser un objeto "
                              f"{{modelo, esfuerzo}}")
        ajustes[str(fase)] = {
            "modelo": str(ficha.get("modelo") or "").strip(),
            "esfuerzo": str(ficha.get("esfuerzo") or "").strip(),
        }

    with _LOCK:
        datos = leer()
        ocupados = {r["id"] for r in datos["recetas"]}
        rid = str(peticion.get("id") or "").strip()
        ficha = {"id": rid or _nuevo_id(ocupados), "pestana": pestana,
                 "nombre": nombre, "nota": str(peticion.get("nota") or "").strip(),
                 "tareas": tareas, "ajustes": ajustes}
        if rid and rid in ocupados:
            datos["recetas"] = [ficha if r["id"] == rid else r
                                for r in datos["recetas"]]
        else:
            datos["recetas"].append(ficha)
        if peticion.get("por_defecto"):
            datos["por_defecto"][pestana] = ficha["id"]
        _escribir(datos)
        return ficha


def borrar(rid):
    with _LOCK:
        datos = leer()
        quedan = [r for r in datos["recetas"] if r["id"] != str(rid)]
        if len(quedan) == len(datos["recetas"]):
            raise ErrorReceta(f"no hay ninguna receta '{rid}'")
        datos["recetas"] = quedan
        datos["por_defecto"] = {k: v for k, v in datos["por_defecto"].items()
                                if v != str(rid)}
        _escribir(datos)
        return True


def receta_puesta(pestana):
    """La receta por defecto de una pestana, o None."""
    datos = leer()
    rid = datos["por_defecto"].get(str(pestana))
    if not rid:
        return None
    for receta in datos["recetas"]:
        if receta["id"] == rid:
            return receta
    return None


def puestas_de(pestana, receta):
    """Que tareas de esta pestana corren con esta receta. -> [ids] en su orden

    EXISTE PARA QUE LA PANTALLA Y LA TANDA DIGAN LO MISMO, y no lo decian: la
    pantalla leia `receta["tareas"].get(tid, True)` --lo que no esta, puesto--
    y quien lanzaba recorria `receta["tareas"].items()` quedandose con las
    verdaderas, o sea que **lo que no estaba no corria**. Con una receta
    guardada antes de que existiera una tarea, o traida de otra version del
    software, la pantalla ensenaba «Direccion de cada plano» encendida y la
    tanda no la hacia. No fallaba nada; salia un video con menos.

    Lo que no esta en la receta vale lo que diga su `de_fabrica`, que es la otra
    mitad de la promesa: una tarea nueva que cambia lo que cuesta cada imagen no
    puede encenderse sola en un video ya generado (ver `de_fabrica`).
    """
    tareas = (receta or {}).get("tareas") or {}
    salida = []
    for ficha in tareas_de(pestana):
        tid = ficha["id"]
        if tid in tareas:
            if tareas[tid]:
                salida.append(tid)
        elif ficha.get("de_fabrica", True):
            salida.append(tid)
    return salida


def de_fabrica(pestana):
    """La receta que se usa sin ninguna guardada.

    Todo lo opcional puesto MENOS lo que se declare `de_fabrica: False`. Ese
    campo existe por un caso concreto y caro: una tarea nueva que cambia lo que
    cuesta cada imagen no puede encenderse sola en un video que ya esta
    generado. La primera vez que alguien pulsara «Generar lo que falta» se
    encontraria el video entero regenerado y la factura pagada, sin haber
    elegido nada. Encenderla es un clic; apagarla despues es 1,6 $.
    """
    return {"id": "", "pestana": pestana, "nombre": "Todo",
            "nota": "sin receta guardada: se hace todo lo que la pestana sabe hacer",
            "tareas": {t["id"]: bool(t.get("de_fabrica", True))
                       for t in tareas_de(pestana)},
            "ajustes": {}}


def resolver(pestana, rid=None, tareas=None):
    """La receta con la que se va a ejecutar, mezclando lo pedido y lo guardado.

    Prioridad: lo que manda quien lanza > la receta pedida > la puesta por
    defecto > todo. Lo no opcional se fuerza siempre.
    """
    base = (obtener(rid) if rid else None) or receta_puesta(pestana) \
        or de_fabrica(pestana)
    if base.get("pestana") and base["pestana"] != pestana:
        raise ErrorReceta(f"la receta '{base['id']}' es de la pestana "
                          f"'{base['pestana']}', no de '{pestana}'")
    puestas = dict(base.get("tareas") or {})
    for tid, valor in (tareas or {}).items():
        if tid in TAREAS_POR_ID:
            puestas[tid] = bool(valor)
    for tarea in tareas_de(pestana):
        # una receta GUARDADA antes de que existiera esta tarea no la nombra:
        # ahi manda su defecto de fabrica, no un «True» generico
        puestas.setdefault(tarea["id"], bool(tarea.get("de_fabrica", True)))
        if not tarea["opcional"]:
            puestas[tarea["id"]] = True
    return dict(base, tareas=puestas)


def catalogo():
    """Lo que la pantalla necesita para pintar las recetas. Sin secretos."""
    return {
        "pestanas": [
            {"id": pestana,
             "tareas": [dict({k: t.get(k) for k in
                              ("id", "nombre", "paso", "necesita", "cuesta",
                               "opcional", "fase", "porque", "familia")},
                             de_fabrica=bool(t.get("de_fabrica", True)),
                             publico=publico_de(t["id"]))
                        for t in tareas_de(pestana)],
             "tandas": [[t["id"] for t in tanda] for tanda in tandas_de(pestana)]}
            for pestana in PESTANAS],
        "familias": FAMILIAS,
        "recetas": listar(),
        "por_defecto": leer()["por_defecto"],
    }
