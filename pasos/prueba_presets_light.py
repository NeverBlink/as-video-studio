"""Prueba del modo light: el plan y la MUESTRA que hace de cara del preset.

Por que hay una suite propia para esto
--------------------------------------
La muestra es lo unico del modo light que no se puede mirar sin pagar: se compone
DESPUES de dibujar cuatro planos, o sea despues de gastar. Si el compositor falla
--una capa en el espacio equivocado, una cartela sin sus datos, un SVG que el
navegador no rasteriza-- el fallo aparece con las imagenes ya pagadas.

Asi que aqui se compone con PNG de mentira: los planos son rectangulos de
colores y lo que se prueba es lo de encima, que es lo que puede romperse. El
rasterizado va por Edge, igual que el render.

    python pasos/prueba_presets_light.py

Se salta la parte de navegador con --sin-navegador (para una maquina sin Edge).
"""
import argparse
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import cartelas                                             # noqa: E402
import presets_light as light                               # noqa: E402

_ok = 0
_fallos = []


def ok(condicion, mensaje):
    global _ok
    if condicion:
        _ok += 1
        return True
    _fallos.append(mensaje)
    print(f"      FALLO: {mensaje}")
    return False


def igual(obtenido, esperado, mensaje):
    return ok(obtenido == esperado,
              f"{mensaje} (esperaba {esperado!r}, llego {obtenido!r})")


def seccion(titulo):
    print(f"\n  {titulo}")


#: El encargo minimo que vale. El estilo grafico son IMAGENES --de un parrafo
#: suelto la guia se inventa todo lo que el parrafo no diga-- y el tono se
#: escribe: no hay nada que copiar, hay algo que decidir.
ENCARGO_VIDEO = {
    "nombre": "Canal de prueba", "idioma": "es",
    "estilo_imagenes": ["a.png", "b.png"],
    "estilo_prompt": "dibujo plano de linea gruesa",
    "tono_prompt": "serio pero cercano, sin dramatismo",
    "voz_prompt": "grave, pausada, sin sonar a locutor",
}


def probar_encargo():
    seccion("EL ENCARGO SE VALIDA ANTES DE GASTAR")
    limpio = light.validar_encargo(dict(ENCARGO_VIDEO, nombre="  Canal  "))
    igual(limpio["nombre"], "Canal", "el nombre se limpia")
    igual(limpio["idioma"], "es", "el idioma viaja")

    casos = [
        (dict(ENCARGO_VIDEO, nombre=""), "sin nombre"),
        (dict(ENCARGO_VIDEO, idioma="kl"), "con un idioma que no existe"),
        # DESCRIBIRLO A SECAS NO ES UN CAMINO: el estilo se COPIA de unas
        # imagenes, y de un parrafo solo la guia se inventa todo lo que el
        # parrafo no diga. Lo escrito acompana, y por eso es opcional.
        (dict(ENCARGO_VIDEO, estilo_imagenes=[]),
         "con indicaciones pero sin imagenes"),
        (dict(ENCARGO_VIDEO, voz_prompt=""), "sin voz"),
        (dict(ENCARGO_VIDEO, tono_prompt=""), "sin tono"),
        (dict(ENCARGO_VIDEO, tono_prompt="cor"), "con un tono de tres letras"),
    ]
    for crudo, etiqueta in casos:
        try:
            light.validar_encargo(crudo)
            ok(False, f"un encargo {etiqueta} tenia que dar error")
        except light.ErrorEncargo as fallo:
            ok(len(str(fallo)) > 20,
               f"un encargo {etiqueta} se rechaza con un motivo legible")


def probar_plan():
    seccion("EL PLAN: ORDEN, PARALELISMO Y CUENTAS")
    encargo = light.validar_encargo(ENCARGO_VIDEO)
    plan = light.plan_de(encargo)
    ids = [[t["id"] for t in tanda] for tanda in plan["tandas"]]
    sueltas = [t["id"] for t in plan["tareas"]]

    ok(plan["segundos"] > 0, "el plan dice cuanto va a tardar")
    # SEIS: las referencias dibujadas, y nada mas. Las muestras se componen
    # ENCIMA de ellas, asi que no dibujan nada.
    igual(plan["imagenes"], light.TAREAS_POR_ID["referencias"]["imagenes"],
          "y cuantas imagenes va a pagar: solo las referencias")
    ok("tono" in ids[0] and "voz" in ids[0],
       f"el tono y la voz arrancan a la vez que la guia: {ids[0]}")
    ok(sueltas.index("guia") < sueltas.index("referencias"),
       "la guia va antes de dibujar nada")
    ok(sueltas.index("referencias") < sueltas.index("muestra"),
       "las muestras van las ultimas: con el estilo ya montado")

    # el total es el CAMINO CRITICO, no la suma: si sumara los tiempos de una
    # tanda paralela, la barra prometeria el doble de lo que tarda
    suma = sum(t["segundos"] for t in plan["tareas"])
    ok(plan["segundos"] < suma,
       f"el total ({plan['segundos']}s) es el camino critico y no la suma ({suma}s)")

    # NO HAY CAMINO DE VIDEO: ni se baja nada ni se eligen fotogramas de nada
    sueltas = [x["id"] for x in plan["tareas"]]
    ok("frames" not in sueltas and "eleccion" not in sueltas,
       f"no se extraen ni se eligen fotogramas: {sueltas}")
    ok("personajes" not in sueltas,
       f"y no hay personajes del canal que dibujar: {sueltas}")

    for parte, ficha in light.PARTES.items():
        recorte = light.plan_de(encargo, ficha["tareas"])
        igual(sorted(t["id"] for t in recorte["tareas"]), sorted(ficha["tareas"]),
              f"rehacer «{parte}» corre solo lo suyo")
    igual(light.plan_de(encargo, light.PARTES["voz"]["tareas"])["imagenes"], 0,
          "rehacer la voz no paga ninguna imagen")
    igual(light.plan_de(encargo, light.PARTES["estilo"]["tareas"])["imagenes"],
          light.imagenes_de_parte("estilo"),
          "rehacer el estilo grafico si paga: se redibujan sus referencias")


