"""Probar cada clave CONTRA SU SERVICIO, con la llamada mas barata que lo diga.

«Puesta» no es «funciona». Una clave de OpenAI copiada a medias, una de
Cartesia de una cuenta borrada o un Client ID de Jamendo caducado se ven igual
en el almacen: una cola de cuatro caracteres y la palabra «puesta». Y se
descubren a mitad de una tanda de imagenes, que es la forma cara.

Aqui cada proveedor tiene su prueba, elegida para que NO cueste dinero:

    openai     GET /v1/models              autentica; no genera nada
    cartesia   GET /voices                 lista voces; no sintetiza nada
    jamendo    GET /tracks/?limit=1        una busqueda; el plan es gratuito
    freesound  GET /search/text/?page_size=1   idem
    claude     salud_cli.probar por cuenta  (haiku, una palabra: es lo minimo)

LO QUE NO PUEDE DECIR, y se dice tal cual: que OpenAI tenga SALDO. La unica
forma de saberlo es generar una imagen, y eso se paga. Si la clave autentica,
la respuesta lo dice y avisa de que el saldo se ve en Billing.

Lo usa `POST /api/claves/probar` (el boton «Probar todas» de Configuracion y
de la guia) y la herramienta `probar_claves` del asistente. Cada proveedor va
protegido por su cuenta: que Cartesia no conteste no impide probar las demas.
"""
import os
import re

try:
    from . import claves, salud_cli
except ImportError:  # ejecutado con la carpeta pasos en sys.path
    import claves
    import salud_cli

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Cuanto se espera a cada servicio. Son llamadas de lectura: si tardan mas es
#: que no van, y eso tambien es una respuesta.
TIEMPO_S = 25

#: Con que version de la API habla el motor de voz. Se lee del propio motor
#: para no tener dos sitios que decidan lo mismo; si no se encuentra, la que
#: tenia el motor cuando se escribio esto.
_VERSION_CARTESIA_POR_DEFECTO = "2024-06-10"


def _requests():
    import requests                                   # noqa: PLC0415
    return requests


def version_cartesia():
    ruta = os.path.join(os.environ.get("ESTUDIO_MOTORES") or
                        os.path.join(RAIZ_ESTUDIO, "motores"),
                        "voz_cartesia", "voz.py")
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            m = re.search(r'API_VERSION\s*=\s*"([^"]+)"', fh.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    return _VERSION_CARTESIA_POR_DEFECTO


def _ficha(proveedor, estado, mensaje, **extra):
    """estado: ok | mal | sin_clave | sin_red"""
    ficha = {"proveedor": proveedor, "estado": estado, "mensaje": mensaje}
    ficha.update(extra)
    return ficha


def _pedir(metodo, url, **kw):
    """Una peticion con el tiempo puesto; los fallos de red salen como (None, texto)."""
    requests = _requests()
    try:
        return requests.request(metodo, url, timeout=TIEMPO_S, **kw), ""
    except requests.RequestException as fallo:          # noqa: BLE001
        return None, f"{type(fallo).__name__}: {fallo}"


def _texto_corto(respuesta):
    try:
        datos = respuesta.json()
        if isinstance(datos, dict):
            error = datos.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])[:300]
            if isinstance(error, str):
                return error[:300]
            if datos.get("detail"):
                return str(datos["detail"])[:300]
            if datos.get("message"):
                return str(datos["message"])[:300]
    except ValueError:
        pass
    return (respuesta.text or "").strip()[:300]


# ------------------------------------------------------------------ proveedores

def probar_openai(clave):
    if not clave:
        return _ficha("openai", "sin_clave", "no hay clave de OpenAI puesta")
    respuesta, fallo = _pedir("GET", "https://api.openai.com/v1/models",
                              headers={"Authorization": f"Bearer {clave}"})
    if respuesta is None:
        return _ficha("openai", "sin_red", f"no se ha podido hablar con OpenAI: {fallo}")
    if respuesta.status_code == 200:
        return _ficha("openai", "ok",
                      "la clave autentica. Lo que NO se puede saber sin pagar una "
                      "imagen es si la cuenta tiene saldo: se mira en "
                      "platform.openai.com → Billing")
    if respuesta.status_code == 401:
        return _ficha("openai", "mal", "OpenAI no reconoce la clave (401): esta mal "
                                       "copiada, revocada o es de otra cuenta")
    if respuesta.status_code == 429:
        return _ficha("openai", "mal", f"OpenAI contesta 429 (limite o sin saldo): "
                                       f"{_texto_corto(respuesta)}")
    return _ficha("openai", "mal", f"OpenAI contesta {respuesta.status_code}: "
                                   f"{_texto_corto(respuesta)}")


def probar_cartesia(clave):
    if not clave:
        return _ficha("cartesia", "sin_clave", "no hay clave de Cartesia puesta")
    respuesta, fallo = _pedir("GET", "https://api.cartesia.ai/voices?limit=1",
                              headers={"X-API-Key": clave,
                                       "Cartesia-Version": version_cartesia()})
    if respuesta is None:
        return _ficha("cartesia", "sin_red", f"no se ha podido hablar con Cartesia: {fallo}")
    if respuesta.status_code == 200:
        return _ficha("cartesia", "ok", "la clave autentica y el catalogo de voces contesta")
    if respuesta.status_code in (401, 403):
        return _ficha("cartesia", "mal", f"Cartesia no reconoce la clave "
                                         f"({respuesta.status_code}): {_texto_corto(respuesta)}")
    return _ficha("cartesia", "mal", f"Cartesia contesta {respuesta.status_code}: "
                                     f"{_texto_corto(respuesta)}")


