"""
Prueba del medidor de coste y de las capturas anotables.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\prueba_coste_capturas.py

Que se prueba de verdad, sin gastar un centimo:

  coste     el medidor sobre ficheros reales (eventos, ids correlativos,
            agregados, presupuesto, tarifas) y la instrumentacion enganchada a
            las funciones reales de los pasos, con la llamada de red sustituida
            por un doble que devuelve el mismo 'usage' que devuelve la API.

  capturas  el almacen, la traduccion a instruccion agrupada y ordenada por
            instante, y el ciclo completo por HTTP: se ejecuta callouts DE
            VERDAD, se toma una captura sobre el rotulo colocado, se aplica y
            se comprueba que el rotulo cambia de sitio y que solo se rehizo esa
            escena.

Con --conservar no borra la carpeta temporal.
"""
import argparse
import json
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile

# La salud de las cuentas del CLI (pasos/salud_cli.py) se apunta en CADA
# llamada, tambien en las de los dobles de esta suite: sin redirigirla iria
# al almacen de claves de verdad.
os.environ.setdefault("ESTUDIO_SECRETOS", tempfile.mkdtemp(prefix="secretos_prueba_"))
import time

RAIZ_ESTUDIO = os.path.dirname(os.path.abspath(__file__))
if RAIZ_ESTUDIO not in sys.path:
    sys.path.insert(0, RAIZ_ESTUDIO)

import requests  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

PYTHON = sys.executable
APP = os.path.join(RAIZ_ESTUDIO, "app.py")
TAMANO = (1536, 1024)

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
    return ok(obtenido == esperado, f"{mensaje} (esperaba {esperado!r}, "
                                    f"llego {obtenido!r})")


def seccion(titulo):
    print(f"\n  {titulo}")


# ------------------------------------------------------------------- semilla

def plano_de_prueba(destino):
    """Plano con una franja rayada en medio y hueco limpio a los dos lados.

    Hace falta detalle real (bordes), no color: la mascara del paso 7 mira la
    desviacion local, asi que un rectangulo plano no cuenta como dibujo.
    """
    imagen = Image.new("RGB", TAMANO, (18, 19, 15))
    lapiz = ImageDraw.Draw(imagen)
    aleatorio = random.Random(7)
    for _ in range(400):
        x = aleatorio.randint(560, 980)
        y = aleatorio.randint(40, TAMANO[1] - 40)
        lapiz.line([(x, y), (x + aleatorio.randint(-60, 60),
                             y + aleatorio.randint(-60, 60))],
                   fill=(215, 205, 180), width=3)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    imagen.save(destino, "PNG")
    return destino


# LAS MARCAS DE VOZ VAN EN LA SEMILLA, y hacen falta desde el 22-08: el
# subtitulo ES la narracion y su hora sale de la marca de cada palabra
# (`subtitulos.de_escena`). Sin ellas la guarda devuelve [] -- «sin subtitulo
# antes que con uno desplazado»-- y este proyecto de prueba saldria mudo.
ESCENAS = [
    {"id": "S001", "t_in": 0.0, "t_out": 6.0, "duracion": 6.0,
     "narracion": 'El puerto amanece con la carga a medio bajar.',
     "marcas": [[0.1, 0.436], [0.52, 0.856], [0.94, 1.276], [1.36, 1.696], [1.78, 2.116], [2.2, 2.536], [2.62, 2.956], [3.04, 3.376], [3.46, 3.796]],
     "zoom": {"de": 1.0, "a": 1.18, "centro": [0.5, 0.5]},
     "transicion": "corte", "capa_vectorial": []},
    {"id": "S002", "t_in": 6.0, "t_out": 11.0, "duracion": 5.0,
     "narracion": 'La bodega guarda lo que nadie declara.',
     "marcas": [[6.1, 6.436], [6.52, 6.856], [6.94, 7.276], [7.36, 7.696], [7.78, 8.116], [8.2, 8.536], [8.62, 8.956]],
     "zoom": {"de": 1.0, "a": 1.1, "centro": [0.5, 0.5]},
     "transicion": "corte", "capa_vectorial": []},
]


def sembrar(raiz_proyectos, nombre="coste y capturas"):
    """Deja el proyecto con los pasos previos hechos y assets con su plan."""
    from nucleo.estado import Estado
    from nucleo.proyecto import Proyecto, escribir_json

    proyecto = Proyecto.crear(raiz_proyectos, nombre)
    estado = Estado(proyecto)

    for paso, params, salidas in (
            ("ingesta", {"url": "https://ejemplo/prueba"},
             {"video": "origen.webm", "resumen": "semilla"}),
            ("brief", {"duracion_s": 30}, {"tema": "prueba", "resumen": "brief"}),
            ("guion", {"idioma": "es"}, {"guion": "guion.json", "resumen": "guion"}),
            ("voz", {"idioma": "es"}, {"pista": "narracion.wav", "resumen": "voz"})):
        escribir_json(os.path.join(proyecto.ruta_trabajo(paso), f"{paso}.json"),
                      salidas)
        estado.set_params(paso, params)
        estado.completar(paso, salidas)

    trabajo = proyecto.ruta_trabajo("assets")
    for escena in ESCENAS:
        plano_de_prueba(os.path.join(trabajo, "escenas", f"{escena['id']}.png"))
    os.makedirs(os.path.join(trabajo, "assets", "sets"), exist_ok=True)
    plan = {"fps": 30, "resolucion": [1920, 1080], "escenas": ESCENAS,
            "assets": {}, "dependencias": {f"escena:{e['id']}": [] for e in ESCENAS}}
    escribir_json(os.path.join(trabajo, "plan.json"), plan)
    estado.set_params("assets", {"calidad": "low", "unidades": {
        f"escena:{e['id']}": {"assets": []} for e in ESCENAS}})
    estado.completar("assets", {"plan": "plan.json", "resumen": "semilla de assets"},
                     {f"escena:{e['id']}": {"tipo": "escena",
                                            "png": f"escenas/{e['id']}.png"}
                      for e in ESCENAS})
    return proyecto


# ------------------------------------------------------------------- medidor

