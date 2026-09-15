"""La cartela: un plano que no es una imagen generada, sino texto sobre negro.

QUE PROBLEMA RESUELVE
---------------------
Hasta ahora todo rotulo iba ENCIMA del plano generado, y para no tapar al
personaje habia que buscarle un hueco: mascara de detalle, transformada de
distancia, catorce candidatos y una comprobacion por pixeles (p7_callouts). Esa
maquina funciona, pero su resultado depende de la imagen que le toque -- un
plano lleno de dibujo no tiene hueco bueno, y ahi el rotulo sale donde puede.

La cartela le quita el problema de encima: no busca hueco porque ES el plano.
Fondo casi negro con textura, y el texto escribiendose palabra a palabra. Sale
bien siempre, porque no hay nada debajo con lo que pelearse.

POR QUE UN PLANO ENTERO Y NO UN INSERTO
---------------------------------------
El corte ya reparte la narracion en planos de 3 a 6 segundos, y esos limites los
marcan las palabras de la voz. Una cartela ocupa uno de esos huecos completo: no
hay que partir ningun clip, la duracion sigue cuadrando al milimetro con el
audio, y ese plano deja de costar una imagen de OpenAI. Lo decide el plan, antes
de generar nada, para no pagar una imagen que se va a tirar.

DE DONDE SALEN LAS PLANTILLAS
-----------------------------
Del sistema declarativo `SC` del motor anterior:
cada escena declara un ARQUETIPO con huecos, en vez de una composicion escrita a
medida. Alli tambien habia un modo libre (`custom`, JSX a mano por escena) y es
exactamente el que fallaba: las composiciones complejas salian mal y no se veia
hasta renderizar el video entero.

Aqui no existe el modo libre. Hay diez plantillas cerradas, el agente solo
rellena sus huecos, y el dibujado ENCAJA el texto en su caja bajando el tamano
hasta que entra (`tipografia.encajar`). Una cartela no puede salir rota: como
mucho sale con la letra mas pequena de lo que pedia su plantilla.

QUE ES DETERMINISTA Y QUE NO
----------------------------
Lo unico que decide un modelo es QUE plano lleva cartela y QUE pone. Eso se
guarda en el plan y a partir de ahi es un dato: el mismo plan da el mismo SVG,
byte a byte. Es el mismo contrato que el catalogo visual, la guia de estilo y el
plan de rotulos.

LAS TRES SALIDAS, Y POR QUE SON TRES
------------------------------------
    svg_fondo()   fondo + textura, sin texto.  -> p7 lo rasteriza al hyperframe
    svg_capa()    solo el texto, animado.      -> p7 lo escribe como capa
    svg_carta()   las dos cosas.               -> la rejilla (quieta) y el
                                                  repaso del montaje (animada)

Las tres se montan con las MISMAS piezas. La de la rejilla de planos no puede
ensenar una cartela distinta de la que se va a renderizar, que es el mismo
principio que las muestras de arquetipo (p7_callouts.muestra_de).

UNA CARTELA OCUPA EL TRAMO EN EL QUE SE DICEN SUS PALABRAS
----------------------------------------------------------
Ese es el enunciado, y de el salen las dos direcciones como consecuencia en vez
de ser dos casos especiales:

    encaje_de()        en que tramo del VIDEO se dicen sus palabras, buscando en
                       una VENTANA de tres planos -- el anterior, el suyo y el
                       siguiente --, porque una cartela destila una FRASE y una
                       frase casi nunca empieza donde empieza el plano.
    escritura_de()     ese encaje metido en el plano que la va a llevar: cuando
                       entra cada palabra, y si le falta tiempo por delante
                       ('falta') o sus palabras empiezan antes ('antes').
    ocupacion_de()     cuantos planos ocupa cada candidata, ANTES de repartir,
                       porque una que ocupa dos consume dos del reparto.

Lo aplica `p6._estirar_cartelas`, al PLANIFICAR: el plano absorbido deja de
generarse, asi que decidirlo de base ahorra una imagen y decidirlo despues seria
tirar una pagada.

Y LO QUE HACE QUE ESTO FUNCIONE ES QUE LA CARTELA DESTILA
---------------------------------------------------------
No repite la narracion: abrevia la cifra y se queda con el nucleo de la frase.
Eso es el ESTILO y se queda, asi que el trabajo es del motor: sincronizar un
texto destilado. Lo que sabe emparejar vive en `medios` -- cifras en otra
notacion, una palabra escrita que es un tramo de varias habladas, comparacion
simetrica -- y lo comparte con los rotulos (`p6._indice_de`). Si viviera aqui
solo, las dos formas de casar texto con voz se separarian y la que se quedara
vieja fallaria en silencio.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import medios  # noqa: E402
import tipografia  # noqa: E402

try:
    from . import cli_claude, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import estadisticas

PASO = "plan_cartelas"

#: El lienzo es el mismo que el de los planos generados, a proposito: asi la
#: cartela pasa por toda la tuberia (hyperframe, capa, movimiento, render) sin
#: que ningun paso tenga que saber de que clase es este plano.
TAMANO = (1536, 1024)

#: Lo que de verdad queda en cuadro: el video recorta 16:9 sobre un lienzo 3:2,
#: asi que arriba y abajo se pierden 80 px. Escribir fuera de esta banda es
#: escribir donde nadie va a leer.
BANDA = (0, 80, 1536, 944)

#: Y donde puede haber texto, con margen para respirar. Todo lo que dibuja una
#: plantilla cabe aqui dentro: 1316 x 706.
SEGURO = (110, 160, 1426, 866)

#: Cuanto tarda en escribirse cada palabra, en segundos. Se ajusta a la duracion
#: del plano entre estos dos limites: por debajo de 0,09 no se lee que se esta
#: escribiendo (parece un fundido) y por encima de 0,32 se hace lento.
S_POR_PALABRA = (0.09, 0.32)

#: La fraccion del plano en la que tiene que estar escrito TODO. El resto es
#: cola: el texto completo tiene que quedarse en pantalla el tiempo suficiente
#: para leerlo entero, y esto es lo que lo garantiza sin mirar cuantas palabras
#: hay. (En el motor anterior la regla equivalente costo una ronda de correcciones:
#: las cabeceras se iban antes de poder leerlas.)
FRACCION_ESCRITURA = 0.62

#: Retardo de entrada. No es cero a proposito: el corte tiene que verse antes de
#: que empiece a pasar nada, o la primera palabra se come el cambio de plano.
ENTRADA = 0.22

#: Cuanto de la region segura usa como mucho un TITULAR. El resto es aire: un
#: titular que llega justo a los dos bordes se lee apretado aunque quepa, y la
#: primera cartela renderizada («30.000.000») salio asi.
AIRE_TITULAR = 0.88

#: Y cuanto se aparta cada columna de `contraste` del borde y de la raya del
#: medio. Con la mitad justa, la cifra de la izquierda tocaba las dos.
MARGEN_COLUMNA = 150

#: Renglones como mucho de una frase grande. En tres deja de leerse de un
#: vistazo, que es justo lo que hace una cartela.
LINEAS_TITULAR = 2

#: EN VERTICAL LA CARTELA SE COMPONE A TAMANO NATURAL Y EN LA BANDA VISIBLE.
#: La primera version anidaba la composicion entera (1536 de ancho) escalada
#: al ancho visible del 9:16 (864 de los 1024 del lienzo): la mitad de tamano,
#: y con el titular pegado al borde izquierdo de la region segura, que en un
#: cuadro estrecho es el borde del cuadro. El canal lo vio en el movil: «mas
#: grandes y centradas». Ahora la composicion va a escala 1 --el mismo tamano
#: en pantalla que en horizontal, porque el recorte 1024->864->1080 es el
#: mismo x1,25 que 1536->1920-- y las plantillas componen dentro de una region
#: segura ESTRECHA y centrada, la banda que de verdad se ve, con este margen a
#: cada lado. Lo que no cabe a lo ancho lo encoge `tipografia.encajar`, como
#: siempre.
ESCALA_VERTICAL = 1.0
MARGEN_VERTICAL = 40


def seguro_vertical(lienzo, salida, escala=ESCALA_VERTICAL):
    """La region segura de una cartela en un lienzo alto. -> (x0, y0, x1, y1)

    En coordenadas de la plantilla (TAMANO): la banda visible del video,
    centrada, con margen. Ver ESCALA_VERTICAL.
    """
    w, _h = TAMANO
    lw, lh = float(lienzo[0]), float(lienzo[1])
    visible = lw
    if salida and salida[0] and salida[1]:
        visible = min(lw, lh * float(salida[0]) / float(salida[1]))
    ancho = visible / float(escala)
    x0 = (w - ancho) / 2.0 + MARGEN_VERTICAL
    x1 = (w + ancho) / 2.0 - MARGEN_VERTICAL
    return (int(round(x0)), SEGURO[1], int(round(x1)), SEGURO[3])



# ===========================================================================
# LAS PLANTILLAS
#
# Cada una declara sus HUECOS y nada mas. El limite de caracteres no es una
# manía: es lo que separa «el agente escribio de mas» de «la cartela salio
# rota». Se recorta al validar, antes de dibujar, y se avisa.
#
#   campos    nombre -> (obligatorio, tope de caracteres)
#   lista     si uno de los campos es una lista, cuantos elementos admite
#   cuando    lo que lee el agente para decidir si esta plantilla es la suya
# ===========================================================================

PLANTILLAS = {
    "cifra": {
        "nombre": "La cifra",
        "descripcion": "El número a pantalla completa, con lo que es debajo. Cuando la narración dice una cantidad que ES el plano.",
        "cuando": "la narración dice una cifra que impacta y que quieres que se lea, no que se oiga y pase",
        "campos": {"cifra": (True, 14), "label": (True, 44), "nota": (False, 70),
                   "icono": (False, 20)},
        "ejemplo": {"cifra": "10.000.000", "label": "cuentas de clientes a la venta",
                    "nota": "Manzanillo, octubre de 2007", "icono": "base_datos"},
    },
    "cita": {
        "nombre": "La cita",
        "descripcion": "Lo que alguien dijo, entrecomillado y escribiéndose, con quién lo dijo debajo.",
        "cuando": "la narración trae una frase entrecomillada o atribuida a alguien",
        "campos": {"texto": (True, 170), "quien": (False, 46)},
        "ejemplo": {"texto": "Nadie sabía nada de aquel cargamento",
                    "quien": "el informe de la aduana"},
    },
    "tesis": {
        "nombre": "La frase que cae",
        "descripcion": "Una sola frase a tamaño grande, palabra a palabra. El golpe de un tramo.",
        "cuando": "el tramo cierra una idea y quieres que se quede; es la cartela más fuerte y la que menos hay que gastar",
        "campos": {"texto": (True, 95), "icono": (False, 20)},
        "ejemplo": {"texto": "Una contraseña sola era toda la cerradura",
                    "icono": "candado_abierto"},
    },
    "enumeracion": {
        "nombre": "La lista",
        "descripcion": "De dos a cuatro líneas que entran una detrás de otra, numeradas.",
        "cuando": "la narración enumera cosas: tres países, cuatro pasos, dos motivos",
        "campos": {"titulo": (False, 46), "lineas": (True, 54)},
        "lista": ("lineas", 2, 4),
        "ejemplo": {"titulo": "El botín",
                    "lineas": ["6M de cuentas con saldo",
                               "28M de números de tarjeta",
                               "La nómina de toda la plantilla"]},
    },
    "contraste": {
        "nombre": "Lo uno contra lo otro",
        "descripcion": "Dos bloques enfrentados con su cifra y su etiqueta, y una raya en medio.",
        "cuando": "la narración compara dos magnitudes o dos estados: antes y después, uno y otro",
        "campos": {"izq_valor": (True, 12), "izq_label": (True, 34),
                   "der_valor": (True, 12), "der_label": (True, 34)},
        "ejemplo": {"izq_valor": "Días", "izq_label": "reponer las tarjetas",
                    "der_valor": "Años", "der_label": "los datos siguen circulando"},
    },
    "pregunta": {
        "nombre": "La pregunta",
        "descripcion": "Una pregunta grande, centrada, con su signo dibujándose detrás.",
        "cuando": "el tramo abre una incógnita que el vídeo va a responder después",
        "campos": {"texto": (True, 88), "icono": (False, 20)},
        "ejemplo": {"texto": "¿Cómo se pierde un barco de 300 metros?"},
    },
    "definicion": {
        "nombre": "La palabra",
        "descripcion": "Un término grande y debajo qué significa, como una entrada de diccionario.",
        "cuando": "la narración usa una palabra técnica o un nombre propio que hay que explicar una vez",
        "campos": {"termino": (True, 26), "texto": (True, 130),
                   "icono": (False, 20)},
        "ejemplo": {"termino": "Infostealer",
                    "texto": "Programa que roba en silencio las contraseñas guardadas en el navegador",
                    "icono": "ojo"},
    },
    "capitulo": {
        "nombre": "La portada de capítulo",
        "descripcion": "El número de capítulo gigante al fondo y su título delante.",
        "cuando": "empieza un bloque nuevo del guion; se pone en el PRIMER plano del capítulo y en ninguno más",
        "campos": {"numero": (True, 4), "texto": (True, 52), "antetitulo": (False, 30)},
        "ejemplo": {"numero": "02", "texto": "El puerto", "antetitulo": "Capítulo"},
    },
    "cronologia": {
        "nombre": "Las fechas",
        "descripcion": "De dos a cuatro hitos con su año, entrando en orden sobre una línea que se dibuja.",
        "cuando": "la narración recorre fechas: pasó esto, después esto otro",
        "campos": {"titulo": (False, 46), "hitos": (True, 52)},
        "lista": ("hitos", 2, 4),
        "ejemplo": {"titulo": "Once meses",
                    "hitos": ["2006 · zarpa de Cartagena",
                              "2007 · lo abordan en Manzanillo",
                              "2008 · el caso se cierra"]},
    },
    "remate": {
        "nombre": "El remate",
        "descripcion": "Una frase corta abajo a la izquierda con una regla gruesa encima. Cierra, no abre.",
        "cuando": "el tramo remata algo que ya se ha contado; es el punto y aparte",
        "campos": {"texto": (True, 66), "icono": (False, 20)},
        "ejemplo": {"texto": "Nadie ha ido a la cárcel", "icono": "escudo_roto"},
    },
}

#: Plantillas que NO puede elegir el agente que decide las cartelas del video.
#: Ahora mismo ninguna: las catorce se eligen plano a plano. Se deja el
#: mecanismo --y no se borra-- porque el dia que haya una que ponga el motor y
#: no el agente, el sitio donde declararlo ya existe.
PLANTILLAS_RESERVADAS = ()


def plantillas_elegibles():
    """Las que se le ofrecen al agente y a la pantalla, en orden."""
    return [n for n in PLANTILLAS if n not in PLANTILLAS_RESERVADAS]

PLANTILLA_POR_DEFECTO = "tesis"

#: Cuantos planos como poco entre dos cartelas. Sin esto, un guion con cuatro
#: cifras seguidas encadena cuatro pantallas de texto y el video deja de ser un
#: video. No es una cuota (el agente decide si hace falta ninguna): es un suelo.
SEPARACION_MINIMA = 4

#: Y cuantas como mucho, en fraccion de planos. Un video no puede ser mitad
#: texto: si el agente se pasa, se quedan las mejores y se avisa.
FRACCION_MAXIMA = 0.22


def plantilla_de(nombre):
    """La ficha de esa plantilla, con la de respaldo si el nombre no existe."""
    return PLANTILLAS.get(str(nombre)) or PLANTILLAS[PLANTILLA_POR_DEFECTO]


#: Los dos fondos que puede tener una cartela.
#:
#:   negro    casi negro con textura. No lleva imagen, asi que ese plano no
#:            cuesta nada y el texto tiene el cuadro entero para el.
#:   imagen   la imagen generada del plano, OSCURECIDA, con el texto encima.
#:            Cuesta lo mismo que un plano normal -- la imagen se genera-- y a
#:            cambio el montaje no se para: el sitio sigue viendose detras.
#:
#: Se alternan a proposito. Todo negro cansa y todo sobre imagen se lee peor;
#: lo elige el agente segun si el plano tiene algo que enseñar debajo.
FONDOS = ("negro", "imagen")
FONDO_POR_DEFECTO = "negro"

#: Cuanto se oscurece la imagen debajo de una cartela. Por debajo de 0,6 el
#: texto compite con el dibujo y no se lee de un vistazo -- es la misma cifra a
#: la que llego el motor anterior con el texto sobre foto (docs/06, «dim >= 0.62»).
VELO = 0.72

#: Cuanto tarda en oscurecerse. No es instantaneo a proposito: se ve el plano
#: limpio un momento, se apaga, y entonces empieza a escribirse el texto. Ese
#: orden es lo que lo hace parecer una transicion y no un rotulo pegado encima.
VELO_ENTRADA = (0.18, 0.45)

#: Cuanto se ve la imagen LIMPIA antes de que entre el velo, como fraccion de lo
#: que tarda en aparecer la primera palabra. El velo ATERRIZA justo cuando esa
#: palabra entra, ni antes ni despues:
#:
#:   - antes, se oscurece y luego no pasa nada: parece que se ha ido la luz;
#:   - despues, las primeras palabras se escriben sobre la imagen limpia y no se
#:     leen, que es lo que pasaba -- el velo tardaba hasta 0,63 s en cerrar y el
#:     texto arrancaba en 0,22.
#:
#: Se cuelga de la voz y no de un numero fijo porque la primera palabra entra
#: CUANDO SE DICE: si se dice en el segundo 1,1 hay tiempo de sobra para un
#: fundido largo, y si se dice en el 0,22 el velo tiene que cerrar deprisa. Lo
#: que no se toca nunca es el tiempo de la palabra: la sincronia manda.
FRACCION_LIMPIA = 0.3
VELO_MINIMO_S = 0.12


def es_cartela(escena):
    """Si este plano es una cartela y no una imagen que haya que generar."""
    return bool((escena or {}).get("cartela"))


#: TODAS LAS CABECERAS VAN SOBRE LA IMAGEN DEL PLANO. Decision del canal
#: (21-08-2026, noche): «hagamos que TODAS las cabeceras tengan imagen de fondo,
#: creo que hará el vídeo mejor».
#:
#: Y hace lo que dice el resto de esta tanda: el montaje NO SE PARA. Una cartela
#: de fondo negro sustituye un plano por una pantalla de texto, y con cartelas
#: que se estiran por su tramo eso son varios segundos sin imagen; sobre imagen,
#: el sitio se sigue viendo detras mientras el texto remata. Es lo mismo que
#: persigue el techo de `SEGUNDOS_MAXIMOS`, por el otro lado.
#:
#: LO QUE CUESTA: el plano de una cartela vuelve a pagar su imagen. Frente a un
#: video sin cartelas no cuesta nada --ese plano se pagaba igual--; frente a
#: como estaba ayer, son las cartelas de fondo negro que dejaban de pagarse, a
#: 0,032 $ cada una (ver COSTE.md). En el video largo, cuatro: 0,13 $.
#:
#: El fondo negro NO se borra. Se dibuja igual (`_fondo`), `FONDOS` lo sigue
#: admitiendo y `sin_imagen` sigue distinguiendolo, porque volver a encenderlo
#: tiene que ser quitar esta linea y no reescribir un dibujado. Lo que cambia es
#: que nadie lo elige: ni el agente, que ya no decide fondo, ni el defecto.
TODAS_SOBRE_IMAGEN = True



def fondo_de(ficha):
    """'negro' o 'imagen'. Hoy SIEMPRE imagen.

    Hubo una excepcion entre el 21 y el 22-08: el ultimo plano de una cabecera
    larga saltaba a fondo solido para rematar el texto con mas contraste. Se
    monto, se vio y se retiro. Lo que se veia no era el
    contraste: era que ahi se acababa el reloj de la cabecera y el texto que
    faltaba aparecia de golpe. El fondo solido no lo causaba, pero lo senalaba.
    """
    ficha = ficha if isinstance(ficha, dict) else {}
    if TODAS_SOBRE_IMAGEN:
        return "imagen"
    fondo = str(ficha.get("fondo") or FONDO_POR_DEFECTO)
    return fondo if fondo in FONDOS else FONDO_POR_DEFECTO


def sobre_imagen(escena):
    """Si esta cartela va ENCIMA de la imagen del plano, que hay que generar."""
    return (es_cartela(escena)
            and fondo_de((escena or {}).get("cartela")) == "imagen")


def sin_imagen(escena):
    """Si este plano NO genera imagen: es una cartela de fondo negro.

    Es la condicion que de verdad importa aguas arriba -- si se paga una imagen,
    si entra en la continuidad, si depende de assets --, y no «es cartela» a
    secas: una cartela sobre imagen es un plano normal con texto encima.
    """
    return es_cartela(escena) and not sobre_imagen(escena)


# ------------------------------------------------------------------- color

def _rgb(hexa):
    crudo = str(hexa or "").strip().lstrip("#")
    if len(crudo) == 3:
        crudo = "".join(c * 2 for c in crudo)
    if len(crudo) != 6:
        return None
    try:
        return tuple(int(crudo[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in rgb)


def _mezclar(uno, otro, cuanto):
    """`uno` mezclado con `otro` en la proporcion `cuanto` (0 = uno, 1 = otro)."""
    a, b = _rgb(uno) or (20, 20, 20), _rgb(otro) or (0, 0, 0)
    return _hex([a[i] + (b[i] - a[i]) * cuanto for i in range(3)])


def diseno_de(plantilla, diseno):
    """La tipografia con la que se dibuja esa cartela: la del preset.

    Se queda como funcion --y no se sustituye por `diseno` a secas en quien
    llama-- porque es el sitio donde declarar una excepcion si algun dia una
    plantilla necesita su propia tipografia. Hubo una y se fue con ella.
    """
    return diseno


def colores_de(paleta, plantilla=None):
    """Los colores de la cartela, derivados de la paleta de los rotulos.

    No se pide una paleta propia a proposito: la cartela pertenece al MISMO
    video que los rotulos y que las transiciones, y anadir cinco selectores de
    color mas a la pantalla seria pedir que se decida dos veces lo mismo.

    El fondo no es negro plano: es el color de sombra del video empujado hacia
    el negro. Asi una historia calida tiene un negro calido y una fria uno frio,
    que es la diferencia entre «una cartela» y «la cartela DE ESTE video».

    TODAS obedecen al canal. Hubo una que no --una firma de marca con su propia
    paleta-- y se fue con la marca: `plantilla` se queda en la firma porque es
    el sitio donde declarar la siguiente excepcion si hace falta.
    """
    p = dict(paleta or {})
    sombra = p.get("sombra") or "#12130f"
    return {
        "fondo": _mezclar(sombra, "#000000", 0.72),
        "fondo_alto": _mezclar(sombra, "#000000", 0.52),
        "texto": p.get("texto") or "#ece7dc",
        "tenue": p.get("tenue") or "#c9c2b4",
        "linea": p.get("linea") or "#d8a657",
        "acento": p.get("acento") or p.get("linea") or "#d8785a",
    }


# ---------------------------------------------------------------- el fondo

def _fondo(colores, semilla=0, tamano=None):
    """Casi negro, con grano, rejilla y vineta. Ni un pixel de texto.

    `tamano` es el lienzo del video cuando no es el de siempre (vertical): el
    fondo se dibuja en coordenadas del lienzo entero, sin anidar, porque no
    lleva texto que haya que mantener a su medida.

    Va al HYPERFRAME y no a la capa: el navegador repinta la capa en cada
    fotograma, y un feTurbulence a pantalla completa por fotograma multiplica el
    tiempo de render por nada -- esto no se mueve.
    """
    grano = int(medios.desempatar(semilla, "grano") % 100)
    w, h = tamano or TAMANO
    return (
        f'<defs>'
        f'<filter id="ct-grano" x="0" y="0" width="100%" height="100%">'
        f'<feTurbulence type="fractalNoise" baseFrequency="0.82" numOctaves="2" '
        f'seed="{grano}" result="ruido"/>'
        f'<feColorMatrix in="ruido" type="saturate" values="0"/>'
        f'<feComponentTransfer><feFuncA type="linear" slope="0.14"/>'
        f'</feComponentTransfer></filter>'
        f'<pattern id="ct-rejilla" width="64" height="64" patternUnits="userSpaceOnUse">'
        f'<path d="M64 0H0V64" fill="none" stroke="{colores["tenue"]}" '
        f'stroke-width="1" opacity="0.05"/></pattern>'
        f'<radialGradient id="ct-alto" cx="50%" cy="42%" r="62%">'
        f'<stop offset="0%" stop-color="{colores["fondo_alto"]}" stop-opacity="1"/>'
        f'<stop offset="100%" stop-color="{colores["fondo"]}" stop-opacity="0"/>'
        f'</radialGradient>'
        f'<radialGradient id="ct-vineta" cx="50%" cy="46%" r="74%">'
        f'<stop offset="55%" stop-color="#000000" stop-opacity="0"/>'
        f'<stop offset="100%" stop-color="#000000" stop-opacity="0.7"/>'
        f'</radialGradient>'
        f'</defs>'
        f'<rect width="{w}" height="{h}" fill="{colores["fondo"]}"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-alto)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-rejilla)"/>'
        f'<rect width="{w}" height="{h}" filter="url(#ct-grano)"/>'
        f'<rect width="{w}" height="{h}" fill="url(#ct-vineta)"/>')


# --------------------------------------------------------- piezas de texto

#: La letra de la cartela cuando nadie dice otra cosa.
#:
#: Ahora la cartela SI obedece al set de diseno de los rotulos (dibujo /
#: realista / editorial), de donde toma la fuente y si va en versales. Estuvo
#: fija un tiempo, y por un motivo real: la cartela se dibujaba dos veces -- en
#: p6 para la rejilla de planos y en p7 para el render-- y el set vive en los
#: params de rotulos, que p6 no ve; con la letra fija las dos coincidian
#: siempre. Desde que p6 no dibuja ninguna cartela (la rejilla la pide al
#: servidor, que si ve el grafismo) hay UN solo dibujante y el motivo
#: desaparece: un video tiene UN grafismo, y el mismo menu decide como se ven
#: sus rotulos y sus cartelas.
LETRA = {"fuente": "Verdana, sans-serif", "versales": True}


#: Por debajo de esto no se abrevia nunca: 900 no gana nada escrito de otra
#: forma. Y por encima SOLO se abrevia si la cifra entera no cabe (ver
#: `_cifra_encajada`): abreviar por sistema seria cambiarle el texto a alguien
#: que ha escrito lo que queria.
DESDE_ABREVIAR = 10000

#: Cuanto puede encoger una cifra antes de que compense abreviarla. Si
#: «30.000.000» hay que dibujarlo a menos del 70% del tamano que pide su
#: plantilla, es que no cabe: ahi «30M» se lee mucho mejor.
ENCOGIDO_ACEPTABLE = 0.7

#: Los separadores de millar que puede traer el texto, en cualquier idioma.
_MILLARES = str.maketrans("", "", ".,    ")


def acortar_numero(texto):
    """'30.000.000' -> '30M'. Devuelve el texto tal cual si no es una cifra sola.

    Solo toca cadenas que son UN numero y nada mas: «$2M», «4%», «165+» y
    «10 TONELADAS» se quedan como estan, porque ahi el texto ya dice algo que
    una abreviatura se llevaria por delante.
    """
    crudo = str(texto or "").strip()
    digitos = crudo.translate(_MILLARES)
    if not digitos.isdigit() or len(digitos) < 2:
        return crudo
    valor = int(digitos)
    if valor < DESDE_ABREVIAR:
        return crudo
    for corte, letra in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if valor >= corte:
            escala = valor / float(corte)
            # un decimal como mucho, y sin el si es redondo: «30M», no «30.0M»
            return (f"{escala:.1f}".rstrip("0").rstrip(".") + letra
                    if escala < 100 else f"{int(round(escala))}{letra}")
    return crudo


# ===========================================================================
# ICONOS
#
# Trazos simples de 24x24, escritos aqui y no traidos de ninguna libreria: son
# doce formas geometricas y una dependencia por doce paths seria pagar mucho
# por poco. Van con `stroke` y sin relleno, asi que heredan el color de la
# cartela y se escalan sin perder grosor relativo.
#
# El catalogo es CERRADO, como las plantillas: el agente elige de esta lista y
# no puede pedir un icono que no existe. Uno inventado se ignora y la cartela
# sale sin el, que es peor que con el pero mucho mejor que rota.
# ===========================================================================

ICONOS = {
    "candado": "M7 11V8a5 5 0 0 1 10 0v3M5 11h14v10H5z",
    "candado_abierto": "M7 11V8a5 5 0 0 1 9.6-2M5 11h14v10H5z",
    "llave": "M14 10a4 4 0 1 1 4 4h-1l-2 2-2-2-2 2-2-2v-2l5-5zM18 8h.01",
    "escudo": "M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5z",
    "escudo_roto": "M12 2l8 3v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5zM12 2v20M9 8l6 4-6 4",
    "ojo": "M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6zM12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6z",
    "alerta": "M12 3l10 17H2zM12 9v5M12 17h.01",
    "reloj": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM12 7v5l3 2",
    "tarjeta": "M2 6h20v12H2zM2 10h20M6 15h4",
    "base_datos": "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
    "servidor": "M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01",
    "globo": "M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18zM3 12h18M12 3c2.5 3 2.5 15 0 18M12 3c-2.5 3-2.5 15 0 18",
    "persona": "M12 4a4 4 0 1 1 0 8 4 4 0 0 1 0-8zM4 21c0-4.4 3.6-7 8-7s8 2.6 8 7",
    "personas": "M9 4a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7zM2 20c0-3.9 3.1-6 7-6s7 2.1 7 6M17 5.2a3.5 3.5 0 0 1 0 6.6M18 14.3c2.4.7 4 2.6 4 5.7",
    "documento": "M6 2h8l4 4v16H6zM14 2v4h4",
    "lupa": "M11 4a7 7 0 1 1 0 14 7 7 0 0 1 0-14zM16.5 16.5L21 21",
    "rayo": "M13 2L4 14h7l-1 8 9-12h-7z",
    "subida": "M3 17l6-6 4 4 8-8M15 7h6v6",
    "bajada": "M3 7l6 6 4-4 8 8M15 17h6v-6",
}


def _cifra_encajada(texto, fam, tam, ancho_max, alto_max, minimo):
    """La cifra dibujable: entera si cabe, abreviada solo si no.

    Se prueba primero tal cual la escribieron. Solo cuando encoger tanto la
    dejaria ilegible se recurre a la abreviatura, y solo si de verdad acorta.
    Abreviar por sistema seria reescribirle el texto a alguien que ha puesto
    justo el que queria: «4%», «165+» y «$2M» tienen que salir como estan.
    """
    lineas, usado = tipografia.encajar(texto, fam, tam, True, 0, ancho_max,
                                       alto_max, minimo=minimo, lineas_max=1)
    if usado >= tam * ENCOGIDO_ACEPTABLE:
        return lineas, usado
    corto = acortar_numero(texto)
    if corto == texto or len(corto) >= len(texto):
        return lineas, usado                   # no hay nada mas corto que poner
    cortas, usado_corto = tipografia.encajar(corto, fam, tam, True, 0, ancho_max,
                                             alto_max, minimo=minimo, lineas_max=1)
    return (cortas, usado_corto) if usado_corto > usado else (lineas, usado)


def _icono(nombre, x, y, tam, color, t0, animado=True, opacidad=0.9):
    """El icono, centrado en (x, y) y entrando en su momento. Vacio si no existe."""
    trazo = ICONOS.get(str(nombre or ""))
    if not trazo:
        return ""
    escala = tam / 24.0
    grosor = max(1.2, 2.0 / escala)
    dibujo = (f'<g transform="translate({x - tam / 2:.1f},{y - tam / 2:.1f}) '
              f'scale({escala:.4f})" fill="none" stroke="{color}" '
              f'stroke-width="{grosor:.2f}" stroke-linecap="round" '
              f'stroke-linejoin="round" opacity="{opacidad:g}">'
              f'<path d="{trazo}"/></g>')
    return _entra(dibujo, t0, animado, dur=0.3)


def _fuente_de(diseno):
    return (diseno or LETRA).get("fuente") or LETRA["fuente"]


def _mayus(texto, diseno):
    """Versales salvo que se diga que no. Nunca en citas: ver `_cuerpo`."""
    return str(texto).upper() if (diseno or LETRA).get("versales") else str(texto)


def _text(x, y, texto, tam, color, diseno, negrita=True, espaciado=0,
          anclaje="start", opacidad=1.0, extra=""):
    peso = "700" if negrita else "400"
    return (f'<text x="{x:.0f}" y="{y:.0f}" font-family="{_fuente_de(diseno)}" '
            f'font-size="{tam}" font-weight="{peso}" letter-spacing="{espaciado}" '
            f'fill="{color}" text-anchor="{anclaje}" opacity="{opacidad:g}"'
            f'{extra}>{tipografia.escapar(texto)}</text>')


def _escrito(x, y, lineas, tam, color, diseno, t0, paso, negrita=True,
             espaciado=0, anclaje="start", animado=True, interlineado=1.25,
             registro=None):
    """El bloque que se ESCRIBE: cada palabra aparece en su momento.

    Devuelve (svg, cuando acaba). Con `animado=False` sale todo escrito, que es
    lo que necesita la rasterizacion de la rejilla de planos: la misma
    composicion sin la linea de tiempo.

    `registro` es una lista donde apuntar (cuando, palabra) de cada palabra. De
    ahi salen las teclas de la maquina de escribir (pasos/sonido.py), y sale de
    AQUI y no de una cuenta aparte a proposito: un teclado que suena cuando no
    se escribe es peor que no ponerlo, y con dos cuentas se desincronizan en
    cuanto alguien toque el ritmo.
    """
    # `paso` puede ser un numero (el ritmo de siempre) o un _Reloj (las marcas
    # de la voz). Se acepta lo mismo en el mismo sitio para no tocar las trece
    # llamadas de _cuerpo, que son las que reparten los bloques.
    reloj = paso if isinstance(paso, _Reloj) else None
    salto_t = 0.0 if reloj else float(paso)
    piezas, t = [], t0
    salto = int(tam * interlineado)

    def cuando():
        return reloj.siguiente() if reloj else t

    for indice, linea in enumerate(lineas):
        cabeza = (f'<text x="{x:.0f}" y="{y + salto * indice:.0f}" '
                  f'font-family="{_fuente_de(diseno)}" font-size="{tam}" '
                  f'font-weight="{"700" if negrita else "400"}" '
                  f'letter-spacing="{espaciado}" fill="{color}" '
                  f'text-anchor="{anclaje}">')
        if not animado:
            piezas.append(cabeza + tipografia.escapar(linea) + "</text>")
            for palabra in linea.split():
                momento = cuando()
                if registro is not None:
                    registro.append((round(momento, 3), palabra))
                t = momento + salto_t
            continue
        trozos = []
        for palabra in linea.split():
            momento = cuando()
            trozos.append(
                f'<tspan opacity="0">{tipografia.escapar(palabra)} '
                f'<animate attributeName="opacity" from="0" to="1" '
                f'begin="{momento:.2f}s" dur="0.14s" fill="freeze"/></tspan>')
            if registro is not None:
                registro.append((round(momento, 3), palabra))
            t = momento + salto_t
        piezas.append(cabeza + "".join(trozos) + "</text>")
    return "".join(piezas), (reloj.fin() if reloj else t)


def _cursor(x, y, alto, color, t0, t1, animado=True):
    """El bloque que parpadea al final de lo escrito. Es lo que lo hace maquina.

    Se va cuando el texto termina: un cursor que sigue parpadeando en una
    pantalla ya escrita dice que va a seguir escribiendo, y no va a seguir.
    """
    if not animado:
        return ""
    return (f'<rect x="{x:.0f}" y="{y - alto:.0f}" width="{max(8, alto * 0.5):.0f}" '
            f'height="{alto:.0f}" fill="{color}" opacity="0">'
            f'<animate attributeName="opacity" values="0;1;1;0" '
            f'begin="{t0:.2f}s" dur="0.7s" repeatCount="indefinite"/>'
            f'<set attributeName="opacity" to="0" begin="{t1:.2f}s"/></rect>')


def _regla(x, y, ancho, alto, color, t0, animado=True, dur=0.5, opacidad=1.0):
    """Una regla de acento que se PINTA. Crece por su lado largo.

    Cual es el lado largo importa: una raya vertical que crece de ancho se ve
    aparecer de golpe (crece dos pixeles), y la que separa los dos bloques de
    'contraste' es justo eso -- tiene que BAJAR, que es lo que dice que hay dos
    lados y no uno.
    """
    vertical = alto > ancho
    crece = "height" if vertical else "width"
    fijo = (f'width="{ancho:.0f}" height="{alto:.0f}"' if not animado else
            (f'width="{ancho:.0f}" height="0"' if vertical
             else f'width="0" height="{alto:.0f}"'))
    cuerpo = (f'<rect x="{x:.0f}" y="{y:.0f}" {fijo} fill="{color}" '
              f'opacity="{opacidad:g}">')
    if animado:
        cuerpo += (f'<animate attributeName="{crece}" from="0" '
                   f'to="{(alto if vertical else ancho):.0f}" '
                   f'begin="{t0:.2f}s" dur="{dur}s" fill="freeze" '
                   f'calcMode="spline" keySplines="0.2 0.8 0.2 1" '
                   f'keyTimes="0;1"/>')
    return cuerpo + "</rect>"


#: Cuanto se ve el glifo gigante del fondo. Por debajo de esto no se distingue
#: del grano y no aporta nada; por encima compite con el texto, que es lo que
#: hay que leer.
OPACIDAD_FANTASMA = 0.13


def _fantasma(texto, tam, color, diseno, semilla=0, animado=True, x=None,
              centro=None):
    """Un glifo gigante al fondo, tenue y con deriva lenta.

    Es lo que impide que la cartela sea una diapositiva: cuando el texto ya
    esta escrito, esto sigue moviendose. La deriva es de 10 px en 14 s -- no se
    ve moverse, se ve VIVO, que no es lo mismo.

    La Y se calcula, no se pasa: un `<text>` se planta por su LINEA BASE, asi
    que colocar un glifo de 700 px «en el centro» a ojo lo deja medio fuera de
    cuadro (paso con el '?' y con el numero de capitulo). El centro que se pide
    es el del glifo, y aqui se convierte en linea base.
    """
    if not str(texto).strip():
        return ""
    bx, by, bx2, by2 = BANDA
    x = (bx + bx2) // 2 if x is None else x
    centro = (by + by2) // 2 if centro is None else centro
    fase = medios.desempatar(semilla, "fantasma") % 5
    deriva = ("" if not animado else
              f'<animateTransform attributeName="transform" type="translate" '
              f'values="0 0; 10 -6; -6 8; 0 0" dur="{14 + fase}s" '
              f'repeatCount="indefinite"/>')
    return (f'<g opacity="{OPACIDAD_FANTASMA}">{deriva}'
            + _text(x, centro + tam * 0.35, texto, tam, color, diseno,
                    negrita=True, anclaje="middle") + '</g>')


def _entra(interior, t, animado, dur=0.22):
    """Envuelve algo que no es texto para que aparezca en su momento.

    Las palabras se escriben solas (cada tspan trae su animacion); un punto de
    la cronologia o el numero de una lista no, y sin esto estarian ahi desde el
    fotograma uno -- que es el «texto fantasma» que el motor anterior prohibio: si ya
    se puede leer lo que va a entrar, la entrada no significa nada.
    """
    if not animado:
        return interior
    return (f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" '
            f'begin="{t:.2f}s" dur="{dur}s" fill="freeze"/>{interior}</g>')


def _cuando_entra(paso, t):
    """Cuando entra la SIGUIENTE palabra que se va a escribir.

    Sirve para los adornos que acompanan a un renglon (el numero de una lista,
    el punto de una cronologia): tienen que aparecer CON el, no cuando termino
    el de antes. Con `paso` numerico no hay nada que preguntar -- el ritmo es
    fijo -- y se devuelve el reloj de la composicion tal cual.
    """
    return paso.mirar() if isinstance(paso, _Reloj) else t


def _paso_de(duracion, palabras):
    """Cuanto tarda cada palabra en aparecer, para que quepan todas con cola."""
    if palabras <= 0:
        return S_POR_PALABRA[0]
    hueco = max(0.4, float(duracion) * FRACCION_ESCRITURA - ENTRADA)
    return max(S_POR_PALABRA[0], min(S_POR_PALABRA[1], hueco / palabras))


class _Reloj:
    """Cuando entra cada palabra de la cartela, en el orden en que se escriben.

    Tiene dos modos y el segundo es el que importa:

    SINTETICO  (`tiempos` vacio) es el de siempre: arranca en ENTRADA y avanza
               un paso fijo por palabra, calculado para que quepan todas con
               cola. Se lee bien y no finge nada.

    DICHO      (`tiempos` con una entrada por palabra) es el de verdad: cada
               palabra entra CUANDO SE DICE, con las marcas de tiempo que
               devolvio la voz. Es lo que hace que una cartela acompane a la
               narracion en vez de ir por libre -- y lo que evita que la cifra
               aparezca cuando el narrador ya iba por otra frase.

    Se pasa donde antes iba `paso` (un numero) para no tocar las trece llamadas
    a `_escrito`: quien recibe un `_Reloj` le pide la hora y quien recibe un
    numero sigue sumando como siempre.
    """

    def __init__(self, t0, paso, tiempos=None):
        self.t0 = float(t0)
        self.paso = float(paso)
        self.tiempos = list(tiempos or [])
        self.i = 0

    @property
    def dicho(self):
        return bool(self.tiempos)

    def _momento(self, indice):
        """Cuando entra la palabra numero `indice` (0..), consumida o no."""
        if indice < len(self.tiempos):
            return float(self.tiempos[indice])
        # mas palabras dibujadas que alineadas (una cifra que se parte, un
        # icono con texto): se sigue con el ritmo sintetico desde la ultima
        base = (float(self.tiempos[-1]) if self.tiempos else self.t0)
        return base + max(1, indice - len(self.tiempos) + 1) * self.paso

    def mirar(self):
        """Cuando entra la SIGUIENTE palabra, sin consumirla.

        Lo pide quien dibuja algo que acompana a un renglon y no es texto -- el
        numero de una lista, el punto de una cronologia --: ese adorno tiene que
        aparecer CON su renglon, y su renglon todavia no se ha escrito. Sin
        esto solo se podia poner «cuando acabo el anterior», que en un reloj
        DICHO no es lo mismo: entre dos renglones puede haber un silencio.
        """
        return self._momento(self.i)

    def siguiente(self):
        valor = self._momento(self.i)
        self.i += 1
        return valor

    def fin(self):
        """Cuando termino de escribirse LO QUE VA CONSUMIDO. No el total.

        Devolvia `tiempos[-1] + paso` -- el final de la cartela ENTERA -- y eso
        era un fallo con nombre y apellidos: `_escrito` devuelve esto como «ya
        he terminado», y las trece plantillas encadenan ahi lo que va detras
        (la regla de acento, el numero de la lista, el punto de la cronologia,
        el pie de la cifra, el cursor). Con el reloj DICHO --el que sincroniza
        con la voz-- todos esos adornos recibian el instante final del plano,
        asi que aparecian de golpe en el ultimo fotograma: en la lista del
        Aurora se veia «01» junto a su linea y el «02» y el «03» saltaban
        cuando la escena ya se iba.

        En reloj SINTETICO daba la casualidad de que coincidia (`t0 + i*paso`
        con `i` = palabras consumidas), y por eso solo se veia con la voz
        alineada, que es el modo normal desde el 21-08.
        """
        if self.i <= 0:
            return self.t0
        return self._momento(self.i - 1) + self.paso


def _palabras_llanas(texto):
    """Las palabras de un texto, en minusculas y sin tildes ni signos.

    UNA POR PALABRA CRUDA, y eso es lo que importa: la posicion n de esta lista
    tiene que ser la marca de tiempo n. Normalizando el texto entero y partiendo
    despues, 'twenty-eight' se convertia en dos y la lista dejaba de cuadrar con
    las marcas -- y `alinear` se rendia entera («mejor no fingir una sincronia»)
    en cualquier plano que llevara una palabra con guion. Es la misma cuenta que
    hace p6._indice_de, que es justo la gracia de que las dos compartan medios.
    """
    return [medios.normalizar_texto(p) for p in str(texto or "").split()]


def tramos_de(*escenas):
    """(narracion, marcas) de cada plano, en orden de video, saltando los vacios.

    Es lo que se le pasa a `encajar` para buscar en una VENTANA: las marcas de
    los vecinos ya estan en plan.json y van en el reloj del video, asi que
    buscar en tres planos en vez de en uno no inventa ningun dato.
    """
    tramos = []
    for escena in escenas:
        escena = escena if isinstance(escena, dict) else {}
        narracion, marcas = escena.get("narracion"), escena.get("marcas")
        if narracion and marcas:
            tramos.append((narracion, marcas))
    return tramos


def vecinos_de(escenas, sid):
    """El plano de antes y el de despues de ese, para alinear en una VENTANA.

    Lo usan los caminos que recalculan la sincronia fuera del plan (p7, el
    sonido y la vista previa): sin vecinos, una cartela cuyas palabras se dicen
    en el plano de al lado vuelve a salir sin sincronizar, y entonces la
    pantalla ensena una cosa y el video otra.
    """
    lista = list(escenas or [])
    for indice, escena in enumerate(lista):
        if isinstance(escena, dict) and escena.get("id") == sid:
            return (lista[indice - 1] if indice > 0 else None,
                    lista[indice + 1] if indice + 1 < len(lista) else None)
    return None, None


def fuera_de_orden(palabras_cartela, narracion, idioma=None):
    """Palabras que se dicen, pero no donde la cartela las pone. -> list

    -> [(palabra, la_anterior_anclada), ...]; vacia si el orden esta bien.

    EL FALLO QUE DETECTA, visto en el video largo (0:17). La narracion
    decia «...and the door opened» y la cartela «OPENED THE DOOR». Las palabras
    son las que se oyen --el prompt lo pedia y se cumplio-- pero puestas al
    reves, y una cartela se escribe de izquierda a derecha al ritmo de la voz:
    NINGUNA sincronia puede quedar bien con el texto en otro orden. Bastaba con
    escribir «THE DOOR OPENED».

    ESTO NO SE ARREGLA ANCLANDO MEJOR, y por eso hay una comprobacion aparte: el
    anclaje puede elegir la ocurrencia buena (`_anclas_mas_juntas`), pero no
    puede reordenar la frase. Reordenarla en codigo seria arreglar la salida en
    vez del motor, y ademas destrozaria el texto: «THE DOOR OPENED» es una
    reescritura, no una permutacion mecanica.

    COMO SE MIDE, y esta es la parte que importa: se pregunta POR EL ANCLAJE DE
    VERDAD, el mismo que va a decidir cuando entra cada palabra. Una palabra
    que el anclaje NO ha podido colocar y que sin embargo SI se dice en ese
    plano solo puede ser una cosa: esta escrita fuera de su sitio.

        una palabra que no se dice        se salta -- eso es DESTILAR, y esta bien
        una palabra que se dice y ancla   perfecto
        una palabra que se dice y NO ancla  <- esto es lo que se avisa

    CONTRA SU PROPIO PLANO Y NO CONTRA LA VENTANA de tres, que es lo que si usa
    el anclaje. Con la ventana, una palabra corriente del plano de al lado
    --«was», «the»-- mueve el puntero y deja en falso desorden a media cartela
    bien escrita. Medido: «ONE PASSWORD WAS THE WHOLE LOCK», que esta
    perfectamente destilada, se acusaba por el «was» del plano siguiente.

    Es un AVISO y nunca un descarte: `medios.casan` empareja por subcadena y una
    cifra consume el tramo hablado entero, asi que quedan falsos positivos
    posibles. Quitarle la cartela a un plano por eso seria peor que el fallo.
    """
    palabras = [str(p) for p in (palabras_cartela or [])]
    dichas = _palabras_llanas(narracion)
    if not palabras or not dichas:
        return []

    numeros = medios.numeros_en(dichas, idioma)
    # el MISMO anclaje que decide los tiempos: si el aviso usara otro criterio,
    # diria que algo esta mal justo donde el motor lo ha hecho bien
    anclas = _anclas_mas_juntas(palabras, dichas, [[0.0, 0.0]] * len(dichas),
                                numeros)
    fuera, ultima = [], ""
    for indice, cruda in enumerate(palabras):
        if indice in anclas:
            ultima = cruda
            continue
        aguja = medios.piezas_de(cruda)[:1]
        if not aguja or not aguja[0][0]:
            continue
        if any(medios.casar_desde(aguja, dichas, j, numeros)
               for j in range(len(dichas))):
            fuera.append((cruda, ultima))
    return fuera


def _opciones_de(palabras, dichas, numeros):
    """Donde podria anclar cada palabra escrita. -> [(indice, [(j, cuantas)])]

    Se calculan TODAS y no la primera: elegir la primera que casa es lo que
    ponia «A» sobre el «a» de «a username» en vez de sobre el de «a password».
    """
    opciones = []
    for indice, cruda in enumerate(palabras):
        # La primera pieza y no todas: una palabra escrita con guion sigue
        # anclando por su primera mitad, como hacia antes. Una cifra -- '30M',
        # '1.500' -- es UNA pieza con su valor, asi que entra entera.
        aguja = medios.piezas_de(cruda)[:1]
        if not aguja or not aguja[0][0]:
            continue
        donde = []
        for j in range(len(dichas)):
            cuantas = medios.casar_desde(aguja, dichas, j, numeros)
            if cuantas:
                donde.append((j, cuantas))
        if donde:
            opciones.append((indice, donde))
    return opciones


def _anclas_mas_juntas(palabras, dichas, marcas, numeros):
    """A que segundo se ancla cada palabra de la cartela. -> {indice: segundo}

    EL FALLO QUE ARREGLA, visto en el video largo (0:17). La narracion
    decia «someone typed a username and a password, and the door opened» y la
    cartela «A PASSWORD». El «A» se anclaba en el PRIMER «a» de la narracion --el
    de «a username»-- porque se cogia la primera marca que casaba, asi que en
    pantalla aparecia «A», pasaba segundo y medio de audio que no tenia nada que
    ver, y despues aparecia «PASSWORD». Las dos palabras de la cartela se dicen
    juntas y salian separadas.

    ASI QUE SE ELIGE LA CADENA MAS JUNTA, no la primera. De todas las formas de
    repartir las palabras en orden, gana la que:

        1. ancla MAS palabras -- una palabra anclada vale mas que una
           interpolada, porque la interpolada no cae donde se dice;
        2. las deja mas JUNTAS (menos distancia entre la primera y la ultima);
        3. y a igualdad, la que empieza antes.

    Sigue siendo MONOTONA --las palabras se anclan en orden-- porque una cartela
    se escribe de izquierda a derecha y dos palabras que entren al reves se leen
    como un parpadeo. Y sigue consumiendo el TRAMO entero: si «30M» anclo en
    «thirty million», la palabra siguiente no puede anclar en «million».
    """
    opciones = _opciones_de(palabras, dichas, numeros)
    if not opciones:
        return {}

    def cadena_desde(arranque, primera_j, primera_cuantas):
        """Lo mas que se puede anclar empezando por ahi. -> [(indice, j)]"""
        elegidas = [(opciones[arranque][0], primera_j)]
        j = primera_j + primera_cuantas
        for indice, donde in opciones[arranque + 1:]:
            for k, cuantas in donde:
                if k >= j:
                    elegidas.append((indice, k))
                    j = k + cuantas
                    break
        return elegidas

    mejor, coste_mejor = None, None
    # SE PRUEBA CON CADA PALABRA COMO PRIMERA ANCLADA, no solo con la primera de
    # la cartela: si la primera no se dice en este tramo, empezar por la segunda
    # ancla mas palabras. Son pocas palabras y pocas marcas, asi que probarlas
    # todas cuesta nada y evita tener que adivinar cual es la buena.
    for arranque in range(len(opciones)):
        for primera_j, primera_cuantas in opciones[arranque][1]:
            elegidas = cadena_desde(arranque, primera_j, primera_cuantas)
            dispersion = elegidas[-1][1] - elegidas[0][1]
            coste = (-len(elegidas), dispersion, primera_j)
            if coste_mejor is None or coste < coste_mejor:
                mejor, coste_mejor = elegidas, coste
    return {indice: float(marcas[j][0]) for indice, j in (mejor or [])}


def encajar(palabras_cartela, tramos, duracion=4.0, idioma=None):
    """Cuando se dice cada palabra de la cartela, EN EL RELOJ DEL VIDEO.

    Devuelve una lista de segundos absolutos (una por palabra escrita) o [] si
    no hay ni una sola ancla. NO recorta contra ningun plano a proposito: de
    esta lista sale justamente la decision de QUE PLANOS ocupa la cartela, y
    recortarla antes seria decidir la respuesta con la pregunta.

    La cartela DESTILA la narracion: no la repite. Y eso NO es un obstaculo que
    haya que rodear, es el estilo -- abreviar la cifra y quedarse con el nucleo
    de la frase es lo que hace que se lea de un vistazo mientras la voz sigue.
    O sea que el trabajo es de aqui: sincronizar un texto destilado.

    Se ancla lo que si coincide -- en orden, sin volver atras -- y lo que no
    coincide se reparte entre sus vecinas ancladas. Una cartela de cinco
    palabras de las que tres estan en el guion sale sincronizada donde importa.

    Lo que sabe emparejar vive en `medios` y lo comparte con los rotulos: la
    cifra en otra notacion (30M contra «thirty million»), que una palabra
    escrita sea un TRAMO de varias habladas, y que la comparacion sea simetrica.

    `tramos` es [(narracion, marcas), ...] en orden de video; `marcas` es
    [[inicio, fin], ...] por palabra, en el reloj del video.
    """
    palabras = [str(p) for p in (palabras_cartela or [])]
    if not palabras:
        return []
    dichas, marcas = [], []
    for narracion, crudas in (tramos or []):
        llanas = _palabras_llanas(narracion)
        tiempos = [m for m in (crudas or []) if isinstance(m, (list, tuple)) and m]
        # La correspondencia palabra n <-> marca n es posicional y la garantiza
        # p6: si un tramo no cuadra se salta ESE tramo, no se tira la ventana
        # entera -- los vecinos siguen sirviendo.
        if not llanas or len(llanas) != len(tiempos):
            continue
        dichas.extend(llanas)
        marcas.extend(tiempos)
    if not dichas:
        return []

    numeros = medios.numeros_en(dichas, idioma)
    anclas = _anclas_mas_juntas(palabras, dichas, marcas, numeros)
    if not anclas:
        return []

    # Lo no anclado se reparte entre las anclas que lo rodean. Fuera de la
    # primera y de la ultima se extrapola con el paso sintetico, que es lo que
    # habria hecho el reloj de siempre.
    paso = _paso_de(duracion, len(palabras))
    llaves = sorted(anclas)
    tiempos, ultimo = [], None
    for indice in range(len(palabras)):
        if indice in anclas:
            valor = anclas[indice]
        else:
            antes = [k for k in llaves if k < indice]
            despues = [k for k in llaves if k > indice]
            if antes and despues:
                a, b = antes[-1], despues[0]
                fraccion = (indice - a) / float(b - a)
                valor = anclas[a] + (anclas[b] - anclas[a]) * fraccion
            elif antes:
                a = antes[-1]
                valor = anclas[a] + (indice - a) * paso
            else:
                b = despues[0]
                valor = anclas[b] - (b - indice) * paso
        # Monotono: dos palabras que entren al reves se leen como un parpadeo.
        valor = valor if ultimo is None else max(valor, ultimo)
        ultimo = valor
        tiempos.append(round(valor, 3))
    return tiempos


def alinear(palabras_cartela, narracion, marcas, t_in=0.0, duracion=4.0,
            entrada=None, idioma=None, tramos=None):
    """Cuando se dice cada palabra de la cartela, DESDE EL PRINCIPIO DE SU PLANO.

    Es `encajar` metido en un plano: se resta el `t_in` y se recorta para que
    ninguna palabra entre antes de la animacion de entrada ni despues del corte
    -- una palabra que entrara despues del corte no se veria nunca.

    `tramos` alinea contra una VENTANA (el plano anterior, el suyo y el
    siguiente) en vez de contra un solo plano; sin el, se mira solo `narracion`.
    [] si no hay con que alinear, y entonces manda el ritmo sintetico de siempre
    y no se finge una sincronia que no existe.
    """
    if tramos is None:
        tramos = tramos_de({"narracion": narracion, "marcas": marcas})
    crudos = encajar(palabras_cartela, tramos, duracion=duracion, idioma=idioma)
    if not crudos:
        return []
    return _en_el_plano(crudos, t_in, duracion, entrada)


def _en_el_plano(tiempos_video, t_in, duracion, entrada=None):
    """El encaje del video, metido en un plano concreto: se resta y se recorta."""
    entrada = ENTRADA if entrada is None else float(entrada)
    t_in, duracion = float(t_in), float(duracion)
    techo = max(entrada, duracion - 0.25)
    limpio, ultimo = [], -1.0
    for valor in tiempos_video:
        valor = max(entrada, min(float(valor) - t_in, techo), ultimo)
        limpio.append(round(valor, 3))
        ultimo = valor
    return limpio


def palabras_dibujadas(ficha, duracion=4.0, diseno=None):
    """Las palabras que se escriben, EN EL ORDEN en que las escribe el dibujado.

    Sale de dibujar, no de recorrer la ficha. Y es importante que sea asi: cada
    plantilla escribe SUS campos en SU orden (la de cifra pone la cifra, luego
    la etiqueta y luego la nota, y se salta cualquier otro campo), asi que una
    lista sacada del diccionario emparejaria la palabra 3 de la cartela con la
    marca de tiempo de otra. Es el mismo motivo por el que las teclas de la
    maquina de escribir salen del dibujado y no de una cuenta paralela.
    """
    return [palabra for _, palabra in
            tiempos_de_escritura(ficha, duracion, diseno)]


#: Cuanto tiene que quedarse en pantalla una cartela DESPUES de escribirse, por
#: palabra, para poder leerla entera. Sale de la regla del motor anterior que costo
#: una ronda: las cabeceras se iban antes de poder leerlas.
COLA_POR_PALABRA = 0.28
COLA_MINIMA = 1.1


def cola_de_lectura(ficha, palabras=None):
    """Cuanto tiene que quedarse en pantalla YA ESCRITA para poder leerse."""
    if palabras is None:
        _, datos = _desmontar(ficha)
        palabras = _cuentapalabras(datos)
    return round(max(COLA_MINIMA, palabras * COLA_POR_PALABRA), 2)


def tiempo_necesario(ficha, duracion=None):
    """Cuantos segundos necesita esta cartela para escribirse Y leerse."""
    _, datos = _desmontar(ficha)
    palabras = _cuentapalabras(datos)
    escribir = palabras * _paso_de(duracion or 4.0, palabras)
    return round(ENTRADA + escribir + cola_de_lectura(ficha, palabras), 2)


def encaje_de(ficha, escena, antes=None, despues=None, diseno=None, idioma=None,
              ventana=None):
    """EN QUE TRAMO DEL VIDEO se dicen las palabras de esta cartela.

        {"palabras": [...],     las que se escriben, en orden de dibujado
         "tiempos": [...],      el segundo del VIDEO de cada una
         "ini": s, "fin": s,    el tramo que ocupan
         "cola": s}             lo que ademas necesita quedarse puesta

    None si no hay ni una ancla, que es cuando manda el ritmo sintetico.

    Busca en una VENTANA -- el plano anterior, el suyo y el siguiente -- y no
    solo en el suyo, porque una cartela puede destilar una frase que empieza a
    decirse antes de su propio plano. Ese es el caso medido del 30M: sus cinco
    palabras se dicen enteras en el plano de ANTES, asi que mirando solo el suyo
    la respuesta era [] y el sistema ni se enteraba.
    """
    duracion = duracion_de(escena)
    palabras = palabras_dibujadas(ficha, duracion, diseno)
    # `ventana` es la lista de planos contra los que buscar, en orden de video.
    # Por defecto los tres de siempre; una cartela que acaba ocupando cuatro
    # necesita mirar mas lejos, o sus ultimas palabras se buscarian en un tramo
    # que ya no es el suyo.
    planos = list(ventana) if ventana else [antes, escena, despues]
    tiempos = encajar(palabras, tramos_de(*planos),
                      duracion=duracion, idioma=idioma)
    if not tiempos:
        return None
    return {"palabras": palabras, "tiempos": tiempos,
            "ini": round(tiempos[0], 3), "fin": round(tiempos[-1], 3),
            "cola": cola_de_lectura(ficha, len(palabras) or 1)}


def escritura_de(ficha, escena, encaje=None, t_in=None, t_out=None, diseno=None):
    """El plan de escritura de una cartela, ya en el reloj del plano que la lleva.

        {"tiempos": [...],      cuando entra cada palabra (vacio = ritmo de siempre)
         "palabras": N,         cuantas se escriben de verdad
         "fin": segundos,       cuando termina de escribirse
         "cola": segundos,      lo que necesita quedarse puesta para leerse
         "falta": segundos,     lo que le falta POR DELANTE (0 si le sobra)
         "antes": segundos,     lo que sus palabras empiezan ANTES de su tramo
         "encaje": [ini, fin],  el tramo del VIDEO en el que se dicen
         "desde_antes": bool,   tiene que arrancar en el plano anterior
         "dos_planos": bool}    tiene que seguir en el siguiente

    `t_in`/`t_out` son el tramo de video que la cartela ocupa DE VERDAD. Por
    defecto los de su plano; cuando ya se ha decidido que empieza antes o que
    sigue despues, los del tramo entero -- y entonces `falta` y `antes` salen
    cero, que es lo que quiere decir «ya cabe».

    Las dos cuentas se hacen sobre el ENCAJE y no sobre los tiempos recortados:
    medir contra el reloj sintetico es lo que hacia que una cartela que llegaba
    cuatro segundos tarde a su propio golpe se declarara «con tiempo de sobra».
    """
    t_in = float(escena.get("t_in") or 0.0) if t_in is None else float(t_in)
    if t_out is None:
        t_out = t_in + duracion_de(escena)
    t_out = float(t_out)
    duracion = max(0.1, t_out - t_in)
    registro = tiempos_de_escritura(ficha, duracion_de(escena), diseno)
    cuantas = len([p for _, p in registro])

    if encaje:
        tiempos = _en_el_plano(encaje["tiempos"], t_in, duracion)
        cola = float(encaje["cola"])
        ini, fin = float(encaje["ini"]), float(encaje["fin"])
        antes = max(0.0, t_in - ini)
        falta = max(0.0, cola - (t_out - fin))
        fin_relativo = fin - t_in
    else:
        # Sin nada con lo que alinear se vuelve al ritmo de siempre, y entonces
        # la unica cuenta honesta es la de las palabras.
        tiempos = []
        cola = cola_de_lectura(ficha, cuantas or 1)
        fin_relativo = float(registro[-1][0]) if registro else ENTRADA
        ini, fin = t_in, t_in + fin_relativo
        antes = 0.0
        falta = max(0.0, cola - (duracion - fin_relativo))
    return {"tiempos": tiempos, "palabras": cuantas,
            "fin": round(fin_relativo, 3), "cola": cola,
            "falta": round(falta, 2), "antes": round(antes, 2),
            "encaje": [round(ini, 3), round(fin, 3)],
            "desde_antes": antes > 0.01, "dos_planos": falta > 0.01}


#: LO QUE UNA CARTELA PUEDE ESTAR EN PANTALLA, COMO MUCHO: EL DOBLE DE LO QUE
#: DURA EL PLANO MAS LARGO DE ESTE VIDEO.
#:
#: Proporcional y no un numero fijo, porque «largo» no significa lo mismo en dos
#: videos distintos: con planos de 1 a 4 s una cartela de once segundos y medio
#: para el montaje en seco, y con planos de 3 a 10 s no. El ajuste ya existe y es
#: `max_s`, lo que el usuario configura para decir el ritmo que quiere; el techo
#: cuelga de ahi en vez de discutirlo por su cuenta.
#:
#: Y el factor DOS no es nuevo: es la decision de 31.4 puesta como techo. Alli se
#: decidio que un plano al que no le da tiempo «dura el doble», con la misma
#: imagen y la camara siguiendo su recorrido. Esto dice hasta donde llega ese
#: doble.
#:
#: No sustituye al bloque del guion, se suma: la cartela para en el primero de
#: los dos que llegue. El bloque impide que se quede puesta mientras la voz
#: cuenta otra cosa; esto impide que se quede puesta y punto.
#:
#: Y NO SE REGENERA NADA PARA CUMPLIRLO. Ni se recorta la frase --una frase
#: cortada por la mitad es peor que una larga-- ni se vuelve a llamar al agente
#: en bucle hasta que quepa: eso ralentiza la produccion y la complica por algo
#: que pasa pocas veces. Se avisa con el numero delante y se arregla donde se
#: escribe. El video tiene que salir dinamico por norma general, no ser
#: demostrablemente perfecto en cada plano.
FACTOR_TECHO = 2.0

#: El `max_s` de p6 cuando nadie lo ha tocado. Vive aqui repetido a proposito:
#: importarlo seria que cartelas dependiera de p6, y la dependencia va al reves.
MAX_S_POR_DEFECTO = 6.0


def techo_de(params=None):
    """Cuanto puede estar puesta una cartela en este video, en segundos."""
    try:
        max_s = float((params or {}).get("max_s") or MAX_S_POR_DEFECTO)
    except (TypeError, ValueError):
        max_s = MAX_S_POR_DEFECTO
    return round(max(2.0, max_s) * FACTOR_TECHO, 2)


#: El techo del video por defecto, para quien no tiene params a mano.
SEGUNDOS_MAXIMOS = techo_de(None)


def palabras_que_caben(duracion):
    """Cuantas palabras se pueden escribir Y leer en ese hueco. Al menos 1.

    Es `tiempo_necesario` al reves, y existe para poder DECIRSELO al agente que
    escribe las cartelas. El presupuesto de palabras ya estaba en su prompt --
    «4 a 7 palabras, y esto es lo que mas se incumple» -- pero escrito como una
    regla general, y una regla general contra un plano concreto de 2,5 s no dice
    nada: la cartela de «Infostealer» salio con trece. Con el numero de SU plano
    delante, la peticion deja de ser una recomendacion.
    """
    duracion = float(duracion or 0)
    cabe = 1
    for palabras in range(1, 41):
        necesita = (ENTRADA + palabras * _paso_de(duracion, palabras)
                    + max(COLA_MINIMA, palabras * COLA_POR_PALABRA))
        if necesita > duracion:
            break
        cabe = palabras
    return cabe


def palabras_maximas(params=None):
    """El presupuesto de una cartela ENTERA, sumando todos sus campos.

    Sale de la MISMA cuenta que decide despues si cabe (`palabras_que_caben`
    sobre el techo del video), para que no puedan discrepar: lo que el agente lee
    es exactamente lo que el motor va a medir.
    """
    return palabras_que_caben(techo_de(params))


#: El presupuesto del video por defecto, para quien no tiene params a mano.
PALABRAS_MAXIMAS = palabras_maximas(None)


def cuantas_palabras(ficha):
    """Cuantas palabras tiene esta cartela en total, sumando sus campos."""
    _, datos = _desmontar(ficha)
    return _cuentapalabras(datos)


def plan_de_escritura(ficha, escena, diseno=None, antes=None, despues=None,
                      idioma=None):
    """Todo lo que hay que saber para escribir esta cartela en SU plano.

    Se calcula UNA vez y lo usan los tres sitios que tienen que estar de
    acuerdo: el plan (para decidir que planos ocupa), el dibujado (para escribir
    a tiempo) y el sonido (para teclear donde se escribe). Antes cada uno hacia
    su cuenta.

    `antes` y `despues` son los planos vecinos: con ellos, las palabras se
    buscan en la VENTANA de tres planos y no solo en el suyo. Ver `encaje_de`.
    """
    encaje = encaje_de(ficha, escena, antes, despues, diseno, idioma)
    return escritura_de(ficha, escena, encaje, diseno=diseno)


#: CUANTOS PLANOS OCUPA UNA CARTELA, COMO MUCHO.
#:
#: En planos y no en segundos desde el 22-08. Lo que se decide
#: aqui es de MONTAJE --cuantos cortes se sacrifican para que el texto quepa-- y
#: contarlo en segundos hacia que el mismo texto pasara o no segun lo que durase
#: la frase de al lado. El tramo de los tres bullets del video largo se paro justo
#: contra los 8,0 s con la ultima linea sin escribir.
#:
#: CUATRO y no dos: una cabecera que ocupa cuatro planos no es un problema, es un
#: plano largo con la cabecera encima, que es lo que se pidio despues de ver el
#: primer montaje. Medido sobre el plan real, con el tope en cuatro los cinco
#: tramos salen a 2, 3, 1, 3 y 2 planos: el tope no muerde ni una vez y quien
#: manda sigue siendo el bloque del guion, que es la frontera de verdad.
PLANOS_MAXIMOS = 4

#: Y a cuantos TIENDE cuando sale bien. Es lo que se le pide al agente en
#: palabras (`palabras_maximas` sobre `techo_de`), no un limite: el limite es el
#: de arriba.
PLANOS_QUE_TIENDE = 2



def bloque_de(escena):
    """De que bloque del guion sale este plano. '' si el plan no lo guardo."""
    return str((((escena or {}).get("origen")) or {}).get("bloque") or "")


def tramo_de(ficha, escenas, indice, libre=None, diseno=None, idioma=None,
             planos=None):
    """DE QUE PLANO A QUE PLANO ocupa esta cartela. (desde, hasta, escritura).

    Es la respuesta al enunciado entero: una cabecera ocupa el tramo de video en
    el que se dicen sus palabras. Asi que se estira MIENTRAS le falte y haya un
    plano libre al lado, en vez de pararse en un numero inventado.

    LA FRENAN DOS COSAS, y para en la primera de las dos que llegue:

    EL BLOQUE DEL GUION, que es la frontera del relato: un bloque es lo que
    escribio el redactor de una vez, o sea UNA idea -- la que se traduce, la que
    se reescribe y la que la voz separa con un silencio. Una cartela que cruza esa
    linea se queda puesta mientras la narracion ya cuenta otra cosa.

    Y EL TOPE DE PLANOS (`PLANOS_MAXIMOS`), que es la frontera del montaje.

    EN PLANOS Y NO EN SEGUNDOS, y se cambio el 22-08: lo que
    se decide aqui es de montaje --cuantos cortes se sacrifican para que el
    texto quepa-- y en segundos el mismo texto pasaba o no segun lo que durase
    la frase de al lado. En el video largo, el tramo de los tres bullets se paro
    justo contra los 8,0 s con la ultima linea sin escribir: «GLOBAL STAFF
    PAYROLL» se dice en el segundo 83,5 y el tramo acababa en el 80,8.

    HACIA ATRAS Y HACIA DELANTE, y con las dos pasa lo mismo: el tramo entero
    se FUNDE en un solo plano mas largo (`p6._fundir`), con la imagen del que se
    queda con la cartela. Asi que no hay ningun corte dentro del tramo -- ni
    fondo que cambie, que era la objecion de 31.4 -- y hacia atras no se pierde
    ninguna imagen: la del plano de origen no llega a pedirse.

    Y es la imagen CORRECTA, no una cualquiera: la cartela se decide leyendo el
    guion, antes de que exista ninguna imagen, asi que no esta soldada a la de su
    plano. Si sus palabras se dicen en el plano anterior, la imagen de ese plano
    es justamente la que ilustra lo que la cartela remata.

    Si al final del estirado sigue faltando tiempo, `escritura['falta']` lo dice
    y quien llama lo cuenta: una cartela que no se puede leer tiene que salir en
    el informe, no quedarse callada -- que es como estaba la de «Infostealer»,
    con trece palabras apiladas en un plano de 2,5 s.

    `libre(escena)` dice si ese plano se puede absorber; sin el, ninguno.
    """
    escenas = list(escenas or [])
    libre = libre or (lambda _e: False)
    planos = int(planos or PLANOS_MAXIMOS)
    bloque = bloque_de(escenas[indice])
    desde = hasta = indice
    escritura = None

    def cabe(otro, nuevo_desde, nuevo_hasta):
        """Si la cartela puede llegar hasta ahi: misma idea Y dentro del tope."""
        if not libre(otro) or (nuevo_hasta - nuevo_desde + 1) > planos:
            return False
        # el bloque del guion manda por encima del tope: es la frontera del
        # relato, no la del montaje
        return not bloque or not bloque_de(otro) or bloque_de(otro) == bloque

    for _ in range(len(escenas) + 1):        # cota dura: nunca un while True
        ventana = escenas[max(0, desde - 1):min(len(escenas), hasta + 2)]
        encaje = encaje_de(ficha, escenas[indice], diseno=diseno, idioma=idioma,
                           ventana=ventana)
        escritura = escritura_de(ficha, escenas[indice], encaje,
                                 t_in=escenas[desde].get("t_in"),
                                 t_out=escenas[hasta].get("t_out"),
                                 diseno=diseno)
        if (escritura["desde_antes"] and desde > 0
                and cabe(escenas[desde - 1], desde - 1, hasta)):
            desde -= 1
            continue
        # LA CARTELA SE MUDA AL PLANO DONDE SE DICE (era PENDIENTE 13).
        #
        # Simetrico de `desde_antes`: si sus palabras no EMPIEZAN hasta el plano
        # siguiente, el hogar es ESE. Antes se extendia sobre los dos --el tramo
        # quedaba cubierto-- pero se escribia comprimida contra el final del
        # primero, porque la continuacion se dibuja ya escrita (31.4).
        #
        # POR QUE SE PUEDE HACER AHORA Y ANTES NO. El argumento que lo frenaba
        # era «mudarla cambia que plano deja de generar imagen». Con
        # TODAS_SOBRE_IMAGEN (34.2) eso se cayo: el plano de una cartela rueda su
        # imagen igual, asi que mudarla no quita ni anade ninguna. Es la misma
        # caida que desbloqueo el «hacia atras».
        #
        # Y no oscila: al mudarse, el nuevo t_in queda por debajo del inicio del
        # encaje, o sea que `antes` sale cero y la rama de arriba no dispara.
        if (desde < hasta
                and escritura["encaje"][0] >= float(escenas[desde].get("t_out") or 0)):
            desde += 1
            continue
        if (escritura["dos_planos"] and hasta + 1 < len(escenas)
                and cabe(escenas[hasta + 1], desde, hasta + 1)):
            hasta += 1
            continue
        break
    return desde, hasta, escritura


#: Los campos de una cartela que NO se escriben: el icono es un glifo, no una
#: palabra. Contarlo daba una palabra de mas en todas las cuentas que cuelgan de
#: `_cuentapalabras` --la cola de lectura, `tiempo_necesario` y el presupuesto de
#: palabras--, o sea que se le pedia mas tiempo del que necesita y se la medía
#: contra un techo mas estrecho del que le toca.
CAMPOS_SIN_TEXTO = frozenset({"icono"})


def ocupacion_de(escenas, plan_bruto, diseno=None, idioma=None, planos=None):
    """Que planos ocuparia cada cartela candidata: {sid: (desde, hasta)} por indice.

    Se calcula ANTES de repartir, y no despues, porque una cartela que ocupa dos
    planos consume DOS del reparto: contarlo despues dejaria el suelo de
    separacion midiendo una cosa y el video ensenando otra.

    Es una cuenta OPTIMISTA: aqui todavia no se sabe cuales van a entrar, asi
    que se da por libre cualquier plano que no sea candidato ni cartela. Quien
    aplica el reparto vuelve a comprobarlo contra el estado final.
    """
    plan = {k: v for k, v in (plan_bruto or {}).items() if v}
    escenas = list(escenas or [])
    por_id = {e.get("id"): i for i, e in enumerate(escenas)}

    def libre(otro):
        otro = otro or {}
        return not (plan.get(otro.get("id")) or otro.get("cartela")
                    or otro.get("sigue_a"))

    ocupacion = {}
    for sid, ficha in plan.items():
        indice = por_id.get(sid)
        if indice is None:
            continue
        try:
            desde, hasta, _ = tramo_de(ficha, escenas, indice, libre, diseno,
                                       idioma, planos)
        except Exception:                                        # noqa: BLE001
            continue
        if (desde, hasta) != (indice, indice):
            ocupacion[sid] = (desde, hasta)
    return ocupacion


def _cuentapalabras(datos):
    """Cuantas palabras se van a ESCRIBIR en total. Manda el ritmo de la cartela.

    Contaba tambien el icono, y el icono no se escribe: una cartela con glifo
    salia con una palabra de mas en todas las cuentas que cuelgan de aqui -- la
    cola de lectura, `tiempo_necesario` y el presupuesto de palabras --, o sea
    que se le pedia mas tiempo del que necesita y se la medía contra un techo mas
    estrecho del que le toca. Lo delato comparar esta cuenta con
    `palabras_dibujadas`, que sale de dibujar de verdad: 14 contra 13.
    """
    total = 0
    for campo, valor in datos.items():
        if campo in CAMPOS_SIN_TEXTO:
            continue
        if isinstance(valor, list):
            total += sum(len(str(v).split()) for v in valor)
        else:
            total += len(str(valor).split())
    return max(1, total)


# ------------------------------------------------------------ el contenido

def _cuerpo(plantilla, datos, colores, diseno, duracion, animado=True, semilla=0,
            registro=None, tiempos=None, seguro=None):
    """Las piezas de la plantilla, ya encajadas en la region segura.

    Cada rama mide con la fuente de verdad y BAJA el tamano hasta que entra
    (`tipografia.encajar`, que comprueba ancho Y alto). Por eso el tamano que
    pide la plantilla es el MAXIMO, no el que se usa: es la diferencia con las
    composiciones libres del motor anterior, donde el tamano se escribia a mano por
    escena y una frase larga se comia el cuadro.

    Dos reglas que salieron de mirar las primeras cartelas renderizadas:

      AIRE      ningun bloque usa la region segura entera. Un titular que llega
                justo a los dos bordes se lee apretado aunque quepa, asi que
                cada rama se reserva un margen propio dentro de ella.
      RENGLONES un pie en cuatro lineas cabe de alto y se lee fatal. Los pies y
                las etiquetas van por `encajar_pocas_lineas`, que prueba a
                meterlo en UNA y solo admite la segunda si de verdad no cabe.

    Todo se compone alrededor del centro de la BANDA visible, no del lienzo:
    componer sobre el lienzo 3:2 deja los bloques altos, porque los 80 px de
    arriba y los de abajo no salen en el video.
    """
    # `seguro` es la region ESTRECHA del vertical (ver seguro_vertical); sin el,
    # la de siempre
    x0, y0, x1, y1 = seguro or SEGURO
    ancho, alto = x1 - x0, y1 - y0
    cx = (x0 + x1) // 2
    cy = (BANDA[1] + BANDA[3]) // 2
    # EN VERTICAL, LO DE UNA COLUMNA SE CENTRA. Las plantillas de texto largo
    # (definicion, cita) van ancladas a la izquierda de la region segura, y en
    # un cuadro estrecho ese borde es el borde del cuadro: el canal lo vio en
    # el movil. Las de lista (enumeracion, cronologia) siguen a la izquierda,
    # que es como se lee una lista.
    centrado = seguro is not None
    # LA FAMILIA CON LA QUE SE MIDE TIENE QUE SER LA QUE SE DIBUJA. Aqui iba
    # «Verdana» a pelo, que es lo que dibujan las trece plantillas del canal;
    # la firma del cierre va con la tipografia de la marca y medirla con Verdana
    # daria la cuenta bien y el numero mal: medir texto es abrir un fichero,
    # asi que el que mide y el que dibuja tienen que ser el MISMO.
    fam = (diseno or {}).get("familia") or "Verdana"
    t = ENTRADA
    # El reloj: sintetico si nadie ha alineado las palabras con la voz, y dicho
    # si si. Se pasa DONDE iba el paso (ver _escrito).
    paso = _Reloj(ENTRADA, _paso_de(duracion, _cuentapalabras(datos)), tiempos)
    icono = datos.get("icono")
    piezas = []

    if plantilla == "cifra":
        # Sin glifo de fondo: la cifra YA es el elemento gigante de esta
        # cartela, y ponerle otro detras es competir consigo misma.
        cifra = _mayus(datos.get("cifra", ""), diseno)
        lineas, tam = _cifra_encajada(cifra, fam, 176, ancho * AIRE_TITULAR,
                                      alto * 0.5, minimo=64)
        salto = int(tam * 1.15)
        etiqueta, tam_e = tipografia.encajar_pocas_lineas(
            datos.get("label", ""), fam, 46, False, 2, ancho * 0.78, 150)
        bloque = (salto * len(lineas) + 42 + 8 + 46
                  + int(tam_e * 1.25) * len(etiqueta))
        arriba = cy - bloque // 2 + tam
        if icono:
            piezas.append(_icono(icono, cx, arriba - tam - 78, 74,
                                 colores["linea"], ENTRADA, animado, 0.75))
        svg, t = _escrito(cx, arriba, lineas, tam, colores["texto"], diseno,
                          t, paso, anclaje="middle", animado=animado,
                          interlineado=1.15, registro=registro)
        piezas.append(svg)
        base = arriba + salto * (len(lineas) - 1)
        piezas.append(_regla(cx - 90, base + 42, 180, 8, colores["linea"],
                             t + 0.1, animado))
        svg, t = _escrito(cx, base + 118, etiqueta, tam_e, colores["tenue"],
                          diseno, t + 0.25, paso, negrita=False, espaciado=2,
                          anclaje="middle", animado=animado, registro=registro)
        piezas.append(svg)
        if datos.get("nota"):
            # pegada al bloque, no clavada al pie: anclada abajo dejaba un
            # agujero de 200 px entre la etiqueta y ella
            nota, tam_n = tipografia.encajar_pocas_lineas(
                _mayus(datos["nota"], diseno), fam, 26, False, 4, ancho * 0.8, 80)
            pie = base + 118 + int(tam_e * 1.25) * (len(etiqueta) - 1) + 74
            for indice, linea in enumerate(nota):
                piezas.append(_entra(
                    _text(cx, min(pie + indice * int(tam_n * 1.3), y1), linea,
                          tam_n, colores["tenue"], diseno, negrita=False,
                          espaciado=4, anclaje="middle", opacidad=0.6),
                    t + 0.3, animado))

    elif plantilla == "cita":
        # Una cita se deja en su caja original: en versales deja de leerse como
        # una cita y pasa a leerse como un titular (regla del motor anterior).
        lineas, tam = tipografia.encajar(datos.get("texto", ""), fam, 62, False,
                                         0, ancho - 190, alto * 0.6, minimo=32,
                                         interlineado=1.3)
        salto = int(tam * 1.3)
        pie = 60 + 56 if datos.get("quien") else 0
        arriba = cy - (salto * len(lineas) + pie) // 2 + tam
        # La comilla se planta por su LINEA BASE y ademas cuelga de lo alto de
        # su cuadratin: a 240 px se salia por arriba de la banda. Va atada al
        # primer renglon y medida contra el, no contra la caja.
        piezas.append(_text(x0, arriba + tam * 0.55, "“", 170,
                            colores["linea"], diseno, opacidad=0.2))
        # centrado (vertical): el texto en el eje y sin cursor, que iria al
        # final de un renglon cuyo ancho aqui no se conoce
        xt = cx if centrado else x0 + 122
        ancla = "middle" if centrado else "start"
        svg, t = _escrito(xt, arriba, lineas, tam, colores["texto"],
                          diseno, t, paso, negrita=False, animado=animado,
                          interlineado=1.3, registro=registro, anclaje=ancla)
        piezas.append(svg)
        base = arriba + salto * (len(lineas) - 1)
        if not centrado:
            piezas.append(_cursor(x0 + 122, base + 10, tam, colores["linea"],
                                  t, t, animado))
        if datos.get("quien"):
            piezas.append(_regla(cx - 32 if centrado else x0 + 122, base + 60,
                                 64, 4, colores["linea"], t + 0.15, animado))
            piezas.append(_entra(
                _text(xt, base + 116, _mayus(datos["quien"], diseno), 30,
                      colores["tenue"], diseno, negrita=False, espaciado=3,
                      anclaje=ancla),
                t + 0.4, animado))

    elif plantilla in ("tesis", "pregunta"):
        if plantilla == "pregunta" and not icono:
            piezas.append(_fantasma("?", 720, colores["linea"], diseno, semilla,
                                    animado, centro=cy))
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 104, True, -1,
            ancho * AIRE_TITULAR, alto * 0.62, minimo=48, interlineado=1.22,
            lineas_max=LINEAS_TITULAR)
        salto = int(tam * 1.22)
        alto_icono = 96 if icono else 0
        arriba = cy - (salto * len(lineas) + 50 + alto_icono) // 2 + tam
        if icono:
            piezas.append(_icono(icono, cx, arriba - tam - 60, 78,
                                 colores["linea"], ENTRADA, animado, 0.8))
        svg, t = _escrito(cx, arriba, lineas, tam, colores["texto"], diseno,
                          t, paso, espaciado=-1, anclaje="middle",
                          animado=animado, interlineado=1.22, registro=registro)
        piezas.append(svg)
        piezas.append(_regla(cx - 60, arriba + salto * (len(lineas) - 1) + 44,
                             120, 6, colores["linea"], t + 0.1, animado))

    elif plantilla == "enumeracion":
        entradas = [str(v) for v in (datos.get("lineas") or []) if str(v).strip()]
        arriba = y0 + 20
        if datos.get("titulo"):
            piezas.append(_text(x0, arriba + 20, _mayus(datos["titulo"], diseno),
                                34, colores["tenue"], diseno, negrita=False,
                                espaciado=5))
            piezas.append(_regla(x0, arriba + 46, 92, 5, colores["linea"],
                                 ENTRADA, animado))
            arriba += 110
        hueco = (y1 - arriba) // max(1, len(entradas))
        tam = min(76, max(38, int(hueco * 0.44)))
        for indice, texto in enumerate(entradas):
            y = arriba + hueco * indice + tam
            partido, tam_l = tipografia.encajar_pocas_lineas(
                _mayus(texto, diseno), fam, tam, True, 0, ancho - 190,
                hueco - 14, lineas=(1, 2), minimo=None)
            # EL NUMERO ENTRA CON SU RENGLON, no cuando acabo el anterior. Con
            # la voz alineada entre dos lineas puede haber un silencio de
            # segundos, y un «02» plantado en ese hueco senala a una linea que
            # todavia no existe. `_cuando_entra` pregunta al reloj por la
            # siguiente palabra sin consumirla.
            piezas.append(_entra(
                _text(x0, y - 4, "%02d" % (indice + 1), 30, colores["linea"],
                      diseno, espaciado=2), _cuando_entra(paso, t), animado))
            svg, t = _escrito(x0 + 92, y, partido, tam_l, colores["texto"],
                              diseno, t + 0.12, paso, animado=animado,
                              registro=registro)
            piezas.append(svg)

    elif plantilla == "contraste":
        piezas.append(_regla(cx - 1, cy - 190, 2, 380, colores["tenue"],
                             ENTRADA, animado, dur=0.8, opacidad=0.45))
        # el ancho de cada lado deja aire A LOS DOS: al borde del cuadro y a la
        # raya del medio. Con la mitad justa, «30.000.000» tocaba los dos.
        ancho_lado = ancho // 2 - MARGEN_COLUMNA
        for lado, signo in (("izq", -1), ("der", 1)):
            centro = cx + signo * (ancho // 4 + 24)
            lineas, tam = _cifra_encajada(
                _mayus(datos.get(f"{lado}_valor", ""), diseno), fam, 110,
                ancho_lado, 230, minimo=44)
            svg, t = _escrito(centro, cy - 40, lineas, tam, colores["texto"],
                              diseno, t + 0.1, paso, anclaje="middle",
                              animado=animado, registro=registro)
            piezas.append(svg)
            etiqueta, tam_e = tipografia.encajar_pocas_lineas(
                datos.get(f"{lado}_label", ""), fam, 38, False, 1,
                ancho_lado, 200)
            svg, t = _escrito(centro, cy + 66, etiqueta, tam_e,
                              colores["tenue"], diseno, t + 0.1, paso,
                              negrita=False, espaciado=1, anclaje="middle",
                              animado=animado, registro=registro)
            piezas.append(svg)

    elif plantilla == "definicion":
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("termino", ""), diseno), fam, 108, True, -1,
            ancho * AIRE_TITULAR, 260, minimo=52, interlineado=1.2, lineas_max=2)
        cuerpo, tam_c = tipografia.encajar(datos.get("texto", ""), fam, 44,
                                           False, 0, ancho - 90, 260, minimo=26,
                                           interlineado=1.35, lineas_max=3)
        salto, salto_c = int(tam * 1.2), int(tam_c * 1.35)
        bloque = salto * len(lineas) + 42 + 7 + 130 + salto_c * len(cuerpo)
        arriba = cy - bloque // 2 + tam
        if icono and centrado:
            # encima del termino, en el eje: a su izquierda no hay sitio
            piezas.append(_icono(icono, cx - 33, arriba - tam - 40, 66,
                                 colores["linea"], ENTRADA, animado, 0.8))
        elif icono:
            piezas.append(_icono(icono, x0 + 34, arriba - tam * 0.34, 66,
                                 colores["linea"], ENTRADA, animado, 0.8))
            x0 += 108                       # el termino se aparta del icono
        xt = cx if centrado else x0
        ancla = "middle" if centrado else "start"
        svg, t = _escrito(xt, arriba, lineas, tam, colores["texto"], diseno,
                          t, paso, espaciado=-1, animado=animado,
                          interlineado=1.2, registro=registro, anclaje=ancla)
        piezas.append(svg)
        base = arriba + salto * (len(lineas) - 1)
        piezas.append(_regla(cx - 110 if centrado else x0, base + 42, 220, 7,
                             colores["linea"], t + 0.1, animado))
        svg, t = _escrito(xt, base + 130, cuerpo, tam_c, colores["tenue"],
                          diseno, t + 0.2, paso, negrita=False, animado=animado,
                          interlineado=1.35, registro=registro, anclaje=ancla)
        piezas.append(svg)

    elif plantilla == "capitulo":
        piezas.append(_fantasma(str(datos.get("numero", "")), 620,
                                colores["linea"], diseno, semilla, animado,
                                centro=cy))
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 120, True, -1,
            ancho * AIRE_TITULAR, 300, minimo=56, interlineado=1.2, lineas_max=2)
        salto = int(tam * 1.2)
        arriba = cy - (salto * len(lineas)) // 2 + tam
        if datos.get("antetitulo"):
            piezas.append(_text(cx, arriba - tam - 56,
                                _mayus(datos["antetitulo"], diseno), 34,
                                colores["tenue"], diseno, negrita=False,
                                espaciado=10, anclaje="middle"))
        svg, t = _escrito(cx, arriba, lineas, tam, colores["texto"], diseno,
                          t + 0.2, paso, espaciado=-1, anclaje="middle",
                          animado=animado, interlineado=1.2, registro=registro)
        piezas.append(svg)
        piezas.append(_regla(cx - 110, arriba + salto * (len(lineas) - 1) + 50,
                             220, 8, colores["linea"], t + 0.1, animado))

    elif plantilla == "cronologia":
        hitos = [str(v) for v in (datos.get("hitos") or []) if str(v).strip()]
        arriba = y0 + 20
        if datos.get("titulo"):
            piezas.append(_text(x0, arriba + 20, _mayus(datos["titulo"], diseno),
                                34, colores["tenue"], diseno, negrita=False,
                                espaciado=5))
            arriba += 90
        hueco = (y1 - arriba) // max(1, len(hitos))
        tam = min(60, max(30, int(hueco * 0.40)))
        # el rail va antes que los puntos para que quede DEBAJO de ellos
        piezas.append(_regla(x0 + 12, arriba + 8, 3, hueco * len(hitos) - 30,
                             colores["tenue"], ENTRADA, animado,
                             dur=max(0.8, duracion * 0.45), opacidad=0.4))
        for indice, hito in enumerate(hitos):
            y = arriba + hueco * indice + tam
            partido, tam_h = tipografia.encajar_pocas_lineas(
                _mayus(hito, diseno), fam, tam, True, 0, ancho - 140,
                hueco - 16, lineas=(1, 2), minimo=None)
            piezas.append(_entra(
                f'<circle cx="{x0 + 13}" cy="{y - tam_h * 0.34:.0f}" r="10" '
                f'fill="{colores["linea"]}"/>', _cuando_entra(paso, t), animado))
            svg, t = _escrito(x0 + 62, y, partido, tam_h, colores["texto"],
                              diseno, t + 0.1, paso, animado=animado,
                              registro=registro)
            piezas.append(svg)


    else:  # remate
        lineas, tam = tipografia.encajar(
            _mayus(datos.get("texto", ""), diseno), fam, 88, True, 0,
            ancho * AIRE_TITULAR, alto * 0.42, minimo=40, interlineado=1.22,
            lineas_max=LINEAS_TITULAR)
        salto = int(tam * 1.22)
        base = y1 - salto * (len(lineas) - 1) - 30
        piezas.append(_regla(x0, base - tam - 62, 340, 10, colores["linea"],
                             ENTRADA, animado))
        if icono:
            piezas.append(_icono(icono, x0 + 34, base - tam - 140, 68,
                                 colores["linea"], ENTRADA, animado, 0.8))
        svg, t = _escrito(x0, base, lineas, tam, colores["texto"], diseno,
                          t + 0.25, paso, animado=animado, interlineado=1.22,
                          registro=registro)
        piezas.append(svg)

    return "".join(p for p in piezas if p)


# ------------------------------------------------------------ las salidas

def _svg(interior, escala=1, lienzo=None, fuera="", salida=None, k=None):
    """El SVG entero. `escala` cambia el TAMANO declarado, no las coordenadas.

    `lienzo` es el lienzo del VIDEO cuando no es el de siempre (vertical).
    Las plantillas componen sobre TAMANO --sus medidas, sus
    tipografias y su region segura estan pensadas para ese ancho--, asi que en
    un lienzo alto lo que se hace es ANIDAR la composicion entera, escalada al
    ancho del lienzo y centrada en vertical: la cartela pasa a ser una banda en
    medio del cuadro. `fuera` va en coordenadas del lienzo entero y por debajo
    (el velo, el fondo): es lo que cubre lo que la banda no cubre.

    Hace falta porque un SVG se rasteriza a SU TAMANO INTRINSECO: al pedirle a
    Edge una captura de 3072x2048 de un SVG que se declara de 1536x1024, lo
    dibuja a 1536x1024 en la esquina y deja el resto de la pagina en BLANCO. La
    primera cartela renderizada salio asi -- un rectangulo negro pequeno arriba
    a la izquierda y tres cuartos de pantalla en blanco -- y el fallo no estaba
    en el dibujo sino en el tamano declarado.
    """
    w, h = TAMANO
    if not lienzo or tuple(lienzo) == tuple(TAMANO):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
                f'width="{int(w * escala)}" height="{int(h * escala)}">'
                f'{fuera}{interior}</svg>')
    lw, lh = int(lienzo[0]), int(lienzo[1])
    # EN LA BANDA VISIBLE, no en el ancho del lienzo. El lienzo vertical es
    # 1024x1536 (2:3) y el video sale a 9:16, mas estrecho: la camara respeta
    # el alto y RECORTA un 8 % por cada lado (p8, `ventana`). Anidado al ancho
    # del lienzo, el titulo --que la plantilla pone a un 7 % del borde-- salia
    # cortado por la izquierda en el MP4 y entero en cualquier previa, que no
    # recorta. Se vio en el primer video vertical (02-09-2026).
    visible = float(lw)
    if salida and salida[0] and salida[1]:
        visible = min(float(lw), lh * float(salida[0]) / float(salida[1]))
    # con `k` la composicion va a esa escala, centrada, y lo que se sale del
    # lienzo por los lados se recorta (es lo que la region segura estrecha
    # de `seguro_vertical` deja vacio a proposito); sin el, al ancho visible
    if k is None:
        k = visible / float(w)
    ancho = w * k
    alto = h * k
    x = (lw - ancho) / 2.0
    y = (lh - alto) / 2.0
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {lw} {lh}" '
            f'width="{int(lw * escala)}" height="{int(lh * escala)}">'
            f'{fuera}'
            f'<svg x="{x:.1f}" y="{y:.1f}" width="{ancho:.1f}" height="{alto:.1f}" '
            f'viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet">'
            f'{interior}</svg></svg>')


def svg_fondo(paleta=None, semilla=0, escala=1, lienzo=None):
    """Fondo con textura y sin una letra. Es lo que se rasteriza al hyperframe."""
    if lienzo and tuple(lienzo) != tuple(TAMANO):
        # el fondo entero en coordenadas del lienzo: sin anidar, no lleva texto
        return _svg("", escala, lienzo,
                    fuera=_fondo(colores_de(paleta), semilla, tuple(lienzo)))
    return _svg(_fondo(colores_de(paleta), semilla), escala)


def _velo(colores, animado=True, primera=None, tamano=None):
    """La capa oscura que se echa sobre la imagen para poder leer el texto.

    ENTRA, no esta puesta desde el fotograma uno: se ve el plano LIMPIO un
    momento, se oscurece, y entonces empieza a escribirse el texto. Ese orden es
    lo que lo hace parecer una transicion del montaje y no un rotulo pegado.

    `primera` es el segundo en que entra la primera palabra, y el velo aterriza
    justo ahi (ver FRACCION_LIMPIA). Sin ese dato el velo iba a su aire: cerraba
    en 0,63 s mientras el texto arrancaba en 0,22, o sea que las primeras
    palabras se escribian sobre la imagen todavia limpia.

    Con `animado=False` esta puesto desde el fotograma cero, que es lo que quiere
    la segunda mitad de una cartela que dura mas de un plano: ahi la imagen ya
    venia oscurecida y volver a hacer el fundido seria un destello de imagen
    limpia en mitad de la cabecera.

    Lleva ademas una vineta encima del velo: con el oscurecido plano el texto
    del centro sigue compitiendo con lo que haya justo detras.
    """
    w, h = tamano or TAMANO
    if primera is None:
        inicio, dur = VELO_ENTRADA
    else:
        cierra = max(VELO_MINIMO_S, float(primera))
        inicio = max(0.05, min(cierra * FRACCION_LIMPIA, cierra - VELO_MINIMO_S))
        dur = max(VELO_MINIMO_S, cierra - inicio)
    entra = ("" if not animado else
             f'<animate attributeName="opacity" from="0" to="{VELO}" '
             f'begin="{inicio:.2f}s" dur="{dur:.2f}s" '
             f'fill="freeze" calcMode="spline" keySplines="0.3 0 0.2 1" '
             f'keyTimes="0;1"/>')
    return (f'<defs><radialGradient id="ct-velo" cx="50%" cy="46%" r="72%">'
            f'<stop offset="35%" stop-color="{colores["fondo"]}" stop-opacity="1"/>'
            f'<stop offset="100%" stop-color="#000000" stop-opacity="1"/>'
            f'</radialGradient></defs>'
            f'<rect width="{w}" height="{h}" fill="url(#ct-velo)" '
            f'opacity="{0 if animado else VELO}">{entra}</rect>')


def svg_capa(ficha, paleta=None, diseno=None, duracion=4.0, semilla=0,
             tiempos=None, escrita=False, lienzo=None, salida=None):
    """La capa del plano: el texto animado, y el velo si la cartela va sobre imagen.

    Sobre transparente en los dos casos. Con fondo negro el hyperframe ya trae
    la textura; con fondo de imagen el hyperframe es la imagen del plano y lo
    que hay que añadir es el velo que la apaga.

    `tiempos` son los segundos de cada palabra cuando la cartela va sincronizada
    con la voz (ver `alinear`). `escrita` es para el SEGUNDO plano de una
    cartela que dura dos: ahi ya no se escribe nada, sigue puesta.
    """
    plantilla, datos = _desmontar(ficha)
    colores = colores_de(paleta, plantilla)
    diseno = diseno_de(plantilla, diseno)
    # el velo aterriza con la PRIMERA PALABRA, y en la segunda mitad de una
    # cartela larga ya viene puesto: refundirlo seria un destello de imagen
    # limpia en mitad de la cabecera
    primera = float(tiempos[0]) if tiempos else ENTRADA
    anidada = bool(lienzo) and tuple(lienzo) != tuple(TAMANO)
    velo = (_velo(colores, animado=not escrita, primera=primera,
                  tamano=tuple(lienzo) if anidada else None)
            if fondo_de(ficha) == "imagen" else "")
    seguro = seguro_vertical(lienzo, salida) if anidada else None
    cuerpo = _cuerpo(plantilla, datos, colores, diseno, duracion,
                     animado=not escrita, semilla=semilla, tiempos=tiempos,
                     seguro=seguro)
    if anidada:
        # el velo cubre el LIENZO entero (va fuera, en sus coordenadas) y el
        # texto va a tamano natural, centrado, compuesto en la banda visible:
        # ver ESCALA_VERTICAL y `_svg`
        return _svg(cuerpo, 1, lienzo, fuera=velo, salida=salida,
                    k=ESCALA_VERTICAL)
    return _svg(velo + cuerpo)


def tiempos_de_escritura(ficha, duracion=4.0, diseno=None, tiempos=None):
    """Cuando entra cada palabra: [(segundo, palabra)]. Para el sonido.

    Sale de DIBUJAR la cartela y recoger lo que apunta el propio dibujado, no de
    una cuenta paralela: las teclas de la maquina de escribir tienen que caer
    exactamente donde caen las palabras, y con dos cuentas se separan en cuanto
    alguien toque el ritmo. Ver `pasos/sonido.py`. Por eso `tiempos` tiene que
    llegar aqui igual que llega a `svg_capa`: si la cartela va sincronizada con
    la voz y el teclado no, se oye escribir cuando no se escribe.
    """
    plantilla, datos = _desmontar(ficha)
    registro = []
    _cuerpo(plantilla, datos, colores_de(None, plantilla),
            diseno_de(plantilla, diseno), duracion,
            animado=True, registro=registro, tiempos=tiempos)
    return registro


def duracion_de(escena):
    """Lo que dura un plano, con los tres sitios donde puede estar escrito."""
    escena = escena if isinstance(escena, dict) else {}
    return (float(escena.get("duracion") or 0)
            or float((escena.get("t_out") or 0) - (escena.get("t_in") or 0))
            or 4.0)


def tiempos_dichos(ficha, escena, duracion=None, diseno=None, antes=None,
                   despues=None, idioma=None):
    """Los segundos de cada palabra de la cartela, alineados con la narracion.

    Es el atajo que usan p7 (para dibujar), el sonido (para teclear) y la vista
    previa: recibe la escena del plan -- que ya trae `narracion` y `marcas` -- y
    devuelve lo que espera `svg_capa`. [] si no hay con que alinear, y entonces
    manda el ritmo sintetico de siempre, que es como iba hasta el 20-08-2026.

    Es el CAMINO DE RESPALDO: cuando el plan trae `escritura.tiempos` mandan
    esos, porque los calculo la planificacion sabiendo ademas que planos ocupa
    la cartela. Aqui se recalcula para un plan viejo o para una vista previa, y
    por eso tambien acepta los vecinos: sin ellos, una cartela cuyas palabras se
    dicen en el plano de al lado volveria a salir sin sincronizar.
    """
    escena = escena if isinstance(escena, dict) else {}
    duracion = duracion or duracion_de(escena)
    palabras = palabras_dibujadas(ficha, duracion, diseno)
    return alinear(palabras, escena.get("narracion"), escena.get("marcas"),
                   t_in=float(escena.get("t_in") or 0.0), duracion=duracion,
                   idioma=idioma, tramos=tramos_de(antes, escena, despues))


def svg_carta(ficha, paleta=None, diseno=None, duracion=4.0, semilla=0,
              debajo="", tiempos=None, animada=False, escrita=False):
    """La cartela entera: para la rejilla de planos, las muestras y el repaso.

    `debajo` es un trozo de SVG que va bajo todo -- la imagen del plano cuando
    la cartela va encima de ella --. Sin el, una cartela de fondo 'imagen' se
    dibuja sobre su propio velo, que es lo que se ve en la muestra del catalogo:
    ahi no hay plano debajo todavia.

    `animada` la devuelve ESCRIBIENDOSE, con los mismos tiempos con los que la
    va a escribir p7. Es lo que mira el repaso del montaje: quieta no se puede
    ver lo unico que hay que repasar de una cartela --si sus palabras entran
    cuando la voz las dice--, y una animacion inventada aparte para la pantalla
    volveria a ser una maqueta que se desincroniza. Para la rejilla sigue
    valiendo la quieta: ahi lo que se mira es el TEXTO.
    """
    plantilla, datos = _desmontar(ficha)
    colores = colores_de(paleta, plantilla)
    diseno = diseno_de(plantilla, diseno)
    if fondo_de(ficha) == "imagen":
        base = ((debajo or _fondo(colores, semilla))
                + _velo(colores, animado=bool(animada) and not escrita,
                        primera=(float(tiempos[0]) if tiempos else ENTRADA)))
    else:
        base = _fondo(colores, semilla)
    return _svg(base + _cuerpo(plantilla, datos, colores, diseno, duracion,
                               animado=bool(animada) and not escrita,
                               semilla=semilla, tiempos=tiempos))


def _desmontar(ficha):
    """(plantilla, datos) de una ficha de cartela, con respaldo si viene rota."""
    ficha = ficha if isinstance(ficha, dict) else {}
    plantilla = str(ficha.get("plantilla") or PLANTILLA_POR_DEFECTO)
    if plantilla not in PLANTILLAS:
        plantilla = PLANTILLA_POR_DEFECTO
    datos = ficha.get("datos") if isinstance(ficha.get("datos"), dict) else {}
    if not datos:
        datos = dict(PLANTILLAS[plantilla]["ejemplo"])
    return plantilla, datos


def muestra_de(plantilla, paleta=None, diseno=None, tamano=(480, 270)):
    """SVG pequeno de como se ve esa plantilla, con su texto de ejemplo.

    Se dibuja con el MISMO codigo que la cartela de verdad y despues se escala:
    una maqueta hecha aparte se desincroniza en cuanto alguien toca una
    plantilla, y entonces la pantalla ofrece cartelas que ya no existen.
    """
    ficha = {"plantilla": plantilla,
             "datos": dict(plantilla_de(plantilla)["ejemplo"])}
    entero = svg_carta(ficha, paleta, diseno, duracion=4.0)
    interior = entero[entero.index(">") + 1:-len("</svg>")]
    ancho, alto = tamano
    # se ensena la BANDA que queda en cuadro, no el lienzo entero: lo de arriba
    # y lo de abajo no sale en el video y en una muestra pequena enganaria
    bx, by, bx2, by2 = BANDA
    escala = ancho / float(bx2 - bx)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{ancho}" '
            f'height="{alto}" viewBox="{bx} {by} {bx2 - bx} {by2 - by}">'
            f'{interior}</svg>')


def catalogo_plantillas(paleta=None, diseno=None):
    """Las plantillas con su muestra dibujada, para elegirlas mirandolas.

    Solo las ELEGIBLES: hoy son todas, pero el filtro se hace igual porque el
    dia que una la ponga el motor y no el agente, esta pantalla no tiene que
    ofrecerla (ver `PLANTILLAS_RESERVADAS`).
    """
    fichas = []
    for pid in plantillas_elegibles():
        ficha = PLANTILLAS[pid]
        fichas.append({
            "id": pid, "nombre": ficha["nombre"],
            "descripcion": ficha["descripcion"], "cuando": ficha["cuando"],
            "campos": {k: {"obligatorio": v[0], "tope": v[1]}
                       for k, v in ficha["campos"].items()},
            "svg": muestra_de(pid, paleta, diseno),
        })
    return fichas


# --------------------------------------------------------------- validacion

def _ajustar_al_presupuesto(ficha, datos, params, avisos):
    """Suelta los campos OPCIONALES hasta que la cartela quepa. Avisa de todo.

    Es lo unico que fuerza de verdad, y esta acotado a proposito:

    SUELTA lo que la plantilla declara opcional, del ultimo al primero -- que es
    el orden en que pierde importancia: la nota al pie antes que la etiqueta, el
    antetitulo antes que el titular --. Soltar un campo entero es una perdida
    limpia; el lector no se entera de que faltaba.

    NO TOCA lo obligatorio ni las listas. Recortar una frase por la mitad deja
    una cartela rota, que es peor que una larga, y quitar una linea de una
    enumeracion cambia lo que el video cuenta. Si despues de soltar lo opcional
    sigue sin caber, eso solo se arregla reescribiendola: se dice con el numero
    delante y ahi acaba el trabajo del motor.

    Y NO SE VUELVE A LLAMAR AL AGENTE. Reintentar en bucle hasta que quepa
    ralentiza la produccion y la complica por algo que pasa pocas veces; lo que
    tiene que salir bien por norma general es el ritmo, no cada plano.
    """
    datos = dict(datos or {})
    techo, caben = techo_de(params), palabras_maximas(params)
    if _cuentapalabras(datos) <= caben:
        return datos, avisos
    # del ultimo al primero: los campos van en el orden en que se dibujan, y lo
    # que se dibuja al final es lo que menos pesa
    opcionales = [c for c, (obligatorio, _) in ficha["campos"].items()
                  if not obligatorio and c not in CAMPOS_SIN_TEXTO
                  and c != (ficha.get("lista") or [None])[0]]
    soltados = []
    for campo in reversed(opcionales):
        if _cuentapalabras(datos) <= caben:
            break
        if str(datos.get(campo) or "").strip():
            soltados.append(campo)
            datos[campo] = ""
    if soltados:
        avisos.append(
            f"se quita {', '.join(soltados)} para que quepa en los "
            f"{techo:.0f} s que puede estar puesta")
    total = _cuentapalabras(datos)
    if total > caben:
        avisos.append(
            f"{total} palabras: no se pueden leer en los {techo:.0f} s que como "
            f"mucho esta puesta una cartela en este video (caben {caben}) "
            f"-- acortala a mano")
    return datos, avisos


def validar(plantilla, datos, params=None):
    """Recorta y limpia los datos de una cartela. Devuelve (datos, avisos).

    Se valida ANTES de dibujar y no al dibujar: asi el aviso llega a la pantalla
    con nombre y apellidos ("S013: 'texto' recortado a 95") en vez de aparecer
    como una cartela con la letra rara que nadie sabe por que salio asi.
    """
    ficha = plantilla_de(plantilla)
    campos, avisos, salida = ficha["campos"], [], {}
    lista = ficha.get("lista")
    # EL PRESUPUESTO DE PALABRAS SE AVISA, NO SE RECORTA. El tope de caracteres
    # de cada campo si recorta -- ahi lo que se corta es un desbordamiento --,
    # pero una cartela de veinte palabras no se arregla cortandola por la mitad:
    # se arregla escribiendo otra cosa. Asi que se dice con el numero delante y
    # el aviso viaja hasta la pantalla, que es donde esta el cajon para
    # reescribirla.
    datos, avisos = _ajustar_al_presupuesto(ficha, datos, params, avisos)
    for campo, (obligatorio, tope) in campos.items():
        crudo = (datos or {}).get(campo)
        if lista and campo == lista[0]:
            valores = [str(v).strip() for v in (crudo or []) if str(v).strip()]
            if len(valores) > lista[2]:
                avisos.append(f"'{campo}': {len(valores)} elementos, se quedan {lista[2]}")
                valores = valores[:lista[2]]
            if len(valores) < lista[1]:
                if obligatorio:
                    return None, [f"'{campo}' necesita al menos {lista[1]} elementos"]
                continue
            recortados = []
            for valor in valores:
                if len(valor) > tope:
                    avisos.append(f"'{campo}': un elemento recortado a {tope}")
                    valor = valor[:tope].rstrip()
                recortados.append(valor)
            salida[campo] = recortados
            continue
        texto = str(crudo or "").strip()
        if campo == "icono":
            # el icono es una LISTA CERRADA, no un texto: uno inventado no se
            # puede dibujar, y dejarlo pasar dejaria la cartela sin el sin decir
            # por que
            if texto and texto not in ICONOS:
                avisos.append(f"icono desconocido '{texto}', la cartela va sin el")
                texto = ""
            if texto:
                salida[campo] = texto
            continue
        if not texto:
            if obligatorio:
                return None, [f"falta '{campo}', que es obligatorio en '{plantilla}'"]
            continue
        if len(texto) > tope:
            avisos.append(f"'{campo}' recortado a {tope} caracteres")
            texto = texto[:tope].rstrip()
        salida[campo] = texto
    return salida, avisos


def repartir(escenas, plan_bruto, avisar_tope=True, ocupacion=None):
    """Aplica el plan del agente respetando el suelo de separacion y el techo.

    El agente decide SIN CUOTA (esa fue la decision: cartela solo cuando el
    tramo la merece), pero sin suelo de separacion un guion con cuatro cifras
    seguidas encadena cuatro pantallas de texto -- y sin techo, un guion de
    frases redondas convierte el video en una presentacion. Las dos reglas se
    aplican aqui, en orden de video, y lo descartado se dice.

    `ocupacion` ({sid: (desde, hasta)}, de `ocupacion_de`) dice que cartelas
    ocupan mas de un plano porque sus palabras se dicen a caballo de dos. Las
    dos reglas cuentan PLANOS y no cartelas: una que ocupa dos consume dos del
    reparto y deja el suelo de separacion contado desde el ultimo que ocupa.
    Sin esto, el reparto mediria una cosa y el video ensenaria otra.
    """
    plan = {k: v for k, v in (plan_bruto or {}).items() if v}
    ocupacion = ocupacion or {}
    puestas, avisos, ultima, ocupados = {}, [], -10 ** 9, 0
    tope = max(1, int(len(escenas) * FRACCION_MAXIMA)) if escenas else 0
    for indice, escena in enumerate(escenas or []):
        sid = escena.get("id")
        ficha = plan.get(sid)
        if not ficha:
            continue
        desde, hasta = ocupacion.get(sid) or (indice, indice)
        # El techo cuenta los planos que la cartela OCUPA, no las cartelas. Mide
        # cuanto rato del video tiene texto encima, que es lo que quiere decir
        # «un montaje mitad texto deja de ser un video»: una que se estira por
        # tres planos pesa tres, aunque la imagen se siga viendo detras de los
        # tres. Contar cartelas hacia que el 22 % declarado y el real no fueran
        # el mismo numero.
        cuantos = max(1, hasta - desde + 1)
        if desde - ultima < SEPARACION_MINIMA:
            avisos.append(f"{sid}: descartada, a menos de {SEPARACION_MINIMA} "
                          f"planos de la anterior")
            continue
        if ocupados + cuantos > tope:
            if avisar_tope:
                avisos.append(f"{sid}: descartada, ya hay {ocupados} planos de "
                              f"cartela ({int(FRACCION_MAXIMA * 100)}% de los "
                              f"planos es el techo)")
            continue
        puestas[sid] = ficha
        ultima, ocupados = hasta, ocupados + cuantos
    return puestas, avisos


# ------------------------------------------------------------- el agente

MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]
TIEMPO_BASE_S = 300

#: No necesita ver ninguna imagen: decide con el GUION delante, y por eso puede
#: correr antes de generar los planos -- que es justo lo que evita pagar una
#: imagen para un plano que va a ser una cartela. Lo unico que escribe es su
#: propia respuesta (`cli_claude.escribiendo`), en una carpeta temporal.
HERRAMIENTAS_VETADAS = ("WebFetch", "WebSearch", "Task", "TodoWrite",
                        "NotebookEdit")

#: YA NO HAY TANDAS. Aqui habia `POR_TANDA = 40`, heredado de que una lista
#: larga en la RESPUESTA se corta a la mitad. Es un limite del mensaje y no del
#: modelo: si el agente escribe su respuesta en vez de devolverla, desaparece
#: (
#:
#: Y quitarlo importa por lo mismo que en los rotulos: dos reglas de esta fase
#: --que no haya dos cartelas a menos de SEPARACION_MINIMA planos y que no pasen
#: del 22 % del video-- se miden sobre el video ENTERO. Con tandas, la segunda
#: no veia lo que habia decidido la primera.


def _catalogo_para_el_agente(activas=None):
    lineas = []
    for pid in plantillas_elegibles():
        ficha = PLANTILLAS[pid]
        if activas and pid not in activas:
            continue
        campos = ", ".join(
            f"{c}{'' if v[0] else ' (opcional)'} [max {v[1]} caracteres]"
            for c, v in ficha["campos"].items())
        lista = ficha.get("lista")
        if lista:
            campos += f" -- '{lista[0]}' es una LISTA de {lista[1]} a {lista[2]}"
        lineas.append(f"- {pid}: {ficha['descripcion']}\n"
                      f"    cuando: {ficha['cuando']}\n"
                      f"    campos: {campos}")
    return "\n".join(lineas)


INSTRUCCION = """Eres el grafista de un video de animacion narrada. Decides que
tramos de la narracion se cuentan MEJOR con una cartela que con un dibujo.