def probar_jamendo(clave):
    if not clave:
        return _ficha("jamendo", "sin_clave", "no hay Client ID de Jamendo; el video "
                                              "se monta sin musica")
    respuesta, fallo = _pedir("GET", "https://api.jamendo.com/v3.0/tracks/",
                              params={"client_id": clave, "format": "json", "limit": 1})
    if respuesta is None:
        return _ficha("jamendo", "sin_red", f"no se ha podido hablar con Jamendo: {fallo}")
    try:
        cabecera = (respuesta.json() or {}).get("headers") or {}
    except ValueError:
        cabecera = {}
    if respuesta.status_code == 200 and cabecera.get("status") == "success":
        return _ficha("jamendo", "ok", "el Client ID vale: Jamendo devuelve pistas")
    motivo = cabecera.get("error_message") or _texto_corto(respuesta)
    return _ficha("jamendo", "mal", f"Jamendo no acepta el Client ID "
                                    f"({respuesta.status_code}): {motivo}")


def probar_freesound(clave):
    if not clave:
        return _ficha("freesound", "sin_clave", "no hay clave de FreeSound; el video "
                                                "se monta sin efectos")
    respuesta, fallo = _pedir("GET", "https://freesound.org/apiv2/search/text/",
                              params={"query": "rain", "page_size": 1, "fields": "id"},
                              headers={"Authorization": f"Token {clave}"})
    if respuesta is None:
        return _ficha("freesound", "sin_red", f"no se ha podido hablar con FreeSound: {fallo}")
    if respuesta.status_code == 200:
        return _ficha("freesound", "ok", "la clave vale: FreeSound devuelve sonidos")
    if respuesta.status_code == 401:
        return _ficha("freesound", "mal", "FreeSound no reconoce la clave (401). Tiene "
                                          "que ser la columna «Client secret/Api key», "
                                          "no el Client id")
    return _ficha("freesound", "mal", f"FreeSound contesta {respuesta.status_code}: "
                                      f"{_texto_corto(respuesta)}")


def probar_claude(cuentas):
    """Una ficha por cuenta del CLI con sesion, con lo que apunta salud_cli."""
    fichas = []
    for cuenta in cuentas:
        etiqueta = cuenta.get("etiqueta") or cuenta.get("correo") or cuenta.get("id") or "la cuenta"
        salud = salud_cli.probar(cuenta, para="probar todas las claves")
        estado = "ok" if salud["estado"] == "ok" else "mal"
        fichas.append(_ficha("claude", estado, salud_cli.describir(salud, etiqueta),
                             cuenta=cuenta.get("id") or "", salud=salud))
    if not fichas:
        fichas.append(_ficha("claude", "sin_clave", "no hay ninguna cuenta de Claude con sesion"))
    return fichas


# ------------------------------------------------------------------ todo junto

def probar_todas(cuentas_claude=(), con_claude=True):
    """Todas las claves del almacen, cada una contra su servicio. -> [fichas]

    `cuentas_claude` son las fichas del CLI que hay que probar (las decide
    quien llama, que es quien sabe cuales tienen sesion). En modo simulado no
    se sale a ningun sitio: cada clave puesta se da por buena.
    """
    almacen = claves.leer()
    fichas = []
    if salud_cli.simulado():
        for proveedor, puesta in (("openai", bool(almacen["openai"])),
                                  ("cartesia", bool(almacen["cartesia"]["clave"])),
                                  ("jamendo", bool(almacen["jamendo"]["clave"])),
                                  ("freesound", bool(almacen["freesound"]["clave"]))):
            fichas.append(_ficha(proveedor, "ok" if puesta else "sin_clave",
                                 "simulado" if puesta else "sin poner"))
        if con_claude:
            fichas.extend(probar_claude(cuentas_claude))
        return fichas
    pruebas = (
        (probar_openai, (almacen["openai"][0]["clave"] if almacen["openai"] else "")),
        (probar_cartesia, almacen["cartesia"]["clave"]),
        (probar_jamendo, almacen["jamendo"]["clave"]),
        (probar_freesound, almacen["freesound"]["clave"]),
    )
    for funcion, clave in pruebas:
        try:
            fichas.append(funcion(clave))
        except Exception as fallo:                     # noqa: BLE001
            nombre = funcion.__name__.replace("probar_", "")
            fichas.append(_ficha(nombre, "sin_red", f"la prueba ha fallado: "
                                                     f"{type(fallo).__name__}: {fallo}"))
    if con_claude:
        try:
            fichas.extend(probar_claude(cuentas_claude))
        except Exception as fallo:                     # noqa: BLE001
            fichas.append(_ficha("claude", "sin_red", f"la prueba ha fallado: "
                                                      f"{type(fallo).__name__}: {fallo}"))
    return fichas


NOMBRES = {"openai": "OpenAI (imágenes)", "cartesia": "Cartesia (voz)",
           "jamendo": "Jamendo (música)", "freesound": "FreeSound (efectos)",
           "claude": "Claude"}


def resumen_texto(fichas):
    """Las fichas en lineas legibles, para el asistente y para el log."""
    marcas = {"ok": "OK", "mal": "MAL", "sin_clave": "SIN PONER", "sin_red": "SIN RED"}
    lineas = []
    for ficha in fichas:
        lineas.append(f"{marcas.get(ficha['estado'], ficha['estado'])}  "
                      f"{NOMBRES.get(ficha['proveedor'], ficha['proveedor'])}: {ficha['mensaje']}")
    return "\n".join(lineas)
