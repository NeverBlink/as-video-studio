"""
Elegir la voz y sus mandos describiendo como quieres que suene.

Para que
--------
Elegir voz era rebuscar entre ochocientas fichas con nombres que no dicen nada
--«Alaric - Wizard», «Hector - Tour Leader»-- y despues acertar a mano con la
velocidad, las emociones y el aire entre bloques. Son cinco decisiones tecnicas
para una sola decision de verdad, que es COMO QUIERES QUE SUENE.

Aqui se escribe eso con palabras -- «narrador de true crime, grave y contenido,
que se tome su tiempo» -- y el CLI elige: la voz del catalogo, la velocidad, las
emociones y el hueco entre bloques.

Por que el catalogo entra recortado
-----------------------------------
Son mas de ochocientas voces y la mayoria no aportan nada a la decision: se
manda solo el idioma que toca y, dentro de el, las nativas primero, con su
nombre y su descripcion. Sin recortar, la instruccion pasa de los 100 KB y el
modelo se pierde entre fichas iguales.

Devuelve una PROPUESTA
----------------------
Lo que sale de aqui no se guarda solo: se devuelve a la interfaz, se rellenan
los mandos y quien mira decide. Es la misma regla que en el resto del Estudio,
y aqui importa mas que en ningun sitio porque la voz se PAGA cada vez que se
graba: aplicar a ciegas una eleccion que no convence son dos tomas en vez de una.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from . import cli_claude, comun, p4_voz
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import p4_voz

PASO = "voz_descrita"
TIEMPO_BASE_S = 180

#: Cuantas voces entran en la instruccion. Con mas, el modelo deja de leerlas y
#: elige por el nombre, que es justo lo que no queremos.
MAX_VOCES = 120

SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor, sin vallas de markdown y sin usar herramientas.")

HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")

INSTRUCCION = """Eres el director de sonido de un canal de video documental.
Elige la VOZ y sus mandos para que suene como pide el encargo.

ENCARGO
<<<
{encargo}
>>>

IDIOMA DE LA NARRACION: {idioma}
{ritmo}
VOCES DISPONIBLES (id — nombre — descripcion)
{voces}

MANDOS QUE TIENES QUE FIJAR

  velocidad: uno de {velocidades}. 'normal' es el ritmo natural de la voz. En
    una narracion documental casi todo cae entre 'slow' y 'normal'; los extremos
    son efectos, no registros.

  emociones: entre cero y dos de {emociones}, cada una opcional con nivel
    (:lowest, :low, :high, :highest). NO PONER NINGUNA ES UNA RESPUESTA VALIDA y
    a menudo la mejor: el tono neutro deja que hablen los hechos, que es como
    narra la mayoria de los documentales. Ponlas solo si el encargo pide color.
    OJO: el modelo de voz aplica UNA SOLA emocion, asi que pon primero la que
    mande.

  hueco_minimo: segundos de silencio entre bloques, de 0.3 a 1.6. Manda el
    ritmo del video entero: 0.3 es un informativo que no respira, 1.6 es un
    ensayo contemplativo. Un documental normal esta entre 0.8 y 1.2.

COMO ELEGIR LA VOZ
Lee las descripciones, no los nombres. Un nombre no dice como suena; la
descripcion si. Prioriza las nativas del idioma salvo que el encargo pida
expresamente acento extranjero.

DEVUELVE EXACTAMENTE ESTE JSON, sin nada alrededor:

{{
  "voz_id": "<id exacto de una de las voces de la lista>",
  "voz_nombre": "<su nombre, para poder comprobarlo>",
  "velocidad": "<una de {velocidades}>",
  "emociones": ["<emocion[:nivel]>", "..."],
  "hueco_minimo": <numero>,
  "velocidad_pedida": <true si el ENCARGO dice algo sobre la velocidad o el
    ritmo al hablar --"rapida", "pausada", "que corra", "sin prisa"--, false si
    no lo menciona y la has elegido tu>,
  "por_que": "<una linea: por que esta voz y estos mandos para este encargo>"
}}
"""


def _voces_para_instruccion(idioma, voz_fija=""):
    """Catalogo recortado a lo que ayuda a decidir: propias y nativas primero.

    Las voces PROPIAS de la cuenta (clonadas) van las primeras y marcadas: si
    el canal se ha clonado una voz, «una voz de hombre cercana» casi siempre
    quiere decir esa. Y `voz_fija` entra en la lista aunque cayera fuera del
    recorte, porque `_validar` la exige dentro.
    """
    fichas = p4_voz.listar_voces(idioma or "es")
    recorte = list(fichas[:MAX_VOCES])
    if voz_fija and all(f["id"] != voz_fija for f in recorte):
        recorte = [f for f in fichas if f["id"] == voz_fija] + recorte
    lineas = []
    for ficha in recorte:
        descripcion = " ".join(str(ficha.get("descripcion") or "").split())[:160]
        propia = not ficha.get("publica", True)
        lineas.append(f"  {ficha['id']} — {ficha.get('nombre') or ficha['id']}"
                      + (f" — {descripcion}" if descripcion else "")
                      + ("  [VOZ PROPIA DEL CANAL, clonada]" if propia else "")
                      + ("" if ficha.get("nativa", True) else "  [no nativa]"))
    if not lineas:
        raise RuntimeError(f"no hay ninguna voz de Cartesia para el idioma "
                           f"{idioma!r}: no se puede elegir por descripcion")
    return "\n".join(lineas), {f["id"] for f in recorte}


def _validar(datos, ids):
    """La propuesta, comprobada contra lo que el paso de voz acepta de verdad.

    Un id inventado o una emocion que no existe no se detectarian hasta lanzar
    la sintesis, o sea despues de pagarla. Aqui cuesta un milisegundo.
    """
    if not isinstance(datos, dict):
        raise RuntimeError("la respuesta no es un objeto JSON")
    voz_id = str(datos.get("voz_id") or "").strip()
    if voz_id not in ids:
        raise RuntimeError(f"la voz elegida ({voz_id!r}) no esta en el catalogo "
                           f"que se le paso. Elige una de la lista")
    velocidad = p4_voz.normalizar_velocidad(datos.get("velocidad") or "normal")
    emociones = p4_voz.normalizar_emociones(datos.get("emociones") or [])
    try:
        hueco = float(datos.get("hueco_minimo", p4_voz.HUECO_POR_DEFECTO))
    except (TypeError, ValueError):
        hueco = p4_voz.HUECO_POR_DEFECTO
    return {
        "voz_id": voz_id,
        "voz_nombre": str(datos.get("voz_nombre") or "").strip(),
        "velocidad": velocidad,
        "emociones": emociones,
        "hueco_minimo": round(max(0.0, min(3.0, hueco)), 2),
        # SI EL ENCARGO HABLABA DE VELOCIDAD O NO. No es telemetria: es lo que
        # permite al modo light rellenar la velocidad con su ritmo SOLO cuando
        # nadie la ha pedido. Lo contesta quien ha leido el encargo, que es el
        # unico que puede: buscar "rapida" en el texto fallaria con "sin prisa"
        # y con "que no corra". Ante la duda, TRUE -- respetar lo que quiza
        # pediste es mejor que pisarlo.
        "velocidad_pedida": datos.get("velocidad_pedida") is not False,
        "por_que": " ".join(str(datos.get("por_que") or "").split()),
    }


def proponer(encargo, idioma="es", ajuste=None, avisar=None, proyecto_id=None,
             cwd=None, peticion="", ritmo="", voz_fija=""):
    """Describe como quieres que suene y devuelve voz y mandos.

    `ritmo` es una frase sobre el MONTAJE ("planos de unos 2 s de media"), no
    una orden sobre la voz. Entra como dato porque cambia que voz encaja: la que
    suena bien encadenando frases de seis segundos no es la misma que aguanta un
    corte cada dos. Quien decide sigue siendo el encargo.
    """
    encargo = " ".join(str(encargo or "").split())
    if not encargo:
        raise RuntimeError("hace falta describir como quieres que suene la voz")
    avisa = avisar if callable(avisar) else (lambda v, m="": v)

    avisa(0.05, "leyendo el catalogo de voces")
    voz_fija = str(voz_fija or "").strip()
    voces, ids = _voces_para_instruccion(idioma, voz_fija)
    if voz_fija and voz_fija not in ids:
        raise RuntimeError(f"la voz elegida a mano ({voz_fija}) no esta en el "
                           f"catalogo de esta cuenta de Cartesia para "
                           f"{idioma!r}: revisa la clave o el idioma")
    por_fase = cli_claude.por_defecto_de(PASO)
    ajuste = ajuste or {"modelo": por_fase["modelo"],
                        "esfuerzo": por_fase["esfuerzo"]}

    ritmo = " ".join(str(ritmo or "").split())
    instruccion = INSTRUCCION.format(
        encargo=encargo, idioma=idioma or "es", voces=voces,
        ritmo=(f"RITMO DEL MONTAJE: {ritmo}\n" if ritmo else ""),
        velocidades=", ".join(p4_voz.VELOCIDADES),
        emociones=", ".join(p4_voz.EMOCIONES))
    # La correccion va la ULTIMA y con precedencia dicha: ver
    # `comun.bloque_correccion`. Vacia no anade nada.
    instruccion += comun.bloque_correccion(peticion, "la voz elegida")
    if voz_fija:
        # LA VOZ YA ESTA DECIDIDA (el canal eligio una a mano, normalmente la
        # suya clonada): el agente solo pone los mandos. Va lo ultimo, con
        # precedencia dicha, como la correccion.
        instruccion += (f"\n\nLA VOZ YA ESTA DECIDIDA POR EL CANAL y no se "
                        f"cambia: es {voz_fija}, la que en el catalogo de "
                        f"arriba lleva ese id. Devuelve exactamente ese voz_id "
                        f"y su nombre, y elige SOLO la velocidad, las emociones "
                        f"y el aire que mejor le van al encargo con esa voz.")

    avisa(0.15, ("poniendo los mandos a la voz elegida a mano"
                 if voz_fija else
                 f"eligiendo entre {len(ids)} voces") + f" con {ajuste['modelo']}")
    texto, sobre = cli_claude.ejecutar(
        instruccion, modelo=ajuste["modelo"], esfuerzo=ajuste["esfuerzo"],
        cwd=cwd, base_tiempo_s=TIEMPO_BASE_S, sistema=SISTEMA,
        herramientas_vetadas=HERRAMIENTAS_VETADAS,
        extra=["--no-session-persistence"],
        para="la eleccion de voz")

    elegido = _validar(comun.extraer_json(texto, "la eleccion de voz"), ids)
    if voz_fija:
        # por si el agente se despisto: la voz es la fija, con su nombre real
        elegido["voz_id"] = voz_fija
        nombre = next((f.get("nombre") for f in p4_voz.listar_voces(idioma or "es")
                       if f["id"] == voz_fija), "")
        elegido["voz_nombre"] = nombre or elegido.get("voz_nombre") or voz_fija
    elegido["tokens"] = comun.tokens_de_cli(sobre)
    avisa(1.0, f"«{elegido['voz_nombre'] or elegido['voz_id']}» · "
               f"{elegido['velocidad']} · "
               f"{', '.join(elegido['emociones']) or 'sin color'} · "
               f"aire {elegido['hueco_minimo']}s")
    return elegido