def probar_ritmo():
    """El deslizador: cinco escalones que de verdad escalan, y sus dos cifras."""
    seccion("EL RITMO: UN MANDO QUE RELLENA CINCO CAMPOS")
    import p4_voz

    igual(len(light.RITMOS), 5, "son cinco escalones")
    ok(light.RITMO_POR_DEFECTO in light.RITMOS_POR_ID,
       "el de fabrica existe")

    minimos = [r["min_s"] for r in light.RITMOS]
    maximos = [r["max_s"] for r in light.RITMOS]
    umbrales = [r["min_s_rotulos"] for r in light.RITMOS]
    medias = [r["media_s"] for r in light.RITMOS]
    huecos = [r["hueco_minimo"] for r in light.RITMOS]
    for lista, etiqueta in ((minimos, "el minimo"), (maximos, "el maximo"),
                            (umbrales, "el umbral de rotulos"),
                            (medias, "el plano medio"), (huecos, "el aire")):
        ok(all(a > b for a, b in zip(lista, lista[1:])),
           f"{etiqueta} baja en los cinco escalones: {lista}")

    for ficha in light.RITMOS:
        ok(ficha["min_s"] < ficha["max_s"],
           f"{ficha['nombre']}: el minimo esta por debajo del maximo")
        ok(ficha["min_s"] <= ficha["min_s_rotulos"] <= ficha["max_s"],
           f"{ficha['nombre']}: el umbral de rotulos cae DENTRO de la horquilla "
           f"({ficha['min_s']} <= {ficha['min_s_rotulos']} <= {ficha['max_s']})")
        ok(ficha["min_s"] <= ficha["media_s"] <= ficha["max_s"],
           f"{ficha['nombre']}: el plano medio cae dentro de la horquilla")
        ok(ficha["velocidad"] in p4_voz.VELOCIDADES,
           f"{ficha['nombre']}: la velocidad existe en p4_voz")

    # CINCO RITMOS, TRES VELOCIDADES. Los extremos de la escala no los usa el
    # deslizador: quedan para quien los pida por escrito.
    usadas = [r["velocidad"] for r in light.RITMOS]
    igual(len(set(usadas)), 3, f"el ritmo usa TRES velocidades, no cinco: {usadas}")
    for extremo in (p4_voz.VELOCIDADES[0], p4_voz.VELOCIDADES[-1]):
        ok(extremo not in usadas,
           f"el ritmo nunca llega a «{extremo}»: es un efecto, no un registro")

    # las dos unicas cifras que ensena la pantalla
    costes = [light.coste_por_minuto(r["id"]) for r in light.RITMOS]
    ok(all(a < b for a, b in zip(costes, costes[1:])),
       f"cuanto mas rapido, mas caro el minuto: {costes}")
    ok(costes[-1] > costes[0] * 2,
       f"y la horquilla de coste es amplia de verdad ({costes[0]} -> {costes[-1]})")
    ok(light.coste_por_minuto("medio", "high") > light.coste_por_minuto("medio"),
       "subir la calidad sube el coste del minuto")

    # RELLENA LOS CAMPOS QUE YA EXISTEN, no inventa ninguno
    cambios = light.params_de_ritmo("rapido")
    igual(sorted(cambios), ["assets", "voz"],
          "el ritmo escribe en assets y en voz, y en ningun sitio mas")
    igual(sorted(cambios["assets"]), ["max_s", "min_s", "min_s_rotulos"],
          "en assets, los tres campos de duracion del modo editor")
    igual(sorted(cambios["voz"]), ["hueco_minimo"],
          "y en voz solo el aire: la VELOCIDAD la pone quien lee tu encargo")
    import p6_assets
    for clave in cambios["assets"]:
        ok(clave in p6_assets.PARAMS_POR_DEFECTO,
           f"«{clave}» es un param que el paso de assets ya tenia")
    for clave in cambios["voz"]:
        ok(clave in p4_voz.resolver_params({}),
           f"«{clave}» es un param que el paso de voz ya tenia")

    # y las claves caen dentro de lo que un preset de canal sabe guardar
    import presets_canal
    for clave in cambios["assets"]:
        ok(clave in presets_canal.TIPOS["estilo"]["claves"],
           f"«{clave}» la guarda el preset de estilo")
    for clave in cambios["voz"]:
        ok(clave in presets_canal.TIPOS["voz"]["claves"],
           f"«{clave}» la guarda el preset de voz")
    ok("ritmo" in presets_canal.CLAVES_ORIGEN,
       "y el ritmo elegido se guarda en el origen del preset")

    # uno desconocido no tumba nada: cae en el de en medio
    igual(light.ritmo_de("turbo")["id"], light.RITMO_POR_DEFECTO,
          "un ritmo que no existe cae en el de fabrica")
    igual(light.ritmo_de(None)["id"], light.RITMO_POR_DEFECTO,
          "y sin ritmo, tambien")

    # el contexto que se le pasa a la voz habla del MONTAJE, no de la voz
    frase = light.contexto_de_ritmo("muy_rapido")
    ok("planos" in frase and "media" in frase,
       f"el contexto de la voz habla de planos, no de velocidad: {frase!r}")
    for prohibida in p4_voz.VELOCIDADES:
        ok(prohibida not in frase,
           f"y no le dicta la velocidad ({prohibida})")

    ficha = light.ficha_de_ritmo("rapido")
    ok(ficha.get("usd_por_minuto", 0) > 0,
       "la ficha que va a la pantalla trae el coste por minuto")


