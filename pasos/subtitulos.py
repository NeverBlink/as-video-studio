"""Los SUBTITULOS: la narracion escrita, trozo a trozo, cuando se dice.

QUE SUSTITUYE
-------------
Hasta el 22-08-2026 encima de cada plano iba un ROTULO: una caja con texto que
el codigo colocaba buscando un hueco libre en la imagen (mascara de detalle,
transformada de distancia, catorce candidatos, linea guia hasta el sujeto). Ese
motor se retiro entero, y por un motivo que estaba a la vista:
de los siete arquetipos solo quedaban dos vigentes y los dos eran
`forma=banda, anclaje=inferior`. O sea que en cada plano se analizaban los
pixeles para colocar una caja que iba SIEMPRE al pie del cuadro. En el video del
Aurora: 49 capas, 3 con rotulo. Cuarenta y seis planos pagaban ese analisis
para nada.

Un subtitulo no flota, asi que no hay nada que colocar. Vive abajo, centrado,
igual en todo el video. Lo unico que hay que calcular es QUE DICE y CUANDO.

Y DESDE EL 23-08 TAMPOCO SE MUEVE. La capa que lo lleva salio del grupo que
hace el zoom, asi que ya no vive en el lienzo de generacion (1536x1024) sino
en el cuadro de salida (1920x1080), quieto. Eso se llevo por delante la
cuenta mas cara de este modulo -- ver `banda_fija`, donde estaba `banda_de`.

POR QUE ESTO ES UN MODULO Y NO UNA PARTE DE p7
-----------------------------------------------
Por lo mismo que `tipografia.py` salio de p7 en su dia: esto es aritmetica de
texto y de tiempo, sin un pixel, sin cv2 y sin numpy. Se prueba sin generar
nada, lo puede importar la vista previa, y p7 lo importa a el -- nunca al reves.

POR QUE AQUI NO HAY QUE EMPAREJAR NADA, QUE ES LO QUE LO HACE FIABLE
---------------------------------------------------------------------
Una CARTELA destila la narracion: escribe «30M Customer accounts on sale» de una
frase que dice otra cosa, y por eso `cartelas.alinear` tiene que buscar cada
palabra dibujada entre las habladas, y por eso existe `_palabras_llanas`.

Un subtitulo NO destila: **es** la narracion. `escena["marcas"]` trae una marca
`[inicio, fin]` por palabra cruda de `escena["narracion"].split()`, y en el
Aurora los 49 planos cumplen `len(narracion.split()) == len(marcas)` exacto.
Emparejar es la identidad.

Y por eso `tramos` devuelve RANGOS DE INDICES y no cadenas. El motor antiguo del
que sale este troceo (el motor anterior, `captions()` en build-config11.js) devolvia
texto y despues volvia a partirlo para contar cuantas palabras consumir; su
propio comentario avisa de que si un trozo pierde o gana una palabra, TODOS los
subtitulos siguientes se desplazan. Con rangos, el tiempo sale de `marcas[a]` y
`marcas[b-1]` y es exacto por construccion: no hay conteo intermedio que pueda
desviarse.

QUE PASA SI NO CUADRA
---------------------
`de_escena` devuelve `[]`. Sin subtitulo antes que con uno descuadrado, que es la
misma disciplina que ya aplica `cartelas.alinear` («mejor no fingir una
sincronia»): un subtitulo que va medio segundo por detras de la voz se lee peor
que no tenerlo, y ademas miente sobre lo unico que promete.
"""
import difflib
import re

