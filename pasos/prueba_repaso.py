"""Prueba del REPASO y de la REVISION DE LOS PLANOS.

Los dos son lo que pasa DESPUES de generar, y los dos tienen el mismo riesgo:
escribir en un cajon que no lee nadie. «Media pieza escrita no da error» ya
costo un video entero en este repo -- el metraje de las menciones se elegia, se
guardaba y no lo leia nadie --, y aqui seria peor: la nota se marca como
aplicada, el video sale igual, y quien la escribio cree que se ha hecho caso.

Por eso la comprobacion central de esta suite no es que el codigo corra: es que
CADA destino de la tabla de cambios sea un parametro que alguien lee de verdad.

    python pasos/prueba_repaso.py
"""
import io
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.abspath(__file__))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
REPO = os.path.dirname(RAIZ)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

import p3_guion                                             # noqa: E402
import p6_assets                                            # noqa: E402
import p7_callouts                                          # noqa: E402
import p8_render                                            # noqa: E402
import p2_brief                                             # noqa: E402
import recetas                                              # noqa: E402
import repaso                                               # noqa: E402

_ok = 0
_fallos = []


RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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


class ProyectoFalso:
    """Lo minimo que `repaso` necesita de un proyecto: una carpeta."""

    def __init__(self, base):
        self.id = "prueba"
        self.base = base

    def ruta(self, *partes):
        return os.path.join(self.base, *partes)


# ------------------------------------------------------------ las notas

def prueba_notas():
    seccion("UNA NOTA NECESITA TEXTO, Y SE ANCLA A SU SEGUNDO")
    base = tempfile.mkdtemp(prefix="repaso_")
    try:
        proyecto = ProyectoFalso(base)
        igual(repaso.leer(proyecto)["notas"], [], "de vacio, ninguna nota")

        try:
            repaso.anadir(proyecto, "   ", 12.0)
            ok(False, "una nota sin texto tenia que rebotar")
        except ValueError as fallo:
            ok("texto" in str(fallo),
               "una nota sin texto rebota: una imagen sola no dice que hay que "
               "hacer con ella")

        segunda = repaso.anadir(proyecto, "la musica esta alta", 92.4,
                                plano="S031")
        primera = repaso.anadir(proyecto, "aqui sobra el rotulo", 10.0,
                                plano="S004", imagenes=["ref.png"])
        igual([n["id"] for n in repaso.leer(proyecto)["notas"]],
              [primera["id"], segunda["id"]],
              "se leen EN ORDEN DE VIDEO, no en orden de escritura: el repaso "
              "se lee con el video delante")
        igual(segunda["plano"], "S031", "cada nota se queda con su plano")
        igual(primera["imagenes"], ["ref.png"], "y con sus referencias")

        repaso.editar(proyecto, primera["id"], texto="mejor quitalo entero")
        igual(repaso.leer(proyecto)["notas"][0]["texto"], "mejor quitalo entero",
              "editar cambia el texto")
        try:
            repaso.editar(proyecto, primera["id"], texto="  ")
            ok(False, "editar a vacio tenia que rebotar")
        except ValueError:
            ok(True, "y no se puede vaciar por la puerta de atras")

        repaso.borrar(proyecto, primera["id"])
        igual(len(repaso.leer(proyecto)["notas"]), 1, "borrar borra")
        try:
            repaso.borrar(proyecto, "R999")
            ok(False, "borrar lo que no existe tenia que rebotar")
        except KeyError:
            ok(True, "y borrar lo que no existe se dice, no se calla")

        ok(len(repaso.pendientes(proyecto)) == 1,
           "lo que no se ha aplicado sigue pendiente")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def prueba_ancla():
    seccion("DEL SEGUNDO AL PLANO")
    cortes = [{"id": "S001", "t_in": 0.0, "t_out": 3.0},
              {"id": "S002", "t_in": 3.0, "t_out": 7.5},
              {"id": "S003", "t_in": 7.5, "t_out": 12.0}]
    igual(repaso.plano_en(cortes, 0.0), "S001", "el primer instante es el primero")
    igual(repaso.plano_en(cortes, 3.0), "S002",
          "la frontera pertenece al que ENTRA: pausar justo en el corte es "
          "querer hablar del plano que aparece")
    igual(repaso.plano_en(cortes, 7.49), "S002", "y el de antes hasta el final")
    igual(repaso.plano_en(cortes, 99.0), "S003",
          "pasado el final se queda con el ultimo, no con nada: una nota al "
          "final del video habla del final del video")
    igual(repaso.plano_en([], 5.0), "", "sin cortes no se inventa ningun plano")