def prueba_medidor(proyecto):
    from nucleo import coste

    seccion("medidor: eventos, agregados y presupuesto")
    medidor = coste.Medidor(proyecto)

    primero = medidor.anotar("openai", "assets", "generar_escena",
                             unidad="escena:S001",
                             tokens={"entrada": 1420, "salida": 0},
                             cantidad={"imagenes": 1},
                             usd=coste.tarifa_imagen("1536x1024", "medium"),
                             usd_estimado=True)
    igual(primero["id"], "ev_00001", "el primer evento es ev_00001")
    igual(primero["usd"], 0.041, "el importe sale de la tabla de tarifas")
    ok(primero["usd_estimado"] is True, "lo derivado de tarifa va marcado")

    segundo = medidor.anotar("openai", "assets", "generar_escena",
                             unidad="escena:S002",
                             tokens={"entrada": 1380, "salida": 0},
                             cantidad={"imagenes": 1},
                             usd=coste.tarifa_imagen("1536x1024", "medium"),
                             usd_estimado=True)
    igual(segundo["id"], "ev_00002", "los ids son correlativos")

    voz = medidor.anotar("tts", "voz", "toma", cantidad={"caracteres": 41200},
                         usd=coste.tarifa_caracter())
    ok(voz["usd"] is None and voz.get("sin_tarifa") is True,
       "sin tarifa de Cartesia el evento se anota sin importe y marcado")

    cli = medidor.anotar("claude_cli", "guion", "redactar",
                         tokens={"entrada": 120000, "salida": 4000, "cache": 60000},
                         usd=9.99)
    ok(cli["usd"] is None, "claude_cli nunca lleva dolares aunque se los pasen")

    total = medidor.total()
    igual(total["eventos"], 4, "cuenta los cuatro eventos")
    igual(round(total["total_usd"], 4), 0.082, "el total solo suma openai y tts")
    igual(total["proveedores"]["claude_cli"]["tokens"]["total"], 184000,
          "claude suma sus tokens")
    ok(total["proveedores"]["claude_cli"]["suma_al_total"] is False,
       "claude queda fuera del total")
    igual(total["proveedores"]["tts"]["cantidad"]["caracteres"], 41200,
          "los caracteres de la voz son los enviados")
    ok("184k tok" in total["cabecera"] and "41.2k car" in total["cabecera"],
       f"la cabecera va formateada: {total['cabecera']}")
    ok("TOTAL  $0.08" in total["cabecera"], "el TOTAL sale en la cabecera")

    por_paso = medidor.por_paso()
    pasos = {f["paso"]: f for f in por_paso["pasos"]}
    igual(round(pasos["assets"]["total_usd"], 4), 0.082,
          "assets se lleva todo el gasto en dolares")
    igual(pasos["voz"]["proveedores"]["tts"]["cantidad"]["caracteres"], 41200,
          "el paso de voz se lleva los caracteres")
    igual([f["paso"] for f in por_paso["pasos"]][:3],
          ["ingesta", "brief", "guion"], "los pasos salen en orden de pipeline")

    filtrados = medidor.eventos(proveedor="openai")
    igual(len(filtrados), 2, "el filtro por proveedor funciona")
    igual(len(medidor.eventos(paso="voz")), 1, "el filtro por paso funciona")
    igual(len(medidor.eventos(unidad="escena:S001")), 1,
          "el filtro por unidad funciona")

    medidor.fijar_presupuesto(0.09)
    total = medidor.total()
    ok(total["fraccion_presupuesto"] > 0.8 and total["aviso_presupuesto"],
       "avisa al pasar del 80% del presupuesto")
    medidor.fijar_presupuesto(None)
    ok(medidor.total()["presupuesto_usd"] is None, "el presupuesto se puede quitar")

    seccion("medidor: la tarifa que falta se puede rellenar")
    coste.guardar_tarifas({"tts": {"usd_por_caracter": 0.000025}})
    ok(coste.tarifa_caracter() == 0.000025, "la tarifa nueva entra en vigor sola")
    nuevo = medidor.anotar("tts", "voz", "toma", cantidad={"caracteres": 1000},
                           usd=coste.tarifa_caracter() * 1000, usd_estimado=True)
    igual(nuevo["usd"], 0.025, "con tarifa el importe ya sale")
    ok(medidor.eventos()[2]["usd"] is None,
       "los eventos viejos no se reescriben al cambiar la tarifa")
    coste.guardar_tarifas({"tts": {"usd_por_caracter": None}})
    ok(coste.tarifa_caracter() is None, "y se puede volver a dejar vacia")

    global_ = coste.resumen_global()
    mios = [p for p in global_["proyectos"] if p["proyecto"] == proyecto.id]
    igual(len(mios), 1, "el agregado global separa por proyecto")
    ok(mios[0]["eventos"] >= 5, "el global tiene los eventos de este video")


# ----------------------------------------------------------- instrumentacion

class FalsoProceso:
    """Un Popen de mentira, para no llamar al CLI de verdad.

    Los cuatro sitios que hablan con el CLI pasan por pasos/cli_claude, que usa
    Popen y no run: hace falta para poder matar el arbol de procesos al vencer el
    plazo y para que la cancelacion desde la UI llegue al hijo.
    """

    def __init__(self, sobre):
        self.returncode = 0
        self.stdout = json.dumps(sobre).encode("utf-8")
        self.stderr = b""
        self.pid = 4242
        self.matado = False

    def communicate(self, entrada=None, timeout=None):
        return self.stdout, self.stderr

    def kill(self):
        self.matado = True


