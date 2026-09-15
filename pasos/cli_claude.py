"""
El unico sitio que arma y lanza una orden del CLI de Claude.

Por que existe
--------------
La lista de argumentos estaba copiada en tres ficheros (p3_guion, p5_revision_audio
y app.py) y ya paso una vez que "faltaban los flags del CLI en dos de los cuatro
sitios": el paso de guion tardaba 70 s y el mismo trabajo lanzado desde otra
pantalla tardaba diez minutos, porque a esa copia se le habia olvidado --effort.
Un solo sitio hace imposible ese fallo.

El esfuerzo es la variable que mas manda
----------------------------------------
Medido con el mismo transcript de 9.341 palabras y la misma instruccion:

    sin --effort, con el entorno limpio      605,8 s   78.447 tokens de salida
    sin --effort, heredando CLAUDE_EFFORT    336,3 s   39.679 tokens de salida
    con --effort low                          67,0 s    7.031 tokens de salida

De ahi salen dos reglas que este modulo aplica siempre:

1. El esfuerzo va SIEMPRE explicito. Si no, el mismo ajuste tarda distinto segun
   con que entorno se arranco el servicio, y entonces ninguna medida vale.
2. **El tiempo maximo escala con el esfuerzo.** Un techo fijo de 420 s con
   esfuerzo 'high' es una trampa: garantiza TiempoAgotado, y TiempoAgotado no se
   reintenta a proposito. Ofrecer un esfuerzo cuyo techo no le da tiempo a
   terminar es ofrecer un boton que solo sabe fallar.

Uso
---
    from . import cli_claude

    texto, sobre = cli_claude.ejecutar(
        instruccion, modelo="sonnet", esfuerzo="low",
        cwd=carpeta, tiempo_max_s=0)      # 0 = automatico segun el esfuerzo

`sobre` es el JSON del CLI con un bloque `_ajuste` anadido (modelo, esfuerzo y
segundos reales), que es lo que despues leen el medidor de coste y el historico.
El CLI no informa del esfuerzo en su respuesta, asi que si no lo estampa quien
llama, el historico se queda ciego justo en la variable que mas mueve el tiempo.
"""
import os
import re
import shutil
import subprocess
import time

# ------------------------------------------------------------------ catalogo

# Alias que entiende el CLI. Se validan contra esta lista porque un modelo mal
# escrito hoy solo se detecta por returncode != 0, o sea despues de haber pagado
# el arranque del CLI y la espera entera.
# Sin ventana negra. El CLI se invoca a traves de claude.cmd, o sea un proceso
# de consola, y desde un servicio eso abre una ventana encima de todo por cada
# llamada -- una por bloque de guion, una por escenario --. Trabajando por
# escritorio remoto es la pantalla tapandose sola durante veinte minutos.
# Escrito aqui y no importado de `medios`: este modulo se carga antes que el, y
# no tiene ninguna otra razon para conocerlo.
SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}

MODELOS = ("haiku", "sonnet", "opus")

# Un id completo tambien vale: el catalogo cambia mas rapido que este fichero.
PATRON_MODELO_COMPLETO = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]*$")

ESFUERZOS = ("low", "medium", "high", "xhigh", "max")

# LO QUE CORRE CUANDO NADIE ELIGE: OPUS CON ESFUERZO MUY ALTO.
#
# Decision del canal (21-08-2026): «que por defecto todo corra en Opus 5 Extra,
# que el selector en todos ellos este por defecto en Opus 5 Extra, aunque si lo
# cambio que se mantenga mi cambio». Antes era sonnet/low, que es lo barato, y la
# consecuencia era que cada fase salia con lo minimo salvo que alguien se
# acordara de subirla una por una.
#
# LO QUE CUESTA, dicho aqui para que nadie lo descubra mirando el reloj: son
# 17,6 veces el tiempo de sonnet/low (2,2 del modelo por 8,0 del esfuerzo), y hay
# fases que llaman UNA VEZ POR PLANO -- son 49 llamadas en el video
# del video largo --. Se elige a sabiendas; el selector de cada tarjeta sigue ahi
# para bajarlo donde no compense, y lo que se baje se recuerda.
MODELO_POR_DEFECTO = "opus"
ESFUERZO_POR_DEFECTO = "xhigh"

# Cuanto multiplica cada esfuerzo al tiempo de 'low'. NO son medidas: 'low' es lo
# unico medido de verdad (67 s frente a los 605,8 s de no pasar el flag). Son
# ordenes de magnitud para que el techo de tiempo y la primera estimacion sean
# razonables; en cuanto haya historial de una combinacion, manda el historial.
FACTOR_ESFUERZO = {"low": 1.0, "medium": 2.5, "high": 5.0, "xhigh": 8.0, "max": 12.0}

# Lo mismo para el modelo, relativo a sonnet.
FACTOR_MODELO = {"haiku": 0.6, "sonnet": 1.0, "opus": 2.2}

# Techo absoluto. Un trabajo puede tardar mucho y eso es legitimo (la barra lo
# ensena y se puede cancelar), pero mas de una hora esperando a una sola llamada
# es casi siempre algo colgado, no algo trabajando.
TIEMPO_MAXIMO_S = 3600
TIEMPO_MINIMO_S = 30

# Variables del entorno que le cambian el razonamiento al CLI. --effort ya pisa a
# CLAUDE_EFFORT (medido), pero MAX_THINKING_TOKENS actua por su cuenta, y el
# Estudio se arranca a menudo desde una sesion de Claude Code que las trae
# puestas: se quitan para que tarde lo mismo se lance desde donde se lance.
ENTORNO_FUERA = ("CLAUDE_EFFORT", "MAX_THINKING_TOKENS")