def prueba_contexto():
    seccion("Y DEL PLANO A TODO LO QUE LO RODEA")
    escenas = {"S002": {"id": "S002", "narracion": "lo que se dice aqui",
                        "origen": {"bloque": "B002"}, "set": "una oficina",
                        "personajes": ["alguien"],
                        "cartela": {"plantilla": "cifra"}}}
    bloques = {"B002": {"id": "B002", "texto": "el bloque entero"}}
    ficha = repaso.contexto_de_nota({"plano": "S002"}, escenas, bloques,
                                    ["S001", "S002", "S003"])
    igual(ficha["bloque"], "B002", "se llega al bloque del guion")
    igual(ficha["texto_bloque"], "el bloque entero", "y a lo que dice")
    igual((ficha["anterior"], ficha["siguiente"]), ("S001", "S003"),
          "y a los planos de al lado, que es lo que hace que «esta transicion» "
          "se pueda colocar")
    igual(ficha["cartela"], "cifra", "y a la cartela que lleva")


# ------------------------------------------------- el vocabulario cerrado

def prueba_vocabulario():
    seccion("EL VOCABULARIO ES CERRADO Y SE VALIDA")
    cambio, motivo = repaso.validar_cambio({"tipo": "musica_db", "valor": -3})
    igual(motivo, "", "un cambio bueno pasa")
    igual(cambio["ambito"], "musica", "con su ambito puesto")

    _, motivo = repaso.validar_cambio({"tipo": "arreglalo_todo"})
    ok("vocabulario" in motivo,
       "un tipo inventado NO se aplica, y se dice: el enrutador propone, el "
       "codigo valida")
    _, motivo = repaso.validar_cambio({"tipo": "musica_db", "valor": -40})
    ok("valor" in motivo, "y un valor fuera de rango tampoco")
    _, motivo = repaso.validar_cambio({"tipo": "feedback_plano",
                                       "plano": "no es un plano", "texto": "x"})
    ok("plano" in motivo, "ni un id de plano que no lo es")
    ok(repaso.validar_cambio({"tipo": "feedback_plano", "plano": "s031",
                              "texto": "remove the sign"})[0]["plano"] == "S031",
       "un id en minusculas se normaliza en vez de rebotar")

    # EL ALCANCE (PENDIENTE 39): lo decide el enrutador, que es el unico que ve
    # la nota, el plano y las imagenes a la vez, y decide si al generador se le
    # adjunta la imagen RECHAZADA.
    igual(repaso.validar_cambio({"tipo": "feedback_plano", "plano": "S031",
                                 "texto": "swap the hand for a glove",
                                 "alcance": "retoque"})[0]["alcance"],
          "retoque", "un retoque localizado se declara como tal")
    igual(repaso.validar_cambio({"tipo": "feedback_plano", "plano": "S031",
                                 "texto": "this should be a phone"})[0]["alcance"],
          "sustituye",
          "y sin alcance NO se descarta el cambio: se rehace como se rehacia "
          "hasta ahora. Perder una correccion por una etiqueta seria peor que "
          "no adjuntar la imagen")
    igual(repaso.validar_cambio({"tipo": "feedback_plano", "plano": "S031",
                                 "texto": "x", "alcance": "lo que sea"})[0]["alcance"],
          "sustituye", "una etiqueta inventada cae al mismo lado seguro")


