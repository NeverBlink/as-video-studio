"""Que hay vivo en web/app.js y que no. Funciones Y tablas de primer nivel.

`sin_llamar_js.py` encuentra lo que nadie NOMBRA, y con eso no se desmonta una
pantalla entera: las funciones de una pantalla se llaman entre ellas y ademas
estan nombradas en una tabla (`PANELES`, `PESTANAS`, `REPINTABLES`), asi que
todas parecen usadas mientras la tabla exista -- y la tabla parece usada mientras
alguna de ellas la nombre. Un corro perfecto.

Esta herramienta lo rompe mirando quien ENTRA desde fuera:

  * las SENTENCIAS de primer nivel (lo que no es una declaracion: llamadas,
    asignaciones, `addEventListener`);
  * lo que nombra `web/index.html`;
  * lo que se le pasa a `addEventListener`, que lo llama el navegador.

Desde ahi se camina el grafo --una funcion o una tabla estan vivas si algo vivo
las nombra-- hasta que no se anade nada. Lo que quede fuera no se puede alcanzar,
sea una funcion o sean cuarenta funciones y su tabla.

    python herramientas/alcanzables_js.py            # la lista
    python herramientas/alcanzables_js.py --quien X  # quien nombra a X, y desde donde
    python herramientas/alcanzables_js.py --borrar   # se lleva UNA vuelta

`--borrar` quita lo que la lista dice y para. UNA vuelta y no un bucle a
proposito: borrar deja sin usar lo que solo usaba lo borrado, asi que hay que
volver a correrla -- y entre vuelta y vuelta se mira que `node --check` sigue
pasando, que es lo que convierte una poda grande en varias pequenas.

QUE NO HACE. No entiende el codigo: cuenta NOMBRES fuera de comentarios y de
cadenas. Eso peca de generoso --un nombre citado en una tabla de datos cuenta
como uso-- y esa es la direccion en la que hay que pecar: da por vivo algo
muerto, nunca al contrario. Y con `${...}` dentro de una plantilla si mira, que
es codigo de verdad.

ANTES DE BORRAR, LO DE SIEMPRE: `node --check web/app.js`, las suites que leen
`app.js` (`prueba_presets_light`, `prueba_api`) y abrir la pantalla.
"""
import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "web", "app.js")
PORTADA = os.path.join(RAIZ, "web", "index.html")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sin_llamar_js import sin_comentarios          # noqa: E402


def _cierre(texto, abre):
    """El indice justo despues de la llave que cierra la que abre en `abre`.

    SOLO SE CUENTA EL PAR QUE ABRE, y no las tres clases de parentesis a la
    vez. Contandolas juntas, un literal de expresion regular con una llave
    dentro --`/[{}]/`, y hay-- desnivela la cuenta y el final de la funcion se
    calcula donde no es. Eso salio como un fichero partido por la mitad: se
    borro la cabecera de una funcion y su cuerpo se quedo suelto.
    """
    par = {"{": "}", "[": "]", "(": ")"}[texto[abre]]
    nivel, i = 0, abre
    while i < len(texto):
        if texto[i] == texto[abre]:
            nivel += 1
        elif texto[i] == par:
            nivel -= 1
            if nivel == 0:
                return i + 1
        i += 1
    return len(texto)


