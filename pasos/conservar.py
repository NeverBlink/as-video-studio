"""Que se puede MANTENER cuando cambia algo de una etapa anterior.

EL PROBLEMA
-----------
El grafo de build deriva la obsolescencia de las firmas, y eso esta bien: nadie
tiene que acordarse de marcar nada. Pero derivar tiene un precio que en un video
de doce minutos se paga entero: tocar una frase del guion cambia la firma del
guion, y con ella la de voz, assets, callouts y render. Todo obsoleto. Y "todo"
son 88 bloques de locucion pagados por caracter y 174 imagenes, cuando lo que ha
cambiado de verdad es una frase.

LA REGLA NUEVA
--------------
Un cambio aguas arriba ya no arrasa lo de aguas abajo. Se ANALIZA que se puede
mantener, se mantiene todo lo que se pueda, y se marca solo lo que es imposible
conservar. Con tres criterios, en este orden:

  1. Lo que no ha cambiado, no se toca. Un bloque con el mismo texto tiene la
     misma locucion y los mismos planos.
  2. Lo que ha cambiado poco se ARREGLA sin propagar. Si un bloque se alarga,
     antes que meter planos nuevos se estiran los que ya hay: el video sigue
     siendo el mismo, solo que ese plano dura un poco mas. Un plano se estira
     hasta ESTIRON_MAXIMO; pasado eso ya no es el mismo plano y se recorta de
     nuevo.
  3. Solo lo que ha cambiado de verdad se marca para rehacer.

DONDE ENTRA EL CLI, Y DONDE NO
------------------------------
Casi todo se decide sin llamar a nadie: comparar textos es gratis y es exacto.
El CLI se usa para la unica pregunta que no se puede contestar contando
caracteres -- "esta frase ha cambiado; la imagen que ya hay, ¿sigue valiendo?" --
y se le pregunta por TODOS los planos dudosos de una vez, en una sola llamada,
con una tabla corta delante. Un bloque retocado en la puntuacion no llega
siquiera a preguntarse.

Y la respuesta por defecto cuando el CLI no esta seguro es REHACER. Conservar de
mas se ve en el video final; conservar de menos solo cuesta una imagen.
"""
import difflib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from . import cli_claude, comun, estadisticas, medios
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas
    import medios

PASO = "conservacion"

MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]
TIEMPO_BASE_S = 240

#: Cuanto se parecen dos textos para considerar que es el mismo bloque retocado
#: -- y por tanto candidato a conservar -- y no uno que dice otra cosa.
#:
#: El umbral es BAJO a proposito. Reescribir una frase cambiandole el tono la
#: aleja mucho carácter a carácter y nada en lo que hay que dibujar: "el juicio
#: duro tres anos" y "el juicio se alargo durante tres anos interminables" se
#: parecen un 0,61 y piden exactamente la misma imagen. Pasado este umbral no se
#: da nada por conservado: se PREGUNTA, que para eso el analisis es barato.
PARECIDO_RETOQUE = 0.55

#: Y por debajo del umbral todavia hay una segunda oportunidad: que las dos
#: frases hablen de las mismas cosas. Se mide sobre las palabras largas, que son
#: las que nombran algo; los articulos y las preposiciones se reparten igual en
#: cualquier par de frases y solo suben el ruido.
SOLAPE_RETOQUE = 0.45
LARGO_CONTENIDO = 4

#: Cambios que NO cambian lo que se ve ni lo que se oye: puntuacion, mayusculas
#: y espacios. Un bloque que solo cambia en esto se conserva sin preguntar.
PARECIDO_COSMETICO = 0.995

#: Cuanto puede alargarse o acortarse un plano para absorber un cambio de
#: duracion sin dejar de ser el mismo plano. Estirar un plano de 4 s a 5 s no lo
#: convierte en otro; a 8 s, si: se queda quieto en pantalla y se nota.
ESTIRON_MAXIMO = 1.35

SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor, sin vallas de markdown y sin usar herramientas.")

HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")

