"""Llamadas que le pasan a un paso un argumento que su firma no tiene.

QUE FALLO ARREGLA
-----------------
El 24-08-2026 el generador de presets moria con:

    generar_guia() got an unexpected keyword argument 'indicaciones'

`app.py` le pasaba `indicaciones=` a `estilo.generar_guia` desde el modo light
--con un comentario explicando muy bien para que servia-- y la firma no lo
recibia. No fallaba a medias: fallaba ENTERO, y solo por el camino de «estilo
desde una URL mas una frase», que es la forma normal de pedir un canal.

Es el mismo fallo que un cajon que no llega al prompt, pero una version peor:
ahi el dato se pierde en silencio y aqui el paso se muere. Lo que tienen en
comun es que **nadie lo ve hasta que alguien pulsa ese boton concreto**: Python
no comprueba las firmas hasta que la llamada ocurre, y la llamada ocurre dentro
de un trabajo en segundo plano.

QUE COMPRUEBA
-------------
Recorre los ficheros que llaman a los modulos de `pasos/` y `nucleo/` y, para
cada llamada `modulo.funcion(...)`, mira los nombres de los argumentos con
nombre contra la firma de verdad. Resuelve tres formas de nombrar un modulo,
que son las tres que se usan en el repo:

    from pasos import estilo          ->  estilo.generar_guia(...)
    estilo = _estilo()                ->  estilo.generar_guia(...)
    PASOS_MODULOS.estilo.generar_guia(...)

LO QUE NO COMPRUEBA, y es a proposito
-------------------------------------
Los argumentos POSICIONALES: cuantos van y en que orden depende de cosas que un
analisis estatico no sabe (`*args`, un desempaquetado). Aqui interesa el fallo
que de verdad pasa, que es el del nombre mal escrito o el parametro que nunca
se llego a anadir.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\herramientas\\firmas_py.py
"""
import ast
import importlib
import inspect
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

#: Donde se llama a los pasos desde fuera. app.py es el gordo; los demas son
#: los guiones sueltos que tambien orquestan.
FICHEROS = ["app.py", "generar_api.py"]

#: Y todo lo de pasos/ y nucleo/ entre si: un modulo que llama a otro con un
#: nombre que ya no existe se rompe igual.
for carpeta in ("pasos", "nucleo"):
    for nombre in sorted(os.listdir(os.path.join(RAIZ, carpeta))):
        if nombre.endswith(".py") and not nombre.startswith("__"):
            FICHEROS.append(f"{carpeta}/{nombre}")


def modulos():
    """nombre corto -> modulo, de todo lo importable de pasos/ y nucleo/."""
    encontrados = {}
    for paquete in ("pasos", "nucleo"):
        try:
            raiz = importlib.import_module(paquete)
        except Exception as fallo:                            # noqa: BLE001
            print(f"AVISO: no se ha podido importar {paquete}: {fallo}")
            continue
        for nombre in dir(raiz):
            hijo = getattr(raiz, nombre)
            if inspect.ismodule(hijo):
                encontrados[nombre] = hijo
    return encontrados


def firma_de(modulo, nombre):
    """La firma de `modulo.nombre`, o None si no es algo que se pueda llamar."""
    fn = getattr(modulo, nombre, None)
    if not (inspect.isfunction(fn) or inspect.isclass(fn)):
        return None
    try:
        return inspect.signature(fn)
    except (TypeError, ValueError):
        return None


def acepta(firma, clave):
    """Esa firma admite un argumento con ese nombre."""
    for parametro in firma.parameters.values():
        if parametro.kind is inspect.Parameter.VAR_KEYWORD:
            return True                                   # **kwargs se lo traga
        if (parametro.name == clave
                and parametro.kind is not inspect.Parameter.POSITIONAL_ONLY):
            return True
    return False


