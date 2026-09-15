"""Las claves de API y las cuentas, en un solo sitio y editables desde la pantalla.

DE DONDE VIENE ESTO
-------------------
Hasta el 20-08-2026 cada proveedor cargaba su clave por su cuenta y desde un
sitio distinto: OpenAI de `C:\\IA\\secrets\\.env` (una principal mas
OPENAI_API_KEY_2..9), Cartesia del .env del motor anterior, Jamendo y Freesound del
de secrets, y el CLI de Claude de la sesion con la que estuviera logueado. Anadir
una cuenta era editar un fichero a mano y reiniciar, y en pantalla no habia nada:
ni que claves hay, ni cual esta gastada, ni con que cuenta se genero cada imagen.

Aqui vive el almacen, y tres reglas que no se tocan:

1. **Nunca en el repo.** El fichero es `<producto>/secretos/claves.json`, y la
   carpeta `secretos/` esta ignorada por git. Un secreto commiteado no se
   arregla borrandolo: se rota. Se puede mover con `ESTUDIO_SECRETOS`, que es
   lo que hace falta cuando varias cuentas comparten una maquina.

2. **El .env se sigue escribiendo.** Los motores de `C:\\IA\\motores` leen el
   .env y no son solo del Estudio, asi que guardar aqui ESPEJA las claves alli
   con los nombres de siempre (OPENAI_API_KEY, OPENAI_API_KEY_2...). Asi el dia
   que alguien arranque un motor sin pasar por el Estudio, sigue funcionando.
   Lo que el .env no sabe guardar -- de quien es cada cuenta -- vive solo aqui.

3. **La clave nunca sale por la API.** `resumen()` devuelve etiqueta, los cuatro
   ultimos caracteres y poco mas. Lo que se manda para guardar puede ser la
   clave entera o el marcador `CONSERVAR`, que significa "deja la que ya habia":
   asi la pantalla puede editar la etiqueta de una cuenta sin tener delante su
   clave.

QUE ES UNA CUENTA DEL CLI DE CLAUDE
-----------------------------------
No es una clave: es un LOGIN. El Estudio consume la suscripcion con la que el
CLI esta logueado y `cli_claude.entorno()` borra a proposito las variables de
pago por uso para que no pueda salirse de ahi (ANTHROPIC_API_KEY y companiaa).
Una cuenta es por tanto una CARPETA DE CONFIGURACION del CLI
(`CLAUDE_CONFIG_DIR`) con su propio login dentro. Meter una clave de API como
respaldo convertiria cada paso en pago por uso sin que nadie se entere, y eso es
justo lo que el contrato prohibe.

**Y son una LISTA ORDENADA, no un par.** Hasta el 24-08-2026 habia exactamente
dos huecos, "principal" y "respaldo", y la carpeta se pegaba a mano. Dos cosas
lo tumbaron el mismo dia: el cupo semanal se agoto de verdad (y una sola cuenta
de respaldo es una sola bala), y el metodo de configurarla era un manual --«crea
una carpeta, corre `claude` con CLAUDE_CONFIG_DIR apuntando ahi, y pega la
ruta»-- justo para el momento en que menos ganas hay de abrir una consola.

Ahora:

  - la lista manda por ORDEN: la primera es la favorita y las siguientes entran
    por orden cuando la de delante falla o se queda sin cupo;
  - `config_dir` y `entrada` los escribe el SERVIDOR, nunca la pantalla. La
    pantalla solo manda id, etiqueta y el orden. Asi un «Guardar» hecho sobre
    una ficha vieja no puede deshacer un login que acabo de terminar;
  - `entrada` es la marca de «esta cuenta tiene sesion hecha». Una cuenta a
    medio loguear existe en la lista pero NO se usa: sin esa marca, un trabajo
    que estuviera corriendo recogeria en caliente una carpeta con un login a
    medias, que falla de una forma que no se parece a nada.

El login vive en `pasos/login_cli.py`; aqui solo se guarda el resultado.
"""
import json
import os
import re
import tempfile
import threading

#: Donde vive el almacen. FUERA del repo, a proposito (ver la cabecera).
CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "secretos")
FICHERO = os.path.join(CARPETA_SECRETOS, "claves.json")
#: El .env que leen los motores. Se espeja al guardar, nunca se lee como verdad
#: salvo la primera vez (`adoptar_env`).
FICHERO_ENV = os.path.join(CARPETA_SECRETOS, ".env")

