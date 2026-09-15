"""
Prueba del paso 1: el material escrito.

No sale a la red y no toca ningun fichero de fuera: escribe en un proyecto
temporal, lo lee y lo compara. El paso entero es texto, asi que la prueba
tambien puede serlo.

Lo que se comprueba, y por que cada cosa:

  1. el material se parte por PARRAFOS, no por frases;
  2. los tiempos van a CERO y se dice (`sin_tiempos`), en vez de inventarlos;
  3. las salidas que se sellan en estado.json son solo CIFRAS -- lo gordo va a
     ficheros, o el nucleo lo sustituye por un resumen y el recuento «llega»
     como un objeto raro;
  4. `fuentes.material_de` --que es por donde lo lee el guion-- ve lo que este
     paso dejo;
  5. un material vacio FALLA en voz alta en vez de dejar el paso «listo» sin
     nada que contar;
  6. y cambiar el material deja obsoleto lo que se hizo leyendolo, que es la
     razon de que esto sea un paso del grafo y no un cajon suelto.
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fuentes
import p1_ingesta
from nucleo import Estado, Proyecto

FALLOS = []

MATERIAL = """La empresa reconocio el acceso en marzo de 2025.

El informe interno se publico tres meses despues, y contaba una version
distinta: hablaba de un unico servidor.

