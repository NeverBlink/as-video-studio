"""QUE SE VE EN ESTE PLANO, y no en el de al lado.

EL HUECO QUE TAPA
-----------------
El prompt de imagen de un plano NO lo escribe ningun modelo: lo arma el codigo
(`p6_assets._prompt_visual`) juntando piezas que vienen de sitios distintos:

    el ESTILO     la guia de estilo del video. La misma en TODOS los planos.
    el SITIO      del catalogo visual: «la fachada de la sede del banco». El
                  mismo para todos los planos rodados ahi.
    la ACCION     del beat del guion: «Aurora confirma el acceso». Un beat
                  cubre un BLOQUE entero, o sea varios planos.
    la FRASE      la narracion de ESE plano. Lo unico que cambiaba de un plano
                  al siguiente.

Medido sobre el video largo (plan v33): S032, S033 y S034 comparten los primeros
**852 caracteres de 1.280**. Dos tercios del prompt identicos, y la diferencia
entera era la frase narrada. O sea que al modelo de imagen se le pedia tres
veces lo mismo con un pie distinto, y la variedad entre planos hermanos quedaba
al azar de lo que decidiera inventar.

Falta una capa, y es la que escribe esto: **el bloque que dice que se VE en ese
plano concreto**. El sitio dice donde, el beat dice que pasa en el tramo, y la
direccion dice que hay en el cuadro AHORA: que manda el primer termino, que hace
cada uno, hacia donde mira, que esta mostrando esa pantalla.

Y SE ESCRIBE CON EL ESTILO Y EL SITIO DELANTE
---------------------------------------------
El agente recibe la guia de estilo entera y la descripcion literal de cada
sitio que se usa, con una instruccion explicita: **no lo repitas y no lo
contradigas**. Esas dos piezas entran en el prompt VERBATIM y no las escribe el;
tenerlas delante es lo que le permite escribir sabiendo como se va a dibujar en
vez de adivinar.

Es la version util de «que el modelo redacte el prompt entero». Redactarlo
entero de verdad -- sitio incluido -- suena mejor y es peor: la descripcion del
sitio es lo que hace que dos planos del mismo sitio PAREZCAN el mismo sitio, y
reescribirla plano a plano es exactamente como se pierde la continuidad. El
sitio y el reparto se quedan con el codigo; lo que aporta el agente es lo que no
estaba escrito en ninguna parte.

POR QUE UNA SOLA LLAMADA CON EL VIDEO ENTERO DELANTE
----------------------------------------------------
Porque el trabajo es justamente comparar unos planos con otros. Pedir plano a
plano «que se ve aqui» daria cuarenta y nueve respuestas razonables y repetidas:
sin ver el plano de al lado no hay forma de no repetirlo. Es el mismo motivo por
el que el catalogo visual manda el guion entero de una vez (`catalogo_visual`),
y por el que el plan de cartelas ve todos los planos con su duracion.

Y AQUI NO SE TROCEA EN TANDAS, que es la diferencia con `plan_cartelas` y
`plan_callouts`: el agente ESCRIBE su respuesta en un fichero en vez de
devolverla en el mensaje (`cli_claude.escribiendo`). El limite que obligaba a
trocear era el largo del MENSAJE, no el del contexto ni el del modelo, y esta


QUE ES DETERMINISTA Y QUE NO
----------------------------
Lo unico que decide el modelo es el bloque de cada plano. Se guarda en los
params POR UNIDAD -- como las cartelas, y por el mismo motivo: escribir una
direccion ensucia SU plano y no los cuarenta y nueve -- y a partir de ahi es un
dato: el mismo plan da el mismo prompt.

Y ES OPCIONAL. Un plano sin direccion se arma exactamente como antes: esto anade
un bloque al prompt, no sustituye ninguno. Asi un video a medias no cambia de
imagen por el hecho de que exista este paso.
"""
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

PASO = "direccion"

#: Lo que puede ocupar una direccion, en palabras.
#:
#: SESENTA Y NO VEINTE, y el numero se movio a proposito (22-08, tarde). La
#: primera version pedia una linea corta «para no ahogar la frase narrada», y
#: eso era medir mal el problema: lo que ahoga un prompt no es su largo, es
#: REPETIR lo que ya dice. Con el estilo, el sitio y el reparto delante, el
#: agente escribe lo que NO esta escrito en ningun sitio -- que hay en primer
#: termino, que hace cada uno, hacia donde mira, que objeto manda el cuadro, que
#: esta mostrando una pantalla -- y ahi sesenta palabras son informacion.
#:
#: El tope sigue existiendo por lo de siempre: sin el, un bloque de doscientas
#: palabras acaba describiendo el sitio otra vez con otras palabras, y entonces
#: si contradice. Se avisa y se recorta por PALABRAS enteras, nunca a media.
PALABRAS_MAXIMAS = 60
PALABRAS_MINIMAS = 5

MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]
TIEMPO_BASE_S = 600

#: El agente ENTREGA ESCRIBIENDO un fichero (`cli_claude.escribiendo`), asi que
#: aqui no se puede vetar Write ni Edit: son como responde. Lo que si se veta es
#: la red y las tareas anidadas; Bash lo veta el propio helper.
HERRAMIENTAS_VETADAS = ("WebFetch", "WebSearch", "Task", "NotebookEdit")

INSTRUCCION = """Eres el director de fotografia de un video explicativo animado
titulado «{titulo}».

El video ya esta cortado en planos, con su sitio, su reparto y su frase de
narracion decididos. Lo que falta -- y es lo unico que escribes tu -- es QUE SE
VE EN CADA PLANO.

POR QUE HACE FALTA. El prompt que recibe el modelo de imagen se arma juntando
piezas que YA EXISTEN: el estilo del video (el mismo en todos), la descripcion
del sitio (la misma para todos los planos rodados ahi), la accion del tramo del
guion (la misma para todo su bloque) y la frase narrada. Medido en un video
real, tres planos seguidos del mismo sitio recibian el 66 % del encargo
IDENTICO. Tu bloque es lo unico que los separa.

=====================================================================
LO QUE YA VA EN EL PROMPT. NO LO REPITAS Y NO LO CONTRADIGAS.
=====================================================================

Esto se le manda al modelo de imagen tal cual, en TODOS los planos. Lo tienes
delante para escribir SABIENDO como se va a dibujar, no para volver a decirlo:

{estilo}

Y LOS SITIOS, tal y como se los va a encontrar cada plano suyo. La descripcion
de su sitio entra VERBATIM en el prompt de ese plano: no la reescribas, no la
resumas y no la contradigas. Lo tuyo pasa DENTRO de este sitio.

{sitios}
{reparto}
=====================================================================
LO QUE ESCRIBES TU
=====================================================================

Un bloque por plano, en INGLES, de {palabras_maximas} palabras como mucho, que
diga lo que NO esta escrito en ningun otro sitio:

- QUE HAY EN PRIMER TERMINO y que objeto manda el cuadro.
- QUE HACE cada personaje que sale, y HACIA DONDE MIRA.
- El detalle concreto que hace que ese plano sea ESE plano y no otro del mismo
  sitio: lo que una pantalla esta mostrando (una grafica cayendo, filas de
  datos, un mapa), un objeto que entra o sale, una puerta que se abre, una mano
  que tapa algo.
- Como cae la luz o donde esta el foco, SI aporta algo. Si no, callate: una
  linea de relleno es peor que ninguna.

REGLAS QUE NO SE SALTAN:

- NO CONTRADIGAS EL SITIO NI EL ESTILO. Si el sitio es una fachada, lo tuyo
  ocurre en la fachada. Si el estilo dice trazo plano y paleta apagada, no pidas
  fotorrealismo ni neon. Cualquier contradiccion la resuelve el modelo de imagen
  a su manera, y ahi se pierde el control.
- NO CONTRADIGAS EL ENCUADRE. Cada plano trae el suyo y el codigo lo exige
  aparte: si pone plano general, no describas un primer plano de una mano.
- DISTINTO DEL DE AL LADO, que es para lo que existe esto. Dos planos seguidos
  del mismo sitio tienen que cambiar de verdad: otro primer termino, otro
  personaje actuando, otro objeto mandando. Estas viendo todos los planos a la
  vez precisamente para poder hacer esto.
- NO REPITAS LA NARRACION. Esa frase ya viaja al modelo. Tu dices lo que se VE
  mientras se oye, que casi nunca es lo mismo.

=====================================================================
LAS TRES QUE MAS SE ROMPEN, Y LAS TRES SE VIERON EN UN VIDEO MONTADO
=====================================================================

1 · QUIEN SALE, SALE UNA VEZ Y ESTA AHI DE VERDAD

El reparto que te doy por plano es quien esta FISICAMENTE en ese sitio en ese
momento del relato. Sobre eso, dos cosas:

  - CADA UNO APARECE UNA SOLA VEZ EN EL CUADRO. Si describes una foto, una
    ficha, un retrato o una cara en una pantalla, esa persona NO puede estar
    ademas de cuerpo presente en el mismo plano. O esta, o la representan.
    Paso: unos investigadores clavando la foto del atacante en un tablon, con
    el atacante de pie a su lado.
  - Y NO METAS A NADIE QUE NO ESTE EN SU REPARTO, aunque la frase lo nombre. De
    alguien se puede HABLAR sin que este en la habitacion. Paso: el grupo
    atacante dibujado dentro de la oficina que lo estaba buscando.

Si crees que el reparto de un plano esta mal --que falta alguien o que sobra--
NO lo arregles metiendo gente en tu bloque: escribe lo que se ve con quien hay,
y ya.

2 · NI UNA LETRA QUE NO HAYAS PEDIDO

El modelo de imagen rellena de letras cualquier superficie que pudiera llevarlas
--una pantalla, un cartel, una portada-- y las elige el. Paso: un plano de
alguien delante de un ordenador salio con la palabra FILM ocupando la pantalla,
sin venir a cuento.

Asi que: o dices QUE PONE, entrecomillado, o dices que NO pone nada. Una
pantalla que no tiene que decir nada se describe por su forma ("columnas de
cifras", "una grafica cayendo", "lineas de texto borrosas ilegibles"), nunca
dejandola en blanco para que el generador decida.

3 · UNA PALABRA CON DOS SENTIDOS SE ESCENIFICA EN EL DEL VIDEO

Cuando la frase usa un termino que significa una cosa en la calle y otra en el
mundo de este video --proveedor, llave, puente, red, cadena, firma, mina--, di
en QUE sentido va y describe objetos de ESE mundo. El generador elige siempre el
sentido mas comun. Paso: una frase sobre los proveedores de servicios de una
empresa salio ilustrada con furgonetas en un almacen.

=====================================================================
EL TEXTO DENTRO DEL DIBUJO
=====================================================================

Se puede, y durante mucho tiempo estuvo prohibido: salian escaparates sin
rotulo y portadas de libro en blanco.

CUANDO SI: cuando el objeto que ya esta en el plano lo llevaria de por si --el
rotulo es parte de lo que esa cosa ES-- y sobre todo cuando es lo que hace
entender el plano. No lo pongas de adorno ni lo repartas para que toque a
todos; tampoco se lo quites a algo que lo llevaria a la vista. Una pared vacia
se queda vacia.

CADA CUANTO NO ESTA ESCRITO EN NINGUN SITIO, y no lo decides tu por costumbre:
lo deciden el mundo que retrata este video y la guia de estilo de arriba. Hay
producciones que llevan letras en casi cada plano y otras que no llevan ninguna
en todo el metraje. Mira lo que tienes delante antes de suponerlo.

DONDE SUELE VIVIR, a modo de ejemplo y sabiendo que depende del mundo del
video -- uno historico, de fantasia o bajo el agua tendra los suyos:

- puesto para ser leido desde lejos: la fachada de un comercio, un cartel, una
  senal, un panel de avisos, un estandarte, una pancarta;
- impreso o grabado en un objeto: la portada de un libro, un titular, una
  etiqueta, una caja, una placa, una lapida, una moneda;
- escrito a mano por alguien: una pizarra, una nota clavada en una puerta, un
  grafiti, un margen anotado;
- lo que muestra un aparato: un titular, un aviso, una cifra en un marcador o
  en un panel;
- puesto encima de alguien o de algo: un rotulo en un vehiculo, una insignia,
  un dorsal, una etiqueta;
- explicativo DENTRO del dibujo: un diagrama con una palabra por elemento, un
  despiece con la pieza senalada, un mapa con un «AQUI», una flecha con una
  palabra. Ojo: esto es un rotulo DIBUJADO, parte de la ilustracion. Los
  rotulos y subtitulos del video son otra cosa y se ponen aparte y ENCIMA
  despues, con tipografia de verdad: esos no se piden aqui.

COMO SE ESCRIBE LO DICE LA GUIA DE ESTILO, NO TU. Un rotulo se dibuja con la
MISMA tecnica, la misma herramienta y el mismo acabado que todo lo demas del
cuadro. No pidas una tipografia concreta ni una convencion que la guia no tenga
--y eso incluye los bocadillos: solo si el estilo de arriba los usa--. Tu dices
QUE pone y DONDE esta; el como sale de la guia.

COMO SE PIDE. Entrecomillado y con su sitio: «a shop sign above the window
reading "ULTRAMARINOS"». Y con TRES limites que no se saltan, porque son las
tres formas en las que el modelo de imagen escribe mal:

- EN EL IDIOMA DEL VIDEO, que es {idioma}. Lo que escribas entre comillas lo
  dibuja el generador tal cual, asi que un rotulo escrito en ingles sale en
  ingles dentro de un video en otro idioma. Tu escribes el plano EN INGLES --el
  generador lo lee en ingles-- pero lo que va ENTRE COMILLAS es del mundo del
  video, no de este encargo: va en el idioma del video, bien escrito y con sus
  tildes. La excepcion son los nombres propios --marcas, siglas, instituciones,
  topónimos, títulos de obras reales--, que se escriben como se escriben en el
  mundo real y no se traducen.

- CORTO: diez palabras como mucho, y lo normal son tres o cuatro. Nada de
  parrafos, listas densas ni letra pequena.
- GRANDE: que se lea de un vistazo, ocupando parte real del cuadro. Si algo no
  puede ser corto Y grande, no lo pidas escrito: sugierelo con la FORMA
  («columnas de cifras borrosas», «un muro de letra pequena ilegible»).

CONTINUIDAD. Los planos van en orden y cuentan una historia: lo que aparece en
uno puede seguir en el siguiente. Si un plano deja algo a medias, el de al lado
puede continuarlo -- pero entonces di EN QUE HA CAMBIADO, no lo repitas.

=====================================================================
LO MAS IMPORTANTE DE TODO: CADA PLANO ES UNA IDEA, NO UN ANGULO
=====================================================================

Lo que escribes NO es «como se encuadra la accion del tramo». Es QUE PASA en
este plano. La accion del tramo va abajo como CONTEXTO --de que va este trozo
del video-- y no como el encargo.

DOS PLANOS DEL MISMO TRAMO NO PUEDEN SER LA MISMA ESCENA VISTA DESDE OTRO
SITIO. Es el fallo que mas se nota en el video montado, y se nota porque cada
plano se dibuja por separado: al pedir «lo mismo desde otro angulo» sale
parecido pero no igual --la comida cambia de sitio, la gente cambia de cara-- y
quien lo ve no lee «otro angulo», lee un error. Medido en un video real: 222 de
222 planos compartian su accion con otro, y habia CINCO planos seguidos de la
misma cocina cambiando solo la camara.

Asi que de dos planos vecinos, o cada uno ensena algo DISTINTO --otro objeto,
otro momento, otro detalle de la misma historia-- o el segundo continua al
primero diciendo QUE HA CAMBIADO. Nunca lo mismo movido.

=====================================================================
SI LA FRASE SE VA A OTRO SITIO, EL PLANO SE VA CON ELLA
=====================================================================

Cada plano trae un `sitio`, y ese sitio es del TRAMO: lo comparte con sus
vecinos. Casi siempre esta bien. Pero un tramo puede empezar contando una cosa y
acabar contando otra, y entonces el sitio se queda viejo a mitad.

LA PREGUNTA QUE TIENES QUE HACERTE EN CADA PLANO, ANTES DE ESCRIBIR NADA:

    ¿lo que dice ESTA frase se puede ENSENAR en este sitio?

Si la respuesta es no, el sitio no vale para este plano por mucho que valga para
sus vecinos. Entonces empieza tu linea con `EN OTRO SITIO: ` y describe TU el
sitio entero, porque el del tramo dejara de usarse para ese plano (y tampoco se
le pondra delante ninguna foto de el).

NO ES SOLO GEOGRAFIA NI SOLO EPOCA. Eso decia antes esta seccion y se leyo al
pie de la letra: en un video de 299 planos no se uso ni una vez. Estos cuatro
son casos de irse, y solo dos cambian de pais o de siglo:

  · «HOY siguen dando para la compra del mes» con una cocina de 1925 de sitio.
    Salio dibujando 1925 y lo que la frase pide es el paralelismo:
    `EN OTRO SITIO: a present-day supermarket checkout, ...`
  · «Argentina lleva decadas en ello» en una calle del Berlin de 1923.
  · «Comprarla para casa cuesta» con una FACTURA sobre la mesa de una oficina de
    sitio. Una caja fuerte en una casa no se ve en una oficina: eso es irse.
  · «Custodiarlo con un tercero cuesta», el plano siguiente, con la misma
    factura de sitio. Una camara acorazada de un tercero tampoco se ve alli.

Los dos ultimos son del mismo tramo, van seguidos, y los dos salieron como otro
angulo de la misma factura. Tres frases distintas, tres veces el mismo mueble.

QUE NO ES IRSE, para que no te pases al otro lado: una frase abstracta que se
puede ESCENIFICAR en el sitio no se va («y este se paga si o si» sobre la
factura, si). Un objeto que entra en el mismo sitio no se va. El sitio
compartido es lo que hace que unos planos seguidos parezcan la misma escena y no
postales sueltas, asi que no lo rompas por gusto -- pero romperlo cuando la
frase se ha ido no es romperlo: es que ya estaba roto.

=====================================================================
Y LA CARA QUE PONEN, TAMBIEN ES DE ESTE PLANO
=====================================================================

El tono --y con el la expresion de la gente-- tambien viene del TRAMO, y tambien
se queda viejo a mitad. Medido en este video: `tenso` («boca apretada, cejas
juntas, mirada dura») en ocho de los diecinueve tramos con gente, y `alegre` en
NINGUNO. Resultado: una familia que puede comer un mes entero con cinco gramos
de oro salia con cara de enfado, y unos obreros haciendo su trabajo tambien.

TODO PLANO EN EL QUE SALGA GENTE ACABA CON SU TONO, SIEMPRE. No es opcional y
no es «solo si cambia»: es una etiqueta mas de la linea, como el sitio. Al final,
tal cual y entre parentesis, uno de estos cinco:

    (TONO: alegre)  (TONO: neutro)  (TONO: tenso)  (TONO: triste)  (TONO: solemne)

  · alegre  cuando la frase es de verdad buena para quien sale: le sale bien,
    consigue algo, le alcanza el dinero, celebra. Es el UNICO que levanta la
    prohibicion de sonreir, asi que sin el nadie sonrie nunca.
  · neutro  alguien explicando, trabajando o mirando. NO es una cara de enfado.
  · tenso   solo con amenaza de verdad, no con «un tema serio».
  · triste  cuando la frase es mala PARA QUIEN SALE: pierde, no le llega, se
    queda sin algo.
  · solemne un momento grave o ceremonial.

POR QUE ES OBLIGATORIO Y ANTES NO LO ERA. Estaba escrito como «dilo si no es el
del tramo», y medido el 07-09-2026 sobre 44 planos: se dijo en 3. Los otros 41
cayeron al tono del tramo, que en ese video estaba vacio, asi que **27 de los 30
planos con gente salieron con la MISMA cara neutra y «No smiling»** -- la misma
para «cada euro que ganas vale menos» que para una familia a la que le alcanza.
La opcion existia y no se usaba; ahora es una casilla que hay que rellenar.

Lo mira una comprobacion antes de gastar un centimo (`direccion.sin_tono`), asi
que un plano con gente sin su tono se ve en el aviso, no en la imagen pagada.

Y MANDA LO QUE SE DICE EN ESE PLANO, no lo que se dice antes o despues. Su
frase esta debajo de cada uno. Si la frase se mueve, el plano se mueve con
ella:

  · una frase que dice «HOY» no se ilustra con la escena de hace cien anos que
    venia contandose, aunque el tramo vaya de eso: se ilustra con el HOY, que
    ademas es el paralelismo que la frase esta pidiendo;
  · una frase que nombra otro pais no se queda en el pais anterior;
  · una frase que dice que algo SUBE no se dibuja bajando.

Los dos pasaron de verdad y se vieron en el video montado.

=====================================================================
LOS PLANOS ({cuantos}, y los quiero TODOS)
=====================================================================
{planos}

DEVUELVE ESTE JSON:

{{"planos": {{"<id de plano>": "<que PASA en ese plano, en ingles>"}}}}

Los {cuantos} planos, ninguno menos y ninguno de mas.
"""