#: Lo que manda la pantalla cuando no quiere tocar una clave que ya existe. La
#: clave de verdad no baja al navegador NUNCA, asi que sin esto editar la
#: etiqueta de una cuenta la habria borrado.
CONSERVAR = "__CONSERVAR__"

#: UNA sola clave de OpenAI. Hubo hasta nueve cuentas repartiendose las
#: imagenes de una tanda, y con ellas una cadena que apartaba la que devolvia
#: 401 y seguia con las demas: eso convertia una clave mal puesta en «va mas
#: lento» en vez de en un error. Con una, si esta mal se dice y se para.
MAX_OPENAI = 1

#: Tope de cuentas del CLI. Aqui no lo impone ningun .env: lo impone que la
#: cadena se recorre EN SERIE cuando falla, asi que cada cuenta de mas es una
#: espera mas antes de darse por vencido.
MAX_CLI = 6

_LOCK = threading.RLock()


class ErrorClaves(ValueError):
    """Lo que manda la pantalla no vale, y se dice por que."""


# --------------------------------------------------------------- lectura

def _vacio():
    return {
        "version": 1,
        "openai": [],
        "cartesia": {"clave": ""},
        # La musica y los efectos: se buscan en catalogos con licencia libre y
        # cada uno pide su clave. Sin ellas el paso de sonido no busca nada y lo
        # dice; no impide montar el video.
        "jamendo": {"clave": ""},
        "freesound": {"clave": ""},
        "claude_cli": {"cuentas": []},
    }


def _leer_json(ruta, defecto):
    try:
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return defecto
    return datos if isinstance(datos, dict) else defecto


def leer():
    """El almacen entero, CON las claves. Solo para el servidor, nunca la API."""
    with _LOCK:
        datos = _leer_json(FICHERO, None)
        if datos is None:
            datos = adoptar_env()
        return _normalizar(datos)


def _normalizar(datos):
    """La forma canonica, aguantando un fichero escrito a mano."""
    base = _vacio()
    datos = datos if isinstance(datos, dict) else {}

    cuentas = []
    for cruda in (datos.get("openai") or []):
        if not isinstance(cruda, dict):
            continue
        clave = str(cruda.get("clave") or "").strip()
        if not clave:
            continue
        cuentas.append({
            "id": str(cruda.get("id") or "").strip() or _nuevo_id(cuentas),
            "etiqueta": str(cruda.get("etiqueta") or "").strip(),
            "clave": clave,
            "activa": cruda.get("activa") is not False,
        })
    base["openai"] = cuentas[:MAX_OPENAI]

    cartesia = datos.get("cartesia")
    if isinstance(cartesia, dict):
        base["cartesia"]["clave"] = str(cartesia.get("clave") or "").strip()
    elif isinstance(cartesia, str):
        base["cartesia"]["clave"] = cartesia.strip()

    for suelta in ("jamendo", "freesound"):
        cruda = datos.get(suelta)
        if isinstance(cruda, dict):
            base[suelta]["clave"] = str(cruda.get("clave") or "").strip()
        elif isinstance(cruda, str):
            base[suelta]["clave"] = cruda.strip()
    base["claude_cli"]["cuentas"] = _cuentas_cli_de(datos.get("claude_cli"))
    return base


def _ficha_cli(cruda, ya):
    """Una cuenta del CLI en su forma canonica."""
    return {
        "id": str(cruda.get("id") or "").strip() or _nuevo_id(ya, "cli"),
        "etiqueta": str(cruda.get("etiqueta") or "").strip(),
        "config_dir": str(cruda.get("config_dir") or "").strip(),
        "entrada": bool(cruda.get("entrada")),
    }


