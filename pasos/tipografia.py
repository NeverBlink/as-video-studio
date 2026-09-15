"""Medir texto con la fuente de verdad, y partirlo para que quepa.

Estaba dentro de p7_callouts y salio de ahi cuando aparecieron las cartelas
(`pasos/cartelas.py`), que necesitan medir exactamente igual: p7 dibuja la capa
que va ENCIMA de un plano y cartelas dibuja el plano entero, pero los dos parten
un texto en lineas y las dos medidas tienen que ser la misma. Con la funcion en
p7 no habia forma -- p7 importa cartelas para dibujar las cartelas, asi que
cartelas no puede importar p7 --, y copiarla habria dejado dos medidas que se
separan en cuanto alguien toque una.

Aqui no hay ninguna decision de diseno: solo la cuenta. Que letra y que tamano
lleva cada cosa lo deciden los arquetipos de p7 y las plantillas de cartelas.
"""
import os
import sys

from PIL import ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Donde viven los FICHEROS de fuente. En Windows son las del sistema; en el
#: servidor se copian LAS MISMAS a una carpeta propia y se apunta con
#: ESTUDIO_FUENTES. Tienen que ser los mismos ficheros: medir con una fuente y
#: dibujar con otra da una cuenta bien y un numero mal (ver `p7_callouts`).
CARPETA_FUENTES = os.environ.get("ESTUDIO_FUENTES") or r"C:\Windows\Fonts"


def _ttf(nombre):
    return os.path.join(CARPETA_FUENTES, nombre)


#: Las fuentes del sistema, en pares (normal, negrita).
FUENTES = {
    "verdana": (_ttf("verdana.ttf"), _ttf("verdanab.ttf")),
    "arial": (_ttf("arial.ttf"), _ttf("arialbd.ttf")),
    "tahoma": (_ttf("tahoma.ttf"), _ttf("tahomabd.ttf")),
    "georgia": (_ttf("georgia.ttf"), _ttf("georgiab.ttf")),
    "consolas": (_ttf("consola.ttf"), _ttf("consolab.ttf")),
    # La del cierre de marca del motor anterior, y la unica que no elige un preset:
    # la web usa Inter, que no viene con Windows, y Segoe UI es la grotesca del
    # sistema que mas se le parece (misma anchura de trazo y mismas
    # proporciones). Se mide con la que se dibuja: ver `cartelas.MARCA_LETRA`.
    "segoe ui": (_ttf("segoeui.ttf"), _ttf("segoeuib.ttf")),
}

_fuentes = {}


def fuente(nombre, tam, negrita=False):
    """Fuente real del sistema, la misma que luego pinta el navegador."""
    clave = (nombre.lower(), int(tam), bool(negrita))
    if clave not in _fuentes:
        rutas = FUENTES.get(nombre.lower()) or FUENTES["verdana"]
        _fuentes[clave] = ImageFont.truetype(rutas[1 if negrita else 0], int(tam))
    return _fuentes[clave]


# Lo que PIL se queda corto respecto a lo que dibuja el navegador.
#
# Medido el 15-08-2026 con Verdana, la misma cadena y el mismo tamano, contra
# canvas.measureText en el navegador que luego rasteriza el SVG:
#
#     "Nadie sabia nada de aquel cargamento"  12px   PIL 229   navegador 235
#     "Una nota cualquiera"                   12px   PIL 120   navegador 121
#     "UDAI HUSSEIN" (negrita, +3 espaciado)  14px   PIL 156   navegador 154
#
# O sea hasta un 2,6% corto. La caja del rotulo se dimensiona con esta medida,
# asi que ese 2,6% se lo come el margen derecho: en «cita» quedaban 22 px de
# aire a la izquierda y 8 a la derecha, y con una frase un poco mas larga el
# texto toca el borde. No es solo cosa de la muestra: en la capa de verdad pasa
# igual, escalado.
#
# 4% de margen cubre el peor caso medido con holgura y no se nota: son 9 px en
# un rotulo de 230.
MARGEN_MEDIDA = 1.04


