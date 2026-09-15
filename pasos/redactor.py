"""EL PROMPT DE CADA PLANO, ESCRITO ENTERO POR UN AGENTE.

QUE ES Y EN QUE SE DIFERENCIA DE `direccion`
--------------------------------------------
`direccion` escribe UNA LINEA por plano --que se ve-- y el codigo la encaja
entre el sitio, el reparto, el tono y la frase narrada. Esto escribe TODO ese
parrafo: el sitio, quien sale, que hace, la luz y la cara que ponen. El codigo
deja de concatenar modulos y pasa a citar lo que el agente entrego.

POR QUE (07-09-2026)
--------------------
Porque los fallos que se vieron en el video del oro eran todos del ENSAMBLADOR,
no de sus piezas: la descripcion del sitio pegada a una frase que ya se habia
ido de el; los 480 caracteres de la descripcion de un personaje que el mismo
prompt declaraba subordinados a su hoja adjunta; el tono del tramo aplicado a un
plano que pedia otro; y 5.713 caracteres de reglas peleando por la ultima
posicion. Cada arreglo fue quitarle peso a un modulo que no venia a cuento en
ESE plano. Un agente que lo redacta con todo delante no mete lo que no toca.

Medido antes de escribir esto: de 19.193 caracteres de prompt, 236 --el 1,2 %--
describian el plano. Los demas eran los mismos en los 299.

LO QUE NO REDACTA, Y NO ES CONSERVADURISMO
-------------------------------------------
Tres bloques se CITAN literales y no se reescriben:

  · LA GUIA DE ESTILO. Es lo que hace que el video parezca un solo trabajo, y
    va con su lamina adjunta. La pone el codigo, igual que antes.
  · LA DESCRIPCION DEL SITIO, cuando el plano usa un sitio del catalogo. Es la
    razon por la que el 28-08 se descarto esta misma idea: «la descripcion del
    sitio es lo que hace que dos planos del mismo sitio PAREZCAN el mismo sitio,
    y reescribirla plano a plano es exactamente como se pierde la continuidad».
    Aqui el agente la copia literal, y si no lo hace se la pone `_limpiar`
    delante y se avisa. La continuidad no depende de que obedezca.
  · LA IDENTIDAD DEL REPARTO. Va en la hoja adjunta; el agente nombra al
    personaje por su identificador y no vuelve a describir su cara.

Y hay dos cosas que decide el codigo y el agente NO puede contradecir: el
ENCUADRE (lo reparte `encuadres` para que dos vecinos no compartan camara) y
las reglas que existen porque las rompe el MODELO DE IMAGEN --no inventar
letras, la regla de especie, un personaje una sola vez--, que siguen entrando
en el prompt.

QUE ES DETERMINISTA
-------------------
Lo mismo que `direccion`: el agente decide UNA VEZ, se guarda por unidad en los
params y a partir de ahi es un dato. El mismo plan da el mismo prompt.

Y ES OPCIONAL. Un plano sin prompt redactado se arma como siempre.
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import medios  # noqa: E402

try:
    from . import cli_claude, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import estadisticas

PASO = "redactor"

#: Tope de largo del parrafo redactado. No es «para que no ahogue la frase»
#: --eso ya se midio mal una vez en `direccion`-- sino contra el unico modo de
#: fallo que tiene un redactor libre: describir el sitio otra vez con otras
#: palabras hasta contradecirse. Con 160 palabras cabe de sobra un plano
#: completo (los de `direccion` mas su sitio rondan las 110).
PALABRAS_MAXIMAS = 160
PALABRAS_MINIMAS = 12

MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]
TIEMPO_BASE_S = 700

HERRAMIENTAS_VETADAS = ("WebFetch", "WebSearch", "Task", "NotebookEdit")

INSTRUCCION = """Eres el director de fotografia de un video explicativo animado
titulado «{titulo}», y escribes EL ENCARGO COMPLETO de cada plano para el modelo
de imagen.

El video ya esta cortado en planos, con su frase de narracion y su tipo de plano
decididos. Lo que escribes tu es el parrafo que describe QUE SE VE.

=====================================================================
COMO SE USA LO QUE ESCRIBES
=====================================================================

