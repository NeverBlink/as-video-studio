"""
Regeneracion de una escena aplicando el feedback humano, al vuelo.

Dos caminos, y el panel elige:

  directo   se reconstruye el prompt anadiendo el feedback y se vuelve a
            generar. Rapido y barato, sirve para el 90% de las correcciones
            ("mas oscuro", "quita el barco", "menos gente").

  agente    se lanza el CLI de Claude con Sonnet sobre la carpeta del proyecto.
            Puede leer el plan, mirar la imagen anterior, decidir que hay que
            cambiar y tocar mas de una cosa. Para feedback que no es una
            correccion de prompt sino un problema de planteamiento.

El feedback dibujado se resume en texto antes de mandarlo: el modelo de imagen
no recibe el trazo, recibe donde cayo. Un circulo en la esquina superior
derecha se convierte en "presta atencion a la zona superior derecha".
"""
import json
import os
import subprocess
import sys

#: La carpeta de motores es la que contiene ESTE fichero. Antes era una ruta
#: fija a una maquina concreta.
MOTORES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(MOTORES, "imagen_openai"))

import imagen as motor  # noqa: E402

# Sin ventana negra. Estos procesos (yt-dlp, ffmpeg, whisperx) son de consola, y
# lanzados desde el servicio del Estudio abren una ventana encima de todo por
# cada llamada. Trabajando por escritorio remoto es la pantalla tapandose sola.
SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


ZONAS = [
    ("superior izquierda", 0.0, 0.33, 0.0, 0.33),
    ("superior centro", 0.33, 0.67, 0.0, 0.33),
    ("superior derecha", 0.67, 1.0, 0.0, 0.33),
    ("centro izquierda", 0.0, 0.33, 0.33, 0.67),
    ("centro", 0.33, 0.67, 0.33, 0.67),
    ("centro derecha", 0.67, 1.0, 0.33, 0.67),
    ("inferior izquierda", 0.0, 0.33, 0.67, 1.0),
    ("inferior centro", 0.33, 0.67, 0.67, 1.0),
    ("inferior derecha", 0.67, 1.0, 0.67, 1.0),
]


def describir_trazos(trazos):
    """Trazo dibujado -> frase. El generador no entiende un canvas."""
    if not trazos:
        return ""
    conteo = {}
    for trazo in trazos:
        for punto in trazo.get("puntos", []):
            for nombre, x0, x1, y0, y1 in ZONAS:
                if x0 <= punto["x"] < x1 and y0 <= punto["y"] < y1:
                    conteo[nombre] = conteo.get(nombre, 0) + 1
                    break
    if not conteo:
        return ""
    orden = sorted(conteo.items(), key=lambda kv: -kv[1])
    zonas = [n for n, _ in orden[:3]]
    return ("The reviewer marked these areas of the image as needing changes: "
            + ", ".join(zonas) + ".")


def prompt_correctivo(prompt_original, feedback, trazos, generales=""):
    partes = [prompt_original.rstrip(".") + "."]
    partes.append("REVISION: the previous version of this shot was rejected. "
                  "Keep everything that was not criticised and change only what "
                  "the note asks for.")
    if generales.strip():
        partes.append(f"General direction for the whole video: {generales.strip()}")
    if feedback.strip():
        partes.append(f"Reviewer note: {feedback.strip()}")
    marcas = describir_trazos(trazos)
    if marcas:
        partes.append(marcas)
    return " ".join(partes)


# --------------------------------------------------------------- camino directo

