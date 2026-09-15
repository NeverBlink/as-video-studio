"""
Referencias de estilo hechas a proposito, en vez de los fotogramas que hubiera.

QUE PROBLEMA RESUELVE
---------------------
La referencia de estilo de un video son fotogramas de OTRO video, y cubren lo que
ese video resulto tener. Si entre ellos no hay un primer plano de cara, el
generador nunca ve como se resuelve una cara en ese estilo -- y una hoja de
personaje se juzga justamente por la cara. Lo mismo con los objetos, los mapas o
un plano general de una sala: se pide que se dibujen «en este estilo» sin haber
ensenado nunca ese estilo aplicado a eso.

Un moodboard es la respuesta: se dibujan A PROPOSITO los ejes que el pipeline
necesita -- una cara, unos cuerpos, un interior, un objeto...-- y esas laminas
sinteticas pasan a ser la referencia. Se generan UNA vez y valen para siempre, y
como se generan una vez se pueden pagar bien y alimentar con muchos mas
fotogramas reales de los que cabria mandar en cada plano.

Medido antes de escribir esto: la hoja de personaje generada con un moodboard de
cuatro ejes salio mas fiel a la referencia que la generada con la lamina de los
siete fotogramas reales.

EL RIESGO, Y POR QUE HAY UNA PERSONA EN MEDIO
---------------------------------------------
El moodboard lo dibuja el mismo modelo que despues lo imita: es copiar una copia.
Si deriva, la deriva se congela y la heredan TODAS las imagenes de TODOS los
videos que usen ese estilo, sin que nadie vuelva a mirar los fotogramas
originales. No es teorico -- en la primera prueba, de cuatro ejes, la cara y los
cuerpos salieron clavados y el interior y el objeto derivaron: sombreado suave en
un sofa y una taza con degradado y sombra proyectada, justo lo que la guia
prohibe.

Por eso:
  - un moodboard nace PROPUESTO y solo lo usa el paso de assets cuando alguien lo
    ha aprobado mirandolo;
  - se corrige POR EJE, con una peticion escrita ("los brazos eran mas
    delgados"), porque en la practica derivan unos ejes y otros no, y rehacerlo
    entero tiraria los que ya estaban bien;
  - la guia ESCRITA se sigue sacando de los fotogramas REALES, nunca del
    moodboard, para que las palabras no deriven jamas;
  - y un moodboard nunca se genera a partir de otro moodboard.

DONDE VIVE
----------
    banco/moodboards/<clave>/              aprobado, global, reutilizable
    banco/moodboards/_propuestas/<clave>/  propuesto, pendiente de mirar

La clave identifica AL ESTILO y no al video: sale del CONTENIDO de los
fotogramas elegidos, asi que dos videos con las mismas referencias comparten
moodboard y el segundo no paga nada. Que sea del contenido y no de la ruta es lo
que hace que un preset de estilo -- que copia los fotogramas a su propia carpeta
del banco -- siga encontrando el mismo moodboard.

Las dos carpetas conviven, y por eje
------------------------------------
Aprobar no es mover la carpeta entera: las laminas de la propuesta se COPIAN
encima de las del banco, eje por eje. Antes se movia el directorio, y rehacer un
solo eje de un moodboard ya aprobado se llevaba por delante los otros cinco
--quedaba en el banco una carpeta con una unica lamina--. Por lo mismo, la ficha
de un estilo mezcla las dos carpetas: de cada eje manda la propuesta si la hay,
que es lo ultimo dibujado y lo que esta pendiente de mirar.
"""
import math
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor

import medios

PASO = "moodboard"
PROPUESTAS = "_propuestas"

