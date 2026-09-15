"""
Paso 6: assets reutilizables y escenas.

El paso hace dos cosas y las versiona con granularidad distinta, que es
justamente lo que permite marcar en cascada sin generar en cascada:

  asset:<nombre>    hojas de reparto, mapas y cabeceras. Un asset se comparte
                    entre muchas escenas.
  escena:<id>       la imagen de un plano, generada con gpt-image-2 usando como
                    referencias el estilo, las hojas de reparto que aparecen y
                    los dos planos anteriores.

Las escenas salen de segmentar la narracion ya sintetizada (3-6 s, cortando en
puntuacion) y de ASIGNAR visuales a cada segmento: sitio, clase de encuadre,
personajes y zoom. La asignacion es determinista -- misma narracion y mismos
parametros dan el mismo plan -- y respeta dos reglas de montaje: nunca dos
planos seguidos de la misma familia de encuadre (`encuadres.repartir`) y zoom
alternando dentro y fuera.

El encuadre viaja SOLO EN TEXTO, como SHOT TYPE obligatorio del prompt: aqui no
hay geometria 3D que construir ni camaras que repartir (se retiro entero el
23-08-2026).

REGLA DE CASCADA, Y ES DE MARCADO: cada escena declara los assets que usa, y
cuando un asset cambia las escenas que lo usan quedan OBSOLETAS (ver
propagar_dependencias). Se marcan y ahi se paran. Rehacer una cosa rehace ESA
cosa; lo que queda sucio lo acciona una persona desde «Regenerar lo obsoleto
(N)», que dice cuantos son y lo que cuestan antes de que nadie pulse.

Hasta el 23-08 la cascada tambien GENERABA: pedir un asset metia detras, en la
misma pasada, todas las escenas que lo usaban. Arreglar una hoja de personaje se
llevaba las cuarenta y cuatro imagenes del video por delante, sin preguntar y sin
decir lo que costaba. Se retiro (PENDIENTE 30); la de marcado no, porque es la
que hace que la etiqueta signifique algo. Sobre ella se apoya
regenerar_geometria(), que es la via para arreglar un plano cuyo problema esta en
la GEOMETRIA y no en el prompt: mover la camara de un set deja obsoletos todos
sus planos, no solo el que dio el feedback.

El vocabulario visual (sets con sus palabras clave y camaras, reparto,
componentes, lugares, capitulos) viaja en params["catalogo"]: es lo que edita el
humano, no algo cableado aqui.

Como lo llama el orquestador:

    resultado = p6_assets.ejecutar(proyecto, params, avisar)          # o unidades=[...]
    p6_assets.propagar_dependencias(estado, resultado["dependencias"])  # antes de sellar
    estado.completar("assets", resultado["salidas"], resultado["unidades"])

ejecutar devuelve {"salidas", "unidades", "conservadas", "dependencias", "plan",
"todas", "regeneradas"}: "unidades" trae SOLO lo rehecho en esta pasada, que es
lo que debe sellarse, y "dependencias" el mapa escena -> assets usados.
"""
import difflib
import hashlib
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cartelas  # noqa: E402
import corrector  # noqa: E402
import cta  # noqa: E402
import encuadres  # noqa: E402
import estadisticas  # noqa: E402
import medios  # noqa: E402
import moodboard  # noqa: E402
# p2_brief por su tabla de nombres de idioma (la del generador de imagen va en
# ingles) y p4_voz por idioma_de_salida, que es el accesor oficial del idioma
# del video. Los dos son de pasos anteriores a este, asi que no hay circulo.
import p2_brief  # noqa: E402
import p4_voz  # noqa: E402

from nucleo.proyecto import ahora  # noqa: E402

#: Por debajo de esta duracion un plano no admite rotulo. No es una manía: un
#: rotulo necesita entrar, leerse y salir, y en menos de tres segundos eso son
#: tres cosas a la vez encima de un plano que ademas ya se esta yendo.
MIN_S_ROTULOS = 3.0

#: Rotulos por plano. UNO.
#:
#: Empezo en dos, con la idea de que si no se pisaban cabian los dos. Y se
#: pisaron: una cifra a tamano de titular encima de un callout con su linea, y
#: la cifra saliendose ademas por abajo del cuadro. Se puede resolver colocando
#: mejor, apagando el primero cuando entra el segundo y midiendo solapes -- o se
#: puede no tener el problema. Uno por plano es una regla que se cumple sola:
#: el plano dura cuatro segundos y hay 174 planos; lo que no cabe aqui cabe en
#: el siguiente.
MAX_ROTULOS = 1


PARAMS_POR_DEFECTO = {
    "calidad": "low",                  # low | medium | high  (coste por imagen)
    "estilo": {
        # VACIO a proposito. Aqui habia una frase describiendo un dibujo concreto
        # -- «simple rounded shapes, muted earthy palette, bean-shaped characters»--
        # y era el relleno silencioso de todos los videos del Estudio: la pantalla
        # jubilo este campo hace tiempo y ya nadie lo escribe, asi que TODA hoja de
        # personaje se pedia con esa descripcion en vez de con la del video
        # elegido. Salian redondeadas y grises pidieras lo que pidieras.
        # Lo que describe este video son las referencias y la guia escrita.
        "prompt": "",
        "referencias": [],             # frames del video de referencia
    },
    "min_s": 3.0,
    "max_s": 6.0,
    # Duracion por debajo de la cual un plano NO lleva rotulos. Un rotulo tiene
    # que entrar, leerse y salir; en menos de esto son tres cosas a la vez sobre
    # un plano que ademas ya se esta yendo.
    "min_s_rotulos": MIN_S_ROTULOS,
    # QUE PLANOS SON CARTELA no se declara aqui, y es a proposito: va POR
    # UNIDAD, en `unidades["escena:S013"]["cartela"]`.
    #
    # Estuvo aqui, como `plan_cartelas`, y era un error caro. Todo lo que no es
    # el bloque `unidades` entra en la FIRMA GLOBAL del paso (ver
    # nucleo/estado.py:_params_globales), asi que guardar el plan de cartelas
    # dejaba obsoletos los cuarenta y nueve planos y todos los assets: decidir
    # una cartela pedia regenerar el video entero. Por unidad, convertir S013 en
    # cartela ensucia S013 y nada mas, que es exactamente lo que ha cambiado.
    #
    # Lo decide un agente leyendo el guion (cartelas.proponer) y lo aprueba una
    # persona; a partir de ahi es un dato. QUE PLANTILLAS puede usar vive en los
    # params de rotulos, junto al resto del grafismo.
    "semilla": 7,
    "motor_imagen": "openai",          # openai | adoptar
    "imagenes_previas": [],            # carpetas de arte ya aprobado
    # Fotogramas REALES del video de referencia, aprobados a mano, para que el
    # dibujo de una persona o un sitio concreto se parezca al original. Vacio en
    # los proyectos que no lo usen: no cambia nada de lo de siempre.
    "referencias_reales": [],
    "banco_imagenes": os.path.join(medios.BANCO, "imagenes"),


    # Aqui habia un "concurrencia": 4 que no leia ninguna linea del paso. Un
    # mando que no hace nada es peor que no tenerlo: la proxima vez que salte un
    # 429, alguien lo bajaria y descartaria la hipotesis correcta. Lo que manda
    # de verdad sobre cuantas imagenes van a la vez es 'cadenas' (con su tope
    # MAX_CADENAS), y por debajo el cubo de imagen.py.
    # Cadenas de generacion a la vez. 0 = una por sitio, que es el paralelismo
    # que admite el grafo: dentro de un sitio los planos van en fila -- cada uno
    # se apoya en el anterior de SU sitio-- y entre sitios no se deben nada.
    # Ver _generar_escenas para por que las cadenas son por SET y no por plano.
    "cadenas": 0,
    "catalogo": {},                    # sets, reparto, componentes y lugares
}

TAMANO = (1536, 1024)

#: Cuantas referencias adjuntas a una nota entran en el prompt de un plano. Dos
#: es lo que cabe decir con imagenes sobre UN cambio; con cuatro, el prompt deja
#: de tener un encargo y pasa a tener un moodboard -- y cada una son ~700 tokens.
MAX_ADJUNTAS = 2

NUMEROS = ("un", "una", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete",
           "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince",
           "veinte", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta",
           "ochenta", "noventa", "cien", "ciento", "cientos", "mil", "miles",
           "millon", "millones", "mil millones", "billones")

UNIDADES = ("toneladas", "tonelada", "kilos", "kilogramos", "kilometros",
            "millas", "dolares", "euros", "pesos", "millones", "anos", "meses",
            "dias", "horas", "personas", "hombres", "barcos", "contenedores")


def describir(params):
    """Frase corta con lo que hara el paso con estos parametros."""
    p = _con_defectos(params)
    catalogo = p["catalogo"] or {}
    motor = ("adoptando arte ya existente" if p["motor_imagen"] == "adoptar"
             else f"generando con gpt-image-2 en calidad {p['calidad']}")
    encuadre = ("asigna a cada plano su clase de encuadre en texto "
                "(caben diagramas y pantallas)")
    return (f"Corta la narracion en planos de {p['min_s']:.0f}-{p['max_s']:.0f} s, "
            f"{encuadre} y {len(catalogo.get('reparto') or {})} fichas de "
            f"reparto, y produce una imagen por plano {motor}.")


def _con_defectos(params):
    p = dict(PARAMS_POR_DEFECTO)
    p.update(params or {})
    estilo = dict(PARAMS_POR_DEFECTO["estilo"])
    estilo.update(p.get("estilo") or {})
    p["estilo"] = estilo
    return p


# --------------------------------------------------------------- entradas

def _palabras_narracion(proyecto, params):
    """Marcas de palabra de la voz ya sintetizada, en orden, y donde cambia de bloque.

    Los muros -- los indices de palabra en que arranca un bloque del guion -- se
    devuelven aparte porque el corte en planos no puede cruzarlos: un bloque es
    la unidad que escribe el redactor, la que se traduce, la que se reescribe
    desde la revision de audio y la que la voz separa con un silencio de un
    segundo. Aplanando sin mas, esa frontera se perdia y un plano podia narrar el
    final de un bloque y el principio del siguiente.

    DE DONDE SALEN LOS MUROS, y hay dos caminos porque hay dos formatos de
    `audio_meta.json`:

      * el de AHORA (`p4_voz`): una lista PLANA de marcas mas `bloques` con el
        `t_in` y el `t_out` de cada uno. Su `palabras` es un RECUENTO, no una
        lista, asi que los muros se calculan por TIEMPO -- la primera marca que
        cae dentro de cada bloque.
      * el de las tomas ANTERIORES: `escenas`, cada una con su propia lista de
        marcas dentro. Ahi el muro es el cambio de escena.

    Y el segundo se leia primero, con lo que el primero caia en un
    `pares = [(p, 0) ...]` que ponia TODAS las palabras en el bloque cero: los
    muros salian vacios y la frontera que este docstring promete no se
    respetaba en ningun video de hoy. No daba error -- daba planos que cruzan
    de un bloque al siguiente de vez en cuando.
    """
    ruta = params.get("audio_meta") or medios.salida_de(
        proyecto, "voz", claves=("meta", "audio_meta", "marcas"),
        patrones=(r"audio_meta\.json", r".*_meta\.json"))
    if not ruta or not os.path.exists(ruta):
        raise RuntimeError("el paso voz no ha dejado audio_meta.json: no hay "
                           "marcas de palabra con las que cortar los planos")
    meta = medios.leer_json(ruta, {})
    pares = []
    for indice, bloque in enumerate(meta.get("escenas") or []):
        for palabra in bloque.get("palabras") or []:
            if isinstance(palabra, dict):
                pares.append((palabra, indice))
    if not pares:
        sueltas = sorted((p for p in (meta.get("palabras") or [])
                          if isinstance(p, dict)),
                         key=lambda p: p.get("s") or 0.0)
        tramos = tramos_de_bloque(meta)
        pares = [(p, _bloque_en(p, tramos)) for p in sueltas]
    pares.sort(key=lambda par: par[0]["s"])
    palabras = [par[0] for par in pares]
    muros = [i for i in range(1, len(pares)) if pares[i][1] != pares[i - 1][1]]
    return palabras, muros, ruta, meta


def _bloque_en(palabra, tramos):
    """En que bloque cae esta marca. -> indice, o -1 si en ninguno.

    Por el ARRANQUE de la palabra y no por su solape: una marca dura decimas y
    esta entera dentro de su bloque, asi que el arranque no tiene ambiguedad y
    ademas es estable si el `t_out` del bloque viene redondeado.
    """
    inicio = float(palabra.get("s") or 0.0)
    for indice, (t_in, t_out, _bid) in enumerate(tramos):
        if t_in <= inicio <= t_out:
            return indice
    return -1


def _catalogo_de(params, proyecto):
    """Catalogo visual: lo declara el guion y aqui solo se completa."""
    catalogo = dict(params.get("catalogo") or {})
    if not catalogo:
        guion = medios.salida_de(proyecto, "guion", claves=("catalogo", "guion", "plan"),
                                patrones=(r"catalogo\.json", r"guion\.json", r"plan.*\.json"))
        datos = medios.leer_json(guion, {}) if guion else {}
        catalogo = datos.get("catalogo") or datos.get("visuales") or {}
    catalogo.setdefault("sets", {})
    catalogo.setdefault("reparto", {})
    catalogo.setdefault("componentes", {})
    catalogo.setdefault("lugares", {})
    catalogo.setdefault("capitulos", {})
    catalogo.setdefault("beats", [])
    return catalogo














# ----------------------------------------------------------- planificacion

def _puntuar(texto, palabras, por_defecto=()):
    """Puntuacion de un candidato: suma de los pesos de sus palabras clave."""
    if not palabras:
        palabras = por_defecto
    if isinstance(palabras, dict):
        pares = palabras.items()
    else:
        pares = [(p, 1.0) for p in palabras]
    return sum(float(peso) for palabra, peso in pares if medios.contiene(texto, palabra))




def _elegir_componente(texto, catalogo, mejor_set):
    """Un componente vectorial (mapa, grafico) gana solo si lo pide el texto."""
    mejor, punto = None, 0.0
    for nombre, spec in catalogo["componentes"].items():
        valor = _puntuar(texto, spec.get("palabras"), (nombre,))
        if valor > punto:
            mejor, punto = nombre, valor
    if mejor and punto >= mejor_set + 0.5:
        return mejor
    return None


def _elegir_set(texto, catalogo, previo, consecutivos, semilla, sid):
    """Set del plano: palabras clave, con continuidad y con tope de repeticion."""
    puntuados = []
    for nombre, spec in catalogo["sets"].items():
        valor = _puntuar(texto, spec.get("palabras"), (nombre.replace("_", " "),))
        if nombre == previo:
            if valor > 0:
                valor += 0.7          # continuidad: no saltar de set por un roce
            # tres planos seguidos en el mismo set cansan; a partir de ahi pesa
            valor -= 1.2 * max(0, consecutivos - 2)
        puntuados.append((valor, -medios.desempatar(semilla, sid, nombre), nombre))
    if not puntuados:
        return None, 0.0
    puntuados.sort(reverse=True)
    valor, _, nombre = puntuados[0]
    if valor <= 0:
        # sin senal en el texto se mantiene el set anterior, salvo que ya lleve
        # demasiados planos: entonces el plano se resuelve sin set (plano abierto)
        if previo and consecutivos < 3:
            return previo, 0.0
        return None, 0.0
    return nombre, valor


















def _elegir_personajes(texto, catalogo, tiene_set, maximo=2):
    elegidos = []
    for nombre, spec in sorted(catalogo["reparto"].items()):
        claves = spec.get("palabras") or [nombre]
        if _puntuar(texto, claves) > 0:
            elegidos.append(nombre)
    if not tiene_set:
        return elegidos[:1]
    return elegidos[:maximo]


#: Cita entrecomillada dentro de la narracion. Comillas de las tres familias
#: porque el guion sale de un modelo y mezcla las que le da la gana.
CITA = re.compile(r'[\"“«]\s*([^\"”»]{12,120})\s*[\"”»]')


def _capa_vectorial(texto, crudo, sid, set_nombre, catalogo, indice,
                    entra_en_set=False, presentar=(), palabras=(), duracion=None,
                    minimo_s=MIN_S_ROTULOS):
    """Que lleva la capa de este plano. Hoy: la cabecera de CAPITULO, y ya.

    ESTO ERAN CIENTO TREINTA Y OCHO LINEAS que proponian rotulos -- cabecera de
    sitio, presentacion de una persona, cita entrecomillada, cifra, fecha y el
    callout con linea guia hasta un elemento-- y decidian cual de los cuatro
    motivos ganaba, porque solo cabia uno por plano.

    Los rotulos se retiraron enteros el 22-08. El motivo estaba
    a la vista: de los siete arquetipos solo quedaban dos vigentes y los dos
    iban al pie del cuadro, o sea que toda la maquinaria de colocacion existia
    para elegir entre dos cosas que acababan en el mismo sitio. Lo que se dice
    encima de un plano ahora son SUBTITULOS (`pasos/subtitulos.py`), que no se
    proponen: son la narracion, y ya esta escrita.

    El CAPITULO se queda porque no es un rotulo: es una portada a cuadro
    completo, con su propio SVG, que ocupa el plano entero.

    La firma se conserva entera a proposito. La llama `planificar` con nueve
    argumentos y recortarla ahora seria tocar el sitio mas delicado del paso por
    una limpieza cosmetica; los argumentos que ya no se miran cuestan una linea
    de documentacion y no un fallo.
    """
    capitulo = (catalogo.get("capitulos") or {}).get(str(sid))         or (catalogo.get("capitulos") or {}).get(str(indice))
    if not capitulo:
        return []
    ficha = {"tipo": "capitulo"}
    ficha.update(capitulo if isinstance(capitulo, dict) else {"texto": capitulo})
    return [ficha]


def _indice_de(palabras, termino, idioma=None):
    """En que palabra del plano empieza ese termino. (indice, cuantas) o None.

    LO HACE `medios`, y eso es la mitad del arreglo. Emparejar un texto escrito
    con lo que dice la voz es la misma pregunta aqui (un rotulo entra cuando se
    dice lo que rotula) y en `cartelas.alinear` (una cartela se escribe al ritmo
    al que la voz la dice), y estaba escrita dos veces con la misma heuristica
    del `in`. Con dos copias, la que se quedara vieja fallaria en silencio: la
    de aqui ya no sabria leer «30M» sobre «thirty million» y un rotulo de cifra
    entraria al empezar el plano en vez de con su golpe.
    """
    return medios.indice_de(palabras, termino, idioma)


def _beat_de(texto, catalogo, instante=None):
    """Indicacion editorial del guion para este trozo de narracion.

    Manda el RANGO, y las palabras clave son el respaldo.

    Un beat con 'desde'/'hasta' cubre un tramo de bloques del guion, y aqui llega
    ya convertido a segundos (ver _tramos_de_beats). Emparejar por palabras sobre
    un fragmento de cuatro segundos no es leer el guion en contexto: es adivinar
    con la frase suelta, y por eso una escena de infancia acababa heredando el
    garaje del plano anterior. Las palabras siguen valiendo para los catalogos
    escritos a mano, que no traen rango.
    """
    if instante is not None:
        for beat in catalogo.get("beats") or []:
            tramo = beat.get("_tramo")
            if tramo and tramo[0] <= instante < tramo[1]:
                return beat
    for beat in catalogo.get("beats") or []:
        if beat.get("_tramo"):
            continue          # ya se ha probado por rango: no colar por palabras
        if _puntuar(texto, beat.get("palabras") or []) > 0:
            return beat
    return None


# ------------------------------------------------- identidad de cada plano
#
# El id de un plano ('S042') es POSICIONAL: sale del orden en que quedaron los
# cortes. Con eso solo, alargar una frase a mitad del guion desplaza todos los
# cortes siguientes, S042 pasa a narrar otra cosa y TODO lo que venia detras
# queda obsoleto aunque no haya cambiado ni una palabra.
#
# La identidad de verdad de un plano es DE QUE TROZO DE GUION SALE. Eso es lo
# que se guarda en 'origen', y es lo que permite reconocer un plano entre dos
# versiones del guion, conservarlo, y limitar lo que hay que rehacer a lo que de
# verdad ha cambiado.

def tramos_de_bloque(meta):
    """[(t_in, t_out, id)] de cada bloque de la locucion, en segundos.

    Se aceptan los dos formatos de audio_meta que hay por ahi: el de ahora
    ('bloques' con t_in/t_out) y el de las tomas anteriores ('escenas' con
    t_primera_palabra). Un proyecto viejo no puede quedarse sin identidad de
    plano solo porque su meta se escribiera con otras claves.
    """
    tramos = []
    for bloque in ((meta or {}).get("bloques")
                   or (meta or {}).get("escenas") or []):
        if not isinstance(bloque, dict):
            continue
        bid = str(bloque.get("id") or "").strip().upper()
        if not bid:
            continue
        palabras = bloque.get("palabras") or []
        palabras = palabras if isinstance(palabras, list) else []
        inicio = bloque.get("t_in")
        if inicio is None:
            inicio = bloque.get("t_primera_palabra")
        if inicio is None and palabras:
            inicio = palabras[0].get("s")
        fin = bloque.get("t_out")
        if fin is None:
            fin = bloque.get("t_ultima_palabra")
        if fin is None and palabras:
            fin = palabras[-1].get("e")
        if inicio is None:
            continue
        tramos.append((float(inicio), float(fin if fin is not None else inicio),
                       bid))
    return tramos


def _marcar_origen(escenas, meta):
    """De que bloque del guion sale cada plano y en que posicion dentro de el."""
    bloques = tramos_de_bloque(meta)
    cuenta = {}
    for escena in escenas:
        inicio = float(escena.get("t_in") or 0.0)
        fin = float(escena.get("t_out") or inicio)
        elegido, mejor = "", 0.0
        for t_in, t_out, bid in bloques:
            solape = min(fin, t_out) - max(inicio, t_in)
            if solape > mejor:
                elegido, mejor = bid, solape
        if not elegido:
            # sin marcas de bloque (o un plano fuera de todas) la identidad se
            # queda en el propio texto: peor, pero nunca inventada
            escena["origen"] = {"bloque": "", "indice": 0,
                                "clave": medios.huella(escena.get("narracion"))}
            continue
        indice = cuenta.get(elegido, 0)
        cuenta[elegido] = indice + 1
        escena["origen"] = {"bloque": elegido, "indice": indice,
                            "clave": f"{elegido}#{indice}"}
    return escenas


def _texto_clave(escena):
    return medios.normalizar_texto(escena.get("narracion") or "")


def _emparejar_con_previo(escenas, anteriores):
    """Que plano de antes es cada plano de ahora. {id nuevo: escena anterior}.

    Dos vueltas, y en este orden:

      1. mismo bloque y MISMA narracion. Es el mismo plano sin discusion, aunque
         haya cambiado de sitio en el video porque lo de delante se alargo.
      2. mismo bloque y misma posicion dentro de el. Aqui la frase ha cambiado,
         asi que el plano NO se da por bueno: solo se le reconoce la identidad,
         para poder decir despues "este es el que hay que rehacer" en vez de
         "estos 174 son nuevos".
    """
    anteriores = list(anteriores or [])
    libres = {}
    for anterior in anteriores:
        bid = str((anterior.get("origen") or {}).get("bloque") or "")
        libres.setdefault(bid, []).append(anterior)

    pareja, gastados = {}, set()

    def coger(escena, candidatos, encaja):
        for anterior in candidatos:
            if id(anterior) in gastados or not encaja(anterior):
                continue
            pareja[escena["id"]] = anterior
            gastados.add(id(anterior))
            return True
        return False

    # 1. mismo bloque y MISMA narracion: el mismo plano sin discusion.
    for escena in escenas:
        bid = str((escena.get("origen") or {}).get("bloque") or "")
        texto = _texto_clave(escena)
        coger(escena, libres.get(bid, []),
              lambda a: _texto_clave(a) == texto)
    # 2. misma narracion en cualquier bloque. Cubre dos casos de verdad: un
    #    plano que se mueve de bloque porque el guion se reorganizo, y los
    #    planes hechos ANTES de que existiera 'origen', que no traen bloque
    #    ninguno y sin esta vuelta se renombrarian todos.
    for escena in escenas:
        if escena["id"] in pareja:
            continue
        texto = _texto_clave(escena)
        coger(escena, anteriores, lambda a: _texto_clave(a) == texto)
    # 3. mismo bloque y misma posicion dentro de el. Aqui la frase ha cambiado,
    #    asi que el plano NO se da por bueno: solo se le reconoce la identidad,
    #    para poder decir despues "este es el que hay que rehacer" en vez de
    #    "estos 174 son nuevos".
    for escena in escenas:
        if escena["id"] in pareja:
            continue
        origen = escena.get("origen") or {}
        bid = str(origen.get("bloque") or "")
        if not bid:
            continue
        coger(escena, libres.get(bid, []),
              lambda a: (a.get("origen") or {}).get("indice") == origen.get("indice"))
    return pareja


def _heredar_ids(escenas, previo):
    """Ids SIEMPRE en orden de video (S001, S002...); lo que se hereda del plan
    anterior es la IDENTIDAD del contenido, no el numero.

    Antes el plano que narraba lo mismo recuperaba su id viejo, y tras recortar
    la rejilla iba en orden de video con los ids saltando (S001, S002, S027...):
    de un vistazo parecia desordenada y hacia falta un numero de posicion junto
    al nombre. La proteccion real contra volver a pagar nunca fue el id: es la
    cache de imagenes POR CONTENIDO (mismo prompt y mismas referencias, mismo
    fichero) mas la herencia de camara/encuadre, que mantiene el prompt igual.
    Asi que el id vuelve a ser lo que parece -- la posicion -- y la herencia
    viaja en `heredados` (clave: id NUEVO -> plano anterior); quien la necesita
    (las camaras de por_set, la conservacion, el informe) la lee de ahi. El
    plano ademas apunta su rastro en `hereda_de` cuando el numero cambio.
    """
    for indice, escena in enumerate(escenas, start=1):
        escena["id"] = f"S{indice:03d}"
    anteriores = (previo or {}).get("escenas") or []
    if not anteriores:
        return {"heredados": {}, "conservados": [], "nuevos": [e["id"] for e in escenas],
                "retirados": []}
    pareja = _emparejar_con_previo(escenas, anteriores)

    heredados, conservados, nuevos = {}, [], []
    emparejados = set()
    for escena in escenas:
        anterior = pareja.get(escena["id"])
        if anterior and anterior.get("id"):
            heredados[escena["id"]] = anterior
            emparejados.add(id(anterior))
            if anterior["id"] != escena["id"]:
                escena["hereda_de"] = anterior["id"]
            if _texto_clave(anterior) == _texto_clave(escena):
                conservados.append(escena["id"])
        else:
            nuevos.append(escena["id"])
    # retirado = contenido que ya no existe en el plan nuevo, no un numero que
    # cambio de sitio: un S027 que ahora se llama S003 no se ha retirado
    retirados = sorted(a["id"] for a in anteriores
                       if a.get("id") and id(a) not in emparejados)
    return {"heredados": heredados, "conservados": conservados,
            "nuevos": nuevos, "retirados": retirados}


def _tramos_de_beats(catalogo, meta):
    """Convierte 'desde'/'hasta' (ids de bloque) en un tramo de segundos.

    Los planos no son los bloques: salen de las marcas de palabra y hay 174 para
    88 bloques. Lo unico que comparten es el reloj, asi que el rango de bloques
    se traduce a tiempo una sola vez y cada plano se ubica por su instante.
    """
    bloques = {}
    for bloque in (meta or {}).get("bloques") or []:
        bid = str(bloque.get("id") or "").strip().upper()
        if bid:
            bloques[bid] = (float(bloque.get("t_in") or 0.0),
                            float(bloque.get("t_out") or 0.0))
    if not bloques:
        return
    for beat in catalogo.get("beats") or []:
        desde = bloques.get(str(beat.get("desde") or "").strip().upper())
        hasta = bloques.get(str(beat.get("hasta") or "").strip().upper())
        if not desde:
            continue
        beat["_tramo"] = (desde[0], (hasta or desde)[1])
    catalogo["_capitulos_en_segundos"] = {
        bloques[bid][0]: ficha
        for bid, ficha in (catalogo.get("capitulos") or {}).items()
        if bid in bloques}


def _capitulos_por_escena(catalogo, escenas):
    """Pasa los capitulos de id de BLOQUE a id de PLANO.

    El catalogo los marca por bloque, que es como se lee un guion; la capa
    vectorial los pide por plano, que es lo que se dibuja. La cabecera abre en
    el primer plano que empieza en ese punto o despues.
    """
    porsegundo = catalogo.pop("_capitulos_en_segundos", None)
    if not porsegundo:
        return
    porescena = {}
    for instante, ficha in sorted(porsegundo.items()):
        for escena in escenas:
            if float(escena.get("t_out") or 0) > instante:
                porescena[escena["id"]] = ficha
                break
    catalogo["capitulos"] = porescena




