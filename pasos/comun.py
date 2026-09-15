"""
Utilidades compartidas por los pasos del pipeline.

Aqui vive solo lo que los tres pasos necesitan por igual: cargar un motor de
C:\\IA\\motores, dejar limpia la carpeta de trabajo y leer la salida de un paso
anterior. Nada de logica de negocio.
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import unicodedata

RAIZ_MOTORES = os.environ.get("ESTUDIO_MOTORES") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "motores")

#: {ruta: (modulo, mtime con el que se cargo)}
_MOTORES = {}


def _motores_congelados():
    """True mientras un paso este corriendo dentro de `medios.trabajo_en_curso`.

    Se lee del modulo sintetico que `medios` deja en sys.modules en vez de
    importar `medios`: comun es la capa de abajo -- la importan todos los pasos y
    no importa a nadie -- y darle la vuelta a esa flecha por un contador no sale
    a cuenta. Pero tiene que ser EL MISMO contador y no uno propio: con dos,
    entrar en un paso congelaria los motores de imagen y dejaria sueltos los de
    voz, que es justo la mitad que esto viene a proteger.
    """
    compartido = sys.modules.get("_medios_compartido")
    en_marcha = getattr(compartido, "en_marcha", None)
    return bool(en_marcha) and en_marcha[0] > 0


def cargar_motor(paquete, fichero=None):
    """Importa un motor de C:\\IA\\motores por ruta, y lo RECARGA si ha cambiado.

    Se carga por ruta en vez de con sys.path porque los motores tienen nombres
    genericos ("ingesta", "voz") que chocarian con cualquier otro modulo.

    Y se recarga por lo mismo que en `medios.motor`, que es donde esta contado
    entero: los pasos corren en un HILO del servicio, asi que un motor cacheado
    para siempre vive lo que viva el proceso. Con el servicio levantado desde por
    la manana, arreglar un motor no servia de nada -- se seguia ejecutando la
    copia en memoria, se volvia a ver el mismo fallo exacto y se depuraba codigo
    que no se estaba ejecutando. Aquel arreglo llego a los motores de imagen,
    corte y el render y NO a estos: ingesta, voz y revision seguian congelados.

    La recarga es la excepcion: solo si cambia el mtime, y nunca con un paso
    dentro (ver `_motores_congelados`). Quien guarde el modulo en una variable de
    su propio modulo se queda con la copia vieja para siempre; por eso `p4_voz`
    no lo guarda.
    """
    nombre_fichero = fichero or f"{paquete}.py"
    ruta = os.path.join(RAIZ_MOTORES, paquete, nombre_fichero)
    guardado = _MOTORES.get(ruta)
    if guardado is not None:
        modulo, sello = guardado
        if _motores_congelados():
            return modulo
        try:
            if os.path.getmtime(ruta) == sello:
                return modulo
        except OSError:
            return modulo
    if not os.path.exists(ruta):
        raise RuntimeError(f"falta el motor {paquete}: no existe {ruta}")
    alias = f"motor_{paquete}"
    spec = importlib.util.spec_from_file_location(alias, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[alias] = modulo
    spec.loader.exec_module(modulo)
    try:
        sello = os.path.getmtime(ruta)
    except OSError:
        sello = 0
    if guardado is not None:
        print(f"[comun] motor recargado: {paquete}/{nombre_fichero}", flush=True)
    _MOTORES[ruta] = (modulo, sello)
    return modulo


def llamar_motor(funcion, *args, **kwargs):
    """Ejecuta una funcion de motor convirtiendo SystemExit en error normal.

    Los motores estan escritos como CLI y abortan con SystemExit; dentro de un
    hilo de GestorTrabajos eso no lo captura nadie y el paso se quedaria colgado
    en 'ejecutando' sin explicacion.
    """
    try:
        return funcion(*args, **kwargs)
    except SystemExit as fallo:
        raise RuntimeError(str(fallo) or "el motor aborto sin mensaje") from fallo


def preparar_trabajo(proyecto, paso_id):
    """Devuelve la carpeta de trabajo del paso, vacia.

    Se borra lo que hubiera de una ejecucion fallida anterior: varios motores
    buscan ficheros por extension dentro de la carpeta y encontrarian restos.
    """
    destino = proyecto.ruta_trabajo(paso_id, crear=False)
    if os.path.isdir(destino):
        shutil.rmtree(destino)
    return proyecto.ruta_trabajo(paso_id, crear=True)


def carpeta_activa(proyecto, paso_id):
    """Carpeta de la version activa de un paso, o None si nunca se completo."""
    if proyecto.version_activa(paso_id) is None:
        return None
    ruta = proyecto.ruta_paso(paso_id)
    return ruta if os.path.isdir(ruta) else None


def leer_salida(proyecto, paso_id, nombre, obligatorio=True):
    """Lee un JSON que dejo un paso anterior en su version activa."""
    carpeta = carpeta_activa(proyecto, paso_id)
    ruta = os.path.join(carpeta, nombre) if carpeta else None
    if not ruta or not os.path.exists(ruta):
        if obligatorio:
            raise RuntimeError(
                f"el paso '{paso_id}' no ha dejado {nombre}: ejecutalo antes")
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as fallo:
        raise RuntimeError(f"{ruta} no es un JSON valido: {fallo}") from fallo


def escribir_json(ruta, datos):
    """Guarda un JSON legible en UTF-8, creando la carpeta si hace falta."""
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(datos, fh, ensure_ascii=False, indent=2)


def escribir_texto(ruta, texto):
    """Guarda texto plano en UTF-8, creando la carpeta si hace falta."""
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto)


def tokens_de_cli(sobre):
    """Tokens que declara el CLI de Claude en su sobre JSON.

    El sobre trae ademas 'total_cost_usd', que aqui no se usa a proposito: el
    CLI va contra la suscripcion, no contra un contador con precio por llamada,
    y anotar ese importe lo pondria a competir con un TOTAL que no lo incluye.
    """
    sobre = sobre if isinstance(sobre, dict) else {}
    uso = sobre.get("usage") if isinstance(sobre.get("usage"), dict) else {}
    return {
        "entrada": int(uso.get("input_tokens") or 0),
        "salida": int(uso.get("output_tokens") or 0),
        "cache": (int(uso.get("cache_creation_input_tokens") or 0)
                  + int(uso.get("cache_read_input_tokens") or 0)),
    }


def contar_palabras(texto):
    """Palabras de un texto, contadas como las cuenta un locutor: separadas por espacios."""
    return len(str(texto or "").split())


# --------------------------------------------------------------------- tildes
#
# El guion no es texto para leer: es texto para LOCUTAR. Un sintetizador de voz
# lee lo que hay escrito, asi que una tilde que falta no es una falta de
# ortografia que nadie ve -- es una palabra mal pronunciada en el video.
#
# Y pasa por una razon concreta: todo el codigo y todas las instrucciones de
# este Estudio estan escritos SIN tildes (por compatibilidad de consolas), y un
# modelo tiende a contestar en el registro en el que se le pregunta. Habia que
# pedirlo explicitamente y ademas comprobarlo.

#: Palabras que en castellano SIEMPRE llevan tilde o ñ, con su forma correcta.
#:
#: LA REGLA: solo entra una palabra si la version SIN tilde no existe. 'mas',
#: 'esta', 'publico' o 'el' existen tambien sin tilde y con otro significado,
#: asi que no prueban nada.
#:
#: La regla estaba escrita aqui arriba y la lista no la cumplia. 'aun' estaba
#: dentro, y 'aun' sin tilde es una palabra corriente: «aun asi», «aun cuando».
#: Con eso basto. Un guion de 2585 palabras que estaba DENTRO de su horquilla
#: (1400-2600) se declaro «SIN TILDES» por un unico «Aun asi», se pidio entero
#: otra vez, y la segunda pasada volvio con 3799 palabras en 120 bloques. Se
#: pago dos veces para acabar con un guion peor que el que ya habia.
#:
#: Y ahora la regla ADEMAS SE APLICA SOLA (ver reponer_tildes), asi que una
#: palabra ambigua aqui dentro ya no da solo un aviso falso: es una palabra bien
#: escrita que el motor estropea. Por eso salen 'aun', 'seria' y 'sabia' (los
#: dos son adjetivos), y 'tenia', 'medico', 'numero' y 'trafico' (existen como
#: nombre o como verbo). Y se corrige 'podia', que apuntaba a 'podían': una
#: «correccion» que le cambiaba la persona al verbo.
#:
#: 'ano' y 'anos' se quedan, y son la unica concesion a la regla: sin ñ existen,
#: pero son vocabulario que una narracion documental no usa, mientras que 'año'
#: sale en casi todas. Y si algun dia toca, la reposicion se anuncia.
SIN_TILDE_ES = {
    "tambien": "también", "despues": "después", "ademas": "además",
    "aqui": "aquí", "alli": "allí", "asi": "así", "segun": "según",
    "quiza": "quizá", "ano": "año", "anos": "años",
    "nino": "niño", "ninos": "niños", "senor": "señor", "senora": "señora",
    "manana": "mañana", "espana": "España", "pequeno": "pequeño",
    "companero": "compañero", "compania": "compañía", "diseno": "diseño",
    "sueno": "sueño", "dueno": "dueño", "extrano": "extraño",
    "dia": "día", "dias": "días", "pais": "país", "paises": "países",
    "habia": "había", "habian": "habían", "tenian": "tenían",
    "podia": "podía", "podian": "podían", "decia": "decía", "decian": "decían",
    "queria": "quería", "querian": "querían",
    "serian": "serían", "haria": "haría",
    "millon": "millón", "camion": "camión",
    "avion": "avión", "prision": "prisión", "decision": "decisión",
    "operacion": "operación", "informacion": "información",
    "investigacion": "investigación", "produccion": "producción",
    "situacion": "situación", "poblacion": "población", "region": "región",
    "kilometros": "kilómetros", "metodo": "método", "ultimo": "último",
    "ultima": "última", "unico": "único", "unica": "única",
    "rapido": "rápido", "facil": "fácil", "dificil": "difícil",
    "politica": "política", "economia": "economía",
    "policia": "policía", "cadaver": "cadáver", "carcel": "cárcel",
    "arbol": "árbol", "aereo": "aéreo", "mexico": "México",
    "america": "América", "africa": "África", "peru": "Perú",
    "panama": "Panamá", "bogota": "Bogotá", "japon": "Japón",
    "dolares": "dólares", "telefono": "teléfono", "camara": "cámara",
    "musica": "música", "numeros": "números",
    "credito": "crédito", "oceano": "océano",
}

#: Idiomas que usan diacriticos de forma habitual. En los demas (ingles,
#: neerlandes) un texto sin tildes es lo normal y no prueba nada.
IDIOMAS_CON_TILDE = ("es", "fr", "pt", "it", "de", "ca", "gl", "pl", "tr",
                     "ro", "hu", "cs", "vi")

#: Por debajo de esta proporcion de palabras con diacritico, un texto largo en
#: uno de esos idiomas casi seguro que se escribio sin tildes. En castellano
#: narrado lo normal esta entre el 8 % y el 14 %.
MINIMO_DIACRITICOS = 0.02


#: Una palabra del castellano, con sus tildes y su ñ. La usan el detector y la
#: reposicion: si buscaran con expresiones distintas, una podria ver una palabra
#: que la otra no sabe arreglar.
_PALABRA_ES = re.compile(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]+")


def _base(idioma):
    return str(idioma or "es").strip().lower().replace("_", "-").split("-")[0]


def palabras_sin_tilde(texto, idioma="es"):
    """Palabras que estan escritas sin la tilde (o la ñ) que les toca.

    Solo mira palabras que NO existen sin tilde, asi que lo que devuelve es un
    error seguro y no una sospecha.
    """
    if _base(idioma) != "es":
        return []
    encontradas = []
    for palabra in _PALABRA_ES.findall(str(texto or "")):
        correcta = SIN_TILDE_ES.get(palabra.lower())
        if correcta and palabra.lower() != correcta.lower():
            encontradas.append((palabra, correcta))
    return encontradas


def reponer_tildes(texto, idioma="es"):
    """Escribe bien las palabras de SIN_TILDE_ES. Devuelve (texto, cambios).

    ESTO ES LO BARATO Y POR ESO VA PRIMERO. La lista solo tiene errores seguros,
    y cada uno viene con su forma correcta al lado: reponer la tilde cuesta un
    milisegundo. Volver a pedirle el guion al modelo costaba minutos, miles de
    tokens y --medido-- un guion peor, porque un guion no se «devuelve igual
    pero con tildes»: se escribe otro.

    Lo que NO arregla esto es un guion escrito entero sin tildes. Ahi no hay
    lista que valga y hay que volver a pedirlo; eso lo sigue viendo
    `revisar_tildes` por la proporcion de diacriticos.

    Respeta como estaba escrita la palabra: 'Tambien' -> 'También' y
    'TAMBIEN' -> 'TAMBIÉN', no 'también' en los dos casos.
    """
    if _base(idioma) != "es":
        return str(texto or ""), []
    cambios = []

    def repone(casa):
        palabra = casa.group(0)
        correcta = SIN_TILDE_ES.get(palabra.lower())
        if not correcta or palabra.lower() == correcta.lower():
            return palabra
        if palabra.isupper() and len(palabra) > 1:
            correcta = correcta.upper()
        elif palabra[:1].isupper():
            correcta = correcta[:1].upper() + correcta[1:]
        cambios.append((palabra, correcta))
        return correcta

    return _PALABRA_ES.sub(repone, str(texto or "")), cambios


def proporcion_diacriticos(texto):
    """Fraccion de palabras con algun diacritico. 0 = ninguna."""
    palabras = re.findall(r"[^\W\d_]+", str(texto or ""), re.UNICODE)
    if not palabras:
        return 1.0
    con = sum(1 for p in palabras
              if any(unicodedata.combining(c) for c in
                     unicodedata.normalize("NFKD", p)))
    return con / float(len(palabras))


# ---------------------------------------------------------------- cifras
#
# La misma familia que las tildes, y por el mismo motivo: esto no se lee, se
# LOCUTA. Un guion con «2024» dentro no dice lo que pone, dice lo que el
# sintetizador decida que pone, y eso depende del idioma con el que resuelva ese
# token. Paso real: un guion en ingles con «Spain, May 2024» se locuto «may dos
# mil veinticuatro» -- el ano en castellano en mitad de una frase en ingles.
#
# No hay forma de arreglarlo desde los mandos de la voz, porque el problema no
# es la voz: es que «2024» no es una palabra, es una cifra que hay que expandir,
# y quien la expande no es quien escribio la frase. La unica manera de que el
# locutor diga lo que el guion quiere es que el guion lo escriba con letras.
#
# Vale igual para los simbolos: «%» puede salir como «por ciento», «porcentaje»
# o nada, y «&» igual. Se escriben con su palabra.

#: Cualquier digito suelto. En un texto que solo se locuta no hay ni uno
#: legitimo: hasta un «B001» es un id de bloque, no algo que se diga.
_CIFRA = re.compile(r"\d")

#: Simbolos que se leen de forma distinta segun quien los expanda.
_SIMBOLOS = "%$€£¥&#@+=½¼¾©®™"

#: Trozos con cifras o simbolos, para poder ensenar ejemplos concretos.
_TROZO_CON_CIFRA = re.compile(
    r"\S*(?:\d|[" + re.escape(_SIMBOLOS) + r"])\S*")


def revisar_cifras(texto):
    """¿Este texto lleva cifras o simbolos sin escribir con letras?

    Devuelve la ficha del diagnostico, con ejemplos, para poder pedir el guion
    otra vez senalando lo que hay que cambiar.
    """
    plano = str(texto or "")
    encontrados = []
    for trozo in _TROZO_CON_CIFRA.findall(plano):
        limpio = trozo.strip("«»\"'()[[]],.;:¿?¡!")
        if limpio and limpio not in encontrados:
            encontrados.append(limpio)
    return {
        "hay_cifras": bool(encontrados),
        "ejemplos": encontrados[:10],
        "cuantos": len(encontrados),
    }


#: NOMBRES PROPIOS PEGADOS, que el sintetizador no sabe partir.
#:
#: «AlexHost» no es una palabra de ningun idioma: es dos pegadas, y un TTS que
#: no la reconoce se inventa una pronunciacion de ocho letras seguidas. Medido
#: en un video real: «AlexHost» y «SmokeLoader» salieron irreconocibles, y ni
#: siquiera se entendia de que se estaba hablando.
#:
#: La cura es escribirlo SEPARADO en el guion --«Alex Host», «Smoke Loader»--,
#: que ademas es lo que se oye, asi que el subtitulo tambien queda bien. No se
#: parte aqui: se DETECTA y se vuelve a pedir el guion, como con las cifras. Un
#: arreglo automatico partiria «McDonald» o «DeSantis», que son una palabra sola.
#:
#: La forma que se busca es la de un compuesto de verdad: dos trozos con inicial
#: mayuscula, el primero de tres letras o mas, y el segundo tambien -- o una
#: sola mayuscula final, que es la otra forma que se usa («StealC»).
_COMPUESTO_PEGADO = re.compile(
    r"\b[A-Z][a-z]{2,}(?:[A-Z][a-z]{2,}|[A-Z](?![a-z]))+\b")

#: Cuantos se ensenan al pedirlo otra vez. Con la lista entera la correccion
#: ocupa mas que la regla y deja de leerse.
MAXIMO_COMPUESTOS = 10


def separar_compuesto(token):
    """«AlexHost» -> «Alex Host». Solo para ensenarlo en el aviso."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(token or ""))


