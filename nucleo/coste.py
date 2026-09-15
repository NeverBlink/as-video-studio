"""
Medidor de coste del Estudio de Video.

El medidor NO estima: cada motor reporta lo que ha consumido en el momento de
consumirlo y aqui solo se suma. Un medidor que calcula por su cuenta se desvia
en cuanto cambia una tarifa o un modelo, y entonces deja de servir para decidir.

Tres proveedores y tres unidades distintas:

    openai      imagenes. La respuesta de /v1/images/edits trae 'usage' con el
                recuento de tokens: se guarda tal cual. Los dolares salen de la
                tabla de tarifas (tarifas.json), no de una constante repartida
                por el codigo.
    tts         caracteres realmente sintetizados, los que el motor de voz envio
                (no los del guion, que incluye bloques que quiza no se locutaron).
                La tarifa por caracter depende del plan contratado y NO se sabe:
                mientras siga vacia en tarifas.json el evento se anota con los
                caracteres y el importe marcado como 'sin tarifa'.
    claude_cli  SOLO tokens. Va contra la suscripcion, no contra un contador con
                precio por llamada, asi que no lleva dolares y no suma al total.

Uso:

    from nucleo.coste import Medidor, contexto, instrumentar

    instrumentar()                       # engancha motores y pasos una vez
    with contexto(proyecto, "assets"):   # todo lo que se gaste aqui dentro
        ...                              # queda anotado en ese proyecto y paso

    Medidor(proyecto).total()            # {"total_usd": ..., "proveedores": ...}

Persistencia: eventos append-only en <proyecto>/coste.jsonl y, con el proyecto
anotado, en C:\\IA\\estudio\\coste_global.jsonl. Igual que la bitacora, se anota
al ocurrir y nunca se reescribe: el historico sigue siendo valido aunque las
tarifas cambien despues.
"""
import contextlib
import functools
import json
import os
import re
import threading

try:
    from .proyecto import (Proyecto, ahora, escribir_json, leer_json,
                           leer_jsonl, lock_de)
    from .estado import PASOS, PASOS_POR_ID
except ImportError:  # ejecutado con la carpeta nucleo directamente en sys.path
    from proyecto import (Proyecto, ahora, escribir_json, leer_json,
                          leer_jsonl, lock_de)
    from estado import PASOS, PASOS_POR_ID

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# la tabla de tarifas se puede desviar con ESTUDIO_TARIFAS por el mismo motivo
# que el agregado global: una prueba que escribe una tarifa de mentira y muere
# antes de restaurarla deja el medidor sumando dolares inventados para siempre,
# que es justo lo que el hueco de 'sin tarifa' existe para evitar
RUTA_TARIFAS = (os.environ.get("ESTUDIO_TARIFAS")
                or os.path.join(RAIZ_ESTUDIO, "tarifas.json"))
# el agregado global se puede desviar con ESTUDIO_COSTE_GLOBAL: las pruebas
# gastan dinero de mentira y ese fichero es el historico real del gasto
RUTA_GLOBAL = (os.environ.get("ESTUDIO_COSTE_GLOBAL")
               or os.path.join(RAIZ_ESTUDIO, "coste_global.jsonl"))
NOMBRE_COSTE = "coste.jsonl"

PROVEEDORES = ("openai", "tts", "claude_cli")
SIN_DOLARES = ("claude_cli",)            # se miden en tokens y no suman al total
ETIQUETAS = {"openai": "OpenAI", "tts": "TTS", "claude_cli": "Claude"}

AVISO_PRESUPUESTO = 0.8                  # fraccion a partir de la cual se avisa

_ESCRITURA = threading.Lock()
_TARIFAS = {"datos": None, "sello": None}


# ------------------------------------------------------------------- tarifas

def _sello(ruta):
    try:
        info = os.stat(ruta)
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


def tarifas(refrescar=False):
    """Tabla de tarifas de tarifas.json, releida cuando el fichero cambia.

    Se cachea porque se consulta en cada evento, y se comprueba el sello del
    fichero porque el precio por caracter de Cartesia se rellena a mano: sin
    esto habria que reiniciar el servicio para que el numero entrase en vigor.
    """
    marca = _sello(RUTA_TARIFAS)
    if refrescar or _TARIFAS["datos"] is None or _TARIFAS["sello"] != marca:
        datos = leer_json(RUTA_TARIFAS)
        _TARIFAS["datos"] = datos if isinstance(datos, dict) else {}
        _TARIFAS["sello"] = marca
    return _TARIFAS["datos"]


