"""Las transiciones entre planos: el catalogo, quien reparte y como se pintan.

DE DONDE SALEN
--------------
Los shaders son los de hyperframes (Apache 2.0), copiados literalmente en
`shaders_hyperframes.py`. Lo que NO se usa de ese proyecto es su tuberia: nuestro
p8 ya es exactamente lo mismo -- HTML, Chrome headless por CDP, un seek por
fotograma y ffmpeg --, asi que meter Node y Puppeteer para eso seria montar un
segundo motor de render al lado del que ya funciona.

POR QUE UNA SEGUNDA PASADA Y NO UNA COMPOSICION EN VIVO
-------------------------------------------------------
Un shader de transicion necesita DOS texturas: el fotograma que sale y el que
entra. Hyperframes las consigue capturando el DOM a un canvas (html2canvas, o la
API experimental de Chrome), que es la parte fragil de su montaje.

Aqui no hace falta: p8 ya escribe TODOS los fotogramas a PNG antes de llamar a
ffmpeg. Asi que las dos texturas son dos ficheros, y la transicion es una pasada
posterior sobre los primeros fotogramas del clip que entra. Sale mas
determinista que el original -- dos PNG identicos y el mismo shader dan el mismo
pixel -- y no depende de ninguna API experimental.

EL RITMO Y EL CATALOGO SON DOS DECISIONES DISTINTAS
---------------------------------------------------
El motor de corte (`motores/guion/segmentar.py`) decide DONDE va un acento: eso
pertenece al corte, se decide con el guion delante y viaja en el plan. Este
modulo decide QUE transicion concreta ocupa ese hueco, y eso se resuelve al
RENDERIZAR. La separacion importa por dinero: cambiar la paleta de transiciones
deja obsoleto el render y nada mas -- ni las imagenes ni las capas.

Las ranuras que deja el plan son tres:

    corte    corte seco. Es la norma, y en un documental narrado tiene que
             seguir siendolo: una transicion en cada corte es un salvapantallas.
    suave    la de despues de una pausa, cuando la frase cierra.
    acento   el golpe de cada pocos planos, en un punto fuerte.

LOS COLORES SON LOS DEL VIDEO
-----------------------------
Los shaders llevan tres uniformes de acento, y ahi entra la paleta derivada de
la guia de estilo (ver p7_callouts.paleta_de_guia). Por eso el destello de un
`light-leak` sale del mismo color que los rotulos: la transicion pertenece a
ESTE video y no es un efecto de catalogo pegado encima.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import medios  # noqa: E402
import shaders_hyperframes as _hf  # noqa: E402

#: El fundido de toda la vida, escrito por nosotros para que TODAS las
#: transiciones pasen por el mismo sitio. Antes vivia en el DOM de la pagina de
#: render (dos capas y una opacidad) y el resto en otro lado; con dos caminos,
#: cualquier arreglo habia que hacerlo dos veces y el fundido se quedaba atras.
#: Lleva la misma cabecera de uniformes que los demas aunque no use casi
#: ninguno: asi el pintor no tiene que saber de que clase es cada shader.
FUNDIDO_GLSL = (
    "precision mediump float;varying vec2 v_uv;"
    "uniform sampler2D u_from, u_to;uniform float u_progress;"
    "uniform vec2 u_resolution;uniform vec3 u_accent;"
    "uniform vec3 u_accent_dark;uniform vec3 u_accent_bright;\n"
    "void main(){gl_FragColor=mix(texture2D(u_from,v_uv),"
    "texture2D(u_to,v_uv),u_progress);}")

# ===========================================================================
# EL CATALOGO
#
# Cada ficha dice lo mismo que hace falta para elegir mirando y para repartir
# sin pensar:
#
#   familia   dos transiciones de la misma familia no van seguidas. Es la misma
#             regla que las cartas de plano (encuadres.carta_de): lo que cansa
#             no es repetir una, es repetir la CLASE.
#   fuerza    1 discreta · 2 se nota · 3 golpe. De aqui salen las dos bolsas:
#             'suave' coge de fuerza <= 2 y 'acento' de fuerza >= 2.
#   factor    multiplica la duracion base. Un latigazo tiene que ser corto o se
#             lee como un barrido; una fuga de luz necesita respirar.
#   defecto   si entra sin que nadie toque nada. La seleccion de fabrica es
#             sobria a proposito: es un documental narrado, no un videoclip.
#             Las catorce estan disponibles y se eligen mirandolas.
# ===========================================================================

CATALOGO = {
    "corte": {
        "nombre": "Corte seco",
        "descripcion": "Sin transicion: el plano siguiente empieza y ya esta. Es la norma del montaje.",
        "familia": "corte", "fuerza": 0, "factor": 0.0,
        "defecto": True, "origen": "estudio",
    },
    "fundido": {
        "nombre": "Fundido",
        "descripcion": "Un plano se disuelve en el otro. Lo de siempre, y lo que mejor cierra una frase.",
        "familia": "mezcla", "fuerza": 1, "factor": 1.0,
        "defecto": True, "origen": "estudio",
    },
    "flash-through-white": {
        "nombre": "Destello blanco",
        "descripcion": "Pasa por blanco a medio camino. El acento clasico: se nota y no distrae.",
        "familia": "destello", "fuerza": 2, "factor": 0.9,
        "defecto": True, "origen": "hyperframes",
    },
    "light-leak": {
        "nombre": "Fuga de luz",
        "descripcion": "Una vela de luz calida entra por una esquina y se lo come todo. Tinta con el acento del video.",
        "familia": "destello", "fuerza": 2, "factor": 1.5,
        "defecto": True, "origen": "hyperframes",
    },
    "sdf-iris": {
        "nombre": "Iris",
        "descripcion": "El plano nuevo se abre en circulo desde el centro, con un anillo encendido en el borde.",
        "familia": "iris", "fuerza": 2, "factor": 1.1,
        "defecto": True, "origen": "hyperframes",
    },
    "cinematic-zoom": {
        "nombre": "Zoom desenfocado",
        "descripcion": "Los dos planos se estiran hacia el centro con desenfoque radial. Muy de cine.",
        "familia": "optica", "fuerza": 2, "factor": 1.4,
        "defecto": True, "origen": "hyperframes",
    },
    "whip-pan": {
        "nombre": "Latigazo",
        "descripcion": "Barrido horizontal con arrastre, como girar la camara de golpe. Corto por definicion.",
        "familia": "barrido", "fuerza": 3, "factor": 0.7,
        "defecto": True, "origen": "hyperframes",
    },
    "chromatic-split": {
        "nombre": "Separacion de color",
        "descripcion": "Los canales rojo y azul se abren del centro y vuelven. Discreta y con nervio.",
        "familia": "optica", "fuerza": 2, "factor": 1.0,
        "defecto": False, "origen": "hyperframes",
    },
    "cross-warp-morph": {
        "nombre": "Deformacion cruzada",
        "descripcion": "Los dos planos se deforman uno hacia el otro con ruido y se funden por manchas.",
        "familia": "disolvencia", "fuerza": 2, "factor": 1.2,
        "defecto": False, "origen": "hyperframes",
    },
    "domain-warp": {
        "nombre": "Disolucion con remolinos",
        "descripcion": "Se disuelve por un frente de ruido retorcido, con el borde encendido en el color de acento.",
        "familia": "disolvencia", "fuerza": 3, "factor": 1.3,
        "defecto": False, "origen": "hyperframes",
    },
    "ridged-burn": {
        "nombre": "Quemado",
        "descripcion": "El plano arde por un frente irregular, con chispas. Como pelicula quemandose.",
        "familia": "disolvencia", "fuerza": 3, "factor": 1.3,
        "defecto": False, "origen": "hyperframes",
    },
    "ripple-waves": {
        "nombre": "Ondas",
        "descripcion": "Ondas concentricas desde el centro deforman los dos planos mientras se cambian.",
        "familia": "onda", "fuerza": 2, "factor": 1.2,
        "defecto": False, "origen": "hyperframes",
    },
    "thermal-distortion": {
        "nombre": "Calor",
        "descripcion": "Temblor de aire caliente subiendo desde abajo. Buena para desiertos, motores y tension.",
        "familia": "onda", "fuerza": 2, "factor": 1.3,
        "defecto": False, "origen": "hyperframes",
    },
    "gravitational-lens": {
        "nombre": "Colapso",
        "descripcion": "El plano que sale se traga hacia el centro con aberracion cromatica, como un agujero negro.",
        "familia": "colapso", "fuerza": 3, "factor": 1.3,
        "defecto": False, "origen": "hyperframes",
    },
    "swirl-vortex": {
        "nombre": "Remolino",
        "descripcion": "Los dos planos giran en espiral en sentidos contrarios. Fuerte: para un salto grande.",
        "familia": "colapso", "fuerza": 3, "factor": 1.2,
        "defecto": False, "origen": "hyperframes",
    },
    "glitch": {
        "nombre": "Glitch",
        "descripcion": "Bloques desplazados, lineas de barrido y color roto. Para senal, camaras y ordenadores.",
        "familia": "digital", "fuerza": 3, "factor": 0.8,
        "defecto": False, "origen": "hyperframes",
    },
}

#: Las que entran si nadie elige nada. Se guarda como lista vacia en los params
#: («entran las de fabrica»), igual que los arquetipos de rotulo.
POR_DEFECTO = tuple(k for k, v in CATALOGO.items() if v["defecto"])

#: Las ranuras que deja el plan. Los nombres viejos siguen entendiendose: hay
#: planes guardados con 'flash' y con 'deslizar', y un plan viejo no puede dejar
#: de renderizar porque hayamos cambiado un vocabulario.
RANURAS = ("corte", "suave", "acento")
RANURA_DE_LO_VIEJO = {
    "corte": "corte",
    "flash": "acento",          # era corte + destello blanco
    "fundido": "suave",
    "deslizar": "suave",        # retirada el 18-08-2026; el plan viejo la trae
}

#: Cuantas transiciones atras se mira para no repetir familia.
VENTANA_FAMILIA = 3

#: Ninguna transicion puede comerse el plano que entra. Un fundido de 0,6 s en
#: un plano de 1,5 s deja de leerse como una transicion y parece que el montaje
#: va lento; el tope es una fraccion de LO QUE DURA el plano.
FRACCION_MAXIMA = 0.35


def frag_de(nombre):
    """El GLSL de esa transicion. El fundido es nuestro; el resto, de hyperframes."""
    if nombre == "fundido":
        return FUNDIDO_GLSL
    return _hf.FRAGMENTOS.get(nombre)




def elegidas_de(params):
    """Las transiciones que entran en este video, validadas contra el catalogo.

    Vacio = las de fabrica, que es como funcionan los arquetipos de rotulo: una
    lista vacia significa «no lo he tocado», no «ninguna».
    """
    pedidas = [str(t) for t in ((params or {}).get("transiciones") or [])]
    validas = [t for t in pedidas if t in CATALOGO and t != "corte"]
    return validas or [t for t in POR_DEFECTO if t != "corte"]


def _bolsas(elegidas):
    """Las dos bolsas de donde sale cada ranura, en el orden del catalogo.

    'fundido' es el respaldo de las suaves y esta siempre disponible aunque
    nadie lo marque: una ranura suave sin nada que poner tendria que degradar a
    corte, y entonces el ritmo del corte -- que se decidio con el guion delante
    -- se perderia por una casilla desmarcada en otra pantalla.
    """
    suaves = [t for t in CATALOGO if t in elegidas and 1 <= CATALOGO[t]["fuerza"] <= 2]
    acentos = [t for t in CATALOGO if t in elegidas and CATALOGO[t]["fuerza"] >= 2]
    return suaves or ["fundido"], acentos or suaves or ["fundido"]


def _sin_repetir_familia(bolsa, arranque, familias_recientes):
    """La primera de la bolsa que no repita familia, empezando por 'arranque'."""
    orden = [bolsa[(arranque + i) % len(bolsa)] for i in range(len(bolsa))]
    libres = [t for t in orden if CATALOGO[t]["familia"] not in familias_recientes]
    return (libres or orden)[0]


def resolver(escenas, params=None, semilla=0):
    """Que transicion concreta lleva cada plano. Determinista.

    Devuelve {id_de_plano: {"tipo","shader","duracion","ranura"}}. El primer
    plano nunca lleva transicion: no hay nada de lo que venir.

    Determinista igual que el reparto de cartas: rehacer el render de un plano
    suelto no puede cambiarle la transicion a otro, o el video se descuadra por
    haber tocado algo que estaba bien.
    """
    p = params or {}
    elegidas = elegidas_de(p)
    suaves, acentos = _bolsas(elegidas)
    base = float(p.get("duracion_transicion") or 0.4)

    salida, familias = {}, []
    for indice, escena in enumerate(escenas or []):
        sid = escena.get("id")
        if not sid:
            continue
        cruda = str(escena.get("transicion") or "suave")
        ranura = cruda if cruda in RANURAS else RANURA_DE_LO_VIEJO.get(cruda, "suave")
        # EL CORTE SECO SE RETIRO el 20-08-2026 (decision del usuario: "no me
        # gusta como queda"). El motor del corte ya no lo reparte, pero los
        # planes GUARDADOS lo traen escrito plano a plano, asi que se traduce
        # aqui tambien: si no, un video ya planificado seguiria saliendo a
        # cortes secos hasta volver a planificarlo, que cuesta dinero.
        if ranura == "corte":
            ranura = "suave"
        # El plano que CONTINUA a otro no encadena: es la segunda mitad de un
        # plano que dura el doble (p6._estirar_cabeceras), asi que los dos
        # fotogramas del corte son la misma imagen. Cualquier transicion ahi
        # seria trabajo de render para no ver nada, y un encadenado sobre si
        # mismo se lee como un parpadeo. No es un corte seco: no hay corte.
        sigue = bool(escena.get("sigue_a")) or (
            bool((escena.get("cartela") or {}).get("sigue_a"))
            if isinstance(escena.get("cartela"), dict) else False)
        # El primer plano si es un corte, y no por gusto: no hay nada de lo que
        # venir. Eso no es una transicion retirada, es la ausencia de una.
        if indice == 0 or sigue:
            salida[sid] = {"tipo": "corte", "shader": None, "duracion": 0.0,
                           "ranura": "corte"}
            continue
        bolsa = acentos if ranura == "acento" else suaves
        arranque = medios.desempatar(semilla, sid, "transicion") % len(bolsa)
        nombre = _sin_repetir_familia(bolsa, arranque,
                                      set(familias[-VENTANA_FAMILIA:]))
        familias.append(CATALOGO[nombre]["familia"])
        duracion = base * float(CATALOGO[nombre]["factor"])
        plano = float(escena.get("duracion") or
                      (float(escena.get("t_out") or 0) - float(escena.get("t_in") or 0)))
        if plano > 0:
            duracion = min(duracion, plano * FRACCION_MAXIMA)
        salida[sid] = {"tipo": nombre, "shader": frag_de(nombre),
                       "duracion": round(max(0.0, duracion), 3), "ranura": ranura}
    return salida


def cuece_el_anterior(ficha):
    """Si esta transicion necesita el ultimo fotograma del plano de antes.

    De aqui sale la cascada del re-render: rehacer un plano obliga a rehacer el
    siguiente SOLO si el siguiente mira hacia atras. El corte no mira.
    """
    return bool(ficha) and ficha.get("tipo") != "corte"


def progresos(fotogramas):
    """El valor de u_progress de cada fotograma de la transicion.

    Ni 0 ni 1: con 0 el primer fotograma del clip seria identico al ultimo del
    anterior (un fotograma repetido en el corte) y con 1 el ultimo seria
    identico al primero limpio. La rampa reparte los N huecos INTERIORES, asi
    que el fotograma N+1 -- el primero sin tocar -- cae justo en 1.
    """
    n = max(0, int(fotogramas))
    return [(i + 1) / float(n + 1) for i in range(n)]


# ------------------------------------------------------------------ pintado

PAGINA = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#000;overflow:hidden}
canvas{display:block;width:__W__px;height:__H__px}
</style></head><body><canvas id="c" width="__W__" height="__H__"></canvas>
<script>
const W = __W__, H = __H__, ACENTO = __ACENTO__;
const gl = document.getElementById('c').getContext('webgl', {
  // sin esto el buffer puede estar vacio cuando el navegador hace la captura:
  // WebGL tiene permiso para tirarlo en cuanto acaba el frame
  preserveDrawingBuffer: true, antialias: false, alpha: false});
if (!gl) throw new Error('sin WebGL');

const VERT = __VERT__;
const quad = gl.createBuffer();
gl.bindBuffer(gl.ARRAY_BUFFER, quad);
gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);

function compilar(tipo, fuente){
  const s = gl.createShader(tipo);
  gl.shaderSource(s, fuente); gl.compileShader(s);
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
    throw new Error('shader: ' + gl.getShaderInfoLog(s));
  return s;
}

const programas = {};
function programa(frag){
  if (programas[frag]) return programas[frag];
  const pr = gl.createProgram();
  gl.attachShader(pr, compilar(gl.VERTEX_SHADER, VERT));
  gl.attachShader(pr, compilar(gl.FRAGMENT_SHADER, frag));
  gl.bindAttribLocation(pr, 0, 'a_pos');
  gl.linkProgram(pr);
  if (!gl.getProgramParameter(pr, gl.LINK_STATUS))
    throw new Error('link: ' + gl.getProgramInfoLog(pr));
  programas[frag] = pr;
  return pr;
}

// Las texturas son de 1920x1080: no son potencia de dos, asi que solo admiten
// CLAMP_TO_EDGE y LINEAR. Con el reglaje por defecto (REPEAT + mipmaps) WebGL
// las da por incompletas y pinta negro, sin avisar de nada.
const texturas = {};
function textura(url){
  if (texturas[url]) return Promise.resolve(texturas[url]);
  return new Promise((ok, mal) => {
    const img = new Image();
    // El try/catch NO es adorno: lo que se lance dentro de un onload no llega a
    // la promesa, asi que sin el una subida de textura que falla deja la
    // promesa colgada para siempre y el render se queda parado sin decir nada.
    img.onload = () => {
      try {
        const t = gl.createTexture();
        gl.bindTexture(gl.TEXTURE_2D, t);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, img);
        texturas[url] = t; ok(t);
      } catch (e) { mal(e); }
    };
    img.onerror = () => mal(new Error('no carga ' + url));
    img.src = url;
  });
}

// El fotograma que ENTRA se usa una sola vez y son cientos: cachearlos llenaria
// la memoria de video. El que SALE es el mismo durante toda la transicion, y
// ese si se guarda.
function soltar(url){
  if (texturas[url]) { gl.deleteTexture(texturas[url]); delete texturas[url]; }
}

async function componer(desde, hasta, progreso, frag){
  const pr = programa(frag);
  const [a, b] = [await textura(desde), await textura(hasta)];
  gl.useProgram(pr);
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.enableVertexAttribArray(0);
  gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
  gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, a);
  gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, b);
  const u = n => gl.getUniformLocation(pr, n);
  gl.uniform1i(u('u_from'), 0);
  gl.uniform1i(u('u_to'), 1);
  gl.uniform1f(u('u_progress'), progreso);
  gl.uniform2f(u('u_resolution'), W, H);
  gl.uniform3fv(u('u_accent'), ACENTO.acento);
  gl.uniform3fv(u('u_accent_dark'), ACENTO.oscuro);
  gl.uniform3fv(u('u_accent_bright'), ACENTO.claro);
  gl.viewport(0, 0, W, H);
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  gl.finish();
  soltar(hasta);
  return 1;
}

// la pagina de render exige un pintar(); aqui no hay linea de tiempo que
// recorrer, cada fotograma se pide por su cuenta
function pintar(t){ return 1; }
</script></body></html>"""