def _ajustes_unidad(params, uid):
    """Lo que el revisor ha anotado sobre una unidad concreta del paso."""
    bloque = (params.get("unidades") or {}).get(uid)
    return bloque if isinstance(bloque, dict) else {}


def _texto_feedback(valor):
    """El feedback de una unidad como UN texto para el prompt.

    El que escribe la pantalla es una cadena; el historial que dejan las
    correcciones de camara es una lista de fichas con 'texto'. Los dos tienen
    que acabar DENTRO del prompt: el feedback movia la firma (se pagaba una
    imagen nueva) pero el prompt era identico, asi que salia una variacion de
    lo mismo y la nota del revisor se ignoraba entera.
    """
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, list):
        trozos = [str(v.get("texto") or "").strip() for v in valor
                  if isinstance(v, dict)]
        return " | ".join(t for t in trozos if t)
    return ""


def _ultima_nota(valor):
    """La ULTIMA nota del historial de una unidad, o {}.

    Manda la última y no todas porque el historial se acumula entre vueltas y la
    imagen que hay en disco YA lleva aplicadas las anteriores: la única que
    habla de lo que se está mirando ahora es la de arriba del todo.
    """
    if isinstance(valor, list):
        for nota in reversed(valor):
            if isinstance(nota, dict):
                return nota
    return {}


def _corrector_activo(p):
    """Si este proyecto usa el corrector. Se apaga con `corrector: "no"`."""
    return str((p or {}).get("corrector") or "agente").strip().lower() != "no"


def _inventario_para_nota(escena, plan, dirs, p, trabajo, notas, proyecto):
    """Todo lo que el corrector puede adjuntar, con rutas reales. -> [fichas]

    Cada ficha es {"ruta", "que", "clase"}. Entra: la imagen actual del plano,
    sus versiones anteriores, los planos vecinos (VECINOS a cada lado), todas
    las hojas del reparto, las piezas, las laminas del estilo y lo que el
    revisor adjunto a la nota. No entra nada que no exista en disco.
    """
    sid = escena["id"]
    fichas = []

    def meter(ruta, que, clase, papel, **atributos):
        # `papel` es el mismo vocabulario que usa la primera generacion
        # (frase_de_referencia): asi el generador oye lo mismo de una hoja o
        # de un plano vecino venga de donde venga
        ruta = os.path.abspath(str(ruta or ""))
        if os.path.isfile(ruta) and all(f["ruta"] != ruta for f in fichas):
            fichas.append(dict(atributos, ruta=ruta, que=que, clase=clase,
                               papel=papel))

    meter(os.path.join(dirs["escenas"], f"{sid}.png"),
          f"LA IMAGEN ACTUAL del plano {sid}, la que el revisor ha rechazado",
          "actual", "rechazada")
    # versiones anteriores de ESTE plano (otras versiones del paso)
    if proyecto is not None:
        try:
            raiz_paso = os.path.dirname(os.path.abspath(trabajo))
            for nombre in sorted(os.listdir(raiz_paso)):
                carpeta = os.path.join(raiz_paso, nombre, "escenas")
                if (nombre.startswith("v") and os.path.isdir(carpeta)
                        and os.path.abspath(os.path.join(raiz_paso, nombre))
                        != os.path.abspath(trabajo)):
                    meter(os.path.join(carpeta, f"{sid}.png"),
                          f"una version ANTERIOR del plano {sid} ({nombre})",
                          "anterior", "adjunta")
        except OSError:
            pass
    # vecinos, con su descripcion
    orden = [e["id"] for e in plan.get("escenas") or []]
    por_id = {e["id"]: e for e in plan.get("escenas") or []}
    if sid in orden:
        i = orden.index(sid)
        for j in range(max(0, i - corrector.VECINOS), min(len(orden), i + corrector.VECINOS + 1)):
            if j == i:
                continue
            vecino = por_id[orden[j]]
            donde = "ANTERIOR" if j < i else "SIGUIENTE"
            meter(os.path.join(dirs["escenas"], f"{vecino['id']}.png"),
                  f"el plano {vecino['id']}, {abs(j - i)} {donde} a este; sitio "
                  f"'{vecino.get('set') or '-'}'; personajes "
                  f"{', '.join(vecino.get('personajes') or []) or 'nadie'}; "
                  f"dice: {' '.join(str(vecino.get('narracion') or '').split())[:160]}",
                  "vecino", "continuidad",
                  mismo_set=bool(vecino.get("set")
                                 and vecino.get("set") == escena.get("set")),
                  desde=str(vecino.get("encuadre") or "")[:120])
    # todas las hojas del reparto
    reparto = (p.get("catalogo") or {}).get("reparto") or {}
    try:
        for nombre in sorted(os.listdir(dirs["reparto"])):
            if nombre.endswith(".png"):
                ident = nombre[:-4]
                ficha = reparto.get(ident) or {}
                meter(os.path.join(dirs["reparto"], nombre),
                      f"la HOJA DE PERSONAJE de '{ident}'"
                      + f": {' '.join(str(ficha.get('descripcion') or '').split())[:200]}",
                      "reparto", "reparto", nombre=ident,
                      tapada=tapa_la_cara(ficha.get("descripcion")))
    except OSError:
        pass
    # las piezas (mapas, graficos)
    try:
        for nombre in sorted(os.listdir(dirs["componentes"])):
            if nombre.endswith(".png"):
                meter(os.path.join(dirs["componentes"], nombre),
                      f"la PIEZA '{nombre[:-4]}' (grafico o mapa del video)",
                      "pieza", "adjunta")
    except (OSError, KeyError):
        pass
    # las laminas del estilo, para quien necesite «personajes genericos del
    # estilo» o un sitio en su dibujo
    for indice, ruta in enumerate(
            medios.reubicar_todas(p["estilo"].get("referencias"))[:8], start=1):
        meter(ruta, f"la LAMINA {indice} del estilo grafico (se adjunta siempre "
                    f"la que toca; esta solo si quieres nombrarla ademas)",
              "estilo", "adjunta")
    # lo que adjunto el revisor
    for adjunto in _adjuntos_de_la_nota(escena, dirs, p, notas):
        if adjunto["papel"] == "adjunta":
            meter(adjunto["ruta"], "una imagen que ADJUNTO EL REVISOR con la nota",
                  "adjunta", "adjunta")
    return fichas


def _corregir_con_agente(escena, plan, dirs, p, trabajo, notas, proyecto,
                         nota_texto, avisar):
    """Llama al corrector con el inventario de este plano. -> dict|None"""
    try:
        inventario = _inventario_para_nota(escena, plan, dirs, p, trabajo, notas,
                                           proyecto)
        bloque = ""
        bid = str((escena.get("origen") or {}).get("bloque") or "")
        for b in (plan.get("bloques") or []):
            if isinstance(b, dict) and str(b.get("id")) == bid:
                bloque = str(b.get("texto") or "")
        titulo = str(plan.get("titulo") or "")
        resultado = corrector.preparar(
            nota_texto, escena, p.get("catalogo") or {},
            "\n".join("  " + l for l in guia_escrita(p["estilo"])),
            regla_de_especie(p["estilo"]), inventario, titulo=titulo,
            bloque=bloque, cwd=getattr(proyecto, "raiz", None),
            proyecto_id=getattr(proyecto, "id", None),
            ajuste=p.get("ajuste_corrector"), avisar=avisar)
    except Exception as fallo:                                   # noqa: BLE001
        resultado = {"error": f"{type(fallo).__name__}: {fallo}"[:300]}
    if resultado and resultado.get("error"):
        print(f"[assets] corrector de {escena['id']}: {resultado['error']}; "
              f"se sigue por el camino de siempre", flush=True)
    return resultado


def _referencias_de_la_nota(escena, dirs, p, cache, notas=None):
    """Lo que la NOTA del revisor pone delante del generador. -> [referencias]

    Dos cosas, y las dos faltaban (PENDIENTE 39):

    1. LA IMAGEN RECHAZADA, y sólo si la nota es un RETOQUE. `_bloque_feedback`
       ya le dice al generador que la descripción de arriba es la que produjo la
       imagen rechazada, pero eso preserva la DESCRIPCIÓN, no los píxeles: en un
       cambio localizado («cámbiale la mano por un guante») la composición
       derivaba entera. Con la imagen delante, no.

       Y sólo en el retoque: en un cambio sustitutivo («esto tenía que ser un
       móvil, no un monolito») una imagen delante se lee como «edita esto» y
       vuelve a salir lo mismo con un cambio pequeño. Ese caso está medido
       (S018 del video largo) y es justo el que `_bloque_feedback` documenta.
       Quién lo clasifica: el ENRUTADOR, que es el único que ve la nota, el
       plano y las imágenes a la vez. Ver `repaso.ALCANCES`.

    2. LA REFERENCIA QUE ADJUNTÓ QUIEN ESCRIBIÓ LA NOTA. La abría el enrutador
       para entender la nota y ahí se quedaba.

       Sólo las del REPASO, no las de las capturas anotadas: una captura es el
       fotograma con trazos pintados encima, y ese camino ya tiene decidido cómo
       se le habla al generador -- se traducen a palabras («la zona superior
       derecha», `capturas.describir_trazos`) porque el generador no entiende un
       canvas. Meterle además el PNG con los trazos invitaría a dibujarlos.

    Lo que cuesta, dicho: cada imagen de referencia son ~700 tokens (~0,006 $)
    por corrección. Sólo se pagan en el plano que se corrige, y sólo cuando la
    nota lo pide.
    """
    adjuntos = _adjuntos_de_la_nota(escena, dirs, p, notas)
    if not adjuntos:
        return []
    imagen = medios.motor("imagen_openai/imagen.py")
    return [{"papel": a["papel"], "ruta": imagen.normalizar(a["ruta"], cache)}
            for a in adjuntos]


def _adjuntos_de_la_nota(escena, dirs, p, notas=None):
    """QUE se adjunta, con sus rutas de disco. -> [{"papel", "ruta"}]

    La decisión va aparte de `_referencias_de_la_nota` para poder probarla sin
    cargar el motor de imagen ni normalizar un PNG: lo que hay que comprobar
    aquí es que el `alcance` que escribe el repaso lo LEE alguien, y eso es esta
    función.
    """
    ajustes = _ajustes_unidad(p, f"escena:{escena['id']}")
    crudo = ajustes.get("feedback")
    nota = _ultima_nota(crudo)
    texto = _texto_feedback(crudo)
    if not nota and texto:
        # el camino rapido manda solo el texto: la nota entera esta en el repaso
        nota = _nota_del_repaso_para(escena["id"], texto, notas) or {"texto": texto}
    if not nota:
        return []
    # EL ALCANCE, DECIDIDO SIEMPRE. Lo pone el enrutador cuando la nota pasa por
    # el; cuando no ha pasado (el boton de rehacer, el feedback directo) se
    # decide aqui: si la nota nombra a un personaje que el plano no lleva, lo
    # que se pide es OTRA escena y la imagen rechazada delante solo la
    # perpetuaria (medido en S018 del video largo); si no, es un retoque y la
    # imagen delante es lo que mantiene la composicion.
    alcance = str(nota.get("alcance") or ajustes.get("alcance") or "").strip()
    if alcance not in ("retoque", "sustituye"):
        alcance = ("sustituye" if _reparto_en_la_nota(texto, p, escena)
                   else "retoque")
    salida = []
    if alcance == "retoque":
        previa = os.path.join(dirs["escenas"], f"{escena['id']}.png")
        if os.path.exists(previa):
            salida.append({"papel": "rechazada", "ruta": previa})
    if str(nota.get("de") or "") == "repaso":
        for ruta in (nota.get("imagenes") or [])[:MAX_ADJUNTAS]:
            if ruta and os.path.exists(str(ruta)):
                salida.append({"papel": "adjunta", "ruta": str(ruta)})
    return salida


def _medio_de(escena):
    """El punto medio del plano, que es por donde se ubica en el reloj.

    El medio y no el arranque: el plano entra un pelin antes que su frase (ver
    `_encadenar`) y por el borde caeria en el tramo anterior justo en los
    cambios de beat, que es donde mas duele.
    """
    return (float((escena or {}).get("t_in") or 0.0)
            + float((escena or {}).get("t_out") or 0.0)) / 2.0


