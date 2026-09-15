"""Las herramientas del Estudio para el asistente: un servidor MCP minimo.

POR QUE EXISTE
--------------
El asistente contestaba «no puedo probar las claves: no tengo acceso a
internet ni ejecuto nada». Y era verdad: tenia Read, Grep y Glob y nada mas. Lo
que la persona espera de una burbuja de ayuda es lo contrario: que PRUEBE las
claves, que mire que trabajo esta parado y por que, que cancele el que se ha
quedado colgado -- desde la primera instalacion y sin que nadie tenga que
darle permisos.

Darle Bash o WebFetch para eso seria darle la puerta entera. Esto es la
alternativa: un puñado de herramientas escritas aqui, con nombre y con
contrato, que el CLI carga como servidor MCP (`--mcp-config`) y que van
PRE-AUTORIZADAS en la orden (`--allowedTools mcp__estudio__...`), de modo que
en headless no hay ninguna pregunta que nadie pueda contestar.

COMO FUNCIONA
-------------
Es un proceso aparte que arranca el propio CLI: JSON-RPC 2.0 por stdin/stdout,
un mensaje por linea (el transporte stdio de MCP). Se implementa a mano y no
con la biblioteca `mcp` porque son cinco metodos (`initialize`, `ping`,
`tools/list`, `tools/call` y la notificacion `initialized`) y una dependencia
mas es una cosa mas que puede faltar en un despliegue.

Cada herramienta llama a la API del Estudio en `ESTUDIO_API` (la pone
`app.py` al arrancar con su propio puerto): no importa codigo de la
aplicacion, habla con ella por contrato, igual que los motores. Asi lo que
hace la herramienta es EXACTAMENTE lo que haria la pantalla, y una ruta que
cambie rompe aqui igual que alli.

Se puede probar a mano:

    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python pasos/mcp_estudio.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = (os.environ.get("ESTUDIO_API") or "http://127.0.0.1:8020").rstrip("/")
PROYECTO_ABIERTO = os.environ.get("ESTUDIO_PROYECTO_ABIERTO") or ""

#: Tope de lo que se le devuelve al modelo por herramienta. Una bitacora entera
#: o una ficha con 300 unidades no ayudan: se recorta y se dice.
TOPE = 14000

PROTOCOLO = "2024-11-05"


# ------------------------------------------------------------------ HTTP

def _llamar(metodo, ruta, datos=None, tiempo=60):
    """Una peticion a la API del Estudio. -> (codigo, json|texto)"""
    url = API + ruta
    cuerpo = None
    cabeceras = {"Accept": "application/json"}
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo) as respuesta:
            crudo = respuesta.read().decode("utf-8", errors="replace")
            codigo = respuesta.status
    except urllib.error.HTTPError as fallo:
        crudo = fallo.read().decode("utf-8", errors="replace")
        codigo = fallo.code
    except (urllib.error.URLError, OSError) as fallo:
        return 0, f"no se ha podido hablar con el Estudio en {url}: {fallo}"
    try:
        return codigo, json.loads(crudo)
    except ValueError:
        return codigo, crudo


def _recortar(texto):
    texto = str(texto)
    if len(texto) <= TOPE:
        return texto
    return texto[:TOPE] + f"\n[... recortado: {len(texto) - TOPE} caracteres mas]"


def _error_de(codigo, datos):
    if isinstance(datos, dict) and datos.get("error"):
        return f"el Estudio contesta {codigo}: {datos['error']}"
    return f"el Estudio contesta {codigo}: {_recortar(datos)}"


def _pid(argumentos):
    return str(argumentos.get("proyecto") or PROYECTO_ABIERTO or "").strip()


# ------------------------------------------------------------------ herramientas

def probar_claves(argumentos):
    """Prueba cada clave contra su servicio: OpenAI, Cartesia, Jamendo, FreeSound."""
    con_claude = bool(argumentos.get("claude", False))
    codigo, datos = _llamar("POST", "/api/claves/probar", {"claude": con_claude},
                            tiempo=400 if con_claude else 120)
    if codigo != 200:
        return _error_de(codigo, datos)
    return datos.get("resumen") or json.dumps(datos, ensure_ascii=False, indent=1)


def probar_claude(argumentos):
    """Prueba las cuentas de Claude con una llamada minima y dice cual contesta."""
    codigo, datos = _llamar("POST", "/api/asistente/probar", {}, tiempo=400)
    if codigo != 200:
        return _error_de(codigo, datos)
    lineas = []
    for cuenta in datos.get("cuentas") or []:
        salud = cuenta.get("salud") or {}
        lineas.append(f"- {cuenta.get('etiqueta')}: "
                      + ("con sesion" if cuenta.get("sesion") else "sin sesion")
                      + (f"; {cuenta['motivo']}" if cuenta.get("motivo") else
                         f"; contesta (comprobado {salud.get('cuando', '?')})"))
    lineas.append("el asistente " + ("puede contestar" if datos.get("listo")
                                     else f"NO puede contestar: {datos.get('motivo')}"))
    return "\n".join(lineas)


def estado_estudio(argumentos):
    """La foto del estado del Estudio ahora mismo (claves, proyecto, pasos, trabajos)."""
    consulta = urllib.parse.urlencode({"proyecto": _pid(argumentos)})
    codigo, datos = _llamar("GET", f"/api/asistente/foto?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    return _recortar(datos.get("foto", ""))


def trabajos(argumentos):
    """Los trabajos de un proyecto (o de todos los abiertos), con su estado y su error."""
    pid = _pid(argumentos)
    consulta = urllib.parse.urlencode({"proyecto": pid, "activos": 0}) if pid else "activos=0"
    codigo, datos = _llamar("GET", f"/api/trabajos?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    lista = datos.get("trabajos") or []
    if not lista:
        return "no hay trabajos que el servicio recuerde" + (f" en {pid}" if pid else "")
    lineas = []
    for t in lista[:40]:
        lineas.append(
            f"- {t.get('id')}  {t.get('nombre')} [{t.get('paso')}] {t.get('estado')} "
            f"{round(100 * float(t.get('progreso') or 0))} % ({t.get('segundos')} s)"
            + (f"  proyecto={t.get('proyecto')}" if t.get("proyecto") else "")
            + (f"\n    mensaje: {t.get('mensaje')}" if t.get("mensaje") else "")
            + (f"\n    ERROR: {str(t.get('error'))[:900]}" if t.get("error") else ""))
    return _recortar("\n".join(lineas))


def ficha_paso(argumentos):
    """La ficha de un paso de un proyecto: estado, mensaje, params, unidades obsoletas."""
    pid = _pid(argumentos)
    paso = str(argumentos.get("paso") or "").strip()
    if not pid or not paso:
        return "hacen falta 'proyecto' y 'paso'"
    codigo, datos = _llamar("GET", f"/api/proyectos/{urllib.parse.quote(pid)}/pasos/"
                                   f"{urllib.parse.quote(paso)}")
    if codigo != 200:
        return _error_de(codigo, datos)
    ficha = {k: datos.get(k) for k in (
        "id", "nombre", "estado", "mensaje", "version", "num_versiones", "firma",
        "unidades_obsoletas", "unidades_sin_hacer", "conservado", "trabajo",
        "descripcion", "aviso", "motor", "params")}
    ficha["unidades"] = len(datos.get("unidades") or [])
    ficha["versiones"] = [{k: v.get(k) for k in ("n", "fecha", "activa", "unidades")}
                          for v in (datos.get("versiones") or [])[-8:]]
    return _recortar(json.dumps(ficha, ensure_ascii=False, indent=1, default=str))


def bitacora(argumentos):
    """Los ultimos eventos de la bitacora de un proyecto, opcionalmente de un paso."""
    pid = _pid(argumentos)
    if not pid:
        return "hace falta 'proyecto'"
    limite = int(argumentos.get("limite") or 60)
    paso = str(argumentos.get("paso") or "").strip()
    consulta = urllib.parse.urlencode({"paso": paso, "limite": limite} if paso
                                      else {"limite": limite})
    codigo, datos = _llamar("GET", f"/api/proyectos/{urllib.parse.quote(pid)}/bitacora?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    eventos = datos.get("eventos") if isinstance(datos, dict) else datos
    lineas = []
    for ev in (eventos or [])[-limite:]:
        d = ev.get("datos") if isinstance(ev.get("datos"), dict) else {}
        resumen = ", ".join(f"{k}={str(v)[:100]}" for k, v in sorted(d.items()))
        lineas.append(f"{ev.get('fecha', '?')}  {ev.get('evento', '?')}"
                      + (f" [{ev.get('paso')}]" if ev.get("paso") else "")
                      + (f" ({ev.get('unidad')})" if ev.get("unidad") else "")
                      + (f"  {resumen[:300]}" if resumen else ""))
    return _recortar("\n".join(lineas) or "sin eventos")


def cancelar_trabajo(argumentos):
    """Pide parar un trabajo por su id (cancelacion cooperativa)."""
    tid = str(argumentos.get("trabajo_id") or "").strip()
    if not tid:
        return "hace falta 'trabajo_id'"
    codigo, datos = _llamar("POST", f"/api/trabajos/{urllib.parse.quote(tid)}/cancelar", {})
    if codigo != 200:
        return _error_de(codigo, datos)
    return (f"cancelacion {'pedida' if datos.get('cancelacion_pedida') else 'NO necesaria'}; "
            f"estado del trabajo: {datos.get('estado')}")


def salud_servicio(argumentos):
    """Si el servicio esta bien: version, pasos cargados, trabajos activos, carpeta."""
    codigo, datos = _llamar("GET", "/api/salud")
    if codigo != 200:
        return _error_de(codigo, datos)
    return json.dumps(datos, ensure_ascii=False, indent=1)


HERRAMIENTAS = {
    "probar_claves": (probar_claves,
        "Prueba DE VERDAD cada clave contra su servicio (OpenAI, Cartesia, Jamendo, "
        "FreeSound) con una llamada que no cuesta dinero, y dice cual autentica y cual "
        "no. Con claude=true prueba tambien las cuentas de Claude (tarda mas). Usala "
        "cuando pregunten si las claves estan bien o si algo falla por una clave.",
        {"claude": {"type": "boolean", "description": "probar tambien las cuentas de Claude"}}),
    "probar_claude": (probar_claude,
        "Prueba las cuentas de Claude del CLI con una llamada minima y dice cual "
        "contesta, cual tiene el cupo agotado (y cuando se renueva) y cual no tiene sesion.",
        {}),
    "estado_estudio": (estado_estudio,
        "La foto del estado del Estudio ahora mismo: claves puestas, cuentas de Claude, "
        "proyectos, y del proyecto abierto sus ocho pasos, trabajos, bitacora y coste.",
        {"proyecto": {"type": "string", "description": "id del proyecto; por defecto el abierto"}}),
    "trabajos": (trabajos,
        "Lista los trabajos (generaciones) con estado, progreso, mensaje y error, para ver "
        "que esta corriendo, parado o fallado.",
        {"proyecto": {"type": "string", "description": "id del proyecto; vacio = todos los abiertos"}}),
    "ficha_paso": (ficha_paso,
        "La ficha de un paso (ingesta, brief, guion, voz, revision_audio, assets, callouts, "
        "render): estado, mensaje, version activa, params, unidades obsoletas y sin hacer.",
        {"proyecto": {"type": "string", "description": "id del proyecto"},
         "paso": {"type": "string", "description": "id del paso"}}),
    "bitacora": (bitacora,
        "Los ultimos eventos de la bitacora de un proyecto: que se genero, que fallo y "
        "con que motivo, en orden.",
        {"proyecto": {"type": "string", "description": "id del proyecto"},
         "paso": {"type": "string", "description": "solo los de este paso (opcional)"},
         "limite": {"type": "integer", "description": "cuantos eventos, por defecto 60"}}),
    "cancelar_trabajo": (cancelar_trabajo,
        "Pide parar un trabajo que se ha quedado colgado o que la persona quiere detener. "
        "Solo si la persona lo pide o esta claro que esta colgado.",
        {"trabajo_id": {"type": "string", "description": "id del trabajo"}}),
    "salud_servicio": (salud_servicio,
        "Si el servicio del Estudio esta bien: version, si los pasos cargaron, trabajos activos.",
        {}),
}


def lista_de_herramientas():
    salida = []
    for nombre, (_, descripcion, propiedades) in HERRAMIENTAS.items():
        salida.append({
            "name": nombre,
            "description": descripcion,
            "inputSchema": {"type": "object", "properties": propiedades,
                            "additionalProperties": False},
        })
    return salida


def nombres_permitidos(servidor="estudio"):
    """Como se autorizan en la orden del CLI: mcp__<servidor>__<herramienta>."""
    return tuple(f"mcp__{servidor}__{nombre}" for nombre in HERRAMIENTAS)


# ------------------------------------------------------------------ JSON-RPC

def atender(mensaje):
    """La respuesta a un mensaje, o None si es una notificacion."""
    metodo = mensaje.get("method")
    ident = mensaje.get("id")
    params = mensaje.get("params") or {}

    def ok(resultado):
        return {"jsonrpc": "2.0", "id": ident, "result": resultado}

    def mal(codigo, texto):
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": codigo, "message": texto}}

    if metodo == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOLO,
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "estudio", "version": "1.0"}})
    if metodo in ("notifications/initialized", "notifications/cancelled"):
        return None
    if metodo == "ping":
        return ok({})
    if metodo == "tools/list":
        return ok({"tools": lista_de_herramientas()})
    if metodo == "tools/call":
        nombre = params.get("name")
        argumentos = params.get("arguments") or {}
        entrada = HERRAMIENTAS.get(nombre)
        if entrada is None:
            return mal(-32602, f"herramienta desconocida: {nombre}")
        try:
            texto = entrada[0](argumentos if isinstance(argumentos, dict) else {})
            return ok({"content": [{"type": "text", "text": str(texto)}], "isError": False})
        except Exception as fallo:                     # noqa: BLE001
            return ok({"content": [{"type": "text",
                                    "text": f"la herramienta ha fallado: "
                                            f"{type(fallo).__name__}: {fallo}"}],
                       "isError": True})
    if ident is None:
        return None
    return mal(-32601, f"metodo desconocido: {metodo}")


def servir(entrada=None, salida=None):
    entrada = entrada or sys.stdin
    salida = salida or sys.stdout
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea)
        except ValueError:
            continue
        respuesta = atender(mensaje)
        if respuesta is not None:
            salida.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            salida.flush()


if __name__ == "__main__":
    servir()