# Y las que sacarian la llamada FUERA de la suscripcion: una clave de API, un
# token, una pasarela o un proveedor en la nube. El Estudio consume la
# suscripcion del CLI y solo esa, asi que ninguna variable heredada del entorno
# puede convertir un paso en pago por uso sin que nadie se entere. Se borran en
# el entorno del HIJO, que es lo unico que hace la garantia independiente de
# desde donde se arranque el servicio.
#
# Duplicado a proposito en los cinco sitios que llaman al CLI (watcher, creador,
# nocturno de X, nocturno de SEO y aqui), por la misma razon que uso_cli.py: los
# sistemas se conectan por contrato, nunca importandose codigo.
PAGO_POR_USO = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")

# Sin herramientas el CLI contesta en un solo turno: para redactar texto no tiene
# nada que leer ni que escribir, todo el material va en la instruccion.
HERRAMIENTAS_VETADAS = ("Bash", "Read", "Write", "Edit", "NotebookEdit", "Glob",
                        "Grep", "WebFetch", "WebSearch", "Task", "TodoWrite")


class TiempoAgotado(RuntimeError):
    """La llamada al CLI vencio. No se reintenta: volveria a vencer."""


class LimiteAgotado(RuntimeError):
    """Se acabo el cupo de la suscripcion. Tampoco se reintenta.

    Pasa lo mismo que con un timeout y por eso comparte forma: reintentar es
    volver a fallar. Pero se distingue por dos motivos, y los dos se vieron el
    24-08-2026, cuando el cupo semanal se agoto a mitad de una tanda:

    1. **Lo que se ve.** El CLI sale con codigo 1 y su mensaje ("has agotado tu
       limite semanal, se renueva el 27 de agosto a las 7:00") viaja DENTRO del
       sobre JSON, en `result`. Sin mirar ahi, lo que llegaba a la pantalla era
       600 caracteres de JSON crudo con `input_tokens: 0` -- que parece una
       averia del Estudio y no lo es.

    2. **Lo que se hace.** Un cupo agotado se reintenta unas cuantas veces en un
       segundo cada una, se gastan todos los reintentos y el paso muere igual;
       peor: el error que se guarda es el del ULTIMO intento, o sea el mismo
       mensaje pero sin la pista de que ya se sabia desde el primero.

    Con la cuenta de respaldo SI se reintenta una vez (`ejecutar`): un login
    distinto tiene un cupo distinto, que es justo para lo que existe.
    """


# ------------------------------------------------------------------ validacion

#: Con que codigo sale una SUITE que no ha podido correr porque no hay cupo.
#: No es 1 a proposito: `pruebas.ps1` lo pinta como CUPO y no lo cuenta como
#: fallo. Una suite que necesita el CLI de verdad --la cadena de guion es la
#: unica-- se pondria en rojo durante los dias que tarde en renovarse el cupo, y
#: un rojo que no significa nada roto es peor que no correrla: ensena a ignorar
#: el rojo. 3 y no 2 porque 2 es lo que devuelve el propio python al no poder
#: abrir el fichero.
CODIGO_SIN_CUPO = 3

#: Como suena un cupo agotado, en los dos idiomas en que puede contestar el CLI.
#: Se casa por PAREJAS (algo de limite + algo de agotado/renovado) y no por
#: frases enteras: el texto exacto cambia cada vez que cambia el CLI, y una
#: frase literal que deje de casar volveria a dar el JSON crudo en pantalla.
_LIMITE_QUE = ("limit", "limite", "límite", "quota", "cuota")
_LIMITE_COMO = ("reset", "renov", "reach", "hit your", "has alcanzado",
                "has agotado", "agotado", "exceed", "superado", "upgrade")


def limite_de(texto):
    """El mensaje si el CLI dice que se acabo el cupo; si no, None. -> str|None

    Se lee del `result` del sobre, que es donde el CLI pone su explicacion en
    cristiano. Lo que devuelve es ese mismo texto limpio, para poder ensenarlo
    tal cual: dice la fecha en que se renueva, y esa fecha es lo unico que le
    importa a quien esta mirando la pantalla.
    """
    plano = str(texto or "").strip()
    if not plano:
        return None
    bajo = plano.lower()
    if any(q in bajo for q in _LIMITE_QUE) and any(c in bajo for c in _LIMITE_COMO):
        return plano
    return None


def modelo_valido(valor):
    """True si el CLI va a entender ese modelo."""
    texto = str(valor or "").strip().lower()
    return bool(texto) and (texto in MODELOS
                            or bool(PATRON_MODELO_COMPLETO.match(texto)))


def normalizar_modelo(valor, estricto=True, defecto=MODELO_POR_DEFECTO):
    texto = str(valor or "").strip().lower()
    if not texto:
        return defecto
    if not modelo_valido(texto):
        if estricto:
            raise ValueError(
                f"modelo desconocido: {texto!r}. Usa uno de "
                f"{', '.join(MODELOS)} o un id completo tipo 'claude-opus-5'")
        return defecto
    return texto


def normalizar_esfuerzo(valor, estricto=True, defecto=ESFUERZO_POR_DEFECTO):
    texto = str(valor or "").strip().lower()
    if not texto:
        return defecto
    if texto not in ESFUERZOS:
        if estricto:
            raise ValueError(
                f"esfuerzo tiene que ser uno de {', '.join(ESFUERZOS)}")
        return defecto
    return texto


def factor(modelo=MODELO_POR_DEFECTO, esfuerzo=ESFUERZO_POR_DEFECTO):
    """Cuanto se espera que multiplique una combinacion al tiempo de sonnet/low."""
    return (FACTOR_MODELO.get(str(modelo or "").strip().lower(), 1.0)
            * FACTOR_ESFUERZO.get(str(esfuerzo or "").strip().lower(), 1.0))


def tiempo_max(esfuerzo=ESFUERZO_POR_DEFECTO, base_s=420, modelo=None,
               pedido_s=0):
    """Segundos que se le dan a UNA llamada antes de cortarla.

    `pedido_s` mayor que cero manda: es el techo que ha fijado una persona a
    mano. Con 0 el techo se deriva del esfuerzo, que es lo unico que evita la
    trampa de ofrecer 'high' contra un techo pensado para 'low'.
    """
    try:
        pedido_s = int(pedido_s or 0)
    except (TypeError, ValueError):
        pedido_s = 0
    if pedido_s > 0:
        return max(TIEMPO_MINIMO_S, min(TIEMPO_MAXIMO_S, pedido_s))
    escala = factor(modelo or MODELO_POR_DEFECTO, esfuerzo)
    return int(max(TIEMPO_MINIMO_S,
                   min(TIEMPO_MAXIMO_S, round(float(base_s) * escala))))


