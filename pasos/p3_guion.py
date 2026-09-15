"""
Paso 3: redaccion del guion.

Llama al CLI de Claude en modo headless y le da cuatro cosas: el transcript del
video de referencia como documentacion, el brief del usuario, el guion anterior
(si lo hay, para no perder el contexto entre iteraciones) y la instruccion
concreta de esta pasada.

La regla que gobierna el paso es que el guion se REDACTA de nuevo: se siguen los
mismos hechos, el mismo orden y el mismo ritmo de capitulos, pero las frases son
propias. Se pide en la instruccion y ahi se queda.

Aqui hubo ademas un DETECTOR DE COPIAS -- tiradas de diez palabras identicas
entre cada bloque y el material, y una nueva pasada si pasaban del umbral -- y se
retiro el 24-08-2026. El motivo es que el material dejo de ser siempre ajeno: con
`fuentes` una persona puede pegar SU PROPIO guion y pedir que se respete, y un
detector que no distingue eso lo unico que sabe hacer es reescribir lo que le
acaban de dar por bueno. Lo que hacia falta no era afinar el umbral: era que la
regla la ponga quien aporta el material.

La instruccion viaja por la ENTRADA ESTANDAR, no como argumento: un transcript
de veinte minutos pasa de los 60 KB y no cabe en una linea de comandos de
Windows.

UN VIDEO, UN IDIOMA
-------------------
Aqui hubo un eje de idiomas: el brief pedia una lista y el paso redactaba el
principal y despues adaptaba bloque a bloque a los demas conservando los ids. Se
retiro entero el 24-08-2026 por decision del canal. Un video se hace en UN
idioma, y hacer el mismo video en otro es otro proyecto -- que ademas es lo
honesto, porque de un guion cuelgan una toma de voz, una imagen por plano y unos
subtitulos, y ninguna de esas tres se comparte entre idiomas.

Por que el paso tardaba diez minutos
------------------------------------
No eran los servidores MCP. Era el ESFUERZO DE RAZONAMIENTO: si no se pasa
--effort, el CLI se pone a pensar durante minutos antes de escribir una sola
palabra del guion. Medido con el mismo transcript de 9341 palabras y la misma
instruccion:

    sin --effort, con el entorno limpio      605,8 s   78.447 tokens de salida
    sin --effort, heredando CLAUDE_EFFORT    336,3 s   39.679 tokens de salida
    con --effort low                          67,0 s    7.031 tokens de salida

Por eso el esfuerzo se pasa SIEMPRE de forma explicita: es la unica manera de
que el paso no dependa de con que entorno se arranco el servicio. Y por eso el
timeout es finito y mata el arbol de procesos: nunca "ejecutando" para siempre.

Salida: el guion partido en bloques con id estable (B001, B002...) para que el
resto del pipeline pueda referenciar trozos concretos.

El humano puede reescribir bloques a mano desde la interfaz: llegan en
params["bloques"] = {"B003": {"texto": "..."}} y se aplican DESPUES de redactar,
asi que lo que corrija una persona gana siempre a lo que acabe de escribir el
modelo.

Anotaciones de voz
------------------
El guion sale con las etiquetas SSML que necesita Cartesia metidas en el propio
texto del bloque -- sobre todo `<break/>`, que es la que marca donde para el
relato. Se piden AQUI, al redactar, y no se cosen despues sobre un guion ya
escrito, y no cosidas despues: donde va una pausa depende de
como este escrita la frase, y un modelo que anota un texto ajeno pone las pausas
donde el las habria puesto.

Todo texto de bloque -- el que escribe el modelo y el que corrige una persona a
mano -- pasa por `_aplicar_marcas` antes de guardarse. Ese es el unico filtro que hay, y hace falta que sea uno solo: una
etiqueta que Cartesia no reconoce no da error, se LOCUTA. Ver marcas_tts.

Las anotaciones no son palabras del guion: la horquilla y la revision de tildes
cuentan lo que se OYE.

Lo barato primero: reponer una tilde no es pedir otro guion
-----------------------------------------------------------
Una tilde que falta se arregla escribiendola. Aqui no: una sola palabra sin
tilde tiraba el guion entero y lo pedia otra vez, y se pago caro el 27-08-2026.
El intento 1 devolvio 88 bloques y 2585 palabras --dentro de la horquilla
1400-2600, listo para grabar--, `comun.SIN_TILDE_ES` marco un unico «Aun asi»
(que ademas esta bien escrito) y el motor pidio el guion completo otra vez. El
intento 2 volvio con 120 bloques y 3799 palabras, un 46 % por encima del
maximo, y ESE fue el que se entrego. Dos llamadas, nueve minutos, y un guion
peor que el que ya estaba escrito.

De ahi las tres reglas que gobiernan ahora los reintentos:

  1. LO QUE SE PUEDE ARREGLAR SIN PREGUNTAR, SE ARREGLA. Las palabras de la
     lista son errores seguros y traen su forma correcta al lado, asi que
     `_aplicar_marcas` las repone y lo cuenta en los avisos. Al modelo solo se
     vuelve si el guion entero viene sin tildes, que eso si es otro guion.
  2. UNA CORRECCION VIAJA CON EL TEXTO QUE CORRIGE. «Devuelvelo sin cambiar
     nada mas» era imposible de obedecer: cada llamada al CLI es una sesion
     nueva y el modelo no habia visto lo que acababa de escribir. Ahora el
     intento anterior va dentro de la instruccion, bloque a bloque y con su
     cuenta de palabras.
  3. SE ENTREGA EL MEJOR INTENTO, NO EL ULTIMO. Un reintento es una apuesta, y
     una apuesta se puede perder. Si el segundo vuelve peor que el primero, se
     entrega el primero y se dice.
"""
import json
import os
import re
import subprocess  # noqa: F401  (las pruebas sustituyen p3_guion.subprocess.Popen)
import time

try:
    from . import cli_claude, comun, cta, estadisticas, fuentes, marcas_tts
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import cta
    import estadisticas
    import fuentes
    import marcas_tts

PASO = "guion"


#: Y del video de origen, cuando el material es el dosier y ademas se lee el
#: video entero. El mismo techo y por lo mismo: aqui lo que se lee es la FORMA,
#: y la forma se aprende del video entero, con su entrada y su cierre.
MAX_CARACTERES_ORIGEN = 60000

# Tiempo de referencia de UNA llamada con esfuerzo 'low'. El techo real se deriva
# de aqui y del esfuerzo elegido (cli_claude.tiempo_max): un techo fijo de 420 s
# con esfuerzo 'high' es una trampa, porque garantiza TiempoAgotado y
# TiempoAgotado no se reintenta a proposito.
TIEMPO_BASE_S = 420

# Espera maxima de una llamada con esfuerzo 'low' para que todavia compense
# repetirla. Tambien escala con el ajuste (ver umbral_reintento_de).
UMBRAL_REINTENTO_BASE_S = 120

PARAMS_POR_DEFECTO = {
    "prompt_general": "",
    "regenerar_desde_cero": False,
    # El ajuste por defecto de cada fase vive en cli_claude.POR_FASE, elegido
    # por la complejidad de la tarea y con las fuentes anotadas alli.
    "modelo": cli_claude.por_defecto_de("guion")["modelo"],
    "esfuerzo": cli_claude.por_defecto_de("guion")["esfuerzo"],
    "tiempo_max_s": 0,      # 0 = automatico segun el esfuerzo
    "reintentos": 1,
    "umbral_reintento_s": 0,  # 0 = automatico segun el esfuerzo
    "max_caracteres_transcript": 120000,
    "idioma": "",           # vacio: el que diga el brief
    # EL MATERIAL NO ESTA AQUI: vive en el paso «Origen» (`p1_ingesta`), con
    # su propia version y su propia firma. Este paso depende de ese, asi que
    # cambiarlo ya deja el guion obsoleto sin necesidad de duplicar el texto
    # --ni su huella-- en dos cajones que pueden separarse.
    # Si el material que se aporto ES el guion. Lo escribe la tarea de fuentes
    # leyendo el `uso` de cada una, y aqui cambia la regla 1 del prompt: con
    # esto puesto no se redacta de nuevo, se respeta.
    "guion_propio": False,
    "bloques": {},          # {"B003": {"texto": "..."}} ediciones a mano
    # Anotaciones de voz dentro del texto (ver marcas_tts). Se piden al redactar
    # y no se cosen despues: donde va una pausa depende de como este escrita la
    # frase, y un modelo que anota un guion ajeno pone las pausas donde el las
    # habria puesto, no donde estan.
    "anotaciones_voz": True,
    # La emocion aparte: es la unica etiqueta que la propia documentacion de
    # Cartesia marca como experimental, y justo en nuestro caso (una toma
    # continua, o sea todo cambio es a mitad de generacion). Se deja encendida
    # porque bien usada aporta, pero con su propio interruptor para poder
    # apagarla sin renunciar a las pausas, que es lo que de verdad importa.
    "emocion_en_voz": True,
    # Silencio garantizado al final del PRIMER bloque. El gancho esta escrito
    # para que despues haya aire, y esa pausa concreta no puede depender de que
    # el redactor se acuerde de anotarla: sin ella el bloque siguiente le pisa
    # el remate y el recurso no funciona. 0 lo desactiva, para un video que no
    # abra con un gancho.
    "pausa_gancho_ms": 900,
    # AIRE AL CAMBIAR DE TEMA. Un video que salta de asunto sin pausa se oye
    # como una lista leida: la frase nueva empieza donde acabo la anterior y no
    # hay forma de oir que se ha cambiado de capitulo. Es la misma clase de
    # decision que la pausa del gancho --estructura, no criterio-- asi que
    # tampoco depende de que el redactor se acuerde: la pone el motor en el
    # bloque que CIERRA cada tramo, o sea justo antes de cada 'abre_seccion'.
    #
    # Se suma al hueco que la voz deja entre bloques (0,5 s de serie), asi que
    # el corte real ronda el segundo y medio. 0 lo desactiva.
    "pausa_seccion_ms": 900,
    # LA PRESENTACION Y LAS LLAMADAS A LA ACCION (`pasos/cta.py`): tres momentos,
    # cada uno con lo que se quiere que diga. Son params del guion porque el
    # texto que redacta el modelo depende de ellos, y son del VIDEO: se escriben
    # una vez en el estilo y cada video nace con ellas puestas.
    **cta.PARAMS_POR_DEFECTO,
}