def prueba_ahorro():
    seccion("APLICAR AHORRA, Y ESO SE MIDE EN TAREAS")
    def tareas(*tipos):
        cambios = []
        for tipo in tipos:
            campos = {"tipo": tipo}
            campos.update({"valor": -3, "plano": "S001", "texto": "x",
                           # cada tipo coge el suyo de este cajon comun
                           "bloque": "B001", "asset": "alguien",
                           "campos_cartela": {"titulo": "x"},
                           "lista": ["fundido"], "animo": "tenso"})
            cambio, motivo = repaso.validar_cambio(campos)
            assert cambio, f"{tipo}: {motivo}"
            cambios.append(cambio)
        return repaso.tareas_de(cambios)

    igual(tareas("musica_db"), ["render"],
          "BAJAR LA MUSICA ES SOLO REMUXEAR. Es el caso que mas se pide y el "
          "que mejor ensena para que existe este modulo: cero imagenes, cero "
          "voz, segundos")
    igual(tareas("cartela_texto"), ["assets", "callouts", "render"],
          "cambiar lo que dice una cartela vuelve a pasar por assets y NO cuesta: "
          "un plano que es cartela cae en `_sin_imagen`, asi que no se paga "
          "ninguna imagen; dejarlo fuera lo dejaria obsoleto para siempre")
    igual(tareas("feedback_plano"), ["assets", "callouts", "render"],
          "y solo tocar la imagen de un plano cuesta una imagen")
    ok("voz" in tareas("bloque_texto"),
       "reescribir un bloque si vuelve a grabar la voz: es lo caro, y por eso "
       "el enrutador tiene que elegirlo solo cuando de verdad toca")
    igual(tareas("anotar"), [],
          "y lo que no se puede aplicar solo no rehace nada")

    juntas = tareas("musica_db", "cartela_texto", "feedback_plano")
    igual(juntas, ["assets", "callouts", "render"],
          "varias notas se funden en UNA lista, en orden de pipeline y sin "
          "repetir: aplicar diez notas no puede renderizar diez veces")
    ok(juntas.index("assets") < juntas.index("callouts") < juntas.index("render"),
       "y el orden es el de las dependencias, no el de las notas")


def prueba_solo_mezcla():
    seccion("BAJAR LA MUSICA NO REDIBUJA UN SOLO PLANO")
    # EL FALLO QUE ARREGLA: se pidio «la musica esta muy fuerte, rebajala en
    # todo el video» y el Estudio se puso a renderizar los 98 planos en Edge,
    # uno a uno. El enrutado era correcto --musica_db va a la tarea `render`--
    # pero la tarea `render` REDIBUJA, y el camino barato
    # (`p8_render.ejecutar(solo_montar=True)`) existia desde hacia dias sin que
    # nadie lo pidiera. La promesa estaba escrita en AMBITOS y era prosa.
    ok(repaso.AMBITOS["musica"].get("solo_mezcla"),
       "la música está marcada como «solo la mezcla», y se LEE")
    ok(repaso.AMBITOS["efectos"].get("solo_mezcla"),
       "y los efectos también")
    igual(sorted(repaso.AMBITOS_SOLO_MEZCLA), ["efectos", "musica"],
          "y no hay ningún otro: todo lo demás toca un fotograma")

    ok(repaso.solo_mezcla([{"tipo": "musica_db", "valor": -4}]),
       "«baja la música» se resuelve remezclando")
    ok(repaso.solo_mezcla([{"tipo": "musica_db"}, {"tipo": "sin_efectos"}]),
       "y música + efectos juntos, también")
    ok(not repaso.solo_mezcla([{"tipo": "musica_db"},
                               {"tipo": "feedback_plano"}]),
       "pero con UN cambio que toca un fotograma, ya no: es AND y no OR. "
       "Quedarse corto daría un vídeo con la música bajada y sin el otro "
       "cambio, y eso nadie lo mira dos veces")
    ok(not repaso.solo_mezcla([]), "sin cambios no se remonta nada")
    ok(not repaso.solo_mezcla([{"tipo": "cartela_texto"}]),
       "y una cartela sí redibuja: se compone sobre el plano")

    # LOS DOS EXTREMOS DEL CABLE. La marca no sirve de nada si no llega a
    # `p8_render.ejecutar`, que es quien de verdad decide si dibuja.
    import p8_render
    ok("solo_montar" in p8_render.OPCIONES_EJECUCION,
       "el paso del render declara que entiende `solo_montar`")
    raiz = RAIZ_ESTUDIO
    fuente = io.open(os.path.join(raiz, "app.py"), encoding="utf-8").read()
    ok("repaso.solo_mezcla(" in fuente,
       "y el repaso lo decide de verdad, no sólo lo declara")
    ok('{"solo_montar": True} if solo_montar else None' in fuente,
       "y se lo pasa a la tarea del MP4")