#: Los ejes que un video necesita ver resueltos. El sujeto es GENERICO a
#: proposito: lo que tiene que viajar es el estilo, nunca el contenido -- ni los
#: personajes ni los sitios de la produccion de la que salen los fotogramas.
EJES = {
    "cara": {
        "titulo": "Una cara de cerca",
        "prompt": ("A single character seen in close-up, head and shoulders, "
                   "front view, neutral serious expression, plain flat "
                   "background. Nothing else in the frame."),
    },
    "cuerpos": {
        "titulo": "Varias personas de cuerpo entero",
        "prompt": ("Three ordinary people standing side by side, full body, "
                   "front view, plain flat background, relaxed neutral poses."),
    },
    "interior": {
        "titulo": "Un interior general",
        "prompt": ("A wide shot of an ordinary interior room with furniture, "
                   "seen from a corner, with no people in it."),
    },
    "exterior": {
        "titulo": "Un exterior general",
        "prompt": ("A wide exterior shot of an ordinary street with buildings "
                   "and sky, with no people in it."),
    },
    "objeto": {
        "titulo": "Un objeto de cerca",
        "prompt": ("A close-up of a single everyday object resting on a flat "
                   "surface, filling most of the frame, plain background."),
    },
    # CON SUS ETIQUETAS, que es lo que hace que un diagrama sea un diagrama.
    # Decia "with no text or labels of any kind" y salian tres cajas vacias: la
    # lamina que tiene que ensenar como se rotula este canal era justo la que
    # tenia el rotulo prohibido.
    "diagrama": {
        "titulo": "Un diagrama sencillo",
        "prompt": ("A simple schematic diagram of three boxes connected by "
                   "arrows on a plain background, drawn in the same style. Each "
                   "box holds a simple icon and one short word under it."),
    },
}

#: Que ejes le importan a un plano segun lo que salga en el. Se manda UN tile por
#: plano -- no varios -- porque cada imagen de referencia se paga en la entrada de
#: CADA llamada, y la entrada es el grueso de la factura. Lo que cambia no es
#: cuantas, sino cuales.
POR_CONTENIDO = {
    "personajes": ("cara", "cuerpos"),
    "sitio": ("interior", "exterior"),
    "componente": ("diagrama", "objeto"),
    "suelto": ("objeto", "cara"),
}

#: Cuantos ejes caben en un tile. Cuatro en 2x2 deja cada uno a 768x512, contra
#: los 340x227 de una lamina de siete fotogramas.
POR_TILE = 4


def raiz_banco(raiz=None):
    """Carpeta de los moodboards aprobados."""
    return os.path.join(raiz or medios.BANCO, "moodboards")


def raiz_propuestas(raiz=None):
    return os.path.join(raiz_banco(raiz), PROPUESTAS)


def clave_de(referencias):
    """Identidad del ESTILO: sus fotogramas, no el video que los eligio.

    Dos videos con las mismas referencias comparten moodboard, y el segundo no
    paga ni una imagen.
    """
    huellas = sorted(medios.huella_fichero(r) for r in referencias
                     if os.path.exists(r))
    if not huellas:
        return ""
    return medios.huella(huellas)


def carpeta_de(referencias, raiz=None, incluir_propuestas=True):
    """Donde vive el moodboard de estas referencias, aprobado o propuesto."""
    clave = clave_de(referencias)
    if not clave:
        return None
    aprobado = os.path.join(raiz_banco(raiz), clave)
    if os.path.isdir(aprobado):
        return aprobado
    propuesta = os.path.join(raiz_propuestas(raiz), clave)
    if incluir_propuestas and os.path.isdir(propuesta):
        return propuesta
    return None


def ficha_de(referencias, raiz=None):
    """Que hay hecho de este estilo: sus ejes, su estado y con que guia se hizo.

    Mira las DOS carpetas y las mezcla eje por eje: de cada eje manda la lamina
    de la propuesta si existe, porque es la ultima dibujada y la que esta
    esperando a que alguien la mire. `pendientes` son justo esos.
    """
    clave = clave_de(referencias)
    if not clave:
        return {"estado": "falta", "clave": "", "ejes": {}, "pendientes": []}
    banco = os.path.join(raiz_banco(raiz), clave)
    propuesta = os.path.join(raiz_propuestas(raiz), clave)

    ficha = medios.leer_json(os.path.join(banco, "ficha.json"), {}) or {}
    nueva = medios.leer_json(os.path.join(propuesta, "ficha.json"), {}) or {}
    coste = (float(ficha.get("coste_usd") or 0.0)
             + float(nueva.get("coste_usd") or 0.0))
    peticiones = dict(ficha.get("peticiones") or {})
    peticiones.update(nueva.get("peticiones") or {})
    ficha.update({k: v for k, v in nueva.items()
                  if k not in ("coste_usd", "peticiones", "estado")})
    ficha["clave"] = clave
    ficha["coste_usd"] = round(coste, 4) if coste else ficha.get("coste_usd")
    ficha["peticiones"] = peticiones

    ejes, pendientes = {}, []
    for eje in sorted(EJES):
        en_propuesta = os.path.join(propuesta, f"{eje}.png")
        en_banco = os.path.join(banco, f"{eje}.png")
        if os.path.exists(en_propuesta):
            ejes[eje] = en_propuesta
            pendientes.append(eje)
        elif os.path.exists(en_banco):
            ejes[eje] = en_banco
    ficha["ejes"] = ejes
    ficha["pendientes"] = pendientes
    ficha["carpeta"] = banco if os.path.isdir(banco) else (
        propuesta if os.path.isdir(propuesta) else None)
    # El estado del conjunto es el del eje mas atrasado: con una sola lamina sin
    # mirar, el moodboard NO se usa en produccion y decir «aprobado» mentiria.
    ficha["estado"] = ("falta" if not ejes
                       else ("propuesto" if pendientes else "aprobado"))
    return ficha


