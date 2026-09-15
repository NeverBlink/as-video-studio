"""
Prueba de extremo a extremo del nucleo del Estudio de Video.

Crea un proyecto temporal, simula la ejecucion de todos los pasos, cambia el
texto de una sola escena y comprueba que la obsolescencia cae solo donde debe,
revierte versiones y comprueba que la propagacion sigue siendo correcta.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\nucleo\\prueba_nucleo.py
"""
import io
import os
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nucleo import (Bitacora, Estado, GestorTrabajos, PASOS, Proyecto,
                    descendientes_de)

FALLOS = []


def comprobar(condicion, texto):
    """Registra el resultado de una comprobacion y sigue con las demas."""
    if condicion:
        print(f"  ok   {texto}")
    else:
        print(f"  FALLO {texto}")
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado, f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]"
              if obtenido != esperado else texto)


def escenas(textos):
    return {clave: {"texto": valor} for clave, valor in textos.items()}


def prueba_proyecto(base):
    print("\n[1] proyecto")
    proyecto = Proyecto.crear(base, "Caso Meridiano")
    igual(proyecto.id, "caso_meridiano", "id derivado del nombre")
    comprobar(os.path.isdir(proyecto.ruta("pasos")), "crea la carpeta pasos/")
    proyecto.config["cliente"] = "canal"
    proyecto.guardar_config()

    recargado = Proyecto(proyecto.raiz)
    igual(recargado.config.get("cliente"), "canal", "la config persiste")

    gemelo = Proyecto.crear(base, "Caso Meridiano")
    igual(gemelo.id, "caso_meridiano_2", "ids unicos ante nombres repetidos")
    shutil.rmtree(gemelo.raiz)

    fichas = Proyecto.listar(base)
    igual([f["id"] for f in fichas], ["caso_meridiano"], "listar encuentra el proyecto")
    comprobar(proyecto.ruta_paso("guion").endswith(os.path.join("guion", "v1")),
              "ruta_paso apunta a v1 cuando no hay version activa")
    return proyecto


def prueba_primer_pase(estado):
    print("\n[2] primer pase por todo el grafo")
    igual(estado.estado_de("ingesta"), "pendiente", "ingesta arranca pendiente")
    igual(estado.estado_de("brief"), "bloqueado", "brief bloqueado sin ingesta")
    igual(estado.estado_de("render"), "bloqueado", "render bloqueado al principio")

    estado.set_params("ingesta", {"url": "https://ejemplo/1", "idioma": "es"})
    estado.completar("ingesta", {"transcripcion": "transcripcion.json"})
    igual(estado.estado_de("ingesta"), "listo", "ingesta lista tras completar")
    igual(estado.estado_de("brief"), "pendiente", "brief se desbloquea")

    estado.set_params("brief", {"angulo": "ruta del contrabando"})
    estado.completar("brief", {"brief": "brief.md"})

    estado.set_params("guion", {
        "tono": "seco",
        "unidades": escenas({"S01": "abre el puerto",
                             "S02": "sube la carga",
                             "S03": "la lancha huye"}),
    })
    estado.completar("guion", {"escenas": 3})
    igual(estado.estado_de("guion"), "listo", "guion listo")
    igual(estado.unidades_declaradas("guion"), ["S01", "S02", "S03"],
          "el guion declara tres escenas")
    igual(estado.unidades_declaradas("render"), ["S01", "S02", "S03"],
          "render hereda las escenas por el DAG")

    estado.set_params("voz", {"voz_id": "abc", "velocidad": "normal"})
    estado.completar("voz", {"wav": "narracion.wav"})
    igual(estado.estado_de("voz"), "listo", "voz lista")
    igual(estado.estado_de("revision_audio"), "pendiente", "revision_audio pendiente")

    estado.set_params("assets", {"estilo": "cartoon", "calidad": "medium"})
    for paso_id in ("assets", "callouts", "render"):
        estado.completar(paso_id, {"total": 3}, {
            "S01": {"png": f"{paso_id}_s01.png"},
            "S02": {"png": f"{paso_id}_s02.png"},
            "S03": {"png": f"{paso_id}_s03.png"},
        })
        igual(estado.estado_de(paso_id), "listo", f"{paso_id} listo con sus 3 unidades")
        igual(estado.unidades_obsoletas(paso_id), [], f"{paso_id} sin unidades sucias")


