"""
Como habla este canal: las instrucciones del guion, escritas a partir de una
descripcion en tus palabras.

Para que
--------
Las instrucciones del brief son lo que le dice al redactor QUE tono usar, cuanto
tecnicismo admitir y a quien le habla. Escribirlas bien cuesta, se hace distinto
cada vez, y describir una voz con precision es justo lo que peor se le da a
cualquiera: se acaba escribiendo "tono divulgativo pero riguroso" en todos los
videos, que no dice nada y no se puede cumplir ni incumplir.

Aqui se escribe en una frase o dos como se quiere que suene --"como quien te lo
cuenta en la barra de un bar y del tema sabe mas que tu", "seco y sin adjetivos,
que los datos hablen solos"-- y el CLI lo convierte en instrucciones DENSAS Y
ACCIONABLES: cada frase de la guia tiene que poder cumplirse o incumplirse al
escribir una linea de guion.

Lo que NO puede pasar, y es la regla entera del modulo
-----------------------------------------------------
Las instrucciones tienen que servir para CUALQUIER tema. Si de una descripcion
salen unas instrucciones que hablan del asunto del primer video, el siguiente
--sobre otra cosa cualquiera-- sale contaminado: el redactor arrastra un tema
que no es el suyo. Por eso la instruccion prohibe explicitamente nombrar temas,
personajes, datos y lugares, y pide el resultado escrito de forma que se pueda
pegar delante de cualquier trama.

Es el gemelo narrativo de `estilo.py`: alli se describe como se DIBUJA (y se
acompana de imagenes), aqui como se CUENTA.
"""
import json
import os
import time

try:
    from . import cli_claude, comun, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import estadisticas

PASO = "tono"
TIEMPO_BASE_S = 240

# El ajuste de ESTA fase, no el general del CLI. Sin esto, llamar a deducir()
# sin ajuste caia en sonnet/low: el mismo agujero que tuvo la guia de estilo
# durante meses, y por el mismo motivo -- el resultado siempre es un texto
# plausible, asi que nadie se entera de que se coló por el escalon barato.
MODELO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["modelo"]
ESFUERZO_POR_DEFECTO = cli_claude.por_defecto_de(PASO)["esfuerzo"]


SISTEMA = ("Responde exclusivamente con el objeto JSON pedido, sin texto "
           "alrededor y sin vallas de markdown.")