def _fuente_del_repo(*partes):
    """El texto de un fichero del repo, para mirar quien lee un cajon."""
    ruta = os.path.join(os.path.dirname(RAIZ), *partes)
    with open(ruta, encoding="utf-8") as fh:
        return fh.read()


def probar_el_mundo_del_canal():
    """Un canal con universo propio lo nombra, y uno sin universo no se lo inventa.

    EL FALLO QUE ESTO EVITA, y salio de leer una guia de verdad. La
    descripcion del canal nombraba un universo inventado y varios temas dentro
    de el. La guia lo detecto y, obedeciendo la regla de «no nombres el tema»,
    lo escribio asi:

        «Traslada el asunto a un mundo alegorico fijo: personajes recurrentes,
         una moneda propia, objetos cotidianos que ocupan el lugar de los del
         caso.»

    Que es la peor salida posible: una orden de inventarse un mundo fijo SIN
    DECIR CUAL. El redactor se inventa uno distinto en cada video, y el canal
    --cuya gracia entera es que el mundo no cambia-- deja de reconocerse. La
    regla no sabia separar el TEMA de lo escrito del MUEBLE del canal.
    """
    seccion("EL MUNDO PROPIO DEL CANAL SE NOMBRA, Y NO SE INVENTA")
    import tono

    claves = [c for c, _ in tono.RASGOS]
    ok("mundo" in claves, "«mundo» es un rasgo de la ficha")
    igual(claves[0], "mundo",
          "y va el PRIMERO: es lo que hay que leer antes de escribir una linea")
    ok('"mundo"' in tono.CONTRATO_JSON, "se pide en el contrato de salida")

    descrito = tono.INSTRUCCION_DESCRITO.format(
        descripcion="lo cuentan unos bichos", idioma=tono.nombre_de_idioma("es"))
    # CON LOS ESPACIOS APLANADOS para buscar frases: el prompt viene con sus
    # saltos de linea y media frase cae de un renglon al siguiente. Buscarla
    # tal cual es una prueba que se rompe al reajustar un margen, no al
    # desaparecer la regla.
    plano = " ".join(descrito.split())

    # LA SENAL PARA DISTINGUIRLO: el mundo es TONO y el tema no lo es, y esa es
    # la unica excepcion a la regla de no nombrar el asunto. Sin decirlo, la
    # regla de arriba se lleva por delante el universo del canal.
    ok("eso NO es el tema" in plano,
       "se le dice COMO separar el mundo del canal del tema del video")
    ok("unica excepcion" in plano,
       "y que es la UNICA excepcion a la regla de no nombrar el asunto")

    ok("mundo" in descrito.lower(),
       "se le pregunta por el mundo propio del canal")
    ok("no se lo inventes" in descrito and "vacio" in descrito.lower(),
       "y se le deja dejarlo VACIO. Inventarle una alegoria a un canal que "
       "cuenta las cosas tal cual es el mismo error del reves")

    # EL PROMPT ES ABSTRACTO Y TIENE QUE SERLO: vale para cualquier canal, no
    # para el que lo destapo. Los huecos del ejemplo van en mayusculas, nunca
    # con las criaturas de nadie dentro.
    for palabra in ("mono", "jungla", "platano", "banano"):
        ok(palabra not in descrito.lower(),
           f"el prompt no nombra «{palabra}»: describe el mecanismo, y el "
           f"universo concreto lo pone cada canal")

    # LOS TERMINOS DE OTRO NO SE COPIAN, se dice como se fabrican. Aqui el
    # «otro» es el canal que quien escribe haya nombrado como referencia.
    ok("son de su autor y no se copian" in plano,
       "los terminos inventados de un canal ajeno no se copian")
    ok("se copia la forma de inventarlos" in plano,
       "se da la receta, que es lo que si es heredable")

    # Y LLEGA HASTA EL REDACTOR, que es lo unico que cuenta.
    ficha = tono._ficha_de_tono({"mundo": "todo pasa entre bichos en un sitio",
                                 "registro": "r"}, "parrafo", {}, 1.0)
    igual(ficha["mundo"], "todo pasa entre bichos en un sitio",
          "la ficha guarda el mundo")
    ok("El mundo del canal: todo pasa entre bichos" in ficha["texto_completo"],
       "y se pega en el brief, que es lo que lee el redactor")

    vacia = tono._ficha_de_tono({"registro": "r"}, "parrafo", {}, 1.0)
    igual(vacia["mundo"], "", "sin mundo, la clave existe y esta vacia")
    ok("El mundo del canal" not in vacia["texto_completo"],
       "y entonces no se pinta: un canal sin universo no lleva una linea que "
       "diga que no tiene ninguno")

    # Y LLEGA A LA PANTALLA POR EL TEXTO COMPLETO, no por una tabla aparte.
    # Hubo una tabla de rasgos --mundo, registro, nivel tecnico...-- que pintaba
    # los mismos datos una segunda vez. Se fue, y no se pierde nada: lo que la
    # ficha del estilo ensena es `instrucciones`, y ahi dentro esta el mundo
    # porque `instrucciones` ES el texto completo. Las dos mitades de esa
    # promesa se comprueban aqui, que es lo unico que la sostiene.
    ok('{"instrucciones": ficha["texto_completo"]}' in _fuente_del_repo("app.py"),
       "el preset guarda como instrucciones el TEXTO COMPLETO, con sus rasgos")
    ok("const guiaTono = (datos.guion || {}).instrucciones" in
       _fuente_del_repo("web", "app.js"),
       "y la ficha del estilo ensena eso mismo, entero y editable")


