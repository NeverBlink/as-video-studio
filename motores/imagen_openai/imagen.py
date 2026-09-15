"""
Motor de imagen sobre gpt-image-2.

Paradigma de referencias, en orden fijo porque el prompt las cita por posicion:

  1. ESTILO      frames del video de referencia -> fija el lenguaje visual
  2. ESTRUCTURA  render del blockout 3D         -> fija encuadre y geometria
  3. PERSONAJES  hojas de reparto               -> fija identidad entre planos
  4. CONTINUIDAD plano anterior ya generado     -> fija paleta y elementos

La estructura viene del blockout y no de una descripcion, que es lo que permite
que los callouts y los zooms se coloquen despues por coordenada y no a ojo.

Las llamadas son de red, asi que se paralelizan: a diferencia de la GPU local,
que es estrictamente serie, aqui el tiempo de pared baja casi linealmente con la
concurrencia.
"""
import base64
import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image

API_URL = "https://api.openai.com/v1/images/edits"
MODELO = "gpt-image-2"

PRECIO = {"low": 0.006, "medium": 0.041, "high": 0.165}
TAMANOS = {"apaisado": "1536x1024", "cuadrado": "1024x1024", "vertical": "1024x1536"}

_gasto = {"usd": 0.0, "llamadas": 0}

# ------------------------------------------------------------------ el freno
#
# El limite que salta de verdad aqui no es el de peticiones: es el de IMAGENES
# DE ENTRADA por minuto. Cada plano manda entre 8 y 14 adjuntos --la lamina de
# estilo, el lineart del blockout, las hojas de reparto, los dos planos
# anteriores--, asi que una tanda con varias cadenas en paralelo se lo come en
# segundos:
#
#   HTTP 429: Rate limit reached for gpt-image-2 ... on input-images per min:
#   Limit 5, Used 5, Requested 1
#
# Y era imposible salir de ahi reintentando como se reintentaba: dos esperas de
# 3 s y 6 s contra una ventana que se renueva CADA MINUTO. Se agotaban los dos
# intentos, el plano moria, y con el se caia la tanda entera despues de haber
# pagado los planos anteriores.
#
# Dos cosas lo arreglan. Una: esperar lo que dice la API --su cabecera
# 'retry-after' o el «try again in 4.2s» de su propio mensaje-- y no un numero
# inventado. Y dos: que el freno sea COMPARTIDO. Sin eso, cuatro cadenas en
# paralelo se comen la ventana entre las cuatro y las cuatro reintentan a la
# vez, que es exactamente la forma de no salir nunca.
_FRENO = threading.Condition()
_LIBRE_EN = [0.0]                       # time.monotonic() a partir del cual se puede


def _frenar(segundos, motivo="", cuenta=None):
    """Para a TODAS las cadenas DE ESA CUENTA hasta que su ventana se renueve.

    El freno es por cuenta desde que hay varias: un 429 de la cuenta 2 no dice
    nada de la ventana de la cuenta 1, y frenarlas juntas tiraria justo la
    mitad de la velocidad que la segunda clave viene a comprar.
    """
    cuenta = cuenta or _cuentas()[0]
    with _FRENO:
        cuenta.libre_en[0] = max(cuenta.libre_en[0],
                                 time.monotonic() + float(segundos))
        if motivo:
            print(f"[imagen] limite de la API ({cuenta.nombre}): esperando "
                  f"{segundos:.0f}s ({motivo})", flush=True)


def _esperar_turno(cuenta=None):
    """Espera a que se levante el freno de esa cuenta, si lo hay."""
    cuenta = cuenta or _cuentas()[0]
    while True:
        with _FRENO:
            falta = cuenta.libre_en[0] - time.monotonic()
        if falta <= 0:
            return
        time.sleep(min(falta, 1.0))


#: Cuanto se espera cuando la API no dice cuanto. La ventana de los limites por
#: minuto es de 60 s, asi que esperar menos es garantizar otro 429.
ESPERA_LIMITE_S = 65.0
#: Tope de una espera, por si la API pide algo absurdo.
ESPERA_MAXIMA_S = 300.0

# ------------------------------------------------------------------ el cubo
#
# El freno de arriba es REACTIVO: solo se entera del limite cuando ya lo ha
# rebasado. Eso convierte el 429 en el mecanismo de control, y con varias
# cadenas en paralelo significa que cada tanda empieza estrellandose.
#
# Esto es lo otro: un cubo de fichas. No se sale a llamar si en los ultimos 60
# segundos ya se han hecho tantas llamadas como permite el limite. El limite no
# se adivina -- se lee de las cabeceras 'x-ratelimit-*' de la propia respuesta, y
# solo si no viene ninguna se usa el numero de abajo, que es el que dijo el 429
# que le salto al usuario ("input-images per min: Limit 5").
LIMITE_POR_MINUTO = [5]
_VENTANA_S = 60.0
#: [(instante, cuantas imagenes de entrada llevaba esa llamada)]
_LLAMADAS = []
_CUBO = threading.Condition()
_CABECERAS_VISTAS = [False]
#: El tope que enseño un 429. Una respuesta buena no puede subir por encima.
_TECHO_DEL_429 = [None]


