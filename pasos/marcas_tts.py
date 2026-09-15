"""
Anotaciones de voz: lo que el guion le dice al TTS y que no se locuta.

Para que
--------
Un guion bien puntuado ya se lee con un ritmo razonable, pero la puntuacion no
distingue entre dos puntos que significan cosas distintas. El punto que cierra
el gancho y el punto que separa dos frases del mismo parrafo se escriben igual,
y Cartesia los locuta igual: media pausa. Resultado, el gancho y la entrada del
documental salen pegados y suena a que el locutor no se ha enterado de que ha
empezado otra cosa.

Aqui vive el vocabulario de etiquetas SSML que el redactor puede meter en el
texto, y las dos operaciones que hacen falta para que ese texto conviva con el
resto del Estudio:

    limpiar(texto)   el texto tal y como se OYE, sin etiquetas. Es el que cuenta
                     palabras, el que se compara con el material de partida, el
                     que se revisa de tildes y, sobre todo, el que reparte las
                     marcas de palabra entre bloques.
    sanear(texto)    el texto tal y como se MANDA a Cartesia: solo etiquetas del
                     vocabulario, en rango, y con el estado devuelto a su sitio.

Lo que se midio contra la API real (sonic-3.5, language=es)
-----------------------------------------------------------
Nada de esto esta en la documentacion de Cartesia y de todo ello depende el
diseno de este modulo:

1. Las etiquetas de PAUSA Y DE VOZ (break, speed, volume, emotion) no salen en
   word_timestamps: Cartesia devuelve las palabras habladas y nada mas. El
   montaje entero se sincroniza con esas marcas, asi que esto es lo que hace
   viable la idea. La excepcion es <spell>, y por eso tiene su punto 6.

2. Una etiqueta DESCONOCIDA se locuta en voz alta. Con `<pausa larga/>` en el
   transcript, las marcas devueltas fueron: Hola. | <pausa | larga/> | Adios.
   El locutor lo dice. Por eso sanear() no avisa de lo que no reconoce: lo
   BORRA. Un aviso que nadie lee acaba en un video diciendo "menor que pausa".

3. <break> funciona en castellano y es ADITIVO sobre la pausa natural, no
   absoluto. Mismo texto, mismo corte de frase: 0,52 s sin etiqueta y 1,55 s
   con `<break time="1200ms"/>`. La etiqueta anade ~0,8x lo que pide.

4. <speed> y <volume> PERSISTEN HASTA EL FINAL DEL TRANSCRIPT. Medido en
   segundos por palabra: 0,295 sin etiqueta, 0,446 tras `<speed ratio="0.7"/>`,
   y 0,480 en la frase siguiente, que no llevaba etiqueta ninguna. Con volumen
   igual: RMS 2476 / 1443 / 1646. Esto es lo mas peligroso de todo el asunto,
   porque el sintoma aparece lejos de la causa: una etiqueta suelta en el bloque
   B012 deja los ocho minutos siguientes del video lentos, y al mirar el guion
   de ese tramo no hay nada raro que ver. Por eso cada bloque se CIERRA solo
   (ver "El bloque se devuelve como estaba").

5. `<speed ratio="1"/>` restaura de verdad: 0,276 / 0,411 / 0,284. El cierre
   automatico funciona, y el entero vale, no hace falta "1.0".

6. <spell> SI sale en word_timestamps, y es la unica que lo hace. Con «Uno
   <spell>ABC</spell> dos.» las marcas vuelven ['Uno', '<spell>ABC</spell>',
   'dos.'], en castellano y en ingles. Por eso texto_de_marca() le quita la
   etiqueta en vez de tirar el token: tirarlo dejaria el bloque con una palabra
   menos de las que espera el reparto, y de ahi en adelante cada corte de plano
   del video caeria una palabra antes.

7. <spell> es la unica forma que deletrea en los DOS idiomas, y deletrea con el
   nombre de las letras del idioma. Medido aislado, con «ING»:

       castellano   pelada 0,72 s   <spell> 1,76 s   «I N G» 0,72 s   «I.N.G.» 0,88 s
       ingles       pelada 0,96 s   <spell> 1,28 s   «I N G» 1,20 s   «I.N.G.» 1,04 s

   O sea que separar las letras a mano deletrea en ingles y NO en castellano
   -- ahi da exactamente lo mismo que la sigla pelada--, que es justo la clase
   de detalle que no se puede adivinar. Y el castellano tarda mas que el ingles
   en las mismas tres letras, que es lo que se espera si esta diciendo «i, ene,
   ge» y no «ai, en, yi».

El bloque se devuelve como estaba
---------------------------------
Un bloque que abre velocidad o volumen los cierra antes de acabar, y si el
redactor no lo cierra lo cierra sanear(). No es manias de limpieza: los bloques
son la unidad que se reescribe sola desde la revision de audio, la que se edita
a mano en la interfaz y la que se traduce a otros idiomas conservando el id. Si
B010 dejase la velocidad abierta para que B011 la aproveche, tocar B010 cambiaria
como suena B011 sin que nadie haya tocado B011. Cada bloque suena igual venga de
donde venga el anterior.

Donde puede ir cada etiqueta
----------------------------
<break> no cambia la voz: solo mete silencio. Puede ir a mitad de frase, que es
justo donde sirve para el suspense. Las demas cambian COMO suena el locutor, y
un cambio a mitad de frase se oye como si hubiera entrado otra persona; esas
solo se admiten en frontera de frase. Lo que llegue mal colocado se quita.

Las etiquetas van en ingles aunque el guion no
----------------------------------------------
`break`, `time`, `ratio`, `emotion` y los valores de emocion son identificadores
del formato, no palabras del guion: son los mismos en la version castellana y en
la inglesa. Lo unico que se traduce es el texto de alrededor.
"""
import re