def _beats_por_escena(escenas, catalogo):
    """Un beat para cada plano, REPARTIENDO los que caen en el mismo tramo.

    EL FALLO QUE CIERRA (07-09-2026), y se tragaba un tercio del catalogo.

    Un beat declara su tramo con ids de BLOQUE del guion, y un bloque es un
    parrafo: cabe mas de una idea visual dentro. `catalogo_visual` lo sabe y
    escribe varios beats para el mismo bloque -- en el video del oro, el bloque
    B001 («Hay una crisis que no sale en los titulares. No hay bolsas cayendo,
    no hay bancos rescatados, no hay colas en la puerta de una oficina. Y aun
    asi, cada euro que ganas vale menos.») trae CUATRO, uno por frase, cada uno
    con su sitio: el quiosco, el parque de la bolsa en calma, la acera del banco
    sin cola y el monedero.

    Y `_beat_de` devolvia SIEMPRE el primero, porque los cuatro se traducen al
    mismo tramo de segundos. Los otros tres eran codigo muerto. Medido sobre ese
    video: 41 bloques de 95 traen mas de un beat, 51 beats de 146 (el 35 %) no
    los podia devolver nadie, y 50 de los 145 sitios del catalogo no se usaban
    NUNCA. De ahi salen los cuatro planos seguidos de quiosco donde el catalogo
    habia pedido cuatro sitios distintos.

    POR PLANOS Y NO POR TIEMPO. La tentacion es partir el tramo del bloque en
    rodajas iguales de reloj; en B001 sale bien por casualidad (cuatro frases
    parecidas). Pero el reloj incluye los silencios y las frases no duran lo
    mismo, asi que una rodaja puede caer entera dentro de un plano y dejar un
    beat sin nadie. Repartiendo los PLANOS que compiten por los mismos beats,
    cada beat cae en un plano de verdad y ninguno se parte.

    Con menos planos que beats se REPARTE igual (el primero, el del medio, el
    ultimo) en vez de coger los primeros: si el bloque cuenta un arco, es mejor
    recorrerlo que quedarse en su principio.

    Lo que no toca: un catalogo escrito a mano, sin rangos, sigue emparejando
    por palabras en `_beat_de`.
    """
    todos = [b for b in (catalogo.get("beats") or []) if isinstance(b, dict)]
    candidatos = []
    for escena in escenas:
        medio = _medio_de(escena)
        candidatos.append([b for b in todos
                           if b.get("_tramo")
                           and b["_tramo"][0] <= medio < b["_tramo"][1]])
    # los beats son dicts (no se pueden meter en un set): se comparan por
    # identidad, que ademas es lo que hace falta -- dos planos van juntos si
    # compiten por LOS MISMOS beats, no por unos iguales
    claves = [tuple(id(b) for b in lista) for lista in candidatos]
    salida = [None] * len(escenas)
    i = 0
    while i < len(escenas):
        if not claves[i]:
            i += 1
            continue
        j = i
        while j < len(escenas) and claves[j] == claves[i]:
            j += 1
        lista, cuantos = candidatos[i], j - i
        for pos in range(cuantos):
            salida[i + pos] = lista[min(len(lista) - 1,
                                        pos * len(lista) // cuantos)]
        i = j
    return salida


def opciones_de_tramo(proyecto, params, escenas):
    """Que sitios y que acciones pone su tramo a mano en cada plano. -> [[beat]]

    Es lo que necesita `redactor` para poder ELEGIR: hasta ahora el codigo
    decidia el sitio de un plano y el agente solo escribia lo que pasa dentro.
    Con los beats de su bloque delante --que en un parrafo son dos, tres o
    cuatro-- el agente ve las opciones que el director de arte escribio y coge
    la que va con la frase de ESE plano.

    Se recalcula el catalogo con sus tramos en segundos porque el plan guardado
    no los lleva: `_tramos_de_beats` anota sobre la copia viva del catalogo, y
    esa copia muere con la planificacion.
    """
    p = _con_defectos(params)
    catalogo = _catalogo_de(p, proyecto)
    _, _, _, meta = _palabras_narracion(proyecto, p)
    _tramos_de_beats(catalogo, meta)
    todos = [b for b in (catalogo.get("beats") or []) if isinstance(b, dict)]
    opciones = []
    for escena in escenas or []:
        medio = _medio_de(escena)
        opciones.append([b for b in todos
                         if b.get("_tramo")
                         and b["_tramo"][0] <= medio < b["_tramo"][1]])
    return opciones, catalogo


def _asignar_sets(escenas, catalogo, p):
    """Set, componente y reparto de cada plano. No depende de las camaras."""
    beats = []
    set_previo, consecutivos = None, 0
    repartidos = _beats_por_escena(escenas, catalogo)
    for indice, escena in enumerate(escenas):
        texto = medios.normalizar_texto(escena["narracion"])
        beat = repartidos[indice]
        if beat is None:
            # sin rango que lo cubra: queda el emparejamiento por palabras, que
            # es como funcionan los catalogos escritos a mano
            beat = _beat_de(texto, catalogo, _medio_de(escena))
        beat = beat or {}
        set_nombre, punto = _elegir_set(texto, catalogo, set_previo, consecutivos,
                                        p["semilla"], escena["id"])
        componente = beat.get("componente") or _elegir_componente(texto, catalogo, punto)
        if beat.get("set"):
            set_nombre, componente = beat["set"], None
        if componente:
            set_nombre = None
        personajes = beat.get("personajes")
        if personajes is None:
            # en un componente vectorial (mapa, grafico) no hay donde poner a
            # nadie: el reparto solo aplica a los planos dibujados
            personajes = ([] if componente else
                          _elegir_personajes(texto, catalogo, bool(set_nombre)))
        escena["set"] = set_nombre
        escena["componente"] = componente
        escena["personajes"] = personajes
        beats.append(beat)

        if set_nombre and set_nombre == set_previo:
            consecutivos += 1
        else:
            consecutivos = 1 if set_nombre else 0
        set_previo = set_nombre
    return beats








def _asignar_cartas(escenas, p):
    """Que CLASE de plano es cada uno: aereo, detalle macro, diagrama, pantalla.

    La carta es lo que produce ritmo: pedirle a un modelo de imagen «haz un
    plano distinto» devuelve el mismo plano medio con otras palabras, y
    decidirlo antes -- este es un aereo, el siguiente un detalle macro -- no.
    Viaja SOLO EN TEXTO: entra en el prompt como SHOT TYPE obligatorio y es lo
    unico que fija el cuadro. El reparto y sus dos reglas viven en
    `encuadres.repartir`.

    Se puede forzar por plano desde la pantalla: `unidades['escena:S007'].carta`.
    Una decision tomada mirando el video manda sobre cualquier reparto.
    """
    forzadas = {e["id"]: str(_ajustes_unidad(p, f"escena:{e['id']}").get("carta")
                             or "") for e in escenas}
    cartas = encuadres.repartir(escenas, semilla=p.get("semilla", 0),
                                forzadas={k: v for k, v in forzadas.items() if v})
    for escena in escenas:
        carta = cartas.get(escena["id"])
        if not carta:
            continue
        escena["carta"] = carta["id"]
        escena["encuadre"] = carta["encuadre"]
        if carta.get("abstracta"):
            # lo lee el prompt: un diagrama no se rueda en «la sede del banco»
            escena["abstracta"] = True
    return cartas


def _repartir_zoom(escenas):
    """El zoom de cada plano, alternado. Se juega en el CORTE, sobre la imagen.

    No necesita ninguna caja ni ningun ancla sobre el que centrarse: el
    movimiento trabaja sobre el cuadro entero.
    """
    segmentar = medios.motor("guion/segmentar.py")
    for indice, escena in enumerate(escenas):
        escena["zoom"] = segmentar.alternar_zoom(indice, None)
    return _informe_cartas(escenas)


def _informe_cartas(escenas):
    """Que ha salido del reparto de cartas.

    'planos_repetidos' cuenta planos SEGUIDOS de la misma familia, que es la
    unica forma de repeticion que queda cuando cada plano trae su propia clase
    de encuadre. Sale a cero salvo que alguien fuerce cartas a mano, y por eso
    vale como aviso: si sube, es que las decisiones manuales se estan comiendo
    el ritmo.
    """
    cartas = [e.get("carta") for e in escenas if e.get("carta")]
    familias = [(encuadres.POR_ID.get(c) or {}).get("familia") for c in cartas]
    seguidas = [escenas[i]["id"] for i in range(1, len(familias))
                if familias[i] and familias[i] == familias[i - 1]]
    return {
        "planos": len(escenas),
        "cartas_distintas": len(set(cartas)),
        "reparto_cartas": {c: cartas.count(c) for c in sorted(set(cartas))},
        "familias_seguidas": seguidas,
        "planos_repetidos": len(seguidas),
        # Las clases de plano que existen, para que la pantalla pueda ofrecer
        # otra sin tener que conocer la escalera. Va en el plan y no en un
        # endpoint aparte porque la pantalla ya lee el plan entero: un viaje
        # menos y, sobre todo, imposible que se desincronicen.
        "escalera": [{"id": c["id"], "nombre": c["nombre"]}
                     for c in encuadres.ESCALERA],
    }


def planificar(proyecto, params, inventario=None, replantear=False,
               previo=None):
    """Corta la narracion y asigna visuales. No genera nada: solo decide.

    Los ids salen SIEMPRE en orden de video (S001, S002...): ver _heredar_ids.
    Por defecto se mira el plan anterior para heredar la IDENTIDAD del contenido
    (camara en por_set, conservacion, informe), que es lo que permite que
    cambiar una frase no obligue a rehacer el video entero. Con 'replantear' se
    corta de cero sin mirar nada -- hoy solo cambia que no se hereda ni se
    informa de conservacion; la numeracion es identica.
    """
    p = _con_defectos(params)
    catalogo = _catalogo_de(p, proyecto)
    palabras, muros, ruta_meta, meta = _palabras_narracion(proyecto, p)
    segmentar = medios.motor("guion/segmentar.py")
    formato = p2_brief.comun.ficha_formato(p4_voz.formato_de_salida(proyecto))

    # el corte se decide con las duraciones DE PANTALLA, asi que necesita saber
    # como se reparten los silencios: es lo mismo que aplica _encadenar despues
    adelanto, cola = p.get("adelanto", 0.25), p.get("cola", 0.45)
    # El reparto va en un dict PROPIO y no en el global del motor: el motor se
    # carga una vez por proceso y lo comparten todos los proyectos, asi que dos
    # planificaciones a la vez se pisarian y el informe de una describiria el
    # corte de la otra.
    reparto_corte = {}
    # DE QUE PLAN SE HEREDA. Normalmente del activo, que es el de la pasada
    # anterior. Se puede pasar otro para RE-CORTAR desde una version concreta:
    # si un corte se movio solo --lo que arreglo `heredar`, pero despues de que
    # ya hubiera pasado-- la forma de volver al bueno es heredar de la version
    # que lo tenia, no cortar de cero, que daria un tercer reparto distinto.
    if previo is None:
        previo = {} if replantear else plan_actual(proyecto)
    # EL CORTE DE ANTES MANDA MIENTRAS EL GUION SEA EL DE ANTES.
    #
    # El reparto optimo se calcula con las MARCAS DE PALABRA, y una voz
    # sintetizada dos veces no da las mismas: el 31-08 la misma frase movio sus
    # marcas ocho centesimas y el corte paso de 222 planos a 217, con el texto
    # identico palabra por palabra. Nadie pidio ese cambio, y detras se llevo
    # las 225 imagenes, que van por el numero del plano.
    #
    # No es que el optimizador se equivoque: con otras duraciones, otro reparto
    # es de verdad mejor. Es que no habia que volver a preguntarselo. Asi que
    # primero se intenta poner el corte que ya estaba sobre los tiempos nuevos,
    # y solo si el texto ya no se reconoce -- se ha reescrito de verdad -- se
    # corta de cero.
    # SE HEREDA DEL CORTE CRUDO, NO DEL PLAN. `plan["escenas"]` es el corte YA
    # procesado: `_fundir_cartelas` junta planos y la firma se pega. Heredar de
    # ahi y volver a pasar el mismo molino funde lo ya
    # fundido, y el plan encoge en CADA pasada -- medido: 225, 221, 219, 215.
    # Asi que el corte tal y como salio del segmentador viaja aparte.
    #
    # Un plan de antes del 31-08 no lo trae, y entonces no se hereda: sin saber
    # donde cortaba de verdad, heredar del resultado es exactamente el fallo de
    # arriba.
    crudo = [{"narracion": x} for x in ((previo or {}).get("corte") or [])]
    segmentos = segmentar.heredar(palabras, crudo,
                                  adelanto=adelanto, cola=cola,
                                  minimo=p["min_s"], maximo=p["max_s"],
                                  reparto=reparto_corte)
    if not segmentos:
        segmentos = segmentar.segmentar(palabras, p["min_s"], p["max_s"],
                                        adelanto=adelanto, cola=cola, muros=muros,
                                        reparto=reparto_corte)
    escenas = [dict(e) for e in segmentar.construir_escenas(segmentos)]
    # EL CORTE, TAL CUAL SALIO. Se guarda antes de que nadie lo toque: es lo
    # unico contra lo que la proxima pasada puede reconocer donde cortaba.
    corte_crudo = [e.get("narracion") or "" for e in escenas]
    _marcar_origen(escenas, meta)
    reparto = _heredar_ids(escenas, previo)
    # Los beats vienen por rango de BLOQUES y los planos van por reloj: se
    # traduce una vez, antes de repartir nada.
    _tramos_de_beats(catalogo, meta)
    _capitulos_por_escena(catalogo, escenas)
    beats = _asignar_sets(escenas, catalogo, p)
    # La carta manda en texto y no hay nada que construir: el generador compone
    # libre sobre el SHOT TYPE. Se reparte sobre las escenas YA ordenadas: la
    # regla de no repetir familia mira a los vecinos, no a un plano suelto.
    _asignar_cartas(escenas, p)
    camaras = _repartir_zoom(escenas)

    # Las duraciones definitivas ANTES de decidir los rotulos: un plano de menos
    # de tres segundos no admite ninguno, y eso solo se sabe una vez repartidos
    # los silencios entre planos.
    _encadenar(escenas, meta.get("duracion"), adelanto, cola, segmentar)
    # Y el informe DESPUES de encadenar, o describe unas duraciones que se
    # tiran en la linea siguiente.
    informe = segmentar.informe(escenas, p["min_s"], p["max_s"],
                                reparto=reparto_corte)
    informe["camaras"] = camaras
    # Las marcas de palabra viajan con el plano: son lo que permite que un
    # rotulo entre cuando se dice lo que rotula y no al empezar el plano. Van
    # ANTES de repartir las cartelas porque ahora las cartelas tambien las usan:
    # se escriben al ritmo al que se dice lo que ponen, y de ahi sale si a una
    # le da tiempo en su plano o tiene que seguir en el siguiente.
    for escena, segmento in zip(escenas, segmentos):
        escena["marcas"] = [[round(float(w["s"]), 3), round(float(w["e"]), 3)]
                            for w in segmento[2]]
    informe["cartelas"] = _marcar_cartelas(escenas, beats, p)

    # QUE SE VE EN CADA PLANO, si alguien lo ha dirigido. Va ANTES de escribir
    # los prompts porque es una linea mas del prompt (ver `_con_direccion`), y
    # se lee de los params POR UNIDAD igual que la cartela: escribir la
    # direccion de un plano ensucia ese plano y no los cuarenta y nueve.
    #
    # Opcional: sin direccion, el prompt sale exactamente como salia.
    #
    # Y `redactado` es lo mismo un escalon mas arriba: el parrafo entero escrito
    # por `redactor`. Si esta, manda sobre todo lo demas (ver `_prompt_visual`);
    # si no esta, no cambia nada. Los dos viven en los params POR UNIDAD, que es
    # lo que hace que escribir uno ensucie SU plano y no los 299.
    for escena in escenas:
        ajustes = _ajustes_unidad(p, f"escena:{escena['id']}")
        linea = " ".join(str(ajustes.get("direccion") or "").split())
        if linea:
            escena["direccion"] = linea
        else:
            escena.pop("direccion", None)
        parrafo = " ".join(str(ajustes.get("redactado") or "").split())
        if parrafo:
            escena["redactado"] = parrafo
            # EL SITIO LO DECLARA EL REDACTOR, y hay que hacerle caso aqui: sin
            # esto la continuidad y las cadenas seguirian agrupando por el set
            # que calculo el codigo, o sea que a un plano que se fue a otro
            # sitio se le adjuntaria la foto del sitio que dejo.
            #
            # Se distingue «no lo declaro» (la clave no esta: se queda el del
            # codigo) de «declaro que no usa ninguno» (cadena vacia: se ha
            # inventado su sitio y no le toca continuidad de nadie).
            sitio = ajustes.get("redactado_set")
            if sitio is not None:
                sitio = str(sitio).strip()
                if sitio and sitio in (catalogo.get("sets") or {}):
                    escena["set"] = sitio
                    escena["componente"] = None
                elif not sitio:
                    escena["set"] = None
        else:
            escena.pop("redactado", None)

    # Lo que hace falta para rotular con criterio y no en cada plano: en que
    # plano se ENTRA en un sitio, y en cual sale alguien por primera vez.
    set_anterior, presentados = None, set()
    for indice, (escena, beat) in enumerate(zip(escenas, beats)):
        if escena.get("sigue_a"):
            # La segunda mitad de un plano que dura mas (una cartela sobre
            # imagen estirada). No tiene prompt ni rotulos propios: los hereda
            # de su primera mitad, y `_seguir_plano` ya se los ha puesto. Sin
            # esto se le escribiria un prompt y se pagaria la imagen que
            # precisamente no hay que pagar.
            continue
        if _sin_imagen(escena):
            # Ni prompt ni rotulos: la cartela ES el rotulo, y ponerle encima
            # una cabecera de sitio seria rotular un sitio en el que no pasa
            # nada. Tampoco toca `set_anterior`: el sitio del plano de antes
            # sigue siendo el sitio del de despues, con la cartela en medio.
            escena["luz"] = ""
            escena["prompt"] = ""
            escena["capa_vectorial"] = []
            continue
        texto = medios.normalizar_texto(escena["narracion"])
        escena["luz"] = (beat.get("luz")
                         or (catalogo["sets"].get(escena["set"]) or {}).get("luz")
                         or catalogo.get("luz_por_defecto", ""))
        # LA ACCION DEL TRAMO, ESCRITA EN EL PLANO. Ya viajaba dentro del
        # prompt, pero disuelta: quien lo lee despues --el agente que dirige los
        # planos-- no puede sacarla de ahi. Escrita aparte, se puede decir «esto
        # lo comparte con sus vecinos, escribe lo OTRO». Ver pasos/direccion.py.
        if beat.get("accion"):
            escena["accion"] = str(beat["accion"]).strip()
        if beat.get("tono"):
            escena["tono"] = str(beat["tono"]).strip()
        escena["prompt"] = _prompt_visual(escena, beat, catalogo)
        entra = bool(escena["set"]) and escena["set"] != set_anterior
        nuevos = [q for q in (escena.get("personajes") or []) if q not in presentados]
        presentados.update(nuevos)
        escena["capa_vectorial"] = _capa_vectorial(
            texto, escena["narracion"], escena["id"], escena["set"],
            catalogo, indice,
            entra_en_set=entra, presentar=nuevos,
            palabras=(escena.get("narracion") or "").split(),
            duracion=escena.get("duracion"),
            minimo_s=p.get("min_s_rotulos", MIN_S_ROTULOS))
        set_anterior = escena["set"] or set_anterior

    # `estirados` desaparecio con los rotulos: estiraba un
    # plano cuando a una cabecera de sitio no le daba tiempo a leerse, y ya no
    # hay cabeceras de sitio. Lo que sigue estirando --y ahora fundiendo-- son
    # las CARTELAS, y eso lo descuenta `_marcar_cartelas` mas arriba.
    informe["estirados"] = []

    plan = {
        "proyecto": proyecto.id,
        # Con que reglas se corto este plan. Ver MOTOR_PLAN: no entra en ninguna
        # firma, se enseña.
        "motor": MOTOR_PLAN,
        # LA SEMILLA DEL VIDEO, y va en el plan porque la leen pasos de mas
        # abajo: de ella salen la transicion de cada corte, el efecto de sonido
        # que suena y el grano del fondo de una cartela.
        #
        # Se deriva del id del proyecto y no es la de los params tal cual: la de
        # los params vale 7 en todos los videos, asi que con ella el reparto
        # «aleatorio» daba exactamente la misma tirada en todos -- los ids de
        # plano tambien son S001..N en todos--, y dos videos seguidos del canal
        # llevarian la misma transicion en el mismo sitio.
        "semilla": medios.desempatar(p.get("semilla", 0), proyecto.id),
        # EL IDIOMA DEL VIDEO, y va en el plan por lo mismo que la semilla: lo
        # leen pasos de mas abajo. De el depende en que lengua rotula el
        # generador lo que dibuja dentro de la imagen (un diagrama, un cartel,
        # una portada). Sale del BRIEF, que es quien lo sabe de primera mano.
        #
        # NO se deduce de la narracion con `medios.idioma_de`: ese solo
        # distingue es/en, asi que un canal en portugues, frances, italiano o
        # aleman saldria etiquetado «es» y todos los rotulos irian en el idioma
        # equivocado -- con el agravante de que ahora el prompt lo AFIRMA. Si no
        # hay idioma, se queda vacio y la regla del motor no decide nada.
        "idioma": p4_voz.idioma_de_salida(proyecto),
        "fps": p.get("fps", 30),
        # EL FORMATO, del brief: de aqui sale el cuadro del MP4
        # y el lienzo de cada imagen, y de aqui lo leen p7 y p8. Un plan
        # anterior a esto no lo trae y es horizontal.
        "formato": formato["id"],
        "resolucion": list(formato["salida"]),
        "generacion": list(formato["generacion"]),
        "estilo": p["estilo"],
        "narracion": {"meta": ruta_meta, "duracion": meta.get("duracion")},
        "duracion_total": round(escenas[-1]["t_out"], 3) if escenas else 0.0,
        "escenas": escenas,
        # el corte antes de fundir cartelas y de pegar la firma: de aqui
        # hereda la pasada siguiente (ver `segmentar.heredar`)
        "corte": corte_crudo,
        "informe": informe,
    }
    plan["assets"] = _assets_necesarios(plan, catalogo, p)
    plan["dependencias"] = {f"escena:{e['id']}": _assets_de_escena(e)
                            for e in escenas}
    # Que ha sobrevivido del plan anterior. Va en el plan a proposito: es lo que
    # la interfaz pinta y lo que decide que se rehace, y una cifra sin
    # procedencia no vale -- aqui esta dicho de donde sale cada plano.
    #
    # Y LOS PLANOS QUE SE HA COMIDO EL FUNDIDO CUENTAN COMO RETIRADOS. Es la
    # contrapartida de fundir y no se penso al hacerlo: `_fundir_cartelas` borra
    # escenas del PLAN --S002 pasa a ser parte de S001-- pero sus UNIDADES
    # seguian declaradas en el estado. Nadie las produce (p7 recorre
    # `plan["escenas"]`), asi que su firma no se sella nunca: quedan obsoletas
    # para siempre y ademas son IMPOSIBLES DE ACCIONAR -- «Regenerar lo obsoleto
    # (5)» se pulsa, corre, y siguen siendo cinco. Un contador que no baja nunca
    # entrena a no mirar el contador, y ese contador es el que sostiene toda la
    # nomenclatura de dos verbos.
    #
    # Se declaran aqui, en el plan, y las retira quien tiene el estado en la
    # mano (app.py, con `retirar_unidades`): los pasos no tocan el estado, y no
    # hace falta que lo hagan porque el canal ya existe -- es el mismo por el
    # que viajan los planos que deja fuera un recorte.
    absorbidos = sorted({f["absorbido"] for f in
                         (informe.get("cartelas") or {}).get("seguidas") or []
                         if f.get("absorbido")})
    # EL PLAN ES LA VERDAD DE QUE PLANOS HAY: un id que sigue en el plan no se
    # retira aunque venga en las dos listas. Los ids son POSICIONALES, asi que
    # un S003 del plan anterior que ya no existe y un S003 del plan de ahora son
    # la misma cadena y cosas distintas; sin este filtro se des-declararia una
    # unidad viva y su firma se recalcularia como si no hubiera corrido nunca.
    vivos = {e["id"] for e in escenas}
    plan["conservacion"] = {
        "conservados": reparto["conservados"],
        "nuevos": reparto["nuevos"],
        "retirados": sorted((set(reparto["retirados"]) | set(absorbidos)) - vivos),
        "absorbidos": absorbidos,
        "reasignados": sorted(set(reparto["heredados"]) - set(reparto["conservados"])),
        "habia_plan_previo": bool((previo or {}).get("escenas")),
        "replanteado": bool(replantear),
    }
    return plan


def _encadenar(escenas, duracion_audio=None, adelanto=0.25, cola=0.45,
               segmentar=None):
    """Estira cada plano hasta el siguiente para que no queden huecos.

    Los segmentos salen de las marcas de palabra, asi que entre frase y frase
    hay pausas que no pertenecen a ningun plano. Si esos silencios no se
    reparten, el video acaba durando menos que la voz y la imagen se adelanta
    un poco mas en cada corte. El plano entra ademas un pelin antes que su
    frase: primero se ve, despues se oye.

    Cuanto antes lo decide el motor de corte (adelanto_de), y no esta aqui a
    proposito: es la misma cuenta con la que el optimizador puntuo las
    duraciones, y si las dos se separan vuelve a decidir sobre segundos que
    nadie ve.
    """
    if not escenas:
        return escenas
    segmentar = segmentar or medios.motor("guion/segmentar.py")
    escenas[0]["t_in"] = round(max(0.0, escenas[0]["t_in"] - adelanto), 3)
    for anterior, siguiente in zip(escenas, escenas[1:]):
        hueco = float(siguiente["t_in"]) - float(anterior["t_out"])
        entra = segmentar.adelanto_de(hueco, anterior.get("corte"), adelanto)
        # El suelo es el FINAL de la ultima palabra del plano anterior, que es
        # exactamente lo que topa `entradas_de` en el segmentador. Aqui ponia
        # `anterior["t_in"] + 0.4` --el arranque del plano anterior mas 0,4 s,
        # que con planos de segundos no muerde nunca-- y esa era la unica
        # diferencia entre las dos cuentas: el optimizador aceptaba un plano de
        # 3,935 s con el maximo en 4 y en pantalla salia de 4,183. O sea que el
        # tope se seguia pasando DESPUES de haberse declarado respetado.
        # `anterior["t_out"]` aqui todavia es el original: la linea de abajo lo
        # sobrescribe despues.
        siguiente["t_in"] = round(max(float(anterior["t_out"]),
                                      siguiente["t_in"] - entra), 3)
        anterior["t_out"] = siguiente["t_in"]
    final = escenas[-1]["t_out"] + cola
    if duracion_audio:
        final = max(final, float(duracion_audio))
    escenas[-1]["t_out"] = round(final, 3)
    for escena in escenas:
        escena["duracion"] = round(escena["t_out"] - escena["t_in"], 3)
    return escenas


def _guion_del_proyecto(proyecto):
    """El guion.json de la version activa, o {}. No falla si no hay."""
    ruta = medios.salida_de(proyecto, "guion", claves=("guion",),
                            patrones=(r"guion\.json",))
    return (medios.leer_json(ruta, {}) or {}) if ruta else {}


def _cartelas_por_texto(p):
    """Las cartelas decididas, indexadas por el texto contra el que se
    decidieron. -> {texto: ficha}

    Solo entran las que traen `ancla`. Una ficha sin ancla no se puede colocar
    por contenido, y meterla aqui con el texto de su numero de hoy seria
    inventarle un sitio.
    """
    indice = {}
    for ajustes in (p.get("unidades") or {}).values():
        ficha = (ajustes or {}).get("cartela")
        if not isinstance(ficha, dict) or not ficha.get("plantilla"):
            continue
        ancla = _texto_clave({"narracion": ficha.get("ancla")})
        if ancla:
            indice[ancla] = ficha
    return indice


def _marcar_cartelas(escenas, beats, p):
    """Marca los planos que son CARTELA en vez de imagen. Devuelve el resumen.

    La decision ya esta tomada y guardada, POR UNIDAD
    (`unidades["escena:S013"]["cartela"]`). Aqui solo se aplica sobre el plan de
    ahora, respetando el suelo de separacion y el techo (`cartelas.repartir`).
    Se vuelve a repartir en vez de guardarlo repartido porque el plan cambia: si
    se replantea el corte, un plano que estaba a seis de la cartela anterior
    puede quedar a dos, y esa comprobacion tiene que correr sobre las escenas de
    AHORA.

    Un plano que se hace cartela pierde su prompt y sus assets: no se genera.
    """
    por_texto = _cartelas_por_texto(p)
    plan = {}
    for indice, escena in enumerate(escenas):
        # POR LO QUE DICE EL PLANO, Y SI NO POR SU NUMERO.
        #
        # La decision se guarda por unidad (`unidades["escena:S087"]`) y el
        # numero de un plano es su POSICION: se reparte de nuevo con cada corte.
        # Las siete cartelas de este video se decidieron sobre el plan v1 y
        # llevaban 67 versiones sin moverse, asi que «TIPO DE INTERES REAL»
        # salia tres planos antes de que se dijera, y el remate del cierre en un
        # numero que ya ni existe.
        #
        # Desde ahora la ficha guarda contra que texto se decidio (`ancla`) y
        # se busca por ahi. Las de antes no lo traen y siguen yendo por su
        # numero: sin saber contra que se decidieron, moverlas seria adivinar.
        ficha = por_texto.get(_texto_clave(escena))
        if not isinstance(ficha, dict):
            ficha = _ajustes_unidad(p, f"escena:{escena['id']}").get("cartela")
        if isinstance(ficha, dict) and ficha.get("plantilla"):
            plan[escena["id"]] = ficha
    idioma = _idioma_hablado(escenas)
    # CUANTOS PLANOS OCUPA CADA UNA, ANTES DE REPARTIR. Una cartela cuyas
    # palabras se dicen a caballo de dos planos consume dos del reparto, y el
    # suelo de separacion y el techo tienen que contarlo antes -- si se contara
    # despues, el reparto mediria una cosa y el video ensenaria otra.
    ocupacion = cartelas.ocupacion_de(escenas, plan, idioma=idioma,
                                      planos=cartelas.PLANOS_MAXIMOS)
    puestas, avisos = cartelas.repartir(escenas, plan, ocupacion=ocupacion)
    for escena in escenas:
        ficha = puestas.get(escena["id"])
        if not ficha:
            continue
        escena["cartela"] = ficha
        if not cartelas.sin_imagen(escena):
            continue          # sobre imagen: el plano se rueda como cualquiera
        _vaciar_plano(escena)
    seguidas = _fundir_cartelas(escenas, beats, puestas, p, idioma)
    # AQUI NO SE AVISA DE TIEMPOS, y los dos avisos que habia se fueron por el
    # mismo motivo: describian como problema algo que el motor ya resuelve.
    #
    # ⚠ CON UNA CORRECCION DEL 25-08. Lo que se lee abajo --«eso esta arreglado
    # y medido [...] cada palabra entra cuando se dice»-- era verdad para el
    # RITMO y no para el ORDEN: una cartela escrita al reves que la voz («OPENED
    # THE DOOR» contra «...and the door opened») no la puede sincronizar nadie,
    # y de eso si se avisa ahora -- pero en `cartelas.avisos_de_orden`, que es
    # donde esta el texto recien escrito y el cajon barato para cambiarlo.
    # 
    #
    # El de «se come tres planos» se retiro el 22-08 con el fundido: una
    # cabecera que ocupa tres planos ES un plano largo con la
    # cabecera encima, que es exactamente lo que se busca.
    #
    # El de «AUN le faltan N s para poder leerse» se retiro el 23-08 (PENDIENTE
    # 33), y conviene tener claro QUE media, porque no era lo que parecia: no
    # decia que la cartela fuera desincronizada -- eso esta arreglado y medido
    # sobre el plan de verdad, cada palabra entra cuando se dice-- sino que
    # queda poca COLA DE LECTURA: el rato que el texto sigue puesto despues de
    # acabar de escribirse. Es confort de lectura, no un fallo de montaje, y
    # sobre todo NO ES ACCIONABLE: cuando salta, el tramo ya se ha estirado
    # todo lo que podia (hasta PLANOS_MAXIMOS o hasta el borde de su bloque) y
    # lo unico que quedaria es reescribir la frase.
    #
    # Lo que NO se va es la cuenta: `cartelas.cola_de_lectura` y
    # `tiempo_necesario` los sigue usando `tramo_de` para decidir hasta donde
    # estirar, que es justo lo que hace que la cola quepa cuando puede caber.
    if seguidas:
        # Un tramo fundido deja menos planos con camara, asi que la alternancia
        # del zoom se rehace sobre las TOMAS que quedan. El recorrido ya no se
        # reparte entre mitades: la escena fundida se lleva el suyo entero, que
        # es lo que hace que la camara no se pare a media cabecera.
        _realternar_zoom(escenas)
    return {"puestas": sorted(puestas), "avisos": avisos, "idioma": idioma,
            "propuestas": len(plan), "seguidas": seguidas,
            "ocupacion": {k: list(v) for k, v in sorted(ocupacion.items())}}


def _idioma_hablado(escenas):
    """En que idioma se locuta este video. Sale de la NARRACION, que esta aqui.

    Hace falta para leer las cifras dichas -- «thirty million» es 30M y «treinta
    millones» tambien --, y se deduce del texto en vez de cablearse desde el
    brief por una razon practica: el mismo emparejado corre en el plan, en la
    vista previa, en p7 y en el sonido, y un parametro que hay que ir pasando
    por cuatro sitios se queda sin pasar en uno. Ver medios.idioma_de.
    """
    texto = " ".join(str(e.get("narracion") or "") for e in escenas[:40])
    return medios.idioma_de(texto)


def _sin_imagen(escena):
    """Los planos que NO pagan una imagen generada.

    Hoy es una sola clase --la cartela de fondo negro, que es texto sobre negro
    y se dibuja entera-- y aun asi la pregunta se hace asi y no «es cartela».
    Lo que decide aguas arriba es si hay una imagen que PAGAR, no de que clase
    es el plano: no se genera, no entra en la cadena de continuidad y no depende
    de ningun asset. Preguntar por la clase obligaria a repasar los cinco sitios
    que lo consultan el dia que aparezca otra clase de plano sin imagen.
    """
    return cartelas.sin_imagen(escena)


def _vaciar_plano(escena):
    """Ni sitio ni gente ni componente: una cartela de fondo negro no ocurre en
    ningun lado, asi que no se rueda ni depende de ningun asset."""
    escena["set"] = None
    escena["personajes"] = []
    escena["componente"] = None
    escena.pop("geo", None)
    escena.pop("carta", None)
    escena.pop("abstracta", None)
    escena["camara"] = None
    escena["ancla"] = None


#: A partir de cuantos planos una cartela deja de ser «un plano que dura el
#: doble» y pasa a ser el montaje parado. DOS esta decidido y es bueno
#: ; tres o mas se avisa. No se prohibe: prohibirlo dejaria la
#: cartela sin poder leerse, que es peor. Lo que se pide es acortar el texto.
PLANOS_SIN_AVISO = 2


def _absorbible(escena, puestas):
    """Si este plano puede pasar a ser una mitad de la cartela de al lado.

    Ni otra cartela (taparla es lo unico que no se puede hacer), ni un plano
    que ya sea la continuacion de otro: un plano normal y suyo.
    """
    if not isinstance(escena, dict):
        return False
    if escena.get("sigue_a") or escena.get("componente"):
        return False
    return not (puestas.get(escena.get("id")) or escena.get("cartela"))




def _fundir(escenas, desde, hasta):
    """Las escenas desde..hasta pasan a ser UNA, mas larga. Devuelve el hogar.

    POR QUE FUNDIR Y NO ENCADENAR. Un plano es un CLIP con su propio reloj SMIL,
    que corre de 0 a lo que dura ESE clip (`p8_render._pagina_de` pone
    `duracion = t_out - t_in` y despues `svg.setCurrentTime`). Mientras un tramo
    fueron varias escenas encadenadas con `sigue_a`, el texto que se dice en el
    segundo 5 tenia su `<animate>` en un clip de 2,5 s y no se pintaba nunca: de
    las siete palabras de la cabecera de INFOSTEALER se escribia UNA, y las seis
    restantes aparecian ya escritas en el corte. Medido sobre el video largo, se
    pintaban 17 de 32 palabras.

    Fundiendo, el reloj del clip ES el del tramo y todas caben. Y no hace falta
    decirle a nadie que ahi dentro no hay corte: es que no lo hay.

    Se concatenan NARRACION y MARCAS, que es lo que decide cuando entra cada
    palabra -- `cartelas.encajar` empareja palabra a palabra contra las marcas y
    se rinde si los dos recuentos no cuadran, asi que concatenar los dos a la
    vez es lo que conserva su invariante. Lo demas es del hogar y no se toca: su
    imagen, su camara, su zoom entero y la transicion con la que se entra.
    """
    hogar = escenas[desde]
    for otro in escenas[desde + 1:hasta + 1]:
        hogar["narracion"] = " ".join(
            x for x in (hogar.get("narracion"), otro.get("narracion")) if x)
        hogar["marcas"] = (list(hogar.get("marcas") or [])
                           + list(otro.get("marcas") or []))
    # el corte de SALIDA del tramo es el del ultimo: es con el que se encadena
    # con lo que viene despues
    hogar["corte"] = escenas[hasta].get("corte")
    hogar["t_out"] = escenas[hasta]["t_out"]
    hogar["duracion"] = round(float(hogar["t_out"]) - float(hogar["t_in"]), 3)
    return hogar


def _fundir_cartelas(escenas, beats, puestas, p=None, idioma=None):
    """UNA CARTELA OCUPA EL TRAMO DE VIDEO EN EL QUE SE DICEN SUS PALABRAS.

    Ese es el enunciado, y las dos direcciones salen de el como consecuencia en
    vez de ser dos casos especiales:

    -- si sus palabras EMPIEZAN antes que su plano, la cartela arranca antes;
    -- si al acabar de escribirse no queda tiempo para leerla, sigue despues.

    Y desde el 22-08 el tramo no se ENCADENA: se FUNDE en una sola escena mas
    larga (ver `_fundir`). Un plano mas, pero mas largo, con la cabecera encima
    -- que es lo que se pidio despues de ver el primer montaje. Con eso se caen
    solos `_seguir_plano`, `_partir_zoom`, la clave `sigue_a` y las ramas que
    existian en transiciones y en sonido para no meter un corte donde no lo
    habia: ya no hay corte que evitar.

    Cuanto se funde lo decide `cartelas.tramo_de`: mientras le falte y haya
    plano libre, SIN cruzar el bloque del guion y sin pasar de
    `cartelas.PLANOS_MAXIMOS`. La frontera del bloque importa tanto como el
    fundido: un bloque es una idea, y una cartela que lo cruza se queda puesta
    mientras la voz ya cuenta otra cosa.

    `beats` va EN PARALELO a `escenas`, asi que se recorta a la vez. Sin eso,
    cada plano posterior a un fundido escribiria el prompt del beat de otro.
    """
    fichas, indice = [], 0
    while indice < len(escenas):
        escena = escenas[indice]
        ficha = puestas.get(escena["id"])
        if not ficha or not cartelas.es_cartela(escena):
            indice += 1
            continue
        libre = lambda otro: _absorbible(otro, puestas)        # noqa: E731
        desde, hasta, escritura = cartelas.tramo_de(
            ficha, escenas, indice, libre, idioma=idioma,
            planos=cartelas.PLANOS_MAXIMOS)
        hogar = escenas[desde]

        # El HOGAR lleva la cartela y la escribe. Si no es su plano de origen,
        # la cartela se ha ido hacia atras: el id NO se renumera --son
        # posicionales-- y el plano de origen se funde dentro.
        if hogar is not escena:
            hogar["cartela"] = dict(ficha)
            escena.pop("cartela", None)
            escena.pop("escritura", None)
            puestas.pop(escena["id"], None)
            puestas[hogar["id"]] = ficha
        hogar["escritura"] = escritura

        # UNA FICHA POR PLANO ABSORBIDO, que es la forma que pide su unico
        # consumidor (`_descontar_estirados`): necesita el `absorbido` y su
        # `libera` uno a uno para quitar del informe de encuadres los planos que
        # dejan de rodarse. Y se apunta si CADA UNO era una toma de verdad,
        # mirando su camara ANTES de que desaparezca -- un plano que ya era
        # cartela no tenia camara que descontar.
        planos = hasta - desde + 1
        segundos = round(float(escenas[hasta]["t_out"])
                         - float(escenas[desde]["t_in"]), 2)
        hacia = "atras" if desde < indice else "delante"
        for otro in escenas[desde + 1:hasta + 1]:
            fichas.append({
                "cartela": hogar["id"], "sigue_en": otro["id"],
                "absorbido": otro["id"],
                "era_toma": bool(otro.get("camara")), "hacia": hacia,
                "planos": planos, "segundos": segundos,
                "faltaban_s": escritura["falta"] or escritura["antes"]})
        _fundir(escenas, desde, hasta)
        if cartelas.sin_imagen(hogar):
            _vaciar_plano(hogar)
        del escenas[desde + 1:hasta + 1]
        del beats[desde + 1:hasta + 1]
        indice = desde + 1
    return fichas


def _realternar_zoom(escenas):
    """Vuelve a alternar el zoom sobre las TOMAS, no sobre los planos.

    Absorber un plano rompe la alternancia de los que quedan: si S002 pasa a ser
    la segunda mitad de S001, entonces S001 y S003 quedan seguidos y los dos
    entrando -- y dos zooms seguidos en el mismo sentido se leen como un unico
    movimiento largo que se traga el corte, que es justo lo que la alternancia
    existe para evitar (motores/guion/segmentar.alternar_zoom).

    Asi que se recuenta: alterna una toma si y otra no.

    Y desde el fundido no hay nada mas que hacer. Antes cada
    toma estirada tenia que REPARTIR su recorrido entre sus mitades, y
    repartiendo de dos en dos cada mitad recibia el recorrido entero otra vez:
    la camara iba y venia en cada corte, que es el «se ve que son varios clips»
    que esto existe para evitar. Un tramo es una escena, asi que se lleva su
    recorrido entero y no hay reparto.
    """
    propios = [e for e in escenas if not e.get("sigue_a")]
    for indice, escena in enumerate(propios):
        zoom = escena.get("zoom")
        if not isinstance(zoom, dict):
            continue
        quiere = "in" if indice % 2 == 0 else "out"
        if zoom.get("tipo") == quiere:
            continue
        # invertirlo es intercambiar los extremos: el recorrido es el mismo
        escena["zoom"] = dict(zoom, tipo=quiere, de=zoom.get("a", 1.0),
                              a=zoom.get("de", 1.0))




def _assets_de_escena(escena):
    usados = []
    if _sin_imagen(escena):
        # Una cartela de fondo NEGRO no usa nada: es texto sobre negro, se
        # dibuja entera y no hereda de ningun sitio, personaje ni componente.
        # Colgarla de un asset la ensuciaria cada vez que se rehiciera ese
        # asset, y rehacerla no cambiaria un pixel. La cartela SOBRE IMAGEN es
        # otra cosa: ahi hay un plano de verdad debajo, con su sitio y su gente.
        #
        return usados
    # El sitio no produce NADA: no es un asset del que depender, asi que
    # la cascada del plano cuelga de sus personajes y sus componentes.
    for personaje in escena.get("personajes") or []:
        usados.append(f"asset:{personaje}")
    if escena.get("componente"):
        usados.append(f"asset:{escena['componente']}")
    for elemento in escena.get("capa_vectorial") or []:
        if elemento.get("tipo") == "capitulo":
            usados.append(f"asset:cabecera_{medios.identificador(elemento.get('titulo', escena['id']))}")
    return usados




def _assets_necesarios(plan, catalogo, params=None):
    """Inventario de assets que el plan necesita, con su tipo y su ficha."""
    params = params or {}
    necesarios = {}
    for escena in plan["escenas"]:
        for personaje in escena.get("personajes") or []:
            spec = catalogo["reparto"].get(personaje) or {}
            necesarios[f"asset:{personaje}"] = {
                "tipo": "reparto", "nombre": personaje,
                "descripcion": spec.get("descripcion", personaje),
                "grupo": bool(spec.get("grupo")),
                # lo que el revisor pidio para ESTA hoja, que tiene que entrar
                # en su prompt (ver _texto_feedback)
                "feedback": _texto_feedback(
                    _ajustes_unidad(params, f"asset:{personaje}").get("feedback")),
            }
        if escena.get("componente"):
            spec = catalogo["componentes"].get(escena["componente"]) or {}
            necesarios[f"asset:{escena['componente']}"] = {
                "tipo": spec.get("tipo", "mapa"), "nombre": escena["componente"],
                "config": spec.get("config") or {},
            }
        for elemento in escena.get("capa_vectorial") or []:
            if elemento.get("tipo") != "capitulo":
                continue
            slug = medios.identificador(elemento.get("titulo", escena["id"]))
            necesarios[f"asset:cabecera_{slug}"] = {
                "tipo": "cabecera", "nombre": f"cabecera_{slug}",
                "titulo": elemento.get("titulo", ""),
                "subtitulo": elemento.get("subtitulo", ""),
                "antetitulo": elemento.get("antetitulo", ""),
            }
    return necesarios


# ------------------------------------------------------------------ prompts

def _prompt_visual(escena, beat, catalogo):
    """Descripcion del plano para el modelo de imagen.

    La frase narrada entra SIEMPRE, y es lo mas importante de esta funcion. El
    catalogo describe el lugar, no el momento: dos planos rodados en el mismo set
    con el mismo reparto producian, sin esto, un prompt identico caracter a
    caracter. Como la firma de la cache es el hash del prompt, el segundo plano
    recibia una copia literal del primero: S001 y S006 salieron con el mismo
    fichero, byte a byte.

    Ademas de evitar el choque, es lo que hace que la imagen ilustre SU frase en
    lugar de una vista generica del sitio donde ocurre.

    Y SI ALGUIEN LO REDACTO ENTERO, MANDA ESO. `redactor` escribe el parrafo
    completo --sitio incluido, copiado literal-- y entonces aqui no hay nada que
    concatenar: se cita y se le pega la frase narrada y el encuadre, que son las
    dos cosas que sigue poniendo el codigo. Ver pasos/redactor.py.
    """
    redactado = " ".join(str(escena.get("redactado") or "").split())
    if redactado:
        # EL SUELO DE LA CARA. Un plano con gente cuyo parrafo no dice la
        # expresion se queda sin que NADIE la diga: esta rama se salta el
        # `_expresion(_tono_de(...))` de mas abajo, y las reglas de la casa
        # llevan «smiling, grin, cheerful expression» en el negativo. O sea que
        # el defecto silencioso no es «la que toque», es «serio».
        #
        # Medido el 07-09-2026: `prueba_1` dejo 98 de 299 planos con gente sin
        # declararla y `prueba_2` 54 -- con la misma instruccion, que ya dice
        # que hay que declararla. Se le exige arriba Y se tapa aqui: si el
        # parrafo no la trae, entra la del tono de SU beat, que es lo que hace el
        # otro camino. Si la trae, aqui no se toca nada: dos expresiones en el
        # mismo prompt seria pedir dos caras.
        if escena.get("personajes") and not _dice_la_cara(redactado):
            redactado = _unir(redactado, _expresion(_tono_de(escena, beat)))
        base = _con_narracion(redactado, escena)
        return (f"{base} SHOT TYPE, and this is not optional: "
                f"{escena['encuadre']}." if escena.get("encuadre") else base)
    if beat.get("prompt"):
        base = _con_direccion(beat["prompt"], escena)
        return _con_narracion(base, escena)
    if escena.get("abstracta"):
        # Una carta abstracta NO se rueda en un sitio: anteponer «la sede del
        # banco» a un diagrama produce un diagrama colgado en una pared. La
        # base es conceptual, la accion del tramo aporta el contenido y los
        # personajes siguen siendo los monigotes del estilo del video.
        partes = ["not a physical location: a clean conceptual composition on "
                  "a flat graphic backdrop, in the exact same flat vector style "
                  "as the rest of the video"]
    # LA ACCION DEL TRAMO SOLO MANDA SI ESTE PLANO NO TIENE LA SUYA.
    #
    # Aqui estaba la raiz de los dos fallos que se veian en el video montado.
    # La accion la escribe `catalogo_visual` UNA VEZ POR TRAMO --y un tramo son
    # varios bloques, o sea varias escenas-- asi que se pegaba identica en todos
    # sus planos. Medido en el video del oro: 222 de 222 escenas compartian su
    # accion con otra, y el grupo mayor eran CINCO planos de la misma cocina de
    # 1925 con la misma accion, distinguidos solo por el angulo de camara.
    #
    # De ahi salian las dos cosas que se veian:
    #   · "la misma escena desde otro angulo", que ademas no cuadra entre si
    #     porque cada plano se dibuja por separado; y
    #   · la imagen que va con lo de antes o lo de despues, porque la accion es
    #     del TRAMO y no se mueve cuando el texto se mueve dentro de el (un
    #     plano que dice "HOY" seguia en la cocina de 1925, y otro que decia
    #     "Argentina" seguia en el Berlin de 1923).
    #
    # `direccion` ya escribe una linea POR PLANO con el video entero delante.
    # Desde ahora esa linea es la idea visual del plano, no un encuadre encima
    # de la del tramo: si la hay, manda ella. La del tramo se queda para los
    # planos sin dirigir, que es como se comportaba todo antes.
        if beat.get("accion") and not _tiene_direccion(escena):
            partes.append(beat["accion"])
        if escena.get("personajes"):
            partes.append("with " + _citar_reparto(escena["personajes"], catalogo)
                + " drawn as the same stick-figure characters as the rest of "
                  "the video, integrated into the composition")
            partes.append(_expresion(_tono_de(escena, beat)))
        base = _con_narracion(
            _con_direccion(", ".join(x for x in partes if x), escena), escena)
        return (f"{base} SHOT TYPE, and this is not optional: "
                f"{escena['encuadre']}." if escena.get("encuadre") else base)
    partes = []
    spec_set = catalogo["sets"].get(escena.get("set")) or {}
    # EL SITIO DEL TRAMO SE CALLA SI EL PLANO DICE EL SUYO. Ver
    # `MARCA_OTRO_SITIO`: anteponer la cocina de 1925 a un plano que dice «HOY»
    # es pedirle al generador dos cosas incompatibles, y gana la que va delante.
    # EL REPARTO DEL TRAMO TAMPOCO LE SIGUE. Un plano que se va a otro sitio se
    # va a otra escena, y la gente del tramo no tiene por que estar alli:
    # medido en el video del oro, un plano que decia «HOY siguen dando para la
    # compra del mes» se fue a un supermercado actual y se llevaba delante «una
    # familia de tres de los anos veinte». Quien salga en ese plano lo dice su
    # propia linea, que para eso la escribe `direccion`.
    otro_sitio = _en_otro_sitio(escena)
    if otro_sitio:
        pass
    elif spec_set.get("prompt") or spec_set.get("descripcion"):
        partes.append(spec_set.get("prompt") or spec_set["descripcion"])
    elif escena.get("componente"):
        spec_comp = catalogo["componentes"].get(escena["componente"]) or {}
        partes.append(spec_comp.get("prompt") or spec_comp.get("descripcion", ""))
    else:
        partes.append(catalogo.get("prompt_por_defecto", ""))
    # Que se ve en este tramo, y SOLO si este plano no trae lo suyo. Ver la nota
    # de arriba: pegarla siempre es lo que hacia que cinco planos seguidos
    # fueran la misma escena desde cinco angulos.
    if beat.get("accion") and not _tiene_direccion(escena):
        partes.append(beat["accion"])
    if escena.get("personajes") and not otro_sitio:
        partes.append("with " + _citar_reparto(escena["personajes"], catalogo))
        partes.append(_expresion(_tono_de(escena, beat)))
    if escena.get("primer_termino"):
        # solo lo llevan los planos que han tenido que repetir camara: cambiar el
        # sujeto en primer termino es lo que hace que no se lean como el mismo
        partes.append("with " + _sujeto(escena["primer_termino"], catalogo) +
                      " large and close in the immediate foreground")
    base = _con_narracion(
        _con_direccion(", ".join(x for x in partes if x), escena), escena)
    if escena.get("encuadre"):
        # LA CARTA TIENE QUE ENTRAR TAMBIEN AQUI, y no solo en la geometria.
        #
        # La direccion le dice al generador donde cae cada cosa, pero no le dice
        # que clase de plano es: dandole solo la caja de un cenital, devuelve una
        # vista en tres cuartos «inspirada» en ella y el plano se aplana al medio
        # de siempre. Dicho por los dos caminos -- la geometria lo propone, esta
        # frase lo exige-- lo que una pasada dejaria suelto lo sujeta la otra,
        # que es la misma regla que ya rige la guia de estilo.
        base = (f"{base} SHOT TYPE, and this is not optional: "
                f"{escena['encuadre']}.")
    return base


# Expresion facial por tono del beat.
#
# La regla de la casa dice que todo prompt con personajes declara la expresion
# de forma explicita (boca, cejas y mirada) y que la sonrisa esta PROHIBIDA por
# defecto, salvo que el plan de escenas pida tono alegre. Con el plan vacio esa
# excepcion no podia dispararse NUNCA: por eso en una fiesta salian todos serios.
# Aqui es donde el tono del beat levanta la prohibicion, y solo aqui.
TONOS = {
    "alegre": ("everyone is visibly happy: open relaxed smiles with the mouth "
               "clearly curved up, raised eyebrows and bright eyes. The cheerful "
               "expression is REQUIRED in this shot, do not draw them neutral"),
    "neutro": ("neutral faces: straight closed mouth, level eyebrows, calm gaze. "
               "No smiling"),
    "tenso": ("tense faces: tight straight mouth, lowered drawn-together "
              "eyebrows, hard fixed stare. No smiling"),
    "triste": ("sad faces: mouth turned down at the corners, inner eyebrows "
               "raised, lowered gaze. No smiling"),
    "solemne": ("solemn faces: closed level mouth, still eyebrows, steady "
                "downward gaze. No smiling"),
}


def _expresion(tono):
    """Frase de expresion facial del tono, con el neutro como valor seguro."""
    return TONOS.get(str(tono or "").strip().lower(), TONOS["neutro"])


def _citar_reparto(personajes, catalogo):
    """Como se nombra al reparto DENTRO de la escena. -> str

    POR SU NOMBRE DE HOJA, NO POR SU DESCRIPCION (07-09).

    Aqui se pegaba la descripcion entera de cada personaje --480 caracteres de
    media en el video del oro-- y era ballast puro: la hoja de ese personaje va
    ADJUNTA como imagen en el mismo prompt, y su propia frase dice, literal,
    «The cast sheet decides what they look like: where the scene description
    below disagrees with it, the sheet wins». O sea que el prompt declaraba
    subordinado un texto que ocupaba el doble que la unica linea que separa un
    plano del de al lado.

    Medido: el bloque `Scene:` paso de 486 caracteres en video_referencia (26 % de
    planos con gente) a 989 en el video del oro (65 % de planos con gente y
    descripciones del doble de largas), y dentro de el la linea del plano cayo
    del 60 % al 24 %. Con la cita corta el bloque vuelve a estar dominado por lo
    que pasa en ESE plano, que es lo que tiene que decidir la imagen.

    Nombrarlos como los nombra la hoja --entre comillas y con el mismo
    identificador-- es lo que ata las dos frases: `frase_de_referencia` dice
    «Reference image 2 is the cast sheet for 'banquero_central'» y esta dice
    «with the character 'banquero_central'».

    LA DESCRIPCION NO SE PIERDE: `_prompt_completo` la vuelve a poner, y solo,
    para el personaje al que NO se le ha podido adjuntar la hoja. Sin ese
    respaldo, una hoja que faltara en disco dejaria al generador con un
    identificador y nada mas.

    Un GRUPO se nombra como grupo: su hoja dibuja a varios, y llamarlo «the
    character» pediria uno.
    """
    reparto = (catalogo or {}).get("reparto") or {}
    piezas = []
    for quien in personajes or []:
        que = "the group" if (reparto.get(quien) or {}).get("grupo") else "the character"
        piezas.append(f"{que} '{quien}'")
    return " and ".join(piezas)


def _sujeto(ancla, catalogo):
    """Como se nombra un ancla del set en un prompt."""
    primeros = catalogo.get("primer_termino") or {}
    return str(primeros.get(ancla) or ancla).replace("_", " ")


def _con_narracion(base, escena):
    """Ancla la descripcion del plano a la frase que se esta narrando.

    Con la coletilla de solo «el momento que describe» las frases abstractas
    (una cifra, una comparacion) salian como otra vista del mismo sitio: no hay
    ningun momento visible que dibujar. La escenificacion explicita es lo que
    permite que «cuesta lo que un piso en Madrid» sea el ladron viviendo en ese
    piso y no el foro de siempre con otro retoque.
    """
    linea = (escena.get("narracion") or "").strip()
    if not linea:
        return base
    momento = (f'This shot accompanies the narration line: "{linea}". '
               f"Show the specific moment that line describes -- or, when the "
               f"line is abstract (a figure, a comparison, a concept), stage "
               f"one concrete scene that makes that idea visible. Never a "
               f"generic view of the location.")
    return _unir(base, momento)


def _unir(base, trozo):
    """Pega dos trozos de prompt con UN punto, no con dos.

    Hasta la direccion (§36) todo lo que llegaba aqui como `base` era una lista
    de fragmentos unida por comas, que nunca acababa en punto, asi que pegar
    «. » a pelo salia bien. La direccion es una frase redactada y SI acaba en
    punto: «flat dark air above.. This shot accompanies...». No rompe la imagen
    -- el modelo lo lee igual -- pero un prompt con erratas es un prompt que
    nadie se cree cuando hay que depurarlo.

    Y no cuesta una sola imagen: un plano SIN direccion no acaba en punto, asi
    que su prompt sale caracter a caracter igual que antes y la cache lo
    reconoce. Solo cambia el de los dirigidos, que ya cambia por llevar la
    direccion.
    """
    base = (base or "").rstrip()
    if not base:
        return trozo
    return f"{base} {trozo}" if base[-1] in ".!?" else f"{base}. {trozo}"


#: Como un plano declara que NO ocurre en el sitio de su tramo. Lo escribe
#: `direccion` al principio de su linea (ver la regla alli), y aqui hace que la
#: descripcion del set no se anteponga: si el plano dice donde esta, el sitio
#: del tramo sobra y ademas lo contradice.
#:
#: Existe porque el sitio es del TRAMO y un tramo puede cambiar de sitio a
#: mitad. Medido en el video del oro: un plano que decia «HOY siguen dando para
#: la compra del mes» llevaba delante «A small 1920s working-class kitchen...» y
#: salio dibujando 1925; otro que decia «Argentina lleva decadas en ello»
#: llevaba la calle del Berlin de 1923, que era el sitio del tramo anterior.
MARCA_OTRO_SITIO = "EN OTRO SITIO:"


def _en_otro_sitio(escena):
    """Si este plano declara su propio sitio y el del tramo no debe anteponerse."""
    linea = " ".join(str((escena or {}).get("direccion") or "").split())
    return linea.upper().startswith(MARCA_OTRO_SITIO)


#: El tono que declara el PLANO, si lo declara. Lo escribe `direccion` al final
#: de su linea como «(TONO: alegre)».
#:
#: El tono es del TRAMO igual que el sitio y la accion, y falla igual: en el
#: video del oro habia `tenso` en ocho de los diecinueve tramos con gente y
#: `alegre` en ninguno, asi que TODOS los planos con personas llevaban «No
#: smiling» y la mitad «hard fixed stare». La familia que comia un mes con cinco
#: gramos de oro salia enfadada.
_TONO_DEL_PLANO = re.compile(r"\(\s*TONO\s*:\s*([a-zA-Zaeiou]+)\s*\)", re.I)


#: Las palabras con las que un texto en ingles declara una cara. Las MISMAS que
#: mira `redactor.sin_declarar`, y tienen que seguir siendo las mismas: si el
#: aviso de antes de pagar y el suelo del prompt no cuentan igual, uno de los dos
#: miente.
PISTAS_DE_CARA = ("mouth", "eyebrow", "brow", "gaze", "eyes", "smil", "grin",
                  "expression", "frown")


def _dice_la_cara(texto):
    """Si ese texto declara la expresion de quien sale. -> bool"""
    bajo = str(texto or "").lower()
    return any(p in bajo for p in PISTAS_DE_CARA)


def _tono_de(escena, beat):
    """El tono que manda en este plano: el suyo si lo declara, y si no el del tramo."""
    linea = str((escena or {}).get("direccion") or "")
    casa = _TONO_DEL_PLANO.search(linea)
    if casa and casa.group(1).strip().lower() in TONOS:
        return casa.group(1).strip().lower()
    return (beat or {}).get("tono")


def _tiene_direccion(escena):
    """Si este plano trae idea propia. Con la MISMA cuenta que `_con_direccion`.

    Una direccion de solo espacios NO es una direccion: `_con_direccion` la
    descarta al normalizarla, asi que mirarla en crudo aqui dejaba el plano sin
    la accion de su tramo Y sin la suya -- un prompt con el sitio y nada mas.
    Lo caza `prueba_piezas`: «una direccion en blanco es no tener direccion».
    """
    return bool(" ".join(str((escena or {}).get("direccion") or "").split()))


def _con_direccion(base, escena):
    """LA LINEA QUE DICE QUE SE VE EN ESTE PLANO, y no en el de al lado.

    Es la capa que faltaba. Todo lo demas del prompt es compartido: el sitio es
    el mismo para todos los planos rodados ahi y la accion del beat es la misma
    para todo su tramo del guion, asi que dos planos seguidos del mismo sitio
    recibian casi el mismo encargo. Medido sobre el video largo: S032, S033 y S034
    compartian 852 caracteres de 1.280, y la unica diferencia era la frase
    narrada (ver `pasos/direccion.py`).

    Va DELANTE de la frase narrada y detras del sitio, que es el orden en que se
    lee: donde estamos, que vemos, y que se esta diciendo mientras.

    OPCIONAL a proposito: un plano sin direccion se arma exactamente como antes
    --con la accion de su tramo--. Asi el paso se puede anadir a un video a
    medias sin cambiarle una imagen hasta que alguien decida dirigirlo.

    Y DESDE EL 28-08 ES LA IDEA VISUAL, no una capa encima de ella. Anadirla
    sobre la accion del tramo no bastaba: los 852 caracteres compartidos que
    mide el parrafo de arriba seguian ahi, y los planos seguian siendo el mismo
    encargo con otro encuadre. Cuando hay direccion, la accion del tramo NO
    entra en el prompt (ver `_prompt_escena`).
    """
    linea = " ".join(str(escena.get("direccion") or "").split())
    if not linea:
        return base
    return _unir(base, linea)


def regla_de_especie(estilo):
    """Lo que el estilo dice de COMO SON los personajes, o "".

    Es la linea `personajes` de la guia escrita («every character is a monkey
    on all fours...»). Existe como funcion porque manda en tres sitios --la hoja
    del reparto, cada plano y el catalogo que describe al reparto-- y en los
    tres tiene que ser la misma frase.
    """
    guia = (estilo or {}).get("guia") if isinstance(estilo, dict) else None
    if not isinstance(guia, dict):
        return ""
    return " ".join(str(guia.get("personajes") or "").split())


def clausula_de_especie(estilo):
    """La frase que hace que «a man» se dibuje como manda el estilo. -> [str]

    PASO (02-09-2026, video de Nvidia con el estilo Monos): el catalogo
    describio a Jensen como «a man in his early thirties of East Asian
    descent...», esa frase entro literal en el prompt de cada plano y el
    generador dibujo un HOMBRE en los dos primeros planos y un mono en los
    demas; la hoja del reparto salio mitad y mitad. La guia decia «every
    character is a monkey», pero iba diez lineas mas abajo y una descripcion
    concreta pesa mas que una regla general. Esta clausula va pegada a la
    descripcion y dice explicitamente quien manda.
    """
    regla = regla_de_especie(estilo)
    if not regla:
        return []
    # TRES AUTORIDADES, EN ORDEN, y se dicen en orden porque el generador
    # resuelve los conflictos con lo ultimo que le parece concreto:
    #   1. la regla del estilo decide la ESPECIE y la anatomia (mono, monigote,
    #      persona realista, plastilina, lo que sea el canal);
    #   2. la hoja del reparto decide la IDENTIDAD (cara, pelo, ropa,
    #      accesorios) y se copia aunque los personajes «de fabrica» del estilo
    #      vistan de otra manera -- paso: Jensen salio mono con camisa blanca y
    #      corbata, el uniforme de los monos de la lamina, en vez de con su
    #      chaqueta de cuero;
    #   3. la descripcion del plano decide la pose y la accion.
    return [f"HOW CHARACTERS ARE DRAWN IN THIS STYLE (species, anatomy, "
            f"proportions), and this rule beats the wording of any character "
            f"description in this prompt: {regla} Where a description says "
            f"'a man', 'a woman', 'a person' or 'people', draw that character "
            f"with the species and anatomy this rule gives to everyone, never "
            f"as a realistic human unless the rule itself says so.",
            "But the rule decides ONLY species and anatomy. Each character's "
            "IDENTITY -- face, hair, facial hair, glasses, age, build, and "
            "especially their clothing and accessories -- comes from their "
            "cast sheet when one is attached, and otherwise from the "
            "description, and it must be kept exactly even if the style's "
            "default characters dress or look differently. A character in a "
            "black leather jacket wears that jacket, not the outfit the style's "
            "sample characters wear."]


def guia_escrita(estilo):
    """La guia de estilo del video, EN PALABRAS, lista para meter en un prompt.

    Dice lo mismo que ensenan las referencias, y va aparte a proposito: el modelo
    de imagen reinterpreta las imagenes en cada llamada y puede fijarse en cosas
    distintas; el texto fija la paleta y el trazo igual en todas. Dicho por dos
    caminos, lo que una pasada dejaria suelto lo sujeta la otra.

    Vive aqui, y no dentro del prompt de los planos, porque LAS HOJAS DE REPARTO
    LA NECESITAN IGUAL. Estaba escrita ahi dentro, y la rama del reparto tenia su
    propia frase de estilo de una linea: el plano recibia 6.188 caracteres
    describiendo el dibujo de este video y la hoja de personaje 986, de los cuales
    201 eran un literal cableado en el codigo -- «simple rounded shapes, muted
    earthy palette, bean-shaped characters» -- identico para todos los videos del
    Estudio. Las hojas salian en un estilo que no era el elegido, y de ahi pasaban
    a los planos que las usan como referencia de personaje.

    Y tenia un segundo filo: la firma con la que se cachea una imagen se calcula
    sobre su prompt, asi que una guia que no entra en el prompt tampoco entra en
    la firma. Reescribir la guia NO invalidaba la hoja: volvia de la cache igual
    para siempre. Con la guia dentro, eso se arregla solo.
    """
    guia = (estilo.get("guia") or {}) if isinstance(estilo.get("guia"), dict) \
        else {"guia": estilo.get("guia")}
    lineas = []
    if guia.get("guia"):
        lineas.append(f"Style guide, follow it to the letter: {guia['guia']}")
    if guia.get("paleta"):
        lineas.append("Use this colour palette: "
                      + ", ".join(str(c) for c in guia["paleta"][:8]) + ".")
    if guia.get("trazo"):
        lineas.append(f"Outlines: {guia['trazo']}")
    if guia.get("relleno"):
        lineas.append(f"Fills and shading: {guia['relleno']}")
    if guia.get("personajes"):
        lineas.append(f"Characters: {guia['personajes']}")
    if guia.get("caras"):
        lineas.append(f"Faces: {guia['caras']}")
    # Las manos son lo segundo que mas canta cuando falla, despues de la cara, y
    # el generador tira SIEMPRE a la mano realista de cinco dedos si nadie le
    # dice otra cosa. Va con nombre propio en el prompt por lo mismo que las
    # caras: metido dentro del parrafo general se diluye.
    if guia.get("manos"):
        lineas.append(f"Hands, arms and feet: {guia['manos']}")
    if guia.get("fondos"):
        lineas.append(f"Backgrounds: {guia['fondos']}")
    # Los tres de abajo los escribe la guia desde el 14-08-2026. Una guia
    # anterior no los trae y aqui simplemente no salen: el prompt es el
    # mismo que antes, asi que no obsoleta ningun proyecto en marcha.
    if guia.get("luz"):
        lineas.append(f"Light and shadow: {guia['luz']}")
    if guia.get("composicion"):
        lineas.append(f"Composition: {guia['composicion']}")
    if guia.get("acabado"):
        lineas.append(f"Finish and texture: {guia['acabado']}")
    if guia.get("evitar"):
        lineas.append(f"Never do this, it breaks the style: {guia['evitar']}")
    return lineas


def _nombre_en(idioma):
    """Codigo de idioma -> nombre EN INGLES para el prompt, o "".

    Al generador de imagen se le habla en ingles --la guia de estilo, las reglas
    de la casa y la descripcion del plano van en ingles-- asi que decirle
    «espanol» ahi dentro es pedirle que adivine. Se usa la tabla de p2_brief, que
    es donde ya viven los nombres de idioma; una copia aqui se desincronizaria el
    dia que se anada uno.

    Vacio cuando no lo conoce, y es deliberado: mas vale no decir nada que
    colarle un codigo de dos letras, que lo dibujaria tan tranquilo.
    """
    codigo = str(idioma or "").strip().lower()
    return p2_brief.nombre_idioma_en(codigo) if codigo else ""


def frase_de_referencia(indice, ref):
    """La frase del prompt que presenta la referencia numero `indice`. -> str|None

    UNA SOLA FUNCION PARA LOS DOS CAMINOS. La primera generacion y el corrector
    (pasos/corrector.py) adjuntan las mismas clases de imagen --la hoja de un
    personaje, el plano anterior, la imagen rechazada, lo que trajo el
    revisor-- y el generador tiene que oir lo mismo de cada clase en los dos
    casos: que copiar de ella y que no. Lo que anade el corrector es `detalle`,
    la precision que solo se sabe mirando la imagen («copy only the beige CRT
    at its left edge»), y va detras de la frase de la clase, no en su lugar.
    Las de estilo y lamina no llevan frase aqui: se presentan juntas arriba.
    """
    lineas = []
    if ref["papel"] in ("estilo", "lamina"):
        return None
    if ref["papel"] == "reparto" and ref.get("de_nota"):
        lineas.append(f"Reference image {indice} is the cast sheet for "
                      f"'{ref['nombre']}', a character the reviewer's note at "
                      f"the end of this prompt names. The note decides who is "
                      f"in this shot: if it says {ref['nombre']} appears, or "
                      f"that someone must be replaced by {ref['nombre']}, draw "
                      f"{ref['nombre']} from this sheet -- same face, hair, "
                      f"build and clothes -- with the same authority as any "
                      f"cast sheet, and do not keep the character it replaces.")
    elif ref["papel"] == "reparto":
        # Con negativo y con prioridad, como las demas. Era el UNICO bloque de
        # referencia que decia solo que copiar y no que NO hacer: la lamina
        # lleva «never their content» y esta se quedaba en una frase de
        # diecisiete palabras. La
        # cara, que es lo que una hoja existe para fijar, ni se nombraba.
        lineas.append(f"Reference image {indice} is the cast sheet for "
                      f"'{ref['nombre']}': draw those exact characters. Copy "
                      f"their faces, hair, skin tone, build and clothes exactly "
                      f"as drawn there, and do not redesign them. The cast "
                      f"sheet decides what they look like: where the scene "
                      f"description below disagrees with it, the sheet wins, "
                      f"and where the style sheet's sample characters dress "
                      f"or look differently, the cast sheet still wins for "
                      f"this character's identity and clothing."
                      + (" Their faces are covered in that sheet and that is "
                         "deliberate: keep every covering on, copy its exact "
                         "shape, markings and colours, and never show the face "
                         "underneath."
                         if ref.get("tapada") else ""))
    elif ref["papel"] == "continuidad":
        # El negativo pesa tanto como lo que se pide, y aqui faltaba. Las
        # referencias de estilo SI lo llevan ("never their content"); esta
        # decia solo que copiar, nunca que no copiar. Con una escena sin set
        # ni reparto, esta imagen era lo unico concreto de todo el prompt
        # -el resto era una linea de narracion- y en una llamada de
        # images/edits eso se lee como "edita esto": salia el plano anterior
        # con un cambio pequeno (la misma persona en la misma posicion,
        # ahora saltando; o con alguien mas al lado).
        if ref.get("mismo_set"):
            # El caso que faltaba, y es el que se nota: dos planos del mismo
            # sitio. Antes esta referencia solo decia lo que NO copiar, asi
            # que el generador dibujaba una sala distinta cada vez -- mismo
            # estilo, misma paleta, otro sitio-- y el espectador no
            # reconocia el lugar. Lo que hacia falta era decir que el
            # ESPACIO es el mismo.
            #
            # PERO NO «SOLO CAMBIA LA CAMARA» (07-09). Aqui ponia «What changes
            # is ONLY the viewpoint, and the viewpoint is the SHOT TYPE
            # described below», que es literalmente el encargo que este paso
            # entero vino a quitar: «la misma escena desde otro angulo». Con
            # esa frase y la foto delante, la linea del plano --236 caracteres
            # de 19.193-- no tenia con que ganar. Medido en el video del oro:
            # cinco planos de `factura_custodia` que dicen «alquilar una caja en
            # el banco», «comprarla para casa» y «custodiarlo con un tercero»
            # salieron los tres como otro angulo de la misma factura sobre la
            # misma mesa.
            #
            # Lo que la foto aporta es EL SITIO. Lo que pasa dentro lo dice la
            # descripcion de abajo, y es OTRO MOMENTO: puede no quedar en el
            # cuadro nada de lo que esa imagen ensena.
            lineas.append(
                f"Reference image {indice} is an earlier shot of THIS SAME "
                f"PLACE"
                + (f" (it was shot from '{ref['desde']}')" if ref.get("desde") else "")
                + ". Use it for the PLACE and nothing else: the same "
                  "architecture, the same walls, floor and ceiling, the same "
                  "fixed furniture, materials and colours, so that a viewer "
                  "recognises it instantly as the same place. Match its "
                  "palette, line weight and lighting. "
                + "Everything else comes from the scene description below, and "
                  "this is a DIFFERENT MOMENT of the story, not the same one "
                  "from another camera: what is in the foreground, who is in "
                  "frame, what they are doing and what the shot is about are "
                  "whatever that description says, even when none of it appears "
                  "in this image. Do NOT reuse its composition, framing, "
                  "staging or character poses, and never redraw it with a small "
                  "change.")
        # No hay «else». Una referencia de continuidad de OTRO sitio ya no se
        # adjunta (ver _referencias_escena): decirle con palabras que no
        # copie el contenido de una imagen no basta, y el precio de que no
        # obedezca es que el colegio salga con los muebles del banco.
    elif ref["papel"] == "parecido":
        # El limite duro de esta referencia. Es una FOTO de imagen real, y
        # adjuntarla sin decir esto empuja el dibujo al fotorrealismo, que es
        # justo lo contrario de lo que busca el Estudio. Se dice que se copia
        # (quien o que es) y, sobre todo, que NO se copia (como esta hecha).
        lineas.append(
            f"Reference image {indice} is a PHOTOGRAPH of the real "
            f"{ref.get('que_es') or 'subject'}, for likeness only: use it to "
            f"know who or what this is"
            + (f" ({ref['rasgos']})" if ref.get("rasgos") else "")
            + ". Do NOT copy its rendering: it is a photo and this must stay "
              "flat vector cartoon exactly as described above. Ignore its "
              "lighting, texture, depth of field, grain and colour grading.")
    elif ref["papel"] == "real":
        # La cosa REAL que la narracion acaba de nombrar, bajada de Wikimedia
        # Commons. Se separa de 'parecido' porque el encargo es distinto: alli
        # se pide la CARA de alguien de este video, y aqui la FORMA de algo
        # que existe en el mundo y que el espectador puede reconocer o no
        # reconocer. Y con los logos hay una trampa propia: un logo suele SER
        # texto, y la regla de la casa dice que el texto es raro y solo
        # cuando la escena lo pide. Un logo pedido a proposito lo pide, y por
        # eso se dice aqui, junto al logo, que ese va SI o SI.
        que = ref.get("que_es") or "thing"
        nombre = ref.get("nombre") or ""
        if ref.get("tipo") == "logo":
            lineas.append(
                f"Reference image {indice} is the REAL logo of "
                f"{nombre or 'the brand named in this shot'}. Redraw it in "
                f"the flat vector style of this production -- same line "
                f"weight, same palette discipline -- but keep its actual "
                f"shape, its actual symbol and its actual proportions, so "
                f"that a viewer recognises the real brand. Text is rare in "
                f"this production, but this logo is asked for: if it "
                f"contains lettering, draw that lettering. Do not invent a "
                f"different mark and do not add any other text.")
        else:
            lineas.append(
                f"Reference image {indice} is a PHOTOGRAPH of the real "
                f"{que}"
                + (f", {nombre}" if nombre else "")
                + ", which the narration of this shot names. Use it so that "
                  "what you draw is recognisably THAT one and not a generic "
                  "example: keep its real shape, its real proportions, its "
                  "landmark details and its real colours. Do NOT copy its "
                  "rendering -- it is a photo and this must stay flat vector "
                  "cartoon exactly as described above -- and ignore its "
                  "lighting, texture, depth of field, grain and grading.")
    elif ref["papel"] == "rechazada":
        # LA IMAGEN QUE SE RECHAZO, y va con la instruccion CONTRARIA a la
        # de continuidad: de esa no se copia el contenido, y de esta se copia
        # TODO menos lo que la nota diga. Solo llega aqui cuando el enrutador
        # ha clasificado la nota como retoque localizado (`repaso.ALCANCES`):
        # en un cambio sustitutivo esta misma frase es la que hacia volver a
        # salir el monolito.
        lineas.append(
            f"Reference image {indice} is THE IMAGE THAT WAS REJECTED: it is "
            f"this very shot as it was drawn last time. Redraw it as it is. "
            f"Keep the same composition, the same framing, the same camera "
            f"angle, the same characters in the same places and poses, the "
            f"same background and the same colours. Change ONLY what the "
            f"reviewer's note at the end asks you to change; everything the "
            f"note does not mention must come out identical. This is a "
            f"correction of that picture, not a new take on the shot.")
    elif ref["papel"] == "adjunta":
        # Lo que arrastro quien escribio la nota. Con su negativo, como
        # todas: sin el, una foto suelta al final del prompt se lee como
        # «dibuja esto».
        lineas.append(
            f"Reference image {indice} was attached by the reviewer together "
            f"with the note at the end of this prompt. Use it ONLY for what "
            f"that note asks of it. Do not copy its framing, its style, its "
            f"rendering or anything in it that the note does not name, and "
            f"never reproduce arrows, circles, handwriting or any other mark "
            f"drawn on top of it: those are annotations, not part of the "
            f"picture.")
    if not lineas:
        return None
    frase = lineas[0]
    detalle = " ".join(str(ref.get("detalle") or "").split())
    if detalle:
        frase += (f" For this shot in particular, the reviewer's correction "
                  f"asks this of image {indice}: {detalle}")
    return frase


#: LO ULTIMO QUE LEE EL GENERADOR SOBRE LAS LETRAS, y va aqui porque la ultima
#: posicion es la que mas pesa.
#:
#: La politica larga --cuando lleva letras un dibujo y como se escriben-- vive
#: en las reglas `texto-en-imagen-permitido-pero-raro` y
#: `nada-de-letras-inventadas`, que ahora entran ANTES de la escena. Esto no las
#: repite entera: sujeta las tres cosas que se rompen, dichas en cuatro lineas.
#:
#: QUE FALTABA, Y ESTA VISTO EN UNA IMAGEN (07-09-2026). Las reglas limitan un
#: rotulo --diez palabras como mucho-- pero no CUANTOS rotulos lleva la imagen
#: ni cuan grande tiene que ser cada uno. Un plano del quiosco salio con NUEVE
#: titulares de cuatro palabras: cada uno cumplia la regla, el conjunto era una
#: pared de letra pequena y tres salieron mal escritos («TRANSPORTE PUBLICO
#: MEJORA SERVICIO» partido, «IIUEVO CAFA!», «VECINOS PLANTAN PLANTA(ARBOLES»).
#: Y la direccion de ese plano no pedia NI UNA letra: se las invento entera.
#:
#: La salida cuando no caben es la que ya funciona y esta en el mismo video: el
#: primer plano dibuja su titular como una banda de garabatos ondulados y se lee
#: como un periodico sin que haya una sola palabra.
ULTIMA_PALABRA_ROTULOS = (
    "LETTERING, AND THIS IS THE LAST WORD ON IT: draw only the words this "
    "prompt asked for in quotes, and nothing else. AT MOST TWO pieces of "
    "lettering in the whole image -- one is better, none is fine -- and every "
    "one of them large enough to read at a glance, occupying a real part of the "
    "frame. Never a wall or a grid of small captions. Every other surface that "
    "could carry text -- a page, a screen, a sign, a cover, a label, a poster, "
    "a book -- is drawn WITHOUT words, using illegible wavy strokes and blocks "
    "that read as text from a distance. Never invent a headline, a title, a "
    "caption or a label, not even a plausible one.")


def _ultima_palabra_idioma(idioma):
    """Y EN QUE IDIOMA, dicho en la ultima linea. -> str o ""

    La politica ya esta arriba, en la regla `texto-dibujado-en-el-idioma-del-
    video`, y con el dato («The language of this film is Spanish.») pegado a
    ella. Esto la REPITE al final, y la repeticion es el arreglo.

    EL FALLO QUE CIERRA (07-09-2026). `direccion` no recibia el idioma del video
    --nadie se lo pasaba-- y el unico ejemplo de rotulo que tenia delante estaba
    escrito en ingles: «a shop sign above the window reading "CORNER STORE"». En
    `video_referencia` pidio 14 rotulos en ingles para un video en castellano: "CITY OPENS
    NEW PARK", "BANK", "SAVINGS", "THE PROBLEM", "TO LET"... Y el generador los
    dibujo, porque un texto ENTRE COMILLAS gana a una politica escrita a la mitad
    del prompt.

    Se arregla arriba --los dos agentes ya reciben el idioma-- y se blinda aqui:
    si a pesar de todo llega un rotulo entrecomillado en otro idioma, la ultima
    linea manda dibujarlo en el del video. Las dos capas hacen falta: la de
    arriba evita el fallo y esta lo tapa cuando la de arriba no obedece.

    Los nombres propios se quedan como son, igual que en la regla: traducir
    «Bank of England» seria otro fallo, no el arreglo de este.
    """
    nombre = _nombre_en(idioma)
    if not nombre:
        return ""
    return (f"AND IN WHICH LANGUAGE: every word you draw is written in "
            f"{nombre}, correctly spelled, accents and diacritics included -- "
            f"even when the scene description above quoted it in another "
            f"language. If a quoted piece of lettering is not in {nombre}, draw "
            f"it in {nombre}. The only exceptions are real names that keep their "
            f"real-world form: brands, logos, acronyms, institutions, place "
            f"names and titles of real works.")


def _prompt_completo(escena, referencias, estilo, feedback="", idioma="",
                     formato="", fichas_reparto=None):
    """Prompt final citando cada referencia por su posicion, como espera la API.

    `fichas_reparto` es `plan["assets"]`, y sirve para UNA cosa: devolver la
    descripcion de un personaje al que no se le ha podido adjuntar la hoja. Ver
    `_citar_reparto`, que es quien la quito del texto de la escena.
    """
    reglas = medios.motor("reglas/reglas.py")
    lineas = ["Draw a single illustration for one shot of an animated documentary."]
    if p2_brief.comun.normalizar_formato(formato) == "vertical":
        # EL CUADRO ES VERTICAL, y hay que decirlo: las referencias de estilo
        # son apaisadas y sin esta linea el generador compone un plano apaisado
        # dentro de un lienzo alto, con el sujeto pequeno en medio y aire arriba
        # y abajo. Lo que se pide es lo que un movil ensena: sujeto grande,
        # centrado, y lo importante en el tercio central.
        lineas.append("The frame is PORTRAIT (9:16, vertical, for a phone "
                      "screen): compose for a tall frame. Put the subject large "
                      "and centred, keep everything important within the middle "
                      "two thirds of the height, and let the background fill the "
                      "top and bottom naturally. Never draw black bars, borders "
                      "or a landscape picture inside the tall frame.")

    # Las de estilo se citan JUNTAS, en una sola frase. Repetir "match the art
    # style of reference image N" una vez por imagen gasta prompt y, sobre todo,
    # sugiere que cada una manda sobre algo distinto: lo que se quiere es que las
    # cinco describan UN mismo estilo visto en situaciones distintas.
    # La lamina: las mismas referencias, pero en UNA imagen. Se cita aparte y
    # con su prohibicion, porque el riesgo es distinto: una hoja de miniaturas
    # invita a devolver una hoja de miniaturas.
    lamina = [(i, ref) for i, ref in enumerate(referencias, start=1)
              if ref["papel"] == "lamina"]
    if lamina:
        indice, ref = lamina[0]
        lineas.append(
            f"Reference image {indice} is a STYLE SHEET: a single picture that "
            f"contains {ref.get('cuantas') or 'several'} separate frames from the "
            f"same production, laid side by side only so they fit in one image. "
            f"Copy the drawing style they share -- line weight, palette, shapes, "
            f"proportions -- and never their content. "
            f"Its grid layout is NOT part of the style and must NOT be "
            f"reproduced: your output is ONE single full-bleed illustration of "
            f"one moment. Never draw a grid, a collage, a contact sheet, panels, "
            f"a split screen, borders, frames or separate boxes.")
        # solo si alguien lo ha escrito: el defecto ya no rellena esto con una
        # descripcion generica, que era describirle otro video al generador
        if estilo.get("prompt"):
            lineas.append(f"Style: {estilo['prompt']}.")

    estilos = [i for i, ref in enumerate(referencias, start=1)
               if ref["papel"] == "estilo"]
    if estilos:
        cita = (f"reference image {estilos[0]}" if len(estilos) == 1
                else f"reference images {estilos[0]} to {estilos[-1]}")
        lineas.append(
            f"Match exactly the art style of {cita}"
            + (f": {estilo['prompt']}" if estilo.get("prompt") else "") + "."
            + (" They are different shots of the same production: copy the "
               "drawing style they share, never their content."
               if len(estilos) > 1 else ""))

    if estilos or lamina:
        lineas.extend(guia_escrita(estilo))
        if escena.get("personajes"):
            lineas.extend(clausula_de_especie(estilo))

    for indice, ref in enumerate(referencias, start=1):
        frase = frase_de_referencia(indice, ref)
        if frase:
            lineas.append(frase)
    # LAS REGLAS DE LA CASA VAN ANTES DE `Scene:`, Y ESO ES LO CONTRARIO DE LO
    # QUE PONIA AQUI (07-09).
    #
    # Estaban detras, y detras son 5.713 caracteres --el 30 % del prompt-- entre
    # lo que hay que dibujar y el final. La ultima posicion es la que mas pesa;
    # lo dice el comentario de «No watermarks» tres lineas mas abajo y lo dice
    # `_bloque_feedback`, que se puso la ultima justamente por eso. Con las
    # reglas ahi, lo ultimo que leia el generador era la lista de leyes
    # generales y no el plano concreto que se le estaba encargando.
    #
    # Y las reglas no pierden nada por adelantarse: son leyes, valen igual
    # dichas antes, y encima quedan donde estan las otras dos leyes generales
    # --la guia de estilo y la regla de especie--, que es donde se leen juntas.
    # Lo que gana el sitio del final es la unica linea que cambia de un plano al
    # de al lado.
    bloque = reglas.bloque_prompt("prompt_imagen")
    if bloque:
        lineas.append(bloque)
    # CUAL es el idioma del video. La POLITICA --que lo que la produccion
    # escribe va en el idioma del video, y que los nombres propios no se
    # traducen-- vive en la regla `texto-dibujado-en-el-idioma-del-video`, que
    # acaba de entrar con el bloque de arriba. Aqui solo se dice el dato, que es
    # lo unico que la regla no puede saber: el reparto es el mismo que en
    # `manos-segun-la-guia`.
    #
    # Va pegado a la regla que lo interpreta, y por eso se ha movido CON ella:
    # lo que no puede es quedarse suelto entre las reglas y la escena.
    nombre = _nombre_en(idioma)
    if nombre:
        lineas.append(f"The language of this film is {nombre}.")
    # EL RESPALDO DE `_citar_reparto`: la escena nombra a su gente por el
    # identificador de su hoja, asi que un personaje SIN hoja adjunta se
    # quedaria en un identificador y nada mas. Solo para esos, y solo aqui --
    # donde por fin se sabe que se ha adjuntado de verdad y que no.
    con_hoja = {r.get("nombre") for r in referencias
                if r.get("papel") == "reparto"}
    for quien in (escena.get("personajes") or []):
        if quien in con_hoja:
            continue
        ficha = (fichas_reparto or {}).get(f"asset:{quien}") or {}
        descrito = " ".join(str(ficha.get("descripcion") or "").split())
        if descrito:
            lineas.append(f"No cast sheet is attached for '{quien}': "
                          f"draw them from this description -- {descrito}")
    if escena.get("prompt"):
        lineas.append(f"Scene: {escena['prompt']}.")
    if escena.get("luz"):
        lineas.append(f"Time of day and lighting: {escena['luz']}. This is "
                      f"mandatory and must not drift from the previous shot.")
    lineas.append(ULTIMA_PALABRA_ROTULOS)
    cierre_idioma = _ultima_palabra_idioma(idioma)
    if cierre_idioma:
        lineas.append(cierre_idioma)
    if feedback:
        lineas.append(_bloque_feedback(feedback))
    # Aqui iba «No text, no letters, no numbers, no watermarks anywhere», y era
    # la ultima linea del prompt: la que mas pesa. Lo que se puede escribir
    # dentro del dibujo lo dice ahora la regla `texto-en-imagen-permitido-pero-
    # raro`, que entra unas lineas mas arriba con el resto del bloque de reglas.
    lineas.append("No watermarks.")
    return " ".join(lineas)


def _bloque_feedback(feedback):
    """La nota del revisor, escrita para que GANE. -> str

    QUE PASABA, Y ESTA MEDIDO (PENDIENTE 36). La nota iba al final del prompt
    con una frase honesta -- «the reviewer rejected the previous image [...] and
    fixing it is NOT optional» -- y funcionaba cuando CORREGIA un detalle («las
    manos mal») y fallaba cuando SUSTITUIA la escena. El caso: en S018 del
    Aurora se pidio «plano cercano de un movil en una mano, con el branding
    de Snowflake» y siguio saliendo el monolito con el candado, sin movil.

    No era una contradiccion literal como la de la hoja de personaje (32): era
    PESO, y se midio antes de tocar nada. En ese plano:

        Scene:      905 caracteres        feedback: 140      6,5 a 1
        y 438 de esos 905 (el 48 %) describen exactamente lo que el revisor
        queria quitar: «the login panel rises as a monolith», «a small keyboard
        lies flat in the foreground», «towering vertical lines».

    Y al medirlo salio ademas una segunda cosa que no estaba apuntada: dentro
    del Scene hay un imperativo ABSOLUTO rival -- «SHOT TYPE, and this is not
    optional: an extreme low-angle shot [...] looming over the viewer» --, o sea
    dos frases que dicen «esto no es opcional» y piden cosas incompatibles. Un
    plano cercano de un movil no puede ser un contrapicado extremo de un
    monolito.

    QUE SE HACE, Y POR QUE ASI. Dos cosas, y ninguna intenta adivinar si la nota
    corrige o sustituye:

    1. VA LA ULTIMA. Antes iba delante del bloque de `reglas/reglas.py`; ahora
       detras, que es la posicion mas fuerte. Es seguro porque se comprobo una a
       una: las cuatro reglas de ambito `prompt_imagen` (hora del dia, luz
       heredada, expresion facial, convencion de manos) no contradicen a ningun
       revisor. No es lo mismo que la hoja de personaje, donde reordenar habria
       roto el otro caso (32).

    2. DICE QUE LO DE ARRIBA ES LA IMAGEN RECHAZADA. Ese es el giro: los 905
       caracteres no se borran -- borrarlos obligaria a clasificar la nota, y
       clasificar mal una correccion («las piernas atraviesan la mesa,
       arreglalo») dejaria el plano sin ninguna descripcion --, pero dejan de
       leerse como el encargo y pasan a leerse como el diagnostico. El peso
       sigue estando; lo que cambia es a favor de quien.

    Y por eso la ultima frase importa tanto como la primera: lo que la nota NO
    menciona se queda como estaba. Sin ella, una correccion de dos palabras
    borraria el plano entero.
    """
    return ("The reviewer looked at the previous image of this exact shot and "
            "REJECTED it. Everything described above -- the scene, the action, "
            "the framing and the SHOT TYPE line -- is the description that "
            "produced the image that was rejected. The reviewer's note below is "
            "the HIGHEST PRIORITY instruction in this entire prompt and it "
            "OVERRIDES anything above it that disagrees with it, including the "
            "subject, the objects on screen, the composition and the shot type: "
            "where they disagree, draw what the note says and drop what the "
            "description said. Whatever the note does not mention stays exactly "
            f"as described above. The reviewer's note is: {feedback}.")


#: LO QUE ALGUIEN SE PONE PARA TAPARSE LA CARA. En las dos lenguas en que se
#: escribe una hoja -- el canal la escribe en castellano y el catalogo la deja en
#: ingles -- y sin tildes, porque se busca sobre el texto normalizado.
#:
#: NO ES SOLO «mascara», y esa fue la advertencia al decidirlo: un casco
#: integral, un pasamontanas, un antifaz o una venda tapan igual, y una hoja
#: escrita con cualquiera de esos choca contra la misma prohibicion.
#:
#: Y SOLO LO QUE SE PONE UNO. Aqui NO entran el reflejo, la sombra, el pelo ni
#: una pantalla delante, y eso es justo la linea que separa los dos casos que el
#: sistema confundia: una mascara es una eleccion de vestuario y un reflejo es
#: un accidente. La descripcion que costo la clausula decia «faces mostly hidden
#: in monitor glare» -- nadie queria eso, se colo la puesta en escena del guion
#: dentro de la descripcion --, asi que ese caso tiene que seguir chocando
#: contra la prohibicion de siempre. Si algun dia hay que reconocer una forma
#: nueva de taparse, se anade AQUI: es una lista de prendas, no una regla.
_TAPACARAS = (
    "mascara", "mascaras", "mascarilla", "mascarillas", "enmascarado",
    "enmascarados", "enmascarada", "enmascaradas",
    "mask", "masks", "masked", "careta", "caretas",
    "antifaz", "antifaces", "pasamontanas", "balaclava", "balaclavas",
    "capirote", "capirotes", "embozo", "embozados", "velo", "veil", "veiled",
    "niqab", "burka", "burqa", "visor", "casco integral", "cascos integrales",
    "full face helmet", "gas mask", "respirator", "venda", "vendas", "vendaje",
    "blindfold", "blindfolded", "face paint", "pintura de cara", "cara pintada",
    "caras pintadas", "guy fawkes", "v de vendetta", "v for vendetta",
)


def tapa_la_cara(*textos):
    """¿Alguno de estos textos pide EXPRESAMENTE una cara tapada? -> bool

    Existe por un caso real (PENDIENTE 32): se escribio en una hoja de personaje
    «grupo de hackers con mascara de anonymous, cara oculta por una mascara
    estilo V de vendetta» y salieron los ocho a cara descubierta, dos veces
    seguidas. No era peso ni mala comprension: era una CONTRADICCION LITERAL. El
    prompt de la hoja termina con «never cover a face with glare, reflection,
    shadow, hair, screens, masks or sunglasses», escrito DETRAS de lo que pide
    el revisor, y el modelo obedece a la ultima -- que ademas va en imperativo.

    Y esa clausula existe por un buen motivo, asi que no se puede borrar: una
    descripcion decia «faces mostly hidden in monitor glare», el modelo dibujo el
    reflejo como una placa blanca sobre los ojos, la hoja se adjunto a nueve
    planos con la orden de copiar esos personajes y no habia cara que copiar --
    asi que cada plano se invento una. Sin cara, una hoja no fija nada.

    Lo que separa los dos casos es si la cara la tapa algo que el personaje SE
    PONE. Una mascara es vestuario y es copiable plano a plano; un reflejo es un
    accidente de luz y no lo es. Por eso `_TAPACARAS` son prendas y no incluye
    ni el brillo ni la sombra: ese caso tiene que seguir chocando contra la
    prohibicion de siempre.

    Cuando la mascara se pide expresamente, la clausula no desaparece: cambia de
    sujeto y pasa a fijar la MASCARA (ver `_prompt_reparto`). La hoja sigue
    fijando algo copiable, que es su unica razon de existir.
    """
    llano = " " + " ".join(medios.normalizar_texto(str(t or ""))
                           for t in textos) + " "
    if not llano.strip():
        return False
    return any(f" {prenda} " in llano for prenda in _TAPACARAS)


def _prompt_reparto(ficha, estilo):
    """Prompt de una hoja de personaje.

    Lleva LA MISMA guia escrita que un plano (ver guia_escrita). Tenia una frase
    de estilo propia y salian en otro dibujo distinto del del video.

    Y lleva la clausula de la cara, que es la razon de existir de una hoja: sin
    cara no fija nada. Paso -- la descripcion del grupo decia «faces mostly hidden
    in monitor glare», y sobre un fondo liso, sin ningun monitor que lo emita, el
    modelo dibujo ese reflejo COMO UNA PLACA BLANCA sobre los ojos. La hoja se
    adjunto a nueve planos con la orden de copiar esos personajes y no habia
    ninguna cara que copiar: cada plano se invento una.
    """
    reglas = medios.motor("reglas/reglas.py")
    lineas = ["Draw a reference cast sheet for an animated documentary."]
    lineas.append("Reference image 1 is a STYLE SHEET: copy the drawing style it "
                  "shows -- line weight, palette, shapes, proportions -- and never "
                  "its content, its framing or its layout.")
    if estilo.get("prompt"):
        lineas.append(f"Style: {estilo['prompt']}.")
    lineas.extend(guia_escrita(estilo))
    # DOS FILAS, y la de arriba son caras grandes. La hoja se adjunta luego a
    # cada plano donde sale ese personaje, y de ella se copia la identidad: con
    # figuras de cuerpo entero, cada cara ocupaba 112x139 px del millon largo de
    # la imagen, y lo que llegaba al plano era la ropa y el pelo. Poner los
    # bustos multiplica por tres o cuatro los pixeles de lo unico que de verdad
    # hay que sostener, sin cambiar ni el numero de imagenes ni el coste.
    lineas.append("Lay the sheet out in two rows on a plain flat background. Top "
                  "row: large head-and-shoulders portraits, one per character, "
                  "taking up most of the height of that row. Bottom row: the same "
                  "characters standing, full body, front view, in the same order. "
                  f"The characters are {ficha['descripcion']}.")
    if not ficha.get("grupo"):
        # UNA hoja de UN personaje: sin decirlo, «the characters are...» con una
        # sola descripcion salio como seis monos distintos (02-09-2026), y la
        # hoja se adjunta para fijar UNA identidad
        lineas.append("This sheet shows exactly ONE character. Every portrait "
                      "and every full-body view is that same character, with "
                      "the same face, hair, clothing and accessories in all of "
                      "them: front view, three-quarter view and profile, never "
                      "six different people.")
    lineas.extend(clausula_de_especie(estilo))
    # El molde manda sobre la descripcion, y hay que decirlo: la descripcion la
    # escribe un modelo y se cuela en ella la puesta en escena del guion. Sin esta
    # frase, «seated at desks crowded with screens» pinta las mesas y los monitores
    # DENTRO de la hoja -- que es lo que paso-- y la hoja deja de ser una hoja.
    lineas.append("Ignore any setting, furniture, props, lighting or action "
                  "mentioned in that description: it describes where these "
                  "characters appear in the film, not what this sheet shows. Draw "
                  "only the characters, evenly lit, on an empty flat background.")
    if ficha.get("feedback"):
        # la nota del revisor sobre ESTA hoja: sin esto se pagaba una hoja
        # nueva con el mismo prompt y salia una variacion de lo mismo
        lineas.append("The reviewer looked at the previous version of this "
                      "sheet and asked for this change, and it is NOT optional "
                      f"-- redesign the characters to satisfy it: "
                      f"{ficha['feedback']}.")
    # LA CLAUSULA DE LA CARA, Y SUS DOS VERSIONES. Va la ultima y en imperativo
    # a proposito -- es lo que sostiene la hoja --, pero escrita DETRAS del
    # feedback contradecia literalmente a quien acababa de pedir mascaras. Asi
    # que cuando la mascara se pide expresamente, la clausula no se calla: sigue
    # exigiendo lo mismo (algo identico y copiable donde va la cara) con la
    # mascara como sujeto. Ver `tapa_la_cara` para el porque entero.
    if tapa_la_cara(ficha.get("descripcion"), ficha.get("feedback")):
        lineas.append("These characters wear something over the face on purpose, "
                      "and that is correct: the covering IS the face of each "
                      "character here. Draw it exactly the same in both rows -- "
                      "same shape, same proportions, same markings, same colours "
                      "-- and clearly different from one character to the next, "
                      "so that every later shot can copy it and get the same "
                      "character back. Never leave the covered area vague, "
                      "shadowed, blurred or blown out by glare: whatever is "
                      "there must be drawn in full detail and be recognisable at "
                      "a glance. Where a face IS visible, draw eyes, eyebrows and "
                      "mouth with a neutral and serious expression.")
    else:
        lineas.append("Every face must be fully visible and unobstructed: draw eyes, "
                      "eyebrows and mouth, with a neutral and serious expression. Never "
                      "cover a face with glare, reflection, shadow, hair, screens, "
                      "masks or sunglasses. The face is what this sheet exists to fix: "
                      "a character drawn without one cannot be kept consistent.")
    if ficha.get("grupo"):
        lineas.append("Show every member of the group side by side, clearly "
                      "different from each other in build, clothes and hair.")
    bloque = reglas.bloque_prompt("reparto")
    if bloque:
        lineas.append(bloque)
    # LO QUE SE PROHIBE AQUI ES ANOTAR LA HOJA, no que el personaje lleve letras.
    # Decia «No text, no letters, no numbers anywhere» y son dos cosas distintas:
    # una hoja de personaje con flechas y rotulitos de «front view» es una hoja
    # estropeada, pero la camiseta de alguien puede poner algo si el estilo lo
    # pide. Ver la regla `texto-en-imagen-permitido-pero-raro`.
    lineas.append("Do not annotate the sheet: no captions, no view labels, no "
                  "arrows, no measurements, no watermarks.")
    return " ".join(lineas)


# ------------------------------------------------------------------- assets



#: Version del reparto de camaras que exige este paso. Tiene que ser la misma que












def _adoptar(nombre, p, firma=None, subcarpetas=("", "escenas", "storyboard", "reparto")):
    """Arte ya aprobado que sirva para ESTE plano, o None.

    Adoptar solo por nombre de fichero es inseguro: los identificadores de escena
    son posicionales, asi que en cuanto el guion cambia, S001 pasa a narrar otra
    cosa y se le sirve la imagen del guion anterior sin que nada lo note. Peor
    aun, si una pasada vieja dejo dos planos con la misma imagen, readoptarlos
    perpetua el duplicado para siempre.

    Por eso se exige que el arte traiga su ficha con la firma con la que se
    genero y que coincida con la de ahora. Sin ficha no se adopta: se genera.
    """
    for base in p["imagenes_previas"] or []:
        for sub in subcarpetas:
            candidata = os.path.join(base, sub, f"{nombre}.png") if sub else \
                os.path.join(base, f"{nombre}.png")
            if not os.path.exists(candidata):
                continue
            if firma is None:
                return candidata
            ficha = medios.leer_json(os.path.splitext(candidata)[0] + ".json", {})
            if ficha.get("firma") == firma:
                return candidata
    return None


def _producir_imagen(nombre, prompt, referencias, destino, p, rehacer=False,
                     tamano=None):
    """Arte adoptado -> cache -> API. Devuelve como se resolvio y el coste.

    'rehacer' es el boton de "esta no me gusta": salta el arte adoptado y la
    cache y paga una imagen nueva, porque con el mismo prompt la cache
    devolveria exactamente la que el humano acaba de rechazar.

    `tamano` es el del motor de imagen ('apaisado' | 'vertical'). Los planos lo
    traen del formato del plan; las hojas de personaje y las piezas van siempre
    apaisadas, que es como se leen mejor como referencia.
    """
    tamano = tamano or "apaisado"
    firma = medios.huella({"prompt": prompt, "calidad": p["calidad"],
                           # el tamano entra en la firma: la misma escena en
                           # vertical es otra imagen, y la cache no puede
                           # devolver la apaisada
                           "tamano": tamano if tamano != "apaisado" else None,
                           "refs": [medios.huella_fichero(r) for r in referencias]})
    cacheada = os.path.join(p["banco_imagenes"], f"{firma}.png")
    # En el modo explicito 'adoptar' el objetivo es no gastar, asi que se acepta
    # arte que solo coincide en nombre. El guardian de planos repetidos sigue
    # vigilando la salida, que es donde se nota si el arte adoptado no vale.
    estricto = p["motor_imagen"] != "adoptar"
    previa = _adoptar(nombre, p, firma if estricto else None)

    if p["motor_imagen"] == "adoptar":
        if not previa:
            raise RuntimeError(f"modo adoptar: no hay arte previo para '{nombre}'")
        medios.copiar(previa, destino)
        return {"origen": "adoptada", "firma": firma, "coste": 0.0,
                "fuente": previa}
    if not rehacer:
        if previa:
            medios.copiar(previa, destino)
            return {"origen": "adoptada", "firma": firma, "coste": 0.0,
                    "fuente": previa}
        if os.path.exists(cacheada):
            medios.copiar(cacheada, destino)
            return {"origen": "cache", "firma": firma, "coste": 0.0}

    imagen = medios.motor("imagen_openai/imagen.py")
    try:
        png, meta = imagen.generar(prompt, referencias, quality=p["calidad"],
                                   tamano=tamano)
    except SystemExit as fallo:
        # el motor esta escrito como CLI y aborta con SystemExit (por ejemplo si
        # falta la clave); dentro de un hilo eso no lo captura nadie y el paso
        # se quedaria colgado en 'ejecutando' sin explicacion
        raise RuntimeError(f"el motor de imagen aborto: {fallo}") from fallo
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as fh:
        fh.write(png)
    medios.copiar(destino, cacheada)
    return {"origen": "generada", "firma": firma, "coste": meta["coste"],
            "segundos": meta["segundos"]}


def _salidas_parciales(plan, resultados, inventario, necesarios, avisar):
    """Lo que devuelve una pasada de SOLO assets.

    Se versionan unicamente las unidades de asset. Los planos no llevan version,
    asi que el grafo sigue sabiendo que faltan en vez de dar el paso por hecho:
    decir "listo" con las escenas sin generar seria mentir sobre el estado.
    """
    salidas = {
        "plan": "plan.json",
        "assets": "assets",
        "dependencias": "dependencias.json",
        "parcial": True,
        "n_escenas": 0,
        "n_escenas_previstas": len(plan["escenas"]),
        # se cuenta lo que ESTA version deja con resultado (incluida la
        # herencia del trabajo sembrado), no el plan entero: decir «50 listos»
        # con las 49 cajas del plan sin construir era mentir sobre la pasada
        "resumen": (f"{len(resultados)} de {len(necesarios)} assets listos, "
                    f"sin planos todavia: apruebalos y genera las "
                    f"{len(plan['escenas'])} escenas"),
    }
    avisar(1.0, salidas["resumen"])
    return {"salidas": salidas, "unidades": dict(resultados),
            "conservadas": [], "dependencias": plan["dependencias"],
            "plan": plan, "todas": resultados, "regeneradas": None,
            "parcial": True}


#: Cuanto se tienen que parecer dos frases para que el dibujo de una valga
#: para la otra. Es un numero BARATO: por debajo no se tira nada ni se
#: repaga nada -- la imagen se queda y se marca OBSOLETA, y quien mira
#: decide si la rehace.
PARECIDO_MINIMO_IMAGEN = 0.6


def _mismo_dicho(uno, otro):
    """Si dos textos son lo mismo dicho, aunque el corte los haya movido.

    Tres varas, de la mas dura a la mas blanda:

      1. la misma frase palabra por palabra;
      2. una DENTRO de la otra -- eso no es el guion cambiando, es el corte:
         un plano que se parte en dos, o dos que se juntan, siguen diciendo
         las mismas palabras;
      3. y si no, cuanto se parecen, que es lo que cubre la preposicion
         corregida y las tres palabras reordenadas.
    """
    if uno == otro:
        return True
    if not uno or not otro:
        return False
    if uno in otro or otro in uno:
        return True
    return difflib.SequenceMatcher(None, uno.split(), otro.split(),
                                   autojunk=False).ratio() >= PARECIDO_MINIMO_IMAGEN


def _recolocar_escenas(carpeta, escenas):
    """Cada dibujo, bajo el numero del plano que dice LO SUYO. -> informe

    POR QUE. El id de un plano es su POSICION: S003 es el tercero y nada
    mas. Y la posicion se reparte de nuevo cada vez que se vuelve a cortar
    la narracion, cosa que pasa con cada voz nueva porque el corte sale de
    las marcas de palabra. El 31-08 un plan de 222 planos paso a 217 al
    regrabar la voz: los dibujos se guardan como `S003.png`, no se movieron,
    y 200 de 225 pasaron a ilustrar la frase de al lado. No se ve venir,
    porque cada plano SIGUE teniendo su imagen; lo unico que cambio es cual.

    `_emparejar_con_previo` ya lo sabia -- su regla 3 empareja por posicion y
    dice, con estas palabras, que asi «el plano NO se da por bueno» -- y el
    bucle que dibuja no se lo preguntaba a el: se lo preguntaba al disco, que
    solo sabe si existe un fichero con ese nombre.

    COMO. Cada ficha guarda la narracion para la que se dibujo. Se busca,
    para cada plano, la imagen escrita para lo que dice hoy, y se la lleva a
    su numero. NO SE TIRA NADA Y NO SE PAGA NADA: la que no reclama nadie se
    queda donde esta, y el plano que se quedo sin la suya sale marcado
    obsoleto en la pantalla de Imagenes para que lo decida quien mira.

    Se mueve en DOS TIEMPOS -- todo a un temporal y luego a su sitio --
    porque los cambios se pisan entre si: S004 va a S003 mientras S005 va a
    S004.
    """
    informe = {"movidas": 0, "obsoletas": []}
    if not os.path.isdir(carpeta):
        return informe

    guardadas = []
    for nombre in sorted(os.listdir(carpeta)):
        if nombre.endswith(".json"):
            ficha = medios.leer_json(os.path.join(carpeta, nombre), {}) or {}
            texto = _texto_clave(ficha)
            if texto:
                guardadas.append([nombre[:-5], texto])

    # DOS VUELTAS, Y EN ESTE ORDEN: primero las que dicen EXACTAMENTE lo mismo
    # y luego las parecidas. En una sola vuelta un plano parecido se lleva la
    # imagen que otro necesitaba palabra por palabra, y el que la tenia exacta
    # se queda sin ella. Es la misma regla, y por el mismo motivo, que las tres
    # vueltas de `_emparejar_con_previo`.
    #
    # Y UNA SOLA VEZ CADA UNA: una frase repetida son dos planos y dos dibujos,
    # asi que si el primero se lleva la imagen el segundo sale obsoleto, que es
    # justo lo que hay que decir.
    quiere = {}
    # UN PLANO QUE NO DICE NADA se queda con lo que tenga debajo. No se puede
    # casar por texto a algo que no tiene texto --una cartela a pantalla
    # completa, por ejemplo--, y darlo por obsoleto seria marcar todos los
    # rotulos de capitulo del video en cuanto se toque una coma en otro sitio.
    for escena in escenas:
        if not _texto_clave(escena):
            quiere[escena["id"]] = escena["id"]
    for exacta in (True, False):
        for escena in escenas:
            if escena["id"] in quiere:
                continue
            texto = _texto_clave(escena)
            for par in guardadas:
                if par[1] is None:
                    continue
                if (par[1] == texto if exacta else _mismo_dicho(texto, par[1])):
                    quiere[escena["id"]] = par[0]
                    par[1] = None
                    break
    informe["obsoletas"] = [e["id"] for e in escenas if e["id"] not in quiere]

    mueve = {d: o for d, o in quiere.items() if d != o}
    if not mueve:
        return informe

    tmp = os.path.join(carpeta, "_recolocando")
    os.makedirs(tmp, exist_ok=True)
    por_id = {e["id"]: e for e in escenas}
    for origen in sorted(set(mueve.values())):
        for ext in (".png", ".json"):
            suyo = os.path.join(carpeta, origen + ext)
            if os.path.exists(suyo):
                os.replace(suyo, os.path.join(tmp, origen + ext))
    for destino, origen in sorted(mueve.items()):
        for ext in (".png", ".json"):
            suyo = os.path.join(tmp, origen + ext)
            if os.path.exists(suyo):
                os.replace(suyo, os.path.join(carpeta, destino + ext))
        # LA FICHA SE PONE AL DIA CON SU NUEVO NUMERO. Dentro lleva su `id` y
        # la ruta de su png, y la rejilla los lee: dejarlos con el numero
        # viejo seria apuntar a un fichero que ya no es el suyo. La
        # `narracion` NO se toca: es para lo que se dibujo, y es justo lo que
        # permite volver a encontrarla la proxima vez.
        ficha_json = os.path.join(carpeta, destino + ".json")
        ficha = medios.leer_json(ficha_json, {}) or {}
        if not ficha:
            continue
        ficha["id"] = destino
        if ficha.get("png"):
            ficha["png"] = ficha["png"].replace(origen, destino)
        escena = por_id.get(destino) or {}
        for campo in ("t_in", "t_out"):
            if campo in escena:
                ficha[campo] = escena[campo]
        ficha["recolocada_de"] = origen
        medios.escribir_json(ficha_json, ficha)
    try:
        os.rmdir(tmp)
    except OSError:
        pass  # si queda algo dentro se ve mirando; no se borra a ciegas
    informe["movidas"] = len(mueve)
    return informe

def _generar_escenas(plan, dirs, p, trabajo, toca, unidades, resultados, avisar,
                     forzar=False, notas_repaso=None, proyecto=None):
    """Genera los planos y devuelve el coste. En fila o en cadenas paralelas.

    Por que cadenas y no planos sueltos
    -----------------------------------
    A cada plano se le adjuntan los DOS anteriores como referencia de
    continuidad, que es lo que impide que la paleta y el grosor de linea deriven
    de un plano al siguiente. Eso convierte la generacion en una cadena: el plano
    N necesita que N-1 y N-2 existan. Lanzarlos todos a la vez rompe justo lo que
    esa referencia sostiene.

    Lo que si son independientes son las SECUENCIAS: entre dos sets distintos hay
    un corte de todas formas. Asi que se agrupa por set, cada grupo se genera en
    fila (conservando su continuidad) y los grupos corren a la vez. Con seis sets
    eso es seis veces mas rapido sin tocar la regla.

    Y la continuidad NO depende de esto: un plano se apoya siempre en los dos
    anteriores de su propio sitio, con cualquier valor de 'cadenas', porque el
    filtro vive dentro de continuidad_de. Es lo que convierte esto en una palanca
    de velocidad pura: el mismo plan da las mismas imagenes vaya en fila o en
    nueve cadenas a la vez.

    Cuantas: por defecto, UNA POR SITIO. El grafo de dependencias no permite mas
    -- dentro de un sitio los planos van en fila-- ni tiene sentido menos. Un
    video de 35 planos en nueve sitios pasa de 35 llamadas en fila a un camino
    critico de 6, que es el sitio con mas planos. No se pone un numero porque el
    numero bueno lo dice cada video: son sus sitios.
    """
    escenas = plan["escenas"]
    # LO PRIMERO: cada dibujo bajo el numero del plano que dice lo suyo. Va
    # aqui y no dentro de la cadena porque es un baile de ficheros entre
    # numeros -- S004 a S003 mientras S005 va a S004 -- y dos cadenas a la vez
    # se lo pisarian.
    recolocadas = _recolocar_escenas(dirs["escenas"], escenas)
    if recolocadas["movidas"]:
        avisar(0.34, "%d imagenes recolocadas: el corte les cambio el numero"
                     % recolocadas["movidas"], None)
    total = len(escenas)
    cadenas = _cuantas_cadenas(p, escenas)
    orden = {escena["id"]: indice for indice, escena in enumerate(escenas)}

    # el candado protege lo que comparten las cadenas: el diccionario de
    # resultados, el coste acumulado y el contador de avance
    cerrojo = threading.Lock()
    estado = {"coste": 0.0, "hechas": 0}

    def anunciar(sid):
        with cerrojo:
            estado["hechas"] += 1
            hechas = estado["hechas"]
        avisar(0.35 + 0.6 * (hechas / max(1, total)),
               f"plano {sid} · {hechas} de {total}", (hechas, total))

    def una_cadena(grupo):
        """Los planos de un set, en fila y arrastrando su propia continuidad."""
        previas = {}
        orden_cadena = []
        for escena in grupo:
            sid = escena["id"]
            uid = f"escena:{sid}"
            destino = os.path.join(dirs["escenas"], f"{sid}.png")
            ficha_json = os.path.join(dirs["escenas"], f"{sid}.json")
            anunciar(sid)

            # Una cartela no deja PNG, asi que su ficha en disco es lo unico
            # que dice que ya estaba hecha. Y tiene que ser una ficha DE
            # CARTELA: un plano que en la pasada anterior era la mitad copiada
            # de otro y hoy es el REMATE sobre fondo solido tiene ahi una ficha
            # que anuncia un PNG, y la rejilla se la creeria. Conservar solo
            # vale si lo conservado es de la misma clase que lo que toca.
            if cartelas.sin_imagen(escena):
                guardada_previa = medios.leer_json(ficha_json, {}) or {}
                hecho = bool(guardada_previa) and not guardada_previa.get("png")
            else:
                hecho = os.path.exists(destino)
            # UNA IMAGEN QUE YA EXISTE SE QUEDA. Solo se rehace si alguien la
            # ha pedido -- por su unidad, o con el «rehacer» de la pantalla.
            #
            # Antes la condicion era `not toca(uid)`, y con `unidades=None`
            # --que es lo que manda una tanda normal-- `toca` da True para
            # todo: o sea que cualquier pasada volvia a entrar a generar los
            # 216 planos. No se pagaban por la cache del banco, pero solo
            # mientras el prompt no cambiara ni una coma; corregir una
            # preposicion en un bloque cambiaba el prompt de sus planos y los
            # repagaba.
            #
            # LA REGLA LA PUSO EL CANAL EL 27-08: un cambio en
            # el audio NUNCA deja imagenes pendientes. Se rehacen los
            # subtitulos, las cartelas y la sincronia, y las imagenes se
            # quedan. Si una deja de cuadrar con lo que se dice, eso se ve
            # MIRANDO el video en el previsualizador y se pide por su feedback,
            # que es un gesto con su cuenta y su precio delante.
            # QUIEN SE REHACE. Si vienen unidades, SOLO ELLAS: `forzar` dice
            # entonces «y ademas saltate la cache», no «y ademas todos».
            #
            # Estaba puesto como `forzar or ...`, y `forzar` es el `rehacer`
            # de la pantalla, que es global. O sea que pulsar «Regenerar
            # imagen» en UNA tarjeta redibujaba las 225: visto el 01-09, 21
            # planos y 0,84 USD antes de cortarlo, y con S001 a S003 --que se
            # acababan de dejar bien-- entre los pisados. Rehacer una cosa
            # rehace ESA cosa.
            #
            # Sin unidades sigue valiendo para todo: ese es el boton de
            # «redibujar el video entero», y ahi si lo has pedido.
            pedida = (uid in set(unidades) if unidades is not None
                      else bool(forzar))
            if hecho and not pedida:
                if not _sin_imagen(escena):
                    previas[sid] = destino
                    orden_cadena.append(sid)
                ficha = medios.leer_json(ficha_json, {}) or {
                    "tipo": "escena", "png": os.path.relpath(destino, trabajo),
                    "origen": "conservado"}
                ficha["origen"] = "conservado"
                # OBSOLETA NO ES PENDIENTE. Si lo que hay dibujado no es de
                # lo que se dice aqui, la imagen se queda igualmente: no se
                # tira, no se rehace sola y no se cobra. Se DICE, y la
                # pantalla de Imagenes la marca para que lo decida quien
                # mira, que es quien sabe si el dibujo sigue valiendo.
                #
                # Y EL DESCARTE SE RECUERDA CONTRA UN TEXTO, no como un si o
                # un no. Quitar la tarjeta es decir «este dibujo me vale para
                # lo que dice AHORA»; guardarlo como un booleano haria que la
                # proxima vez que cambiara la frase la imagen siguiera
                # aprobada, que es justo lo que no se quiere.
                ficha["obsoleta"] = (
                    not _mismo_dicho(_texto_clave(ficha), _texto_clave(escena))
                    and (medios.normalizar_texto(ficha.get("vale_para") or "")
                         != _texto_clave(escena)))
                with cerrojo:
                    resultados[uid] = ficha
                continue

            if cartelas.sin_imagen(escena):
                # UNA CARTELA DE FONDO NEGRO NO DEJA IMAGEN, y es deliberado.
                #
                # Aqui se rasterizaba a PNG para que la rejilla de planos
                # tuviera algo que enseñar. El problema: como se ve una cartela
                # depende del grafismo (la paleta y el set de diseño), que vive
                # en los params de ROTULOS -- y este paso no los ve. O sea que
                # la rejilla enseñaba una cartela dibujada con unos colores y el
                # video llevaba otra. Es justo la clase de mentira que las
                # muestras de este sistema existen para no contar.
                #
                # Ahora no hay fichero: la pantalla pide el SVG al servidor (que
                # si ve el grafismo) y p7 dibuja el del video con la misma
                # llamada. Un solo sitio, siempre al dia, y una rasterizacion
                # menos por cartela en cada tanda.
                meta = {"origen": "cartela", "coste": 0.0,
                        "plantilla": escena["cartela"].get("plantilla")}
                prompt = ""
                referencias = []
            elif escena.get("sigue_a"):
                # LA SEGUNDA MITAD DE UN PLANO QUE DURA EL DOBLE. Es la misma
                # imagen: no se genera ni se paga, se copia. Ver
                # _estirar_cabeceras -- lo que dura mas es el plano, no el
                # rotulo pegado sobre otro dibujo.
                fuente = os.path.join(dirs["escenas"],
                                      f"{escena['sigue_a']}.png")
                if not os.path.exists(fuente):
                    raise RuntimeError(f"{sid}: sigue a {escena['sigue_a']} y esa "
                                       f"imagen no esta generada todavia")
                medios.copiar(fuente, destino)
                meta = {"origen": "sigue", "coste": 0.0,
                        "sigue_a": escena["sigue_a"]}
                prompt = ""
                referencias = []
            elif escena.get("componente"):
                fuente = os.path.join(dirs["componentes"],
                                      f"{escena['componente']}.png")
                if not os.path.exists(fuente):
                    raise RuntimeError(f"{sid}: falta el componente "
                                       f"{escena['componente']}")
                medios.copiar(fuente, destino)
                meta = {"origen": "componente", "coste": 0.0}
                prompt = ""
                referencias = []
            else:
                # La cadena manda siempre, tambien en fila: es el orden DEL PLAN
                # dentro de ese sitio, y comparando ids no lo era -- los ids se
                # heredan del plan anterior y dejan de ir en orden --. Asi los dos
                # caminos dan exactamente las mismas referencias.
                referencias = _referencias_escena(
                    escena, plan, dirs, p, dirs["cache"], previas,
                    anteriores=orden_cadena, notas=notas_repaso)
                nota_texto = _texto_feedback(
                    _ajustes_unidad(p, uid).get("feedback"))
                escena_final = escena
                corregido = None
                # EL CORRECTOR, solo cuando hay nota y alguien ha pedido rehacer
                # ESTE plano: es una llamada al CLI por imagen, y una tanda
                # entera de planos sucios no la merece. Con nota y a mano si:
                # es la diferencia entre «adjunta lo de siempre» y «mira las
                # imagenes y adjunta lo que la nota pide» (pasos/corrector.py).
                if nota_texto and pedida and _corrector_activo(p):
                    corregido = _corregir_con_agente(
                        escena, plan, dirs, p, trabajo, notas_repaso, proyecto,
                        nota_texto, avisar)
                if corregido and not corregido.get("error"):
                    escena_final = dict(escena, prompt=corregido["escena"],
                                        personajes=corregido["personajes"])
                    # las mismas clases y las mismas frases que en la primera
                    # generacion (frase_de_referencia); el corrector solo
                    # elige cuales y anade el detalle
                    motor_imagen = medios.motor("imagen_openai/imagen.py")
                    referencias = (
                        list(_referencias_estilo(p, dirs["cache"], escena_final))
                        + [dict(r, ruta=motor_imagen.normalizar(r["ruta"],
                                                                dirs["cache"]))
                           for r in corregido["referencias"]])
                prompt = _prompt_completo(
                    escena_final, referencias, p["estilo"],
                    feedback=nota_texto,
                    idioma=plan.get("idioma") or "",
                    formato=plan.get("formato") or "",
                    fichas_reparto=plan.get("assets"))
                # SI EL HUMANO HA PEDIDO REHACERLA, rehacerla de verdad: ni el
                # arte adoptado ni la cache valen, porque con el mismo prompt la
                # cache devuelve exactamente la que acaba de rechazar.
                #
                # Y SOLO SI LO HA PEDIDO. Aqui ponia `forzar or unidades is not
                # None`, o sea que bastaba con que la tanda fuera dirigida a
                # unidades concretas -- que es justo lo que hace REPARAR lo que
                # se ha quedado sucio, sin que nadie rechace nada. Con eso, cada
                # reparacion volvia a pagar imagenes identicas: medido el 31-08,
                # 14 planos con la firma SIN cambiar y su PNG en el banco,
                # 0,55 $. Es el ultimo resto de la deduccion vieja que el
                # comentario de `_generar_escenas` da por retirada.
                meta = _producir_imagen(sid, prompt,
                                        [r["ruta"] for r in referencias],
                                        destino, p,
                                        # y para la que SI se ha pedido,
                                        # saltarse la cache: con el mismo
                                        # prompt devolveria la que se acaba de
                                        # rechazar
                                        rehacer=(pedida and forzar
                                                 and os.path.exists(destino)),
                                        # al tamano del formato del video: un
                                        # plano vertical se PIDE vertical, no
                                        # se recorta de uno apaisado
                                        tamano=p2_brief.comun.ficha_formato(
                                            plan.get("formato"))["tamano_imagen"])
                if corregido:
                    meta = dict(meta, corrector={
                        k: corregido.get(k) for k in
                        ("alcance", "personajes", "escena", "referencias",
                         "porque", "error", "modelo", "esfuerzo", "segundos")})
            # Una cartela NO entra en la continuidad: las referencias de
            # continuidad existen para que la paleta y el grosor de linea no
            # deriven de un plano al siguiente, y pasarle al generador una
            # pantalla negra con letras como «asi va este video» es justo lo
            # contrario de lo que hacen. Un fotograma de un mapa REAL, menos
            # todavia: es la unica imagen del video que no esta dibujada.
            if not _sin_imagen(escena):
                previas[sid] = destino
                orden_cadena.append(sid)
            ficha = {"tipo": "escena", "id": sid,
                     # sin 'png' si es cartela: no hay fichero, y anunciar uno
                     # que no existe deja la rejilla con un hueco roto
                     **({} if cartelas.sin_imagen(escena)
                        else {"png": os.path.relpath(destino, trabajo)}),
                     "cartela": (escena.get("cartela") or {}).get("plantilla"),
                     "narracion": escena["narracion"],
                     "t_in": escena["t_in"], "t_out": escena["t_out"],
                     "set": escena.get("set"),
                     "componente": escena.get("componente"),
                     "personajes": escena.get("personajes"),
                     "zoom": escena.get("zoom"),
                     "assets": plan["dependencias"].get(uid, []),
                     "prompt": prompt,
                     "referencias": [{"papel": r["papel"], "ruta": r["ruta"]}
                                     for r in referencias], **meta}
            medios.escribir_json(ficha_json, ficha)
            with cerrojo:
                resultados[uid] = ficha
                estado["coste"] += float(meta.get("coste") or 0.0)

    # En fila tambien se va por grupos: es el MISMO reparto, un hilo detras de
    # otro. Asi «en fila» y «a la vez» dejan de ser dos caminos distintos con dos
    # ordenes distintos, y la unica diferencia entre ellos es el reloj.
    grupos = _cadenas_por_set(escenas, orden)
    if cadenas <= 1:
        for grupo in grupos:
            una_cadena(grupo)
        return estado["coste"]

    avisar(0.34, f"{len(grupos)} cadenas de planos, {cadenas} a la vez")
    # Un fallo dentro de una cadena tiene que salir del paso, no quedarse
    # tragado en su hilo: se recoge el resultado de cada una para que la
    # excepcion vuelva a levantarse aqui.
    with ThreadPoolExecutor(max_workers=cadenas) as pool:
        for tarea in [pool.submit(una_cadena, g) for g in grupos]:
            tarea.result()
    return estado["coste"]


#: Tope de llamadas simultaneas a la API de imagen. No es una regla del montaje
#: sino del OTRO LADO, y estaba puesto en 12 mientras el otro lado decia 5.
#:
#: El limite que salta de verdad es de imagenes de entrada por minuto, y cada
#: plano manda entre 8 y 14 adjuntos. Con una llamada de unos 25 s, un cubo de
#: 5 por minuto admite ~2 llamadas en vuelo: mas hilos no generan mas imagenes,
#: generan 429. Se deja en 4 -- algo de holgura por si el limite de la
#: organizacion sube, que el motor detecta solo leyendo las cabeceras -- y quien
#: manda de verdad sobre el ritmo es el cubo de imagen.py, no este numero.
#:
#: Y si, esto reduce el paralelismo que se gano montando las cadenas. Sin
#: adornos: con un techo de 5 llamadas/minuto esa ganancia no existia. Lo que
#: hacian las cadenas de la sexta a la novena era chocar contra el limite.
MAX_CADENAS = 4


def _cuantas_cadenas(p, escenas):
    """Cuantas cadenas correr a la vez: por defecto, una por sitio, con tope.

    0 (por defecto) = automatico, 1 = en fila, N = tope de N. El automatico mira
    las dos restricciones y se queda con la mas estrecha: el paralelismo que
    admite el MONTAJE son los sitios -- dentro de un sitio los planos van en
    fila porque cada uno se apoya en el anterior --, y el que admite la API es
    MAX_CADENAS. Antes solo miraba la primera, que es la que no manda.
    """
    pedidas = int(p.get("cadenas") or 0)
    if pedidas > 0:
        return pedidas
    sitios = {escena.get("set") or "\x00sin-set" for escena in escenas}
    return max(1, min(len(sitios), MAX_CADENAS))


def _cadenas_por_set(escenas, orden):
    """Los planos agrupados por set, cada grupo en el orden del plan.

    Los planos sin set (componentes: mapas, cabeceras) no tienen continuidad que
    conservar -- se copian de un fichero ya hecho -- asi que van todos juntos.
    Los grupos salen ordenados de mas largo a mas corto para que el reparto entre
    hilos no deje uno solo trabajando al final.
    """
    grupos = {}
    for escena in escenas:
        clave = escena.get("set") or "\x00sin-set"
        grupos.setdefault(clave, []).append(escena)
    for grupo in grupos.values():
        grupo.sort(key=lambda e: orden.get(e["id"], 0))
    return sorted(grupos.values(), key=len, reverse=True)


def _planos_repetidos(resultados, trabajo, copiados=()):
    """Grupos de escenas que han acabado con un fichero identico.

    Vale la pena comprobarlo aunque el prompt ya lleve la narracion: que dos
    planos compartan imagen es un fallo que en la UI se ve como 'repetimos
    mucho' y que en disco es un byte a byte identico. Callarlo hasta que alguien
    lo note a ojo sale mas caro que abortar aqui.

    LO QUE BUSCA ES UN FALLO CONCRETO: dos prompts que salieron identicos y una
    cache que devolvio el mismo fichero. Asi que lo que comparte imagen A
    PROPOSITO no cuenta, y son dos casos:

      la cartela        no tiene prompt ni pasa por la cache; dos cartelas
                        iguales serian dos textos iguales, que se ve en la
                        rejilla y no justifica tumbar una tanda ya pagada.
      la CONTINUACION   la segunda mitad de una toma que dura mas es la MISMA
                        imagen copiada: misma imagen, zoom partido, sin
                        transicion en medio. Es byte a byte identica porque
                        tiene que serlo.

    El segundo caso salio el 22-08 y es una leccion de las buenas: hasta
    entonces la continuacion se quedaba con su imagen VIEJA, o sea que NO
    coincidia con su hogar y este guardian no la veia. Al arreglar la copia, la
    tanda se cayo en el ultimo paso -- «S013 = S014» -- despues de generar.
    **Un guardian calibrado sobre un fallo aprende a dar por bueno ese fallo**:
    lo que lo mantenia callado no era su criterio, era el bug.

    Quien dice quien es continuacion es el PLAN (`copiados`), NO la ficha en
    disco. Y esto no es prudencia: al RETOMAR una tanda, un plano que ya tiene
    su imagen se conserva y su ficha pasa a decir `origen: "conservado"`, con lo
    que el rastro de por que compartia imagen se pierde. Con el plan delante,
    reanudar da lo mismo que empezar.
    """
    copiados = set(copiados or ())
    porhash = {}
    for uid, ficha in resultados.items():
        if ficha.get("tipo") != "escena" or not ficha.get("png"):
            continue
        sid = ficha.get("id") or str(uid).split(":", 1)[-1]
        if ficha.get("origen") in ("cartela", "sigue") \
                or sid in copiados or ficha.get("sigue_a"):
            continue
        ruta = os.path.join(trabajo, ficha["png"])
        if not os.path.exists(ruta):
            continue
        porhash.setdefault(medios.huella_fichero(ruta), []).append(sid)
    return [sorted(ids) for ids in porhash.values() if len(ids) > 1]




# Cuantas imagenes de estilo se adjuntan. Antes estaba clavado en 2 y descartaba
# en silencio el resto de la lista.
#
# MINIMO 3: con una o dos, el generador copia esa escena concreta en vez de
# quedarse con el estilo. Hacen falta varias situaciones distintas para que lo
# comun entre ellas (el trazo, la paleta, la forma de los personajes) sea lo
# unico que pueda imitar.
#
# MAXIMO 8, y no es arbitrario: a cada escena se le adjuntan ademas las hojas
# de reparto que toquen (hasta 3) y los dos planos
# anteriores para continuidad (2). Con 8 de estilo se llega a 14 imagenes por
# llamada, cerca del limite practico de la API, y cada una cuesta tokens de
# entrada y segundos. Pasado ese punto el estilo tambien empieza a competir con
# ellas por la atencion del modelo, que es justo lo que no interesa.
MIN_REFERENCIAS_ESTILO = 3
#: CUANTAS ENTRAN EN LA LAMINA DE RESPALDO que viaja en el prompt de cada
#: imagen. Ocho, y su limite no es economico sino fisico: la lamina es un pliego
#: de tamano fijo, asi que con ocho cada foto ocupa ~512x341 y con dieciseis
#: bajaria a 384x256 -- a partir de ahi deja de servir como referencia de trazo.
#:
#: DE RESPALDO porque en cuanto el moodboard esta aprobado la lamina se hace con
#: las laminas DIBUJADAS y no con los fotogramas (ver `_referencias_estilo`).
MAX_REFERENCIAS_ESTILO = 8

#: CUANTOS FOTOGRAMAS SE ELIGEN. Muchos mas de los que caben en esa lamina, y no
#: es un descuido: los fotogramas tienen DOS oficios y ninguno de los dos los
#: manda en cuadricula.
#:
#:   1. escribir la GUIA DE ESTILO. `estilo.generar_guia` se los da al CLI como
#:      ficheros sueltos y el los abre uno a uno, a tamano completo, con su
#:      herramienta de lectura. Una sola llamada, por SUSCRIPCION.
#:   2. dibujar el MOODBOARD, que es lo que despues se compone en el tile que si
#:      viaja en cada prompt.
#:
#:   La cuadricula viene DESPUES, y se hace con lo dibujado.
#:
#: O sea que subir este numero mejora la guia y el moodboard y **no toca la
#: factura por imagen**. Es el caso claro de algo que se paga una vez por canal
#: y se reutiliza en todos sus videos, que es como lo planteo el canal el 22-08.
REFERENCIAS_A_ELEGIR = 24


def _exigir_catalogo(catalogo):
    """Aborta ANTES de gastar si el catalogo no trae ni sitios ni reparto.

    Sin catalogo el paso NO fallaba: degradaba en silencio, que es el fallo que
    mas caro ha salido en este sistema. Lo que pasaba de verdad:

      - `_asignar_sets` dejaba `set=None` en los 174 planos,
      - `_asignar_camaras` arranca con `if not escena.get("set"): continue`, o
        sea que no se ejecutaba ni una vez y todos los planos salian sin angulo
        asignado pese a que la maquinaria de no repetir encuadre existe,
      - sin reparto no se generaba ninguna hoja de personaje, asi que cada plano
        se inventaba la cara y el hijo acababa dibujado donde iba el padre,
      - y el prompt se quedaba en la frase narrada, con lo cual lo unico
        concreto que le llegaba al modelo eran las dos imagenes del plano
        anterior: devolvia el plano anterior con un cambio pequeno.

    Y encima costaba dinero: aquella tanda fueron 10 $ de imagenes para tirar.
    """
    if (catalogo.get("sets") or catalogo.get("reparto")):
        return
    raise RuntimeError(
        "este paso necesita el catalogo visual y esta vacio. El catalogo dice "
        "QUIEN sale (con nombre y descripcion fija, que es lo unico que impide "
        "que un personaje cambie de cara entre planos), DONDE ocurre cada tramo "
        "y con que TONO. Sin el, los planos salen sin sitio y sin encuadre "
        "asignado, y cada imagen acaba siendo la anterior con un retoque. "
        "Pulsa «Construir escenarios» en Video: de ahi salen, leyendo el guion, "
        "los sitios y el reparto que necesita este paso.")






def _exigir_estilo(p):
    """Aborta ANTES de gastar si no hay ninguna imagen de estilo utilizable.

    Es la comprobacion que faltaba: sin referencias, la primera escena llega al
    generador sin adjuntos y la API contesta un 400 sobre tipos de contenido que
    no dice nada de lo que pasa de verdad, que es que falta una entrada. Y para
    entonces ya se ha corrido medio paso.

    Solo se exige en el modo que genera imagenes: 'adoptar' reutiliza arte ya
    aprobado y no llama a nadie.
    """
    if p.get("motor_imagen") == "adoptar":
        return
    rutas = (p.get("estilo") or {}).get("referencias") or []
    # `reubicar`: el proyecto pudo escribirse en otra maquina y los ficheros
    # seguir estando, en el banco de ahora (ver medios.reubicar)
    existen = [r for r in medios.reubicar_todas(rutas) if os.path.exists(r)]
    if existen:
        # Y la guia escrita, que desde ahora es lo unico que describe ESTE video
        # con palabras: el prompt de estilo cableado se quito porque describia un
        # dibujo generico igual para todos los proyectos, y callado. Sin guia, una
        # hoja de personaje se pediria solo con la lamina.
        guia = (p.get("estilo") or {}).get("guia")
        tiene = bool(guia.get("guia")) if isinstance(guia, dict) else bool(guia)
        if not tiene and not (p.get("estilo") or {}).get("prompt"):
            raise RuntimeError(
                "hay imagenes de estilo pero no hay guia escrita, y sin ella las "
                "hojas de personaje y los planos se piden sin decir con palabras "
                "como se dibuja este video. Escribela en la pestana de Video, en "
                "«Estilo grafico»: se saca de las mismas imagenes que ya has "
                "elegido y no cuesta ninguna imagen.")
        return
    if rutas:
        raise RuntimeError(
            "ninguna de las imagenes de estilo existe en el disco del servidor: "
            + ", ".join(str(r) for r in rutas[:5])
            + ". Vuelve a elegirlas en la pestana de Video.")
    raise RuntimeError(
        "este paso necesita al menos una imagen de estilo y no hay ninguna. "
        "Son las que le dicen al generador COMO dibujar (trazo, paleta, forma de "
        "los personajes); el prompt de estilo solo no basta. Sacalas de un video "
        "con el boton de extraer estilo, o apunta a fotogramas que ya tengas.")


#: Lado de la lamina de estilo. La misma proporcion en la que se generan los
#: planos: una lamina cuadrada en un pipeline 3:2 invita a componer en cuadrado.
LAMINA = TAMANO


def _lamina_estilo(rutas, destino):
    """Monta las referencias de estilo en UNA sola imagen en cuadricula.

    Por que: la entrada es el grueso de la factura. Cada plano se llevaba las 8
    laminas sueltas, unos 6.700 tokens de ENTRADA por imagen; en una tanda de
    174 planos fueron 1,17 millones de tokens (unos 9,4 $) contra 1 $ de
    imagenes generadas. Ocho imagenes en una sola dejan esa parte en un octavo.

    Sin texto NI separadores marcados, a proposito. Lo que se busca es que el
    modelo lea una hoja de referencia, no una composicion que reproducir, y
    cualquier rejilla dibujada empuja justo a lo contrario. Lo que dice que es
    una hoja va en el prompt (ver _prompt_completo), donde ademas se prohibe
    explicitamente devolver una cuadricula.
    """
    from PIL import Image
    fotos = []
    for ruta in rutas:
        try:
            fotos.append(Image.open(ruta).convert("RGB"))
        except Exception:                      # noqa: BLE001  una ilegible no tumba el paso
            continue
    if not fotos:
        return None
    columnas = int(math.ceil(math.sqrt(len(fotos))))
    filas = int(math.ceil(len(fotos) / columnas))
    ancho, alto = LAMINA[0] // columnas, LAMINA[1] // filas
    hoja = Image.new("RGB", (ancho * columnas, alto * filas), (255, 255, 255))
    for indice, foto in enumerate(fotos):
        copia = foto.copy()
        copia.thumbnail((ancho, alto), Image.LANCZOS)
        x = (indice % columnas) * ancho + (ancho - copia.width) // 2
        y = (indice // columnas) * alto + (alto - copia.height) // 2
        hoja.paste(copia, (x, y))
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    hoja.save(destino, "PNG")
    return destino


def _referencias_estilo(p, cache, escena=None):
    """La referencia de estilo de un plano: el moodboard si lo hay, si no los
    fotogramas.

    El moodboard manda cuando esta APROBADO, y solo entonces: son laminas
    dibujadas por el mismo modelo que luego las imita, asi que hasta que una
    persona las ha mirado no entran en produccion. Se le manda el tile de los
    ejes que le tocan a ESTE plano -- una cara y unos cuerpos si salen personajes,
    un interior si hay sitio --, y sigue siendo UNA sola imagen: lo que cambia no
    es cuantas referencias van, es cuales.
    """
    imagen = medios.motor("imagen_openai/imagen.py")
    rutas = [r for r in medios.reubicar_todas(p["estilo"].get("referencias"))
             if os.path.exists(r)]
    if rutas and escena is not None:
        tile = moodboard.tile_para(escena, rutas, cache)
        if tile:
            return [{"papel": "lamina", "ruta": imagen.normalizar(tile, cache),
                     "cuantas": len(moodboard.ejes_de_plano(escena)),
                     "moodboard": True}]
    rutas = rutas[:MAX_REFERENCIAS_ESTILO]

    # Siempre que haya mas de una. No es una opcion: mandar ocho imagenes
    # sueltas cuesta ocho veces mas por cada plano y no aporta nada que la
    # lamina no tenga. Un mando mas en la pantalla para elegir entre "caro" y
    # "barato a igualdad de resultado" es un mando de mas.
    if len(rutas) > 1:
        # la firma es del CONTENIDO de la lista: cambiar una referencia da otra
        # lamina, y la cache la reconstruye sola
        firma = hashlib.sha1("|".join(sorted(rutas)).encode("utf-8")).hexdigest()[:12]
        destino = os.path.join(cache, f"lamina_estilo_{firma}.png")
        if not os.path.exists(destino):
            destino = _lamina_estilo(rutas, destino)
        if destino and os.path.exists(destino):
            return [{"papel": "lamina", "ruta": imagen.normalizar(destino, cache),
                     "cuantas": len(rutas)}]

    return [{"papel": "estilo", "ruta": imagen.normalizar(ruta, cache)}
            for ruta in rutas]


def _referencias_reales(escena, p):
    """Fotogramas reales aprobados que tocan a esta escena.

    El emparejamiento se aprobo por BLOQUE de guion, y una escena sale de un
    trozo de la narracion, asi que se cruza por texto: si la narracion de la
    escena contiene el fragmento que se marco, esa referencia es suya. Es la
    misma idea que usa la revision de audio para localizar un comentario cuando
    los offsets ya no cuadran, y por el mismo motivo: el texto sobrevive a las
    reediciones, las posiciones no.

    Como mucho UNA por escena. A cada plano ya se le adjuntan hasta 8 imagenes
    de estilo, las hojas de reparto y los dos planos anteriores;
    pasado cierto punto el estilo compite con la geometria por la atencion del
    modelo, y una referencia de mas no compensa.
    """
    narracion = (escena.get("narracion") or "").strip()
    if not narracion:
        return []
    for real in (p.get("referencias_reales") or []):
        if not isinstance(real, dict) or not os.path.exists(real.get("ruta") or ""):
            continue
        fragmento = (real.get("fragmento") or "").strip()
        if fragmento and fragmento in narracion:
            return [real]
    return []


def continuidad_de(escena, anteriores, por_id, cuantos=1):
    """De que planos anteriores se toma la continuidad. Nunca de otro escenario.

    El filtro vive aqui, y no en quien llama, a proposito: asi vale con cualquier
    valor de 'cadenas' y no depende de que nadie se acuerde de agrupar antes.

    Se adjuntaba el plano anterior fuera cual fuera su sitio. En un video real
    eso fueron 27 de 49 referencias: una sucursal bancaria se genero con dos
    planos de la guarida de unos hackers pegados como referencia, y un plano de
    un colegio se apoyaria en el banco de la escena de antes. La imagen manda
    mucho mas que el texto que la acompana: se probo a decirlo con palabras
    ("for visual continuity ONLY") y no basta.

    Y no se pierde nada de lo que la continuidad sostiene -- paleta, grosor de
    linea, luz --, porque eso ya lo sujetan la lamina de estilo y la guia
    escrita, que van en TODOS los planos. Lo unico que aporta de mas es "es la
    misma habitacion", y eso solo vale cuando de verdad lo es.

    LA MARCA `EN OTRO SITIO:` MANDA AQUI TAMBIEN, y hasta el 07-09 no la leia
    nadie mas que el texto del prompt. Un plano que declara su propio sitio se
    quedaba SIN la descripcion del sitio del tramo (`_prompt_visual`) y CON las
    fotos de ese mismo sitio delante, presentadas como «la misma habitacion».
    Medido en video_referencia, que son los dos ejemplos que la instruccion de
    `direccion` tiene escritos como «esto paso de verdad»: S003 («Hoy siguen
    dando para la compra del mes», que se iba a un supermercado actual) recibio
    DOS fotos de la cocina de 1925, y S037 («Argentina lleva decadas en ello»)
    una del Berlin de 1923. La salida de escape existia y estaba anulada por las
    imagenes, que es el lado que gana.

    Va en las dos direcciones y las dos hacen falta:
      · el plano que se va no se apoya en nadie -- lo que hay detras es otro
        sitio, y ninguna foto anterior ensena el suyo;
      · y el que se queda no se apoya en el que se fue -- su PNG es el
        supermercado de hoy, no la cocina del tramo.

    UNA SOLA FOTO, NO DOS (07-09). Aqui ponia `cuantos=2` «porque con una sola
    la paleta deriva», y la paleta la sujetan la lamina y la guia escrita en los
    114 planos que llevaban dos. Lo que dos fotos anaden de verdad es peso: son
    dos imagenes diciendo «esto es lo que hay en esta habitacion» contra los 236
    caracteres de la linea del plano, y de ahi salen los cinco angulos de la
    misma factura.
    """
    if not escena.get("set"):
        return []
    if _en_otro_sitio(escena):
        return []
    mismos = [sid for sid in (anteriores or [])
              if (por_id.get(sid) or {}).get("set") == escena["set"]
              and not _en_otro_sitio(por_id.get(sid))]
    return mismos[-cuantos:] if cuantos else mismos


def _referencias_escena(escena, plan, dirs, p, cache, hechas, anteriores=None,
                        notas=None):
    """Estilo, estructura, reparto y continuidad, en ese orden fijo.

    'anteriores' son los planos de los que se toma la continuidad. Sin ella se
    usan los dos que van antes en el plan, que es el comportamiento de siempre.
    Al generar en cadenas paralelas se pasa la lista de LA CADENA: si no, cada
    plano se apoyaria en el fichero que otra cadena acabara de dejar en disco, y
    el resultado dependeria de quien llegase antes. Un pipeline que da imagenes
    distintas segun el orden de los hilos deja de ser reproducible.
    """
    imagen = medios.motor("imagen_openai/imagen.py")
    referencias = list(_referencias_estilo(p, cache, escena))
    # La MISMA ficha con la que se dibujo la hoja (`_assets_necesarios`), que es
    # la unica forma de que el plano y la hoja lean lo mismo: leerlo del catalogo
    # por un lado y de los params por otro es como se acaba con una hoja
    # enmascarada y unos planos que la destapan.
    fichas_asset = (plan or {}).get("assets") or {}
    for personaje in escena.get("personajes") or []:
        hoja = os.path.join(dirs["reparto"], f"{personaje}.png")
        if os.path.exists(hoja):
            # SI LA HOJA VA CON LA CARA TAPADA, EL PLANO TIENE QUE SABERLO. Es
            # el otro extremo de PENDIENTE 32: la hoja ya dibuja la mascara,
            # pero el plano recibe «copy their faces exactly as drawn there» y
            # ademas la regla de prompt_imagen le pide declarar la expresion
            # facial de cada personaje. Con las dos cosas delante y sin decir
            # nada, el generador tiene un motivo para destapar. Se dice.
            ficha_q = fichas_asset.get(f"asset:{personaje}") or {}
            referencias.append({"papel": "reparto", "nombre": personaje,
                                "tapada": tapa_la_cara(ficha_q.get("descripcion"),
                                                       ficha_q.get("feedback")),
                                "ruta": imagen.normalizar(hoja, cache)})
    for real in _referencias_reales(escena, p):
        referencias.append({"papel": "parecido", "ruta": imagen.normalizar(real["ruta"], cache),
                            "que_es": real.get("que_es", ""),
                            "rasgos": real.get("rasgos", "")})
    # EL plano anterior DE SU SITIO, uno solo, y ninguno si este plano declara
    # `EN OTRO SITIO:`. Las dos reglas viven en continuidad_de, con su porque.
    if anteriores is None:
        # los que van ANTES EN EL PLAN, no los que tienen un id menor. Los ids se
        # heredan del plan anterior para no volver a pagar los planos que no han
        # cambiado, asi que dejan de ir en orden en cuanto el guion se recorta
        # distinto: un plan real empieza S001, S002, S027, S028, S003... y
        # comparando cadenas, S003 se apoyaba en S001 y S002 -- que en el video
        # van cinco planos antes -- y nunca en S028, que es el que tiene delante.
        orden = [e["id"] for e in plan["escenas"]]
        anteriores = orden[:orden.index(escena["id"])] if escena["id"] in orden else []
    por_id = {e["id"]: e for e in plan["escenas"]}
    for sid in continuidad_de(escena, anteriores, por_id):
        previa = hechas.get(sid) or os.path.join(dirs["escenas"], f"{sid}.png")
        if not os.path.exists(previa):
            continue
        ficha = {"papel": "continuidad", "ruta": imagen.normalizar(previa, cache)}
        # Si el plano anterior ocurre en el MISMO sitio, eso hay que decirlo: es
        # la diferencia entre «otro plano parecido» y «la misma habitacion desde
        # otra camara». Sin decirlo, el generador dibujaba un sitio nuevo cada
        # vez -- mismo estilo, misma paleta, otra sala-- y el espectador no
        # reconocia el lugar de un plano al siguiente. El SHOT TYPE ya fija el
        # angulo; lo que faltaba era decir que el ESPACIO es el mismo.
        anterior = por_id.get(sid) or {}
        if escena.get("set") and anterior.get("set") == escena.get("set"):
            ficha["mismo_set"] = True
            ficha["desde"] = anterior.get("camara") or ""
        referencias.append(ficha)
    # LAS DE LA NOTA VAN LAS ULTIMAS, pegadas al bloque de feedback --que es lo
    # ultimo del prompt y la posicion mas fuerte-- y detras de las de
    # continuidad, que dicen lo contrario que ellas («never their content»).
    # LAS HOJAS DE LOS PERSONAJES QUE NOMBRA LA NOTA. «Esto tiene que ser
    # Curtis, no Jensen» sin la hoja de Curtis delante es pedirle al generador
    # que se invente a Curtis; y con la de Jensen sola --que es la del plano--
    # el resultado seguia siendo Jensen. Van detras de las del plano y se
    # anuncian como lo que son (ver _prompt_completo, papel reparto + de_nota).
    ya = {r.get("nombre") for r in referencias if r.get("papel") == "reparto"}
    for quien in _reparto_en_la_nota(_texto_de_la_nota(escena, p, notas), p, escena):
        hoja = os.path.join(dirs["reparto"], f"{quien}.png")
        if quien in ya or not os.path.exists(hoja):
            continue
        referencias.append({"papel": "reparto", "nombre": quien, "de_nota": True,
                            "ruta": imagen.normalizar(hoja, cache)})
    referencias.extend(_referencias_de_la_nota(escena, dirs, p, cache, notas))
    return referencias


def _notas_del_repaso(proyecto):
    """Las notas del repaso por plano, con sus imagenes ya resueltas a disco.

    -> {plano: [nota, ...]}. Nunca levanta: sin repaso, un diccionario vacio.
    Existe para el camino RAPIDO de «rehacer ESA imagen» de la pantalla de
    Imagenes: manda al paso solo el texto de la nota (`unidades[uid].feedback`),
    y el alcance (retoque / sustituye) y las imagenes que el revisor adjunto se
    quedaban en el repaso sin llegar al generador. Aqui se recuperan por el
    texto, y asi los dos caminos --aplicar el repaso y rehacer una imagen--
    ponen delante del generador exactamente lo mismo.
    """
    if proyecto is None:
        return {}
    try:
        try:
            from . import repaso                                 # noqa: PLC0415
        except ImportError:                                      # pragma: no cover
            import repaso                                        # noqa: PLC0415
        ficha = repaso.leer(proyecto)
        carpeta = repaso.carpeta_imagenes(proyecto)
    except Exception:                                            # noqa: BLE001
        return {}
    salida = {}
    for nota in ficha.get("notas") or []:
        sid = str(nota.get("plano") or "")
        if not sid:
            continue
        copia = dict(nota)
        copia["imagenes"] = [
            (r if os.path.isabs(str(r)) else os.path.join(carpeta, str(r)))
            for r in (nota.get("imagenes") or []) if r]
        salida.setdefault(sid, []).append(copia)
    return salida


def _texto_de_la_nota(escena, p, notas=None):
    """El texto de la nota vigente sobre este plano, venga por donde venga."""
    crudo = _ajustes_unidad(p, f"escena:{escena['id']}").get("feedback")
    return _texto_feedback(crudo)


def _nota_del_repaso_para(sid, texto, notas):
    """La nota del repaso que corresponde a ESTE texto, o la ultima pendiente."""
    candidatas = list((notas or {}).get(str(sid)) or [])
    if not candidatas:
        return {}
    llano = medios.normalizar_texto(texto or "")
    for nota in reversed(candidatas):
        if llano and medios.normalizar_texto(nota.get("texto") or "") == llano:
            return dict(nota, de="repaso")
    pendientes = [n for n in candidatas if n.get("estado") != "aplicado"]
    ultima = (pendientes or candidatas)[-1]
    return dict(ultima, de="repaso")


def _reparto_en_la_nota(texto, p, escena=None):
    """Los personajes del reparto que la nota NOMBRA y el plano no lleva. -> [ids]

    Se busca por nombre, por id (con los guiones como espacios) y por las
    palabras con las que el guion los nombra (`palabras` del catalogo), sobre
    el texto normalizado. Es lo que hace posible «pon a Curtis en vez de a
    Jensen» sin tocar el plan: se adjunta la hoja de Curtis y la nota manda.
    """
    llano = " " + medios.normalizar_texto(texto or "") + " "
    if len(llano.strip()) < 3:
        return []
    en_plano = set((escena or {}).get("personajes") or [])
    reparto = dict((p.get("catalogo") or {}).get("reparto") or {})
    for ficha in (p.get("personajes") or []):
        if isinstance(ficha, dict) and ficha.get("id"):
            reparto.setdefault(medios.identificador(ficha["id"]),
                               {"nombre": ficha.get("nombre"), "palabras": []})
    def claves_de(ident, ficha):
        crudas = [str(ficha.get("nombre") or ""), ident.replace("_", " ")]
        crudas += [str(x) for x in (ficha.get("palabras") or [])]
        return {medios.normalizar_texto(c) for c in crudas
                if len(medios.normalizar_texto(c)) >= 4}

    # lo que ya nombra a alguien DEL PLANO no nombra a otro: «Jensen» en un
    # plano de jensen_joven es el, no el Jensen mayor del reparto
    del_plano = set()
    for ident in en_plano:
        ficha = reparto.get(ident)
        if isinstance(ficha, dict):
            del_plano |= claves_de(ident, ficha)
    salida = []
    for ident, ficha in reparto.items():
        if ident in en_plano or not isinstance(ficha, dict):
            continue
        for llana in claves_de(ident, ficha) - del_plano:
            if (" " + llana + " ") in llano:
                salida.append(ident)
                break
    return salida


# ------------------------------------------------------------------ ejecutar

def planos_hechos(proyecto):
    """Los planos que hay AHORA MISMO en la carpeta de trabajo, con su ficha.

    Existe por dos cosas que pasaban a la vez en la pantalla, y las dos por lo
    mismo: el navegador construia la ruta de la imagen de un plano a partir de
    su ID (`escenas/S028.png`) sin preguntar si esa imagen era suya.

    1. Un plano SIN GENERAR ensenaba una imagen. Los ids son posicionales y se
       heredan entre planes, y `sembrar_trabajo` conserva lo de la version
       anterior: en la carpeta habia un S028.png de OTRO plano que se llamo asi.
       Dos planos distintos salian con la misma imagen y parecia un fallo del
       generador.
    2. Y era, a la vez, la unica forma de ver una tanda avanzar: las unidades no
       se sellan hasta que el paso TERMINA, asi que durante cinco minutos la
       unica senal de que algo se estaba generando eran esos ficheros.

    Aqui se responden las dos sin adivinar: se lee la ficha que cada plano deja
    a su lado al generarse, y quien pregunta puede comparar la narracion con la
    del plan. Si no coinciden, esa imagen es de otro plano y no se ensena.
    """
    # La VERSION ACTIVA es el fondo estable y lo que haya en trabajo/ pisa
    # encima. Las dos hacen falta A LA VEZ, no una u otra:
    #   - al COMPLETAR una tanda el trabajo entero se mueve a la version, y
    #     con solo el trabajo los 49 planos recien pagados desaparecian de la
    #     rejilla justo al terminar (18-08);
    #   - al LANZAR un rehecho, sembrar_trabajo esta COPIANDO la activa al
    #     trabajo (y _refs pesa): con solo el trabajo, la rejilla se vaciaba
    #     tambien durante toda esa ventana (mismo dia, al rehacer un plano).
    # Las rutas relativas coinciden en las dos carpetas (escenas/SXXX.png) y
    # urlDe() en el navegador resuelve contra la activa, como siempre.
    def _leer_escenas(base):
        carpeta = os.path.join(base, "escenas")
        if not os.path.isdir(carpeta):
            return {}
        hechos = {}
        for nombre in os.listdir(carpeta):
            if not nombre.endswith(".png"):
                continue
            sid = nombre[:-len(".png")]
            png = os.path.join(carpeta, nombre)
            ficha = medios.leer_json(os.path.join(carpeta, f"{sid}.json"), {}) or {}
            try:
                sello = int(os.path.getmtime(png))
            except OSError:
                sello = 0
            hechos[sid] = {
                "png": os.path.relpath(png, base).replace(os.sep, "/"),
                # la ruta REAL respecto al proyecto, para usarla tal cual: el
                # navegador deducia la carpeta (trabajo/ o vN/) por el estado
                # del paso, y ese adivinar es lo que vaciaba la rejilla entera
                # al ARRANCAR una tanda -- todas las URL saltaban a trabajo/
                # mientras la siembra aun estaba copiando -- y daba 404 en cada
                # plano no regenerado todavia
                "ruta": os.path.relpath(png, proyecto.raiz).replace(os.sep, "/"),
                "narracion": ficha.get("narracion"),
                "origen": ficha.get("origen"),
                "coste": ficha.get("coste"),
                "prompt": ficha.get("prompt"),
                "sello": sello,
            }
        return hechos

    hechos = {}
    if proyecto.version_activa("assets") is not None:
        hechos.update(_leer_escenas(proyecto.ruta_paso("assets")))
    trabajo = proyecto.ruta_trabajo("assets", crear=False)
    if os.path.isdir(trabajo):
        hechos.update(_leer_escenas(trabajo))
    return hechos


def unidades_pendientes(proyecto, params):
    """Unidades que TODAVIA no estan hechas en la carpeta de trabajo.

    Es lo que hace posible retomar una generacion que se corto a la mitad (sin
    creditos en la API, un corte de red, un Cancelar). El trabajo a medias no se
    pierde: `sembrar_trabajo` no borra nada, asi que los planos ya generados
    siguen ahi. Lo que faltaba era poder decir "sigue por donde ibas" sin volver
    a pagar los que ya estan.

    Devuelve None si no hay nada empezado -- en ese caso retomar es exactamente
    lo mismo que ejecutar entero, y decirlo con None evita un caso especial.
    """
    p = _con_defectos(params)
    trabajo = proyecto.ruta_trabajo("assets", crear=False)
    if not os.path.isdir(trabajo):
        return None
    plan = planificar(proyecto, p)
    dirs = {
        "sets": os.path.join(trabajo, "assets", "sets"),
        "reparto": os.path.join(trabajo, "assets", "reparto"),
        "componentes": os.path.join(trabajo, "assets", "componentes"),
        "cabeceras": os.path.join(trabajo, "assets", "cabeceras"),
        "escenas": os.path.join(trabajo, "escenas"),
    }
    faltan = []
    for uid, ficha in sorted(plan["assets"].items()):
        if not _asset_hecho(uid, ficha, dirs, p):
            faltan.append(uid)
    for escena in plan["escenas"]:
        if not os.path.exists(os.path.join(dirs["escenas"], f"{escena['id']}.png")):
            faltan.append(f"escena:{escena['id']}")
    return faltan


def _asset_hecho(uid, ficha, dirs, p):
    """Si el artefacto de un asset ya esta en la carpeta de trabajo.

    Mira exactamente lo mismo que mira el bucle de ejecutar() para decidir si
    puede conservarlo.
    """
    nombre = ficha["nombre"]
    if ficha["tipo"] == "reparto":
        return os.path.exists(os.path.join(dirs["reparto"], f"{nombre}.png"))
    if ficha["tipo"] in ("mapa", "grafico"):
        return os.path.exists(os.path.join(dirs["componentes"], f"{nombre}.png"))
    if ficha["tipo"] == "cabecera":
        return os.path.exists(os.path.join(dirs["cabeceras"], f"{nombre}.svg"))
    return False


#: Ajustes que este paso admite por invocacion. No son params: describen COMO se
#: corre esta vez, no que produce, asi que no entran en la firma.
def _avisar_conservacion(plan, avisar):
    """Dice EN LA BARRA cuanto se conserva del plan anterior.

    Se dice antes de gastar y con las tres cifras separadas -- lo que sigue
    igual, lo que ha cambiado de encuadre y lo que es nuevo -- porque "174
    planos" sin decir cuantos se rehacen se lee como si se pagaran los 174.
    """
    ficha = plan.get("conservacion") or {}
    if not ficha.get("habia_plan_previo"):
        return
    avisar(None, f"{len(ficha.get('conservados') or [])} planos siguen igual, "
                 f"{len(ficha.get('reasignados') or [])} cambian de contenido y "
                 f"{len(ficha.get('nuevos') or [])} son nuevos")


#: LA VERSION DEL MOTOR QUE CORTA EL PLAN. Se estampa en `plan.json` y la
#: pantalla la compara con esta para decir «este video se corto con reglas de
#: antes».
#:
#: POR QUE HACE FALTA. Las firmas del nucleo miran los PARAMS, asi que un cambio
#: en el MOTOR --como se corta un tramo, como se reparte el zoom, donde nace
#: una banda-- no pone naranja absolutamente nada: los ocho pasos siguen
#: diciendo «listo» mientras el video montado lleva las reglas de anteayer. Se
#: comprobo contra el proyecto del video largo el 22-08-2026, despues de tres
#: cambios de motor seguidos: cero unidades obsoletas.
#:
#: Y NO ENTRA EN NINGUNA FIRMA a proposito. Meterla dejaria obsoletos los
#: renders de TODOS los proyectos a la vez cada vez que se toca una regla, y en
#: la mayoria de los casos ese trabajo no hay que hacerlo -- se hace cuando toca
#: mirar ese video. Lo que hace falta no es un estado nuevo: es que se VEA.
#:
#: SE SUBE A MANO, y esa es la disciplina: quien cambia una regla de
#: planificacion sube el numero, igual que escribe su porque ahi al lado.
#: Un plan sin `motor` es de antes de que esto existiera, y se lee como «viejo».
MOTOR_PLAN = 6

#: Y que cambio en cada version, para que el aviso pueda decir QUE se ha perdido
#: en vez de un numero. Solo lo que cambia el video, no cada retoque.
MOTOR_CAMBIOS = {
    2: "las cabeceras se escriben cuando se dicen y el plano dura el doble si "
       "no caben",
    3: "una cabecera ocupa el tramo en el que se dicen sus palabras, en las dos "
       "direcciones",
    4: "todas las cabeceras van sobre la imagen del plano",
    5: "la cabecera de varios planos remata en fondo solido, y el remate no se "
       "lleva recorrido de camara",
    6: "se retira el fondo solido: una cabecera larga es UNA toma sobre la "
       "misma imagen, de principio a fin",
}

OPCIONES_EJECUCION = ("solo_assets", "replantear", "rehacer", "tipos")


def _anotar_tiempo(paso, arranque, hechas, detalle=None, proyecto=None):
    """El tiempo REAL de una tanda, al historico.

    LOS TRES PASOS MAS LARGOS DEL ESTUDIO no anotaban nada: `assets`, `callouts`
    y `render`. O sea que la unica cifra que la barra tenia para prometer
    cuanto falta era la tabla del primer dia (`estadisticas.INICIALES`), escrita
    a ojo, y no podia mejorar nunca por muchos videos que se hicieran. Es el
    mismo agujero que tenia el paso `voz` hasta el 24-08.

    Y LO QUE SE MIDE ES LO QUE SE HA HECHO, no lo que hay en el proyecto. Aqui
    se anotaba el numero de escenas del PLAN pasara lo que pasara dentro, asi
    que rehacer UNA imagen de un video de 226 dejaba una muestra que dice «226
    escenas en 40 segundos». Con treinta de esas --que es lo que hay hoy, de
    tanto retocar planos sueltos-- la estimacion de una tanda completa se va al
    suelo y la barra promete lo que no puede cumplir.

    Una pasada que no produjo nada no se anota: no dice cuanto cuesta producir,
    y meterla arrastra hacia abajo la media de todas las demas. Lo que cuesta
    la vuelta en si --recorrer los planos conservando-- lo cubre el `suelo`.
    """
    if not int(hechas or 0):
        return        # no produjo nada: no dice cuanto cuesta producir
    try:
        estadisticas.anotar(paso, max(0.01, time.time() - arranque),
                            tamano=int(hechas),
                            proyecto=getattr(proyecto, "id", None),
                            detalle=detalle or {})
    except Exception:                                       # noqa: BLE001
        pass          # medir no puede tumbar una tanda que ya ha salido bien


def ejecutar(proyecto, params, avisar=None, unidades=None, solo_assets=False,
             replantear=False, rehacer=False, tipos=None, previo=None):
    """Construye assets y escenas. Si unidades no es None, solo esas.

    Con solo_assets se para despues de los assets (sets, reparto, mapas y
    cabeceras) y NO se generan los planos. Sirve para aprobar el material base
    antes de gastar una imagen por escena: si un set o una hoja de reparto no
    convence, corregirlo despues obliga a rehacer todos los planos que lo usan.
    Los planos quedan sin version, asi que el paso se ve incompleto -- que es la
    verdad -- y se terminan con "Retomar" o rehaciendo lo obsoleto.

    `tipos` limita esa pasada a esas clases de pieza ('reparto' para las hojas
    de personaje; 'mapa', 'grafico' y 'cabecera' para las piezas) e implica
    solo_assets: la pantalla tiene un boton para los personajes y otro para las
    piezas, y cada uno paga solo lo suyo.

    Con `rehacer` NO se reutiliza NADA: ni el arte adoptado, ni la cache de
    imagenes del banco. Es lo que promete el boton «Rehacer todo», y hasta ahora
    no lo cumplia nadie: forzar se deducia de `unidades is not None`, o sea de
    haber pedido unidades CONCRETAS. Con lo cual pedirlo todo --la peticion mas
    fuerte que hay-- era la unica que no forzaba nada, y quien cambiaba la guia
    de estilo y le daba a «Rehacer todo» se llevaba de vuelta las mismas
    imagenes de antes, sacadas de la cache, con el estilo viejo.
    """
    arranque_paso = time.time()
    p = _con_defectos(params)
    avisar = estadisticas.avisador(avisar)
    tipos = {str(t) for t in (tipos or [])} or None
    if tipos:
        solo_assets = True
    _exigir_estilo(p)
    trabajo = medios.sembrar_trabajo(proyecto, "assets")
    dirs = {
        "sets": os.path.join(trabajo, "assets", "sets"),
        "reparto": os.path.join(trabajo, "assets", "reparto"),
        "componentes": os.path.join(trabajo, "assets", "componentes"),
        "cabeceras": os.path.join(trabajo, "assets", "cabeceras"),
        "escenas": os.path.join(trabajo, "escenas"),
        "cache": os.path.join(trabajo, "_refs"),
    }
    for ruta in dirs.values():
        os.makedirs(ruta, exist_ok=True)
    catalogo = _catalogo_de(p, proyecto)
    _exigir_catalogo(catalogo)

    avisar(0.03, "cortando la narracion en planos")
    plan = planificar(proyecto, p, replantear=replantear, previo=previo)
    necesarios = plan["assets"]
    _avisar_conservacion(plan, avisar)

    # El plan se escribe YA, antes de generar nada. Se escribia solo al final, y
    # eso dejaba la pantalla vacia durante toda la tanda: la interfaz lee el plan
    # para saber que planos hay, asi que sin el no podia enseñar los que iban
    # saliendo por mucho que llegaran avisos de progreso. Con el plan puesto de
    # entrada, cada imagen aparece en su hueco en cuanto existe en disco.
    medios.escribir_json(os.path.join(trabajo, "plan.json"), plan)

    # REHACER UNA COSA REHACE ESA COSA. Aqui habia siete lineas de CASCADA:
    # pedir un asset metia detras todas las escenas que lo usan, asi que pulsar
    # «Regenerar los personajes» para arreglar UNA hoja de reparto se ponia a
    # dibujar «plano S035 - 41 de 44» -- cuarenta y cuatro imagenes, sin
    # preguntar y sin decir antes lo que costaban.
    #
    # Se retiro el 23-08 por decision del canal (PENDIENTE 30). Lo que queda
    # sucio NO se pierde: la cascada de MARCADO sigue entera
    # (`propagar_dependencias`, que corre despues de esta funcion), asi que esas
    # escenas quedan `obsoleto` y se accionan desde la pantalla con «Regenerar
    # lo obsoleto (N)» -- que dice cuantas son y lo que cuestan ANTES de que
    # nadie pulse. El comentario que habia aqui decia que hacerlo en el momento
    # «evita una segunda pasada»; esa segunda pasada es justo lo que se quiere,
    # porque es donde una persona mira el numero y decide.
    pedidas = set(unidades) if unidades is not None else None

    def toca(unidad):
        return pedidas is None or unidad in pedidas

    # LO QUE YA ESTA HECHO SE QUEDA, salvo que alguien lo pida. `toca` da True
    # con `pedidas is None` --que es lo que manda una tanda normal-- y eso hacia
    # que cualquier pasada volviera a generar TODO. Ver la regla del canal en
    # `_generar_escenas`: un cambio en el audio no rehace lo dibujado.
    def pedido(unidad):
        # La misma regla que en los planos: con unidades, solo ellas. Un
        # `rehacer` de una escena no puede arrastrar los assets del video.
        if pedidas is not None:
            return unidad in pedidas
        return bool(rehacer)

    # ---------------------------------------------------------------- assets
    resultados = {}
    inventario = {}
    pendientes = [(uid, ficha) for uid, ficha in sorted(necesarios.items())
                  if tipos is None or ficha["tipo"] in tipos]
    for indice, (uid, ficha) in enumerate(pendientes):
        # El numero va en el mensaje, no solo en la barra: "12 de 44" dice de
        # un vistazo cuanto queda; un porcentaje hay que traducirlo mentalmente.
        avisar(0.05 + 0.25 * (indice / max(1, len(pendientes))),
               f"asset {ficha['nombre']} · {indice + 1} de {len(pendientes)}",
               (indice + 1, len(pendientes)))
        if ficha["tipo"] == "reparto":
            destino = os.path.join(dirs["reparto"], f"{ficha['nombre']}.png")
            if pedido(uid) or not os.path.exists(destino):
                prompt = _prompt_reparto(ficha, p["estilo"])
                # a una hoja de personaje le tocan los ejes de personas: la
                # cara y los cuerpos, que es lo que esa hoja tiene que fijar
                refs = [r["ruta"] for r in _referencias_estilo(
                    p, dirs["cache"], {"personajes": [ficha["nombre"]]})]
                meta = _producir_imagen(ficha["nombre"], prompt, refs, destino, p,
                                        rehacer=((rehacer or unidades is not None)
                                                 and os.path.exists(destino)))
                resultados[uid] = {"tipo": "reparto",
                                   "png": os.path.relpath(destino, trabajo), **meta}
            else:
                resultados[uid] = {"tipo": "reparto",
                                   "png": os.path.relpath(destino, trabajo),
                                   "origen": "conservado"}
        elif ficha["tipo"] in ("mapa", "grafico"):
            svg = os.path.join(dirs["componentes"], f"{ficha['nombre']}.svg")
            png = os.path.join(dirs["componentes"], f"{ficha['nombre']}.png")
            if toca(uid) or not os.path.exists(png):
                mapa = medios.motor("capa_vectorial/mapa.py")
                medios.escribir_texto(svg, mapa.construir(ficha["config"]))
                medios.rasterizar(svg, png, *TAMANO, transparente=False)
            resultados[uid] = {"tipo": "mapa", "svg": os.path.relpath(svg, trabajo),
                               "png": os.path.relpath(png, trabajo)}
        elif ficha["tipo"] == "cabecera":
            svg = os.path.join(dirs["cabeceras"], f"{ficha['nombre']}.svg")
            if toca(uid) or not os.path.exists(svg):
                cabecera = medios.motor("capa_vectorial/cabecera.py")
                medios.escribir_texto(svg, cabecera.construir(
                    ficha["titulo"], ficha["subtitulo"], ficha["antetitulo"]))
            resultados[uid] = {"tipo": "cabecera",
                               "svg": os.path.relpath(svg, trabajo),
                               "titulo": ficha["titulo"]}

    # el plan definitivo se recalcula con las camaras y anclas reales del set
    avisar(0.32, "asignando camaras y anclas")
    # CON EL MISMO `previo` QUE LA PRIMERA. Se planifica dos veces --la segunda
    # ya con las camaras y anclas del set-- y esta se quedaba sin el, asi que
    # heredaba del plan activo mientras la de arriba heredaba de lo que le
    # hubieran pasado: dos cortes distintos en la misma pasada, y ganaba este.
    plan = planificar(proyecto, p, inventario=inventario or None,
                      replantear=replantear, previo=previo)

    # ---------------------------------------------------------------- escenas
    escenas = plan["escenas"]
    if solo_assets:
        # Lo que ESTA pasada no toco hereda su resultado del trabajo sembrado
        # (la version activa se copia entera al trabajo antes de ejecutar).
        # Sin esto, una pasada parcial versionaba un assets.json solo con lo
        # suyo, y la pantalla entera -- que lee la version activa -- se quedaba
        # sin cajas, sin hojas y sin piezas hasta la siguiente pasada completa.
        # Solo se hereda lo que el plan de AHORA sigue pidiendo: un asset
        # retirado del plan no debe resucitar por herencia.
        previos = (medios.leer_json(os.path.join(trabajo, "assets.json"), {})
                   or {}).get("resultados") or {}
        for uid, salida in previos.items():
            if uid in necesarios and uid not in resultados:
                resultados[uid] = salida
        avisar(0.9, f"{len(resultados)} assets listos; los {len(escenas)} planos "
                    f"quedan para cuando los apruebes")
        medios.escribir_json(os.path.join(trabajo, "plan.json"), plan)
        # EXACTAMENTE la misma forma que escribe la pasada completa. Aqui se
        # escribia el 'inventario', que es otra cosa: solo lleva sets, va con el
        # nombre pelado por clave en vez del id de unidad, guarda rutas absolutas
        # a la carpeta de trabajo -- que deja de existir al versionar -- y no
        # trae los resultados. La pantalla lo leia igual, asi que salia una
        # tarjeta por set sin tipo ("undefined sin previsualizacion"), sin imagen
        # y sin escenas, faltaban el reparto y las cabeceras, y al guardar
        # quedaban declaradas unidades con ese nombre pelado que ninguna pasada
        # produce jamas: el paso se quedaba obsoleto para siempre.
        medios.escribir_json(os.path.join(trabajo, "assets.json"),
                             {"assets": necesarios, "resultados": resultados})
        # y las dependencias, que es de donde sale la cascada asset -> planos:
        # sin el fichero, propagar_dependencias() no encuentra nada que propagar
        # y tocar un set dejaba de ensuciar los planos rodados en el
        medios.escribir_json(os.path.join(trabajo, "dependencias.json"),
                             plan["dependencias"])
        return _salidas_parciales(plan, resultados, inventario, necesarios, avisar)
    coste = _generar_escenas(plan, dirs, p, trabajo, toca, unidades,
                             resultados, avisar, forzar=rehacer,
                             notas_repaso=_notas_del_repaso(proyecto),
                             proyecto=proyecto)

    avisar(0.96, "comprobando que no hay planos repetidos")
    # Los que comparten imagen A PROPOSITO salen del PLAN: la segunda mitad de
    # una toma que dura mas copia la del hogar, y tiene que ser identica.
    repetidos = _planos_repetidos(
        resultados, trabajo,
        copiados={e["id"] for e in escenas if e.get("sigue_a")})
    if repetidos:
        detalle = "; ".join(" = ".join(grupo) for grupo in repetidos)
        # Al generar, dos planos con la misma imagen siempre es un fallo: significa
        # que sus prompts salieron identicos y la cache devolvio el mismo fichero.
        # En el modo explicito 'adoptar' es lo esperado, porque se esta repartiendo
        # un fondo de arte limitado entre mas planos de los que hay.
        if p["motor_imagen"] == "adoptar":
            avisar(None, f"AVISO: planos con la misma imagen adoptada: {detalle}")
            plan.setdefault("informe", {})["planos_repetidos"] = repetidos
        else:
            raise RuntimeError(
                f"dos o mas planos han acabado con la MISMA imagen: {detalle}. "
                f"Sus prompts salieron identicos y la cache devolvio el mismo "
                f"fichero. Revisa que la narracion de cada plano entre en su prompt.")

    avisar(0.97, "escribiendo el plan")
    medios.escribir_json(os.path.join(trabajo, "plan.json"), plan)
    medios.escribir_json(os.path.join(trabajo, "assets.json"),
                        {"assets": necesarios, "resultados": resultados})
    medios.escribir_json(os.path.join(trabajo, "dependencias.json"), plan["dependencias"])

    # a completar() solo van las unidades que se han rehecho de verdad: si se
    # sellara tambien lo conservado, una unidad obsoleta que nadie ha tocado
    # pasaria por fresca y ya nunca se rehria
    if pedidas is None:
        rehechas = dict(resultados)
    else:
        rehechas = {uid: ficha for uid, ficha in resultados.items() if uid in pedidas}
    conservadas = sorted(uid for uid in resultados if uid not in rehechas)

    generadas = sum(1 for r in resultados.values() if r.get("origen") == "generada")
    camaras = plan["informe"]["camaras"]
    salidas = {
        "plan": "plan.json",
        "escenas": "escenas",
        "assets": "assets",
        "dependencias": "dependencias.json",
        "n_escenas": len(escenas),
        "duracion": plan["duracion_total"],
        "coste_usd": round(coste, 4),
        "clases_de_encuadre": camaras["cartas_distintas"],
        "planos_con_familia_repetida": camaras["planos_repetidos"],
        # El resumen dice lo que de verdad ha pasado. «N camaras distintas» ya no
        # significa nada: no hay camaras, hay clases de encuadre, y lo unico que
        # hay que vigilar es que no salgan dos seguidas de la misma familia.
        "resumen": (
            f"{len(escenas)} planos, {len(necesarios)} assets, "
            f"{camaras['cartas_distintas']} clases de encuadre "
            f"({camaras['planos_repetidos']} seguidos de la misma familia), "
            f"{generadas} imagenes nuevas, {coste:.3f} USD"),
    }
    avisar(1.0, salidas["resumen"])
    # Los planos que este recorte ha dejado fuera. Van en el resultado para que
    # quien tiene el estado en la mano los DES-DECLARE: un id de plano es
    # posicional y se hereda, asi que un plan mas corto deja unidades declaradas
    # que ya nadie va a producir nunca, y el paso se quedaba obsoleto para
    # siempre por un plano que no existe. Solo en una pasada COMPLETA: si se han
    # pedido unidades sueltas, el plan que se acaba de calcular no es la ultima
    # palabra sobre que planos hay.
    retirados = []
    if unidades is None:
        retirados = [f"escena:{sid}"
                     for sid in (plan.get("conservacion") or {}).get("retirados") or []]
        # Y LOS ASSETS QUE EL PLAN NUEVO YA NO PIDE. Es el mismo fallo que el de
        # los planos retirados, con otra puerta de entrada: al retirarse la
        # geometria 3D los planes viejos dejaron huerfanas las
        # unidades de sitio y de caja (asset:sede_central, asset:geo_s007...).
        # Nadie las va a producir jamas, `completar()` solo refresca la firma de
        # lo que esta pasada ha hecho, y `unidades_obsoletas` las seguiria
        # contando: el paso se quedaria en ambar para siempre por unas unidades
        # que ya no existen.
        #
        # Lo que decide es el plan ANTERIOR contra el nuevo, y no la lista de
        # declaradas, porque este modulo no sabe de estado y no tiene por que:
        # el plan que hay en disco es exactamente lo que declaro la ultima
        # pasada completa. Si no hay plan previo, no se retira nada.
        antes = set((plan_actual(proyecto) or {}).get("assets") or {})
        ahora_pide = set(plan.get("assets") or {})
        retirados += sorted(antes - ahora_pide)
    _anotar_tiempo("assets", arranque_paso, len(rehechas),
                   {"generadas": len(rehechas), "solo_assets": bool(solo_assets),
                    "unidades_pedidas": len(pedidas) if pedidas is not None else 0},
                   proyecto)
    return {"salidas": salidas, "unidades": rehechas, "conservadas": conservadas,
            "dependencias": plan["dependencias"], "plan": plan,
            "todas": resultados, "retiradas": retirados,
            "regeneradas": sorted(pedidas) if pedidas is not None else None}


# -------------------------------------------------- correccion de geometria

CLAVES_DE_CAMARA = ("azimut", "altura", "distancia", "focal", "objetivo")


def cortar(proyecto, params, replantear=False):
    """El corte en planos, escrito donde `plan_actual` lo encuentra. -> plan

    Es `planificar` mas dejarlo en la carpeta de trabajo, y existe por un caso
    que solo aparece en un video NUEVO: las cartelas y la direccion de cada
    plano se deciden ANTES de generar --decidirlas despues es pagar una imagen
    para tirarla-- y las dos necesitan saber cuantos planos hay y que dice cada
    uno. En un video que ya se genero alguna vez el plan esta en su version; en
    uno recien hecho no hay ninguno, y la tanda entera se plantaba con «no hay
    planos todavia: corta la narracion antes».

    CORTAR NO CUESTA NADA: no llama a ningun modelo y no genera ninguna imagen.
    Son las marcas de palabra de la toma y las reglas de ritmo del canal.
    """
    plan = planificar(proyecto, params, replantear=replantear)
    trabajo = proyecto.ruta_trabajo("assets", crear=True)
    medios.escribir_json(os.path.join(trabajo, "plan.json"), plan)
    return plan


def plan_actual(proyecto, paso="assets", estado=None):
    """Ultimo plan de escenas versionado, o el de la carpeta de trabajo.

    `estado` se pasa tal cual a `medios.salida_de`: quien ya tenga cargado el
    Estado del proyecto se ahorra que se construya otro, que es reparsear
    estado.json entero. Ver el docstring de salida_de.
    """
    ruta = medios.salida_de(proyecto, paso, claves=("plan",),
                            patrones=(r"plan\.json",), estado=estado)
    if not ruta:
        ruta = os.path.join(proyecto.ruta_trabajo(paso, crear=False), "plan.json")
    return medios.leer_json(ruta, {}) or {}


def unidades_del_plan(proyecto, paso="assets"):
    """Ids de unidad que el plan activo conoce: sus assets y sus escenas.

    Existen ANTES de estar declarados en el estado -- una unidad se declara al
    escribirle params o al propagar dependencias, y una caja 3D recien
    planificada no tiene ni lo uno ni lo otro --, y aun asi pedirlas por id es
    exactamente como se construyen la primera vez desde su tarjeta. La API
    valida las unidades pedidas contra las declaradas MAS estas.
    """
    plan = plan_actual(proyecto, paso)
    unidades = set(plan.get("assets") or {})
    for escena in plan.get("escenas") or []:
        if escena.get("id"):
            unidades.add(f"escena:{escena['id']}")
    return sorted(unidades)




def escenas_del_set(plan, set_nombre):
    """Todos los planos rodados en ese set: los que arrastra cambiarlo."""
    return [e["id"] for e in plan.get("escenas") or [] if e.get("set") == set_nombre]






def propagar_dependencias(estado, dependencias=None, paso="assets"):
    """Mete en los params de cada escena la firma de los assets que usa.

    Sin esto la cascada no existiria: el nucleo firma cada unidad con SUS
    parametros, asi que una escena solo se entera de que su set ha cambiado si
    la firma del set forma parte de sus propios parametros.

    Se llama justo ANTES de completar() -- para que la version guarde las firmas
    ya propagadas -- y tambien despues de tocar a mano los params de un asset,
    que es cuando marca obsoletas las escenas que lo usan.
    """
    proyecto = estado.proyecto
    if dependencias is None:
        ruta = medios.salida_de(proyecto, paso, claves=("dependencias",),
                               patrones=(r"dependencias\.json",))
        dependencias = medios.leer_json(ruta, {}) if ruta else {}
    # los params de una escena llevan tambien lo que escribe el humano (su
    # feedback): se parte de lo que ya hay y solo se pisan las dos claves de
    # dependencias, o propagar borraria las notas al guardarlas
    previos = (estado.params(paso) or {}).get("unidades") or {}
    cambios = {}
    for escena, usados in (dependencias or {}).items():
        firmas = {uid: estado.firma_unidad(paso, uid) for uid in sorted(usados)}
        anterior = previos.get(escena)
        ficha = dict(anterior) if isinstance(anterior, dict) else {}
        ficha["assets"] = sorted(usados)
        ficha["huella_assets"] = medios.huella(firmas)
        cambios[escena] = ficha
    if not cambios:
        return []
    antes = {u: estado.firma_unidad(paso, u) for u in cambios}
    # del_propio_paso: esto no es una edicion del usuario, es lo que el paso
    # acaba de descubrir sobre si mismo, asi que no invalida su propia ejecucion
    estado.actualizar_params(paso, {"unidades": cambios}, del_propio_paso=True)
    return sorted(u for u in cambios if estado.firma_unidad(paso, u) != antes[u])
