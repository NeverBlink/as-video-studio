"""
Prueba del selector de ajustes del CLI, del historico por combinacion y de las
los ajustes del CLI por fase.

No llama a ningun modelo: el CLI se sustituye por un doble, asi que es completa
y rapida. Lo que se comprueba es justo lo que se puede romper en silencio:

  - que un modelo o un esfuerzo invalidos se rechacen ANTES de pagar el arranque
  - que el plazo escale con el esfuerzo (un techo fijo garantiza TiempoAgotado)
  - que la estimacion distinga combinaciones y diga de donde sale cada cifra
  - que los fallos se anoten (si no, el recomendador nunca sabe que algo vence)
  - que una integracion no pueda prometer un clip que la pool no tiene

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_ajustes.py
"""
import json
import io
import os
import shutil
import subprocess
import sys
import tempfile

# La salud de las cuentas del CLI (pasos/salud_cli.py) se apunta en CADA
# llamada, tambien en las de los dobles de esta suite: sin redirigirla iria
# al almacen de claves de verdad.
os.environ.setdefault("ESTUDIO_SECRETOS", tempfile.mkdtemp(prefix="secretos_prueba_"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude
import estadisticas

FALLOS = []


def comprobar(condicion, texto):
    if condicion:
        print(f"  ok   {texto}")
    else:
        print(f"  FALLO {texto}")
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado,
              texto if obtenido == esperado
              else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def falla(funcion, trozo, texto):
    try:
        funcion()
    except (ValueError, RuntimeError) as fallo:
        comprobar(trozo.lower() in str(fallo).lower(),
                  f"{texto} -> {str(fallo)[:90]}")
        return
    comprobar(False, f"{texto} (no fallo)")


def seccion(titulo):
    print(f"\n[{titulo}]")


# ------------------------------------------------------------------ catalogo

def prueba_validacion():
    seccion("1] un ajuste imposible se rechaza antes de lanzar el CLI")

    igual(cli_claude.normalizar_modelo("sonnet"), "sonnet", "acepta un alias")
    igual(cli_claude.normalizar_modelo("  OPUS  "), "opus",
          "normaliza espacios y mayusculas")
    igual(cli_claude.normalizar_modelo("claude-opus-5"), "claude-opus-5",
          "acepta un id completo, porque el catalogo cambia mas que el codigo")
    falla(lambda: cli_claude.normalizar_modelo("sonet"), "desconocido",
          "rechaza un modelo mal escrito")
    falla(lambda: cli_claude.normalizar_esfuerzo("altisimo"), "tiene que ser",
          "rechaza un esfuerzo que no existe")
    igual(cli_claude.normalizar_modelo("sonet", estricto=False),
          cli_claude.MODELO_POR_DEFECTO,
          "sin estricto cae al valor por defecto en vez de reventar")

    igual(cli_claude.normalizar_esfuerzo(""), cli_claude.ESFUERZO_POR_DEFECTO,
          "vacio significa el valor por defecto, no un error")
    igual((cli_claude.MODELO_POR_DEFECTO, cli_claude.ESFUERZO_POR_DEFECTO),
          ("opus", "xhigh"),
          "y el defecto del canal es opus con esfuerzo muy alto (21-08-2026)")

    catalogo = cli_claude.catalogo()
    comprobar(len(catalogo["modelos"]) >= 3 and len(catalogo["esfuerzos"]) == 5,
              f"el catalogo publica {len(catalogo['modelos'])} modelos y "
              f"{len(catalogo['esfuerzos'])} esfuerzos")
    comprobar(all(e.get("nota") for e in catalogo["esfuerzos"]),
              "cada esfuerzo lleva su nota, para que elegir no sea a ciegas")
    igual(sorted(e["id"] for e in catalogo["esfuerzos"]),
          sorted(cli_claude.ESFUERZOS),
          "el catalogo y la lista de validacion son la MISMA lista")


def prueba_tiempo():
    seccion("2] el plazo escala con el esfuerzo")

    plazos = [cli_claude.tiempo_max(e, base_s=420) for e in cli_claude.ESFUERZOS]
    comprobar(plazos == sorted(plazos) and len(set(plazos)) > 1,
              f"sube con el esfuerzo: {dict(zip(cli_claude.ESFUERZOS, plazos))}")
    # El PLAZO se deriva del modelo Y del esfuerzo, y `base_s` esta calibrado
    # sobre sonnet/low: por eso hay que nombrar el modelo para fijar la
    # referencia. Sin nombrarlo manda el defecto del canal, que desde el
    # 21-08-2026 es opus -- y entonces hasta una llamada de esfuerzo bajo tiene
    # mas plazo, que es lo correcto: tarda mas.
    igual(cli_claude.tiempo_max("low", base_s=420, modelo="sonnet"), 420,
          "con sonnet y esfuerzo bajo se queda en el plazo de siempre")
    comprobar(cli_claude.tiempo_max("low", base_s=420) > 420,
              "y sin nombrar modelo manda el defecto del canal, que da mas plazo")
    comprobar(cli_claude.tiempo_max("high", base_s=420) > 420,
              "con esfuerzo alto se le da mas margen: un techo fijo de 420 s "
              "garantizaba TiempoAgotado, y TiempoAgotado no se reintenta")
    igual(cli_claude.tiempo_max("max", base_s=420), cli_claude.TIEMPO_MAXIMO_S,
          "y hay un techo absoluto, para que nada espere indefinidamente")
    igual(cli_claude.tiempo_max("low", base_s=420, pedido_s=900), 900,
          "un plazo puesto a mano manda sobre el automatico")

    import p3_guion
    opciones = p3_guion._normalizar({"esfuerzo": "high"})
    comprobar(p3_guion.umbral_reintento_de(opciones) > 120,
              "el umbral de reintento tambien escala: con uno fijo, subir el "
              "esfuerzo desactivaba los reintentos SIN DECIRLO")


def prueba_orden():
    seccion("3] la orden del CLI se arma en un unico sitio")

    orden = cli_claude.construir_orden("opus", "high", sistema="una linea")
    for bandera in ("--model", "--effort", "--output-format",
                    "--strict-mcp-config"):
        comprobar(bandera in orden, f"la orden lleva {bandera}")
    igual(orden[orden.index("--model") + 1], "opus", "y el modelo elegido")
    igual(orden[orden.index("--effort") + 1], "high", "y el esfuerzo elegido")

    falla(lambda: cli_claude.construir_orden(sistema="dos\nlineas"),
          "una sola linea",
          "un prompt de sistema con salto de linea se rechaza (en Windows "
          "partiria la orden de claude.cmd)")

    entorno = cli_claude.entorno()
    comprobar("CLAUDE_EFFORT" not in entorno
              and "MAX_THINKING_TOKENS" not in entorno,
              "el entorno del hijo va limpio de variables de razonamiento")


class ProcesoFalso:
    """Un Popen de mentira: cli_claude habla con el CLI por communicate()."""

    def __init__(self, sobre=None, al_comunicar=None, codigo=0):
        self.returncode = codigo
        self._sobre = sobre if sobre is not None else {"result": "vale"}
        self._al_comunicar = al_comunicar
        self.pid = 999
        self.matado = False

    def communicate(self, entrada=None, timeout=None):
        if self._al_comunicar:
            raise self._al_comunicar
        return json.dumps(self._sobre).encode("utf-8"), b""

    def kill(self):
        self.matado = True


def prueba_ejecucion():
    seccion("4] la ejecucion estampa el ajuste y corta a tiempo")

    original_popen = subprocess.Popen
    original_which = shutil.which
    original_cuentas = cli_claude.cuentas
    shutil.which = lambda nombre: r"C:\falso\claude.cmd"
    # UNA SOLA CUENTA, siempre. Esta prueba mide que UNA pasada falla limpio, y
    # sin fijarlo leeria el almacen de verdad: en una maquina con tres cuentas
    # logueadas los tres casos de fallo correrian tres veces cada uno, y el
    # texto de la comprobacion pasaria a decir otra cosa que la que mide.
    cli_claude.cuentas = lambda: [{"etiqueta": "", "config_dir": ""}]
    try:
        subprocess.Popen = lambda *a, **k: ProcesoFalso(
            {"result": "hecho", "usage": {"output_tokens": 12}})
        texto, sobre = cli_claude.ejecutar("hola", modelo="opus",
                                           esfuerzo="medium")
        igual(texto, "hecho", "devuelve el texto de la respuesta")
        igual(sobre["_ajuste"]["modelo"], "opus",
              "y estampa el modelo en el sobre")
        igual(sobre["_ajuste"]["esfuerzo"], "medium",
              "y el esfuerzo, que el CLI NO devuelve y es lo que mas mueve el "
              "tiempo")
        comprobar(sobre["_ajuste"]["segundos"] >= 0,
                  "y los segundos reales que tardo")

        colgado = ProcesoFalso(
            al_comunicar=subprocess.TimeoutExpired("claude", 420))
        subprocess.Popen = lambda *a, **k: colgado
        falla(lambda: cli_claude.ejecutar("hola", esfuerzo="low"),
              "no ha respondido", "al vencer el plazo se explica y se corta")
        comprobar(colgado.matado,
                  "y se mata el proceso (con taskkill /T se van tambien los hijos)")

        subprocess.Popen = lambda *a, **k: ProcesoFalso(
            {"is_error": True, "result": "sin credito"})
        falla(lambda: cli_claude.ejecutar("hola"), "devolvio error",
              "un is_error del CLI es un error del paso")

        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": "   "})
        falla(lambda: cli_claude.ejecutar("hola"), "vacia",
              "una respuesta en blanco no se da por buena")
    finally:
        subprocess.Popen = original_popen
        shutil.which = original_which
        cli_claude.cuentas = original_cuentas


def prueba_limite():
    seccion("5] un cupo agotado se dice en cristiano y no se reintenta")
    # EL FALLO QUE ARREGLA, visto el 24-08-2026 a mitad de una tanda: el cupo
    # semanal se agoto, el CLI salio con codigo 1 y lo que llego a la pantalla
    # fueron 600 caracteres de JSON con `input_tokens: 0`, que parece una averia
    # del Estudio. El motivo de verdad venia dentro, en `result`.
    real = "You've hit your weekly limit · resets Aug 27, 7am (Europe/Andorra)"
    comprobar(cli_claude.limite_de(real) == real,
              "se reconoce el mensaje REAL del CLI, tal cual lo escribe")
    for dicho in ("Claude usage limit reached. Your limit will reset at 3pm.",
                  "5-hour limit reached · resets 9pm",
                  "Has agotado tu limite semanal, se renueva el 27 de agosto",
                  "Quota exceeded for this account"):
        comprobar(cli_claude.limite_de(dicho),
                  f"y tambien esta forma: {dicho[:38]}...")
    for otro in ("", None, "el modelo no existe", "connection reset by peer",
                 "hecho"):
        comprobar(cli_claude.limite_de(otro) is None,
                  f"y NO se confunde con {otro!r}: un fallo normal sigue "
                  f"siendo un fallo normal")

    original_popen = subprocess.Popen
    original_which = shutil.which
    original_cuentas = cli_claude.cuentas
    shutil.which = lambda nombre: r"C:\falso\claude.cmd"
    cli_claude.cuentas = lambda: [{"etiqueta": "", "config_dir": ""}]
    try:
        # codigo 1 CON sobre dentro: es como sale de verdad
        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": real,
                                                         "is_error": True},
                                                        codigo=1)
        try:
            cli_claude.ejecutar("hola", para="el guion")
            comprobar(False, "un cupo agotado tiene que fallar")
        except cli_claude.LimiteAgotado as fallo:
            comprobar("cupo" in str(fallo) and "el guion" in str(fallo),
                      "sale un LimiteAgotado que dice QUE no se ha podido hacer")
            comprobar("resets Aug 27" in str(fallo),
                      "y CUANDO se renueva, que es lo unico que le importa a "
                      "quien mira la pantalla")
            comprobar("input_tokens" not in str(fallo),
                      "y no el JSON crudo del sobre")
        except RuntimeError as fallo:
            comprobar(False, f"tenia que ser LimiteAgotado y fue {fallo!r}")

        # el mismo mensaje pero con codigo 0 e is_error: el otro camino
        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": real,
                                                         "is_error": True})
        falla(lambda: cli_claude.ejecutar("hola"), "cupo",
              "y por el camino de is_error con codigo 0, igual")

        # un fallo NORMAL con codigo 1 sigue explicandose, y ahora mejor: con el
        # `result` del sobre delante en vez del JSON entero
        subprocess.Popen = lambda *a, **k: ProcesoFalso(
            {"result": "model 'opus-9' not found", "is_error": True}, codigo=1)
        try:
            cli_claude.ejecutar("hola")
            comprobar(False, "un fallo normal tiene que fallar")
        except cli_claude.LimiteAgotado:
            comprobar(False, "un modelo inexistente NO es un cupo agotado")
        except RuntimeError as fallo:
            comprobar("opus-9" in str(fallo),
                      "un fallo normal ensena el motivo del sobre, no el JSON")
    finally:
        subprocess.Popen = original_popen
        shutil.which = original_which
        cli_claude.cuentas = original_cuentas

    # Y NO SE REINTENTA. Reintentar un cupo agotado gasta los reintentos en un
    # segundo y hace que el error guardado sea el del ULTIMO intento: el mismo
    # mensaje, pero sin la pista de que ya se sabia desde el primero.
    import p3_guion
    comprobar(cli_claude.LimiteAgotado in p3_guion.SIN_REINTENTO,
              "el bucle de reintentos del guion lo trata como el timeout")
    comprobar(cli_claude.TiempoAgotado in p3_guion.SIN_REINTENTO,
              "y el timeout sigue dentro")
    comprobar(issubclass(cli_claude.LimiteAgotado, RuntimeError),
              "y sigue siendo un RuntimeError, para que la cuenta de respaldo "
              "-- que tiene OTRO cupo -- entre a probar antes de rendirse")