#: De donde sale cada lamina. Va en la URL con la que la sirve la interfaz para
#: que rehacer un eje de un moodboard ya aprobado ensene el NUEVO y no el viejo.
ORIGENES = ("banco", "propuesta")


def carpeta_por_origen(clave, origen, raiz=None):
    """La carpeta de un moodboard en el banco o entre las propuestas."""
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido: {origen!r}. "
                         f"Los origenes son: {', '.join(ORIGENES)}")
    base = raiz_banco(raiz) if origen == "banco" else raiz_propuestas(raiz)
    return os.path.join(base, str(clave))


def origen_de(ficha, eje):
    """'propuesta' si ese eje esta sin mirar, 'banco' si ya esta aprobado."""
    return "propuesta" if eje in (ficha.get("pendientes") or []) else "banco"


def version_de(ruta):
    """Sello de la lamina, para que el navegador no ensene la cacheada.

    Sin esto, rehacer un eje deja la MISMA url apuntando a otra imagen y el
    navegador sigue pintando la anterior: la correccion parece no haber hecho
    nada, que es justo lo contrario de lo que hay que poder ver aqui.
    """
    try:
        return int(os.path.getmtime(ruta))
    except OSError:
        return 0


def ejes_de_plano(escena):
    """Los ejes que le tocan a un plano, por lo que sale en el.

    Devuelve SIEMPRE POR_TILE ejes: los que pide el plano primero y el resto
    detras en orden fijo. Fijo y no aleatorio porque el tile se cachea por esa
    combinacion, y porque dos planos iguales tienen que recibir lo mismo.
    """
    escena = escena or {}
    pedidos = []
    if escena.get("personajes"):
        pedidos.extend(POR_CONTENIDO["personajes"])
    if escena.get("set"):
        pedidos.extend(POR_CONTENIDO["sitio"])
    if escena.get("componente"):
        pedidos.extend(POR_CONTENIDO["componente"])
    if not pedidos:
        pedidos.extend(POR_CONTENIDO["suelto"])
    for eje in EJES:
        if eje not in pedidos:
            pedidos.append(eje)
    vistos, orden = set(), []
    for eje in pedidos:
        if eje not in vistos:
            vistos.add(eje)
            orden.append(eje)
    return orden[:POR_TILE]


def tile_para(escena, referencias, cache, raiz=None):
    """El tile de estilo que le toca a este plano, o None si no hay moodboard.

    Solo se usa un moodboard APROBADO: uno propuesto no ha pasado por delante de
    nadie, y el fallo que este modulo puede tener -- derivar del estilo original --
    no se ve leyendo codigo, se ve mirando la imagen.
    """
    carpeta = carpeta_de(referencias, raiz, incluir_propuestas=False)
    if not carpeta:
        return None
    ejes = [e for e in ejes_de_plano(escena)
            if os.path.exists(os.path.join(carpeta, f"{e}.png"))]
    if not ejes:
        return None
    destino = os.path.join(cache, f"tile_{'_'.join(ejes)}.png")
    if os.path.exists(destino):
        return destino
    rutas = [os.path.join(carpeta, f"{e}.png") for e in ejes]
    return _montar(rutas, destino)


def _montar(rutas, destino):
    """Las laminas en una sola imagen, en cuadricula y sin separadores."""
    from PIL import Image
    fotos = []
    for ruta in rutas:
        try:
            fotos.append(Image.open(ruta).convert("RGB"))
        except Exception:                      # noqa: BLE001
            continue
    if not fotos:
        return None
    columnas = 1 if len(fotos) == 1 else 2
    filas = int(math.ceil(len(fotos) / columnas))
    ancho, alto = TAMANO[0] // columnas, TAMANO[1] // filas
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