def probar_el_diccionario_se_acuna():
    """El mundo se hereda; las palabras inventadas por el autor, no.

    SEGUNDA PASADA SOBRE EL MISMO SITIO. Con el campo `mundo` ya puesto, la guia
    salio nombrando el universo -- bien -- pero copiando ademas los TERMINOS que
    el autor del canal nombrado como referencia se habia inventado para las
    cosas corrientes: el nombre de su moneda, el de su coche, el de su telefono.

    Eso es lo mismo que copiarle el nombre del protagonista, y se reconoce igual
    de rapido. La prueba que separa una cosa de la otra es UNA pregunta: ¿esa
    palabra existia en el idioma antes que el canal? Las criaturas, el sitio y
    lo que se come, si: son el genero del mundo y van tal cual. Un termino
    acunado, no: es de su autor.

    Y no basta con prohibirlo, porque un mundo sin palabras fijas no es un
    mundo: la guia tiene que ACUNAR las suyas y dejarlas fijas, mas la receta
    para acunar una mas cuando salga un objeto nuevo.
    """
    seccion("EL DICCIONARIO DEL MUNDO SE ACUNA, NO SE COPIA")
    import tono

    descrito = tono.INSTRUCCION_DESCRITO.format(
        descripcion="lo cuentan unos bichos", idioma=tono.nombre_de_idioma("es"))

    plano = " ".join(descrito.split())      # ver `probar_el_mundo_del_canal`
    ok("palabras normales del idioma" in plano,
       "el mundo se nombra con el idioma de siempre: lo que se acuna es el "
       "diccionario, no la forma de llamar a las criaturas")
    ok("son de su autor y no se copian" in plano,
       "y un termino acunado por otro no se copia, ni como ejemplo")

    ok("ACUNAS TU" in descrito,
       "el diccionario de este canal lo escribe la guia")
    ok("receta" in descrito.lower(),
       "y deja la receta para acunar uno mas el dia que salga un objeto que "
       "no esta en la lista")
    ok("ACUNAS TU" in tono.CONTRATO_JSON,
       "y el contrato de salida lo pide en el propio campo `mundo`")
    ok("fijos" in descrito.lower(),
       "los terminos quedan FIJOS: un diccionario que cambia cada video no es "
       "un diccionario")

    # SIGUE SIENDO ABSTRACTO. Ni el universo ni el vocabulario del canal que lo
    # destapo pueden acabar escritos en el motor: vale para cualquier canal.
    for palabra in ("mono", "jungla", "platano", "banano", "troncomovil",
                    "platanofono", "hojas verdes"):
        ok(palabra not in descrito.lower(),
           f"el prompt no nombra «{palabra}»")


def probar_la_guia_de_tono_se_edita():
    """La guia entera, en pantalla y editable, con autoguardado.

    La tarjeta ensenaba `tono_resumen`: cuatro lineas cortadas con «...» de una
    guia de casi dos mil palabras, asi que parecia corta y a medias cuando el
    problema estaba en otro sitio. Ahora se ensena entera y se corrige ahi
    mismo.
    """
    seccion("LA GUIA DE TONO SE VE ENTERA Y SE EDITA")
    js = _fuente_del_repo("web", "app.js")
    ok("const guiaTono = (datos.guion || {}).instrucciones" in js,
       "la tarjeta ensena la guia COMPLETA, no el resumen recortado")
    ok("guardarPresetLight(ficha.id, { instrucciones: v })" in js,
       "y se edita ahi mismo, con el autoguardado de siempre: editar es "
       "decidir, no hay boton de confirmar")
    ok("filas: 16" in js, "en un area de texto, que es lo que cabe")

    py = _fuente_del_repo("app.py")
    ok('instrucciones = datos.get("instrucciones")' in py,
       "el PUT del preset acepta la guia editada")
    ok("None if instrucciones is None else" in py,
       "y distingue «no me han mandado nada» de «borrala»: con un `or`, "
       "guardar el nombre desde otro sitio se llevaria por delante la guia")
    ok('"brief", {"instrucciones": instrucciones}' in py,
       "lo editado va TAMBIEN al taller: sin eso, rehacer despues la voz "
       "vuelve a congelar el preset desde los params y lo revierte en silencio")


