"""
Paso 7: capa vectorial y movimiento de camara.

Encima de cada plano va una capa SVG con rotulos, callouts con linea guia,
cifras y cabeceras de capitulo, y al lado el JSON de movimiento con las ventanas
de zoom (motor render_video/movimiento.py).

Dos decisiones que gobiernan todo el paso:

1. El texto NUNCA lo escribe el modelo de imagen. La tipografia sale exacta en
   vectorial y aproximada en difusion, y ademas asi se corrige una errata sin
   volver a generar la escena.

2. La colocacion es determinista y se verifica por pixeles. De la imagen se saca
   una mascara de detalle (donde hay dibujo), de ahi una transformada de
   distancia, y la caja de texto va al hueco mas grande. Antes de aceptarla se
   cuentan los pixeles de mascara que caen dentro: si la caja pisa al sujeto se
   prueba el siguiente candidato. La linea guia elige el lado de la caja cuyo
   trazo hasta el objetivo cruza menos dibujo.

Los rotulos se colocan ademas dentro de la zona que sigue en cuadro durante todo
el zoom, no dentro del plano entero: el video recorta 16:9 sobre un plano 3:2 y
encima se mueve, asi que rotular mirando solo la imagen deja el texto cortado.

Como lo llama el orquestador:

    resultado = p7_callouts.ejecutar(proyecto, params, avisar)     # o unidades=[...]
    estado.completar("callouts", resultado["salidas"], resultado["unidades"])

Salidas por escena: capas/<id>.svg, movimiento/<id>.json, hyper/<id>.png y
previo/<id>.png (plano + capa compuestos para la pantalla de revision).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# `cv2`, `numpy`, `PIL`, `math` y `re` ya no se importan aqui, y su ausencia es
# la medida de lo que este paso ha dejado de hacer: eran para abrir el PNG de
# cada plano, sacarle una mascara de detalle, calcular una transformada de
# distancia y probar catorce cajas hasta encontrar un hueco donde el rotulo no
# pisara al sujeto. Un subtitulo no flota, asi que no hay
# nada que colocar -- ni un pixel que mirar.

import cartelas  # noqa: E402
import comun  # noqa: E402
import estadisticas  # noqa: E402
import subtitulos  # noqa: E402
import medios  # noqa: E402
import tipografia  # noqa: E402

PARAMS_POR_DEFECTO = {
    "fuente": "Verdana",
    "margen": 64,               # respeto al borde del cuadro, en px de generacion
    "escala_hyper": 2,
    "previsualizar": True,      # compone escena + capa en un PNG para la revision
    # El plan de rotulos NO esta aqui: describe UN plano, asi que va por unidad
    # (ver CLAVE_ROTULOS y rotulos_de, mas abajo).
    #
    # QUE TAMANO tiene el subtitulo: pequeno | normal | grande | enorme, o un
    # numero de pixeles del lienzo de generacion. El normal esta calculado (ver
    # SUB_TAM), asi que quien no lo toque tiene uno que se lee.
    "subtitulo_tam": "normal",
    # CUANTO TAPA LA CAJA de detras del subtitulo: "auto" es lo decidido por el
    # canal (SUB_CAJA_OPACIDAD), y un numero de 0 a 1 manda sobre ello. 0 la
    # quita del todo y deja el texto a pelo.
    #
    # Existe porque no habia forma de pedirlo: la opacidad era una constante de
    # modulo, asi que «bajale un poco la caja al subtitulo» no tenia donde
    # aterrizar -- y lo que parecia el mando, la clave `opacidad` de los tres
    # SETS_DISENO, no la leia nadie. Un mando que no existe es peor que uno
    # feo: el enrutador del estilo grafico habria escrito ahi, el video habria
    # salido igual, y la correccion habria quedado marcada como aplicada.
    "subtitulo_caja": "auto",
    # Set de estilo de diseno: dibujo | realista | editorial. Lo sugiere la guia
    # de estilo del video (ver diseno_sugerido) y se puede cambiar a mano.
    # Escrito y no DISENO_POR_DEFECTO porque los sets se declaran mas abajo:
    # esta tabla es lo primero del modulo a proposito, para poder leerla de un
    # vistazo. La prueba de coherencia de ahi abajo los ata.
    "diseno": "dibujo",
    # Paleta de RESPALDO. Los colores de verdad salen de la guia de estilo del
    # video (paleta_de_guia); esto es lo que se usa mientras no haya guia.
    "paleta": {
        "texto": "#ece7dc",
        "tenue": "#c9c2b4",
        "linea": "#d8a657",
        "sombra": "#12130f",
        "acento": "#d8785a",
    },
}

TAMANO = (1536, 1024)

#: Las fuentes y la medida viven en `tipografia`: las cartelas miden igual que
#: los rotulos y no pueden importar p7 (p7 las importa a ellas). Se dejan los
#: nombres aqui porque medio repositorio -- suites incluidas -- llama a
#: p7.medir y p7.fuente, y renombrarlos no arregla nada.
FUENTES = tipografia.FUENTES
fuente = tipografia.fuente
medir = tipografia.medir
partir = tipografia.partir
MARGEN_MEDIDA = tipografia.MARGEN_MEDIDA

# ===========================================================================

# LOS ARQUETIPOS DE ROTULO VIVIAN AQUI, y eran 115 lineas de tabla. Se
# retirados el 22-08: de los siete solo quedaban dos vigentes

def _rgb(hexa):
    """'#d8a657' -> (216, 166, 87). None si no es un color legible."""
    crudo = str(hexa or "").strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    if len(crudo) != 6:
        return None
    try:
        return tuple(int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _luz(rgb):
    """Luminancia percibida, 0..255. El verde pesa mas porque el ojo lo ve mas."""
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _saturacion(rgb):
    return max(rgb) - min(rgb)


def paleta_de_guia(guia, paleta_base=None):
    """Paleta de los rotulos DERIVADA de la guia de estilo del video.

    La de los params son cinco colores escritos a mano que no tienen nada que
    ver con el dibujo: un rotulo dorado sobre un video de azules aterriza
    encima en vez de pertenecer. La guia de estilo ya trae la paleta del video
    en hexadecimales, asi que los colores del rotulo salen de ahi.

    El reparto es por luminancia y saturacion, y es DETERMINISTA: la misma
    paleta da siempre los mismos cinco colores.

      texto   el mas claro          (tiene que leerse encima del dibujo)
      sombra  el mas oscuro         (contorno del texto)
      linea   el mas saturado       (la regla y la linea guia: el acento)
      acento  el segundo saturado, o el mismo
      tenue   el mas cercano a la media (subtitulos)

    Sin guia se queda la de los params, que es lo que habia. Los proyectos de
    antes no cambian.

    LO PUESTO A MANO MANDA. `fijados` son los papeles que una persona ha
    elegido con el selector de color, y esos NO se derivan: se respetan y solo
    se rellena el resto. Antes esta funcion construia un diccionario nuevo con
    los cinco y tiraba `paleta_base` entera, asi que elegir un color funcionaba
    en pantalla y lo pisaba la siguiente ejecucion sin que nada lo dijera --
    justo el tipo de degradacion silenciosa que este sistema no se permite. Es
    la misma regla que el idioma de la voz y que los presets: lo puesto a mano
    manda, lo vacio se deriva.
    """
    base = dict(paleta_base or {})
    fijados = {papel: valor for papel, valor in (base.get("fijados") or {}).items()
               if _rgb(valor)}
    base.pop("fijados", None)
    colores = []
    for crudo in (guia or {}).get("paleta") or []:
        rgb = _rgb(crudo)
        if rgb:
            colores.append((f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}", rgb))
    if len(colores) < 3:
        base.update(fijados)
        return base                    # con dos colores no hay reparto que hacer

    por_luz = sorted(colores, key=lambda c: _luz(c[1]))
    por_sat = sorted(colores, key=lambda c: _saturacion(c[1]), reverse=True)
    medio = por_luz[len(por_luz) // 2]
    derivada = {
        "texto": por_luz[-1][0],
        "sombra": por_luz[0][0],
        "linea": por_sat[0][0],
        "acento": por_sat[1][0] if len(por_sat) > 1 else por_sat[0][0],
        "tenue": medio[0],
    }
    derivada.update(fijados)
    return derivada


def diseno_de(p, guia=None):
    """Set de diseno elegido, con su ficha.

    SI NADIE HA ELEGIDO, MANDA LA SUGERENCIA DE LA GUIA DE ESTILO. Hasta el
    22-08 `diseno_sugerido` se calculaba, se servia a la pantalla y ahi se
    quedaba: habia que abrir la tarjeta y pulsarla. Deducir algo bien y despues
    pedirle a una persona que lo confirme es exactamente el paso que sobra
    -- se aplica solo, y cambiarlo sigue siendo un clic.

    Elegir a mano sigue mandando sobre todo: `p["diseno"]` gana siempre.
    """
    nombre = str(p.get("diseno") or "")
    if not nombre and guia:
        nombre = diseno_sugerido(guia)[0]
    nombre = nombre or DISENO_POR_DEFECTO
    return nombre if nombre in SETS_DISENO else DISENO_POR_DEFECTO, \
        SETS_DISENO.get(nombre) or SETS_DISENO[DISENO_POR_DEFECTO]


def diseno_sugerido(guia):
    """Que set pega con esta guia de estilo, para preseleccionarlo.

    Se mira lo que la guia dice del TRAZO, que es lo que de verdad separa un
    dibujo plano de una imagen con aire realista. Es una sugerencia con su
    porque, no una imposicion: se puede cambiar a mano.
    """
    trazo = medios.normalizar_texto(str((guia or {}).get("trazo") or ""))
    personajes = medios.normalizar_texto(str((guia or {}).get("personajes") or ""))
    junto = f"{trazo} {personajes}"
    if any(p in junto for p in ("thick", "grueso", "bold outline", "cartoon",
                                "flat", "stickman", "uniform")):
        return "dibujo", "la guía habla de trazo grueso y relleno plano"
    if any(p in junto for p in ("no outline", "sin contorno", "photo", "realistic",
                                "soft", "gradient", "degradado")):
        return "realista", "la guía describe un acabado sin contorno marcado"
    return DISENO_POR_DEFECTO, "no hay señal clara en la guía: se usa el de por defecto"


# ===========================================================================
# SETS DE ESTILO DE DISENO
#
# El MISMO arquetipo dibujado de tres maneras. Un video de trazo grueso y otro
# de aire documental no pueden llevar el mismo rotulo, y hasta ahora la paleta
# era fija en los params: cinco colores escritos a mano que no tenian nada que
# ver con el dibujo del video.
#
# Cada set dice como se dibuja el envoltorio; los COLORES no estan aqui, salen
# de la paleta de la guia de estilo (ver paleta_de_guia). Asi el rotulo se
# parece al video en vez de aterrizar encima.
#
# AQUI HABIA UNA CLAVE `opacidad` EN LOS TRES, y no la leia nadie: la de la caja
# del subtitulo sale de `SUB_CAJA_OPACIDAD` y del param `subtitulo_caja` desde
# que el canal decidio la caja ligera (24-08). Tres numeros con pinta de mando y
# sin lector son una trampa -- se escribe ahi, el video sale igual y el cambio
# queda marcado como aplicado --, asi que se fueron.
# ===========================================================================

SETS_DISENO = {
    # Para dibujo plano: trazo grueso, esquinas redondas, relleno opaco. Es el
    # que pega con el estilo stickman del estudio.
    "dibujo": {
        "nombre": "Dibujo",
        "descripcion": "trazo grueso, esquinas redondas y relleno opaco, como el dibujo",
        "borde": 5, "radio": 18, "sombra_texto": 7,
        "fuente": "Verdana, sans-serif", "versales": True,
    },
    # Aire de documental: cajas discretas, esquina viva, fondo semitransparente.
    "realista": {
        "nombre": "Realista",
        "descripcion": "cajas discretas de esquina viva sobre fondo translúcido",
        "borde": 2, "radio": 3, "sombra_texto": 5,
        "fuente": "Georgia, serif", "versales": False,
    },
    # Revista: sin caja, la tipografia manda y una regla gruesa la sujeta.
    "editorial": {
        "nombre": "Editorial",
        "descripcion": "sin caja: manda la tipografía, sujeta por una regla gruesa",
        "borde": 0, "radio": 0, "sombra_texto": 9,
        "fuente": "Verdana, sans-serif", "versales": True,
    },
}

DISENO_POR_DEFECTO = "dibujo"

# Los dos sitios donde aparece el set por defecto tienen que decir lo mismo. Se
# comprueba al importar y no en una prueba: si se desincronizan, el paso arranca
# con un diseno y la interfaz ensena otro, y eso no se ve hasta renderizar.
assert PARAMS_POR_DEFECTO["diseno"] == DISENO_POR_DEFECTO
assert DISENO_POR_DEFECTO in SETS_DISENO


def describir(params):
    """Frase corta con lo que hara el paso con estos parametros."""
    p = _con_defectos(params)
    return (f"Escribe los subtitulos de cada plano en {p['fuente']} "
            f"(tamano {p['subtitulo_tam']}), sincronizados con la voz y en una "
            f"banda que es la misma en todo el video, y calcula las ventanas de "
            f"zoom sobre hyperframes x{p['escala_hyper']}.")


def _con_defectos(params):
    p = dict(PARAMS_POR_DEFECTO)
    p.update(params or {})
    paleta = dict(PARAMS_POR_DEFECTO["paleta"])
    paleta.update(p.get("paleta") or {})
    p["paleta"] = paleta
    return p


# --------------------------------------------------------------- la camara
#
# Donde cae el recorte 16:9 dentro del plano 3:2 en cada instante del zoom. Es
# la MISMA cuenta que hace la pagina del render y que replica el reproductor: si
# se calculara distinto en cualquiera de los tres, lo aprobado dejaria de ser lo
# renderizado.
#
# Debajo de este titulo vivia el analisis de pixeles -- mascara de detalle,
# transformada de distancia, catorce cajas candidatas -- que buscaba un hueco
# limpio donde poner un rotulo. Se fue entero con los rotulos:
# un subtitulo no flota, asi que no hay nada que colocar.


def suavizar(u):
    """La misma curva de aceleracion que usa el reproductor y el render."""
    u = min(max(float(u), 0.0), 1.0)
    return u * u * (3 - 2 * u)


def ventana_en(mov, fraccion, tamano=TAMANO, aspecto=16 / 9):
    """Trozo del plano que se ve en ese punto del recorrido del zoom.

    Es la MISMA matematica que la pagina del render: interpolacion suavizada
    entre ventana_ini y ventana_fin y recorte al aspecto de salida sobre el
    mismo centro. Tiene que serlo, o una captura tomada en el segundo 2,2 no
    coincidiria con lo que el video ensena en el segundo 2,2.
    """
    ancho, alto = tamano
    ini, fin = mov["ventana_ini"], mov["ventana_fin"]
    e = suavizar(fraccion)
    x = ini[0] + (fin[0] - ini[0]) * e
    y = ini[1] + (fin[1] - ini[1]) * e
    w = ini[2] + (fin[2] - ini[2]) * e
    h = ini[3] + (fin[3] - ini[3]) * e
    # el lado que limita manda (la misma regla que la pagina del render):
    # salida mas ancha que el plano -> el ancho; mas alta -> el alto
    if aspecto >= float(ancho) / float(alto):
        px_ancho = w * ancho
        px_alto = px_ancho / aspecto
        if px_alto > alto:
            px_alto, px_ancho = alto, alto * aspecto
    else:
        px_alto = h * alto
        px_ancho = px_alto * aspecto
        if px_ancho > ancho:
            px_ancho, px_alto = ancho, ancho / aspecto
    cx, cy = (x + w / 2) * ancho, (y + h / 2) * alto
    x0 = min(max(cx - px_ancho / 2, 0), ancho - px_ancho)
    y0 = min(max(cy - px_alto / 2, 0), alto - px_alto)
    return (x0, y0, x0 + px_ancho, y0 + px_alto)


def region_segura(mov, tamano, aspecto):
    """Zona del plano que se ve durante TODO el movimiento de camara.

    El video recorta 16:9 dentro de un plano 3:2 y ademas se mueve, asi que un
    rotulo colocado mirando solo la imagen completa acaba cortado por el borde.
    Se interseca la ventana inicial con la final y ahi dentro se coloca.
    """
    cajas = [ventana_en(mov, 0.0, tamano, aspecto),
             ventana_en(mov, 1.0, tamano, aspecto)]
    return (max(c[0] for c in cajas), max(c[1] for c in cajas),
            min(c[2] for c in cajas), min(c[3] for c in cajas))


def punto_en_plano(mov, fraccion, x, y, tamano=TAMANO, aspecto=16 / 9):
    """Punto del fotograma (0..1 de la pantalla) -> punto del plano (0..1).

    Lo que el revisor marca esta en coordenadas de lo que VE, y lo que ve es la
    ventana de zoom de ese instante recortada a 16:9. Sin deshacer ese recorte,
    una marca en el centro de la pantalla caeria en el centro del plano entero,
    que con el zoom entrado es otro sitio.
    """
    x0, y0, x1, y1 = ventana_en(mov, fraccion, tamano, aspecto)
    return ((x0 + min(max(float(x), 0.0), 1.0) * (x1 - x0)) / tamano[0],
            (y0 + min(max(float(y), 0.0), 1.0) * (y1 - y0)) / tamano[1])


# ------------------------------------------------------------------- SVG

_escapar = tipografia.escapar


def _aparicion(inicio, fin, extra=""):
    return (f'<animate attributeName="opacity" from="0" to="1" begin="{inicio:.2f}s" '
            f'dur="0.32s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="1" to="0" begin="{fin:.2f}s" '
            f'dur="0.3s" fill="freeze"/>{extra}')


def _corte_seco(inicio, fin):
    """Aparece y desaparece de golpe, sin fundido. Es lo del subtitulo vertical:
    con trozos de tres palabras, 0,32 s de entrada y 0,3 s de salida se comian
    la mitad del tiempo de lectura (el canal lo pidio el 02-09-2026)."""
    return (f'<set attributeName="opacity" to="1" begin="{inicio:.2f}s"/>'
            f'<set attributeName="opacity" to="0" begin="{fin:.2f}s"/>')


#: Donde vive, DENTRO de la unidad, lo que alguien decidio rotular en ese plano.
#:
#: El plan de rotulos describe UN plano, asi que va en el bloque `unidades` de
#: los params -- `unidades["escena:S013"]["rotulos"]` -- y no suelto. Todo lo que
#: no es ese bloque entra en la firma GLOBAL del paso, y con ella en la firma de
#: cada unidad: con el plan suelto, arrastrar el rotulo de UN plano dejaba
#: obsoletos los cuarenta y nueve y el render entero. Y eso no da ningun error,
#: solo un monton de naranja que parece otra cosa.
CLAVE_ROTULOS = "rotulos"


#: Cuanto tiene que estar en pantalla una cabecera, por palabra, para poder
#: leerla. La regla vive en p6 (`_estirar_cabeceras`), que es quien decide si un
#: plano dura el doble porque su cabecera no cabia: es una decision del PLAN --
#: cambia que imagen se paga y como se mueve la camara --, no de la capa. Aqui
#: solo se dibuja lo que el plan haya marcado como `arrastrado`.


#: EL CUADRO DE SALIDA, que es donde vive la capa QUIETA. La de siempre --la
#: que lleva la cartela y la cabecera-- sigue viviendo en el lienzo de
#: generacion (TAMANO), porque va dentro del zoom y se escala con la imagen.
#: Dos capas, dos sistemas de coordenadas, y no es un capricho: es exactamente
#: la diferencia entre lo que se mueve y lo que no.
SALIDA = (1920, 1080)

#: Cuerpo del subtitulo, en px del cuadro de SALIDA (1920x1080).
#:
#: CINCUENTA Y DOS, y el numero hubo que recalcularlo entero al sacar la capa
#: del zoom -- no conservarlo. Antes eran 34 px del lienzo de generacion, que el
#: zoom convertia en 42-45 px de 1080p (`s` va de 1,250 a 1,316 medido sobre las
#: 49 ventanas de un video real). Quieto en pantalla, 34 son 34: el subtitulo
#: ENCOGIA SOLO al hacerlo estatico, un 23 %.
#:
#: Asi que el orden fue: sacar la capa, medir en 1080p, y entonces elegir. 44 px
#: es lo que valia antes; el canal pidio ademas «un escalon mas grande», y un
#: escalon de la tabla de abajo son 52 px -- el 4,8 % del alto, dentro del
#: estandar de un subtitulo de 1080p (Netflix y YouTube rondan el 4,5 %).
SUB_TAM = 52

#: Y los tamanos que se pueden elegir a mano, en «Opciones avanzadas». Viven en
#: los params de ESTE paso, que es lo que hace que cambiarlo sea gratis: tocar
#: el grafismo no deja obsoleta ni una imagen, solo las capas.
#:
#: La tabla se recalibro ENTERA, no solo el «normal»: sus cuatro escalones
#: estaban calculados contra el lienzo de generacion y todos encogian igual.
#: Guardan las mismas proporciones que la vieja (28/34/40/46).
SUB_TAMANOS = {"pequeno": 44, "normal": SUB_TAM, "grande": 62, "enorme": 72}

#: Ancho maximo del bloque, en px de SALIDA. Eran 1.100 de un lienzo de 1.536
#: (el 72 %); esto es el 73 % de 1.920, o sea la misma proporcion.
SUB_ANCHO = 1400

#: Aire por debajo del suelo de la banda, en px de SALIDA. Eran 64 de 1.024 (el
#: 6,3 %); 72 de 1.080 es el 6,7 %, dentro del margen habitual de un subtitulo.
SUB_MARGEN = 72

#: LA CAJA. Decision del canal (22-08, despues de verlo montado): «que vayan en
#: una caja rectangular negra que los envuelve ligera (poca opacidad)».
#:
#: Y REVIERTE UNA DECISION DE ESTA MISMA SEMANA, a proposito. El 22-08 se decidio
#: lo contrario --sin caja, con perfilado-- y el porque escrito era que «un
#: cuadro tapa la imagen justo donde el ojo esta mirando». Se
#: monto, se vio, y el canal decidio caja. Queda escrito que es DELIBERADO, para
#: que nadie lo revierta leyendo el 39.3.
#:
#: 0,55 es «poca opacidad» de verdad: se ve la imagen a traves y aun asi el
#: texto no compite con lo que haya detras.
#:
#: Es el valor por DEFECTO desde el 24-08-2026 por la noche, no el unico: lo
#: manda `subtitulo_caja`, que se puede bajar, subir o poner a cero.
SUB_CAJA_OPACIDAD = 0.65   # +0,10 el 02-09-2026 a peticion del canal

#: Cuanto respira el texto dentro de la caja, en fraccion del cuerpo. A lo ancho
#: mas que a lo alto: una caja que toca las letras por los lados se lee apretada
#: mucho antes que una que las toca por arriba.
SUB_CAJA_AIRE = (0.62, 0.24)

#: Y el PESO. Era 400 --el normal de la fuente-- y sube a semibold. Esto si es
#: independiente de sacar la capa del zoom y se podia haber subido antes; va
#: aqui porque con la caja detras forman UNA decision: son las dos capas de
#: contraste que sustituyen al perfilado (ver `bloque_subtitulo`).
#:
#: OJO AL MEDIR: Verdana no tiene corte de 600, asi que el navegador sube al
#: siguiente que existe (700, `verdanab.ttf`). Quien mida este texto tiene que
#: abrir ESE fichero o la cuenta sale corta -- un 12,5 % corta, medido, que es
#: justo lo que hacia que el subtitulo se saliera de su caja.
SUB_PESO = 600


#: CUANTO CRECE EL SUBTITULO EN VERTICAL, como mucho. El cuerpo (52 px) esta
#: pensado para 1080 de alto; en un 1080x1920 que se ve en un movil, 52 px son
#: la mitad de alto relativo y se leen pequenos. Se escala con el alto del
#: cuadro (1920/1080 = 1,78) con este techo: a 1,78 el subtitulo se comia dos
#: renglones de un tercio de pantalla (02-09-2026, primer video vertical).
SUB_ESCALA_VERTICAL_MAX = 1.35

#: EN VERTICAL EL SUBTITULO VA A UN TERCIO DE LA PANTALLA desde abajo, no al
#: pie: en un movil el pie lo tapan los controles y la mirada esta en el
#: centro. Es la fraccion del alto que queda por debajo de la linea base.
SUB_ALTURA_VERTICAL = 1.0 / 3.0


def es_vertical(salida=None):
    return bool(salida) and len(salida) >= 2 and float(salida[1] or 0) > float(salida[0] or 0)


def banda_subtitulo(salida):
    """La banda del subtitulo de ESTA salida: la de siempre, o a un tercio."""
    banda = subtitulos.banda_fija(salida[0], salida[1], margen=SUB_MARGEN,
                                  ancho_maximo=SUB_ANCHO)
    if es_vertical(salida):
        # solo sube el SUELO: el margen lateral (y con el, el ancho de la
        # banda) es el de siempre. Pasarle un tercio del alto como margen
        # dejaba la banda con ancho negativo y partia cada trozo en dos.
        banda["suelo"] = round(float(salida[1]) * (1.0 - SUB_ALTURA_VERTICAL), 1)
    return banda


def escala_subtitulo(salida=None):
    """Por cuanto se multiplica el cuerpo del subtitulo en ESTA salida."""
    if not salida or len(salida) < 2:
        return 1.0
    ancho, alto = float(salida[0] or 0), float(salida[1] or 0)
    if alto <= ancho or alto <= 0:
        return 1.0
    return round(min(SUB_ESCALA_VERTICAL_MAX, alto / 1080.0), 2)


def tamano_subtitulo(p, salida=None):
    """Cuerpo del subtitulo segun los params. Siempre un numero utilizable.

    Con `salida` va escalado al formato (ver `escala_subtitulo`): en vertical
    el mismo «normal» es mas grande, porque la pantalla es mas alta que ancha.
    """
    nombre = str((p or {}).get("subtitulo_tam") or "normal").strip().lower()
    if nombre in SUB_TAMANOS:
        base = SUB_TAMANOS[nombre]
    else:
        try:
            valor = int(float(nombre))
        except (TypeError, ValueError):
            valor = SUB_TAM
        base = valor if 12 <= valor <= 120 else SUB_TAM
    return int(round(base * escala_subtitulo(salida)))


def cap_subtitulo(tam, banda):
    """Caracteres por linea para ESTE cuerpo y ESTA banda. -> int

    `subtitulos.CAP_LINEA` (38) esta medido para cuerpo 52 en una banda de
    1.400 px. Con otro cuerpo u otra banda --en vertical el cuerpo crece y la
    banda se estrecha a 936-- caben menos, y trocear con 38 daba renglones que
    `dos_lineas` tenia que encoger o que se salian: el usuario lo vio como
    «frases largas y pequenas» en el movil. Aqui salen 16 por linea en
    vertical, o sea trozos mas cortos y mas grandes.
    """
    ancho = float((banda or {}).get("ancho") or SUB_ANCHO)
    return max(12, int(round(subtitulos.CAP_LINEA * (ancho / float(SUB_ANCHO))
                             * (float(SUB_TAM) / float(tam or SUB_TAM)))))


def cap_trozo_subtitulo(cap_linea, salida):
    """Tope del trozo: dos lineas en horizontal, UNA en vertical.

    En el movil el canal quiere un renglon de dos, tres o cuatro palabras y
    nunca dos a la vez: se lee de un golpe y no tapa el plano.
    """
    return cap_linea if es_vertical(salida) else None


def cap_subtitulo_de(p, plan):
    """La misma cuenta que hace `capa_fija_de`, para quien solo tiene el plan."""
    salida = salida_de(plan)
    return cap_subtitulo(tamano_subtitulo(p, salida), banda_subtitulo(salida))


def _medidor(fuente_nombre, tam, negrita=False):
    """Una funcion que mide texto en pixeles con la fuente de verdad.

    Mide con `tipografia.medir`, que es la MISMA cuenta que usan las cartelas y
    la que hace el render: medir aqui de otra forma es como se llega a un
    subtitulo que cabe en la prueba y se sale en el video.

    Y HAY QUE DECIRLE SI VA EN NEGRITA, que es lo que faltaba. Medir es abrir un
    FICHERO de fuente (`verdana.ttf` o `verdanab.ttf`) y preguntarle el avance:
    si se mide con uno y se dibuja con el otro, la cuenta esta bien y el numero
    esta mal. Verdana Bold es un 12,5 % mas ancha que la regular -- medido --,
    asi que el subtitulo se salia de su propia caja por los dos lados, y solo se
    notaba en las lineas largas porque en las cortas ese 12,5 % cabia dentro del
    aire (ver SUB_CAJA_AIRE).
    """
    def medir(texto):
        return tipografia.medir(str(texto or ""), fuente_nombre, tam,
                                negrita=bool(negrita))[0]
    return medir


def opacidad_de_caja(p):
    """Cuanto tapa la caja del subtitulo, de 0 a 1. -> float

    "auto" --y cualquier cosa que no sea un numero-- es lo decidido por el
    canal. Se recorta al rango a proposito y no se rechaza: esto lo escribe un
    enrutador leyendo una frase, y un 1,4 mal puesto tiene que dar una caja
    opaca, no tumbar el render de un video entero.
    """
    crudo = (p or {}).get("subtitulo_caja", "auto")
    if isinstance(crudo, bool) or crudo in (None, "", "auto"):
        return SUB_CAJA_OPACIDAD
    try:
        return max(0.0, min(1.0, float(crudo)))
    except (TypeError, ValueError):
        return SUB_CAJA_OPACIDAD


def bloque_subtitulo(trozo, banda, tam, paleta, diseno, opacidad=None,
                     fundido=True):
    """Un trozo de subtitulo dibujado: uno o dos renglones, centrados, en caja.

    CON CAJA NEGRA LIGERA, Y ES UN CAMBIO DELIBERADO. El 22-08 se decidio lo
    contrario --sin caja, con perfilado-- porque «un cuadro tapa la imagen justo
    donde el ojo esta mirando». Se monto, se vio, y el canal
    pidio caja ligera. Ver SUB_CAJA_OPACIDAD: queda escrito para que nadie lo
    revierta leyendo aquel apunte.

    Y EL PERFILADO SE VA CON ELLA. Con una caja detras y el cuerpo a semibold,
    el `stroke` seria la tercera capa de contraste para el mismo trabajo -- y no
    es gratis: a peso alto un perfilado del 15 % del cuerpo engorda el trazo y
    emborrona las contraformas. Dos capas bastan y son las que se ven.

    UNA CAJA POR TROZO, no una por renglon. Con el texto centrado, dos cajas de
    anchos distintos apiladas dibujan un escalon en el borde y eso es lo que
    convierte un subtitulo en un cartel; una sola caja del ancho del renglon mas
    largo es lo que hace la television desde siempre.

    ANCLADO POR ABAJO: la ultima linea siempre a la misma altura y el bloque
    crece hacia arriba, asi que un subtitulo de una linea y otro de dos empiezan
    en el mismo sitio. Al reves, el ojo tendria que buscarlo en cada corte.

    NUNCA EN VERSALES, aunque el set del grafismo las pida: una banda de sitio en
    mayusculas es un gesto de diseno y un subtitulo en mayusculas es ilegible.
    """
    fuente_nombre = (diseno or {}).get("fuente") or "Verdana"
    # SE MIDE CON LA MISMA FUENTE QUE SE DIBUJA. El SVG pide `font-weight` 600 y
    # Verdana no tiene un corte de 600: el navegador sube al siguiente que hay,
    # que es el 700, o sea `verdanab.ttf`. Midiendo con la regular la caja salia
    # un 12,5 % corta y el texto se le salia por los lados -- y `dos_lineas`
    # partia tarde por el mismo motivo. Ver `_medidor` y SUB_PESO.
    medir = _medidor(fuente_nombre, tam, negrita=SUB_PESO >= 600)
    lineas = subtitulos.dos_lineas(trozo["texto"], medir, banda["ancho"])
    if not lineas:
        return ""
    salto = int(tam * 1.28)
    base = float(banda["suelo"]) - salto * (len(lineas) - 1)
    color = (paleta or {}).get("texto") or "#ffffff"
    centro = float(banda["centro"])
    piezas = []

    # LA CAJA. El ancho lo manda el renglon mas largo MEDIDO con la fuente de
    # verdad (`tipografia.medir`, la misma cuenta que hace el render): a ojo se
    # llega a una caja que encaja en la prueba y se queda corta en el video.
    ancho_texto = max(medir(linea) for linea in lineas)
    aire_x, aire_y = SUB_CAJA_AIRE
    ancho_caja = ancho_texto + 2 * tam * aire_x
    # De la linea base al alto de la caja: por arriba sube el ascendente del
    # primer renglon y por abajo baja el descendente del ultimo.
    #
    # OJO CON `base`: ya ES la linea base del PRIMER renglon (se calcula arriba
    # restandole al suelo los saltos que crecen hacia arriba). Restarle otra vez
    # `salto * (n-1)` subia la caja de un subtitulo de dos lineas 66 px de mas,
    # asi que la de una linea y la de dos no acababan a la misma altura -- y el
    # anclaje por abajo, que es lo que hace que el ojo no tenga que buscarlo en
    # cada corte, se perdia justo en el caso en que se nota.
    arriba = base - tam * (0.82 + aire_y)
    alto_caja = salto * (len(lineas) - 1) + tam * (1.08 + 2 * aire_y)
    # las esquinas las manda el grafismo (SETS_DISENO), como el resto del
    # envoltorio: en 'dibujo' son redondas y en 'editorial' vivas
    radio = min(float((diseno or {}).get("radio") or 0), tam * 0.5)
    tapa = SUB_CAJA_OPACIDAD if opacidad is None else max(0.0, min(1.0, float(opacidad)))
    piezas.append(
        f'<rect x="{centro - ancho_caja / 2:.0f}" y="{arriba:.0f}" '
        f'width="{ancho_caja:.0f}" height="{alto_caja:.0f}" '
        f'rx="{radio:.0f}" ry="{radio:.0f}" '
        f'fill="#000000" opacity="{tapa:g}"/>')

    for indice, linea in enumerate(lineas):
        piezas.append(
            f'<text x="{centro:.0f}" y="{base + salto * indice:.0f}" '
            f'font-family="{fuente_nombre}" font-size="{tam}" '
            f'font-weight="{SUB_PESO}" '
            f'text-anchor="middle" fill="{color}">'
            f'{tipografia.escapar(linea)}</text>')
    entrada = (_aparicion(trozo["desde"], trozo["hasta"]) if fundido
               else _corte_seco(trozo["desde"], trozo["hasta"]))
    return f'<g opacity="0">{"".join(piezas)}{entrada}</g>'


def capa_fija_de(escena, p, banda=None, salida=SALIDA):
    """La capa QUIETA de un plano: sus subtitulos. -> (svg, fichas)

    Vive aparte de `capa_de_escena` porque la necesitan las tres clases de plano
    y las tres construyen su capa movil de forma distinta: un plano normal
    (subtitulo y nada mas), una cartela sobre imagen (velo y texto de cabecera
    encima del plano) y una cartela de fondo negro (la cabecera ES el plano).

    UN PLANO CON CARTELA NO LLEVA SUBTITULO, y es una decision del canal del
    24-08-2026 que REVIERTE la del 23-08.

    La del 23 fue: «con la capa quieta aparte ya no hay conflicto -- la cabecera
    vive arriba y en el espacio del plano, el subtitulo abajo y en el del
    cuadro-- y dejarlas mudas era un agujero de once segundos en la unica pista
    que promete estar siempre». Es verdad que caben las dos. Lo que se vio al
    mirarlo montado es que caber no es lo mismo que convenir: una cartela
    DESTILA la frase que se esta diciendo, asi que el subtitulo de debajo dice
    lo mismo con otras palabras y el plano tiene dos textos compitiendo.

    Lo que se acepta a cambio, dicho para que no sorprenda: un tramo con
    cabecera fundida --hasta tres planos-- se queda sin subtitulo. Es el
    agujero que la decision del 23 venia a tapar, y se asume a sabiendas.
    """
    if cartelas.es_cartela(escena) or escena.get("capitulo_svg"):
        return _envoltorio_fijo("", salida), []
    banda = banda or banda_subtitulo(salida)
    paleta = paleta_de_guia((p.get("estilo") or {}).get("guia"), p.get("paleta"))
    # `diseno_de` devuelve (nombre, ficha): aqui interesa la ficha, que trae la
    # fuente
    _, diseno = diseno_de(p, (p.get("estilo") or {}).get("guia"))
    tam = tamano_subtitulo(p, salida)
    trozos = subtitulos.de_escena(
        escena, idioma=p.get("idioma"),
        cap_linea=cap_subtitulo(tam, banda),
        cap_trozo=cap_trozo_subtitulo(cap_subtitulo(tam, banda), salida),
        texto=texto_subtitulo_de(p, f"escena:{escena.get('id')}"))
    tapa = opacidad_de_caja(p)
    # en vertical sin fundidos: cada trozo dura poco y se lee entero
    piezas = [bloque_subtitulo(x, banda, tam, paleta, diseno, tapa,
                               fundido=not es_vertical(salida))
              for x in trozos]
    fichas = [{"tipo": "subtitulo", "texto": x["texto"],
               "desde": x["desde"], "hasta": x["hasta"]} for x in trozos]
    return _envoltorio_fijo("".join(x for x in piezas if x), salida), fichas


def capa_de_escena(escena, p, mov=None, banda=None, aspecto=16 / 9,
                   lienzo=TAMANO, salida=SALIDA):
    """Las DOS capas de un plano y sus fichas. -> (svg_movil, svg_fijo, fichas)

    DOS Y NO UNA, y esa es la firma del cambio del 23-08 (PENDIENTE 38):

      svg_movil   va DENTRO del grupo que hace el zoom, en coordenadas del
                  lienzo de generacion (TAMANO). Aqui vive la cabecera de
                  capitulo, y en `ejecutar` tambien la cartela: su velo oscurece
                  la imagen y su texto acompana al plano, asi que sacarlas las
                  dejaria flotando sobre una imagen que se mueve debajo.
      svg_fijo    va FUERA del zoom, en coordenadas del cuadro de salida
                  (SALIDA). Aqui vive el subtitulo, y por eso se queda quieto en
                  pantalla: no hay ningun transform encima.

    Antes era una sola capa y iba dentro del zoom, o sea que el subtitulo hacia
    zoom con la imagen. El canal lo vio montado y pidio que se quedara quieto;
    la unica forma de que una cosa se quede quieta y la otra no es que sean dos
    capas, porque el transform lo lleva el grupo entero.

    LA FIRMA TAMBIEN ES LA PRUEBA DE QUE ESTO SE SIMPLIFICO EN SU DIA. Antes
    recibia la RUTA DE LA IMAGEN y el directorio de assets, porque tenia que
    abrir el PNG, sacarle una mascara de detalle, calcular una transformada de
    distancia y probar catorce cajas hasta encontrar un hueco donde el rotulo no
    pisara al sujeto. Un subtitulo no flota.

    `banda` es ahora el pie del cuadro de salida y ya no depende del plano, asi
    que se podria deducir aqui; entra igual por parametro para que quien componga
    fuera (la vista previa, el repaso) use exactamente la misma.
    """
    fija, fichas = capa_fija_de(escena, p, banda, salida)
    if escena.get("capitulo_svg"):
        # Una cabecera de capitulo es una portada a cuadro completo: se incrusta
        # tal cual y va CON la imagen. Su subtitulo, como el de cualquier otro
        # plano, va en la capa quieta -- que es lo que permite que una portada
        # tenga subtitulo sin que las dos se peleen por el mismo sitio.
        return (_envoltorio_svg(_cabecera_incrustada(escena["capitulo_svg"]),
                                lienzo),
                fija, fichas)
    return capa_vacia(lienzo), fija, fichas


def _envoltorio_svg(interior, tamano=TAMANO):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{tamano[0]}" height="{tamano[1]}" '
            f'viewBox="0 0 {tamano[0]} {tamano[1]}">{interior}</svg>')


def lienzo_de(plan):
    """El lienzo de generacion de ESTE video, que es el de su formato. Un plan
    de antes no lo trae y es el de siempre."""
    valor = (plan or {}).get("generacion")
    if isinstance(valor, (list, tuple)) and len(valor) == 2:
        return (int(valor[0]), int(valor[1]))
    return TAMANO


def salida_de(plan):
    """El cuadro de salida de ESTE video: el de su formato."""
    valor = (plan or {}).get("resolucion")
    if isinstance(valor, (list, tuple)) and len(valor) == 2:
        return (int(valor[0]), int(valor[1]))
    return SALIDA


def _envoltorio_fijo(interior, salida=SALIDA):
    """El envoltorio de la capa QUIETA: el cuadro de salida, no el lienzo.

    Va aparte de `_envoltorio_svg` y no con un parametro porque son dos espacios
    distintos y confundirlos no da un error: da un subtitulo colocado con las
    coordenadas del otro sistema, que es un fallo que solo se ve renderizando.
    """
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{salida[0]}" height="{salida[1]}" '
            f'viewBox="0 0 {salida[0]} {salida[1]}">{interior}</svg>')


def _cabecera_incrustada(ruta_svg):
    """Mete la cabecera de capitulo dentro de la capa, escalada al cuadro."""
    with open(ruta_svg, "r", encoding="utf-8") as fh:
        crudo = fh.read()
    interior = crudo[crudo.index(">", crudo.index("<svg")) + 1: crudo.rindex("</svg>")]
    return (f'<svg x="0" y="0" width="{TAMANO[0]}" height="{TAMANO[1]}" '
            f'viewBox="0 0 1920 1080" preserveAspectRatio="xMidYMid slice">'
            f'{interior}</svg>')


#: Lo que se le pide al SVG de la vista previa: ADELANTA hasta que todo lo que
#: entra ha entrado, y ni un segundo mas.
#:
#: La vista previa se rasterizaba dejando correr 1,8 s de tiempo virtual y
#: disparando la captura. Con eso, un rotulo que entra mas tarde -- y desde que
#: cada uno entra CUANDO SE DICE lo que rotula, muchos entran mas tarde -- salia
#: a medio fundido o directamente no salia: la previa quedaba identica al plano
#: desnudo. Se veia como una suite intermitente, que es la peor forma de verlo.
#:
#: Asi que se hace lo mismo que el render (p8): pedirle al navegador el instante
#: exacto con setCurrentTime, en vez de esperar a ver que pilla. El instante sale
#: del propio SVG: despues de la ultima ENTRADA y antes de la primera SALIDA (las
#: que van `to="0"`), o la previa saldria justo cuando todo se ha ido.
#:
#: Y se CONGELA la linea de tiempo antes de colocarla. El caso que lo enseno: el
#: rotulo de S001 entraba del todo en 0,67 s y empezaba a irse en 1,83, y la
#: captura caia en 1,80 -- treinta milesimas antes de que se fuera. Cualquier
#: deriva la pasaba al otro lado. Colocar sin congelar tampoco vale: el tiempo
#: virtual sigue corriendo desde donde se le deje.
#: LAS DOS CAPAS, NO LA PRIMERA. Cada <svg> lleva su propio reloj, y esto
#: colocaba solo el de la capa movil: el de la QUIETA --donde vive el subtitulo--
#: seguia corriendo en tiempo real desde que se inserto, asi que si la captura
#: llegaba antes de que el fundido de entrada terminara, el subtitulo salia a
#: opacidad cero. Se veia como intermitente: en los planos con cartela la capa
#: movil daba trabajo de sobra al navegador y para cuando capturaba, el subtitulo
#: ya habia entrado; en los planos sin cartela no, y el subtitulo desaparecia.
#: Justo el fallo que este script existe para no tener.
BUSCAR_ENTRADAS = """
  var capas = document.querySelectorAll('svg');
  for (var c = 0; c < capas.length; c++) {
    var svg = capas[c];
    var anims = svg.querySelectorAll('animate, animateTransform');
    var entra = 0, sale = Infinity;
    for (var i = 0; i < anims.length; i++) {
      var a = anims[i];
      var b = parseFloat(a.getAttribute('begin')) || 0;
      var d = parseFloat(a.getAttribute('dur')) || 0;
      if (b < 0) continue;                       // ya puesto desde el fotograma 0
      if ((a.getAttribute('to') || '').trim() === '0') {
        if (b < sale) sale = b;                  // esto es IRSE
      } else if (b + d > entra) {
        entra = b + d;                           // esto es ENTRAR
      }
    }
    var t = entra + 0.05;
    if (t >= sale) t = (entra + sale) / 2;       // entre que ha entrado y se va
    // CONGELAR y despues colocar. Sin pausar, el tiempo virtual del navegador
    // sigue corriendo desde donde se le deje y la captura acaba cayendo despues
    // del fundido de salida: colocar sin congelar es no colocar.
    if (svg.pauseAnimations) svg.pauseAnimations();
    if (svg.setCurrentTime) svg.setCurrentTime(t);
  }
