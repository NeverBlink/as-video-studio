"""
Capturas anotables de los pasos 7 (callouts) y 8 (render).

El feedback por escena no puede expresar un problema que solo existe en un
instante: un plano de 6 s con un zoom lento puede estar bien al empezar y mal al
acabar. Por eso aqui la unidad de feedback no es la escena, es
(escena, segundo exacto).

El navegador compone el fotograma -- reconstruido con la misma matematica del
reproductor en callouts, o dibujando el <video> en un canvas en render -- y este
modulo guarda el PNG con su anotacion:

    almacen = Almacen(proyecto)
    ficha = almacen.crear("callouts", "S003", png, trazos=[...],
                          comentario="el rotulo pisa la grua",
                          t_video=14.62, t_escena=2.18)

Al aplicarlas, cada captura se traduce a instruccion para su escena (comentario
literal + zonas de los trazos + contexto temporal) y varias capturas de la misma
escena se agrupan en UNA sola instruccion ordenada por instante, para no lanzar
regeneraciones encadenadas de la misma unidad.

Invalidacion: una captura afecta a la unidad escena:<id> de SU paso; el nucleo
MARCA en cascada esa misma escena aguas abajo. Nunca el paso entero, y nunca
generando: marcar y generar dejaron de ser lo mismo el 23-08 (PENDIENTE 30). Lo
que queda obsoleto se acciona desde la pantalla, con su cuenta y su coste
delante.
"""
import json
import os
import re
import shutil

try:
    from .proyecto import (Proyecto, ahora, escribir_json, leer_json, lock_de,
                           ruta_contenida)
except ImportError:  # ejecutado con la carpeta nucleo directamente en sys.path
    from proyecto import (Proyecto, ahora, escribir_json, leer_json, lock_de,
                          ruta_contenida)

CARPETA = "capturas"
INDICE = "capturas.json"
PASOS_CON_CAPTURA = ("callouts", "render")
FIRMA_PNG = b"\x89PNG\r\n\x1a\n"
LIMITE_PNG = 24 * 1024 * 1024
ID_ESCENA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
ID_CAPTURA = re.compile(r"^cap_\d{4,}$")


class ErrorCaptura(ValueError):
    """Captura mal formada. El mensaje esta pensado para que lo lea un humano."""


# --------------------------------------------------------------- validacion

def validar_paso(paso):
    """Solo callouts y render tienen reproductor del que capturar."""
    paso = str(paso or "").strip()
    if paso not in PASOS_CON_CAPTURA:
        raise ErrorCaptura(
            f"el paso '{paso}' no tiene reproductor: la captura anotable es de "
            + " y ".join(PASOS_CON_CAPTURA))
    return paso


def _validar_escena(escena):
    escena = str(escena or "").strip()
    if not ID_ESCENA.match(escena):
        raise ErrorCaptura(f"id de escena invalido: {escena!r}")
    return escena


def segundos(valor, nombre="instante", obligatorio=False):
    if valor is None or valor == "":
        if obligatorio:
            raise ErrorCaptura(f"falta '{nombre}'")
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        raise ErrorCaptura(f"'{nombre}' debe ser un numero de segundos, "
                           f"llego {valor!r}")
    if numero < 0 or numero != numero:
        raise ErrorCaptura(f"'{nombre}' no puede ser negativo: {valor!r}")
    return round(numero, 3)


def normalizar_trazos(crudos):
    """Trazos del canvas -> forma canonica con puntos en 0..1.

    Se normalizan (y se recortan al cuadro) porque la anotacion tiene que
    seguir siendo valida a cualquier tamano de pantalla, igual que en el resto
    de paneles del estudio.
    """
    if crudos in (None, ""):
        return []
    if isinstance(crudos, str):
        try:
            crudos = json.loads(crudos)
        except ValueError as fallo:
            raise ErrorCaptura(f"'trazos' no es JSON valido: {fallo}")
    if not isinstance(crudos, list):
        raise ErrorCaptura("'trazos' debe ser una lista")
    limpios = []
    for trazo in crudos:
        if not isinstance(trazo, dict):
            raise ErrorCaptura("cada trazo debe ser un objeto con 'puntos'")
        puntos = []
        for punto in trazo.get("puntos") or []:
            if isinstance(punto, dict):
                x, y = punto.get("x"), punto.get("y")
            elif isinstance(punto, (list, tuple)) and len(punto) >= 2:
                x, y = punto[0], punto[1]
            else:
                raise ErrorCaptura("cada punto es {'x':0..1,'y':0..1}")
            try:
                x, y = float(x), float(y)
            except (TypeError, ValueError):
                raise ErrorCaptura(f"punto no numerico: {punto!r}")
            puntos.append({"x": round(min(max(x, 0.0), 1.0), 5),
                           "y": round(min(max(y, 0.0), 1.0), 5)})
        if not puntos:
            continue
        ficha = {"color": str(trazo.get("color") or "#d4785a"),
                 "grosor": int(trazo.get("grosor") or 4),
                 "puntos": puntos}
        limpios.append(ficha)
    return limpios


