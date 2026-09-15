"""
Las piezas que se verificaron a mano y no tenian suite.

Diez cosas nuevas entraron en el Estudio comprobadas en la consola, con numeros
reales, y ninguna quedo protegida. En un repo cuya norma es "verificado
ejecutando" eso es deuda, y esta suite la salda. Cubre, por orden de riesgo:

  1. catalogo_visual._limpiar   lo que descarta y lo que avisa
  2. p7_callouts                arquetipos, paleta derivada de la guia,
                                la franja inferior cuando esta pisada,
                                elementos_de con y sin plan, y la cabeza
  3. coste.coste_openai         por tokens, por imagen de respaldo, sin doble
                                conteo
  4. segmentar                  que no deje huerfana la primera palabra
  5. voz.espaciar               que el relleno sea ruido de sala y no ceros
  6. p6._capa_vectorial         prioridad de candidatos y el tope de UNO

Todo es unitario y en memoria: ni red ni API de imagen. Corre en
segundos, que es lo que hace que se ejecute de verdad.

Y eso ULTIMO ESTA ATADO, no prometido: `_prohibir_pagar()` sustituye `generar`
--lo unico del motor de imagen que cuesta dinero-- por una funcion que lanza.
Una llamada que nadie previo sale como un fallo con su traza, y no como una
factura. Hizo falta: `prueba_rehacer_de_verdad` se calculaba a mano el nombre
del fichero de la cache, el codigo le anadio `tamano` a la firma, la copia se
quedo atras y la llamada siguio camino hasta OpenAI.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_piezas.py
"""
import io
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time

import numpy as np  # noqa: E402  (la pista de efectos se suma en numpy)
from PIL import Image  # noqa: E402  (va con el motor de imagen)

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

import cartelas  # noqa: E402
import catalogo_visual  # noqa: E402
import cli_claude  # noqa: E402
import comun  # noqa: E402
import direccion  # noqa: E402
import redactor  # noqa: E402
import estilo  # noqa: E402
import medios  # noqa: E402
import recetas  # noqa: E402
import sonido  # noqa: E402
import subtitulos  # noqa: E402
import tipografia  # noqa: E402
import transiciones  # noqa: E402
import p4_voz  # noqa: E402
import p2_brief
import p6_assets  # noqa: E402
import p7_callouts  # noqa: E402
import p8_render  # noqa: E402

from nucleo import coste  # noqa: E402

_fallos = []
_comprobaciones = [0]


def ok(condicion, mensaje):
    _comprobaciones[0] += 1
    if not condicion:
        _fallos.append(mensaje)
        print(f"    FALLO: {mensaje}")
    else:
        print(f"  ok   {mensaje}")
    return bool(condicion)


def igual(obtenido, esperado, mensaje):
    return ok(obtenido == esperado, f"{mensaje} (obtenido {obtenido!r}, "
                                    f"esperado {esperado!r})")


def titulo(texto):
    print(f"\n[{texto}]")


# ------------------------------------------------------ 1. catalogo_visual

def prueba_catalogo():
    titulo("catalogo_visual._limpiar")
    construibles = {"despacho": ["mesa", "ventanal"], "puerto": ["buque"]}
    datos = {
        "reparto": {"Udai Hussein": {"nombre": "Udai", "descripcion": "a young man",
                                     "palabras": ["udai"]},
                    "": {"descripcion": "sin nombre"}},
        "sets": {
            "despacho_de_saddam": {"base": "despacho", "luz": "warm lamp",
                                   "palabras": ["despacho"],
                                   "elementos": {"mesa": {"etiqueta": "LA MESA",
                                                          "palabras": ["mesa"]},
                                                 "piscina": {"etiqueta": "NO EXISTE"}}},
            "quirofano_central": {"base": "quirofano", "palabras": ["quirofano"]},
        },
        "capitulos": {"B001": {"titulo": "El principio"},
                      "B999": {"titulo": "Un bloque que no existe"}},
        "beats": [
            {"desde": "B002", "hasta": "B001", "set": "despacho_de_saddam",
             "personajes": ["udai_hussein", "fantasma"], "tono": "TENSO"},
            {"desde": "B404", "hasta": "B404", "set": "despacho_de_saddam"},
            {"desde": "B003", "hasta": "B003", "set": "inventado"},
        ],
        "componentes": {
            "mapa_ruta": {"tipo": "mapa", "palabras": ["ruta"],
                          "config": {"region": "america",
                                     "origen": {"nombre": "colombia", "coord": [3.9, -77.0]},
                                     "destino": {"nombre": "mexico", "coord": [19.0, -104.3]}}},
            "mapa_de_europa": {"tipo": "mapa",
                               "config": {"region": "europa",
                                          "origen": {"coord": [1, 2]},
                                          "destino": {"coord": [3, 4]}}},
            "mapa_sin_coord": {"tipo": "mapa",
                               "config": {"region": "america",
                                          "origen": {"coord": ["norte", "sur"]},
                                          "destino": {"coord": [3, 4]}}},
        },
        "lugares": {"Manzanillo": "puerto de manzanillo", "de": "PREPOSICION"},
    }
    limpio = catalogo_visual._limpiar(datos, ["B001", "B002", "B003", "B004"])
    avisos = " | ".join(limpio["avisos"])

    igual(sorted(limpio["reparto"]), ["udai_hussein"],
          "un personaje sin identificador no entra en el reparto")
    ok("despacho_de_saddam" in limpio["sets"] and "quirofano_central" in limpio["sets"],
       "los sitios declarados sobreviven, cada uno con su descripcion")

    igual(sorted(limpio["capitulos"]), ["B001"],
          "un capitulo en un bloque inexistente se descarta")
    ok("B999" in avisos, "y se dice de cual se trata")

    igual([(b["desde"], b["hasta"]) for b in limpio["beats"]],
          [("B001", "B002"), ("B003", "B003")],
          "un beat con el rango del reves se endereza, y uno a un bloque "
          "inexistente se cae")
    igual(limpio["beats"][0]["personajes"], ["udai_hussein"],
          "un personaje que no esta en el reparto no entra en el beat")
    igual(limpio["beats"][0]["tono"], "tenso", "el tono se normaliza")
    igual(limpio["beats"][1]["set"], None,
          "un beat a un set no declarado se queda sin sitio")
    ok("B404" in avisos, "y se avisa del beat descartado")

    igual(limpio["cobertura"], 0.75,
          "la cobertura dice que un cuarto del guion se ha quedado sin beat")
    ok("B004" in avisos, "y se nombra el bloque sin cubrir")
    ok("mas de un beat" not in avisos,
       "y donde ningun bloque lleva dos beats, no se avisa de solapes")

    # LOS SOLAPES SE DICEN, Y NO SE RECHAZAN (07-09-2026). La instruccion pide
    # el guion «sin huecos y sin solaparte» y esto solo miraba los huecos, asi
    # que el solape pasaba en silencio -- y con el, en el video del oro, 51 de
    # los 146 beats que ningun plano podia llegar a usar. Hoy se reparten
    # (`p6_assets._beats_por_escena`), pero un tramo con mas beats que planos
    # sigue dejando alguno fuera y esto es lo unico que lo cuenta.
    solapado = catalogo_visual._limpiar(
        {"sets": {"quiosco": {"base": "quiosco"},
                  "bolsa": {"base": "parque de bolsa"}},
         "beats": [{"desde": "B001", "hasta": "B002", "set": "quiosco"},
                   {"desde": "B001", "hasta": "B001", "set": "bolsa"}]},
        ["B001", "B002"])
    dice = " | ".join(solapado["avisos"])
    ok("1 bloque(s) con mas de un beat" in dice,
       "con dos beats sobre el mismo bloque, se dice cuantos bloques comparten")
    ok("hasta 2 en uno" in dice and "B001" in dice,
       "cuantos beats lleva el que mas, y cual es")
    igual(len(solapado["beats"]), 2,
          "y los dos beats se quedan: son dos ideas visuales buenas, no un fallo")
    igual(solapado["cobertura"], 1.0,
          "un solape no es un hueco: la cobertura sigue entera")

    igual(sorted(limpio["componentes"]), ["mapa_ruta"],
          "solo sobrevive el mapa que se puede dibujar de verdad")
    ok("europa" in avisos, "se dice que esa region no se puede dibujar")
    ok("coordenadas" in avisos, "y que unas coordenadas no eran validas")
    igual(limpio["lugares"], {"manzanillo": "PUERTO DE MANZANILLO"},
          "un lugar de dos letras saltaria en cualquier frase y se descarta")

    titulo("catalogo_visual: las regiones dibujables salen del motor de mapas")
    ok("america" in catalogo_visual.regiones_de_mapa(),
       "y las regiones dibujables, del propio motor de mapas")


# --------------------------------------------------------- 2. p7_callouts

def prueba_reparto_inventado():
    """Que al catalogo no le falte gente por no venir descrita en el guion.

    Un guion documental casi nunca describe a nadie: dice «Nubla», «un
    empleado», y sigue. Y el catalogo lo tomaba como motivo para dejarlos fuera,
    con su aviso y todo: «se nombra varias veces pero el guion no da ninguna
    descripcion fisica, asi que no se pudo crear una entrada sin inventarla».

    El razonamiento suena prudente y es al reves: un reparto vacio NO significa
    que no salga nadie, significa que no hay hoja de personaje. Y sin hoja, cada
    plano se inventa la cara POR SU CUENTA. Una cara inventada una vez y repetida
    en cuarenta y ocho planos es un personaje; cuarenta y ocho caras inventadas
    por separado no son nadie -- que es el fallo que este catalogo existe para
    impedir, y esta escrito con esas palabras en su propio docstring.
    """
    titulo("catalogo: si el guion no describe a alguien, se inventa la ficha")
    criterio = catalogo_visual.CRITERIO
    ok("SI EL GUION NO LO DESCRIBE, INVENTATELO" in criterio,
       "se le dice con esas palabras, no como excepcion")
    ok("no es una licencia: es la regla" in criterio,
       "y como regla: casi ningun guion documental describe a nadie")
    ok("cuarenta y ocho caras inventadas" in criterio,
       "con el porque: sin hoja, la cara se inventa igual, pero distinta cada vez")
    ok("coherente con lo que SI dice el guion" in criterio,
       "acotado a lo que el guion sostiene: epoca, sitio, oficio, edad")
    ok("Sin nombres de personas reales" in criterio,
       "y sin retratar a alguien que existe: se describe por oficio y edad")
    ok("'avisos'" in criterio and "se invento" in criterio,
       "y se dice en los avisos, que es lo que permite corregirlo mirando")

def prueba_sitios_sin_tramo():
    """Un sitio que ningun tramo usa se QUITA, no se vuelve a pedir el catalogo.

    El sitio de un plano lo fija su TRAMO: `p6_assets._asignar_sets` calcula uno
    por palabras y acto seguido lo pisa con `beat["set"]` si el tramo trae uno.
    Asi que con todos los tramos con sitio, uno que ningun tramo nombra no lo
    puede elegir nadie: se escribe, se guarda, se pinta en la pantalla y no sale
    en el video. Salieron 19 de 31 en un catalogo real.

    Lo primero que se hizo fue reintentar la llamada, y estaba mal: reintentar es
    pagar otra tirada esperando que salga distinto. La inconsistencia no es de
    criterio -- el video tiene los tramos que tiene --, es que se describieron
    sitios de mas, y eso se quita con una linea y sin gastar nada.
    """
    titulo("catalogo: el sitio que no puede usar nadie se quita")
    bloques = [{"id": f"B{i:03d}", "texto": "palabra " * 20} for i in range(1, 4)]
    ids = [b["id"] for b in bloques]
    crudo = {
        "reparto": {},
        "sets": {"usado": {"descripcion": "a", "palabras": ["a"]},
                 "huerfano": {"descripcion": "b", "palabras": ["b"]}},
        "beats": [{"desde": "B001", "hasta": "B003", "set": "usado",
                   "tono": "neutro"}],
    }
    ficha = catalogo_visual._limpiar(crudo, ids)        # noqa: SLF001
    igual(sorted(ficha["sets"]), ["usado"],
          "con todos los tramos con sitio, el que sobra se va")
    ok(any("se han quitado" in a and "huerfano" in a for a in ficha["avisos"]),
       f"y se dice cual y por que: {' '.join(ficha['avisos'])[:110]}")

    titulo("catalogo: pero no se quita el que todavia puede salir")
    crudo2 = {**crudo, "beats": [
        {"desde": "B001", "hasta": "B002", "set": "usado", "tono": "neutro"},
        {"desde": "B003", "hasta": "B003", "tono": "neutro"}]}
    ficha2 = catalogo_visual._limpiar(crudo2, ids)      # noqa: SLF001
    igual(sorted(ficha2["sets"]), ["huerfano", "usado"],
          "con un tramo sin sitio, `_elegir_set` todavia puede elegirlo por "
          "palabras: quitarlo seria quitarle una opcion al motor")
    ok(any("sin tramo propio" in a for a in ficha2["avisos"]),
       "y se dice que se quedan por eso")

    titulo("catalogo: y se le pide al agente que no los proponga")
    ok("CADA SITIO QUE DECLARES TIENE QUE USARLO ALGUN TRAMO"
       in catalogo_visual.CRITERIO,
       "la regla va en el criterio: evitarlo sale mas barato que limpiarlo")
    ok("cruza las dos listas" in catalogo_visual.CRITERIO,
       "con la comprobacion dicha: todo id de 'sets' en el 'set' de algun tramo")

def prueba_planos_por_sitio():
    """Los sitios que se piden salen de cuantos planos hay, no de una constante.

    El catalogo pedia «dos planos por sitio» con PLANOS_POR_SET, pero cuantos
    planos hay lo decide min_s/max_s, que se elige en la tarjeta de assets y que
    este paso no veia. Con planos de 1-4 s salen unos 48 planos sobre los 9
    sitios que se proponian: casi cinco por sitio en vez de dos, y de ahi los
    encuadres repetidos. Una intencion sin aritmetica no se puede obedecer.
    """
    titulo("catalogo: cuantos sitios pedir sale de cuantos planos hay")
    bloques = [{"id": f"B{i:03d}", "texto": "palabra " * 60} for i in range(6)]

    largos = catalogo_visual.planos_previstos(bloques, 3.0, 6.0)
    cortos = catalogo_visual.planos_previstos(bloques, 1.0, 4.0)
    ok(cortos > largos,
       f"el mismo guion da mas planos si los planos son mas cortos "
       f"({cortos} con 1-4 s contra {largos} con 3-6 s)")
    igual(catalogo_visual.planos_previstos([], 3.0, 6.0), 0,
          "sin guion no hay cuenta que dar")

    texto = catalogo_visual._cuantos_planos(48, 1.0, 4.0)
    ok("48 planos" in texto, "el prompt lleva los planos que van a salir")
    ok("24 sitios COMO MINIMO" in texto,
       "y la division ya hecha: pedirle al agente que divida es pedirle "
       "que se equivoque")
    ok("1-4 s" in texto, "con la duracion de plano de la que sale el numero")

    igual(catalogo_visual._cuantos_planos(0, 3.0, 6.0), "",
          "y si no se sabe cuantos planos hay, no se inventa un minimo: uno "
          "inventado se obedece igual de bien que uno cierto")
    igual(catalogo_visual._cuantos_planos(10, None, None), "",
          "tampoco sin duracion de plano")

    entero = catalogo_visual.CRITERIO.format(
        planos_por_set=catalogo_visual.PLANOS_POR_SET,
        cuantos_planos=texto, sets_construibles="(sets)", regiones_mapa="(mapa)")
    ok("24 sitios COMO MINIMO" in entero,
       "y todo eso entra en el criterio que lee el agente")


def _fundir_ct(escenas, puestas, p=None, idioma=None):
    """`_fundir_cartelas` con el andamiaje que la prueba no necesita ver.

    `beats` va EN PARALELO a `escenas` en el motor y el fundido recorta los dos a
    la vez; aqui se pasa una lista de relleno del mismo largo para que ese
    recorte se ejerza de verdad en cada prueba.
    """
    beats = [{} for _ in escenas]
    fichas = p6_assets._fundir_cartelas(escenas, beats, puestas, p, idioma)
    igual(len(beats), len(escenas),
          "los beats se recortan con las escenas: si no, cada plano posterior "
          "a un fundido escribiria el prompt de otro beat")
    return fichas