def regenerar_directo(proyecto, escena_id, feedback, trazos, generales="",
                      quality="low", carpeta="storyboard"):
    """Vuelve a generar la escena con el prompt corregido."""
    meta_ruta = os.path.join(proyecto, "assets", carpeta, "escenas_meta.json")
    if not os.path.exists(meta_ruta):
        raise RuntimeError(f"No encuentro {meta_ruta}")
    with open(meta_ruta, "r", encoding="utf-8") as fh:
        meta = json.load(fh)

    registro = next((e for e in meta["escenas"] if e["id"] == escena_id), None)
    if not registro or not registro.get("prompt"):
        raise RuntimeError(f"{escena_id} no tiene prompt guardado; "
                           f"regenera el storyboard entero primero")

    anterior = os.path.join(proyecto, "assets", carpeta, f"{escena_id}.png")
    cache = os.path.join(proyecto, "assets", "_refs")
    refs = []
    # La version rechazada va como referencia: se corrige sobre ella en lugar de
    # empezar de cero, que es lo que hace que el resto del plano no cambie.
    if os.path.exists(anterior):
        refs.append(motor.normalizar(anterior, cache))

    # La ruta del plan la dejo escrita el orquestador al generar; asi no hay que
    # adivinarla cuando conviven varias versiones del plan en la carpeta.
    plan_ruta = meta.get("plan") or os.path.join(proyecto, "scenes",
                                                 "plan_v3_timed.json")
    if os.path.exists(plan_ruta):
        with open(plan_ruta, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        for rel in plan.get("estilo", {}).get("referencias_estilo", [])[:1]:
            ruta = os.path.join(proyecto, rel)
            if os.path.exists(ruta):
                refs.append(motor.normalizar(ruta, cache))
        escena = next((e for e in plan["escenas"] if e["id"] == escena_id), {})
        for pid in escena.get("personajes", []):
            hoja = os.path.join(proyecto, "assets", "reparto", f"{pid}.png")
            if os.path.exists(hoja):
                refs.append(motor.normalizar(hoja, cache))

    prompt = prompt_correctivo(registro["prompt"], feedback, trazos, generales)
    png, info = motor.generar(prompt, refs, quality=quality)

    # La version anterior se guarda: si la correccion empeora, hay vuelta atras
    historial = os.path.join(proyecto, "assets", carpeta, "_historial")
    os.makedirs(historial, exist_ok=True)
    if os.path.exists(anterior):
        n = len([f for f in os.listdir(historial) if f.startswith(escena_id)])
        os.replace(anterior, os.path.join(historial, f"{escena_id}_v{n + 1}.png"))
    with open(anterior, "wb") as fh:
        fh.write(png)

    registro["prompt"] = prompt
    registro["revisiones"] = registro.get("revisiones", 0) + 1
    with open(meta_ruta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    return {"ok": True, "modo": "directo", "escena": escena_id,
            "archivo": f"{escena_id}.png", "prompt": prompt, **info}


# ---------------------------------------------------------------- camino agente

INSTRUCCION_AGENTE = """\
Eres el asistente de produccion de un video de animacion cartoon.

El revisor humano ha rechazado la escena {escena} y ha dejado esta nota:

    {feedback}
{marcas}{generales}

Tu trabajo:
1. Lee scenes/plan_v2_timed.json y assets/{carpeta}/escenas_meta.json.
2. Mira assets/{carpeta}/{escena}.png, que es la version rechazada.
3. Decide que hay que cambiar de verdad. Puede ser el prompt, la luz, el set,
   la camara, los personajes o el zoom.
4. Aplica el cambio donde corresponda y regenera SOLO la escena {escena} con:
     C:\\IA\\venvs\\cartoon\\Scripts\\python.exe orquestador_v2.py storyboard --solo {escena}
5. Si el problema es general y no de esta escena, anade una regla a
   C:\\IA\\motores\\reglas\\reglas.json con reglas.py.

Trabaja en {proyecto}. No toques otras escenas. Termina con un resumen de una
linea de lo que cambiaste.
"""


def regenerar_agente(proyecto, escena_id, feedback, trazos, generales="",
                     carpeta="storyboard", modelo="sonnet", timeout=900):
    """Lanza el CLI de Claude para que decida y aplique la correccion."""
    marcas = describir_trazos(trazos)
    instruccion = INSTRUCCION_AGENTE.format(
        escena=escena_id,
        feedback=feedback.strip() or "(sin nota escrita)",
        marcas=f"\n    {marcas}\n" if marcas else "",
        generales=f"\n    Direccion general: {generales.strip()}\n" if generales.strip() else "",
        carpeta=carpeta,
        proyecto=proyecto,
    )

    # El esfuerzo va explicito y los MCP del usuario se quedan fuera: sin
    # --effort el CLI razona durante minutos antes de tocar nada (371 s frente a
    # 70 s medidos con la misma entrada), y los servidores MCP no pintan nada en
    # una correccion de escena. El entorno viaja sin las variables de
    # razonamiento para que tarde lo mismo se lance desde donde se lance.
    entorno = {c: v for c, v in os.environ.items()
               if c not in ("CLAUDE_EFFORT", "MAX_THINKING_TOKENS")}
    proceso = subprocess.run(
        ["claude", "-p", instruccion,
         "--model", modelo,
         "--effort", "low",
         "--strict-mcp-config",
         "--permission-mode", "acceptEdits",
         "--add-dir", MOTORES],
        cwd=proyecto, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
        shell=True, env=entorno, **SIN_VENTANA)
    salida = (proceso.stdout or "").strip()
    return {"ok": proceso.returncode == 0, "modo": "agente", "escena": escena_id,
            "modelo": modelo, "salida": salida[-2000:],
            "error": (proceso.stderr or "")[-800:] if proceso.returncode else ""}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--proyecto", required=True)
    parser.add_argument("--escena", required=True)
    parser.add_argument("--feedback", default="")
    parser.add_argument("--generales", default="")
    parser.add_argument("--modo", default="directo", choices=["directo", "agente"])
    parser.add_argument("--carpeta", default="storyboard")
    args = parser.parse_args()

    fn = regenerar_directo if args.modo == "directo" else regenerar_agente
    print(json.dumps(fn(args.proyecto, args.escena, args.feedback, [],
                        args.generales, carpeta=args.carpeta),
                     ensure_ascii=False, indent=2))