def prueba_instrumentacion(proyecto):
    from nucleo import coste
    import pasos

    seccion("instrumentacion: los motores reportan lo que consumen")

    # hay mas de una copia cargada del motor de imagen (ver modulos_de_imagen):
    # el doble tiene que ponerse en todas o la llamada se iria a la red de verdad
    copias = coste.modulos_de_imagen(pasos)
    ok(len(copias) >= 1, f"encuentra el motor de imagen cargado ({len(copias)})")
    imagen = copias[0]
    llamadas = {"imagen": 0, "voz": 0, "voz_contexto": 0, "claude": 0}

    def falsa_imagen(prompt, referencias, *, quality="low", tamano="apaisado",
                     api_key=None, reintentos=2):
        llamadas["imagen"] += 1
        return (b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                {"segundos": 1.0, "quality": quality, "refs": len(referencias),
                 "coste": imagen.PRECIO[quality], "modelo": imagen.MODELO,
                 "tamano": imagen.TAMANOS[tamano],
                 "usage": {"input_tokens": 1543, "output_tokens": 4096,
                           "input_tokens_details": {"cached_tokens": 128}}})

    def falsa_toma(texto, cfg, progreso=None):
        llamadas["voz"] += 1
        return b"RIFF", 4.0, [{"w": "hola", "s": 0.0, "e": 0.4}]

    def falsa_toma_contexto(trozos, cfg, progreso=None):
        llamadas["voz_contexto"] += 1
        return b"RIFF", 9.0, [{"w": "hola", "s": 0.0, "e": 0.4}]

    def falso_claude(instruccion, opciones, cwd):
        llamadas["claude"] += 1
        sobre = {"result": "{}", "duration_ms": 4200, "total_cost_usd": 0.31,
                 "usage": {"input_tokens": 900, "output_tokens": 1200,
                           "cache_creation_input_tokens": 3000,
                           "cache_read_input_tokens": 15000}}
        return sobre["result"], sobre

    # los dobles se ponen ANTES de instrumentar: lo que se prueba es el enganche
    # real, con la unica parte que cuesta dinero (la llamada de red) sustituida
    for copia in copias:
        copia.generar = falsa_imagen
    pasos.p4_voz._toma_real = falsa_toma
    pasos.p4_voz._toma_por_contexto = falsa_toma_contexto
    pasos.p3_guion._llamar_claude = falso_claude
    informe = coste.instrumentar(pasos)
    ok("assets.producir_imagen" in informe["enganchado"], "engancha assets")
    ok("imagen_openai.generar" in informe["enganchado"], "engancha el motor de imagen")
    ok("voz.toma_real" in informe["enganchado"], "engancha la toma de voz")
    # LA TOMA POR CONTEXTO ES EL CAMINO NORMAL y no estaba enganchada: cualquier
    # guion con mas de una seccion --o sea, todos-- graba por aqui, y tambien
    # regrabar una seccion suelta. Medido en un video real: veinte minutos de
    # locucion y CERO caracteres en el medidor.
    ok("voz.toma_por_contexto" in informe["enganchado"],
       "engancha tambien la toma por contexto, que es por donde graban todos")
    ok("guion.claude" in informe["enganchado"], "engancha el CLI del guion")
    igual(informe["ausente"], [], "no falta nada por enganchar")

    # Y QUE DE VERDAD ANOTA: enganchar sin que llegue un evento seria el mismo
    # hueco con otro nombre.
    medidor_voz = coste.Medidor(proyecto)
    antes_voz = len(medidor_voz.eventos())
    with coste.contexto(proyecto, "voz"):
        pasos.p4_voz._toma_por_contexto(["hola que tal", "y adios"],
                                        {"modelo": "sonic-3.5", "idioma": "es"})
    nuevos = medidor_voz.eventos()[antes_voz:]
    igual(len(nuevos), 1, "una toma por contexto deja un evento")
    igual(nuevos[0]["proveedor"], "tts", "del proveedor de voz")
    igual(nuevos[0]["cantidad"]["caracteres"], len("hola que tal") + len("y adios"),
          "con los caracteres de TODAS las entradas del contexto")
    igual(nuevos[0]["detalle"]["secciones"], 2, "y cuantas secciones eran")

    import inspect
    firma = inspect.signature(pasos.p7_callouts.ejecutar).parameters
    ok("unidades" in firma, "envolver el paso no le cambia la firma que ve la API")

    medidor = coste.Medidor(proyecto)
    antes = len(medidor.eventos())
    banco = os.path.join(proyecto.raiz, "banco")
    with coste.contexto(proyecto, "assets"):
        producida = pasos.p6_assets._producir_imagen(
            "S001", "un plano de prueba", [],
            os.path.join(proyecto.raiz, "tmp", "escenas", "S001.png"),
            {"calidad": "medium", "motor_imagen": "openai",
             "banco_imagenes": banco, "imagenes_previas": []})
    eventos = medidor.eventos()[antes:]
    igual(len(eventos), 1, "una llamada al motor deja un evento")
    evento = eventos[0]
    igual(evento["proveedor"], "openai", "el proveedor es openai")
    igual(evento["paso"], "assets", "el paso sale del contexto")
    igual(evento["unidad"], "escena:S001", "la unidad sale de la carpeta destino")
    igual(evento["tokens"]["entrada"], 1543, "los tokens son los que dio la API")
    igual(evento["tokens"]["cache"], 128, "la cache va aparte")
    # El importe sale de tarifas.json y NO del motor, igual que siempre; lo que
    # cambia es por que via. Antes se cobraba solo la imagen devuelta (0,041 $ en
    # medium) y los tokens de ENTRADA se anotaban sin tarifar: en una tanda real
    # eso escondia el 90% del gasto. Ahora manda el recuento de tokens.
    #
    # Se calcula con las tarifas vivas en vez de escribir la cifra a mano: asi la
    # prueba sigue comprobando lo que importa -que el importe salga de la tabla-
    # el dia que OpenAI cambie el precio, en vez de romperse por un numero.
    precios = coste.tarifa_tokens()
    esperado = round(1543 * precios["entrada_imagen"] + 4096 * precios["salida"], 6)
    igual(evento["usd"], esperado, "el importe sale de tarifas.json, no del motor")
    igual(evento["detalle"]["coste"]["via"], "tokens",
          "y sale por tokens, que es donde esta el grueso del gasto")

    # Y EL IMPORTE DE VERDAD LLEGA AL PASO, no solo al fichero de coste.
    #
    # Hasta el 22-08 el paso se quedaba con `meta["coste"]`, que es el precio de
    # la TABLA POR IMAGEN del motor: la bitacora del video largo dijo «45 imagenes,
    # 0,264 $» de una tanda que costo 1,3776 $ segun coste.jsonl. Un factor de
    # cinco entre lo que se leia y lo que se pagaba.
    igual(producida["coste"], esperado,
          "el paso se queda con el importe por TOKENS, no con el de la tabla")
    ok(producida["coste"] > imagen.PRECIO["medium"],
       f"que es mayor que el de la tabla ({imagen.PRECIO['medium']} $): la "
       f"tabla solo cubre la imagen devuelta, y la entrada son las referencias")
    igual(round(sum(e["usd"] for e in eventos), 6), round(producida["coste"], 6),
          "asi que lo que suma el paso y lo que registra el medidor son EL "
          "MISMO numero: sin eso, la pantalla y la factura no cuadran")
    ok(evento["usd"] > coste.tarifa_imagen("1536x1024", "medium"),
       "cobrar la entrada da mas que cobrar solo la imagen devuelta")
    igual(evento["cantidad"]["imagenes"], 1, "cuenta la imagen")

    antes = len(medidor.eventos())
    locucion = "Hola, esto es lo unico que se manda a sintetizar."
    with coste.contexto(proyecto, "voz"):
        pasos.p4_voz.sintetizar_toma(locucion, {"modelo": "sonic-3",
                                                "voz_id": "abc", "idioma": "es"})
    evento = medidor.eventos()[antes:][0]
    igual(evento["proveedor"], "tts", "la voz reporta como tts")
    igual(evento["cantidad"]["caracteres"], len(locucion),
          "los caracteres son los del texto enviado, contados uno a uno")
    ok(evento["usd"] is None and evento["sin_tarifa"],
       "sin tarifa de Cartesia el evento queda marcado")

    antes = len(medidor.eventos())
    with coste.contexto(proyecto, "guion"):
        pasos.p3_guion._llamar_claude("redacta", {"modelo": "sonnet"}, proyecto.raiz)
    evento = medidor.eventos()[antes:][0]
    igual(evento["proveedor"], "claude_cli", "el CLI reporta como claude_cli")
    igual(evento["tokens"]["cache"], 18000, "suma creacion y lectura de cache")
    ok(evento["usd"] is None, "el CLI no aporta dolares")
    igual(evento["detalle"]["coste_suscripcion_usd"], 0.31,
          "el coste del CLI se guarda como dato, no como gasto del video")

    igual(llamadas, {"imagen": 1, "voz": 1, "voz_contexto": 1, "claude": 1},
          "cada doble se llamo exactamente una vez")
    ok(coste.informe_instrumentacion()["sin_contexto"]["eventos"] == 0,
       "ningun evento se quedo sin proyecto")

    ok(coste.instrumentar(pasos)["enganchado"] == informe["enganchado"],
       "instrumentar dos veces no duplica el enganche")
    antes = len(medidor.eventos())
    with coste.contexto(proyecto, "voz"):
        pasos.p4_voz.sintetizar_toma("otra vez", {"modelo": "sonic-3"})
    igual(len(medidor.eventos()) - antes, 1, "y no cuenta dos veces lo mismo")