def prueba_orden_completo():
    seccion("EL ORDEN CUBRE TODO LO QUE SE PUEDE ENSUCIAR")
    pedidas = set()
    for ficha in repaso.CAMBIOS.values():
        pedidas.update(ficha["rehacer"])
    fuera = sorted(pedidas - set(repaso.ORDEN))
    igual(fuera, [],
          "ninguna tarea que un cambio ensucia se queda fuera del orden: si se "
          "quedara, se escribiria el param y no se volveria a generar nada")
    conocidas = {t["id"] for t in recetas.TAREAS}
    desconocidas = sorted(set(repaso.ORDEN) - conocidas)
    igual(desconocidas, [],
          "y todas las del orden son tareas que la receta sabe correr: un id "
          "que no existe se salta en silencio")


# ---------------------------------------------- la trampa de este repo

def prueba_destinos_los_lee_alguien():
    seccion("CADA CAMBIO ESCRIBE EN UN PARAM QUE ALGUIEN LEE")
    # ESTA ES LA COMPROBACION CENTRAL DE LA SUITE. Un cambio que escribe en un
    # cajon muerto no da error: la nota se marca como aplicada y el video sale
    # igual. Es el mismo fallo que el metraje que se elegia y no leia nadie.
    declarados = {
        "assets": set(p6_assets.PARAMS_POR_DEFECTO),
        "callouts": set(p7_callouts.PARAMS_POR_DEFECTO),
        "render": set(p8_render.PARAMS_POR_DEFECTO),
        "guion": set(p3_guion.PARAMS_POR_DEFECTO),
        "brief": set(p2_brief.PARAMS_POR_DEFECTO),
    }
    #: Las claves POR UNIDAD no estan en PARAMS_POR_DEFECTO --viven dentro del
    #: bloque reservado `unidades` (nucleo.estado.CLAVE_UNIDADES)-- asi que se
    #: comprueban contra SU LECTOR: se le da a p6 unos params con esa clave
    #: puesta y se mira que la vea.
    ejemplo = {"unidades": {"escena:S001": {"feedback": "una nota",
                                            "cartela": {"plantilla": "cifra"},
                                            "subtitulo_texto": "un 1% al año"},
                            "asset:alguien": {"feedback": "otra nota"}}}
    lectores = {
        "unidades.escena:*.feedback":
            lambda: p6_assets._ajustes_unidad(ejemplo, "escena:S001").get("feedback"),
        "unidades.asset:*.feedback":
            lambda: p6_assets._ajustes_unidad(ejemplo, "asset:alguien").get("feedback"),
        "unidades.escena:*.cartela":
            lambda: p6_assets._ajustes_unidad(ejemplo, "escena:S001").get("cartela"),
        "unidades.escena:*.subtitulo_texto":
            lambda: p7_callouts.texto_subtitulo_de(ejemplo, "escena:S001"),
    }
    for tipo, (paso, clave) in repaso.DESTINOS.items():
        if not paso:
            continue                       # `anotar` no escribe en ningun sitio
        if clave in lectores:
            ok(bool(lectores[clave]()),
               f"{tipo}: escribe en {clave}, y el paso {paso} lo LEE de verdad "
               f"(no basta con que el cajon exista)")
            continue
        ok(clave in declarados.get(paso, set()),
           f"{tipo}: escribe en {paso}.{clave}, y ese param lo declara el paso")
    ok(p6_assets._texto_feedback("una nota") == "una nota"
       and "x" in p6_assets._texto_feedback([{"texto": "x"}]),
       "y el feedback llega al prompt tanto escrito a mano como en historial: "
       "es el camino por el que entran la revision y el repaso")
    igual(sorted(repaso.DESTINOS), sorted(repaso.CAMBIOS),
          "y la tabla de destinos cubre exactamente los cambios que existen: "
          "ni uno de mas ni uno de menos")


