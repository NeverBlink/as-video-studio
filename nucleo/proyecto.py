"""
Proyecto del Estudio de Video: una carpeta en disco con su configuracion.

    from nucleo.proyecto import Proyecto

    p = Proyecto.crear(r"C:\\IA\\estudio\\proyectos", "Caso Meridiano")
    p.ruta("assets", "reparto")          -> <raiz>/assets/reparto
    p.ruta_paso("guion")                 -> <raiz>/pasos/guion/v3   (version activa)
    p.ruta_trabajo("guion")              -> <raiz>/pasos/guion/trabajo

El puntero de version activa de cada paso vive en pasos/<id>/activa.json,
no en estado.json, para que Proyecto sepa resolver rutas sin depender de Estado.

Ademas expone las utilidades de E/S que usan el resto de modulos del nucleo:
leer_json, escribir_json (escritura atomica), lock_de, ahora, identificador.
"""
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
import unicodedata
from datetime import datetime

try:
    import msvcrt
except ImportError:  # linux/mac
    msvcrt = None
try:
    import fcntl
except ImportError:  # windows
    fcntl = None

NOMBRE_CONFIG = "proyecto.json"
VERSION_FORMATO = 1

#: Donde guarda cada version su manifiesto de unidades: `pasos/<paso>/_versiones/v<N>.json`.
#:
#: Vive aqui y no en `estado.py` porque hacen falta los dos: `Estado` lo escribe
#: y lo lee, y `Proyecto.duplicar` tiene que llevarselo a la copia. Una constante
#: en cada sitio son dos verdades que se separan en cuanto una cambie.
#:
#: El guion bajo delante NO es adorno: `p6_assets` recorre `pasos/<paso>/`
#: aceptando todo lo que empiece por "v", asi que una carpeta llamada
#: `versiones` se colaria como si fuera una version mas.
CARPETA_MANIFIESTOS = "_versiones"

ESPERA_CERROJO = 30.0       # segundos antes de rendirse esperando a otro proceso
ESPERA_ES = 10.0            # segundos reintentando ante bloqueos de Windows
PAUSA_ES = 0.002
# Lo que se insiste antes de copiar en vez de mover. Menos que ESPERA_ES porque
# aqui hay plan B: pasado este punto se copia y se sigue, no se falla.
ESPERA_MOVER = 5.0

_LOCKS = {}
_LOCKS_LOCK = threading.Lock()