#: Lado del tile. La misma proporcion en la que se generan los planos.
TAMANO = (1536, 1024)


def _nombre_en(idioma):
    """Codigo de idioma -> nombre EN INGLES para el prompt, o "".

    Tarde y a proposito, como el resto de los imports de este modulo: p2_brief
    arrastra medio paquete y aqui solo hace falta su tabla de nombres. Se usa la
    SUYA y no una copia: dos tablas de idiomas se desincronizan el dia que se
    anada uno.
    """
    codigo = str(idioma or "").strip().lower()
    if not codigo:
        return ""
    try:
        from . import p2_brief                              # noqa: PLC0415
    except ImportError:
        try:
            import p2_brief                                 # noqa: PLC0415
        except ImportError:
            return ""
    return p2_brief.nombre_idioma_en(codigo)


def prompt_de_eje(eje, estilo, peticion="", guia_escrita=None, reglas=None,
                  con_lamina=True, idioma=""):
    """Lo que se le pide al generador para una lamina de estilo.

    Lleva la guia escrita entera y el bloque de reglas de la casa, igual que un
    plano. En la primera prueba se monto este prompt a mano sin las reglas y los
    tres cuerpos salieron SONRIENDO, con la regla que lo prohibe escrita y sin
    llegar: eso no puede depender de que alguien se acuerde.

    `con_lamina=False` es el caso del estilo DESCRITO, que no tiene fotogramas
    reales: sin adjunto, hablar de "reference image 1" seria mandarle a mirar
    algo que no existe, y un prompt que describe un adjunto ausente se responde
    con cualquier cosa. Lo que queda entonces es la guia escrita, que en ese
    camino es toda la verdad del estilo.
    """
    ficha = EJES.get(eje) or {}
    return prompt_de_dibujo(ficha.get("prompt") or "", estilo, peticion,
                            guia_escrita, reglas, con_lamina, idioma=idioma)


def prompt_de_dibujo(descripcion, estilo, peticion="", guia_escrita=None,
                     reglas=None, con_lamina=True, encabezado=None, idioma=""):
    """El prompt de UNA ilustracion suelta en el estilo del canal.

    Es el cuerpo de `prompt_de_eje`, sacado a una funcion porque lo necesita
    tambien la MUESTRA de un preset (`presets_light`): una escena de ejemplo
    dibujada con este estilo, para la miniatura de la tarjeta. Los dos piden lo
    mismo --una imagen suelta, con la guia escrita entera y las reglas de la
    casa-- y con dos constructores uno de los dos se quedaria sin las reglas,
    que es exactamente el fallo que salio la primera vez (los tres cuerpos
    SONRIENDO con la regla que lo prohibe escrita y sin llegar).
    """
    lineas = [encabezado
              or "Draw one single illustration for a style reference sheet."]
    if con_lamina:
        lineas.append("Reference image 1 is a STYLE SHEET: copy the drawing style it "
                      "shows -- line weight, palette, shapes, proportions, how faces "
                      "and volumes are resolved -- and never its content, its "
                      "characters, its framing or its layout. Your output is ONE "
                      "single full-bleed illustration, never a grid or a collage.")
    else:
        lineas.append("Your output is ONE single full-bleed illustration, never "
                      "a grid or a collage. The written style guide below is the "
                      "only description of how this production is drawn: follow "
                      "every one of its numbers exactly.")
    if guia_escrita:
        lineas.extend(guia_escrita)
    lineas.append(str(descripcion or ""))
    if peticion:
        # La correccion de quien mira manda sobre la descripcion generica: es lo
        # que hace que «los brazos eran mas delgados» sirva de algo.
        lineas.append(f"Correction, this takes priority: {peticion}")
    if reglas:
        lineas.append(reglas)
    # CUAL es el idioma del canal. La POLITICA la trae la regla
    # `texto-dibujado-en-el-idioma-del-video` dentro de `reglas`; aqui solo se
    # dice el dato, que es lo unico que la regla no puede saber.
    #
    # Y HACE FALTA JUSTO AQUI, mas que en un plano: la lamina del eje «diagrama»
    # viaja despues como imagen de referencia dentro de cada plano que lleve un
    # componente (`POR_CONTENIDO`), o sea que si sale rotulada en el idioma
    # equivocado ensena a rotular mal CON UN EJEMPLO DIBUJADO, y eso ningun
    # texto lo contradice del todo. De ahi salio el «PLAN / DO / REVIEW» de un
    # canal en espanol.
    nombre = _nombre_en(idioma)
    if nombre:
        lineas.append(f"The language of this production is {nombre}.")
    # Aqui iba «No text, no letters, no numbers, no watermarks anywhere». Lo que
    # se puede y lo que no lo dice ahora la regla `texto-en-imagen-permitido-
    # pero-raro`, que llega en `reglas` y vale para las laminas y para los planos
    # a la vez: prohibirlo aqui la contradecia una linea despues.
    lineas.append("No watermarks.")
    return " ".join(x for x in lineas if x)


