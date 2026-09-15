"""La CADENCIA de la locucion: cuanto dura lo escrito, dicho con esta voz.

QUE PROBLEMA RESUELVE
---------------------
La duracion objetivo se pide en segundos y el guion se escribe en palabras, asi
que en algun sitio hay que convertir. Hasta el 24-08-2026 esa conversion vivia en
`p2_brief` como una tabla de dos cifras -- 2,6 palabras por segundo en ingles,
2,3 en espanol -- que ignoraba las dos cosas que de verdad mueven el reloj:

  - la VELOCIDAD de la voz. El mismo texto a 'slow' dura un 20 % mas que a
    'normal', y el ritmo del canal la fija (`presets_light.RITMOS`).
  - el AIRE entre bloques. `motor.espaciar` ensancha los silencios de los cortes
    hasta `hueco_minimo`, y eso son segundos que no estan en ninguna palabra.

Y habia una segunda copia de la misma cuenta, en `p4_voz`, para el modo simulado.
Dos tablas para lo mismo se separan en cuanto alguien toca una. Aqui esta la
unica, y `p4_voz` la importa.

LO QUE ESTA MEDIDO Y LO QUE NO
------------------------------
Hay UNA toma real medida, y conviene saber cual es antes de fiarse de un numero
de aqui: el video largo, 369 palabras en ingles a velocidad 'normal' con sonic-3.5
(proyecto `how_they_hacked...`, voz v10).

    duracion de la toma            148,485 s
    aire insertado por espaciar      3,975 s  (11 costuras)
    o sea sintesis pura            144,510 s
    cadencia bruta                   2,553 palabras/s
    aire por costura                 0,361 s con hueco_minimo 0,9

Con esa toma se calibro el estimador que ya existia para el modo simulado, que
daba 184,39 s para esos mismos 369 palabras: un 27,6 % de mas. La correccion es
CALIBRE, y no es cosmetica -- tambien arregla que el modo simulado ensayara
sobre una linea de tiempo un cuarto mas larga que la de verdad.

Todo lo que no sea ingles a 'normal' son cifras ESCRITAS, no medidas. En cuanto
haya tomas reales manda el historial (`cadencia_de`), que es la misma disciplina
que `presets_light.segundos_de`: la tabla es el primer dia, la medida es despues.
"""
import os
import sys

try:
    from . import estadisticas, marcas_tts
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import estadisticas
    import marcas_tts