Tu parrafo se manda al modelo de imagen precedido SIEMPRE de estas tres cosas,
que no escribes tu y que NO tienes que repetir:

  1. la guia de estilo del video (va entera, y ademas con una lamina adjunta);
  2. la presentacion de las imagenes que se adjuntan a ESE plano (la hoja de
     cada personaje que sale, y una foto del plano anterior si ocurre en el
     mismo sitio);
  3. las reglas de la casa sobre letras, manos, expresiones y luz.

Y detras de tu parrafo van, tambien puestos por el codigo: la frase narrada, el
TIPO DE PLANO y la hora del dia. O sea que NO escribas «this shot accompanies
the narration», ni el encuadre, ni repitas el estilo.

Escribe en INGLES, en prosa, sin listas y sin encabezados. Como mucho
{palabras_maximas} palabras.

=====================================================================
LA GUIA DE ESTILO, PARA QUE ESCRIBAS SABIENDO COMO SE VA A DIBUJAR
=====================================================================
{estilo}
=====================================================================
LOS SITIOS DEL VIDEO
=====================================================================

Cada plano trae abajo los sitios que su tramo del guion tiene disponibles. Si
usas uno, COPIA SU DESCRIPCION LITERAL, palabra por palabra, al principio de tu
parrafo, y declara su identificador en el campo `set`. No la resumas y no la
reescribas: que dos planos del mismo sitio lleven EXACTAMENTE el mismo texto es
lo unico que hace que se lean como la misma habitacion y no como dos parecidas.

{sitios}
{reparto}
=====================================================================
LO QUE DECIDES TU, PLANO A PLANO
=====================================================================

1 · EN QUE SITIO OCURRE. Casi siempre es uno de los que trae su tramo. Pero un
    tramo puede empezar contando una cosa y acabar contando otra, y entonces su
    sitio no vale. La pregunta, en cada plano:

        ¿lo que dice ESTA frase se puede ENSENAR en este sitio?

    Si no, escribe TU el sitio entero (y deja `set` vacio). Ejemplos reales de
    este mismo video, y solo dos cambian de pais o de siglo:

      · «HOY siguen dando para la compra del mes» con una cocina de 1925 de
        sitio: lo que la frase pide es la caja de un supermercado de hoy.
      · «con billetes que servian para encender la chimenea» con un muro de
        mapamundi de sitio: pide una estufa con los billetes ardiendo.
      · «Comprarla para casa cuesta» con una factura sobre una mesa de oficina:
        una caja fuerte en una casa no se ve en una oficina.
      · «Custodiarlo con un tercero cuesta», el plano siguiente, con la misma
        factura: una camara acorazada ajena tampoco se ve alli.

    Lo que NO es irse: una frase abstracta que se puede ESCENIFICAR en el sitio.
    Un sitio compartido es lo que hace que unos planos seguidos parezcan la
    misma escena y no postales sueltas, asi que no lo rompas por gusto.

    Y una tercera salida, cuando la frase es una cifra, una comparacion o un
    mecanismo: no la ilustres con una vista de ningun sitio, monta un DIAGRAMA
    plano sobre fondo grafico, con el mismo trazo y la misma paleta del video.

2 · QUE PASA EN EL CUADRO. Que hay en primer termino y que objeto manda. Que
    hace cada personaje y hacia donde mira. El detalle concreto que hace que
    este plano sea ESTE y no otro del mismo sitio: lo que una pantalla esta
    mostrando, un objeto que entra o sale, una puerta que se abre.

    DOS PLANOS VECINOS NO PUEDEN SER LA MISMA ESCENA VISTA DESDE OTRO SITIO. Es
    el fallo que mas se nota en el montado: al pedir «lo mismo desde otro
    angulo» sale parecido pero no igual, y quien lo ve no lee «otro angulo», lee
    un error. O cada uno ensena algo DISTINTO, o el segundo continua al primero
    diciendo QUE HA CAMBIADO.