def prueba_cambio_de_escena(estado):
    print("\n[3] cambiar solo el texto de S03")
    firmas_antes = {p["id"]: estado.firma_unidad(p["id"], "S01") for p in PASOS}
    estado.actualizar_params("guion", {"unidades": {"S03": {"texto": "la lancha explota"}}})

    igual(estado.params("guion")["unidades"]["S01"]["texto"], "abre el puerto",
          "el resto de escenas no se toca")
    igual(estado.estado_de("guion"), "obsoleto", "guion obsoleto")
    igual(estado.estado_de("voz"), "obsoleto", "voz obsoleta (audio continuo)")
    igual(estado.estado_de("ingesta"), "listo", "ingesta intacta aguas arriba")
    igual(estado.estado_de("brief"), "listo", "brief intacto aguas arriba")

    for paso_id in ("assets", "callouts", "render"):
        igual(estado.estado_de(paso_id), "obsoleto", f"{paso_id} obsoleto")
        igual(estado.unidades_obsoletas(paso_id), ["S03"],
              f"{paso_id} obsoleto SOLO en S03")
        igual(estado.firma_unidad(paso_id, "S01"), firmas_antes[paso_id],
              f"la firma de S01 en {paso_id} no se movio")
    igual(descendientes_de("guion"),
          ["voz", "revision_audio", "assets", "callouts", "render"],
          "descendientes de guion segun el DAG")


def prueba_corregir_no_deja_obsoleto_al_que_corriges(base):
    """Arreglar a mano la salida de un paso no lo deja obsoleto A EL.

    Editar un bloque del guion no es pedirle otro guion al modelo: es arreglar
    el que dio. Volver a ejecutarlo no incorporaria la correccion -- la
    borraria --, asi que marcarlo obsoleto propone un remedio destructivo.

    Lo vivido el 01-09 con veintitres bloques retocados: `guion` obsoleto para
    siempre y, detras, assets, callouts y render. El video salia «Obsoleto»
    recien montado y cada montaje volvia a recorrer pasos sin nada que hacer.

    Lo que SI tiene que seguir invalidando es lo de aguas abajo: si cambias el
    texto, la voz hay que regrabarla. Esa mitad es la que no se puede perder al
    arreglar la otra.
    """
    print("\n[3b] corregir a mano no deja obsoleto al paso corregido")
    # CON SU PROPIO PROYECTO: la cadena compartida llega aqui con el guion ya
    # obsoleto a proposito, y lo que se mira es justo lo contrario.
    proyecto = Proyecto.crear(base, "Correcciones a mano")
    estado = Estado(proyecto)
    estado.completar("ingesta", {"transcript": "t.txt"})
    estado.completar("brief", {"brief": "b.json"})
    estado.completar("guion", {"fichero": "guion.json"})
    for paso_id in ("voz", "revision_audio", "assets", "callouts", "render"):
        estado.completar(paso_id, {"salida": paso_id})
    igual(estado.estado_de("guion"), "listo", "de partida, el guion esta al dia")

    estado.actualizar_params("guion", {"bloques": {"B002": {"texto": "otra cosa"}}})

    igual(estado.estado_de("guion"), "listo",
          "corregir un bloque NO deja obsoleto al guion: rehacerlo borraria la "
          "correccion, asi que la etiqueta propondria destruir lo que acabas de "
          "escribir")
    for paso_id in ("voz", "assets", "callouts", "render"):
        igual(estado.estado_de(paso_id), "obsoleto",
              f"{paso_id} SI queda obsoleto: se hizo leyendo el texto de antes")

    # y lo que no es una correccion sigue invalidando al propio paso
    estado.actualizar_params("guion", {"prompt_general": "mas directo"})
    igual(estado.estado_de("guion"), "obsoleto",
          "un param que SI es una entrada del paso lo deja obsoleto, como "
          "siempre: la excepcion es solo para lo que corrige su salida")

