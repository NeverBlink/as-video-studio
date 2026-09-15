"""Manifiesto por version: que el historico NO viva dentro de estado.json.

Cada version de un paso por unidades guarda que produjo CADA unidad. Con 240
planos eso son ~4 MB por version, y estado.json llego a 320 MB (crece como
versiones x unidades y nadie lo poda). El manifiesto vive ahora en
`pasos/<paso>/_versiones/v<N>.json` y en la entrada solo queda el recuento.

Lo que se comprueba aqui, y por que:

  [1][2] una version nueva escribe el manifiesto FUERA y estado.json no engorda.
  [3][4] se recupera, y `revertir` restaura con el el mapa vivo de unidades.
  [5]    COMPATIBILIDAD: las versiones de antes lo llevan dentro de la entrada y
         se siguen leyendo igual. No hay migracion obligatoria.
  [6]    un manifiesto que falta LANZA. Es la comprobacion importante: `revertir`
         mete lo que reciba en el mapa vivo, asi que devolver {} ante un fichero
         ausente dejaria las 240 unidades como «sin hacer» y la pantalla
         ofreceria regenerar el video entero -- sin que nada fallara a la vista.
  [7]    `duplicar` se lleva el manifiesto de la version activa. Se salta la
         clase Estado (lee estado.json crudo), asi que hay que copiarlo a mano o
         la copia nace con una version que apunta a un fichero que no existe.
"""
import os, sys, json, shutil, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo.proyecto import Proyecto, CARPETA_MANIFIESTOS, escribir_json
from nucleo.estado import Estado

fallos = []
def ok(cond, texto):
    print(("  ok   " if cond else "  FALLA ") + texto)
    if not cond: fallos.append(texto)

base = tempfile.mkdtemp(prefix="manifiestos_")
p = Proyecto.crear(base, "prueba")
e = Estado(p)

print("\n[1] una version nueva escribe su manifiesto FUERA de estado.json")
e.set_params("guion", {"unidades": {"S01": {"texto": "a"}, "S02": {"texto": "b"}}})
e.completar("guion", {"doc": "guion.json"}, {"S01": {"png": "1.png"}, "S02": {"png": "2.png"}})
entrada = e.versiones("guion")[0]
ok("unidades" not in entrada, "la entrada de la version NO lleva el manifiesto dentro")
ok(entrada.get("n_unidades") == 2, f"lleva el recuento: n_unidades={entrada.get('n_unidades')}")
ruta_m = os.path.join(p.raiz, "pasos", "guion", CARPETA_MANIFIESTOS, "v1.json")
ok(os.path.isfile(ruta_m), f"el manifiesto esta en su fichero: {CARPETA_MANIFIESTOS}/v1.json")
ok(sorted(json.load(open(ruta_m, encoding="utf-8"))) == ["S01", "S02"], "y trae las dos unidades")

print("\n[2] estado.json ya no engorda con el manifiesto")
doc = json.load(open(p.ruta("estado.json"), encoding="utf-8"))
ok("unidades" not in doc["pasos"]["guion"]["versiones"][0], "tampoco en el fichero de disco")

print("\n[3] manifiesto_version lo recupera, por entrada y por numero")
ok(sorted(e.manifiesto_version("guion", entrada)) == ["S01", "S02"], "por la entrada")
ok(sorted(e.manifiesto_version("guion", 1)) == ["S01", "S02"], "por el numero de version")

print("\n[4] revertir restaura el mapa vivo desde el manifiesto")
e.set_params("guion", {"unidades": {"S01": {"texto": "CAMBIADO"}, "S02": {"texto": "b"}}})
e.completar("guion", {"doc": "guion.json"}, {"S01": {"png": "1b.png"}, "S02": {"png": "2.png"}})
ok(e.salidas_unidad("guion", "S01").get("png") == "1b.png", "v2 activa: S01 -> 1b.png")
e.revertir("guion", 1)
ok(e.salidas_unidad("guion", "S01").get("png") == "1.png",
   "tras revertir a v1: S01 -> 1.png (el manifiesto se ha leido del fichero)")
ok(len(e.unidades_declaradas("guion")) == 2, "y las dos unidades siguen declaradas")

print("\n[5] COMPATIBILIDAD: una version en formato VIEJO (manifiesto dentro) se lee igual")
doc = json.load(open(p.ruta("estado.json"), encoding="utf-8"))
v1 = doc["pasos"]["guion"]["versiones"][0]
v1.pop("n_unidades", None)
v1["unidades"] = {"S01": {"firma": "x", "salidas": {"png": "VIEJO.png"}}}
escribir_json(p.ruta("estado.json"), doc)
os.remove(os.path.join(p.raiz, "pasos", "guion", CARPETA_MANIFIESTOS, "v1.json"))
e2 = Estado(p)
ok(e2.manifiesto_version("guion", 1)["S01"]["salidas"]["png"] == "VIEJO.png",
   "el manifiesto embebido se devuelve tal cual, sin buscar fichero")
ok(e2.versiones_resumen("guion")[0]["n_unidades"] == 1,
   "y versiones_resumen lo cuenta del manifiesto embebido")

print("\n[6] LO IMPORTANTE: un manifiesto que falta LANZA, no devuelve vacio")
doc = json.load(open(p.ruta("estado.json"), encoding="utf-8"))
v1 = doc["pasos"]["guion"]["versiones"][0]
v1.pop("unidades", None)
v1["n_unidades"] = 240                      # dice tener 240 y no hay fichero
escribir_json(p.ruta("estado.json"), doc)
e3 = Estado(p)
try:
    e3.manifiesto_version("guion", 1)
    ok(False, "tendria que haber lanzado y no lanzo")