# La lista vive en cli_claude para que la UI, el backend y los cuatro sitios que
# llaman al CLI no tengan cada uno su copia: ya estaban desincronizadas (la
# interfaz ofrecia tres esfuerzos y el backend aceptaba cinco).
ESFUERZOS = cli_claude.ESFUERZOS

# Variables del entorno que le cambian el razonamiento al CLI. --effort ya pisa
# a CLAUDE_EFFORT (medido), pero MAX_THINKING_TOKENS actua por su cuenta, y el
# Estudio se arranca a menudo desde una sesion de Claude Code que las trae
# puestas: se quitan para que el paso tarde lo mismo se lance desde donde se
# lance.
ENTORNO_FUERA = ("CLAUDE_EFFORT", "MAX_THINKING_TOKENS")

# Sin herramientas el CLI contesta en un solo turno: aqui no tiene nada que leer
# ni que escribir, todo el material va en la instruccion.
HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")

# Una sola linea y sin metacaracteres: en Windows el CLI se invoca a traves de
# claude.cmd y un salto de linea dentro de un argumento parte el comando.
SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor, sin vallas de markdown y sin usar herramientas.")

def describir(params):
    """Resumen de una linea de la configuracion del paso, para la bitacora."""
    opciones = _normalizar(params, estricto=False)
    texto = " ".join(opciones["prompt_general"].split())
    if len(texto) > 60:
        texto = texto[:57] + "..."
    origen = "desde cero" if opciones["regenerar_desde_cero"] else "sobre el guion anterior"
    editados = len(opciones["bloques"])
    idioma = opciones["idioma"] or "el del brief"
    return (f"guion con {opciones['modelo']} (esfuerzo {opciones['esfuerzo']}) "
            f"{origen} en {idioma}: {texto or 'sin instruccion extra'}"
            + (f"; {editados} bloque(s) editados a mano" if editados else "")
            + ("" if opciones["anotaciones_voz"] else "; sin anotaciones de voz"))


# --------------------------------------------------------------------- params

def _normalizar(params, estricto=True):
    """Params completos y con los tipos correctos; valida si estricto."""
    opciones = dict(PARAMS_POR_DEFECTO)
    for clave, valor in (params or {}).items():
        if clave in PARAMS_POR_DEFECTO:
            opciones[clave] = valor

    opciones["prompt_general"] = str(opciones.get("prompt_general") or "").strip()
    opciones["regenerar_desde_cero"] = bool(opciones.get("regenerar_desde_cero"))
    opciones["anotaciones_voz"] = bool(opciones.get("anotaciones_voz"))
    opciones["emocion_en_voz"] = bool(opciones.get("emocion_en_voz"))
    # Un modelo mal escrito solo se detectaba por returncode != 0, o sea despues
    # de haber pagado el arranque del CLI y la espera entera.
    opciones["modelo"] = cli_claude.normalizar_modelo(
        opciones.get("modelo"), estricto=estricto)
    opciones["esfuerzo"] = cli_claude.normalizar_esfuerzo(
        opciones.get("esfuerzo"), estricto=estricto)

    for clave, minimo in (("reintentos", 0), ("umbral_reintento_s", 0),
                          ("pausa_seccion_ms", 0),
                          ("pausa_gancho_ms", 0),
                          ("max_caracteres_transcript", 2000)):
        try:
            opciones[clave] = int(opciones[clave])
        except (TypeError, ValueError):
            if estricto:
                raise ValueError(f"{clave} tiene que ser un numero entero")
            opciones[clave] = PARAMS_POR_DEFECTO[clave]
        if estricto and opciones[clave] < minimo:
            raise ValueError(f"{clave} tiene que ser al menos {minimo}")

    # 0 significa "automatico segun el esfuerzo". Cualquier otro valor es un
    # techo puesto a mano, y ahi si se exige un minimo: un techo de 5 s no es
    # una decision, es una errata, y produce un TiempoAgotado que parece un
    # fallo del CLI.
    try:
        opciones["tiempo_max_s"] = int(opciones["tiempo_max_s"])
    except (TypeError, ValueError):
        if estricto:
            raise ValueError("tiempo_max_s tiene que ser un numero entero")
        opciones["tiempo_max_s"] = PARAMS_POR_DEFECTO["tiempo_max_s"]
    if estricto and 0 < opciones["tiempo_max_s"] < 30:
        raise ValueError("tiempo_max_s tiene que ser al menos 30 "
                         "(o 0 para que lo decida el esfuerzo)")
    if opciones["tiempo_max_s"] < 0:
        opciones["tiempo_max_s"] = 0

    # Se tolera la clave vieja en plural para que un proyecto guardado con el
    # eje de idiomas siga abriendo: se coge el primero, que es el que era el
    # principal, y los demas se pierden -- que es exactamente lo que significa
    # haber retirado el eje.
    crudo = opciones.get("idioma")
    if not str(crudo or "").strip():
        vieja = (params or {}).get("idiomas")
        if isinstance(vieja, str):
            crudo = vieja
        elif isinstance(vieja, list) and vieja:
            crudo = vieja[0]
    opciones["idioma"] = str(crudo or "").strip().lower()

    opciones["guion_propio"] = bool(opciones.get("guion_propio"))

    # LOS PARAMS CRUDOS otra vez, y por el mismo motivo: `cta._normalizar` mira
    # tambien los personajes para TRADUCIR lo de antes del 06-09-2026 (cuando
    # esto eran dos casillas del personaje), y sobre `opciones` ya estaria
    # mirando sus propios defectos en vez de lo que se guardo.
    opciones.update(cta._normalizar(params or {}, estricto=estricto))

    crudos = opciones.get("bloques")
    ediciones = {}
    if isinstance(crudos, dict):
        for clave, valor in crudos.items():
            texto = valor.get("texto") if isinstance(valor, dict) else valor
            texto = " ".join(str(texto or "").split())
            if texto:
                ediciones[str(clave).strip().upper()] = texto
    elif crudos and estricto:
        raise ValueError("bloques tiene que ser un objeto {id: {texto}}")
    opciones["bloques"] = ediciones
    return opciones


# ------------------------------------------------------------------ material


def _reloj(segundos):
    total = int(float(segundos))
    return f"{total // 60:02d}:{total % 60:02d}"


def _transcript_legible(transcript, maximo):
    """El transcript como lineas con marca de tiempo, recortado si no cabe."""
    lineas = [f"[{_reloj(t.get('t_in', 0))}] {t.get('texto', '')}" for t in transcript]
    texto, _ = comun.recortar("\n".join(lineas), maximo,
                              "[...transcript recortado por longitud...]")
    return texto


def _guion_anterior(proyecto):
    """Guion de la version activa del paso, si ya se redacto alguna vez."""
    datos = comun.leer_salida(proyecto, PASO, "guion.json", obligatorio=False)
    if not isinstance(datos, dict):
        return None
    bloques = datos.get("guion") or datos.get("bloques") or []
    return datos if bloques else None


def _idioma_pedido(brief, opciones):
    """Idioma del guion: el de los params si esta, si no el del brief."""
    if opciones["idioma"]:
        return opciones["idioma"]
    delista = brief.get("idiomas_salida")
    if isinstance(delista, list) and delista:
        return str(delista[0]).strip().lower()
    return str(brief.get("idioma_salida") or "es").strip().lower()


def _horquilla(brief, idioma):
    """Presupuesto y limites de palabras de ese idioma, segun el brief."""
    horquillas = brief.get("horquillas")
    if isinstance(horquillas, dict) and isinstance(horquillas.get(idioma), dict):
        ficha = horquillas[idioma]
        return (int(ficha.get("presupuesto_palabras") or 0),
                int(ficha.get("palabras_minimo") or 0),
                int(ficha.get("palabras_maximo") or 0))
    presupuesto = int(brief.get("presupuesto_palabras") or 0)
    margen = brief.get("margen") or {}
    minimo = int(brief.get("palabras_minimo") or margen.get("minimo") or 0)
    maximo = int(brief.get("palabras_maximo") or margen.get("maximo") or 0)
    return presupuesto, minimo, maximo


def _nombre_idioma(brief, idioma):
    nombres = dict(zip(brief.get("idiomas_salida") or [],
                       brief.get("idiomas_salida_nombres") or []))
    return nombres.get(idioma) or brief.get("idioma_salida_nombre") or idioma


# LA REGLA DE REDACCION LA PONE EL MATERIAL, y por eso son dos.
#
# Hasta el 24-08 solo existia la primera y ademas se comprobaba con un detector
# de tiradas identicas. Con `fuentes` el material puede ser algo que ha escrito
# la propia persona y que quiere que se respete: reescribirlo seria tirar su
# trabajo, y ningun umbral sabe distinguir un caso del otro. Lo que decide es de
# donde viene el material, que es un dato y no una adivinanza.
REGLA_REDACCION = (
    "REDACTA DE NUEVO. El material que va arriba es DOCUMENTACION, no un texto "
    "para reaprovechar: sigue los mismos hechos, el mismo orden y el mismo ritmo "
    "de capitulos, pero las frases son tuyas. No copies ninguna frase del "
    "original y no la parafrasees frase a frase: lee el bloque de informacion, "
    "entiendelo y cuentalo a tu manera.")

#: Y LA TERCERA, para cuando el material es un DOSIER y no un relato.
#:
#: La de arriba manda seguir «el mismo orden y el mismo ritmo de capitulos», y
#: eso solo tiene sentido si el material ES un relato -- un video transcrito de
#: principio a fin --. Cuando el material sale de `fuentes` con las busquedas
#: encendidas, lo que hay arriba son ciento y pico fichas de datos en el orden
#: en que se encontraron: seguir ESE orden es exactamente lo que hace que el
#: video salte de tema a tema tirando datos sueltos. Medido en un video real de
#: 67 busquedas y 129 entradas.
REGLA_REDACCION_DOSIER = (
    "REDACTA DE NUEVO, Y EL ORDEN LO PONES TU. El material que va arriba es un "
    "DOSIER: hechos reunidos de varias fuentes y apilados en el orden en que se "
    "encontraron. No es un relato, asi que aqui NO hay un orden que seguir ni un "
    "ritmo de capitulos que copiar: eso lo decides tu, y es la parte mas "
    "importante del encargo (ver COMO SE ESTRUCTURA ESTE VIDEO, mas abajo). Del "
    "dosier salen los hechos; del orden que tu elijas sale el video. Las frases "
    "son tuyas: no copies ni parafrasees ficha a ficha.")

