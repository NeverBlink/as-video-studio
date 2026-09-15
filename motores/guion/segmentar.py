"""
Corta una narracion en escenas de duracion objetivo, cortando en las pausas.

El ritmo de estos videos no sale de trocear el texto a ojo: sale de que la voz
ya trae pausas donde hay comas y puntos, y de cortar ahi. Con las marcas de
palabra de la sintesis se sabe el instante exacto de cada pausa, asi que el
problema deja de ser editorial y pasa a ser de optimizacion.

Se resuelve por programacion dinamica en lugar de por avance voraz: un corte
voraz encaja bien los primeros planos y arrastra el error al final, dejando
colas de un segundo. La version por DP minimiza el coste total, asi que reparte
el desajuste en vez de acumularlo.

Coste de un segmento:
    - fuera del rango [minimo, maximo]: penalizacion cuadratica
    - dentro del rango: penalizacion suave por alejarse del ideal
    - mas la penalizacion del punto de corte (un punto corta mejor que una coma)

Y DOS COSAS QUE NO SON PRECIO SINO PROHIBICION
----------------------------------------------
El coste solo no basta, y el fallo que lo demostro es este: "The seller had not
touched a single one of the bank's own systems. Spain, May of twenty
twenty-four." salio en UN plano. La aritmetica: junto costaba 2.8401, partido
3.2853, o sea que partir perdia por 0.4452 -- que es exactamente lo que paga el
trozo SANO por no durar el ideal. Anadir un segmento solo puede SUMAR terminos,
nunca quitarlos, asi que el optimizador tiene un sesgo estructural a no partir, y
con dos frases de duracion parecida el sesgo gana siempre.

Un precio no arregla eso: se calibra para un video y se esquiva en el siguiente.
Asi que hay dos reglas duras, sin constante que ajustar:

  1. Un plano NO puede tragarse un punto interior si partir ahi es legal, y
     legal es que las dos mitades caigan en [SUELO_S, TECHO_S] y al menos una
     llegue al minimo. Esa segunda mitad es la que impide romper un plano bueno
     para fabricar dos malos: dos frases de 2.2 y 2.5 s siguen siendo un plano.
  2. Un plano no puede cerrar a mitad de frase si dentro lleva un punto cuya
     cabeza se sostiene sola. Es la vieja regla de la huerfana, generalizada de
     "una o dos palabras sueltas" a "lo que sea": el caso real que la pario
     -- "...reserved for the country's elite. Music, dancing, glasses raised",
     con "Music" pegada al plano anterior y la fiesta entrando 0,724 s tarde --
     sigue cubierto, y ahora tambien lo esta el mismo fallo con cinco palabras.

Y SE MIDE LO QUE SE VE, NO LO QUE SE HABLA
------------------------------------------
Las duraciones que se puntuan son las de PANTALLA: un plano entra un poco antes
de su primera palabra y dura hasta que entra el siguiente, asi que los silencios
entre frases son suyos (ver entradas_de). Puntuando el habla, el optimizador
optimizaba una magnitud que no ve nadie: en el caso de arriba, 1,148 s de
silencio entre las dos frases se le cobraban al plano como si hablara.

    python segmentar.py --audio ./audio --out escenas.json --min 3 --max 6
"""
import argparse
import difflib
import json
import math
import os
import re
import unicodedata

# Cuanto "cuesta" cortar en cada signo. Un punto es una frontera natural; una
# coma sirve, pero deja la frase partida; cortar donde no hay nada es lo peor.
COSTE_CORTE = {
    "fuerte": 0.0,     # . ! ? … y fin de intervencion
    "medio": 0.8,      # ; :
    "debil": 1.6,      # ,
    "ninguno": 12.0,   # a mitad de sintagma
}

FUERTE = ".!?…"
MEDIO = ";:"
DEBIL = ","