def generar(referencias, estilo, ejes=None, peticiones=None, calidad="medium",
            avisar=None, raiz=None, idioma=""):
    """Dibuja las laminas de estilo que faltan y las deja PROPUESTAS.

    'ejes' None son todos; con una lista se rehacen solo esos, que es lo que
    hace util el feedback: en la practica derivan unos y otros salen clavados, y
    rehacer entero tiraria los buenos.

    'peticiones' es {eje: "lo que hay que corregir"}, y manda sobre la
    descripcion generica de ese eje.

    Calidad media por defecto: esto se genera UNA vez por estilo y lo hereda
    cualquier video que lo use, asi que ahorrar aqui es ahorrar en el sitio
    equivocado.
    """
    imagen = medios.motor("imagen_openai/imagen.py")
    reglas = medios.motor("reglas/reglas.py")
    avisar = avisar or (lambda *a, **k: None)
    rutas = [r for r in (referencias or []) if os.path.exists(r)]
    if len(rutas) < 3:
        raise RuntimeError("hacen falta al menos 3 fotogramas de referencia para "
                           "dibujar un moodboard: con menos se copia una escena, "
                           "no un estilo")
    clave = clave_de(rutas)
    pedidos = [e for e in (ejes or EJES) if e in EJES]
    peticiones = peticiones or {}

    cache = os.path.join(raiz_propuestas(raiz), clave, "_refs")
    os.makedirs(cache, exist_ok=True)
    # Los fotogramas REALES, y todos los que quepan: esto se paga una vez, asi
    # que aqui no hay motivo para escatimar ejemplos como en cada plano.
    lamina = _montar([imagen.normalizar(r, cache) for r in rutas],
                     os.path.join(cache, "reales.png"))
    refs = [imagen.normalizar(lamina, cache)]

    # tarde y a proposito: p6_assets importa este modulo, asi que importarlo
    # arriba seria un circulo. La guia se dice en UN sitio -- escribirla dos veces
    # es el fallo que dejo las hojas de personaje en otro estilo durante meses.
    import p6_assets
    guia = p6_assets.guia_escrita(estilo)
    bloque = reglas.bloque_prompt("prompt_imagen")
    ficha = medios.leer_json(
        os.path.join(raiz_propuestas(raiz), clave, "ficha.json"), {}) or {}
    ficha.setdefault("clave", clave)
    ficha["referencias"] = rutas
    ficha["guia"] = (estilo.get("guia") or {}).get("guia") if isinstance(
        estilo.get("guia"), dict) else estilo.get("guia")
    ficha.setdefault("peticiones", {})

    # EN CADENAS, NO EN FILA. Esto era un bucle recto: seis ejes a ~1 min cada
    # uno son seis minutos mirando «2 de 6». Y no habia motivo -- p6 SI reparte
    # (`_en_cadenas`), y el tope de llamadas simultaneas al motor de imagen
    # (`MAX_CADENAS`) es un limite del OTRO LADO que ya vive alli.
    #
    # Aqui el reparto es ademas mas simple que el de p6: alli se reparte POR
    # SITIO porque dentro de un sitio cada plano se apoya en el anterior, y la
    # continuidad no puede depender de que hilo llegue antes. Los ejes de un
    # moodboard son INDEPENDIENTES entre si -- cada uno dibuja otra cosa con las
    # mismas referencias --, asi que se reparten uno por hilo y ya.
    #
    # El orden de `hechos` y el gasto salen indexados y se recomponen despues:
    # una lista compartida entre hilos daria un orden distinto en cada pasada, y
    # este resultado se escribe en la ficha del banco.
    # `p6_assets` ya esta importado unas lineas mas arriba (guia_escrita), y
    # tarde a proposito: p6 importa este modulo, asi que arriba seria un circulo.
    cadenas = max(1, min(len(pedidos), p6_assets.MAX_CADENAS))
    resultados = [None] * len(pedidos)
    hechas = [0]
    candado = threading.Lock()

    def dibujar(indice, eje):
        prompt = prompt_de_eje(eje, estilo, peticiones.get(eje), guia, bloque,
                               idioma=idioma)
        png, meta = imagen.generar(prompt, refs, quality=calidad,
                                   tamano="apaisado")
        guardar(clave, eje, png, raiz)
        resultados[indice] = (eje, float(meta.get("coste") or 0.0))
        # LA BARRA CUENTA LO TERMINADO, no lo empezado: con varias a la vez, «3
        # de 6» tiene que significar tres dibujadas. El candado es por la cuenta,
        # no por el dibujo.
        with candado:
            hechas[0] += 1
            avisar(hechas[0] / max(1, len(pedidos)),
                   f"{hechas[0]} de {len(pedidos)} referencias dibujadas")

    avisar(0.02, f"dibujando {len(pedidos)} referencias"
                 + (f", {cadenas} a la vez" if cadenas > 1 else ""))
    if cadenas <= 1:
        for indice, eje in enumerate(pedidos):
            dibujar(indice, eje)
    else:
        # se recoge el resultado de cada hilo para que un fallo vuelva a
        # levantarse aqui en vez de quedarse tragado dentro de su hilo
        with ThreadPoolExecutor(max_workers=cadenas) as pool:
            for tarea in [pool.submit(dibujar, i, e)
                          for i, e in enumerate(pedidos)]:
                tarea.result()

    hechos, gasto = [], 0.0
    for par in resultados:
        if not par:
            continue
        eje, coste = par
        if peticiones.get(eje):
            ficha["peticiones"][eje] = peticiones[eje]
        gasto += coste
        hechos.append(eje)
    ficha["coste_usd"] = round(float(ficha.get("coste_usd") or 0.0) + gasto, 4)
    medios.escribir_json(
        os.path.join(raiz_propuestas(raiz), clave, "ficha.json"), ficha)
    avisar(1.0, f"{len(hechos)} referencia(s) dibujadas, {gasto:.3f} USD")
    return {"clave": clave, "ejes": hechos, "coste_usd": round(gasto, 4),
            "estado": "propuesto"}


