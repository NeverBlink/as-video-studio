"""
Conservacion en cascada.

Un cambio aguas arriba no arrasa lo de aguas abajo. Se prueba la comparacion de
guiones, la regla de estirar antes que partir, la identidad estable de cada
plano entre dos planes y el primitivo del grafo (estado.adoptar), que acepta
entradas nuevas sin rehacer.

No hay red ni CLI: todo lo que aqui se comprueba es determinista.

    C:\\IA\\venvs\\cartoon\\Scripts\\python.exe C:\\IA\\estudio\\pasos\\prueba_conservar.py
"""
import json
import os
import shutil
import sys
import tempfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)
sys.path.insert(0, os.path.join(RAIZ, "pasos"))

import conservar  # noqa: E402
import p6_assets  # noqa: E402

from nucleo.estado import Estado  # noqa: E402
from nucleo.proyecto import Proyecto  # noqa: E402

CARPETA = os.path.join(tempfile.gettempdir(), "estudio_prueba_conservar")

_fallos = []
_comprobaciones = [0]


def ok(condicion, mensaje):
    _comprobaciones[0] += 1
    if not condicion:
        _fallos.append(mensaje)
        print(f"    FALLO: {mensaje}")
    else:
        print(f"  ok   {mensaje}")
    return bool(condicion)


def igual(obtenido, esperado, mensaje):
    return ok(obtenido == esperado, f"{mensaje} (obtenido {obtenido!r}, "
                                    f"esperado {esperado!r})")


def titulo(texto):
    print(f"\n[{texto}]")


FUENTE_BUENA = '''
NOMBRE = "quirofano"
ANCLAS = {"mesa_operaciones": "mesa_", "monitores": "monitor_"}
VOCABULARIO = {
    "mesa_operaciones": {"etiqueta": "LA MESA", "palabras": ["mesa", "camilla"],
                         "sujeto": "the operating table"},
    "monitores": {"etiqueta": "LOS MONITORES", "palabras": ["monitor", "pulso"],
                  "sujeto": "the vital signs monitors"},
}

def build():
    box("suelo", (0, 0, -0.1), (9, 11, 0.2))
    box("mesa_tablero", (0, 0.5, 0.85), (0.8, 2.2, 0.12))
    box("monitor_1", (-2.2, 3.0, 1.5), (0.6, 0.15, 0.45))
    return [add_camera("general", (0, -4, 1.9), (0, 0.6, 1.2), lens=28)]
'''


# ------------------------------------------------------------ conservacion

def prueba_comparar():
    titulo("conservar: que le ha pasado a cada bloque")
    antes = [{"id": "B01", "texto": "El carguero zarpo de Buenaventura."},
             {"id": "B02", "texto": "La marina lo intercepto frente a Manzanillo."},
             {"id": "B03", "texto": "El juicio duro tres anos."},
             {"id": "B04", "texto": "Nadie fue condenado."},
             {"id": "B05", "texto": "Este bloque desaparece."}]
    ahora = [{"id": "B01", "texto": "El carguero zarpo de Buenaventura."},
             {"id": "B02", "texto": "La marina lo intercepto, frente a Manzanillo!"},
             {"id": "B03", "texto": "El juicio se alargo durante tres anos interminables."},
             {"id": "B04", "texto": "La fabrica de Chicago cerro en 1998."},
             {"id": "B06", "texto": "Y este es nuevo."}]
    fichas = conservar.comparar_bloques(antes, ahora)
    igual(fichas["B01"]["estado"], "igual", "el texto identico no se toca")
    igual(fichas["B02"]["estado"], "cosmetico",
          "un cambio de puntuacion no cambia ni lo que se oye ni lo que se ve")
    igual(fichas["B03"]["estado"], "retocado",
          "la misma idea con otras palabras es un retoque: hay que MIRAR sus planos")
    igual(fichas["B04"]["estado"], "reescrito", "y esto dice otra cosa")
    igual(fichas["B05"]["estado"], "borrado", "un bloque que ya no esta")
    igual(fichas["B06"]["estado"], "nuevo", "y uno que antes no estaba")
    igual(conservar.resumen_bloques(fichas),
          {"igual": 1, "cosmetico": 1, "retocado": 1, "reescrito": 1,
           "borrado": 1, "nuevo": 1},
          "y el resumen cuenta uno de cada")

    titulo("conservar: cambiar el TONO no tiene por que cambiar la imagen")
    seco = [{"id": "B01", "texto": "El juicio duro tres anos."}]
    literario = [{"id": "B01", "texto": "El juicio se alargo durante tres anos."}]
    igual(conservar.comparar_bloques(seco, literario)["B01"]["estado"], "retocado",
          "reescribir una frase con otro tono no la convierte en otra frase")