def prueba_rehacer_solo_s03(estado, proyecto):
    print("\n[4] rehacer solo lo afectado")
    estado.completar("guion", {"escenas": 3})
    estado.completar("voz", {"wav": "narracion.wav"})
    igual(estado.estado_de("guion"), "listo", "guion listo tras regenerar")
    igual(estado.estado_de("voz"), "listo", "voz lista tras regenerar")
    igual(estado.unidades_obsoletas("assets"), ["S03"],
          "assets sigue pidiendo solo S03")

    for paso_id in ("assets", "callouts", "render"):
        version = estado.completar(paso_id, {"total": 1},
                                   {"S03": {"png": f"{paso_id}_s03_v2.png"}})
        igual(version, 2, f"{paso_id} crea la version 2")
        igual(estado.estado_de(paso_id), "listo", f"{paso_id} listo tras rehacer S03")
        igual(estado.unidades_obsoletas(paso_id), [], f"{paso_id} sin unidades sucias")
        igual(estado.salidas_unidad(paso_id, "S01")["png"], f"{paso_id}_s01.png",
              f"{paso_id} conserva la salida original de S01")
        igual(estado.salidas_unidad(paso_id, "S03")["png"], f"{paso_id}_s03_v2.png",
              f"{paso_id} actualiza la salida de S03")

    comprobar(proyecto.ruta_paso("assets").endswith(os.path.join("assets", "v2")),
              "la ruta activa de assets apunta a v2")
    comprobar(proyecto.ruta_paso("assets", 1).endswith(os.path.join("assets", "v1")),
              "v1 de assets sigue accesible")
    igual([v["n"] for v in estado.versiones("assets")], [1, 2],
          "assets guarda las dos versiones")
    igual([v["activa"] for v in estado.versiones("assets")], [False, True],
          "solo la ultima esta activa")


def prueba_revertir(estado):
    print("\n[5] revertir y propagar")
    estado.revertir("guion", 1)
    igual(estado.params("guion")["unidades"]["S03"]["texto"], "la lancha huye",
          "revertir restaura los params de la version")
    igual(estado.estado_de("guion"), "listo", "guion vuelve a estar listo en v1")
    igual(estado.estado_de("voz"), "obsoleto", "voz queda obsoleta tras revertir el guion")

    for paso_id in ("assets", "callouts", "render"):
        igual(estado.estado_de(paso_id), "obsoleto",
              f"{paso_id} obsoleto tras revertir")
        igual(estado.unidades_obsoletas(paso_id), ["S03"],
              f"{paso_id} obsoleto solo en S03 tras revertir")

    estado.revertir("voz", 1)
    igual(estado.estado_de("voz"), "listo", "voz coherente al revertir a v1")
    for paso_id in ("assets", "callouts", "render"):
        estado.revertir(paso_id, 1)
        igual(estado.estado_de(paso_id), "listo",
              f"{paso_id} vuelve a estar listo en v1")
        igual(estado.salidas_unidad(paso_id, "S03")["png"], f"{paso_id}_s03.png",
              f"{paso_id} recupera la salida vieja de S03")
    igual([v["n"] for v in estado.versiones("render")], [1, 2],
          "revertir no borra la version 2")


def prueba_unidades_a_mano(estado, proyecto):
    print("\n[6] invalidar unidades a mano y recoger trabajo/")
    estado.invalidar_unidades("render", ["S02"])
    igual(estado.unidades_obsoletas("render"), ["S02"], "S02 marcada a mano")
    igual(estado.estado_de("render"), "obsoleto", "render obsoleto por una unidad")

    carpeta = proyecto.ruta_trabajo("render")
    with open(os.path.join(carpeta, "S02.mp4"), "w", encoding="utf-8") as fh:
        fh.write("bytes de video")
    version = estado.completar("render", {"total": 1}, {"S02": {"mp4": "S02.mp4"}})
    igual(estado.unidades_obsoletas("render"), [], "S02 deja de estar sucia")
    igual(estado.estado_de("render"), "listo", "render listo de nuevo")
    comprobar(os.path.isfile(os.path.join(proyecto.ruta_paso("render", version), "S02.mp4")),
              "lo escrito en trabajo/ acaba dentro de la version")
    comprobar(not os.path.isdir(proyecto.ruta_trabajo("render", crear=False)),
              "trabajo/ queda vacia tras versionar")


def prueba_versionar_con_fichero_abierto(estado, proyecto):
    """Versionar no se cae porque la interfaz este ensenando un fichero.

    En Windows, un fichero que otro proceso tiene abierto no se puede mover ni
    borrar --y mover una carpeta con uno dentro, tampoco--. La interfaz ensena
    los PNG de trabajo/ MIENTRAS el paso corre, asi que justo al versionar hay
    handles abiertos sobre lo que hay que mover, y el [WinError 32] tiraba una
    version entera de trabajo ya hecho y pagado. Lo que Windows si permite sobre
    un fichero abierto es sobrescribirlo: de ahi el plan B de `recolocar`.
    """
    print("\n[6c] versionar con un fichero abierto por otro (WinError 32)")
    estado.invalidar_unidades("render", ["S03"])
    carpeta = proyecto.ruta_trabajo("render")
    pases = os.path.join(carpeta, "pases")
    os.makedirs(pases, exist_ok=True)
    lamina = os.path.join(pases, "S03__fotograma.png")
    with open(lamina, "w", encoding="utf-8") as fh:
        fh.write("lo nuevo")
    with open(os.path.join(carpeta, "S03.mp4"), "w", encoding="utf-8") as fh:
        fh.write("bytes de video")

    # exactamente lo que hace el navegador: tenerlo abierto para ensenarlo
    mirando = open(lamina, "rb")
    try:
        version = estado.completar("render", {"total": 1},
                                   {"S03": {"mp4": "S03.mp4"}})
    finally:
        mirando.close()
    destino = proyecto.ruta_paso("render", version)
    comprobar(os.path.isfile(os.path.join(destino, "S03.mp4")),
              "la version se cierra igual, sin caerse")
    guardada = os.path.join(destino, "pases", "S03__fotograma.png")
    comprobar(os.path.isfile(guardada),
              "y el fichero que estaban mirando llega a la version")
    with open(guardada, encoding="utf-8") as fh:
        igual(fh.read(), "lo nuevo", "con su contenido, no con uno a medias")
    shutil.rmtree(proyecto.ruta_trabajo("render", crear=False), ignore_errors=True)