class Cerrojo:
    """Exclusion mutua entre hilos Y entre procesos sobre un mismo fichero.

    El RLock por si solo no basta: el estudio se abre a la vez desde el
    servidor, desde los CLI de los pasos y desde los agentes de revision, y
    cada proceso tiene su propio RLock. Sin cerrojo en el sistema de ficheros
    dos procesos hacen leer-modificar-escribir a la vez y uno pierde su cambio.
    """

    def __init__(self, ruta):
        # el fichero de cerrojo NO va junto al fichero protegido: en Windows un
        # descriptor abierto impide borrar la carpeta, y borrar un proyecto es
        # una operacion normal. Va a un sitio fijo derivado de la ruta absoluta,
        # asi que todos los procesos de la maquina coinciden en el mismo fichero.
        clave = hashlib.sha256(
            os.path.normcase(os.path.abspath(ruta)).encode("utf-8")).hexdigest()[:24]
        self.ruta = os.path.join(tempfile.gettempdir(), "estudio_cerrojos",
                                 clave + ".lock")
        self._interno = threading.RLock()
        self._profundidad = 0
        self._descriptor = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()

    def acquire(self):
        self._interno.acquire()
        # el contador solo lo toca el hilo que ya posee el RLock, asi que las
        # tomas anidadas (Estado._guardar dentro de Estado.set_params) no
        # vuelven a pedir el cerrojo del sistema de ficheros y no se autobloquean
        self._profundidad += 1
        if self._profundidad == 1:
            try:
                self._tomar()
            except BaseException:
                self._profundidad -= 1
                self._interno.release()
                raise
        return True

    def release(self):
        self._profundidad -= 1
        if self._profundidad == 0:
            self._soltar()
        self._interno.release()

    def _abrir(self):
        if self._descriptor is None:
            os.makedirs(os.path.dirname(self.ruta), exist_ok=True)
            self._descriptor = os.open(self.ruta, os.O_RDWR | os.O_CREAT)
        return self._descriptor

    def _tomar(self):
        if msvcrt is None and fcntl is None:
            return
        descriptor = self._abrir()
        limite = time.monotonic() + ESPERA_CERROJO
        while True:
            try:
                if msvcrt is not None:
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.monotonic() >= limite:
                    raise TimeoutError(
                        f"otro proceso lleva {ESPERA_CERROJO:.0f}s con {self.ruta}")
                time.sleep(0.005)

    def _soltar(self):
        if self._descriptor is None:
            return
        try:
            if msvcrt is not None:
                os.lseek(self._descriptor, 0, os.SEEK_SET)
                msvcrt.locking(self._descriptor, msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        # se cierra al soltar para no acumular descriptores: el estudio abre un
        # cerrojo por fichero y por proyecto, y un servidor largo los sumaria
        try:
            os.close(self._descriptor)
        except OSError:
            pass
        self._descriptor = None


def lock_de(ruta):
    """Cerrojo reentrante de un fichero, compartido por hilos y procesos."""
    clave = os.path.normcase(os.path.abspath(ruta))
    with _LOCKS_LOCK:
        cerrojo = _LOCKS.get(clave)
        if cerrojo is None:
            cerrojo = Cerrojo(ruta)
            _LOCKS[clave] = cerrojo
        return cerrojo


def ahora():
    """Marca de tiempo local en ISO, sin microsegundos."""
    return datetime.now().isoformat(timespec="seconds")


def leer_json(ruta, por_defecto=None, estricto=False):
    """Lee un JSON; devuelve por_defecto si no existe o esta corrupto.

    Con estricto=True solo el "no existe" devuelve por_defecto: un fichero
    presente pero ilegible o corrupto lanza. Quien guarda estado no puede
    confundir "todavia no hay nada" con "ahora mismo no he podido leerlo", o
    escribira encima un documento vacio.
    """
    limite = time.monotonic() + ESPERA_ES
    espera = PAUSA_ES
    while True:
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except FileNotFoundError:
            return por_defecto
        except ValueError:
            if estricto:
                raise
            return por_defecto
        except PermissionError:
            # en Windows, mientras os.replace cambia el fichero, abrirlo da
            # PermissionError: es un instante, no un fichero ilegible
            if time.monotonic() >= limite:
                if estricto:
                    raise
                return por_defecto
            time.sleep(espera)
            espera = min(espera * 1.5, 0.05)


def leer_jsonl(ruta):
    """Registros de un .jsonl. Una linea a medio escribir no tumba el resto.

    Estaba duplicada en `bitacora` y en `coste`, que son los dos que escriben
    ficheros append-only. Vive aqui porque los dos ya entran por este modulo
    para todo lo de disco.
    """
    if not os.path.exists(ruta):
        return []
    registros = []
    with open(ruta, "r", encoding="utf-8") as fh:
        for cruda in fh:
            cruda = cruda.strip()
            if not cruda:
                continue
            try:
                registro = json.loads(cruda)
            except ValueError:
                continue
            if isinstance(registro, dict):
                registros.append(registro)
    return registros


def huella(valor):
    """Hash corto y estable de cualquier estructura serializable.

    La usan el grafo de build (`estado`, para las firmas de los pasos) y los
    pasos visuales (`medios`, para la clave de cache de cada imagen). Estaban
    escritas dos veces, identicas: si alguien "mejorase" una, la mitad del
    sistema cambiaria de firma y la otra mitad no, y todo quedaria obsoleto sin
    que nada lo explicase.
    """
    crudo = json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]


def escribir_json(ruta, datos):
    """Escribe JSON de forma atomica: fichero temporal + os.replace."""
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    with lock_de(ruta):
        # el temporal va en la misma carpeta porque os.replace solo es
        # atomico dentro del mismo volumen
        descriptor, temporal = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
                json.dump(datos, fh, ensure_ascii=False, indent=2)
            _reemplazar(temporal, ruta)
        except BaseException:
            if os.path.exists(temporal):
                os.remove(temporal)
            raise


def _reemplazar(temporal, ruta):
    """os.replace reintentado: en Windows falla si alguien esta leyendo."""
    limite = time.monotonic() + ESPERA_ES
    espera = PAUSA_ES
    while True:
        try:
            os.replace(temporal, ruta)
            return
        except PermissionError:
            if time.monotonic() >= limite:
                raise
            time.sleep(espera)
            espera = min(espera * 1.5, 0.05)


