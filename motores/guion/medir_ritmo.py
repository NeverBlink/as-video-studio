"""
Mide el ritmo de montaje real de un video: cada cuanto corta de plano.

Sirve para calibrar el segmentador con datos en lugar de a ojo. No extrae ni
guarda contenido del video, solo la estadistica de los instantes de corte.

    python medir_ritmo.py --video <archivo> [--umbral 0.30]
"""
import argparse
import os
import re
import statistics
import subprocess

# Sin ventana negra: ffmpeg es un proceso de consola y lanzado desde el servicio
# abre una encima de todo. Ver el mismo bloque en pasos/medios.py.
SIN_VENTANA = {}
if os.name == "nt":
    SIN_VENTANA = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}


def instantes_de_corte(video, umbral=0.30):
    """showinfo escribe una linea por frame seleccionado en stderr."""
    proceso = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", video,
         "-vf", f"select='gt(scene,{umbral})',showinfo",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, errors="ignore", timeout=1800,
        **SIN_VENTANA)
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", proceso.stderr)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--umbral", type=float, default=0.30)
    parser.add_argument("--min", type=float, default=3.0)
    parser.add_argument("--max", type=float, default=6.0)
    args = parser.parse_args()

    cortes = instantes_de_corte(args.video, args.umbral)
    if len(cortes) < 3:
        raise SystemExit(f"Solo {len(cortes)} cortes detectados; baja el umbral")

    # Se descartan intervalos muy cortos: son parpadeos dentro del mismo plano
    # (un flash, un movimiento brusco), no cambios de escena de montaje.
    intervalos = [b - a for a, b in zip(cortes, cortes[1:]) if b - a > 0.5]

    en_rango = sum(1 for d in intervalos if args.min <= d <= args.max)
    print(f"duracion analizada : {cortes[-1]:.0f}s")
    print(f"cortes detectados  : {len(cortes)}")
    print(f"intervalo medio    : {statistics.mean(intervalos):.2f}s")
    print(f"mediana            : {statistics.median(intervalos):.2f}s")
    print(f"minimo / maximo    : {min(intervalos):.2f}s / {max(intervalos):.2f}s")
    print(f"dentro de {args.min:.0f}-{args.max:.0f}s     : "
          f"{en_rango / len(intervalos):.0%} de los cortes")

    cuartiles = statistics.quantiles(intervalos, n=4)
    print(f"cuartiles          : {cuartiles[0]:.2f} / {cuartiles[1]:.2f} / "
          f"{cuartiles[2]:.2f}")


if __name__ == "__main__":
    main()