def probar_tono_completo():
    """El tono no describe solo COMO SUENA: dice QUE SE HACE con las fuentes."""
    seccion("LA GUIA DE TONO CUBRE LA OTRA MITAD")
    import tono

    claves = [c for c, _ in tono.RASGOS]
    for nueva in ("estructura", "storytelling", "bloques", "fuentes"):
        ok(nueva in claves, f"«{nueva}» es uno de los rasgos de la ficha")
        ok(nueva in tono.CONTRATO_JSON,
           f"«{nueva}» se pide en el contrato de salida")

    descrito = tono.INSTRUCCION_DESCRITO.format(
        descripcion="serio pero cercano", idioma=tono.nombre_de_idioma("es"))
    for palabra in ("ESTRUCTURA", "STORYTELLING", "BLOQUES"):
        ok(palabra in descrito.upper(), f"se le pide la {palabra.lower()}")
    ok("articulo" in descrito.lower(),
       "se le dice que el material puede ser un articulo pegado, y no algo "
       "que alguien dijo en voz alta")
    # LO QUE NO ES SUYO. Salio de leer la primera guia de verdad: con el
    # estilo en INGLES empezaba por «Redacta siempre en castellano neutro»,
    # fijaba «videos de entre 8 y 20 minutos» y «bloques de sesenta a ciento
    # veinte segundos». Tres ajustes distintos pisados por un prompt que no
    # sabia que existian.
    ok("ni nombres ningun idioma" in descrito,
       "se le prohibe nombrar el idioma dentro del texto")
    ok("cuanto dura un video" in descrito,
       "y fijar la duracion del video")
    ok("nunca cuantos segundos" in descrito,
       "y el tamano de bloque")

    # el idioma viaja de verdad hasta la instruccion
    en_ingles = tono.INSTRUCCION_DESCRITO.format(
        descripcion="serio pero cercano", idioma=tono.nombre_de_idioma("en"))
    ok("INGLES" in en_ingles,
       "la instruccion dice en que idioma hay que escribir la guia")
    ok("ESPANOL" not in en_ingles,
       "y no arrastra el castellano cuando el canal es en otro idioma")
    igual(tono.nombre_de_idioma("pt"), "PORTUGUES",
          "el nombre del idioma sale de la tabla del brief, no de una copia")
    import inspect
    ok("idioma" in inspect.signature(tono.desde_descripcion).parameters,
       "desde_descripcion recibe el idioma")

    # la ficha los arrastra, y el texto que se pega en el brief tambien
    ficha = tono._ficha_de_tono(
        {"registro": "r", "estructura": "e", "storytelling": "s",
         "bloques": "b", "fuentes": "f"}, "parrafo", {}, 1.0)
    for clave in ("estructura", "storytelling", "bloques", "fuentes"):
        ok(clave in ficha, f"la ficha guarda «{clave}»")
    for etiqueta in ("Estructura", "Forma de contar", "Bloques",
                     "Que hacer con las fuentes"):
        ok(etiqueta in ficha["texto_completo"],
           f"«{etiqueta}» se pega en el brief, que es lo que lee el redactor")

    # una ficha vieja, con solo los cinco de antes, sigue valiendo
    vieja = tono._ficha_de_tono({"registro": "r", "ritmo": "ri"}, "parrafo", {}, 1.0)
    ok(vieja["texto_completo"].startswith("parrafo"),
       "una ficha escrita antes de esto se sigue pegando sin huecos raros")

    # EL RASGO «fuentes» Y LA LISTA DE REFERENCIAS NO SON LO MISMO, y la ficha
    # tenia la misma clave escrita dos veces: la lista pisaba al rasgo y «que
    # hacer con las fuentes» desaparecia de la ficha en silencio. La lista hoy
    # viene siempre vacia --el tono se escribe-- pero el hueco sigue en la
    # firma de `_ficha_de_tono`, asi que la confusion sigue siendo posible.
    con_refs = tono._ficha_de_tono(
        {"registro": "r", "fuentes": "atribuye lo que solo diga una"},
        "parrafo", {}, 1.0, [{"titulo": "T", "huella": "abc"}])
    igual(con_refs["fuentes"], "atribuye lo que solo diga una",
          "«fuentes» sigue siendo el RASGO del tono")
    igual([f["huella"] for f in con_refs["referencias"]], ["abc"],
          "y lo que se leyo va en «referencias», que es lo que es")

    seccion("EL TONO SE ESCRIBE")
    base = {"nombre": "X", "idioma": "es",
            "estilo_imagenes": ["a.png"],
            "voz_prompt": "grave y pausada"}
    limpio = light.validar_encargo(
        dict(base, tono_prompt="  seco  y  sin  adjetivos  "))
    igual(limpio["tono_prompt"], "seco y sin adjetivos",
          "las indicaciones del tono se limpian de espacios de sobra")
    try:
        light.validar_encargo(dict(base, tono_prompt=""))
        paso = False
    except light.ErrorEncargo:
        paso = True
    ok(paso, "y sin tono no se deja empezar: el guion se escribiria a ciegas")

    # UN CAJON ES UNA PROMESA: lo que el encargo valida tiene que caber en el
    # origen del preset, que es de donde sale el encargo al REHACER una parte.
    # Sin `estilo_imagenes` ahi, un estilo nacido de imagenes no pasaba la
    # validacion al corregirlo con una frase.
    import presets_canal                                    # noqa: PLC0415
    for clave in ("tono_prompt", "estilo_prompt", "estilo_imagenes"):
        ok(clave in presets_canal.CLAVES_ORIGEN,
           f"CLAVES_ORIGEN guarda {clave}: sin ella, rehacer una parte "
           f"leeria un encargo mas pobre que el que se pago")