#: Caracteres por linea. Se recalibro entero el 23-08 con el subtitulo: el
#: cuerpo dejo de medirse en px del lienzo de generacion (34) para medirse en
#: px de 1080p (52), porque la capa ya no la escala el zoom.
#:
#: Con Verdana, los 18,07 px por caracter medidos sobre las 49 narraciones del
#: Aurora eran a cuerpo 34; a cuerpo 52 son 27,6, o sea que 42 caracteres
#: pasan de ~760 px a ~1.160. La banda tambien crecio (de 1.100 px de lienzo a
#: 1.400 de 1080p), asi que sigue cabiendo -- con menos holgura, y por eso el
#: numero baja a 38: en dos lineas cabe cualquier trozo y ninguno roza el
#: borde. El reparto de una o dos lineas lo decide despues `dos_lineas`,
#: midiendo de verdad con la fuente.
CAP_LINEA = 38

#: UN SUBTITULO SON DOS LINEAS COMO MUCHO. Tres tapan el plano, y a partir de
#: ahi deja de ser un subtitulo para ser un parrafo encima del video.
CAP_TROZO = CAP_LINEA * 2

#: Si hay una clausula donde partir, se parte ya aqui aunque quepa mas. Leer dos
#: trozos cortos va con el habla; leer uno largo obliga a volver atras.
CAP_BLANDO = 62

#: Por debajo de esto un trozo es un HUERFANO («In California,» solo) y se funde
#: con el vecino que lo admita. Un subtitulo de tres palabras que parpadea medio
#: segundo se lee peor que no estar.
MIN_TROZO = 16

#: UN HUECO CORTO NO SE VE. Entre dos trozos seguidos la voz respira unas
#: decimas, y quitar el subtitulo para volver a ponerlo es un parpadeo: el
#: trozo anterior se queda puesto HASTA que entra el siguiente. Solo se queda
#: la pantalla sin subtitulo cuando el silencio es de verdad (este umbral). Lo
#: pidio el canal con el vertical delante, donde sin fundidos el parpadeo se
#: veia; vale igual en horizontal.
HUECO_SIN_SUBTITULO = 0.4

#: Los tokens que cierran clausula. El guion suelto va aparte porque es una
#: pausa de dictado, no puntuacion pegada a la palabra.
_CIERRA = re.compile(r"[,;:]$")
_GUION = re.compile(r"^[—–-]$")


def _cierra_clausula(token):
    token = str(token or "")
    return bool(_CIERRA.search(token) or _GUION.match(token))