def prueba_retirar_unidades(estado, proyecto):
    """Un plano que ya no existe no puede dejar el paso obsoleto para siempre.

    Los ids de plano son posicionales y se heredan entre planes. Cuando un
    recorte nuevo deja fuera el ultimo plano, su unidad seguia DECLARADA en
    params y nadie volvia a producirla: `completar()` solo refresca la firma de
    lo que la pasada ha hecho, asi que la suya se quedaba vieja para siempre,
    `unidades_obsoletas` la seguia contando y el paso no salia nunca del ambar.
    Y no habia forma de limpiarlo: rehacer no la tocaba, porque el plan ya no la
    incluye.
    """
    print("\n[6d] un plano retirado del plan se des-declara")
    estado.actualizar_params("render", {"unidades": {
        "S01": {"x": 1}, "S02": {"x": 1}, "S03": {"x": 1}, "S99": {"x": 1}}})
    carpeta = proyecto.ruta_trabajo("render")
    for sid in ("S01", "S02", "S03", "S99"):
        with open(os.path.join(carpeta, f"{sid}.mp4"), "w", encoding="utf-8") as fh:
            fh.write("v")
    estado.completar("render", {"total": 4},
                     {u: {"mp4": f"{u}.mp4"} for u in ("S01", "S02", "S03", "S99")})
    comprobar("S99" in estado.unidades_declaradas("render"),
              "el plano nuevo queda declarado y producido")

    # el guion se recorta y S99 desaparece del plan
    estado.actualizar_params("render", {"unidades": {
        "S01": {"x": 2}, "S02": {"x": 1}, "S03": {"x": 1}, "S99": {"x": 1}}})
    estado.invalidar_unidades("render", ["S99"])
    comprobar("S99" in estado.unidades_obsoletas("render"),
              "el plano que ya no existe cuenta como pendiente")
    salida = estado.retirar_unidades("render", ["S99"], motivo="fuera del plan")
    igual(salida["retiradas"], ["S99"], "se retira")
    comprobar("S99" not in estado.unidades_obsoletas("render"),
              "y deja de contar como pendiente")
    comprobar("S99" not in estado.unidades_declaradas("render"),
              "porque deja de estar declarada, no porque se marque nada")
    comprobar(estado.retirar_unidades("render", ["S99"])["retiradas"] == [],
              "retirar lo que ya no esta no hace nada ni protesta")
    comprobar(any(e.get("unidades") == ["S99"] for e in estado.retiradas("render")),
              "y queda constancia de por que dejo de estar declarada")
    comprobar(not any(e.get("unidades") == ["S99"]
                      for e in estado.conservaciones("render")),
              "en SU historico, no en el de conservadas: ese alimenta el cartel "
              "de «conservado, no regenerado» y esto no es eso")
    # lo que SI sigue existiendo no se toca
    comprobar("S01" in estado.unidades_obsoletas("render"),
              "el plano que si existe y esta sucio sigue pendiente")
    comprobar(estado.estado_de("render") == "obsoleto",
              "y como queda algo sucio de verdad, el paso sigue en ambar")

    # RETIRAR NO PUEDE SER OTRA FORMA DE DEJARLO EN AMBAR. La firma del paso
    # incluye la lista de unidades DECLARADAS, asi que quitar una la mueve por si
    # sola: el paso se quedaba «obsoleto» con CERO unidades sucias -- nada que
    # rehacer, y aun asi naranja --, que es justo el estado que esta funcion
    # existe para evitar. Se vio en cuanto el fundido empezo a retirar unidades
    # de verdad.
    print("\n[6f] retirar no deja el paso en ambar si estaba al dia")
    # Se parte de un paso AL DIA de verdad: se sella todo lo declarado, que a
    # estas alturas de la suite son mas planos que los tres de arriba.
    #
    # Y la victima es una unidad PROPIA de render («S77», que se declara aqui
    # mismo). Una heredada del grafo no serviria: `unidades_declaradas` las junta
    # todas, asi que retirarla de render la dejaria declarada aguas arriba y
    # seguiria contando -- que es correcto, pero no es lo que esta prueba mira.
    estado.actualizar_params("render", {"unidades": {"S77": {"x": 1}}})
    todas = list(estado.unidades_declaradas("render"))
    estado.completar("render", {"total": len(todas)},
                     {u: {"mp4": f"{u}.mp4"} for u in todas})
    igual(estado.estado_de("render"), "listo", "el paso arranca al dia")
    estado.retirar_unidades("render", ["S77"], motivo="lo absorbio el fundido")
    igual(estado.unidades_obsoletas("render"), [],
          "tras retirar no queda ni una unidad sucia")
    igual(estado.estado_de("render"), "listo",
          "asi que el paso SIGUE al dia: retirar no descuadra lo que ya cuadraba")

    # y al reves: si NO estaba al dia, retirar no puede taparlo
    sucia, otra = todas[0], todas[1]
    estado.actualizar_params("render", {"unidades": {sucia: {"x": 9}}})
    igual(estado.estado_de("render"), "obsoleto", "un cambio de verdad lo ensucia")
    estado.retirar_unidades("render", [otra], motivo="otra que se va")
    igual(estado.estado_de("render"), "obsoleto",
          "y retirar OTRA cosa no lo resella: taparia una obsolescencia real")
    shutil.rmtree(proyecto.ruta_trabajo("render", crear=False), ignore_errors=True)


