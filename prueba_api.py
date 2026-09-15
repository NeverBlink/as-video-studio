"""
Prueba del servicio HTTP del Estudio.

Arranca app.py en un puerto libre contra una carpeta de proyectos temporal,
ejerce los endpoints principales y comprueba codigos y formas de respuesta.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\prueba_api.py

Corre con ESTUDIO_SIMULAR=1: la sintesis de voz no llama a Cartesia, asi que la
prueba ejercita el camino real de ejecutar -> trabajo -> SSE -> version sin
gastar un centimo ni depender de la red. Los pasos que llaman al CLI de Claude
(guion, revision de audio) se siembran en disco con el nucleo, igual que hacen
las pruebas de los pasos: lo que se prueba aqui es la API, no el pipeline.

Con --conservar no borra la carpeta temporal (util para mirar que quedo).
"""
import argparse
import ast
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

RAIZ_ESTUDIO = os.path.dirname(os.path.abspath(__file__))
if RAIZ_ESTUDIO not in sys.path:
    sys.path.insert(0, RAIZ_ESTUDIO)

import requests  # noqa: E402

PYTHON = sys.executable
APP = os.path.join(RAIZ_ESTUDIO, "app.py")

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


# --------------------------------------------------------------------- cliente

class Cliente:
    """requests con la base del servidor puesta y json ya decodificado."""

    def __init__(self, base, carpeta=""):
        self.base = base.rstrip("/")
        self.carpeta = carpeta
        self.sesion = requests.Session()

    def pedir(self, metodo, ruta, **extra):
        respuesta = self.sesion.request(metodo, self.base + ruta,
                                        timeout=extra.pop("timeout", 120), **extra)
        try:
            datos = respuesta.json()
        except ValueError:
            datos = None
        return respuesta, datos

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
    """Lanza el servidor y espera a que /api/salud conteste."""
    entorno = dict(os.environ)
    entorno["ESTUDIO_SIMULAR"] = "1"
    entorno["PYTHONIOENCODING"] = "utf-8"
    # los presets del canal tambien van a la carpeta temporal: sin esto la
    # prueba escribia sus presets de mentira en el presets.json del canal real
    entorno["ESTUDIO_PRESETS"] = os.path.join(carpeta, "presets.json")
    entorno["ESTUDIO_BANCO_PRESETS"] = os.path.join(carpeta, "banco_presets")
    # Y las CLAVES y las RECETAS, por el mismo motivo y con mas razon: sin esto
    # la prueba escribiria claves de mentira encima de las de verdad, y la
    # primera vez que corriera dejaria al Estudio sin poder generar nada.
    entorno["ESTUDIO_SECRETOS"] = os.path.join(carpeta, "secretos")
    entorno["ESTUDIO_RECETAS"] = os.path.join(carpeta, "recetas.json")
    # Y LOS AJUSTES: la guia de inicio se marca como vista desde aqui, y sin
    # esto la marca acabaria en el ajustes.json de verdad.
    entorno["ESTUDIO_AJUSTES"] = os.path.join(carpeta, "ajustes.json")
    # Y EL HISTORICO DE TIEMPOS, que ademas es el que mas dano hacia: el
    # historico guarda 30 muestras por paso, y esta prueba escribe una tanda de
    # tomas SIMULADAS en castellano cada vez que corre. Con eso dentro, la unica
    # toma real en ingles que habia --la que hace que `cadencia` deje de usar la
    # tabla escrita y use lo medido-- se caia por antiguedad. O sea que correr
    # las pruebas BORRABA lo aprendido de las voces del canal.
    entorno["ESTUDIO_ESTADISTICAS"] = os.path.join(carpeta, "estadisticas.json")
    os.makedirs(entorno["ESTUDIO_SECRETOS"], exist_ok=True)
    proceso = subprocess.Popen(
        [PYTHON, APP, "--puerto", str(puerto), "--proyectos", carpeta],
        cwd=RAIZ_ESTUDIO, env=entorno,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace")
    base = f"http://127.0.0.1:{puerto}"
    limite = time.time() + 90
    while time.time() < limite:
        if proceso.poll() is not None:
            salida = proceso.stdout.read() if proceso.stdout else ""
            raise RuntimeError(f"el servidor murio al arrancar:\n{salida}")
        try:
            respuesta = requests.get(base + "/api/salud", timeout=2)
            if respuesta.status_code == 200:
                return proceso, base
        except requests.RequestException:
            time.sleep(0.3)
    proceso.kill()
    raise RuntimeError("el servidor no respondio a /api/salud en 90 s")


def parar(proceso):
    if proceso.poll() is None:
        proceso.terminate()
        try:
            proceso.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proceso.kill()


# --------------------------------------------------------------------- semilla

BLOQUES = [{"id": f"B{n:03d}",
            "texto": (f"Bloque numero {n} de la narracion de prueba. "
                      "Aqui se cuenta un hecho con nombres, fechas y una cifra "
                      "concreta para que el locutor tenga material que leer.")}
           for n in range(1, 41)]


def sembrar(raiz_proyecto):
    """Deja ingesta, brief y guion versionados, como si ya se hubieran corrido.

    Se usa el nucleo directamente, no la API: ejecutar el guion de verdad
    llamaria al CLI de Claude, que ni es gratis ni es lo que prueba este fichero.
    """
    from nucleo.estado import Estado
    from nucleo.proyecto import Proyecto, escribir_json

    proyecto = Proyecto(raiz_proyecto)
    estado = Estado(proyecto)

    transcript = [{"t_in": n * 3.0, "t_out": n * 3.0 + 2.8,
                   "texto": f"linea {n} del transcript de origen"}
                  for n in range(1, 60)]
    salidas_ingesta = {
        "transcript": transcript,
        "video": "origen.webm",
        "video_externo": False,
        "metadatos": {"titulo": "Video de prueba", "palabras_transcript": 420,
                      "idioma_transcript": "es", "duracion_s": 180.0},
        "resumen": "semilla de prueba",
    }
    escribir_json(os.path.join(proyecto.ruta_trabajo("ingesta"), "ingesta.json"),
                  salidas_ingesta)
    estado.set_params("ingesta", {"url": "https://ejemplo/prueba"})
    estado.completar("ingesta", salidas_ingesta)

    salidas_brief = {"tema": "prueba de api", "duracion_s": 90,
                     "resumen": "brief de prueba"}
    escribir_json(os.path.join(proyecto.ruta_trabajo("brief"), "brief.json"),
                  salidas_brief)
    estado.set_params("brief", {"duracion_s": 90, "idioma": "es"})
    estado.completar("brief", salidas_brief)

    escribir_json(os.path.join(proyecto.ruta_trabajo("guion"), "guion.json"),
                  {"titulo": "Guion de prueba", "guion": BLOQUES})
    estado.set_params("guion", {"idioma": "es", "duracion_s": 90})
    estado.completar("guion", {"guion": "guion.json", "n_bloques": len(BLOQUES),
                               "resumen": f"{len(BLOQUES)} bloques"})
    return proyecto


def esperar_trabajo(cliente, tid, limite=180):
    """Sondea un trabajo hasta que termina; devuelve su ficha final."""
    fin = time.time() + limite
    while time.time() < fin:
        respuesta, ficha = cliente.get(f"/api/trabajos/{tid}")
        if respuesta.status_code != 200:
            return {"estado": "desconocido", "error": f"HTTP {respuesta.status_code}"}
        if ficha["estado"] in ("listo", "error", "cancelado"):
            return ficha
        time.sleep(0.2)
    return {"estado": "colgado", "error": f"seguia corriendo tras {limite} s"}


def leer_sse(base, tid, limite=120):
    """Consume el SSE de un trabajo y devuelve (content_type, eventos)."""
    eventos = []
    tipo = ""
    fin = time.time() + limite
    with requests.get(f"{base}/api/trabajos/{tid}/eventos",
                      stream=True, timeout=(10, limite)) as respuesta:
        tipo = respuesta.headers.get("content-type", "")
        if respuesta.status_code != 200:
            return tipo, eventos
        nombre = None
        for cruda in respuesta.iter_lines(decode_unicode=True):
            if time.time() > fin:
                break
            if cruda is None:
                continue
            linea = cruda.strip()
            if linea.startswith("event:"):
                nombre = linea.split(":", 1)[1].strip()
            elif linea.startswith("data:"):
                cuerpo = linea.split(":", 1)[1].strip()
                try:
                    eventos.append((nombre, json.loads(cuerpo)))
                except ValueError:
                    eventos.append((nombre, cuerpo))
                if nombre == "fin":
                    break
    return tipo, eventos


# ---------------------------------------------------------------------- bloques

def probar_salud_y_proyectos(cliente):
    seccion("SALUD Y PROYECTOS")
    respuesta, datos = cliente.get("/api/salud")
    igual(respuesta.status_code, 200, "/api/salud responde 200")
    ok(datos.get("ok") is True, "/api/salud dice ok")
    igual(len(datos.get("pasos") or []), 8, "salud lista los 8 pasos")
    ok(datos.get("pasos_cargados") is True,
       f"los modulos de pasos se han cargado ({datos.get('error_pasos')})")
    ok(datos.get("simulado") is True, "el servidor corre en modo simulado")

    respuesta, datos = cliente.get("/api/proyectos")
    igual(respuesta.status_code, 200, "GET /api/proyectos responde 200")
    igual(datos.get("proyectos"), [], "la carpeta temporal empieza vacia")

    respuesta, datos = cliente.post("/api/proyectos", {})
    igual(respuesta.status_code, 400, "crear sin nombre da 400")
    ok("error" in (datos or {}), "el 400 trae {'error': ...}")

    respuesta, datos = cliente.post("/api/proyectos", {"nombre": "Prueba API"})
    igual(respuesta.status_code, 201, "crear proyecto da 201")
    pid = (datos.get("proyecto") or {}).get("id")
    igual(pid, "prueba_api", "el id sale de identificador(nombre)")
    igual(len(datos.get("pasos") or []), 8, "la creacion devuelve los 8 pasos")

    respuesta, gemelo = cliente.post("/api/proyectos", {"nombre": "Prueba API"})
    igual(respuesta.status_code, 201, "el segundo proyecto homonimo se crea")
    igual((gemelo.get("proyecto") or {}).get("id"), "prueba_api_2",
          "el id se desambigua solo")

    respuesta, datos = cliente.get("/api/proyectos")
    igual(len(datos.get("proyectos") or []), 2, "ahora hay dos proyectos")

    respuesta, datos = cliente.get("/api/proyectos/no_existe")
    igual(respuesta.status_code, 404, "proyecto inexistente da 404")
    ok("error" in (datos or {}), "el 404 trae {'error': ...}")

    respuesta, datos = cliente.get("/api/proyectos/..%2F..%2Fetc")
    igual(respuesta.status_code, 404, "un id con rutas dentro da 404")
    return pid, (gemelo.get("proyecto") or {}).get("id")


def probar_renombrar(cliente, pid):
    """Cambiar el nombre de un proyecto cambia la ETIQUETA, no la carpeta."""
    seccion("RENOMBRAR UN PROYECTO")
    respuesta, antes = cliente.get(f"/api/proyectos/{pid}")
    nombre_viejo = (antes.get("proyecto") or {}).get("nombre")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}", {})
    igual(respuesta.status_code, 400, "renombrar sin nombre da 400")
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}", {"nombre": "   "})
    igual(respuesta.status_code, 400, "y un nombre en blanco tambien")
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}", {"nombre": "!!! ???"})
    igual(respuesta.status_code, 400,
          "un nombre sin ninguna letra ni cifra se rechaza: seria ilegible en "
          "la lista, y al duplicarlo la copia acabaria en una carpeta "
          "llamada `proyecto`")
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}", {"nombre": "Proyecto"})
    igual(respuesta.status_code, 200,
          "y se comprueba ASI y no con `identificador`, que nunca devuelve "
          "vacio: llamarse «Proyecto» es legitimo y esa guarda lo rechazaria")
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}", {"nombre": "x" * 200})
    igual(respuesta.status_code, 400, "y uno larguisimo, que rompe la fila")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}",
                                   {"nombre": "El oro y la inflación"})
    igual(respuesta.status_code, 200, "renombrar responde 200")
    igual((datos.get("proyecto") or {}).get("nombre"), "El oro y la inflación",
          "y devuelve la ficha con el nombre nuevo")
    igual((datos.get("proyecto") or {}).get("id"), pid,
          "EL ID NO CAMBIA: es la clave de las rutas de estado.json, de las "
          "rutas absolutas del manifiesto, del coste global y de lo que el modo "
          "light se guarda en el navegador")

    respuesta, releido = cliente.get(f"/api/proyectos/{pid}")
    igual((releido.get("proyecto") or {}).get("nombre"), "El oro y la inflación",
          "y se ha escrito de verdad: se relee y sigue puesto")
    ok(nombre_viejo != "El oro y la inflación",
       "(la prueba vale porque el nombre de antes era otro)")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}",
                                   {"nombre": "El oro y la inflación"})
    igual(respuesta.status_code, 200, "renombrar al mismo nombre no falla")
    igual(datos.get("cambiado"), False, "y dice que no ha cambiado nada")

    respuesta, datos = cliente.put("/api/proyectos/no_existe", {"nombre": "X"})
    igual(respuesta.status_code, 404, "renombrar lo que no existe da 404")

    # LA LISTA LO ENSENA. Es donde se lee, y es lo que el lapiz del modo light
    # actualiza sin recargar.
    respuesta, lista = cliente.get("/api/proyectos")
    nombres = {p.get("id"): p.get("nombre") for p in (lista.get("proyectos") or [])}
    igual(nombres.get(pid), "El oro y la inflación",
          "y la lista de proyectos lo ensena ya cambiado")

    # y se deja como estaba, que despues de esto vienen mas pruebas
    cliente.put(f"/api/proyectos/{pid}", {"nombre": nombre_viejo})


def probar_pasos(cliente, pid):
    seccion("GRAFO DE PASOS Y PARAMETROS")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos")
    igual(respuesta.status_code, 200, "GET /pasos responde 200")
    fichas = {p["id"]: p for p in datos["pasos"]}
    igual(len(fichas), 8, "el DAG trae los 8 pasos")
    igual(fichas["ingesta"]["estado"], "pendiente", "ingesta arranca pendiente")
    igual(fichas["voz"]["estado"], "bloqueado", "voz arranca bloqueada")
    igual(fichas["render"]["depende_de"], ["callouts"], "el DAG trae dependencias")
    ok(fichas["assets"]["por_unidades"] is True, "assets trabaja por unidades")
    ok(fichas["ingesta"]["descripcion"], "cada paso se describe a si mismo")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/guion")
    igual(respuesta.status_code, 200, "detalle de un paso responde 200")
    for clave in ("params", "salidas", "unidades", "detalle_unidades",
                  "historico", "versiones_detalle", "estado", "firma"):
        ok(clave in datos, f"el detalle del paso trae '{clave}'")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/inventado")
    igual(respuesta.status_code, 404, "paso inexistente da 404")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/pasos/brief/params",
                                   {"params": {"duracion_s": 90, "idioma": "es"}})
    igual(respuesta.status_code, 200, "PUT params responde 200")
    ok(datos.get("cambiado") is True, "cambiar params mueve la firma")
    igual(datos["params"]["duracion_s"], 90, "los params quedan guardados")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/pasos/brief/params",
                                   {"params": {"duracion_s": 90, "idioma": "es"}})
    ok(datos.get("cambiado") is False, "repetir los mismos params no cambia nada")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/pasos/brief/params",
                                   {"params": "esto no es un objeto"})
    igual(respuesta.status_code, 400, "params que no son objeto dan 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", {})
    igual(respuesta.status_code, 409, "ejecutar un paso bloqueado da 409")
    ok("faltan" in (datos or {}), "el 409 dice que falta por ejecutar")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/inventado/ejecutar", {})
    igual(respuesta.status_code, 404, "ejecutar un paso inexistente da 404")


def probar_ejecucion(cliente, base, pid):
    seccion("EJECUCION, TRABAJOS Y SSE")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/voz")
    igual(datos["estado"], "pendiente", "con el guion sembrado, voz ya no bloquea")

    respuesta, lanzado = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", {})
    igual(respuesta.status_code, 202, "lanzar un paso responde 202")
    tid = lanzado.get("trabajo_id")
    ok(bool(tid), "la respuesta trae trabajo_id")
    igual(lanzado.get("eventos"), f"/api/trabajos/{tid}/eventos",
          "y la URL de eventos SSE")

    respuesta, repetido = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", {})
    igual(respuesta.status_code, 409, "no se puede lanzar dos veces el mismo paso")
    igual(repetido.get("trabajo_id"), tid, "el 409 devuelve el trabajo que ya corre")

    tipo, eventos = leer_sse(base, tid)
    ok("text/event-stream" in tipo, f"el SSE se sirve como event-stream ({tipo})")
    ok(len(eventos) >= 1, "el SSE emite al menos un evento")
    ok(eventos and eventos[-1][0] == "fin", "el SSE cierra con un evento 'fin'")
    if eventos:
        avances = [e[1]["progreso"] for e in eventos if isinstance(e[1], dict)]
        ok(all(b >= a for a, b in zip(avances, avances[1:])),
           f"el progreso del SSE nunca retrocede ({avances})")
        igual(avances[-1], 1.0, "y termina en 1.0")
        ultimo = eventos[-1][1]
        igual(ultimo.get("estado"), "listo", "el trabajo acaba listo")
        for clave in ("id", "progreso", "mensaje", "estado", "resultado"):
            ok(clave in ultimo, f"el evento SSE trae '{clave}'")

    ficha = esperar_trabajo(cliente, tid)
    igual(ficha["estado"], "listo", f"el trabajo termina bien ({ficha.get('error')})")
    resultado = ficha.get("resultado") or {}
    igual(resultado.get("version"), 1, "la ejecucion deja la version 1")
    ok(resultado.get("resumen"), "el resultado trae resumen del paso")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/voz")
    igual(datos["estado"], "listo", "el paso queda listo")
    igual(datos["version_activa"], 1, "con la v1 activa")
    salidas = datos["salidas"]
    ok(salidas.get("archivo"), "las salidas dicen como se llama la pista")
    ok(salidas.get("duracion"), "y cuanto dura")
    return tid, salidas


def probar_versiones(cliente, pid):
    seccion("VERSIONES Y REVERTIR")
    cliente.put(f"/api/proyectos/{pid}/pasos/voz/params",
                {"params": {"preset": "true_crime_tenso"}})
    respuesta, lanzado = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar", {})
    igual(respuesta.status_code, 202, "se puede reejecutar con otros params")
    ficha = esperar_trabajo(cliente, lanzado["trabajo_id"])
    igual(ficha["estado"], "listo", f"la segunda toma sale bien ({ficha.get('error')})")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/voz/versiones")
    igual(respuesta.status_code, 200, "GET versiones responde 200")
    igual(len(datos["versiones"]), 2, "hay dos versiones de voz")
    igual(datos["activa"], 2, "la activa es la ultima")
    ok(all("resumen" in v and "fecha" in v for v in datos["versiones"]),
       "cada version trae fecha y resumen")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/revertir",
                                    {"version": 1})
    igual(respuesta.status_code, 200, "revertir responde 200")
    igual(datos["activa"], 1, "vuelve a estar activa la v1")
    igual(datos["params"].get("preset"), None,
          "revertir restaura tambien los params de esa version")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/revertir",
                                    {"version": 99})
    igual(respuesta.status_code, 404, "revertir a una version inexistente da 404")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/revertir", {})
    igual(respuesta.status_code, 400, "revertir sin version da 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/revertir",
                                    {"version": "tres"})
    igual(respuesta.status_code, 400, "revertir con version no numerica da 400")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/voz/versiones",
                                   params={"detalle": 1})
    ok(all("params" in v for v in datos["versiones"]),
       "con detalle=1 cada version trae sus params")
    # EL MANIFIESTO YA NO VIAJA EN LA RESPUESTA. Desde que vive en su fichero
    # (`pasos/<paso>/_versiones/v<N>.json`), de las unidades solo va el recuento:
    # rehidratarlo aqui serian ~4 MB por version para un endpoint que nadie usa
    # para eso. Se fija por escrito porque es un cambio de contrato publico y sin
    # esta comprobacion nada avisaria de que alguien vuelve a apoyarse en el.
    ok(all("unidades" not in v for v in datos["versiones"]),
       "con detalle=1 NO viaja el manifiesto de unidades")
    ok(all(isinstance(v.get("n_unidades"), int) for v in datos["versiones"]),
       "pero si el recuento, que es lo que se pinta")

    respuesta, ligeras = cliente.get(f"/api/proyectos/{pid}/pasos/voz/versiones")
    ok(all("unidades" in v and "params" not in v for v in ligeras["versiones"]),
       "y sin detalle sigue yendo la ficha ligera, con 'unidades' como numero")
    ok(all(isinstance(v["unidades"], int) for v in ligeras["versiones"]),
       "ese 'unidades' de la ficha ligera es un numero, no el mapa")


def probar_archivos(cliente, pid, salidas):
    seccion("ARCHIVOS DEL PROYECTO")
    ruta = f"/a/{pid}/pasos/voz/v1/{salidas['archivo']}"
    respuesta = cliente.sesion.get(cliente.base + ruta, timeout=60)
    igual(respuesta.status_code, 200, "se sirve el wav de la version activa")
    igual(respuesta.headers.get("content-type"), "audio/wav",
          "con el tipo de contenido correcto")
    igual(respuesta.headers.get("accept-ranges"), "bytes", "anunciando Range")
    entero = len(respuesta.content)
    ok(entero > 0, "el wav no viene vacio")

    respuesta = cliente.sesion.get(cliente.base + ruta, timeout=60,
                                   headers={"Range": "bytes=0-99"})
    igual(respuesta.status_code, 206, "una peticion con Range da 206")
    igual(len(respuesta.content), 100, "y devuelve exactamente los bytes pedidos")
    igual(respuesta.headers.get("content-range"), f"bytes 0-99/{entero}",
          "con la cabecera Content-Range bien puesta")

    respuesta = cliente.sesion.get(cliente.base + ruta, timeout=60,
                                   headers={"Range": f"bytes={entero + 500}-"})
    igual(respuesta.status_code, 416, "un Range fuera del fichero da 416")

    respuesta, datos = cliente.get(f"/a/{pid}/pasos")
    igual(respuesta.status_code, 200, "una carpeta se lista")
    ok("voz" in (datos.get("entradas") or []), "y trae sus entradas")

    respuesta, datos = cliente.get(f"/a/{pid}/no_existe.png")
    igual(respuesta.status_code, 404, "un archivo inexistente da 404")

    # miniaturas: una imagen grande con ?mini=1 baja como JPEG pequeno; lo que
    # no es imagen (el wav) ignora el parametro y baja entero
    from PIL import Image
    import random
    ruidosa = Image.new("RGB", (1536, 1024))
    ruidosa.putdata([(random.randrange(256), random.randrange(256),
                      random.randrange(256)) for _ in range(1536 * 1024)])
    ruta_png = os.path.join(cliente.carpeta, pid, "grande.png")
    ruidosa.save(ruta_png, "PNG")
    original = os.path.getsize(ruta_png)
    respuesta = cliente.sesion.get(f"{cliente.base}/a/{pid}/grande.png?mini=1",
                                   timeout=60)
    igual(respuesta.status_code, 200, "la miniatura responde 200")
    igual(respuesta.headers.get("content-type"), "image/jpeg",
          "y es un JPEG, no el PNG de generacion")
    ok(len(respuesta.content) < original / 10,
       f"y pesa menos de la decima parte ({len(respuesta.content)} de {original})")
    respuesta = cliente.sesion.get(f"{cliente.base}{ruta}?mini=1", timeout=60)
    igual(respuesta.headers.get("content-type"), "audio/wav",
          "un wav con ?mini=1 baja entero: la miniatura es cosa de imagenes")

    for intento, etiqueta in (
            ("..%2F..%2F..%2Fsecrets%2F.env", "escapar con .. codificado"),
            ("..%5C..%5Cwindows%5Cwin.ini", "escapar con barras invertidas"),
            ("C:%2FWindows%2Fwin.ini", "colar una ruta absoluta")):
        respuesta = cliente.sesion.get(f"{cliente.base}/a/{pid}/{intento}",
                                       timeout=30, allow_redirects=False)
        ok(respuesta.status_code in (403, 404),
           f"{etiqueta} se corta ({respuesta.status_code})")