# ------------------------------------------------------------------ vocabulario

#: Silencio, en milisegundos, que puede pedir una etiqueta <break>. Por abajo,
#: menos de 100 ms no se distingue de la pausa que ya deja la coma. Por arriba,
#: 2,5 s en una narracion en off ya no es una pausa: es un fallo de reproduccion.
BREAK_MIN_MS = 100
BREAK_MAX_MS = 2500

#: Rangos que acepta Cartesia en sonic-3/3.5. Fuera de ellos la peticion no
#: falla: se ignora en silencio, que es peor.
SPEED_MIN, SPEED_MAX = 0.6, 1.5
VOLUMEN_MIN, VOLUMEN_MAX = 0.5, 2.0

#: Y lo que tiene sentido en una narracion documental, que es mucho menos. A
#: 0,6 el locutor arrastra las palabras y a 1,5 atropella; ninguno de los dos
#: extremos es una decision de guion, son un error de tecleo.
SPEED_SUAVE_MIN, SPEED_SUAVE_MAX = 0.85, 1.15
VOLUMEN_SUAVE_MIN, VOLUMEN_SUAVE_MAX = 0.8, 1.15

#: Las seis que la documentacion de Cartesia da como primarias, que son las que
#: responden bien. De las 56 que admite, el resto son matices que en una toma
#: continua no se distinguen y si arriesgan el efecto de cambio de locutor.
EMOCIONES = ("neutral", "calm", "angry", "content", "sad", "scared")

#: Valor neutro al que se devuelve un bloque que abrio velocidad o volumen.
NEUTRO = "1"

# ---------------------------------------------------------------- reconocedores

_BREAK = re.compile(r'<break\s+time="(\d+(?:\.\d+)?)\s*(ms|s)"\s*/>', re.I)
_RATIO = re.compile(r'<(speed|volume)\s+ratio="(-?\d+(?:\.\d+)?)"\s*/>', re.I)
_EMOCION = re.compile(r'<emotion\s+value="([A-Za-z]+)"\s*/>', re.I)
_SPELL = re.compile(r'<spell>\s*([^<>]+?)\s*</spell>', re.I)