# Ajuste por defecto de cada fase, elegido por la COMPLEJIDAD de su tarea y no
# por inercia.
#
# De donde salen estos valores
# ----------------------------
# De la matriz por tipo de tarea que publican las guias del parametro de
# esfuerzo, no de una corazonada:
#
#   pregunta simple, clasificacion, lotes ......... bajo
#   generacion de contenido, redaccion rutinaria .. medio
#   revision de codigo, depuracion, trabajo creativo alto
#   arquitectura, analisis legal, flujos agenticos  maximo
#
# Y de tres hallazgos medidos que corrigen la intuicion de "mas esfuerzo es
# siempre mejor":
#
#   - En FrontierCode v1.1, Opus 5 con esfuerzo MEDIO es la configuracion mas
#     eficiente por computo (53,4 %), y el esfuerzo alto da rendimientos
#     decrecientes o ligeramente negativos en tareas de codigo.
#   - La calidad escala casi lineal hasta 'xhigh' y ahi se aplana: 'max' es
#     mucho gasto para muy poco, y quien lo ha medido lo llama una trampa.
#     El alto ya da el 90-95 % de la calidad del maximo por una fraccion.
#   - El esfuerzo bajo esta INFRAUTILIZADO: tareas como redactar una respuesta
#     corta a partir de datos concretos salen igual de bien en bajo.
#
# El coste no es lineal: de bajo a medio son ~2,5x los tokens, a alto ~6x y a
# maximo ~12x. Por eso subir un escalon tiene que ganarselo.
POR_FASE = {
    # Redactar el guion desde un transcript de 19.000 palabras, con horquilla de
    # palabras, troceado en bloques y adaptacion a varios idiomas. En la matriz
    # es "generacion de contenido", que pide MEDIO. Se resistio la tentacion de
    # poner alto: el historial dice que en bajo termina bien 20 de 20 veces, asi
    # que medio ya es subir un escalon sobre algo que funciona.
    "guion": {"modelo": "sonnet", "esfuerzo": "medium",
              "porque": "generacion de contenido larga con restricciones; en la "
                        "matriz por tarea eso es esfuerzo medio, y el historial "
                        "dice que en bajo ya termina bien 20 de 20 veces"},

    # Leer varias transcripciones enteras de un canal y destilar de ellas COMO
    # escribe. Es el gemelo en texto de 'guia_estilo': una sola llamada, entrada
    # larga, y su salida --las instrucciones de guion-- la heredan todos los
    # videos del canal. Ahi se aplica la misma lectura que alli, con una
    # diferencia que baja un escalon: esto lo lee y lo edita una persona en un
    # campo de texto antes de que escriba nada, asi que un matiz perdido se ve y
    # se corrige, mientras que la guia de estilo se aplica a ciegas en cada
    # imagen.
    "tono": {"modelo": "opus", "esfuerzo": "medium",
             "porque": "destila de varias transcripciones como escribe un canal, "
                       "y eso lo heredan todos sus videos; medio y no alto "
                       "porque lo lee y lo corrige una persona antes de usarlo"},

    # Leer el guion ENTERO y repartirlo en personajes, sitios y tramos. Es una
    # sola llamada por video, con todo el texto delante, y de ella depende que
    # los planos no se repitan: es el sitio donde pagar esfuerzo sale barato.
    # Medio y no alto por lo mismo que el guion: alto se reserva para cuando el
    # historial diga que medio se queda corto.
    # Elegir voz leyendo ciento veinte descripciones y fijar cuatro mandos. Es
    # lectura y criterio, no razonamiento largo, y ademas la propuesta se ve
    # antes de grabar nada: equivocarse no cuesta una toma, cuesta un clic.
    "voz_descrita": {"modelo": "sonnet", "esfuerzo": "low",
                     "porque": "leer un catalogo y elegir; lo que salga se ve "
                               "en los mandos antes de pagar ninguna sintesis"},

    "catalogo_visual": {"modelo": "sonnet", "esfuerzo": "medium",
                        "porque": "una sola llamada por video que decide el "
                                  "reparto y los sitios de todo el montaje; "
                                  "equivocarse aqui sale mucho mas caro que el "
                                  "escalon de esfuerzo"},

    # Mirar una imagen por plano y decidir el grafismo. Es trabajo de juicio
    # visual repetido muchas veces, no de razonamiento largo: medio sobra y el
    # coste manda, porque son 174 imagenes en tandas de 24.
    # Elegir que tramos se cuentan mejor con texto que con dibujo, y ESCRIBIR
    # esa frase. Es lo contrario del de arriba: no mira ninguna imagen, mira el
    # guion entero, y decide poco (tres o cuatro cartelas en treinta planos)
    # pero cada decision es de criterio narrativo y ademas hay que redactarla.
    # Ahi el esfuerzo si se nota, y como son una o dos llamadas por video, sale
    # barato pagarlo.
    # QUE SE VE EN CADA PLANO, con TODOS los planos delante. El trabajo no es
    # describir un plano --eso lo hace cualquiera-- sino que cada uno se
    # distinga del de al lado, y eso es comparar. Una o dos llamadas por video.
    "direccion": {"modelo": "opus", "esfuerzo": "high",
                  "porque": "el trabajo es COMPARAR unos planos con otros para "
                            "que no se repitan, no describir uno: es criterio "
                            "sobre el conjunto, y son una o dos llamadas por "
                            "video, asi que el esfuerzo alto sale barato"},

    # EL PROMPT ENTERO DE CADA PLANO. Lo mismo que `direccion` un escalon mas
    # arriba: alli el agente escribe una linea y el codigo la encaja entre el
    # sitio, el reparto y el tono; aqui escribe el parrafo entero y ademas
    # ELIGE el sitio entre los que su tramo pone a mano.
    "redactor": {"modelo": "opus", "esfuerzo": "high",
                 "porque": "escribe el encargo entero de cada plano y elige su "
                           "sitio entre los del tramo: son mas decisiones por "
                           "plano que dirigirlo, y sigue siendo una sola "
                           "llamada por video"},

    "plan_cartelas": {"modelo": "sonnet", "esfuerzo": "high",
                      "porque": "pocas decisiones por video pero de criterio "
                                "narrativo, y ademas hay que redactar el texto: "
                                "una o dos llamadas, el esfuerzo alto cuesta "
                                "poco y se nota en lo que escribe"},

    # MIRAR las imagenes ya generadas y decir cual esta mal. El unico agente que
    # Reescribir UN bloque de unas 30 palabras aplicando una nota del revisor, y
    # una llamada POR BLOQUE. Es el ejemplo de manual de lo que sale igual de
    # bien en bajo, y ahi la latencia se multiplica por el numero de bloques.
    "revision_audio": {"modelo": "haiku", "esfuerzo": "low",
                       "porque": "reescribir 30 palabras con una nota concreta "
                                 "es de los casos que salen igual de bien en "
                                 "bajo, y se llama una vez por bloque"},

    # Mirar capturas anotadas, decidir que cambiar y EDITAR ficheros del
    # proyecto: flujo agentico con efectos en disco. La matriz apunta a maximo,
    # pero el maximo esta medido como rendimientos decrecientes, y el alto da el
    # 90-95 % por mucho menos.
    "capturas_agente": {"modelo": "sonnet", "esfuerzo": "high",
                        "porque": "es agentico y toca ficheros: la matriz pide "
                                  "maximo, pero alto da el 90-95 % de esa "
                                  "calidad por una fraccion del gasto"},

    # Mirar de 3 a 8 fotogramas y describir el estilo que comparten. Es
    # observacion descriptiva, la categoria que sale bien en bajo.
    "guia_estilo": {"modelo": "opus", "esfuerzo": "high",
                    "porque": "es la UNICA descripcion en palabras del dibujo de "
                              "este video, y la reciben todas las imagenes que se "
                              "generan: los planos y las hojas de personaje. Era "
                              "el escalon mas barato del Estudio -- 23 segundos, "
                              "193 palabras -- para la pieza que decide como se "
                              "ve el video entero, y se notaba: describia bien el "
                              "trazo y se dejaba lo que mas canta, como se "
                              "resuelve una cara. Es UNA llamada por video"},

    # Decidir, plano a plano, si la imagen que ya existe sigue valiendo con la
    # frase nueva. Es comparar dos frases cortas y contestar si o no: en la
    # matriz por tarea es clasificacion, que es la categoria que sale igual de
    # bien en bajo. Y ademas tiene que ser BARATO: si analizar si se puede
    # conservar cuesta mas que rehacerlo, nadie lo usaria.
    "conservacion": {"modelo": "sonnet", "esfuerzo": "low",
                     "porque": "clasificar si dos frases piden la misma imagen "
                               "es de lo que sale igual de bien en bajo, y el "
                               "analisis tiene que costar menos que rehacer"},

    # MIRAR LOS PLANOS GENERADOS Y DECIR CUAL CONTRADICE EL RELATO. Es la fase
    # que mas criterio pide de todas las que miran imagenes: no es «esta bien
    # dibujado», es «esto que se ve contradice lo que se esta contando». Hay que
    # tener el guion entero en la cabeza y ademas resistirse a senalar lo que
    # solo es mejorable, que es lo que convierte una revision util en una lista
    # de la compra de cien reparaciones.
    # REPARTIR EL REPASO EN CAMBIOS. Es la fase con mas consecuencias por
    # decision: elegir mal el ambito de una nota puede volver a grabar la voz de
    # un video entero para arreglar algo que era la musica. Y hay que saber lo
    # que cuesta cada camino, que es lo que separa «arreglalo» de «arreglalo
    # barato».
    "repaso": {"modelo": "opus", "esfuerzo": "high",
               "porque": "elegir el cambio mas barato que resuelve una nota "
                         "pide entender el pipeline entero: equivocarse de "
                         "ambito puede regrabar un video para bajar la musica"},
    # El corrector de UN plano: lee la nota, abre las imagenes del inventario
    # (el plano, sus vecinos, las hojas, las laminas) y decide que se adjunta y
    # con que etiqueta. Es una imagen por llamada y la equivocacion se paga en
    # imagenes: merece el modelo grande (pasos/corrector.py).
    "corrector_imagen": {"modelo": "opus", "esfuerzo": "high",
                         "porque": "entender una nota como «el mismo ordenador "
                                   "que en la escena anterior» exige mirar las "
                                   "imagenes y elegir bien que se adjunta; una "
                                   "eleccion mala se paga en imagenes"},

}


