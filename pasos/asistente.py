"""El asistente: un chat que contesta con el CLI de Claude y con el Estudio delante.

QUE ES
------
La burbuja de abajo a la derecha. Quien la abre pregunta en castellano --«me ha
dado este error», «por que assets esta en naranja», «donde consigo la clave de
Cartesia», «la tanda lleva parada diez minutos»-- y contesta el CLI de Claude
con la MISMA cuenta con la que el Estudio escribe los guiones. No hay ninguna
clave nueva que pedir: si el CLI tiene sesion, el asistente responde; si no, lo
dice y manda a entrar primero.

CON QUE CONTEXTO CONTESTA, y por que asi
----------------------------------------
Tres capas, de mas fija a mas viva:

1. **La documentacion del producto**, entera y en el primer mensaje: CLAUDE.md,
   README.md, docs/RETOMAR.md y docs/API.md. Son unas 45.000 letras y van una
   sola vez por charla: los turnos siguientes REANUDAN la sesion del CLI
   (`--resume`), que ya las tiene leidas.
2. **El codigo**, a demanda. El CLI corre con la carpeta del Estudio de trabajo
   y con Read, Grep y Glob permitidos, y nada mas: ni Bash, ni escribir, ni
   salir a internet. Asi «me ha dado este error» se resuelve buscando el texto
   exacto del error en el codigo, que es donde esta escrito por que salta.
3. **Una foto del estado AHORA**, delante de CADA pregunta: que claves hay, que
   proyecto esta abierto, en que estado esta cada paso, que trabajos corren o
   han fallado, los ultimos eventos de la bitacora y los errores que la pantalla
   tiene a la vista. La hace `app.py` (es quien tiene los contextos) y se manda
   siempre, tambien al reanudar: lo que estaba pasando hace tres preguntas ya
   no esta pasando.

LO QUE NO PUEDE LEER, y esto es lo importante
--------------------------------------------
`secretos/` esta DENTRO de la carpeta del Estudio por defecto, o sea al alcance
de un Read. Se veta por regla de permiso del CLI (`Read(./secretos/**)` y la
forma absoluta), y ademas se le dice en el prompt de sistema. Las dos cosas, a
proposito: la regla es la que manda, y el prompt es para que no lo intente y
conteste que las claves no se ensenan. Un `.env` y cualquier `claves.json`
quedan vetados tambien por nombre, esten donde esten.

Lo que SI puede leer fuera del repo es la carpeta de proyectos (`--add-dir`):
un `estado.json` o una bitacora son justo lo que hace falta para explicar por
que un plano esta obsoleto.

UNA CHARLA ES UNA SESION DEL CLI
--------------------------------
El sobre JSON del CLI trae `session_id`; el turno siguiente se lanza con
`--resume <id>` y el CLI recuerda la conversacion entera sin volver a mandar la
documentacion. Si reanudar falla --el servicio cambio de cuenta del CLI a
mitad, la sesion se borro, lo que sea-- se vuelve a empezar con la
documentacion Y con los turnos anteriores pegados en el mensaje, y la persona
no nota nada salvo que ese turno tarda un poco mas.

Un turno corre en un HILO y la pantalla lo sigue preguntando: la respuesta
puede tardar un minuto, y detras de un proxy una peticion de un minuto se corta
a los sesenta segundos sin decir por que. Cada charla admite UN turno a la vez.

MODELO Y ESFUERZO
-----------------
Sonnet con esfuerzo medio, y NO el defecto del canal (opus/xhigh): esto es un
chat y lo que importa es contestar en segundos, no en minutos. Se puede cambiar
con ESTUDIO_ASISTENTE_MODELO y ESTUDIO_ASISTENTE_ESFUERZO sin tocar nada.

Con ESTUDIO_SIMULAR=1 no se llama al CLI: contesta un doble que repite lo que
recibio, que es lo que dejan comprobar las pruebas de la API.
"""
import json
import os
import sys
import tempfile
import threading
import time
import uuid