def prueba_callouts():
    titulo("p7_callouts: la paleta sale de la guia de estilo del video")
    base = dict(p7_callouts.PARAMS_POR_DEFECTO["paleta"])
    igual(p7_callouts.paleta_de_guia(None, base), base,
          "sin guia se queda la paleta de los params")
    guia = {"paleta": ["#0d1b2a", "#1b263b", "#e0e1dd", "#ff8800"]}
    derivada = p7_callouts.paleta_de_guia(guia, base)
    ok(derivada != base, "con guia, los colores cambian")
    ok(all(str(v).startswith("#") for v in derivada.values()),
       f"y todos son colores validos: {derivada}")
    igual(p7_callouts.paleta_de_guia(guia, base), derivada,
          "y es DETERMINISTA: la misma guia da la misma paleta")

    titulo("p7_callouts: el subtitulo NO SE MUEVE, y por eso va en otra capa")
    # Esto eran cincuenta lineas comprobando que la caja del rotulo esquivaba el
    # dibujo, y despues veinte comprobando que la banda comun no bajaba mas que
    # la de ningun plano suelto. Las dos cosas existian porque la capa iba DENTRO
    # del zoom. Desde el 23-08 va fuera (PENDIENTE 38), asi que lo que hay que
    # comprobar es justo eso: que salen dos capas y que el subtitulo esta en la
    # que no escala.
    escena_sub = {"id": "S001", "narracion": "one two three",
                  "marcas": [[0.0, 0.4], [0.5, 0.9], [1.0, 1.4]],
                  "t_in": 0.0, "t_out": 3.0}
    movil, fija, fichas = p7_callouts.capa_de_escena(
        escena_sub, p7_callouts._con_defectos({}))
    ok(fichas, f"el plano lleva subtitulo: {len(fichas)} trozo(s)")
    ok("<text" not in movil,
       "la capa que ESCALA no lleva ni una letra del subtitulo: si la llevara, "
       "el subtitulo haria zoom con la imagen")
    ok("<text" in fija, "y la capa QUIETA si")
    ok(f'viewBox="0 0 {p7_callouts.SALIDA[0]} {p7_callouts.SALIDA[1]}"' in fija,
       "la capa quieta esta dibujada en el cuadro de SALIDA (1920x1080), no en "
       "el lienzo de generacion: fuera del zoom no hay lienzo que valga")
    ok(f'viewBox="0 0 {p7_callouts.TAMANO[0]} {p7_callouts.TAMANO[1]}"' in movil,
       "y la que escala sigue en el lienzo de generacion")

    titulo("p7_callouts: el subtitulo va en caja negra ligera y a semibold")
    ok("<rect" in fija, "lleva caja detras de los renglones")
    ok('fill="#000000"' in fija, "negra")
    ok(f'opacity="{p7_callouts.SUB_CAJA_OPACIDAD:g}"' in fija,
       f"y ligera: opacidad {p7_callouts.SUB_CAJA_OPACIDAD}")
    ok(f'font-weight="{p7_callouts.SUB_PESO}"' in fija,
       f"el texto sube a semibold ({p7_callouts.SUB_PESO}); era 400")
    ok("stroke=" not in fija,
       "y el perfilado se va con la caja: con caja y semibold seria la tercera "
       "capa de contraste para el mismo trabajo")

    titulo("p7_callouts: un plano CON CARTELA no lleva subtitulo")
    # Del 23 al 24-08 lo llevo, y se revirtio por decision del canal. Caben las
    # dos cosas --la cabecera vive en el espacio del plano y el subtitulo en el
    # del cuadro-- pero caber no es convenir: una cartela DESTILA la frase que se
    # esta diciendo, asi que el subtitulo de debajo dice lo mismo con otras
    # palabras y el plano tiene dos textos compitiendo.
    cabecera = dict(escena_sub, cartela={"plantilla": "tesis", "fondo": "imagen",
                                         "datos": {"texto": "Una frase"}})
    svg_c, fichas_c = p7_callouts.capa_fija_de(cabecera, p7_callouts._con_defectos({}))
    igual(fichas_c, [], "un plano con cartela no lleva ni un trozo de subtitulo")
    ok("<text" not in svg_c, "y su capa quieta sale vacia de verdad, no oculta")
    # Y el de al lado, SIN cartela, lo sigue llevando: la regla es «cuando hay
    # cartela», no «cuando hay cabecera en el video».
    _, fichas_n = p7_callouts.capa_fija_de(dict(escena_sub),
                                           p7_callouts._con_defectos({}))
    ok(fichas_n, f"y el plano sin cartela sigue con sus {len(fichas_n)} trozo(s)")

    titulo("p8_render: la capa QUIETA va ENCIMA, y dicho, no deducido")
    # En una cabecera, el velo de la cartela cubre el cuadro entero y vive dentro
    # de #camara. Por orden del DOM la capa quieta ya quedaba encima --medido
    # sobre el MP4: el subtitulo llega a su color exacto tambien en las
    # cabeceras--, pero eso depende de que nadie le ponga un transform o un
    # will-change a #capafija. Con el z-index escrito no depende de nada.
    pagina = p8_render.PAGINA
    ok("#camara{z-index:0}" in pagina, "la camara declara su z-index")
    ok("z-index:1" in pagina.split("#capafija{")[1].split("}")[0],
       "y la capa quieta el suyo, por encima")
    ok(pagina.index("__CAPA__") < pagina.index("__CAPAFIJA__"),
       "y ademas va despues en el DOM: las dos cosas dicen lo mismo")

    titulo("p7_callouts: la caja se ancla POR ABAJO, una linea o dos")
    # Un subtitulo de una linea y otro de dos empiezan en el mismo sitio: al
    # reves, el ojo tendria que buscarlo en cada corte. La caja tiene que
    # respetar ese anclaje, y no lo hacia: `base` ya es la linea base del primer
    # renglon, asi que restarle otra vez los saltos subia la caja de dos lineas
    # 66 px de mas.
    banda_p = subtitulos.banda_fija(1920, 1080, margen=p7_callouts.SUB_MARGEN,
                                    ancho_maximo=p7_callouts.SUB_ANCHO)
    pies = []
    for texto in ("una linea corta",
                  "una frase bastante mas larga que no cabe de una sola vez y "
                  "por eso se parte en dos renglones"):
        svg_caja = p7_callouts.bloque_subtitulo(
            {"texto": texto, "desde": 0.0, "hasta": 2.0}, banda_p,
            p7_callouts.SUB_TAM, p7_callouts.PARAMS_POR_DEFECTO["paleta"],
            p7_callouts.SETS_DISENO["dibujo"])
        caja = re.search(r'<rect x="(-?\d+)" y="(-?\d+)" width="(\d+)" '
                         r'height="(\d+)"', svg_caja)
        x, y, ancho_c, alto_c = (int(v) for v in caja.groups())
        pies.append(y + alto_c)
        ok(x >= 0 and y >= 0 and x + ancho_c <= 1920 and y + alto_c <= 1080,
           f"la caja cabe en el cuadro (x={x} y={y} w={ancho_c} h={alto_c})")
        ok(len(re.findall(r"<rect", svg_caja)) == 1,
           "y es UNA caja, no una por renglon: dos anchos apilados dibujan un "
           "escalon en el borde y eso es un cartel, no un subtitulo")
    igual(pies[0], pies[1],
          "la caja de una linea y la de dos acaban a la MISMA altura")

    titulo("p7_callouts: la caja se mide con la fuente que se DIBUJA")
    # El fallo: se medía con `verdana.ttf` y el navegador dibujaba con
    # `verdanab.ttf` (Verdana no tiene corte de 600, asi que sube al 700). Bold
    # es un 12,5 % mas ancha, y el texto se salia de su propia caja -- solo en
    # las lineas largas, porque en las cortas ese 12,5 % cabia en el aire.
    for texto in ("a call cancels the card.",
                  "facing fines up to four percent of annual revenue,",
                  "30 million customer accounts went up for sale that night"):
        svg_m = p7_callouts.bloque_subtitulo(
            {"texto": texto, "desde": 0.0, "hasta": 2.0}, banda_p,
            p7_callouts.SUB_TAM, p7_callouts.PARAMS_POR_DEFECTO["paleta"],
            p7_callouts.SETS_DISENO["dibujo"])
        caja = re.search(r'<rect x="(-?\d+)" y="-?\d+" width="(\d+)"', svg_m)
        x, ancho_c = int(caja.group(1)), int(caja.group(2))
        renglones = re.findall(r">([^<]+)</text>", svg_m)
        # lo que el navegador dibuja DE VERDAD, con el fichero de la negrita
        dibujado = max(tipografia.medir(l, "Verdana", p7_callouts.SUB_TAM,
                                        negrita=True)[0] for l in renglones)
        ok(dibujado <= ancho_c,
           f"el texto cabe en su caja ({dibujado} en {ancho_c}): "
           f"«{texto[:36]}»")
        ok(x >= 0 and x + ancho_c <= p7_callouts.SALIDA[0],
           "y la caja no se sale del cuadro")

    titulo("cabeceras: una cartela se escribe CUANDO SE DICE lo que pone")
    ficha_cartela = {"plantilla": "cifra", "datos": {
        "cifra": "30M", "label": "cuentas de clientes a la venta"}}
    narracion = ("treinta millones de cuentas de clientes salieron a la venta "
                 "en un foro")
    marcas = [[10.0 + i * 0.4, 10.3 + i * 0.4]
              for i in range(len(narracion.split()))]
    escena_c = {"id": "S010", "narracion": narracion, "marcas": marcas,
                "t_in": 10.0, "t_out": 16.0, "duracion": 6.0}
    dibujadas = cartelas.palabras_dibujadas(ficha_cartela, 6.0)
    igual(dibujadas, ["30M", "cuentas", "de", "clientes", "a", "la", "venta"],
          "las palabras salen del DIBUJADO, en su orden, no del diccionario")
    tiempos = cartelas.tiempos_dichos(ficha_cartela, escena_c)
    igual(len(tiempos), len(dibujadas), "un tiempo por palabra escrita")
    ok(all(b >= a for a, b in zip(tiempos, tiempos[1:])),
       f"y van hacia delante, sin parpadeos: {tiempos}")
    # 'cuentas' es la palabra 3 de la narracion: se dice en t_in+1.2
    igual(tiempos[1], 1.2, "la palabra que SI se dice entra cuando se dice")
    ok(tiempos[0] < tiempos[1],
       "y la que no se dice se coloca antes de la siguiente anclada, no al azar")
    svg_sinc = cartelas.svg_capa(ficha_cartela, duracion=6.0, tiempos=tiempos)
    ok('begin="1.20s"' in svg_sinc, "y el SVG lleva ese segundo dentro")
    igual(cartelas.alinear(dibujadas, "", [], 0.0, 6.0), [],
          "sin narracion con la que alinear no se finge sincronia: manda el "
          "ritmo de siempre")

    titulo("cabeceras: la que no da tiempo a leerse ocupa DOS planos")
    plan_e = cartelas.plan_de_escritura(ficha_cartela, escena_c)
    ok(not plan_e["dos_planos"],
       f"con 6 s le sobra tiempo para leerse ({plan_e})")
    corto = dict(escena_c, duracion=4.0, t_out=14.0)
    ok(cartelas.plan_de_escritura(ficha_cartela, corto)["dos_planos"],
       "con 4 s no, y se dice")
    marcas_tarde = [[10.0 + 3.0 + i * 0.2, 10.2 + 3.0 + i * 0.2]
                    for i in range(len(narracion.split()))]
    tarde = dict(escena_c, marcas=marcas_tarde)
    ok(cartelas.plan_de_escritura(ficha_cartela, tarde)["dos_planos"],
       "y con 6 s tambien si lo que pone se dice al final: acaba de escribirse "
       "con el corte y no queda nada que leer")

    titulo("medios: emparejar un texto escrito con lo que dice la voz")
    # LA MISMA CUENTA para los rotulos y para las cartelas. Vive en `medios` y
    # no una copia en cada sitio: con dos, la que se quedara vieja fallaria en
    # silencio (PENDIENTE 12).
    for escrito, esperado in (("30M", 30_000_000.0), ("4%", 4.0), ("165+", 165.0),
                              ("1.500", 1500.0), ("2,5M", 2_500_000.0),
                              ("$2M", 2_000_000.0), ("120k", 120_000.0),
                              ("28", 28.0), ("S001", None), ("abril", None)):
        igual(medios.valor_numerico(escrito), esperado,
              f"'{escrito}' vale {esperado}")
    for dicho, esperado in (
            ("thirty million customer accounts", (0, 2, 30_000_000.0)),
            ("a hundred and sixty five companies", (0, 5, 165.0)),
            ("fines up to four percent of revenue", (3, 2, 4.0)),
            ("treinta millones de cuentas", (0, 2, 30_000_000.0)),
            ("mil quinientos millones de euros", (0, 3, 1_500_000_000.0)),
            ("cuatro mil kilometros de mar", (0, 2, 4000.0))):
        tramos = medios.numeros_dichos(medios.normalizar_texto(dicho).split())
        igual(tramos[0] if tramos else None, esperado,
              f"«{dicho[:34]}» se lee como {esperado[2]:.0f}")
    igual(medios.numeros_dichos("one of the systems".split()), [],
          "«one of the systems» NO es la cifra 1: un articulo suelto no es un "
          "numero, y si lo fuera la mitad de un guion seria una cifra")
    igual(medios.indice_de("Thirty million customer accounts went up".split(), "30M"),
          (0, 2),
          "«30M» ancla en «thirty» y consume «million»: el ancla es un TRAMO, "
          "no una palabra, o la siguiente ancla caeria dentro de la cifra")
    igual(medios.indice_de("More than one hundred sixty-five companies".split(), "165+"),
          (2, 3), "y una cifra dicha en cinco palabras ocupa las tres marcas que son")
    ok(medios.casan("accounts", "account") and medios.casan("account", "accounts"),
       "casar es SIMETRICO: antes «account» casaba con «accounts» y no al reves")
    ok(not medios.casan("de", "desde"),
       "pero una palabra de dos letras no casa por dentro de otra")
    igual(medios.indice_de("no se dice ninguna cifra aqui".split(), "30M"), None,
          "y lo que no se dice no se ancla")

    titulo("cabeceras: una cartela ocupa el tramo en el que SE DICEN sus palabras")
    # EL CASO MEDIDO, el del video largo (PENDIENTE 12): la cartela cuelga de S002
    # y sus cinco palabras se dicen enteras en S001. Alineada solo contra su
    # plano da [] -- y ademas «le sobra tiempo», que es por que el sistema ni se
    # enteraba--; alineada contra la VENTANA sale clavada.
    s001 = {"id": "S001", "t_in": 0.0, "t_out": 3.8, "duracion": 3.8,
            "narracion": "Thirty million customer accounts went up for sale "
                         "for two million",
            "marcas": [[0.123, 0.52], [0.524, 1.08], [1.081, 1.48],
                       [1.482, 1.88], [1.881, 2.12], [2.2, 2.2], [2.28, 2.36],
                       [2.361, 2.6], [2.68, 2.68], [2.761, 3.12], [3.121, 3.52]],
            "set": "foro", "camara": "general",
            "zoom": {"tipo": "in", "de": 1.0, "a": 1.0526}}
    s002 = {"id": "S002", "t_in": 3.8, "t_out": 7.228, "duracion": 3.428,
            "narracion": "dollars, roughly the price of an apartment in Madrid.",
            "marcas": [[3.802, 4.28], [4.552, 5.08], [5.16, 5.16], [5.241, 5.56],
                       [5.56, 5.64], [5.72, 5.72], [5.801, 6.32], [6.4, 6.4],
                       [6.481, 6.92]],
            "set": "foro", "camara": "hombro",
            "zoom": {"tipo": "out", "de": 1.0526, "a": 1.0}}
    s003 = {"id": "S003", "t_in": 7.228, "t_out": 9.4, "duracion": 2.172,
            "narracion": "The seller had not touched a single",
            "marcas": [[7.536, 7.64], [7.721, 8.04], [8.048, 8.2], [8.28, 8.44],
                       [8.447, 8.84], [8.92, 8.92], [9.0, 9.08]],
            "set": "foro", "camara": "general"}
    ficha_30m = {"plantilla": "cifra", "fondo": "negro",
                 "datos": {"cifra": "30M", "label": "Customer accounts on sale",
                           "icono": "base_datos"}}
    dibujadas_30m = cartelas.palabras_dibujadas(ficha_30m, 3.428)
    igual(dibujadas_30m, ["30M", "Customer", "accounts", "on", "sale"],
          "las cinco palabras de la cartela del 30M")
    igual(cartelas.alinear(dibujadas_30m, s002["narracion"], s002["marcas"],
                           t_in=s002["t_in"], duracion=s002["duracion"]), [],
          "contra SU plano no hay nada que anclar: la cartela destila una frase "
          "que ahi ya no se dice")
    encaje = cartelas.encaje_de(ficha_30m, s002, s001, s003)
    if ok(encaje is not None, "contra la VENTANA si"):
        igual(encaje["tiempos"], [0.123, 1.081, 1.482, 1.921, 2.361],
              "y cada palabra cae donde se dice, en el reloj del video")
        ok(encaje["ini"] < s002["t_in"],
           f"que empieza ANTES de su plano ({encaje['ini']} < {s002['t_in']})")
    escrito = cartelas.escritura_de(ficha_30m, s002, encaje)
    ok(escrito["desde_antes"] and escrito["antes"] > 3.5,
       f"o sea que llega casi cuatro segundos tarde a su golpe ({escrito})")
    ok(not escrito["falta"],
       "y medido contra el reloj sintetico parecia que le sobraba tiempo: por "
       "eso hay que medir contra el ENCAJE")

    titulo("cabeceras: hacia atras, y sale del mismo enunciado que hacia delante")
    escenas_ct = [dict(s001), dict(s002), dict(s003)]
    puestas_ct = {"S002": ficha_30m}
    # SIN vaciar el plano: desde que todas las cartelas van sobre imagen, el de
    # la cartela sigue siendo una toma con su camara -- es un plano normal con
    # texto encima -- hasta que lo absorbe el tramo.
    escenas_ct[1]["cartela"] = ficha_30m
    seguidas = _fundir_ct(escenas_ct, puestas_ct, {})
    igual([f["hacia"] for f in seguidas], ["atras"],
          "la cartela se estira HACIA ATRAS: es donde se dicen sus palabras")
    igual(escenas_ct[0]["cartela"]["plantilla"], "cifra",
          "el plano anterior pasa a llevar la cartela")
    igual([e["id"] for e in escenas_ct], ["S001", "S003"],
          "el tramo se FUNDE en UNA escena: S002 desaparece dentro de S001 "
          ". No es un plano encadenado, es un plano mas largo")
    ok(escenas_ct[0].get("camara"),
       "el HOGAR sigue rodando: es el que pone la imagen del tramo entero")
    igual(escenas_ct[0]["t_out"], s002["t_out"],
          "y se lleva el t_out del ultimo del tramo")
    igual(escenas_ct[0]["duracion"],
          round(s002["t_out"] - s001["t_in"], 3),
          "asi que su clip dura el tramo ENTERO, que es lo que da tiempo a "
          "escribir la cabecera: el reloj SMIL de un clip corre de 0 a lo que "
          "dura ESE clip, y por eso antes solo se pintaba la primera palabra")
    igual(escenas_ct[0]["narracion"],
          " ".join(x for x in (s001["narracion"], s002["narracion"]) if x),
          "la narracion se concatena: es de donde salen los tiempos")
    igual(len(escenas_ct[0]["marcas"]),
          len(escenas_ct[0]["narracion"].split()),
          "y las marcas con ella, palabra a palabra -- si los dos recuentos no "
          "cuadran, `encajar` se rinde y la cartela se queda sin sincronizar")
    ok(not any(e.get("sigue_a") for e in escenas_ct),
       "y NADIE lleva `sigue_a`: no hay tramo que encadenar porque no hay tramo")
    igual(escenas_ct[0]["escritura"]["tiempos"],
          [0.22, 1.081, 1.482, 1.921, 2.361],
          "y ya sincronizada: cada palabra entra cuando la voz la dice")
    titulo("cabeceras: se estira lo que haga falta, pero SIN cruzar el bloque")
    # El limite no es un numero inventado: es el BLOQUE DEL GUION, que es lo que
    # el redactor escribio de una vez, o sea UNA idea. Una cartela que lo cruza
    # se queda puesta mientras la voz ya cuenta otra cosa.
    def _plano(sid, t_in, dur, bloque, texto=""):
        return {"id": sid, "t_in": t_in, "t_out": round(t_in + dur, 3),
                "duracion": dur, "narracion": texto or f"palabras de {sid}",
                "marcas": [], "origen": {"bloque": bloque, "indice": 0},
                "set": "sitio", "camara": "general",
                "zoom": {"tipo": "in", "de": 1.0, "a": 1.0526}}

    larga = {"plantilla": "definicion", "fondo": "imagen",
             "datos": {"termino": "Infostealer",
                       "texto": "Malware that siphons saved passwords and login "
                                "sessions off an infected computer"}}
    # Planos cortos a proposito: ni el bloque entero le llega, asi que se ve
    # DONDE se para. Con planos normales se para antes, en cuanto le cabe.
    escenas_b = [_plano("S001", 0.0, 1.5, "B001"), _plano("S002", 1.5, 1.5, "B001"),
                 _plano("S003", 3.0, 1.5, "B001"), _plano("S004", 4.5, 1.5, "B001"),
                 _plano("S005", 6.0, 4.0, "B002"), _plano("S006", 10.0, 4.0, "B002")]
    escenas_b[0]["cartela"] = larga
    seguidas_b = _fundir_ct(escenas_b, {"S001": larga}, {})
    absorbidos = [f["absorbido"] for f in seguidas_b if f["absorbido"]]
    igual(absorbidos, ["S002", "S003", "S004"],
          "se estira por SU bloque, que es lo que dura su idea")
    ok("S005" not in absorbidos,
       "y se para en el bloque siguiente aunque le siga faltando tiempo: "
       "cruzarlo seria quedarse puesta mientras se cuenta otra cosa")
    # Con planos normales del mismo bloque para en cuanto le cabe, sin comerselo
    # entero: el tramo lo marca lo que tarda en leerse, no la frontera.
    holgados = [_plano("S001", 0.0, 2.5, "B001"), _plano("S002", 2.5, 2.5, "B001"),
                _plano("S003", 5.0, 3.0, "B001"), _plano("S004", 8.0, 3.0, "B001")]
    holgados[0]["cartela"] = larga
    seg_h = _fundir_ct(holgados, {"S001": larga}, {})
    igual([f["absorbido"] for f in seg_h if f["absorbido"]],
          ["S002", "S003"],
          "para en cuanto cabe: S004 es del mismo bloque y no lo toca")
    igual([f for f in seg_h if f["hacia"] == "no_cabe"], [],
          "y entonces no hay nada que avisar")
    igual(len(holgados), 2,
          "los tres planos del tramo son ya UNO: S002 y S003 se han fundido "
          "dentro de S001 y solo queda el, mas S004")
    igual(holgados[0]["duracion"], 8.0,
          "y su clip dura el tramo entero, que es lo que da tiempo a escribir")
    ok(not any(e.get("sigue_a") for e in holgados),
       "sin `sigue_a`: no hay mitades que encadenar")
    ok(holgados[0]["cartela"]["plantilla"],
       "el hogar es el unico que lleva cartela, y la escribe entera")

    titulo("el plan dice CON QUE REGLAS se corto")
    # Las firmas miran los params, asi que cambiar el motor no pone naranja
    # nada. El sello no entra en ninguna firma --meterlo dejaria obsoletos los
    # renders de todos los proyectos a la vez-- y por eso se ENSENA. PENDIENTE 24.
    ok(p6_assets.MOTOR_PLAN >= 1, f"hay una version de motor: {p6_assets.MOTOR_PLAN}")
    for version in range(2, p6_assets.MOTOR_PLAN + 1):
        ok(p6_assets.MOTOR_CAMBIOS.get(version),
           f"la version {version} dice que cambio: un numero suelto no dice si "
           f"importa")
    ok(max(p6_assets.MOTOR_CAMBIOS) <= p6_assets.MOTOR_PLAN,
       "y no se anuncia un cambio de una version que todavia no existe")

    titulo("cabeceras: NO hay fondo solido, la toma entera va sobre la imagen")
    # Entre el 21 y el 22-08 el ultimo plano de una cabecera
    # larga saltaba a fondo solido. Se monto, se vio y se retiro: lo que se
    # notaba ahi no era el contraste, era que en ese punto se acababa el reloj
    # de la cabecera y el texto restante aparecia de golpe. El fondo solido no
    # lo causaba -- lo senalaba.
    igual([f for f in seguidas_b if f.get("remate")], [],
          "ningun plano del tramo remata en solido")
    tramo_b = [e for e in escenas_b if e.get("cartela")]
    igual([e["id"] for e in tramo_b], ["S001"],
          "el tramo de cuatro planos es ya UNA escena: S002..S004 se han "
          "fundido dentro de S001")
    for escena in tramo_b:
        igual(cartelas.fondo_de(escena["cartela"]), "imagen",
              f"{escena['id']}: sobre la imagen, como todos los demas")
        ok(not cartelas.sin_imagen(escena),
           f"{escena['id']}: y sigue siendo un plano con imagen")
    for medio in tramo_b[1:]:
        igual(medio.get("sigue_a"), "S001",
              f"{medio['id']}: la misma toma, sin transicion ni sonido de corte")
        igual(medio.get("set"), escenas_b[0].get("set"),
              f"{medio['id']}: y hereda el sitio del hogar, que es donde se rueda")
        ok("ct-velo" in cartelas.svg_capa(medio["cartela"], None, None,
                                          duracion=1.5, escrita=True),
           f"{medio['id']}: con su velo, que es lo que oscurece la imagen")

    titulo("cabeceras: una toma ES una escena, asi que no hay medias tomas")
    # ASI SE CERRO EL FALLO DEL 4 %, y de la unica forma que no puede volver.
    # Se edito el texto de la cartela del hogar, el nucleo marco sucia SU unidad
    # --que es donde vive la decision-- y la continuacion se conservo con el SVG
    # viejo: en el video se veia empezar a escribir una frase y terminar otra.
    # La firma no podia detectarlo porque una continuacion no es una decision,
    # es una consecuencia, asi que hubo que preguntarselo al PLAN
    # (`tramo_ids`, `hermanas_de`, `hogar_de`).
    #
    # Con el fundido ese andamiaje entero SOBRA: un tramo es
    # UNA escena, o sea UNA unidad, o sea UNA firma. No hay media toma que
    # conservar porque no hay mitades. Se borro, y esto es lo que lo fija.
    for nombre in ("tramo_ids", "hermanas_de", "hogar_de"):
        ok(not hasattr(cartelas, nombre),
           f"`cartelas.{nombre}` ya no existe: existia solo para mantener "
           f"sincronizadas varias mitades, y ya no hay mitades")
    fuente_p6 = io.open(os.path.join(RAIZ, "pasos", "p6_assets.py"),
                        encoding="utf-8").read()
    for ruta in ("pasos/p7_callouts.py", "pasos/p8_render.py"):
        cuerpo = io.open(os.path.join(RAIZ, *ruta.split("/")),
                         encoding="utf-8").read()
        ok("hermanas_de" not in cuerpo,
           f"{ruta} ya no expande lo pedido a la toma entera")
    ok("hermanas_de" not in fuente_p6,
       "y p6 tampoco: pedir un plano es pedir un plano")
    ok(not any(e.get("sigue_a") for e in escenas_b),
       "y en un plan recien fundido no queda ni un `sigue_a`")

    titulo("cabeceras: dos mitades con la MISMA imagen no son un plano repetido")
    # El guardian de planos repetidos busca un fallo concreto: dos prompts que
    # salieron identicos y una cache que devolvio el mismo fichero. La segunda
    # mitad de una toma copia la imagen del hogar A PROPOSITO (31.4), asi que es
    # identica porque tiene que serlo.
    #
    # Esto se cayo de verdad el 22-08 --«S013 = S014», despues de generar-- y
    # solo cuando se arreglo la copia (35.2): mientras la continuacion se
    # quedaba con su imagen VIEJA, no coincidia con su hogar y el guardian no la
    # veia. Un guardian calibrado sobre un fallo aprende a dar por bueno el fallo.
    copia = tempfile.mkdtemp(prefix="estudio_repes_")
    try:
        for sid in ("S001", "S002", "S003"):
            with open(os.path.join(copia, f"{sid}.png"), "wb") as fh:
                fh.write(b"la misma imagen" if sid != "S003" else b"otra distinta")
        fichas = {f"escena:{sid}": {"tipo": "escena", "id": sid, "png": f"{sid}.png"}
                  for sid in ("S001", "S002", "S003")}
        igual(p6_assets._planos_repetidos(fichas, copia), [["S001", "S002"]],
              "dos planos que se rodaron aparte y salieron iguales SI se cantan")
        igual(p6_assets._planos_repetidos(fichas, copia, copiados={"S002"}), [],
              "pero si el plan dice que S002 es la segunda mitad de S001, no: "
              "esa imagen es la misma porque el motor la copio")
        fichas["escena:S002"]["origen"] = "sigue"
        igual(p6_assets._planos_repetidos(fichas, copia), [],
              "y la ficha de la propia tanda tambien lo dice ('origen': sigue)")
        # Y AL RETOMAR, la ficha ya no dice 'sigue': dice 'conservado', porque
        # ese plano ya tenia su imagen. Quien lo sabe es el PLAN. Sin esto el
        # arreglo funciona de primeras y falla justo al reanudar una tanda, que
        # es cuando mas duele.
        fichas["escena:S001"]["origen"] = "conservado"
        fichas["escena:S002"]["origen"] = "conservado"
        igual(p6_assets._planos_repetidos(fichas, copia), [["S001", "S002"]],
              "con la ficha ya conservada, por si sola vuelve a cantarlos")
        igual(p6_assets._planos_repetidos(fichas, copia,
                                          copiados={"S001", "S002"}), [],
              "pero el PLAN dice que se copian a proposito, y eso manda")
    finally:
        shutil.rmtree(copia, ignore_errors=True)

    titulo("cabeceras: hacia atras se lleva la cartela a la imagen QUE TOCA")
    # Con todas sobre imagen (21-08, noche) hacia atras vuelve a estar permitido,
    # y es lo correcto: el tramo entero ensena UNA imagen --la del hogar-- y la
    # cartela se decide leyendo el guion, antes de que exista ninguna imagen. Si
    # sus palabras se dicen en el plano de antes, la imagen de ese plano es
    # justamente la que ilustra lo que la cartela remata.
    detras = [_plano("S001", 0.0, 4.0, "B001", "thirty million customer accounts"),
              _plano("S002", 4.0, 4.0, "B001", "went up for sale")]
    detras[0]["marcas"] = [[0.2 + i * 0.5, 0.6 + i * 0.5] for i in range(4)]
    detras[1]["marcas"] = [[4.2 + i * 0.5, 4.6 + i * 0.5] for i in range(4)]
    sobre = {"plantilla": "cifra", "fondo": "imagen",
             "datos": {"cifra": "30M", "label": "customer accounts"}}
    detras[1]["cartela"] = sobre
    seg_sobre = _fundir_ct(detras, {"S002": sobre}, {})
    igual([f["hacia"] for f in seg_sobre if f["absorbido"]], ["atras"],
          "absorbe el plano de antes, que es donde se dicen sus palabras")
    igual((detras[0].get("cartela") or {}).get("plantilla"), "cifra",
          "el plano anterior pasa a llevarla, y es el que rueda")
    igual(len(detras), 1,
          "y el de origen desaparece dentro de el: son UN plano, no dos")
    igual(detras[0]["duracion"], 8.0,
          "que dura los dos, con UNA sola imagen y un solo reloj")
    igual([f["era_toma"] for f in seg_sobre if f["absorbido"]], [True],
          "y el que se absorbe SI era una toma, asi que se descuenta del informe")

    titulo("cabeceras: la que se dice ENTERA en el plano siguiente SE MUDA")
    # Era el limite conocido de PENDIENTE 13: la cartela se EXTENDIA sobre los
    # dos planos --el tramo quedaba cubierto-- pero se escribia comprimida
    # contra el final del primero, porque la continuacion se dibuja ya escrita.
    # Con TODAS_SOBRE_IMAGEN el argumento que lo frenaba se cayo: mudarla ya no
    # cambia que plano paga imagen.
    delante = [_plano("S001", 0.0, 4.0, "B001", "y ahora viene lo importante"),
               _plano("S002", 4.0, 4.0, "B001",
                      "thirty million customer accounts went up for sale")]
    delante[0]["marcas"] = [[0.2 + i * 0.6, 0.7 + i * 0.6] for i in range(6)]
    delante[1]["marcas"] = [[4.2 + i * 0.4, 4.5 + i * 0.4] for i in range(8)]
    tarde = {"plantilla": "cifra", "fondo": "imagen",
             "datos": {"cifra": "30M", "label": "customer accounts"}}
    delante[0]["cartela"] = tarde          # puesta en S001, dicha en S002
    seg_mudanza = _fundir_ct(delante, {"S001": tarde}, {})
    igual((delante[1].get("cartela") or {}).get("plantilla"), "cifra",
          "la cartela se muda al plano donde EMPIEZAN sus palabras")
    igual((delante[0].get("cartela") or {}).get("plantilla"), None,
          "y el plano donde estaba deja de llevarla")
    igual(len(delante), 2,
          "y los dos planos siguen siendo dos: mudarse no es fundirse")
    igual(delante[0].get("sigue_a"), None,
          "el de origen vuelve a ser un plano normal, no una mitad de nadie")
    ok((delante[1].get("escritura") or {}).get("tiempos"),
       "y se escribe con sus tiempos, no comprimida contra el final del anterior")
    igual([f["hacia"] for f in seg_mudanza if f.get("absorbido")], [],
          "no absorbe a nadie: se ha mudado, no se ha estirado")

    titulo("cabeceras: lo que sigue sin caber YA NO SE DICE")
    # PENDIENTE 33. El aviso «AUN le faltan N s para poder leerse» se retiro el
    # 23-08 y conviene tener claro QUE media, porque no era lo que parecia: no
    # decia que la cartela fuera desincronizada --eso esta arreglado y medido
    # sobre el plan de verdad-- sino que queda poca COLA DE LECTURA. Es confort,
    # no un fallo de montaje, y sobre todo no es accionable: cuando saltaba, el
    # tramo ya se habia estirado todo lo que podia.
    corto = [_plano("S001", 0.0, 2.0, "B001"), _plano("S002", 2.0, 2.0, "B002")]
    apretada = {"plantilla": "tesis", "fondo": "negro",
                "datos": {"texto": "una frase demasiado larga para dos segundos "
                                   "de plano y por eso no cabe"}}
    corto[0]["cartela"] = apretada
    seg_corto = _fundir_ct(corto, {"S001": apretada}, {})
    igual([f for f in seg_corto if not f.get("absorbido")], [],
          "una cartela que no cabe ni estirando ya no emite ficha de aviso: "
          "las unicas fichas que quedan describen planos ABSORBIDOS de verdad")
    # Y la CUENTA no se va con el aviso: la sigue usando `tramo_de` para decidir
    # hasta donde estirar, que es lo que hace que la cola quepa cuando cabe.
    ok(cartelas.cola_de_lectura(apretada) > 0,
       "cola_de_lectura sigue en pie: se fue el aviso, no la cuenta")
    ok(cartelas.tiempo_necesario(apretada, 2.0) > 2.0,
       "y tiempo_necesario tambien, que es de donde sale el estiron")

    titulo("cabeceras: el tope esta en PLANOS, no en segundos")
    # Cambiado el 22-08. Lo que se decide aqui es de montaje
    # --cuantos cortes se sacrifican para que el texto quepa-- y en segundos el
    # mismo texto pasaba o no segun lo que durase la frase de al lado: el tramo
    # de los tres bullets del video largo se paro contra los 8,0 s con la ultima
    # linea sin escribir, y esa linea se dice en el segundo 83,5.
    ok(cartelas.PLANOS_MAXIMOS >= cartelas.PLANOS_QUE_TIENDE,
       f"a lo que tiende ({cartelas.PLANOS_QUE_TIENDE}) cabe dentro del tope "
       f"({cartelas.PLANOS_MAXIMOS})")
    muchos = [_plano(f"S{n:03d}", n * 2.0, 2.0, "B001") for n in range(1, 9)]
    muchos[0]["cartela"] = apretada
    _fundir_ct(muchos, {"S001": apretada}, {})
    ok(len(muchos) >= 8 - cartelas.PLANOS_MAXIMOS,
       f"una cartela que no cabe nunca no se come el video entero: quedan "
       f"{len(muchos)} planos de 8, con el tope en {cartelas.PLANOS_MAXIMOS}")
    # el presupuesto de palabras sigue colgando del ritmo del video
    igual(cartelas.techo_de({"max_s": 4}), 8.0,
          "el presupuesto de palabras sigue en segundos: es lo que se le pide "
          "al agente, no lo que frena el fundido")
    ok(cartelas.palabras_maximas({"max_s": 4})
       < cartelas.palabras_maximas({"max_s": 10}),
       "y el presupuesto de palabras cuelga del techo, no al reves")

    corto_p = {"min_s": 1, "max_s": 4}
    largos = [_plano(f"S{i:03d}", (i - 1) * 3.0, 3.0, "B001") for i in range(1, 7)]
    largos[0]["cartela"] = larga
    seg_l = _fundir_ct(largos, {"S001": larga}, corto_p)
    comidos = [f["absorbido"] for f in seg_l if f["absorbido"]]
    ok(len(comidos) + 1 <= cartelas.PLANOS_MAXIMOS,
       f"con seis planos del MISMO bloque para en el tope de "
       f"{cartelas.PLANOS_MAXIMOS}, no se los come todos: {comidos}")
    igual(largos[0]["duracion"],
          round(3.0 * (len(comidos) + 1), 3),
          "y el plano fundido dura exactamente lo que ocupaba el tramo")
    igual(len(largos), 6 - len(comidos),
          "los absorbidos ya no estan en la lista: se han fundido, no marcado")

    titulo("cabeceras: el presupuesto de palabras se AVISA, no se recorta")
    # Recortar una frase por la mitad es peor que dejarla larga: se dice con el
    # numero delante y se arregla donde se escribe.
    ok(cartelas.palabras_maximas(corto_p)
       == cartelas.palabras_que_caben(cartelas.techo_de(corto_p)),
       "el limite de palabras sale de la MISMA cuenta que decide si cabe")
    datos_l, avisos_l = cartelas.validar("definicion", larga["datos"], corto_p)
    ok(any("palabras" in a for a in avisos_l),
       f"una cartela que no se puede leer en 8 s se dice: {avisos_l}")

    # LO UNICO QUE FUERZA: soltar los campos OPCIONALES hasta que quepa. Es una
    # perdida limpia --el lector no se entera de que faltaba la nota-- frente a
    # recortar una frase por la mitad, que deja la cartela rota.
    con_nota = {"cifra": "30M", "label": "Customer accounts up for sale",
                "nota": "Price: two million dollars, the whole database",
                "icono": "base_datos"}
    salida_n, avisos_n = cartelas.validar("cifra", con_nota, corto_p)
    ok(not salida_n.get("nota"),
       "se suelta la nota al pie, que es opcional (un campo vacio no viaja)")
    igual(salida_n["label"], con_nota["label"],
          "y NO se toca lo obligatorio: una frase cortada es peor que una larga")
    ok(any("se quita" in a for a in avisos_n), f"y se dice: {avisos_n}")
    ok(cartelas._cuentapalabras(salida_n) <= cartelas.palabras_maximas(corto_p),
       "con eso ya cabe")
    igual([a for a in avisos_n if "acortala a mano" in a], [],
          "y entonces no hace falta que nadie la reescriba")
    # cuando lo que sobra es lo OBLIGATORIO, el motor se para y lo dice
    ok(any("acortala a mano" in a for a in avisos_l),
       "y si lo que sobra es el texto obligatorio, se pide a mano en vez de "
       "recortarlo o de volver a llamar al agente en bucle")
    igual(datos_l["texto"], larga["datos"]["texto"], "sin tocar una letra")

    titulo("cabeceras: el icono NO es una palabra")
    # Contaba el nombre del glifo ('llave') como texto, asi que toda cartela con
    # icono pedia mas tiempo del que necesita. Lo delato comparar esta cuenta con
    # `palabras_dibujadas`, que sale de dibujar de verdad.
    con_icono = {"termino": "Infostealer", "texto": "Malware que roba claves",
                 "icono": "llave"}
    ficha_i = {"plantilla": "definicion", "datos": con_icono}
    igual(cartelas._cuentapalabras(con_icono),
          len(cartelas.palabras_dibujadas(ficha_i, 4.0)),
          "la cuenta de palabras y las que se dibujan dicen lo mismo")
    sin_icono = {k: v for k, v in con_icono.items() if k != "icono"}
    igual(cartelas._cuentapalabras(con_icono), cartelas._cuentapalabras(sin_icono),
          "poner un icono no le quita tiempo de lectura a la cartela")
    _, con_holgura = cartelas.validar("definicion", larga["datos"], {"max_s": 10})
    igual([a for a in con_holgura if "palabras" in a], [],
          "y la MISMA cartela en un video de planos largos no molesta: el "
          "presupuesto es del video, no del texto")
    igual(datos_l["texto"], larga["datos"]["texto"],
          "pero NO se recorta la frase: una frase cortada es peor que una larga")
    _, sin_aviso = cartelas.validar("tesis", {"texto": "El candado estaba abierto"})
    igual([a for a in sin_aviso if "palabras" in a], [],
          "y una corta no molesta")

    titulo("cabeceras: la camara recorre la toma fundida de punta a punta")
    # Cuando un tramo eran varias mitades habia que REPARTIR el recorrido entre
    # ellas (`_partir_zoom`), y repartiendo de dos en dos cada mitad recibia el
    # recorrido entero otra vez: la camara iba y venia en cada corte. Con el
    # fundido no hay nada que repartir -- la escena es una y se lleva su
    # recorrido entero -- y esa funcion sobra.
    p6_assets._realternar_zoom(escenas_b)
    zoom_b = escenas_b[0]["zoom"]
    ok(zoom_b, "la escena fundida lleva su recorrido")
    ok(abs(zoom_b["a"] - zoom_b["de"]) > 0.001,
       f"y avanza de verdad a lo largo de toda la toma: {zoom_b}")
    antes_z = dict(zoom_b)
    p6_assets._realternar_zoom(escenas_b)
    igual(escenas_b[0]["zoom"], antes_z,
          "y correrlo dos veces no lo encoge: es idempotente")

    titulo("cabeceras: se retira el aviso de «se come medio bloque»")
    # Ese aviso describia como problema justo lo que ahora se busca: una cabecera
    # que ocupa tres planos ES un plano largo con la cabecera encima
    # . Y era ademas un aviso que nadie podia accionar, porque
    # el limite lo aplica el propio fundido (`cartelas.PLANOS_MAXIMOS`): se le
    # pedia a una persona que vigilara una regla que no puede romperse.
    igual([f for f in seguidas_b if f["hacia"] == "muy_larga"], [],
          "una cabecera larga ya no genera aviso: es lo que se quiere")
    breve = {"plantilla": "tesis", "fondo": "imagen",
             "datos": {"texto": "El candado estaba abierto"}}
    dos = [_plano("S001", 0.0, 2.0, "B001"), _plano("S002", 2.0, 3.0, "B001"),
           _plano("S003", 5.0, 3.0, "B001")]
    dos[0]["cartela"] = breve
    seg_dos = _fundir_ct(dos, {"S001": breve}, {})
    igual([f for f in seg_dos if f["hacia"] == "muy_larga"], [],
          "una cartela corta que cabe en dos planos no genera ningun aviso")

    titulo("cabeceras: cuantas palabras caben en un hueco")
    # Es `tiempo_necesario` al reves, y es lo que se le pone delante al agente
    # plano a plano: una regla general no evito una definicion de trece palabras
    # en un plano de 2,5 s.
    ok(cartelas.palabras_que_caben(2.5) < cartelas.palabras_que_caben(6.0),
       "en un plano mas largo caben mas palabras")
    igual(cartelas.palabras_que_caben(2.5), 3, "en 2,5 s caben tres")
    for duracion in (2.0, 3.0, 4.5, 6.0, 9.0):
        cuantas = cartelas.palabras_que_caben(duracion)
        ficha_n = {"plantilla": "tesis", "datos": {"texto": " ".join(["x"] * cuantas)}}
        ok(cartelas.tiempo_necesario(ficha_n, duracion) <= duracion + 0.01,
           f"y lo que dice que cabe en {duracion}s cabe de verdad ({cuantas})")
    legible = cartelas._planos_legibles([{"id": "S001", "duracion": 2.5,
                                          "narracion": "lo que sea"}])
    ok("caben 3 palabras" in legible,
       f"y el agente lo ve escrito en SU plano: {legible.splitlines()[0]}")

    titulo("cabeceras: un AVISO no descuenta ninguna camara")
    # La misma lista trae las que absorben un plano y las de AVISO --la que no
    # cabe, la que se come medio bloque--, que no absorben nada. Colandose en el
    titulo("cabeceras: el reparto cuenta PLANOS, no cartelas")
    escenas_r = [{"id": f"S{i:03d}"} for i in range(1, 21)]
    plan_r = {"S002": {"plantilla": "tesis", "datos": {"texto": "una"}},
              "S009": {"plantilla": "tesis", "datos": {"texto": "otra"}},
              "S014": {"plantilla": "tesis", "datos": {"texto": "y otra"}},
              "S019": {"plantilla": "tesis", "datos": {"texto": "la ultima"}}}
    puestas_r, _ = cartelas.repartir(escenas_r, plan_r)
    igual(sorted(puestas_r), ["S002", "S009", "S014", "S019"],
          "cuatro sueltas caben en veinte planos")
    # las dos primeras ocupan dos planos cada una: 2+2+1 ya son cinco, y el
    # techo de veinte planos son cuatro
    puestas_r, avisos_r = cartelas.repartir(
        escenas_r, plan_r, ocupacion={"S002": (1, 2), "S009": (8, 9)})
    igual(sorted(puestas_r), ["S002", "S009"],
          "con dos que ocupan dos planos, el techo se llena antes")
    ok(any("techo" in a for a in avisos_r), f"y se dice por que: {avisos_r}")
    puestas_r, avisos_r = cartelas.repartir(
        escenas_r, {"S002": plan_r["S002"], "S007": plan_r["S009"]},
        ocupacion={"S002": (1, 3)})
    igual(sorted(puestas_r), ["S002"],
          "y el suelo de separacion se mide desde el ULTIMO plano que ocupa")

    titulo("cabeceras: se retira el estirado por ROTULO, no el de cartela")
    # `_estirar_cabeceras` hacia durar el DOBLE a un plano corto cuando su
    # cabecera de sitio no daba tiempo a leerse. Se fue con los rotulos
    # : no hay cabecera de sitio que leer. Lo que sigue
    # ocupando varios planos es la CARTELA, y eso ahora funde en vez de
    # encadenar (`_fundir_cartelas`), que es lo que se prueba mas arriba.
    for nombre in ("_estirar_cabeceras", "_anclaje_de", "_cuando_entra",
                   "_seguir_plano", "_partir_zoom"):
        ok(not hasattr(p6_assets, nombre),
           f"`p6_assets.{nombre}` ya no existe")
    # Y con el 3D se fue el descuento de encuadres: sin camaras compartidas, una
    # cartela que funde tres planos no libera ningun punto de vista.
    for nombre in ("_descontar_estirados", "_asignar_camaras", "_elegir_camara",
                   "_espacio_de", "_geo_de", "demanda_de_camaras"):
        ok(not hasattr(p6_assets, nombre),
           f"`p6_assets.{nombre}` se fue con la geometria 3D")

    titulo("cabeceras: el plano continuado no encadena con el anterior")
    reparto_sigue = transiciones.resolver(
        [{"id": "S001", "duracion": 3.2, "transicion": "suave"},
         {"id": "S002", "duracion": 4.0, "transicion": "acento",
          "sigue_a": "S001"},
         {"id": "S003", "duracion": 4.0, "transicion": "suave"}], {})
    igual(reparto_sigue["S002"]["tipo"], "corte",
          "los dos fotogramas son la misma imagen: encadenar ahi es render para "
          "no ver nada")
    ok(reparto_sigue["S003"]["tipo"] != "corte",
       "y el siguiente vuelve a encadenar con normalidad")

    titulo("p7_callouts: ya no hay rotulos que elegir")
    # `elementos_de` y `rotulos_de` leian el plan de rotulos de la unidad y
    # decidian cual pintaba p7. Con los rotulos retirados lo
    # que va encima del plano es la narracion, que no se elige: ya esta escrita.
    for nombre in ("elementos_de", "rotulos_de", "arquetipo_de", "vigentes",
                   "colocar", "mascara_sujeto", "_caja_inferior", "_linea_guia"):
        ok(not hasattr(p7_callouts, nombre),
           f"`p7_callouts.{nombre}` ya no existe: era maquinaria de colocar "
           f"rotulos, y no hay rotulos")


