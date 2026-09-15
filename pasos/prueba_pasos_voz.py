"""
Prueba de los pasos 4 (voz) y 5 (revision de audio).

Casi todo corre en modo simulado (ESTUDIO_SIMULAR=1): wav de silencio con marcas
sinteticas y reescritura local, para no gastar creditos de Cartesia ni del CLI de
Claude. Al final se hace UNA sola llamada real y corta a Cartesia para verificar
que el envoltorio con __experimental_controls habla de verdad con la API.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_pasos_voz.py
    ... --sin-red      solo simulado, no toca la red
    ... --con-claude   ademas, una reescritura real con el CLI (cuesta unos centimos)
"""
import json
import os
import shutil
import struct
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
sys.path.insert(0, AQUI)

from nucleo.estado import Estado  # noqa: E402
from nucleo.proyecto import Proyecto  # noqa: E402
from nucleo.trabajos import Cancelado, GestorTrabajos  # noqa: E402

import comun  # noqa: E402
import p4_voz  # noqa: E402
import p5_revision_audio as p5  # noqa: E402
import presets_voz  # noqa: E402

FALLOS = []
HECHAS = [0]

GUION = [
    {"id": "S01", "texto": "Octubre de 2007. Un carguero avanza en la oscuridad "
                           "del Pacifico rumbo a la costa mexicana."},
    {"id": "S02", "texto": "Nadie a bordo sabe que la bodega esconde veintitres "
                           "toneladas de precursores quimicos."},
    {"id": "S03", "texto": "Cuando la marina lo aborda, el capitan ya ha lanzado "
                           "los manifiestos por la borda."},
]


def comprobar(condicion, texto):
    """Registra el resultado de una comprobacion y sigue con las demas."""
    HECHAS[0] += 1
    if condicion:
        print(f"  ok   {texto}")
    else:
        print(f"  FALLO {texto}")
        FALLOS.append(texto)


def igual(obtenido, esperado, texto):
    comprobar(obtenido == esperado,
              texto if obtenido == esperado
              else f"{texto}  [obtenido={obtenido!r} esperado={esperado!r}]")


def falla(funcion, texto, tipo=Exception):
    HECHAS[0] += 1
    try:
        funcion()
    except tipo:
        print(f"  ok   {texto}")
        return
    except Exception as otro:
        print(f"  FALLO {texto}  [excepcion inesperada: {otro!r}]")
        FALLOS.append(texto)
        return
    print(f"  FALLO {texto}  [no fallo]")
    FALLOS.append(texto)


def duracion_wav(ruta):
    """Segundos de un wav PCM s16le mono leyendo la cabecera que escribimos."""
    with open(ruta, "rb") as fh:
        cabecera = fh.read(44)
        datos = os.path.getsize(ruta) - 44
    canales, ritmo = struct.unpack("<H", cabecera[22:24])[0], struct.unpack("<I", cabecera[24:28])[0]
    return datos / float(ritmo * canales * 2), cabecera