def probar_feedback(cliente, pid):
    seccion("FEEDBACK EN CASCADA")
    ruta = f"/api/proyectos/{pid}/feedback"

    respuesta, datos = cliente.post(ruta, {"texto": "algo"})
    igual(respuesta.status_code, 400, "feedback sin paso da 400")

    respuesta, datos = cliente.post(ruta, {"paso": "inventado", "texto": "algo"})
    igual(respuesta.status_code, 404, "feedback a un paso inexistente da 404")

    respuesta, datos = cliente.post(ruta, {"paso": "guion", "ejecutar": False})
    igual(respuesta.status_code, 400, "feedback sin texto ni trazos da 400")

    respuesta, datos = cliente.post(ruta, {"paso": "guion", "texto": "x",
                                           "modo": "telepatia", "ejecutar": False})
    igual(respuesta.status_code, 400, "un modo desconocido da 400")

    respuesta, datos = cliente.post(ruta, {
        "paso": "guion", "unidad": "B002", "modo": "agente", "ejecutar": False,
        "texto": "este bloque se va por las ramas, ve al grano",
        "trazos": [{"puntos": [{"x": 0.8, "y": 0.15}, {"x": 0.85, "y": 0.2}]}]})
    igual(respuesta.status_code, 202, "el feedback por unidad se acepta")
    igual(datos.get("unidad"), "B002", "y queda apuntado a esa unidad")
    igual(datos["nota"]["modo"], "agente", "conservando el modo pedido")
    ok(datos["nota"]["zonas"], "los trazos se traducen a zonas en texto")
    igual(datos.get("trabajo_id"), None, "con ejecutar=false no lanza nada")
    ok("voz" in (datos.get("aguas_abajo") or {}),
       "la respuesta dice que arrastra a voz")

    respuesta, paso = cliente.get(f"/api/proyectos/{pid}/pasos/guion")
    notas = ((paso["params"].get("unidades") or {}).get("B002") or {}).get("feedback")
    ok(isinstance(notas, list) and len(notas) == 1,
       "la nota queda guardada en los params de la unidad")
    igual(paso["estado"], "obsoleto", "el guion queda obsoleto por el feedback")
    ok("B002" in paso["unidades_obsoletas"], "y la unidad tocada, marcada")

    respuesta, voz = cliente.get(f"/api/proyectos/{pid}/pasos/voz")
    igual(voz["estado"], "obsoleto", "la cascada llega a voz sola")

    respuesta, datos = cliente.post(ruta, {
        "paso": "voz", "texto": "sube un poco el ritmo general", "modo": "directo"})
    igual(respuesta.status_code, 202, "el feedback general se acepta")
    tid = datos.get("trabajo_id")
    ok(bool(tid), "y esta vez si lanza un trabajo")
    ficha = esperar_trabajo(cliente, tid)
    igual(ficha["estado"], "listo", f"el trabajo del feedback acaba ({ficha.get('error')})")

    respuesta, voz = cliente.get(f"/api/proyectos/{pid}/pasos/voz")
    igual(voz["estado"], "listo", "tras aplicarlo, voz vuelve a listo")
    ok(len(voz["params"].get("feedback") or []) == 1,
       "el feedback general vive en los params del paso")


def probar_voz(cliente, pid):
    seccion("VOZ: PRESETS, CATALOGO Y ESCUCHA")
    # Los endpoints globales: los por-proyecto (/voz/presets, /voz/voces) eran
    # alias literales y se retiraron. La interfaz siempre uso estos.
    respuesta, datos = cliente.get("/api/presets")
    igual(respuesta.status_code, 200, "GET presets responde 200")
    ok(len(datos.get("presets") or []) >= 8, "hay presets de estilo")
    ok(all("id" in p and "nombre" in p for p in datos["presets"]),
       "cada preset trae id y nombre")
    ok(datos.get("por_defecto"), "y se dice cual es el de partida")

    respuesta, datos = cliente.get("/api/voces", params={"idioma": "es"})
    igual(respuesta.status_code, 200, "GET voces responde 200")
    ok(isinstance(datos.get("voces"), list) and datos["voces"],
       "el catalogo de voces no viene vacio")
    ok(all("id" in v for v in datos["voces"]), "cada voz trae su id")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/voz/previsualizar",
                                    {"params": {"preset": "documental_sobrio"},
                                     "segundos": 8})
    igual(respuesta.status_code, 202, "previsualizar responde 202")
    tid = datos.get("trabajo_id")
    ok(bool(tid), "y devuelve trabajo_id")
    ficha = esperar_trabajo(cliente, tid)
    igual(ficha["estado"], "listo", f"la escucha se genera ({ficha.get('error')})")
    url = (ficha.get("resultado") or {}).get("url")
    ok(bool(url), "el resultado trae la URL para escuchar")
    if url:
        respuesta = cliente.sesion.get(cliente.base + url, timeout=60)
        igual(respuesta.status_code, 200, "y esa URL sirve el audio")
        igual(respuesta.headers.get("content-type"), "audio/wav",
              "como audio/wav")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/voz/previsualizar",
                                    {"segundos": 900})
    igual(respuesta.status_code, 400, "una duracion absurda da 400")


def probar_bitacora(cliente, pid):
    seccion("BITACORA")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/bitacora")
    igual(respuesta.status_code, 200, "GET bitacora responde 200")
    eventos = datos.get("eventos") or []
    ok(eventos, "la bitacora tiene eventos")
    tipos = {e["evento"] for e in eventos}
    for esperado in ("proyecto_creado", "params_actualizados", "paso_completado",
                     "feedback", "revertido"):
        ok(esperado in tipos, f"la bitacora registra '{esperado}'")
    ok(all({"fecha", "evento", "paso", "unidad", "datos"} <= set(e) for e in eventos),
       "cada evento trae fecha, evento, paso, unidad y datos")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/bitacora",
                                   params={"paso": "voz"})
    ok(all(e["paso"] == "voz" for e in datos["eventos"]), "el filtro por paso funciona")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/bitacora",
                                   params={"paso": "inventado"})
    igual(respuesta.status_code, 404, "filtrar por un paso inexistente da 404")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/bitacora/llm")
    igual(respuesta.status_code, 200, "el resumen para LLM responde 200")
    ok("BITACORA DEL PROYECTO" in (datos.get("texto") or ""),
       "y trae el historial en texto")
    ok(datos.get("lineas", 0) > 5, "con varias lineas")

    respuesta = cliente.sesion.get(
        f"{cliente.base}/api/proyectos/{pid}/bitacora/llm?formato=texto", timeout=60)
    ok(respuesta.headers.get("content-type", "").startswith("text/plain"),
       "en formato=texto se sirve como texto plano")


def probar_presets_canal(cliente):
    seccion("PRESETS DEL CANAL Y SUS FICHEROS")
    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "guion", "nombre": "Prueba API",
        "datos": {"idiomas_salida": ["es"], "duracion_objetivo_s": 300}})
    igual(respuesta.status_code, 200, "guardar un preset de guion responde 200")
    preset_id = (datos.get("preset") or {}).get("id") or ""
    ok(preset_id, "la respuesta trae el id del preset")

    respuesta, datos = cliente.get("/api/presets-canal")
    ok(any(p.get("id") == preset_id
           for p in (datos.get("presets") or {}).get("guion") or []),
       "el preset aparece en la lista de su tipo")

    # el fichero se siembra a mano en la carpeta del preset: este endpoint
    # existe para servir lo que YA vive en banco/presets/<id>/
    carpeta_preset = os.path.join(cliente.carpeta, "banco_presets", preset_id)
    os.makedirs(carpeta_preset, exist_ok=True)
    with open(os.path.join(carpeta_preset, "referencia.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("fotograma de mentira")
    respuesta = cliente.sesion.get(
        f"{cliente.base}/api/presets-canal/{preset_id}/fichero/referencia.txt",
        timeout=30)
    igual(respuesta.status_code, 200, "un fichero del preset se sirve")
    igual(respuesta.text, "fotograma de mentira", "con su contenido intacto")

    respuesta = cliente.sesion.get(
        f"{cliente.base}/api/presets-canal/{preset_id}/fichero/no_existe.png",
        timeout=30)
    igual(respuesta.status_code, 404, "un fichero que no existe da 404")

    for intento, etiqueta in (
            ("..%2F..%2Fpresets.json", "escapar con .. codificado"),
            ("..%5C..%5Cpresets.json", "escapar con barras invertidas"),
            ("C:%2FWindows%2Fwin.ini", "colar una ruta absoluta")):
        respuesta = cliente.sesion.get(
            f"{cliente.base}/api/presets-canal/{preset_id}/fichero/{intento}",
            timeout=30, allow_redirects=False)
        ok(respuesta.status_code in (400, 404),
           f"{etiqueta} se corta ({respuesta.status_code})")

    respuesta, datos = cliente.get(
        "/api/presets-canal/pr_inexistente/fichero/referencia.txt")
    igual(respuesta.status_code, 400, "pedir ficheros de un preset inexistente da 400")


def probar_cartelas_y_transiciones(cliente, pid, raiz_proyecto=None):
    """Las dos pantallas nuevas: cartelas (assets) y transiciones (render)."""
    seccion("CARTELAS, TRANSICIONES Y SONIDO")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/cartelas")
    igual(respuesta.status_code, 200, "el catalogo de cartelas responde 200")
    plantillas = datos.get("plantillas") or []
    ok(len(plantillas) >= 8, f"vienen las plantillas ({len(plantillas)})")
    sin_muestra = [p["id"] for p in plantillas
                   if not str(p.get("svg") or "").startswith("<svg")]
    igual(sin_muestra, [], "cada una trae su muestra DIBUJADA, no una maqueta")
    ok(all(p.get("cuando") and p.get("campos") for p in plantillas),
       "y dice cuando va y que huecos tiene")
    ok(datos.get("todas"), "sin elegir nada, entran todas")

    # guardar un plan valido
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S001": {"plantilla": "tesis",
                          "datos": {"texto": "Y entonces dejo de existir"},
                          "por_que": "la prueba"}}})
    igual(respuesta.status_code, 200, "guardar un plan de cartelas responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/cartelas")
    igual(list(datos.get("plan") or {}), ["S001"], "y queda guardado")

    # una plantilla que no existe se corta AQUI, no al renderizar
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S001": {"plantilla": "no_existe", "datos": {}}}})
    igual(respuesta.status_code, 400, "una plantilla inventada da 400")

    # y un campo obligatorio que falta, tambien: el aviso lleva el id del plano
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S007": {"plantilla": "cifra", "datos": {"label": "sin numero"}}}})
    igual(respuesta.status_code, 400, "una cartela sin campo obligatorio da 400")
    ok("S007" in str(datos), f"y el error dice de que plano habla: {datos}")

    # el texto de mas se RECORTA y se guarda: no es un error, es un aviso
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S001": {"plantilla": "tesis", "datos": {"texto": "x" * 400}}}})
    igual(respuesta.status_code, 200, "un texto largo se guarda recortado")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/cartelas")
    ok(len(datos["plan"]["S001"]["datos"]["texto"]) <= 95,
       "recortado a su tope, no rechazado")

    # LA CARTELA VA POR UNIDAD, no en un param suelto. Es lo que impide que
    # decidir una cartela deje obsoletos los cuarenta y nueve planos: todo lo
    # que no es el bloque `unidades` entra en la firma GLOBAL del paso.
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    params = datos.get("params") or datos
    ok("plan_cartelas" not in params,
       "el plan NO es un param global de assets: eso ensuciaba todo el video")
    unidades = params.get("unidades") or {}
    ok((unidades.get("escena:S001") or {}).get("cartela"),
       f"esta guardada en su unidad: {list(unidades)[:4]}")

    # y guardarla NO se lleva por delante lo que ya hubiera en esa unidad
    cliente.post(f"/api/proyectos/{pid}/feedback", {
        "paso": "assets", "unidad": "escena:S001", "texto": "una nota previa",
        "ejecutar": False})
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S001": {"plantilla": "tesis",
                          "datos": {"texto": "Otra frase"}}}})
    igual(respuesta.status_code, 200, "volver a guardar el plan responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    unidad = ((datos.get("params") or datos).get("unidades") or {}).get("escena:S001") or {}
    ok(unidad.get("feedback"),
       "el feedback de ese plano sigue ahi: guardar la cartela no lo pisa")
    ok((unidad.get("cartela") or {}).get("fondo") in ("negro", "imagen"),
       "y la cartela guarda su fondo")

    # quitar una cartela la quita de verdad
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {"plan": {}})
    igual(respuesta.status_code, 200, "guardar un plan vacio responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/cartelas")
    igual(datos.get("plan"), {}, "y el plano deja de ser cartela")

    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas",
                               {"plantillas": ["cifra", "cita"]})
    igual(respuesta.status_code, 200, "elegir que plantillas entran responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/callouts")
    igual((datos.get("params") or datos).get("plantillas_cartela"),
          ["cifra", "cita"],
          "las plantillas permitidas van con el GRAFISMO, en params de rotulos: "
          "solo limitan lo que puede elegir el agente, asi que no tienen por "
          "que ensuciar una sola imagen")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas",
                               {"plantillas": ["ni_idea"]})
    igual(respuesta.status_code, 400, "una plantilla desconocida da 400")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {})
    igual(respuesta.status_code, 400, "un PUT sin nada que guardar da 400")

    # --- transiciones
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/transiciones")
    igual(respuesta.status_code, 200, "el catalogo de transiciones responde 200")
    lista = datos.get("transiciones") or []
    igual(len(lista), 15, "las catorce de hyperframes mas nuestro fundido")
    sin_glsl = [t["id"] for t in lista if "void main()" not in (t.get("frag") or "")]
    igual(sin_glsl, [], "cada una viaja con SU shader: la pantalla corre el "
                        "mismo GLSL que el render, no una imitacion")
    ok(datos.get("vertices"), "y el vertex shader comun")
    ok("corte" not in (datos.get("por_defecto") or []),
       "'corte' no viaja como transicion: es lo que pasa cuando no hay ninguna")
    acento = datos.get("acento") or {}
    ok(all(len(acento.get(p) or []) == 3 for p in ("acento", "oscuro", "claro")),
       "con los tres colores de acento del video, listos para los uniformes")

    # la seleccion es un param del RENDER, y una mal escrita se corta al guardar
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/pasos/render/params",
                               {"transiciones": ["glitch", "sdf-iris"]})
    igual(respuesta.status_code, 200, "elegir transiciones responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/transiciones")
    ok(not datos.get("todas_de_fabrica"), "y deja de estar en las de fabrica")
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/pasos/render/params",
                                   {"transiciones": ["remolino_loco"]})
    igual(respuesta.status_code, 400,
          "una transicion inventada da 400 al GUARDARLA, no un video sin ella")

    # QUE TRANSICION LE TOCA A CADA PLANO. Viaja resuelta por el motor
    # (`transiciones.resolver`) para que el repaso del montaje pueda correr el
    # shader de verdad en cada corte en vez de adivinar cual toca -- y adivinaria
    # mal en cuanto alguien cambiara la paleta elegida.
    from nucleo.proyecto import Proyecto, escribir_json
    escribir_json(os.path.join(Proyecto(raiz_proyecto).ruta_trabajo("assets"),
                               "plan.json"), {
        "semilla": 7,
        # CON SU NARRACION, que es lo que dice cada plano. No es de adorno en el
        # fixture: es lo unico que permite volver a encontrar el plano de una
        # nota cuando la segmentacion renumera (ver el repaso, mas abajo).
        "escenas": [
            {"id": "S001", "duracion": 4.0, "t_in": 0.0, "t_out": 4.0,
             "transicion": "suave",
             "narracion": "treinta millones de cuentas salieron a la venta"},
            {"id": "S002", "duracion": 4.0, "t_in": 4.0, "t_out": 8.0,
             "transicion": "acento",
             "narracion": "daban de comer a una familia un mes entero"},
            {"id": "S003", "duracion": 4.0, "t_in": 8.0, "t_out": 12.0,
             "transicion": "suave", "sigue_a": "S002",
             "narracion": "y nadie aviso a los clientes hasta mucho despues"},
        ],
    })
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/transiciones")
    reparto = datos.get("reparto") or {}
    igual(sorted(reparto), ["S001", "S002", "S003"],
          "el reparto trae un corte por plano")
    igual(reparto.get("S001", {}).get("tipo"), "corte",
          "el primer plano no encadena: no hay nada de lo que venir")
    igual(reparto.get("S003", {}).get("tipo"), "corte",
          "y una continuacion tampoco: los dos fotogramas son la misma imagen")
    ok(reparto.get("S002", {}).get("tipo") not in (None, "corte"),
       f"el resto si: {reparto.get('S002')}")
    ok(float(reparto.get("S002", {}).get("duracion") or 0) > 0,
       "con su duracion, que es la que el repaso tiene que recorrer")
    ok("shader" not in (reparto.get("S002") or {}),
       "y SIN el GLSL: el frag de cada transicion ya viaja una vez en el "
       "catalogo, repetirlo por plano serian doscientas copias")
    ok(any(x["id"] == reparto["S002"]["tipo"] for x in lista),
       "la que toca esta en el catalogo, asi que la pantalla puede buscar su frag")

    # --- musica y efectos. SOLO lo que no sale a la red: que Jamendo y
    # Freesound sigan vivos no depende de este repo, y una suite que se cae
    # porque una API de fuera tiene un mal dia deja de servir para nada.
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/sonido")
    igual(respuesta.status_code, 200, "el estado del sonido responde 200")
    papeles = datos.get("papeles") or []
    ok(len(papeles) >= 4, f"vienen los papeles de efecto ({len(papeles)})")
    ok(all(p.get("nombre") and p.get("descripcion") for p in papeles),
       "cada papel dice que es y para que")
    ok(datos.get("animos"), "y los animos con los que buscar musica")
    ok("hay_jamendo" in datos and "hay_freesound" in datos,
       "dice si estan las claves, para poder avisar en vez de fallar al pulsar")

    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/sonido", {"activo": False})
    igual(respuesta.status_code, 200, "apagar el sonido responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/sonido")
    igual(datos.get("activo"), False, "y queda apagado")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/sonido",
                               {"activo": True, "lufs": -20})
    igual(respuesta.status_code, 200, "y se vuelve a encender")

    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/sonido",
                               {"musica": {"titulo": "sin id ni descarga"}})
    igual(respuesta.status_code, 400,
          "un tema sin 'id' ni 'descarga' se corta al guardarlo, no al renderizar")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/sonido", {})
    igual(respuesta.status_code, 400, "un PUT sin nada que guardar da 400")
    respuesta, _ = cliente.post(f"/api/proyectos/{pid}/sonido/efectos",
                                {"papeles": ["no_existe"]})
    igual(respuesta.status_code, 400, "un papel de efecto inventado da 400")

    # --- EL VETO DE UN EFECTO (PENDIENTE 19). Se veta lo que se acaba de oir,
    # donde se oye: la pantalla trae cada efecto con su muestra y su ✕, y el
    # veto es del CANAL, no de este video.
    from pasos import sonido as mod_sonido
    guardados = dict(mod_sonido.vetados())
    try:
        laser = {"fuente": "prueba", "id": "laser_api", "titulo": "Laser"}
        respuesta, datos = cliente.post(f"/api/proyectos/{pid}/sonido/vetados",
                                        {"efecto": laser, "papel": "transicion_acento"})
        igual(respuesta.status_code, 200, "vetar un efecto responde 200")
        ok(datos.get("vetado"), "y dice que ha quedado vetado")
        ok(any(v.get("clave") == "prueba_laser_api" for v in datos.get("vetados") or []),
           f"y devuelve la lista del canal: {datos.get('vetados')}")
        respuesta, datos = cliente.get(f"/api/proyectos/{pid}/sonido")
        ok(any(v.get("clave") == "prueba_laser_api" for v in datos.get("vetados") or []),
           "la pantalla de sonido lo trae ya marcado, sin tener que preguntar aparte")
        respuesta, datos = cliente.post(f"/api/proyectos/{pid}/sonido/vetados",
                                        {"clave": "prueba_laser_api", "quitar": True})
        igual(respuesta.status_code, 200, "y se puede levantar")
        ok(datos.get("quitado"), "diciendo que habia algo que levantar")
        respuesta, _ = cliente.post(f"/api/proyectos/{pid}/sonido/vetados", {})
        igual(respuesta.status_code, 400,
              "vetar sin decir que se veta da 400, no un veto vacio")
        respuesta, _ = cliente.get("/api/efectos/no_existe.mp3")
        igual(respuesta.status_code, 404,
              "y pedir una muestra que no esta en el banco da 404")
        respuesta, _ = cliente.get("/api/efectos/..%2F..%2Fapp.py")
        ok(respuesta.status_code in (403, 404),
           f"y no se puede salir del banco por la ruta ({respuesta.status_code})")
    finally:
        mod_sonido._guardar_vetados(guardados)