# ---------------------------------------------------------------- geometria

def prueba_geometria():
    from pasos import p7_callouts as p7

    seccion("geometria: la captura y el video miran el mismo pixel")
    mov = {"ventana_ini": [0.0, 0.0, 1.0, 1.0],
           "ventana_fin": [0.1, 0.1, 0.8, 0.8]}
    ancho, alto = 3072, 2048
    aspecto = 1920 / 1080

    ini = p7.ventana_en(mov, 0.0, (ancho, alto), aspecto)
    ok(abs(ini[0]) < 0.01 and abs(ini[2] - ancho) < 0.01,
       f"en 0 la ventana es el plano entero de ancho: {ini}")
    ok(abs((ini[3] - ini[1]) - ancho / aspecto) < 0.01,
       "y esta recortada al 16:9 de salida")

    fin = p7.ventana_en(mov, 1.0, (ancho, alto), aspecto)
    ok(fin[2] - fin[0] < ini[2] - ini[0], "en 1 la ventana es mas pequena (zoom)")

    medio = p7.ventana_en(mov, 0.5, (ancho, alto), aspecto)
    esperado = (ini[0] + fin[0]) / 2
    ok(abs(medio[0] - esperado) < 1.0,
       "a mitad de recorrido la interpolacion suavizada cae en el medio")

    centro = p7.punto_en_plano(mov, 1.0, 0.5, 0.5, (ancho, alto), aspecto)
    esperado = ((fin[0] + fin[2]) / 2 / ancho, (fin[1] + fin[3]) / 2 / alto)
    ok(abs(centro[0] - esperado[0]) < 1e-6 and abs(centro[1] - esperado[1]) < 1e-6,
       "el centro de la pantalla cae en el centro de la ventana de ese instante")

    esquina = p7.punto_en_plano(mov, 1.0, 0.0, 0.0, (ancho, alto), aspecto)
    ok(esquina[0] > 0.05, "con el zoom entrado, la esquina de la pantalla ya no "
                          "es la esquina del plano")


# ------------------------------------------------------------------ almacen

def png_de_prueba(color=(80, 90, 70)):
    import io

    imagen = Image.new("RGB", (320, 180), color)
    memoria = io.BytesIO()
    imagen.save(memoria, "PNG")
    return memoria.getvalue()


def sembrar_render(proyecto):
    """Sella una version de render, como si el video ya estuviera montado.

    Se hace DESPUES de que callouts corra de verdad: asi las unidades de render
    quedan al dia y lo que ensucie despues una captura se ve limpio en la
    cascada, sin el ruido de un paso que nunca se ejecuto.
    """
    from nucleo.estado import Estado

    estado = Estado(proyecto)
    trabajo = proyecto.ruta_trabajo("render")
    os.makedirs(os.path.join(trabajo, "clips"), exist_ok=True)
    for escena in ESCENAS:
        with open(os.path.join(trabajo, "clips", f"{escena['id']}.mp4"), "wb") as fh:
            fh.write(b"clip de prueba")
    with open(os.path.join(trabajo, "video.mp4"), "wb") as fh:
        fh.write(b"video de prueba")
    unidades = {uid: {"clip": f"clips/{uid.split(':')[-1]}.mp4"}
                for uid in estado.unidades_declaradas("render")}
    estado.completar("render", {"mp4": "video.mp4", "duracion": 11.0, "fps": 30,
                                "resolucion": [1920, 1080],
                                "resumen": "semilla de render"}, unidades)
    return estado.unidades_obsoletas("render")