def guardar(clave, eje, png, raiz=None, ficha=None):
    """Deja una lamina en la propuesta de ese estilo."""
    carpeta = os.path.join(raiz_propuestas(raiz), clave)
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, f"{eje}.png")
    with open(destino, "wb") as fh:
        fh.write(png)
    if ficha is not None:
        medios.escribir_json(os.path.join(carpeta, "ficha.json"), ficha)
    return destino


def aprobar(referencias, raiz=None):
    """Mete la propuesta en el banco global. Es la decision de una persona.

    Se copia EJE A EJE encima de lo que ya hubiera en el banco, y solo entonces
    se tira la propuesta. Antes se movia la carpeta entera, y eso significaba
    que rehacer un eje de un moodboard ya aprobado --que es el caso normal:
    cinco salen bien y uno deriva-- dejaba en el banco una carpeta con esa unica
    lamina y borraba las otras cinco sin decirlo.
    """
    clave = clave_de(referencias)
    origen = os.path.join(raiz_propuestas(raiz), clave)
    if not clave or not os.path.isdir(origen):
        raise RuntimeError("no hay ningun moodboard propuesto para este estilo "
                           "que aprobar")
    destino = os.path.join(raiz_banco(raiz), clave)
    os.makedirs(destino, exist_ok=True)

    aprobadas = []
    for eje in sorted(EJES):
        lamina = os.path.join(origen, f"{eje}.png")
        if os.path.exists(lamina):
            shutil.copyfile(lamina, os.path.join(destino, f"{eje}.png"))
            aprobadas.append(eje)

    ficha = medios.leer_json(os.path.join(destino, "ficha.json"), {}) or {}
    nueva = medios.leer_json(os.path.join(origen, "ficha.json"), {}) or {}
    coste = (float(ficha.get("coste_usd") or 0.0)
             + float(nueva.get("coste_usd") or 0.0))
    peticiones = dict(ficha.get("peticiones") or {})
    peticiones.update(nueva.get("peticiones") or {})
    ficha.update({k: v for k, v in nueva.items()
                  if k not in ("coste_usd", "peticiones", "estado")})
    ficha.update({"clave": clave, "estado": "aprobado",
                  "coste_usd": round(coste, 4), "peticiones": peticiones})
    medios.escribir_json(os.path.join(destino, "ficha.json"), ficha)
    shutil.rmtree(origen, ignore_errors=True)
    return {"clave": clave, "carpeta": destino, "estado": "aprobado",
            "ejes": aprobadas}