def probar_motor_del_plan(cliente, pid):
    """CON QUE REGLAS SE CORTO ESTE VIDEO (PENDIENTE 24).

    Las firmas miran los params, asi que cambiar el MOTOR no pone naranja nada.
    No se inventa un estado --eso obligaria a rehacer los renders de todos los
    proyectos cada vez que se toca una regla--: se ensena.
    """
    seccion("EL PLAN DICE CON QUE REGLAS SE CORTO")

    from pasos import p6_assets
    respuesta, ficha = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    igual(respuesta.status_code, 200, "assets responde 200")
    motor = ficha.get("motor")
    if not ok(isinstance(motor, dict), f"assets dice con que motor se corto: {motor}"):
        return
    igual(motor.get("ahora"), p6_assets.MOTOR_PLAN,
          "y con cual hay ahora, que es lo que se compara")
    # El plan de esta suite se corto antes de que existiera el sello, asi que
    # es EL CASO QUE IMPORTA: un video viejo tiene que decirlo. Sin sello se lee
    # como version 1, que es lo correcto -- «no lo se» y «es viejo» son lo mismo
    # aqui, porque lo unico accionable es volver a cortar.
    igual(motor.get("plan"), 1,
          "un plan sin sello se lee como viejo, no como al dia")
    igual(motor.get("al_dia"), False, "asi que se avisa")
    ok(motor.get("cambios"),
       f"y se dice QUE se ha perdido, no un numero: {(motor.get('cambios') or [''])[0][:60]}")
    ok(all(isinstance(t, str) and t for t in motor.get("cambios") or []),
       "cada cambio es una frase que se puede leer")

    ok(all(v in p6_assets.MOTOR_CAMBIOS for v in range(2, p6_assets.MOTOR_PLAN + 1)),
       "cada version del motor dice QUE cambio: un numero suelto no dice si "
       "importa")

    # y el render y los rotulos tambien lo traen: son los que se quedan viejos
    for paso in ("callouts", "render"):
        respuesta, otra = cliente.get(f"/api/proyectos/{pid}/pasos/{paso}")
        ok(isinstance(otra.get("motor"), dict),
           f"{paso} tambien lo trae: es donde se ve el video")


def probar_direccion(cliente, pid):
    """QUE SE VE EN CADA PLANO: la capa que faltaba en el prompt de imagen.

    Va POR UNIDAD, como las cartelas y por lo mismo: escribir la direccion de un
    plano ensucia ESE plano y no los cuarenta y nueve.
    """
    seccion("LA DIRECCION DE LOS PLANOS VA POR UNIDAD")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/direccion")
    igual(respuesta.status_code, 200, "la pantalla de direccion responde 200")
    ok("planos" in datos and "dirigibles" in datos,
       "trae los planos que se pueden dirigir y cuantos son")
    ok(datos.get("palabras_maximas", 0) > 0,
       "y el tope de palabras, que es lo que la hace util")
    planos = datos.get("planos") or []
    if not ok(planos, "hay planos que dirigir"):
        return
    sid = planos[0]["id"]

    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/direccion", {})
    igual(respuesta.status_code, 400, "un PUT sin 'plan' da 400")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/direccion",
                               {"plan": {sid: "dos palabras"}})
    igual(respuesta.status_code, 400,
          "una direccion de dos palabras se corta al guardarla, no al generar")

    linea = "a hand covers the screen while another clerk walks in"
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/direccion",
                                   {"plan": {sid: linea}})
    igual(respuesta.status_code, 200, "guardar una direccion responde 200")
    igual(datos.get("guardado"), 1, "y dice cuantas ha guardado")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/direccion")
    igual((datos.get("plan") or {}).get(sid), linea, "queda guardada")

    # y NO se lleva por delante lo demas de esa unidad, que es la trampa que ya
    # costo una ronda con las cartelas
    respuesta, antes = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    unidad = ((antes.get("params") or {}).get("unidades") or {}).get(f"escena:{sid}") or {}
    ok("direccion" in unidad,
       f"vive en los params de SU unidad, no en un param global: {sorted(unidad)}")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/direccion",
                                   {"plan": {sid: ""}})
    igual(respuesta.status_code, 200, "y una vacia la quita")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/direccion")
    igual((datos.get("plan") or {}).get(sid), None, "queda quitada")

    # la receta la conoce, y va DESPUES de las cartelas y ANTES de los planos
    from pasos import recetas
    orden = [t["id"] for t in recetas.orden_de("video")]
    ok("direccion" in orden, f"la receta de Video la incluye: {orden}")
    ok(orden.index("plan_cartelas") < orden.index("direccion") < orden.index("assets"),
       "y en su sitio: despues de decidir que planos son texto, antes de pagar "
       "las imagenes")


# AQUI SE PROBABA «mirar», la revision de las imagenes: que un informe NO
# tocara la firma de ningun plano, porque si la tocara revisar el video pediria
# volver a pagarlo entero. Se retiro entera el 24-08-2026 con el resto del
# modulo. La propiedad que probaba sigue viva y la sigue probando la nota del
# montaje, justo debajo: lo que se escribe SOBRE lo terminado no es una entrada
# del paso y no vive en su firma.


def probar_nota_del_montaje(cliente, pid):
    """La nota del video terminado NO puede dejar el video obsoleto.

    Hasta el 21-08 vivia en los params del render, o sea DENTRO de su firma:
    escribir «la musica esta alta en 0:45» pintaba el MP4 de naranja como si
    volver a renderizarlo fuera a arreglar la musica -- y nadie leia la nota,
    asi que rehacerlo daba el mismo fichero.
    """
    seccion("LA NOTA DEL VIDEO TERMINADO ES UN REGISTRO")

    respuesta, antes = cliente.get(f"/api/proyectos/{pid}/pasos/render")
    firma_antes = antes.get("firma")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/montaje/notas")
    igual(respuesta.status_code, 200, "la nota responde 200")
    igual(datos.get("nota"), "", "y empieza vacia")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/montaje/notas",
                                   {"nota": "la musica esta alta en 0:45"})
    igual(respuesta.status_code, 200, "se guarda")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/montaje/notas")
    igual(datos.get("nota"), "la musica esta alta en 0:45", "y se relee")
    ok(datos.get("cuando"), "con la fecha, que es lo que la hace un registro")

    respuesta, despues = cliente.get(f"/api/proyectos/{pid}/pasos/render")
    igual(despues.get("firma"), firma_antes,
          "y la firma del render NO se ha movido: escribir sobre lo terminado "
          "no puede pedir volver a terminarlo")

    respuesta, params = cliente.get(f"/api/proyectos/{pid}/pasos/render")
    ok("feedback_final" not in (params.get("params") or {}),
       "la nota no vuelve a params ni de rebote")


def probar_repaso(cliente, pid):
    """El repaso: notas ancladas al segundo, y NINGUNA firma movida al escribir.

    Es la misma regla que la nota del montaje y por el mismo motivo, solo que
    aqui hay varias notas y cada una apunta a un momento: comentar un video no
    puede pedir volver a montarlo. Lo que toca las firmas es APLICAR.
    """
    seccion("EL REPASO: NOTAS SOBRE EL VIDEO MONTADO")

    _r, antes_render = cliente.get(f"/api/proyectos/{pid}/pasos/render")
    _r, antes_assets = cliente.get(f"/api/proyectos/{pid}/pasos/assets")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/repaso")
    igual(respuesta.status_code, 200, "el repaso responde 200")
    igual(datos.get("notas"), [], "y empieza sin notas")
    ok(isinstance(datos.get("catalogo"), dict),
       "trae el catalogo de ambitos y cambios: la pantalla tiene que poder "
       "decir lo que cuesta cada cosa antes de pulsar")

    # ---- QUE UNA NOTA NO SE QUEDE APUNTANDO AL PLANO DE AL LADO ------------
    #
    # El numero de un plano NO ES ESTABLE: al regrabar la voz la segmentacion
    # vuelve a cortar y lo que era S005 pasa a ser S004. Las notas ya escritas
    # se quedan con el numero viejo, y aplicarlas rehace el plano que estaba
    # bien. Se arregla al LEER, comparando lo que la nota dice que se decia
    # ahi (`ancla`) con lo que se dice ahora.
    cortes = datos.get("cortes") or []
    ok(len(cortes) >= 2, "el repaso trae los cortes del MP4")
    ok(all("narracion" in c for c in cortes),
       "y CADA CORTE TRAE LO QUE SE DICE EN EL: es contra esto contra lo que "
       "se comprueba que una nota siga en su plano. Sin ello, re-anclar no "
       "encontraria nada y daria por descolgadas todas las notas")
    hablados = [c for c in cortes if (c.get("narracion") or "").strip()]
    ok(len(hablados) >= 2, "y al menos dos planos dicen algo")

    fuera, dentro = hablados[0], hablados[-1]
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/repaso",
                                    {"t": 1.0, "texto": "esta se ha movido",
                                     "plano": fuera["id"],
                                     "ancla": dentro["narracion"]})
    igual(respuesta.status_code, 201, "una nota puede decir contra que se escribio")
    movida = datos["nota"]["id"]
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/repaso")
    suya = [n for n in datos["notas"] if n["id"] == movida][0]
    igual(suya.get("plano"), dentro["id"],
          "y al leerla vuelve al plano QUE DICE LO SUYO, no al numero que "
          "tenia guardado")
    igual(suya.get("reanclada"), fuera["id"],
          "diciendo de donde venia: recolocar a la callada es indistinguible "
          "de no haber hecho nada")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/repaso",
                                    {"t": 1.0, "texto": "esta se quedo sin sitio",
                                     "plano": fuera["id"],
                                     "ancla": "zumbaba un zeppelin de gengibre"})
    huerfana = datos["nota"]["id"]
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/repaso")
    suya = [n for n in datos["notas"] if n["id"] == huerfana][0]
    ok(suya.get("descolgada"),
       "y si lo que habia ya no esta en el video se DICE, en vez de dejarla "
       "senalando a cualquier sitio")
    cliente.delete(f"/api/proyectos/{pid}/repaso/{movida}")
    cliente.delete(f"/api/proyectos/{pid}/repaso/{huerfana}")

    # LA PANTALLA DEL VIDEO NO MANDA ANCLA: la rellena el servidor con lo que
    # dice ese plano. Se comprueba aparte porque es el camino por el que entran
    # casi todas las notas, y si ahi no se guardara el ancla el arreglo de
    # arriba solo protegeria a las de Imagenes.
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/repaso",
                                    {"t": 5.0, "texto": "sin decir contra que",
                                     "plano": dentro["id"]})
    sola = datos["nota"]["id"]
    igual(datos["nota"].get("ancla"), dentro["narracion"],
          "una nota que no dice contra que se escribio la ancla el servidor")
    cliente.delete(f"/api/proyectos/{pid}/repaso/{sola}")

    respuesta, _d = cliente.post(f"/api/proyectos/{pid}/repaso",
                                 {"t": 12.0, "texto": "   "})
    igual(respuesta.status_code, 400,
          "una nota SIN TEXTO rebota: una imagen sola no dice que hacer con ella")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/repaso",
                                    {"t": 92.4, "texto": "la musica esta alta"})
    igual(respuesta.status_code, 201, "una nota con texto se guarda")
    segunda = datos["nota"]["id"]
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/repaso",
                                    {"t": 10.0, "texto": "aqui sobra el rotulo"})
    primera = datos["nota"]["id"]
    igual([n["id"] for n in datos["notas"]], [primera, segunda],
          "y se leen en ORDEN DE VIDEO, no de escritura")
    igual(datos.get("pendientes"), 2, "las dos estan sin aplicar")

    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/repaso/{primera}",
                                   {"texto": "mejor quitalo entero"})
    igual(respuesta.status_code, 200, "se puede editar")
    igual(datos["notas"][0]["texto"], "mejor quitalo entero", "y se relee")
    respuesta, _d = cliente.put(f"/api/proyectos/{pid}/repaso/{primera}",
                                {"texto": "  "})
    igual(respuesta.status_code, 400, "pero no vaciar por la puerta de atras")
    respuesta, _d = cliente.put(f"/api/proyectos/{pid}/repaso/R999",
                                {"texto": "x"})
    igual(respuesta.status_code, 404, "ni editar una que no existe")

    _r, despues_render = cliente.get(f"/api/proyectos/{pid}/pasos/render")
    _r, despues_assets = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    igual(despues_render.get("firma"), antes_render.get("firma"),
          "y LA FIRMA DEL RENDER NO SE HA MOVIDO: escribir sobre el video "
          "terminado no puede pintarlo de naranja")
    igual(despues_assets.get("firma"), antes_assets.get("firma"),
          "ni la de assets")

    respuesta, datos = cliente.delete(f"/api/proyectos/{pid}/repaso/{primera}")
    igual(respuesta.status_code, 200, "se puede borrar")
    igual(len(datos.get("notas") or []), 1, "y se queda la otra")
    respuesta, _d = cliente.delete(f"/api/proyectos/{pid}/repaso/R999")
    igual(respuesta.status_code, 404, "borrar lo que no existe se dice")

    # limpieza: la nota que queda no puede quedarse pendiente para las suites
    # que corran despues sobre el mismo proyecto
    cliente.delete(f"/api/proyectos/{pid}/repaso/{segunda}")


def probar_plan_de_rotulos(cliente, pid):
    """El plan de rotulos, que es la otra cosa que describe UN plano.

    Nacio suelto (`plan_callouts`) igual que el de cartelas, y con el mismo
    precio: tocar el rotulo de un plano dejaba obsoletos los cuarenta y nueve y
    el render entero, sin dar ningun error.
    """
    seccion("EL GRAFISMO ES DEL VIDEO, Y SE APLICA SOLO")

    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/callouts/diseno")
    igual(respuesta.status_code, 200, "la pantalla de grafismo responde 200")
    ok(datos.get("sets") and datos.get("elegido"), "trae los sets y el elegido")
    ok(datos.get("subtitulo_tamanos"),
       f"y los tamanos de subtitulo que se pueden elegir: "
       f"{datos.get('subtitulo_tamanos')}")
    igual(datos.get("subtitulo_tam"), "normal", "con el normal de partida")
    ok("arquetipos" not in datos and "plan" not in datos,
       "y ya NO trae ni arquetipos ni plan de rotulos: se retiraron enteros "
       "el 22-08")

    # EL SET SE APLICA SOLO. Antes se calculaba `sugerido`, se servia aqui y ahi
    # se quedaba: habia que abrir la tarjeta y pulsarlo. Deducir algo bien y
    # pedirle despues a una persona que lo confirme es el paso que sobra.
    igual(datos.get("elegido"), datos.get("sugerido"),
          "sin elegir nada, manda lo que sugiere la guia de estilo")
    ok(datos.get("por_que"), "y se dice por que, que es lo que permite cambiarlo")

    # el set de diseno SI es global, y a proposito: describe el video entero
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/callouts/plan",
                               {"diseno": "editorial"})
    igual(respuesta.status_code, 200, "elegir el set de diseno responde 200")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/pasos/callouts")
    igual((datos.get("params") or datos).get("diseno"), "editorial",
          "y ese si va suelto: el grafismo es del video, no de un plano")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/callouts/plan",
                               {"diseno": "ni_idea"})
    igual(respuesta.status_code, 400, "un set inventado da 400")
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/callouts/plan", {})
    igual(respuesta.status_code, 400, "un PUT sin nada que guardar da 400")

    # LA REGLA, EN EL SITIO DONDE SE APLICA. Un param suelto indexado por
    # unidades se corta al guardarlo, con nombre y apellidos, en vez de dejar
    # el video entero naranja sin que nada falle.
    respuesta, datos = cliente.put(f"/api/proyectos/{pid}/pasos/callouts/params",
                                   {"plan_de_lo_que_sea": {"escena:S001": {"x": 1}}})
    igual(respuesta.status_code, 400,
          "un param suelto indexado por unidad da 400 al GUARDARLO")
    ok("unidades" in str(datos) and "plan_de_lo_que_sea" in str(datos),
       f"y el aviso dice que clave es y donde tiene que ir: {str(datos)[:120]}")


def probar_vista_de_cartela(cliente, raiz_proyecto, pid):
    """La cartela se dibuja con la DECISION, no con la foto de la ultima tanda.

    p6 estampa en plan.json la cartela que habia decidida cuando corrio
    (`_marcar_cartelas`). La vista leia esa foto ANTES que los params, asi que
    volver a decidir o editar el texto a mano no cambiaba el dibujo: se escribia
    otra frase y salia la de antes. Es justo lo que esta llamada existe para que
    no pase, y no lo veia ninguna prueba.

    El plan va a la carpeta de TRABAJO, que es de donde `plan_actual` lo coge
    cuando no hay version: asi esto no crea ninguna version ni mueve el grafo.
    """
    seccion("LA CARTELA SE DIBUJA CON LO DECIDIDO")
    from nucleo.proyecto import Proyecto, escribir_json

    proyecto = Proyecto(raiz_proyecto)
    escribir_json(os.path.join(proyecto.ruta_trabajo("assets"), "plan.json"), {
        "semilla": 7,
        "escenas": [{"id": "S001", "duracion": 4.0, "narracion": "lo que sea",
                     # la FOTO: lo que habia decidido la ultima tanda
                     "cartela": {"plantilla": "tesis", "fondo": "negro",
                                 "datos": {"texto": "La frase vieja"}}}],
    })

    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas", {
        "plan": {"S001": {"plantilla": "tesis",
                          "datos": {"texto": "The new line"}}}})
    igual(respuesta.status_code, 200, "guardar la cartela nueva responde 200")

    # el cuerpo es SVG, no JSON: hay que mirar el texto crudo
    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/cartelas/vista?plano=S001")
    igual(respuesta.status_code, 200, "la vista de la cartela responde 200")
    texto = respuesta.text
    ok("THE NEW LINE" in texto.upper(),
       "sale lo DECIDIDO, no lo que estampo la ultima tanda")
    ok("FRASE VIEJA" not in texto.upper(),
       f"y la foto de plan.json no manda: {texto[:80]}")

    # quitarla la quita: la vista deja de tener nada que dibujar
    cliente.put(f"/api/proyectos/{pid}/cartelas", {"plan": {}})
    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/cartelas/vista?plano=S001")
    igual(respuesta.status_code, 404,
          "sin cartela decidida no se dibuja la vieja: se dice que no hay")


def probar_cartela_sincronizada(cliente, raiz_proyecto, pid):
    """La vista ANIMADA escribe cada palabra cuando la voz la dice.

    Es el caso medido de PENDIENTE.md 12, el del 30M del video largo: la cartela
    colgaba de S002 y sus palabras se dicen enteras en S001, asi que el plan la
    pasa a S001 y deja S002 de continuacion. Lo que se comprueba aqui es que esa
    sincronia LLEGA A LA PANTALLA por la misma llamada que mira el repaso del
    montaje -- si el repaso dibujara su propia animacion, se elegiria una cosa y
    saldria otra, que es la regla de todas las muestras de esta casa.
    """
    seccion("LA CARTELA SE ESCRIBE CUANDO SE DICE")
    from nucleo.proyecto import Proyecto, escribir_json

    proyecto = Proyecto(raiz_proyecto)
    ficha = {"plantilla": "cifra", "fondo": "negro",
             "datos": {"cifra": "30M", "label": "Customer accounts on sale"}}
    escribir_json(os.path.join(proyecto.ruta_trabajo("assets"), "plan.json"), {
        "semilla": 7,
        "escenas": [
            # el plan YA la ha movido: la cartela vive en S001, que es donde se
            # dicen sus palabras, y S002 es su segunda mitad
            {"id": "S001", "t_in": 0.0, "t_out": 3.8, "duracion": 3.8,
             "narracion": "Thirty million customer accounts went up for sale",
             "marcas": [[0.123, 0.52], [0.524, 1.08], [1.081, 1.48],
                        [1.482, 1.88], [1.881, 2.12], [2.2, 2.2], [2.28, 2.36],
                        [2.361, 2.6]],
             "cartela": dict(ficha),
             "escritura": {"tiempos": [0.22, 1.081, 1.482, 1.921, 2.361],
                           "palabras": 5, "fin": 2.361, "cola": 1.4,
                           "falta": 0.0, "dos_planos": False}},
            {"id": "S002", "t_in": 3.8, "t_out": 7.2, "duracion": 3.4,
             "narracion": "dollars, roughly the price of an apartment",
             "marcas": [[3.802, 4.28], [4.552, 5.08], [5.16, 5.16],
                        [5.241, 5.56], [5.56, 5.64], [5.72, 5.72],
                        [5.801, 6.32]],
             "cartela": dict(ficha, sigue_a="S001"),
             "escritura": {"tiempos": [], "palabras": 5, "fin": 0.0,
                           "cola": 1.4, "falta": 0.0, "dos_planos": False,
                           "continua": True}},
        ],
    })
    # SOLO S001 en la decision: S002 es su continuacion, y eso no lo decide
    # nadie -- lo deduce la planificacion --, asi que no esta en params. La vista
    # tiene que resolverlo desde el hogar igualmente, o la rejilla enseniaria
    # «sin imagen» en un plano donde el video lleva la cartela puesta.
    respuesta, _ = cliente.put(f"/api/proyectos/{pid}/cartelas",
                               {"plan": {"S001": ficha}})
    igual(respuesta.status_code, 200, "guardar la cartela del 30M responde 200")

    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/cartelas/vista?plano=S001")
    igual(respuesta.status_code, 200, "la vista quieta responde 200")
    ok("<animate" not in respuesta.text,
       "la de la rejilla sigue quieta: ahi lo que se mira es el TEXTO")

    respuesta, _ = cliente.get(
        f"/api/proyectos/{pid}/cartelas/vista?plano=S001&animada=1")
    igual(respuesta.status_code, 200, "la vista animada responde 200")
    comienzos = sorted({float(m) for m in
                        re.findall(r'begin="([\d.]+)s"', respuesta.text)})
    ok(comienzos, f"la cartela se escribe palabra a palabra: {comienzos[:6]}")
    for cuando in (1.081, 1.482, 2.361):
        ok(any(abs(c - cuando) < 0.02 for c in comienzos),
           f"la palabra que se dice en {cuando}s entra en {cuando}s")

    respuesta, _ = cliente.get(
        f"/api/proyectos/{pid}/cartelas/vista?plano=S002&animada=1")
    igual(respuesta.status_code, 200, "la continuacion responde 200")
    ok("<animate" not in respuesta.text,
       "y la segunda mitad NO se reescribe: sigue puesta y quieta, o se "
       "reescribiria desde cero en mitad del corte")
    ok("30M" in respuesta.text,
       "y es LA MISMA cartela, resuelta desde su hogar aunque S002 no este en "
       "la decision: una continuacion es una consecuencia, no una decision")
    # y sigue mandando la decision: quitar la del hogar quita la continuacion
    cliente.put(f"/api/proyectos/{pid}/cartelas", {"plan": {}})
    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/cartelas/vista?plano=S002")
    igual(respuesta.status_code, 404,
          "si se quita la cartela del hogar, su continuacion deja de dibujarse")
    cliente.put(f"/api/proyectos/{pid}/cartelas", {"plan": {}})


