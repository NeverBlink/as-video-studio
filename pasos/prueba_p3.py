"""
Prueba del paso 3 (guion).

Dos mitades: la logica del paso (parseo de la respuesta, ids de bloque,
horquilla de palabras, manejo de fallos del CLI) se prueba sin red, y
despues se llama de verdad al CLI de Claude para redactar un guion corto sobre
un material de referencia en ingles con un brief en espanol.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_p3.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

# La salud de las cuentas del CLI (pasos/salud_cli.py) se apunta en CADA
# llamada, tambien en las de los dobles de esta suite: sin redirigirla iria
# al almacen de claves de verdad.
os.environ.setdefault("ESTUDIO_SECRETOS", tempfile.mkdtemp(prefix="secretos_prueba_"))
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import comun
import marcas_tts
import p2_brief
import p3_guion
from nucleo import Estado, Proyecto

FALLOS = []

MATERIAL = [
    "In 1863 a young bookkeeper from Cleveland put his savings into a small oil refinery.",
    "His name was John Davison Rockefeller and he was twenty three years old.",
    "He did not drill for oil because drilling was the part of the business that ruined people.",
    "Instead he bought the refineries that turned crude oil into kerosene for lamps.",
    "By 1870 he had folded those refineries into a single company called Standard Oil.",
    "The railroads carried his kerosene and he demanded secret rebates on every barrel.",
    "Competitors paid the full freight rate while Standard Oil paid a fraction of it.",
    "One by one the rival refiners sold out to him or went bankrupt.",
    "By 1880 Standard Oil controlled about ninety percent of the refining capacity of the country.",
    "The company built its own pipelines, its own barrels and its own tank cars.",
    "In 1911 the Supreme Court ordered Standard Oil to break into thirty four companies.",
    "Rockefeller owned a quarter of the shares of every one of those new companies.",
    "The breakup made him richer than he had ever been before.",
    "He spent the last decades of his life giving that fortune away.",
    "He died in 1937 with a fortune worth about one and a half percent of the American economy.",
]


def comprobar(condicion, texto):
    """Registra el resultado de una comprobacion y sigue con las demas."""
    if condicion:
        print(f"  ok   {texto}")
    else:
        print(f"  FALLO {texto}")
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado,
              texto if obtenido == esperado
              else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def falla(funcion, esperado_en_mensaje, texto):
    """Comprueba que algo falla y que el mensaje explica que ha pasado."""
    try:
        funcion()
    except (ValueError, RuntimeError) as fallo:
        mensaje = str(fallo)
        comprobar(esperado_en_mensaje.lower() in mensaje.lower(),
                  f"{texto} -> {mensaje[:110]}")
        return
    comprobar(False, f"{texto} (no fallo)")


class ProcesoFalso:
    """Un Popen de mentira: el paso habla con el CLI por communicate()."""

    def __init__(self, codigo=0, salida=b"", error=b"", al_comunicar=None):
        self.returncode = codigo
        self.stdout = salida
        self.stderr = error
        self.al_comunicar = al_comunicar
        self.pid = -1
        self.matado = False

    def communicate(self, entrada=None, timeout=None):
        if isinstance(self.al_comunicar, BaseException):
            raise self.al_comunicar
        return self.stdout, self.stderr

    def kill(self):
        self.matado = True


def simular_cli(resultado):
    """Sustituye subprocess.Popen dentro del paso y devuelve el original."""
    original = p3_guion.subprocess.Popen

    def falso(*args, **kwargs):
        if isinstance(resultado, BaseException):
            raise resultado
        return resultado

    p3_guion.subprocess.Popen = falso
    return original


def _tardar(proceso, segundos=1.5):
    """communicate() que tarda, para probar la regla de no reintentar esperas largas."""
    def comunicar(entrada=None, timeout=None):
        time.sleep(segundos)
        return proceso.stdout, proceso.stderr
    return comunicar


def leer_json(ruta):
    """Lo gordo ya no viaja en las salidas: se lee del fichero de la version."""
    with open(ruta, "r", encoding="utf-8") as fh:
        return json.load(fh)


def sobre_cli(texto):
    """Sobre JSON como el que escribe 'claude -p --output-format json'."""
    return json.dumps({"is_error": False, "result": texto, "total_cost_usd": 0.01,
                       "duration_ms": 1234, "num_turns": 1}).encode("utf-8")


# --------------------------------------------------------------------- logica

def prueba_params():
    print("\n[1] parametros")
    for clave in ("prompt_general", "regenerar_desde_cero"):
        comprobar(clave in p3_guion.PARAMS_POR_DEFECTO,
                  f"PARAMS_POR_DEFECTO trae {clave}")

    falla(lambda: p3_guion._normalizar({"tiempo_max_s": 5}), "al menos 30",
          "tiempo_max_s demasiado corto")
    falla(lambda: p3_guion._normalizar({"reintentos": -1}), "al menos 0",
          "reintentos negativos")
    falla(lambda: p3_guion._normalizar({"reintentos": "muchos"}), "entero",
          "reintentos que no son numero")

    opciones = p3_guion._normalizar({"prompt_general": "  menos cifras  ",
                                     "regenerar_desde_cero": 1})
    igual(opciones["prompt_general"], "menos cifras", "el prompt se limpia")
    igual(opciones["regenerar_desde_cero"], True, "la bandera se vuelve booleana")

    resumen = p3_guion.describir({"prompt_general": "empieza por el final",
                                  "regenerar_desde_cero": True})
    comprobar("\n" not in resumen and "desde cero" in resumen,
              f"describir da una linea: {resumen}")


def prueba_parseo():
    print("\n[2] lectura de la respuesta del modelo")
    esperado = {"titulo": "T", "bloques": [{"id": "B001", "texto": "hola"}]}
    igual(p3_guion._extraer_json(json.dumps(esperado)), esperado, "JSON pelado")
    igual(p3_guion._extraer_json("```json\n" + json.dumps(esperado) + "\n```"), esperado,
          "JSON dentro de vallas de markdown")
    igual(p3_guion._extraer_json("Aqui tienes:\n" + json.dumps(esperado) + "\nEso es todo."),
          esperado, "JSON envuelto en texto")
    igual(p3_guion._extraer_json('{"titulo": "con {llaves} dentro", "bloques": []}'),
          {"titulo": "con {llaves} dentro", "bloques": []},
          "llaves dentro de una cadena no confunden al lector")

    falla(lambda: p3_guion._extraer_json("no hay json aqui"), "no contiene ningun json",
          "respuesta sin JSON")
    falla(lambda: p3_guion._extraer_json('{"titulo": "roto", "bloques": [}'),
          "mal formado", "JSON mal formado")


def prueba_bloques():
    print("\n[3] bloques e ids")
    buenos = p3_guion._normalizar_bloques(
        {"bloques": [{"id": "B007", "texto": "uno"}, {"id": "B008", "texto": "dos"}]})
    igual([b["id"] for b in buenos], ["B007", "B008"],
          "los ids con formato correcto se respetan (continuidad entre iteraciones)")

    renumerados = p3_guion._normalizar_bloques(
        {"bloques": [{"id": "1", "texto": "uno"}, {"id": "dos", "texto": "dos"}]})
    igual([b["id"] for b in renumerados], ["B001", "B002"], "los ids invalidos se renumeran")

    repetidos = p3_guion._normalizar_bloques(
        {"bloques": [{"id": "B001", "texto": "uno"}, {"id": "B001", "texto": "dos"}]})
    igual([b["id"] for b in repetidos], ["B001", "B002"], "los ids repetidos se renumeran")

    sueltos = p3_guion._normalizar_bloques({"bloques": ["primero", "segundo"]})
    igual([b["texto"] for b in sueltos], ["primero", "segundo"],
          "acepta bloques como cadenas sueltas")
    igual(p3_guion._normalizar_bloques({"guion": [{"id": "B001", "texto": " a   b "}]})[0]["texto"],
          "a b", "el texto se normaliza de espacios")

    falla(lambda: p3_guion._normalizar_bloques({"titulo": "T"}), "ningun bloque",
          "respuesta sin bloques")
    falla(lambda: p3_guion._normalizar_bloques({"bloques": [{"texto": "  "}]}), "vacios",
          "bloques vacios")
    falla(lambda: p3_guion._normalizar_bloques([1, 2]), "objeto json",
          "respuesta que no es un objeto")


def prueba_aire():
    """El silencio que separa un tema del siguiente.

    Un video que salta de asunto sin pausa se oye como una lista leida: sin
    aire delante, la primera frase del tema nuevo entra pegada al remate del
    anterior. La pausa no puede depender de que el redactor la anote.
    """
    print("\n[3b] aire al cambiar de tema")
    opciones = p3_guion._normalizar({})
    bloques = [{"id": "B001", "texto": "el gancho.", "abre_seccion": True},
               {"id": "B002", "texto": "sigue el mismo tema.", "abre_seccion": False},
               {"id": "B003", "texto": "y aqui empieza otro.", "abre_seccion": True}]
    igual(p3_guion._aire_entre_secciones(bloques, opciones), 1,
          "se pone un silencio por cada cambio de tema")
    comprobar(marcas_tts.silencio_final(bloques[1]["texto"]) >= 900,
              "y va en el bloque que CIERRA el tema, no en el que abre el nuevo")
    igual(marcas_tts.silencio_final(bloques[2]["texto"]), 0,
          "el bloque que abre no arrastra silencio propio")
    igual(marcas_tts.limpiar(bloques[1]["texto"]), "sigue el mismo tema.",
          "y no cambia ni una palabra de lo que se locuta")
    igual(p3_guion._aire_entre_secciones(bloques, opciones), 0,
          "pasarlo dos veces no encadena dos silencios")

    sin_marcas = p3_guion._normalizar({"anotaciones_voz": False})
    limpios = [{"id": "B001", "texto": "uno.", "abre_seccion": True},
               {"id": "B002", "texto": "dos.", "abre_seccion": True}]
    igual(p3_guion._aire_entre_secciones(limpios, sin_marcas), 0,
          "con las anotaciones apagadas no se pone: se borraria despues")
    igual(p3_guion._aire_entre_secciones(
        [dict(b) for b in bloques], p3_guion._normalizar({"pausa_seccion_ms": 0})), 0,
          "y con la pausa a cero se desactiva")
    falla(lambda: p3_guion._normalizar({"pausa_seccion_ms": -1}), "al menos 0",
          "una pausa negativa se rechaza")


def prueba_copias():
    """La horquilla y las revisiones que obligan a rehacer el guion.

    AQUI VIVIA EL DETECTOR DE COPIAS y se retiro el 24-08-2026: con `fuentes`
    el material puede ser el guion que ha escrito la propia persona, y un
    detector de tiradas identicas no distingue eso de un plagio -- lo unico que
    sabe hacer es reescribir lo que le acaban de dar por bueno. Lo que queda son
    las revisiones que SI son del motor: horquilla, cifras y tildes.
    """
    print("\n[4] horquilla, cifras y tildes")
    bloques = [
        {"id": "B001", "texto": "By 1880 Standard Oil controlled about ninety percent "
                                "of the refining capacity of the country."},
        # Con su tilde y con el ano ESCRITO CON LETRAS, que es como tiene que
        # salir un guion: esto se locuta. Sin tilde el sintetizador pronuncia mal
        # 'pais', y una cifra la expande el como decida -- «May 2024» en un guion
        # en ingles se locuto «may dos mil veinticuatro».
        {"id": "B002", "texto": "Para mil ochocientos ochenta su empresa refinaba "
                                "nueve de cada diez barriles del país."},
    ]
    brief = {"margen": {"minimo": 100, "maximo": 140}}
    opciones = p3_guion._normalizar({})
    comprobar(any("minimo de la horquilla son 100" in m for m in
                  p3_guion._problemas(bloques, 30, brief, opciones, "es")),
              "un guion por debajo de la horquilla obliga a rehacer")
    comprobar(any("recorta" in m for m in
                  p3_guion._problemas(bloques, 400, brief, opciones, "es")),
              "un guion por encima de la horquilla obliga a rehacer")
    limpios = bloques[1:]   # B001 arrastra su ano en cifras
    igual(p3_guion._problemas(limpios, 120, brief, opciones, "es"), [],
          "un guion dentro de la horquilla y sin cifras no se rehace")
    comprobar(any("cifra" in m for m in
                  p3_guion._problemas(bloques, 120, brief, opciones, "es")),
              "un ano en cifras obliga a rehacer: se locuta y lo expande el TTS")
    igual(p3_guion._problemas(limpios, 139, brief, opciones, "es"), [],
          "dentro de la horquilla no se persigue la cifra exacta")
    # Y NADA DE COPIAS: el mismo bloque, palabra por palabra igual al material,
    # ya no es un motivo para rehacer. Es la comprobacion de que se fue.
    identico = [{"id": "B001", "texto": MATERIAL[0]}]
    comprobar(not any("copian" in m for m in
                      p3_guion._problemas(identico, 120, brief, opciones, "es")),
              "copiar el material palabra por palabra ya no obliga a rehacer")

    por_idioma = {"horquillas": {"en": {"presupuesto_palabras": 200,
                                        "palabras_minimo": 140,
                                        "palabras_maximo": 260}}}
    igual(p3_guion._horquilla(por_idioma, "en"), (200, 140, 260),
          "la horquilla se puede fijar por idioma en el brief")

    # UNA TILDE SUELTA SE REPONE Y NO SE VUELVE A PEDIR EL GUION.
    #
    # Esto costo un guion entero el 27-08-2026: 2585 palabras dentro de la
    # horquilla se declararon «SIN TILDES» por un unico «Aun asi» --que ademas
    # esta bien escrito-- y la segunda pasada devolvio 3799.
    igual(comun.reponer_tildes("Aun cuando fallara, ni aun con eso", "es")[1], [],
          "'aun' sin tilde es castellano correcto y no se toca")
    comprobar(not comun.palabras_sin_tilde("Aun cuando fallara lo hizo", "es"),
              "y tampoco se denuncia como falta")
    texto, cambios = comun.reponer_tildes("tambien decia el senor", "es")
    igual(texto, "también decía el señor", "las faltas seguras se escriben bien")
    igual(len(cambios), 3, "y se devuelve lo que se ha tocado")
    igual(comun.reponer_tildes("Tambien y TAMBIEN", "es")[0], "También y TAMBIÉN",
          "respetando como estaba escrita la palabra")
    igual(comun.reponer_tildes("Tambien", "en")[1], [],
          "y en un idioma que no es el castellano no se toca nada")
    igual(comun.SIN_TILDE_ES["podia"], "podía",
          "'podia' se corrige a 'podia' con tilde, no a 'podian': era otra persona del verbo")

    avisos_marcas = []
    repuestos = p3_guion._aplicar_marcas(
        [{"id": "B001", "texto": "tambien lo decia aqui"}],
        p3_guion._normalizar({}), avisos_marcas, "es")
    igual(repuestos[0]["texto"], "también lo decía aquí",
          "el embudo de bloques repone las tildes del texto que se locuta")
    comprobar(any("repuestas 3 tilde" in a for a in avisos_marcas),
              "y lo cuenta en los avisos: corregir en silencio es no enterarse")
    igual(p3_guion._problemas(repuestos, 120, brief, opciones, "es"), [],
          "una falta que ya se ha repuesto no obliga a rehacer el guion")

    # Lo que SI obliga a rehacerlo es un guion escrito entero sin tildes: ahi no
    # hay lista de palabras que valga.
    seco = [{"id": "B001", "texto": " ".join(
        ["texto liso de relleno sin ni un solo diacritico dentro"] * 20)}]
    comprobar(any("ENTERO sin tildes" in m for m in
                  p3_guion._problemas(seco, 120, brief, opciones, "es")),
              "un guion sin un solo diacritico si obliga a rehacerlo")


def prueba_instruccion():
    print("\n[5] instruccion que se le manda al CLI")
    transcript = [{"t_in": i * 4, "t_out": i * 4 + 4, "texto": t}
                  for i, t in enumerate(MATERIAL)]
    brief = {"instrucciones": "menos tecnicismos", "idioma_salida_nombre": "espanol",
             "presupuesto_palabras": 138, "margen": {"minimo": 124, "maximo": 152},
             "palabras_por_bloque": 30, "avisos": ["el material esta en ingles"]}
    anterior = {"titulo": "Version vieja", "guion": [{"id": "B001", "texto": "algo viejo"}]}
    opciones = p3_guion._normalizar({"prompt_general": "empieza por el final"})

    texto = p3_guion._instruccion(transcript, {"titulo": "Rockefeller", "canal": "Canal",
                                               "duracion_s": 60, "palabras_transcript": 200},
                                  brief, anterior, opciones, ["corrige esto"], "es")
    for fragmento in ("REDACTA DE NUEVO", "mismos hechos", "mismo orden",
                      "ritmo de capitulos", "DOCUMENTACION",
                      "menos tecnicismos", "empieza por el final", "Version vieja",
                      "algo viejo", "entre 124 y 152 palabras", "en espanol",
                      "corrige esto", "el material esta en ingles",
                      "[00:04] His name was John Davison Rockefeller"):
        comprobar(fragmento in texto, f"la instruccion incluye: {fragmento!r}")
    comprobar("No copies ninguna frase" in texto and "parafrasees frase a frase" in texto,
              "la instruccion prohibe copiar y parafrasear frase a frase")
    comprobar("no persigas un numero exacto" in texto,
              "la instruccion pide una horquilla, no una cifra exacta")

    # LAS DOS REGLAS DE LONGITUD TIENEN QUE MULTIPLICAR AL PRESUPUESTO.
    #
    # La regla 4 decia «bloques de unas 30 palabras» y no decia CUANTOS, asi que
    # se contradecia con la regla 3 (el total) sin que ninguna estuviera mal:
    # diez bloques de 30 son 300 palabras y siete son 210, y las dos cumplen esa
    # linea. Salio en los dos sentidos: un guion de 302 palabras sobre un maximo
    # de 269 y otro de 268 hecho de trece bloques de 21, que cumple el total
    # rompiendo el tamano de bloque. El brief ya calculaba los bloques previstos
    # y no llegaban hasta aqui.
    comprobar("unos 5 bloques" in texto,
              "la instruccion dice CUANTOS bloques, no solo de que tamano")
    comprobar("5 x 30 son unas 150 palabras" in texto,
              "y trae la cuenta hecha: bloques x tamano = la longitud pedida")
    comprobar("el total manda sobre el tamano del bloque" in texto,
              "con cual de las dos gana si no cuadran")

    # y si el brief trae los bloques calculados, mandan sobre la division
    con_bloques = p3_guion._instruccion(
        transcript, {}, dict(brief, bloques_estimados=9), None, opciones, [], "es")
    comprobar("unos 9 bloques" in con_bloques,
              "los bloques que calculo el brief mandan sobre la cuenta local")

    # UNA CORRECCION SIN EL TEXTO QUE CORRIGE NO SE PUEDE OBEDECER. Cada llamada
    # al CLI es una sesion nueva: pedir «devuelvelo sin cambiar nada mas» sin
    # ensenarle el «lo» solo puede acabar en otro guion distinto, y acabo -- de
    # 88 bloques a 120.
    previo = {"_bloques": [{"id": "B001", "texto": "lo que devolvio el intento uno"}]}
    con_previo = p3_guion._instruccion(
        transcript, {}, brief, None, opciones,
        ["el guion se va a 3799 palabras y el maximo son 2600"], "es", previo)
    comprobar("LO QUE DEVOLVISTE EN EL INTENTO ANTERIOR" in con_previo,
              "al corregir, el intento que se corrige va dentro de la instruccion")
    comprobar("lo que devolvio el intento uno" in con_previo,
              "y va con su texto entero, bloque a bloque")
    comprobar("1 bloques, 6 palabras" in con_previo,
              "con la cuenta hecha, que es lo que hay que corregir")
    sin_correcciones = p3_guion._instruccion(transcript, {}, brief, None, opciones,
                                             [], "es", previo)
    comprobar("LO QUE DEVOLVISTE" not in sin_correcciones,
              "sin correcciones que hacer no se le repite lo que ya escribio")

    # LA ESTRUCTURA ES LO PRIMERO QUE SE DECIDE. Sin esta seccion el guion salia
    # correcto frase a frase y sin relato: doce temas mencionados, ninguno
    # explicado y saltando de uno a otro sin cerrar.
    comprobar("COMO SE ESTRUCTURA ESTE VIDEO" in texto,
              "la instruccion dice como se estructura el video, no solo como se escribe")
    for trozo in ("POCOS TEMAS", "EL ORDEN ES UN ARGUMENTO", "NO SE RELLENA",
                  "Y NO SE SALTA"):
        comprobar(trozo in texto, f"  y lo dice entero: {trozo!r}")
    comprobar(texto.index("COMO SE ESTRUCTURA") < texto.index("== REGLAS =="),
              "y va antes de las reglas de oficio: primero que se cuenta, luego como")
    # LAS PARADAS SON LAS SECCIONES, dicho en los dos sitios. Sin atarlas, esta
    # seccion pide cuatro o seis paradas y la regla 11 admite hasta diez
    # secciones: dos reglas que se contradicen sin que ninguna este mal, que es
    # el mismo fallo que tenian la 3 y la 4 con las palabras y los bloques.
    comprobar("PARADAS SON LAS SECCIONES" in texto,
              "y ata las paradas a las secciones del guion")
    comprobar("COMO SE ESTRUCTURA ESTE VIDEO)" in texto,
              "y la regla de las secciones apunta de vuelta a las paradas")

    # EL VIDEO DE ORIGEN, cuando el material es un dosier de busquedas. Sin el,
    # encender las busquedas borraba del prompt el video que se puso de
    # referencia: el guion se escribia sin haberlo leido nunca, y salia sin
    # parecerse a el ni en el asunto ni en el vocabulario.
    origen = ([{"t_in": 0.0, "t_out": 4.0,
                "texto": "el oro se mide en onzas troy y esto es una explicacion financiera"}],
              {"titulo": "Como invertir en oro"})
    con_origen = p3_guion._instruccion(transcript, {}, brief, None, opciones, [],
                                       "es", None, origen)
    comprobar("EL VIDEO DE ORIGEN" in con_origen,
              "con dosier y video de origen, el video entra entero en la instruccion")
    comprobar("explicacion financiera" in con_origen,
              "y va su transcripcion, no solo su titulo")
    comprobar("Como invertir en oro" in con_origen, "con su titulo delante")
    # QUIEN MANDA EN QUE. La guia de tono sale de OTROS videos del canal y este
    # es el de ESTE encargo: sin repartirlo, un canal con guia de tono de
    # estafas escribe un video de finanzas con vocabulario de estafas.
    comprobar("la FORMA de la frase" in con_origen and "el ASUNTO" in con_origen,
              "diciendo que manda la guia de tono y que manda el video de origen")
    comprobar(con_origen.index("EL VIDEO DE ORIGEN")
              < con_origen.index("== BRIEF DEL USUARIO =="),
              "y va pegado al material, antes del brief")
    comprobar("EL ORDEN LO PONES TU" in con_origen,
              "con dosier, la regla 1 deja de mandar seguir un orden que no existe")
    comprobar("EL ORDEN LO PONES TU" not in texto,
              "y con un video transcrito de verdad se sigue su orden, como antes")
    comprobar("EL VIDEO DE ORIGEN" not in texto,
              "sin dosier no se pinta la seccion: seria el mismo texto dos veces")

    sin_anterior = p3_guion._instruccion(transcript, {}, brief, None, opciones, [], "es")
    comprobar("GUION ANTERIOR" not in sin_anterior,
              "sin guion previo no se inventa la seccion")

    corto = p3_guion._normalizar({"max_caracteres_transcript": 2000})
    recortado = p3_guion._instruccion(transcript * 4, {}, brief, None, corto, [], "es")
    comprobar("transcript recortado" in recortado,
              "un transcript que no cabe se recorta dejando constancia")
    comprobar(len(recortado) < len(p3_guion._instruccion(transcript * 4, {}, brief,
                                                         None, opciones, [], "es")),
              "el recorte de verdad acorta la instruccion")



def prueba_fallos_cli():
    print("\n[6] fallos del CLI tratados como error del paso")
    opciones = p3_guion._normalizar({})
    carpeta = tempfile.gettempdir()
    COLGADO = ProcesoFalso(al_comunicar=subprocess.TimeoutExpired("claude", 420))

    casos = [
        (ProcesoFalso(1, b"", b"boom: modelo no disponible"), "codigo 1",
         "el CLI devuelve codigo distinto de cero"),
        (ProcesoFalso(0, b"no soy json"), "no devolvio json",
         "el CLI escribe algo que no es JSON"),
        (ProcesoFalso(0, json.dumps({"is_error": True, "result": "sin credito"}).encode()),
         "devolvio error", "el CLI marca is_error"),
        (ProcesoFalso(0, sobre_cli("   ")), "respuesta vacia",
         "el CLI contesta en blanco"),
        # El plazo NO se escribe a mano: se deriva del esfuerzo por defecto del
        # paso, asi que cambiar ese defecto no rompe la prueba (y si alguien lo
        # cambia sin querer, esto lo sigue cubriendo).
        (COLGADO, f"no ha respondido en {p3_guion.tiempo_max_de(opciones)} s",
         "el CLI se queda colgado"),
        (OSError("no se pudo lanzar"), "no se ha podido lanzar",
         "el ejecutable no arranca"),
    ]
    for resultado, esperado, texto in casos:
        original = simular_cli(resultado)
        try:
            falla(lambda: p3_guion._llamar_claude("hola", opciones, carpeta),
                  esperado, texto)
        finally:
            p3_guion.subprocess.Popen = original

    comprobar(COLGADO.matado,
              "al vencer el tiempo se mata el proceso (y con el, sus hijos)")
    comprobar(os.path.exists(p3_guion._localizar_claude()),
              f"encuentra el CLI: {p3_guion._localizar_claude()}")


def prueba_reintento():
    print("\n[7] reintento cuando la respuesta no se puede leer")
    base = tempfile.mkdtemp(prefix="prueba_p3_sim_")
    try:
        proyecto, estado = preparar_proyecto(base, "Guion Simulado")
        respuestas = [ProcesoFalso(0, sobre_cli("perdona, ahora te lo doy")),
                      ProcesoFalso(0, sobre_cli(json.dumps(
                          {"titulo": "A la segunda",
                           "bloques": [{"id": "B001", "texto": "uno " * 70},
                                       {"id": "B002", "texto": "dos " * 70}]})))]
        original = p3_guion.subprocess.Popen
        p3_guion.subprocess.Popen = lambda *a, **k: respuestas.pop(0)
        try:
            salidas = p3_guion.ejecutar(proyecto, {"prompt_general": "prueba"},
                                        lambda v, m="": v)
        finally:
            p3_guion.subprocess.Popen = original

        igual(salidas["intentos"], 2, "reintenta cuando la primera respuesta no se lee")
        igual(salidas["titulo"], "A la segunda", "se queda con la respuesta buena")
        trabajo = proyecto.ruta_trabajo("guion", crear=False)
        comprobar(os.path.exists(os.path.join(trabajo, "instruccion_2.txt")),
                  "guarda la instruccion de cada intento")

        respuestas = [ProcesoFalso(0, sobre_cli("sigo sin darte JSON")),
                      ProcesoFalso(0, sobre_cli("y sigo sin darte JSON"))]
        p3_guion.subprocess.Popen = lambda *a, **k: respuestas.pop(0)
        try:
            falla(lambda: p3_guion.ejecutar(proyecto, {"prompt_general": "prueba"},
                                            lambda v, m="": v),
                  "no contiene ningun json",
                  "agotados los reintentos, el paso falla con el motivo")
        finally:
            p3_guion.subprocess.Popen = original

        # SE ENTREGA EL MEJOR INTENTO, NO EL ULTIMO. Un reintento es una apuesta
        # y se puede perder: el 27-08-2026 la segunda pasada devolvio un guion
        # un 46 % mas largo que el de la primera, que estaba listo para grabar,
        # y se entrego el largo solo porque era el ultimo.
        bueno = {"titulo": "El bueno",
                 "bloques": [{"id": "B001", "texto": "uno " * 70},
                             {"id": "B002", "texto": "y en 1880 pasa esto"}]}
        peor = {"titulo": "El peor",
                "bloques": [{"id": "B001", "texto": "uno " * 900},
                            {"id": "B002", "texto": "y en 1880 pasa esto"}]}
        respuestas = [ProcesoFalso(0, sobre_cli(json.dumps(bueno))),
                      ProcesoFalso(0, sobre_cli(json.dumps(peor)))]
        p3_guion.subprocess.Popen = lambda *a, **k: respuestas.pop(0)
        try:
            salidas = p3_guion.ejecutar(proyecto, {"prompt_general": "prueba"},
                                        lambda v, m="": v)
        finally:
            p3_guion.subprocess.Popen = original
        igual(salidas["titulo"], "El bueno",
              "si el reintento vuelve peor, se entrega el intento anterior")
        igual(salidas["intentos"], 2, "sin mentir sobre cuantas llamadas se pagaron")
        comprobar(any("se entrega el intento 1 y no el 2" in a
                      for a in salidas["avisos"]),
                  "y se dice cual se ha entregado")

        # una llamada lenta no se reintenta: dos esperas largas seguidas es lo
        # que convertia un paso de un minuto en un paso de diez
        lentas = [ProcesoFalso(0, sobre_cli("esto no es JSON")),
                  ProcesoFalso(0, sobre_cli(json.dumps(
                      {"titulo": "No deberia llegar aqui",
                       "bloques": [{"id": "B001", "texto": "uno " * 70}]})))]

        def lenta(*a, **k):
            proceso = lentas.pop(0)
            proceso.communicate = _tardar(proceso)
            return proceso

        p3_guion.subprocess.Popen = lenta
        try:
            falla(lambda: p3_guion.ejecutar(
                proyecto, {"prompt_general": "prueba", "umbral_reintento_s": 1},
                lambda v, m="": v),
                "no contiene ningun json",
                "una llamada que tardo mas del umbral no se reintenta")
            igual(len(lentas), 1, "y por eso solo se llamo una vez al CLI")
        finally:
            p3_guion.subprocess.Popen = original
    finally:
        shutil.rmtree(base, ignore_errors=True)


# ------------------------------------------------------------------ CLI real

def preparar_proyecto(base, nombre, duracion=60):
    """Proyecto con ingesta simulada y brief real, listo para redactar."""
    proyecto = Proyecto.crear(base, nombre)
    estado = Estado(proyecto)

    trabajo = comun.preparar_trabajo(proyecto, "ingesta")
    transcript = [{"t_in": i * 4.0, "t_out": i * 4.0 + 4.0, "texto": t}
                  for i, t in enumerate(MATERIAL)]
    comun.escribir_json(os.path.join(trabajo, "ingesta.json"), {
        "transcript": transcript,
        "frames_utiles": [{"archivo": "retrato_f_0001.png", "tipo": "retrato"}],
        "video": "video.webm",
        "metadatos": {"titulo": "Rockefeller: el primer millonario",
                      "canal": "Canal de prueba", "url": "https://ejemplo/1",
                      "duracion_s": len(MATERIAL) * 4, "idioma_transcript": "en",
                      "palabras_transcript": sum(len(t.split()) for t in MATERIAL)},
    })
    estado.completar("ingesta", {"resumen": "ingesta simulada"})

    p2_brief.ejecutar(proyecto, {
        "instrucciones": "cuenta como se hizo rico, con las cifras concretas y "
                         "sin tecnicismos de contabilidad",
        "idioma_salida": "es", "duracion_objetivo_s": duracion}, lambda v, m="": v)
    estado.completar("brief", {"resumen": "brief de prueba"})
    return proyecto, estado


def prueba_real(base):
    print("\n[8] redaccion de verdad con el CLI de Claude")
    proyecto, estado = preparar_proyecto(base, "Guion Real")

    avisos = []
    print("  ... llamando al CLI (puede tardar medio minuto)")
    salidas = p3_guion.ejecutar(
        proyecto, {"prompt_general": "arranca por la cifra del noventa por ciento",
                   "regenerar_desde_cero": True},
        lambda valor, mensaje="": avisos.append((valor, mensaje)))

    igual(sorted(k for k in ("guion_fichero", "palabras", "titulo") if k in salidas),
          ["guion_fichero", "palabras", "titulo"],
          "las salidas traen las claves del contrato")
    comprobar(all(not isinstance(v, (list, dict)) or len(json.dumps(v)) < 4000
                  for v in salidas.values()),
              "ninguna salida es tan grande que el nucleo tenga que resumirla")

    trabajo = proyecto.ruta_trabajo("guion", crear=False)
    documento = leer_json(os.path.join(trabajo, salidas["guion_fichero"]))
    guion = documento["guion"]
    comprobar(len(guion) >= 2, f"el guion sale partido en {len(guion)} bloques")
    igual([b["id"] for b in guion], [f"B{n:03d}" for n in range(1, len(guion) + 1)],
          "los ids son B001, B002... en orden")
    # 'abre_seccion' viaja con cada bloque desde el 16-08: de el salen las
    # secciones con las que se graba la voz, y sin el aqui se perderia al
    # guardar el guion.
    comprobar(all(set(b) == {"id", "texto", "abre_seccion"} for b in guion),
              "cada bloque es exactamente {id, texto, abre_seccion}")
    comprobar(guion[0]["abre_seccion"] is True,
              "el primer bloque siempre abre seccion")
    comprobar(all(b["texto"].strip() for b in guion), "ningun bloque viene vacio")
    # Se cuenta lo que se LOCUTA. El guion sale con anotaciones de voz dentro
    # del texto (<break/>, <speed/>...) y esas no se dicen: contarlas inflaria
    # la horquilla y el modelo recortaria narracion de verdad para cuadrarla.
    igual(salidas["palabras"],
          sum(marcas_tts.contar_palabras(b["texto"]) for b in guion),
          "el recuento de palabras cuadra con el texto que se locuta")
    comprobar(salidas["palabras"] <= sum(len(b["texto"].split()) for b in guion),
              "y no cuenta las anotaciones de voz como palabras")
    comprobar(salidas["titulo"].strip(), f"trae titulo: {salidas['titulo']!r}")
    comprobar(salidas["dentro_de_horquilla"],
              f"{salidas['palabras']} palabras, dentro de la horquilla "
              f"{salidas['palabras_minimo']}-{salidas['palabras_maximo']}")
    comprobar(all(set(b) == {"id", "texto", "palabras"}
                  for b in documento["bloques_detalle"]),
              "el detalle de cada bloque es {id, texto, palabras} y nada mas")

    # `guion.es.txt` se fue con el eje de idiomas: con uno solo, `guion.txt` ES
    # el guion y un segundo fichero con lo mismo dentro solo puede desincronizarse.
    for nombre in ("guion.json", "guion.txt", "instruccion_1.txt",
                   "respuesta_instruccion_1.json"):
        comprobar(os.path.exists(os.path.join(trabajo, nombre)), f"deja {nombre}")
    with open(os.path.join(trabajo, "instruccion_1.txt"), "r", encoding="utf-8") as fh:
        instruccion = fh.read()
    comprobar("GUION ANTERIOR" not in instruccion,
              "con regenerar_desde_cero no se le pasa el guion previo")

    valores = [v for v, _ in avisos]
    comprobar(valores == sorted(valores) and valores[-1] == 1.0,
              "el progreso avanza y acaba en 1.0")
    tokens = salidas["tokens"]
    comprobar(set(tokens) == {"entrada", "salida", "cache"}
              and all(v >= 0 for v in tokens.values()),
              f"registra tokens y no dolares de Claude: {tokens}")

    print("\n[9] integracion con el nucleo y segunda iteracion")
    estado.completar("guion", salidas)
    igual(estado.estado_de("guion"), "listo", "tras completar queda listo")
    comprobar(os.path.exists(os.path.join(proyecto.ruta_paso("guion"), "guion.json")),
              "guion.json viajo a la version v1")

    print("  ... segunda llamada al CLI, ahora sobre el guion anterior")
    segundas = p3_guion.ejecutar(
        proyecto, {"prompt_general": "el mismo guion pero mas seco, sin adjetivos",
                   "regenerar_desde_cero": False}, lambda v, m="": v)
    trabajo = proyecto.ruta_trabajo("guion", crear=False)
    with open(os.path.join(trabajo, "instruccion_1.txt"), "r", encoding="utf-8") as fh:
        instruccion = fh.read()
    comprobar("GUION ANTERIOR" in instruccion, "la segunda pasada ve el guion anterior")
    comprobar(guion[0]["texto"] in instruccion,
              "el guion anterior viaja entero en la instruccion")
    nuevo = leer_json(os.path.join(trabajo, segundas["guion_fichero"]))["guion"]
    comprobar(nuevo and nuevo != guion, "la segunda pasada devuelve un guion distinto")

    numero = estado.completar("guion", segundas)
    igual(numero, 2, "se versiona como v2")
    with open(os.path.join(proyecto.ruta_paso("guion", 1), "guion.json"),
              "r", encoding="utf-8") as fh:
        igual(json.load(fh)["titulo"], salidas["titulo"], "v1 sigue intacta")


def principal():
    base = tempfile.mkdtemp(prefix="prueba_p3_")
    # el historico de tiempos de verdad no se toca: aqui los pasos corren
    # con el CLI sustituido por un doble y sus centesimas no miden nada
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(base, "estadisticas.json")
    conservar = "--conservar" in sys.argv
    try:
        prueba_params()
        prueba_parseo()
        prueba_bloques()
        prueba_aire()
        prueba_copias()
        prueba_instruccion()
        prueba_fallos_cli()
        prueba_reintento()
        # La redaccion REAL es opt-in, con el mismo flag que prueba_pasos_voz:
        # llama al CLI de verdad (red, medio minuto y varianza del modelo -- una
        # tirada salio de horquilla con 196 palabras sobre 179). La suite por
        # defecto es determinista y en seco.
        if "--con-claude" in sys.argv:
            prueba_real(base)
        else:
            print("\n[8] redaccion real omitida (pasa --con-claude para probarla)")
    finally:
        if conservar:
            print(f"\nproyectos temporales conservados en {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones:")
        for texto in FALLOS:
            print(f"  - {texto}")
        return 1
    print("P3 GUION OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
