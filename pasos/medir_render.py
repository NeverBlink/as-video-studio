"""EL REPARTO DEL TIEMPO DE RENDER, MEDIDO. Sin esto, acelerar es una apuesta.

POR QUE EXISTE
--------------
2 min 28 s de video costaban 48 minutos de render: 4.440 fotogramas a 0,65 s
cada uno. Con videos de veinte minutos eso son siete horas. La sospecha escrita
en PENDIENTE.md era «el cuello es el viaje al navegador por fotograma», y habia
cuatro caminos posibles para arreglarlo -- que el navegador pinte menos,
capturar mas barato, la GPU en la codificacion, o portar el montaje a MLT --.
Los cuatro son caros de hacer y tres de ellos tocan como se ve el video.

Asi que primero se mide, y se mide EL CODIGO DE VERDAD: este modulo llama a
`p8_render.Navegador`, a `p8_render._pagina_de`, a `p8_render._codificar` y a
`transiciones.componer`, no a una imitacion. Una medida sobre una maqueta mide
la maqueta.

QUE MIDE, Y POR QUE ESAS CASILLAS
---------------------------------
Las cuatro que nombra PENDIENTE.md 20, cada una aislada:

    arrancar     levantar Edge headless y engancharse por CDP. Es UNA vez por
                 render entero, asi que se mide para poder descontarla.
    abrir        cargar la pagina de un plano (el HTML con el hyperframe y el
                 SVG dentro). Una vez por PLANO.
    pintar       poner la pagina en el instante t: `pintar(t)` mas los dos
                 requestAnimationFrame que esperan a que quede pintado.
    capturar     `Page.captureScreenshot` en PNG, decodificar el base64 y
                 escribir el fichero. Una vez por FOTOGRAMA.
    codificar    libx264 sobre la secuencia de PNG del clip.
    transicion   los primeros fotogramas repintados con WebGL.
    montar       concatenar los clips y muxear el audio.

CONDICIONES
-----------
Headless y SIN SESION, que es el limite que no se negocia: este PC no tiene
pantalla y el escritorio remoto esta cerrado el 90 % del tiempo. Si la medida se
toma con una sesion abierta, mide otra maquina.

COMO SE USA

    python pasos\\medir_render.py                    # con lo que haya en el banco
    python pasos\\medir_render.py --fotogramas 90
    python pasos\\medir_render.py --json salida.json

Y no toca ningun proyecto: copia el hyperframe y la capa que se le den a una
carpeta temporal y trabaja ahi.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import medios  # noqa: E402
import p8_render  # noqa: E402
import transiciones  # noqa: E402

#: Cuantos fotogramas se capturan para medir. Noventa son tres segundos de
#: video: bastantes para que la media no dependa del primero (que carga la
#: pagina) y pocos para que la medida entera dure un par de minutos.
FOTOGRAMAS = 90

#: El coste por fotograma se reparte entre los que se capturan, pero `abrir` es
#: por PLANO: para extrapolar a un video hace falta saber cuanto dura un plano.
#: Cuatro segundos es el techo del video largo (`max_s`).
SEGUNDOS_POR_PLANO = 4.0


def condiciones():
    """En que estado esta el escritorio: la medida no vale sin esto.

    Con una sesion de escritorio remoto CONECTADA la maquina esta componiendo un
    escritorio ademas de renderizar, y la cifra sale peor -- o mejor, segun que
    este haciendo el que mira. Este PC corre con el RDP cerrado el 90 % del
    tiempo, asi que esa es la condicion que hay que medir, y por eso la medida
    la dice en vez de darla por supuesta.
    """
    if os.name != "nt":
        return "no es Windows"
    try:
        salida = subprocess.run(["query", "session"], capture_output=True,
                                text=True, timeout=15).stdout or ""
    except Exception:                                            # noqa: BLE001
        return "no se ha podido preguntar"
    activas = [l for l in salida.splitlines()
               if " Active" in l or " Activ" in l]
    return ("hay una sesion de escritorio CONECTADA (la medida sale sesgada)"
            if activas else "sin escritorio conectado (RDP cerrado)")


def _cronometrar(funcion, veces=1):
    """Segundos que tarda `funcion`, sin contar nada mas."""
    inicio = time.perf_counter()
    for _ in range(veces):
        funcion()
    return time.perf_counter() - inicio


def _hyperframe_y_capa(hyper=None, capa=None):
    """El plano sobre el que medir. Por defecto, uno de verdad del banco.

    Se mide sobre un hyperframe REAL y no sobre un PNG plano a proposito: el
    coste de capturar depende de lo que haya en pantalla -- un cuadro liso se
    comprime en nada y mentiria a favor.
    """
    if hyper and os.path.exists(hyper):
        svg = ""
        if capa and os.path.exists(capa):
            with open(capa, "r", encoding="utf-8") as fh:
                svg = fh.read()
        return hyper, svg
    # Los proyectos pueden no estar junto al codigo: en el servidor cada cuenta
    # tiene los suyos y la ruta llega por ESTUDIO_PROYECTOS, igual que en app.py.
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proyectos = (os.environ.get("ESTUDIO_PROYECTOS")
                 or os.path.join(raiz, "proyectos"))
    for proyecto in sorted(os.listdir(proyectos)):
        base = os.path.join(proyectos, proyecto, "pasos", "callouts")
        if not os.path.isdir(base):
            continue
        for version in sorted(os.listdir(base), reverse=True):
            dir_hyper = os.path.join(base, version, "hyper")
            dir_capas = os.path.join(base, version, "capas")
            if not os.path.isdir(dir_hyper):
                continue
            for nombre in sorted(os.listdir(dir_hyper)):
                if not nombre.lower().endswith(".png"):
                    continue
                svg_ruta = os.path.join(dir_capas,
                                        os.path.splitext(nombre)[0] + ".svg")
                svg = ""
                if os.path.exists(svg_ruta):
                    with open(svg_ruta, "r", encoding="utf-8") as fh:
                        svg = fh.read()
                return os.path.join(dir_hyper, nombre), svg
    raise RuntimeError("no hay ningun hyperframe con el que medir: genera "
                       "callouts de algun proyecto, o pasa --hyper")


def medir(fotogramas=FOTOGRAMAS, resolucion=(1920, 1080), fps=30,
          calidad="alta", hyper=None, capa=None, con_transicion=True):
    """El reparto del tiempo de render, en segundos por casilla.

    Devuelve tambien el coste POR FOTOGRAMA de cada casilla, que es lo unico
    que se puede extrapolar a un video de veinte minutos.
    """
    hyper, svg = _hyperframe_y_capa(hyper, capa)
    ancho, alto = [int(v) for v in resolucion]
    trabajo = tempfile.mkdtemp(prefix="medir_render_")
    carpeta = os.path.join(trabajo, "frames")
    os.makedirs(carpeta, exist_ok=True)
    tiempos = {}
    navegador = None
    try:
        duracion = fotogramas / float(fps)
        escena = {"id": "M001", "t_in": 0.0, "t_out": duracion}
        with Image.open(hyper) as imagen:
            hyper_px = list(imagen.size)
        mov = {"ventana_ini": [0.0, 0.0, 1.0, 1.0],
               "ventana_fin": [0.0263, 0.0263, 0.9474, 0.9474],
               "hyperframe_px": hyper_px}
        p = {"resolucion": [ancho, alto], "fps": fps}

        inicio = time.perf_counter()
        pagina = p8_render._pagina_de(escena, mov, svg, hyper, p,
                                      os.path.join(carpeta, "escena.html"))
        tiempos["escribir_pagina"] = time.perf_counter() - inicio

        inicio = time.perf_counter()
        navegador = p8_render.Navegador(ancho, alto)
        tiempos["arrancar"] = time.perf_counter() - inicio

        tiempos["abrir"] = _cronometrar(lambda: navegador.abrir(pagina))

        pintar = capturar = 0.0
        for numero in range(fotogramas):
            t0 = time.perf_counter()
            navegador.pintar(numero / float(fps))
            t1 = time.perf_counter()
            navegador.capturar(os.path.join(carpeta, f"f{numero + 1:05d}.png"))
            t2 = time.perf_counter()
            pintar += t1 - t0
            capturar += t2 - t1
        tiempos["pintar"] = pintar
        tiempos["capturar"] = capturar

        clip = os.path.join(trabajo, "clip.mp4")
        tiempos["codificar"] = _cronometrar(
            lambda: p8_render._codificar(carpeta, clip, fps, calidad))

        tiempos["transicion"] = 0.0
        cuantos = 0
        if con_transicion:
            paleta = {"linea": "#d8a657", "acento": "#d8785a", "texto": "#ece7dc"}
            pagina_trans = transiciones.pagina(
                os.path.join(trabajo, "transicion.html"), ancho, alto, paleta)
            anterior = os.path.join(carpeta, "f00001.png")
            cuantos = min(fotogramas, int(round(fps * 0.4)))
            corte = {"shader": transiciones.frag_de("fundido"), "duracion": 0.4}
            tiempos["transicion"] = _cronometrar(
                lambda: p8_render._cocer_transicion(
                    navegador, pagina_trans, anterior, carpeta, fotogramas,
                    fps, corte))

        # MONTAR: concatenar sin recodificar y muxear. Se miden dos clips
        # porque con uno solo `concat` no tiene nada que empalmar.
        clip_b = os.path.join(trabajo, "clip_b.mp4")
        shutil.copy2(clip, clip_b)
        destino = os.path.join(trabajo, "video.mp4")
        tiempos["montar"] = _cronometrar(
            lambda: p8_render._concatenar([clip, clip_b], destino, None, 0.0,
                                          trabajo))
    finally:
        if navegador:
            navegador.cerrar()
        shutil.rmtree(trabajo, ignore_errors=True)

    por_fotograma = {k: v / float(fotogramas) for k, v in tiempos.items()}
    # LO QUE DE VERDAD CUESTA UN FOTOGRAMA DE VIDEO. `pintar` y `capturar` se
    # pagan en cada uno; `codificar` tambien, porque libx264 recorre la
    # secuencia entera. `abrir` y `transicion` se pagan una vez por PLANO, asi
    # que se reparten entre los fotogramas que dura un plano -- si no, un video
    # de planos de cuatro segundos parece costar lo mismo que uno de planos de
    # medio segundo, y no es verdad.
    por_plano = max(1, int(round(fps * SEGUNDOS_POR_PLANO)))
    unitario = (por_fotograma["pintar"] + por_fotograma["capturar"]
                + por_fotograma["codificar"]
                + (tiempos["abrir"] + tiempos["transicion"]) / por_plano)
    return {
        "fotogramas": fotogramas,
        "resolucion": [ancho, alto],
        "fps": fps,
        "calidad": calidad,
        "hyperframe": os.path.basename(hyper),
        "condiciones": condiciones(),
        "capa_bytes": len(svg),
        "transicion_fotogramas": cuantos,
        "segundos": {k: round(v, 3) for k, v in tiempos.items()},
        "por_fotograma": {k: round(v, 4) for k, v in por_fotograma.items()},
        "s_por_fotograma": round(unitario, 4),
    }


def reparto(ficha):
    """El reparto en tanto por ciento de lo que cuesta UN fotograma de video.

    Es la tabla que hay que mirar antes de elegir por donde acelerar: lo que no
    sale aqui arriba no puede ser el cuello por mucho que lo parezca.
    """
    fps = float(ficha["fps"])
    por_plano = max(1, int(round(fps * SEGUNDOS_POR_PLANO)))
    partes = {
        "pintar la pagina": ficha["por_fotograma"]["pintar"],
        "capturar el PNG": ficha["por_fotograma"]["capturar"],
        "codificar el clip": ficha["segundos"]["codificar"] / ficha["fotogramas"],
        "abrir la pagina": ficha["segundos"]["abrir"] / por_plano,
        "transiciones": ficha["segundos"]["transicion"] / por_plano,
        "montar el video": ficha["segundos"]["montar"] / (por_plano * 20),
    }
    total = sum(partes.values()) or 1.0
    return {k: {"s": round(v, 4), "pct": round(100.0 * v / total, 1)}
            for k, v in sorted(partes.items(), key=lambda kv: -kv[1])}


def medir_reparto(procesos=(1, 4, 8, 16), fotogramas=30, resolucion=(1920, 1080),
                  fps=30, hyper=None, capa=None):
    """Cuantos fotogramas por segundo dan N procesos de captura a la vez.

    Es la medida que decidio el arreglo del 21-08-2026 y por eso se queda: el
    techo de un proceso no lo pone Edge, lo pone lo que hace PYTHON con cada
    fotograma (recomponer el mensaje, parsear 1,5 MB de JSON, descodificar el
    base64). Con hilos eso no se reparte y la curva se aplana en cuatro; con
    procesos escala. Corre por el MISMO camino que el render de verdad
    (`p8_render.correr_lote` en un subproceso), no por una imitacion.
    """
    hyper, svg = _hyperframe_y_capa(hyper, capa)
    ancho, alto = [int(v) for v in resolucion]
    with Image.open(hyper) as imagen:
        hyper_px = list(imagen.size)
    trabajo = tempfile.mkdtemp(prefix="medir_reparto_")
    curva = {}
    try:
        for cuantos in procesos:
            tareas = []
            for numero in range(cuantos):
                carpeta = os.path.join(trabajo, f"p{cuantos}_{numero}")
                tareas.append([{
                    "id": f"M{numero:03d}",
                    "escena": {"id": f"M{numero:03d}", "t_in": 0.0,
                               "t_out": fotogramas / float(fps)},
                    "mov": {"ventana_ini": [0.0, 0.0, 1.0, 1.0],
                            "ventana_fin": [0.0263, 0.0263, 0.9474, 0.9474],
                            "hyperframe_px": hyper_px},
                    "capa": svg, "hyper": hyper, "frames": fotogramas,
                    "fps": fps, "resolucion": [ancho, alto], "calidad": "alta",
                    "carpeta": carpeta,
                    "clip": os.path.join(carpeta, "clip.mp4"),
                    "ultimo": os.path.join(carpeta, "ultimo.png"),
                    "anterior": None, "esperar_anterior": False,
                    "corte": {}, "pagina_trans": "",
                    "conservar_frames": False}])
            inicio = time.perf_counter()
            p8_render._correr_lotes_en_procesos(
                tareas, trabajo, lambda *a, **k: None, cuantos)
            tardo = time.perf_counter() - inicio
            curva[cuantos] = round(cuantos * fotogramas / max(0.001, tardo), 2)
    finally:
        shutil.rmtree(trabajo, ignore_errors=True)
    return curva


def _main(argv=None):
    aparcador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    aparcador.add_argument("--fotogramas", type=int, default=FOTOGRAMAS)
    aparcador.add_argument("--ancho", type=int, default=1920)
    aparcador.add_argument("--alto", type=int, default=1080)
    aparcador.add_argument("--fps", type=int, default=30)
    aparcador.add_argument("--calidad", default="alta",
                           choices=sorted(p8_render.CALIDADES))
    aparcador.add_argument("--hyper", default=None)
    aparcador.add_argument("--capa", default=None)
    aparcador.add_argument("--sin-transicion", action="store_true")
    aparcador.add_argument("--reparto", action="store_true",
                           help="ademas, la curva de N procesos a la vez")
    aparcador.add_argument("--json", default=None)
    args = aparcador.parse_args(argv)

    ficha = medir(fotogramas=args.fotogramas,
                  resolucion=(args.ancho, args.alto), fps=args.fps,
                  calidad=args.calidad, hyper=args.hyper, capa=args.capa,
                  con_transicion=not args.sin_transicion)
    tabla = reparto(ficha)
    print(f"MEDIDO sobre {ficha['fotogramas']} fotogramas de "
          f"{ficha['resolucion'][0]}x{ficha['resolucion'][1]} a {ficha['fps']} fps, "
          f"calidad {ficha['calidad']}")
    print(f"  hyperframe {ficha['hyperframe']}, capa de {ficha['capa_bytes']} bytes")
    print(f"  condiciones: {ficha['condiciones']}")
    print()
    for nombre, valor in ficha["segundos"].items():
        print(f"  {nombre:<18} {valor:8.2f} s")
    print()
    print(f"  UN FOTOGRAMA DE VIDEO cuesta {ficha['s_por_fotograma']:.3f} s")
    for nombre, valor in tabla.items():
        print(f"    {nombre:<20} {valor['s']:7.4f} s  {valor['pct']:5.1f} %")
    minutos = ficha["s_por_fotograma"] * ficha["fps"] * 148 / 60.0
    print()
    print(f"  extrapolado a 2:28 de video, en UN proceso: {minutos:.0f} min")
    curva = {}
    if args.reparto:
        print()
        print("  CON N PROCESOS A LA VEZ (que es como corre p8 desde el 21-08):")
        curva = medir_reparto(hyper=args.hyper, capa=args.capa,
                              resolucion=(args.ancho, args.alto), fps=args.fps)
        for cuantos, velocidad in curva.items():
            print(f"    {cuantos:>3} proceso(s): {velocidad:6.2f} fotogramas/s"
                  f"   -> 2:28 en {148 * args.fps / velocidad / 60:5.1f} min")
    if args.json:
        medios.escribir_json(args.json, {"medida": ficha, "reparto": tabla,
                                         "procesos": curva})
        print(f"  escrito en {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