Una cartela es texto que se escribe palabra a palabra ENCIMA de la imagen del
plano, que se oscurece para poder leerlo. El sitio se sigue viendo detras, asi
que el montaje no se para: por eso NO tienes que elegir fondo -- todas van sobre
la imagen -- y por eso una cartela no "gasta" un plano, lo remata.

Lo que si decides es DONDE va y QUE pone.

TITULO: {titulo}

===========================================================================
EL IDIOMA DEL VIDEO ES: {idioma}
===========================================================================
TODO lo que escribas -- cada campo de cada cartela -- va en {idioma} y en
ningun otro idioma. Estas instrucciones estan en castellano porque son para ti,
no para el video: no las tomes como el idioma de salida. La narracion que ves
abajo esta en {idioma} y es la que manda.

Y escribelo BIEN escrito en ese idioma: con sus tildes, sus enyes, sus signos
de apertura y su puntuacion. "DIAS" y "ANOS" son faltas; se escriben "Dias" y
"Anos" con tilde y con enye. Una pregunta en castellano abre con el signo.
Esto vale igual para las mayusculas: el dibujado las pone en caja alta solo,
y una tilde escrita se conserva.
===========================================================================

LAS PLANTILLAS QUE PUEDES USAR
{catalogo}

LOS ICONOS, cuando la plantilla admite uno (campo "icono", siempre opcional):
{iconos}
Un icono solo si de verdad dice algo del texto -- un candado abierto para una
contraseña que no protegia, una base de datos para un recuento de cuentas --.
Ninguno si no lo hay: un icono decorativo distrae de lo que hay que leer.