def _planos_legibles(escenas, beats=None):
    """Los planos para el agente: donde ocurre, quien sale, QUE PASA y que se narra.

    La accion del beat entra aqui como CONTEXTO: es lo que le dice al agente de
    que va este trozo del video, y sin ella escribiria cuarenta y nueve escenas
    sueltas en vez de una historia. Va marcada como «el tramo» para que se vea
    que la comparte con sus vecinos.

    Lo que NO es: el encargo. Hasta el 28-08 la nota de aqui decia que «lo que
    tiene que escribir es lo OTRO» --el encuadre-- y por eso salian cinco planos
    de la misma cocina cambiando solo la camara. Lo que tiene que escribir es
    QUE PASA en su plano, y desde entonces la accion del tramo ni siquiera viaja
    al modelo de imagen cuando el plano trae la suya (`p6_assets._prompt_escena`).
    """
    beats = list(beats or [])
    lineas = []
    for indice, escena in enumerate(escenas):
        beat = beats[indice] if indice < len(beats) else {}
        beat = beat if isinstance(beat, dict) else {}
        if not beat.get("accion"):
            # el plan lo trae escrito desde la ultima planificacion; un plan
            # anterior a esto simplemente no lo tiene, y entonces se calla
            beat = {"accion": escena.get("accion"), "tono": escena.get("tono")}
        donde = escena.get("set") or escena.get("componente") or "sin sitio"
        gente = ", ".join(escena.get("personajes") or []) or "nadie"
        cabeza = f"[{escena.get('id')}] sitio: {donde} · reparto: {gente}"
        encuadre = str(escena.get("encuadre") or "").strip()
        if encuadre:
            cabeza += f" · encuadre (no lo contradigas): {encuadre}"
        # LO QUE SE DICE VA PRIMERO, y el tramo debajo. El orden no es
        # cosmetica: lo de arriba se lee como el encargo y lo de abajo como el
        # marco. Estaba al reves, y con el al reves salian planos que
        # ilustraban el tramo en vez de su propia frase.
        cuerpo = [f"    SE DICE AQUI: {str(escena.get('narracion') or '').strip()}"]
        accion = str(beat.get("accion") or "").strip()
        if accion:
            tono = str(beat.get("tono") or "").strip()
            cuerpo.append(f"    (contexto, el tramo va de: {accion}"
                          + (f"; tono {tono})" if tono else ")"))
        lineas.append(cabeza + "\n" + "\n".join(cuerpo))
    return "\n".join(lineas)


