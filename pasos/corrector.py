"""EL CORRECTOR DE UN PLANO: la nota del revisor, convertida en prompt y adjuntos.

QUE ES
------
Cuando alguien rechaza una imagen con una nota («que el ordenador sea el mismo
que en la escena anterior, que uno de los monos sea Jensen y el resto monos
trabajadores random, y mantén la composición»), el generador necesita DOS cosas
que una frase no lleva: las imágenes exactas de las que se habla (la escena
anterior, la hoja de Jensen, la lámina del estilo, la imagen que se rechaza) y
un prompt que diga qué tomar de cada una y qué no.

Hasta el 02-09-2026 eso se resolvía con reglas fijas: la hoja de los personajes
del plano, la imagen rechazada si el enrutador decía «retoque», lo que trajera
la nota. Valía para «cámbiale las gafas» y se quedaba corto en cuanto la nota
nombraba OTRA escena, OTRO personaje o «personajes genéricos del estilo».

QUE HACE
--------
Un agente del CLI (`cli_claude`, el mismo motor que el catálogo, la dirección y
el repaso) recibe la nota, el contexto del plano y un INVENTARIO de todo el
material del vídeo con sus rutas: la imagen actual, las versiones anteriores de
ese plano, los planos vecinos, todas las hojas del reparto, las láminas del
estilo, las piezas, lo que el revisor adjuntó. Abre con `Read` las que necesite
para entender la nota, y devuelve:

  - `alcance`        retoque (se conserva la composición) o sustituye
  - `personajes`     quién sale en el plano nuevo (ids del reparto)
  - `escena`         la descripción nueva del plano, en inglés, ya con lo que
                     pide la nota
  - `referencias`    la lista ORDENADA de imágenes que se adjuntan, con el
                     detalle de qué copiar de cada una; su clase (hoja, plano
                     vecino, imagen rechazada, adjunto) la pone el inventario
  - `porque`         una línea, para la bitácora

`p6_assets` compone el prompt final con eso, CON LAS MISMAS PIEZAS que la
primera generación: la lámina del estilo la primera (es la que fija el dibujo),
cada referencia presentada por `frase_de_referencia` según su clase --la misma
frase que oiría en un plano nuevo-- más el detalle del agente, la descripción
nueva, la cláusula de especie, las reglas de la casa y la nota al final, que es
donde más pesa (ver `_bloque_feedback`). El corrector no tiene vocabulario
propio: elige y precisa, no reescribe.

LO QUE NO HACE
--------------
No genera. No toca el plan: la descripción nueva y los personajes valen para
ESTA regeneración y se guardan en el resultado de la unidad, no en el plan. Y
no puede adjuntar nada que no esté en el inventario: la respuesta se valida
contra él, ruta a ruta.

SI FALLA
--------
Se vuelve al camino de siempre (`_referencias_escena` + `_prompt_completo` con
la nota al final) y se anota el fallo. Una corrección nunca se queda sin hacer
porque el agente no contestara.
"""
import json
import os
import time

try:
    from . import cli_claude, comun
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun

FASE = "corrector_imagen"
MODELO_POR_DEFECTO = cli_claude.por_defecto_de(FASE)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(FASE)["esfuerzo"]
TIEMPO_BASE_S = 360

#: Cuantas imagenes puede adjuntar el agente ademas de la lamina del estilo. La
#: API admite mas, pero cada una son ~700 tokens y a partir de seis o siete el
#: generador deja de saber cual manda.
MAX_REFERENCIAS = 6

#: Cuantos planos vecinos (a cada lado) entran en el inventario.
VECINOS = 3

HERRAMIENTAS_VETADAS = ("Bash", "Write", "Edit", "NotebookEdit", "Grep", "Glob",
                        "WebFetch", "WebSearch", "Task", "TodoWrite")
HERRAMIENTAS_PERMITIDAS = ("Read",)

SISTEMA = ("Eres el director de arte que corrige UN plano de un video de "
           "animacion narrada a partir de la nota de un revisor. Antes de "
           "escribir nada, abre con Read las imagenes del inventario que "
           "necesites para entender la nota: como minimo la imagen actual del "
           "plano y cualquier imagen que la nota nombre o implique. Responde "
           "despues exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor y sin vallas de markdown.")