# ------------------------------------------------------------- 3 bis. coste

def prueba_coste():
    titulo("coste.coste_openai: manda el recuento de tokens")
    usage = {"input_tokens": 1000, "output_tokens": 500,
             "input_tokens_details": {"text_tokens": 400, "image_tokens": 600}}
    usd, via = coste.coste_openai(usage, "1536x1024", "low")
    precios = coste.tarifa_tokens()
    esperado = (400 * precios["entrada_texto"] + 600 * precios["entrada_imagen"]
                + 500 * precios["salida"])
    igual(via["via"], "tokens", "con tokens se cobra por tokens")
    ok(abs(usd - round(esperado, 6)) < 1e-9,
       f"y la cuenta es entrada de texto + entrada de imagen + salida ({usd} $)")
    igual((via["entrada_texto"], via["entrada_imagen"], via["salida"]),
          (400, 600, 500), "y se dice de donde sale cada trozo")

    solo_imagen = coste.tarifa_imagen("1536x1024", "low")
    ok(usd != solo_imagen,
       "el importe NO es el precio por imagen: era la decima parte del gasto")

    titulo("coste.coste_openai: sin tokens, el precio por imagen de respaldo")
    usd2, via2 = coste.coste_openai({}, "1536x1024", "low")
    igual(via2["via"], "imagen", "sin 'usage' se tarifa la imagen")
    ok(abs(usd2 - solo_imagen) < 1e-9, f"al precio de su calidad ({usd2} $)")
    usd3, _ = coste.coste_openai({}, "1536x1024", "low", imagenes=3)
    ok(abs(usd3 - solo_imagen * 3) < 1e-9, "y por tres imagenes, el triple")

    titulo("coste.coste_openai: nunca se suman las dos vias")
    ok(usd < solo_imagen + esperado,
       "la imagen devuelta ES los tokens de salida: sumar las dos la cobraria dos veces")

    titulo("coste.coste_openai: un desglose incoherente se tarifa por arriba")
    raro = {"input_tokens": 100, "output_tokens": 10,
            "input_tokens_details": {"text_tokens": 90, "image_tokens": 90}}
    _, via4 = coste.coste_openai(raro, "1536x1024", "low")
    igual((via4["entrada_texto"], via4["entrada_imagen"]), (0, 100),
          "si el desglose no cuadra, todo va a la tarifa mas cara")
    igual(via4["sin_desglosar"], 100, "y se dice que no venia desglosado")


# ---------------------------------------------------------- 4. segmentar

def _palabras(frase, desde=0.0, paso=0.4):
    palabras = []
    t = desde
    for w in frase.split():
        palabras.append({"w": w, "s": round(t, 3), "e": round(t + paso, 3)})
        t += paso
    return palabras


def prueba_segmentar():
    titulo("segmentar: no deja huerfana la primera palabra de una frase")
    segmentar = medios.motor("guion/segmentar.py")
    # El caso real: el corte caia tras "Music," y la palabra que ANUNCIA la
    # fiesta se quedaba pegada al plano anterior.
    frase = ("reservado para la elite del pais. Musica, baile, copas en alto, "
             "y una piscina llena de gente que no deberia estar ahi esta noche.")
    palabras = _palabras(frase)
    segmentos = segmentar.segmentar(palabras, 3.0, 6.0)
    ok(len(segmentos) >= 2, f"la frase se parte en {len(segmentos)} planos")
    cortes = [s[2][-1]["w"] for s in segmentos[:-1]]
    tipos = [segmentar.tipo_de_corte(w) for w in cortes]
    ok(all(t != "ninguno" for t in tipos),
       f"todos los cortes caen en puntuacion, ninguno a media palabra: "
       f"{list(zip(cortes, tipos))}")

    huerfanas = 0
    for anterior in segmentos[:-1]:
        textos = [p["w"] for p in anterior[2]]
        for i, w in enumerate(textos):
            if w.rstrip('"\'').endswith(".") and len(textos) - i - 1 in (1, 2):
                huerfanas += 1
    igual(huerfanas, 0,
          "ningun segmento acaba con una o dos palabras sueltas detras de un punto")

    titulo("segmentar: las duraciones caen dentro de la horquilla")
    largos = [round(fin - ini, 2) for ini, fin, _ in segmentos]
    ok(all(l <= 6.0 * 1.35 for l in largos), f"ninguno se dispara: {largos}")
    igual(segmentar.segmentar([], 3.0, 6.0), [], "sin palabras no hay planos")


# --------------------------------------------- 4bis. una frase, un plano

def _frases(frases, hueco=0.5, arranque=0.0):
    """Marcas de palabra sinteticas con la DURACION que se pide por frase.

    [(texto, segundos)] -> [{"w","s","e"}]. La duracion se reparte entre las
    palabras de la frase y entre frase y frase se deja un silencio, que es lo que
    hace la voz de verdad. Hace falta poder pedir la duracion exacta: los casos
    que importan aqui se juegan en decimas -- una frase de 2.1 s se sostiene sola
    y una de 1.9 no -- y con marcas de paso fijo no se pueden escribir.
    """
    palabras, t = [], arranque
    for texto, segundos in frases:
        trozos = texto.split()
        paso = segundos / max(1, len(trozos))
        for w in trozos:
            palabras.append({"w": w, "s": round(t, 3), "e": round(t + paso, 3)})
            t += paso
        t += hueco
    return palabras


def _textos(segmentos):
    return [" ".join(p["w"] for p in seg[2]) for seg in segmentos]


def prueba_una_frase_un_plano():
    """Que un plano no se trague una frase que podia haber sido un plano.

    El caso que lo pario: "The seller had not touched a single one of the bank's
    own systems. Spain, May of twenty twenty-four." salio en UN plano. Partirlo
    costaba 0.4452 mas que dejarlo junto, y ese 0.4452 era lo que pagaba el trozo
    SANO por no durar exactamente el ideal: el optimizador tenia un sesgo
    estructural a no partir, porque anadir un segmento solo puede sumar terminos.
    """
    segmentar = medios.motor("guion/segmentar.py")

    titulo("segmentar: la estampa corta abre su propio plano")
    palabras = _frases([
        ("The seller had not touched a single one of the bank's own systems.", 3.23),
        ("Spain, May of twenty twenty-four.", 2.31),
    ], hueco=1.15)
    textos = _textos(segmentar.segmentar(palabras, 3.0, 6.0))
    igual(len(textos), 2, f"dos frases, dos planos: {textos}")
    ok(textos and textos[-1].startswith("Spain"),
       f"y la estampa va sola en el suyo: {textos}")

    titulo("segmentar: no se rompe un plano bueno para fabricar dos malos")
    # Dos frases cortas seguidas EN MEDIO del video: partirlas deja las dos por
    # debajo del minimo y juntas caen en el centro de la horquilla, asi que se
    # quedan juntas. (Al final del video no seria el mismo caso: el ultimo plano
    # se queda en pantalla un poco mas, y con eso la segunda mitad ya se sostiene.)
    palabras = _frases([("Card fraud gets caught fast.", 2.20),
                        ("A call cancels the card.", 2.50),
                        ("Y el video sigue un rato mas por aqui.", 4.00)],
                       hueco=0.30)
    textos = _textos(segmentar.segmentar(palabras, 3.0, 6.0))
    ok(textos and textos[0].startswith("Card fraud")
       and "A call cancels the card." in textos[0],
       f"las dos frases cortas siguen siendo un plano: {textos}")

    titulo("segmentar: la horquilla que se pide manda, pero se dice lo que cuesta")
    # La misma narracion con tres horquillas. Con 2/4 y 3/6 la estampa abre
    # plano; con 4/8 no cabe -- se han pedido planos de cuatro segundos y la
    # estampa dura dos y pico-- y entonces lo que no puede pasar es que se
    # trague la frase EN SILENCIO: el informe la cuenta y la nombra.
    palabras = _frases([
        ("The seller had not touched a single one of the bank's own systems.", 3.23),
        ("Spain, May of twenty twenty-four.", 2.31),
    ], hueco=1.15)
    for minimo, maximo in ((2.0, 4.0), (3.0, 6.0)):
        textos = _textos(segmentar.segmentar(palabras, minimo, maximo))
        igual(len(textos), 2, f"con horquilla {minimo}/{maximo} la estampa va sola")
    segmentos = segmentar.segmentar(palabras, 4.0, 8.0)
    igual(len(segmentos), 1, "con 4/8 no cabe partirla: los dos trozos se "
                             "quedarian por debajo de lo pedido")
    escenas = segmentar.construir_escenas(segmentos)
    igual(segmentar.informe(escenas, 4.0, 8.0)["planos_con_varias_frases"], 1,
          "pero el informe lo canta en vez de dejarlo pasar")

    titulo("segmentar: el MAXIMO es un tope, no un precio")
    # Esto era lo contrario y por eso hubo que cambiarlo: min/max solo entraban
    # como penalizacion cuadratica, asi que pasarse tenia precio y no estaba
    # prohibido. Con el mando en 1-4 s salian planos de 4,875 s. Quien escribe
    # "maximo 4" esta poniendo un limite, no expresando una preferencia.
    largas = _frases([("Treinta millones de cuentas de clientes salieron a la "
                       "venta por dos millones de dolares, mas o menos lo que "
                       "cuesta un piso en Madrid.", 7.00),
                      ("Y el vendedor no toco ni uno solo de los sistemas del "
                       "banco.", 4.50),
                      ("Espana, mayo de dos mil veinticuatro.", 2.40)],
                     hueco=0.60)
    for minimo, maximo in ((1.0, 4.0), (2.0, 3.0), (3.0, 6.0)):
        segmentos = segmentar.segmentar(largas, minimo, maximo)
        escenas = segmentar.construir_escenas(segmentos)
        inf = segmentar.informe(escenas, minimo, maximo)
        pasados = [e["duracion"] for e in escenas if e["duracion"] > maximo + 0.05]
        ok(not pasados or not inf["maximo_respetado"],
           f"con {minimo}-{maximo}s ningun plano se pasa del maximo "
           f"(largos: {pasados}, max real {inf['duracion_max']}s)")

    titulo("segmentar: el corte y _encadenar miden LO MISMO")
    # El docstring de entradas_de dice «tiene que decir lo MISMO que _encadenar
    # del paso de assets... hay una prueba que lo comprueba», y no la habia. Sin
    # ella, las dos aritmeticas se separaron: el optimizador aceptaba un plano de
    # 3,935 s con el maximo en 4 y en pantalla salia de 4,183, o sea que el tope
    # se pasaba DESPUES de haberse declarado respetado. Solo lo pilla un caso con
    # alguna frontera de hueco menor que el adelanto (0,25 s).
    pegadas = _frases([("Treinta millones de cuentas salieron a la venta.", 3.10),
                       ("Nadie toco los sistemas del banco.", 2.60),
                       ("Espana, mayo de dos mil veinticuatro.", 2.30),
                       ("Ni fuerza bruta ni cortafuegos rotos.", 2.50)],
                      hueco=0.05)          # hueco < adelanto: es lo que discrimina
    for minimo, maximo in ((2.0, 4.0), (3.0, 6.0)):
        segmentos = segmentar.segmentar(pegadas, minimo, maximo)
        escenas = p6_assets._encadenar([dict(e) for e in
                                        segmentar.construir_escenas(segmentos)],
                                       None, 0.25, 0.45, segmentar)
        entradas = segmentar.entradas_de(pegadas, 0.25, 0.45)
        # los limites de cada segmento, en indices de palabra
        indices, corrido = [], 0
        for _, _, trozo in segmentos:
            indices.append((corrido, corrido + len(trozo)))
            corrido += len(trozo)
        desajustes = []
        for escena, (ini, fin) in list(zip(escenas, indices))[:-1]:
            optimizador = entradas[fin] - entradas[ini]
            if abs(escena["duracion"] - optimizador) > 0.002:
                desajustes.append((escena["id"], round(escena["duracion"], 3),
                                   round(optimizador, 3)))
        igual(desajustes, [],
              f"con {minimo}-{maximo}s la duracion que puntua el optimizador es "
              f"la que queda en pantalla")

    titulo("segmentar: el minimo cede antes que partir una frase, y se DICE")
    # No siempre existe un reparto que caiga entero en la horquilla cuadrando
    # ademas con las frases: basta una frase corta entre dos largas. Ahi hay que
    # elegir entre un plano medio segundo corto y un corte a mitad de sintagma,
    # y lo segundo se ve muchisimo peor. Lo que no se puede es callarlo.
    apretadas = _frases([("Una frase que dura lo suyo y llena bien el plano.", 5.20),
                         ("Corta.", 1.20),
                         ("Y otra que vuelve a durar lo suyo del todo.", 5.10)],
                        hueco=0.40)
    segmentos = segmentar.segmentar(apretadas, 5.0, 6.0)
    escenas = segmentar.construir_escenas(segmentos)
    inf = segmentar.informe(escenas, 5.0, 6.0)
    cortados = [t for t in _textos(segmentos)
                if segmentar.tipo_de_corte(t.split()[-1]) == "ninguno"]
    igual(cortados, [], "no se parte ninguna frase por la mitad para cuadrar")
    ok(inf["maximo_respetado"], "el maximo se sigue respetando")
    ok(not inf["minimo_respetado"] or inf["fuera_de_rango"] == 0,
       f"y si algun plano se queda corto, el informe lo declara "
       f"(fuera {inf['fuera_de_rango']}, minimo_respetado "
       f"{inf['minimo_respetado']})")

    titulo("segmentar: el resultado no cambia si la voz va mas rapida o mas lenta")
    # La decision se toma sobre lo que se VE, asi que escalar las marcas no puede
    # mover las fronteras de frase. Antes se tomaba sobre el habla, y un 9,5% de
    # velocidad de mas cruzaba el umbral y devolvia otro reparto.
    base = _frases([
        ("Thirty million customer accounts went up for sale for two million dollars.", 4.10),
        ("The seller had not touched the bank's own systems.", 3.20),
        ("Spain, May of twenty twenty-four.", 2.31),
        ("No brute force, no broken firewall.", 2.60),
    ], hueco=0.90)
    fronteras = {}
    for factor in (0.90, 1.0, 1.10):
        escaladas = [{"w": p["w"], "s": round(p["s"] * factor, 3),
                      "e": round(p["e"] * factor, 3)} for p in base]
        fronteras[factor] = _textos(segmentar.segmentar(escaladas, 3.0, 6.0))
    igual(fronteras[0.90], fronteras[1.0], "x0.90 da el mismo reparto")
    igual(fronteras[1.10], fronteras[1.0], "x1.10 da el mismo reparto")
    igual(len(fronteras[1.0]), 4, f"y son cuatro frases, cuatro planos: {fronteras[1.0]}")

    titulo("segmentar: ningun plano cierra a mitad de frase teniendo un punto dentro")
    palabras = _frases([
        ("reservado para la elite del pais.", 3.10),
        ("Musica, baile, copas en alto, y una piscina llena de gente.", 5.20),
    ], hueco=0.60)
    segmentos = segmentar.segmentar(palabras, 3.0, 6.0)
    colgando = sum(1 for texto in _textos(segmentos)
                   for w in texto.split()[:-1]
                   if segmentar.tipo_de_corte(w) == "fuerte")
    igual(colgando, 0, "ningun segmento se cierra dejando colgado el arranque "
                       "de la frase siguiente")

    titulo("segmentar: un plano no cruza una frontera de bloque del guion")
    # Dos bloques del guion, y la ultima frase del primero es corta: sin muro se
    # juntaria con la primera del segundo, y ese plano narraria dos bloques.
    bloque1 = [("El banco confirma el acceso no autorizado a los datos.", 3.40),
               ("Nadie toco sus sistemas.", 2.20)]
    bloque2 = [("Meses antes, un infostealer llego al portatil de un empleado.", 4.10),
               ("Sin doble factor, la contrasena era toda la cerradura.", 3.80)]
    palabras = _frases(bloque1 + bloque2, hueco=0.50)
    muro = sum(len(texto.split()) for texto, _ in bloque1)
    segmentos = segmentar.segmentar(palabras, 3.0, 6.0, muros=[muro])
    cruces = [t for t in _textos(segmentos)
              if "sistemas." in t and "Meses" in t]
    igual(cruces, [], "ningun plano narra el final de un bloque y el principio "
                      "del siguiente")

    titulo("segmentar: un bloque mas corto que el suelo no fuerza un plano imposible")
    palabras = _frases([("Un pais entero mirando.", 3.20), ("Ya.", 0.40),
                        ("Y entonces todo se detuvo del todo.", 3.10)], hueco=0.30)
    segmentos = segmentar.segmentar(palabras, 3.0, 6.0, muros=[5, 6])
    cortos = [round(f - i, 2) for i, f, _ in segmentos if f - i < segmentar.SUELO_S]
    igual(cortos, [], f"ninguno queda por debajo del suelo: "
                      f"{[round(f - i, 2) for i, f, _ in segmentos]}")

    titulo("segmentar: se puntua lo que se ve, no lo que se habla")
    palabras = _frases([("Una frase.", 2.0), ("Otra distinta.", 2.0)],
                       hueco=2.0, arranque=1.0)
    entradas = segmentar.entradas_de(palabras, 0.25, 0.45)
    igual(len(entradas), len(palabras) + 1,
          "hay una entrada por palabra mas el final del ultimo plano")
    # la primera palabra de la segunda frase va detras de un punto y de dos
    # segundos de silencio: su plano entra en la mitad de ese silencio
    corte = len("Una frase.".split())
    igual(round(entradas[corte], 3),
          round((palabras[corte]["s"] + palabras[corte - 1]["e"]) / 2, 3),
          "el plano que entra tras un punto lo hace en mitad del silencio")
    igual(round(segmentar.adelanto_de(1.0, "fuerte", 0.25), 3), 0.5,
          "tras un punto, el silencio se reparte a medias")
    igual(round(segmentar.adelanto_de(1.0, "debil", 0.25), 3), 0.25,
          "tras una coma no: ahi la frase sigue")


# ------------------------------------------------------------- 5. voz.espaciar

def _wav(muestras):
    pcm = b"".join(struct.pack("<h", int(v)) for v in muestras)
    voz = medios.motor("voz_cartesia/voz.py")
    return voz.wav_desde_pcm(pcm)


def prueba_espaciar():
    titulo("voz.espaciar: el relleno es ruido de sala, no ceros")
    voz = medios.motor("voz_cartesia/voz.py")
    sr = voz.SR
    # Dos frases con una pausa corta entre ellas. La pausa lleva ruido de fondo
    # de verdad (no silencio digital), que es lo que hay que copiar.
    total = int(sr * 4)
    muestras = []
    for i in range(total):
        t = i / float(sr)
        if 1.0 <= t < 1.25:
            muestras.append(120 if i % 2 else -120)      # ruido de sala
        else:
            muestras.append(9000 if i % 3 else -9000)    # voz
    wav = _wav(muestras)

    escenas = [{"id": "B01"}, {"id": "B02"}]
    reparto = {"B01": [{"s": 0.0, "e": 1.0}], "B02": [{"s": 1.25, "e": 4.0}]}
    palabras = reparto["B01"] + reparto["B02"]
    nuevo, desplazamientos = voz.espaciar(wav, palabras, reparto, escenas,
                                          hueco_minimo=1.0)
    ok(len(nuevo) > len(wav), "el wav crece: se ha insertado silencio")
    igual(len(desplazamientos), 1, "y hay un desplazamiento por corte")
    ok(abs(desplazamientos[0]["retardo"] - 0.75) < 0.02,
       f"del tamano que faltaba para el hueco minimo ({desplazamientos[0]['retardo']}s)")

    pcm = voz._pcm_de_wav(nuevo)
    inicio = int(1.05 * sr) * 2
    fin = int(1.9 * sr) * 2
    trozo = [struct.unpack("<h", pcm[i:i + 2])[0] for i in range(inicio, fin, 2)]
    nulos = sum(1 for v in trozo if v == 0)
    ok(nulos < len(trozo) * 0.2,
       f"lo insertado NO son ceros: solo {nulos} de {len(trozo)} muestras a cero")
    ok(max(abs(v) for v in trozo) < 2000,
       "pero tampoco es voz: es el ruido de la propia pausa")

    sin_falta = {"B01": [{"s": 0.0, "e": 1.0}], "B02": [{"s": 3.0, "e": 4.0}]}
    igual(voz.espaciar(wav, palabras, sin_falta, escenas, 1.0)[1], [],
          "si la pausa ya es mayor que el minimo no se toca nada")


# --------------------------------------------------- 6. p6._capa_vectorial









# ------------------------------- 4ter. geometria compartida y continuidad

CATALOGO_DESPACHOS = {"sets": {
    # tres sitios que el guion presenta como distintos y salen del mismo modelo
    "despacho_regulador": {"base": "despacho"},
    "oficina_empleado": {"base": "despacho"},
    "sala_seguridad": {"base": "despacho"},
    "sucursal": {"base": "sucursal_bancaria"},
}}


ESTILO_MONIGOTE = {
    "referencias": ["a.png", "b.png"],
    "guia": {
        "guia": "flat vector cartoon, bold uniform black outlines, 4-6px thick",
        "paleta": ["#c4b8a4", "#1a1a1a", "#8fa8b2"],
        "trazo": "Uniform-width black outline, roughly 4-6px relative to frame",
        "personajes": "oversized round heads, 2-3 heads tall, dot eyes, no nose",
        "fondos": "flat colour, no texture",
        "evitar": "no gradients, no realistic proportions",
    },
}


def prueba_prompt_de_estilo():
    """El estilo del video se dice en UN sitio y lo reciben las dos ramas.

    Estaba escrito dos veces: el prompt de un plano volcaba la guia escrita entera
    y el de una hoja de personaje tenia su propia frase, que interpolaba un campo
    que la pantalla habia jubilado y que por tanto caia a un literal cableado
    -- «simple rounded shapes, muted earthy palette»-- igual para todos los videos.
    Las hojas salian en un dibujo que no era el elegido, y de ahi pasaban a los
    planos que las usan como referencia de personaje.
    """
    ficha = {"tipo": "reparto", "nombre": "nubla", "grupo": True,
             "descripcion": "a small group of young adults in hoodies"}

    titulo("prompt de la hoja de reparto: lleva la guia escrita del video")
    hoja = p6_assets._prompt_reparto(ficha, ESTILO_MONIGOTE)
    for trozo in ("4-6px", "#c4b8a4", "2-3 heads tall", "no gradients"):
        ok(trozo in hoja, f"la hoja recibe «{trozo}»")
    plano = p6_assets._prompt_completo(
        {"prompt": "five hackers at their desks", "luz": "night"},
        [{"papel": "lamina", "cuantas": 7, "ruta": "l.png"}], ESTILO_MONIGOTE)
    faltan = [t for t in ("4-6px", "#c4b8a4", "2-3 heads tall", "no gradients")
              if t not in plano]
    igual(faltan, [], "y el plano recibe exactamente lo mismo")

    titulo("prompt: no hay relleno generico cuando nadie escribio uno")
    vacio = p6_assets._con_defectos({"estilo": {"referencias": []}})["estilo"]
    igual(vacio.get("prompt"), "",
          "el estilo por defecto ya no describe un dibujo concreto")
    sin_estilo = p6_assets._prompt_reparto(ficha, dict(ESTILO_MONIGOTE, prompt=""))
    ok("rounded" not in sin_estilo and "bean-shaped" not in sin_estilo,
       "y no se cuela ninguna descripcion de otro video")

    titulo("prompt de la hoja: la cara es obligatoria y el decorado se ignora")
    for trozo in ("Every face must be fully visible", "eyes, eyebrows and mouth",
                  "Never cover a face with glare", "Ignore any setting"):
        ok(trozo in hoja, f"la hoja exige «{trozo}»")

    titulo("prompt del plano: la hoja de reparto manda sobre el texto")
    con_hoja = p6_assets._prompt_completo(
        {"prompt": "five hackers", "luz": "night"},
        [{"papel": "lamina", "cuantas": 7, "ruta": "l.png"},
         {"papel": "reparto", "nombre": "nubla", "ruta": "r.png"}],
        ESTILO_MONIGOTE)
    ok("do not redesign them" in con_hoja, "lleva negativo")
    ok("the sheet wins" in con_hoja, "y dice quien manda si el texto no coincide")
    ok("Copy their faces" in con_hoja, "y nombra la cara, que es lo que fija")

    # LA IMAGEN RECHAZADA Y LA QUE ADJUNTA EL REVISOR (PENDIENTE 39). Hasta el
    # 28-08-2026 los papeles de referencia eran estilo, lamina, reparto,
    # parecido, real y continuidad: NUNCA la propia imagen que se rechazo. El
    # prompt decia que la descripcion de arriba produjo la imagen rechazada,
    # pero eso preserva la DESCRIPCION, no los pixeles, y la composicion derivaba.
    titulo("prompt del plano: la imagen rechazada se cita, y con lo contrario")
    con_rechazada = p6_assets._prompt_completo(
        {"prompt": "a hand on a desk", "luz": "night"},
        [{"papel": "lamina", "cuantas": 7, "ruta": "l.png"},
         {"papel": "rechazada", "ruta": "s031.png"}],
        ESTILO_MONIGOTE, feedback="swap the hand for a gloved one")
    ok("THE IMAGE THAT WAS REJECTED" in con_rechazada,
       "se dice QUE es esa imagen: este mismo plano, como se dibujo la ultima vez")
    ok("Keep the same composition" in con_rechazada
       and "Change ONLY what the reviewer" in con_rechazada,
       "y la instruccion es la CONTRARIA que la de continuidad: de esta se copia "
       "todo menos lo que la nota diga")
    ok("Reference image 2" in con_rechazada,
       "citada por su posicion, que se numera sola desde la lista")
    adjunta = p6_assets._prompt_completo(
        {"prompt": "a hand on a desk"},
        [{"papel": "adjunta", "ruta": "nota.png"}], ESTILO_MONIGOTE,
        feedback="like this one")
    ok("attached by the reviewer" in adjunta, "la referencia de la nota se cita")
    ok("never reproduce arrows, circles, handwriting" in adjunta,
       "y con su negativo: una imagen suelta al final del prompt se lee como "
       "«dibuja esto», y los trazos de encima son anotaciones, no dibujo")

    # Y EL CAJON TIENE LECTOR: el `alcance` que escribe el repaso lo lee ESTA
    # funcion. Sin esta comprobacion, el enrutador podria estar clasificando
    # notas para nadie -- la nota se marcaria como aplicada y el plano se
    # rehariia sin la imagen delante, exactamente como antes.
    titulo("el alcance que escribe el repaso lo LEE quien monta las referencias")
    carpeta = tempfile.mkdtemp(prefix="rechazada_")
    try:
        previa = os.path.join(carpeta, "S031.png")
        with open(previa, "wb") as fh:
            fh.write(b"no es un png de verdad, y aqui da igual")
        dirs = {"escenas": carpeta}
        escena31 = {"id": "S031"}
        def adjuntos(nota):                                    # noqa: E306
            return p6_assets._adjuntos_de_la_nota(             # noqa: SLF001
                escena31, dirs, {"unidades": {"escena:S031": {"feedback": [nota]}}})
        igual([a["papel"] for a in adjuntos(
                   {"texto": "swap the hand", "alcance": "retoque", "de": "repaso"})],
              ["rechazada"], "con «retoque» se adjunta la imagen rechazada")
        igual(adjuntos({"texto": "this should be a phone", "alcance": "sustituye",
                        "de": "repaso"}), [],
              "y con «sustituye» no se adjunta nada: una imagen delante se lee "
              "como «edita esto» y volvia a salir el monolito")
        # SIN ALCANCE SE DECIDE AQUI, y por eso no hay tercer estado. El
        # enrutador lo escribe cuando la nota pasa por el, pero hay dos caminos
        # que no pasan --el boton de rehacer y el feedback escrito a pelo-- y
        # dejarlos sin imagen delante era dejar el caso mas comun sin la unica
        # cosa que mantiene la composicion. La regla: si la nota nombra a
        # alguien del reparto que este plano no lleva, lo que se pide es OTRA
        # escena («sustituye»); si no, es un retoque.
        igual([a["papel"] for a in adjuntos(
                   {"texto": "una nota vieja", "de": "repaso"})],
              ["rechazada"],
              "una nota sin alcance y sin nadie del reparto dentro se trata "
              "como retoque, que es lo que es casi siempre")
        igual([a["papel"] for a in adjuntos(
                   {"texto": "como esto", "de": "repaso", "imagenes": [previa]})],
              ["rechazada", "adjunta"],
              "y la referencia que dejo quien escribio la nota llega, DETRAS de "
              "la rechazada: primero lo que hay, despues lo que se quiere")
        igual([a["papel"] for a in adjuntos(
                   {"texto": "arregla esto", "de": "captura",
                    "imagenes": [previa]})],
              ["rechazada"],
              "pero NO las imagenes de una captura anotada: ese camino ya "
              "traduce los trazos a palabras a proposito, y meterle el PNG "
              "pintado invitaria a dibujar los trazos. La rechazada si va: es "
              "un retoque como cualquier otro")
        igual(p6_assets._adjuntos_de_la_nota(                  # noqa: SLF001
                  escena31, dirs, {}), [],
              "sin ninguna nota no se adjunta nada")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)

    titulo("cambiar la guia cambia la firma de cache de la hoja")
    # El segundo filo del fallo: la firma se calcula sobre el prompt, asi que una
    # guia que no entra en el prompt tampoco entra en la firma y la hoja volvia
    # de la cache igual para siempre por mucho que se reescribiera el estilo.
    otro = json.loads(json.dumps(ESTILO_MONIGOTE))
    otro["guia"]["guia"] = "stickman, 12px black line, no colour at all"
    otro["guia"]["trazo"] = "very thick 12px"
    ok(p6_assets._prompt_reparto(ficha, otro) != hoja,
       "otra guia, otro prompt")
    igual(medios.huella({"prompt": hoja}) == medios.huella(
        {"prompt": p6_assets._prompt_reparto(ficha, otro)}), False,
        "y por tanto otra firma: reescribir la guia invalida la hoja sola")