def prueba_valores_reales():
    seccion("Y LOS VALORES SON LOS QUE EL PASO ENTIENDE")
    cambio, _ = repaso.validar_cambio({"tipo": "grafismo", "valor": "editorial"})
    ok(cambio and cambio["valor"] in p7_callouts.SETS_DISENO,
       "un set de diseno tiene que ser uno de los que hay: escribir 'moderno' "
       "en `callouts.diseno` no da error, deja el grafismo como estaba")
    ok(repaso.validar_cambio({"tipo": "grafismo", "valor": "moderno"})[0] is None,
       "y uno que no existe no pasa")
    for tam in ("pequeno", "normal", "grande", "enorme", 52):
        ok(repaso.validar_cambio({"tipo": "subtitulo_tam", "valor": tam})[0],
           f"el tamano de subtitulo «{tam}» vale")
    ok(repaso.validar_cambio({"tipo": "subtitulo_tam", "valor": "gigante"})[0] is None,
       "y uno inventado no")


# ------------------------------------------------ y aplicar de verdad

class _Bitacora:
    def anotar(self, *a, **k):
        pass


class _Ctx:
    """Lo minimo que `_aplicar_cambios_del_repaso` necesita de un proyecto."""

    def __init__(self, proyecto):
        from nucleo.estado import Estado                       # noqa: PLC0415
        self.proyecto = proyecto
        self.id = proyecto.id
        self.estado = Estado(proyecto)
        self.bitacora = _Bitacora()