def _sitios_legibles(catalogo, escenas):
    """Los sitios QUE SE USAN, con la descripcion que va a entrar en el prompt.

    Solo los que salen: el catalogo del video largo tiene treinta y un sitios y un
    video usa doce. Los diecinueve que sobran son ruido en la instruccion y
    ademas invitan a describir un sitio en el que no se rueda.
    """
    catalogo = catalogo if isinstance(catalogo, dict) else {}
    usados, orden = set(), []
    for escena in escenas:
        nombre = escena.get("set") or escena.get("componente")
        if nombre and nombre not in usados:
            usados.add(nombre)
            orden.append(nombre)
    lineas = []
    for nombre in orden:
        ficha = ((catalogo.get("sets") or {}).get(nombre)
                 or (catalogo.get("componentes") or {}).get(nombre) or {})
        texto = str(ficha.get("prompt") or ficha.get("descripcion") or "").strip()
        lineas.append(f"  [{nombre}] {texto or '(sin descripcion)'}")
    return "\n".join(lineas) or "  (ningun sitio declarado)"


def _reparto_legible(catalogo, escenas):
    """Quien sale en este video, con la descripcion que ya viaja en el prompt."""
    catalogo = catalogo if isinstance(catalogo, dict) else {}
    quienes, orden = set(), []
    for escena in escenas:
        for quien in (escena.get("personajes") or []):
            if quien not in quienes:
                quienes.add(quien)
                orden.append(quien)
    if not orden:
        return ""
    lineas = []
    for quien in orden:
        ficha = (catalogo.get("reparto") or {}).get(quien) or {}
        texto = str(ficha.get("descripcion") or "").strip()
        lineas.append(f"  [{quien}] {texto or '(sin descripcion)'}")
    return ("\nY EL REPARTO, tambien verbatim en el prompt de su plano. Ojo: la "
            "descripcion de cada uno viaja ADJUNTA COMO IMAGEN a los planos "
            "donde sale, asi que en un plano donde uno de estos aparece, "
            "aparece con ESA cara. Si un plano necesita a alguien generico "
            "--una persona cualquiera, un cliente, un empleado sin nombre-- eso "
            "no es ninguno de estos:\n\n"
            + "\n".join(lineas) + "\n")