def energia_wav(ruta):
    """Suma de valores absolutos del PCM: 0 en un silencio puro."""
    with open(ruta, "rb") as fh:
        fh.seek(44)
        crudo = fh.read()
    muestras = struct.unpack(f"<{len(crudo) // 2}h", crudo[:len(crudo) // 2 * 2])
    return sum(abs(m) for m in muestras)


# ------------------------------------------------------------------- presets

def prueba_presets():
    print("\n[1] presets de voz")
    comprobar(len(presets_voz.PRESETS) >= 6,
              f"hay al menos 6 presets (hay {len(presets_voz.PRESETS)})")
    claves = {"nombre", "descripcion", "modelo", "velocidad", "emociones",
              "hueco_minimo", "voces_sugeridas"}
    for identificador, preset in presets_voz.PRESETS.items():
        comprobar(claves.issubset(preset), f"{identificador} tiene todas las claves")
        comprobar(preset["modelo"] in p4_voz.MODELOS,
                  f"{identificador} usa un modelo valido ({preset['modelo']})")
        comprobar(p4_voz.normalizar_velocidad(preset["velocidad"]) is not None,
                  f"{identificador} tiene velocidad valida")
        try:
            limpias = p4_voz.normalizar_emociones(preset["emociones"])
            comprobar(limpias == list(preset["emociones"]),
                      f"{identificador} usa etiquetas de emocion validas")
        except ValueError as fallo:
            comprobar(False, f"{identificador} emociones invalidas: {fallo}")
        comprobar(isinstance(preset["hueco_minimo"], float)
                  and preset["hueco_minimo"] >= 0,
                  f"{identificador} tiene hueco_minimo numerico")
        comprobar(len(preset["voces_sugeridas"]) >= 1
                  and all(isinstance(v, str) and len(v) == 36
                          for v in preset["voces_sugeridas"]),
                  f"{identificador} sugiere ids de voz con forma de uuid")

    perfiles = {p: (presets_voz.PRESETS[p]["velocidad"],
                    tuple(presets_voz.PRESETS[p]["emociones"]))
                for p in presets_voz.PRESETS}
    igual(len(set(perfiles.values())), len(perfiles),
          "ningun preset es un duplicado de otro")
    igual(len(presets_voz.listar()), len(presets_voz.PRESETS), "listar() los devuelve todos")
    falla(lambda: presets_voz.preset("no_existe"), "preset desconocido falla claro",
          ValueError)


def prueba_controles():
    print("\n[2] controles experimentales")
    igual(p4_voz.construir_controles("slow", ["curiosity:high", "sadness:low"]),
          {"speed": "slow", "emotion": ["curiosity:high", "sadness:low"]},
          "construye speed + emotion")
    igual(p4_voz.construir_controles(None, None), {}, "sin controles, dict vacio")
    igual(p4_voz.construir_controles(-0.4, "anger"),
          {"speed": -0.4, "emotion": ["anger"]}, "acepta velocidad numerica")
    igual(p4_voz.normalizar_emociones(["anger", "anger"]), ["anger"],
          "no repite etiquetas")
    falla(lambda: p4_voz.normalizar_emociones(["melancolia"]),
          "rechaza una emocion inventada", ValueError)
    falla(lambda: p4_voz.normalizar_emociones(["surprise:medium"]),
          "rechaza un nivel inventado", ValueError)
    falla(lambda: p4_voz.normalizar_velocidad("volando"),
          "rechaza una velocidad inventada", ValueError)
    falla(lambda: p4_voz.normalizar_velocidad(3.0),
          "rechaza velocidad numerica fuera de rango", ValueError)

    cfg = p4_voz.resolver_params({"preset": "true_crime_tenso"})
    igual(cfg["velocidad"], "slow", "el preset fija la velocidad")
    igual(cfg["emociones"], ["curiosity:high", "sadness:low"],
          "el preset fija las emociones")
    igual(cfg["voz_id"], presets_voz.PRESETS["true_crime_tenso"]["voces_sugeridas"][0],
          "el preset propone su primera voz")
    cfg = p4_voz.resolver_params({"preset": "true_crime_tenso", "velocidad": "fast",
                                  "voz_id": "x" * 36})
    igual(cfg["velocidad"], "fast", "lo fijado a mano gana al preset")
    igual(cfg["voz_id"], "x" * 36, "la voz elegida a mano gana al preset")
    falla(lambda: p4_voz.resolver_params({"modelo": "sonic-9"}),
          "rechaza un modelo desconocido", ValueError)


def prueba_lectura_guion(base):
    print("\n[3] lectura del guion")
    proyecto = Proyecto.crear(base, "Lectura Guion")
    estado = Estado(proyecto)

    falla(lambda: p4_voz.cargar_guion(proyecto), "sin guion, error explicito",
          RuntimeError)

    estado.set_params("guion", {"tono": "seco", "unidades": {
        "S02": {"texto": GUION[1]["texto"]},
        "S01": {"texto": GUION[0]["texto"]},
    }})
    bloques = p4_voz.cargar_guion(proyecto)
    igual([b["id"] for b in bloques], ["S01", "S02"],
          "lee las unidades del paso guion y las ordena")

    carpeta = proyecto.ruta_paso("guion", 1, crear=True)
    proyecto.fijar_version_activa("guion", 1)
    # forma exacta del guion.json que escribe el paso 3
    with open(os.path.join(carpeta, "guion.json"), "w", encoding="utf-8") as fh:
        json.dump({"titulo": "Caso Meridiano", "guion": GUION, "palabras": 40,
                   "bloques_detalle": [dict(b, palabras=7) for b in GUION]},
                  fh, ensure_ascii=False)
    bloques = p4_voz.cargar_guion(proyecto)
    igual([b["id"] for b in bloques], ["S01", "S02", "S03"],
          "lee el guion.json que deja el paso 3 y manda sobre las unidades")
    igual(bloques[0]["texto"], GUION[0]["texto"], "el texto llega intacto")

    igual([b["id"] for b in p4_voz.cargar_guion(proyecto, {"bloques": GUION[:1]})],
          ["S01"], "los params ganan a todo lo demas")
    igual([b["texto"] for b in p4_voz.normalizar_bloques(
        {"escenas": [{"id": "S01", "narracion": "Hola."}]})],
        ["Hola."], "entiende escenas/narracion del formato del plan")
    igual(len(p4_voz.normalizar_bloques("Uno.\n\nDos.")), 2,
          "entiende un guion en texto plano separado por lineas en blanco")
    igual(p4_voz.normalizar_bloques({"titulo": "Caso Meridiano", "modelo": "sonnet"}),
          [], "un documento cualquiera no se cuela como guion")
    igual([b["id"] for b in p4_voz.normalizar_bloques(
        {"B001": "Uno.", "B002": {"texto": "Dos."}})],
        ["B001", "B002"], "acepta el mapa de unidades con texto suelto o en dict")

    # LO EDITADO A MANO LLEGA AL AUDIO. `params.guion.bloques` es el cajon donde
    # la pantalla guarda lo que una persona reescribe de un bloque, y hasta el
    # 24-08 lo aplicaba SOLO p3_guion al redactar: corregir una frase y darle a
    # grabar locutaba la frase VIEJA, y la unica forma de que llegara era volver
    # a pedirle el guion entero al modelo.
    estado.set_params("guion", {"bloques": {
        "S02": {"texto": "Esto lo he escrito yo."},
        "S99": {"texto": "un bloque que ya no existe"},
    }})
    bloques = p4_voz.cargar_guion(proyecto)
    porid = {b["id"]: b["texto"] for b in bloques}
    igual(porid.get("S02"), "Esto lo he escrito yo.",
          "la edicion a mano manda sobre el guion.json")
    igual(porid.get("S01"), GUION[0]["texto"],
          "y los bloques que nadie ha tocado se quedan como estaban")
    comprobar("S99" not in porid,
              "una edicion de un guion anterior se ignora en silencio: no es un error")
    # Lo que llega por params SI gana a la edicion: ahi hay un guion explicito
    # (una prueba, o la reescritura del paso 5) y pisarlo seria contestar otra
    # cosa a lo que se pide.
    igual([b["texto"] for b in p4_voz.cargar_guion(proyecto, {"bloques": GUION[1:2]})],
          [GUION[1]["texto"]], "un guion explicito en params gana a la edicion")
    estado.set_params("guion", {"bloques": {}})

    # El idioma de la voz sale del brief. Sin esto, un guion escrito en ingles se
    # locutaba en espanol y no fallaba: lo leia con acento y no lo decia nadie.
    igual(p4_voz.idioma_de_salida(proyecto), "", "sin brief no se inventa idioma")
    igual(p4_voz.params_con_idioma(proyecto, {}), {},
          "sin brief, los params se quedan como estaban")
    estado.set_params("brief", {"idiomas_salida": ["en", "es"]})
    igual(p4_voz.idioma_de_salida(proyecto), "en",
          "hereda el idioma principal del brief")
    igual(p4_voz.params_con_idioma(proyecto, {})["idioma"], "en",
          "el idioma vacio se rellena con el del video")
    igual(p4_voz.params_con_idioma(proyecto, {"idioma": "es"})["idioma"], "es",
          "el idioma fijado a mano manda sobre el del video")
    igual(p4_voz.resolver_params(p4_voz.params_con_idioma(proyecto, {}))["idioma"],
          "en", "y llega hasta la configuracion con la que se sintetiza")
    shutil.rmtree(proyecto.raiz)


# --------------------------------------------------------------------- paso 4

def preparar_proyecto(base, nombre="Caso Meridiano"):
    proyecto = Proyecto.crear(base, nombre)
    estado = Estado(proyecto)
    estado.set_params("ingesta", {"url": "https://ejemplo/1"})
    estado.completar("ingesta", {"frames": 0})
    estado.set_params("brief", {"angulo": "seco"})
    estado.completar("brief", {"ok": True})
    estado.set_params("guion", {"unidades": {b["id"]: {"texto": b["texto"]}
                                             for b in GUION}})
    carpeta = proyecto.ruta_trabajo("guion")
    with open(os.path.join(carpeta, "guion.json"), "w", encoding="utf-8") as fh:
        json.dump({"titulo": "Caso Meridiano", "guion": GUION}, fh, ensure_ascii=False)
    estado.completar("guion", {"guion": GUION, "bloques": len(GUION)})
    return proyecto, estado


def prueba_paso4(base):
    print("\n[4] paso 4: voz (simulado)")
    proyecto, estado = preparar_proyecto(base)
    params = {"preset": "documental_sobrio", "hueco_minimo": 1.0,
              "emociones": ["curiosity:low"]}
    estado.set_params("voz", params)
    igual(estado.estado_de("voz"), "pendiente", "voz pendiente tras el guion")

    trazas = []
    salidas = p4_voz.ejecutar(proyecto, params,
                              lambda v, m="": trazas.append((v, m)))

    for clave in ("pista", "duracion", "palabras", "controles"):
        comprobar(clave in salidas, f"salidas trae {clave}")
    comprobar(os.path.exists(salidas["pista"]), "la pista existe en disco")
    segundos, cabecera = duracion_wav(salidas["pista"])
    comprobar(cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WAVE",
              "la pista es un wav valido")
    comprobar(abs(segundos - salidas["duracion"]) < 0.25,
              f"la duracion declarada cuadra con el wav ({segundos:.2f}s)")
    comprobar(salidas["duracion"] > 5, "la toma dura mas de 5 segundos")

    esperadas = sum(len(b["texto"].split()) for b in GUION)
    igual(len(salidas["palabras"]), esperadas,
          "hay una marca por palabra del guion")
    marcas = salidas["palabras"]
    comprobar(all(marcas[i]["e"] <= marcas[i + 1]["s"] + 1e-6
                  for i in range(len(marcas) - 1)),
              "las marcas van en orden y no se solapan")
    comprobar(marcas[-1]["e"] <= salidas["duracion"] + 0.5,
              "la ultima marca cae dentro de la pista")

    igual([b["id"] for b in salidas["bloques"]], ["S01", "S02", "S03"],
          "cada bloque recibe su tramo")
    huecos = [salidas["bloques"][i + 1]["t_in"] - salidas["bloques"][i]["t_out"]
              for i in range(len(salidas["bloques"]) - 1)]
    comprobar(all(h >= 0.99 for h in huecos),
              f"se respeta hueco_minimo=1.0 entre bloques ({[round(h, 2) for h in huecos]})")

    igual(salidas["controles"]["emociones"], ["curiosity:low"],
          "las emociones de los params llegan a los controles")
    igual(salidas["controles"]["experimental_controls"],
          {"speed": "slow", "emotion": ["curiosity:low"]},
          "el bloque __experimental_controls sale montado")
    comprobar(trazas and trazas[-1][0] == 1.0, "el progreso termina en 1.0")

    meta = os.path.join(os.path.dirname(salidas["pista"]), "audio_meta.json")
    comprobar(os.path.exists(meta), "deja audio_meta.json junto a la pista")

    numero = estado.completar("voz", salidas)
    igual(estado.estado_de("voz"), "listo", "el paso queda listo tras completar")
    final = os.path.join(proyecto.ruta_paso("voz"), salidas["archivo"])
    comprobar(os.path.exists(final), f"la pista viaja a la version v{numero}")
    igual(p4_voz.ruta_pista(proyecto, salidas), final,
          "ruta_pista resuelve la pista ya versionada")
    return proyecto, estado, salidas


def prueba_previsualizacion(proyecto):
    print("\n[5] previsualizacion")
    params = {"preset": "divulgacion_cercana"}
    ruta = p4_voz.previsualizar(proyecto, params, segundos=8)
    comprobar(os.path.exists(ruta), "escribe el wav de previsualizacion")
    segundos, _ = duracion_wav(ruta)
    comprobar(3 <= segundos <= 14, f"dura del orden de 8s ({segundos:.2f}s)")
    comprobar(os.path.dirname(ruta).endswith("previsualizaciones"),
              "no ensucia la carpeta de trabajo del paso")
    marca = os.path.getmtime(ruta)
    igual(p4_voz.previsualizar(proyecto, params, segundos=8), ruta,
          "la segunda llamada reutiliza el wav cacheado")
    igual(os.path.getmtime(ruta), marca, "y no lo vuelve a sintetizar")

    texto = p4_voz.recortar_texto(GUION, 8, "slow")
    comprobar(texto.endswith((".", "!", "?")), "el recorte acaba en final de frase")
    comprobar(len(texto.split()) < sum(len(b["texto"].split()) for b in GUION),
              "el recorte es mas corto que el guion entero")


def prueba_trabajo_en_segundo_plano(base):
    print("\n[6] paso 4 dentro del gestor de trabajos")
    proyecto, estado = preparar_proyecto(base, "Con Gestor")
    gestor = GestorTrabajos(estado=estado)
    trabajo = gestor.lanzar("voz", lambda avisar: p4_voz.ejecutar(
        proyecto, {"preset": "testimonio_seco"}, avisar), paso="voz")
    ficha = gestor.esperar(trabajo, 120)
    igual(ficha["estado"], "listo", "el trabajo termina bien")
    comprobar(ficha["resultado"] and ficha["resultado"].get("duracion", 0) > 0,
              "el trabajo devuelve las salidas")
    estado.completar("voz", ficha["resultado"])
    igual(estado.estado_de("voz"), "listo", "el grafo queda coherente")

    def cortar(valor, mensaje=""):
        if valor > 0.03:
            raise Cancelado("cancelado a mitad")
        return valor

    falla(lambda: p4_voz.ejecutar(proyecto, {"preset": "testimonio_seco"}, cortar),
          "la cancelacion cooperativa sale del paso, no se traga", Cancelado)
    shutil.rmtree(proyecto.raiz)


# --------------------------------------------------------------------- paso 5

def prueba_paso5(proyecto, estado, salidas_voz):
    print("\n[7] paso 5: revision de audio (simulado)")
    texto_s02 = GUION[1]["texto"]
    fragmento = "veintitres toneladas de precursores quimicos"
    inicio = texto_s02.find(fragmento)
    comentarios = [
        {"id": "C1", "bloque_id": "S02", "inicio_char": inicio,
         "fin_char": inicio + len(fragmento),
         "texto_seleccionado": fragmento,
         "comentario": "veintitres toneladas de efedrina"},
        {"id": "C2", "bloque_id": "S03", "inicio_char": 0, "fin_char": 0,
         "texto_seleccionado": "",
         "comentario": "acorta esto, se hace largo"},
    ]
    estado.set_params("revision_audio", {"comentarios": comentarios})
    igual(estado.estado_de("revision_audio"), "pendiente",
          "revision_audio pendiente con la voz lista")

    trazas = []
    salidas = p5.ejecutar(proyecto, {"comentarios": comentarios},
                          lambda v, m="": trazas.append((v, m)))

    igual(sorted(salidas["bloques_modificados"]), ["S02", "S03"],
          "solo se marcan los bloques comentados")
    textos = {b["id"]: b["texto"] for b in salidas["bloques"]}
    igual(textos["S01"], GUION[0]["texto"], "el bloque sin comentarios no se toca")
    comprobar("efedrina" in textos["S02"],
              "el comentario con offsets reescribe el fragmento seleccionado")
    comprobar("precursores" not in textos["S02"],
              "y el texto original del fragmento desaparece")
    comprobar(len(textos["S03"]) < len(GUION[2]["texto"]),
              "el comentario de acortar deja el bloque mas corto")

    for clave in ("pista", "duracion", "palabras", "controles",
                  "bloques_modificados"):
        comprobar(clave in salidas, f"salidas trae {clave}")
    comprobar(os.path.exists(salidas["pista"]), "regraba la pista completa")
    comprobar(salidas["pista"] != salidas_voz["pista"],
              "la pista nueva no pisa la del paso 4")
    esperadas = sum(len(t.split()) for t in textos.values())
    igual(len(salidas["palabras"]), esperadas,
          "las marcas corresponden al guion reescrito, no al viejo")
    igual(salidas["controles"]["voz_id"], salidas_voz["controles"]["voz_id"],
          "hereda la voz del paso 4")
    igual(salidas["controles"]["emociones"], salidas_voz["controles"]["emociones"],
          "hereda las emociones del paso 4")
    comprobar(all(c["ok"] for c in salidas["cambios"]),
              "ninguna reescritura queda en aviso")
    igual(salidas["avisos"], [], "sin avisos con comentarios bien formados")

    carpeta = os.path.dirname(salidas["pista"])
    comprobar(os.path.exists(os.path.join(carpeta, "guion_revisado.json")),
              "deja el guion revisado en disco")
    estado.completar("revision_audio", salidas)
    igual(estado.estado_de("revision_audio"), "listo", "el paso 5 queda listo")

    print("\n[8] paso 5: casos de borde")
    # Sin comentarios el paso reescribe cero bloques, asi que su resultado ES la
    # toma del paso 4: se sella copiandola, no pagando otra sintesis. Es el
    # boton de "esta bien asi" de la interfaz.
    vacio = p5.ejecutar(proyecto, {"comentarios": []})
    igual(vacio["bloques_modificados"], [],
          "sin comentarios no cambia ningun bloque")
    comprobar(vacio["duracion"] > 0, "y la toma sigue estando entera")
    comprobar(vacio.get("sellada_del_paso_4") is True,
              "sin comentarios se sella la toma del paso 4, no se regraba")
    igual(vacio["duracion"], salidas_voz["duracion"],
          "la toma sellada dura exactamente lo que la del paso 4")
    comprobar(os.path.exists(vacio["pista"]) and vacio["pista"] != salidas_voz["pista"],
              "pero la pista se copia a la carpeta del paso 5, no se referencia")
    igual([b["texto"] for b in vacio["bloques"]],
          [b["texto"] for b in salidas_voz["bloques"]],
          "y el texto sellado es el que se locuto")

    # Si alguien cambia la voz, sellar seria mentir: hay que regrabar.
    otra_voz = p5.ejecutar(proyecto, {"comentarios": [],
                                      "voz": {"velocidad": "slowest"}})
    comprobar(not otra_voz.get("sellada_del_paso_4"),
              "con otros controles de voz no se sella: se vuelve a grabar")
    igual(otra_voz["controles"]["velocidad"], "slowest",
          "y la toma nueva usa los controles pedidos")

    sueltos = p5.ejecutar(proyecto, {"comentarios": [
        {"id": "C9", "bloque_id": "S99", "comentario": "esto no existe"}]})
    comprobar(any("S99" in a for a in sueltos["avisos"]),
              "avisa de un comentario sobre un bloque inexistente")

    desfasado = {"id": "C8", "bloque_id": "S01", "inicio_char": 5, "fin_char": 9,
                 "texto_seleccionado": "carguero", "comentario": "quita esto"}
    inicio, fin = p5.localizar(GUION[0]["texto"], desfasado)
    igual(GUION[0]["texto"][inicio:fin], "carguero",
          "si los offsets mienten, se busca el fragmento seleccionado")
    igual(p5.localizar(GUION[0]["texto"],
                       {"texto_seleccionado": "no esta", "inicio_char": None,
                        "fin_char": None})[0], None,
          "si el fragmento no aparece, la nota es para el bloque entero")

    igual(p5._limpiar_respuesta("```\nAqui tienes:\nTexto final.\n```"),
          "Texto final.", "limpia fences y preambulos de la respuesta del CLI")


def prueba_regrabacion_completa(proyecto):
    print("\n[9] la toma se regraba entera, nunca se empalma")
    comentario = [{"id": "C1", "bloque_id": "S01",
                   "texto_seleccionado": "Octubre de 2007.",
                   "inicio_char": 0, "fin_char": len("Octubre de 2007."),
                   "comentario": "Noviembre de 2007."}]
    salidas = p5.ejecutar(proyecto, {"comentarios": comentario})
    tramos = {b["id"]: (b["t_in"], b["t_out"]) for b in salidas["bloques"]}
    comprobar(tramos["S01"][0] < tramos["S02"][0] < tramos["S03"][0],
              "los tres bloques vienen de la misma toma, en orden")
    comprobar(all(t[0] is not None and t[1] is not None for t in tramos.values()),
              "ningun bloque se queda sin tramo tras la reescritura")
    palabras = salidas["palabras"]
    igual(len(palabras), sum(b["palabras"] for b in salidas["bloques"]),
          "todas las marcas estan asignadas a algun bloque")


# ------------------------------------------------------------------- con red

def prueba_cache_por_clave():
    """EL CACHE SABE CON QUE CLAVE SE BAJO (06-09-2026).

    Se cambio la clave de Cartesia por la de la cuenta donde vive la voz clonada
    del canal, y el desplegable siguio diciendo «no hay voces clonadas en esta
    cuenta»: el catalogo cacheado --934 voces bajadas con la clave anterior--
    todavia estaba dentro de sus siete dias. No fallaba nada, no habia nada que
    mirar y la pantalla mentia. Iba a durar una semana.

    Sin red: se sustituye la descarga por una que cuenta cuantas veces la
    llaman, que es exactamente lo que hay que comprobar. Y se sustituye tambien
    `_hay_clave`, porque sin clave `listar_voces` no llega a pedir nada -- eso
    es lo correcto y lo prueba `prueba_catalogo_voces`, pero aqui lo que se mira
    es lo de DESPUES: que con clave puesta, el cache se invalide al cambiarla.
    """
    print("\n[10b] el cache de voces se invalida al cambiar de clave")
    bajadas = [0]
    real_descargar, real_huella = p4_voz._descargar_voces, p4_voz._huella_clave
    real_hay = p4_voz._hay_clave
    guardado = None
    if os.path.exists(p4_voz.RUTA_CACHE_VOCES):
        with open(p4_voz.RUTA_CACHE_VOCES, "r", encoding="utf-8") as fh:
            guardado = fh.read()

    def falsa():
        bajadas[0] += 1
        return [{"id": "v1", "nombre": "Una", "idioma": "es", "nativa": True,
                 "publica": False, "descripcion": ""}]

    # SIN SIMULADO, pero tampoco con red: la descarga esta sustituida. En
    # simulado `listar_voces` sirve lo cacheado sin mirar la clave, que es otro
    # camino y no el que se esta comprobando.
    simular = os.environ.get("ESTUDIO_SIMULAR")
    try:
        os.environ["ESTUDIO_SIMULAR"] = "0"
        p4_voz._descargar_voces = falsa
        p4_voz._hay_clave = lambda: True
        p4_voz._huella_clave = lambda: "clave_A"
        p4_voz.listar_voces("es")
        igual(bajadas[0], 1, "un cache bajado con OTRA clave no vale: se baja")
        p4_voz.listar_voces("es")
        igual(bajadas[0], 1, "y con cache de la MISMA clave no se vuelve a bajar")

        p4_voz._huella_clave = lambda: "clave_B"
        p4_voz.listar_voces("es")
        igual(bajadas[0], 2, "al cambiar de clave se baja otra vez, sin esperar "
                             "a que caduquen los siete dias")

        # Un cache de antes de esta fecha no lleva huella: se refresca una vez.
        with open(p4_voz.RUTA_CACHE_VOCES, "r", encoding="utf-8") as fh:
            viejo = json.load(fh)
        viejo.pop("clave", None)
        with open(p4_voz.RUTA_CACHE_VOCES, "w", encoding="utf-8") as fh:
            json.dump(viejo, fh)
        p4_voz.listar_voces("es")
        igual(bajadas[0], 3, "un cache sin huella (de antes del 06-09) se "
                             "refresca una vez y ya la tiene")

        # Y SI NO SE PUEDE SABER QUE CLAVE HAY, la huella no opina: lo cacheado
        # es mejor que nada. Sin esto, una maquina sin clave configurada
        # intentaria bajar el catalogo en cada peticion, y fallando.
        p4_voz._huella_clave = lambda: ""
        p4_voz.listar_voces("es")
        igual(bajadas[0], 3, "sin clave legible se sirve lo cacheado y no se "
                             "pide nada")
    finally:
        if simular is None:
            os.environ.pop("ESTUDIO_SIMULAR", None)
        else:
            os.environ["ESTUDIO_SIMULAR"] = simular
        p4_voz._descargar_voces, p4_voz._huella_clave = real_descargar, real_huella
        p4_voz._hay_clave = real_hay
        if guardado is None:
            if os.path.exists(p4_voz.RUTA_CACHE_VOCES):
                os.remove(p4_voz.RUTA_CACHE_VOCES)
        else:
            with open(p4_voz.RUTA_CACHE_VOCES, "w", encoding="utf-8") as fh:
                fh.write(guardado)


def prueba_catalogo_voces(con_red):
    print("\n[10] catalogo de voces")
    if not con_red:
        voces = p4_voz.listar_voces("es")
        comprobar(isinstance(voces, list) and voces,
                  "en simulado devuelve el catalogo minimo o el cacheado")
        return
    os.environ["ESTUDIO_SIMULAR"] = "0"
    try:
        voces = p4_voz.listar_voces("es", refrescar=True)
    finally:
        os.environ["ESTUDIO_SIMULAR"] = "1"
    comprobar(len(voces) > 20, f"lista voces en espanol ({len(voces)})")
    comprobar(all(v["id"] and v["nombre"] for v in voces),
              "cada ficha trae id y nombre")
    comprobar(os.path.exists(p4_voz.RUTA_CACHE_VOCES), "cachea el catalogo en disco")

    todas = p4_voz.listar_voces()
    comprobar(len(todas) > len(voces), f"sin filtro salen mas ({len(todas)})")
    catalogo = {v["id"] for v in todas}
    faltan = [i for p in presets_voz.PRESETS.values()
              for i in p["voces_sugeridas"] if i not in catalogo]
    igual(faltan, [], "todas las voces sugeridas por los presets existen")

    nativas = p4_voz.listar_voces("es", solo_nativas=True)
    comprobar(0 < len(nativas) <= len(voces),
              f"solo_nativas recorta el catalogo ({len(nativas)} de {len(voces)})")
    comprobar(all(v["nativa"] for v in nativas), "y todas son nativas")
    # El ORDEN es lo que se comprueba, no que existan las dos clases: el
    # 21-08-2026 Cartesia devolvia 78 voces en castellano y las 78 nativas, asi
    # que exigir una prestada al final era exigir que su catalogo no mejorara.
    orden_nativas = [bool(v["nativa"]) for v in voces]
    comprobar(orden_nativas == sorted(orden_nativas, reverse=True),
              f"las nativas van primero y las prestadas al final "
              f"({sum(orden_nativas)} nativas de {len(voces)})")
    sugeridas = {v["id"] for v in nativas}
    prestadas = [i for p in presets_voz.PRESETS.values()
                 for i in p["voces_sugeridas"] if i not in sugeridas]
    igual(prestadas, [], "los presets solo proponen voces nativas en espanol")


def prueba_llamada_real(base):
    print("\n[11] UNA llamada real y corta a Cartesia")
    os.environ["ESTUDIO_SIMULAR"] = "0"
    try:
        proyecto = Proyecto.crear(base, "Llamada Real")
        corto = [{"id": "S01", "texto": "Octubre de dos mil siete."},
                 {"id": "S02", "texto": "El carguero ya no responde."}]
        params = {"preset": "true_crime_tenso", "bloques": corto,
                  "hueco_minimo": 0.6}
        salidas = p4_voz.ejecutar(proyecto, params)
    finally:
        os.environ["ESTUDIO_SIMULAR"] = "1"

    comprobar(not salidas["simulado"], "la toma no es simulada")
    comprobar(os.path.exists(salidas["pista"]), "Cartesia devuelve audio")
    segundos, cabecera = duracion_wav(salidas["pista"])
    comprobar(cabecera[:4] == b"RIFF", "el wav real tiene cabecera valida")
    comprobar(2 < segundos < 20, f"dura lo esperable ({segundos:.2f}s)")
    comprobar(energia_wav(salidas["pista"]) > 0, "el audio no es silencio")
    igual(len(salidas["palabras"]),
          sum(len(b["texto"].split()) for b in corto),
          "Cartesia devuelve una marca por palabra")
    comprobar(salidas["palabras"][0]["e"] > salidas["palabras"][0]["s"],
              "las marcas reales tienen duracion")
    huecos = salidas["bloques"][1]["t_in"] - salidas["bloques"][0]["t_out"]
    comprobar(huecos >= 0.59, f"el aire entre bloques se aplica al audio real ({huecos:.2f}s)")
    igual(salidas["controles"]["experimental_controls"],
          {"speed": "slow", "emotion": ["curiosity:high", "sadness:low"]},
          "se enviaron los controles del preset")
    print(f"       pista real: {salidas['pista']}")
    shutil.rmtree(proyecto.raiz, ignore_errors=True)


def prueba_reescritura_real():
    print("\n[12] reescritura real con el CLI de Claude")
    os.environ["ESTUDIO_SIMULAR"] = "0"
    cwd = tempfile.mkdtemp(prefix="estudio_cli_")
    try:
        bloque = dict(GUION[0])
        comentario = [{"id": "C1", "bloque_id": "S01", "inicio_char": 0,
                       "fin_char": len("Octubre de 2007."),
                       "texto_seleccionado": "Octubre de 2007.",
                       "comentario": "cambia la fecha a marzo de 2011"}]
        nuevo, aviso, sobre = p5.reescribir_bloque(bloque, comentario, cwd=cwd)
    finally:
        os.environ["ESTUDIO_SIMULAR"] = "1"
        shutil.rmtree(cwd, ignore_errors=True)
    igual(aviso, "", "el CLI responde sin avisos")
    comprobar("2011" in nuevo, f"aplica la nota al fragmento ({nuevo[:60]}...)")
    comprobar("2007" not in nuevo, "y quita lo que habia")
    comprobar("carguero" in nuevo, "no toca lo que nadie comento")
    comprobar(sobre.get("total_cost_usd") is not None, "registra el coste")


def _hay_clave_cartesia():
    """Si esta maquina puede hablar con Cartesia. -> bool

    Se pregunta al MOTOR, que es quien sabe de donde puede salir la clave (el
    entorno, el almacen que escribe Configuracion, un .env). Repetir esa busqueda
    aqui seria una segunda version que se queda vieja el dia que cambie la
    primera.
    """
    try:
        motor = comun.cargar_motor("voz_cartesia", "voz.py")
        return bool(motor.cargar_api_key())
    except BaseException:                                     # noqa: BLE001
        # `cargar_api_key` aborta con SystemExit --esta escrito como CLI-- y eso
        # no lo captura un `except Exception`
        return False


def main():
    con_red = "--sin-red" not in sys.argv
    con_claude = "--con-claude" in sys.argv
    # SIN CLAVE DE CARTESIA NO SE SALE A LA RED, y no es un fallo: es una suite
    # que no puede correr esa parte en esta maquina. Antes moria con el
    # SystemExit del motor --«No encuentro CARTESIA_API_KEY»-- y en la tanda
    # entera eso se leia igual que un rojo de verdad.
    if con_red and not _hay_clave_cartesia():
        con_red = False
        print("(sin CARTESIA_API_KEY: se omite lo que sale a la red. Ponla en "
              "Configuracion para probar el catalogo y una toma real)")
    os.environ["ESTUDIO_SIMULAR"] = "1"
    base = tempfile.mkdtemp(prefix="estudio_voz_")
    # EL HISTORICO, A UNA COPIA. Esta suite sale a Cartesia de verdad con frases
    # de DIEZ palabras y anota su cadencia: en el historico real esas muestras
    # decian 2,7 palabras/s en castellano --mas rapido que el ingles medido-- y
    # con ellas dentro pedir la voz 'slow' salia MAS rapida que 'normal'.
    # `cadencia.PALABRAS_MINIMAS_MEDIDA` lo defiende; esto lo evita de raiz.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(base, "estadisticas.json")
    print(f"proyectos de prueba en {base}")
    try:
        prueba_presets()
        prueba_controles()
        prueba_lectura_guion(base)
        proyecto, estado, salidas = prueba_paso4(base)
        prueba_previsualizacion(proyecto)
        prueba_trabajo_en_segundo_plano(base)
        prueba_paso5(proyecto, estado, salidas)
        prueba_regrabacion_completa(proyecto)
        prueba_cache_por_clave()
        prueba_catalogo_voces(con_red)
        if con_red:
            prueba_llamada_real(base)
        else:
            print("\n[11] llamada real omitida (--sin-red)")
        if con_claude:
            prueba_reescritura_real()
        else:
            print("\n[12] reescritura real omitida (pasa --con-claude para probarla)")
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print()
    if FALLOS:
        print(f"PASOS 4 Y 5: {len(FALLOS)} de {HECHAS[0]} comprobaciones fallan")
        for texto in FALLOS:
            print(f"  - {texto}")
        return 1
    print(f"PASOS 4 Y 5 OK: {HECHAS[0]} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