def tramos(palabras, cap_linea=CAP_LINEA, cap_blando=CAP_BLANDO,
           min_trozo=MIN_TROZO, cap_trozo=None, intocables=None):
    """[(a, b), ...] rangos de indices sobre `palabras`, sin solapar y cubriendo.

    Cuatro pasos, portados del motor que ya lo resolvio (el motor anterior,
    `trozos()` en scripts/build-config11.js):

      1. se corta en FRONTERA DE CLAUSULA -- detras de un token que acabe en
         `,;:` o de un guion suelto;
      2. lo que aun no cabe en dos lineas se parte por la mitad, siempre en
         frontera de palabra y eligiendo el corte mas parejo;
      3. se reagrupa mientras quepa comodo en una linea;
      4. un huerfano se funde con el vecino que lo admita.

    Devuelve indices y no texto a proposito: ver la cabecera del modulo.
    """
    palabras = list(palabras or [])
    if not palabras:
        return []
    # `cap_trozo` es el tope del TROZO: dos lineas de siempre, o UNA cuando
    # quien llama lo pide (vertical: un renglon de pocas palabras y nunca dos)
    cap_trozo = int(cap_trozo) if cap_trozo else cap_linea * 2
    # y con el trozo capado a una linea, «comodo» no puede ser mas que eso: el
    # reagrupado del paso 3 volvia a juntar dos renglones por el blando
    cap_blando = min(cap_blando, cap_trozo)
    # CON OTRA LINEA, LOS OTROS DOS TOPES ESCALAN CON ELLA. En vertical la linea
    # es de 16 caracteres (`p7_callouts.cap_subtitulo`): con el blando de 62 y
    # el huerfano de 16 escritos para 38, ningun corte de clausula entraria y
    # todo trozo seria huerfano. Solo cuando quien llama no los ha fijado.
    if cap_linea != CAP_LINEA:
        escala = cap_linea / float(CAP_LINEA)
        if cap_blando == CAP_BLANDO:
            cap_blando = max(cap_linea, int(round(CAP_BLANDO * escala)))
        if min_trozo == MIN_TROZO:
            min_trozo = max(6, int(round(MIN_TROZO * escala)))

    def largo(a, b):
        return len(" ".join(palabras[a:b]))

    # 1 · fronteras de clausula
    rangos, ini = [], 0
    for i, token in enumerate(palabras):
        if i == len(palabras) - 1 or _cierra_clausula(token):
            rangos.append([ini, i + 1])
            ini = i + 1

    # 2 · lo que no cabe se parte por el sitio mas parejo, y NUNCA por dentro
    #     de una cifra: «dos mil | veinticinco» se convertiria en «2000» y
    #     «25», y «un dolar con | ochenta» perderia el «$1,80» (`intocables`
    #     son esos tramos, en indices de palabra; los pone `de_escena`). Solo
    #     si no queda otro corte se parte por dentro.
    dentro = set()
    for a_, b_ in (intocables or ()):
        dentro.update(range(a_ + 1, b_))

    def partir(par):
        a, b = par
        if largo(a, b) <= cap_trozo or b - a < 2:
            return [[a, b]]
        mejor, dif = None, None
        for corte in range(a + 1, b):
            if corte in dentro:
                continue
            distancia = abs(largo(a, corte) - largo(corte, b))
            if dif is None or distancia < dif:
                dif, mejor = distancia, corte
        if mejor is None:
            # todo lo que queda es UNA cifra dicha («un dolar con ochenta»,
            # «mil novecientos noventa y seis»): se deja entera aunque pase
            # del tope, porque escrita en numero es mucho mas corta
            return [[a, b]]
        return partir([a, mejor]) + partir([mejor, b])

    piezas = [trozo for par in rangos for trozo in partir(par)]

    # 3 · se reagrupa mientras quepa comodo
    salida = []
    for a, b in piezas:
        if salida:
            ultimo = salida[-1]
            junto = largo(ultimo[0], b)
            if (junto <= cap_blando
                    or (largo(ultimo[0], ultimo[1]) < min_trozo
                        and junto <= cap_trozo)):
                ultimo[1] = b
                continue
        salida.append([a, b])

    # 4 · los huerfanos se funden
    i = 0
    while i < len(salida) and len(salida) > 1:
        if largo(salida[i][0], salida[i][1]) >= min_trozo:
            i += 1
            continue
        if i > 0 and largo(salida[i - 1][0], salida[i][1]) <= cap_trozo:
            salida[i - 1][1] = salida[i][1]
            salida.pop(i)
            i = max(0, i - 1)
        elif (i < len(salida) - 1
                and largo(salida[i][0], salida[i + 1][1]) <= cap_trozo):
            salida[i + 1][0] = salida[i][0]
            salida.pop(i)
        else:
            i += 1
    return [(a, b) for a, b in salida]


#: Los signos que se quedan pegados a una cifra convertida. Se conservan porque
#: son puntuacion de la frase, no de la palabra: sustituir «sixty-five.» por
#: «65» a secas se comeria el punto y el subtitulo siguiente arrancaria pegado.
_PEGADO_IZQUIERDA = re.compile(r"^[^0-9A-Za-zÀ-ÿ]+")
_PEGADO_DERECHA = re.compile(r"[^0-9A-Za-zÀ-ÿ]+$")


def _cortes_de(palabras):
    """Los indices detras de los que el texto crudo lleva puntuacion.

    Sirve para que una serie de digitos no se trague dos frases: «two, three,
    four times» son tres cosas y no el numero 234. Se mira el token CRUDO
    porque al normalizar la coma desaparece.
    """
    cortes = set()
    for indice, palabra in enumerate(palabras):
        if re.search(r"[,;:.!?…]$", str(palabra or "")):
            cortes.add(indice)
    return cortes


