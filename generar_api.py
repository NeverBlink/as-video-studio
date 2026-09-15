"""Escribe docs/API.md leyendo app.py. No inventa nada.

    python generar_api.py

POR QUE ESTO EXISTE Y NO UNA LISTA A MANO
------------------------------------------
La habia: la cabecera de `web/app.js` documentaba la API en un comentario. Se
quedo en **52 de 126 endpoints**, porque nadie la completaba al anadir uno --y una
lista a medias de una API es peor que ninguna, porque parece completa--. Asi que
la lista se genera de donde vive la verdad (los decoradores de `app.py`) y lo
unico que se escribe a mano son las FAMILIAS de aqui abajo, que es la unica parte
que un programa no puede deducir: en que se parecen dos rutas.

De cada endpoint se saca la ruta, el verbo y la PRIMERA FRASE de su docstring.
En este repo esa primera frase dice lo que hace la cosa, asi que la referencia
sale escrita sin que nadie la reescriba.

Y no hace falta acordarse de correrlo: `prueba_api.py` comprueba en las dos
direcciones que docs/API.md nombre todas las rutas y ninguna que ya no exista.
"""
import ast
import io
import os

RAIZ = os.path.dirname(os.path.abspath(__file__))

#: En que se parecen dos rutas. Cada familia son los PREFIJOS que le tocan, y
#: una ruta va a la familia cuyo prefijo es el MAS LARGO -- no a la primera que
#: encaje: `/api/proyectos` encaja con todo lo de un proyecto y se lo tragaria
#: entero.
FAMILIAS = (
    ("Proyectos y papelera", ("/api/proyectos",)),
    ("Pasos: estado, params y ejecución", ("/api/proyectos/{pid}/pasos",)),
    ("Trabajos en marcha", ("/api/trabajos",)),
    ("Recetas y pestañas", ("/api/recetas", "/api/proyectos/{pid}/pestanas",
                            "/api/proyectos/{pid}/generar")),
    ("Coste y bitácora", ("/api/coste", "/api/proyectos/{pid}/coste",
                          "/api/proyectos/{pid}/bitacora", "/api/tarifas")),
    ("Origen y guion", ("/api/proyectos/{pid}/frames",
                        "/api/proyectos/{pid}/integraciones",
                        "/api/proyectos/{pid}/material",
                        "/api/proyectos/{pid}/guion",
                        "/api/proyectos/{pid}/tono")),
    ("Voz", ("/api/proyectos/{pid}/voz", "/api/voces")),
    ("Catálogo, escenarios y piezas",
     ("/api/proyectos/{pid}/catalogo", "/api/proyectos/{pid}/escenarios",
      "/api/proyectos/{pid}/assets", "/api/proyectos/{pid}/conservacion")),
    ("Estilo y moodboard", ("/api/proyectos/{pid}/estilo",
                            "/api/proyectos/{pid}/moodboard", "/api/moodboard")),
    ("Referencias reales", ("/api/proyectos/{pid}/reales", "/api/commons")),
    ("Grafismo: subtítulos y cartelas",
     ("/api/proyectos/{pid}/callouts", "/api/proyectos/{pid}/cartelas",
      "/api/proyectos/{pid}/direccion", "/api/proyectos/{pid}/imagenes")),
    ("Sonido y transiciones", ("/api/proyectos/{pid}/sonido",
                               "/api/proyectos/{pid}/transiciones",
                               "/api/efectos")),
    ("Render y montaje", ("/api/proyectos/{pid}/montaje",
                          "/api/proyectos/{pid}/capturas",
                          "/api/proyectos/{pid}/render")),
    ("Presets del canal", ("/api/presets-canal", "/api/presets")),
    ("Modo light: estilos y vídeo", ("/api/presets-light", "/api/estimacion")),
    ("Ajustes del CLI y estadísticas", ("/api/ajustes", "/api/estadisticas",
                                        "/api/rendimiento", "/api/mapa")),
    ("Claves y enlaces", ("/api/claves", "/api/enlaces")),
    ("El asistente", ("/api/asistente",)),
    ("Ficheros y salud", ("/a/", "/api/salud", "/api/dictado")),
)

CABECERA = """# La API

Todo lo que sirve `app.py`, sacado del propio código: ruta, verbo y la primera
frase del docstring de cada endpoint. **Este fichero no se escribe a mano**: lo
escribe `generar_api.py`, y `prueba_api.py` comprueba que no se quede viejo.

Reglas que valen para toda la API y no se repiten en cada fila:

- **Un endpoint por cosa que sabe hacer el núcleo.** La pantalla no calcula
  estado: lo pide. Ver [README.md](../README.md).
- **Los errores hablan castellano.** `ErrorApi(codigo, "frase")` sale como
  `{"error": {...}}` con la frase que lee una persona y el detalle técnico
  aparte.
- **Nada bloquea.** Lo que tarda devuelve `202` con `trabajo_id`, y el progreso
  se sigue por `GET /api/trabajos/{tid}` o por el `eventos` que devuelve.
- **Editar es decidir.** No hay endpoint de «guardar y confirmar»: `PUT` guarda,
  y pasar de paso es aprobar.
"""


def endpoints(fuente):
    """[(verbo, ruta, primera frase del docstring)] de todos los @app.<verbo>."""
    salida = []
    for nodo in ast.parse(fuente).body:
        if not isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in nodo.decorator_list:
            if not (isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id == "app"):
                continue
            verbo = deco.func.attr.upper()
            if verbo not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                continue
            ruta = (deco.args[0].value
                    if deco.args and isinstance(deco.args[0], ast.Constant) else "")
            doc = ast.get_docstring(nodo) or ""
            frase = " ".join(doc.strip().split("\n")[0].split()) if doc else ""
            salida.append((verbo, ruta, frase))
    return salida


def familia_de(ruta):
    """La familia cuyo prefijo encaja y es el mas largo."""
    mejor, largo = None, -1
    for titulo, prefijos in FAMILIAS:
        for prefijo in prefijos:
            if ruta.startswith(prefijo) and len(prefijo) > largo:
                mejor, largo = titulo, len(prefijo)
    return mejor or "Lo demás"


def main():
    with io.open(os.path.join(RAIZ, "app.py"), encoding="utf-8") as fh:
        rutas = endpoints(fh.read())
    reparto = {}
    for entrada in rutas:
        reparto.setdefault(familia_de(entrada[1]), []).append(entrada)

    lineas = [CABECERA]
    orden = [t for t, _ in FAMILIAS] + ["Lo demás"]
    for titulo in orden:
        filas = sorted(reparto.get(titulo, []), key=lambda r: (r[1], r[0]))
        if not filas:
            continue
        lineas.append(f"\n## {titulo}\n")
        lineas.append("| | Ruta | Qué hace |")
        lineas.append("|---|---|---|")
        for verbo, ruta, frase in filas:
            lineas.append(f"| `{verbo}` | `{ruta}` | {frase or '—'} |")
    lineas.append(f"\n---\n\n**{len(rutas)} endpoints.** Escrito por "
                  f"`generar_api.py` desde `app.py`.\n")

    destino = os.path.join(RAIZ, "docs", "API.md")
    with io.open(destino, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lineas))
    print(f"{destino}: {len(rutas)} endpoints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
