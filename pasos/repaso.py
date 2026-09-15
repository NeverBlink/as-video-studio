"""EL REPASO: lo que se escribe MIRANDO el vídeo, y cómo se convierte en cambios.

QUE ES
------
El último paso del sistema y el primero que existe para una persona. Con el MP4
delante se pausa, se escribe una frase --y si hace falta se arrastra una imagen
de referencia-- y esa nota se queda anclada AL SEGUNDO en el que se escribió.
Después, un botón: aplicar y volver a generar.

Todo lo anterior del Estudio decide ANTES de ver el resultado. Esto es lo
contrario, y por eso tiene reglas propias.

LAS TRES DECISIONES QUE LO GOBIERNAN
------------------------------------

1 · UNA NOTA ES UN REGISTRO, NO UNA ENTRADA DEL PASO.
    Vive en `<proyecto>/repaso.json` y NO en los params. Escribir «la música
    está alta en 0:45» no puede dejar el render obsoleto: el vídeo no cambia
    porque alguien lo comente. Es la misma lección que ya costó una ronda con
    `notas_del_montaje.json` -- una nota en los params pintaba el vídeo de
    naranja como si volver a renderizarlo fuera a arreglar la música.

    Lo que SÍ toca las firmas es APLICAR, y eso es un gesto aparte y con su
    coste delante.

2 · EL SEGUNDO ES EL ANCLA, Y DE AHÍ SALE TODO LO DEMÁS.
    Del instante se deducen el plano que estaba en pantalla, su bloque de guion,
    su cartela si la lleva, su transición de entrada y la de salida, sus
    subtítulos y qué sonaba. Una nota no dice «el plano S031»: dice «aquí», y
    «aquí» se resuelve contra los cortes con los que se montó ESE MP4
    (`p8_render.reproductor`), no contra el plan de ahora -- que puede haber
    cambiado.

3 · APLICAR AHORRA, Y ESO NO ES UNA OPTIMIZACIÓN: ES EL DISEÑO.
    Cada nota se enruta a un ÁMBITO, y cada ámbito sabe exactamente qué hay que
    rehacer. Bajar la música es remuxear (segundos, cero dólares); cambiar el
    texto de una cartela es redibujar una capa; sólo tocar la IMAGEN de un plano
    cuesta una imagen. Un sistema que ante cualquier nota regenerara el vídeo
    entero convertiría el repaso en algo que nadie usa dos veces.

EL VOCABULARIO CERRADO DE CAMBIOS
---------------------------------
El enrutador es un agente, así que **no escribe código ni params libres**:
elige entre los cambios de `CAMBIOS`, que son datos validados por este módulo.
Un cambio que no está en la tabla no se aplica -- se queda como nota y se dice.

Es la misma disciplina que el resto del Estudio: alguien propone, el código
valida, y a partir de ahí es determinista.
"""
import copy
import json
import os
import re
import unicodedata
import time

try:
    from . import cli_claude, comun, estadisticas, subtitulos
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas
    import subtitulos

PASO = "repaso"