def prueba_estirar():
    titulo("conservar: estirar el plano antes que partir el tramo")
    antes = [{"id": "B01", "texto": "Una frase corta."}]
    plan = {"escenas": [{"id": "S001", "narracion": "Una frase corta",
                         "duracion": 4.0,
                         "origen": {"bloque": "B01", "indice": 0}}]}

    poco = [{"id": "B01", "texto": "Una frase corta pero algo mayor."}]
    ficha = conservar.analizar(antes, poco, plan)
    igual(ficha["rehacer"], [],
          "un bloque que crece poco NO obliga a rehacer su plano")
    igual([d["id"] for d in ficha["dudosos"]], ["S001"],
          "solo hay que mirar si su imagen sigue valiendo")
    ok(ficha["estirar"] and ficha["estirar"][0]["cabe"],
       f"y el plano se estira para absorberlo: x{ficha['estirar'][0]['estiron']}")

    mucho = [{"id": "B01", "texto": "Una frase corta que ahora es larguisima, con "
                                    "datos, con contexto y con tres oraciones mas "
                                    "que antes no estaban en ninguna parte."}]
    ficha2 = conservar.analizar(antes, mucho, plan)
    igual(ficha2["rehacer"], ["S001"],
          "pero si el bloque triplica su largo ya no cabe: ese tramo se recorta")
    igual(ficha2["dudosos"], [],
          "y no se gasta una llamada preguntando por un plano que hay que rehacer igual")


def prueba_planos():
    titulo("conservar: del guion a los planos")
    antes = [{"id": "B01", "texto": "Primer bloque."},
             {"id": "B02", "texto": "Segundo bloque."}]
    ahora = [{"id": "B01", "texto": "Primer bloque."},
             {"id": "B02", "texto": "Un asunto completamente distinto y ajeno."}]
    plan = {"escenas": [
        {"id": "S001", "narracion": "Primer", "duracion": 4.0,
         "origen": {"bloque": "B01", "indice": 0}},
        {"id": "S002", "narracion": "bloque", "duracion": 4.0,
         "origen": {"bloque": "B01", "indice": 1}},
        {"id": "S003", "narracion": "Segundo bloque", "duracion": 4.0,
         "origen": {"bloque": "B02", "indice": 0}},
    ]}
    ficha = conservar.plan_de_conservacion(antes, ahora, plan, preguntar=False)
    igual(ficha["conservar"], ["S001", "S002"],
          "los planos del bloque intacto se conservan")
    igual(ficha["rehacer"], ["S003"], "y solo se rehace el del bloque cambiado")
    ok(ficha["motivos"]["S001"], "cada plano dice POR QUE se conserva")
    ok(ficha["motivos"]["S003"], "y cada uno POR QUE se rehace")

    titulo("conservar: sin juicio del modelo no se conserva nada dudoso")
    retocado = [{"id": "B01", "texto": "Primer bloque."},
                {"id": "B02", "texto": "Segundo bloque, algo mas largo."}]
    ficha2 = conservar.plan_de_conservacion(antes, retocado, plan, preguntar=False)
    ok("S003" in ficha2["rehacer"],
       "un plano dudoso al que no se ha preguntado se rehace: es lo que se hacia "
       "antes, asi que fallar aqui nunca deja el video peor")

    titulo("conservar: un plan sin 'origen' se dice, no se disimula")
    viejo = {"escenas": [{"id": "S001", "narracion": "algo", "duracion": 4.0}]}
    ficha3 = conservar.analizar(antes, ahora, viejo)
    ok(ficha3["sin_origen"],
       "sin saber de que bloque sale cada plano no se puede conservar por bloques")