#: EL CONTRATO DE SALIDA, compartido por los dos caminos que describen como
#: habla un canal: leyendo transcripciones de videos suyos o leyendo una
#: descripcion escrita. Vive aparte por lo mismo que el de la guia de estilo
#: -- es el esquema que leen el brief, el resumen del preset y la pantalla --
#: y porque duplicado se desincroniza en cuanto alguien anade un rasgo.
CONTRATO_JSON = """\
DEVUELVE SOLO ESTE JSON
{{"instrucciones": "el texto que se pega en las instrucciones del guion.
ESCRITO EN {idioma}, que es la lengua de los videos de este canal, y sin nombrar
ningun idioma dentro. En segunda persona, entre 400 y 700 palabras, en parrafos
cortos o con guiones. Denso y accionable: cada frase tiene que poder cumplirse o
incumplirse al escribir una linea de guion. Nada de adjetivos vacios del tipo
'tono profesional pero cercano' sin decir en que se nota. Tiene que cubrir las
DOS mitades: como suena (registro, ritmo, persona) y que se hace con el material
(estructura, storytelling, bloques, tratamiento de las fuentes). Si el canal
tiene un mundo propio, ese mundo entra tambien AQUI y no solo en su campo: es lo
primero que el redactor necesita saber para escribir una linea.",
  "mundo": "El universo propio del canal, SI LO TIENE, y la cadena vacia si no.
Hay canales que lo cuentan todo dentro de un mundo inventado que se repite video
tras video: unas criaturas, un sitio, unos objetos que ocupan el lugar de los
reales. Si estos videos comparten uno, escribe tres cosas y en este orden:
(a) EL MUNDO, con palabras normales del idioma -- que criaturas, donde pasa todo,
de que esta hecho, que se come, en que se trabaja --. Esas palabras ya existian
antes que el canal, asi que van tal cual: sin ellas no hay mundo.
(b) EL DICCIONARIO DE ESTE CANAL, QUE ACUNAS TU. Un termino NUEVO y propio para
el dinero, el vehiculo, el telefono, la vivienda, el trabajo, la comida y lo que
mas vaya a salir, cada uno con la equivalencia al lado. Hechos con el material
del mundo y con el mismo tipo de broma que gastan esos videos, pero TUYOS: los
del canal de referencia se los invento su autor y no se copia ni uno.
(c) LA RECETA para acunar uno mas el dia que salga un objeto que no esta en tu
lista, para que el redactor no se quede parado ni vuelva a la palabra literal.
De cinco a diez frases, y el diccionario en forma de lista de equivalencias. Si
estos videos no comparten ningun mundo, que es lo normal, deja la cadena VACIA:
inventarle un mundo a un canal que cuenta las cosas tal cual es tan grave como
perderle el suyo al que lo tiene.",
  "registro": "dos o tres frases: formal, neutro, cercano o callejero; se tutea o
se trata de usted; hay humor, ironia o gravedad; cuanta distancia se guarda",
  "nivel_tecnico": "dos frases: cuanto tecnicismo admite, si lo explica al usarlo
o lo da por sabido, y como traduce lo dificil",
  "publico": "una o dos frases: a quien le habla y cuanto se da por sabido",
  "ritmo": "dos o tres frases sobre el RELATO (no sobre el montaje): longitud de
frase, cuanto tarda en llegar al grano, si abre con gancho o con contexto, donde
acelera y donde se para",
  "estructura": "de tres a cinco frases: como se ordena un video de este canal de
principio a fin. Con que se abre y en cuantos segundos, en que orden va lo que
sigue, donde se coloca el contexto, como se cierra y si hay remate. Escrito de
forma que se pueda seguir con cualquier material delante",
  "storytelling": "dos o tres frases: que forma de contar usa --caso que se
investiga, cronologia, tesis con sus pruebas, misterio que se resuelve, perfil de
alguien, explicacion de un mecanismo-- y como se sostiene la atencion sin
recurrir a trucos",
  "bloques": "dos o tres frases: si el relato va en BLOQUES con corte entre ellos
o seguido, de que tamano es un bloque, con que se abre y se cierra cada uno, y
como se enlaza con el siguiente",
  "fuentes": "de tres a cinco frases, y es la parte que mas se usa: QUE SE HACE
con el material de partida. Que se conserva y que se tira (menus de navegacion,
notas al pie, plantillas, listas de referencias, pies de foto, tablas sueltas);
como se ordena cuando llegan VARIAS fuentes a la vez y se solapan o se
contradicen; que se hace con un dato que no se puede confirmar; que nunca se
inventa; y si la fuente trae opinion, como se separa del hecho",
  "evitar": "de tres a seis frases con lo que NO debe hacer nunca, concretas y en
negativo",
  "resumen": "una linea corta para reconocer este tono en un desplegable"}}

TODOS los campos de ese JSON van en {idioma}, no solo las instrucciones: son la
misma guia partida en piezas y media guia en otra lengua no sirve.
"""


#: EN QUE LENGUA SE ESCRIBE LA GUIA DE TONO. En la del canal, y no en
#: castellano siempre: la lee el redactor, que va a escribir en esa lengua.
#:
#: Salio de leer la primera guia generada de verdad: con el estilo puesto en
#: INGLES, las instrucciones empezaban por «Redacta siempre en castellano
#: neutro» y daban los ejemplos de remate en castellano. Tres ajustes distintos
#: --el idioma, la duracion del video y el tamano de bloque-- pisados por un
#: prompt que no sabia que existian.
def nombre_de_idioma(codigo):
    """'en' -> 'INGLES'. En mayusculas porque va dentro de una orden.

    Se pide a `p2_brief`, que es quien tiene la tabla, en vez de escribir aqui
    una cuarta copia de la misma lista. Tarde, porque p2_brief arrastra el
    catalogo del brief y esto se importa desde el arranque.
    """
    try:
        from . import p2_brief                              # noqa: PLC0415
    except ImportError:
        import p2_brief                                     # noqa: PLC0415
    codigo = p2_brief.normalizar_idioma(codigo) or "es"
    return str(p2_brief.nombre_idioma(codigo) or codigo).upper()