def probar_trabajos_y_errores(cliente, pid, tid, virgen):
    seccion("TRABAJOS Y ERRORES")
    respuesta, datos = cliente.get("/api/trabajos")
    igual(respuesta.status_code, 200, "GET /api/trabajos responde 200")
    ok(any(t["id"] == tid for t in datos["trabajos"]),
       "el historico de trabajos recuerda los terminados")

    respuesta, datos = cliente.get("/api/trabajos", params={"activos": 1})
    igual(respuesta.status_code, 200, "se pueden pedir solo los activos")

    respuesta, datos = cliente.get("/api/trabajos/no_existe")
    igual(respuesta.status_code, 404, "un trabajo inexistente da 404")
    ok("error" in (datos or {}), "con su mensaje de error")

    respuesta, datos = cliente.post("/api/trabajos/no_existe/cancelar")
    igual(respuesta.status_code, 404, "cancelar un trabajo inexistente da 404")

    respuesta, datos = cliente.post(f"/api/trabajos/{tid}/cancelar")
    igual(respuesta.status_code, 200, "cancelar uno terminado responde 200")
    ok(datos.get("cancelacion_pedida") is False,
       "diciendo que ya no habia nada que cancelar")

    respuesta = cliente.sesion.post(
        f"{cliente.base}/api/proyectos", data=b"{esto no es json",
        headers={"Content-Type": "application/json"}, timeout=30)
    igual(respuesta.status_code, 400, "un cuerpo que no es JSON da 400")
    ok("error" in respuesta.json(), "y sale como {'error': ...}")

    respuesta, datos = cliente.get("/api/nada/de/nada")
    igual(respuesta.status_code, 404, "una ruta inexistente da 404")
    ok("error" in (datos or {}), "tambien en forma de {'error': ...}")

    # un proyecto con el estado corrupto no puede tumbar el servicio: el nucleo
    # aparta el fichero ilegible (no lo pisa) y el proyecto se abre en blanco
    roto = os.path.join(cliente.carpeta, "roto")
    os.makedirs(roto, exist_ok=True)
    with open(os.path.join(roto, "proyecto.json"), "w", encoding="utf-8") as fh:
        json.dump({"id": "roto", "nombre": "Roto"}, fh)
    with open(os.path.join(roto, "estado.json"), "w", encoding="utf-8") as fh:
        json.dump({"pasos": "esto deberia ser un objeto"}, fh)
    respuesta, datos = cliente.get("/api/proyectos/roto")
    igual(respuesta.status_code, 200, "un proyecto corrupto se abre igualmente")
    igual([p["estado"] for p in datos["pasos"]][0], "pendiente",
          "y arranca de cero, con la ingesta pendiente")
    ok(any(n.startswith("estado.roto.") for n in os.listdir(roto)),
       "el estado ilegible se guarda a un lado en vez de sobreescribirse")

    respuesta, datos = cliente.get("/api/salud")
    igual(respuesta.status_code, 200, "y el servicio sigue en pie despues")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/voz/ejecutar",
                                    {"unidades": ["B001"]})
    igual(respuesta.status_code, 400, "pedir unidades a un paso que no las tiene da 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"unidades": ["escena:S99"]})
    igual(respuesta.status_code, 400, "pedir una unidad que no existe da 400")
    ok("escena:S99" in (datos or {}).get("error", ""),
       "y el error nombra la unidad desconocida")
    ok("declaradas" in (datos or {}), "listando las que si valen")

    # las unidades del PLAN del paso tambien valen sin estar declaradas: una
    # unidad recien planificada no tiene params ni dependencias propagadas, y
    # aun asi pedirla por id es como se genera desde su tarjeta
    trabajo_assets = os.path.join(cliente.carpeta, pid, "pasos", "assets", "trabajo")
    os.makedirs(trabajo_assets, exist_ok=True)
    with open(os.path.join(trabajo_assets, "plan.json"), "w", encoding="utf-8") as fh:
        json.dump({"assets": {"asset:pepe": {"tipo": "reparto",
                                             "nombre": "pepe"}},
                   "escenas": [{"id": "S001"}], "dependencias": {}}, fh)
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"unidades": ["asset:pepe"]})
    igual(respuesta.status_code, 202,
          "una unidad que el plan conoce pasa la validacion sin estar declarada")
    esperar_trabajo(cliente, datos["trabajo_id"])
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"unidades": ["asset:nadie"]})
    igual(respuesta.status_code, 400,
          "y una que ni el plan ni el estado conocen sigue dando 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{virgen}/pasos/assets/ejecutar",
                                    {"unidades": ["escena:S01"]})
    igual(respuesta.status_code, 409,
          "pedir unidades en un proyecto que aun no tiene ninguna da 409")

    # la opcion 'tipos' de assets: es la que usan los botones de "Generar los
    # personajes" / "las piezas", y el servidor la tiraba sin decirlo
    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"tipos": "reparto"})
    igual(respuesta.status_code, 400, "'tipos' que no es lista da 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"tipos": [123]})
    igual(respuesta.status_code, 400, "'tipos' con cosas que no son texto da 400")

    respuesta, datos = cliente.post(f"/api/proyectos/{pid}/pasos/assets/ejecutar",
                                    {"tipos": ["reparto"]})
    igual(respuesta.status_code, 202, "lanzar assets con tipos responde 202")
    igual((datos.get("opciones") or {}).get("tipos"), ["reparto"],
          "y la respuesta confirma que 'tipos' viaja como opcion de invocacion")
    ficha = esperar_trabajo(cliente, datos["trabajo_id"])
    # sin estilo fijado el paso corta la pasada: lo que se prueba aqui es que
    # la opcion LLEGA y el paso corre hasta su propia validacion de negocio
    igual(ficha["estado"], "error", "sin estilo fijado la pasada corta en error")
    ok("estilo" in str(ficha.get("error", "")).lower(),
       "y el error dice que falta el estilo")


# -------------------------------------------------------------------------- main

def probar_claves(cliente):
    """La pantalla de configuracion: N cuentas, sin que salga ninguna clave."""
    seccion("CLAVES DE API")
    respuesta, ficha = cliente.get("/api/claves")
    igual(respuesta.status_code, 200, "GET /api/claves responde 200")
    crudo = json.dumps(ficha)
    ok("clave" not in ficha.get("cartesia", {}),
       "la respuesta NO lleva la clave de Cartesia")
    ok(all("clave" not in c for c in ficha.get("openai", [])),
       "ni las de OpenAI: solo etiqueta y los cuatro ultimos")
    ok("max_openai" in ficha, "dice cuantas cuentas admite")

    # UNA SOLA CLAVE DE OPENAI. Con varias habia un reparto que convertia una
    # clave mal puesta en «va mas lento» en vez de en un error, y una segunda
    # cuenta doblaba el techo de imagenes por minuto. Ahora es una: si esta mal
    # se dice, y se para.
    respuesta, ficha = cliente.put("/api/claves", {"openai": [
        {"etiqueta": "mia@ejemplo.com", "clave": "sk-" + "a" * 40}]})
    igual(respuesta.status_code, 200, f"PUT /api/claves guarda la clave: {ficha}")
    igual(len(ficha["openai"]), 1, "y guarda UNA")
    ok(ficha["openai"][0]["cola"].endswith("aaaa"),
       f"con su cola, que es lo unico que se ensena: {ficha['openai']}")

    respuesta, _ = cliente.put("/api/claves", {"openai": [
        {"clave": "sk-" + "a" * 40}, {"clave": "sk-" + "b" * 40}]})
    igual(respuesta.status_code, 400, "dos claves de OpenAI dan 400")

    # LAS TRES SUELTAS: se editan desde la pantalla, no en un fichero a mano.
    # Jamendo y Freesound estuvieron fuera del editor --«son del stack»-- y
    # ponerlas era abrir el .env con un editor de texto, que es justo lo que
    # esta pantalla existe para no tener que hacer.
    respuesta, ficha = cliente.put("/api/claves", {
        "cartesia": {"clave": "car-" + "x" * 20},
        "jamendo": {"clave": "jam-" + "y" * 12},
        "freesound": {"clave": "fso-" + "z" * 12}})
    igual(respuesta.status_code, 200, "PUT guarda las tres claves sueltas")
    for suelta in ("cartesia", "jamendo", "freesound"):
        ok(ficha[suelta]["puesta"], f"{suelta} queda puesta")
        ok("clave" not in ficha[suelta],
           f"y la de {suelta} NO baja al navegador")

    # editar UNA sin mandar las otras no borra las otras: es para lo que existe
    # el marcador CONSERVAR, y sin el cambiar Jamendo se llevaria Cartesia
    respuesta, ficha = cliente.put("/api/claves",
                                   {"jamendo": {"clave": "jam-nueva-1234"}})
    ok(ficha["cartesia"]["puesta"], "cambiar Jamendo no borra Cartesia")
    ok(ficha["freesound"]["puesta"], "ni Freesound")
    respuesta, ficha = cliente.put("/api/claves", {"jamendo": {"clave": ""}})
    ok(not ficha["jamendo"]["puesta"], "y una vacia la quita, que es como se quita")

    respuesta, _ = cliente.put("/api/claves", {"openai": [{"clave": "corta"}]})
    igual(respuesta.status_code, 400, "una clave que no lo parece da 400")


def probar_cuentas_cli(cliente):
    """Las cuentas del CLI: una LISTA ORDENADA, y se entra desde la pantalla."""
    seccion("LAS CUENTAS DEL CLI DE CLAUDE")
    respuesta, ficha = cliente.get("/api/claves/cli")
    igual(respuesta.status_code, 200, "GET /api/claves/cli responde 200")
    ok(isinstance(ficha.get("cuentas"), list), "devuelve una lista de cuentas")
    ok(ficha.get("max", 0) >= 2, f"y dice cuantas admite: {ficha.get('max')}")

    # ANADIR: la lista entera, como las de OpenAI. El id lo pone el servidor.
    respuesta, ficha = cliente.put("/api/claves", {"claude_cli": {"cuentas": [
        {"etiqueta": "la mia"}, {"etiqueta": "la de repuesto"}]}})
    igual(respuesta.status_code, 200, f"PUT guarda dos cuentas del CLI: {ficha}")
    cuentas = ficha["claude_cli"]["cuentas"]
    igual([c["etiqueta"] for c in cuentas], ["la mia", "la de repuesto"],
          "en el orden en que se mandan, que ES la prioridad")
    ok(all(c["id"] for c in cuentas), f"y con un id cada una: {cuentas}")
    ok(all(not c["entrada"] for c in cuentas),
       "recien creadas NO cuentan como logueadas: una carpeta sin sesion "
       "hecha falla de una forma que no se parece a nada")

    primero, segundo = cuentas[0]["id"], cuentas[1]["id"]
    respuesta, ficha = cliente.put("/api/claves", {"claude_cli": {"cuentas": [
        {"id": segundo, "etiqueta": "la de repuesto"},
        {"id": primero, "etiqueta": "la mia"}]}})
    igual([c["id"] for c in ficha["claude_cli"]["cuentas"]], [segundo, primero],
          "reordenar es mandar la lista en otro orden")

    respuesta, ficha = cliente.put("/api/claves", {"claude_cli": {"cuentas": [
        {"id": segundo, "etiqueta": "la de repuesto"}]}})
    igual([c["id"] for c in ficha["claude_cli"]["cuentas"]], [segundo],
          "y quitar una es no mandarla")

    # LA PANTALLA NO MANDA `config_dir` NI `entrada`, y aunque los mande no
    # cuentan: son del servidor. Si pudiera, un «Guardar» hecho sobre una ficha
    # vieja desharia en silencio el login que acaba de terminar.
    respuesta, ficha = cliente.put("/api/claves", {"claude_cli": {"cuentas": [
        {"id": segundo, "etiqueta": "la de repuesto",
         "config_dir": "C:/me/lo/invento", "entrada": True}]}})
    igual(respuesta.status_code, 200, "mandar carpeta y sesion no da error…")
    igual(ficha["claude_cli"]["cuentas"][0]["config_dir"], "",
          "…pero la carpeta la sigue poniendo el servidor")
    ok(not ficha["claude_cli"]["cuentas"][0]["entrada"],
       "y la sesion tambien: la pantalla no puede declararse logueada")

    respuesta, _ = cliente.put("/api/claves",
                               {"claude_cli": {"cuentas": [{}] * 20}})
    igual(respuesta.status_code, 400,
          "pasarse del tope da 400: la cadena se recorre en serie")
    respuesta, _ = cliente.put("/api/claves", {"claude_cli": "una cadena"})
    igual(respuesta.status_code, 400, "y una forma que no es una lista, tambien")

    # ENTRAR con una cuenta que no existe
    respuesta, _ = cliente.post("/api/claves/cli/noexiste/entrar")
    igual(respuesta.status_code, 404, "entrar con una cuenta que no existe da 404")
    respuesta, _ = cliente.post("/api/claves/cli/noexiste/codigo", {"codigo": "x"})
    igual(respuesta.status_code, 404, "y pegarle un codigo, tambien")

    # PEGAR UN CODIGO SIN HABER ENTRADO: 409, no 500
    respuesta, ficha = cliente.post(f"/api/claves/cli/{segundo}/codigo",
                                    {"codigo": "loquesea"})
    igual(respuesta.status_code, 409,
          "un codigo sin acceso abierto da 409 y lo explica")
    ok("Entrar" in json.dumps(ficha), f"y dice que hay que darle a Entrar: {ficha}")

    # CANCELAR algo que no existe no es un error
    respuesta, ficha = cliente.delete(f"/api/claves/cli/{segundo}/entrar")
    igual(respuesta.status_code, 200, "cancelar un acceso que no hay responde 200")
    ok(ficha.get("cancelado") is False, "diciendo que no habia ninguno")

    # SALIR de la sesion POR DEFECTO no se permite: es la consola del usuario
    respuesta, ficha = cliente.post(f"/api/claves/cli/{segundo}/salir")
    igual(respuesta.status_code, 409,
          "cerrar la sesion por defecto del CLI da 409, no la cierra")
    ok("terminal" in json.dumps(ficha),
       f"y dice por que: es la misma con la que el usuario tiene su consola: {ficha}")

    cliente.put("/api/claves", {"claude_cli": {"cuentas": []}})


def probar_asistente(cliente):
    """El asistente: estado, una charla entera contra el doble, y sus errores.

    El servidor corre con ESTUDIO_SIMULAR=1, asi que no se llama al CLI: contesta
    `asistente.ejecutar_simulado`, que repite lo que recibe. Lo que se prueba
    aqui es la API: abrir, preguntar, seguir la respuesta, reanudar, cancelar y
    cerrar, y que cada fallo tenga su codigo.
    """
    seccion("EL ASISTENTE")
    respuesta, ficha = cliente.get("/api/asistente")
    igual(respuesta.status_code, 200, "GET /api/asistente responde 200")
    ok(isinstance(ficha.get("listo"), bool), f"y dice si puede contestar: {ficha}")
    ok(ficha.get("modelo") and ficha.get("esfuerzo"),
       "y con que modelo y esfuerzo")
    ok(ficha.get("simulado") is True, "en las pruebas se declara simulado")

    respuesta, _ = cliente.get("/api/asistente/charlas/noexiste")
    igual(respuesta.status_code, 404, "una charla que no existe da 404")
    respuesta, _ = cliente.post("/api/asistente/charlas/noexiste/mensajes",
                                {"texto": "hola"})
    igual(respuesta.status_code, 404, "y preguntarle, tambien")
    respuesta, _ = cliente.post("/api/asistente/charlas/noexiste/cancelar")
    igual(respuesta.status_code, 404, "y cancelarla")
    respuesta, ficha = cliente.delete("/api/asistente/charlas/noexiste")
    igual(respuesta.status_code, 200, "cerrar una que no existe responde 200")
    ok(ficha.get("cerrada") is False, "diciendo que no habia ninguna")

    respuesta, charla = cliente.post("/api/asistente/charlas")
    igual(respuesta.status_code, 201, "POST /api/asistente/charlas abre una charla")
    cid = charla.get("id")
    ok(cid and charla.get("turnos") == [] and charla.get("ocupada") is False,
       f"vacia y libre: {charla}")

    respuesta, _ = cliente.post(f"/api/asistente/charlas/{cid}/mensajes", {"texto": "   "})
    igual(respuesta.status_code, 400, "una pregunta vacia da 400")

    respuesta, ficha = cliente.post(f"/api/asistente/charlas/{cid}/mensajes",
                                    {"texto": "que me falta?", "proyecto": "",
                                     "pantalla": {"pestana": "encargo"}})
    igual(respuesta.status_code, 202, f"una pregunta responde 202: {ficha}")
    igual(len(ficha.get("turnos") or []), 2, "con el turno de la persona y el del asistente")
    igual(ficha["turnos"][1]["estado"], "pensando", "que empieza pensando")

    def esperar_respuesta(segundos=20):
        limite = time.time() + segundos
        while time.time() < limite:
            r, f = cliente.get(f"/api/asistente/charlas/{cid}")
            if r.status_code == 200 and not f.get("ocupada"):
                return f
            time.sleep(0.2)
        return f

    ficha = esperar_respuesta()
    ultimo = ficha["turnos"][-1]
    igual(ultimo["estado"], "listo", f"y termina listo: {ultimo}")
    ok("que me falta?" in ultimo["texto"], "el doble repite la pregunta")
    ok("de arranque" in ultimo["texto"], "y el primer turno es de arranque")
    ok(ficha.get("reanuda") is True, "la charla se acuerda de la sesion")
    ok(ultimo.get("segundos") is not None and ultimo.get("tokens"),
       "y el turno dice cuanto tardo y cuantos tokens")

    respuesta, ficha = cliente.post(f"/api/asistente/charlas/{cid}/mensajes",
                                    {"texto": "y ahora?"})
    igual(respuesta.status_code, 202, "una segunda pregunta tambien va")
    ficha = esperar_respuesta()
    ok("reanudando la sesion" in ficha["turnos"][-1]["texto"],
       f"y el segundo turno REANUDA la sesion del primero: {ficha['turnos'][-1]['texto'][:120]}")

    respuesta, ficha = cliente.post(f"/api/asistente/charlas/{cid}/cancelar")
    igual(respuesta.status_code, 200, "cancelar sin nada en marcha responde 200")
    ok(ficha.get("cancelado") is False, "diciendo que no habia nada que parar")

    respuesta, ficha = cliente.delete(f"/api/asistente/charlas/{cid}")
    igual(respuesta.status_code, 200, "cerrar la charla responde 200")
    ok(ficha.get("cerrada") is True, "y la cierra")
    respuesta, _ = cliente.get(f"/api/asistente/charlas/{cid}")
    igual(respuesta.status_code, 404, "y ya no esta")


def probar_la_foto_del_asistente(cliente, pid):
    """La foto del estado que recibe el asistente lleva lo que hace falta y
    ninguna clave. Se pide por la API (`/api/asistente/foto`), que devuelve
    EXACTAMENTE el texto que va delante de cada pregunta."""
    seccion("LA FOTO QUE VE EL ASISTENTE")
    # una clave de mentira para comprobar que NO viaja
    respuesta, _ = cliente.put("/api/claves", {"openai": [
        {"etiqueta": "", "clave": "sk-esta-clave-no-puede-salir-en-la-foto-000",
         "activa": True}]})
    igual(respuesta.status_code, 200, "se guarda una clave de OpenAI de mentira")
    respuesta, ficha = cliente.get("/api/asistente/foto",
                                   params={"proyecto": pid, "pestana": "imagenes",
                                           "error": "S03: la cara sale rara"})
    igual(respuesta.status_code, 200, "GET /api/asistente/foto responde 200")
    foto = ficha.get("foto") or ""
    ok("sk-esta-clave" not in foto and "foto-000" not in foto, "la clave NO viaja en la foto")
    ok("OpenAI (imagenes) puesta" in foto, "pero si que esta puesta")
    ok("PROYECTO ABIERTO EN PANTALLA" in foto and pid in foto, "lleva el proyecto abierto")
    ok("paso ingesta" in foto and "paso render" in foto, "con sus ocho pasos")
    ok("S03: la cara sale rara" in foto, "y los errores que la pantalla tiene a la vista")
    ok("pestana: imagenes" in foto, "y la pestana")
    ok("proyectos (videos)" in foto, "y la lista de videos")
    ok("ultimos trabajos" in foto, "y los ultimos trabajos del video")
    ok(ficha.get("caracteres") == len(foto), "y dice cuanto ocupa")

    respuesta, ficha = cliente.get("/api/asistente/foto")
    sin = ficha.get("foto") or ""
    ok("PROYECTO ABIERTO" not in sin and "fecha y hora" in sin,
       "sin proyecto abierto la foto sigue saliendo")
    respuesta, ficha = cliente.get("/api/asistente/foto", params={"proyecto": "no_existe"})
    igual(respuesta.status_code, 200, "un proyecto que no existe no revienta")
    ok("no_existe" in ficha.get("foto", "") and "desconocido" in ficha.get("foto", ""),
       "se dice en la propia foto")
    cliente.put("/api/claves", {"openai": []})


def probar_onboarding(cliente):
    """La marca de la guia de inicio vive en los ajustes del servidor."""
    seccion("LA GUIA DE INICIO")
    respuesta, ficha = cliente.get("/api/ajustes")
    igual(respuesta.status_code, 200, "GET /api/ajustes responde 200")
    ok(ficha["ajustes"].get("onboarding_visto") is False,
       f"de fabrica la guia no se ha visto: {ficha['ajustes']}")
    respuesta, ficha = cliente.put("/api/ajustes", {"onboarding_visto": True})
    igual(respuesta.status_code, 200, "se marca como vista")
    ok(ficha["ajustes"].get("onboarding_visto") is True, "y lo dice")
    respuesta, _ = cliente.put("/api/ajustes", {"onboarding_visto": "si"})
    igual(respuesta.status_code, 400, "una marca que no es booleana da 400")
    respuesta, ficha = cliente.get("/api/ajustes")
    ok(ficha["ajustes"].get("onboarding_visto") is True
       and ficha["ajustes"].get("calidad_imagen") in ficha.get("calidades", []),
       "se queda marcada y la calidad sigue en su sitio")


def probar_salud_de_las_cuentas(cliente):
    """La salud de las cuentas de Claude y la prueba de las claves, por la API.

    En modo simulado `salud_cli.probar` no llama al CLI y `comprobar_claves`
    no sale a la red: lo que se comprueba es la API y que la salud viaje en
    la lista de cuentas y en el estado del asistente.
    """
    seccion("LA SALUD DE LAS CUENTAS Y LA PRUEBA DE LAS CLAVES")
    respuesta, ficha = cliente.put("/api/claves", {"claude_cli": {"cuentas": [
        {"etiqueta": "la de prueba"}]}})
    igual(respuesta.status_code, 200, "se anade una cuenta del CLI")
    cid = ficha["claude_cli"]["cuentas"][0]["id"]
    respuesta, ficha = cliente.get("/api/claves/cli")
    ok("salud" in ficha["cuentas"][0], "cada cuenta de la lista lleva su salud")
    ok(ficha["cuentas"][0]["salud"] is None, "y una recien anadida no tiene nada apuntado")

    respuesta, ficha = cliente.post(f"/api/claves/cli/{cid}/probar")
    igual(respuesta.status_code, 200, f"probar una cuenta responde 200: {ficha}")
    igual((ficha.get("salud") or {}).get("estado"), "ok", "en simulado contesta ok")
    ok("cuentas" in ficha and ficha["cuentas"][0]["salud"]["estado"] == "ok",
       "y devuelve la lista con la salud puesta")
    respuesta, _ = cliente.post("/api/claves/cli/noexiste/probar")
    igual(respuesta.status_code, 404, "probar una cuenta que no existe da 404")

    respuesta, ficha = cliente.get("/api/asistente")
    ok(isinstance(ficha.get("cuentas"), list) and "sin_probar" in ficha,
       f"el estado del asistente lleva las cuentas con su salud: {ficha.get('cuentas')}")
    respuesta, ficha = cliente.post("/api/asistente/probar")
    igual(respuesta.status_code, 200, "probar el asistente responde 200")
    ok(isinstance(ficha.get("probadas"), list) and "listo" in ficha,
       f"y dice que cuentas probo y si esta listo: {ficha.get('probadas')}")

    respuesta, ficha = cliente.post("/api/claves/probar", {"claude": True})
    igual(respuesta.status_code, 200, f"probar todas las claves responde 200: {str(ficha)[:200]}")
    proveedores = [p["proveedor"] for p in ficha.get("pruebas") or []]
    ok(proveedores[:4] == ["openai", "cartesia", "jamendo", "freesound"],
       f"con los cuatro servicios en orden: {proveedores}")
    ok("claude" in proveedores, "y Claude cuando se pide")
    ok(isinstance(ficha.get("resumen"), str) and "todo_bien" in ficha,
       "con un resumen legible y un veredicto")
    respuesta, ficha = cliente.post("/api/claves/probar", {"claude": False})
    ok("claude" not in [p["proveedor"] for p in ficha.get("pruebas") or []],
       "y sin Claude cuando no se pide")

    respuesta, _ = cliente.get("/api/asistente/foto")
    cliente.put("/api/claves", {"claude_cli": {"cuentas": []}})


def probar_recetas(cliente, pid):
    """Ejecutar una pestana entera: el catalogo, el estado y el lanzamiento."""
    seccion("RECETAS POR PESTANA")
    respuesta, catalogo = cliente.get("/api/recetas")
    igual(respuesta.status_code, 200, "GET /api/recetas responde 200")
    pestanas = {p["id"]: p for p in catalogo["pestanas"]}
    igual(sorted(pestanas), ["guion", "origen", "render", "video", "voz"],
          "las cinco pestanas tienen receta")
    tandas = pestanas["video"]["tandas"]
    ok(["escenarios", "guia_estilo"] == tandas[0],
       f"lo que no depende de nada va en la misma tanda: {tandas[0]}")
    plano = [t for t in tandas if "assets" in t][0]
    igual(plano, ["assets"], "generar los planos va solo, esperando a los demas")
    orden = [t for tanda in tandas for t in tanda]
    ok(orden.index("plan_cartelas") < orden.index("assets"),
       "las cartelas se deciden ANTES de generar: si no, se paga una imagen "
       "para tirarla")
    # EL CORTE ES UN PASO, y va antes que todo lo que decide POR PLANO. Sin él,
    # la tanda de un vídeo NUEVO se plantaba a la mitad con «no hay planos
    # todavía»: las cartelas y la dirección no tenían sobre qué decidir.
    ok(orden.index("corte") < orden.index("plan_cartelas"),
       f"el corte en planos va antes que las cartelas ({orden})")
    ok(orden.index("corte") < orden.index("direccion"),
       "y antes que la dirección, que también decide plano a plano")
    # Y LAS PIEZAS, DESPUÉS DE LAS CARTELAS: un plano que se convierte en
    # cartela pierde su sitio y su gente, así que el mapa que pedía deja de
    # hacer falta. Generarlo antes es pagarlo para tirarlo.
    ok(orden.index("plan_cartelas") < orden.index("piezas"),
       "las piezas van después de las cartelas")
    corte = [t for t in tandas if "corte" in t][0]
    igual(corte, ["corte"], "y el corte va solo: dos tareas replanificando a "
                            "la vez escriben sobre la misma carpeta")

    # Y EL CORTE LO HACE ESA TAREA, UNA VEZ. Las de `assets` de la receta pasan
    # `replantear: False`: replantear renumera los planos, y si lo hiciera
    # también la pasada de piezas o la de planos, la dirección y las cartelas
    # —que se deciden POR PLANO— acabarían apuntando a otros. Medido en la
    # primera tanda de un vídeo nuevo: el corte dio 97 planos y piezas 98.
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "app.py"),
                     encoding="utf-8").read()
    trozo = fuente[fuente.index('if tarea_id == "piezas":'):
                   fuente.index('if tarea_id == "callouts":')]
    igual(trozo.count('"replantear": False'), 2,
          "las dos tareas de assets de la receta pasan replantear: False")
    ok(orden.index("assets") < orden.index("callouts"),
       "y los subtitulos DESPUES de los planos: se dibujan encima")
    ok("plan_callouts" not in orden,
       "y la fase de PAGO que decidia los rotulos ya no existe: los rotulos se "
       "retiraron enteros el 22-08")

    # LO QUE LA PANTALLA NECESITA PARA NO DEDUCIR NADA. `publico` es como se
    # cuenta esa tarea mientras corre, y `de_fabrica` es si viene puesta sin
    # ninguna receta guardada.
    todas = [t for p in catalogo["pestanas"] for t in p["tareas"]]
    ok(all(t.get("publico") for t in todas),
       "cada tarea del catalogo dice su nombre publico")
    ok(all("de_fabrica" in t for t in todas),
       "y si viene puesta de fabrica")
    ids_guion = [t["id"] for t in pestanas["guion"]["tareas"]]
    ok("integraciones" not in ids_guion and "fuentes" not in ids_guion,
       f"ni menciones del mapa ni documentalista: no existen ({ids_guion})")

    respuesta, estado = cliente.get(f"/api/proyectos/{pid}/pestanas/video")
    igual(respuesta.status_code, 200, "GET /pestanas/video responde 200")
    ok(all("al_dia" in t and "puesta" in t for t in estado["tareas"]),
       "cada tarea dice si esta al dia y si esta puesta")
    ok(any(t["cuesta"] for t in estado["tareas"]), "y cual cuesta dinero")

    # UNA TAREA QUE CAMBIA LO QUE CUESTA CADA IMAGEN NO SE ENCIENDE SOLA... en
    # un video que YA las ha pagado. `direccion` reescribe el prompt de todos
    # los planos, o sea que la cache falla y se vuelven a pagar. Encendida de
    # fabrica, la primera vez que alguien pulsara «Generar lo que falta» en un
    # video ya montado se encontraria el video entero regenerado sin haber
    # elegido nada. Donde no hay ninguna imagen que repagar --un video que
    # nunca ha generado sus planos-- viene encendida, se haya creado por donde
    # se haya creado: es la regla de `_receta_de_video`, y esta
    # pantalla la lee de ahi para decir lo mismo que va a hacer la tanda.
    respuesta, assets = cliente.get(f"/api/proyectos/{pid}/pasos/assets")
    con_planos = bool((assets or {}).get("versiones"))
    puestas = {t["id"]: t["puesta"] for t in estado["tareas"]}
    igual(puestas.get("direccion"), not con_planos,
          "la direccion viene APAGADA en un video con planos hechos y ENCENDIDA "
          f"en uno que nunca los ha pagado (este {'los tiene' if con_planos else 'no los tiene'})")
    ok(puestas.get("plan_cartelas") and puestas.get("piezas"),
       f"y las demas opcionales siguen puestas: {puestas}")
    if con_planos:
        ok("direccion" not in (estado.get("pendientes") or []),
           "asi que no sale en lo pendiente de la pestana")

    respuesta, _ = cliente.get(f"/api/proyectos/{pid}/pestanas/no_existe")
    igual(respuesta.status_code, 404, "una pestana inventada da 404")
    respuesta, _ = cliente.post(f"/api/proyectos/{pid}/pestanas/video/generar",
                                {"modo": "raro"})
    igual(respuesta.status_code, 400, "un modo inventado da 400")

    # apagar una tarea opcional se guarda, y deja de salir en lo pendiente
    respuesta, receta = cliente.post("/api/recetas", {
        "pestana": "video", "nombre": "Sin cartelas",
        "tareas": {"plan_cartelas": False}, "por_defecto": True})
    igual(respuesta.status_code, 200, f"POST /api/recetas guarda: {receta}")
    ok(receta["tareas"]["assets"],
       "lo obligatorio se fuerza aunque no se mande")
    igual(receta["tareas"]["plan_cartelas"], False, "y lo opcional se respeta")
    respuesta, estado = cliente.get(f"/api/proyectos/{pid}/pestanas/video")
    cartelas_puesta = [t for t in estado["tareas"] if t["id"] == "plan_cartelas"][0]
    igual(cartelas_puesta["puesta"], False,
          "la receta por defecto manda en lo que se va a hacer")
    respuesta, _ = cliente.delete(f"/api/recetas/{receta['id']}")
    igual(respuesta.status_code, 200, "y se puede borrar")
    respuesta, _ = cliente.post("/api/recetas", {"pestana": "video"})
    igual(respuesta.status_code, 400, "una receta sin nombre da 400")