def revisar_compuestos(texto):
    """Nombres propios escritos pegados, que el TTS no sabe pronunciar.

    Devuelve la ficha del diagnostico con ejemplos, para poder pedir el guion
    otra vez senalando cuales hay que separar.
    """
    encontrados = []
    for trozo in _COMPUESTO_PEGADO.findall(str(texto or "")):
        if trozo not in encontrados:
            encontrados.append(trozo)
    return {
        "hay_compuestos": bool(encontrados),
        "ejemplos": [f"'{t}' -> '{separar_compuesto(t)}'"
                     for t in encontrados[:MAXIMO_COMPUESTOS]],
        "tokens": encontrados,
        "cuantos": len(encontrados),
    }


def revisar_tildes(texto, idioma="es", minimo_palabras=120):
    """¿Este texto se escribio sin tildes? Devuelve la ficha del diagnostico.

    Importa mas de lo que parece: esto no se lee, se LOCUTA. Sin tilde, el
    sintetizador dice 'publico' donde el guion queria 'publicó', y eso no se
    arregla en el montaje.

    'minimo_palabras' evita gritar por un texto corto: en tres frases puede no
    tocar ninguna palabra con tilde de forma perfectamente legitima.
    """
    texto = str(texto or "")
    faltan = palabras_sin_tilde(texto, idioma)
    proporcion = proporcion_diacriticos(texto)
    palabras = contar_palabras(texto)
    sospecha = (_base(idioma) in IDIOMAS_CON_TILDE
                and palabras >= minimo_palabras
                and proporcion < MINIMO_DIACRITICOS)
    ejemplos = [f"'{mal}' -> '{bien}'" for mal, bien in faltan[:8]]
    return {
        "sin_tildes": bool(faltan) or sospecha,
        "faltan": faltan,
        "ejemplos": ejemplos,
        "proporcion": round(proporcion, 4),
        "palabras": palabras,
    }