#: QUE SE DELETREA DE VERDAD, y por que no se le puede dejar al redactor.
#:
#: `<spell>` existe para las siglas que se dicen letra a letra. El problema
#: medido no es que el redactor no sepa cuales son: es que TODA palabra en
#: mayusculas se le parece. En un video sobre malware salieron deletreados
#: RACCOON, LUMMA, ALEXHOST y MEGA -- que son NOMBRES y se leen -- mientras
#: VIDAR y STEALER, a su lado y en la misma lista, salieron leidos. Sin patron,
#: y ademas caro: deletrear una palabra de ocho letras alarga el plano tanto que
#: lo que serian dos o tres planos se convierten en cinco o seis.
#:
#: Asi que la decision deja de ser del redactor y pasa a ser del motor. Es una
#: prueba de FORMA, no una lista de marcas, porque una lista de marcas envejece
#: y ademas solo sirve para un tema: aqui se mira si el token se puede
#: PRONUNCIAR como una palabra. Lo que se puede pronunciar, se lee.
#:
#:     sin vocal           DNS, SQL, GCHQ, HTML  -> se deletrea, no hay otra
#:     una o dos letras    IP, AI, PC            -> se deletrea
#:     tres letras         FBI, MFA, API, CIA    -> se deletrea, salvo C-V-C
#:                         SIM, PIN, RAM, LAN    -> C-V-C: es una silaba, se lee
#:     cuatro letras       NCSC, HTML, ICBM      -> menos de dos grupos de vocal
#:                         NASA, OTAN, MEGA      -> dos grupos: se lee
#:     cinco o mas         LUMMA, VIDAR, STEALC  -> se lee
#:     mas de seis         SMOKELOADER           -> ni de lejos una sigla
#:
#: La regla es abstracta a proposito: vale igual para un video de malware que
#: para uno de historia o de cocina, y no hay ninguna marca escrita en el codigo.
LARGO_MAXIMO_SIGLA = 6
_VOCALES = "AEIOUY"


def _grupos_de_vocal(letras):
    """Cuantos nucleos silabicos tiene: «NASA» dos, «HTML» ninguno."""
    grupos, dentro = 0, False
    for letra in letras:
        if letra in _VOCALES:
            if not dentro:
                grupos += 1
            dentro = True
        else:
            dentro = False
    return grupos


def _pelado(token):
    """El token sin la puntuacion que lleve pegada. «MFA.» -> «MFA»."""
    return re.sub(r"^[^0-9A-Za-z]+|[^0-9A-Za-z]+$", "", str(token or ""))


def es_inicialismo(token):
    """Si esto se DELETREA de verdad, o es una palabra que se lee. Ver arriba.

    Se decide por la FORMA del token y nada mas: ni listas de marcas ni idioma.
    Un token que no venga entero en mayusculas no es una sigla -- «AlexHost» y
    «Mega» son nombres propios, se escriban como se escriban --.
    """
    limpio = _pelado(token)
    if not limpio or len(limpio) > LARGO_MAXIMO_SIGLA:
        return False
    letras = [c for c in limpio if c.isalpha()]
    if not letras or any(c.islower() for c in letras):
        return False
    if len(limpio) == 1:
        return True
    if not _grupos_de_vocal(letras):
        return True                     # sin vocal no hay forma de leerlo
    if len(limpio) >= 5:
        return False                    # LUMMA, VIDAR, SWIFT: son palabras
    if len(limpio) == 4:
        return _grupos_de_vocal(letras) < 2
    if len(limpio) == 3:
        # C-V-C es una silaba y se lee (SIM, PIN, RAM); cualquier otra forma
        # (FBI, CIA, MFA, API, USB) se deletrea. Un digito cuenta como consonante.
        forma = "".join("V" if c in _VOCALES else "C" for c in limpio.upper())
        return forma != "CVC"
    return True                         # dos letras: IP, AI, PC


def _deletreable(pieza):
    """El contenido de un <spell> partido en tokens, con el veredicto de cada uno.

    -> [(token, se_deletrea)]. Un <spell> con varias palabras dentro deletrea
    TODAS, espacios incluidos: medido, «<spell>AT and T</spell>» se oye «AT,
    A-N-D-T». Asi que se parte en uno por token y cada uno se juzga solo.
    """
    return [(token, es_inicialismo(token)) for token in str(pieza or "").split()]

#: Cualquier cosa con forma de etiqueta, valida o no. Se usa para BORRAR lo que
#: no se reconozca, porque lo que no se reconoce se locuta (leccion 2).
_ALGO_ASI = re.compile(r'<[^<>]*>')