#: Palabras de la COCINA. Ninguna puede salir en una frase publica: son los
#: nombres de las piezas del Estudio, y quien mira el video no tiene por que
#: llevarselos. La lista es de prefijos: 'subtitul' pilla singular y plural.
COCINA = (
    "prompt", "modelo", "cli", "claude", "openai", "cartela", "callout",
    "asset", "rotulo", "rótulo", "json", "ffmpeg", "yt-dlp", "api", "token",
    "param", "receta", "preset", "taller", "plano", "render", "moodboard",
    "wikimedia", "jamendo", "freesound", "cartesia", "tts", "subtitul",
    "subtítul", "guion", "guión", "brief", "ingesta", "pestaña", "unidad",
)


def probar_lo_que_se_cuenta_en_publico():
    """El modo light se graba: sus barras no pueden ensenar como esta hecho.

    Aqui se fija el CONTRATO de esa mascara, que tiene tres mitades:

      · COMPLETA: toda tarea tiene su frase publica. Una tarea nueva sin entrada
        no ensena su nombre de casa -- se dice «Trabajando» -- pero eso es el
        respaldo, no el sitio donde se quiere estar.
      · LIMPIA: ni una palabra de la cocina, y ninguna frase igual al nombre de
        casa (si coincidieran no seria una mascara, seria una copia).
      · SEGURA: lo que no se sabe se tapa. `publico_de` de una tarea que no
        existe devuelve el generico, nunca el nombre real.
    """
    seccion("LO QUE SE CUENTA EN PUBLICO")
    sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "pasos"))
    import recetas                                            # noqa: PLC0415
    import presets_light                                      # noqa: PLC0415

    for modulo, nombre in ((recetas, "recetas"), (presets_light, "presets_light")):
        faltan = [x["id"] for x in modulo.TAREAS if x["id"] not in modulo.PUBLICO]
        igual(faltan, [], f"{nombre}: todas las tareas tienen frase publica")
        for tarea in modulo.TAREAS:
            ficha = modulo.PUBLICO.get(tarea["id"]) or {}
            ok(bool(ficha.get("nombre")) and bool(ficha.get("fases")),
               f"{nombre}/{tarea['id']}: tiene titulo y al menos una fase")
            ok(ficha.get("nombre") != tarea["nombre"],
               f"{nombre}/{tarea['id']}: la frase publica no es el nombre de casa")
            frases = [ficha.get("nombre", "")] + list(ficha.get("fases") or [])
            for frase in frases:
                sucias = [p for p in COCINA
                          if re.search(r"\b" + re.escape(p), frase, re.I)]
                igual(sucias, [], f"{nombre}/{tarea['id']}: «{frase}» sin cocina")

        # LA FASE SE MUEVE CON LA FRACCION: eso es el «desglosado» de la barra.
        largas = [x for x in modulo.TAREAS
                  if len((modulo.PUBLICO[x["id"]].get("fases") or [])) > 1]
        tid = largas[0]["id"]
        fases = modulo.PUBLICO[tid]["fases"]
        ok(fases[0] in modulo.publico_de(tid, 0.0),
           f"{nombre}: al empezar la tarea se dice su primera fase")
        ok(fases[-1] in modulo.publico_de(tid, 1.0),
           f"{nombre}: y al acabarla, la ultima")

        # LO QUE NO SE SABE SE TAPA, nunca se destapa.
        igual(modulo.publico_de("no_existe_esta_tarea", 0.5),
              modulo.PUBLICO_GENERICO,
              f"{nombre}: una tarea desconocida se cuenta como generica")
        ok(modulo.publico_de("no_existe_esta_tarea") == modulo.PUBLICO_GENERICO,
           f"{nombre}: y sin fraccion, igual")

    # UNA CUENTA MEDIDA MANDA SOBRE LA FASE INVENTADA.
    #
    # La fase sale de partir la fraccion en tramos, asi que «volviendo a dibujar
    # lo que no encaja» solo significa «va por el segundo tercio» -- y se vio
    # diciendolo mientras todavia MIRABA la tanda 20 de 36. Con doscientos
    # dieciseis planos delante, lo que hace falta es la cuenta.
    con_cuenta = recetas.publico_de("assets", 0.9, (34, 216))
    ok("34 de 216 planos" in con_cuenta,
       f"con unidades se ensena la cuenta de verdad: {con_cuenta!r}")
    fases_assets = recetas.PUBLICO["assets"]["fases"]
    ok(not any(f in con_cuenta for f in fases_assets),
       "y la fase inventada se calla: sobre lo medido no manda una frase")
    ok(recetas.PUBLICO["assets"]["nombre"] in con_cuenta,
       "pero el titulo se queda: sin el no se sabe de que tarea se habla")
    ok(fases_assets[-1] in recetas.publico_de("assets", 0.9),
       "sin unidades, la fase sigue mandando como siempre")

    # NADIE ENSENA «1 de 1»: ocupa una linea para decir que hay una cosa, y
    # ademas se lee como un error.
    ok(recetas.PUBLICO["assets"]["fases"][0]
       in recetas.publico_de("assets", 0.0, (0, 1)),
       "con un total de uno no se cuenta: se cuenta la fase")
    # y unidades rotas no tumban la barra
    for rotas in ((None, 3), ("x", "y"), (), (1,)):
        ok(isinstance(recetas.publico_de("assets", 0.5, rotas), str),
           f"unas unidades ilegibles {rotas!r} no revientan la frase")

    # LA UNIDAD SE DICE POR SU NOMBRE, y vive en la misma tabla que el resto de
    # lo publico: dos tablas se desincronizan en cuanto alguien anade un paso.
    for tid in ("assets", "callouts", "render", "piezas"):
        ok(bool((recetas.PUBLICO.get(tid) or {}).get("unidad")),
           f"{tid} dice en que unidad cuenta")


class _CtxSinProyecto:
    """Lo justo para `_tramos_por_tiempo`: un proyecto sin ninguna version.

    Lo demas que toca esa funcion va sustituido en la prueba; esto solo tiene
    que hacer que la lectura del brief devuelva vacio sin reventar.
    """

    class proyecto:                                           # noqa: N801
        id = "prueba_tramos"

        @staticmethod
        def version_activa(paso_id):
            return None

        @staticmethod
        def ruta_paso(paso_id, version=None, crear=False):
            return os.path.join(tempfile.gettempdir(), "tramos_que_no_existen")


def probar_el_avisador_y_los_tramos():
    """Quien escucha la barra puede ser cualquiera, y el tramo va por tiempo."""
    seccion("EL CONTADOR DE VERDAD Y EL REPARTO DE LA BARRA")
    sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "pasos"))
    import estadisticas                                       # noqa: PLC0415

    # EL AVISADOR NO PUEDE ROMPER UN PASO POR ADORNAR LA BARRA. Los pasos avisan
    # con (hechas, total) y quien escucha puede ser el servicio, el doble de una
    # suite --`lambda v, m="": v`, dos argumentos-- o nada.
    recogido = []
    de_tres = estadisticas.avisador(
        lambda f, m="", u=None: recogido.append(("tres", f, m, u)))
    de_dos = estadisticas.avisador(lambda v, m="": recogido.append(("dos", v, m)))
    variadic = estadisticas.avisador(lambda *a, **k: recogido.append(("var", a)))
    de_nada = estadisticas.avisador(None)

    de_tres(0.5, "hola", (34, 216))
    igual(recogido[-1], ("tres", 0.5, "hola", (34, 216)),
          "quien sabe de unidades las recibe enteras")
    de_dos(0.5, "hola", (34, 216))
    igual(recogido[-1], ("dos", 0.5, "hola"),
          "y quien no, se queda sin ellas en vez de reventar")
    variadic(0.5, "hola", (34, 216))
    igual(recogido[-1], ("var", (0.5, "hola", (34, 216))),
          "un *args cuenta como que sabe")
    antes = len(recogido)
    de_nada(0.5, "hola", (34, 216))
    igual(len(recogido), antes, "y sin nadie escuchando no pasa nada")

    # LA BARRA SE REPARTE POR TIEMPO MEDIDO. Con un tramo igual por tarea, una
    # de cuarenta y nueve segundos ocupaba lo mismo que una de treinta y cinco
    # minutos: la barra saltaba en las cortas y se clavaba en la larga.
    import app as servicio                                    # noqa: PLC0415
    tandas = [[{"id": "corta", "paso": "assets"}],
              [{"id": "larga", "paso": "assets"}]]
    medidas = {"corta": 10.0, "larga": 990.0}
    guardado = (servicio._segundos_de_tarea, servicio._esta_al_dia,
                servicio._planos_previstos)
    servicio._segundos_de_tarea = lambda ctx, tarea, *a: medidas[tarea["id"]]
    servicio._esta_al_dia = lambda ctx, tarea: False
    servicio._planos_previstos = lambda ctx: {"total": 216, "con_imagen": 216,
                                              "origen": "el plan de este video"}
    try:
        tramos = servicio._tramos_por_tiempo(_CtxSinProyecto(), tandas,
                                             "pendientes")
    finally:
        (servicio._segundos_de_tarea, servicio._esta_al_dia,
         servicio._planos_previstos) = guardado
    ok(tramos["larga"][1] > tramos["corta"][1] * 50,
       f"la tarea larga se lleva casi toda la barra: {tramos}")
    igual(round(tramos["corta"][0], 6), 0.0, "la primera arranca en cero")
    igual(round(tramos["larga"][0] + tramos["larga"][1], 6), 1.0,
          "y la ultima llega al final: la barra no se queda a medias")