def _orden_modelo(nombre):
    """Cuanto sube un modelo en la escala. Los ids ya van de menos a mas."""
    return MODELOS.index(nombre) if nombre in MODELOS else len(MODELOS)


def _orden_esfuerzo(nombre):
    """Lo mismo para el esfuerzo."""
    return ESFUERZOS.index(nombre) if nombre in ESFUERZOS else 0


def por_defecto_de(fase):
    """Lo que corre en esa fase si nadie elige. Hoy, lo mismo en todas.

    MANDA EL DEFECTO DEL CANAL, no la recomendacion por fase. `POR_FASE` sigue
    entera y no se borra ni una linea: es lo que cada fase NECESITARIA, medido y
    razonado uno a uno, y sigue viajando en 'recomendado' para poder leerlo en la
    pantalla y para el dia que se quiera volver a ella. Pero la decision del
    canal es correr todo en Opus con esfuerzo muy alto, y una tabla que dice una
    cosa mientras el sistema hace otra es la clase de discrepancia que acaba con
    alguien depurando por que su seleccion no se aplica.

    Volver al reparto por fase es devolver aqui `dict(ficha)`.
    """
    ficha = POR_FASE.get(str(fase))
    modelo, esfuerzo = MODELO_POR_DEFECTO, ESFUERZO_POR_DEFECTO
    porque = f"el canal corre todo en {modelo} con esfuerzo {esfuerzo}"
    if ficha:
        # EL DEFECTO ES UN SUELO, NO UN TECHO. «Que todo corra en Opus Extra» es
        # SUBIR lo que iba por debajo, no bajar lo que ya iba por encima: una
        # fase que pide opus/max lo pide porque su fallo se arrastra, y aplicar
        # el defecto a secas la habria rebajado en silencio. Se coge el mayor de
        # los dos en cada eje.
        modelo = max(modelo, ficha["modelo"], key=_orden_modelo)
        esfuerzo = max(esfuerzo, ficha["esfuerzo"], key=_orden_esfuerzo)
        if (modelo, esfuerzo) != (ficha["modelo"], ficha["esfuerzo"]):
            porque += (f"; para esta fase bastaria con {ficha['modelo']}/"
                       f"{ficha['esfuerzo']} ({ficha['porque']})")
        else:
            porque = ficha["porque"]
    return {"modelo": modelo, "esfuerzo": esfuerzo, "porque": porque,
            "recomendado": dict(ficha) if ficha else None}