#: Cuantos silencios por bloque son demasiados. La voz se graba en UNA toma
#: continua a proposito: frase a frase cada linea arranca en
#: frio y el corte se oye. Un <break> parte la generacion, asi que un guion con
#: un silencio en cada bloque desanda esa decision sin decirlo y devuelve el
#: sonido de lista leida que se arreglo en su dia.
DENSIDAD_MAXIMA = 0.5

#: Los cierres de frase tras los que se admite un cambio de voz. Los puntos
#: suspensivos y los dos puntos cuentan: detras de ellos el locutor ya para.
_FIN_DE_FRASE = re.compile(r'(?:[.!?:;]|\.\.\.|…)["»\')\]]?\s*$')


def _numero(texto, por_defecto=1.0):
    try:
        return float(texto)
    except (TypeError, ValueError):
        return por_defecto


def _acotar(valor, minimo, maximo):
    return max(minimo, min(maximo, valor))


def _formatear(valor):
    """1.0 -> '1'; 0.90 -> '0.9'. Cartesia acepta el entero y se lee mejor."""
    if abs(valor - round(valor)) < 1e-9:
        return str(int(round(valor)))
    return f"{valor:.2f}".rstrip("0").rstrip(".")


# ------------------------------------------------------------------- limpiar

def limpiar(texto):
    """El texto tal y como se OYE: sin etiquetas y sin dobles espacios.

    Este es el texto con el que trabaja TODO lo que no sea la llamada a
    Cartesia. En particular el reparto de marcas de palabra entre bloques, que
    empareja lo que el guion dice con lo que Cartesia devolvio: como Cartesia no
    devuelve las etiquetas, dejarlas aqui meteria tokens que no existen y cada
    uno se comeria una palabra real, desplazando todos los cortes de plano
    siguientes.
    """
    plano = str(texto or "")
    plano = _SPELL.sub(lambda m: m.group(1), plano)
    plano = _ALGO_ASI.sub(" ", plano)
    # la etiqueta se comia el espacio que la separaba de la palabra siguiente
    return " ".join(plano.split())


def hay_marcas(texto):
    """True si el texto lleva alguna anotacion de voz."""
    return bool(_ALGO_ASI.search(str(texto or "")))


def contar_palabras(texto):
    """Palabras que se locutan, sin contar las etiquetas."""
    return len(limpiar(texto).split())


# -------------------------------------------------------------------- sanear

def trocear(texto):
    """[(clase, pieza)] recorriendo el texto una vez.

    clase es 'texto', 'break', 'speed', 'volume', 'emotion', 'spell' o 'basura'.
    """
    piezas = []
    posicion = 0
    for encontrado in _ALGO_ASI.finditer(texto):
        # <spell> se consume entero desde su apertura, asi que el cierre que
        # encuentre el iterador cae detras de 'posicion' y ya esta contado
        if encontrado.start() < posicion:
            continue
        if encontrado.start() > posicion:
            piezas.append(("texto", texto[posicion:encontrado.start()]))
        posicion = encontrado.end()
        cruda = encontrado.group(0)

        salto = _BREAK.fullmatch(cruda)
        if salto:
            ms = _numero(salto.group(1), 0.0)
            if salto.group(2).lower() == "s":
                ms *= 1000.0
            piezas.append(("break", ms))
            continue

        ratio = _RATIO.fullmatch(cruda)
        if ratio:
            piezas.append((ratio.group(1).lower(), _numero(ratio.group(2))))
            continue

        emocion = _EMOCION.fullmatch(cruda)
        if emocion:
            piezas.append(("emotion", emocion.group(1).lower()))
            continue

        # <spell> es el unico par de apertura y cierre: se busca completo desde
        # la apertura, porque _ALGO_ASI lo ve como dos etiquetas sueltas
        if cruda.lower().startswith("<spell"):
            entero = _SPELL.match(texto, encontrado.start())
            if entero:
                piezas.append(("spell", entero.group(1)))
                posicion = entero.end()
                continue

        piezas.append(("basura", cruda))
    if posicion < len(texto):
        piezas.append(("texto", texto[posicion:]))
    return piezas