def prueba_cadena():
    seccion("6] la cadena de cuentas: por orden, y el ultimo fallo sube tal cual")
    original_popen = subprocess.Popen
    original_which = shutil.which
    original_cuentas = cli_claude.cuentas
    shutil.which = lambda nombre: r"C:\falso\claude.cmd"
    limite = "You've hit your weekly limit \u00b7 resets Aug 27, 7am"
    try:
        tres = [{"etiqueta": "la mia", "config_dir": "C:\\a"},
                {"etiqueta": "la segunda", "config_dir": "C:\\b"},
                {"etiqueta": "la tercera", "config_dir": "C:\\c"}]
        cli_claude.cuentas = lambda: list(tres)

        # 1) la PRIMERA manda: si contesta, no se toca ninguna otra
        usadas = []

        def falso(*a, **k):
            usadas.append(k.get("env", {}).get("CLAUDE_CONFIG_DIR", ""))
            return ProcesoFalso({"result": "hecho"})

        subprocess.Popen = falso
        texto, sobre = cli_claude.ejecutar("hola")
        igual(texto, "hecho", "con la primera cuenta basta")
        igual(usadas, ["C:\\a"], "y las demas ni se lanzan")
        igual(sobre["_ajuste"]["cuenta"], "la mia",
              "el sobre dice CON CUAL se hizo, que es lo unico que lo cuenta")

        # 2) sin cupo en las dos primeras: entra la tercera
        usadas.clear()
        respuestas = [
            ProcesoFalso({"result": limite, "is_error": True}, codigo=1),
            ProcesoFalso({"result": limite, "is_error": True}, codigo=1),
            ProcesoFalso({"result": "por fin"}),
        ]

        def por_turnos(*a, **k):
            usadas.append(k.get("env", {}).get("CLAUDE_CONFIG_DIR", ""))
            return respuestas[len(usadas) - 1]

        subprocess.Popen = por_turnos
        texto, sobre = cli_claude.ejecutar("hola")
        igual(texto, "por fin", "sin cupo en las dos primeras, contesta la tercera")
        igual(usadas, ["C:\\a", "C:\\b", "C:\\c"], "y se recorren EN ORDEN")
        igual(sobre["_ajuste"]["cuenta"], "la tercera", "y se apunta cual salvo la tanda")

        # 3) TODAS sin cupo: sube el ULTIMO fallo, con su tipo y su texto.
        # Esto no es cosmetico: un RuntimeError generico del tipo "las 3 cuentas
        # fallaron" hace que `limite_de` no lo reconozca, y con el se pierden el
        # aviso en cristiano y la valvula CUPO de las suites, que casa por TEXTO.
        usadas.clear()
        subprocess.Popen = lambda *a, **k: (
            usadas.append(k.get("env", {}).get("CLAUDE_CONFIG_DIR", "")),
            ProcesoFalso({"result": limite, "is_error": True}, codigo=1))[1]
        try:
            cli_claude.ejecutar("hola", para="el guion")
            comprobar(False, "con todas sin cupo tiene que fallar")
        except cli_claude.LimiteAgotado as fallo:
            igual(len(usadas), 3, "se prueban las tres antes de rendirse")
            comprobar("resets Aug 27" in str(fallo),
                      "y el ultimo fallo sube TAL CUAL, sin envolver: si no, "
                      "`limite_de` deja de reconocerlo y pruebas.ps1 pinta "
                      "FALLA donde tenia que pintar CUPO")
            comprobar(cli_claude.limite_de(str(fallo)),
                      "comprobado con el mismo reconocedor que usa la valvula")
        except RuntimeError as fallo:
            comprobar(False, f"tenia que ser LimiteAgotado y fue {fallo!r}")

        # 4) UN TIMEOUT NO BAJA A LA SIGUIENTE, a proposito
        usadas.clear()
        subprocess.Popen = lambda *a, **k: (
            usadas.append(k.get("env")) if "env" in k else None,
            ProcesoFalso(al_comunicar=subprocess.TimeoutExpired("claude", 420)))[1]
        falla(lambda: cli_claude.ejecutar("hola", esfuerzo="low"),
              "no ha respondido", "un plazo agotado se corta y se dice")
        igual(len(usadas), 1,
              "y NO se prueba con las otras: el techo ya escala con el "
              "esfuerzo, asi que volveria a vencer igual")

        # 5) sin cuentas en el almacen, el login por defecto: nunca lista vacia
        cli_claude.cuentas = original_cuentas
        subprocess.Popen = lambda *a, **k: ProcesoFalso({"result": "vale"})
        comprobar(len(cli_claude.cuentas()) >= 1,
           "cuentas() nunca devuelve una lista vacia: sin cuentas no habria a "
           "quien llamar, y un almacen ilegible no puede dejar al Estudio mudo")
    finally:
        subprocess.Popen = original_popen
        shutil.which = original_which
        cli_claude.cuentas = original_cuentas


