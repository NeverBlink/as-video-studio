"""Como respondio cada cuenta del CLI de Claude la ultima vez que se le hablo.

POR QUE EXISTE
--------------
«Con sesion» no es «funciona». Una cuenta puede estar logueada y tener el cupo
semanal agotado hasta el jueves, o la sesion caducada, o el CLI colgandose; y
todo eso la pantalla lo pintaba en verde («con sesion», que es lo unico que
sabe decir `claude auth status`) hasta que alguien preguntaba algo y se comia
un error de seiscientos caracteres. Aqui se apunta LO ULTIMO QUE PASO con cada
cuenta, y la pantalla lo ensena al lado de la sesion: en la burbuja del
asistente, en Configuracion y en la guia de inicio.

DE DONDE SALE
-------------
De dos sitios:

  1. **De cada llamada de verdad.** `cli_claude._una_pasada` es el unico sitio
     por el que pasa toda llamada al CLI (el guion, el catalogo, los rotulos,
     el asistente...), y al volver anota aqui si fue bien o que fallo. Asi el
     cupo agotado a mitad de una tanda se ve en la burbuja al momento, sin que
     nadie haya preguntado nada.
  2. **De una prueba a proposito** (`probar`): una llamada minima --haiku,
     esfuerzo bajo, «contesta ok»-- que cuesta lo menos posible y falla rapido
     (medido: 2,8 s con el cupo agotado). Es lo que hay detras del boton
     «Probar» y lo que el asistente lanza solo al abrirse si no sabe nada de
     una cuenta.

LOS ESTADOS, que son los que pinta la pantalla:

    ok       contesto
    cupo     se acabo el cupo de la suscripcion (`LimiteAgotado`); el mensaje
             del CLI lleva la fecha en que se renueva
    sesion   el CLI dice que no hay sesion o que caduco: hay que volver a entrar
    tiempo   no contesto a tiempo (`TiempoAgotado`)
    error    cualquier otra cosa, con el texto tal cual

Se guarda en `<secretos>/salud_cli.json`, junto a las claves y fuera del repo,
y por cuenta se guarda la CARPETA de sesion (`config_dir`), que es lo que
identifica a una cuenta del CLI; la sesion por defecto es `__defecto__`. Un
fichero y no memoria porque el servicio se reinicia y un cupo agotado el
martes sigue agotado el miercoles.

LO QUE NO HACE: no decide por su cuenta que un cupo se ha renovado. Un estado
malo se queda hasta que una llamada --de verdad o de prueba-- vuelve a salir
bien. La fecha de renovacion viaja en el mensaje para que la persona sepa
cuando volver a probar.
"""
import json
import os
import re
import tempfile
import threading
import time

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fichero():
    """Donde se guarda. Se mira el entorno EN CADA LLAMADA y no al importar:
    las suites redirigen ESTUDIO_SECRETOS despues de importar los pasos, y un
    fichero fijado al importar escribiria la salud de sus dobles en el almacen
    de verdad."""
    carpeta = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(RAIZ_ESTUDIO, "secretos")
    return os.path.join(carpeta, "salud_cli.json")

ESTADOS = ("ok", "cupo", "sesion", "tiempo", "error")
DEFECTO = "__defecto__"

#: Como suena «no hay sesion» en lo que devuelve el CLI. Se casa por trozos y no
#: por frases enteras, por lo mismo que `cli_claude.limite_de`: el texto exacto
#: cambia con cada version del CLI.
_SESION = ("not logged in", "no est", "log in", "login", "authenticat", "oauth",
           "token expired", "expired", "credential", "unauthorized", "401",
           "sesion", "sesión", "caduc")

#: Lo que se le manda en la prueba. Corto a proposito: lo que se mide es si la
#: cuenta contesta, no que contesta.
INSTRUCCION_PRUEBA = "Contesta solo con la palabra: ok"
MODELO_PRUEBA = "haiku"
ESFUERZO_PRUEBA = "low"
TIEMPO_PRUEBA_S = 90

_LOCK = threading.RLock()


def simulado():
    return str(os.environ.get("ESTUDIO_SIMULAR", "")).strip().lower() in (
        "1", "true", "si")


def clave_de(cuenta):
    """Con que se identifica una cuenta aqui: su carpeta de sesion."""
    carpeta = ""
    if isinstance(cuenta, dict):
        carpeta = str(cuenta.get("config_dir") or "").strip()
    elif isinstance(cuenta, str):
        carpeta = cuenta.strip()
    return os.path.normcase(os.path.abspath(carpeta)) if carpeta else DEFECTO


# ------------------------------------------------------------------ fichero