def sanear(texto, avisos=None):
    """El texto tal y como se MANDA a Cartesia.

    Deja solo etiquetas del vocabulario, con los valores dentro de rango, sin
    encadenar dos silencios seguidos, sin cambios de voz a mitad de frase y con
    la velocidad y el volumen devueltos a neutro antes de terminar. Si 'avisos'
    es una lista, se le anade lo que se haya tenido que corregir.

    Es idempotente: sanear(sanear(x)) == sanear(x).
    """
    apunta = avisos.append if isinstance(avisos, list) else (lambda _: None)
    crudo = str(texto or "")
    if not crudo.strip():
        return ""

    salida = []
    dicho = ""           # texto locutado acumulado, para saber si toca frontera
    ultimo_break = None  # indice en 'salida' del ultimo silencio, si va seguido
    abiertos = {}        # 'speed'/'volume' -> valor distinto de neutro

    def en_frontera():
        """True si aqui cabe un cambio de voz sin partir una frase."""
        return not dicho.strip() or bool(_FIN_DE_FRASE.search(dicho))

    for clase, pieza in trocear(crudo):
        if clase == "texto":
            if pieza.strip():
                ultimo_break = None
            dicho += pieza
            salida.append(pieza)

        elif clase == "spell":
            # <spell> deletrea TODO lo que lleva dentro, espacios incluidos.
            # Medido: «<spell>AT and T</spell>» se oye «AT, A-N-D-T» -- deletrea
            # la palabra 'and'. Y ademas rompe el karaoke: en el texto son tres
            # tokens y en las marcas uno, asi que de ahi en adelante la palabra
            # que se ilumina no es la que suena.
            #
            # Se parte en uno por token y solo se deletrea lo que parece sigla:
            # mayusculas o cosa corta. Lo demas sale como palabra normal, que es
            # lo que es.
            trozos = []
            for token, deletrea in _deletreable(pieza):
                if deletrea:
                    trozos.append(f"<spell>{token}</spell>")
                else:
                    trozos.append(token)
                    apunta(f"«{token}» estaba dentro de <spell> y no se deletrea: "
                           f"se puede pronunciar como palabra, asi que se lee. "
                           f"Deletrear un nombre propio suena raro y ademas "
                           f"alarga el plano")
            dicho += " " + str(pieza)
            ultimo_break = None
            salida.append(" ".join(trozos))

        elif clase == "break":
            ms = pieza
            if ms < BREAK_MIN_MS:
                apunta(f"silencio de {int(ms)} ms: por debajo de {BREAK_MIN_MS} ms "
                       f"no se distingue de la pausa que ya deja la puntuacion")
                continue
            if ms > BREAK_MAX_MS:
                apunta(f"silencio de {int(ms)} ms recortado a {BREAK_MAX_MS} ms: "
                       f"mas que eso en una narracion suena a fallo de reproduccion")
                ms = BREAK_MAX_MS
            if ultimo_break is not None:
                # la documentacion de Cartesia avisa de que dos silencios
                # seguidos pueden hacerle alucinar: se funden en uno
                previo = _BREAK.fullmatch(salida[ultimo_break])
                juntos = min(BREAK_MAX_MS, _numero(previo.group(1)) + ms)
                salida[ultimo_break] = f'<break time="{int(juntos)}ms"/>'
                apunta("dos silencios seguidos fundidos en uno")
                continue
            salida.append(f'<break time="{int(ms)}ms"/>')
            ultimo_break = len(salida) - 1

        elif clase in ("speed", "volume"):
            if not en_frontera():
                apunta(f"cambio de {clase} a mitad de frase, quitado: se oye como "
                       f"si entrase otro locutor")
                continue
            minimo, maximo = ((SPEED_MIN, SPEED_MAX) if clase == "speed"
                              else (VOLUMEN_MIN, VOLUMEN_MAX))
            valor = _acotar(pieza, minimo, maximo)
            if abs(valor - pieza) > 1e-9:
                apunta(f"{clase} {_formatear(pieza)} fuera del rango que acepta "
                       f"Cartesia, ajustado a {_formatear(valor)}")
            texto_valor = _formatear(valor)
            if abs(valor - 1.0) < 1e-9:
                abiertos.pop(clase, None)
            else:
                abiertos[clase] = texto_valor
            salida.append(f'<{clase} ratio="{texto_valor}"/>')
            ultimo_break = None

        elif clase == "emotion":
            if not en_frontera():
                apunta("cambio de emocion a mitad de frase, quitado: se oye como "
                       "si entrase otro locutor")
                continue
            if pieza not in EMOCIONES:
                apunta(f"emocion {pieza!r} desconocida, quitada. Validas: "
                       + ", ".join(EMOCIONES))
                continue
            salida.append(f'<emotion value="{pieza}"/>')
            ultimo_break = None

        else:  # basura
            # No se avisa y ya: se BORRA. Una etiqueta que Cartesia no reconoce
            # la LOCUTA, y un video que dice "menor que pausa larga" es mucho
            # peor que un guion al que le falta un silencio.
            apunta(f"anotacion {pieza.strip()!r} fuera del vocabulario, quitada "
                   f"antes de que el locutor la lea en voz alta")

    final = "".join(salida).strip()
    # Un silencio al final del bloque SI vale, y es el caso principal: la pausa
    # entre el gancho y la entrada del documental es justo eso. No se toca.
    #
    # No choca con el aire que mete la pista despues de sintetizar
    # (voz.espaciar): aquel ensancha hasta un MINIMO midiendo la pausa real, asi
    # que si el <break> ya la dejo suficientemente ancha, no anade nada. Lo que
    # aporta el <break> y no puede aportar el silencio de la pista es la
    # PROSODIA: parte la generacion, y por eso el bloque anterior cierra la
    # entonacion y el siguiente arranca de cero. Un segundo de silencio metido
    # en mitad de una entonacion continua no suena a pausa, suena a corte.

    # un bloque que solo tiene etiquetas no es un bloque: no se locuta nada, y
    # dejar el silencio suelto seria colgarlo del bloque de al lado
    if not limpiar(final):
        return ""

    # lo que este bloque abrio, este bloque lo cierra
    for clase in ("speed", "volume"):
        if clase in abiertos:
            apunta(f"el bloque dejaba {clase} en {abiertos[clase]} al terminar y "
                   f"eso sigue puesto hasta el final del video: se cierra solo")
            final += f'<{clase} ratio="{NEUTRO}"/>'
    return final