def probar_el_mensaje_publico_de_una_tanda():
    """Una tanda dice por donde va DOS veces, y las dos a la vez.

    Esto es el cableado, que es lo que ninguna tabla comprueba: que el detalle
    tecnico que manda cada paso --«plano S035 - 41 de 44»-- sigue llegando
    entero al mensaje de casa, y que el publico que viaja al lado no lo lleva ni
    de refilon. Si alguien enmascarara EL MISMO mensaje en vez de mandar dos,
    esto se pondria rojo: el de casa se quedaria sin sus cifras.

    Se corre en proceso con una tarea de mentira: lo que se mira es el formato
    de lo que sale por `avisar`, no lo que hace ninguna tarea de verdad.
    """
    seccion("UNA TANDA CUENTA POR DONDE VA SIN ENSENAR LA COCINA")
    sys.path.insert(0, RAIZ_ESTUDIO)
    import app as servidor                                    # noqa: PLC0415

    class _Bitacora:
        def anotar(self, *_a, **_k):
            pass

    class _Proyecto:
        config = {}
        id = "x"

        # lo justo para que el reparto de la barra por tiempo medido
        # (`_tramos_por_tiempo`) recorra su camino de verdad en vez de caerse al
        # respaldo plano y dejar la prueba mirando otra cosa
        @staticmethod
        def version_activa(paso_id):
            return None

        @staticmethod
        def ruta_paso(paso_id, version=None, crear=False):
            return os.path.join(tempfile.gettempdir(), "tanda_que_no_existe")

        @staticmethod
        def ruta_trabajo(paso_id, crear=False):
            return os.path.join(tempfile.gettempdir(), "tanda_que_no_existe")

    class _Ctx:
        id = "x"
        bitacora = _Bitacora()
        proyecto = _Proyecto()
        estado = None

    dichos = []

    def avisar(valor, mensaje="", publico=""):
        dichos.append((float(valor or 0), mensaje, publico))

    def falsa(avisar_tarea):
        avisar_tarea(0.0, "")
        avisar_tarea(0.5, "plano S035 - 41 de 44")
        avisar_tarea(None, "AVISO: dos planos con la misma imagen")
        avisar_tarea(1.0, "44 planos listos")
        return {"resumen": "de mentira"}

    def correr(*args, **kwargs):
        del dichos[:]
        original = servidor._que_hace
        servidor._que_hace = lambda *_a, **_k: (falsa, ())
        try:
            args[0](avisar, _Ctx(), *args[1:], **kwargs)
        finally:
            servidor._que_hace = original
        return ([p for _v, _m, p in dichos], [m for _v, m, _p in dichos])

    # ---- UNA PESTANA SOLA: es lo que corre el modo editor y el repaso -------
    publicos, caseros = correr(servidor._correr_receta, "voz",
                               {"nombre": "Todo", "tareas": {}},
                               ["voz", "revision_audio"], "todo")
    ok(all(publicos), f"cada aviso lleva su mensaje publico ({publicos[:2]})")
    ok(any("S035" in m for m in caseros),
       "el mensaje de casa conserva el detalle tecnico entero")
    ok(not any("S035" in p for p in publicos),
       "y el publico no lo lleva ni de refilon")
    for frase in publicos:
        sucias = [x for x in COCINA if re.search(r"\b" + re.escape(x), frase, re.I)]
        igual(sucias, [], f"«{frase}» no nombra ninguna pieza del Estudio")
    ok(publicos[0].startswith("1 de 2 · "),
       f"y dice que tarea de cuantas: {publicos[0]!r}")
    igual(publicos[-1], servidor.PUBLICO_LISTO,
          "al acabar dice «Listo» y no el recuento de tareas del motor")

    # LA FRASE SE MUEVE DENTRO DE LA TAREA --eso es el «desglosado»-- y un aviso
    # SIN fraccion no la devuelve al principio.
    de_la_primera = [p for p in publicos if p.startswith("1 de 2 · ")]
    ok(len(set(de_la_primera)) > 1,
       f"la frase cambia mientras la tarea corre: {set(de_la_primera)}")
    a_mitad = [p for _v, m, p in dichos if "S035" in m][0]
    sin_fraccion = [p for _v, m, p in dichos if "AVISO" in m][0]
    igual(sin_fraccion, a_mitad,
          "un aviso sin fraccion deja la frase donde estaba, no la manda al "
          "principio de la tarea")

    # ---- LA TANDA ENTERA, que es la del modo light -------------------------
    # `_correr_cadena` recorre varias pestanas seguidas y reparte el tramo de la
    # barra. Si su avisador se comiera el mensaje publico --es un tercer
    # parametro con valor por defecto, o sea que caeria en silencio-- TODAS las
    # barras del modo light dirian «Trabajando...» y nada mas.
    # `pendientes` es la lista de las que SE HACEN, y es la que cuenta el
    # contador publico: en modo 'todo' son todas.
    plan = {"segundos": 20.0, "fases": [
        {"pestana": "voz", "desde": 0.0, "segundos": 10.0,
         "pendientes": ["voz", "revision_audio"],
         "tareas": [{"id": "voz"}, {"id": "revision_audio"}]},
        {"pestana": "render", "desde": 10.0, "segundos": 10.0,
         "pendientes": ["banda_sonora", "efectos", "render"],
         "tareas": [{"id": "banda_sonora"}, {"id": "efectos"}, {"id": "render"}]}]}
    publicos, caseros = correr(servidor._correr_cadena, ["voz", "render"],
                               "todo", {}, plan)
    ok(any(m.startswith("voz · ") for m in caseros),
       "el mensaje de casa lleva delante la pestana, vocabulario del motor")
    ok(not [p for p in publicos if p.startswith(("voz · ", "render · "))],
       "y el publico no: ahi la pestana no significa nada")

    # UN HUECO NO ES UN FALLO: "" quiere decir «no toques la linea», y es lo que
    # manda una pestana que acaba con la tanda a medias. Lo que no puede haber
    # es un «Listo» ahi: la barra decia que habia terminado y seguia con «3 de
    # 5», que en pantalla se lee como que ha vuelto a empezar.
    cabezas = []
    for frase in [p for p in publicos if p]:
        cabeza = frase.split(" · ")[0]
        if cabeza not in cabezas:
            cabezas.append(cabeza)
    igual(cabezas, ["1 de 5", "2 de 5", "3 de 5", "4 de 5", "5 de 5",
                    servidor.PUBLICO_LISTO],
          "el contador recorre las DOS pestanas seguidas sin reiniciarse")
    primero = publicos.index(servidor.PUBLICO_LISTO)
    ultima = max(i for i, p in enumerate(publicos) if p.startswith("5 de 5"))
    ok(primero > ultima,
       "«Listo» no sale hasta que ha pasado la ultima tarea de la tanda")
    igual(publicos[-1], servidor.PUBLICO_LISTO, "y es lo ultimo que se dice")

    # ---- Y LO QUE YA ESTA AL DIA NO SE CUENTA ------------------------------
    # Montar el MP4 de un video ya dibujado recorre once tareas y corre tres:
    # la barra decia «11 de 11» desde el primer minuto --las saltadas sumaban
    # al contador-- y llegaba al final sin haberse movido nunca.
    al_dia = {"banda_sonora", "efectos"}
    original_al_dia = servidor._esta_al_dia
    servidor._esta_al_dia = lambda _ctx, tarea: tarea["id"] in al_dia
    try:
        plan_pendiente = {"segundos": 20.0, "fases": [
            {"pestana": "voz", "desde": 0.0, "segundos": 10.0,
             "pendientes": ["voz", "revision_audio"],
             "tareas": [{"id": "voz"}, {"id": "revision_audio"}]},
            {"pestana": "render", "desde": 10.0, "segundos": 10.0,
             "pendientes": ["render"],
             "tareas": [{"id": "banda_sonora"}, {"id": "efectos"},
                        {"id": "render"}]}]}
        publicos, _caseros = correr(servidor._correr_cadena, ["voz", "render"],
                                    "pendientes", {}, plan_pendiente)
    finally:
        servidor._esta_al_dia = original_al_dia
    cabezas = []
    for frase in [p for p in publicos if p]:
        cabeza = frase.split(" · ")[0]
        if cabeza not in cabezas:
            cabezas.append(cabeza)
    igual(cabezas, ["1 de 3", "2 de 3", "3 de 3", servidor.PUBLICO_LISTO],
          "una tanda con tareas al dia cuenta SOLO las que corre")
    ok(not [p for p in publicos if p.startswith("1 de 5")],
       "y no arranca contando las saltadas como hechas")



def probar_el_reloj_de_lo_que_queda_por_hacer():
    """Una tanda «pendientes» tarda lo que queda, no lo que costo el paso entero.

    Montar el MP4 de un video con sus 302 imagenes ya dibujadas prometia 282
    minutos y duro veinte (08-09-2026, `video_referencia`): `assets` no estaba «al dia»
    --el feedback de UN plano le habia movido la firma-- asi que entraba en el
    plan con las seis horas que cuesta dibujar los 302, cuando lo que quedaba
    por dibujar era cero.

    Se mira `_fraccion_por_hacer`, que es lo que escala la estimacion, con un
    estado de mentira: lo que se comprueba es la regla, no el historial de esta
    maquina.
    """
    seccion("EL RELOJ CUENTA LO QUE QUEDA, NO EL PASO ENTERO")
    sys.path.insert(0, RAIZ_ESTUDIO)
    import app as servidor                                    # noqa: PLC0415

    class _Estado:
        def __init__(self, declaradas, obsoletas):
            self._d, self._o = declaradas, obsoletas

        def unidades_declaradas(self, _paso):
            return self._d

        def unidades_obsoletas(self, _paso):
            return self._o

    class _Ctx:
        def __init__(self, declaradas, obsoletas):
            self.estado = _Estado(declaradas, obsoletas)

    todas = [f"escena:S{n:03d}" for n in range(1, 303)]

    igual(servidor._fraccion_por_hacer(_Ctx(todas, todas), "render"), 1.0,
          "con todo obsoleto se estima el paso entero")
    ok(servidor._fraccion_por_hacer(_Ctx(todas, todas[:1]), "assets") < 0.01,
       "con una unidad de 302 por rehacer, el reloj es el de una unidad")
    ok(0 < servidor._fraccion_por_hacer(_Ctx(todas, []), "assets") < 0.01,
       "y con ninguna no baja a cero: un paso que corre tarda algo")
    igual(servidor._fraccion_por_hacer(_Ctx(todas, []), "guion"), 1.0,
          "un paso que no va por unidades no se escala")
    igual(servidor._fraccion_por_hacer(_Ctx([], []), "assets"), 1.0,
          "y sin unidades declaradas tampoco: no hay nada que repartir")

    class _Roto:
        estado = None

    igual(servidor._fraccion_por_hacer(_Roto(), "assets"), 1.0,
          "no saber repartir el reloj no puede tumbar una tanda")


def probar_que_la_barra_light_no_ensena_la_cocina():
    """Las barras del modo light leen el mensaje PUBLICO y nunca el de casa.

    Se comprueba leyendo la fuente por lo mismo que el `value` de los textarea:
    para ejecutarlo hace falta un DOM. Lo que se fija es la invariante que de
    verdad protege -- que ninguna de las barras de esa pantalla pueda caer en
    `trabajo.mensaje`, que es donde viven los ids de plano y los nombres de los
    pasos. Un enmascarado que falla tiene que fallar tapando.
    """
    seccion("LAS BARRAS DEL MODO LIGHT NO ENSENAN LA COCINA")
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "web", "app.js"),
                     encoding="utf-8").read()

    def cuerpo_de(firma):
        trozo = fuente[fuente.index(firma):]
        return trozo[:trozo.index("\n}\n") + 3]

    lector = cuerpo_de("function avancePublico(trabajo)")
    ok(".mensaje" not in lector,
       "avancePublico NO cae nunca en el mensaje de casa")
    ok("'Trabajando" in lector,
       "sin mensaje publico dice algo generico, no el de casa")

    # `barraTandaLight` es la envoltura viva (`enVivo`); quien pinta de verdad
    # -- y quien podria caerse al mensaje de casa -- es `...Ahora`.
    for firma, nombre in (("function barraTandaLightAhora(", "la barra de las tandas"),
                          ("function vistaGenerandoLight()", "la del estilo")):
        trozo = cuerpo_de(firma)
        ok("avancePublico(" in trozo, f"{nombre} lee el mensaje publico")
        ok("leerAvance(" not in trozo, f"{nombre} no lee el de casa")
    ok("tarea.publico || tarea.nombre" in cuerpo_de("function vistaGenerandoLight()"),
       "y la lista de tareas del estilo dice el nombre publico")


def probar_value_de_los_textarea():
    """Un <textarea> NO tiene atributo `value`, y eso vaciaba la pantalla.

    `h()` volcaba todos los props con setAttribute. En un <input> el atributo
    value SI pinta el campo, asi que el fallo solo salia en los textarea -- o
    sea, justo donde no se busca. La direccion de los 45 planos se guardaba
    entera en el servidor y la pantalla los pintaba en blanco, que se lee como
    «no ha generado nada».

    Esto se comprueba leyendo la fuente y no ejecutando: para ejecutarlo hace
    falta un DOM, y montar Edge para una funcion de nueve lineas cuesta mas que
    lo que protege. Lo que se fija aqui es la INVARIANTE: `value` no puede
    volver a salir por setAttribute.
    """
    seccion("EL value DE UN TEXTAREA VA POR PROPIEDAD")
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "web", "app.js"),
                     encoding="utf-8").read()
    cuerpo = fuente[fuente.index("function h(etiqueta, props"):]
    cuerpo = cuerpo[:cuerpo.index("function meter(")]
    ok("clave === 'value'" in cuerpo and "n.value =" in cuerpo,
       "h() asigna `value` como PROPIEDAD: en un textarea el atributo no "
       "existe, no da error y deja el campo vacio")
    ok(cuerpo.index("meter(n, hijos)") < cuerpo.index("n.value ="),
       "y DESPUES de meter los hijos: un <select> necesita sus <option> dentro "
       "antes de poder elegir uno")


def probar_el_gemelo_de_las_marcas_tts():
    """`sinMarcasTts` (JS) tiene que decir lo MISMO que `marcas_tts.limpiar`.

    De esa cuenta sale el reparto de las marcas de palabra entre bloques: una
    palabra de mas desplaza todo lo que va detras. Y `<spell>` es la excepcion
    que las separaba: su contenido se pega a lo que tenga al lado, sin espacio.
    En el JS se sustituia por un espacio como cualquier otra etiqueta, asi que
    «<spell>VPN</spell>s» daba DOS palabras donde Cartesia devuelve una marca.
    Medido en el video largo: 716 palabras pintadas contra 713 marcas.
    """
    seccion("EL GEMELO EN JS DE LAS MARCAS DE VOZ")
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "web", "app.js"),
                     encoding="utf-8").read()
    ok("const SPELL_TTS" in fuente,
       "el JS tiene su propio patron para <spell>")
    ok("replace(SPELL_TTS, '$1')" in fuente,
       "y lo sustituye por su CONTENIDO, no por un espacio")
    ok(fuente.index("replace(SPELL_TTS") < fuente.index("replace(MARCA_TTS"),
       "y antes que el patron general, o el general se lo comeria primero")

    # Y el backend, que es el que manda: la misma frase, una sola palabra.
    sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "pasos"))
    import marcas_tts                                        # noqa: PLC0415
    frase = ('Commercial <spell>VPN</spell>s, on <spell>MEGA</spell>.'
             '<break time="400ms"/> Fin.')
    igual(marcas_tts.limpiar(frase), "Commercial VPNs, on MEGA. Fin.",
          "el backend pega el contenido de <spell> a lo que tiene al lado")
    igual(marcas_tts.contar_palabras(frase), 5,
          "y por eso cuenta cinco palabras, no siete")


def probar_que_la_receta_aplica():
    """Una receta que propone y no guarda es una factura sin resultado.

    Tres tareas de la tuberia PROPONEN y la pantalla las guarda con un segundo
    clic: las menciones, las cartelas y el plan de rotulos. En una tanda de una
    tirada no hay nadie para dar ese segundo clic, asi que el ejecutor tiene que
    pedir que se apliquen. Si alguien anade una tarea que propone y se olvida,
    esto lo dice aqui y no en la factura del mes.

    Se mira en proceso y no por HTTP porque lo que se comprueba es el CABLEADO
    -- que argumentos recibe cada tarea --, no una respuesta.
    """
    seccion("LA RECETA APLICA LO QUE PROPONE")
    sys.path.insert(0, RAIZ_ESTUDIO)
    import app as servidor                                  # noqa: PLC0415

    class _Estado:
        def params(self, _paso):
            return {}

    class _Ctx:
        id = "x"
        estado = _Estado()

    ctx = _Ctx()
    for tarea in ("plan_cartelas",):
        _funcion, args = servidor._que_hace(tarea, ctx, {})
        ok(args and args[-1] is True,
           f"{tarea}: la receta pide APLICAR lo propuesto ({args[-1]!r})")

    # Y las que son un paso del grafo pasan por _un_paso, que es lo que las hace
    # rehacer SOLO lo sucio: con unidades=None se rehace el paso entero, y en
    # assets eso son las 49 imagenes otra vez.
    import inspect                                          # noqa: PLC0415
    fuente = inspect.getsource(servidor._que_hace)
    ok("_correr_paso" not in fuente,
       "ninguna tarea de paso llama a _correr_paso a pelo: todas por _un_paso")
    ok("_plan_de_ejecucion" in inspect.getsource(servidor._un_paso),
       "y _un_paso pide las unidades al mismo sitio que el boton de ejecutar")


def probar_que_la_api_esta_documentada():
    """docs/API.md tiene que nombrar TODAS las rutas que sirve app.py.

    La cabecera de `web/app.js` llevaba una lista a mano y se quedo en 52 de 126
    endpoints: nadie la completaba al anadir uno, y una lista a medias de una API
    es peor que ninguna porque parece completa. La lista se movio a docs/API.md,
    generada desde el propio `app.py`, y esto es lo que impide que se quede vieja
    otra vez -- que es lo unico que hace falta para que siga sirviendo.
    """
    print("\n[api] docs/API.md nombra todas las rutas que sirve app.py")
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "app.py"), encoding="utf-8").read()
    doc = io.open(os.path.join(RAIZ_ESTUDIO, "docs", "API.md"), encoding="utf-8").read()
    servidas = {(m.group(1).upper(), m.group(2)) for m in
                re.finditer(r'@app\.(get|post|put|delete|patch)\("([^"]+)"', fuente)}
    faltan = sorted(f"{v} {r}" for v, r in servidas if f"`{r}`" not in doc)
    ok(not faltan,
       f"todas las rutas ({len(servidas)}) estan en docs/API.md"
       + (f" -- FALTAN: {', '.join(faltan[:6])}" if faltan else ""))
    # y al reves: una ruta documentada que ya no existe manda a buscar algo que
    # no esta, que es la otra forma de que una referencia deje de servir
    rutas = {r for _, r in servidas}
    sobran = sorted(m.group(1) for m in re.finditer(r"^\| `[A-Z]+` \| `([^`]+)`", doc, re.M)
                    if m.group(1) not in rutas)
    ok(not sobran,
       "y ninguna documentada ha dejado de existir"
       + (f" -- SOBRAN: {', '.join(sobran[:6])}" if sobran else ""))


def probar_que_las_llamadas_a_los_pasos_encajan():
    """Nadie le pasa a un paso un argumento que su firma no tiene.

    EL FALLO QUE ARREGLA, visto el 24-08-2026 al generar un preset:

        generar_guia() got an unexpected keyword argument 'indicaciones'

    `app.py` le pasaba `indicaciones=` a `estilo.generar_guia` desde el modo
    light --con un comentario explicando muy bien para que servia-- y la firma
    no lo recibia. No fallaba a medias: fallaba ENTERO, y solo por el camino de
    «estilo desde una URL mas una frase», que es la forma normal de pedir un
    canal.

    Python no comprueba una firma hasta que la llamada ocurre, y aqui las
    llamadas ocurren dentro de un trabajo en segundo plano: o se pulsa ESE boton
    o no se entera nadie. Esto lo comprueba sin pulsarlo, leyendo el AST.
    """
    print("\n[api] ninguna llamada a un paso pasa un argumento que no existe")
    sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "herramientas"))
    import firmas_py

    conocidos = firmas_py.modulos()
    ok(len(conocidos) > 20, f"se han cargado los modulos de pasos y nucleo: "
                            f"{len(conocidos)}")

    hallazgos = []
    for relativo in firmas_py.FICHEROS:
        ruta = os.path.join(RAIZ_ESTUDIO, relativo.replace("/", os.sep))
        if not os.path.exists(ruta):
            continue
        arbol = ast.parse(io.open(ruta, encoding="utf-8").read(), filename=ruta)
        rastreador = firmas_py.Rastreador(relativo, conocidos)
        rastreador.visit(arbol)
        hallazgos.extend(rastreador.hallazgos)
    ok(not hallazgos,
       "ninguna llamada sobra un argumento"
       + ("" if not hallazgos else " -- " + "; ".join(
           f"{h['fichero']}:{h['linea']} {h['llamada']}({h['sobra']}=)"
           for h in hallazgos[:5])))

    # Y QUE EL DETECTOR DETECTE. Un comprobador que siempre dice que si es peor
    # que ninguno: da la tranquilidad sin dar la comprobacion.
    falso = ast.parse(
        "def f():\n"
        "    estilo = _estilo()\n"
        "    estilo.generar_guia(p, r, meloinvento=1)\n")
    rastreador = firmas_py.Rastreador("(inventado)", conocidos)
    rastreador.visit(falso)
    igual(len(rastreador.hallazgos), 1,
          "y con un argumento inventado, lo caza: si no, este verde no vale nada")
    if rastreador.hallazgos:
        igual(rastreador.hallazgos[0]["sobra"], "meloinvento",
              "diciendo cual sobra")

    # los tres modos de nombrar un modulo que se usan en el repo
    for fuente, comose in (
            ("from pasos import estilo\nestilo.generar_guia(p, r, xx=1)",
             "importado directamente"),
            ("def f():\n    e = _estilo()\n    e.generar_guia(p, r, xx=1)",
             "sacado de _estilo()"),
            ("PASOS_MODULOS.estilo.generar_guia(p, r, xx=1)",
             "por PASOS_MODULOS")):
        r = firmas_py.Rastreador("(inventado)", conocidos)
        r.visit(ast.parse(fuente))
        ok(len(r.hallazgos) == 1, f"reconoce un modulo {comose}")

    # y NO se inventa fallos donde no los hay
    r = firmas_py.Rastreador("(inventado)", conocidos)
    r.visit(ast.parse("def f():\n    e = _estilo()\n"
                      "    e.generar_guia(p, r, peticion='x', indicaciones='y')"))
    igual(len(r.hallazgos), 0,
          "y los argumentos que SI existen no se marcan")


def probar_que_no_falta_ningun_nombre_en_el_servidor():
    """Ni el Python llama a nada que no exista.

    EL FALLO QUE ARREGLA, visto el 07-09-2026: el redactor recien estrenado se
    caia entero con

        NameError: name '_exigir_pasos' is not defined

    `app.py:_redactor()` llamaba a un ayudante que no existe en ese fichero. Y
    esta suite pasaba en verde --748 comprobaciones-- porque para llegar a esa
    linea hay que LANZAR el trabajo, y el trabajo tarda veinte minutos y cuesta
    una llamada al CLI. Se descubrio lanzandolo: las dos copias caidas en el
    primer segundo, con la tarde por delante.

    Es el gemelo de la comprobacion de arriba: aquella mira `web/app.js` porque
    en el navegador un nombre que falta solo revienta cuando alguien pinta esa
    pantalla; esta mira el Python porque en el servidor solo revienta cuando
    alguien pulsa ese boton. La misma clase de agujero, los dos lados.
    """
    print("\n[api] el Python del estudio no usa ningun nombre sin declarar")
    sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "herramientas"))
    import indefinidos_py

    sueltos = indefinidos_py.revisar()
    ok(len(indefinidos_py.FICHEROS) > 40,
       f"se miran todos los ficheros, no uno: {len(indefinidos_py.FICHEROS)}")
    ok(not sueltos,
       "ningun nombre sin declarar"
       + ("" if not sueltos else " -- " + "; ".join(
           f"{n} ({s[0][0]}:{s[0][1]})" for n, s in sorted(sueltos.items())[:6])))

    # Y QUE EL DETECTOR DETECTE, con el fallo DE VERDAD y no con uno de mentira:
    # un comprobador que siempre dice que si da la tranquilidad sin dar la
    # comprobacion. Se escribe el `_redactor()` tal y como estaba.
    roto = os.path.join(tempfile.gettempdir(), "app_con_nombre_suelto.py")
    io.open(roto, "w", encoding="utf-8").write(
        "def _redactor():\n"
        "    _exigir_pasos()\n"
        "    return PASOS_MODULOS.redactor\n"
        "PASOS_MODULOS = None\n")
    try:
        cazados = indefinidos_py.revisar([os.path.basename(roto)],
                                         raiz=tempfile.gettempdir())
        ok("_exigir_pasos" in cazados,
           "y con el fallo del 07-09 delante, lo caza")
        ok("PASOS_MODULOS" not in cazados,
           "sin marcar lo que SI se declara mas abajo: en Python el orden del "
           "fichero no manda dentro de una funcion")
    finally:
        os.remove(roto)

    # y no se inventa fallos con lo que el interprete pone solo
    limpio = os.path.join(tempfile.gettempdir(), "app_limpio.py")
    io.open(limpio, "w", encoding="utf-8").write(
        "import os\n"
        "def f(a, *resto, **kw):\n"
        "    b = [x for x in resto if x]\n"
        "    try:\n"
        "        with open(a) as m:\n"
        "            return os.path.join(m.name, str(b), __file__, kw['x'])\n"
        "    except OSError as fallo:\n"
        "        return str(fallo)\n")
    try:
        igual(indefinidos_py.revisar([os.path.basename(limpio)],
                                     raiz=tempfile.gettempdir()), {},
              "y parametros, comprensiones, `with`, `except as` y `__file__` "
              "no son nombres sueltos")
    finally:
        os.remove(limpio)


