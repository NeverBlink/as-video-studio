"""
Paso 8: render a MP4.

Compone hyperframe + ventana de zoom + capa vectorial, captura los fotogramas
con Edge headless por CDP y ensambla con ffmpeg mezclando la pista de voz.

Por que un navegador y no PIL: la capa vectorial va animada (SMIL), y el
navegador sabe pintarla en un instante concreto con setCurrentTime. Ademas es el
mismo motor que ve el humano en la pantalla de revision, asi que lo aprobado y
lo renderizado son la misma imagen.

Se renderiza POR ESCENA a clips independientes que luego se concatenan sin
recodificar: rehacer un plano cuesta un clip, no el video entero. Por eso las
transiciones van cocidas en los primeros fotogramas del clip que entra, sobre el
ultimo fotograma del clip anterior; asi ningun clip depende del siguiente y las
duraciones siguen cuadrando al milimetro con la narracion.

Las transiciones son una SEGUNDA PASADA con WebGL sobre los fotogramas ya
escritos (ver pasos/transiciones.py): se captura el clip limpio y despues se
vuelven a pintar sus primeros N fotogramas mezclando el ultimo del plano
anterior con un shader. Antes se cocian en el DOM de esta pagina -- una capa con
el fotograma anterior y una opacidad--, lo que solo daba para fundido y
destello; con las texturas en la mano entra el catalogo entero de hyperframes.

Como lo llama el orquestador:

    resultado = p8_render.ejecutar(proyecto, params, avisar)      # o unidades=[...]
    estado.completar("render", resultado["salidas"], resultado["unidades"])

Salidas: {"mp4", "duracion", "clips": {escena: ruta}, "fps", "resolucion"}.
"""
import base64
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import websocket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cartelas  # noqa: E402
import estadisticas  # noqa: E402
import medios  # noqa: E402
import sonido  # noqa: E402
import transiciones  # noqa: E402

PARAMS_POR_DEFECTO = {
    "fps": 30,
    "resolucion": [1920, 1080],
    "calidad_video": "alta",       # alta | media | baja
    # Duracion BASE de una transicion. Cada una la multiplica por su factor (un
    # latigazo es corto por definicion, una fuga de luz necesita respirar) y
    # ninguna puede comerse mas de una fraccion del plano que entra.
    "duracion_transicion": 0.4,
    # QUE transiciones entran en este video. Vacio = las de fabrica.
    #
    # Es un parametro del RENDER y no del plan a proposito: el plan decide DONDE
    # va un acento -- eso pertenece al corte y se decide con el guion delante --
    # y esto decide CUAL. Asi cambiar la paleta de transiciones deja obsoleto el
    # render y nada mas: ni las imagenes ni las capas.
    "transiciones": [],
    "conservar_frames": False,
    # CUANTOS PROCESOS DE CAPTURA A LA VEZ. 0 = automatico (ver LOTES_A_LA_VEZ),
    # 1 = en fila. Es una palanca de VELOCIDAD pura: el video sale identico
    # byte a byte se reparta como se reparta, porque cada proceso corre el mismo
    # navegador sobre la misma pagina. Por eso vive en los params del render y
    # no en el plan.
    "lotes": 0,
    "audio": None,                 # por defecto, el wav del paso voz
    # ------------------------------------------------------------- sonido
    # El interruptor general. Con esto en False el video sale como salia antes:
    # solo la locucion.
    "sonido": True,
    # El tema de fondo elegido a mano en la pantalla, ya descargado al banco:
    #   {"fuente","id","titulo","artista","duracion","licencia",...}
    # Se guarda la FICHA y no una busqueda: una busqueda en Jamendo devuelve
    # cosas distintas cada semana, y el mismo plan tiene que dar el mismo video.
    "musica": {},
    # Los efectos que hay en el banco para cada papel, tambien elegidos una vez:
    #   {"transicion_suave": [ficha, ...], "tecla": [...], ...}
    # Renderizar NO sale a la red: coge de aqui y reparte por semilla.
    "efectos": {},
    "musica_lufs": sonido.MUSICA_LUFS,
    # CUANTA MUSICA, EN ESTE VIDEO. Un ajuste en dB sobre el nivel del canal
    # (`sonido.MUSICA_SUBIDA_DB`), no un nivel absoluto: el canal decide como
    # suena su musica y esto solo corrige un video concreto. Es el mando que
    # mueve el repaso cuando alguien dice «la musica esta alta» -- y cambiarlo
    # solo obliga a remuxear, ni una imagen ni un clip.
    "musica_db": 0.0,
    # Y CUANTOS EFECTOS. El gemelo del de arriba, y por el mismo motivo: es el
    # mando que se mueve cuando alguien dice «los golpes suenan muy fuerte».
    # Lo que iguala unos efectos con otros va aparte y siempre puesto
    # (`sonido.igualar_por_papel`); esto decide cuanto suenan TODOS.
    "efectos_db": 0.0,
}

CALIDADES = {
    "alta": {"crf": "16", "preset": "slow"},
    "media": {"crf": "20", "preset": "medium"},
    "baja": {"crf": "26", "preset": "veryfast"},
}


def describir(params):
    """Frase corta con lo que hara el paso con estos parametros."""
    p = _con_defectos(params)
    ancho, alto = p["resolucion"]
    lotes = int(p.get("lotes") or 0)
    reparto = ("en fila" if lotes == 1 else
               f"{lotes} planos a la vez" if lotes > 1 else
               "varios planos a la vez, uno por proceso")
    return (f"Renderiza cada plano a un clip {ancho}x{alto} a {p['fps']} fps "
            f"(calidad {p['calidad_video']}, {reparto}), con el zoom leido del "
            f"hyperframe y la capa vectorial encima, encadena con "
            f"{transiciones.describir(p)} y concatena sin recodificar mezclando "
            f"la narracion con {sonido.describir(p)}.")


def _con_defectos(params):
    p = dict(PARAMS_POR_DEFECTO)
    p.update(params or {})
    p["resolucion"] = list(p["resolucion"])
    return p


# --------------------------------------------------------------- navegador