# -------------------------------------------------------------------- revisar

def revisar(texto):
    """Lo que habria que decirle a una persona sobre las anotaciones del texto.

    sanear() ya deja el texto utilizable; esto es para el aviso que sube a la
    interfaz, que es donde se ve si el redactor ha entendido el vocabulario.
    """
    problemas = []
    sanear(texto, problemas)
    return problemas


def silencio_final(texto):
    """Milisegundos de silencio que quedan detras de la ultima palabra."""
    total = 0
    for clase, pieza in reversed(trocear(str(texto or ""))):
        if clase == "break":
            total += pieza
        elif clase == "spell" or (clase == "texto" and str(pieza).strip()):
            break
    return total


def pausa_al_final(texto, ms):
    """El bloque termina con al menos 'ms' de silencio, cueste lo que cueste.

    Existe porque hay una pausa que no puede depender de que el redactor se
    acuerde: la del gancho a la entrada del documental. El gancho esta ESCRITO
    para que despues haya aire -- es una frase que remata y se queda colgando --
    y si el aire no esta, el bloque siguiente le pisa el final y el recurso no
    funciona. Las demas pausas son criterio; esta es estructura.

    Si ya hay silencio suficiente no se toca nada. Si hay pero se queda corto,
    se sustituye en vez de sumarle otro: dos silencios casi pegados es de lo
    poco que la documentacion de Cartesia desaconseja explicitamente.
    """
    crudo = str(texto or "")
    if ms <= 0 or not limpiar(crudo):
        return crudo
    if silencio_final(crudo) >= ms:
        return crudo
    # se reconstruye sin los silencios de cola y se pone uno solo
    piezas, cola = trocear(crudo), []
    while piezas and piezas[-1][0] in ("break", "speed", "volume", "emotion"):
        clase, pieza = piezas.pop()
        if clase != "break":
            cola.insert(0, (clase, pieza))
    rehecho = _rearmar(piezas) + f'<break time="{int(ms)}ms"/>' + _rearmar(cola)
    return sanear(rehecho)