def probar_escenas_de_muestra():
    seccion("LAS ESCENAS DE LA MUESTRA")
    # SEIS, una por lamina del moodboard. SUBTITULO EN TODAS Y CARTELA EN DOS:
    # la fila tiene que parecerse al video terminado, y en un video la narracion
    # no para pero una cartela sale cada varios planos. Con las seis
    # encarteladas no se ensena el canal, se ensena una promo del rotulador.
    escenas = [light._escena_muestra(i, "semilla") for i in range(6)]
    for escena in escenas:
        ok(escena.get("narracion"), "cada muestra lleva subtitulo")
        igual(len(escena["marcas"]), len(escena["narracion"].split()),
              "hay una marca por palabra, que es lo que exige subtitulos.de_escena")
    con_cartela = [e for e in escenas if e.get("cartela")]
    igual(len(con_cartela), light.CARTELAS_EN_MUESTRAS,
          "y solo dos de las seis llevan cartela")
    posiciones = [i for i, e in enumerate(escenas) if e.get("cartela")]
    ok(all(b - a > 1 for a, b in zip(posiciones, posiciones[1:])),
       f"repartidas, nunca dos seguidas: {posiciones}")
    for escena in con_cartela:
        ficha = escena["cartela"]
        ok(ficha["plantilla"] in cartelas.PLANTILLAS,
           f"la plantilla existe de verdad: {ficha['plantilla']}")
        igual(ficha.get("fondo"), "imagen",
              "y va sobre imagen, que es lo que hay que mirar: el velo encima "
              "del dibujo de ESTE canal")
        # EL TEXTO SALE DE `MUESTRAS_POR_IDIOMA`, no de `PLANTILLAS[x]["ejemplo"]`:
        # esos son castellano fijo y son de la pantalla de plantillas del modo
        # editor. La muestra existe para ensenar como queda el video de ESTE
        # estilo, y en otro idioma ya no ensena ni la longitud de linea ni donde
        # parte el subtitulo.
        propios = [c["datos"] for c in light.muestras_de_idioma("es")["cartelas"]]
        ok(ficha["datos"] in propios,
           "y ese texto es el del juego de muestras, no el de la plantilla")

    # LAS DOS, CON PLANTILLA DISTINTA. Salian iguales: los indices que llevan
    # cartela son todos multiplos del paso, asi que el resto contra el numero de
    # plantillas daba siempre cero y las dos caian en la misma.
    usadas = {e["cartela"]["plantilla"] for e in con_cartela}
    igual(len(usadas), len(con_cartela),
          f"y cada una con una plantilla distinta ({sorted(usadas)})")

    # ---- y cambia con el IDIOMA del estilo
    for idioma in ("en", "de"):
        otras = [light._escena_muestra(i, "semilla", idioma) for i in range(6)]
        frases = light.muestras_de_idioma(idioma)["frases"]
        ok(all(e["narracion"] in frases for e in otras),
           f"en «{idioma}» el subtitulo de muestra va en su idioma")
        propias = [c["datos"] for c in light.muestras_de_idioma(idioma)["cartelas"]]
        encarteladas = [e["cartela"]["datos"] for e in otras if e.get("cartela")]
        ok(encarteladas and all(d in propias for d in encarteladas),
           f"y la cartela tambien: {list(encarteladas[0].values())[:1]}")
    igual(light.muestras_de_idioma("kl"), light.muestras_de_idioma("es"),
          "un idioma que no esta cae en castellano")

    # LA ESCUCHA DE LA VOZ. Un taller no tiene guion --no es un video-- asi que
    # el texto se le pasa por params, que es el primer sitio donde
    # `p4_voz.cargar_guion` mira. Sin esto la escucha moria con «no encuentro el
    # guion», que es exactamente lo que paso al probarlo.
    import p4_voz
    for idioma in light.IDIOMAS:
        bloques = light.bloques_de_escucha(idioma)
        igual(len(bloques), 1, f"«{idioma}»: la escucha lleva un bloque")
        ok(len(bloques[0]["texto"].split()) >= 25,
           f"«{idioma}»: y texto de sobra para diez segundos "
           f"({len(bloques[0]['texto'].split())} palabras)")
        ok(p4_voz.cargar_guion(None, {"bloques": bloques}),
           f"«{idioma}»: p4_voz lo lee de los params sin tocar el disco")
    ok(light.bloques_de_escucha("en")[0]["texto"]
       != light.bloques_de_escucha("es")[0]["texto"],
       "y cada idioma se escucha en el suyo")

    # los seis idiomas que ofrece el modo tienen sus textos
    for idioma in light.IDIOMAS:
        juego = light.MUESTRAS_POR_IDIOMA.get(idioma)
        ok(juego is not None, f"«{idioma}» tiene juego de muestras propio")
        if juego:
            ok(len(juego["frases"]) >= 3 and len(juego["cartelas"]) >= 3,
               f"«{idioma}» trae frases y cartelas suficientes")
            for c in juego["cartelas"]:
                ok(c["plantilla"] in cartelas.PLANTILLAS,
                   f"«{idioma}»: la plantilla {c['plantilla']} existe")

    # la semilla manda: el mismo preset ensena siempre las mismas muestras
    otra = [light._escena_muestra(i, "semilla") for i in range(6)]
    igual(otra, escenas, "con la misma semilla salen las mismas escenas")
    hay_otra = any([light._escena_muestra(i, f"otra{n}") for i in range(6)] != escenas
                   for n in range(6))
    ok(hay_otra, "y otra semilla puede empezar la rueda por otra cartela")