def guardar_tarifas(cambios):
    """Escribe tarifas.json mezclando cambios; devuelve la tabla resultante.

    Solo toca lo que se le pasa: el resto de la tabla (y los comentarios que
    lleva dentro) se conserva tal cual.
    """
    if not isinstance(cambios, dict):
        raise TypeError("las tarifas se actualizan con un dict")
    actual = json.loads(json.dumps(tarifas(refrescar=True)))
    for bloque, valores in cambios.items():
        if isinstance(valores, dict) and isinstance(actual.get(bloque), dict):
            actual[bloque].update(valores)
        else:
            actual[bloque] = valores
    actual["actualizado"] = ahora()
    escribir_json(RUTA_TARIFAS, actual)
    _TARIFAS["datos"] = actual
    _TARIFAS["sello"] = _sello(RUTA_TARIFAS)
    return actual


def _numero(valor):
    """float del valor, o None si no es un numero utilizable como tarifa."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 0 else None


def tarifa_imagen(tamano, calidad):
    """USD por imagen de ese tamano y calidad, o None si no esta tarifada."""
    tabla = (tarifas().get("openai") or {}).get("usd_por_imagen") or {}
    fila = tabla.get(str(tamano))
    if not isinstance(fila, dict):
        return None
    return _numero(fila.get(str(calidad)))


def tarifa_tokens():
    """USD por token de gpt-image: entrada de texto, entrada de imagen y salida."""
    tabla = (tarifas().get("openai") or {}).get("usd_por_token") or {}
    return {clave: _numero(tabla.get(clave))
            for clave in ("entrada_texto", "entrada_imagen", "salida")}


def tarifa_caracter():
    """USD por caracter sintetizado, o None mientras no se conozca el plan."""
    return _numero((tarifas().get("tts") or {}).get("usd_por_caracter"))


def coste_openai(usage, tamano, calidad, imagenes=1):
    """Importe de una llamada de imagen, y de donde ha salido.

    El precio por imagen de la tabla cubre SOLO la imagen devuelta, que en este
    pipeline es la parte pequena: la API cobra ademas los tokens de ENTRADA, y
    aqui la entrada son las referencias de estilo, de reparto y las dos de
    continuidad que se le adjuntan a cada plano. En una tanda real fueron
    1.170.532 tokens de entrada sin tarifar contra 1,04 $ de imagenes, o sea
    que el medidor ensenaba la decima parte del gasto.

    Manda el recuento de tokens; el precio por imagen queda de respaldo para
    cuando la API no devuelve 'usage'. Nunca se suman los dos: la imagen
    devuelta ES los tokens de salida, y sumarlos la cobraria dos veces.
    """
    usage = usage if isinstance(usage, dict) else {}
    precios = tarifa_tokens()
    entrada = int(usage.get("input_tokens") or 0)
    salida = int(usage.get("output_tokens") or 0)
    if not (entrada or salida) or precios["salida"] is None:
        precio = tarifa_imagen(tamano, calidad)
        return (None if precio is None else precio * int(imagenes),
                {"via": "imagen", "motivo": "la API no ha devuelto tokens"
                 if not (entrada or salida) else "faltan tarifas por token"})

    # La API desglosa la entrada cuando puede. Lo que no desglose se tarifa como
    # IMAGEN, que es la mas cara de las dos: pasarse por arriba es preferible a
    # repetir el fallo de ensenar un gasto que no es.
    detalles = usage.get("input_tokens_details")
    detalles = detalles if isinstance(detalles, dict) else {}
    texto = int(detalles.get("text_tokens") or 0)
    imagen_tok = int(detalles.get("image_tokens") or 0)
    if texto + imagen_tok > entrada:                  # desglose incoherente
        texto, imagen_tok = 0, 0
    sin_desglosar = max(0, entrada - texto - imagen_tok)
    imagen_tok += sin_desglosar

    tarifa_texto = precios["entrada_texto"] if precios["entrada_texto"] is not None \
        else precios["entrada_imagen"]
    tarifa_img = precios["entrada_imagen"] if precios["entrada_imagen"] is not None \
        else tarifa_texto
    if tarifa_img is None:
        precio = tarifa_imagen(tamano, calidad)
        return (None if precio is None else precio * int(imagenes),
                {"via": "imagen", "motivo": "faltan tarifas de entrada"})

    usd = (texto * tarifa_texto + imagen_tok * tarifa_img
           + salida * precios["salida"])
    return round(usd, 6), {
        "via": "tokens",
        "entrada_texto": texto,
        "entrada_imagen": imagen_tok,
        "salida": salida,
        "sin_desglosar": sin_desglosar,
    }


# -------------------------------------------------------------------- eventos

def _tokens(datos):
    datos = datos if isinstance(datos, dict) else {}
    return {"entrada": int(datos.get("entrada") or 0),
            "salida": int(datos.get("salida") or 0),
            "cache": int(datos.get("cache") or 0)}


def _cantidad(datos):
    datos = datos if isinstance(datos, dict) else {}
    return {"imagenes": int(datos.get("imagenes") or 0),
            "caracteres": int(datos.get("caracteres") or 0)}


def _linea(ruta, registro):
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")


class Medidor:
    """Eventos de consumo de un proyecto: se anotan, se leen y se suman."""

    def __init__(self, proyecto):
        if isinstance(proyecto, str):
            proyecto = Proyecto(proyecto)
        self.proyecto = proyecto
        self.ruta = proyecto.ruta(NOMBRE_COSTE)
        self.ruta_global = RUTA_GLOBAL

    def __repr__(self):
        return f"<Medidor {self.proyecto.id}>"

    # ------------------------------------------------------------- escritura

    def anotar(self, proveedor, paso, operacion, unidad=None, tokens=None,
               cantidad=None, usd=None, usd_estimado=False, detalle=None):
        """Anota lo consumido por una llamada. Devuelve el registro escrito.

        usd=None significa 'no hay importe': en claude_cli porque no lo lleva
        (va contra la suscripcion) y en el resto porque falta la tarifa. Los dos
        casos se distinguen con 'sin_tarifa', y ninguno inventa un numero.
        """
        proveedor = str(proveedor)
        if proveedor not in PROVEEDORES:
            raise ValueError(f"proveedor desconocido: {proveedor}. "
                             f"Los proveedores son: {', '.join(PROVEEDORES)}")
        importe = None if proveedor in SIN_DOLARES else _numero(usd)
        registro = {
            "id": None,
            "proveedor": proveedor,
            "paso": str(paso) if paso else None,
            "unidad": str(unidad) if unidad else None,
            "operacion": str(operacion or ""),
            "tokens": _tokens(tokens),
            "cantidad": _cantidad(cantidad),
            "usd": round(importe, 6) if importe is not None else None,
            "usd_estimado": bool(usd_estimado) and importe is not None,
            "momento": ahora(),
        }
        if importe is None and proveedor not in SIN_DOLARES:
            registro["sin_tarifa"] = True
        if isinstance(detalle, dict) and detalle:
            registro["detalle"] = detalle
        with _ESCRITURA, lock_de(self.ruta):
            registro["id"] = self._siguiente_id()
            _linea(self.ruta, registro)
            global_registro = dict(registro)
            global_registro["proyecto"] = self.proyecto.id
            global_registro["raiz"] = self.proyecto.raiz
            _linea(self.ruta_global, global_registro)
        return registro

    def _siguiente_id(self):
        """ev_00001, ev_00002... derivado del fichero, que es la unica verdad.

        Se lee el maximo en vez de contar lineas: si una linea quedo a medias no
        se puede reutilizar un identificador ya emitido.
        """
        mayor = 0
        if os.path.exists(self.ruta):
            with open(self.ruta, "r", encoding="utf-8") as fh:
                for cruda in fh:
                    encaje = re.search(r'"id"\s*:\s*"ev_(\d+)"', cruda)
                    if encaje:
                        mayor = max(mayor, int(encaje.group(1)))
        return f"ev_{mayor + 1:05d}"

    # -------------------------------------------------------------- lectura

    def eventos(self, proveedor=None, paso=None, unidad=None, limite=None):
        """Eventos del proyecto en orden cronologico, filtrables."""
        registros = leer_jsonl(self.ruta)
        if proveedor:
            registros = [r for r in registros if r.get("proveedor") == proveedor]
        if paso:
            registros = [r for r in registros if r.get("paso") == paso]
        if unidad:
            registros = [r for r in registros if r.get("unidad") == unidad]
        if limite and int(limite) > 0:
            registros = registros[-int(limite):]
        return registros

    def total(self):
        """Total del video desglosado por proveedor, con la linea de cabecera."""
        resumen = agregar(self.eventos())
        resumen["proyecto"] = self.proyecto.id
        resumen["nombre"] = self.proyecto.config.get("nombre", self.proyecto.id)
        resumen.update(self._presupuesto(resumen["total_usd"]))
        return resumen

    def por_paso(self):
        """Desglose por paso del pipeline, en el orden en que corren."""
        registros = self.eventos()
        orden = [p["id"] for p in PASOS]
        for registro in registros:
            paso = registro.get("paso")
            if paso and paso not in orden:
                orden.append(paso)
        fichas = []
        for paso in orden:
            resumen = agregar([r for r in registros if r.get("paso") == paso])
            resumen["paso"] = paso
            resumen["nombre"] = PASOS_POR_ID.get(paso, {}).get("nombre", paso)
            fichas.append(resumen)
        sueltos = [r for r in registros if not r.get("paso")]
        if sueltos:
            resumen = agregar(sueltos)
            resumen["paso"] = None
            resumen["nombre"] = "sin paso"
            fichas.append(resumen)
        general = agregar(registros)
        general["proyecto"] = self.proyecto.id
        general["pasos"] = fichas
        general.update(self._presupuesto(general["total_usd"]))
        return general

    def _presupuesto(self, gastado):
        """Fraccion consumida del presupuesto del video, si lo hay."""
        limite = _numero(self.proyecto.config.get("presupuesto_usd"))
        if not limite:
            return {"presupuesto_usd": None, "fraccion_presupuesto": None,
                    "aviso_presupuesto": False}
        fraccion = gastado / limite
        return {"presupuesto_usd": round(limite, 4),
                "fraccion_presupuesto": round(fraccion, 4),
                "aviso_presupuesto": fraccion >= AVISO_PRESUPUESTO}

    def fijar_presupuesto(self, usd):
        """Fija (o quita, con None) el presupuesto en dolares del video."""
        limite = _numero(usd)
        if usd is not None and limite is None:
            raise ValueError(f"presupuesto invalido: {usd!r}")
        self.proyecto.config["presupuesto_usd"] = limite
        self.proyecto.guardar_config()
        return limite


# ------------------------------------------------------------------ agregado

def _vacio(proveedor):
    return {
        "proveedor": proveedor,
        "etiqueta": ETIQUETAS.get(proveedor, proveedor),
        "eventos": 0,
        "usd": None if proveedor in SIN_DOLARES else 0.0,
        "usd_estimado": False,
        "sin_tarifa": False,
        "suma_al_total": proveedor not in SIN_DOLARES,
        "tokens": {"entrada": 0, "salida": 0, "cache": 0, "total": 0},
        "cantidad": {"imagenes": 0, "caracteres": 0},
    }


def _acumular(destino, registro):
    destino["eventos"] += 1
    tokens = _tokens(registro.get("tokens"))
    for clave, valor in tokens.items():
        destino["tokens"][clave] += valor
    destino["tokens"]["total"] += sum(tokens.values())
    for clave, valor in _cantidad(registro.get("cantidad")).items():
        destino["cantidad"][clave] += valor
    importe = _numero(registro.get("usd"))
    if importe is not None and destino["usd"] is not None:
        destino["usd"] = round(destino["usd"] + importe, 6)
    if registro.get("usd_estimado"):
        destino["usd_estimado"] = True
    if registro.get("sin_tarifa"):
        destino["sin_tarifa"] = True


def corto(numero):
    """312000 -> '312k', 41200 -> '41.2k'. Para la linea de cabecera."""
    numero = int(numero or 0)
    if numero < 1000:
        return str(numero)
    if numero < 100000:
        return f"{numero / 1000:.1f}k"
    if numero < 1000000:
        return f"{numero / 1000:.0f}k"
    return f"{numero / 1000000:.1f}M"


def cabecera(proveedores, total_usd):
    """La linea que va junto al selector de proyecto, ya formateada.

    Claude sale sin importe y no entra en el TOTAL: mostrar un dolar inventado
    ahi seria peor que no mostrar nada.
    """
    def importe(ficha):
        if ficha["sin_tarifa"] and not ficha["usd"]:
            return "sin tarifa"
        return f"${ficha['usd'] or 0:.2f}"

    abierto = proveedores.get("openai") or _vacio("openai")
    voz = proveedores.get("tts") or _vacio("tts")
    cli = proveedores.get("claude_cli") or _vacio("claude_cli")
    return "     ".join([
        f"OpenAI  {importe(abierto)} · {corto(abierto['tokens']['total'])} tok",
        f"TTS  {importe(voz)} · {corto(voz['cantidad']['caracteres'])} car",
        f"Claude  {corto(cli['tokens']['total'])} tok",
        f"TOTAL  ${total_usd:.2f}",
    ])


def agregar(registros):
    """Suma una lista de eventos: por proveedor, total y linea de cabecera."""
    proveedores = {nombre: _vacio(nombre) for nombre in PROVEEDORES}
    for registro in registros:
        nombre = registro.get("proveedor")
        if nombre not in proveedores:
            proveedores[nombre] = _vacio(nombre)
        _acumular(proveedores[nombre], registro)
    total = round(sum(ficha["usd"] or 0.0 for ficha in proveedores.values()
                      if ficha["suma_al_total"]), 6)
    momentos = [r.get("momento") for r in registros if r.get("momento")]
    return {
        "eventos": len(registros),
        "total_usd": total,
        "moneda": "USD",
        "proveedores": proveedores,
        "tarifa_caracter": tarifa_caracter(),
        "cabecera": cabecera(proveedores, total),
        "ultimo": max(momentos) if momentos else "",
    }


def resumen_global(limite=None):
    """Agregado de todos los videos, con el desglose de cada uno."""
    registros = leer_jsonl(RUTA_GLOBAL)
    if limite and int(limite) > 0:
        registros = registros[-int(limite):]
    proyectos = []
    for pid in sorted({str(r.get("proyecto") or "") for r in registros}):
        suyos = [r for r in registros if str(r.get("proyecto") or "") == pid]
        ficha = agregar(suyos)
        ficha["proyecto"] = pid or None
        raices = [r.get("raiz") for r in suyos if r.get("raiz")]
        ficha["raiz"] = raices[-1] if raices else None
        proyectos.append(ficha)
    proyectos.sort(key=lambda f: f["total_usd"], reverse=True)
    general = agregar(registros)
    general["proyectos"] = proyectos
    general["ruta"] = RUTA_GLOBAL
    return general


# ---------------------------------------------------------- contexto de medida

class _Contexto:
    """A que proyecto, paso y unidad se apunta lo que se gaste ahora mismo."""

    def __init__(self, proyecto, paso, unidad=None):
        self.medidor = proyecto if isinstance(proyecto, Medidor) else Medidor(proyecto)
        self.paso = str(paso) if paso else None
        self.unidad = str(unidad) if unidad else None

    def __repr__(self):
        return f"<contexto {self.medidor.proyecto.id}/{self.paso}/{self.unidad}>"


_LOCAL = threading.local()
_ACTIVOS = {}
_ACTIVOS_LOCK = threading.RLock()
_SIN_CONTEXTO = {"eventos": 0, "ultimo": ""}


def _pila():
    pila = getattr(_LOCAL, "pila", None)
    if pila is None:
        pila = []
        _LOCAL.pila = pila
    return pila


@contextlib.contextmanager
def contexto(proyecto, paso, unidad=None):
    """Todo lo que se consuma aqui dentro se anota en ese proyecto y paso."""
    actual = _Contexto(proyecto, paso, unidad)
    pila = _pila()
    pila.append(actual)
    ident = threading.get_ident()
    with _ACTIVOS_LOCK:
        _ACTIVOS[ident] = actual
    try:
        yield actual
    finally:
        pila.pop()
        with _ACTIVOS_LOCK:
            if pila:
                _ACTIVOS[ident] = pila[-1]
            else:
                _ACTIVOS.pop(ident, None)


@contextlib.contextmanager
def unidad_activa(unidad):
    """Afina la unidad del contexto en vigor (escena:S03, asset:puerto)."""
    pila = _pila()
    if pila:
        actual = pila[-1]
        previa = actual.unidad
        actual.unidad = str(unidad) if unidad else None
        try:
            yield actual
        finally:
            actual.unidad = previa
        return
    heredado = contexto_actual()
    if heredado is None:
        yield None
        return
    # el contexto heredado es de OTRO hilo: se apila una copia propia en vez de
    # cambiarle la unidad, que se le quedaria puesta al hilo dueno
    propio = _Contexto(heredado.medidor, heredado.paso, unidad)
    pila.append(propio)
    try:
        yield propio
    finally:
        pila.pop()


def contexto_actual():
    """Contexto de este hilo o, si no lo hay, el unico activo del proceso.

    El respaldo importa: el motor de imagen paraleliza sus llamadas en un pool
    de hilos, y esos hilos hijos no heredan el contexto del que los lanzo. Si
    hay un solo trabajo midiendo, atribuirle el gasto es exacto; si hay dos, no
    hay forma de saber de cual es y el evento se cuenta como huerfano en vez de
    cargarselo al proyecto equivocado.
    """
    pila = getattr(_LOCAL, "pila", None)
    if pila:
        return pila[-1]
    with _ACTIVOS_LOCK:
        unicos = {id(c): c for c in _ACTIVOS.values()}
        if len(unicos) == 1:
            return next(iter(unicos.values()))
    return None


def _anotar(proveedor, operacion, unidad=None, **campos):
    actual = contexto_actual()
    if actual is None:
        with _ACTIVOS_LOCK:
            _SIN_CONTEXTO["eventos"] += 1
            _SIN_CONTEXTO["ultimo"] = f"{proveedor}:{operacion} @ {ahora()}"
        return None
    return actual.medidor.anotar(proveedor, actual.paso, operacion,
                                 unidad=unidad or actual.unidad, **campos)


# ------------------------------------------------------------- reportadores

def reportar_openai(usage, calidad, tamano, imagenes=1, operacion="imagen",
                    unidad=None, detalle=None):
    """Anota una llamada de imagen con el 'usage' que devolvio la API."""
    usage = usage if isinstance(usage, dict) else {}
    detalles = usage.get("input_tokens_details")
    cache = int((detalles or {}).get("cached_tokens") or 0) \
        if isinstance(detalles, dict) else 0
    importe, procedencia = coste_openai(usage, tamano, calidad, imagenes)
    ficha = {"calidad": calidad, "tamano": tamano}
    # De donde sale el importe, guardado con el evento: sin esto no habria forma
    # de saber despues si un gasto viejo se tarifo por tokens o por imagen.
    ficha["coste"] = procedencia
    ficha.update(detalle or {})
    return _anotar("openai", operacion, unidad=unidad,
                   tokens={"entrada": usage.get("input_tokens"),
                           "salida": usage.get("output_tokens"),
                           "cache": cache},
                   cantidad={"imagenes": imagenes},
                   usd=importe,
                   # el importe sale de la tabla de tarifas, no de la factura:
                   # la cabecera lo pinta con un matiz distinto por eso mismo
                   usd_estimado=True, detalle=ficha)


def reportar_tts(caracteres, operacion="sintesis", unidad=None, tokens=None,
                 detalle=None):
    """Anota una sintesis con los caracteres que el motor de voz envio de verdad."""
    caracteres = int(caracteres or 0)
    precio = tarifa_caracter()
    return _anotar("tts", operacion, unidad=unidad,
                   tokens=tokens, cantidad={"caracteres": caracteres},
                   usd=None if precio is None else precio * caracteres,
                   usd_estimado=True, detalle=detalle)


def reportar_claude(sobre, operacion="cli", unidad=None, detalle=None):
    """Anota una llamada al CLI de Claude leyendo su bloque 'usage'.

    Entrada, salida y cache van por separado porque la cache cambia mucho el
    recuento y mezclarlas oculta de donde viene el gasto.
    """
    sobre = sobre if isinstance(sobre, dict) else {}
    usage = sobre.get("usage") if isinstance(sobre.get("usage"), dict) else {}
    cache = (int(usage.get("cache_creation_input_tokens") or 0)
             + int(usage.get("cache_read_input_tokens") or 0))
    ficha = {}
    if sobre.get("model"):
        ficha["modelo"] = sobre["model"]
    if sobre.get("duration_ms") is not None:
        ficha["segundos"] = round(float(sobre["duration_ms"]) / 1000.0, 1)
    # El sobre del CLI no dice con que esfuerzo se le hablo, y el esfuerzo es la
    # variable que mas mueve el tiempo: lo estampa pasos/cli_claude al volver.
    ajuste = sobre.get("_ajuste")
    if isinstance(ajuste, dict):
        ficha.setdefault("modelo", ajuste.get("modelo"))
        ficha["esfuerzo"] = ajuste.get("esfuerzo")
        if ajuste.get("segundos") is not None:
            ficha["segundos"] = ajuste["segundos"]
    # el CLI informa de su coste, pero no se anota como dolares del video: no es
    # un cargo por llamada sino consumo de una suscripcion ya pagada
    if sobre.get("total_cost_usd") is not None:
        ficha["coste_suscripcion_usd"] = round(float(sobre["total_cost_usd"]), 4)
    ficha.update(detalle or {})
    return _anotar("claude_cli", operacion, unidad=unidad,
                   tokens={"entrada": usage.get("input_tokens"),
                           "salida": usage.get("output_tokens"),
                           "cache": cache},
                   detalle=ficha)


# ----------------------------------------------------------- instrumentacion

_INFORME = {"enganchado": [], "ausente": [], "fecha": ""}
_MARCA = "_coste_enganchado"


def _envolver(contenedor, nombre, fabrica, informe, etiqueta=None):
    """Sustituye contenedor.nombre por su version medida, una sola vez."""
    etiqueta = etiqueta or f"{getattr(contenedor, '__name__', contenedor)}.{nombre}"
    original = getattr(contenedor, nombre, None)
    if original is None or not callable(original):
        if etiqueta not in informe["ausente"]:
            informe["ausente"].append(etiqueta)
        return False
    if getattr(original, _MARCA, False):
        return True
    envuelta = fabrica(original)
    functools.update_wrapper(envuelta, original)
    setattr(envuelta, _MARCA, True)
    setattr(contenedor, nombre, envuelta)
    if etiqueta not in informe["enganchado"]:
        informe["enganchado"].append(etiqueta)
    return True


def _medir_paso(paso_id):
    def fabrica(original):
        def medido(proyecto, params, avisar=None, *args, **kwargs):
            with contexto(proyecto, paso_id):
                return original(proyecto, params, avisar, *args, **kwargs)
        return medido
    return fabrica


def _medir_previsualizacion(original):
    def medido(proyecto, params, *args, **kwargs):
        with contexto(proyecto, "voz"):
            return original(proyecto, params, *args, **kwargs)
    return medido


def _medir_toma_real(original):
    def medido(texto, cfg, *args, **kwargs):
        resultado = original(texto, cfg, *args, **kwargs)
        # se anota DESPUES y con el texto que se envio: si la llamada revienta
        # no hay recuento fiable y preferimos un hueco a un numero inventado
        cfg = cfg if isinstance(cfg, dict) else {}
        reportar_tts(len(texto or ""), operacion="toma",
                     detalle={"modelo": cfg.get("modelo"),
                              "voz_id": cfg.get("voz_id"),
                              "idioma": cfg.get("idioma")})
        return resultado
    return medido


def _medir_toma_por_contexto(original):
    """La toma en varias entradas de un mismo contexto: el camino NORMAL.

    `_toma_real` estaba envuelto desde el principio y este no, y este es el que
    se usa: `sintetizar_bloques` manda por aqui cualquier guion con mas de una
    seccion --o sea, todos-- y `regrabar_seccion` tambien. Resultado medido en
    un video real: veinte minutos de locucion grabados y CERO caracteres en el
    medidor. Y no chirriaba, porque un hueco en el importe del TTS es
    exactamente lo que se pinta cuando falta la tarifa por caracter.

    Se cuentan los caracteres que se ENVIARON, sumando las entradas del
    contexto, y se anota DESPUES: si la llamada revienta no hay recuento
    fiable, y un hueco es mejor que un numero inventado.
    """
    def medido(trozos, cfg, *args, **kwargs):
        resultado = original(trozos, cfg, *args, **kwargs)
        cfg = cfg if isinstance(cfg, dict) else {}
        piezas = list(trozos or [])
        reportar_tts(sum(len(str(t or "")) for t in piezas), operacion="toma",
                     detalle={"modelo": cfg.get("modelo"),
                              "voz_id": cfg.get("voz_id"),
                              "idioma": cfg.get("idioma"),
                              "secciones": len(piezas)})
        return resultado
    return medido


def _medir_claude(operacion):
    def fabrica(original):
        def medido(*args, **kwargs):
            texto, sobre = original(*args, **kwargs)
            reportar_claude(sobre, operacion=operacion)
            return texto, sobre
        return medido
    return fabrica


def _medir_imagen(original):
    def medido(prompt, referencias, *args, **kwargs):
        png, meta = original(prompt, referencias, *args, **kwargs)
        meta = meta if isinstance(meta, dict) else {}
        calidad = kwargs.get("quality") or meta.get("quality") or "low"
        tamano = meta.get("tamano") or kwargs.get("tamano") or "apaisado"
        registro = reportar_openai(meta.get("usage"), calidad, tamano,
                                   detalle={"modelo": meta.get("modelo"),
                                            "refs": meta.get("refs"),
                                            "segundos": meta.get("segundos")})
        # Y EL IMPORTE DE VERDAD SE DEVUELVE, no solo se anota.
        #
        # El motor trae en `meta["coste"]` el precio de su TABLA POR IMAGEN
        # (0,006 $ en calidad baja), que es la parte pequena: la API cobra
        # ademas los tokens de entrada, y aqui la entrada son las referencias de
        # estilo, de reparto y las dos de continuidad que lleva cada plano. Ese
        # numero es el que p6 sumaba para su resumen y el que acababa en la
        # bitacora, asi que la pantalla decia «45 imagenes, 0,264 $» de una
        # tanda que costo 1,3776 $ -- un factor de cinco.
        #
        # `coste_openai` ya sabia calcularlo y su propio docstring ya describia
        # este fallo; lo unico que faltaba era que alguien se quedara con el
        # resultado. Se pisa `meta["coste"]` aqui y no en p6 porque este es el
        # sitio por el que pasan TODAS las imagenes, se pidan desde donde se
        # pidan.
        if isinstance(registro, dict) and registro.get("usd") is not None:
            meta["coste"] = float(registro["usd"])
            meta["coste_estimado"] = bool(registro.get("usd_estimado"))
        return png, meta
    return medido


def _medir_produccion_imagen(original):
    """Da nombre de unidad a lo que gaste la produccion de una imagen.

    El motor de imagen no sabe para que escena trabaja; quien lo sabe es el paso
    de assets, y lo unico que lo delata sin tocar su codigo es la carpeta de
    destino: escenas/ es un plano y el resto son assets del reparto.
    """
    def medido(nombre, prompt, referencias, destino, *args, **kwargs):
        carpeta = os.path.basename(os.path.dirname(str(destino)))
        prefijo = "escena" if carpeta == "escenas" else "asset"
        with unidad_activa(f"{prefijo}:{nombre}"):
            return original(nombre, prompt, referencias, destino, *args, **kwargs)
    return medido


def instrumentar(pasos=None):
    """Engancha el medidor a las llamadas reales. Idempotente.

    Devuelve el informe de que se engancho y que no. El informe se publica en la
    API a proposito: si alguien renombra una funcion instrumentada, el medidor
    dejaria de contar en silencio, y un hueco que se ve es lo unico que evita
    seguir mirando un total que ya no es el total.
    """
    informe = {"enganchado": list(_INFORME["enganchado"]),
               "ausente": [], "fecha": ahora()}
    if pasos is None:
        # importacion tardia: el nucleo tiene que seguir siendo importable sin
        # los pasos, que arrastran cv2, PIL y los motores
        try:
            import pasos as modulo_pasos
        except Exception as fallo:  # noqa: BLE001
            informe["ausente"].append(f"pasos ({type(fallo).__name__}: {fallo})")
            _INFORME.update(informe)
            return dict(informe)
        pasos = modulo_pasos

    for paso_id, modulo in (getattr(pasos, "MODULOS", {}) or {}).items():
        _envolver(modulo, "ejecutar", _medir_paso(paso_id), informe,
                  etiqueta=f"{paso_id}.ejecutar")

    voz = getattr(pasos, "p4_voz", None)
    if voz is not None:
        _envolver(voz, "_toma_real", _medir_toma_real, informe, "voz.toma_real")
        _envolver(voz, "_toma_por_contexto", _medir_toma_por_contexto, informe,
                  "voz.toma_por_contexto")
        _envolver(voz, "previsualizar", _medir_previsualizacion, informe,
                  "voz.previsualizar")
    guion = getattr(pasos, "p3_guion", None)
    if guion is not None:
        _envolver(guion, "_llamar_claude", _medir_claude("guion"), informe,
                  "guion.claude")
    revision = getattr(pasos, "p5_revision_audio", None)
    if revision is not None:
        _envolver(revision, "_llamar_claude", _medir_claude("revision_audio"),
                  informe, "revision_audio.claude")
    estilo = getattr(pasos, "estilo", None)
    if estilo is not None:
        _envolver(estilo, "_llamar_claude", _medir_claude("guia_estilo"),
                  informe, "guia_estilo.claude")
    tono = getattr(pasos, "tono", None)
    if tono is not None:
        _envolver(tono, "_llamar_claude", _medir_claude("tono"),
                  informe, "tono.claude")
    catalogo = getattr(pasos, "catalogo_visual", None)
    if catalogo is not None:
        _envolver(catalogo, "_llamar_claude", _medir_claude("catalogo_visual"),
                  informe, "catalogo_visual.claude")
    conservar = getattr(pasos, "conservar", None)
    if conservar is not None:
        _envolver(conservar, "_llamar_claude", _medir_claude("conservacion"),
                  informe, "conservacion.claude")
    assets = getattr(pasos, "p6_assets", None)
    if assets is not None:
        _envolver(assets, "_producir_imagen", _medir_produccion_imagen, informe,
                  "assets.producir_imagen")

    for modulo in modulos_de_imagen(pasos):
        _envolver(modulo, "generar", _medir_imagen, informe, "imagen_openai.generar")

    # Y se queda apuntado para volver a engancharse si medios RECARGA un motor.
    # Sin esto, recargar imagen.py deja un objeto modulo nuevo cuya `generar` no
    # esta envuelta, y el gasto de imagen deja de contarse sin decir nada: el
    # fallo que esta funcion existe para no tener nunca.
    _apuntarse_a_las_recargas(pasos, informe)

    _INFORME.update(informe)
    return dict(informe)


def _apuntarse_a_las_recargas(pasos, informe):
    """Registra el reenganche en cada copia de `medios` que haya cargada."""
    import sys

    for medios in [getattr(pasos, "medios", None) if pasos else None,
                   sys.modules.get("medios"), sys.modules.get("pasos.medios")]:
        ganchos = getattr(medios, "AL_CARGAR", None)
        if isinstance(ganchos, list) and _reenganchar not in ganchos:
            ganchos.append(_reenganchar)
            informe.setdefault("enganchado", [])
            if "medios.AL_CARGAR" not in informe["enganchado"]:
                informe["enganchado"].append("medios.AL_CARGAR")


def _reenganchar(clave, modulo):
    """Vuelve a medir un motor que se acaba de (re)cargar."""
    if os.path.basename(str(clave)).lower() != "imagen.py":
        return
    _envolver(modulo, "generar", _medir_imagen,
              {"enganchado": [], "ausente": []}, "imagen_openai.generar")


def modulos_de_imagen(pasos=None):
    """Todas las copias cargadas del motor de imagen.

    Hay mas de una a proposito, aunque no lo parezca: los pasos 6, 7 y 8 hacen
    'import medios' a secas y el paquete hace 'from . import medios', asi que
    conviven dos modulos medios con su propia cache de motores, y cada uno carga
    su copia de imagen.py. Enganchar solo una dejaria sin contar justo las
    llamadas que hace el paso de assets, que es el que gasta.
    """
    import sys

    modulos = []
    candidatos = [getattr(pasos, "medios", None) if pasos else None,
                  sys.modules.get("medios"), sys.modules.get("pasos.medios")]
    for medios in candidatos:
        if medios is None or not hasattr(medios, "motor"):
            continue
        try:
            modulo = medios.motor("imagen_openai/imagen.py")
        except Exception:  # noqa: BLE001
            continue
        if modulo not in modulos:
            modulos.append(modulo)
    for modulo in list(sys.modules.values()):
        fichero = getattr(modulo, "__file__", "") or ""
        if os.path.basename(fichero).lower() == "imagen.py" and \
                "imagen_openai" in fichero.replace("/", os.sep) and \
                modulo not in modulos:
            modulos.append(modulo)
    return modulos


def informe_instrumentacion():
    """Que esta enganchado, que falta y cuantos eventos se quedaron sin dueno."""
    with _ACTIVOS_LOCK:
        huerfanos = dict(_SIN_CONTEXTO)
        activos = len({id(c) for c in _ACTIVOS.values()})
    return {"enganchado": list(_INFORME["enganchado"]),
            "ausente": list(_INFORME["ausente"]),
            "fecha": _INFORME["fecha"],
            "contextos_activos": activos,
            "sin_contexto": huerfanos}