#: Que pistas de subtitulos se piden. Es una LISTA DE LA COMPRA y no una
#: prioridad: yt-dlp se baja todas las que casen. Cual se lee se decide despues,
#: y se decidia solo por el nombre del fichero -- ver `_transcripcion`.
PISTAS = "es.*,en.*,pt.*,fr.*,it.*,de.*"


def _llamar_claude(instruccion, modelo, esfuerzo, cwd, avance=None):
    """Se llama asi para que el medidor de coste pueda engancharla por nombre."""
    return cli_claude.ejecutar(
        instruccion, modelo=modelo, esfuerzo=esfuerzo, cwd=cwd,
        tiempo_max_s=0, base_tiempo_s=TIEMPO_BASE_S,
        sistema=SISTEMA, permisos="acceptEdits", avance=avance,
        para="las instrucciones de guion")


# Los rasgos, con la etiqueta con la que se leen en pantalla y con la que se
# pegan en el brief. Eran CINCO y todos sobre como suena la voz; desde el 23-08
# son nueve, porque unas instrucciones que solo describen el sonido no bastan
# para escribir un guion con un material delante.
#
# Los cuatro nuevos son la otra mitad del trabajo: como se ORDENA un video
# (estructura), con que FORMA se cuenta (storytelling), si va a trozos o seguido
# (bloques) y --el que mas se va a usar-- que se hace con el MATERIAL DE PARTIDA
# (fuentes), que puede ser un video, un articulo, cinco articulos pegados con sus
# menus y sus notas al pie, o cuatro parrafos sueltos.
#
# Una ficha escrita antes de esto trae los cinco viejos y ninguno de los nuevos,
# y sigue valiendo: `_texto_completo` solo pega lo que hay.
RASGOS = (
    # EL PRIMERO, y no por orden de aparicion: es lo unico que hay que leer
    # antes de escribir la primera linea, y en los canales que lo tienen es lo
    # que se reconoce de ellos. En los que no lo tienen viene vacio y no se
    # pinta, ni aqui ni en la pantalla.
    ("mundo", "El mundo del canal"),
    ("registro", "Registro"),
    ("nivel_tecnico", "Nivel tecnico"),
    ("publico", "Publico"),
    ("ritmo", "Ritmo del relato"),
    ("estructura", "Estructura"),
    ("storytelling", "Forma de contar"),
    ("bloques", "Bloques"),
    ("fuentes", "Que hacer con las fuentes"),
    ("evitar", "Evita"),
)


def _texto_completo(instrucciones, datos):
    """El parrafo mas los cinco rasgos, listo para pegar en el brief.

    En la pantalla el parrafo y la ficha se ven separados porque asi se revisan
    mejor, pero lo que se COPIA tiene que ser todo: el nivel tecnico y el
    publico son justo lo que hay que decirle al redactor, y quedandose en la
    ficha se perdian al pulsar el boton.
    """
    lineas = [instrucciones]
    sueltos = [f"{etiqueta}: {' '.join(str(datos.get(clave) or '').split())}"
               for clave, etiqueta in RASGOS
               if str(datos.get(clave) or "").strip()]
    if sueltos:
        lineas.append("\n".join(sueltos))
    return "\n\n".join(lineas)