def _validar_png(imagen):
    if isinstance(imagen, str):
        crudo = imagen.strip()
        if crudo.startswith("data:"):
            crudo = crudo.split(",", 1)[-1]
        import base64
        try:
            imagen = base64.b64decode(crudo, validate=False)
        except Exception as fallo:  # noqa: BLE001
            raise ErrorCaptura(f"la imagen en base64 no se puede decodificar: {fallo}")
    if not isinstance(imagen, (bytes, bytearray)):
        raise ErrorCaptura("la imagen debe llegar como PNG (multipart o base64)")
    imagen = bytes(imagen)
    if not imagen:
        raise ErrorCaptura("la imagen llego vacia")
    if len(imagen) > LIMITE_PNG:
        raise ErrorCaptura(f"la captura pesa {len(imagen) // 1024} KB, "
                           f"el limite son {LIMITE_PNG // 1024} KB")
    if not imagen.startswith(FIRMA_PNG):
        raise ErrorCaptura("la captura tiene que ser un PNG "
                           "(el fotograma se compone en un canvas y se sube en PNG)")
    return imagen


# ----------------------------------------------------------------- almacen

class Almacen:
    """Capturas de un proyecto: PNG en capturas/ e indice en capturas.json."""

    def __init__(self, proyecto):
        if isinstance(proyecto, str):
            proyecto = Proyecto(proyecto)
        self.proyecto = proyecto
        self.carpeta = proyecto.ruta(CARPETA)
        self.indice = os.path.join(self.carpeta, INDICE)

    def __repr__(self):
        return f"<Capturas {self.proyecto.id}>"

    # ------------------------------------------------------------- interno

    def _leer(self):
        datos = leer_json(self.indice)
        if not isinstance(datos, dict) or not isinstance(datos.get("capturas"), list):
            return {"version": 1, "capturas": []}
        return datos

    def _guardar(self, datos):
        datos["actualizado"] = ahora()
        escribir_json(self.indice, datos)

    def ruta_imagen(self, ficha):
        """Ruta absoluta del PNG de una captura."""
        relativa = ficha.get("imagen") if isinstance(ficha, dict) else str(ficha)
        return ruta_contenida(self.proyecto.raiz, str(relativa or ""))

    # ------------------------------------------------------------ escritura

    def crear(self, paso, escena, imagen, trazos=None, comentario="",
              t_video=None, t_escena=None, contexto=None):
        """Guarda una captura con su anotacion y devuelve su ficha."""
        paso = validar_paso(paso)
        escena = _validar_escena(escena)
        datos_png = _validar_png(imagen)
        trazos = normalizar_trazos(trazos)
        comentario = str(comentario or "").strip()
        if not comentario and not trazos:
            raise ErrorCaptura("una captura sin comentario y sin trazos no dice "
                               "nada: escribe la nota o pinta encima")
        t_video = segundos(t_video, "t_video")
        t_escena = segundos(t_escena, "t_escena")
        if t_video is None and t_escena is None:
            raise ErrorCaptura("hace falta 't_video' o 't_escena': una captura "
                               "sin instante no se puede situar en el plano")

        os.makedirs(self.carpeta, exist_ok=True)
        with lock_de(self.indice):
            datos = self._leer()
            numero = max([_numero_de(c.get("id")) for c in datos["capturas"]]
                         or [0]) + 1
            cid = f"cap_{numero:04d}"
            nombre = f"{cid}.png"
            with open(os.path.join(self.carpeta, nombre), "wb") as fh:
                fh.write(datos_png)
            ficha = {
                "id": cid,
                "paso": paso,
                "escena": escena,
                "unidad": f"escena:{escena}",
                "t_video": t_video,
                "t_escena": t_escena,
                "imagen": f"{CARPETA}/{nombre}",
                "trazos": trazos,
                "comentario": comentario,
                "creada": ahora(),
                "aplicada": None,
                "trabajo": None,
                "bytes": len(datos_png),
            }
            if isinstance(contexto, dict) and contexto:
                ficha["contexto"] = contexto
            datos["capturas"].append(ficha)
            self._guardar(datos)
        return dict(ficha)

    def borrar(self, cid):
        """Borra una captura y su PNG. Devuelve la ficha borrada."""
        cid = str(cid or "")
        if not ID_CAPTURA.match(cid):
            raise ErrorCaptura(f"id de captura invalido: {cid!r}")
        with lock_de(self.indice):
            datos = self._leer()
            quedan = [c for c in datos["capturas"] if c.get("id") != cid]
            if len(quedan) == len(datos["capturas"]):
                return None
            borrada = next(c for c in datos["capturas"] if c.get("id") == cid)
            datos["capturas"] = quedan
            self._guardar(datos)
        ruta = self.ruta_imagen(borrada)
        if os.path.exists(ruta):
            os.remove(ruta)
        return borrada

    def marcar_aplicadas(self, ids, trabajo=None, instruccion=None):
        """Anota que capturas ya se aplicaron y en que trabajo."""
        pedidos = {str(i) for i in (ids or [])}
        marca = ahora()
        with lock_de(self.indice):
            datos = self._leer()
            tocadas = []
            for ficha in datos["capturas"]:
                if ficha.get("id") in pedidos:
                    ficha["aplicada"] = marca
                    ficha["trabajo"] = trabajo
                    if instruccion:
                        ficha["instruccion"] = instruccion
                    tocadas.append(ficha["id"])
            self._guardar(datos)
        return tocadas

    # -------------------------------------------------------------- lectura

    def listar(self, paso=None, escena=None, pendientes=None):
        """Capturas del proyecto, de la mas antigua a la mas reciente."""
        fichas = list(self._leer()["capturas"])
        if paso:
            fichas = [f for f in fichas if f.get("paso") == str(paso)]
        if escena:
            escena = str(escena)
            fichas = [f for f in fichas
                      if f.get("escena") == escena or f.get("unidad") == escena]
        if pendientes is True:
            fichas = [f for f in fichas if not f.get("aplicada")]
        elif pendientes is False:
            fichas = [f for f in fichas if f.get("aplicada")]
        fichas.sort(key=lambda f: (str(f.get("creada") or ""), str(f.get("id"))))
        return fichas

    def obtener(self, cid):
        """Ficha de una captura, o None."""
        for ficha in self._leer()["capturas"]:
            if ficha.get("id") == str(cid):
                return ficha
        return None

    def obtener_varias(self, ids):
        """Fichas de varias capturas, en el orden pedido. Falla si falta alguna."""
        indice = {f["id"]: f for f in self._leer()["capturas"] if f.get("id")}
        fichas, faltan = [], []
        for cid in ids or []:
            ficha = indice.get(str(cid))
            if ficha is None:
                faltan.append(str(cid))
            else:
                fichas.append(ficha)
        if faltan:
            raise ErrorCaptura(f"capturas desconocidas: {', '.join(faltan)}")
        return fichas

    def limpiar(self):
        """Borra todas las capturas del proyecto (util en pruebas)."""
        shutil.rmtree(self.carpeta, ignore_errors=True)