REGLA_GUION_PROPIO = (
    "ESTE GUION YA ESTA ESCRITO Y ES DE LA CASA. El material que va arriba no es "
    "documentacion: es el guion, escrito por quien te lo pide. Conservalo palabra "
    "por palabra siempre que puedas. Lo unico que tienes que hacer es partirlo en "
    "bloques, ajustarlo a la horquilla de palabras si se sale, escribir las "
    "cifras con letras y colocar las anotaciones de voz. No lo 'mejores', no lo "
    "reescribas con tus palabras y no le cambies el tono.")


def _instruccion(transcript, metadatos, brief, anterior, opciones, correcciones,
                 idioma, previo=None, origen=None):
    """Texto completo que se le pasa al CLI por la entrada estandar.

    'previo' son los datos que devolvio el intento que se esta corrigiendo. No
    es lo mismo que 'anterior', que es el guion GUARDADO de una version pasada:
    este es de hace un minuto y el modelo no lo recuerda, porque cada llamada al
    CLI es una sesion limpia.

    """
    presupuesto, minimo, maximo = _horquilla(brief, idioma)
    nombre_idioma = _nombre_idioma(brief, idioma)
    por_bloque = int(brief.get("palabras_por_bloque") or 30)
    # CUANTOS bloques, y no solo de que tamano. Ver la regla 4: sin esto las dos
    # reglas de longitud no se pueden cumplir a la vez. Del brief si esta, y si
    # no calculado aqui, que es la misma cuenta que hace el brief -- los briefs
    # escritos antes de que existiera el campo no traen 'bloques_estimados'.
    bloques_previstos = int(brief.get("bloques_estimados") or 0) or max(
        1, int(round(presupuesto / max(1, por_bloque))))

    propio = bool(opciones.get("guion_propio"))
    # QUE REGLA DE REDACCION TOCA lo decide de donde viene el material, que es un
    # dato y no una adivinanza: un dosier no tiene orden que seguir.
    if propio:
        regla_redaccion = REGLA_GUION_PROPIO
    elif origen and (origen[0] if origen else None):
        regla_redaccion = REGLA_REDACCION_DOSIER
    else:
        regla_redaccion = REGLA_REDACCION
    partes = [
        "Eres el guionista de un canal de video documental. Escribes la "
        "narracion en off que se va a locutar: frases pensadas para el oido, "
        "claras y con ritmo, sin adornos de texto escrito.",
        "",
        ("== EL GUION QUE YA ESTA ESCRITO ==" if propio
         else "== MATERIAL DE PARTIDA (documentacion, NO texto para copiar) =="),
        f"Video de referencia: {metadatos.get('titulo', 'sin titulo')}"
        + (f" ({metadatos['canal']})" if metadatos.get("canal") else ""),
        f"Duracion original: {int(float(metadatos.get('duracion_s') or 0))} s, "
        f"{metadatos.get('palabras_transcript', 0)} palabras de transcript.",
        "",
        "Transcripcion con marcas de tiempo:",
        _transcript_legible(transcript, opciones["max_caracteres_transcript"]),
    ]

    # EL VIDEO DE ORIGEN, ADEMAS DEL DOSIER Y ANTES DEL BRIEF.
    #
    # Con las busquedas encendidas el dosier gana como material y el video que
    # se puso de referencia desaparecia del prompt entero: el guion se escribia
    # con ciento y pico fichas de datos sin haber leido nunca el video del que
    # salio el encargo. El resultado fue el que tenia que ser -- un guion que no
    # se parecia al de referencia ni en el asunto, ni en el vocabulario, ni en
    # por donde pasaba --, y desde fuera se ve como «la guia de tono pesa mas
    # que el video»: es que el video no pesaba nada.
    #
    # Y AQUI SE DICE QUE MANDA CADA COSA, que es lo que faltaba. La guia de tono
    # sale de OTROS videos del canal y describe la FORMA de la frase; este video
    # es el de ESTE encargo y fija el ASUNTO, el vocabulario y la profundidad.
    # Sin repartirlo, un canal con guia de tono de estafas escribe un video de
    # finanzas con vocabulario de estafas.
    trozos_origen, metadatos_origen = origen if origen else ([], {})
    if trozos_origen:
        titulo_origen = (metadatos_origen or {}).get("titulo") or ""
        partes.extend([
            "",
            "== EL VIDEO DE ORIGEN, TRANSCRITO ENTERO =="
            + (f"  ({titulo_origen})" if titulo_origen else ""),
            "Este es el video del que sale el encargo. El dosier de arriba trae "
            "los HECHOS; esto trae la FORMA: de que se habla, en que orden, "
            "cuanto se para en cada cosa, con que vocabulario y a que "
            "profundidad. Leelo entero antes de decidir la estructura.",
            "",
            "  - EL ASUNTO Y EL REGISTRO SON LOS DE ESTE VIDEO. Si aqui se "
            "habla de dinero, tu video habla de dinero y con esas palabras. La "
            "guia de tono del brief sale de OTROS videos del canal y dice como "
            "suena una frase suya --el trato, el humor, el ritmo--; este dice de "
            "que va ESTE video. Cuando parezcan contradecirse: la guia manda en "
            "la FORMA de la frase, este video manda en el ASUNTO, el "
            "vocabulario y la profundidad con la que se explica cada cosa.",
            "  - POR DONDE PASA ES UNA BUENA REFERENCIA. El orden en que este "
            "video explica las cosas ya funciona; uselo como punto de partida "
            "para tus paradas salvo que la instruccion de esta iteracion diga "
            "otra cosa.",
            "  - SUS HECHOS TAMBIEN SON TUYOS. Lo que este aqui y no en el "
            "dosier se cuenta igual: es material de este video.",
            "  - LO QUE NO SE COPIA son sus frases --se redacta de nuevo-- y su "
            "mobiliario de canal: presentarse, despedirse, el patrocinador, "
            "pedir suscripcion y remitir a otros videos suyos.",
            "",
            _transcript_legible(trozos_origen, MAX_CARACTERES_ORIGEN),
        ])

    partes.extend([
        "",
        "== BRIEF DEL USUARIO ==",
        brief.get("instrucciones") or "(sin brief)",
    ])

    # LOS PERSONAJES DEL CANAL, detras del brief: son del canal, como el tono,
    # y no de este video. Lo que se le pide al redactor esta escrito en
    # `_seccion_personajes`: presentarse una vez, cerrar si toca, y NUNCA
    # hablar de si mismo como de una mascota.

    # LA PRESENTACION Y LAS LLAMADAS A LA ACCION, pegadas a los personajes:
    # quien las dice sale justo arriba (si hay personaje; si no, las dice la voz
    # en off y ya esta). Van ANTES de redactar, y no cosidas despues, para que
    # el bloque anterior a cada una pueda prepararla (`pasos/cta.py`).
    #
    # El cierre de marca, si lo hay, es lo ULTIMO del video: la llamada del
    # cierre se corre un bloque para no pelearse con el por el mismo sitio.
    seccion_cta = cta.bloque_para_guion(opciones.get("cta"))
    if seccion_cta:
        partes.extend(["", seccion_cta])

    avisos = brief.get("avisos") or []
    if avisos:
        partes.append("")
        partes.append("Avisos del brief (tenlos en cuenta):")
        partes.extend(f"  - {aviso}" for aviso in avisos)

    if anterior:
        partes.extend([
            "",
            "== GUION ANTERIOR (iteracion previa) ==",
            f"Titulo: {anterior.get('titulo', '')}",
        ])
        previos = anterior.get("guion") or anterior.get("bloques") or []
        for bloque in previos:
            texto = bloque.get("texto", "")
            # la cuenta va de lo que se OYE: las anotaciones no se locutan, y si
            # contasen, el modelo creeria que un bloque anotado es mas largo de
            # lo que es y lo recortaria para cuadrar
            partes.append(f"{bloque.get('id', '?')} "
                          f"({marcas_tts.contar_palabras(texto)} pal.): {texto}")
        partes.append("")
        partes.append("Ese guion es el punto de partida: conserva lo que sigue "
                      "sirviendo y cambia solo lo que pide la instruccion de "
                      "esta iteracion.")
        # Esto no es un capricho de formato: de ese guion anterior ya cuelgan la
        # locucion grabada, una imagen por plano y un clip por plano. Un bloque
        # que conserva su id y su largo se puede reaprovechar entero; uno que
        # cambia de largo obliga a recortar los planos de ese tramo, y uno que
        # cambia de id lo obliga aunque diga exactamente lo mismo.
        partes.extend([
            "",
            "== LO QUE CUESTA CAMBIAR (leelo antes de reescribir) ==",
            f"De ese guion ya cuelgan la voz grabada y una imagen por plano. "
            f"Cada bloque que toques hay que volver a grabarlo, y si ademas "
            f"cambia de LARGO hay que recortar de nuevo los planos de ese tramo "
            f"y volver a dibujarlos. Por eso:",
            "  - Toca SOLO los bloques que pide la instruccion. Los demas se "
            "devuelven palabra por palabra como estan, sin mejorarlos.",
            "  - Manten el id de cada bloque y el orden. Un bloque con otro id "
            "es un bloque nuevo aunque diga lo mismo.",
            "  - Un bloque que cambies, devuelvelo con un largo PARECIDO al que "
            "tenia (arriba va su cuenta de palabras). Cambiar el tono de una "
            "frase no tiene por que cambiar lo que dura: si dura lo mismo, la "
            "voz encaja en el mismo hueco y los planos solo se recolocan.",
            "  - Si de verdad hace falta partir o juntar bloques, hazlo, pero "
            "sabiendo que eso si rehace ese tramo entero.",
        ])

    # LA ESTRUCTURA, COMO SECCION Y NO COMO REGLA NUMERADA.
    #
    # Las catorce reglas de abajo son de OFICIO: como se escribe una frase que
    # se locuta, que se deletrea, que va con letras. Ninguna dice de que va el
    # video, y con un dosier de ciento y pico hechos delante eso es justo lo que
    # falta: el guion salia correcto frase a frase y sin relato -- doce temas
    # mencionados y ninguno explicado, saltando de uno a otro sin cerrar.
    #
    # Va como seccion propia y pegada a la instruccion de la iteracion porque no
    # es una comprobacion que se pasa al final: es lo primero que hay que
    # decidir, antes de escribir la primera frase.
    partes.extend([
        "",
        "== COMO SE ESTRUCTURA ESTE VIDEO ==",
        "Un video no es una lista de datos buenos: es UN RELATO con unas pocas "
        "paradas, y cada parada existe porque la anterior la pide.",
        "",
        "  - POCOS TEMAS Y BIEN CONTADOS. Elige unas pocas paradas para todo el "
        "video --cuatro o seis, no doce-- y quedate ahi. Cada una se lleva "
        "varios bloques seguidos y se explica con calma: el dato, que significa "
        "y por que importa. Un tema que se despacha en un bloque y no vuelve no "
        "era un tema, era un dato suelto.",
        "  - EL ORDEN ES UN ARGUMENTO. Cada parada se apoya en la anterior: la "
        "primera deja una pregunta que contesta la segunda. Si puedes cambiar "
        "dos paradas de sitio y el video sigue funcionando igual, no hay "
        "relato: hay lista.",
        "  - NO SE RELLENA. El material trae mas hechos de los que caben, y ese "
        "es su trabajo: que puedas ELEGIR. Un hecho entra si empuja la parada en "
        "la que esta; si solo es curioso, se queda fuera. Vale mas un video con "
        "cinco temas explicados que uno con doce mencionados.",
        "  - Y NO SE SALTA. Antes de cambiar de parada, cierrala con una frase "
        "que remate lo que se acaba de contar. Cambiar de asunto a media idea es "
        "lo que hace que un video se sienta desordenado aunque cada frase por "
        "separado este bien.",
        "",
        "Decide esas paradas y su orden ANTES de escribir. El guion que "
        "entregues tiene que poder resumirse en esa lista.",
        # ATAR LAS PARADAS A LAS SECCIONES, o son dos reglas que se contradicen
        # sin que ninguna este mal: esta pide cuatro o seis paradas y la 11
        # admite hasta diez secciones. Es el mismo fallo que tenian la regla 3 y
        # la 4 con las palabras y los bloques: una regla por unidad sin decir
        # como se relaciona con la otra unidad es una intencion sin aritmetica.
        "",
        "Y ESAS PARADAS SON LAS SECCIONES DEL GUION: el bloque que abre cada "
        "una lleva \"abre_seccion\": true (regla 11). Una parada larga puede "
        "partirse en dos secciones; lo que no puede pasar es cambiar de parada "
        "sin abrir seccion, porque ahi es donde el motor pone el silencio que "
        "deja respirar el video.",
        "",
        "== INSTRUCCION DE ESTA ITERACION ==",
        opciones["prompt_general"] or
        "Redacta el guion siguiendo el brief, sin indicaciones adicionales.",
        "",
        "== REGLAS ==",
        f"1. {regla_redaccion}",
        f"2. Escribe en {nombre_idioma}.",
        f"3. Longitud total del guion: entre {minimo} y {maximo} palabras. "
        f"Cualquier cifra dentro de esa horquilla vale igual; no persigas un "
        f"numero exacto. El centro es {presupuesto} palabras y de esto depende "
        f"la duracion del video.",
        # LAS DOS REGLAS DE LONGITUD TIENEN QUE MULTIPLICAR AL PRESUPUESTO.
        #
        # Aqui ponia «bloques de unas N palabras» y no decia CUANTOS, asi que la
        # regla 3 (el total) y esta se contradecian sin que ninguna estuviera
        # mal: con bloques de 30 palabras, escribir diez da 300 y escribir siete
        # da 210, y las dos obedecen esta linea. Pasaba de verdad y por los dos
        # lados -- un guion de 302 palabras sobre un maximo de 269 (diez bloques
        # de 30) y otro de 268 hecho de trece bloques de 21, que cumple el total
        # rompiendo esta --, y el reintento automatico por horquilla tampoco lo
        # cerraba: se le decia «recorta a 269» sin decirle en cuantos trozos.
        #
        # El brief ya calculaba los bloques previstos y no llegaban hasta aqui.
        # Es el mismo fallo que tenia el catalogo visual con «dos planos por
        # sitio»: una regla por unidad sin el numero de unidades es una intencion
        # sin aritmetica, y no se puede obedecer.
        f"4. Parte el guion en unos {bloques_previstos} bloques de unas "
        f"{por_bloque} palabras cada uno: {bloques_previstos} x {por_bloque} "
        f"son unas {bloques_previstos * por_bloque} palabras, que es la "
        f"longitud pedida en la regla 3. Si te salen mas bloques, hazlos mas "
        f"cortos; el total manda sobre el tamano del bloque. Cada bloque es una "
        f"idea que se lee de un tiron. Numeralos B001, B002, B003 en orden. Si "
        f"conservas un bloque del guion anterior practicamente igual, mantenle "
        f"su id.",
        # Esta regla existe por un fallo concreto: el guion salia sin tildes.
        # Todo lo que hay escrito en este Estudio -- codigo, instrucciones,
        # comentarios -- va sin tildes por compatibilidad de consolas, y el
        # modelo contesta en el registro en el que se le pregunta. El guion no
        # se lee: se LOCUTA, asi que una tilde que falta no es una falta que
        # nadie ve, es una palabra mal pronunciada en el video.
        f"5. ORTOGRAFIA COMPLETA de {nombre_idioma}, con TODAS sus tildes, "
        "diereses y enes. Este texto lo lee un sintetizador de voz: sin tilde "
        "dice «publico» donde pone «publicó» y «esta» donde pone «está», y eso "
        "no se arregla despues. Da igual como este escrita esta instruccion: "
        "el guion va con su ortografia entera.",
        "6. Solo el texto que se locuta: nada de acotaciones, indicaciones de "
        "camara, nombres de seccion ni marcas tipo [musica]."
        + (" La unica excepcion son las anotaciones de voz que se explican "
           "debajo, que no se locutan: le dicen al sintetizador donde parar."
           if opciones["anotaciones_voz"] else ""),
        "7. Respeta cifras, fechas y nombres propios del material. No inventes "
        "datos que no esten en el.",
        # Esta regla existe por un fallo concreto y oido: un guion en ingles con
        # «Spain, May 2024» se locuto «may dos mil veinticuatro». Una cifra no es
        # una palabra: es algo que alguien tiene que expandir, y quien la expande
        # no es quien escribio la frase.
        "8. TODO CON LETRAS. Ni un digito, ni un simbolo, en ningun bloque. "
        "Esto se locuta, y una cifra la pronuncia el sintetizador como el "
        "decida: un guion en ingles con «May 2024» dijo «may dos mil "
        "veinticuatro». Escribe los anos como se dicen en el idioma del guion "
        "(«twenty twenty-four», «dos mil veinticuatro»), y con letras tambien "
        "los numeros, las fechas, los porcentajes, el dinero, los ordinales y "
        "las horas: «treinta millones», «el dos por ciento», «dos millones de "
        "dolares», «seis de cada diez». Nada de %, $, &, +, #.",
        # Medido, porque la intuicion falla aqui: separar las letras a mano
        # («I N G») deletrea en ingles pero NO en castellano -- misma duracion
        # que la sigla pelada--, y los puntos («I.N.G.») casi tampoco. La unica
        # forma que deletrea en los dos idiomas es <spell>, y ademas lo hace con
        # el nombre de las letras del idioma del guion.
        #
        # Y la regla se reescribio entera el 24-08 despues de oir un video: de
        # una lista de seis nombres de malware, tres salieron deletreados letra
        # a letra y tres leidos, sin patron. La causa es que «va en mayusculas»
        # se parece mucho a «es una sigla». Ahora la regla se dice por la
        # PRONUNCIACION -- se deletrea lo que no se puede pronunciar -- y ademas
        # el motor la impone: `marcas_tts.sanear` quita el <spell> de lo que sea
        # pronunciable, se pida como se pida (`marcas_tts.es_inicialismo`).
        "9. DELETREAR ES LA EXCEPCION, NO LA NORMA. La pregunta no es si va en "
        "mayusculas: es si un locutor lo PRONUNCIARIA o lo diria letra a letra.\n"
        "   - Se LEE tal cual, sin ninguna etiqueta, todo lo que se puede "
        "pronunciar: los nombres propios y las marcas (Lumma, Vidar, Mega, "
        "Raccoon, RedLine, Alex Host), y las siglas que se dicen como una "
        "palabra (NASA, OTAN, UNICEF, CISA).\n"
        "   - Solo va en <spell> lo que de verdad se dice letra a letra, y son "
        "casi siempre de dos a cuatro letras sin forma de silaba: "
        "<spell>FBI</spell>, <spell>MFA</spell>, <spell>DNS</spell>, "
        "<spell>URL</spell>, <spell>IP</spell>.\n"
        "   - Ante la duda, NO lo deletrees. Un nombre leido de mas suena "
        "normal; un nombre deletreado suena a error, y ademas alarga el plano: "
        "una lista de seis nombres deletreados ocupa el doble de video.\n"
        "   - UNA SIGLA POR ETIQUETA, nunca una frase: <spell>AT and T</spell> "
        "se locuta «AT, A-N-D-T» porque deletrea tambien el 'and'. Lo correcto "
        "es <spell>AT</spell> and <spell>T</spell>.\n"
        "   - No las separes con espacios ni con puntos («I N G», «I.N.G.»): "
        "eso no deletrea, solo ensucia el texto. Y si el guion la explica, "
        "mejor con palabras: «doble factor» antes que «2FA».",
        # Un nombre compuesto pegado no es una palabra de ningun idioma, asi que
        # el sintetizador se inventa como suena. Medido: «AlexHost» y
        # «SmokeLoader» salieron irreconocibles en un video real, y con ellos se
        # perdio de que se estaba hablando. Se comprueba, ver comun.revisar_compuestos.
        "10. LOS NOMBRES PEGADOS, SEPARADOS. Un nombre propio escrito de una "
        "pieza con una mayuscula dentro --AlexHost, SmokeLoader, RedLine, "
        "StealC-- lo lee un sintetizador que no lo conoce, asi que se inventa "
        "una pronunciacion y no se entiende ni de que hablas. Escribelos "
        "SEPARADOS, que ademas es como se dicen: «Alex Host», «Smoke Loader», "
        "«Red Line», «Steal C». Los que ya son una palabra sola (Lumma, Vidar, "
        "Mega) se quedan como estan.",
        # Las secciones no son un capricho de formato: la voz se graba por
        # secciones dentro de un mismo contexto, y si un dia hay que regrabar
        # una, la costura cae justo en su frontera. Por eso se corta donde el
        # relato ya cambia de asunto: ahi un cambio de entonacion se lee como
        # intencionado y no como un empalme.
        "11. MARCA LAS SECCIONES. Pon \"abre_seccion\": true en el bloque que "
        "empieza un tramo nuevo del relato -- o sea, en cada una de las paradas "
        "que decidiste arriba (COMO SE ESTRUCTURA ESTE VIDEO). Se cambia de "
        "seccion cuando se cambia de asunto, no cuando se cambia de frase. El "
        "primer bloque siempre la lleva. Piensa en "
        "capitulos de un documental: el gancho, la entrada, quien lo hizo, que "
        "se llevaron, las consecuencias, el cierre. En un video de dos minutos "
        "salen cuatro o cinco; en uno de quince, ocho o diez COMO MUCHO. "
        "Pasarse es peor que quedarse corto. Y ESE CORTE SE OYE: el motor deja "
        "un silencio al final del bloque anterior, asi que ese bloque tiene que "
        "REMATAR el tema que cierra, no enlazar con el siguiente.",
        # LA REGLA DEL RELATO QUE AVANZA. Nacio de un video real: pasado el
        # minuto dos, el guion volvia a presentar el caso --el numero de
        # afectados, quienes eran los atacantes-- con el mismo tono de
        # revelacion que la entrada, como si el espectador acabara de llegar. No
        # era que empezara de nuevo: era que un dato ya dado se volvia a dar
        # como si fuera nuevo, y eso desactiva el efecto de las dos veces.
        "12. UNA COSA SE CUENTA UNA VEZ. Un dato, un nombre o una cifra que ya "
        "ha salido NO se vuelve a presentar como si fuera nuevo: se le llama "
        "por su nombre corto y se sigue. Nada de «resulta que...», «lo que casi "
        "nadie sabe es que...» ni «y aqui viene lo interesante» sobre algo que "
        "ya contaste. El guion AVANZA: cada bloque anade algo que el anterior "
        "no tenia. Si necesitas recordar un dato para lo que viene, recuerdalo "
        "en tres palabras y de pasada, nunca con el tono con el que se revela "
        "algo por primera vez.",
        "13. EL GANCHO ES UNO Y VA AL PRINCIPIO. El tono de entrada --la "
        "promesa, la sorpresa, el «esto es mas grande de lo que parece»-- se "
        "usa en los dos primeros bloques y no vuelve a aparecer. A mitad de "
        "video ese tono no promete nada: repite, y se nota.",
        "14. El titulo es para el video, no para el guion: corto y concreto.",
    ])

    if opciones["anotaciones_voz"]:
        partes.append("")
        partes.append(marcas_tts.instrucciones(
            con_emocion=opciones["emocion_en_voz"]))

    if correcciones:
        # EL TEXTO QUE SE CORRIGE VA DELANTE DE LA CORRECCION. Sin esto, las
        # correcciones eran ordenes imposibles: «recorta a 2600 palabras», «pon
        # las tildes sin cambiar nada mas» -- de un texto que el modelo no tiene
        # a la vista, porque el CLI arranca una sesion nueva en cada llamada.
        # Con las manos vacias solo se puede hacer una cosa, que es escribir
        # otro guion, y ahi es donde 88 bloques se convirtieron en 120.
        bloques_previos = (previo or {}).get("_bloques") or []
        if bloques_previos:
            palabras_previas = sum(marcas_tts.contar_palabras(b["texto"])
                                   for b in bloques_previos)
            partes.extend([
                "",
                f"== LO QUE DEVOLVISTE EN EL INTENTO ANTERIOR "
                f"({len(bloques_previos)} bloques, {palabras_previas} palabras) ==",
            ])
            partes.extend(
                f"{b.get('id', '?')} ({marcas_tts.contar_palabras(b['texto'])} "
                f"pal.): {b['texto']}" for b in bloques_previos)
            partes.extend([
                "",
                "PARTE DE ESE TEXTO. No es un guion nuevo: es ese mismo con las "
                "correcciones de abajo hechas. Lo que las correcciones no "
                "nombran se devuelve palabra por palabra como esta, con su "
                "mismo id y en el mismo orden -- tampoco lo mejores.",
            ])
        partes.extend(["", "== CORRECCIONES AL INTENTO ANTERIOR =="])
        partes.extend(f"  - {linea}" for linea in correcciones)

    ejemplo = ('{"titulo": "titulo del video", "bloques": [{"id": "B001", '
               '"texto": "texto locutado del primer bloque"}, '
               '{"id": "B002", "texto": "..."}]}')
    if opciones["anotaciones_voz"]:
        # El ejemplo lleva la anotacion puesta a proposito: un modelo copia la
        # forma del ejemplo antes que la regla, y esta es exactamente la pausa
        # que se echaba en falta -- la del gancho a la entrada del documental.
        ejemplo = ('{"titulo": "titulo del video", "bloques": [{"id": "B001", '
                   '"texto": "el gancho, que cierra aqui.<break time=\\"900ms\\"/>", '
                   '"abre_seccion": true}, '
                   '{"id": "B002", "texto": "y aqui empieza el documental.", '
                   '"abre_seccion": true}]}')
    if opciones.get("personajes"):
        # con personaje, el ejemplo ensena la marca puesta en la presentacion:
        # un modelo copia la forma del ejemplo antes que la regla
        ejemplo = ('{"titulo": "titulo del video", "bloques": [{"id": "B001", '
                   '"texto": "el gancho, que cierra aqui.<break time=\\"900ms\\"/>", '
                   '"abre_seccion": true}, '
                   '{"id": "B002", "texto": "Soy Nombre y en este video te voy a '
                   'contar...", "personaje": true, "abre_seccion": true}, '
                   '{"id": "B003", "texto": "y aqui sigue el documental."}]}')
    # LA CUENTA, OTRA VEZ Y AL FINAL. No es repetir la regla 3 por insistir: la
    # ULTIMA parte de un prompt es la que mas pesa --esta medido en este repo
    # con el feedback de un plano-- y la longitud es lo unico
    # del guion que arrastra dinero: un guion un 27 % largo son 27 % mas de
    # segundos de TTS, mas planos y mas imagenes.
    #
    # Y va como una COMPROBACION, no como una regla. «Escribe entre X e Y» ya
    # esta dicho arriba y se olvida por el camino; «cuenta y recorta antes de
    # entregar» es algo que se puede hacer justo antes de responder.
    partes.extend([
        "",
        "== ANTES DE ENTREGAR, CUENTA ==",
        f"Suma las palabras de todos los bloques. Tienen que estar entre "
        f"{minimo} y {maximo}, en unos {bloques_previstos} bloques de unas "
        f"{por_bloque}. Si te has pasado, RECORTA antes de responder: quita "
        f"frases enteras que no aporten un hecho nuevo, no acortes todas un "
        f"poco. Si te has quedado corto, desarrolla los hechos del material. "
        f"Esta cuenta manda sobre cualquier otra cosa que te apetezca contar.",
    ])
    partes.extend([
        "",
        "== FORMATO DE SALIDA ==",
        "Responde UNICAMENTE con un objeto JSON valido, sin texto antes ni "
        "despues y sin vallas de markdown, con esta forma exacta:",
        ejemplo,
    ])
    return "\n".join(partes)


