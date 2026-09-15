"""
Componente de mapa como SVG vectorial.

Los mapas NO pasan por el generador de imagen: son datos (coordenadas reales) y
tipografia, y ambas cosas salen exactas en SVG y aproximadas en difusion. Ademas
el trazo de la ruta se puede animar por longitud de path, que es lo que da el
efecto de dibujado progresivo sin fotogramas intermedios.

    python mapa.py --config config.json --out mapa.svg
"""
import argparse
import json
import math
import os

# Paleta alineada con el estilo cartoon del resto del video
COLORES = {
    "mar": "#2c3f4d",
    "tierra": "#3f4a3a",
    "tierra_foco": "#6b6a45",
    "linea": "#12130f",
    "ruta": "#d8a657",
    "punto": "#d8785a",
    "texto": "#ece7dc",
}

ANCHO, ALTO = 1536, 1024


def mercator(lat, lon):
    """Proyeccion Mercator normalizada. Suficiente y honesta para un mapa
    editorial: mantiene los angulos y todo el mundo la reconoce."""
    x = (lon + 180.0) / 360.0
    lat_rad = math.radians(max(-85.0, min(85.0, lat)))
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0
    return x, y


class Vista:
    """Encuadre geografico -> pixeles."""

    def __init__(self, lat_min, lat_max, lon_min, lon_max, ancho=ANCHO, alto=ALTO):
        self.ancho, self.alto = ancho, alto
        self.x0, self.y1 = mercator(lat_min, lon_min)
        self.x1, self.y0 = mercator(lat_max, lon_max)

    def px(self, lat, lon):
        x, y = mercator(lat, lon)
        return (round((x - self.x0) / (self.x1 - self.x0) * self.ancho, 1),
                round((y - self.y0) / (self.y1 - self.y0) * self.alto, 1))


REGIONES = {
    "america": Vista(-12, 40, -125, -58),
    "estados_unidos": Vista(23, 51, -127, -65),
}

# Paises que se resaltan por region: el resto del continente se dibuja igual pero
# con el tono base, para que el foco quede claro sin perder el contexto.
FOCO = {
    "america": {"Colombia", "Mexico"},
    "estados_unidos": {"United States of America"},
}

RUTA_GEO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "datos", "paises_110m.geojson")

_cache_geo = {}


def cargar_paises():
    """Geometria real de Natural Earth 110m (dominio publico).

    Se uso geometria real en lugar de siluetas dibujadas a mano porque a mano
    los contornos abiertos se cierran solos al rellenarlos y salen manchas que
    no se parecen a ningun continente.
    """
    if "paises" not in _cache_geo:
        with open(RUTA_GEO, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        _cache_geo["paises"] = datos["features"]
    return _cache_geo["paises"]


def anillos_de(feature):
    """Normaliza Polygon y MultiPolygon a una lista de anillos exteriores."""
    geo = feature.get("geometry") or {}
    tipo, coords = geo.get("type"), geo.get("coordinates") or []
    if tipo == "Polygon":
        return [coords[0]] if coords else []
    if tipo == "MultiPolygon":
        return [poligono[0] for poligono in coords if poligono]
    return []


def d_anillo(vista, anillo, minimo=6):
    """Path cerrado. Se descartan islas diminutas: a este zoom solo anaden ruido
    de contorno sobre un estilo de linea gruesa."""
    puntos = [vista.px(lat, lon) for lon, lat in anillo]
    if len(puntos) < minimo:
        return None
    xs = [p[0] for p in puntos]
    ys = [p[1] for p in puntos]
    if (max(xs) - min(xs)) < 8 and (max(ys) - min(ys)) < 8:
        return None
    return "M " + " L ".join(f"{x} {y}" for x, y in puntos) + " Z"


def arco(vista, origen, destino, curvatura=0.22):
    """Ruta curva entre dos puntos: una recta lee como regla, un arco lee como
    trayecto."""
    x0, y0 = vista.px(*origen)
    x1, y1 = vista.px(*destino)
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    cx, cy = mx - dy * curvatura, my + dx * curvatura
    return f"M {x0} {y0} Q {round(cx,1)} {round(cy,1)} {x1} {y1}", (x0, y0), (x1, y1)


def construir(config):
    region = config.get("region", "america")
    vista = REGIONES[region]
    foco = FOCO.get(region, set())
    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {ANCHO} {ALTO}" '
        f'width="{ANCHO}" height="{ALTO}">',
        f'<rect width="{ANCHO}" height="{ALTO}" fill="{COLORES["mar"]}"/>',
        f'<g stroke="{COLORES["linea"]}" stroke-width="4" '
        f'stroke-linejoin="round" stroke-linecap="round">',
    ]
    for feature in cargar_paises():
        nombre = (feature.get("properties") or {}).get("NAME", "")
        relleno = COLORES["tierra_foco"] if nombre in foco else COLORES["tierra"]
        for anillo in anillos_de(feature):
            d = d_anillo(vista, anillo)
            if d:
                partes.append(f'<path d="{d}" fill="{relleno}"/>')
    partes.append("</g>")

    marcas = []

    if config.get("origen") and config.get("destino"):
        o = config["origen"]
        d = config["destino"]
        camino, p0, p1 = arco(vista, o["coord"], d["coord"])
        partes.append(
            f'<path id="ruta" d="{camino}" fill="none" stroke="{COLORES["ruta"]}" '
            f'stroke-width="7" stroke-linecap="round" stroke-dasharray="18 14"/>')
        marcas += [(p0, o["nombre"], "fin"), (p1, d["nombre"], "inicio")]

    for i, punto in enumerate(config.get("puntos", [])):
        p = vista.px(*punto["coord"])
        marcas.append((p, punto["nombre"], "inicio"))

    for indice, ((x, y), nombre, lado) in enumerate(marcas):
        # La etiqueta se voltea sola si no cabe: un rotulo cortado por el borde
        # es un fallo visible y aqui se puede evitar con aritmetica.
        ancho_estimado = len(nombre) * 19 + 30
        if lado != "fin" and x + ancho_estimado > ANCHO:
            lado = "fin"
        elif lado == "fin" and x - ancho_estimado < 0:
            lado = "inicio"
        ancla = "end" if lado == "fin" else "start"
        dx = -22 if lado == "fin" else 22
        partes.append(
            f'<g class="marca" data-indice="{indice}">'
            f'<circle cx="{x}" cy="{y}" r="11" fill="{COLORES["punto"]}" '
            f'stroke="{COLORES["linea"]}" stroke-width="4"/>'
            f'<text x="{x + dx}" y="{y + 8}" text-anchor="{ancla}" '
            f'font-family="Verdana, sans-serif" font-size="30" font-weight="700" '
            f'fill="{COLORES["texto"]}" stroke="{COLORES["linea"]}" '
            f'stroke-width="6" paint-order="stroke">{nombre}</text></g>')

    partes.append("</svg>")
    return "\n".join(partes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as fh:
        config = json.load(fh)
    svg = construir(config)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(svg)
    print(f"[mapa] {args.out}  ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