INSTRUCCION = """Un video de animacion narrada ya generado tiene que absorber un
cambio en su guion. Cada plano tiene una imagen ya dibujada y ya pagada. Tu
trabajo es decidir, plano a plano, si esa imagen SIGUE VALIENDO con la frase
nueva o si hay que volver a dibujarla.

COMO SE DECIDE
Vale si lo que se ve seguiria siendo verdad: los mismos personajes, el mismo
sitio, la misma accion. Cambiar el tono de una frase, apretar su redaccion,
corregir una cifra que no se ve en pantalla o cambiar una palabra por un sinonimo
NO cambia lo que hay que dibujar.

No vale si la frase nueva describe otra cosa: otro sitio, otra persona, otro
momento, otra accion, o algo concreto que la imagen tendria que ensenar y no
ensena.

Ante la duda, di que NO vale. Una imagen conservada de mas se ve en el video
final; una rehecha de mas cuesta unos centimos.

LO QUE HAY QUE JUZGAR
Cada plano trae lo que narraba ANTES, lo que narra AHORA y como se describio la
imagen que ya existe.
<<<
{planos}
>>>

DEVUELVE EXACTAMENTE ESTE JSON, sin nada alrededor:

{{
  "planos": [
    {{
      "id": "<id del plano>",
      "vale": true,
      "porque": "<en una linea, por que sigue valiendo o por que no>"
    }}
  ]
}}
"""


# ------------------------------------------------------- comparar dos guiones

def _normal(texto):
    """Texto comparable: sin acentos, sin puntuacion y sin dobles espacios."""
    return " ".join(re.sub(r"[^\w\s]", " ", medios.normalizar_texto(texto)).split())


def _parecido(antes, despues):
    if antes == despues:
        return 1.0
    return difflib.SequenceMatcher(None, antes, despues).ratio()


def _contenido(texto):
    """Las palabras que NOMBRAN algo. Sin ellas dos frases no hablan de lo mismo."""
    return {p for p in texto.split() if len(p) >= LARGO_CONTENIDO}


def _solape(antes, despues):
    """Cuanto comparten dos frases de lo que nombran (Jaccard). 0 = nada."""
    a, d = _contenido(antes), _contenido(despues)
    if not a or not d:
        return 0.0
    return len(a & d) / float(len(a | d))


def comparar_bloques(antes, despues):
    """Que le ha pasado a cada bloque del guion. Sin llamar a nadie.

    'antes' y 'despues' son listas de {"id", "texto"}. Devuelve un dict por id de
    bloque con su estado:

        igual       ni una palabra distinta -> no se toca nada
        cosmetico   solo puntuacion, mayusculas o espacios -> tampoco
        retocado    la misma idea con otras palabras -> hay que mirar los planos
        reescrito   dice otra cosa -> se rehace
        nuevo       no estaba
        borrado     ya no esta

    La diferencia entre 'retocado' y 'reescrito' es la que decide cuanto dinero
    cuesta el cambio, asi que se mide y no se opina: se compara el texto
    normalizado y se mira ademas cuanto cambia de LARGO, porque un bloque que
    duplica su longitud ya no cabe en los mismos planos por mucho que hable de
    lo mismo.
    """
    mapa_antes = {str(b.get("id") or "").upper(): str(b.get("texto") or "")
                  for b in (antes or []) if b.get("id")}
    mapa_despues = {str(b.get("id") or "").upper(): str(b.get("texto") or "")
                    for b in (despues or []) if b.get("id")}
    fichas = {}
    for bid in sorted(set(mapa_antes) | set(mapa_despues)):
        viejo, nuevo = mapa_antes.get(bid), mapa_despues.get(bid)
        if viejo is None:
            fichas[bid] = {"estado": "nuevo", "parecido": 0.0, "solape": 0.0,
                           "palabras": 0,
                           "palabras_nuevas": comun.contar_palabras(nuevo),
                           "antes": "", "despues": nuevo}
            continue
        if nuevo is None:
            fichas[bid] = {"estado": "borrado", "parecido": 0.0, "solape": 0.0,
                           "palabras": comun.contar_palabras(viejo),
                           "palabras_nuevas": 0, "antes": viejo, "despues": ""}
            continue
        a, d = _normal(viejo), _normal(nuevo)
        parecido = _parecido(a, d)
        solape = _solape(a, d)
        largos = (comun.contar_palabras(viejo), comun.contar_palabras(nuevo))
        if viejo == nuevo:
            estado = "igual"
        elif a == d or parecido >= PARECIDO_COSMETICO:
            estado = "cosmetico"
        elif parecido >= PARECIDO_RETOQUE or solape >= SOLAPE_RETOQUE:
            estado = "retocado"
        else:
            estado = "reescrito"
        fichas[bid] = {"estado": estado, "parecido": round(parecido, 3),
                       "solape": round(solape, 3),
                       "palabras": largos[0], "palabras_nuevas": largos[1],
                       "antes": viejo, "despues": nuevo}
    return fichas


