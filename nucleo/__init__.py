"""
Nucleo del Estudio de Video.

    from nucleo import Proyecto, Estado, Bitacora, GestorTrabajos, PASOS

    p = Proyecto.crear(r"C:\\IA\\estudio\\proyectos", "Caso Meridiano")
    e = Estado(p)
    b = Bitacora(p)
    g = GestorTrabajos(estado=e, bitacora=b)

Cuatro piezas y nada mas:
  proyecto  carpeta en disco, configuracion y rutas de pasos versionados
  estado    grafo de build con firmas, versiones y granularidad por unidad
  bitacora  historial append-only del proyecto y global
  trabajos  ejecucion en hilos con progreso consultable
"""
from .proyecto import (Cerrojo, Proyecto, ahora, escribir_json, identificador,
                       leer_json, lock_de, ruta_contenida)
from .estado import (Estado, PASOS, PASOS_POR_ID, ESTADOS, dependientes_de,
                     descendientes_de)
from .bitacora import Bitacora, RUTA_GLOBAL
from .trabajos import GestorTrabajos, Cancelado

__all__ = [
    "Proyecto", "Estado", "Bitacora", "GestorTrabajos", "Cancelado",
    "PASOS", "PASOS_POR_ID", "ESTADOS", "RUTA_GLOBAL", "Cerrojo",
    "dependientes_de", "descendientes_de", "ruta_contenida",
    "ahora", "escribir_json", "leer_json", "lock_de", "identificador",
]
