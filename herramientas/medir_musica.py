"""Cuanta musica se oye bajo la voz, en el remate de frase y en la pausa.

    python herramientas/medir_musica.py <id_del_proyecto>

Es el banco de pruebas del DUCKING, y mide sobre EL GRAFO DE VERDAD
(`sonido.filtro_de_mezcla`), no sobre una reconstruccion: reconstruirlo aqui
daria numeros de otra cosa el dia que alguien mueva una constante.

POR QUE EXISTE. Los siete numeros del ducking se calibraron el 24-08-2026 con
una locucion SINTETICA (PENDIENTE §31), y una voz de verdad tiene otra dinamica.
Esto los vuelve a medir con la locucion REAL de un video ya generado, que es lo
unico que cierra esa pregunta.

QUE MIDE, Y CONTRA QUE. Se renderiza la musica DOS veces por el mismo grafo: con
el `sidechaincompress` y sin el. La diferencia en dB, ventana a ventana, es
«cuanto agacha el ducking» -- que es un numero comparable entre videos, a
diferencia del nivel absoluto, que depende del tema.

LAS TRES VENTANAS salen de las marcas de palabra de la voz, o sea de donde de
verdad esta hablando:

    bajo la voz        en mitad de una racha de palabras sin huecos
    remate de frase    los ultimos 300 ms de la ultima palabra antes de un
                       silencio: es donde la envolvente de la voz cae, donde la
                       llave sin aplanar se caia con ella, y donde esta el dato
    pausa              en mitad de un silencio de mas de un segundo
"""
import io
import json
import os
import subprocess
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

import numpy as np                                              # noqa: E402

from pasos import medios, sonido                                # noqa: E402

#: Que hueco entre dos palabras cierra una frase. Medido sobre una locucion de
#: verdad: los silencios de punto y aparte de una voz sintetizada rondan el
#: medio segundo, no el segundo entero.
FIN_DE_FRASE_S = 0.45
#: Cuanto dura la ventana del remate de frase.
REMATE_S = 0.30
#: Un silencio de los que se OYEN como silencio. No hay muchos mas largos: una
#: locucion continua rara vez calla mas de un segundo, y el `<break>` del gancho
#: son 900 ms.
PAUSA_S = 0.8
#: Que parte de la pausa se mide: la ULTIMA. El ducking tiene 1,2 s de caida, o
#: sea que el principio de un silencio sigue agachado a proposito -- medir ahi
#: seria medir la caida y no la pausa.
FRACCION_PAUSA = 0.45


def leer(ruta, defecto=None):
    try:
        with io.open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return defecto


def activa(proyecto, paso):
    base = os.path.join(RAIZ, "proyectos", proyecto, "pasos", paso)
    if not os.path.isdir(base):
        return ""
    ficha = leer(os.path.join(base, "activa.json"), {}) or {}
    version = ficha.get("version") or ficha.get("activa")
    if version and os.path.isdir(os.path.join(base, str(version))):
        return os.path.join(base, str(version))
    versiones = sorted((n for n in os.listdir(base)
                        if n.startswith("v") and n[1:].isdigit()),
                       key=lambda n: int(n[1:]))
    return os.path.join(base, versiones[-1]) if versiones else ""


def marcas_del_video(proyecto):
    """Todas las marcas de palabra del video, en orden. -> [(t_in, t_out)]"""
    plan = leer(os.path.join(activa(proyecto, "assets"), "plan.json"), {}) or {}
    marcas = []
    for escena in plan.get("escenas") or []:
        for marca in escena.get("marcas") or []:
            try:
                marcas.append((float(marca[0]), float(marca[1])))
            except (TypeError, ValueError, IndexError):
                pass
    return sorted(marcas)