def prueba_sin_hacer(estado):
    """Distinguir lo que se quedo viejo de lo que no se ha hecho nunca.

    Las dos cosas hay que hacerlas, y por eso las dos salen en
    unidades_obsoletas, pero no son lo mismo y decirle a quien mira que un plano
    'ha quedado obsoleto' cuando no se ha generado jamas le manda a buscar un
    cambio aguas arriba que no ha existido.
    """
    print("\n[6b] sin hacer no es lo mismo que obsoleto")
    igual(estado.unidades_sin_hacer("assets"), [],
          "con todo producido no hay nada sin hacer")
    igual(estado.unidades_producidas("assets"), ["S01", "S02", "S03"],
          "y produjo las tres unidades")

    # una escena nueva: declarada, nunca producida
    estado.actualizar_params("guion", {"unidades": {"S04": {"texto": "amanece"}}})
    comprobar("S04" in estado.unidades_obsoletas("assets"),
              "la escena nueva sale como pendiente")
    igual(estado.unidades_sin_hacer("assets"), ["S04"],
          "y como SIN HACER, porque de ella no hay nada guardado")
    comprobar("S04" not in estado.unidades_producidas("assets"),
              "producidas no la cuenta")

    # y una vieja de verdad: se produjo y sus entradas cambiaron
    estado.actualizar_params("guion", {"unidades": {"S02": {"texto": "otra cosa"}}})
    igual(sorted(estado.unidades_obsoletas("assets")), ["S02", "S04"],
          "las dos estan pendientes")
    igual(estado.unidades_sin_hacer("assets"), ["S04"],
          "pero solo una no se ha hecho nunca: S02 es obsoleta de verdad")

    estado.completar("assets", {"total": 2}, {"S02": {"png": "s02_v3.png"},
                                              "S04": {"png": "s04.png"}})
    igual(estado.unidades_sin_hacer("assets"), [],
          "generarla la saca de sin hacer")
    igual(estado.estado_de("assets"), "listo", "y el paso vuelve a estar al dia")