def resumen_bloques(fichas):
    """Cuantos bloques hay de cada clase, para poder decirlo en una linea."""
    cuenta = {}
    for ficha in (fichas or {}).values():
        cuenta[ficha["estado"]] = cuenta.get(ficha["estado"], 0) + 1
    return cuenta


# --------------------------------------------------- del guion a los planos

def planos_por_bloque(plan):
    """{id de bloque: [planos]}, leyendo el 'origen' que marca p6_assets.

    Sin 'origen' un plan antiguo no sabe de que trozo de guion sale cada plano.
    Ahi no se puede conservar nada por bloques, y se dice: es exactamente el
    caso en el que callarse haria creer que no habia nada que conservar.
    """
    por_bloque = {}
    for escena in (plan or {}).get("escenas") or []:
        origen = escena.get("origen") or {}
        bid = str(origen.get("bloque") or "").upper()
        if bid:
            por_bloque.setdefault(bid, []).append(escena)
    return por_bloque


def _hueco_de_duracion(planos, delta_palabras, cadencia):
    """Si el bloque cambia de largo, ¿cabe estirando los planos que ya hay?

    Es la regla que mas cambios evita: antes que meter planos nuevos -- que hay
    que dibujar y pagar -- se reparte el tiempo entre los que ya estan. Solo si
    no cabe se admite que el bloque necesita otro corte.
    """
    if not planos or not delta_palabras:
        return {"cabe": True, "estiron": 1.0, "segundos": 0.0}
    segundos = float(delta_palabras) / max(0.5, float(cadencia))
    actual = sum(float(p.get("duracion") or 0.0) for p in planos)
    if actual <= 0:
        return {"cabe": False, "estiron": 0.0, "segundos": round(segundos, 2)}
    estiron = (actual + segundos) / actual
    return {"cabe": 1.0 / ESTIRON_MAXIMO <= estiron <= ESTIRON_MAXIMO,
            "estiron": round(estiron, 3), "segundos": round(segundos, 2)}


def analizar(bloques_antes, bloques_despues, plan, cadencia=2.4):
    """Que se conserva y que no, SIN llamar a nadie todavia.

    Devuelve el reparto por bloques y por planos, con la lista de dudosos: los
    que hay que preguntar porque su frase ha cambiado sin cambiar de asunto.
    """
    fichas = comparar_bloques(bloques_antes, bloques_despues)
    por_bloque = planos_por_bloque(plan)
    conservar, rehacer, dudosos, estirar = [], [], [], []
    for bid, ficha in sorted(fichas.items()):
        planos = por_bloque.get(bid) or []
        ids = [p["id"] for p in planos]
        if ficha["estado"] in ("igual", "cosmetico"):
            conservar.extend(ids)
            continue
        if ficha["estado"] == "borrado":
            rehacer.extend(ids)          # sus planos desaparecen del montaje
            continue
        if ficha["estado"] == "nuevo":
            continue                     # todavia no tiene planos: seran nuevos
        hueco = _hueco_de_duracion(
            planos, ficha["palabras_nuevas"] - ficha["palabras"], cadencia)
        if ficha["estado"] == "reescrito" or not hueco["cabe"]:
            rehacer.extend(ids)
            continue
        if hueco["estiron"] != 1.0:
            estirar.append({"bloque": bid, **hueco, "planos": ids})
        for plano in planos:
            dudosos.append({"id": plano["id"], "bloque": bid,
                            "antes": _frase_de(plano, ficha["antes"]),
                            "despues": ficha["despues"],
                            "imagen": plano.get("prompt") or ""})
    return {"bloques": fichas, "resumen_bloques": resumen_bloques(fichas),
            "conservar": sorted(set(conservar)), "rehacer": sorted(set(rehacer)),
            "dudosos": dudosos, "estirar": estirar,
            "sin_origen": not por_bloque and bool((plan or {}).get("escenas"))}


def _frase_de(plano, texto_bloque):
    """Lo que narraba el plano. Si no lo trae, el bloque entero del que salio."""
    return (plano.get("narracion") or "").strip() or texto_bloque


# ------------------------------------------------------- la pregunta al CLI