def _numero_de(cid):
    encaje = re.search(r"(\d+)", str(cid or ""))
    return int(encaje.group(1)) if encaje else 0


# ------------------------------------------------------------- instruccion

def _coma(numero, decimales=1):
    """2.18 -> '2,2'. El texto lo lee un humano y lo lee un modelo en espanol."""
    if numero is None:
        return "?"
    return f"{float(numero):.{decimales}f}".replace(".", ",")


def describir_trazos(trazos, describir=None):
    """Trazos -> frase de zonas, con el motor de revision del sistema.

    Se usa el mismo motor que el resto del feedback dibujado: el generador no
    entiende un canvas, entiende 'la zona superior derecha'.
    """
    if not trazos:
        return ""
    if describir is None:
        try:
            from pasos import comun
            describir = comun.cargar_motor("revision", "regenerar.py").describir_trazos
        except Exception:  # noqa: BLE001
            # el motor arrastra el de imagen: si no carga, la nota no se pierde,
            # solo se queda sin la frase de zonas
            return ""
    try:
        return str(describir(trazos) or "")
    except Exception:  # noqa: BLE001
        return ""


def frase_temporal(captura):
    """El instante de la captura, dicho como se lo damos a quien regenera.

    Sin esto, una nota sobre algo que solo ocurre al final del movimiento se
    interpreta como si valiera para todo el plano.
    """
    contexto = captura.get("contexto") if isinstance(captura, dict) else None
    contexto = contexto if isinstance(contexto, dict) else {}
    if contexto.get("frase"):
        return str(contexto["frase"])
    t_escena = captura.get("t_escena")
    if t_escena is None:
        return f"el problema aparece a {_coma(captura.get('t_video'))} s de video"
    return f"el problema aparece a {_coma(t_escena)} s del plano"