def ventanas(marcas, duracion):
    """Las tres clases de instante que hay que medir. -> {clase: [(ini, fin)]}"""
    bajo, remate, pausa = [], [], []
    # La CABECERA cuenta como pausa y es la mas honesta de todas: antes de la
    # primera palabra no ha hablado nadie todavia, asi que la musica esta en su
    # nivel de verdad. Es ademas lo primero que oye quien abre el video.
    if marcas and marcas[0][0] > 1.0:
        pausa.append((0.2, marcas[0][0] - 0.15))
    for indice, (entra, sale) in enumerate(marcas):
        siguiente = marcas[indice + 1][0] if indice + 1 < len(marcas) else duracion
        hueco = siguiente - sale
        if hueco >= FIN_DE_FRASE_S:
            remate.append((max(0.0, sale - REMATE_S), sale))
            if hueco >= PAUSA_S:
                ini = siguiente - hueco * FRACCION_PAUSA
                fin = siguiente - 0.10
                if fin - ini >= 0.15:
                    pausa.append((ini, fin))
        elif hueco < 0.12 and sale - entra >= 0.20:
            # en mitad de una racha: la palabra de al lado esta pegada
            bajo.append((entra + 0.05, sale - 0.02))
    return {"bajo la voz": bajo, "remate de frase": remate, "en la pausa": pausa}


def _render(entradas, grafo, destino):
    orden = [medios.ffmpeg(), "-y", "-v", "error"]
    for ruta in entradas:
        orden += ["-i", ruta]
    orden += ["-filter_complex", grafo, "-map", "[salida]",
              "-c:a", "pcm_s16le", "-ar", str(sonido.FRECUENCIA), destino]
    fallo = subprocess.run(orden, capture_output=True, text=True,
                           **medios.SIN_VENTANA)
    if fallo.returncode != 0:
        raise RuntimeError("ffmpeg: " + (fallo.stderr or "")[-500:])
    return destino


def _rms_db(muestras, frecuencia, tramos):
    """El nivel medio en esas ventanas, en dBFS. -> float o None."""
    trozos = []
    for ini, fin in tramos:
        a, b = int(ini * frecuencia), int(fin * frecuencia)
        if 0 <= a < b <= len(muestras):
            trozos.append(muestras[a:b])
    if not trozos:
        return None
    junto = np.concatenate(trozos)
    return 20 * float(np.log10(max(1e-9, float(np.sqrt(np.mean(junto ** 2))))))


