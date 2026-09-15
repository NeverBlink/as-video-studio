"""Identificadores USADOS y nunca declarados en web/app.js.

`node --check` valida SINTAXIS, no referencias: borrar una constante o una
funcion y dejar sus usos pasa el check y revienta en el navegador, y **solo
cuando alguien pinta esa pantalla**. Esto lo caza en seco.

POR QUE SE AFINO (24-08-2026)
-----------------------------
Existia y no sirvio. El 24-08 se borro de rebote el bloque de constantes de la
voz --`VELOCIDADES`, `EMOCIONES`, `MODELOS_VOZ`, `NIVELES` y los dos ayudantes
de emociones-- al retirar el eje de idiomas, y el modo light empezo a morir con
`VELOCIDADES is not defined`. El comprobador **lo estaba diciendo**, enterrado
entre 69 nombres de los que 60 eran mentira: `const` 2.014 veces, `let` 77,
`https`, `Za`, `gi`, `min`... Un informe que grita sesenta veces no lo lee
nadie, y entonces da igual que la que importaba estuviera dentro.

Dos causas, las dos arregladas aqui:

  1. **Faltaban palabras clave en la lista de globales.** `const`, `let`, `var`
     y `finally` se contaban como identificadores sin declarar. Solo eso eran
     2.100 avisos.
  2. **No se quitaban las expresiones regulares.** Los trozos de un
     `/^https?:\\/\\/[A-Za-z]/` entraban como nombres: de ahi `https`, `Za`,
     `gi`, `bde`, `spell`. Ahora se blanquean como las cadenas, distinguiendo
     una regex de una division por lo que va DELANTE de la barra, que es la
     regla de siempre en JavaScript.

Queda una lista corta de falsos positivos conocidos (`CONOCIDOS`) que son
declaraciones que este reconocedor por expresiones regulares no sabe ver. Van
escritas con su motivo: una lista de excepciones sin motivo se convierte en el
sitio donde se esconde el fallo de verdad.

Lo usa `prueba_api.py`, asi que un nombre nuevo sin declarar pone una suite en
rojo en vez de esperar a que alguien abra esa pantalla.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\herramientas\\indefinidos_js.py
"""
import io
import os
import re

RUTA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "web", "app.js")

#: Delante de una barra, esto quiere decir que empieza una EXPRESION REGULAR y
#: no una division. Es la regla de JavaScript de siempre: detras de un VALOR la
#: barra divide; detras de un operador, de una apertura o de una palabra clave,
#: abre un literal.
ANTES_DE_REGEX = re.compile(
    r"[=(,:;!&|?{}\[\]+\-*%~^<>]\s*$"
    r"|\b(?:return|typeof|case|in|of|new|delete|void|instanceof|do|else|yield|await)\s*$")

#: Declaraciones que este reconocedor no sabe ver, con el porque de cada una.
#: NO se anaden a la ligera: cada linea de aqui es un sitio donde podria
#: esconderse un fallo de verdad.
#: Falsos positivos conocidos: declaraciones que este reconocedor no sabe ver.
#: **Esta vacia, y esa es la idea.** Empezo con 26 entradas y se podaron todas
#: reconociendo de verdad lo que las provocaba (las regex, las plantillas
#: anidadas, los multideclaradores y los parametros de una arrow con nombre).
#: Una excepcion sin motivo se convierte en el sitio donde se esconde el fallo
#: de verdad; si algun dia hace falta anadir una, va con su porque escrito.
CONOCIDOS = {}

PALABRAS = set("""if for while switch catch return typeof function await new do else try
throw case in of delete void instanceof yield this true false null break continue default
export import class extends super static get set async const let var finally
console document window JSON Object
Array String Number Boolean Math Date Promise Set Map WeakMap WeakSet RegExp Error TypeError
fetch setTimeout clearTimeout setInterval clearInterval requestAnimationFrame Reflect Proxy
cancelAnimationFrame parseInt parseFloat isNaN isFinite encodeURIComponent decodeURIComponent
encodeURI decodeURI URL URLSearchParams Blob File FormData Headers Request Response
AbortController Intl localStorage sessionStorage navigator location alert confirm prompt
EventSource FileReader Audio Image MutationObserver IntersectionObserver ResizeObserver
CustomEvent Event KeyboardEvent MouseEvent WebSocket performance queueMicrotask
Uint8Array Uint8ClampedArray Int32Array Float32Array Float64Array ArrayBuffer DataView
TextDecoder TextEncoder Symbol Infinity NaN undefined globalThis getComputedStyle
DOMParser XMLSerializer XMLHttpRequest MediaRecorder speechSynthesis Element Node
SpeechSynthesisUtterance matchMedia btoa atob structuredClone AudioContext Notification
ClipboardItem HTMLElement SVGElement CSS crypto history screen frames self top parent
webkitSpeechRecognition SpeechRecognition OffscreenCanvas createImageBitmap ImageData""".split())