def _rearmar(piezas):
    """Vuelve a escribir el texto a partir de [(clase, pieza)] de trocear()."""
    trozos = []
    for clase, pieza in piezas:
        if clase == "texto" or clase == "basura":
            trozos.append(str(pieza))
        elif clase == "spell":
            trozos.append(f"<spell>{pieza}</spell>")
        elif clase == "break":
            trozos.append(f'<break time="{int(pieza)}ms"/>')
        elif clase == "emotion":
            trozos.append(f'<emotion value="{pieza}"/>')
        else:
            trozos.append(f'<{clase} ratio="{_formatear(pieza)}"/>')
    return "".join(trozos)


def revisar_conjunto(bloques):
    """Problemas que solo se ven mirando el guion ENTERO, no bloque a bloque.

    Uno solo, pero es el que puede estropear la toma: pasarse de silencios. Cada
    <break> parte la generacion, asi que muchos convierten la toma continua en
    una lectura frase a frase, que es exactamente lo que no se quiere.
    """
    textos = [(b.get("texto") if isinstance(b, dict) else b) for b in bloques or []]
    textos = [str(t or "") for t in textos]
    if not textos:
        return []
    silencios = sum(1 for t in textos for clase, _ in trocear(t) if clase == "break")
    tope = int(len(textos) * DENSIDAD_MAXIMA)
    if silencios <= max(1, tope):
        return []
    return [f"{silencios} silencios para {len(textos)} bloques. Cada <break> parte "
            f"la generacion, asi que a esa densidad la toma deja de sonar continua "
            f"y vuelve a sonar a lista leida. Deja como mucho {max(1, tope)}, en "
            f"los sitios donde el relato cambia de marcha de verdad"]


def resumen(bloques):
    """Cuantas anotaciones de cada clase hay en una lista de bloques."""
    cuenta = {"break": 0, "speed": 0, "volume": 0, "emotion": 0, "spell": 0}
    for bloque in bloques or []:
        texto = bloque.get("texto") if isinstance(bloque, dict) else bloque
        for clase, _ in trocear(str(texto or "")):
            if clase in cuenta:
                cuenta[clase] += 1
    return cuenta


# ---------------------------------------------------- filtro de marcas de vuelta

def texto_de_marca(palabra):
    """La palabra hablada que hay detras de una marca, o None si no hay ninguna.

    Cartesia devuelve casi todas las etiquetas fuera de word_timestamps... pero
    NO <spell>. Medido en los dos idiomas: con «Uno <spell>ABC</spell> dos.» las
    marcas vuelven ['Uno', '<spell>ABC</spell>', 'dos.'], con la etiqueta entera
    dentro del token.

    Y eso importa mucho mas de lo que parece. El reparto empareja lo que el
    guion dice --donde limpiar() ya dejo 'ABC'-- con lo que Cartesia devolvio.
    Si aqui se TIRA el token por llevar angulos, esa palabra desaparece de las
    marcas mientras el reparto la sigue esperando, y a partir de ahi todo el
    bloque va corrido: cada corte de plano del video cae una palabra antes.

    Asi que no se tira: se le quita la etiqueta y se queda la palabra. Lo que
    si se tira es cualquier otra cosa con angulos, que solo puede ser una
    etiqueta que no deberia estar ahi.
    """
    trozo = str(palabra or "")
    if "<" not in trozo and ">" not in trozo:
        return trozo
    # <spell>ABC</spell> -> ABC, conservando lo que lleve pegado (una coma, un
    # punto): el emparejador compara normalizado, pero la marca se guarda tal cual
    limpio = _SPELL.sub(lambda m: m.group(1), trozo)
    if "<" in limpio or ">" in limpio:
        return None
    return limpio


def es_token_de_etiqueta(palabra):
    """True si esta marca no lleva ninguna palabra hablada dentro."""
    return texto_de_marca(palabra) is None


# ------------------------------------------------------- instrucciones al modelo