def _cifras_de(palabras, idioma=None):
    """Los tramos de palabras que son UNA cifra dicha. -> [(a, b)]

    La misma cuenta que `limpiar_texto` (medios.cifras_en sobre las palabras
    normalizadas), para que lo que no se parte sea exactamente lo que luego se
    convierte.
    """
    try:
        from . import medios                                   # noqa: PLC0415
    except ImportError:                                        # pragma: no cover
        import medios                                          # noqa: PLC0415
    try:
        llanas = [medios.normalizar_texto(p) for p in palabras]
        return [(a, a + n) for a, n, _ in
                medios.cifras_en(llanas, idioma, _cortes_de(palabras))]
    except Exception:                                          # noqa: BLE001
        return []


def limpiar_texto(palabras, idioma=None):
    """El texto que se DIBUJA a partir de las palabras que se DICEN.

    Dos cosas y ninguna toca los tiempos:

    - las etiquetas de voz ya no estan (`marcas_tts.limpiar` corre mucho antes,
      al repartir las marcas), asi que aqui no hay nada que quitar; y
    - LO QUE SE DICE CON PALABRAS SE ESCRIBE CON NUMEROS. El guion va con todo
      en letra porque lo locuta un sintetizador, pero eso es una
      regla de la VOZ: en pantalla, «one hundred sixty-five companies» se lee
      peor que «165 companies», y «UNC five five three seven» directamente no se
      reconoce como el identificador que es. La vuelta la hace
      `medios.cifras_en`, con las MISMAS tablas con las que el alineador
      reconoce una cifra hablada -- una sola fuente, y por tanto imposible de
      desincronizar.

    SE HACE SOBRE EL TROZO YA ELEGIDO, nunca antes: los tiempos salen de los
    INDICES de palabra, asi que cambiar el numero de palabras antes de trocear
    desplazaria todo lo que viene detras. Aqui el texto puede encoger sin que
    nada se mueva, porque el trozo ya tiene su `desde` y su `hasta`.
    """
    palabras = list(palabras or [])
    if not palabras:
        return ""
    try:
        from . import medios                                   # noqa: PLC0415
    except ImportError:                                        # pragma: no cover
        import medios                                          # noqa: PLC0415
    llanas = [medios.normalizar_texto(p) for p in palabras]
    try:
        tramos = medios.cifras_en(llanas, idioma, _cortes_de(palabras))
    except Exception:                                          # noqa: BLE001
        return " ".join(palabras)
    por_indice = {t[0]: t for t in tramos}
    salida, i = [], 0
    while i < len(palabras):
        tramo = por_indice.get(i)
        if not tramo:
            salida.append(palabras[i])
            i += 1
            continue
        _, cuantas, cifra = tramo
        primero, ultimo = str(palabras[i]), str(palabras[i + cuantas - 1])
        izquierda = _PEGADO_IZQUIERDA.search(primero)
        derecha = _PEGADO_DERECHA.search(ultimo)
        salida.append((izquierda.group(0) if izquierda else "") + cifra
                      + (derecha.group(0) if derecha else ""))
        i += cuantas
    return " ".join(salida)