def recolocar(origen, destino, espera_s=ESPERA_MOVER):
    """Deja en `destino` lo que hay en `origen`, pase lo que pase.

    Mover es lo barato y es lo que se intenta primero. Pero en Windows un
    fichero que otro proceso tiene abierto NO se puede mover ni borrar --y
    mover una carpeta con uno dentro tampoco--, y aqui eso pasa de verdad: la
    interfaz esta ensenando los PNG de la carpeta de trabajo del paso mientras
    el paso termina, asi que justo al versionar hay handles abiertos sobre lo
    que se quiere mover. Un [WinError 32] en este punto tira una version entera
    de trabajo YA HECHO Y PAGADO, y ademas a mitad de camino.

    Lo que Windows si permite sobre un fichero abierto es SOBRESCRIBIRLO. Por
    eso el plan B es copiar encima y luego borrar el origen como se pueda: la
    version nueva queda completa, y lo que sobreviva en trabajo/ es basura
    inofensiva que se limpia sola en la siguiente pasada.

    Devuelve 'movido' o 'copiado', para que quien llame pueda decirlo.
    """
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    limite = time.monotonic() + float(espera_s)
    pausa = PAUSA_ES
    while True:
        try:
            _vaciar_destino(destino)
            os.rename(origen, destino)
            return "movido"
        except PermissionError:
            # WinError 32: lo tiene abierto otro proceso. Casi siempre dura
            # milisegundos --una respuesta HTTP terminando de enviarse--, asi
            # que se insiste un rato antes de caer al plan B.
            if time.monotonic() >= limite:
                break
            time.sleep(pausa)
            pausa = min(pausa * 1.5, 0.1)
        except OSError:
            # otro volumen, o cualquier otra cosa que insistir no va a
            # arreglar: al plan B directamente, sin esperar diez segundos
            break

    if os.path.isdir(origen):
        # dirs_exist_ok: se copia ENCIMA, sin borrar antes, que es la operacion
        # que no choca con un fichero abierto
        shutil.copytree(origen, destino, dirs_exist_ok=True)
    else:
        shutil.copy2(origen, destino)
    _borrar_como_se_pueda(origen)
    return "copiado"


def _vaciar_destino(destino):
    if not os.path.exists(destino):
        return
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    else:
        os.remove(destino)


def _borrar_como_se_pueda(ruta):
    """Se lleva lo que pueda y no protesta por lo que no. Es limpieza."""
    if os.path.isdir(ruta):
        shutil.rmtree(ruta, ignore_errors=True)
        return
    try:
        os.remove(ruta)
    except OSError:
        pass


def ruta_contenida(raiz, *partes):
    """Une partes bajo raiz y falla si el resultado se sale de raiz.

    Los nombres que se concatenan aqui vienen de JSON generado por modelos y de
    parametros que edita el usuario, asi que un '..' o una ruta absoluta no es
    hipotetico: sin esta comprobacion un paso puede escribir en cualquier sitio.
    """
    base = os.path.abspath(raiz)
    trozos = []
    for parte in partes:
        texto = str(parte)
        if "\x00" in texto:
            raise ValueError("ruta invalida: contiene un byte nulo")
        trozos.append(texto)
    destino = os.path.abspath(os.path.join(base, *trozos)) if trozos else base
    entero = os.path.normcase(os.path.realpath(destino))
    dentro = os.path.normcase(os.path.realpath(base))
    if entero != dentro and not entero.startswith(dentro + os.sep):
        raise ValueError(f"ruta fuera del proyecto: {os.path.join(*trozos)!r}")
    return destino


def _mudar_rutas(dato, desde, hasta):
    """Copia de `dato` con toda ruta que cuelgue de `desde` movida a `hasta`.

    Recorre la estructura entera y no hace un reemplazo sobre el texto del JSON,
    y la diferencia importa: en el fichero las barras van escapadas
    (`C:\\IA\\estudio`) y en memoria no, asi que un `str.replace` sobre el texto
    acierta unas veces y otras no -- que es peor que fallar siempre.

    Compara en minusculas porque Windows no distingue mayusculas en las rutas y
    el mismo proyecto aparece escrito de las dos formas segun quien lo escribiera.
    """
    if isinstance(dato, dict):
        return {k: _mudar_rutas(v, desde, hasta) for k, v in dato.items()}
    if isinstance(dato, list):
        return [_mudar_rutas(v, desde, hasta) for v in dato]
    if not isinstance(dato, str) or not dato:
        return dato
    for barra in ("\\", "/"):
        viejo = desde.replace("\\", barra)
        if dato.lower().startswith(viejo.lower()):
            # se responde con la MISMA barra con la que estaba escrito: mezclar
            # las dos en una ruta funciona en Windows y se lee fatal despues
            return hasta.replace("\\", barra) + dato[len(viejo):]
    return dato