def medir(texto, nombre, tam, negrita=False, espaciado=0):
    """Ancho y alto en pixeles del texto, medidos con la fuente de verdad.

    Se mide el AVANCE (getlength) y no la caja de tinta (getbbox). La caja de
    tinta acaba en el ultimo pixel pintado, y una 'o' final pinta menos ancho
    del que ocupa: la caja del rotulo salia corta y el texto se salia por la
    derecha. Y el espaciado se cuenta por cada letra, no por los huecos: los
    navegadores lo anaden TAMBIEN detras de la ultima, que es lo que se dibuja
    de verdad aunque no sea lo que parece.

    Y aun asi PIL se queda corto frente al navegador: ver MARGEN_MEDIDA.
    """
    tipo = fuente(nombre, tam, negrita)
    try:
        avance = tipo.getlength(texto)
    except AttributeError:                 # Pillow antiguo
        caja = tipo.getbbox(texto)
        avance = caja[2] - caja[0]
    ancho = avance * MARGEN_MEDIDA + espaciado * len(texto)
    return int(round(ancho)), int(tam * 1.25)


def partir(texto, nombre, tam, negrita, espaciado, ancho_max):
    """Parte el texto en lineas que quepan en ancho_max."""
    palabras = str(texto).split()
    lineas, actual = [], ""
    for palabra in palabras:
        prueba = (actual + " " + palabra).strip()
        if medir(prueba, nombre, tam, negrita, espaciado)[0] <= ancho_max or not actual:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def escapar(texto):
    """El texto, listo para meterlo dentro de un SVG."""
    return (str(texto).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def encajar(texto, nombre, tam, negrita, espaciado, ancho_max, alto_max,
            minimo=None, interlineado=1.25, lineas_max=None):
    """Baja el tamano hasta que el texto quepa en la caja. Devuelve (lineas, tam).

    Es lo que hace que una cartela no pueda salir mal: la plantilla pide un
    tamano y este texto concreto se queda con el que de verdad entra. Sin esto,
    una cifra de dos digitos y una de siete se dibujan igual de grandes y la
    segunda se sale del cuadro -- que es exactamente el fallo que tenian las
    composiciones libres.

    SE COMPRUEBA EL ANCHO DE CADA LINEA, no solo el alto. Antes solo se miraba
    el alto, y con un texto que no se puede partir -- «30.000.000», una palabra
    larga -- `partir` devuelve una sola linea igual de larga pase lo que pase
    (mete siempre la primera palabra aunque no quepa). El alto cuadraba, se daba
    por bueno, y el numero se salia por los dos lados. Se veia en el video: una
    cartela con la cifra tocando ambos bordes.

    `lineas_max` es el tope de renglones. Un pie de cifra en cuatro lineas cabe
    de alto y se lee fatal: lo que hace falta es que baje de tamano hasta caber
    en una o dos.

    El suelo es el 45% del tamano pedido salvo que se diga otro: por debajo el
    rotulo deja de leerse a tamano de video y es mejor que se note que ese texto
    es demasiado largo para su plantilla.
    """
    suelo = int(minimo if minimo is not None else max(12, tam * 0.45))
    actual = max(int(tam), suelo)
    while True:
        lineas = partir(texto, nombre, actual, negrita, espaciado, ancho_max)
        cabe = (len(lineas) * int(actual * interlineado) <= alto_max
                and (lineas_max is None or len(lineas) <= lineas_max)
                and all(medir(linea, nombre, actual, negrita, espaciado)[0]
                        <= ancho_max for linea in lineas))
        if cabe or actual <= suelo:
            return lineas, actual
        actual = min(actual - 1, int(actual * 0.94))


def encajar_pocas_lineas(texto, nombre, tam, negrita, espaciado, ancho_max,
                         alto_max, lineas=(1, 2), minimo=None, interlineado=1.25):
    """Como `encajar`, pero probando primero a meterlo en UNA linea.

    Un pie de cartela partido en dos se lee peor que el mismo pie una pizca mas
    pequeno de un tirón, y en tres se lee mal a secas. Asi que se intenta con
    una linea bajando bastante el tamano, y solo si ahi no cabe se admite la
    segunda -- con el suelo mas alto, porque dos lineas ya reparten el ancho.
    """
    for indice, tope in enumerate(lineas):
        # con una sola linea se puede bajar mas: sigue leyendose de un vistazo
        suelo = int(minimo if minimo is not None
                    else max(14, tam * (0.52 if indice == 0 else 0.42)))
        hechas, usado = encajar(texto, nombre, tam, negrita, espaciado,
                                ancho_max, alto_max, minimo=suelo,
                                interlineado=interlineado, lineas_max=tope)
        if len(hechas) <= tope and usado > suelo:
            return hechas, usado
    return encajar(texto, nombre, tam, negrita, espaciado, ancho_max, alto_max,
                   minimo=minimo, interlineado=interlineado,
                   lineas_max=lineas[-1] if lineas else None)
