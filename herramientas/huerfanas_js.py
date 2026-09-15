"""Llamadas a funciones que ya no existen en web/app.js, sin comentarios ni cadenas."""
import io
import os, re

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
crudo = io.open(os.path.join(RAIZ, "web", "app.js"), encoding="utf-8").read()

# quita comentarios y literales de cadena, conservando los saltos de linea
fuera, i, n = [], 0, len(crudo)
while i < n:
    c = crudo[i]
    if c == "/" and i + 1 < n and crudo[i+1] == "/":
        j = crudo.find("\n", i);  j = n if j < 0 else j
        fuera.append(" " * (j - i)); i = j
    elif c == "/" and i + 1 < n and crudo[i+1] == "*":
        j = crudo.find("*/", i + 2); j = n if j < 0 else j + 2
        fuera.append(re.sub(r"[^\n]", " ", crudo[i:j])); i = j
    elif c in "'\"`":
        j, cierre = i + 1, c
        while j < n:
            if crudo[j] == "\\": j += 2; continue
            if crudo[j] == cierre: j += 1; break
            j += 1
        trozo = crudo[i:j]
        # dentro de `...` puede haber ${expresiones} que SI son codigo
        if cierre == "`":
            trozo = re.sub(r"[^\n$\{\}]", " ", trozo)
        else:
            trozo = re.sub(r"[^\n]", " ", trozo)
        fuera.append(trozo); i = j
    else:
        fuera.append(c); i += 1
s = "".join(fuera)

definidos = set()
for m in re.finditer(r"\b(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)", s):
    definidos.add(m.group(1))
for m in re.finditer(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)", s):
    definidos.add(m.group(1))
for m in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*(?:=>|=\s*(?:async\s*)?(?:function|\())", s):
    definidos.add(m.group(1))
for m in re.finditer(r"(?:\(|,)\s*([A-Za-z_$][\w$]*)\s*(?:,|\)|=)", s):
    definidos.add(m.group(1))            # parametros
for m in re.finditer(r"\bfor\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)", s):
    definidos.add(m.group(1))
for m in re.finditer(r"\{([^{}\n]*)\}\s*=", s):
    for x in re.findall(r"[A-Za-z_$][\w$]*", m.group(1)):
        definidos.add(x)

GLOBALES = set("""if for while switch catch return typeof function await new do else try
throw case in of delete void instanceof yield console document window JSON Object Array
String Number Boolean Math Date Promise Set Map WeakMap RegExp Error fetch setTimeout
clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame parseInt
parseFloat isNaN encodeURIComponent decodeURIComponent URL URLSearchParams Blob FormData
AbortController Intl localStorage sessionStorage navigator location alert confirm prompt
EventSource FileReader Audio Image MutationObserver IntersectionObserver ResizeObserver
CustomEvent Event WebSocket performance queueMicrotask Uint8Array Float32Array ArrayBuffer
TextDecoder TextEncoder Symbol Infinity NaN undefined globalThis getComputedStyle DOMParser
XMLSerializer XMLHttpRequest MediaRecorder speechSynthesis SpeechSynthesisUtterance
matchMedia btoa atob structuredClone AudioContext Notification ClipboardItem""".split())

llamadas = {}
for m in re.finditer(r"(?<![\w$.])([a-zA-Z_$][\w$]*)\s*\(", s):
    nombre = m.group(1)
    if nombre in GLOBALES or nombre in definidos:
        continue
    llamadas.setdefault(nombre, []).append(s[:m.start()].count("\n") + 1)

if not llamadas:
    print("OK: ninguna llamada a algo que no exista")
else:
    print(f"SOSPECHOSAS: {len(llamadas)}")
    for nombre, lineas in sorted(llamadas.items()):
        print(f"  {nombre}()  -> lineas {lineas[:6]}")
