"""
Servicio HTTP del Estudio de Video.

Expone por API TODO lo que sabe hacer el nucleo y los ocho pasos: crear
proyectos, leer el grafo de build, tocar parametros, ejecutar pasos (enteros o
por unidad), mandar feedback, revertir versiones, escuchar voces y servir los
archivos que se van produciendo.

    python app.py --puerto 8020

Piezas
------
Contexto     por proyecto: Proyecto + Estado + Bitacora + GestorTrabajos. El
             gestor se ata al estado del proyecto para que marque 'ejecutando' y
             'error' en el paso correcto; por eso hay uno por proyecto y un
             indice global trabajo -> proyecto para poder consultar /api/trabajos.

Ejecucion    los pasos 1-5 devuelven las salidas directamente; los pasos 6-8
             devuelven {"salidas", "unidades", ...} y aceptan unidades=[...].
             _correr_paso absorbe las dos formas y versiona con estado.completar.

Progreso     cada trabajo publica su progreso por SSE en
             /api/trabajos/{tid}/eventos, para que la UI pinte barras reales en
             vez de girar un reloj.

Errores      no hay 500 mudos: todo fallo sale como {"error": mensaje} con el
             codigo que toca, y los inesperados llevan ademas "traza".

Interfaz     web/ se sirve en la raiz del mismo origen, asi que abrir
             http://127.0.0.1:<puerto>/ da el Estudio entero.
"""
import argparse
import asyncio
import copy
import hashlib
import inspect
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
import traceback

RAIZ_ESTUDIO = os.path.dirname(os.path.abspath(__file__))
if RAIZ_ESTUDIO not in sys.path:
    sys.path.insert(0, RAIZ_ESTUDIO)

from fastapi import Body, FastAPI, Query, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import (FileResponse, HTMLResponse,  # noqa: E402
                               JSONResponse, PlainTextResponse, Response,
                               StreamingResponse)
from starlette.exceptions import HTTPException as ErrorHTTP  # noqa: E402

from nucleo.bitacora import (Bitacora, anotar_global,  # noqa: E402
                             RUTA_GLOBAL as RUTA_BITACORA_GLOBAL)
from nucleo.estado import (PASOS, PASOS_POR_ID, Estado,  # noqa: E402
                           descendientes_de)
from nucleo.proyecto import (Proyecto, ahora, escribir_json,  # noqa: E402
                             identificador, leer_json, leer_jsonl, lock_de,
                             recolocar,
                             ruta_contenida)
from nucleo.trabajos import GestorTrabajos  # noqa: E402

# Los pasos cargan los motores de `motores/` al importarse. Si uno falla, el
# servicio tiene que seguir sirviendo el resto en vez de no arrancar: el error se
# guarda y solo revienta (con explicacion) quien pida ejecutar algo.
try:
    import pasos as PASOS_MODULOS
    ERROR_PASOS = ""
except Exception as fallo:  # noqa: BLE001
    PASOS_MODULOS = None
    ERROR_PASOS = f"{type(fallo).__name__}: {fallo}"

# Estos se importan SUELTOS, sin pasar por el paquete 'pasos', a proposito:
# solo dependen de la biblioteca estandar, y el selector de ajustes y el
# historico tienen que seguir funcionando aunque un motor pesado (cv2, PIL,
# un motor pesado) rompa la carga de los pasos. Si dependieran de PASOS_MODULOS, un fallo
# en el paso de assets dejaria la pantalla de ajustes en blanco.
sys.path.insert(0, os.path.join(RAIZ_ESTUDIO, "pasos"))
import ajustes as AJUSTES  # noqa: E402
import cli_claude as CLI_CLAUDE  # noqa: E402
import estadisticas as ESTADISTICAS  # noqa: E402


def comun_tokens(sobre):
    """Tokens del sobre del CLI sin arrastrar el paquete de pasos entero."""
    uso = (sobre or {}).get("usage") if isinstance(sobre, dict) else None
    uso = uso if isinstance(uso, dict) else {}
    return {"entrada": int(uso.get("input_tokens") or 0),
            "salida": int(uso.get("output_tokens") or 0)}

VERSION = "1.0"
RAIZ_POR_DEFECTO = os.path.join(RAIZ_ESTUDIO, "proyectos")
RAIZ_WEB = os.path.join(RAIZ_ESTUDIO, "web")
ID_VALIDO = re.compile(r"^[a-z0-9_]+$")
FICHERO_WEB = re.compile(r"^[A-Za-z0-9._-]+$")
LIMITE_SALIDA = 4000        # caracteres de JSON por clave antes de resumirla
INTERVALO_SSE = 0.25
LATIDO_SSE = 15.0

#: Lo ultimo que dice una barra PUBLICA al acabar (ver `recetas.PUBLICO`).
#: El mensaje de casa sigue diciendo cuantas tareas se han hecho y cuantas
#: estaban ya; eso es un recuento del motor, no una frase para ensenar.
PUBLICO_LISTO = "Listo"

TIPOS = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mkv": "video/x-matroska",
    ".json": "application/json", ".jsonl": "application/x-ndjson",
    ".txt": "text/plain; charset=utf-8", ".md": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript", ".vtt": "text/vtt",
    ".srt": "text/plain; charset=utf-8",
}

_ESTADO_SERVICIO = {"raiz": os.environ.get("ESTUDIO_PROYECTOS") or RAIZ_POR_DEFECTO}
_CONTEXTOS = {}
_INDICE_TRABAJOS = {}
_LOCK = threading.RLock()


# --------------------------------------------------------------------- errores

class ErrorApi(Exception):
    """Fallo con codigo HTTP y mensaje pensado para que lo lea un humano."""

    def __init__(self, codigo, mensaje, extra=None):
        super().__init__(mensaje)
        self.codigo = int(codigo)
        self.mensaje = str(mensaje)
        self.extra = extra if isinstance(extra, dict) else {}


def _respuesta_error(codigo, mensaje, extra=None):
    cuerpo = {"error": str(mensaje)}
    if isinstance(extra, dict):
        cuerpo.update(extra)
    return JSONResponse(cuerpo, status_code=int(codigo))


# ------------------------------------------------------------------- proyectos

def raiz_proyectos():
    """Carpeta donde viven los proyectos de este servicio."""
    return _ESTADO_SERVICIO["raiz"]


def fijar_raiz_proyectos(ruta):
    """Cambia la carpeta base de proyectos y olvida los contextos cacheados."""
    with _LOCK:
        _ESTADO_SERVICIO["raiz"] = os.path.abspath(ruta)
        _CONTEXTOS.clear()
        os.makedirs(_ESTADO_SERVICIO["raiz"], exist_ok=True)
    return _ESTADO_SERVICIO["raiz"]


class Contexto:
    """Todo lo que hace falta para operar sobre un proyecto concreto."""

    def __init__(self, raiz):
        self.proyecto = Proyecto(raiz)
        self.estado = Estado(self.proyecto)
        self.bitacora = Bitacora(self.proyecto)
        self.gestor = GestorTrabajos(estado=self.estado, bitacora=self.bitacora)

    @property
    def id(self):
        return self.proyecto.id


def contexto(pid):
    """Contexto del proyecto, creandolo la primera vez. 404 si no existe."""
    clave = str(pid or "")
    # el id llega por URL y se convierte en ruta: solo se acepta la forma que
    # produce identificador(), asi que no hay manera de salir de la carpeta base
    if not ID_VALIDO.match(clave):
        raise ErrorApi(404, f"proyecto desconocido: {pid!r}")
    with _LOCK:
        existente = _CONTEXTOS.get(clave)
    if existente is not None:
        return existente
    raiz = os.path.join(raiz_proyectos(), clave)
    if not os.path.isdir(raiz):
        raise ErrorApi(404, f"proyecto desconocido: {clave}")
    try:
        ctx = Contexto(raiz)
    except Exception as fallo:  # noqa: BLE001
        raise ErrorApi(500, f"no se ha podido abrir el proyecto {clave}: {fallo}")
    with _LOCK:
        _CONTEXTOS.setdefault(clave, ctx)
        return _CONTEXTOS[clave]


def _registrar_trabajo(trabajo_id, pid):
    with _LOCK:
        _INDICE_TRABAJOS[trabajo_id] = pid


def contexto_de_trabajo(trabajo_id):
    """Contexto del proyecto dueno de un trabajo. 404 si no se conoce."""
    with _LOCK:
        pid = _INDICE_TRABAJOS.get(str(trabajo_id))
    if pid is None:
        raise ErrorApi(404, f"trabajo desconocido: {trabajo_id}")
    return contexto(pid)


# ----------------------------------------------------------------------- pasos

def _validar_paso(paso_id):
    if str(paso_id) not in PASOS_POR_ID:
        raise ErrorApi(404, f"paso desconocido: {paso_id}. Los pasos son: "
                            + ", ".join(p["id"] for p in PASOS))
    return str(paso_id)


def modulo_de(paso_id):
    """Modulo que implementa el paso; explica claro si no se pudo importar."""
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    modulo = PASOS_MODULOS.modulo_de(paso_id)
    if modulo is None or not hasattr(modulo, "ejecutar"):
        raise ErrorApi(501, f"el paso '{paso_id}' no tiene implementacion")
    return modulo


def _acepta_unidades(modulo):
    return "unidades" in inspect.signature(modulo.ejecutar).parameters


def _describir(modulo, params):
    describir = getattr(modulo, "describir", None)
    if not callable(describir):
        return ""
    try:
        return str(describir(params))
    except Exception as fallo:  # noqa: BLE001
        # describir() es cosmetico: que falle no puede tumbar la lectura del paso
        return f"(no se ha podido describir: {fallo})"


def _desmontar(modulo, resultado):
    """Separa salidas y unidades sea cual sea la forma que devuelva el paso."""
    if _acepta_unidades(modulo) and isinstance(resultado, dict) \
            and isinstance(resultado.get("salidas"), dict):
        mapa = resultado.get("unidades")
        return resultado["salidas"], (mapa if isinstance(mapa, dict) else None)
    if isinstance(resultado, dict):
        return resultado, None
    return {"valor": resultado}, None


def _aligerar(salidas):
    """Sustituye los bloques enormes por un resumen antes de guardarlos.

    estado.json guarda las salidas dos veces por version (activa e historico), y
    la ingesta devuelve el transcript entero: sin esto el estado crece cientos de
    KB por ejecucion. Solo se tocan listas y diccionarios; las cadenas se dejan
    intactas porque son rutas y medios.salida_de() las usa para localizar
    ficheros. El contenido completo sigue en los JSON del propio paso.
    """
    if not isinstance(salidas, dict):
        return salidas, []
    ligeras = {}
    recortadas = []
    for clave, valor in salidas.items():
        if isinstance(valor, (list, dict)):
            crudo = json.dumps(valor, ensure_ascii=False, default=str)
            if len(crudo) > LIMITE_SALIDA:
                ligeras[clave] = {"_resumido": True,
                                  "elementos": len(valor),
                                  "caracteres": len(crudo)}
                recortadas.append(clave)
                continue
        ligeras[clave] = valor
    return ligeras, recortadas


import contextlib  # noqa: E402


@contextlib.contextmanager
def _motores_congelados():
    """Impide que un motor se recargue mientras un paso esta corriendo.

    Si los pasos no se han podido cargar, esto no hace nada: el paso va a
    fallar de todas formas y con su propio mensaje.
    """
    if PASOS_MODULOS is None:
        yield
        return
    with PASOS_MODULOS.medios.trabajo_en_curso():
        yield


def _correr_paso(avisar, ctx, paso_id, unidades, opciones=None):
    """Ejecuta un paso y lo versiona. Es la funcion que corre en el hilo.

    'opciones' son ajustes de ESTA invocacion, no del paso: no se guardan en los
    params y por tanto no mueven la firma. Cada modulo declara cuales entiende en
    OPCIONES_EJECUCION, y aqui solo se le pasan esas; asi una opcion nueva no
    revienta un paso que no la conoce.
    """
    modulo = modulo_de(paso_id)
    params = ctx.estado.params(paso_id)
    admitidas = getattr(modulo, "OPCIONES_EJECUCION", ())
    extra = {k: v for k, v in (opciones or {}).items() if k in admitidas}
    # Los motores de `motores/` se recargan solos cuando cambian, pero NO a
    # media tanda: dentro de esto quedan congelados (ver medios.trabajo_en_curso)
    with _motores_congelados():
        if _acepta_unidades(modulo):
            resultado = modulo.ejecutar(ctx.proyecto, params, avisar,
                                        unidades=unidades, **extra)
        else:
            resultado = modulo.ejecutar(ctx.proyecto, params, avisar, **extra)

    salidas, mapa = _desmontar(modulo, resultado)

    # sin propagar_dependencias el nucleo no sabe que escena usa que asset, y la
    # cascada de MARCADO de un asset a sus planos no existiria: cambiar una hoja
    # de personaje dejaria sus planos declarandose al dia con la hoja vieja. Lo
    # que se propaga es la etiqueta, no el trabajo (PENDIENTE 30). Va ANTES de
    # completar para que la version guarde ya las firmas propagadas.
    if paso_id == "assets":
        dependencias = resultado.get("dependencias") if isinstance(resultado, dict) else None
        modulo.propagar_dependencias(ctx.estado, dependencias)

    ligeras, recortadas = _aligerar(salidas)
    version = ctx.estado.completar(paso_id, ligeras, mapa)
    # Las unidades que el paso dice que YA NO EXISTEN se des-declaran, aqui y en
    # todo lo que cuelga. Un id de plano es posicional y se hereda entre planes;
    # sin esto, un recorte que deja fuera un plano dejaba su unidad declarada
    # para siempre, sin nadie que la produjera, y el paso se quedaba obsoleto por
    # un plano que no existe. Va DESPUES de completar: primero se sella lo que se
    # ha hecho y luego se limpia lo que sobra.
    retiradas = resultado.get("retiradas") if isinstance(resultado, dict) else None
    # Y LA RED: cualquier plano DECLARADO que el plan nuevo ya no tenga.
    #
    # El paso compara el plan nuevo contra el anterior, que es lo correcto --no
    # sabe de estado ni tiene por que--, pero eso solo pilla lo que desaparece
    # AHORA. Un plano que se fue hace veinte versiones, o antes de que esto
    # existiera, se queda declarado para siempre: nadie lo produce, su firma
    # nunca cuadra y el paso se queda en ambar. Paso con `escena:S231` en
    # `video_referencia`, que dejaba assets, callouts y render obsoletos con el video
    # recien montado.
    #
    # Se hace aqui y no en el paso porque hace falta saber QUE ESTA DECLARADO, y
    # eso es del estado. Solo en pasada completa: con unidades sueltas, el plan
    # que se acaba de calcular no es la ultima palabra sobre que planos hay.
    plan_nuevo = resultado.get("plan") if isinstance(resultado, dict) else None
    if isinstance(plan_nuevo, dict) and not unidades:
        vivos = {f"escena:{e.get('id')}" for e in (plan_nuevo.get("escenas") or [])
                 if e.get("id")}
        huerfanas = [u for u in ctx.estado.unidades_declaradas(paso_id)
                     if str(u).startswith("escena:") and u not in vivos]
        if huerfanas:
            retiradas = sorted(set(retiradas or []) | set(huerfanas))
    if retiradas:
        for destino in [paso_id] + list(descendientes_de(paso_id)):
            try:
                ctx.estado.retirar_unidades(destino, retiradas,
                                            motivo=f"fuera del plan de {paso_id}")
            except Exception as fallo:  # noqa: BLE001
                ctx.bitacora.anotar("aviso", destino, {"retirar_unidades": str(fallo)})
        ctx.bitacora.anotar("unidades_retiradas", paso_id, {"unidades": retiradas})
    ctx.bitacora.anotar("paso_completado", paso_id, {
        "version": version,
        "resumen": str(salidas.get("resumen") or ""),
        "unidades": sorted(mapa) if mapa else [],
        "retiradas": retiradas or [],
        "salidas_resumidas": recortadas,
    })
    return {
        "version": version,
        "resumen": str(salidas.get("resumen") or ""),
        "salidas": ligeras,
        "unidades": sorted(mapa) if mapa else [],
        "retiradas": retiradas or [],
        "ruta": ctx.proyecto.ruta_paso(paso_id, version),
    }


def _trabajo_activo(ctx, paso_id):
    for ficha in ctx.gestor.listar(activos=True):
        if ficha.get("paso") == paso_id:
            return ficha
    return None


def _unidades_pedidas(cuerpo):
    crudo = cuerpo.get("unidades")
    if crudo is None:
        return None
    if isinstance(crudo, str):
        crudo = [crudo]
    if not isinstance(crudo, list):
        raise ErrorApi(400, "'unidades' debe ser una lista de ids de unidad")
    limpias = [str(u).strip() for u in crudo if str(u).strip()]
    return limpias or None


def _comprobar_unidades(ctx, paso_id, unidades):
    """Rechaza unidades que el paso no declara, diciendo cuales valen.

    Solo se valida en los pasos que trabajan por unidades, porque esos las
    heredan del guion y una unidad que no existe es una equivocacion. En los
    demas, escribir una unidad en sus params es justamente lo que la declara.
    """
    if not unidades or not PASOS_POR_ID[paso_id]["unidades"]:
        return
    declaradas = set(ctx.estado.unidades_declaradas(paso_id))
    # Las unidades del PLAN del propio paso tambien valen: una caja 3D existe
    # en el plan antes de que nadie la ejecute o le escriba params (que es lo
    # que declara), y pedirla por id es justo como se construye la primera vez
    # desde su tarjeta. Sin esto, «Construir las cajas» devolvia 400 con las
    # 49 cajas del plan delante.
    modulo = modulo_de(paso_id)
    del_plan = getattr(modulo, "unidades_del_plan", None)
    if callable(del_plan):
        try:
            declaradas |= set(del_plan(ctx.proyecto))
        except Exception:  # noqa: BLE001 - un plan ilegible no anula la validacion
            pass
    if not declaradas:
        raise ErrorApi(409, f"el paso '{paso_id}' todavia no declara unidades: "
                            f"ejecutalo entero una vez antes de pedir unidades sueltas")
    desconocidas = [u for u in unidades if u not in declaradas]
    if desconocidas:
        muestra = sorted(declaradas)[:12]
        raise ErrorApi(400, f"unidades desconocidas en '{paso_id}': "
                            f"{', '.join(desconocidas)}",
                       {"declaradas": sorted(declaradas), "muestra": muestra})


def _plan_de_ejecucion(ctx, paso_id, cuerpo):
    """Que unidades hay que rehacer: lo pedido, o lo obsoleto, o todo."""
    modulo = modulo_de(paso_id)
    pedidas = _unidades_pedidas(cuerpo)
    if pedidas and not _acepta_unidades(modulo):
        raise ErrorApi(400, f"el paso '{paso_id}' no trabaja por unidades")
    if pedidas:
        _comprobar_unidades(ctx, paso_id, pedidas)
        return pedidas
    if cuerpo.get("retomar"):
        return _unidades_que_faltan(ctx, paso_id, modulo)
    if cuerpo.get("todo") or not _acepta_unidades(modulo):
        return None
    if ctx.proyecto.version_activa(paso_id) is None:
        return None
    sucias = ctx.estado.unidades_obsoletas(paso_id)
    declaradas = ctx.estado.unidades_declaradas(paso_id)
    # rehacer solo lo sucio es el caso normal; si esta todo sucio da igual y sale
    # mas barato dejar que el paso decida sin lista
    if sucias and len(sucias) < len(declaradas):
        return sucias
    return None


def _unidades_que_faltan(ctx, paso_id, modulo):
    """Lo que quedo a medias en la carpeta de trabajo, para poder RETOMAR.

    Una generacion que se corta -- se acaban los creditos de la API, se va la
    red, alguien cancela -- deja el trabajo hecho hasta ese punto en
    pasos/<paso>/trabajo/, porque sembrar_trabajo no borra nada. Volver a
    lanzar el paso entero lo regeneraria TODO y volveria a pagarlo. Retomar es
    ejecutar solo lo que falta.
    """
    calcular = getattr(modulo, "unidades_pendientes", None)
    if not callable(calcular):
        raise ErrorApi(400, f"el paso '{paso_id}' no sabe retomar: se ejecuta entero")
    try:
        faltan = calcular(ctx.proyecto, ctx.estado.params(paso_id) or {})
    except Exception as fallo:  # noqa: BLE001
        raise ErrorApi(500, f"no se ha podido mirar que falta: {fallo}")
    if faltan is None:
        return None                    # no hay nada empezado: retomar es ejecutar
    if not faltan:
        raise ErrorApi(409, "no falta nada por generar: la carpeta de trabajo ya "
                            "tiene todas las unidades. Si quieres rehacerlas, "
                            "usa ejecutar en vez de retomar")
    return faltan


def dependencias_que_faltan(ctx, paso_id, producidos=()):
    """Los pasos previos sin version que de verdad hacen falta. -> [ids]

    `producidos` son los que ESTA tanda va a producir: en una receta, 'voz' y
    'revision_audio' van juntas y la segunda no esta bloqueada, es que todavia
    no le ha tocado.

    AQUI HABIA UNA EXCEPCION PARA `ingesta` y se fue con el documentalista: el
    material podia llegar por dos vias --el paso «Origen» o un dosier armado a
    partir de busquedas-- y habia que preguntar si existia la segunda antes de
    declarar bloqueado un paso. Hoy el material es UNO y vive en «Origen», asi
    que tener version es exactamente lo mismo que tener material: preguntarlo
    dos veces solo daba dos formas de contestar distinto.
    """
    faltan = []
    for dependencia in PASOS_POR_ID[paso_id]["depende_de"]:
        if ctx.proyecto.version_activa(dependencia) is not None:
            continue
        if dependencia in producidos:
            continue
        faltan.append(dependencia)
    return faltan


def lanzar_paso(ctx, paso_id, unidades, nombre=None, evento="paso_lanzado",
                datos=None, opciones=None):
    """Comprueba que el paso se puede correr y lo manda al gestor de trabajos."""
    estado_actual = ctx.estado.estado_de(paso_id)
    if estado_actual == "bloqueado":
        faltan = dependencias_que_faltan(ctx, paso_id)
        if faltan:
            raise ErrorApi(409, f"'{paso_id}' esta bloqueado: falta ejecutar "
                                + ", ".join(faltan), {"faltan": faltan})
    activo = _trabajo_activo(ctx, paso_id)
    if activo is not None:
        raise ErrorApi(409, f"'{paso_id}' ya se esta ejecutando",
                       {"trabajo_id": activo["id"], "progreso": activo["progreso"]})

    trabajo_id = ctx.gestor.lanzar(nombre or paso_id, _correr_paso, ctx, paso_id,
                                   unidades, opciones or {}, paso=paso_id,
                                   unidades=unidades)
    _registrar_trabajo(trabajo_id, ctx.id)
    ficha = {"trabajo": trabajo_id, "unidades": unidades or "todas"}
    ficha.update(datos or {})
    ctx.bitacora.anotar(evento, paso_id, ficha)
    return trabajo_id


# --------------------------------------------------------------------- fichas

def _version_ligera(version):
    """Una entrada del historico, recortada a lo que pinta la interfaz.

    Acepta las dos formas que devuelve el nucleo: la cruda de `versiones()`,
    que trae el manifiesto entero en 'unidades', y la de `versiones_resumen()`,
    que trae el recuento ya hecho en 'n_unidades'. Se admiten las dos para que
    esta funcion valga en los dos caminos sin duplicarla, y porque el camino
    barato (el resumen) es el que usa la pantalla en cada carga.
    """
    return {
        "n": version.get("n"),
        "fecha": version.get("fecha", ""),
        "resumen": version.get("resumen", ""),
        "firma": version.get("firma", ""),
        "activa": bool(version.get("activa")),
        "unidades": (version["n_unidades"] if "n_unidades" in version
                     else len(version.get("unidades") or {})),
    }


def ficha_paso(ctx, paso_id, completa=False):
    """Ficha de un paso para la API: estado, params, salidas y unidades."""
    estado = ctx.estado
    definicion = PASOS_POR_ID[paso_id]
    params = estado.params(paso_id)
    sucias = estado.unidades_obsoletas(paso_id)
    activo = _trabajo_activo(ctx, paso_id)
    # el RESUMEN, no el historico entero: de cada version aqui solo se pintan
    # seis campos y el recuento de unidades, y `versiones()` copiaria de paso el
    # manifiesto completo de cada una -- 296 MB y ~0,9 s en un video con 73
    # versiones de assets, para tirarlo todo en la linea siguiente
    versiones = estado.versiones_resumen(paso_id)
    activa = ctx.proyecto.version_activa(paso_id)
    ficha = {
        "id": paso_id,
        "nombre": definicion["nombre"],
        "depende_de": list(definicion["depende_de"]),
        "por_unidades": definicion["unidades"],
        "estado": estado.estado_de(paso_id),
        "mensaje": estado.mensaje(paso_id),
        # 'version'/'versiones' son lo que consume la interfaz (numero activo y
        # lista para el desplegable); 'version_activa' y 'num_versiones' se
        # mantienen porque son el nombre con el que la API se documento
        "version": activa,
        "version_activa": activa,
        "versiones": [_version_ligera(v) for v in versiones],
        "num_versiones": len(versiones),
        "firma": estado.firma(paso_id),
        "unidades": estado.unidades_declaradas(paso_id),
        "unidades_obsoletas": sucias,
        # De las obsoletas, las que no tienen NADA producido: no se han quedado
        # viejas, es que todavia no se han hecho. La interfaz necesita la
        # diferencia para no decir "ha quedado obsoleto" de un plano que nunca
        # se genero, que manda a buscar un cambio aguas arriba inexistente.
        "unidades_sin_hacer": estado.unidades_sin_hacer(paso_id),
        # Lo ultimo que se CONSERVO en vez de rehacerse. Va en la ficha porque
        # un paso que dice "listo" tiene que poder explicar si es porque se
        # ejecuto o porque se dio por bueno lo que ya habia: sin esto, conservar
        # seria indistinguible de regenerar.
        "conservado": (estado.conservaciones(paso_id) or [None])[-1],
        "trabajo": activo,
        "trabajo_id": activo["id"] if activo else None,
        "params": params,
    }
    try:
        modulo = modulo_de(paso_id)
        ficha["descripcion"] = _describir(modulo, params)
        ficha["acepta_unidades"] = _acepta_unidades(modulo)
        ficha["implementado"] = True
    except ErrorApi as fallo:
        ficha["descripcion"] = ""
        ficha["acepta_unidades"] = False
        ficha["implementado"] = False
        ficha["aviso"] = fallo.mensaje
    # CON QUE REGLAS SE CORTO ESTE VIDEO. Las firmas miran los params, así que un
    # cambio en el MOTOR no pone naranja nada y el vídeo se queda con las reglas
    # de anteayer sin que ningún estado lo diga (PENDIENTE §24). No se inventa un
    # estado —eso obligaría a rehacer los renders de todos los proyectos cada vez
    # que se toca una regla—: se ENSEÑA, y quien mira decide.
    if paso_id in ("assets", "callouts", "render"):
        ficha["motor"] = _motor_del_plan(ctx)
    # LAS SALIDAS VAN SIEMPRE, tambien en la ficha ligera, y no es por comodidad.
    # El modo light lee `ficha.salidas` de la respuesta del PROYECTO (hayMp4Light,
    # urlMp4Light y leerAudioLight en web/app.js) y solo vuelve a pedir por su
    # cuenta la ficha de assets: nunca la de voz ni la de render. Dejarlas dentro
    # del `if completa` no daria ningun error -- daria algo peor, una pantalla que
    # ofrece «Montar el vídeo» encima de un mp4 que ya existe. Son 8 KB.
    ficha["salidas"] = estado.salidas(paso_id)
    if completa:
        # Duplicado literal de ficha["versiones"]: cero lectores en el front, pero
        # es el nombre con el que se documento la API y prueba_api.py lo exige en
        # el detalle de un paso, asi que se queda AQUI -- en la ficha completa, que
        # se pide de un paso cada vez -- y no en la del proyecto, que los trae los ocho.
        ficha["historico"] = [_version_ligera(v) for v in versiones]
        # Declaradas MAS producidas. Solo las declaradas dejaba fuera justo lo
        # que la interfaz necesita para pintar: un asset no tiene params propios
        # hasta que alguien le escribe feedback, asi que las hojas de personaje y
        # los sets recien generados no salian en esta lista y la pantalla se
        # quedaba sin una sola previsualizacion de lo que acababa de pagarse.
        ficha["detalle_unidades"] = [
            {"id": unidad,
             "obsoleta": unidad in sucias,
             "firma": estado.firma_unidad(paso_id, unidad),
             "salidas": estado.salidas_unidad(paso_id, unidad)}
            for unidad in sorted(set(ficha["unidades"])
                                 | set(estado.unidades_producidas(paso_id)))
        ]
    return ficha


def ficha_proyecto(ctx):
    resumen = ctx.estado.resumen()
    return {
        "id": ctx.proyecto.id,
        "nombre": ctx.proyecto.config.get("nombre", ctx.proyecto.id),
        "raiz": ctx.proyecto.raiz,
        "creado": ctx.proyecto.config.get("creado", ""),
        "actualizado": resumen.get("actualizado", ""),
        "config": ctx.proyecto.config,
    }


# --------------------------------------------------------------------- ficheros

def _tipo_de(ruta):
    extension = os.path.splitext(ruta)[1].lower()
    if extension in TIPOS:
        return TIPOS[extension]
    return mimetypes.guess_type(ruta)[0] or "application/octet-stream"


def ruta_segura(raiz, relativa):
    """Ruta dentro del proyecto; rechaza cualquier intento de salirse."""
    crudo = str(relativa or "").replace("\\", "/")
    if "\x00" in crudo:
        raise ErrorApi(400, "ruta invalida")
    destino = os.path.realpath(os.path.join(raiz, crudo.lstrip("/")))
    base = os.path.realpath(raiz)
    # realpath resuelve '..' y los enlaces, asi que basta comparar el prefijo ya
    # resuelto: una ruta absoluta ajena tampoco lo cumple
    if os.path.normcase(destino) != os.path.normcase(base) and \
            not os.path.normcase(destino).startswith(os.path.normcase(base) + os.sep):
        raise ErrorApi(403, "ruta fuera del proyecto")
    return destino


def _rango(cabecera, tamano):
    """Interpreta la cabecera Range; devuelve (inicio, fin) o None."""
    if not cabecera:
        return None
    encaje = re.fullmatch(r"bytes=(\d*)-(\d*)", str(cabecera).strip())
    if not encaje:
        return None
    inicio, fin = encaje.group(1), encaje.group(2)
    if not inicio and not fin:
        return None
    if not inicio:
        longitud = min(int(fin), tamano)
        if longitud <= 0:
            return None
        return tamano - longitud, tamano - 1
    principio = int(inicio)
    if principio >= tamano:
        return "fuera"
    final = int(fin) if fin else tamano - 1
    return principio, min(final, tamano - 1)


def servir_fichero(peticion, ruta):
    """Devuelve el fichero, con soporte de Range para audio y video."""
    tamano = os.path.getsize(ruta)
    tipo = _tipo_de(ruta)
    tramo = _rango(peticion.headers.get("range"), tamano)
    if tramo == "fuera":
        return _respuesta_error(416, "rango fuera del fichero",
                                {"tamano": tamano})
    if tramo is None:
        return FileResponse(ruta, media_type=tipo,
                            headers={"Accept-Ranges": "bytes",
                                     "Cache-Control": "no-cache"})
    inicio, fin = tramo
    longitud = fin - inicio + 1

    def trozos(bloque=1 << 16):
        with open(ruta, "rb") as fh:
            fh.seek(inicio)
            pendiente = longitud
            while pendiente > 0:
                dato = fh.read(min(bloque, pendiente))
                if not dato:
                    break
                pendiente -= len(dato)
                yield dato

    return StreamingResponse(trozos(), status_code=206, media_type=tipo, headers={
        "Content-Range": f"bytes {inicio}-{fin}/{tamano}",
        "Content-Length": str(longitud),
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-cache",
    })


def url_de(pid, ruta_absoluta, raiz):
    """Ruta absoluta -> URL servible por /a/{pid}/..., o None si esta fuera."""
    if not ruta_absoluta:
        return None
    try:
        relativa = os.path.relpath(os.path.realpath(ruta_absoluta),
                                   os.path.realpath(raiz))
    except ValueError:
        return None
    if relativa.startswith(".."):
        return None
    return f"/a/{pid}/" + relativa.replace("\\", "/")


# ------------------------------------------------------------------ aplicacion

app = FastAPI(title="Estudio de Video", version=VERSION,
              description="API del estudio: grafo de build, pasos y revision.")


@app.exception_handler(ErrorApi)
async def _manejar_error_api(peticion, fallo):
    return _respuesta_error(fallo.codigo, fallo.mensaje, fallo.extra)


@app.exception_handler(ErrorHTTP)
async def _manejar_error_http(peticion, fallo):
    return _respuesta_error(fallo.status_code, fallo.detail)


@app.exception_handler(RequestValidationError)
async def _manejar_validacion(peticion, fallo):
    detalles = []
    for problema in fallo.errors():
        sitio = ".".join(str(p) for p in problema.get("loc", ()) if p != "body")
        detalles.append(f"{sitio or 'cuerpo'}: {problema.get('msg', 'invalido')}")
    return _respuesta_error(400, "peticion mal formada: " + "; ".join(detalles),
                            {"detalles": detalles})


@app.exception_handler(Exception)
async def _manejar_imprevisto(peticion, fallo):
    return _respuesta_error(500, f"{type(fallo).__name__}: {fallo}",
                            {"traza": traceback.format_exc(limit=8)})


def _cuerpo(crudo):
    return crudo if isinstance(crudo, dict) else {}


# ------------------------------------------------------------------ proyectos

@app.get("/api/salud")
def salud():
    """Estado del servicio."""
    with _LOCK:
        abiertos = list(_CONTEXTOS)
        vivos = [_CONTEXTOS[pid] for pid in abiertos]
    activos = sum(len(ctx.gestor.listar(activos=True)) for ctx in vivos)
    return {
        "ok": True,
        "version": VERSION,
        "raiz_proyectos": raiz_proyectos(),
        "proyectos": len(Proyecto.listar(raiz_proyectos())),
        "abiertos": abiertos,
        "trabajos_activos": activos,
        "pasos": [p["id"] for p in PASOS],
        "pasos_cargados": PASOS_MODULOS is not None,
        "error_pasos": ERROR_PASOS,
        "simulado": str(os.environ.get("ESTUDIO_SIMULAR", "")).strip() in ("1", "true", "si"),
        "fecha": ahora(),
    }


@app.get("/api/proyectos")
def listar_proyectos():
    """Proyectos disponibles, del mas reciente al mas antiguo.

    Sin los TALLERES de los presets del modo light. No son videos: son la
    carpeta donde se genero un preset (sus fotogramas, su guia, sus muestras) y
    salen en esta lista como «taller Mi canal» junto a los videos de verdad,
    invitando a abrirlos y a trastear dentro de algo que no es de nadie. Siguen
    en el disco y se borran con su preset (`DELETE /api/presets-light/{id}`).
    """
    fichas = []
    for ficha in Proyecto.listar(raiz_proyectos()):
        if ficha.get(CONFIG_TALLER):
            continue
        fichas.append({
            "id": ficha.get("id"),
            "nombre": ficha.get("nombre"),
            "raiz": ficha.get("raiz"),
            "creado": ficha.get("creado", ""),
            "actualizado": ficha.get("actualizado", ""),
            # SI SE HIZO DESDE EL MODO LIGHT, y con que estilo. No lo esconde
            # --un video es un video, se haga por donde se haga-- pero la
            # galeria del modo light tiene que poder ensenar los suyos: al
            # volver de una recarga, ahi es donde se aterriza, y sin esto un
            # video a medio generar no tiene desde donde retomarse.
            "video_light": bool(ficha.get(CONFIG_VIDEO_LIGHT)),
            "estilo_light": ficha.get(CONFIG_ESTILO_LIGHT) or "",
        })
    return {"proyectos": fichas, "raiz": raiz_proyectos()}


#: Tope del nombre visible de un proyecto. No lo pide ningun formato: es que la
#: lista del modo light lo pinta en una linea, y un nombre de mil caracteres
#: rompe la fila sin avisar de nada.
LARGO_MAXIMO_NOMBRE = 120


@app.post("/api/proyectos", status_code=201)
def crear_proyecto(cuerpo: dict = Body(default=None)):
    """Crea un proyecto nuevo a partir de {"nombre"}."""
    datos = _cuerpo(cuerpo)
    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        raise ErrorApi(400, "hace falta 'nombre' para crear el proyecto")
    if not identificador(nombre):
        raise ErrorApi(400, f"'{nombre}' no da un identificador valido")
    os.makedirs(raiz_proyectos(), exist_ok=True)
    try:
        proyecto = Proyecto.crear(raiz_proyectos(), nombre)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido crear el proyecto: {fallo}")
    ctx = contexto(proyecto.id)
    if isinstance(datos.get("config"), dict):
        ctx.proyecto.config.update(datos["config"])
        ctx.proyecto.guardar_config()
    # LA CALIDAD DE IMAGEN SE ESCRIBE AQUI, al crear, y no se lee al generar.
    # Leerla al generar dejaria obsoletas las imagenes de todos los proyectos
    # que nunca la fijaron en cuanto alguien tocara el ajuste -- `calidad` entra
    # en la firma de cada imagen --, y eso es dinero. Escrita aqui, lo viejo se
    # queda como estaba y esto es solo el punto de partida del proyecto nuevo.
    try:
        ctx.estado.actualizar_params("assets",
                                     {"calidad": AJUSTES.calidad_imagen()})
    except Exception:  # noqa: BLE001
        # un ajuste ilegible no puede impedir crear un proyecto: se queda con
        # el valor por defecto del paso, que es el que habia antes de todo esto
        pass
    ctx.bitacora.anotar("proyecto_creado", None, {"nombre": nombre, "id": proyecto.id})
    return {"proyecto": ficha_proyecto(ctx),
            "pasos": [ficha_paso(ctx, p["id"]) for p in PASOS]}


@app.post("/api/proyectos/{pid}/duplicar", status_code=201)
def duplicar_proyecto(pid: str, cuerpo: dict = Body(default=None)):
    """Copia un proyecto entero con lo que tiene puesto HOY. -> el nuevo.

    Para qué sirve, que es lo que decide su forma: repetir un vídeo con otra
    cosa cambiada —otro idioma, otro estilo, otra tanda de arreglos— sin volver a
    pagar las imágenes y sin tocar el original. Es la operación que se estaba
    haciendo a mano copiando carpetas, que es como se acaba con dos proyectos
    escribiendo en los mismos ficheros.

    NO ES UN CLON DEL DISCO. Se copia la versión ACTIVA de cada paso y se
    renumera a v1; el historial se queda en el original, que es de quien es. En
    el video largo eso son 0,89 GB en vez de 11,6. Y todas las rutas absolutas del
    estado se mudan a la carpeta nueva: sin eso, la copia trabajaría sobre los
    ficheros del original sin decirlo (ver `Proyecto.duplicar`).

    Con 'desde' se pide que un paso y todo lo que cuelga de él se queden SIN
    HACER en la copia: útil para «lo mismo pero volviendo a montar desde las
    capas». Sin 'desde', la copia queda al día en todo.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    nombre = str(datos.get("nombre") or "").strip() or f"Copia {ctx.proyecto.config.get('nombre') or ctx.id}"
    if not identificador(nombre):
        raise ErrorApi(400, f"'{nombre}' no da un identificador valido")
    # NO SE DUPLICA CON UNA TANDA CORRIENDO. Un paso a medias escribe en
    # `trabajo/` y sella al terminar: copiar en mitad de eso da una copia que
    # dice «listo» de una version que todavia se estaba escribiendo.
    activos = [t for t in ctx.gestor.listar(activos=True)]
    if activos:
        raise ErrorApi(409, f"hay {len(activos)} trabajo(s) corriendo en este "
                            f"proyecto: espera a que terminen para duplicarlo")
    desde = str(datos.get("desde") or "").strip()
    saltar = ()
    if desde:
        desde = _validar_paso(desde)
        saltar = tuple([desde] + list(descendientes_de(desde)))
    try:
        nuevo = ctx.proyecto.duplicar(raiz_proyectos(), nombre, saltar=saltar)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido duplicar el proyecto: {fallo}")
    destino = contexto(nuevo.id)
    destino.bitacora.anotar("proyecto_duplicado", None,
                            {"de": ctx.id, "nombre": nombre,
                             "sin_hacer": list(saltar)})
    ctx.bitacora.anotar("proyecto_duplicado", None,
                        {"a": nuevo.id, "nombre": nombre})
    return {"proyecto": ficha_proyecto(destino),
            "copia_de": ctx.id,
            "sin_hacer": list(saltar),
            "pasos": [ficha_paso(destino, p["id"]) for p in PASOS]}


# -------------------------------------------------------------- la papelera
# Un proyecto es el trabajo de varias horas y varios euros de generacion. No se
# borra: se aparta. La carpeta se mueve a proyectos/_papelera/, que no aparece en
# el listado porque no tiene fichero de configuracion, y se puede devolver.
# No hay ruta para vaciar la papelera a proposito: borrar de verdad se hace desde
# el explorador, mirando lo que se borra.

NOMBRE_PAPELERA = "_papelera"


def raiz_papelera():
    return os.path.join(raiz_proyectos(), NOMBRE_PAPELERA)


def _ficha_papelera(nombre):
    carpeta = os.path.join(raiz_papelera(), nombre)
    config = {}
    try:
        with open(os.path.join(carpeta, "proyecto.json"), "r", encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        config = {}
    pid, _, marca = str(nombre).rpartition("__")
    return {
        "carpeta": nombre,
        "id": config.get("id") or pid or nombre,
        "nombre": config.get("nombre") or pid or nombre,
        "creado": config.get("creado", ""),
        "actualizado": config.get("actualizado", ""),
        "apartado": marca.replace("T", " ") if marca else "",
        "raiz": carpeta,
    }


@app.get("/api/proyectos/papelera")
def listar_papelera():
    """Proyectos apartados, del mas recientemente apartado al mas antiguo."""
    base = raiz_papelera()
    if not os.path.isdir(base):
        return {"papelera": [], "raiz": base}
    fichas = [_ficha_papelera(n) for n in sorted(os.listdir(base), reverse=True)
              if os.path.isdir(os.path.join(base, n))]
    return {"papelera": fichas, "raiz": base}


# OJO AL ORDEN: esta ruta tiene que declararse ANTES que DELETE
# /api/proyectos/{pid}. Starlette resuelve por orden de declaracion, y
# declarada despues 'papelera' casaba con {pid} y devolvia «proyecto
# desconocido: papelera» -- el endpoint era inalcanzable.
@app.delete("/api/proyectos/papelera")
def vaciar_papelera(confirmar: bool = Query(default=False)):
    """Vacia la papelera entera. Tampoco tiene vuelta atras."""
    base = raiz_papelera()
    carpetas = ([n for n in sorted(os.listdir(base))
                 if os.path.isdir(os.path.join(base, n))]
                if os.path.isdir(base) else [])
    total = [_peso_de(os.path.join(base, n)) for n in carpetas]
    ficheros = sum(f for f, _ in total)
    tamano = sum(t for _, t in total)
    if not confirmar:
        raise ErrorApi(409, f"esto borra {len(carpetas)} proyecto(s), {ficheros} "
                            f"ficheros ({tamano / (1024 * 1024):.1f} MB), y no se "
                            f"puede deshacer: repite la llamada con confirmar=true",
                       {"proyectos": carpetas, "ficheros": ficheros, "bytes": tamano})
    borrados, fallidos = [], []
    for nombre in carpetas:
        try:
            shutil.rmtree(os.path.join(base, nombre))
            borrados.append(nombre)
        except OSError as fallo:
            fallidos.append({"carpeta": nombre, "error": str(fallo)})
    anotar_global("papelera_vaciada",
                  {"borrados": len(borrados), "fallidos": len(fallidos),
                   "ficheros": ficheros, "bytes": tamano})
    if fallidos and not borrados:
        raise ErrorApi(500, f"no se ha podido borrar nada: {fallidos[0]['error']}",
                       {"fallidos": fallidos})
    return {"borrados": borrados, "fallidos": fallidos,
            "ficheros": ficheros, "bytes": tamano}


@app.delete("/api/proyectos/{pid}")
def apartar_proyecto(pid: str):
    """Mueve el proyecto a la papelera. No borra nada."""
    ctx = contexto(pid)
    activos = [t for t in ctx.gestor.listar(activos=True)]
    if activos:
        raise ErrorApi(409, f"'{pid}' tiene {len(activos)} trabajo(s) en marcha: "
                            f"cancelalos antes de apartarlo",
                       {"trabajos": [t.get("id") for t in activos]})
    origen = ctx.proyecto.raiz
    marca = time.strftime("%Y%m%dT%H%M%S")
    destino = os.path.join(raiz_papelera(), f"{pid}__{marca}")
    # El apunte va al log GLOBAL y no a la bitacora del proyecto, que es lo que
    # se hacia. Escribir dentro de una carpeta y moverla en la linea siguiente es
    # pedir un [WinError 5]: en Windows el fichero recien escrito puede seguir
    # tomado un instante --por el indexador, por el antivirus, por la respuesta
    # HTTP que lo estaba sirviendo-- y una carpeta con algo tomado dentro no se
    # mueve. Ademas la bitacora del proyecto se va CON el proyecto, asi que el
    # unico sitio donde ese apunte sirve para algo es el global (ver
    # `bitacora.anotar_global`, escrito para exactamente esto).
    anotar_global("proyecto_apartado", {"id": pid, "destino": destino},
                  proyecto=pid)
    try:
        os.makedirs(raiz_papelera(), exist_ok=True)
        # recolocar y no os.rename: insiste unos segundos y, si aun asi no puede
        # moverlo, lo copia y borra el origen como se pueda. Un `os.rename`
        # pelado no da NINGUNA oportunidad, y el bloqueo aqui es casi siempre de
        # milisegundos: la propia interfaz estaba sirviendo los PNG del proyecto
        # cuando se pulso el boton. Es la misma funcion que ya salvaba el
        # versionado (ver su docstring: el WinError 32 al versionar).
        como = recolocar(origen, destino)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido apartar el proyecto: {fallo}. "
                            f"Se ha insistido unos segundos y sigue tomado: mira "
                            f"si tienes abierto algun fichero de {origen} en otro "
                            f"programa (un video en un reproductor, una imagen en "
                            f"un editor) y vuelve a intentarlo")
    with _LOCK:
        _CONTEXTOS.pop(str(pid), None)
    return {"apartado": pid, "papelera": destino, "como": como,
            "aviso": "sigue entero en la papelera; se puede devolver"}


@app.post("/api/proyectos/papelera/{carpeta}/restaurar")
def restaurar_proyecto(carpeta: str):
    """Devuelve a su sitio un proyecto apartado."""
    if not re.match(r"^[a-z0-9_]+__\d{8}T\d{6}$", str(carpeta or "")):
        raise ErrorApi(404, f"no hay nada asi en la papelera: {carpeta!r}")
    origen = os.path.join(raiz_papelera(), carpeta)
    if not os.path.isdir(origen):
        raise ErrorApi(404, f"no hay nada asi en la papelera: {carpeta}")
    pid = str(carpeta).rpartition("__")[0]
    destino = os.path.join(raiz_proyectos(), pid)
    if os.path.exists(destino):
        raise ErrorApi(409, f"ya existe un proyecto con el id '{pid}': "
                            f"renombra o aparta el actual antes de restaurar este")
    try:
        # el mismo motivo que al apartar: insistir unos segundos antes de darse
        # por vencido, porque el bloqueo casi siempre dura milisegundos
        recolocar(origen, destino)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido restaurar: {fallo}")
    ctx = contexto(pid)
    ctx.bitacora.anotar("proyecto_restaurado", None, {"id": pid, "desde": carpeta})
    return {"restaurado": pid, "proyecto": ficha_proyecto(ctx)}


# El borrado definitivo es la unica operacion de este servicio que destruye
# trabajo: se lleva el guion, las tomas de voz, las imagenes generadas y el
# render, o sea todo lo que se pago por generar. Por eso pide confirmacion
# explicita en el cuerpo y no se puede disparar por accidente con un DELETE
# suelto, y por eso solo alcanza a lo que YA esta en la papelera: un proyecto
# vivo hay que apartarlo antes, que es un paso mas y reversible.

def _carpeta_de_papelera(carpeta):
    """Ruta real de una carpeta de la papelera, validada. Nunca sale de ahi."""
    if not re.match(r"^[a-z0-9_]+__\d{8}T\d{6}$", str(carpeta or "")):
        raise ErrorApi(404, f"no hay nada asi en la papelera: {carpeta!r}")
    try:
        ruta = ruta_contenida(raiz_papelera(), str(carpeta))
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    if not os.path.isdir(ruta):
        raise ErrorApi(404, f"no hay nada asi en la papelera: {carpeta}")
    return ruta


def _peso_de(ruta):
    """(ficheros, bytes) de una carpeta. Para decir QUE se va a perder."""
    ficheros = tamano = 0
    for base, _, nombres in os.walk(ruta):
        for nombre in nombres:
            try:
                tamano += os.path.getsize(os.path.join(base, nombre))
            except OSError:
                continue
            ficheros += 1
    return ficheros, tamano


@app.get("/api/proyectos/papelera/{carpeta}")
def mirar_papelera(carpeta: str):
    """Que hay dentro de un proyecto apartado, para poder decir que se pierde."""
    ruta = _carpeta_de_papelera(carpeta)
    ficheros, tamano = _peso_de(ruta)
    ficha = _ficha_papelera(carpeta)
    ficha.update({"ficheros": ficheros, "bytes": tamano,
                  "megas": round(tamano / (1024 * 1024), 1)})
    return ficha


@app.delete("/api/proyectos/papelera/{carpeta}")
def borrar_de_papelera(carpeta: str, confirmar: bool = Query(default=False)):
    """Borra DE VERDAD un proyecto apartado. No hay vuelta atras."""
    ruta = _carpeta_de_papelera(carpeta)
    ficheros, tamano = _peso_de(ruta)
    if not confirmar:
        raise ErrorApi(409, f"esto borra {ficheros} ficheros ({tamano / (1024 * 1024):.1f} MB) "
                            f"y no se puede deshacer: repite la llamada con "
                            f"confirmar=true si es lo que quieres",
                       {"carpeta": carpeta, "ficheros": ficheros, "bytes": tamano})
    ficha = _ficha_papelera(carpeta)
    try:
        shutil.rmtree(ruta)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido borrar: {fallo}. Suele ser que un "
                            f"fichero del proyecto esta abierto en otro programa")
    # La bitacora global sobrevive al proyecto: es el unico sitio donde queda
    # constancia de que existio y de que se borro a proposito.
    anotar_global("proyecto_borrado",
                  {"carpeta": carpeta, "ficheros": ficheros, "bytes": tamano},
                  proyecto=ficha.get("id"))
    return {"borrado": carpeta, "id": ficha.get("id"),
            "ficheros": ficheros, "bytes": tamano}


@app.get("/api/proyectos/{pid}")
def leer_proyecto(pid: str):
    """Estado del proyecto: los ocho pasos, sus params, versiones y trabajos.

    Los pasos van en ficha LIGERA (`completa=False`), y esta es la decision que
    hace que abrir un video sea instantaneo. La ficha completa anade
    `detalle_unidades`, que en un video de 240 planos son 4,15 MB -- el 94,5 %
    de esta respuesta -- y que aqui no lee NADIE: los cuatro sitios del front que
    lo consumen (unidadesDeFicha en web/app.js) reciben su ficha de
    `GET /pasos/{paso}`, que sigue trayendolo. Se pedian los ocho pasos al
    completo para pintar una pantalla que ensena uno.

    Lo que si va aqui es `salidas`, que el modo light lee de esta respuesta y no
    vuelve a pedir. Ver el comentario de `ficha_paso`.
    """
    ctx = contexto(pid)
    return {
        "proyecto": ficha_proyecto(ctx),
        "pasos": [ficha_paso(ctx, p["id"]) for p in PASOS],
        "trabajos": ctx.gestor.listar(activos=True),
    }


@app.put("/api/proyectos/{pid}")
def renombrar_proyecto(pid: str, cuerpo: dict = Body(default=None)):
    """Cambia el nombre VISIBLE del proyecto. -> la ficha.

    LA CARPETA Y EL ID NO SE TOCAN, y no es una limitacion: es el diseno.
    `pid` es la clave primaria de todo lo demas -- las rutas dentro de
    estado.json, las rutas ABSOLUTAS que el manifiesto de assets guarda por
    unidad (111 en el video del oro), el `proyecto` de cada linea de
    coste_global.jsonl y de la bitacora global, y el id que el modo light se
    guarda en el navegador para saber que video estabas mirando. Mover la
    carpeta seria una migracion con seis sitios que tocar, no un renombrado.
    Asi que esto cambia la ETIQUETA: lo que se lee en la lista.

    Y NO MUEVE NINGUNA FIRMA, que es lo que hace que sea seguro llamarlo sobre
    un video terminado. Comprobado antes de escribirlo: el nombre solo se usa
    para derivar el id al CREAR (`Proyecto.crear`) y como etiqueta; ningun paso
    lee `proyecto.config["nombre"]` al generar, y no esta en los params de
    ninguno. La firma de una unidad sale de sus params guardados
    (`Estado._firma_unidad`), asi que renombrar no deja obsoleto nada.

    Se exige que el nombre lleve alguna letra o cifra, y se comprueba ASI y no
    con `if not identificador(nombre)` como hacen `crear_proyecto` y
    `crear_video_light`: `identificador` **nunca** devuelve vacio -- cae en
    "proyecto" (`return plano or "proyecto"`) --, asi que esa guarda no puede
    dispararse nunca y las dos que hay escritas son codigo muerto. Lo que se
    quiere evitar es real: «!!! ???» seria una etiqueta ilegible en la lista, y
    al duplicarlo la copia acabaria en una carpeta llamada `proyecto`.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        raise ErrorApi(400, "hace falta 'nombre' para renombrar el proyecto")
    if len(nombre) > LARGO_MAXIMO_NOMBRE:
        raise ErrorApi(400, f"el nombre no puede pasar de "
                            f"{LARGO_MAXIMO_NOMBRE} caracteres")
    if not any(c.isalnum() for c in nombre):
        raise ErrorApi(400, f"'{nombre}' no tiene ninguna letra ni cifra")
    antes = ctx.proyecto.config.get("nombre") or ctx.id
    if nombre == antes:
        return {"proyecto": ficha_proyecto(ctx), "cambiado": False}
    ctx.proyecto.config["nombre"] = nombre
    ctx.proyecto.guardar_config()
    ctx.bitacora.anotar("proyecto_renombrado", None,
                        {"antes": antes, "ahora": nombre})
    return {"proyecto": ficha_proyecto(ctx), "cambiado": True}


@app.get("/api/proyectos/{pid}/pasos")
def listar_pasos(pid: str):
    """Resumen del DAG con el estado de cada paso."""
    ctx = contexto(pid)
    return {"proyecto": ctx.id,
            "pasos": [ficha_paso(ctx, p["id"]) for p in PASOS]}


@app.get("/api/proyectos/{pid}/pasos/{paso}")
def leer_paso(pid: str, paso: str):
    """Detalle de un paso: params, salidas, unidades y versiones."""
    ctx = contexto(pid)
    paso_id = _validar_paso(paso)
    ficha = ficha_paso(ctx, paso_id, completa=True)
    # `_version_ligera` se queda con seis campos, asi que pedir el historico
    # entero (y copiarlo) para tirarlo aqui mismo era pagar 296 MB por nada
    ficha["versiones_detalle"] = [_version_ligera(v)
                                  for v in ctx.estado.versiones_resumen(paso_id)]
    return ficha


# Claves de ajuste del CLI y que son: (validador, es_modelo)
CLAVES_AJUSTE = {
    "modelo": True, "modelo_texto": True,
    "esfuerzo": False, "esfuerzo_texto": False,
}





def _validar_params(paso_id, nuevos, ctx=None):
    """Rechaza un ajuste del CLI imposible AL GUARDARLO, no al ejecutar.

    Guardar 'esfuerzo: turbo' y enterarse veinte minutos despues, cuando el paso
    revienta al normalizar, es la version cara del mismo error. Y peor en los
    pasos que se tragan el fallo: la revision de audio devuelve el texto original
    si la llamada falla, asi que un modelo mal escrito se veia como "no ha
    cambiado nada".

    Se validan SOLO las claves de ajuste, y a proposito. El `estricto` de cada
    paso significa "esto ya se puede ejecutar", no "este valor es valido": el
    brief, por ejemplo, exige instrucciones no vacias, y usarlo aqui impediria
    guardar un brief a medias mientras se escribe. Guardar y ejecutar son dos
    momentos distintos y solo el segundo exige que este todo.
    """
    for clave, es_modelo in CLAVES_AJUSTE.items():
        if clave not in (nuevos or {}):
            continue
        valor = nuevos[clave]
        if valor in (None, ""):
            continue
        try:
            if es_modelo:
                CLI_CLAUDE.normalizar_modelo(valor)
            else:
                CLI_CLAUDE.normalizar_esfuerzo(valor)
        except ValueError as fallo:
            raise ErrorApi(400, f"{clave}: {fallo}")

    # una lista con un nombre mal escrito no revienta nada. Las
    # transiciones desconocidas se filtran y el video sale con las de fabrica;
    # una plantilla desconocida se dibuja como la de respaldo. En los dos casos
    # el error se ve renderizando, que es tarde y encima no dice que paso.
    # LAS LLAMADAS A LA ACCION, por lo mismo: un producto que no existe o una
    # ranura que no es un objeto no es "un guion a medias mientras se escribe",
    # es un valor imposible. Guardarlo y enterarse al redactar seria enterarse
    # despues de haber pagado la llamada al CLI.
    if paso_id == "guion" and "cta" in (nuevos or {}) and PASOS_MODULOS is not None:
        try:
            PASOS_MODULOS.cta.normalizar(nuevos["cta"], estricto=True)
        except ValueError as fallo:
            raise ErrorApi(400, f"cta: {fallo}")

    if PASOS_MODULOS is not None:
        listas = (("transiciones", PASOS_MODULOS.transiciones.CATALOGO,
                   "transiciones"),
                  ("plantillas_cartela", PASOS_MODULOS.cartelas.PLANTILLAS,
                   "plantillas de cartela"))
        for clave, catalogo, comose in listas:
            valores = (nuevos or {}).get(clave)
            if not isinstance(valores, list):
                continue
            fuera = [str(v) for v in valores if str(v) not in catalogo]
            if fuera:
                raise ErrorApi(400, f"{clave}: no existen {', '.join(fuera)}. "
                                    f"Las {comose} son: {', '.join(catalogo)}")


@app.put("/api/proyectos/{pid}/pasos/{paso}/params")
def fijar_params(pid: str, paso: str, cuerpo: dict = Body(default=None)):
    """Actualiza los parametros del paso; la obsolescencia cae en cascada sola."""
    ctx = contexto(pid)
    paso_id = _validar_paso(paso)
    datos = _cuerpo(cuerpo)
    reemplazar = bool(datos.get("reemplazar"))
    if "params" in datos:
        # si el que llama nombra 'params' expresamente, tiene que ser un objeto:
        # tragarselo como un parametro mas llamado "params" seria peor que fallar
        if not isinstance(datos["params"], dict):
            raise ErrorApi(400, "'params' debe ser un objeto, "
                                f"llego {type(datos['params']).__name__}")
        nuevos = datos["params"]
    else:
        nuevos = {k: v for k, v in datos.items() if k != "reemplazar"}

    _validar_params(paso_id, nuevos)

    antes = {p["id"]: ctx.estado.estado_de(p["id"]) for p in PASOS}
    try:
        if reemplazar:
            cambiado = ctx.estado.set_params(paso_id, nuevos)
        else:
            cambiado = ctx.estado.actualizar_params(paso_id, nuevos)
    except ValueError as fallo:
        # un param suelto indexado por unidad: es culpa de quien llama, no del
        # servidor, y decirlo con un 500 lo escondería detrás de una traza
        raise ErrorApi(400, str(fallo))

    avisos_origen = []

    # tocar a mano los params de un asset solo marca obsoletas las escenas que lo
    # usan si se vuelve a propagar la huella de dependencias
    if paso_id == "assets" and cambiado and PASOS_MODULOS is not None:
        try:
            PASOS_MODULOS.p6_assets.propagar_dependencias(ctx.estado)
        except Exception as fallo:  # noqa: BLE001
            ctx.bitacora.anotar("aviso", paso_id,
                                {"propagar_dependencias": str(fallo)})

    afectados = [p["id"] for p in PASOS
                 if ctx.estado.estado_de(p["id"]) != antes[p["id"]]]
    ctx.bitacora.anotar("params_actualizados", paso_id,
                        {"claves": sorted(nuevos), "cambio_firma": cambiado,
                         "reemplazar": reemplazar, "afectados": afectados})
    return {
        "paso": paso_id,
        "cambiado": cambiado,
        "params": ctx.estado.params(paso_id),
        "estado": ctx.estado.estado_de(paso_id),
        "unidades_obsoletas": ctx.estado.unidades_obsoletas(paso_id),
        "afectados": afectados,
        "aguas_abajo": {hijo: ctx.estado.unidades_obsoletas(hijo)
                        for hijo in descendientes_de(paso_id)},
        # lo que el material ha decidido por su cuenta, para que la pantalla
        # que acaba de guardarlo pueda ensenarlo sin volver a leer el proyecto
        "avisos": avisos_origen,
        "origen": (ctx.estado.params("ingesta") or {}).get("url") or "",
    }


@app.post("/api/proyectos/{pid}/pasos/{paso}/ejecutar", status_code=202)
def ejecutar_paso(pid: str, paso: str, cuerpo: dict = Body(default=None)):
    """Lanza el paso en segundo plano y devuelve el id del trabajo.

    Si el cuerpo trae 'params' se guardan ANTES de decidir el plan: la interfaz
    manda lo que hay escrito en la pestana al pulsar ejecutar, y ejecutar con
    los parametros viejos (la URL anterior, el prompt anterior) seria mentir.
    Guardarlos antes hace ademas que las unidades que ese cambio ensucia entren
    en el plan de esta misma pasada.
    """
    ctx = contexto(pid)
    paso_id = _validar_paso(paso)
    datos = _cuerpo(cuerpo)
    if isinstance(datos.get("params"), dict):
        ctx.estado.actualizar_params(paso_id, datos["params"])
        if paso_id == "assets" and PASOS_MODULOS is not None:
            try:
                PASOS_MODULOS.p6_assets.propagar_dependencias(ctx.estado)
            except Exception as fallo:  # noqa: BLE001
                ctx.bitacora.anotar("aviso", paso_id,
                                    {"propagar_dependencias": str(fallo)})
    elif datos.get("params") is not None:
        raise ErrorApi(400, "'params' debe ser un objeto, "
                            f"llego {type(datos['params']).__name__}")
    unidades = _plan_de_ejecucion(ctx, paso_id, datos)
    # Ajustes de ESTA invocacion. No son params y no mueven la firma: describen
    # como se corre esta vez, no que produce el paso.
    opciones = {clave: bool(datos.get(clave))
                for clave in ("solo_assets", "replantear", "rehacer",
                              "solo_montar")
                if datos.get(clave)}
    # 'tipos' limita una pasada de assets a esas clases de pieza ('reparto'
    # para las hojas; 'mapa', 'grafico', 'cabecera' para las piezas). Es una
    # LISTA, no una bandera, asi que no entra por el bucle de arriba -- y sin
    # esto el boton de "Generar los personajes" mandaba tipos, el servidor lo
    # tiraba y la pasada generaba (y cobraba) el paso entero. Viaja como las
    # demas opciones: cada modulo declara en OPCIONES_EJECUCION si la entiende.
    if datos.get("tipos") is not None:
        if not isinstance(datos["tipos"], list) or not all(
                isinstance(t, str) and t.strip() for t in datos["tipos"]):
            raise ErrorApi(400, "'tipos' debe ser una lista de clases de pieza"
                                " (p. ej. [\"reparto\"])")
        if datos["tipos"]:
            opciones["tipos"] = [t.strip() for t in datos["tipos"]]
    trabajo_id = lanzar_paso(ctx, paso_id, unidades, opciones=opciones)
    return {"trabajo_id": trabajo_id, "paso": paso_id, "opciones": opciones,
            "unidades": unidades, "estado": "ejecutando",
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.get("/api/proyectos/{pid}/pasos/{paso}/versiones")
def listar_versiones(pid: str, paso: str, detalle: int = Query(default=0)):
    """Historico de versiones del paso."""
    ctx = contexto(pid)
    paso_id = _validar_paso(paso)
    # Sin `detalle` esto solo pinta la lista, asi que se lee el resumen: pedir
    # `versiones()` para pasarlo entero por _version_ligera copiaba el manifiesto
    # de cada version (cientos de MB) y se quedaba con seis campos. Con
    # `detalle=1` si hace falta el historico crudo, params incluidos, que es lo
    # que comprueba prueba_api.py.
    if detalle:
        fichas = ctx.estado.versiones(paso_id)
    else:
        fichas = [_version_ligera(v) for v in ctx.estado.versiones_resumen(paso_id)]
    return {"paso": paso_id,
            "activa": ctx.proyecto.version_activa(paso_id),
            "versiones": fichas}


@app.post("/api/proyectos/{pid}/pasos/{paso}/revertir")
def revertir_paso(pid: str, paso: str, cuerpo: dict = Body(default=None)):
    """Activa una version anterior del paso; nada se borra."""
    ctx = contexto(pid)
    paso_id = _validar_paso(paso)
    datos = _cuerpo(cuerpo)
    if "version" not in datos:
        raise ErrorApi(400, "hace falta 'version' para revertir")
    try:
        numero = int(datos["version"])
    except (TypeError, ValueError):
        raise ErrorApi(400, f"'version' debe ser un entero, no {datos['version']!r}")
    if _trabajo_activo(ctx, paso_id):
        raise ErrorApi(409, f"'{paso_id}' se esta ejecutando: no se puede revertir ahora")
    try:
        ctx.estado.revertir(paso_id, numero)
    except ValueError as fallo:
        raise ErrorApi(404, str(fallo))
    ctx.bitacora.anotar("revertido", paso_id, {"version": numero})
    return {"paso": paso_id, "activa": ctx.proyecto.version_activa(paso_id),
            "estado": ctx.estado.estado_de(paso_id),
            "params": ctx.estado.params(paso_id),
            "aguas_abajo": {hijo: ctx.estado.estado_de(hijo)
                            for hijo in descendientes_de(paso_id)}}


# -------------------------------------------------------------------- feedback

def _describir_trazos(trazos):
    """Trazos del canvas -> frase, con el motor de revision si esta disponible."""
    if not trazos:
        return ""
    try:
        motor = PASOS_MODULOS.comun.cargar_motor("revision", "regenerar.py")
        return motor.describir_trazos(trazos)
    except Exception:  # noqa: BLE001
        # el motor carga imagen_openai: si eso falla, el feedback no se pierde,
        # solo se queda sin la frase de zonas
        return ""


def _nota_de(datos, historial):
    texto = str(datos.get("texto") or "").strip()
    trazos = datos.get("trazos") or []
    if not isinstance(trazos, list):
        raise ErrorApi(400, "'trazos' debe ser una lista")
    if not texto and not trazos:
        raise ErrorApi(400, "el feedback necesita 'texto' o 'trazos'")
    modo = str(datos.get("modo") or "directo").strip().lower()
    if modo not in ("directo", "agente"):
        raise ErrorApi(400, f"modo desconocido: {modo!r}. Usa 'directo' o 'agente'")
    return {
        "id": f"F{len(historial) + 1:03d}",
        "fecha": ahora(),
        "texto": texto,
        "modo": modo,
        "trazos": len(trazos),
        "zonas": _describir_trazos(trazos),
    }


def _historial(params, unidad):
    if unidad:
        bloque = params.get("unidades")
        actual = bloque.get(unidad) if isinstance(bloque, dict) else None
        actual = actual if isinstance(actual, dict) else {}
        historial = actual.get("feedback")
        return actual, list(historial) if isinstance(historial, list) else []
    historial = params.get("feedback")
    return params, list(historial) if isinstance(historial, list) else []


@app.post("/api/proyectos/{pid}/feedback", status_code=202)
def enviar_feedback(pid: str, cuerpo: dict = Body(default=None)):
    """Feedback general o sobre una unidad; rehace SOLO lo que apunta.

    La nota se guarda en los parametros del paso. Eso cambia su firma (la global
    si es feedback general, la de la unidad si va dirigido), y el nucleo deriva
    solo que queda obsoleto aguas abajo -- esa cascada de MARCADO se queda, es
    la que hace que la etiqueta signifique algo.

    Lo que ya no hay es cascada de GENERACION (PENDIENTE 30). Escribirle
    feedback a UNA hoja de personaje relanzaba el paso con todo lo sucio detras,
    o sea las cuarenta y cuatro imagenes que usan esa hoja, sin preguntar y sin
    decir antes lo que costaban. Ahora:

      con unidad    se rehace ESA unidad y nada mas;
      sin unidad    el feedback es del paso entero, asi que se rehace lo sucio
                    -- que es lo que el propio texto pide.

    Lo que ha quedado obsoleto por arrastre viaja igual en la respuesta
    (`afectadas`, `aguas_abajo`) para que la pantalla lo diga y ofrezca
    accionarlo con su cuenta y su coste delante.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    if not datos.get("paso"):
        raise ErrorApi(400, "hace falta 'paso' en el feedback")
    paso_id = _validar_paso(datos.get("paso"))
    unidad = datos.get("unidad")
    unidad = str(unidad).strip() if unidad not in (None, "") else None
    if unidad:
        _comprobar_unidades(ctx, paso_id, [unidad])
    # se resuelve antes de tocar nada: si el paso no tiene implementacion, mejor
    # fallar sin haber dejado el feedback escrito a medias
    ejecutar_despues = datos.get("ejecutar") is not False
    modulo = modulo_de(paso_id) if ejecutar_despues else None

    params = ctx.estado.params(paso_id)
    destino, historial = _historial(params, unidad)
    nota = _nota_de(datos, historial)
    historial.append(nota)

    # Los comentarios sobre texto seleccionado se retiraron enteros: el feedback
    # de audio se da POR SECCION (regrabar_seccion), asi que el de revision va
    # por el camino generico de unidades como el de cualquier otro paso.
    if unidad:
        nuevo = dict(destino)
        nuevo["feedback"] = historial
        ctx.estado.actualizar_params(paso_id, {"unidades": {unidad: nuevo}})
    else:
        ctx.estado.actualizar_params(paso_id, {"feedback": historial})

    if paso_id == "assets" and PASOS_MODULOS is not None:
        try:
            PASOS_MODULOS.p6_assets.propagar_dependencias(ctx.estado)
        except Exception as fallo:  # noqa: BLE001
            ctx.bitacora.anotar("aviso", paso_id, {"propagar_dependencias": str(fallo)})

    afectadas = ctx.estado.unidades_obsoletas(paso_id)
    aguas_abajo = {hijo: ctx.estado.unidades_obsoletas(hijo)
                   for hijo in descendientes_de(paso_id)}
    ctx.bitacora.anotar("feedback", paso_id, {
        "modo": nota["modo"], "texto": nota["texto"], "zonas": nota["zonas"],
        "trazos": nota["trazos"], "afectadas": afectadas,
    }, unidad=unidad)

    respuesta = {
        "paso": paso_id, "unidad": unidad, "nota": nota,
        "afectadas": afectadas, "aguas_abajo": aguas_abajo,
        "estado": ctx.estado.estado_de(paso_id),
    }
    if not ejecutar_despues:
        respuesta["trabajo_id"] = None
        return respuesta

    # REHACER UNA COSA REHACE ESA COSA. Con la nota dirigida a una unidad se
    # rehace esa unidad, aunque el marcado haya ensuciado veinte mas: esas veinte
    # quedan `obsoleto` y las acciona una persona desde «Regenerar lo obsoleto
    # (N)», que dice cuantas son y lo que cuestan antes de pulsar. Un feedback
    # general si es del paso entero, y ahi lo sucio es exactamente lo que la
    # nota pide rehacer.
    if unidad and _acepta_unidades(modulo):
        unidades = [unidad]
    else:
        unidades = afectadas if (afectadas and _acepta_unidades(modulo)) else None
    respuesta["unidades_lanzadas"] = list(unidades) if unidades else None
    respuesta["trabajo_id"] = lanzar_paso(
        ctx, paso_id, unidades, nombre=f"feedback:{paso_id}",
        evento="feedback_lanzado", datos={"modo": nota["modo"], "unidad": unidad})
    respuesta["eventos"] = f"/api/trabajos/{respuesta['trabajo_id']}/eventos"
    return respuesta


# -------------------------------------------------------------------- trabajos

@app.get("/api/trabajos")
def listar_trabajos(proyecto: str = Query(default=None),
                    activos: int = Query(default=0)):
    """Trabajos conocidos, opcionalmente de un solo proyecto."""
    with _LOCK:
        pids = [proyecto] if proyecto else list(_CONTEXTOS)
    fichas = []
    for pid in pids:
        try:
            ctx = contexto(pid)
        except ErrorApi:
            continue
        for ficha in ctx.gestor.listar(activos=bool(activos)):
            ficha["proyecto"] = ctx.id
            fichas.append(ficha)
    return {"trabajos": fichas}


@app.get("/api/trabajos/{tid}")
def leer_trabajo(tid: str):
    """Estado y progreso de un trabajo."""
    ctx = contexto_de_trabajo(tid)
    try:
        ficha = ctx.gestor.estado(tid)
    except KeyError:
        raise ErrorApi(404, f"trabajo desconocido o ya olvidado: {tid}")
    ficha["proyecto"] = ctx.id
    return ficha


@app.post("/api/trabajos/{tid}/cancelar")
def cancelar_trabajo(tid: str):
    """Pide la cancelacion cooperativa de un trabajo."""
    ctx = contexto_de_trabajo(tid)
    try:
        pedido = ctx.gestor.cancelar(tid)
    except KeyError:
        raise ErrorApi(404, f"trabajo desconocido o ya olvidado: {tid}")
    ficha = ctx.gestor.estado(tid)
    ctx.bitacora.anotar("cancelacion_pedida", ficha.get("paso"),
                        {"trabajo": tid, "aceptada": pedido})
    return {"trabajo_id": tid, "cancelacion_pedida": pedido, "estado": ficha["estado"]}


def _sse(evento, datos):
    return f"event: {evento}\ndata: {json.dumps(datos, ensure_ascii=False, default=str)}\n\n"


@app.get("/api/trabajos/{tid}/eventos")
async def eventos_trabajo(tid: str, peticion: Request):
    """Progreso del trabajo en vivo por Server-Sent Events."""
    ctx = contexto_de_trabajo(tid)
    try:
        ctx.gestor.estado(tid)
    except KeyError:
        raise ErrorApi(404, f"trabajo desconocido o ya olvidado: {tid}")

    async def flujo():
        anterior = None
        ultimo_latido = time.time()
        while True:
            if await peticion.is_disconnected():
                return
            try:
                ficha = ctx.gestor.estado(tid)
            except KeyError:
                yield _sse("fin", {"id": tid, "estado": "olvidado"})
                return
            ficha["proyecto"] = ctx.id
            clave = (ficha["estado"], ficha["progreso"], ficha["mensaje"],
                     ficha.get("publico"))
            if clave != anterior:
                anterior = clave
                ultimo_latido = time.time()
                yield _sse("progreso", ficha)
            if ficha["estado"] in ("listo", "error", "cancelado"):
                yield _sse("fin", ficha)
                return
            # sin latido, un proxy o el navegador cierran una conexion que calla
            if time.time() - ultimo_latido > LATIDO_SSE:
                ultimo_latido = time.time()
                yield ": latido\n\n"
            await asyncio.sleep(INTERVALO_SSE)

    return StreamingResponse(flujo(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


# ------------------------------------------------------------------------- voz

def _previsualizar_voz(avisar, ctx, params, segundos):
    avisar(0.05, "preparando el texto")
    ruta = PASOS_MODULOS.p4_voz.previsualizar(ctx.proyecto, params, segundos)
    avisar(1.0, "escucha lista")
    return {"archivo": os.path.basename(ruta),
            "url": url_de(ctx.id, ruta, ctx.proyecto.raiz),
            "ruta": ruta,
            "segundos": segundos}


@app.post("/api/proyectos/{pid}/voz/previsualizar", status_code=202)
def previsualizar_voz(pid: str, cuerpo: dict = Body(default=None)):
    """Sintetiza unos segundos con estos mandos de voz para escucharlos."""
    ctx = contexto(pid)
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    datos = _cuerpo(cuerpo)
    params = datos.get("params") if isinstance(datos.get("params"), dict) else \
        {k: v for k, v in datos.items() if k not in ("segundos",)}
    if not params:
        params = ctx.estado.params("voz")
    try:
        segundos = float(datos.get("segundos") or 20)
    except (TypeError, ValueError):
        raise ErrorApi(400, "'segundos' debe ser un numero")
    if not 1 <= segundos <= 120:
        raise ErrorApi(400, "'segundos' debe estar entre 1 y 120")

    trabajo_id = ctx.gestor.lanzar("voz:previsualizar", _previsualizar_voz,
                                   ctx, params, segundos, paso=None)
    _registrar_trabajo(trabajo_id, ctx.id)
    ctx.bitacora.anotar("voz_previsualizada", "voz",
                        {"segundos": segundos, "trabajo": trabajo_id,
                         "voz": params.get("voz_id") or params.get("preset") or ""})
    return {"trabajo_id": trabajo_id, "segundos": segundos,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# El catalogo de Cartesia y los presets no dependen del proyecto: la interfaz
# los pide una sola vez al arrancar, antes incluso de tener proyecto abierto.
# (Existieron /voz/voces y /voz/presets por proyecto; eran alias literales de
# estos dos y se retiraron.)

@app.get("/api/voces")
def catalogo_voces_global(idioma: str = Query(default=None),
                          nativas: int = Query(default=0),
                          solo_nativas: int = Query(default=0),
                          refrescar: int = Query(default=0)):
    """Catalogo de voces de Cartesia, sin atarlo a ningun proyecto."""
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    try:
        voces = PASOS_MODULOS.p4_voz.listar_voces(
            idioma=idioma, refrescar=bool(refrescar),
            solo_nativas=bool(nativas or solo_nativas))
    # BaseException Y NO Exception: los motores estan escritos como CLI y abortan
    # con SystemExit --«No encuentro CARTESIA_API_KEY»--, que no es un
    # `Exception`. Se colaba por debajo, subia entera y el navegador recibia un
    # 500 sin texto: la pantalla se quedaba en «cargando tus voces...» sin decir
    # que lo que falta es la clave.
    except (Exception, SystemExit) as fallo:  # noqa: BLE001
        raise ErrorApi(502, f"no se ha podido leer el catalogo de voces: {fallo}")
    return {"voces": voces, "total": len(voces), "idioma": idioma,
            "solo_nativas": bool(nativas or solo_nativas)}


# ------------------------------------------------------------ voz descrita
#
# Elegir voz era rebuscar entre ochocientas fichas con nombres que no dicen nada
# y despues acertar a mano con velocidad, emociones y aire. Aqui se describe con
# palabras como quieres que suene y el CLI elige. Devuelve una PROPUESTA: no
# toca los params, los rellena la interfaz y decide quien mira. La voz se paga
# cada vez que se graba, asi que aplicar a ciegas son dos tomas en vez de una.

def _correr_voz_descrita(avisar, ctx, encargo, idioma, ajuste):
    if PASOS_MODULOS is None:
        raise RuntimeError(f"los pasos no se han podido cargar: {ERROR_PASOS}")
    elegido = PASOS_MODULOS.voz_descrita.proponer(
        encargo, idioma=idioma, ajuste=ajuste, avisar=avisar,
        proyecto_id=ctx.id, cwd=ctx.proyecto.raiz)
    ctx.bitacora.anotar("voz_descrita", "voz", {
        "encargo": encargo[:200], "voz": elegido.get("voz_nombre"),
        "velocidad": elegido.get("velocidad"),
        "emociones": elegido.get("emociones"),
        "hueco_minimo": elegido.get("hueco_minimo")})
    return elegido


@app.post("/api/proyectos/{pid}/voz/describir", status_code=202)
def describir_voz(pid: str, cuerpo: dict = Body(default=None)):
    """Describe como quieres que suene y devuelve voz y mandos propuestos."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    encargo = str(datos.get("encargo") or "").strip()
    if not encargo:
        raise ErrorApi(400, "hace falta describir como quieres que suene la voz")
    idioma = str(datos.get("idioma") or "").strip().lower()
    if not idioma and PASOS_MODULOS is not None:
        idioma = PASOS_MODULOS.p4_voz.idioma_de_salida(ctx.proyecto) or "es"
    por_fase = CLI_CLAUDE.por_defecto_de("voz_descrita")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("voz_descrita", _correr_voz_descrita, ctx,
                                   encargo, idioma, ajuste, paso="voz")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste, "idioma": idioma,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# --------------------------------------------------- regrabar una seccion
#
# Antes, un tartamudeo del TTS en el minuto ocho obligaba a volver a pagar y
# regrabar el video entero. Ahora se regraba la seccion y se cose.
#
# Y el cambio de texto VIAJA AL GUION. No es un extra: si se quedara solo en la
# toma, el guion y la voz dirian cosas distintas, y el guion es la entrada de
# todo lo que viene despues -- los planos, los rotulos--. Es gratis porque es la
# misma informacion.

def _correr_regrabar(avisar, ctx, seccion_id, peticion, ajuste):
    p4 = PASOS_MODULOS.p4_voz
    ficha_voz = ctx.estado.salidas("voz") or {}
    carpeta = ctx.proyecto.ruta_paso("voz")
    meta = medios_json(os.path.join(carpeta, ficha_voz.get("meta")
                                    or p4.NOMBRE_META))
    if not meta:
        raise RuntimeError("no encuentro el audio_meta.json de la toma actual")
    bloques = [{"id": b["id"], "texto": b["texto"]}
               for b in (meta.get("bloques") or [])]
    if not bloques:
        raise RuntimeError("la toma no trae bloques que regrabar")
    # LO EDITADO A MANO MANDA sobre lo que se grabo. Aqui se partia del texto de
    # la TOMA, asi que reescribir un bloque a mano y darle a regrabar su tramo
    # volvia a grabar la frase vieja: la unica forma de que la correccion
    # llegara era pedir el guion entero otra vez. Es el mismo cajon y la misma
    # regla que `p4_voz.cargar_guion`.
    bloques = p4.ediciones_a_mano(ctx.proyecto, bloques)
    cfg = p4.resolver_params(p4.params_con_idioma(
        ctx.proyecto, ctx.estado.params("voz") or {}))
    destino = PASOS_MODULOS.comun.preparar_trabajo(ctx.proyecto, "voz")
    # se parte de la toma que hay: se cose sobre ella
    shutil.copy2(os.path.join(carpeta, ficha_voz.get("archivo")
                              or p4.NOMBRE_PISTA),
                 os.path.join(destino, ficha_voz.get("archivo")
                              or p4.NOMBRE_PISTA))
    salidas, nuevos = p4.regrabar_seccion(
        bloques, seccion_id, cfg, meta, destino, peticion=peticion,
        ajuste=ajuste, avisar=avisar, cwd=ctx.proyecto.raiz)

    cambiados = [b["id"] for b, viejo in zip(nuevos, bloques)
                 if b["texto"] != viejo["texto"]]
    if cambiados:
        # al guion, que es de donde bebe todo lo de despues. Con la MISMA forma
        # que escribe y lee la pantalla ({"texto": ...}): se guardaba la cadena
        # pelada, p3 la toleraba, pero la interfaz leia `.texto`, no veia la
        # edicion y la machacaba al primer toque del bloque.
        ediciones = dict((ctx.estado.params("guion") or {}).get("bloques") or {})
        for bloque in nuevos:
            if bloque["id"] in cambiados:
                ediciones[bloque["id"]] = {"texto": bloque["texto"]}
        ctx.estado.actualizar_params("guion", {"bloques": ediciones})
    ctx.bitacora.anotar("seccion_regrabada", "voz", {
        "seccion": seccion_id, "peticion": peticion[:200],
        "bloques_cambiados": cambiados})
    salidas["bloques_cambiados"] = cambiados
    return salidas


def medios_json(ruta):
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _correr_reescribir(avisar, ctx, ids, peticion, ajuste):
    """Reescribe unos bloques del guion por prompt. NO toca el audio.

    Es la otra mitad del microcambio: con la toma hecha, cambiar un bloque es
    reescribir Y regrabar (`regrabar_seccion`); sin toma, es reescribir y ya. El
    cuerpo es el mismo (`p4_voz.reescribir_bloques`), asi que el prompt no puede
    quedarse viejo en uno de los dos caminos.

    Escribe en `params.guion.bloques`, que es el MISMO cajon que una edicion a
    mano: asi el cambio viaja igual --lo aplica `p4_voz.cargar_guion` al grabar
    y `p3_guion` si se vuelve a redactar-- y deja el guion obsoleto por el
    camino normal.
    """
    p4 = PASOS_MODULOS.p4_voz
    documento = PASOS_MODULOS.comun.leer_salida(ctx.proyecto, "guion",
                                                "guion.json", obligatorio=False)
    bloques = [{"id": b["id"], "texto": b["texto"]}
               for b in ((documento or {}).get("guion") or [])]
    if not bloques:
        raise RuntimeError("todavia no hay guion que reescribir")
    # lo que ya se haya editado a mano manda sobre lo que hay en disco: es lo
    # que se esta viendo en la pantalla, y es sobre eso sobre lo que se pide
    editados = (ctx.estado.params("guion") or {}).get("bloques") or {}
    for bloque in bloques:
        ficha = editados.get(bloque["id"])
        texto = ficha.get("texto") if isinstance(ficha, dict) else ficha
        if isinstance(texto, str) and texto.strip():
            bloque["texto"] = texto
    faltan = [b for b in ids if b not in {x["id"] for x in bloques}]
    if faltan:
        raise RuntimeError("el guion no tiene los bloques " + ", ".join(faltan))
    avisar(0.1, f"reescribiendo {', '.join(ids)}")
    nuevos = p4.reescribir_bloques(bloques, ids, peticion, ajuste=ajuste,
                                   cwd=ctx.proyecto.raiz,
                                   motivo=p4.MOTIVO_EDITOR)
    antes = {b["id"]: b["texto"] for b in bloques}
    cambiados = [b["id"] for b in nuevos if b["texto"] != antes.get(b["id"])]
    ediciones = dict(editados)
    for bloque in nuevos:
        if bloque["id"] in cambiados:
            ediciones[bloque["id"]] = {"texto": bloque["texto"]}
    if ediciones != editados:
        ctx.estado.actualizar_params("guion", {"bloques": ediciones})
    ctx.bitacora.anotar("bloques_reescritos", "guion",
                        {"bloques": list(ids), "cambiados": cambiados,
                         "peticion": str(peticion)[:200]})
    avisar(1.0, f"{len(cambiados)} bloque(s) reescrito(s)"
                if cambiados else "el guion se ha quedado igual")
    return {"bloques": list(ids), "bloques_cambiados": cambiados,
            "textos": {b["id"]: b["texto"] for b in nuevos
                       if b["id"] in cambiados},
            "resumen": f"{len(cambiados)} de {len(ids)} bloque(s) cambiados"}


@app.post("/api/proyectos/{pid}/guion/bloques/reescribir", status_code=202)
def reescribir_bloques_guion(pid: str, cuerpo: dict = Body(default=None)):
    """Reescribe unos bloques del guion con una frase. Sin tocar el audio."""
    ctx = contexto(pid)
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    datos = _cuerpo(cuerpo)
    crudos = datos.get("bloques") or ([datos["bloque"]] if datos.get("bloque") else [])
    ids = [str(b).strip().upper() for b in crudos if str(b).strip()]
    if not ids:
        raise ErrorApi(400, "hace falta 'bloque' o 'bloques' con los ids a reescribir")
    peticion = str(datos.get("peticion") or "").strip()
    if not peticion:
        raise ErrorApi(400, "hace falta 'peticion': que hay que cambiar de ese bloque")
    por_fase = CLI_CLAUDE.por_defecto_de("revision_audio")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("reescribir_bloques", _correr_reescribir,
                                   ctx, ids, peticion, ajuste, paso="guion")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "bloques": ids, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/proyectos/{pid}/voz/secciones/{seccion_id}/regrabar",
          status_code=202)
def regrabar_seccion(pid: str, seccion_id: str, cuerpo: dict = Body(default=None)):
    """Regraba una seccion de la toma, con microcambio si se pide."""
    ctx = contexto(pid)
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("revision_audio")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar(
        "regrabar_seccion", _correr_regrabar, ctx, seccion_id,
        str(datos.get("peticion") or ""), ajuste, paso="voz")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "seccion": seccion_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# ==========================================================================
# LA ESTIMACION: cuantas palabras, cuantos planos y cuanto cuesta
#
# UN SOLO SITIO, y por eso es un endpoint y no una cuenta en la pantalla. La
# conversion de segundos a palabras vivio en tres copias --`p2_brief`, el modo
# simulado de la voz y una tabla en `web/app.js`-- y la de la pantalla era
# ademas la que menos sabia: ignoraba la velocidad de la voz y el aire entre
# bloques. Aqui se responde de una vez todo lo que hace falta para decidir una
# duracion: las palabras, la horquilla de vuelta EN SEGUNDOS, cuantos planos
# salen y lo que va a costar.
#
# No necesita proyecto: se pregunta antes de que exista ninguno, que es
# justamente el caso del modo light.
# ==========================================================================

@app.post("/api/estimacion")
def estimar_video(cuerpo: dict = Body(default=None)):
    """Lo que va a salir de esa duracion: palabras, planos y dolares."""
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    datos = _cuerpo(cuerpo)
    p2 = PASOS_MODULOS.p2_brief
    light = PASOS_MODULOS.presets_light

    try:
        segundos = max(p2.DURACION_MINIMA_S,
                       min(p2.DURACION_MAXIMA_S,
                           int(round(float(datos.get("duracion_objetivo_s") or 600)))))
    except (TypeError, ValueError):
        raise ErrorApi(400, "duracion_objetivo_s tiene que ser un numero de segundos")
    idioma = p2.normalizar_idioma(datos.get("idioma")) or "es"
    velocidad = datos.get("velocidad") or "normal"
    try:
        hueco = max(0.0, float(datos.get("hueco_minimo", 1.0)))
    except (TypeError, ValueError):
        hueco = 1.0
    try:
        por_bloque = max(5, int(datos.get("palabras_por_bloque") or 30))
    except (TypeError, ValueError):
        por_bloque = 30
    try:
        tolerancia = float(datos.get("tolerancia", p2.TOLERANCIA_MAXIMA))
    except (TypeError, ValueError):
        tolerancia = p2.TOLERANCIA_MAXIMA

    # LA VOZ ENTRA EN LA CUENTA. La cadencia no es solo del idioma: medido, dos
    # voces inglesas con el mismo modelo dan 2,553 y 1,91 palabras/s a velocidad
    # normal. Con `voz` puesta y tomas suyas medidas, la horquilla deja de ser
    # la del idioma y pasa a ser la de quien va a locutar.
    voz = str(datos.get("voz") or datos.get("voz_id") or "").strip()
    horquilla = p2.horquilla_de(segundos, idioma, tolerancia, velocidad, hueco,
                                por_bloque, voz)

    # CUANTOS PLANOS: la duracion entre la duracion media de un plano, que esta
    # MEDIDA por ritmo. El modo light manda su ritmo; el editor manda la
    # horquilla que tenga escrita en assets y aqui se busca el ritmo parecido.
    if datos.get("ritmo"):
        ficha_ritmo = light.ritmo_de(datos.get("ritmo"))
    else:
        ficha_ritmo = light.ritmo_parecido(datos.get("min_s"), datos.get("max_s"))
    media = max(0.5, float(ficha_ritmo["media_s"]))
    planos = max(1, int(round(segundos / media)))

    calidad = str(datos.get("calidad") or "low").lower()
    usd_imagen = light.USD_POR_IMAGEN.get(calidad, light.USD_POR_IMAGEN["low"])

    imagenes = max(1, planos)

    caracteres = int(round(horquilla["presupuesto_palabras"] * 6.1))
    tarifas = COSTE.tarifas()
    usd_caracter = float(((tarifas.get("tts") or {}).get("usd_por_caracter")) or 0.0)
    usd_tts = round(caracteres * usd_caracter, 4)
    usd_imagenes = round(imagenes * usd_imagen, 3)

    return {
        "duracion_objetivo_s": segundos,
        "idioma": idioma,
        "velocidad": velocidad,
        "voz": voz,
        "hueco_minimo": hueco,
        "cadencia": {"palabras_s": horquilla["palabras_por_segundo"],
                     "origen": horquilla["cadencia_origen"]},
        "palabras": {
            "objetivo": horquilla["presupuesto_palabras"],
            "minimo": horquilla["palabras_minimo"],
            "maximo": horquilla["palabras_maximo"],
            "bloques": max(1, int(round(horquilla["presupuesto_palabras"] / por_bloque))),
            "aire_s": horquilla["aire_s"],
        },
        "segundos": {"minimo": horquilla["segundos_minimo"],
                     "maximo": horquilla["segundos_maximo"],
                     "tolerancia": horquilla["tolerancia"]},
        "planos": {"total": planos, "media_s": round(media, 2),
                   "ritmo": ficha_ritmo["id"],
                   "con_imagen": imagenes},
        "coste": {"imagenes": imagenes, "calidad": calidad,
                  "usd_por_imagen": usd_imagen,
                  "usd_imagenes": usd_imagenes, "usd_tts": usd_tts,
                  "usd_total": round(usd_imagenes + usd_tts, 3)},
    }


@app.get("/api/presets")
def presets_globales():
    """Presets de estilo de locucion."""
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    fichas = PASOS_MODULOS.presets_voz.listar()
    return {"presets": fichas, "total": len(fichas),
            "por_defecto": PASOS_MODULOS.presets_voz.POR_DEFECTO}


# -------------------------------------------------------------------- bitacora

@app.get("/api/proyectos/{pid}/bitacora")
def leer_bitacora(pid: str, paso: str = Query(default=None),
                  unidad: str = Query(default=None),
                  limite: int = Query(default=200)):
    """Historial estructurado del proyecto."""
    ctx = contexto(pid)
    if paso is not None:
        _validar_paso(paso)
    eventos = ctx.bitacora.leer(paso=paso, unidad=unidad,
                                limite=limite if limite and limite > 0 else None)
    return {"proyecto": ctx.id, "eventos": eventos, "total": len(eventos)}


@app.get("/api/proyectos/{pid}/bitacora/llm")
def bitacora_para_llm(pid: str, formato: str = Query(default="json")):
    """Historial en texto navegable, pensado para darselo a un LLM."""
    ctx = contexto(pid)
    texto = ctx.bitacora.resumen_para_llm()
    if str(formato).lower() in ("texto", "text", "plano"):
        return PlainTextResponse(texto, media_type="text/plain; charset=utf-8")
    return {"proyecto": ctx.id, "texto": texto,
            "lineas": len(texto.splitlines()),
            "caracteres": len(texto)}


# -------------------------------------------------------------------- archivos

#: Miniaturas para las rejillas: ancho fijo y cache por ruta+mtime. Viven en
#: la cache del estudio, NUNCA dentro de las carpetas de version: una version
#: es una salida sellada y un derivado colado alli confunde a todo lo que las
#: lee (planos_hechos, la conservacion, las suites).
RUTA_MINIS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "cache", "minis")
ANCHO_MINI = 512


#: Los anchos de miniatura que se sirven. Cerrado a proposito: la cache va por
#: (ruta, mtime, ancho), y admitir cualquier numero seria una cache infinita
#: llenandose de tamanos que nadie vuelve a pedir. 512 es la rejilla y 1024 el
#: repaso del montaje, que es un reproductor y no un icono.
ANCHOS_MINI = (512, 1024)


def _miniatura_de(ruta, ancho=None):
    """JPEG pequeno para una rejilla, o None si no toca (y se sirve el original).

    Una rejilla de 49 planos son 49 PNG de generacion (~2 MB cada uno): por
    movil es media eternidad, y el original solo hace falta en la lupa. La
    mini se cachea por ruta+mtime+ancho, asi que rehacer un plano produce otra.
    Cualquier fallo (PIL ausente, imagen rara) degrada a servir el original.

    El ANCHO se pide: 512 para la rejilla y 1024 para el repaso del montaje, que
    es un reproductor a pantalla y no un icono. Antes el repaso cargaba el
    original de 1536 px y 2 MB por plano, sin cache de navegador y sin precarga:
    cada corte era una descarga entera y el visor se quedaba en negro. Es la
    causa de que "se cuelgue" al repasar.
    """
    if os.path.splitext(ruta)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return None
    ancho = int(ancho or ANCHO_MINI)
    if ancho not in ANCHOS_MINI:
        ancho = ANCHO_MINI
    try:
        if os.path.getsize(ruta) < 150_000:
            return None                    # ya es pequena: reducir no ahorra
        mtime = int(os.path.getmtime(ruta))
        clave = hashlib.sha1(f"{os.path.realpath(ruta)}|{mtime}|{ancho}"
                             .encode("utf-8")).hexdigest()
        destino = os.path.join(RUTA_MINIS, f"{clave}.jpg")
        if os.path.exists(destino):
            return destino
        from PIL import Image  # noqa: PLC0415 - perezoso: sin PIL, original
        imagen = Image.open(ruta).convert("RGB")
        if imagen.width <= ancho:
            return None                    # mas pequena que lo pedido: original
        alto = max(1, round(imagen.height * ancho / max(1, imagen.width)))
        imagen = imagen.resize((ancho, alto), Image.LANCZOS)
        os.makedirs(RUTA_MINIS, exist_ok=True)
        temporal = f"{destino}.{os.getpid()}.tmp"
        imagen.save(temporal, "JPEG", quality=82)
        os.replace(temporal, destino)
        return destino
    except Exception:  # noqa: BLE001
        return None


@app.get("/a/{pid}/{ruta:path}")
def servir_archivo(pid: str, ruta: str, peticion: Request,
                   mini: int = Query(default=0)):
    """Sirve un archivo del proyecto (imagen, wav, svg, mp4) con proteccion.

    Con `?mini=1` una imagen grande se sirve como miniatura JPEG cacheada: es
    lo que cargan las rejillas. La URL de la rejilla lleva ademas `?v=sello`,
    asi que la mini se puede cachear fuerte en el navegador.

    `mini` admite tambien el ANCHO en pixeles (512 o 1024): el repaso del
    montaje es un reproductor, no una rejilla de iconos, y cargar ahi el
    original de 2 MB por plano era lo que dejaba el visor en negro en cada
    corte. Cualquier otro numero cae al de la rejilla.
    """
    ctx = contexto(pid)
    destino = ruta_segura(ctx.proyecto.raiz, ruta)
    if os.path.isdir(destino):
        nombres = sorted(os.listdir(destino))
        return {"directorio": ruta, "entradas": nombres, "total": len(nombres)}
    if not os.path.isfile(destino):
        raise ErrorApi(404, f"no existe: {ruta}")
    if mini:
        reducida = _miniatura_de(destino, mini if mini in ANCHOS_MINI else None)
        if reducida:
            return FileResponse(reducida, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})
    return servir_fichero(peticion, destino)


# ---------------------------------------------------------------------- coste
# El medidor no estima: cada motor reporta lo que consumio al consumirlo y aqui
# solo se suma. La instrumentacion se engancha al importar el servicio, asi que
# cuenta tambien lo que gasten los pasos lanzados desde la API.

from nucleo import capturas as CAPTURAS  # noqa: E402
from nucleo import coste as COSTE  # noqa: E402


@app.exception_handler(CAPTURAS.ErrorCaptura)
async def _manejar_error_captura(peticion, fallo):
    return _respuesta_error(400, str(fallo))


def _instrumentar_coste():
    """Engancha el medidor a los pasos y motores ya cargados."""
    if PASOS_MODULOS is None:
        return {"enganchado": [], "ausente": [f"pasos: {ERROR_PASOS}"], "fecha": ahora()}
    try:
        return COSTE.instrumentar(PASOS_MODULOS)
    except Exception as fallo:  # noqa: BLE001
        # que el medidor falle no puede dejar sin servicio al estudio entero
        return {"enganchado": [], "ausente": [f"{type(fallo).__name__}: {fallo}"],
                "fecha": ahora()}


# Se llama por su EFECTO, y no se guarda lo que devuelve: quien pide el informe
# es la API, y lo lee de COSTE.informe_instrumentacion(), que es la fuente viva.
# Una copia guardada aqui al importar se quedaria vieja en cuanto se enganchase
# algo mas, y sonaria a verdad.
_instrumentar_coste()


def medidor(ctx):
    """Medidor de coste del proyecto."""
    return COSTE.Medidor(ctx.proyecto)


def _sello_fichero(ruta):
    try:
        info = os.stat(ruta)
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return None


@app.get("/api/proyectos/{pid}/coste")
def leer_coste(pid: str):
    """Total del video, desglosado por proveedor, con la linea de cabecera."""
    ctx = contexto(pid)
    ficha = medidor(ctx).total()
    ficha["instrumentacion"] = COSTE.informe_instrumentacion()
    return ficha


@app.get("/api/proyectos/{pid}/coste/por-paso")
def coste_por_paso(pid: str):
    """Desglose por paso del pipeline: que fase se come el presupuesto."""
    return medidor(contexto(pid)).por_paso()


@app.get("/api/proyectos/{pid}/coste/eventos")
def eventos_coste(pid: str, proveedor: str = Query(default=None),
                  paso: str = Query(default=None),
                  unidad: str = Query(default=None),
                  limite: int = Query(default=200)):
    """Detalle de cada consumo, filtrable por proveedor, paso y unidad."""
    ctx = contexto(pid)
    if proveedor and proveedor not in COSTE.PROVEEDORES:
        raise ErrorApi(400, f"proveedor desconocido: {proveedor}. Los proveedores "
                            f"son: {', '.join(COSTE.PROVEEDORES)}")
    if paso:
        _validar_paso(paso)
    eventos = medidor(ctx).eventos(proveedor=proveedor, paso=paso, unidad=unidad,
                                   limite=limite)
    return {"proyecto": ctx.id, "eventos": eventos, "total": len(eventos),
            "filtros": {"proveedor": proveedor, "paso": paso, "unidad": unidad}}


@app.get("/api/proyectos/{pid}/coste/flujo")
async def flujo_coste(pid: str, peticion: Request):
    """Coste en vivo por SSE, para que la cabecera se mueva mientras corre un paso."""
    ctx = contexto(pid)
    contador = medidor(ctx)

    async def flujo():
        sello = object()
        ultimo_latido = time.time()
        while True:
            if await peticion.is_disconnected():
                return
            actual = _sello_fichero(contador.ruta)
            if actual != sello:
                sello = actual
                ultimo_latido = time.time()
                yield _sse("coste", contador.total())
            if time.time() - ultimo_latido > LATIDO_SSE:
                ultimo_latido = time.time()
                yield ": latido\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(flujo(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    })


@app.put("/api/proyectos/{pid}/coste/presupuesto")
def fijar_presupuesto(pid: str, cuerpo: dict = Body(default=None)):
    """Fija el presupuesto en dolares del video (null para quitarlo)."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    if "usd" not in datos and "presupuesto_usd" not in datos:
        raise ErrorApi(400, "hace falta 'usd' con el presupuesto del video")
    valor = datos.get("usd", datos.get("presupuesto_usd"))
    try:
        limite = medidor(ctx).fijar_presupuesto(valor)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    ctx.bitacora.anotar("presupuesto_fijado", None, {"usd": limite})
    return medidor(ctx).total()


@app.get("/api/coste/global")
def coste_global(limite: int = Query(default=0)):
    """Agregado de todos los videos, con el desglose de cada uno."""
    ficha = COSTE.resumen_global(limite=limite)
    ficha["instrumentacion"] = COSTE.informe_instrumentacion()
    return ficha


@app.get("/api/coste/tarifas")
def leer_tarifas():
    """Tabla de tarifas. Vive en un unico sitio: estudio/tarifas.json."""
    return {"tarifas": COSTE.tarifas(refrescar=True), "ruta": COSTE.RUTA_TARIFAS,
            "usd_por_caracter": COSTE.tarifa_caracter()}


@app.put("/api/coste/tarifas")
def escribir_tarifas(cuerpo: dict = Body(default=None)):
    """Actualiza tarifas.json. Sirve para rellenar el precio por caracter."""
    datos = _cuerpo(cuerpo)
    cambios = datos.get("tarifas") if isinstance(datos.get("tarifas"), dict) else datos
    if not cambios:
        raise ErrorApi(400, "no hay nada que cambiar en las tarifas")
    if "usd_por_caracter" in cambios:
        # atajo comodo: lo unico que se rellena a mano es el precio de Cartesia
        cambios = {"tts": {"usd_por_caracter": cambios["usd_por_caracter"]}}
    try:
        tabla = COSTE.guardar_tarifas(cambios)
    except (TypeError, OSError) as fallo:
        raise ErrorApi(400, f"no se han podido guardar las tarifas: {fallo}")
    return {"tarifas": tabla, "usd_por_caracter": COSTE.tarifa_caracter()}


# -------------------------------------------------------- ajustes del CLI
# Los pasos que llaman al CLI de Claude dejan elegir modelo y esfuerzo. Estas
# rutas existen para que esa eleccion sea informada: la lista de opciones sale de
# UN solo sitio (cli_claude), y el tiempo que cuesta cada una sale del historico
# real de todos los proyectos, no de un numero escrito a mano en la interfaz.


@app.get("/api/ajustes-cli")
def ajustes_cli():
    """Catalogo de modelos y esfuerzos, y en que pasos se puede elegir.

    La interfaz ofrecia tres esfuerzos y el backend aceptaba cinco: dos listas
    escritas a mano en sitios distintos se desincronizan solas. Esta es la lista.
    """
    return {
        **CLI_CLAUDE.catalogo(),
        "pasos": list(ESTADISTICAS.PASOS_CON_CLI),
        # Ajuste recomendado de cada fase, con el porque. La interfaz lo ensena
        # y lo usa como valor de partida de sus desplegables, para que elegir
        # otro sea una decision y no un descuido.
        #
        # La union de las dos listas, no solo la de estadisticas: hay fases con
        # ajuste razonado que no llevan historico ('tono', 'voz_descrita'), y
        # dejarlas fuera hacia que su pantalla se anunciara con el defecto
        # general del CLI mientras el backend ejecutaba el de la fase.
        "por_fase": {fase: CLI_CLAUDE.por_defecto_de(fase)
                     for fase in sorted(set(ESTADISTICAS.PASOS_CON_CLI)
                                        | set(CLI_CLAUDE.POR_FASE))},
        "medido": {
            "guion": {"sin_effort_s": 605.8, "con_effort_low_s": 67.0,
                      "nota": "mismo transcript de 9.341 palabras"},
        },
    }


# Cualquier campo de texto de la interfaz se puede rellenar hablando. El audio
# lo graba el navegador y lo transcribe Whisper EN LOCAL (el mismo modelo que
# usa la ingesta cuando un video no trae subtitulos): no sale de esta maquina y
# no cuesta nada por uso, asi que no entra en el medidor de coste.


# ------------------------------------- frames del video como referencia real
# Los fotogramas de la ingesta llevaban ahi desde el principio y solo se miraban.
# Etiquetados con lo que se narraba en su segundo, sirven para que el dibujo de
# una persona o un sitio concreto SE PAREZCA al original en vez de a lo que el
# modelo se imagine.
#
# Etiquetar y proponer son ACCIONES, no pasos del grafo: producen candidatos para
# que una persona decida. Lo que si es parametro (y por tanto invalida assets) es
# la seleccion aprobada, porque cambia las imagenes que se le mandan al generador.


def _frames():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.frames


def _correr_etiquetar_frames(avisar, ctx, ajuste):
    frames = _frames()
    with COSTE.contexto(ctx.proyecto, "ingesta"):
        ficha = frames.etiquetar(ctx.proyecto, modelo=ajuste["modelo"],
                                 esfuerzo=ajuste["esfuerzo"], avisar=avisar,
                                 proyecto_id=ctx.id)
    ctx.bitacora.anotar("frames_etiquetados", "ingesta",
                        {"frames": ficha["total"], "utiles": ficha["utiles"],
                         "ajuste": ajuste})
    return ficha


# ------------------------------------------------- imagenes de estilo
# Las referencias de estilo definen COMO se dibuja. Se pueden sacar de un video
# de YouTube cuyo look guste, que no tiene por que ser el video de referencia
# del proyecto: uno aporta el contenido y el otro el estilo.
#
# Extraer es una ACCION, no un paso del grafo: produce candidatos para que una
# persona elija. Lo que si es parametro (y por tanto invalida assets) es la
# seleccion final, porque cambia las imagenes que se le mandan al generador.


def _estilo():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.estilo


def _correr_extraer_estilo(avisar, ctx, url, maximo):
    estilo = _estilo()
    ficha = estilo.extraer(ctx.proyecto, url, avisar=avisar, maximo=maximo)
    ctx.bitacora.anotar("estilo_extraido", "assets", {
        "url": url, "fotogramas": ficha["total"],
        "utiles": ficha.get("utiles"),
        "propuestos": len(ficha.get("sugeridos") or [])})
    return ficha


# ------------------------------------------------- el tono de las instrucciones
# El gemelo narrativo de las imagenes de estilo: alli se copia COMO SE DIBUJA
# mirando fotogramas, aqui COMO SE CUENTA leyendo las transcripciones de videos
# que ya suenan como quieres. Lo que sale son las instrucciones del guion.

def _tono():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.tono


def _correr_tono(avisar, ctx, urls, ajuste):
    tono = _tono()
    # El idioma sale del BRIEF, que es quien lo fija en el modo editor. Sin
    # esto, un video en ingles recibia unas instrucciones escritas en
    # castellano que ademas le ordenaban redactar en castellano.
    brief = ctx.estado.params("brief") or {}
    ficha = tono.deducir(ctx.proyecto, urls,
                         modelo=(ajuste or {}).get("modelo"),
                         esfuerzo=(ajuste or {}).get("esfuerzo"),
                         avisar=avisar, proyecto_id=ctx.proyecto.id,
                         idioma=_idioma_de_brief(brief))
    # LAS TRANSCRIPCIONES SE QUEDAN PUESTAS, y esto SI escribe params -- al
    # contrario que las instrucciones, que se devuelven para que una persona
    # decida. No es una contradiccion: lo que se decide leyendo es el PARRAFO,
    # que puede estar mejor o peor escrito; las transcripciones son un dato, son
    # de los videos que se acaban de elegir, y dejarlas esperando a un segundo
    # boton es la forma de que nunca lleguen al guion (ver `un-cajon-es-una-promesa`).
    referencias = [f for f in (ficha.get("referencias") or []) if f.get("huella")]
    if referencias:
        ctx.estado.actualizar_params("guion", {"referencias_tono": referencias})
    ctx.bitacora.anotar("tono_deducido", "brief", {
        "videos": len(ficha.get("referencias") or []),
        "palabras": ficha.get("palabras"),
        "referencias_guardadas": len(referencias),
        "avisos": len(ficha.get("avisos") or [])})
    return ficha


@app.get("/api/proyectos/{pid}/estilo")
def leer_estilo(pid: str):
    """Fotogramas ya extraidos y cuales estan elegidos ahora mismo."""
    ctx = contexto(pid)
    estilo = _estilo()
    ficha = estilo.ficha(ctx.proyecto) or {"total": 0, "candidatos": []}
    elegidas = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("referencias") or []
    for candidato in ficha.get("candidatos", []):
        candidato["url"] = url_de(ctx.id, candidato["ruta"], ctx.proyecto.raiz)
        candidato["elegida"] = candidato["ruta"] in elegidas
    ficha["elegidas"] = elegidas
    return ficha


@app.put("/api/proyectos/{pid}/estilo/seleccion")
def elegir_estilo(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda las imagenes de estilo elegidas en los params de assets."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    estilo = _estilo()
    try:
        rutas = estilo.validar_seleccion(datos.get("referencias"))
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    minimo = PASOS_MODULOS.p6_assets.MIN_REFERENCIAS_ESTILO
    tope = PASOS_MODULOS.p6_assets.MAX_REFERENCIAS_ESTILO
    if len(rutas) < minimo:
        raise ErrorApi(400, f"elige al menos {minimo} imagenes de estilo; has "
                            f"mandado {len(rutas)}. Con una o dos, el generador "
                            f"copia esa escena concreta en vez de quedarse con "
                            f"el estilo: hacen falta varias situaciones "
                            f"distintas para que lo unico que puedan tener en "
                            f"comun sea la forma de dibujar")
    if len(rutas) > tope:
        raise ErrorApi(400, f"como mucho {tope} imagenes de estilo; has mandado "
                            f"{len(rutas)}. A cada escena se le adjuntan ademas "
                            f"las hojas de reparto y los dos planos anteriores, "
                            f"y pasado ese punto el estilo compite con ellas por "
                            f"la atencion del modelo")
    actual = dict((ctx.estado.params("assets") or {}).get("estilo") or {})
    actual["referencias"] = rutas
    # se manda el objeto 'estilo' entero: escribir solo 'referencias' lo
    # sustituiria y se perderia el prompt de estilo
    ctx.estado.actualizar_params("assets", {"estilo": actual})
    ctx.bitacora.anotar("estilo_elegido", "assets", {"imagenes": len(rutas)})
    return {"referencias": rutas, "estado": ctx.estado.estado_de("assets"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("assets")}}


def _correr_guia_estilo(avisar, ctx, rutas, ajuste):
    estilo = _estilo()
    guia = estilo.generar_guia(ctx.proyecto, rutas,
                               modelo=ajuste["modelo"],
                               esfuerzo=ajuste["esfuerzo"],
                               avisar=avisar, proyecto_id=ctx.id)
    # La guia es parametro del paso: cambia lo que se le manda al generador, asi
    # que tiene que invalidar assets y lo que cuelga. Es el comportamiento
    # correcto, no un efecto secundario.
    actual = dict((ctx.estado.params("assets") or {}).get("estilo") or {})
    actual["guia"] = guia
    ctx.estado.actualizar_params("assets", {"estilo": actual})
    ctx.bitacora.anotar("guia_estilo", "assets", {
        "fotogramas": len(guia.get("fotogramas") or []),
        "palabras": guia.get("palabras"), "ajuste": ajuste})
    avisar(1.0, f"guia de {guia.get('palabras')} palabras")
    return guia


@app.post("/api/proyectos/{pid}/estilo/guia", status_code=202)
def escribir_guia_estilo(pid: str, cuerpo: dict = Body(default=None)):
    """Escribe la guia de estilo mirando los fotogramas elegidos.

    Es la segunda via del mismo estilo: las imagenes van adjuntas en cada
    llamada, y ademas su descripcion viaja escrita dentro del prompt. Dicho por
    dos caminos, el estilo se mantiene mas estable entre planos.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    estilo = _estilo()
    rutas = datos.get("referencias")
    if not rutas:
        rutas = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("referencias")
    try:
        rutas = estilo.validar_seleccion(rutas)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    minimo = PASOS_MODULOS.p6_assets.MIN_REFERENCIAS_ESTILO
    if len(rutas) < minimo:
        raise ErrorApi(400, f"elige al menos {minimo} fotogramas antes de pedir "
                            f"la guia: con menos se describe una escena, no un "
                            f"estilo")
    ajuste = _ajuste_cli(datos)
    trabajo_id = ctx.gestor.lanzar("guia_estilo", _correr_guia_estilo,
                                   ctx, rutas, ajuste, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


def _catalogo_visual():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.catalogo_visual


def _bloques_del_guion(ctx):
    """Los bloques del guion activo, en orden, con su id y su texto."""
    medios = PASOS_MODULOS.medios
    ruta = medios.salida_de(ctx.proyecto, "guion",
                            claves=("guion",), patrones=(r"guion\.json",))
    documento = medios.leer_json(ruta, {}) if ruta else {}
    bloques = documento.get("bloques_detalle") or documento.get("guion") or []
    limpios = []
    for bloque in bloques:
        if not isinstance(bloque, dict):
            continue
        bid = str(bloque.get("id") or "").strip()
        texto = str(bloque.get("texto") or "").strip()
        if bid and texto:
            limpios.append({"id": bid, "texto": texto,
                            # si el personaje del canal da la cara en este
                            # bloque: lo marca el redactor
                            "personaje": bool(bloque.get("personaje"))})
    return limpios


def _correr_catalogo(avisar, ctx, ajuste, peticion):
    catalogo = _catalogo_visual()
    bloques = _bloques_del_guion(ctx)
    if not bloques:
        raise RuntimeError("no hay guion que leer: genera el guion antes de "
                           "pedir el catalogo visual")
    brief = (ctx.estado.salidas("brief") or {})
    # Cuantos planos van a salir lo decide la duracion de plano, que se elige en
    # la tarjeta de assets y que el catalogo no veia: sin ella, «dos planos por
    # sitio» era una intencion sin aritmetica (ver catalogo.planos_previstos).
    por_defecto = PASOS_MODULOS.p6_assets.PARAMS_POR_DEFECTO
    params = ctx.estado.params("assets") or {}
    min_s = params.get("min_s") or por_defecto["min_s"]
    max_s = params.get("max_s") or por_defecto["max_s"]
    planos = catalogo.planos_previstos(bloques, min_s, max_s)
    # PERO ESA PRESION ES DEL MODELO VIEJO, y en el nuevo hace dano.
    #
    # Pedir un minimo de sitios existia porque en 'por_set' pocos sitios son
    # muchos planos compartiendo sitio, o sea planos que se parecen. En
    # 'por_plano' eso no puede pasar: cada plano trae su caja pase lo que pase.
    # Lo unico que queda del sitio es el RELATO -- la luz, el rotulo que situa, y
    # de quien se toma la continuidad --, y ahi cuantos mas sitios, peor.
    #
    # Con la presion puesta salieron 31 sitios para 48 planos: 1,5 planos por
    # sitio. Y no eran sitios distintos, era el MISMO partido por momentos --
    # 'sala_control_2fa', 'sala_control_sin_mfa', 'sala_control_activacion_mfa';
    # tres sucursales del mismo banco --, que es exactamente lo que el criterio
    # del catalogo prohibe con esas palabras: «un set es un LUGAR, no un plano».
    # Con eso, la referencia de continuidad no se dispara casi nunca (necesita
    # dos planos del mismo sitio) y entra una cabecera de sitio cada plano y
    # medio. O sea que se lleva por delante lo unico que sostenia el
    # reconocimiento del lugar, que ya era la parte fragil de este modo.
    ficha = catalogo.proponer(bloques, brief=brief, ajuste=ajuste,
                              avisar=avisar, proyecto_id=ctx.id,
                              planos=planos, min_s=min_s, max_s=max_s,
                              # los personajes del canal, que entran en el
                              # reparto ya decididos
                              # y como son los personajes en este estilo, para
                              # que el reparto se describa ya convertido
                              regla_personajes=PASOS_MODULOS.p6_assets.regla_de_especie(
                                  params.get("estilo") or {}))
    ctx.bitacora.anotar("catalogo_propuesto", "assets", {
        "personajes": len(ficha.get("reparto") or {}),
        "sets": len(ficha.get("sets") or {}),
        "beats": len(ficha.get("beats") or []),
        "cobertura": ficha.get("cobertura"), "ajuste": ajuste})
    avisar(1.0, f"{len(ficha.get('reparto') or {})} personajes, "
                f"{len(ficha.get('sets') or {})} sitios "
                f"para unos {planos} planos")
    return ficha




@app.post("/api/proyectos/{pid}/catalogo/proponer", status_code=202)
def proponer_catalogo(pid: str, cuerpo: dict = Body(default=None)):
    """Lee el guion ENTERO y propone quien sale, donde y con que tono.

    Proponer no es aprobar: esto no toca los params. Lo que devuelve va a una
    persona, que lo repasa y lo guarda con PUT /catalogo.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    # cada fase trae su ajuste razonado (cli_claude.POR_FASE): el del catalogo
    # es el mismo escalon que el del guion, porque es la misma clase de trabajo
    por_fase = CLI_CLAUDE.por_defecto_de("catalogo_visual")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("catalogo_visual", _correr_catalogo, ctx,
                                   ajuste, str(datos.get("peticion") or ""),
                                   paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.get("/api/proyectos/{pid}/catalogo")
def leer_catalogo(pid: str):
    """El catalogo APROBADO que hay guardado en los params de assets."""
    ctx = contexto(pid)
    guardado = (ctx.estado.params("assets") or {}).get("catalogo") or {}
    return {
        "catalogo": guardado,
        "reparto": guardado.get("reparto") or {},
        "sets": guardado.get("sets") or {},
        "beats": guardado.get("beats") or [],
        "bloques": len(_bloques_del_guion(ctx)) if PASOS_MODULOS else 0,
    }


@app.put("/api/proyectos/{pid}/catalogo")
def guardar_catalogo(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda el catalogo aprobado en los params de assets.

    Es un parametro del paso, asi que guardarlo deja obsoletos los assets y todo
    lo que cuelga. Es lo correcto y no un efecto secundario: con otro reparto o
    con otros sitios, las imagenes son otras.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    catalogo = datos.get("catalogo")
    if not isinstance(catalogo, dict):
        raise ErrorApi(400, "hace falta el objeto 'catalogo'")
    limpio = {
        "reparto": catalogo.get("reparto") or {},
        "sets": catalogo.get("sets") or {},
        "beats": catalogo.get("beats") or [],
    }
    if not limpio["reparto"] and not limpio["sets"]:
        raise ErrorApi(400, "el catalogo llega vacio: sin reparto ni sitios, el "
                            "paso de assets no puede repartir encuadres ni "
                            "mantener a un personaje igual entre planos")
    # Lo que la pantalla no edita se CONSERVA del catalogo guardado: la lista
    # 'reales' (las imagenes de Wikimedia) y la firma del guion las escribe
    # /escenarios. Guardar el catalogo a mano las borraba, y con ellas
    # desaparecian los logos de todos los planos.
    previo = (ctx.estado.params("assets") or {}).get("catalogo") or {}
    for clave in ("reales", "_firma_guion"):
        if clave in previo and clave not in catalogo:
            limpio[clave] = previo[clave]
    ctx.estado.actualizar_params("assets", {"catalogo": limpio})
    ctx.bitacora.anotar("catalogo_guardado", "assets", {
        "personajes": len(limpio["reparto"]), "sets": len(limpio["sets"]),
        "beats": len(limpio["beats"])})
    return {"catalogo": limpio, "estado": ctx.estado.estado_de("assets"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("assets")}}


@app.get("/api/proyectos/{pid}/assets/hechos")
def planos_hechos(pid: str, ligero: int = Query(default=0)):
    """Los planos que hay generados AHORA en la carpeta de trabajo.

    Es lo que permite que la rejilla se llene segun salen --las unidades no se
    sellan hasta que el paso termina, asi que durante toda la tanda no hay otra
    senal-- y, a la vez, que un plano que no se ha generado deje de ensenar la
    imagen de otro que se llamaba igual en el plan anterior.

    Con `ligero=1` cada plano va SIN su `prompt`. No es un ahorro cosmetico:
    el prompt son ~17 KB por plano y en un video de 232 son 3,74 MB de los
    3,88 MB de esta respuesta. Y esta respuesta se pide UNA VEZ POR IMAGEN
    GENERADA mientras corre la tanda, asi que el modo light se estaba bajando
    unos 900 MB por tanda -- para mirar `planos.length` y ordenar por `sello`,
    que es lo unico que usa (refrescarPlanosLight en web/app.js).

    El prompt sigue yendo entero por defecto: la rejilla del editor pinta con el
    el boton de «ver el prompt de esta escena», y ahi si se lee.
    """
    ctx = contexto(pid)
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    try:
        hechos = PASOS_MODULOS.p6_assets.planos_hechos(ctx.proyecto)
    except Exception as fallo:  # noqa: BLE001
        raise ErrorApi(500, f"no se ha podido mirar que planos hay: {fallo}")
    # QUE PLANOS TIENE EL PLAN DE AHORA. La carpeta de trabajo CONSERVA lo de
    # pasadas anteriores --es lo que permite retomar una tanda cortada-- asi que
    # ahi puede haber PNG de planos que el plan de hoy ya no tiene: un corte
    # nuevo deja menos planos, o con otros ids. Quien pregunta necesita poder
    # separar «lo que hay en el disco» de «lo que es de este video», y deducirlo
    # por el nombre del fichero es exactamente lo que esta funcion existe para
    # no hacer.
    if ligero:
        # se rehace el dict en vez de tocar el que devuelve el paso: ese es suyo
        # y sale de su propia lectura, no de una copia que se pueda ensuciar
        hechos = {sid: {k: v for k, v in ficha.items() if k != "prompt"}
                  for sid, ficha in hechos.items()}
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    del_plan = [str(e.get("id")) for e in (plan.get("escenas") or []) if e.get("id")]
    return {"planos": hechos, "total": len(hechos),
            "plan": del_plan,
            "del_plan": len([s for s in del_plan if s in hechos])}


def _moodboard():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.moodboard


def _referencias_de_estilo(ctx):
    estilo = (ctx.estado.params("assets") or {}).get("estilo") or {}
    # reubicar: un proyecto traido de otra maquina guarda rutas de ALLI, y los
    # ficheros estan aqui, en el banco de ahora (ver medios.reubicar)
    rutas = PASOS_MODULOS.medios.reubicar_todas(estilo.get("referencias"))
    return [r for r in rutas if os.path.exists(r)], estilo


@app.get("/api/proyectos/{pid}/moodboard")
def leer_moodboard(pid: str):
    """Las referencias de estilo dibujadas a proposito para este estilo.

    Viven en el banco global y se comparten entre videos: la clave sale de los
    fotogramas elegidos, asi que el segundo video con el mismo estilo no paga.

    Cada eje dice de donde sale su lamina ('banco' si esta aprobada, 'propuesta'
    si esta sin mirar) y con que version, porque rehacer un eje deja la misma
    URL apuntando a otra imagen y sin el sello el navegador ensena la vieja.
    """
    ctx = contexto(pid)
    mod = _moodboard()
    rutas, estilo = _referencias_de_estilo(ctx)
    ficha = mod.ficha_de(rutas)
    clave = ficha.get("clave") or mod.clave_de(rutas)
    hechos = ficha.get("ejes") or {}

    def _eje(eje):
        ruta = hechos.get(eje)
        origen = mod.origen_de(ficha, eje)
        return {
            "eje": eje, "titulo": mod.EJES[eje]["titulo"],
            "hecho": bool(ruta), "origen": origen if ruta else None,
            "aprobado": bool(ruta) and origen == "banco",
            "peticion": (ficha.get("peticiones") or {}).get(eje, ""),
            "url": (f"/api/moodboard/{clave}/{origen}/{eje}.png"
                    f"?v={mod.version_de(ruta)}") if ruta else None,
        }

    return {
        "estado": ficha.get("estado"),
        "clave": clave,
        "referencias": len(rutas),
        "hay_guia": bool((estilo.get("guia") or {}) if isinstance(
            estilo.get("guia"), dict) else estilo.get("guia")),
        "peticiones": ficha.get("peticiones") or {},
        "pendientes": ficha.get("pendientes") or [],
        "coste_usd": ficha.get("coste_usd"),
        "ejes": [_eje(eje) for eje in mod.EJES],
    }


@app.get("/api/moodboard/{clave}/{origen}/{archivo}")
def servir_lamina_moodboard(clave: str, origen: str, archivo: str,
                            peticion: Request, mini: int = Query(default=0)):
    """Sirve una lamina del banco de moodboards, que vive fuera de los proyectos.

    El origen va en la ruta y no se adivina: con un moodboard aprobado y un eje
    recien rehecho existen las dos laminas a la vez, y elegir "la que aparezca
    primero" es como se acaba ensenando la vieja despues de corregir.

    Con `?mini=512` sale la version reducida, que es lo que pide la rejilla:
    esto devolvia el PNG tal cual --1536x1024, `moodboard.TAMANO`-- para pintarlo
    a un tercio de ese tamano, y son seis a la vez. Es exactamente lo que ya
    resolvio la revision de planos, con la misma cache por ruta+mtime+ancho
    (`_miniatura_de`): la lupa sigue teniendo el original, sin `mini`.
    """
    mod = _moodboard()
    try:
        carpeta = mod.carpeta_por_origen(clave, origen)
    except ValueError as fallo:
        raise ErrorApi(404, str(fallo))
    destino = ruta_segura(carpeta, archivo)
    if not os.path.isfile(destino):
        raise ErrorApi(404, f"el moodboard «{clave}» no tiene la lamina "
                            f"{archivo!r} en {origen}")
    if mini:
        reducida = _miniatura_de(destino, mini if mini in ANCHOS_MINI else None)
        if reducida:
            return FileResponse(reducida, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})
    return servir_fichero(peticion, destino)


def _correr_moodboard(avisar, ctx, ejes, peticiones, calidad):
    mod = _moodboard()
    rutas, estilo = _referencias_de_estilo(ctx)
    hecho = mod.generar(rutas, estilo, ejes=ejes, peticiones=peticiones,
                        calidad=calidad, avisar=avisar)
    ctx.bitacora.anotar("moodboard_generado", "assets", hecho)
    return hecho


@app.post("/api/proyectos/{pid}/moodboard", status_code=202)
def generar_moodboard(pid: str, cuerpo: dict = Body(default=None)):
    """Dibuja las laminas de estilo. Quedan PROPUESTAS hasta que alguien las mira.

    Con 'ejes' se rehacen solo esos, y con 'peticiones' se les dice que corregir.
    Es lo que hace util el feedback: en la practica unos ejes salen clavados y
    otros derivan, y rehacerlo entero tiraria los buenos.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    mod = _moodboard()
    rutas, estilo = _referencias_de_estilo(ctx)
    if len(rutas) < 3:
        raise ErrorApi(409, "hacen falta al menos 3 fotogramas de estilo elegidos "
                            "antes de dibujar el moodboard: con menos se copia "
                            "una escena, no un estilo")
    guia = estilo.get("guia")
    if not ((guia.get("guia") if isinstance(guia, dict) else guia)):
        raise ErrorApi(409, "antes hace falta la guia escrita del estilo: es lo "
                            "que le dice al generador COMO se dibuja, y sin ella "
                            "el moodboard sale de lo que el modelo suponga")
    crudos = datos.get("ejes")
    ejes = [e for e in (crudos or []) if e in mod.EJES] or None
    peticiones = {k: str(v).strip() for k, v in (datos.get("peticiones") or {}).items()
                  if k in mod.EJES and str(v).strip()}
    calidad = str(datos.get("calidad") or "medium")
    trabajo_id = ctx.gestor.lanzar("moodboard", _correr_moodboard, ctx, ejes,
                                   peticiones, calidad, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ejes": ejes or sorted(mod.EJES),
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/proyectos/{pid}/moodboard/aprobar")
def aprobar_moodboard(pid: str):
    """Mete el moodboard en el banco del canal. Es la decision de una persona.

    Hasta aqui, el paso de assets sigue usando los fotogramas reales: estas
    laminas las dibujo el mismo modelo que luego las imita, y si derivan del
    estilo original esa deriva se hereda en todo. Eso no se ve leyendo codigo, se
    ve mirandolas.
    """
    ctx = contexto(pid)
    rutas, _estilo = _referencias_de_estilo(ctx)
    try:
        hecho = _moodboard().aprobar(rutas)
    except RuntimeError as fallo:
        raise ErrorApi(409, str(fallo))
    ctx.bitacora.anotar("moodboard_aprobado", "assets", hecho)
    # Es la referencia de estilo de todas las imagenes, asi que cambiarla deja
    # obsoleto lo generado: es lo correcto, no un efecto secundario.
    ctx.estado.invalidar_unidades("assets", [])
    return {**hecho, "estado_paso": ctx.estado.estado_de("assets")}






# --------------------------------------------------------------- escenarios
#
# UN CLIC, y por eso el catalogo dejo de ser un paso.
#
# Antes esto eran dos acciones encadenadas y ninguna se explicaba sola: pedir el
# catalogo visual y repasarlo y guardarlo. Ninguna era una decision del usuario:
# el catalogo APROBADO guarda `reparto`, `sets` y `beats`, o sea quien sale,
# donde y que pasa en cada tramo -- todo deducido del guion, que ya estaba
# escrito. No habia nada que decidir ahi que no estuviera decidido antes.
#
# Asi que el catalogo deja de ser un paso visible y pasa a ser lo que siempre
# fue: deducir del guion quien sale y donde ocurre. Se sigue guardando en
# `params.assets.catalogo` porque p6_assets reparte reparto y sitios leyendolo,
# y porque sigue siendo un parametro legitimo del paso: lo que cambia es que ya
# no hay que pedirlo, mirarlo y guardarlo a mano.


def _firma_del_guion(ctx):
    """Huella del TEXTO del guion. Cambia solo si cambia lo que se dice."""
    try:
        bloques = _bloques_del_guion(ctx) if PASOS_MODULOS else []
    except Exception:  # noqa: BLE001
        return ""
    if not bloques:
        return ""
    crudo = "|".join(f'{b["id"]}:{b["texto"]}' for b in bloques)
    return hashlib.sha256(crudo.encode("utf-8")).hexdigest()[:16]




def _correr_escenarios(avisar, ctx, ajuste_catalogo, peticion, rehacer):
    """Deduce del guion quien sale y donde ocurre."""
    guardado = (ctx.estado.params("assets") or {}).get("catalogo") or {}
    hay = bool(guardado.get("sets") or guardado.get("reparto"))

    def _tramo(desde, ancho):
        """Avisador que mapea el progreso de un sub-paso dentro de su tramo.

        Acepta fraccion None a proposito: un sub-paso puede querer mandar solo
        un MENSAJE, sin tener todavia ningun progreso que dar. Haciendole
        aritmetica a ese None reventaba con «'<' not supported between NoneType
        and float».
        """
        def avisa(fraccion=None, mensaje=""):
            if fraccion is None:
                return avisar(desde, mensaje)
            return avisar(desde + ancho * max(0.0, min(1.0, float(fraccion))),
                          mensaje)
        return avisa

    # SOLO se vuelve a deducir si el guion ha cambiado de verdad.
    #
    # El boton dice «construye los escenarios de mi guion», y la primera version
    # entendia eso como «vuelve a leer el guion siempre». Suena igual y no lo es:
    # el CLI NO nombra los sitios igual dos veces. La misma frase salio una vez
    # como «centro_datos» y a la siguiente como «salon_de_fiestas». Y como los
    # sitios se guardan POR NOMBRE, cada pulsacion orfanaba lo que ya estaba y lo
    # volvia a pedir con otro nombre.
    #
    # La firma es el TEXTO de los bloques: si el guion no ha cambiado, los
    # nombres se quedan quietos y lo construido sigue valiendo.
    firma = _firma_del_guion(ctx)
    cambio = bool(firma) and guardado.get("_firma_guion") != firma
    # Y tambien se vuelve a leer si el catalogo guardado es de ANTES de que el
    # catalogo supiera deducir algo que ahora deduce. La clave 'reales' se
    # escribe siempre desde el 18-08-2026, aunque salga vacia, asi que su
    # AUSENCIA es la senal de que ese catalogo se dedujo con una version que no
    # la conocia. Sin esto, un proyecto en marcha no vuelve a leer el guion
    # nunca -- porque el guion no ha cambiado -- y se queda sin las cosas reales
    # para siempre: el boton decia «ya estaban deducidos» y tenia razon sobre lo
    # que sabia deducir cuando se dedujeron.
    incompleto = hay and "reales" not in guardado
    if incompleto:
        avisar(0.02, "el catalogo se dedujo antes de que existieran las "
                     "imagenes reales: se vuelve a leer el guion")
    elif rehacer and hay and not cambio:
        avisar(0.02, "el guion no ha cambiado: se conservan los sitios ya deducidos")

    if (rehacer and cambio) or incompleto or not hay:
        avisar(0.02, "leyendo el guion para deducir quien sale y donde ocurre")
        ficha = _correr_catalogo(_tramo(0.02, 0.33), ctx, ajuste_catalogo, peticion)
        # Se guarda lo mismo que guardaba el PUT de aprobar: reparto, sitios y
        # beats. Lo demas que propone el catalogo (capitulos, componentes,
        # lugares) ya se descartaba al aprobarlo, asi que aqui tampoco entra --
        # guardarlo ahora seria meter en los params campos que nunca han
        # estado ahi y que p6 no espera encontrar.
        limpio = {"reparto": ficha.get("reparto") or {},
                  "sets": ficha.get("sets") or {},
                  "beats": ficha.get("beats") or [],
                  # Lo que existe de verdad y hay que ENSENAR en vez de
                  # imaginar: de aqui salen las imagenes que se bajan de
                  # Wikimedia Commons (pasos/wikimedia.py). Se quedaba fuera al
                  # guardar, asi que el catalogo lo deducia y se tiraba en la
                  # linea siguiente: la funcion entera no podia funcionar nunca,
                  # y no fallaba -- simplemente no salia ningun logo.
                  "reales": ficha.get("reales") or [],
                  "_firma_guion": firma}
        if not limpio["reparto"] and not limpio["sets"]:
            raise RuntimeError(
                "del guion no ha salido ni un personaje ni un sitio. Sin eso no "
                "hay escenarios que construir ni encuadres que repartir: revisa "
                "que el guion tenga texto y vuelve a intentarlo")
        ctx.estado.actualizar_params("assets", {"catalogo": limpio})
        ctx.bitacora.anotar("catalogo_guardado", "assets", {
            "personajes": len(limpio["reparto"]), "sets": len(limpio["sets"]),
            "beats": len(limpio["beats"]), "automatico": True})
    else:
        avisar(0.35, "los sitios ya estaban deducidos del guion")

    avisar(1.0, "reparto y sitios deducidos del guion: el encuadre de cada "
                "plano va en texto, asi que no hay nada mas que construir")
    return {"construidos": [], "fallidos": [], "ya_estaban": True,
            "previsualizados": [],
            "resumen": "reparto y sitios listos"}


@app.post("/api/proyectos/{pid}/escenarios", status_code=202)
def construir_escenarios(pid: str, cuerpo: dict = Body(default=None)):
    """Un clic: deduce del guion quien sale y donde ocurre."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_catalogo = CLI_CLAUDE.por_defecto_de("catalogo_visual")
    ajuste_catalogo = _ajuste_cli(datos, por_catalogo["modelo"],
                                  por_catalogo["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("escenarios", _correr_escenarios, ctx,
                                   ajuste_catalogo,
                                   str(datos.get("peticion") or ""),
                                   bool(datos.get("rehacer")),
                                   paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste_catalogo,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}








# --------------------------------------------------------------- conservacion
#
# Un cambio en una etapa anterior ya no arrasa lo de despues. Se analiza que se
# puede mantener, se mantiene, y se marca solo lo que es imposible conservar.
#
# El analisis va en dos tiempos a proposito:
#
#   GET  mira el guion y los planos y contesta al instante y gratis. Es lo que
#        se pinta nada mas entrar: cuantos bloques han cambiado y de que manera.
#   POST pregunta al CLI por los planos dudosos -- los que narran algo distinto
#        sin cambiar de asunto- y devuelve el plan definitivo.
#
# Aplicarlo es una tercera accion, y tambien a proposito: conservar es aceptar
# material viejo para entradas nuevas, y eso no puede pasar sin que alguien lo
# haya visto.

def _conservar():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.conservar


def _ficha_conservacion(ficha):
    """Lo que la interfaz necesita, sin los textos completos de cada bloque."""
    bloques = {}
    for bid, b in (ficha.get("bloques") or {}).items():
        bloques[bid] = {k: b.get(k) for k in
                        ("estado", "parecido", "solape", "palabras",
                         "palabras_nuevas")}
        bloques[bid]["antes"] = (b.get("antes") or "")[:400]
        bloques[bid]["despues"] = (b.get("despues") or "")[:400]
    return {**{k: v for k, v in ficha.items() if k not in ("bloques", "dudosos")},
            "bloques": bloques,
            "dudosos": [{"id": d["id"], "bloque": d["bloque"]}
                        for d in (ficha.get("dudosos") or [])]}


@app.get("/api/proyectos/{pid}/conservacion")
def leer_conservacion(pid: str):
    """Que se puede mantener del video, sin llamar a nadie y sin gastar."""
    ctx = contexto(pid)
    ficha = _conservar().plan_del_proyecto(ctx.proyecto, ctx.estado,
                                           preguntar=False)
    return _ficha_conservacion(ficha)


def _correr_conservacion(avisar, ctx, ajuste):
    mod = _conservar()
    ficha = mod.plan_del_proyecto(ctx.proyecto, ctx.estado, ajuste=ajuste,
                                  avisar=avisar, proyecto_id=ctx.id,
                                  cwd=ctx.proyecto.raiz, preguntar=True)
    if not ficha.get("posible"):
        raise RuntimeError(ficha.get("por_que_no") or
                           "no hay material anterior con el que comparar")
    ctx.bitacora.anotar("conservacion_analizada", "assets", {
        "conservar": len(ficha.get("conservar") or []),
        "rehacer": len(ficha.get("rehacer") or []),
        "bloques": ficha.get("resumen_bloques"), "ajuste": ajuste})
    avisar(1.0, ficha.get("resumen") or "análisis listo")
    return _ficha_conservacion(ficha)


@app.post("/api/proyectos/{pid}/conservacion/analizar", status_code=202)
def analizar_conservacion(pid: str, cuerpo: dict = Body(default=None)):
    """Pregunta por los planos dudosos y devuelve el plan definitivo."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("conservacion")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("conservacion", _correr_conservacion, ctx,
                                   ajuste, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/proyectos/{pid}/conservacion/aplicar")
def aplicar_conservacion(pid: str, cuerpo: dict = Body(default=None)):
    """Conserva lo que se puede conservar y marca el resto para rehacer.

    Se aplica el plan que la persona ha visto, no uno recalculado por dentro:
    aplicar algo distinto de lo que estaba en pantalla es la peor forma posible
    de que esto se gane la confianza de nadie.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    plan = datos.get("plan") if isinstance(datos.get("plan"), dict) else None
    if not plan or not plan.get("pasos"):
        raise ErrorApi(400, "hace falta el plan de conservacion que se ha "
                            "revisado (el que devuelve /conservacion/analizar)")
    hecho = _conservar().aplicar(
        ctx.estado, plan, motivo=str(datos.get("motivo") or "")
        or "cambio en el guion analizado plano a plano", quien="persona")
    ctx.bitacora.anotar("conservacion_aplicada", "assets", {
        "conservar": len(plan.get("conservar") or []),
        "rehacer": len(plan.get("rehacer") or []),
        "pasos": {p: len((r or {}).get("conservadas") or [])
                  for p, r in hecho.items()}})
    return {"aplicado": hecho,
            "pasos": {p["id"]: {"estado": ctx.estado.estado_de(p["id"]),
                                "unidades_obsoletas": ctx.estado.unidades_obsoletas(p["id"])}
                      for p in PASOS}}










@app.get("/api/proyectos/{pid}/callouts/diseno")
def leer_diseno(pid: str):
    """Sets de diseno, el elegido y el que sugiere la guia de estilo del video."""
    ctx = contexto(pid)
    p7 = PASOS_MODULOS.p7_callouts if PASOS_MODULOS else None
    if p7 is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    guia = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("guia")
    sugerido, porque = p7.diseno_sugerido(guia)
    elegido, _ = p7.diseno_de(ctx.estado.params("callouts") or {}, guia)
    return {
        "sets": [{"id": k, **v} for k, v in p7.SETS_DISENO.items()],
        "elegido": elegido,
        "sugerido": sugerido,
        "por_que": porque,
        # con los papeles fijados a mano dentro: lo puesto a mano manda y
        # solo se deriva lo que nadie ha tocado
        "paleta": p7.paleta_de_guia(
            guia, {**p7.PARAMS_POR_DEFECTO["paleta"],
                   **(ctx.estado.params("callouts") or {}).get("paleta", {})}),
        "fijados": ((ctx.estado.params("callouts") or {}).get("paleta") or {}).get("fijados") or {},
        # Y el tamano del subtitulo, que es lo unico que queda por elegir del
        # grafismo. Vive en los params de callouts, o sea que cambiarlo no deja
        # obsoleta ni una imagen: solo las capas, que son gratis.
        "subtitulo_tam": (ctx.estado.params("callouts") or {}).get(
            "subtitulo_tam") or "normal",
        "subtitulo_tamanos": sorted(p7.SUB_TAMANOS),
    }




@app.get("/api/proyectos/{pid}/callouts/vista")
def dibujar_capa(pid: str, plano: str = Query(...),
                 capa: str = Query(default="fija")):
    """La capa de ESE plano, dibujada ahora con el código de p7.

    Es lo que hace que el repaso del montaje enseñe los subtítulos ANTES de
    montar las capas: sin esto la única forma de verlos era ejecutar el paso
    entero, o sea después de haber pagado los planos. La misma llamada que
    dibuja el vídeo (`p7.capa_de_escena`), como en `/cartelas/vista`.

    SON DOS CAPAS Y HAY QUE PEDIR CUÁL (PENDIENTE 38):

      capa=fija    la que NO escala, en píxeles del cuadro de salida. Aquí vive
                   el subtítulo, y es la de por defecto porque es la única que
                   este paso dibuja hoy para un plano normal.
      capa=movil   la que va dentro del zoom, en píxeles del lienzo de
                   generación. En un plano normal sale vacía; la llevan la
                   cabecera de capítulo y la cartela, que tienen su propia ruta.

    Y ESTABA ROTA, de antes de esto: llamaba a `capa_de_escena` con la firma
    vieja —la ruta del PNG y el directorio de assets, más un `evitar=` que ya no
    existe—, que es la de cuando esta función buscaba un hueco limpio en la
    imagen para colocar un rótulo. Desde que los rótulos se retiraron
    la firma es otra, así que cada llamada moría en el `except`
    y devolvía un 500: en el repaso del plan no se veía ni un subtítulo, y el
    aviso de «ningún plano lleva subtítulo» culpaba a las marcas de voz.
    """
    ctx = contexto(pid)
    p7 = PASOS_MODULOS.p7_callouts if PASOS_MODULOS else None
    if p7 is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escena = next((e for e in (plan.get("escenas") or [])
                   if e.get("id") == plano), None)
    if escena is None:
        raise ErrorApi(404, f"no hay ningun plano '{plano}' en el plan")
    # el grafismo DECIDIDO manda sobre lo que dedujo p6, igual que en el vídeo:
    # la pantalla no puede enseñar una cosa y el render otra
    params = dict(ctx.estado.params("callouts") or {})
    params.setdefault("estilo", plan.get("estilo") or {})
    try:
        salida = p7.salida_de(plan)
        movil, fija, _ = p7.capa_de_escena(
            escena, p7._con_defectos(params),
            aspecto=float(salida[0]) / float(salida[1]),
            lienzo=p7.lienzo_de(plan), salida=salida)
    except Exception as fallo:  # noqa: BLE001
        raise ErrorApi(500, f"no se ha podido dibujar la capa de {plano}: {fallo}")
    svg = movil if str(capa).strip().lower() == "movil" else fija
    return Response(content=svg, media_type="image/svg+xml")


@app.put("/api/proyectos/{pid}/callouts/plan")
def guardar_plan_callouts(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda el GRAFISMO del video en los params de callouts.

    Ya no guarda ningun plan de rotulos: se retiraron enteros el 22-08
    . Lo que queda es lo que describe el VIDEO -- el set de
    dibujo, la paleta y el tamano del subtitulo -- y por eso va suelto y no por
    unidad. Merece llamarse /callouts/grafismo; la ruta se conserva porque la
    pantalla vieja la sigue usando y renombrarla no arregla nada.

    El plan va al bloque `unidades` y NO a un param suelto: describe UN plano.
    Suelto entraba en la firma global del paso, y guardar el rotulo de S013
    dejaba obsoletos los cuarenta y nueve y el render.
    El set de diseno, la paleta y el tamano del subtitulo van SUELTOS, y a proposito:
    describen el video entero.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    cambios = {}
    hecho = []
    p7 = PASOS_MODULOS.p7_callouts
    if datos.get("subtitulo_tam"):
        # el tamano del subtitulo, que es lo unico que queda por elegir del
        # grafismo. Vive en los params de callouts: cambiarlo no deja obsoleta
        # ni una imagen, solo las capas, que son gratis.
        nombre = str(datos["subtitulo_tam"]).strip().lower()
        if nombre not in p7.SUB_TAMANOS:
            raise ErrorApi(400, f"tamano de subtitulo desconocido: {nombre}. "
                                f"Los tamanos son: {', '.join(sorted(p7.SUB_TAMANOS))}")
        cambios["subtitulo_tam"] = nombre
        hecho.append("subtitulo_tam")
    if datos.get("diseno"):
        if datos["diseno"] not in p7.SETS_DISENO:
            raise ErrorApi(400, f"set de diseno desconocido: {datos['diseno']}. "
                                f"Los sets son: {', '.join(p7.SETS_DISENO)}")
        cambios["diseno"] = datos["diseno"]
    if isinstance(datos.get("arquetipos"), list):
        # contra los VIGENTES: los cinco jubilados el 19-08-2026 se siguen
        # dibujando para los planes ya guardados, pero no se pueden elegir
        vigentes = p7.vigentes()
        desconocidos = [a for a in datos["arquetipos"] if a not in vigentes]
        if desconocidos:
            raise ErrorApi(400, f"arquetipos no disponibles: {', '.join(desconocidos)}. "
                                f"Los que hay son: {', '.join(vigentes)}")
        cambios["arquetipos"] = datos["arquetipos"]
    if isinstance(datos.get("paleta"), dict):
        # Los colores elegidos a mano viajan en 'fijados' DENTRO de la paleta,
        # no sueltos: paleta_de_guia necesita distinguir "esto lo puso alguien"
        # de "esto se derivo", o al volver a derivar se los lleva por delante.
        fijados = {papel: str(color) for papel, color in
                   (datos["paleta"].get("fijados") or {}).items()
                   if papel in p7.PARAMS_POR_DEFECTO["paleta"] and color}
        actual = dict((ctx.estado.params("callouts") or {}).get("paleta")
                      or p7.PARAMS_POR_DEFECTO["paleta"])
        actual["fijados"] = fijados
        cambios["paleta"] = actual
    if not cambios and not hecho:
        raise ErrorApi(400, "hace falta 'diseno', 'paleta' o 'subtitulo_tam'")
    if cambios:
        ctx.estado.actualizar_params("callouts", cambios)
    hecho.extend(cambios)
    ctx.bitacora.anotar("grafismo_guardado", "callouts", {
        "diseno": cambios.get("diseno"),
        "subtitulo_tam": cambios.get("subtitulo_tam")})
    return {"guardado": hecho, "estado": ctx.estado.estado_de("callouts"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("callouts")}}


# ----------------------------------------------------------------- cartelas
# Un plano de texto sobre negro en vez de una imagen (pasos/cartelas.py).
#
# Vive en ASSETS y no en Rotulos aunque sea grafismo, y el motivo es el dinero:
# una cartela cambia el PLAN -- ese plano deja de generar imagen --, asi que
# tiene que estar decidida ANTES de generar. Decidirla en Rotulos, que va
# despues, seria pagar una imagen para tirarla.

def _cartelas():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.cartelas


def _paleta_del_video(ctx):
    """La paleta derivada de la guia de estilo, que es de donde salen los colores
    de los rotulos, de las cartelas y del acento de las transiciones."""
    p7 = PASOS_MODULOS.p7_callouts
    guia = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("guia")
    return p7.paleta_de_guia(
        guia, {**p7.PARAMS_POR_DEFECTO["paleta"],
               **(ctx.estado.params("callouts") or {}).get("paleta", {})})


def _grafismo(ctx):
    """El grafismo del video: la paleta y el set de diseno, de rotulos.

    UN video tiene UN grafismo. El mismo set decide como se envuelve un rotulo
    sobre la imagen y como se escribe una cartela, y la misma paleta tine los
    dos y ademas el acento de las transiciones. Vive en los params de ROTULOS
    porque cambiarlo no cuesta imagenes: rehace capas y render, nada mas.
    """
    p7 = PASOS_MODULOS.p7_callouts
    params = ctx.estado.params("callouts") or {}
    _, diseno = p7.diseno_de({**p7.PARAMS_POR_DEFECTO, **params})
    return _paleta_del_video(ctx), diseno


def _migrar_cartelas(ctx):
    """Mueve el plan de cartelas del param suelto viejo a los ajustes por unidad.

    Nacio como `plan_cartelas`, un param global de assets, y era un error caro:
    todo lo que no es el bloque `unidades` entra en la firma GLOBAL del paso,
    asi que guardar el plan dejaba obsoletos los cuarenta y nueve planos y todos
    los assets. Se veia como «rehago el personaje y sigue saliendo obsoleto».

    Se migra al abrir la pantalla, una vez, y se borra la clave vieja. Borrarla
    mueve la firma una ultima vez -- lo que ya estaba obsoleto sigue estandolo --
    y a partir de ahi cambiar una cartela solo ensucia SU plano.
    """
    params = ctx.estado.params("assets") or {}
    viejo = params.get("plan_cartelas")
    if not isinstance(viejo, dict):
        return False
    nuevos = copy.deepcopy(params)
    nuevos.pop("plan_cartelas", None)
    bloque = nuevos.get("unidades")
    bloque = dict(bloque) if isinstance(bloque, dict) else {}
    for sid, ficha in viejo.items():
        if not isinstance(ficha, dict) or not ficha.get("plantilla"):
            continue
        uid = f"escena:{sid}"
        actual = bloque.get(uid)
        actual = dict(actual) if isinstance(actual, dict) else {}
        # el fondo explicito: las de antes de que existieran los dos son negras
        actual.setdefault("cartela", {**ficha, "fondo": _cartelas().fondo_de(ficha)})
        bloque[uid] = actual
    nuevos["unidades"] = bloque
    ctx.estado.set_params("assets", nuevos)
    return True


def _motor_del_plan(ctx):
    """Con qué versión del motor se cortó el plan activo, y qué se ha perdido.

    Devuelve `None` cuando no hay plan todavía: ahí no hay nada que comparar.
    """
    if PASOS_MODULOS is None:
        return None
    p6 = PASOS_MODULOS.p6_assets
    plan = p6.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    if not plan.get("escenas"):
        return None
    # sin `motor` es un plan de antes de que esto existiera: viejo por defecto
    tenia = int(plan.get("motor") or 1)
    ahora = int(p6.MOTOR_PLAN)
    return {
        "plan": tenia,
        "ahora": ahora,
        "al_dia": tenia >= ahora,
        # QUÉ se ha perdido, no un número: «tienes la 3 y hay la 5» no dice si
        # importa. Lo que importa es qué reglas no lleva este vídeo.
        "cambios": [texto for version, texto in sorted(p6.MOTOR_CAMBIOS.items())
                    if tenia < version <= ahora],
    }


def _plan_de_cartelas(ctx):
    """Las cartelas guardadas, POR UNIDAD: {"S013": {...}}.

    Van en `unidades` y no en un param global porque todo lo que no es ese
    bloque entra en la firma GLOBAL del paso: con el plan suelto, guardar una
    cartela dejaba obsoletos los cuarenta y nueve planos.
    """
    bloque = (ctx.estado.params("assets") or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        ficha = (datos or {}).get("cartela") if isinstance(datos, dict) else None
        if isinstance(ficha, dict) and ficha.get("plantilla"):
            plan[str(uid).split(":", 1)[-1]] = ficha
    return plan


@app.get("/api/proyectos/{pid}/cartelas")
def leer_cartelas(pid: str):
    """Las plantillas de cartela con su muestra dibujada, y el plan guardado."""
    ctx = contexto(pid)
    cartelas = _cartelas()
    migrado = _migrar_cartelas(ctx)
    activas = (ctx.estado.params("callouts") or {}).get("plantillas_cartela") or []
    paleta, diseno = _grafismo(ctx)
    return {
        "plantillas": [{**ficha,
                        "activa": (not activas) or ficha["id"] in set(activas)}
                       for ficha in cartelas.catalogo_plantillas(paleta, diseno)],
        "todas": not activas,
        "plan": _plan_de_cartelas(ctx),
        "migrado": migrado,
        "iconos": sorted(cartelas.ICONOS),
        "fondos": list(cartelas.FONDOS),
        "separacion_minima": cartelas.SEPARACION_MINIMA,
        "fraccion_maxima": cartelas.FRACCION_MAXIMA,
        # CUÁNTAS PALABRAS CABEN EN CADA PLANO, con la MISMA cuenta que después
        # decide si la cartela cabe (`palabras_que_caben`). Va al lado del cajón
        # mientras se escribe: el aviso del informe llega al planificar, y para
        # entonces ya se ha escrito el texto largo (PENDIENTE §15).
        "caben": {e["id"]: cartelas.palabras_que_caben(e.get("duracion"))
                  for e in ((PASOS_MODULOS.p6_assets.plan_actual(
                      ctx.proyecto, "assets", estado=ctx.estado) or {}).get("escenas") or [])
                  if e.get("id")},
        "palabras_maximas": cartelas.palabras_maximas(ctx.estado.params("assets")),
    }


@app.get("/api/proyectos/{pid}/cartelas/vista")
def dibujar_cartela(pid: str, plano: str = Query(...), animada: int = 0):
    """El SVG de la cartela de ESE plano, dibujado ahora con el grafismo de ahora.

    La rejilla de planos lo pide en vez de leer un PNG, y no es un capricho: una
    cartela no deja fichero (ver p6_assets), y si lo dejara habria que rehacerlo
    cada vez que alguien tocara un color. Asi la rejilla ensena exactamente lo
    que va a dibujar p7, porque es la MISMA llamada.
    """
    ctx = contexto(pid)
    cartelas = _cartelas()
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escena = next((e for e in (plan.get("escenas") or [])
                   if e.get("id") == plano), None)
    if escena is None:
        raise ErrorApi(404, f"no hay ningun plano '{plano}' en el plan")
    # MANDA LA DECISION GUARDADA, no la copia que dejo la ultima tanda.
    #
    # `escena["cartela"]` es una FOTO: p6 estampa en plan.json lo que habia
    # decidido cuando corrio (`_marcar_cartelas`). Leerla primero hacia que esta
    # vista ensenara la cartela vieja despues de volver a decidir o de editar el
    # texto a mano -- se escribia otra frase y el dibujo no cambiaba--, que es
    # justo lo que esta llamada existe para que no pase (ver 27.2). La decision
    # esta en params y es lo que dibujara p7 en cuanto se regenere ese plano.
    #
    # Y sin red de reserva: si la decision dice que este plano ya NO es cartela,
    # dibujar la de la foto seria seguir ensenando algo que alguien ha quitado.
    decidido = _plan_de_cartelas(ctx)
    ficha = decidido.get(plano)
    # UNA CONTINUACION NO ES UNA DECISION, ES UNA CONSECUENCIA.
    #
    # Cuando una cartela no cabe en su plano, el PLAN marca los de al lado como
    # su segunda mitad (`cartela.sigue_a`). Eso no esta en params y no tiene por
    # que estarlo: no lo decide nadie, lo deduce la planificacion. Pero la
    # pantalla lo pedia aqui y se llevaba un 404, asi que en la rejilla ese plano
    # salia como «sin imagen» -- y el video iba a enseñar la cartela puesta. Una
    # pantalla que dice una cosa y un video que hace otra es justo lo que esta
    # llamada existe para evitar.
    #
    # Se dibuja la ficha del HOGAR y se lee de params, no del plan: si la persona
    # cambia el texto o quita la cartela, la continuacion cambia o desaparece con
    # ella. La decision sigue mandando; lo unico que sale del plan es a QUIEN
    # sigue este plano.
    sigue_a = str(((escena.get("cartela") or {}) if isinstance(
        escena.get("cartela"), dict) else {}).get("sigue_a") or "")
    if not ficha and sigue_a:
        ficha = decidido.get(sigue_a)
    if not ficha:
        raise ErrorApi(404, f"el plano '{plano}' no lleva cartela")
    paleta, diseno = _grafismo(ctx)
    duracion = float(escena.get("duracion") or 4.0)
    debajo = ""
    if cartelas.fondo_de(ficha) == "imagen":
        # la cartela va ENCIMA del plano: se mete su imagen debajo del velo,
        # servida por la misma ruta que usa la rejilla
        png = os.path.join(ctx.proyecto.ruta_paso("assets"), "escenas",
                           f"{plano}.png")
        url = url_de(ctx.id, png, ctx.proyecto.raiz) if os.path.exists(png) else None
        if url:
            ancho, alto = PASOS_MODULOS.p7_callouts.lienzo_de(plan)
            debajo = (f'<image href="{url}" x="0" y="0" width="{ancho}" '
                      f'height="{alto}" preserveAspectRatio="xMidYMid slice"/>')
    # ANIMADA para el repaso del montaje, quieta para la rejilla.
    #
    # De una cartela hay dos cosas que mirar y se miran en dos sitios: en la
    # rejilla, QUE PONE --y ahi una animacion solo estorba--; en el repaso, si
    # sus palabras entran CUANDO LA VOZ LAS DICE, que es lo unico que no se
    # puede ver en una imagen quieta. Los tiempos son los que calculo el plan
    # (`escritura.tiempos`), o sea exactamente los que va a usar p7; sin ellos
    # --un plan viejo-- se recalculan aqui con los vecinos, que es como los
    # recalcula p7. Una animacion inventada para la pantalla se desincronizaria
    # del render, que es la regla de todas las muestras de esta casa.
    tiempos, escrita = None, False
    if animada:
        escritura = escena.get("escritura") if isinstance(
            escena.get("escritura"), dict) else {}
        escrita = bool(escritura.get("continua")) or bool(sigue_a)
        tiempos = list(escritura.get("tiempos") or [])
        if not tiempos and not escrita:
            antes, despues = cartelas.vecinos_de(plan.get("escenas"), plano)
            tiempos = cartelas.tiempos_dichos(ficha, escena, duracion=duracion,
                                              diseno=diseno, antes=antes,
                                              despues=despues)
    svg = cartelas.svg_carta(ficha, paleta, diseno, duracion=duracion,
                             semilla=plan.get("semilla") or 0, debajo=debajo,
                             tiempos=tiempos or None, animada=bool(animada),
                             escrita=escrita)
    return Response(content=svg, media_type="image/svg+xml")


def _idioma_de_brief(brief):
    """El idioma del video, con respaldo en la clave vieja del eje de idiomas.

    UN VIDEO, UN IDIOMA desde el 24-08-2026. `idiomas_salida`
    ya no se escribe, pero un proyecto guardado antes la trae y su primer codigo
    era el principal: leerla es lo que evita que ese proyecto se abra en otro
    idioma sin que nadie lo diga.
    """
    brief = brief or {}
    codigo = str(brief.get("idioma_salida") or "").strip().lower()
    if codigo:
        return codigo
    lista = brief.get("idiomas_salida") or []
    if isinstance(lista, str):
        lista = [lista]
    return str((list(lista) or ["es"])[0] or "es").strip().lower()


def _idioma_del_video(ctx):
    """El idioma en el que se locuta este video, con su nombre."""
    codigo = _idioma_de_brief(ctx.estado.params("brief") or {})
    p2 = PASOS_MODULOS.p2_brief
    return f"{p2.nombre_idioma(codigo)} ({codigo})"


def _plan_de_planos(ctx, avisar=None):
    """El corte en planos QUE VA A RODAR LA TANDA, replanificado ahora. -> plan

    Las cartelas, la direccion y el redactor deciden ANTES de generar
    —decidirlo despues es pagar una imagen para tirarla— y los tres necesitan el
    corte. Y lo necesitan tal y como va a quedar, no como quedo la ultima vez:
    ver el comentario de dentro.

    En un video recien hecho no hay plan de ninguna clase y la tanda se plantaba
    con «no hay planos todavia», que en el modo editor es un mensaje accionable
    (pulsa el otro boton) y en una tirada de punta a punta es la tanda entera
    caida a la mitad. Por eso, si planificar no da escenas, se corta y se deja
    escrito. Cortar no cuesta nada: son las marcas de palabra de la toma y las
    reglas de ritmo del canal. Ver `p6_assets.cortar`.
    """
    p6 = PASOS_MODULOS.p6_assets
    # SE PLANIFICA DE NUEVO, QUE ES LO QUE VA A HACER LA TANDA.
    #
    # Aqui se leia `plan_actual`, o sea el plan de la ULTIMA version generada, y
    # eso es una foto vieja: `ejecutar` no lo usa, llama a `planificar`. Mientras
    # el plan no cambie da igual; en cuanto cambia --otro catalogo, otro corte, o
    # el propio codigo que reparte los sitios-- lo que se decide aqui describe un
    # video que ya no es el que se va a rodar, y no falla nada: el prompt sale
    # con la descripcion VERBATIM de un sitio y una direccion escrita para otro.
    #
    # Medido el 07-09-2026 en `video_referencia`: con el reparto de beats recien puesto,
    # la direccion se escribio contra el plan de la v2 --S001..S004 los cuatro en
    # `titulares_vacios`-- y la tanda iba a rodarlos en `titulares_vacios`,
    # `bolsa_tranquila`, `cola_banco_vacia` y `monedero_euros`. Tres de cuatro
    # planos con el quiosco escrito dentro de un parque de bolsa.
    #
    # Planificar no cuesta nada --ni un modelo ni una imagen: son las marcas de
    # palabra de la toma y las reglas de ritmo-- y hereda los ids del plan
    # anterior, asi que no mueve la numeracion. Ver `p6_assets.cortar`.
    params = ctx.estado.params("assets") or {}
    try:
        plan = p6.planificar(ctx.proyecto, params) or {}
    except Exception as fallo:
        # NO SE DEJA A NADIE TIRADO. Un video que ya tiene plan pero cuya toma no
        # se puede releer --audio_meta ilegible, la voz movida de sitio-- podia
        # dirigirse antes y tiene que poder seguir dirigiendose: se vuelve al
        # plan guardado, que es exactamente lo que se leia hasta hoy.
        plan = p6.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
        if not plan.get("escenas"):
            raise
        ctx.bitacora.anotar("plan_viejo", "assets",
                            {"porque": f"no se ha podido replanificar: {fallo}",
                             "planos": len(plan.get("escenas") or [])})
        return plan
    if plan.get("escenas"):
        return plan
    if avisar:
        avisar(0.02, "cortando la narracion en planos (no cuesta nada)")
    plan = p6.cortar(ctx.proyecto, params)
    ctx.bitacora.anotar("plan_cortado", "assets",
                        {"planos": len(plan.get("escenas") or []),
                         "porque": "no habia plan todavia"})
    return plan


def _correr_corte(avisar, ctx, replantear=False):
    """Reparte la narracion en planos. No llama a ningun modelo y no cuesta nada.

    Con `replantear` se corta de cero sin heredar los ids del plan anterior, que
    es lo que hace el boton «Regenerar el corte en planos» del modo editor.
    """
    p6 = PASOS_MODULOS.p6_assets
    avisar(0.05, "cortando la narracion en planos")
    plan = p6.cortar(ctx.proyecto, ctx.estado.params("assets") or {},
                     replantear=bool(replantear))
    escenas = plan.get("escenas") or []
    ctx.bitacora.anotar("plan_cortado", "assets", {
        "planos": len(escenas), "replantear": bool(replantear)})
    resumen = f"{len(escenas)} planos"
    avisar(1.0, resumen)
    return {"planos": len(escenas), "resumen": resumen}


def _correr_plan_cartelas(avisar, ctx, ajuste, aplicar=False):
    cartelas = _cartelas()
    assets = ctx.estado.params("assets") or {}
    plan_assets = _plan_de_planos(ctx, avisar)
    escenas = (plan_assets or {}).get("escenas") or []
    if not escenas:
        raise RuntimeError("no hay planos todavia y no se ha podido cortar la "
                           "narracion: comprueba que la voz haya dejado su "
                           "audio_meta.json")
    ficha = cartelas.proponer(
        escenas, params=assets, ajuste=ajuste, avisar=avisar,
        proyecto_id=ctx.id, cwd=ctx.proyecto.raiz,
        titulo=(assets.get("titulo") or ctx.proyecto.id),
        # EL IDIOMA VA EXPLICITO. El prompt esta escrito en castellano porque es
        # para el modelo, y sin decirselo escribia las cartelas en castellano
        # tambien: un video en ingles salio con «de la facturacion anual
        # global» y «DIAS / ANOS» en pantalla.
        idioma=_idioma_del_video(ctx),
        plantillas=(ctx.estado.params("callouts") or {}).get("plantillas_cartela"))
    ctx.bitacora.anotar("plan_cartelas", "assets", {
        "planos": ficha.get("planos"), "cartelas": ficha.get("cartelas"),
        "propuestas": ficha.get("propuestas"), "ajuste": ajuste,
        "aplicar": bool(aplicar)})
    # Igual que el plan de rotulos: desde una receta se aplica, o la tanda paga
    # la llamada y sigue como si no hubiera pasado nada.
    if aplicar and isinstance(ficha.get("plan"), dict):
        _guardar_cartelas_por_unidad(ctx, cartelas, ficha["plan"])
        ficha["aplicado"] = True
        # Y SE VUELVE A CORTAR, que no cuesta nada. Una cartela FUNDE su tramo
        # en un solo plano mas largo (`p6._fundir_cartelas`), asi que el corte
        # de antes ya no describe este video: tiene mas planos y con otros ids.
        # Lo que viene detras --la direccion de cada plano y las piezas-- decide
        # POR PLANO, asi que leyendo el corte viejo escribiria la direccion de
        # S054 sobre lo que despues es otro plano. No da error: da un video en
        # el que las descripciones estan corridas.
        plan = PASOS_MODULOS.p6_assets.cortar(
            ctx.proyecto, ctx.estado.params("assets") or {})
        ficha["planos_tras_cartelas"] = len(plan.get("escenas") or [])
        avisar(0.98, f"{ficha['planos_tras_cartelas']} planos tras fundir las "
                     f"cartelas")
    avisar(1.0, f"{ficha.get('cartelas')} de {ficha.get('planos')} planos "
                f"serían cartela")
    return ficha


@app.post("/api/proyectos/{pid}/cartelas/plan", status_code=202)
def proponer_plan_cartelas(pid: str, cuerpo: dict = Body(default=None)):
    """Lee el guion y decide que tramos se cuentan mejor con texto que con dibujo.

    Proponer no es aprobar: lo que devuelve se repasa y se guarda con PUT.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("plan_cartelas")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("plan_cartelas", _correr_plan_cartelas, ctx,
                                   ajuste, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


def _guardar_cartelas_por_unidad(ctx, cartelas, plan):
    """Escribe el plan de cartelas en `unidades` de assets, fusionando.

    Sale del endpoint para poder llamarlo tambien desde la RECETA: proponer sin
    guardar es pagarle al modelo y tirar la respuesta, que es lo que pasaria si
    la tanda de una pestana solo propusiera.
    """
    # CONTRA QUE TEXTO SE DECIDE CADA UNA. El plan se guarda por unidad y el id
    # de un plano es su POSICION: se reparte de nuevo con cada corte, asi que sin
    # esto una cartela se queda en su numero mientras lo que ahi se dice se ha
    # ido a otro sitio. Paso con las siete de `video_referencia`: decididas sobre el
    # plan v1, sesenta y siete versiones despues «TIPO DE INTERES REAL» salia
    # tres planos antes de que se dijera.
    dice = {}
    try:
        actual = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
        dice = {e.get("id"): (e.get("narracion") or "")
                for e in (actual.get("escenas") or []) if e.get("id")}
    except Exception:                                         # noqa: BLE001
        dice = {}        # sin plan no hay ancla; se guarda igual, por su numero
    limpio = {}
    for sid, ficha in plan.items():
        if not isinstance(ficha, dict):
            continue
        plantilla = str(ficha.get("plantilla") or "")
        if plantilla not in cartelas.PLANTILLAS:
            raise ErrorApi(400, f"plantilla de cartela desconocida: "
                                f"{plantilla}. Las que hay son: "
                                f"{', '.join(cartelas.PLANTILLAS)}")
        # Se valida al GUARDAR y no al dibujar: una cartela con un texto de
        # mas se recorta, y ese aviso tiene que salir aqui -- con el id del
        # plano delante -- y no aparecer como una cartela con la letra rara
        # que nadie sabe por que salio asi.
        # con los params del video: el presupuesto de palabras de una cartela
        # cuelga de lo que duran SUS planos (cartelas.techo_de)
        valores, avisos = cartelas.validar(plantilla, ficha.get("datos"),
                                           ctx.estado.params("assets"))
        if valores is None:
            raise ErrorApi(400, f"{sid}: {'; '.join(avisos)}")
        limpio[sid] = {"plantilla": plantilla,
                       "fondo": cartelas.fondo_de(ficha),
                       "datos": valores,
                       "ancla": dice.get(sid, ""),
                       "por_que": str(ficha.get("por_que") or "").strip()}
    # se escribe el plan ENTERO: los planos que ya no salen se quedan sin
    # cartela, o quitar una desde la pantalla no la quitaria de ningun sitio
    antes = _plan_de_cartelas(ctx)
    # SE FUSIONA con lo que ya tenga cada unidad. `actualizar_params`
    # sustituye el diccionario de la unidad entero, asi que escribir solo
    # {"cartela": ...} se llevaria por delante el feedback de ese plano, sus
    # zonas marcadas y su carta forzada. Es la clase de perdida que no da
    # ningun error: la nota simplemente deja de estar.
    previos = (ctx.estado.params("assets") or {}).get("unidades") or {}
    bloque = {}
    for sid in set(limpio) | set(antes):
        uid = f"escena:{sid}"
        actual = previos.get(uid)
        actual = dict(actual) if isinstance(actual, dict) else {}
        if sid in limpio:
            actual["cartela"] = limpio[sid]
        else:
            actual.pop("cartela", None)
        bloque[uid] = actual
    ctx.estado.actualizar_params("assets", {"unidades": bloque})
    return len(limpio)


@app.put("/api/proyectos/{pid}/cartelas")
def guardar_cartelas(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda que planos son cartela (POR UNIDAD) y que plantillas se pueden usar.

    El plan va al bloque `unidades` de assets y NO a un param suelto. Todo lo
    que no es ese bloque entra en la firma GLOBAL del paso, asi que con el plan
    suelto guardar una cartela dejaba obsoletos los cuarenta y nueve planos y
    todos los assets: decidir una cartela pedia regenerar el video entero. Por
    unidad, convertir S013 en cartela ensucia S013 y nada mas.

    Y las plantillas permitidas van a los params de ROTULOS, con el resto del
    grafismo: solo limitan lo que puede elegir el agente la proxima vez, asi que
    no tienen por que ensuciar una sola imagen.
    """
    ctx = contexto(pid)
    cartelas = _cartelas()
    datos = _cuerpo(cuerpo)
    hecho = []
    if isinstance(datos.get("plan"), dict):
        _guardar_cartelas_por_unidad(ctx, cartelas, datos["plan"])
        hecho.append("plan")
    if isinstance(datos.get("plantillas"), list):
        desconocidas = [t for t in datos["plantillas"]
                        if t not in cartelas.PLANTILLAS]
        if desconocidas:
            raise ErrorApi(400, f"plantillas desconocidas: {', '.join(desconocidas)}. "
                                f"Las que hay son: {', '.join(cartelas.PLANTILLAS)}")
        ctx.estado.actualizar_params(
            "callouts", {"plantillas_cartela": list(datos["plantillas"])})
        hecho.append("plantillas")
    if not hecho:
        raise ErrorApi(400, "hace falta 'plan' o 'plantillas'")
    ctx.bitacora.anotar("plan_cartelas_guardado", "assets", {
        "cartelas": len(_plan_de_cartelas(ctx))})
    return {"guardado": hecho, "estado": ctx.estado.estado_de("assets"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("assets")}}


# ------------------------------------------------------------- dirección
# QUÉ SE VE EN CADA PLANO. La capa que faltaba: el sitio es el mismo para todos
# los planos rodados ahí y la acción del tramo es la misma para todo su bloque,
# así que dos planos seguidos recibían casi el mismo encargo (medido: 852 de
# 1.280 caracteres idénticos). Ver `pasos/direccion.py`.
#
# Va POR UNIDAD, como las cartelas y por lo mismo: escribir la dirección de un
# plano ensucia ESE plano, no los cuarenta y nueve.


def _direccion():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.direccion


def _plan_de_direccion(ctx):
    """Lo dirigido, POR UNIDAD: {"S013": "a hand covers the screen"}."""
    bloque = (ctx.estado.params("assets") or {}).get("unidades") or {}
    plan = {}
    for uid, datos in bloque.items():
        linea = (datos or {}).get("direccion") if isinstance(datos, dict) else None
        linea = " ".join(str(linea or "").split())
        if linea:
            plan[str(uid).split(":", 1)[-1]] = linea
    return plan


@app.get("/api/proyectos/{pid}/direccion")
def leer_direccion(pid: str):
    """Qué se ve en cada plano: lo dirigido, y los planos que lo admiten."""
    ctx = contexto(pid)
    direccion = _direccion()
    plan_assets = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan_assets.get("escenas") or []
    plan = _plan_de_direccion(ctx)
    dirigibles = [e for e in escenas if direccion.dirigible(e)]
    return {
        "plan": plan,
        "planos": [{"id": e["id"], "set": e.get("set") or e.get("componente"),
                    "personajes": e.get("personajes") or [],
                    "narracion": e.get("narracion") or "",
                    "direccion": plan.get(e["id"], "")}
                   for e in dirigibles],
        "dirigibles": len(dirigibles),
        "total": len(escenas),
        "palabras_maximas": direccion.PALABRAS_MAXIMAS,
        "repetidas": direccion.repetidas(plan, dirigibles),
        "resumen": direccion.describir(plan, dirigibles),
    }


def _guardar_direccion_por_unidad(ctx, plan):
    """Escribe la dirección en `unidades` de assets, FUSIONANDO.

    `actualizar_params` sustituye el diccionario de la unidad entero, así que
    escribir sólo {"direccion": ...} se llevaría por delante la cartela de ese
    plano, su feedback y sus zonas marcadas. Es la misma trampa que ya costó una
    ronda con las cartelas, y no da ningún error: la nota deja de estar.
    """
    direccion = _direccion()
    limpio, avisos = {}, []
    for sid, texto in (plan or {}).items():
        sid = str(sid).strip().upper()
        if not str(texto or "").strip():
            continue                       # vacío = quitarla
        linea, motivo = direccion.limpiar_linea(texto)
        if linea is None:
            raise ErrorApi(400, f"{sid}: {motivo}")
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        limpio[sid] = linea
    antes = _plan_de_direccion(ctx)
    previos = (ctx.estado.params("assets") or {}).get("unidades") or {}
    bloque = {}
    for sid in set(limpio) | set(antes):
        uid = f"escena:{sid}"
        actual = previos.get(uid)
        actual = dict(actual) if isinstance(actual, dict) else {}
        if sid in limpio:
            actual["direccion"] = limpio[sid]
        else:
            actual.pop("direccion", None)
        bloque[uid] = actual
    ctx.estado.actualizar_params("assets", {"unidades": bloque})
    return len(limpio), avisos


@app.put("/api/proyectos/{pid}/direccion")
def guardar_direccion(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda qué se ve en cada plano. Un texto vacío la quita."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    if not isinstance(datos.get("plan"), dict):
        raise ErrorApi(400, "hace falta 'plan': {id de plano: qué se ve}")
    cuantas, avisos = _guardar_direccion_por_unidad(ctx, datos["plan"])
    ctx.bitacora.anotar("direccion_guardada", "assets", {"planos": cuantas})
    return {"guardado": cuantas, "avisos": avisos,
            "estado": ctx.estado.estado_de("assets"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("assets")}}


def _redactor():
    """El módulo que escribe el prompt entero de cada plano.

    La guarda es la MISMA que la de `_direccion`, escrita a mano: aqui habia una
    llamada a un `_exigir_pasos()` que no existe en este fichero, asi que el
    redactor entero se caia con un NameError antes de leer un solo plano.
    """
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.redactor


def _guardar_redactado_por_unidad(ctx, plan):
    """Escribe el prompt redactado en `unidades` de assets, FUSIONANDO.

    Misma trampa y mismo cuidado que `_guardar_direccion_por_unidad`:
    `actualizar_params` sustituye el diccionario de la unidad entero, así que
    escribir sólo el prompt se llevaría por delante la cartela de ese plano.

    Son DOS claves: `redactado` (el párrafo) y `redactado_set` (el sitio que
    eligió). La segunda se escribe siempre que haya párrafo, incluso vacía, y
    eso es a propósito: vacía significa «este plano se inventó su sitio y no le
    toca continuidad de nadie», que no es lo mismo que «no opinó».
    """
    redactor = _redactor()
    limpio, avisos = {}, []
    for sid, ficha in (plan or {}).items():
        sid = str(sid).strip().upper()
        if isinstance(ficha, dict) and not str(ficha.get("prompt") or "").strip():
            continue                       # vacío = quitarlo
        limpia, motivo = redactor.limpiar_ficha(ficha)
        if limpia is None:
            raise ErrorApi(400, f"{sid}: {motivo}")
        if motivo:
            avisos.append(f"{sid}: {motivo}")
        limpio[sid] = limpia
    previos = (ctx.estado.params("assets") or {}).get("unidades") or {}
    antes = {uid.split(":", 1)[1] for uid, ficha in previos.items()
             if uid.startswith("escena:") and isinstance(ficha, dict)
             and ficha.get("redactado")}
    bloque = {}
    for sid in set(limpio) | antes:
        uid = f"escena:{sid}"
        actual = previos.get(uid)
        actual = dict(actual) if isinstance(actual, dict) else {}
        if sid in limpio:
            actual["redactado"] = limpio[sid]["prompt"]
            actual["redactado_set"] = limpio[sid]["set"]
        else:
            actual.pop("redactado", None)
            actual.pop("redactado_set", None)
        bloque[uid] = actual
    ctx.estado.actualizar_params("assets", {"unidades": bloque})
    return len(limpio), avisos


@app.put("/api/proyectos/{pid}/redactor")
def guardar_redactado(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda el prompt escrito de cada plano. Un prompt vacío lo quita."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    if not isinstance(datos.get("plan"), dict):
        raise ErrorApi(400, "hace falta 'plan': {id de plano: {set, prompt}}")
    cuantas, avisos = _guardar_redactado_por_unidad(ctx, datos["plan"])
    ctx.bitacora.anotar("redactor_guardado", "assets", {"planos": cuantas})
    return {"guardado": cuantas, "avisos": avisos,
            "estado": ctx.estado.estado_de("assets"),
            "aguas_abajo": {h: ctx.estado.unidades_obsoletas(h)
                            for h in descendientes_de("assets")}}


def _correr_redactor(avisar, ctx, ajuste, aplicar=False):
    """Escribe el encargo entero de cada plano, con TODO el vídeo delante."""
    redactor = _redactor()
    assets = ctx.estado.params("assets") or {}
    plan_assets = _plan_de_planos(ctx, avisar)
    escenas = (plan_assets or {}).get("escenas") or []
    if not escenas:
        raise RuntimeError("no hay planos todavía: corta la narración antes")
    # LO QUE SU TRAMO PONE A MANO. Es la diferencia con `direccion`: el agente
    # no recibe UN sitio ya decidido por el código, recibe los que el director
    # de arte escribió para ese trozo del guion y elige el que va con la frase.
    opciones, catalogo = PASOS_MODULOS.p6_assets.opciones_de_tramo(
        ctx.proyecto, assets, escenas)
    for escena, beats in zip(escenas, opciones):
        escena["_sitios"] = [b.get("set") for b in beats if b.get("set")]
        escena["_acciones"] = [b.get("accion") for b in beats if b.get("accion")]
    ficha = redactor.proponer(
        escenas, ajuste=ajuste, avisar=avisar, proyecto_id=ctx.id,
        titulo=(assets.get("titulo") or ctx.proyecto.id),
        estilo=(assets.get("estilo") or (plan_assets or {}).get("estilo") or {}),
        # EL IDIOMA VA EXPLICITO, igual que en el plan de cartelas y por lo
        # mismo: lo que el agente escribe ENTRE COMILLAS lo dibuja el generador
        # tal cual, y sin este dato lo escribe en el idioma del ejemplo que
        # tenga delante. Ver `_ultima_palabra_idioma` en p6_assets.
        idioma=_idioma_del_video(ctx),
        catalogo=catalogo)
    ctx.bitacora.anotar("redactor", "assets", {
        "planos": ficha.get("planos"), "redactados": ficha.get("redactados"),
        "ajuste": ajuste, "aplicar": bool(aplicar)})
    if aplicar and isinstance(ficha.get("plan"), dict):
        _guardar_redactado_por_unidad(ctx, ficha["plan"])
        ficha["aplicado"] = True
    avisar(1.0, f"{ficha.get('redactados')} de {ficha.get('planos')} planos escritos")
    return ficha


@app.post("/api/proyectos/{pid}/redactor/proponer", status_code=202)
def proponer_redactado(pid: str, cuerpo: dict = Body(default=None)):
    """Escribe el prompt de cada plano, con TODOS los planos delante de una vez."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("redactor")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("redactor", _correr_redactor, ctx, ajuste,
                                   paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


def _correr_direccion(avisar, ctx, ajuste, aplicar=False):
    direccion = _direccion()
    assets = ctx.estado.params("assets") or {}
    plan_assets = _plan_de_planos(ctx, avisar)
    escenas = (plan_assets or {}).get("escenas") or []
    if not escenas:
        raise RuntimeError("no hay planos todavía y no se ha podido cortar la "
                           "narración: comprueba que la voz haya dejado su "
                           "audio_meta.json")
    # TODO EL CONTEXTO DE UNA VEZ: el estilo tal y como lo recibe el modelo de
    # imagen, los sitios con su descripción literal, el reparto y la acción del
    # tramo de cada plano. Es lo que le permite escribir SABIENDO cómo se va a
    # dibujar, en vez de adivinar — y lo que hace que pueda no contradecirlo.
    ficha = direccion.proponer(
        escenas, ajuste=ajuste, avisar=avisar, proyecto_id=ctx.id,
        titulo=(assets.get("titulo") or ctx.proyecto.id),
        estilo=(assets.get("estilo") or (plan_assets or {}).get("estilo") or {}),
        # EL IDIOMA VA EXPLICITO. Sin el, `direccion` escribia los rotulos en el
        # idioma de su unico ejemplo, que estaba en ingles: en `video_referencia`
        # (07-09-2026) pidio catorce rotulos en ingles --"CITY OPENS NEW PARK",
        # "BANK", "SAVINGS"-- para un video en castellano, y el generador los
        # dibujo. Es el mismo dato que ya recibia el plan de cartelas, y por el
        # mismo motivo.
        idioma=_idioma_del_video(ctx),
        catalogo=(assets.get("catalogo")
                  or (plan_assets or {}).get("catalogo") or {}),
        beats=(plan_assets or {}).get("beats"))
    ctx.bitacora.anotar("direccion", "assets", {
        "planos": ficha.get("planos"), "dirigidos": ficha.get("dirigidos"),
        "ajuste": ajuste, "aplicar": bool(aplicar)})
    # Desde una receta se APLICA, o la tanda paga la llamada y sigue como si no
    # hubiera pasado nada. Es la misma regla que el plan de cartelas.
    if aplicar and isinstance(ficha.get("plan"), dict):
        _guardar_direccion_por_unidad(ctx, ficha["plan"])
        ficha["aplicado"] = True
    avisar(1.0, f"{ficha.get('dirigidos')} de {ficha.get('planos')} planos dirigidos")
    return ficha


@app.post("/api/proyectos/{pid}/direccion/proponer", status_code=202)
def proponer_direccion(pid: str, cuerpo: dict = Body(default=None)):
    """Escribe qué se ve en cada plano, con TODOS los planos delante de una vez.

    De una vez y no plano a plano: el trabajo es que cada plano se distinga del
    de al lado, y eso es comparar. Sin ver el vecino, cuarenta y nueve respuestas
    razonables y repetidas.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("direccion")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    trabajo_id = ctx.gestor.lanzar("direccion", _correr_direccion, ctx, ajuste,
                                   paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# LAS IMÁGENES YA NO SE MIRAN SOLAS. Aquí vivía `mirar`: un agente que abría
# los cuarenta y nueve PNG uno a uno y decía cuál tenía manos raras, el logo
# equivocado o una escena que no era la pedida. Se retiró el 24-08-2026 por
# decisión del canal, con su módulo, su tarea de receta, su ajuste del CLI y su
# pantalla. No cambiaba nada de lo que salía: señalaba, y decidir qué hacer con
# lo señalado ya tenía su botón.
#
# Lo que hace que las imágenes salgan bien sigue en pie y es lo de antes de
# generarlas: la guía de estilo, las referencias, y sobre todo `direccion`, que
# escribe qué se ve en CADA plano con el vídeo entero delante.


def _carpeta_de_escenas(ctx):
    return os.path.join(ctx.proyecto.ruta_paso("assets"), "escenas")


# ----------------------------------------- el previsualizador escena a escena
#
# AQUI VIVIA LA REVISION DE LOS PLANOS CON IA, y esto es lo que la sustituye.
#
# Aquella abria los PNG con un modelo, decidia cuales contradecian el relato y
# rehacia esos. Miraba bien y era barata de mirar, pero se comia el reloj -- una
# llamada por cada seis planos, treinta y seis en un video normal -- y sobre
# todo decidia SOLA sobre lo unico que no deberia decidir sola: que se ve.
#
# Lo que entra en su lugar no es otro agente: es una PANTALLA. Se ve el video
# antes de montarlo, plano a plano y al ritmo de quien mira, con el audio de esa
# escena sonando y un cuadro de feedback debajo.
#
# ESTE ENDPOINT NO MONTA NADA, y ahi esta la gracia. Devuelve las piezas
# sueltas --la imagen, sus dos capas vectoriales y donde empieza y acaba su
# audio-- y quien las junta es el navegador. Que ademas las junta MEJOR que el
# render para esto: el subtitulo es texto de verdad y no pixeles quemados, y
# cambiar de escena es mover el `currentTime` de un <audio>, no cortar un wav.
#
# LO QUE NO VA, y es la mitad del encargo: ni el movimiento de camara
# (`movimiento/{id}.json`) ni las transiciones. Se mira UNA imagen quieta con su
# audio. El zoom y los cortes se ven en el MP4, que es donde importan.


def _ruta_de_version(ctx, paso, *partes):
    """`pasos/assets/v3/escenas/S001.png`, o None si ese paso no tiene version.

    La misma forma que arma la interfaz (`rutaVersion` en app.js) y que entiende
    `GET /a/{pid}/{ruta}`: relativa al proyecto y con barras normales.
    """
    version = ctx.proyecto.version_activa(paso)
    if not version:
        return None
    ruta = os.path.join(ctx.proyecto.ruta_paso(paso, version), *partes)
    if not os.path.exists(ruta):
        return None
    return "/".join(["pasos", paso, f"v{int(version)}"] + list(partes))


def _ficha_de_escena(ctx, sid):
    """La ficha del dibujo de un plano: para QUE texto se dibujo, y su ruta."""
    version = ctx.proyecto.version_activa("assets")
    if not version:
        return {}
    ruta = os.path.join(ctx.proyecto.ruta_paso("assets", version),
                        "escenas", f"{sid}.json")
    return PASOS_MODULOS.medios.leer_json(ruta, {}) or {}


def _obsolescencia(ctx, escena):
    """Si el dibujo de este plano ya no es de lo que el plano dice. -> {}

    SE CALCULA AL MIRAR, no al generar. El texto de un plano cambia cuando se
    reescribe el guion o cuando se vuelve a cortar la narracion, y las dos cosas
    pasan sin que nadie vuelva a pasar por el paso de imagenes: preguntarlo solo
    al dibujar seria preguntarlo cuando todavia estaba bien.

    Y OBSOLETO NO ES PENDIENTE: la imagen se queda, no se rehace sola y no se
    cobra. Lo unico que hace esto es DECIRLO, para que lo decida quien mira
    .
    """
    p6 = PASOS_MODULOS.p6_assets
    ficha = _ficha_de_escena(ctx, str(escena.get("id") or ""))
    if not ficha:
        return {}
    dibujada = p6._texto_clave(ficha)
    dice = p6._texto_clave(escena)
    if not dibujada or not dice or p6._mismo_dicho(dibujada, dice):
        return {}
    # EL DESCARTE SE RECUERDA CONTRA UN TEXTO. Quitar la tarjeta es decir «este
    # dibujo me vale para lo que dice AHORA»; guardarlo como un si o un no haria
    # que la proxima vez que cambiara la frase siguiera aprobado.
    if PASOS_MODULOS.medios.normalizar_texto(ficha.get("vale_para") or "") == dice:
        return {}
    return {"obsoleta": True, "dibujada_para": ficha.get("narracion") or ""}

def _audio_de_la_toma(ctx):
    """El wav que se oye: el de la revision si la hay, y si no el de la voz.

    En ese orden y no al reves: `revision_audio` es el paso que puede haber
    regrabado una seccion, asi que su toma es la que de verdad va a sonar en el
    MP4. Coger la de `voz` daria a escuchar algo que ya no existe.
    """
    for paso in ("revision_audio", "voz"):
        ruta = _ruta_de_version(ctx, paso, "narracion.wav")
        if ruta:
            return ruta
    return None


def _medidor_de_subtitulo(ctx, plan):
    """Con que se mide un subtitulo aqui. -> (medir, banda)

    LO MISMO QUE USA EL RENDER, pedido a quien lo tiene: `p7_callouts` mide con
    la fuente del grafismo y en el peso con el que dibuja (SUB_PESO), porque
    medir con la regular partia un doce por ciento tarde y el texto se salia.
    Repetir esa cuenta aqui seria tener dos medidores que se separan el dia que
    alguien cambie la fuente.

    Si algo falla se devuelve (None, None) y el subtitulo sale sin partir: peor
    corte, pero pantalla.
    """
    try:
        p7 = PASOS_MODULOS.p7_callouts
        # LA MISMA BANDA Y EL MISMO MEDIDOR QUE `p7_callouts.ejecutar`: su
        # margen y su ancho maximo son constantes suyas, y `banda_fija` sin
        # ellos da otra caja. Se le piden a el, no se copian.
        salida = p7.salida_de(plan)
        banda = p7.banda_subtitulo(salida)
        params_callouts = ctx.estado.params("callouts") or {}
        _, ficha_diseno = p7.diseno_de(params_callouts)
        # el cuerpo de ESTA salida: en vertical es mas grande (p7.escala_subtitulo)
        medir = p7._medidor((ficha_diseno or {}).get("fuente") or "Verdana",
                            p7.tamano_subtitulo(params_callouts, salida),
                            negrita=p7.SUB_PESO >= 600)
        return medir, banda
    except Exception:                                         # noqa: BLE001
        return None, None


def _lineas_de_subtitulo(texto, medir, banda):
    """El texto partido en las mismas lineas que dibujara el render."""
    texto = " ".join(str(texto or "").split())
    if not texto:
        return []
    if not medir or not banda:
        return [texto]
    try:
        return list(PASOS_MODULOS.subtitulos.dos_lineas(
            texto, medir, banda["ancho"])) or [texto]
    except Exception:                                         # noqa: BLE001
        return [texto]


@app.post("/api/proyectos/{pid}/escenas/{sid}/vale")
def aceptar_imagen_obsoleta(pid: str, sid: str):
    """«Este dibujo me vale para lo que dice ahora». -> {ok}

    Es el descarte de la tarjeta de obsoleto, y no toca la imagen ni el plan:
    escribe en la ficha CONTRA QUE TEXTO se acepto. Si manana esa frase vuelve
    a cambiar, la tarjeta vuelve, que es justo lo que se quiere -- un «ya lo he
    visto» permanente aprobaria dibujos que nadie ha vuelto a mirar.
    """
    ctx = contexto(pid)
    version = ctx.proyecto.version_activa("assets")
    if not version:
        raise ErrorApi(409, "todavia no hay imagenes de este video")
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escena = next((e for e in (plan.get("escenas") or [])
                   if str(e.get("id") or "") == sid), None)
    if not escena:
        raise ErrorApi(404, f"no hay ningun plano {sid} en este video")
    ruta = os.path.join(ctx.proyecto.ruta_paso("assets", version),
                        "escenas", f"{sid}.json")
    ficha = PASOS_MODULOS.medios.leer_json(ruta, {}) or {}
    if not ficha:
        raise ErrorApi(404, f"{sid} no tiene ficha de imagen")
    ficha["vale_para"] = escena.get("narracion") or ""
    ficha["obsoleta"] = False
    PASOS_MODULOS.medios.escribir_json(ruta, ficha)
    return {"ok": True, "id": sid}


@app.get("/api/proyectos/{pid}/previsualizacion")
def leer_previsualizacion(pid: str):
    """Las piezas para ver el video sin montarlo. -> {escenas, audio, ...}"""
    ctx = contexto(pid)
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas_plan = plan.get("escenas") or []
    if not escenas_plan:
        raise ErrorApi(409, "todavia no hay plan de planos: genera el video "
                            "antes de poder mirarlo")
    subtitulos = PASOS_MODULOS.subtitulos
    idioma = plan.get("idioma") or ""
    # Y LOS SUBTITULOS CORREGIDOS A MANO, por el MISMO lector que usa el render
    # (`p7_callouts.texto_subtitulo_de`). Sin esto la vista previa enseñaría el
    # texto de antes de la corrección y el MP4 el de después: dos caminos para
    # lo mismo, y uno de los dos viejo.
    params_callouts = ctx.estado.params("callouts") or {}
    medir, banda = _medidor_de_subtitulo(ctx, plan)
    escenas = []
    for escena in escenas_plan:
        sid = str(escena.get("id") or "")
        if not sid:
            continue
        # LOS SUBTITULOS, PARTIDOS EN LAS MISMAS DOS LINEAS QUE EL RENDER.
        #
        # Van como texto y con sus tiempos --el navegador los pinta al ritmo del
        # audio, que es lo que hace falta aqui y un fotograma no da-- pero el
        # CORTE no se le deja al navegador. Se salian por los lados y partian
        # donde no toca porque CSS parte por el ancho de la caja y el render
        # parte MIDIENDO con la fuente que dibuja (`subtitulos.dos_lineas` con
        # el medidor de `p7_callouts`, ver SUB_PESO alli). Se parte aqui, con la
        # misma cuenta, y el navegador solo pinta las lineas ya hechas.
        try:
            trozos = subtitulos.de_escena(
                escena, idioma=idioma,
                # los mismos trozos que el render: en vertical son mas cortos
                cap_linea=PASOS_MODULOS.p7_callouts.cap_subtitulo_de(
                    params_callouts, plan),
                cap_trozo=PASOS_MODULOS.p7_callouts.cap_trozo_subtitulo(
                    PASOS_MODULOS.p7_callouts.cap_subtitulo_de(params_callouts, plan),
                    PASOS_MODULOS.p7_callouts.salida_de(plan)),
                texto=PASOS_MODULOS.p7_callouts.texto_subtitulo_de(
                    params_callouts, f"escena:{sid}")) or []
        except Exception:                                     # noqa: BLE001
            trozos = []
        escenas.append({
            "id": sid,
            "t_in": round(float(escena.get("t_in") or 0.0), 3),
            "t_out": round(float(escena.get("t_out") or 0.0), 3),
            "duracion": round(float(escena.get("duracion") or 0.0), 3),
            "narracion": escena.get("narracion") or "",
            "bloque": (escena.get("origen") or {}).get("bloque") or "",
            "cartela": (escena.get("cartela") or {}).get("plantilla") or "",
            "imagen": _ruta_de_version(ctx, "assets", "escenas", f"{sid}.png"),
            # y si el dibujo que hay ya no es de lo que aqui se dice. Va vacio
            # cuando esta al dia: es una excepcion, no un campo de todos.
            **_obsolescencia(ctx, escena),
            # EL CUADRO YA COMPUESTO, cuando existe, y manda sobre todo lo
            # demas. `p7_callouts.previsualizar` compone lo MISMO que renderiza
            # `p8_render` --la imagen dentro del transform de camara, la capa
            # movil con ella, y el subtitulo fuera a 1:1 sobre el cuadro de
            # salida-- y sale un 1920x1080 de verdad.
            #
            # Aqui se estaban mandando por separado la imagen y `capas/{id}.svg`
            # para juntarlas en el navegador, y estaba MAL de dos formas: esa
            # capa vive en el espacio del LIENZO DE GENERACION (1536x1024) y
            # estirarla sobre un cuadro 16:9 descoloca las cartelas, y el
            # subtitulo lo dibujaba el navegador a su manera --con sus propios
            # saltos de linea-- en vez de con la fuente y el corte medidos que
            # usa el render. Dos motivos para lo mismo: lo que se aprueba tiene
            # que ser lo que se renderiza.
            "compuesto": _ruta_de_version(ctx, "callouts", "previo",
                                          f"{sid}.png"),
            # `desde`/`hasta` vienen en el reloj DEL PLANO y asi se dejan: el
            # previsualizador cuenta desde que arranca la escena, no desde que
            # arranca el video, y restar aqui obligaria a volver a sumar alli.
            "subtitulos": [
                {"lineas": _lineas_de_subtitulo(t.get("texto") or "", medir,
                                                banda),
                 "desde": round(float(t.get("desde") or 0.0), 3),
                 "hasta": round(float(t.get("hasta") or 0.0), 3)}
                for t in trozos],
        })
    render = ctx.estado.params("render") or {}
    return {
        "escenas": escenas,
        "audio": _audio_de_la_toma(ctx),
        # LA MUSICA Y LOS EFECTOS SOLO PARA EL PLAY SEGUIDO. Escena a escena se
        # oye la VOZ y nada mas: lo que se esta juzgando ahi es si la imagen
        # cuadra con lo que se dice, y una cama de musica debajo es justo lo que
        # tapa esa pregunta.
        "musica": (render.get("musica") or {}).get("pista") if isinstance(
            render.get("musica"), dict) else None,
        "efectos": (render.get("efectos") or {}).get("pista") if isinstance(
            render.get("efectos"), dict) else None,
        "resolucion": plan.get("resolucion") or [1920, 1080],
        "formato": PASOS_MODULOS.comun.formato_de_plan(plan),
        "duracion_s": round(float(plan.get("duracion_total") or 0.0), 2),
        "idioma": idioma,
        # si callouts no ha corrido todavia, se puede mirar igual: se veran las
        # imagenes con sus subtitulos y sin cartelas, y decirlo es mejor que
        # ensenar una pantalla a medias sin explicacion
        "con_cartelas": bool(ctx.proyecto.version_activa("callouts")),
        "montado": bool(_ruta_de_version(ctx, "render", "video.mp4")),
    }


# ------------------------------------------- la nota del vídeo terminado
# LO QUE SE ESCRIBE DESPUÉS DE VER EL MP4, y que hasta el 21-08 vivía en los
# params del render. Ahí costaba dinero sin dar nada: los params entran en la
# firma del paso, así que escribir «la música está alta en 0:45» dejaba el
# render entero OBSOLETO — el vídeo se pintaba naranja, como si volver a
# renderizarlo fuera a arreglar la música. Y no lo lee nadie: rehacerlo daba
# exactamente el mismo MP4.
#
# Una nota sobre lo terminado no es una entrada del paso, es un REGISTRO. Y un
# registro no vive en la firma. Aquí vive en su fichero, como el informe de las
# imágenes, que también vivía en un fichero suelto y por el mismo motivo.
#
# La nota POR PLANO se queda donde está a propósito: esa sí marca su clip para
# rehacerlo, que es lo que se quiere cuando lo que falla se arregla arriba.

FICHERO_NOTAS = "notas_del_montaje.json"


def _ruta_notas(ctx):
    return ctx.proyecto.ruta(FICHERO_NOTAS)


# =========================================================================
# EL REPASO: lo que se escribe MIRANDO el vídeo, y cómo se aplica
#
# Es el único sitio del Estudio donde se decide DESPUÉS de ver el resultado, y
# de ahí salen sus dos reglas propias:
#
#   · UNA NOTA NO TOCA NINGUNA FIRMA. Vive en `repaso.json`, que es un registro
#     y no unos params: comentar un vídeo no puede dejarlo obsoleto. Lo que sí
#     toca las firmas es APLICAR, que es un gesto aparte y con su coste delante.
#   · APLICAR AHORRA. Cada nota se reparte en cambios de un vocabulario cerrado
#     (`pasos/repaso.CAMBIOS`), y cada cambio sabe qué hay que rehacer. Bajar la
#     música es volver a mezclar el audio; sólo tocar la imagen de un plano
#     cuesta una imagen. Ver `pasos/repaso.py`.
# =========================================================================

EXT_REPASO = (".png", ".jpg", ".jpeg", ".webp")
MAX_BYTES_REPASO = 12 * 1024 * 1024


def _repaso():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, "los pasos no están cargados")
    return PASOS_MODULOS.repaso


def _cortes_del_mp4(ctx):
    """Los cortes con los que se montó el MP4 que se está viendo.

    Del PLAN y no del render: el plan es quien tiene los tiempos por plano, y el
    render los usa tal cual. Si no hay plan todavía, no hay nada que anclar y
    una nota se queda con su segundo y sin plano, que es peor pero no rompe.
    """
    try:
        plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    except Exception:  # noqa: BLE001
        return []
    # LA NARRACION VIAJA CON EL CORTE, y no es de adorno: es contra lo que se
    # comprueba que una nota siga apuntando a su plano cuando la segmentacion
    # cambia (ver `repaso.reanclar`). Sin ella, re-anclar no encontraria nada
    # y daria por descolgadas todas las notas.
    return [{"id": e.get("id"), "t_in": e.get("t_in"), "t_out": e.get("t_out"),
             "narracion": e.get("narracion") or ""}
            for e in (plan.get("escenas") or []) if e.get("id")]


def _ficha_repaso(ctx):
    repaso = _repaso()
    ficha = repaso.leer(ctx.proyecto)
    cortes = _cortes_del_mp4(ctx)
    # SE RE-ANCLAN AL LEER, no al guardar. El numero de un plano cambia cuando
    # se regraba la voz y se vuelve a segmentar, y eso pasa DESPUES de escribir
    # la nota: comprobarlo al guardar seria comprobarlo cuando todavia estaba
    # bien. Aqui se compara lo que la nota dice que habia con lo que hay.
    notas = repaso.reanclar(ficha["notas"], cortes)
    return {
        "notas": notas,
        "pendientes": len([n for n in notas
                           if n.get("estado") != "aplicado"]),
        "cortes": cortes,
        "aplicado": ficha.get("aplicado") or [],
        "catalogo": repaso.catalogo(),
    }


@app.get("/api/proyectos/{pid}/repaso")
def leer_repaso(pid: str):
    """Las notas escritas sobre el vídeo montado, con los cortes para anclarlas."""
    return _ficha_repaso(contexto(pid))


@app.post("/api/proyectos/{pid}/repaso", status_code=201)
def anadir_nota_repaso(pid: str, cuerpo: dict = Body(default=None)):
    """Una nota nueva, anclada al segundo en el que se pausó.

    El texto es obligatorio y la imagen no: una referencia visual sin una frase
    no dice qué hay que hacer con ella.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    repaso = _repaso()
    try:
        segundo = float(datos.get("t") or 0.0)
    except (TypeError, ValueError):
        raise ErrorApi(400, "hace falta 't', el segundo del vídeo")
    plano = str(datos.get("plano") or "") or repaso.plano_en(
        _cortes_del_mp4(ctx), segundo)
    imagenes = [str(i) for i in (datos.get("imagenes") or [])]
    try:
        # DE QUE PANTALLA VIENE. Imagenes y Video no comparten cuaderno: en una
        # se anota sobre el dibujo y en la otra sobre lo que se monta encima.
        # EL ANCLA: lo que se decia en ese plano cuando se escribio la nota. Es
        # lo que permite volver a encontrarlo si los planos se renumeran. Lo
        # manda la pantalla, que es quien lo tiene delante; si no llega, se saca
        # de los cortes del MP4.
        ancla = str(datos.get("ancla") or "")
        if not ancla:
            for corte in _cortes_del_mp4(ctx):
                if corte.get("id") == plano:
                    ancla = str(corte.get("narracion") or "")
                    break
        nota = repaso.anadir(ctx.proyecto, datos.get("texto"), segundo,
                             plano=plano, imagenes=imagenes,
                             pantalla=str(datos.get("pantalla") or "video"),
                             ancla=ancla)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    ctx.bitacora.anotar("repaso_nota", "render",
                        {"id": nota["id"], "t": nota["t"], "plano": plano})
    return {"nota": nota, **_ficha_repaso(ctx)}


@app.put("/api/proyectos/{pid}/repaso/{nid}")
def editar_nota_repaso(pid: str, nid: str, cuerpo: dict = Body(default=None)):
    """Cambia el texto, el instante o las imágenes de una nota."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    repaso = _repaso()
    try:
        nota = repaso.editar(
            ctx.proyecto, nid,
            texto=datos.get("texto"),
            t=datos.get("t"),
            imagenes=(datos.get("imagenes")
                      if isinstance(datos.get("imagenes"), list) else None),
            regenerado=datos.get("regenerado"))
    except KeyError:
        raise ErrorApi(404, f"no hay ninguna nota {nid}")
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    return {"nota": nota, **_ficha_repaso(ctx)}


@app.delete("/api/proyectos/{pid}/repaso/{nid}")
def borrar_nota_repaso(pid: str, nid: str):
    """Quita una nota del repaso."""
    ctx = contexto(pid)
    try:
        _repaso().borrar(ctx.proyecto, nid)
    except KeyError:
        raise ErrorApi(404, f"no hay ninguna nota {nid}")
    return _ficha_repaso(ctx)


@app.post("/api/proyectos/{pid}/repaso/imagenes", status_code=201)
async def subir_imagenes_repaso(pid: str, peticion: Request):
    """Las imágenes de referencia que acompañan a una nota.

    Van a la carpeta del PROYECTO y no a un buzón: una nota del repaso pertenece
    a este vídeo y tiene que seguir ahí cuando se abra mañana.
    """
    ctx = contexto(pid)
    tipo = (peticion.headers.get("content-type") or "").lower()
    if not tipo.startswith("multipart/"):
        raise ErrorApi(400, "manda las imágenes como multipart")
    try:
        formulario = await peticion.form()
    except Exception as fallo:                              # noqa: BLE001
        raise ErrorApi(400, f"multipart ilegible: {fallo}")
    carpeta = _repaso().carpeta_imagenes(ctx.proyecto, crear=True)
    guardadas, avisos = [], []
    for _clave, valor in formulario.multi_items():
        if not hasattr(valor, "read"):
            continue
        origen = os.path.basename(str(getattr(valor, "filename", "") or ""))
        extension = os.path.splitext(origen)[1].lower()
        if extension not in EXT_REPASO:
            avisos.append(f"«{origen or 'sin nombre'}» no es una imagen "
                          f"({', '.join(EXT_REPASO)})")
            continue
        contenido = await valor.read()
        if len(contenido) > MAX_BYTES_REPASO:
            avisos.append(f"«{origen}» pesa "
                          f"{len(contenido) / 1024 / 1024:.1f} MB y el tope son "
                          f"{MAX_BYTES_REPASO // 1024 // 1024}")
            continue
        nombre = f"{uuid.uuid4().hex[:12]}{extension}"
        with open(os.path.join(carpeta, nombre), "wb") as fh:
            fh.write(contenido)
        guardadas.append({"nombre": nombre, "origen": origen,
                          "bytes": len(contenido)})
    if not guardadas and avisos:
        raise ErrorApi(400, "no se ha podido guardar ninguna: " + "; ".join(avisos))
    return {"imagenes": guardadas, "avisos": avisos}


@app.get("/api/proyectos/{pid}/repaso/imagenes/{nombre}")
def servir_imagen_repaso(pid: str, nombre: str, peticion: Request):
    """Una imagen de referencia de una nota."""
    ctx = contexto(pid)
    carpeta = _repaso().carpeta_imagenes(ctx.proyecto)
    ruta = os.path.join(carpeta, os.path.basename(nombre))
    if not ruta_contenida(carpeta, ruta) or not os.path.exists(ruta):
        raise ErrorApi(404, f"esa imagen no está: {nombre}")
    return servir_fichero(peticion, ruta)


#: EL MODO CON EL QUE SE REGENERA TRAS UN REPASO, y no es «todo» ni
#: «pendientes»: es un tercer camino y hace falta que lo sea.
#:
#:   todo         rehace de cero y REPLANTEA. Con esto, aplicar una nota sobre
#:                un plano volvería a pagar las ochenta imágenes del vídeo.
#:   pendientes   se SALTA lo que está al día, y eso también está mal aquí: el
#:                corte se da por al día en cuanto existe un plan, así que tras
#:                reescribir un bloque no se volvería a cortar.
#:   sucio        corre TODAS las tareas que los cambios han ensuciado, y cada
#:                una sobre sus unidades sucias. Ni salta ni rehace de más.
#:
#: Funciona sin código nuevo porque las dos ramas de arriba comparan por
#: igualdad: `_correr_receta` sólo salta con 'pendientes' y `_un_paso` sólo
#: fuerza `rehacer` con 'todo'.
MODO_TRAS_REPASO = "sucio"


def _correr_repaso(avisar, ctx, ajuste, modo=MODO_TRAS_REPASO,
                   sin_montar=False):
    """Reparte las notas en cambios, los aplica y vuelve a generar lo justo.

    Los tres pasos van juntos en UN trabajo a propósito: desde el navegador es
    un botón, y encadenar tres llamadas se rompe al recargar -- justo en un
    flujo pensado para dejarlo generando y volver luego.
    """
    repaso = _repaso()
    # SOLO LAS DEL REPASO DEL VIDEO. Las de Imagenes se accionan una a una en su
    # pantalla y no pasan por aqui: contarlas aqui las daria por aplicadas sin
    # que nadie las hubiera aplicado.
    notas = repaso.pendientes(ctx.proyecto, pantalla="video")
    if not notas:
        avisar(1.0, "no hay notas pendientes")
        return {"notas": [], "tareas": [], "resumen": "no hay notas pendientes"}

    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = {e.get("id"): e for e in (plan.get("escenas") or [])}
    orden = [e.get("id") for e in (plan.get("escenas") or [])]
    guion = (PASOS_MODULOS.comun.leer_salida(
        ctx.proyecto, "guion", "guion.json", obligatorio=False) or {})
    bloques = guion.get("guion") or []
    por_bloque = {b.get("id"): b for b in bloques}
    # LOS SUBTITULOS QUE YA SE CORRIGIERON A MANO, para que el enrutador lea lo
    # que se ve AHORA. Sin esto, una segunda vuelta de notas leería el subtítulo
    # de antes de la primera corrección.
    puestos = {}
    for uid, bloque in ((ctx.estado.params("callouts") or {}).get("unidades")
                        or {}).items():
        if isinstance(bloque, dict) and bloque.get("subtitulo_texto"):
            puestos[str(uid).split(":", 1)[-1]] = bloque["subtitulo_texto"]
    contextos = {n["id"]: repaso.contexto_de_nota(
        n, escenas, por_bloque, orden, _carpeta_de_escenas(ctx),
        textos_subtitulo=puestos)
        for n in notas}
    carpeta = repaso.carpeta_imagenes(ctx.proyecto)
    rutas = {nombre: os.path.join(carpeta, nombre)
             for nota in notas for nombre in (nota.get("imagenes") or [])}

    reproductor = PASOS_MODULOS.p8_render.reproductor(ctx.proyecto)
    avisar(0.05, f"repartiendo {len(notas)} nota(s) del repaso")
    reparto = repaso.enrutar(
        [dict(n) for n in notas], contextos, bloques,
        titulo=guion.get("titulo") or ctx.proyecto.id,
        duracion=float(reproductor.get("duracion") or 0.0),
        estado=PASOS_MODULOS.sonido.describir(ctx.estado.params("render") or {}),
        ajuste=ajuste, avisar=lambda v, m="": avisar(0.05 + 0.15 * float(v or 0), m),
        proyecto_id=ctx.id, rutas_imagenes=rutas,
        # CADA PANTALLA ARREGLA LO SUYO, y el repaso del video arregla lo que se
        # MONTA ENCIMA del plano y lo que se OYE: cartela, subtitulo,
        # transicion, musica y efectos. Los otros tres ambitos tienen su sitio
        # y se vetan aqui:
        #
        #   imagen      -> la pantalla de Imagenes, plano a plano
        #   guion, voz  -> la pantalla de Guion, que es donde se reescribe
        #
        # Se veta al VALIDAR y no en el prompt: pedirselo al agente es pedirlo.
        # Y la nota no se pierde, vuelve como aviso diciendo donde se arregla.
        ambitos_vetados=("imagen", "guion", "voz"))

    resumen = repaso.resumen_de(reparto)
    avisos = list(reparto.get("avisos") or [])
    aplicados = _aplicar_cambios_del_repaso(ctx, reparto, avisos)
    tareas = resumen["tareas"]
    ctx.bitacora.anotar("repaso_aplicado", "render", {
        "notas": len(notas), "cambios": len(reparto.get("cambios") or []),
        "tareas": tareas, "por_ambito": resumen["por_ambito"]})

    if tareas:
        avisar(0.22, f"volviendo a generar: {', '.join(tareas)}")
        # ¿HACE FALTA DIBUJAR ALGO, O SOLO VOLVER A MEZCLAR? Si todas las
        # notas son de música o de efectos, no cambia un solo fotograma: se
        # remonta el MP4 sobre los clips que ya hay. La promesa estaba escrita
        # en `AMBITOS["musica"]["cuesta"]` desde el primer día y no se cumplía:
        # pedir «baja la música» redibujaba los 98 planos en Edge.
        solo_montar = repaso.solo_mezcla(
            [c for n in (reparto.get("notas") or [])
             for c in (n.get("cambios") or [])])
        # APLICAR NO ES MONTAR, y desde las diapositivas son dos gestos.
        #
        # Aplicando desde ahi se redibuja lo que las notas tocan --el plano, su
        # capa, la cartela-- y se PARA: lo que se acaba de arreglar se mira en
        # las diapositivas, que es donde se escribio la nota. Montar el MP4 es
        # lo que se hace despues, con el boton de la pantalla del video, y es
        # el paso caro en tiempo de maquina.
        #
        # Solo se quita la tarea del MP4: `banda_sonora` y `efectos` viven en
        # la misma pestaña pero son PREPARACION --traen material al banco-- y
        # dejarlas fuera obligaria a pagar esa espera al montar.
        if sin_montar:
            tareas = [x for x in tareas if x != "render"]
        if tareas:
            _regenerar_tras_repaso(avisar, ctx, tareas, modo, solo_montar)

    # las notas aplicadas se marcan DESPUÉS de generar: si la tanda se cae, las
    # notas siguen pendientes y volver a darle al botón las vuelve a intentar
    ficha = repaso.leer(ctx.proyecto)
    aplicadas = {n["id"] for n in reparto.get("notas") or [] if n.get("cambios")}
    for nota in ficha["notas"]:
        if nota.get("id") in aplicadas:
            nota["estado"] = "aplicado"
            nota["aplicado_en"] = ahora()
    ficha.setdefault("aplicado", []).append({
        "cuando": ahora(), "notas": sorted(aplicadas), "tareas": tareas,
        "por_ambito": resumen["por_ambito"]})
    repaso.guardar(ctx.proyecto, ficha)

    frase = (f"{len(aplicadas)} de {len(notas)} notas aplicadas · "
             + (resumen["frase"] or "sin cambios"))
    avisar(1.0, frase)
    return {"notas": reparto.get("notas"), "tareas": tareas,
            "por_ambito": resumen["por_ambito"], "aplicados": aplicados,
            "avisos": avisos, "resumen": frase}


def _regenerar_tras_repaso(avisar, ctx, tareas, modo, solo_montar=False):
    """Corre SOLO las tareas que los cambios han ensuciado, en su orden.

    Se agrupan por pestaña y se corre cada pestaña con su receta recortada a lo
    que hay que rehacer, que es exactamente lo que ya sabe hacer `_correr_receta`.

    Y con `solo_montar`, el MP4 se REMONTA en vez de renderizarse: ni un plano
    se vuelve a dibujar. Es lo que hace que «baja la música» cueste segundos y
    no el render entero. Ver `repaso.solo_mezcla`.
    """
    recetas = _recetas()
    por_pestana = {}
    for tarea in tareas:
        ficha = recetas.TAREAS_POR_ID.get(tarea)
        if ficha:
            por_pestana.setdefault(ficha["pestana"], []).append(tarea)
    pestanas = [p for p in recetas.PESTANAS if p in por_pestana]
    for indice, pestana in enumerate(pestanas):
        base = 0.25 + 0.7 * indice / max(1, len(pestanas))
        techo = 0.25 + 0.7 * (indice + 1) / max(1, len(pestanas))
        receta = _receta_de_video(ctx, pestana)
        _correr_receta(lambda v, m="", p="", _b=base, _t=techo:
                       avisar(_b + (_t - _b) * float(v or 0), m, p),
                       ctx, pestana, receta, por_pestana[pestana], modo,
                       solo_montar)


def _aplicar_cambios_del_repaso(ctx, reparto, avisos):
    """Escribe en params lo que dicen los cambios. -> [descripciones]

    Cada tipo se escribe en SU cajón, y el cajón es el mismo que usa la pantalla
    para lo mismo: el feedback de un plano va al feedback de esa unidad, el
    texto de un bloque a `params.guion.bloques`, la música a los params del
    render. Ni un cajón nuevo -- un segundo camino para lo mismo se queda viejo.
    """
    hechos = []
    unidades_assets, params_callouts, unidades_callouts = {}, {}, {}
    params_render, params_guion, params_brief = {}, {}, {}
    for cambio in (reparto.get("cambios") or []):
        tipo = cambio["tipo"]
        if tipo == "feedback_plano":
            uid = f"escena:{cambio['plano']}"
            unidades_assets.setdefault(uid, {}).setdefault("feedback_nuevo", [])                 .append({"texto": cambio["texto"],
                          "alcance": cambio.get("alcance") or "sustituye",
                          "imagenes": list(cambio.get("imagenes") or [])})
        elif tipo == "feedback_asset":
            uid = f"asset:{cambio['asset']}"
            unidades_assets.setdefault(uid, {}).setdefault("feedback_nuevo", [])                 .append({"texto": cambio["texto"],
                          "imagenes": list(cambio.get("imagenes") or [])})
        elif tipo == "cartela_texto":
            uid = f"escena:{cambio['plano']}"
            unidades_assets.setdefault(uid, {})["cartela_campos"] =                 cambio["campos_cartela"]
        elif tipo == "quitar_cartela":
            uid = f"escena:{cambio['plano']}"
            unidades_assets.setdefault(uid, {})["quitar_cartela"] = True
        elif tipo == "subtitulo_tam":
            params_callouts["subtitulo_tam"] = cambio["valor"]
        elif tipo == "grafismo":
            params_callouts["diseno"] = cambio["valor"]
        elif tipo == "subtitulo_texto":
            # POR UNIDAD, como el resto de decisiones de un plano: corregir lo
            # escrito en S072 deja obsoleto S072 y ninguno más. Lo lee
            # `p7_callouts.texto_subtitulo_de`, que es lo que hace que esto no
            # sea un cajón muerto.
            unidades_callouts[f"escena:{cambio['plano']}"] = cambio["texto"]
        elif tipo == "transicion_duracion":
            params_render["duracion_transicion"] = float(cambio["valor"])
        elif tipo == "transiciones":
            params_render["transiciones"] = list(cambio["lista"])
        elif tipo == "musica_db":
            params_render["musica_db"] = float(cambio["valor"])
        elif tipo == "efectos_db":
            params_render["efectos_db"] = float(cambio["valor"])
        elif tipo == "sin_musica":
            params_render["musica"] = {}
        elif tipo == "otra_musica":
            params_render["musica"] = {}
        elif tipo == "sin_efectos":
            params_render["efectos"] = {}
        elif tipo == "otros_efectos":
            params_render["efectos"] = {}
        elif tipo == "bloque_texto":
            params_guion.setdefault("bloques", {})[cambio["bloque"]] =                 cambio["texto"]
        elif tipo == "velocidad":
            params_brief["velocidad"] = float(cambio["valor"])
        elif tipo == "anotar":
            avisos.append(f"queda por decidir a mano: {cambio['texto']}")
            continue
        hechos.append(f"{tipo}: " + ", ".join(
            f"{k}={v}" for k, v in cambio.items()
            # las rutas de las imágenes no entran en el resumen: es una línea
            # para leer, y una ruta absoluta por nota la deja ilegible
            if k not in ("tipo", "ambito", "rehacer", "imagenes")))

    if unidades_assets:
        # LO QUE NO SE PUDO ESCRIBIR SALE DE `hechos`. Un resumen que dice
        # «cambiado el texto de la cartela de S099» cuando ese plano no lleva
        # ninguna es la misma clase de mentira que una nota marcada como
        # aplicada sin aplicar.
        fallidos = _escribir_unidades_del_repaso(ctx, unidades_assets, avisos)
        for uid in fallidos:
            plano = uid.split(":", 1)[-1]
            hechos = [h for h in hechos
                      if not (h.startswith("cartela_texto:") and plano in h)]
    if unidades_callouts:
        # Fusionando lo que ya hubiera en esa unidad, igual que en assets:
        # `actualizar_params` sustituye el diccionario de la unidad ENTERO, así
        # que escribir sólo el subtítulo borraría sus zonas a evitar y su
        # `sin_callout`.
        previas = (ctx.estado.params("callouts") or {}).get("unidades") or {}
        bloque = {}
        for uid, texto in unidades_callouts.items():
            actual = previas.get(uid)
            actual = dict(actual) if isinstance(actual, dict) else {}
            actual["subtitulo_texto"] = texto
            bloque[uid] = actual
        params_callouts["unidades"] = bloque
    if params_callouts:
        ctx.estado.actualizar_params("callouts", params_callouts)
    if params_render:
        ctx.estado.actualizar_params("render", params_render)
    if params_guion:
        actuales = ctx.estado.params("guion") or {}
        if "bloques" in params_guion:
            fusion = dict(actuales.get("bloques") or {})
            fusion.update(params_guion["bloques"])
            params_guion["bloques"] = fusion
        ctx.estado.actualizar_params("guion", params_guion)
    if params_brief:
        ctx.estado.actualizar_params("brief", params_brief)
    return hechos


def _escribir_unidades_del_repaso(ctx, cambios, avisos=None):
    """Fusiona lo que toca a cada unidad, sin llevarse por delante lo que había.

    `actualizar_params` sustituye el diccionario de la unidad ENTERO, así que
    escribir sólo el feedback borraría la cartela de ese plano y su dirección.
    Es la misma trampa que ya costó una ronda con las cartelas y con la
    dirección, y no da ningún error: la nota deja de estar.
    """
    previos = (ctx.estado.params("assets") or {}).get("unidades") or {}
    bloque, fallidos = {}, []
    for uid, pedido in cambios.items():
        actual = previos.get(uid)
        actual = dict(actual) if isinstance(actual, dict) else {}
        for nota in (pedido.get("feedback_nuevo") or []):
            historial = actual.get("feedback")
            historial = list(historial) if isinstance(historial, list) else []
            historial.append({
                "id": f"F{len(historial) + 1:03d}", "fecha": ahora(),
                "texto": nota["texto"], "modo": "directo", "trazos": 0,
                "zonas": "", "de": "repaso",
                # QUE CLASE DE CORRECCION ES, y con qué se acompaña. Lo lee
                # `p6_assets._referencias_escena` para decidir si al generador
                # se le adjunta la imagen rechazada. Ver `repaso.ALCANCES`.
                **({"alcance": nota["alcance"]} if nota.get("alcance") else {}),
                **({"imagenes": list(nota["imagenes"])}
                   if nota.get("imagenes") else {})})
            actual["feedback"] = historial
        sin_cartela = False
        if pedido.get("cartela_campos"):
            # SOLO SI ESE PLANO YA ES UNA CARTELA. Escribir `datos` sobre un
            # plano que no la lleva crearía una cartela SIN PLANTILLA, y
            # `cartelas._desmontar` la rellenaría con el EJEMPLO de la de por
            # defecto: un plano del vídeo diciendo el texto de muestra. Cambiar
            # lo que dice una cartela y crear una son dos cosas.
            cartela = actual.get("cartela")
            if isinstance(cartela, dict) and cartela.get("plantilla"):
                cartela = dict(cartela)
                datos = dict(cartela.get("datos") or {})
                datos.update({k: v for k, v in pedido["cartela_campos"].items()
                              if isinstance(k, str)})
                cartela["datos"] = datos
                actual["cartela"] = cartela
            else:
                sin_cartela = True
        if pedido.get("quitar_cartela"):
            actual.pop("cartela", None)
        bloque[uid] = actual
        if sin_cartela:
            fallidos.append(uid)
            if isinstance(avisos, list):
                avisos.append(f"{uid}: se pidió cambiar el texto de su cartela y "
                              f"ese plano no lleva ninguna, así que no se ha "
                              f"tocado")
    ctx.estado.actualizar_params("assets", {"unidades": bloque})
    return fallidos


@app.post("/api/proyectos/{pid}/repaso/aplicar", status_code=202)
def aplicar_repaso(pid: str, cuerpo: dict = Body(default=None)):
    """Aplica las notas del repaso y vuelve a generar SOLO lo que cambian.

    Un botón y un trabajo: reparte las notas en cambios, los escribe en su cajón
    y corre las tareas que han quedado sucias, en orden de pipeline. Una nota
    sobre la música vuelve a mezclar el audio; ninguna imagen se repaga si nada
    lo pide.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    por_fase = CLI_CLAUDE.por_defecto_de("repaso")
    ajuste = _ajuste_cli(datos, por_fase["modelo"], por_fase["esfuerzo"])
    modo = str(datos.get("modo") or MODO_TRAS_REPASO)
    # `sin_montar`: aplica y para antes del MP4. Lo pide la pantalla de las
    # diapositivas, donde lo que se quiere es MIRAR lo arreglado; la del video
    # no lo manda, porque alli aplicar y montar son el mismo gesto.
    sin_montar = bool(datos.get("sin_montar"))
    trabajo_id = ctx.gestor.lanzar("repaso", _correr_repaso, ctx, ajuste, modo,
                                   sin_montar, paso="render")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "ajuste": ajuste,
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.get("/api/proyectos/{pid}/montaje/notas")
def leer_notas_montaje(pid: str):
    """Lo escrito sobre el vídeo terminado. No toca ninguna firma."""
    ctx = contexto(pid)
    ficha = leer_json(_ruta_notas(ctx), {}) or {}
    return {"nota": str(ficha.get("nota") or ""), "cuando": ficha.get("cuando")}


@app.put("/api/proyectos/{pid}/montaje/notas")
def guardar_notas_montaje(pid: str, cuerpo: dict = Body(default=None)):
    """Guarda la nota del vídeo entero. Autoguardado, como todo lo demás."""
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    nota = str(datos.get("nota") or "").strip()
    ruta = _ruta_notas(ctx)
    ficha = {"nota": nota, "cuando": time.strftime("%Y-%m-%dT%H:%M:%S")}
    temporal = ruta + ".parcial"
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump(ficha, fh, ensure_ascii=False, indent=1)
    os.replace(temporal, ruta)
    ctx.bitacora.anotar("nota_montaje", "render", {"letras": len(nota)})
    # se devuelve el estado para que la pantalla vea que NO se ha movido: el
    # vídeo sigue al día por mucho que se escriba encima
    return {"guardado": True, "estado": ctx.estado.estado_de("render"), **ficha}


# ------------------------------------------------------------- transiciones
# El catalogo de shaders de hyperframes, elegido MIRANDOLO: la pantalla corre el
# mismo GLSL que el render, asi que la muestra no puede ensenar otra cosa.

@app.get("/api/proyectos/{pid}/transiciones")
def leer_transiciones(pid: str):
    """Las transiciones que existen, con su GLSL, y cuales entran en este video."""
    ctx = contexto(pid)
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    trans = PASOS_MODULOS.transiciones
    render = ctx.estado.params("render") or {}
    elegidas = render.get("transiciones") or []
    ficha = trans.catalogo_para_pantalla(elegidas or None)
    ficha["duracion"] = render.get(
        "duracion_transicion", PASOS_MODULOS.p8_render.PARAMS_POR_DEFECTO["duracion_transicion"])
    ficha["todas_de_fabrica"] = not elegidas
    # Los tres colores de acento con los que se pintan, para que la muestra de
    # la pantalla salga del color de ESTE video y no de un naranja de catalogo.
    ficha["acento"] = trans.acentos(_paleta_del_video(ctx))
    # QUE TRANSICION LLEVA CADA PLANO, resuelta por el motor.
    #
    # El plan solo trae la RANURA (suave / acento), que es una decision del
    # corte; cual la ocupa lo decide `transiciones.resolver` con la semilla del
    # video, y es determinista. Viaja hasta la pantalla para que el repaso del
    # montaje pueda correr EL MISMO shader que el render en cada corte, en vez
    # de la aproximacion CSS que enseniaba antes (un destello y un encadenado).
    # Sin esto, el repaso tendria que adivinar cual toca -- y adivinaria mal en
    # cuanto cambiara la paleta elegida.
    #
    # Va el reparto y no el GLSL de cada plano: el frag de cada transicion ya
    # viaja UNA vez en el catalogo, y repetirlo por plano serian doscientas
    # copias del mismo texto.
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan.get("escenas") or []
    reparto = trans.resolver(escenas, render, semilla=(plan.get("semilla") or 0))
    ficha["reparto"] = {sid: {k: v for k, v in corte.items() if k != "shader"}
                        for sid, corte in reparto.items()}
    return ficha


# ------------------------------------------------------- música y efectos
# Dos momentos separados a propósito (ver pasos/sonido.py): aquí se BUSCA y se
# ELIGE, con la red delante; renderizar no sale a la red, coge del banco lo que
# digan los params. Una búsqueda en una API devuelve cosas distintas cada
# semana, y el mismo plan tiene que dar el mismo vídeo.

def _sonido():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.sonido


@app.get("/api/proyectos/{pid}/sonido")
def leer_sonido(pid: str):
    """Qué suena en este vídeo: el tema puesto, los efectos surtidos y el catálogo."""
    ctx = contexto(pid)
    sonido = _sonido()
    render = ctx.estado.params("render") or {}
    crudo = render.get("efectos") or {}
    hay_jamendo, hay_freesound = sonido.hay_claves()
    # CADA EFECTO, CON SU MUESTRA Y SU VETO. La pantalla tiene que poder oír lo
    # que acaba de sonar y ponerle la ✕ ahí mismo: un veto que hay que escribir
    # en otra pantalla es un veto que no se pone. Ver `sonido.vetar`.
    prohibidos = sonido.vetados()
    surtido = {}
    for papel, fichas in crudo.items():
        lista = [{
            **(f if isinstance(f, dict) else {}),
            "clave": sonido.clave_de(f),
            "vetado": sonido.clave_de(f) in prohibidos,
            "muestra": f"/api/efectos/{sonido._nombre_de(f)}",
            # cuánto de su energía está por encima de 4 kHz. Ordena la lista para
            # encontrar «ese que suena como un láser» sin escuchar los doce: un
            # láser es filo y un aire es cuerpo. No decide, ordena.
            "agudo": sonido.agudeza(f),
        } for f in (fichas or []) if isinstance(f, dict)]
        surtido[papel] = sorted(lista, key=lambda x: -(x.get("agudo") or 0))
    return {
        "activo": render.get("sonido", True),
        "musica": render.get("musica") or {},
        "efectos": surtido,
        # LOS VETADOS DEL CANAL. Viajan a la pantalla para poder pintar la ✕ ya
        # marcada en el efecto que se veto: si no, la lista enseñaria un sonido
        # con aspecto de estar puesto que en el vídeo no suena.
        "vetados": [prohibidos[k] for k in sorted(prohibidos)],
        # `surtidos` cuenta los que DE VERDAD pueden sonar: un papel con seis
        # efectos de los que cinco están vetados no tiene seis, tiene uno.
        "papeles": [{"id": k, **{c: v[c] for c in
                                 ("nombre", "descripcion", "cuantos")},
                     "surtidos": sum(1 for f in (surtido.get(k) or [])
                                     if not f.get("vetado")),
                     "vetados": sum(1 for f in (surtido.get(k) or [])
                                    if f.get("vetado"))}
                    for k, v in sonido.PAPELES.items()],
        "animos": sorted(sonido.ANIMOS),
        "hay_jamendo": hay_jamendo,
        "hay_freesound": hay_freesound,
        "lufs": render.get("musica_lufs", sonido.MUSICA_LUFS),
        "resumen": sonido.describir(render),
        # los créditos, en una lista lista para pegar en la descripción: los
        # temas son de Jamendo y varios piden atribución
        "creditos": [{"titulo": t.get("titulo"), "artista": t.get("artista"),
                      "licencia": t.get("licencia")}
                     for t in (render.get("musica") or {}).get("tramos") or []],
    }


@app.post("/api/proyectos/{pid}/sonido/musica")
def buscar_musica(pid: str, cuerpo: dict = Body(default=None)):
    """Temas de Jamendo que pegan con el tono. Devuelve candidatos, no elige."""
    ctx = contexto(pid)
    sonido = _sonido()
    datos = _cuerpo(cuerpo)
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    try:
        temas = sonido.buscar_musica(
            animo=str(datos.get("animo") or "sobrio"),
            duracion_s=float(plan.get("duracion_total") or 0),
            velocidad=str(datos.get("velocidad") or "low"),
            extra=str(datos.get("extra") or "")[:80],
            cuantas=int(datos.get("cuantas") or 12))
    except Exception as fallo:
        # una API caída no puede tumbar la pantalla: se dice y se sigue
        raise ErrorApi(502, f"no se ha podido buscar música: {fallo}")
    return {"temas": temas, "duracion_video": plan.get("duracion_total")}


@app.put("/api/proyectos/{pid}/sonido")
def guardar_sonido(pid: str, cuerpo: dict = Body(default=None)):
    """Fija el tema (bajándolo al banco), el interruptor o el nivel de música."""
    ctx = contexto(pid)
    sonido = _sonido()
    datos = _cuerpo(cuerpo)
    cambios = {}
    if "activo" in datos:
        cambios["sonido"] = bool(datos["activo"])
    if isinstance(datos.get("lufs"), (int, float)):
        cambios["musica_lufs"] = max(-40.0, min(-10.0, float(datos["lufs"])))
    if "musica" in datos:
        ficha = datos["musica"] or {}
        if not ficha:
            cambios["musica"] = {}
        else:
            if not ficha.get("id") or not ficha.get("descarga"):
                raise ErrorApi(400, "el tema tiene que traer 'id' y 'descarga'")
            # Se BAJA aquí, al elegirlo, y no al renderizar: el render no sale a
            # la red, y enterarse de que el enlace ya no vale cuando llevas
            # veinte minutos de clips es la versión cara del mismo error.
            try:
                sonido.traer(ficha, "musica")
            except Exception as fallo:
                raise ErrorApi(502, f"no se ha podido bajar el tema: {fallo}")
            cambios["musica"] = ficha
    if not cambios:
        raise ErrorApi(400, "hace falta 'musica', 'activo' o 'lufs'")
    ctx.estado.actualizar_params("render", cambios)
    ctx.bitacora.anotar("sonido", "render", {
        "musica": (cambios.get("musica") or {}).get("titulo"),
        "activo": cambios.get("sonido")})
    return {"guardado": list(cambios), "estado": ctx.estado.estado_de("render")}


def _correr_surtir_efectos(avisar, ctx, papeles, salteado):
    sonido = _sonido()
    render = ctx.estado.params("render") or {}
    surtido = dict(render.get("efectos") or {})
    total = len(papeles)
    for indice, papel in enumerate(papeles):
        avisar(0.05 + 0.9 * (indice / max(1, total)),
               f"buscando y bajando «{sonido.PAPELES[papel]['nombre']}»")
        surtido[papel] = sonido.surtir(papel, salteado=salteado)
    ctx.estado.actualizar_params("render", {"efectos": surtido})
    cuantos = sum(len(v or []) for v in surtido.values())
    avisar(1.0, f"{cuantos} efectos en el banco")
    return {"efectos": surtido, "cuantos": cuantos}


def _correr_banda(avisar, ctx, tramos):
    """Monta la banda sonora entera sin preguntar nada. Ver sonido.montar_banda."""
    sonido = _sonido()
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan.get("escenas") or []
    if not escenas:
        raise RuntimeError("no hay planos todavía: la música se monta sobre el "
                           "ritmo del montaje, así que primero hay que cortarlo")
    largo = float(plan.get("duracion_total") or 0) or None
    if not largo:
        largo = (float(escenas[-1].get("t_out") or 0)
                 - float(escenas[0].get("t_in") or 0))
    avisar(0.05, "leyendo el ritmo del montaje")
    ficha = sonido.montar_banda(escenas, largo, avisar=avisar, tramos=tramos)
    ctx.estado.actualizar_params("render", {"musica": ficha})
    ctx.bitacora.anotar("banda_sonora", "render", {
        "tramos": len(ficha["tramos"]),
        "animos": [t["animo"] for t in ficha["tramos"]]})
    avisar(1.0, sonido.describir(ctx.estado.params("render") or {}))
    return {**ficha, "resumen": sonido.describir(ctx.estado.params("render") or {})}


@app.get("/api/proyectos/{pid}/sonido/arco")
def leer_arco(pid: str):
    """El arco que sale del RITMO del montaje. Gratis, sin salir a la red.

    Es lo que la pantalla enseña antes de montar nada: en cuántos tramos se
    parte el vídeo, cuántos planos tiene cada uno y qué ánimo pide. Sirve para
    entender la decisión, no para tomarla.
    """
    ctx = contexto(pid)
    sonido = _sonido()
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan.get("escenas") or []
    largo = float(plan.get("duracion_total") or 0)
    if not largo and escenas:
        largo = (float(escenas[-1].get("t_out") or 0)
                 - float(escenas[0].get("t_in") or 0))
    return {"tramos": sonido.arco_del_video(escenas, largo),
            "duracion": largo, "planos": len(escenas)}


@app.post("/api/proyectos/{pid}/sonido/banda", status_code=202)
def montar_banda_sonora(pid: str, cuerpo: dict = Body(default=None)):
    """Monta la banda sonora SOLA: un tema por tramo, elegido por el ritmo.

    No hay nada que elegir. El montaje ya dice dónde acelera y dónde respira
    (`sonido.arco_del_video`), cada tramo pide su ánimo, y de los candidatos se
    queda el que mejor deja libre la banda de la voz — medido, no escuchado.
    """
    ctx = contexto(pid)
    sonido = _sonido()
    datos = _cuerpo(cuerpo)
    if not sonido.hay_claves()[0]:
        raise ErrorApi(409, "falta JAMENDO_CLIENT_ID en C:\\IA\\secrets\\.env")
    # los tramos se pueden pasar retocados desde avanzadas (otro ánimo), pero el
    # camino normal es no pasar nada y que los deduzca del ritmo
    tramos = datos.get("tramos") if isinstance(datos.get("tramos"), list) else None
    trabajo_id = ctx.gestor.lanzar("banda_sonora", _correr_banda, ctx, tramos,
                                   paso="render")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.get("/api/efectos/{archivo}")
def servir_efecto(archivo: str, peticion: Request):
    """Sirve un efecto del banco del canal, para poder oírlo antes de vetarlo.

    Del BANCO y no del enlace de Freesound a propósito: lo que hay que escuchar
    es el fichero que va a sonar en el vídeo, que es este. El de Freesound puede
    haber cambiado, o no estar, y entonces se vetaría a ciegas.
    """
    sonido = _sonido()
    destino = ruta_segura(sonido.banco("efectos"), archivo)
    if not os.path.isfile(destino):
        raise ErrorApi(404, f"no hay ningún efecto {archivo!r} en el banco")
    return servir_fichero(peticion, destino)


@app.post("/api/proyectos/{pid}/sonido/vetados")
def vetar_efecto(pid: str, cuerpo: dict = Body(default=None)):
    """Prohíbe un efecto en TODO el canal, o levanta el veto con `quitar`.

    Es la contraparte de `camara_vetada` para el sonido, con una diferencia que
    importa: la cámara se veta para UN plano de UN vídeo, y un sonido que no
    gusta no gusta nunca más. Por eso el veto es del canal y vive al lado del
    banco, no en los params del proyecto.

    Y NO SE BORRA EL FICHERO. Freesound ordena por descargas: borrarlo sólo
    consigue que la siguiente búsqueda lo vuelva a bajar.
    """
    contexto(pid)                      # el proyecto tiene que existir
    sonido = _sonido()
    datos = _cuerpo(cuerpo)
    ficha = datos.get("efecto") if isinstance(datos.get("efecto"), dict) else None
    clave = str(datos.get("clave") or "").strip() or (
        sonido.clave_de(ficha) if ficha else "")
    if not clave:
        raise ErrorApi(400, "hace falta 'clave' o 'efecto' con fuente e id")
    if datos.get("quitar"):
        return {"vetado": False, "quitado": sonido.desvetar(clave),
                "vetados": [sonido.vetados()[k] for k in sorted(sonido.vetados())]}
    try:
        entrada = sonido.vetar(ficha or clave, papel=datos.get("papel"),
                               motivo=str(datos.get("motivo") or ""))
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    return {"vetado": True, "efecto": entrada,
            "vetados": [sonido.vetados()[k] for k in sorted(sonido.vetados())]}


@app.post("/api/proyectos/{pid}/sonido/efectos", status_code=202)
def surtir_efectos(pid: str, cuerpo: dict = Body(default=None)):
    """Llena el banco de efectos del canal para los papeles que se pidan.

    Va en un trabajo porque baja ficheros: cuatro papeles son una veintena de
    peticiones a Freesound y otras tantas descargas.
    """
    ctx = contexto(pid)
    sonido = _sonido()
    datos = _cuerpo(cuerpo)
    pedidos = datos.get("papeles") or list(sonido.PAPELES)
    desconocidos = [p for p in pedidos if p not in sonido.PAPELES]
    if desconocidos:
        raise ErrorApi(400, f"papeles desconocidos: {', '.join(desconocidos)}. "
                            f"Los que hay son: {', '.join(sonido.PAPELES)}")
    if not sonido.hay_claves()[1]:
        raise ErrorApi(409, "falta FREESOUND_API_KEY en C:\\IA\\secrets\\.env")
    # 'salteado' rota por qué consulta se empieza: volver a pulsar trae OTROS
    # sonidos en vez de los mismos, que es lo que se espera de «buscar más».
    salteado = int(datos.get("salteado") or 0)
    trabajo_id = ctx.gestor.lanzar("efectos", _correr_surtir_efectos, ctx,
                                   list(pedidos), salteado, paso="render")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# ------------------------------------------------------------------ ajustes

@app.get("/api/ajustes")
def leer_ajustes():
    """Lo que hay puesto, y lo que cuesta cada calidad de imagen.

    La tabla de costes viaja CON el ajuste y no en otra llamada porque es lo
    que hace que la eleccion se pueda tomar: elegir calidad mirando solo el
    precio de la imagen devuelta es elegir mirando la parte pequena.
    """
    return {"ajustes": AJUSTES.leer(),
            "calidades": list(AJUSTES.CALIDADES),
            "costes": AJUSTES.tabla_de_costes(),
            "tamano": AJUSTES.TAMANO}


@app.put("/api/ajustes")
def guardar_ajustes(cuerpo: dict = Body(default=None)):
    """Cambia ajustes. NO toca ningun proyecto: es el valor de los NUEVOS."""
    try:
        guardados = AJUSTES.guardar(_cuerpo(cuerpo))
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    anotar_global("ajustes_guardados", {"ajustes": guardados})
    return {"ajustes": guardados, "costes": AJUSTES.tabla_de_costes()}


# ------------------------------------------------------------------ enlaces
# -------------------------------------------------------------------- recetas
#
# Ejecutar una PESTANA entera de una tirada. La tabla de tareas (que hay, de que
# depende cada una, cual cuesta dinero) vive en pasos/recetas.py; aqui vive lo
# unico que no cabe alli: QUE FUNCION corre cada tarea. Y es a proposito la
# MISMA que corre su boton -- no hay un camino "automatico" y otro "a mano",
# porque entonces habria dos comportamientos que mantener y uno de los dos se
# quedaria viejo.
#
# El ejecutor entero corre en UN trabajo del gestor, no en el navegador. El
# encadenado que habia (lanzarGuionCompleto, en app.js) se rompia al recargar la
# pagina, justo en un flujo pensado para dejarlo generando y mirarlo desde el
# movil.


def _recetas():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.recetas


def _ajuste_de_fase(receta, fase, extra=None):
    """El modelo y el esfuerzo de una fase: lo de la receta, o su defecto razonado."""
    por_defecto = CLI_CLAUDE.por_defecto_de(fase)
    puesto = ((receta or {}).get("ajustes") or {}).get(fase) or {}
    datos = dict(puesto)
    datos.update(extra or {})
    return _ajuste_cli(datos, por_defecto["modelo"], por_defecto["esfuerzo"])


def _referencias_de_estilo_o_400(ctx):
    """Las laminas de estilo con las que se genera cada plano, o un 400 claro.

    Son las que dibujo la parte «estilo» del estilo grafico
    (`_correr_light_referencias`). No se preselecciona nada: antes se elegian
    solas de entre los fotogramas de un video de referencia, y ya no hay video
    ni fotogramas -- lo que hay son las laminas, y o estan dibujadas o no.
    """
    estilo = _estilo()
    rutas = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("referencias")
    try:
        rutas = estilo.validar_seleccion(rutas)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    minimo = PASOS_MODULOS.p6_assets.MIN_REFERENCIAS_ESTILO
    if len(rutas) < minimo:
        raise ErrorApi(400, f"la generacion necesita al menos {minimo} laminas "
                            f"de estilo y hay {len(rutas)}: rehaz el estilo "
                            f"grafico de este canal y vuelve a lanzar")
    return rutas


# Cada entrada: (funcion, argumentos) a partir de (ctx, receta). La funcion
# recibe `avisar` como primer argumento, igual que cualquier trabajo del gestor.
def _un_paso(ctx, paso_id, modo, extra=None):
    """Un paso del grafo desde una receta, con las MISMAS unidades que su boton.

    Esto es lo que separa «generar lo que falta» de «pagar 49 imagenes otra
    vez». `_correr_paso` con `unidades=None` rehace el paso ENTERO; quien decide
    que hay que rehacer de verdad es `_plan_de_ejecucion`, que es lo que llama
    el endpoint de ejecutar. La receta tiene que pasar por ahi igual:

        todo         rehace de cero, y ademas REPLANTEA -- se vuelve a cortar la
                     narracion y se renumeran los planos. Es lo que hace el
                     boton «Rehacer los planos».
        pendientes   solo las unidades sucias, y SIN replantear: replantear
                     renumera, y entonces las imagenes ya generadas dejan de
                     corresponder con sus planos.
    """
    cuerpo = {"todo": True} if modo == "todo" else {}
    unidades = _plan_de_ejecucion(ctx, paso_id, cuerpo)
    opciones = dict(extra or {})
    if modo == "todo" and paso_id == "assets":
        # EL CORTE LO HACE LA TAREA `corte`, UNA VEZ POR TANDA, y por eso las
        # tareas de `assets` de una receta pasan `replantear: False` (gana sobre
        # este defecto). Replantear renumera los planos: si lo hicieran tambien
        # las de despues, la direccion y las cartelas —que se deciden POR
        # PLANO— acabarian apuntando a otros. Medido en la primera tanda de un
        # video nuevo: el corte dio 97 planos y la pasada de piezas 98.
        opciones.setdefault("replantear", True)
        opciones.setdefault("rehacer", True)
    return _correr_paso, (ctx, paso_id, unidades, opciones)


def _que_hace(tarea_id, ctx, receta, modo="pendientes", solo_montar=False):
    """(funcion, args) de una tarea. Levanta si la tarea no se sabe hacer.

    `solo_montar` solo lo entiende la tarea del MP4, y es la diferencia entre
    volver a dibujar los 98 planos en un navegador y volver a mezclar el audio
    sobre los clips que ya hay. Ver `repaso.solo_mezcla`.
    """
    if tarea_id == "ingesta":
        return _un_paso(ctx, "ingesta", modo)
    if tarea_id == "brief":
        return _un_paso(ctx, "brief", modo)
    if tarea_id == "guion":
        return _un_paso(ctx, "guion", modo)
    if tarea_id == "voz":
        return _un_paso(ctx, "voz", modo)
    if tarea_id == "revision_audio":
        return _un_paso(ctx, "revision_audio", modo)
    if tarea_id == "escenarios":
        return _correr_escenarios, (
            ctx, _ajuste_de_fase(receta, "catalogo_visual"), "", False)
    if tarea_id == "guia_estilo":
        return _correr_guia_estilo, (
            ctx, _referencias_de_estilo_o_400(ctx),
            _ajuste_de_fase(receta, "guia_estilo"))
    if tarea_id == "corte":
        return _correr_corte, (ctx, modo == "todo")
    if tarea_id == "plan_cartelas":
        return _correr_plan_cartelas, (ctx, _ajuste_de_fase(receta, "plan_cartelas"),
                                       True)
    if tarea_id == "direccion":
        return _correr_direccion, (ctx, _ajuste_de_fase(receta, "direccion"), True)
    if tarea_id == "piezas":
        # personajes y piezas de una vez: es lo que hace falta antes de los
        # planos, y por separado son dos botones porque cada uno paga lo suyo
        return _un_paso(ctx, "assets", modo,
                        {"tipos": ["reparto", "mapa", "grafico", "cabecera"],
                         "replantear": False})
    if tarea_id == "assets":
        return _un_paso(ctx, "assets", modo, {"replantear": False})
    if tarea_id == "callouts":
        return _un_paso(ctx, "callouts", modo)
    if tarea_id == "banda_sonora":
        return _correr_banda, (ctx, None)
    if tarea_id == "efectos":
        return _correr_surtir_efectos, (ctx, list(_sonido().PAPELES), False)
    if tarea_id == "render":
        return _un_paso(ctx, "render", modo,
                        {"solo_montar": True} if solo_montar else None)
    raise ErrorApi(500, f"la receta declara la tarea '{tarea_id}' y nadie sabe "
                        f"hacerla: falta cablearla en app.py")


def _esta_al_dia(ctx, tarea):
    """Si esta tarea ya esta hecha Y al dia, para 'Generar lo pendiente'.

    Se mira el ESTADO del paso al que pertenece, que es la unica verdad que el
    nucleo mantiene. Las tareas que no son pasos del grafo (el catalogo, la
    guia, los planes) se miran por su huella en los params: es lo mismo que
    hace la pantalla para pintar su pastilla.
    """
    tid = tarea["id"]
    if tid in PASOS_POR_ID:
        # `al_dia` y no `estado_de`: el trabajo de la tanda se registra EN UN
        # PASO, asi que preguntar por el estado devuelve "ejecutando" -- el
        # suyo propio -- y la tanda se rehacia a si misma entera.
        return ctx.estado.al_dia(tid)
    if tid == "escenarios":
        catalogo = (ctx.estado.params("assets") or {}).get("catalogo") or {}
        return bool(catalogo.get("sets") or catalogo.get("reparto"))
    if tid == "guia_estilo":
        return bool(((ctx.estado.params("assets") or {}).get("estilo") or {}).get("guia"))
    if tid == "corte":
        # AL DIA es que HAYA corte, no que sea el ultimo posible: cortar es
        # gratis y lo rehace `assets` de todas formas al generar. Lo que esto
        # evita es que una tanda «pendientes» vuelva a cortar cada vez.
        plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
        return bool(plan.get("escenas"))
    if tid == "plan_cartelas":
        unidades = (ctx.estado.params("assets") or {}).get("unidades") or {}
        return any((u or {}).get("cartela") for u in unidades.values())
    if tid == "direccion":
        unidades = (ctx.estado.params("assets") or {}).get("unidades") or {}
        return any((u or {}).get("direccion") for u in unidades.values())
    if tid == "piezas":
        # las piezas viven dentro de assets: si assets esta al dia, estan
        return ctx.estado.al_dia("assets")
    if tid == "banda_sonora":
        return bool((ctx.estado.params("render") or {}).get("musica"))
    if tid == "efectos":
        return bool((ctx.estado.params("render") or {}).get("efectos"))
    return False


def _tramos_por_tiempo(ctx, tandas, modo):
    """Que trozo de la barra se lleva cada tarea. -> {tid: (desde, ancho)}

    POR TIEMPO MEDIDO Y NO POR NUMERO DE TAREAS. Con un tramo igual para cada
    una, `corte` --49 s de historial-- ocupaba lo mismo que la tarea que dibuja
    los planos: la barra saltaba de golpe en las cortas y se quedaba clavada en
    la larga, que es justo el rato en el que alguien se pregunta si aquello
    sigue vivo. Un porcentaje que avanza a tirones no es un
    porcentaje, es un adorno.

    Los segundos salen de `_segundos_de_tarea`, que es EL MISMO sitio del que
    sale el «~50m» que se ensena antes de pulsar: asi lo prometido y lo pintado
    no pueden discrepar. Si el historial no sabe de una tarea, su peso es el
    reparto plano de siempre.

    Se calcula sobre las tareas que SE VAN A HACER, no sobre todas. La banda de
    cada pestana ya viene medida asi --`_plan_de_generacion` suma los segundos
    de las pendientes-- y repartir aqui sobre todas dejaria la barra sin llegar
    nunca al final de su banda: en una tanda retomada con cinco de doce tareas
    al dia, se quedaria a mitad y despues pegaria un salto al terminar.
    """
    # Y NADA DE ESTO PUEDE TUMBAR LA TANDA. Repartir la barra es un adorno
    # sobre el trabajo de verdad: si el plan no se puede leer --un proyecto a
    # medias, un fichero que falta-- se vuelve al reparto plano y se genera
    # igual. Reventar una tanda de cincuenta minutos por no saber pintar un
    # porcentaje seria el peor cambio posible.
    try:
        planos = _planos_previstos(ctx)
        brief = PASOS_MODULOS.comun.leer_salida(
            ctx.proyecto, "brief", "brief.json", obligatorio=False) or {}
    except Exception:                                         # noqa: BLE001
        return {}
    palabras = int(brief.get("presupuesto_palabras") or 0)
    orden = [tarea for tanda in tandas for tarea in tanda
             if not (modo == "pendientes" and _esta_al_dia(ctx, tarea))]
    if not orden:
        return {}
    reparto = {}
    for tarea in orden:
        if not tarea.get("fase"):
            reparto[tarea["paso"]] = reparto.get(tarea["paso"], 0) + 1
    pesos = []
    for tarea in orden:
        try:
            segundos = float(_segundos_de_tarea(ctx, tarea, planos, palabras,
                                                reparto, modo))
        except Exception:                                     # noqa: BLE001
            segundos = 0.0
        # un suelo para que una tarea sin historial no se quede con un tramo de
        # ancho cero, que en pantalla es una tarea que no existe
        pesos.append(max(segundos, 1.0))
    suma = sum(pesos) or float(len(orden))
    tramos, acumulado = {}, 0.0
    for tarea, peso in zip(orden, pesos):
        ancho = peso / suma
        tramos[tarea["id"]] = (acumulado, ancho)
        acumulado += ancho
    return tramos


def _correr_receta(avisar, ctx, pestana, receta, tareas, modo,
                   solo_montar=False, hechas_antes=0, total_global=0):
    """Recorre la receta: tanda a tanda, y dentro de una tanda a la vez.

    El progreso es por TAREA y no por tanda: lo que se lee en pantalla es
    «3 de 7 · Generar los planos», que es lo unico que dice de verdad por donde
    va. Dentro de una tarea, su propio progreso ocupa su tramo.

    Y SE CUENTA DOS VECES: el mensaje de casa con sus nombres y sus cifras, y el
    PUBLICO --«3 de 7 · Dibujando las escenas»-- para la pantalla que se graba
    (`recetas.PUBLICO`). Los dos salen del mismo sitio y a la vez, que es lo
    unico que impide que el segundo se quede viejo.

    `hechas_antes` y `total_global` existen para que ese contador publico no se
    reinicie a mitad: una tanda del modo light recorre dos pestanas seguidas
    (video y render) y sin esto la barra iba «7 de 8» y volvia a «1 de 3»,
    que en pantalla se lee como que algo ha fallado.
    """
    recetas = _recetas()
    tandas = recetas.tandas_de(pestana, tareas)
    # LA CUENTA ES DE LO QUE SE VA A HACER, NO DE LO QUE HAY EN LA RECETA.
    #
    # Contaba las once tareas de la tanda «El MP4» --las ocho de la pestana
    # Video mas las tres del render-- cuando en un video ya dibujado corren
    # tres: la barra decia «11 de 11» desde el primer minuto y llegaba al final
    # sin haberse movido. Y peor: las saltadas sumaban al contador, asi que
    # empezaba en «8 de 11» sin que nadie hubiera hecho nada.
    #
    # Se cuentan solo las que no estan al dia, que es exactamente lo que el
    # bucle de abajo va a correr y lo mismo que el plan promete antes de pulsar
    # (`_plan_de_generacion` suma los segundos de esas). Es la misma lista que
    # ya calcula `_tramos_por_tiempo` para repartir la barra, asi que las dos
    # cuentas no pueden discrepar.
    #
    # Y NUNCA CUENTA MENOS DE LAS QUE SALEN: si una tarea deja de estar al dia
    # mientras la tanda corre --una de aguas arriba la ha ensuciado-- el total
    # crece con ella. Un «4 de 3» seria peor que un total que se mueve.
    previstas = len([t for tanda in tandas for t in tanda
                     if not (modo == "pendientes" and _esta_al_dia(ctx, t))])
    total = previstas or 1
    tramos = _tramos_por_tiempo(ctx, tandas, modo)
    hechas = {"n": 0}
    cerrojo = threading.Lock()
    salida = {"tareas": [], "saltadas": [], "pestana": pestana,
              "receta": receta.get("nombre") or "Todo", "modo": modo}

    total_publico = total_global or total

    def correr(tarea):
        with cerrojo:
            hechas["n"] += 1
            indice = hechas["n"]
        desde, ancho = tramos.get(tarea["id"], ((indice - 1) / total, 1.0 / total))
        # LA FRASE PUBLICA SE RECUERDA. Hay pasos que avisan sin fraccion
        # (`avisar(None, "AVISO: ...")`) y ahi lo correcto es no moverla:
        # recalcularla con un cero la mandaria al principio de la tarea.
        ultimo = {"frase": recetas.publico_de(tarea["id"], 0.0)}

        # EL CONTADOR DE VERDAD LLEGA HASTA AQUI. Los pasos que trabajan pieza a
        # pieza avisan con (hechas, total) --ver `comun.avisador`-- y esa cuenta
        # manda sobre la fase inventada: «34 de 216 planos» esta medido y
        # «rematando los detalles» solo significa «va por el ultimo tercio».
        def avisar_tarea(valor, mensaje="", unidades=None):
            if valor is not None or unidades:
                ultimo["frase"] = recetas.publico_de(tarea["id"], valor,
                                                     unidades)
            avisar(desde + ancho * min(1.0, max(0.0, float(valor or 0))),
                   f"{indice} de {max(total, indice)} · {tarea['nombre']}"
                   + (f" — {mensaje}" if mensaje else ""),
                   f"{hechas_antes + indice}"
                   f" de {max(total_publico, hechas_antes + indice)}"
                   f" · {ultimo['frase']}")

        avisar_tarea(0.0, "")
        funcion, args = _que_hace(tarea["id"], ctx, receta, modo, solo_montar)
        arranque = time.time()
        resultado = funcion(avisar_tarea, *args)
        ficha = {"tarea": tarea["id"], "nombre": tarea["nombre"],
                 "segundos": round(time.time() - arranque, 1)}
        if isinstance(resultado, dict) and resultado.get("resumen"):
            ficha["resumen"] = str(resultado["resumen"])[:300]
        with cerrojo:
            salida["tareas"].append(ficha)
        ctx.bitacora.anotar("receta_tarea", tarea["paso"],
                            {"pestana": pestana, "tarea": tarea["id"],
                             "segundos": ficha["segundos"]})

    for tanda in tandas:
        # Lo de una tanda no depende entre si, asi que va a la vez. Con una sola
        # tarea se corre en este mismo hilo: montar un pool para una tarea es
        # ceremonia, y ademas conserva la traza del error tal cual.
        pendientes = []
        for tarea in tanda:
            if modo == "pendientes" and _esta_al_dia(ctx, tarea):
                # NO SUMA AL CONTADOR: una tarea saltada no es una tarea hecha,
                # y contarlas hacia que la barra arrancara por la mitad.
                with cerrojo:
                    salida["saltadas"].append(tarea["id"])
                continue
            pendientes.append(tarea)
        if not pendientes:
            continue
        if len(pendientes) == 1:
            correr(pendientes[0])
            continue
        with ThreadPoolExecutor(max_workers=len(pendientes)) as pool:
            futuros = [pool.submit(correr, t) for t in pendientes]
            for futuro in futuros:
                futuro.result()          # una excepcion sube y corta la receta

    # «LISTO» SOLO SI DE VERDAD SE ACABA AQUI. Una tanda del modo light recorre
    # dos pestanas seguidas, asi que al terminar la primera la barra decia
    # «Listo» y despues seguia con «3 de 5»: en pantalla eso se lee como que ha
    # acabado y ha vuelto a empezar. Vacio deja la frase anterior donde estaba.
    # `previstas` y no `total`: una pestana sin nada pendiente tiene previstas 0
    # --`total` lleva el suelo de 1-- y con el suelo diria «Listo» al pasar por
    # ella, con la pestana siguiente todavia por correr.
    avisar(1.0, f"{len(salida['tareas'])} tareas hechas"
                + (f", {len(salida['saltadas'])} ya estaban" if salida["saltadas"] else ""),
           PUBLICO_LISTO if hechas_antes + previstas >= total_publico else "")
    return salida


@app.get("/api/recetas")
def leer_recetas():
    """El catalogo de tareas por pestana y las recetas guardadas."""
    return _recetas().catalogo()


@app.post("/api/recetas")
def guardar_receta(cuerpo: dict = Body(default=None)):
    modulo = _recetas()
    try:
        return modulo.guardar(_cuerpo(cuerpo))
    except modulo.ErrorReceta as fallo:
        raise ErrorApi(400, str(fallo))


@app.delete("/api/recetas/{rid}")
def borrar_receta(rid: str):
    modulo = _recetas()
    try:
        modulo.borrar(rid)
    except modulo.ErrorReceta as fallo:
        raise ErrorApi(404, str(fallo))
    return {"borrada": rid}


@app.get("/api/proyectos/{pid}/pestanas/{pestana}")
def estado_de_pestana(pid: str, pestana: str):
    """Que le falta a esta pestana para estar terminada."""
    ctx = contexto(pid)
    recetas = _recetas()
    if pestana not in recetas.PESTANAS:
        raise ErrorApi(404, f"pestana desconocida: {pestana}. Son "
                            + ", ".join(recetas.PESTANAS))
    # la de ESTE video, no la del canal a secas: es la misma que va a correr la
    # tanda, y la unica diferencia entre las dos --la direccion de un video sin
    # planos-- es justo lo que esta pantalla tiene que decir bien
    receta = _receta_de_video(ctx, pestana)
    # LO MISMO QUE VA A CORRER, y por la misma funcion: la pantalla y la tanda
    # leian la receta cada una a su manera y no coincidian con una tarea que la
    # receta no nombra (ver `recetas.puestas_de`).
    puestas = recetas.puestas_de(pestana, receta)
    fichas = []
    for tarea in recetas.tareas_de(pestana):
        fichas.append({
            "id": tarea["id"], "nombre": tarea["nombre"], "paso": tarea["paso"],
            "cuesta": tarea["cuesta"], "opcional": tarea["opcional"],
            "porque": tarea.get("porque", ""),
            # LA FAMILIA A LA QUE PERTENECE, si pertenece a alguna. La pantalla
            # las pinta juntas en vez de como hermanas del resto: las dos de
            # sonido son ENTRADAS del MP4 -- salen a la red a traer material al
            # banco -- y leidas al mismo nivel que «El MP4» invitan a pensar que
            # el render ya no las usa. Las usa: se mezclan al muxear.
            "familia": tarea.get("familia") or None,
            "puesta": tarea["id"] in puestas,
            "al_dia": _esta_al_dia(ctx, tarea)})
    pendientes = [f for f in fichas if f["puesta"] and not f["al_dia"]]
    return {"pestana": pestana, "receta": receta, "tareas": fichas,
            "familias": recetas.FAMILIAS,
            "pendientes": [f["id"] for f in pendientes],
            "cuesta": any(f["cuesta"] for f in pendientes),
            # LO QUE VA A PARAR LA TANDA, ANTES DE PULSAR. Hay decisiones que la
            # receta NO puede tomar porque no son mecánicas —elegir los
            # fotogramas de estilo, aprobar el moodboard— y sin ellas una tarea
            # se planta con un 400 a los tres minutos, con la mitad hecha. Que
            # falle ahí es correcto; enterarse ahí, no (PENDIENTE §11).
            "impedimentos": _impedimentos(ctx, pestana, pendientes),
            "trabajo": (_trabajo_de_receta(ctx, pestana) or {})}


def _impedimentos(ctx, pestana, pendientes):
    """Lo que va a parar esta tanda, dicho ANTES de lanzarla.

    Cada entrada: {tarea, que, donde}. `donde` es la tarjeta donde se arregla,
    porque un aviso que no dice dónde se arregla es medio aviso — la misma
    lección que los avisos de cartela (§15).

    Sólo se mira lo que de verdad para: si la tarea no está pendiente, o está
    apagada, su requisito no importa.
    """
    ids = {f["id"] for f in pendientes}
    fuera = []
    if pestana != "video":
        return fuera
    if "guia_estilo" in ids:
        try:
            _referencias_de_estilo_o_400(ctx)
        except ErrorApi as fallo:
            fuera.append({"tarea": "guia_estilo", "que": fallo.mensaje,
                          "donde": "Estilo gráfico"})
    if "escenarios" in ids:
        guion = ctx.estado.params("guion") or {}
        if not (guion.get("bloques") or ctx.proyecto.version_activa("guion")):
            fuera.append({"tarea": "escenarios",
                          "que": "no hay guion todavía: sin él no hay nada que leer",
                          "donde": "la pestaña Guion"})
    return fuera


def _trabajo_de_receta(ctx, pestana):
    for ficha in ctx.gestor.listar(activos=True):
        if ficha.get("nombre") == f"receta:{pestana}":
            return ficha
    return None


@app.post("/api/proyectos/{pid}/pestanas/{pestana}/generar", status_code=202)
def generar_pestana(pid: str, pestana: str, cuerpo: dict = Body(default=None)):
    """Un boton: hace todo lo de esta pestana, en orden y en paralelo lo que se pueda.

    `modo` es 'todo' (rehace lo que haga falta) o 'pendientes' (se salta lo que
    ya esta hecho y al dia). El segundo es el que se usa despues de haber tocado
    tres cosas a mano: termina la pestana sin repetir -- ni volver a pagar --
    lo que ya estaba.
    """
    ctx = contexto(pid)
    recetas = _recetas()
    if pestana not in recetas.PESTANAS:
        raise ErrorApi(404, f"pestana desconocida: {pestana}. Son "
                            + ", ".join(recetas.PESTANAS))
    datos = _cuerpo(cuerpo)
    modo = str(datos.get("modo") or "pendientes").strip().lower()
    if modo not in ("todo", "pendientes"):
        raise ErrorApi(400, f"modo desconocido: {modo!r}. Usa 'todo' o 'pendientes'")
    try:
        receta = recetas.resolver(pestana, datos.get("receta"),
                                  datos.get("tareas"))
    except recetas.ErrorReceta as fallo:
        raise ErrorApi(400, str(fallo))

    activo = _trabajo_de_receta(ctx, pestana)
    if activo is not None:
        raise ErrorApi(409, f"la pestana '{pestana}' ya se esta generando",
                       {"trabajo_id": activo["id"], "progreso": activo["progreso"]})
    puestas = recetas.puestas_de(pestana, receta)
    orden = [t for t in recetas.orden_de(pestana, puestas)]
    if not orden:
        raise ErrorApi(400, "la receta no deja ninguna tarea que hacer")
    # Se comprueba ANTES de lanzar que las tareas se saben hacer y que lo que
    # necesitan esta: un 400 aqui es un mensaje; el mismo fallo dentro del hilo
    # es una barra que se pone roja a los tres minutos.
    #
    # Lo primero, el BLOQUEO. La receta llama a las funciones directamente y no
    # pasa por `lanzar_paso`, asi que no hereda su comprobacion: sin esto,
    # generar la pestana Video de un proyecto sin guion arrancaria y reventaria
    # dentro con un error del motor en vez de decir que falta el guion.
    # Lo que ESTA receta va a producir no cuenta como dependencia que falta: en
    # Voz, 'revision_audio' esta bloqueado hasta que corra 'voz', y las dos van
    # en la misma tanda.
    producidos = {t["paso"] for t in orden}
    for tarea in orden:
        paso = tarea["paso"]
        if ctx.estado.estado_de(paso) != "bloqueado":
            continue
        # `dependencias_que_faltan` y no la lista pelada: un video hecho de
        # material aportado no tiene ingesta y no le falta ninguna.
        faltan = dependencias_que_faltan(ctx, paso, producidos)
        if faltan:
            raise ErrorApi(409, f"'{pestana}' no se puede generar todavia: "
                                f"falta ejecutar " + ", ".join(faltan),
                           {"faltan": faltan, "tarea": tarea["id"]})
    for tarea in orden:
        if modo == "pendientes" and _esta_al_dia(ctx, tarea):
            continue
        _que_hace(tarea["id"], ctx, receta, modo)

    trabajo_id = ctx.gestor.lanzar(f"receta:{pestana}", _correr_receta, ctx,
                                   pestana, receta, puestas, modo,
                                   paso=orden[0]["paso"])
    _registrar_trabajo(trabajo_id, ctx.id)
    ctx.bitacora.anotar("receta_lanzada", orden[0]["paso"],
                        {"pestana": pestana, "modo": modo,
                         "receta": receta.get("nombre"),
                         "tareas": [t["id"] for t in orden]})
    return {"trabajo_id": trabajo_id, "pestana": pestana, "modo": modo,
            "receta": receta, "tareas": [t["id"] for t in orden],
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


# --------------------------------------------------------------------- claves
#
# Las claves de API y las cuentas, editables desde la pantalla. El almacen vive
# FUERA del arbol de codigo (`secretos/claves.json`, ver pasos/claves.py) y lo
# baja al navegador no lleva NUNCA una clave entera: etiqueta, los cuatro
# ultimos caracteres y el estado. Para editar la etiqueta de una cuenta sin
# tener su clave delante, el navegador manda el marcador CONSERVAR.


def _claves():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.claves


def _cuentas_de_imagen():
    """Como esta cada cuenta de OpenAI AHORA: sin saldo, limite medido, espera.

    Se pregunta al MOTOR y no al almacen porque lo interesante no es que claves
    hay escritas -- eso ya lo dice el almacen -- sino cuales estan generando. Si
    el motor no se puede cargar se devuelve vacio y la pantalla lo dice: un
    panel de claves que revienta porque falta PIL no ayuda a nadie.
    """
    try:
        motor = PASOS_MODULOS.medios.motor("imagen_openai/imagen.py")
        return list(motor.cuentas_para_la_pantalla())
    except SystemExit as fallo:
        # UNA INSTALACION RECIEN HECHA NO TIENE NINGUNA CLAVE, y eso no es un
        # fallo: es el estado de todo el mundo antes de poner la primera.
        #
        # El `except Exception` de abajo estaba escrito justo para esto y NO lo
        # cogia: los motores estan escritos como CLI y abortan con SystemExit,
        # que hereda de BaseException y no de Exception. Consecuencia medida en
        # un VPS recien instalado: `GET /api/claves` y `PUT /api/claves`
        # contestaban 500, y como la guia de inicio pasa por ahi, **la guia
        # entera moria en el paso 1** -- el de la cuenta de Claude, que no tiene
        # nada que ver con OpenAI. «Internal Server Error» y a callar.
        #
        # Sin clave la respuesta honesta es «ninguna cuenta», no un error.
        texto = str(fallo)
        if "OPENAI_API_KEY" in texto:
            return []
        return {"error": texto or "el motor de imagen aborto sin mensaje"}
    except Exception as fallo:  # noqa: BLE001
        return {"error": f"{type(fallo).__name__}: {fallo}"}


@app.get("/api/claves")
def leer_claves():
    """Que claves hay puestas, sin ninguna clave dentro."""
    ficha = _claves().resumen()
    ficha["cuentas_imagen"] = _cuentas_de_imagen()
    return ficha


@app.put("/api/claves")
def guardar_claves(cuerpo: dict = Body(default=None)):
    """Guarda las claves y espeja el .env que leen los motores.

    No hace falta reiniciar: el motor de imagen recarga sus cuentas cuando
    cambia el fichero, y el CLI lee su cuenta en cada llamada.
    """
    datos = _cuerpo(cuerpo)
    modulo = _claves()
    try:
        ficha = modulo.guardar(datos)
    except modulo.ErrorClaves as fallo:
        raise ErrorApi(400, str(fallo))
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido escribir el almacen de claves: {fallo}")
    anotar_global("claves_guardadas", {
        "openai": len(ficha["openai"]),
        "cartesia": ficha["cartesia"]["puesta"],
        "cuentas_cli": len(ficha["claude_cli"]["cuentas"])})
    ficha["cuentas_imagen"] = _cuentas_de_imagen()
    return ficha


# ---------------------------------------------------------------------------
# ENTRAR CON UNA CUENTA DEL CLI DESDE LA PANTALLA
#
# Una cuenta del CLI no es una clave que se pega: es un LOGIN. Hasta el
# 24-08-2026 la pantalla pedia la ruta de una carpeta y el texto de ayuda era un
# manual de tres pasos con una consola dentro. Aqui el login se hace entero
# desde el navegador: sale un enlace, se entra, se pega el codigo.
#
# EL ESTADO VIVO DEL INTENTO NO SE GUARDA EN DISCO NI VIAJA EN EL NAVEGADOR: vive
# en `login_cli._INTENTOS`, o sea en el proceso del servicio. Es lo que hace que
# recargar la pagina --o cambiar de video, que vacia `APP.vista`-- reencuentre el
# intento donde estaba en vez de perderlo. Y es lo que hace que apagar el
# servicio se lo lleve, que es justo lo que tiene que pasar con un login a medias.
#
# NO PASA POR EL GESTOR DE TRABAJOS a proposito, aunque parezca uno: los trabajos
# son de un PROYECTO (`ctx.gestor`) y un login es de la maquina. Ademas cada
# operacion aqui contesta en menos de dos segundos --arrancar tarda 0,4 s y pegar
# el codigo 1-- asi que no hay nada que seguir con una barra.
#
# 

#: El estado de sesion de cada cuenta, cacheado. `claude auth status` lanza un
#: proceso node y tarda unas decimas: sin cache, abrir el cajon de
#: configuracion serian N procesos encadenados DENTRO de la peticion, y ese
#: cajon se abre para mirar cualquier cosa, no solo las cuentas.
_ESTADO_CLI = {}
VIDA_ESTADO_CLI_S = 30


def _login_cli():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.login_cli


#: Lo que se contesta de una cuenta a la que todavia no se ha entrado.
SIN_SESION = {"conectada": False, "correo": "", "plan": "", "metodo": "",
              "error": ""}


def _sesion_de(cuenta, refrescar=False):
    """Con quien esta logueada una cuenta, sin preguntarlo mil veces."""
    login = _login_cli()
    # UNA CUENTA RECIEN ANADIDA NO ESTA LOGUEADA, aunque preguntar por ella
    # dijera que si: sin carpeta propia, `claude auth status` contesta por la
    # sesion POR DEFECTO, o sea que dos cuentas nuevas ensenarian el mismo
    # correo y las dos dirian «conectada». Eso no es un estado, es un espejismo.
    # Solo la entrada heredada --la que ya venia funcionando sin carpeta-- tiene
    # derecho a hablar por la sesion por defecto, y se reconoce porque tiene
    # `entrada` puesta.
    if not cuenta["config_dir"] and not cuenta["entrada"]:
        return dict(SIN_SESION)
    llave = cuenta["id"]
    ficha = _ESTADO_CLI.get(llave)
    if (not refrescar and ficha
            and time.time() - ficha["cuando"] < VIDA_ESTADO_CLI_S
            and ficha["carpeta"] == cuenta["config_dir"]):
        return ficha["sesion"]
    sesion = login.situacion(cuenta["config_dir"])
    _ESTADO_CLI[llave] = {"cuando": time.time(), "sesion": sesion,
                          "carpeta": cuenta["config_dir"]}
    return sesion


def _olvidar_sesion(cuenta_id):
    _ESTADO_CLI.pop(cuenta_id, None)


def _cuenta_cli(cid):
    """La ficha guardada de una cuenta, o 404."""
    for cuenta in _claves().cuentas_cli(solo_listas=False):
        if cuenta["id"] == cid:
            return cuenta
    raise ErrorApi(404, f"no hay ninguna cuenta del CLI con id '{cid}'")


def _cuentas_cli_para_pantalla(refrescar=False):
    login = _login_cli()
    salida = []
    for indice, cuenta in enumerate(_claves().cuentas_cli(solo_listas=False)):
        sesion = _sesion_de(cuenta, refrescar)
        salida.append({
            "id": cuenta["id"],
            "etiqueta": cuenta["etiqueta"],
            "orden": indice,
            "manda": indice == 0,
            # sin carpeta propia = la sesion por defecto del CLI, que es la
            # misma con la que el usuario tiene su consola abierta
            "propia": bool(cuenta["config_dir"]),
            "carpeta": cuenta["config_dir"],
            "guardada": cuenta["entrada"],
            "sesion": sesion,
            "intento": login.mirar(cuenta["id"]),
            # como respondio la ultima vez que se le hablo (cupo, sesion
            # caducada...): «con sesion» no es «funciona»
            "salud": _salud_cli().de(cuenta),
        })
    return salida


@app.post("/api/claves/probar")
def probar_claves(cuerpo: dict = Body(default=None)):
    """Prueba cada clave contra su servicio y dice cuál funciona de verdad.

    Llamadas de lectura que no cuestan dinero (pasos/comprobar_claves.py). Con
    {"claude": true} prueba también las cuentas de Claude con sesión, que es
    lo que más tarda. Es el botón «Probar todas» y la herramienta
    `probar_claves` del asistente.
    """
    datos = _cuerpo(cuerpo)
    con_claude = datos.get("claude") is not False
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    cuentas = []
    if con_claude:
        try:
            cuentas = [c for c in _candidatas_del_asistente()
                       if _sesion_de(c).get("conectada")]
        except Exception as fallo:  # noqa: BLE001
            raise ErrorApi(500, f"no se ha podido leer el almacen de claves: {fallo}")
    modulo = PASOS_MODULOS.comprobar_claves
    pruebas = modulo.probar_todas(cuentas_claude=cuentas, con_claude=con_claude)
    for cuenta in cuentas:
        if cuenta.get("id"):
            _olvidar_sesion(cuenta["id"])
    anotar_global("claves_probadas", {p["proveedor"]: p["estado"] for p in pruebas})
    return {"pruebas": pruebas, "resumen": modulo.resumen_texto(pruebas),
            "todo_bien": all(p["estado"] in ("ok", "sin_clave") for p in pruebas)}


@app.get("/api/claves/cli")
def leer_cuentas_cli(refrescar: int = 0):
    """Las cuentas del CLI en orden, con quién hay logueado en cada una."""
    return {"cuentas": _cuentas_cli_para_pantalla(bool(refrescar)),
            "max": _claves().MAX_CLI,
            "carpeta_base": _login_cli().CARPETA_CUENTAS}


@app.post("/api/claves/cli/{cid}/entrar")
def entrar_cuenta_cli(cid: str):
    """Arranca el acceso de esa cuenta y devuelve el enlace donde entrar."""
    modulo, login = _claves(), _login_cli()
    cuenta = _cuenta_cli(cid)
    carpeta = cuenta["config_dir"] or login.carpeta_de(cid)
    try:
        if not cuenta["config_dir"]:
            login.asegurar_carpeta(cid)
        # LA CARPETA SE APUNTA YA, PERO `entrada` SE QUEDA COMO ESTABA. Asi la
        # cuenta se acuerda de donde vive aunque el login se abandone a medias,
        # y mientras tanto NO entra en la cadena: `cli_claude.cuentas()` solo
        # coge las que tienen `entrada`. Una carpeta con un login a medias falla
        # de una forma que no se parece a nada.
        if carpeta != cuenta["config_dir"]:
            modulo.apuntar_cuenta_cli(cid, config_dir=carpeta)
        ficha = login.entrar(cid, carpeta)
    except modulo.ErrorClaves as fallo:
        raise ErrorApi(400, str(fallo))
    except login.ErrorLogin as fallo:
        raise ErrorApi(409, str(fallo))
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido preparar la carpeta de la "
                            f"cuenta: {fallo}")
    _olvidar_sesion(cid)
    anotar_global("cli_entrar", {"cuenta": cid, "estado": ficha["estado"]})
    return {"intento": ficha, "cuentas": _cuentas_cli_para_pantalla()}


@app.post("/api/claves/cli/{cid}/codigo")
def codigo_cuenta_cli(cid: str, cuerpo: dict = Body(default=None)):
    """Le pasa al CLI el código que devolvió la página de acceso."""
    modulo, login = _claves(), _login_cli()
    _cuenta_cli(cid)
    datos = _cuerpo(cuerpo)
    try:
        ficha = login.pegar(cid, datos.get("codigo"))
    except login.ErrorLogin as fallo:
        raise ErrorApi(409, str(fallo))
    _olvidar_sesion(cid)
    if ficha["estado"] == "dentro":
        # AHORA SI: la cuenta pasa a contar. Y solo ahora.
        try:
            modulo.apuntar_cuenta_cli(cid, entrada=True)
        except modulo.ErrorClaves as fallo:
            raise ErrorApi(400, str(fallo))
    anotar_global("cli_codigo", {"cuenta": cid, "estado": ficha["estado"]})
    return {"intento": ficha, "cuentas": _cuentas_cli_para_pantalla(True)}


@app.post("/api/claves/cli/{cid}/probar")
def probar_cuenta_cli(cid: str):
    """Le habla a esa cuenta con una llamada mínima y apunta cómo responde.

    Es lo que distingue «con sesión» de «funciona»: el cupo agotado, la sesión
    caducada o un CLI que no arranca solo se ven hablándole. Cuesta lo menos
    posible (haiku, esfuerzo bajo, una palabra) y falla rápido.
    """
    cuenta = _cuenta_cli(cid)
    if cuenta["config_dir"] and not cuenta["entrada"]:
        raise ErrorApi(409, "esta cuenta todavía no tiene sesión: entra primero")
    ficha = _salud_cli().probar(cuenta, para=f"probar la cuenta {cuenta['etiqueta'] or cid}")
    _olvidar_sesion(cid)
    anotar_global("cli_probar", {"cuenta": cid, "estado": ficha["estado"]})
    return {"salud": ficha, "cuentas": _cuentas_cli_para_pantalla(True)}


@app.delete("/api/claves/cli/{cid}/entrar")
def cancelar_cuenta_cli(cid: str):
    """Tira el acceso a medias de esa cuenta."""
    _cuenta_cli(cid)
    habia = _login_cli().cancelar(cid)
    return {"cancelado": habia, "cuentas": _cuentas_cli_para_pantalla()}


@app.post("/api/claves/cli/{cid}/salir")
def salir_cuenta_cli(cid: str):
    """Cierra la sesión de esa cuenta, sin quitarla de la lista."""
    modulo, login = _claves(), _login_cli()
    cuenta = _cuenta_cli(cid)
    login.cancelar(cid)
    try:
        ok, dicho = login.salir(cuenta["config_dir"])
    except login.ErrorLogin as fallo:
        raise ErrorApi(409, str(fallo))
    try:
        modulo.apuntar_cuenta_cli(cid, entrada=False)
    except modulo.ErrorClaves as fallo:
        raise ErrorApi(400, str(fallo))
    _olvidar_sesion(cid)
    _salud_cli().olvidar(cuenta)
    anotar_global("cli_salir", {"cuenta": cid, "ok": ok})
    return {"ok": ok, "dicho": dicho, "cuentas": _cuentas_cli_para_pantalla(True)}


# ------------------------------------------------------------------ asistente
#
# El chat de la burbuja de abajo a la derecha (pasos/asistente.py). Aqui vive lo
# unico que ese modulo no puede hacer solo: la FOTO del estado, porque los
# contextos, los gestores de trabajos y las claves son de este proceso.
#
# NO PASA POR EL GESTOR DE TRABAJOS por lo mismo que el login: un trabajo es de
# un PROYECTO y una charla es de la maquina (se puede preguntar sin ningun video
# abierto). Corre en su hilo y la pantalla sigue la charla preguntando por ella:
# la respuesta puede tardar un minuto, y detras de un proxy una peticion de un
# minuto se corta a los sesenta segundos sin decir por que.

def _asistente():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.asistente


def _salud_cli():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.salud_cli


#: Con que se pregunta por la sesion POR DEFECTO del CLI (~/.claude), que es
#: con la que corre el Estudio cuando el almacen de claves no tiene ninguna
#: cuenta (`cli_claude.cuentas`). Lleva `entrada` para que `_sesion_de` acepte
#: hablar por ella: solo la entrada heredada tiene ese derecho.
_CUENTA_POR_DEFECTO_CLI = {"id": "__defecto__", "etiqueta": "", "config_dir": "",
                           "entrada": True}


def _candidatas_del_asistente():
    """Las cuentas con las que hablaria el motor, en su orden. -> [ficha]

    Es exactamente la regla de `cli_claude.cuentas()`: las que tienen
    `entrada`, y SIN NINGUNA usable, la sesion por defecto del CLI. Una cuenta
    anadida y nunca logueada no cuenta ni aqui ni alli: si esto dijera «no»
    cuando el motor va a contestar, el asistente estaria cerrado justo en la
    maquina donde el Estudio lleva generando desde el primer dia.
    """
    cuentas = _claves().cuentas_cli(solo_listas=False)
    usables = [c for c in cuentas if c["entrada"]]
    if usables:
        return usables
    return [dict(_CUENTA_POR_DEFECTO_CLI, etiqueta="la sesión por defecto del CLI")]


def _asistente_listo():
    """Si el asistente puede contestar AHORA.

    -> (listo, motivo, cuenta, cuentas, sin_probar)

    «Con sesion» no basta: una cuenta logueada con el cupo agotado no contesta.
    Por eso cada candidata lleva su SALUD (pasos/salud_cli.py, lo ultimo que
    paso al hablarle) y solo cuenta como buena la que tiene sesion y no tiene
    apuntado un fallo. `sin_probar` dice si alguna buena no se ha probado
    nunca: la pantalla la prueba sola al abrir la burbuja.
    """
    salud = _salud_cli()
    try:
        candidatas = _candidatas_del_asistente()
    except ErrorApi:
        raise
    except Exception as fallo:  # noqa: BLE001
        return False, f"no se ha podido leer el almacen de claves: {fallo}", None, [], False
    fichas, sin_probar = [], False
    for cuenta in candidatas:
        sesion = _sesion_de(cuenta)
        ficha_salud = salud.de(cuenta)
        por_defecto = cuenta.get("id") == _CUENTA_POR_DEFECTO_CLI["id"]
        ficha = {
            "id": "" if por_defecto else cuenta["id"],
            "etiqueta": cuenta.get("etiqueta") or sesion.get("correo") or cuenta.get("id"),
            "correo": sesion.get("correo", ""),
            "plan": sesion.get("plan", ""),
            "sesion": bool(sesion.get("conectada")),
            "salud": ficha_salud,
            "motivo": "",
        }
        if not sesion.get("conectada"):
            ficha["motivo"] = (sesion.get("error")
                               or ("todavía no has entrado con tu cuenta de Claude"
                                   if por_defecto else
                                   f"la cuenta «{ficha['etiqueta']}» no tiene sesión"))
        elif (ficha_salud or {}).get("estado") in ("cupo", "sesion", "tiempo", "error"):
            ficha["motivo"] = salud.describir(ficha_salud, ficha["etiqueta"])
        elif ficha_salud is None:
            sin_probar = True
        fichas.append(ficha)
    buenas = [f for f in fichas if not f["motivo"]]
    if buenas:
        return True, "", buenas[0], fichas, sin_probar
    motivo = ("; ".join(f["motivo"] for f in fichas)
              or "todavía no has entrado con tu cuenta de Claude")
    return False, motivo, None, fichas, sin_probar


def _foto_para_asistente(pid, pantalla=None):
    """El estado del Estudio ahora mismo, en texto, para el asistente.

    Cada trozo va protegido por su cuenta: que no se pueda leer el coste no
    puede dejar sin contestar una pregunta sobre las claves. Y aqui no viaja
    NINGUNA clave: solo si esta puesta o no.
    """
    lineas = [f"fecha y hora: {ahora()}"]
    simulado = str(os.environ.get("ESTUDIO_SIMULAR", "")).strip() in ("1", "true", "si")
    lineas.append(
        f"servicio: version {VERSION}; carpeta de proyectos {raiz_proyectos()}; "
        f"pasos cargados: {'si' if PASOS_MODULOS is not None else 'NO (' + ERROR_PASOS + ')'}; "
        f"modo simulado: {'si' if simulado else 'no'}")

    # -- claves y cuentas (sin ninguna clave dentro)
    try:
        resumen = _claves().resumen()
        lineas.append("claves: OpenAI (imagenes) "
                      + ("puesta" if resumen["openai"] else
                         "SIN PONER (sin ella no se generan imagenes)")
                      + "; Cartesia (voz) "
                      + ("puesta" if resumen["cartesia"]["puesta"] else "sin poner")
                      + "; Jamendo (musica) "
                      + ("puesta" if resumen["jamendo"]["puesta"] else "sin poner")
                      + "; FreeSound (efectos) "
                      + ("puesta" if resumen["freesound"]["puesta"] else "sin poner"))
        cuentas = _cuentas_cli_para_pantalla()
        if not any(c.get("guardada") for c in cuentas):
            sesion = _sesion_de(_CUENTA_POR_DEFECTO_CLI)
            lineas.append("cuentas de Claude (CLI): ninguna con sesion hecha en el "
                          "almacen; se usa la sesion por defecto del CLI, que "
                          + (f"esta conectada como {sesion.get('correo') or '?'}"
                             f" ({sesion.get('plan') or 'plan ?'})"
                             if sesion.get("conectada") else "NO tiene sesion"))
        for cuenta in cuentas:
            sesion = cuenta.get("sesion") or {}
            intento = cuenta.get("intento") or {}
            lineas.append(
                f"cuenta de Claude '{cuenta['etiqueta'] or cuenta['id']}'"
                f"{' (manda)' if cuenta.get('manda') else ''}: "
                + (f"con sesion como {sesion.get('correo') or '?'} "
                   f"({sesion.get('plan') or 'plan ?'})"
                   if sesion.get("conectada") else "sin sesion")
                + (f"; acceso en curso en estado '{intento.get('estado')}'"
                   if intento else "")
                + (f"; ultima llamada: {_salud_cli().describir(cuenta.get('salud'))}"
                   if cuenta.get("salud") else ""))
    except Exception as fallo:  # noqa: BLE001
        lineas.append(f"claves: no se han podido leer ({fallo})")

    try:
        ajustes = AJUSTES.leer()
        lineas.append(f"ajustes: calidad de imagen para los videos nuevos = "
                      f"{ajustes['calidad_imagen']}; guia de inicio vista = "
                      f"{'si' if ajustes.get('onboarding_visto') else 'no'}")
    except Exception as fallo:  # noqa: BLE001
        lineas.append(f"ajustes: no se han podido leer ({fallo})")

    # -- los proyectos que hay
    try:
        fichas = [f for f in Proyecto.listar(raiz_proyectos())
                  if not f.get(CONFIG_TALLER)]
        lineas.append(f"proyectos (videos): {len(fichas)}")
        for ficha in fichas[:15]:
            lineas.append(f"  - {ficha.get('id')} «{ficha.get('nombre')}», "
                          f"actualizado {ficha.get('actualizado') or '?'}")
    except Exception as fallo:  # noqa: BLE001
        lineas.append(f"proyectos: no se han podido listar ({fallo})")

    # -- el proyecto que la pantalla tiene abierto
    pid = str(pid or "").strip()
    if pid:
        try:
            ctx = contexto(pid)
            lineas.append(f"\nPROYECTO ABIERTO EN PANTALLA: {ctx.id} "
                          f"«{ctx.proyecto.config.get('nombre', ctx.id)}» "
                          f"(carpeta {ctx.proyecto.raiz})")
            for paso in PASOS:
                ficha = ficha_paso(ctx, paso["id"])
                trabajo = ficha.get("trabajo") or {}
                lineas.append(
                    f"  paso {paso['id']}: estado {ficha['estado']}"
                    + (f", version activa v{ficha['version']}" if ficha.get("version") else ", sin version")
                    + (f", {len(ficha.get('unidades') or [])} unidades" if ficha.get("por_unidades") else "")
                    + (f", {len(ficha.get('unidades_obsoletas') or [])} obsoletas"
                       if ficha.get("unidades_obsoletas") else "")
                    + (f", {len(ficha.get('unidades_sin_hacer') or [])} sin hacer"
                       if ficha.get("unidades_sin_hacer") else "")
                    + (f"; mensaje: {ficha['mensaje']}" if ficha.get("mensaje") else "")
                    + (f"; TRABAJO EN MARCHA {trabajo.get('id')} al "
                       f"{round(100 * float(trabajo.get('progreso') or 0))} %: "
                       f"{trabajo.get('mensaje') or ''}" if trabajo else ""))
            trabajos = ctx.gestor.listar(activos=False)[:10]
            if trabajos:
                lineas.append("  ultimos trabajos (el mas reciente primero):")
                for t in trabajos:
                    lineas.append(
                        f"    - {t.get('nombre')} [{t.get('paso')}] {t.get('estado')}"
                        f" ({t.get('segundos')} s)"
                        + (f", mensaje: {t.get('mensaje')}" if t.get("mensaje") else "")
                        + (f", ERROR: {str(t.get('error'))[:700]}" if t.get("error") else ""))
            eventos = ctx.bitacora.leer(limite=40)
            if eventos:
                lineas.append("  ultimos eventos de la bitacora del proyecto:")
                for ev in eventos:
                    lineas.append("    " + ctx.bitacora._linea_evento(ev))
            try:
                coste = medidor(ctx).total()
                lineas.append(f"  coste del video: {coste.get('cabecera') or coste.get('total_usd')}")
            except Exception as fallo:  # noqa: BLE001
                lineas.append(f"  coste del video: no se ha podido leer ({fallo})")
        except ErrorApi as fallo:
            lineas.append(f"\nproyecto abierto en pantalla: {pid} -> {fallo.mensaje}")
        except Exception as fallo:  # noqa: BLE001
            lineas.append(f"\nproyecto abierto en pantalla: {pid} -> no se ha "
                          f"podido leer ({fallo})")

    # -- trabajos vivos en cualquier proyecto abierto por el servicio
    try:
        with _LOCK:
            vivos = [(p, _CONTEXTOS[p]) for p in list(_CONTEXTOS) if p != pid]
        for otro, ctx in vivos:
            for t in ctx.gestor.listar(activos=True):
                lineas.append(f"trabajo en marcha en OTRO proyecto ({otro}): "
                              f"{t.get('nombre')} [{t.get('paso')}] al "
                              f"{round(100 * float(t.get('progreso') or 0))} %: "
                              f"{t.get('mensaje') or ''}")
    except Exception as fallo:  # noqa: BLE001
        lineas.append(f"trabajos de otros proyectos: no se han podido leer ({fallo})")

    # -- lo ultimo que paso en la maquina
    try:
        globales = leer_jsonl(RUTA_BITACORA_GLOBAL)[-15:]
        if globales:
            lineas.append("\nultimos eventos globales (todos los proyectos):")
            for ev in globales:
                datos = ev.get("datos") if isinstance(ev.get("datos"), dict) else {}
                resumen = ", ".join(f"{k}={str(v)[:80]}" for k, v in sorted(datos.items()))
                lineas.append(f"  {ev.get('fecha', '?')}  {ev.get('evento', '?')}"
                              + (f" [{ev.get('proyecto')}]" if ev.get("proyecto") else "")
                              + (f"  {resumen[:240]}" if resumen else ""))
    except Exception as fallo:  # noqa: BLE001
        lineas.append(f"bitacora global: no se ha podido leer ({fallo})")

    # -- lo que la pantalla tiene delante
    if isinstance(pantalla, dict):
        lineas.append("\nLO QUE LA PERSONA TIENE EN PANTALLA:")
        if pantalla.get("pestana"):
            lineas.append(f"  pestana: {pantalla['pestana']}")
        if pantalla.get("url"):
            lineas.append(f"  url: {str(pantalla['url'])[:300]}")
        errores = pantalla.get("errores")
        if isinstance(errores, dict) and errores:
            lineas.append("  errores a la vista (por paso):")
            for paso, texto in list(errores.items())[:8]:
                lineas.append(f"    - {paso}: {str(texto)[:800]}")
    return "\n".join(lineas)


@app.get("/api/asistente")
def estado_asistente():
    """Si el asistente puede contestar ahora, y con qué cuenta."""
    modulo = _asistente()
    listo, motivo, cuenta, cuentas, sin_probar = _asistente_listo()
    return {"listo": listo, "motivo": motivo, "cuenta": cuenta,
            "cuentas": cuentas, "sin_probar": sin_probar,
            "modelo": modulo.MODELO, "esfuerzo": modulo.ESFUERZO,
            "simulado": modulo.simulado()}


@app.post("/api/asistente/probar")
def probar_asistente():
    """Prueba las cuentas con las que contestaría el asistente y dice cómo están.

    Una llamada mínima por cuenta con sesión, en el orden de la cadena. Es lo
    que hace que un cupo agotado se vea ANTES de preguntar y no como un error
    a mitad de la charla.
    """
    salud = _salud_cli()
    try:
        candidatas = _candidatas_del_asistente()
    except ErrorApi:
        raise
    except Exception as fallo:  # noqa: BLE001
        raise ErrorApi(500, f"no se ha podido leer el almacen de claves: {fallo}")
    probadas = []
    for cuenta in candidatas:
        if not _sesion_de(cuenta).get("conectada"):
            continue
        ficha = salud.probar(cuenta, para="comprobar el asistente")
        probadas.append({"id": cuenta.get("id"), "estado": ficha["estado"]})
        if cuenta.get("id"):
            _olvidar_sesion(cuenta["id"])
    anotar_global("asistente_probar", {"cuentas": probadas})
    ficha = estado_asistente()
    ficha["probadas"] = probadas
    return ficha


@app.get("/api/asistente/foto")
def foto_del_asistente(proyecto: str = Query(default=""),
                       pestana: str = Query(default=""),
                       error: str = Query(default="")):
    """Lo que el asistente ve del Estudio ahora mismo, en texto y sin claves.

    Es EXACTAMENTE lo que va delante de cada pregunta. Existe para poder
    mirarlo -- y para que la prueba de la API compruebe que lleva el proyecto
    abierto y no lleva ninguna clave -- sin tener que preguntar nada.
    """
    pantalla = {}
    if pestana:
        pantalla["pestana"] = pestana
    if error:
        pantalla["errores"] = {"pantalla": error}
    foto = _foto_para_asistente(proyecto, pantalla or None)
    return {"foto": foto, "caracteres": len(foto)}


@app.post("/api/asistente/charlas", status_code=201)
def abrir_charla():
    """Abre una charla vacía con el asistente."""
    charla = _asistente().nueva()
    anotar_global("asistente_charla", {"charla": charla.id})
    return charla.ver()


def _charla_o_404(cid):
    charla = _asistente().obtener(cid)
    if charla is None:
        raise ErrorApi(404, f"no hay ninguna charla '{cid}': se habrá cerrado "
                            f"o el servicio se ha reiniciado. Abre una nueva.")
    return charla


@app.get("/api/asistente/charlas/{cid}")
def leer_charla(cid: str):
    """Los turnos de una charla; el último dice si sigue pensando."""
    return _charla_o_404(cid).ver()


@app.post("/api/asistente/charlas/{cid}/mensajes", status_code=202)
def preguntar_al_asistente(cid: str, cuerpo: dict = Body(default=None)):
    """Manda una pregunta; la respuesta se sigue con GET de la charla."""
    modulo = _asistente()
    charla = _charla_o_404(cid)
    datos = _cuerpo(cuerpo)
    texto = str(datos.get("texto") or "").strip()
    if not texto:
        raise ErrorApi(400, "escribe algo que preguntar")
    # SIN SESION NO SE PREGUNTA, y se dice antes de lanzar nada: el CLI
    # tardaria medio minuto en fallar con un mensaje que no se parece a nada.
    listo, motivo, _, _, _ = _asistente_listo()
    if not listo and not modulo.simulado():
        raise ErrorApi(409, f"el asistente no puede contestar todavía: {motivo}")
    pid = str(datos.get("proyecto") or "").strip()
    foto = _foto_para_asistente(pid, datos.get("pantalla"))
    try:
        ficha = charla.preguntar(texto, foto, raiz=RAIZ_ESTUDIO,
                                 carpetas_extra=(raiz_proyectos(),), pid=pid)
    except modulo.Ocupada as fallo:
        raise ErrorApi(409, str(fallo))
    except modulo.ErrorAsistente as fallo:
        raise ErrorApi(400, str(fallo))
    anotar_global("asistente_pregunta", {"charla": cid, "proyecto": pid or None,
                                         "caracteres": len(texto)})
    return ficha


@app.post("/api/asistente/charlas/{cid}/cancelar")
def cancelar_asistente(cid: str):
    """Para la respuesta que esté en marcha en esa charla."""
    charla = _charla_o_404(cid)
    habia = charla.cancelar()
    return {"cancelado": habia, "charla": charla.ver()}


@app.delete("/api/asistente/charlas/{cid}")
def cerrar_charla(cid: str):
    """Cierra una charla; lo que estuviera contestando se cancela."""
    return {"cerrada": _asistente().olvidar(cid)}


# ----------------------------------------------------------- presets de canal
# Lo que se decide una vez por canal (idioma, estilo grafico, ritmo, voz) y se
# repite igual en todos sus videos. Viven FUERA de los proyectos porque un canal
# sobrevive a cualquier video suyo.
#
# Aplicar COPIA los valores a los params del paso que toque; no se guarda el
# nombre del preset en ningun sitio. Asi, borrar un preset no puede romper un
# video ya terminado -- que es justo lo que pasa con los presets de voz escritos
# en el codigo, donde un nombre desconocido lanza ValueError.

def _presets():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.presets_canal


def _preset_o_400(tarea):
    """Traduce el fallo del modulo a un 400 con su mensaje, no a un 500 mudo."""
    presets = _presets()
    try:
        return tarea(presets)
    except presets.ErrorPreset as fallo:
        raise ErrorApi(400, str(fallo))


@app.get("/api/presets-canal")
def listar_presets_canal():
    """Presets guardados, agrupados por tipo, mas su papelera y el catalogo."""
    return _preset_o_400(lambda p: p.listar())


@app.post("/api/presets-canal")
def guardar_preset_canal(cuerpo: dict = Body(default=None)):
    """Guarda un preset nuevo, o sustituye el contenido de uno que ya existe."""
    datos = _cuerpo(cuerpo)
    ficha = _preset_o_400(lambda p: p.guardar(
        datos.get("tipo"), datos.get("nombre"), datos.get("datos"),
        nota=datos.get("nota") or "", miniatura=datos.get("miniatura") or "",
        pid=datos.get("id") or None))
    anotar_global("preset_guardado", {"id": ficha["id"], "tipo": ficha["tipo"],
                                      "nombre": ficha["nombre"]})
    return {"preset": ficha, **_presets().listar()}


@app.patch("/api/presets-canal/{pid}")
def renombrar_preset_canal(pid: str, cuerpo: dict = Body(default=None)):
    """Cambia solo el nombre o la nota. Lo que el preset guarda no se toca."""
    datos = _cuerpo(cuerpo)
    ficha = _preset_o_400(lambda p: p.renombrar(
        pid, nombre=datos.get("nombre"), nota=datos.get("nota")))
    anotar_global("preset_renombrado", {"id": pid, "nombre": ficha["nombre"]})
    return {"preset": ficha, **_presets().listar()}


@app.get("/api/presets-canal/{pid}/miniatura")
def miniatura_preset_canal(pid: str, peticion: Request):
    """La cara del preset en el desplegable: uno de sus propios fotogramas."""
    ficha = _preset_o_400(lambda p: p.leer(pid))
    presets = _presets()
    # LA RUTA GUARDADA NO SE USA TAL CUAL, solo su nombre: la miniatura vive
    # dentro de la carpeta del preset y solo ahi, asi que una ficha escrita en
    # otra maquina --o antes de mover el banco-- trae una ruta que aqui no
    # existe. `ruta_de_miniatura` la vuelve a pegar a la carpeta de ahora.
    ruta = presets.ruta_de_miniatura(ficha)
    # y se comprueba igual que antes: la ficha es un JSON que alguien puede
    # editar a mano, y una ruta suelta serviria cualquier fichero del disco
    carpeta = os.path.abspath(presets.carpeta_de(pid))
    if not ruta or not os.path.abspath(ruta).startswith(carpeta + os.sep):
        raise ErrorApi(404, f"el preset {pid} no tiene miniatura")
    if not os.path.isfile(ruta):
        raise ErrorApi(404, f"la miniatura del preset {pid} ya no esta en el disco")
    return servir_fichero(peticion, ruta)


@app.get("/api/presets-canal/{pid}/fichero/{archivo:path}")
def fichero_preset_canal(pid: str, archivo: str, peticion: Request):
    """Un fichero de la carpeta del preset (fotogramas, laminas del moodboard).

    Existe para poder PREVISUALIZAR un preset entero: sus referencias viven en
    banco/presets/<id>/ y, sin esto, la unica cara visible era la miniatura y
    el resto se listaba como rutas de texto.
    """
    _preset_o_400(lambda p: p.leer(pid))
    presets = _presets()
    carpeta = os.path.abspath(presets.carpeta_de(pid))
    try:
        destino = ruta_contenida(carpeta, archivo)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    if not os.path.isfile(destino):
        raise ErrorApi(404, f"el preset {pid} no tiene el fichero {archivo!r}")
    return servir_fichero(peticion, destino)


@app.delete("/api/presets-canal/{pid}")
def apartar_preset_canal(pid: str):
    """A la papelera. No borra nada: la ficha y sus fotogramas siguen enteros."""
    ficha = _preset_o_400(lambda p: p.apartar(pid))
    anotar_global("preset_apartado", {"id": pid, "tipo": ficha.get("tipo"),
                                      "nombre": ficha.get("nombre")})
    return {"apartado": pid, "preset": ficha,
            "aviso": "sigue entero en la papelera; se puede devolver",
            **_presets().listar()}


@app.post("/api/presets-canal/papelera/{pid}/restaurar")
def restaurar_preset_canal(pid: str):
    """Devuelve a la lista un preset apartado."""
    ficha = _preset_o_400(lambda p: p.restaurar(pid))
    return {"restaurado": pid, "preset": ficha, **_presets().listar()}


@app.get("/api/presets-canal/papelera/{pid}")
def peso_preset_canal(pid: str):
    """Que hay dentro de un preset apartado, para decir que se pierde."""
    return _preset_o_400(lambda p: p.peso(pid))


@app.delete("/api/presets-canal/papelera/{pid}")
def borrar_preset_canal(pid: str, confirmar: int = Query(default=0)):
    """Borrado definitivo. Solo alcanza a lo que ya esta en la papelera."""
    salida = _preset_o_400(lambda p: p.borrar(pid, confirmar=bool(confirmar)))
    anotar_global("preset_borrado", salida)
    return {**salida, **_presets().listar()}


@app.post("/api/proyectos/{pid}/presets-canal/{preset_id}/aplicar")
def aplicar_preset_canal(pid: str, preset_id: str):
    """Copia los valores del preset a los params de los pasos que toque.

    Se aplica en el SERVIDOR y no en la interfaz porque quien sabe que clave va
    a que paso es el catalogo de tipos, y porque el estilo tiene que fusionarse
    con lo que ya hubiera en assets.estilo (el prompt escrito a mano de los
    proyectos antiguos vive ahi). Repartir esa regla entre los dos lados es como
    se acaba con dos versiones que se contradicen.
    """
    ctx = contexto(pid)
    presets = _presets()
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    actuales = {paso: (ctx.estado.params(paso) or {})
                for paso in presets.TIPOS[ficha["tipo"]]["pasos"]}
    cambios = _preset_o_400(lambda p: p.cambios_para(ficha, actuales))
    # Las referencias dibujadas que guarda el preset vuelven al banco global si
    # alli ya no estan. Normalmente no hace nada: la clave sale de la huella de
    # los fotogramas, y los del preset son copia byte a byte de los originales.
    devueltas = presets.restaurar_moodboard(ficha)

    # actualizar_params devuelve si el paso ha cambiado de firma de verdad:
    # aplicar un preset que ya estaba puesto no obsoleta nada, y decirlo evita
    # el aviso de "queda obsoleto todo" cuando no ha pasado nada
    cambiados = {paso: bool(ctx.estado.actualizar_params(paso, valores))
                 for paso, valores in cambios.items()}
    ctx.bitacora.anotar("preset_aplicado", None, {
        "id": preset_id, "tipo": ficha["tipo"], "nombre": ficha.get("nombre"),
        "pasos": sorted(cambios),
        "cambiados": sorted(p for p, c in cambiados.items() if c)})
    afectados = {p for p, c in cambiados.items() if c}
    return {
        "aplicado": preset_id, "preset": presets.publicar(ficha),
        "moodboard_devuelto": devueltas.get("ejes") or [],
        "pasos": sorted(cambios), "cambiados": cambiados,
        "estado": {paso: ctx.estado.estado_de(paso) for paso in cambios},
        "aguas_abajo": sorted({h for paso in afectados for h in descendientes_de(paso)}
                              - afectados),
    }


# ==========================================================================
# MODO LIGHT: el preset de canal entero, de una tirada
#
# La tabla de tareas, los tiempos y la miniatura viven en `pasos/presets_light`;
# aqui vive lo unico que no cabe alli: QUE FUNCION corre cada tarea. Y es a
# proposito la MISMA que corre su boton del modo editor -- no hay un camino
# "automatico" y otro "a mano", porque entonces habria dos comportamientos que
# mantener y uno de los dos se quedaria viejo. Misma regla que las recetas.
#
# EL TALLER. Todo esto necesita un proyecto: ahi viven los fotogramas, los params
# y la bitacora. Asi que cada preset tiene el suyo, oculto de la lista de
# proyectos (`config['taller_de_preset']`) y borrado con el. Que se quede
# despues de guardar es lo que hace barato corregir: rehacer la guia no vuelve a
# bajar el video.
# ==========================================================================

CONFIG_TALLER = "taller_de_preset"


def _light():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.presets_light


def _encargo_o_400(cuerpo):
    try:
        return _light().validar_encargo(cuerpo)
    except Exception as fallo:                              # noqa: BLE001
        raise ErrorApi(400, str(fallo))


def _crear_taller(encargo):
    """Un proyecto oculto donde generar este preset. -> ctx"""
    os.makedirs(raiz_proyectos(), exist_ok=True)
    base = f"taller {encargo['nombre']}"[:60]
    nombre, intento = base, 1
    while os.path.isdir(os.path.join(raiz_proyectos(), identificador(nombre))):
        intento += 1
        nombre = f"{base} {intento}"
    try:
        proyecto = Proyecto.crear(raiz_proyectos(), nombre)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido crear el taller del preset: {fallo}")
    ctx = contexto(proyecto.id)
    ctx.proyecto.config[CONFIG_TALLER] = True
    ctx.proyecto.guardar_config()
    return ctx


#: Donde esperan las imagenes que se suben junto a una descripcion, ANTES de que
#: exista el taller. Se suben mientras se rellena el formulario y el taller no
#: nace hasta pulsar «Generar», asi que hace falta un sitio intermedio; al crear
#: el preset se copian dentro del taller y esto se vacia.
CARPETA_APORTADAS = "_imagenes_aportadas"

#: Lo que se acepta subir. Las mismas que sabe abrir el CLI y que sabe
#: normalizar el motor de imagen.
EXT_APORTADAS = (".png", ".jpg", ".jpeg", ".webp")

#: Tope por fichero. Un fotograma de un video pesa decimas de mega; diez son de
#: sobra para una captura de pantalla o una foto de movil, y ponen un techo a lo
#: que puede llenar el disco alguien que arrastre una carpeta entera.
MAX_BYTES_APORTADA = 10 * 1024 * 1024


def _carpeta_aportadas():
    return os.path.join(raiz_proyectos(), CARPETA_APORTADAS)


def _rutas_aportadas(nombres):
    """De los nombres que devolvio la subida a rutas de verdad. -> [rutas]

    Se valida el nombre y se comprueba que el fichero este: lo que llega es una
    lista que ha viajado por el navegador, y componer una ruta con ella sin
    mirar es como se sale de la carpeta.
    """
    carpeta = _carpeta_aportadas()
    rutas = []
    for nombre in nombres or []:
        limpio = os.path.basename(str(nombre or "").strip())
        if not limpio or not FICHERO_WEB.match(limpio):
            continue
        ruta = os.path.join(carpeta, limpio)
        if os.path.isfile(ruta):
            rutas.append(ruta)
    return rutas


def _carpeta_aportadas_de(ctx):
    return os.path.join(ctx.proyecto.raiz, "estilo", "aportadas")


def _aportadas_del_taller(ctx):
    """Las imagenes de apoyo que se subieron con la descripcion. -> [rutas]

    SE LEEN DE SU CARPETA Y NO DE `estilo.referencias`, y esa es la parte que
    importa: sin video, `referencias` acaba siendo lo que DIBUJA el paso de
    laminas (`_correr_light_referencias`), asi que guardarlas ahi hacia que al
    rehacer el estilo la guia se mirara su propia salida en vez del material que
    dio una persona. Cada cosa en su sitio.
    """
    carpeta = _carpeta_aportadas_de(ctx)
    if not os.path.isdir(carpeta):
        return []
    return [os.path.join(carpeta, n) for n in sorted(os.listdir(carpeta))
            if os.path.splitext(n)[1].lower() in EXT_APORTADAS]


def _sembrar_aportadas(ctx, encargo):
    """Mete en el taller las imagenes subidas, y vacia la carpeta de espera.

    EN EL TALLER: es lo que sobrevive al preset y lo que permite rehacer el
    estilo sin volver a pedir nada. La carpeta de espera es un buzon, no un
    almacen -- lo que se copia se borra de ahi, o se queda para siempre.
    """
    rutas = _rutas_aportadas(encargo.get("estilo_imagenes"))
    if not rutas:
        # sin nada nuevo NO se borra lo que ya hubiera: retomar un taller a
        # medias tiene que conservar el material con el que se lanzo
        return _aportadas_del_taller(ctx)
    destino = _carpeta_aportadas_de(ctx)
    shutil.rmtree(destino, ignore_errors=True)
    os.makedirs(destino, exist_ok=True)
    dentro = []
    for indice, ruta in enumerate(rutas):
        final = os.path.join(destino, f"{indice:02d}_{os.path.basename(ruta)}")
        try:
            shutil.copyfile(ruta, final)
        except OSError:
            continue
        dentro.append(final)
        try:
            os.remove(ruta)
        except OSError:
            pass            # que no se vacie el buzon no puede tumbar la tanda
    return dentro


@app.post("/api/presets-light/imagenes", status_code=201)
async def subir_imagenes_light(peticion: Request):
    """Guarda las imagenes que acompanan a una descripcion de estilo.

    Se suben ANTES de crear nada --el taller no existe hasta pulsar «Generar»--
    y por eso esperan en una carpeta aparte. Devuelve el nombre con el que se han
    guardado, que es lo que el navegador manda despues en `estilo_imagenes`.
    """
    tipo = (peticion.headers.get("content-type") or "").lower()
    if not tipo.startswith("multipart/"):
        raise ErrorApi(400, "manda las imagenes como multipart")
    try:
        formulario = await peticion.form()
    except Exception as fallo:                              # noqa: BLE001
        raise ErrorApi(400, f"multipart ilegible: {fallo}")

    carpeta = _carpeta_aportadas()
    os.makedirs(carpeta, exist_ok=True)
    guardadas, avisos = [], []
    for _clave, valor in formulario.multi_items():
        if not hasattr(valor, "read"):
            continue
        origen = os.path.basename(str(getattr(valor, "filename", "") or ""))
        extension = os.path.splitext(origen)[1].lower()
        if extension not in EXT_APORTADAS:
            avisos.append(f"«{origen or 'sin nombre'}» no es una imagen de las "
                          f"que se pueden abrir ({', '.join(EXT_APORTADAS)})")
            continue
        contenido = await valor.read()
        if len(contenido) > MAX_BYTES_APORTADA:
            avisos.append(f"«{origen}» pesa "
                          f"{len(contenido) / 1024 / 1024:.1f} MB y el tope son "
                          f"{MAX_BYTES_APORTADA // 1024 // 1024}")
            continue
        # nombre propio: dos ficheros distintos pueden llamarse igual, y el
        # segundo se llevaria al primero por delante
        sello = uuid.uuid4().hex[:12]
        nombre = f"{sello}{extension}"
        with open(os.path.join(carpeta, nombre), "wb") as fh:
            fh.write(contenido)
        guardadas.append({"nombre": nombre, "origen": origen,
                          "bytes": len(contenido)})
    if not guardadas and avisos:
        raise ErrorApi(400, "no se ha podido guardar ninguna: " + "; ".join(avisos))
    return {"imagenes": guardadas, "avisos": avisos,
            "tope": _light().max_imagenes_estilo()}


@app.get("/api/presets-light/imagenes/{nombre}")
def servir_imagen_light(nombre: str, peticion: Request):
    """La miniatura de una imagen que espera en el buzon."""
    rutas = _rutas_aportadas([nombre])
    if not rutas:
        raise ErrorApi(404, f"esa imagen no esta: {nombre}")
    return servir_fichero(peticion, rutas[0])


@app.delete("/api/presets-light/imagenes/{nombre}")
def borrar_imagen_light(nombre: str):
    """Quita una imagen de la carpeta de espera. Quitarla de la lista es esto."""
    rutas = _rutas_aportadas([nombre])
    if not rutas:
        raise ErrorApi(404, f"esa imagen ya no esta: {nombre}")
    try:
        os.remove(rutas[0])
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido borrar: {fallo}")
    return {"borrada": os.path.basename(rutas[0])}


def _talleres_sueltos():
    """Talleres sin preset: intentos que se quedaron a medias. -> [ficha]

    Un taller nace ANTES que su preset —el preset se guarda al final, con lo que
    el taller produjo—, asi que una generacion que falla deja la carpeta sin
    nadie que la borre: son cientos de megas y unos fotogramas que ya no puede
    aplicar nadie.

    En vez de barrerlos por edad —borrar solo, por reloj, lo que quiza estabas a
    punto de retomar— se ENSENAN en la galeria con sus dos salidas: retomarlo
    (que se salta lo que ya salio bien) o descartarlo. Es la misma regla que la
    papelera: nada se pierde sin que alguien lo diga.
    """
    presets = _presets()
    guardado = _preset_o_400(lambda p: p.listar())
    usados = set()
    for grupo in (list((guardado.get("presets") or {}).values())
                  + [guardado.get("papelera") or []]):
        for ficha in grupo:
            tid = ((ficha.get("datos") or {}).get("origen") or {}).get("taller")
            if tid:
                usados.add(str(tid))
    sueltos = []
    for ficha in Proyecto.listar(raiz_proyectos()):
        if not ficha.get(CONFIG_TALLER):
            continue
        if str(ficha.get("id")) in usados:
            continue
        sueltos.append({"id": ficha.get("id"),
                        "nombre": ficha.get("nombre") or ficha.get("id"),
                        "creado": ficha.get("creado", ""),
                        "actualizado": ficha.get("actualizado", "")})
    sueltos.sort(key=lambda f: str(f.get("actualizado") or ""), reverse=True)
    return sueltos


def _taller_de(ficha):
    """El taller de un preset ya guardado, o 409 si ya no esta.

    Se dice en voz alta en vez de crear uno nuevo: un taller nuevo no tiene los
    fotogramas, asi que rehacer el estilo volveria a bajar el video sin avisar y
    la correccion tardaria diez minutos en vez de dos.
    """
    tid = ((ficha.get("datos") or {}).get("origen") or {}).get("taller")
    if not tid:
        raise ErrorApi(409, "este preset no se hizo en el modo light, asi que no "
                            "tiene taller donde rehacer una parte. Editalo desde "
                            "el modo editor, o crea uno nuevo aqui")
    try:
        return contexto(tid)
    except ErrorApi:
        raise ErrorApi(409, f"el taller de este preset ({tid}) ya no esta en el "
                            f"disco: no se puede rehacer una parte sin el "
                            f"material con el que se hizo. Crea un preset nuevo")


def _sembrar_voz(ctx, cambios):
    """Los mandos de voz del estilo, tambien en su taller.

    El taller es de donde sale la ESCUCHA y de donde saldria una regeneracion,
    asi que dejarlo con la voz anterior haria que lo que oyes no sea lo que has
    elegido -- el fallo mudo de tener el mismo dato en dos sitios.
    """
    ctx.estado.actualizar_params("voz", dict(cambios))
    return cambios


def _sembrar_taller(ctx, encargo):
    """Escribe en el taller lo que se decide con un mando: el idioma y el ritmo.

    NADA DE ESTO ES LOGICA NUEVA. Son los mismos params que escribe el modo
    editor a mano —`assets.min_s/max_s/min_s_rotulos` en la tarjeta de estilo,
    `voz.hueco_minimo` en la de voz— y las mismas claves que ya guarda un preset
    de canal. El ritmo no toca el segmentador ni las cabeceras: rellena.
    """
    light = _light()
    idioma = encargo["idioma"]
    ctx.estado.actualizar_params("brief", {"idioma_salida": idioma})
    ctx.estado.actualizar_params("voz", {"idioma": idioma})
    # Y LAS LLAMADAS A LA ACCION, que tambien son un mando: se eligen al crear
    # el estilo y de aqui salen a su preset de guion (`datos_de_params`), que es
    # lo que hace que cada video nazca con ellas puestas.
    if encargo.get("cta"):
        ctx.estado.actualizar_params("guion", {"cta": encargo["cta"]})
    for paso, valores in light.params_de_ritmo(encargo.get("ritmo")).items():
        ctx.estado.actualizar_params(paso, valores)
    return idioma


# ------------------------------------------------------------ las ocho tareas

def _correr_light_guia(avisar, ctx, encargo):
    estilo = _estilo()
    peticion = (encargo.get("feedback") or {}).get("estilo") or ""
    # LAS IMAGENES SON LA FUENTE y lo escrito acompana: la guia se escribe
    # MIRANDOLAS, y las indicaciones son el «esto pero mas frio» que una imagen
    # no puede decir sola. Van aparte del feedback, que es de esta pasada y gana
    # si chocan.
    #
    # Se leen del TALLER y no del encargo: el encargo trae los nombres del buzon
    # y el buzon se vacia al copiarlas dentro.
    aportadas = _aportadas_del_taller(ctx)
    guia = estilo.generar_guia(ctx.proyecto, aportadas, avisar=avisar,
                               proyecto_id=ctx.id, peticion=peticion,
                               indicaciones=encargo.get("estilo_prompt"))
    bloque = dict((ctx.estado.params("assets") or {}).get("estilo") or {})
    bloque["guia"] = guia
    ctx.estado.actualizar_params("assets", {"estilo": bloque})
    ctx.bitacora.anotar("guia_estilo", "assets", {
        "imagenes": len(guia.get("fotogramas") or []),
        "palabras": guia.get("palabras")})
    avisar(1.0, f"guía de {guia.get('palabras')} palabras")
    return guia


def _correr_light_referencias(avisar, ctx, encargo):
    """Las laminas dibujadas, que SON las referencias del estilo.

    No son un moodboard encima de unos fotogramas: no hay fotogramas. Se dibujan
    a partir de la guia --que a su vez se escribio mirando las imagenes que
    adjuntaste-- y por eso se escriben en `referencias` y no se aprueba nada: no
    hay clave que aprobar.

    Y se dibujan en vez de usar tus imagenes tal cual a proposito: una lamina
    dibujada ya esta EN el estilo de salida, mientras que una foto de referencia
    trae su propio encuadre, su luz y su formato. Lo que cada plano copia tiene
    que parecerse al video, no a la fuente.

    LAS SEIS O UNA SOLA. `encargo["laminas"]` es {eje: "que cambiarle}, lo pone
    el reparto de la correccion (`enrutar_estilo.laminas_de`) y va por
    INVOCACION: describe lo que se corrige hoy, no lo que el estilo es. Vacio
    --que es el caso normal, y el unico que existia-- son las seis.

    El motor ya sabia hacer esto por los dos caminos (`ejes=`, `peticiones=`):
    se escribio para cuando derivan unos ejes y otros salen clavados. Lo que
    faltaba era que alguien se lo pidiera.
    """
    mod = _moodboard()
    calidad = str((ctx.estado.params("assets") or {}).get("calidad") or "medium")
    bloque = dict((ctx.estado.params("assets") or {}).get("estilo") or {})
    # Se filtra contra los ejes que existen de verdad: una peticion escrita para
    # un eje inventado no daria error, dibujaria las seis sin decirlo.
    peticiones = {eje: " ".join(str(texto).split())
                  for eje, texto in (encargo.get("laminas") or {}).items()
                  if eje in mod.EJES and str(texto or "").strip()}
    pedidos = sorted(peticiones) or None
    # EL IDIOMA DEL CANAL, hasta la lamina. Sin esto, un canal en espanol saca
    # el eje «diagrama» rotulado en ingles --paso: «PLAN / DO / REVIEW»-- porque
    # el encargo entero va en ingles y el generador rotula en el idioma en que
    # se le habla. Y esa lamina no se queda en la ficha del preset: viaja como
    # imagen de referencia dentro de cada plano que lleve un componente, o sea
    # que ensena a rotular mal con un ejemplo dibujado.
    idioma = str(encargo.get("idioma") or "").strip().lower()
    destino = os.path.join(ctx.proyecto.raiz, "estilo", "dibujadas")
    hecho = mod.dibujar_desde_guia({"guia": bloque.get("guia")}, destino,
                                   ejes=pedidos, peticiones=peticiones,
                                   calidad=calidad, avisar=avisar,
                                   idioma=idioma)
    # LA LISTA NO SE PISA CUANDO SOLO SE HA REDIBUJADO UNA. Cada lamina se
    # escribe en `<eje>.png`, o sea encima de la que habia, asi que las otras
    # cinco siguen en su sitio y en la lista. Escribir aqui `hecho["rutas"]` a
    # secas dejaria un estilo con UNA referencia: sin error, sin aviso, y con el
    # video montado despues sobre una sola lamina de apoyo.
    previas = [r for r in (bloque.get("referencias") or []) if r]
    if not pedidos or not previas:
        bloque["referencias"] = hecho["rutas"]
    else:
        bloque["referencias"] = previas + [r for r in hecho["rutas"]
                                           if r not in previas]
    ctx.estado.actualizar_params("assets", {"estilo": bloque})
    ctx.bitacora.anotar("estilo_dibujado", "assets", {
        "ejes": hecho["ejes"], "coste_usd": hecho["coste_usd"],
        "pedidos": pedidos or "todos"})
    return hecho


def _enrutar_estilo():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.enrutar_estilo


def _frase_del_estilo(encargo, antes, peticion):
    """Qué ha escrito de verdad para corregir el estilo. -> str

    Son DOS cajas y hay que mirar las dos, porque la que se usa no es la que
    parece: el bloque del estilo gráfico NO tiene caja de «qué le cambiarías»
    —se quitó a propósito— así que la corrección se escribe en «Indicaciones
    (opcional)», que viaja como `estilo_prompt` dentro de `origen`.

    Un enrutador que mirase sólo `feedback["estilo"]` no vería nunca nada: esa
    clave no la escribe nadie en la pantalla para el estilo.

    Del `estilo_prompt` sólo cuenta si CAMBIÓ: es una indicación permanente del
    preset («igual pero más frío»), no una corrección de esta pasada, y
    enrutarla otra vez en cada regeneración repetiría un cambio que ya está
    puesto.
    """
    if peticion:
        return peticion
    ahora = " ".join(str(encargo.get("estilo_prompt") or "").split())
    antes_prompt = " ".join(str((antes or {}).get("estilo_prompt") or "").split())
    return ahora if ahora and ahora != antes_prompt else ""


def _estado_del_estilo(ctx):
    """Cómo está el canal ahora, para que el reparto no decida a ciegas.

    Y desde que se puede corregir UNA de las seis referencias sin tocar las
    otras cinco, esto es además lo único que dice CUÁL es cuál. El vocabulario
    del reparto describe qué se le pidió a cada eje —tres personas de pie, una
    calle, un objeto— y con eso basta para «la de los tres cuerpos»; lo que el
    vocabulario no puede saber es en qué ORDEN se ven en este estilo, que es lo
    que hace falta para «la segunda». Ese orden no es el mismo con vídeo que sin
    él, así que se lee del propio estilo (`_laminas_por_eje`) en vez de
    escribirse a mano.

    Van también las correcciones que ya lleva encima cada lámina: son de las
    pasadas anteriores, y sin ellas «vuelve a dejarla como estaba» o «esa misma
    pero con menos gente» se leen a ciegas.
    """
    p7 = _p7()
    mod = _moodboard()
    callouts = ctx.estado.params("callouts") or {}
    estilo = (ctx.estado.params("assets") or {}).get("estilo") or {}
    guia = estilo.get("guia") or {}
    nombre, _ficha = p7.diseno_de(callouts, guia)
    trozos = [
        f"grafismo: {nombre}",
        f"subtítulo: tamaño {callouts.get('subtitulo_tam') or 'normal'}, "
        f"caja al {p7.opacidad_de_caja(callouts):g}",
    ]
    if guia.get("trazo"):
        trozos.append(f"trazo: {str(guia['trazo'])[:160]}")
    linea = " · ".join(trozos)

    laminas = _laminas_por_eje(ctx)
    if not laminas:
        return linea                    # todavía no hay nada dibujado
    rutas, _e = _referencias_de_estilo(ctx)
    peticiones = (mod.ficha_de(rutas) or {}).get("peticiones") or {}
    filas = []
    for orden, (eje, _ruta) in enumerate(laminas, start=1):
        if not eje:
            continue                    # sin eje no se puede señalar
        titulo = (mod.EJES.get(eje) or {}).get("titulo") or eje
        pedido = " ".join(str(peticiones.get(eje) or "").split())
        filas.append(f"  {orden}. {eje} — {titulo}"
                     + (f"  [ya se le pidió: «{pedido[:140]}»]" if pedido else ""))
    if not filas:
        return linea
    return (linea + "\n\nlas referencias dibujadas, numeradas en el "
            "orden en que se ven en pantalla:\n" + "\n".join(filas))


def _correr_light_grafismo(avisar, ctx, encargo):
    """El grafismo sale de la guia y no cuesta nada: es una cuenta.

    Lo que decide `p7.diseno_sugerido` y `p7.paleta_de_guia` es lo mismo que
    ensena el desplegable del modo editor con su «lo que sugiere la guia». Aqui
    se ESCRIBE en vez de sugerirse, que es toda la diferencia entre los dos
    modos.
    """
    p7 = _p7()
    guia = ((ctx.estado.params("assets") or {}).get("estilo") or {}).get("guia")
    avisar(0.3, "leyendo la guía para decidir el grafismo")
    puestos = ctx.estado.params("callouts") or {}
    diseno, porque = p7.diseno_sugerido(guia)
    paleta = p7.paleta_de_guia(guia, dict(p7.PARAMS_POR_DEFECTO["paleta"]))
    # LO QUE SE ELIGIO A MANO MANDA SOBRE LO DEDUCIDO. Esta tarea vuelve a
    # deducir el set de la guia cada vez que corre, asi que sin esto una
    # correccion --«los rotulos mas sobrios», que escribe `diseno`-- se
    # revertiria en silencio en la siguiente regeneracion. `p7.diseno_de` ya lo
    # dice al reves («elegir a mano gana siempre») y aqui se le hacia caso solo
    # con el tamano del subtitulo.
    elegido = str(puestos.get("diseno") or "")
    if elegido in p7.SETS_DISENO:
        diseno, porque = elegido, "elegido a mano; no se deduce de la guía"
    cambios = {"diseno": diseno, "paleta": paleta,
               "subtitulo_tam": puestos.get("subtitulo_tam") or "normal",
               "subtitulo_caja": puestos.get("subtitulo_caja", "auto")}
    ctx.estado.actualizar_params("callouts", cambios)
    ctx.bitacora.anotar("grafismo_deducido", "callouts",
                        {"diseno": diseno, "por_que": porque})
    avisar(1.0, f"grafismo «{diseno}»")
    return {"diseno": diseno, "por_que": porque, "paleta": paleta}


def _correr_light_tono(avisar, ctx, encargo):
    tono = _tono()
    peticion = (encargo.get("feedback") or {}).get("tono") or ""
    idioma = encargo.get("idioma") or "es"
    ficha = tono.desde_descripcion(ctx.proyecto, encargo["tono_prompt"],
                                   avisar=avisar, proyecto_id=ctx.id,
                                   peticion=peticion, idioma=idioma)
    # Al BRIEF, que es donde viven las instrucciones del guion. Lo que se pega es
    # el texto COMPLETO (el parrafo mas los cinco rasgos): el nivel tecnico y el
    # publico son justo lo que hay que decirle al redactor.
    ctx.estado.actualizar_params("brief",
                                 {"instrucciones": ficha["texto_completo"]})
    # UN RESUMEN PARA LA TARJETA. Lo que se guarda en el preset son las
    # instrucciones enteras --400-700 palabras, que es lo que lee el redactor--
    # y eso no se puede enseñar en una ficha. El resumen sale de los rasgos que
    # el propio modelo ha escrito, no de recortar el parrafo por la mitad.
    encargo["tono_resumen"] = _resumen_de_tono(ficha)
    ctx.bitacora.anotar("tono_escrito", "brief",
                        {"palabras": ficha.get("palabras")})
    return ficha


def _resumen_de_tono(ficha):
    """Tres o cuatro lineas cortas de lo que ha salido. -> str

    Se queda con los rasgos que de verdad distinguen un canal de otro cuando se
    miran dos fichas seguidas: como suena, a quien le habla, como ordena y que
    hace con las fuentes. Lo demas esta dentro y se lee en el modo editor.
    """
    trozos = []
    for clave in ("resumen", "registro", "publico", "estructura", "fuentes"):
        texto = " ".join(str(ficha.get(clave) or "").split())
        if not texto:
            continue
        if len(texto) > 150:
            texto = texto[:149].rsplit(" ", 1)[0] + "…"
        trozos.append(texto)
    return "\n".join(trozos[:4])


def _correr_light_voz(avisar, ctx, encargo):
    """La voz, con el ritmo del montaje delante.

    DOS EJES, NO UNO. La velocidad de la voz y la duracion de un plano no son la
    misma decision: un montaje rapido con voz normal funciona, y la voz al tope
    sobre planos de dos segundos es un anuncio de teletienda. Asi que el ritmo
    entra como DATO en el prompt —cambia que voz encaja, no solo cuanto corre— y
    solo RELLENA la velocidad cuando el encargo no ha dicho nada de ella. Quien
    dice si el encargo hablaba de velocidad es el propio modelo que lo ha leido
    (`velocidad_pedida`), porque buscar «rapida» en el texto fallaria con «sin
    prisa».

    El AIRE entre bloques si lo pone el ritmo siempre: no es caracter de la voz,
    es tiempo muerto de montaje.
    """
    light = _light()
    ficha_ritmo = light.ritmo_de(encargo.get("ritmo"))
    peticion = (encargo.get("feedback") or {}).get("voz") or ""
    elegido = PASOS_MODULOS.voz_descrita.proponer(
        encargo["voz_prompt"], idioma=encargo["idioma"], avisar=avisar,
        proyecto_id=ctx.id, cwd=ctx.proyecto.raiz, peticion=peticion,
        ritmo=light.contexto_de_ritmo(encargo.get("ritmo")),
        # la voz elegida a mano (la clonada del canal): el agente solo pone
        # los mandos
        voz_fija=encargo.get("voz_id") or "")
    cambios = {c: elegido[c] for c in ("modelo", "voz_id", "voz_nombre",
                                       "velocidad", "emociones", "hueco_minimo")
               if elegido.get(c) is not None}
    cambios["idioma"] = encargo["idioma"]
    rellenada = not elegido.get("velocidad_pedida")
    if rellenada:
        cambios["velocidad"] = ficha_ritmo["velocidad"]
    cambios["hueco_minimo"] = ficha_ritmo["hueco_minimo"]
    ctx.estado.actualizar_params("voz", cambios)
    ctx.bitacora.anotar("voz_descrita", "voz", {
        "encargo": encargo["voz_prompt"][:200],
        "voz": elegido.get("voz_nombre"), "velocidad": cambios["velocidad"],
        "velocidad_del_ritmo": rellenada, "ritmo": ficha_ritmo["id"]})
    return dict(elegido, velocidad=cambios["velocidad"],
                hueco_minimo=cambios["hueco_minimo"])


def _laminas_por_eje(ctx):
    """Las referencias dibujadas, CON SU EJE y en el orden en que se ven.

    Son las MISMAS que copia cada plano del video, y por eso son las que se
    ensenan: cualquier otra cosa seria una promesa que el render no tiene por que
    cumplir. Dos caminos, los mismos dos que las dibujan
    (`_correr_light_referencias`):

        con video    el moodboard, guardado en el banco global bajo la huella de
                     los fotogramas elegidos. Seis laminas, una por eje, por
                     orden alfabetico de eje.
        sin video    las laminas dibujadas a partir de la guia SON las
                     referencias del estilo, asi que estan en `referencias`, en
                     el orden en que se dibujaron, y el eje es el nombre de su
                     fichero.

    EL EJE VA CON LA RUTA porque es lo que permite corregir UNA («la de los tres
    cuerpos») en vez de las seis, y EL ORDEN ES EL QUE SE VE porque es lo que
    permite corregir «la segunda». Los dos caminos no lo tienen igual, y eso es
    exactamente por lo que se calcula aqui en vez de escribirse a mano en el
    prompt del reparto: un numero fijo acertaria en la mitad de los estilos.

    Una ruta cuyo fichero no se llame como un eje conocido sale con el eje en
    blanco. No se le adivina uno: mandar ahi una correccion la aplicaria a la
    lamina de al lado.
    """
    mod = _moodboard()
    rutas, _estilo = _referencias_de_estilo(ctx)
    if not rutas:
        return []
    ejes = (mod.ficha_de(rutas) or {}).get("ejes") or {}
    laminas = [(eje, ejes[eje]) for eje in sorted(ejes)
               if ejes.get(eje) and os.path.exists(ejes[eje])]
    if laminas:
        return laminas
    # SIN TOCAR EL ORDEN GUARDADO. Reordenarlo aqui no daria un error, daria
    # otras muestras: `presets_light._escena_muestra` decide POR INDICE cual de
    # las seis lleva cartela.
    return [(os.path.splitext(os.path.basename(r))[0]
             if os.path.splitext(os.path.basename(r))[0] in mod.EJES else "", r)
            for r in rutas]


def _laminas_del_estilo(ctx):
    """Las referencias dibujadas del estilo, en orden. -> [rutas]"""
    return [ruta for _eje, ruta in _laminas_por_eje(ctx)]


def _correr_light_muestra(avisar, ctx, encargo):
    """Las referencias del estilo con su cartela y su subtitulo, y la 2x2.

    NO SE DIBUJA NADA: las laminas ya estan --son las que copia cada plano-- y lo
    unico que se hace aqui es ponerles encima el texto con el mismo codigo que el
    repaso del montaje. Antes esto generaba cuatro planos de ejemplo a proposito,
    cuatro imagenes pagadas por estilo, para ensenar lo mismo. Ver la cabecera de
    `presets_light`.

    Como no cuesta nada y la lamina limpia esta siempre, recomponer en otro
    idioma es gratis por construccion: no hay ningun caso en el que haya que
    volver a pagar por cambiar el texto de encima.
    """
    light = _light()
    assets = ctx.estado.params("assets") or {}
    estilo = dict(assets.get("estilo") or {})
    carpeta = os.path.join(ctx.proyecto.raiz, "muestras")
    shutil.rmtree(carpeta, ignore_errors=True)
    os.makedirs(carpeta, exist_ok=True)

    avisar(0.1, "buscando las referencias del estilo")
    laminas = _laminas_del_estilo(ctx)
    if not laminas:
        raise RuntimeError("este estilo no tiene ninguna referencia dibujada "
                           "con la que hacer las muestras")

    avisar(0.3, f"montando {len(laminas)} muestras con su cartela y su subtítulo")
    params = dict(ctx.estado.params("callouts") or {})
    params.setdefault("estilo", estilo)
    # EL IDIOMA DEL ESTILO, que es el de sus muestras: un subtitulo de ejemplo
    # en otro idioma no ensena ni la longitud de linea ni donde parte.
    params["idioma"] = encargo["idioma"]
    hecho = light.componer(laminas, os.path.join(carpeta, "miniatura.png"),
                           params, semilla=ctx.id)
    ctx.bitacora.anotar("muestras_preset", "callouts",
                        {"laminas": len(laminas), "idioma": encargo["idioma"]})
    avisar(1.0, "muestras listas")
    return {"miniatura": hecho["miniatura"], "celdas": hecho["celdas"],
            "laminas": laminas}


def _light_hecha(ctx, tarea_id, encargo):
    """Si esta tarea ya esta hecha EN ESTE TALLER. Solo la mira `retomar`.

    Existe por un caso real: YouTube devolvio un 403 —de los que se reintentan
    solos y a veces fallan los cinco— cuando el tono y la voz ya estaban
    escritos, y la tanda entera se fue con el. Volver a pulsar rehacia dos
    llamadas al CLI que ya habian salido bien.

    Se mira EL RESULTADO en el disco y en los params, no una bandera aparte: es
    la misma regla que `_esta_al_dia` de las recetas, y la unica que no puede
    mentir despues de un corte a medias.
    """
    assets = ctx.estado.params("assets") or {}
    estilo = assets.get("estilo") or {}
    if tarea_id == "frames":
        return bool((_estilo().ficha(ctx.proyecto) or {}).get("candidatos"))
    if tarea_id == "guia":
        guia = estilo.get("guia")
        return bool((guia or {}).get("guia") if isinstance(guia, dict) else guia)
    if tarea_id == "referencias":
        # las laminas dibujadas SON las referencias del estilo
        return any("dibujadas" in str(r) for r in (estilo.get("referencias") or []))
    if tarea_id == "grafismo":
        return bool((ctx.estado.params("callouts") or {}).get("diseno"))
    if tarea_id == "tono":
        return bool((ctx.estado.params("brief") or {}).get("instrucciones"))
    if tarea_id == "voz":
        return bool((ctx.estado.params("voz") or {}).get("voz_id"))
    if tarea_id == "muestra":
        return os.path.isfile(os.path.join(ctx.proyecto.raiz, "muestras",
                                           "miniatura.png"))
    return False


_LIGHT_QUE_HACE = {
    "guia": _correr_light_guia,
    "referencias": _correr_light_referencias,
    "grafismo": _correr_light_grafismo,
    "tono": _correr_light_tono,
    "voz": _correr_light_voz,
    "muestra": _correr_light_muestra,
}


def _correr_preset_light(avisar, ctx, encargo, solo, preset_id, retomar=False):
    """Recorre el plan tanda a tanda y congela el resultado en el preset.

    LA BARRA VA POR TIEMPO, no por numero de tareas. Cada tanda ocupa en la barra
    lo que se espera que tarde (`presets_light.plan_de`, que mira el historial
    medido), y dentro de una tanda manda la mas lenta: es lo unico que hace que
    «bajando el vídeo» no sea el 12 % de la barra durante tres minutos y despues
    seis tareas cortas se coman el resto de golpe.
    """
    light = _light()
    presets = _presets()
    plan = light.plan_de(encargo, solo)
    total = max(1.0, float(plan["segundos"]))
    salida = {"tareas": [], "preset": preset_id, "coste_usd": 0.0}
    cerrojo = threading.Lock()

    for tanda in plan["tandas"]:
        # RETOMAR se salta lo que ya salio bien en este taller. Nunca se salta
        # nada en una pasada normal ni al rehacer una parte: ahi el encargo es
        # justamente volver a hacerlo.
        if retomar:
            tanda = [f for f in tanda if not _light_hecha(ctx, f["id"], encargo)]
            if not tanda:
                continue

        def correr(ficha):
            desde = float(ficha["desde"]) / total
            trozo = float(ficha["tanda_segundos"]) / total

            ultimo = {"frase": light.publico_de(ficha["id"], 0.0)}

            def avisar_tarea(valor, mensaje=""):
                if valor is not None:
                    ultimo["frase"] = light.publico_de(ficha["id"], valor)
                avisar(desde + trozo * min(1.0, max(0.0, float(valor or 0))),
                       ficha["nombre"] + (f" — {mensaje}" if mensaje else ""),
                       ultimo["frase"])

            avisar_tarea(0.0, "")
            arranque = time.time()
            resultado = _LIGHT_QUE_HACE[ficha["id"]](avisar_tarea, ctx, encargo)
            with cerrojo:
                salida["tareas"].append({"tarea": ficha["id"],
                                         "segundos": round(time.time() - arranque, 1)})
                if isinstance(resultado, dict):
                    salida["coste_usd"] += float(resultado.get("coste_usd") or 0.0)
            return resultado

        if len(tanda) == 1:
            correr(tanda[0])
            continue
        with ThreadPoolExecutor(max_workers=len(tanda)) as pool:
            for futuro in [pool.submit(correr, f) for f in tanda]:
                futuro.result()          # una excepcion sube y corta la tanda

    avisar(0.99, "guardando el preset", "Guardando tu estilo")
    ficha = _congelar_preset(ctx, encargo, preset_id)
    salida["preset"] = ficha["id"]
    salida["resumen"] = ficha.get("resumen") or ""
    salida["coste_usd"] = round(salida["coste_usd"], 4)
    avisar(1.0, f"preset «{ficha['nombre']}» listo", PUBLICO_LISTO)
    return salida


def _congelar_preset(ctx, encargo, preset_id=None):
    """Guarda lo que ha producido el taller como preset de canal. -> ficha."""
    presets = _presets()
    params = {paso: (ctx.estado.params(paso) or {})
              for paso in ("brief", "guion", "assets", "voz", "callouts")}
    datos = presets.datos_de_params(params)
    datos["origen"] = {c: encargo[c] for c in presets.CLAVES_ORIGEN
                       if encargo.get(c)}
    datos["origen"]["taller"] = ctx.id
    taller_muestras = os.path.join(ctx.proyecto.raiz, "muestras")
    miniatura = os.path.join(taller_muestras, "miniatura.png")
    if not os.path.exists(miniatura):
        miniatura = ""
    sueltas = [os.path.join(taller_muestras, n)
               for n in _light().nombres_de_muestra()]
    datos["origen"]["muestras"] = [os.path.basename(r) for r in sueltas
                                   if os.path.exists(r)]
    try:
        ficha = presets.guardar("canal", encargo["nombre"], datos,
                                miniatura=miniatura, pid=preset_id)
    except presets.ErrorPreset as fallo:
        raise RuntimeError(str(fallo))

    # LAS CUATRO SUELTAS TAMBIEN AL BANCO, y DESPUES de guardar: la siembra del
    # estilo rehace la carpeta del preset entera, asi que copiarlas antes seria
    # copiarlas para que se las lleve por delante. Fallar aqui no puede tumbar
    # un estilo que ya esta guardado: lo que se pierde es el banner, y la
    # miniatura sigue.
    destino = presets.carpeta_de(ficha["id"])
    for ruta in sueltas:
        if not os.path.exists(ruta):
            continue
        try:
            os.makedirs(destino, exist_ok=True)
            shutil.copyfile(ruta, os.path.join(destino, os.path.basename(ruta)))
        except OSError:
            pass
    return ficha


# ------------------------------------------------------------------ endpoints

def _rescatar_del_taller(ficha, carpeta):
    """Las muestras que el taller todavia tiene. -> [nombres] copiados.

    Se dibujaron ahi y ahi siguen: el taller no se borra al guardar el preset,
    que es justo lo que permite rehacer solo el tono sin volver a bajar el video.
    Asi que un preset al que le faltan sus muestras no es un preset que haya que
    regenerar; es uno al que hay que devolverselas, y eso no cuesta nada.
    """
    tid = ((ficha.get("datos") or {}).get("origen") or {}).get("taller") or ""
    if not tid:
        return []
    try:
        origen = os.path.join(contexto(tid).proyecto.raiz, "muestras")
    except ErrorApi:
        return []
    if not os.path.isdir(origen):
        return []
    salida = []
    os.makedirs(carpeta, exist_ok=True)
    # la 2x2 se rescata con ellas: es la cara de la tarjeta de la galeria y se
    # perdia en el mismo sitio y por el mismo motivo
    for nombre in ["miniatura.png"] + _light().nombres_de_muestra():
        fuente = os.path.join(origen, nombre)
        if not os.path.isfile(fuente):
            continue
        try:
            shutil.copyfile(fuente, os.path.join(carpeta, nombre))
        except OSError:
            continue
        if nombre != "miniatura.png":
            salida.append(nombre)
    return salida


def _curar_muestras(ficha):
    """Las muestras sueltas de un estilo, devueltas si le faltan.

    Se hace AQUI --al listar-- y no en una migracion aparte porque es lo unico
    que garantiza que pase: una migracion que hay que acordarse de ejecutar es
    una migracion que no se ejecuta. Es idempotente y solo toca a los que les
    falta: el segundo listado no hace nada.

    DOS CASOS, y ninguno cuesta una imagen:

        las declara y no
        estan en el disco  se las llevo por delante un guardado posterior, de
                           cuando sembrar el estilo borraba la carpeta entera
                           (`presets_canal._apartar_propios`). Se recuperan del
                           taller, que las tiene intactas.
        no las declara     un estilo anterior a que se guardaran sueltas. Su 2x2
                           se parte en cuatro ficheros, que son los mismos cuatro
                           planos ya pagados.

    Falla en silencio a proposito. Lo que se pierde si no puede recuperarlas es
    la fila de muestras, y eso no puede impedir que la galeria se lea.
    """
    datos = ficha.get("datos") or {}
    origen = datos.get("origen") or {}
    presets = _presets()
    carpeta = presets.carpeta_de(ficha["id"])
    propia = os.path.join(carpeta, "miniatura.png")
    declaradas = list(origen.get("muestras") or [])
    ya = [n for n in _light().nombres_de_muestra()
          if os.path.isfile(os.path.join(carpeta, n))]
    if not ya:
        ya = _rescatar_del_taller(ficha, carpeta)
    # LA 2x2 Y SOLO LA 2x2. Partir en cuatro `ficha['miniatura']` a secas era
    # partir un FOTOGRAMA cuando el canal venia del modo editor: cuatro
    # cuadrantes de una imagen suelta presentados como «planos de ejemplo con su
    # cartela y su subtitulo». La hoja de muestras se llama siempre igual y vive
    # siempre en el mismo sitio, asi que se pide por su nombre.
    if not ya and os.path.isfile(propia):
        try:
            ya = [os.path.basename(r) for r in
                  _light().partir_miniatura(propia, carpeta)]
        except Exception:                                   # noqa: BLE001
            ya = []
    # y la cara del preset vuelve a ser esa hoja: sin esto, el guardado que se
    # llevo las muestras dejaba la tarjeta de la galeria con un fotograma crudo
    miniatura = propia if os.path.isfile(propia) else (ficha.get("miniatura") or "")
    if ya == declaradas and miniatura == (ficha.get("miniatura") or ""):
        return
    # se anota en la ficha QUE SE PUBLICA y tambien en el almacen, para no
    # volver a mirar el disco en cada listado
    ficha.setdefault("datos", {}).setdefault("origen", {})["muestras"] = ya
    ficha["miniatura"] = miniatura
    ficha["hay_miniatura"] = bool(miniatura and os.path.exists(miniatura))
    try:
        contenido = copy.deepcopy(datos)
        contenido.setdefault("origen", {})["muestras"] = ya
        presets.guardar("canal", ficha.get("nombre") or ficha["id"], contenido,
                        nota=ficha.get("nota") or "",
                        miniatura=miniatura, pid=ficha["id"])
    except Exception:                                       # noqa: BLE001
        pass


@app.get("/api/presets-light")
def listar_presets_light():
    """Los presets de canal, con sus viñetas y su plan de generacion.

    `plan` viaja aqui y no en un endpoint aparte porque la pantalla lo necesita
    ANTES de pulsar: es lo que dice cuanto va a tardar y cuanto va a costar.
    """
    presets = _presets()
    light = _light()
    # `listar` agrupa por tipo; aqui solo interesan los de canal, que son los
    # que este modo entiende. Los de guion, estilo, voz y grafismo siguen
    # existiendo y siguen siendo del modo editor: no se ensenan ni se tocan.
    fichas = (_preset_o_400(lambda p: p.listar())["presets"] or {}).get("canal") or []
    for ficha in fichas:
        _curar_muestras(ficha)
    return {"presets": fichas,
            "idiomas": [{"valor": c, "nombre": presets.NOMBRES_IDIOMA.get(c, c)}
                        for c in light.IDIOMAS],
            "partes": {k: v["nombre"] for k, v in light.PARTES.items()},
            # lo que cuesta rehacer cada parte, para poder decirlo ANTES de
            # pulsar sin que la pantalla se invente la cifra
            "imagenes_por_parte": {k: light.imagenes_de_parte(k)
                                   for k in light.PARTES},
            # cuantas imagenes de apoyo admite una descripcion de estilo: las
            # mismas que se eligen de un video, y lo dice quien lo sabe
            "max_imagenes_estilo": light.max_imagenes_estilo(),
            # El deslizador de ritmo, con las dos unicas cifras que ensena: el
            # plano medio y lo que cuesta un minuto de video a ese ritmo.
            "ritmos": [light.ficha_de_ritmo(r["id"]) for r in light.RITMOS],
            "ritmo_por_defecto": light.RITMO_POR_DEFECTO,
            "sueltos": _talleres_sueltos(),
            "tareas": [{"id": t["id"], "nombre": t["nombre"],
                        "porque": t.get("porque", ""), "cuesta": t["cuesta"],
                        "imagenes": t.get("imagenes") or 0,
                        "solo": t.get("solo") or ""} for t in light.TAREAS]}


@app.post("/api/presets-light/plan")
def plan_preset_light(cuerpo: dict = Body(default=None)):
    """Lo que va a hacer, en orden y con sus tiempos. No lanza nada."""
    encargo = _encargo_o_400(_cuerpo(cuerpo))
    plan = _light().plan_de(encargo)
    return {"encargo": encargo, "plan": plan}


@app.post("/api/presets-light", status_code=202)
def crear_preset_light(cuerpo: dict = Body(default=None)):
    """Crea el estilo entero a partir de los cuatro campos.

    Con `taller` se RETOMA uno que se quedo a medias: se salta lo que ya salio
    bien y sigue por donde iba. Es lo que convierte un 403 de YouTube —de los
    que se reintentan solos y a veces fallan los cinco— en volver a pulsar, en
    vez de en rehacer el tono y la voz que ya estaban escritos.
    """
    datos = _cuerpo(cuerpo)
    encargo = _encargo_o_400(datos)
    pedido = str(datos.get("taller") or "").strip()
    retomar = False
    if pedido:
        try:
            ctx = contexto(pedido)
        except ErrorApi:
            raise ErrorApi(404, f"el taller {pedido} ya no esta en el disco")
        if not ctx.proyecto.config.get(CONFIG_TALLER):
            raise ErrorApi(400, f"{pedido} no es un taller de estilo")
        retomar = True
    else:
        ctx = _crear_taller(encargo)
    _sembrar_taller(ctx, encargo)
    # ANTES de lanzar: la guia es la primera tarea que las mira, y retomar un
    # taller no puede perderlas -- se vuelven a copiar y ya estaban.
    aportadas = _sembrar_aportadas(ctx, encargo)
    ctx.bitacora.anotar("preset_light_lanzado", None,
                        {"nombre": encargo["nombre"], "idioma": encargo["idioma"],
                         "ritmo": encargo.get("ritmo"), "retomado": retomar,
                         "aportadas": len(aportadas)})
    trabajo_id = ctx.gestor.lanzar("preset_light", _correr_preset_light, ctx,
                                   encargo, None, None, retomar, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "taller": ctx.id, "encargo": encargo,
            "retomado": retomar, "plan": _light().plan_de(encargo),
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/presets-light/{preset_id}/voz/previsualizar", status_code=202)
def previsualizar_voz_light(preset_id: str, cuerpo: dict = Body(default=None)):
    """Unos segundos con la voz de este estilo, para escucharla.

    Corre en el TALLER, que es un proyecto y por tanto tiene todo lo que
    `p4_voz.previsualizar` necesita. Es el mismo endpoint que el modo editor
    por dentro; lo unico que cambia es que aqui no hay que saber en que
    proyecto esta.

    CON `voz_id` SE ESCUCHA OTRA VOZ SIN ELEGIRLA. En la cuadricula de voces cada
    una lleva su propio play, y darle es AUDICIONARLA: si escuchar guardara, oir
    seis para comparar dejaria puesta la sexta. Todo lo demas --velocidad, color,
    aire-- son los mandos del estilo, que es lo que hace que la comparacion valga:
    cambia la voz y nada mas. La sintesis se cachea por firma (y la voz entra en
    ella), asi que volver a una ya escuchada no vuelve a pagar.
    """
    presets = _presets()
    datos = _cuerpo(cuerpo)
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    if ficha.get("tipo") != "canal":
        raise ErrorApi(400, "esto no es un estilo")
    ctx = _taller_de(ficha)
    params = dict((ficha.get("datos") or {}).get("voz") or {})
    suelta = str(datos.get("voz_id") or "").strip()
    if suelta:
        params["voz_id"] = suelta
    if not params.get("voz_id"):
        raise ErrorApi(409, "este estilo todavia no tiene voz elegida")
    # EL TEXTO QUE SE LEE. En un video sale del paso 3; en un taller no hay
    # guion --no es un video, es donde se monta un estilo-- y sin esto la
    # escucha moria con «no encuentro el guion». Se le pasa por params, que es
    # el primer sitio donde `p4_voz.cargar_guion` mira desde siempre: ninguna
    # logica nueva, solo darle el texto.
    params["bloques"] = _light().bloques_de_escucha(
        params.get("idioma") or presets.idioma_de(ficha) or "es")
    try:
        segundos = float(datos.get("segundos") or 12)
    except (TypeError, ValueError):
        raise ErrorApi(400, "'segundos' debe ser un numero")
    if not 1 <= segundos <= 60:
        raise ErrorApi(400, "'segundos' debe estar entre 1 y 60")
    trabajo_id = ctx.gestor.lanzar("voz:previsualizar", _previsualizar_voz,
                                   ctx, params, segundos, paso=None)
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "segundos": segundos,
            "voz_id": params["voz_id"],
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/presets-light/{preset_id}/duplicar", status_code=201)
def duplicar_preset_light(preset_id: str, cuerpo: dict = Body(default=None)):
    """Una copia del estilo, con su taller.

    CON SU TALLER, y eso es lo que cuesta: sin el, la copia no puede rehacer ni
    el estilo grafico ni el tono ni la voz --no tiene el material con el que se
    hizo-- y seria un estilo de segunda que solo sirve para mirar. `duplicar`
    copia la version ACTIVA de cada paso, no el historial, asi que un taller son
    decenas de megas y no cientos.

    Para que sirve: el mismo dibujo en otro idioma, o con otro ritmo, sin volver
    a bajar el video ni a pagar las referencias.
    """
    presets = _presets()
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    if ficha.get("tipo") != "canal":
        raise ErrorApi(400, "esto no es un estilo")
    datos = _cuerpo(cuerpo)
    nombre = " ".join(str(datos.get("nombre") or "").split()) \
        or f"{ficha.get('nombre') or 'Estilo'} (copia)"

    contenido = copy.deepcopy(ficha.get("datos") or {})
    origen = dict(contenido.get("origen") or {})
    # el taller se copia; si no lo hay, la copia se queda sin el y lo dice al
    # intentar rehacer una parte
    tid = origen.get("taller")
    if tid:
        try:
            viejo = contexto(tid)
            nuevo = viejo.proyecto.duplicar(raiz_proyectos(),
                                            f"taller {nombre}"[:60])
            copia = contexto(nuevo.id)
            copia.proyecto.config[CONFIG_TALLER] = True
            copia.proyecto.guardar_config()
            origen["taller"] = copia.id
        except Exception as fallo:                          # noqa: BLE001
            raise ErrorApi(500, f"no se ha podido copiar el taller: {fallo}")
    contenido["origen"] = origen

    try:
        nueva = presets.guardar("canal", nombre, contenido,
                                nota=ficha.get("nota") or "",
                                miniatura=ficha.get("miniatura") or "")
    except presets.ErrorPreset as fallo:
        raise ErrorApi(400, str(fallo))

    # las muestras sueltas, que no son params y por tanto no viajan en `datos`
    viejas = presets.carpeta_de(preset_id)
    destino = presets.carpeta_de(nueva["id"])
    for nombre_fichero in (origen.get("muestras") or []):
        una = os.path.join(viejas, os.path.basename(str(nombre_fichero)))
        if os.path.exists(una):
            try:
                os.makedirs(destino, exist_ok=True)
                shutil.copyfile(una, os.path.join(destino,
                                                  os.path.basename(una)))
            except OSError:
                pass
    return {"preset": nueva, "de": preset_id}


@app.delete("/api/presets-light/talleres/{taller_id}")
def descartar_taller_light(taller_id: str):
    """Tira un intento a medias. A la papelera de proyectos, no al vacio."""
    try:
        ctx = contexto(taller_id)
    except ErrorApi:
        raise ErrorApi(404, f"el taller {taller_id} ya no esta")
    if not ctx.proyecto.config.get(CONFIG_TALLER):
        raise ErrorApi(400, f"{taller_id} no es un taller de estilo")
    if taller_id in {f["id"] for f in _talleres_sueltos()}:
        apartar_proyecto(taller_id)
        return {"descartado": taller_id}
    raise ErrorApi(409, f"el taller {taller_id} es de un estilo guardado: "
                        f"borra el estilo y se va con el")


@app.post("/api/presets-light/{preset_id}/regenerar", status_code=202)
def regenerar_preset_light(preset_id: str, cuerpo: dict = Body(default=None)):
    """Rehace UNA de las tres partes con una frase de feedback.

    Tres y no ocho: el canal ve tres cosas --el estilo grafico, el tono y la
    voz-- asi que corrige tres cosas. El idioma no esta aqui porque se cambia a
    mano y no hay nada que rehacer (PUT).

    CON `origen` SE CAMBIA LA FUENTE, no solo se corrige, y la tienen DOS de las
    tres partes:

      estilo   «los mismos videos pero en fotografico»: otro video, u otra
               descripcion con otras imagenes, y se rehace el estilo entero
               CONSERVANDO el tono, la voz, el ritmo y el idioma. Con un video
               nuevo hay que bajarlo y volver a elegir fotogramas, asi que la
               lista de tareas sale del encargo nuevo (`light.tareas_de_estilo`).
      tono     otros videos de referencia (hasta `light.MAX_VIDEOS_TONO`), o
               una descripcion en su lugar. Rehace solo las instrucciones del
               guion; no cuesta ninguna imagen.

    La voz no: se corrige con una frase, que ya es su fuente entera.
    """
    light = _light()
    datos = _cuerpo(cuerpo)
    parte = str(datos.get("parte") or "").strip().lower()
    if parte not in light.PARTES:
        raise ErrorApi(400, f"parte desconocida: {parte!r}. Son "
                            + ", ".join(light.PARTES))
    peticion = " ".join(str(datos.get("peticion") or "").split())
    fuente = datos.get("origen") if isinstance(datos.get("origen"), dict) else None
    if fuente and parte not in ("estilo", "tono", "personajes"):
        raise ErrorApi(400, "la voz no tiene fuente que cambiar: se corrige "
                            "con una frase, que ya es su descripcion entera")
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    if ficha.get("tipo") != "canal":
        raise ErrorApi(400, "esto no es un preset de canal")
    ctx = _taller_de(ficha)

    origen = dict((ficha.get("datos") or {}).get("origen") or {})
    antes = dict(origen)
    origen["nombre"] = ficha.get("nombre") or "canal"
    origen.setdefault("idioma", _presets().idioma_de(ficha) or "es")
    if fuente and parte == "estilo":
        # las DOS a la vez y siempre: dejar la vieja puesta es como se acaba con
        # unas indicaciones que describen unas imagenes que ya no estan
        origen["estilo_prompt"] = fuente.get("estilo_prompt") or ""
        origen["estilo_imagenes"] = fuente.get("estilo_imagenes") or []
    if fuente and parte == "tono":
        origen["tono_prompt"] = fuente.get("tono_prompt") or ""
    encargo = _encargo_o_400(origen)

    # ¿HAN CAMBIADO LAS IMAGENES, O SOLO LAS INDICACIONES? Cambiar «igual pero
    # mas frio» con las MISMAS imagenes detras solo obliga a reescribir la guia y
    # lo que cuelga de ella, que es justo lo que rehace la parte «estilo» de
    # siempre. Se compara con lo que habia, no con si vino `origen`: la pantalla
    # manda las dos claves juntas y una de ellas puede no haberse tocado.
    material = bool(fuente) and parte == "estilo" and bool(
        encargo.get("estilo_imagenes"))
    # El feedback viaja por INVOCACION y no se guarda en el encargo: describe
    # esta pasada, no lo que el preset es. Guardarlo lo aplicaria otra vez la
    # proxima, y dos correcciones seguidas se sumarian sin que nadie lo pida.
    encargo["feedback"] = {parte: peticion}

    # EL REPARTO: leer la frase ANTES de correr nada y quedarse con lo que hace
    # falta. Corregir el estilo grafico corria siempre las cuatro tareas --24
    # fotogramas mirados otra vez, la guia reescrita y SEIS imagenes nuevas--
    # aunque lo que se pidiera fuera bajarle la opacidad a la caja del
    # subtitulo, que son dos numeros en un fichero de params.
    #
    # NO toca el camino de la fuente nueva: si de verdad hay otro video o otras
    # imagenes, hay que rehacerlo todo y no hay nada que repartir.
    reparto = None
    if parte == "estilo" and not material:
        frase = _frase_del_estilo(encargo, antes, peticion)
        if frase:
            reparto = _enrutar_estilo().repartir(
                frase, estado=_estado_del_estilo(ctx), cwd=ctx.proyecto.raiz,
                proyecto_id=ctx.id)
            # LOS PARAMS SE ESCRIBEN AQUI Y NO DENTRO DEL TRABAJO: asi el
            # grafismo que corre despues ya los encuentra puestos, y si el
            # trabajo se cancela lo elegido se queda.
            for paso_destino, valores in (reparto.get("params") or {}).items():
                ctx.estado.actualizar_params(paso_destino, valores)
            # QUE REFERENCIA REDIBUJAR Y QUE CAMBIARLE. Va en el encargo y NO
            # en los params, por lo mismo que el feedback: describe esta pasada
            # y no lo que el estilo es. Guardado, la siguiente regeneracion
            # volveria a corregir una lamina que ya esta corregida.
            #
            # Vacio son las seis, que es lo de siempre. Lo llena solo
            # `una_referencia`, y `laminas_de` ya se encarga de devolver vacio
            # si algo del reparto pide las seis: media correccion aplicada
            # dejaria cinco laminas con un estilo y una con otro.
            encargo["laminas"] = dict(reparto.get("laminas") or {})
    if material:
        tareas = light.tareas_de_estilo(encargo)
    elif reparto is not None:
        # LA TUPLA VACIA ES UNA RESPUESTA, no la ausencia de una. Es lo que
        # devuelve el reparto cuando dice «esto no tiene mando», y escrito con
        # un `or` se caia al respaldo: se lanzaban las cuatro tareas y las seis
        # imagenes para una frase que el motor acababa de decir que no sabia
        # aplicar -- o sea justo lo contrario de lo que este reparto existe para
        # hacer. Pasó al probarlo con «pon el subtítulo arriba del todo».
        tareas = tuple(reparto.get("tareas") or ())
    else:
        tareas = light.PARTES[parte]["tareas"]
    # UN CAJON ES UNA PROMESA: una tarea que no existe se filtra en silencio mas
    # abajo y deja un plan VACIO -- el trabajo termina «listo» sin haber hecho
    # nada y la pantalla vuelve como si el cambio estuviera aplicado.
    tareas = tuple(t for t in tareas if t in light.TAREAS_POR_ID)
    aportadas = _sembrar_aportadas(ctx, encargo) if material else []
    ctx.bitacora.anotar("preset_light_regenerar", None,
                        {"preset": preset_id, "parte": parte,
                         "peticion": peticion[:200],
                         "fuente_nueva": bool(fuente),
                         "material_nuevo": material,
                         "aportadas": len(aportadas),
                         "reparto": (reparto or {}).get("resumen") or "",
                         "laminas": sorted(encargo.get("laminas") or {})})

    # NADA QUE CORRER. Pasa cuando el reparto dice «esto no tiene mando»: es una
    # respuesta, no un fallo, y lo que hay que hacer con ella es DECIRLA. Lanzar
    # un trabajo vacio la enseñaria como un cambio aplicado.
    if not tareas:
        return {"trabajo_id": "", "taller": ctx.id, "parte": parte,
                "fuente_nueva": False, "material_nuevo": False,
                "reparto": reparto, "sin_cambios": True,
                "aviso": (reparto or {}).get("resumen")
                         or "no hay nada que rehacer con eso"}

    trabajo_id = ctx.gestor.lanzar(
        "preset_light", _correr_preset_light, ctx, encargo,
        list(tareas), preset_id, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    return {"trabajo_id": trabajo_id, "taller": ctx.id, "parte": parte,
            "fuente_nueva": bool(fuente), "material_nuevo": material,
            "reparto": reparto,
            "plan": light.plan_de(encargo, tareas),
            "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.put("/api/presets-light/{preset_id}")
def editar_preset_light(preset_id: str, cuerpo: dict = Body(default=None)):
    """El nombre, el idioma y la guia de tono: lo que se cambia a mano.

    NINGUNO DE LOS DOS CUESTA UNA IMAGEN. El nombre es una cadena. El idioma
    cambia los params --y con ellos lo que se aplica a un video-- y ademas
    ADAPTA lo que lleva lengua dentro: reescribe las instrucciones del guion (una
    llamada al CLI, por suscripcion) y vuelve a componer el texto de las muestras
    sobre los planos limpios, que siguen ahi sin tocar. Cero imagenes, unos
    cuarenta segundos, y por eso duplicar un estilo y cambiarle el idioma es una
    operacion normal y no una regeneracion.
    """
    presets = _presets()
    light = _light()
    datos = _cuerpo(cuerpo)
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    if ficha.get("tipo") != "canal":
        raise ErrorApi(400, "esto no es un preset de canal")

    nombre = " ".join(str(datos.get("nombre") or "").split()) or ficha["nombre"]
    idioma = str(datos.get("idioma") or "").strip().lower()
    # LA GUIA DE TONO SE EDITA A MANO, y por eso entra por el mismo PUT que el
    # nombre: no cuesta nada, es un texto. Se manda entera --el parrafo mas los
    # rasgos, que es lo que se pega en el brief-- y se guarda tal cual, sin
    # limpiar los saltos de linea: es un texto de mil palabras con su forma.
    #
    # `None` es «no me han mandado nada» y la cadena vacia es «borrala»: con un
    # `or` serian lo mismo y guardar el nombre desde otro sitio se llevaria por
    # delante una guia de mil palabras sin decir nada.
    instrucciones = datos.get("instrucciones")
    instrucciones = None if instrucciones is None else str(instrucciones).strip()
    if idioma and idioma not in light.IDIOMAS:
        raise ErrorApi(400, f"idioma desconocido: {idioma!r}. Los que hay son: "
                            + ", ".join(light.IDIOMAS))

    contenido = copy.deepcopy(ficha.get("datos") or {})

    # EL RITMO TAMPOCO REGENERA NADA: escribe los mismos tres campos de duracion
    # que el modo editor tiene en su tarjeta de estilo, mas el aire entre
    # bloques. Lo que NO toca es la velocidad de la voz: esa se decidio una vez
    # leyendo lo que pediste, y cambiarla por mover un deslizador seria pisar
    # una decision tuya sin decirlo. Si la quieres mas rapida, se pide en su caja.
    # LOS MANDOS DE LA VOZ, uno a uno. Se eligieron describiendo como querias
    # que sonara, y esto es la vuelta de tuerca fina: cambiar la voz concreta,
    # la velocidad, las emociones o el aire sin volver a describir nada. No
    # cuesta nada --son params-- y por eso viven en el mismo PUT que el nombre.
    voz_pedida = datos.get("voz") if isinstance(datos.get("voz"), dict) else None

    adaptar = bool(idioma and idioma != presets.idioma_de(ficha))
    ritmo = str(datos.get("ritmo") or "").strip().lower()
    if ritmo:
        if ritmo not in light.RITMOS_POR_ID:
            raise ErrorApi(400, f"ritmo desconocido: {ritmo!r}. Los que hay son: "
                                + ", ".join(light.RITMOS_POR_ID))
        cambios_ritmo = light.params_de_ritmo(ritmo)
        estilo = dict(contenido.get("estilo") or {})
        estilo.update(cambios_ritmo["assets"])
        contenido["estilo"] = estilo
        if contenido.get("voz"):
            contenido["voz"] = dict(contenido["voz"], **cambios_ritmo["voz"])
        contenido.setdefault("origen", {})["ritmo"] = ritmo
        try:
            _sembrar_taller(_taller_de(ficha), {"idioma": presets.idioma_de(ficha)
                                                or "es", "ritmo": ritmo})
        except ErrorApi:
            pass                    # sin taller el preset sigue siendo correcto

    if voz_pedida:
        limpios = {c: voz_pedida[c] for c in presets.TIPOS["voz"]["claves"]
                   if c in voz_pedida and voz_pedida[c] not in (None, "")}
        sobran = [c for c in voz_pedida if c not in presets.TIPOS["voz"]["claves"]]
        if sobran:
            raise ErrorApi(400, "un preset de voz no guarda "
                                + ", ".join(sorted(sobran)))
        if limpios:
            contenido["voz"] = dict(contenido.get("voz") or {}, **limpios)
            # y el origen recuerda la voz elegida a mano: rehacer «la voz» con
            # una frase pone los mandos a ESTA, no vuelve a elegir otra
            if limpios.get("voz_id"):
                contenido.setdefault("origen", {})["voz_id"] = limpios["voz_id"]
            try:
                _sembrar_voz(_taller_de(ficha), limpios)
            except ErrorApi:
                pass            # sin taller el preset sigue siendo correcto


    if instrucciones is not None:
        contenido.setdefault("guion", {})["instrucciones"] = instrucciones
        # Y AL TALLER, que es de donde sale la proxima congelacion. Sin esto,
        # rehacer despues la VOZ --o el ritmo, o cualquier cosa-- vuelve a
        # congelar el preset desde los params del taller y se lleva por delante
        # lo editado a mano, en silencio y sin que nadie lo haya pedido.
        try:
            _taller_de(ficha).estado.actualizar_params(
                "brief", {"instrucciones": instrucciones})
        except ErrorApi:
            pass                    # sin taller el preset sigue siendo correcto

    # LA PRESENTACION Y LAS LLAMADAS A LA ACCION, por el mismo PUT que el nombre
    # y la guia de tono: no cuestan nada --son texto y dos desplegables-- y son
    # del canal, que es lo que se escribe una vez y se repite en cada video. Van
    # al bloque `guion` del preset, que es de donde salen los params del guion
    # de cada video que se haga con este estilo.
    if datos.get("cta") is not None:
        try:
            contenido.setdefault("guion", {})["cta"] = _cta().normalizar(
                datos["cta"], estricto=True)
        except ValueError as fallo:
            raise ErrorApi(400, f"cta: {fallo}")
        # Y AL TALLER, por lo mismo que las instrucciones: sin esto, rehacer
        # cualquier parte vuelve a congelar el preset desde los params del
        # taller y se lleva por delante lo que se acaba de escribir.
        try:
            _taller_de(ficha).estado.actualizar_params(
                "guion", {"cta": contenido["guion"]["cta"]})
        except ErrorApi:
            pass                    # sin taller el preset sigue siendo correcto

    idioma_anterior = presets.idioma_de(ficha)
    if idioma and idioma != idioma_anterior:
        contenido.setdefault("guion", {})["idioma_salida"] = idioma
        contenido["guion"].pop("idiomas_salida", None)
        if contenido.get("voz"):
            contenido["voz"]["idioma"] = idioma
        contenido.setdefault("origen", {})["idioma"] = idioma
        # Y en el taller, que es de donde saldria la proxima regeneracion: sin
        # esto, corregir el tono despues de cambiar el idioma lo devolveria al
        # anterior en silencio.
        try:
            ctx = _taller_de(ficha)
            _sembrar_taller(ctx, {"idioma": idioma})
        except ErrorApi:
            pass                    # sin taller el preset sigue siendo correcto
    try:
        nueva = presets.guardar("canal", nombre, contenido,
                                nota=ficha.get("nota") or "",
                                miniatura=ficha.get("miniatura") or "",
                                pid=preset_id)
    except presets.ErrorPreset as fallo:
        raise ErrorApi(400, str(fallo))

    # CAMBIAR DE IDIOMA ADAPTA, NO REGENERA. Dos cosas llevan lengua dentro --las
    # instrucciones del guion y el texto dibujado en las muestras-- y las dos se
    # rehacen sin pagar una sola imagen: la primera es una llamada al CLI y la
    # segunda es volver a componer el texto sobre los planos limpios, que siguen
    # ahi. Ver `presets_light.TAREAS_DE_IDIOMA`.
    salida = {"preset": nueva}
    # LO QUE NO SE ADAPTA, DICHO Y CON SU PRECIO. Las laminas de estilo pueden
    # llevar letras DENTRO --el eje «diagrama» casi siempre-- y esas se
    # dibujaron en el idioma anterior. Cambiar el idioma no las redibuja (seis
    # imagenes; ver `presets_light.TAREAS_DE_IDIOMA`), y como despues viajan
    # como referencia dentro de cada plano con componentes, callarlo seria
    # dejar que ensenen a rotular en el idioma viejo sin que nadie lo sepa.
    aviso = light.aviso_de_idioma(idioma_anterior, idioma) if idioma else ""
    if aviso:
        salida["aviso_laminas"] = aviso
    if not adaptar:
        return salida
    try:
        ctx = _taller_de(nueva)
    except ErrorApi as fallo:
        # sin taller el estilo sigue siendo correcto: lo que queda es el tono en
        # la lengua anterior, y se dice en vez de callarlo
        salida["aviso"] = (f"el idioma ya está cambiado, pero {fallo.mensaje} — "
                           f"las instrucciones del guion y el texto de las "
                           f"muestras se quedan en el idioma anterior")
        return salida
    origen = dict((nueva.get("datos") or {}).get("origen") or {})
    origen["nombre"] = nombre
    origen["idioma"] = idioma
    encargo = _encargo_o_400(origen)
    _sembrar_taller(ctx, encargo)
    trabajo_id = ctx.gestor.lanzar(
        "preset_light", _correr_preset_light, ctx, encargo,
        list(light.TAREAS_DE_IDIOMA), preset_id, False, paso="assets")
    _registrar_trabajo(trabajo_id, ctx.id)
    ctx.bitacora.anotar("preset_light_idioma", None,
                        {"preset": preset_id, "idioma": idioma})
    salida.update({"trabajo_id": trabajo_id, "taller": ctx.id,
                   "plan": light.plan_de(encargo, light.TAREAS_DE_IDIOMA),
                   "trabajo": ctx.gestor.estado(trabajo_id),
                   "eventos": f"/api/trabajos/{trabajo_id}/eventos"})
    return salida


@app.delete("/api/presets-light/{preset_id}")
def borrar_preset_light(preset_id: str):
    """A la papelera de presets, y su taller con el.

    El taller no vale para nada sin su preset --son fotogramas de un estilo que
    ya no se puede aplicar-- y son cientos de megas. Va a la papelera de
    proyectos, que es donde se puede recuperar si el borrado fue un error.
    """
    ficha = _preset_o_400(lambda p: p.leer(preset_id))
    tid = ((ficha.get("datos") or {}).get("origen") or {}).get("taller")
    apartado = _preset_o_400(lambda p: p.apartar(preset_id))
    taller = ""
    if tid:
        try:
            apartar_proyecto(tid)
            taller = tid
        except ErrorApi:
            taller = ""             # ya no estaba: el preset se aparta igual
    return {"apartado": preset_id, "preset": apartado, "taller": taller}


# ==========================================================================
# EL VIDEO DEL MODO LIGHT: de un ESTILO a un MP4, en tres botones
#
# El modo light llegaba hasta el estilo (PENDIENTE 29). De aqui para abajo esta
# la segunda mitad: elegir un estilo y HACER UN VIDEO con el.
#
# LAS TRES TANDAS, y no cinco pestanas. En el modo editor cada pestana es una
# parada porque cada una tiene decisiones dentro. Aqui las decisiones son tres,
# y coinciden con las tres cosas que se pueden MIRAR antes de seguir:
#
#     guion            se lee y se corrige (a mano, por prompt, por bloque)
#     voz              se escucha, y editar un bloque regraba su seccion
#     video            se ve escena a escena, con su audio y su feedback
#     render           se monta, y se mira el MP4 entero
#
# HASTA EL 27-08 ERAN TRES: 'video' y 'render' iban juntas con el argumento de
# que entre las dos no habia ninguna decision. La hay, y es la mas cara de
# saltarse -- mirar los planos con su audio ANTES de montar --, asi que ahora
# son cuatro paradas y el MP4 es lo que se pide cuando ya has mirado.
#
# ESTO ES TAMBIEN PENDIENTE 28 (la tirada de punta a punta), que sale de
# standby: `POST /api/proyectos/{pid}/generar` acepta las pestanas que se le
# pidan, asi que las cinco de una tirada son un caso mas. Lo que no puede
# romper, y por eso esta escrito asi: el coste se dice ANTES (`GET .../generar`
# no lanza nada), y se puede interrumpir y retomar -- cancelar el trabajo corta
# donde este, y volver a lanzarlo en modo 'pendientes' se salta lo que ya salio.
# ==========================================================================

#: Marca en la config del proyecto: este video se hizo desde el modo light.
#: NO lo esconde de la lista (un video es un video, se haga por donde se haga);
#: lo que hace es decidir por el las tareas que en el modo editor se eligen a
#: mano. Hoy, una: la direccion de cada plano.
CONFIG_VIDEO_LIGHT = "video_light"

#: Y de que estilo salio, para poder decirlo y para poder volver a aplicarlo.
CONFIG_ESTILO_LIGHT = "estilo_light"

#: Las tandas del modo light, en orden, con las pestanas que recorre cada una.
TANDAS_LIGHT = [
    {"id": "guion", "nombre": "El guion", "pestanas": ["guion"],
     "porque": "lee el material y redacta el guion"},
    {"id": "voz", "nombre": "La voz", "pestanas": ["voz"],
     "porque": "adapta las siglas y las cifras, sintetiza y alinea"},
    # EL MP4 YA NO ENTRA AQUI. Esta tanda deja hecho todo lo que hace falta para
    # MIRAR el video sin montarlo --los planos, los subtitulos, las cartelas, la
    # musica y los efectos-- y se para. Lo que se mira despues es el
    # previsualizador escena a escena, y renderizar es lo que
    # se hace cuando ya has mirado.
    # LAS DIAPOSITIVAS SON LAS IMAGENES, Y NADA MAS.
    #
    # Llevaba tambien `callouts` --los subtitulos, las cartelas y el movimiento
    # de camara-- y eso ya no cuadra con lo que hace cada pantalla: en Imagenes
    # se mira el DIBUJO y nada mas (se quito de ahi todo lo que se monta
    # encima), asi que nada de callouts hace falta para esa revision.
    #
    # Donde si hace falta es al montar, y ahi es donde esta ahora. La cadena
    # queda en tres piezas con una frontera clara: guion y audio; las imagenes,
    # que solo dependen de esos dos; y el montaje, que es todo lo que se pone
    # encima --rotulos, transiciones, musica y efectos--.
    #
    # Efecto de lado, y es la mitad del motivo: rehacer un plano suelto dejaba
    # `callouts` obsoleto, y con callouts aqui dentro eso pintaba «Obsoleto» al
    # lado de las diapositivas, que estaban perfectamente al dia.
    {"id": "video", "nombre": "Las imágenes", "pestanas": ["video"],
     "sin": ["callouts"],
     "porque": "dibuja un plano por escena, listos para mirarlos uno a uno"},
    # MONTAR ES MONTAR LO QUE HAY, Y LO QUE HAY TIENE QUE ESTAR AL DIA.
    #
    # Esta tanda llevaba solo ["render"], asi que montaba con los rotulos de la
    # pasada anterior. Rehacer un plano suelto deja `callouts` obsoleto --su
    # movimiento y su capa son de ese dibujo-- y el render se plantaba con
    # «S007: el paso callouts no dejo movimiento», que no dice nada de lo que
    # de verdad pasa.
    #
    # Lleva la pestana entera y NO redibuja nada: el modo es «pendientes», y
    # ahi todo lo que ya esta al dia se salta (ver `_esta_al_dia`). Con assets
    # listo, lo unico que corre es lo que se quedo viejo.
    {"id": "render", "nombre": "El MP4", "pestanas": ["video", "render"],
     "porque": "pone al día los rótulos si hace falta y monta el vídeo"},
]
TANDAS_LIGHT_POR_ID = {t["id"]: t for t in TANDAS_LIGHT}


def _sin_de_la_tanda(datos):
    """Las tareas que esta tanda NO corre, aunque la receta las de por puestas.

    No se puede pedir por la receta: `recetas.resolver` fuerza las tareas no
    opcionales --y el render lo es-- justamente para que una receta guardada no
    se salte un paso obligado. Eso esta bien y no se toca; lo que una tanda dice
    es otra cosa: no que el paso sobre, sino que no toca AHORA.

    Hoy solo lo usa la tanda 'video' del modo light, que se para antes de montar
    el MP4 para que se pueda mirar escena a escena.
    """
    ficha = TANDAS_LIGHT_POR_ID.get(
        str((datos or {}).get("tanda") or "").strip().lower()) or {}
    return set(ficha.get("sin") or ())


def _receta_de_video(ctx, pestana, datos=None):
    """La receta con la que corre una pestana de ESTE proyecto.

    Dos diferencias, y las dos son del proyecto y no del canal:

      1. En un video del modo light va encendida de fabrica la DIRECCION. Esta
         apagada de fabrica porque en un video ya generado encenderla cuesta
         imagenes --cambia el prompt de todos los planos-- y eso no se enciende
         solo (`recetas.de_fabrica`). Un video del modo light nace nuevo y se
         genera de una tirada, asi que ahi no repaga nada. Y por lo mismo va
         encendida en cualquier video que todavia no tenga planos, se haya
         creado por donde se haya creado.
      2. Y NO se toca lo que la tanda deja fuera: eso no se puede pedir aqui.
         `recetas.resolver` fuerza las tareas NO OPCIONALES --y el render lo
         es-- para que una receta guardada no pueda saltarse un paso obligado.
         La exclusion de una tanda es otra cosa y va en `_sin_de_la_tanda`.

    Aqui se encendia tambien la REVISION de los planos, que miraba los PNG con
    un modelo y rehacia los que contradecian el relato. Se retiro entera el
    27-08: quien mira los planos vuelve a ser una persona, con
    el previsualizador escena a escena.
    """
    recetas = _recetas()
    datos = datos or {}
    pedidas = dict((datos.get("tareas") or {}))
    # Y EN CUALQUIER VIDEO QUE NUNCA HAYA GENERADO SUS PLANOS, venga del modo
    # que venga (02-09): el modo editor recorre ahora las mismas
    # tandas que el light, y la razon de tenerla apagada --repagar las imagenes
    # de un video ya dibujado-- no existe donde todavia no hay ninguna. Un
    # proyecto con planos hechos se queda como estaba: ahi encenderla sigue
    # siendo un clic y una factura, y eso lo decide una persona.
    if ctx.proyecto.config.get(CONFIG_VIDEO_LIGHT) \
            or not ctx.proyecto.version_activa("assets"):
        pedidas.setdefault("direccion", True)
    return recetas.resolver(pestana, datos.get("receta"), pedidas)


def _planos_previstos(ctx):
    """Cuantos planos va a tener este video y cuantos pagan imagen.

    Con el plan ya cortado se CUENTAN; sin el se estiman con la misma cuenta que
    `POST /api/estimacion` -- la duracion entre el plano medio del ritmo --,
    porque el precio hay que decirlo antes de que exista ningun plan.
    """
    light = PASOS_MODULOS.presets_light
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan.get("escenas") or []
    if escenas:
        cartelas = PASOS_MODULOS.cartelas
        con_imagen = [e for e in escenas
                      if not cartelas.sin_imagen(e)
                      and not e.get("sigue_a")]
        return {"total": len(escenas), "con_imagen": len(con_imagen),
                "origen": "el plan de este video"}
    brief = PASOS_MODULOS.comun.leer_salida(ctx.proyecto, "brief", "brief.json",
                                            obligatorio=False) or {}
    segundos = float(brief.get("duracion_objetivo_s")
                     or (ctx.estado.params("brief") or {}).get("duracion_objetivo_s")
                     or 0)
    assets = ctx.estado.params("assets") or {}
    ficha = light.ritmo_parecido(assets.get("min_s"), assets.get("max_s"))
    media = max(0.5, float(ficha["media_s"]))
    total = max(1, int(round(segundos / media))) if segundos else 0
    return {"total": total, "con_imagen": total,
            "origen": "estimado por la duración y el ritmo"}


def _imagenes_ya_generadas(ctx, planos):
    """Cuantos planos de los que PAGAN imagen la tienen ya en la carpeta.

    Es un HECHO, no una prediccion: el PNG esta escrito y su firma quedo
    guardada en el banco, asi que una tanda nueva lo recupera de la cache sin
    pagarlo (`p6_assets._producir_imagen` con rehacer=False). Lo unico que tira
    esa cache es que cambie el PROMPT o alguna referencia del plano -- y eso lo
    delata el propio plan, porque entonces la tarea de arriba sale con
    `al_dia: false`.

    Existe por un numero que asustaba con razon: una tanda cortada en el plano
    doscientos once de doscientos dieciseis volvia a ofrecerse como «216
    imagenes, 7,13 $». El precio era el del VIDEO ENTERO y no el de lo que
    faltaba, asi que retomar parecia costar lo mismo que empezar de cero -- y
    con esa cifra delante lo razonable es no pulsar.
    """
    if planos.get("origen") != "el plan de este video":
        return 0
    plan = PASOS_MODULOS.p6_assets.plan_actual(ctx.proyecto, "assets", estado=ctx.estado) or {}
    escenas = plan.get("escenas") or []
    if not escenas:
        return 0
    # EN LA CARPETA DE TRABAJO MIENTRAS SE GENERA, Y EN LA VERSION UNA VEZ
    # SELLADA. Mirar solo la de trabajo daba CERO en cuanto el paso terminaba
    # --que es justo cuando hay 216 imagenes hechas-- y el boton volvia a pedir
    # los 7,13 $ enteros. Se miran las dos, en ese orden: durante una tanda lo
    # nuevo esta en trabajo y lo de antes en la version.
    carpetas = [ctx.proyecto.ruta_trabajo("assets", crear=False)]
    version = ctx.proyecto.version_activa("assets")
    if version:
        carpetas.append(ctx.proyecto.ruta_paso("assets", version))
    carpetas = [os.path.join(c, "escenas") for c in carpetas
                if c and os.path.isdir(os.path.join(c, "escenas"))]
    if not carpetas:
        return 0
    cartelas = PASOS_MODULOS.cartelas
    hechas = 0
    for escena in escenas:
        # los mismos dos filtros que `_planos_previstos`, y a proposito: si
        # aqui se contara una cartela --que nunca deja PNG-- el descuento seria
        # de una imagen que nadie iba a pagar
        if cartelas.sin_imagen(escena) or escena.get("sigue_a"):
            continue
        if any(os.path.exists(os.path.join(c, f"{escena['id']}.png"))
               for c in carpetas):
            hechas += 1
    return hechas


def _coste_previsto(ctx, pestanas):
    """Lo que va a costar esta tanda, en dolares y en imagenes.

    Se dice ANTES de pulsar, que es la unica forma de que sirva. Las dos partes
    caras del Estudio son las IMAGENES (una por plano) y el TTS (por caracter);
    todo lo que llama al CLI va por la suscripcion y no entra aqui.
    """
    light = PASOS_MODULOS.presets_light
    planos = _planos_previstos(ctx)
    assets = ctx.estado.params("assets") or {}
    calidad = str(assets.get("calidad") or "low").lower()
    usd_imagen = light.USD_POR_IMAGEN.get(calidad, light.USD_POR_IMAGEN["low"])
    tarifas = COSTE.tarifas()
    usd_caracter = float(((tarifas.get("tts") or {}).get("usd_por_caracter")) or 0.0)

    imagenes = planos["con_imagen"] if "video" in pestanas else 0
    caracteres = 0
    if "voz" in pestanas:
        brief = PASOS_MODULOS.comun.leer_salida(
            ctx.proyecto, "brief", "brief.json", obligatorio=False) or {}
        palabras = int(brief.get("presupuesto_palabras") or 0)
        # con el guion escrito se cuentan sus caracteres de verdad; sin el, el
        # presupuesto de palabras por los 6,1 caracteres de la media medida
        guion = PASOS_MODULOS.comun.leer_salida(
            ctx.proyecto, "guion", "guion.json", obligatorio=False) or {}
        bloques = guion.get("guion") or []
        if bloques:
            caracteres = sum(len(str(b.get("texto") or "")) for b in bloques)
        else:
            caracteres = int(round(palabras * 6.1))
    usd_imagenes = round(imagenes * usd_imagen, 3)
    usd_tts = round(caracteres * usd_caracter, 4)
    # LO QUE YA ESTA HECHO VIAJA AL LADO DEL TECHO, no en su lugar. El total
    # sigue siendo lo que cuesta el video entero --que es lo que hay que pagar
    # si algo aguas arriba cambia y la cache falla-- y `por_generar` es lo que
    # cuesta si nada cambia. Ensenar solo uno de los dos miente en un sentido o
    # en el otro: uno asusta al que retoma, el otro promete barato de mas.
    hechas = _imagenes_ya_generadas(ctx, planos) if imagenes else 0
    hechas = min(hechas, imagenes)
    por_generar = max(0, imagenes - hechas)
    return {"imagenes": imagenes, "calidad": calidad,
            "usd_por_imagen": usd_imagen, "usd_imagenes": usd_imagenes,
            "imagenes_hechas": hechas, "imagenes_por_generar": por_generar,
            "usd_por_generar": round(por_generar * usd_imagen + usd_tts, 3),
            "caracteres": caracteres, "usd_tts": usd_tts,
            "usd_total": round(usd_imagenes + usd_tts, 3),
            "planos": planos}


def _tamano_para(clave, planos, palabras):
    """Con que unidad se mide ese paso o esa fase, y cuanto vale hoy.

    Sale de `estadisticas.INICIALES`, que es donde cada uno declara su unidad:
    preguntarselo a una lista escrita aqui seria una segunda tabla que se
    desincroniza en cuanto alguien anade un paso.
    """
    unidad = str((ESTADISTICAS.INICIALES.get(str(clave)) or {}).get("unidad") or "")
    if "palabra" in unidad:
        return palabras
    if "segundo" in unidad:
        return 0
    return planos["total"]


def _fraccion_por_hacer(ctx, paso):
    """Que parte de un paso por unidades queda por rehacer. -> 0 < x <= 1

    LA ESTIMACION DEL HISTORIAL ES SIEMPRE DEL PASO ENTERO, y en una tanda
    «pendientes» eso miente por goleada. Montar el MP4 de un video con sus 302
    imagenes ya dibujadas prometia 282 minutos --lo que cuesta dibujarlas-- y
    duro veinte: `assets` no estaba «al dia» porque el feedback de UN plano le
    habia movido la firma, pero lo que quedaba por dibujar era ese plano y nada
    mas. Medido el 08-09-2026 en `video_referencia`, con la barra diciendo «quedan
    ~261m» a los veinte minutos de haber pulsado.

    Se mide con las unidades OBSOLETAS --que es exactamente lo que un modo
    «pendientes» va a rehacer-- contra las declaradas. Es la misma cuenta que
    ya hace el coste con `imagenes_por_generar`: lo que se dice del dinero y lo
    que se dice del reloj salen del mismo sitio.

    Suelo de una unidad: un paso que corre tarda algo, y un cero dejaria su
    tramo de la barra con ancho nulo -- que en pantalla es una tarea que no
    existe. Y NUNCA LEVANTA: no saber repartir el reloj no puede tumbar una
    tanda de cincuenta minutos.
    """
    try:
        if not (PASOS_POR_ID.get(paso) or {}).get("unidades"):
            return 1.0
        declaradas = len(ctx.estado.unidades_declaradas(paso))
        if not declaradas:
            return 1.0
        obsoletas = len(ctx.estado.unidades_obsoletas(paso))
        return min(1.0, max(1, obsoletas) / float(declaradas))
    except Exception:                                         # noqa: BLE001
        return 1.0


def _segundos_de_tarea(ctx, tarea, planos, palabras, reparto=None,
                       modo="todo"):
    """Lo que se espera que tarde una tarea, del historial real de esta maquina.

    UNA TAREA NO ES UN PASO. Aqui se estimaba el PASO de cada tarea, y la
    pestana Video tiene CINCO tareas del paso `assets`: la cuenta salia por
    cinco (medido: 20.742 s para una tanda de veinte minutos). Asi que:

      - una tarea con FASE propia (`catalogo_visual`, `guia_estilo`,
        `plan_cartelas`, `direccion`) se estima con su fase, que tiene su propio
        historial medido;
      - las que no la tienen SON el paso, y se reparten su tiempo entre ellas.

    Con eso el total de la tanda vuelve a ser el tiempo del paso, que es lo
    unico que la barra promete de verdad.
    """
    fase = tarea.get("fase")
    if fase:
        # UNA FASE NO SE ESCALA. Las tareas con fase propia --la guia de estilo,
        # el corte de cartelas, la direccion-- no rehacen las unidades del paso:
        # hacen lo suyo entero o no se hacen, y tienen su propio historial
        # medido. Lo que se escala mas abajo son las que SON el paso.
        ajuste = _ajuste_de_fase(_receta_de_video(ctx, tarea["pestana"]), fase)
        return float(ESTADISTICAS.estimar(
            fase, tamano=_tamano_para(fase, planos, palabras),
            ajuste={"modelo": ajuste["modelo"],
                    "esfuerzo": ajuste["esfuerzo"]})["segundos"])
    paso = tarea["paso"]
    entre = max(1, int((reparto or {}).get(paso, 1)))
    segundos = float(ESTADISTICAS.estimar(
        paso, tamano=_tamano_para(paso, planos, palabras))["segundos"]) / entre
    # SOLO EN «pendientes»: en modo 'todo' se rehace el paso entero y el
    # historial del paso entero es justo lo que va a tardar.
    if modo == "pendientes":
        segundos *= _fraccion_por_hacer(ctx, paso)
    return segundos


def _plan_de_generacion(ctx, pestanas, modo="pendientes", datos=None):
    """Que se va a hacer, cuanto va a tardar y cuanto va a costar. No lanza nada.

    LA BARRA VA POR TIEMPO MEDIDO, no por numero de tareas, y por la misma razon
    que en el modo light de los estilos: con las imagenes
    tardando seis minutos y el brief dos segundos, contar tareas da una barra
    que se planta y despues salta.
    """
    recetas = _recetas()
    planos = _planos_previstos(ctx)
    brief = PASOS_MODULOS.comun.leer_salida(
        ctx.proyecto, "brief", "brief.json", obligatorio=False) or {}
    palabras = int(brief.get("presupuesto_palabras") or 0)
    fases, total = [], 0.0
    for pestana in pestanas:
        receta = _receta_de_video(ctx, pestana, datos)
        sin = _sin_de_la_tanda(datos)
        puestas = [t for t in recetas.puestas_de(pestana, receta)
                   if t not in sin]
        orden = recetas.orden_de(pestana, puestas)
        # cuantas tareas de cada paso NO tienen fase propia: son las que SON el
        # paso, y se reparten su tiempo en vez de contarlo cada una entera
        reparto = {}
        for tarea in orden:
            if not tarea.get("fase"):
                reparto[tarea["paso"]] = reparto.get(tarea["paso"], 0) + 1
        tareas = []
        for tarea in orden:
            al_dia = _esta_al_dia(ctx, tarea)
            segundos = _segundos_de_tarea(ctx, tarea, planos, palabras,
                                          reparto, modo)
            tareas.append({
                "id": tarea["id"], "nombre": tarea["nombre"],
                "publico": recetas.publico_de(tarea["id"]),
                "paso": tarea["paso"], "porque": tarea.get("porque", ""),
                "cuesta": bool(tarea["cuesta"]), "al_dia": al_dia,
                "se_hace": not (modo == "pendientes" and al_dia),
                "segundos": round(segundos, 1)})
        pendientes = [t for t in tareas if t["se_hace"]]
        segundos = round(sum(t["segundos"] for t in pendientes), 1)
        fases.append({"pestana": pestana, "tareas": tareas,
                      "pendientes": [t["id"] for t in pendientes],
                      "segundos": segundos, "desde": round(total, 1),
                      "impedimentos": _impedimentos(
                          ctx, pestana,
                          [{"id": t["id"]} for t in pendientes])})
        total += segundos
    return {
        "pestanas": list(pestanas), "modo": modo,
        "fases": fases,
        "segundos": round(total, 1),
        "tareas": sum(len(f["pendientes"]) for f in fases),
        "coste": _coste_previsto(ctx, pestanas),
        "impedimentos": [i for f in fases for i in f["impedimentos"]],
    }


def _correr_cadena(avisar, ctx, pestanas, modo, datos, plan):
    """Recorre varias pestanas seguidas en UN trabajo. -> resumen.

    Cada pestana ocupa en la barra lo que se espera que tarde, y dentro de ella
    manda el progreso de `_correr_receta`, que ya reparte por tarea. Asi la
    barra de «Generar Vídeo» no se planta en el 50 % durante los seis minutos
    de las imagenes.

    SE INTERRUMPE Y SE RETOMA. Cancelar el trabajo corta en la siguiente llamada
    a `avisar` (nucleo/trabajos.py), y volver a lanzarlo en modo 'pendientes' se
    salta lo que ya salio bien: no hay estado que guardar aparte, porque lo que
    dice por donde iba es el propio proyecto.
    """
    recetas = _recetas()
    total = max(1.0, float(plan["segundos"]))
    salida = {"pestanas": [], "modo": modo, "tareas": [], "saltadas": []}
    # EL CONTADOR PUBLICO ES DE LA TANDA ENTERA, no de cada pestana, y cuenta lo
    # que SE VA A HACER. Contaba todas las tareas del plan --tambien las que se
    # iban a saltar-- y montar el MP4 de un video ya dibujado decia «11 de 11»
    # con tres tareas por delante. Es la misma cuenta que hace `_correr_receta`
    # dentro de cada pestana, que es lo que impide un «9 de 8».
    total_publico = sum(len(f["pendientes"]) for f in plan["fases"])
    hechas_antes = 0
    for ficha in plan["fases"]:
        pestana = ficha["pestana"]
        desde = float(ficha["desde"]) / total
        trozo = max(0.001, float(ficha["segundos"]) / total)

        def avisar_fase(valor, mensaje="", publico="",
                        _d=desde, _t=trozo, _p=pestana):
            avisar(min(0.999, _d + _t * min(1.0, max(0.0, float(valor or 0)))),
                   f"{_p} · {mensaje}" if mensaje else _p,
                   # el nombre de la pestana NO va en el publico: es de casa
                   publico)

        receta = _receta_de_video(ctx, pestana, datos)
        sin = _sin_de_la_tanda(datos)
        puestas = [t for t in recetas.puestas_de(pestana, receta)
                   if t not in sin]
        if not recetas.orden_de(pestana, puestas):
            continue
        hecho = _correr_receta(avisar_fase, ctx, pestana, receta, puestas, modo,
                               hechas_antes=hechas_antes,
                               total_global=total_publico)
        # LAS QUE DE VERDAD HAN CORRIDO, no las que el plan preveia: entre
        # planificar y correr una tarea puede haber dejado de estar al dia, y
        # entonces el contador de la pestana siguiente arrancaria por debajo.
        hechas_antes += len(hecho.get("tareas") or [])
        salida["pestanas"].append(pestana)
        salida["tareas"].extend(hecho.get("tareas") or [])
        salida["saltadas"].extend(hecho.get("saltadas") or [])
    salida["resumen"] = (f"{len(salida['tareas'])} tareas en "
                         f"{len(salida['pestanas'])} pestañas"
                         + (f", {len(salida['saltadas'])} ya estaban"
                            if salida["saltadas"] else ""))
    avisar(1.0, salida["resumen"], PUBLICO_LISTO)
    return salida


def _pestanas_pedidas(datos):
    """Las pestanas de una peticion de generacion, validadas y en orden.

    Acepta `tanda` (guion|voz|video, las tres del modo light) o `pestanas` (la
    lista cruda, que es lo que usa la tirada de punta a punta). Sin nada, las
    cinco: eso es PENDIENTE 28.
    """
    recetas = _recetas()
    tanda = str(datos.get("tanda") or "").strip().lower()
    if tanda:
        if tanda not in TANDAS_LIGHT_POR_ID:
            raise ErrorApi(400, f"tanda desconocida: {tanda!r}. Son "
                                + ", ".join(TANDAS_LIGHT_POR_ID))
        return list(TANDAS_LIGHT_POR_ID[tanda]["pestanas"])
    crudas = datos.get("pestanas")
    if crudas is None:
        return list(recetas.PESTANAS)
    if isinstance(crudas, str):
        crudas = [crudas]
    if not isinstance(crudas, list) or not crudas:
        raise ErrorApi(400, "'pestanas' tiene que ser una lista de pestanas")
    pedidas = [str(p).strip().lower() for p in crudas]
    for pestana in pedidas:
        if pestana not in recetas.PESTANAS:
            raise ErrorApi(404, f"pestana desconocida: {pestana}. Son "
                                + ", ".join(recetas.PESTANAS))
    # EN EL ORDEN DEL PIPELINE, no en el que lleguen: pedir «render, video»
    # renderizaria clips de unos planos que todavia no existen.
    return [p for p in recetas.PESTANAS if p in pedidas]


def _con_origen(ctx, pestanas):
    """La tanda del guion se lleva el ORIGEN si a la ingesta le falta correr.

    En el modo light no hay una pestana «Origen»: hay MATERIAL, y el material
    vive en los params del paso `ingesta`. Pero un param no es una version:
    `brief` depende de `ingesta` y sigue BLOQUEADO hasta que la ingesta corre
    y deja la suya (`dependencias_que_faltan` pregunta por la version, y es lo
    unico que pregunta desde que el material tiene una sola via).

    Esto anadia el origen SOLO si habia una URL de YouTube que bajar --era la
    regla de cuando el material podia venir tambien del documentalista-- y con
    material pegado no anadia nada. Resultado: en un video nuevo la tanda del
    guion llegaba a `brief` con la ingesta sin correr y el servidor contestaba
    «no se puede generar todavia: falta ejecutar ingesta» (visto el 10-09 al
    pulsar «Generar el guion» desde el encargo). Ahora se mira lo que importa:
    si la ingesta NO esta al dia --nunca ha corrido, o el material ha cambiado--
    va delante. Si ya lo esta, no se anade y la tanda queda como antes: con
    modo 'pendientes' se saltaria igual, y con 'todo' no hay por que rehacer
    una entrada que no ha cambiado.
    """
    lista = list(pestanas)
    if "guion" not in lista or "origen" in lista:
        return lista
    if ctx.estado.al_dia("ingesta"):
        return lista
    return ["origen"] + lista


def _trabajo_de_cadena(ctx):
    for ficha in ctx.gestor.listar(activos=True):
        if str(ficha.get("nombre") or "").startswith("generar:"):
            return ficha
    return None


#: Un cerrojo por proyecto para MIRAR-Y-LANZAR una tanda sin que se cuelen dos.
#:
#: Entre la comprobacion de «ya se esta generando» y el `lanzar` hay varios
#: segundos: se calcula el plan entero, su coste y sus impedimentos. El 01-09 se
#: pulso «Montar el vídeo» dos veces con nueve segundos de diferencia y las dos
#: pasaron el 409 -- la primera todavia no habia registrado su trabajo --. Los
#: dos hilos escribieron en la misma carpeta de trabajo y el que llego segundo
#: se encontro con que el primero ya la habia versionado: FileNotFoundError
#: sobre su propio fichero temporal.
_CERROJOS_CADENA = {}
_CERROJO_CERROJOS = threading.Lock()


def _cerrojo_de_cadena(pid):
    with _CERROJO_CERROJOS:
        return _CERROJOS_CADENA.setdefault(str(pid), threading.Lock())


@app.get("/api/proyectos/{pid}/generar")
def plan_de_generacion(pid: str, tanda: str = Query(default=""),
                       pestanas: str = Query(default=""),
                       modo: str = Query(default="pendientes")):
    """Lo que va a hacer, cuanto tarda y cuanto cuesta. NO lanza nada.

    Es lo que se lee al lado del boton antes de pulsarlo. Una cifra inventada en
    la pantalla y otra distinta durante la generacion serian dos mentiras, y la
    segunda tardaria diez minutos en descubrirse.
    """
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    ctx = contexto(pid)
    datos = {"tanda": tanda,
             "pestanas": [p for p in pestanas.split(",") if p.strip()] or None}
    if not tanda and not datos["pestanas"]:
        datos.pop("pestanas")
    modo = str(modo or "pendientes").strip().lower()
    if modo not in ("todo", "pendientes"):
        raise ErrorApi(400, f"modo desconocido: {modo!r}. Usa 'todo' o 'pendientes'")
    elegidas = _con_origen(ctx, _pestanas_pedidas(datos))
    # CON `datos` DELANTE, igual que el POST. Sin esto la tanda no llegaba hasta
    # aqui y el plan ENSENADO traia el render que la tanda de video no hace: el
    # boton prometia cuatro tareas y corrian tres. Una cifra en la pantalla y
    # otra durante la generacion son dos mentiras, que es justo lo que este
    # endpoint existe para evitar.
    plan = _plan_de_generacion(ctx, elegidas, modo, datos)
    plan["trabajo"] = _trabajo_de_cadena(ctx) or {}
    plan["tandas"] = TANDAS_LIGHT
    return plan


@app.post("/api/proyectos/{pid}/generar", status_code=202)
def generar_video(pid: str, cuerpo: dict = Body(default=None)):
    """Recorre varias pestanas seguidas, en orden, en UN trabajo.

    Es el boton que faltaba (PENDIENTE 28) y el motor de las tres tandas del
    modo light. `params` se guardan ANTES de planificar, por el mismo motivo que
    en `ejecutar_paso`: la pantalla manda lo que hay escrito al pulsar, y
    generar con los valores anteriores seria mentir.
    """
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    for paso_id, valores in (datos.get("params") or {}).items():
        if paso_id not in PASOS_POR_ID:
            raise ErrorApi(400, f"'{paso_id}' no es un paso: no tiene params")
        if not isinstance(valores, dict):
            raise ErrorApi(400, f"los params de '{paso_id}' tienen que ser un objeto")
        # `_validar_params` VALIDA y no devuelve nada: lo que se guarda es lo
        # que llego. Encadenarlas escribiria None y no guardaria nada.
        _validar_params(paso_id, valores, ctx)
        ctx.estado.actualizar_params(paso_id, valores)

    modo = str(datos.get("modo") or "pendientes").strip().lower()
    if modo not in ("todo", "pendientes"):
        raise ErrorApi(400, f"modo desconocido: {modo!r}. Usa 'todo' o 'pendientes'")
    elegidas = _con_origen(ctx, _pestanas_pedidas(datos))

    # MIRAR-Y-LANZAR, DENTRO DEL CERROJO. Comprobar fuera no vale: entre la
    # comprobacion y el `lanzar` se calcula el plan entero, y en esos segundos
    # cabe un segundo clic (ver `_cerrojo_de_cadena`).
    with _cerrojo_de_cadena(ctx.id):
        activo = _trabajo_de_cadena(ctx)
        if activo is not None:
            raise ErrorApi(409, "este video ya se esta generando",
                           {"trabajo_id": activo["id"], "progreso": activo["progreso"]})
        for pestana in elegidas:
            if _trabajo_de_receta(ctx, pestana) is not None:
                raise ErrorApi(409, f"la pestana '{pestana}' ya se esta generando")

        plan = _plan_de_generacion(ctx, elegidas, modo, datos)
        if not plan["tareas"]:
            raise ErrorApi(400, "no queda nada por generar en "
                                + ", ".join(elegidas)
                                + ". Con modo 'todo' se rehace de todas formas")
        # LO QUE VA A PARAR LA TANDA, DICHO ANTES. Un 400 aqui es un mensaje; el
        # mismo fallo dentro del hilo es una barra que se pone roja a los seis
        # minutos con la mitad hecha.
        if plan["impedimentos"]:
            primero = plan["impedimentos"][0]
            raise ErrorApi(409, primero["que"], {"impedimentos": plan["impedimentos"]})
        recetas = _recetas()
        producidos = set()
        for ficha in plan["fases"]:
            for tarea in ficha["tareas"]:
                producidos.add(recetas.TAREAS_POR_ID[tarea["id"]]["paso"])
        for ficha in plan["fases"]:
            for tarea in ficha["tareas"]:
                paso = recetas.TAREAS_POR_ID[tarea["id"]]["paso"]
                if ctx.estado.estado_de(paso) != "bloqueado":
                    continue
                faltan = dependencias_que_faltan(ctx, paso, producidos)
                if faltan:
                    raise ErrorApi(409, "no se puede generar todavia: falta "
                                        "ejecutar " + ", ".join(faltan),
                                   {"faltan": faltan, "tarea": tarea["id"]})

        trabajo_id = ctx.gestor.lanzar("generar:" + "+".join(elegidas),
                                       _correr_cadena, ctx, elegidas, modo, datos,
                                       plan, paso=plan["fases"][0]["tareas"][0]["paso"])
    _registrar_trabajo(trabajo_id, ctx.id)
    ctx.bitacora.anotar("generacion_lanzada", None, {
        "pestanas": elegidas, "modo": modo, "tareas": plan["tareas"],
        "segundos_previstos": plan["segundos"],
        "usd_previstos": plan["coste"]["usd_total"]})
    return {"trabajo_id": trabajo_id, "pestanas": elegidas, "modo": modo,
            "plan": plan, "trabajo": ctx.gestor.estado(trabajo_id),
            "eventos": f"/api/trabajos/{trabajo_id}/eventos"}


@app.post("/api/presets-light/{preset_id}/video", status_code=201)
def crear_video_light(preset_id: str, cuerpo: dict = Body(default=None)):
    """Un proyecto de video nuevo con ese estilo ya aplicado. -> la ficha.

    ES UN PROYECTO NORMAL Y SE VE EN LA LISTA. No es un taller: un taller es la
    carpeta donde se genero un estilo y no es de nadie; esto es un video, y un
    video se hace por donde se quiera pero es el mismo video. Se puede abrir en
    el modo editor y seguir ahi.

    Lo que se le escribe al nacer son las cuatro decisiones que la pantalla del
    modo light ya ha tomado: el estilo (aplicando el preset, con el MISMO codigo
    que el boton del modo editor), la duracion y el material.
    """
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    datos = _cuerpo(cuerpo)
    presets = _presets()
    # 404 y no 400: un estilo que no existe es una direccion equivocada, no una
    # peticion mal escrita. `_preset_o_400` traduce todo a 400 porque casi todo
    # lo que rechaza el almacen son datos malos; esto no.
    try:
        ficha_preset = presets.leer(preset_id)
    except presets.ErrorPreset as fallo:
        raise ErrorApi(404, str(fallo))
    if not ficha_preset:
        raise ErrorApi(404, f"no hay ningun estilo '{preset_id}'")
    if ficha_preset.get("tipo") != "canal":
        raise ErrorApi(400, f"el preset '{preset_id}' es de tipo "
                            f"'{ficha_preset.get('tipo')}': el modo light hace "
                            f"videos con estilos de canal")

    nombre = str(datos.get("nombre") or "").strip()
    if not nombre:
        nombre = f"Vídeo de {ficha_preset.get('nombre') or preset_id}"
    if not identificador(nombre):
        raise ErrorApi(400, f"'{nombre}' no da un identificador valido")
    os.makedirs(raiz_proyectos(), exist_ok=True)
    base, intento = nombre[:60], 1
    while os.path.isdir(os.path.join(raiz_proyectos(), identificador(nombre))):
        intento += 1
        nombre = f"{base} {intento}"
    try:
        proyecto = Proyecto.crear(raiz_proyectos(), nombre)
    except OSError as fallo:
        raise ErrorApi(500, f"no se ha podido crear el video: {fallo}")
    ctx = contexto(proyecto.id)
    ctx.proyecto.config[CONFIG_VIDEO_LIGHT] = True
    ctx.proyecto.config[CONFIG_ESTILO_LIGHT] = preset_id
    ctx.proyecto.guardar_config()

    # EL ESTILO, con el mismo codigo que el boton del modo editor. Un segundo
    # camino que copiara las claves a mano se quedaria viejo el dia que un
    # preset guarde una mas.
    aplicado = aplicar_preset_canal(proyecto.id, preset_id)
    avisos = _sembrar_video_light(ctx, datos)
    ctx.bitacora.anotar("video_light_creado", None, {
        "preset": preset_id, "estilo": ficha_preset.get("nombre"),
        "nombre": nombre, "avisos": avisos})
    return {"proyecto": ficha_proyecto(ctx),
            "estilo": {"id": preset_id, "nombre": ficha_preset.get("nombre")},
            "aplicado": aplicado.get("pasos") or [],
            "avisos": avisos,
            "pasos": [ficha_paso(ctx, p["id"]) for p in PASOS]}


def _sembrar_video_light(ctx, datos):
    """Las decisiones que la pantalla del modo light ya ha tomado. -> [avisos]

    Son params de siempre y de pasos de siempre: la duracion y el tema van al
    brief, y el material al paso «Origen». Nada de esto es una via nueva -- es
    rellenar los mismos cajones que rellena el modo editor a mano, que es la
    unica forma de que las dos pantallas no se separen.
    """
    avisos = []
    brief, guion = {}, {}
    if datos.get("duracion_objetivo_s") is not None:
        brief["duracion_objetivo_s"] = datos["duracion_objetivo_s"]
    # EL FORMATO, junto a la duracion: horizontal o vertical.
    # Es una decision del video y va al brief, de donde la leen los pasos.
    if datos.get("formato") is not None:
        brief["formato"] = PASOS_MODULOS.comun.normalizar_formato(datos["formato"])
    # LAS INSTRUCCIONES DEL BRIEF NO SE TOCAN, y es deliberado: ahi vive la GUIA
    # DE TONO del canal, que es lo que acaba de escribir el estilo al aplicarse.
    # En el modo light no hay un campo «de que va el video»: el material ES el
    # encargo y el nombre del proyecto es como lo llamo quien lo creo.
    # Machacarlas aqui borraria el tono del canal con una frase de este video.
    if datos.get("instrucciones") is not None:
        brief["instrucciones"] = str(datos["instrucciones"] or "")
    # EL MATERIAL, al paso «Origen»: es su param, con su version y su firma.
    # Aqui llega como un texto y no como una lista de fuentes -- ya no hay
    # varias, ni enlaces que resolver, ni nada que buscar fuera.
    ingesta = {}
    if datos.get("material") is not None:
        ingesta["texto"] = str(datos["material"] or "")
    if datos.get("titulo_material") is not None:
        ingesta["titulo"] = str(datos["titulo_material"] or "")
    # Y SI LO PEGADO YA ES EL GUION, la regla del redactor cambia: no se
    # reescribe, se respeta. Es del guion --es una regla de SU prompt-- y no del
    # material, que es el mismo texto en los dos casos.
    if datos.get("guion_propio") is not None:
        guion["guion_propio"] = bool(datos["guion_propio"])
    # LA PRESENTACION Y LAS LLAMADAS A LA ACCION. Se normalizan AQUI --y no al
    # redactar-- para que un producto que no existe se conteste al crear el
    # video, que es cuando hay alguien mirando la pantalla, y no veinte minutos
    # despues. El estilo ya las trae puestas (van en el preset de guion); esto
    # es lo que el encargo de ESTE video haya cambiado.
    if datos.get("cta") is not None:
        try:
            guion["cta"] = _cta().normalizar(datos["cta"], estricto=True)
        except ValueError as fallo:
            raise ErrorApi(400, f"cta: {fallo}")
    # LAS INDICACIONES DEL VIDEO, al cajon del guion que existe para eso
    # (`prompt_general`): «no fuerces una historia de personaje», «no incluyas
    # la entrevista». Van aparte del material a proposito -- el material son los
    # HECHOS y esto es COMO contarlos --, y no se pisa lo que ya hubiera escrito.
    if datos.get("indicaciones") is not None:
        guion["prompt_general"] = str(datos["indicaciones"] or "")
    if ingesta:
        _validar_params("ingesta", ingesta, ctx)
        ctx.estado.actualizar_params("ingesta", ingesta)
    if brief:
        _validar_params("brief", brief, ctx)
        ctx.estado.actualizar_params("brief", brief)
    if guion:
        _validar_params("guion", guion, ctx)
        ctx.estado.actualizar_params("guion", guion)
    return avisos


def _cta():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.cta


# ==========================================================================
# EL MATERIAL DEL VIDEO
#
# SI es un paso del grafo --«Origen», `pasos/p1_ingesta.py`-- y por eso aqui solo
# hay lectura. El texto vive en su param, con su version y su firma, asi que
# cambiarlo deja obsoletos el brief, el guion, la voz y todo lo que cuelga, que
# es exactamente lo que tiene que pasar.
#
# `pasos/fuentes.py` es quien lo LEE, y esta separado del paso que lo escribe a
# proposito: el porque esta en su cabecera.
# ==========================================================================

def _fuentes():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.fuentes


@app.get("/api/estadisticas")
def estadisticas_globales(paso: str = Query(default=""),
                          tamano: int = Query(default=0)):
    """Historico de tiempos reales, entre todos los proyectos.

    Sin 'paso' devuelve el panorama; con 'paso' devuelve la comparativa completa
    de combinaciones mas la recomendacion.
    """
    if not paso:
        return ESTADISTICAS.panorama()
    return {
        "paso": paso,
        "comparativa": ESTADISTICAS.comparativa(paso, tamano=tamano),
        "recomendacion": ESTADISTICAS.recomendacion(paso, tamano=tamano),
        "historial": ESTADISTICAS.historial(paso)[-40:],
    }


@app.post("/api/estadisticas/valoracion")
def valorar_ajuste(cuerpo: dict = Body(default=None)):
    """Anota si el resultado de un ajuste gusto o no.

    Es la unica senal de calidad que no es un proxy. Sin ella el recomendador
    solo sabria recomendar lo mas rapido, que es una tautologia, no un consejo.
    """
    datos = _cuerpo(cuerpo)
    paso = str(datos.get("paso") or "").strip()
    if not paso:
        raise ErrorApi(400, "hace falta decir de que paso es la valoracion")
    ajuste = _ajuste_cli(datos)
    try:
        anotada = ESTADISTICAS.valorar(
            paso, datos.get("valoracion"), ajuste=ajuste,
            proyecto=datos.get("proyecto"), nota=datos.get("nota"))
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    if anotada is None:
        raise ErrorApi(409, f"todavia no hay ninguna ejecucion de '{paso}' con "
                            f"{ajuste['modelo']}/{ajuste['esfuerzo']} que valorar")
    return {"anotada": anotada,
            "recomendacion": ESTADISTICAS.recomendacion(paso)}


# ------------------------------------------------------------------- capturas
# La captura del fotograma la compone el navegador (en callouts rehaciendo la
# ventana de zoom con la misma matematica del render, en render dibujando el
# <video> en un canvas). Aqui llega ya como PNG y se guarda con su anotacion.

def almacen(ctx):
    """Almacen de capturas del proyecto."""
    return CAPTURAS.Almacen(ctx.proyecto)


def _p7():
    if PASOS_MODULOS is None:
        raise ErrorApi(503, f"los pasos no se han podido cargar: {ERROR_PASOS}")
    return PASOS_MODULOS.p7_callouts


def _ficha_captura(ctx, ficha):
    """Ficha de captura con la URL con la que la interfaz pinta el PNG."""
    salida = dict(ficha)
    salida["url"] = f"/a/{ctx.id}/" + str(ficha.get("imagen") or "")
    return salida


async def _cuerpo_captura(peticion):
    """Lee la captura venga como multipart o como JSON con la imagen en base64."""
    tipo = (peticion.headers.get("content-type") or "").lower()
    if tipo.startswith("multipart/"):
        try:
            formulario = await peticion.form()
        except Exception as fallo:  # noqa: BLE001
            raise ErrorApi(400, f"multipart ilegible: {fallo}")
        datos, imagen = {}, None
        for clave, valor in formulario.multi_items():
            if hasattr(valor, "read"):
                if clave in ("imagen", "png", "captura"):
                    imagen = await valor.read()
                continue
            datos[clave] = valor
        return datos, imagen
    try:
        datos = await peticion.json()
    except Exception:  # noqa: BLE001
        raise ErrorApi(400, "manda la captura como multipart (imagen + campos) "
                            "o como JSON con 'imagen_b64'")
    datos = datos if isinstance(datos, dict) else {}
    return datos, datos.get("imagen_b64") or datos.get("imagen")


@app.post("/api/proyectos/{pid}/capturas", status_code=201)
async def crear_captura(pid: str, peticion: Request):
    """Guarda una captura anotada de los pasos callouts o render.

    Acepta multipart (imagen + metadatos) y tambien JSON con 'imagen_b64', que
    es lo comodo para un cliente que ya tiene el dataURL del canvas.
    """
    ctx = contexto(pid)
    datos, imagen = await _cuerpo_captura(peticion)
    if imagen is None:
        raise ErrorApi(400, "falta el PNG de la captura ('imagen' en multipart "
                            "o 'imagen_b64' en JSON)")
    paso = CAPTURAS.validar_paso(datos.get("paso"))
    escena = str(datos.get("escena") or "").strip() or None
    t_video = CAPTURAS.segundos(datos.get("t_video"), "t_video")
    t_escena = CAPTURAS.segundos(datos.get("t_escena"), "t_escena")
    if escena is None and t_video is None:
        raise ErrorApi(400, "hace falta 'escena' o 't_video' para situar la captura")

    temporal = _p7().contexto_temporal(ctx.proyecto, escena, t_video, t_escena)
    escena = temporal.get("escena") or escena
    if not escena:
        raise ErrorApi(400, f"no hay ningun plano en t_video={t_video}: "
                            f"manda 'escena' o ejecuta callouts antes")
    _comprobar_unidades(ctx, paso, [f"escena:{escena}"])

    ficha = almacen(ctx).crear(
        paso, escena, imagen,
        trazos=datos.get("trazos"),
        comentario=datos.get("comentario") or datos.get("texto") or "",
        t_video=temporal.get("t_video", t_video),
        t_escena=temporal.get("t_escena", t_escena),
        contexto=temporal)
    ctx.bitacora.anotar("captura_tomada", paso, {
        "captura": ficha["id"], "imagen": ficha["imagen"],
        "t_video": ficha["t_video"], "t_escena": ficha["t_escena"],
        "comentario": ficha["comentario"], "trazos": len(ficha["trazos"]),
        "instante": temporal.get("frase", "")}, unidad=ficha["unidad"])
    return {"captura": _ficha_captura(ctx, ficha), "contexto": temporal}


@app.get("/api/proyectos/{pid}/capturas")
def listar_capturas(pid: str, paso: str = Query(default=None),
                    escena: str = Query(default=None),
                    pendientes: int = Query(default=0)):
    """Capturas del proyecto, filtrables por paso y escena."""
    ctx = contexto(pid)
    fichas = almacen(ctx).listar(paso=paso, escena=escena,
                                 pendientes=True if pendientes else None)
    fichas = [_ficha_captura(ctx, f) for f in fichas]
    return {"proyecto": ctx.id, "capturas": fichas, "total": len(fichas),
            "pendientes": sum(1 for f in fichas if not f.get("aplicada"))}


@app.get("/api/proyectos/{pid}/capturas/contexto")
def contexto_captura(pid: str, paso: str = Query(default="callouts"),
                     escena: str = Query(default=None),
                     t_video: float = Query(default=None),
                     t_escena: float = Query(default=None)):
    """Donde cae un instante y con que material se compone ese fotograma.

    La interfaz necesita la ventana de zoom EXACTA de ese instante para pintar
    el fotograma igual que lo pinta el render; calcularla dos veces con dos
    formulas parecidas es justo lo que haria que la captura y el video no
    coincidiesen.
    """
    ctx = contexto(pid)
    paso = CAPTURAS.validar_paso(paso)
    p7 = _p7()
    ficha = p7.contexto_temporal(ctx.proyecto, escena, t_video, t_escena)
    ficha["paso"] = paso
    ficha["unidad"] = f"escena:{ficha['escena']}" if ficha.get("escena") else None
    ficha["escenas"] = [{"id": sid, **tramo} for sid, tramo in
                        sorted(p7.tiempos_de_escena(ctx.proyecto).items(),
                               key=lambda kv: kv[1]["t_in"])]

    if paso == "render":
        reproductor = PASOS_MODULOS.p8_render.reproductor(ctx.proyecto)
        ficha["mp4"] = url_de(ctx.id, reproductor["mp4"], ctx.proyecto.raiz)
        ficha["clip"] = url_de(ctx.id, reproductor["clips"].get(ficha.get("escena")),
                               ctx.proyecto.raiz)
        ficha["fps"] = reproductor["fps"]
        ficha["resolucion"] = reproductor["resolucion"]
        ficha["duracion_video"] = reproductor["duracion"]
        return ficha

    mov = p7.movimientos_de(ctx.proyecto).get(ficha.get("escena"))
    if not mov:
        raise ErrorApi(409, f"callouts todavia no ha producido el plano "
                            f"{ficha.get('escena')}: no hay fotograma que componer")
    base = os.path.dirname(p7.ruta_movimiento(ctx.proyecto))
    hyper = os.path.join(base, mov.get("hyperframe") or "")
    capa = os.path.join(base, mov.get("capa") or "")
    tamano = mov.get("hyperframe_px") or [3072, 2048]
    resolucion = PASOS_MODULOS.p8_render.PARAMS_POR_DEFECTO["resolucion"]
    aspecto = float(resolucion[0]) / float(resolucion[1])
    fraccion = ficha.get("fraccion") or 0.0
    ficha.update({
        "hyperframe": url_de(ctx.id, hyper, ctx.proyecto.raiz),
        "hyperframe_px": tamano,
        "capa": url_de(ctx.id, capa, ctx.proyecto.raiz),
        "resolucion": list(resolucion),
        "ventana": [round(v, 3) for v in
                    p7.ventana_en(mov, fraccion, tamano, aspecto)],
        "ventana_ini": mov.get("ventana_ini"),
        "ventana_fin": mov.get("ventana_fin"),
    })
    return ficha


@app.delete("/api/proyectos/{pid}/capturas/{cid}")
def borrar_captura(pid: str, cid: str):
    """Borra una captura y su PNG."""
    ctx = contexto(pid)
    borrada = almacen(ctx).borrar(cid)
    if borrada is None:
        raise ErrorApi(404, f"captura desconocida: {cid}")
    ctx.bitacora.anotar("captura_borrada", borrada.get("paso"),
                        {"captura": cid}, unidad=borrada.get("unidad"))
    return {"borrada": cid, "captura": borrada}


def _correr_capturas_agente(avisar, ctx, grupos, paso_id, unidades, ajuste=None):
    """Deja que el CLI decida que cambiar y despues rehace las unidades.

    El camino directo solo recoloca con lo que dicen los trazos; este sirve
    cuando el problema no es donde cae un rotulo sino como esta planteado el
    plano, que es algo que hay que mirar y decidir.

    El modelo y el esfuerzo llegan por invocacion y NO son params del paso: son
    la forma de resolver ESTA peticion, no una propiedad del plano. Guardarlos en
    los params cambiaria la firma del paso y dejaria obsoleto todo lo que cuelga
    de el cada vez que alguien mueve un desplegable.
    """
    ajuste = ajuste or {}
    recomendado = CLI_CLAUDE.por_defecto_de("capturas_agente")
    modelo = ajuste.get("modelo") or recomendado["modelo"]
    esfuerzo = ajuste.get("esfuerzo") or recomendado["esfuerzo"]
    instruccion = INSTRUCCION_CAPTURAS.format(
        proyecto=ctx.proyecto.raiz,
        paso=paso_id,
        unidades=", ".join(unidades or []),
        detalle="\n\n".join(g["instruccion"] for g in grupos))

    prevision = ESTADISTICAS.estimar(
        "capturas_agente", tamano=len(unidades or []),
        ajuste={"modelo": modelo, "esfuerzo": esfuerzo})
    avance = ESTADISTICAS.Avance(avisar, 0.05, 0.33, prevision,
                                 f"el agente esta mirando las capturas con "
                                 f"{modelo} (esfuerzo {esfuerzo})")
    avance.arrancar()
    arranque = time.time()
    try:
        # Aqui el agente SI usa herramientas: tiene que mirar los PNG y editar el
        # proyecto. Por eso no se le vetan, a diferencia del guion.
        texto, sobre = CLI_CLAUDE.ejecutar(
            instruccion, modelo=modelo, esfuerzo=esfuerzo,
            cwd=ctx.proyecto.raiz, tiempo_max_s=int(ajuste.get("tiempo_max_s") or 0),
            base_tiempo_s=1800, herramientas_vetadas=None,
            permisos="acceptEdits", avance=avance,
            para="el agente de capturas")
    except BaseException:
        avance.parar()
        ESTADISTICAS.anotar("capturas_agente", time.time() - arranque, ok=False,
                            ajuste={"modelo": modelo, "esfuerzo": esfuerzo},
                            proyecto=ctx.id, resultado="error")
        raise
    segundos = avance.parar()
    ESTADISTICAS.anotar("capturas_agente", segundos,
                        tamano=len(unidades or []),
                        ajuste={"modelo": modelo, "esfuerzo": esfuerzo},
                        proyecto=ctx.id, unidades=len(unidades or []),
                        detalle={"modelo": modelo, "esfuerzo": esfuerzo,
                                 "paso": paso_id,
                                 "tokens_salida": comun_tokens(sobre).get("salida")})
    with COSTE.contexto(ctx.proyecto, paso_id):
        COSTE.reportar_claude(sobre, operacion="capturas")
    ctx.bitacora.anotar("capturas_agente", paso_id,
                        {"resumen": str(texto or "")[:1200],
                         "modelo": modelo, "esfuerzo": esfuerzo,
                         "segundos": round(segundos, 1)})
    avisar(0.35, "rehaciendo lo que el agente ha tocado")
    resultado = _correr_paso(avisar, ctx, paso_id, unidades)
    resultado["agente"] = str(texto or "")[:2000]
    resultado["ajuste_cli"] = {"modelo": modelo, "esfuerzo": esfuerzo,
                               "segundos": round(segundos, 1)}
    return resultado


INSTRUCCION_CAPTURAS = """\
Eres el asistente de produccion de un video del Estudio.

El revisor ha marcado un problema sobre el reproductor del paso {paso} y ha
dejado estas capturas anotadas (las imagenes estan en capturas/ dentro del
proyecto, y los PNG se pueden mirar):

{detalle}

Trabajas en {proyecto}. Las unidades afectadas son: {unidades}.

Mira las capturas, decide que hay que cambiar de verdad (el texto del rotulo, su
colocacion, el movimiento de camara, el plano) y aplicalo donde corresponda
dentro del proyecto. NO toques otras escenas. En cuanto termines, el estudio
rehara por su cuenta esas unidades, asi que no lances renders tu.

Acaba con un resumen de una linea de lo que has cambiado.
"""


def _ajuste_cli(datos, defecto_modelo=None, defecto_esfuerzo=None):
    """Modelo y esfuerzo de una peticion, validados.

    Se valida aqui, al entrar, y no cuando ya se ha lanzado el CLI: un modelo mal
    escrito solo se detecta por returncode != 0, o sea despues de haber pagado el
    arranque y la espera entera.
    """
    datos = datos if isinstance(datos, dict) else {}
    crudo = datos.get("ajuste") if isinstance(datos.get("ajuste"), dict) else datos
    try:
        modelo = CLI_CLAUDE.normalizar_modelo(
            crudo.get("modelo"), defecto=defecto_modelo or CLI_CLAUDE.MODELO_POR_DEFECTO)
        esfuerzo = CLI_CLAUDE.normalizar_esfuerzo(
            crudo.get("esfuerzo"),
            defecto=defecto_esfuerzo or CLI_CLAUDE.ESFUERZO_POR_DEFECTO)
    except ValueError as fallo:
        raise ErrorApi(400, str(fallo))
    ajuste = {"modelo": modelo, "esfuerzo": esfuerzo}
    if crudo.get("tiempo_max_s"):
        try:
            ajuste["tiempo_max_s"] = int(crudo["tiempo_max_s"])
        except (TypeError, ValueError):
            raise ErrorApi(400, "tiempo_max_s tiene que ser un numero entero")
    return ajuste


def _lanzar_capturas(ctx, paso_id, unidades, grupos, modo, ajuste=None):
    """Comprueba y lanza la regeneracion que piden las capturas aplicadas."""
    if ctx.estado.estado_de(paso_id) == "bloqueado":
        faltan = [d for d in PASOS_POR_ID[paso_id]["depende_de"]
                  if ctx.proyecto.version_activa(d) is None]
        raise ErrorApi(409, f"'{paso_id}' esta bloqueado: falta ejecutar "
                            + ", ".join(faltan), {"faltan": faltan})
    if modo != "agente":
        return lanzar_paso(ctx, paso_id, unidades, nombre=f"capturas:{paso_id}",
                           evento="capturas_aplicadas",
                           datos={"modo": modo,
                                  "capturas": [c for g in grupos
                                               for c in g["capturas"]]})
    activo = _trabajo_activo(ctx, paso_id)
    if activo is not None:
        raise ErrorApi(409, f"'{paso_id}' ya se esta ejecutando",
                       {"trabajo_id": activo["id"], "progreso": activo["progreso"]})
    modulo_de(paso_id)
    trabajo_id = ctx.gestor.lanzar(f"capturas:{paso_id}", _correr_capturas_agente,
                                   ctx, grupos, paso_id, unidades, ajuste,
                                   paso=paso_id)
    _registrar_trabajo(trabajo_id, ctx.id)
    ctx.bitacora.anotar("capturas_aplicadas", paso_id,
                        {"modo": modo, "trabajo": trabajo_id,
                         "unidades": unidades or "todas",
                         "ajuste": ajuste,
                         "capturas": [c for g in grupos for c in g["capturas"]]})
    return trabajo_id


@app.post("/api/proyectos/{pid}/capturas/aplicar", status_code=202)
def aplicar_capturas(pid: str, cuerpo: dict = Body(default=None)):
    """Traduce las capturas a instruccion y rehace SOLO las escenas tocadas.

    Varias capturas de la misma escena se juntan en una sola instruccion
    ordenada por instante. Si hay capturas de callouts y de render a la vez se
    lanza la de mas arriba del grafo: rehacer la capa ya deja obsoleta esa misma
    escena en el render, y lanzar los dos a la vez seria pisarse.
    """
    ctx = contexto(pid)
    datos = _cuerpo(cuerpo)
    modo = str(datos.get("modo") or "directo").strip().lower()
    if modo not in ("directo", "agente"):
        raise ErrorApi(400, f"modo desconocido: {modo!r}. Usa 'directo' o 'agente'")
    # Se valida siempre, aunque el modo sea 'directo': si alguien manda un ajuste
    # imposible conviene que lo sepa ahora y no la proxima vez que use el agente.
    ajuste = _ajuste_cli(datos)
    guardadas = almacen(ctx)
    pedidas = datos.get("capturas")
    if isinstance(pedidas, str):
        pedidas = [pedidas]
    if pedidas:
        fichas = guardadas.obtener_varias(pedidas)
    else:
        fichas = guardadas.listar(pendientes=True)
    if not fichas:
        raise ErrorApi(409, "no hay capturas pendientes que aplicar")

    p7 = _p7()
    zonas = {}
    for ficha in fichas:
        if ficha.get("paso") == "callouts":
            zonas[ficha["id"]] = p7.zonas_de_captura(ctx.proyecto, ficha)

    grupos = CAPTURAS.aplicar(ctx.estado, fichas, zonas=zonas, modo=modo)
    for grupo in grupos:
        ctx.bitacora.anotar("captura_aplicada", grupo["paso"], {
            "capturas": grupo["capturas"],
            "imagenes": grupo["nota"]["imagenes"],
            "instruccion": grupo["instruccion"],
            "zonas_evitadas": len(grupo["zonas"]),
            "modo": modo}, unidad=grupo["unidad"])

    por_paso = {}
    for grupo in grupos:
        por_paso.setdefault(grupo["paso"], []).append(grupo["unidad"])
    orden = [p["id"] for p in PASOS if p["id"] in por_paso]
    primero = orden[0]
    trabajo_id = _lanzar_capturas(ctx, primero, sorted(set(por_paso[primero])),
                                  [g for g in grupos if g["paso"] == primero], modo,
                                  ajuste=ajuste)
    guardadas.marcar_aplicadas([c for g in grupos for c in g["capturas"]],
                               trabajo=trabajo_id)
    return {
        "trabajo_id": trabajo_id,
        "paso": primero,
        "modo": modo,
        "ajuste": ajuste if modo == "agente" else None,
        "unidades": sorted(set(por_paso[primero])),
        "grupos": grupos,
        "aplazados": {paso: sorted(set(uds)) for paso, uds in por_paso.items()
                      if paso != primero},
        "aguas_abajo": {hijo: ctx.estado.unidades_obsoletas(hijo)
                        for hijo in descendientes_de(primero)},
        "trabajo": ctx.gestor.estado(trabajo_id),
        "eventos": f"/api/trabajos/{trabajo_id}/eventos",
    }


# ---------------------------------------------------------------------- web
# La interfaz se sirve desde el MISMO origen que la API: app.js pide rutas
# absolutas (/api/..., /a/...) y desde file:// o desde otro puerto no habria
# forma de hablar con el servicio sin CORS. Estas dos rutas van las ultimas
# para no tapar ninguna de las de arriba.

@app.get("/")
def portada(peticion: Request):
    """La interfaz del Estudio."""
    return fichero_web("index.html", peticion)


#: Rutas que NO son ficheros: son el MODO con el que abrir la interfaz.
#:
#: `/light` y `/editor` sirven la misma pagina que `/`, y quien lee el modo es
#: el navegador (`modoDeLaUrl` en app.js), que ademas lo recuerda. Existen para
#: poder guardar un enlace directo --y para que el panel de control pueda abrir
#: el Estudio ya en el modo que toca-- sin tener que entrar y cambiarlo a mano.
#:
#: Van aqui y no en el fichero de Caddy porque son de esta aplicacion: el proxy
#: solo tiene que seguir mandando /estudio/* a este puerto, que es lo que ya
#: hace. Una regla por modo en el proxy seria repartir la misma decision entre
#: dos sitios que no se hablan.
#: Hubo dos modos y la ruta llevaba cual --/estudio/light, /estudio/editor--.
#: Ahora hay uno, asi que no hay nada que llevar; se siguen ACEPTANDO esos dos
#: nombres para que un enlace guardado no de 404 y abra la pantalla de siempre.
MODOS_EN_LA_URL = ("light", "editor")

#: Los assets del front que se sellan en la portada. Son los dos unicos ficheros
#: que index.html enlaza.
ASSETS_SELLADOS = ("estilo.css", "app.js")


def _sello_asset(nombre):
    """Sello corto del asset: cambia cuando cambia el fichero, y solo entonces."""
    marca = _sello_fichero(os.path.join(RAIZ_WEB, nombre))
    return _huella_corta(marca) if marca else "0"


def _huella_corta(valor):
    return hashlib.sha256(repr(valor).encode("utf-8")).hexdigest()[:10]


def _portada_sellada():
    """index.html con `?v=<sello>` en los dos assets que enlaza.

    El sello sale del propio fichero (mtime + tamano), asi que cambia SOLO
    cuando el asset cambia. Eso es lo que permite servir app.js y estilo.css con
    cache de un ano: la URL nueva es un recurso nuevo, y la vieja ya no la pide
    nadie. Sin sello no se puede cachear fuerte -- congelaria a los usuarios en
    un front viejo sin forma de invalidarlo desde el servidor --, y por eso hasta
    ahora los 957 KB de app.js se revalidaban en CADA carga de la pagina.

    La portada en si NO se cachea: es la que trae los sellos nuevos.
    """
    with open(os.path.join(RAIZ_WEB, "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    for nombre in ASSETS_SELLADOS:
        sello = _sello_asset(nombre)
        # solo la referencia literal del enlace, y una vez: asi no se toca
        # ninguna otra aparicion del nombre dentro del documento
        html = html.replace(f'"{nombre}"', f'"{nombre}?v={sello}"', 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/{fichero}")
def fichero_web(fichero: str, peticion: Request):
    """Sirve un fichero suelto de web/ (app.js, estilo.css...)."""
    nombre = str(fichero or "")
    if nombre in MODOS_EN_LA_URL:
        nombre = "index.html"
    # web/ es plano: aceptar solo un nombre de fichero deja fuera cualquier
    # forma de subir de carpeta antes incluso de tocar el disco
    if not FICHERO_WEB.match(nombre) or nombre in (".", ".."):
        raise ErrorApi(404, f"no existe: {fichero}")
    destino = os.path.join(RAIZ_WEB, nombre)
    if not os.path.isfile(destino):
        raise ErrorApi(404, f"no existe: {fichero}")
    if nombre == "index.html":
        return _portada_sellada()
    # UN ASSET PEDIDO CON SU SELLO ES INMUTABLE. La portada solo pone el `?v=`
    # que corresponde al fichero que hay ahora, asi que si el navegador pide ESE
    # sello, lo que reciba no va a cambiar nunca: se puede guardar un ano y no
    # volver a preguntar. Sin esto, app.js (957 KB) se revalidaba en cada carga
    # -- un viaje de ida y vuelta entero, y con ~235 ms de latencia se nota.
    #
    # Se comprueba que el sello COINCIDA con el del fichero: un `?v=` viejo (una
    # pestana que lleva dias abierta, un enlace guardado) no puede llevarse la
    # cabecera de inmutable, o se quedaria con esa respuesta para siempre.
    if nombre in ASSETS_SELLADOS:
        pedido = peticion.query_params.get("v")
        if pedido and pedido == _sello_asset(nombre):
            return FileResponse(destino, media_type=_tipo_de(destino), headers={
                "Cache-Control": "public, max-age=31536000, immutable",
            })
    return servir_fichero(peticion, destino)


# ------------------------------------------------------------------------ main

def main():
    parser = argparse.ArgumentParser(description="Servicio HTTP del Estudio de Video")
    parser.add_argument("--puerto", type=int, default=8020)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--proyectos", default=None,
                        help="carpeta base de proyectos "
                             f"(por defecto {RAIZ_POR_DEFECTO})")
    argumentos = parser.parse_args()
    fijar_raiz_proyectos(argumentos.proyectos or raiz_proyectos())
    # Donde escucha esta API, para las herramientas del asistente
    # (pasos/mcp_estudio.py): el CLI arranca ese servidor como proceso hijo y
    # el hijo vuelve a hablar con este mismo proceso por HTTP.
    os.environ.setdefault("ESTUDIO_API", f"http://127.0.0.1:{argumentos.puerto}")

    import uvicorn
    print(f"Estudio de Video en http://{argumentos.host}:{argumentos.puerto}")
    print(f"proyectos en {raiz_proyectos()}")
    if ERROR_PASOS:
        print(f"AVISO: los pasos no se han cargado -> {ERROR_PASOS}")
    try:
        uvicorn.run(app, host=argumentos.host, port=argumentos.puerto,
                    log_level="warning")
    finally:
        # un `claude auth login` a medias deja un node esperando un codigo por
        # una tuberia que ya no tiene quien escriba
        if PASOS_MODULOS is not None:
            PASOS_MODULOS.login_cli.olvidar_todos()
            # y una charla a medias deja otro node contestando a nadie
            PASOS_MODULOS.asistente.olvidar_todas()


if __name__ == "__main__":
    main()