# LA HORQUILLA QUE SE PIDE ES UN TOPE, NO UN PRECIO
# --------------------------------------------------
# Esto era al reves y hubo que cambiarlo. minimo/maximo entraban solo en
# `coste_duracion` como penalizacion cuadratica, o sea que pasarse tenia PRECIO y
# no estaba prohibido: con el mando en 1-4 s salian planos de 4,875 s (14 de 42),
# porque partir esa frase costaba mas que pasarse casi un segundo. Quien escribe
# "maximo 4" no esta expresando una preferencia, esta poniendo un limite, y una
# pantalla que ofrece un limite tiene que cumplirlo.
#
# Ahora la horquilla se respeta como PROHIBICION: un segmento fuera de
# [minimo, maximo] no se considera. Y como una narracion puede no admitir ningun
# reparto asi -- una palabra sola mas larga que el maximo, o una intervencion mas
# corta que el minimo --, hay tres pasadas de menos a mas permisiva y el informe
# dice por cual se salio. Nunca se devuelve nada.
#
# Estos dos numeros se quedan como la horquilla POR DEFECTO de quien llame sin
# decir nada, y como referencia de lo que se sostiene en pantalla: por debajo de
# dos segundos un plano no da tiempo ni a leerse, y por encima de ocho se para el
# video. Pero ya no mandan sobre lo que pide quien monta.
SUELO_S = 2.0
TECHO_S = 8.0

#: Con que se ha resuelto el ultimo corte. Lo escribe segmentar() y lo lee
#: informe(), para que un plan que ha tenido que salirse de la horquilla lo diga
#: en vez de aparecer y ya.
#:
#: Es el respaldo, no el sitio bueno: quien pueda debe pasarle a las dos su
#: propio dict con `reparto=`. Este modulo se carga UNA vez por proceso y lo
#: comparten todos los proyectos --hay un gestor de trabajos por proyecto y los
#: endpoints sincronos corren en el threadpool de uvicorn--, asi que dos
#: planificaciones a la vez se pisarian este dict y el informe de una describiria
#: el corte de la otra.
ULTIMO_REPARTO = {"maximo_respetado": True, "minimo_respetado": True,
                  "horquilla_respetada": True, "frases_enterradas": False,
                  "minimo": None, "maximo": None, "escalon": 0}


def tipo_de_corte(palabra):
    limpia = palabra.rstrip('"\'')
    if not limpia:
        return "ninguno"
    if limpia[-1] in FUERTE:
        return "fuerte"
    if limpia[-1] in MEDIO:
        return "medio"
    if limpia[-1] in DEBIL:
        return "debil"
    return "ninguno"


def coste_duracion(dur, minimo, maximo, ideal):
    if dur < minimo:
        return 6.0 * (minimo - dur) ** 2
    if dur > maximo:
        return 6.0 * (dur - maximo) ** 2
    return 0.35 * abs(dur - ideal)


def adelanto_de(hueco, corte, adelanto=0.25):
    """Cuanto se adelanta un plano sobre su primera palabra.

    En una frontera fuerte el silencio se parte por la mitad entre los dos
    planos. El silencio de un punto no es de nadie, y darselo entero al plano
    que se va deja al que entra pegado a su propia frase: una estampa de dos
    segundos y pico se quedaba por debajo del minimo para llevar rotulo por
    culpa de un silencio que estaba ahi mismo, sin dueno.

    En una pausa debil no: ahi la frase sigue, y adelantarse media coma se lee
    como que la imagen va por delante de lo que se cuenta.
    """
    if corte == "fuerte":
        return max(adelanto, hueco / 2.0)
    return adelanto


def entradas_de(palabras, adelanto=0.25, cola=0.45):
    """Instante en que ENTRA en pantalla el plano que empezara en cada palabra.

    Es la magnitud que hay que puntuar, y no la del habla: un plano dura hasta
    que entra el siguiente, asi que los silencios entre frases son suyos. La
    lista trae un elemento de mas, el final del ultimo plano, para que la
    duracion de un segmento sea siempre entradas[fin] - entradas[ini].

    Tiene que decir lo MISMO que _encadenar del paso de assets, que es quien
    escribe estos tiempos de verdad. Si dejan de coincidir, el optimizador vuelve
    a decidir sobre duraciones que nadie ve; hay una prueba que lo comprueba.
    """
    if not palabras:
        return []
    cortes = [tipo_de_corte(p["w"]) for p in palabras]
    entradas = [max(0.0, float(palabras[0]["s"]) - adelanto)]
    for i in range(1, len(palabras)):
        fin_anterior = float(palabras[i - 1]["e"])
        hueco = float(palabras[i]["s"]) - fin_anterior
        # El tope inferior es el final de la palabra anterior, y lo mismo topa
        # `_encadenar` en el paso de assets con su `max(anterior["t_out"], ...)`.
        # Las dos cuentas TIENEN que dar lo mismo o el optimizador decide sobre
        # una duracion que nadie ve: con una horquilla estrecha --2 a 3 s--
        # sacaba ocho planos fuera de rango despues de aceptarlos como validos.
        entradas.append(max(0.0, fin_anterior,
                            float(palabras[i]["s"])
                            - adelanto_de(hueco, cortes[i - 1], adelanto)))
    entradas.append(float(palabras[-1]["e"]) + cola)
    return entradas


