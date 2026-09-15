"""
Motor de voz: Cartesia sonic-3 con marcas de tiempo por palabra.

Se usa la ruta SSE en lugar de /tts/bytes porque devuelve word timestamps, y son
esos timestamps los que permiten sincronizar la animacion con la narracion sin
adivinar. Si SSE falla se cae a /tts/bytes, que da audio pero sin marcas: en ese
caso el consumidor tendra que repartir el tiempo proporcionalmente.

Uso:
    python voz.py --plan plan.json --out ./audio [--idioma es]

Espera un JSON con una lista "escenas", cada una con "id" y "narracion".
Escribe <out>/<id>.wav y <out>/audio_meta.json.
"""
import argparse
import base64
import json
import os
import re
import struct
import sys

import requests

API_SSE = "https://api.cartesia.ai/tts/sse"
API_BYTES = "https://api.cartesia.ai/tts/bytes"
API_VERSION = "2025-04-16"
MODELO = "sonic-3"
SR = 44100

VOCES = {
    "es": {"id": "b042270c-d46f-4d4f-8fb0-7dd7c5fe5615", "nombre": "Hector - Tour Leader"},
    "en": {"id": "a892d232-f705-40d7-bc8d-e368b295ec2a", "nombre": "Harlan - Vintage Tone"},
}

#: La carpeta de secretos se puede mover con ESTUDIO_SECRETOS: en el servidor
#: cada cuenta tiene la suya. Sin la variable, el valor es el de siempre.
CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")
RUTAS_ENV = [
    os.path.join(CARPETA_SECRETOS, ".env"),
]

#: El almacen que escribe la pantalla de configuracion del Estudio
#: (pasos/claves.py). Se lee por CONTRATO -- una ruta y una forma --, nunca
#: importando codigo del Estudio: este motor tambien lo usan otras cosas.
RUTA_CLAVES = os.path.join(CARPETA_SECRETOS, "claves.json")


def _del_almacen():
    if not os.path.exists(RUTA_CLAVES):
        return ""
    try:
        with open(RUTA_CLAVES, "r", encoding="utf-8-sig") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return ""
    ficha = datos.get("cartesia") if isinstance(datos, dict) else None
    if isinstance(ficha, dict):
        return str(ficha.get("clave") or "").strip()
    return ""


def cargar_api_key():
    """La clave nunca se pasa por linea de comandos: se lee del entorno, del
    almacen de claves del Estudio, o de los .env conocidos."""
    clave = os.environ.get("CARTESIA_API_KEY")
    if clave:
        return clave.strip()
    clave = _del_almacen()
    if clave:
        return clave
    for ruta in RUTAS_ENV:
        if not os.path.exists(ruta):
            continue
        # utf-8-sig y no utf-8: el .env de secrets empieza con BOM, asi que si
        # alguien pone CARTESIA_API_KEY en su primera linea el regex no
        # enganchaba y el fallo salia como "no encuentro la clave", que manda a
        # buscar al sitio equivocado.
        with open(ruta, "r", encoding="utf-8-sig") as fh:
            for linea in fh:
                m = re.match(r"^CARTESIA_API_KEY=(.*)$", linea.strip())
                if m:
                    return m.group(1).strip()
    raise SystemExit(
        "No encuentro CARTESIA_API_KEY. Ponla en la pantalla de Configuracion "
        f"(se guarda en {RUTA_CLAVES}), o en el entorno.")


def wav_desde_pcm(pcm: bytes) -> bytes:
    """Cabecera WAV PCM s16le mono sobre PCM crudo."""
    cabecera = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    cabecera += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16)
    cabecera += b"data" + struct.pack("<I", len(pcm))
    return cabecera + pcm


def _cuerpo(transcript, voz_id, idioma, timestamps):
    cuerpo = {
        "model_id": MODELO,
        "transcript": transcript,
        "voice": {"mode": "id", "id": voz_id},
        "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": SR},
        "language": idioma,
    }
    if timestamps:
        cuerpo["add_timestamps"] = True
    return cuerpo