def instruccion_de(capturas, describir=None):
    """Varias capturas de la MISMA escena -> una sola instruccion ordenada.

    Se agrupan a proposito: aplicarlas una a una lanzaria regeneraciones
    encadenadas de la misma unidad, cada una sin saber lo que pedia la anterior.
    """
    capturas = ordenar(capturas)
    if not capturas:
        return ""
    primera = capturas[0]
    lineas = [f"Correccion pedida sobre el plano {primera.get('escena')} "
              f"desde el reproductor de {primera.get('paso')}: "
              f"{len(capturas)} captura(s) anotada(s), en orden de instante."]
    for numero, captura in enumerate(capturas, start=1):
        lineas.append("")
        lineas.append(f"{numero}. {frase_temporal(captura)}.")
        comentario = str(captura.get("comentario") or "").strip()
        if comentario:
            lineas.append(f'   Nota del revisor: "{comentario}"')
        zonas = describir_trazos(captura.get("trazos"), describir)
        if zonas:
            lineas.append(f"   {zonas}")
        lineas.append(f"   Captura: {captura.get('imagen')}")
    return "\n".join(lineas)


def ordenar(capturas):
    """Capturas por instante, que es el orden en que se ven en el video."""
    def clave(captura):
        instante = captura.get("t_escena")
        if instante is None:
            instante = captura.get("t_video")
        return (float(instante or 0.0), str(captura.get("id") or ""))
    return sorted(capturas or [], key=clave)


def agrupar(capturas):
    """{(paso, escena): [capturas]}, cada grupo ordenado por instante."""
    grupos = {}
    for captura in capturas or []:
        clave = (captura.get("paso"), captura.get("escena"))
        grupos.setdefault(clave, []).append(captura)
    return {clave: ordenar(fichas) for clave, fichas in grupos.items()}


# --------------------------------------------------------------- aplicacion

def aplicar(estado, capturas, zonas=None, modo="directo", describir=None):
    """Traduce las capturas a feedback por unidad y marca lo que hay que rehacer.

    Devuelve un grupo por (paso, escena) con la instruccion y la unidad tocada.
    No lanza nada: quien llama decide como se regenera (directo o con agente).
    """
    modo = str(modo or "directo").strip().lower()
    if modo not in ("directo", "agente"):
        raise ErrorCaptura(f"modo desconocido: {modo!r}. Usa 'directo' o 'agente'")
    zonas = zonas if isinstance(zonas, dict) else {}
    grupos = []
    for (paso, escena), fichas in sorted(agrupar(capturas).items()):
        paso = validar_paso(paso)
        unidad = f"escena:{escena}"
        instruccion = instruccion_de(fichas, describir)
        nota = {
            "id": f"C{fichas[0]['id'][4:]}",
            "fecha": ahora(),
            "origen": "captura",
            "modo": modo,
            "capturas": [f["id"] for f in fichas],
            "imagenes": [f.get("imagen") for f in fichas],
            "instantes": [{"captura": f["id"], "t_video": f.get("t_video"),
                           "t_escena": f.get("t_escena")} for f in fichas],
            "texto": instruccion,
        }
        evitar = []
        for ficha in fichas:
            evitar.extend(zonas.get(ficha["id"]) or [])

        params = estado.params(paso)
        bloque = (params.get("unidades") or {}).get(unidad)
        bloque = dict(bloque) if isinstance(bloque, dict) else {}
        historial = bloque.get("feedback")
        historial = list(historial) if isinstance(historial, list) else []
        historial.append(nota)
        bloque["feedback"] = historial
        if evitar:
            # las zonas marcadas son coordenadas del plano, ya convertidas desde
            # el instante de la captura: el paso 7 las trata como ocupadas al
            # colocar, que es lo que hace que la correccion cambie el resultado
            previas = bloque.get("evitar")
            previas = list(previas) if isinstance(previas, list) else []
            bloque["evitar"] = previas + evitar
        estado.actualizar_params(paso, {"unidades": {unidad: bloque}})
        # el cambio de params ya deja la unidad obsoleta, pero invalidarla
        # ademas cubre el caso de la misma nota repetida, que no mueve la firma
        estado.invalidar_unidades(paso, [unidad])
        grupos.append({"paso": paso, "escena": escena, "unidad": unidad,
                       "capturas": [f["id"] for f in fichas],
                       "instruccion": instruccion, "nota": nota,
                       "zonas": evitar})
    return grupos