def _estilo_legible(estilo):
    """La guia de estilo del video, tal y como la recibe el modelo de imagen.

    Se pide a `p6_assets.guia_escrita` y no se reescribe aqui: si hubiera dos
    versiones de la guia, el agente escribiria para una y el modelo dibujaria
    con la otra.
    """
    try:
        import p6_assets                                         # noqa: PLC0415
    except ImportError:                                          # pragma: no cover
        from . import p6_assets                                  # noqa: PLC0415
    piezas = p6_assets.guia_escrita(estilo or {})
    texto = "\n".join(piezas) if isinstance(piezas, (list, tuple)) else str(piezas)
    return texto.strip() or "(este video todavia no tiene guia de estilo escrita)"


def dirigible(escena):
    """Si este plano admite direccion: los que GENERAN una imagen.

    Una cartela es texto y una continuacion copia la imagen del hogar; escribir
    una direccion para ellos seria escribir para un plano que no se rueda, y en
    la lista del agente solo serviria para despistarlo.
    """
    escena = escena if isinstance(escena, dict) else {}
    if escena.get("sigue_a"):
        return False
    ficha = escena.get("cartela")
    if isinstance(ficha, dict) and ficha.get("plantilla"):
        # una cartela SOBRE IMAGEN si rueda su plano; la de fondo propio no
        try:
            import cartelas                                     # noqa: PLC0415
        except ImportError:                                      # pragma: no cover
            from . import cartelas                               # noqa: PLC0415
        return bool(cartelas.sobre_imagen(escena))
    return True