def _cuentas_cli_de(crudo):
    """La lista ordenada, venga como venga el fichero. -> list

    AGUANTA LA FORMA VIEJA A PROPOSITO. El almacen de esta maquina lleva escrito
    `{"principal": {...}, "respaldo": {...}}` desde el 20-08, y un normalizador
    que no la reconociera no daria error: devolveria una lista vacia y el
    Estudio se quedaria de golpe sin la cuenta con la que lleva generando desde
    entonces. Se migra en la lectura y se reescribe sola en el primer guardado.
    """
    if isinstance(crudo, list):
        crudas = crudo
    elif isinstance(crudo, dict) and isinstance(crudo.get("cuentas"), list):
        crudas = crudo["cuentas"]
    elif isinstance(crudo, dict):
        # la forma vieja: dos papeles con nombre, y el orden lo daba el nombre
        crudas = []
        for papel in ("principal", "respaldo"):
            ficha = crudo.get(papel)
            if not isinstance(ficha, dict):
                continue
            etiqueta = str(ficha.get("etiqueta") or "").strip()
            carpeta = str(ficha.get("config_dir") or "").strip()
            if papel == "respaldo" and not carpeta:
                continue          # el respaldo vacio nunca fue una cuenta
            crudas.append({"etiqueta": etiqueta, "config_dir": carpeta,
                           # ya estaban logueadas: si no, no habrian servido
                           "entrada": True})
    else:
        crudas = []

    cuentas = []
    for cruda in crudas:
        if not isinstance(cruda, dict):
            continue
        cuentas.append(_ficha_cli(cruda, cuentas))
    return cuentas[:MAX_CLI]


def _nuevo_id(ya, prefijo="cta"):
    ocupados = {c.get("id") for c in ya}
    indice = 1
    while f"{prefijo}{indice}" in ocupados:
        indice += 1
    return f"{prefijo}{indice}"


def adoptar_env():
    """La primera vez: se recogen las claves que ya estaban en el .env.

    Sin esto, abrir la pantalla de configuracion el primer dia ensenaria cero
    cuentas mientras el Estudio genera tan tranquilo con las dos del .env, que es
    la peor forma de estrenar un panel: diciendo algo que no es verdad.
    """
    datos = _vacio()
    valores = _valores_env()
    principal = valores.get("OPENAI_API_KEY")
    if principal:
        datos["openai"].append({"id": "cta1", "etiqueta": "", "clave": principal,
                                "activa": True})
    for indice in range(2, MAX_OPENAI + 1):
        clave = valores.get(f"OPENAI_API_KEY_{indice}")
        if clave:
            datos["openai"].append({"id": f"cta{indice}", "etiqueta": "",
                                    "clave": clave, "activa": True})
    datos["cartesia"]["clave"] = valores.get("CARTESIA_API_KEY", "") or ""
    datos["jamendo"]["clave"] = valores.get("JAMENDO_CLIENT_ID", "") or ""
    datos["freesound"]["clave"] = valores.get("FREESOUND_API_KEY", "") or ""
    return datos


def _valores_env(ruta=None):
    """Las parejas CLAVE=valor del .env. utf-8-sig porque el fichero tiene BOM."""
    ruta = ruta or FICHERO_ENV
    valores = {}
    if not os.path.exists(ruta):
        return valores
    try:
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            for linea in fh:
                trozo = linea.strip()
                if not trozo or trozo.startswith("#") or "=" not in trozo:
                    continue
                nombre, valor = trozo.split("=", 1)
                valores[nombre.strip()] = valor.strip()
    except OSError:
        return {}
    return valores


# --------------------------------------------------------------- escritura

def guardar(peticion):
    """Valida lo que manda la pantalla, lo escribe y espeja el .env.

    Devuelve el `resumen()` de lo que queda guardado, para que quien llame no
    tenga que volver a leer y para que la respuesta no lleve ni una clave.
    """
    with _LOCK:
        actual = leer()
        nuevo = _fusionar(actual, peticion)
        _escribir_json(FICHERO, nuevo)
        espejar_env(nuevo)
        return resumen(nuevo)


