"""Foto comparable del estado de un proyecto, para cotejar dos maquinas.

Imprime JSON en una linea por si se quiere diffear, y ademas comprueba lo que
una mudanza puede romper sin que se note en la pantalla: que los ficheros que
el estado dice haber producido **estan de verdad ahi**. Una ruta mal mudada no
da ningun error al abrir el proyecto -- se ve al pedir la miniatura, y ya con
el video montado.

    python herramientas/foto_proyecto.py <carpeta> [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from nucleo.proyecto import Proyecto            # noqa: E402
from nucleo.estado import Estado, PASOS         # noqa: E402


def _rutas(dato, acc):
    """Toda cadena que parezca una ruta absoluta, de Windows o de POSIX."""
    if isinstance(dato, dict):
        for v in dato.values():
            _rutas(v, acc)
    elif isinstance(dato, list):
        for v in dato:
            _rutas(v, acc)
    elif isinstance(dato, str) and dato:
        if dato.startswith("/") or (len(dato) > 2 and dato[1] == ":"
                                    and dato[2] in "\\/"):
            acc.append(dato)
    return acc


def foto(carpeta):
    estado = Estado(Proyecto(carpeta))
    doc = estado._doc
    salida = {"proyecto": os.path.basename(os.path.abspath(carpeta)), "pasos": {}}

    # `trabajo/` es la carpeta de paso: `medios.sembrar_trabajo` la siembra y
    # `_recoger_trabajo` la vuelca en la version siguiente, asi que el estado
    # guarda rutas suyas que ya no existen. Pasa igual en la maquina de origen
    # --medido en «Video sobre el oro»: 916 de 945-- y por eso se cuentan
    # aparte: lo que delata una mudanza mal hecha es que falte algo PERSISTENTE.
    faltan, faltan_trabajo, comprobadas = [], [], 0
    for paso in PASOS:
        pid = paso["id"]
        datos = doc["pasos"][pid]
        salida["pasos"][pid] = {
            "estado": estado.estado_de(pid),
            "activa": datos.get("activa"),
            "versiones": len(datos.get("versiones") or []),
            "unidades": len(datos.get("unidades") or {}),
            "obsoletas": len(estado._unidades_obsoletas(pid)),
            "invalidadas": len(datos.get("invalidadas") or []),
            "declaradas": len(estado._declaradas(pid)),
        }
        # los ficheros que dice haber producido, y las referencias de entrada
        for bloque in (datos.get("salidas"), datos.get("unidades"),
                       datos.get("params")):
            for r in _rutas(bloque, []):
                # Solo las que apuntan dentro de los datos del estudio, y se
                # miran con las barras APLANADAS: una mudanza a medias deja
                # `/opt/.../proyectos\beats_2\...`, que no encaja ni con
                # «/proyectos/» ni con «\proyectos\». Filtrandolo por separado
                # esas rutas se caian del recuento y el fallo no se veia --paso,
                # y lo delato que el origen comprobara 31 ficheros y el destino 0.
                llano = r.replace("\\", "/")
                if "/proyectos/" not in llano and "/banco/" not in llano:
                    continue
                comprobadas += 1
                if os.path.exists(r):
                    continue
                transitoria = ("/trabajo/" in r.replace("\\", "/"))
                (faltan_trabajo if transitoria else faltan).append(r)

    salida["ficheros_comprobados"] = comprobadas
    salida["faltan_persistentes"] = len(set(faltan))
    salida["faltan_en_trabajo"] = len(set(faltan_trabajo))
    salida["ejemplos_que_faltan"] = sorted(set(faltan))[:10]
    return salida


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("carpeta")
    ap.add_argument("--json", action="store_true", help="solo el JSON, en una linea")
    args = ap.parse_args(argv)

    f = foto(args.carpeta)
    if args.json:
        print(json.dumps(f, sort_keys=True, ensure_ascii=False))
        return 0

    print(f"proyecto: {f['proyecto']}")
    print(f"{'paso':16} {'estado':10} {'activa':>6} {'vers':>5} {'unid':>5} "
          f"{'obsol':>6} {'inval':>6} {'decl':>5}")
    for pid, d in f["pasos"].items():
        print(f"{pid:16} {d['estado']:10} {str(d['activa']):>6} "
              f"{d['versiones']:>5} {d['unidades']:>5} {d['obsoletas']:>6} "
              f"{d['invalidadas']:>6} {d['declaradas']:>5}")
    print(f"\nficheros referidos por el estado:  {f['ficheros_comprobados']}")
    print(f"faltan, y son PERSISTENTES:        {f['faltan_persistentes']}   <- esto es lo que importa")
    print(f"faltan, pero son de trabajo/:      {f['faltan_en_trabajo']}   (transitorias, faltan tambien en el origen)")
    for r in f["ejemplos_que_faltan"]:
        print(f"   falta: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
