"""
Bitacora del Estudio de Video: historial append-only de todo lo que pasa.

Cada evento se escribe como una linea JSON en <proyecto>/bitacora.jsonl y, con
el proyecto anotado, en C:\\IA\\estudio\\bitacora_global.jsonl. Nada se
sobreescribe nunca: es el registro del que aprenden los agentes.

    b = Bitacora(proyecto)
    b.anotar("regenerado", "assets", {"motivo": "cara rara"}, unidad="S03")
    b.leer(paso="assets", limite=20)
    print(b.resumen_para_llm())
"""
import json
import os
import threading

try:
    from .proyecto import ahora, leer_jsonl
    from .estado import PASOS, PASOS_POR_ID
except ImportError:  # ejecutado con la carpeta nucleo directamente en sys.path
    from proyecto import ahora, leer_jsonl
    from estado import PASOS, PASOS_POR_ID

NOMBRE_BITACORA = "bitacora.jsonl"
#: Redirigible con ESTUDIO_BITACORA_GLOBAL: en el servidor cada cuenta tiene la
#: suya, y una bitacora compartida mezclaria dos historiales que no se conocen.
RUTA_GLOBAL = os.environ.get("ESTUDIO_BITACORA_GLOBAL") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bitacora_global.jsonl",
)

_ESCRITURA = threading.Lock()


def _linea(ruta, registro):
    carpeta = os.path.dirname(os.path.abspath(ruta))
    os.makedirs(carpeta, exist_ok=True)
    with open(ruta, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")


def anotar_global(evento, datos=None, proyecto=None):
    """Anota SOLO en el log global, sin proyecto vivo detras.

    Existe por el borrado definitivo: cuando la carpeta del proyecto ya no esta,
    su bitacora se ha ido con ella, y el unico sitio donde puede quedar
    constancia de que existio y de que alguien lo borro a proposito es el log
    global. Escribir ahi el evento es lo que hace que un proyecto que desaparece
    no desaparezca tambien del historial.
    """
    registro = {
        "fecha": ahora(),
        "evento": str(evento),
        "paso": None,
        "unidad": None,
        "datos": datos if isinstance(datos, dict) else ({} if datos is None else {"valor": datos}),
        "proyecto": proyecto,
        "raiz": None,
    }
    with _ESCRITURA:
        _linea(RUTA_GLOBAL, registro)
    return registro


def _resumir_datos(datos, limite=200):
    if not isinstance(datos, dict) or not datos:
        return ""
    trozos = []
    for clave in sorted(datos):
        valor = datos[clave]
        if isinstance(valor, (dict, list)):
            texto = json.dumps(valor, ensure_ascii=False, default=str)
        else:
            texto = str(valor)
        texto = " ".join(texto.split())
        if len(texto) > 80:
            texto = texto[:77] + "..."
        trozos.append(f"{clave}={texto}")
    salida = ", ".join(trozos)
    if len(salida) > limite:
        salida = salida[:limite - 3] + "..."
    return salida


class Bitacora:
    """Historial estructurado de un proyecto, replicado en el log global."""

    def __init__(self, proyecto):
        self.proyecto = proyecto
        self.ruta = proyecto.ruta(NOMBRE_BITACORA)
        self.ruta_global = RUTA_GLOBAL

    def anotar(self, evento, paso, datos=None, unidad=None):
        """Registra un evento; devuelve el registro escrito."""
        registro = {
            "fecha": ahora(),
            "evento": str(evento),
            "paso": str(paso) if paso else None,
            "unidad": str(unidad) if unidad else None,
            "datos": datos if isinstance(datos, dict) else ({} if datos is None else {"valor": datos}),
        }
        with _ESCRITURA:
            _linea(self.ruta, registro)
            global_registro = dict(registro)
            global_registro["proyecto"] = self.proyecto.id
            global_registro["raiz"] = self.proyecto.raiz
            _linea(self.ruta_global, global_registro)
        return registro

    def leer(self, paso=None, unidad=None, limite=None):
        """Eventos del proyecto en orden cronologico, filtrables."""
        registros = leer_jsonl(self.ruta)
        if paso is not None:
            registros = [r for r in registros if r.get("paso") == paso]
        if unidad is not None:
            registros = [r for r in registros if r.get("unidad") == unidad]
        if limite is not None and limite > 0:
            registros = registros[-int(limite):]
        return registros

    def eventos_globales(self, proyecto=None, limite=None):
        """Eventos del log global, opcionalmente de un solo proyecto."""
        registros = leer_jsonl(self.ruta_global)
        if proyecto is not None:
            registros = [r for r in registros if r.get("proyecto") == proyecto]
        if limite is not None and limite > 0:
            registros = registros[-int(limite):]
        return registros

    def resumen_para_llm(self):
        """Historial del video en texto navegable, agrupado por paso y unidad."""
        registros = self.leer()
        nombre = self.proyecto.config.get("nombre", self.proyecto.id)
        lineas = [f"BITACORA DEL PROYECTO {self.proyecto.id} ({nombre})",
                  f"raiz: {self.proyecto.raiz}"]
        if not registros:
            lineas.append("eventos: 0 (proyecto sin historial todavia)")
            return "\n".join(lineas)

        lineas.append(f"eventos: {len(registros)}  "
                      f"desde {registros[0].get('fecha', '?')} "
                      f"hasta {registros[-1].get('fecha', '?')}")

        orden = [p["id"] for p in PASOS]
        sueltos = [r.get("paso") for r in registros if r.get("paso") not in PASOS_POR_ID]
        for extra in sueltos:
            if extra not in orden:
                orden.append(extra)

        for paso_id in orden:
            del_paso = [r for r in registros if r.get("paso") == paso_id]
            if not del_paso:
                continue
            titulo = PASOS_POR_ID.get(paso_id, {}).get("nombre", str(paso_id))
            lineas.append("")
            lineas.append(f"== {paso_id} ({titulo}) - {len(del_paso)} eventos ==")
            generales = [r for r in del_paso if not r.get("unidad")]
            for registro in generales:
                lineas.append("  " + self._linea_evento(registro))
            unidades = sorted({r["unidad"] for r in del_paso if r.get("unidad")})
            for unidad in unidades:
                de_unidad = [r for r in del_paso if r.get("unidad") == unidad]
                lineas.append(f"  [{unidad}] {len(de_unidad)} eventos")
                for registro in de_unidad:
                    lineas.append("    " + self._linea_evento(registro))
        return "\n".join(lineas)

    def _linea_evento(self, registro):
        detalle = _resumir_datos(registro.get("datos"))
        base = f"{registro.get('fecha', '?')}  {registro.get('evento', '?')}"
        return f"{base}  {detalle}".rstrip()