def recortar(texto, maximo, aviso="[...material recortado...]"):
    """Recorta un texto largo por el final dejando constancia del recorte."""
    texto = str(texto or "")
    if len(texto) <= maximo:
        return texto, False
    return texto[:maximo].rsplit("\n", 1)[0] + "\n" + aviso, True


def ficha_de_fotogramas(ruta, clave):
    """Lee una ficha de fotogramas y descarta los que ya no estan en disco.

    La usan `estilo` (sus candidatos) y `frames` (los del video de referencia).
    Estaba escrita dos veces, con el mismo comentario reescrito, y el motivo es
    el mismo en las dos: un fotograma borrado a mano no puede seguir saliendo
    como elegible en la pantalla, o se elige algo que no existe y el paso falla
    mucho mas tarde, cuando ya se ha pagado lo anterior.

    Devuelve None si no hay ficha o si esta ilegible: no hay nada que ensenar.
    """
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, ValueError):
        return None
    vivos = [f for f in (datos.get(clave) or []) if os.path.exists(f.get("ruta", ""))]
    datos[clave] = vivos
    datos["total"] = len(vivos)
    return datos


def extraer_json(texto, que="la respuesta"):
    """Saca el objeto JSON de una respuesta del CLI aunque venga envuelto.

    A un modelo se le pide JSON y a veces contesta con el JSON dentro de una
    valla de markdown, o con una frase amable delante. Esto lo desenvuelve.

    Estaba copiado en varios modulos (conservar, plan_callouts,
    catalogo_visual, estilo), unos byte a byte y otros con el mensaje de error
    cambiado. Vive aqui porque todos los pasos que hablan
    con el CLI ya entran por `comun`, y porque un desenvolvedor con seis
    versiones es un desenvolvedor con seis comportamientos el dia que alguien
    arregle uno.

    `que` es lo que se nombra en el error ("la guia", "el catalogo"): un fallo
    de parseo tiene que decir QUE respuesta no se pudo leer, o hay que ir a
    buscar en la traza de qué paso venía.

    Lo que NO usa esto es `p3_guion`, a proposito: el guion empareja llaves con
    `_primer_objeto` en vez de cortar entre la primera y la ultima, y su suite
    lo prueba por su nombre. Cambiarle el parser al paso mas caro del pipeline
    para ahorrar quince lineas es un mal negocio.
    """
    texto = str(texto or "").strip()
    if texto.startswith("```"):
        texto = re.sub(r"^```[a-z]*\s*|\s*```$", "", texto)
    try:
        return json.loads(texto)
    except ValueError:
        pass
    principio, final = texto.find("{"), texto.rfind("}")
    if principio >= 0 and final > principio:
        try:
            return json.loads(texto[principio:final + 1])
        except ValueError as fallo:
            raise RuntimeError(f"{que} no es un JSON legible: {fallo}")
    raise RuntimeError(f"{que} no trae ningun objeto JSON: {texto[:300]}")