def catalogo():
    """Lo que la interfaz necesita para pintar el selector, desde una sola fuente.

    La UI ofrecia tres esfuerzos y el backend aceptaba cinco: dos listas que se
    desincronizan solas. Esta es la lista, y la UI la pide.
    """
    return {
        "modelos": [
            {"id": "haiku", "nombre": "Haiku",
             "nota": "el mas rapido y el mas barato; para trabajo mecanico"},
            {"id": "sonnet", "nombre": "Sonnet",
             "nota": "el equilibrio; suficiente para casi todo lo mecanico"},
            {"id": "opus", "nombre": "Opus",
             "nota": "el mas capaz y el mas lento; es el que usa el Estudio por "
                     "defecto, para lo que hay que pensar"},
        ],
        "esfuerzos": [
            {"id": "low", "nombre": "Bajo",
             "nota": "contesta casi sin razonar. Medido: 67 s donde sin el flag "
                     "tardaba 606 s"},
            {"id": "medium", "nombre": "Medio",
             "nota": "razona un poco antes de escribir"},
            {"id": "high", "nombre": "Alto",
             "nota": "piensa de verdad; cuesta varias veces mas tiempo"},
            {"id": "xhigh", "nombre": "Muy alto",
             "nota": "para material dificil, con paciencia; es el que usa el "
                     "Estudio por defecto"},
            {"id": "max", "nombre": "Maximo",
             "nota": "todo lo que sabe dar. Puede tardar mas de diez minutos"},
        ],
        "por_defecto": {"modelo": MODELO_POR_DEFECTO,
                        "esfuerzo": ESFUERZO_POR_DEFECTO},
        "factores": {"modelo": dict(FACTOR_MODELO),
                     "esfuerzo": dict(FACTOR_ESFUERZO)},
        "aviso_factores": ("los factores son ordenes de magnitud para estimar "
                           "antes de tener historial, no medidas"),
    }


def clave_ajuste(modelo, esfuerzo):
    """Identificador estable de una combinacion, para agrupar el historico."""
    return f"{normalizar_modelo(modelo, estricto=False)}|" \
           f"{normalizar_esfuerzo(esfuerzo, estricto=False)}"


# -------------------------------------------------------------------- proceso

def localizar(para="el Estudio"):
    """Ruta del ejecutable del CLI de Claude."""
    for nombre in ("claude.cmd", "claude.exe", "claude"):
        ruta = shutil.which(nombre)
        if ruta:
            return ruta
    raise RuntimeError(
        f"no se encuentra el CLI de claude en el PATH y {para} lo necesita "
        f"(instalalo con 'npm i -g @anthropic-ai/claude-code')")


def entorno(cuenta=None):
    """Entorno del hijo: sin lo que le cambia el razonamiento y sin lo que lo
    sacaria de la suscripcion.

    `cuenta` es una ficha {etiqueta, config_dir} del almacen de claves. Una
    cuenta del CLI NO es una clave: es un LOGIN, y un login del CLI vive en su
    carpeta de configuracion. Por eso cambiar de cuenta es cambiar
    CLAUDE_CONFIG_DIR y nada mas -- meter aqui una ANTHROPIC_API_KEY convertiria
    todo el Estudio en pago por uso sin que nadie se entere, que es justo lo que
    PAGO_POR_USO existe para impedir.
    """
    limpio = dict(os.environ)
    for clave in ENTORNO_FUERA + PAGO_POR_USO:
        limpio.pop(clave, None)
    carpeta = (cuenta or {}).get("config_dir") if isinstance(cuenta, dict) else None
    if carpeta:
        limpio["CLAUDE_CONFIG_DIR"] = carpeta
    return limpio


#: Con que se sale del paso cuando no hay ni almacen: el login por defecto del
#: CLI, que es como iba antes de que existiera el almacen. NUNCA una lista
#: vacia: sin cuentas no habria a quien llamar, y un almacen ilegible no puede
#: dejar al Estudio mudo.
POR_DEFECTO = {"etiqueta": "", "config_dir": ""}


def cuentas():
    """Las cuentas del CLI EN ORDEN, la favorita primero. -> list, nunca vacia

    Se lee del almacen en cada llamada y no al importar: se puede entrar con una
    cuenta nueva desde la pantalla con el servicio levantado, y tiene que entrar
    sin reiniciar nada.

    Solo salen las que tienen sesion hecha (`claves.cuentas_cli`): una cuenta a
    medio loguear es una carpeta con un `.credentials.json` a medias, y correr
    con ella falla de una forma que no se parece a nada.
    """
    try:
        from . import claves                              # noqa: PLC0415
    except ImportError:                                   # pasos/ suelto en sys.path
        try:
            import claves                                 # noqa: PLC0415
        except ImportError:
            return [dict(POR_DEFECTO)]
    try:
        lista = claves.cuentas_cli()
    except Exception:                                     # noqa: BLE001
        return [dict(POR_DEFECTO)]
    return list(lista) if lista else [dict(POR_DEFECTO)]