def limpiar_linea(texto):
    """Una direccion aceptable, o (None, motivo).

    Recorta por PALABRAS enteras y nunca a media palabra: una frase cortada por
    la mitad llega al modelo de imagen como una instruccion rota, y eso se ve en
    la imagen. Es la misma regla que las cartelas.
    """
    crudo = " ".join(str(texto or "").split())
    crudo = re.sub(r'^["\'`]+|["\'`]+$', "", crudo).strip()
    if not crudo:
        return None, "vacia"
    palabras = crudo.split()
    if len(palabras) < PALABRAS_MINIMAS:
        return None, f"solo {len(palabras)} palabra(s): no dice nada que dibujar"
    aviso = ""
    if len(palabras) > PALABRAS_MAXIMAS:
        crudo = " ".join(palabras[:PALABRAS_MAXIMAS]).rstrip(",;:")
        aviso = (f"{len(palabras)} palabras, se recorta a {PALABRAS_MAXIMAS}: "
                 f"a partir de ahi vuelve a describir el sitio")
    return crudo, aviso


def _limpiar(crudo, ids):
    """Valida lo que devuelve el agente contra los planos pedidos."""
    salida, avisos = {}, []
    if not isinstance(crudo, dict):
        return salida, ["la respuesta no trae un objeto de planos"]
    planos = crudo.get("planos") if isinstance(crudo.get("planos"), dict) else crudo
    for sid, texto in (planos or {}).items():
        sid = str(sid).strip().upper()
        if sid not in ids:
            avisos.append(f"{sid}: no es un plano de este video, se ignora")
            continue
        linea, motivo = limpiar_linea(texto)
        if linea is None:
            avisos.append(f"{sid}: {motivo}")
            continue
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        salida[sid] = linea
    faltan = [sid for sid in sorted(ids) if sid not in salida]
    if faltan:
        avisos.append(f"{len(faltan)} plano(s) se han quedado sin direccion: "
                      + ", ".join(faltan[:8]))
    return salida, avisos