class Rastreador(ast.NodeVisitor):
    """Ata cada nombre local al modulo que representa, y revisa las llamadas."""

    def __init__(self, fichero, conocidos):
        self.fichero = fichero
        self.conocidos = conocidos
        self.alias = {}          # nombre en el codigo -> nombre de modulo
        self.hallazgos = []

    # -- de donde salen los nombres
    def visit_ImportFrom(self, nodo):
        if (nodo.module or "").split(".")[0] in ("pasos", "nucleo") or nodo.level:
            for cual in nodo.names:
                if cual.name in self.conocidos:
                    self.alias[cual.asname or cual.name] = cual.name
        self.generic_visit(nodo)

    def visit_Import(self, nodo):
        for cual in nodo.names:
            corto = cual.name.split(".")[-1]
            if corto in self.conocidos:
                self.alias[cual.asname or corto] = corto
        self.generic_visit(nodo)

    def visit_Assign(self, nodo):
        # `estilo = _estilo()` y `estilo = PASOS_MODULOS.estilo`
        destinos = [d.id for d in nodo.targets if isinstance(d, ast.Name)]
        cual = self._modulo_de(nodo.value)
        if cual:
            for destino in destinos:
                self.alias[destino] = cual
        self.generic_visit(nodo)

    def _modulo_de(self, valor):
        """Que modulo representa esta expresion, si representa alguno."""
        if (isinstance(valor, ast.Call) and isinstance(valor.func, ast.Name)
                and valor.func.id.startswith("_")):
            corto = valor.func.id.lstrip("_")
            if corto in self.conocidos:
                return corto
        if (isinstance(valor, ast.Attribute)
                and isinstance(valor.value, ast.Name)
                and valor.value.id in ("PASOS_MODULOS", "pasos")
                and valor.attr in self.conocidos):
            return valor.attr
        return None

    # -- y aqui se comprueba
    def visit_Call(self, nodo):
        self.generic_visit(nodo)
        if not isinstance(nodo.func, ast.Attribute):
            return
        cual = None
        raiz = nodo.func.value
        if isinstance(raiz, ast.Name):
            cual = self.alias.get(raiz.id)
        else:
            cual = self._modulo_de(raiz)
        if not cual:
            return
        modulo = self.conocidos.get(cual)
        firma = firma_de(modulo, nodo.func.attr) if modulo else None
        if firma is None:
            return
        for palabra in nodo.keywords:
            if palabra.arg is None:                       # **algo: no se sabe
                return
            if not acepta(firma, palabra.arg):
                self.hallazgos.append({
                    "fichero": self.fichero, "linea": nodo.lineno,
                    "llamada": f"{cual}.{nodo.func.attr}",
                    "sobra": palabra.arg, "firma": str(firma),
                })


def main():
    conocidos = modulos()
    print(f"{len(conocidos)} modulos, {len(FICHEROS)} ficheros")
    hallazgos = []
    for relativo in FICHEROS:
        ruta = os.path.join(RAIZ, relativo.replace("/", os.sep))
        if not os.path.exists(ruta):
            continue
        with open(ruta, "r", encoding="utf-8") as fh:
            try:
                arbol = ast.parse(fh.read(), filename=ruta)
            except SyntaxError as fallo:
                print(f"FALLO  {relativo} no compila: {fallo}")
                hallazgos.append({"fichero": relativo, "linea": fallo.lineno,
                                  "llamada": "(sintaxis)", "sobra": str(fallo),
                                  "firma": ""})
                continue
        rastreador = Rastreador(relativo, conocidos)
        rastreador.visit(arbol)
        hallazgos.extend(rastreador.hallazgos)

    if not hallazgos:
        print("\nFIRMAS OK: ninguna llamada pasa un argumento que no existe")
        return 0
    print(f"\n{len(hallazgos)} LLAMADAS CON UN ARGUMENTO QUE NO EXISTE:\n")
    for h in hallazgos:
        print(f"  {h['fichero']}:{h['linea']}  {h['llamada']}(… {h['sobra']}=…)")
        print(f"      la firma es {h['llamada']}{h['firma']}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
