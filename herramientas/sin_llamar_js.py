"""Funciones de web/app.js que nadie llama. El gemelo de `huerfanas_js.py`.

`huerfanas_js.py` busca lo que FALTA --llamadas a funciones que ya no existen--
y esta busca lo que SOBRA: funciones definidas que nadie nombra en ningun sitio.
Las dos hacen falta al podar, y por motivos distintos: quitar una pantalla deja
las dos cosas a la vez --llamadas a lo que se fue y funciones que se quedaron
sin quien las llame-- y cada herramienta ve solo la mitad.

COMO CUENTA, y por que asi:

  * Se miran los nombres FUERA de comentarios y de cadenas, con el mismo
    troceador que `huerfanas_js.py`: un nombre citado en un comentario no es una
    llamada, y contarlo deja huerfanas invisibles para siempre.
  * Pero se mira TAMBIEN `web/index.html` con las cadenas dentro: ahi los
    nombres viven en atributos (`onclick="algo()"`) y en `index.html` no hay
    codigo que confundir.
  * Y se avisa aparte de los nombres que aparecen SOLO dentro de una cadena de
    app.js: son las que se llaman por nombre (`window[nombre]`, una tabla de
    acciones) y no se pueden borrar sin mirar.

    python herramientas/sin_llamar_js.py            # la lista
    python herramientas/sin_llamar_js.py --arbol X  # que llama a X, y a quien llama X

NO ES UN ANALISIS DE ALCANZABILIDAD. Un corro de funciones que solo se llaman
entre ellas no sale aqui: hay que borrar una vuelta, volver a correrla, y repetir
hasta que no salga nada. Que haga falta pasar varias veces es la senal de que
habia un arbol muerto y no una funcion suelta.
"""
import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(RAIZ, "web", "app.js")
PORTADA = os.path.join(RAIZ, "web", "index.html")


def sin_comentarios(crudo):
    """El fichero con los comentarios y el TEXTO de las cadenas en blanco.

    Lo que va dentro de `${...}` en una plantilla SI se conserva, porque es
    codigo de verdad: `${nombreIdioma(x)}` es una llamada. `huerfanas_js.py`
    dejaba en blanco todo menos las llaves, y eso ahi solo hace que se le
    escapen llamadas --peca de callado--, pero aqui la cuenta va al contrario:
    una funcion que solo se llama desde una plantilla parecia no llamarse
    desde ningun sitio. Se borraron cuatro asi, y lo dijo `prueba_api`.

    Los espacios se ponen uno por caracter para que las lineas y los indices
    sigan cuadrando con el fichero de verdad.
    """
    def enblanco(trozo):
        return re.sub(r"[^\n]", " ", trozo)

    fuera, i, n = [], 0, len(crudo)
    while i < n:
        c = crudo[i]
        if c == "/" and i + 1 < n and crudo[i + 1] == "/":
            j = crudo.find("\n", i)
            j = n if j < 0 else j
            fuera.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and crudo[i + 1] == "*":
            j = crudo.find("*/", i + 2)
            j = n if j < 0 else j + 2
            fuera.append(enblanco(crudo[i:j]))
            i = j
        elif c == "`":
            # LA PLANTILLA, TROZO A TROZO: el texto se borra y lo de dentro de
            # `${...}` se queda. Se cuentan las llaves para que un objeto o
            # otra plantilla anidada dentro de la expresion no la corte.
            fuera.append(" ")
            j = i + 1
            while j < n and crudo[j] != "`":
                if crudo[j] == "\\":
                    fuera.append("  ")
                    j += 2
                    continue
                if crudo[j] == "$" and j + 1 < n and crudo[j + 1] == "{":
                    nivel, k = 0, j + 1
                    while k < n:
                        if crudo[k] == "{":
                            nivel += 1
                        elif crudo[k] == "}":
                            nivel -= 1
                            if nivel == 0:
                                k += 1
                                break
                        k += 1
                    # el `$` en blanco y la expresion tal cual, recursivamente:
                    # dentro puede haber cadenas y otra plantilla
                    fuera.append(" ")
                    fuera.append(sin_comentarios(crudo[j + 1:k]))
                    j = k
                    continue
                fuera.append("\n" if crudo[j] == "\n" else " ")
                j += 1
            fuera.append(" ")
            i = min(j + 1, n)
        elif c in "'\"":
            j, cierre = i + 1, c
            while j < n:
                if crudo[j] == "\\":
                    j += 2
                    continue
                if crudo[j] == cierre:
                    j += 1
                    break
                j += 1
            fuera.append(enblanco(crudo[i:j]))
            i = j
        else:
            fuera.append(c)
            i += 1
    return "".join(fuera)