def nombre_de(cuenta, indice=None):
    """Como se llama una cuenta cuando hay que decirlo por escrito."""
    etiqueta = (cuenta or {}).get("etiqueta") or ""
    if etiqueta:
        return etiqueta
    if indice is None:
        return "la cuenta"
    return "la principal" if indice == 0 else f"la {indice + 1}.a"


def matar_arbol(proceso):
    """Mata el proceso Y sus hijos.

    En Windows el CLI se lanza a traves de claude.cmd, que arranca un node
    aparte: matar solo el padre deja el node vivo consumiendo y esperando, que es
    justo lo que se veia colgando de las llamadas que vencian.
    """
    # esto es limpieza: si taskkill no esta, no puede o falla, lo que importa
    # sigue siendo el error que provoco la limpieza, no el de matar
    try:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proceso.pid)],
                       capture_output=True, timeout=30, **SIN_VENTANA)
    except Exception:  # noqa: BLE001
        pass
    try:
        proceso.kill()
    except Exception:  # noqa: BLE001
        pass


def construir_orden(modelo=MODELO_POR_DEFECTO, esfuerzo=ESFUERZO_POR_DEFECTO,
                    sistema=None, herramientas_vetadas=HERRAMIENTAS_VETADAS,
                    permisos=None, extra=None, herramientas_permitidas=()):
    """La lista de argumentos, en un unico sitio.

    `sistema` tiene que ser UNA sola linea y sin metacaracteres: en Windows el
    CLI se invoca a traves de claude.cmd y un salto de linea dentro de un
    argumento parte el comando.

    `herramientas_permitidas` son las que puede usar SIN PEDIR PERMISO, y hace
    falta para una sola cosa: **`WebFetch` pide permiso POR DOMINIO**. En
    headless eso no es una pregunta, es una negativa -- y no da error: el agente
    anota «bloqueado: sin permiso de acceso a ejemplo.com» y sigue con lo que
    tenga. Medido en la primera tanda de `fuentes` del video largo: de ocho
    fuentes que quiso abrir, SIETE bloqueadas.
    """
    if sistema is not None and ("\n" in sistema or "\r" in sistema):
        raise ValueError("el prompt de sistema tiene que caber en una sola linea: "
                         "en Windows un salto de linea parte la orden de claude.cmd")
    orden = [localizar(), "-p",
             "--model", normalizar_modelo(modelo),
             "--effort", normalizar_esfuerzo(esfuerzo),
             "--output-format", "json",
             "--strict-mcp-config"]
    if herramientas_permitidas:
        orden += ["--allowedTools", ",".join(herramientas_permitidas)]
    if herramientas_vetadas:
        orden += ["--disallowedTools", ",".join(herramientas_vetadas)]
    if sistema:
        orden += ["--append-system-prompt", sistema]
    if permisos:
        orden += ["--permission-mode", permisos]
    orden += list(extra or [])
    return orden


def ejecutar(instruccion, modelo=MODELO_POR_DEFECTO,
             esfuerzo=ESFUERZO_POR_DEFECTO, cwd=None, tiempo_max_s=0,
             base_tiempo_s=420, sistema=None,
             herramientas_vetadas=HERRAMIENTAS_VETADAS, permisos=None,
             extra=None, avance=None, consejos_extra=None, para="la llamada",
             herramientas_permitidas=()):
    """Lanza el CLI en headless y devuelve (texto de la respuesta, sobre JSON).

    La instruccion va SIEMPRE por stdin, nunca como argumento: un transcript de
    20 minutos pasa de 60 KB y no cabe en una linea de comandos de Windows.

    El timeout es finito y mata el arbol de procesos: nunca se deja un paso en
    'ejecutando' para siempre.
    """
    modelo = normalizar_modelo(modelo)
    esfuerzo = normalizar_esfuerzo(esfuerzo)
    lista = cuentas()
    for indice, cuenta in enumerate(lista):
        try:
            return _una_pasada(
                instruccion, modelo, esfuerzo, cwd, tiempo_max_s, base_tiempo_s,
                sistema, herramientas_vetadas, permisos, extra, avance,
                consejos_extra, para, cuenta, herramientas_permitidas)
        except TiempoAgotado:
            # A proposito NO se baja a la siguiente cuenta con un timeout: el
            # techo ya escala con el esfuerzo y volver a intentarlo es volver a
            # esperar media hora para volver a vencer. La clase lo lleva escrito.
            raise
        except RuntimeError as fallo:
            # EL ULTIMO FALLO SUBE TAL CUAL, con su tipo y su texto. No se
            # envuelve en un "las N cuentas fallaron" por dos motivos medidos:
            # `LimiteAgotado` deja de reconocerse como tal (y con el, el aviso
            # en cristiano de que el cupo se renueva el dia X), y la valvula
            # CUPO de las suites casa por TEXTO -- envolverlo pinta FALLA donde
            # tenia que pintar CUPO.
            queda = indice + 1 < len(lista)
            cancelado = avance is not None and getattr(avance, "cancelado", False)
            if not queda or cancelado:
                raise
            print(f"[cli] {nombre_de(cuenta, indice)} fallo "
                  f"({str(fallo)[:120]}); se sigue con "
                  f"{nombre_de(lista[indice + 1], indice + 1)}", flush=True)
    # inalcanzable: `cuentas()` nunca devuelve una lista vacia. Escrito de todas
    # formas porque "inalcanzable" envejece mal.
    raise RuntimeError("no hay ninguna cuenta del CLI de claude configurada")