def _tabla_de_dudosos(dudosos, maximo=60):
    lineas = []
    for ficha in dudosos[:maximo]:
        lineas.append(f"[{ficha['id']}]")
        lineas.append(f"  ANTES : {' '.join(str(ficha['antes']).split())}")
        lineas.append(f"  AHORA : {' '.join(str(ficha['despues']).split())}")
        imagen = " ".join(str(ficha.get("imagen") or "").split())
        if imagen:
            lineas.append(f"  IMAGEN: {comun.recortar(imagen, 320, '…')[0]}")
    return "\n".join(lineas)


def juzgar_dudosos(dudosos, ajuste=None, avisar=None, proyecto_id=None, cwd=None):
    """Pregunta por TODOS los dudosos de una vez si sigue valiendo su imagen.

    Una sola llamada y no una por plano: son frases cortas y la pregunta es la
    misma. Y si algo falla, todos los dudosos se van a rehacer -- que es lo que
    pasaba antes de que existiera este modulo, o sea que el fallo nunca deja el
    video peor de lo que estaba.
    """
    if not dudosos:
        return {"vale": {}, "porque": {}, "llamada": False}
    ajuste = ajuste or {}
    modelo = ajuste.get("modelo") or MODELO_POR_DEFECTO
    esfuerzo = ajuste.get("esfuerzo") or ESFUERZO_POR_DEFECTO
    elegido = {"modelo": modelo, "esfuerzo": esfuerzo}
    avisar = avisar or (lambda *a, **k: None)
    avisar(None, f"preguntando por {len(dudosos)} plano(s) dudoso(s) "
                 f"({modelo}/{esfuerzo})")

    arranque = time.time()
    instruccion = INSTRUCCION.format(planos=_tabla_de_dudosos(dudosos))
    texto, sobre = _llamar_claude(instruccion, modelo, esfuerzo, cwd)
    datos = comun.extraer_json(texto, "la respuesta")
    vale, porque = {}, {}
    conocidos = {d["id"] for d in dudosos}
    for ficha in (datos.get("planos") or []):
        if not isinstance(ficha, dict):
            continue
        pid = str(ficha.get("id") or "").strip()
        if pid not in conocidos:
            continue
        vale[pid] = bool(ficha.get("vale"))
        porque[pid] = str(ficha.get("porque") or "").strip()
    # Un plano por el que se pregunto y del que no contesto NO se conserva: no
    # contestar es no haberlo mirado, y darlo por bueno seria inventarse un si.
    for ficha in dudosos:
        vale.setdefault(ficha["id"], False)
        porque.setdefault(ficha["id"], "el analisis no dijo nada de este plano, "
                                       "asi que se rehace")
    segundos = time.time() - arranque
    estadisticas.anotar(PASO, segundos, tamano=len(dudosos), ajuste=elegido,
                        proyecto=proyecto_id, unidades=len(dudosos),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "conservados": sum(1 for v in vale.values() if v),
                                 "tokens_salida": comun.tokens_de_cli(sobre).get("salida")})
    return {"vale": vale, "porque": porque, "llamada": True,
            "segundos": round(segundos, 1), "ajuste": elegido}


def plan_de_conservacion(bloques_antes, bloques_despues, plan, ajuste=None,
                         avisar=None, proyecto_id=None, cwd=None, cadencia=2.4,
                         preguntar=True):
    """El plan entero: que se conserva, que se rehace y por que, plano a plano."""
    analisis = analizar(bloques_antes, bloques_despues, plan, cadencia)
    motivos = {pid: "el bloque del guion no ha cambiado"
               for pid in analisis["conservar"]}
    for pid in analisis["rehacer"]:
        motivos[pid] = "el bloque del guion dice otra cosa"

    juicio = {"vale": {}, "porque": {}, "llamada": False}
    if analisis["dudosos"] and preguntar:
        try:
            juicio = juzgar_dudosos(analisis["dudosos"], ajuste, avisar,
                                    proyecto_id, cwd)
        except Exception as fallo:         # noqa: BLE001
            # Sin juicio no se conserva nada dudoso. Es lo que pasaba antes de
            # que esto existiera, asi que fallar aqui nunca deja el video peor.
            juicio = {"vale": {}, "porque": {}, "llamada": False,
                      "error": f"{type(fallo).__name__}: {fallo}"}

    conservar = list(analisis["conservar"])
    rehacer = list(analisis["rehacer"])
    for ficha in analisis["dudosos"]:
        pid = ficha["id"]
        if juicio["vale"].get(pid):
            conservar.append(pid)
            motivos[pid] = (juicio["porque"].get(pid)
                            or "la frase cambia, pero lo que se ve no")
        else:
            rehacer.append(pid)
            motivos[pid] = (juicio["porque"].get(pid)
                            or "la frase ha cambiado y no se ha podido comprobar "
                               "si la imagen sigue valiendo")
    conservar = sorted(set(conservar) - set(rehacer))
    rehacer = sorted(set(rehacer))
    return {
        **analisis,
        "conservar": conservar,
        "rehacer": rehacer,
        "motivos": {pid: motivos.get(pid, "") for pid in conservar + rehacer},
        "juicio": {k: v for k, v in juicio.items() if k != "vale"},
        "resumen": (f"{len(conservar)} planos se conservan, {len(rehacer)} hay "
                    f"que rehacer"),
    }