3 · QUIEN SALE. Solo quien esta FISICAMENTE ahi en ese momento del relato. De
    alguien se puede HABLAR sin que este en la habitacion, y meterlo porque la
    frase lo nombra es como el grupo atacante acabo dibujado dentro de la
    oficina que lo buscaba.

    Nombra a cada uno por su identificador entre comillas --the character
    'banquero_central'-- y NO describas su cara, su pelo ni su ropa: su hoja va
    adjunta y manda sobre cualquier cosa que escribas. Si el plano necesita a
    alguien generico (un cliente, un empleado), no nombres a nadie del reparto:
    escribe «a generic figure» y ya.

    CADA UNO APARECE UNA SOLA VEZ EN EL CUADRO. Si describes una foto, una ficha
    o una cara en una pantalla, esa persona NO puede estar ademas de cuerpo
    presente.

4 · LA CARA QUE PONEN, Y ES OBLIGATORIA. En TODO plano en el que salga gente
    escribes la expresion --boca, cejas y mirada-- y escribes LA QUE PIDE ESA
    FRASE, no una cara de compromiso:

      · si lo que se dice es malo para quien sale (pierde, no le llega, se
        queda sin algo), la cara es de eso;
      · si es BUENO para quien sale (le alcanza, lo consigue, celebra),
        **sonrie**, y hay que escribirlo: la sonrisa esta prohibida por defecto
        en el negativo del prompt, asi que la unica forma de que alguien sonria
        es que tu lo pidas;
      · si esta explicando, trabajando o mirando, es neutra -- que NO es una
        cara de enfado.

    Un plano con gente sin expresion no sale «como toque»: sale SERIO, porque el
    negativo prohibe la sonrisa. Paso de verdad: una familia que puede comer un
    mes entero con cinco gramos de oro salio con cara de enfado.

    Se comprueba antes de gastar un centimo (`redactor.sin_declarar`), y si aun
    asi falta, el codigo le pone la del tono de su tramo -- que es mejor que
    nada y peor que la que hubieras escrito tu.

5 · LAS LETRAS DENTRO DEL DIBUJO. Se pueden, y aqui esta el limite duro, porque
    es donde el modelo de imagen falla:

      · COMO MUCHO DOS rotulos en toda la imagen. Uno es mejor. Ninguno vale.
      · Cada uno CORTO --tres o cuatro palabras, ocho como techo-- y GRANDE, que
        se lea de un vistazo ocupando parte real del cuadro.
      · Lo pides entrecomillado y con su sitio: «a shop sign reading "PRENSA"».
      · **EN EL IDIOMA DEL VIDEO, que es {idioma}.** El generador dibuja tal cual
        lo que va entre comillas, asi que un rotulo en ingles sale en ingles
        dentro de un video en otro idioma. Tu escribes el parrafo EN INGLES,
        pero lo de las comillas es del mundo del video y no de este encargo: va
        en el idioma del video, bien escrito y con sus tildes. Excepcion: los
        nombres propios --marcas, siglas, instituciones, topónimos, títulos de
        obras reales-- se escriben como en el mundo real y no se traducen.
      · TODA superficie que podria llevar texto y no has pedido --una portada,
        una pantalla, un cartel, una etiqueta-- se describe SIN palabras, con
        trazos ondulados ilegibles que se leen como texto de lejos.

    Paso de verdad, y es lo que esta regla viene a cerrar: un plano de un
    quiosco salio con NUEVE titulares de cuatro palabras, pequenos, y tres mal
    escritos. Cada uno cumplia el limite de palabras; el conjunto era una pared
    de letra pequena. Si no puede ser corto Y grande, no lo pidas escrito.

=====================================================================
LOS PLANOS ({cuantos}, y los quiero TODOS)
=====================================================================
{planos}

DEVUELVE ESTE JSON:

{{"planos": {{"<id>": {{"set": "<id del sitio del catalogo, o cadena vacia>",
                      "prompt": "<el parrafo, en ingles>"}}}}}}