def probar_el_aviso_de_cambiar_de_idioma():
    """Cambiar el idioma deja las laminas rotuladas en el anterior, y se dice.

    Las referencias dibujadas pueden llevar LETRAS DENTRO --el eje «diagrama»
    casi siempre-- y esas se dibujaron en el idioma que tenia el canal ese dia.
    `TAREAS_DE_IDIOMA` NO las rehace a proposito: convertiria cambiar de idioma
    en una operacion de seis imagenes, que es justo lo que esa tupla existe para
    evitar. Asi que se dice, con el precio delante, y lo decide quien mira.
    """
    seccion("CAMBIAR DE IDIOMA DEJA LAS LAMINAS EN EL ANTERIOR, Y SE DICE")
    ok("referencias" not in light.TAREAS_DE_IDIOMA,
       "cambiar de idioma sigue sin pagar ni una imagen")
    aviso = light.aviso_de_idioma("es", "pt")
    ok(aviso, "y con un cambio de verdad, hay aviso")
    ok("castellano" in aviso and "portugués" in aviso,
       f"que nombra los DOS idiomas, en cristiano: {aviso[:80]}…")
    ok("6 imágenes" in aviso,
       "y dice cuantas imagenes cuesta arreglarlo")
    ok("0,44 $" in aviso, f"y cuanto: {aviso[-40:]}")
    igual(aviso.count("$"), 1, "una cifra, no dos")

    igual(light.aviso_de_idioma("es", "es"), "",
       "sin cambio no se avisa de nada")
    igual(light.aviso_de_idioma("", "es"), "",
       "y sin idioma anterior tampoco: no hay nada que se quede atras")

    # LA CIFRA SALE DE LA TABLA, no de una constante escrita a mano: es la misma
    # regla que `imagenes_de_parte`, que existe porque la pantalla decia «10
    # imágenes» a mano y se quedo mintiendo.
    igual(light.imagenes_de_parte("estilo"), 6,
          "y las seis salen de las tareas de la parte, no de un numero suelto")


def probar_la_frase_del_estilo_llega_al_prompt():
    """Lo que escribe al pedir el canal tiene que llegar a la guia de estilo.

    EL FALLO QUE ARREGLA, visto el 24-08-2026 al generar un preset:

        generar_guia() got an unexpected keyword argument 'indicaciones'

    El modo light le pasaba a `estilo.generar_guia` la frase del encargo --«este
    canal pero mas frio»-- y la firma no la recibia. No fallaba a medias:
    fallaba ENTERO, y solo por el camino de «URL mas frase», que es la forma
    normal de pedir un canal.

    Que la firma lo acepte no basta: un parametro que se recibe y no se usa es
    el mismo fallo, en silencio. Aqui se sigue el dato hasta el PROMPT.
    """
    seccion("LA FRASE DEL ENCARGO LLEGA A LA GUIA DE ESTILO")
    import json
    import estilo as mod_estilo

    visto = {}
    original = mod_estilo._llamar_claude

    def falso(instruccion, modelo, esfuerzo, carpeta, avance):
        visto["instruccion"] = instruccion
        return json.dumps({"guia": "una guia", "paleta": ["#000"]}), {}

    carpeta = tempfile.mkdtemp(prefix="prueba_guia_")
    try:
        mod_estilo._llamar_claude = falso
        rutas = []
        for n in range(3):
            ruta = os.path.join(carpeta, f"f{n}.png")
            with open(ruta, "wb") as fh:
                fh.write(b"\x89PNG\r\n\x1a\n")
            rutas.append(ruta)

        mod_estilo.generar_guia(carpeta, rutas,
                                indicaciones="este canal pero mas frio")
        texto = visto["instruccion"]
        ok("este canal pero mas frio" in texto,
           "la frase del encargo entra en el prompt, literal")
        ok("Y ADEMAS HA ESCRITO ESTO" in texto,
           "con el bloque que dice que manda sobre lo que se vea")

        mod_estilo.generar_guia(carpeta, rutas)
        ok("Y ADEMAS HA ESCRITO ESTO" not in visto["instruccion"],
           "y sin frase no se anade nada: un bloque vacio le daria a entender "
           "que hay una indicacion que no hay")

        # EL ORDEN IMPORTA y esta escrito en el codigo: la correccion de ESTA
        # pasada va la ULTIMA y con precedencia dicha, asi que gana si choca con
        # lo que se pidio al crear el canal.
        mod_estilo.generar_guia(carpeta, rutas, indicaciones="mas frio",
                                peticion="y con mas contraste")
        texto = visto["instruccion"]
        donde_encargo = texto.find("mas frio")
        donde_correccion = texto.find("y con mas contraste")
        ok(0 < donde_encargo < donde_correccion,
           f"lo del encargo va ANTES que la correccion de esta pasada, que es "
           f"la que manda ({donde_encargo} < {donde_correccion})")

        # y el hermano: el camino sin video hace lo MISMO con su descripcion
        mod_estilo.guia_de_descripcion(carpeta, "un canal de dibujos",
                                       rutas=rutas)
        ok("Y ADEMAS HA ESCRITO ESTO" in visto["instruccion"],
           "y el camino sin video usa el MISMO bloque: dos formas de decir «y "
           "ademas quiero esto» acabarian separandose")
    finally:
        mod_estilo._llamar_claude = original
        shutil.rmtree(carpeta, ignore_errors=True)