# ------------------------------------------------------------ la correccion
#
# LO QUE HACE UTIL EL FEEDBACK DE UNA FRASE.
#
# En el modo light no hay desglose: un preset se ensena entero y, si algo no
# convence, se pide en una frase ("que los subtitulos sean mas claros", "menos
# solemne", "una voz mas joven") y se rehace ESA parte. Esa frase tiene que
# entrar en el prompt, y tiene que entrar CON PRECEDENCIA: quien escribe la guia
# ha visto lo mismo que la vez anterior, asi que sin decirle que esto manda
# volveria a escribir lo mismo.
#
# Va al FINAL y no al principio. Es la misma leccion que el feedback de un plano
# de un plano: alli se midio que 905 caracteres de
# descripcion tapaban 140 de nota, y la cura fue ponerla la ultima y declarar la
# precedencia en voz alta. Aqui pasa lo mismo con una guia de 400 palabras.
#
# Vive en comun y no en cada modulo porque la usan los tres --estilo, tono y
# voz-- y con tres copias una se quedaria sin la linea de precedencia, que es la
# unica que de verdad hace algo.

def bloque_correccion(peticion, que="lo anterior"):
    """El texto que se pega al final de una instruccion para corregirla.

    Devuelve "" si no hay peticion, para poder concatenarlo siempre sin un `if`
    en cada sitio.
    """
    peticion = " ".join(str(peticion or "").split())
    if not peticion:
        return ""
    return ("\n\nCORRECCION, Y MANDA SOBRE TODO LO DE ARRIBA\n"
            f"Ya has hecho esto antes y el canal ha mirado el resultado. Esto es "
            f"lo que ha pedido cambiar de {que}:\n\n"
            f'"{peticion}"\n\n'
            "Aplicalo aunque contradiga lo que escribirias por tu cuenta o lo "
            "que dice el material de entrada: quien lo ha pedido ha visto el "
            "resultado y tu no. Lo demas se queda como estaba -- corriges lo "
            "que te dicen, no rehaces todo con otro criterio.")