def probar_que_no_falta_ningun_nombre_en_la_pantalla():
    """web/app.js no usa ningun nombre que nadie declara.

    EL FALLO QUE ARREGLA, visto el 24-08-2026 al pintar el modo light:

        VELOCIDADES is not defined

    Retirando el eje de idiomas se llevo por delante el bloque de constantes de
    la voz --las cuatro listas y los dos ayudantes de emociones-- porque estaba
    pegado a lo que si sobraba. `node --check` valida SINTAXIS, no referencias:
    el fichero seguia siendo JavaScript valido perfecto, y el fallo solo aparece
    **cuando alguien pinta esa pantalla**. Los paneles de Voz y el paso de voz
    del modo light morian; el resto de la interfaz, tan tranquila.

    El comprobador ya existia y lo estaba diciendo, enterrado entre 69 nombres
    de los que 60 eran mentira (`const` 2.014 veces). Un informe que grita
    sesenta veces no lo lee nadie. Se afino hasta dejarlo en cero y aqui se
    convierte en una comprobacion, que es lo unico que no depende de que alguien
    se acuerde de mirarlo.
    """
    print("\n[api] web/app.js no usa ningun nombre sin declarar")
    ruta_herramientas = os.path.join(RAIZ_ESTUDIO, "herramientas")
    if ruta_herramientas not in sys.path:
        sys.path.insert(0, ruta_herramientas)
    import indefinidos_js

    sueltos = indefinidos_js.revisar()
    ok(not sueltos,
       "ningun nombre sin declarar"
       + ("" if not sueltos else " -- " + "; ".join(
           f"{n} (lineas {ls[:3]})" for n, ls in sorted(sueltos.items())[:6])))
    igual(indefinidos_js.CONOCIDOS, {},
          "y sin excepciones escritas a mano: una lista de excepciones es un "
          "sitio donde esconderse")

    # Y QUE EL DETECTOR DETECTE, con el fallo de verdad. Un comprobador que
    # siempre dice que si da la tranquilidad sin dar la comprobacion.
    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "web", "app.js"),
                     encoding="utf-8").read()
    declaracion = "const VELOCIDADES = ['slowest', 'slow', 'normal', 'fast', 'fastest'];"
    ok(declaracion in fuente,
       "el bloque de constantes de la voz sigue en su sitio")
    if declaracion in fuente:
        roto = os.path.join(tempfile.gettempdir(), "app_sin_velocidades.js")
        io.open(roto, "w", encoding="utf-8").write(fuente.replace(declaracion, ""))
        try:
            sueltos = indefinidos_js.revisar(roto)
            ok("VELOCIDADES" in sueltos,
               "y quitandolo a proposito, el detector lo caza")
        finally:
            os.remove(roto)


def probar_el_reloj_de_un_trabajo():
    """El reloj de un trabajo NO se hereda del anterior.

    EL FALLO QUE ARREGLA, visto el 24-08-2026: se cambio la voz de un preset y
    despues se lanzo una regeneracion del estilo, y la pantalla dijo «3m 51s»
    recien pulsada. `seguirTrabajo` conservaba el arranque que hubiera en la
    ranura del paso -- que es lo correcto al RETOMAR uno que venia corriendo --
    sin comprobar que fuera del MISMO trabajo. En el modo light se nota mas
    porque `preset_light` es UNA ranura fija por la que pasan todos sus
    trabajos, uno detras de otro.

    ESTA SE CORRE DE VERDAD, en node, y no leyendo el fichero: aqui lo que se
    prueba es una CUENTA, y una cuenta se comprueba haciendola. Las demas
    comprobaciones de JS de esta suite miran el texto porque lo que vigilan es
    que dos sitios digan lo mismo, que es otra cosa.
    """
    seccion("EL RELOJ DE UN TRABAJO NO SE HEREDA DEL ANTERIOR")
    nodo = shutil.which("node")
    if not nodo:
        print("      (sin node: no se puede correr el JS; se salta)")
        return

    fuente = io.open(os.path.join(RAIZ_ESTUDIO, "web", "app.js"),
                     encoding="utf-8").read()
    desde = fuente.find("function arranqueDe(")
    hasta = fuente.find("function seguirTrabajo(")
    ok(0 <= desde < hasta,
       "`arranqueDe` existe y va delante de `seguirTrabajo`")
    if not (0 <= desde < hasta):
        return

    guion = fuente[desde:hasta] + r"""
const AHORA = Date.now();
const ANTES = AHORA - 231000;
const salida = {
  otro:      arranqueDe({id: 'viejo', inicio: ANTES, estado: 'listo'}, 'nuevo'),
  mismo:     arranqueDe({id: 'a', inicio: ANTES, estado: 'ejecutando'}, 'a'),
  espera:    arranqueDe({id: null, inicio: ANTES, estado: 'pendiente'}, 'a'),
  vacio:     arranqueDe(undefined, 'a'),
  sin_reloj: arranqueDe({id: 'a'}, 'a'),
  ahora: AHORA, antes: ANTES,
};
console.log(JSON.stringify(salida));
"""
    ruta = os.path.join(tempfile.gettempdir(), "prueba_reloj_trabajo.js")
    io.open(ruta, "w", encoding="utf-8").write(guion)
    try:
        corrido = subprocess.run([nodo, ruta], capture_output=True, text=True,
                                 timeout=60)
    finally:
        try:
            os.remove(ruta)
        except OSError:
            pass
    if corrido.returncode != 0:
        ok(False, f"el JS no ha corrido: {(corrido.stderr or '')[:200]}")
        return
    r = json.loads(corrido.stdout.strip().splitlines()[-1])

    ok(r["otro"] >= r["ahora"],
       "un trabajo NUEVO arranca su reloj de cero: heredarlo hacia que una "
       "regeneracion recien pulsada dijera «3m 51s»")
    igual(r["mismo"], r["antes"],
          "el MISMO trabajo conserva el suyo: sin eso, recargar la pagina a "
          "media ejecucion diria «lleva 3s» de un paso de media hora")
    igual(r["espera"], r["antes"],
          "y la espera del clic (id: null) tambien, que es lo honesto: lo que "
          "llevas esperando es desde que pulsaste")
    ok(r["vacio"] >= r["ahora"], "sin nada previo, ahora")
    ok(r["sin_reloj"] >= r["ahora"], "y con id pero sin reloj, ahora")

    # Y QUE NADIE VUELVA A LEER `inicio` A PELO en el sitio que lo decide: el
    # fallo era exactamente eso, un `|| Date.now()` sin comparar el id.
    cuerpo = fuente[hasta:hasta + 900]
    ok("arranqueDe(APP.trabajos[paso], tid)" in cuerpo,
       "y `seguirTrabajo` lo decide por ahi, no con un `|| Date.now()` suelto")


def probar_modo_light(cliente):
    """El modo light: la galeria de presets de canal y su plan de generacion.

    NO se lanza ninguna generacion de verdad: eso baja un video, llama al CLI y
    paga imagenes. Lo que se prueba aqui es todo lo que decide ANTES de gastar
    -- que el encargo se valida, que el plan sale con sus tiempos y sus tandas, y
    que editar y borrar hacen lo que dicen -- que es justo donde un fallo se
    lleva por delante diez minutos y cuatro imagenes.
    """
    seccion("MODO LIGHT: LA GALERIA DE PRESETS DE CANAL")

    respuesta, datos = cliente.get("/api/presets-light")
    igual(respuesta.status_code, 200, "la galeria contesta 200")
    ok(isinstance(datos.get("presets"), list), "trae la lista de presets")
    ok(any(i.get("valor") == "es" for i in (datos.get("idiomas") or [])),
       "trae el catalogo de idiomas")
    igual(sorted(datos.get("partes") or {}), ["estilo", "tono", "voz"],
          "las partes que se pueden rehacer son TRES")
    ok(len(datos.get("tareas") or []) >= 5, "trae la tabla de tareas")

    # ---- el encargo se valida ANTES de crear ningun taller
    base = {"nombre": "Canal de prueba", "idioma": "es",
            "estilo_imagenes": ["x.png", "y.png"],
            "estilo_prompt": "dibujo plano de linea gruesa",
            "tono_prompt": "serio pero cercano, sin dramatismo",
            "voz_prompt": "grave, pausada, sin sonar a locutor"}
    for cambio, etiqueta in (
            ({"nombre": ""}, "sin nombre"),
            ({"idioma": "kl"}, "con un idioma que no existe"),
            # EL ESTILO SON IMAGENES: sin ellas no hay de donde copiar, y lo
            # escrito solo acompana. Un parrafo suelto se lo inventa todo.
            ({"estilo_imagenes": []}, "sin imagenes para el estilo"),
            ({"voz_prompt": ""}, "sin voz"),
            ({"tono_prompt": ""}, "sin tono"),
            ({"tono_prompt": "cor"}, "con un tono de tres letras")):
        respuesta, datos = cliente.post("/api/presets-light/plan",
                                        dict(base, **cambio))
        igual(respuesta.status_code, 400, f"un encargo {etiqueta} da 400")

    # ---- el plan: tandas, tiempos y paralelismo
    respuesta, datos = cliente.post("/api/presets-light/plan", base)
    igual(respuesta.status_code, 200, "un encargo completo devuelve su plan")
    plan = datos.get("plan") or {}
    tandas = plan.get("tandas") or []
    ids = [[t["id"] for t in tanda] for tanda in tandas]
    ok(plan.get("segundos", 0) > 0, "el plan dice cuanto va a tardar")
    ok(any(len(tanda) > 1 for tanda in ids),
       f"algo corre en paralelo (tandas: {ids})")
    primera = ids[0] if ids else []
    ok("tono" in primera and "voz" in primera,
       "el tono y la voz arrancan a la vez que la guia, que es la tarea larga "
       f"(primera tanda: {primera})")
    planas = [t for tanda in ids for t in tanda]
    ok(planas.index("guia") < planas.index("referencias"),
       "la guia escrita va antes de dibujar nada")
    ok(planas.index("referencias") < planas.index("muestra"),
       "las muestras van las ultimas: se dibujan con el estilo ya montado")
    # NO HAY CAMINO DE VIDEO: ni se baja nada ni se eligen fotogramas
    sueltas = [x["id"] for x in (plan.get("tareas") or [])]
    ok("frames" not in sueltas and "eleccion" not in sueltas,
       f"no se extraen ni se eligen fotogramas de ningun video ({sueltas})")
    ok("personajes" not in sueltas,
       f"y no hay personajes del canal que dibujar ({sueltas})")

    # ---- un preset de canal guardado a mano se ve en la galeria y se edita
    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "canal", "nombre": "Canal light",
        "datos": {"guion": {"idiomas_salida": ["es"],
                            "instrucciones": "Habla claro y sin adornos."},
                  "voz": {"voz_id": "v-de-prueba", "idioma": "es",
                          "velocidad": "normal"},
                  "origen": {"tono_prompt": "serio pero cercano",
                             "estilo_prompt": "dibujo plano"}}})
    igual(respuesta.status_code, 200, "guardar un preset de canal responde 200")
    pid_preset = (datos.get("preset") or {}).get("id") or ""

    respuesta, datos = cliente.get("/api/presets-light")
    ficha = next((f for f in (datos.get("presets") or [])
                  if f.get("id") == pid_preset), None)
    ok(ficha is not None, "el preset de canal sale en la galeria light")
    if ficha:
        igual(ficha.get("idioma"), "es", "la tarjeta sabe su idioma")
        ok(2 <= len(ficha.get("vinetas") or []) <= 5,
           f"la tarjeta trae de dos a cinco viñetas ({ficha.get('vinetas')})")

    respuesta, datos = cliente.put(f"/api/presets-light/{pid_preset}",
                                   {"nombre": "Canal light EN", "idioma": "en"})
    igual(respuesta.status_code, 200, "editar nombre e idioma responde 200")
    nueva = datos.get("preset") or {}
    igual(nueva.get("idioma"), "en", "el idioma cambia sin regenerar nada")
    igual(nueva.get("nombre"), "Canal light EN", "y el nombre tambien")
    igual(((nueva.get("datos") or {}).get("voz") or {}).get("idioma"), "en",
          "y arrastra el idioma de la voz, que es el que locuta")

    respuesta, datos = cliente.put(f"/api/presets-light/{pid_preset}", {"idioma": "kl"})
    igual(respuesta.status_code, 400, "un idioma que no existe da 400 al editar")

    # rehacer una parte de un preset SIN taller se dice, no se inventa uno
    respuesta, datos = cliente.post(
        f"/api/presets-light/{pid_preset}/regenerar",
        {"parte": "tono", "peticion": "menos solemne"})
    igual(respuesta.status_code, 409,
          "rehacer una parte sin taller da 409 y lo explica")
    respuesta, datos = cliente.post(
        f"/api/presets-light/{pid_preset}/regenerar", {"parte": "inventada"})
    igual(respuesta.status_code, 400, "una parte que no existe da 400")

    respuesta, datos = cliente.delete(f"/api/presets-light/{pid_preset}")
    igual(respuesta.status_code, 200, "borrar el preset responde 200")
    respuesta, datos = cliente.get("/api/presets-light")
    ok(not any(f.get("id") == pid_preset for f in (datos.get("presets") or [])),
       "y desaparece de la galeria")


def probar_video_light(cliente):
    """De un ESTILO a un video: crear el proyecto, planificar y decir el coste.

    Aqui NO se genera nada: generar un video son diez minutos y un dolar largo.
    Lo que se prueba es todo lo que decide antes de gastar -- que el proyecto
    nace con el estilo puesto y visible en la lista, que la direccion viene
    encendida en un video que nunca ha dibujado nada, que el plan dice cuanto
    cuesta ANTES de pulsar y que el guion no esta bloqueado por no tener video
    de referencia --, que es donde un fallo se lleva por delante la tanda entera.
    """
    seccion("MODO LIGHT: DE UN ESTILO A UN VIDEO")

    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "canal", "nombre": "Estilo para vídeo",
        # sin bloque 'estilo': un preset de estilo grafico necesita al menos
        # tres fotogramas de referencia y aqui no se extrae ningun video. Lo que
        # se prueba es el camino del VIDEO, no el del estilo.
        "datos": {"guion": {"idioma_salida": "es",
                            "instrucciones": "Habla claro y sin adornos."},
                  "voz": {"voz_id": "v-de-prueba", "idioma": "es",
                          "velocidad": "normal"},
                  "origen": {"tono_prompt": "serio", "estilo_prompt": "plano"}}})
    igual(respuesta.status_code, 200, "hay un estilo con el que hacer el vídeo")
    estilo_id = (datos.get("preset") or {}).get("id") or ""

    # ---- crear el video: los cuatro campos de la pantalla en un POST
    respuesta, creado = cliente.post(f"/api/presets-light/{estilo_id}/video", {
        "nombre": "El hackeo del banco",
        "duracion_objetivo_s": 240,
        # EL MATERIAL es un texto y nada mas: ni enlaces que resolver ni
        # varias cajas. Las INDICACIONES van aparte -- el material son los
        # hechos y las indicaciones son como contarlos.
        "material": "La empresa reconoció el acceso en 2025.\n\n"
                    "El informe se publicó tres meses después.",
        "indicaciones": "Céntrate en el mecanismo, no en las personas.",
        # LAS LLAMADAS A LA ACCION SE DECIDEN POR VIDEO, no en el estilo
        "cta": {"cta_final": {"puesto": True,
                              "texto": "que se suscriba y vea otro vídeo"}}})
    igual(respuesta.status_code, 201, f"crear el vídeo responde 201: {creado}")
    vid = (creado.get("proyecto") or {}).get("id") or ""
    ok(bool(vid), "y devuelve el proyecto")
    igual((creado.get("estilo") or {}).get("id"), estilo_id,
          "diciendo de qué estilo salió")

    # ES UN VIDEO Y SE VE EN LA LISTA. Un taller se esconde porque no es de
    # nadie; un video se hace por donde se quiera y sigue siendo un video.
    respuesta, lista = cliente.get("/api/proyectos")
    ok(any(p["id"] == vid for p in lista["proyectos"]),
       "el vídeo del modo light SALE en la lista de proyectos")

    # ---- lo que la pantalla ya decidio esta escrito en los params de siempre
    respuesta, brief = cliente.get(f"/api/proyectos/{vid}/pasos/brief")
    igual((brief.get("params") or {}).get("duracion_objetivo_s"), 240,
          "la duración va al brief")
    # EL MATERIAL VA AL PASO «ORIGEN», que es donde vive con su version y su
    # firma: cambiarlo deja obsoleto el guion y todo lo que cuelga.
    respuesta, origen = cliente.get(f"/api/proyectos/{vid}/pasos/ingesta")
    par_origen = origen.get("params") or {}
    ok("reconoció el acceso" in (par_origen.get("texto") or ""),
       "el material va al paso Origen")
    respuesta, guion = cliente.get(f"/api/proyectos/{vid}/pasos/guion")
    params = guion.get("params") or {}
    # LAS INDICACIONES llegan al GUIONISTA. Van al cajon que existe para eso y
    # no mezcladas con el material: los hechos son una cosa y como contarlos es
    # otra, y un guionista que recibe «sin indicaciones adicionales» mientras
    # alguien pedia algo escribe un guion que no hace caso a nadie.
    igual(params.get("prompt_general"),
          "Céntrate en el mecanismo, no en las personas.",
          "y las indicaciones llegan al guionista")
    igual(((params.get("cta") or {}).get("cta_final") or {}).get("puesto"), True,
          "y la llamada a la acción de este vídeo, que se decide por vídeo")
    igual((brief.get("params") or {}).get("instrucciones"),
          "Habla claro y sin adornos.",
          "y la guía de tono del estilo NO se machaca: el modo light no tiene "
          "un campo «de qué va», el material es el encargo")

    # ---- el guion NO esta bloqueado por no tener video de referencia
    respuesta, pasos = cliente.get(f"/api/proyectos/{vid}/pasos")
    por_id = {p["id"]: p for p in pasos["pasos"]}
    igual(por_id["ingesta"]["estado"], "pendiente",
          "el origen queda pendiente hasta que se lance: el material ya está "
          "escrito en sus params, pero una entrada del grafo se ejecuta")

    # ---- el plan: que se va a hacer, cuanto tarda y cuanto cuesta
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar?tanda=guion")
    igual(respuesta.status_code, 200, "el plan de la tanda del guion responde 200")
    # CON EL ORIGEN DELANTE, porque la ingesta no ha corrido nunca: sin ella
    # el brief sigue bloqueado y la tanda contestaba «falta ejecutar ingesta»
    # al pulsar «Generar el guion» en un vídeo recién creado (ver _con_origen).
    igual(plan["pestanas"], ["origen", "guion"],
          "la tanda del guion se lleva el origen mientras la ingesta esté sin correr")
    tareas = [t["id"] for f in plan["fases"] for t in f["tareas"]]
    ok("ingesta" in tareas, f"con la ingesta dentro, que es lo que desbloquea el brief ({tareas})")
    ok("guion" in tareas, f"con la redacción dentro ({tareas})")
    ok("fuentes" not in tareas and "integraciones" not in tareas,
       f"y sin documentalista ni menciones: ya no existen ({tareas})")
    ok(plan["segundos"] > 0, "dice cuánto va a tardar")
    igual(plan["coste"]["imagenes"], 0,
          "la tanda del guion no paga ninguna imagen")

    # LAS TRES PIEZAS DE LA CADENA, con la frontera donde toca: guion y audio;
    # las IMAGENES, que solo dependen de esos dos; y el MONTAJE, que es todo lo
    # que se pone encima. `callouts` --rotulos, cartelas y movimiento-- es del
    # montaje: en Imagenes se mira el dibujo y nada mas.
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar?tanda=video")
    igual(plan["pestanas"], ["video"],
          "la tanda de las imágenes se queda en su pestaña")
    tareas = [t["id"] for f in plan["fases"] for t in f["tareas"]]
    ok("callouts" not in tareas,
       f"y NO dibuja los rótulos: eso es del montaje ({tareas})")
    ok("direccion" in tareas,
       f"y la dirección viene ENCENDIDA en un vídeo del modo light ({tareas})")
    ok(plan["coste"]["imagenes"] > 0,
       f"esta sí paga imágenes: {plan['coste']['imagenes']}")
    ok(plan["coste"]["usd_total"] > 0,
       f"y lo dice en dólares ANTES de pulsar: {plan['coste']['usd_total']} $")
    igual(plan["coste"]["planos"]["origen"], "estimado por la duración y el ritmo",
          "sin plan cortado todavía, los planos se estiman y se dice")

    # ---- MONTAR TIENE QUE PODER PONER AL DIA LOS ROTULOS -------------------
    #
    # La tanda del MP4 llevaba solo la pestana del render, asi que montaba con
    # los rotulos de la pasada anterior. Rehacer un plano suelto deja `callouts`
    # obsoleto --su movimiento y su capa son de ESE dibujo-- y el render se
    # plantaba con «S007: el paso callouts no dejo movimiento», que manda a
    # mirar el render cuando lo que falta es el paso de antes.
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar?tanda=render")
    tareas = [t["id"] for f in plan["fases"] for t in f["tareas"]]
    ok("callouts" in tareas,
       f"montar el vídeo alcanza a los rótulos, que es de donde salen los "
       f"movimientos que el render exige: {tareas}")
    ok("render" in tareas, "y al render, claro")

    # ---- y en un proyecto NUEVO del modo editor tambien: nunca ha pagado una
    # imagen, asi que encenderla no repaga nada. Donde sigue
    # apagada es en un video con planos hechos: ver probar_recetas.
    respuesta, otro = cliente.post("/api/proyectos", {"nombre": "Editor normal"})
    otro_id = (otro.get("proyecto") or {}).get("id") or ""
    respuesta, plan = cliente.get(f"/api/proyectos/{otro_id}/generar?tanda=video")
    tareas = [t["id"] for f in plan["fases"] for t in f["tareas"]]
    ok("direccion" in tareas,
       "en un vídeo nuevo del modo editor la dirección viene encendida: "
       "todavía no hay ninguna imagen que repagar")
    cliente.delete(f"/api/proyectos/{otro_id}")

    # ---- las cinco pestanas de una tirada: PENDIENTE 28
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar")
    igual(plan["pestanas"], ["origen", "guion", "voz", "video", "render"],
          "sin tanda ni pestañas, las cinco: la tirada de punta a punta")

    respuesta, _ = cliente.get(f"/api/proyectos/{vid}/generar?tanda=inventada")
    igual(respuesta.status_code, 400, "una tanda que no existe da 400")
    respuesta, _ = cliente.get(f"/api/proyectos/{vid}/generar?pestanas=no_existe")
    igual(respuesta.status_code, 404, "una pestaña que no existe da 404")
    respuesta, _ = cliente.post(f"/api/proyectos/{vid}/generar", {"modo": "raro"})
    igual(respuesta.status_code, 400, "un modo inventado da 400")

    # EL ORDEN LO PONE EL PIPELINE, no el orden en que lleguen: pedir
    # «render, video» renderizaria clips de planos que no existen.
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar?pestanas=render,video")
    igual(plan["pestanas"], ["video", "render"],
          "las pestañas se reordenan al orden del pipeline")

    # ---- reescribir un bloque del guion SIN tocar el audio
    respuesta, _ = cliente.post(f"/api/proyectos/{vid}/guion/bloques/reescribir",
                                {"peticion": "mas corto"})
    igual(respuesta.status_code, 400, "sin decir qué bloque, 400")
    respuesta, _ = cliente.post(f"/api/proyectos/{vid}/guion/bloques/reescribir",
                                {"bloque": "B001"})
    igual(respuesta.status_code, 400, "y sin decir qué cambiar, también")

    # ---- el material vive en el paso «Origen» y se lee de sus params
    respuesta, origen = cliente.get(f"/api/proyectos/{vid}/pasos/ingesta")
    igual(respuesta.status_code, 200, "el material se lee del paso Origen")
    texto = (origen.get("params") or {}).get("texto") or ""
    ok("reconoció el acceso" in texto, "y trae lo que se escribió")
    ok("informe se publicó" in texto,
       "los dos párrafos, no solo el primero")

    # NO HAY SEGUNDO CAMINO. Un enlace pegado en el material es texto y nada
    # mas: no se baja, no se abre y no se busca. Es lo que hace que el material
    # sea siempre lo que se ve en la caja. El origen SI va en la tanda mientras
    # la ingesta no haya corrido --es el paso que versiona ese texto y
    # desbloquea el brief--, pero su unica tarea es la ingesta del material
    # escrito: ni documentalista ni descarga.
    respuesta, plan = cliente.get(f"/api/proyectos/{vid}/generar?tanda=guion")
    igual(plan["pestanas"], ["origen", "guion"],
          "la tanda del guion lleva el origen delante mientras la ingesta esté "
          "sin correr")
    tareas_origen = [t["id"] for f in plan["fases"] if f["pestana"] == "origen"
                     for t in f["tareas"]]
    igual(tareas_origen, ["ingesta"],
          "y del origen solo entra la ingesta del material escrito: no se baja "
          "ni se busca nada")

    respuesta, _ = cliente.post("/api/presets-light/no_existe/video", {})
    igual(respuesta.status_code, 404, "un estilo que no existe da 404")

    cliente.delete(f"/api/proyectos/{vid}")
    cliente.delete(f"/api/presets-light/{estilo_id}")