MODELO_POR_DEFECTO = cli_claude.por_defecto_de("repaso")["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de("repaso")["esfuerzo"]
TIEMPO_BASE_S = 480

FICHERO = "repaso.json"
CARPETA_IMAGENES = "repaso"

#: Cuántas imágenes de referencia caben en una nota. Más de cuatro y deja de ser
#: «mira esto» para ser un moodboard, que es otra cosa y tiene su sitio.
MAX_IMAGENES = 4

#: Lo que puede ocupar una nota. No es una limitación técnica: una nota de mil
#: palabras es un brief, y un brief se escribe en el encargo.
MAX_TEXTO = 1200

HERRAMIENTAS_VETADAS = ("Bash", "Write", "Edit", "NotebookEdit", "Grep",
                        "WebFetch", "WebSearch", "Task", "TodoWrite")
#: `Read` sí: las notas pueden traer imágenes de referencia, y una referencia
#: visual que nadie abre es una referencia que no está.
HERRAMIENTAS_PERMITIDAS = ("Read",)

SISTEMA = ("Si alguna nota trae imágenes de referencia, ábrelas con Read antes "
           "de decidir. Responde después exclusivamente con el objeto JSON "
           "pedido, sin texto alrededor y sin vallas de markdown.")


# ===========================================================================
# LOS ÁMBITOS
#
# Un ámbito es «de qué parte del vídeo habla esta nota», y lo que lo hace útil
# no es la etiqueta: es la TERCERA columna, qué hay que rehacer. Ahí es donde
# vive el ahorro.
# ===========================================================================

#: DONDE SE ARREGLA CADA COSA. Un ambito vetado no se traga: se devuelve con
#: esta frase, porque «aqui no» sin un «y alli si» deja a quien escribio la nota
#: sin saber que hacer con ella.
DONDE_SE_ARREGLA = {
    "imagen": "El dibujo de un plano se cambia en Imagenes, plano a plano.",
    "guion": "Lo que se DICE se reescribe en Guion, en su bloque.",
    "voz": "Como se dice -- ritmo, pausas, entonacion -- se cambia en Guion.",
}

AMBITOS = {
    "imagen": {
        "que_es": "lo que se ve dibujado en el plano: qué hay, quién sale, "
                  "qué hace, dónde ocurre",
        "cuesta": "una imagen por plano tocado",
    },
    "cartela": {
        "que_es": "el texto que se escribe encima del plano (la cabecera, la "
                  "cifra, la lista, la firma del cierre)",
        "cuesta": "nada: se redibuja la capa",
    },
    "subtitulo": {
        "que_es": "la narración escrita abajo: cuándo entra, cómo se parte, de "
                  "qué tamaño",
        "cuesta": "nada: se recalcula",
    },
    "transicion": {
        "que_es": "el efecto entre dos planos, o su duración",
        "cuesta": "nada: se vuelven a cocer los clips",
    },
    "musica": {
        "que_es": "la cama sonora: cuánta hay, qué tema es",
        "cuesta": "nada: se vuelve a mezclar el audio sobre los clips que hay",
        # SOLO LA MEZCLA. Ver AMBITOS_SOLO_MEZCLA: esto no es un texto, se lee.
        "solo_mezcla": True,
    },
    "efectos": {
        "que_es": "los golpes de transición y la máquina de escribir",
        "cuesta": "nada: se vuelve a mezclar",
        "solo_mezcla": True,
    },
    "guion": {
        "que_es": "lo que se dice: el texto de un bloque de la narración",
        "cuesta": "la locución de esa sección, y todo lo que cuelga de ella",
    },
    "voz": {
        "que_es": "cómo se dice: el ritmo, las pausas, la entonación",
        "cuesta": "la locución de esa sección",
    },
    "nota": {
        "que_es": "algo que no se puede aplicar solo y hay que decidir a mano",
        "cuesta": "nada: se queda escrito",
    },
}


# ===========================================================================
# EL VOCABULARIO DE CAMBIOS
#
#   ambito     de qué habla
#   destino    dónde se escribe: 'params:<paso>', 'unidad:<paso>', 'registro'
#   rehacer    qué tareas de la receta quedan sucias. ES LA COLUMNA QUE AHORRA.
#   valida     cómo se comprueba lo que llegue
# ===========================================================================

def _num(valor, minimo, maximo):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if minimo <= numero <= maximo else None


def _texto(valor, tope=600):
    limpio = " ".join(str(valor or "").split())
    return limpio[:tope] or None


def _plano(valor):
    limpio = str(valor or "").strip().upper()
    return limpio if re.fullmatch(r"S\d{3,4}", limpio) else None


def _bloque(valor):
    limpio = str(valor or "").strip().upper()
    return limpio if re.fullmatch(r"B\d{3,4}", limpio) else None


#: LOS DOS ALCANCES DE UNA CORRECCION DE IMAGEN, y la diferencia decide si al
#: generador se le adjunta la imagen RECHAZADA:
#:
#:   retoque     «cámbiale la mano por un guante», «quita el cartel del fondo».
#:               Lo demás del plano se queda: con la imagen delante, la
#:               composición no deriva.
#:   sustituye   «esto tenía que ser un móvil, no un monolito». Adjuntarla sería
#:               contraproducente: en una llamada de images/edits, una imagen se
#:               lee como «edita esto», y el monolito volvía a salir.
#:
#: Es la clasificación que `p6_assets._bloque_feedback` dice que NO intenta
#: hacer, y con razón: ahí sólo se ve el texto de la nota. El enrutador SÍ ve la
#: nota, el plano, su narración y las imágenes adjuntas, así que la hace él.
ALCANCES = ("retoque", "sustituye")

#: Y EL DEFECTO ES `sustituye`, que es no adjuntar nada: si el enrutador no lo
#: dice o dice cualquier otra cosa, el plano se rehace EXACTAMENTE como se
#: rehacía hasta el 28-08-2026. Un campo obligatorio aquí descartaría el cambio
#: entero -- y perder una corrección por una etiqueta es peor que no adjuntar.
def _alcance(valor):
    limpio = str(valor or "").strip().lower()
    return limpio if limpio in ALCANCES else "sustituye"


#: LOS VALORES QUE DE VERDAD LEE `p7_callouts`. No se escriben a mano aquí: se
#: piden al módulo, porque un cambio que escribe en un param que nadie lee es la
#: peor clase de fallo de este repo -- no da error, deja el vídeo igual y la
#: nota marcada como aplicada.
def _tamano_subtitulo(valor):
    nombre = str(valor or "").strip().lower()
    if nombre in ("pequeno", "pequeño", "normal", "grande", "enorme"):
        return nombre.replace("ñ", "n")
    return _num(valor, 20, 80)


def _set_de_diseno(valor):
    try:
        from . import p7_callouts                             # noqa: PLC0415
    except ImportError:                                       # pragma: no cover
        import p7_callouts                                    # noqa: PLC0415
    nombre = str(valor or "").strip().lower()
    return nombre if nombre in p7_callouts.SETS_DISENO else None


CAMBIOS = {
    # ---------------------------------------------------------------- imagen
    "feedback_plano": {
        "ambito": "imagen",
        "que_es": "vuelve a dibujar ESE plano con la nota delante. `alcance` es "
                  "«retoque» si el cambio es LOCALIZADO (se cambia una cosa y "
                  "el resto del plano se queda igual) o «sustituye» si lo que "
                  "hay que dibujar es otra cosa",
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano, "texto": lambda v: _texto(v, 600),
                   "alcance": _alcance},
    },
    "feedback_asset": {
        "ambito": "imagen",
        "que_es": "vuelve a dibujar una hoja de personaje o una pieza",
        "rehacer": ["piezas", "assets", "callouts", "render"],
        "campos": {"asset": lambda v: _texto(v, 80),
                   "texto": lambda v: _texto(v, 600)},
    },
    # --------------------------------------------------------------- cartela
    "cartela_texto": {
        "ambito": "cartela",
        "que_es": "cambia lo que dice la cartela de ese plano",
        # `assets` entra en la lista y NO cuesta: un plano que es cartela cae en
        # `_sin_imagen`, asi que se vuelve a planificar sin pagar ninguna
        # imagen. Dejarlo fuera lo dejaria marcado como obsoleto para siempre.
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano,
                   "campos_cartela": lambda v: v if isinstance(v, dict) and v else None},
    },
    "quitar_cartela": {
        "ambito": "cartela",
        "que_es": "ese plano deja de llevar cartela",
        # quitar una cartela devuelve la imagen a ese plano, asi que hay que
        # volver a pasar por assets: sin ella el plano SI se dibuja
        "rehacer": ["assets", "callouts", "render"],
        "campos": {"plano": _plano},
    },
    # ------------------------------------------------------------- subtitulo
    "subtitulo_tam": {
        "ambito": "subtitulo",
        "que_es": "el tamaño del subtítulo: pequeno, normal, grande o enorme",
        "rehacer": ["callouts", "render"],
        "campos": {"valor": _tamano_subtitulo},
    },
    "grafismo": {
        "ambito": "subtitulo",
        "que_es": "el set de estilo con el que se dibuja el texto encima del "
                  "vídeo: dibujo, realista o editorial",
        "rehacer": ["callouts", "render"],
        "campos": {"valor": _set_de_diseno},
    },
    "subtitulo_texto": {
        "ambito": "subtitulo",
        "que_es": "corrige lo que DICE el subtítulo de ese plano, sin tocar la "
                  "voz: se escribe el texto entero del plano, ya corregido",
        # NI VOZ NI IMAGENES. Esto es lo que lo justifica: hasta el 28-08-2026
        # lo más cercano para cambiar una palabra escrita era `bloque_texto`,
        # que reescribe el guion y regenera voz, corte, assets, cartelas y
        # montaje. Para arreglar «un uno por 100» eso es absurdo.
        "rehacer": ["callouts", "render"],
        "campos": {"plano": _plano, "texto": lambda v: _texto(v, 300)},
    },
    # ------------------------------------------------------------ transicion
    "transicion_duracion": {
        "ambito": "transicion",
        "que_es": "lo que dura una transición, en segundos",
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, 0.1, 1.2)},
    },
    "transiciones": {
        "ambito": "transicion",
        "que_es": "qué efectos de transición entran en este vídeo",
        "rehacer": ["render"],
        "campos": {"lista": lambda v: [str(x) for x in v][:14]
                   if isinstance(v, list) and v else None},
    },
    # ---------------------------------------------------------------- musica
    "musica_db": {
        "ambito": "musica",
        "que_es": "sube o baja la música, en decibelios",
        # SOLO REMUXEAR: es el caso que mas se pide y el mas barato de todos.
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, -12, 6)},
    },
    "sin_musica": {
        "ambito": "musica",
        "que_es": "este vídeo se queda sin cama sonora",
        "rehacer": ["render"],
        "campos": {},
    },
    "otra_musica": {
        "ambito": "musica",
        "que_es": "busca otro tema para la cama",
        "rehacer": ["banda_sonora", "render"],
        "campos": {"animo": lambda v: _texto(v, 60)},
    },
    # --------------------------------------------------------------- efectos
    "efectos_db": {
        "ambito": "efectos",
        "que_es": "sube o baja los golpes y la máquina de escribir, en decibelios",
        # SOLO REMUXEAR, igual que `musica_db`: la pista de efectos ya esta
        # montada y esto es un volumen sobre ella.
        "rehacer": ["render"],
        "campos": {"valor": lambda v: _num(v, -12, 6)},
    },
    "sin_efectos": {
        "ambito": "efectos",
        "que_es": "se quitan los golpes y la máquina de escribir",
        "rehacer": ["render"],
        "campos": {},
    },
    "otros_efectos": {
        "ambito": "efectos",
        "que_es": "vuelve a surtir los efectos del banco",
        "rehacer": ["efectos", "render"],
        "campos": {},
    },
    # ----------------------------------------------------------------- guion
    "bloque_texto": {
        "ambito": "guion",
        "que_es": "reescribe lo que se dice en ese bloque",
        "rehacer": ["voz", "revision_audio", "corte", "assets", "callouts",
                    "render"],
        "campos": {"bloque": _bloque, "texto": lambda v: _texto(v, 900)},
    },
    # ------------------------------------------------------------------ voz
    "velocidad": {
        "ambito": "voz",
        "que_es": "cómo de rápido habla el locutor",
        "rehacer": ["voz", "revision_audio", "corte", "assets", "callouts",
                    "render"],
        "campos": {"valor": lambda v: _num(v, 0.6, 1.5)},
    },
    # ------------------------------------------------------------------ nota
    "anotar": {
        "ambito": "nota",
        "que_es": "no se puede aplicar solo: se deja escrito para decidirlo",
        "rehacer": [],
        "campos": {"texto": lambda v: _texto(v, 600)},
    },
}


