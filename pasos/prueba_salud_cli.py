"""Prueba de la salud de las cuentas del CLI, de las pruebas de claves y de las
herramientas del asistente. Sin red y sin CLI: dobles en los tres sitios.

  - salud_cli: que apunte, clasifique y describa cada fallo, y que la clave
    de una cuenta sea su carpeta de sesion;
  - cli_claude._una_pasada: que TODA llamada apunte la salud de su cuenta, y
    que una cancelacion no apunte nada;
  - comprobar_claves: cada proveedor con su respuesta buena y su 401, sin
    salir a internet, y el modo simulado;
  - mcp_estudio: el protocolo (initialize, tools/list, tools/call) y que cada
    herramienta hable con la API por contrato.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe pasos\\prueba_salud_cli.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CARPETA = tempfile.mkdtemp(prefix="salud_prueba_")
os.environ["ESTUDIO_SECRETOS"] = os.path.join(CARPETA, "secretos")

import cli_claude  # noqa: E402
import comprobar_claves  # noqa: E402
import mcp_estudio  # noqa: E402
import salud_cli  # noqa: E402

FALLOS = []


def comprobar(condicion, texto):
    print(("  ok   " if condicion else "  FALLO ") + texto)
    if not condicion:
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado,
              texto if obtenido == esperado
              else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def seccion(titulo):
    print(f"\n[{titulo}]")


# ------------------------------------------------------------------ salud_cli

def prueba_salud():
    seccion("1] salud_cli: apuntar, clasificar, describir")
    comprobar(salud_cli.fichero().startswith(os.environ["ESTUDIO_SECRETOS"]),
              "el fichero va con los secretos, y mira el entorno al llamar")
    igual(salud_cli.leer(), {}, "sin fichero, nada apuntado")
    igual(salud_cli.clave_de({"config_dir": ""}), salud_cli.DEFECTO,
          "sin carpeta es la sesion por defecto")
    igual(salud_cli.clave_de({"config_dir": "C:/x/../x/cli1"}),
          salud_cli.clave_de("C:/x/cli1"), "la clave es la carpeta normalizada")

    ficha = salud_cli.anotar({"config_dir": "C:/x/cli1"}, "cupo",
                             "You've hit your weekly limit · resets Sep 14, 2am (UTC)", "guion")
    igual(ficha["estado"], "cupo", "se apunta el cupo")
    igual(salud_cli.de({"config_dir": "C:/x/cli1"})["mensaje"], ficha["mensaje"],
          "y se relee por la cuenta")
    comprobar(salud_cli.de({"config_dir": "C:/x/otra"}) is None,
              "otra cuenta no tiene nada")
    igual(salud_cli.renueva(ficha), "Sep 14, 2am (UTC)", "se saca cuando se renueva")
    comprobar("cupo agotado" in salud_cli.describir(ficha, "la mia")
              and "la mia" in salud_cli.describir(ficha, "la mia"),
              "y se describe con la etiqueta")
    salud_cli.anotar({"config_dir": "C:/x/cli1"}, "ok")
    igual(salud_cli.de({"config_dir": "C:/x/cli1"})["estado"], "ok",
          "una llamada buena limpia el cupo")
    comprobar(salud_cli.olvidar({"config_dir": "C:/x/cli1"})
              and not salud_cli.olvidar({"config_dir": "C:/x/cli1"}),
              "olvidar dice si habia algo")
    try:
        salud_cli.anotar({}, "raro")
        comprobar(False, "un estado desconocido tenia que fallar")
    except ValueError:
        comprobar(True, "un estado desconocido da ValueError")

    igual(salud_cli.clasificar(cli_claude.LimiteAgotado("se acabo"))[0], "cupo",
          "LimiteAgotado es cupo")
    igual(salud_cli.clasificar(cli_claude.TiempoAgotado("vencio"))[0], "tiempo",
          "TiempoAgotado es tiempo")
    igual(salud_cli.clasificar(RuntimeError("el CLI de claude fallo (codigo 1): "
                                            "Not logged in. Please run /login"))[0],
          "sesion", "«not logged in» es sesion")
    igual(salud_cli.clasificar(RuntimeError("OAuth token expired"))[0], "sesion",
          "un token caducado es sesion")
    igual(salud_cli.clasificar(RuntimeError("no se encuentra el CLI"))[0], "error",
          "y lo demas, error")

    os.environ["ESTUDIO_SIMULAR"] = "1"
    try:
        igual(salud_cli.probar({"config_dir": ""})["estado"], "ok",
              "en modo simulado probar no llama a nadie y da ok")
    finally:
        os.environ.pop("ESTUDIO_SIMULAR", None)


class ProcesoFalso:
    def __init__(self, sobre=None, codigo=0, al_comunicar=None):
        self.sobre = sobre
        self.codigo = codigo
        self.al_comunicar = al_comunicar
        self.pid = 4242
        self.stdin = None

    def communicate(self, entrada=None, timeout=None):
        if self.al_comunicar is not None:
            raise self.al_comunicar
        return json.dumps(self.sobre).encode("utf-8"), b""

    @property
    def returncode(self):
        return self.codigo

    def poll(self):
        return self.codigo

    def kill(self):
        pass


def prueba_una_pasada():
    seccion("2] toda llamada al CLI apunta la salud de su cuenta")
    cuenta = {"etiqueta": "la mia", "config_dir": os.path.join(CARPETA, "cli9")}
    original = subprocess.Popen
    original_localizar = cli_claude.localizar
    cli_claude.localizar = lambda *a, **k: "claude"
    try:
        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": "vale", "session_id": "s"})
        cli_claude._una_pasada("hola", "haiku", "low", None, 60, 60, None,
                               cli_claude.HERRAMIENTAS_VETADAS, None, None, None,
                               None, "probar", cuenta)
        igual(salud_cli.de(cuenta)["estado"], "ok", "una llamada buena apunta ok")

        subprocess.Popen = lambda *a, **k: ProcesoFalso(
            {"result": "You've hit your weekly limit · resets Sep 14", "is_error": True}, 1)
        try:
            cli_claude._una_pasada("hola", "haiku", "low", None, 60, 60, None,
                                   cli_claude.HERRAMIENTAS_VETADAS, None, None, None,
                                   None, "el guion", cuenta)
            comprobar(False, "tenia que lanzar LimiteAgotado")
        except cli_claude.LimiteAgotado:
            comprobar(True, "el cupo agotado sigue lanzando LimiteAgotado")
        ficha = salud_cli.de(cuenta)
        igual(ficha["estado"], "cupo", "y queda apuntado como cupo")
        comprobar("Sep 14" in ficha["mensaje"], "con la fecha de renovacion")
        igual(ficha["para"], "el guion", "y para que se le hablaba")

        class Avance:
            cancelado = True
            al_cancelar = None
        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": "vale"})
        try:
            cli_claude._una_pasada("hola", "haiku", "low", None, 60, 60, None,
                                   cli_claude.HERRAMIENTAS_VETADAS, None, None, Avance(),
                                   None, "algo", cuenta)
        except RuntimeError:
            pass
        igual(salud_cli.de(cuenta)["estado"], "cupo",
              "una cancelacion NO apunta nada: no dice nada de la cuenta")

        salud_cli.probar(cuenta)
        igual(salud_cli.de(cuenta)["estado"], "ok", "probar con el CLI contestando limpia el cupo")
    finally:
        subprocess.Popen = original
        cli_claude.localizar = original_localizar


# ------------------------------------------------------------------ claves

class RespuestaFalsa:
    def __init__(self, codigo, datos=None, texto=""):
        self.status_code = codigo
        self._datos = datos
        self.text = texto

    def json(self):
        if self._datos is None:
            raise ValueError("sin json")
        return self._datos


def prueba_claves():
    seccion("3] comprobar_claves: cada proveedor con su respuesta")
    peticiones = []

    def falso(metodo, url, **kw):
        peticiones.append((metodo, url, kw))
        if "openai" in url:
            return (RespuestaFalsa(200, {"data": []}) if kw["headers"]["Authorization"] == "Bearer buena"
                    else RespuestaFalsa(401, {"error": {"message": "Incorrect API key"}})), ""
        if "cartesia" in url:
            return (RespuestaFalsa(200, []) if kw["headers"]["X-API-Key"] == "buena"
                    else RespuestaFalsa(401, {"error": "invalid"})), ""
        if "jamendo" in url:
            return (RespuestaFalsa(200, {"headers": {"status": "success"}}) if kw["params"]["client_id"] == "buena"
                    else RespuestaFalsa(200, {"headers": {"status": "failed",
                                                          "error_message": "Your credential is not authorized."}})), ""
        if "freesound" in url:
            return (RespuestaFalsa(200, {"count": 1}) if kw["headers"]["Authorization"] == "Token buena"
                    else RespuestaFalsa(401, {"detail": "Invalid token."})), ""
        return None, "sin red"

    original = comprobar_claves._pedir
    comprobar_claves._pedir = falso
    try:
        igual(comprobar_claves.probar_openai("buena")["estado"], "ok", "OpenAI buena autentica")
        comprobar("saldo" in comprobar_claves.probar_openai("buena")["mensaje"],
                  "y avisa de que el saldo no se puede saber sin pagar")
        igual(comprobar_claves.probar_openai("mala")["estado"], "mal", "OpenAI mala da mal")
        comprobar("401" in comprobar_claves.probar_openai("mala")["mensaje"], "y dice el 401")
        igual(comprobar_claves.probar_openai("")["estado"], "sin_clave", "sin clave lo dice")
        igual(comprobar_claves.probar_cartesia("buena")["estado"], "ok", "Cartesia buena")
        igual(comprobar_claves.probar_cartesia("mala")["estado"], "mal", "Cartesia mala")
        comprobar(peticiones[-1][2]["headers"].get("Cartesia-Version"),
                  "y manda la version de la API que usa el motor")
        igual(comprobar_claves.probar_jamendo("buena")["estado"], "ok", "Jamendo bueno")
        ficha = comprobar_claves.probar_jamendo("mala")
        igual(ficha["estado"], "mal", "Jamendo malo aunque conteste 200")
        comprobar("not authorized" in ficha["mensaje"], "con el motivo de Jamendo")
        igual(comprobar_claves.probar_freesound("buena")["estado"], "ok", "FreeSound buena")
        ficha = comprobar_claves.probar_freesound("mala")
        igual(ficha["estado"], "mal", "FreeSound mala")
        comprobar("Client secret/Api key" in ficha["mensaje"],
                  "y recuerda que columna es: la duda de verdad")
    finally:
        comprobar_claves._pedir = original

    def sin_red(metodo, url, **kw):
        return None, "ConnectionError: sin red"
    comprobar_claves._pedir = sin_red
    try:
        igual(comprobar_claves.probar_openai("x")["estado"], "sin_red",
              "sin red no es una clave mala: es sin red")
    finally:
        comprobar_claves._pedir = original

    os.environ["ESTUDIO_SIMULAR"] = "1"
    try:
        fichas = comprobar_claves.probar_todas(cuentas_claude=[{"config_dir": "", "etiqueta": "x"}])
        igual([f["proveedor"] for f in fichas],
              ["openai", "cartesia", "jamendo", "freesound", "claude"],
              "probar_todas trae los cinco en orden")
        comprobar(all(f["estado"] in ("ok", "sin_clave") for f in fichas),
                  "y en simulado ninguna sale a la red")
        texto = comprobar_claves.resumen_texto(fichas)
        comprobar("OpenAI" in texto and "\n" in texto, "y hay un resumen legible")
    finally:
        os.environ.pop("ESTUDIO_SIMULAR", None)


# ------------------------------------------------------------------ mcp

def prueba_mcp():
    seccion("4] mcp_estudio: el protocolo y las herramientas")
    r = mcp_estudio.atender({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05"}})
    igual(r["result"]["serverInfo"]["name"], "estudio", "initialize se presenta como estudio")
    comprobar("tools" in r["result"]["capabilities"], "y anuncia herramientas")
    comprobar(mcp_estudio.atender({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None,
              "una notificacion no se contesta")
    lista = mcp_estudio.atender({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    nombres = [t["name"] for t in lista]
    comprobar("probar_claves" in nombres and "cancelar_trabajo" in nombres
              and "estado_estudio" in nombres, f"tools/list trae las herramientas: {nombres}")
    comprobar(all(t["inputSchema"]["type"] == "object" for t in lista),
              "cada una con su esquema")
    igual(mcp_estudio.nombres_permitidos()[0], "mcp__estudio__probar_claves",
          "y se autorizan como mcp__estudio__<nombre>")
    r = mcp_estudio.atender({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "no_existe", "arguments": {}}})
    comprobar("error" in r, "una herramienta desconocida es un error JSON-RPC")
    r = mcp_estudio.atender({"jsonrpc": "2.0", "id": 4, "method": "lo_que_sea"})
    igual(r["error"]["code"], -32601, "un metodo desconocido, tambien")

    llamadas = []

    def falso(metodo, ruta, datos=None, tiempo=60):
        llamadas.append((metodo, ruta, datos))
        if ruta.startswith("/api/claves/probar"):
            return 200, {"resumen": "OK  OpenAI: vale", "pruebas": []}
        if ruta.startswith("/api/asistente/foto"):
            return 200, {"foto": "fecha y hora: ahora"}
        if ruta.startswith("/api/trabajos?"):
            return 200, {"trabajos": [{"id": "t1", "nombre": "assets", "paso": "assets",
                                       "estado": "error", "progreso": 0.4, "segundos": 12,
                                       "error": "S03: la cara"}]}
        if ruta.startswith("/api/trabajos/t1/cancelar"):
            return 200, {"cancelacion_pedida": True, "estado": "ejecutando"}
        if ruta.endswith("/pasos/nada"):
            return 404, {"error": "paso desconocido: nada"}
        if "/bitacora" in ruta:
            return 200, {"eventos": [{"fecha": "hoy", "evento": "fallo", "paso": "assets",
                                      "datos": {"error": "x"}}]}
        if "/pasos/" in ruta:
            return 200, {"id": "assets", "estado": "obsoleto", "unidades": ["S01", "S02"],
                         "versiones": [{"n": 1, "fecha": "ayer", "activa": True}],
                         "params": {"calidad": "low"}}
        return 404, {"error": "no existe"}

    original = mcp_estudio._llamar
    mcp_estudio._llamar = falso
    try:
        def llamar(nombre, argumentos):
            r = mcp_estudio.atender({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                                     "params": {"name": nombre, "arguments": argumentos}})
            return r["result"]["content"][0]["text"], r["result"]["isError"]

        texto, mal = llamar("probar_claves", {})
        comprobar(texto == "OK  OpenAI: vale" and not mal, "probar_claves devuelve el resumen")
        igual(llamadas[-1][:2], ("POST", "/api/claves/probar"), "por POST /api/claves/probar")
        igual(llamadas[-1][2], {"claude": False}, "sin probar Claude salvo que se pida")
        texto, _ = llamar("estado_estudio", {"proyecto": "p1"})
        comprobar("ahora" in texto and "proyecto=p1" in llamadas[-1][1], "estado_estudio pide la foto del proyecto")
        texto, _ = llamar("trabajos", {"proyecto": "p1"})
        comprobar("S03: la cara" in texto and "error" in texto, "trabajos ensena el error")
        texto, _ = llamar("cancelar_trabajo", {"trabajo_id": "t1"})
        comprobar("pedida" in texto, "cancelar_trabajo pide la cancelacion")
        texto, _ = llamar("cancelar_trabajo", {})
        comprobar("hace falta" in texto, "y sin id lo dice")
        texto, _ = llamar("bitacora", {"proyecto": "p1", "limite": 5})
        comprobar("fallo [assets]" in texto, "bitacora lista los eventos")
        texto, _ = llamar("ficha_paso", {"proyecto": "p1", "paso": "assets"})
        comprobar('"unidades": 2' in texto and "obsoleto" in texto, "ficha_paso resume el paso")
        texto, mal = llamar("ficha_paso", {"proyecto": "p1", "paso": "nada"})
        comprobar("404" in texto, "un 404 de la API se cuenta tal cual")
    finally:
        mcp_estudio._llamar = original

    # y el proceso entero, por stdin/stdout
    proceso = subprocess.run(
        [sys.executable, mcp_estudio.__file__],
        input='{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
              '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n',
        capture_output=True, text=True, timeout=60, encoding="utf-8")
    lineas = [l for l in proceso.stdout.splitlines() if l.strip()]
    igual(len(lineas), 2, "el servidor contesta una linea por peticion")
    comprobar(json.loads(lineas[1])["result"]["tools"], "y la segunda es la lista")


def main():
    try:
        prueba_salud()
        prueba_una_pasada()
        prueba_claves()
        prueba_mcp()
    finally:
        shutil.rmtree(CARPETA, ignore_errors=True)
    print()
    if FALLOS:
        print(f"PRUEBA SALUD CLI CON FALLOS: {len(FALLOS)}")
        for fallo in FALLOS:
            print(f"  - {fallo}")
        return 1
    print("PRUEBA SALUD CLI OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