def repetidas(plan, escenas):
    """Direcciones IGUALES entre planos, que es el fallo que esto viene a quitar.

    Se compara normalizado, porque «a hand covers the screen» y «A hand covers
    the screen.» son la misma indicacion. No se corrige sola: se dice, y se
    arregla volviendo a pedirla o escribiendola a mano -- igual que las cartelas
    que no caben (32.2 ter), no se llama al agente en bucle hasta que salga.
    """
    por_texto = {}
    for escena in (escenas or []):
        linea = plan.get(escena.get("id"))
        if not linea:
            continue
        por_texto.setdefault(medios.normalizar_texto(linea), []).append(escena["id"])
    return [sorted(ids) for ids in por_texto.values() if len(ids) > 1]


TONOS_VALIDOS = ("alegre", "neutro", "tenso", "triste", "solemne")

#: El tono que declara un plano al final de su linea. La MISMA expresion que lee
#: `p6_assets._TONO_DEL_PLANO`, y eso importa: si aqui se aceptara una forma que
#: alli no encaja, la comprobacion diria que si y el prompt saldria sin tono.
_TONO_ESCRITO = re.compile(r"\(\s*TONO\s*:\s*([a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa]+)\s*\)", re.I)


def sin_tono(plan, escenas):
    """Planos con gente cuya linea no declara el tono. -> [ids]

    El gemelo de `redactor.sin_declarar`, y existe por lo mismo: se comprueba UNA
    vez sobre lo dirigido y se dice ANTES de gastar un centimo, en vez de esperar
    a ver la cara en la imagen pagada.

    EL FALLO QUE MIDE (07-09-2026). El tono era opcional --«dilo si no es el del
    tramo»-- y sobre 44 planos se dijo en 3. Los otros 41 cayeron al tono del
    tramo, que en el video del oro estaba vacio, asi que 27 de los 30 planos con
    gente salieron con la misma cara neutra y «No smiling»: la misma para «cada
    euro que ganas vale menos» que para una familia a la que le alcanza.

    Un tono ESCRITO MAL tambien cuenta como sin declarar, y no es rigor de
    mas: `p6_assets._tono_de` solo reconoce los cinco de la tabla, asi que un
    «(TONO: preocupado)» no llega al prompt y el plano se queda con el del tramo
    sin que nadie lo diga.
    """
    flojos = []
    for escena in escenas or []:
        linea = str((plan or {}).get(escena.get("id")) or "")
        if not linea or not escena.get("personajes"):
            continue
        casa = _TONO_ESCRITO.search(linea)
        if not casa or casa.group(1).strip().lower() not in TONOS_VALIDOS:
            flojos.append(escena["id"])
    return flojos