INSTRUCCION = """Corrige el plano {sid} de «{titulo}» siguiendo la nota del revisor.

LA NOTA DEL REVISOR (manda sobre todo lo demas):
<<<
{nota}
>>>

EL PLANO, TAL Y COMO ESTA:
  narracion (lo que dice la voz en ese tramo): {narracion}
  bloque del guion: {bloque}
  sitio: {sitio}
  personajes del plano ahora: {personajes}
  descripcion con la que se dibujo (en ingles): {descripcion}
  luz: {luz}
  tipo de plano (obligatorio, no lo cambies): {encuadre}

EL ESTILO DEL VIDEO:
{estilo}

EL REPARTO (id -> como es; su hoja esta en el inventario si se dibujo):
{reparto}

LOS SITIOS DEL VIDEO (id -> como es):
{sitios}

INVENTARIO DE IMAGENES (ruta -> que es). Solo puedes adjuntar rutas de esta
lista, tal cual estan escritas. Cada una lleva su CLASE entre corchetes, y la
clase decide lo que el generador oye de ella por defecto:
  [rechazada]    «es este mismo plano tal y como se dibujo: conserva todo y
                 cambia solo lo que pide la nota»
  [continuidad]  «es un plano vecino: misma paleta, misma luz, mismo sitio si
                 lo es; no copies su encuadre ni sus poses»
  [reparto]      «es la hoja de ese personaje: copia su cara, pelo, cuerpo y
                 ropa; no copies la hoja»
  [adjunta]      «usala SOLO para lo que la nota pida de ella»
{inventario}

QUE TIENES QUE DEVOLVER
Un objeto JSON con estas claves:
  "alcance"      "retoque" si la composicion se conserva y cambia algo
                 concreto; "sustituye" si el plano nuevo es otra cosa.
  "personajes"   la lista de ids del reparto que salen en el plano NUEVO
                 (vacia si no sale nadie del reparto). Los personajes
                 genericos («trabajadores random») no van aqui: van en la
                 descripcion.
  "escena"       la descripcion NUEVA del plano en ingles, completa y
                 autosuficiente: que se ve, quien, donde, que hace cada uno.
                 Incorpora lo que pide la nota y conserva lo que la nota no
                 toca. No describas el estilo de dibujo (eso lo pone la
                 lamina) ni escribas «reference image»: eso va en las
                 etiquetas.
  "referencias"  la lista ORDENADA de imagenes a adjuntar, cada una
                 {{"ruta": <ruta del inventario>, "detalle": <frase en
                 ingles>}}. El generador ya oye la frase de su clase (arriba);
                 el detalle es lo que SOLO se sabe mirando la imagen: que
                 copiar de ella en concreto y que no. Ejemplos:
                   - imagen rechazada: «keep the empty cubicles, the stacked
                     boxes and the whiteboard of crossed-out numbers exactly;
                     change only who sits at the desk»
                   - hoja de personaje: «use the full-body row; grey polo, no
                     tie»
                   - plano vecino: «copy only the beige boxy CRT at its left
                     edge, same model and screen, and put that computer on
                     the central desk; copy nothing else from it»
                 La lamina del estilo NO la pongas: se adjunta siempre y va la
                 primera. Como mucho {max_referencias} referencias; no
                 adjuntes lo que no vayas a precisar en su detalle. Si el
                 alcance es sustituye, no adjuntes la imagen rechazada: con
                 ella delante el generador la retoca en vez de sustituirla.
  "porque"       una linea: que has mirado y por que has elegido esas
                 referencias.

REGLAS
- Abre con Read las imagenes que necesites ANTES de decidir; la nota puede
  hablar de algo que solo se ve mirando («el mismo ordenador que antes»).
- {especie}
- La identidad de cada personaje del reparto sale de SU hoja: si la nota
  mete a alguien del reparto en el plano, adjunta su hoja y nombralo en
  "personajes". Si la nota pide personajes genericos del estilo, descríbelos
  en "escena" (distintos entre si) y NO les adjuntes hoja.
- Si la nota se contradice con la narracion o con el sitio, manda la nota.
- Nada de texto escrito en la imagen salvo que la nota lo pida.
"""


def _texto(valor, tope=1200):
    return " ".join(str(valor or "").split())[:tope]


def _inventario_legible(inventario):
    lineas = []
    for ficha in inventario:
        lineas.append(f"  {ficha['ruta']}\n      -> [{ficha.get('papel') or 'adjunta'}] "
                      f"{ficha['que']}")
    return "\n".join(lineas) if lineas else "  (sin imagenes)"


def _reparto_legible(reparto):
    lineas = []
    for ident, ficha in (reparto or {}).items():
        if not isinstance(ficha, dict):
            continue
        lineas.append(f"  {ident}: {_texto(ficha.get('descripcion'), 400)}")
    return "\n".join(lineas) if lineas else "  (sin reparto)"


def _sitios_legibles(sets):
    lineas = []
    for ident, ficha in (sets or {}).items():
        if isinstance(ficha, dict):
            lineas.append(f"  {ident}: {_texto(ficha.get('descripcion'), 300)}")
    return "\n".join(lineas) if lineas else "  (sin sitios)"