# ------------------------------------------------------------------ CLI

def _localizar_claude():
    """Ruta del ejecutable del CLI de Claude."""
    return cli_claude.localizar("el paso de guion")


TiempoAgotado = cli_claude.TiempoAgotado
LimiteAgotado = cli_claude.LimiteAgotado

#: Los fallos que NO se reintentan, y por el mismo motivo los dos: el segundo
#: intento no puede salir mejor que el primero. Un timeout volveria a vencer y
#: un cupo agotado seguira agotado dentro de un segundo. Gastar los reintentos
#: en ellos no cuesta solo tiempo: hace que el error que se guarda sea el del
#: ULTIMO intento, o sea el mismo mensaje sin la pista de que ya se sabia.
SIN_REINTENTO = (TiempoAgotado, LimiteAgotado)


def tiempo_max_de(opciones):
    """Techo de UNA llamada: el que se haya fijado a mano, o el del esfuerzo."""
    return cli_claude.tiempo_max(opciones["esfuerzo"], base_s=TIEMPO_BASE_S,
                                 modelo=opciones["modelo"],
                                 pedido_s=opciones.get("tiempo_max_s") or 0)


def _llamar_claude(instruccion, opciones, cwd, avance=None):
    """Lanza el CLI en headless y devuelve (texto de la respuesta, sobre JSON).

    La orden la arma cli_claude, que es el unico sitio del Estudio que sabe
    construirla. Esta funcion sigue existiendo con este nombre y esta firma
    porque el medidor de coste la engancha POR NOMBRE (nucleo/coste.py:724) y
    porque las pruebas sustituyen aqui el CLI por un doble.
    """
    return cli_claude.ejecutar(
        instruccion,
        modelo=opciones["modelo"], esfuerzo=opciones["esfuerzo"],
        cwd=cwd, tiempo_max_s=opciones.get("tiempo_max_s") or 0,
        base_tiempo_s=TIEMPO_BASE_S,
        sistema=SISTEMA, herramientas_vetadas=HERRAMIENTAS_VETADAS,
        extra=["--no-session-persistence"], avance=avance,
        para="la redaccion del guion",
        consejos_extra=[f"baja 'max_caracteres_transcript' (ahora "
                        f"{opciones['max_caracteres_transcript']}) para mandar "
                        f"menos material"])