def prueba_param_suelto_por_unidad(estado):
    """Un parametro que describe UN plano no se puede guardar suelto.

    Ha pasado dos veces -- el plan de cartelas y el de rotulos -- y las dos
    costo lo mismo verlo: guardar la decision de un plano dejaba obsoleto el
    video entero, porque todo lo que no es el bloque `unidades` entra en la
    firma GLOBAL del paso y con ella en la de cada unidad. Y no falla nada: solo
    sale naranja donde antes no lo habia, que se lee como cualquier otra cosa.
    La segunda vez se pago resellando cuarenta y nueve planos a mano.

    Una leccion en un documento no impide el tercer caso; esto si.
    """
    print("\n[6e] un param que describe un plano nunca va suelto")
    antes = dict(estado.params("assets") or {})
    obsoletas = estado.unidades_obsoletas("assets")
    try:
        estado.actualizar_params("assets", {"plan_de_algo": {"S02": {"x": 1}}})
        comprobar(False, "guardar un param indexado por unidad tendria que levantar")
    except ValueError as fallo:
        comprobar("plan_de_algo" in str(fallo) and "S02" in str(fallo),
                  "levanta diciendo QUE clave y QUE unidades la delatan")
        comprobar("unidades" in str(fallo),
                  "y donde va: dentro del bloque de unidades")
    igual(estado.params("assets"), antes, "y no se guarda nada a medias")
    igual(estado.unidades_obsoletas("assets"), obsoletas,
          "ni deja obsoleta ninguna unidad de rebote")

    # Lo mismo pero DENTRO de la unidad: es exactamente donde tiene que ir
    estado.actualizar_params("assets", {"unidades": {"S02": {"algo": {"x": 1}}}})
    comprobar("S02" in estado.unidades_obsoletas("assets"),
              "por unidad se guarda, y ensucia SOLO ese plano")
    igual([u for u in estado.unidades_obsoletas("assets") if u != "S02"],
          [u for u in obsoletas if u != "S02"],
          "los demas planos siguen como estaban")
    estado.completar("assets", {"total": 1}, {"S02": {"png": "s02_v4.png"}})

    # Un param global de verdad -- describe el video, no un plano -- pasa
    estado.actualizar_params("assets", {"estilo": {"guia": "seco", "referencias": []}})
    igual((estado.params("assets") or {}).get("estilo", {}).get("guia"), "seco",
          "y un param que describe el video entero se guarda sin ruido")

    # UNA CLAVE VIEJA QUE YA ESTABA NO BLOQUEA NADA. Es lo que pasa al revertir a
    # una version de antes de que esto existiera: sus params se restauran tal
    # cual, y si guardar cualquier otra cosa levantara, el proyecto se quedaria
    # sin poder tocarse. La migracion la hace la pantalla que conoce esa clave.
    with estado._lock:
        estado._sincronizar()
        estado._doc["pasos"]["assets"]["params"]["plan_viejo"] = {"S02": {"x": 1}}
        estado._guardar()
    estado._cache = {}
    estado.actualizar_params("assets", {"calidad": "alta"})
    igual((estado.params("assets") or {}).get("calidad"), "alta",
          "con una clave vieja guardada se sigue pudiendo guardar lo demas")
    try:
        estado.actualizar_params("assets", {"plan_viejo": {"S02": {"x": 2}}})
        comprobar(False, "pero CAMBIARLA si tendria que levantar")
    except ValueError:
        comprobar(True, "pero cambiarla levanta: eso ya es introducir el fallo")
    estado.actualizar_params("assets", {"plan_viejo": None})


def prueba_persistencia(estado, proyecto):
    print("\n[7] persistencia entre instancias")
    otro = Estado(proyecto)
    esperados = {p["id"]: estado.estado_de(p["id"]) for p in PASOS}
    obtenidos = {p["id"]: otro.estado_de(p["id"]) for p in PASOS}
    igual(obtenidos, esperados, "una instancia nueva ve el mismo estado")
    igual(otro.params("guion"), estado.params("guion"), "los params sobreviven")

    otro.set_params("revision_audio", {"umbral": 0.4})
    igual(estado.estado_de("revision_audio"), "pendiente",
          "la primera instancia recarga los cambios de la segunda")
    ficha = estado.resumen()
    igual([p["id"] for p in ficha["pasos"]], [p["id"] for p in PASOS],
          "resumen devuelve los ocho pasos en orden")
    igual(ficha["proyecto"], proyecto.id, "resumen identifica el proyecto")