Los {cuantos} planos, ninguno menos y ninguno de mas.
"""


def _estilo_legible(estilo):
    """La guia de estilo tal y como la va a recibir el modelo de imagen."""
    try:
        from . import p6_assets                                  # noqa: PLC0415
    except ImportError:                                          # pragma: no cover
        import p6_assets                                         # noqa: PLC0415
    lineas = list(p6_assets.guia_escrita(estilo or {}))
    return "\n".join("  " + l for l in lineas) if lineas else "  (sin guia escrita)"


def _sitios_de(escena):
    """Los identificadores de sitio que su tramo pone a disposicion del plano.

    Los anota `app._correr_redactor` a partir de `p6_assets.opciones_de_tramo`.
    Con la clave vacia el plano no tiene donde elegir y se lo inventa todo, que
    es el comportamiento correcto para un plano sin beat.
    """
    return [s for s in ((escena or {}).get("_sitios") or []) if s]


def _sitios_legibles(catalogo, escenas):
    """Los sitios QUE SE USAN, con la descripcion que hay que copiar literal."""
    sets = (catalogo or {}).get("sets") or {}
    usados = []
    for escena in escenas:
        for nombre in _sitios_de(escena) or [escena.get("set")]:
            if nombre and nombre not in usados:
                usados.append(nombre)
    lineas = []
    for nombre in usados:
        ficha = sets.get(nombre) or {}
        texto = ficha.get("prompt") or ficha.get("descripcion") or ""
        lineas.append(f"  [{nombre}] {' '.join(str(texto).split())}")
    return "\n".join(lineas) or "  (este video no usa sitios del catalogo)"


def _reparto_legible(catalogo, escenas):
    """Quien puede salir, por su identificador. Sin describir caras: van en su hoja."""
    reparto = (catalogo or {}).get("reparto") or {}
    quienes = []
    for escena in escenas:
        for quien in escena.get("personajes") or []:
            if quien not in quienes:
                quienes.append(quien)
    if not quienes:
        return ""
    lineas = ["", "EL REPARTO (su hoja va adjunta; no describas su cara):"]
    for quien in quienes:
        ficha = reparto.get(quien) or {}
        que = "grupo" if ficha.get("grupo") else "personaje"
        lineas.append(f"  '{quien}' ({que})")
    return "\n".join(lineas) + "\n"


def _planos_legibles(escenas, catalogo=None):
    """Cada plano con lo que decide el codigo y lo que tiene disponible."""
    sets = (catalogo or {}).get("sets") or {}
    lineas = []
    for escena in escenas:
        cabeza = f"[{escena.get('id')}]"
        encuadre = " ".join(str(escena.get("encuadre") or "").split())
        if encuadre:
            cabeza += f" tipo de plano (lo pone el codigo, no lo contradigas): {encuadre}"
        cuerpo = [f"    SE DICE AQUI: {str(escena.get('narracion') or '').strip()}"]
        disponibles = _sitios_de(escena)
        if disponibles:
            cuerpo.append("    sitios que su tramo pone a mano: "
                          + ", ".join(f"[{s}]" for s in disponibles))
        gente = ", ".join(f"'{q}'" for q in (escena.get("personajes") or []))
        if gente:
            cuerpo.append(f"    esta fisicamente ahi: {gente}")
        acciones = [a for a in (escena.get("_acciones") or []) if a]
        if acciones:
            cuerpo.append("    de que va este trozo del guion (contexto, no es "
                          "el encargo): " + " / ".join(acciones))
        lineas.append(cabeza + "\n" + "\n".join(cuerpo))
    return "\n".join(lineas)


def dirigible(escena):
    """Si este plano admite prompt redactado: los que GENERAN una imagen."""
    try:
        from . import direccion                                  # noqa: PLC0415
    except ImportError:                                          # pragma: no cover
        import direccion                                         # noqa: PLC0415
    return direccion.dirigible(escena)


def limpiar_ficha(ficha, sets=None, disponibles=()):
    """Una ficha aceptable, o (None, motivo).

    LA DESCRIPCION DEL SITIO SE GARANTIZA AQUI, no se pide por favor. Si el
    agente declara un `set` del catalogo y no ha copiado su descripcion literal,
    se le pone delante y se avisa: la continuidad entre dos planos del mismo
    sitio no puede depender de que un agente obedezca una instruccion.
    """
    if isinstance(ficha, str):
        ficha = {"prompt": ficha, "set": ""}
    if not isinstance(ficha, dict):
        return None, "no es un objeto con 'prompt'"
    crudo = " ".join(str(ficha.get("prompt") or "").split())
    crudo = re.sub(r'^["\'`]+|["\'`]+$', "", crudo).strip()
    if not crudo:
        return None, "vacia"
    palabras = crudo.split()
    if len(palabras) < PALABRAS_MINIMAS:
        return None, f"solo {len(palabras)} palabra(s): no describe un plano"
    aviso = ""
    if len(palabras) > PALABRAS_MAXIMAS:
        crudo = " ".join(palabras[:PALABRAS_MAXIMAS]).rstrip(",;:")
        aviso = (f"{len(palabras)} palabras, se recorta a {PALABRAS_MAXIMAS}: "
                 f"a partir de ahi vuelve a describir el sitio")
    nombre = str(ficha.get("set") or "").strip()
    if nombre and disponibles and nombre not in disponibles:
        aviso = (aviso + "; " if aviso else "") + \
            f"declara el sitio '{nombre}', que no es de su tramo"
    descrito = ((sets or {}).get(nombre) or {}) if nombre else {}
    literal = " ".join(str(descrito.get("prompt")
                           or descrito.get("descripcion") or "").split())
    if literal and literal.lower() not in crudo.lower():
        crudo = f"{literal}. {crudo}"
        aviso = (aviso + "; " if aviso else "") + \
            "no copio la descripcion del sitio: se le pone delante"
    return {"set": nombre, "prompt": crudo}, aviso


def _limpiar(crudo, escenas, catalogo=None):
    """Valida lo que devuelve el agente contra los planos pedidos."""
    sets = (catalogo or {}).get("sets") or {}
    por_id = {e["id"]: e for e in escenas}
    salida, avisos = {}, []
    if not isinstance(crudo, dict):
        return salida, ["la respuesta no trae un objeto de planos"]
    planos = crudo.get("planos") if isinstance(crudo.get("planos"), dict) else crudo
    for sid, ficha in (planos or {}).items():
        sid = str(sid).strip().upper()
        if sid not in por_id:
            avisos.append(f"{sid}: no es un plano de este video, se ignora")
            continue
        limpia, motivo = limpiar_ficha(
            ficha, sets, tuple(_sitios_de(por_id[sid])))
        if limpia is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        salida[sid] = limpia
    faltan = [sid for sid in sorted(por_id) if sid not in salida]
    if faltan:
        avisos.append(f"{len(faltan)} plano(s) se han quedado sin prompt: "
                      + ", ".join(faltan[:8]))
    return salida, avisos


def sin_declarar(plan, escenas):
    """Planos con gente cuyo prompt no dice la expresion facial. -> [ids]

    Es la comprobacion que sustituye a pegar la regla en los 299 prompts: en vez
    de exigirselo al modelo de imagen en cada llamada, se comprueba UNA vez
    sobre lo redactado y se dice antes de gastar un centimo.
    """
    # LA MISMA TABLA QUE EL SUELO DEL PROMPT, y no una copia. Aqui habia una
    # tupla igual escrita a mano; `p6_assets._dice_la_cara` la usa para decidir
    # si le pone la expresion del tono a un plano que no la trae, asi que si las
    # dos listas se separan una de las dos miente: o el aviso dice que falta y el
    # prompt no la pone, o al contrario. Se importa aqui dentro para no atar los
    # dos modulos al cargarse.
    try:                                                         # noqa: PLC0415
        from . import p6_assets
    except ImportError:            # con la carpeta pasos suelta en sys.path
        import p6_assets

    pistas = p6_assets.PISTAS_DE_CARA
    flojos = []
    for escena in escenas or []:
        ficha = (plan or {}).get(escena.get("id"))
        if not ficha or not escena.get("personajes"):
            continue
        texto = str(ficha.get("prompt") or "").lower()
        if not any(p in texto for p in pistas):
            flojos.append(escena["id"])
    return flojos


def repetidos(plan, escenas):
    """Prompts IGUALES entre planos, que es el fallo que esto viene a quitar."""
    por_texto = {}
    for escena in (escenas or []):
        ficha = (plan or {}).get(escena.get("id"))
        if not ficha:
            continue
        clave = medios.normalizar_texto(str(ficha.get("prompt") or ""))
        por_texto.setdefault(clave, []).append(escena["id"])
    return [sorted(ids) for ids in por_texto.values() if len(ids) > 1]


def _llamar_claude(instruccion, modelo, esfuerzo, avance=None):
    """Entrega ESCRIBIENDO un fichero: 299 parrafos no caben en un mensaje."""
    return cli_claude.escribiendo(
        instruccion, modelo=modelo, esfuerzo=esfuerzo,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        herramientas_vetadas=HERRAMIENTAS_VETADAS, avance=avance,
        para="los prompts de los planos", que="los prompts de los planos")


def proponer(escenas, ajuste=None, avisar=None, proyecto_id=None, cwd=None,
             titulo="", estilo=None, catalogo=None, idioma=""):
    """Redacta el prompt de cada plano. NO escribe en params: propone."""
    ajuste = ajuste or {}
    modelo = ajuste.get("modelo") or MODELO_POR_DEFECTO
    esfuerzo = ajuste.get("esfuerzo") or ESFUERZO_POR_DEFECTO
    elegido = {"modelo": modelo, "esfuerzo": esfuerzo}

    todos = [e for e in (escenas or []) if e.get("id")]
    if not todos:
        raise RuntimeError("no hay planos: corta la narracion antes")
    dirigibles = [e for e in todos if dirigible(e)]
    if not dirigibles:
        raise RuntimeError("ningun plano de este video genera imagen propia")

    prevision = estadisticas.estimar(PASO, tamano=len(dirigibles), ajuste=elegido)
    avance = None
    if avisar is not None:
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            f"redactando el encargo de los {len(dirigibles)} planos con "
            f"{modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    instruccion = INSTRUCCION.format(
        titulo=titulo or "sin titulo",
        palabras_maximas=PALABRAS_MAXIMAS,
        # EL IDIOMA DEL VIDEO. Ver la regla del rotulo: sin este dato el agente
        # escribe los rotulos en el idioma del ejemplo que tenga delante, que es
        # exactamente como `direccion` acabo pidiendo "CITY OPENS NEW PARK" en
        # un video en castellano (07-09-2026, `video_referencia`: 14 rotulos en ingles).
        idioma=idioma or "el del guion que se te da mas abajo",
        estilo=_estilo_legible(estilo),
        sitios=_sitios_legibles(catalogo, dirigibles),
        reparto=_reparto_legible(catalogo, dirigibles),
        cuantos=len(dirigibles),
        planos=_planos_legibles(dirigibles, catalogo))

    arranque = time.time()
    try:
        crudo = _llamar_claude(instruccion, modelo, esfuerzo, avance)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO, time.time() - arranque, ok=False, ajuste=elegido,
                            proyecto=proyecto_id, resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    plan, avisos = _limpiar(crudo, dirigibles, catalogo)
    for grupo in repetidos(plan, dirigibles):
        avisos.append(f"{' = '.join(grupo)}: el mismo prompt en varios planos")
    flojos = sin_declarar(plan, dirigibles)
    if flojos:
        avisos.append(f"{len(flojos)} plano(s) con gente no declaran la "
                      f"expresion facial (sin ella nadie sonrie nunca): "
                      + ", ".join(flojos[:8]))
    estadisticas.anotar(PASO, segundos, tamano=len(dirigibles), ajuste=elegido,
                        proyecto=proyecto_id, unidades=len(plan),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "planos": len(dirigibles),
                                 "redactados": len(plan)})
    return {
        "plan": plan,
        "avisos": avisos,
        "planos": len(dirigibles),
        "redactados": len(plan),
        "sin_expresion": flojos,
        "ajuste": elegido,
        "segundos": round(segundos, 1),
        "estimacion_s": prevision["segundos"],
    }


def describir(plan, escenas=None):
    """Frase corta para la pantalla."""
    plan = plan or {}
    if not plan:
        return "sin redactar: cada plano se arma juntando sus modulos"
    total = len([e for e in (escenas or []) if dirigible(e)]) or len(plan)
    return f"{len(plan)} de {total} planos con su encargo escrito entero"