try:
    from . import cli_claude, mcp_estudio
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import cli_claude
    import mcp_estudio

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Con que contesta. Ver la cabecera: un chat pide segundos, no minutos.
MODELO = os.environ.get("ESTUDIO_ASISTENTE_MODELO") or "sonnet"
ESFUERZO = os.environ.get("ESTUDIO_ASISTENTE_ESFUERZO") or "medium"

#: Techo de UN turno. Con herramientas de lectura un turno puede encadenar
#: varias llamadas; siete minutos es mucho para un chat, pero menos deja fuera
#: una pregunta que obligue a leer medio codigo.
TIEMPO_MAX_S = 420

#: Lo que se le da a leer en el primer turno, en este orden. Lo que no exista
#: se salta sin avisar: un despliegue puede no llevar la carpeta docs/.
DOCUMENTOS = ("CLAUDE.md", "README.md", "docs/RETOMAR.md", "docs/API.md")

#: Lo que puede hacer ademas de contestar: LEER el codigo, y las herramientas
#: del Estudio (pasos/mcp_estudio.py): probar las claves, ver el estado, los
#: trabajos, la bitacora, cancelar un trabajo. Van pre-autorizadas: en
#: headless una pregunta de permiso es una negativa, y la persona espera que
#: el asistente PRUEBE las cosas, no que diga que no puede.
HERRAMIENTAS_PERMITIDAS = ("Read", "Grep", "Glob") + mcp_estudio.nombres_permitidos()


def api_del_estudio():
    """Donde escucha la API del Estudio, para las herramientas. Lo pone app.py
    al arrancar; sin el (una suite, el modulo suelto) no se cargan."""
    return (os.environ.get("ESTUDIO_API") or "").strip()

#: Todo lo demas, por nombre, ademas de lo que veta `cli_claude` de fabrica.
#: `Bash` es la herramienta con la que se sale de una carpeta; `Write` y `Edit`
#: convertirian una pregunta en un cambio en el codigo; `WebFetch` y
#: `WebSearch` sacarian el estado del Estudio a internet.
HERRAMIENTAS_VETADAS = ("Bash", "Write", "Edit", "MultiEdit", "NotebookEdit",
                        "WebFetch", "WebSearch", "Task", "Agent", "TodoWrite",
                        "KillShell", "BashOutput")

#: Carpetas y ficheros que un Read no puede abrir, relativos a la raiz.
CARPETAS_VETADAS = ("secretos",)
FICHEROS_VETADOS = ("**/.env", "**/claves.json", "**/.credentials.json")

#: Cuantas charlas se recuerdan y cuanto vive una sin que nadie le hable. Viven
#: en memoria a proposito: recargar la pagina tiene que reencontrar la charla,
#: reiniciar el servicio no.
MAX_CHARLAS = 30
CADUCIDAD_CHARLA_S = 24 * 3600

#: Al perder la sesion del CLI se vuelve a empezar con los ultimos turnos
#: pegados en el mensaje. Todos no: una charla larga volveria a costar lo que
#: la documentacion entera.
TURNOS_AL_REEMPEZAR = 12

#: Tope de una pregunta. No es un limite del CLI: es que un pegado de 200 KB de
#: log no es una pregunta, y el turno tardaria minutos en leerlo.
MAX_PREGUNTA = 20000

_LOCK = threading.RLock()
_CHARLAS = {}


class ErrorAsistente(ValueError):
    """Algo que la pantalla puede ENSENAR tal cual."""


class Ocupada(ErrorAsistente):
    """La charla ya esta contestando: es un 409, no un 400."""


def simulado():
    """True si no hay que llamar al CLI (ESTUDIO_SIMULAR=1)."""
    return str(os.environ.get("ESTUDIO_SIMULAR", "")).strip().lower() in (
        "1", "true", "si")


# ------------------------------------------------------------------ el prompt