def repartir_escrito(dibujados, texto):
    """El texto corregido a mano, repartido entre los trozos que ya tienen hora.

    LOS TIEMPOS NO SE TOCAN, y por eso esto reparte en vez de volver a trocear:
    el `desde` y el `hasta` de cada trozo salen del INDICE de la marca de la
    palabra hablada, no de contar el texto dibujado (ver la cabecera del
    modulo). Volver a trocear el texto escrito daria otro numero de trozos y
    habria que repartir los tiempos a ojo, que es exactamente lo que este modulo
    existe para no hacer.

    Se reparte ALINEANDO, no por proporcion: el caso real es corregir una
    palabra («un uno por 100» -> «1%»), asi que casi todo el texto es identico y
    un alineado deja cada palabra en el trozo donde ya estaba. Lo que cambia se
    queda en el trozo de la palabra que sustituye.
    """
    dibujados = [str(t or "") for t in (dibujados or [])]
    texto = " ".join(str(texto or "").split())
    if not dibujados:
        return []
    if not texto:
        return dibujados
    if len(dibujados) == 1:
        return [texto]
    viejas, de_trozo = [], []
    for indice, trozo in enumerate(dibujados):
        for palabra in trozo.split():
            viejas.append(palabra)
            de_trozo.append(indice)
    nuevas = texto.split()
    reparto = [[] for _ in dibujados]
    casador = difflib.SequenceMatcher(
        None, [p.lower() for p in viejas], [p.lower() for p in nuevas],
        autojunk=False)
    for etiqueta, i1, i2, j1, j2 in casador.get_opcodes():
        if etiqueta == "delete":
            continue
        if etiqueta == "equal":
            for salto in range(j2 - j1):
                reparto[de_trozo[i1 + salto]].append(nuevas[j1 + salto])
            continue
        # lo que cambia o lo que se anade va entero al trozo donde EMPEZABA lo
        # que sustituye; si se anade detras del final, al ultimo
        donde = de_trozo[i1] if i1 < len(de_trozo) else len(dibujados) - 1
        reparto[donde].extend(nuevas[j1:j2])
    return [" ".join(p) for p in reparto]


def de_escena(escena, cap_linea=CAP_LINEA, idioma=None, texto="",
              cap_trozo=None):
    """[{"texto", "desde", "hasta"}] en el reloj DEL PLANO, o [] si no cuadra.

    `desde`/`hasta` salen de la primera y la ultima marca del rango, menos el
    `t_in` del plano: los mismos numeros que ya usa todo lo demas.

    Con `texto` manda lo escrito a mano en vez de lo que sale de la narracion.
    Existe porque no habia ninguna forma de corregir una palabra ESCRITA: el
    vocabulario del repaso solo llegaba a `bloque_texto`, que reescribe el guion
    y vuelve a grabar la voz -- para cambiar «un uno por 100» por «1%», eso es
    absurdo. Entra AQUI y no antes de trocear, que es lo unico que importa:
    despues del troceo el texto puede encoger sin que nada se mueva.
    """
    escena = escena if isinstance(escena, dict) else {}
    palabras = str(escena.get("narracion") or "").split()
    marcas = escena.get("marcas") or []
    if not palabras or len(palabras) != len(marcas):
        # LA GUARDA. Sin esto un plano cuyo texto y cuyas marcas no cuadran
        # sacaria el subtitulo desplazado, y un subtitulo desplazado es peor que
        # ninguno: miente sobre lo unico que promete.
        return []
    t_in = float(escena.get("t_in") or 0.0)
    rangos = list(tramos(palabras, cap_linea=cap_linea, cap_trozo=cap_trozo,
                         intocables=_cifras_de(palabras, idioma)))
    dibujados = [limpiar_texto(palabras[a:b], idioma) for a, b in rangos]
    if texto:
        dibujados = repartir_escrito(dibujados, texto)
    salida = []
    for (a, b), escrito in zip(rangos, dibujados):
        try:
            desde = float(marcas[a][0]) - t_in
            hasta = float(marcas[b - 1][1]) - t_in
        except (TypeError, ValueError, IndexError):
            return []
        if hasta < desde:
            hasta = desde
        if not escrito:
            # un trozo que se queda sin texto no se dibuja: el override puede
            # ser mas corto que lo que sustituye
            continue
        salida.append({"texto": escrito,
                       "desde": round(desde, 3), "hasta": round(hasta, 3)})
    # los huecos cortos se cierran: ver HUECO_SIN_SUBTITULO
    for anterior, siguiente in zip(salida, salida[1:]):
        if 0 <= siguiente["desde"] - anterior["hasta"] < HUECO_SIN_SUBTITULO:
            anterior["hasta"] = siguiente["desde"]
    # y el ultimo llega al final del plano si le falta poco: el plano siguiente
    # arranca con su propio subtitulo en cuanto empieza a decirlo
    try:
        fin_plano = float(escena.get("t_out")) - t_in
    except (TypeError, ValueError):
        fin_plano = None
    if salida and fin_plano is not None             and 0 <= fin_plano - salida[-1]["hasta"] < HUECO_SIN_SUBTITULO:
        salida[-1]["hasta"] = round(fin_plano, 3)
    return salida