# ============================================================ EL FORMATO
#
# HORIZONTAL (16:9) O VERTICAL (9:16), y se decide al crear el video, junto a
# la duracion (02-09-2026). Todo lo que cuelga de esa decision
# la lee de aqui y de ningun otro sitio: el tamano al que se PIDE cada imagen,
# el lienzo de generacion sobre el que se componen las capas y las cartelas, y
# el cuadro de salida del MP4. Vive en `comun` porque lo leen p2, p6, p7, p8 y
# cartelas, y ninguno importa a los demas en ese sentido.
#
#   salida        el cuadro del MP4 y de la capa quieta (subtitulos)
#   generacion    el lienzo de las imagenes y de la capa movil (cartelas). Es
#                 3:2 en horizontal y 2:3 en vertical: el generador de imagen
#                 solo sabe hacer esos dos tamanos, y el video recorta dentro.
#   tamano_imagen el nombre con el que se le pide al motor de imagen

FORMATOS = {
    "horizontal": {"nombre": "Horizontal 16:9", "salida": [1920, 1080],
                   "generacion": [1536, 1024], "tamano_imagen": "apaisado"},
    "vertical": {"nombre": "Vertical 9:16", "salida": [1080, 1920],
                 "generacion": [1024, 1536], "tamano_imagen": "vertical"},
}
FORMATO_POR_DEFECTO = "horizontal"


def normalizar_formato(valor):
    """'vertical' | 'horizontal'. Lo desconocido cae en horizontal, que es lo
    que habia siempre: un proyecto anterior a esto no trae ninguno."""
    texto = str(valor or "").strip().lower()
    if texto in ("vertical", "9:16", "9x16", "portrait"):
        return "vertical"
    return FORMATO_POR_DEFECTO


def ficha_formato(valor):
    """La ficha del formato, con sus tres tamanos. Nunca levanta."""
    ficha = dict(FORMATOS[normalizar_formato(valor)])
    ficha["id"] = normalizar_formato(valor)
    ficha["salida"] = list(ficha["salida"])
    ficha["generacion"] = list(ficha["generacion"])
    return ficha


def formato_de_plan(plan):
    """El formato con el que se corto un plan. Un plan de antes es horizontal."""
    return normalizar_formato((plan or {}).get("formato"))
