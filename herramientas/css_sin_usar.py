"""Clases e ids de web/estilo.css que no aparecen en ningun sitio.

Al quitar una pantalla, su CSS se queda: no da error, no se ve, y engorda el
fichero que el navegador descarga en cada visita. Y lo peor no es el peso, es
que se lee: quien busca de que color es una tarjeta encuentra tres reglas para
una clase que ya no existe y no sabe cual manda.

COMO CUENTA
-----------
Saca los `.clase` y los `#id` de los selectores del CSS y los busca en
`web/app.js` y `web/index.html` DENTRO de las cadenas -- que es donde viven, o
sea justo al contrario que en las otras herramientas de aqui: `h('div', {clase:
'ficha-estilo'})` es una cadena, no codigo.

Se busca el nombre suelto, no `.clase`, porque en el JS se escribe sin punto y a
veces pegado a otro (`'fila cierre'`, `'mini fantasma'`).

    python herramientas/css_sin_usar.py

LO QUE NO SABE, y por eso lo que dice se mira antes de borrar:

  * un nombre COMPUESTO en el codigo (`clase: 'ficha-' + tipo`) no aparece
    entero en ningun sitio, asi que su regla saldra como no usada;
  * las clases que pone el navegador (`:hover`, `::before`) no son clases y no
    se cuentan;
  * las de estado que solo se ponen con `classList.add` si aparecen, porque eso
    tambien es una cadena.

Peca de decir que sobra algo que se usa, nunca al contrario: es la direccion
segura para una herramienta que sugiere borrar.
"""
import io
import os
import re
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(RAIZ, "web", "estilo.css")
FUENTES = (os.path.join(RAIZ, "web", "app.js"),
           os.path.join(RAIZ, "web", "index.html"))

#: Las que pone el propio CSS o el navegador, no el codigo.
DEL_NAVEGADOR = frozenset((
    "oculto", "hover", "focus", "active", "disabled", "checked", "visible",
))

#: `#fff` y `#d8a657` NO son ids: son colores, y hay decenas en la paleta. Se
#: reconocen por la forma --3, 4, 6 u 8 digitos hexadecimales y nada mas-- y no
#: por donde salen, porque un color puede aparecer en cualquier propiedad.
COLOR = re.compile(r"^(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def nombres_del_css(texto):
    """{nombre: [lineas]} de cada clase e id que aparece en un selector."""
    # fuera los comentarios: dentro se citan clases que ya no existen
    limpio = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)),
                    texto, flags=re.S)
    donde = {}
    for m in re.finditer(r"([.#])([A-Za-z_0-9][\w-]*)", limpio):
        if m.group(1) == "#" and COLOR.match(m.group(2)):
            continue
        if m.group(2)[0].isdigit():          # `.5rem`, no una clase
            continue
        linea = limpio[:m.start()].count("\n") + 1
        donde.setdefault(m.group(2), []).append(linea)
    return donde


def main():
    css = io.open(CSS, encoding="utf-8").read()
    usados = ""
    for ruta in FUENTES:
        if os.path.exists(ruta):
            usados += io.open(ruta, encoding="utf-8").read()

    donde = nombres_del_css(css)
    sobran = []
    for nombre, lineas in sorted(donde.items()):
        if nombre in DEL_NAVEGADOR:
            continue
        if re.search(r"[\"'\s>]" + re.escape(nombre) + r"[\"'\s<]", usados):
            continue
        if re.search(r"\b" + re.escape(nombre) + r"\b", usados):
            continue
        sobran.append((nombre, lineas))

    print(f"{len(donde)} nombres en el CSS · {len(sobran)} sin usar")
    for nombre, lineas in sobran:
        cuantas = ", ".join(str(x) for x in lineas[:6])
        mas = "…" if len(lineas) > 6 else ""
        print(f"  {nombre:34} estilo.css:{cuantas}{mas}")

    if "--borrar" in sys.argv:
        muertos = {n for n, _l in sobran}
        nuevo, cuantas = _podar(css, muertos)
        io.open(CSS, "w", encoding="utf-8", newline="").write(nuevo)
        print(f"\nBORRADAS {cuantas} reglas "
              f"({css.count(chr(10)) - nuevo.count(chr(10))} lineas). "
              f"MIRA LA PANTALLA: una regla de menos no da ningun error, se ve.")
    return 0


def _podar(css, muertos):
    """El CSS sin las reglas cuyos selectores son TODOS de nombres muertos.

    UNA REGLA SE VA SOLO SI SOBRA ENTERA. `.ficha-estilo, .tarjeta-muerta {...}`
    se queda: la mitad viva necesita el bloque. Y una regla sin ninguna clase ni
    id --`body`, `a:hover`, `*`-- no se toca nunca: no la puede reclamar nadie
    y quitarla cambia como se ve todo.

    Los `@media` se recorren por dentro y se van si se quedan vacios.
    """
    def limpiar(bloque):
        fuera, i, quitadas = [], 0, 0
        while i < len(bloque):
            abre = bloque.find("{", i)
            if abre < 0:
                fuera.append(bloque[i:])
                break
            selector = bloque[i:abre]
            nivel, j = 0, abre
            while j < len(bloque):
                if bloque[j] == "{":
                    nivel += 1
                elif bloque[j] == "}":
                    nivel -= 1
                    if nivel == 0:
                        break
                j += 1
            cuerpo = bloque[abre + 1:j]
            entero = bloque[i:j + 1]
            corto = selector.strip()
            if corto.startswith("@media") or corto.startswith("@supports"):
                dentro, n = limpiar(cuerpo)
                quitadas += n
                if dentro.strip():
                    fuera.append(selector + "{" + dentro + "}")
                else:
                    quitadas += 1
                i = j + 1
                continue
            if corto.startswith("@"):            # keyframes, font-face, import
                fuera.append(entero)
                i = j + 1
                continue
            # los comentarios que van pegados delante viajan con la regla
            partes = [p.strip() for p in re.split(r",", _sin_comentarios(selector))
                      if p.strip()]
            nombres = set()
            for parte in partes:
                nombres |= {m.group(2) for m in
                            re.finditer(r"([.#])([A-Za-z_][\w-]*)", parte)}
            if partes and nombres and nombres <= muertos:
                quitadas += 1
                i = j + 1
                continue
            fuera.append(entero)
            i = j + 1
        return "".join(fuera), quitadas

    return limpiar(css)


def _sin_comentarios(trozo):
    return re.sub(r"/\*.*?\*/", " ", trozo, flags=re.S)


if __name__ == "__main__":
    sys.exit(main())
