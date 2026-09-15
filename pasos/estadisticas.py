"""
Historico de ejecuciones reales, estimacion honesta y recomendacion de ajustes.

Que resuelve
------------
Los pasos que llaman a un modelo no emiten progreso: una invocacion de
'claude -p' no dice por donde va. Antes se reportaba un 10% fijo que saltaba al
100% al terminar, que es peor que no reportar nada porque parece una medida.

Aqui se guarda cuanto tardo DE VERDAD cada ejecucion (en
C:\\IA\\estudio\\estadisticas.json), con que entrada y **con que ajuste**
(modelo y esfuerzo), y con eso se estima la siguiente.

Por que el ajuste es una dimension y no un adorno
-------------------------------------------------
Medido: el mismo guion tarda 67 s con esfuerzo 'low' y 606 s sin el flag. Si el
historico mezcla combinaciones, la mediana suma peras y manzanas y la barra de
progreso vuelve a mentir, que es justo el problema que este modulo nacio para
resolver. Por eso todo se agrupa por `modelo|esfuerzo`.

El historico es GLOBAL entre proyectos a proposito: el fichero vive junto al
Estudio, no dentro de un video. Es lo que permite que el tercer video ya empiece
sabiendo cuanto cuesta cada ajuste.

Uso
---
    marca = time.time()
    ...
    estadisticas.anotar("guion", time.time() - marca, tamano=9341,
                        ajuste={"modelo": "sonnet", "esfuerzo": "low"},
                        proyecto=pid, intentos=1)

    prevision = estadisticas.estimar("guion", tamano=9341,
                                     ajuste={"modelo": "sonnet", "esfuerzo": "low"})
    avance = estadisticas.Avance(avisar, 0.10, 0.95, prevision, "redactando")
    avance.arrancar()
    ...
    avance.parar()

    estadisticas.comparativa("guion", tamano=9341)   # tabla para el selector
    estadisticas.recomendacion("guion", tamano=9341) # que ajuste conviene
"""
import inspect
import errno
import json
import os
import tempfile
import threading
import time

try:
    from . import cli_claude
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude

RUTA_POR_DEFECTO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "estadisticas.json")


def ruta():
    """Fichero del historico.

    Se resuelve en cada llamada y no al importar: las pruebas ejecutan los pasos
    con el CLI sustituido por un doble y anotan tiempos de centesimas que no son
    medidas de nada, y mezclados con los reales estropean la estimacion de las
    ejecuciones pequenas. Desviarlo con ESTUDIO_ESTADISTICAS tiene que funcionar
    aunque la prueba ya haya importado este modulo.
    """
    return os.environ.get("ESTUDIO_ESTADISTICAS") or RUTA_POR_DEFECTO


# Muestras que se conservan POR COMBINACION, no por paso. Con un tope global de
# 40 repartido entre 15 combinaciones, las celdas poco usadas se quedaban con una
# muestra o con ninguna y el recomendador no podia decir nada de ellas.
MUESTRAS_POR_AJUSTE = 30
# Tope de seguridad por paso, para que el fichero no crezca sin limite.
MUESTRAS_POR_PASO = 400
VERSION_FORMATO = 2