def leer():
    """{clave: ficha}. Un fichero ilegible es un fichero vacio, no un error."""
    try:
        with open(fichero(), "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _escribir(datos):
    ruta = fichero()
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=os.path.dirname(ruta),
                prefix=".salud-", suffix=".tmp", delete=False) as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            temporal = fh.name
        os.replace(temporal, ruta)
        temporal = None
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def anotar(cuenta, estado, mensaje="", para=""):
    """Apunta como respondio esa cuenta. -> la ficha escrita"""
    if estado not in ESTADOS:
        raise ValueError(f"estado desconocido: {estado!r}")
    ficha = {
        "estado": estado,
        "mensaje": " ".join(str(mensaje or "").split())[:600],
        "para": str(para or "")[:120],
        "cuando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "epoch": int(time.time()),
    }
    with _LOCK:
        datos = leer()
        datos[clave_de(cuenta)] = ficha
        _escribir(datos)
    return dict(ficha)


def olvidar(cuenta):
    """Se borra lo apuntado de esa cuenta (al cerrar su sesion). -> bool"""
    with _LOCK:
        datos = leer()
        habia = datos.pop(clave_de(cuenta), None) is not None
        if habia:
            _escribir(datos)
    return habia


def de(cuenta):
    """La ficha de esa cuenta, o None si nunca se le ha hablado."""
    ficha = leer().get(clave_de(cuenta))
    return dict(ficha) if isinstance(ficha, dict) else None


# ------------------------------------------------------------------ clasificar

def clasificar(fallo):
    """(estado, mensaje) a partir de lo que lanzo el CLI.

    Se mira el TIPO primero (cupo y tiempo tienen clase propia en cli_claude) y
    el texto solo para distinguir «no hay sesion» de «otra cosa».
    """
    nombre = type(fallo).__name__
    texto = " ".join(str(fallo).split())
    if nombre == "LimiteAgotado":
        return "cupo", texto
    if nombre == "TiempoAgotado":
        return "tiempo", texto
    bajo = texto.lower()
    if any(pista in bajo for pista in _SESION):
        return "sesion", texto
    return "error", texto


def describir(ficha, etiqueta=""):
    """Una frase para la pantalla, o '' si no hay nada apuntado."""
    if not isinstance(ficha, dict):
        return ""
    quien = f"«{etiqueta}» " if etiqueta else ""
    estado = ficha.get("estado")
    mensaje = ficha.get("mensaje") or ""
    if estado == "ok":
        return f"la cuenta {quien}contesta (comprobado {ficha.get('cuando', '?')})"
    if estado == "cupo":
        return f"la cuenta {quien}tiene el cupo agotado: {mensaje}"
    if estado == "sesion":
        return f"la cuenta {quien}no tiene sesión válida: {mensaje}"
    if estado == "tiempo":
        return f"la cuenta {quien}no contestó a tiempo: {mensaje}"
    return f"la cuenta {quien}ha fallado: {mensaje}"


def renueva(ficha):
    """El trozo del mensaje que dice cuando se renueva el cupo, si lo dice."""
    if not isinstance(ficha, dict) or ficha.get("estado") != "cupo":
        return ""
    m = re.search(r"(resets?|renueva|se renueva|renovar[aá]?)\s*:?\s*(.+)$",
                  ficha.get("mensaje") or "", re.I)
    return m.group(2).strip() if m else ""


# ------------------------------------------------------------------ probar

def probar(cuenta, para="comprobar la cuenta"):
    """UNA llamada minima con esa cuenta, y se apunta lo que pase. -> ficha

    Va directa a `_una_pasada` y no a `ejecutar`: `ejecutar` recorre la cadena
    de cuentas y se pasaria a la siguiente, y lo que se quiere saber es como
    esta ESTA.
    """
    if simulado():
        return anotar(cuenta, "ok", "simulado", para)
    try:
        from . import cli_claude                        # noqa: PLC0415
    except ImportError:                                 # pasos/ suelto en sys.path
        import cli_claude                               # noqa: PLC0415
    try:
        cli_claude._una_pasada(
            INSTRUCCION_PRUEBA, MODELO_PRUEBA, ESFUERZO_PRUEBA, None,
            TIEMPO_PRUEBA_S, TIEMPO_PRUEBA_S, None, cli_claude.HERRAMIENTAS_VETADAS,
            None, None, None, None, para, cuenta)
    except Exception as fallo:                          # noqa: BLE001
        estado, mensaje = clasificar(fallo)
        return anotar(cuenta, estado, mensaje, para)
    return anotar(cuenta, "ok", "", para)


def describir_modulo():
    return f"salud de las cuentas del CLI en {fichero()}"