def piezas(codigo):
    """[(nombre, inicio, fin, clase)] de cada declaracion de primer nivel.

    Clase es 'funcion' o 'tabla'. De las tablas solo se recogen las que abren
    con `{` o `[` en la misma linea: son las que pueden esconder un corro de
    nombres dentro. Un `const N = 4` no crea dependencias y da igual.
    """
    fuera = []
    for m in re.finditer(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)",
                         codigo, re.MULTILINE):
        abre = codigo.find("{", m.end())
        if abre >= 0:
            fuera.append((m.group(1), m.start(), _cierre(codigo, abre), "funcion"))
    for m in re.finditer(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*[\{\[]",
                         codigo, re.MULTILINE):
        abre = m.end() - 1
        fuera.append((m.group(1), m.start(), _cierre(codigo, abre), "tabla"))
    fuera.sort(key=lambda x: x[1])

    # Y SE COMPRUEBA QUE NINGUN TRAMO SE SOLAPE CON EL SIGUIENTE. Es la senal de
    # que una cuenta de llaves salio mal: en este fichero las declaraciones de
    # primer nivel no se anidan, asi que un tramo que se come el principio del
    # de al lado esta mal medido y borrarlo partiria el fichero. Se dice y se
    # para, que es mejor que dejarlo a medias.
    for (n1, _a1, b1, _k1), (n2, a2, _b2, _k2) in zip(fuera, fuera[1:]):
        if b1 > a2:
            linea = codigo[:a2].count(chr(10)) + 1
            raise SystemExit(
                f"TRAMOS SOLAPADOS: «{n1}» se come el principio de «{n2}» "
                f"(app.js:{linea}). La cuenta de llaves de «{n1}» esta mal; "
                f"mira si dentro hay una expresion regular con llaves.")
    return fuera


def main():
    crudo = io.open(APP, encoding="utf-8").read()
    codigo = sin_comentarios(crudo)
    portada = io.open(PORTADA, encoding="utf-8").read()

    decl = piezas(codigo)
    porNombre = {n: (a, b, k) for n, a, b, k in decl}
    nombres = set(porNombre)

    def nombrados(texto):
        return {x for x in re.findall(r"[A-Za-z_$][\w$]*", texto) if x in nombres}

    if "--quien" in sys.argv:
        objetivo = sys.argv[sys.argv.index("--quien") + 1]
        print(f"QUIEN NOMBRA A {objetivo}:")
        for nombre, a, b, _k in decl:
            if nombre == objetivo:
                continue
            if re.search(r"\b" + re.escape(objetivo) + r"\b", codigo[a:b]):
                print(f"  [{nombre}]  app.js:{crudo[:a].count(chr(10)) + 1}")
        return 0

    # las SENTENCIAS de primer nivel: lo que queda al sacar las declaraciones
    trozos, fin = [], 0
    for _n, a, b, _k in decl:
        trozos.append(codigo[fin:a])
        fin = b
    trozos.append(codigo[fin:])
    sentencias = "".join(trozos)

    semillas = nombrados(sentencias) | nombrados(portada)
    for m in re.finditer(r"addEventListener\s*\([^,]+,\s*([A-Za-z_$][\w$]*)",
                         codigo):
        if m.group(1) in nombres:
            semillas.add(m.group(1))

    grafo = {n: nombrados(codigo[a:b]) for n, (a, b, _k) in porNombre.items()}
    vivos, cola = set(semillas), list(semillas)
    while cola:
        for siguiente in grafo.get(cola.pop(), ()):
            if siguiente not in vivos:
                vivos.add(siguiente)
                cola.append(siguiente)

    muertos = [(n, a, b, k) for n, a, b, k in decl if n not in vivos]
    if "--borrar" in sys.argv and muertos:
        # DE ATRAS HACIA DELANTE, para que los indices de los de arriba sigan
        # valiendo. Se lleva tambien el comentario pegado justo encima: es la
        # explicacion de lo que se va, y dejarla huerfana confunde mas que
        # borrarla. Se reconoce por ir sin linea en blanco en medio.
        salto = chr(10)
        nuevo = crudo
        for _n, a, b, _k in sorted(muertos, key=lambda x: x[1], reverse=True):
            ini = a
            while True:
                corte = nuevo[:ini].rstrip()
                if not corte.endswith("*/"):
                    break
                abre = corte.rfind("/*")
                if abre < 0 or (salto + salto) in nuevo[abre:ini]:
                    break
                ini = abre
            fin = b
            # el `;` de un `const X = [...];` va DETRAS del corchete, asi que no
            # entra en el tramo: sin esto queda un punto y coma suelto en medio
            # del fichero -- valido, y basura
            while fin < len(nuevo) and nuevo[fin] in ";":
                fin += 1
            while fin < len(nuevo) and nuevo[fin] == salto:
                fin += 1
            nuevo = nuevo[:ini] + nuevo[fin:]
        io.open(APP, "w", encoding="utf-8", newline="").write(nuevo)
        print(f"BORRADAS {len(muertos)} piezas "
              f"({crudo.count(chr(10)) - nuevo.count(chr(10))} lineas). "
              f"Vuelve a correrla.")
        return 0
    alto = lambda a, b: codigo[a:b].count(chr(10)) + 1        # noqa: E731
    peso = sum(alto(a, b) for _n, a, b, _k in muertos)
    print(f"{len(nombres)} piezas de primer nivel · {len(vivos)} vivas · "
          f"{len(muertos)} NO ({peso} lineas de {crudo.count(chr(10)) + 1})")
    print(f"semillas: {len(semillas)}\n")
    for n, a, b, k in muertos:
        print(f"  app.js:{crudo[:a].count(chr(10)) + 1:<6} {k:8} {n}  "
              f"({alto(a, b)} lineas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