def _fusionar(actual, peticion):
    """Lo nuevo sobre lo viejo, resolviendo los CONSERVAR contra lo que habia."""
    if not isinstance(peticion, dict):
        raise ErrorClaves("se esperaba un objeto con las claves")
    salida = _vacio()
    por_id = {c["id"]: c for c in actual["openai"]}

    if "openai" in peticion:
        crudas = peticion.get("openai")
        if not isinstance(crudas, list):
            raise ErrorClaves("'openai' tiene que ser una lista de cuentas")
        if len(crudas) > MAX_OPENAI:
            raise ErrorClaves(
                "aqui va UNA clave de OpenAI. Si tienes varias cuentas, "
                "elige con cual generar: repartir entre ellas convertia una "
                "clave mal puesta en «va mas lento» en vez de en un error")
        cuentas = []
        for cruda in crudas:
            if not isinstance(cruda, dict):
                raise ErrorClaves("cada cuenta de OpenAI es un objeto "
                                  "{etiqueta, clave}")
            cid = str(cruda.get("id") or "").strip()
            clave = str(cruda.get("clave") or "").strip()
            if clave == CONSERVAR:
                anterior = por_id.get(cid)
                if anterior is None:
                    raise ErrorClaves(f"la cuenta '{cid}' pide conservar su "
                                      f"clave y no hay ninguna guardada")
                clave = anterior["clave"]
            if not clave:
                raise ErrorClaves("una cuenta de OpenAI sin clave no sirve de "
                                  "nada: escribela o quita la cuenta")
            _validar_clave_openai(clave)
            cuentas.append({
                "id": cid or _nuevo_id(cuentas),
                "etiqueta": str(cruda.get("etiqueta") or "").strip(),
                "clave": clave,
                "activa": cruda.get("activa") is not False,
            })
        _sin_repetidas(cuentas)
        salida["openai"] = cuentas
    else:
        salida["openai"] = actual["openai"]

    # LAS TRES CLAVES SUELTAS, con la misma regla: la que llega como CONSERVAR
    # es la que ya habia. Sin eso, editar la de Jamendo borraria la de Cartesia,
    # porque la clave de verdad no baja al navegador NUNCA y la pantalla manda
    # el centinela en su lugar.
    for suelta in ("cartesia", "jamendo", "freesound"):
        if suelta in peticion:
            ficha = peticion.get(suelta)
            clave = ficha.get("clave") if isinstance(ficha, dict) else ficha
            clave = str(clave or "").strip()
            if clave == CONSERVAR:
                clave = actual[suelta]["clave"]
            salida[suelta]["clave"] = clave
        else:
            salida[suelta] = actual[suelta]

    if "claude_cli" in peticion:
        salida["claude_cli"]["cuentas"] = _cuentas_cli_pedidas(
            peticion.get("claude_cli"), actual["claude_cli"]["cuentas"])
    else:
        salida["claude_cli"] = actual["claude_cli"]
    return salida


def _cuentas_cli_pedidas(crudo, actuales):
    """La lista que pide la pantalla, con lo del servidor intacto. -> list

    LA PANTALLA NO MANDA `config_dir` NI `entrada`, y no es una omision: son del
    servidor. La pantalla solo sabe de id, etiqueta y ORDEN. Si pudiera mandar
    los otros dos, un «Guardar» hecho sobre una ficha leida hace un minuto
    desharia el login que acaba de terminar en segundo plano -- y lo desharia en
    silencio, que es la peor forma de perder un login.

    Lo que SI puede hacer la pantalla es quitar una cuenta: la que no venga en
    la lista, se va.
    """
    if isinstance(crudo, dict) and isinstance(crudo.get("cuentas"), list):
        crudas = crudo["cuentas"]
    elif isinstance(crudo, list):
        crudas = crudo
    else:
        raise ErrorClaves("'claude_cli' tiene que ser una lista ordenada de "
                          "cuentas, o un objeto {cuentas: [...]}")
    if len(crudas) > MAX_CLI:
        raise ErrorClaves(f"como mucho {MAX_CLI} cuentas del CLI: la cadena se "
                          f"recorre en serie cuando falla, y cada cuenta de mas "
                          f"es una espera mas antes de rendirse")
    por_id = {c["id"]: c for c in actuales}
    cuentas = []
    for cruda in crudas:
        if not isinstance(cruda, dict):
            raise ErrorClaves("cada cuenta del CLI es un objeto {id, etiqueta}")
        cid = str(cruda.get("id") or "").strip()
        anterior = por_id.get(cid) or {}
        cuentas.append(_ficha_cli({
            "id": cid,
            "etiqueta": cruda.get("etiqueta"),
            # del servidor, siempre: ver el porque arriba
            "config_dir": anterior.get("config_dir", ""),
            "entrada": anterior.get("entrada", False),
        }, cuentas))
    _revisar_cuentas_cli(cuentas)
    return cuentas


def _revisar_cuentas_cli(cuentas):
    """Lo que no puede pasar en una lista de cuentas del CLI."""
    vistos, carpetas = set(), {}
    for cuenta in cuentas:
        if cuenta["id"] in vistos:
            raise ErrorClaves(f"la cuenta '{cuenta['id']}' esta dos veces en la "
                              f"lista")
        vistos.add(cuenta["id"])
        carpeta = cuenta["config_dir"]
        if not carpeta:
            continue
        if not os.path.isdir(carpeta):
            raise ErrorClaves(
                f"la carpeta de la cuenta '{cuenta['etiqueta'] or cuenta['id']}' "
                f"no existe: {carpeta}. Es una carpeta de sesion del CLI: la "
                f"crea el Estudio al entrar con esa cuenta.")
        llave = os.path.normcase(os.path.abspath(carpeta))
        if llave in carpetas:
            raise ErrorClaves(
                f"'{cuenta['etiqueta'] or cuenta['id']}' y "
                f"'{carpetas[llave]}' usan la MISMA carpeta de sesion: "
                f"entonces no son dos cuentas, son la misma, y la segunda "
                f"fallaria por lo mismo que la primera")
        carpetas[llave] = cuenta["etiqueta"] or cuenta["id"]