def sin_comentarios_ni_cadenas(crudo):
    """El fichero con los comentarios, las cadenas y las regex en blanco.

    Se blanquean y no se borran para que los numeros de linea no se muevan: un
    aviso que apunta a la linea equivocada es peor que ninguno.

    LAS PLANTILLAS SE RECORREN CON UNA PILA, y hace falta: en este fichero hay
    plantillas DENTRO de plantillas --`${a ? `x ${b}` : ''}`-- y un recorrido
    plano se cree que la primera comilla de dentro cierra la de fuera. A partir
    de ahi lee texto como si fuera codigo, y de ahi salian avisos por palabras
    como «quedan», «negros» o «procesos». Dentro de un `${...}` SI hay codigo,
    asi que se conserva; el texto de alrededor se blanquea.
    """
    salida = []
    # cada nivel es ("plantilla",) --texto de una plantilla-- o ("hueco", llaves)
    # --dentro de un ${...}, con cuantas llaves lleva abiertas--
    pila = []
    i, n = 0, len(crudo)

    def en_plantilla():
        return bool(pila) and pila[-1][0] == "plantilla"

    while i < n:
        c = crudo[i]

        if en_plantilla():
            if c == "\\":
                salida.append("  ")
                i += 2
                continue
            if c == "`":
                salida.append(" ")
                pila.pop()
                i += 1
                continue
            if c == "$" and i + 1 < n and crudo[i + 1] == "{":
                salida.append("  ")
                pila.append(["hueco", 0])
                i += 2
                continue
            salida.append("\n" if c == "\n" else " ")
            i += 1
            continue

        # -- contexto de codigo (el de fuera, o el de dentro de un ${...})
        if c == "/" and i + 1 < n and crudo[i + 1] == "/":
            j = crudo.find("\n", i)
            j = n if j < 0 else j
            salida.append(" " * (j - i))
            i = j
        elif c == "/" and i + 1 < n and crudo[i + 1] == "*":
            j = crudo.find("*/", i + 2)
            j = n if j < 0 else j + 2
            salida.append(re.sub(r"[^\n]", " ", crudo[i:j]))
            i = j
        elif c == "/" and ANTES_DE_REGEX.search("".join(salida[-120:])[-80:]):
            j, dentro_clase = i + 1, False
            while j < n:
                ch = crudo[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "\n":
                    break                  # una regex no cruza lineas: no lo era
                if ch == "[":
                    dentro_clase = True
                elif ch == "]":
                    dentro_clase = False
                elif ch == "/" and not dentro_clase:
                    j += 1
                    while j < n and crudo[j] in "gimsuyvd":
                        j += 1
                    break
                j += 1
            salida.append(re.sub(r"[^\n]", " ", crudo[i:j]))
            i = j
        elif c in "'\"":
            j, cierre = i + 1, c
            while j < n:
                if crudo[j] == "\\":
                    j += 2
                    continue
                if crudo[j] == cierre:
                    j += 1
                    break
                if crudo[j] == "\n":
                    break                  # cadena sin cerrar: no la habia
                j += 1
            salida.append(re.sub(r"[^\n]", " ", crudo[i:j]))
            i = j
        elif c == "`":
            salida.append(" ")
            pila.append(("plantilla",))
            i += 1
        elif c == "{" and pila and pila[-1][0] == "hueco":
            pila[-1][1] += 1
            salida.append(c)
            i += 1
        elif c == "}" and pila and pila[-1][0] == "hueco":
            if pila[-1][1] == 0:
                pila.pop()                 # se cierra el ${...}
                salida.append(" ")
            else:
                pila[-1][1] -= 1
                salida.append(c)
            i += 1
        else:
            salida.append(c)
            i += 1
    return "".join(salida)


def _multideclaradores(s):
    """Los nombres de un `let a = 0, b = null;` -> set

    Una sola declaracion puede nombrar varias cosas, y con inicializador por
    medio: `let tiempo = 0, jugando = false, ultimoReloj = 0, escenaActual =
    null;`. Un patron de expresion regular no lo sabe recorrer --el valor de en
    medio puede llevar comas, parentesis y hasta una funcion-- asi que se
    recorre a mano contando la profundidad, y se recoge el identificador que va
    justo detras de la palabra clave y el que va detras de cada coma AL NIVEL
    DE FUERA.

    Estos ocho salian como «sin declarar» y estuvieron en la lista de
    excepciones un rato. Reconocerlos es mejor que excusarlos: una lista de
    excepciones es un sitio donde esconderse.
    """
    nombres = set()
    for m in re.finditer(r"\b(?:const|let|var)\s+", s):
        i, n = m.end(), len(s)
        profundidad, esperando = 0, True
        while i < n:
            c = s[i]
            if c in "([{":
                profundidad += 1
            elif c in ")]}":
                if profundidad == 0:
                    break
                profundidad -= 1
            elif profundidad == 0 and c == ";":
                break
            elif profundidad == 0 and c == "\n":
                # sigue en la linea de abajo solo si venia una coma pendiente
                anterior = s[m.end():i].rstrip()
                if not anterior.endswith(","):
                    break
            elif profundidad == 0 and c == ",":
                esperando = True
            elif esperando and (c.isalpha() or c in "_$"):
                j = i
                while j < n and (s[j].isalnum() or s[j] in "_$"):
                    j += 1
                nombres.add(s[i:j])
                esperando = False
                i = j
                continue
            i += 1
    return nombres


def declarados(s):
    """Todo lo que el fichero declara, de todas las formas que usa."""
    encontrados = set()

    def declara(patron, grupo=1, banderas=0):
        for m in re.finditer(patron, s, banderas):
            for x in re.findall(r"[A-Za-z_$][\w$]*", m.group(grupo)):
                encontrados.add(x)

    declara(r"\b(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)")
    declara(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)")
    declara(r"\b(?:const|let|var)\s*(\{[^{}]*\}|\[[^\[\]]*\])")
    encontrados |= _multideclaradores(s)
    declara(r"\bcatch\s*\(\s*([A-Za-z_$][\w$]*)")
    declara(r"\bfor\s*\(\s*(?:const|let|var)\s+(\{[^{}]*\}|\[[^\]]*\]|[A-Za-z_$][\w$]*)")
    declara(r"\bclass\s+([A-Za-z_$][\w$]*)")
    # parametros de funcion y de arrow
    for m in re.finditer(
            r"(?:function\s*\*?\s*[A-Za-z_$\w]*\s*|=>\s*|\b)\(([^()]{0,400}?)\)\s*(?:=>|\{)", s):
        for x in re.findall(r"[A-Za-z_$][\w$]*", m.group(1)):
            encontrados.add(x)
    for m in re.finditer(r"(?<![\w$.)])([A-Za-z_$][\w$]*)\s*=>", s):
        encontrados.add(m.group(1))
    # `clave: (a, b) => …`: el bucle de arriba pide una palabra pegada al
    # parentesis y aqui delante hay dos puntos y un espacio, asi que no casaba y
    # los parametros que no se usan se contaban como nombres sin declarar
    for m in re.finditer(r"\(([^()]{0,400}?)\)\s*=>", s):
        for x in re.findall(r"[A-Za-z_$][\w$]*", m.group(1)):
            encontrados.add(x)
    # metodos y propiedades de objeto: `nombre(...)` al principio de linea
    declara(r"^\s*([A-Za-z_$][\w$]*)\s*\(", 1, re.M)
    return encontrados


def revisar(ruta=RUTA):
    """-> {nombre: [lineas]} de lo que se usa y no se declara."""
    s = sin_comentarios_ni_cadenas(io.open(ruta, encoding="utf-8").read())
    dichos = declarados(s)
    usos = {}
    for m in re.finditer(r"(?<![\w$.])([A-Za-z_$][\w$]*)", s):
        nombre = m.group(1)
        if nombre in PALABRAS or nombre in dichos or nombre in CONOCIDOS:
            continue
        if s[m.end():m.end() + 1] == ":":        # clave de un objeto
            continue
        usos.setdefault(nombre, []).append(s[:m.start()].count("\n") + 1)
    return usos


def main():
    usos = revisar()
    if not usos:
        print("OK: ningun identificador sin declarar"
              + (f" ({len(CONOCIDOS)} falsos positivos conocidos)" if CONOCIDOS
                 else ", y sin ninguna excepcion escrita a mano"))
        return 0
    print(f"SIN DECLARAR: {len(usos)}")
    for nombre, lineas in sorted(usos.items(), key=lambda x: -len(x[1])):
        print(f"  {nombre}  -> {len(lineas)} uso(s), lineas {lineas[:5]}")
    return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
