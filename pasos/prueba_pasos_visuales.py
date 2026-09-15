"""
Prueba de los pasos 6, 7 y 8 de punta a punta, con su material fabricado aqui.

No es un test de humo: monta un proyecto de verdad sobre el nucleo, con la voz
ya "sintetizada" (audio_meta.json con sus marcas de palabra, mas el wav) y el
arte ya aprobado, y ejecuta la cadena entera hasta el MP4.

EL MATERIAL SE FABRICA EN ESTE FICHERO y no se lee de ningun proyecto: la
locucion es un texto de aqui con las marcas puestas a una cadencia fija, el wav
es un tono del largo exacto, y el arte son PNG dibujados con un sujeto en un
sitio conocido. Eso hace la suite DETERMINISTA --antes el numero de planos
dependia de como hubiera respirado el sintetizador el dia de la toma-- y la deja
corriendo en cualquier maquina que tenga ffmpeg y Edge.

Lo que se comprueba de cada paso:

  p6  corta la narracion, asigna sitio, carta de encuadre y zoom, construye
      los assets y una imagen por plano, y declara que assets usa cada escena.
      Ademas: la cascada. Se toca un asset y quedan obsoletas -- via el nucleo,
      no de mentira -- exactamente las escenas que lo usan.
  p7  coloca los rotulos en el hueco libre verificando por pixeles que no pisan
      al sujeto y calcula el zoom.
  p8  renderiza clip a clip con Edge y ensambla el MP4 con la voz; rehacer un
      plano rehace su clip y no el video entero.

El modo de imagen es "adoptar": el arte ya existe y no se vuelve a pagar. Todo
lo demas (segmentacion, asignacion, mapas, capas, zoom, render, ffmpeg) se
ejecuta de verdad.

Sobre el RECUENTO: esta suite paso de 100 comprobaciones a 98 el 14-08, y no es
una regresion. Dos de sus aserciones van dentro de un bucle POR ROTULO (el
solape verificado y el lado de la linea guia), y desde que la regla es un rotulo
por plano hay menos rotulos que recorrer. A cambio entro la asercion que
comprueba justo esa regla.

POR POWERSHELL Y NO POR BASH: Edge headless devuelve codigo 0 y no escribe el
PNG cuando se lanza desde un shell sandboxeado, asi que la suite falla con
«Edge no genero ...png» sin que nada este roto.

    powershell -NoProfile -Command "python pasos\\prueba_pasos_visuales.py"
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from nucleo.bitacora import Bitacora  # noqa: E402
from nucleo.estado import Estado  # noqa: E402
from nucleo.proyecto import Proyecto  # noqa: E402
from nucleo.trabajos import GestorTrabajos  # noqa: E402

import cartelas  # noqa: E402
import encuadres  # noqa: E402
import medios  # noqa: E402
import p6_assets  # noqa: E402
import p7_callouts  # noqa: E402
import p8_render  # noqa: E402
import sonido  # noqa: E402
import transiciones  # noqa: E402

CARPETA = os.path.join(os.environ.get("TEMP", r"C:\Windows\Temp"),
                       "estudio_prueba_visual")
# el banco de la prueba va en temporal y no en el `banco/` del producto: la
# prueba no
# debe ensuciar el banco real, que es compartido entre proyectos
BANCO_PRUEBA = os.path.join(CARPETA, "_banco")

_fallos = []
_comprobaciones = [0]


def ok(condicion, mensaje):
    _comprobaciones[0] += 1
    if not condicion:
        _fallos.append(mensaje)
        print(f"    FALLO: {mensaje}")
    return bool(condicion)


def igual(obtenido, esperado, mensaje):
    return ok(obtenido == esperado, f"{mensaje} (obtenido {obtenido!r}, "
                                    f"esperado {esperado!r})")


# --------------------------------------------------------------- catalogo

CATALOGO = {
    "luz_por_defecto": "overcast daylight, flat diffuse light",
    "prompt_por_defecto": ("wide establishing shot of the open Pacific ocean at "
                           "night, long calm swells"),
    "sets": {
        "puerto": {
            "palabras": {"puerto": 2, "muelle": 2, "contenedor": 1.5,
                         "contenedores": 1.5, "grua": 1.5, "carguero": 1.5,
                         "buque": 1.5, "manzanillo": 2, "atraca": 1},
            "luz": "overcast daylight over an industrial port, flat grey light",
            "prompt": ("a large industrial container port, stacked shipping "
                       "containers, gantry cranes and a moored cargo ship"),
            "camaras": {
                "general_aereo": {"palabras": ["puerto", "mayor", "industrial"],
                                  "prompt": "the whole container port seen from "
                                            "high above, cranes and stacked containers"},
                "medio_grua": {"palabras": ["grua", "gruas"]},
                "nivel_muelle": {"palabras": ["muelle", "atraca", "amarra"]},
                "pasillo_contenedores": {"palabras": ["contenedor", "contenedores",
                                                      "revisa", "inspeccion"]},
            },
        },
        "puerto_sin_buque": {
            "palabras": {"marina": 2, "incautado": 1.5, "pseudoefedrina": 2},
            "luz": "overcast daylight over an industrial port, flat grey light",
            "prompt": "an industrial container port with an empty berth",
            "camaras": {"general_aereo": {}, "medio_grua": {},
                        "nivel_muelle": {}, "pasillo_contenedores": {}},
        },
        "bodega": {
            "palabras": {"carga": 2, "cocaina": 2, "toneladas": 1.5,
                         "mercancia": 1.5, "dentro": 1},
            "luz": "dim interior, a single work lamp, deep shadows",
            "prompt": ("the inside of a shipping container packed with stacked "
                       "bricks of cargo"),
            "camaras": {"puerta_abierta": {"palabras": ["dentro", "abre"]},
                        "detalle_pila": {"palabras": ["toneladas", "cocaina"]}},
        },
    },
    "reparto": {
        "tripulacion": {
            "grupo": True,
            "palabras": ["tripulacion", "navega", "zarpo", "marineros"],
            "descripcion": ("three clearly different merchant sailors on a cargo "
                            "ship deck"),
        },
        "estibadores": {
            "grupo": True,
            "palabras": ["puerto", "muelle", "estibadores"],
            "descripcion": "three clearly different port dock workers",
        },
        "marinos": {
            "grupo": True,
            "palabras": ["marina", "incautado"],
            "descripcion": "two clearly different Mexican navy officers",
        },
    },
    "componentes": {
        "mapa_ruta": {
            "tipo": "mapa",
            "palabras": {"kilometros": 2, "ruta": 2, "entrega": 1.5,
                         "chicago": 2, "destino": 1.5},
            "config": {"region": "america",
                       "origen": {"nombre": "COLOMBIA", "coord": [3.88, -77.03]},
                       "destino": {"nombre": "MEXICO", "coord": [19.05, -104.31]}},
        },
    },
    "lugares": {"manzanillo": "PUERTO DE MANZANILLO"},
    "etiquetas": {"buque": "carguero esmeralda", "patio": "patio de contenedores",
                  "carga": "la carga declarada"},
    "anclas": {"buque": ["carguero", "barco", "esmeralda"],
               "patio": ["contenedores", "patio"],
               "carga": ["carga", "cocaina", "mercancia"]},
    "capitulos": {"S001": {"titulo": "EL ESMERALDA",
                           "antetitulo": "capitulo uno",
                           "subtitulo": "Octubre de 2007"}},
}


# --------------------------------------------------------------- la locucion
#
# EL TEXTO QUE SE «LOCUTA», por bloques, y cada bloque es un parrafo del guion.
# Las palabras NO son de adorno: son las que el catalogo de arriba usa para
# decidir el sitio de cada plano, quien sale y cuando entra el mapa, asi que
# cambiar una cambia el plan. Los bloques van a proposito de largos distintos:
# uno corto obliga al segmentador a decidir si lo parte, y el muro entre dos
# bloques es lo que ningun plano puede cruzar.
BLOQUES_LOCUCION = [
    ("B001", "El carguero Esmeralda zarpo del puerto una manana de octubre "
             "con su tripulacion completa y la carga ya declarada."),
    ("B002", "Cuatro mil kilometros de mar abierto separaban el origen del "
             "destino, y la ruta pasaba por dos puertos mas antes de la "
             "entrega."),
    ("B003", "En el muelle de Manzanillo el buque atraca de madrugada. Las "
             "gruas empiezan a mover contenedores antes de que amanezca."),
    ("B004", "Los estibadores del puerto descargan el patio entero en seis "
             "horas."),
    ("B005", "Dentro de uno de los contenedores, la mercancia no era la que "
             "decia el manifiesto: veinte toneladas de contrabando repartidas "
             "en cajas identicas."),
    ("B006", "La marina llega al amanecer y todo queda incautado. El puerto "
             "sigue trabajando como si no hubiera pasado nada."),
]

#: Cadencia de la locucion falsa, en palabras por segundo. 2,4 es lo que da una
#: voz de documental a velocidad normal en castellano, y con estos seis bloques
#: sale una narracion de unos cuarenta segundos: suficiente para que salgan diez
#: planos largos y corta para que la suite entera quepa en un par de minutos.
PALABRAS_POR_SEGUNDO = 2.4

#: El silencio entre dos bloques. Un segundo, que es lo que deja el motor de voz
#: (`p4_voz`): sin el, dos bloques quedarian pegados y el muro no se veria.
SILENCIO_ENTRE_BLOQUES_S = 1.0


def locucion_falsa():
    """La locucion, con marcas de palabra. -> (meta, segundos)

    EL FORMATO ES EL QUE ESCRIBE `p4_voz` HOY, y eso no es un detalle: una
    lista PLANA de marcas (`palabras`) mas `bloques` con el `t_in`, el `t_out`
    y el RECUENTO de palabras de cada uno. En el de las tomas anteriores cada
    bloque llevaba su propia lista dentro, y escribir ese aqui seria probar un
    camino de compatibilidad en vez del que corre de verdad.

    Se escribe a mano y NO se genera llamando al motor de voz: si el motor
    cambiara de forma, esta suite tiene que enterarse, no seguirle.
    """
    paso = 1.0 / PALABRAS_POR_SEGUNDO
    reloj, bloques, sueltas = 0.0, [], []
    for bid, texto in BLOQUES_LOCUCION:
        inicio, cuantas = reloj, 0
        for cruda in texto.split():
            sueltas.append({"w": cruda, "s": round(reloj, 3),
                            "e": round(reloj + paso * 0.85, 3)})
            reloj += paso
            cuantas += 1
        bloques.append({"id": bid, "texto": texto, "narracion": texto,
                        "t_in": round(inicio, 3),
                        "t_out": round(reloj - paso * 0.15, 3),
                        "palabras": cuantas})
        reloj += SILENCIO_ENTRE_BLOQUES_S
    total = round(reloj - SILENCIO_ENTRE_BLOQUES_S, 3)
    return ({"bloques": bloques, "palabras": sueltas, "duracion": total,
             "transcript": " ".join(t for _b, t in BLOQUES_LOCUCION),
             "secciones": [{"id": "SB001",
                            "bloques": [b["id"] for b in bloques],
                            "t_in": 0.0, "t_out": total}]},
            total)


# ------------------------------------------------------------- preparacion

def preparar_proyecto():
    """Proyecto nuevo con ingesta, brief, guion y voz ya completados de verdad.

    La voz no se sintetiza: se fabrica su `audio_meta.json` (ver
    `locucion_falsa`) y un wav del largo exacto. Para p6, p7 y p8 la locucion
    ES ese fichero de marcas -- el wav solo se muxea al final -- asi que la
    cadena que se prueba es la de verdad.
    """
    if os.path.isdir(CARPETA):
        shutil.rmtree(CARPETA)
    os.makedirs(CARPETA)
    proyecto = Proyecto.crear(CARPETA, "Prueba visual")
    estado = Estado(proyecto)

    material = "\n\n".join(texto for _bid, texto in BLOQUES_LOCUCION)
    for paso, salidas in (("ingesta", {"palabras": len(material.split())}),
                          ("brief", {"tema": "caso-meridiano"})):
        medios.escribir_json(os.path.join(proyecto.ruta_trabajo(paso),
                                          f"{paso}.json"), salidas)
        estado.set_params(paso, {"texto": material} if paso == "ingesta" else {})
        estado.completar(paso, salidas)

    guion = os.path.join(proyecto.ruta_trabajo("guion"), "guion.json")
    medios.escribir_json(guion, {
        "catalogo": CATALOGO,
        "guion": [{"id": bid, "texto": texto, "abre_seccion": bid == "B001"}
                  for bid, texto in BLOQUES_LOCUCION],
    })
    estado.set_params("guion", {"idioma": "es"})
    estado.completar("guion", {"guion": "guion.json", "catalogo": "guion.json"})

    trabajo_voz = proyecto.ruta_trabajo("voz")
    meta, segundos = locucion_falsa()
    medios.escribir_json(os.path.join(trabajo_voz, "audio_meta.json"), meta)
    # UN TONO GRAVE Y FLOJO, no silencio: el silencio absoluto haria que el
    # loudnorm del paso 8 midiera -inf LUFS y la mezcla se fuera al tope.
    _audio_falso(os.path.join(trabajo_voz, "narracion.wav"), segundos, 110)
    estado.set_params("voz", {"voz": "prueba", "modo": "continuo"})
    estado.completar("voz", {"meta": "audio_meta.json", "wav": "narracion.wav",
                             "duracion": segundos})
    return proyecto, estado


#: Tamano del arte: el de GENERACION de un video horizontal
#: (`comun.FORMATOS`), que es el que tendria una imagen recien pagada. No es un
#: detalle: p7 mide en pixeles sobre este lienzo para colocar el rotulo, y con
#: otro tamano lo que se comprueba deja de ser lo que pasa en un video.
LIENZO_ARTE = (1536, 1024)

#: Donde esta EL SUJETO en las laminas fabricadas, en fraccion del alto. Una
#: banda oscura en la mitad de abajo: p7 tiene que poner el rotulo ARRIBA, y con
#: el sujeto en un sitio conocido esa comprobacion dice algo. Con un dibujo de
#: verdad el sujeto esta donde este y la prueba se vuelve una loteria.
SUJETO_DESDE = 0.55


def _lamina(destino, semilla):
    """Una lamina de prueba: cielo claro arriba, sujeto oscuro abajo.

    Cada una con su tono, para que dos planos NO compartan imagen: el guardian
    de planos repetidos de p6 tumba la tanda si dos salen byte a byte iguales,
    y con laminas identicas esta suite no llegaria ni a p7.
    """
    ancho, alto = LIENZO_ARTE
    fondo = (200 - (semilla * 7) % 60, 205 - (semilla * 5) % 50, 215)
    imagen = Image.new("RGB", (ancho, alto), fondo)
    pixeles = imagen.load()
    y0 = int(alto * SUJETO_DESDE)
    for y in range(y0, alto):
        tono = 40 + (y - y0) * 30 // max(1, alto - y0) + (semilla * 3) % 20
        for x in range(ancho):
            pixeles[x, y] = (tono, tono + 6, tono + 14)
    # una marca clara en el centro del sujeto: da contraste dentro de la banda,
    # que es lo que hace que el detector de hueco no la lea como un plano liso
    lado = ancho // 8
    for y in range(y0 + 40, min(alto, y0 + 40 + lado)):
        for x in range((ancho - lado) // 2, (ancho + lado) // 2):
            pixeles[x, y] = (220, 220, 225)
    # Y GRANO, que no es adorno: `medios.rasterizar` avisa por consola cuando un
    # PNG a cuadro completo pesa menos de `MINIMO_RASTERIZADO_BYTES`, porque eso
    # huele a pagina de error. Una lamina de colores planos comprime a 30 KB y
    # disparaba el aviso en casi cada plano: diez alarmas en una suite que va
    # bien ensenan a no leer las alarmas. Con grano pesa como un dibujo.
    for y in range(0, alto, 2):
        for x in range((y * 7 + semilla) % 3, ancho, 3):
            r, g, b = pixeles[x, y]
            d = ((x * 31 + y * 17 + semilla * 13) % 23) - 11
            pixeles[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)),
                             max(0, min(255, b + d)))
    imagen.save(destino, "PNG")
    return destino


def preparar_arte(proyecto, ids):
    """Carpeta de arte ya aprobado: una lamina por plano, dibujada aqui.

    El modo de imagen de la suite es 'adoptar' -- el arte ya existe y no se
    paga -- asi que esta carpeta es lo que en un video de verdad seria el
    storyboard aprobado. Las hojas del reparto se dibujan igual, con el nombre
    que el catalogo les da: p6 las busca POR NOMBRE, y ese emparejamiento es
    parte de lo que se comprueba.
    """
    arte = os.path.join(CARPETA, "_arte")
    os.makedirs(os.path.join(arte, "escenas"), exist_ok=True)
    os.makedirs(os.path.join(arte, "reparto"), exist_ok=True)
    for indice, sid in enumerate(ids):
        _lamina(os.path.join(arte, "escenas", f"{sid}.png"), indice + 1)
    for indice, quien in enumerate(sorted(CATALOGO["reparto"])):
        _lamina(os.path.join(arte, "reparto", f"{quien}.png"), 100 + indice)
    return arte


def parametros(arte):
    return {
        "calidad": "low",
        "min_s": 3.0,
        "max_s": 6.0,
        "semilla": 7,
        # DOS CARTELAS, una de cada fondo, y POR UNIDAD -- que es donde viven:
        # en un param suelto entrarian en la firma GLOBAL del paso y guardar
        # una dejaria obsoletos los cuarenta y nueve planos.
        #
        # S003 va sobre negro (no genera imagen) y S010 sobre la imagen del
        # propio plano (se genera como cualquiera). Las dos en medio y separadas,
        # para que les toquen vecinos por los dos lados y para no pasarse del
        # suelo de `cartelas.SEPARACION_MINIMA`.
        #
        # LA CIFRA DE S003 ES «4.000 KM» Y SU PLANO DICE «Cuatro mil
        # kilometros»: la cartela DESTILA, no repite, y aqui se comprueba de
        # punta a punta que el motor sincroniza igual una cifra escrita en otra
        # notacion (`medios.numeros_dichos`). Van las dos en un video de once
        # planos, que es 0,18 y cabe en el techo del 22 %
        # (`cartelas.FRACCION_MAXIMA`): una que ocupara dos planos se llevaria
        # las dos plazas.
        #
        # SI SE TOCA `BLOQUES_LOCUCION`, ESTO SE MUEVE. El plano que dice
        # «Cuatro mil» depende de como corte el segmentador, asi que cambiar el
        # texto de arriba puede dejar la cartela en un plano que no nombra la
        # cifra -- y entonces falla, con razon, la comprobacion de la sincronia.
        "unidades": {
            "escena:S003": {"cartela": {
                "plantilla": "cifra", "fondo": "negro",
                "datos": {"cifra": "4.000 KM",
                          "label": "de mar abierto"},
                "por_que": "la prueba"}},
            "escena:S010": {"cartela": {
                "plantilla": "tesis", "fondo": "imagen",
                "datos": {"texto": "Y entonces el barco dejo de existir"},
                "por_que": "la prueba, sobre imagen"}},
        },
        "motor_imagen": "adoptar",
        "imagenes_previas": [arte],
        "banco_imagenes": os.path.join(BANCO_PRUEBA, "imagenes"),
        "catalogo": CATALOGO,
        "estilo": {
            "prompt": ("flat vector cartoon illustration: thick uniform black "
                       "outlines, flat fill colours, muted earthy palette"),
            "referencias": [],
        },
    }


def avisador(etiqueta):
    ultimo = {"t": 0.0}

    def avisar(valor, mensaje=""):
        ahora = time.time()
        if mensaje and ahora - ultimo["t"] > 1.5:
            ultimo["t"] = ahora
            print(f"      [{etiqueta}] {mensaje}")
    return avisar


# ------------------------------------------------------------------ paso 6

def probar_assets(proyecto, estado, params):
    print("\n  PASO 6 · assets y escenas")
    plan_previo = p6_assets.planificar(proyecto, params)
    ids = [e["id"] for e in plan_previo["escenas"]]
    ok(len(ids) >= 6,
       f"la locucion de {locucion_falsa()[1]:.0f} s da varios planos ({len(ids)})")

    # NINGUN PLANO CRUZA DE UN BLOQUE AL SIGUIENTE, y esto es lo que lo prueba.
    #
    # `p6._palabras_narracion` devuelve unos MUROS --el indice de palabra en que
    # empieza cada bloque-- y el segmentador no corta a caballo de uno. La
    # promesa estaba escrita en su docstring y no se cumplia: los muros se
    # sacaban de un `escenas` con las palabras dentro, que es el formato de las
    # tomas ANTERIORES, asi que con el de hoy caian en el camino de repuesto que
    # mete todas las palabras en el bloque cero. Muros vacios, y un plano que de
    # vez en cuando narra el final de un bloque y el principio del siguiente:
    # no da error, se ve en el video.
    #
    # Se comprueba por el ORIGEN de cada plano, que es lo que el resto del
    # camino lee: un plano de un solo bloque tiene un origen y nada mas.
    palabras, muros, _ruta, meta = p6_assets._palabras_narracion(  # noqa: SLF001
        proyecto, params)
    igual(len(muros), len(BLOQUES_LOCUCION) - 1,
          f"hay un muro por frontera de bloque ({muros})")
    igual(len(palabras),
          sum(len(texto.split()) for _bid, texto in BLOQUES_LOCUCION),
          "y estan todas las palabras de la locucion")
    bloques = p6_assets.tramos_de_bloque(meta)
    for escena in plan_previo["escenas"]:
        dentro = [bid for t_in, t_out, bid in bloques
                  if min(escena["t_out"], t_out) - max(escena["t_in"], t_in) > 0.2]
        igual(len(dentro), 1,
              f"{escena['id']} narra UN bloque y no dos: {dentro}")

    otra_vez = p6_assets.planificar(proyecto, params)
    igual(json.dumps(otra_vez["escenas"], sort_keys=True),
          json.dumps(plan_previo["escenas"], sort_keys=True),
          "planificar es determinista")

    arte = preparar_arte(proyecto, ids)
    params["imagenes_previas"] = [arte]

    resultado = p6_assets.ejecutar(proyecto, params, avisador("p6"))
    plan = resultado["plan"]
    escenas = plan["escenas"]

    # --- montaje
    cartas = [e.get("carta") for e in escenas]
    ok(all(cartas), "todos los planos llevan su clase de encuadre")
    familias = [(encuadres.POR_ID.get(c) or {}).get("familia") for c in cartas]
    seguidas = [(a, b) for a, b in zip(familias, familias[1:]) if a and a == b]
    igual(seguidas, [], "ninguna familia de encuadre se repite en dos seguidos")
    tipos = [e["zoom"]["tipo"] for e in escenas]
    igual(tipos, ["in" if i % 2 == 0 else "out" for i in range(len(escenas))],
          "el zoom alterna dentro y fuera")
    duraciones = [e["duracion"] for e in escenas]
    ok(all(2.0 <= d <= 8.0 for d in duraciones),
       f"duraciones dentro de rango razonable: {[round(d, 1) for d in duraciones]}")
    ok(any(e.get("set") for e in escenas), "algun plano ocurre en un sitio")
    ok(any(e.get("componente") for e in escenas), "algun plano es un componente")

    # --- LAS CARTELAS: TODAS sobre imagen desde el 21-08-2026 (noche)
    #
    # Una cartela ya no sustituye un plano por una pantalla de texto: es un plano
    # normal con el texto encima y la imagen oscurecida detras. El montaje no se
    # para, y ese plano se paga como cualquier otro. El fondo negro sigue
    # dibujandose y `sin_imagen` lo sigue distinguiendo, pero nadie lo elige --
    # ni el agente, que ya no decide fondo -- asi que aqui se comprueba que ni
    # pidiendolo se cuela.
    carpeta_escenas = os.path.join(proyecto.ruta_trabajo("assets", crear=False),
                                   "escenas")
    for sid, pedia in (("S003", "negro"), ("S010", "imagen")):
        cartela = next((e for e in escenas if e["id"] == sid), None)
        if not ok(cartela is not None, f"{sid} existe en el plan"):
            continue
        ok(cartelas.es_cartela(cartela), f"{sid} es una cartela")
        ok(cartelas.sobre_imagen(cartela),
           f"y va SOBRE IMAGEN aunque su ficha pedia «{pedia}»")
        ok(not cartelas.sin_imagen(cartela), "asi que genera su imagen")
        ok(cartela.get("prompt"), "tiene prompt, como cualquier plano")
        ok(cartela.get("set") or cartela.get("componente"),
           "y su sitio o su componente: sigue habiendo algo que rodar debajo")
        ok((plan["dependencias"].get(f"escena:{sid}") or []),
           "y depende de sus assets, asi que la cascada le llega")
        ficha_c = resultado["unidades"].get(f"escena:{sid}") or {}
        ok(ficha_c.get("png"), "deja su PNG como los demas")
        ok(os.path.exists(os.path.join(carpeta_escenas, f"{sid}.png")),
           "y el fichero esta")

    # los demas siguen teniendo su sitio: la cartela no rompe la cadena
    ok(any(e.get("set") for e in escenas if e["id"] != "S003"),
       "los planos de alrededor conservan su sitio")
    # --- ficheros
    trabajo = proyecto.ruta_trabajo("assets", crear=False)
    for escena in escenas:
        # una cartela de fondo negro no deja imagen a proposito: se dibuja
        if cartelas.sin_imagen(escena):
            continue
        ok(os.path.exists(os.path.join(trabajo, "escenas", f"{escena['id']}.png")),
           f"falta la imagen de {escena['id']}")
    for escena in escenas:
        for personaje in escena.get("personajes") or []:
            ok(os.path.exists(os.path.join(trabajo, "assets", "reparto",
                                           f"{personaje}.png")),
               f"falta la hoja de reparto de {personaje}")
    componentes = {e["componente"] for e in escenas if e.get("componente")}
    for nombre in componentes:
        ok(os.path.exists(os.path.join(trabajo, "assets", "componentes",
                                       f"{nombre}.png")),
           f"el componente {nombre} deberia estar rasterizado")

    # --- prompts con las referencias en su sitio
    ficha = medios.leer_json(os.path.join(trabajo, "escenas",
                                          f"{escenas[0]['id']}.json"), {})
    ok(not any(r["papel"] == "estructura"
               for r in (ficha.get("referencias") or [])),
       "ya no se adjunta ningun lineart: la geometria 3D se retiro")
    ok(len(resultado["dependencias"]) == len(escenas),
       "cada escena declara los assets que usa")

    # las dependencias se declaran antes de versionar: asi la version guarda ya
    # la firma de los assets de cada escena
    p6_assets.propagar_dependencias(estado, resultado["dependencias"])
    version = estado.completar("assets", resultado["salidas"], resultado["unidades"])
    igual(version, 1, "assets queda versionado como v1")
    igual(estado.estado_de("assets"), "listo", "assets queda listo tras completar")
    return resultado


def probar_cascada(proyecto, estado, resultado):
    print("\n  PASO 6 · cascada de un asset a sus escenas")
    dependencias = resultado["dependencias"]
    candidatos = {}
    for escena, usados in dependencias.items():
        for uid in usados:
            candidatos.setdefault(uid, []).append(escena)
    tocado = None
    for uid, escenas in sorted(candidatos.items()):
        if uid.startswith("asset:") and 0 < len(escenas) < len(dependencias):
            tocado = uid
            break
    if not ok(tocado, "hace falta un asset usado por unas escenas y no por otras"):
        return
    usan = set(candidatos[tocado])
    no_usan = set(dependencias) - usan

    estado.actualizar_params("assets", {"unidades": {tocado: {"nota": "rehacer"}}})
    p6_assets.propagar_dependencias(estado, dependencias)
    obsoletas = set(estado.unidades_obsoletas("assets"))

    ok(tocado in obsoletas, f"{tocado} deberia quedar obsoleto")
    ok(usan <= obsoletas,
       f"las escenas que usan {tocado} deberian quedar obsoletas: "
       f"{sorted(usan - obsoletas)}")
    ok(not (no_usan & obsoletas),
       f"las demas escenas NO deberian moverse: {sorted(no_usan & obsoletas)}")
    igual(estado.estado_de("assets"), "obsoleto", "el paso entero queda obsoleto")
    heredadas = set(estado.unidades_obsoletas("render"))
    ok(usan <= heredadas, "la obsolescencia llega hasta el render por unidad")

    # REHACER UNA COSA REHACE ESA COSA. Aqui se comprobaba lo contrario -- que
    # pedir el asset arrastraba sus escenas detras -- y esa cascada de
    # GENERACION se retiro el 23-08: pedir una hoja de
    # personaje se llevaba las cuarenta y cuatro imagenes del video por delante,
    # sin preguntar y sin decir lo que costaban.
    print(f"      rehaciendo SOLO {tocado} ({len(usan)} escena(s) quedan sucias)")
    parcial = p6_assets.ejecutar(proyecto, resultado["params"], avisador("p6"),
                                 unidades=[tocado])
    rehechas = set(parcial["regeneradas"])
    igual(sorted(rehechas), [tocado],
          "la ejecucion parcial rehace el asset y NADA mas")
    ok(not (usan & rehechas),
       f"y no arrastra ni una de las {len(usan)} escenas que lo usan: eso lo "
       f"decide una persona, con la cuenta y el coste delante")
    ok(parcial["conservadas"], "las escenas ajenas al asset se conservan tal cual")
    ok(not (set(parcial["unidades"]) & set(parcial["conservadas"])),
       "una unidad conservada no se sella como rehecha")
    p6_assets.propagar_dependencias(estado, parcial["dependencias"])
    estado.completar("assets", parcial["salidas"], parcial["unidades"])
    # LA CASCADA DE MARCADO SE QUEDA, y esto es lo que la sujeta: las escenas
    # que usan el asset siguen obsoletas hasta que alguien las rehaga a
    # proposito. Sin esto, retirar la cascada de generacion seria perder trabajo
    # en silencio en vez de dejarlo accionable.
    igual(estado.estado_de("assets"), "obsoleto",
          "el paso sigue obsoleto: quedan las escenas que usaban ese asset")
    ok(usan <= set(estado.unidades_obsoletas("assets")),
       "y son exactamente ellas las que se pueden accionar con «Regenerar lo "
       "obsoleto (N)»")
    igual(len(estado.versiones("assets")), 2, "hay dos versiones de assets")
    trabajo = proyecto.ruta_paso("assets")
    # las cartelas de fondo negro no tienen imagen que conservar: se dibujan
    sin_imagen = {f"escena:{e['id']}"
                  for e in (resultado.get("plan") or {}).get("escenas") or []
                  if cartelas.sin_imagen(e)}
    faltan = [e for e in dependencias if e not in sin_imagen
              and not os.path.exists(os.path.join(trabajo, "escenas",
                                                  f"{e.split(':')[1]}.png"))]
    igual(faltan, [], "la version nueva conserva todas las imagenes")


def probar_solo_assets(proyecto, estado, params):
    """La pasada de SOLO assets deja lo mismo que la completa, menos los planos.

    Esto no estaba protegido y se rompio en silencio: esta rama escribia el
    assets.json con otra forma -- solo sets, con el nombre pelado por clave en
    vez del id de unidad y sin resultados -- y la pantalla, que lee ese fichero,
    pintaba una tarjeta por set sin tipo ni imagen y, peor, tomaba esas claves
    por ids de unidad: al guardar quedaban declaradas unidades que ninguna
    ejecucion produce, y el paso se quedaba obsoleto para siempre.
    """
    print("\n  PASO 6 · solo assets, sin planos")
    parcial = p6_assets.ejecutar(proyecto, params, avisador("p6"), solo_assets=True)
    salidas = parcial["salidas"]
    ok(salidas.get("parcial"), "la pasada se declara parcial")
    igual(salidas.get("n_escenas"), 0, "y dice que no ha generado ni un plano")

    trabajo = proyecto.ruta_trabajo("assets", crear=False)
    fichero = medios.leer_json(os.path.join(trabajo, "assets.json"), {})
    inventario = fichero.get("assets") or {}
    ok(inventario, "escribe el inventario de assets")
    raros = [uid for uid in inventario if not str(uid).startswith("asset:")]
    igual(raros, [], "las claves son ids de unidad, no nombres pelados: la "
                     "interfaz las guarda como unidades y una unidad inventada "
                     "no se puede rehacer nunca")
    igual(sorted(inventario), sorted(parcial["unidades"]),
          "y son exactamente las unidades que la pasada sella")
    sin_ficha = [uid for uid, ficha in inventario.items()
                 if not (ficha.get("tipo") and ficha.get("nombre"))]
    igual(sin_ficha, [], "cada asset dice de que tipo es y como se llama")
    tipos = {ficha.get("tipo") for ficha in inventario.values()}
    ok(len(tipos) > 1, f"estan todos los tipos, no solo los sets: {sorted(tipos)}")

    resultados = fichero.get("resultados") or {}
    igual(sorted(resultados), sorted(inventario),
          "y lo que produjo cada uno, que es de donde sale la previsualizacion")
    sin_imagen = []
    for uid, salida in resultados.items():
        ruta = salida.get("png") or salida.get("svg") or salida.get("dir")
        if not ruta or not os.path.exists(os.path.join(trabajo, ruta)):
            sin_imagen.append(uid)
    igual(sin_imagen, [], "cada resultado apunta a algo que existe, y con ruta "
                          "relativa a la version: la absoluta a trabajo/ deja de "
                          "valer en cuanto se versiona")

    deps = medios.leer_json(os.path.join(trabajo, "dependencias.json"), None)
    igual(deps, parcial["dependencias"],
          "escribe las dependencias: sin ellas, tocar un set no ensucia sus planos")

    # Y una pasada limitada por tipos HEREDA lo que no toca: pulsar «Generar
    # las piezas» en un video cuyo plan no pide piezas versionaba un
    # assets.json casi vacio, y la pantalla entera -- que lee la version
    # activa -- se quedaba sin cajas, sin hojas y sin piezas hasta la
    # siguiente pasada completa.
    antes = set(resultados)
    de_tipos = p6_assets.ejecutar(proyecto, params, avisador("p6"),
                                  tipos=["mapa"])
    ok(de_tipos["salidas"].get("parcial"),
       "pedir tipos tambien es una pasada parcial")
    despues = set((medios.leer_json(os.path.join(trabajo, "assets.json"), {})
                   or {}).get("resultados") or {})
    ok(antes <= despues,
       "la pasada por tipos conserva en assets.json los resultados que no toco")


# ------------------------------------------------------------------ paso 7

def probar_callouts(proyecto, estado, params):
    print("\n  PASO 7 · capa vectorial y movimiento")
    resultado = p7_callouts.ejecutar(proyecto, params, avisador("p7"))
    trabajo = proyecto.ruta_trabajo("callouts", crear=False)
    plan = medios.leer_json(medios.salida_de(proyecto, "assets", claves=("plan",),
                                             patrones=(r"plan\.json",)), {})
    escenas = plan["escenas"]

    for escena in escenas:
        sid = escena["id"]
        svg = os.path.join(trabajo, "capas", f"{sid}.svg")
        ok(os.path.exists(svg), f"falta la capa de {sid}")
        mov = medios.leer_json(os.path.join(trabajo, "movimiento", f"{sid}.json"), {})
        ok(mov.get("ventana_ini") and mov.get("ventana_fin"),
           f"{sid}: sin ventanas de zoom")
        ok(os.path.exists(os.path.join(trabajo, "hyper", f"{sid}.png")),
           f"{sid}: sin hyperframe")

    # EL SUBTITULO DE S001 SALE DE SU NARRACION, no de ninguna decision: es la
    # narracion, y ya esta escrita. Aqui se comprueba de punta
    # a punta que lo que dice la voz acaba DIBUJADO en el SVG.
    #
    # Y se lee de `capas_fijas/`, que es donde vive desde el 23-08: el subtitulo
    # esta en la capa que NO escala. En `capas/` esta lo que
    # va dentro del zoom -- la cartela, la cabecera --, asi que buscarlo alli
    # daria un falso negativo con toda la razon del mundo.
    with open(os.path.join(trabajo, "capas_fijas", "S001.svg"), encoding="utf-8") as fh:
        svg_s001 = fh.read()
    dicho = [e.get("texto") for e in
             (resultado["unidades"].get("escena:S001") or {}).get("elementos") or []]
    if ok(dicho, f"S001 lleva subtitulo: {dicho}"):
        # por palabras: el bloque parte el texto en dos renglones si no cabe de
        # una, y buscar la frase entera daria falso negativo por un salto legitimo
        primera = dicho[0].split()[0]
        ok(primera in svg_s001,
           f"y lo que dice sale dibujado ('{primera}' en el SVG de S001)")

    # LA CARTELA sobre imagen SI pasa por el motor de movimiento: debajo hay un
    # plano de verdad, con su zoom, y lo unico que cambia es su capa -- el velo
    # que oscurece la imagen y el texto escribiendose encima.
    ficha_cartela = resultado["unidades"].get("escena:S003") or {}
    ok(ficha_cartela.get("ventana_ini") and ficha_cartela.get("ventana_fin"),
       "una cartela sobre imagen conserva su recorrido de camara")
    ok(ficha_cartela.get("ventana_ini") != ficha_cartela.get("ventana_fin"),
       "y se mueve: el plano de debajo sigue siendo un plano")
    with open(os.path.join(trabajo, "capas", "S003.svg"), encoding="utf-8") as fh:
        svg_cartela = fh.read()
    # palabra a palabra: cada una va en su tspan porque la cartela se ESCRIBE,
    # asi que buscar la frase entera no encontraria nunca nada
    ok(all(p in svg_cartela for p in ("4.000", "mar", "abierto")),
       "la capa de la cartela lleva su texto")
    ok(svg_cartela.count("<animate") >= 3,
       "y se ESCRIBE: cada palabra con su aparicion, no todas de golpe")
    # Y SE ESCRIBE CUANDO SE DICE, con la cifra en otra notacion. El plano dice
    # «Cuatro mil kilometros» y la cartela pone «4.000 KM»: si el emparejado de
    # cifras se rompiera, esto seguiria dibujando la cartela -- con el ritmo
    # sintetico -- y nadie se enteraria hasta ver el video.
    escritura = next(e for e in escenas if e["id"] == "S003")["escritura"]
    ok(escritura["tiempos"], "la cartela va sincronizada con la voz, no a ritmo fijo")
    marcas = next(e for e in escenas if e["id"] == "S003")["marcas"]
    cuatro = medios.indice_de(
        next(e for e in escenas if e["id"] == "S003")["narracion"].split(), "4.000")
    if ok(cuatro is not None, "«4.000» se reconoce en «Cuatro mil»"):
        t_in = next(e for e in escenas if e["id"] == "S003")["t_in"]
        esperado = round(marcas[cuatro[0]][0] - t_in, 2)
        ok(abs(escritura["tiempos"][0] - esperado) < 0.05,
           f"y la cifra entra cuando se dice ({escritura['tiempos'][0]} "
           f"contra {esperado})")
    # EL VELO SE MIRA, no solo se comprueba que exista. Es lo que da contraste
    # para leer el texto sobre la imagen, y aterriza JUSTO cuando entra la
    # primera palabra: antes, se oscurece y luego no pasa nada; despues, las
    # primeras palabras se escriben sobre la imagen limpia y no se leen.
    ok("ct-velo" in svg_cartela,
       "la capa de la cartela lleva el velo que oscurece la imagen")
    trozo = svg_cartela[svg_cartela.index('fill="url(#ct-velo)"'):][:400]
    ok('opacity="0"' in trozo,
       "que empieza invisible: se ve el plano LIMPIO un momento antes")
    entrada_velo = re.search(r'begin="([\d.]+)s" dur="([\d.]+)s"', trozo)
    if ok(entrada_velo, "y se oscurece solo"):
        cierra = float(entrada_velo.group(1)) + float(entrada_velo.group(2))
        primera = escritura["tiempos"][0] if escritura["tiempos"] else cartelas.ENTRADA
        ok(abs(cierra - primera) < 0.03,
           f"aterrizando con la primera palabra ({cierra:.2f} contra {primera})")

    # LOS SUBTITULOS, que es lo que sustituyo a los rotulos.
    # Ya no hay nada que colocar ni ningun arquetipo que pueda colarse: un
    # subtitulo va en la banda y la banda es la misma en todo el video. Lo que
    # hay que comprobar es que se escriba con la voz y que no se salga.
    con_texto = [uid for uid, ficha in resultado["unidades"].items()
                 if ficha.get("elementos")]
    ok(con_texto, f"algun plano deberia llevar subtitulo ({len(con_texto)})")
    subs = [e for uid in con_texto
            for e in resultado["unidades"][uid]["elementos"]]
    ok(all(e.get("tipo") == "subtitulo" for e in subs),
       f"y todo lo que se dibuja encima es un subtitulo: "
       f"{sorted({e.get('tipo') for e in subs})}")
    ok(all(e.get("hasta", 0) >= e.get("desde", 0) for e in subs),
       "ninguno va del reves en el tiempo")
    # SE DIBUJA DE VERDAD, EN LA CAPA QUE NO ESCALA, Y CON CAJA.
    #
    # Las tres cosas cambiaron el 23-08. Aqui se comprobaba lo
    # contrario -- perfilado y sin rectangulo -- y era correcto entonces: la
    # decision del 22-08 era «sin caja, con perfilado, porque un cuadro tapa la
    # imagen justo donde el ojo esta mirando». Se monto, se vio, y el canal
    # decidio caja ligera. Queda escrito que el cambio es DELIBERADO.
    ficha_uno = resultado["unidades"][con_texto[0]]
    with io.open(os.path.join(trabajo, ficha_uno["svg"]), encoding="utf-8") as fh:
        svg_movil = fh.read()
    with io.open(os.path.join(trabajo, ficha_uno["svg_fijo"]), encoding="utf-8") as fh:
        svg_uno = fh.read()
    ok("<text" not in svg_movil,
       "la capa que ESCALA no lleva ni una letra del subtitulo: si la llevara, "
       "el subtitulo haria zoom con la imagen")
    ok("<text" in svg_uno, "y la capa QUIETA si")
    ok(f'viewBox="0 0 {p7_callouts.SALIDA[0]} {p7_callouts.SALIDA[1]}"' in svg_uno,
       "dibujada en el cuadro de SALIDA, que es donde vive lo que no se mueve")
    ok("<rect" in svg_uno and 'fill="#000000"' in svg_uno,
       "lleva la caja negra que pidio el canal despues de verlo montado")
    ok(f'opacity="{p7_callouts.SUB_CAJA_OPACIDAD:g}"' in svg_uno,
       f"ligera: opacidad {p7_callouts.SUB_CAJA_OPACIDAD}")
    ok(f'font-weight="{p7_callouts.SUB_PESO}"' in svg_uno,
       "y a semibold; era 400")
    ok("stroke=" not in svg_uno,
       "el perfilado se va con la caja: con caja y semibold seria la tercera "
       "capa de contraste para el mismo trabajo")
    ok('text-anchor="middle"' in svg_uno, "va centrado")
    print(f"      subtitulos dibujados: {len(subs)}")

    previos = [uid for uid, ficha in resultado["unidades"].items()
               if ficha.get("previo")]
    if ok(previos, "deberia haber vistas previas compuestas"):
        uid = previos[0]
        sid = uid.split(":")[1]
        _comparar_previo(proyecto, trabajo, sid)

    version = estado.completar("callouts", resultado["salidas"], resultado["unidades"])
    igual(version, 1, "callouts queda versionado")
    igual(estado.estado_de("callouts"), "listo", "callouts queda listo")
    return resultado




def _comparar_previo(proyecto, trabajo, sid):
    import numpy as np
    from PIL import Image

    base = os.path.join(proyecto.ruta_paso("assets"), "escenas", f"{sid}.png")
    previo = os.path.join(trabajo, "previo", f"{sid}.png")
    # LA PREVIA ES EL CUADRO QUE VA A SALIR, no el lienzo de generacion. Pintaba
    # el 3:2 entero sin zoom, que valia mientras las dos capas vivian en el mismo
    # espacio; con el subtitulo fuera del zoom no hay un espacio en el que
    # quepan las dos, asi que compone como compone el render.
    with Image.open(previo) as imagen:
        igual(imagen.size, tuple(p7_callouts.SALIDA),
              f"{sid}: la previa sale en el cuadro de salida, no en el lienzo")
    a = np.asarray(Image.open(base).convert("RGB").resize((512, 341)), dtype=np.int16)
    b = np.asarray(Image.open(previo).convert("RGB").resize((512, 341)), dtype=np.int16)
    distintos = int(np.count_nonzero(np.abs(a - b).sum(axis=2) > 40))
    ok(distintos > 200,
       f"{sid}: la previa no puede salir igual que el plano desnudo "
       f"({distintos} px distintos)")


# ------------------------------------------------------------------ paso 8

def _audio_falso(destino, segundos, hz, ffmpeg_a=None):
    """Un fichero de audio de verdad, hecho aquí. Para no salir a la red.

    La suite corre EN SECO: ni Jamendo ni Freesound. Lo que se prueba no es que
    esas APIs sigan vivas -- eso no depende de este repo -- sino que lo que
    decide el programa (qué suena, cuándo, a qué nivel) acaba dentro del MP4.
    """
    subprocess.run(
        [medios.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"sine=frequency={hz}:duration={segundos}",
         "-ac", "2", "-ar", "48000", destino],
        capture_output=True, timeout=120, **medios.SIN_VENTANA)
    return destino


def probar_banda_sonora(proyecto, estado, params, plan):
    """Música y efectos DENTRO del MP4, con ficheros fabricados aquí."""
    print("\n  PASO 8 · banda sonora")
    escenas = plan["escenas"]
    # el banco es el del canal: se siembra con nombres 'prueba_' y se limpia
    tema = {"fuente": "prueba", "id": "musica", "titulo": "Tema de prueba",
            "artista": "Nadie", "duracion": 8.0, "descarga": "", "escucha": ""}
    efectos = {}
    puestos = []
    try:
        _audio_falso(sonido.banco("musica", "prueba_musica.mp3"), 8.0, 110)
        puestos.append(sonido.banco("musica", "prueba_musica.mp3"))
        for indice, papel in enumerate(sonido.PAPELES):
            fichas = []
            for numero in range(2):
                ficha = {"fuente": "prueba", "id": f"{papel}{numero}"}
                nombre = sonido._nombre_de(ficha)
                _audio_falso(sonido.banco("efectos", nombre), 0.25,
                             500 + 220 * indice + 60 * numero)
                puestos.append(sonido.banco("efectos", nombre))
                fichas.append(ficha)
            efectos[papel] = fichas

        p = dict(params)
        p.update({"sonido": True, "musica": tema, "efectos": efectos})
        estado.set_params("render", p)
        resultado = p8_render.ejecutar(proyecto, p, avisador("p8"))
        salidas = resultado["salidas"]
        igual(salidas.get("avisos"), [], "no debería haber avisos de sonido")
        igual(salidas.get("musica"), "Tema de prueba", "la música entra en el MP4")
        ok(salidas.get("efectos", 0) > 0,
           f"y suenan efectos: {salidas.get('efectos')}")

        trabajo = proyecto.ruta_trabajo("render", crear=False)
        pista = os.path.join(trabajo, "efectos.wav")
        ok(os.path.exists(pista), "se escribe la pista de efectos")
        muestras = sonido._leer(pista)
        largo = float(escenas[-1]["t_out"]) - float(escenas[0]["t_in"])
        ok(abs(len(muestras) / sonido.FRECUENCIA - largo) < 0.05,
           "la pista de efectos dura lo que el vídeo")
        pico = 20 * np.log10(max(1e-9, float(np.abs(muestras).max())))
        ok(abs(pico - sonido.EFECTOS_PICO_DB) < 0.6,
           f"y sale al pico pedido ({pico:.1f} dBFS)")

        # LO QUE IMPORTA: que la banda esté DENTRO del MP4 y no solo en un wav
        # suelto al lado. Se compara con el vídeo sin música: si el audio final
        # fuera el mismo, todo lo anterior sería decorado.
        mp4 = os.path.join(trabajo, salidas["mp4"])
        con = _pista_de(mp4, trabajo, "con.wav")
        p["sonido"] = False
        estado.set_params("render", p)
        p8_render.ejecutar(proyecto, p, avisador("p8"))
        sin = _pista_de(os.path.join(proyecto.ruta_trabajo("render", crear=False),
                                     "video.mp4"), trabajo, "sin.wav")
        n = min(len(con), len(sin))
        diferencia = float(np.abs(con[:n] - sin[:n]).mean())
        ok(diferencia > 0.001,
           f"el audio del MP4 cambia al poner música y efectos ({diferencia:.4f})")
        pico_final = 20 * np.log10(max(1e-9, float(np.abs(con).max())))
        ok(pico_final <= -0.3,
           f"y el limitador impide que la mezcla se pase de cero ({pico_final:.1f} dBFS)")

        # LA CAMA: varios temas encadenados en vez de uno en bucle. Es lo que
        # monta sola `sonido.montar_banda` leyendo el ritmo; aquí se prueba lo
        # que hace el RENDER con su resultado, que es lo que no sale a la red.
        print("\n  PASO 8 · la cama de varios temas")
        cama_tramos = []
        for indice, hz in enumerate((90, 160, 240)):
            ficha = {"fuente": "prueba", "id": f"cama{indice}"}
            ruta = sonido.banco("musica", sonido._nombre_de(ficha))
            _audio_falso(ruta, 6.0, hz)          # más cortos que su tramo: se repiten
            puestos.append(ruta)
            cama_tramos.append({**ficha, "titulo": f"tema {indice}", "duracion": 6.0,
                                "fraccion": 1 / 3, "animo": "sobrio"})
        p.update({"sonido": True,
                  "musica": {"tramos": cama_tramos, "cruce_s": 2.0,
                             "ganancia_db": sonido.CAMA_GANANCIA_DB}})
        estado.set_params("render", p)
        resultado_cama = p8_render.ejecutar(proyecto, p, avisador("p8"))
        igual(resultado_cama["salidas"].get("avisos"), [],
              "la cama se monta sin avisos")
        trabajo_cama = proyecto.ruta_trabajo("render", crear=False)
        cama = os.path.join(trabajo_cama, "cama.wav")
        ok(os.path.exists(cama), "se escribe la cama encadenada")
        if os.path.exists(cama):
            largo_cama = len(sonido._leer(cama)) / sonido.FRECUENCIA
            # LA COLA CUENTA. El vídeo cierra con unos segundos de negro
            # (`p8_render.COLA_NEGRO_S`) y la cama tiene que llegar hasta el
            # final: si se corta con la última sílaba, el negro se queda mudo de
            # golpe, que es lo contrario de lo que la cola viene a arreglar.
            esperado = largo + p8_render.COLA_NEGRO_S
            ok(abs(largo_cama - esperado) < 0.06,
               f"y dura lo que el vídeo MÁS su cola de negro "
               f"({largo_cama:.2f}s de {esperado:.2f}s)")
            # el fundido de entrada: sin él, la cama arranca de golpe
            arranque = sonido._leer(cama)[:int(sonido.FRECUENCIA * 0.2)]
            entera = sonido._leer(cama)
            ok(float(np.abs(arranque).max()) < float(np.abs(entera).max()) * 0.6,
               "entra con fundido, no de golpe")
        con_cama = _pista_de(os.path.join(trabajo_cama, "video.mp4"),
                             trabajo, "cama_mp4.wav")
        n2 = min(len(con_cama), len(sin))
        ok(float(np.abs(con_cama[:n2] - sin[:n2]).mean()) > 0.001,
           "y la cama llega al MP4, no se queda en un wav al lado")
    finally:
        for ruta in puestos:
            for resto in (ruta, os.path.splitext(ruta)[0] + ".48000.wav"):
                try:
                    os.remove(resto)
                except OSError:
                    pass


def _pista_de(mp4, trabajo, nombre):
    destino = os.path.join(trabajo, nombre)
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-i", mp4,
                    "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", destino],
                   capture_output=True, timeout=300, **medios.SIN_VENTANA)
    return sonido._leer(destino)


def probar_render(proyecto, estado, params):
    print("\n  PASO 8 · render a MP4")
    inicio = time.time()
    resultado = p8_render.ejecutar(proyecto, params, avisador("p8"))
    trabajo = proyecto.ruta_trabajo("render", crear=False)
    salidas = resultado["salidas"]
    mp4 = os.path.join(trabajo, salidas["mp4"])
    ok(os.path.exists(mp4), "deberia existir el MP4")
    ok(os.path.getsize(mp4) > 40000, f"el MP4 parece vacio ({os.path.getsize(mp4)} B)")

    plan = medios.leer_json(medios.salida_de(proyecto, "assets", claves=("plan",),
                                             patrones=(r"plan\.json",)), {})
    # el plan mide lo que se habla; el MP4 lleva ademas la cola de negro
    esperada = (plan["duracion_total"] - plan["escenas"][0]["t_in"]
                + p8_render.COLA_NEGRO_S)
    ok(abs(salidas["duracion"] - esperada) < 0.6,
       f"la duracion del video ({salidas['duracion']}s) deberia cuadrar con el "
       f"plan ({esperada:.2f}s)")
    igual(len(salidas["clips"]), len(plan["escenas"]), "un clip por plano")
    for sid, ruta in salidas["clips"].items():
        ok(os.path.exists(os.path.join(trabajo, ruta)), f"falta el clip de {sid}")
    print(f"      {salidas['resumen']} en {time.time() - inicio:.0f}s")

    # LAS TRANSICIONES son una segunda pasada con WebGL sobre los fotogramas ya
    # escritos. Se comprueba que alguna se pinto de verdad -- no solo que se
    # eligiera -- y que su shader es uno del catalogo: con el flag de origen
    # opaco de 'file://' mal puesto, WebGL rechaza la textura y la transicion se
    # queda en nada SIN dar error (la promesa ni resuelve ni rechaza).
    cortes = transiciones.resolver(plan["escenas"], params)
    con_shader = [sid for sid, c in cortes.items() if c["tipo"] != "corte"]
    ok(con_shader, f"algun plano deberia encadenar: {cortes}")
    pintadas = {uid: f["frames_transicion"] for uid, f in resultado["unidades"].items()
                if f.get("frames_transicion")}
    ok(pintadas, f"alguna transicion deberia haberse pintado: {pintadas}")
    malos = [c["tipo"] for c in cortes.values()
             if c["tipo"] != "corte" and c["tipo"] not in transiciones.CATALOGO]
    igual(malos, [], "todas las transiciones repartidas estan en el catalogo")
    # y ninguna se come el plano que entra
    largas = {sid: c["duracion"] for sid, c in cortes.items()
              if c["duracion"] > 0.35 * next(
                  e["duracion"] for e in plan["escenas"] if e["id"] == sid) + 0.001}
    igual(largas, {}, "ninguna transicion pasa de un tercio del plano que entra")

    estado.completar("render", salidas, resultado["unidades"])
    igual(estado.estado_de("render"), "listo", "render queda listo")

    # REPARTIR EN PROCESOS NO CAMBIA UN PIXEL, y esto es lo que lo sostiene.
    #
    # Desde el 21-08-2026 los planos se capturan en varios procesos a la vez
    # : el techo no era el navegador sino lo que hace Python
    # con cada fotograma, y con hilos eso no escala. La promesa de ese cambio es
    # que es una palanca de VELOCIDAD y nada mas -- mismo Edge, misma pagina,
    # mismo codigo --, asi que el clip tiene que salir byte a byte igual.
    # Se comparan los PIXELES y no el fichero: el muxer de MP4 estampa la hora
    # en las cabeceras, asi que dos clips identicos nunca dan el mismo byte.
    def _huella_video(ruta):
        salida = subprocess.run(
            [medios.ffmpeg(), "-v", "error", "-i", ruta, "-an", "-f", "md5", "-"],
            capture_output=True, text=True, timeout=300, **medios.SIN_VENTANA)
        return ((salida.stdout or "").strip()
                or f"NO SE PUDO LEER {ruta}: {(salida.stderr or '')[-120:]}")

    print("      los mismos clips en fila que repartidos")
    # de la version RECIEN sellada y no de la carpeta de trabajo: `completar`
    # acaba de versionarla, y ahi ya no estan los clips
    versionado = proyecto.ruta_paso("render")
    huellas = {sid: _huella_video(os.path.join(versionado, ruta))
               for sid, ruta in salidas["clips"].items()}
    ok(all(h.startswith("MD5=") for h in huellas.values()),
       f"se pueden leer los clips de la version sellada: "
       f"{[h for h in huellas.values() if not h.startswith('MD5=')][:1]}")
    en_fila = p8_render.ejecutar(proyecto, dict(params, lotes=1), avisador("p8"))
    trabajo_f = proyecto.ruta_trabajo("render", crear=False)
    distintos = [sid for sid, ruta in en_fila["salidas"]["clips"].items()
                 if _huella_video(os.path.join(trabajo_f, ruta))
                 != huellas.get(sid)]
    igual(distintos, [],
          "el video sale identico se reparta en procesos o corra en fila: "
          "repartir es una palanca de velocidad, no de imagen")
    estado.completar("render", en_fila["salidas"], en_fila["unidades"])

    # rehacer un plano no rehace el video entero
    print("      re-render de un solo plano")
    objetivo = plan["escenas"][1]["id"]
    otros = [e["id"] for e in plan["escenas"] if e["id"] != objetivo]
    marcas = {sid: os.path.getmtime(os.path.join(proyecto.ruta_paso("render"),
                                                 f"clips/{sid}.mp4"))
              for sid in otros}
    time.sleep(1.1)
    parcial = p8_render.ejecutar(proyecto, params, avisador("p8"),
                                 unidades=[f"escena:{objetivo}"])
    nuevo = proyecto.ruta_trabajo("render", crear=False)
    rehechos = [uid for uid, ficha in parcial["unidades"].items()
                if ficha.get("origen") == "renderizado"]
    ok(f"escena:{objetivo}" in rehechos, "el plano pedido se rehace")
    ok(len(rehechos) <= 2,
       f"solo se rehace el plano pedido (y el siguiente si encadena): {rehechos}")
    sin_tocar = [sid for sid in otros
                 if os.path.getmtime(os.path.join(nuevo, f"clips/{sid}.mp4"))
                 == marcas[sid] and f"escena:{sid}" not in rehechos]
    ok(len(sin_tocar) >= len(otros) - 1,
       f"los demas clips se reutilizan sin recodificar ({len(sin_tocar)}/{len(otros)})")
    ok(os.path.exists(os.path.join(nuevo, "video.mp4")),
       "el MP4 se vuelve a montar con el clip nuevo")
    estado.completar("render", parcial["salidas"], parcial["unidades"])

    # LA BANDA SONORA VA LA ULTIMA, y no es capricho: vuelve a ejecutar el paso
    # entero, y `sembrar_trabajo` recopia la version activa al trabajo -- o sea
    # que le cambia la fecha a TODOS los clips. Puesta antes, la comprobacion de
    # que rehacer un plano no recodifica los demas media una fecha que habia
    # movido esta prueba, no el render.
    probar_banda_sonora(proyecto, estado, params, plan)
    probar_transicion_no_coge_la_vieja(proyecto)
    probar_imagen_sigue_a_su_frase()
    probar_el_corte_no_se_mueve_solo()
    probar_planificar_no_encoge(proyecto, params)
    probar_rehacer_uno_rehace_uno(proyecto, estado, params)
    return resultado


def probar_rehacer_uno_rehace_uno(proyecto, estado, params):
    """Pedir un plano rehace UN plano, no el video entero.

    Esto es dinero, y se escapo. El boton «Regenerar imagen» de cada tarjeta
    manda `unidades: [escena:S00X]` con `rehacer: true` -- lo segundo para que
    la cache no devuelva justo el dibujo que acabas de rechazar --, y `rehacer`
    entraba como `pedida = forzar or ...`, que con `forzar` en True da True
    para TODOS. Pulsar una tarjeta redibujaba los 225 planos: el 01-09 se
    cortaron a los 21, 0,84 USD, y entre los pisados iban tres que se acababan
    de dejar bien.

    Se mira lo que la pasada SELLA, que es lo que se ha vuelto a producir, y no
    el coste: con la cache del banco delante, un fallo asi puede salir gratis
    una vez y cobrarse la siguiente.
    """
    print("\n  [rehacer un plano rehace UN plano]")
    # LOS PARAMS DE ASSETS, no los que traiga quien llame: esto se cuelga del
    # final del render y alli lo que hay a mano son los de ese paso.
    params = estado.params("assets")
    plan = p6_assets.plan_actual(proyecto)
    sid = plan["escenas"][1]["id"]
    uid = f"escena:{sid}"

    hecho = p6_assets.ejecutar(proyecto, params, avisador("p6"),
                               unidades=[uid], rehacer=True)
    selladas = {u for u in (hecho["unidades"] or {}) if u.startswith("escena:")}
    igual(sorted(selladas), [uid],
          f"con unidades=[{uid}] y rehacer, se vuelve a producir ESE plano y "
          f"ninguno mas")
    ok(len(plan["escenas"]) > 1,
       "y el video tiene mas de un plano, o esta prueba no probaria nada")

    # y sin unidades, `rehacer` SI vale para todo: es el boton de redibujarlo
    # entero, y ahi si lo has pedido
    todas = p6_assets.ejecutar(proyecto, params, avisador("p6"), rehacer=True)
    selladas = {u for u in (todas["unidades"] or {}) if u.startswith("escena:")}
    igual(len(selladas), len(plan["escenas"]),
          "sin unidades, rehacer sigue valiendo para el video entero")

def probar_planificar_no_encoge(proyecto, params):
    """Planificar dos veces seguidas tiene que dar el MISMO video.

    Nadie pide esto, pero pasa solo: cada tanda vuelve a planificar, y si el
    plan que sale depende del plan que entra, el video se va deformando sin que
    nadie toque nada.

    El fallo que esto fija, y lo metio el arreglo del corte:
    heredar el corte de la pasada anterior es lo correcto, pero se heredaba de
    `plan["escenas"]`, que es el corte YA PROCESADO -- `_fundir_cartelas` junta
    planos, la firma se pega, las menciones se saltan --. Volver a pasar eso por
    el mismo molino funde lo ya fundido: medido sobre un video real, 225 planos
    pasaban a 221, luego 219, luego 215. Por eso el corte crudo viaja aparte
    en `plan["corte"]`.
    """
    print("\n  [planificar dos veces da el mismo video]")
    plan = p6_assets.planificar(proyecto, params)
    ok(bool(plan.get("corte")),
       "el plan lleva el corte CRUDO aparte: sin el, la pasada siguiente solo "
       "puede heredar del resultado, que es el fallo que esto cubre")
    ok(len(plan["corte"]) >= len(plan["escenas"]),
       "y trae al menos tantos trozos como planos: fundir solo puede quitar")
    cuentas = [len(plan["escenas"])]
    for _ in range(3):
        plan = p6_assets.planificar(proyecto, params, previo=plan)
        cuentas.append(len(plan["escenas"]))
    igual(len(set(cuentas)), 1,
          f"cuatro pasadas seguidas dan siempre los mismos planos: {cuentas}")

def probar_el_corte_no_se_mueve_solo():
    """Regrabar la misma frase no puede recortar el video entero.

    El fallo que esto fija: el reparto de planos se decide con
    las marcas de palabra, o sea con los milisegundos de la voz. Y una voz
    sintetizada dos veces no da los mismos milisegundos. El 31-08 se regrabo el
    mismo guion --identico palabra por palabra--, las marcas se movieron unas
    centesimas, y el reparto optimo paso de 222 planos a 217. Detras se llevo
    las 225 imagenes, que se guardan por el numero del plano.

    El optimizador no se equivocaba: con otras duraciones, otro reparto es de
    verdad mejor. Lo que estaba mal era volver a preguntarselo.
    """
    print("\n  [el corte no se mueve solo al regrabar la voz]")
    segmentar = medios.motor("guion/segmentar.py")

    frase = ("hace cien anos cinco gramos de oro daban de comer a una familia "
             "un mes entero hoy siguen dando para la compra del mes y eso "
             "deberia bastar para entender el resto de la historia").split()

    def voz(desfase):
        """La misma frase dicha dos veces: cada palabra cae unas centesimas antes."""
        palabras, reloj = [], 0.0
        for i, w in enumerate(frase):
            dura = 0.30 + 0.02 * ((i * 7) % 5)
            palabras.append({"w": w, "s": round(reloj, 3),
                             "e": round(reloj + dura, 3)})
            reloj += dura + 0.06 + desfase * ((i * 3) % 4)
        return palabras

    primera, segunda = voz(0.0), voz(0.012)
    corte = segmentar.segmentar(primera, 1.0, 4.0, reparto={})
    previas = segmentar.construir_escenas(corte)
    de_cero = segmentar.construir_escenas(
        segmentar.segmentar(segunda, 1.0, 4.0, reparto={}))
    heredado = segmentar.construir_escenas(
        segmentar.heredar(segunda, previas, minimo=1.0, maximo=4.0, reparto={}))

    ok(len(de_cero) != len(previas) or
       [e["narracion"] for e in de_cero] != [e["narracion"] for e in previas],
       f"cortando de cero, la misma frase da OTRO reparto ({len(previas)} planos "
       f"-> {len(de_cero)}): es el fallo que se esta cubriendo")
    igual([e["narracion"] for e in heredado], [e["narracion"] for e in previas],
          "heredando, cada plano sigue diciendo exactamente lo mismo")
    movidos = sum(1 for a, b in zip(heredado, previas)
                  if abs(a["t_in"] - b["t_in"]) > 0.001)
    ok(movidos >= len(previas) - 1,
       f"y con los tiempos de la VOZ NUEVA: {movidos} de {len(previas)} planos "
       f"entran en otro instante. Se resincroniza, no se congela -- heredar el "
       f"corte con los tiempos viejos desencajaria la imagen del audio")
    igual(heredado[0]["t_in"], round(segunda[0]["s"], 3),
          "el primer plano arranca en la primera palabra de la toma nueva")
    igual(heredado[-1]["t_out"], round(segunda[-1]["e"], 3),
          "y el ultimo cierra en la ultima, sin adelanto ni cola: eso lo pone "
          "_encadenar despues, y sumarlo aqui alargaba el video 0,87 s")

    # UNA PALABRA CAMBIADA no puede mover ninguna frontera
    tocada = [dict(w) for w in segunda]
    tocada[3]["w"] = "gramillos"
    retocado = segmentar.construir_escenas(
        segmentar.heredar(tocada, previas, minimo=1.0, maximo=4.0, reparto={}))
    igual([len(e["narracion"].split()) for e in retocado],
          [len(e["narracion"].split()) for e in previas],
          "cambiar UNA palabra deja los planos donde estaban: corregir una "
          "preposicion no puede volver a repartir el video entero")

    # UN TEXTO DE CERO no se hereda: se corta
    otro = voz(0.0)
    for w in otro:
        w["w"] = "zumbido"
    igual(segmentar.heredar(otro, previas, minimo=1.0, maximo=4.0, reparto={}), [],
          "y un texto que ya no se reconoce NO hereda nada: se corta de cero, "
          "que es lo unico honesto cuando lo de antes ya no esta")

def probar_imagen_sigue_a_su_frase():
    """Una imagen es de lo que DICE su plano, no del numero que le toco.

    El fallo que esto fija: el corte sale de las marcas de
    palabra, asi que una voz nueva vuelve a cortar. El 31-08 un plan de 222
    planos paso a 217 y los dibujos, guardados como `S003.png`, se quedaron
    quietos: 200 de 225 pasaron a ilustrar la frase de al lado. Y no se ve
    venir, porque cada plano SIGUE teniendo su imagen.

    Se reproduce el caso real: cinco planos que pasan a cuatro. Y se comprueba
    lo unico que importa de verdad -- que ningun plano acaba ilustrando otra
    cosa --, no cuantos ficheros se movieron.
    """
    print("\n  [la imagen sigue a su frase, no a su numero]")
    carpeta = tempfile.mkdtemp(prefix="recolocar_")
    try:
        antes = ["Hace cien anos, cinco gramos de oro daban de",
                 "comer a una familia un mes entero.",
                 "Hoy siguen dando para la compra del mes.",
                 "Si hace 100 anos hubieses guardado ese dinero en billetes,",
                 "no te daria ni para una barra de pan."]
        for i, frase in enumerate(antes, start=1):
            sid = "S%03d" % i
            with io.open(os.path.join(carpeta, sid + ".png"), "wb") as fh:
                fh.write(frase.encode("utf-8"))   # el png dice de quien es
            json.dump({"tipo": "escena", "id": sid, "png": "escenas/%s.png" % sid,
                       "narracion": frase, "t_in": 0.0, "t_out": 1.0},
                      io.open(os.path.join(carpeta, sid + ".json"), "w",
                              encoding="utf-8"))

        # el mismo texto, cortado en cuatro: es lo que devuelve el segmentador
        # cuando se regraba la voz
        ahora = ["Hace cien anos, cinco gramos de oro daban de comer a una familia",
                 "un mes entero. Hoy siguen dando para la compra del mes.",
                 "Si hace 100 anos hubieses guardado ese dinero en billetes,",
                 "no te daria ni para una barra de pan."]
        escenas = [{"id": "S%03d" % i, "narracion": frase,
                    "t_in": float(i), "t_out": float(i) + 1.0}
                   for i, frase in enumerate(ahora, start=1)]

        informe = p6_assets._recolocar_escenas(carpeta, escenas)

        for escena in escenas:
            ficha = json.load(io.open(os.path.join(carpeta, escena["id"] + ".json"),
                                      encoding="utf-8"))
            ok(p6_assets._mismo_dicho(p6_assets._texto_clave(ficha),
                                      p6_assets._texto_clave(escena)),
               f"{escena['id']} ilustra lo que dice: «{ficha['narracion'][:34]}»")
            igual(ficha["id"], escena["id"],
                  "y la ficha lleva su numero nuevo, que es el que lee la rejilla")

        pan = io.open(os.path.join(carpeta, "S004.png"), "rb").read().decode("utf-8")
        igual(pan, "no te daria ni para una barra de pan.",
              "el dibujo de la barra de pan viaja de S005 a S004 EN VEZ de "
              "quedarse quieto ilustrando lo que dice ahora S005")
        igual(informe["obsoletas"], [],
              "y aqui no sobra ninguno: el guion no cambio, solo el corte")

        # y una frase que SI cambia: la imagen NO se tira ni se rehace sola
        otras = [dict(escenas[0]),
                 {"id": "S002", "narracion": "El oro no paga dividendos ni alquiler.",
                  "t_in": 1.0, "t_out": 2.0}]
        informe = p6_assets._recolocar_escenas(carpeta, otras)
        ok("S002" in informe["obsoletas"],
           "una frase escrita de cero deja su plano sin imagen SUYA: se dice, "
           "para que lo decida quien mira")
        ok(os.path.exists(os.path.join(carpeta, "S002.png")),
           "pero el dibujo NO se borra: obsoleto no es pendiente, y rehacerlo "
           "cuesta dinero que nadie ha pedido gastar")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

def probar_transicion_no_coge_la_vieja(proyecto):
    """La transicion se cuece sobre el fotograma DE ESTE RENDER, no sobre el viejo.

    El fallo que esto fija: `trabajo/ultimo/` no se vacia nunca
    y `sembrar_trabajo` recopia dentro la version activa entera, asi que TODO
    render arranca con los ultimos fotogramas de la pasada anterior ya puestos.
    Mientras la barrera entre procesos solo miraba `os.path.exists`, se cumplia
    al instante y el plano que iba por delante mezclaba su transicion con la
    imagen VIEJA. En el video largo le paso a 25 de 43 transiciones, y no habia ni
    una prueba que lo mirara.

    Se prueba la BARRERA y no el render entero a proposito: reproducir la carrera
    de verdad pide dos procesos y suerte con el reparto, y una prueba que a veces
    pasa esta describiendo un fallo del producto.
    """
    print("\n  [la transicion no se coce sobre el fotograma viejo]")
    carpeta = tempfile.mkdtemp(prefix="ultimo_viejo_")
    try:
        viejo = os.path.join(carpeta, "S001.png")
        with io.open(viejo, "wb") as fh:
            fh.write(b"no soy de este render")
        # el fichero existe y es ANTERIOR al arranque: la barrera no puede darlo
        # por bueno por mucho que este ahi
        arranque = os.path.getmtime(viejo) + 1.0
        ok(os.path.exists(viejo), "el ultimo fotograma de la pasada anterior sigue en su sitio")
        ok(not p8_render._fresco(viejo, arranque),
           "y NO cuenta como fresco: existir no es haberlo escrito este render")
        igual(p8_render._esperar(viejo, arranque, limite=0.3), False,
              "la espera se agota en vez de darla por cumplida al instante, que "
              "es lo que cocia 25 de 43 transiciones sobre la imagen vieja")
        # y en cuanto lo escribe este render, la barrera se abre
        with io.open(viejo, "wb") as fh:
            fh.write(b"si soy de este render")
        os.utime(viejo, (arranque + 5.0, arranque + 5.0))
        ok(p8_render._fresco(viejo, arranque), "reescrito por este render, ya vale")
        igual(p8_render._esperar(viejo, arranque, limite=0.3), True,
              "y la espera se cumple de verdad")
        ok(p8_render.ESPERA_ANTERIOR_S >= 600,
           f"y la espera cubre el desfase real entre lotes ({p8_render.ESPERA_ANTERIOR_S:.0f} s): "
           f"medido, un plano llego a ir 122 s por detras de su anterior")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


# ------------------------------------------------------------------- main

def main():
    # NO HAY NADA QUE COMPROBAR ANTES DE EMPEZAR. Aqui habia un aviso de que
    # faltaban «los datos reales» en una carpeta de otro proyecto; el material
    # se fabrica ahora en este mismo fichero (ver `locucion_falsa` y `_lamina`),
    # asi que la unica dependencia de fuera son ffmpeg y Edge, y las dos las
    # dicen en su sitio los pasos que las usan.
    #
    # EL HISTORICO DE TIEMPOS, A UNA COPIA. Desde que p6, p7 y p8 anotan cuanto
    # tardan, esta suite escribiria en el de VERDAD: diez planos a 640x360
    # tardan una fraccion de lo que tardan ciento veinte a 1920x1080, y con esas
    # muestras dentro la barra de un video real prometeria la mitad de tiempo.
    # Es la misma trampa que ya tenia la suite de voz con la cadencia.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(
        tempfile.gettempdir(), "estudio_prueba_visual", "estadisticas.json")
    print("=" * 70)
    print("PRUEBA DE LOS PASOS 6, 7 y 8 (material fabricado por la suite)")
    print("=" * 70)

    proyecto, estado = preparar_proyecto()
    bitacora = Bitacora(proyecto)
    print(f"  proyecto en {proyecto.raiz}")

    params = parametros(os.path.join(CARPETA, "_arte"))
    estado.set_params("assets", params)
    resultado = probar_assets(proyecto, estado, params)
    resultado["params"] = params
    bitacora.anotar("prueba", "assets", {"escenas": len(resultado["plan"]["escenas"])})

    probar_cascada(proyecto, estado, resultado)

    # EL PLAN DE ROTULOS VA POR UNIDAD, y aqui se comprueba de punta a punta:
    # se escribe donde lo escribe la pantalla y se mira si sale DIBUJADO. Es el
    # tramo que ni la suite de piezas (que solo lee) ni la de la API (que solo
    # escribe) recorren enteros. Suelto ensuciaria el video entero.
    params_callouts = {"previsualizar": True, "unidades": {
        "escena:S001": {"rotulos": [{"tipo": "rotulo_lugar",
                                     "texto": "PUERTO POR UNIDAD"}]}}}
    estado.set_params("callouts", params_callouts)
    probar_callouts(proyecto, estado, params_callouts)

    params_render = {"fps": 12, "resolucion": [640, 360], "calidad_video": "baja"}
    estado.set_params("render", params_render)
    probar_render(proyecto, estado, params_render)

    # el gestor de trabajos es como lo llamara el estudio: en un hilo, con
    # progreso y con la marca de ejecutando limpiada al acabar
    print("\n  INTEGRACION · a traves de GestorTrabajos")
    gestor = GestorTrabajos(estado=estado, bitacora=bitacora)
    trabajo_id = gestor.lanzar("describir", lambda avisar: p6_assets.describir(params),
                               paso="assets")
    ficha = gestor.esperar(trabajo_id, 60)
    igual(ficha["estado"], "listo", "el gestor ejecuta un paso sin colgarse")
    ok(isinstance(ficha["resultado"], str) and len(ficha["resultado"]) > 40,
       "describir() devuelve una frase util")
    for modulo in (p6_assets, p7_callouts, p8_render):
        ok(isinstance(modulo.PARAMS_POR_DEFECTO, dict) and modulo.PARAMS_POR_DEFECTO,
           f"{modulo.__name__} expone PARAMS_POR_DEFECTO")
        ok(isinstance(modulo.describir({}), str),
           f"{modulo.__name__} expone describir()")

    # va la ultima a proposito: deja en trabajo/ una pasada sin planos, y lo que
    # viene detras (p7, p8) lee de la version, no de trabajo
    probar_solo_assets(proyecto, estado, params)

    print("\n" + "=" * 70)
    if _fallos:
        print(f"FALLOS: {len(_fallos)} de {_comprobaciones[0]} comprobaciones")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"PASOS 6-7-8 OK: {_comprobaciones[0]} comprobaciones pasan")
    print(f"proyecto de la prueba: {proyecto.raiz}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