#: Repertorio en terminos de GUION, no de milisegundos. Un redactor sabe cuando
#: acaba el gancho; no sabe si eso son 600 u 800 ms.
PAUSAS = (
    ("del gancho a la entrada del documental", 900),
    ("cambio de capitulo o salto grande de tiempo o de lugar", 700),
    ("justo antes de una revelacion, una cifra que pesa o un giro", 400),
    ("suspense dentro de una frase, detras de una coma o de puntos suspensivos", 250),
)


def instrucciones(con_emocion=True):
    """Bloque de reglas de anotacion para el prompt del guion."""
    lineas = [
        "== ANOTACIONES DE VOZ (van dentro del texto de los bloques) ==",
        "El guion no se lee: lo locuta Cartesia. La puntuacion normal ya da el "
        "ritmo basico y es la primera herramienta: escribe frases bien "
        "puntuadas ANTES de pensar en ninguna etiqueta. Las etiquetas son para "
        "lo que la puntuacion no distingue, que es cuando el relato cambia de "
        "marcha.",
        "",
        "SILENCIO. `<break time=\"700ms\"/>` mete una pausa donde va. Es la "
        "etiqueta principal y casi siempre la unica que hace falta. Cuanto:",
    ]
    lineas.extend(f"  - {motivo}: <break time=\"{ms}ms\"/>" for motivo, ms in PAUSAS)
    lineas.extend([
        f"  El maximo es {BREAK_MAX_MS} ms. No pongas dos seguidos.",
        "",
        "MEDIDA. Un silencio cada dos o tres bloques como mucho, y solo donde el "
        "relato cambia de marcha de verdad. Un guion con una pausa en cada "
        "bloque no suena solemne: suena a que el locutor duda.",
        "",
        f"VELOCIDAD. `<speed ratio=\"0.92\"/>` frena y `<speed ratio=\"1.08\"/>` "
        f"acelera; util para rematar despacio una conclusion o para pasar de "
        f"puntillas por una enumeracion. Quedate entre {SPEED_SUAVE_MIN} y "
        f"{SPEED_SUAVE_MAX}: fuera de ahi ya no es una intencion, es un efecto.",
        "",
        f"VOLUMEN. `<volume ratio=\"0.9\"/>` baja la voz, para un inciso o una "
        f"confidencia. Entre {VOLUMEN_SUAVE_MIN} y {VOLUMEN_SUAVE_MAX}.",
    ])
    if con_emocion:
        lineas.extend([
            "",
            f"EMOCION. `<emotion value=\"sad\"/>` inclina el tono. Validas: "
            f"{', '.join(EMOCIONES)}. Solo funciona si la emocion concuerda con lo "
            f"que el bloque DICE, asi que no la pongas a ver que pasa. Como mucho "
            f"en un giro de capitulo, no en cada bloque.",
        ])
    lineas.extend([
        "",
        "DONDE PUEDEN IR. `<break>` puede ir a mitad de frase, que es donde sirve "
        "para el suspense. Las que cambian COMO suena la voz "
        "(speed, volume" + (", emotion" if con_emocion else "") + ") solo al "
        "empezar un bloque o justo detras de un punto: a mitad de frase parece "
        "que ha entrado otro locutor.",
        "",
        "CADA BLOQUE SE CIERRA SOLO. speed y volume siguen puestos hasta el final "
        "del video, no hasta el final de la frase. Si un bloque abre uno, tiene "
        "que devolverlo a `ratio=\"1\"` antes de acabar. Los bloques se reescriben "
        "y se reordenan por separado, asi que ninguno puede depender de lo que "
        "dejo puesto el anterior.",
        "",
        "EN INGLES. Las etiquetas y sus valores son del formato, no del guion: "
        "van igual escribas en castellano, en ingles o en lo que sea. Solo se "
        "traduce el texto de alrededor.",
        "",
        "NADA MAS. Estas son las unicas etiquetas que existen. Cualquier otra "
        "cosa entre < y > la LOCUTA el sintetizador en voz alta, asi que no te "
        "inventes ninguna. Y no cuentan como palabras del guion: la horquilla se "
        "mide sobre lo que se oye.",
    ])
    return "\n".join(lineas)