#: DONDE ESCRIBE CADA CAMBIO. Es una tabla y no un comentario porque la suite
#: la recorre: cada destino tiene que ser un param que ALGUIEN LEA. «Media pieza
#: escrita no da error» ya costó un vídeo entero en este repo -- se elegía un
#: ajuste, se guardaba y no lo leía nadie --, y un repaso que escribe en un
#: cajón muerto es exactamente lo mismo: la nota se marca como aplicada y el
#: vídeo sale igual.
DESTINOS = {
    "feedback_plano": ("assets", "unidades.escena:*.feedback"),
    "feedback_asset": ("assets", "unidades.asset:*.feedback"),
    "cartela_texto": ("assets", "unidades.escena:*.cartela"),
    "quitar_cartela": ("assets", "unidades.escena:*.cartela"),
    "subtitulo_tam": ("callouts", "subtitulo_tam"),
    "grafismo": ("callouts", "diseno"),
    "subtitulo_texto": ("callouts", "unidades.escena:*.subtitulo_texto"),
    "transicion_duracion": ("render", "duracion_transicion"),
    "transiciones": ("render", "transiciones"),
    "musica_db": ("render", "musica_db"),
    "efectos_db": ("render", "efectos_db"),
    "sin_musica": ("render", "musica"),
    "otra_musica": ("render", "musica"),
    "sin_efectos": ("render", "efectos"),
    "otros_efectos": ("render", "efectos"),
    "bloque_texto": ("guion", "bloques"),
    "velocidad": ("brief", "velocidad"),
    "anotar": ("", ""),
}


def catalogo():
    """Los ámbitos y los cambios, para la pantalla y para la instrucción."""
    return {
        "ambitos": {k: dict(v) for k, v in AMBITOS.items()},
        "cambios": {k: {"ambito": v["ambito"], "que_es": v["que_es"],
                        "rehacer": list(v["rehacer"]),
                        "campos": sorted(v["campos"]),
                        "destino": list(DESTINOS.get(k) or ("", ""))}
                    for k, v in CAMBIOS.items()},
    }


