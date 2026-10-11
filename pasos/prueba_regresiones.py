"""Los fallos de octubre de 2026, uno por seccion, para que no vuelvan.

Salieron de las incidencias de GitHub (crear un estilo fallaba siempre) y de
una auditoria de la version publicada. Cada seccion reproduce el fallo con lo
minimo y comprueba el arreglo. Sin red, sin CLI y sin pagar nada: el motor de
imagen, el navegador y el modelo van sustituidos por dobles.

  1] el motor de imagen dibuja SIN adjuntos (por /generations) y aprende su ritmo
  2] las laminas de un estilo se dibujan con las imagenes del canal delante,
     y una lamina ya dibujada con lo mismo no se vuelve a pagar
  3] el catalogo visual monta su prompt (el `{fijos}` que se quedo colgando)
  4] guardar otra vez un estilo no renombra ni borra sus ficheros
  5] un solo precio por imagen
  6] la captura del navegador: el PNG entero, el navegador que no sale, y un
     PNG viejo que no puede convertir un fallo en un exito
  7] la previa con el cielo claro, y la pagina de error
  8] los lotes de render caben en la memoria
  9] el guionista recibe el material escrito como texto, no como un video

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe pasos\\prueba_regresiones.py
"""
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest import mock

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

CARPETA = tempfile.mkdtemp(prefix="regresiones_")
# todo lo que se escribe, a la carpeta de la prueba: ni el historico de tiempos,
# ni los secretos, ni lo que aprende el motor de imagen pueden acabar en los de
# verdad
os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(CARPETA, "estadisticas.json")
os.environ["ESTUDIO_SECRETOS"] = os.path.join(CARPETA, "secretos")
os.environ["OPENAI_API_KEY"] = "sk-prueba-sin-red"

from PIL import Image  # noqa: E402

import catalogo_visual  # noqa: E402
import medios  # noqa: E402
import moodboard  # noqa: E402
import p3_guion  # noqa: E402
import p7_callouts  # noqa: E402
import p8_render  # noqa: E402
import presets_canal  # noqa: E402
import presets_light  # noqa: E402
import recetas  # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    print(("  ok   " if condicion else "  FALLO ") + texto)
    if not condicion:
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado,
              texto if obtenido == esperado
              else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def seccion(titulo):
    print(f"\n[{titulo}]")


def _png(ruta, color, tamano=(64, 48)):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    Image.new("RGB", tamano, color).save(ruta)
    return ruta


def _png_en_bytes(color=(10, 20, 30)):
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