def _validar_clave_openai(clave):
    # Un dedazo aqui no revienta nada: se ve como un 401 a mitad de una tanda de
    # 49 planos, que es la forma cara de enterarse.
    if len(clave) < 20 or re.search(r"\s", clave):
        raise ErrorClaves("eso no parece una clave de OpenAI: son largas y sin "
                          "espacios. Copiala entera desde platform.openai.com")


def _sin_repetidas(cuentas):
    vistas = {}
    for cuenta in cuentas:
        if cuenta["clave"] in vistas:
            otra = vistas[cuenta["clave"]]
            raise ErrorClaves(
                f"la misma clave esta puesta dos veces ({otra or 'sin etiqueta'}"
                f" y {cuenta['etiqueta'] or 'sin etiqueta'}). Repartir entre dos "
                f"copias de la misma cuenta no dobla el ritmo: el limite es del "
                f"servidor de OpenAI, no de la clave.")
        vistas[cuenta["clave"]] = cuenta["etiqueta"]


def _escribir_json(ruta, datos):
    """Escritura atomica: un fichero de claves a medio escribir deja el Estudio
    sin generar imagenes hasta que alguien lo mire."""
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    temporal = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=os.path.dirname(ruta),
                prefix=".claves-", suffix=".tmp", delete=False) as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
            temporal = fh.name
        os.replace(temporal, ruta)
        temporal = None
    finally:
        if temporal and os.path.exists(temporal):
            os.unlink(temporal)