def prueba_identidad():
    titulo("p6: de que trozo de guion sale cada plano")
    escenas = [{"id": "S001", "t_in": 0.0, "t_out": 4.0},
               {"id": "S002", "t_in": 4.0, "t_out": 8.0},
               {"id": "S003", "t_in": 8.0, "t_out": 12.0}]
    meta = {"bloques": [{"id": "B01", "t_in": 0.0, "t_out": 7.0},
                        {"id": "B02", "t_in": 7.0, "t_out": 12.0}]}
    p6_assets._marcar_origen(escenas, meta)
    igual([e["origen"]["clave"] for e in escenas], ["B01#0", "B01#1", "B02#0"],
          "cada plano sabe de que bloque sale y en que posicion")

    viejo = {"escenas": [{"id": "S01", "t_primera_palabra": 0.0,
                          "t_ultima_palabra": 7.0},
                         {"id": "S02", "t_primera_palabra": 7.0,
                          "t_ultima_palabra": 12.0}]}
    otras = [dict(e) for e in escenas]
    p6_assets._marcar_origen(otras, viejo)
    igual([e["origen"]["bloque"] for e in otras], ["S01", "S01", "S02"],
          "y con un audio_meta del formato antiguo tambien, que si no un "
          "proyecto viejo se quedaria sin identidad de plano")

    titulo("p6: los ids van por posicion; la identidad viaja en hereda_de")
    previo = {"escenas": [
        {"id": "S001", "narracion": "el carguero zarpa", "set": "puerto",
         "camara": "general_aereo", "origen": {"bloque": "B01", "indice": 0}},
        {"id": "S002", "narracion": "con diez toneladas", "set": "puerto",
         "camara": "medio_grua", "origen": {"bloque": "B01", "indice": 1}},
        {"id": "S003", "narracion": "y nadie lo sabia", "set": "bodega",
         "camara": "detalle_pila", "origen": {"bloque": "B02", "indice": 0}},
    ]}
    # el guion mete una frase nueva EN MEDIO: los numeros se corren (siempre en
    # orden de video) y lo que se conserva es la IDENTIDAD, no el numero
    nuevas = [
        {"id": "S001", "narracion": "el carguero zarpa",
         "origen": {"bloque": "B01", "indice": 0}},
        {"id": "S002", "narracion": "de noche y sin permiso",
         "origen": {"bloque": "B01", "indice": 1}},
        {"id": "S003", "narracion": "con diez toneladas",
         "origen": {"bloque": "B01", "indice": 2}},
        {"id": "S004", "narracion": "y nadie lo sabia",
         "origen": {"bloque": "B02", "indice": 0}},
    ]
    reparto = p6_assets._heredar_ids(nuevas, previo)
    igual([e["id"] for e in nuevas], ["S001", "S002", "S003", "S004"],
          "los ids SIEMPRE en orden de video, tambien heredando")
    igual([e.get("hereda_de") for e in nuevas], [None, None, "S002", "S003"],
          "los que se movieron de sitio apuntan de que id viejo heredan")
    igual(sorted(reparto["conservados"]), ["S001", "S003", "S004"],
          "tres se conservan (por narracion, no por numero)")
    igual(reparto["nuevos"], ["S002"], "y el que entra es el unico nuevo")
    igual(reparto["retirados"], [], "un numero que se corre no es contenido retirado")

    titulo("p6: reciclar un numero no cuelga salidas viejas")
    solo_uno = [{"id": "S001", "narracion": "algo distinto del todo",
                 "origen": {"bloque": "B09", "indice": 0}}]
    reparto2 = p6_assets._heredar_ids(solo_uno, previo)
    igual(solo_uno[0]["id"], "S001",
          "el numero es la posicion, aunque antes lo llevara otro contenido")
    ok(not solo_uno[0].get("hereda_de") and reparto2["heredados"] == {},
       "sin narracion que case no se hereda nada: la firma y la narracion son "
       "las que impiden colgarle el arte viejo (adopcion por firma, hechoDe)")
    igual(sorted(reparto2["retirados"]), ["S001", "S002", "S003"],
          "y el contenido que de verdad se va queda dicho")