def _extraer_json(texto):
    """Saca el objeto JSON de la respuesta aunque venga envuelto."""
    crudo = texto.strip()
    if crudo.startswith("```"):
        crudo = re.sub(r"^```[A-Za-z]*\s*", "", crudo)
        crudo = re.sub(r"\s*```\s*$", "", crudo)
    try:
        return json.loads(crudo)
    except ValueError:
        pass
    bloque = _primer_objeto(crudo)
    if bloque is None:
        raise RuntimeError(f"la respuesta no contiene ningun JSON: {texto[:400]}")
    try:
        return json.loads(bloque)
    except ValueError as fallo:
        raise RuntimeError(
            f"el JSON de la respuesta esta mal formado ({fallo}): {bloque[:400]}") from fallo


def _primer_objeto(texto):
    """Primer objeto {...} equilibrado del texto, ignorando llaves entrecomilladas."""
    inicio = texto.find("{")
    if inicio < 0:
        return None
    nivel = 0
    dentro = False
    escapado = False
    for posicion in range(inicio, len(texto)):
        caracter = texto[posicion]
        if dentro:
            if escapado:
                escapado = False
            elif caracter == "\\":
                escapado = True
            elif caracter == '"':
                dentro = False
            continue
        if caracter == '"':
            dentro = True
        elif caracter == "{":
            nivel += 1
        elif caracter == "}":
            nivel -= 1
            if nivel == 0:
                return texto[inicio:posicion + 1]
    return None