def prueba_bitacora(proyecto, estado):
    print("\n[8] bitacora")
    bitacora = Bitacora(proyecto)
    bitacora.anotar("creado", "ingesta", {"url": "https://ejemplo/1"})
    bitacora.anotar("regenerado", "assets", {"motivo": "la cara sale rara"}, unidad="S03")
    bitacora.anotar("aprobado", "assets", {"revisor": "humano"}, unidad="S01")

    igual(len(bitacora.leer()), 3, "tres eventos escritos")
    igual(len(bitacora.leer(paso="assets")), 2, "filtra por paso")
    igual(len(bitacora.leer(paso="assets", unidad="S03")), 1, "filtra por unidad")
    igual(len(bitacora.leer(limite=1)), 1, "respeta el limite")
    igual(bitacora.leer(limite=1)[0]["evento"], "aprobado", "el limite coge lo mas nuevo")

    texto = bitacora.resumen_para_llm()
    comprobar("== assets" in texto, "el resumen agrupa por paso")
    comprobar("[S03]" in texto, "el resumen agrupa por unidad")
    comprobar("la cara sale rara" in texto, "el resumen conserva los datos")

    globales = bitacora.eventos_globales(proyecto=proyecto.id)
    comprobar(len(globales) >= 3, "los eventos tambien van al log global")
    comprobar(all(g["proyecto"] == proyecto.id for g in globales),
              "el log global anota el proyecto")
    comprobar(os.path.isfile(proyecto.ruta("bitacora.jsonl")),
              "bitacora.jsonl vive dentro del proyecto")
    igual(estado.estado_de("ingesta"), "listo", "la bitacora no toca el estado")
    return bitacora


def prueba_trabajos(estado, bitacora):
    print("\n[9] trabajos en segundo plano")
    gestor = GestorTrabajos(estado=estado, bitacora=bitacora)

    def contar(avisar, veces):
        for indice in range(veces):
            avisar((indice + 1) / veces, f"paso {indice + 1}",
                   f"Trabajando {indice + 1}")
            time.sleep(0.01)
        return {"veces": veces}

    def reventar(avisar):
        avisar(0.5, "a punto de fallar")
        raise RuntimeError("cartesia devolvio 500")

    def eterno(avisar):
        for indice in range(500):
            avisar(min(0.99, indice / 500), "trabajando")
            time.sleep(0.01)
        return "no deberia llegar"

    identificador = gestor.lanzar("contar", contar, 5, paso="revision_audio")
    ficha = gestor.esperar(identificador, 10)
    igual(ficha["estado"], "listo", "trabajo correcto termina listo")
    igual(ficha["progreso"], 1.0, "progreso al 100%")
    igual(ficha["resultado"], {"veces": 5}, "devuelve el resultado de la funcion")
    comprobar(ficha["segundos"] >= 0, "mide el tiempo")
    # DOS MENSAJES Y NO UNO: el de casa con sus cifras y el PUBLICO, que es lo
    # que lee la pantalla que se graba (modo light). Viajan juntos y por
    # separado: enmascarar el unico que hubiera dejaria al modo editor sin
    # saber por donde va y a la bitacora sin nada que investigar.
    igual(ficha["mensaje"], "paso 5", "guarda el mensaje de casa")
    igual(ficha["publico"], "Trabajando 5", "y el publico, aparte")

    def callado(avisar):
        avisar(0.4, "detalle de casa")
        return "ya"

    identificador = gestor.lanzar("callado", callado, paso="revision_audio")
    ficha = gestor.esperar(identificador, 10)
    igual(ficha["publico"], "",
          "quien no manda mensaje publico no hereda ninguno: la pantalla que "
          "se graba prefiere un hueco antes que el mensaje de casa")
    estado.limpiar_marca("revision_audio")
    igual(estado.estado_de("revision_audio"), "pendiente",
          "la marca de ejecutando se limpia al acabar")

    identificador = gestor.lanzar("reventar", reventar, paso="revision_audio")
    ficha = gestor.esperar(identificador, 10)
    igual(ficha["estado"], "error", "trabajo fallido queda en error")
    comprobar("cartesia devolvio 500" in (ficha["error"] or ""), "guarda el error")
    igual(estado.estado_de("revision_audio"), "error", "el paso hereda el error")
    estado.limpiar_marca("revision_audio")
    igual(estado.estado_de("revision_audio"), "pendiente", "la marca se puede limpiar")

    identificador = gestor.lanzar("eterno", eterno, paso="revision_audio")
    while gestor.estado(identificador)["estado"] != "ejecutando":
        time.sleep(0.01)
    comprobar(len(gestor.listar(activos=True)) == 1, "listar ve el trabajo activo")
    comprobar(gestor.cancelar(identificador), "cancelar acepta el trabajo vivo")
    ficha = gestor.esperar(identificador, 10)
    igual(ficha["estado"], "cancelado", "el trabajo se cancela de verdad")
    igual(gestor.listar(activos=True), [], "ya no queda nada activo")
    igual(len(gestor.listar(activos=False)), 4, "el historico guarda los cuatro")
    estado.limpiar_marca("revision_audio")


