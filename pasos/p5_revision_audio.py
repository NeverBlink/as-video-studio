"""
Paso 5 del Estudio: REVISION DE AUDIO.

Comentarios al estilo Google Docs sobre el guion. El usuario selecciona un trozo
de un bloque y deja una nota; el paso aplica TODAS las notas de una tacada:

  1. agrupa los comentarios por bloque,
  2. reescribe cada bloque afectado con el CLI de Claude (modelo sonnet),
     pasandole el bloque original, el fragmento seleccionado y la nota,
  3. vuelve a sintetizar la toma COMPLETA con los mismos controles de voz.

Por que se resintetiza todo
---------------------------
Aunque solo cambie un bloque, empalmar el audio nuevo con el de la toma anterior
rompe la continuidad de entonacion y de energia justo en el corte, que es
exactamente lo que se evitaba grabando en una sola toma. Reventar 40 segundos de
sintesis es barato; un empalme que se oye, no.

El paso es reproducible desde sus entradas: siempre parte del guion original del
paso 3 y aplica la lista completa de comentarios que hay en sus params. Anadir
un comentario y volver a ejecutar da el mismo resultado que aplicarlos todos de
cero, que es lo que espera el grafo de build.

Modo simulado (ESTUDIO_SIMULAR=1): ni CLI de Claude ni Cartesia. La reescritura
la hacen reglas locales deterministas y el audio es silencio con marcas.

API publica
-----------
    ejecutar(proyecto, params, avisar) -> salidas (las del paso 4 mas
                                          "bloques_modificados")

Params del paso
---------------
    comentarios     [{"id","bloque_id","inicio_char","fin_char",
                      "texto_seleccionado","comentario"}]
    modelo_texto    modelo del CLI para reescribir (sonnet por defecto)
    esfuerzo_texto  esfuerzo de razonamiento del CLI (low por defecto)
    tiempo_max_s    tope por bloque para el CLI; 0 = automatico segun el esfuerzo
    voz             dict opcional que sobreescribe los controles del paso 4
                    (o las claves sueltas preset/voz_id/modelo/velocidad/
                    emociones/idioma/hueco_minimo)

Ojo con el nombre 'modelo'
--------------------------
En ESTE paso 'modelo' ya significa el modelo de voz de Cartesia (lo usa
_config_voz). Por eso el del CLI se llama 'modelo_texto' y su esfuerzo
'esfuerzo_texto': dos mandos distintos con el mismo nombre en el mismo
formulario es una confusion garantizada.

Que parte del tiempo manda el ajuste
------------------------------------
Aqui hay UNA llamada al CLI por bloque comentado, y despues una resintesis
completa de la toma que se lleva la mayor parte del paso. Subir el esfuerzo
alarga solo la primera parte: el historico guarda los dos tiempos por separado
(`segundos_cli` en el detalle) para que la cifra no enganse.
"""
import json
import os
import re
import shutil
import subprocess
import time

try:
    from . import cli_claude, comun, estadisticas, marcas_tts, p4_voz
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas
    import marcas_tts
    import p4_voz

PASO = "revision_audio"
# Ver cli_claude.POR_FASE: reescribir un bloque corto con una nota concreta es
# de los casos que salen igual de bien con el modelo rapido y esfuerzo bajo, y
# aqui hay una llamada POR BLOQUE, asi que la latencia se multiplica.
MODELO_TEXTO = cli_claude.por_defecto_de("revision_audio")["modelo"]
TIMEOUT_CLI = 420

# Sin --effort, el CLI se pone a razonar durante minutos antes de escribir, y
# hereda ademas el esfuerzo del entorno desde el que se arranco el servicio.
# Medido en el paso 3 con la misma entrada: 606 s sin el, 67 s con 'low'.
# Reescribir un bloque de treinta palabras no necesita mas.
ESFUERZO_TEXTO = cli_claude.por_defecto_de("revision_audio")["esfuerzo"]

PARAMS_POR_DEFECTO = {
    "comentarios": [],
    "modelo_texto": MODELO_TEXTO,
    "esfuerzo_texto": ESFUERZO_TEXTO,
    "tiempo_max_s": 0,      # 0 = automatico segun el esfuerzo
    "voz": {},
}
NOMBRE_GUION = "guion_revisado.json"
NOMBRE_COMENTARIOS = "comentarios.json"