def espejar_env(datos=None):
    """Escribe en el .env lo que los motores esperan encontrar ahi.

    Se CONSERVA todo lo que no gestiona esta pantalla (Jamendo, Freesound y
    cualquier cosa que alguien anadiera a mano): se reescriben solo las lineas
    de OpenAI y Cartesia y se dejan las demas tal cual y en su orden.
    """
    datos = datos if datos is not None else leer()
    activas = [c for c in datos["openai"] if c["activa"]]
    nuestras = {}
    for indice, cuenta in enumerate(activas, start=1):
        nombre = "OPENAI_API_KEY" if indice == 1 else f"OPENAI_API_KEY_{indice}"
        nuestras[nombre] = cuenta["clave"]
    if datos["cartesia"]["clave"]:
        nuestras["CARTESIA_API_KEY"] = datos["cartesia"]["clave"]
    if datos["jamendo"]["clave"]:
        nuestras["JAMENDO_CLIENT_ID"] = datos["jamendo"]["clave"]
    if datos["freesound"]["clave"]:
        nuestras["FREESOUND_API_KEY"] = datos["freesound"]["clave"]

    # Los nombres que ESTA pantalla escribe. Lo que no este aqui se conserva tal
    # cual y en su orden: un .env puede tener cosas que nadie de aqui gestiona.
    gestionadas = {"OPENAI_API_KEY", "CARTESIA_API_KEY",
                   "JAMENDO_CLIENT_ID", "FREESOUND_API_KEY"} | {
        f"OPENAI_API_KEY_{i}" for i in range(2, MAX_OPENAI + 1)}

    lineas, puestas = [], set()
    if os.path.exists(FICHERO_ENV):
        try:
            with open(FICHERO_ENV, "r", encoding="utf-8-sig") as fh:
                previas = fh.read().splitlines()
        except OSError:
            previas = []
        for linea in previas:
            nombre = linea.split("=", 1)[0].strip() if "=" in linea else ""
            if nombre in gestionadas:
                if nombre in nuestras and nombre not in puestas:
                    lineas.append(f"{nombre}={nuestras[nombre]}")
                    puestas.add(nombre)
                continue                       # una clave retirada desaparece
            lineas.append(linea)
    for nombre, valor in nuestras.items():
        if nombre not in puestas:
            lineas.append(f"{nombre}={valor}")
    os.makedirs(os.path.dirname(FICHERO_ENV), exist_ok=True)
    texto = "\n".join(lineas).rstrip("\n") + "\n"
    with open(FICHERO_ENV, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return FICHERO_ENV


# ----------------------------------------------------------------- resumen

def tapar(clave):
    """Una clave como se puede ensenar: los cuatro ultimos y nada mas."""
    clave = str(clave or "")
    if not clave:
        return ""
    return f"…{clave[-4:]}" if len(clave) > 4 else "…"


def resumen(datos=None):
    """Lo que SI puede bajar al navegador. Ni una clave entera."""
    datos = datos if datos is not None else leer()
    return {
        "openai": [{
            "id": c["id"],
            "etiqueta": c["etiqueta"],
            "cola": tapar(c["clave"]),
            "activa": c["activa"],
        } for c in datos["openai"]],
        "cartesia": {
            "puesta": bool(datos["cartesia"]["clave"]),
            "cola": tapar(datos["cartesia"]["clave"]),
        },
        "claude_cli": {
            "cuentas": [{
                "id": c["id"],
                "etiqueta": c["etiqueta"],
                "config_dir": c["config_dir"],
                "entrada": c["entrada"],
                # una cuenta sin carpeta propia es la sesion por defecto del
                # CLI, que es la misma con la que el usuario tiene su consola
                # abierta: de ahi no se le puede echar desde aqui
                "propia": bool(c["config_dir"]),
            } for c in datos["claude_cli"]["cuentas"]],
            "max": MAX_CLI,
        },
        "jamendo": {
            "puesta": bool(datos["jamendo"]["clave"]),
            "cola": tapar(datos["jamendo"]["clave"]),
        },
        "freesound": {
            "puesta": bool(datos["freesound"]["clave"]),
            "cola": tapar(datos["freesound"]["clave"]),
        },
        "fichero": FICHERO,
        "max_openai": MAX_OPENAI,
    }


# ------------------------------------------------- lo que usa el resto del codigo

def cuentas_cli(solo_listas=True):
    """Las cuentas del CLI, EN ORDEN. -> list

    `solo_listas` deja fuera las que todavia no tienen sesion hecha
    (`entrada` en falso). Es lo que quiere quien va a LLAMAR al CLI: una cuenta
    a medio loguear no es una cuenta, es una carpeta con un `.credentials.json`
    a medias, y usarla falla de una forma que no se parece a nada.

    La pantalla, en cambio, las quiere TODAS: si escondieramos la que esta a
    medias, el boton de entrar no tendria donde vivir.
    """
    cuentas = leer()["claude_cli"]["cuentas"]
    return [c for c in cuentas if c["entrada"]] if solo_listas else list(cuentas)


def cuenta_cli(papel="principal"):
    """La ficha de una cuenta del CLI por su papel de antes, o None.

    Se queda por compatibilidad con lo que aun habla de «principal» y
    «respaldo»: hoy eso es «la primera» y «la segunda» de la lista.
    """
    usables = cuentas_cli()
    if papel == "principal":
        # sin ninguna, el login por defecto del CLI: es como iba antes de que
        # existiera el almacen, y es lo que evita que un fichero vacio deje al
        # Estudio sin poder llamar a nadie
        return usables[0] if usables else {"etiqueta": "", "config_dir": ""}
    return usables[1] if len(usables) > 1 else None


def apuntar_cuenta_cli(cuenta_id, config_dir=None, entrada=None, etiqueta=None):
    """Lo que escribe el SERVIDOR sobre una cuenta. -> la ficha

    Solo por aqui se tocan `config_dir` y `entrada`. Ver el porque en
    `_cuentas_cli_pedidas`.
    """
    with _LOCK:
        datos = leer()
        for ficha in datos["claude_cli"]["cuentas"]:
            if ficha["id"] != cuenta_id:
                continue
            if config_dir is not None:
                ficha["config_dir"] = str(config_dir or "").strip()
            if entrada is not None:
                ficha["entrada"] = bool(entrada)
            if etiqueta is not None:
                ficha["etiqueta"] = str(etiqueta or "").strip()
            _revisar_cuentas_cli(datos["claude_cli"]["cuentas"])
            _escribir_json(FICHERO, datos)
            return dict(ficha)
    raise ErrorClaves(f"no hay ninguna cuenta del CLI con id '{cuenta_id}'")


def cartesia():
    """La clave de Cartesia guardada aqui, si la hay."""
    return leer()["cartesia"]["clave"] or ""
