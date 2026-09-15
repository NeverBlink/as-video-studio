"""Entrar con una cuenta del CLI de Claude desde la pantalla, sin pegar rutas.

POR QUE EXISTE
--------------
Hasta el 24-08-2026 una segunda cuenta del CLI se configuraba pegando en un
campo la ruta de una carpeta `CLAUDE_CONFIG_DIR`, y el texto de ayuda pedia:
«crea una carpeta, corre una vez `claude` con CLAUDE_CONFIG_DIR apuntando ahi,
entra con la otra cuenta, y pega la ruta debajo». Eso es un manual, no un boton.
Y el dia que hace falta -- el cupo se ha agotado a mitad de una tanda -- es el
peor momento para abrir una consola y acordarse de la receta.

Aqui el login se hace ENTERO desde la pantalla, con el mismo flujo que cualquier
inicio de sesion moderno: sale un enlace, se entra en el navegador, se pega el
codigo que devuelve, y la cuenta queda logueada para siempre.

COMO SE COMPORTA EL CLI, MEDIDO
-------------------------------
`claude auth login --claudeai` con las tuberias conectadas (sin terminal) hace
esto, y todo esto esta comprobado contra el CLI 2.1.241 de esta maquina:

    Opening browser to sign in…
    If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?…
    Paste code here if prompted >         <- y AQUI SE QUEDA, leyendo stdin

    ~0,6 s desde el arranque hasta que el enlace esta escrito.

Se le escribe el codigo con un salto de linea y termina: **codigo 0 si entro,
codigo 1 escribiendo `Login failed: …` si el codigo no valia**.

TRES COSAS QUE HUBO QUE RESOLVER, Y NINGUNA ES OBVIA
---------------------------------------------------
1. **ABRE UN NAVEGADOR.** Medido: sale un `msedge.exe` nuevo. Aqui se trabaja por
   escritorio remoto y nada puede abrir ventanas ni robar el foco --de ahi
   `medios.SIN_VENTANA`--, y ademas el navegador se abriria en la maquina y no en
   el movil desde el que se esta mirando. `BROWSER=none` lo apaga: probado con y
   sin, contando procesos de navegador antes y despues. El enlace se ensena en la
   pantalla, que ademas es lo unico que funciona por Tailscale desde el sofa.

2. **LA VERDAD NO SE LEE DE LO QUE IMPRIME, SE PREGUNTA.** Se podria buscar un
   «Login successful» en la salida, pero entonces cada vez que el CLI cambie una
   palabra el Estudio se cree que fallo un login que fue bien. Al terminar el
   proceso se llama a `claude auth status --json` en esa carpeta, que devuelve
   `{loggedIn, email, subscriptionType}`. Eso no cambia de forma, y ademas es lo
   mismo que se ensena luego en la ficha de la cuenta.

3. **LA CARPETA POR DEFECTO NO SE TOCA.** `~/.claude` es la sesion con la que el
   usuario tiene su propia consola abierta. Un `auth logout` ahi le echa de su
   terminal sin avisar. Por eso toda cuenta que se loguea desde aqui vive en su
   PROPIA carpeta (`CARPETA_CUENTAS/<id>`), creada por el Estudio, y la entrada
   heredada «la sesion por defecto» se muda a una carpeta propia en cuanto se
   entra con ella desde la pantalla.

LO QUE NO SE GUARDA EN NINGUN SITIO
-----------------------------------
Ni el enlace ni el codigo. El enlace lleva dentro el reto PKCE de ESE intento y
el codigo vale una vez: los dos viven solo en memoria, mientras dura el intento,
y se van con el. Lo unico que queda en disco es lo que escribe el propio CLI en
su carpeta (`.credentials.json`), que es donde tiene que estar.


"""
import json
import os
import re
import subprocess
import threading
import time

try:
    from . import cli_claude
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import cli_claude