# --------------------------------------------- el tono SIN videos de referencia
#
# El gemelo de `estilo.guia_de_descripcion`, y por el mismo motivo: en modo light
# el canal puede describir como quiere sonar en vez de dar videos que ya suenan
# asi. Lo que cambia es de donde sale el material; el CONTRATO de salida es el
# mismo, y por eso lo comparten (`CONTRATO_JSON`).
#
# LA REGLA DEL MODULO SIGUE EN PIE, y aqui hace aun mas falta: lo que salga tiene
# que valer para cualquier tema. Una descripcion como "quiero contar casos de
# estafas" mezcla el TEMA con el TONO, y si el tema se cuela en las
# instrucciones, el guion de un video sobre otra cosa sale contaminado. Por eso
# se le dice explicitamente que separe una cosa de la otra y se quede con la
# segunda.

INSTRUCCION_DESCRITO = """\
Eres guionista de documental. El dueno de un canal te ha descrito con sus
palabras COMO quiere que suenen sus guiones, y tienes que convertir eso en las
INSTRUCCIONES DE VOZ con las que se van a redactar.

LO QUE HA ESCRITO, entre comillas y tal cual:
"{descripcion}"

QUE HACER CON ESO
Concretarlo hasta que se pueda obedecer. Lo que ha escrito suele ser una
intencion en tres o cuatro palabras --"serio pero cercano", "como un true
crime"-- y unas instrucciones asi no se pueden cumplir ni incumplir. Tu trabajo
es decidir, de forma coherente con lo que ha pedido, todo esto:

- el registro: formal, neutro, cercano, callejero; se tutea o se trata de usted;
  hay humor, ironia, gravedad
- el nivel tecnico: cuantos tecnicismos admite, si los explica al usarlos o los
  da por sabidos, a que publico le habla (alguien del gremio o cualquiera)
- el ritmo: frases largas y subordinadas o cortas y secas; cuanto tarda en
  llegar al grano; si abre con gancho o con contexto
- como maneja los datos: cifras redondeadas o exactas, si cita fuentes, si
  compara con cosas cotidianas para que se entiendan
- la persona y la distancia: primera o tercera, si se dirige al espectador, si
  se permite opinar o se mantiene fuera
- los recursos que repite: preguntas retoricas, enumeraciones, adelantar lo que
  viene, silencios, repeticiones
- lo que EVITA: coletillas de youtuber, cliffhangers baratos, adjetivos vacios,
  sensacionalismo

Y LA MITAD QUE NO ES SONIDO, que tendras que decidir tu entera porque el no la
ha descrito:

- la ESTRUCTURA: con que abre un video de este canal, en que orden va lo que
  sigue, donde entra el contexto, como cierra
- el STORYTELLING: caso que se investiga, cronologia, tesis con pruebas, misterio
  que se resuelve, perfil, explicacion de un mecanismo
- los BLOQUES: si el relato va a trozos con corte entre ellos o seguido, y de que
  tamano es cada trozo
- y el TRATAMIENTO DE LAS FUENTES. Los guiones de este canal no siempre saldran
  de un video: pueden salir de un articulo, de cinco articulos pegados de golpe
  con sus menus y sus notas al pie, o de cuatro parrafos sueltos. Escribe que se
  conserva y que se tira, como se ordena cuando llegan varias fuentes que se
  solapan o se contradicen, que se hace con un dato que no se puede confirmar, y
  que no se inventa nunca.

EN QUE IDIOMA ESCRIBES ESTO
Los videos de este canal son en {idioma}, asi que ESCRIBE LAS INSTRUCCIONES EN
{idioma}: las lee el redactor, que va a redactar en esa lengua, y unas
instrucciones en otro idioma le obligan a traducir cada matiz. Los ejemplos que
pongas entre comillas --un remate, una interpelacion-- tambien en {idioma}.

Y NO escribas «redacta en {idioma}» ni nombres ningun idioma dentro del texto:
el idioma lo fija un ajuste del canal y puede cambiarse sin volver a escribirte
a ti. Una instruccion que lo repite se queda mintiendo el dia que cambie.

Si un rasgo solo existe en una lengua --el tuteo y el usted del castellano, el
genero gramatical, las formas de cortesia-- describe el MECANISMO ("trata al
espectador de tu a tu, sin distancia formal") y no la forma concreta.

LO QUE TAMPOCO DECIDES TU
Estas instrucciones conviven con otros ajustes, y fijar aqui lo que ellos deciden
no es un matiz: es una contradiccion que el redactor se encuentra delante.

- LA DURACION DEL VIDEO. Cambia en cada uno y la fija su propio ajuste. No digas
  cuanto dura un video de este canal.
- EL TAMANO DE BLOQUE Y LA DURACION DE PLANO. Tambien son ajustes, y hay ademas
  un mando de RITMO que los mueve. Describe COMO funciona un bloque --con que
  abre, con que cierra, como enlaza con el siguiente-- y nunca cuantos segundos
  ni cuantas palabras mide.

Lo que el haya fijado manda sobre lo que a ti te parezca que queda mejor. Lo que
no haya dicho lo decides tu y lo dejas escrito: un hueco aqui lo rellena el
redactor de otra forma en cada video, y entonces el canal no suena igual dos
veces.

LA REGLA QUE NO PUEDES SALTARTE
El resultado tiene que valer para CUALQUIER tema: manana graba sobre un banco,
pasado sobre un accidente aereo y despues sobre una estafa. Asi que:

- Si en su descripcion hay un TEMA ("hablo de crimenes", "hago videos de
  finanzas"), usalo solo para entender a quien le habla y con que gravedad, y
  NO lo nombres en las instrucciones. Lo que describes es la VOZ, no el asunto.
- NO nombres canales, programas, series ni presentadores concretos, ni aunque el
  los haya nombrado: describe COMO hablan, con rasgos que se puedan cumplir.
- Escribelo como ordenes al redactor, en segunda persona y en {idioma}.

EL MUNDO PROPIO, SI LO HA DESCRITO
Si en lo que ha escrito hay un universo --unas criaturas, un sitio, objetos que
ocupan el lugar de los reales-- eso NO es el tema: es parte del tono, y va en
`mundo` y tambien dentro de las instrucciones. Es la unica excepcion a la regla
de arriba, y existe porque un guion sin ese mundo no se parece en nada a lo que
ha pedido.

El mundo se nombra con las palabras normales del idioma que el haya usado. El
DICCIONARIO lo ACUNAS TU: un termino nuevo y propio para el dinero, el vehiculo,
el telefono, la vivienda y lo que mas salga, con su equivalencia al lado y fijos
para siempre, mas la receta para acunar uno mas. Si el ha nombrado un canal o un
video que le gusta, los terminos inventados de ese canal son de su autor y no se
copian: se copia la forma de inventarlos.

Si no ha descrito ningun mundo, no se lo inventes: deja `mundo` vacio.

""" + CONTRATO_JSON


