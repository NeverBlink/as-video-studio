"""
Cabeceras animadas de capitulo: la tarjeta tipo "Year 10" o "Colombia, 1931".

Se montan en SVG y no se generan con el modelo de imagen por lo mismo de
siempre: son tipografia, y la tipografia sale exacta en vectorial y aproximada
en difusion. Ademas asi el texto se puede corregir sin volver a generar nada.

La animacion va declarada en el propio SVG (SMIL + CSS), de modo que el
reproductor del gate y el render final ven exactamente lo mismo.

    python cabecera.py --titulo "Year 10" --subtitulo "$96,000" --out cab.svg
"""
import argparse
import json
import os

ANCHO, ALTO = 1920, 1080

PALETA = {
    "fondo": "#12130f",
    "velo": "#1b1c17",
    "linea": "#d8a657",
    "texto": "#ece7dc",
    "tenue": "#9a958a",
}

# Duraciones en segundos. La regla es que el titulo termine de entrar antes de
# que empiece a salir el velo, o el ojo pierde la palabra.
ENTRADA = 0.45
SALIDA = 0.35


def construir(titulo, subtitulo="", antetitulo="", duracion=2.2,
              paleta=None, transparente=True):
    p = dict(PALETA, **(paleta or {}))
    fin_entrada = ENTRADA
    inicio_salida = max(fin_entrada + 0.3, duracion - SALIDA)

    fondo = ("" if transparente else
             f'<rect width="{ANCHO}" height="{ALTO}" fill="{p["fondo"]}"/>')

    # El velo cubre el plano de debajo y se retira al final: asi la cabecera se
    # puede montar ENCIMA de la escena en lugar de sustituirla.
    velo = (f'<rect id="velo" width="{ANCHO}" height="{ALTO}" fill="{p["velo"]}" '
            f'opacity="0.92">'
            f'<animate attributeName="opacity" from="0" to="0.92" '
            f'begin="0s" dur="{ENTRADA}s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="0.92" to="0" '
            f'begin="{inicio_salida}s" dur="{SALIDA}s" fill="freeze"/>'
            f'</rect>')

    cy = ALTO / 2
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}" '
        f'width="{ANCHO}" height="{ALTO}">',
        fondo, velo,
        f'<g font-family="Verdana, Geneva, sans-serif" text-anchor="middle">',
    ]

    if antetitulo:
        partes.append(
            f'<text x="{ANCHO/2}" y="{cy - 118}" font-size="30" '
            f'letter-spacing="9" fill="{p["tenue"]}" opacity="0">'
            f'{antetitulo.upper()}'
            f'<animate attributeName="opacity" from="0" to="1" begin="0.18s" '
            f'dur="0.35s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="1" to="0" '
            f'begin="{inicio_salida}s" dur="{SALIDA}s" fill="freeze"/></text>')

    # Regla que se dibuja de dentro hacia fuera: el trazo creciente es lo que da
    # la sensacion de cabecera y no de rotulo estatico.
    partes.append(
        f'<rect x="{ANCHO/2}" y="{cy - 74}" width="0" height="5" '
        f'fill="{p["linea"]}">'
        f'<animate attributeName="width" from="0" to="360" begin="0.05s" '
        f'dur="{ENTRADA}s" fill="freeze"/>'
        f'<animate attributeName="x" from="{ANCHO/2}" to="{ANCHO/2 - 180}" '
        f'begin="0.05s" dur="{ENTRADA}s" fill="freeze"/>'
        f'<animate attributeName="opacity" from="1" to="0" '
        f'begin="{inicio_salida}s" dur="{SALIDA}s" fill="freeze"/></rect>')

    partes.append(
        f'<text x="{ANCHO/2}" y="{cy + 26}" font-size="112" font-weight="700" '
        f'fill="{p["texto"]}" opacity="0">{titulo}'
        f'<animate attributeName="opacity" from="0" to="1" begin="0.12s" '
        f'dur="0.4s" fill="freeze"/>'
        f'<animateTransform attributeName="transform" type="translate" '
        f'from="0 22" to="0 0" begin="0.12s" dur="0.5s" fill="freeze"/>'
        f'<animate attributeName="opacity" from="1" to="0" '
        f'begin="{inicio_salida}s" dur="{SALIDA}s" fill="freeze"/></text>')

    if subtitulo:
        partes.append(
            f'<text x="{ANCHO/2}" y="{cy + 96}" font-size="42" '
            f'fill="{p["tenue"]}" opacity="0">{subtitulo}'
            f'<animate attributeName="opacity" from="0" to="1" begin="0.32s" '
            f'dur="0.4s" fill="freeze"/>'
            f'<animate attributeName="opacity" from="1" to="0" '
            f'begin="{inicio_salida}s" dur="{SALIDA}s" fill="freeze"/></text>')

    partes.append("</g></svg>")
    return "\n".join(partes)


def desde_plan(plan, salida):
    """Genera una cabecera por cada escena que declare 'capitulo'."""
    os.makedirs(salida, exist_ok=True)
    hechas = []
    for escena in plan.get("escenas", []):
        cap = escena.get("capitulo")
        if not cap:
            continue
        if isinstance(cap, str):
            cap = {"titulo": cap}
        dur = min(2.6, max(1.6, (escena.get("t_out", 0) - escena.get("t_in", 0)) * 0.6))
        svg = construir(cap.get("titulo", ""), cap.get("subtitulo", ""),
                        cap.get("antetitulo", ""), duracion=dur)
        ruta = os.path.join(salida, f"{escena['id']}_capitulo.svg")
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(svg)
        hechas.append({"escena": escena["id"], "archivo": os.path.basename(ruta),
                       "titulo": cap.get("titulo", ""), "duracion": round(dur, 2)})
        print(f"  {escena['id']}: cabecera '{cap.get('titulo','')}' ({dur:.1f}s)")
    return hechas


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--titulo")
    parser.add_argument("--subtitulo", default="")
    parser.add_argument("--antetitulo", default="")
    parser.add_argument("--duracion", type=float, default=2.2)
    parser.add_argument("--plan", help="genera todas las cabeceras de un plan")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    if args.plan:
        with open(args.plan, "r", encoding="utf-8") as fh:
            plan = json.load(fh)
        hechas = desde_plan(plan, args.out)
        print(f"[cabecera] {len(hechas)} cabeceras -> {args.out}")
        return

    if not args.titulo:
        raise SystemExit("Hace falta --titulo o --plan")
    svg = construir(args.titulo, args.subtitulo, args.antetitulo, args.duracion)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"[cabecera] {args.out}")


if __name__ == "__main__":
    main()
