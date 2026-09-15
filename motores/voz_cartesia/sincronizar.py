"""
Fija los tiempos del plan de escenas a partir de la duracion real del audio.

El plan que escribe el guionista lleva tiempos estimados. Los reales solo se
conocen una vez sintetizada la voz, y son esos los que manda: si la animacion se
cronometra sobre estimaciones, la imagen y la narracion se separan y no hay forma
de recuperarlo despues.

Regla de adelanto: el corte visual entra ADELANTO segundos antes de que empiecen
las palabras de esa escena, para que el plano este establecido cuando llegan.

Uso:
    python sincronizar.py --plan plan.json --audio ./audio --out plan_timed.json
"""
import argparse
import json
import os

ADELANTO = 0.25        # el visual entra antes que la voz
COLA = 0.45            # aire despues de la ultima palabra
DURACION_MINIMA = 2.2  # ninguna escena baja de esto, aunque la frase sea corta


def sincronizar_continuo(plan, audio_meta):
    """Cortes deducidos de una toma unica de voz.

    Aqui el audio manda del todo: no se decide cuanto dura cada plano y luego se
    encaja la voz, sino al reves. El corte visual entra ADELANTO segundos antes
    de la primera palabra del plano, y dura hasta el corte del siguiente. Asi
    nunca hay deriva acumulada, porque todos los tiempos salen de las marcas de
    la misma grabacion.
    """
    por_id = {e["id"]: e for e in audio_meta["escenas"]}
    escenas = plan["escenas"]
    total_audio = audio_meta["duracion"]

    # Primer instante util de cada escena, saltando las que no tienen voz
    inicios = []
    for escena in escenas:
        datos = por_id.get(escena["id"], {})
        inicios.append(datos.get("t_primera_palabra"))

    # Las escenas sin narracion heredan un hueco proporcional entre sus vecinas
    for i, valor in enumerate(inicios):
        if valor is None:
            anterior = next((inicios[j] for j in range(i - 1, -1, -1)
                             if inicios[j] is not None), 0.0)
            siguiente = next((inicios[j] for j in range(i + 1, len(inicios))
                              if inicios[j] is not None), total_audio)
            inicios[i] = anterior + (siguiente - anterior) / 2

    for i, escena in enumerate(escenas):
        datos = por_id.get(escena["id"], {})
        t_in = max(0.0, inicios[i] - ADELANTO)
        if i + 1 < len(escenas):
            t_out = max(t_in + DURACION_MINIMA, inicios[i + 1] - ADELANTO)
        else:
            fin = datos.get("t_ultima_palabra") or total_audio
            t_out = max(t_in + DURACION_MINIMA, fin + COLA)

        escena["t_in"] = round(t_in, 3)
        escena["t_out"] = round(t_out, 3)
        escena["audio"] = {
            "pista": audio_meta["archivo"],
            "t_primera_palabra": datos.get("t_primera_palabra"),
            "t_ultima_palabra": datos.get("t_ultima_palabra"),
            "duracion": datos.get("duracion", 0.0),
            # Marcas ya absolutas en la linea de tiempo del video: al ser una
            # toma unica, el tiempo del audio ES el tiempo del video.
            "palabras": datos.get("palabras", []),
        }

    plan["duracion_total"] = round(max(escenas[-1]["t_out"], total_audio + COLA), 3)
    plan["sincronizado"] = {"modo": "continuo", "adelanto": ADELANTO,
                            "cola": COLA, "duracion_minima": DURACION_MINIMA,
                            "pista": audio_meta["archivo"]}
    return plan


def sincronizar(plan, audio_meta):
    duraciones = {e["id"]: e["duracion"] for e in audio_meta["escenas"]}
    palabras = {e["id"]: e.get("palabras") or [] for e in audio_meta["escenas"]}

    reloj = 0.0
    for escena in plan["escenas"]:
        sid = escena["id"]
        dur_voz = duraciones.get(sid, 0.0)
        dur_escena = max(DURACION_MINIMA, ADELANTO + dur_voz + COLA)

        escena["t_in"] = round(reloj, 3)
        escena["t_out"] = round(reloj + dur_escena, 3)
        escena["audio"] = {
            "archivo": f"{sid}.wav" if dur_voz else None,
            "t_inicio": round(reloj + ADELANTO, 3) if dur_voz else None,
            "duracion": round(dur_voz, 3),
            # Marcas absolutas en la linea de tiempo del video, no relativas al clip:
            # asi el consumidor no tiene que sumar offsets y no puede equivocarse.
            "palabras": [
                {"w": p["w"],
                 "s": round(reloj + ADELANTO + p["s"], 3),
                 "e": round(reloj + ADELANTO + p["e"], 3)}
                for p in palabras.get(sid, [])
            ],
        }
        reloj += dur_escena

    plan["duracion_total"] = round(reloj, 3)
    plan["sincronizado"] = {"adelanto": ADELANTO, "cola": COLA,
                            "duracion_minima": DURACION_MINIMA}
    return plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--audio", required=True, help="carpeta con audio_meta.json")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.plan, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    with open(os.path.join(args.audio, "audio_meta.json"), "r", encoding="utf-8") as fh:
        audio_meta = json.load(fh)

    plan = sincronizar(plan, audio_meta)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, ensure_ascii=False, indent=2)

    for e in plan["escenas"]:
        print(f"  {e['id']}  {e['t_in']:6.2f} -> {e['t_out']:6.2f}  "
              f"({e['t_out'] - e['t_in']:5.2f}s)  voz {e['audio']['duracion']:5.2f}s")
    print(f"[sync] duracion total {plan['duracion_total']:.2f}s -> {args.out}")


if __name__ == "__main__":
    main()