def prueba_almacen(proyecto):
    from nucleo import capturas

    seccion("almacen de capturas")
    almacen = capturas.Almacen(proyecto)
    almacen.limpiar()

    primera = almacen.crear("callouts", "S001", png_de_prueba(),
                            trazos=[{"color": "#d4785a", "grosor": 4,
                                     "puntos": [{"x": 0.8, "y": 0.2},
                                                {"x": 0.9, "y": 0.3}]}],
                            comentario="el rotulo pisa la grua",
                            t_video=4.4, t_escena=4.4)
    igual(primera["id"], "cap_0001", "la primera captura es cap_0001")
    igual(primera["unidad"], "escena:S001", "la captura apunta a su unidad")
    ok(os.path.exists(almacen.ruta_imagen(primera)), "el PNG queda en disco")

    segunda = almacen.crear("callouts", "S001", png_de_prueba((20, 20, 20)),
                            comentario="y ademas se sale de cuadro",
                            t_video=1.2, t_escena=1.2)
    igual(segunda["id"], "cap_0002", "la segunda es cap_0002")

    fallos = 0
    for caso, argumentos in (
            ("paso sin reproductor", ("guion", "S001", png_de_prueba())),
            ("no es un png", ("callouts", "S001", b"esto no es un png")),
            ("escena invalida", ("callouts", "../fuera", png_de_prueba()))):
        try:
            almacen.crear(*argumentos, comentario="x", t_escena=1.0)
        except capturas.ErrorCaptura:
            fallos += 1
        else:
            ok(False, f"deberia haber rechazado: {caso}")
    igual(fallos, 3, "rechaza paso, formato y escena invalidos")

    try:
        almacen.crear("callouts", "S001", png_de_prueba(), comentario="",
                      t_escena=1.0)
        ok(False, "deberia rechazar una captura sin comentario ni trazos")
    except capturas.ErrorCaptura:
        ok(True, "una captura que no dice nada se rechaza")

    listadas = almacen.listar(paso="callouts", escena="S001")
    igual(len(listadas), 2, "lista las dos capturas de la escena")
    igual(len(almacen.listar(escena="S002")), 0, "no mezcla escenas")

    instruccion = capturas.instruccion_de(listadas)
    ok(instruccion.index("1,2 s") < instruccion.index("4,4 s"),
       "las capturas se ordenan por instante, no por orden de llegada")
    ok("el rotulo pisa la grua" in instruccion, "el comentario va literal")
    ok(instruccion.count("Nota del revisor") == 2,
       "las dos capturas caben en UNA sola instruccion")

    borrada = almacen.borrar(segunda["id"])
    ok(borrada is not None and not os.path.exists(almacen.ruta_imagen(segunda)),
       "borrar quita la ficha y el PNG")
    ok(almacen.borrar("cap_9999") is None, "borrar lo que no existe no revienta")
    almacen.limpiar()


def prueba_aplicacion_render(proyecto):
    """Una captura de render toca la unidad de render, y solo esa."""
    from nucleo import capturas
    from nucleo.estado import Estado

    seccion("aplicar: una captura invalida su unidad, nunca el paso")
    estado = Estado(proyecto)
    almacen = capturas.Almacen(proyecto)
    ficha = almacen.crear("render", "S002", png_de_prueba(),
                          comentario="el corte entra tarde", t_video=7.5)

    antes_arriba = set(estado.unidades_obsoletas("callouts"))
    grupos = capturas.aplicar(estado, [ficha])
    igual(len(grupos), 1, "un grupo por escena y paso")
    igual(grupos[0]["unidad"], "escena:S002", "toca la unidad de la escena")
    ok("escena:S002" in estado.unidades_obsoletas("render"),
       "la escena queda obsoleta en render")
    igual(sorted(estado.params("render").get("unidades", {})), ["escena:S002"],
          "y es la unica escena que entra en los params del paso")
    igual(set(estado.unidades_obsoletas("callouts")), antes_arriba,
          "el paso de arriba no se entera: la cascada va hacia abajo")
    nota = estado.params("render")["unidades"]["escena:S002"]["feedback"][-1]
    ok("el corte entra tarde" in nota["texto"], "el comentario llega a los params")
    igual(nota["origen"], "captura", "la nota queda marcada como de captura")
    almacen.limpiar()


# ---------------------------------------------------------------------- HTTP

class Cliente:
    def __init__(self, base):
        self.base = base.rstrip("/")
        self.sesion = requests.Session()

    def pedir(self, metodo, ruta, **extra):
        respuesta = self.sesion.request(metodo, self.base + ruta,
                                        timeout=extra.pop("timeout", 300), **extra)
        try:
            return respuesta, respuesta.json()
        except ValueError:
            return respuesta, None

    def get(self, ruta, **extra):
        return self.pedir("GET", ruta, **extra)

    def post(self, ruta, cuerpo=None, **extra):
        return self.pedir("POST", ruta, json=cuerpo, **extra)

    def put(self, ruta, cuerpo=None, **extra):
        return self.pedir("PUT", ruta, json=cuerpo, **extra)

    def delete(self, ruta, **extra):
        return self.pedir("DELETE", ruta, **extra)


def puerto_libre():
    with socket.socket() as sonda:
        sonda.bind(("127.0.0.1", 0))
        return sonda.getsockname()[1]