# Sin herramientas el CLI contesta en un solo turno. Con ellas se pone a mirar la
# carpeta desde la que se le lanza y contesta al proyecto en vez de al encargo:
# comprobado, devolvia una presentacion en vez del bloque reescrito.
HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")

SISTEMA = ("Responde exclusivamente con el texto reescrito del bloque, sin texto "
           "alrededor, sin comillas, sin vallas de markdown y sin usar herramientas.")

INSTRUCCION = """\
Eres el guionista de un documental narrado en off, en espanol.

Reescribe UN bloque del guion aplicando las notas del revisor.

BLOQUE ORIGINAL (id {bloque_id}):
<<<
{texto}
>>>

NOTAS DEL REVISOR:
{notas}

Reglas:
- Responde SOLO con el texto reescrito del bloque. Sin comillas, sin markdown,
  sin encabezados, sin explicar lo que has cambiado.
- Es texto para leer en voz alta: nada de acotaciones, parentesis tecnicos,
  nombres de plano ni marcas de escena.
- Con la ORTOGRAFIA COMPLETA del castellano: todas las tildes, las dieresis y
  las enes. Lo lee un sintetizador de voz, asi que sin tilde dice «publico»
  donde pone «publico» con tilde. Da igual como este escrita esta instruccion.
- TODO CON LETRAS: ni un digito ni un simbolo. Esto se locuta, y una cifra la
  pronuncia el sintetizador como el decida (un guion en ingles con «May 2024»
  dijo «may dos mil veinticuatro»). Anos, numeros, fechas, porcentajes, dinero y
  horas, escritos como se dicen en el idioma del bloque. Las siglas que se
  deletrean, marcadas: <spell>MFA</spell>.
- Manten el idioma, el registro y una longitud parecida, salvo que la nota pida
  expresamente acortar o alargar.
- Cambia solo lo que piden las notas; el resto del bloque se queda como esta.
- Si una nota no se puede aplicar, aplica las demas y no lo comentes.
- Si el bloque trae anotaciones de voz (<break time="700ms"/>, <speed ratio=
  "0.9"/>, <volume ratio="0.9"/>, <emotion value="sad"/>), NO son texto: le
  dicen al sintetizador donde parar y como sonar. Van en ingles aunque el guion
  no, se conservan, y se recolocan si la frase que las rodeaba ha cambiado.
  Estas son las unicas que existen: no te inventes ninguna, porque una etiqueta
  que el sintetizador no reconoce la LEE EN VOZ ALTA. Y si el bloque abre
  <speed> o <volume>, tiene que cerrarlo con ratio="1" antes de acabar.
"""

_PREAMBULOS = re.compile(
    r"^(aqui tienes|aqui va|texto reescrito|bloque reescrito|version reescrita|"
    r"reescritura|resultado)\b[^\n]*:\s*$", re.IGNORECASE)


# ---------------------------------------------------------------- comentarios

def agrupar_comentarios(comentarios):
    """{bloque_id: [comentarios]} conservando el orden de llegada."""
    agrupados = {}
    for posicion, crudo in enumerate(comentarios or [], 1):
        if not isinstance(crudo, dict):
            continue
        bloque_id = str(crudo.get("bloque_id") or crudo.get("bloque") or "").strip()
        texto = str(crudo.get("comentario") or "").strip()
        if not bloque_id or not texto:
            continue
        ficha = {
            "id": str(crudo.get("id") or f"C{posicion:03d}"),
            "bloque_id": bloque_id,
            "inicio_char": crudo.get("inicio_char"),
            "fin_char": crudo.get("fin_char"),
            "texto_seleccionado": str(crudo.get("texto_seleccionado") or ""),
            "comentario": texto,
        }
        agrupados.setdefault(bloque_id, []).append(ficha)
    return agrupados