def _muros_utiles(muros, entradas, n, suelo=SUELO_S):
    """Fronteras que de verdad se pueden respetar.

    Un muro es una frontera de bloque del guion: ahi el redactor cambio de idea
    y la voz deja un silencio de un segundo, asi que un plano no deberia
    cruzarla. Pero un bloque mas corto que el suelo no puede ser un plano por si
    mismo, y forzarlo seria cambiar un plano con dos ideas por uno que no se ve:
    ese muro se cae, y ese bloque comparte plano con el siguiente.

    El suelo es el minimo PEDIDO, no una constante: con el mando en 1 s, un
    bloque de 1,4 s si puede ser un plano y su muro se sostiene.
    """
    validos = sorted({int(m) for m in (muros or []) if 0 < int(m) < n})
    utiles, previo = [], 0
    for indice, muro in enumerate(validos):
        siguiente = validos[indice + 1] if indice + 1 < len(validos) else n
        if (entradas[muro] - entradas[previo] >= suelo
                and entradas[siguiente] - entradas[muro] >= suelo):
            utiles.append(muro)
            previo = muro
    return utiles


def _entierra_frase(ini, fin, cortes, entradas, minimo, maximo):
    """True si este segmento se traga una frase que podia haber sido un plano.

    Las dos prohibiciones de la cabecera, juntas, porque las dos miran lo mismo:
    los puntos que quedan DENTRO del segmento.

    Se miden contra la horquilla PEDIDA. Antes se median contra [2, 8] fijos, y
    eso las volvia incoherentes con el mando: con el minimo en 1, la excepcion
    de la regla 1 se volvia inalcanzable -- para llegar ahi las dos mitades ya
    tenian que medir 2 s o mas, y no pueden ser las dos menores que 1 -- asi que
    la proteccion cambiaba de comportamiento sin que nadie lo pidiera.
    """
    for k in range(ini, fin - 1):
        if cortes[k] != "fuerte":
            continue
        izq = entradas[k + 1] - entradas[ini]
        der = entradas[fin] - entradas[k + 1]
        # 1. Partir aqui es legal si las dos mitades se sostienen... salvo en el
        #    unico caso en que partir empeora el plan: que las dos se queden
        #    cortas Y el plano junto caiga justo en la horquilla pedida. Dos
        #    frases de 2.2 y 2.5 s son un plano de 5 s en su sitio, y partirlas
        #    seria romper un plano bueno para fabricar dos malos.
        if minimo <= izq <= maximo and minimo <= der <= maximo:
            return True
        # 2. Y aunque la cola no se sostenga sola, cerrar a mitad de frase
        #    teniendo dentro un punto cuya cabeza aguanta es siempre peor: eso
        #    es dejar huerfano el arranque de la frase siguiente.
        if cortes[fin - 1] != "fuerte" and minimo <= izq <= maximo:
            return True
    return False