# ------------------------------------------- de donde sale el antes y el ahora

def guion_locutado(proyecto):
    """El texto con el que se grabo la voz que hay ahora. Es el 'antes' de verdad.

    No se compara contra el guion de la version anterior sino contra lo que se
    LOCUTO: es lo unico que corresponde exactamente al audio y a las imagenes que
    estan en disco. Si alguien regenero el guion dos veces sin pasar por voz, la
    version anterior del guion no describe nada de lo que hay.
    """
    ruta = medios.salida_de(proyecto, "voz", claves=("guion_locutado",),
                            patrones=(r"guion_locutado\.json",))
    documento = medios.leer_json(ruta, {}) if ruta else {}
    bloques = [b for b in (documento.get("bloques") or [])
               if isinstance(b, dict) and b.get("id") and b.get("texto")]
    if bloques:
        return bloques
    # Respaldo: el propio audio_meta guarda el texto de cada bloque cuando lo
    # escribio p4. Vale igual y a veces es lo unico que hay.
    meta = medios.leer_json(
        medios.salida_de(proyecto, "voz", claves=("meta", "audio_meta"),
                         patrones=(r"audio_meta\.json",)) or "", {}) or {}
    return [{"id": b["id"], "texto": b["texto"]}
            for b in (meta.get("bloques") or meta.get("escenas") or [])
            if isinstance(b, dict) and b.get("id") and b.get("texto")]


def guion_ahora(proyecto, estado=None):
    """El guion tal y como esta ahora: el de la version activa, con las ediciones.

    Las ediciones a mano viven en params['bloques'] del paso guion y las aplica
    p3 en su siguiente pasada. Aqui se aplican tambien, porque la pregunta que
    contesta este modulo es "si sigo, ¿que se salva?", y eso incluye lo editado
    y todavia no regenerado.
    """
    documento = medios.leer_json(
        medios.salida_de(proyecto, "guion", claves=("guion",),
                         patrones=(r"guion\.json",)) or "", {}) or {}
    bloques = [dict(b) for b in (documento.get("bloques_detalle")
                                 or documento.get("guion") or [])
               if isinstance(b, dict) and b.get("id")]
    ediciones = {}
    if estado is not None:
        crudas = (estado.params("guion") or {}).get("bloques") or {}
        for clave, valor in crudas.items():
            texto = valor.get("texto") if isinstance(valor, dict) else valor
            texto = " ".join(str(texto or "").split())
            if texto:
                ediciones[str(clave).strip().upper()] = texto
    for bloque in bloques:
        nuevo = ediciones.get(str(bloque.get("id") or "").strip().upper())
        if nuevo:
            bloque["texto"] = nuevo
    return bloques


def _cadencia_de(plan, bloques):
    """Palabras por segundo de la locucion que ya existe. Medida, no supuesta."""
    escenas = (plan or {}).get("escenas") or []
    segundos = sum(float(e.get("duracion") or 0.0) for e in escenas)
    palabras = sum(comun.contar_palabras(e.get("narracion")) for e in escenas)
    if segundos > 5.0 and palabras > 20:
        return palabras / segundos
    return 2.4                       # el ritmo tipico del castellano narrado