def sistema():
    """El prompt de sistema, en UNA linea y sin acentos.

    Una linea porque en Windows el CLI se invoca a traves de claude.cmd y un
    salto de linea dentro de un argumento parte la orden (`construir_orden` lo
    comprueba). Sin acentos porque va como ARGUMENTO y no por stdin: la consola
    lo recodifica con su pagina de codigos y una enye llega como dos letras
    raras. Lo que va por stdin (el mensaje) si lleva acentos.
    """
    return (
        "Eres el asistente de AS Video Studio, un producto que convierte texto en "
        "un video narrado en ocho pasos (ingesta, brief, guion, voz, revision de "
        "audio, assets, callouts, render). Hablas con la persona que lo esta usando "
        "desde la propia pantalla del Estudio, y tu trabajo es resolver dudas y "
        "problemas: que significa un estado, por que un paso esta obsoleto o "
        "parado, que dice un error y que hacer con el, como conseguir o cambiar "
        "una clave, cuanto va a costar algo. Contestas en castellano, en pocas "
        "frases, con pasos concretos y numerados cuando hay que hacer algo, y "
        "diciendo donde esta cada cosa en la pantalla (Configuracion es el "
        "engranaje de arriba a la derecha; las claves y las cuentas de Claude se "
        "cambian ahi). Tienes el codigo del Estudio en la carpeta de trabajo y "
        "puedes leerlo con Read, Grep y Glob cuando la foto del estado y la "
        "documentacion no basten, por ejemplo para buscar el texto exacto de un "
        "error y ver por que salta; no tienes Bash, no puedes escribir nada y no "
        "sales a internet. Tienes ademas las herramientas del Estudio (servidor "
        "estudio): probar_claves prueba de verdad cada clave contra su servicio, "
        "probar_claude prueba las cuentas de Claude, estado_estudio da la foto "
        "actual, trabajos lista las generaciones con su error, ficha_paso y "
        "bitacora miran un paso o el historial de un proyecto, cancelar_trabajo "
        "para uno colgado y salud_servicio dice si el servicio va. Usalas sin "
        "pedir permiso cuando la pregunta lo pida: si te preguntan si las claves "
        "estan bien, PRUEBALAS con probar_claves y cuenta el resultado; si algo "
        "esta parado, mira trabajos y bitacora antes de contestar. Nunca leas ni "
        "cites la carpeta secretos, ningun .env ni "
        "ninguna clave: si te lo piden, di que las claves no se ensenan y que se "
        "cambian en Configuracion. Antes de cada pregunta recibes una foto del "
        "estado actual del Estudio: fiate de ella para lo que esta pasando ahora "
        "mismo, y de la documentacion para como funciona. Si no sabes algo, dilo y "
        "propone donde mirar en vez de inventarlo. No repitas la pregunta ni "
        "saludes: contesta.")


def vetos_de_lectura(raiz=None):
    """Las reglas de permiso que dejan las claves fuera del alcance de Read.

    Van en las dos formas --relativa a la carpeta de trabajo y absoluta--
    porque el CLI resuelve las relativas contra el cwd, y el cwd es la raiz
    del Estudio; la absoluta cubre el caso de que alguien mueva la carpeta de
    trabajo y se olvide de esto.
    """
    raiz = os.path.abspath(raiz or RAIZ_ESTUDIO)
    reglas = []
    for carpeta in CARPETAS_VETADAS:
        reglas.append(f"Read(./{carpeta}/**)")
        absoluta = os.path.join(raiz, carpeta).replace("\\", "/")
        reglas.append(f"Read(//{absoluta.lstrip('/')}/**)")
    for fichero in FICHEROS_VETADOS:
        reglas.append(f"Read({fichero})")
    return reglas


def documentos(raiz=None):
    """[(nombre, texto)] de la documentacion que exista."""
    raiz = raiz or RAIZ_ESTUDIO
    salida = []
    for relativo in DOCUMENTOS:
        ruta = os.path.join(raiz, *relativo.split("/"))
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                salida.append((relativo, fh.read()))
        except OSError:
            continue
    return salida


def _bloque(titulo, cuerpo):
    return f"=== {titulo} ===\n{str(cuerpo or '').strip()}\n"