def localizar(texto, comentario):
    """Tramo (inicio, fin) del bloque al que se refiere el comentario.

    Los offsets del navegador pueden no cuadrar si el guion se reeditio despues
    de comentar, asi que solo se aceptan si el texto que hay ahi es el que el
    usuario dice haber seleccionado; si no, se busca el fragmento y, en ultimo
    caso, la nota se aplica al bloque entero.
    """
    seleccion = comentario.get("texto_seleccionado") or ""
    inicio, fin = comentario.get("inicio_char"), comentario.get("fin_char")
    if isinstance(inicio, int) and isinstance(fin, int) and 0 <= inicio < fin <= len(texto):
        if not seleccion or texto[inicio:fin] == seleccion:
            return inicio, fin
    if seleccion:
        encontrado = texto.find(seleccion)
        if encontrado >= 0:
            return encontrado, encontrado + len(seleccion)
    return None, None


def _fragmento(texto, comentario):
    inicio, fin = localizar(texto, comentario)
    if inicio is None:
        return (comentario.get("texto_seleccionado") or "").strip()
    return texto[inicio:fin]


def redactar_notas(texto, comentarios):
    """Comentarios -> lista numerada legible para el modelo."""
    lineas = []
    for numero, comentario in enumerate(comentarios, 1):
        trozo = _fragmento(texto, comentario)
        if trozo:
            lineas.append(f'{numero}. Sobre el fragmento "{trozo}": '
                          f'{comentario["comentario"]}')
        else:
            lineas.append(f'{numero}. Sobre todo el bloque: {comentario["comentario"]}')
    return "\n".join(lineas)


# ---------------------------------------------------------------- reescritura

def _limpiar_respuesta(salida):
    """Quita fences, preambulos y comillas de la respuesta del CLI."""
    texto = (salida or "").strip()
    if not texto:
        return ""
    texto = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", texto).strip()
    lineas = [l for l in texto.splitlines()]
    while lineas and (not lineas[0].strip() or _PREAMBULOS.match(lineas[0].strip())):
        lineas.pop(0)
    texto = "\n".join(lineas).strip()
    if len(texto) > 1 and texto[0] in "\"'«" and texto[-1] in "\"'»":
        texto = texto[1:-1].strip()
    return re.sub(r"[ \t]+", " ", texto).strip()