def plan_del_proyecto(proyecto, estado=None, ajuste=None, avisar=None,
                      proyecto_id=None, cwd=None, preguntar=True):
    """El plan de conservacion de ESTE proyecto, con sus ficheros en disco.

    Ademas del reparto por planos traduce el resultado a los pasos del grafo,
    que es lo que hay que tocar despues: la voz se conserva por bloques y los
    planos por unidades 'escena:<id>'.
    """
    antes = guion_locutado(proyecto)
    ahora = guion_ahora(proyecto, estado)
    if not antes:
        return {"posible": False,
                "por_que_no": "no hay constancia de con que texto se grabo la voz "
                              "(falta guion_locutado.json). Sin eso no se puede "
                              "saber que ha cambiado, asi que se rehace todo, "
                              "que es lo que se hacia antes.",
                "conservar": [], "rehacer": [], "bloques": {}}
    if not ahora:
        return {"posible": False,
                "por_que_no": "no hay guion que comparar: ejecuta el paso de guion",
                "conservar": [], "rehacer": [], "bloques": {}}

    plan = _plan_de_assets(proyecto)
    ficha = plan_de_conservacion(antes, ahora, plan, ajuste=ajuste, avisar=avisar,
                                 proyecto_id=proyecto_id, cwd=cwd,
                                 cadencia=_cadencia_de(plan, ahora),
                                 preguntar=preguntar)
    ficha["posible"] = True
    ficha["bloques_a_regrabar"] = sorted(
        bid for bid, b in ficha["bloques"].items()
        if b["estado"] in ("retocado", "reescrito", "nuevo"))
    ficha["pasos"] = {
        # La voz se regraba por BLOQUE: lo cosmetico no se toca porque suena
        # igual, y lo retocado si, porque son otras palabras.
        "voz": {"regrabar": ficha["bloques_a_regrabar"]},
        "assets": {"conservar": [f"escena:{p}" for p in ficha["conservar"]],
                   "rehacer": [f"escena:{p}" for p in ficha["rehacer"]]},
        "callouts": {"conservar": [f"escena:{p}" for p in ficha["conservar"]],
                     "rehacer": [f"escena:{p}" for p in ficha["rehacer"]]},
        "render": {"conservar": [f"escena:{p}" for p in ficha["conservar"]],
                   "rehacer": [f"escena:{p}" for p in ficha["rehacer"]]},
    }
    return ficha


def _plan_de_assets(proyecto):
    """El plan de planos vigente, con el origen de cada plano resuelto.

    Los planes hechos antes de que existiera 'origen' no dicen de que bloque
    sale cada plano, y sin eso no se puede conservar nada por bloques. No hace
    falta regenerarlos: el origen se deduce igual cruzando los tiempos del plano
    con los del bloque, que es exactamente lo que hace p6 al planificar.
    """
    try:
        from . import p6_assets
    except ImportError:                    # pasos/ directamente en sys.path
        import p6_assets
    plan = p6_assets.plan_actual(proyecto)
    escenas = plan.get("escenas") or []
    if escenas and not any((e.get("origen") or {}).get("bloque") for e in escenas):
        meta = medios.leer_json(
            medios.salida_de(proyecto, "voz", claves=("meta", "audio_meta"),
                             patrones=(r"audio_meta\.json",)) or "", {}) or {}
        p6_assets._marcar_origen(escenas, meta)
    return plan


def aplicar(estado, ficha, motivo="", quien="analisis"):
    """Escribe el plan en el grafo: conserva unas unidades y marca otras.

    Las dos cosas en la MISMA operacion y por paso. Conservar sin marcar lo que
    no se conserva seria dar por bueno un video que tiene trozos viejos dentro, y
    eso es exactamente la degradacion silenciosa que este sistema no se permite.
    """
    if not ficha.get("posible"):
        raise RuntimeError(ficha.get("por_que_no")
                           or "no hay nada que conservar todavia")
    hecho = {}
    for paso, reparto in (ficha.get("pasos") or {}).items():
        if paso == "voz":
            continue                       # la voz no va por unidades del grafo
        conservar = [u for u in reparto.get("conservar") or []]
        rehacer = [u for u in reparto.get("rehacer") or []]
        if not conservar and not rehacer:
            continue
        try:
            hecho[paso] = estado.adoptar(paso, unidades=conservar,
                                         rehacer=rehacer, motivo=motivo,
                                         quien=quien)
        except ValueError as fallo:
            # el paso no ha producido nada todavia: no hay nada que conservar y
            # tampoco nada que estropear
            hecho[paso] = {"paso": paso, "sin_hacer": str(fallo)}
    return hecho


def _llamar_claude(instruccion, modelo, esfuerzo, cwd, avance=None):
    """Se llama asi para poder engancharle el medidor de coste, que va POR NOMBRE."""
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        sistema=SISTEMA, herramientas_vetadas=HERRAMIENTAS_VETADAS,
        extra=["--no-session-persistence"], avance=avance,
        para="el analisis de que se puede conservar")