def _ficha_de_tono(datos, instrucciones, ajuste, segundos, fuentes=(), avisos=()):
    """La ficha del tono, venga de transcripciones o de una descripcion.

    Una sola, por lo mismo que la de la guia de estilo: la leen el brief, el
    preset y la pantalla por claves, y dos diccionarios escritos a mano se
    separan en cuanto alguien anade un rasgo.
    """
    completo = _texto_completo(instrucciones, datos)
    return {
        "instrucciones": instrucciones,
        # Lo que de verdad se pega en el brief: el parrafo MAS los cinco
        # rasgos. En pantalla se leen aparte porque asi se revisan mejor,
        # pero separarlos al copiarlos dejaba fuera la mitad de lo util --
        # el nivel tecnico y el publico son justo lo que hay que decirle al
        # redactor, y se quedaban de adorno.
        "texto_completo": completo,
        # El universo propio del canal, cuando lo tiene. Vacio es una respuesta
        # y la normal: la mayoria de los canales cuentan las cosas tal cual.
        "mundo": str(datos.get("mundo") or "").strip(),
        "registro": str(datos.get("registro") or "").strip(),
        "nivel_tecnico": str(datos.get("nivel_tecnico") or "").strip(),
        "publico": str(datos.get("publico") or "").strip(),
        "ritmo": str(datos.get("ritmo") or "").strip(),
        # La otra mitad: como se ordena, con que forma se cuenta, si va a
        # trozos, y que se hace con el material de partida.
        "estructura": str(datos.get("estructura") or "").strip(),
        "storytelling": str(datos.get("storytelling") or "").strip(),
        "bloques": str(datos.get("bloques") or "").strip(),
        # OJO CON EL NOMBRE. `fuentes` es un RASGO del tono ("que hacer con el
        # material de partida", ver RASGOS) y aqui habia ademas una segunda
        # clave `fuentes` con la lista de videos leidos: la segunda pisaba a la
        # primera y el rasgo desaparecia de la ficha en silencio. Los videos son
        # `referencias`, que ademas es lo que son.
        "fuentes": str(datos.get("fuentes") or "").strip(),
        "evitar": str(datos.get("evitar") or "").strip(),
        "resumen": " ".join(str(datos.get("resumen") or "").split()),
        "referencias": list(fuentes),
        "avisos": list(avisos),
        "ajuste": ajuste,
        "segundos": round(segundos, 1),
        "palabras": len(completo.split()),
    }


