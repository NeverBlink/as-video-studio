"""Muda un proyecto (o un banco de presets) de una maquina a otra.

Para que
--------
Un proyecto del estudio guarda RUTAS ABSOLUTAS dentro de su estado: las salidas
de cada unidad, los manifiestos de cada version, las referencias de estilo del
preset y las hojas de personaje. Copiar la carpeta a otra maquina y ya deja
todas esas rutas apuntando al disco de la maquina de origen.

Copiar y reemplazar el texto del JSON tampoco vale, y por dos motivos
distintos:

1. En el fichero las barras van escapadas (`C:\\\\IA\\\\estudio`) y en memoria no,
   asi que un `str.replace` sobre el texto acierta unas veces y otras no. Por
   eso se muda con `nucleo.proyecto._mudar_rutas`, que recorre la estructura.

2. Y el que cuesta dinero: **las rutas entran en la firma de los pasos**. Las
   referencias de estilo viven en `assets.params.estilo.referencias`, y
   `_params_globales` mete los params enteros en la firma; las salidas de cada
   unidad entran en la firma del paso que depende de ella
   (`_sello_salida_unidad`). Medido sobre «Video sobre el oro»: mudar las rutas
   y no hacer nada mas deja `assets`, `callouts` y `render` en **obsoleto**, y
   la pantalla ofrece regenerar 302 planos ya pagados y volver a renderizar
   catorce minutos de video.

Asi que despues de mudar hay que RE-SELLAR: recalcular la firma de cada paso y
de cada unidad y guardarla, que es el valor que tendria el estado si el video se
hubiera generado en la maquina de destino.

La regla del re-sellado, que es lo unico delicado
------------------------------------------------
Se re-sella **solo lo que la mudanza movio, y solo si estaba en sincronia**.

No es una precaucion generica: `guion` guarda a proposito una `firma` que NO
cuadra con la calculada. Cuando alguien corrige el guion a mano, lo que gobierna
es `firma_propia` (la firma sin contar las correcciones) y la `firma` de siempre
se queda atras. Escribirla «arreglandola» mueve `_sello_salida(guion)`, que
entra en la firma de `voz`, y la cascada deja obsoleto todo lo que hay debajo
--medido: voz, revision_audio, assets, callouts y render--. Por eso se compara
contra la firma CALCULADA ANTES de mudar y no contra la guardada: lo que estaba
descuadrado se queda descuadrado igual.

Las versiones del historico se tratan igual. La mayoria conserva su firma
historica (su pareja `params`/`firma` ya no cuadra con lo de hoy, aqui y en la
maquina de origen: al revertirlas salen «obsoleto» en las dos, que es la misma
conducta), y se re-sellan solo aquellas cuya firma si estaba en sincronia.

Uso
---
    python herramientas/mudar_proyecto.py <carpeta> \\
        --regla "C:\\IA\\estudio\\proyectos=/opt/studio/datos/adrian/proyectos" \\
        --regla "C:\\IA\\estudio\\banco=/opt/studio/datos/adrian/banco" \\
        [--aplicar]

Sin `--aplicar` es un SIMULACRO: dice cuantas rutas y cuantas firmas cambiaria
y no escribe nada.

Ojo con donde se lanza
----------------------
Si se lanza sobre los datos de un servicio en marcha, lo mismo que avisa
`migrar_manifiestos.py`: con los servicios PARADOS y como el usuario dueno de
los ficheros. El cerrojo vive en `tempfile.gettempdir()` y las unidades de
systemd llevan `PrivateTmp=yes`, asi que un proceso lanzado por ssh cree tomar
exclusion mutua y no toma nada.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

from nucleo.proyecto import Proyecto, _mudar_rutas          # noqa: E402
from nucleo.estado import (Estado, PASOS, PASOS_POR_ID,      # noqa: E402
                           CLAVE_UNIDADES)

# Texto plano que tambien lleva rutas: la lista de concat de ffmpeg del render.
TEXTO_PLANO = (".txt",)


# --------------------------------------------------------------- utilidades

def orden_topologico():
    """Los pasos de modo que cada uno vaya despues de sus dependencias."""
    pendientes = [p["id"] for p in PASOS]
    hechos, salida = set(), []
    while pendientes:
        movio = False
        for pid in list(pendientes):
            if all(d in hechos for d in PASOS_POR_ID[pid]["depende_de"]):
                salida.append(pid)
                hechos.add(pid)
                pendientes.remove(pid)
                movio = True
        if not movio:                       # ciclo: no deberia pasar nunca
            salida.extend(pendientes)
            break
    return salida


def _barra_de(ruta):
    """La barra que usa un destino: '/' si es POSIX, '\\' si es de Windows."""
    return "\\" if (len(ruta) > 1 and ruta[1] == ":") else "/"


def mudar_cadena(dato, reglas):
    """Muda una cadena y NORMALIZA LAS BARRAS DE LA COLA. -> (nueva, cambio)

    Lo segundo es la diferencia con `nucleo.proyecto._mudar_rutas`, y no es un
    detalle de estilo. Aquella se escribio para `duplicar`, que copia dentro de
    la MISMA maquina: cambia el prefijo y pega la cola tal cual, y en Windows da
    igual con que barra venga. Cruzando de Windows a Linux no da igual --deja
    `/opt/studio/datos/adrian/proyectos` + `{BS}taller{BS}estilo{BS}f_0079.png`,
    que en Linux es UN nombre de fichero con barras invertidas dentro y no
    existe--. Se vio comparando cuantos ficheros del estado estan en disco: 31
    en el origen y 0 en el destino.

    Y es IDEMPOTENTE a proposito: una cadena que ya empieza por el destino se
    normaliza igual. Asi volver a pasar la herramienta repara una mudanza a
    medias en vez de tener que subir los datos otra vez.
    """
    if not isinstance(dato, str) or not dato:
        return dato, False
    for desde, hasta in reglas:
        barra = _barra_de(hasta)
        for candidato in (hasta, desde):
            for b in ("\\", "/"):
                viejo = candidato.replace("\\", b)
                if not dato.lower().startswith(viejo.lower()):
                    continue
                cola = dato[len(viejo):]
                cola = cola.replace("\\" if barra == "/" else "/", barra)
                nueva = hasta + cola
                return nueva, nueva != dato
    return dato, False


def mudar_dato(dato, reglas):
    """Recorre la estructura. -> (nueva, cuantas cadenas cambiaron)"""
    if isinstance(dato, dict):
        n, out = 0, {}
        for k, v in dato.items():
            out[k], k_n = mudar_dato(v, reglas)
            n += k_n
        return out, n
    if isinstance(dato, list):
        n, out = 0, []
        for v in dato:
            nv, k_n = mudar_dato(v, reglas)
            out.append(nv)
            n += k_n
        return out, n
    nueva, cambio = mudar_cadena(dato, reglas)
    return nueva, (1 if cambio else 0)


# ------------------------------------------------------------------ ficheros

def ficheros_json(carpeta):
    for base, _dirs, nombres in os.walk(carpeta):
        for n in sorted(nombres):
            if n.endswith(".json"):
                yield os.path.join(base, n), "json"
            elif n.endswith(".jsonl"):
                yield os.path.join(base, n), "jsonl"
            elif n.endswith(TEXTO_PLANO):
                yield os.path.join(base, n), "texto"


def mudar_fichero(ruta, tipo, reglas, aplicar):
    """Devuelve cuantas rutas se mudaron en ese fichero."""
    if tipo == "json":
        try:
            doc = json.load(open(ruta, encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            return 0
        nuevo, n = mudar_dato(doc, reglas)
        if n and aplicar:
            tmp = ruta + ".mudando"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(nuevo, f, ensure_ascii=False, indent=2)
            os.replace(tmp, ruta)
        return n

    if tipo == "jsonl":
        n, lineas, cambio = 0, [], False
        for linea in open(ruta, encoding="utf-8"):
            linea = linea.rstrip("\n")
            if not linea.strip():
                lineas.append(linea)
                continue
            try:
                doc = json.loads(linea)
            except ValueError:
                lineas.append(linea)
                continue
            doc, k = mudar_dato(doc, reglas)
            n += k
            if k:
                cambio = True
            lineas.append(json.dumps(doc, ensure_ascii=False))
        if cambio and aplicar:
            tmp = ruta + ".mudando"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lineas) + "\n")
            os.replace(tmp, ruta)
        return n

    # Texto plano (la lista de concat de ffmpeg). Aqui el reemplazo SI es sobre
    # el texto --no es JSON, no hay barras escapadas-- y la ruta va entera en su
    # linea, asi que se normaliza la linea completa.
    n, lineas = 0, []
    for linea in open(ruta, encoding="utf-8", errors="replace").read().splitlines():
        nueva = linea
        for desde, hasta in reglas:
            barra = _barra_de(hasta)
            for candidato in (hasta, desde):
                for b in ("\\", "/"):
                    viejo = candidato.replace("\\", b)
                    pos = nueva.find(viejo)
                    if pos < 0:
                        continue
                    cola = nueva[pos + len(viejo):]
                    # la cola llega hasta el final de la ruta: aqui el resto de
                    # la linea es la comilla de cierre, sin barras
                    cola = cola.replace("\\" if barra == "/" else "/", barra)
                    nueva = nueva[:pos] + hasta + cola
                    break
                else:
                    continue
                break
        if nueva != linea:
            n += 1
        lineas.append(nueva)
    nuevo = "\n".join(lineas) + "\n"
    if n and aplicar:
        tmp = ruta + ".mudando"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(nuevo)
        os.replace(tmp, ruta)
    return n


# ------------------------------------------------------------------ sellado

def _manifiesto_de(estado, pid, v):
    """El manifiesto de una version, venga en la entrada o en su fichero."""
    try:
        return estado.manifiesto_version(pid, v)
    except Exception:
        return {}


def _escribir_manifiesto(estado, pid, v, mapa):
    """Guarda el manifiesto donde vivia: en la entrada o en su fichero.

    Se respeta el formato que tenia. Un proyecto sin migrar guarda el mapa
    dentro de la entrada de la version; uno migrado, en
    `pasos/<paso>/_versiones/v<N>.json`. Escribirlo en el otro sitio dejaria
    dos copias que se contradicen, y `manifiesto_version` lee primero la de la
    entrada.
    """
    if CLAVE_UNIDADES in v:
        v[CLAVE_UNIDADES] = mapa
        return
    estado._guardar_manifiesto(pid, v.get("n"), mapa)


def _calculadas(estado):
    """Firmas CALCULADAS de todo: pasos, sus propias, unidades y versiones.

    De cada version se calculan tambien las firmas de las unidades de su
    MANIFIESTO, y hacen falta: `revertir` mete el manifiesto en el mapa vivo y
    `_unidades_obsoletas` compara la firma que trae cada unidad. Sin re-sellar
    esas, la mudanza deja el estado vivo perfecto y cada «Revertir» ensena las
    302 unidades en obsoleto -- medido.
    """
    foto = {}
    for pid in orden_topologico():
        datos = estado._doc["pasos"][pid]
        estado._cache = {}
        entrada = {
            "firma": estado._firma(pid),
            "propia": estado._firma(pid, propias=False),
            "unidades": {},
            "versiones": {},
        }
        for u in (datos.get("unidades") or {}):
            entrada["unidades"][str(u)] = estado._firma_unidad(pid, str(u))
        # cada version, con SUS params puestos: es la pareja que compara
        # `revertir` al activarla
        vivos = (datos.get("params"), datos.get("unidades"), datos.get("salidas"))
        try:
            for v in (datos.get("versiones") or []):
                if not isinstance(v, dict) or v.get("n") is None:
                    continue
                datos["params"] = v.get("params", {})
                estado._cache = {}
                por_unidad = {}
                for u in _manifiesto_de(estado, pid, v):
                    por_unidad[str(u)] = estado._firma_unidad(pid, str(u))
                entrada["versiones"][v["n"]] = {
                    "firma": estado._firma(pid),
                    "propia": estado._firma(pid, propias=False),
                    "unidades": por_unidad,
                }
        finally:
            datos["params"], datos["unidades"], datos["salidas"] = vivos
            estado._cache = {}
        foto[pid] = entrada
    return foto


def resellar(carpeta, antes, aplicar, avisos, todo=False):
    """Escribe las firmas que la mudanza movio. Devuelve cuantas cambiaron.

    DOS MODOS, y la diferencia importa:

    * el de siempre (`todo=False`) re-sella **solo lo que la mudanza movio, y
      solo si estaba en sincronia**. Conserva el estado tal y como estaba en la
      maquina de origen, descuadres incluidos: `guion` guarda a proposito una
      `firma` que no cuadra (manda `firma_propia`), y «arreglarla» mueve el
      sello de salida del guion y deja obsoleto todo lo que hay debajo.

    * `todo=True` sella al valor CALCULADO sin preguntar. Es lo que hace falta
      cuando el proyecto viene de una version del software con OTROS params
      --unas claves se caen al normalizar-- y lo que se quiere es que abra como
      si se hubiera generado aqui: nada obsoleto. Va en orden topologico y
      guardando lo calculado a cada paso, asi que cada paso se sella contra un
      aguas-arriba ya sellado y el resultado cuadra de arriba abajo.
    """
    estado = Estado(Proyecto(carpeta))
    cambios = 0

    for pid in orden_topologico():
        datos = estado._doc["pasos"][pid]
        previo = antes[pid]

        estado._cache = {}
        nueva = estado._firma(pid)
        nueva_propia = estado._firma(pid, propias=False)

        # --- la firma del paso ---
        if datos.get("firma") is not None and datos["firma"] != nueva:
            if todo or (nueva != previo["firma"]
                        and datos["firma"] == previo["firma"]):
                if aplicar:
                    datos["firma"] = nueva
                cambios += 1
            elif nueva != previo["firma"]:
                avisos.append(
                    f"{pid}: la firma guardada ya estaba fuera de sincronia "
                    f"antes de mudar; se deja como estaba (manda firma_propia)")

        if (datos.get("firma_propia") is not None
                and datos["firma_propia"] != nueva_propia):
            if todo or (nueva_propia != previo["propia"]
                        and datos["firma_propia"] == previo["propia"]):
                if aplicar:
                    datos["firma_propia"] = nueva_propia
                cambios += 1
            elif nueva_propia != previo["propia"]:
                avisos.append(
                    f"{pid}: firma_propia fuera de sincronia antes de mudar; "
                    f"se deja como estaba")

        # --- cada unidad ---
        for u, reg in (datos.get("unidades") or {}).items():
            if not isinstance(reg, dict) or reg.get("firma") is None:
                continue
            u = str(u)
            viejo = previo["unidades"].get(u)
            estado._cache = {}
            fu = estado._firma_unidad(pid, u)
            if reg["firma"] == fu:
                continue
            if todo:
                if aplicar:
                    reg["firma"] = fu
                cambios += 1
                continue
            if viejo is None or fu == viejo:
                continue
            if reg["firma"] == viejo:
                if aplicar:
                    reg["firma"] = fu
                cambios += 1
            else:
                avisos.append(f"{pid}/{u}: firma de unidad fuera de sincronia; se deja")

        # --- las versiones del historico, y el manifiesto de cada una ---
        vivos = (datos.get("params"), datos.get("unidades"), datos.get("salidas"))
        try:
            for v in (datos.get("versiones") or []):
                if not isinstance(v, dict) or v.get("n") is None:
                    continue
                prev_v = previo["versiones"].get(v["n"])
                if not prev_v:
                    continue
                datos["params"] = v.get("params", {})
                estado._cache = {}
                fv = estado._firma(pid)
                fvp = estado._firma(pid, propias=False)
                if v.get("firma") is not None and v["firma"] != fv:
                    if todo or (fv != prev_v["firma"]
                                and v["firma"] == prev_v["firma"]):
                        if aplicar:
                            v["firma"] = fv
                        cambios += 1
                if v.get("firma_propia") is not None and v["firma_propia"] != fvp:
                    if todo or (fvp != prev_v["propia"]
                                and v["firma_propia"] == prev_v["propia"]):
                        if aplicar:
                            v["firma_propia"] = fvp
                        cambios += 1

                # el manifiesto: lo que `revertir` mete en el mapa vivo
                mapa = _manifiesto_de(estado, pid, v)
                if not mapa:
                    continue
                toco = False
                for u, reg in mapa.items():
                    if not isinstance(reg, dict) or reg.get("firma") is None:
                        continue
                    fu = estado._firma_unidad(pid, str(u))
                    if reg["firma"] == fu:
                        continue
                    if not todo:
                        viejo_u = prev_v["unidades"].get(str(u))
                        if viejo_u is None or fu == viejo_u \
                                or reg["firma"] != viejo_u:
                            continue
                    reg["firma"] = fu
                    toco = True
                    cambios += 1
                if toco and aplicar:
                    _escribir_manifiesto(estado, pid, v, mapa)
        finally:
            datos["params"], datos["unidades"], datos["salidas"] = vivos
            estado._cache = {}

    if aplicar:
        estado._guardar()
    return cambios


# --------------------------------------------------------------------- main

def tipo_de(ruta):
    if ruta.endswith(".json"):
        return "json"
    if ruta.endswith(".jsonl"):
        return "jsonl"
    if ruta.endswith(TEXTO_PLANO):
        return "texto"
    return None


def mudar_objetivo(objetivo, reglas, aplicar, saltar, todo=False):
    """Muda un fichero o una carpeta. Si la carpeta es un proyecto, re-sella."""
    print(f"\n=== {objetivo} ===")

    if os.path.isfile(objetivo):
        tipo = tipo_de(objetivo)
        if tipo is None:
            print("  (no es json/jsonl/txt: no se toca)")
            return 0
        n = mudar_fichero(objetivo, tipo, reglas, aplicar)
        print(f"  rutas mudadas: {n}")
        return 0

    hay_estado = os.path.exists(os.path.join(objetivo, "estado.json"))
    antes = None
    if hay_estado:
        antes = _calculadas(Estado(Proyecto(objetivo)))

    total, tocados = 0, 0
    for ruta, tipo in ficheros_json(objetivo):
        if any(os.path.normcase(ruta).startswith(os.path.normcase(s))
               for s in saltar):
            continue
        n = mudar_fichero(ruta, tipo, reglas, aplicar)
        if n:
            total += n
            tocados += 1
    print(f"  rutas mudadas: {total}   ficheros con rutas: {tocados}")

    if not hay_estado:
        print("  (sin estado.json: no hay firmas que re-sellar)")
        return 0

    avisos = []
    n = resellar(objetivo, antes, aplicar, avisos, todo=todo)
    print(f"  firmas re-selladas: {n}"
          + ("  (SELLADO TOTAL: se sella lo calculado, no solo lo que movio)"
             if todo else ""))
    for a in avisos:
        print(f"    aviso: {a}")

    if aplicar:
        estado = Estado(Proyecto(objetivo))
        for pid in orden_topologico():
            print(f"    {pid:16} {estado.estado_de(pid)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("objetivo", nargs="+",
                    help="carpeta de proyecto, carpeta cualquiera o fichero json")
    ap.add_argument("--regla", action="append", default=[], metavar="DESDE=HASTA",
                    help="prefijo a mudar; se puede repetir")
    ap.add_argument("--saltar", action="append", default=[], metavar="RUTA",
                    help="subarbol que no se toca; se puede repetir")
    ap.add_argument("--aplicar", action="store_true",
                    help="escribir de verdad (sin esto es un simulacro)")
    ap.add_argument("--sellar-todo", action="store_true", dest="sellar_todo",
                    help="sella al valor CALCULADO sin preguntar, en orden "
                         "topologico: el proyecto abre como si se hubiera "
                         "generado aqui. Para traerlo de una version del "
                         "software con otros params (ver `resellar`)")
    args = ap.parse_args(argv)

    reglas = []
    for r in args.regla:
        if "=" not in r:
            ap.error(f"regla sin '=': {r}")
        desde, hasta = r.split("=", 1)
        reglas.append((desde.rstrip("\\/"), hasta.rstrip("/")))
    if not reglas:
        ap.error("hace falta al menos una --regla")

    saltar = [os.path.abspath(s) for s in args.saltar]
    print(f"{'APLICANDO' if args.aplicar else 'SIMULACRO'}")
    for d, h in reglas:
        print(f"  regla: {d}  ->  {h}")
    for s in saltar:
        print(f"  salta: {s}")

    for o in args.objetivo:
        o = os.path.abspath(o)
        if not os.path.exists(o):
            ap.error(f"no existe: {o}")
        mudar_objetivo(o, reglas, args.aplicar, saltar, todo=args.sellar_todo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