def probar_planos_hechos(cliente, pid):
    """Los PNG que hay AHORA, y cuales son de este plan.

    La carpeta de trabajo conserva lo de pasadas anteriores -- es lo que permite
    retomar una tanda cortada -- asi que ahi puede haber planos que el corte de
    hoy ya no tiene. Sin decir cuales son del plan, la pantalla ensenaba un
    «S105» en un video cuyo ultimo plano es otro.
    """
    seccion("QUE PLANOS HAY, Y CUALES SON DE ESTE PLAN")
    respuesta, datos = cliente.get(f"/api/proyectos/{pid}/assets/hechos")
    igual(respuesta.status_code, 200, "responde 200")
    ok(isinstance(datos.get("planos"), dict),
       "los planos llegan por id, no en una lista")
    ok(isinstance(datos.get("plan"), list),
       "y con la lista de ids que tiene el plan de ahora")
    igual(datos.get("del_plan"),
          len([s for s in (datos.get("plan") or []) if s in (datos.get("planos") or {})]),
          "y cuantos de los que hay son de este plan")


def probar_estimacion(cliente):
    """Cuantas palabras, cuantos planos y cuanto cuesta, SIN proyecto.

    Es lo que se lee al mover la duracion en la pantalla del modo light, y no
    necesita proyecto porque se pregunta antes de que exista ninguno.
    """
    seccion("LA ESTIMACION DE UN VIDEO")
    respuesta, datos = cliente.post("/api/estimacion",
                                    {"duracion_objetivo_s": 240, "idioma": "es",
                                     "velocidad": "normal", "ritmo": "medio"})
    igual(respuesta.status_code, 200, "la estimación responde 200")
    igual(datos["duracion_objetivo_s"], 240, "respeta la duración pedida")
    ok(datos["palabras"]["objetivo"] > 0, "dice cuántas palabras caben")
    ok(datos["palabras"]["minimo"] < datos["palabras"]["objetivo"]
       < datos["palabras"]["maximo"], "con su horquilla alrededor")
    ok(datos["segundos"]["minimo"] < 240 < datos["segundos"]["maximo"],
       "y la horquilla de vuelta EN SEGUNDOS, que es lo que se pregunta")
    ok(datos["planos"]["total"] > 0, "cuántos planos salen")
    ok(datos["coste"]["usd_total"] > 0, "y lo que va a costar el vídeo entero")
    igual(datos["cadencia"]["origen"] in ("medido", "estimado"), True,
          "diciendo si la cadencia está medida o estimada")

    # TODOS LOS PLANOS PAGAN IMAGEN. Antes habia planos que no --los que
    # ensenaban metraje real de un mapa-- y se descontaban de la cuenta. Ya no
    # existen, asi que el precio es el numero de planos por lo que cuesta uno:
    # si esto deja de cumplirse, hay algo descontando en silencio.
    igual(datos["coste"]["imagenes"], datos["planos"]["total"],
          "se paga una imagen por plano, sin descuentos escondidos")
    igual(datos["planos"]["con_imagen"], datos["planos"]["total"],
          "y la ficha de planos dice lo mismo")

    respuesta, _ = cliente.post("/api/estimacion", {"duracion_objetivo_s": "hola"})
    igual(respuesta.status_code, 400, "una duración que no es un número da 400")


def probar_escucha_de_voz_light(cliente):
    """La escucha de una voz, y la de OTRA sin elegirla.

    Es lo que hace el play de cada celda de la cuadricula: audicionar. Si
    escuchar guardara, comparar seis voces dejaria puesta la sexta -- asi que la
    voz viaja en el cuerpo y el preset no se toca. Todo lo demas (velocidad,
    color, aire) son los mandos del estilo, que es lo que hace que la comparacion
    valga: cambia la voz y nada mas.
    """
    seccion("MODO LIGHT: ESCUCHAR UNA VOZ SIN ELEGIRLA")
    respuesta, datos = cliente.post("/api/proyectos", {"nombre": "taller de escucha"})
    tid = (datos.get("proyecto") or {}).get("id") or ""
    config = os.path.join(cliente.carpeta, tid, "proyecto.json")
    with open(config, "r", encoding="utf-8") as fh:
        ficha = json.load(fh)
    ficha["taller_de_preset"] = True
    with open(config, "w", encoding="utf-8") as fh:
        json.dump(ficha, fh)

    respuesta, datos = cliente.get("/api/voces", params={"idioma": "es", "nativas": 1})
    voces = datos.get("voces") or []
    ok(len(voces) >= 2, f"hay al menos dos voces nativas que comparar ({len(voces)})")
    puesta, otra = voces[0], voces[-1]

    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "canal", "nombre": "Canal con taller",
        "datos": {"guion": {"idiomas_salida": ["es"]},
                  "voz": {"voz_id": puesta["id"], "voz_nombre": puesta["nombre"],
                          "idioma": "es", "velocidad": "normal"},
                  "origen": {"estilo_prompt": "dibujo plano", "taller": tid}}})
    pid_preset = (datos.get("preset") or {}).get("id") or ""

    ruta = f"/api/presets-light/{pid_preset}/voz/previsualizar"
    respuesta, datos = cliente.post(ruta, {"segundos": 4})
    igual(respuesta.status_code, 202, "escuchar la voz del estilo responde 202")
    igual(datos.get("voz_id"), puesta["id"], "y suena la que tiene puesta")
    hecho = esperar_trabajo(cliente, datos.get("trabajo_id"))
    igual(hecho["estado"], "listo", f"la escucha se genera ({hecho.get('error')})")
    ok(bool((hecho.get("resultado") or {}).get("url")), "y trae su URL")

    respuesta, datos = cliente.post(ruta, {"segundos": 4, "voz_id": otra["id"]})
    igual(respuesta.status_code, 202, "escuchar OTRA voz responde 202")
    igual(datos.get("voz_id"), otra["id"], "y suena la que se ha pedido")
    hecho = esperar_trabajo(cliente, datos.get("trabajo_id"))
    igual(hecho["estado"], "listo", f"la audicion se genera ({hecho.get('error')})")

    respuesta, datos = cliente.get("/api/presets-light")
    guardado = next((f for f in (datos.get("presets") or [])
                     if f.get("id") == pid_preset), {})
    igual(((guardado.get("datos") or {}).get("voz") or {}).get("voz_id"),
          puesta["id"], "y el estilo SIGUE con la suya: escuchar no elige")

    cliente.delete(f"/api/presets-light/{pid_preset}")


def probar_muestras_recuperadas(cliente):
    """Un estilo al que le faltan sus muestras se las recupera del taller.

    Las muestras son lo unico que se mira de un estilo: cuatro planos con su
    cartela y su subtitulo puestos, a todo lo ancho. Cuando desaparecian del
    banco --se las llevaba por delante cualquier guardado posterior-- la ficha
    seguia declarandolas y la pantalla pintaba cuatro imagenes rotas: un hueco
    negro donde va lo unico que hay que juzgar.

    El taller no se borra al guardar el preset, asi que devolverlas no cuesta ni
    una imagen ni una llamada. Se hace al listar, que es lo unico que garantiza
    que pase.
    """
    seccion("MODO LIGHT: LAS MUESTRAS QUE FALTAN SE DEVUELVEN")
    respuesta, datos = cliente.post("/api/proyectos", {"nombre": "taller con muestras"})
    tid = (datos.get("proyecto") or {}).get("id") or ""
    config = os.path.join(cliente.carpeta, tid, "proyecto.json")
    with open(config, "r", encoding="utf-8") as fh:
        ficha = json.load(fh)
    ficha["taller_de_preset"] = True
    with open(config, "w", encoding="utf-8") as fh:
        json.dump(ficha, fh)

    sueltas = [f"muestra{n}.png" for n in range(1, 5)]
    carpeta = os.path.join(cliente.carpeta, tid, "muestras")
    os.makedirs(carpeta, exist_ok=True)
    for indice, nombre in enumerate(["miniatura.png"] + sueltas):
        with open(os.path.join(carpeta, nombre), "wb") as fh:
            fh.write(b"\x89PNG-taller" + bytes([indice]) * 16)

    # el preset las DECLARA y en su carpeta del banco no hay ninguna: es
    # exactamente como quedaba un estilo despues de cambiarle el nombre
    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "canal", "nombre": "Canal sin sus muestras",
        "datos": {"guion": {"idiomas_salida": ["es"]},
                  "origen": {"estilo_prompt": "dibujo plano", "taller": tid,
                             "muestras": sueltas}}})
    pid_preset = (datos.get("preset") or {}).get("id") or ""

    respuesta, datos = cliente.get("/api/presets-light")
    guardado = next((f for f in (datos.get("presets") or [])
                     if f.get("id") == pid_preset), {})
    igual(((guardado.get("datos") or {}).get("origen") or {}).get("muestras"),
          sueltas, "la ficha sigue declarando sus cuatro muestras")
    for nombre in sueltas:
        respuesta = cliente.sesion.get(
            f"{cliente.base}/api/presets-canal/{pid_preset}/fichero/{nombre}",
            timeout=30)
        igual(respuesta.status_code, 200, f"y {nombre} se sirve de verdad")
    ok(guardado.get("hay_miniatura") is True,
       "y la cara de la tarjeta vuelve a ser la hoja 2x2, no un fotograma")

    cliente.delete(f"/api/presets-light/{pid_preset}")


def probar_imagenes_de_apoyo(cliente):
    """Imagenes adjuntas a una descripcion de estilo: el buzon y sus limites.

    El camino del video le da a la guia veinticuatro fotogramas que mirar; el
    descrito le daba un parrafo y nada mas. Se pueden adjuntar hasta las MISMAS
    veinticuatro como material de apoyo, y el tope sale de donde vive
    (`p6_assets.REFERENCIAS_A_ELEGIR`) en vez de escribirse dos veces.

    Se suben ANTES de que exista el taller --no hay taller hasta pulsar
    «Generar»-- asi que esperan en un buzon; lo que se prueba aqui es ese buzon
    y las dos cosas que tiene que rechazar.
    """
    seccion("MODO LIGHT: IMAGENES DE APOYO DE UNA DESCRIPCION")
    respuesta, datos = cliente.get("/api/presets-light")
    tope = datos.get("max_imagenes_estilo")
    ok(isinstance(tope, int) and tope > 0,
       f"la galeria dice cuantas imagenes caben ({tope})")

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    respuesta, datos = cliente.pedir(
        "POST", "/api/presets-light/imagenes",
        files=[("imagenes", ("una.png", png, "image/png")),
               ("imagenes", ("otra.jpg", png, "image/jpeg"))])
    igual(respuesta.status_code, 201, "subir dos imagenes responde 201")
    subidas = datos.get("imagenes") or []
    igual(len(subidas), 2, "y las guarda las dos")
    ok(all(s.get("nombre") and s.get("origen") for s in subidas),
       "cada una vuelve con su nombre guardado y el que traia")
    ok(subidas[0]["nombre"] != subidas[1]["nombre"],
       "con nombres distintos: dos ficheros que se llamen igual no se pisan")

    for s in subidas:
        respuesta = cliente.sesion.get(
            f"{cliente.base}/api/presets-light/imagenes/{s['nombre']}", timeout=30)
        igual(respuesta.status_code, 200, f"{s['origen']} se sirve para la miniatura")

    # lo que NO se acepta: un fichero que el CLI no puede abrir
    respuesta, datos = cliente.pedir(
        "POST", "/api/presets-light/imagenes",
        files=[("imagenes", ("apuntes.txt", b"no soy una imagen", "text/plain"))])
    igual(respuesta.status_code, 400, "un fichero que no es imagen da 400")

    nombres = [s["nombre"] for s in subidas]
    base = {"nombre": "Canal con imagenes", "idioma": "es",
            "estilo_prompt": "igual pero más frío y sin personajes",
            "tono_prompt": "serio pero cercano, sin dramatismo",
            "voz_prompt": "grave, pausada, sin sonar a locutor"}

    respuesta, datos = cliente.post("/api/presets-light/plan",
                                    dict(base, estilo_imagenes=nombres))
    igual(respuesta.status_code, 200,
          "un encargo de imagenes CON indicaciones es valido")
    respuesta, datos = cliente.post("/api/presets-light/plan",
                                    dict(base, estilo_prompt="",
                                         estilo_imagenes=nombres))
    igual(respuesta.status_code, 200, "y sin indicaciones tambien: son opcionales")

    # SIN IMAGENES NO HAY ESTILO, por muchas indicaciones que se escriban: de
    # un parrafo suelto se inventa todo lo que el parrafo no diga.
    respuesta, datos = cliente.post("/api/presets-light/plan", dict(
        base, estilo_imagenes=[]))
    igual(respuesta.status_code, 400,
          "sin imagenes da 400 aunque haya indicaciones")

    respuesta, datos = cliente.post("/api/presets-light/plan", dict(
        base, estilo_imagenes=[f"x{i}.png" for i in range(tope + 1)]))
    igual(respuesta.status_code, 400, f"pasarse de {tope} da 400")

    respuesta, datos = cliente.delete(
        f"/api/presets-light/imagenes/{nombres[0]}")
    igual(respuesta.status_code, 200, "quitar una del buzon responde 200")
    respuesta = cliente.sesion.get(
        f"{cliente.base}/api/presets-light/imagenes/{nombres[0]}", timeout=30)
    igual(respuesta.status_code, 404, "y ya no esta")


def probar_cambiar_la_fuente_del_estilo(cliente):
    """Cambiar DE DONDE sale el estilo, conservando el tono y la voz.

    El caso: «los mismos videos, pero en fotografico». Corregir con una frase
    rehace la guia con los MISMOS fotogramas; esto es la otra cosa, y hasta
    ahora era un estilo nuevo desde cero y volver a escribir el tono y la voz.

    Lo que se prueba aqui es lo que decide ANTES de gastar: que la lista de
    tareas sale del encargo NUEVO --con un video hay que bajarlo y volver a
    elegir fotogramas, y sin el no-- y que el tono y la voz nunca entran.
    """
    seccion("MODO LIGHT: CAMBIAR LA FUENTE DEL ESTILO")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "pasos"))
    import presets_light as light

    base = {"nombre": "Canal", "idioma": "es",
            "tono_prompt": "serio pero cercano, sin dramatismo",
            "voz_prompt": "grave, pausada, sin sonar a locutor"}

    descrito = light.validar_encargo(
        dict(base, estilo_prompt="fotográfico, luz natural, sin filtros"))
    tareas = light.tareas_de_estilo(descrito)
    ok("frames" not in tareas and "eleccion" not in tareas,
       f"con una descripcion nueva no se baja ningun vídeo ({tareas})")

    con_video = light.validar_encargo(
        dict(base, estilo_url="https://www.youtube.com/watch?v=xxxxxxxxxxx"))
    tareas_video = light.tareas_de_estilo(con_video)
    ok("frames" in tareas_video and "eleccion" in tareas_video,
       f"con un vídeo nuevo si: hay que bajarlo y volver a elegir ({tareas_video})")
    ok(tareas_video.index("frames") < tareas_video.index("guia"),
       "y en orden: primero los fotogramas, despues la guia")

    for lista in (tareas, tareas_video):
        ok("tono" not in lista and "voz" not in lista,
           "el tono y la voz NUNCA se rehacen al cambiar el estilo")
        ok(all(t in lista for t in light.PARTES["estilo"]["tareas"]),
           "y se rehace el estilo entero, no media guia")

    igual(light.plan_de(descrito, tareas)["imagenes"],
          light.imagenes_de_parte("estilo"),
          "cambiar a una descripcion cuesta lo mismo que rehacer el estilo")

    # y por la API: sin taller se dice, no se inventa uno
    respuesta, datos = cliente.post("/api/presets-canal", {
        "tipo": "canal", "nombre": "Canal sin taller",
        "datos": {"guion": {"idiomas_salida": ["es"]},
                  "origen": {"estilo_prompt": "dibujo plano",
                             "tono_prompt": "serio pero cercano",
                             "voz_prompt": "grave y pausada"}}})
    pid = (datos.get("preset") or {}).get("id") or ""
    respuesta, datos = cliente.post(f"/api/presets-light/{pid}/regenerar", {
        "parte": "estilo", "peticion": "",
        "origen": {"estilo_prompt": "fotográfico, luz natural, sin filtros"}})
    igual(respuesta.status_code, 409,
          "cambiar la fuente sin taller da 409 y lo explica")
    respuesta, datos = cliente.post(f"/api/presets-light/{pid}/regenerar", {
        "parte": "voz", "peticion": "más joven",
        "origen": {"estilo_prompt": "fotográfico"}})
    igual(respuesta.status_code, 400,
          "y la voz no tiene fuente que cambiar: eso es un 400")
    cliente.delete(f"/api/presets-light/{pid}")


def probar_taller_oculto(cliente):
    """Un taller de preset NO sale en la lista de proyectos.

    Se comprueba de verdad --creando la carpeta con su marca-- porque el fallo
    que evita es mudo: el taller aparece entre los videos, alguien lo abre, y
    empieza a trastear dentro de la carpeta de la que sale un preset.
    """
    seccion("EL TALLER DE UN PRESET NO ES UN PROYECTO")
    respuesta, datos = cliente.post("/api/proyectos", {"nombre": "taller falso"})
    igual(respuesta.status_code, 201, "se crea el proyecto que hara de taller")
    tid = (datos.get("proyecto") or {}).get("id") or ""

    config = os.path.join(cliente.carpeta, tid, "proyecto.json")
    with open(config, "r", encoding="utf-8") as fh:
        ficha = json.load(fh)
    ficha["taller_de_preset"] = True
    with open(config, "w", encoding="utf-8") as fh:
        json.dump(ficha, fh)

    respuesta, datos = cliente.get("/api/proyectos")
    ok(not any(p.get("id") == tid for p in (datos.get("proyectos") or [])),
       "un proyecto marcado como taller no sale en la lista")
    respuesta, datos = cliente.get(f"/api/proyectos/{tid}")
    igual(respuesta.status_code, 200,
          "pero sigue abriendose por su id: es donde corre la generacion")


def main():
    parser = argparse.ArgumentParser(description="Prueba del servicio HTTP")
    parser.add_argument("--conservar", action="store_true",
                        help="no borrar la carpeta temporal al acabar")
    argumentos = parser.parse_args()

    carpeta = tempfile.mkdtemp(prefix="estudio_api_")
    puerto = puerto_libre()
    print(f"PRUEBA DE LA API DEL ESTUDIO\n  puerto {puerto}\n  proyectos en {carpeta}")
    proceso, base = arrancar(puerto, carpeta)
    cliente = Cliente(base, carpeta)
    try:
        pid, virgen = probar_salud_y_proyectos(cliente)
        probar_renombrar(cliente, pid)
        probar_pasos(cliente, pid)

        sembrar(os.path.join(carpeta, pid))
        tid, salidas = probar_ejecucion(cliente, base, pid)
        probar_versiones(cliente, pid)
        probar_archivos(cliente, pid, salidas)
        probar_feedback(cliente, pid)
        probar_voz(cliente, pid)
        probar_bitacora(cliente, pid)
        probar_presets_canal(cliente)
        probar_modo_light(cliente)
        probar_video_light(cliente)
        probar_estimacion(cliente)
        probar_planos_hechos(cliente, pid)
        probar_escucha_de_voz_light(cliente)
        probar_muestras_recuperadas(cliente)
        probar_imagenes_de_apoyo(cliente)
        probar_taller_oculto(cliente)
        probar_cartelas_y_transiciones(cliente, pid, os.path.join(carpeta, pid))
        probar_direccion(cliente, pid)
        probar_motor_del_plan(cliente, pid)
        probar_nota_del_montaje(cliente, pid)
        probar_repaso(cliente, pid)
        probar_plan_de_rotulos(cliente, pid)
        probar_trabajos_y_errores(cliente, pid, tid, virgen)
        probar_vista_de_cartela(cliente, os.path.join(carpeta, pid), pid)
        probar_cartela_sincronizada(cliente, os.path.join(carpeta, pid), pid)
        probar_claves(cliente)
        probar_cuentas_cli(cliente)
        probar_asistente(cliente)
        probar_la_foto_del_asistente(cliente, pid)
        probar_onboarding(cliente)
        probar_salud_de_las_cuentas(cliente)
        probar_recetas(cliente, pid)
        probar_lo_que_se_cuenta_en_publico()
        probar_el_avisador_y_los_tramos()
        probar_el_mensaje_publico_de_una_tanda()
        probar_el_reloj_de_lo_que_queda_por_hacer()
        probar_que_la_barra_light_no_ensena_la_cocina()
        probar_value_de_los_textarea()
        probar_el_gemelo_de_las_marcas_tts()
        probar_que_la_receta_aplica()
        probar_que_la_api_esta_documentada()
        probar_que_las_llamadas_a_los_pasos_encajan()
        probar_que_no_falta_ningun_nombre_en_la_pantalla()
        probar_que_no_falta_ningun_nombre_en_el_servidor()
        probar_el_reloj_de_un_trabajo()
    finally:
        parar(proceso)
        if not argumentos.conservar:
            shutil.rmtree(carpeta, ignore_errors=True)

    print()
    if _fallos:
        print(f"PRUEBA API CON FALLOS: {len(_fallos)} de {_ok + len(_fallos)}")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"PRUEBA API OK: {_ok} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