Dos peritos lo desmintieron en octubre."""


def comprobar(texto, condicion, detalle=""):
    if condicion:
        print(f"  ok   {texto}")
    else:
        FALLOS.append(texto)
        print(f"  MAL  {texto}" + (f" -- {detalle}" if detalle else ""))


def igual(texto, obtenido, esperado):
    comprobar(texto, obtenido == esperado,
              f"obtenido {obtenido!r}, esperado {esperado!r}")


def _avisar(_valor, _mensaje="", _extra=None):
    """El `avisar` del nucleo, callado: aqui no hay barra que mover."""


def _carpeta(raiz, nombre):
    """`Proyecto` adopta una carpeta que EXISTE: crearla es del que lo llama."""
    ruta = os.path.join(raiz, nombre)
    os.makedirs(ruta, exist_ok=True)
    return ruta


def main():
    raiz = tempfile.mkdtemp(prefix="p1_material_")
    try:
        print("== el material se parte en parrafos ==")
        trozos = p1_ingesta._trozos(MATERIAL)
        igual("tres parrafos, tres trozos", len(trozos), 3)
        comprobar("el segundo viene de una sola linea, con sus saltos cosidos",
                  "\n" not in trozos[1]["texto"]
                  and "version" in trozos[1]["texto"], trozos[1]["texto"])
        igual("los tiempos van a cero, no inventados",
              [(t["t_in"], t["t_out"]) for t in trozos], [(0.0, 0.0)] * 3)
        igual("las lineas en blanco de sobra no dejan trozos vacios",
              len(p1_ingesta._trozos("uno\n\n\n\n  \n\ndos")), 2)
        igual("sin material, ningun trozo", p1_ingesta._trozos("   "), [])

        print("\n== los params, normalizados ==")
        opciones = p1_ingesta._normalizar({"texto": MATERIAL, "titulo": "  El  caso  "})
        igual("el titulo se limpia de espacios de sobra",
              opciones["titulo"], "El caso")
        largo = "x" * (p1_ingesta.MAX_CARACTERES + 100)
        try:
            p1_ingesta._normalizar({"texto": largo})
            comprobar("un material pasado del tope se rechaza", False,
                      "no ha levantado ValueError")
        except ValueError as fallo:
            comprobar("un material pasado del tope se rechaza", True)
            comprobar("y el mensaje dice el tope",
                      str(p1_ingesta.MAX_CARACTERES) in str(fallo), str(fallo))
        igual("sin estricto se corta en vez de reventar la pantalla",
              len(p1_ingesta._normalizar({"texto": largo},
                                         estricto=False)["texto"]),
              p1_ingesta.MAX_CARACTERES)

        print("\n== ejecutar el paso de verdad ==")
        proyecto = Proyecto(_carpeta(raiz, "video"))
        estado = Estado(proyecto)
        estado.actualizar_params("ingesta", {"texto": MATERIAL,
                                             "titulo": "El caso"})
        estado.marcar_ejecutando("ingesta")
        salidas = p1_ingesta.ejecutar(proyecto, estado.params("ingesta"), _avisar)
        estado.completar("ingesta", salidas)

        igual("cuenta las palabras", salidas["palabras"], len(MATERIAL.split()))
        igual("y los parrafos", salidas["parrafos"], 3)
        comprobar("dice que no hay tiempos", salidas["sin_tiempos"] is True)
        comprobar("el resumen se lee de un vistazo",
                  "palabras de material escrito" in salidas["resumen"],
                  salidas["resumen"])

        # LAS SALIDAS SON CIFRAS. El transcript entero dentro de estado.json
        # seria justo lo que el nucleo sustituye por un resumen.
        for clave in ("transcript", "texto"):
            comprobar(f"'{clave}' NO va en las salidas selladas",
                      clave not in salidas)

        print("\n== los ficheros que quedan en la version ==")
        version = proyecto.ruta_paso("ingesta")
        for nombre in ("ingesta.json", "transcript.json", "material.txt"):
            comprobar(f"{nombre} esta en disco",
                      os.path.isfile(os.path.join(version, nombre)))
        plano = open(os.path.join(version, "material.txt"), encoding="utf-8").read()
        comprobar("material.txt se puede leer a ojo, sin JSON alrededor",
                  plano.startswith("La empresa reconocio"), plano[:40])

        print("\n== y el guion lo encuentra ==")
        trozos_leidos, metadatos, de_donde = fuentes.material_de(proyecto)
        igual("de_donde dice de donde salio", de_donde, "ingesta")
        igual("con sus tres trozos", len(trozos_leidos), 3)
        igual("y el titulo en los metadatos", metadatos["titulo"], "El caso")
        igual("las palabras cuadran con lo que cuenta `fuentes`",
              fuentes.palabras_de(proyecto), salidas["palabras"])
        # ESCASO ES UN AVISO, NO UN ERROR: con cuarenta palabras el guion se
        # inventa casi todo, y eso se dice ANTES de escribirlo. El umbral vive
        # en `fuentes` y no aqui, que es lo que hace que no haya dos opiniones.
        comprobar("cuarenta palabras SI son escasas, y se dice",
                  fuentes.material_escaso(proyecto),
                  f"{fuentes.palabras_de(proyecto)} palabras contra un "
                  f"umbral de {fuentes.PALABRAS_MATERIAL_SUFICIENTE}")
        abundante = Proyecto(_carpeta(raiz, "abundante"))
        p1_ingesta.ejecutar(abundante,
                            {"texto": (MATERIAL + "\n\n") * 6}, _avisar)
        comprobar("y con material de sobra ya no lo es",
                  not fuentes.material_escaso(abundante),
                  f"{fuentes.palabras_de(abundante)} palabras")

        print("\n== un material vacio FALLA, no se queda listo ==")
        otro = Proyecto(_carpeta(raiz, "vacio"))
        try:
            p1_ingesta.ejecutar(otro, {"texto": "   "}, _avisar)
            comprobar("ejecutar sin material levanta RuntimeError", False,
                      "ha terminado como si nada")
        except RuntimeError as fallo:
            comprobar("ejecutar sin material levanta RuntimeError", True)
            comprobar("y el mensaje dice que hay que escribir algo",
                      "material esta vacio" in str(fallo), str(fallo))

        print("\n== cambiar el material deja obsoleto lo de abajo ==")
        # es la razon de que el material sea un PASO y no un cajon suelto
        igual("recien hecho, el paso esta listo", estado.estado_de("ingesta"), "listo")
        estado.actualizar_params("ingesta", {"texto": MATERIAL + "\n\nY un dato mas."})
        igual("con otro material, obsoleto", estado.estado_de("ingesta"), "obsoleto")
    finally:
        shutil.rmtree(raiz, ignore_errors=True)

    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones:")
        for f in FALLOS:
            print(f"  - {f}")
        return 1
    print("P1 MATERIAL OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