def prueba_guia_de_estilo():
    """La guia escrita: quien la escribe y que se le pregunta.

    Es la UNICA descripcion en palabras del dibujo del video y la reciben todas
    las imagenes -- planos y hojas de personaje --. Se escribia con el escalon mas
    barato del Estudio y, sobre todo, la llamada sin ajuste NI SIQUIERA llegaba a
    ese escalon: caia en el defecto general del CLI. Medido con imagenes: con la
    guia buena, las piernas salen como trazos negros sin manos ni pies y las
    caras planas, que es el estilo de la referencia; con la barata, cuerpos
    redondeados con sombreado.
    """
    titulo("guia de estilo: la escribe un escalon ALTO, nunca el barato")
    # Desde el 21-08-2026 el canal corre TODO en opus con esfuerzo muy alto
    # (cli_claude.MODELO_POR_DEFECTO), asi que esta fase ya no se distingue por
    # tener ajuste propio. Lo que sigue importando --y es lo que costo una ronda
    # de imagenes-- es que NUNCA caiga al escalon barato, y que su recomendacion
    # razonada siga escrita para el dia que se vuelva al reparto por fase.
    por_fase = cli_claude.por_defecto_de("guia_estilo")
    igual(por_fase["modelo"], "opus", "la escribe opus")
    ok(por_fase["esfuerzo"] in ("high", "xhigh", "max"),
       f"con esfuerzo alto: {por_fase['esfuerzo']}")
    recomendado = por_fase.get("recomendado") or {}
    igual((recomendado.get("modelo"), recomendado.get("esfuerzo")),
          ("opus", "high"),
          "y su recomendacion propia sigue escrita, sin borrar")
    ok(len(por_fase.get("porque") or "") > 40, "y esta escrito por que")
    # EL DEFECTO ES UN SUELO, NO UN TECHO: una fase que pide mas no se rebaja.
    # Se prueba con una fase de mentira porque hoy ninguna real pide 'max', y la
    # regla tiene que seguir protegida el dia que alguna vuelva a pedirlo.
    cli_claude.POR_FASE["_prueba_max"] = {
        "modelo": "opus", "esfuerzo": "max",
        "porque": "fase de prueba: comprueba que el defecto no rebaja a nadie"}
    try:
        igual(cli_claude.por_defecto_de("_prueba_max")["esfuerzo"], "max",
              "una fase que pide MAX sigue en max: subir el defecto no baja a nadie")
    finally:
        cli_claude.POR_FASE.pop("_prueba_max", None)

    titulo("guia de estilo: se pregunta por la cara, sea cual sea el estilo")
    plantilla = estilo.INSTRUCCION_GUIA
    ok('"caras"' in plantilla and "LA CARA" in plantilla,
       "el esquema pide un campo propio para la cara")
    # la pregunta describe lo que se ve, no un estilo: tiene que servir igual
    # para un dibujo plano, para anime, para pintura o para realista
    ok("sea cual sea el estilo" in plantilla
       and "Describe lo que VES" in plantilla,
       "y no presupone que el estilo sea de dibujo plano")

    titulo("guia de estilo: la cara llega al prompt de la imagen")
    con_caras = dict(ESTILO_MONIGOTE)
    con_caras["guia"] = dict(ESTILO_MONIGOTE["guia"],
                             caras="flat cream fill, no skin tone, dot eyes")
    texto = " ".join(p6_assets.guia_escrita(con_caras))
    ok("Faces:" in texto and "no skin tone" in texto,
       "lo que dice la guia sobre las caras entra en el prompt")
    sin_caras = " ".join(p6_assets.guia_escrita(ESTILO_MONIGOTE))
    ok("Faces:" not in sin_caras,
       "y una guia vieja, sin ese campo, sigue valiendo igual")


def prueba_exigir_estilo():
    """Sin guia escrita no se gasta el primer dolar."""
    titulo("_exigir_estilo: exige referencias Y guia")
    aqui = os.path.abspath(__file__)
    try:
        p6_assets._exigir_estilo({"estilo": {"referencias": [aqui]}})
        ok(False, "tendria que haber levantado")
    except RuntimeError as fallo:
        ok("guia escrita" in str(fallo), "y lo dice claro")
    try:
        p6_assets._exigir_estilo(
            {"estilo": {"referencias": [aqui], "guia": ESTILO_MONIGOTE["guia"]}})
        ok(True, "con guia, adelante")
    except RuntimeError as fallo:
        ok(False, f"no deberia levantar: {fallo}")
    try:
        p6_assets._exigir_estilo({"motor_imagen": "adoptar", "estilo": {}})
        ok(True, "y en modo adoptar no se exige nada: no se genera ninguna imagen")
    except RuntimeError as fallo:
        ok(False, f"adoptar no deberia levantar: {fallo}")


def prueba_cadenas():
    """Cuantas cadenas de generacion corren a la vez: una por sitio.

    El grafo lo dice solo: dentro de un sitio los planos van en fila -- cada uno
    se apoya en el anterior de SU sitio -- y entre sitios no se deben nada. Estaba
    en 1 por defecto, o sea 35 llamadas a la API en fila cuando el camino critico
    real eran 6.
    """
    titulo("cadenas: el paralelismo lo dice el video, no un numero")
    escenas = [{"set": "guarida"}, {"set": "guarida"}, {"set": "foro"},
               {"set": "sucursal"}, {"componente": "mapa", "set": None}]
    igual(p6_assets._cuantas_cadenas({}, escenas), 4,
          "tres sitios mas los planos sin sitio: cuatro cadenas")
    igual(p6_assets._cuantas_cadenas({"cadenas": 1}, escenas), 1,
          "con 1 se pide en fila, y se respeta")
    igual(p6_assets._cuantas_cadenas({"cadenas": 2}, escenas), 2,
          "y con un numero, ese numero")
    muchos = [{"set": f"sitio_{i}"} for i in range(40)]
    igual(p6_assets._cuantas_cadenas({}, muchos), p6_assets.MAX_CADENAS,
          "cuarenta sitios no disparan cuarenta llamadas a la vez")
    igual(p6_assets._cuantas_cadenas({}, []), 1, "sin planos, una")


def prueba_moodboard():
    """Referencias de estilo dibujadas a proposito, en vez de las que hubiera.

    Lo que se comprueba aqui es todo lo que NO cuesta una imagen: que ejes le
    tocan a cada plano, que el tile se monta y se cachea, que un moodboard sin
    aprobar no entra en produccion, y que el prompt lleva la guia y las reglas.
    """
    import moodboard

    titulo("moodboard: a cada plano le tocan los ejes de lo que sale en el")
    con_gente = moodboard.ejes_de_plano({"personajes": ["x"], "set": "guarida"})
    igual(con_gente[:2], ["cara", "cuerpos"],
          "un plano con personajes empieza por la cara y los cuerpos")
    ok("interior" in con_gente, "y lleva tambien el sitio")
    igual(moodboard.ejes_de_plano({"componente": "mapa"})[:2],
          ["diagrama", "objeto"], "un componente pide diagrama y objeto")
    igual(len(moodboard.ejes_de_plano({})), moodboard.POR_TILE,
          "siempre se manda un tile lleno: es UNA imagen, lo que cambia es cual")
    igual(moodboard.ejes_de_plano({"personajes": ["x"]}),
          moodboard.ejes_de_plano({"personajes": ["y"]}),
          "y es determinista: dos planos iguales reciben lo mismo")

    titulo("moodboard: la clave es del ESTILO, no del video")
    base = os.path.join(os.environ.get("TEMP", "."), "estudio_prueba_mood")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)
    rutas = []
    for indice in range(3):
        ruta = os.path.join(base, f"frame_{indice}.png")
        Image.new("RGB", (64, 48), color=(20 + indice * 40, 30, 40)).save(ruta)
        rutas.append(ruta)
    clave = moodboard.clave_de(rutas)
    ok(clave, "unos fotogramas dan una clave")
    igual(moodboard.clave_de(list(reversed(rutas))), clave,
          "y el orden en que se listan no la cambia")
    otras = rutas[:2] + [os.path.join(base, "frame_otro.png")]
    Image.new("RGB", (64, 48), color=(200, 10, 10)).save(otras[2])
    ok(moodboard.clave_de(otras) != clave, "otro fotograma, otro estilo")
    igual(moodboard.clave_de([]), "", "sin fotogramas no hay estilo que identificar")

    titulo("moodboard: sin aprobar NO entra en produccion")
    propuesta = os.path.join(base, "banco", "moodboards", "_propuestas", clave)
    os.makedirs(propuesta, exist_ok=True)
    for eje in ("cara", "cuerpos", "interior", "exterior"):
        Image.new("RGB", (120, 80), color=(90, 90, 90)).save(
            os.path.join(propuesta, f"{eje}.png"))
    cache = os.path.join(base, "_cache")
    igual(moodboard.tile_para({"personajes": ["x"]}, rutas, cache,
                              raiz=os.path.join(base, "banco")), None,
          "una propuesta no la usa el paso de assets")
    igual(moodboard.ficha_de(rutas, raiz=os.path.join(base, "banco"))["estado"],
          "propuesto", "pero se ve que esta ahi, esperando que alguien la mire")

    titulo("moodboard: aprobado, se monta el tile y se cachea")
    moodboard.aprobar(rutas, raiz=os.path.join(base, "banco"))
    igual(moodboard.ficha_de(rutas, raiz=os.path.join(base, "banco"))["estado"],
          "aprobado", "aprobar lo mueve al banco")
    tile = moodboard.tile_para({"personajes": ["x"], "set": "guarida"}, rutas,
                               cache, raiz=os.path.join(base, "banco"))
    ok(tile and os.path.exists(tile), f"se monta el tile: {tile}")
    ancho, alto = Image.open(tile).size
    igual((ancho, alto), moodboard.TAMANO, "con la proporcion de los planos")
    ok(os.path.basename(tile).startswith("tile_cara_cuerpos"),
       "y el nombre dice de que ejes es, que es lo que lo cachea")
    igual(moodboard.tile_para({"personajes": ["x"], "set": "guarida"}, rutas,
                              cache, raiz=os.path.join(base, "banco")), tile,
          "el segundo plano igual reutiliza el mismo tile")

    titulo("moodboard: rehacer un eje no se lleva por delante los demas")
    # El caso normal: de seis ejes salen bien cinco y uno deriva. Se rehace ese,
    # y con el aprobar de antes -- que movia la carpeta entera-- el banco se
    # quedaba con esa unica lamina y las otras cinco desaparecian sin decirlo.
    banco = os.path.join(base, "banco")
    os.makedirs(propuesta, exist_ok=True)      # aprobar se la ha llevado entera
    Image.new("RGB", (120, 80), color=(200, 10, 10)).save(
        os.path.join(propuesta, "interior.png"))
    ficha = moodboard.ficha_de(rutas, raiz=banco)
    igual(ficha["estado"], "propuesto",
          "con un eje sin mirar, el conjunto no esta aprobado")
    igual(ficha["pendientes"], ["interior"], "y es ese, no los demas")
    igual(len(ficha["ejes"]), 4, "los otros tres siguen contando")
    igual(moodboard.origen_de(ficha, "interior"), "propuesta",
          "el eje rehecho se lee de la propuesta")
    igual(moodboard.origen_de(ficha, "cara"), "banco", "y el resto del banco")
    igual(Image.open(ficha["ejes"]["interior"]).getpixel((1, 1)), (200, 10, 10),
          "la ficha apunta a la lamina NUEVA, que es la que hay que mirar")
    moodboard.aprobar(rutas, raiz=banco)
    quedan = sorted(f for f in os.listdir(os.path.join(banco, "moodboards", clave))
                    if f.endswith(".png"))
    igual(len(quedan), 4, f"aprobar un eje deja los cuatro en el banco: {quedan}")
    igual(Image.open(os.path.join(banco, "moodboards", clave,
                                  "interior.png")).getpixel((1, 1)),
          (200, 10, 10), "y el que manda es el corregido")

    titulo("moodboard: viaja DENTRO del preset de estilo")
    # Un preset de estilo copia sus fotogramas a su propia carpeta del banco.
    # La clave del moodboard sale del CONTENIDO de esos fotogramas, asi que la
    # copia encuentra el mismo; y ademas las laminas se guardan con el preset,
    # para el dia que el banco se limpie.
    import presets_canal
    fichero, banco_presets, banco_medios = (presets_canal.FICHERO,
                                            presets_canal.BANCO, medios.BANCO)
    presets_canal.FICHERO = os.path.join(base, "presets.json")
    presets_canal.BANCO = os.path.join(base, "banco_presets")
    medios.BANCO = banco
    try:
        preset = presets_canal.guardar("estilo", "Estilo de prueba", {
            "referencias": rutas, "calidad": "low",
            "guia": {"guia": "trazo grueso", "palabras": 3}})
        guardado = preset["datos"].get("moodboard") or {}
        igual(guardado.get("clave"), clave, "el preset guarda la clave del estilo")
        igual(len(guardado.get("ejes") or []), 4,
              "y las cuatro laminas aprobadas")
        igual(moodboard.clave_de(preset["datos"]["referencias"]), clave,
              "los fotogramas copiados apuntan al mismo moodboard: la clave es "
              "del contenido, no de la ruta")
        ok("referencias dibujadas" in preset["resumen"],
           f"y el desplegable lo dice sin abrirlo: {preset['resumen']}")

        shutil.rmtree(os.path.join(banco, "moodboards", clave), ignore_errors=True)
        igual(moodboard.ficha_de(rutas, raiz=banco)["estado"], "falta",
              "se limpia el banco de moodboards")
        devueltas = presets_canal.restaurar_moodboard(
            presets_canal.leer(preset["id"]))
        igual(len(devueltas["ejes"]), 4, "aplicar el preset lo devuelve entero")
        igual(moodboard.ficha_de(rutas, raiz=banco)["estado"], "aprobado",
              "y vuelve aprobado, que es como se guardo")
    finally:
        presets_canal.FICHERO, presets_canal.BANCO = fichero, banco_presets
        medios.BANCO = banco_medios

    titulo("moodboard: el prompt lleva la guia y las reglas de la casa")
    reglas = medios.motor("reglas/reglas.py")
    prompt = moodboard.prompt_de_eje(
        "cara", ESTILO_MONIGOTE, "los brazos eran mas delgados",
        p6_assets.guia_escrita(ESTILO_MONIGOTE),
        reglas.bloque_prompt("prompt_imagen"))
    ok("4-6px" in prompt, "la guia escrita entera")
    ok("los brazos eran mas delgados" in prompt and "takes priority" in prompt,
       "la correccion de quien mira, y por delante")
    ok("sonriendo" in prompt or "smiling" in prompt.lower(),
       "y las reglas de la casa: en la primera prueba salieron sonriendo "
       "porque este bloque no llegaba")
    ok("never its content" in prompt,
       "con la prohibicion de copiar el contenido de la referencia")

    titulo("el idioma del canal llega a lo que se DIBUJA dentro de la imagen")
    # EL FALLO QUE ARREGLA, visto el 24-08-2026 en la muestra de un preset:
    # un canal en ESPANOL saco el eje «diagrama» rotulado «PLAN / DO / REVIEW».
    # Nadie lo pidio en ingles; el encargo entero va en ingles y el generador
    # rotula en el idioma en que se le habla. Y esa lamina no se queda en la
    # ficha: viaja como referencia dentro de cada plano con componentes, o sea
    # que ensena a rotular mal CON UN EJEMPLO DIBUJADO.
    bloque = reglas.bloque_prompt("prompt_imagen")
    ok("LETTERING YOU DRAW BELONGS TO THE FILM" in bloque,
       "la POLITICA vive en el motor de reglas, no en el codigo: asi vale para "
       "las laminas y para los planos con una sola redaccion")
    ok("never translated" in bloque,
       "y dice que los nombres propios NO se traducen: sin eso, «FBI» o un "
       "logotipo saldrian traducidos")
    ok("adds nothing" in bloque,
       "y que no anade texto: solo decide el idioma del que ya se permite")

    con = moodboard.prompt_de_eje("diagrama", ESTILO_MONIGOTE, "",
                                  None, bloque, idioma="es")
    sin = moodboard.prompt_de_eje("diagrama", ESTILO_MONIGOTE, "",
                                  None, bloque)
    ok("The language of this production is Spanish." in con,
       "en la LAMINA se dice cual es el idioma, con su nombre en ingles")
    ok("The language of this production is" not in sin,
       "y sin idioma no se dice nada: la regla se queda inerte a proposito")
    ok(con.index("LETTERING YOU DRAW") < con.index("The language of this"),
       "el dato va DETRAS de la regla que lo interpreta")

    escena_texto = {"id": "S001", "prompt": "a whiteboard", "narracion": "hola"}
    con = p6_assets._prompt_completo(escena_texto, [], ESTILO_MONIGOTE,
                                     idioma="pt")
    ok("The language of this film is Portuguese." in con,
       "y en el PLANO de un video, igual")
    ok("The language of this film is" not in
       p6_assets._prompt_completo(escena_texto, [], ESTILO_MONIGOTE),
       "sin idioma, tampoco se dice nada")
    ok("The language of this film is" not in
       p6_assets._prompt_completo(escena_texto, [], ESTILO_MONIGOTE,
                                  idioma="xx"),
       "y un codigo que no se conoce NO se cuela: mas vale callarse que "
       "mandarle dos letras a un generador de imagenes")

    # LOS SEIS IDIOMAS QUE OFRECE EL MODO LIGHT tienen nombre en ingles. Sin
    # esto, elegir portugues seria elegir un idioma que el prompt no sabe decir.
    import presets_light as light_mod
    faltan = [c for c in light_mod.IDIOMAS if not p2_brief.nombre_idioma_en(c)]
    ok(not faltan, f"los {len(light_mod.IDIOMAS)} idiomas del modo light saben "
                   f"decirse en ingles{'' if not faltan else f' -- FALTAN {faltan}'}")
    shutil.rmtree(base, ignore_errors=True)


def prueba_orden_de_la_cartela():
    """La cartela se escribe al ritmo de la voz, asi que va en SU orden.

    EL CASO, del video largo (0:17). La narracion decia «Someone typed a
    username and a password, and the door opened» y salieron dos fallos
    distintos con la misma pinta:

        1. «A PASSWORD» se anclaba en el PRIMER «a» --el de «a username»-- asi
           que en pantalla aparecia «A», pasaba segundo y medio de audio que no
           tenia nada que ver, y despues «PASSWORD». Es del MOTOR.
        2. «OPENED THE DOOR» pone las palabras al reves que la voz. Ninguna
           sincronia puede arreglar eso. Es del TEXTO.
    """
    titulo("la cartela va en el orden de la voz")
    narracion = "Someone typed a username and a password, and the door opened."
    marcas = [[i * 0.4, i * 0.4 + 0.35] for i in range(11)]
    tramos = [(narracion, marcas)]
    #      0        1      2   3         4    5   6         7    8    9     10
    #   someone  typed    a  username  and   a  password  and  the  door  opened
    #   0.0      0.4     0.8   1.2     1.6  2.0   2.4     2.8  3.2  3.6   4.0

    # --- FALLO 1: la ocurrencia buena
    igual(cartelas.encajar(["A", "PASSWORD"], tramos, duracion=4.0),
          [2.0, 2.4],
          "«A PASSWORD» ancla en el «a» de «a password» (2,0 s) y no en el de "
          "«a username» (0,8 s): las dos palabras se dicen juntas y tienen que "
          "salir juntas")
    igual(cartelas.encajar(["A", "USERNAME"], tramos, duracion=4.0),
          [0.8, 1.2],
          "y NO es «coge la ultima»: con «A USERNAME» vuelve a ser el primer "
          "«a», que ahi es el bueno. Lo que se elige es el grupo mas JUNTO")
    igual(cartelas.encajar(["THE", "DOOR", "OPENED"], tramos, duracion=4.0),
          [3.2, 3.6, 4.0],
          "y escrita en el orden en que se oye, cae clavada palabra a palabra")

    # --- FALLO 2: el orden, que el anclaje no puede arreglar
    ok(not cartelas.fuera_de_orden(["THE", "DOOR", "OPENED"], narracion),
       "«THE DOOR OPENED» va en el orden de la voz: sin aviso")
    sueltas = cartelas.fuera_de_orden(["OPENED", "THE", "DOOR"], narracion)
    ok(sueltas, f"«OPENED THE DOOR» se avisa: {sueltas}")
    igual([p for p, _ in sueltas], ["OPENED"],
          "y se nombra la palabra que esta fuera de su sitio, que es lo que "
          "dice como se arregla")

    # --- LO QUE NO PUEDE AVISAR: destilar esta BIEN
    ok(not cartelas.fuera_de_orden(
        ["ONE", "PASSWORD", "WAS", "THE", "WHOLE", "LOCK"], narracion),
       "una cartela DESTILADA --con palabras que no se dicen-- no se avisa: "
       "reducir es lo que se pide, y solo se acusa lo que se dice fuera de sitio")
    ok(not cartelas.fuera_de_orden(["SOMEONE", "TYPED", "A", "PASSWORD"],
                                   narracion),
       "ni una que recorta por el medio pero respeta el orden")
    ok(not cartelas.fuera_de_orden([], narracion), "ni una cartela vacia")
    ok(not cartelas.fuera_de_orden(["LO", "QUE", "SEA"], ""),
       "ni un plano sin narracion")

    # --- Y EL AVISO LLEGA, con el id del plano delante para que sea un enlace
    escenas = [
        {"id": "S012", "narracion": "Before that, nothing.",
         "marcas": [[0, 0.3], [0.3, 0.6], [0.6, 0.9]]},
        {"id": "S013", "narracion": narracion, "marcas": marcas},
        {"id": "S014", "narracion": "And then it was over.",
         "marcas": [[4.4 + i * 0.3, 4.6 + i * 0.3] for i in range(5)]},
    ]
    plan = {"S013": {"plantilla": "tesis", "datos": {"texto": "OPENED THE DOOR"}}}
    avisos = cartelas.avisos_de_orden(plan, escenas)
    ok(avisos and avisos[0].startswith("S013: "),
       f"el aviso empieza por el id del plano: {avisos}")
    ok(avisos and "OPENED" in avisos[0], "y nombra la palabra")

    plan_bueno = {"S013": {"plantilla": "tesis",
                           "datos": {"texto": "THE DOOR OPENED"}}}
    igual(cartelas.avisos_de_orden(plan_bueno, escenas), [],
          "y la version bien escrita no avisa de nada")

    # CONTRA SU PROPIO PLANO Y NO CONTRA LA VENTANA: con la ventana, una palabra
    # corriente del plano de al lado --el «was» de S014-- deja en falso
    # desorden a media cartela bien escrita.
    plan_destilado = {"S013": {"plantilla": "tesis",
                               "datos": {"texto": "ONE PASSWORD WAS THE WHOLE LOCK"}}}
    igual(cartelas.avisos_de_orden(plan_destilado, escenas), [],
          "y el «was» del plano siguiente no ensucia el aviso de este")

    # --- EL PROMPT LO PIDE, ademas de comprobarse
    ok("EN EL MISMO ORDEN EN QUE SE OYEN" in cartelas.INSTRUCCION,
       "y el prompt lo pide, que es lo que evita el aviso en vez de contarlo")
    ok("PENDIENTE.md 12" not in cartelas.INSTRUCCION,
       "y ya no delega el orden en el motor: esa frase decia que de sincronizar "
       "ya se encargaba el, y de reordenar no puede encargarse nadie")


def prueba_redactor():
    """El prompt escrito entero: lo que el codigo GARANTIZA pase lo que pase."""
    sets = {"quiosco": {"descripcion": "A quiet newsstand wall of front pages"}}

    titulo("redactor: la descripcion del sitio se garantiza, no se pide por favor")
    # Es la razon por la que el 28-08 se descarto que el agente redactara el
    # prompt entero: si reescribe el sitio, dos planos del mismo sitio dejan de
    # parecer el mismo sitio. Aqui no depende de que obedezca.
    ficha, aviso = redactor.limpiar_ficha(
        {"set": "quiosco",
         "prompt": "A newsstand seen from the street with racks of papers and "
                   "nobody around at all"}, sets, ("quiosco",))
    ok(ficha["prompt"].startswith("A quiet newsstand wall of front pages."),
       "si no la copio, se le pone delante")
    ok("no copio la descripcion del sitio" in aviso, "y se dice")
    ficha, aviso = redactor.limpiar_ficha(
        {"set": "quiosco",
         "prompt": "A quiet newsstand wall of front pages. One clipped page "
                   "fills the frame with wavy scribbles instead of a headline"},
        sets, ("quiosco",))
    igual(aviso, "", "si la copio, no se toca nada")
    igual(ficha["prompt"].count("A quiet newsstand wall"), 1,
          "y no se duplica")

    titulo("redactor: el sitio que declara")
    igual(redactor.limpiar_ficha(
        {"set": "", "prompt": "A 1920s apartment corner with a tall tiled "
                              "stove and banknotes burning in the firebox"},
        sets, ("quiosco",))[0]["set"], "",
        "puede no usar ninguno del catalogo: se ha inventado su sitio")
    ok("no es de su tramo" in redactor.limpiar_ficha(
        {"set": "otro", "prompt": "x " * 20}, sets, ("quiosco",))[1],
       "y si declara uno que no es de su tramo, se canta")

    titulo("redactor: lo que se comprueba ANTES de pagar una imagen")
    igual(redactor.limpiar_ficha({"prompt": "a shot"}, sets)[0], None,
          "un parrafo de dos palabras no describe un plano")
    plan = {"S001": {"prompt": "the banker signs a document"},
            "S002": {"prompt": "the banker, mouth a straight line, signs"}}
    escenas = [{"id": "S001", "personajes": ["b"]},
               {"id": "S002", "personajes": ["b"]}]
    igual(redactor.sin_declarar(plan, escenas), ["S001"],
          "un plano con gente que no declara la expresion se caza aqui: sin "
          "ella la sonrisa esta prohibida y nadie sonrie nunca")
    igual(redactor.repetidos({"S001": {"prompt": "el mismo"},
                              "S002": {"prompt": "El mismo."}}, escenas),
          [["S001", "S002"]], "dos planos con el mismo prompt se cantan")


def prueba_reparto_de_beats():
    """Varios beats en el mismo bloque se reparten entre sus planos."""
    titulo("_beats_por_escena: un bloque con cuatro ideas da cuatro sitios")
    # es B001 del video del oro: un parrafo con cuatro frases y cuatro beats,
    # de los que hasta el 07-09 solo se usaba el primero (los otros tres eran
    # codigo muerto: 51 de 146 en ese video)
    beats = [{"set": "quiosco", "_tramo": (0.1, 9.8)},
             {"set": "bolsa", "_tramo": (0.1, 9.8)},
             {"set": "banco", "_tramo": (0.1, 9.8)},
             {"set": "monedero", "_tramo": (0.1, 9.8)},
             {"set": "oficina", "_tramo": (9.8, 20.0)}]
    catalogo = {"beats": beats}
    cuatro = [{"t_in": 0.0, "t_out": 2.0}, {"t_in": 2.0, "t_out": 4.8},
              {"t_in": 4.8, "t_out": 7.0}, {"t_in": 7.0, "t_out": 9.6},
              {"t_in": 10.3, "t_out": 12.8}]
    igual([(b or {}).get("set")
           for b in p6_assets._beats_por_escena(cuatro, catalogo)],
          ["quiosco", "bolsa", "banco", "monedero", "oficina"],
          "cuatro planos y cuatro beats: uno cada uno, en orden")

    seis = [{"t_in": i * 1.5, "t_out": i * 1.5 + 1.5} for i in range(6)]
    igual([(b or {}).get("set")
           for b in p6_assets._beats_por_escena(seis, catalogo)],
          ["quiosco", "quiosco", "bolsa", "banco", "banco", "monedero"],
          "con mas planos que beats, se reparten sin saltarse ninguno")

    dos = [{"t_in": 0.0, "t_out": 4.0}, {"t_in": 4.0, "t_out": 9.0}]
    igual([(b or {}).get("set")
           for b in p6_assets._beats_por_escena(dos, catalogo)],
          ["quiosco", "banco"],
          "con menos planos que beats se RECORRE el arco, no se coge el "
          "principio: el primero y el tercero, no el primero y el segundo")

    titulo("_beats_por_escena: sin rango no opina, y el emparejamiento por "
           "palabras sigue vivo")
    igual(p6_assets._beats_por_escena([{"t_in": 0, "t_out": 1}],
                                      {"beats": [{"set": "x",
                                                  "palabras": ["oro"]}]}),
          [None], "un catalogo escrito a mano no trae tramos: aqui se dice que "
                  "no hay beat y lo resuelve _beat_de por palabras")
    igual(p6_assets._beats_por_escena([{"t_in": 0, "t_out": 1}], {}), [None],
          "y sin beats tampoco revienta")


def prueba_ultima_palabra_rotulos():
    """La cláusula de rótulos va la ULTIMA, que es la posicion que pesa."""
    titulo("prompt: los rotulos se sujetan al final")
    escena = {"prompt": "a newsstand wall", "luz": "grey morning"}
    prompt = p6_assets._prompt_completo(escena, [], {"guia": {}}, idioma="es")
    ok(p6_assets.ULTIMA_PALABRA_ROTULOS in prompt,
       "la clausula entra en el prompt")
    ok(prompt.index(p6_assets.ULTIMA_PALABRA_ROTULOS)
       > prompt.index("Scene:"),
       "y va DESPUES de la escena: las reglas largas se adelantaron el 07-09 "
       "y esto es lo que recupera el sitio fuerte para lo que mas se rompe")
    ok("AT MOST TWO" in p6_assets.ULTIMA_PALABRA_ROTULOS,
       "limita CUANTOS rotulos, que es lo que no limitaba nadie: nueve "
       "titulares de cuatro palabras cumplian la regla de las diez")
    ok("illegible wavy strokes" in p6_assets.ULTIMA_PALABRA_ROTULOS,
       "y dice que hacer cuando no caben, que es lo que ya funciona en S001")


def prueba_rotulo_en_el_idioma_del_video():
    """Lo que se dibuja escrito va en el idioma del vídeo, y se dice al final.

    EL FALLO QUE ARREGLA, visto el 07-09-2026 en `video_referencia`: catorce rótulos en
    INGLÉS dentro de un vídeo en castellano -- "CITY OPENS NEW PARK", "BANK",
    "SAVINGS", "THE PROBLEM", "TO LET" --. Dos causas, y las dos aquí:

      1. Nadie le pasaba el idioma a `direccion` (a `cartelas` sí, desde que un
         vídeo en inglés salió con «DIAS / ANOS» en pantalla), y su ÚNICO
         ejemplo de rótulo estaba escrito en inglés: «reading "CORNER STORE"».
         El agente copia el patrón que tiene delante.
      2. La política estaba a mitad del prompt y un texto ENTRE COMILLAS le
         gana: el generador dibuja lo que se le pide literal.

    Por eso el arreglo son dos capas, y las dos se comprueban: los agentes lo
    saben, y la ÚLTIMA línea del prompt lo repite.
    """
    titulo("prompt: el rotulo va en el idioma del video")
    escena = {"prompt": "a newsstand wall", "luz": "grey morning"}
    prompt = p6_assets._prompt_completo(escena, [], {"guia": {}}, idioma="es")
    cierre = p6_assets._ultima_palabra_idioma("es")
    ok(cierre and cierre in prompt, "la clausula del idioma entra en el prompt")
    ok("Spanish" in cierre,
       "y nombra el idioma EN INGLES, que es en lo que se le habla al generador")
    ok(prompt.index(cierre) > prompt.index(p6_assets.ULTIMA_PALABRA_ROTULOS),
       "va DESPUES de la clausula de rotulos: es lo ultimo que se lee")
    ok("in another language" in cierre,
       "y cubre el caso real: un rotulo que la escena pidio en otro idioma")
    ok("brands" in cierre and "acronyms" in cierre,
       "sin traducir los nombres propios, que seria el fallo contrario")

    igual(p6_assets._ultima_palabra_idioma(""), "",
          "sin idioma no se dice nada: mejor callar que colarle un codigo")
    igual(p6_assets._ultima_palabra_idioma("zz"), "",
          "y un idioma que no se conoce tampoco opina")

    titulo("los dos agentes reciben el idioma, y su ejemplo no lo contradice")
    ok("{idioma}" in direccion.INSTRUCCION,
       "`direccion` tiene el hueco del idioma en su encargo")
    ok("{idioma}" in redactor.INSTRUCCION,
       "y `redactor` tambien")
    ok("CORNER STORE" not in direccion.INSTRUCCION,
       "y el ejemplo en ingles se ha ido: era lo unico que decia en que idioma "
       "se escribe un rotulo, y decia que en ingles")