def _acortar(texto):
    """Recorta a la primera frase; si es una sola, a su primera oracion util."""
    frases = [f for f in re.split(r"(?<=[.!?])\s+", texto.strip()) if f]
    if len(frases) > 1:
        return frases[0]
    cuerpo = frases[0] if frases else texto.strip()
    coma = cuerpo.find(",")
    if coma > 0:
        return cuerpo[:coma].rstrip() + "."
    palabras = cuerpo.split()
    if len(palabras) > 4:
        return " ".join(palabras[:max(3, len(palabras) * 2 // 3)]).rstrip(",.") + "."
    return cuerpo


def _reescribir_simulado(texto, comentarios):
    """Reescritura local determinista, solo para pruebas sin gastar creditos.

    Tres reglas que cubren lo que se pide de verdad en una revision: quitar algo,
    acortar, o sustituir el fragmento por lo que dice la nota.
    """
    resultado = texto
    for comentario in comentarios:
        nota = comentario["comentario"].strip()
        plano = nota.lower()
        inicio, fin = localizar(resultado, comentario)
        if any(p in plano for p in ("elimina", "quita", "borra", "fuera")):
            if inicio is not None:
                resultado = (resultado[:inicio] + resultado[fin:])
            continue
        if any(p in plano for p in ("acorta", "mas corto", "corta", "resume")):
            resultado = _acortar(resultado)
            continue
        if inicio is not None:
            resultado = resultado[:inicio] + nota.rstrip(".") + resultado[fin:]
        else:
            resultado = resultado.rstrip(". ") + ". " + nota
    resultado = re.sub(r"\s+", " ", resultado).strip()
    resultado = re.sub(r"\s+([,.;:])", r"\1", resultado)
    return resultado


def describir(params):
    """Resumen de una linea de la configuracion del paso, para la bitacora."""
    opciones = _normalizar(params, estricto=False)
    notas = len(opciones["comentarios"])
    return (f"revision de audio con {opciones['modelo_texto']} "
            f"(esfuerzo {opciones['esfuerzo_texto']}): "
            f"{notas} comentario(s) y regrabacion de la toma")


def _normalizar(params, estricto=True):
    """Params completos y con los tipos correctos; valida si estricto.

    Hasta ahora este paso no validaba nada: 'modelo_texto' llegaba tal cual a
    --model, y como reescribir_bloque se traga el error devolviendo el texto
    original, un modelo mal escrito se veia como "no ha cambiado nada" en vez de
    como un fallo. Un aviso que hay que deducir no es un aviso.
    """
    opciones = dict(PARAMS_POR_DEFECTO)
    for clave, valor in (params or {}).items():
        if clave in PARAMS_POR_DEFECTO:
            opciones[clave] = valor

    opciones["modelo_texto"] = cli_claude.normalizar_modelo(
        opciones.get("modelo_texto"), estricto=estricto, defecto=MODELO_TEXTO)
    opciones["esfuerzo_texto"] = cli_claude.normalizar_esfuerzo(
        opciones.get("esfuerzo_texto"), estricto=estricto, defecto=ESFUERZO_TEXTO)

    try:
        opciones["tiempo_max_s"] = int(opciones["tiempo_max_s"] or 0)
    except (TypeError, ValueError):
        if estricto:
            raise ValueError("tiempo_max_s tiene que ser un numero entero")
        opciones["tiempo_max_s"] = 0
    if estricto and 0 < opciones["tiempo_max_s"] < 30:
        raise ValueError("tiempo_max_s tiene que ser al menos 30 "
                         "(o 0 para que lo decida el esfuerzo)")
    if opciones["tiempo_max_s"] < 0:
        opciones["tiempo_max_s"] = 0

    comentarios = opciones.get("comentarios")
    opciones["comentarios"] = list(comentarios) if isinstance(comentarios, list) else []
    voz = opciones.get("voz")
    opciones["voz"] = dict(voz) if isinstance(voz, dict) else {}
    return opciones


def tiempo_max_de(opciones):
    """Techo de UNA reescritura: el fijado a mano, o el que pide el esfuerzo."""
    return cli_claude.tiempo_max(opciones["esfuerzo_texto"], base_s=TIMEOUT_CLI,
                                 modelo=opciones["modelo_texto"],
                                 pedido_s=opciones.get("tiempo_max_s") or 0)


def _localizar_claude():
    """Ruta del ejecutable del CLI de Claude."""
    return cli_claude.localizar("la revision de audio")


def _llamar_claude(instruccion, modelo, cwd, tiempo_max, esfuerzo=ESFUERZO_TEXTO):
    """Lanza el CLI en headless y devuelve (texto de la respuesta, sobre JSON).

    Sigue existiendo con este nombre porque el medidor de coste la engancha POR
    NOMBRE (nucleo/coste.py:728). La orden la arma cli_claude.
    """
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=tiempo_max, base_tiempo_s=TIMEOUT_CLI,
        sistema=SISTEMA, herramientas_vetadas=HERRAMIENTAS_VETADAS,
        extra=["--no-session-persistence"],
        para="la reescritura del bloque")


def reescribir_bloque(bloque, comentarios, modelo=MODELO_TEXTO, cwd=None,
                      tiempo_max=TIMEOUT_CLI, esfuerzo=ESFUERZO_TEXTO):
    """Aplica las notas a un bloque. Devuelve (texto_nuevo, aviso, sobre).

    Si algo sale mal se devuelve el texto ORIGINAL y el aviso: perder el bloque
    entero por una reescritura fallida seria peor que ignorar la nota, y el
    aviso sube hasta las salidas del paso para que se vea en la UI.
    """
    texto = bloque["texto"]
    if not comentarios:
        return texto, "", {}
    if p4_voz.simulado():
        return _reescribir_simulado(texto, comentarios), "", {}

    instruccion = INSTRUCCION.format(
        bloque_id=bloque["id"], texto=texto,
        notas=redactar_notas(texto, comentarios))
    try:
        crudo, sobre = _llamar_claude(instruccion, modelo, cwd, tiempo_max,
                                      esfuerzo=esfuerzo)
    except (subprocess.TimeoutExpired, cli_claude.TiempoAgotado):
        return texto, f"el CLI de claude no respondio en {tiempo_max}s", {}
    except (RuntimeError, OSError) as fallo:
        return texto, str(fallo), {}

    nuevo = _limpiar_respuesta(crudo)
    if not nuevo:
        return texto, "el CLI de claude devolvio una respuesta vacia", sobre
    # una reescritura que multiplica o divide el bloque suele ser el modelo
    # explicando en vez de reescribiendo: mejor quedarse con el original. Se
    # compara sobre el texto HABLADO: un bloque con anotaciones tiene mas
    # caracteres sin decir una palabra mas, y esa holgura falseaba el limite.
    hablado_antes = marcas_tts.limpiar(texto)
    hablado_nuevo = marcas_tts.limpiar(nuevo)
    if not (0.25 * len(hablado_antes) <= len(hablado_nuevo)
            <= 4 * len(hablado_antes)):
        return texto, (f"reescritura descartada por longitud implausible "
                       f"({len(hablado_antes)} -> {len(hablado_nuevo)} "
                       f"caracteres de narracion)"), sobre
    # El bloque puede volver de aqui con una etiqueta inventada, y lo que
    # Cartesia no reconoce lo LOCUTA. Se corrige en silencio y no se cuenta como
    # aviso: el aviso de esta funcion significa "la reescritura no salio", y
    # esta si salio. Lo que haya habido que corregir lo dice el paso de voz al
    # sintetizar (salidas["avisos_marcas"]), que es justo antes de pagar el TTS.
    nuevo = marcas_tts.sanear(nuevo)
    if not nuevo.strip():
        return texto, "la reescritura se quedo sin texto que locutar", sobre
    return nuevo, "", sobre


# ------------------------------------------------------------------- el paso

def _config_voz(proyecto, params):
    """Controles de voz del paso 4, con lo que este paso quiera sobreescribir."""
    base = {}
    estado = p4_voz._estado_de(proyecto)
    if estado is not None:
        base = estado.params("voz") or {}
    base = {k: v for k, v in base.items() if k != "unidades"}
    for clave in ("preset", "modelo", "voz_id", "idioma", "velocidad",
                  "emociones", "hueco_minimo"):
        if params.get(clave) is not None:
            base[clave] = params[clave]
    if isinstance(params.get("voz"), dict):
        base.update(params["voz"])
    return base


def _sellar_sin_cambios(proyecto, bloques, cfg, destino, avisa):
    """Da por buena la toma del paso 4 SIN volver a sintetizarla.

    Es el caso de "la toma esta bien, no tengo nada que corregir". Sin
    comentarios, esta pasada reescribe cero bloques, asi que su resultado es,
    palabra por palabra, la toma del paso 4: resintetizarla seria pagar a
    Cartesia por una copia. Se copian la pista y sus marcas tal cual.

    Solo vale si lo que se copia es de verdad lo mismo, y eso son tres
    condiciones que se comprueban aqui, no se suponen:

      1. el paso 4 tiene version activa con pista y meta en disco,
      2. los controles de voz de esa toma son los que pediria esta pasada
         (si alguien cambio la voz o la velocidad, hay que regrabar),
      3. los bloques y su texto son identicos a los que se locutaron.

    Devuelve las salidas ya escritas, o None si hay que regrabar de verdad.
    """
    carpeta = comun.carpeta_activa(proyecto, "voz")
    if not carpeta:
        return None
    meta = comun.leer_salida(proyecto, "voz", p4_voz.NOMBRE_META, obligatorio=False)
    if not isinstance(meta, dict):
        return None
    origen_wav = os.path.join(carpeta, meta.get("archivo") or p4_voz.NOMBRE_PISTA)
    if not os.path.exists(origen_wav):
        return None

    controles = meta.get("controles")
    if not isinstance(controles, dict):
        return None
    # Se comparan los controles RESUELTOS de las dos partes: cfg ya viene de
    # resolver_params, y 'controles' es el cfg con el que se grabo.
    if {k: controles.get(k) for k in cfg} != dict(cfg):
        return None

    grabados = [(b.get("id"), (b.get("texto") or "").strip())
                for b in (meta.get("bloques") or [])]
    ahora = [(b.get("id"), (b.get("texto") or "").strip()) for b in bloques]
    if grabados != ahora:
        return None

    avisa(0.3, "la toma del paso 4 vale tal cual: se sella sin regrabar")
    nombre = meta.get("archivo") or p4_voz.NOMBRE_PISTA
    shutil.copy2(origen_wav, os.path.join(destino, nombre))

    salidas = {k: v for k, v in meta.items() if k != "transcript"}
    salidas["pista"] = os.path.join(destino, nombre)
    salidas["bloques_modificados"] = []
    salidas["cambios"] = []
    salidas["avisos"] = []
    salidas["sellada_del_paso_4"] = True
    salidas["resumen"] = (f"toma dada por buena sin cambios: es la del paso 4 "
                          f"({salidas.get('duracion')}s, sin regrabar)")
    nueva_meta = dict(salidas)
    nueva_meta["transcript"] = meta.get("transcript")
    comun.escribir_json(os.path.join(destino, p4_voz.NOMBRE_META), nueva_meta)
    return salidas


def ejecutar(proyecto, params, avisar=None):
    """Aplica todos los comentarios y regraba la toma entera.

    Sin ningun comentario, el paso NO regraba: sella la toma del paso 4, que es
    exactamente lo que quedaria al reescribir cero bloques. Es el boton de "esta
    bien asi" de la interfaz. Ver _sellar_sin_cambios.

    Escribe en pasos/revision_audio/trabajo/: narracion.wav, audio_meta.json,
    guion_revisado.json y comentarios.json. Tras estado.completar, esa carpeta
    pasa a ser pasos/revision_audio/v<N>/.
    """
    arranque = time.time()
    avisa = p4_voz._avisador(avisar)
    params = dict(params or {})
    opciones = _normalizar(params)
    modelo_texto = opciones["modelo_texto"]
    esfuerzo_texto = opciones["esfuerzo_texto"]
    ajuste = {"modelo": modelo_texto, "esfuerzo": esfuerzo_texto}
    techo_cli = tiempo_max_de(opciones)
    segundos_cli = 0.0

    avisa(0.01, "leyendo guion y comentarios")
    bloques = p4_voz.cargar_guion(proyecto, params)
    agrupados = agrupar_comentarios(params.get("comentarios"))
    conocidos = {b["id"] for b in bloques}
    destino = comun.preparar_trabajo(proyecto, PASO)

    cambios, avisos = [], []
    for bloque_id in agrupados:
        if bloque_id not in conocidos:
            avisos.append(f"comentario sobre un bloque inexistente: {bloque_id}")

    cfg = p4_voz.resolver_params(_config_voz(proyecto, params))

    if not agrupados:
        sellada = _sellar_sin_cambios(proyecto, bloques, cfg, destino, avisa)
        if sellada is not None:
            comun.escribir_json(os.path.join(destino, NOMBRE_GUION),
                                {"guion": [dict(b) for b in bloques]})
            comun.escribir_json(os.path.join(destino, NOMBRE_COMENTARIOS),
                                {"comentarios": [], "cambios": [], "avisos": []})
            # Se anota igual que cualquier otra ejecucion: si no, el historico
            # diria que este paso siempre tarda minutos, y la mayoria de las
            # veces se resuelve asi.
            estadisticas.anotar(
                PASO, time.time() - arranque,
                tamano=sum(comun.contar_palabras(b.get("texto")) for b in bloques),
                ajuste=ajuste, proyecto=getattr(proyecto, "id", None), unidades=0,
                detalle={"modelo": modelo_texto, "esfuerzo": esfuerzo_texto,
                         "bloques_reescritos": 0, "bloques_modificados": 0,
                         "segundos_cli": 0.0, "sellada_del_paso_4": True,
                         "avisos": 0})
            avisa(1.0, sellada["resumen"])
            return sellada

    afectados = [b for b in bloques if b["id"] in agrupados]
    revisados = []
    tokens = {"entrada": 0, "salida": 0, "cache": 0}
    for bloque in bloques:
        comentarios = agrupados.get(bloque["id"], [])
        if not comentarios:
            revisados.append(dict(bloque))
            continue
        avisa(0.02 + 0.35 * (len(cambios) / max(1, len(afectados))),
              f"reescribiendo {bloque['id']} ({len(comentarios)} comentarios)")
        marca_bloque = time.time()
        nuevo, aviso, sobre = reescribir_bloque(
            bloque, comentarios, modelo_texto, cwd=destino,
            tiempo_max=techo_cli, esfuerzo=esfuerzo_texto)
        segundos_cli += time.time() - marca_bloque
        for clave, valor in comun.tokens_de_cli(sobre).items():
            tokens[clave] += valor
        cambiado = nuevo.strip() != bloque["texto"].strip()
        cambios.append({
            "bloque_id": bloque["id"],
            "comentarios": [c["id"] for c in comentarios],
            "antes": bloque["texto"],
            "despues": nuevo,
            "cambiado": cambiado,
            "ok": not aviso,
            "aviso": aviso,
        })
        if aviso:
            avisos.append(f"{bloque['id']}: {aviso}")
        revisados.append({"id": bloque["id"], "texto": nuevo})

    modificados = [c["bloque_id"] for c in cambios if c["cambiado"]]

    avisa(0.4, f"regrabando la toma completa ({len(modificados)} bloques tocados)")

    def progreso(valor, mensaje=""):
        return avisa(0.4 + 0.58 * max(0.0, min(1.0, valor)), mensaje)

    salidas = p4_voz.sintetizar_bloques(
        revisados, destino, cfg, avisar=progreso,
        extra_meta={"bloques_modificados": modificados,
                    "cambios": cambios,
                    "avisos": avisos,
                    "modelo_texto": modelo_texto,
                    "esfuerzo_texto": esfuerzo_texto,
                    "segundos_cli": round(segundos_cli, 1),
                    "tokens": tokens})

    salidas["resumen"] = (f"{len(modificados)} bloques reescritos, "
                          f"toma de {salidas['duracion']}s"
                          + (f"; {len(avisos)} aviso(s)" if avisos else ""))
    salidas["modelo_texto"] = modelo_texto
    salidas["esfuerzo_texto"] = esfuerzo_texto
    salidas["segundos_cli"] = round(segundos_cli, 1)
    # misma forma que guion.json del paso 3, para que lo lea el mismo codigo
    comun.escribir_json(os.path.join(destino, NOMBRE_GUION), {"guion": revisados})
    comun.escribir_json(os.path.join(destino, NOMBRE_COMENTARIOS),
                        {"comentarios": [c for lista in agrupados.values()
                                         for c in lista],
                         "cambios": cambios, "avisos": avisos})

    # El tiempo del paso NO es el tiempo del modelo: la resintesis completa se
    # lleva la mayor parte. Se guardan los dos, y el que manda para comparar
    # ajustes es 'segundos_cli'.
    estadisticas.anotar(
        PASO, time.time() - arranque,
        tamano=sum(comun.contar_palabras(b.get("texto")) for b in revisados),
        ajuste=ajuste, proyecto=getattr(proyecto, "id", None),
        unidades=len(afectados),
        detalle={"modelo": modelo_texto, "esfuerzo": esfuerzo_texto,
                 "bloques_reescritos": len(afectados),
                 "bloques_modificados": len(modificados),
                 "segundos_cli": round(segundos_cli, 1),
                 "tokens_salida": tokens.get("salida"),
                 "avisos": len(avisos)})

    avisa(1.0, salidas["resumen"])
    return salidas


def ruta_pista(proyecto, salidas):
    """Ruta real del wav revisado, en trabajo/ o ya versionado."""
    return p4_voz.ruta_pista(proyecto, salidas, paso_id="revision_audio")


if __name__ == "__main__":
    import argparse
    import sys

    sys.path.insert(0, p4_voz.RAIZ_ESTUDIO)
    from nucleo.proyecto import Proyecto  # noqa: E402

    parser = argparse.ArgumentParser(description="Paso 5: revision de audio")
    parser.add_argument("--proyecto", required=True)
    parser.add_argument("--comentarios", required=True,
                        help="JSON con la lista de comentarios")
    args = parser.parse_args()

    with open(args.comentarios, "r", encoding="utf-8") as fh:
        crudo = json.load(fh)
    lista = crudo.get("comentarios") if isinstance(crudo, dict) else crudo

    def traza(valor, mensaje=""):
        if mensaje:
            print(f"[{valor * 100:5.1f}%] {mensaje}")
        return valor

    resultado = ejecutar(Proyecto(args.proyecto), {"comentarios": lista}, traza)
    print(json.dumps({k: v for k, v in resultado.items() if k != "palabras"},
                     ensure_ascii=False, indent=2))
