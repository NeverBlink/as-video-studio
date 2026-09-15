"""Llamadas a `modulo.algo()` donde `algo` ya no existe en ese modulo.

Para que
--------
`indefinidos_py.py` caza los NOMBRES sueltos sin declarar, y no ve esto:

    estilo.ficha(proyecto)      # `ficha` se borro de pasos/estilo.py

Eso pasa `ast.parse`, pasa el import del modulo y revienta en la peticion que
lo llama -- y solo en esa. Al podar features es EL fallo tipico: se borra una
funcion, se arreglan los sitios que la llamaban por su nombre y se queda el que
la llamaba por su modulo.

Se descubrio asi: al quitar el video de referencia se borro `estilo.ficha` y
`app._preseleccionar_estilo` seguia llamandola. El sintoma fue una peticion que
no contestaba, no un error de importacion.

Que comprueba
-------------
Para cada `import x` / `from . import x` de los modulos DEL PROYECTO, mira todos
los `x.algo` del fichero y avisa si `algo` no esta declarado en `x` (funcion,
clase o asignacion de nivel superior).

Lo hace por AST y sin importar nada: asi no hace falta que el entorno tenga las
dependencias ni se ejecuta codigo de nadie.

    python herramientas/atributos_py.py [fichero.py ...]

Sin argumentos, mira app.py y todo pasos/ y nucleo/.
"""
from __future__ import annotations

import argparse
import ast
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: LO QUE TIENE TODO MODULO Y NO ESTA ESCRITO EN NINGUNO. Los pone Python al
#: importar, asi que no aparecen leyendo el fichero y salian como atributos
#: inexistentes: `io.open(login_cli.__file__)` --leer el propio codigo de un
#: modulo, que es como se comprueba que un prompt dice lo que tiene que decir--
#: se cantaba como un fallo en cada suite que lo usa.
DE_TODO_MODULO = frozenset((
    "__file__", "__name__", "__doc__", "__dict__", "__loader__", "__spec__",
    "__package__", "__builtins__", "__path__", "__all__", "__cached__",
))

#: Lo que un modulo EXPONE: funciones, clases y asignaciones de nivel superior.
#: Tambien lo que reexporta con `from x import y`, que para quien lo usa desde
#: fuera es un atributo igual de valido.
def _declarados(ruta):
    try:
        arbol = ast.parse(io.open(ruta, encoding="utf-8").read())
    except (OSError, SyntaxError):
        return None
    nombres = set()
    for nodo in arbol.body:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nombres.add(nodo.name)
        elif isinstance(nodo, ast.Assign):
            for destino in nodo.targets:
                if isinstance(destino, ast.Name):
                    nombres.add(destino.id)
        elif isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            nombres.add(nodo.target.id)
        elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
            for alias in nodo.names:
                nombres.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(nodo, ast.Try):
            # los imports de este codigo van dentro de un try/except ImportError
            for rama in list(nodo.body) + list(nodo.orelse) + [
                    x for m in nodo.handlers for x in m.body]:
                if isinstance(rama, (ast.Import, ast.ImportFrom)):
                    for alias in rama.names:
                        nombres.add(alias.asname or alias.name.split(".")[0])
                elif isinstance(rama, ast.Assign):
                    for destino in rama.targets:
                        if isinstance(destino, ast.Name):
                            nombres.add(destino.id)
    return nombres


def _modulos_del_proyecto():
    """{nombre: ruta} de los modulos propios, por su nombre de import."""
    mapa = {}
    for carpeta in ("pasos", "nucleo"):
        base = os.path.join(RAIZ, carpeta)
        if not os.path.isdir(base):
            continue
        for nombre in os.listdir(base):
            if nombre.endswith(".py") and not nombre.startswith("__"):
                mapa[nombre[:-3]] = os.path.join(base, nombre)
    return mapa


def revisar(rutas):
    propios = _modulos_del_proyecto()
    cache = {}
    fallos = []

    for ruta in rutas:
        try:
            texto = io.open(ruta, encoding="utf-8").read()
            arbol = ast.parse(texto)
        except (OSError, SyntaxError) as fallo:
            print(f"{ruta}: no se puede leer ({fallo})")
            continue

        # que modulos propios se importan aqui, y con que nombre local
        locales = {}
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.Import):
                for alias in nodo.names:
                    corto = alias.name.split(".")[-1]
                    if corto in propios:
                        locales[alias.asname or corto] = corto
            elif isinstance(nodo, ast.ImportFrom):
                for alias in nodo.names:
                    if alias.name in propios:
                        locales[alias.asname or alias.name] = alias.name

        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Attribute):
                continue
            if not isinstance(nodo.value, ast.Name):
                continue
            modulo = locales.get(nodo.value.id)
            if not modulo:
                continue
            if modulo not in cache:
                cache[modulo] = _declarados(propios[modulo])
            expone = cache[modulo]
            if expone is None or nodo.attr in expone:
                continue
            if nodo.attr in DE_TODO_MODULO:
                continue
            fallos.append((ruta, nodo.lineno, nodo.value.id, modulo, nodo.attr))

    if not fallos:
        print(f"OK: {len(rutas)} ficheros, ningun atributo de modulo que no exista")
        return 0

    print(f"ATRIBUTOS QUE NO EXISTEN: {len(fallos)}")
    for ruta, linea, local, modulo, attr in sorted(fallos):
        rel = os.path.relpath(ruta, RAIZ)
        marca = f"{local}.{attr}"
        extra = f" (es pasos/{modulo}.py)" if local != modulo else ""
        print(f"  {marca:38} {rel}:{linea}{extra}")
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ficheros", nargs="*")
    args = ap.parse_args(argv)

    if args.ficheros:
        rutas = [os.path.abspath(f) for f in args.ficheros]
    else:
        rutas = [os.path.join(RAIZ, "app.py")]
        for carpeta in ("pasos", "nucleo"):
            base = os.path.join(RAIZ, carpeta)
            if os.path.isdir(base):
                rutas += [os.path.join(base, n) for n in sorted(os.listdir(base))
                          if n.endswith(".py")]
    rutas = [r for r in rutas if os.path.isfile(r)]
    return revisar(rutas)


if __name__ == "__main__":
    raise SystemExit(main())