def validar_cambio(crudo):
    """Un cambio propuesto, validado. -> (cambio, motivo del descarte)"""
    if not isinstance(crudo, dict):
        return None, "no es un objeto"
    tipo = str(crudo.get("tipo") or "").strip()
    ficha = CAMBIOS.get(tipo)
    if not ficha:
        return None, f"«{tipo}» no está en el vocabulario de cambios"
    limpio = {"tipo": tipo, "ambito": ficha["ambito"]}
    for campo, valida in ficha["campos"].items():
        valor = valida(crudo.get(campo))
        if valor is None:
            return None, f"«{tipo}» necesita un {campo} válido"
        limpio[campo] = valor
    limpio["rehacer"] = list(ficha["rehacer"])
    return limpio, ""


# ===========================================================================
# LAS NOTAS
# ===========================================================================

def ruta_fichero(proyecto):
    return proyecto.ruta(FICHERO)


def carpeta_imagenes(proyecto, crear=False):
    ruta = proyecto.ruta(CARPETA_IMAGENES)
    if crear:
        os.makedirs(ruta, exist_ok=True)
    return ruta


def leer(proyecto):
    """Las notas del repaso, en orden de vídeo. Nunca levanta."""
    try:
        with open(ruta_fichero(proyecto), "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        datos = {}
    notas = [n for n in (datos.get("notas") or []) if isinstance(n, dict)]
    notas.sort(key=lambda n: float(n.get("t") or 0.0))
    return {"notas": notas, "aplicado": datos.get("aplicado") or [],
            "version_mp4": datos.get("version_mp4")}


def guardar(proyecto, ficha):
    comun.escribir_json(ruta_fichero(proyecto), ficha)
    return ficha


def _siguiente_id(notas):
    numeros = []
    for nota in notas:
        encaje = re.fullmatch(r"R(\d+)", str(nota.get("id") or ""))
        if encaje:
            numeros.append(int(encaje.group(1)))
    return f"R{(max(numeros) + 1) if numeros else 1:03d}"


#: De que pantalla es una nota. NO SON EL MISMO CUADERNO, aunque vivan en el
#: mismo fichero: en Imagenes se anota sobre el DIBUJO de un plano y cada nota
#: se acciona sola; en Video se anota sobre lo que se monta encima y sobre lo
#: que se oye, y se aplican juntas por el enrutador. Mezclarlas hacia que las
#: ocho notas de una salieran contadas en la otra.
#:
#: Por defecto 'video': las notas escritas antes de esta separacion son del
#: repaso del MP4, que es lo unico que habia.
PANTALLAS = ("video", "imagenes")


def anadir(proyecto, texto, t, plano="", imagenes=(), version_mp4=None,
           pantalla="video", ancla=""):
    """Una nota nueva, anclada a su segundo. El texto es OBLIGATORIO.

    La imagen es opcional y el texto no, y no es una asimetría caprichosa: una
    referencia visual sin una frase no dice qué hay que hacer con ella -- ¿es
    el estilo?, ¿la composición?, ¿el objeto? --, y adivinarlo es exactamente
    como se acaba regenerando lo que no había que tocar.
    """
    limpio = " ".join(str(texto or "").split())[:MAX_TEXTO]
    if not limpio:
        raise ValueError("una nota del repaso necesita texto: una imagen sola "
                         "no dice qué hay que hacer con ella")
    ficha = leer(proyecto)
    nota = {
        "id": _siguiente_id(ficha["notas"]),
        "t": round(max(0.0, float(t or 0.0)), 3),
        "plano": str(plano or ""),
        "texto": limpio,
        "imagenes": [str(i) for i in (imagenes or [])][:MAX_IMAGENES],
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "estado": "pendiente",
        "pantalla": (str(pantalla) if pantalla in PANTALLAS else "video"),
        # LO QUE HABIA EN PANTALLA CUANDO SE ESCRIBIO. Es el seguro contra que
        # los planos se renumeren: ver `reanclar`.
        "ancla": " ".join(str(ancla or "").split())[:MAX_TEXTO],
    }
    ficha["notas"].append(nota)
    if version_mp4 is not None:
        ficha["version_mp4"] = version_mp4
    guardar(proyecto, ficha)
    return nota


def editar(proyecto, nid, texto=None, t=None, imagenes=None,
           regenerado=None):
    ficha = leer(proyecto)
    for nota in ficha["notas"]:
        if nota.get("id") != nid:
            continue
        if texto is not None:
            limpio = " ".join(str(texto).split())[:MAX_TEXTO]
            if not limpio:
                raise ValueError("una nota del repaso necesita texto")
            nota["texto"] = limpio
        if t is not None:
            nota["t"] = round(max(0.0, float(t)), 3)
        if imagenes is not None:
            nota["imagenes"] = [str(i) for i in imagenes][:MAX_IMAGENES]
        # CONTRA QUE TEXTO SE REDIBUJO. No un si o un no: si fuera un booleano,
        # cambiar la nota dejaria el «Regenerada ✓» puesto sobre una peticion
        # que nadie ha atendido todavia. Guardando el texto, editar la nota
        # devuelve el boton a «Regenerar imagen» ella sola.
        if regenerado is not None:
            nota["regenerado"] = " ".join(str(regenerado).split())[:MAX_TEXTO]
        # UNA NOTA CUYA IMAGEN YA SE REHIZO ESTA RESUELTA, y por eso deja de
        # contar en «Aplicar N cambios»: rehacer su plano ES aplicarla. Se
        # seguia contando como pendiente, asi que el boton pedia aplicar cosas
        # que ya estaban hechas -- y aplicarlas otra vez cuesta dinero.
        #
        # Y es lo mismo que ya decia la linea de abajo, solo que mirando el
        # dato entero: editada es pendiente otra vez PORQUE el texto nuevo ya
        # no es el que se dibujo.
        nota["estado"] = ("aplicado"
                          if nota.get("regenerado")
                          and nota.get("regenerado") == nota.get("texto")
                          else "pendiente")
        guardar(proyecto, ficha)
        return nota
    raise KeyError(nid)


def borrar(proyecto, nid):
    ficha = leer(proyecto)
    antes = len(ficha["notas"])
    ficha["notas"] = [n for n in ficha["notas"] if n.get("id") != nid]
    if len(ficha["notas"]) == antes:
        raise KeyError(nid)
    guardar(proyecto, ficha)
    return len(ficha["notas"])


def _palabras(texto):
    """El texto reducido a palabras comparables: sin tildes ni puntuacion."""
    limpio = unicodedata.normalize("NFD", str(texto or "").lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    return [p for p in re.sub(r"[^a-z0-9 ]", " ", limpio).split() if p]


def _parecido(a, b):
    """Cuanto de `a` aparece en `b`, de 0 a 1."""
    if not a:
        return 0.0
    otras = set(b)
    return sum(1 for p in a if p in otras) / len(a)


#: Cuanto tiene que coincidir para dar por buena una escena. Alto a proposito:
#: re-anclar mal es peor que no re-anclar -- una nota que apunta al plano
#: equivocado hace rehacer el que estaba bien y deja el malo como estaba.
PARECIDO_MINIMO = 0.7


def _mismo_dicho(unas, otras):
    """Si dos listas de palabras son lo mismo dicho, aunque el corte las moviera.

    Tres varas, de la mas dura a la mas blanda:

      1. las mismas palabras;
      2. unas DENTRO de las otras -- eso no es el guion cambiando, es el corte:
         un plano que se parte en dos sigue diciendo las mismas palabras, solo
         que menos de ellas;
      3. y si no, cuanto se parecen.

    La 2 es la que faltaba. Sin ella, al partir un plano la nota se quedaba
    huerfana: su ancla decia «...de la gente sin tocar su cuenta y sin que nadie
    lo note» y el plano paso a decir «...de la gente». Se parecen 0,615 --por
    debajo del minimo-- y aun asi es exactamente el mismo plano. Es la misma
    regla que `p6_assets._mismo_dicho` usa para las imagenes, y por lo mismo.
    """
    if unas == otras:
        return True
    if not unas or not otras:
        return False
    una, otra = " ".join(unas), " ".join(otras)
    if una in otra or otra in una:
        return True
    return _parecido(unas, otras) >= PARECIDO_MINIMO


def reanclar(notas, escenas):
    """Devuelve las notas con su plano puesto al dia. -> [notas]

    POR QUE EXISTE. Una nota se ancla al plano que estabas mirando, y el numero
    de un plano NO ES ESTABLE: al regrabar la voz cambian los tiempos de las
    palabras, la segmentacion vuelve a cortar y lo que era S005 pasa a ser S004.
    Paso el 31-08-2026: tres notas escritas a las 18:39 apuntaban, tras el audio
    nuevo de las 19:01, al plano de al lado. La nota seguia ahi y el plano que
    señalaba ya no era el suyo, asi que aplicarla habria rehecho el que estaba
    bien.

    COMO. Cada nota guarda el TEXTO que se decia en ese plano (`ancla`). Si el
    plano que dice sigue diciendo eso, no se toca nada. Si no, se busca el que
    lo diga; y si ninguno se le parece lo bastante, se marca `descolgada` en vez
    de dejarla apuntando a cualquier sitio. Una nota huerfana que lo dice se
    arregla a mano; una que apunta mal, no se ve venir.

    Las notas viejas no tienen `ancla` y se quedan como estan: sin saber contra
    que se escribieron, moverlas seria adivinar.
    """
    por_id = {e.get("id"): e for e in (escenas or []) if e.get("id")}
    palabras = {sid: _palabras(e.get("narracion"))
               for sid, e in por_id.items()}
    salida = []
    for nota in (notas or []):
        ficha = dict(nota)
        ancla = _palabras(ficha.get("ancla"))
        sid = ficha.get("plano") or ""
        if not ancla or not por_id:
            salida.append(ficha)
            continue
        if sid in palabras and _mismo_dicho(ancla, palabras[sid]):
            salida.append(ficha)
            continue
        # EL MEJOR DE LOS QUE VALEN, no el mejor a secas: se puntua entre los
        # que ya pasan la vara, para que un parecido flojo no gane a uno que
        # dice literalmente lo mismo pero mas corto.
        mejor, punto = "", 0.0
        for otro, pal in palabras.items():
            if not _mismo_dicho(ancla, pal):
                continue
            p = _parecido(ancla, pal)
            if p > punto:
                mejor, punto = otro, p
        if mejor:
            ficha["plano"] = mejor
            ficha["t"] = round(float(por_id[mejor].get("t_in") or 0.0), 3)
            ficha["reanclada"] = sid or True
        else:
            ficha["descolgada"] = True
        salida.append(ficha)
    return salida


def pantalla_de(nota):
    """De que pantalla es una nota. Las de antes de la separacion, de video."""
    p = str((nota or {}).get("pantalla") or "")
    return p if p in PANTALLAS else "video"


def pendientes(proyecto, pantalla=None):
    """Las notas sin aplicar. Con `pantalla`, solo las de esa."""
    notas = [n for n in leer(proyecto)["notas"] if n.get("estado") != "aplicado"]
    if pantalla:
        notas = [n for n in notas if pantalla_de(n) == pantalla]
    return notas


# ===========================================================================
# DEL SEGUNDO AL CONTEXTO
# ===========================================================================

def plano_en(cortes, segundo):
    """Qué plano estaba en pantalla en ese instante. -> id o ""

    `cortes` es [{"id", "t_in", "t_out"}] con los tiempos del MP4 que se está
    viendo. Se busca por intervalo y no por índice: los planos no duran lo mismo.
    """
    segundo = float(segundo or 0.0)
    for corte in (cortes or []):
        try:
            if float(corte.get("t_in") or 0) <= segundo < float(corte.get("t_out") or 0):
                return str(corte.get("id") or "")
        except (TypeError, ValueError):
            continue
    return str((cortes or [{}])[-1].get("id") or "") if cortes else ""


def contexto_de_nota(nota, escenas_por_id, bloques_por_id, orden,
                     carpeta_escenas="", textos_subtitulo=None):
    """Todo lo que rodea a un instante: el plano, su bloque, sus vecinos.

    Es lo que se le da al enrutador para que no tenga que adivinar de qué habla
    «aquí». Sin esto, una nota como «esto se oye mal» no se puede colocar.

    Y con `carpeta_escenas` se añade LA IMAGEN DE ESE PLANO, para que el
    enrutador pueda abrirla: una nota como «esto no tiene sentido» sólo se puede
    repartir mirando lo que hay en pantalla. Es la misma idea que las
    referencias visuales que trae la nota, pero del lado del vídeo.

    Y EL SUBTÍTULO ESCRITO, que no es la narración: la narración va con las
    cifras en letra porque la locuta un sintetizador, y abajo se lee «1%». Una
    nota como «ahí pone otra cifra de la que se oye» no se puede repartir
    leyendo la narración -- ahí la cifra está bien. `textos_subtitulo` son los
    que ya se hayan corregido a mano ({plano: texto}), para que una segunda
    vuelta lea lo que se ve AHORA y no lo que se veía antes de corregir.
    """
    sid = str(nota.get("plano") or "")
    escena = escenas_por_id.get(sid) or {}
    bid = str((escena.get("origen") or {}).get("bloque") or "")
    indice = orden.index(sid) if sid in orden else -1
    anterior = orden[indice - 1] if indice > 0 else ""
    siguiente = orden[indice + 1] if 0 <= indice < len(orden) - 1 else ""
    imagen = ""
    if carpeta_escenas and sid:
        candidata = os.path.join(carpeta_escenas, f"{sid}.png")
        imagen = candidata if os.path.exists(candidata) else ""
    try:
        trozos = subtitulos.de_escena(
            escena, texto=(textos_subtitulo or {}).get(sid, ""))
    except Exception:                                          # noqa: BLE001
        trozos = []
    return {
        "plano": sid,
        "imagen": imagen,
        "subtitulo": " ".join(str(t.get("texto") or "") for t in trozos).strip(),
        "anterior": anterior,
        "siguiente": siguiente,
        "narracion": str(escena.get("narracion") or ""),
        "bloque": bid,
        "texto_bloque": str((bloques_por_id.get(bid) or {}).get("texto") or ""),
        "sitio": escena.get("set") or "",
        "personajes": list(escena.get("personajes") or []),
        "cartela": (escena.get("cartela") or {}).get("plantilla") or "",
    }


# ===========================================================================
# EL ENRUTADOR
# ===========================================================================

INSTRUCCION = """Eres quien recoge el repaso de un vídeo ya montado y lo
convierte en cambios concretos.

Alguien ha visto el vídeo «{titulo}», lo ha ido pausando y ha escrito notas. Tu
trabajo NO es opinar sobre el vídeo: es leer cada nota, entender de qué parte
habla, y elegir el cambio MÁS BARATO que la resuelve.

=====================================================================
POR QUÉ EL MÁS BARATO, Y NO EL MÁS COMPLETO
=====================================================================

Cada cambio arrastra un trabajo distinto:

  bajar la música          se vuelve a mezclar el audio          segundos, 0 $
  cambiar una cartela      se redibuja una capa                  segundos, 0 $
  tocar el movimiento      se recalcula y se recaptura el clip    minutos, 0 $
  rehacer una imagen       se paga una imagen nueva               minutos, $
  reescribir un bloque     se vuelve a grabar la voz de esa
                           sección, y con ella todo lo que
                           cuelga: el corte, los planos, el MP4   mucho, $$

Así que si una nota dice «no se entiende lo que dice aquí» y lo que pasa es que
la música tapa la voz, el cambio es la MÚSICA, no volver a grabar. Y si dice
«esta cartela pone otra cosa de la que se oye», el cambio es el TEXTO de la
cartela, no la imagen del plano.

Cuando de verdad no se pueda arreglar con ninguno de los cambios de la tabla,
usa `anotar`: se queda escrito para decidirlo a mano. Es una salida legítima y
mejor que forzar un cambio que no toca.

=====================================================================
EL VOCABULARIO. NO HAY NINGUNO MÁS
=====================================================================
{cambios}

=====================================================================
EL VÍDEO
=====================================================================
Duración: {duracion}
{estado}

EL GUION, BLOQUE A BLOQUE:
{guion}

=====================================================================
LAS NOTAS ({cuantas}), CADA UNA CON LO QUE HABÍA EN PANTALLA
=====================================================================
{notas}

=====================================================================
QUE DEVOLVER
=====================================================================

Devuelve SOLO este objeto JSON, con UNA entrada por nota y en el mismo orden:

{{"notas": [
  {{"id": "R001",
    "entendido": "qué pide esta nota, en una línea y con tus palabras",
    "ambito": "musica",
    "cambios": [
      {{"tipo": "musica_db", "valor": -3}}
    ]}}
]}}

Reglas de la respuesta:
  · `cambios` puede llevar más de uno si la nota pide dos cosas, y puede ir
    vacío si la nota no pide ninguna acción (una felicitación, una duda).
  · Los tipos y los campos son EXACTAMENTE los de la tabla. Un tipo inventado se
    descarta entero y la nota se queda sin aplicar.
  · `feedback_plano` y `feedback_asset` llevan su texto EN INGLÉS: va derecho al
    modelo de imagen. Di qué QUITAR y qué PONER, en una o dos frases; no
    describas el plano entero.
  · `feedback_plano` lleva además `alcance`, y esa etiqueta la decides TÚ porque
    eres el único que ve la nota, el plano y las imágenes a la vez:

      «retoque»     el cambio es LOCALIZADO y el resto del plano se queda como
                    está: «cámbiale la mano por un guante», «quita el cartel
                    del fondo», «esa cara mira a otro lado». Con esta etiqueta
                    al generador se le adjunta la imagen que se rechazó, y así
                    la composición no deriva.
      «sustituye»   lo que hay que dibujar ahí es OTRA COSA: «esto tenía que ser
                    un móvil, no un monolito». Aquí la imagen NO se adjunta: en
                    una llamada de edición, una imagen delante se lee como
                    «edita esto» y volvería a salir lo mismo con un cambio
                    pequeño. Ya pasó, y está medido.

    En la duda, «sustituye»: es como se rehacía un plano hasta ahora.
  · `bloque_texto` lleva el texto en el idioma del guion, con las cifras
    escritas con letras (lo locuta un sintetizador) y respetando las
    anotaciones de voz que ya tuviera.
  · `subtitulo_texto` es lo contrario y es el cambio BARATO: corrige lo que se
    LEE sin tocar lo que se oye. Se escribe el subtítulo ENTERO de ese plano ya
    corregido (te lo doy tal y como está ahora en «lo que se LEE abajo»), con
    las cifras como se escriben. Úsalo cuando la nota hable de una palabra o una
    cifra mal ESCRITA; si lo que está mal es lo que se DICE, eso es
    `bloque_texto` y cuesta volver a grabar la voz.
  · Si una nota se refiere a algo que se repite en todo el vídeo (la música, el
    tamaño del subtítulo, las transiciones), usa el cambio GLOBAL una sola vez,
    no uno por plano.
"""


def _notas_legibles(notas, contextos):
    piezas = []
    for nota in notas:
        contexto = contextos.get(nota["id"]) or {}
        trozos = [f"--- {nota['id']} · minuto {_reloj(nota.get('t'))} ---",
                  f"lo que escribió: {nota.get('texto')}"]
        if contexto.get("plano"):
            trozos.append(f"plano en pantalla: {contexto['plano']}")
        if contexto.get("narracion"):
            trozos.append(f"se estaba narrando: {contexto['narracion']}")
        if contexto.get("subtitulo"):
            # LO QUE SE LEE NO ES LO QUE SE DICE. La narración lleva las cifras
            # en letra (la locuta un sintetizador) y el subtítulo las escribe
            # con números: sin esta línea, una nota sobre lo escrito se
            # repartiría leyendo un texto que no está en pantalla.
            trozos.append(f"lo que se LEE abajo (el subtítulo, que no es igual "
                          f"que la narración): {contexto['subtitulo']}")
        if contexto.get("bloque"):
            trozos.append(f"bloque del guion: {contexto['bloque']}")
        if contexto.get("cartela"):
            trozos.append(f"lleva cartela: {contexto['cartela']}")
        if contexto.get("sitio") or contexto.get("personajes"):
            trozos.append(f"sitio: {contexto.get('sitio') or '-'} · sale: "
                          + (", ".join(contexto.get("personajes") or []) or "nadie"))
        if contexto.get("anterior") or contexto.get("siguiente"):
            trozos.append(f"planos de al lado: {contexto.get('anterior') or '-'}"
                          f" → {contexto.get('siguiente') or '-'}")
        if contexto.get("imagen"):
            trozos.append(f"lo que se ve en ese plano, ÁBRELO CON Read si la "
                          f"nota habla de la imagen: {contexto['imagen']}")
        for imagen in (nota.get("imagenes") or []):
            trozos.append(f"referencia que ha dejado quien escribe la nota "
                          f"(ábrela con Read): {imagen}")
        piezas.append("\n".join(trozos))
    return "\n\n".join(piezas)


def _reloj(segundos):
    try:
        total = int(float(segundos or 0))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60}:{total % 60:02d}"


def _cambios_legibles():
    lineas = []
    for tipo, ficha in CAMBIOS.items():
        campos = ", ".join(sorted(ficha["campos"])) or "sin campos"
        rehacer = ", ".join(ficha["rehacer"]) or "nada"
        lineas.append(f"  · {tipo} ({ficha['ambito']}) — {ficha['que_es']}. "
                      f"Campos: {campos}. Rehace: {rehacer}.")
    return "\n".join(lineas)


def enrutar(notas, contextos, guion_bloques, titulo="", duracion=0.0,
            estado="", ajuste=None, avisar=None, cwd=None, proyecto_id=None,
            rutas_imagenes=None, ambitos_vetados=()):
    """De las notas a los cambios, validados. -> {"notas": [...], "avisos": [...]}

    `ambitos_vetados` son los ambitos que ESTA pantalla no arregla. Se usa desde
    el repaso del video, que desde el 01-09 no toca ni un dibujo: lo que se ve
    mal en una imagen se corrige en la pantalla de Imagenes, donde se mira la
    imagen sola y se rehace una sola.

    SE VETA AQUI Y NO EN EL PROMPT. Pedirselo al agente es pedirlo; comprobarlo
    al validar es tenerlo. Ademas asi la nota no se pierde: se devuelve un aviso
    con su id diciendo donde se arregla, que es lo contrario de tragarsela.
    """
    avisar = avisar or (lambda *a, **k: None)
    notas = [n for n in (notas or []) if n.get("texto")]
    if not notas:
        return {"notas": [], "cambios": [], "avisos": ["no hay notas que aplicar"]}
    ajuste = dict(ajuste or {})
    modelo = cli_claude.normalizar_modelo(ajuste.get("modelo"),
                                          defecto=MODELO_POR_DEFECTO)
    esfuerzo = cli_claude.normalizar_esfuerzo(ajuste.get("esfuerzo"),
                                              defecto=ESFUERZO_POR_DEFECTO)
    # las rutas de las imagenes se resuelven ANTES: el agente las abre con Read
    for nota in notas:
        nota["imagenes"] = [(rutas_imagenes or {}).get(i, i)
                            for i in (nota.get("imagenes") or [])]
    instruccion = INSTRUCCION.format(
        titulo=titulo or "sin título",
        cambios=_cambios_legibles(),
        duracion=f"{_reloj(duracion)} ({duracion:.1f} s)" if duracion else "?",
        estado=estado or "",
        guion="\n".join(f"[{b.get('id')}] {b.get('texto')}"
                        for b in (guion_bloques or []))[:24000],
        cuantas=len(notas),
        notas=_notas_legibles(notas, contextos or {}))
    arranque = time.time()
    vetados = {str(a) for a in (ambitos_vetados or ())}
    avisar(0.1, f"leyendo {len(notas)} nota(s) del repaso")
    texto, _sobre = cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S, sistema=SISTEMA,
        herramientas_vetadas=HERRAMIENTAS_VETADAS,
        herramientas_permitidas=HERRAMIENTAS_PERMITIDAS,
        extra=["--no-session-persistence"],
        para="el reparto del repaso en cambios")
    datos = comun.extraer_json(texto, "la respuesta")
    salida, avisos = [], []
    por_id = {n["id"]: n for n in notas}
    for cruda in (datos.get("notas") or []):
        if not isinstance(cruda, dict):
            continue
        nid = str(cruda.get("id") or "")
        if nid not in por_id:
            continue
        cambios = []
        for propuesto in (cruda.get("cambios") or []):
            cambio, motivo = validar_cambio(propuesto)
            if cambio and cambio.get("ambito") in vetados:
                donde = DONDE_SE_ARREGLA.get(cambio["ambito"], "otra pantalla")
                avisos.append(f"{nid}: eso no se arregla aqui. {donde}")
                continue
            if cambio:
                # LAS IMAGENES DE LA NOTA VIAJAN CON EL CAMBIO. El enrutador las
                # abre para entender la nota, pero hasta el 28-08-2026 se
                # quedaban ahi: `feedback_plano` transportaba `plano` y `texto`
                # y nada mas, asi que la referencia que alguien habia arrastrado
                # para decir «como esto» no llegaba nunca a quien dibuja.
                if cambio["tipo"] in ("feedback_plano", "feedback_asset"):
                    cambio["imagenes"] = [str(i) for i in
                                          (por_id[nid].get("imagenes") or [])]
                cambios.append(cambio)
            elif motivo:
                avisos.append(f"{nid}: {motivo}")
        salida.append({
            "id": nid,
            "texto": por_id[nid]["texto"],
            "entendido": " ".join(str(cruda.get("entendido") or "").split()),
            "ambito": (str(cruda.get("ambito") or "").strip()
                       if str(cruda.get("ambito") or "").strip() in AMBITOS
                       else (cambios[0]["ambito"] if cambios else "nota")),
            "cambios": cambios,
        })
    sin_respuesta = [n["id"] for n in notas
                     if n["id"] not in {s["id"] for s in salida}]
    if sin_respuesta:
        avisos.append("estas notas no se han podido repartir y se quedan sin "
                      "aplicar: " + ", ".join(sin_respuesta))
    estadisticas.anotar(PASO, time.time() - arranque, tamano=len(notas),
                        ajuste={"modelo": modelo, "esfuerzo": esfuerzo},
                        proyecto=proyecto_id, unidades=len(salida))
    return {"notas": salida,
            "cambios": [c for s in salida for c in s["cambios"]],
            "avisos": avisos,
            "ajuste": {"modelo": modelo, "esfuerzo": esfuerzo}}


