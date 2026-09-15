r"""Trae un proyecto o unos estilos de la version ANTERIOR del software.

Para que
--------
Esta version quito features enteras: el material dejo de ser un video de YouTube
y paso a ser texto, se fueron el documentalista, los personajes fijos del canal
y las menciones ilustradas. Un proyecto de antes lleva en sus params las claves
de todo eso.

Y esas claves NO se pueden dejar ahi. `_normalizar` de cada paso se queda solo
con las que conoce, asi que **la firma que calcula este software no es la que
esta guardada**: el proyecto abre con los ocho pasos en obsoleto y la pantalla
ofrece regenerar 302 planos ya pagados.

Copiar la carpeta tampoco basta por lo de siempre: dentro hay rutas absolutas, y
entran en las firmas. Eso lo arregla `mudar_proyecto.py`.

Asi que son tres cosas, en este orden:

    1. NORMALIZAR   traducir los params y las salidas al contrato de hoy  (aqui)
    2. MUDAR        las rutas de la maquina de origen a esta   (mudar_proyecto)
    3. RE-SELLAR    las firmas al valor que calcula este software
                    (`mudar_proyecto --sellar-todo`)

Que se traduce, y a que
-----------------------
**El material.** `ingesta.params` era `{"url": "<YouTube>"}` y aqui es
`{"texto": ...}`. El transcript de aquel video esta dentro del proyecto, asi que
se convierte en el TEXTO del material: los tramos con tiempos se pegan en
parrafos cortando por los silencios largos. No se inventa nada -- es el mismo
material con el que se escribio el guion.

Y la version se vuelve a producir **llamando al paso de hoy** (`p1_ingesta`), no
imitando su salida a mano: asi la version queda reproducible desde sus params,
que es el contrato de todo el grafo. Con ella se van el mp4, los subtitulos y
los fotogramas: en esta version no existe un video de origen.

**El guion.** Se caen `fuentes`, `buscar_en_internet`, `material_huella`,
`integraciones_*` y `personajes`. `cta` se queda, sin el campo `producto`.

**Los planos.** Se cae `assets.params.personajes` -- los personajes FIJOS del
canal. El **reparto** del video no se toca, y ahi es donde vive la gente que
sale: en el video del oro, el personaje del canal estaba tambien en el reparto,
asi que su hoja y sus 199 planos siguen exactamente igual.

**Los estilos.** `origen.estilo_url` (el video del que se saco el estilo) se cae
y en su sitio van como `estilo_imagenes` las referencias que ese estilo ya
produjo: son imagenes, que es lo que esta version pide. Se caen los personajes
del canal y la `cta` del preset -- aqui las llamadas a la accion se deciden
video por video.

Uso
---
    python herramientas/traer_de_v1.py proyecto <carpeta>       [--aplicar]
    python herramientas/traer_de_v1.py presets  <presets.json> [--aplicar]
    python herramientas/traer_de_v1.py recetas  <recetas.json> [--aplicar]

Sobre la COPIA que se quiere quedar, nunca sobre el original: esto reescribe
params y borra ficheros. Y con los servicios parados, por lo mismo que avisa
`mudar_proyecto.py`.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for ruta in (RAIZ, os.path.join(RAIZ, "pasos")):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

from nucleo.estado import Estado, PASOS_POR_ID                # noqa: E402
from nucleo.proyecto import Proyecto                          # noqa: E402

import p1_ingesta                                             # noqa: E402
import recetas                                                # noqa: E402

#: Silencio a partir del cual el material cambia de parrafo, en segundos. Un
#: transcript viene en tramos de dos o tres segundos, y pegarlos todos daria un
#: bloque de seis mil palabras: ilegible al abrirlo y un solo trozo para el
#: guionista. Un segundo y medio es donde quien hablaba tomo aire.
SILENCIO_PARRAFO_S = 1.5

#: Y CUANDO NO HAY SILENCIOS, cada cuantas palabras se corta.
#:
#: Un transcript automatico de YouTube no trae silencios: sus tramos son una
#: ventana que avanza, no frases, y los huecos entre uno y el siguiente son de
#: una centesima TODOS (medido sobre 872 huecos de un video de catorce minutos:
#: el percentil 100 es 0,01 s). Tampoco trae puntuacion, asi que no hay ninguna
#: marca en el texto por la que cortar.
#:
#: Asi que los parrafos se hacen por CUENTA DE PALABRAS, y noventa es lo que
#: dura un parrafo hablado. Es una decision de presentacion sobre un texto que
#: no tiene estructura propia -- y hace falta: un solo trozo de seis mil
#: palabras es una caja de texto imposible de revisar.
PALABRAS_PARRAFO = 90

#: Params que este software ya no tiene y que hay que quitar a mano. No se
#: quitan «por si acaso»: cada uno era una feature entera, y dejarlos descuadra
#: la firma sin que nada avise.
FUERA_DE_PARAMS = {
    "ingesta": ("url", "video_local", "recortar", "idiomas_subtitulo",
                "frames_cada_s", "max_frames"),
    "guion": ("fuentes", "buscar_en_internet", "material_huella",
              "integraciones_cortas", "integraciones_duracion_s",
              "integraciones_outro", "integraciones_prompt",
              "integraciones_modo", "integraciones_max", "integraciones_insistir",
              "integraciones_modelo", "integraciones_esfuerzo",
              "personajes"),
    "assets": ("personajes",),
}

#: Y lo que se cae de las SALIDAS, que tambien entran en la firma del paso de
#: abajo (`_sello_salida`).
FUERA_DE_SALIDAS = {
    "guion": ("integraciones",),
}

#: Ficheros de una version de ingesta que en esta version no existen: el video
#: de origen, sus subtitulos y los fotogramas que se le sacaron.
FUERA_DE_LA_INGESTA = (".mp4", ".webm", ".mkv", ".vtt", ".srt", ".info.json")
CARPETAS_FUERA_INGESTA = ("frames_utiles", "frames_relleno")


# ------------------------------------------------------------------ el material

def texto_del_transcript(tramos):
    """El transcript con tiempos, convertido en texto con parrafos. -> str

    POR LOS SILENCIOS SI LOS HAY, y por cuenta de palabras si no. Un silencio
    largo es la unica marca del transcript que significa algo para un lector, y
    cuando existe manda; un transcript automatico no trae ninguna (ver
    `PALABRAS_PARRAFO`) y entonces se corta por largo.

    Ni una linea por tramo --ochocientas de tres palabras-- ni un solo muro de
    seis mil.
    """
    piezas, fin_previo, corte_por_silencio = [], None, False
    for tramo in tramos or []:
        if not isinstance(tramo, dict):
            continue
        texto = " ".join(str(tramo.get("texto") or "").split())
        if not texto:
            continue
        inicio = float(tramo.get("t_in") or 0.0)
        hueco = None if fin_previo is None else inicio - fin_previo
        if hueco is not None and hueco >= SILENCIO_PARRAFO_S:
            corte_por_silencio = True
        piezas.append((texto, hueco))
        fin_previo = float(tramo.get("t_out") or inicio)

    parrafos, actual, cuantas = [], [], 0
    for texto, hueco in piezas:
        largo = hueco is not None and hueco >= SILENCIO_PARRAFO_S
        lleno = not corte_por_silencio and cuantas >= PALABRAS_PARRAFO
        if actual and (largo or lleno):
            parrafos.append(" ".join(actual))
            actual, cuantas = [], 0
        actual.append(texto)
        cuantas += len(texto.split())
    if actual:
        parrafos.append(" ".join(actual))
    return "\n\n".join(parrafos)


class _EnLaVersion:
    """Un `proyecto` de mentira que trabaja DENTRO de la carpeta de una version.

    `p1_ingesta.ejecutar` solo usa `proyecto.ruta_trabajo(paso)`, asi que con
    esto se le puede pedir que produzca su salida encima de la version que ya
    existe -- en vez de crear una version nueva, que moveria la activa.
    """

    def __init__(self, carpeta):
        self.carpeta = carpeta

    def ruta_trabajo(self, _paso, crear=True):
        if crear:
            os.makedirs(self.carpeta, exist_ok=True)
        return self.carpeta


def _rehacer_ingesta(estado, proyecto, aplicar, avisos):
    """La ingesta, con el material como TEXTO y su version reproducible."""
    datos = estado._doc["pasos"]["ingesta"]
    params = dict(datos.get("params") or {})
    if params.get("texto"):
        avisos.append("ingesta: ya tiene `texto`; se deja como esta")
        return 0

    activa = datos.get("activa")
    if activa is None:
        avisos.append("ingesta: sin version activa, no hay material que traer")
        return 0
    carpeta = os.path.join(proyecto.raiz, "pasos", "ingesta", f"v{activa}")

    documento = {}
    for nombre in ("ingesta.json", "transcript.json"):
        ruta = os.path.join(carpeta, nombre)
        if os.path.exists(ruta):
            documento = json.load(io.open(ruta, encoding="utf-8"))
            if documento.get("transcript"):
                break
    tramos = documento.get("transcript") or []
    if not tramos:
        avisos.append(f"ingesta: no encuentro el transcript en {carpeta}")
        return 0

    texto = texto_del_transcript(tramos)
    metadatos = documento.get("metadatos") or {}
    nuevos = {
        "texto": texto,
        "titulo": str(metadatos.get("titulo") or "").strip(),
        "idioma": str(metadatos.get("idioma_transcript") or "").strip().lower(),
    }
    palabras = len(texto.split())
    print(f"  ingesta: {len(tramos)} tramos -> {palabras} palabras en "
          f"{texto.count(chr(10) * 2) + 1} parrafo(s)")
    if not aplicar:
        return 1

    # LA VERSION, PRODUCIDA POR EL PASO DE HOY. Se le da la carpeta de la
    # version como carpeta de trabajo: escribe ingesta.json, transcript.json y
    # material.txt encima de los que habia.
    salidas = p1_ingesta.ejecutar(_EnLaVersion(carpeta), nuevos,
                                  lambda *_a, **_k: None)
    datos["params"] = nuevos
    datos["salidas"] = salidas
    for v in (datos.get("versiones") or []):
        if isinstance(v, dict) and v.get("n") == activa:
            v["params"] = dict(nuevos)
            v["salidas"] = dict(salidas)

    # y fuera lo que en esta version no existe
    for nombre in sorted(os.listdir(carpeta)):
        entera = os.path.join(carpeta, nombre)
        if os.path.isdir(entera):
            if nombre in CARPETAS_FUERA_INGESTA:
                shutil.rmtree(entera, ignore_errors=True)
            continue
        if nombre.lower().endswith(FUERA_DE_LA_INGESTA) or nombre in (
                "transcript.txt", "frames_utiles.json"):
            os.remove(entera)
    return 1


# ------------------------------------------------------------- params y salidas

def _limpiar_cta(ficha):
    """La `cta` sin el campo `producto`, que aqui no existe."""
    if not isinstance(ficha, dict):
        return ficha, 0
    fuera = 0
    for momento in list(ficha):
        ranura = ficha.get(momento)
        if isinstance(ranura, dict) and "producto" in ranura:
            ranura.pop("producto")
            fuera += 1
    return ficha, fuera


def _podar_paso(estado, pid, aplicar):
    """Quita de un paso los params y las salidas que ya no existen. -> cuantos"""
    datos = estado._doc["pasos"].get(pid) or {}
    fuera = 0

    def poda(sitio, claves):
        nonlocal fuera
        if not isinstance(sitio, dict):
            return
        for clave in claves:
            if clave in sitio:
                if aplicar:
                    sitio.pop(clave)
                fuera += 1

    bloques = [datos.get("params"), datos.get("salidas")]
    for v in (datos.get("versiones") or []):
        if isinstance(v, dict):
            bloques.append(v.get("params"))
            bloques.append(v.get("salidas"))

    claves_p = FUERA_DE_PARAMS.get(pid, ())
    claves_s = FUERA_DE_SALIDAS.get(pid, ())
    for indice, sitio in enumerate(bloques):
        poda(sitio, claves_p if indice % 2 == 0 else claves_s)
        if isinstance(sitio, dict) and isinstance(sitio.get("cta"), dict):
            _ficha, n = _limpiar_cta(sitio["cta"])
            fuera += n
    return fuera


def traer_proyecto(carpeta, aplicar):
    proyecto = Proyecto(carpeta)
    estado = Estado(proyecto)
    avisos = []
    print(f"\n=== {carpeta}")

    total = _rehacer_ingesta(estado, proyecto, aplicar, avisos)
    for pid in PASOS_POR_ID:
        n = _podar_paso(estado, pid, aplicar)
        if n:
            print(f"  {pid}: {n} clave(s) de features que ya no existen")
            total += n
    for a in avisos:
        print(f"  aviso: {a}")
    if aplicar:
        estado._guardar()
        print("  escrito. AHORA hay que mudar las rutas y re-sellar:")
        print("    python herramientas/mudar_proyecto.py <carpeta> "
              "--regla '<origen>=<destino>' --aplicar --sellar-todo")
    else:
        print(f"  (simulacro) {total} cambio(s)")
    return 0


# ------------------------------------------------------------------- presets

def traer_presets(ruta, aplicar):
    """Los estilos, al contrato de hoy. Devuelve 0."""
    print(f"\n=== {ruta}")
    documento = json.load(io.open(ruta, encoding="utf-8"))
    # LOS DE LA PAPELERA TAMBIEN. Ahi no se ven, pero se pueden devolver, y uno
    # devuelto con las claves de antes es la misma sorpresa mas tarde.
    fichas = list(documento.get("presets") or [])
    enpapelera = list(documento.get("papelera") or [])
    fichas += enpapelera
    print(f"  {len(fichas) - len(enpapelera)} en uso + {len(enpapelera)} en la papelera")
    tocados = 0
    for ficha in fichas:
        if not isinstance(ficha, dict):
            continue
        nombre = ficha.get("nombre") or ficha.get("id")
        datos = ficha.get("datos") or {}
        cambios = []

        # los personajes FIJOS del canal: la feature no existe
        if "personajes" in datos:
            cambios.append(f"personajes ({len(datos.get('personajes') or [])})")
            if aplicar:
                datos.pop("personajes")

        # LA CTA DEL PRESET: aqui se decide video por video, asi que se cae del
        # canal. Y SE IMPRIME LO QUE DECIA, porque es texto que escribio una
        # persona: los videos que ya existen se lo quedan en sus propios params,
        # pero para los siguientes hay que volver a escribirlo una vez, y
        # borrarlo en silencio seria perderlo.
        guion = datos.get("guion")
        if isinstance(guion, dict) and "cta" in guion:
            puestas = [(m, r) for m, r in (guion["cta"] or {}).items()
                       if isinstance(r, dict) and r.get("puesto")
                       and str(r.get("texto") or "").strip()]
            cambios.append(f"cta del preset ({len(puestas)} con texto) "
                           f"-- se decide por video; el texto, aqui debajo")
            for momento, ranura in puestas:
                cambios.append(f"    [{momento}] {ranura['texto']}")
            if aplicar:
                guion.pop("cta")

        # el origen: el video del que salio el estilo, por sus referencias
        origen = ficha.get("origen")
        if not isinstance(origen, dict):
            origen = datos.get("origen") if isinstance(datos.get("origen"), dict) else None
        if isinstance(origen, dict):
            if origen.get("estilo_url"):
                cambios.append("origen.estilo_url")
                if aplicar:
                    origen.pop("estilo_url")
            if origen.get("personajes"):
                cambios.append(f"origen.personajes "
                               f"({len(origen['personajes'])})")
                if aplicar:
                    origen.pop("personajes")
            # EL TONO SE ESCRIBE, y sin `tono_prompt` no se puede rehacer: la
            # pantalla lo pediria en blanco. Los estilos de antes lo sacaban de
            # unos videos (`tono_urls`), y lo mas cercano a unas indicaciones
            # que dejaron es el RESUMEN de la guia que salio -- una frase que
            # describe como suena el canal, que es exactamente lo que se pide
            # ahora. La guia completa NO sirve: son dos mil palabras.
            if not origen.get("tono_prompt"):
                resumen = str(origen.get("tono_resumen") or "").strip()
                primera = resumen.split("\n")[0].strip()
                if len(primera) >= 12:
                    cambios.append(f"origen.tono_prompt <- del resumen del tono: "
                                   f"«{primera[:70]}…»")
                    if aplicar:
                        origen["tono_prompt"] = primera
                else:
                    cambios.append("origen.tono_prompt se queda VACIO (este "
                                   "estilo no dejo resumen del tono): rehacer "
                                   "el tono pedira las indicaciones")
            for clave in ("tono_url", "tono_urls"):
                if origen.get(clave):
                    cambios.append(f"origen.{clave}")
                    if aplicar:
                        origen.pop(clave)
            if not origen.get("estilo_imagenes"):
                refs = ((datos.get("estilo") or {}).get("referencias") or [])
                rutas = [r.get("ruta") if isinstance(r, dict) else r
                         for r in refs]
                rutas = [str(r) for r in rutas if r]
                if rutas:
                    cambios.append(f"origen.estilo_imagenes <- {len(rutas)} "
                                   f"referencias del propio estilo")
                    if aplicar:
                        origen["estilo_imagenes"] = rutas

        # y la url del estilo, que era la del video de referencia
        estilo = datos.get("estilo")
        if isinstance(estilo, dict) and estilo.get("url"):
            cambios.append("estilo.url")
            if aplicar:
                estilo.pop("url")

        if cambios:
            tocados += 1
            print(f"  · {nombre!r}")
            for c in cambios:
                print(f"      {c}")

    if aplicar:
        tmp = ruta + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(
            json.dumps(documento, ensure_ascii=False, indent=1))
        os.replace(tmp, ruta)
        print(f"  escrito: {tocados} preset(s) tocados")
    else:
        print(f"  (simulacro) {tocados} preset(s)")
    return 0


def traer_recetas(ruta, aplicar):
    """Las recetas del canal, con las tareas de HOY y nada mas.

    Una receta dice que tareas OPCIONALES corren en una pestana. Las de la
    version anterior nombran tareas que aqui no existen --`integraciones`,
    `fuentes`, `plan_callouts`-- y les faltan las que se anadieron despues.
    Ninguna de las dos cosas revienta (`recetas.puestas_de` ignora lo que no
    conoce y le da a lo que falta su `de_fabrica`), pero deja la receta
    diciendo una cosa y el software otra, y eso se lee mal el dia que alguien
    la abra.

    Asi que se reescribe: se conserva el valor que la receta le daba a cada
    tarea que SIGUE existiendo, lo que no existe se va, y lo que falta se pone
    a su `de_fabrica`. Los ajustes por tarea (modelo y esfuerzo) se conservan
    tal cual: son decisiones de quien la escribio.
    """
    print("")
    print(f"=== {ruta}")
    documento = json.load(io.open(ruta, encoding="utf-8"))
    tocadas = 0
    for receta in (documento.get("recetas") or []):
        if not isinstance(receta, dict):
            continue
        pestana = str(receta.get("pestana") or "")
        conocidas = {t["id"]: bool(t.get("de_fabrica", True))
                     for t in recetas.tareas_de(pestana)}
        antes = dict(receta.get("tareas") or {})
        if not conocidas:
            print(f"  · {receta.get('nombre')!r} ({pestana}): esa pestana no "
                  f"existe aqui; se deja como esta")
            continue
        nuevas = {tid: (bool(antes[tid]) if tid in antes else defecto)
                  for tid, defecto in conocidas.items()}
        fuera = sorted(set(antes) - set(conocidas))
        entran = sorted(set(conocidas) - set(antes))
        if not fuera and not entran:
            continue
        tocadas += 1
        print(f"  · {receta.get('nombre')!r} ({pestana})")
        for tid in fuera:
            print(f"      fuera: «{tid}», que en esta version no existe")
        for tid in entran:
            print(f"      entra: «{tid}» = {nuevas[tid]} (lo que dice su "
                  f"de_fabrica)")
        if aplicar:
            receta["tareas"] = nuevas

    # y el ajuste de una tarea que ya no esta tampoco pinta nada
    for receta in (documento.get("recetas") or []):
        ajustes = receta.get("ajustes")
        if not isinstance(ajustes, dict):
            continue
        for tid in [x for x in ajustes if x not in recetas.TAREAS_POR_ID]:
            print(f"      fuera: el ajuste de «{tid}», que ya no existe")
            if aplicar:
                ajustes.pop(tid)

    if aplicar:
        tmp = ruta + ".tmp"
        io.open(tmp, "w", encoding="utf-8").write(
            json.dumps(documento, ensure_ascii=False, indent=1))
        os.replace(tmp, ruta)
        print(f"  escrito: {tocadas} receta(s) tocadas")
    else:
        print(f"  (simulacro) {tocadas} receta(s)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("que", choices=("proyecto", "presets", "recetas"))
    ap.add_argument("objetivo")
    ap.add_argument("--aplicar", action="store_true",
                    help="escribir de verdad (sin esto es un simulacro)")
    args = ap.parse_args(argv)
    objetivo = os.path.abspath(args.objetivo)
    if not os.path.exists(objetivo):
        ap.error(f"no existe: {objetivo}")
    print("APLICANDO" if args.aplicar else "SIMULACRO")
    if args.que == "proyecto":
        return traer_proyecto(objetivo, args.aplicar)
    if args.que == "recetas":
        return traer_recetas(objetivo, args.aplicar)
    return traer_presets(objetivo, args.aplicar)


if __name__ == "__main__":
    raise SystemExit(main())