# ------------------------------------------------------------------- bloques

def _normalizar_bloques(datos):
    """Lista de bloques {id, texto} a partir de lo que haya contestado el modelo."""
    if not isinstance(datos, dict):
        raise RuntimeError("la respuesta no es un objeto JSON con titulo y bloques")
    crudos = datos.get("bloques")
    if not isinstance(crudos, list) or not crudos:
        crudos = datos.get("guion")
    if not isinstance(crudos, list) or not crudos:
        raise RuntimeError("la respuesta no trae ningun bloque de guion")

    propuestos = []
    for elemento in crudos:
        if isinstance(elemento, str):
            propuestos.append({"id": "", "texto": elemento.strip()})
        elif isinstance(elemento, dict):
            texto = elemento.get("texto") or elemento.get("text") or ""
            propuestos.append({"id": str(elemento.get("id") or "").strip().upper(),
                               "texto": " ".join(str(texto).split()),
                               "abre_seccion": bool(elemento.get("abre_seccion")),
                               # SI EL PERSONAJE DEL CANAL DA LA CARA en este
                               # bloque (se presenta, cierra). Lo marca el
                               # redactor y lo lee el catalogo visual, que es
                               # quien lo pone en el plano.
                               "personaje": bool(elemento.get("personaje"))})
        else:
            raise RuntimeError(f"bloque de guion con forma inesperada: {elemento!r}")

    propuestos = [b for b in propuestos if b["texto"]]
    if not propuestos:
        raise RuntimeError("todos los bloques del guion han venido vacios")

    ids = [b["id"] for b in propuestos]
    validos = all(re.fullmatch(r"B\d{3}", i) for i in ids) and len(set(ids)) == len(ids)
    if not validos:
        # renumerar es la unica forma de garantizar ids unicos y con formato;
        # se pierde la continuidad con el guion anterior, pero no la coherencia
        for numero, bloque in enumerate(propuestos, start=1):
            bloque["id"] = f"B{numero:03d}"
    return propuestos


def _aplicar_marcas(bloques, opciones, avisos=None, idioma="es"):
    """Deja el texto de cada bloque en un estado seguro para locutarlo.

    Es el unico sitio por el que pasa TODO texto de bloque antes de guardarse:
    lo que escribe el modelo, lo que traduce a otro idioma y lo que corrige una
    persona a mano. Tiene que ser uno solo, porque el fallo que evita no perdona:
    una etiqueta que Cartesia no reconoce NO da error, se LOCUTA, y el video
    acaba diciendo «menor que pausa larga barra».

    Con las anotaciones apagadas no basta con no pedirlas: se quitan. El modelo
    las ha visto en el guion anterior y las repite por inercia.

    Y AQUI SE REPONEN LAS TILDES SEGURAS, por el mismo motivo por el que se
    sanean las marcas: es el embudo por el que pasa todo, y una tilde que falta
    tampoco da error --se locuta mal--. Solo se toca lo que `comun.SIN_TILDE_ES`
    garantiza (palabras que sin tilde no existen), asi que esto no reescribe a
    nadie: pone la tilde que ya tenia que estar. Vale igual para lo que teclea
    una persona a mano, que tambien se locuta.

    Lo repuesto SE CUENTA en los avisos. Corregir en silencio es la forma de que
    nadie se entere el dia que la lista se equivoque.
    """
    quita = not opciones.get("anotaciones_voz")
    repuestas = []
    for bloque in bloques:
        if quita:
            bloque["texto"] = marcas_tts.limpiar(bloque["texto"])
        else:
            bloque["texto"] = marcas_tts.sanear(bloque["texto"], avisos)
        bloque["texto"], cambios = comun.reponer_tildes(bloque["texto"], idioma)
        repuestas.extend(cambios)
    if repuestas and avisos is not None:
        muestra = list(dict.fromkeys(f"'{mal}' -> '{bien}'"
                                     for mal, bien in repuestas))
        avisos.append(
            f"repuestas {len(repuestas)} tilde(s) que faltaban, que esto se "
            f"locuta: " + ", ".join(muestra[:8])
            + (f" y {len(muestra) - 8} mas" if len(muestra) > 8 else ""))
    vivos = [b for b in bloques if b["texto"].strip()]

    # La pausa del gancho es la unica que no se deja a criterio del redactor.
    # El primer bloque esta escrito para rematar y quedarse colgando, y sin aire
    # detras el segundo le pisa el final: el recurso no funciona. Se pone aqui,
    # DESPUES de sanear, y solo si no la puso ya el modelo.
    pausa = int(opciones.get("pausa_gancho_ms") or 0)
    if not quita and pausa > 0 and len(vivos) > 1:
        vivos[0]["texto"] = marcas_tts.pausa_al_final(vivos[0]["texto"], pausa)
    return vivos


def _aire_entre_secciones(bloques, opciones):
    """Silencio en el bloque que CIERRA cada tramo, antes de cambiar de asunto.

    Un video que salta de tema sin pausa se oye como una lista leida: sin aire
    delante, la primera frase del tema nuevo entra pegada al remate del
    anterior y no hay forma de oir que ha cambiado el capitulo. La pausa no se
    deja al criterio del redactor por lo mismo que la del gancho: es
    estructura, y si depende de que se acuerde, la mitad de las veces no esta.

    Va DESPUES de fijar las secciones y no dentro de `_aplicar_marcas` porque
    el flag todavia se toca despues: el primer bloque siempre abre seccion.
    Ponerla antes seria dejar un silencio delante de un corte que ya no existe.

    Con las anotaciones apagadas no se pone: no hay forma de decir un silencio
    dentro del texto, y `_aplicar_marcas` las quitaria a continuacion.
    """
    ms = int(opciones.get("pausa_seccion_ms") or 0)
    if ms <= 0 or not opciones.get("anotaciones_voz"):
        return 0
    puestas = 0
    for indice, bloque in enumerate(bloques[1:], start=1):
        if not bloque.get("abre_seccion"):
            continue
        cierra = bloques[indice - 1]
        antes = cierra["texto"]
        cierra["texto"] = marcas_tts.pausa_al_final(antes, ms)
        puestas += int(cierra["texto"] != antes)
    return puestas


def _problemas(bloques, palabras, brief, opciones, idioma):
    """Motivos por los que merece la pena volver a pedir el guion."""
    _, minimo, maximo = _horquilla(brief, idioma)
    motivos = []

    # la horquilla ya trae su propio margen: fuera de ella el guion no sirve,
    # asi que aqui no se anade holgura extra sobre la holgura
    # La correccion lleva la CUENTA hecha, igual que la regla 4. Decir «recorta
    # a 269» sin decir en cuantos trozos es el mismo hueco que dejaba la regla:
    # el guion volvia con el mismo numero de bloques y la misma longitud.
    presupuesto = _horquilla(brief, idioma)[0]
    por_bloque = int(brief.get("palabras_por_bloque") or 30)
    previstos = int(brief.get("bloques_estimados") or 0) or max(
        1, int(round((presupuesto or maximo or 1) / max(1, por_bloque))))
    reparto = (f"; son unos {previstos} bloques de unas {por_bloque} palabras y "
               f"has escrito {len(bloques)}")
    if minimo and palabras < minimo:
        motivos.append(f"el guion se queda en {palabras} palabras y el minimo de "
                       f"la horquilla son {minimo}: desarrolla mas los hechos "
                       f"del material{reparto}")
    if maximo and palabras > maximo:
        motivos.append(f"el guion se va a {palabras} palabras y el maximo de la "
                       f"horquilla son {maximo}: recorta sin perder "
                       f"hechos{reparto}")

    # Pasarse de pausas no se ve bloque a bloque, solo mirando el guion entero,
    # y estropea justo lo que se queria mejorar: cada <break> parte la
    # generacion, asi que muchos devuelven el sonido de lista leida que la toma
    # continua existe para evitar.
    if opciones.get("anotaciones_voz"):
        motivos.extend(marcas_tts.revisar_conjunto(bloques))

    # Una cifra no es una palabra: es algo que hay que expandir, y quien la
    # expande es el sintetizador, no quien escribio la frase. Un guion en ingles
    # con «May 2024» se locuto «may dos mil veinticuatro». Se detecta en un
    # milisegundo y arreglarlo despues de grabar cuesta la toma entera.
    ficha_cifras = comun.revisar_cifras(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques))
    if ficha_cifras["hay_cifras"]:
        motivos.append(
            f"el guion trae {ficha_cifras['cuantos']} cifra(s) o simbolo(s) sin "
            f"escribir con letras: {', '.join(ficha_cifras['ejemplos'])}. Esto se "
            f"locuta, y una cifra la pronuncia el sintetizador como el decida (un "
            f"guion en ingles con «May 2024» dijo «may dos mil veinticuatro»). "
            f"Devuelvelo con TODO escrito con letras, en el idioma del guion, sin "
            f"cambiar nada mas")

    # Un nombre propio pegado no es una palabra de ningun idioma, asi que el
    # sintetizador se inventa como suena. Medido en un video real: «AlexHost» y
    # «SmokeLoader» salieron irreconocibles, y con ellos se perdio de que se
    # estaba hablando. Se detecta en un milisegundo; arreglarlo despues de
    # grabar cuesta la toma.
    ficha_compuestos = comun.revisar_compuestos(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques))
    if ficha_compuestos["hay_compuestos"]:
        motivos.append(
            f"el guion trae {ficha_compuestos['cuantos']} nombre(s) propio(s) "
            f"escrito(s) de una pieza con una mayuscula dentro: "
            f"{', '.join(ficha_compuestos['ejemplos'])}. Esto lo locuta un "
            f"sintetizador que no los conoce, asi que se inventa la "
            f"pronunciacion y no se entiende ni de que se habla. Devuelvelo con "
            f"esos nombres SEPARADOS, sin cambiar nada mas")

    # UN GUION ESCRITO ENTERO SIN TILDES si hay que pedirlo otra vez: no es un
    # guion con faltas, es un guion que se va a PRONUNCIAR mal de arriba abajo y
    # no hay lista de palabras que lo salve.
    #
    # Lo que ya NO llega hasta aqui son las faltas sueltas: las de
    # `comun.SIN_TILDE_ES` vienen repuestas de `_aplicar_marcas`, que es donde
    # tienen que arreglarse. Cuando esto estaba al reves --una palabra suelta
    # obligaba a rehacer el guion entero-- costo lo que cuenta la cabecera del
    # modulo: 2585 palabras buenas cambiadas por 3799 malas.
    ficha = comun.revisar_tildes(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques), idioma)
    if ficha["sin_tildes"]:
        motivos.append(
            f"el guion viene ENTERO sin tildes y esto se locuta, no se lee: un "
            f"sintetizador dice 'publico' donde el texto queria 'publico' con "
            f"tilde. Solo el {ficha['proporcion'] * 100:.1f} % de las palabras "
            f"lleva algun diacritico, y en un guion narrado en {idioma} lo "
            f"normal esta entre el 8 % y el 14 %. Vuelve a escribirlo con la "
            f"ortografia completa del idioma")
    return motivos