def segmentar(palabras, minimo=3.0, maximo=6.0, ideal=None,
              adelanto=0.25, cola=0.45, muros=(), reparto=None):
    """palabras: [{"w","s","e"}] en orden. Devuelve [(inicio, fin, [palabras])].

    'muros' son indices de palabra donde empieza un bloque del guion: ningun
    plano los cruza. No es estetica -- ahi la voz deja un silencio de un segundo
    entero, asi que un plano a caballo lleva ese segundo mudo dentro -- y ademas
    es un hecho y no una inferencia sobre el ultimo caracter, o sea que aguanta
    "Dr.", "EE.UU." y el cambio de idioma.
    """
    destino = ULTIMO_REPARTO if reparto is None else reparto
    minimo = max(0.1, float(minimo))
    maximo = max(minimo + 0.1, float(maximo))
    if not palabras:
        # tambien aqui se escribe: heredar el reparto del corte anterior seria
        # describir otro plan
        destino.update({"maximo_respetado": True, "minimo_respetado": True,
                        "horquilla_respetada": True, "frases_enterradas": False,
                        "minimo": minimo, "maximo": maximo, "escalon": 0})
        return []
    ideal = ideal if ideal is not None else (minimo + maximo) / 2
    n = len(palabras)

    cortes = [tipo_de_corte(p["w"]) for p in palabras]
    cortes[-1] = "fuerte"                       # el final siempre cierra
    entradas = entradas_de(palabras, adelanto, cola)
    tapias = set(_muros_utiles(muros, entradas, n, suelo=minimo))
    # El vano de UNA palabra mas largo que hay. Se usa para que la poda por
    # duracion del ultimo escalon no llegue a podar el segmento de una sola
    # palabra: ese es el unico que garantiza que siempre exista solucion, y si
    # se poda, el DP se queda sin camino y la reconstruccion devuelve un reparto
    # a medias --con un minimo bajo y un maximo bajo, 367 palabras salian en un
    # solo plano--. Es una poda de rendimiento, no una regla.
    vano_max = max((entradas[i + 1] - entradas[i] for i in range(n)), default=0.0)

    def resolver(estricto, tope_max, tope_min):
        """Reparto optimo. Los topes hacen de min/max una PROHIBICION, no un precio."""
        INF = float("inf")
        coste = [INF] * (n + 1)
        origen = [-1] * (n + 1)
        coste[0] = 0.0
        for fin in range(1, n + 1):
            for ini in range(fin - 1, -1, -1):
                dur = entradas[fin] - entradas[ini]
                # con el maximo como tope basta pasarse para dejar de mirar; sin
                # tope, la poda nunca puede llevarse el segmento de una palabra
                if dur > (maximo if tope_max else max(maximo * 2.2, vano_max)):
                    break
                if coste[ini] == INF:
                    continue
                if tope_min and dur < minimo:
                    continue
                if any(ini < muro < fin for muro in tapias):
                    continue
                if estricto:
                    # Un plano no se cierra a mitad de sintagma mientras haya
                    # otra forma. Esto estaba ESCRITO en el comentario de este
                    # bucle -- "solo se permite terminar un segmento en un punto
                    # de puntuacion, salvo que no haya ninguno alcanzable"-- y no
                    # estaba en el codigo: solo era un precio (COSTE_CORTE de
                    # 12). Con el maximo convertido en tope se notó de golpe:
                    # a la voz un 10% mas lenta, cuadrar la horquilla salia mas
                    # barato partiendo "...for two million | dollars. The seller
                    # had not touched the bank's" que dejando un plano corto.
                    if cortes[fin - 1] == "ninguno":
                        continue
                    if _entierra_frase(ini, fin, cortes, entradas,
                                       minimo, maximo):
                        continue
                c = (coste[ini]
                     + coste_duracion(dur, minimo, maximo, ideal)
                     + COSTE_CORTE[cortes[fin - 1]])
                if c < coste[fin]:
                    coste[fin] = c
                    origen[fin] = ini
        return coste, origen

    # EL MAXIMO Y EL MINIMO NO VALEN LO MISMO, Y POR ESO CEDEN EN ESTE ORDEN
    # ---------------------------------------------------------------------
    # El maximo es un TOPE de verdad y es el ultimo en caer: pediste planos de
    # cuatro segundos y uno de siete es lo que se ve y lo que molesta.
    #
    # El minimo cede antes, y cede antes que romper una frase por la mitad. Una
    # narracion no siempre admite un reparto que caiga entero en la horquilla
    # cuadrando ademas con las frases -- basta una frase corta entre dos largas --
    # y ahi hay que elegir: un plano medio segundo mas corto de lo pedido, o un
    # corte a mitad de sintagma. Lo segundo se ve muchisimo peor, y ademas es lo
    # que las dos prohibiciones de la cabecera existen para evitar.
    #
    # Se para en el primer escalon que salga, y se apunta cual para que el
    # informe lo pueda decir: un plan que se ha salido de lo pedido tiene que
    # poder explicarse, no aparecer y ya.
    ESCALERA = (
        (True,  True,  True),    # 0: todo se cumple
        (True,  True,  False),   # 1: algun plano corto, antes que partir una frase
        (False, True,  True),    # 2: se entierra alguna frase, pero la horquilla entera
        (False, True,  False),   # 3: maximo respetado, y ya
        (True,  False, False),   # 4: ni el maximo cabe: se vuelve al precio de siempre
        (False, False, False),   # 5: ultimo recurso, siempre devuelve algo
    )
    for etapa, (estricto, tope_max, tope_min) in enumerate(ESCALERA):
        coste, origen = resolver(estricto, tope_max, tope_min)
        if coste[n] != float("inf"):
            break
    else:
        coste = None
    if coste is None or coste[n] == float("inf"):
        # No deberia ocurrir nunca: el ultimo escalon no prohibe nada y la poda
        # ya no alcanza al segmento de una palabra. Si ocurre, se grita: esto
        # manda a generar imagenes, y devolver un reparto a medias en silencio
        # es el peor modo de fallo que hay aqui.
        raise RuntimeError(
            f"no hay ningun reparto posible para {n} palabras con planos de "
            f"{minimo}-{maximo} s")

    limites = []
    fin = n
    while fin > 0:
        ini = origen[fin]
        limites.append((ini, fin))
        fin = ini
    limites.reverse()

    # Se derivan de los FLAGS del escalon que ha ganado, no de indices
    # cableados: con indices, tocar la escalera los deja mintiendo en silencio.
    destino.update({
        "maximo_respetado": tope_max,
        "minimo_respetado": tope_min,
        "horquilla_respetada": tope_max and tope_min,
        "frases_enterradas": not estricto,
        "minimo": minimo, "maximo": maximo, "escalon": etapa,
    })
    return [(palabras[i]["s"], palabras[j - 1]["e"], palabras[i:j])
            for i, j in limites]