class Navegador:
    """Edge headless manejado por CDP: una pestana que se pinta y se captura."""

    def __init__(self, ancho, alto):
        self.perfil = tempfile.mkdtemp(prefix="edge_render_")
        self.puerto = _puerto_libre()
        # LO QUE EDGE ESCUPE AL MORIR, A UN FICHERO Y NO A /dev/null. Iba a
        # DEVNULL, asi que cuando el navegador moria al nacer no quedaba ni una
        # linea que leer y el unico sintoma era «no abrio el puerto». Vive
        # dentro del perfil, que es temporal y se borra en `cerrar`.
        self.registro = os.path.join(self.perfil, "edge.log")
        self._registro = open(self.registro, "w", encoding="utf-8", errors="replace")
        self.proceso = subprocess.Popen(
            [medios.edge(), "--headless=new", "--disable-gpu", "--no-first-run",
             "--disable-extensions", "--hide-scrollbars", "--mute-audio",
             "--force-device-scale-factor=1", "--disable-lcd-text",
             f"--user-data-dir={self.perfil}",
             # sin esto el navegador rechaza el websocket con 403: desde la
             # version 111 exige declarar el origen de quien lo pilota
             "--remote-allow-origins=*",
             # Y sin esto las transiciones no pueden pintarse. En 'file://' cada
             # documento tiene ORIGEN OPACO, asi que un PNG del disco es
             # cross-origin para la pagina del disco que lo carga y WebGL se
             # niega a subirlo como textura ("the image element contains
             # cross-origin data"). Da igual que sea el fotograma que acabamos
             # de escribir nosotros. El perfil es temporal, headless y solo abre
             # las paginas que genera este paso.
             "--allow-file-access-from-files",
             f"--remote-debugging-port={self.puerto}",
             f"--window-size={int(ancho)},{int(alto)}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=self._registro,
            **medios.SIN_VENTANA)
        try:
            self.ws = websocket.create_connection(self._url_pestana(), timeout=60)
            self._id = 0
            self.rAF = True
            self.llamar("Page.enable")
            self.llamar("Emulation.setDeviceMetricsOverride",
                        width=int(ancho), height=int(alto), deviceScaleFactor=1,
                        mobile=False)
        except Exception:
            # UN NAVEGADOR QUE NO LLEGA A NACER TAMBIEN SE RECOGE. Sin esto,
            # cada intento fallido dejaba el proceso suelto y un perfil temporal
            # en disco -- y son DIECISEIS por tanda, asi que el sintoma de la
            # noche del 28-08 habria ido dejando carpetas de perfil cada vez.
            self.ws = None
            self.cerrar()
            raise

    def _url_pestana(self, espera=30):
        """La pestana que se va a pilotar, esperando a que Edge abra el puerto.

        Y MIRANDO SI EL PROCESO SIGUE VIVO, que es lo que faltaba. Esto hacia
        polling del puerto durante treinta segundos y NUNCA preguntaba por el
        proceso: un Edge que muere al instante --el caso real, con el servicio
        del 8020 protegido: los 16 procesos del render morian al nacer-- se
        reportaba medio minuto despues como «no abrio el puerto de depuracion»,
        que manda a investigar la red cuando lo que hay que mirar es por que
        murio. Ahora se dice en cuanto pasa, con su codigo de salida y con lo
        ultimo que escribio.
        """
        limite = time.time() + espera
        while time.time() < limite:
            codigo = self.proceso.poll()
            if codigo is not None:
                raise RuntimeError(
                    f"Edge se ha cerrado solo con codigo {codigo} sin abrir el "
                    f"puerto de depuracion (tardo "
                    f"{espera - max(0.0, limite - time.time()):.1f} s). Mira "
                    f"quien es el proceso PADRE: bajo un servicio protegido "
                    f"Edge no llega a arrancar." + self._ultimo_error())
            try:
                listado = requests.get(f"http://127.0.0.1:{self.puerto}/json/list",
                                       timeout=2).json()
                for ficha in listado:
                    if ficha.get("type") == "page" and ficha.get("webSocketDebuggerUrl"):
                        return ficha["webSocketDebuggerUrl"]
            except Exception:
                time.sleep(0.25)
        raise RuntimeError("Edge no abrio el puerto de depuracion en "
                           f"{espera} s y sigue vivo (PID {self.proceso.pid})"
                           + self._ultimo_error())

    def _ultimo_error(self, lineas=4):
        """Lo ultimo que Edge escribio en su registro, para el mensaje. -> str"""
        try:
            self._registro.flush()
            with open(self.registro, "r", encoding="utf-8", errors="replace") as fh:
                sueltas = [l.strip() for l in fh.read().splitlines() if l.strip()]
        except OSError:
            return ""
        return ("\n" + "\n".join(sueltas[-lineas:])) if sueltas else ""

    def llamar(self, metodo, **params):
        self._id += 1
        self.ws.send(json.dumps({"id": self._id, "method": metodo, "params": params}))
        while True:
            mensaje = json.loads(self.ws.recv())
            if mensaje.get("id") != self._id:
                continue                       # los eventos no interesan aqui
            if "error" in mensaje:
                raise RuntimeError(f"{metodo}: {mensaje['error']}")
            return mensaje.get("result", {})

    def abrir(self, ruta_html):
        url = "file:///" + os.path.abspath(ruta_html).replace("\\", "/")
        self.llamar("Page.navigate", url=url)
        limite = time.time() + 30
        while time.time() < limite:
            listo = self.evaluar("document.readyState === 'complete' && "
                                 "typeof pintar === 'function'")
            if listo:
                return
            time.sleep(0.1)
        raise RuntimeError(f"la pagina no acabo de cargar: {ruta_html}")

    def evaluar(self, expresion, esperar=False):
        resultado = self.llamar("Runtime.evaluate", expression=expresion,
                                returnByValue=True, awaitPromise=bool(esperar))
        return (resultado.get("result") or {}).get("value")

    def pintar(self, t):
        """Pone la pagina en el instante t y espera a que quede pintada.

        `Promise.resolve(...)` porque `pintar` PUEDE devolver una promesa. Hoy
        devuelve un 1 pelado en todos los planos --la pagina no cambia ninguna
        imagen a mitad de plano: un plano es UNA imagen
        (24-08-2026)-- y aun asi se envuelve: envolver vale para los dos casos y
        preguntarle a la pagina de que clase es su respuesta es como se acaba
        con dos caminos y uno de los dos viejo.
        """
        self.evaluar(f"Promise.resolve(pintar({t:.4f}))", esperar=True)
        if not self.rAF:
            return
        try:
            self.evaluar("new Promise(r=>requestAnimationFrame("
                         "()=>requestAnimationFrame(()=>r(1))))", esperar=True)
        except Exception:
            # sin ventana visible el navegador puede no servir rAF; el propio
            # captureScreenshot fuerza un frame, asi que se sigue sin esperar
            self.rAF = False

    def capturar(self, destino):
        datos = self.llamar("Page.captureScreenshot", format="png",
                            captureBeyondViewport=False)
        with open(destino, "wb") as fh:
            fh.write(base64.b64decode(datos["data"]))
        return destino

    def cerrar(self):
        try:
            self.ws.close()
        except Exception:
            pass
        self.proceso.terminate()
        try:
            self.proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proceso.kill()
        try:
            self._registro.close()
        except Exception:
            pass
        shutil.rmtree(self.perfil, ignore_errors=True)


def _puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ----------------------------------------------------------------- pagina

PAGINA = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:#0b0c09;overflow:hidden}
#lienzo{position:relative;width:__W__px;height:__H__px;overflow:hidden}
#camara{position:absolute;left:0;top:0;transform-origin:0 0;will-change:transform}
#fondo{display:block;width:__HW__px;height:__HH__px}
#capa{position:absolute;left:0;top:0;width:__HW__px;height:__HH__px}
/* SOLO EL HIJO DIRECTO (`>`), y no es estilo: en vertical la capa lleva la
   composicion de la cartela ANIDADA en un segundo <svg> escalado a la banda
   del medio (cartelas._svg). Con `#capa svg` esa regla alcanzaba tambien al
   anidado, le imponia el ancho del hyperframe entero y el titulo salia del
   cuadro por la izquierda. Se vio en el primer MP4 vertical (02-09-2026). */
#capa > svg{width:__HW__px;height:__HH__px;display:block}
/* z-index EXPLICITO y no solo el orden del DOM. Por orden ya quedaba encima,
   pero eso depende de que nadie le ponga un transform o un will-change a
   #capafija: el dia que pase, el velo de una cabecera --que va dentro de
   #camara y cubre el cuadro entero-- se comeria el subtitulo, y eso no da
   error, da un subtitulo apagado. Se dice, y asi no hay que deducirlo. */
#camara{z-index:0}
#capafija{position:absolute;left:0;top:0;width:__W__px;height:__H__px;z-index:1}
#capafija > svg{width:__W__px;height:__H__px;display:block}
</style></head><body>
<!-- DOS CAPAS, Y LA DIFERENCIA ES EN QUE LADO DEL TRANSFORM ESTAN.
     #capa va DENTRO de #camara, asi que la escala el zoom: ahi vive lo que
     acompana al plano (la cartela con su velo, la cabecera de capitulo).
     #capafija va FUERA, en pixeles del cuadro de salida: ahi vive el subtitulo,
     y por eso se queda quieto mientras la imagen se acerca debajo. Era una sola
     capa y el subtitulo hacia zoom con la imagen; el canal lo vio montado y
     pidio que no se moviera (PENDIENTE 38). -->
<div id="lienzo">
  <div id="camara">
    <img id="fondo" src="__FONDO__">
    <div id="capa">__CAPA__</div>
  </div>
  <div id="capafija">__CAPAFIJA__</div>
</div>
<script>
// Esta pagina pinta el plano LIMPIO: su zoom y su capa animada, y nada mas. La
// transicion con el plano anterior se pinta despues, sobre los PNG ya escritos
// (pasos/transiciones.py). Antes se cocia aqui, con una capa que llevaba el
// ultimo fotograma del plano anterior y una opacidad encima; eso daba para un
// fundido y para un destello, y para nada mas, porque el shader necesita las
// dos imagenes como TEXTURAS y de un div no se saca una textura.
const MOV = __MOV__, W = __W__, H = __H__, HW = __HW__, HH = __HH__;
const DUR = __DUR__, FPS = __FPS__;
// AQUI VIVIA `FOTOGRAMAS`, la tira de imagenes de un plano de metraje grabado.
// Se retiro entera con la pool de clips: todos los planos son una imagen quieta,
// asi que el render vuelve a saber de una sola cosa -- una imagen y una ventana
// que se mueve por encima.
const camara = document.getElementById('camara');
const fondo = document.getElementById('fondo');
const svg = document.querySelector('#capa svg');
const svgFijo = document.querySelector('#capafija svg');
if (svg && svg.pauseAnimations) svg.pauseAnimations();
// La capa quieta tambien lleva SMIL (el subtitulo entra y sale con la voz), asi
// que hay que congelarla y moverla a mano igual que la otra: si corriera sola,
// cada fotograma la pillaria donde le tocase por reloj de pared.
if (svgFijo && svgFijo.pauseAnimations) svgFijo.pauseAnimations();

function suavizar(u){ return u*u*(3-2*u); }

// La ventana que da el motor de movimiento es cuadrada en normalizado; el video
// es 16:9, asi que se respeta el ancho y se recorta el alto sobre el mismo
// centro. Recortar aqui y no en el motor evita tocar lo que ya usan otros pasos.
function ventana(u){
  const a = MOV.ventana_ini, b = MOV.ventana_fin, e = suavizar(u);
  const x = a[0] + (b[0]-a[0])*e, y = a[1] + (b[1]-a[1])*e;
  const w = a[2] + (b[2]-a[2])*e, h = a[3] + (b[3]-a[3])*e;
  const cx = (x + w/2) * HW, cy = (y + h/2) * HH;
  // EL LADO QUE MANDA ES EL QUE LIMITA. Con salida mas ancha que el plano
  // (16:9 sobre 3:2) manda el ancho y se recorta el alto; con salida mas alta
  // (9:16 sobre 2:3) manda el ALTO y se recorta el ancho. Antes mandaba
  // siempre el ancho y en vertical el tope del alto se comia el zoom entero:
  // todos los planos salian a ventana completa, sin acercarse ni alejarse.
  let pw, ph;
  if (W / H >= HW / HH) {
    pw = w * HW; ph = pw * H / W;
    if (ph > HH) { ph = HH; pw = ph * W / H; }
  } else {
    ph = h * HH; pw = ph * W / H;
    if (pw > HW) { pw = HW; ph = pw * H / W; }
  }
  let px = Math.min(Math.max(cx - pw/2, 0), HW - pw);
  let py = Math.min(Math.max(cy - ph/2, 0), HH - ph);
  return [px, py, pw];
}

function pintar(t){
  const u = DUR > 0 ? Math.min(1, Math.max(0, t/DUR)) : 0;
  const v = ventana(u), s = W / v[2];
  camara.style.transform =
    'translate(' + (-v[0]*s).toFixed(3) + 'px,' + (-v[1]*s).toFixed(3) +
    'px) scale(' + s.toFixed(6) + ')';
  if (svg && svg.setCurrentTime) svg.setCurrentTime(t);
  if (svgFijo && svgFijo.setCurrentTime) svgFijo.setCurrentTime(t);
  // Sigue devolviendo 1 y no undefined: quien llama hace
  // `Promise.resolve(pintar(t))`, asi que un valor pelado vale igual.
  return 1;
}
pintar(0);
</script></body></html>"""


def _url_local(ruta):
    return "file:///" + os.path.abspath(ruta).replace("\\", "/")


def _pagina_de(escena, mov, capa_svg, hyper, p, destino, capa_fija="", fps=30):
    ancho, alto = [int(v) for v in p["resolucion"]]
    hw, hh = mov.get("hyperframe_px") or [3072, 2048]
    duracion = float(escena["t_out"]) - float(escena["t_in"])
    html = (PAGINA
            .replace("__W__", str(ancho)).replace("__H__", str(alto))
            .replace("__HW__", str(hw)).replace("__HH__", str(hh))
            .replace("__FONDO__", _url_local(hyper))
            .replace("__CAPA__", capa_svg)
            .replace("__CAPAFIJA__", capa_fija or "")
            .replace("__MOV__", json.dumps({"ventana_ini": mov["ventana_ini"],
                                            "ventana_fin": mov["ventana_fin"]}))
            .replace("__FPS__", str(int(fps)))
            .replace("__DUR__", f"{duracion:.4f}"))
    return medios.escribir_texto(destino, html)


# ------------------------------------------------------------------ ffmpeg

def _codificar(dir_frames, destino, fps, calidad):
    ajustes = CALIDADES.get(calidad) or CALIDADES["media"]
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error",
             "-framerate", str(fps), "-i", os.path.join(dir_frames, "f%05d.png"),
             "-c:v", "libx264", "-preset", ajustes["preset"], "-crf", ajustes["crf"],
             "-pix_fmt", "yuv420p", "-r", str(fps), destino]
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=3600,
                             **medios.SIN_VENTANA)
    if proceso.returncode != 0 or not os.path.exists(destino):
        raise RuntimeError(f"ffmpeg fallo con {destino}: {proceso.stderr[-400:]}")
    return destino


def _medir_mezcla(orden):
    """Corre la pasada de analisis y devuelve lo que midio `loudnorm`. -> dict|None

    El filtro escribe un JSON al final de stderr y no a la salida estandar, asi
    que se busca el ULTIMO objeto que haya ahi. Nunca levanta: una medida que no
    sale deja el video sin masterizar --como salia hasta el 28-08-2026-- y eso es
    degradar, no romper. Tumbar un render de veinte minutos porque ffmpeg cambio
    el formato de un informe seria la peor forma de enterarse.
    """
    # Y CON EL REGISTRO ABIERTO. El resto del paso llama a ffmpeg con
    # `-loglevel error` --lo que se quiere de un mux es silencio-- y `loudnorm`
    # escribe su informe a nivel `info`: con el nivel de siempre, esta funcion
    # devolveria None SIEMPRE y el video saldria sin masterizar sin decir nada.
    orden = list(orden)
    for indice, arg in enumerate(orden[:-1]):
        if arg == "-loglevel":
            orden[indice + 1] = "info"
    try:
        proceso = subprocess.run(orden, capture_output=True, text=True,
                                 timeout=900, **medios.SIN_VENTANA)
    except Exception:                                          # noqa: BLE001
        return None
    salida = (proceso.stderr or "") + (proceso.stdout or "")
    abre = salida.rfind("{")
    if proceso.returncode != 0 or abre < 0:
        return None
    try:
        medida = json.loads(salida[abre:salida.rfind("}") + 1])
    except ValueError:
        return None
    if not all(k in medida for k in ("input_i", "input_tp", "input_lra",
                                     "input_thresh")):
        return None
    try:
        # con silencio absoluto `loudnorm` devuelve '-inf', y eso no se puede
        # aplicar: mejor sin masterizar que con una ganancia infinita
        for clave in ("input_i", "input_tp", "input_lra", "input_thresh"):
            if not math.isfinite(float(medida[clave])):
                return None
    except (TypeError, ValueError):
        return None
    return medida


#: Lo que se le anade al final: negro, DESPUES del ultimo plano. No es un
#: fundido sobre los ultimos segundos --eso se comeria contenido--, es cola: el
#: video termina tres segundos despues de la ultima silaba en vez de en ella.
COLA_NEGRO_S = 3.0

#: Y el negro ENTRA desde el ultimo fotograma en vez de aparecer de golpe. Es
#: el mismo motivo por el que existe la cola: cortar en seco de un dibujo a
#: negro se lee como que el fichero se ha roto.
ENTRADA_NEGRO_S = 0.8


def _cola_negra(clips, trabajo, fps, calidad, segundos=COLA_NEGRO_S):
    """Anade al final un clip de negro. -> [rutas]

    SE ANADE, NO SE FUNDE. La primera version fundia a negro los ultimos tres
    segundos del video, y eso es otra cosa: se lleva por delante tres segundos
    de lo que se esta diciendo. Aqui el contenido se queda entero y el negro va
    detras.

    El clip sale del ULTIMO FOTOGRAMA del ultimo plano, no de un negro liso: se
    funde desde el a negro y despues se queda quieto, asi que la salida es una
    transicion y no un corte. Se codifica con los mismos ajustes que los demas
    clips porque la concatenacion va con `-c:v copy` y no admite mezclar
    formatos.

    Si algo falla se devuelve la lista tal cual: antes un video sin cola que
    ningun video.
    """
    if not clips or segundos <= 0:
        return clips
    carpeta = os.path.join(trabajo, "_cola")
    os.makedirs(carpeta, exist_ok=True)
    ultimo, fotograma = clips[-1], os.path.join(carpeta, "ultimo.png")
    negro = os.path.join(carpeta, "cola.mp4")
    ajustes = CALIDADES.get(calidad) or CALIDADES["media"]
    entrada = min(ENTRADA_NEGRO_S, segundos)
    try:
        # el ultimo fotograma del ultimo clip
        sacar = subprocess.run(
            [medios.ffmpeg(), "-y", "-loglevel", "error", "-sseof", "-0.2",
             "-i", ultimo, "-update", "1", "-frames:v", "1", fotograma],
            capture_output=True, text=True, timeout=120, **medios.SIN_VENTANA)
        if sacar.returncode != 0 or not os.path.exists(fotograma):
            return clips
        hacer = subprocess.run(
            [medios.ffmpeg(), "-y", "-loglevel", "error", "-loop", "1",
             "-framerate", str(fps), "-t", f"{segundos:g}", "-i", fotograma,
             "-vf", f"fade=t=out:st=0:d={entrada:g}:color=black",
             "-c:v", "libx264", "-preset", ajustes["preset"],
             "-crf", ajustes["crf"], "-pix_fmt", "yuv420p", "-r", str(fps),
             "-an", negro],
            capture_output=True, text=True, timeout=300, **medios.SIN_VENTANA)
        if hacer.returncode != 0 or not os.path.exists(negro):
            return clips
    except Exception:                                       # noqa: BLE001
        return clips
    return list(clips) + [negro]

def _concatenar(clips, destino, audio, desfase, trabajo, musica=None,
                efectos=None, duracion=0.0, lufs=None, cama=False,
                ajuste_db=0.0, fps=12, calidad="media", efectos_db=0.0):
    """Une los clips sin recodificar y mezcla la banda sonora.

    La banda son tres pistas: la locucion, el tema de fondo agachado bajo ella
    (`sidechaincompress`) y los efectos. La musica y los efectos son opcionales
    y NO cambian nada del video: se mezclan al muxear, asi que cambiarlos vuelve
    a montar el MP4 sin recodificar un solo clip.
    """
    faltan = [os.path.basename(c) for c in clips if not os.path.exists(c)]
    if faltan:
        raise RuntimeError(f"no se puede montar el video, faltan clips: {faltan}. "
                           f"Renderiza el paso entero antes de rehacer planos sueltos")
    # LA COLA DE NEGRO. Se hace aqui y no en el clip de cada plano porque
    # depende del ORDEN: es el final del VIDEO, no el de una escena, y hasta
    # que no estan todos no se sabe cual es el ultimo.
    clips = _cola_negra(clips, trabajo, fps, calidad)
    lista = os.path.join(trabajo, "clips.txt")
    with open(lista, "w", encoding="utf-8") as fh:
        for clip in clips:
            fh.write("file '" + clip.replace("\\", "/") + "'\n")
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", lista]
    if audio and os.path.exists(audio):
        # el primer plano empieza en la primera palabra, no en el silencio de
        # cabecera: la voz entra recortada por ahi para no desincronizar
        orden += ["-ss", f"{max(0.0, float(desfase)):.3f}", "-i", audio]
        con_musica = bool(musica and os.path.exists(musica))
        con_efectos = bool(efectos and os.path.exists(efectos))
        if con_musica:
            # la CAMA ya viene del largo exacto del video; un tema suelto va en
            # bucle, porque uno de dos minutos tiene que cubrir doce y el corte
            # se lo lleva el atrim del grafo
            if not cama:
                orden += ["-stream_loop", "-1"]
            orden += ["-i", musica]
        if con_efectos:
            orden += ["-i", efectos]
        if con_musica or con_efectos:
            def mezcla(medida=None):
                return sonido.filtro_de_mezcla(
                    con_musica, con_efectos, max(0.1, float(duracion)),
                    lufs if lufs is not None else sonido.MUSICA_LUFS,
                    ya_normalizada=cama, ajuste_db=ajuste_db,
                    master=True, medida=medida, efectos_db=efectos_db)
            # LA PASADA QUE MIDE, con el MISMO grafo y sin escribir nada. Ver
            # `sonido.filtro_master`: la medida es lo que convierte el
            # `loudnorm` de adaptativo --que sobre voz con musica se oye como
            # bombeo-- en una ganancia constante. Si falla se sigue sin
            # masterizar, que es como salia el video hasta el 28-08.
            medida = _medir_mezcla(orden + ["-filter_complex", mezcla(),
                                            "-map", "[salida]", "-f", "null", "-"])
            orden += ["-filter_complex", mezcla(medida),
                      "-map", "0:v", "-map", "[salida]"]
        else:
            orden += ["-map", "0:v", "-map", "1:a"]
        # SIN `-shortest`: la locucion acaba antes que el video --le sobran los
        # tres segundos de cola-- y con el la salida se recortaba ahi, que es
        # exactamente quitar lo que se acaba de anadir. Manda el video.
        orden += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k"]
    else:
        orden += ["-c", "copy"]
    # +faststart: el indice del MP4 (el atomo `moov`) al PRINCIPIO en vez de al
    # final. Sin esto, un navegador que quiere reproducir tiene que descargarse
    # el fichero entero antes de poder empezar -- el indice esta detras --, y
    # por eso el preview del video renderizado tardaba una eternidad en arrancar
    # y no dejaba saltar a un plano concreto hasta tenerlo todo. Es una segunda
    # pasada de ffmpeg sobre el fichero ya escrito: no recodifica nada.
    orden += ["-movflags", "+faststart"]
    orden.append(destino)
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=3600,
                             **medios.SIN_VENTANA)
    if proceso.returncode != 0 or not os.path.exists(destino):
        raise RuntimeError(f"ffmpeg no pudo concatenar: {proceso.stderr[-400:]}")
    return destino


# -------------------------------------------------------------- reproductor

def reproductor(proyecto):
    """Donde esta el video montado y el clip de cada plano.

    Lo consume el reproductor de revision: para tomar una captura del paso 8
    hace falta el MP4 exacto que se esta viendo, y para situarla en un plano
    hacen falta los cortes con los que se monto ESA version, no los del plan.
    """
    from nucleo.estado import Estado

    ruta = medios.salida_de(proyecto, "render", claves=("mp4",),
                            patrones=(r"video\.mp4",))
    try:
        salidas = Estado(proyecto).salidas("render")
    except Exception:  # noqa: BLE001
        salidas = {}
    clips = {}
    if ruta:
        dir_clips = os.path.join(os.path.dirname(ruta), "clips")
        if os.path.isdir(dir_clips):
            for nombre in sorted(os.listdir(dir_clips)):
                if nombre.lower().endswith(".mp4"):
                    clips[os.path.splitext(nombre)[0]] = \
                        os.path.join(dir_clips, nombre)
    return {"mp4": ruta,
            "clips": clips,
            "duracion": salidas.get("duracion"),
            "fps": salidas.get("fps") or PARAMS_POR_DEFECTO["fps"],
            "resolucion": salidas.get("resolucion")
            or list(PARAMS_POR_DEFECTO["resolucion"])}


# ------------------------------------------------------------------ ejecutar

def _cocer_transicion(navegador, pagina_trans, anterior, carpeta, total, fps,
                      corte):
    """Repinta los primeros fotogramas del clip mezclandolos con el anterior.

    Se hace DESPUES de capturar el clip limpio, y no mientras: el shader
    necesita las dos imagenes como texturas, y de la pagina de la escena --que
    es un div con una transformacion y un SVG dentro-- no se saca una textura
    sin capturar el DOM, que es la parte fragil del montaje original.

    El tope de fotogramas es el propio plano: una transicion mas larga que el
    plano que entra no existe, y en un plano de un segundo con un `light-leak`
    de 0,6 s el calculo daba mas fotogramas de los que hay.
    """
    cuantos = min(total, int(round(fps * float(corte.get("duracion") or 0))))
    if cuantos <= 0:
        return 0
    navegador.abrir(pagina_trans)
    for indice, progreso in enumerate(transiciones.progresos(cuantos)):
        marco = os.path.join(carpeta, f"f{indice + 1:05d}.png")
        transiciones.componer(navegador, anterior, marco, progreso,
                              corte["shader"], marco)
    return cuantos


# ------------------------------------------------- los planos, en paralelo
#
# EL TECHO NO ERA EL NAVEGADOR: ERA EL PROCESO DE PYTHON. Medido el 21-08-2026
# con `pasos/medir_render.py`, headless y con el escritorio remoto cerrado, que
# son las condiciones de verdad:
#
#     capturar el PNG      0,461 s/fotograma   82 %
#     transiciones         0,062 s             11 %   (tambien son capturas)
#     pintar la pagina     0,027 s              5 %
#     codificar el clip    0,011 s              2 %
#     montar el video      0,000 s              0 %
#
# O sea que el 93 % del render son capturas, y el montaje --que es lo que se
# portaria a MLT-- es el 2 %. Un fotograma de 1920x1080 sale de Edge como un
# PNG de 1,1 MB que viaja en base64 por el websocket de CDP, y ese tubo da 7
# MB/s: 210 ms de puro viaje mas 350 ms de comprimir.
#
# Y lo que de verdad importa, porque es lo que abre la puerta: con HILOS eso no
# escala. Cuatro navegadores en cuatro hilos dan 4,0 fotogramas/s y ocho dan
# 4,1 -- el mismo techo --, porque el trabajo por fotograma que hace PYTHON
# (recomponer el mensaje, parsear 1,5 MB de JSON y descodificar el base64) no
# se puede repartir dentro de un proceso. Con PROCESOS escala casi lineal:
#
#     1 navegador                    1,7 fotogramas/s
#     4 en hilos                     4,0        8 en hilos   4,1
#     4 en procesos                  5,9
#     8 en procesos                 10,4
#    16 en procesos                 16,9        -> 2:28 de video en 4,4 min
#
# Por eso cada LOTE de planos corre en su propio proceso. Y son procesos de
# verdad lanzados con subprocess, no un ProcessPoolExecutor: esto vive dentro
# del servidor, y `spawn` en Windows reimporta el `__main__` del padre.
#
# Los planos se reparten SALTEADOS y no en tramos seguidos, por la unica
# dependencia que hay entre ellos (la transicion mira al plano de antes): ver
# `_repartir_lotes`.
#
# Lo que NO cambia: el mismo Edge, la misma pagina, el mismo codigo y los
# mismos PNG. La imagen es identica byte a byte -- solo cambia quien la pide.

#: Cuantos lotes de planos a la vez. 0 = automatico, 1 = en fila (que es como
#: iba hasta el 21-08-2026 y lo que sigue haciendo cuando solo hay un plano que
#: rehacer). El automatico sale de la medida: escala hasta 16 y ahi ya son ~6
#: GB de navegadores, que en esta maquina de 30 GB es la mitad justa.
LOTES_A_LA_VEZ = 0
MAX_LOTES = 16

#: Cuanto espera un plano a que el ANTERIOR deje su ultimo fotograma, que es lo
#: que su transicion mezcla.
#:
#: TRESCIENTOS SEGUNDOS SE QUEDABAN CORTOS, y el comentario que habia aqui decia
#: por que no se habia visto: afirmaba que «con el reparto salteado los dos van
#: en el mismo punto de sus colas, asi que la espera de verdad es de milesimas».
#: Medido sobre el render de 2:28 del video largo, es falso: los planos duran
#: cosas distintas, asi que los lotes se desincronizan, y el desfase entre un
#: plano y su anterior llego a 122 s (S031). Nunca se noto porque hasta el
#: 22-08 la espera se cumplia sola -- bastaba con que el fichero existiera, y
#: existia siempre (ver _esperar). Con la barrera de verdad puesta, esto tiene
#: que cubrir el desfase de un video largo, no el de este.
ESPERA_ANTERIOR_S = 900.0


def _python():
    """El interprete con el que lanzar un lote, con consola aunque el padre no.

    El servicio del 8020 arranca con `pythonw.exe` a proposito (start.ps1: con
    `python.exe` y la salida redirigida, Windows abre una consola negra en cada
    arranque). Pero un hijo lanzado con pythonw puede quedarse con `sys.stderr`
    a None, y entonces un lote que revienta vuelve con codigo de error y SIN una
    linea que diga por que -- que es la peor forma de fallar.
    Aqui se cambia por su `python.exe`, y la ventana la quita `SIN_VENTANA`,
    que es para lo que esta.
    """
    ejecutable = sys.executable or "python"
    if os.path.basename(ejecutable).lower() == "pythonw.exe":
        consola = os.path.join(os.path.dirname(ejecutable), "python.exe")
        if os.path.exists(consola):
            return consola
    return ejecutable


def _cuantos_lotes(p, cuantos_planos):
    """Cuantos procesos de captura correr a la vez."""
    pedidos = int(p.get("lotes") or LOTES_A_LA_VEZ)
    if pedidos > 0:
        return max(1, min(pedidos, cuantos_planos))
    # EL AUTOMATICO SE PUEDE FIJAR POR ENTORNO. La mitad de los hilos es una
    # regla buena en una maquina con SMT de sobra, pero se queda corta en una
    # de 8 vCPU: medido ahi con medir_render, 4 procesos dan 6,75 fotogramas/s
    # y 8 dan 10,40 -- un 54 % mas por no dejar nucleos parados. Con
    # ESTUDIO_LOTES sin poner no cambia nada de lo que habia.
    forzado = 0
    try:
        forzado = int(os.environ.get("ESTUDIO_LOTES") or 0)
    except ValueError:
        forzado = 0
    if forzado > 0:
        return max(1, min(forzado, MAX_LOTES, cuantos_planos))
    return max(1, min(MAX_LOTES, (os.cpu_count() or 2) // 2, cuantos_planos))


def _repartir_lotes(pendientes, cuantos):
    """Los planos a renderizar SALTEADOS, uno de cada N por proceso.

    SALTEADOS Y NO EN TRAMOS SEGUIDOS, y el motivo es la unica dependencia que
    hay entre planos: la transicion de uno se cuece sobre el ULTIMO FOTOGRAMA
    del anterior. Con tramos seguidos, el primer plano de cada lote depende del
    ULTIMO del lote de al lado, o sea de lo ultimo que hace ese proceso: con
    tres planos por lote, uno de cada tres se quedaba parado dos tercios del
    tiempo esperando. Repartiendo salteado, el plano N de un lote depende del
    plano N del lote de al lado -- que va en el mismo punto de su cola-- y la
    espera es de milesimas.

    Lo que NO se pierde por saltear: el navegador. Cada lote abre UNO para todos
    sus planos, que es lo que ahorra los medio segundos de arrancar Edge por
    plano. Y de paso los lotes quedan mejor equilibrados: un tramo seguido de
    planos largos hacia esperar a todos los demas.
    """
    if cuantos <= 1 or len(pendientes) <= 1:
        return [list(pendientes)]
    lotes = [[] for _ in range(min(cuantos, len(pendientes)))]
    for indice, tarea in enumerate(pendientes):
        lotes[indice % len(lotes)].append(tarea)
    return [lote for lote in lotes if lote]


def _fresco(ruta, desde):
    """Si ese fichero lo ha escrito ESTE render, y no el anterior."""
    try:
        return os.path.getmtime(ruta) >= float(desde)
    except OSError:
        return False


def _esperar(ruta, desde, limite=ESPERA_ANTERIOR_S):
    """Espera a que el ultimo fotograma del anterior sea DE ESTE RENDER.

    QUE EXISTA NO BASTA, y esto costo 25 de las 43 transiciones de un video.
    `trabajo/ultimo/` no se vacia nunca y `medios.sembrar_trabajo` copia dentro
    la version activa entera, asi que TODO render arranca con los ultimos
    fotogramas de la pasada anterior ya puestos. Comprobando solo la existencia,
    la barrera se cumplia al instante: con los planos repartidos salteados en
    dieciseis procesos, el plano N acaba antes que el N-1 la mitad de las veces
    y cocia su transicion contra la imagen VIEJA -- mientras su propio clip
    llevaba la nueva. Se veia como un fogonazo de otro plano justo al empezar
    cada transicion.

    Se compara con la FECHA y no borrando el fichero de antemano a proposito:
    borrar destruiria el ultimo fotograma bueno de un plano que no entra en esta
    tanda, que es justo el que ahi manda.
    """
    fin = time.time() + float(limite)
    while time.time() < fin:
        if _fresco(ruta, desde):
            return True
        time.sleep(0.2)
    return _fresco(ruta, desde)


def _guardar_ultimo(origen, destino):
    """El ultimo fotograma del plano, escrito de golpe.

    De golpe y no copiando encima porque es una SENAL: el proceso que renderiza
    el plano siguiente espera a que este fichero exista para cocer su
    transicion, y una copia a medias se leeria como un fotograma valido.
    """
    temporal = destino + ".parcial"
    medios.copiar(origen, temporal)
    medios.reemplazar(temporal, destino)
    return destino


def renderizar_plano(tarea, navegador=None):
    """Los fotogramas de UN plano, su transicion y su clip. -> ficha del plano.

    Es el cuerpo que corria dentro del bucle de `ejecutar`, sacado a una funcion
    para que lo pueda usar igual el camino en fila y el proceso de un lote. Un
    solo cuerpo: si hubiera dos, uno de los dos se quedaria viejo.
    """
    sid = tarea["id"]
    fps = int(tarea["fps"])
    total = int(tarea["frames"])
    carpeta = tarea["carpeta"]
    # SE VACIA, NO SE BORRA: el mismo Edge acaba de tener abiertos como textura
    # los PNG del plano anterior de este lote, y borrar la carpeta con un handle
    # vivo dentro la deja en BORRADO PENDIENTE -- existe para `os.path.exists`,
    # `makedirs(exist_ok=True)` no hace nada, y desaparece a mitad del bucle de
    # fotogramas. Ver `medios.rehacer_carpeta`.
    resisten = medios.rehacer_carpeta(carpeta)
    if resisten:
        # Un PNG viejo que sobrevive dentro de la secuencia f00001..fNNNNN se
        # colaria en el clip: se dice, con su nombre, en vez de renderizar
        # encima y descubrirlo mirando el video.
        print(f"[render] {sid}: {len(resisten)} fichero(s) de la pasada anterior "
              f"siguen bloqueados en {carpeta} ({os.path.basename(resisten[0])}…)",
              flush=True)
    pagina = _pagina_de(tarea["escena"], tarea["mov"], tarea["capa"],
                        tarea["hyper"], {"resolucion": tarea["resolucion"]},
                        os.path.join(carpeta, "escena.html"),
                        capa_fija=tarea.get("capa_fija") or "", fps=fps)

    navegador.abrir(pagina)
    for numero in range(total):
        navegador.pintar(numero / float(fps))
        navegador.capturar(os.path.join(carpeta, f"f{numero + 1:05d}.png"))
    # El ultimo fotograma se guarda ANTES de la transicion: es el que mira el
    # plano siguiente, y lo que tiene que mirar es este plano limpio, no este
    # plano mezclado con el anterior.
    _guardar_ultimo(os.path.join(carpeta, f"f{total:05d}.png"), tarea["ultimo"])

    corte = tarea.get("corte") or {}
    pintados = 0
    anterior = tarea.get("anterior")
    if anterior and transiciones.cuece_el_anterior(corte):
        # el plano de antes puede estar renderizandose en otro proceso: su
        # ultimo fotograma es la senal de que ya se puede mezclar con el
        listo = True
        if tarea.get("esperar_anterior"):
            listo = _esperar(anterior, tarea["desde"])
            if not listo:
                # SE DICE, no se calla. Antes daba igual porque la espera nunca
                # fallaba (bastaba con que el fichero existiera); ahora un lote
                # caido deja a su sucesor sin transicion, y un corte seco que
                # aparece sin motivo es media hora buscando en el sitio que no
                # es. El plano sale igual, con corte.
                print(f"[render] {tarea['id']}: el plano anterior "
                      f"({tarea['previo']}) no ha dejado su ultimo fotograma en "
                      f"{ESPERA_ANTERIOR_S:.0f} s; este corte va sin transicion",
                      flush=True)
        if listo and os.path.exists(anterior):
            pintados = _cocer_transicion(navegador, tarea["pagina_trans"],
                                         anterior, carpeta, total, fps, corte)

    _codificar(carpeta, tarea["clip"], fps, tarea["calidad"])
    medios.borrar(pagina)
    if not tarea.get("conservar_frames"):
        shutil.rmtree(carpeta, ignore_errors=True)
    return {"id": sid, "frames": total,
            "duracion": round(total / float(fps), 3),
            "transicion": corte.get("tipo") or "corte",
            "ranura": corte.get("ranura") or "corte",
            "frames_transicion": pintados,
            "origen": "renderizado"}


def correr_lote(tareas, senal_vivo=None):
    """Un tramo de planos con UN navegador. -> [ficha por plano].

    Arrancar Edge cuesta medio segundo y abrir su pagina otra decima; con un
    navegador por plano eso serian cincuenta arranques en un video de cincuenta
    planos. Uno por lote, y el lote son planos seguidos.

    `senal_vivo` es la ruta de un fichero que se toca EN CUANTO el navegador
    esta en pie. No es telemetria: es lo unico que el padre puede contar durante
    el arranque en frio, que son los primeros minutos del render y hasta ahora
    los pasaba en silencio (PENDIENTE 37). Va por FICHERO y no por stdout porque
    el padre recoge cada hijo con `communicate()`, que no devuelve nada hasta que
    el proceso termina.
    """
    if not tareas:
        return []
    ancho, alto = [int(v) for v in tareas[0]["resolucion"]]
    navegador = Navegador(ancho, alto)
    if senal_vivo:
        try:
            medios.escribir_texto(senal_vivo, "1")
        except Exception:                                      # noqa: BLE001
            pass          # una barra que no avanza no puede tumbar un render
    try:
        return [renderizar_plano(tarea, navegador) for tarea in tareas]
    finally:
        navegador.cerrar()


#: Cada cuanto mira el padre lo que hay en disco para mover la barra. Un
#: segundo: un plano tarda decenas de segundos, asi que mas fino no dice nada
#: nuevo y mas grueso deja huecos donde parece que se ha colgado.
LATIDO_S = 1.0


def _vigilar_avance(dir_lotes, dir_clips, ids, cuantos_lotes, desde, avisar,
                    parar):
    """Cuenta lo que hay EN DISCO y mueve la barra. Corre en su propio hilo.

    POR QUE HACE FALTA, Y NO ES UN ADORNO. Se pulsaba «Generar el MP4» y la
    barra se quedaba minutos en «44 planos en 16 procesos a la vez» antes de que
    apareciera el primer «X de 44». Dos causas, y la segunda es la gorda:

      1. los dieciseis Edge arrancan en frio, cada uno con su perfil temporal
         nuevo -- son unos 6 GB y bastante E/S --, y de eso no se decia nada;
      2. el contador iba POR LOTE. El padre espera cada lote con
         `communicate()`, o sea a que termine ENTERO, y solo entonces suma sus
         planos: con 44 planos en 16 lotes son 2-3 por lote, asi que la barra no
         se movia hasta que un lote acababa sus tres. En un video de 20 minutos
         con lotes de diez, hasta que uno hiciera los diez.

    Se mide con lo que YA EXISTE y sin canal nuevo: los `.vivo` que deja cada
    hijo al levantar su navegador, y los clips segun caen en `trabajo/clips/`.

    Y LOS CLIPS SE CUENTAN POR FRESCURA, no por existencia. `sembrar_trabajo`
    copia los clips de la version anterior a la carpeta de trabajo, asi que
    contar ficheros diria «44 de 44» en el primer segundo. Es la misma
    disciplina que ya aplica `_esperar` con el ultimo fotograma: un fichero
    cuenta cuando lo ha escrito ESTE render.

    Esto mueve la BARRA y nada mas. Lo que salio de cada plano -- la ficha del
    clip -- lo sigue leyendo el padre del `.hecho` de su lote, que es el unico
    sitio donde esta.
    """
    ultimo = None
    while not parar.is_set():
        try:
            vivos = len([n for n in os.listdir(dir_lotes) if n.endswith(".vivo")])
        except OSError:
            vivos = 0
        frescos = 0
        for sid in ids:
            clip = os.path.join(dir_clips, f"{sid}.mp4")
            try:
                if os.path.getmtime(clip) >= desde:
                    frescos += 1
            except OSError:
                pass
        if frescos:
            mensaje = f"{frescos} de {len(ids)} planos renderizados"
            fraccion = 0.05 + 0.85 * (frescos / max(1, len(ids)))
        elif vivos >= cuantos_lotes:
            mensaje = (f"{cuantos_lotes} navegadores listos, "
                       f"dibujando los primeros planos")
            fraccion = 0.05
        else:
            mensaje = (f"arrancando los navegadores: {vivos} de "
                       f"{cuantos_lotes} listos")
            fraccion = 0.02 + 0.03 * (vivos / max(1, cuantos_lotes))
        if mensaje != ultimo:
            avisar(fraccion, mensaje)
            ultimo = mensaje
        parar.wait(LATIDO_S)


def _correr_lotes_en_procesos(lotes, trabajo, avisar, total_planos,
                              dir_clips=None, desde=None):
    """Lanza un proceso por lote y recoge sus fichas. -> {sid: ficha}.

    Con `subprocess` y un fichero de tareas por lote, y no con
    `ProcessPoolExecutor`: este paso corre DENTRO del servidor, y el `spawn` de
    Windows reimporta el `__main__` del proceso padre en cada hijo -- o sea que
    levantaria otro servidor por cada lote.
    """
    dir_lotes = os.path.join(trabajo, "lotes")
    os.makedirs(dir_lotes, exist_ok=True)
    procesos = []
    for numero, tareas in enumerate(lotes):
        ficha = os.path.join(dir_lotes, f"lote{numero:02d}.json")
        medios.escribir_json(ficha, {"tareas": tareas})
        procesos.append((ficha, subprocess.Popen(
            [_python(), os.path.abspath(__file__), "--lote", ficha],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", **medios.SIN_VENTANA)))
    avisar(0.02, f"{total_planos} planos en {len(lotes)} procesos: "
                 f"arrancando los navegadores")

    # LA BARRA LA MUEVE UN VIGILANTE, no la recogida. Ver `_vigilar_avance`: la
    # recogida solo puede hablar cuando un lote ENTERO termina, y eso son
    # minutos de silencio al principio y saltos de tres planos despues.
    ids = [t["id"] for lote in lotes for t in lote]
    parar = threading.Event()
    vigilante = None
    if dir_clips and desde is not None:
        vigilante = threading.Thread(
            target=_vigilar_avance,
            args=(dir_lotes, dir_clips, ids, len(lotes), desde, avisar, parar),
            daemon=True)
        vigilante.start()

    # SE RECOGE EL QUE ACABA, NO EL SIGUIENTE DE LA FILA. Esperando en orden, la
    # barra no se movia hasta que terminara el lote 0 aunque los otros quince ya
    # hubieran acabado -- y esto se mira desde el movil mientras corre. Cada
    # espera va en su hilo porque `communicate()` ademas VACIA las tuberias: sin
    # eso, un hijo que escupiera un traceback largo se quedaria bloqueado
    # llenando su stderr.
    salida, fallos, hechos = {}, [], 0

    def recoger(par):
        ficha, proceso = par
        _, error = proceso.communicate()
        return ficha, proceso.returncode, error

    try:
        with ThreadPoolExecutor(max_workers=max(1, len(procesos))) as pool:
            for tarea in as_completed([pool.submit(recoger, p) for p in procesos]):
                ficha, codigo, error = tarea.result()
                resultado = medios.leer_json(ficha + ".hecho", {})
                if codigo != 0 or not resultado.get("planos"):
                    fallos.append((error or "").strip()[-600:]
                                  or f"el proceso del lote salio con {codigo}")
                    continue
                for plano in resultado["planos"]:
                    salida[plano["id"]] = plano
                    hechos += 1
    finally:
        parar.set()
        if vigilante:
            vigilante.join(timeout=2 * LATIDO_S)
    avisar(0.05 + 0.85 * (hechos / max(1, total_planos)),
           f"{hechos} de {total_planos} planos renderizados",
           (hechos, total_planos))
    if fallos:
        raise RuntimeError("fallo el render de un lote de planos: "
                           + " | ".join(fallos[:2]))
    return salida


#: Lo que este paso entiende como opcion DE ESTA INVOCACION (no es un param y
#: no mueve la firma): volver a montar el MP4 sin tocar un solo clip.
OPCIONES_EJECUCION = ("solo_montar",)


def ejecutar(proyecto, params, avisar=None, unidades=None, solo_montar=False):
    """Renderiza los clips que toquen y rehace el MP4 final.

    Con `solo_montar` NO se toca un solo clip: se vuelven a mezclar la banda
    sonora y la voz sobre los clips que ya hay y se muxea otra vez. Existe
    porque hay cosas que cambian el VIDEO sin cambiar ningun fotograma -- vetar
    un efecto de sonido, montar otra banda, mover el nivel de la musica -- y
    hasta ahora la unica forma de aplicarlas era volver a renderizar los
    cuarenta y nueve planos para cambiar la mezcla, que se hace al muxear.
    En un video de veinte minutos eso son 36 minutos de render para nada.
    """
    arranque_paso = time.time()
    p = _con_defectos(params)
    avisar = estadisticas.avisador(avisar)

    ruta_plan = (params or {}).get("plan") or medios.salida_de(
        proyecto, "assets", claves=("plan",), patrones=(r"plan\.json",))
    ruta_mov = (params or {}).get("movimiento") or medios.salida_de(
        proyecto, "callouts", claves=("movimiento",), patrones=(r"movimiento\.json",))
    if not ruta_plan or not ruta_mov:
        raise RuntimeError("faltan las salidas de assets o de callouts")
    plan = medios.leer_json(ruta_plan, {})
    base_callouts = os.path.dirname(ruta_mov)
    movimientos = {m["id"]: m for m in
                   (medios.leer_json(ruta_mov, {}) or {}).get("movimientos", [])
                   if m.get("id")}

    audio = p["audio"] or medios.salida_de(
        proyecto, "voz", claves=("wav", "audio", "narracion"),
        patrones=(r"narracion\.wav", r".*\.wav"))

    trabajo = medios.sembrar_trabajo(proyecto, "render")
    # DESPUES de sembrar, y eso es lo que lo hace robusto: todo lo que aparezca
    # en trabajo/ a partir de aqui lo ha escrito ESTE render. `sembrar_trabajo`
    # copia con copy2 y conserva la fecha original, asi que tomandolo antes
    # tambien saldria bien -- pero entonces el arreglo dependeria de un detalle
    # de shutil que nadie tiene por que respetar manana. Ver `_esperar`.
    arranque_render = time.time()
    dir_clips = os.path.join(trabajo, "clips")
    dir_ultimo = os.path.join(trabajo, "ultimo")
    dir_frames = os.path.join(trabajo, "frames")
    for ruta in (dir_clips, dir_ultimo, dir_frames):
        os.makedirs(ruta, exist_ok=True)

    escenas = plan.get("escenas") or []
    fps = int(p["fps"])
    # QUE transicion concreta lleva cada plano. El plan solo trae la RANURA
    # (corte / suave / acento), que es una decision del corte; cual la ocupa se
    # resuelve aqui, al renderizar, contra la paleta elegida en esta pantalla.
    cortes = transiciones.resolver(escenas, p,
                                   semilla=(plan.get("semilla") or 0))
    pedidas = set(unidades) if unidades is not None else None
    arrastrados = []
    if pedidas is not None:
        # EL UNICO ARRASTRE QUE SOBREVIVE, y no es «rehacer lo que depende»:
        # es «el fichero producido seria incorrecto». El clip que entra lleva
        # cocida la transicion sobre el ultimo fotograma del anterior, asi que
        # si cambia un plano, el siguiente queda con una transicion cocida sobre
        # un fotograma que ya no existe -- y eso se VE: es un fogonazo entre
        # los dos planos.
        #
        # Por eso se queda cuando la cascada de generacion se retiro del resto
        # del sistema (PENDIENTE 30). A cambio SE DICE: al terminar sale en los
        # avisos con los ids, para que nadie encuentre un clip rehecho que no
        # habia pedido y tenga que deducir por que.
        #
        # UN salto y no en cascada: el ultimo fotograma del siguiente no cambia
        # por rehacer su arranque, asi que el de mas alla no tiene por que
        # pagarse. Iterando sobre el propio set, S002 arrastraba S003, S003 a
        # S004 y una peticion de un plano recodificaba media cola de fundidos.
        originales = set(pedidas)
        for indice, escena in enumerate(escenas[1:], start=1):
            # solo arrastran las que MIRAN hacia atras: el corte no mira
            if (f"escena:{escenas[indice - 1]['id']}" in originales
                    and transiciones.cuece_el_anterior(cortes.get(escena["id"]))):
                if f"escena:{escena['id']}" not in originales:
                    arrastrados.append(escena["id"])
                pedidas.add(f"escena:{escena['id']}")

    # EL CUADRO LO DICE EL PLAN: el formato se decide al crear
    # el video y viaja en plan.json; el param del render es el respaldo de un
    # plan de antes, que no lo trae.
    ancho, alto = [int(v) for v in (plan.get("resolucion") or p["resolucion"])]
    # La pagina de las transiciones se escribe UNA vez por render: dentro
    # compila los shaders segun los va necesitando y se los queda, asi que
    # reabrirla por plano seria recompilarlos. Los colores de acento salen de la
    # paleta que dejo callouts (ver p7_callouts.ejecutar).
    paleta = (medios.leer_json(ruta_mov, {}) or {}).get("paleta") or {}
    pagina_trans = transiciones.pagina(
        os.path.join(trabajo, "transicion.html"), ancho, alto, paleta)
    resultados = {}
    clips = []
    tareas = []
    for indice, escena in enumerate(escenas):
        sid = escena["id"]
        uid = f"escena:{sid}"
        clip = os.path.join(dir_clips, f"{sid}.mp4")
        clips.append(clip)

        inicio = round(float(escena["t_in"]) * fps)
        final = round(float(escena["t_out"]) * fps)
        total = max(1, final - inicio)

        # SOLO MONTAR: ningun plano se renderiza, se reutilizan todos sus clips.
        # Si falta alguno se dice al concatenar, con su nombre.
        if solo_montar or (pedidas is not None and uid not in pedidas
                           and os.path.exists(clip)):
            resultados[uid] = {"clip": os.path.relpath(clip, trabajo),
                               "frames": total, "origen": "conservado"}
            continue

        mov = movimientos.get(sid)
        if not mov:
            raise RuntimeError(f"{sid}: el paso callouts no dejo movimiento")
        hyper = mov.get("hyperframe")
        hyper = (hyper if hyper and os.path.isabs(hyper)
                 else os.path.join(base_callouts, hyper or ""))
        if not os.path.exists(hyper):
            raise RuntimeError(f"{sid}: falta el hyperframe {hyper}")
        capa = os.path.join(base_callouts, mov.get("capa") or "")
        svg = ""
        if os.path.exists(capa):
            with open(capa, "r", encoding="utf-8") as fh:
                svg = fh.read()
        # LA CAPA QUIETA. Puede faltar --un movimiento.json de antes del 23-08 no
        # la tiene-- y entonces el plano sale sin subtitulo en vez de reventar:
        # es exactamente lo que ya pasa con la capa movil, y la alternativa seria
        # tumbar el render de un video entero por una version vieja del paso
        # anterior. Se vuelve a montar callouts y aparece.
        fija = ""
        ruta_fija = mov.get("capa_fija")
        if ruta_fija:
            ruta_fija = os.path.join(base_callouts, ruta_fija)
            if os.path.exists(ruta_fija):
                with open(ruta_fija, "r", encoding="utf-8") as fh:
                    fija = fh.read()

        tareas.append({
            "id": sid, "escena": {"id": sid, "t_in": escena["t_in"],
                                  "t_out": escena["t_out"]},
            "mov": {"ventana_ini": mov["ventana_ini"],
                    "ventana_fin": mov["ventana_fin"],
                    "hyperframe_px": mov.get("hyperframe_px")},
            "capa": svg, "capa_fija": fija,
            "hyper": hyper, "frames": total, "fps": fps,
            "resolucion": [ancho, alto], "calidad": p["calidad_video"],
            "carpeta": os.path.join(dir_frames, sid), "clip": clip,
            "ultimo": os.path.join(dir_ultimo, f"{sid}.png"),
            # el arranque de ESTA pasada: con el, el ultimo fotograma del plano
            # de antes deja de ser «un fichero que existe» y pasa a ser «un
            # fichero que ha escrito este render» (ver _esperar)
            "desde": arranque_render,
            "anterior": (os.path.join(dir_ultimo,
                                      f"{escenas[indice - 1]['id']}.png")
                         if indice else None),
            "previo": escenas[indice - 1]["id"] if indice else None,
            "corte": {k: v for k, v in (cortes.get(sid) or {}).items()},
            "pagina_trans": pagina_trans,
            "conservar_frames": bool(p["conservar_frames"])})

    # QUIEN TIENE QUE ESPERAR A QUIEN. La transicion de un plano se cuece sobre
    # el ULTIMO FOTOGRAMA del anterior, asi que si ese plano tambien se
    # renderiza en esta tanda su fichero todavia no existe: lo va a dejar otro
    # proceso y hay que esperarlo. Se decide contra la lista de tareas de
    # VERDAD y no contra las unidades pedidas, porque no son lo mismo: un plano
    # que no se pidio pero cuyo clip falta tambien se renderiza.
    #
    # Y si el anterior NO entra en esta tanda, manda lo que haya en disco: el
    # ultimo fotograma de la pasada anterior. Si tampoco esta, ese corte va sin
    # transicion, que es lo que ya hacia antes.
    en_tanda = {t["id"] for t in tareas}
    for tarea in tareas:
        tarea["esperar_anterior"] = bool(tarea["previo"] in en_tanda)
        if (tarea["anterior"] and not tarea["esperar_anterior"]
                and not os.path.exists(tarea["anterior"])):
            tarea["anterior"] = None

    if tareas:
        lotes = _repartir_lotes(tareas, _cuantos_lotes(p, len(tareas)))
        if len(lotes) <= 1:
            # UN SOLO PLANO (o el modo en fila): no hace falta sacar un proceso
            # para lanzar un navegador. Es el mismo cuerpo, corriendo aqui.
            avisar(0.05, f"{len(tareas)} plano(s), en fila")
            fichas = {f["id"]: f for f in correr_lote(lotes[0])}
        else:
            fichas = _correr_lotes_en_procesos(
                lotes, trabajo, avisar, len(tareas),
                dir_clips=dir_clips, desde=arranque_render)
        for sid, ficha in fichas.items():
            resultados[f"escena:{sid}"] = dict(
                ficha, clip=os.path.relpath(
                    os.path.join(dir_clips, f"{sid}.mp4"), trabajo))
        faltan = [t["id"] for t in tareas if t["id"] not in fichas]
        if faltan:
            raise RuntimeError(f"no se renderizaron {len(faltan)} plano(s): "
                               f"{', '.join(faltan[:6])}")

    if not p["conservar_frames"]:
        shutil.rmtree(dir_frames, ignore_errors=True)
        shutil.rmtree(os.path.join(trabajo, "lotes"), ignore_errors=True)

    # ------------------------------------------------------------- sonido
    # Va DESPUES de los clips y antes de montar, y no toca el video: la banda
    # sonora se mezcla al muxear, asi que cambiar la musica o los efectos
    # rehace el MP4 sin recodificar un solo clip.
    desfase = float(escenas[0]["t_in"]) if escenas else 0.0
    largo = (float(escenas[-1]["t_out"]) - desfase) if escenas else 0.0
    # LA BANDA CUBRE TAMBIEN LA COLA. La musica cierra con su propio fundido
    # (`sonido.construir_cama`), y si se construye solo para lo que dura el
    # habla, ese fundido cae ANTES del negro y la cola se queda muda de golpe.
    largo_con_cola = largo + (COLA_NEGRO_S if escenas else 0.0)
    pista_efectos, sonidos = None, 0
    if p.get("sonido", True):
        avisar(0.93, "montando la banda de efectos")
        lista_eventos = sonido.eventos(escenas, cortes, p,
                                       semilla=(plan.get("semilla") or 0))
        if lista_eventos:
            pista_efectos, sonidos = sonido.pista_de_efectos(
                lista_eventos, largo, os.path.join(trabajo, "efectos.wav"))
    pista_musica, faltan_temas, cama = None, [], False
    ficha_musica = (p.get("musica") or {}) if p.get("sonido", True) else {}
    if ficha_musica.get("tramos"):
        # LA CAMA: varios temas encadenados, uno por tramo del video. Se
        # construye AQUI, sin salir a la red, desde los ficheros que dejo en el
        # banco quien la decidio: el mismo plan da la misma cama siempre.
        avisar(0.94, f"encadenando {len(ficha_musica['tramos'])} temas")
        pista_musica, faltan_temas = sonido.construir_cama(
            ficha_musica, largo_con_cola, os.path.join(trabajo, "cama.wav"))
        cama = bool(pista_musica)
    elif ficha_musica.get("id"):
        candidata = sonido.banco("musica", sonido._nombre_de(ficha_musica))
        # si el tema no esta en el banco se sigue SIN el: un video sin musica
        # es un video, y tumbar un render de veinte minutos por un mp3 que
        # alguien borro del banco no arregla nada. Se dice en los avisos.
        pista_musica = candidata if os.path.exists(candidata) else None

    avisar(0.95, "montando el video")
    destino = os.path.join(trabajo, "video.mp4")
    try:
        ajuste_musica = float(p.get("musica_db") or 0.0)
    except (TypeError, ValueError):
        ajuste_musica = 0.0
    try:
        ajuste_efectos = float(p.get("efectos_db") or 0.0)
    except (TypeError, ValueError):
        ajuste_efectos = 0.0
    _concatenar(clips, destino, audio, desfase, trabajo, musica=pista_musica,
                efectos=pista_efectos, duracion=largo_con_cola,
                lufs=p.get("musica_lufs"), cama=cama, ajuste_db=ajuste_musica,
                fps=fps, calidad=p.get("calidad") or "media",
                efectos_db=ajuste_efectos)
    duracion = medios.duracion_media(destino)

    # los assets son unidades heredadas: no se renderizan, pero se sellan igual
    # o el paso nunca daria 'listo' aunque el video este hecho
    for usados in (plan.get("dependencias") or {}).values():
        for uid in usados:
            resultados.setdefault(uid, {"heredado": "assets"})

    # igual que en assets: solo se sellan las unidades rehechas en esta pasada
    if pedidas is None:
        rehechas = dict(resultados)
    else:
        rehechas = {uid: ficha for uid, ficha in resultados.items() if uid in pedidas}

    avisos = []
    if arrastrados:
        avisos.append(
            f"{len(arrastrados)} clip(s) se han rehecho sin pedirlos "
            f"({', '.join(arrastrados[:6])}"
            + (f" y {len(arrastrados) - 6} más" if len(arrastrados) > 6 else "")
            + "): llevan la transición cocida sobre el último fotograma del "
              "plano anterior, que ha cambiado. No rehacerlos dejaría un "
              "fogonazo en ese corte. No cuesta dinero: es recodificar.")
    if faltan_temas:
        avisos.append(f"faltan en el banco {len(faltan_temas)} tema(s) de la "
                      f"banda sonora ({', '.join(str(t) for t in faltan_temas[:3])}): "
                      f"esos tramos van sin música. Vuelve a montarla en «Sonido».")
    if ficha_musica.get("id") and not ficha_musica.get("tramos") and not pista_musica:
        avisos.append(f"el tema «{ficha_musica.get('titulo') or ficha_musica['id']}» "
                      f"no está en el banco: el vídeo va sin música. Vuelve a "
                      f"elegirlo en «Música y efectos».")
    salidas = {"mp4": "video.mp4",
               "duracion": round(duracion, 3),
               "clips": {e["id"]: f"clips/{e['id']}.mp4" for e in escenas},
               "fps": fps, "resolucion": [ancho, alto],
               "audio": os.path.basename(audio) if audio else None,
               "musica": (sonido.describir(p) if cama else
                          ficha_musica.get("titulo") if pista_musica else None),
               "efectos": sonidos,
               "avisos": avisos,
               "solo_montado": bool(solo_montar),
               "resumen": (("banda sonora remontada sobre " if solo_montar else "")
                           + f"{len(escenas)} clips, {duracion:.1f}s a {fps} fps "
                           f"{ancho}x{alto}"
                           + (f", {sonidos} efectos" if sonidos else "")
                           + (" y música" if pista_musica else ""))}
    avisar(1.0, salidas["resumen"])
    # Lo que se mide es lo REHECHO: un «solo montar» reutiliza los clips y no
    # dice lo que cuesta renderizarlos (ver `p6_assets._anotar_tiempo`).
    try:
        if rehechas:
            estadisticas.anotar("render",
                                max(0.01, time.time() - arranque_paso),
                                tamano=len(rehechas),
                                proyecto=getattr(proyecto, "id", None),
                                detalle={"solo_montar": bool(solo_montar),
                                         "duracion_s": round(duracion, 1),
                                         "fps": fps,
                                         "resolucion": [ancho, alto]})
    except Exception:                                       # noqa: BLE001
        pass
    return {"salidas": salidas, "unidades": rehechas, "todas": resultados,
            "conservadas": sorted(uid for uid in resultados if uid not in rehechas),
            "avisos": avisos}


# ------------------------------------------------------- el proceso del lote
#
# Cada lote de planos corre como `python p8_render.py --lote <ficha.json>`. Se
# lanza asi y no con multiprocessing por una razon concreta de Windows: el
# `spawn` reimporta el `__main__` del proceso padre en cada hijo, y aqui el
# padre es el SERVIDOR. Un fichero de tareas y un proceso limpio no tienen esa
# sorpresa, y ademas un lote que revienta deja su error en stderr en vez de
# tumbar el render entero sin decir donde.

def _main(argv=None):
    import argparse                                        # noqa: PLC0415
    aparcador = argparse.ArgumentParser(description="Renderiza un lote de planos")
    aparcador.add_argument("--lote", required=True,
                           help="ficha JSON con las tareas del lote")
    args = aparcador.parse_args(argv)
    ficha = medios.leer_json(args.lote, {}) or {}
    planos = correr_lote(ficha.get("tareas") or [],
                         senal_vivo=args.lote + ".vivo")
    medios.escribir_json(args.lote + ".hecho", {"planos": planos})
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