def _avisos(bloques, palabras, brief, idioma):
    """Lo que hay que contarle al usuario aunque el guion se de por bueno."""
    _, minimo, maximo = _horquilla(brief, idioma)
    avisos = []
    if minimo and palabras < minimo:
        avisos.append(f"{palabras} palabras, por debajo del minimo ({minimo})")
    if maximo and palabras > maximo:
        avisos.append(f"{palabras} palabras, por encima del maximo ({maximo})")
    largos = [b["id"] for b in bloques if marcas_tts.contar_palabras(b["texto"]) > 80]
    if largos:
        avisos.append(f"bloques demasiado largos para un plano: "
                      + ", ".join(largos))
    avisos.extend(marcas_tts.revisar_conjunto(bloques))
    cifras = comun.revisar_cifras(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques))
    if cifras["hay_cifras"]:
        avisos.append(f"hay cifras o simbolos sin escribir con letras "
                      f"y esto se locuta: " + ", ".join(cifras["ejemplos"]))
    compuestos = comun.revisar_compuestos(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques))
    if compuestos["hay_compuestos"]:
        avisos.append("hay nombres propios pegados y el sintetizador se inventa "
                      "como suenan: " + ", ".join(compuestos["ejemplos"]))
    # Si despues de los reintentos sigue habiendo palabras sin tilde, se dice.
    # Callarlo aqui es dejar que se grabe la voz de un texto que se va a
    # pronunciar mal, que es lo que costo detectar la primera vez.
    ficha = comun.revisar_tildes(
        " ".join(marcas_tts.limpiar(b["texto"]) for b in bloques), idioma)
    if ficha["sin_tildes"]:
        avisos.append(f"hay palabras sin tilde y esto se locuta: "
                      + (", ".join(ficha["ejemplos"])
                         or f"solo el {ficha['proporcion'] * 100:.1f} % de las "
                            f"palabras lleva diacritico"))
    return avisos


# ------------------------------------------------------------------ redaccion

def _pedir(instruccion, opciones, trabajo, avisar, tramo, mensaje, prevision,
           nombre_fichero, comprobar):
    """Una peticion al CLI con sus reintentos, su reloj y sus correcciones.

    'instruccion' recibe (correcciones, previo): las correcciones que hay que
    hacerle al intento anterior y LO QUE DEVOLVIO ese intento. Las dos cosas
    juntas, porque una correccion sin el texto que corrige no se puede obedecer:
    cada llamada al CLI es una sesion nueva y el modelo no recuerda lo que
    escribio hace un minuto. Se le decia «devuelvelo sin cambiar nada mas» sin
    ensenarle el «lo», y volvia otro guion distinto -- de 88 bloques a 120.

    'comprobar' recibe los datos que devolvio el modelo y responde con la lista
    de motivos para volver a pedirlo (vacia si el resultado vale). Devuelve
    (datos, sobre, intentos, correcciones_pendientes).
    """
    desde, hasta = tramo
    # Cada intento se queda con su propio trozo del tramo. Con un tramo comun,
    # un reintento pintaba la barra al 95% y la devolvia al 5%: decir que casi
    # ha terminado y volver atras es la misma mentira que el 10% fijo de antes,
    # solo que al reves. Asi el progreso solo sube, y lo que se ve es que la
    # segunda pasada arranca donde acabo la primera.
    posibles = opciones["reintentos"] + 1
    ancho = (hasta - desde) / posibles

    def subtramo(intento):
        principio = desde + ancho * (intento - 1)
        return principio, principio + ancho

    correcciones = []
    previo = None
    # EL MEJOR INTENTO, NO EL ULTIMO. Un reintento es una apuesta: se paga otra
    # llamada esperando algo mejor, y a veces sale peor. El 27-08-2026 salio
    # peor de la unica forma que importa --un guion dentro de la horquilla
    # cambiado por otro un 46 % mas largo-- y se entrego el malo, porque aqui
    # solo se guardaba el ultimo. Lo que se guarda ahora es el que menos
    # problemas trae, y si el entregado no es el ultimo se dice en los avisos.
    mejor = None
    motivos_mejor = None
    for intento in range(1, posibles + 1):
        intento_desde, intento_hasta = subtramo(intento)
        instruccion_actual = instruccion(correcciones, previo)
        comun.escribir_texto(
            os.path.join(trabajo, f"{nombre_fichero}_{intento}.txt"),
            instruccion_actual)

        avance = estadisticas.Avance(
            avisar, intento_desde, intento_hasta, prevision,
            f"{mensaje} (intento {intento})")
        avance.arrancar()
        try:
            texto, sobre = _llamar_claude(instruccion_actual, opciones, trabajo, avance)
        except RuntimeError as fallo:
            tardado = avance.parar()
            reintentable = (not isinstance(fallo, SIN_REINTENTO)
                            and _puede_reintentar(intento, tardado, opciones))
            if not reintentable:
                if mejor is None:
                    raise
                # ya hay un resultado utilizable de un intento anterior: mejor
                # entregarlo con el aviso que tirar el paso entero
                return mejor[0], mejor[1], intento, list(motivos_mejor) + [
                    f"el intento {intento} fallo ({fallo}); se entrega el "
                    f"intento {mejor[2]}"]
            correcciones = []
            previo = None
            avisar(intento_hasta,
                   f"reintentando tras fallar en {int(tardado)} s: {fallo}")
            continue
        tardado = avance.parar()

        comun.escribir_json(
            os.path.join(trabajo, f"respuesta_{nombre_fichero}_{intento}.json"), sobre)
        avisar(intento_hasta, "revisando lo que ha devuelto")
        try:
            datos = _extraer_json(texto)
            motivos = comprobar(datos)
        except RuntimeError as fallo:
            if not _puede_reintentar(intento, tardado, opciones):
                if mejor is None:
                    raise
                return mejor[0], mejor[1], intento, list(motivos_mejor) + [
                    f"el intento {intento} devolvio algo ilegible ({fallo}); se "
                    f"entrega el intento {mejor[2]}"]
            correcciones = [f"la respuesta anterior no se pudo leer ({fallo}). "
                            "Devuelve solo el objeto JSON pedido."]
            previo = None
            continue

        if mejor is None or len(motivos) < len(motivos_mejor):
            mejor, motivos_mejor = (datos, sobre, intento), motivos
        if not motivos or not _puede_reintentar(intento, tardado, opciones):
            avisar(hasta, "revisando lo que ha devuelto")
            pendientes = list(motivos_mejor)
            if mejor[2] != intento:
                pendientes.append(
                    f"se entrega el intento {mejor[2]} y no el {intento}: el "
                    f"ultimo volvio con mas problemas ({len(motivos)} frente a "
                    f"{len(motivos_mejor)})")
            return mejor[0], mejor[1], intento, pendientes
        correcciones = motivos
        previo = datos
        avisar(intento_hasta, f"rehaciendo: {motivos[0][:80]}")
    # el bucle siempre sale por un return o por una excepcion; llegar aqui solo
    # es posible si alguien cambia la condicion de reintento, y entonces vale
    # mas devolver lo mejor que hubiera que reventar sin explicacion
    if mejor is None:
        raise RuntimeError("el paso de guion no llego a obtener ninguna respuesta")
    return mejor[0], mejor[1], posibles, list(motivos_mejor)


def umbral_reintento_de(opciones):
    """Cuanto puede haber tardado una llamada para que valga la pena repetirla.

    Escala con el ajuste por el mismo motivo que el techo de tiempo: con un
    umbral fijo de 120 s, cualquier esfuerzo por encima de 'low' lo superaba
    siempre y desactivaba los reintentos SIN DECIRLO. El usuario subia el
    esfuerzo esperando mas calidad y perdia, sin enterarse, las correcciones
    automaticas por copias literales y por horquilla de palabras.
    """
    pedido = opciones.get("umbral_reintento_s") or 0
    if pedido > 0:
        return int(pedido)
    return int(round(UMBRAL_REINTENTO_BASE_S
                     * cli_claude.factor(opciones["modelo"], opciones["esfuerzo"])))


def _puede_reintentar(intento, tardado, opciones):
    """Hay reintentos de sobra Y la llamada anterior no fue una espera larga.

    Reintentar una llamada que ya tardo mucho multiplica la espera del usuario
    sin darle nada a cambio: es mejor devolver lo que hay, o el error, y que
    decida el.
    """
    if intento > opciones["reintentos"]:
        return False
    return tardado <= umbral_reintento_de(opciones)


# --------------------------------------------------------------------- salida

