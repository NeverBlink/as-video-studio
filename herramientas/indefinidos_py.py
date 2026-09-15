"""Nombres USADOS y nunca declarados en el Python del estudio.

El gemelo de `indefinidos_js.py`, y existe por el mismo motivo: Python no
comprueba un nombre hasta que la linea se ejecuta, y aqui casi todas las lineas
que importan se ejecutan dentro de un trabajo en segundo plano. O se pulsa ESE
boton, o no se entera nadie.

EL FALLO QUE ARREGLA, visto el 07-09-2026
-----------------------------------------
El redactor recien estrenado se caia entero con

    NameError: name '_exigir_pasos' is not defined

`app.py:_redactor()` llamaba a un ayudante que no existe en ese fichero --el que
hay se llama de otra forma y esta escrito a mano en `_direccion()`--. La suite
entera pasaba en verde: 748 comprobaciones, y ninguna llegaba a esa linea porque
para llegar hay que lanzar el trabajo. Se descubrio lanzandolo, veinte minutos
de agente por delante, con las dos llamadas caidas en el primer segundo.

COMO MIRA
---------
Sin importar nada y sin ejecutar nada: se lee el AST y se resuelve cada nombre
contra los sitios donde puede haberse declarado -- los builtins, lo de nivel de
modulo (imports, def, class, asignaciones) y, dentro de una funcion, sus
parametros y todo lo que se le asigne.

**Es a proposito insensible al flujo**: un nombre asignado en cualquier rama de
la funcion cuenta como declarado en toda ella. Un `if` que asigna y un `else`
que lee son un fallo de verdad, pero solo a veces y solo con ciertos datos;
marcarlo aqui llenaria el informe de avisos que hay que ir a comprobar a mano, y
un informe que grita no lo lee nadie -- que es exactamente la leccion que dejo
escrita el de JavaScript. Lo que este caza es lo otro: el nombre que NO existe
en ninguna parte, que falla siempre.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\herramientas\\indefinidos_py.py
"""
import ast
import builtins
import io
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

import firmas_py                                              # noqa: E402

#: Los mismos ficheros que vigila `firmas_py`: app.py, los guiones sueltos y
#: todo pasos/ y nucleo/. Una lista aparte se quedaria vieja el dia que se anada
#: un modulo, y ese dia nadie se acordaria de esta.
FICHEROS = firmas_py.FICHEROS

#: Nombres que el interprete pone y no se escriben en ningun sitio.
IMPLICITOS = {"__name__", "__file__", "__doc__", "__package__", "__spec__",
              "__loader__", "__builtins__", "__debug__", "__class__",
              "__module__", "__qualname__", "__annotations__", "__dict__"}

BUILTINS = set(dir(builtins)) | IMPLICITOS


def _nombres_de(destino):
    """Los nombres que ata un objetivo de asignacion, desempaquetados."""
    if isinstance(destino, ast.Name):
        return {destino.id}
    if isinstance(destino, (ast.Tuple, ast.List)):
        atados = set()
        for hijo in destino.elts:
            atados |= _nombres_de(hijo)
        return atados
    if isinstance(destino, ast.Starred):
        return _nombres_de(destino.value)
    return set()                    # a.b = / a[0] = no declaran ningun nombre


def _atados_en(nodo, dentro_de_funcion=False):
    """Todo lo que un cuerpo declara: imports, def, class y asignaciones.

    No entra en los cuerpos de las funciones de dentro (esos son su propio
    ambito) pero SI en los `if`, `for`, `try` y `with`, que no lo son.
    """
    atados = set()

    def recorrer(hijos):
        for nodo_hijo in hijos:
            atados.update(_declara(nodo_hijo))
            if isinstance(nodo_hijo, (ast.FunctionDef, ast.AsyncFunctionDef,
                                      ast.ClassDef, ast.Lambda)):
                continue            # su cuerpo es otro ambito
            recorrer(list(ast.iter_child_nodes(nodo_hijo)))

    recorrer(list(ast.iter_child_nodes(nodo)))
    if dentro_de_funcion and isinstance(nodo, (ast.FunctionDef,
                                               ast.AsyncFunctionDef,
                                               ast.Lambda)):
        atados |= _parametros_de(nodo)
    return atados


def _declara(nodo):
    """Los nombres que ESTE nodo declara, sin bajar a sus hijos."""
    if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {nodo.name}
    if isinstance(nodo, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in nodo.names}
    if isinstance(nodo, ast.Assign):
        atados = set()
        for destino in nodo.targets:
            atados |= _nombres_de(destino)
        return atados
    if isinstance(nodo, (ast.AugAssign, ast.AnnAssign)):
        return _nombres_de(nodo.target)
    if isinstance(nodo, ast.NamedExpr):                        # el walrus
        return _nombres_de(nodo.target)
    if isinstance(nodo, (ast.For, ast.AsyncFor)):
        return _nombres_de(nodo.target)
    if isinstance(nodo, (ast.With, ast.AsyncWith)):
        atados = set()
        for item in nodo.items:
            if item.optional_vars is not None:
                atados |= _nombres_de(item.optional_vars)
        return atados
    if isinstance(nodo, ast.ExceptHandler):
        return {nodo.name} if nodo.name else set()
    if isinstance(nodo, (ast.Global, ast.Nonlocal)):
        return set(nodo.names)
    if isinstance(nodo, ast.comprehension):
        return _nombres_de(nodo.target)
    if isinstance(nodo, ast.MatchAs):
        return {nodo.name} if nodo.name else set()
    if isinstance(nodo, ast.MatchStar):
        return {nodo.name} if nodo.name else set()
    if isinstance(nodo, ast.MatchMapping):
        return {nodo.rest} if nodo.rest else set()
    return set()