#: El acento cuando no hay guia de estilo (o cuando el color no se puede leer).
#: Es UNA constante y no dos numeros escritos en dos sitios: con el respaldo
#: duplicado, «sin paleta» y «paleta ilegible» daban colores parecidos pero no
#: iguales, y eso es un tono distinto en el destello segun por donde se llegue.
ACENTO_POR_DEFECTO = "#d8a657"


def acentos(paleta):
    """Los tres colores de acento en 0-1, listos para los uniformes.

    El oscuro y el claro se derivan del acento en vez de pedir tres colores:
    la guia de estilo ya da una paleta y anadirle dos papeles nuevos solo para
    esto seria pedirle al modelo que decida algo que es una cuenta.
    """
    crudo = str((paleta or {}).get("linea") or (paleta or {}).get("acento") or "")
    rgb = _componentes(crudo) or _componentes(ACENTO_POR_DEFECTO)
    return {"acento": [round(v, 4) for v in rgb],
            "oscuro": [round(v * 0.45, 4) for v in rgb],
            "claro": [round(min(1.0, v * 1.35 + 0.12), 4) for v in rgb]}


def _componentes(hexa):
    """'#d8a657' -> [0.847, 0.651, 0.341]. None si no es un color legible."""
    crudo = str(hexa or "").strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    if len(crudo) != 6:
        return None
    try:
        return [int(crudo[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None


def pagina(destino, ancho, alto, paleta=None):
    """Escribe la pagina de WebGL que compone las transiciones. Una por render."""
    html = (PAGINA
            .replace("__W__", str(int(ancho)))
            .replace("__H__", str(int(alto)))
            .replace("__VERT__", json.dumps(_hf.VERTICES))
            .replace("__ACENTO__", json.dumps(acentos(paleta))))
    return medios.escribir_texto(destino, html)


def _url(ruta):
    return "file:///" + os.path.abspath(ruta).replace("\\", "/")


def componer(navegador, desde, hasta, progreso, frag, destino):
    """Un fotograma de transicion: `desde` y `hasta` mezclados por el shader.

    Se captura a un fichero aparte y despues se sustituye: `hasta` es el propio
    fotograma que se esta rehaciendo, y escribir encima del PNG que el navegador
    tiene abierto deja medio fichero a medio leer.
    """
    navegador.evaluar(
        "componer(%s,%s,%s,%s)" % (json.dumps(_url(desde)), json.dumps(_url(hasta)),
                                   repr(round(float(progreso), 6)), json.dumps(frag)),
        esperar=True)
    temporal = destino + ".tmp.png"
    navegador.capturar(temporal)
    medios.reemplazar(temporal, destino)
    return destino


def describir(params=None):
    """Frase corta con la paleta de transiciones puesta, para la pantalla."""
    elegidas = elegidas_de(params)
    nombres = [CATALOGO[t]["nombre"] for t in CATALOGO if t in elegidas]
    return ", ".join(nombres) if nombres else "solo cortes secos"


def catalogo_para_pantalla(elegidas=None):
    """El catalogo con el GLSL dentro, para que la pantalla lo pinte de verdad.

    La muestra de la interfaz corre EL MISMO shader que el render, igual que la
    muestra de un arquetipo se dibuja con el mismo codigo que la capa: una
    maqueta hecha aparte se desincroniza y entonces se elige otra cosa.
    """
    puestas = set(elegidas if elegidas is not None else POR_DEFECTO)
    fichas = []
    for tid, ficha in CATALOGO.items():
        if tid == "corte":
            continue
        fichas.append({"id": tid, "puesta": tid in puestas,
                       "frag": frag_de(tid),
                       **{k: ficha[k] for k in
                          ("nombre", "descripcion", "familia", "fuerza",
                           "factor", "defecto", "origen")}})
    # sin 'corte': no es una transicion que se pueda marcar ni desmarcar, es lo
    # que pasa cuando no hay ninguna. Si viajara, la pantalla contaria siete
    # puestas con seis casillas marcadas.
    return {"transiciones": fichas, "vertices": _hf.VERTICES,
            "por_defecto": [t for t in POR_DEFECTO if t != "corte"]}