COMO SE ELIGE
- La cartela NO ilustra: REMATA. Se pone donde el dibujo diria menos que el
  texto -- una cifra, una cita literal, una frase que cierra un tramo, una
  enumeracion, una palabra que hay que definir.
- NO hay cuota. Si el guion no pide ninguna, devuelve la lista vacia: es una
  respuesta correcta. Un video de treinta planos rara vez pide mas de tres o
  cuatro cartelas.
- Nunca dos seguidas ni casi seguidas: entre dos cartelas tiene que haber al
  menos {separacion} planos. Si dudas entre dos vecinas, elige la mejor.
- El texto de la cartela NO repite la narracion palabra por palabra: la
  DESTILA. Lo que se lee y lo que se oye a la vez tiene que sumar, no competir.
  La excepcion es 'cita', donde el texto SI es lo que se dijo.
- CORTO, y esto es lo que mas se incumple. El tope de caracteres de cada campo
  es un LIMITE, no un objetivo: apuntar a el produce cartelas de tres renglones
  que se leen como un parrafo y tapan el plano.

  Y NO ES UN CONSEJO: cada plano de la lista de abajo trae escrito CUANTAS
  PALABRAS CABEN en el, calculado con su duracion real (lo que tarda en
  escribirse mas lo que tiene que quedarse puesta para poder leerse). Ese numero
  manda sobre todo lo demas. Si lo que quieres decir no cabe en su plano, la
  respuesta NO es escribirlo igual: es decirlo mas corto, o poner la cartela en
  otro plano que dure mas, o no ponerla. Una cartela que no se puede leer es
  peor que ninguna -- tapa el plano y no aporta.

  EL LIMITE DURO son {palabras_maximas} PALABRAS EN TODA LA CARTELA, sumando
  todos sus campos. Sale de que ninguna cartela esta en pantalla mas de
  {segundos_maximos} segundos: si su plano es corto puede quedarse un poco mas
  sobre los siguientes de SU MISMO tramo del guion, pero ahi se acaba -- mas
  tiempo seria el montaje parado. Pasarse de esas palabras no alarga la cartela,
  la deja sin poder leerse.

  El presupuesto por campo, en PALABRAS:
      titular o tesis     4 a 7 palabras. Ocho ya es una frase larga.
      pie de una cifra    3 a 6 palabras
      nota al pie         hasta 8, y muchas veces sobra: dejala vacia
      linea de una lista  3 a 6 palabras cada una

  Una cartela se lee en el tiempo que dura un plano y compitiendo con la voz.
  Si no cabe en un vistazo, no es una cartela: es un parrafo sobre negro.
  Quita adjetivos, quita subordinadas, quita el verbo si se entiende sin el.
  Escribe la mitad de lo que te pida el cuerpo y quedara el doble de bien.