except ValueError as fallo:
    ok("no aparece" in str(fallo), "lanza ValueError con un mensaje que explica el caso")
try:
    e3.revertir("guion", 1)
    ok(False, "revertir tendria que haber lanzado")
except ValueError:
    ok(True, "revertir lanza en vez de vaciar el mapa de unidades")

print("\n[7] duplicar se lleva el manifiesto de la activa, con las rutas mudadas")
base2 = tempfile.mkdtemp(prefix="manifiestos_dup_")
p2 = Proyecto.crear(base2, "origen")
e4 = Estado(p2)
e4.set_params("guion", {"unidades": {"S01": {"texto": "a"}}})
# Una ruta ABSOLUTA dentro de la salida, como las 111 que lleva el manifiesto de
# assets en un video real. Cuando el manifiesto vivia dentro de estado.json se
# las mudaba `_mudar_rutas`; al sacarlo fuera hay que seguir haciendolo, o la
# copia apunta a los ficheros del proyecto ORIGINAL.
absoluta = os.path.join(p2.raiz, "pasos", "guion", "v1", "narracion.wav")
e4.completar("guion", {"doc": "g.json"}, {"S01": {"png": "1.png", "wav": absoluta}})
copia = p2.duplicar(base2, "copia")
ruta_copia = os.path.join(copia.raiz, "pasos", "guion", CARPETA_MANIFIESTOS, "v1.json")
ok(os.path.isfile(ruta_copia), "la copia tiene el manifiesto de su version activa")
man_copia = Estado(copia).manifiesto_version("guion", 1)
ok(man_copia["S01"]["salidas"]["png"] == "1.png",
   "y la copia puede revertir sin quedarse sin unidades")
wav = man_copia["S01"]["salidas"]["wav"]
ok(wav.lower().startswith(copia.raiz.lower()),
   "la ruta absoluta del manifiesto apunta a la COPIA")
ok(not wav.lower().startswith(p2.raiz.lower()),
   "y ya no apunta al proyecto de origen")

print("\n[8] un manifiesto CORTO tambien lanza: el tipo no basta, tiene que cuadrar")
base3 = tempfile.mkdtemp(prefix="manifiestos_corto_")
p3 = Proyecto.crear(base3, "corto")
e5 = Estado(p3)
e5.set_params("guion", {"unidades": {"S01": {"t": 1}, "S02": {"t": 2}, "S03": {"t": 3}}})
e5.completar("guion", {"doc": "g.json"},
             {"S01": {"png": "1.png"}, "S02": {"png": "2.png"}, "S03": {"png": "3.png"}})
ruta_m3 = os.path.join(p3.raiz, "pasos", "guion", CARPETA_MANIFIESTOS, "v1.json")
man = json.load(open(ruta_m3, encoding="utf-8"))
man.pop("S03")                                  # una escritura a medias, una copia mala
escribir_json(ruta_m3, man)
e6 = Estado(p3)
try:
    e6.manifiesto_version("guion", 1)
    ok(False, "un manifiesto de 2 donde la version dice 3 tendria que lanzar")
except ValueError as fallo:
    ok("incompleto" in str(fallo), "lanza y dice que esta incompleto: " + str(fallo)[:60])

print("\n[9] si falla la escritura del manifiesto, el estado vivo NO se toca")
base4 = tempfile.mkdtemp(prefix="manifiestos_fallo_")
p4 = Proyecto.crear(base4, "fallo")
e7 = Estado(p4)
e7.set_params("guion", {"unidades": {"S01": {"t": 1}}})
e7.completar("guion", {"doc": "g1.json"}, {"S01": {"png": "1.png"}})
import nucleo.estado as _mod
bueno = _mod.escribir_json
def romper(ruta, datos):
    if CARPETA_MANIFIESTOS in str(ruta):
        raise OSError(28, "no queda sitio en el dispositivo")
    return bueno(ruta, datos)
_mod.escribir_json = romper
try:
    e7.set_params("guion", {"unidades": {"S01": {"t": 2}}})
    try:
        e7.completar("guion", {"doc": "g2.json"}, {"S01": {"png": "2.png"}})
        ok(False, "completar tendria que haber lanzado")
    except OSError:
        ok(True, "completar lanza cuando no puede escribir el manifiesto")
    # y ahora lo importante: que el documento vivo siga siendo el de v1
    e7.marcar_error("guion", "la tanda reviento")   # lo que hace el gestor de trabajos
finally:
    _mod.escribir_json = bueno
disco = json.load(open(p4.ruta("estado.json"), encoding="utf-8"))["pasos"]["guion"]
ok(disco["activa"] == 1, f"la version activa sigue siendo la 1 (es {disco['activa']})")
ok([v["n"] for v in disco["versiones"]] == [1], "y el historico sigue con una sola version")
ok(disco["salidas"].get("doc") == "g1.json",
   "las salidas siguen siendo las de v1, no las de la tanda que fallo")
ok(any(v["n"] == disco["activa"] for v in disco["versiones"]),
   "activa apunta a una version que EXISTE (sin esto, revertir da 404 y la "
   "pantalla ensena las imagenes viejas como recien hechas)")

for d in (base, base2, base3, base4):
    shutil.rmtree(d, ignore_errors=True)
print("\n" + ("MANIFIESTOS OK: todas las comprobaciones pasan" if not fallos
              else f"FALLAN {len(fallos)}: " + "; ".join(fallos)))
sys.exit(1 if fallos else 0)