#: Donde vive la carpeta de configuracion de cada cuenta que gestiona el Estudio.
#: Junto a las claves y FUERA del repo, por lo mismo: dentro hay un
#: `.credentials.json` con un login de verdad.
CARPETA_CUENTAS = os.path.join(
    os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "secretos"), "cli")

#: Cuanto se espera a que el CLI escriba el enlace. Medido: 0,6 s. El techo es
#: alto porque el primer arranque del CLI en una carpeta nueva se instala cosas.
ESPERA_ENLACE_S = 60

#: Cuanto se espera al veredicto despues de pegar el codigo.
ESPERA_CODIGO_S = 120

#: Cuanto se le da a un codigo mal copiado para demostrar que el CLI sigue vivo.
#: Un codigo malo se contesta en decimas; esto es para no confundir «me lo esta
#: volviendo a pedir» con «esta a punto de terminar».
ASENTAR_S = 1.5

#: Cuanto vive un intento sin terminar antes de que se mate solo. Un codigo de
#: OAuth caduca antes de esto, asi que pasado el plazo el intento ya no servia:
#: lo unico que hace seguir vivo es dejar un proceso colgado por cada vez que
#: alguien abrio la pantalla y se fue.
CADUCIDAD_INTENTO_S = 20 * 60

#: De donde se saca el enlace de la salida del CLI. Se busca la URL a pelo y no
#: la frase que la precede: la frase es copy y cambia, la URL es la URL.
_ENLACE = re.compile(r"https://\S*claude\.com/\S*oauth\S*", re.I)

#: La linea con la que el CLI explica un fallo.
_FALLO = re.compile(r"^\s*(Login failed:.*|Error:.*)$", re.M)

#: Lo que el CLI escribe DELANTE del hueco donde espera el codigo. Sirve para
#: quedarse solo con lo que dijo despues de que se le pasara uno.
_PIDE = "Paste code here if prompted"

_LOCK = threading.RLock()
#: id de cuenta -> Intento. Vive en memoria a proposito: recargar la pagina
#: tiene que encontrarlo, cerrar el servicio tiene que perderlo.
_INTENTOS = {}


class ErrorLogin(RuntimeError):
    """Algo que la pantalla puede ENSENAR tal cual."""


def _ultima_linea(texto):
    """Lo ultimo que dijo el CLI, sin el hueco donde espera el codigo.

    La salida viene de una consola que no lo es, asi que la frase util queda
    pegada detras del «Paste code here if prompted > » de la misma linea.
    """
    for linea in reversed(str(texto or "").splitlines()):
        limpia = linea.split(_PIDE, 1)[-1].lstrip("> ").strip()
        if limpia:
            return limpia
    return ""


# ------------------------------------------------------------------ carpetas

def carpeta_de(cuenta_id):
    """Donde va la carpeta de configuracion de una cuenta gestionada aqui."""
    limpio = re.sub(r"[^a-zA-Z0-9_-]", "", str(cuenta_id or "")) or "cta"
    return os.path.join(CARPETA_CUENTAS, limpio)


def asegurar_carpeta(cuenta_id):
    """La crea si no esta. -> ruta"""
    ruta = carpeta_de(cuenta_id)
    os.makedirs(ruta, exist_ok=True)
    return ruta


# ------------------------------------------------------------------ situacion