def prueba_login():
    seccion("7] entrar con una cuenta se hace desde la pantalla, no en una consola")
    import login_cli

    # LO QUE NO PUEDE PASAR: que el servidor abra un navegador. Aqui se trabaja
    # por escritorio remoto, y ademas el navegador se abriria en la maquina y no
    # en el movil desde el que se esta mirando. Medido: sin BROWSER=none sale un
    # msedge.exe nuevo por cada intento.
    fuente = io.open(login_cli.__file__, encoding="utf-8").read()
    comprobar('entorno["BROWSER"] = "none"' in fuente,
       "el intento apaga el navegador del CLI (medido: si no, abre un Edge)")
    comprobar("cli_claude.SIN_VENTANA" in fuente, "y va sin consola, como todo lo demas")
    comprobar("matar_arbol" in fuente,
       "y al matarlo se lleva el arbol: claude.cmd arranca un node aparte")

    # el enlace se saca por la URL y no por la frase que la precede
    salida = ("Opening browser to sign in\u2026\nIf the browser didn't open, visit: "
              "https://claude.com/cai/oauth/authorize?code=true&client_id=abc"
              "&state=xyz\nPaste code here if prompted > ")
    hallado = login_cli._ENLACE.search(salida)
    comprobar(hallado and hallado.group(0).endswith("state=xyz"),
       "el enlace se reconoce entero, hasta el final")
    comprobar("Opening browser" not in (hallado.group(0) if hallado else ""),
       "y sin la frase de delante, que es copy y cambia")

    # lo que dijo el CLI, sin el hueco donde espera el codigo
    igual(login_cli._ultima_linea(
        "Paste code here if prompted > Invalid code. Please make sure the full "
        "code was copied."),
        "Invalid code. Please make sure the full code was copied.",
        "de la ultima linea se quita el 'Paste code here >', que viene pegado")
    igual(login_cli._ultima_linea(""), "", "y una salida vacia no inventa nada")

    # la carpeta de una cuenta se saca de su id, y no se puede salir de ella
    comprobar(login_cli.carpeta_de("cli2").endswith("cli2"), "cada cuenta, su carpeta")
    comprobar(".." not in login_cli.carpeta_de("../../otro"),
       "y un id con puntos no se sale de la carpeta base")
    comprobar(login_cli.carpeta_de("") .endswith("cta"),
       "un id vacio no deja la ruta a medias")

    # de la sesion por defecto no se puede echar a nadie desde aqui
    falla(lambda: login_cli.salir(""), "terminal",
          "cerrar la sesion por defecto se rechaza: es la misma con la que el "
          "usuario tiene su consola abierta")

    # y sin intento abierto, pegar un codigo se explica en vez de reventar
    login_cli.olvidar_todos()
    falla(lambda: login_cli.pegar("cli9", "x"), "Entrar",
          "pegar un codigo sin haber entrado dice que le des a Entrar")
    igual(login_cli.mirar("cli9"), None, "y no hay nada que mirar")
    comprobar(login_cli.cancelar("cli9") is False, "ni nada que cancelar")