def dos_lineas(texto, medir, ancho_max):
    """Una linea, o DOS lo mas parejas posible. Nunca tres. -> [str, ...]

    `medir(cadena)` devuelve el ancho en pixeles.

    NO se usa `tipografia.partir` y no es un descuido: `partir` llena la primera
    linea hasta el tope y deja de huerfana la ultima palabra, que en una caja
    alineada a la izquierda no se nota y CENTRADO canta. Medido sobre el S001
    del video largo: `partir` reparte 1.022 px / 116 px («...for two / million») y
    esto reparte 582 / 556. En los cinco planos que se parten en dos, el desnivel
    baja de 618-927 px a 17-64 px.

    `partir` no se toca porque lo usan las cartelas, que van en caja y alineadas
    a la izquierda, y ahi llenar la linea es lo correcto.
    """
    texto = " ".join(str(texto or "").split())
    if not texto or medir(texto) <= ancho_max:
        return [texto] if texto else []
    palabras = texto.split()
    if len(palabras) < 2:
        return [texto]
    mejor, dif = 1, None
    for corte in range(1, len(palabras)):
        arriba = medir(" ".join(palabras[:corte]))
        abajo = medir(" ".join(palabras[corte:]))
        # entre dos repartos igual de parejos gana el que no se pase de ancho
        castigo = max(0.0, arriba - ancho_max) + max(0.0, abajo - ancho_max)
        distancia = abs(arriba - abajo) + castigo * 4
        if dif is None or distancia < dif:
            dif, mejor = distancia, corte
    return [" ".join(palabras[:mejor]), " ".join(palabras[mejor:])]


def banda_fija(ancho=1920, alto=1080, margen=72, ancho_maximo=1400):
    """Donde va el subtitulo: EL PIE DEL CUADRO DE SALIDA. -> {"suelo","centro","ancho"}

    Tres numeros y ninguna cuenta, y eso es la prueba de que el cambio del 23-08
    era el correcto. Aqui vivia `banda_de`, que intersecaba las regiones seguras
    de TODOS los planos del video -- lo que se ve durante el recorrido de camara
    de todos ellos -- y tenia un motivo de verdad: la capa iba DENTRO del grupo
    que hace el zoom, asi que el subtitulo se movia con la imagen. Anclado a la
    region de cada plano saltaba 95 px de un plano al siguiente (medido sobre el
    Aurora); con la interseccion, la deriva en 2:28 bajaba a 19 px.

    Diecinueve pixeles de deriva siguen siendo deriva. El canal lo vio montado y
    pidio que el subtitulo se quede QUIETO, asi que la capa salio del grupo que
    escala (pasos/p7_callouts.capa_de_escena, pasos/p8_render.PAGINA) -- y sin
    zoom debajo no hay region segura que intersecar: el subtitulo vive en el
    cuadro de 1920x1080 y ahi no se mueve nada. La deriva es cero por
    construccion, no por calculo.

    Ojo con el orden si algun dia se deshace: esto SOLO vale con la capa fuera
    del zoom. Con la capa dentro, el pie del cuadro de salida se sale de la
    imagen en cuanto el zoom entra.
    """
    ancho, alto = float(ancho), float(alto)
    return {"suelo": round(alto - float(margen), 1),
            "centro": round(ancho / 2.0, 1),
            "ancho": round(min(float(ancho_maximo), ancho - 2 * float(margen)), 1)}