def situacion(carpeta=""):
    """Quien esta logueado en esa carpeta, preguntandoselo al CLI.

    -> {"conectada": bool, "correo": str, "plan": str, "metodo": str,
        "error": str}

    `carpeta` vacia = la sesion por defecto del CLI (`~/.claude`).

    Se pregunta y no se deduce del disco: mirar si hay un `.credentials.json`
    diria «si» de un login caducado, y un login caducado es exactamente el caso
    en el que hace falta enterarse.
    """
    orden = [_ejecutable(), "auth", "status", "--json"]
    entorno = cli_claude.entorno({"config_dir": carpeta} if carpeta else None)
    try:
        proceso = subprocess.run(orden, capture_output=True, timeout=60,
                                 env=entorno, **cli_claude.SIN_VENTANA)
    except (OSError, subprocess.TimeoutExpired) as fallo:
        return {"conectada": False, "correo": "", "plan": "", "metodo": "",
                "error": f"no se ha podido preguntar al CLI: {fallo}"}
    crudo = (proceso.stdout or b"").decode("utf-8", errors="replace")
    try:
        ficha = json.loads(crudo)
    except ValueError:
        # `auth status` sale con codigo 1 cuando no hay sesion, y eso NO es un
        # error del Estudio: es la respuesta.
        return {"conectada": False, "correo": "", "plan": "", "metodo": "",
                "error": "" if proceso.returncode else "el CLI no devolvio JSON"}
    if not isinstance(ficha, dict):
        return {"conectada": False, "correo": "", "plan": "", "metodo": "",
                "error": "respuesta inesperada del CLI"}
    return {
        "conectada": bool(ficha.get("loggedIn")),
        "correo": str(ficha.get("email") or ""),
        "plan": str(ficha.get("subscriptionType") or ""),
        "metodo": str(ficha.get("authMethod") or ""),
        "error": "",
    }


def salir(carpeta):
    """Cierra la sesion de esa carpeta. -> (ok, mensaje)

    La carpeta por defecto NO se acepta aqui: es la sesion con la que el usuario
    tiene su consola abierta, y echarle de ella desde una pantalla del Estudio
    seria un efecto que nadie pidio.
    """
    if not str(carpeta or "").strip():
        raise ErrorLogin(
            "esta cuenta usa la sesion por defecto del CLI, que es la misma con "
            "la que tienes tu consola abierta. Salir de ahi desde aqui te "
            "echaria tambien de tu terminal: entra con esta cuenta y el Estudio "
            "le dara su propia carpeta, y entonces ya se podra cerrar.")
    orden = [_ejecutable(), "auth", "logout"]
    entorno = cli_claude.entorno({"config_dir": carpeta})
    try:
        proceso = subprocess.run(orden, capture_output=True, timeout=60,
                                 env=entorno, **cli_claude.SIN_VENTANA)
    except (OSError, subprocess.TimeoutExpired) as fallo:
        raise ErrorLogin(f"no se ha podido cerrar la sesion: {fallo}") from fallo
    salida = ((proceso.stdout or b"") + (proceso.stderr or b"")).decode(
        "utf-8", errors="replace").strip()
    return proceso.returncode == 0, salida


# ------------------------------------------------------------------ el intento