def definiciones(codigo):
    """{nombre: linea} de cada `function nombre(`, en el orden del fichero."""
    donde = {}
    for m in re.finditer(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)",
                         codigo, re.MULTILINE):
        donde.setdefault(m.group(1), codigo[:m.start()].count("\n") + 1)
    return donde


def repetidas(codigo):
    """{nombre: [lineas]} de los nombres declarados MAS DE UNA VEZ.

    NO ES UN AVISO DE ESTILO. En JavaScript la segunda `function f(){}` se lleva
    la primera por delante --y sin un solo error, porque las declaraciones se
    izan-- asi que la de arriba deja de ejecutarse y sigue ahi, leyendose como
    si funcionara. Paso: el coste del video que se ensena antes de generar
    compartia nombre con el medidor del video ya empezado, y el hueco de al lado
    del boton llevaba vacio desde el dia que se escribio.
    """
    todas = {}
    for m in re.finditer(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)",
                         codigo, re.MULTILINE):
        todas.setdefault(m.group(1), []).append(codigo[:m.start()].count("\n") + 1)
    return {n: ls for n, ls in todas.items() if len(ls) > 1}


def _cuenta(codigo, nombre):
    return len(re.findall(r"\b" + re.escape(nombre) + r"\b", codigo))


def main():
    crudo = io.open(APP, encoding="utf-8").read()
    codigo = sin_comentarios(crudo)
    portada = io.open(PORTADA, encoding="utf-8").read()
    donde = definiciones(codigo)

    if "--arbol" in sys.argv:
        objetivo = sys.argv[sys.argv.index("--arbol") + 1]
        lineas = codigo.split("\n")
        print(f"QUIEN NOMBRA A {objetivo}:")
        for numero, linea in enumerate(lineas, 1):
            if re.search(r"\b" + re.escape(objetivo) + r"\b", linea):
                dueno = [n for n, ln in donde.items() if ln <= numero]
                dueno = max(dueno, key=lambda n: donde[n]) if dueno else "?"
                print(f"  {numero:6}  [{dueno}]  {linea.strip()[:110]}")
        return 0

    sueltas, solo_en_texto = [], []
    for nombre, linea in sorted(donde.items(), key=lambda x: x[1]):
        # una vez es su propia definicion
        if _cuenta(codigo, nombre) > 1:
            continue
        if re.search(r"\b" + re.escape(nombre) + r"\b", portada):
            continue
        if _cuenta(crudo, nombre) > _cuenta(codigo, nombre):
            solo_en_texto.append((nombre, linea))
        else:
            sueltas.append((nombre, linea))

    print(f"{len(donde)} funciones con nombre en web/app.js")
    dobles = repetidas(codigo)
    if dobles:
        print(f"\nDECLARADAS DOS VECES: {len(dobles)} -- LA DE ARRIBA NO CORRE")
        for nombre, lineas in dobles.items():
            print(f"  {nombre}: app.js:{', '.join(str(x) for x in lineas)}")
    print(f"\nNADIE LAS LLAMA: {len(sueltas)}")
    for nombre, linea in sueltas:
        print(f"  app.js:{linea:<6} {nombre}")
    if solo_en_texto:
        print(f"\nSOLO SE NOMBRAN EN UN COMENTARIO O UNA CADENA: "
              f"{len(solo_en_texto)} -- MIRAR ANTES DE BORRAR")
        for nombre, linea in solo_en_texto:
            print(f"  app.js:{linea:<6} {nombre}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