def _anotar_salud(cuenta, fallo=None, para=""):
    """Apunta en salud_cli como respondio la cuenta. Nunca lanza: es un registro."""
    try:
        try:
            from . import salud_cli                       # noqa: PLC0415
        except ImportError:                               # pasos/ suelto en sys.path
            import salud_cli                              # noqa: PLC0415
        if fallo is None:
            salud_cli.anotar(cuenta, "ok", "", para)
        else:
            estado, mensaje = salud_cli.clasificar(fallo)
            salud_cli.anotar(cuenta, estado, mensaje, para)
    except Exception:                                     # noqa: BLE001
        pass


def _una_pasada(instruccion, modelo, esfuerzo, cwd, tiempo_max_s, base_tiempo_s,
                sistema, herramientas_vetadas, permisos, extra, avance,
                consejos_extra, para, cuenta, herramientas_permitidas=()):
    """UNA llamada al CLI con UNA cuenta, apuntando como respondio.

    Es el UNICO sitio por el que pasa toda llamada al CLI, y por eso la salud de
    la cuenta (pasos/salud_cli.py) se apunta aqui y no en cada paso: un cupo
    agotado a mitad del guion se ve en la burbuja al momento. Una cancelacion
    no se apunta: no dice nada de la cuenta.
    """
    try:
        resultado = _una_pasada_cruda(
            instruccion, modelo, esfuerzo, cwd, tiempo_max_s, base_tiempo_s,
            sistema, herramientas_vetadas, permisos, extra, avance,
            consejos_extra, para, cuenta, herramientas_permitidas)
    except Exception as fallo:
        if not (avance is not None and getattr(avance, "cancelado", False)):
            _anotar_salud(cuenta, fallo, para)
        raise
    _anotar_salud(cuenta, None, para)
    return resultado


def _una_pasada_cruda(instruccion, modelo, esfuerzo, cwd, tiempo_max_s, base_tiempo_s,
                      sistema, herramientas_vetadas, permisos, extra, avance,
                      consejos_extra, para, cuenta, herramientas_permitidas=()):
    """El cuerpo de la llamada, sin el registro de salud."""
    techo = tiempo_max(esfuerzo, base_s=base_tiempo_s, modelo=modelo,
                       pedido_s=tiempo_max_s)
    orden = construir_orden(modelo, esfuerzo, sistema=sistema,
                            herramientas_vetadas=herramientas_vetadas,
                            permisos=permisos, extra=extra,
                            herramientas_permitidas=herramientas_permitidas)
    try:
        proceso = subprocess.Popen(orden, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   cwd=cwd, env=entorno(cuenta), **SIN_VENTANA)
    except OSError as fallo:
        raise RuntimeError(
            f"no se ha podido lanzar el CLI de claude: {fallo}") from fallo

    if avance is not None:
        avance.al_cancelar = lambda: matar_arbol(proceso)

    arranque = time.time()
    try:
        crudo, error_crudo = proceso.communicate(
            (instruccion or "").encode("utf-8"), timeout=techo)
    except subprocess.TimeoutExpired as fallo:
        matar_arbol(proceso)
        consejos = list(consejos_extra or [])
        if esfuerzo != "low":
            consejos.insert(0, f"baja 'esfuerzo' de '{esfuerzo}' a 'low': es lo "
                               f"que mas alarga la espera")
        consejos.append("comprueba que 'claude -p' contesta a mano desde una consola")
        consejos.append(f"sube 'tiempo_max_s' por encima de {techo} si el trabajo "
                        f"es largo de verdad")
        raise TiempoAgotado(
            f"el CLI de claude no ha respondido en {techo} s y se ha cortado "
            f"{para} (se ha matado el proceso y sus hijos). Que probar: "
            + "; ".join(consejos) + ".") from fallo

    segundos = time.time() - arranque
    if avance is not None and getattr(avance, "cancelado", False):
        raise RuntimeError(f"{para} se cancelo mientras esperaba al CLI de claude")

    salida = crudo.decode("utf-8", errors="replace")
    error = error_crudo.decode("utf-8", errors="replace").strip()
    import json
    if proceso.returncode != 0:
        # El CLI sale con codigo 1 y AUN ASI escribe su sobre JSON: el motivo
        # de verdad esta en `result`. Sin mirarlo, un cupo agotado llegaba a la
        # pantalla como 600 caracteres de JSON.
        motivo = ""
        try:
            motivo = str(json.loads(salida).get("result") or "").strip()
        except (ValueError, AttributeError):
            motivo = ""
        limite = limite_de(motivo)
        if limite:
            raise LimiteAgotado(
                f"se ha agotado el cupo de la suscripcion de Claude y no se "
                f"puede hacer {para}: {limite}")
        raise RuntimeError(
            f"el CLI de claude fallo (codigo {proceso.returncode}) despues de "
            f"{int(segundos)} s: {(motivo or error or salida)[:600] or 'sin mensaje'}")
    try:
        sobre = json.loads(salida)
    except ValueError as fallo:
        raise RuntimeError(
            f"el CLI de claude no devolvio JSON: {salida[:600] or '(vacio)'}") from fallo
    if not isinstance(sobre, dict):
        raise RuntimeError(f"respuesta inesperada del CLI de claude: {salida[:600]}")
    if sobre.get("is_error"):
        limite = limite_de(sobre.get("result"))
        if limite:
            raise LimiteAgotado(
                f"se ha agotado el cupo de la suscripcion de Claude y no se "
                f"puede hacer {para}: {limite}")
        raise RuntimeError(
            f"el CLI de claude devolvio error: {str(sobre.get('result'))[:600]}")
    texto = sobre.get("result")
    if not isinstance(texto, str) or not texto.strip():
        raise RuntimeError("el CLI de claude devolvio una respuesta vacia")

    # El sobre del CLI no dice con que esfuerzo se le hablo, y el esfuerzo es la
    # variable que mas mueve el tiempo: si no se estampa aqui, el medidor de
    # coste y el historico se quedan ciegos justo donde importa.
    sobre["_ajuste"] = {"modelo": modelo, "esfuerzo": esfuerzo,
                        "segundos": round(segundos, 2), "tiempo_max_s": techo,
                        "cuenta": (cuenta or {}).get("etiqueta") or "principal"}
    sobre.setdefault("model", modelo)
    return texto, sobre


