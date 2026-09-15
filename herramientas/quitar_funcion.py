"""Borra funciones de nivel superior de un modulo, por nombre y sin dejar restos.

Para que
--------
Podar un fichero grande a mano se hace con numeros de linea, y los numeros de
linea se mueven en cuanto borras la primera cosa. Esto lo hace por AST: pide los
nombres y calcula los limites reales de cada funcion, incluidos sus decoradores
y el bloque de comentarios que la precede --que en este codigo es la mitad del
valor y quedarse huerfano encima de otra funcion es peor que borrarlo--.

Comprueba dos cosas antes de escribir, y por eso se puede usar en cadena:

  1. que la funcion EXISTE (si no, para: un nombre mal escrito que no avisa
     deja pensando que ya estaba quitada);
  2. que el resultado SIGUE SIENDO Python valido.

Y avisa de quien seguia llamandola, que es lo que hay que arreglar despues.

    python herramientas/quitar_funcion.py <fichero.py> nombre1 nombre2 ...
                                          [--aplicar]
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import re
import sys


def _limite_arriba(lineas, inicio):
    """Sube por los comentarios y decoradores pegados a la funcion. -> indice 0-based

    Un comentario separado por una linea en blanco NO se lleva: ahi ya no
    describe a esta funcion, describe la seccion.
    """
    i = inicio
    while i > 0:
        anterior = lineas[i - 1].strip()
        if anterior.startswith("#") or anterior.startswith("@"):
            i -= 1
            continue
        break
    return i


def quitar(ruta, nombres, aplicar=False):
    texto = io.open(ruta, encoding="utf-8").read()
    lineas = texto.splitlines(keepends=True)
    arbol = ast.parse(texto)

    porNombre = {}
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            porNombre[nodo.name] = nodo

    faltan = [n for n in nombres if n not in porNombre]
    if faltan:
        print(f"NO EXISTEN en {os.path.basename(ruta)}: {', '.join(faltan)}")
        print(f"  las que hay: {', '.join(sorted(porNombre))[:400]}")
        return 1

    # de abajo arriba, para que borrar no mueva los limites de las siguientes
    tramos = []
    for nombre in nombres:
        nodo = porNombre[nombre]
        arriba = _limite_arriba(lineas, nodo.lineno - 1)
        abajo = nodo.end_lineno                     # 1-based, exclusivo al usar [a:b]
        # se lleva las lineas en blanco que quedan detras, para no dejar huecos
        while abajo < len(lineas) and not lineas[abajo].strip():
            abajo += 1
        tramos.append((arriba, abajo, nombre))
    tramos.sort(reverse=True)

    nuevas = list(lineas)
    for arriba, abajo, nombre in tramos:
        cuantas = abajo - arriba
        print(f"  quito {nombre}() -- {cuantas} lineas ({arriba + 1}-{abajo})")
        del nuevas[arriba:abajo]

    resultado = "".join(nuevas)
    try:
        ast.parse(resultado)
    except SyntaxError as fallo:
        print(f"EL RESULTADO NO ES PYTHON VALIDO: {fallo}")
        return 1

    # quien seguia llamandolas
    quedan = []
    for nombre in nombres:
        usos = len(re.findall(rf"\b{re.escape(nombre)}\s*\(", resultado))
        if usos:
            quedan.append((nombre, usos))
    if quedan:
        print("  OJO, siguen llamandose (hay que arreglar esos sitios):")
        for nombre, usos in quedan:
            print(f"    {nombre}(): {usos} usos")

    if aplicar:
        io.open(ruta, "w", encoding="utf-8", newline="").write(resultado)
        print(f"  escrito: {ruta}")
    else:
        print("  (simulacro: nada escrito)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("fichero")
    ap.add_argument("nombres", nargs="+")
    ap.add_argument("--aplicar", action="store_true")
    args = ap.parse_args(argv)
    return quitar(args.fichero, args.nombres, args.aplicar)


if __name__ == "__main__":
    raise SystemExit(main())
