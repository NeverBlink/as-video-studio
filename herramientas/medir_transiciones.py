"""Cuanto se adelanta el EFECTO de transicion a la transicion que se VE.

    python herramientas/medir_transiciones.py <id_del_proyecto> [<otro_id>...]

Se oye como «el sonido llega antes que el corte». Aqui se mide, corte a corte,
sobre los mismos datos con los que se monta el video: el plan de planos, la
paleta de transiciones resuelta (`transiciones.resolver`) y los eventos de
sonido (`sonido.eventos`). No abre el MP4 ni sale a la red.

QUE SE COMPARA, Y POR QUE ASI. La transicion **se cuece dentro de los primeros
fotogramas del plano que ENTRA** (`p8._cocer_transicion`), asi que ocupa la
ventana [t_in, t_in + duracion]. El efecto se coloca por su GOLPE --el momento
en que llega a -6 dB de su pico, `sonido.golpe_de`-- y no por su primera
muestra, para que caiga siempre en `ANCLA_TRANSICION` de esa ventana.

Lo que se mide aqui es **donde acaba cayendo ese golpe**, corte a corte:

    golpe - centro      0 = el sonido pega justo cuando la mezcla visual va por
                        la mitad. Positivo = tarde, negativo = pronto.
    dispersion          la diferencia entre el corte que mas se adelanta y el
                        que mas se retrasa. ES LA CIFRA QUE IMPORTA: un desfase
                        constante se oye como estilo, uno que cambia en cada
                        corte se oye como que algo esta roto.

Con varios proyectos en la linea de ordenes se comparan entre si, que es la
forma de saber si algo ha CAMBIADO o si siempre fue asi.
"""
import io
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

from pasos import sonido, transiciones                          # noqa: E402


def leer(ruta, defecto=None):
    try:
        with io.open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return defecto


def activa(proyecto, paso):
    base = os.path.join(RAIZ, "proyectos", proyecto, "pasos", paso)
    if not os.path.isdir(base):
        return ""
    ficha = leer(os.path.join(base, "activa.json"), {}) or {}
    version = ficha.get("version") or ficha.get("activa")
    if version and os.path.isdir(os.path.join(base, str(version))):
        return os.path.join(base, str(version))
    versiones = sorted((n for n in os.listdir(base)
                        if n.startswith("v") and n[1:].isdigit()),
                       key=lambda n: int(n[1:]))
    return os.path.join(base, versiones[-1]) if versiones else ""


def medir(proyecto, detalle=False):
    plan = leer(os.path.join(activa(proyecto, "assets"), "plan.json"), {}) or {}
    escenas = plan.get("escenas") or []
    if not escenas:
        print("%s: no hay plan" % proyecto)
        return None
    estado = leer(os.path.join(RAIZ, "proyectos", proyecto, "estado.json"),
                  {}) or {}
    p = ((estado.get("pasos") or {}).get("render") or {}).get("params") or {}
    semilla = plan.get("semilla") or 0
    cortes = transiciones.resolver(escenas, p, semilla=semilla)
    origen = float(escenas[0].get("t_in") or 0.0)

    # los eventos de transicion, tal y como los coloca el montaje
    lista = sonido.eventos(escenas, cortes, p, semilla=semilla)
    por_plano = {}
    orden = [e for e in escenas
             if (cortes.get(e.get("id")) or {}).get("tipo") not in (None, "corte")]
    transiciones_sonoras = [e for e in lista
                            if str(e.get("papel") or "").startswith("transicion")]
    for escena, evento in zip(orden, sorted(transiciones_sonoras,
                                            key=lambda e: e["t"])):
        por_plano[escena["id"]] = evento

    filas = []
    for escena in escenas:
        corte = cortes.get(escena.get("id")) or {}
        if not corte.get("tipo") or corte["tipo"] == "corte":
            continue
        papel = ("transicion_acento" if corte.get("ranura") == "acento"
                 else "transicion_suave")
        dur = float(corte.get("duracion") or 0.0)
        entra = float(escena.get("t_in") or 0.0) - origen
        centro = entra + sonido.ANCLA_TRANSICION * dur
        # el efecto que le toco de verdad a ESTE corte, con su golpe medido
        evento = por_plano.get(escena["id"])
        if not evento:
            continue
        golpe = sonido.golpe_de(
            sonido.banco("efectos", sonido._nombre_de(evento["ficha"])))
        filas.append({"id": escena["id"], "papel": papel, "dur": dur,
                      "t_corte": entra, "t_efecto": float(evento["t"]),
                      "golpe": golpe,
                      "desfase": float(evento["t"]) + golpe - centro})

    if not filas:
        print("%s: no hay ninguna transicion con efecto" % proyecto)
        return None

    suaves = [f for f in filas if f["papel"] == "transicion_suave"]
    acentos = [f for f in filas if f["papel"] == "transicion_acento"]
    print("=" * 68)
    print(proyecto)
    print("=" * 68)
    print("  transiciones con efecto: %d  (%d suaves, %d acentos)"
          % (len(filas), len(suaves), len(acentos)))
    print("  base de duracion (render.duracion_transicion): %.2f s"
          % float(p.get("duracion_transicion") or 0.4))
    print("  efectos de transicion colocados: %d" % len(transiciones_sonoras))
    print("")
    print("  %-18s %10s %12s %12s" % ("", "duracion", "golpe del", "dispersion"))
    print("  %-18s %10s %12s %12s" % ("", "visual", "efecto", "(max-min)"))
    print("  " + "-" * 56)
    for nombre, grupo in (("suave", suaves), ("acento", acentos),
                          ("TODAS", filas)):
        if not grupo:
            continue
        desfases = [f["desfase"] for f in grupo]
        med = sum(f["dur"] for f in grupo) / len(grupo)
        print("  %-18s %9.2fs %11.3fs %11.3fs"
              % (nombre, med, sum(desfases) / len(desfases),
                 max(desfases) - min(desfases)))
    if detalle:
        print("")
        for f in filas[:14]:
            print("    %s %-18s arranca %6.2fs · golpea %6.2fs · centro visual "
                  "%6.2fs · desfase %+6.3fs"
                  % (f["id"], f["papel"], f["t_efecto"],
                     f["t_efecto"] + f["golpe"],
                     f["t_corte"] + sonido.ANCLA_TRANSICION * f["dur"],
                     f["desfase"]))
    desfases = [f["desfase"] for f in filas]
    return {"n": len(filas),
            "desfase": sum(desfases) / len(desfases),
            "dispersion": max(desfases) - min(desfases),
            "dur": sum(f["dur"] for f in filas) / len(filas)}


def main():
    proyectos = sys.argv[1:]
    if not proyectos:
        print(__doc__)
        return 2
    resumen = {}
    for proyecto in proyectos:
        ficha = medir(proyecto, detalle=len(proyectos) == 1)
        if ficha:
            resumen[proyecto] = ficha
        print("")
    if len(resumen) > 1:
        print("=" * 68)
        print("COMPARADOS")
        print("=" * 68)
        print("  %-34s %9s %11s %11s" % ("", "cortes", "desfase", "dispersion"))
        for proyecto, f in resumen.items():
            print("  %-34s %9d %10.3fs %10.3fs"
                  % (proyecto[:34], f["n"], f["desfase"], f["dispersion"]))
        print("")
        print("  La DISPERSION es la que delata: con los efectos colocados por")
        print("  su primera muestra se iba a casi un segundo, y era distinta en")
        print("  cada corte porque el efecto lo reparte la semilla.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