#: Cuanto cuadro se ve con el zoom CERRADO, en fraccion del plano entero. Es
#: el numero en el que se piensa el movimiento -- "de 100 a 95" -- y no la
#: escala, que es su inversa y por eso enganaba: 1.16 de escala no cerraba un
#: 16% sino un 14%, y aun asi se notaba de mas. Se bajo a 95 el 20-08-2026: el
#: zoom tiene que empujar el plano sin que se vea empujar.
CIERRE = 0.95

#: La escala que pide el motor de movimiento, que recorta 1/escala de cuadro.
ESCALA_CERRADA = round(1.0 / CIERRE, 4)


def alternar_zoom(indice, ancla=None):
    """Alterna acercar y alejar plano a plano.

    Alternar no es un capricho estetico: dos zooms seguidos en la misma
    direccion se leen como un unico movimiento largo y el corte entre ellos
    desaparece.
    """
    if indice % 2 == 0:
        return {"tipo": "in", "ancla": ancla, "de": 1.0, "a": ESCALA_CERRADA}
    return {"tipo": "out", "ancla": ancla, "de": ESCALA_CERRADA, "a": 1.0}


def transicion_para(indice, corte):
    """Que RANURA de transicion deja este corte. Suave como norma.

    Devuelve una de tres: 'corte', 'suave' o 'acento'. QUE transicion concreta
    ocupa cada ranura NO se decide aqui sino al renderizar (pasos/
    transiciones.py), contra la paleta elegida para ese video. La separacion es
    por dinero: donde va un acento pertenece al CORTE y viaja en el plan, asi
    que moverlo obliga a replanificar; cual es el acento es una eleccion de
    acabado, y cambiarla solo deja obsoleto el render.

    Antes esto devolvia el nombre del efecto ('corte', 'fundido', 'flash'). El
    render sigue entendiendolos, por los planes ya guardados; y tambien
    'deslizar', que se retiro el 18-08-2026 por arrastrar el plano saliente
    por pantalla.

    Y de paso, una correccion de la version anterior: su docstring decia
    «fundido tras pausa» y el codigo hacia lo contrario -- encadenaba la mitad
    de los cortes que NO cierran frase (`return "fundido" if indice % 2`) y
    dejaba secos dos tercios de los que si la cerraban. Encadenar a media frase
    es lo que hace que un montaje parezca un pase de diapositivas: si la frase
    no ha terminado, se corta. Determinista por indice, como todo lo del corte.
    """
    # Desde el 20-08-2026 no se reparte ni un corte seco: decision del usuario
    # mirando el primer video montado ("no me gusta como queda"). Lo que era
    # 'corte' pasa a 'suave', que es la ranura mas discreta que hay; el acento
    # sigue cayendo donde caia, en el corte fuerte de cada cinco.
    #
    # El unico corte seco que queda en un video es el del PRIMER plano, y ese no
    # es una transicion: no hay nada de lo que venir (transiciones.resolver).
    if corte == "fuerte" and indice % 5 == 2:
        return "acento"
    return "suave"