# Segundos por unidad de tamano cuando todavia no hay historial. Son ordenes de
# magnitud medidos a mano una vez, no promesas: en cuanto haya una ejecucion
# real de ese paso, manda el historial. Los pasos que llaman al CLI llevan
# ademas la combinacion con la que se midieron, para poder escalar desde ahi.
INICIALES = {
    "ingesta":        {"por_unidad": 0.14, "suelo": 45.0, "unidad": "segundos de video"},
    "brief":          {"por_unidad": 0.0,  "suelo": 2.0,  "unidad": "palabras de transcript"},
    "guion":          {"por_unidad": 0.02, "suelo": 90.0, "unidad": "palabras de transcript",
                       "medido_con": {"modelo": "sonnet", "esfuerzo": "low"}},
    "voz":            {"por_unidad": 0.05, "suelo": 30.0, "unidad": "palabras de guion"},
    "revision_audio": {"por_unidad": 0.05, "suelo": 40.0, "unidad": "palabras de guion",
                       "medido_con": {"modelo": "sonnet", "esfuerzo": "low"}},
    "assets":         {"por_unidad": 30.0, "suelo": 60.0, "unidad": "escenas"},
    # Medidos en el VPS el 01-09 sobre este mismo video: callouts 705,6 s para
    # 226 planos (3,1 s cada uno) y render 633,1 s para 222 clips (2,85 s). Los
    # que habia --12 y 40-- eran de otra epoca y un orden de magnitud altos: la
    # barra prometia 96 minutos para un montaje de once.
    "callouts":       {"por_unidad": 3.2, "suelo": 30.0, "unidad": "escenas"},
    "render":         {"por_unidad": 3.0, "suelo": 60.0, "unidad": "escenas"},
    "capturas_agente": {"por_unidad": 0.0, "suelo": 120.0, "unidad": "unidades",
                        "medido_con": {"modelo": "sonnet", "esfuerzo": "low"}},
    "guia_estilo":    {"por_unidad": 8.0, "suelo": 40.0, "unidad": "fotogramas",
                       "medido_con": {"modelo": "sonnet", "esfuerzo": "low"}},
    # Mira una imagen por plano y decide: el tiempo va con los PLANOS, y en
    # tandas de 24, asi que crece a saltos pero de forma lineal.
    # Lee el guion y devuelve tres o cuatro cartelas. No mira imagenes, asi que
    # por plano cuesta mucho menos que el de arriba; lo que pesa es leerse el
    # guion entero de una vez y redactar el texto de cada cartela.
    "plan_cartelas": {"por_unidad": 0.7, "suelo": 45.0, "unidad": "planos",
                      "medido_con": {"modelo": "sonnet", "esfuerzo": "high"}},
    # Una sola llamada, pero con el guion ENTERO delante (9.000 palabras) y
    # devolviendo reparto, sitios y un beat por tramo: pesa como el guion.
    "catalogo_visual": {"por_unidad": 0.02, "suelo": 90.0,
                        "unidad": "palabras de guion",
                        "medido_con": {"modelo": "sonnet", "esfuerzo": "medium"}},
    # Una sola llamada con una tabla de frases cortas. Tiene que ser barato: si
    # analizar que se conserva costara mas que rehacerlo, nadie lo usaria.
    "conservacion": {"por_unidad": 0.6, "suelo": 25.0, "unidad": "planos dudosos",
                     "medido_con": {"modelo": "sonnet", "esfuerzo": "low"}},
}

POR_DEFECTO = {"por_unidad": 0.0, "suelo": 60.0, "unidad": "unidades"}

# Pasos cuyo tiempo lo domina una llamada al CLI: son los unicos donde tiene
# sentido ensenar un selector de modelo y esfuerzo.
PASOS_CON_CLI = ("guion", "revision_audio", "capturas_agente", "guia_estilo",
                 "catalogo_visual", "plan_cartelas", "conservacion")

_LOCK = threading.RLock()


# ------------------------------------------------------- cerrojo entre procesos