def prueba_duplicar(proyecto, estado, base):
    """Una copia es lo que hay puesto HOY, con las rutas mudadas.

    Dos cosas que hay que sujetar con pruebas, porque las dos fallan en silencio:

      1. la copia arranca en v1 y no arrastra el historial. En el video largo eso
         es la diferencia entre 0,89 GB y 11,6;
      2. **las rutas absolutas se mudan**. El estado guarda miles (el wav de la
         locucion, los fotogramas, cada salida de cada paso). Una copia con el
         estado tal cual apunta a los ficheros del ORIGINAL, y trabajar en ella
         iria escribiendo encima del proyecto de al lado sin decir nada.
    """
    print("\n[9] duplicar")
    # una salida con RUTA ABSOLUTA dentro del proyecto, que es el caso que
    # importa: si esto no se muda, la copia lee del original
    dentro = os.path.join(proyecto.ruta_trabajo("guion"), "dentro.txt")
    with io.open(dentro, "w", encoding="utf-8") as fh:
        fh.write("hola")
    estado.completar("guion", {"resumen": "con ruta", "fichero": dentro})
    version_origen = proyecto.version_activa("guion")
    comprobar(version_origen and version_origen > 1,
              f"el original va por la v{version_origen} de guion")

    copia = proyecto.duplicar(base, "Copia Caso Meridiano")
    igual(copia.id, "copia_caso_meridiano", "la copia tiene su propio id")
    igual(copia.config.get("copia_de"), proyecto.id, "y apunta de quien es copia")
    comprobar(copia.raiz != proyecto.raiz, "y su propia carpeta")

    igual(copia.version_activa("guion"), version_origen,
          "la copia CONSERVA el numero de version: renumerar cambia el sello "
          "del paso (`huella([activa, firma])`) y deja la copia entera en "
          "obsoleto sin que haya cambiado un solo byte de lo producido")
    comprobar(os.path.isdir(copia.ruta_paso("guion", version_origen)),
              "y la carpeta de esa version existe con el contenido copiado")
    comprobar(not os.path.isdir(copia.ruta("pasos", "guion", "v1")),
              "el historial NO viaja: la v1 del original no esta en la copia")

    estado_copia = Estado(copia)
    guardado = estado_copia.salidas("guion").get("fichero") or ""
    comprobar(guardado.lower().startswith(copia.raiz.lower()),
              f"LA RUTA SE MUDA a la copia: {guardado}")
    comprobar(not guardado.lower().startswith(proyecto.raiz.lower()),
              "y no cuelga de la carpeta del original. Se compara la RAIZ y no "
              "el id porque el id de una copia contiene el del original "
              "('copia_caso_meridiano'), asi que buscar el id daria un falso "
              "positivo justo en el caso normal")
    igual(len(estado_copia.versiones("guion")), 1,
          "el estado tampoco declara versiones que no estan en disco")
    igual(estado_copia.estado_de("guion"), "listo",
          "y la copia arranca al dia: es lo que el original tenia puesto")

    # con `saltar`, el paso se queda SIN HACER en vez de a medias
    otra = proyecto.duplicar(base, "Copia sin guion", saltar=("guion",))
    estado_otra = Estado(otra)
    igual(estado_otra.versiones("guion"), [],
          "un paso salteado no trae ninguna version")
    comprobar(estado_otra.estado_de("guion") in ("pendiente", "bloqueado"),
              f"y queda sin hacer, no listo ({estado_otra.estado_de('guion')})")
    shutil.rmtree(otra.raiz, ignore_errors=True)
    shutil.rmtree(copia.raiz, ignore_errors=True)


def principal():
    base = tempfile.mkdtemp(prefix="estudio_prueba_")
    conservar = "--conservar" in sys.argv
    try:
        proyecto = prueba_proyecto(base)
        estado = Estado(proyecto)
        prueba_primer_pase(estado)
        prueba_cambio_de_escena(estado)
        prueba_corregir_no_deja_obsoleto_al_que_corriges(base)
        prueba_rehacer_solo_s03(estado, proyecto)
        prueba_revertir(estado)
        prueba_unidades_a_mano(estado, proyecto)
        prueba_versionar_con_fichero_abierto(estado, proyecto)
        prueba_sin_hacer(estado)
        prueba_retirar_unidades(estado, proyecto)
        prueba_param_suelto_por_unidad(estado)
        prueba_persistencia(estado, proyecto)
        bitacora = prueba_bitacora(proyecto, estado)
        prueba_trabajos(estado, bitacora)
        prueba_duplicar(proyecto, estado, base)
    finally:
        if conservar:
            print(f"\nproyecto temporal conservado en {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones:")
        for texto in FALLOS:
            print(f"  - {texto}")
        return 1
    print("NUCLEO OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
