"""
Hyperframes y movimiento de camara determinista.

Idea: el plano se genera a 1536x1024 y se amplia x2 en local. El video sale a
1920x1080 recortando una ventana 16:9 DENTRO de ese hyperframe de 3072x2048. Un
zoom de 1.0 a 1.2 sigue leyendo pixeles reales del hyperframe en vez de estirar
los del plano, que es la diferencia entre un zoom limpio y uno emborronado.

El centro del zoom no se elige a ojo: sale de anclas.json, que el blockout
proyecta desde la misma geometria que guio la generacion de la imagen. Si la
escena dice zoom sobre 'buque', el encuadre acaba sobre el buque, sin adivinar.

    python movimiento.py --plan plan_timed.json --escenas ./assets/final --out movimiento.json
"""
import argparse
import json
import os
import sys

from PIL import Image

ASPECTO = 16 / 9


def cargar_anclas(blockout_dir, set_name, camara):
    ruta = os.path.join(blockout_dir, set_name or "", "anclas.json")
    if not set_name or not os.path.exists(ruta):
        return {}
    with open(ruta, "r", encoding="utf-8") as fh:
        return json.load(fh).get(camara, {})


def centro_de(escena, anclas):
    """Centro normalizado del zoom. Prioridad: ancla del blockout, centro
    explicito del plan, y si no hay nada, el centro geometrico."""
    zoom = escena.get("zoom") or {}
    nombre = zoom.get("ancla")
    if nombre:
        ancla = anclas.get(nombre)
        if ancla and ancla.get("visible"):
            return [ancla["x"], ancla["y"]], f"ancla:{nombre}"
    if zoom.get("centro"):
        return list(zoom["centro"]), "plan"
    return [0.5, 0.5], "por_defecto"


def ventana(centro, escala):
    """Rectangulo 16:9 normalizado sobre el hyperframe para una escala dada.

    La ventana se mantiene dentro de los limites: si el ancla esta cerca de un
    borde, se desplaza en lugar de salirse, porque un recorte fuera del lienzo
    sacaria banda negra.
    """
    ancho = 1.0 / escala
    alto = 1.0 / escala
    x = min(max(centro[0] - ancho / 2, 0.0), 1.0 - ancho)
    y = min(max(centro[1] - alto / 2, 0.0), 1.0 - alto)
    return [round(x, 5), round(y, 5), round(ancho, 5), round(alto, 5)]


def hyperframe(origen, destino, escala=2):
    """Amplia el plano. LANCZOS basta porque el arte es plano y de linea dura:
    no hay textura fina que reconstruir, solo bordes que mantener limpios."""
    img = Image.open(origen).convert("RGB")
    grande = img.resize((img.width * escala, img.height * escala), Image.LANCZOS)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    grande.save(destino, "PNG")
    return grande.size


def calcular(plan, dir_escenas, dir_hyper, blockout_dir, escala=2):
    movimientos = []
    for escena in plan["escenas"]:
        sid = escena["id"]
        origen = os.path.join(dir_escenas, f"{sid}.png")
        zoom = escena.get("zoom") or {}
        anclas = cargar_anclas(blockout_dir, escena.get("set"), escena.get("camara"))
        centro, fuente = centro_de(escena, anclas)

        de = float(zoom.get("de", 1.0))
        a = float(zoom.get("a", 1.0))

        entrada = {
            "id": sid,
            "t_in": escena.get("t_in"),
            "t_out": escena.get("t_out"),
            "transicion": escena.get("transicion", "corte"),
            "centro": [round(c, 4) for c in centro],
            "origen_centro": fuente,
            "escala_ini": de,
            "escala_fin": a,
            "ventana_ini": ventana(centro, de),
            "ventana_fin": ventana(centro, a),
            "componente": escena.get("componente"),
        }

        if os.path.exists(origen):
            destino = os.path.join(dir_hyper, f"{sid}.png")
            ancho, alto = hyperframe(origen, destino, escala)
            entrada["hyperframe"] = os.path.relpath(destino, os.path.dirname(dir_hyper))
            entrada["hyperframe_px"] = [ancho, alto]
            # Con la ventana mas cerrada, cuantos pixeles reales quedan por
            # cada pixel de salida. Por debajo de 1.0 se estaria inventando detalle.
            estrecha = min(de, a) if min(de, a) > 0 else 1.0
            entrada["px_por_px_salida"] = round((ancho / max(de, a)) / 1920, 2)
        else:
            entrada["hyperframe"] = None

        movimientos.append(entrada)
    return movimientos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--escenas", required=True)
    parser.add_argument("--hyper", required=True)
    parser.add_argument("--blockout", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--escala", type=int, default=2)
    args = parser.parse_args()

    with open(args.plan, "r", encoding="utf-8") as fh:
        plan = json.load(fh)

    movimientos = calcular(plan, args.escenas, args.hyper, args.blockout, args.escala)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"fps": plan.get("fps", 30),
                   "resolucion": plan.get("resolucion", [1920, 1080]),
                   "movimientos": movimientos}, fh, ensure_ascii=False, indent=2)

    for m in movimientos:
        marca = "OK " if m.get("hyperframe") else "-- "
        ratio = m.get("px_por_px_salida")
        aviso = "" if ratio is None or ratio >= 1.0 else f"  AVISO ratio {ratio}"
        print(f"  {marca}{m['id']}  zoom {m['escala_ini']}->{m['escala_fin']}  "
              f"centro {m['centro']} ({m['origen_centro']}){aviso}")
    print(f"[movimiento] {len(movimientos)} escenas -> {args.out}")


if __name__ == "__main__":
    main()