def desde_descripcion(proyecto, descripcion, modelo=None, esfuerzo=None,
                      avisar=None, proyecto_id=None, peticion="", idioma="es"):
    """Escribe las instrucciones de guion a partir de una descripcion escrita.

    Mismo contrato que `deducir` y `fuentes` vacio, que es la verdad: este tono
    no sale de ningun video.
    """
    def avisa(valor, mensaje=""):
        if callable(avisar):
            avisar(valor, mensaje)

    descripcion = " ".join(str(descripcion or "").split())
    if len(descripcion) < 8:
        raise ValueError("describe el tono con algo mas de detalle: con dos "
                         "palabras las instrucciones se las inventa enteras")

    modelo = cli_claude.normalizar_modelo(modelo, estricto=False,
                                          defecto=MODELO_POR_DEFECTO)
    esfuerzo = cli_claude.normalizar_esfuerzo(esfuerzo, estricto=False,
                                              defecto=ESFUERZO_POR_DEFECTO)
    ajuste = {"modelo": modelo, "esfuerzo": esfuerzo}

    trabajo = os.path.join(proyecto.raiz, "tono")
    os.makedirs(trabajo, exist_ok=True)
    instruccion = INSTRUCCION_DESCRITO.format(
        descripcion=descripcion, idioma=nombre_de_idioma(idioma))
    instruccion += comun.bloque_correccion(peticion,
                                           "las instrucciones de guion")

    prevision = estadisticas.estimar(PASO, tamano=0, ajuste=ajuste)
    avance = None
    if callable(avisar):
        avance = estadisticas.Avance(
            avisar, 0.05, 0.95, prevision,
            f"escribiendo el tono a partir de tu descripcion con {modelo}")
        avance.arrancar()
    else:
        avisa(0.05, "escribiendo el tono a partir de tu descripcion")

    arranque = time.time()
    try:
        texto_cli, sobre = _llamar_claude(instruccion, modelo, esfuerzo,
                                          trabajo, avance)
    except BaseException:
        if avance is not None:
            avance.parar()
        estadisticas.anotar(PASO, time.time() - arranque, ok=False,
                            ajuste=ajuste, proyecto=proyecto_id,
                            resultado="error")
        raise
    segundos = avance.parar() if avance is not None else time.time() - arranque

    datos = comun.extraer_json(texto_cli, "las instrucciones de guion")
    instrucciones = " ".join(str(datos.get("instrucciones") or "").split())
    if not instrucciones:
        raise RuntimeError("el modelo no ha devuelto ningunas instrucciones")

    estadisticas.anotar(PASO, segundos, tamano=0, ajuste=ajuste,
                        proyecto=proyecto_id, unidades=0,
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "videos": 0, "de_descripcion": True,
                                 "palabras": len(instrucciones.split()),
                                 "tokens_salida":
                                     comun.tokens_de_cli(sobre).get("salida")})
    ficha = _ficha_de_tono(datos, instrucciones, ajuste, segundos)
    ficha["descripcion"] = descripcion
    return ficha