def tts_sse(api_key, voz_id, idioma, transcript):
    cabeceras = {
        "X-API-Key": api_key,
        "Cartesia-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    respuesta = requests.post(API_SSE, headers=cabeceras,
                              json=_cuerpo(transcript, voz_id, idioma, True),
                              stream=True, timeout=180)
    if respuesta.status_code != 200:
        raise RuntimeError(f"SSE HTTP {respuesta.status_code}: {respuesta.text[:200]}")

    trozos, palabras = [], []
    for linea in respuesta.iter_lines(decode_unicode=True):
        if not linea or not linea.startswith("data:"):
            continue
        try:
            evento = json.loads(linea[5:].strip())
        except json.JSONDecodeError:
            continue
        if evento.get("data"):
            trozos.append(base64.b64decode(evento["data"]))
        wt = evento.get("word_timestamps")
        if wt and wt.get("words"):
            for w, ini, fin in zip(wt["words"], wt["start"], wt["end"]):
                palabras.append({"w": w, "s": round(ini, 3), "e": round(fin, 3)})

    pcm = b"".join(trozos)
    if not pcm:
        raise RuntimeError("SSE sin audio")
    return wav_desde_pcm(pcm), len(pcm) / (SR * 2), palabras


def tts_bytes(api_key, voz_id, idioma, transcript):
    cabeceras = {
        "X-API-Key": api_key,
        "Cartesia-Version": API_VERSION,
        "Content-Type": "application/json",
    }
    respuesta = requests.post(API_BYTES, headers=cabeceras,
                              json=_cuerpo(transcript, voz_id, idioma, False),
                              timeout=180)
    if respuesta.status_code != 200:
        raise RuntimeError(f"bytes HTTP {respuesta.status_code}: {respuesta.text[:200]}")
    pcm = respuesta.content
    return wav_desde_pcm(pcm), len(pcm) / (SR * 2), None


def _normalizar(palabra):
    return re.sub(r"[^\wáéíóúüñ]", "", palabra.lower())


def _repartir_palabras(escenas, palabras):
    """Asigna a cada escena el tramo de palabras que le corresponde.

    Se recorre la lista devuelta por Cartesia en orden y se van consumiendo las
    palabras de cada escena. Se compara normalizado porque el modelo puede
    devolver la puntuacion pegada o separada, y un desajuste de un token
    desplazaria todos los cortes siguientes.
    """
    reparto = {}
    i = 0
    for escena in escenas:
        esperadas = [_normalizar(p) for p in (escena.get("narracion") or "").split()]
        esperadas = [p for p in esperadas if p]
        tramo = []
        for esperada in esperadas:
            # Ventana de tolerancia por si el modelo parte o une un token
            j = i
            while j < min(i + 3, len(palabras)):
                if _normalizar(palabras[j]["w"]) == esperada:
                    break
                j += 1
            if j < min(i + 3, len(palabras)):
                tramo.extend(palabras[i:j + 1])
                i = j + 1
            elif i < len(palabras):
                tramo.append(palabras[i])
                i += 1
        reparto[escena["id"]] = tramo
    # Lo que sobre se cuelga de la ultima escena con texto
    if i < len(palabras) and reparto:
        ultimo = [e["id"] for e in escenas if (e.get("narracion") or "").strip()]
        if ultimo:
            reparto[ultimo[-1]].extend(palabras[i:])
    return reparto


def _pcm_de_wav(wav: bytes) -> bytes:
    """Extrae el PCM saltando la cabecera de 44 bytes que escribimos nosotros."""
    return wav[44:]


#: Milisegundos de fundido al pegar el relleno. Sin esto, el salto de amplitud
#: en el empalme suena como un chasquido, que es peor que el problema original.
FUNDIDO_MS = 12