"""


def previsualizar(ruta_png, ruta_svg, destino, ruta_fija=None, mov=None,
                  lienzo=TAMANO, salida=SALIDA):
    """Compone el CUADRO QUE VA A SALIR en un PNG para la pantalla de revision.

    LO QUE SE APRUEBA TIENE QUE SER LO QUE SE RENDERIZA, y desde que hay dos
    capas eso obliga a componer aqui igual que compone el render. Esto pintaba
    el lienzo de generacion entero (1536x1024) con la capa encima y sin ningun
    zoom: valia mientras la capa iba dentro del zoom -- estaban las dos en el
    mismo espacio y la previa era ese espacio --, pero con el subtitulo fuera
    del zoom no hay un solo espacio en el que quepan las dos.

    Asi que se hace lo mismo que `p8_render.PAGINA`, con la misma matematica y
    el mismo reparto: la imagen dentro de un grupo que lleva el transform de la
    camara, la capa movil dentro de ese grupo, y la capa QUIETA fuera, a 1:1
    sobre el cuadro de salida. Sale un fotograma de 1920x1080 -- el recorte 16:9
    de verdad, con su zoom -- en vez de un 3:2 que el video nunca ensena.

    La camara se coloca en la MITAD del recorrido (`suavizar(0.5)`) y no al
    principio: una previa del fotograma 0 no dice si el zoom se come algo.

    Las capas se incrustan como marcado y no como <img>: dentro de una imagen el
    navegador no siempre corre las animaciones SMIL, y como el texto entra con
    una animacion de opacidad, la vista previa saldria vacia.

    Y se ADELANTA el SVG hasta que todo lo que entra ha entrado (ver
    BUSCAR_ENTRADAS): esperar a ver que pilla la captura daba una previa distinta
    en cada pasada.
    """
    with open(ruta_svg, "r", encoding="utf-8") as fh:
        svg = fh.read()
    fija = ""
    if ruta_fija and os.path.exists(ruta_fija):
        with open(ruta_fija, "r", encoding="utf-8") as fh:
            fija = fh.read()
    ancho, alto = salida
    # La ventana a mitad de recorrido, con la MISMA cuenta que el render
    # (`ventana_en`, que es la que replica `p8_render.ventana()`).
    if mov and mov.get("ventana_ini") and mov.get("ventana_fin"):
        x0, y0, x1, _ = ventana_en(mov, 0.5, lienzo, float(ancho) / float(alto))
    else:
        x0, y0, x1 = 0.0, 0.0, float(lienzo[0])
    escala = ancho / max(1.0, (x1 - x0))
    html = (f'<html><body style="margin:0;width:{ancho}px;height:{alto}px;'
            f'overflow:hidden;background:#0b0c09">'
            f'<div style="position:absolute;left:0;top:0;'
            f'width:{ancho}px;height:{alto}px;overflow:hidden">'
            f'<div style="position:absolute;left:0;top:0;z-index:0;'
            f'transform-origin:0 0;'
            f'transform:translate({-x0 * escala:.3f}px,{-y0 * escala:.3f}px) '
            f'scale({escala:.6f})">'
            f'<img src="file:///{ruta_png.replace(chr(92), "/")}" '
            f'style="display:block;width:{lienzo[0]}px;height:{lienzo[1]}px">'
            f'<div style="position:absolute;left:0;top:0;'
            f'width:{lienzo[0]}px;height:{lienzo[1]}px">{svg}</div>'
            f'</div>'
            # la capa QUIETA, con su z-index dicho y no deducido del orden: en
            # una cabecera el velo de la cartela cubre el cuadro entero, y va
            # dentro del grupo de arriba
            f'<div style="position:absolute;left:0;top:0;z-index:1;'
            f'width:{ancho}px;height:{alto}px">{fija}</div>'
            f'</div>'
            f'<script>{BUSCAR_ENTRADAS}</script>'
            f'</body></html>')
    ruta_html = medios.escribir_texto(destino + ".html", html)
    medios.rasterizar(ruta_html, destino, ancho, alto, transparente=False)
    os.remove(ruta_html)
    _comprobar_previa(destino)
    return destino


#: El fondo del cuadro compuesto, en el HTML de arriba. Sirve de FIRMA: si la
#: esquina no se parece a esto, lo que hay dentro no lo ha pintado esta funcion.
FONDO_PREVIA = (0x0b, 0x0c, 0x09)


def _comprobar_previa(destino):
    """Levanta si el PNG compuesto no es el cuadro, sino otra cosa.

    EDGE NO FALLA CUANDO NO ENCUENTRA ALGO: pinta SU pagina de error --«File not
    found», casi blanca-- y la fotografia. El PNG aparece, `rasterizar` lo da
    por bueno, y lo que se guarda como cuadro de revision es la captura de un
    mensaje de un navegador. El 28-08 habia 820 asi repartidas por cuatro
    versiones, todas de 27 KB, y nadie levanto en ningun sitio: se vieron
    MIRANDO la pantalla.

    La firma es la esquina. Este HTML pinta el fondo a #0b0c09 y encima el plano
    escalado, asi que la esquina de un cuadro de verdad es oscura o es imagen;
    la de la pagina de error es casi blanca. No se mira el peso: un plano
    legitimamente plano pesa poco y seria un falso positivo.

    Levanta y no borra el PNG: quien llama lo recoge como aviso (ver `ejecutar`)
    y asi queda en disco para poder mirarlo si alguien pregunta por que.
    """
    try:
        from PIL import Image                                 # noqa: PLC0415
        esquina = Image.open(destino).convert("RGB").load()[5, 5]
    except Exception:                                         # noqa: BLE001
        return
    if min(esquina) > 200:
        raise RuntimeError(
            f"la previa salio en blanco ({esquina}): Edge ha fotografiado una "
            f"pagina de error en vez del cuadro")


# ------------------------------------------------------------------ capturas

def ruta_movimiento(proyecto):
    """movimiento.json de la version activa del paso, o None si no hay."""
    return medios.salida_de(proyecto, "callouts", claves=("movimiento",),
                            patrones=(r"movimiento\.json",))


def movimientos_de(proyecto):
    """{id de escena: movimiento} de la version activa de callouts."""
    ruta = ruta_movimiento(proyecto)
    datos = medios.leer_json(ruta, {}) if ruta else {}
    return {m["id"]: m for m in (datos.get("movimientos") or []) if m.get("id")}


def _escenas_del_plan(proyecto):
    ruta = medios.salida_de(proyecto, "assets", claves=("plan",),
                            patrones=(r"plan\.json",))
    plan = medios.leer_json(ruta, {}) if ruta else {}
    return {e["id"]: e for e in (plan.get("escenas") or []) if e.get("id")}


def tiempos_de_escena(proyecto):
    """{id: {t_in, t_out}} de la linea de tiempo completa del video.

    Se mira primero lo que dejo callouts, que es lo que el reproductor esta
    ensenando, y solo si falta se recurre al plan de assets.
    """
    tiempos = {}
    for sid, escena in _escenas_del_plan(proyecto).items():
        if escena.get("t_in") is not None and escena.get("t_out") is not None:
            tiempos[sid] = {"t_in": float(escena["t_in"]),
                            "t_out": float(escena["t_out"])}
    for sid, mov in movimientos_de(proyecto).items():
        if mov.get("t_in") is not None and mov.get("t_out") is not None:
            tiempos[sid] = {"t_in": float(mov["t_in"]),
                            "t_out": float(mov["t_out"])}
    return tiempos


def escena_en(proyecto, t_video):
    """Que plano se esta viendo en ese segundo del video, o None."""
    if t_video is None:
        return None
    instante = float(t_video)
    tiempos = tiempos_de_escena(proyecto)
    for sid, tramo in sorted(tiempos.items(), key=lambda kv: kv[1]["t_in"]):
        if tramo["t_in"] <= instante < tramo["t_out"]:
            return sid
    # el ultimo fotograma cae justo en t_out y no pertenece a ningun tramo
    ultimo = max(tiempos.items(), key=lambda kv: kv[1]["t_out"], default=None)
    if ultimo and instante >= ultimo[1]["t_out"]:
        return ultimo[0]
    # y el primer plano no arranca en 0 sino tras el adelanto del audio: sin
    # esto, capturar en 0:00 -- que es donde esta el reproductor al abrirlo --
    # no caia en ningun plano
    primero = min(tiempos.items(), key=lambda kv: kv[1]["t_in"], default=None)
    if primero and instante < primero[1]["t_in"]:
        return primero[0]
    return None


def contexto_temporal(proyecto, escena=None, t_video=None, t_escena=None):
    """Instante de una captura situado en el plano y en el recorrido del zoom.

    Devuelve tambien la frase que se le manda a quien regenera: una nota sobre
    algo que solo ocurre al final del movimiento, sin el instante, se interpreta
    como si valiese para todo el plano.
    """
    sid = str(escena) if escena else escena_en(proyecto, t_video)
    tiempos = tiempos_de_escena(proyecto)
    tramo = tiempos.get(sid) or {}
    t_in = tramo.get("t_in")
    t_out = tramo.get("t_out")
    duracion = (t_out - t_in) if (t_in is not None and t_out is not None) else None

    if t_escena is None and t_video is not None and t_in is not None:
        t_escena = max(0.0, float(t_video) - t_in)
    if t_video is None and t_escena is not None and t_in is not None:
        t_video = t_in + float(t_escena)

    fraccion = None
    if t_escena is not None and duracion:
        fraccion = min(max(float(t_escena) / duracion, 0.0), 1.0)

    mov = movimientos_de(proyecto).get(sid)
    hay_zoom = bool(mov) and mov.get("ventana_ini") != mov.get("ventana_fin")

    ficha = {
        "escena": sid,
        "t_in": round(t_in, 3) if t_in is not None else None,
        "t_out": round(t_out, 3) if t_out is not None else None,
        "duracion": round(duracion, 3) if duracion is not None else None,
        "t_video": round(float(t_video), 3) if t_video is not None else None,
        "t_escena": round(float(t_escena), 3) if t_escena is not None else None,
        "fraccion": round(fraccion, 4) if fraccion is not None else None,
        "zoom": hay_zoom,
    }
    ficha["frase"] = _frase_temporal(ficha)
    return ficha


def _frase_temporal(ficha):
    def coma(valor, decimales=1):
        return f"{float(valor):.{decimales}f}".replace(".", ",")

    if ficha["t_escena"] is None:
        if ficha["t_video"] is None:
            return "el problema no trae instante"
        return f"el problema aparece a {coma(ficha['t_video'])} s de video"
    partes = [f"el problema aparece a {coma(ficha['t_escena'])} s del plano"]
    if ficha["duracion"]:
        partes[0] += f" (de {coma(ficha['duracion'])} s)"
    if ficha["fraccion"] is not None and ficha["zoom"]:
        partes.append(f"con el zoom al {round(ficha['fraccion'] * 100)}% "
                      f"de su recorrido")
    return ", ".join(partes)


def zonas_de_captura(proyecto, captura, aspecto=16 / 9, minimo=0.05):
    """Trazos de una captura -> cajas del PLANO que hay que dejar libres.

    El revisor pinta sobre lo que ve, que es la ventana de zoom de ese instante
    recortada a 16:9. Aqui se deshace ese recorte para que la zona marcada sea
    la del plano, que es donde el paso coloca los rotulos.
    """
    trazos = captura.get("trazos") or []
    if not trazos:
        return []
    escena = captura.get("escena")
    mov = movimientos_de(proyecto).get(str(escena))
    if not mov:
        return []
    contexto = captura.get("contexto") if isinstance(captura.get("contexto"), dict) else {}
    fraccion = contexto.get("fraccion")
    if fraccion is None:
        fraccion = contexto_temporal(proyecto, escena,
                                     captura.get("t_video"),
                                     captura.get("t_escena"))["fraccion"]
    fraccion = 0.0 if fraccion is None else float(fraccion)

    zonas = []
    for trazo in trazos:
        puntos = trazo.get("puntos") or []
        if not puntos:
            continue
        x1, y1 = punto_en_plano(mov, fraccion, min(p["x"] for p in puntos),
                                min(p["y"] for p in puntos), TAMANO, aspecto)
        x2, y2 = punto_en_plano(mov, fraccion, max(p["x"] for p in puntos),
                                max(p["y"] for p in puntos), TAMANO, aspecto)
        # un trazo corto (un circulito, un punto) tiene que seguir prohibiendo
        # un area util, no un pixel
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        ancho = max(x2 - x1, minimo)
        alto = max(y2 - y1, minimo)
        zonas.append({
            "x1": round(max(0.0, cx - ancho / 2), 5),
            "y1": round(max(0.0, cy - alto / 2), 5),
            "x2": round(min(1.0, cx + ancho / 2), 5),
            "y2": round(min(1.0, cy + alto / 2), 5),
            "captura": captura.get("id"),
            "t_escena": captura.get("t_escena"),
        })
    return zonas


def _zonas_de_unidad(p, uid):
    """Zonas a evitar que las capturas aplicadas dejaron en los params del plano."""
    bloque = (p.get("unidades") or {}).get(uid)
    zonas = bloque.get("evitar") if isinstance(bloque, dict) else None
    return [z for z in zonas if isinstance(z, dict)] if isinstance(zonas, list) else []


def texto_subtitulo_de(p, uid):
    """El subtitulo escrito a mano para ese plano, si lo hay. -> str

    Es el cajon de `repaso.CAMBIOS["subtitulo_texto"]`, y vive en la unidad como
    el resto de decisiones por plano: corregir una palabra escrita deja obsoleto
    ESE plano y ninguno mas, y no toca ni la voz ni las imagenes.
    """
    bloque = (p.get("unidades") or {}).get(uid)
    if not isinstance(bloque, dict):
        return ""
    return " ".join(str(bloque.get("subtitulo_texto") or "").split())


def _sin_callout(p, uid):
    """Si el revisor ha apagado la capa de este plano.

    A veces el rotulo sobra y punto: el plano se lee solo, o el callout tapa lo
    unico que hay que mirar. Antes la unica salida era dar feedback y rehacerlo
    esperando que esta vez no pusiera nada, que es pedirle al azar lo que se
    puede decidir. Vive en los params de la unidad, como el resto de decisiones
    por plano, asi que apagarlo solo deja obsoleto ESE plano.
    """
    bloque = (p.get("unidades") or {}).get(uid)
    return bool(bloque.get("sin_callout")) if isinstance(bloque, dict) else False


def capa_vacia(tamano=TAMANO):
    """Capa sin nada. Un SVG valido y del tamano del lienzo, no un fichero vacio.

    El reproductor y el render inyectan este SVG tal cual: si no existiera o no
    fuese valido, la escena se caeria en vez de verse sin rotulo.
    """
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {tamano[0]} {tamano[1]}" '
            f'width="{tamano[0]}" height="{tamano[1]}"></svg>')


def capa_fija_vacia(salida=SALIDA):
    """Lo mismo para la capa QUIETA, que vive en el cuadro de salida."""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="0 0 {salida[0]} {salida[1]}" '
            f'width="{salida[0]}" height="{salida[1]}"></svg>')


#: Cuanto se amplia el fondo de una cartela frente al lienzo de generacion. Es
#: el mismo x2 que el hyperframe de un plano dibujado, y por el mismo motivo: la
#: pagina de render lo coloca a ese tamano.
ESCALA_CARTELA = 2


def _capa_de_cartela(escena, paleta, diseno, dirs, trabajo, svg_ruta, mov_ruta,
                     ficha_ruta, plan, fija_ruta, svg_fijo=None, fichas=None,
                     lienzo=TAMANO, salida=SALIDA):
    """La cartela como plano: fondo al hyperframe, texto animado a la capa.

    No pasa por el motor de movimiento a proposito. Ese motor mira la IMAGEN
    para decidir donde centrar el zoom y cuanto cerrar, y aqui no hay imagen que
    mirar: hay texto compuesto en el centro del cuadro. Un zoom sobre una
    cartela ademas movería el texto mientras se escribe, que es justo lo que no
    se quiere. La camara se queda quieta y lo que se mueve va DENTRO del SVG
    (las palabras entrando, el cursor, la regla, el glifo del fondo).
    """
    sid = escena["id"]
    duracion = float(escena.get("duracion") or
                     (escena.get("t_out", 0) - escena.get("t_in", 0)) or 4.0)
    hyper = os.path.join(dirs["hyper"], f"{sid}.png")
    # La escala va DENTRO del SVG y no solo en la ventana de captura: un SVG se
    # rasteriza a su tamano intrinseco, asi que pedir 3072x2048 de un SVG que se
    # declara de 1536x1024 lo dibuja pequeno en una esquina y deja el resto en
    # blanco (ver cartelas._svg).
    medios.rasterizar(cartelas.svg_fondo(paleta, semilla=_semilla_de(plan),
                                         escala=ESCALA_CARTELA, lienzo=lienzo),
                      hyper, lienzo[0] * ESCALA_CARTELA,
                      lienzo[1] * ESCALA_CARTELA, transparente=False)
    # CUANDO entra cada palabra. Dos casos:
    #
    #   el plano de la cartela   se escribe al ritmo al que la voz lo dice
    #                            (`escritura.tiempos`, que calcula el plan). Si
    #                            no hay con que alinear, sale el ritmo sintetico
    #                            de siempre y no se finge una sincronia que no
    #                            existe.
    #   el plano de continuacion la cartela YA esta escrita: sigue puesta y
    #                            quieta mientras se lee. Volver a animarla la
    #                            reescribiria desde cero en mitad del corte.
    escritura = escena.get("escritura") if isinstance(escena.get("escritura"), dict) else {}
    continua = bool(escritura.get("continua")) or bool(
        (escena.get("cartela") or {}).get("sigue_a"))
    tiempos = list(escritura.get("tiempos") or [])
    if not tiempos and not continua:
        # Con los VECINOS: una cartela destila una frase, y una frase casi nunca
        # empieza justo donde empieza el plano en el que cuelga (PENDIENTE 12).
        antes, despues = cartelas.vecinos_de((plan or {}).get("escenas"), sid)
        tiempos = cartelas.tiempos_dichos(escena["cartela"], escena,
                                          duracion=duracion, diseno=diseno,
                                          antes=antes, despues=despues)
    medios.escribir_texto(svg_ruta, cartelas.svg_capa(
        escena["cartela"], paleta, diseno, duracion=duracion,
        semilla=_semilla_de(plan), tiempos=tiempos, escrita=continua,
        lienzo=lienzo, salida=salida))
    # Y su capa QUIETA con el subtitulo. Iba vacia --«la cartela ES el texto»--
    # y era un agujero en la unica pista que promete estar siempre: once
    # segundos de cabecera sin subtitular. La cabecera ocupa el cuadro y el
    # subtitulo el pie, asi que no se pisan.
    medios.escribir_texto(fija_ruta, svg_fijo or capa_fija_vacia())

    entrada = {
        "id": sid,
        "hyperframe": os.path.relpath(hyper, trabajo),
        "hyperframe_px": [lienzo[0] * ESCALA_CARTELA, lienzo[1] * ESCALA_CARTELA],
        "ventana_ini": [0.0, 0.0, 1.0, 1.0],
        "ventana_fin": [0.0, 0.0, 1.0, 1.0],
        "centro": [0.5, 0.5],
        "origen_centro": "cartela",
        "capa": os.path.relpath(svg_ruta, trabajo),
        "capa_fija": os.path.relpath(fija_ruta, trabajo),
        "t_in": escena.get("t_in"), "t_out": escena.get("t_out"),
    }
    medios.escribir_json(mov_ruta, entrada)
    ficha = {"svg": os.path.relpath(svg_ruta, trabajo),
             "svg_fijo": os.path.relpath(fija_ruta, trabajo),
             "movimiento": os.path.relpath(mov_ruta, trabajo),
             "hyperframe": entrada["hyperframe"],
             "cartela": escena["cartela"].get("plantilla"),
             "zonas_evitadas": 0, "sin_callout": False,
             "elementos": list(fichas or []),
             "region_segura": list(cartelas.SEGURO),
             "centro": entrada["centro"], "origen_centro": "cartela",
             "ventana_ini": entrada["ventana_ini"],
             "ventana_fin": entrada["ventana_fin"]}
    medios.escribir_json(ficha_ruta, ficha)
    return ficha


def _en_la_banda(svg, ancho, alto):
    """La capa de una cartela, recortada a lo que de verdad sale en cuadro.

    El lienzo de las cartelas es 1536x1024 (3:2) y lo que se ve es
    `cartelas.BANDA`, que dentro de el mide 16:9. Se cambia el `viewBox` y se
    conserva el interior tal cual -- las animaciones SMIL incluidas --, que es lo
    mismo que hace `cartelas.muestra_de` para dibujar una plantilla pequena.
    """
    interior = svg[svg.index(">") + 1:-len("</svg>")]
    bx, by, bx2, by2 = cartelas.BANDA
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{bx} {by} {bx2 - bx} {by2 - by}" '
            f'width="{int(ancho)}" height="{int(alto)}">{interior}</svg>')


def _semilla_de(plan):
    """La semilla del video, para que el grano de la cartela no cambie solo.

    La escribe p6 en el plan, derivada del id del proyecto: asi dos videos del
    mismo canal no salen con el grano calcado.
    """
    return int((plan or {}).get("semilla")
               or medios.desempatar((plan or {}).get("proyecto") or ""))


# ------------------------------------------------------------------ ejecutar

def ejecutar(proyecto, params, avisar=None, unidades=None):
    """Capa vectorial y movimiento de cada plano. Si unidades no es None, solo esas."""
    arranque_paso = time.time()
    p = _con_defectos(params)
    avisar = estadisticas.avisador(avisar)

    ruta_plan = params.get("plan") if params else None
    ruta_plan = ruta_plan or medios.salida_de(proyecto, "assets", claves=("plan",),
                                              patrones=(r"plan\.json",))
    if not ruta_plan:
        raise RuntimeError("el paso assets no ha dejado plan.json")
    plan = medios.leer_json(ruta_plan, {})
    base_assets = os.path.dirname(ruta_plan)
    dir_escenas = os.path.join(base_assets, "escenas")
    dir_assets = os.path.join(base_assets, "assets")

    trabajo = medios.sembrar_trabajo(proyecto, "callouts")
    dirs = {"capas": os.path.join(trabajo, "capas"),
            # LA CAPA QUIETA VA EN SU PROPIA CARPETA, no con otro nombre dentro
            # de `capas`: son dos espacios de coordenadas distintos (el lienzo
            # de generacion y el cuadro de salida) y mezclarlos en un directorio
            # invita a que alguien lea una donde toca la otra.
            "capas_fijas": os.path.join(trabajo, "capas_fijas"),
            "movimiento": os.path.join(trabajo, "movimiento"),
            "hyper": os.path.join(trabajo, "hyper"),
            "previo": os.path.join(trabajo, "previo")}
    for ruta in dirs.values():
        os.makedirs(ruta, exist_ok=True)

    escenas = plan.get("escenas") or []
    pedidas = set(unidades) if unidades is not None else None
    movimiento = medios.motor("render_video/movimiento.py")
    # EL FORMATO DEL VIDEO, del plan: el cuadro de salida, el
    # lienzo de generacion y su aspecto. Todo lo de abajo los recibe de aqui.
    salida = salida_de(plan)
    lienzo = lienzo_de(plan)
    aspecto = float(salida[0]) / float(salida[1])
    resultados = {}
    avisos = []

    # LA GUIA DE ESTILO SALE DEL PLAN, no de los params de este paso.
    #
    # `capa_de_escena` deriva los colores de `p["estilo"]["guia"]`, pero
    # `estilo` es un parametro de ASSETS: en los params de callouts no existe y
    # nunca ha existido. O sea que la derivacion caia siempre al respaldo y el
    # video se rotulaba con los cinco colores escritos a mano, mientras la
    # pantalla de Rotulos ensenaba las muestras con los colores de la guia --
    # que es lo que app.py si sabe hacer. Se elegia mirando una paleta y se
    # renderizaba con otra. El plan trae `estilo` dentro (lo escribe p6), asi
    # que aqui hay de donde sacarlo.
    p.setdefault("estilo", {})
    if not (p["estilo"] or {}).get("guia") and (plan.get("estilo") or {}).get("guia"):
        p["estilo"] = plan["estilo"]
    paleta_video = paleta_de_guia((p.get("estilo") or {}).get("guia"), p["paleta"])
    # El grafismo de este video: el MISMO set decide como se envuelve un rotulo
    # y como se escribe una cartela. Un video tiene un grafismo, no dos.
    _, ficha_diseno = diseno_de(p)

    # LA BANDA DEL SUBTITULO ES EL PIE DEL CUADRO DE SALIDA, y ya esta.
    #
    # Aqui habia una interseccion de las regiones seguras de los 49 planos --lo
    # que se ve durante el recorrido de camara de TODOS ellos-- y tenia su
    # motivo: la capa iba dentro del zoom, asi que el subtitulo se movia con la
    # imagen y anclarlo al suelo de cada plano lo hacia saltar 95 px de un corte
    # al siguiente (medido). Con la capa fuera del zoom (PENDIENTE 38) no hay
    # nada que intersecar: el subtitulo vive en 1920x1080 y no se mueve.
    #
    # Se sigue calculando UNA VEZ para el video entero y se pasa a cada plano,
    # aunque ya no dependa de ninguno: asi la vista previa y el repaso reciben
    # exactamente la misma, que es lo que sostiene que lo aprobado sea lo
    # renderizado.
    banda = banda_subtitulo(salida)

    for indice, escena in enumerate(escenas):
        sid = escena["id"]
        uid = f"escena:{sid}"
        svg_ruta = os.path.join(dirs["capas"], f"{sid}.svg")
        fija_ruta = os.path.join(dirs["capas_fijas"], f"{sid}.svg")
        mov_ruta = os.path.join(dirs["movimiento"], f"{sid}.json")
        ficha_ruta = os.path.join(dirs["movimiento"], f"{sid}.ficha.json")
        previo = os.path.join(dirs["previo"], f"{sid}.png")
        avisar(0.02 + 0.94 * (indice / max(1, len(escenas))),
               f"capa de {sid} · {indice + 1} de {len(escenas)}",
               (indice + 1, len(escenas)))

        # SE CONSERVA LO QUE ESTA ENTERO, y desde el 23-08 «entero» son DOS
        # ficheros. Sin mirar tambien la capa quieta, un plano montado antes de
        # que existiera se daria por bueno al «Regenerar lo obsoleto» y se
        # quedaria sin subtitulo en el video, sin decir nada: la capa que le
        # falta no la echa de menos nadie hasta verlo montado.
        if (pedidas is not None and uid not in pedidas
                and os.path.exists(svg_ruta) and os.path.exists(fija_ruta)):
            guardada = medios.leer_json(ficha_ruta, {}) or {
                "svg": os.path.relpath(svg_ruta, trabajo),
                "svg_fijo": os.path.relpath(fija_ruta, trabajo),
                "movimiento": os.path.relpath(mov_ruta, trabajo),
                "origen": "conservado"}
            resultados[uid] = guardada
            continue

        # Una cartela de fondo NEGRO no pasa por el motor de movimiento: no
        # hay imagen que mirar. Una cartela SOBRE IMAGEN si -- debajo hay un
        # plano de verdad, con su zoom -- y lo unico que cambia es su capa.
        if cartelas.sin_imagen(escena):
            # capa fija VACIA por lo mismo que en la cartela sobre imagen: la
            # cartela es el texto, y un subtitulo debajo repite lo que ya se lee
            resultados[uid] = _capa_de_cartela(
                escena, paleta_video, ficha_diseno, dirs, trabajo, svg_ruta,
                mov_ruta, ficha_ruta, plan, fija_ruta,
                capa_fija_vacia(salida), [], lienzo=lienzo, salida=salida)
            continue

        png = os.path.join(dir_escenas, f"{sid}.png")
        if not os.path.exists(png):
            raise RuntimeError(f"{sid}: falta la imagen {png}")

        # el movimiento va primero: la capa necesita saber que trozo del plano
        # sigue en cuadro durante todo el zoom para no rotular fuera de campo
        entrada = movimiento.calcular({"escenas": [escena]}, dir_escenas,
                                      dirs["hyper"], os.path.join(dir_assets, "sets"),
                                      int(p["escala_hyper"]))[0]
        evitar = _zonas_de_unidad(p, uid)
        apagada = _sin_callout(p, uid)
        if cartelas.sobre_imagen(escena):
            # el plano se ha rodado y tiene su zoom; encima va el velo y el
            # texto de la cartela, no los rotulos de siempre
            duracion_c = float(escena.get("duracion") or
                               (escena.get("t_out", 0) - escena.get("t_in", 0)) or 4.0)
            escritura = escena.get("escritura") if isinstance(
                escena.get("escritura"), dict) else {}
            continua = bool(escritura.get("continua")) or bool(
                (escena.get("cartela") or {}).get("sigue_a"))
            tiempos = list(escritura.get("tiempos") or [])
            if not tiempos and not continua:
                antes, despues = cartelas.vecinos_de(escenas, sid)
                tiempos = cartelas.tiempos_dichos(escena["cartela"], escena,
                                                  duracion=duracion_c,
                                                  diseno=ficha_diseno,
                                                  antes=antes, despues=despues)
            # LA CARTELA VA EN LA CAPA QUE ESCALA, y es deliberado: su velo
            # oscurece la imagen y su texto acompana al plano. Fuera del zoom
            # quedaria flotando sobre una imagen que se mueve debajo, que es
            # exactamente lo que se quiere para el subtitulo y lo contrario de
            # lo que se quiere para una cabecera (PENDIENTE 38).
            svg = cartelas.svg_capa(escena["cartela"], paleta_video, ficha_diseno,
                                    duracion=duracion_c,
                                    semilla=_semilla_de(plan),
                                    tiempos=tiempos, escrita=continua,
                                    lienzo=lienzo, salida=salida)
            # SIN SUBTITULO: LA CARTELA ES EL TEXTO DE ESTE PLANO.
            #
            # Estuvo al reves --cabecera arriba, subtitulo al pie, «no se
            # pisan»-- para no dejar huecos en la pista de subtitulos. Pero no
            # es un hueco: en un plano de cartela lo que hay que leer YA esta
            # escrito, a tamano de titular y en el centro, y ponerle debajo la
            # misma frase en pequeno son dos textos compitiendo por la misma
            # atencion. Decision del 31-08.
            fija, fichas = capa_fija_vacia(salida), []
        elif apagada:
            # el movimiento SI se calcula: el plano sigue teniendo su zoom y su
            # transicion, lo unico que se va es el texto
            svg, fija, fichas = capa_vacia(lienzo), capa_fija_vacia(salida), []
        else:
            svg, fija, fichas = capa_de_escena(escena, p, entrada, banda, aspecto,
                                               lienzo, salida)
        medios.escribir_texto(svg_ruta, svg)
        medios.escribir_texto(fija_ruta, fija)
        entrada["capa"] = os.path.relpath(svg_ruta, trabajo)
        entrada["capa_fija"] = os.path.relpath(fija_ruta, trabajo)
        medios.escribir_json(mov_ruta, entrada)

        ficha = {"svg": os.path.relpath(svg_ruta, trabajo),
                 "svg_fijo": os.path.relpath(fija_ruta, trabajo),
                 "zonas_evitadas": len(evitar),
                 "sin_callout": apagada,
                 "cartela": (escena.get("cartela") or {}).get("plantilla"),
                 "movimiento": os.path.relpath(mov_ruta, trabajo),
                 "hyperframe": os.path.relpath(
                     os.path.join(dirs["hyper"], f"{sid}.png"), trabajo),
                 "elementos": fichas,
                 "region_segura": [round(v) for v in
                                   region_segura(entrada, lienzo, aspecto)],
                 "centro": entrada["centro"],
                 "origen_centro": entrada["origen_centro"],
                 "ventana_ini": entrada["ventana_ini"],
                 "ventana_fin": entrada["ventana_fin"]}
        # LA PREVIA NO PUEDE TUMBAR EL PASO. Es una comodidad --el cuadro ya
        # compuesto para mirarlo antes de montar-- y el render no la necesita
        # para nada: se rasteriza con Edge, y un Edge que se cae en un plano se
        # llevaba por delante una tanda con los 222 planos ya calculados.
        #
        # Se dice en los avisos y se sigue. El previsualizador sabe vivir sin
        # ella: sin cuadro compuesto ensena la imagen con sus subtitulos.
        # Y LAS DE CARTELA TAMBIEN SE COMPONEN, aunque no tengan elementos.
        # Antes la condicion era solo `fichas` y una cartela deja esa lista
        # vacia, asi que esas quince escenas se quedaban sin cuadro compuesto:
        # el previsualizador caia a la imagen cruda y dibujaba subtitulos que el
        # video no tiene, sin ensenar la cartela que si tiene. Justo lo
        # contrario de lo que esta pantalla promete.
        if p["previsualizar"] and (fichas or cartelas.sobre_imagen(escena)):
            try:
                ficha["previo"] = os.path.relpath(
                    previsualizar(png, svg_ruta, previo, fija_ruta, entrada,
                                  lienzo=lienzo, salida=salida),
                    trabajo)
            except Exception as fallo:                        # noqa: BLE001
                avisos.append(f"{sid}: no se ha podido componer la previa "
                              f"({str(fallo)[:120]})")
        medios.escribir_json(ficha_ruta, ficha)
        resultados[uid] = ficha

    completo = {"fps": plan.get("fps", 30),
                "resolucion": plan.get("resolucion", [1920, 1080]),
                # La paleta viaja al render porque las transiciones la usan: sus
                # shaders llevan tres uniformes de acento y de ahi sale que el
                # destello de un corte sea del color de los rotulos de ESTE
                # video. p8 no puede derivarla -- la guia esta en los params de
                # assets-- y quien la tiene resuelta es este paso.
                "paleta": paleta_video,
                "movimientos": [medios.leer_json(
                    os.path.join(dirs["movimiento"], f"{e['id']}.json"), {})
                    for e in escenas]}
    medios.escribir_json(os.path.join(trabajo, "movimiento.json"), completo)

    # los assets son unidades heredadas del paso anterior: aqui no producen
    # nada propio, pero hay que sellarlas o el paso jamas llegaria a 'listo'
    for usados in (plan.get("dependencias") or {}).values():
        for uid in usados:
            resultados.setdefault(uid, {"heredado": "assets"})

    # igual que en assets: solo se sellan las unidades rehechas en esta pasada
    if pedidas is None:
        rehechas = dict(resultados)
    else:
        rehechas = {uid: ficha for uid, ficha in resultados.items() if uid in pedidas}

    # LO QUE SE CUENTA ES LO QUE HAY. Decia «N capas (M con rotulo), K sin hueco
    # limpio» y ya no hay rotulos ni huecos que buscar: un
    # subtitulo no flota, vive abajo y no hay nada que colocar. Lo que se cuenta
    # ahora son los TROZOS de subtitulo --que es el trabajo de verdad de este
    # paso-- y los planos que no llevan ninguno, que son las cartelas y los
    # planos cuyas marcas no cuadraban con su texto (`subtitulos.de_escena`
    # devuelve [] antes que fingir una sincronia).
    trozos = sum(len(r.get("elementos") or []) for r in resultados.values())
    con_texto = sum(1 for r in resultados.values() if r.get("elementos"))
    salidas = {"movimiento": "movimiento.json", "capas": "capas",
               "capas_fijas": "capas_fijas",
               "hyperframes": "hyper", "previos": "previo",
               "n_escenas": len(escenas), "avisos": avisos,
               "resumen": (f"{len(escenas)} capas, {trozos} trozos de subtítulo "
                           f"en {con_texto} planos")}
    avisar(1.0, salidas["resumen"])
    # El tiempo REAL de esta tanda, al historico: es lo unico que hace que la
    # barra deje de prometer la tabla del primer dia (ver p6._anotar_tiempo).
    # Lo que se mide es lo REHECHO, no las escenas del plan: una pasada que
    # conserva 220 de 226 no dice lo que cuesta hacer 226 (ver
    # `p6_assets._anotar_tiempo`).
    try:
        if rehechas:
            estadisticas.anotar("callouts",
                                max(0.01, time.time() - arranque_paso),
                                tamano=len(rehechas),
                                proyecto=getattr(proyecto, "id", None),
                                detalle={"rehechas": len(rehechas),
                                         "trozos": trozos})
    except Exception:                                       # noqa: BLE001
        pass
    return {"salidas": salidas, "unidades": rehechas, "todas": resultados,
            "conservadas": sorted(uid for uid in resultados if uid not in rehechas),
            "avisos": avisos}