def _llamar_claude(instruccion, modelo, esfuerzo, avance=None):
    """Se llama asi para poder engancharle el medidor de coste, que va POR NOMBRE.

    Entrega ESCRIBIENDO un fichero y no en el mensaje (`cli_claude.escribiendo`):
    dirigir un video de veinte minutos son 175 bloques, y eso en una respuesta se
    corta.
    """
    return cli_claude.escribiendo(
        instruccion, modelo=modelo, esfuerzo=esfuerzo,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        herramientas_vetadas=HERRAMIENTAS_VETADAS, avance=avance,
        para="la direccion de los planos", que="la direccion de los planos")


def proponer(escenas, ajuste=None, avisar=None, proyecto_id=None, cwd=None,
             titulo="", estilo=None, catalogo=None, beats=None, idioma=""):
    """Escribe que se ve en cada plano. NO escribe en params: propone.

    Devuelve {plan, avisos, ...}. Igual que el plan de cartelas y el de rotulos:
    proponer no es aprobar, y lo que se guarda despues es la DECISION.

    `cwd` se admite por simetria con los demas agentes y se IGNORA a proposito:
    aqui el agente escribe (ver FICHERO_SALIDA), y lo que escriba tiene que caer
    en una carpeta temporal, fuera del proyecto y fuera del repo.
    """
    ajuste = ajuste or {}
    modelo = ajuste.get("modelo") or MODELO_POR_DEFECTO
    esfuerzo = ajuste.get("esfuerzo") or ESFUERZO_POR_DEFECTO
    elegido = {"modelo": modelo, "esfuerzo": esfuerzo}

    todos = [e for e in (escenas or []) if e.get("id")]
    if not todos:
        raise RuntimeError("no hay planos: corta la narracion antes")
    # los beats van EN PARALELO a las escenas, asi que se filtran a la vez
    beats = list(beats or [])
    pares = [(e, beats[i] if i < len(beats) else {})
             for i, e in enumerate(todos) if dirigible(e)]
    dirigibles = [e for e, _ in pares]
    if not dirigibles:
        raise RuntimeError("ningun plano de este video genera imagen propia: "
                           "no hay nada que dirigir")

    prevision = estadisticas.estimar(PASO, tamano=len(dirigibles), ajuste=elegido)
    avance = None
    if avisar is not None:
        avance = estadisticas.Avance(
            avisar, 0.05, 0.9, prevision,
            f"leyendo los {len(dirigibles)} planos a la vez para que ninguno "
            f"repita al de al lado, con {modelo} (esfuerzo {esfuerzo})")
        avance.arrancar()

    instruccion = INSTRUCCION.format(
        titulo=titulo or "sin titulo",
        palabras_maximas=PALABRAS_MAXIMAS,
        # EL IDIOMA DEL VIDEO, y no es un adorno: ver la regla del rotulo. Si no
        # llega, se dice asi en vez de dejar el hueco: un «{idioma}» crudo en el
        # encargo es peor que una frase que reconoce que no se sabe.
        idioma=idioma or "el del guion que se te da mas abajo",
        estilo=_estilo_legible(estilo),
        sitios=_sitios_legibles(catalogo, dirigibles),
        reparto=_reparto_legible(catalogo, dirigibles),
        cuantos=len(dirigibles),
        planos=_planos_legibles(dirigibles, [b for _, b in pares]))

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

    plan, avisos = _limpiar(crudo, {e["id"] for e in dirigibles})
    for grupo in repetidas(plan, dirigibles):
        avisos.append(f"{' = '.join(grupo)}: misma direccion en varios planos, "
                      f"que es justo lo que esto viene a quitar -- vuelve a "
                      f"pedirla o cambiala a mano")
    mudos = sin_tono(plan, dirigibles)
    if mudos:
        avisos.append(f"{len(mudos)} plano(s) con gente no declaran su tono "
                      f"(se quedan con el del tramo, que es el mismo para todo "
                      f"el tramo): " + ", ".join(mudos[:8]))
    estadisticas.anotar(PASO, segundos, tamano=len(dirigibles), ajuste=elegido,
                        proyecto=proyecto_id, unidades=len(plan),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "planos": len(dirigibles), "dirigidos": len(plan)})
    return {
        "plan": plan,
        "avisos": avisos,
        "planos": len(dirigibles),
        "dirigidos": len(plan),
        "ajuste": elegido,
        "segundos": round(segundos, 1),
        "estimacion_s": prevision["segundos"],
    }


def describir(plan, escenas=None):
    """Frase corta para la pantalla."""
    plan = plan or {}
    if not plan:
        return "sin dirigir: cada plano se arma con su sitio y su frase"
    total = len([e for e in (escenas or []) if dirigible(e)]) or len(plan)
    repes = len(repetidas(plan, escenas or []))
    return (f"{len(plan)} de {total} planos dirigidos"
            + (f", {repes} repetida(s)" if repes else ""))