def prueba_la_cara_es_de_esa_escena():
    """Un plano con gente nunca se queda sin expresión, y es la suya.

    EL FALLO QUE ARREGLA, medido el 07-09-2026 sobre 44 planos:

      · en el camino de `direccion` el tono era OPCIONAL («dilo si no es el del
        tramo») y se dijo en 3 de 44. Los otros 41 cayeron al del tramo, vacío en
        ese vídeo, así que 27 de los 30 planos con gente salieron con la misma
        cara neutra y «No smiling» -- la misma para «cada euro que ganas vale
        menos» que para una familia a la que le alcanza;
      · en el camino del `redactor` no la ponía NADIE: el cortocircuito de
        `redactado` se salta el `_expresion(_tono_de(...))`, y el negativo lleva
        «smiling, grin, cheerful expression». 98 planos de 299 en `prueba_1`.

    El defecto silencioso de los dos no era «la que toque»: era «serio».
    """
    titulo("la cara: el suelo del prompt redactado")
    con_gente = {"redactado": "A wide hall with two figures crossing it",
                 "personajes": ["ahorrador"], "narracion": "Y le alcanza"}
    salida = p6_assets._prompt_visual(con_gente, {"tono": "alegre"}, {})
    ok("open relaxed smiles" in salida,
       "un parrafo con gente que no dice la cara recibe la del tono de SU beat")

    ya_la_dice = {"redactado": "A wide hall, the man with a wide open mouth and "
                               "raised eyebrows", "personajes": ["ahorrador"],
                  "narracion": "Y le alcanza"}
    salida = p6_assets._prompt_visual(ya_la_dice, {"tono": "alegre"}, {})
    ok("open relaxed smiles" not in salida,
       "y el que SI la dice no recibe una segunda: dos expresiones en un prompt "
       "es pedir dos caras")

    sin_nadie = {"redactado": "An empty pavement", "personajes": [],
                 "narracion": "No hay nadie"}
    ok("faces" not in p6_assets._prompt_visual(sin_nadie, {"tono": "tenso"}, {}),
       "y un plano sin gente no recibe ninguna cara")

    titulo("la cara: `direccion.sin_tono` avisa antes de pagar")
    escenas = [{"id": "S1", "personajes": ["a"]}, {"id": "S2", "personajes": ["a"]},
               {"id": "S3", "personajes": []}]
    plan = {"S1": "algo (TONO: alegre)", "S2": "algo sin tono",
            "S3": "una calle vacia"}
    igual(direccion.sin_tono(plan, escenas), ["S2"],
          "senala el plano con gente que no declara su tono")
    igual(direccion.sin_tono({"S1": "algo (TONO: preocupado)"},
                             [{"id": "S1", "personajes": ["a"]}]), ["S1"],
          "y un tono que no esta en la tabla cuenta como no declarado: "
          "`_tono_de` no lo reconoce, asi que no llegaria al prompt")
    ok("(TONO:" in direccion.INSTRUCCION
       and "OBLIGATORIO" in direccion.INSTRUCCION.upper(),
       "y el encargo ya no lo pide «si cambia», lo pide siempre")

    titulo("la cara: una sola tabla de pistas, no dos")
    ok(redactor.sin_declarar({"S1": {"prompt": "an empty hall"}},
                             [{"id": "S1", "personajes": ["a"]}]) == ["S1"],
       "el aviso del redactor marca el plano sin cara")
    ok(redactor.sin_declarar({"S1": {"prompt": "his mouth tight"}},
                             [{"id": "S1", "personajes": ["a"]}]) == [],
       "y no marca el que la trae")
    for pista in p6_assets.PISTAS_DE_CARA:
        if not p6_assets._dice_la_cara(f"something {pista} something"):
            ok(False, f"la pista '{pista}' no la reconoce el suelo del prompt")
            break
    else:
        ok(True, "las pistas del aviso y las del suelo del prompt son LAS "
                 "MISMAS: si se separan, uno de los dos miente")


def prueba_continuidad():
    """La continuidad no cruza de escenario."""
    titulo("continuidad_de: solo planos del mismo sitio")
    plan = [{"id": "S001", "set": "guarida"}, {"id": "S002", "set": "guarida"},
            {"id": "S003", "set": "sucursal"}, {"id": "S004", "set": "sucursal"}]
    por_id = {e["id"]: e for e in plan}
    anteriores = ["S001", "S002"]
    igual(p6_assets.continuidad_de(por_id["S003"], anteriores, por_id), [],
          "el primer plano de un sitio no se apoya en el sitio anterior")
    igual(p6_assets.continuidad_de(por_id["S004"], ["S001", "S002", "S003"], por_id),
          ["S003"], "el segundo se apoya solo en el suyo")
    igual(p6_assets.continuidad_de({"id": "S005", "set": None}, anteriores, por_id), [],
          "un plano sin sitio (un mapa) no arrastra continuidad de nadie")
    largo = [{"id": f"S{i:03d}", "set": "guarida"} for i in range(1, 6)]
    por_id_largo = {e["id"]: e for e in largo}
    igual(p6_assets.continuidad_de(por_id_largo["S005"],
                                   ["S001", "S002", "S003", "S004"], por_id_largo),
          ["S004"], "y UNA sola, la ultima: dos fotos pesan mas que la linea "
                    "del plano y devuelven los cinco angulos del mismo mueble")
    igual(p6_assets.continuidad_de(por_id_largo["S005"],
                                   ["S001", "S002", "S003", "S004"],
                                   por_id_largo, cuantos=2),
          ["S003", "S004"], "quien pida dos sigue pudiendo pedirlas")

    titulo("continuidad_de: `EN OTRO SITIO:` corta la continuidad por los dos lados")
    # Es el fallo que anulaba la salida de escape: el plano declaraba su propio
    # sitio, `_prompt_visual` le quitaba el del tramo del TEXTO, y aqui se le
    # seguian adjuntando las fotos de ese mismo sitio presentadas como «la misma
    # habitacion». Medido en video_referencia: S003 («Hoy siguen dando para la compra
    # del mes», que se iba a un supermercado actual) recibio dos fotos de la
    # cocina de 1925.
    fuga = [{"id": "S001", "set": "cocina_1925"},
            {"id": "S002", "set": "cocina_1925"},
            {"id": "S003", "set": "cocina_1925",
             "direccion": "EN OTRO SITIO: a present-day supermarket checkout"},
            {"id": "S004", "set": "cocina_1925"}]
    por_id_fuga = {e["id"]: e for e in fuga}
    igual(p6_assets.continuidad_de(por_id_fuga["S003"], ["S001", "S002"],
                                   por_id_fuga),
          [], "el que se va no se apoya en el sitio del que se acaba de ir")
    igual(p6_assets.continuidad_de(por_id_fuga["S004"],
                                   ["S001", "S002", "S003"], por_id_fuga),
          ["S002"], "y el que se queda salta al ultimo que SI estaba alli: el "
                    "PNG del que se fue es el supermercado, no la cocina")


def prueba_cache_referencias():
    """Dos referencias distintas con el mismo nombre no se pisan en la cache."""
    titulo("imagen.normalizar: la cache va por ruta, no por nombre de fichero")
    imagen = medios.motor("imagen_openai/imagen.py")
    base = os.path.join(os.environ.get("TEMP", "."), "estudio_prueba_refs")
    shutil.rmtree(base, ignore_errors=True)
    rutas = []
    for indice, sitio in enumerate(("despacho_regulador", "oficina_empleado")):
        carpeta = os.path.join(base, sitio)
        os.makedirs(carpeta, exist_ok=True)
        ruta = os.path.join(carpeta, "hombro__vista.png")
        Image.new("L", (8, 8), color=40 + indice * 100).save(ruta, "PNG")
        rutas.append(ruta)
    cache = os.path.join(base, "_cache")
    destinos = [imagen.normalizar(r, cache) for r in rutas]
    ok(destinos[0] != destinos[1],
       f"el mismo nombre en dos sets da dos entradas: {destinos}")
    colores = [Image.open(d).convert("L").getpixel((0, 0)) for d in destinos]
    ok(colores[0] != colores[1],
       f"y cada una tiene su imagen, no la del otro set: {colores}")
    shutil.rmtree(base, ignore_errors=True)


def prueba_rehacer_de_verdad():
    """«Rehacer todo» no puede devolver lo mismo sacado de la cache.

    Forzar se deducia de `unidades is not None`, o sea de haber pedido unidades
    CONCRETAS: pedirlo TODO --la peticion mas fuerte que hay-- era la unica que
    no forzaba nada. Cambiabas la guia de estilo, dabas a «Rehacer todo» y una
    parte del video volvia igual, servida por la cache del banco de imagenes.
    """
    titulo("rehacer: con la cache llena, forzar tiene que pagar imagen nueva")
    base = os.path.join(os.environ.get("TEMP", "."), "estudio_prueba_rehacer")
    shutil.rmtree(base, ignore_errors=True)
    banco = os.path.join(base, "banco_imagenes")
    os.makedirs(banco, exist_ok=True)
    referencia = os.path.join(base, "ref.png")
    Image.new("RGB", (32, 32), color=(10, 20, 30)).save(referencia)

    p = dict(p6_assets.PARAMS_POR_DEFECTO)
    p.update({"banco_imagenes": banco, "motor_imagen": "openai",
              "calidad": "low", "imagenes_previas": []})
    destino = os.path.join(base, "S001.png")

    # EL MOTOR DE MENTIRA, PUESTO DESDE LA PRIMERA LINEA. No es comodidad: si
    # algo de aqui abajo se equivoca y una llamada no acierta en la cache,
    # `_producir_imagen` sigue camino hasta OpenAI y la prueba PAGA una imagen.
    # Con el motor sustituido, ese fallo sale como un numero de llamadas que no
    # cuadra, que es como tiene que salir.
    llamadas = []

    class MotorFalso:
        #: Un color por llamada, para reconocer de cual salio el fichero.
        colores = [(200, 0, 0), (0, 200, 0), (0, 0, 200)]

        @staticmethod
        def generar(prompt, referencias, quality="low", tamano="apaisado"):
            color = MotorFalso.colores[len(llamadas) % 3]
            llamadas.append(prompt)
            crudo = io.BytesIO()
            Image.new("RGB", (32, 32), color=color).save(crudo, "PNG")
            return crudo.getvalue(), {"coste": 0.006, "segundos": 1.0}

    original = medios.motor
    medios.motor = lambda ruta: (MotorFalso if "imagen" in ruta else original(ruta))
    try:
        # 1. LA CACHE SE LLENA LLAMANDO AL CODIGO, no escribiendo un fichero con
        #    un nombre calculado a mano. La firma lleva el prompt, la calidad,
        #    el tamano y la huella de cada referencia, y copiar esa receta aqui
        #    es lo que se rompio: cuando el codigo le anadio `tamano`, la copia
        #    se quedo atras y la prueba dejo de probar lo que decia.
        meta = p6_assets._producir_imagen("S001", "un plano", [referencia],
                                          destino, p)
        igual(meta["origen"], "generada", "la primera vez se paga y se cachea")
        igual(len(llamadas), 1, "una llamada al motor")

        # 2. Y LA SEGUNDA ACIERTA. Es lo mismo que probaba la version anterior,
        #    pero atado al codigo: si la firma deja de ser estable entre dos
        #    llamadas iguales, esto falla.
        meta = p6_assets._producir_imagen("S001", "un plano", [referencia],
                                          destino, p)
        igual(meta["origen"], "cache",
              "sin forzar, la cache manda (y no cuesta nada)")
        igual(len(llamadas), 1, "y no se ha vuelto a llamar al motor")

        # 3. FORZANDO SE PAGA, que es el fallo que descubrio esta prueba:
        #    «Rehacer todo» --la peticion mas fuerte que hay-- era la unica que
        #    no forzaba nada, y devolvia de la cache la imagen que el humano
        #    acababa de rechazar.
        meta = p6_assets._producir_imagen("S001", "un plano", [referencia],
                                          destino, p, rehacer=True)
    finally:
        medios.motor = original
    igual(meta["origen"], "generada", "forzando, se paga una imagen nueva")
    igual(len(llamadas), 2, "y se ha llamado al motor una vez mas, solo una")
    igual(Image.open(destino).convert("RGB").getpixel((1, 1)), (0, 200, 0),
          "el fichero que queda es el NUEVO, no el de la cache")

    ok("rehacer" in p6_assets.OPCIONES_EJECUCION,
       "y la opcion viaja por invocacion, sin tocar la firma del paso")
    shutil.rmtree(base, ignore_errors=True)


def prueba_ids_en_orden():
    """Los ids van SIEMPRE en orden de video; la herencia viaja aparte.

    Antes el plano que narraba lo mismo recuperaba su id viejo y tras recortar
    la rejilla saltaba (S001, S002, S027...). La proteccion real contra volver
    a pagar nunca fue el numero: es la cache por contenido mas la herencia de
    camara/identidad, que ahora viaja en `heredados` (id nuevo -> plano
    anterior) y en `hereda_de`, con el id siempre igual a la posicion.
    """
    segmentar = medios.motor("guion/segmentar.py")

    titulo("planificar: los ids siempre en orden; la herencia, en heredados")
    palabras, tiempo = [], 0.0
    for i in range(1, 13):
        for w in ("Una", "frase", f"numero", f"{i}."):
            palabras.append({"w": w, "s": round(tiempo, 2),
                             "e": round(tiempo + 0.4, 2)})
            tiempo += 0.5
        tiempo += 0.4
    segmentos = segmentar.segmentar(palabras, 2.0, 4.0)
    recien = [dict(e) for e in segmentar.construir_escenas(segmentos)]
    igual([e["id"] for e in recien[:4]], ["S001", "S002", "S003", "S004"],
          "el corte numera en orden de video")

    # un plan anterior con los mismos textos pero otros ids
    previo = {"escenas": [dict(e, id=f"S{40 - i:03d}")
                          for i, e in enumerate(recien)]}
    heredado = [dict(e) for e in segmentar.construir_escenas(segmentos)]
    reparto = p6_assets._heredar_ids(heredado, previo)
    igual([e["id"] for e in heredado[:4]], ["S001", "S002", "S003", "S004"],
          "heredando, los ids SIGUEN en orden de video")
    ok(all(e.get("hereda_de") for e in heredado),
       "y cada plano apunta de que id viejo hereda (hereda_de)")
    igual(heredado[0].get("hereda_de"), "S040",
          "el rastro dice el id anterior de verdad")
    ok(len(reparto["conservados"]) == len(heredado),
       "misma narracion = conservado, aunque el numero haya cambiado")
    igual(reparto["retirados"], [],
          "un numero que cambia de sitio NO es contenido retirado")

    replanteado = [dict(e) for e in segmentar.construir_escenas(segmentos)]
    reparto = p6_assets._heredar_ids(replanteado, {})
    igual([e["id"] for e in replanteado[:4]], ["S001", "S002", "S003", "S004"],
          "sin plan previo, igual: en orden")
    igual(reparto["heredados"], {}, "y sin previo no hay nada que heredar")


def prueba_guia_con_manos():
    """La guia escrita tiene que fijar las manos, y llegar al prompt.

    El generador dibuja manos realistas de cinco dedos MIENTRAS NADIE LE DIGA LO
    CONTRARIO, asi que en un estilo de manopla el hueco no sale neutro: sale
    mal. Se pedia «como son manos y extremidades» dentro de la lista de
    personajes y se perdia entre lo demas.
    """
    titulo("guia de estilo: las manos se piden aparte y llegan al prompt")
    ok("manos" in estilo.INSTRUCCION_GUIA,
       "el prompt de la guia pide un campo de manos con nombre propio")
    ok("NUMERO DE DEDOS" in estilo.INSTRUCCION_GUIA,
       "y exige el numero de dedos con una cifra, no un adjetivo")
    ok("no close-up hands visible" in estilo.INSTRUCCION_GUIA,
       "con salida honesta si en los fotogramas no se ve ninguna mano")

    con_manos = dict(ESTILO_MONIGOTE)
    guia = dict(con_manos["guia"])
    guia["manos"] = "mitten-shaped hands, no separate fingers"
    guia["relleno"] = "flat fills, one tone per surface"
    con_manos["guia"] = guia
    lineas = p6_assets.guia_escrita(con_manos)
    texto = " ".join(lineas)
    ok("mitten-shaped hands" in texto,
       "y lo que diga de las manos entra en el prompt de cada imagen")
    ok("flat fills" in texto, "igual que el relleno")

    ok("no realistic five-fingered hands" in estilo.INSTRUCCION_GUIA,
       "y le dice a la guia que lo prohiba en su campo 'evitar'...")
    ok("SI dibuja manos" in estilo.INSTRUCCION_GUIA,
       "...pero solo si en ESOS fotogramas las manos no son realistas")

    # La base de reglas es transversal: se lee igual en todos los videos, sin
    # mirar los fotogramas ni la guia. Llevaba 'realistic hands' y 'photographic
    # anatomy' en el negativo, o sea que empujaba contra el estilo elegido en
    # cualquier video que quisiera ser realista. Es el mismo fallo que el prompt
    # de reparto con «bean-shaped characters» cableado, mas pequeno.
    reglas = medios.motor("reglas/reglas.py")
    bloque = reglas.bloque_prompt("prompt_imagen")
    ok("dedos" in bloque or "hand" in bloque.lower(),
       "y hay una regla de la casa para cuando la guia no lo diga")
    ok("extra fingers" in bloque and "fused fingers" in bloque,
       "que prohibe los defectos que lo son en cualquier estilo")
    bajo = bloque.lower()
    ok("realistic hands" not in bajo and "photographic anatomy" not in bajo,
       "y NO decide el estilo: eso es de la guia, que si mira los fotogramas")
    ok("five-fingered" not in bajo,
       "ni cuenta los dedos por su cuenta en un video que no ha visto")


def prueba_recarga_de_motores():
    """Un motor arreglado tiene que llegar a ejecutarse, y sin dejar de medirse.

    Los motores se cacheaban para siempre y los pasos corren en un HILO del
    servicio: con el servicio levantado desde por la manana, arreglar un motor
    no servia de nada -- se seguia ejecutando la copia en memoria y se depuraba
    codigo que no se estaba ejecutando. Paso de verdad con el limite de la API
    de imagen.

    Y la trampa del arreglo: recargar crea un objeto modulo NUEVO, y el medidor
    de coste engancha sus funciones POR NOMBRE sobre el objeto viejo. Sin volver
    a engancharse, el gasto de imagen dejaria de contarse en silencio.
    """
    from nucleo import coste

    titulo("motores: se recargan si cambian, y el medidor no se suelta")
    ruta = os.path.join(medios.MOTORES, "imagen_openai", "imagen.py")
    if not os.path.exists(ruta):
        ok(False, f"falta el motor de imagen en {ruta}")
        return
    antes = medios.motor("imagen_openai/imagen.py")
    coste.instrumentar()
    ok(getattr(antes.generar, coste._MARCA, False),
       "el motor cargado esta enganchado al medidor de gasto")

    copia = ruta + ".prueba_bak"
    shutil.copy2(ruta, copia)
    try:
        os.utime(ruta, (time.time() + 2, time.time() + 2))
        ahora = medios.motor("imagen_openai/imagen.py")
        ok(ahora is not antes, "si el fichero cambia, se recarga")
        ok(getattr(ahora.generar, coste._MARCA, False),
           "y el modulo NUEVO sigue midiendo: si no, el gasto se dejaria de "
           "contar sin decir nada")

        with medios.trabajo_en_curso():
            os.utime(ruta, (time.time() + 4, time.time() + 4))
            durante = medios.motor("imagen_openai/imagen.py")
        igual(durante is ahora, True,
              "a media tanda NO se recarga: partiria en dos el freno del "
              "limite de la API y el contador de gasto")
        ok(medios.motor("imagen_openai/imagen.py") is not ahora,
           "y al terminar la tanda si")
    finally:
        shutil.move(copia, ruta)
        # EL CANDADO, OTRA VEZ. Aqui arriba se ha recargado el motor a
        # proposito, y un motor recien cargado trae su `generar` de verdad.
        _prohibir_pagar()


def prueba_recarga_de_la_otra_cache():
    """Los motores de comun (ingesta, voz, revision) tambien se recargan.

    El arreglo de la cache llego a `medios` -- imagen, corte -- y NO a
    `pasos/comun.py`, que tiene la suya. O sea que la mitad de los motores
    seguian congelados exactamente por el mismo motivo, y con el mismo sintoma:
    se arregla voz.py y el servicio sigue ejecutando la copia de por la manana.

    Y el congelado tiene que ser EL MISMO que el de medios: con dos contadores,
    entrar en un paso protegeria los motores de imagen y dejaria sueltos los de
    voz, a media sintesis.
    """
    titulo("motores de comun: se recargan si cambian, y no a media tanda")
    ruta = os.path.join(comun.RAIZ_MOTORES, "voz_cartesia", "voz.py")
    if not os.path.exists(ruta):
        ok(False, f"falta el motor de voz en {ruta}")
        return
    antes = comun.cargar_motor("voz_cartesia", "voz.py")
    ok(comun.cargar_motor("voz_cartesia", "voz.py") is antes,
       "sin tocar el fichero, la cache devuelve el mismo modulo")

    copia = ruta + ".prueba_bak"
    shutil.copy2(ruta, copia)
    try:
        os.utime(ruta, (time.time() + 2, time.time() + 2))
        ahora = comun.cargar_motor("voz_cartesia", "voz.py")
        ok(ahora is not antes, "si el fichero cambia, se recarga")

        with medios.trabajo_en_curso():
            os.utime(ruta, (time.time() + 4, time.time() + 4))
            durante = comun.cargar_motor("voz_cartesia", "voz.py")
        igual(durante is ahora, True,
              "a media tanda NO se recarga: es el congelado de medios, no otro")
        despues = comun.cargar_motor("voz_cartesia", "voz.py")
        ok(despues is not ahora, "y al terminar la tanda si")

        # p4_voz guardaba el modulo en una variable suya, asi que la recarga no
        # le llegaba nunca: se arreglaba el motor y el paso seguia con el viejo.
        ok(p4_voz.motor.SR is despues.SR,
           "y p4_voz resuelve contra el modulo cargado ahora, no contra el suyo")
    finally:
        shutil.move(copia, ruta)


def prueba_limite_de_la_api():
    """Un 429 de velocidad se espera; uno de saldo, no. Y se espera lo que dicen.

    El limite que salta de verdad es el de IMAGENES DE ENTRADA por minuto --cada
    plano manda entre 8 y 14 adjuntos--, y se reintentaba con dos esperas de 3 s
    y 6 s contra una ventana que se renueva cada minuto: era imposible salir de
    ahi, y la tanda entera moria despues de haber pagado los planos anteriores.
    """
    titulo("motor de imagen: el 429 se espera lo que la API dice")
    imagen = medios.motor("imagen_openai/imagen.py")

    class Respuesta:
        def __init__(self, texto, cabeceras=None, codigo=429):
            self.text = texto
            self.headers = cabeceras or {}
            self.status_code = codigo

        def json(self):
            return json.loads(self.text)

    velocidad = Respuesta(json.dumps({"error": {
        "message": "Rate limit reached for gpt-image-2 in organization org-X on "
                   "input-images per min: Limit 5, Used 5, Requested 1. Please "
                   "try again in 4.2s. Visit https://platform.openai.com/"
                   "account/billing to see your limits.",
        "type": "requests", "code": "rate_limit_exceeded"}}))
    ok(not imagen._sin_saldo(velocidad),
       "un 429 de velocidad NO se confunde con quedarse sin credito, aunque su "
       "mensaje mencione la pagina de facturacion")
    igual(imagen._cuanto_esperar(velocidad), 5.2,
          "se espera lo que dice el mensaje, con un margen")
    igual(imagen._cuanto_esperar(Respuesta("{}", {"retry-after": "30"})), 30.0,
          "y si viene la cabecera, manda ella")
    igual(imagen._cuanto_esperar(Respuesta("{}")), imagen.ESPERA_LIMITE_S,
          "sin ninguna pista se espera la ventana entera: con un limite POR "
          "MINUTO, esperar menos es garantizar otro 429")
    ok("input-images por min" in imagen._motivo_limite(velocidad),
       f"y se dice QUE limite ha saltado: {imagen._motivo_limite(velocidad)}")

    sin_saldo = Respuesta(json.dumps({"error": {
        "message": "You exceeded your current quota.",
        "type": "insufficient_quota", "code": "insufficient_quota"}}))
    ok(imagen._sin_saldo(sin_saldo),
       "y quedarse sin credito si se reconoce: reintentar eso no arregla nada")

    titulo("motor de imagen: el cubo cuenta lo que cuenta el otro lado")
    # El limite que salta es de IMAGENES DE ENTRADA por minuto y cada plano
    # manda entre 4 y 14 adjuntos: contando llamadas, cuatro cadenas metian
    # veinte imagenes contra un tope de cinco.
    imagen.LIMITE_POR_MINUTO[0] = 5
    imagen._TECHO_DEL_429[0] = None
    imagen._LLAMADAS[:] = []
    imagen._pedir_ficha(4)
    igual(sum(n for _, n in imagen._LLAMADAS), 4,
          "una llamada con cuatro adjuntos gasta cuatro fichas, no una")
    imagen._LLAMADAS[:] = []

    # Y el calibrado no puede quedarse con el cubo de TOKENS, que son millones
    cabeceras = {"x-ratelimit-limit-images": "5",
                 "x-ratelimit-reset-images": "1s",
                 "x-ratelimit-limit-requests": "500",
                 "x-ratelimit-reset-requests": "6ms",
                 "x-ratelimit-limit-tokens": "2000000",
                 "x-ratelimit-reset-tokens": "1s",
                 "x-ratelimit-limit-requests-day": "10000",
                 "x-ratelimit-reset-requests-day": "86400s"}
    imagen._calibrar(Respuesta("{}", cabeceras, 200))
    igual(imagen.LIMITE_POR_MINUTO[0], 5,
          "de todas las cabeceras se coge la del cubo que salta, no la de tokens "
          "ni la del cupo diario")
    # y el orden en que las emita el servidor no puede cambiar el resultado
    imagen.LIMITE_POR_MINUTO[0] = 99
    imagen._calibrar(Respuesta("{}", dict(reversed(list(cabeceras.items()))), 200))
    igual(imagen.LIMITE_POR_MINUTO[0], 5, "y da igual el orden de las cabeceras")
    imagen.LIMITE_POR_MINUTO[0] = 5


def prueba_copiar_con_fichero_abierto():
    """Regenerar no se cae porque la pantalla este ensenando un fichero.

    La interfaz pinta las imagenes leyendolas de la MISMA carpeta de trabajo que
    se rehace al regenerar. Copiar lo recien generado empezaba por borrar esa
    carpeta, o sea por borrar justo los ficheros que se estan mirando, y en
    Windows un fichero abierto no se puede borrar: [WinError 32], y el paso se
    caia despues de haber pagado. Lo que si se puede es sobrescribirlo.
    """
    titulo("copiar: un fichero abierto no tumba el paso")
    base = os.path.join(os.environ.get("TEMP", "."), "estudio_prueba_copiar")
    shutil.rmtree(base, ignore_errors=True)

    def sembrar(carpeta, texto, nombres=("ventanal__vista.png",
                                         "ventanal__depth.png")):
        os.makedirs(carpeta, exist_ok=True)
        for nombre in nombres:
            with open(os.path.join(carpeta, nombre), "w", encoding="utf-8") as fh:
                fh.write(texto)
        return carpeta

    origen = sembrar(os.path.join(base, "_generado", "despacho"), "nuevo")
    destino = sembrar(os.path.join(base, "trabajo", "despacho"), "viejo")
    sembrar(destino, "sobra", ("camara_vieja__vista.png",))

    mirando = open(os.path.join(destino, "ventanal__vista.png"), "rb")
    try:
        try:
            shutil.rmtree(destino)
            choca = False
        except PermissionError:
            choca = True
        # en Linux si se puede borrar un fichero abierto: alli esto no aplica
        ok(choca or os.name != "nt",
           "el borrado de antes SI choca con el fichero abierto (WinError 32)")
        sobrantes = medios.copiar_carpeta(origen, destino)
    finally:
        mirando.close()

    with open(os.path.join(destino, "ventanal__vista.png"), encoding="utf-8") as fh:
        igual(fh.read(), "nuevo",
              "la lamina bloqueada se SOBRESCRIBE, que es lo que Windows si deja")
    igual(sobrantes, [], "y lo que ya no existe en el origen se retira")
    ok(not os.path.exists(os.path.join(destino, "camara_vieja__vista.png")),
       "no se queda ninguna camara fantasma")

    # un sobrante que si esta bloqueado se declara: no tumba el paso, pero
    # tampoco se calla, porque una lamina vieja es un encuadre que ya no existe
    sembrar(destino, "x", ("fantasma__vista.png",))
    pegado = open(os.path.join(destino, "fantasma__vista.png"), "rb")
    try:
        sobrantes = medios.copiar_carpeta(origen, destino)
    finally:
        pegado.close()
    igual([os.path.basename(s) for s in sobrantes], ["fantasma__vista.png"],
          "y lo que no se ha podido retirar se dice por su nombre")

    # Y EL CASO CONTRARIO: el fichero se esfuma ENTRE la foto y el borrado. La
    # lista que recorre `_retirar_sobrantes` sale de un `os.walk`, o sea de una
    # foto: para cuando le toca el turno a un nombre, el navegador puede haber
    # soltado su ultima referencia y Windows haber completado un borrado que
    # tenia pendiente. Subia como WinError 2 desde `borrar` --la unica funcion
    # que promete no tirar nada-- y se llevaba el paso entero DESPUES de
    # haberlo pagado. Tumbo esta misma suite el 25-08.
    esfumado = os.path.join(destino, "fantasma__vista.png")
    sembrar(destino, "x", ("fantasma__vista.png",))
    remove_de_verdad = os.remove

    def remove_que_llega_tarde(objetivo):
        remove_de_verdad(objetivo)
        if os.path.abspath(objetivo) == os.path.abspath(esfumado):
            raise FileNotFoundError(2, "The system cannot find the file specified")

    os.remove = remove_que_llega_tarde
    try:
        ok(medios.borrar(esfumado),
           "un fichero que ya no esta cuando le toca el turno cuenta como "
           "borrado: el estado que se buscaba es justo ese")
    finally:
        os.remove = remove_de_verdad
    ok(not os.path.exists(esfumado), "y en efecto no queda")

    shutil.rmtree(base, ignore_errors=True)


