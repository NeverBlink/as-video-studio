"""Prueba del acceso a una cuenta del CLI, CONTRA EL CLI DE VERDAD.

Por que esta suite existe
-------------------------
Todo lo demas del login se puede probar con dobles, y se prueba: los endpoints
en `prueba_api.py` y las piezas sueltas en `prueba_ajustes.py`. Lo que NO se
puede probar con un doble es lo unico que no controlamos: **que el CLI siga
comportandose como el dia que se escribio esto**. Y ese contrato tiene tres
clausulas que no estan escritas en ningun sitio salvo aqui:

  1. `claude auth login --claudeai` con las tuberias conectadas escribe una URL
     y se queda leyendo stdin. Si un dia decide que sin terminal no hay login,
     el boton de Entrar deja de funcionar y NADA MAS se entera.
  2. `BROWSER=none` le quita las ganas de abrir un navegador. Aqui se trabaja
     por escritorio remoto: el dia que eso deje de valer, cada intento de acceso
     abre un Edge encima de lo que el usuario este mirando.
  3. `claude auth status --json` contesta `{loggedIn, email, subscriptionType}`.
     Es la unica fuente de verdad de si una cuenta sirve.

Tarda unos segundos y sale a la red (a la pagina de acceso de Anthropic, sin
autenticar nada). Lo que NO hace, y no puede hacer, es completar un acceso: eso
pide entrar con una cuenta en un navegador.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_login.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FALLOS = []


def ok(condicion, texto):
    print(("  ok   " if condicion else "  FALLO ") + texto)
    if not condicion:
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    ok(obtenido == esperado,
       texto if obtenido == esperado
       else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def seccion(titulo):
    print(f"\n[{titulo}]")


def edges():
    """Cuantos procesos de Edge hay ahora mismo."""
    orden = ["tasklist", "/FO", "CSV", "/NH"]
    salida = subprocess.run(orden, capture_output=True, text=True,
                            creationflags=0x08000000).stdout
    return sum(1 for l in salida.splitlines() if l.lower().startswith('"msedge.exe'))


def main():
    carpeta = tempfile.mkdtemp(prefix="prueba_login_")
    # EL ALMACEN, A UNA CARPETA APARTE. Sin esto, la prueba escribiria cuentas
    # de mentira encima de las de verdad y dejaria al Estudio sin poder llamar
    # a nadie.
    os.environ["ESTUDIO_SECRETOS"] = os.path.join(carpeta, "secretos")
    os.makedirs(os.environ["ESTUDIO_SECRETOS"], exist_ok=True)

    import claves
    import cli_claude
    import login_cli
    login_cli.CARPETA_CUENTAS = os.path.join(os.environ["ESTUDIO_SECRETOS"], "cli")

    try:
        cli_claude.localizar("la prueba del acceso")
    except RuntimeError as fallo:
        print(f"\nSIN CLI: {fallo}")
        print("La suite no puede correr sin el CLI instalado.")
        shutil.rmtree(carpeta, ignore_errors=True)
        return 0

    try:
        seccion("1] preguntar por una sesion que no existe")
        vacia = login_cli.carpeta_de("nadie")
        os.makedirs(vacia, exist_ok=True)
        ficha = login_cli.situacion(vacia)
        ok(ficha["conectada"] is False, "una carpeta vacia no esta conectada")
        igual(ficha["error"], "",
              "y eso NO es un error: `auth status` sale con codigo 1 cuando no "
              "hay sesion, y esa es la respuesta, no una averia")
        ok(set(ficha) == {"conectada", "correo", "plan", "metodo", "error"},
           f"la ficha tiene siempre los mismos campos: {sorted(ficha)}")

        seccion("2] arrancar un acceso: el enlace y nada mas")
        antes = edges()
        arranque = time.time()
        intento = login_cli.entrar("cta", login_cli.asegurar_carpeta("cta"))
        tardado = time.time() - arranque
        igual(intento["estado"], "enlace",
              f"el CLI escribe el enlace y se queda esperando ({tardado:.1f}s)")
        ok(tardado < login_cli.ESPERA_ENLACE_S,
           f"y tarda mucho menos que el techo ({login_cli.ESPERA_ENLACE_S}s)")
        ok(intento["enlace"].startswith("https://claude.com/"),
           f"el enlace es de claude.com: {intento['enlace'][:60]}…")
        ok("code_challenge" in intento["enlace"],
           "y lleva dentro el reto PKCE de ESTE intento, que es justo por lo "
           "que no se puede guardar ni reutilizar")
        ok(intento["caduca_en"] > 60, f"dice cuanto le queda: {intento['caduca_en']}s")

        # LO QUE NO PUEDE PASAR: que se abra un navegador en la maquina. Ver la
        # cabecera de login_cli: medido, sin BROWSER=none sale un msedge nuevo.
        time.sleep(2.5)
        despues = edges()
        ok(despues <= antes,
           f"NO se ha abierto ningun navegador (Edge antes {antes}, despues "
           f"{despues}): aqui se trabaja por escritorio remoto")

        seccion("3] el acceso vive en el servidor, no en la pagina")
        vuelto = login_cli.mirar("cta")
        ok(vuelto and vuelto["enlace"] == intento["enlace"],
           "se reencuentra con el mismo enlace: recargar la pagina no lo pierde")

        seccion("4] un codigo mal copiado no tira el acceso")
        # Medido: con un codigo sin la parte de detras de la almohadilla el CLI
        # dice «Invalid code» y SIGUE VIVO; con uno bien formado pero invalido
        # dice «Login failed» y se cierra. Confundirlos costaba los dos minutos
        # enteros de espera y despues obligaba a empezar de cero, con un enlace
        # que seguia siendo perfectamente valido.
        arranque = time.time()
        ficha = login_cli.pegar("cta", "sinlaalmohadilla")
        tardado = time.time() - arranque
        igual(ficha["estado"], "enlace",
              f"vuelve a esperar codigo en vez de morirse ({tardado:.1f}s)")
        ok(tardado < 10, "y contesta en seguida, sin agotar el plazo entero")
        ok(ficha["mensaje"], f"diciendo lo que dijo el CLI: {ficha['mensaje']}")
        igual(ficha["enlace"], intento["enlace"],
              "y el enlace SIGUE valiendo: se puede volver a pegar")

        seccion("5] un codigo bien formado pero falso si lo tira")
        ficha = login_cli.pegar("cta", "noexiste#tampoco")
        igual(ficha["estado"], "fallo", "el intento se cierra")
        ok(ficha["mensaje"], f"con el motivo del CLI: {ficha['mensaje']}")
        ok(not (ficha.get("cuenta_conectada") or {}).get("conectada"),
           "y la carpeta sigue sin sesion")

        seccion("6] volver a entrar da un enlace NUEVO")
        segundo = login_cli.entrar("cta", login_cli.carpeta_de("cta"))
        igual(segundo["estado"], "enlace", "arranca otra vez")
        ok(segundo["enlace"] != intento["enlace"],
           "con otro enlace: el reto del intento viejo ya no vale")
        ok(login_cli.cancelar("cta") is True, "y se puede dejar a medias")
        igual(login_cli.mirar("cta"), None, "que se lo lleva entero")

        seccion("7] la cuenta no entra en la cadena hasta que hay sesion")
        ficha = claves.guardar({"claude_cli": {"cuentas": [
            {"etiqueta": "a medias"}, {"etiqueta": "la buena"}]}})
        cuentas = ficha["claude_cli"]["cuentas"]
        igual(len(cuentas), 2, "dos cuentas guardadas")
        igual(len(claves.cuentas_cli()), 0,
              "y NINGUNA usable: sin sesion hecha, una carpeta con un "
              "`.credentials.json` a medias falla de una forma que no se "
              "parece a nada")
        igual(len(claves.cuentas_cli(solo_listas=False)), 2,
              "pero la pantalla las ve las dos, que es donde vive el boton de "
              "entrar")
        claves.apuntar_cuenta_cli(cuentas[1]["id"], config_dir=carpeta,
                                  entrada=True)
        usables = claves.cuentas_cli()
        igual([c["etiqueta"] for c in usables], ["la buena"],
              "en cuanto una tiene sesion, entra ella sola")
        igual([c["etiqueta"] for c in cli_claude.cuentas()], ["la buena"],
              "y es la que ve quien va a llamar al CLI")

        seccion("8] `auth status --json` sigue contestando lo que decimos")
        # Contra la sesion POR DEFECTO, que es la unica que esta logueada de
        # verdad en esta maquina. Es la clausula 3 del contrato con el CLI.
        suya = login_cli.situacion("")
        if suya["conectada"]:
            ok(bool(suya["correo"]), f"trae el correo: {suya['correo']}")
            ok(bool(suya["plan"]), f"y el plan: {suya['plan']}")
            igual(suya["metodo"], "claude.ai",
                  "y dice que va por suscripcion y no por clave de API, que es "
                  "lo que el contrato del Estudio existe para garantizar")
        else:
            print("  (la sesion por defecto no esta logueada; nada que mirar)")
    finally:
        login_cli.olvidar_todos()
        os.environ.pop("ESTUDIO_SECRETOS", None)
        shutil.rmtree(carpeta, ignore_errors=True)

    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones:")
        for texto in FALLOS:
            print(f"  - {texto}")
        return 1
    print("ACCESO AL CLI OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
