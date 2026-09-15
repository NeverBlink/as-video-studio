"""
Base de reglas transversales aprendidas del feedback humano.

Cada vez que una revision detecta un fallo, el fallo se destila en una regla
abierta y se guarda aqui. Las reglas NO pertenecen al video en el que se
descubrieron: se aplican a todos los proyectos futuros.

Uso desde un motor:

    import reglas
    lineas = reglas.para("prompt_imagen")        # texto listo para inyectar
    reglas.anadir(id="...", ambito="...", regla="...", por_que="...", origen={...})

Uso desde consola:

    python reglas.py listar [--ambito prompt_imagen]
    python reglas.py destilar --feedback feedback_gate1.json --proyecto mi_video
"""
import argparse
import json
import os
from datetime import date

RUTA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reglas.json")

AMBITOS = ("prompt_imagen", "referencias", "reparto", "blockout",
           "plan_escenas", "storyboard", "montaje", "voz")


def cargar():
    with open(RUTA, "r", encoding="utf-8") as fh:
        return json.load(fh)


def guardar(datos):
    with open(RUTA, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)


def para(ambito, como_texto=True):
    """Reglas de un ambito, ordenadas por prioridad."""
    datos = cargar()
    filtradas = [r for r in datos["reglas"] if r["ambito"] == ambito]
    filtradas.sort(key=lambda r: r.get("prioridad", 9))
    if not como_texto:
        return filtradas
    return [r["regla"] for r in filtradas]


def bloque_prompt(ambito="prompt_imagen"):
    """Devuelve las reglas como un parrafo listo para concatenar a un prompt."""
    lineas = para(ambito)
    if not lineas:
        return ""
    return " ".join(lineas)


def anadir(*, id, ambito, regla, por_que="", origen=None, prioridad=1):
    if ambito not in AMBITOS:
        raise ValueError(f"ambito desconocido: {ambito} (validos: {AMBITOS})")
    datos = cargar()
    existentes = {r["id"] for r in datos["reglas"]}
    if id in existentes:
        # Se actualiza en lugar de duplicar: la misma leccion puede reaparecer
        # en varios proyectos y lo util es acumular origenes, no repetir reglas.
        for r in datos["reglas"]:
            if r["id"] == id:
                r["regla"] = regla
                r.setdefault("origenes_extra", []).append(origen or {})
                break
    else:
        datos["reglas"].append({
            "id": id, "ambito": ambito, "prioridad": prioridad,
            "regla": regla, "por_que": por_que,
            "origen": origen or {}, "fecha": date.today().isoformat(),
        })
    guardar(datos)
    return id


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_listar = sub.add_parser("listar")
    p_listar.add_argument("--ambito", default=None, choices=AMBITOS)

    args = parser.parse_args()

    if args.cmd == "listar":
        datos = cargar()
        reglas = datos["reglas"]
        if args.ambito:
            reglas = [r for r in reglas if r["ambito"] == args.ambito]
        reglas.sort(key=lambda r: (r["ambito"], r.get("prioridad", 9)))
        ambito_actual = None
        for r in reglas:
            if r["ambito"] != ambito_actual:
                ambito_actual = r["ambito"]
                print(f"\n=== {ambito_actual} ===")
            print(f"  [{r['id']}]  {r['regla']}")
            if r.get("origen", {}).get("feedback"):
                print(f"      nacio de: \"{r['origen']['feedback']}\"")
        print(f"\n{len(reglas)} reglas")


if __name__ == "__main__":
    main()