def prueba_render_con_fichero_abierto():
    """El render no se cae porque Edge o el antivirus retengan un PNG.

    Es la misma familia que la de arriba y salio del mismo sitio --Windows y un
    fichero abierto-- pero en el paso 8, y ahi se veia de dos formas distintas
    que no se parecen entre si:

      1. `os.replace` del fotograma de transicion sobre el PNG que el propio
         Edge acaba de cargar como textura: [WinError 32] y el lote entero
         muerto, con el render ya pagado;
      2. y la peor de leer: `shutil.rmtree` + `os.makedirs(exist_ok=True)` sobre
         la carpeta de fotogramas del plano. Con un handle vivo dentro, Windows
         deja la carpeta en BORRADO PENDIENTE en vez de quitarla -- sigue
         existiendo, `makedirs` no hace nada, y desaparece a mitad del bucle:

             FileNotFoundError: ... frames\\S008\\f00027.png

    Las dos curas viven en `medios`: insistir al sustituir, y VACIAR la carpeta
    en vez de borrarla.
    """
    titulo("render: un PNG retenido no tumba el lote")
    base = os.path.join(os.environ.get("TEMP", "."), "estudio_prueba_render_fs")
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base, exist_ok=True)

    # 1 · reemplazar insiste mientras el destino este retenido
    destino = os.path.join(base, "f00002.png")
    with open(destino, "wb") as fh:
        fh.write(b"viejo")
    temporal = destino + ".tmp.png"
    with open(temporal, "wb") as fh:
        fh.write(b"nuevo")
    replace_de_verdad = os.replace
    intentos = [0]

    def replace_que_choca_una_vez(origen, hasta):
        intentos[0] += 1
        if intentos[0] == 1:
            raise PermissionError(
                32, "The process cannot access the file because it is being "
                    "used by another process")
        return replace_de_verdad(origen, hasta)

    os.replace = replace_que_choca_una_vez
    try:
        medios.reemplazar(temporal, destino)
    finally:
        os.replace = replace_de_verdad
    igual(intentos[0], 2, "reemplazar vuelve a intentarlo tras un WinError 32")
    with open(destino, "rb") as fh:
        igual(fh.read(), b"nuevo", "y el fotograma acaba siendo el nuevo")

    # y un bloqueo que NO se suelta SUBE: taparlo dejaria un corte sin
    # transicion y sin que nadie lo supiera
    def replace_que_nunca_va(origen, hasta):
        raise PermissionError(32, "sigue abierto")

    os.replace = replace_que_nunca_va
    try:
        with open(temporal, "wb") as fh:
            fh.write(b"otro")
        try:
            medios.reemplazar(temporal, destino)
            subio = False
        except PermissionError:
            subio = True
    finally:
        os.replace = replace_de_verdad
    ok(subio, "un bloqueo que no se suelta sube en vez de callarse")

    # 2 · rehacer_carpeta deja la carpeta VACIA Y EXISTIENDO, y lo hace con un
    # fichero abierto dentro -- que es cuando `rmtree` la dejaria pendiente
    carpeta = os.path.join(base, "S008")
    os.makedirs(carpeta, exist_ok=True)
    for numero in range(3):
        with open(os.path.join(carpeta, f"f{numero:05d}.png"), "wb") as fh:
            fh.write(b"x")
    abierto = open(os.path.join(carpeta, "f00001.png"), "rb")
    try:
        resisten = medios.rehacer_carpeta(carpeta)
    finally:
        abierto.close()
    ok(os.path.isdir(carpeta),
       "la carpeta del plano sigue existiendo con un fichero abierto dentro")
    igual([os.path.basename(r) for r in resisten],
          ["f00001.png"] if os.name == "nt" else [],
          "y lo que resiste se DICE por su nombre (en Linux no resiste nada)")
    # y lo importante: se puede seguir escribiendo dentro, que es justo lo que
    # el borrado pendiente impedia
    with open(os.path.join(carpeta, "f00027.png"), "wb") as fh:
        fh.write(b"nuevo")
    ok(os.path.exists(os.path.join(carpeta, "f00027.png")),
       "y se puede escribir dentro despues de vaciarla")

    resisten = medios.rehacer_carpeta(carpeta)
    igual(resisten, [], "sin nadie reteniendo, no queda nada")
    igual(os.listdir(carpeta), [], "y la carpeta queda vacia")

    shutil.rmtree(base, ignore_errors=True)


def prueba_feedback_en_prompts():
    """La nota del revisor ENTRA en el prompt que se paga, no solo en la firma.

    El feedback movia la firma de la unidad (se pagaba una imagen nueva) pero
    el prompt era identico: salia una variacion de lo mismo y la nota se
    ignoraba entera. Paso con una hoja de reparto («que parezcan hackers con
    capucha») y con un plano («plano dividido en 3 paises»), el 18-08.
    """
    titulo("p6: el feedback del revisor entra en el prompt")
    igual(p6_assets._texto_feedback("  con capucha  "), "con capucha",  # noqa: SLF001
          "una cadena se limpia y pasa")
    igual(p6_assets._texto_feedback([{"texto": "a"}, {"texto": "b"}]),  # noqa: SLF001
          "a | b", "un historial se aplana en un texto")
    igual(p6_assets._texto_feedback(None), "", "y sin nota no hay clausula")

    escena = {"id": "S007", "narracion": "customers across three countries",
              "prompt": "a bank office", "luz": "day"}
    con = p6_assets._prompt_completo(escena, [], {},              # noqa: SLF001
                                     feedback="split screen, 3 paises")
    sin = p6_assets._prompt_completo(escena, [], {})             # noqa: SLF001
    ok("split screen, 3 paises" in con and "REJECTED it" in con,
       "el prompt del plano lleva la nota y dice que es un rechazo")
    # PENDIENTE 36: la nota no compite con la descripcion, la MANDA. Medido
    # sobre el S018 del video largo, el `Scene:` eran 905 caracteres describiendo
    # lo que el revisor queria quitar contra 140 de nota -- 6,5 a 1 --, y ahi
    # dentro un imperativo absoluto rival («SHOT TYPE, and this is not
    # optional»). No se clasifica la nota: se le da precedencia sobre todo.
    ok("HIGHEST PRIORITY" in con and "OVERRIDES" in con,
       "y va con precedencia explicita sobre lo de arriba, que es lo que "
       "arregla el feedback que SUSTITUYE la escena en vez de corregirla")
    ok(con.index("Scene: a bank office") < con.index("split screen, 3 paises"),
       "la nota va DETRAS de todo, incluidas las reglas de la casa: es la "
       "posicion mas fuerte del prompt")
    ok("does not mention stays exactly" in con,
       "y lo que la nota no menciona se queda como estaba: sin esa frase, una "
       "correccion de dos palabras borraria el plano entero")
    ok("reviewer" not in sin, "y sin nota no aparece la clausula")

    ficha = {"nombre": "nubla", "descripcion": "four hackers",
             "feedback": "capucha y mascara de anonymous"}
    hoja = p6_assets._prompt_reparto(ficha, {})                  # noqa: SLF001
    ok("capucha y mascara de anonymous" in hoja and "NOT optional" in hoja,
       "el prompt de la hoja lleva la nota como orden, no como adorno")

    params = {"unidades": {"asset:nubla": {"feedback": "con mascara"}}}
    plan = {"escenas": [{"id": "S001", "narracion": "x",
                         "personajes": ["nubla"]}]}
    necesarios = p6_assets._assets_necesarios(plan, {"sets": {}, "reparto": {},
                                                     "componentes": {}}, params)
    igual(necesarios["asset:nubla"].get("feedback"), "con mascara",
          "y la ficha de la hoja recoge la nota de la unidad")



def prueba_direccion():
    """QUE SE VE EN CADA PLANO: la capa que faltaba en el prompt de imagen.

    El sitio es el mismo para todos los planos rodados ahi y la accion del beat
    es la misma para todo su tramo, asi que dos planos seguidos recibian casi el
    mismo encargo. Medido sobre el video largo: 852 caracteres identicos de 1.280.
    """
    titulo("direccion: la linea se limpia, no se corta a medias")
    igual(direccion.limpiar_linea('  "a hand covers the screen"  ')[0],
          "a hand covers the screen",
          "se quitan las comillas y los espacios de sobra")
    igual(direccion.limpiar_linea("")[0], None, "una vacia no vale")
    igual(direccion.limpiar_linea("cuatro palabras aqui mismo")[0], None,
          f"ni una de menos de {direccion.PALABRAS_MINIMAS} palabras: no dice "
          f"nada que dibujar")
    larga = " ".join(f"w{i}" for i in range(direccion.PALABRAS_MAXIMAS * 2))
    recortada, aviso = direccion.limpiar_linea(larga)
    igual(len(recortada.split()), direccion.PALABRAS_MAXIMAS,
          "una larga se recorta al tope")
    ok(all(len(x) > 1 for x in recortada.split()),
       "y por PALABRAS enteras: una frase cortada a media palabra llega al "
       "modelo de imagen como una instruccion rota")
    ok("se recorta" in aviso, f"y se dice: {aviso}")

    titulo("direccion: solo se dirige lo que GENERA imagen")
    ok(direccion.dirigible({"id": "S001"}), "un plano normal se dirige")
    ok(not direccion.dirigible({"id": "S002", "sigue_a": "S001"}),
       "una mitad de toma no: copia la imagen del hogar")
    ok(direccion.dirigible({"id": "S001", "cartela": {"plantilla": "cifra"}}),
       "una cartela SOBRE IMAGEN si: su plano se rueda igual")
    ok(not direccion.dirigible({"id": "S002", "sigue_a": "S001", "cartela": {
        "plantilla": "cifra", "sigue_a": "S001"}}),
       "y la continuacion de una cartela tampoco: lo que la excluye es "
       "`sigue_a`, no el fondo -- desde el 22-08 no hay fondo solido "
       "")

    titulo("direccion: lo que devuelve el agente se valida contra los planos")
    limpio, avisos = direccion._limpiar(
        {"planos": {"S001": "a hand covers the screen while a clerk walks in",
                    "S002": "  ",
                    "S099": "un plano que no existe"}},
        {"S001", "S002", "S003"})
    igual(sorted(limpio), ["S001"], "solo entra lo que vale y es de esta tanda")
    ok(any("S099" in a for a in avisos), "un id inventado se dice y se ignora")
    ok(any("sin direccion" in a for a in avisos),
       f"y los que se quedan sin ella tambien: {avisos}")

    titulo("direccion: dos planos con la MISMA linea se cantan")
    escenas_d = [{"id": "S001"}, {"id": "S002"}, {"id": "S003"}]
    igual(direccion.repetidas({"S001": "A hand covers the screen.",
                               "S002": "a hand covers the screen",
                               "S003": "otra cosa"}, escenas_d),
          [["S001", "S002"]],
          "normalizado, porque el punto final no las hace distintas")
    igual(direccion.repetidas({"S001": "una", "S002": "otra"}, escenas_d), [],
          "y si son distintas no hay nada que decir")

    titulo("direccion: entra en el prompt, y sin ella el prompt no cambia")
    # Es la propiedad que permite anadir esto a un video a medias: un plano sin
    # direccion se arma exactamente como antes.
    catalogo_d = {"sets": {"sitio": {"descripcion": "a bank office"}},
                  "reparto": {}, "componentes": {}, "prompt_por_defecto": ""}
    escena_d = {"id": "S001", "set": "sitio", "narracion": "the line",
                "personajes": []}
    beat_d = {"accion": "the auditor arrives"}
    sin = p6_assets._prompt_visual(dict(escena_d), beat_d, catalogo_d)
    con = p6_assets._prompt_visual(
        dict(escena_d, direccion="a hand covers the screen"), beat_d, catalogo_d)
    ok("a hand covers the screen" in con, "la direccion entra en el prompt")
    ok("a hand covers the screen" not in sin,
       "y sin ella el prompt sale exactamente como salia")
    ok(con.index("a hand covers") < con.index("the line"),
       "va ANTES de la frase narrada: donde estamos, que vemos, y que se dice")
    ok(con.index("bank office") < con.index("a hand covers"),
       "y DESPUES del sitio, que es el orden en que se lee")
    igual(p6_assets._prompt_visual(dict(escena_d, direccion="   "), beat_d,
                                   catalogo_d), sin,
          "una direccion en blanco es no tener direccion")

    titulo("direccion: y el prompt de dos planos hermanos deja de ser el mismo")
    # El fallo que esto viene a quitar, medido igual que se midio en el video.
    a = p6_assets._prompt_visual(dict(escena_d, id="S001"), beat_d, catalogo_d)
    b = p6_assets._prompt_visual(dict(escena_d, id="S002"), beat_d, catalogo_d)
    comun_sin = 0
    while comun_sin < min(len(a), len(b)) and a[comun_sin] == b[comun_sin]:
        comun_sin += 1
    a2 = p6_assets._prompt_visual(
        dict(escena_d, id="S001", direccion="a hand covers the screen"),
        beat_d, catalogo_d)
    b2 = p6_assets._prompt_visual(
        dict(escena_d, id="S002", direccion="the auditor opens a folder"),
        beat_d, catalogo_d)
    comun_con = 0
    while comun_con < min(len(a2), len(b2)) and a2[comun_con] == b2[comun_con]:
        comun_con += 1
    ok(comun_con < comun_sin,
       f"dos planos del mismo sitio comparten menos prompt con direccion "
       f"({comun_con} caracteres) que sin ella ({comun_sin})")


def prueba_cartelas():
    """Las cartelas: encajan siempre, se validan antes de dibujar y se reparten."""
    titulo("cartelas: las diez plantillas se dibujan y caben en la banda")
    paleta = {"texto": "#ece7dc", "tenue": "#c9c2b4", "linea": "#d8a657",
              "sombra": "#1b1710", "acento": "#d8785a"}
    for pid, ficha in cartelas.PLANTILLAS.items():
        svg = cartelas.svg_carta({"plantilla": pid, "datos": dict(ficha["ejemplo"])},
                                 paleta, duracion=4.5)
        ok(svg.startswith("<svg") and svg.endswith("</svg>"), f"{pid}: SVG entero")
        # El TEXTO tiene que caer dentro de la BANDA visible: el video recorta
        # 16:9 sobre un lienzo 3:2 y lo de fuera no lo ve nadie. Se mide solo el
        # texto y no todo lo que lleve una 'y': el fondo es un rect de 0 a 1024
        # y TIENE que cubrir el lienzo entero, no la banda.
        ys = [float(m) for m in re.findall(r'<text[^>]*\sy="(-?[\d.]+)"', svg)]
        ok(ys, f"{pid}: deberia dibujar algo de texto")
        fuera = [y for y in ys if y < cartelas.BANDA[1] - 1 or y > cartelas.BANDA[3] + 1]
        igual(fuera, [], f"{pid}: nada se escribe fuera de la banda que sale en cuadro")

    titulo("cartelas: un texto larguisimo NO se sale, baja de tamano")
    largo = "palabra " * 40
    corto = cartelas.svg_carta({"plantilla": "tesis", "datos": {"texto": largo}},
                               paleta, duracion=4.0)
    tam_largo = min(int(t) for t in re.findall(r'font-size="(\d+)"', corto))
    normal = cartelas.svg_carta({"plantilla": "tesis", "datos": {"texto": "Dos palabras"}},
                                paleta, duracion=4.0)
    tam_normal = max(int(t) for t in re.findall(r'font-size="(\d+)"', normal))
    ok(tam_largo < tam_normal,
       f"el texto largo se dibuja mas pequeno ({tam_largo} < {tam_normal})")
    ys = [float(m) for m in re.findall(r'<text[^>]*\sy="(-?[\d.]+)"', corto)]
    ok(max(ys) <= cartelas.BANDA[3] + 1,
       f"y aun asi no se sale por abajo ({max(ys):.0f})")

    titulo("cartelas: se valida ANTES de dibujar, con el aviso dicho")
    datos, avisos = cartelas.validar("cifra", {"cifra": "X" * 40, "label": "algo"})
    igual(len(datos["cifra"]), 14, "un campo de mas se recorta a su tope")
    ok(any("cifra" in a for a in avisos), f"y se dice cual: {avisos}")
    faltan, avisos = cartelas.validar("cifra", {"label": "sin numero"})
    ok(faltan is None and avisos, "sin un campo obligatorio no hay cartela")
    lista, avisos = cartelas.validar("enumeracion", {"lineas": ["a", "b", "c", "d", "e", "f"]})
    igual(len(lista["lineas"]), 4, "una lista de mas se recorta al tope")
    pocas, avisos = cartelas.validar("enumeracion", {"lineas": ["a"]})
    ok(pocas is None, "y con menos del minimo no se dibuja")

    titulo("cartelas: el suelo de separacion y el techo")
    escenas = [{"id": f"S{i:03d}"} for i in range(1, 21)]
    # cuatro seguidas: solo puede quedar la primera y la que este a >= 4
    plan = {"S002": {"plantilla": "tesis", "datos": {"texto": "una"}},
            "S003": {"plantilla": "tesis", "datos": {"texto": "otra"}},
            "S004": {"plantilla": "tesis", "datos": {"texto": "otra mas"}},
            "S009": {"plantilla": "tesis", "datos": {"texto": "lejos"}}}
    puestas, avisos = cartelas.repartir(escenas, plan)
    igual(sorted(puestas), ["S002", "S009"],
          "dos cartelas pegadas no pasan: se queda la primera")
    ok(len(avisos) == 2, f"y lo descartado se dice: {avisos}")
    # el techo: 20 planos al 22% son 4
    muchas = {f"S{i:03d}": {"plantilla": "tesis", "datos": {"texto": "x"}}
              for i in range(1, 21, 4)}
    puestas, avisos = cartelas.repartir(escenas, muchas)
    ok(len(puestas) <= 4, f"un video no puede ser mitad texto: {len(puestas)}")

    titulo("cartelas: mismo plan, mismo SVG")
    ficha = {"plantilla": "cita", "datos": {"texto": "Nadie sabia nada",
                                            "quien": "el informe"}}
    uno = cartelas.svg_carta(ficha, paleta, duracion=4.0, semilla=7)
    otro = cartelas.svg_carta(ficha, paleta, duracion=4.0, semilla=7)
    igual(uno, otro, "dos dibujados del mismo plan dan el mismo SVG")

    titulo("cartelas: la capa se escribe y el fondo no lleva letra")
    capa = cartelas.svg_capa(ficha, paleta, duracion=4.0)
    ok(capa.count("<animate") >= 3, "la capa escribe palabra a palabra")
    fondo = cartelas.svg_fondo(paleta)
    ok("<text" not in fondo, "el fondo no lleva ni una letra")
    ok("feTurbulence" in fondo, "pero si textura: no es negro plano")
    # el tamano declarado escala con la peticion, o Edge lo rasteriza pequeno
    ok('width="3072"' in cartelas.svg_fondo(paleta, escala=2),
       "el fondo declara el tamano que se le pide")

    titulo("cartelas: la muestra se dibuja con el mismo codigo que la de verdad")
    catalogo = cartelas.catalogo_plantillas(paleta)
    igual(len(catalogo), len(cartelas.plantillas_elegibles()),
          "hay una muestra por plantilla ELEGIBLE")
    # EL MECANISMO DE RESERVAR SIGUE EN PIE aunque hoy no reserve ninguna: el
    # dia que una plantilla la ponga el motor y no el agente, el catalogo no
    # tiene que ofrecerla, y esto es lo que lo comprueba.
    ok(all(f["id"] not in cartelas.PLANTILLAS_RESERVADAS for f in catalogo),
       "una plantilla reservada no se ofrece para un plano suelto")
    for ficha_c in catalogo:
        ok(ficha_c["svg"].startswith("<svg") and ficha_c["nombre"] and ficha_c["cuando"],
           f"{ficha_c['id']}: nombre, cuando va y muestra dibujada")
    ok("<animate" not in catalogo[0]["svg"],
       "la muestra va escrita del todo: se ve el resultado, no un fotograma al azar")


def prueba_transiciones():
    """El catalogo de shaders, el reparto por ranura y los topes."""
    titulo("transiciones: los catorce shaders de hyperframes estan enteros")
    import shaders_hyperframes
    igual(len(shaders_hyperframes.NOMBRES), 14, "los catorce, ni uno menos")
    for nombre, frag in shaders_hyperframes.FRAGMENTOS.items():
        ok(frag.startswith("precision mediump float;"),
           f"{nombre}: lleva la cabecera de uniformes")
        ok("void main()" in frag and "u_progress" in frag,
           f"{nombre}: es un fragment shader de transicion")
        ok("u_accent" in frag, f"{nombre}: puede tenirse con el acento del video")
    for nombre in shaders_hyperframes.NOMBRES:
        ok(nombre in transiciones.CATALOGO,
           f"{nombre}: esta en el catalogo con su nombre en castellano")
    ok(transiciones.frag_de("fundido"), "y el fundido, que es nuestro, tambien")

    titulo("transiciones: cada ficha dice lo que hace falta para elegir y repartir")
    for tid, ficha in transiciones.CATALOGO.items():
        for clave in ("nombre", "descripcion", "familia", "fuerza", "factor"):
            ok(clave in ficha, f"{tid}: le falta '{clave}'")
        ok(0 <= ficha["fuerza"] <= 3, f"{tid}: fuerza fuera de escala")

    titulo("transiciones: el plan da la RANURA y el render elige cual")
    escenas = [{"id": f"S{i:03d}", "duracion": 5.0,
                "transicion": ["corte", "suave", "acento"][i % 3]}
               for i in range(1, 16)]
    reparto = transiciones.resolver(escenas, {})
    igual(reparto["S001"]["tipo"], "corte",
          "el primer plano nunca encadena: no hay de donde venir")
    # El corte seco se retiro el 20-08-2026 y los planes ya guardados lo traen
    # escrito: se traducen a 'suave' al renderizar, o el video seguiria saliendo
    # a cortes secos hasta volver a planificarlo (que cuesta dinero).
    cortes = [s for s, c in reparto.items() if c["tipo"] == "corte"]
    igual(cortes, ["S001"], "y es el UNICO corte seco del video")
    igual([c["ranura"] for s, c in reparto.items() if s != "S001" and
           escenas[int(s[1:]) - 1]["transicion"] == "corte"][:1], ["suave"],
          "una ranura 'corte' de un plan viejo se renderiza como suave")
    con_shader = [c for c in reparto.values() if c["tipo"] != "corte"]
    ok(con_shader, "y las demas traen su shader")
    ok(all(c["shader"] for c in con_shader), "con el GLSL dentro, listo para pintar")

    titulo("transiciones: determinista, y sin repetir familia seguida")
    otra_vez = transiciones.resolver(escenas, {})
    igual({s: c["tipo"] for s, c in reparto.items()},
          {s: c["tipo"] for s, c in otra_vez.items()},
          "el mismo plan da el mismo reparto: rehacer un clip no descoloca otro")
    familias = [transiciones.CATALOGO[c["tipo"]]["familia"]
                for c in reparto.values() if c["tipo"] != "corte"]
    seguidas = [(a, b) for a, b in zip(familias, familias[1:]) if a == b]
    igual(seguidas, [], f"no se repite familia: {familias}")

    titulo("transiciones: ninguna se come el plano que entra")
    cortas = [{"id": "S001", "duracion": 4.0, "transicion": "corte"},
              {"id": "S002", "duracion": 1.2, "transicion": "acento"}]
    ficha = transiciones.resolver(cortas, {"duracion_transicion": 0.9})["S002"]
    ok(ficha["duracion"] <= 1.2 * transiciones.FRACCION_MAXIMA + 0.001,
       f"un plano de 1,2 s no admite 0,9 s de transicion ({ficha['duracion']})")

    titulo("transiciones: los planes viejos se siguen entendiendo")
    viejas = [{"id": "S001", "duracion": 4.0, "transicion": "corte"},
              {"id": "S002", "duracion": 4.0, "transicion": "flash"},
              {"id": "S003", "duracion": 4.0, "transicion": "fundido"},
              {"id": "S004", "duracion": 4.0, "transicion": "deslizar"}]
    reparto = transiciones.resolver(viejas, {})
    igual(reparto["S002"]["ranura"], "acento", "'flash' era un acento")
    igual(reparto["S003"]["ranura"], "suave", "'fundido' era una suave")
    igual(reparto["S004"]["ranura"], "suave",
          "y 'deslizar', retirada en agosto, tambien: un plan viejo tiene que "
          "poder renderizarse")

    titulo("transiciones: la seleccion se respeta, y nunca deja una ranura vacia")
    solo = transiciones.resolver(escenas, {"transiciones": ["glitch"]})
    usadas = {c["tipo"] for c in solo.values() if c["tipo"] != "corte"}
    ok(usadas <= {"glitch", "fundido"},
       f"con una sola elegida se usa esa (y el fundido de respaldo): {usadas}")
    inventadas = transiciones.elegidas_de({"transiciones": ["no_existe"]})
    igual(sorted(inventadas), sorted(t for t in transiciones.POR_DEFECTO if t != "corte"),
          "un nombre inventado no deja el video sin transiciones: caen las de fabrica")

    titulo("transiciones: la rampa de progreso no repite fotograma")
    pasos = transiciones.progresos(4)
    ok(pasos[0] > 0 and pasos[-1] < 1,
       f"ni 0 (seria el fotograma anterior otra vez) ni 1: {pasos}")
    ok(all(b > a for a, b in zip(pasos, pasos[1:])), "y va siempre hacia delante")

    titulo("transiciones: el acento sale de la paleta del video")
    acento = transiciones.acentos({"linea": "#d8785a"})
    for papel in ("acento", "oscuro", "claro"):
        ok(len(acento[papel]) == 3 and all(0 <= v <= 1 for v in acento[papel]),
           f"{papel}: tres componentes en 0-1, listas para el uniforme")
    ok(acento["oscuro"][0] < acento["acento"][0] < acento["claro"][0],
       "y van de oscuro a claro")
    igual(transiciones.acentos({}), transiciones.acentos({"linea": "no-es-color"}),
          "un color ilegible cae al de respaldo en vez de reventar")