def prueba_adoptar():
    titulo("estado.adoptar: aceptar entradas nuevas sin rehacer")
    raiz = os.path.join(CARPETA, "proyecto")
    shutil.rmtree(raiz, ignore_errors=True)
    os.makedirs(raiz, exist_ok=True)
    proyecto = Proyecto.crear(raiz, "prueba conservar") \
        if hasattr(Proyecto, "crear") else Proyecto(raiz)
    estado = Estado(proyecto)

    estado.set_params("ingesta", {"url": "https://ejemplo"})
    estado.completar("ingesta", {"palabras": 100})
    estado.set_params("brief", {"minutos": 10})
    estado.completar("brief", {"resumen": "un brief"})
    estado.set_params("guion", {"tono": "seco"})
    estado.completar("guion", {"bloques": 4})
    estado.set_params("voz", {"voz": "una"})
    estado.completar("voz", {"duracion": 100.0})
    estado.set_params("assets", {"calidad": "low",
                                 "unidades": {"S001": {}, "S002": {}}})
    estado.completar("assets", {"escenas": 2},
                     unidades={"S001": {"png": "a.png"}, "S002": {"png": "b.png"}})
    igual(estado.estado_de("assets"), "listo", "el montaje arranca al dia")

    estado.set_params("guion", {"tono": "literario"})
    igual(estado.estado_de("voz"), "obsoleto", "cambiar el guion deja la voz obsoleta")
    igual(estado.estado_de("assets"), "obsoleto", "y los assets tambien")
    igual(sorted(estado.unidades_obsoletas("assets")), ["S001", "S002"],
          "con TODAS sus unidades, que es justo el problema")

    resultado = estado.adoptar("assets", unidades=["S001"], rehacer=["S002"],
                               motivo="S001 narra lo mismo", quien="prueba")
    igual(resultado["conservadas"], ["S001"], "se conserva la unidad que sigue valiendo")
    igual(estado.unidades_obsoletas("assets"), ["S002"],
          "y solo queda por rehacer la otra")
    igual(estado.estado_de("assets"), "obsoleto",
          "el paso sigue obsoleto mientras quede algo por rehacer: conservar no "
          "es declararlo terminado")
    igual(estado.salidas_unidad("assets", "S001"), {"png": "a.png"},
          "lo conservado NO pierde lo que produjo")

    historico = estado.conservaciones("assets")
    igual(len(historico), 1, "queda escrito que se conservo")
    igual(historico[0]["quien"], "prueba", "quien lo decidio")
    ok(historico[0]["motivo"], "y por que")
    ok(historico[0]["firma_antes"] != historico[0]["firma_despues"],
       "con la firma de antes y la de despues, que es la prueba de que las "
       "entradas eran otras")
    igual(len(estado.versiones("assets")), 1,
          "y NO se inventa una version: no se ha producido nada nuevo")

    estado.adoptar("voz", motivo="la locucion sigue sirviendo")
    igual(estado.estado_de("voz"), "listo",
          "un paso sin unidades se conserva entero y deja de estar obsoleto")

    titulo("estado.adoptar: lo que nunca se hizo no se puede conservar")
    estado.set_params("assets", {"calidad": "low",
                                 "unidades": {"S001": {}, "S002": {}, "S003": {}}})
    resultado2 = estado.adoptar("assets", unidades=["S003"], motivo="no existe")
    igual(resultado2["conservadas"], [],
          "una unidad que nunca se produjo no se da por buena")
    ok("S003" in estado.unidades_obsoletas("assets"),
       "y sigue pendiente, como tiene que ser")

    titulo("estado.adoptar: un paso sin ejecutar no se puede conservar")
    try:
        estado.adoptar("render")
        ok(False, "tendria que haber levantado")
    except ValueError as fallo:
        ok("nada que conservar" in str(fallo),
           "y se dice claramente en vez de fingir que hay algo")


def main():
    # EL HISTORICO DE TIEMPOS, A UNA COPIA. Guarda 30 muestras por paso, asi
    # que las de una suite EXPULSAN las reales por antiguedad -- y con ellas se
    # va lo unico que hace que `cadencia` y la barra dejen de usar la tabla
    # escrita y usen lo medido de esta maquina.
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(
        tempfile.gettempdir(), "estudio_prueba_conservar", "estadisticas.json")
    os.makedirs(CARPETA, exist_ok=True)
    prueba_comparar()
    prueba_estirar()
    prueba_planos()
    prueba_identidad()
    prueba_adoptar()

    print("\n" + "=" * 70)
    if _fallos:
        print(f"FALLAN {len(_fallos)} de {_comprobaciones[0]} comprobaciones:")
        for fallo in _fallos:
            print(f"  - {fallo}")
        return 1
    print(f"CONSERVACION OK: {_comprobaciones[0]} comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