def mensaje_de_arranque(foto, pregunta, raiz=None, historia=()):
    """El primer mensaje de una charla: documentacion + foto + pregunta.

    `historia` son los turnos anteriores cuando se vuelve a empezar porque se
    perdio la sesion del CLI. Vacia en una charla nueva.
    """
    partes = [
        "Esto es todo lo que hay que saber del Estudio, tal como esta escrito en "
        "su repositorio. Leelo entero antes de contestar; despues, en cada turno, "
        "recibiras una foto del estado y una pregunta.\n"]
    for nombre, texto in documentos(raiz):
        partes.append(_bloque(f"DOCUMENTO {nombre}", texto))
    if historia:
        lineas = []
        for turno in list(historia)[-TURNOS_AL_REEMPEZAR:]:
            quien = "PERSONA" if turno.get("quien") == "tu" else "ASISTENTE"
            lineas.append(f"[{quien}] {str(turno.get('texto') or '').strip()}")
        partes.append(_bloque(
            "CONVERSACION ANTERIOR (la sesion del CLI se perdio; sigue desde aqui)",
            "\n\n".join(lineas)))
    partes.append(mensaje_de_turno(foto, pregunta))
    return "\n".join(partes)


def mensaje_de_turno(foto, pregunta):
    """Lo que va en cada turno que reanuda: la foto de ahora y la pregunta."""
    return (_bloque("ESTADO DEL ESTUDIO AHORA MISMO (lo hace el servidor, no "
                    "la persona)", foto)
            + "\n" + _bloque("PREGUNTA", pregunta))


# ------------------------------------------------------------------ ejecutar

class Avance:
    """Lo minimo que `cli_claude.ejecutar` necesita para poder cancelar."""

    def __init__(self):
        self.cancelado = False
        self.al_cancelar = None