# ------------------------------------------------- viajar dentro de un preset
#
# Un preset de estilo copia sus fotogramas a banco/presets/<id>/ para no
# depender de la carpeta del proyecto donde se creo. La clave de un moodboard
# sale del CONTENIDO de esos fotogramas, asi que la copia encuentra el mismo
# moodboard sin hacer nada... mientras el banco de moodboards siga entero.
#
# No basta. El banco es una carpeta del disco, y un preset que dice "estas son
# mis referencias dibujadas" tiene que poder cumplirlo el dia que esa carpeta se
# limpie o el preset se lleve a otra maquina. Por eso las laminas APROBADAS se
# copian tambien dentro del preset, y al aplicarlo se devuelven al banco si no
# estan. Es la misma regla que ya seguian los fotogramas: un preset se guarda
# entero o no se guarda.

def exportar(referencias, destino, raiz=None):
    """Copia a `destino` las laminas APROBADAS de este estilo.

    Solo las aprobadas: una propuesta no ha pasado por delante de nadie, y
    meterla en un preset es congelar en el canal una deriva que nadie ha visto.
    """
    clave = clave_de(referencias)
    banco = os.path.join(raiz_banco(raiz), clave) if clave else ""
    if not clave or not os.path.isdir(banco):
        return None
    ejes = [e for e in sorted(EJES)
            if os.path.exists(os.path.join(banco, f"{e}.png"))]
    if not ejes:
        return None
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino, exist_ok=True)
    for eje in ejes:
        shutil.copyfile(os.path.join(banco, f"{eje}.png"),
                        os.path.join(destino, f"{eje}.png"))
    ficha = medios.leer_json(os.path.join(banco, "ficha.json"), {}) or {}
    ficha["clave"] = clave
    medios.escribir_json(os.path.join(destino, "ficha.json"), ficha)
    return {"clave": clave, "ejes": ejes, "carpeta": destino}


def importar(carpeta, clave, raiz=None):
    """Devuelve al banco las laminas guardadas dentro de un preset.

    No pisa lo que ya hubiera: si el moodboard sigue en el banco, esto no hace
    nada. Solo rellena los ejes que falten, que es el caso de una maquina nueva
    o de un banco que alguien ha limpiado.
    """
    clave = str(clave or "")
    if not clave or not os.path.isdir(carpeta):
        return {"clave": clave, "ejes": []}
    destino = os.path.join(raiz_banco(raiz), clave)
    os.makedirs(destino, exist_ok=True)
    devueltos = []
    for eje in sorted(EJES):
        lamina = os.path.join(carpeta, f"{eje}.png")
        final = os.path.join(destino, f"{eje}.png")
        if os.path.exists(lamina) and not os.path.exists(final):
            shutil.copyfile(lamina, final)
            devueltos.append(eje)
    if devueltos and not os.path.exists(os.path.join(destino, "ficha.json")):
        ficha = medios.leer_json(os.path.join(carpeta, "ficha.json"), {}) or {}
        ficha.update({"clave": clave, "estado": "aprobado"})
        medios.escribir_json(os.path.join(destino, "ficha.json"), ficha)
    return {"clave": clave, "ejes": devueltos, "carpeta": destino}


# ---------------------------------------------- estilo DESCRITO, sin fotogramas
#
# En modo light el canal puede describir su estilo con palabras en vez de dar un
# video. Entonces no hay fotogramas reales, y todo lo de arriba --la clave por
# contenido, el banco compartido, el aprobado-- deja de tener sentido: la clave
# de un moodboard es la huella de SUS FOTOGRAMAS, y aqui no hay ninguno.
#
# Lo que si tiene sentido es dibujar los mismos ejes a partir de la guia escrita,
# y que esas laminas pasen a ser las REFERENCIAS del estilo. No hay moodboard
# encima de nada: las laminas dibujadas son el material de referencia, y desde
# ahi todo lo de abajo (la lamina de p6, la hoja de personaje, cada plano)
# funciona sin enterarse de que no vienen de ningun video.
#
# Y NO se escribe la guia mirandolas despues. Seria describir una copia, que es
# justo lo que la cabecera de este modulo dice que no se haga nunca: la guia sale
# de las palabras del canal y las laminas salen de la guia, en ese orden.