class _Cuenta:
    """El estado de UNA cuenta de OpenAI: su clave, su cubo y su freno.

    Cada cuenta tiene su propia ventana de limites EN EL SERVIDOR, asi que
    compartir cubo entre dos claves seria frenar a una con los 429 de la otra.
    La cuenta principal REUTILIZA las listas historicas del modulo
    (LIMITE_POR_MINUTO, _LLAMADAS, _LIBRE_EN...) para que las suites y
    cualquier calibrado externo sigan mirando donde siempre.
    """

    def __init__(self, nombre, clave, limite=None, llamadas=None,
                 libre_en=None, techo=None, vistas=None):
        self.nombre = nombre
        self.clave = clave
        self.limite = limite if limite is not None else [5]
        self.llamadas = llamadas if llamadas is not None else []
        self.libre_en = libre_en if libre_en is not None else [0.0]
        self.techo = techo if techo is not None else [None]
        self.vistas = vistas if vistas is not None else [False]
        self.etiqueta = ""
        self._sin_saldo = False
        self.sin_saldo_desde = None
        # LA CLAVE NO VALE (401 «Incorrect API key»): una clave rotada o
        # revocada. No es «sin saldo» --no se arregla recargando-- y no vuelve
        # sola: se queda fuera hasta que cambie el fichero de claves
        # (`_cuentas` rehace la lista al cambiar su sello). Antes un 401 de UNA
        # de las tres cuentas tumbaba la tanda entera (02-09-2026).
        self.clave_rechazada = False

    @property
    def sin_saldo(self):
        """Si esta cuenta esta fuera del reparto AHORA MISMO.

        Caduca (GRACIA_SIN_SALDO_S). Antes se ponia y no se quitaba nunca: una
        cuenta agotada por la manana seguia sin usarse por la tarde aunque se
        hubiera recargado, y solo reiniciando el servicio volvia al reparto.
        """
        if not self._sin_saldo:
            return False
        desde = self.sin_saldo_desde
        if desde is not None and time.monotonic() - desde > GRACIA_SIN_SALDO_S:
            self._sin_saldo = False
            self.sin_saldo_desde = None
            return False
        return True

    @sin_saldo.setter
    def sin_saldo(self, valor):
        self._sin_saldo = bool(valor)
        self.sin_saldo_desde = time.monotonic() if valor else None

    def espera_estimada(self, cuantas, ahora=None):
        """Cuanto le queda a esta cuenta para poder salir, SIN bloquear."""
        ahora = time.monotonic() if ahora is None else ahora
        espera = max(0.0, self.libre_en[0] - ahora)
        with _CUBO:
            vivas = [(t, n) for t, n in self.llamadas if ahora - t < _VENTANA_S]
            tope = max(1, int(self.limite[0]))
            gastadas = sum(n for _, n in vivas)
            if vivas and gastadas + min(max(1, int(cuantas or 1)), tope) > tope:
                espera = max(espera, _VENTANA_S - (ahora - vivas[0][0]))
        return espera


_CUENTAS_CARGADAS = []
#: (mtime, tamano) del almacen de claves con el que se cargaron las cuentas de
#: arriba. Si cambia, se recargan solas: editar las claves desde la pantalla del
#: Estudio y tener que reiniciar el servicio para que entren es exactamente el
#: fallo que `medios.motor` existe para no repetir.
_SELLO_CLAVES = [None]

#: El almacen que escribe la pantalla de configuracion del Estudio
#: (pasos/claves.py). Se lee por CONTRATO -- una ruta y una forma --, nunca
#: importando codigo del Estudio: este motor tambien lo usan otras cosas.
#: La carpeta de secretos se puede mover con ESTUDIO_SECRETOS: en el servidor
#: cada cuenta tiene la suya. Sin la variable, el valor es el de siempre.
CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")
RUTA_CLAVES = os.path.join(CARPETA_SECRETOS, "claves.json")
RUTA_ENV = os.path.join(CARPETA_SECRETOS, ".env")

#: Cuanto se deja fuera del reparto una cuenta que dijo "sin credito". No es
#: para siempre a proposito: una cuenta que se agoto a las diez y se recargo a
#: las once seguia fuera hasta reiniciar, y el panel de la pantalla la habria
#: seguido pintando en rojo con dinero dentro.
GRACIA_SIN_SALDO_S = 1800.0


def _sello_de(ruta):
    try:
        estado = os.stat(ruta)
    except OSError:
        return None
    return (estado.st_mtime_ns, estado.st_size)


