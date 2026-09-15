"""
Prueba del paso 2 (brief).

El paso no llama a ningun modelo, asi que la prueba es completa y rapida:
normalizacion de idiomas, presupuesto de palabras, validaciones, avisos contra
el material de la ingesta e integracion con el nucleo.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_p2.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import comun
import p2_brief
from nucleo import Estado, Proyecto

FALLOS = []


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


def falla(funcion, texto):
    try:
        funcion()
    except ValueError as fallo:
        comprobar(bool(str(fallo)), f"{texto} -> ValueError: {fallo}")
        return
    comprobar(False, f"{texto} (no fallo)")


def sin_progreso(valor, mensaje=""):
    return valor


def fabricar_ingesta(proyecto, estado, palabras=700, duracion=300, idioma="en"):
    """Deja una version de ingesta creible sin correr el paso 1."""
    trabajo = comun.preparar_trabajo(proyecto, "ingesta")
    frase = "the refinery bought every barrel that reached the river docks"
    por_frase = len(frase.split())
    entradas = max(1, palabras // por_frase)
    paso = duracion / entradas
    transcript = [{"t_in": round(i * paso, 2), "t_out": round((i + 1) * paso, 2),
                   "texto": frase} for i in range(entradas)]
    comun.escribir_json(os.path.join(trabajo, "ingesta.json"), {
        "transcript": transcript,
        "frames_utiles": [],
        "video": "video.webm",
        "metadatos": {"titulo": "Video de referencia", "url": "https://ejemplo/1",
                      "duracion_s": duracion, "idioma_transcript": idioma,
                      "palabras_transcript": entradas * por_frase},
    })
    estado.completar("ingesta", {"resumen": "ingesta simulada"})


def prueba_idiomas():
    print("\n[1] idiomas y cadencia")
    for entrada, esperado in (("es", "es"), ("ES", "es"), ("es-ES", "es"),
                              ("espanol", "es"), ("Español", "es"),
                              ("spanish", "es"), ("English", "en"),
                              ("en_US", "en"), ("pt-BR", "pt"), ("", "")):
        igual(p2_brief.normalizar_idioma(entrada), esperado,
              f"normalizar_idioma({entrada!r})")

    # El ingles ya no son 2,6: son 2,553, MEDIDO sobre la toma del video largo
    # (369 palabras en 144,51 s de sintesis). El espanol sigue siendo la cifra
    # escrita porque no hay ninguna toma en espanol que medir. Ver cadencia.py.
    igual(p2_brief.palabras_por_segundo("en"), 2.553, "cadencia en ingles")
    igual(p2_brief.palabras_por_segundo("espanol"), 2.3, "cadencia en espanol")
    igual(p2_brief.palabras_por_segundo("fi"), p2_brief.PALABRAS_POR_SEGUNDO_OTROS,
          "idioma sin medir usa el punto medio")

    # LA VELOCIDAD MUEVE LA CUENTA, que es la mitad de por que esto se rehizo:
    # el mismo idioma a 'slow' cabe en menos palabras.
    comprobar(p2_brief.palabras_por_segundo("es", "slow")
              < p2_brief.palabras_por_segundo("es", "normal")
              < p2_brief.palabras_por_segundo("es", "fast"),
              "la velocidad ordena la cadencia")

    # Sin aire entre bloques la cuenta es la de siempre: duracion x cadencia.
    igual(p2_brief.presupuesto_de(180, "es"), 414, "180 s en espanol = 414 palabras")
    igual(p2_brief.presupuesto_de(180, "en"), 460, "180 s en ingles = 460 palabras")
    igual(p2_brief.presupuesto_de(60, "en"), 153, "60 s en ingles = 153 palabras")

    # Y CON AIRE CABEN MENOS: el silencio entre bloques son segundos que no dice
    # nadie. Con 1 s de hueco y bloques de 30 palabras, 180 s pierden unos 6 s.
    comprobar(p2_brief.presupuesto_de(180, "es", "normal", 1.0, 30) < 414,
              "el aire entre bloques descuenta palabras")

    # UNA SOLA TABLA DE VELOCIDAD, y el factor de TIEMPO es su inverso exacto.
    # Habia dos --el multiplicador que recibe Cartesia en `p4_voz` y un factor
    # escrito a mano en `cadencia`-- y no coincidian: 0,72 de tiempo son 1,39x
    # de velocidad, no 1,30x. O sea que lo que se le pedia a la voz y lo que se
    # estimaba que iba a durar no eran el mismo mando.
    import cadencia as cad                                   # noqa: PLC0415
    import p4_voz                                            # noqa: PLC0415
    igual(p4_voz.SPEED_DE_PRESET, cad.VELOCIDAD_API,
          "el multiplicador que recibe la voz sale de la tabla de cadencia")
    for nombre, api in cad.VELOCIDAD_API.items():
        igual(round(cad.FACTOR_VELOCIDAD[nombre] * api, 3), 1.0,
              f"'{nombre}': el factor de tiempo es el inverso del de velocidad")

    # LA VOZ ENTRA EN LA CUENTA. Medido: dos voces inglesas con el mismo modelo
    # dan 2,553 y 1,91 palabras/s a velocidad normal. Sin esto, cambiar de voz
    # dejaba el presupuesto igual y la toma duraba otra cosa.
    comprobar("voz_id" in p2_brief.PARAMS_POR_DEFECTO,
              "el brief declara la voz con la que hace la cuenta")
    igual(p2_brief.palabras_por_segundo("en", "normal", "una-voz-sin-tomas"),
          p2_brief.palabras_por_segundo("en", "normal"),
          "sin tomas de esa voz manda la tabla del idioma")
    ficha = p2_brief.horquilla_de(240, "en", 0.30, "normal", 1.0, 30, "vx")
    comprobar(ficha["presupuesto_palabras"] > 0,
              "la horquilla acepta la voz sin romperse")


def prueba_params():
    print("\n[2] parametros")
    for clave in ("instrucciones", "idioma_salida", "duracion_objetivo_s"):
        comprobar(clave in p2_brief.PARAMS_POR_DEFECTO,
                  f"PARAMS_POR_DEFECTO trae {clave}")

    falla(lambda: p2_brief._normalizar({"instrucciones": "   "}), "brief vacio")
    falla(lambda: p2_brief._normalizar({"instrucciones": "algo", "duracion_objetivo_s": 99999}),
          "duracion por encima del maximo")
    falla(lambda: p2_brief._normalizar({"instrucciones": "algo", "duracion_objetivo_s": "tres"}),
          "duracion que no es un numero")

    # El minimo de 10 minutos era linea editorial disfrazada de regla del
    # sistema y se quito: un video de un minuto es un video. Lo que queda es un
    # suelo TECNICO, lo justo para que haya algo que segmentar.
    corta = p2_brief._normalizar({"instrucciones": "algo", "duracion_objetivo_s": 60})
    igual(corta["duracion_objetivo_s"], 60,
          "un video de 60 s se respeta tal cual, sin subirlo a ningun minimo")
    igual(corta["duracion_pedida_s"], 60, "se recuerda lo que se pidio")
    bajo_suelo = p2_brief._normalizar({"instrucciones": "algo", "duracion_objetivo_s": 3})
    igual(bajo_suelo["duracion_objetivo_s"], p2_brief.DURACION_MINIMA_S,
          "por debajo del suelo tecnico si se sube, que si no no hay ni un plano")
    igual(bajo_suelo["duracion_pedida_s"], 3, "y se recuerda lo que se pidio")
    pasada = p2_brief._normalizar({"instrucciones": "algo", "tolerancia": 1.5})
    igual(pasada["tolerancia"], p2_brief.TOLERANCIA_MAXIMA,
          "la tolerancia se recorta al maximo admitido")

    opciones = p2_brief._normalizar({"instrucciones": "  menos tecnicismos  ",
                                     "idioma_salida": "Español",
                                     "duracion_objetivo_s": "840.6"})
    igual(opciones["instrucciones"], "menos tecnicismos", "las instrucciones se limpian")
    igual(opciones["idioma_salida"], "es", "el idioma se normaliza")
    igual(opciones["duracion_objetivo_s"], 841, "la duracion se redondea a entero")

    # UN VIDEO, UN IDIOMA. La lista vieja se sigue LEYENDO --se coge el primero,
    # que era el principal-- para que un proyecto guardado con el eje de idiomas
    # no se abra de pronto en otro idioma; no se vuelve a escribir.
    viejo = p2_brief._normalizar({"instrucciones": "algo",
                                  "idiomas_salida": ["English", "es"]})
    igual(viejo["idioma_salida"], "en", "de la lista vieja se coge el primero")
    comprobar("idiomas_salida" not in viejo, "y la lista no se vuelve a escribir")
    nuevo = p2_brief._normalizar({"instrucciones": "algo", "idioma_salida": "pt",
                                  "idiomas_salida": ["en"]})
    igual(nuevo["idioma_salida"], "pt", "la clave nueva gana a la vieja")

    resumen = p2_brief.describir({"instrucciones": "mas centrado en las cifras",
                                  "idioma_salida": "es", "duracion_objetivo_s": 900})
    # 2070 antes de que la cuenta descontara el aire entre bloques.
    comprobar("\n" not in resumen and "2000" in resumen,
              f"describir da una linea con el presupuesto: {resumen}")


def prueba_sin_ingesta(base):
    print("\n[3] brief sin material de ingesta")
    proyecto = Proyecto.crear(base, "Brief Suelto")
    salidas = p2_brief.ejecutar(proyecto, {
        "instrucciones": "el mismo video pero con menos tecnicismos",
        "idioma_salida": "es", "duracion_objetivo_s": 180}, sin_progreso)

    # 180 s a 2,3 pal/s serian 414 palabras, pero el paso descuenta el AIRE que
    # se inserta entre bloques (hueco_minimo 1,0 s de fabrica): con 13 bloques
    # son unos 6 s que no dice nadie, o sea 401 palabras. Antes esto se subia a
    # 600 s y devolvia 1380 palabras para un video pedido de tres minutos.
    igual(salidas["presupuesto_palabras"], 401,
          "180 s en espanol son 401 palabras con el aire descontado")
    igual(salidas["brief"]["velocidad"], "normal", "la velocidad queda escrita")
    comprobar(salidas["brief"]["aire_s"] > 0, "y el aire descontado, tambien")
    comprobar(not any("suelo tecnico" in aviso for aviso in salidas["brief"]["avisos"]),
              "y no avisa de haber subido nada, porque no ha subido nada")
    comprobar(any("no hay ingesta" in aviso for aviso in salidas["brief"]["avisos"]),
              "avisa de que no ha podido contrastar con la ingesta")
    trabajo = proyecto.ruta_trabajo("brief", crear=False)
    comprobar(os.path.exists(os.path.join(trabajo, "brief.json")), "escribe brief.json")
    comprobar(os.path.exists(os.path.join(trabajo, "brief.txt")), "escribe brief.txt")


def prueba_con_ingesta(base):
    print("\n[4] brief contrastado con la ingesta")
    proyecto = Proyecto.crear(base, "Brief Con Material")
    estado = Estado(proyecto)
    fabricar_ingesta(proyecto, estado, palabras=700, duracion=300, idioma="en")

    avisos = []
    salidas = p2_brief.ejecutar(proyecto, {
        "instrucciones": "mas centrado en las cifras y en como se financio",
        "idioma_salida": "es", "duracion_objetivo_s": 600},
        lambda valor, mensaje="": avisos.append((valor, mensaje)))

    brief = salidas["brief"]
    igual(sorted(k for k in ("brief", "presupuesto_palabras") if k in salidas),
          ["brief", "presupuesto_palabras"], "las salidas traen las claves del contrato")
    igual(salidas["presupuesto_palabras"], 1335,
          "600 s en espanol = 1335 palabras (1380 menos el aire entre bloques)")
    igual(brief["margen"], {"minimo": 934, "maximo": 1736, "tolerancia": 0.30},
          "la horquilla es el presupuesto mas menos el 30%")
    igual([brief["palabras_minimo"], brief["palabras_maximo"]], [934, 1736],
          "el minimo y el maximo de palabras van sueltos en el brief")
    igual(brief["bloques_estimados"], 44, "bloques estimados a 30 palabras por bloque")
    # LA HORQUILLA, DE VUELTA EN SEGUNDOS. Es lo que se le ensena a quien pidio
    # una duracion: cuanto se puede desviar de verdad el video que va a salir.
    comprobar(brief["segundos_minimo"] < 600 < brief["segundos_maximo"],
              "los 600 s pedidos caen dentro de la horquilla en segundos")

    textos = " | ".join(brief["avisos"])
    comprobar("pides 600s" in textos, f"avisa de que el objetivo dobla al original: {textos}")
    comprobar("supera al transcript" in textos, "avisa de que no hay material para tanto")
    comprobar("ingles" in textos and "espanol" in textos, "avisa del cambio de idioma")
    comprobar("ningun frame util" in textos, "avisa de que no hay referencia visual")
    igual(brief["referencia"]["palabras_transcript"], 700,
          "la referencia recoge las palabras del transcript")

    valores = [v for v, _ in avisos]
    comprobar(valores == sorted(valores) and valores[-1] == 1.0,
              "el progreso avanza y acaba en 1.0")

    with open(os.path.join(proyecto.ruta_trabajo("brief", crear=False), "brief.json"),
              "r", encoding="utf-8") as fh:
        igual(json.load(fh)["presupuesto_palabras"], 1335,
              "brief.json en disco coincide con las salidas")

    print("\n[5] integracion con el nucleo")
    igual(estado.estado_de("brief"), "pendiente", "antes de completar esta pendiente")
    estado.completar("brief", salidas)
    igual(estado.estado_de("brief"), "listo", "tras completar queda listo")
    igual(estado.estado_de("guion"), "pendiente", "el guion se desbloquea")
    comprobar(os.path.exists(os.path.join(proyecto.ruta_paso("brief"), "brief.json")),
              "brief.json viajo a la version v1")

    estado.set_params("brief", {"instrucciones": "otra cosa"})
    igual(estado.estado_de("brief"), "obsoleto", "cambiar el brief lo deja obsoleto")


def principal():
    base = tempfile.mkdtemp(prefix="prueba_p2_")
    # el historico de tiempos de verdad no se toca: aqui los pasos corren
    # con el CLI sustituido por un doble y sus centesimas no miden nada
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(base, "estadisticas.json")
    conservar = "--conservar" in sys.argv
    try:
        prueba_idiomas()
        prueba_params()
        prueba_sin_ingesta(base)
        prueba_con_ingesta(base)
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
    print("P2 BRIEF OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