def _relleno_de_sala(pcm, desde_seg, hasta_seg, duracion):
    """Ruido de sala para rellenar un hueco, sacado de la PROPIA pausa.

    Antes se insertaban ceros. Una toma continua tiene su suelo de ruido, y
    cortarlo a cero durante mas de un segundo se oye como un corte: el fondo
    desaparece de golpe y vuelve. Con 88 bloques y 1,2 s de hueco eran 62 s de
    vacio digital en un video de 15 minutos, uno en cada frontera de bloque.

    La mejor muestra de ruido de sala es la de la pausa que se esta ensanchando,
    asi que se toma de ahi y se repite. Se alterna con su reverso para que la
    repeticion no cree un patron audible.
    """
    bytes_por_seg = SR * 2
    necesarios = int(duracion * bytes_por_seg) & ~1
    if necesarios <= 0:
        return b""
    # semilla: el centro de la pausa natural, hasta 200 ms
    ancho = max(0.0, hasta_seg - desde_seg)
    if ancho < 0.04:
        return b"\x00" * necesarios          # no hay pausa de la que sacar nada
    toma = min(0.2, ancho * 0.8)
    centro = (desde_seg + hasta_seg) / 2.0
    ini = int((centro - toma / 2) * bytes_por_seg) & ~1
    fin = (ini + (int(toma * bytes_por_seg) & ~1))
    semilla = pcm[max(0, ini):min(len(pcm), fin)]
    if len(semilla) < 4:
        return b"\x00" * necesarios

    reverso = semilla[::-1]
    # el reverso de un buffer de bytes invierte tambien los dos bytes de cada
    # muestra: se rehace por pares para que siga siendo audio y no ruido blanco
    reverso = b"".join(reverso[i:i + 2][::-1] for i in range(0, len(reverso) - 1, 2))
    trozos, largo, vuelta = [], 0, 0
    while largo < necesarios:
        pieza = semilla if vuelta % 2 == 0 else reverso
        trozos.append(pieza)
        largo += len(pieza)
        vuelta += 1
    relleno = bytearray(b"".join(trozos)[:necesarios])

    # fundido de entrada y de salida sobre el relleno
    muestras = FUNDIDO_MS * SR // 1000
    for i in range(min(muestras, len(relleno) // 2)):
        factor = i / muestras
        for pos in (i * 2, len(relleno) - 2 - i * 2):
            valor = int.from_bytes(relleno[pos:pos + 2], "little", signed=True)
            relleno[pos:pos + 2] = int(valor * factor).to_bytes(2, "little", signed=True)
    return bytes(relleno)


def espaciar(wav, palabras, reparto, escenas, hueco_minimo=1.0):
    """Ensancha los silencios ENTRE escenas sin re-sintetizar nada.

    Una lectura continua encadena las frases con pausas cortas, y algunos planos
    se quedan por debajo de dos segundos. Trocear la sintesis lo arreglaria pero
    devolveria el problema de origen: cada frase arrancando en frio. Aqui se
    conserva la toma tal cual y solo se estira el silencio en los cortes, asi que
    la prosodia dentro de cada frase queda intacta.

    Lo que se inserta es RUIDO DE SALA de la propia pausa, no ceros: ver
    _relleno_de_sala.

    Devuelve (wav_nuevo, desplazamientos) donde desplazamientos es el retardo
    acumulado a aplicar a cada marca segun el instante en que caiga.
    """
    pcm = _pcm_de_wav(wav)
    bytes_por_seg = SR * 2

    # Cortes: (instante original, silencio a insertar, pausa natural)
    cortes = []
    con_voz = [e for e in escenas if reparto.get(e["id"])]
    for anterior, siguiente in zip(con_voz, con_voz[1:]):
        fin = reparto[anterior["id"]][-1]["e"]
        inicio = reparto[siguiente["id"]][0]["s"]
        falta = hueco_minimo - (inicio - fin)
        if falta > 0.01:
            cortes.append((fin + (inicio - fin) / 2, falta, fin, inicio))

    if not cortes:
        return wav, []

    trozos = []
    anterior_byte = 0
    acumulado = 0.0
    desplazamientos = []
    for instante, silencio, desde, hasta in cortes:
        corte_byte = int(instante * bytes_por_seg) & ~1        # alineado a muestra
        trozos.append(pcm[anterior_byte:corte_byte])
        trozos.append(_relleno_de_sala(pcm, desde, hasta, silencio))
        anterior_byte = corte_byte
        acumulado += silencio
        desplazamientos.append({"desde": instante, "retardo": round(acumulado, 3)})
    trozos.append(pcm[anterior_byte:])

    return wav_desde_pcm(b"".join(trozos)), desplazamientos


def aplicar_desplazamiento(instante, desplazamientos):
    retardo = 0.0
    for d in desplazamientos:
        if instante >= d["desde"]:
            retardo = d["retardo"]
    return round(instante + retardo, 3)


def sintetizar_continuo(plan, out_dir, idioma="es", nombre="narracion.wav",
                        hueco_minimo=1.0):
    """UNA sola toma para todo el video.

    Sintetizar frase a frase suena artificial: cada linea arranca en frio, sin
    continuidad de entonacion ni de energia entre planos. Con una toma unica la
    prosodia fluye, y los cortes de escena se deducen despues de las marcas de
    palabra, que son exactas.
    """
    api_key = cargar_api_key()
    voz = VOCES[idioma]
    os.makedirs(out_dir, exist_ok=True)

    escenas = plan["escenas"]
    partes = [(e.get("narracion") or "").strip() for e in escenas]
    transcript = " ".join(p for p in partes if p)
    if not transcript:
        raise SystemExit("El plan no tiene narracion")

    print(f"[voz] toma unica: {len(transcript)} caracteres, "
          f"{len(transcript.split())} palabras")
    wav, duracion, palabras = tts_sse(api_key, voz["id"], idioma, transcript)
    reparto = _repartir_palabras(escenas, palabras or [])

    if hueco_minimo > 0:
        wav, desplazamientos = espaciar(wav, palabras, reparto, escenas,
                                        hueco_minimo)
        if desplazamientos:
            for tramo in reparto.values():
                for p in tramo:
                    p["s"] = aplicar_desplazamiento(p["s"], desplazamientos)
                    p["e"] = aplicar_desplazamiento(p["e"], desplazamientos)
            anadido = desplazamientos[-1]["retardo"]
            duracion += anadido
            print(f"[voz] silencio insertado en {len(desplazamientos)} cortes "
                  f"(+{anadido:.2f}s) para que ningun plano baje de {hueco_minimo}s "
                  f"de aire")

    destino = os.path.join(out_dir, nombre)
    with open(destino, "wb") as fh:
        fh.write(wav)
    meta = {
        "modo": "continuo",
        "modelo": MODELO, "api": API_VERSION, "voz": voz, "idioma": idioma,
        "archivo": nombre, "duracion": round(duracion, 3),
        "transcript": transcript,
        "escenas": [],
    }
    for escena in escenas:
        tramo = reparto.get(escena["id"], [])
        meta["escenas"].append({
            "id": escena["id"],
            "duracion": round(tramo[-1]["e"] - tramo[0]["s"], 3) if tramo else 0.0,
            "t_primera_palabra": round(tramo[0]["s"], 3) if tramo else None,
            "t_ultima_palabra": round(tramo[-1]["e"], 3) if tramo else None,
            "palabras": tramo,
        })
        n = len(tramo)
        marca = (f"{tramo[0]['s']:6.2f} -> {tramo[-1]['e']:6.2f}" if tramo
                 else "   sin narracion")
        print(f"  {escena['id']}: {marca}  {n:3d} palabras")

    ruta_meta = os.path.join(out_dir, "audio_meta.json")
    with open(ruta_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print(f"[voz] toma unica de {duracion:.2f}s -> {destino}")
    return meta


def sintetizar_plan(plan, out_dir, idioma="es"):
    api_key = cargar_api_key()
    voz = VOCES[idioma]
    os.makedirs(out_dir, exist_ok=True)

    meta = {"modelo": MODELO, "api": API_VERSION, "voz": voz, "idioma": idioma, "escenas": []}
    for escena in plan["escenas"]:
        texto = (escena.get("narracion") or "").strip()
        if not texto:
            meta["escenas"].append({"id": escena["id"], "archivo": None,
                                    "duracion": 0.0, "palabras": []})
            print(f"  {escena['id']}: sin narracion, se omite")
            continue
        try:
            wav, duracion, palabras = tts_sse(api_key, voz["id"], idioma, texto)
        except Exception as exc:
            print(f"  {escena['id']}: SSE fallo ({exc}) -> fallback bytes")
            wav, duracion, palabras = tts_bytes(api_key, voz["id"], idioma, texto)

        destino = os.path.join(out_dir, f"{escena['id']}.wav")
        with open(destino, "wb") as fh:
            fh.write(wav)
        meta["escenas"].append({
            "id": escena["id"],
            "archivo": os.path.basename(destino),
            "duracion": round(duracion, 3),
            "palabras": palabras or [],
        })
        n = len(palabras) if palabras else 0
        print(f"  {escena['id']}: {duracion:6.2f}s  {n:3d} palabras con marca")

    ruta_meta = os.path.join(out_dir, "audio_meta.json")
    with open(ruta_meta, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    total = sum(e["duracion"] for e in meta["escenas"])
    print(f"[voz] total narracion {total:.1f}s en {len(meta['escenas'])} escenas -> {ruta_meta}")
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--idioma", default="es", choices=sorted(VOCES))
    parser.add_argument("--modo", default="continuo",
                        choices=["continuo", "por_escena"],
                        help="continuo: una sola toma (recomendado). "
                             "por_escena: un wav por escena, suena artificial")
    parser.add_argument("--hueco", type=float, default=1.0,
                        help="silencio minimo entre escenas, en segundos")
    args = parser.parse_args()

    with open(args.plan, "r", encoding="utf-8") as fh:
        plan = json.load(fh)
    if args.modo == "continuo":
        sintetizar_continuo(plan, args.out, args.idioma,
                            hueco_minimo=args.hueco)
    else:
        sintetizar_plan(plan, args.out, args.idioma)


if __name__ == "__main__":
    main()
