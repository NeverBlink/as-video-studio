"""QUE CLASE DE PLANO es cada uno: la escalera de cartas y su reparto.

NO CONFUNDIR CON cartelas.py, que es el texto que se escribe sobre la imagen.
Aqui una "carta" es una clase de encuadre -- una vista aerea, un detalle macro,
una silueta a contraluz --, y lo unico que produce este modulo es cual le toca a
cada plano.

DE DONDE VIENE
--------------
Esto era la mitad viva de `planos3d.py`, que construia un blockout 3D por plano
en Blender. La caja se retiro entera el 23-08-2026; la carta
no, porque nunca dependio de ella: pedirle a un modelo de imagen «haz un plano
distinto» devuelve el mismo plano medio con otras palabras, y decidirlo ANTES
--este es un aereo, el siguiente un detalle macro-- es lo que produce ritmo.

Cada carta lleva su `encuadre` en ingles, que entra en el prompt del plano como
SHOT TYPE obligatorio y es lo unico que fija el cuadro. Las cartas ya no llevan
numeros de camara (distancia, altura, focal): eran para Blender y no los leia
nadie mas.

LO QUE NO PUEDE CAMBIAR
-----------------------
El reparto es DETERMINISTA y tiene que seguir siendolo: la imagen de un plano se
cachea por su prompt, y el encuadre va en el prompt. Cambiar el orden de la
escalera, un peso o un texto de `encuadre` le cambia la carta a planos que narran
exactamente lo mismo, y eso se paga en imagenes. Por eso al retirar la caja se
conservaron los ids, las familias, los pesos y el orden EXACTOS.
"""
import medios


# --------------------------------------------------------------- la escalera

#: Las clases de plano que se van alternando.
#:
#: 'familia' es lo que impide que dos planos seguidos se parezcan: dos cartas de
#: la misma familia miran el mundo igual aunque cambien de nombre.
#:
#: 'peso' inclina el reparto sin cerrarlo: un documental es sobre todo gente y
#: sitios, y si los detalles macro salieran tanto como el plano medio el video
#: pareceria un anuncio.
#:
#: 'abstracta' marca las que no ocurren en ningun sitio fisico. Lo lee el prompt
#: del plano: un diagrama no se rueda en «la sede del banco», asi que su sitio
#: se sustituye por una base conceptual.
ESCALERA = (
    {"id": "aereo", "familia": "lejos", "peso": 2, "nombre": "vista aerea",
     "encuadre": ("a high aerial bird's-eye shot looking steeply down on the "
                  "scene from far above, wide angle, the whole layout visible "
                  "and the people small within it")},

    {"id": "general", "familia": "lejos", "peso": 3, "nombre": "plano general",
     "encuadre": ("a wide establishing shot from far back, the figures small "
                  "inside a large space, plenty of air above and around them")},

    {"id": "contrapicado", "familia": "angulo", "peso": 2,
     "nombre": "contrapicado extremo",
     "encuadre": ("an extreme low-angle shot from near the floor tilted sharply "
                  "up, towering vertical lines, the subject looming over the "
                  "viewer")},

    {"id": "cenital", "familia": "angulo", "peso": 2, "nombre": "cenital",
     "encuadre": ("a top-down overhead shot looking straight down on the surface "
                  "below, the objects arranged flat within the frame")},

    {"id": "detalle", "familia": "cerca", "peso": 3, "nombre": "detalle macro",
     "encuadre": ("an extreme close-up of one single object filling the frame, "
                  "shallow depth, everything behind it out of focus and abstract")},

    {"id": "retrato", "familia": "cerca", "peso": 3, "nombre": "retrato cerrado",
     "encuadre": ("a tight close-up portrait of the face and shoulders, long "
                  "lens, the background simple and far behind")},

    {"id": "hombro", "familia": "medio", "peso": 2, "nombre": "sobre el hombro",
     "encuadre": ("an over-the-shoulder shot, the back and shoulder of one "
                  "figure large and dark on one side of the frame, the subject "
                  "of their attention beyond")},

    {"id": "silueta", "familia": "luz", "peso": 2,
     "nombre": "silueta a contraluz",
     "encuadre": ("a backlit silhouette shot: the figure is a dark shape against "
                  "a large bright opening behind, almost no detail on the figure "
                  "itself")},

    {"id": "entre", "familia": "luz", "peso": 2,
     "nombre": "mirando entre las cosas",
     "encuadre": ("a shot framed through a gap: something in the immediate "
                  "foreground partly blocks the view from the edges, the subject "
                  "seen through the opening between")},

    {"id": "perfil", "familia": "medio", "peso": 2, "nombre": "perfil lateral",
     "encuadre": ("a flat side-on profile shot, the subject seen exactly from "
                  "the side against a background parallel to the frame, almost "
                  "graphic")},

    {"id": "suelo", "familia": "angulo", "peso": 1, "nombre": "a ras de suelo",
     "encuadre": ("a ground-level shot with the camera resting on the floor, the "
                  "floor filling the lower half of the frame, everything seen "
                  "from below")},

    {"id": "hueco", "familia": "lejos", "peso": 1, "nombre": "el sitio vacio",
     "encuadre": ("an empty establishing shot of the place with no people in it "
                  "at all, still and quiet, the traces of what happened left "
                  "behind")},

    # -------- cartas ABSTRACTAS: sin caja posible, solo en geometria 'directa'.
    # No llevan "plano" porque no hay nada que construir en Blender: son planos
    # que no ocurren en un sitio fisico. Es lo que ese modo gana -- un documental
    # que funciona tambien corta a un diagrama, a una pantalla o a una metafora,
    # no solo a otra habitacion -- y siempre con los monigotes y el estilo del
    # video, que lo imponen las referencias de estilo, no la carta.
    {"id": "diagrama", "familia": "abstracta", "peso": 2, "abstracta": True,
     "nombre": "diagrama",
     "encuadre": ("a clean explanatory diagram filling the frame: simple flat "
                  "shapes, thick arrows and short labels laid out on a plain "
                  "graphic background, the idea drawn as a chart rather than a "
                  "place, with small stick figures integrated as part of the "
                  "diagram")},

    {"id": "pantalla", "familia": "abstracta", "peso": 2, "abstracta": True,
     "nombre": "pantalla",
     "encuadre": ("a full-frame computer screen taking up the entire image: "
                  "terminal windows, scrolling code, progress bars and blinking "
                  "cursors drawn flat in the video's own style, slightly angled "
                  "as if glowing in a dark room, no visible person unless the "
                  "scene names one")},

    {"id": "eterea", "familia": "abstracta", "peso": 1, "abstracta": True,
     "nombre": "composicion eterea",
     "encuadre": ("an abstract conceptual composition floating on an empty "
                  "backdrop: the subject suspended in space among drifting "
                  "symbolic elements, no floor, no walls, no horizon, a visual "
                  "metaphor of the idea rather than a scene")},
)