- MEJOR LAS PALABRAS QUE YA SE OYEN. La cartela se ESCRIBE palabra a palabra
  al ritmo al que el narrador las dice: cada palabra de la cartela que aparezca
  en la narracion de su plano entra EXACTAMENTE cuando se pronuncia. Asi que la
  version que mejor funciona casi siempre es la frase corta que el propio
  narrador dice en ese tramo, recortada a su nucleo. Leer justo lo que se esta
  oyendo, escribiendose, es lo que hace que el plano remate; leer otra cosa
  parecida obliga a atender a dos textos. Cuando el tramo tenga una frase que ya
  sea el golpe, usala tal cual.
- Y EN EL MISMO ORDEN EN QUE SE OYEN. Esto es tan importante como elegirlas.
  La cartela se escribe de izquierda a derecha al ritmo de la voz, asi que cada
  palabra entra cuando se dice: si las pones en otro orden que el narrador,
  NINGUNA sincronia puede salir bien y el texto entra a destiempo. Quita todo lo
  que quieras --sobra casi todo-- pero lo que dejes tiene que ir en el orden en
  que se oye.

  El narrador dice «...and the door opened». Escribe «THE DOOR OPENED», no
  «OPENED THE DOOR»: las mismas tres palabras, y solo una de las dos se puede
  sincronizar.

  Vale igual para los CONCEPTOS aunque cambies las palabras: lo que pongas
  primero tiene que ser lo que se oye primero. Y vale entre CAMPOS de la misma
  cartela: se dibujan en el orden en que la plantilla los coloca, asi que el
  campo de arriba tiene que decir lo que se oye antes.