def ejecutar(proyecto, params, avisar):
    """Redacta el guion, y deje o no resultado, anota lo que costo intentarlo.

    Las ejecuciones que fallan se anotan igual que las que salen bien. Antes solo
    se guardaba lo que terminaba, asi que una combinacion que siempre vence el
    plazo no dejaba ni rastro en el historico y el recomendador no podia avisar
    de ella nunca: justo el dato mas util que se puede tener de un ajuste caro.
    """
    arranque = time.time()
    seguro = _normalizar(params, estricto=False)
    ajuste = {"modelo": seguro["modelo"], "esfuerzo": seguro["esfuerzo"]}
    try:
        return _redactar(proyecto, params, avisar)
    except cli_claude.TiempoAgotado:
        estadisticas.anotar(PASO, time.time() - arranque, ok=False, ajuste=ajuste,
                            proyecto=getattr(proyecto, "id", None),
                            resultado="tiempo agotado")
        raise
    except Exception:  # noqa: BLE001
        estadisticas.anotar(PASO, time.time() - arranque, ok=False, ajuste=ajuste,
                            proyecto=getattr(proyecto, "id", None),
                            resultado="error")
        raise


def _redactar(proyecto, params, avisar):
    """Redacta el guion con el CLI de Claude a partir del material y el brief."""
    arranque = time.time()
    opciones = _normalizar(params)
    trabajo = comun.preparar_trabajo(proyecto, PASO)

    avisar(0.02, "reuniendo el material")
    brief_doc = comun.leer_salida(proyecto, "brief", "brief.json")
    # EL MATERIAL, del paso «Origen». Se lee por `material_de` y no abriendo el
    # fichero aqui: es el unico sitio donde se decide de donde sale, y con dos
    # lecturas distintas de lo mismo una de las dos se queda vieja.
    transcript, metadatos, de_donde = fuentes.material_de(proyecto)
    if not transcript:
        raise RuntimeError(
            "no hay material para el guion: el paso «Origen» no ha dejado "
            "nada. Escribe o pega de que va este video y vuelve a lanzarlo")

    # NO HAY «VIDEO DE ORIGEN» aparte del material: el material es uno y es el
    # que se escribio. `origen` se queda --el prompt tiene su seccion-- para el
    # dia que haya una segunda fuente que aporte la FORMA y no los hechos.
    origen = None

    anterior = None if opciones["regenerar_desde_cero"] else _guion_anterior(proyecto)
    idioma = _idioma_pedido(brief_doc, opciones)
    palabras_material = int(metadatos.get("palabras_transcript") or
                            sum(comun.contar_palabras(t.get("texto", ""))
                                for t in transcript))

    # La estimacion va por COMBINACION: mezclar 'sonnet/low' con 'opus/high' en
    # una sola mediana es sumar peras y manzanas, y la barra vuelve a mentir.
    ajuste = {"modelo": opciones["modelo"], "esfuerzo": opciones["esfuerzo"]}
    prevision_llamada = estadisticas.estimar(PASO, palabras_material,
                                             ajuste=ajuste)

    # LOS AVISOS SON DEL INTENTO QUE SE ENTREGA, no de todos los que se pagaron.
    # Con una lista compartida, un intento descartado dejaba puestos los suyos
    # --«repuestas tres tildes», «etiqueta desconocida»-- encima de un guion que
    # no es el suyo, y eso manda a mirar un texto que no tiene ese problema.
    # Desde que se entrega el MEJOR intento y no el ultimo, esto pasa de verdad.
    def comprobar_principal(datos):
        propios = []
        bloques = _aplicar_marcas(_normalizar_bloques(datos), opciones,
                                  propios, idioma)
        datos["_bloques"] = bloques
        datos["_avisos"] = propios
        palabras = sum(marcas_tts.contar_palabras(b["texto"]) for b in bloques)
        return _problemas(bloques, palabras, brief_doc, opciones, idioma)

    datos, sobre, intentos, pendientes = _pedir(
        lambda correcciones, previo: _instruccion(transcript, metadatos,
                                                  brief_doc, anterior, opciones,
                                                  correcciones, idioma, previo,
                                                  origen),
        opciones, trabajo, avisar, (0.05, 0.95),
        f"redactando el guion en {_nombre_idioma(brief_doc, idioma)} "
        f"con {opciones['modelo']}",
        prevision_llamada, "instruccion", comprobar_principal)

    avisos_marcas = list(datos.get("_avisos") or [])
    bloques = datos["_bloques"]
    # las ediciones a mano mandan sobre lo que acabe de escribir el modelo: el
    # humano ya vio ese bloque y lo corrigio, y perder su texto en la siguiente
    # pasada seria tirar su trabajo.
    editados = [b["id"] for b in bloques if b["id"] in opciones["bloques"]]
    for bloque in bloques:
        if bloque["id"] in opciones["bloques"]:
            bloque["texto"] = opciones["bloques"][bloque["id"]]
    # tambien lo escrito a mano: la interfaz ensena las anotaciones dentro del
    # texto, asi que una persona puede teclear una que no existe sin saberlo, y
    # lo que Cartesia no reconoce lo locuta
    bloques = _aplicar_marcas(bloques, opciones, avisos_marcas, idioma)

    palabras = sum(marcas_tts.contar_palabras(b["texto"]) for b in bloques)
    titulo = str(datos.get("titulo") or metadatos.get("titulo") or "Sin titulo").strip()

    if bloques:
        bloques[0]["abre_seccion"] = True   # el primero siempre abre seccion
    # Y AHORA EL AIRE, con las secciones ya fijadas.
    _aire_entre_secciones(bloques, opciones)
    guion = [{"id": b["id"], "texto": b["texto"],
              "abre_seccion": bool(b.get("abre_seccion")),
              # y si el personaje del canal da la cara en el:
              # solo cuando es verdad, para no ensuciar los guiones sin personaje
              **({"personaje": True} if b.get("personaje") else {})}
             for b in bloques]
    detalle = [{"id": b["id"], "texto": b["texto"],
                "palabras": marcas_tts.contar_palabras(b["texto"])}
               for b in bloques]
    avisos = list(_avisos(bloques, palabras, brief_doc, idioma))
    avisos.extend(pendientes)
    tokens = comun.tokens_de_cli(sobre)

    avisar(0.96, "guardando el guion")
    # Lo que hubo que corregir de las anotaciones sube a la interfaz. No es
    # ruido: si el modelo se inventa etiquetas una y otra vez, se ve aqui antes
    # de pagar el TTS, que es cuando todavia se puede cambiar la instruccion.
    avisos.extend(dict.fromkeys(avisos_marcas))
    marcas = marcas_tts.resumen(guion)
    presupuesto, minimo, maximo = _horquilla(brief_doc, idioma)

    documento = {
        "titulo": titulo,
        "guion": guion,
        "palabras": palabras,
        "presupuesto_palabras": presupuesto,
        "palabras_minimo": minimo,
        "palabras_maximo": maximo,
        "bloques_detalle": detalle,
        "idioma": idioma,
        "modelo": opciones["modelo"],
        "esfuerzo": opciones["esfuerzo"],
        "intentos": intentos,
        "prompt_general": opciones["prompt_general"],
        "regenerado_desde_cero": opciones["regenerar_desde_cero"],
        "partia_de": (anterior or {}).get("titulo", "") if anterior else "",
        "bloques_editados": editados,
        "anotaciones_voz": opciones["anotaciones_voz"],
        "marcas_tts": marcas,
        "avisos": avisos,
        # LO QUE ESTE VIDEO PROMOCIONA, ESCRITO EN EL GUION.
        #
        # Aguas abajo hace falta saberlo --la firma del cierre es la marca de un
        # PRODUCTO, no del canal (ver `p6_assets._firmar_cierre`)-- y ahi solo se
        # llega al guion, no a los params. Se guarda con el guion por la misma
        # razon que las anotaciones de voz: es parte de lo que se escribio.
        #
        # Va en el DOCUMENTO y no en `salidas`: el sello de un paso es su version
        # y su firma (`Estado._sello_salida`), asi que anadir esto no deja
        # obsoleto nada. Un guion escrito antes de hoy no lo lleva, y quien lo lee
        # trata esa ausencia como «no promociona nada», que es lo correcto: una
        # marca en pantalla es publicidad, y la publicidad que no se ha pedido no
        # se pone.
        "cta": opciones.get("cta"),
    }
    comun.escribir_json(os.path.join(trabajo, "guion.json"), documento)
    comun.escribir_texto(
        os.path.join(trabajo, "guion.txt"),
        f"{titulo}\n\n"
        + "\n\n".join(f"{b['id']}  {b['texto']}" for b in guion) + "\n")

    segundos = time.time() - arranque
    estadisticas.anotar(PASO, segundos, tamano=palabras_material,
                        ajuste=ajuste, proyecto=getattr(proyecto, "id", None),
                        idioma=idioma, intentos=intentos,
                        detalle={"modelo": opciones["modelo"],
                                 "esfuerzo": opciones["esfuerzo"],
                                 "bloques": len(bloques),
                                 "tokens_salida": (tokens or {}).get("salida")})

    dentro = (not minimo or palabras >= minimo) and (not maximo or palabras <= maximo)
    total_marcas = sum(marcas.values())
    resumen = (f"\"{titulo}\": {len(bloques)} bloques, {palabras} palabras "
               f"(horquilla {minimo}-{maximo})"
               + ("" if dentro else " FUERA de la horquilla")
               + (f"; {total_marcas} anotaciones de voz" if total_marcas else "")
               + (f"; {len(avisos)} aviso(s)" if avisos else ""))

    # Salidas pequenas a proposito: el nucleo resume cualquier salida grande al
    # sellarla, y un guion entero ahi dentro llegaria roto al panel. El texto
    # completo esta en guion.json dentro de la version.
    salidas = {
        "guion_fichero": "guion.json",
        "idioma": idioma,
        "titulo": titulo,
        "bloques": len(bloques),
        "palabras": palabras,
        "presupuesto_palabras": presupuesto,
        "palabras_minimo": minimo,
        "palabras_maximo": maximo,
        "dentro_de_horquilla": dentro,
        "desviacion": round(palabras / presupuesto - 1.0, 3) if presupuesto else 0.0,
        "bloques_editados": editados,
        "anotaciones_voz": opciones["anotaciones_voz"],
        "marcas_tts": marcas,
        "avisos": avisos,
        "modelo": opciones["modelo"],
        "esfuerzo": opciones["esfuerzo"],
        "intentos": intentos,
        "tokens": tokens,
        "segundos": round(segundos, 1),
        "estimacion_s": prevision_llamada["segundos"],
        "resumen": resumen,
    }
    avisar(1.0, resumen)
    return salidas