def probar_lo_que_cuesta_cada_parte():
    """El precio se dice ANTES de pulsar, y sale de la tabla.

    La pantalla lo escribia a mano («10 imágenes»): seis referencias mas cuatro
    muestras. El dia que las muestras dejaron de dibujarse el numero se quedo
    mintiendo, que es peor que no decirlo.
    """
    seccion("LO QUE CUESTA REHACER CADA PARTE")
    igual(light.imagenes_de_parte("tono"), 0, "rehacer el tono no paga imagenes")
    igual(light.imagenes_de_parte("voz"), 0, "rehacer la voz tampoco")
    igual(light.imagenes_de_parte("estilo"),
          light.TAREAS_POR_ID["referencias"]["imagenes"],
          "y el estilo paga SOLO las referencias: las muestras se componen "
          "sobre ellas, no se dibujan")
    igual(light.imagenes_de_parte("inventada"), 0,
          "una parte que no existe no cuesta nada en vez de reventar")
    for ficha in light.TAREAS:
        ok(bool(ficha.get("imagenes")) == bool(ficha.get("cuesta")),
           f"«{ficha['id']}»: decir que cuesta y decir cuantas van juntas")


def _png(ruta, color):
    from PIL import Image
    Image.new("RGB", (768, 512), color).save(ruta, "PNG")
    return ruta


def probar_composicion():
    seccion("LA HOJA DE MUESTRAS SE COMPONE CON EL CODIGO DEL VIDEO")
    from PIL import Image
    carpeta = tempfile.mkdtemp(prefix="muestra_light_")
    try:
        # SEIS, como las seis laminas del moodboard que se le pasan de verdad
        colores = [(180, 90, 60), (60, 120, 180), (90, 160, 90),
                   (150, 130, 60), (140, 70, 150), (70, 150, 150)]
        imagenes = [_png(os.path.join(carpeta, f"m{i}.png"), c)
                    for i, c in enumerate(colores)]
        params = {"estilo": {"guia": {"paleta": ["#e8d8b0", "#2b2b2b", "#c46a3a"]}},
                  "idioma": "es"}
        hecho = light.componer(imagenes, os.path.join(carpeta, "miniatura.png"),
                               params, semilla="semilla")
        destino = hecho["miniatura"]
        ok(os.path.exists(destino), "la hoja se escribe")
        # y las SUELTAS, que son las que se ponen en fila al editar el estilo:
        # apiladas el subtitulo no se lee, y es lo que hay que juzgar
        igual(len(hecho["celdas"]), len(imagenes),
              "sale una muestra suelta por lamina, sin dejarse ninguna")
        for suelta in hecho["celdas"]:
            ok(os.path.exists(suelta), f"{os.path.basename(suelta)} se escribe")
        with Image.open(hecho["celdas"][0]) as una:
            igual(una.size, tuple(light.p7_callouts.SALIDA),
                  "cada muestra suelta sale a tamaño de cuadro entero")

        ancho_salida, alto_salida = light.p7_callouts.SALIDA
        celda_w = ancho_salida // light.COLUMNAS_MINIATURA
        celda_h = round(celda_w * alto_salida / ancho_salida)
        filas = -(-len(imagenes) // light.COLUMNAS_MINIATURA)
        with Image.open(destino) as hoja:
            ancho, alto = hoja.size
            igual((ancho, alto), (celda_w * light.COLUMNAS_MINIATURA, celda_h * filas),
                  f"la hoja son {light.COLUMNAS_MINIATURA} columnas por {filas} "
                  f"filas de celdas 16:9, sin recortar ninguna")
            # cada celda tiene que ser DISTINTA: si el compositor pegara la misma
            # imagen seis veces --o dejara cinco en negro-- la hoja se seguiria
            # escribiendo y nadie se enteraria
            centros = [hoja.getpixel(((i % light.COLUMNAS_MINIATURA) * celda_w + celda_w // 2,
                                      (i // light.COLUMNAS_MINIATURA) * celda_h + celda_h // 2))
                       for i in range(len(imagenes))]
            ok(len({c for c in centros}) >= len(imagenes) - 1,
               f"cada celda lleva una lamina distinta: {centros}")
            ok(all(sum(c) > 30 for c in centros),
               f"ninguna celda sale en negro: {centros}")

        # y partirla devuelve las mismas, que es lo que cura a un estilo viejo
        trozos = light.partir_miniatura(destino, os.path.join(carpeta, "partida"))
        igual(len(trozos), len(imagenes),
              "partir la hoja devuelve una por lamina, no cuatro fijas")
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description="Prueba del modo light")
    parser.add_argument("--sin-navegador", action="store_true",
                        help="salta la composicion de la miniatura (necesita Edge)")
    argumentos = parser.parse_args()

    # EL HISTORICO DE TIEMPOS, A UNA COPIA. Guarda 30 muestras por paso, asi
    # que las de una suite EXPULSAN las reales por antiguedad -- y con ellas se
    # va lo unico que hace que `cadencia` y la barra dejen de usar la tabla
    # escrita y usen lo medido de esta maquina.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(
        tempfile.gettempdir(), "estudio_prueba_light", "estadisticas.json")
    print("PRUEBA DEL MODO LIGHT")
    probar_encargo()
    probar_plan()
    probar_ritmo()
    probar_tono_completo()
    probar_el_mundo_del_canal()
    probar_el_diccionario_se_acuna()
    probar_la_guia_de_tono_se_edita()
    probar_escenas_de_muestra()
    probar_el_aviso_de_cambiar_de_idioma()
    probar_la_frase_del_estilo_llega_al_prompt()
    probar_lo_que_cuesta_cada_parte()
    if argumentos.sin_navegador:
        print("\n  (composicion de la miniatura saltada por --sin-navegador)")
    else:
        probar_composicion()

    print()
    if _fallos:
        print(f"PRUEBA LIGHT CON FALLOS: {len(_fallos)} de {_ok + len(_fallos)}")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"PRUEBA LIGHT OK: {_ok} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