def dibujar_desde_guia(estilo, destino, ejes=None, calidad="medium",
                       avisar=None, idioma="", peticiones=None):
    """Dibuja las laminas de un estilo DESCRITO. -> {rutas, ejes, coste_usd}.

    Sin fotogramas de entrada y sin tocar el banco de moodboards: las laminas se
    dejan en `destino`, que es de quien las pide (el taller de un preset), y lo
    que devuelve son rutas de ficheros normales.

    'peticiones' es {eje: "lo que hay que corregir"}, igual que en `generar`, y
    manda sobre la descripcion generica de ese eje. LO MISMO EN LOS DOS CAMINOS
    y no solo en el del video: quien corrige una lamina suelta escribe una frase
    y no sabe --ni tiene por que-- si su estilo salio de una URL o de una
    descripcion. Sin esto, el estilo descrito aceptaba el encargo, redibujaba esa
    lamina con su descripcion generica de siempre, pagaba la imagen y devolvia
    otra vez lo mismo, con la correccion dada por aplicada.
    """
    imagen = medios.motor("imagen_openai/imagen.py")
    reglas = medios.motor("reglas/reglas.py")
    avisar = avisar or (lambda *a, **k: None)
    pedidos = [e for e in (ejes or EJES) if e in EJES]
    if not pedidos:
        raise RuntimeError("no hay ningun eje que dibujar")
    peticiones = peticiones or {}
    os.makedirs(destino, exist_ok=True)

    # tarde y a proposito, igual que en `generar`: p6_assets importa este modulo
    import p6_assets                                        # noqa: PLC0415
    guia = p6_assets.guia_escrita(estilo)
    if not guia:
        raise RuntimeError(
            "un estilo descrito no tiene fotogramas, asi que la guia escrita es "
            "lo unico que describe el dibujo: sin ella las laminas saldrian con "
            "el estilo por defecto del generador")
    bloque = reglas.bloque_prompt("prompt_imagen")

    resultados = [None] * len(pedidos)
    hechas = [0]
    candado = threading.Lock()

    def dibujar(indice, eje):
        # Encabezado NEUTRO en cuanto al medio: sin fotogramas reales, la guia
        # escrita es lo unico que dice si este canal se dibuja o se fotografia,
        # y "draw an illustration" la contradiria de entrada. El camino con
        # video no pasa por aqui y conserva su encabezado de siempre.
        prompt = prompt_de_dibujo(
            (EJES.get(eje) or {}).get("prompt") or "", estilo,
            peticiones.get(eje), guia, bloque,
            con_lamina=False,
            encabezado="Produce one single full-frame image for a style "
                       "reference sheet.")
        # SIN referencias: no hay ninguna que mandar, y mandar una lamina vacia
        # es lo que provoca el "Unsupported content type" que no dice nada.
        png, meta = imagen.generar(prompt, [], quality=calidad,
                                   tamano="apaisado")
        ruta = os.path.join(destino, f"{eje}.png")
        with open(ruta, "wb") as fh:
            fh.write(png)
        resultados[indice] = (eje, ruta, float(meta.get("coste") or 0.0))
        with candado:
            hechas[0] += 1
            avisar(hechas[0] / max(1, len(pedidos)),
                   f"{hechas[0]} de {len(pedidos)} referencias dibujadas")

    cadenas = max(1, min(len(pedidos), p6_assets.MAX_CADENAS))
    avisar(0.02, f"dibujando {len(pedidos)} referencias a partir de la guia"
                 + (f", {cadenas} a la vez" if cadenas > 1 else ""))
    if cadenas <= 1:
        for indice, eje in enumerate(pedidos):
            dibujar(indice, eje)
    else:
        with ThreadPoolExecutor(max_workers=cadenas) as pool:
            for tarea in [pool.submit(dibujar, i, e)
                          for i, e in enumerate(pedidos)]:
                tarea.result()

    rutas, hechos, gasto = [], [], 0.0
    for trio in resultados:
        if not trio:
            continue
        eje, ruta, coste = trio
        hechos.append(eje)
        rutas.append(ruta)
        gasto += coste
    avisar(1.0, f"{len(hechos)} referencia(s) dibujadas, {gasto:.3f} USD")
    return {"rutas": rutas, "ejes": hechos, "coste_usd": round(gasto, 4),
            "origen": "descrito"}