def arrancar(puerto, carpeta):
    entorno = dict(os.environ)
    entorno["PYTHONIOENCODING"] = "utf-8"
    proceso = subprocess.Popen(
        [PYTHON, APP, "--puerto", str(puerto), "--proyectos", carpeta],
        cwd=RAIZ_ESTUDIO, env=entorno, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    base = f"http://127.0.0.1:{puerto}"
    limite = time.time() + 90
    while time.time() < limite:
        if proceso.poll() is not None:
            raise RuntimeError("el servidor murio al arrancar:\n"
                               + (proceso.stdout.read() if proceso.stdout else ""))
        try:
            if requests.get(base + "/api/salud", timeout=2).status_code == 200:
                return proceso, base
        except requests.RequestException:
            time.sleep(0.3)
    proceso.kill()
    raise RuntimeError("el servidor no respondio a /api/salud")


def esperar_trabajo(cliente, tid, limite=600):
    fin = time.time() + limite
    while time.time() < fin:
        respuesta, ficha = cliente.get(f"/api/trabajos/{tid}")
        if respuesta.status_code != 200:
            return {"estado": "desconocido"}
        if ficha["estado"] in ("listo", "error", "cancelado"):
            return ficha
        time.sleep(0.5)
    return {"estado": "tiempo agotado"}


def subtitulos_de(proyecto, escena="S001"):
    """Los trozos de subtitulo que el paso 7 dibujo, con su hora."""
    from nucleo.proyecto import leer_json

    ruta = os.path.join(proyecto.ruta_paso("callouts"), "movimiento",
                        f"{escena}.ficha.json")
    ficha = leer_json(ruta, {}) or {}
    return [(e.get("texto"), e.get("desde"), e.get("hasta"))
            for e in (ficha.get("elementos") or [])
            if e.get("tipo") == "subtitulo"]


def prueba_http(cliente, proyecto):
    from pasos import p7_callouts as p7

    pid = proyecto.id
    seccion("HTTP: coste")
    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/coste")
    igual(respuesta.status_code, 200, "GET /coste responde 200")
    ok(ficha["eventos"] >= 4, "el servicio ve los eventos ya anotados")
    ok(set(ficha["proveedores"]) >= {"openai", "tts", "claude_cli"},
       "estan los tres proveedores")
    ok(ficha["instrumentacion"]["enganchado"],
       "el servicio arranca con la instrumentacion puesta")
    igual(ficha["instrumentacion"]["ausente"], [],
          "y sin huecos en el enganche")

    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/coste/por-paso")
    igual(respuesta.status_code, 200, "GET /coste/por-paso responde 200")
    ok(any(f["paso"] == "assets" and f["total_usd"] > 0 for f in ficha["pasos"]),
       "el desglose por paso carga el gasto en assets")

    respuesta, ficha = cliente.get(
        f"/api/proyectos/{pid}/coste/eventos?proveedor=openai")
    igual(respuesta.status_code, 200, "GET /coste/eventos responde 200")
    ok(all(e["proveedor"] == "openai" for e in ficha["eventos"]),
       "el filtro por proveedor llega al endpoint")
    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/coste/eventos?proveedor=nada")
    igual(respuesta.status_code, 400, "un proveedor inventado da 400")

    respuesta, ficha = cliente.get("/api/coste/global")
    igual(respuesta.status_code, 200, "GET /api/coste/global responde 200")
    ok(any(p["proyecto"] == pid for p in ficha["proyectos"]),
       "el global incluye este proyecto")

    respuesta, ficha = cliente.get("/api/coste/tarifas")
    ok(ficha["usd_por_caracter"] is None,
       "la tarifa por caracter sigue vacia, como debe")
    respuesta, ficha = cliente.put("/api/coste/tarifas",
                                   {"usd_por_caracter": 0.00003})
    igual(ficha["usd_por_caracter"], 3e-05, "se puede rellenar por API")
    cliente.put("/api/coste/tarifas", {"usd_por_caracter": None})

    respuesta, ficha = cliente.put(f"/api/proyectos/{pid}/coste/presupuesto",
                                   {"usd": 5.0})
    igual(ficha["presupuesto_usd"], 5.0, "el presupuesto se fija por API")
    ok(ficha["aviso_presupuesto"] is False, "y con 5 USD no hay aviso")

    with cliente.sesion.get(f"{cliente.base}/api/proyectos/{pid}/coste/flujo",
                            stream=True, timeout=20) as flujo:
        igual(flujo.status_code, 200, "el SSE de coste responde 200")
        recibido = ""
        for trozo in flujo.iter_lines(decode_unicode=True):
            recibido += (trozo or "") + "\n"
            if "event: coste" in recibido and "data:" in recibido:
                break
        ok("event: coste" in recibido, "y empuja el coste al conectarse")

    seccion("HTTP: se ejecuta callouts de verdad")
    respuesta, ficha = cliente.post(
        f"/api/proyectos/{pid}/pasos/callouts/ejecutar",
        {"params": {"previsualizar": False}})
    igual(respuesta.status_code, 202, "callouts arranca")
    final = esperar_trabajo(cliente, ficha["trabajo_id"])
    igual(final["estado"], "listo", f"callouts termina bien: {final.get('error')}")
    subs_antes = subtitulos_de(proyecto)
    ok(subs_antes, f"el subtitulo se dibujo ({len(subs_antes)} trozos)")
    igual(sembrar_render(proyecto), [],
          "con render sellado no queda ninguna unidad sucia aguas abajo")

    seccion("HTTP: capturas")
    respuesta, ficha = cliente.get(
        f"/api/proyectos/{pid}/capturas/contexto?paso=callouts&t_video=4.4")
    igual(respuesta.status_code, 200, "GET /capturas/contexto responde 200")
    igual(ficha["escena"], "S001", "situa el segundo 4,4 en la escena S001")
    igual(ficha["t_escena"], 4.4, "y calcula el instante dentro del plano")
    ok(abs(ficha["fraccion"] - 4.4 / 6.0) < 0.01, "y la fraccion del recorrido")
    ok("zoom al" in ficha["frase"], f"la frase lleva el zoom: {ficha['frase']}")
    ok(ficha["hyperframe"].startswith(f"/a/{pid}/"), "da la URL del hyperframe")
    ok(ficha["capa"].endswith(".svg"), "y la de la capa vectorial")
    igual(len(ficha["ventana"]), 4, "y la ventana exacta de ese instante")

    respuesta, video = cliente.get(
        f"/api/proyectos/{pid}/capturas/contexto?paso=render&t_video=7.5")
    igual(respuesta.status_code, 200, "el contexto del paso 8 responde 200")
    igual(video["escena"], "S002", "situa el segundo 7,5 en S002")
    igual(video["t_escena"], 1.5, "y el instante dentro del plano")
    ok(video["mp4"].endswith("video.mp4"), "da la URL del MP4 que se esta viendo")
    ok(video["clip"].endswith("S002.mp4"), "y la del clip de ese plano")
    igual(video["fps"], 30, "con los fps con los que se monto")

    # El trazo se marca sobre lo que el revisor VE, o sea en coordenadas de
    # pantalla ya normalizadas (0..1). Antes se derivaba de la caja del rotulo
    # colocado, convertida a la ventana de ese instante; con los rotulos
    # retirados no hay caja de la que partir, asi que se marca una zona
    # cualquiera del cuadro -- que es lo que hace un revisor de verdad.
    mov = p7.movimientos_de(proyecto)["S001"]
    ok(p7.ventana_en(mov, ficha["fraccion"], p7.TAMANO, 16 / 9),
       "la ventana del instante se sigue calculando: es lo que sitúa el trazo")
    trazos = [{"color": "#d4785a", "grosor": 6,
               "puntos": [{"x": 0.30, "y": 0.35}, {"x": 0.62, "y": 0.58}]}]

    import base64
    respuesta, ficha = cliente.post(f"/api/proyectos/{pid}/capturas", {
        "paso": "callouts", "t_video": 4.4, "trazos": trazos,
        "comentario": "la grua sale borrosa cuando el zoom acaba de entrar",
        "imagen_b64": base64.b64encode(png_de_prueba()).decode("ascii")})
    igual(respuesta.status_code, 201, f"POST /capturas responde 201: {ficha}")
    captura = ficha["captura"]
    igual(captura["escena"], "S001", "la escena se deduce del instante")
    igual(captura["t_escena"], 4.4, "guarda el instante dentro del plano")
    igual(captura["t_video"], 4.4, "y el instante del video")
    ok(captura["url"].startswith(f"/a/{pid}/capturas/"), "y sirve el PNG")

    ficheros = {"imagen": ("cap.png", png_de_prueba((10, 40, 10)), "image/png")}
    respuesta, ficha = cliente.pedir(
        "POST", f"/api/proyectos/{pid}/capturas", files=ficheros,
        data={"paso": "callouts", "escena": "S001", "t_escena": "1.0",
              "comentario": "y el texto entra tarde",
              "trazos": json.dumps([{"puntos": [{"x": 0.2, "y": 0.2}]}])})
    igual(respuesta.status_code, 201, f"tambien acepta multipart: {ficha}")
    segunda = ficha["captura"]["id"]

    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/capturas?pendientes=1")
    igual(ficha["total"], 2, "las dos capturas estan pendientes")

    respuesta, ficha = cliente.delete(f"/api/proyectos/{pid}/capturas/{segunda}")
    igual(respuesta.status_code, 200, "DELETE /capturas/{cid} responde 200")
    respuesta, _ = cliente.delete(f"/api/proyectos/{pid}/capturas/cap_9999")
    igual(respuesta.status_code, 404, "borrar una captura inexistente da 404")

    respuesta, mala = cliente.post(f"/api/proyectos/{pid}/capturas", {
        "paso": "guion", "escena": "S001", "t_escena": 1.0, "comentario": "x",
        "imagen_b64": base64.b64encode(png_de_prueba()).decode("ascii")})
    igual(respuesta.status_code, 400, "una captura de un paso sin reproductor da 400")

    seccion("HTTP: aplicar la captura anota la zona, y el subtitulo NO se mueve")
    respuesta, ficha = cliente.post(f"/api/proyectos/{pid}/capturas/aplicar",
                                    {"modo": "directo"})
    igual(respuesta.status_code, 202, f"POST /capturas/aplicar responde 202: {ficha}")
    igual(ficha["paso"], "callouts", "aplica sobre callouts")
    igual(ficha["unidades"], ["escena:S001"], "y solo sobre la escena de la captura")
    ok(ficha["grupos"][0]["zonas"], "la captura dejo zonas que evitar en el plano")
    igual(ficha["aguas_abajo"].get("render"), ["escena:S001"],
          "la misma escena queda obsoleta aguas abajo, y solo esa")

    final = esperar_trabajo(cliente, ficha["trabajo_id"])
    igual(final["estado"], "listo", f"la regeneracion termina bien: {final.get('error')}")

    # UN SUBTITULO NO ESQUIVA NADA, y eso es lo que cambio el 22-08. Cuando lo
    # que iba encima del plano era un ROTULO, marcar una zona en la captura lo
    # mandaba a otro hueco: flotaba, asi que se podia mover. Un subtitulo vive en
    # la banda de abajo, la misma en todo el video, y moverlo seria justo el
    # salto que la banda existe para evitar.
    #
    # La zona se sigue anotando: es feedback sobre la IMAGEN, y va a la unidad
    # para que quien regenere ese plano lo sepa. Lo que ya no hace es recolocar.
    subs_despues = subtitulos_de(proyecto)
    igual(subs_despues, subs_antes,
          "el subtitulo se queda donde estaba: no flota, asi que no hay nada "
          "que esquivar")

    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/capturas")
    ok(ficha["capturas"][0]["aplicada"], "la captura queda marcada como aplicada")
    ok(ficha["capturas"][0]["trabajo"], "con el trabajo que la aplico")

    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/bitacora?limite=50")
    eventos = [e["evento"] for e in ficha["eventos"]]
    ok("captura_tomada" in eventos and "captura_aplicada" in eventos,
       "la bitacora recoge la captura y su aplicacion")
    anotada = [e for e in ficha["eventos"] if e["evento"] == "captura_aplicada"][-1]
    ok(anotada["datos"]["imagenes"], "y guarda con que imagen se pidio")

    respuesta, ficha = cliente.post(f"/api/proyectos/{pid}/capturas/aplicar", {})
    igual(respuesta.status_code, 409, "sin capturas pendientes da 409")


# -------------------------------------------------------------- modo agente

def prueba_agente(carpeta, proyecto):
    """El camino 'agente' entero, con el CLI sustituido por un doble.

    Se prueba en este proceso y con el servicio ya parado: lo que interesa es
    que el trabajo llame al CLI con --output-format json, apunte sus tokens al
    medidor y despues rehaga la unidad, no gastar tokens de verdad.
    """
    import shutil as shutil_real
    import subprocess as subprocess_real

    import app
    from nucleo import capturas, coste

    seccion("modo agente: consulta al CLI y despues rehace la unidad")
    app.fijar_raiz_proyectos(carpeta)
    ctx = app.contexto(proyecto.id)
    almacen = capturas.Almacen(proyecto)
    ficha = almacen.crear("callouts", "S002", png_de_prueba(),
                          comentario="este plano no se entiende, replantealo",
                          t_escena=1.0)
    grupos = capturas.aplicar(ctx.estado, [ficha], modo="agente")
    igual(len(grupos), 1, "la captura se traduce a un grupo")

    sobre = {"result": "he cambiado el rotulo de S002", "duration_ms": 8000,
             "total_cost_usd": 0.42, "model": "sonnet",
             "usage": {"input_tokens": 5000, "output_tokens": 800,
                       "cache_creation_input_tokens": 1000,
                       "cache_read_input_tokens": 40000}}
    visto = {}

    proceso_falso = FalsoProceso(sobre)

    def falso_popen(orden, **extra):
        visto["orden"] = orden
        visto["entorno"] = extra.get("env") or {}
        return proceso_falso

    def comunicar(entrada=None, timeout=None):
        visto["instruccion"] = (entrada or b"").decode("utf-8")
        visto["timeout"] = timeout
        return proceso_falso.stdout, proceso_falso.stderr

    proceso_falso.communicate = comunicar

    medidor = coste.Medidor(proyecto)
    antes = len(medidor.eventos())
    original_popen, original_which = subprocess_real.Popen, shutil_real.which
    subprocess_real.Popen = falso_popen
    shutil_real.which = lambda nombre: r"C:\falso\claude.cmd"
    try:
        resultado = app._correr_capturas_agente(
            lambda *a, **k: None, ctx, grupos, "callouts", ["escena:S002"],
            ajuste={"modelo": "opus", "esfuerzo": "medium"})
    finally:
        subprocess_real.Popen = original_popen
        shutil_real.which = original_which

    # el ajuste llega por invocacion, no por params del paso: mover el
    # desplegable no puede dejar obsoleto el video entero
    ok("opus" in visto["orden"] and "medium" in visto["orden"],
       "el modelo y el esfuerzo elegidos llegan a la orden del CLI")
    ok(visto.get("timeout") and visto["timeout"] > 1800,
       f"y el plazo escala con el esfuerzo: {visto.get('timeout')} s "
       f"(base 1800 s con esfuerzo bajo)")

    ok("--output-format" in visto["orden"] and "json" in visto["orden"],
       "el CLI se invoca con --output-format json")
    # el mismo trato que el paso de guion: sin --effort el CLI razona durante
    # minutos (371 s frente a 70 s medidos), y los MCP del usuario no pintan
    # nada aqui. Se comprueba porque es justo lo que se olvido en este camino.
    ok("--effort" in visto["orden"], "y con --effort explicito, como el guion")
    ok("--strict-mcp-config" in visto["orden"],
       "y con --strict-mcp-config, para no levantar los MCP del usuario")
    ok("CLAUDE_EFFORT" not in visto["entorno"]
       and "MAX_THINKING_TOKENS" not in visto["entorno"],
       "y con el entorno limpio de variables de razonamiento")
    ok("este plano no se entiende" in visto["instruccion"],
       "la instruccion lleva el comentario del revisor")
    ok("1,0 s del plano" in visto["instruccion"],
       f"y el instante: {visto['instruccion'][:0] or ''}"
       + [l for l in visto["instruccion"].splitlines() if "s del plano" in l][0])
    ok(resultado.get("version"), "la unidad se rehace despues del agente")
    igual(resultado["agente"], sobre["result"], "y devuelve lo que dijo el agente")

    eventos = medidor.eventos()[antes:]
    igual(len(eventos), 1, "el agente deja un evento de coste")
    igual(eventos[0]["proveedor"], "claude_cli", "medido como claude_cli")
    igual(eventos[0]["paso"], "callouts", "cargado al paso de la captura")
    igual(eventos[0]["tokens"]["cache"], 41000, "con la cache sumada aparte")
    ok(eventos[0]["usd"] is None, "y sin dolares, que van con la suscripcion")
    ok(medidor.total()["proveedores"]["claude_cli"]["tokens"]["total"] > 0,
       "los tokens del agente entran en el total de tokens")


# ------------------------------------------------------------------ principal

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conservar", action="store_true")
    argumentos = parser.parse_args()

    carpeta = tempfile.mkdtemp(prefix="estudio_coste_")
    # el agregado global de verdad no se toca: aqui se gasta dinero de mentira
    os.environ["ESTUDIO_COSTE_GLOBAL"] = os.path.join(carpeta, "coste_global.jsonl")
    # NI EL HISTORICO DE TIEMPOS, por lo mismo. Desde que p6, p7 y p8 anotan
    # cuanto tardan, esta prueba metia tomas de DOS planos de 4 px en el
    # historico real: con ellas dentro, la barra de un video de verdad
    # prometeria una fraccion del tiempo que va a tardar.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(carpeta, "estadisticas.json")
    # ni la tabla de tarifas: la prueba rellena el precio por caracter de
    # Cartesia para comprobar que entra en vigor, y si reventase entre el
    # relleno y el vaciado dejaria el medidor sumando un importe inventado
    tarifas_prueba = os.path.join(carpeta, "tarifas.json")
    shutil.copyfile(os.path.join(RAIZ_ESTUDIO, "tarifas.json"), tarifas_prueba)
    # La copia arranca SIN precio por caracter, pase lo que pase en la de verdad.
    # Media prueba mide justo el camino de "sin tarifa" -> se rellena -> entra en
    # vigor, y heredar el numero real hacia que esas comprobaciones fallaran el
    # dia que alguien lo rellenase, que es el dia en que todo va bien.
    with open(tarifas_prueba, "r", encoding="utf-8") as fh:
        _tabla = json.load(fh)
    _tabla.setdefault("tts", {})["usd_por_caracter"] = None
    with open(tarifas_prueba, "w", encoding="utf-8") as fh:
        json.dump(_tabla, fh, ensure_ascii=False, indent=2)
    os.environ["ESTUDIO_TARIFAS"] = tarifas_prueba
    print(f"\nPRUEBA DE COSTE Y CAPTURAS\n  carpeta: {carpeta}")
    servidor = None
    try:
        proyecto = sembrar(carpeta)
        print(f"  proyecto: {proyecto.id}")
        prueba_medidor(proyecto)
        prueba_instrumentacion(proyecto)
        prueba_geometria()
        prueba_almacen(proyecto)
        prueba_aplicacion_render(proyecto)

        puerto = puerto_libre()
        servidor, base = arrancar(puerto, carpeta)
        print(f"\n  servicio en {base}")
        prueba_http(Cliente(base), proyecto)
        # el servicio se para antes: el modo agente vuelve a versionar el paso
        # desde este proceso y dos duenos escribiendo estado.json es otra prueba
        servidor.terminate()
        servidor.wait(timeout=15)
        servidor = None
        prueba_agente(carpeta, proyecto)
    finally:
        if servidor is not None:
            servidor.terminate()
            try:
                servidor.wait(timeout=15)
            except subprocess.TimeoutExpired:
                servidor.kill()
        if argumentos.conservar:
            print(f"\n  carpeta conservada en {carpeta}")
        else:
            shutil.rmtree(carpeta, ignore_errors=True)

    print(f"\n  {_ok} comprobaciones correctas, {len(_fallos)} fallos")
    for fallo in _fallos:
        print(f"    - {fallo}")
    return 1 if _fallos else 0


if __name__ == "__main__":
    sys.exit(main())