POR_ID = {carta["id"]: carta for carta in ESCALERA}


# ------------------------------------------------ la escalera SENCILLA (01-10)
#
# LA ESCALERA DE ARRIBA ES LA MITAD DE LOS FALLOS DE UN VIDEO. Medido en un
# video largo (30-09-2026, 281 planos, 117 notas de repaso): de las quince
# cartas, ocho piden algo que el generador dibuja mal con monigotes -- un
# cenital de gente sentada (salen atravesando la mesa), una vista aerea con cola
# de publico (una muchedumbre de manos), un contrapicado extremo (el telefono
# salio dos veces), «a traves de un hueco» y «sobre el hombro» (meten en el
# cuadro una figura o unos objetos que nadie pidio), una silueta (el cable del
# telefono salio doble)--, y la regla de no repetir FAMILIA en dos planos
# obligaba a ir saltando entre ellas: no habia un plano medio normal en toda la
# escalera. El ritmo salia de pedir el angulo mas dificil cada tres planos.
#
# Esta es la que usan los catalogos nuevos (`catalogo["sencillo"]`, ver
# p6_assets._asignar_cartas): planos a la altura de los ojos, y el ritmo lo da
# el TAMANO (entero, medio, retrato, detalle) en vez del angulo. Hacia donde
# mira cada uno no lo fija la carta: lo decide la direccion del plano.
#
# La de arriba se queda tal cual para los videos hechos -- ver «LO QUE NO PUEDE
# CAMBIAR» en la cabecera --, y por eso las cartas que se comparten son LAS
# MISMAS (mismo id, mismo texto) y las nuevas tienen id propio. `carta_de` y
# `repartir` no se tocan: un catalogo sin la marca reparte carta por carta
# como siempre.
SOLO_SENCILLA = {
    "entero": {
        "id": "entero", "familia": "lejos", "nombre": "cuerpo entero",
        "encuadre": ("an eye-level full shot: the whole figure seen from head to "
                     "floor, in a simple setting with calm empty space around "
                     "them")},
    "medio": {
        "id": "medio", "familia": "medio", "nombre": "plano medio",
        "encuadre": ("an eye-level medium shot: the subject seen from the waist "
                     "up, the background simple and quiet behind them")},
    "picado": {
        "id": "picado", "familia": "angulo", "nombre": "picado suave",
        "encuadre": ("a gentle high-angle shot from slightly above eye level, "
                     "looking a little down on the subject, the floor visible "
                     "around them")},
    "contrapicado_suave": {
        "id": "contrapicado_suave", "familia": "angulo",
        "nombre": "contrapicado suave",
        "encuadre": ("a gentle low-angle shot from slightly below eye level, "
                     "looking a little up at the subject, plain wall, ceiling or "
                     "sky behind")},
    "esquema": {
        "id": "esquema", "familia": "abstracta", "abstracta": True,
        "nombre": "esquema",
        "encuadre": ("a clean explanatory diagram filling the frame: two to four "
                     "simple flat shapes, a few thick arrows and at most three "
                     "short labels on a plain graphic background, the idea drawn "
                     "as a chart rather than a place, with no people in it")},
    "simbolo": {
        "id": "simbolo", "familia": "abstracta", "abstracta": True,
        "nombre": "simbolo",
        "encuadre": ("one single symbolic object, large and centred on a plain "
                     "flat backdrop, a visual metaphor of the idea: no people, no "
                     "floor and no other objects")},
}