def fichero_mcp(proyecto=""):
    """Escribe la configuracion MCP del servidor `estudio` y devuelve su ruta.

    Va a un fichero y no como JSON en la linea de ordenes: en Windows el CLI se
    invoca a traves de claude.cmd y las comillas de un JSON no sobreviven. El
    fichero se reescribe en cada turno porque lleva el proyecto abierto.
    Devuelve "" si no hay API a la que hablar (una suite, el modulo suelto).
    """
    api = api_del_estudio()
    if not api:
        return ""
    config = {"mcpServers": {"estudio": {
        "command": sys.executable,
        "args": [os.path.abspath(mcp_estudio.__file__)],
        "env": {"ESTUDIO_API": api, "ESTUDIO_PROYECTO_ABIERTO": str(proyecto or ""),
                "ESTUDIO_SECRETOS": os.environ.get("ESTUDIO_SECRETOS", "")},
    }}}
    ruta = os.path.join(tempfile.gettempdir(), f"estudio_mcp_{os.getpid()}.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(config, fh)
    return ruta


def ejecutar_cli(mensaje, extra=(), avance=None, raiz=None, carpetas_extra=(),
                 proyecto=""):
    """UNA llamada al CLI con las herramientas y los vetos del asistente.

    -> (texto, sobre). Lanza lo mismo que `cli_claude.ejecutar`.
    """
    raiz = os.path.abspath(raiz or RAIZ_ESTUDIO)
    orden_extra = list(extra or [])
    mcp = fichero_mcp(proyecto)
    if mcp:
        orden_extra += ["--mcp-config", mcp]
    for carpeta in carpetas_extra or ():
        if carpeta and os.path.isdir(carpeta):
            orden_extra += ["--add-dir", os.path.abspath(carpeta)]
    vetadas = tuple(HERRAMIENTAS_VETADAS) + tuple(vetos_de_lectura(raiz))
    return cli_claude.ejecutar(
        mensaje, modelo=MODELO, esfuerzo=ESFUERZO, cwd=raiz,
        tiempo_max_s=TIEMPO_MAX_S, sistema=sistema(),
        herramientas_vetadas=vetadas, avance=avance, extra=orden_extra,
        para="contestar en el asistente",
        herramientas_permitidas=HERRAMIENTAS_PERMITIDAS)


def ejecutar_simulado(mensaje, extra=(), avance=None, raiz=None,
                      carpetas_extra=(), proyecto=""):
    """El doble de las pruebas: no llama a nadie y cuenta lo que recibio."""
    extra = list(extra or [])
    reanuda = "--resume" in extra
    pregunta = mensaje.rsplit("=== PREGUNTA ===", 1)[-1].strip()
    texto = (f"(simulado) He recibido {len(mensaje)} caracteres"
             f"{' reanudando la sesion' if reanuda else ' de arranque'}. "
             f"Me preguntas: {pregunta}")
    sobre = {"session_id": extra[extra.index("--resume") + 1] if reanuda
             else f"sim-{uuid.uuid4().hex[:8]}",
             "usage": {"input_tokens": len(mensaje) // 4, "output_tokens": 40},
             "_ajuste": {"modelo": "simulado", "esfuerzo": "-", "segundos": 0}}
    return texto, sobre


def ejecutor():
    return ejecutar_simulado if simulado() else ejecutar_cli


# ------------------------------------------------------------------ la charla

class Charla:
    """Una conversacion: sus turnos y la sesion del CLI que la recuerda.

    Estados de un turno del asistente (los pinta la pantalla):

        pensando   el CLI esta en ello
        listo      contesto; `texto` es la respuesta
        error      no pudo; `texto` dice por que
        cancelado  se le pidio parar
    """

    def __init__(self, cid=None):
        self.id = cid or uuid.uuid4().hex[:12]
        self.session_id = ""
        self.turnos = []
        self.creada = time.time()
        self.tocada = self.creada
        self.pid = ""
        self._lock = threading.RLock()
        self._hilo = None
        self._avance = None

    # -- lo que ve la pantalla
    def ver(self):
        with self._lock:
            return {
                "id": self.id,
                "proyecto": self.pid,
                "turnos": [dict(t) for t in self.turnos],
                "ocupada": self.ocupada(),
                "reanuda": bool(self.session_id),
                "modelo": MODELO,
                "esfuerzo": ESFUERZO,
            }

    def ocupada(self):
        return bool(self.turnos) and self.turnos[-1].get("estado") == "pensando"

    def caducada(self):
        return time.time() - self.tocada > CADUCIDAD_CHARLA_S

    def _anadir(self, quien, texto, estado="listo", **extra):
        turno = {"n": len(self.turnos) + 1, "quien": quien, "texto": texto,
                 "estado": estado, "fecha": time.strftime("%Y-%m-%d %H:%M:%S")}
        turno.update(extra)
        self.turnos.append(turno)
        return turno

    def preguntar(self, pregunta, foto, raiz=None, carpetas_extra=(),
                  ejecutar=None, pid=""):
        """Arranca un turno. -> la ficha de la charla, con el turno 'pensando'.

        No espera: el turno corre en un hilo y la pantalla vuelve a preguntar.
        """
        pregunta = str(pregunta or "").strip()
        if not pregunta:
            raise ErrorAsistente("escribe algo que preguntar")
        if len(pregunta) > MAX_PREGUNTA:
            raise ErrorAsistente(
                f"la pregunta pasa de {MAX_PREGUNTA} caracteres; si es un log, "
                f"pega solo el trozo donde esta el error")
        with self._lock:
            if self.ocupada():
                raise Ocupada("todavia esta contestando la anterior; espera "
                              "o cancelala")
            self.tocada = time.time()
            self.pid = str(pid or "")
            self._anadir("tu", pregunta)
            respuesta = self._anadir("asistente", "", estado="pensando",
                                     segundos=0)
            avance = Avance()
            self._avance = avance
            arranque = time.time()
        ejecutar = ejecutar or ejecutor()
        hilo = threading.Thread(
            target=self._correr,
            args=(pregunta, foto, raiz, tuple(carpetas_extra or ()), ejecutar,
                  respuesta, avance, arranque),
            daemon=True)
        self._hilo = hilo
        hilo.start()
        return self.ver()

    def _correr(self, pregunta, foto, raiz, carpetas_extra, ejecutar, respuesta,
                avance, arranque):
        try:
            texto, sobre = self._contestar(pregunta, foto, raiz, carpetas_extra,
                                           ejecutar, avance)
            with self._lock:
                self.session_id = str(sobre.get("session_id") or self.session_id)
                uso = sobre.get("usage") if isinstance(sobre.get("usage"), dict) else {}
                respuesta.update({
                    "texto": texto, "estado": "listo",
                    "segundos": round(time.time() - arranque, 1),
                    "tokens": {"entrada": int(uso.get("input_tokens") or 0),
                               "salida": int(uso.get("output_tokens") or 0)},
                    "cuenta": ((sobre.get("_ajuste") or {}).get("cuenta") or ""),
                })
        except Exception as fallo:  # noqa: BLE001 - el motivo va a la pantalla
            with self._lock:
                cancelado = avance.cancelado
                respuesta.update({
                    "estado": "cancelado" if cancelado else "error",
                    "texto": ("cancelado" if cancelado
                              else f"{type(fallo).__name__}: {fallo}"),
                    "segundos": round(time.time() - arranque, 1),
                })
        finally:
            with self._lock:
                self.tocada = time.time()
                self._avance = None

    def _contestar(self, pregunta, foto, raiz, carpetas_extra, ejecutar, avance):
        """Reanuda si hay sesion; si reanudar falla, vuelve a empezar."""
        with self._lock:
            sesion = self.session_id
            historia = [dict(t) for t in self.turnos[:-2]]
        if sesion:
            try:
                return ejecutar(mensaje_de_turno(foto, pregunta),
                                extra=["--resume", sesion], avance=avance,
                                raiz=raiz, carpetas_extra=carpetas_extra,
                                proyecto=self.pid)
            except (cli_claude.TiempoAgotado, cli_claude.LimiteAgotado):
                # ni un plazo vencido ni un cupo agotado se arreglan volviendo
                # a empezar: volverian a pasar, y con la documentacion delante
                raise
            except RuntimeError as fallo:
                if avance.cancelado:
                    raise
                print(f"[asistente] no se pudo reanudar la sesion "
                      f"{sesion[:8]} ({str(fallo)[:120]}); se vuelve a "
                      f"empezar con la conversacion pegada", flush=True)
                with self._lock:
                    self.session_id = ""
        return ejecutar(mensaje_de_arranque(foto, pregunta, raiz, historia),
                        avance=avance, raiz=raiz, carpetas_extra=carpetas_extra,
                        proyecto=self.pid)

    def cancelar(self):
        """Para el turno en marcha. -> bool (habia uno)"""
        with self._lock:
            avance = self._avance
            if avance is None or not self.ocupada():
                return False
            avance.cancelado = True
            matar = avance.al_cancelar
        if callable(matar):
            try:
                matar()
            except Exception:  # noqa: BLE001 - es limpieza
                pass
        return True


# ------------------------------------------------------------------ registro

def _barrer():
    """Se lleva las charlas caducadas y, si sobran, las mas viejas."""
    for cid, charla in list(_CHARLAS.items()):
        if charla.caducada() and not charla.ocupada():
            _CHARLAS.pop(cid, None)
    if len(_CHARLAS) > MAX_CHARLAS:
        libres = sorted((c for c in _CHARLAS.values() if not c.ocupada()),
                        key=lambda c: c.tocada)
        for charla in libres[:len(_CHARLAS) - MAX_CHARLAS]:
            _CHARLAS.pop(charla.id, None)


def nueva():
    with _LOCK:
        _barrer()
        charla = Charla()
        _CHARLAS[charla.id] = charla
        return charla


def obtener(cid):
    """La charla con ese id, o None."""
    with _LOCK:
        _barrer()
        return _CHARLAS.get(str(cid or ""))


def olvidar(cid):
    """Tira una charla, cancelando lo que tuviera en marcha. -> bool"""
    with _LOCK:
        charla = _CHARLAS.pop(str(cid or ""), None)
    if charla is None:
        return False
    charla.cancelar()
    return True


def olvidar_todas():
    """Para las pruebas y para cerrar el servicio."""
    with _LOCK:
        charlas = list(_CHARLAS.values())
        _CHARLAS.clear()
    for charla in charlas:
        charla.cancelar()


def describir():
    return (f"asistente con {MODELO}/{ESFUERZO}, lectura del codigo y de los "
            f"proyectos, sin acceso a {', '.join(CARPETAS_VETADAS)}")