def prueba_aplicar_escribe_donde_dice():
    seccion("APLICAR ESCRIBE EN SU CAJON, Y AHI SI SE MUEVE LA FIRMA")
    # Es la funcion que ESCRIBE, o sea la unica del repaso que puede estropear
    # un proyecto. Se ejercita contra un proyecto de verdad, no contra un doble.
    import app                                                 # noqa: PLC0415
    from nucleo.proyecto import Proyecto                       # noqa: PLC0415

    raiz = tempfile.mkdtemp(prefix="repaso_aplicar_")
    try:
        ctx = _Ctx(Proyecto.crear(raiz, "Prueba del repaso"))
        firma_antes = ctx.estado.firma("render")
        # un plano que YA es cartela, para poder cambiarle el texto
        ctx.estado.actualizar_params("assets", {"unidades": {
            "escena:S012": {"cartela": {"plantilla": "tesis",
                                        "datos": {"titulo": "Lo de antes"}}}}})

        avisos = []
        hechos = app._aplicar_cambios_del_repaso(ctx, {"cambios": [
            {"tipo": "musica_db", "ambito": "musica", "valor": -3.0,
             "rehacer": ["render"]},
            {"tipo": "feedback_plano", "ambito": "imagen", "plano": "S031",
             "texto": "remove the second figure", "alcance": "retoque",
             "rehacer": []},
            {"tipo": "cartela_texto", "ambito": "cartela", "plano": "S012",
             "campos_cartela": {"titulo": "Otra cosa"}, "rehacer": []},
            {"tipo": "cartela_texto", "ambito": "cartela", "plano": "S099",
             "campos_cartela": {"titulo": "No existe"}, "rehacer": []},
            {"tipo": "subtitulo_tam", "ambito": "subtitulo", "valor": "grande",
             "rehacer": []},
            {"tipo": "subtitulo_texto", "ambito": "subtitulo", "plano": "S072",
             "texto": "un 1% al año", "rehacer": []},
            {"tipo": "bloque_texto", "ambito": "guion", "bloque": "B014",
             "texto": "lo que se dice ahora", "rehacer": []},
            {"tipo": "anotar", "ambito": "nota", "texto": "esto lo decides tu",
             "rehacer": []},
        ]}, avisos)

        render = ctx.estado.params("render") or {}
        callouts = ctx.estado.params("callouts") or {}
        guion = ctx.estado.params("guion") or {}
        unidades = (ctx.estado.params("assets") or {}).get("unidades") or {}

        igual(render.get("musica_db"), -3.0, "la musica va a los params del render")
        igual(callouts.get("subtitulo_tam"), "grande",
              "el tamano del subtitulo a los de callouts, que es quien lo lee")
        igual(p7_callouts.texto_subtitulo_de(callouts, "escena:S072"),
              "un 1% al año",
              "y el TEXTO corregido a la unidad de ese plano: corregir lo "
              "escrito deja obsoleto S072 y ninguno mas, sin tocar la voz")
        igual((guion.get("bloques") or {}).get("B014"), "lo que se dice ahora",
              "y el texto de un bloque al cajon que ya usa la pantalla")

        feedback = (unidades.get("escena:S031") or {}).get("feedback") or []
        ok(feedback and feedback[0]["texto"].startswith("remove the second"),
           "el feedback de un plano entra por el MISMO cajon que el de una "
           "persona, que es el que ya sabe entrar en el prompt con peso")
        igual(feedback[0].get("de") if feedback else None, "repaso",
              "y queda dicho de donde viene")
        igual(feedback[0].get("alcance") if feedback else None, "retoque",
              "y con QUE ALCANCE: es lo que decide si al generador se le "
              "adjunta la imagen rechazada (PENDIENTE 39)")

        cartela = (unidades.get("escena:S012") or {}).get("cartela") or {}
        igual((cartela.get("datos") or {}).get("titulo"), "Otra cosa",
              "la cartela cambia de texto")
        igual(cartela.get("plantilla"), "tesis",
              "sin perder su plantilla: se FUSIONA, no se pisa")
        ok(not (unidades.get("escena:S099") or {}).get("cartela"),
           "y un plano que NO lleva cartela no se convierte en una a medias: "
           "sin plantilla, `cartelas._desmontar` la rellenaria con el texto de "
           "EJEMPLO de la plantilla por defecto")
        ok(any("S099" in a for a in avisos), "se dice que no se ha podido")
        ok(any("decides tu" in a for a in avisos),
           "y lo que no se puede aplicar solo se queda escrito en los avisos")
        igual(len(hechos), 6,
              "seis cambios escritos: el de la cartela imposible y la nota no "
              "cuentan")

        ok(ctx.estado.firma("render") != firma_antes,
           "Y AQUI SI SE MUEVE LA FIRMA. Escribir una nota no puede; aplicarla "
           "tiene que")

        app._aplicar_cambios_del_repaso(ctx, {"cambios": [
            {"tipo": "feedback_plano", "ambito": "imagen", "plano": "S031",
             "texto": "and make the sky darker", "rehacer": []}]}, [])
        unidades = (ctx.estado.params("assets") or {}).get("unidades") or {}
        igual(len(((unidades.get("escena:S031") or {}).get("feedback") or [])), 2,
              "el feedback se ACUMULA, no se pisa")
        ok(((unidades.get("escena:S012") or {}).get("cartela") or {}).get("datos"),
           "y escribir en una unidad no se lleva por delante otra: es la trampa "
           "que ya costo una ronda con las cartelas y con la direccion")
    finally:
        shutil.rmtree(raiz, ignore_errors=True)