# =========================================================================
# PEDIR UNA RESPUESTA LARGA: QUE LA ESCRIBA, NO QUE LA DEVUELVA
#
# El limite que obligaba a trocear las listas largas en tandas (`POR_TANDA`) es
# el largo del MENSAJE, no el del contexto ni el del modelo. Medido el
# 22-08-2026 con el mismo encargo por los dos caminos, en sonnet/medium:
#
#     120 items de 60 palabras   en la RESPUESTA  120/120  16.941 car.   88 s
#                                a FICHERO        120/120  14.738 car.   78 s
#     300 items de 60 palabras   en la RESPUESTA   NO PARSEA   790 car.  623 s
#                                a FICHERO        300/300  95.370 car.  578 s
#
# A 300 la respuesta vuelve rota despues de diez minutos y el fichero sale
# entero en menos tiempo. Es lo mismo que hace un agente cuando escribe miles de
# lineas de codigo: no las mete en su mensaje final, las escribe con Write en
# varias pasadas y contesta «hecho».
#
# LO QUE OBLIGA A CUIDAR, porque esto le da la herramienta Write a un agente:
#   - corre en una carpeta TEMPORAL de un solo uso, creada aqui y borrada aqui.
#     Nunca el proyecto ni el repo, que es donde corren las demas fases;
#   - `Bash` se veta siempre, pase lo que pase: no hace falta para escribir un
#     JSON y es la herramienta con la que se sale de una carpeta;
#   - si el fichero no aparece, el error dice QUE ficheros si dejo. Sin eso,
#     «no escribio nada» no distingue entre equivocarse de nombre, de carpeta o
#     no llegar a escribir, y son tres arreglos distintos.
#
# 

#: Como se llama el fichero que se le pide. Uno solo para todas las fases: si
#: cada una eligiera el suyo, el dia que una falle habria que ir a mirar cual
#: era el nombre en esa.
FICHERO_SALIDA = "salida.json"

CIERRE = """

=====================================================================
COMO ENTREGARLO
=====================================================================

ESCRIBE EL RESULTADO EN EL FICHERO `{fichero}` de este directorio, con la forma
exacta que se pide arriba. Escribelo en varias pasadas si te resulta mas comodo
(Write y despues Edit para ir anadiendo); lo unico que importa es que al
terminar sea un JSON valido y completo.

Se escribe a fichero y NO se devuelve en el mensaje a proposito: una lista larga
en la respuesta se corta a la mitad y se pierde entera.

Cuando este escrito, responde solo con: LISTO
"""


def escribiendo(instruccion, modelo=MODELO_POR_DEFECTO,
                esfuerzo=ESFUERZO_POR_DEFECTO, tiempo_max_s=0,
                base_tiempo_s=600, herramientas_vetadas=(), avance=None,
                para="la llamada", que="la respuesta", carpetas=(),
                herramientas_permitidas=()):
    """Como `ejecutar`, pero el agente ESCRIBE su JSON y aqui se lee. -> dict.

    La instruccion NO tiene que decir como entregarlo: se le anade el cierre
    (ver CIERRE), asi que todas las fases piden la entrega igual y el dia que
    esto cambie, cambia en un sitio.

    `herramientas_vetadas` se respeta y se le suma `Bash` siempre.

    `carpetas` son rutas que el agente puede LEER ademas de la suya (--add-dir).
    Sin esto, Read de una ruta fuera del directorio de trabajo pide permiso y en
    headless eso es colgarse. Se pasan las carpetas que EXISTEN: una ruta
    inventada aborta el CLI entero antes de arrancar.
    """
    import json                                                # noqa: PLC0415
    import shutil                                              # noqa: PLC0415
    import tempfile                                            # noqa: PLC0415

    vetadas = tuple(dict.fromkeys(tuple(herramientas_vetadas or ()) + ("Bash",)))
    for imprescindible in ("Write", "Edit", "Read"):
        if imprescindible in vetadas:
            raise ValueError(
                f"'{imprescindible}' no se puede vetar aqui: es como el agente "
                f"entrega la respuesta (ver cli_claude.escribiendo)")
    extra = ["--no-session-persistence"]
    for ruta in dict.fromkeys(str(c) for c in (carpetas or ()) if c):
        if os.path.isdir(ruta):
            extra += ["--add-dir", os.path.abspath(ruta)]
    carpeta = tempfile.mkdtemp(prefix="cli_salida_")
    try:
        ejecutar(instruccion + CIERRE.format(fichero=FICHERO_SALIDA),
                 modelo=modelo, esfuerzo=esfuerzo, cwd=carpeta,
                 tiempo_max_s=tiempo_max_s, base_tiempo_s=base_tiempo_s,
                 herramientas_vetadas=vetadas, permisos="acceptEdits",
                 extra=extra, avance=avance, para=para,
                 herramientas_permitidas=herramientas_permitidas)
        ruta = os.path.join(carpeta, FICHERO_SALIDA)
        if not os.path.exists(ruta):
            hay = sorted(os.listdir(carpeta))[:8]
            raise RuntimeError(
                f"el agente de {para} no ha escrito {FICHERO_SALIDA}"
                + (f" (dejo: {', '.join(hay)})" if hay else " (no dejo nada)"))
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            crudo = fh.read()
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    try:
        return json.loads(crudo)
    except ValueError:
        # con vallas de markdown o una frase delante: se rescata igual que se
        # rescata la respuesta de cualquier otro agente
        try:
            from . import comun                                # noqa: PLC0415
        except ImportError:                          # pasos/ suelto en sys.path
            import comun                                       # noqa: PLC0415
        return comun.extraer_json(crudo, que)