def _del_almacen():
    """[(etiqueta, clave)] del claves.json que escribe el Estudio."""
    if not os.path.exists(RUTA_CLAVES):
        return []
    try:
        with open(RUTA_CLAVES, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return []
    salida = []
    for cruda in (datos.get("openai") or []) if isinstance(datos, dict) else []:
        if not isinstance(cruda, dict) or cruda.get("activa") is False:
            continue
        clave = str(cruda.get("clave") or "").strip()
        if clave:
            salida.append((str(cruda.get("etiqueta") or "").strip(), clave))
    return salida


def _del_entorno():
    claves = []
    principal = os.environ.get("OPENAI_API_KEY")
    if principal and principal.strip():
        claves.append(("entorno", principal.strip()))
    for indice in range(2, 10):
        clave = os.environ.get(f"OPENAI_API_KEY_{indice}")
        if clave and clave.strip():
            claves.append((f"entorno {indice}", clave.strip()))
    return claves


def _del_env():
    claves = []
    if not os.path.exists(RUTA_ENV):
        return claves
    with open(RUTA_ENV, "r", encoding="utf-8-sig") as fh:
        for linea in fh:
            m = re.match(r"^OPENAI_API_KEY(_\d+)?=(.*)$", linea.strip())
            if m and m.group(2).strip():
                claves.append(("", m.group(2).strip()))
    return claves


def _claves_declaradas():
    """Todas las claves que hay, de las tres fuentes, sin repetir.

    Se FUSIONAN. Antes el entorno y el fichero eran excluyentes -- en cuanto
    aparecia una OPENAI_API_KEY_2 exportada, las del fichero desaparecian en
    silencio -- y el reparto se quedaba corto sin que nada lo dijera.
    """
    # El ORDEN lo pone el entorno (una clave exportada es un override
    # explicito), pero la ETIQUETA la pone el almacen: es el unico sitio donde
    # esta escrito de quien es cada cuenta, y sin esto la cuenta que ademas
    # estuviera en el entorno se llamaria "entorno" en el panel en vez de por su
    # correo.
    del_almacen = dict((clave, etiqueta) for etiqueta, clave in _del_almacen())
    fuentes = _del_entorno() + _del_almacen() + _del_env()
    vistas, salida = set(), []
    for etiqueta, clave in fuentes:
        if clave in vistas:
            continue
        vistas.add(clave)
        salida.append((del_almacen.get(clave) or etiqueta, clave))
    return salida


def _claves_extra():
    """Las claves de la segunda cuenta en adelante. Se conserva por compatibilidad."""
    return [clave for _, clave in _claves_declaradas()[1:]]


def _nombre_de(indice, etiqueta):
    return f"cuenta {indice} ({etiqueta})" if etiqueta else f"cuenta {indice}"


def _cuentas():
    """Las cuentas disponibles. Se recargan solas si cambia el almacen de claves."""
    sello = _sello_de(RUTA_CLAVES)
    if _CUENTAS_CARGADAS and sello == _SELLO_CLAVES[0]:
        return _CUENTAS_CARGADAS

    declaradas = _claves_declaradas()
    if not declaradas:
        # Se conserva el mensaje de siempre: es el que sale por pantalla y el
        # que la gente busca cuando el Estudio no genera.
        declaradas = [("", cargar_api_key())]

    # Lo que estaba marcado sin credito sigue estandolo aunque se recarguen las
    # cuentas: una recarga de claves no recarga la tarjeta de nadie.
    gastadas = {c.clave: getattr(c, "sin_saldo_desde", None)
                for c in _CUENTAS_CARGADAS if c.sin_saldo}
    # y una clave rechazada sigue rechazada mientras sea LA MISMA clave: si el
    # fichero trae otra para esa cuenta, entra limpia
    rechazadas = {c.clave for c in _CUENTAS_CARGADAS
                  if getattr(c, "clave_rechazada", False)}

    nuevas = []
    for indice, (etiqueta, clave) in enumerate(declaradas, start=1):
        if indice == 1:
            cuenta = _Cuenta(_nombre_de(1, etiqueta), clave,
                             limite=LIMITE_POR_MINUTO, llamadas=_LLAMADAS,
                             libre_en=_LIBRE_EN, techo=_TECHO_DEL_429,
                             vistas=_CABECERAS_VISTAS)
        else:
            cuenta = _Cuenta(_nombre_de(indice, etiqueta), clave)
        cuenta.etiqueta = etiqueta
        if clave in gastadas:
            cuenta.sin_saldo = True
            cuenta.sin_saldo_desde = gastadas[clave]
        if clave in rechazadas:
            cuenta.clave_rechazada = True
        nuevas.append(cuenta)

    _CUENTAS_CARGADAS[:] = nuevas
    _SELLO_CLAVES[0] = sello
    if len(_CUENTAS_CARGADAS) > 1:
        print(f"[imagen] {len(_CUENTAS_CARGADAS)} cuentas de OpenAI: las "
              f"llamadas se reparten y cada una lleva su propio limite",
              flush=True)
    return _CUENTAS_CARGADAS


def cuentas_para_la_pantalla():
    """Como esta cada cuenta AHORA. Sin claves: etiqueta, estado y espera.

    Es lo que hace que el panel de configuracion no sea una lista de secretos
    escritos sino un sitio donde se ve por que no se esta generando.
    """
    fichas = []
    for cuenta in _cuentas():
        fichas.append({
            "nombre": cuenta.nombre,
            "etiqueta": getattr(cuenta, "etiqueta", ""),
            "cola": f"…{cuenta.clave[-4:]}" if len(cuenta.clave or "") > 4 else "",
            "sin_saldo": bool(cuenta.sin_saldo),
            "clave_rechazada": bool(getattr(cuenta, "clave_rechazada", False)),
            "limite_por_minuto": int(cuenta.limite[0]),
            "medido": bool(cuenta.vistas[0]),
            "espera_s": round(cuenta.espera_estimada(1), 2),
        })
    return fichas


def _elegir_cuenta(cuantas):
    """La cuenta que puede salir a llamar ANTES. Las sin saldo no juegan."""
    todas = _cuentas()
    vivas = [c for c in todas if not c.sin_saldo and not c.clave_rechazada]
    if not vivas and all(c.clave_rechazada for c in todas):
        raise RuntimeError(
            "OpenAI rechaza todas las claves que hay (401 Incorrect API key): "
            "revisalas en Configuracion > Claves. Lo ya generado no se pierde.")
    if not vivas:
        raise SinSaldo(
            "todas las cuentas de OpenAI se han quedado sin credito, asi que "
            "no se pueden generar mas imagenes. Recarga en "
            "https://platform.openai.com/settings/organization/billing y "
            "retoma la generacion: lo ya generado NO se pierde ni se vuelve "
            "a pagar.")
    if len(vivas) == 1:
        return vivas[0]
    ahora = time.monotonic()
    return min(vivas, key=lambda c: c.espera_estimada(cuantas, ahora))


def _pedir_ficha(cuantas=1, cuenta=None):
    """Espera hasta que quepan `cuantas` imagenes mas en la ventana del minuto.

    Se cuentan IMAGENES DE ENTRADA y no llamadas, porque el limite que salta es
    de input-images por minuto y cada plano manda entre cuatro y catorce
    adjuntos. Contando llamadas, cuatro cadenas metian veinte imagenes en la
    misma ventana contra un tope de cinco y el 429 seguia siendo el mecanismo de
    control. El cubo es POR CUENTA: cada clave tiene su propia ventana.
    """
    cuenta = cuenta or _cuentas()[0]
    cuantas = max(1, int(cuantas or 1))
    while True:
        with _CUBO:
            ahora = time.monotonic()
            cuenta.llamadas[:] = [(t, n) for t, n in cuenta.llamadas
                                  if ahora - t < _VENTANA_S]
            tope = max(1, int(cuenta.limite[0]))
            gastadas = sum(n for _, n in cuenta.llamadas)
            # `min(cuantas, tope)` para que una llamada mas gorda que el cubo
            # entero pueda salir igualmente: si no, se esperaria para siempre
            if gastadas + min(cuantas, tope) <= tope or not cuenta.llamadas:
                cuenta.llamadas.append((ahora, cuantas))
                return
            espera = _VENTANA_S - (ahora - cuenta.llamadas[0][0]) + 0.05
        time.sleep(min(max(espera, 0.05), _VENTANA_S))


def _calibrar(respuesta, cuenta=None):
    """Aprende el limite real de las cabeceras, en vez de suponerlo.

    Se llama en TODAS las respuestas, no solo en los errores: el sitio donde la
    API dice cuanto te queda es la respuesta buena, y tirarla obliga a
    descubrirlo estrellandose. Tolerante a proposito: si no viene ninguna
    cabecera, el comportamiento es exactamente el de antes. Calibra LA CUENTA
    que respondio: cada clave tiene sus propios limites en el servidor.
    """
    cuenta = cuenta or _cuentas()[0]
    cabeceras = {k.lower(): v for k, v in (respuesta.headers or {}).items()
                 if k.lower().startswith("x-ratelimit-")}
    if cabeceras and not cuenta.vistas[0]:
        # Una vez por proceso y por cuenta, para que el limite real deje de ser
        # una discusion sobre lo que creemos que cuenta el cubo.
        cuenta.vistas[0] = True
        print(f"[imagen] limites que declara la API ({cuenta.nombre}): "
              f"{cabeceras}", flush=True)
    # Se eligen los candidatos, no se aplica el ultimo que pase. Con
    # {limit-images: 5, limit-requests: 500, limit-tokens: 2000000} el bucle
    # ingenuo acababa en 2.000.000 o en 5 segun el ORDEN en que el servidor
    # emitiera las cabeceras, y con el de tokens el cubo no frena nada.
    #
    # Tres filtros: el recurso tiene que ser de imagenes o de peticiones (el
    # cubo cuenta llamadas, no tokens); su ventana tiene que ser de un minuto o
    # menos, lo que descarta solo los cupos diarios; y de los que sobrevivan
    # manda el MAS PEQUENO, que es el que va a saltar primero.
    candidatos = []
    for clave, valor in cabeceras.items():
        recurso = clave.rsplit("-", 1)[-1]
        if "-limit-" not in clave:
            continue
        if not ("image" in recurso or "request" in recurso):
            continue
        try:
            tope = int(str(valor).strip())
        except ValueError:
            continue
        ventana = _segundos_de(cabeceras.get(f"x-ratelimit-reset-{recurso}"), 60.0)
        if ventana > 60.0 or not 1 <= tope <= 10000:
            continue
        candidatos.append((tope, clave))
    if candidatos:
        tope, clave = min(candidatos)
        # y una respuesta buena nunca puede SUBIR por encima de lo que enseño un
        # 429: ese numero lo dijo el servidor sobre el cubo que de verdad salta
        if cuenta.techo[0]:
            tope = min(tope, cuenta.techo[0])
        if tope != cuenta.limite[0]:
            cuenta.limite[0] = tope
            print(f"[imagen] limite por minuto de {cuenta.nombre} calibrado a "
                  f"{tope} ({clave})", flush=True)
    # Si la API dice que no queda nada, se frena ANTES de rebotar. Con los
    # mismos filtros: un 'remaining-tokens: 0' de cupo diario pararia la tanda
    # entera cinco minutos desde una respuesta que ha ido bien.
    for clave, valor in cabeceras.items():
        recurso = clave.rsplit("-", 1)[-1]
        if "-remaining-" not in clave:
            continue
        if not ("image" in recurso or "request" in recurso):
            continue
        try:
            quedan = int(str(valor).strip())
        except ValueError:
            continue
        espera = _segundos_de(cabeceras.get(f"x-ratelimit-reset-{recurso}"),
                              ESPERA_LIMITE_S)
        if quedan <= 0 and espera <= 60.0:
            _frenar(espera, f"{clave}=0", cuenta)


def cargar_api_key():
    clave = os.environ.get("OPENAI_API_KEY")
    if clave:
        return clave.strip()
    for ruta in (RUTA_ENV,):
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8-sig") as fh:
                for linea in fh:
                    m = re.match(r"^OPENAI_API_KEY=(.*)$", linea.strip())
                    if m:
                        return m.group(1).strip()
    raise SystemExit("Falta OPENAI_API_KEY")


def normalizar(ruta, cache_dir, lado_max=1024):
    """PNG RGBA. La API rechaza modos 'L' o 'P', y los pases del blockout salen
    en escala de grises.

    El nombre en la cache lleva la huella de la RUTA COMPLETA, y no solo el
    nombre del fichero, porque dos referencias distintas se llaman igual mas a
    menudo de lo que parece: el pase 'hombro__lineart.png' existe dentro de la
    carpeta de CADA set, asi que tres sets con ese encuadre se pisaban la misma
    entrada y el segundo se llevaba la imagen del primero -- con la comprobacion
    de fecha, encima, dandola por buena.
    """
    os.makedirs(cache_dir, exist_ok=True)
    nombre, extension = os.path.splitext(os.path.basename(ruta))
    firma = hashlib.sha1(os.path.normcase(os.path.abspath(ruta)).encode("utf-8"))
    destino = os.path.join(cache_dir, f"{nombre}__{firma.hexdigest()[:8]}{extension}")
    if _al_dia(destino, ruta):
        return destino
    img = Image.open(ruta).convert("RGBA")
    if max(img.size) > lado_max:
        escala = lado_max / max(img.size)
        img = img.resize((int(img.width * escala), int(img.height * escala)),
                         Image.LANCZOS)
    # SE ESCRIBE A UN TEMPORAL Y SE SUSTITUYE DE GOLPE, y no es limpieza.
    #
    # Las llamadas van en paralelo (`generar_lote`, y aguas arriba las cadenas de
    # p6), y varias comparten referencias: el estilo del video es el mismo en
    # todos los planos y la hoja de un personaje la usan todos sus planos. Con
    # `img.save(destino)` a pelo, una cadena puede estar ESCRIBIENDO este fichero
    # mientras otra ya lo ha visto existir y lo esta abriendo para adjuntarlo. Lo
    # que sale por el cable es medio PNG, y la API contesta:
    #
    #     HTTP 400: Invalid image file or mode for image 1
    #
    # que manda a buscar un fichero corrupto en el disco -- y en el disco no hay
    # ninguno, porque para cuando alguien va a mirarlo ya se termino de escribir.
    # Visto el 25-08 tumbando una tanda en el plano 89 de 93, con las 88
    # anteriores ya pagadas. El temporal lleva el pid y el hilo dentro para que
    # dos escritores simultaneos tampoco se pisen entre ellos.
    temporal = "%s.%d.%d.tmp" % (destino, os.getpid(),
                                 threading.get_ident() & 0xffff)
    img.save(temporal, "PNG")
    return _sustituir(temporal, destino, ruta)


#: Cuanto se insiste ante un destino bloqueado antes de darlo por perdido. Un
#: bloqueo asi dura milisegundos; esperar dos segundos es barato al lado de una
#: tanda de imagenes tirada. Los mismos escalones que `medios.ESPERAS_BLOQUEO`
#: del Estudio, que existe por esto mismo en el render.
ESPERAS_BLOQUEO = (0.1, 0.25, 0.5, 1.0)


def _sustituir(temporal, destino, origen):
    """`os.replace` aguantando que el destino este abierto. -> destino.

    EL TEMPORAL DE ARRIBA RESUELVE MEDIA CARRERA Y ABRE LA OTRA MITAD. Evita que
    se lea un PNG a medio escribir, si; pero en Windows no se puede sustituir un
    fichero que otro tiene ABIERTO, y aqui siempre hay alguien: estas cadenas
    van en paralelo y comparten referencias --el estilo del video es el mismo en
    todos los planos y la hoja de un personaje la usan todos los suyos--, asi
    que mientras un hilo hace el replace otro puede tener ese mismo destino
    abierto para adjuntarlo a su peticion. Y detras va el antivirus, que analiza
    cada fichero al cerrarlo. El sintoma:

        PermissionError: [WinError 5] Access is denied:
        '...\\_refs\\tile_..._69ecf3d8.png.40948.32444.tmp'
        -> '...\\_refs\\tile_..._69ecf3d8.png'

    Y ES EL MISMO FICHERO. El nombre lleva dentro el sha1 de la ruta de origen,
    asi que dos hilos que se pisan aqui han escrito lo mismo byte a byte. Por
    eso, si despues de insistir el destino ya esta ahi y no es mas viejo que su
    origen, se tira el temporal y se usa: perder una tanda pagada porque otro
    hilo gano la carrera para dejar EXACTAMENTE el fichero que hacia falta seria
    absurdo.

    Lo que si sube es un bloqueo que no deja destino utilizable: eso no es una
    carrera, es otra cosa, y taparlo dejaria el plano sin su referencia.
    """
    fallo = None
    for espera in ESPERAS_BLOQUEO + (0,):
        try:
            os.replace(temporal, destino)
            return destino
        except PermissionError as choque:
            fallo = choque
            if espera:
                time.sleep(espera)
    if _al_dia(destino, origen):
        try:
            os.remove(temporal)
        except OSError:
            pass
        return destino
    raise fallo


def _al_dia(destino, origen):
    """El destino existe y no es mas viejo que su origen."""
    try:
        return (os.path.exists(destino)
                and os.path.getmtime(destino) >= os.path.getmtime(origen))
    except OSError:
        return False


def generar(prompt, referencias, *, quality="low", tamano="apaisado",
            api_key=None, reintentos=6):
    # Sin referencias esta llamada NO se puede hacer, y hay que decirlo aqui.
    # Motivo: requests solo pone 'multipart/form-data' cuando files no esta
    # vacio; con la lista vacia cae a 'x-www-form-urlencoded', que es justo lo
    # que /v1/images/edits rechaza. El sintoma era un 400 de la API diciendo
    # "Unsupported content type", que suena a fallo del servidor y manda a
    # buscar al sitio equivocado, cuando lo que pasa es que falta una entrada.
    if not referencias:
        raise ValueError(
            "generar() necesita al menos una imagen de referencia: la API de "
            "edicion de imagenes se llama con adjuntos, y sin ellos la peticion "
            "sale con el formato equivocado y la rechaza con un error que no "
            "explica nada. Pon al menos una imagen de estilo.")
    faltan = [r for r in referencias if not os.path.exists(r)]
    if faltan:
        raise ValueError("estas imagenes de referencia no existen: "
                         + ", ".join(str(f) for f in faltan[:5]))

    # con api_key explicita se respeta esa clave (una cuenta efimera con su
    # propio cubo); sin ella, cada intento elige la cuenta con hueco -- que es
    # lo que reparte una tanda entre dos claves sin tocar a quien llama
    cuenta_fija = _Cuenta("clave explicita", api_key) if api_key else None
    ultimo_error = None
    reintento_imagen = False
    r = None

    for intento in range(reintentos + 1):
        cuenta = cuenta_fija or _elegir_cuenta(len(referencias))
        # si otra cadena se ha comido la ventana del limite de ESTA cuenta,
        # aqui se espera: salir a llamar igualmente es gastar otro 429
        _esperar_turno(cuenta)
        # y aunque no haya freno puesto, no se rebasa el ritmo permitido. Se
        # piden tantas fichas como adjuntos lleva, que es lo que cuenta el cubo
        # del otro lado.
        _pedir_ficha(len(referencias), cuenta)
        abiertos, archivos = [], []
        try:
            for ruta in referencias:
                fh = open(ruta, "rb")
                abiertos.append(fh)
                archivos.append(("image[]", (os.path.basename(ruta), fh, "image/png")))
            datos = {"model": MODELO, "prompt": prompt,
                     "size": TAMANOS[tamano], "quality": quality, "n": "1"}
            t0 = time.time()
            r = requests.post(API_URL,
                              headers={"Authorization": f"Bearer {cuenta.clave}"},
                              data=datos, files=archivos, timeout=600)
            segundos = time.time() - t0
        finally:
            for fh in abiertos:
                fh.close()

        # se aprende de TODAS las respuestas, no solo de los errores: el sitio
        # donde la API dice cuanto queda es la respuesta buena
        try:
            _calibrar(r, cuenta)
        except Exception:                          # noqa: BLE001
            pass                                   # calibrar no puede tumbar una tanda

        if r.status_code == 200:
            payload = r.json()
            png = base64.b64decode(payload["data"][0]["b64_json"])
            _gasto["usd"] += PRECIO[quality]
            _gasto["llamadas"] += 1
            # 'usage' es el unico recuento real de tokens de esta llamada y solo
            # existe aqui: se devuelve tal cual para que el medidor no lo estime
            return png, {"segundos": round(segundos, 1), "quality": quality,
                         "refs": len(referencias), "coste": PRECIO[quality],
                         "modelo": MODELO, "tamano": TAMANOS[tamano],
                         "usage": payload.get("usage") or {}}

        ultimo_error = f"HTTP {r.status_code}: {r.text[:200]}"
        # UNA CLAVE QUE NO VALE aparta SU cuenta y se sigue con las demas. Es el
        # gemelo del «sin credito» de abajo, y existe por un caso real: una de
        # tres claves rotada en OpenAI y cada tanda con un tercio de
        # probabilidades de morir en la primera imagen con «Incorrect API
        # key». Solo el 401 de clave; el 401 de cuota lo lee `_sin_saldo`.
        if r.status_code == 401 and not _sin_saldo(r):
            cuenta.clave_rechazada = True
            print(f"[imagen] {cuenta.nombre}: OpenAI rechaza su clave (401); "
                  f"se aparta y se sigue con las demas", flush=True)
            if cuenta_fija is None \
                    and any(not c.sin_saldo and not c.clave_rechazada
                            for c in _cuentas()) \
                    and intento < reintentos:
                continue
            raise RuntimeError(
                f"OpenAI rechaza la clave de {cuenta.nombre} (401 Incorrect API "
                f"key): revisala en Configuracion > Claves. {ultimo_error}")
        # Un 429 puede ser dos cosas MUY distintas: "vas demasiado rapido", que
        # se arregla esperando, o "no te queda saldo", que no se arregla nunca
        # por mucho que se reintente. Distinguirlas evita quemar tres esperas
        # para acabar en el mismo sitio, y sobre todo evita el mensaje que manda
        # a mirar la red cuando lo que hay que hacer es recargar la cuenta.
        if _sin_saldo(r):
            cuenta.sin_saldo = True
            if cuenta_fija is None \
                    and any(not c.sin_saldo for c in _cuentas()) \
                    and intento < reintentos:
                # con otra cuenta viva se sigue con ella: abortar la tanda por
                # una de las dos claves seria tirar la mitad que queda
                print(f"[imagen] {cuenta.nombre} sin credito: se sigue con "
                      f"las demas", flush=True)
                continue
            raise SinSaldo(
                "la cuenta de OpenAI se ha quedado sin credito, asi que no se "
                "pueden generar mas imagenes. Recarga en "
                "https://platform.openai.com/settings/organization/billing y "
                "retoma la generacion: lo ya generado NO se pierde ni se vuelve "
                "a pagar.")
        if r.status_code == 429 and intento < reintentos:
            # el freno es de todas las cadenas DE ESA CUENTA: si lo pone una,
            # las demas tampoco salen a llamar con esa clave hasta que su
            # ventana se renueve; el proximo intento puede elegir otra cuenta
            _frenar(_cuanto_esperar(r), _motivo_limite(r, cuenta), cuenta)
            continue
        if r.status_code in (500, 502, 503, 504) and intento < reintentos:
            time.sleep(min(3 * (intento + 1), 30))
            continue
        # UN 400 DE «IMAGEN INVALIDA» SE REINTENTA UNA VEZ, y solo ese. La causa
        # conocida --leer un adjunto a medio escribir-- esta arreglada de raiz en
        # `normalizar` (escribe a un temporal y sustituye), asi que esto es el
        # cinturon: el reintento vuelve a ABRIR los ficheros, que es exactamente
        # lo que hace falta si alguna vez se cuela otra carrera parecida. Si la
        # imagen esta mal de verdad, el segundo intento falla igual y el error
        # sube con su texto. Mas de uno seria empeñarse contra un fichero malo.
        if (r.status_code == 400 and not reintento_imagen
                and "image" in r.text.lower() and intento < reintentos):
            reintento_imagen = True
            print(f"[imagen] la API rechazo un adjunto ({r.text[:120]}); "
                  f"se vuelve a intentar releyendo los ficheros", flush=True)
            time.sleep(1.0)
            continue
        break

    if r is not None and r.status_code == 429:
        raise RuntimeError(
            "la API de imagen sigue diciendo que vamos demasiado rapido despues "
            f"de {reintentos} esperas. Su limite que salta es el de IMAGENES DE "
            "ENTRADA por minuto, y cada plano manda entre 8 y 14: baja las "
            "cadenas en paralelo (params de assets, 'cadenas') o espera unos "
            f"minutos y retoma -- lo ya generado no se vuelve a pagar. {ultimo_error}")
    raise RuntimeError(ultimo_error)


def _segundos_de(crudo, por_defecto):
    """'30', '1.5s', '2m', '500ms' -> segundos. Las cabeceras varian de formato."""
    texto = str(crudo or "").strip().lower()
    if not texto:
        return por_defecto
    encaje = re.match(r"^([\d.]+)\s*(ms|s|m)?$", texto)
    if not encaje:
        return por_defecto
    try:
        valor = float(encaje.group(1))
    except ValueError:
        return por_defecto
    unidad = encaje.group(2) or "s"
    segundos = valor / 1000 if unidad == "ms" else (
        valor * 60 if unidad == "m" else valor)
    return min(max(segundos, 0.0), ESPERA_MAXIMA_S)


def _cuanto_esperar(respuesta):
    """Segundos que hay que esperar, preguntandoselo a la API y no inventando.

    Por orden: la cabecera 'retry-after', el «try again in 4.2s» que la propia
    API escribe en su mensaje, y si no dice nada, la ventana entera. Esperar
    menos que la ventana con un limite POR MINUTO es garantizar otro 429.
    """
    cabecera = (respuesta.headers or {}).get("retry-after")
    if cabecera:
        segundos = _segundos_de(cabecera, 0.0)
        if segundos:
            return min(max(segundos, 1.0), ESPERA_MAXIMA_S)
    encaje = re.search(r"try again in ([\d.]+)\s*(ms|s|m)\b",
                       respuesta.text or "", re.I)
    if encaje:
        # un margen: la ventana se mide en el servidor y su reloj no es el mio
        segundos = _segundos_de(encaje.group(1) + (encaje.group(2) or "s"), 0.0)
        return min(max(segundos + 1.0, 1.0), ESPERA_MAXIMA_S)
    return ESPERA_LIMITE_S


def _motivo_limite(respuesta, cuenta=None):
    """El trozo del mensaje que dice QUE limite ha saltado, para poder decirlo."""
    encaje = re.search(r"on ([a-z-]+) per (\w+): Limit (\d+)",
                       respuesta.text or "", re.I)
    if encaje:
        # el numero que dice el propio 429 es la mejor fuente despues de las
        # cabeceras: se aprende de el en vez de volver a chocar con lo mismo
        try:
            tope = int(encaje.group(3))
            if 1 <= tope <= 10000:
                objetivo = cuenta or _cuentas()[0]
                objetivo.limite[0] = tope
                objetivo.techo[0] = tope
        except ValueError:
            pass
        return f"{encaje.group(1)} por {encaje.group(2)}, tope {encaje.group(3)}"
    return "429"


class SinSaldo(RuntimeError):
    """No queda credito en la cuenta. Reintentar no arregla esto."""


def _sin_saldo(respuesta):
    """Si el 429 es por falta de credito y no por ir demasiado rapido.

    Se mira el CODIGO del error y no el texto suelto. Buscando 'billing' en el
    cuerpo, un 429 de velocidad que mencionara la pagina de facturacion se leia
    como «no queda credito» y abortaba la tanda entera en vez de esperar los
    segundos que hacian falta. El codigo lo pone la API a proposito para poder
    distinguirlas: 'insufficient_quota' no se arregla esperando, 'rate_limit_
    exceeded' se arregla siempre.
    """
    if respuesta.status_code not in (401, 402, 429):
        return False
    codigo = tipo = ""
    try:
        error = (respuesta.json() or {}).get("error") or {}
        codigo = str(error.get("code") or "").lower()
        tipo = str(error.get("type") or "").lower()
    except ValueError:
        pass
    if "rate_limit" in codigo or "rate_limit" in tipo:
        return False
    if "insufficient_quota" in (codigo, tipo):
        return True
    texto = (respuesta.text or "").lower()
    return ("insufficient_quota" in texto
            or "no credits remaining" in texto
            or "exceeded your current quota" in texto)


def generar_lote(trabajos, *, concurrencia=4):
    """Ejecuta trabajos en paralelo. Cada trabajo es un dict con 'prompt',
    'referencias', 'destino' y opcionalmente 'quality'.

    Devuelve la lista de resultados en el mismo orden de entrada. Un fallo no
    tumba el lote: se registra y los demas siguen.
    """
    def uno(trabajo):
        try:
            # sin api_key a proposito: asi cada llamada elige la cuenta con
            # hueco y el lote se reparte entre las claves que haya
            png, meta = generar(trabajo["prompt"], trabajo["referencias"],
                                quality=trabajo.get("quality", "low"),
                                tamano=trabajo.get("tamano", "apaisado"))
        except Exception as exc:
            return {"id": trabajo.get("id"), "error": str(exc)}
        os.makedirs(os.path.dirname(trabajo["destino"]), exist_ok=True)
        with open(trabajo["destino"], "wb") as fh:
            fh.write(png)
        return {"id": trabajo.get("id"), "destino": trabajo["destino"], **meta}

    with ThreadPoolExecutor(max_workers=concurrencia) as pool:
        return list(pool.map(uno, trabajos))


def gasto():
    return dict(_gasto, usd=round(_gasto["usd"], 4))