def preparar(nota, escena, catalogo, estilo_legible, regla_especie, inventario,
             titulo="", bloque="", cwd=None, proyecto_id=None, ajuste=None,
             avisar=None):
    """Convierte la nota en (alcance, personajes, escena, referencias). -> dict|None

    `inventario` es [{"ruta", "que", "clase"}], con rutas absolutas y reales.
    Devuelve None si el agente no contesta o contesta algo inservible: quien
    llama vuelve entonces al camino de siempre.
    """
    avisar = avisar or (lambda *a, **k: None)
    nota = _texto(nota, 2000)
    if not nota or not inventario:
        return None
    validas = {os.path.normcase(os.path.abspath(f["ruta"])): f
               for f in inventario}
    reparto = (catalogo or {}).get("reparto") or {}
    ajuste = dict(ajuste or {})
    modelo = cli_claude.normalizar_modelo(ajuste.get("modelo"),
                                          defecto=MODELO_POR_DEFECTO)
    esfuerzo = cli_claude.normalizar_esfuerzo(ajuste.get("esfuerzo"),
                                              defecto=ESFUERZO_POR_DEFECTO)
    instruccion = INSTRUCCION.format(
        sid=escena.get("id"), titulo=_texto(titulo, 120) or "sin titulo",
        nota=nota,
        narracion=_texto(escena.get("narracion"), 600) or "(sin narracion)",
        bloque=_texto(bloque, 900) or "(sin bloque)",
        sitio=escena.get("set") or "(sin sitio)",
        personajes=", ".join(escena.get("personajes") or []) or "(nadie del reparto)",
        descripcion=_texto(escena.get("prompt"), 1500) or "(sin descripcion)",
        luz=_texto(escena.get("luz"), 200) or "(sin dato)",
        encuadre=_texto(escena.get("encuadre"), 300) or "(libre)",
        estilo=estilo_legible or "  (sin guia escrita)",
        reparto=_reparto_legible(reparto),
        sitios=_sitios_legibles((catalogo or {}).get("sets")),
        inventario=_inventario_legible(inventario),
        max_referencias=MAX_REFERENCIAS,
        especie=(f"En este estilo, {regla_especie} Esa regla decide la especie "
                 f"y la anatomia de TODOS los personajes, tambien de los "
                 f"genericos; la hoja de cada uno decide su identidad."
                 if regla_especie else
                 "Los personajes se dibujan como diga la lamina del estilo."))
    arranque = time.time()
    avisar(0.05, f"{escena.get('id')}: el corrector esta leyendo la nota y las "
                 f"imagenes")
    try:
        texto, _sobre = cli_claude.ejecutar(
            instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
            tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S, sistema=SISTEMA,
            herramientas_vetadas=HERRAMIENTAS_VETADAS,
            herramientas_permitidas=HERRAMIENTAS_PERMITIDAS,
            extra=["--no-session-persistence"],
            para=f"el corrector del plano {escena.get('id')}")
        datos = comun.extraer_json(texto, "la respuesta del corrector")
    except Exception as fallo:                                   # noqa: BLE001
        return {"error": f"{type(fallo).__name__}: {fallo}"[:300],
                "segundos": round(time.time() - arranque, 1)}
    if not isinstance(datos, dict):
        return {"error": "la respuesta no es un objeto",
                "segundos": round(time.time() - arranque, 1)}

    alcance = str(datos.get("alcance") or "").strip().lower()
    if alcance not in ("retoque", "sustituye"):
        alcance = "retoque"
    personajes = []
    for ident in (datos.get("personajes") or []):
        ident = str(ident or "").strip()
        if ident in reparto and ident not in personajes:
            personajes.append(ident)
    descripcion = _texto(datos.get("escena"), 2500)
    referencias, vistas = [], set()
    for cruda in (datos.get("referencias") or []):
        if not isinstance(cruda, dict):
            continue
        clave = os.path.normcase(os.path.abspath(str(cruda.get("ruta") or "")))
        ficha = validas.get(clave)
        detalle = _texto(cruda.get("detalle") or cruda.get("etiqueta"), 600)
        if not ficha or clave in vistas:
            continue
        vistas.add(clave)
        # la referencia sale con el papel y los atributos del inventario
        # (nombre, tapada, mismo_set...) y con el detalle del agente encima
        referencia = {k: v for k, v in ficha.items() if k not in ("que", "clase")}
        referencia["detalle"] = detalle
        referencias.append(referencia)
        if len(referencias) >= MAX_REFERENCIAS:
            break
    if not descripcion:
        return {"error": "el corrector no ha devuelto la descripcion del plano",
                "segundos": round(time.time() - arranque, 1)}
    return {"alcance": alcance, "personajes": personajes, "escena": descripcion,
            "referencias": referencias,
            "porque": _texto(datos.get("porque"), 400),
            "modelo": modelo, "esfuerzo": esfuerzo,
            "segundos": round(time.time() - arranque, 1)}