# ---------------------------------------------------------------- historico

def prueba_historico(carpeta):
    seccion("5] el historico distingue combinaciones y dice de donde sale cada cifra")

    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(carpeta, "est.json")
    for segundos in (70, 74, 68):
        estadisticas.anotar("guion", segundos, tamano=9000,
                            ajuste={"modelo": "sonnet", "esfuerzo": "low"},
                            proyecto="p1", intentos=1)

    previsto = estadisticas.estimar("guion", 9000,
                                    {"modelo": "sonnet", "esfuerzo": "low"})
    igual(previsto["segundos"], 70.0, "la mediana de las tres medidas")
    comprobar(previsto["medida"] and previsto["muestras"] == 3,
              f"se declara medida y con cuantas muestras: {previsto['origen']}")

    otra = estadisticas.estimar("guion", 9000,
                                {"modelo": "sonnet", "esfuerzo": "high"})
    comprobar(otra["segundos"] > previsto["segundos"],
              f"otra combinacion se estima mas lenta: {otra['segundos']} s")
    comprobar(not otra["medida"] and "escalado desde" in otra["origen"],
              f"y NO se hace pasar por medida: {otra['origen']}")

    estadisticas.anotar("guion", 3200, ok=False,
                        ajuste={"modelo": "opus", "esfuerzo": "max"},
                        proyecto="p1", resultado="tiempo agotado")
    fallida = estadisticas.resumen_ajuste("guion", "opus", "max")
    igual(fallida["fallidas"], 1, "una ejecucion que vence deja rastro")
    comprobar(fallida["fiabilidad"] == 0.0,
              "y su fiabilidad queda a 0, que es justo lo que hay que avisar")

    # la mediana NO puede contaminarse con la combinacion que fallo
    comprobar(estadisticas.estimar(
        "guion", 9000, {"modelo": "sonnet", "esfuerzo": "low"})["segundos"] == 70.0,
        "una ejecucion fallida no estropea la estimacion de otra combinacion")