- Y PONLA EN EL PLANO DONDE SE DICE, no en el siguiente. Este es el error que
  mas se ha visto: la cifra se menciona en un plano y la cartela se pone en el
  de despues, asi que el espectador lee en pantalla algo que ya ha oido hace
  cuatro segundos y la cartela llega tarde a su propio golpe. Si lo que quieres
  rotular se dice a caballo entre dos planos, elige AQUEL EN EL QUE EMPIEZA.
- Las cifras, tal y como quieras que se lean. Si una cifra larga cabe mejor
  abreviada ("30M" en vez de "30.000.000"), escribela ya abreviada. Destilar
  asi es lo que se quiere: el motor sabe sincronizar un texto destilado, asi
  que no alargues la cartela para parecerte mas al audio. Lo que el motor NO
  puede hacer es reordenarla: recorta cuanto quieras, pero en el orden de la
  voz (ver la vineta del orden, mas arriba).
- Sin punto final, salvo que sean varias frases. Sin comillas en 'cita': las
  pone el dibujo.
- 'capitulo' solo en el PRIMER plano de un capitulo, y solo si el plano trae
  capitulo marcado.

PLANOS. Cada uno con su duracion y lo que se narra en el:
{planos}

DEVUELVE ESTE JSON:

{{
  "cartelas": {{
    "<id de plano>": {{
      "plantilla": "<una de las de arriba>",
      "datos": {{ "<campo>": "<valor>", ... }},
      "por_que": "<en pocas palabras, por que este tramo pide cartela>"
    }}
  }}
}}