class Intento:
    """Un `claude auth login` a medias, esperando el codigo.

    Los estados, y son los que pinta la pantalla:

        abriendo    el proceso arranco y todavia no ha escrito el enlace
        enlace      hay enlace y esta esperando el codigo   <- lo normal
        probando    se le paso el codigo y esta comprobandolo
        dentro      entro; `situacion` lo confirma
        fallo       no entro, y `mensaje` dice por que
    """

    def __init__(self, cuenta_id, carpeta):
        self.cuenta_id = cuenta_id
        self.carpeta = carpeta
        self.estado = "abriendo"
        self.enlace = ""
        self.mensaje = ""
        self.ficha = {}
        self.arranque = time.time()
        self.proceso = None
        self._trozos = []
        self._lock = threading.RLock()

    # -- lo que ve la pantalla
    def ver(self):
        with self._lock:
            return {
                "cuenta": self.cuenta_id,
                "estado": self.estado,
                "enlace": self.enlace,
                "mensaje": self.mensaje,
                "segundos": int(time.time() - self.arranque),
                "caduca_en": max(0, int(CADUCIDAD_INTENTO_S
                                        - (time.time() - self.arranque))),
                "cuenta_conectada": self.ficha,
            }

    # -- la salida del CLI, tal cual
    def _texto(self):
        return b"".join(self._trozos).decode("utf-8", errors="replace")

    def _bombear(self):
        flujo = self.proceso.stdout
        while True:
            trozo = flujo.read(1)
            if not trozo:
                break
            self._trozos.append(trozo)

    def arrancar(self):
        entorno = cli_claude.entorno({"config_dir": self.carpeta})
        # NO ABRIR NAVEGADOR: medido, sin esto sale un Edge en la maquina. Ver
        # la cabecera del modulo.
        entorno["BROWSER"] = "none"
        try:
            self.proceso = subprocess.Popen(
                [_ejecutable(), "auth", "login", "--claudeai"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, cwd=self.carpeta, env=entorno,
                **cli_claude.SIN_VENTANA)
        except OSError as fallo:
            raise ErrorLogin(
                f"no se ha podido lanzar el CLI de claude: {fallo}") from fallo
        threading.Thread(target=self._bombear, daemon=True).start()

        limite = time.time() + ESPERA_ENLACE_S
        while time.time() < limite:
            hallado = _ENLACE.search(self._texto())
            if hallado:
                with self._lock:
                    self.enlace = hallado.group(0)
                    self.estado = "enlace"
                return self.ver()
            if self.proceso.poll() is not None:
                break
            time.sleep(0.2)

        salida = self._texto().strip()
        self.matar()
        with self._lock:
            self.estado = "fallo"
            self.mensaje = (
                f"el CLI no ha escrito el enlace de acceso en {ESPERA_ENLACE_S} s. "
                f"Lo que dijo: {salida[:400] or '(nada)'}")
        return self.ver()

    def pegar(self, codigo):
        codigo = str(codigo or "").strip()
        if not codigo:
            raise ErrorLogin("pega el codigo que te ha dado la pagina")
        with self._lock:
            if self.estado not in ("enlace", "probando"):
                raise ErrorLogin(
                    f"este intento ya no espera un codigo (esta en "
                    f"'{self.estado}'). Vuelve a darle a Entrar.")
            self.estado = "probando"
        if self.proceso is None or self.proceso.poll() is not None:
            with self._lock:
                self.estado = "fallo"
                self.mensaje = ("el intento se cerro antes de recibir el "
                                "codigo; vuelve a darle a Entrar")
            return self.ver()
        marca = len(self._texto())
        try:
            self.proceso.stdin.write((codigo + "\n").encode("utf-8"))
            self.proceso.stdin.flush()
        except OSError as fallo:
            with self._lock:
                self.estado = "fallo"
                self.mensaje = f"no se le ha podido pasar el codigo: {fallo}"
            return self.ver()

        # UN CODIGO MAL COPIADO NO MATA EL INTENTO, y esto se midio: con un
        # codigo sin la parte de despues de la almohadilla el CLI escribe
        # «Invalid code. Please make sure the full code was copied.» y SIGUE
        # VIVO pidiendolo otra vez; con uno bien formado pero invalido escribe
        # «Login failed: …» y se cierra. Sin distinguirlo, el primer caso se
        # quedaba colgado los dos minutos enteros y despues obligaba a empezar
        # de cero -- con un enlace que seguia siendo perfectamente valido.
        #
        # La regla es generica a proposito, para que no dependa de como esten
        # escritas esas frases hoy: si ha dicho algo nuevo y sigue vivo pasado
        # un momento, es que lo esta volviendo a pedir.
        limite = time.time() + ESPERA_CODIGO_S
        dijo_algo = 0.0
        while time.time() < limite and self.proceso.poll() is None:
            if not dijo_algo and len(self._texto()) > marca:
                dijo_algo = time.time()
            if dijo_algo and time.time() - dijo_algo > ASENTAR_S:
                with self._lock:
                    self.estado = "enlace"          # el enlace sigue valiendo
                    self.mensaje = _ultima_linea(self._texto()[marca:]) or (
                        "ese codigo no le ha valido; copialo entero, incluido "
                        "todo lo que va detras de la almohadilla")
                return self.ver()
            time.sleep(0.2)
        if self.proceso.poll() is None:
            self.matar()
            with self._lock:
                self.estado = "fallo"
                self.mensaje = (f"el CLI no ha contestado en {ESPERA_CODIGO_S} s "
                                f"despues de darle el codigo")
            return self.ver()

        # LA VERDAD SE PREGUNTA, NO SE LEE DE LO QUE IMPRIMIO. Ver la cabecera.
        ficha = situacion(self.carpeta)
        with self._lock:
            self.ficha = ficha
            if ficha["conectada"]:
                self.estado = "dentro"
                self.mensaje = ""
            else:
                self.estado = "fallo"
                dicho = _FALLO.search(self._texto())
                self.mensaje = (dicho.group(1).strip() if dicho else
                                "el codigo no ha valido. Vuelve a abrir el "
                                "enlace: cada codigo sirve una sola vez.")
        return self.ver()

    def matar(self):
        proceso, self.proceso = self.proceso, None
        if proceso is None:
            return
        try:
            cli_claude.matar_arbol(proceso)
        except Exception:                                     # noqa: BLE001
            pass

    def caducado(self):
        return time.time() - self.arranque > CADUCIDAD_INTENTO_S


# ------------------------------------------------------------------ el registro

def _ejecutable():
    return cli_claude.localizar("entrar con una cuenta del CLI")


def _barrer():
    """Se lleva los intentos caducados. Se llama en cada operacion.

    Sin hilo de fondo a proposito: un temporizador mas es una cosa mas que puede
    quedarse viva cuando el servicio se recarga.
    """
    for cuenta_id, intento in list(_INTENTOS.items()):
        if intento.caducado() and intento.estado in ("abriendo", "enlace",
                                                     "probando"):
            intento.matar()
            intento.estado = "fallo"
            intento.mensaje = ("el intento caduco sin terminar. El codigo de "
                               "acceso tambien habria caducado: vuelve a "
                               "darle a Entrar.")


def entrar(cuenta_id, carpeta):
    """Arranca un login para esa cuenta. -> la ficha del intento

    Si ya habia uno a medias para la misma cuenta, se tira: el enlace viejo
    lleva dentro el reto de ESE intento y ya no vale.
    """
    with _LOCK:
        _barrer()
        anterior = _INTENTOS.get(cuenta_id)
        if anterior is not None:
            anterior.matar()
        os.makedirs(carpeta, exist_ok=True)
        intento = Intento(cuenta_id, carpeta)
        _INTENTOS[cuenta_id] = intento
    return intento.arrancar()


def pegar(cuenta_id, codigo):
    """Le pasa el codigo al intento de esa cuenta. -> la ficha del intento"""
    with _LOCK:
        _barrer()
        intento = _INTENTOS.get(cuenta_id)
    if intento is None:
        raise ErrorLogin("no hay ningun intento de acceso abierto para esta "
                         "cuenta. Dale a Entrar primero.")
    return intento.pegar(codigo)


def mirar(cuenta_id):
    """Como va el intento de esa cuenta, o None si no hay ninguno."""
    with _LOCK:
        _barrer()
        intento = _INTENTOS.get(cuenta_id)
    return intento.ver() if intento is not None else None


def cancelar(cuenta_id):
    """Tira el intento de esa cuenta. -> bool (habia alguno)"""
    with _LOCK:
        intento = _INTENTOS.pop(cuenta_id, None)
    if intento is None:
        return False
    intento.matar()
    return True


def olvidar_todos():
    """Para las pruebas y para cuando se borra una cuenta."""
    with _LOCK:
        for intento in _INTENTOS.values():
            intento.matar()
        _INTENTOS.clear()


def describir():
    return (f"login del CLI en carpeta propia por cuenta ({CARPETA_CUENTAS}), "
            f"enlace en pantalla y sin abrir navegador")