# ===========================================================================
# QUÉ HAY QUE REHACER
# ===========================================================================

#: El orden en que se recorren las tareas. Es el del pipeline, y por eso vive
#: aquí como una lista y no como un conjunto: aplicar diez cambios tiene que
#: rehacer las cosas en el orden en que dependen unas de otras.
#: Los ambitos que NO tocan un solo fotograma: lo suyo se resuelve volviendo a
#: mezclar el audio sobre los clips que ya hay.
#:
#: EXISTE PORQUE LA PROMESA ESTABA ESCRITA Y NO SE CUMPLIA. `AMBITOS["musica"]`
#: dice desde el primer dia «cuesta nada: se vuelve a mezclar el audio sobre los
#: clips que hay», y `CAMBIOS["musica_db"]` lleva un comentario que dice «SOLO
#: REMUXEAR: es el caso que mas se pide y el mas barato de todos». Pero eso era
#: prosa: el repaso enrutaba a la tarea `render` y la tarea `render` redibuja los
#: 98 planos en Edge, uno a uno. Pedir «baja la musica» costaba el render entero.
#:
#: Y el camino barato ya existia --`p8_render.ejecutar(solo_montar=True)`, que
#: dice en su docstring «hay cosas que cambian el video sin cambiar ningun
#: fotograma: vetar un efecto, montar otra banda, MOVER EL NIVEL DE LA MUSICA»--:
#: lo unico que faltaba era que el repaso lo pidiera.
AMBITOS_SOLO_MEZCLA = frozenset(
    a for a, ficha in AMBITOS.items() if ficha.get("solo_mezcla"))