RAIZ_ESTUDIO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Cadencia bruta a velocidad 'normal', en palabras por segundo de SINTESIS (sin
#: el aire que se inserta despues). El ingles esta MEDIDO sobre la toma del
#: Aurora; los demas son la tabla que traia `p2_brief`, que es de donde
#: salieron y sigue siendo lo unico honesto sin haber medido.
CADENCIA = {"en": 2.553, "es": 2.3}
CADENCIA_OTROS = 2.45

#: EL MULTIPLICADOR QUE RECIBE LA API, y la unica tabla de velocidad que hay.
#:
#: Es el `generation_config.speed` de sonic-3/3.5: 1.0 es normal, 1.3 es un 30 %
#: mas rapido. No son los extremos del rango (0,6..1,5) a proposito: 0,6 arrastra
#: las palabras y 1,5 atropella, y ninguno de los dos es una locucion documental.
#:
#: VIVE AQUI Y NO EN `p4_voz` porque estaban las DOS: alli el multiplicador que
#: se manda y aqui un `FACTOR_VELOCIDAD` escrito a mano que decia lo mismo del
#: reves -- y no coincidian (0,72 de tiempo es 1,39x de velocidad, no 1,30x).
#: Dos tablas para la misma cosa se separan en cuanto alguien toca una, y esta
#: se separo: lo que se le pide a Cartesia y lo que se estima que va a durar no
#: eran el mismo mando.
VELOCIDAD_API = {"slowest": 0.70, "slow": 0.85, "normal": 1.0,
                 "fast": 1.15, "fastest": 1.30}

#: Y cuanto multiplica cada velocidad al TIEMPO, que es el INVERSO exacto de lo
#: anterior. Se deriva y no se escribe: asi no puede volver a desviarse.
FACTOR_VELOCIDAD = {nombre: round(1.0 / valor, 4)
                    for nombre, valor in VELOCIDAD_API.items()}

#: Pausas que el estimador anade al leer. Vienen de `p4_voz` tal cual.
PAUSA_FRASE = 0.35
PAUSA_COMA = 0.15

#: Un <break> no impone su duracion: la SUMA a la pausa que ya habia. Medido con
#: el mismo corte de frase, 0,52 s sin etiqueta y 1,55 s con time="1200ms", o sea
#: ~0,8x de lo pedido.
FACTOR_BREAK = 0.8

#: CALIBRE del estimador contra la realidad. El estimador daba 184,39 s para una
#: toma que duro 144,51 s de sintesis: 0,7837 global. Se aplica solo al termino
#: de la PALABRA --que es el 92 % del total (169,71 de 184,39)-- porque es el que
#: lleva la cadencia; las pausas y los <break> son tiempo escrito y se respetan.
#: Sobre ese termino el factor exacto que reproduce la toma es 0,765.
CALIBRE = 0.765

#: Pausa natural que ya hay entre dos bloques, sin contar lo que el guion escriba.
#: Medida por diferencia: con hueco_minimo 0,9 s la toma del video largo recibio
#: 3,975 s de aire en 11 costuras, o sea 0,361 por costura, luego lo que ya
#: habia promediaba 0,539 s. Es lo que hace que subir el aire de 0,7 a 1,4 --que
#: es lo que mueve el mando de ritmo-- se note en la estimacion.
PAUSA_ENTRE_BLOQUES = 0.54

#: Muestras minimas para que el historial gane a la tabla. Con una sola toma
#: rara --un guion de dos frases, una voz que se atasco-- la media se va, y aqui
#: una cifra mala no se ve: sale como un guion mas largo de la cuenta.
MUESTRAS_MINIMAS = 3

#: Y LA TOMA TIENE QUE SER LO BASTANTE LARGA PARA MEDIR ALGO. Esto no es una
#: precaucion teorica: la suite de voz sale a Cartesia de verdad con frases de
#: DIEZ palabras, y esas tres tomas daban 2,7 palabras/s en castellano --mas
#: rapido que el ingles medido-- porque en diez palabras no cabe ni una pausa de
#: frase ni una costura entre bloques. Con eso dentro, pedir la voz 'slow' salia
#: MAS rapida que 'normal', que es la cuenta al reves.
PALABRAS_MINIMAS_MEDIDA = 60


# --------------------------------------------------------------- velocidad

def factor_velocidad(velocidad):
    """Cuanto multiplica esa velocidad al tiempo. 1.0 es 'normal'."""
    if isinstance(velocidad, (int, float)) and not isinstance(velocidad, bool):
        # -1 es lo mas lento y 1 lo mas rapido: mismo rango que los presets
        return 1.0 - 0.3 * float(velocidad)
    return FACTOR_VELOCIDAD.get(str(velocidad or "normal"), 1.0)


def nombre_velocidad(velocidad):
    """Como se dice esa velocidad en una linea de pantalla."""
    if isinstance(velocidad, (int, float)) and not isinstance(velocidad, bool):
        return f"{float(velocidad):+.2f}"
    return str(velocidad or "normal")


# --------------------------------------------------------------- cadencia

def _idioma(codigo):
    return str(codigo or "").strip().lower().split("-")[0]


def cadencia_escrita(idioma=None):
    """La de la tabla, sin mirar el historial. Palabras por segundo a 'normal'."""
    return CADENCIA.get(_idioma(idioma), CADENCIA_OTROS)


def cadencia_medida(idioma=None, voz=None):
    """Lo que dicen las tomas REALES de esa VOZ (o ese idioma) a velocidad normal.

    SE MIDE UNA SOLA COSA y las cinco velocidades salen de ella. Cada toma se
    devuelve a su equivalente en 'normal' multiplicandola por su propio factor
    --una toma a 'slow' dice un 20 % menos de palabras por segundo, y ese 20 % lo
    pone el mando, no el idioma-- y despues se aplica la velocidad que se pida.

    Se hace asi por dos motivos, y el segundo salio de un fallo de verdad:

      1. la cadencia es una propiedad del IDIOMA y de la voz; la velocidad es un
         mando encima. Guardar cinco medidas independientes reparte las pocas
         muestras que hay entre cinco cajones y ninguno llega a tres.
      2. medidas por separado pueden CONTRADECIRSE. Paso: tres tomas reales de
         diez palabras a 'slow' daban 2,7 palabras/s, asi que pedir 'slow' salia
         mas rapido que 'normal'. Normalizando no puede pasar: el orden lo pone
         FACTOR_VELOCIDAD, que es una tabla y no una muestra.

    LA VOZ MANDA SOBRE EL IDIOMA cuando hay tomas suyas, y eso no es un refinamiento:
    es lo que se midio. Con la toma del video largo a 'normal' (voz v10, ingles)
    salieron 2,553 palabras/s; con la del modo light a 'fastest' (voz Carson,
    ingles) salieron 2,483, que devueltas a 'normal' son 1,91 -- un 25 % menos
    POR LA VOZ, con el mismo idioma y el mismo modelo. Mezclarlas en una media
    del idioma es prometer una duracion que ninguna de las dos va a dar.

    Asi que primero se buscan tomas de ESTA voz; si no hay suficientes, las del
    idioma; y si tampoco, la tabla escrita.

    Solo cuentan las tomas no simuladas --el simulado escribe silencio del largo
    que dice este mismo modulo, asi que seria medirse a uno mismo-- y solo las
    que tengan palabras suficientes (ver PALABRAS_MINIMAS_MEDIDA).
    """
    try:
        registros = estadisticas.historial("voz", solo_ok=True)
    except Exception:                                       # noqa: BLE001
        return None
    codigo = _idioma(idioma)
    quien = str(voz or "").strip()
    de_la_voz, del_idioma = [], []
    for registro in registros:
        detalle = registro.get("detalle") or {}
        if detalle.get("simulado"):
            continue
        cadencia = detalle.get("cadencia_palabras_s")
        if not cadencia:
            continue
        try:
            if int(registro.get("tamano") or 0) < PALABRAS_MINIMAS_MEDIDA:
                continue
        except (TypeError, ValueError):
            continue
        try:
            valor = float(cadencia) * factor_velocidad(detalle.get("velocidad"))
        except (TypeError, ValueError):
            continue
        if valor <= 0:
            continue
        if quien and str(detalle.get("voz_id") or "") == quien:
            de_la_voz.append(valor)
        if not codigo or _idioma(registro.get("idioma")
                                 or detalle.get("idioma")) == codigo:
            del_idioma.append(valor)
    valores = de_la_voz if len(de_la_voz) >= MUESTRAS_MINIMAS else del_idioma
    if len(valores) < MUESTRAS_MINIMAS:
        return None
    ordenados = sorted(valores)
    mitad = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[mitad]
    return (ordenados[mitad - 1] + ordenados[mitad]) / 2.0


def cadencia_de(idioma=None, velocidad=None, voz=None):
    """Palabras por segundo de sintesis con esta voz. -> (valor, de_donde)

    El historial manda en cuanto hay muestras suficientes --de ESTA voz si las
    hay, y si no del idioma--; hasta entonces, la tabla. En los dos casos la
    velocidad se aplica al final y con la MISMA tabla, asi que 'slow' siempre
    cabe en menos palabras que 'normal'.
    """
    medida = cadencia_medida(idioma, voz)
    if medida:
        base, origen = medida, "medido"
    else:
        base = cadencia_escrita(idioma)
        origen = "medido en otro guion" if _idioma(idioma) in ("en",) else "estimado"
    return base / max(0.05, factor_velocidad(velocidad)), origen


# ------------------------------------------------------ estimar sobre texto

def calibre_de(idioma=None, voz=None):
    """El CALIBRE ajustado a lo que de verdad tarda ESTA voz. -> factor

    LAS DOS DIRECCIONES TIENEN QUE USAR LA MISMA MEDIDA. `palabras_para` (de
    segundos a palabras) ya miraba el historial; `estimar` (de texto a segundos)
    no, porque su termino de palabra va por LONGITUD y no por cadencia. O sea
    que con una voz un 25 % mas lenta, planificar decia una cosa y medir lo
    escrito decia otra -- y las dos se equivocaban en el mismo sitio.

    Se corrige aqui: si hay medida, el calibre se escala por lo que esa voz se
    separa de la tabla. Sin medida, el CALIBRE de siempre.
    """
    medida = cadencia_medida(idioma, voz)
    base = cadencia_escrita(idioma)
    if not medida or not base or medida <= 0:
        return CALIBRE
    return CALIBRE * (base / medida)


def duracion_palabra(palabra, factor=1.0, calibre=None):
    """Cuanto tarda en leerse una palabra, estimado por su longitud.

    El CALIBRE va aqui y no fuera porque este es el termino que lleva la
    cadencia: las pausas de frase y los <break> son tiempo escrito, y corregirlos
    con el mismo factor cambiaria donde para el relato, que es una decision de
    guion y no una medida.
    """
    fino = CALIBRE if calibre is None else float(calibre)
    return max(0.12, len(palabra) * 0.055 + 0.18) * factor * fino


def marcas_de(texto, factor=1.0, desde=0.0, calibre=None):
    """Marcas de palabra plausibles sin sintetizar nada. -> ([{w,s,e}], final)

    Las anotaciones de voz no son palabras: no se devuelven como marcas, igual
    que no las devuelve Cartesia. Los <break> si cuentan para el reloj, para que
    en simulado los tiempos se parezcan a los de verdad y el aire entre bloques
    salga donde va a salir.
    """
    # El texto se parte en tramos separados por los silencios. Cada tramo se
    # arma como lo arma marcas_tts.limpiar -- el contenido de <spell> pegado a
    # lo que tenga al lado y un espacio donde iba cualquier otra etiqueta --
    # porque las palabras que salgan de aqui se reparten despues contra ese
    # mismo texto limpio. Partir distinto aunque sea en un token deja un bloque
    # con una palabra de mas y el resto del reparto corrido.
    tramos, actual = [], ""
    for clase, pieza in marcas_tts.trocear(str(texto or "")):
        if clase == "break":
            tramos.append((actual, (pieza / 1000.0) * FACTOR_BREAK))
            actual = ""
        elif clase == "texto":
            actual += str(pieza)
        elif clase == "spell":
            actual += str(pieza)      # se deletrea, pero es una palabra
        else:
            actual += " "             # donde iba la etiqueta queda separacion
    tramos.append((actual, 0.0))

    palabras = []
    reloj = float(desde)
    for tramo, silencio in tramos:
        for cruda in tramo.split():
            duracion = duracion_palabra(cruda, factor, calibre)
            palabras.append({"w": cruda, "s": round(reloj, 3),
                             "e": round(reloj + duracion, 3)})
            reloj += duracion
            if cruda.endswith((".", "!", "?", ":", "...")):
                reloj += PAUSA_FRASE * factor
            elif cruda.endswith((",", ";")):
                reloj += PAUSA_COMA * factor
        reloj += silencio
    return palabras, round(reloj, 3)


def aire_de(textos, hueco_minimo=0.0):
    """Segundos que `motor.espaciar` va a insertar entre esos bloques.

    Se cuenta costura a costura y no como `hueco x bloques`: un bloque que ya
    termina con un <break> largo no recibe aire ninguno, y en un guion con
    capitulos eso es la mitad de las costuras.
    """
    hueco = max(0.0, float(hueco_minimo or 0.0))
    if hueco <= 0:
        return 0.0
    vivos = [t for t in textos if str(t or "").strip()]
    total = 0.0
    for texto in vivos[:-1]:
        natural = PAUSA_ENTRE_BLOQUES + marcas_tts.silencio_final(texto) / 1000.0
        total += max(0.0, hueco - natural)
    return round(total, 3)


def estimar(bloques, idioma=None, velocidad=None, hueco_minimo=0.0, voz=None):
    """Cuanto va a durar este guion dicho con esta voz. -> ficha

    `bloques` son textos, o fichas con 'texto'. La ficha que sale trae las tres
    cifras por separado --habla, aire y total-- porque son tres decisiones
    distintas: el largo del guion, la velocidad y el ritmo del montaje.
    """
    textos = []
    for bloque in (bloques or []):
        if isinstance(bloque, dict):
            textos.append(str(bloque.get("texto") or ""))
        else:
            textos.append(str(bloque or ""))
    factor = factor_velocidad(velocidad)
    calibre = calibre_de(idioma, voz)
    habla = 0.0
    palabras = 0
    for texto in textos:
        _marcas, final = marcas_de(texto, factor, calibre=calibre)
        habla += final
        palabras += marcas_tts.contar_palabras(texto)
    aire = aire_de(textos, hueco_minimo)
    return {
        "palabras": palabras,
        "bloques": len([t for t in textos if t.strip()]),
        "habla_s": round(habla, 2),
        "aire_s": round(aire, 2),
        "segundos": round(habla + aire, 2),
        "idioma": _idioma(idioma),
        "velocidad": nombre_velocidad(velocidad),
        "hueco_minimo": round(float(hueco_minimo or 0.0), 3),
        # de donde sale la cifra: la tabla escrita o las tomas de esta voz
        "cadencia_origen": cadencia_de(idioma, velocidad, voz)[1],
    }


# ------------------------------------------------------ de segundos a palabras

def palabras_para(segundos, idioma=None, velocidad=None, hueco_minimo=0.0,
                  palabras_por_bloque=30, voz=None):
    """Cuantas palabras caben en esa duracion. -> ficha

    Es la inversa de `estimar`, y por eso vive al lado: separadas, una diria una
    cosa al planificar y la otra otra al medir lo escrito.

    El aire depende de cuantos bloques haya y los bloques dependen de cuantas
    palabras: se resuelve en dos pasadas, que con estas cifras converge de sobra
    -- el aire es del orden del 3 % del total --.
    """
    total = max(0.0, float(segundos or 0.0))
    cadencia, origen = cadencia_de(idioma, velocidad, voz)
    por_bloque = max(5, int(palabras_por_bloque or 30))
    hueco = max(0.0, float(hueco_minimo or 0.0))
    # aire por costura si ningun bloque trae silencio escrito: es lo unico que
    # se puede suponer antes de que el guion exista
    por_costura = max(0.0, hueco - PAUSA_ENTRE_BLOQUES)

    palabras = int(round(total * cadencia))
    for _ in range(2):
        bloques = max(1, int(round(palabras / por_bloque)))
        aire = por_costura * max(0, bloques - 1)
        palabras = max(1, int(round(max(0.0, total - aire) * cadencia)))
    bloques = max(1, int(round(palabras / por_bloque)))
    return {
        "palabras": palabras,
        "bloques": bloques,
        "aire_s": round(por_costura * max(0, bloques - 1), 2),
        "cadencia_palabras_s": round(cadencia, 3),
        "cadencia_origen": origen,
        "idioma": _idioma(idioma),
        "velocidad": nombre_velocidad(velocidad),
        "hueco_minimo": round(hueco, 3),
    }


def segundos_para(palabras, idioma=None, velocidad=None, hueco_minimo=0.0,
                  palabras_por_bloque=30, voz=None):
    """Lo que va a durar un guion de N palabras. La otra mitad de la inversa."""
    cuenta = max(0, int(palabras or 0))
    cadencia, _origen = cadencia_de(idioma, velocidad, voz)
    por_bloque = max(5, int(palabras_por_bloque or 30))
    bloques = max(1, int(round(cuenta / por_bloque)))
    aire = max(0.0, float(hueco_minimo or 0.0) - PAUSA_ENTRE_BLOQUES) * max(0, bloques - 1)
    return round(cuenta / max(0.05, cadencia) + aire, 2)


# ------------------------------------------------------------------ medida

def medida_de_toma(palabras, duracion_s, silencio_anadido_s=0.0):
    """La cadencia REAL que ha salido de una toma. -> palabras/s, o None.

    Se descuenta el aire insertado: lo que caracteriza a una voz es lo que tarda
    en decir las palabras, y el aire lo pone el mando de ritmo, que es otra cosa
    y se estima aparte.
    """
    try:
        cuenta = int(palabras)
        bruta = float(duracion_s) - float(silencio_anadido_s or 0.0)
    except (TypeError, ValueError):
        return None
    if cuenta <= 0 or bruta <= 0:
        return None
    return round(cuenta / bruta, 3)