def _motor_imagen():
    """El motor de imagen DE VERDAD, cargado aparte (lee el entorno al importar)."""
    ruta = os.path.join(RAIZ, "motores", "imagen_openai", "imagen.py")
    spec = importlib.util.spec_from_file_location("imagen_prueba", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Respuesta:
    def __init__(self, codigo=200, cuerpo=None, texto=""):
        self.status_code = codigo
        self._cuerpo = cuerpo or {}
        self.text = texto or json.dumps(self._cuerpo)
        self.headers = {}

    def json(self):
        return self._cuerpo


# ------------------------------------------------------------------- 1] motor

def prueba_motor_sin_adjuntos():
    seccion("1] el motor de imagen dibuja sin adjuntos y aprende su ritmo")
    imagen = _motor_imagen()
    comprobar(imagen.RUTA_LIMITES.startswith(os.environ["ESTUDIO_SECRETOS"]),
              "lo aprendido se guarda con los secretos, no junto al programa")
    llamadas = []
    pngb64 = __import__("base64").b64encode(_png_en_bytes()).decode()

    def post(url, **kwargs):
        llamadas.append({"url": url, **kwargs})
        return _Respuesta(200, {"data": [{"b64_json": pngb64}], "usage": {}})

    with mock.patch.object(imagen.requests, "post", side_effect=post):
        png, meta = imagen.generar("un gato", [], quality="low")
        comprobar(png.startswith(b"\x89PNG"), "sin referencias devuelve una imagen")
        igual(llamadas[-1]["url"], imagen.API_URL_SIN_REFS,
              "y la pide a /generations")
        comprobar("json" in llamadas[-1] and "files" not in llamadas[-1],
                  "como JSON y sin adjuntos (con /edits salia «Unsupported content type»)")
        igual(llamadas[-1]["json"]["model"], imagen.MODELO, "con el mismo modelo")
        igual(meta["refs"], 0, "y la ficha dice que no llevaba referencias")

        ref = _png(os.path.join(CARPETA, "motor", "ref.png"), (200, 10, 10))
        imagen.generar("un gato", [ref], quality="low")
        igual(llamadas[-1]["url"], imagen.API_URL, "con referencias sigue yendo a /edits")
        comprobar(llamadas[-1].get("files"), "y las manda como adjuntos")

    # el cubo: va justa, nadie la frena -> sube; un 429 sin numero -> atras
    cuenta = imagen._cuentas()[0]
    antes = int(cuenta.limite[0])
    cuenta.saturada_en = time.monotonic()
    cuenta.subida_en = cuenta.frenada_en = -1e9
    imagen._quizas_subir(cuenta)
    comprobar(int(cuenta.limite[0]) > antes,
              f"una cuenta que va justa sube su ritmo ({antes} -> {cuenta.limite[0]})")
    comprobar(os.path.exists(imagen.RUTA_LIMITES), "y lo deja apuntado")
    guardado = json.load(open(imagen.RUTA_LIMITES, encoding="utf-8"))
    comprobar("sk-prueba" not in json.dumps(guardado),
              "por la huella de la clave, nunca la clave")
    imagen._aprender_del_429(cuenta, cuenta.techo[0])
    igual(int(cuenta.limite[0]), antes, "un 429 sin numero la devuelve al ritmo de antes")


# ---------------------------------------------------------------- 2] laminas

def prueba_laminas_con_imagenes():
    seccion("2] las laminas del estilo se dibujan con las imagenes del canal")
    destino = os.path.join(CARPETA, "taller", "estilo", "dibujadas")
    aportadas = [_png(os.path.join(CARPETA, "taller", "aportadas", f"{i}.png"), c)
                 for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255)])]
    pedidas = []

    def generar(prompt, referencias, **kwargs):
        pedidas.append({"prompt": prompt, "refs": list(referencias)})
        return _png_en_bytes(), {"coste": 0.01}

    motor = SimpleNamespace(generar=generar,
                            normalizar=lambda ruta, cache, lado_max=1024: ruta)
    reglas = SimpleNamespace(bloque_prompt=lambda _: "")
    p6 = SimpleNamespace(MAX_CADENAS=1,
                         guia_escrita=lambda _e: ["Flat chibi drawing."])

    def motor_de(ruta):
        return motor if ruta.startswith("imagen_") else reglas

    with mock.patch.dict(sys.modules, {"p6_assets": p6}), \
            mock.patch.object(moodboard.medios, "motor", side_effect=motor_de):
        hecho = moodboard.dibujar_desde_guia(
            {"guia": "x"}, destino, ejes=["cara", "diagrama"], idioma="es",
            calidad="low", referencias=aportadas)
        igual(len(pedidas), 2, "dos ejes, dos dibujos")
        comprobar(all(len(p["refs"]) == 1 for p in pedidas),
                  "cada dibujo lleva UNA lamina con las imagenes del canal")
        lamina = pedidas[0]["refs"][0]
        comprobar(os.path.exists(lamina) and Image.open(lamina).size[0] > 0,
                  "y la lamina existe")
        comprobar("STYLE SHEET" in pedidas[0]["prompt"],
                  "el prompt le dice que copie el estilo de esa lamina")
        comprobar("Spanish" in pedidas[0]["prompt"],
                  "y le dice el idioma del canal (antes no llegaba)")
        igual(hecho["coste_usd"], 0.02, "y se cuenta lo pagado")

        # RETOMAR CON LO MISMO NO PAGA OTRA VEZ
        moodboard.dibujar_desde_guia(
            {"guia": "x"}, destino, ejes=["cara", "diagrama"], idioma="es",
            calidad="low", referencias=aportadas)
        igual(len(pedidas), 2, "pedir lo mismo otra vez no vuelve a dibujar")
        moodboard.dibujar_desde_guia(
            {"guia": "x"}, destino, ejes=["cara"], idioma="es", calidad="low",
            referencias=aportadas, peticiones={"cara": "mas redonda"})
        igual(len(pedidas), 3, "con una correccion, esa lamina si se redibuja")

        # SIN IMAGENES: solo con la guia (el motor ya sabe pedirlo sin adjuntos)
        otro = os.path.join(CARPETA, "taller2", "dibujadas")
        moodboard.dibujar_desde_guia({"guia": "x"}, otro, ejes=["cara"],
                                     calidad="low", referencias=[])
        igual(pedidas[-1]["refs"], [], "sin imagenes del canal se dibuja sin adjuntos")
        comprobar("STYLE SHEET" not in pedidas[-1]["prompt"],
                  "y el prompt no habla de una lamina que no existe")

    muchas = [_png(os.path.join(CARPETA, "muchas", f"{i}.png"), (i * 10, 0, 0),
                   (400, 300)) for i in range(24)]
    hoja = moodboard._montar_aportadas(muchas, os.path.join(CARPETA, "muchas", "h.png"))
    ancho, alto = Image.open(hoja).size
    comprobar(ancho <= moodboard.TAMANO[0] and alto <= moodboard.TAMANO[1]
              and ancho > moodboard.TAMANO[0] * 0.98,
              f"veinticuatro imagenes caben en una hoja del tamano de un plano "
              f"({ancho}x{alto})")
    # se toman doce repartidas, en casillas que se ven (con dos columnas fijas
    # cada una salia de 85 px de alto): la hoja tiene 3 filas, no 12
    filas = round(alto / (moodboard.TAMANO[1] // 3))
    igual(filas, 3, "doce imagenes en tres filas, cada una de mas de 300 px de alto")


# --------------------------------------------------------------- 3] catalogo

def prueba_catalogo():
    seccion("3] el catalogo visual monta su prompt")
    recibido = {}

    class Corte(Exception):
        pass

    def llamar(instruccion, *args, **kwargs):
        recibido["prompt"] = instruccion
        raise Corte()

    with mock.patch.object(catalogo_visual, "_llamar_claude", side_effect=llamar):
        try:
            catalogo_visual.proponer(
                [{"id": "B001", "texto": "Revisa el contrato de la vivienda."}],
                brief={"titulo": "Compra sobre plano"}, peticion="sobrio")
        except Corte:
            pass
        except KeyError as fallo:
            comprobar(False, f"el prompt no se puede montar: KeyError {fallo}")
    comprobar("Revisa el contrato de la vivienda." in recibido.get("prompt", ""),
              "el guion llega al modelo (antes: KeyError 'fijos' en todo video nuevo)")


# ----------------------------------------------------------------- 4] estilos

def prueba_estilo_estable():
    seccion("4] guardar otra vez un estilo no le cambia los ficheros")
    presets_canal.FICHERO = os.path.join(CARPETA, "presets.json")
    presets_canal.BANCO = os.path.join(CARPETA, "banco_presets")
    origen = [_png(os.path.join(CARPETA, "taller3", f"{eje}.png"), (i * 40, 90, 90))
              for i, eje in enumerate(("cara", "cuerpos", "interior"))]
    ficha = presets_canal.guardar("estilo", "Mi estilo", {"referencias": origen})
    rutas = list(ficha["datos"]["referencias"])
    comprobar(all(os.path.exists(r) for r in rutas), "al crear, se copian al banco")
    # un video hecho con el estilo guarda ESAS rutas
    for vez in range(3):
        guardado = presets_canal.leer(ficha["id"])
        ficha = presets_canal.guardar("estilo", f"Mi estilo {vez}",
                                      guardado["datos"], pid=ficha["id"])
    igual(ficha["datos"]["referencias"], rutas,
          "tres guardados despues, las referencias son las mismas rutas")
    comprobar(all(os.path.exists(r) for r in rutas),
              "y siguen en el disco: el video que las tiene puede seguir dibujando")
    comprobar(not any("00_00_" in os.path.basename(r)
                      for r in os.listdir(presets_canal.carpeta_de(ficha["id"]))),
              "nada se vuelve a copiar con otro prefijo")
    # un estilo regenerado: las laminas nuevas entran sin pisar las viejas
    nuevas = [_png(os.path.join(CARPETA, "taller4", f"{eje}.png"), (5, 5, i * 60))
              for i, eje in enumerate(("cara", "cuerpos", "interior"))]
    ficha = presets_canal.guardar("estilo", "Mi estilo", {"referencias": nuevas},
                                  pid=ficha["id"])
    comprobar(all(os.path.exists(r) for r in rutas),
              "regenerado el estilo, las laminas viejas siguen (las usan videos viejos)")
    comprobar(set(ficha["datos"]["referencias"]).isdisjoint(rutas),
              "y las nuevas son otros ficheros")


# ------------------------------------------------------------------ 5] precio

def prueba_precio():
    seccion("5] un solo precio por imagen")
    import ajustes  # noqa: PLC0415
    for calidad in ("low", "medium", "high"):
        igual(round(presets_light.usd_por_imagen(calidad), 4),
              round(ajustes.coste_por_imagen(calidad)["usd_total"], 4),
              f"el plan y Configuracion dicen lo mismo en {calidad}")


# ---------------------------------------------------------------- 6] captura

class _Navegador:
    """Un navegador de mentira: escribe la captura y, si se le dice, no sale."""

    def __init__(self, orden, escribe=True, sale=True, **kwargs):
        self.pid = 4242
        self.sale = sale
        self.cerrado = False
        self.returncode = None
        if escribe:
            ruta = next(x.split("=", 1)[1] for x in orden
                        if x.startswith("--screenshot="))
            Image.new("RGB", (32, 24), "navy").save(ruta)

    def poll(self):
        if self.sale or self.cerrado:
            self.returncode = 0
            return 0
        return None

    def wait(self, timeout=None):
        if self.sale or self.cerrado:
            return 0
        raise subprocess.TimeoutExpired("navegador", timeout)

    def kill(self):
        self.cerrado = True


def prueba_captura():
    seccion("6] la captura del navegador")
    creados = []

    def lanzar(clase_kwargs):
        def popen(orden, **kwargs):
            navegador = _Navegador(orden, **clase_kwargs)
            creados.append(navegador)
            return navegador
        return popen

    def cerrar(orden, **kwargs):
        for navegador in creados:
            navegador.cerrado = True
        return SimpleNamespace(returncode=0)

    destino = os.path.join(CARPETA, "captura", "foto.png")
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with mock.patch.object(medios, "edge", return_value="navegador"), \
            mock.patch.object(medios, "GRACIA_SALIDA_S", 0.2), \
            mock.patch.object(medios.subprocess, "run", side_effect=cerrar), \
            mock.patch.object(medios.os, "killpg", create=True,
                              side_effect=lambda *a: cerrar(None)):
        Image.new("RGB", (32, 24), "red").save(destino)
        with mock.patch.object(medios.subprocess, "Popen",
                               side_effect=lanzar({"sale": False})):
            arranque = time.time()
            medios.rasterizar("<svg/>", destino, 32, 24)
            segundos = time.time() - arranque
        comprobar(segundos < 10,
                  f"con el PNG entero no espera a que el navegador salga ({segundos:.1f} s)")
        comprobar(creados[-1].cerrado, "y al que no sale se le cierra")
        igual(Image.open(destino).getpixel((0, 0)), (0, 0, 128),
              "el destino es la captura nueva, no lo que habia")

        Image.new("RGB", (32, 24), "red").save(destino)
        anterior = open(destino, "rb").read()
        with mock.patch.object(medios.subprocess, "Popen",
                               side_effect=lanzar({"escribe": False})), \
                mock.patch.object(medios, "ESPERA_RASTERIZAR_S", 0):
            try:
                medios.rasterizar("<svg/>", destino, 32, 24)
                comprobar(False, "un navegador que no escribe nada tiene que fallar")
            except RuntimeError:
                comprobar(True, "un navegador que no escribe nada falla")
        igual(open(destino, "rb").read(), anterior,
              "y el PNG viejo no se da por bueno ni se toca")


# ------------------------------------------------------------------ 7] previa

def prueba_previa():
    seccion("7] la previa: la firma de carga")
    ancho, alto = 40, 30
    ruta = os.path.join(CARPETA, "previa", "previa.png")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    claro = Image.new("RGB", (ancho, alto + p7_callouts.ALTO_FIRMA), (212, 221, 231))
    for i, color in enumerate(p7_callouts.FIRMA_PREVIA):
        for x in range(i * 4, i * 4 + 4):
            for y in range(alto, alto + p7_callouts.ALTO_FIRMA):
                claro.putpixel((x, y), color)
    claro.save(ruta)
    p7_callouts._comprobar_previa(ruta, (ancho, alto))
    con = Image.open(ruta)
    igual(con.size, (ancho, alto), "un plano de cielo claro pasa, y sin la franja")
    igual(con.getpixel((5, 5)), (212, 221, 231), "con su esquina clara intacta")
    for color in ("white", "black"):
        Image.new("RGB", (ancho, alto + p7_callouts.ALTO_FIRMA), color).save(ruta)
        try:
            p7_callouts._comprobar_previa(ruta, (ancho, alto))
            comprobar(False, f"una pagina sin firma ({color}) tiene que fallar")
        except RuntimeError:
            comprobar(True, f"una pagina sin firma ({color}) no se da por buena")


# ------------------------------------------------------------------ 8] lotes

def prueba_lotes():
    seccion("8] los lotes de render caben en la memoria")
    with mock.patch.dict(os.environ, {"ESTUDIO_LOTES": "8"}), \
            mock.patch.object(p8_render, "_memoria_total_gb", return_value=8.0):
        igual(p8_render._cuantos_lotes({}, 300), 2,
              "8 nucleos pedidos con 8 GB: caben 2")
        igual(p8_render._cuantos_lotes({"lotes": 6}, 300), 6,
              "lo que se pide a mano para un video manda")
    with mock.patch.dict(os.environ, {"ESTUDIO_LOTES": "8"}), \
            mock.patch.object(p8_render, "_memoria_total_gb", return_value=32.0):
        igual(p8_render._cuantos_lotes({}, 300), 8, "con 32 GB caben los 8")
    with mock.patch.object(p8_render, "_memoria_total_gb", return_value=None):
        comprobar(p8_render._tope_por_memoria() == p8_render.MAX_LOTES,
                  "sin saber la memoria no se limita nada")


# ------------------------------------------------------------------- 9] guion

def prueba_material_escrito():
    seccion("9] el guionista recibe el material escrito como texto")
    transcript = [{"t_in": 0, "t_out": 0, "texto": "Primer parrafo del material."},
                  {"t_in": 0, "t_out": 0, "texto": "Segundo parrafo."}]
    brief = {"presupuesto_palabras": 120, "margen": {"minimo": 100, "maximo": 140},
             "palabras_por_bloque": 30}
    opciones = p3_guion._normalizar({})
    texto = p3_guion._instruccion(
        transcript, {"titulo": "Mi tema", "origen": "escrito", "sin_tiempos": True,
                     "palabras_transcript": 5, "duracion_s": 0},
        brief, None, opciones, [], "es")
    comprobar("Material escrito: Mi tema" in texto, "se presenta como material escrito")
    comprobar("[00:00]" not in texto and "Video de referencia" not in texto,
              "sin marcas de tiempo ni «video de referencia»")
    comprobar("Primer parrafo del material." in texto, "y con su texto")
    igual(recetas.PUBLICO["ingesta"]["nombre"], "Leyendo el material",
          "y la barra ya no dice «Extrayendo el vídeo»")


def main():
    try:
        prueba_motor_sin_adjuntos()
        prueba_laminas_con_imagenes()
        prueba_catalogo()
        prueba_estilo_estable()
        prueba_precio()
        prueba_captura()
        prueba_previa()
        prueba_lotes()
        prueba_material_escrito()
    finally:
        shutil.rmtree(CARPETA, ignore_errors=True)
    print()
    if FALLOS:
        print(f"REGRESIONES CON FALLOS: {len(FALLOS)}")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        return 1
    print("REGRESIONES OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