def prueba_reanclar():
    """Una nota sigue a su plano aunque el corte lo mueva, lo parta o lo junte.

    El numero de un plano es su POSICION y se reparte de nuevo con cada voz
    nueva, asi que una nota escrita ayer puede amanecer senalando el plano de al
    lado. Se ancla al TEXTO y se comprueba al leer.

    Y el caso que se escapo: al PARTIR un plano en dos, el ancla decia
    «...de la gente sin tocar su cuenta y sin que nadie lo note» y el plano paso
    a decir «...de la gente». Se parecen 0,615 -- por debajo del minimo -- y es
    exactamente el mismo plano, asi que la nota salia marcada como huerfana en
    la pantalla, con un plano perfectamente valido delante.
    """
    seccion("LAS NOTAS SIGUEN A SU PLANO, NO A SU NUMERO")

    escenas = [
        {"id": "S001", "t_in": 0.0, "narracion": "Esto no va de metales brillantes."},
        {"id": "S002", "t_in": 2.0, "narracion": "Va de un truco muy viejo: cómo se le quita valor al dinero de la gente"},
        {"id": "S003", "t_in": 5.0, "narracion": "sin tocar su cuenta y sin que nadie lo note."},
    ]

    # 1. el plano que dice lo suyo: no se toca
    notas = repaso.reanclar([{ "id": "R001", "plano": "S001", "t": 0.0,
                              "ancla": "Esto no va de metales brillantes."}], escenas)
    igual(notas[0]["plano"], "S001", "el plano que sigue diciendo lo suyo no se toca")
    ok(not notas[0].get("descolgada"), "y no se marca nada")

    # 2. el numero se ha corrido: se muda al que lo dice
    notas = repaso.reanclar([{ "id": "R002", "plano": "S003", "t": 9.9,
                              "ancla": "Esto no va de metales brillantes."}], escenas)
    igual(notas[0]["plano"], "S001", "una nota con el numero corrido vuelve al que dice lo suyo")
    igual(notas[0]["reanclada"], "S003", "y cuenta de donde venia")
    igual(notas[0]["t"], 0.0, "con el segundo de su plano nuevo, para que el salto lleve al sitio")

    # 3. EL PLANO SE PARTIO: sigue siendo suyo
    largo = ("Va de un truco muy viejo: cómo se le quita valor al dinero de la "
             "gente sin tocar su cuenta y sin que nadie lo note.")
    notas = repaso.reanclar([{ "id": "R003", "plano": "S002", "t": 2.0,
                              "ancla": largo}], escenas)
    ok(not notas[0].get("descolgada"),
       "un plano PARTIDO no deja huerfana a su nota: lo que dice ahora está "
       "dentro de lo que decía, o sea que es el mismo plano dicho más corto")
    igual(notas[0]["plano"], "S002", "y se queda en la mitad que lo empieza")

    # 4. y un texto que ya no esta se DICE, en vez de apuntar a cualquier sitio
    notas = repaso.reanclar([{ "id": "R004", "plano": "S002", "t": 2.0,
                              "ancla": "zumbaba un zeppelin de jengibre sobre la ciudad"}],
                            escenas)
    ok(notas[0].get("descolgada"),
       "lo que ya no se dice en el vídeo se marca: una nota huérfana que lo "
       "dice se arregla a mano; una que apunta mal no se ve venir")

    # 5. las de antes de que esto existiera no llevan ancla y no se mueven
    notas = repaso.reanclar([{"id": "R005", "plano": "S003", "t": 5.0}], escenas)
    igual(notas[0]["plano"], "S003",
          "sin ancla no se adivina: una nota vieja se queda donde está")

def main():
    print("PRUEBA DEL REPASO Y DE LA REVISION")
    prueba_notas()
    prueba_ancla()
    prueba_reanclar()
    prueba_contexto()
    prueba_vocabulario()
    prueba_ahorro()
    prueba_solo_mezcla()
    prueba_orden_completo()
    prueba_destinos_los_lee_alguien()
    prueba_valores_reales()
    prueba_aplicar_escribe_donde_dice()

    print("\n" + "=" * 70)
    if _fallos:
        print(f"FALLAN {len(_fallos)} de {_ok + len(_fallos)} comprobaciones:")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"PRUEBA REPASO OK: {_ok} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