def prueba_sonido():
    """Musica y efectos: el reparto, los tiempos y la mezcla. TODO en seco.

    No sale a la red ni una vez: las fichas se inventan aqui y los ficheros de
    audio se fabrican con numpy. Lo que se comprueba es lo que decide el
    programa -- que suena, cuando y a que nivel --, no que Freesound siga vivo.
    """
    titulo("sonido: los cuatro papeles saben que pedir y como entra")
    for papel, ficha in sonido.PAPELES.items():
        ok(ficha["consultas"] and all(ficha["consultas"]),
           f"{papel}: tiene consultas que hacerle a Freesound")
        ok(len(ficha["consultas"]) > 1,
           f"{papel}: varias consultas, o Freesound devuelve siempre lo mismo")
        dur_min, dur_max = ficha["duracion"]
        ok(0 < dur_min < dur_max, f"{papel}: rango de duracion con sentido")
        ok(0 < ficha["ganancia"] <= 1.0, f"{papel}: ganancia en 0-1")
    ok(sonido.PAPELES["tecla"]["duracion"][1] < 1.0,
       "una tecla es corta por definicion: mas larga no es una tecla")
    ok(sonido.PAPELES["transicion_acento"]["ganancia"]
       > sonido.PAPELES["tecla"]["ganancia"],
       "un golpe de transicion suena mas que una tecla")
    ok(all("adelanto" not in f for f in sonido.PAPELES.values()),
       "ya no hay un adelanto escrito a ojo: lo pone `golpe_de` fichero a fichero")
    ok(0.0 <= sonido.ANCLA_TRANSICION <= 1.0,
       "el ancla del golpe cae dentro de la transicion que se ve")

    titulo("sonido: elegir es determinista, y reparte")
    fichas = [{"fuente": "x", "id": str(i)} for i in range(6)]
    uno = sonido.elegir(fichas, 7, "S001", "tecla")
    igual(sonido.elegir(fichas, 7, "S001", "tecla"), uno,
          "la misma clave da el mismo efecto: dos renders suenan igual")
    distintos = {sonido.elegir(fichas, 7, f"S{i:03d}", "tecla")["id"]
                 for i in range(1, 30)}
    ok(len(distintos) >= 4, f"y planos distintos cogen efectos distintos: {distintos}")
    igual(sonido.elegir([], 7, "S001"), None, "sin surtido no se elige nada")

    titulo("sonido: cuando suena cada cosa")
    escenas = [
        {"id": "S001", "t_in": 2.0, "t_out": 6.0, "duracion": 4.0},
        {"id": "S002", "t_in": 6.0, "t_out": 10.0, "duracion": 4.0},
        {"id": "S003", "t_in": 10.0, "t_out": 15.0, "duracion": 5.0,
         "cartela": {"plantilla": "tesis",
                     "datos": {"texto": "Y entonces dejo de existir"}}},
    ]
    cortes = {"S001": {"tipo": "corte", "ranura": "corte"},
              "S002": {"tipo": "sdf-iris", "ranura": "acento"},
              "S003": {"tipo": "fundido", "ranura": "suave"}}
    surtido = {p: [{"fuente": "prueba", "id": f"{p}{i}"} for i in range(4)]
               for p in sonido.PAPELES}
    lista = sonido.eventos(escenas, cortes, {"efectos": surtido}, semilla=7)
    ok(lista, "deberia sonar algo")
    ok(all(a["t"] <= b["t"] for a, b in zip(lista, lista[1:])),
       "los eventos salen en orden de reloj")
    ok(all(e["t"] >= 0 for e in lista), "y ninguno antes de que empiece el video")

    # el reloj es el del VIDEO MONTADO: el primer plano esta en t=0 aunque su
    # t_in sea 2.0, porque la voz se recorta ahi al montar
    acento = [e for e in lista if e["papel"] == "transicion_acento"]
    igual(len(acento), 1, "un acento, el de S002")
    ok(abs(acento[0]["t"] - 4.0) < 0.01,
       f"y su GOLPE cae en el corte de S002 (transicion de duracion 0 en esta "
       f"prueba, asi que el ancla no lo mueve): {acento[0]['t']}")
    igual([e for e in lista if e["papel"] == "transicion_suave"][0]["papel"],
          "transicion_suave", "el encadenado suave de S003 tambien suena")
    ok(not [e for e in lista if e["t"] < 0.5 and e["papel"].startswith("transicion")],
       "el primer plano no encadena con nada, asi que no suena")

    titulo("sonido: el GOLPE del efecto cae donde la transicion se ve")
    # Lo que se oia: «los efectos no van sincronizados, y no sabria decir si
    # siempre». No era un retraso fijo -- era que el montaje colocaba la PRIMERA
    # MUESTRA del fichero, y un barrido tarda entre 0,05 y 0,90 s en pegar segun
    # cual sea. Medio segundo largo de recorrido, distinto en cada corte porque
    # el efecto lo reparte la semilla.
    banco_efectos = os.path.join(os.environ.get("TEMP", "."),
                                 "estudio_prueba_golpe")
    shutil.rmtree(banco_efectos, ignore_errors=True)
    os.makedirs(banco_efectos, exist_ok=True)

    def _con_golpe_en(ruta, retardo_s, largo_s=1.4):
        """Un WAV que esta callado hasta `retardo_s` y ahi pega."""
        n = int(largo_s * sonido.FRECUENCIA)
        x = np.zeros((n, 2), dtype=np.float32)
        desde = int(retardo_s * sonido.FRECUENCIA)
        x[desde:desde + int(0.12 * sonido.FRECUENCIA)] = 0.9
        sonido._escribir(ruta, x)                                  # noqa: SLF001
        return ruta

    pronto = _con_golpe_en(os.path.join(banco_efectos, "pronto.wav"), 0.05)
    tarde = _con_golpe_en(os.path.join(banco_efectos, "tarde.wav"), 0.90)
    ok(abs(sonido.golpe_de(pronto) - 0.05) < 0.02,
       f"golpe_de encuentra el golpe temprano: {sonido.golpe_de(pronto):.3f}s")
    ok(abs(sonido.golpe_de(tarde) - 0.90) < 0.02,
       f"y el tardio: {sonido.golpe_de(tarde):.3f}s")
    igual(sonido.golpe_de(os.path.join(banco_efectos, "no_existe.wav")), 0.0,
          "un efecto que no esta en el banco da 0 y no revienta: no se mezcla")

    # Y LO QUE IMPORTA: dos ficheros que pegan en momentos MUY distintos tienen
    # que dejar su golpe en el MISMO instante del video. Antes se separaban 0,85s.
    banco_de_verdad, nombre_de_verdad = sonido.banco, sonido._nombre_de
    sonido.banco = lambda *partes: os.path.join(banco_efectos, partes[-1])
    try:
        escenas_t = [{"id": "T001", "t_in": 0.0, "t_out": 4.0, "duracion": 4.0},
                     {"id": "T002", "t_in": 4.0, "t_out": 8.0, "duracion": 4.0}]
        cortes_t = {"T001": {"tipo": "corte", "ranura": "corte"},
                    "T002": {"tipo": "fundido", "ranura": "suave",
                             "duracion": 0.46}}
        golpes = {}
        for nombre in ("pronto.wav", "tarde.wav"):
            crudo = {"fuente": "prueba", "id": nombre[:-4]}
            sonido._nombre_de = lambda f, n=nombre: n              # noqa: SLF001
            lista_t = sonido.eventos(escenas_t, cortes_t,
                                     {"efectos": {"transicion_suave": [crudo]}},
                                     semilla=1)
            evento = [e for e in lista_t if e["papel"] == "transicion_suave"][0]
            golpes[nombre] = evento["t"] + sonido.golpe_de(
                os.path.join(banco_efectos, nombre))
        separacion = abs(golpes["pronto.wav"] - golpes["tarde.wav"])
        ok(separacion < 0.02,
           f"los dos dejan el golpe en el mismo instante ({separacion*1000:.0f} ms "
           f"de diferencia); con la primera muestra se separaban 850 ms")
        esperado = 4.0 + sonido.ANCLA_TRANSICION * 0.46
        ok(abs(golpes["pronto.wav"] - esperado) < 0.02,
           f"y ese instante es el ancla dentro de la transicion visual "
           f"({golpes['pronto.wav']:.3f}s contra {esperado:.3f}s)")
    finally:
        sonido.banco, sonido._nombre_de = banco_de_verdad, nombre_de_verdad
        shutil.rmtree(banco_efectos, ignore_errors=True)

    titulo("sonido: las teclas caen donde se escriben las palabras")
    teclas = [e for e in lista if e["papel"] == "tecla"]
    palabras = cartelas.tiempos_de_escritura(escenas[2]["cartela"], 5.0)
    origen = 10.0 - 2.0                       # t_in de la cartela en el video
    ok(teclas, "una cartela suena a maquina de escribir")
    for cuando, _ in palabras:
        cerca = [e for e in teclas if abs(e["t"] - (origen + cuando)) < 0.5]
        ok(cerca, f"hay pulsaciones alrededor de la palabra en {cuando}s")
    ok(len(teclas) > len(palabras),
       f"y son mas que palabras: se teclea letra a letra "
       f"({len(teclas)} para {len(palabras)} palabras)")
    ok(max(e["t"] for e in teclas) <= origen + 5.0,
       "ninguna tecla suena despues de que acabe su plano")
    volumenes = {round(e["ganancia"], 4) for e in teclas}
    ok(len(volumenes) > 1,
       "las pulsaciones no suenan todas igual: un teclado plano suena a bucle")
    retorno = [e for e in lista if e["papel"] == "retorno"]
    igual(len(retorno), 1, "y al terminar de escribirse, el carro")
    ok(retorno[0]["t"] > max(e["t"] for e in teclas),
       "que va DESPUES de la ultima tecla")

    titulo("sonido: sin surtido no suena nada, y no es un error")
    igual(sonido.eventos(escenas, cortes, {}, 7), [],
          "un video sin efectos traidos se monta igual, en silencio")

    titulo("sonido: la pista se suma en numpy y sale a su pico")
    carpeta = tempfile.mkdtemp(prefix="estudio_sfx_")
    try:
        # un "efecto" fabricado: 0,2 s de tono. Se mete en el banco a mano
        # para no salir a la red.
        muestras = np.zeros((int(0.2 * sonido.FRECUENCIA), 2), dtype=np.float32)
        t = np.arange(len(muestras)) / sonido.FRECUENCIA
        muestras[:, 0] = muestras[:, 1] = 0.8 * np.sin(2 * np.pi * 880 * t)
        falso = {"fuente": "prueba", "id": "tono"}
        # El mp3 PRIMERO y el wav despues, y no al reves: el wav es la cache
        # del mp3 y _a_wav la da por buena solo si es igual de nueva o mas
        # (mtime >=). Con el wav escrito antes, la suite fallaba una de cada
        # tantas -- cuando los dos no caian en el mismo milisegundo --
        # pidiendole a ffmpeg que decodificara 4000 bytes de ceros.
        with open(sonido.banco("efectos", "prueba_tono.mp3"), "wb") as fh:
            fh.write(b"\0" * 4000)            # basta con que exista: el wav manda
        sonido._escribir(sonido.banco("efectos", "prueba_tono.48000.wav"), muestras)

        eventos = [{"t": 1.0, "papel": "tecla", "ficha": falso, "ganancia": 1.0},
                   {"t": 3.0, "papel": "tecla", "ficha": falso, "ganancia": 0.5},
                   # este se sale del video: tiene que recortarse, no reventar
                   {"t": 9.9, "papel": "tecla", "ficha": falso, "ganancia": 1.0}]
        destino = os.path.join(carpeta, "sfx.wav")
        ruta, usados = sonido.pista_de_efectos(eventos, 10.0, destino)
        igual(usados, 3, "los tres eventos entran")
        pista = sonido._leer(ruta)
        igual(len(pista), int(10.0 * sonido.FRECUENCIA),
              "la pista dura exactamente lo que el video")
        pico = 20 * np.log10(max(1e-9, float(np.abs(pista).max())))
        ok(abs(pico - sonido.EFECTOS_PICO_DB) < 0.5,
           f"y sale al pico pedido ({pico:.1f} dBFS, se pedia "
           f"{sonido.EFECTOS_PICO_DB})")
        # donde hay evento hay energia, y donde no, silencio
        def energia(seg):
            a = int(seg * sonido.FRECUENCIA)
            return float(np.abs(pista[a:a + int(0.2 * sonido.FRECUENCIA)]).max())
        ok(energia(1.0) > 0.01, "suena en el primer evento")
        ok(energia(3.0) > 0.01, "y en el segundo")
        ok(energia(5.0) < 1e-6, "y calla donde no hay ninguno")
        ok(energia(3.0) < energia(1.0),
           "el de media ganancia suena menos que el de ganancia entera")

        vacia, cuantos = sonido.pista_de_efectos([], 4.0,
                                                 os.path.join(carpeta, "v.wav"))
        igual(cuantos, 0, "sin eventos no se usa ninguno")
        ok(float(np.abs(sonido._leer(vacia)).max()) == 0.0,
           "y la pista sale muda en vez de fallar")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
        for resto in ("prueba_tono.48000.wav", "prueba_tono.mp3"):
            try:
                os.remove(sonido.banco("efectos", resto))
            except OSError:
                pass

    titulo("sonido: el grafo de mezcla dice lo que tiene que decir")
    grafo = sonido.filtro_de_mezcla(True, True, 42.0)
    ok("sidechaincompress" in grafo, "la musica se agacha bajo la voz")
    ok("loudnorm=I=-23" in grafo, "y va normalizada a -23 LUFS")
    ok("normalize=0" in grafo,
       "amix NO reparte volumen: con normalize=1 la voz sonaria a un tercio "
       "por el hecho de haber puesto musica")
    ok("alimiter" in grafo,
       "y detras un limitador: las tres pistas se suman y se pasan de cero")
    ok("atrim=0:42.000" in grafo,
       "las tres se recortan al mismo largo, o el amix de una musica en bucle "
       "no termina nunca")
    igual(grafo.count("amix"), 1, "una sola mezcla")
    solo_voz = sonido.filtro_de_mezcla(False, False, 10.0)
    ok("amix=inputs=1" in solo_voz, "sin musica ni efectos queda la voz sola")
    ok("sidechaincompress" not in solo_voz, "y sin nada que agachar")
    ok("[3:a]" in grafo and "[3:a]" not in sonido.filtro_de_mezcla(False, True, 10.0),
       "las entradas se numeran segun lo que haya: sin musica, los efectos "
       "entran por la 2 y no por la 3")

    titulo("sonido: se describe solo, para la pantalla y para p8.describir")
    ok("sin música" in sonido.describir({"sonido": False}),
       "apagado lo dice")
    frase = sonido.describir({"musica": {"id": "1", "titulo": "Tema",
                                         "artista": "Alguien"},
                              "efectos": {"tecla": [1, 2, 3]}})
    ok("Tema" in frase and "3 efectos" in frase, f"y puesto tambien: {frase}")

    titulo("sonido: el efecto que no gusta se VETA, y el veto es del canal")
    # «De forma recurrente suena un sonido que es como una especie de laser que
    # no me gusta nada». Borrar su fichero del banco no sirve: Freesound ordena
    # por descargas y la siguiente busqueda lo vuelve a bajar.
    guardados = dict(sonido.vetados())
    try:
        for clave in guardados:                # se parte de la lista vacia
            sonido.desvetar(clave)
        laser = {"fuente": "prueba", "id": "laser", "titulo": "Laser sweep",
                 "papel": "transicion_acento"}
        surtido = [{"fuente": "prueba", "id": str(i)} for i in range(5)]
        surtido.insert(2, laser)
        antes = {sid: (sonido.elegir(surtido, 7, sid, "t") or {}).get("id")
                 for sid in [f"S{i:03d}" for i in range(1, 40)]}
        ok(laser["id"] in antes.values(), "sin veto, el laser suena en algun corte")

        sonido.vetar(laser, papel="transicion_acento", motivo="no me gusta")
        ok(sonido.esta_vetado(laser), "vetado queda vetado")
        ok(sonido.esta_vetado({"fuente": "prueba", "id": "laser"}),
           "y se reconoce por fuente+id, no por el papel: un laser vetado como "
           "golpe tampoco vuelve como aire")
        despues = {sid: (sonido.elegir(surtido, 7, sid, "t") or {}).get("id")
                   for sid in antes}
        ok(laser["id"] not in despues.values(),
           "y deja de sonar YA, sin volver a surtir ni pagar otra busqueda")
        movidos = [sid for sid in antes if antes[sid] != despues[sid]]
        igual(sorted(movidos),
              sorted(sid for sid in antes if antes[sid] == laser["id"]),
              "y SOLO cambian los cortes que sonaban a laser: vetar uno quita "
              "uno, no rebaraja el video entero")
        igual(sonido.elegir([laser], 7, "S001", "t"), None,
              "si todo lo que hay esta vetado, ese hueco se queda mudo en vez "
              "de colar el vetado")
        ok(os.path.exists(sonido.banco("efectos")),
           "y el banco sigue ahi: un veto no borra ficheros, porque borrarlos "
           "solo consigue que la proxima busqueda los baje otra vez")
        ficha_v = sonido.vetados()[sonido.clave_de(laser)]
        ok(ficha_v.get("fecha") and ficha_v.get("titulo") == "Laser sweep",
           f"y se guarda con titulo y fecha, para poder leerlo meses despues: {ficha_v}")
        ok(sonido.desvetar(laser), "se puede levantar")
        ok(not sonido.esta_vetado(laser), "y entonces vuelve a entrar")
        igual(sonido.desvetar(laser), False, "levantarlo dos veces no hace nada")
        fallo_v = None
        try:
            sonido.vetar({"titulo": "sin id"})
        except ValueError as choque:
            fallo_v = str(choque)
        ok(fallo_v, f"un efecto sin fuente ni id no se puede vetar: {fallo_v}")

        titulo("sonido: lo AGUDO de un efecto, para encontrar el laser")
        # Identificar «ese que suena como una especie de laser» entre doce
        # efectos es escucharlos los doce. Un laser es filo y un aire de
        # transicion es cuerpo, asi que la energia por encima de 4 kHz los
        # ordena. No decide nada: pone el candidato arriba.
        igual(sonido.agudeza({"fuente": "prueba", "id": "no_esta"}), None,
              "un efecto que no esta en el banco no tiene medida, y no revienta")
        hz = np.arange(int(0.3 * sonido.FRECUENCIA)) / sonido.FRECUENCIA
        for nombre, frecuencia in (("agudo", 9000.0), ("grave", 300.0)):
            onda = np.zeros((len(hz), 2), dtype=np.float32)
            onda[:, 0] = onda[:, 1] = 0.7 * np.sin(2 * np.pi * frecuencia * hz)
            with open(sonido.banco("efectos", f"prueba_{nombre}.mp3"), "wb") as fh:
                fh.write(b"\0" * 4000)
            sonido._escribir(sonido.banco("efectos", f"prueba_{nombre}.48000.wav"), onda)
        filo = sonido.agudeza({"fuente": "prueba", "id": "agudo"})
        cuerpo = sonido.agudeza({"fuente": "prueba", "id": "grave"})
        ok(filo is not None and filo > 0.9,
           f"un tono de 9 kHz sale casi todo agudo: {filo}")
        ok(cuerpo is not None and cuerpo < 0.1,
           f"y uno de 300 Hz casi nada: {cuerpo}")
        ok(filo > cuerpo, "asi que ordenar por esto pone el filo delante")
        igual(sonido.agudeza({"fuente": "prueba", "id": "agudo"}), filo,
              "y se cachea: la pantalla de Sonido lo pide en cada carga")
        # el banco es del USUARIO: esta suite escribe en el de verdad, asi que
        # se lleva lo suyo al salir
        for nombre in ("prueba_agudo", "prueba_grave"):
            for extension in (".mp3", ".48000.wav"):
                medios.borrar(sonido.banco("efectos", nombre + extension))
    finally:
        # se devuelve el fichero del canal tal y como estaba: esta suite no
        # puede dejarle al usuario un veto puesto ni quitarle uno suyo
        sonido._guardar_vetados(guardados)


# AQUI SE PROBABA «mirar»: que un informe de la revision de imagenes no pudiera
# dejar obsoleto ningun plano --si lo dejara, mirar una imagen pediria volver a
# pagarla--. Se retiro entera el 24-08-2026 con el resto del modulo.


def prueba_subtitulos():
    """El subtitulo: la narracion, troceada por clausula y con su hora exacta.

    Sustituye a los rotulos. Lo que se prueba aqui es la
    propiedad que lo hace fiable: los tiempos salen de INDICES de palabra, no de
    volver a contar el texto, asi que limpiar una cifra no puede desplazar nada.
    """
    titulo("subtitulos: se trocea por clausula, y en indices")
    frase = "Spain, May of twenty twenty-four, and nobody knew yet."
    partes = subtitulos.tramos(frase.split())
    ok(partes[0][0] == 0 and partes[-1][1] == len(frase.split()),
       f"los rangos cubren la frase entera: {partes}")
    for uno, otro in zip(partes, partes[1:]):
        igual(uno[1], otro[0], "y encajan sin solaparse ni dejar hueco")
    larga = " ".join(["palabra"] * 40)
    ok(all(len(" ".join(larga.split()[a:b])) <= subtitulos.CAP_TROZO
           for a, b in subtitulos.tramos(larga.split())),
       "ningun trozo pasa de dos lineas: tres tapan el plano")
    corto = subtitulos.tramos("Vale, si.".split())
    igual(len(corto), 1,
          "y un huerfano se funde con su vecino en vez de parpadear solo")

    titulo("subtitulos: la hora sale de las marcas, no de recontar")
    escena = {"id": "S001", "t_in": 10.0, "t_out": 14.0,
              "narracion": "Thirty million accounts, and nobody said a word.",
              "marcas": [[10.0, 10.4], [10.4, 10.9], [10.9, 11.5], [11.6, 11.8],
                         [11.8, 12.2], [12.2, 12.6], [12.6, 12.8], [12.8, 13.4]]}
    trozos = subtitulos.de_escena(escena, idioma="en")
    ok(trozos, f"sale subtitulo: {[x['texto'] for x in trozos]}")
    igual(trozos[0]["desde"], 0.0, "el primero arranca con su primera palabra")
    igual(round(trozos[-1]["hasta"], 2), 3.4,
          "y el ultimo acaba con la ultima, en el reloj del plano")
    ok(all(x["hasta"] >= x["desde"] for x in trozos), "ninguno va del reves")

    titulo("subtitulos: una cifra dicha se escribe en cifra, y NO mueve la hora")
    igual(subtitulos.limpiar_texto("Thirty million accounts".split(), "en"),
          "30 million accounts",
          "«thirty million» se lee mejor escrito «30 million»")
    igual(subtitulos.limpiar_texto("Around one hundred sixty-five companies".split(), "en"),
          "Around 165 companies",
          "y una cifra compuesta entera: en pantalla se lee de un vistazo")
    igual(subtitulos.limpiar_texto("May of twenty twenty-four".split(), "en"),
          "May of 2024",
          "EL ANO EN DOS MITADES sale con sus cuatro cifras: el parser general "
          "lo sumaria y daria 44, asi que tiene su propio reconocedor")
    igual(subtitulos.limpiar_texto("nineteen eighty-four".split(), "en"),
          "1984", "y en cualquier siglo de la horquilla")
    igual(subtitulos.limpiar_texto("twenty five people".split(), "en"),
          "25 people",
          "pero «twenty five» NO es el ano 2005: la segunda mitad de un ano "
          "tiene que valer diez o mas")
    igual(subtitulos.limpiar_texto("UNC five five three seven.".split(), "en"),
          "UNC 5537.",
          "LA SERIE DE DIGITOS es un identificador dictado, no una suma: el "
          "parser general devolveria 20")
    igual(subtitulos.limpiar_texto("two, three, four times".split(), "en"),
          "two, three, four times",
          "y una coma la parte: son tres cosas, no el numero 234")
    igual(subtitulos.limpiar_texto("four percent of the total".split(), "en"),
          "4% of the total", "el porcentaje se escribe como se escribe")
    igual(subtitulos.limpiar_texto("two systems went down".split(), "en"),
          "two systems went down",
          "ni una cifra pequena: «2 systems» no se lee mejor")
    igual(subtitulos.limpiar_texto("six out of ten companies".split(), "en"),
          "6 out of 10 companies",
          "salvo que la acompane otra que si se convierte: «six out of 10» "
          "no lo escribe nadie")
    igual(subtitulos.limpiar_texto(
              "En dos mil veinticuatro, treinta millones de cuentas.".split(), "es"),
          "En 2024, 30 millones de cuentas.",
          "en castellano igual, y la coma cierra el primer numero: sin eso los "
          "dos se leian como uno solo y salia «2054 millones»")

    # LOS ORDINALES, que el parser general no ve: 'fifth' no es una unidad, asi
    # que se quedaba en letra al lado de un 2026 ya en cifra («On August fifth,
    # 2026»). Y un compuesto ademas se partia por la mitad, porque su primera
    # palabra SI es una unidad ('twenty' -> 20).
    igual(subtitulos.limpiar_texto(
              "On August fifth, 2026, he pleads guilty.".split(), "en"),
          "On August 5th, 2026, he pleads guilty.",
          "un ordinal detras de un mes es una fecha y va en cifra")
    igual(subtitulos.limpiar_texto("Sentencing, October twenty-seventh.".split(),
                                   "en"),
          "Sentencing, October 27th.",
          "y un compuesto entero, no «October 20 seventh»")
    igual(subtitulos.limpiar_texto("On June second, Snowflake signs".split(), "en"),
          "On June 2nd, Snowflake signs",
          "con el sufijo que le toca a cada uno: 2nd, no 2th")
    igual(subtitulos.limpiar_texto(
              "May thirtieth, twenty twenty-four.".split(), "en"),
          "May 30th, 2024.",
          "y conviven con el ano dicho en dos mitades, sin pisarse")
    # DONDE NO, que pesa igual: 'second' es tambien la unidad de tiempo y
    # 'first/second/third' viven casi siempre dentro de una frase, no de una
    # fecha. Se vio en este mismo video: «the second step switched on».
    igual(subtitulos.limpiar_texto(
              "the second step was not switched on".split(), "en"),
          "the second step was not switched on",
          "un ordinal pequeno SUELTO no es una cifra: «the 2nd step» no")
    igual(subtitulos.limpiar_texto("It was the thirtieth time".split(), "en"),
          "It was the 30th time",
          "de diez para arriba si, con la misma doctrina que las cifras sueltas")
    # Y EN CASTELLANO UNA FECHA NO LLEVA ORDINAL: se dice «el cinco de agosto»,
    # con cardinal, y ese cinco se quedaba en letra por ser menor que diez.
    igual(subtitulos.limpiar_texto(
              "El cinco de agosto de dos mil veintiseis.".split(), "es"),
          "El 5 de agosto de 2026.",
          "en castellano lo que se reconoce es el DIA pegado a «de <mes>»")
    igual(subtitulos.limpiar_texto("el segundo paso no estaba puesto".split(),
                                   "es"),
          "el segundo paso no estaba puesto",
          "y un ordinal castellano suelto tampoco se convierte")

    # LA PALABRA DEBIL, que es donde estaba el fallo mas caro de este modulo
    # (PENDIENTE 40). «un», «una», «a», «one» valen 1 en la tabla, y se SUMABAN
    # al numero de al lado: cinco subtitulos del video del oro decian una cifra
    # distinta de la que se estaba oyendo. La regla buena estaba escrita en
    # `_DEBILES` desde el primer dia y no se habia implementado nunca.
    titulo("subtitulos: una palabra debil no se suma a la cifra de al lado")
    for dicho, escrito in (("un dos por ciento de las reservas", "un 2% de las reservas"),
                           ("en torno a tres por ciento", "en torno a 3%"),
                           ("un cuatro por ciento", "un 4%"),
                           ("un cinco por ciento", "un 5%"),
                           ("un cuatrocientos ochenta por ciento", "un 480%")):
        igual(subtitulos.limpiar_texto(dicho.split(), "es"), escrito,
              f"«{dicho}» se escribe «{escrito}», no sumandole el articulo")
    igual(subtitulos.limpiar_texto("a un decimo de onza".split(), None),
          "a un decimo de onza",
          "y dos debiles seguidas tampoco: «a un decimo» salia «2 10» -- el "
          "«a» ingles vale 1 y el «un» castellano tambien")
    igual(subtitulos.limpiar_texto("un millon de cuentas".split(), "es"),
          "1 millon de cuentas",
          "pero delante de un MULTIPLICADOR la debil si es el numero")
    igual(subtitulos.limpiar_texto("a hundred and sixty-five companies".split(), "en"),
          "165 companies", "«a hundred» sigue siendo 100")
    igual(subtitulos.limpiar_texto("one of the systems failed".split(), "en"),
          "one of the systems failed",
          "y una debil que no lleva nada detras no es una cifra")

    # LO QUE QUEDABA: cuando la debil ES el numero. Saltarla dejaba la cola
    # huerfana y «ciento» se leia como el 100 pelado. Reales: S072 y S083.
    titulo("subtitulos: una debil delante de «por ciento» SI es la cifra")
    igual(subtitulos.limpiar_texto("un uno por ciento al ano".split(), "es"),
          "un 1% al ano", "«un uno por ciento» es 1 %, no «un uno por 100»")
    igual(subtitulos.limpiar_texto("un uno y medio por ciento".split(), "es"),
          "un 1,5%", "y con la mitad dicha, 1,5 % -- con la coma castellana")
    igual(subtitulos.limpiar_texto("one and a half percent".split(), "en"),
          "1.5%",
          "en ingles la mitad lleva articulo por medio («and A half»), que "
          "ademas esta en la tabla de debiles: sin verlo salia 2")
    igual(subtitulos.limpiar_texto("one and a half million dollars".split(), "en"),
          "1.5 million dollars",
          "y el multiplicador se conserva dicho, como cualquier otra cifra")
    igual(subtitulos.limpiar_texto("dos y medio por ciento".split(), "es"),
          "2,5%", "la mitad no necesita que delante haya una debil")
    igual(subtitulos.limpiar_texto("medio segundo despues".split(), "es"),
          "medio segundo despues",
          "pero «medio» suelto no es media unidad de nada: solo cuenta detras "
          "de un numero y de su enlace")

    # LOS HERMANOS DE LA MISMA FAMILIA: una cifra en pantalla que la voz no
    # dice. Salieron al medir el arreglo de arriba, y los tres son de siempre.
    titulo("subtitulos: ninguna cifra que no se oiga")
    igual(subtitulos.limpiar_texto("treinta y uno de agosto".split(), "es"),
          "31 de agosto",
          "el dia de una fecha no se lleva la cola de un numero mayor: salia "
          "«treinta y 1 de agosto» porque esa regla corre antes que el parser")
    igual(subtitulos.limpiar_texto("el cinco de agosto de dos mil veintiseis".split(),
                                   "es"),
          "el 5 de agosto de 2026", "y la fecha normal sigue saliendo igual")
    igual(subtitulos.limpiar_texto("millones de personas".split(), "es"),
          "millones de personas",
          "un multiplo en PLURAL y sin cifra delante es una cantidad "
          "indefinida: «1000000 de personas» no lo dice nadie")
    igual(subtitulos.limpiar_texto("treinta millones de personas".split(), "es"),
          "30 millones de personas", "con cifra delante, intacto")
    igual(subtitulos.limpiar_texto("por ciento al ano".split(), "es"),
          "por ciento al ano",
          "y una COLA huerfana no es un 100: `limpiar_texto` corre por trozo y "
          "`tramos` puede cortar entre «cuatro» y «por ciento»")
    igual(subtitulos.limpiar_texto("por ciento veinte euros".split(), "es"),
          "por 120 euros", "solo si la cola es todo el tramo: 120 sigue siendo 120")

    # Y SIN IDIOMA, QUE ES EL CASO DE VERDAD. `subtitulos.de_escena` lo recibe
    # de `p7.p.get("idioma")` y los params de callouts NO tienen esa clave: al
    # dibujar el video llega None siempre. La primera version de esto miraba el
    # idioma que le pasaran y en el MP4 salio «On August 5, 2026» sin el sufijo.
    # Ahora el idioma lo pone la palabra encontrada: 'fifth' solo esta en la
    # tabla inglesa.
    igual(subtitulos.limpiar_texto(
              "On August fifth, 2026, he pleads guilty.".split(), None),
          "On August 5th, 2026, he pleads guilty.",
          "sin idioma declarado el sufijo sigue siendo el que toca")
    igual(subtitulos.limpiar_texto(
              "El cinco de agosto de dos mil veintiseis.".split(), None),
          "El 5 de agosto de 2026.",
          "y una fecha castellana sigue saliendo con cardinal pelado")
    # LA PROPIEDAD QUE LO SOSTIENE: limpiar cambia el numero de palabras
    # («Thirty million» -> «30 million» son dos, pero «six million» -> «6
    # million» tambien), y aun asi los tiempos no se mueven ni un milisegundo,
    # porque salen del INDICE de la marca y no de recontar el texto dibujado.
    crudo = subtitulos.de_escena(dict(escena), idioma=None)
    igual([x["desde"] for x in crudo], [x["desde"] for x in trozos],
          "con cifra o sin ella, los mismos instantes: el tiempo sale del "
          "indice de palabra, no del texto")

    # EL SUBTITULO ESCRITO A MANO (PENDIENTE 38). Hasta el 28-08-2026 no habia
    # forma de corregir una palabra ESCRITA: lo mas cercano era `bloque_texto`,
    # que reescribe el guion y regenera voz, corte, assets, cartelas y montaje.
    titulo("subtitulos: lo escrito a mano manda, y NO mueve ni un milisegundo")
    escrito = subtitulos.de_escena(dict(escena), idioma="en",
                                   texto="Thirty million accounts, and nobody spoke.")
    igual([x["desde"] for x in escrito], [x["desde"] for x in trozos],
          "los tiempos son los mismos: salen del INDICE de la marca, y el "
          "override entra DESPUES de trocear")
    igual(" ".join(x["texto"] for x in escrito),
          "Thirty million accounts, and nobody spoke.",
          "y lo que se lee es EXACTAMENTE lo que se escribio: ni una palabra "
          "se pierde al repartirlo entre los trozos")
    igual(subtitulos.repartir_escrito(["un uno por 100 al"], "un 1% al"),
          ["un 1% al"], "con un solo trozo, el texto entero es ese trozo")
    igual(subtitulos.repartir_escrito(["se pagaba un uno por 100", "al ano, cada ano"],
                                      "se pagaba un 1% al ano, cada ano"),
          ["se pagaba un 1%", "al ano, cada ano"],
          "y con dos, cada palabra se queda en el trozo donde ya estaba: se "
          "reparte ALINEANDO, no por proporcion")
    igual(subtitulos.repartir_escrito(["lo de arriba", "lo de abajo"], ""),
          ["lo de arriba", "lo de abajo"],
          "sin texto no se toca nada: un override vacio no es un borrado")
    corto = subtitulos.de_escena(dict(escena), idioma="en", texto="30M.")
    ok(len(corto) == 1 and corto[0]["texto"] == "30M.",
       "un override mas corto que lo que sustituye deja trozos vacios, y un "
       "trozo vacio no se dibuja en vez de parpadear en blanco")

    titulo("subtitulos: sin marcas que cuadren, NO hay subtitulo")
    igual(subtitulos.de_escena({"narracion": "tres palabras aqui",
                                "marcas": [[0.0, 1.0]], "t_in": 0.0}), [],
          "una narracion de tres palabras con una sola marca no se finge: sin "
          "subtitulo antes que con uno desplazado")
    igual(subtitulos.de_escena({"narracion": "", "marcas": [], "t_in": 0.0}), [],
          "y un plano sin narracion no lleva ninguno")

    titulo("subtitulos: dos lineas parejas, que centradas se notan")
    ancho = lambda s: len(s) * 10.0                            # noqa: E731
    igual(subtitulos.dos_lineas("una sola linea", ancho, 1000), ["una sola linea"],
          "lo que cabe va en una")
    arriba, abajo = subtitulos.dos_lineas(
        "went up for sale for two million dollars today", ancho, 260)
    ok(abs(ancho(arriba) - ancho(abajo)) < 120,
       f"y lo que no, se parte por la mitad: «{arriba}» / «{abajo}»")
    ok(len(subtitulos.dos_lineas(" ".join(["x"] * 60), ancho, 100)) == 2,
       "nunca tres lineas, por larga que sea")

    titulo("subtitulos: la banda es el PIE DEL CUADRO DE SALIDA")
    # Aqui se comprobaba la interseccion de las regiones seguras de todos los
    # planos, que existia porque la capa iba dentro del zoom. Fuera del zoom no
    # hay nada que intersecar y la deriva es cero por construccion, no por
    # calculo (PENDIENTE 38).
    banda = subtitulos.banda_fija(1920, 1080, margen=72, ancho_maximo=1400)
    igual(banda["suelo"], 1008.0, "el suelo es el alto menos el margen")
    igual(banda["centro"], 960.0, "y el centro es el centro del cuadro")
    igual(banda["ancho"], 1400.0, "el ancho lo topa el maximo pedido")
    estrecha = subtitulos.banda_fija(800, 600, margen=72, ancho_maximo=1400)
    igual(estrecha["ancho"], 656.0,
          "y en un cuadro mas estrecho manda el cuadro, no el tope")
    ok(subtitulos.banda_fija()["suelo"] < 1080,
       "la banda siempre cae dentro del cuadro")