def identificador(texto):
    """Convierte un nombre libre en un id de carpeta seguro y sin tildes."""
    plano = unicodedata.normalize("NFKD", str(texto))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = plano.lower().replace("ñ", "n")
    plano = re.sub(r"[^a-z0-9]+", "_", plano).strip("_")
    return plano or "proyecto"


class Proyecto:
    """Carpeta de un video con su proyecto.json y sus pasos versionados."""

    def __init__(self, raiz):
        self.raiz = os.path.abspath(raiz)
        if not os.path.isdir(self.raiz):
            raise FileNotFoundError(f"no existe la carpeta del proyecto: {self.raiz}")
        self.config = leer_json(self.ruta(NOMBRE_CONFIG))
        if not isinstance(self.config, dict):
            # adoptar una carpeta existente sin proyecto.json en vez de fallar
            self.config = {
                "id": identificador(os.path.basename(self.raiz)),
                "nombre": os.path.basename(self.raiz),
                "creado": ahora(),
                "actualizado": ahora(),
                "version_formato": VERSION_FORMATO,
            }
            escribir_json(self.ruta(NOMBRE_CONFIG), self.config)
        self.config.setdefault("id", identificador(os.path.basename(self.raiz)))
        self.config.setdefault("nombre", self.config["id"])
        self.id = self.config["id"]

    def __repr__(self):
        return f"<Proyecto {self.id} en {self.raiz}>"

    def ruta(self, *partes):
        """Ruta absoluta dentro del proyecto; ValueError si intenta salirse."""
        return ruta_contenida(self.raiz, *partes)

    def ruta_paso(self, paso_id, version=None, crear=False):
        """Carpeta de una version de un paso; la activa si version es None."""
        numero = version
        if numero is None:
            numero = self.version_activa(paso_id) or 1
        destino = self.ruta("pasos", str(paso_id), f"v{int(numero)}")
        if crear:
            os.makedirs(destino, exist_ok=True)
        return destino

    def ruta_trabajo(self, paso_id, crear=True):
        """Carpeta donde un paso escribe mientras corre, antes de versionarse."""
        destino = self.ruta("pasos", str(paso_id), "trabajo")
        if crear:
            os.makedirs(destino, exist_ok=True)
        return destino

    def version_activa(self, paso_id):
        """Numero de version activa de un paso, o None si nunca se completo."""
        datos = leer_json(self.ruta("pasos", str(paso_id), "activa.json"))
        if isinstance(datos, dict) and isinstance(datos.get("activa"), int):
            return datos["activa"]
        return None

    def fijar_version_activa(self, paso_id, numero):
        """Mueve el puntero de version activa de un paso."""
        ruta = self.ruta("pasos", str(paso_id), "activa.json")
        escribir_json(ruta, {"paso": str(paso_id), "activa": int(numero),
                             "fecha": ahora()})

    def guardar_config(self):
        """Persiste proyecto.json actualizando la fecha de modificacion."""
        self.config["actualizado"] = ahora()
        self.config.setdefault("creado", self.config["actualizado"])
        self.config.setdefault("version_formato", VERSION_FORMATO)
        self.config["id"] = self.id
        escribir_json(self.ruta(NOMBRE_CONFIG), self.config)

    @staticmethod
    def listar(raiz_base):
        """Proyectos disponibles bajo raiz_base, del mas reciente al mas viejo."""
        base = os.path.abspath(raiz_base)
        if not os.path.isdir(base):
            return []
        encontrados = []
        for nombre in sorted(os.listdir(base)):
            carpeta = os.path.join(base, nombre)
            if not os.path.isdir(carpeta):
                continue
            config = leer_json(os.path.join(carpeta, NOMBRE_CONFIG))
            if not isinstance(config, dict):
                continue
            ficha = dict(config)
            ficha["raiz"] = carpeta
            ficha.setdefault("id", identificador(nombre))
            ficha.setdefault("nombre", ficha["id"])
            encontrados.append(ficha)
        encontrados.sort(key=lambda f: str(f.get("actualizado", "")), reverse=True)
        return encontrados

    def duplicar(self, raiz_base, nombre, saltar=()):
        """Un proyecto NUEVO con lo que este tiene puesto HOY. -> Proyecto

        UNA COPIA NO ES UN CLON DEL DISCO, y por eso esto existe en vez de un
        `copytree`. El Aurora ocupa 11,6 GB porque guarda 41 versiones de
        assets, 10 de capas y 5 de render -- la historia de como se llego a lo
        que hay --, y de eso lo que vale para empezar otro video son 0,89 GB: la
        version ACTIVA de cada paso. La historia no se copia porque no es del
        video nuevo: es de las decisiones que se tomaron en el viejo, y estan
        contadas donde tienen que estar (la bitacora).

        Cada paso conserva su NUMERO de version: la copia del video largo arranca
        con assets en v41 y una sola version declarada. Se probo a renumerar a v1
        --parecia mas limpio-- y la copia salia ENTERA EN OBSOLETO, que es el
        peor resultado posible: obliga a pagar cuarenta y cuatro imagenes por
        haber copiado. El motivo esta en `Estado._sello_salida`, que es
        `huella([activa, firma])`: el numero de version entra en el sello, el
        sello entra en la firma del paso siguiente, y de ahi baja en cascada
        hasta el render. Renumerar cambia el sello sin cambiar ni un byte de lo
        producido.

        La otra salida --renumerar y volver a sellar-- se descarto por lo que ya
        avisa `retirar_unidades`: una firma escrita a mano es una firma con la
        que el paso no ha corrido nunca, y eso tapa obsolescencias de verdad.

        Asi que el numero se queda, y ademas dice algo cierto: de que version del
        original salio esta copia. La siguiente pasada creara la v42.

        LO QUE SE REESCRIBE, Y ES LA PARTE QUE HAY QUE MIRAR. El estado guarda
        rutas ABSOLUTAS (5.505 en el video largo: el wav de la locucion, los
        fotogramas de estilo, cada salida de cada paso), asi que una copia con el
        estado tal cual apuntaria a los ficheros del ORIGINAL -- y trabajar en la
        copia iria escribiendo encima del proyecto de al lado sin decirlo. Se
        recorre el JSON entero, valor a valor, y toda ruta que caiga dentro del
        origen se muda al destino. Lo mismo con los JSON de cada version
        copiada.

        LO QUE SI SE MUEVE, Y HAY QUE SABERLO: mudar las rutas cambia el sello
        de las unidades que guardan alguna, y ese sello entra en la firma del
        paso siguiente. En el video largo, cada unidad de assets apunta a la lamina
        de estilo con la que se genero (`referencias[].ruta`, en `trabajo/_refs`,
        que es una carpeta que ni siquiera se copia), asi que la copia sale con
        sus 49 capas y sus 49 clips en OBSOLETO aunque las imagenes sean las
        mismas byte a byte.

        No se disimula, y son los dos pasos que no cuestan dinero: se vuelven a
        montar en minutos. La alternativa era no mudar esa ruta -- dejar que la
        copia declare que uso un fichero del original -- y eso es exactamente la
        clase de mentira que este modulo evita en todo lo demas.

        `saltar` son ids de paso que NO se copian, para pedir una copia que
        rehaga desde ahi.

        Lo que NO viaja, a proposito:
          - la bitacora y el coste, que son el historial de OTRO video;
          - las carpetas `trabajo/`, que son lo que un paso deja a medias;
          - `previsualizaciones/`, que se rehacen solas y pesan.
        """
        saltar = {str(p) for p in (saltar or ())}
        copia = Proyecto.crear(raiz_base, nombre)
        equivalencias = {}          # ruta vieja -> ruta nueva, por si hace falta

        for paso in sorted(os.listdir(self.ruta("pasos"))
                           if os.path.isdir(self.ruta("pasos")) else []):
            if paso in saltar or not os.path.isdir(self.ruta("pasos", paso)):
                continue
            activa = self.version_activa(paso)
            if not activa:
                continue
            origen = self.ruta_paso(paso, activa)
            if not os.path.isdir(origen):
                continue
            destino = copia.ruta_paso(paso, activa, crear=True)
            _vaciar_destino(destino)
            shutil.copytree(origen, destino, dirs_exist_ok=True)
            copia.fijar_version_activa(paso, activa)
            equivalencias[origen] = destino

        # Las carpetas del PROYECTO, no de un paso: los fotogramas de estilo y
        # los videos de tono son entradas que el usuario eligio, y una copia sin
        # ellas no se puede regenerar sin volver a elegirlas.
        for carpeta in ("estilo", "tono"):
            if os.path.isdir(self.ruta(carpeta)):
                shutil.copytree(self.ruta(carpeta), copia.ruta(carpeta),
                                dirs_exist_ok=True)

        estado = leer_json(self.ruta("estado.json"))
        if isinstance(estado, dict):
            estado = _mudar_rutas(estado, self.raiz, copia.raiz)
            for paso_id, datos in (estado.get("pasos") or {}).items():
                if not isinstance(datos, dict):
                    continue
                if paso_id in saltar:
                    # el paso se queda SIN HACER, no a medias: si se dejara la
                    # firma sin las salidas, la copia diria «listo» de algo que
                    # no tiene ni un fichero
                    datos.update({"activa": None, "versiones": [], "salidas": {},
                                  "unidades": {}, "firma": None, "marca": None})
                    continue
                # SOLO LA ACTIVA, con su numero. `activa` y `firma` no se tocan:
                # los dos entran en el sello del paso, y moverlos deja la copia
                # entera en obsoleto sin que haya cambiado nada de lo producido.
                activa = datos.get("activa")
                datos["versiones"] = [
                    v for v in (datos.get("versiones") or [])
                    if isinstance(v, dict) and v.get("n") == activa]
                # Y SU MANIFIESTO, que desde que vive fuera de estado.json no
                # viaja solo. Sin esto la copia nace con una version que dice
                # tener 240 unidades y un fichero de manifiesto que no existe:
                # todo va bien hasta que alguien pulsa «Revertir» en la copia.
                #
                # Solo el de la version activa, porque es la unica que sobrevive
                # al filtro de arriba. Y solo si el original lo tiene aparte: las
                # versiones en formato viejo lo llevan dentro de la entrada y se
                # copian con ella.
                if activa is not None:
                    manifiesto = self.ruta("pasos", paso_id,
                                           CARPETA_MANIFIESTOS, f"v{activa}.json")
                    # estricto: un manifiesto que ESTA pero no se puede leer tiene
                    # que reventar aqui. Sin esto se confunde con "no hay", que es
                    # lo normal en una version de formato viejo, y la copia nace
                    # con una version que dice tener 232 unidades y ningun
                    # manifiesto -- sin un solo aviso, hasta que alguien revierte.
                    contenido = leer_json(manifiesto, estricto=True)
                    if contenido is not None:
                        # Y SE LE MUDAN LAS RUTAS, que es la mitad que se olvida.
                        # El manifiesto de assets guarda rutas ABSOLUTAS dentro de
                        # las salidas de cada unidad (111 de ellas en un video
                        # real). Cuando vivia dentro de estado.json se las mudaba
                        # el `_mudar_rutas` de arriba; ahora que vive aparte hay
                        # que hacerlo aqui, o la copia apunta a los ficheros del
                        # proyecto ORIGINAL.
                        escribir_json(
                            copia.ruta("pasos", paso_id, CARPETA_MANIFIESTOS,
                                       f"v{activa}.json"),
                            _mudar_rutas(contenido, self.raiz, copia.raiz))
            escribir_json(copia.ruta("estado.json"), estado)

        # Y los JSON de dentro de cada version copiada: el plan apunta al meta de
        # la narracion, el movimiento a los hyperframes... con rutas absolutas.
        for destino in equivalencias.values():
            for carpeta, _, ficheros in os.walk(destino):
                for fichero in ficheros:
                    if not fichero.lower().endswith(".json"):
                        continue
                    ruta_json = os.path.join(carpeta, fichero)
                    datos = leer_json(ruta_json)
                    if datos is None:
                        continue
                    mudado = _mudar_rutas(datos, self.raiz, copia.raiz)
                    if mudado != datos:
                        escribir_json(ruta_json, mudado)

        copia.config["copia_de"] = self.id
        copia.guardar_config()
        return copia

    @staticmethod
    def crear(raiz_base, nombre):
        """Crea la carpeta del proyecto con un id unico y devuelve el Proyecto."""
        base = os.path.abspath(raiz_base)
        os.makedirs(base, exist_ok=True)
        semilla = identificador(nombre)
        id_final = semilla
        contador = 2
        while os.path.exists(os.path.join(base, id_final)):
            id_final = f"{semilla}_{contador}"
            contador += 1
        raiz = os.path.join(base, id_final)
        os.makedirs(os.path.join(raiz, "pasos"), exist_ok=True)
        escribir_json(os.path.join(raiz, NOMBRE_CONFIG), {
            "id": id_final,
            "nombre": str(nombre),
            "creado": ahora(),
            "actualizado": ahora(),
            "version_formato": VERSION_FORMATO,
        })
        return Proyecto(raiz)