Solo los planos que lleven cartela. Los demas no se nombran.
"""


def _planos_legibles(escenas):
    """Los planos para el agente: cuanto duran, QUE CABE en ellos, y que dicen.

    El presupuesto de palabras ya estaba en la instruccion --«4 a 7 palabras, y
    esto es lo que mas se incumple»--, pero como regla general. Una regla general
    contra un plano concreto de 2,5 s no dice nada, y por eso salio una
    definicion de trece palabras en uno de 2,5: se lee la regla, se escribe la
    frase, y no hay ningun sitio donde las dos se toquen.

    Aqui se tocan: cada plano lleva SU numero, calculado con la misma cuenta que
    despues decide si la cartela cabe (`palabras_que_caben`). Pasarse ya no es
    ignorar un consejo, es contradecir un dato que tiene delante.
    """
    lineas = []
    for escena in escenas:
        cap = escena.get("capitulo")
        marca = f" [empieza capitulo: {cap}]" if cap else ""
        duracion = float(escena.get("duracion") or 0)
        lineas.append(
            f"[{escena.get('id')}] {duracion:.1f}s · caben "
            f"{palabras_que_caben(duracion)} palabras{marca}\n"
            f"    {str(escena.get('narracion') or '').strip()}")
    return "\n".join(lineas)


def _limpiar(datos, ids, activas=None, params=None):
    """Valida la propuesta contra las plantillas REALES y sus topes.

    `params` son los del video, para que el presupuesto de palabras se mida
    contra SU techo (`techo_de`) y no contra el de un video por defecto.
    """
    salida, avisos = {}, []
    crudo = datos.get("cartelas") if isinstance(datos, dict) else None
    crudo = crudo if isinstance(crudo, dict) else {}
    for sid, ficha in crudo.items():
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de esta tanda, se ignora")
            continue
        if not isinstance(ficha, dict):
            continue
        plantilla = str(ficha.get("plantilla") or "").strip()
        if plantilla not in PLANTILLAS:
            avisos.append(f"{sid}: plantilla desconocida '{plantilla}', se ignora")
            continue
        if activas and plantilla not in activas:
            avisos.append(f"{sid}: '{plantilla}' esta apagada en este video")
            continue
        limpios, mas = validar(plantilla, ficha.get("datos"), params)
        if limpios is None:
            avisos.extend(f"{sid}: {m}" for m in mas)
            continue
        avisos.extend(f"{sid}: {m}" for m in mas)
        salida[sid] = {"plantilla": plantilla, "fondo": fondo_de(ficha),
                       "datos": limpios,
                       "por_que": str(ficha.get("por_que") or "").strip()}
    return salida, avisos


def avisos_de_orden(plan, escenas, idioma=None):
    """Las cartelas que van en otro orden que la voz. -> [aviso]

    Se mira DESPUES de repartir y contra la VENTANA de tres planos --el
    anterior, el suyo y el siguiente-- que es la misma que usa el anclaje: una
    cartela cuyas palabras se dicen a caballo entre dos planos no esta
    desordenada por eso.

    Se AVISA y ya: ni se reescribe el texto, ni se reordena, ni se vuelve a
    llamar al agente, ni se descarta la cartela. Es la misma doctrina que el
    presupuesto de palabras («se avisa, no se recorta»): una cartela en otro
    orden no se arregla permutando sus palabras, se arregla escribiendo otra
    cosa -- y eso lo decide quien mira. El cajon donde tocarla es barato: el
    repaso lo cambia sin repagar una imagen.
    """
    avisos = []
    por_id = {e.get("id"): i for i, e in enumerate(escenas or []) if e.get("id")}
    for sid, ficha in (plan or {}).items():
        indice = por_id.get(sid)
        if indice is None:
            continue
        narracion = (escenas[indice] or {}).get("narracion") or ""
        if not narracion:
            continue
        sueltas = fuera_de_orden(palabras_dibujadas(ficha), narracion, idioma)
        for palabra, anterior in sueltas:
            # Con `anterior` se puede decir CONTRA QUE esta desordenada, que es
            # lo que hace el aviso accionable. Sin ella --cuando la palabra
            # suelta es la primera de la cartela-- se dice lo que se sabe y
            # nada mas: inventar una referencia seria peor que no darla.
            donde = (f"se dice ANTES que «{anterior}»" if anterior
                     else "se dice en otro momento del plano")
            avisos.append(
                f"{sid}: «{palabra}» {donde}, así que la cartela va en otro "
                f"orden que la voz y esa palabra entra a destiempo. Escríbela "
                f"en el orden en que se oye.")
    return avisos


def proponer(escenas, params=None, ajuste=None, avisar=None, proyecto_id=None,
             cwd=None, titulo="", idioma="", plantillas=None):
    """Decide que planos son cartela y que pone cada una. NO escribe en params.

    Devuelve {plan, avisos, ...}. Igual que el plan de rotulos: proponer no es
    aprobar, y lo que se guarda despues es la DECISION, no la llamada.

    `cwd` se admite por simetria con los demas agentes y se IGNORA: aqui el
    agente entrega escribiendo un fichero, y eso tiene que caer en una carpeta
    temporal y no en el proyecto (`cli_claude.escribiendo`).
    """
    ajuste = ajuste or {}
    modelo = ajuste.get("modelo") or MODELO_POR_DEFECTO
    esfuerzo = ajuste.get("esfuerzo") or ESFUERZO_POR_DEFECTO
    elegido = {"modelo": modelo, "esfuerzo": esfuerzo}

    escenas = [e for e in (escenas or []) if e.get("id")]
    if not escenas:
        raise RuntimeError("no hay planos: corta la narracion antes")
    # QUE PLANTILLAS puede usar viene de fuera (vive en los params de rotulos,
    # con el resto del grafismo); `params` se sigue admitiendo por si alguien
    # llama a mano.
    activas = set(plantillas or (params or {}).get("plantillas_cartela") or []) or None
    idioma = str(idioma or "").strip() or "el idioma de la narracion"

    prevision = estadisticas.estimar(PASO, tamano=len(escenas), ajuste=elegido)
    avance = None
    if avisar is not None:
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            f"leyendo los {len(escenas)} planos para decidir las cartelas, "
            f"con {modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    # UNA llamada con TODOS los planos delante: ver la nota de arriba.
    instruccion = INSTRUCCION.format(
        palabras_maximas=palabras_maximas(params),
        segundos_maximos=round(techo_de(params)),
        titulo=titulo or "sin titulo",
        idioma=idioma,
        catalogo=_catalogo_para_el_agente(activas),
        iconos=", ".join(sorted(ICONOS)),
        separacion=SEPARACION_MINIMA,
        planos=_planos_legibles(escenas))
    arranque = time.time()
    try:
        crudo = _llamar_claude(instruccion, modelo, esfuerzo, avance)
        bruto, avisos = _limpiar(crudo, {e["id"] for e in escenas}, activas,
                                 params)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO, time.time() - arranque, ok=False, ajuste=elegido,
                            proyecto=proyecto_id, resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    plan, mas = repartir(escenas, bruto)
    avisos.extend(mas)
    # EL ORDEN, comprobado en codigo y no solo pedido en el prompt. Lo que se
    # pide en un prompt se cumple casi siempre; «casi» es justo lo que hace
    # falta comprobar, y este fallo no se ve hasta tener el video montado.
    avisos.extend(avisos_de_orden(plan, escenas, idioma))
    estadisticas.anotar(PASO, segundos, tamano=len(escenas), ajuste=elegido,
                        proyecto=proyecto_id, unidades=len(plan),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "planos": len(escenas), "cartelas": len(plan),
                                 "propuestas": len(bruto)})
    return {
        "plan": plan,
        "avisos": avisos,
        "planos": len(escenas),
        "cartelas": len(plan),
        "propuestas": len(bruto),
        "ajuste": elegido,
        "segundos": round(segundos, 1),
        "estimacion_s": prevision["segundos"],
    }


def _llamar_claude(instruccion, modelo, esfuerzo, avance=None):
    """Se llama asi para poder engancharle el medidor de coste, que va POR NOMBRE.

    Entrega ESCRIBIENDO un fichero y no en el mensaje.
    """
    return cli_claude.escribiendo(
        instruccion, modelo=modelo, esfuerzo=esfuerzo,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        herramientas_vetadas=HERRAMIENTAS_VETADAS, avance=avance,
        para="el plan de cartelas", que="el plan de cartelas")