class _CerrojoFichero:
    """Cerrojo por fichero, para que dos procesos no se pisen el historico.

    La escritura es atomica (os.replace), pero el ciclo leer-modificar-escribir
    no lo es: dos procesos a la vez se pisaban a ultimo-gana y se perdian
    muestras. Con varias sesiones abiertas eso hace que el historico mienta sin
    que nadie lo note.
    """

    def __init__(self, destino, espera=5.0):
        self.senal = str(destino) + ".lock"
        self.espera = float(espera)
        self.descriptor = None

    def __enter__(self):
        limite = time.time() + self.espera
        while True:
            try:
                os.makedirs(os.path.dirname(self.senal) or ".", exist_ok=True)
                self.descriptor = os.open(
                    self.senal, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                return self
            except OSError as fallo:
                if fallo.errno not in (errno.EEXIST, errno.EACCES):
                    return self          # sin cerrojo antes que sin historico
                # un cerrojo viejo es un proceso que murio sin soltarlo
                try:
                    if time.time() - os.path.getmtime(self.senal) > 30:
                        os.remove(self.senal)
                        continue
                except OSError:
                    pass
                if time.time() >= limite:
                    return self          # se sigue: perder una muestra es menos
                time.sleep(0.05)         # malo que bloquear un paso

    def __exit__(self, *_):
        if self.descriptor is not None:
            try:
                os.close(self.descriptor)
            except OSError:
                pass
            try:
                os.remove(self.senal)
            except OSError:
                pass
        return False


# ------------------------------------------------------------------ historico

def _leer():
    try:
        with open(ruta(), "r", encoding="utf-8") as fh:
            documento = json.load(fh)
    except (OSError, ValueError):
        return {"version_formato": VERSION_FORMATO, "pasos": {}}
    if not isinstance(documento, dict) or not isinstance(documento.get("pasos"), dict):
        return {"version_formato": VERSION_FORMATO, "pasos": {}}
    documento["version_formato"] = VERSION_FORMATO
    return documento


def _escribir(documento):
    destino = ruta()
    carpeta = os.path.dirname(destino)
    os.makedirs(carpeta, exist_ok=True)
    descriptor, temporal = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as fh:
            json.dump(documento, fh, ensure_ascii=False, indent=2)
        os.replace(temporal, destino)
    except BaseException:
        if os.path.exists(temporal):
            os.remove(temporal)
        raise


def ajuste_de(registro):
    """Combinacion con la que se ejecuto, o None si el registro no la trae.

    Los registros de la version 1 no la traen: siguen valiendo para el agregado
    del paso, pero no para hablar de una combinacion concreta.
    """
    if not isinstance(registro, dict):
        return None
    directo = registro.get("ajuste")
    if isinstance(directo, dict) and directo.get("modelo"):
        return {"modelo": str(directo["modelo"]),
                "esfuerzo": str(directo.get("esfuerzo") or "")}
    detalle = registro.get("detalle")
    if isinstance(detalle, dict) and detalle.get("modelo"):
        return {"modelo": str(detalle["modelo"]),
                "esfuerzo": str(detalle.get("esfuerzo") or "")}
    return None


def clave_de(registro):
    """Clave 'modelo|esfuerzo' de un registro, o '' si no la tiene."""
    ajuste = ajuste_de(registro)
    if not ajuste:
        return ""
    return cli_claude.clave_ajuste(ajuste.get("modelo"), ajuste.get("esfuerzo"))


def _clave_pedida(ajuste):
    if not ajuste:
        return ""
    if isinstance(ajuste, str):
        return ajuste
    return cli_claude.clave_ajuste(ajuste.get("modelo"), ajuste.get("esfuerzo"))


def _recortar(historial):
    """Deja MUESTRAS_POR_AJUSTE de cada combinacion, las mas recientes.

    Recortar por paso a secas vaciaba las combinaciones poco usadas: si alguien
    prueba 'opus/high' una vez y despues hace veinte ejecuciones con 'sonnet/low',
    la unica muestra de opus desaparece y el selector se queda sin nada que decir
    justo del ajuste caro, que es del que mas falta hace saberlo.
    """
    por_clave = {}
    for registro in reversed(historial):          # de la mas nueva a la mas vieja
        clave = clave_de(registro)
        por_clave.setdefault(clave, []).append(registro)
    conservados = []
    for clave, registros in por_clave.items():
        conservados.extend(registros[:MUESTRAS_POR_AJUSTE])
    conservados.sort(key=lambda r: str(r.get("fecha") or ""))
    return conservados[-MUESTRAS_POR_PASO:]


def anotar(paso, segundos, tamano=0, ok=True, detalle=None, ajuste=None,
           proyecto=None, idioma=None, intentos=None, resultado=None,
           unidades=None):
    """Guarda lo que tardo una ejecucion real del paso, con que entrada y con que ajuste.

    Se anotan TAMBIEN las que fallan (ok=False). Antes solo se guardaba lo que
    terminaba bien, asi que una combinacion que siempre vence el plazo no dejaba
    ni rastro y el recomendador nunca podia avisar de ella: justo la informacion
    mas util que tiene el historico.
    """
    try:
        segundos = float(segundos)
    except (TypeError, ValueError):
        return None
    if segundos <= 0:
        return None
    try:
        tamano = int(tamano)
    except (TypeError, ValueError):
        tamano = 0

    registro = {
        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "segundos": round(segundos, 2),
        "tamano": max(0, tamano),
        "ok": bool(ok),
    }
    if ajuste is None and isinstance(detalle, dict) and detalle.get("modelo"):
        ajuste = {"modelo": detalle.get("modelo"),
                  "esfuerzo": detalle.get("esfuerzo")}
    if isinstance(ajuste, dict) and ajuste.get("modelo"):
        registro["ajuste"] = {
            "modelo": cli_claude.normalizar_modelo(ajuste.get("modelo"),
                                                   estricto=False),
            "esfuerzo": cli_claude.normalizar_esfuerzo(ajuste.get("esfuerzo"),
                                                       estricto=False),
        }
    # El id del proyecto y el idioma se guardan desde el principio aunque el eje
    # de idioma del grafo todavia no exista: un historico sin ellos habria que
    # tirarlo entero el dia que se anada, y las muestras cuestan ejecuciones
    # reales.
    if proyecto:
        registro["proyecto"] = str(proyecto)
    if idioma:
        registro["idioma"] = str(idioma)
    if intentos is not None:
        try:
            registro["intentos"] = max(1, int(intentos))
        except (TypeError, ValueError):
            pass
    if unidades is not None:
        try:
            registro["unidades"] = max(0, int(unidades))
        except (TypeError, ValueError):
            pass
    if resultado:
        registro["resultado"] = str(resultado)[:80]
    if isinstance(detalle, dict) and detalle:
        registro["detalle"] = detalle

    with _LOCK:
        with _CerrojoFichero(ruta()):
            documento = _leer()
            historial = documento["pasos"].setdefault(str(paso), [])
            historial.append(registro)
            documento["pasos"][str(paso)] = _recortar(historial)
            try:
                _escribir(documento)
            except OSError:
                # el historico es una ayuda, no un resultado: si no se puede
                # escribir, el paso ya ha hecho su trabajo y no debe fallar por esto
                return None
    return registro


def valorar(paso, valoracion, ajuste=None, proyecto=None, nota=None,
            tamano=0):
    """Anota lo que opino una persona del resultado de un ajuste.

    Es la unica senal de calidad que no es un proxy. El tiempo se mide solo, pero
    "esto ha quedado bien" no lo sabe nadie mas que quien lo mira, y sin eso el
    recomendador solo sabria recomendar lo mas rapido, que es justo lo que no
    hace falta recomendar.
    """
    valoracion = str(valoracion or "").strip().lower()
    if valoracion not in ("bien", "mal"):
        raise ValueError("la valoracion tiene que ser 'bien' o 'mal'")
    with _LOCK:
        with _CerrojoFichero(ruta()):
            documento = _leer()
            historial = documento["pasos"].setdefault(str(paso), [])
            clave = _clave_pedida(ajuste)
            # se cuelga de la ejecucion mas reciente de esa combinacion: es la
            # que la persona acaba de mirar
            destino = None
            for registro in reversed(historial):
                if not clave or clave_de(registro) == clave:
                    destino = registro
                    break
            if destino is None:
                return None
            destino["valoracion"] = valoracion
            if nota:
                destino["nota"] = str(nota)[:400]
            if proyecto:
                destino.setdefault("proyecto", str(proyecto))
            try:
                _escribir(documento)
            except OSError:
                return None
    return destino


def historial(paso, ajuste=None, solo_ok=False):
    """Ejecuciones guardadas de un paso, de la mas antigua a la mas reciente."""
    with _LOCK:
        registros = list(_leer()["pasos"].get(str(paso), []))
    clave = _clave_pedida(ajuste)
    if clave:
        registros = [r for r in registros if clave_de(r) == clave]
    if solo_ok:
        registros = [r for r in registros if r.get("ok")]
    return registros


def pasos_con_historial():
    """Ids de paso que tienen alguna ejecucion guardada."""
    with _LOCK:
        return sorted(_leer()["pasos"].keys())


def _mediana(valores):
    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if not ordenados:
        return 0.0
    if len(ordenados) % 2:
        return float(ordenados[mitad])
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def _parecidas(registros, tamano):
    """Ejecuciones de tamano parecido (un tercio a el triple).

    En un paso que llama a un modelo casi todo el tiempo es fijo, asi que escalar
    linealmente desde una entrada tres veces mas pequena da cifras absurdas. Solo
    cuando no hay ninguna parecida se escala por tamano, que es mejor que nada.
    """
    if not tamano:
        return []
    return [r for r in registros
            if int(r.get("tamano") or 0) > 0
            and tamano / 3.0 <= float(r["tamano"]) <= tamano * 3.0]


def _desde(registros, tamano):
    """(segundos, como) a partir de un grupo de ejecuciones, o None."""
    utiles = [r for r in registros
              if r.get("ok") and float(r.get("segundos") or 0) > 0]
    if not utiles:
        return None
    cercanas = _parecidas(utiles, tamano)
    if cercanas:
        return _mediana([float(r["segundos"]) for r in cercanas]), \
            f"{len(cercanas)} ejecucion(es) de tamano parecido", len(cercanas)
    con_tamano = [r for r in utiles if int(r.get("tamano") or 0) > 0]
    if tamano and con_tamano:
        ratio = _mediana([float(r["segundos"]) / float(r["tamano"])
                          for r in con_tamano])
        return ratio * tamano, \
            f"{len(con_tamano)} ejecucion(es) escalada(s) por tamano", len(con_tamano)
    return _mediana([float(r["segundos"]) for r in utiles]), \
        f"{len(utiles)} ejecucion(es)", len(utiles)


def estimar(paso, tamano=0, ajuste=None):
    """Segundos que se espera que tarde el paso con esa entrada y ese ajuste.

    Devuelve un dict con la cifra, de donde sale y cuantas muestras la respaldan,
    porque quien la ensena tiene que poder decir que es una estimacion y no una
    medida.

    La cadena de respaldo va de lo mas fiable a lo mas flojo, y el 'origen' dice
    siempre por donde se ha entrado:
      1. esa misma combinacion, con entradas de tamano parecido
      2. esa misma combinacion, escalada por tamano
      3. OTRA combinacion medida, reescalada por su factor relativo
      4. el agregado del paso, sin mirar la combinacion
      5. la estimacion inicial escrita a mano
    """
    try:
        tamano = max(0, int(tamano))
    except (TypeError, ValueError):
        tamano = 0

    base = INICIALES.get(str(paso), POR_DEFECTO)
    todas = historial(paso)
    clave = _clave_pedida(ajuste)
    pedido = ajuste if isinstance(ajuste, dict) else {}

    # 1 y 2: la misma combinacion
    if clave:
        mismas = [r for r in todas if clave_de(r) == clave]
        calculo = _desde(mismas, tamano)
        if calculo:
            segundos, como, muestras = calculo
            return _prevision(segundos, f"historial de {como} con este mismo ajuste",
                              muestras, base, tamano, clave)

    # 3: otra combinacion, reescalada por el factor relativo
    if clave:
        factor_pedido = cli_claude.factor(pedido.get("modelo"),
                                          pedido.get("esfuerzo"))
        mejores = None
        for otra_clave in {clave_de(r) for r in todas if clave_de(r)}:
            grupo = [r for r in todas if clave_de(r) == otra_clave]
            calculo = _desde(grupo, tamano)
            if not calculo:
                continue
            modelo, _, esfuerzo = otra_clave.partition("|")
            factor_otra = cli_claude.factor(modelo, esfuerzo)
            if factor_otra <= 0:
                continue
            candidata = (calculo[2], calculo[0] * factor_pedido / factor_otra,
                         otra_clave, calculo[2])
            if mejores is None or candidata[0] > mejores[0]:
                mejores = candidata
        if mejores:
            return _prevision(
                mejores[1],
                f"sin historial de este ajuste: escalado desde "
                f"{mejores[2].replace('|', '/')} ({mejores[3]} ejecucion(es))",
                0, base, tamano, clave)

    # 4: el agregado del paso
    calculo = _desde(todas, tamano)
    if calculo:
        segundos, como, muestras = calculo
        aviso = "historial de " + como
        if clave:
            aviso += " sin distinguir el ajuste"
        return _prevision(segundos, aviso, muestras if not clave else 0,
                          base, tamano, clave)

    # 5: la estimacion inicial, reescalada si se pide otra combinacion
    segundos = base["suelo"] + base["por_unidad"] * tamano
    origen = "estimacion inicial, sin historial todavia"
    medido_con = base.get("medido_con")
    if clave and medido_con:
        factor_base = cli_claude.factor(medido_con.get("modelo"),
                                        medido_con.get("esfuerzo"))
        factor_pedido = cli_claude.factor(pedido.get("modelo"),
                                          pedido.get("esfuerzo"))
        if factor_base > 0:
            segundos = segundos * factor_pedido / factor_base
            origen = ("estimacion inicial reescalada por el factor del ajuste, "
                      "sin historial todavia")
    return _prevision(segundos, origen, 0, base, tamano, clave)


def _prevision(segundos, origen, muestras, base, tamano, clave):
    return {"segundos": max(5.0, round(float(segundos), 1)),
            "origen": origen, "muestras": muestras,
            "unidad": base["unidad"], "tamano": tamano,
            "ajuste": clave or None,
            "medida": muestras > 0}


def reloj(segundos):
    """Segundos -> '3 min 20 s', para mensajes de progreso."""
    total = int(round(float(segundos)))
    if total < 60:
        return f"{total} s"
    minutos, resto = divmod(total, 60)
    return f"{minutos} min" + (f" {resto} s" if resto else "")


# --------------------------------------------------------------- comparativa

def resumen_ajuste(paso, modelo, esfuerzo, tamano=0):
    """Todo lo que se sabe de una combinacion en un paso."""
    clave = cli_claude.clave_ajuste(modelo, esfuerzo)
    registros = [r for r in historial(paso) if clave_de(r) == clave]
    correctas = [r for r in registros if r.get("ok")]
    fallidas = [r for r in registros if not r.get("ok")]
    con_intentos = [r for r in correctas if r.get("intentos")]
    reintentadas = [r for r in con_intentos if int(r.get("intentos") or 1) > 1]
    buenas = [r for r in registros if r.get("valoracion") == "bien"]
    malas = [r for r in registros if r.get("valoracion") == "mal"]
    prevision = estimar(paso, tamano=tamano,
                        ajuste={"modelo": modelo, "esfuerzo": esfuerzo})
    ficha = {
        "modelo": modelo,
        "esfuerzo": esfuerzo,
        "clave": clave,
        "segundos": prevision["segundos"],
        "reloj": reloj(prevision["segundos"]),
        "origen": prevision["origen"],
        "medida": prevision["medida"],
        "ejecuciones": len(registros),
        "correctas": len(correctas),
        "fallidas": len(fallidas),
        "valorada_bien": len(buenas),
        "valorada_mal": len(malas),
    }
    if registros:
        ficha["fiabilidad"] = round(len(correctas) / len(registros), 2)
    if con_intentos:
        ficha["sin_reintento"] = round(
            1.0 - len(reintentadas) / len(con_intentos), 2)
    if buenas or malas:
        ficha["aceptacion"] = round(len(buenas) / (len(buenas) + len(malas)), 2)
    tokens = [int((r.get("detalle") or {}).get("tokens_salida") or 0)
              for r in correctas]
    tokens = [t for t in tokens if t > 0]
    if tokens:
        ficha["tokens_salida"] = int(_mediana(tokens))
    return ficha


def comparativa(paso, tamano=0, modelos=None, esfuerzos=None):
    """Tabla de todas las combinaciones: lo que se espera que tarde cada una.

    Es lo que necesita el selector para que elegir un ajuste sea una decision
    informada y no una apuesta.
    """
    modelos = list(modelos or cli_claude.MODELOS)
    esfuerzos = list(esfuerzos or cli_claude.ESFUERZOS)
    filas = [resumen_ajuste(paso, modelo, esfuerzo, tamano=tamano)
             for modelo in modelos for esfuerzo in esfuerzos]
    return {
        "paso": paso,
        "tamano": tamano,
        "unidad": INICIALES.get(str(paso), POR_DEFECTO)["unidad"],
        "ajustes": filas,
        "aviso": ("estimacion, no medida, salvo en las filas que declaran "
                  "ejecuciones propias"),
    }


def recomendacion(paso, tamano=0, modelos=None, esfuerzos=None):
    """Que ajuste conviene para este paso, y por que.

    Criterio, en este orden:
      - se descartan las combinaciones que fallan mas de lo que aciertan
      - entre las que alguien ha valorado bien, gana la mas rapida
      - si nadie ha valorado nada, se recomienda la mas usada con exito
      - y si no hay historial suficiente, se dice que no hay datos, en vez de
        inventar una recomendacion que parezca medida

    Nunca recomienda por tiempo a secas: lo mas rapido siempre seria 'haiku/low'
    y eso no es una recomendacion, es una tautologia.
    """
    tabla = comparativa(paso, tamano=tamano, modelos=modelos, esfuerzos=esfuerzos)
    filas = tabla["ajustes"]
    con_datos = [f for f in filas if f["ejecuciones"] > 0]

    fiables = [f for f in con_datos
               if f.get("fiabilidad", 1.0) >= 0.5 and f["correctas"] > 0]
    descartadas = [f"{f['modelo']}/{f['esfuerzo']}"
                   for f in con_datos if f not in fiables]

    valoradas = [f for f in fiables if f.get("aceptacion") is not None]
    aprobadas = [f for f in valoradas if f["aceptacion"] >= 0.5]

    elegida, motivo, confianza = None, "", "ninguna"
    if aprobadas:
        elegida = min(aprobadas, key=lambda f: f["segundos"])
        motivo = (f"la mas rapida de las que has valorado bien "
                  f"({elegida['valorada_bien']} de "
                  f"{elegida['valorada_bien'] + elegida['valorada_mal']} veces), "
                  f"unos {elegida['reloj']}")
        confianza = "alta" if elegida["ejecuciones"] >= 3 else "media"
    elif fiables:
        elegida = max(fiables, key=lambda f: (f["correctas"], -f["segundos"]))
        motivo = (f"es la que mas veces ha terminado bien "
                  f"({elegida['correctas']} de {elegida['ejecuciones']}), unos "
                  f"{elegida['reloj']}. Nadie ha valorado todavia el resultado, "
                  f"asi que esto habla de que funciona, no de que quede mejor")
        confianza = "media" if elegida["correctas"] >= 3 else "baja"
    else:
        motivo = ("todavia no hay ejecuciones suficientes de este paso para "
                  "recomendar nada. Se mantiene el ajuste por defecto")

    salida = {
        "paso": paso,
        "tamano": tamano,
        "hay_datos": bool(con_datos),
        "ejecuciones_totales": sum(f["ejecuciones"] for f in filas),
        "motivo": motivo,
        "confianza": confianza,
        "descartadas": descartadas,
    }
    if elegida:
        salida["ajuste"] = {"modelo": elegida["modelo"],
                            "esfuerzo": elegida["esfuerzo"]}
        salida["segundos"] = elegida["segundos"]
        salida["reloj"] = elegida["reloj"]
    else:
        salida["ajuste"] = dict(cli_claude.catalogo()["por_defecto"])
    return salida


def panorama(tamanos=None):
    """Resumen del historico de todos los pasos, para la pantalla de ajustes."""
    tamanos = tamanos or {}
    pasos = {}
    for paso in sorted(set(list(INICIALES) + pasos_con_historial())):
        registros = historial(paso)
        ficha = {
            "paso": paso,
            "usa_cli": paso in PASOS_CON_CLI,
            "ejecuciones": len(registros),
            "correctas": sum(1 for r in registros if r.get("ok")),
            "proyectos": len({r.get("proyecto") for r in registros
                              if r.get("proyecto")}),
            "unidad": INICIALES.get(paso, POR_DEFECTO)["unidad"],
        }
        if registros:
            ficha["ultima"] = registros[-1].get("fecha")
            correctas = [float(r["segundos"]) for r in registros if r.get("ok")]
            if correctas:
                ficha["mediana_s"] = round(_mediana(correctas), 1)
                ficha["mediana"] = reloj(_mediana(correctas))
        if paso in PASOS_CON_CLI:
            ficha["recomendacion"] = recomendacion(
                paso, tamano=int(tamanos.get(paso) or 0))
        pasos[paso] = ficha
    return {"pasos": pasos,
            "fichero": ruta(),
            "muestras_por_ajuste": MUESTRAS_POR_AJUSTE}


# -------------------------------------------------------------------- avance

# ------------------------------------------------------------------- avisar
#
# UN CONTADOR DE VERDAD EN LA BARRA. Los pasos que trabajan pieza a pieza
# --dibujar un plano, mirar un plano, renderizarlo-- saben exactamente por
# cuantos van, y esa cuenta se perdia por el camino: la barra publica decia
# «Revisando lo que se ve - comparando la imagen con lo que se cuenta», que es
# una frase elegida por tramos de la fraccion, no algo medido. Con doscientos
# dieciseis planos delante, «34 de 216» dice cuanto queda; la frase no dice nada.
#
# El contador viaja como TERCER argumento de `avisar` y no dentro del mensaje,
# porque el mensaje es de casa y el publico se compone aparte (ver
# `recetas.publico_de`): meterlo en el texto obligaria a volver a sacarlo con una
# expresion regular, que es la forma de que un dia deje de casar en silencio.


def avisador(avisar):
    """Deja `avisar` en algo que SIEMPRE acepta (fraccion, mensaje, unidades).

    Quien escucha puede ser el servicio --que sabe de unidades--, el doble de una
    suite --`lambda v, m="": v`, que no-- o nada. En vez de que cada bucle
    averigue a quien tiene delante en cada vuelta, se envuelve UNA vez aqui.

    'unidades' es (hechas, total). Si el de fuera no las entiende se le avisa sin
    ellas y no se entera: perder el contador es peor barra, pero reventar el paso
    por adornar la barra seria mucho peor.
    """
    if avisar is None:
        return lambda *a, **k: None
    try:
        parametros = inspect.signature(avisar).parameters.values()
    except (TypeError, ValueError):          # un callable sin firma legible
        return lambda fraccion, mensaje="", unidades=None: avisar(fraccion, mensaje)
    if (len(parametros) >= 3
            or any(par.kind in (par.VAR_POSITIONAL, par.VAR_KEYWORD)
                   for par in parametros)):
        return avisar

    def sin_unidades(fraccion, mensaje="", unidades=None):
        return avisar(fraccion, mensaje)

    return sin_unidades


class Avance:
    """Empuja el progreso con el reloj contra una estimacion, en su propio hilo.

    Se para en 'hasta' si la estimacion se queda corta: pasado ese punto solo
    cambia el mensaje, para que se vea que sigue trabajando sin fingir que ya
    esta. Si alguien cancela el trabajo, avisar() lanza y esto lo detecta: se
    marca cancelado y se avisa a quien tenga que cortar el proceso de fuera.
    """

    def __init__(self, avisar, desde, hasta, prevision, mensaje,
                 al_cancelar=None, cadencia=2.0):
        self.avisar = avisar
        self.desde = float(desde)
        self.hasta = float(hasta)
        self.prevision = prevision if isinstance(prevision, dict) else {"segundos": float(prevision or 60), "origen": "estimacion"}
        self.mensaje = str(mensaje)
        self.al_cancelar = al_cancelar
        self.cadencia = float(cadencia)
        self.cancelado = False
        self.inicio = time.time()
        self._parar = threading.Event()
        self._hilo = None

    @property
    def segundos(self):
        return time.time() - self.inicio

    def texto(self):
        """Mensaje honesto: lo que lleva, lo que se estimo y que es estimacion."""
        estimado = float(self.prevision.get("segundos") or 60.0)
        transcurrido = self.segundos
        origen = self.prevision.get("origen", "estimacion")
        if transcurrido >= estimado:
            return (f"{self.mensaje}; lleva {reloj(transcurrido)} y se estimaron "
                    f"{reloj(estimado)}: sigue esperando la respuesta "
                    f"(estimacion, no medida: {origen})")
        return (f"{self.mensaje}; {reloj(transcurrido)} de {reloj(estimado)} "
                f"(estimacion, no medida: {origen})")

    def valor(self):
        estimado = max(1.0, float(self.prevision.get("segundos") or 60.0))
        avance = min(1.0, self.segundos / estimado)
        return self.desde + (self.hasta - self.desde) * avance

    def _latir(self):
        while not self._parar.wait(self.cadencia):
            try:
                self.avisar(self.valor(), self.texto())
            except BaseException:  # noqa: BLE001
                # avisar() lanza Cancelado cuando el usuario cancela el trabajo;
                # el hilo principal esta bloqueado en el subproceso y no se
                # entera, asi que hay que sacarlo de ahi desde aqui
                self.cancelado = True
                if callable(self.al_cancelar):
                    try:
                        self.al_cancelar()
                    except Exception:  # noqa: BLE001
                        pass
                return

    def arrancar(self):
        self.inicio = time.time()
        self.avisar(self.desde, self.texto())
        self._hilo = threading.Thread(target=self._latir, daemon=True,
                                      name="avance-estimado")
        self._hilo.start()
        return self

    def parar(self):
        """Detiene el hilo y devuelve los segundos reales que se han tardado."""
        self._parar.set()
        if self._hilo is not None:
            self._hilo.join(timeout=self.cadencia + 1.0)
        return self.segundos

    def __enter__(self):
        return self.arrancar()

    def __exit__(self, *_):
        self.parar()
        return False