def main():
    proyecto = sys.argv[1] if len(sys.argv) > 1 else ""
    if not proyecto:
        print(__doc__)
        return 2
    carpeta = activa(proyecto, "render")
    estado = leer(os.path.join(RAIZ, "proyectos", proyecto, "estado.json"),
                  {}) or {}
    params = ((estado.get("pasos") or {}).get("render") or {}).get("params") or {}
    ajuste = float(params.get("musica_db") or 0.0)

    voz = os.path.join(activa(proyecto, "voz"), "voz.wav")
    if not os.path.exists(voz):
        candidatos = [n for n in os.listdir(activa(proyecto, "voz"))
                      if n.endswith(".wav")]
        voz = os.path.join(activa(proyecto, "voz"), candidatos[0]) if candidatos else ""
    cama = os.path.join(carpeta, "cama.wav")
    ya_normalizada = os.path.exists(cama)
    musica = cama if ya_normalizada else ""
    if not musica:
        banco = (params.get("musica") or {}).get("fichero") or ""
        musica = banco if os.path.exists(banco) else ""
    if not (voz and os.path.exists(voz) and musica):
        print("no encuentro la voz o la musica de ese video")
        print("  voz:    " + str(voz))
        print("  musica: " + str(musica) + " (cama.wav en " + carpeta + ")")
        return 2

    duracion = medios.duracion_media(voz)
    marcas = marcas_del_video(proyecto)
    tramos = ventanas(marcas, duracion)
    print("=" * 66)
    print("DUCKING MEDIDO CON LA VOZ REAL DE " + proyecto)
    print("=" * 66)
    print("voz:    %s (%.1f s, %d marcas de palabra)"
          % (os.path.basename(voz), duracion, len(marcas)))
    print("musica: %s%s" % (os.path.basename(musica),
                            " (cama ya normalizada)" if ya_normalizada else ""))
    print("ajuste de este video (render.musica_db): %+.1f dB" % ajuste)
    for clase, lista in tramos.items():
        print("  %-16s %3d ventanas, %.1f s en total"
              % (clase, len(lista), sum(f - i for i, f in lista)))
    if not all(tramos.values()):
        print("faltan ventanas de alguna clase: la medida seria parcial")

    grafo = sonido.filtro_de_mezcla(True, False, duracion,
                                    ya_normalizada=ya_normalizada,
                                    ajuste_db=ajuste)
    # SOLO LA MUSICA, POR EL MISMO GRAFO. Se cambia la ULTIMA mezcla para que
    # salga la rama de la musica sola; todo lo de antes --el loudnorm, la
    # subida, la llave aplanada y el compresor-- es literalmente el del render.
    # `[vozmix]` se queda sin destino, y una salida de `asplit` sin conectar es
    # un error de ffmpeg, no un aviso: se manda a un sumidero.
    solo_musica = grafo.replace(
        "[vozmix][musduck]amix=inputs=2",
        "[vozmix]anullsink;[musduck]amix=inputs=1")
    if solo_musica == grafo:
        print("el grafo de la mezcla ha cambiado de forma: revisa este script")
        return 3
    # Y LA REFERENCIA: la misma musica sin agachar. Se quita el compresor de
    # cadena lateral y se deja pasar la musica tal cual.
    sin_duck = solo_musica
    for parte in solo_musica.split(";"):
        if parte.startswith("[mus][llave]sidechaincompress"):
            # la llave se queda sin destino, y otra vez: una salida sin
            # conectar es un error de ffmpeg, no un aviso
            sin_duck = solo_musica.replace(
                parte, "[llave]anullsink;[mus]anull[musduck]")
            break
    if sin_duck == solo_musica:
        print("no encuentro el sidechaincompress en el grafo")
        return 3

    tmp = os.path.join(os.environ.get("TEMP", "."), "estudio_medir_musica")
    os.makedirs(tmp, exist_ok=True)
    silencio = os.path.join(tmp, "silencio.wav")
    subprocess.run([medios.ffmpeg(), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "anullsrc=r=%d:cl=stereo" % sonido.FRECUENCIA,
                    "-t", "0.1", silencio], capture_output=True,
                   **medios.SIN_VENTANA)
    entradas = [silencio, voz, musica]          # 0 no se usa, 1 voz, 2 musica
    con = _render(entradas, solo_musica, os.path.join(tmp, "con_duck.wav"))
    sin = _render(entradas, sin_duck, os.path.join(tmp, "sin_duck.wav"))

    muestras_con = sonido._leer(con)                            # noqa: SLF001
    muestras_sin = sonido._leer(sin)                            # noqa: SLF001
    print("")
    print("%-18s %12s %12s %12s" % ("", "sin agachar", "en el video", "agacha"))
    print("-" * 60)
    resultado = {}
    for clase, lista in tramos.items():
        base = _rms_db(muestras_sin, sonido.FRECUENCIA, lista)
        ahora = _rms_db(muestras_con, sonido.FRECUENCIA, lista)
        if base is None or ahora is None:
            print("%-18s %12s" % (clase, "sin ventanas"))
            continue
        resultado[clase] = round(ahora - base, 1)
        print("%-18s %11.1f dB %11.1f dB %11.1f dB"
              % (clase, base, ahora, ahora - base))
    print("")
    print("Lo medido el 24-08 con voz sintetica, para comparar:")
    print("  bajo la voz -48,6 dB · remate de frase -46,8 dB · pausa -29,3 dB")
    print("(son dB relativos a la musica sin agachar, o sea la ultima columna)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