#: La escalera sencilla, con su peso. Ids de la escalera clasica donde la carta
#: es la misma, y de SOLO_SENCILLA donde no.
#:
#: SIN EL PERFIL, a proposito: de perfil la cara de un monigote es medio ojo y
#: una raya, y lo que mas notas se llevo en ese video largo fue justo la
#: expresion. Con el dentro, la simulacion sobre ese mismo video le daba 27
#: planos de 281, porque era la unica otra carta de su familia.
ESCALERA_SENCILLA = (
    ("general", 2), ("entero", 3), ("medio", 4),
    ("retrato", 3), ("detalle", 2), ("picado", 1), ("contrapicado_suave", 1),
    ("esquema", 1), ("simbolo", 1), ("hueco", 1),
)

#: Las cartas que NO puede recibir un plano con gente: sin nadie dentro
#: (el sitio vacio, el simbolo, el esquema) o con un objeto llenando el cuadro
#: (el detalle). Con reparto y una de estas, el prompt pide dos cosas que no
#: caben juntas y el generador mete las dos: un objeto enorme y alguien al lado.
SIN_GENTE = ("hueco", "detalle", "simbolo", "esquema")

#: En la escalera sencilla basta con no repetir familia en el plano de al lado:
#: con cartas faciles, lo que se quiere es que el tamano cambie de un plano al
#: siguiente, no obligar a un angulo raro cada tres.
VENTANA_FAMILIA_SENCILLA = 1
VENTANA_CARTA_SENCILLA = 3


def carta_por_id(cid):
    """La carta de ese id, de la escalera clasica o de la sencilla. -> dict o None"""
    return POR_ID.get(cid) or SOLO_SENCILLA.get(cid)


def escalera_sencilla():
    """La escalera sencilla como cartas. -> [dict] (para la pantalla)"""
    return [carta_por_id(cid) for cid, _ in ESCALERA_SENCILLA]


#: Cuantos planos hacia atras se mira para no repetir FAMILIA. Regla dura. Dos y
#: no uno: con uno, 'aereo'-'retrato'-'general' pasa el filtro y el espectador ve
#: dos planos lejanos separados por uno cercano, que es el ritmo de siempre.
VENTANA_FAMILIA = 2

#: Y cuantos para no repetir la MISMA carta. Preferencia, no regla: con quince
#: cartas y videos de cuarenta y ocho planos, exigirlo dejaria sin candidatos.
VENTANA_CARTA = 5


def _repartidas():
    """La escalera expandida por peso, que es sobre lo que se reparte."""
    expandida = []
    for carta in ESCALERA:
        expandida.extend([carta] * max(1, int(carta.get("peso") or 1)))
    return expandida


def _repartidas_sencillas():
    """La escalera sencilla expandida por peso."""
    expandida = []
    for cid, peso in ESCALERA_SENCILLA:
        carta = carta_por_id(cid)
        if carta:
            expandida.extend([carta] * max(1, int(peso)))
    return expandida