def _parametros_de(funcion):
    args = funcion.args
    todos = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    nombres = {a.arg for a in todos}
    for extra in (args.vararg, args.kwarg):
        if extra is not None:
            nombres.add(extra.arg)
    return nombres


class Rastreador(ast.NodeVisitor):
    """Recorre un fichero llevando la pila de ambitos. -> self.hallazgos"""

    def __init__(self, fichero, globales=None):
        self.fichero = fichero
        self.hallazgos = []
        self.ambitos = [set(globales or ())]

    # -------------------------------------------------------------- ambitos
    def _con_ambito(self, nodo, atados, hijos):
        self.ambitos.append(set(atados))
        for hijo in hijos:
            self.visit(hijo)
        self.ambitos.pop()

    def visit_FunctionDef(self, nodo):                        # noqa: N802
        self._visitar_funcion(nodo)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _visitar_funcion(self, nodo):
        # los decoradores y los defectos se evaluan FUERA, en el ambito de arriba
        for hijo in nodo.decorator_list:
            self.visit(hijo)
        for defecto in list(nodo.args.defaults) + [d for d in nodo.args.kw_defaults if d]:
            self.visit(defecto)
        self._visitar_anotaciones(nodo)
        self._con_ambito(nodo, _atados_en(nodo, dentro_de_funcion=True),
                         nodo.body)

    def _visitar_anotaciones(self, nodo):
        args = nodo.args
        for arg in (list(args.posonlyargs) + list(args.args)
                    + list(args.kwonlyargs) + [args.vararg, args.kwarg]):
            if arg is not None and arg.annotation is not None:
                self.visit(arg.annotation)
        if nodo.returns is not None:
            self.visit(nodo.returns)

    def visit_Lambda(self, nodo):                             # noqa: N802
        for defecto in list(nodo.args.defaults) + [d for d in nodo.args.kw_defaults if d]:
            self.visit(defecto)
        self._con_ambito(nodo, _atados_en(nodo, dentro_de_funcion=True),
                         [nodo.body])

    def visit_ClassDef(self, nodo):                           # noqa: N802
        for hijo in nodo.decorator_list + nodo.bases + nodo.keywords:
            self.visit(hijo)
        # EL CUERPO DE UNA CLASE NO ES UN AMBITO QUE HEREDEN SUS METODOS, pero
        # si declara nombres para sus propias lineas. Se apila como uno mas: lo
        # que se pierde es marcar un atributo de clase usado desde un metodo sin
        # `self.`, que es un fallo distinto y muy poco frecuente.
        self._con_ambito(nodo, _atados_en(nodo), nodo.body)

    def _visitar_comprension(self, nodo, partes):
        atados = set()
        for generador in nodo.generators:
            atados |= _nombres_de(generador.target)
        self._con_ambito(nodo, atados, list(nodo.generators) + partes)

    def visit_ListComp(self, nodo):                           # noqa: N802
        self._visitar_comprension(nodo, [nodo.elt])

    visit_SetComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp

    def visit_DictComp(self, nodo):                           # noqa: N802
        self._visitar_comprension(nodo, [nodo.key, nodo.value])

    # --------------------------------------------------------------- nombres
    def visit_Name(self, nodo):                               # noqa: N802
        if not isinstance(nodo.ctx, ast.Load):
            return
        if nodo.id in BUILTINS:
            return
        for ambito in self.ambitos:
            if nodo.id in ambito:
                return
        self.hallazgos.append({"fichero": self.fichero, "linea": nodo.lineno,
                               "nombre": nodo.id})


def revisar(ficheros=None, raiz=RAIZ):
    """{nombre: [(fichero, linea), ...]} de lo usado y nunca declarado."""
    sueltos = {}
    for relativo in (ficheros if ficheros is not None else FICHEROS):
        ruta = os.path.join(raiz, relativo.replace("/", os.sep))
        if not os.path.exists(ruta):
            continue
        arbol = ast.parse(io.open(ruta, encoding="utf-8").read(), filename=ruta)
        rastreador = Rastreador(relativo, _atados_en(arbol))
        for hijo in arbol.body:
            rastreador.visit(hijo)
        for hallazgo in rastreador.hallazgos:
            sueltos.setdefault(hallazgo["nombre"], []).append(
                (hallazgo["fichero"], hallazgo["linea"]))
    return sueltos


def main():
    sueltos = revisar()
    if not sueltos:
        print(f"OK: {len(FICHEROS)} ficheros, ningun nombre sin declarar")
        return 0
    print(f"NOMBRES SIN DECLARAR: {len(sueltos)}")
    for nombre, sitios in sorted(sueltos.items()):
        donde = ", ".join(f"{f}:{l}" for f, l in sitios[:6])
        print(f"  {nombre:32s} {donde}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