def prueba_recomendacion(carpeta):
    seccion("6] la recomendacion no confunde 'rapido' con 'bueno'")

    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(carpeta, "rec.json")

    vacia = estadisticas.recomendacion("guion")
    comprobar(not vacia["hay_datos"] and "no hay ejecuciones" in vacia["motivo"],
              "sin historial dice que no hay datos, en vez de inventar")
    igual(vacia["ajuste"]["modelo"], cli_claude.MODELO_POR_DEFECTO,
          "y se queda en el ajuste por defecto")

    for _ in range(3):
        estadisticas.anotar("guion", 60, tamano=9000, proyecto="p1",
                            ajuste={"modelo": "haiku", "esfuerzo": "low"})
    for _ in range(3):
        estadisticas.anotar("guion", 400, tamano=9000, proyecto="p1",
                            ajuste={"modelo": "opus", "esfuerzo": "high"})

    sin_valorar = estadisticas.recomendacion("guion", 9000)
    comprobar(sin_valorar["confianza"] in ("media", "baja"),
              f"con ejecuciones pero sin valoracion la confianza no es alta: "
              f"{sin_valorar['confianza']}")
    comprobar("nadie ha valorado" in sin_valorar["motivo"].lower(),
              "y lo dice: habla de que funciona, no de que quede mejor")

    estadisticas.valorar("guion", "mal",
                         ajuste={"modelo": "haiku", "esfuerzo": "low"})
    estadisticas.valorar("guion", "bien",
                         ajuste={"modelo": "opus", "esfuerzo": "high"})
    valorada = estadisticas.recomendacion("guion", 9000)
    igual(valorada["ajuste"]["modelo"], "opus",
          "valorado el resultado, recomienda el que gusto aunque sea 6 veces "
          "mas lento: lo mas rapido siempre seria haiku/low y eso no es un "
          "consejo, es una tautologia")

    tabla = estadisticas.comparativa("guion", 9000)
    igual(len(tabla["ajustes"]),
          len(cli_claude.MODELOS) * len(cli_claude.ESFUERZOS),
          "la comparativa trae TODAS las combinaciones, tambien las no probadas")
    comprobar(all(f.get("origen") for f in tabla["ajustes"]),
              "y cada una dice de donde sale su cifra")


def prueba_retencion(carpeta):
    seccion("7] el recorte del historico es por combinacion")

    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(carpeta, "ret.json")
    estadisticas.anotar("guion", 999, tamano=9000, proyecto="p1",
                        ajuste={"modelo": "opus", "esfuerzo": "max"})
    for i in range(estadisticas.MUESTRAS_POR_AJUSTE + 15):
        estadisticas.anotar("guion", 60 + i, tamano=9000, proyecto="p1",
                            ajuste={"modelo": "sonnet", "esfuerzo": "low"})

    raras = estadisticas.historial("guion",
                                   ajuste={"modelo": "opus", "esfuerzo": "max"})
    igual(len(raras), 1,
          "la unica muestra del ajuste caro sobrevive a 45 del barato: "
          "recortando por paso se perdia, y es de la que mas falta hace saber")
    comunes = estadisticas.historial("guion",
                                     ajuste={"modelo": "sonnet", "esfuerzo": "low"})
    igual(len(comunes), estadisticas.MUESTRAS_POR_AJUSTE,
          f"y del ajuste usado se guardan las ultimas {estadisticas.MUESTRAS_POR_AJUSTE}")