def prueba_encajar_mide_el_ancho():
    """El fallo que sacaba la cifra del cuadro: solo se medía el ALTO.

    Con un texto que no se puede partir -- «30.000.000», una palabra larga --
    `partir` devuelve UNA linea igual de larga pase lo que pase (mete siempre la
    primera palabra aunque no quepa). El alto cuadraba, se daba por bueno, y el
    numero se salia por los dos lados. Se vio en el video.
    """
    titulo("tipografia: encajar mide el ancho de cada linea, no solo el alto")
    for texto in ("30.000.000", "SUPERCALIFRAGILISTICOESPIALIDOSO", "165+"):
        lineas, tam = tipografia.encajar(texto, "Verdana", 176, True, 0,
                                         500, 900, minimo=20)
        anchos = [tipografia.medir(l, "Verdana", tam, True, 0)[0] for l in lineas]
        ok(max(anchos) <= 500,
           f"'{texto}' cabe de ancho a {tam}px ({max(anchos)} <= 500)")

    titulo("tipografia: y respeta el tope de renglones")
    largo = "una frase con unas cuantas palabras dentro para que tenga que partirse"
    for tope in (1, 2, 3):
        lineas, _ = tipografia.encajar(largo, "Verdana", 80, True, 0, 700, 900,
                                       minimo=10, lineas_max=tope)
        ok(len(lineas) <= tope, f"con lineas_max={tope} salen {len(lineas)}")

    titulo("tipografia: prueba primero a meterlo en UNA linea")
    corta, tam_c = tipografia.encajar_pocas_lineas(
        "de la facturacion anual global", "Verdana", 46, False, 2, 700, 200)
    igual(len(corta), 1, f"un pie normal cabe de un renglon a {tam_c}px")
    # y si de verdad no cabe en una a tamano legible, admite la segunda
    imposible = ("una etiqueta larguisima que no hay manera de meter en un solo "
                 "renglon por mucho que se encoja sin dejarla ilegible")
    dos, _ = tipografia.encajar_pocas_lineas(imposible, "Verdana", 46, False, 0,
                                             700, 400)
    ok(len(dos) <= 2, f"y como mucho dos: {len(dos)}")


def prueba_cartelas_composicion():
    """Aire, cifras abreviadas solo si hace falta, e iconos de catalogo cerrado."""
    paleta = {"texto": "#ece7dc", "tenue": "#c9c2b4", "linea": "#d8a657",
              "sombra": "#1b1710", "acento": "#d8785a"}

    titulo("cartelas: la cifra se abrevia SOLO cuando no cabe")
    igual(cartelas.acortar_numero("30.000.000"), "30M",
          "una cifra larga tiene forma corta")
    for intacto in ("$2M", "4%", "165+", "10 TONELADAS", "900"):
        igual(cartelas.acortar_numero(intacto), intacto,
              f"'{intacto}' se queda como esta: ahi el texto ya dice algo")
    # el dibujado: la que cabe entera sale entera, la que no, abreviada
    ancho = int((cartelas.SEGURO[2] - cartelas.SEGURO[0]) * cartelas.AIRE_TITULAR)
    corta, _ = cartelas._cifra_encajada("4%", "Verdana", 176, ancho, 400, 64)
    igual(corta, ["4%"], "una cifra corta no se toca")
    entera, _ = cartelas._cifra_encajada("30.000.000", "Verdana", 176, ancho,
                                         400, 64)
    igual(entera, ["30.000.000"],
          "con el cuadro entero para ella cabe, y se queda entera")
    # en `contraste` cada lado tiene la mitad menos el margen de la raya: ahi no
    columna = (cartelas.SEGURO[2] - cartelas.SEGURO[0]) // 2 - cartelas.MARGEN_COLUMNA
    larga, tam_l = cartelas._cifra_encajada("30.000.000", "Verdana", 110, columna,
                                            230, 44)
    igual(larga, ["30M"], "en media columna no cabe, y ahi si se abrevia")
    ok(tam_l >= 110 * cartelas.ENCOGIDO_ACEPTABLE,
       f"a cambio se dibuja grande ({tam_l}px de 110)")

    titulo("cartelas: nada se sale del cuadro, ni con los textos que fallaron")
    duros = [
        {"plantilla": "contraste", "datos": {
            "izq_valor": "30.000.000", "izq_label": "customer accounts for sale",
            "der_valor": "$2M", "der_label": "the asking price"}},
        {"plantilla": "tesis", "datos": {
            "texto": "A password alone was the whole lock"}},
        {"plantilla": "cifra", "datos": {
            "cifra": "4%", "label": "of global annual revenue",
            "nota": "Hundreds of millions of euros in fines"}},
        {"plantilla": "definicion", "datos": {
            "termino": "Infostealer",
            "texto": "Programa que roba en silencio las contrasenas guardadas"}},
    ]
    bx, by, bx2, by2 = cartelas.BANDA
    for ficha in duros:
        svg = cartelas.svg_carta(ficha, paleta, duracion=4.5)
        ys = [float(m) for m in re.findall(r'<text[^>]*\sy="(-?[\d.]+)"', svg)]
        fuera = [y for y in ys if y < by - 1 or y > by2 + 1]
        igual(fuera, [], f"{ficha['plantilla']}: nada se escribe fuera de la banda")
        ok(ys, f"{ficha['plantilla']}: y algo se escribe")

    titulo("cartelas: los titulares no pasan de dos renglones")
    svg = cartelas.svg_carta(
        {"plantilla": "tesis",
         "datos": {"texto": "A password alone was the whole lock"}},
        paleta, duracion=4.5)
    igual(svg.count("<text"), cartelas.LINEAS_TITULAR,
          "la frase que fallaba cabe en dos, no en tres")

    titulo("cartelas: los iconos son un catalogo CERRADO")
    ok(len(cartelas.ICONOS) >= 12, f"hay unos cuantos: {len(cartelas.ICONOS)}")
    for nombre, trazo in cartelas.ICONOS.items():
        ok(trazo.startswith("M") and len(trazo) > 10,
           f"{nombre}: es un path de verdad")
    trazo = cartelas.ICONOS["candado"]
    con = cartelas.svg_carta({"plantilla": "tesis",
                              "datos": {"texto": "Hola", "icono": "candado"}},
                             paleta, duracion=4.0)
    ok(trazo in con, "una cartela con icono dibuja SU trazo")
    sin = cartelas.svg_carta({"plantilla": "tesis", "datos": {"texto": "Hola"}},
                             paleta, duracion=4.0)
    ok(trazo not in sin, "y sin icono no dibuja ninguno")
    datos, avisos = cartelas.validar("tesis", {"texto": "x", "icono": "inventado"})
    ok("icono" not in datos and avisos,
       f"un icono que no existe se descarta y se dice: {avisos}")

    titulo("cartelas: los ejemplos estan bien escritos en su idioma")
    # el agente los IMITA: con los ejemplos sin acentuar escribia «DIAS» y
    # «ANOS» en pantalla
    juntos = " ".join(str(v) for f in cartelas.PLANTILLAS.values()
                      for v in f["ejemplo"].values() if isinstance(v, str))
    ok(any(c in juntos for c in "áéíóúñ¿"),
       "llevan tildes, enyes y signos de apertura")


def prueba_cartelas_dos_fondos():
    """TODAS van sobre la imagen del plano, y el velo aterriza con la voz."""
    titulo("cartelas: todas van sobre la imagen del plano")
    # Decision del canal (21-08-2026, noche): todas sobre imagen, para que el
    # montaje no se pare. El fondo negro no se borra --se sigue dibujando y
    # `sin_imagen` lo sigue distinguiendo-- pero nadie lo elige.
    negra = {"cartela": {"plantilla": "tesis", "fondo": "negro",
                         "datos": {"texto": "Hola"}}}
    encima = {"cartela": {"plantilla": "tesis", "fondo": "imagen",
                          "datos": {"texto": "Hola"}}}
    ok(cartelas.es_cartela(negra) and cartelas.es_cartela(encima),
       "las dos son cartelas")
    ok(cartelas.TODAS_SOBRE_IMAGEN, "y hoy todas van sobre imagen")
    igual(cartelas.fondo_de({"fondo": "negro"}), "imagen",
          "hasta una que pida negro: el plano se sigue viendo detras")
    ok(cartelas.sobre_imagen(negra) and cartelas.sobre_imagen(encima),
       "las dos van sobre el plano")
    ok(not cartelas.sin_imagen(negra) and not cartelas.sin_imagen(encima),
       "y las dos generan imagen: una cartela ya no ahorra un plano, lo remata")
    ok(not cartelas.es_cartela({}), "un plano normal no es cartela")

    titulo("cartelas: el velo ATERRIZA con la primera palabra")
    # Antes iba a su aire: cerraba en 0,63 s mientras el texto arrancaba en
    # 0,22, asi que las primeras palabras se escribian sobre la imagen limpia.
    import re as _re
    for primera in (0.22, 1.08, 2.4):
        capa = cartelas.svg_capa(encima["cartela"], duracion=6.0,
                                 tiempos=[primera, primera + 0.4])
        rect = capa[capa.index('fill="url(#ct-velo)"'):][:500]
        m = _re.search(r'begin="([\d.]+)s" dur="([\d.]+)s"', rect)
        if not ok(m, "el velo trae su entrada"):
            continue
        ini, dur = float(m.group(1)), float(m.group(2))
        ok(ini > 0, f"se ve el plano LIMPIO un momento antes ({ini:.2f}s)")
        ok(abs((ini + dur) - primera) < 0.02,
           f"y esta cerrado cuando entra la primera palabra ({ini + dur:.2f} "
           f"contra {primera})")
    capa = cartelas.svg_capa(encima["cartela"], duracion=4.0)
    rect = capa[capa.index('fill="url(#ct-velo)"'):][:500]
    ok('opacity="0"' in rect,
       f"empieza invisible, nunca puesto de inicio ({rect[:110]})")
    ok(f'to="{cartelas.VELO}"' in rect,
       f"y llega al velo que deja leer el texto ({cartelas.VELO})")
    # LA SEGUNDA MITAD no vuelve a fundir: seria un destello de imagen limpia
    # en mitad de la cabecera, en cada corte interno del tramo
    sigue = cartelas.svg_capa(encima["cartela"], duracion=4.0,
                              tiempos=[0.5], escrita=True)
    rect_s = sigue[sigue.index('fill="url(#ct-velo)"'):][:500]
    ok("<animate" not in rect_s,
       "la continuacion arranca con el velo YA puesto, sin refundirlo")
    ok(f'opacity="{cartelas.VELO}"' in rect_s,
       "y con la imagen ya oscurecida desde el fotograma cero")


def prueba_reloj_de_cartela():
    """EL FALLO DE LA LISTA: el «02» y el «03» llegaban al final de la escena.

    Visto en el video montado, en la cabecera de los tres bullets del video largo:
    se veia «01» junto a su linea, y los numeros de la segunda y la tercera no
    aparecian hasta que la escena ya se iba.

    La causa estaba en `_Reloj.fin()`, que devolvia `tiempos[-1] + paso` -- el
    final de la cartela ENTERA -- y no el de lo que se llevaba escrito.
    `_escrito` devuelve eso como «ya he terminado», y LAS TRECE PLANTILLAS
    encadenan ahi lo que va detras: la regla de acento, el numero de una lista,
    el punto de una cronologia, el pie de la cifra, el cursor. O sea que no era
    un fallo de la lista: era de todas, y solo se veia con el reloj DICHO --el
    que sincroniza con la voz--, porque en el sintetico daba la casualidad de
    que coincidia.
    """
    titulo("cartelas: cada adorno entra con SU renglon, no al final de todo")
    datos = {"lineas": ["6M account records", "28M card numbers",
                        "Global staff payroll"]}
    # una marca por palabra dibujada: tres lineas de tres palabras
    tiempos = [1.4, 1.5, 1.6, 5.1, 5.2, 5.3, 9.2, 9.3, 9.4]
    svg = cartelas._cuerpo("enumeracion", datos, cartelas.colores_de(None),  # noqa: SLF001
                           {"fuente": "Verdana"}, duracion=11.5,
                           tiempos=tiempos)

    def entra(numero):
        """El `begin` de la animacion que hace aparecer ese numero."""
        antes = svg[:svg.index(f">{numero}<")]
        return float(re.findall(r'begin="([\d.]+)s"', antes)[-1])

    igual(entra("01"), 1.4, "el 01 entra con la primera palabra de su linea")
    igual(entra("02"), 5.1, "el 02 con la primera de la SUYA, no al final")
    igual(entra("03"), 9.2, "y el 03 igual")
    ok(entra("01") < entra("02") < entra("03"),
       "o sea en el orden logico: 01 [copy] 02 [copy] 03 [copy]")
    ok(entra("03") < tiempos[-1] + 1.0,
       "y ninguno espera al final de la escena, que es lo que se veia")

    titulo("cartelas: el reloj dice cuando acabo LO ESCRITO, no la cartela")
    reloj = cartelas._Reloj(0.2, 0.3, [1.0, 2.0, 3.0, 9.0])   # noqa: SLF001
    igual(reloj.fin(), 0.2, "sin consumir nada, el fin es el arranque")
    reloj.siguiente()
    igual(round(reloj.fin(), 2), 1.3, "tras una palabra, la suya mas un paso")
    igual(round(reloj.mirar(), 2), 2.0,
          "y `mirar` dice cuando entra la siguiente SIN consumirla: es lo que "
          "necesita un adorno que acompana al renglon que aun no se ha escrito")
    reloj.siguiente()
    igual(round(reloj.fin(), 2), 2.3, "el fin sigue lo consumido, no el total")
    ok(reloj.fin() < 9.0 + 0.3,
       "nunca el final de la cartela entera, que era el fallo")


def prueba_mascaras_en_la_hoja():
    """La hoja de personaje prohibia las mascaras y ganaba a lo que escribieras.

    Contradiccion literal (PENDIENTE 32): se pidieron ocho hackers con mascara
    de Anonymous y salieron a cara descubierta dos veces seguidas, porque tres
    frases despues el prompt decia «never cover a face with [...] masks».

    Y la clausula existe por un buen motivo, asi que no se puede borrar: una
    descripcion decia «faces mostly hidden in monitor glare» y el modelo dibujo
    el reflejo como una placa blanca sobre los ojos -- una hoja sin cara no fija
    nada. La salida es distinguir los dos casos.
    """
    titulo("reparto: se distingue «quiero mascaras» de «se me ha colado un brillo»")
    for texto in ("Grupo de hackers con mascara de anonymous en la cara",
                  "un equipo con casco integral y mono naranja",
                  "los cuatro con pasamontanas",
                  "rostro cubierto por una venda",
                  "four figures wearing Guy Fawkes masks"):
        ok(p6_assets.tapa_la_cara(texto), f"se pide tapar la cara: «{texto[:44]}»")
    for texto in ("faces mostly hidden in monitor glare",
                  "their faces are in shadow, lit only by the screens",
                  "todos con capucha, estilo estereotipo de hacker",
                  "an anonymous whistleblower in a grey coat",
                  "tres analistas en camisa, gesto serio"):
        ok(not p6_assets.tapa_la_cara(texto),
           f"y aqui NO, aunque lo parezca: «{texto[:44]}»")

    titulo("reparto: con mascara la clausula cambia de sujeto, no desaparece")
    tapada = p6_assets._prompt_reparto(                            # noqa: SLF001
        {"nombre": "nubla", "grupo": True, "feedback": "",
         "descripcion": "hackers con mascara de anonymous, todos con capucha"},
        {"prompt": "flat vector"})
    ok("covering IS the face" in tapada,
       "la mascara pasa a SER la cara: es lo que la hoja tiene que fijar")
    ok("Draw it exactly the same in both rows" in tapada,
       "y se exige identica en las dos filas, o no se puede copiar plano a plano")
    ok("Never leave the covered area vague" in tapada,
       "sin dejar hueco para el brillo, que es el fallo que costo la clausula")
    ok("masks or sunglasses" not in tapada,
       "y la prohibicion literal NO va: era la que ganaba al revisor")

    normal = p6_assets._prompt_reparto(                            # noqa: SLF001
        {"nombre": "analistas", "grupo": True, "feedback": "",
         "descripcion": "tres analistas en camisa, gesto serio"},
        {"prompt": "flat vector"})
    ok("Every face must be fully visible" in normal,
       "sin mascara pedida, la prohibicion de siempre sigue entera")
    ok("covering IS the face" not in normal, "y la excepcion no se cuela")

    titulo("reparto: y el PLANO tambien se entera de que la hoja va tapada")
    ref = {"papel": "reparto", "nombre": "nubla", "tapada": True}
    con = p6_assets._prompt_completo(                               # noqa: SLF001
        {"id": "S002", "prompt": "una sala"}, [ref], {})
    ok("Their faces are covered in that sheet" in con,
       "el plano recibe «copy their faces exactly as drawn there» y la regla de "
       "la casa le pide declarar la expresion facial: sin decirle que la cara va "
       "tapada, tiene dos motivos para destaparla")
    sin = p6_assets._prompt_completo(                               # noqa: SLF001
        {"id": "S002", "prompt": "una sala"},
        [{"papel": "reparto", "nombre": "analistas"}], {})
    ok("Their faces are covered" not in sin, "y si no va tapada, no se dice")


def prueba_unidades_fantasma():
    """Los cinco planos que absorbio el fundido y no bajaban nunca.

    «Regenerar lo obsoleto (5)» se pulsaba, corria, y seguian siendo cinco
    (PENDIENTE 34): al fundir se borran escenas del PLAN, pero nadie retiraba sus
    UNIDADES del estado. Nadie las produce --p7 recorre `plan["escenas"]`--, asi
    que su firma no se sella jamas.

    Se arregla declarandolas en el plan, que es el canal que ya existe para los
    planos que deja fuera un recorte (`conservacion.retirados` -> app.py ->
    `estado.retirar_unidades`).
    """
    titulo("cabeceras: un plano absorbido por el fundido se declara RETIRADO")

    def _pl(sid, t_in, dur, bloque):
        return {"id": sid, "t_in": t_in, "t_out": round(t_in + dur, 3),
                "duracion": dur, "narracion": f"palabras de {sid}",
                "marcas": [], "origen": {"bloque": bloque, "indice": 0},
                "set": "sitio", "camara": "general",
                "zoom": {"tipo": "in", "de": 1.0, "a": 1.0526}}

    escenas = [_pl("S001", 0.0, 3.0, "B001"), _pl("S002", 3.0, 3.0, "B001"),
               _pl("S003", 6.0, 3.0, "B001")]
    larga = {"plantilla": "tesis", "fondo": "negro",
             "datos": {"texto": "una frase larga que necesita mas de un plano "
                                "para poder leerse entera"}}
    escenas[0]["cartela"] = larga
    seguidas = _fundir_ct(escenas, {"S001": larga}, {})
    absorbidos = sorted({f["absorbido"] for f in seguidas if f.get("absorbido")})
    ok(absorbidos, f"el fundido se come planos: {absorbidos}")
    vivos = {e["id"] for e in escenas}
    ok(not (set(absorbidos) & vivos),
       "y los absorbidos ya NO estan en el plan: por eso nadie los produce")
    ok(all(a not in vivos for a in absorbidos),
       "asi que retirarlos no puede tocar ninguna unidad viva -- que es la "
       "guarda que lleva `planificar`: el plan es la verdad de que planos hay")


def prueba_lo_que_la_receta_no_nombra():
    """La pantalla y la tanda tienen que leer la receta IGUAL.

    EL FALLO QUE ESTO CIERRA, y no daba ningun error: la pantalla preguntaba
    `receta["tareas"].get(tid, True)` --lo que no esta, encendido-- y quien
    lanzaba recorria `receta["tareas"].items()` quedandose con las verdaderas,
    o sea que **lo que no estaba no corria**. Con una receta guardada antes de
    que la tarea existiera --o traida de otra version del software-- la
    pantalla ensenaba «La direccion de cada plano» encendida y la tanda no la
    hacia. Salia un video con menos, y nada lo decia.
    """
    titulo("recetas: lo que la receta no nombra vale lo que diga de_fabrica")
    opcionales = [t for t in recetas.tareas_de("video") if t.get("opcional")]
    ok(len(opcionales) >= 2, f"«video» tiene opcionales que apagar: "
                             f"{[t['id'] for t in opcionales]}")
    falta = opcionales[0]["id"]

    # una receta que NO nombra esa tarea (como las guardadas antes de que
    # existiera): corre si su de_fabrica lo dice
    a_medias = {"tareas": {t["id"]: True for t in recetas.tareas_de("video")
                           if t["id"] != falta}}
    puestas = recetas.puestas_de("video", a_medias)
    espera = recetas.TAREAS_POR_ID[falta].get("de_fabrica", True)
    igual(falta in puestas, bool(espera),
          f"«{falta}» no esta en la receta, asi que vale su de_fabrica "
          f"({espera})")

    # y lo que SI nombra manda, en los dos sentidos
    apagada = dict(a_medias["tareas"]); apagada[falta] = False
    ok(falta not in recetas.puestas_de("video", {"tareas": apagada}),
       f"apagada a mano, «{falta}» no corre")
    encendida = dict(a_medias["tareas"]); encendida[falta] = True
    ok(falta in recetas.puestas_de("video", {"tareas": encendida}),
       f"encendida a mano, «{falta}» corre")

    # UNA TAREA QUE NO EXISTE se ignora, no revienta: es lo que trae una receta
    # de otra version del software (`integraciones`, `fuentes`, `plan_callouts`)
    inventada = dict(a_medias["tareas"])
    inventada.update({"integraciones": True, "fuentes": True, "loquesea": True})
    puestas = recetas.puestas_de("video", {"tareas": inventada})
    ok(all(p in recetas.TAREAS_POR_ID for p in puestas),
       f"una tarea que este software no conoce no se cuela: {puestas}")

    # y las obligatorias siempre, las nombre o no
    vacia = recetas.puestas_de("video", {"tareas": {}})
    for ficha in recetas.tareas_de("video"):
        if not ficha.get("opcional"):
            ok(ficha["id"] in vacia,
               f"«{ficha['id']}» no es opcional: corre con receta vacia")


def prueba_familias_de_receta():
    """La banda sonora y los efectos son ENTRADAS del MP4, no hermanas suyas."""
    titulo("recetas: el sonido es una familia, no dos hermanas del MP4")
    render = {t["id"]: t for t in recetas.tareas_de("render")}
    igual(render["banda_sonora"].get("familia"), "sonido",
          "la banda sonora es de la familia «sonido»")
    igual(render["efectos"].get("familia"), "sonido", "los efectos tambien")
    igual(render["render"].get("familia"), None,
          "y «El MP4» no: es lo que las OTRAS dos alimentan")
    ok("sonido" in recetas.FAMILIAS, "la familia esta declarada, con su nombre")
    ok(recetas.FAMILIAS["sonido"].get("porque"),
       "y con su porque, que es lo que se lee al pasar por encima")

    # UNA FAMILIA NO ES UNA DECISION. El canal lo pidio expresamente: «musica y
    # sonido casi siempre aciertas, no hace falta que de primeras se le pida eso
    # al usuario». Agrupar no puede convertirlas en algo que decidir.
    for tid in ("banda_sonora", "efectos"):
        ok(render[tid]["opcional"], f"{tid} sigue siendo opcional")
        ok(render[tid].get("de_fabrica", True) is True,
           f"y {tid} sigue encendida de fabrica: corre sola, no se pregunta")
        ok(not render[tid]["cuesta"], f"y {tid} no cuesta dinero")
    ok("familias" in recetas.catalogo(), "y la pantalla las recibe")


def prueba_musica_un_pelin_mas_alta():
    """La musica sube un pelin, y las dos ramas suben lo mismo."""
    titulo("sonido: el nivel de la musica, la cama y el tema suelto igual")
    cama = sonido.filtro_de_mezcla(True, False, 10.0, ya_normalizada=True)
    suelto = sonido.filtro_de_mezcla(True, False, 10.0)
    ok(f"volume={sonido.CAMA_GANANCIA_DB + sonido.MUSICA_SUBIDA_DB:g}dB" in cama,
       "la cama suma la subida del canal a su ganancia calibrada")
    ok(f"loudnorm=I={sonido.MUSICA_LUFS:.1f}" in suelto
       and f"volume={sonido.MUSICA_SUBIDA_DB:g}dB" in suelto,
       "y el tema suelto la lleva DETRAS del loudnorm, no moviendo su objetivo: "
       "ese objetivo es tambien con el que se normalizo cada tramo de la cama, "
       "asi que tocarlo la subiria dos veces")
    ok("sidechaincompress" in cama and "alimiter" in cama,
       "el ducking y el limitador siguen en su sitio: mover el nivel no puede "
       "quitar lo que impide que la mezcla recorte")

    # EL MASTER (PENDIENTE 42). El video salia a -17,1 LUFS, tres por debajo de
    # lo que normaliza YouTube, y con el pico a dos decimas de cero.
    titulo("sonido: el video sale al nivel de la plataforma, y en DOS pasadas")
    analisis = sonido.filtro_de_mezcla(True, False, 10.0, master=True)
    ok("print_format=json" in analisis,
       "sin medida, el grafo es el que MIDE y escribe el informe")
    ok("measured_I" not in analisis and "linear=true" not in analisis,
       "y no aplica ninguna ganancia: esa pasada no escribe video")
    aplicado = sonido.filtro_de_mezcla(
        True, False, 10.0, master=True,
        medida={"input_i": "-17.1", "input_tp": "-0.2", "input_lra": "3.6",
                "input_thresh": "-27.3"})
    ok(f"I={sonido.MASTER_LUFS:g}" in aplicado
       and f"TP={sonido.MASTER_TP:g}" in aplicado,
       f"con la medida delante se apunta a {sonido.MASTER_LUFS:g} LUFS y "
       f"{sonido.MASTER_TP:g} dBTP")
    ok("measured_I=-17.10" in aplicado and "linear=true" in aplicado,
       "y con `linear=true`: la ganancia es CONSTANTE. Un loudnorm de una "
       "pasada es adaptativo, y sobre voz con musica eso se oye como bombeo")
    ok(aplicado.index("alimiter")
       < aplicado.index(f"loudnorm=I={sonido.MASTER_LUFS:g}"),
       "el limitador va DELANTE del master: lo que impide que la suma de tres "
       "pistas recorte no puede depender de que la medida haya salido bien")
    ok("loudnorm=I=-14" not in sonido.filtro_de_mezcla(True, False, 10.0),
       "y sin master el grafo es exactamente el de siempre")

    titulo("sonido: la LLAVE del ducking va aplanada, no es la voz tal cual")
    # El fallo que arregla: con la voz de llave, la musica sigue su envolvente y
    # sube en el remate de cada frase, justo encima de la ultima palabra. Medido
    # sobre el grafo real: +11,74 dB antes, +1,77 dB ahora.
    ok(f"[vozllave]volume={sonido.DUCK_LLAVE_SUBIDA_DB:g}dB" in suelto,
       "la llave se sube antes de limitarla: una silaba floja tiene que cruzar "
       "el umbral igual que una fuerte")
    ok(f"alimiter=limit={sonido.DUCK_LLAVE_TECHO:g}" in suelto,
       "y se le corta la cabeza, que es lo que la deja plana")
    ok("[mus][llave]sidechaincompress" in suelto,
       "y el compresor toma como cadena lateral la llave, no la voz cruda")
    ok(f"release={sonido.DUCK_CAIDA_MS:g}" in suelto and sonido.DUCK_CAIDA_MS >= 900,
       "la caida es larga: con 450 ms la musica volvia a subir entre dos frases "
       "de la misma idea, o sea varias veces por plano")

    titulo("sonido: cuanta musica lleva ESTE video es un mando de un numero")
    con_ajuste = sonido.filtro_de_mezcla(True, False, 10.0, ajuste_db=-3)
    ok(f"volume={sonido.MUSICA_SUBIDA_DB - 3:g}dB" in con_ajuste,
       "el ajuste del video se suma a la subida del canal, en la misma cuenta")
    cama_ajustada = sonido.filtro_de_mezcla(True, False, 10.0, ya_normalizada=True,
                                            ajuste_db=-3)
    ok(f"volume={sonido.CAMA_GANANCIA_DB + sonido.MUSICA_SUBIDA_DB - 3:g}dB"
       in cama_ajustada,
       "y llega a las DOS ramas: con cama o con tema suelto, bajar la musica "
       "tiene que bajarla igual")
    ok("musica_db" in p8_render.PARAMS_POR_DEFECTO
       and p8_render.PARAMS_POR_DEFECTO["musica_db"] == 0.0,
       "vive en los params del render, a cero de fabrica: solo obliga a "
       "remuxear, ni una imagen ni un clip")


def _prohibir_pagar():
    """Deja el motor de imagen sin `generar`. Ver la cabecera del modulo.

    Se sustituye SOLO `generar`: el resto del motor --`_cuanto_esperar`,
    `_sin_saldo`, `_calibrar`, el cubo de fichas, `normalizar`-- lo miran varias
    pruebas y tiene que ser el de verdad. Quien necesite generar algo pone su
    propio motor de mentira, que es lo que hace `prueba_rehacer_de_verdad`.

    El medidor de gasto (`coste.instrumentar`) envuelve lo que encuentre, asi
    que envuelve a esta y la marca igual: `prueba_recarga_de_motores`, que
    comprueba la marca, sigue viendo lo que tiene que ver.
    """
    motor = medios.motor("imagen_openai/imagen.py")

    def no_se_paga(*_args, **_kwargs):
        raise AssertionError(
            "una prueba ha llamado al motor de imagen DE VERDAD. Esta suite no "
            "puede pagar imagenes: pon un motor de mentira (ver "
            "`prueba_rehacer_de_verdad`) o arregla la firma de cache que ha "
            "dejado de acertar")

    motor.generar = no_se_paga


def main():
    _prohibir_pagar()
    # EL HISTORICO DE TIEMPOS, A UNA COPIA. Guarda 30 muestras por paso, asi
    # que las de una suite EXPULSAN las reales por antiguedad -- y con ellas se
    # va lo unico que hace que `cadencia` y la barra dejen de usar la tabla
    # escrita y usen lo medido de esta maquina.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(
        tempfile.gettempdir(), "estudio_prueba_piezas", "estadisticas.json")
    prueba_feedback_en_prompts()
    prueba_catalogo()
    prueba_planos_por_sitio()
    prueba_reparto_inventado()
    prueba_sitios_sin_tramo()
    prueba_callouts()
    prueba_coste()
    prueba_segmentar()
    prueba_una_frase_un_plano()
    prueba_prompt_de_estilo()
    prueba_guia_de_estilo()
    prueba_exigir_estilo()
    prueba_cadenas()
    prueba_moodboard()
    prueba_rehacer_de_verdad()
    prueba_ids_en_orden()
    prueba_guia_con_manos()
    prueba_recarga_de_motores()
    prueba_recarga_de_la_otra_cache()
    prueba_limite_de_la_api()
    prueba_copiar_con_fichero_abierto()
    prueba_render_con_fichero_abierto()
    prueba_orden_de_la_cartela()
    prueba_redactor()
    prueba_reparto_de_beats()
    prueba_ultima_palabra_rotulos()
    prueba_rotulo_en_el_idioma_del_video()
    prueba_la_cara_es_de_esa_escena()
    prueba_continuidad()
    prueba_cache_referencias()
    prueba_espaciar()
    prueba_cartelas()
    prueba_direccion()
    prueba_subtitulos()
    prueba_encajar_mide_el_ancho()
    prueba_cartelas_composicion()
    prueba_cartelas_dos_fondos()
    prueba_transiciones()
    prueba_sonido()
    prueba_reloj_de_cartela()
    prueba_mascaras_en_la_hoja()
    prueba_unidades_fantasma()
    prueba_lo_que_la_receta_no_nombra()
    prueba_familias_de_receta()
    prueba_musica_un_pelin_mas_alta()

    print("\n" + "=" * 70)
    if _fallos:
        print(f"FALLAN {len(_fallos)} de {_comprobaciones[0]} comprobaciones:")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"PIEZAS OK: {_comprobaciones[0]} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