def solo_mezcla(cambios):
    """Con estos cambios, basta con volver a mezclar el audio. -> bool

    Es AND y no OR a proposito: basta con que UN cambio toque un fotograma
    --una imagen, una cartela, un subtitulo, el guion-- para que haya que
    renderizar de verdad. Quedarse corto aqui no da un video a medias: da un
    video con el cambio pedido y sin los otros, y nadie lo mira dos veces.
    """
    cambios = [c for c in (cambios or []) if c.get("tipo")]
    if not cambios:
        return False
    return all(
        (CAMBIOS.get(c["tipo"]) or {}).get("ambito") in AMBITOS_SOLO_MEZCLA
        for c in cambios)


ORDEN = ("guion", "voz", "revision_audio", "escenarios",
         "guia_estilo", "corte", "plan_cartelas", "direccion", "piezas",
         "assets", "callouts", "banda_sonora", "efectos",
         "render")


def tareas_de(cambios):
    """Las tareas que hay que volver a correr, en orden de pipeline.

    ESTO ES EL AHORRO, y se ve mejor por lo que NO devuelve: una nota sobre la
    música devuelve `['render']` y nada más, o sea que aplicarla es volver a
    mezclar el audio sobre los clips que ya existen. Antes de esto, cualquier
    cambio significaba «genera el vídeo otra vez».
    """
    pedidas = set()
    for cambio in (cambios or []):
        pedidas.update(cambio.get("rehacer") or [])
    return [t for t in ORDEN if t in pedidas]


def resumen_de(reparto):
    """Una línea por ámbito con lo que se va a hacer, para enseñarlo antes."""
    cuenta = {}
    for nota in (reparto or {}).get("notas") or []:
        cuenta[nota["ambito"]] = cuenta.get(nota["ambito"], 0) + 1
    partes = [f"{n} de {ambito}" for ambito, n in sorted(cuenta.items())]
    tareas = tareas_de((reparto or {}).get("cambios") or [])
    return {"por_ambito": cuenta,
            "frase": " · ".join(partes) or "nada que aplicar",
            "tareas": tareas,
            "cuesta_imagenes": any(t in ("assets", "piezas") for t in tareas),
            "cuesta_voz": any(t in ("voz", "guion") for t in tareas)}