def carta_sencilla(sid, previas=(), semilla=0, forzada="", prohibidas=()):
    """Como `carta_de`, pero con la escalera sencilla. Determinista igual.

    `prohibidas` quita esas cartas del reparto (un plano con gente no recibe las
    de sin gente). Lo forzado a mano sigue mandando sobre todo, y se busca en las
    dos escaleras: una decision tomada mirando el video no se rebate sola.
    """
    if forzada and carta_por_id(forzada):
        return carta_por_id(forzada)
    previas = [str(p) for p in (previas or [])]
    vetadas = {(carta_por_id(p) or {}).get("familia")
               for p in previas[-VENTANA_FAMILIA_SENCILLA:]}
    vetadas.discard(None)
    recientes = set(previas[-VENTANA_CARTA_SENCILLA:])
    fuera = set(prohibidas or ())
    fondo = [c for c in _repartidas_sencillas() if c["id"] not in fuera]
    if not fondo:
        fondo = _repartidas_sencillas()
    arranque = medios.desempatar(semilla, sid, "carta") % len(fondo)
    orden = [fondo[(arranque + i) % len(fondo)] for i in range(len(fondo))]
    libres = [c for c in orden if c["familia"] not in vetadas]
    if not libres:
        return orden[0]
    frescas = [c for c in libres if c["id"] not in recientes]
    return (frescas or libres)[0]


def repartir_sencillo(escenas, semilla=0, forzadas=None):
    """Una carta por plano con la escalera sencilla, mirando QUIEN sale.

    Un plano con gente no recibe ninguna de las que no llevan a nadie
    (`SIN_GENTE`). Va aparte de `repartir` y no con una bandera dentro: asi el
    reparto de un catalogo de antes no pasa ni por una linea nueva.
    """
    forzadas = forzadas or {}
    cartas, previas = {}, []
    for escena in escenas or []:
        sid = escena.get("id")
        if not sid:
            continue
        prohibidas = SIN_GENTE if escena.get("personajes") else ()
        carta = carta_sencilla(sid, previas, semilla, forzadas.get(sid, ""),
                               prohibidas=prohibidas)
        cartas[sid] = carta
        previas.append(carta["id"])
    return cartas


def carta_de(sid, previas=(), semilla=0, forzada=""):
    """Que clase de plano es este. Determinista, y nunca la familia de al lado.

    'previas' son los ids de carta de los planos que van justo antes, en orden.
    De ahi salen las dos reglas: dura contra la familia (ver VENTANA_FAMILIA) y
    blanda contra la carta (ver VENTANA_CARTA).

    Determinista porque replanificar no puede rebarajar el video: un plano que
    narra lo mismo tiene que salir con la misma carta, o su prompt cambia y se
    vuelve a pagar una imagen que ya estaba bien.

    'forzada' es el id que haya pedido una persona para ESE plano, y manda sobre
    todo lo demas. Una decision tomada mirando el video no se rebate sola.
    """
    if forzada and forzada in POR_ID:
        return POR_ID[forzada]
    previas = [str(p) for p in (previas or [])]
    vetadas = {(POR_ID.get(p) or {}).get("familia")
               for p in previas[-VENTANA_FAMILIA:]}
    vetadas.discard(None)
    recientes = set(previas[-VENTANA_CARTA:])
    fondo = _repartidas()
    arranque = medios.desempatar(semilla, sid, "carta") % len(fondo)
    orden = [fondo[(arranque + i) % len(fondo)] for i in range(len(fondo))]
    libres = [c for c in orden if c["familia"] not in vetadas]
    if not libres:
        return orden[0]
    frescas = [c for c in libres if c["id"] not in recientes]
    return (frescas or libres)[0]


def repartir(escenas, semilla=0, forzadas=None):
    """Una carta por plano, en orden y con las dos reglas puestas.

    Va aparte de `carta_de` porque el reparto depende del ORDEN -- cada plano
    mira los que tiene delante --, y eso es una decision del conjunto.
    """
    forzadas = forzadas or {}
    cartas, previas = {}, []
    for escena in escenas or []:
        sid = escena.get("id")
        if not sid:
            continue
        carta = carta_de(sid, previas, semilla, forzadas.get(sid, ""))
        cartas[sid] = carta
        previas.append(carta["id"])
    return cartas