#: Cuanto del texto tiene que reconocerse para que herede el corte de antes.
#: Por debajo ya no es «el mismo guion con otra voz» sino otro texto, y
#: entonces se corta de cero.
RECONOCIDO_MINIMO = 0.5


def _limpia(palabra):
    """La palabra a secas, para comparar: sin puntuacion, sin tildes y en bajas.

    Sin esto, «mes.» y «mes» son dos palabras distintas y el corte no se
    reconoce justo donde mas falta hace: en el limite de un plano, que es donde
    caen los puntos.
    """
    s = unicodedata.normalize("NFD", str(palabra or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "", s)


def heredar(palabras, previas, adelanto=0.25, cola=0.45, maximo=None,
            minimo=None, reparto=None):
    """El corte de antes puesto sobre las palabras de ahora. -> [(ini,fin,[pal])]

    POR QUE. El corte se decide con las MARCAS DE PALABRA, asi que depende de
    los milisegundos de la voz. Y una voz sintetizada dos veces no da los mismos
    milisegundos: el 31-08 se regrabo la misma frase, las marcas se movieron
    ochenta milesimas, y el reparto optimo cambio de 222 planos a 217. El texto
    era el mismo palabra por palabra. Nada de eso lo pidio nadie, y arrastro
    detras a las 225 imagenes, que se guardan por el numero del plano.

    El optimizador no esta mal: dadas OTRAS duraciones, otro reparto es
    efectivamente mejor. Lo que esta mal es volver a preguntarselo. Si el guion
    no ha cambiado, el corte ya estaba decidido y esto solo lo vuelve a colocar
    sobre los tiempos nuevos, que es lo unico que de verdad cambio.

    COMO, Y POR QUE ES DETERMINISTA. Se alinean las palabras de antes con las de
    ahora y cada limite de plano se traslada al mismo sitio del texto:

      - si la palabra donde cortaba sigue estando, ahi se corta;
      - si esa se toco, se va A LA SIGUIENTE QUE NO SE TOCO y se corta donde
        empieza;
      - y si no queda ninguna por delante, se cierra justo despues del ultimo
        trozo reconocido de lo anterior.

    No hay ningun optimo que recalcular, asi que corregir una preposicion mueve
    la frontera de esa frase y NADA MAS. Lo que se reescriba de cero no se
    reconoce, cae en un hueco, y ese hueco --solo ese-- se vuelve a cortar con
    `segmentar`.
    """
    if not palabras or not previas:
        return []
    nuevas = [_limpia(p["w"]) for p in palabras]
    viejas, limites = [], []
    for escena in previas:
        trozo = [_limpia(w) for w in str(escena.get("narracion") or "").split()]
        if not trozo:
            continue
        viejas.extend(trozo)
        limites.append(len(viejas))
    if not viejas or len(limites) < 2:
        return []

    pares = difflib.SequenceMatcher(None, viejas, nuevas,
                                    autojunk=False).get_matching_blocks()
    mapa, reconocidas = {}, 0
    for a, b, n in pares:
        reconocidas += n
        for k in range(n):
            mapa[a + k] = b + k
    if reconocidas < RECONOCIDO_MINIMO * len(nuevas):
        return []

    fronteras = set()
    for limite in limites[:-1]:
        if limite in mapa:
            fronteras.add(mapa[limite])
            continue
        # LA SIGUIENTE QUE NO SE TOCO: se corta donde empieza ella.
        siguiente = next((i for i in range(limite, len(viejas)) if i in mapa), None)
        if siguiente is not None:
            fronteras.add(mapa[siguiente])
            continue
        # y si no queda nada por delante, justo detras de lo ultimo reconocido
        anterior = next((i for i in range(limite - 1, -1, -1) if i in mapa), None)
        if anterior is not None:
            fronteras.add(mapa[anterior] + 1)
    cortes = sorted(i for i in fronteras if 0 < i < len(nuevas))

    entradas = entradas_de(palabras, adelanto, cola)
    trozos, ini = [], 0
    for fin in cortes + [len(nuevas)]:
        if fin > ini:
            trozos.append((ini, fin))
            ini = fin

    # UN HUECO SE CORTA, NO SE TRAGA. Lo que se haya escrito de cero no se
    # reconoce y se queda pegado al plano vecino, que puede acabar durando medio
    # minuto. Ese plano --y solo ese-- vuelve a pasar por el optimizador.
    segmentos = []
    for ini, fin in trozos:
        largo = entradas[fin] - entradas[ini]
        if maximo and largo > 2.0 * float(maximo) and fin - ini > 1:
            dentro = segmentar(palabras[ini:fin], maximo / 2.0, maximo,
                               adelanto=adelanto, cola=cola, reparto={})
            for _a, _b, trozo in dentro:
                segmentos.append(trozo)
            continue
        segmentos.append(palabras[ini:fin])

    # LOS TIEMPOS, CRUDOS, igual que los devuelve `segmentar`: el principio de
    # la primera palabra y el final de la ultima. `entradas` --que ya lleva
    # dentro el adelanto y la cola-- sirve para MEDIR aqui, no para publicar:
    # quien recibe esto es `_encadenar`, y ese vuelve a restar el adelanto y a
    # sumar la cola. Devolverlas ya sumadas alargaba el video 0,87 s y lo
    # descuadraba con el audio.
    salida, i = [], 0
    for trozo in segmentos:
        j = i + len(trozo)
        salida.append((float(trozo[0]["s"]), float(trozo[-1]["e"]), trozo))
        i = j

    # SE DICE LO QUE SALIO, MEDIDO. `informe` lee estas banderas y, si nadie las
    # escribe, se queda con los valores por defecto -- o sea que anunciaria «la
    # horquilla se ha respetado» sin haberla mirado. Un corte heredado puede
    # perfectamente salirse: hereda las FRONTERAS, y con una voz mas lenta el
    # mismo trozo dura mas.
    if reparto is not None:
        # LA DURACION QUE SE JUZGA ES LA DE PANTALLA, la de `entradas`: un
        # plano dura hasta que entra el siguiente, asi que los silencios entre
        # frases son suyos. Medir el habla a secas diria que la horquilla se
        # respeta cuando en pantalla no se respeta.
        cortes_i, k = [0], 0
        for _ini, _fin, trozo in salida:
            k += len(trozo)
            cortes_i.append(k)
        duraciones = [entradas[b] - entradas[a]
                      for a, b in zip(cortes_i, cortes_i[1:])]
        bajo = float(minimo) if minimo else None
        alto = float(maximo) if maximo else None
        reparto.update({
            "heredado": True,
            "maximo_respetado": (not alto
                                 or all(d <= alto + 0.05 for d in duraciones)),
            "minimo_respetado": (not bajo
                                 or all(d >= bajo - 0.05 for d in duraciones)),
            "horquilla_respetada": (not (bajo and alto)
                                    or all(bajo - 0.05 <= d <= alto + 0.05
                                           for d in duraciones)),
            "frases_enterradas": False,
            "minimo": bajo, "maximo": alto, "escalon": 0,
        })
    return salida

def construir_escenas(segmentos, prefijo="S", capitulos=None):
    capitulos = capitulos or {}
    escenas = []
    for i, (ini, fin, palabras) in enumerate(segmentos):
        sid = f"{prefijo}{i + 1:03d}"
        texto = " ".join(p["w"] for p in palabras)
        corte = tipo_de_corte(palabras[-1]["w"])
        escena = {
            "id": sid,
            "narracion": texto,
            "t_in": round(ini, 3),
            "t_out": round(fin, 3),
            "duracion": round(fin - ini, 3),
            "corte": corte,
            "zoom": alternar_zoom(i),
            "transicion": transicion_para(i, corte),
        }
        cap = capitulos.get(sid)
        if cap:
            escena["capitulo"] = cap
        escenas.append(escena)
    return escenas


def frases_dentro(narracion):
    """Cuantas frases se cierran DENTRO de un plano, sin contar la ultima."""
    palabras = str(narracion or "").split()
    return sum(1 for w in palabras[:-1] if tipo_de_corte(w) == "fuerte")


def informe(escenas, minimo, maximo, reparto=None):
    """Los numeros del corte. Se calcula DESPUES de repartir los silencios.

    Se calculaba antes, y describia unas duraciones que se descartaban en la
    linea siguiente: decia 6.69 s de plano mas largo cuando el plano mas largo
    del mismo fichero medía 7.34. Un informe que no mide lo que se guarda no
    sirve para vigilar nada.
    """
    # Lo que dejo el corte de ESTE plan si quien llama lo guardo; si no, el
    # respaldo de modulo (ver ULTIMO_REPARTO).
    hecho = ULTIMO_REPARTO if reparto is None else reparto
    duraciones = [e["duracion"] for e in escenas]
    fuera = [e for e in escenas
             if e["duracion"] < minimo - 0.05 or e["duracion"] > maximo + 0.05]
    reparto_cortes = {}
    for e in escenas:
        reparto_cortes[e["corte"]] = reparto_cortes.get(e["corte"], 0) + 1
    # Un plano con dos frases dentro y una frase repartida entre dos planos son
    # las dos formas de que el corte no case con lo que se cuenta. Se cuentan y
    # se nombran: sin esto, seis planos de veintiseis llevaban dos ideas dentro
    # y no lo sabia nadie hasta ver el video.
    con_varias = [e["id"] for e in escenas if frases_dentro(e.get("narracion")) > 0]
    partidas = [e["id"] for e in escenas if e.get("corte") != "fuerte"]
    return {
        "escenas": len(escenas),
        "duracion_media": round(sum(duraciones) / len(duraciones), 2) if duraciones else 0,
        "duracion_min": round(min(duraciones), 2) if duraciones else 0,
        "duracion_max": round(max(duraciones), 2) if duraciones else 0,
        "fuera_de_rango": len(fuera),
        "fuera_de_rango_ids": [e["id"] for e in fuera],
        # La horquilla que se pidio, dentro del informe: un plan que se mira
        # dos dias despues no puede obligar a adivinar con que se corto.
        "horquilla": [minimo, maximo],
        # Y si se ha tenido que ceder, y en que. Sin esto, "he pedido 1-4 y hay
        # planos de 5" no tiene respuesta. `maximo_respetado` en False solo
        # ocurre cuando la narracion no admite NINGUN reparto por debajo del
        # maximo -- una palabra sola mas larga, o un bloque indivisible --.
        "horquilla_respetada": bool(hecho.get("horquilla_respetada", True)),
        "maximo_respetado": bool(hecho.get("maximo_respetado", True)),
        "minimo_respetado": bool(hecho.get("minimo_respetado", True)),
        "frases_enterradas": bool(hecho.get("frases_enterradas", False)),
        # cuantos planos cierran a mitad de sintagma: el corte que peor se ve
        "cortes_a_mitad_de_frase": reparto_cortes.get("ninguno", 0),
        "cortes_por_tipo": reparto_cortes,
        "planos_con_varias_frases": len(con_varias),
        "planos_con_varias_frases_ids": con_varias,
        "frases_partidas": len(partidas),
        "frases_partidas_ids": partidas,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audio", required=True, help="carpeta con audio_meta.json")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min", type=float, default=3.0)
    parser.add_argument("--max", type=float, default=6.0)
    args = parser.parse_args()

    with open(os.path.join(args.audio, "audio_meta.json"), "r", encoding="utf-8") as fh:
        meta = json.load(fh)

    palabras = []
    for bloque in meta["escenas"]:
        palabras.extend(bloque.get("palabras") or [])
    palabras.sort(key=lambda p: p["s"])

    segmentos = segmentar(palabras, args.min, args.max)
    escenas = construir_escenas(segmentos)
    datos = {"fuente": meta.get("archivo"), "escenas": escenas,
             "informe": informe(escenas, args.min, args.max)}

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)

    inf = datos["informe"]
    for e in escenas[:8]:
        print(f"  {e['id']}  {e['t_in']:6.2f}->{e['t_out']:6.2f} "
              f"({e['duracion']:4.2f}s) [{e['corte']:<7}] {e['narracion'][:58]}")
    if len(escenas) > 8:
        print(f"  … {len(escenas) - 8} mas")
    print(f"\n[segmentar] {inf['escenas']} escenas · media {inf['duracion_media']}s "
          f"· rango {inf['duracion_min']}-{inf['duracion_max']}s "
          f"· fuera de rango {inf['fuera_de_rango']}")
    print(f"[segmentar] cortes: {inf['cortes_por_tipo']}")
    print(f"[segmentar] -> {args.out}")


if __name__ == "__main__":
    main()
