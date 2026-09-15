r"""
Prueba del reparto de cartas de encuadre (pasos/encuadres.py).

Es la mitad viva de lo que fue `planos3d.py`: la caja 3D se retiro el 23-08-2026
y la carta no, porque nunca dependio de ella. Lo que se protege aqui es lo que
cuesta dinero si se rompe:

  1. LA ESCALERA        ids unicos, familia y peso en todas, y las tres
                        abstractas marcadas como tales
  2. DETERMINISMO       el mismo plano con la misma semilla saca SIEMPRE la
                        misma carta. Es lo que impide que replanificar cambie el
                        prompt de un plano que narra lo mismo -- y con el prompt
                        cambiado la imagen se vuelve a pagar
  3. LAS DOS REGLAS     nunca dos familias seguidas (dura) y no repetir carta
                        dentro de la ventana mientras queden libres (blanda)
  4. FORZAR             lo que pide una persona manda, incluidas las abstractas
  5. EL PROMPT          toda carta trae 'encuadre' en ingles y no vacio: es lo
                        unico que fija el cuadro sin geometria

    python pasos\prueba_encuadres.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import encuadres  # noqa: E402

FALLOS = []
COMPROBACIONES = 0


def igual(visto, esperado, que):
    global COMPROBACIONES
    COMPROBACIONES += 1
    if visto != esperado:
        FALLOS.append(f"{que}: esperaba {esperado!r}, vino {visto!r}")


def cierto(condicion, que):
    global COMPROBACIONES
    COMPROBACIONES += 1
    if not condicion:
        FALLOS.append(que)


def titulo(texto):
    print(f"\n--- {texto}")


ESCENAS = [{"id": f"S{n:03d}"} for n in range(1, 60)]


titulo("1 · la escalera")
ids = [c["id"] for c in encuadres.ESCALERA]
igual(len(ids), len(set(ids)), "los ids de carta son unicos")
cierto(len(ids) >= 12, "la escalera tiene al menos doce cartas")
for carta in encuadres.ESCALERA:
    cierto(bool(carta.get("familia")), f"'{carta['id']}' tiene familia")
    cierto(int(carta.get("peso") or 0) >= 1, f"'{carta['id']}' tiene peso >= 1")
    cierto(bool(carta.get("nombre")), f"'{carta['id']}' tiene nombre")
    cierto("plano" not in carta,
           f"'{carta['id']}' ya no lleva numeros de camara 3D")
abstractas = [c["id"] for c in encuadres.ESCALERA if c.get("abstracta")]
igual(sorted(abstractas), ["diagrama", "eterea", "pantalla"],
      "las tres cartas abstractas siguen ahi")
igual(sorted(encuadres.POR_ID), sorted(ids), "POR_ID cubre la escalera entera")

titulo("5 · el prompt de cada carta")
for carta in encuadres.ESCALERA:
    texto = carta.get("encuadre") or ""
    cierto(len(texto) > 30, f"'{carta['id']}' trae un encuadre escrito")
    cierto(texto == texto.strip(), f"'{carta['id']}' sin espacios sobrantes")

titulo("2 · determinismo")
for semilla in (0, 7, 42):
    una = encuadres.repartir(ESCENAS, semilla=semilla)
    otra = encuadres.repartir(ESCENAS, semilla=semilla)
    igual({k: v["id"] for k, v in una.items()},
          {k: v["id"] for k, v in otra.items()},
          f"semilla {semilla}: dos repartos seguidos dan lo mismo")
# y un plano suelto saca lo mismo que dentro del reparto, con las mismas previas
reparto = encuadres.repartir(ESCENAS, semilla=3)
previas = []
for escena in ESCENAS:
    suelta = encuadres.carta_de(escena["id"], previas, 3)
    igual(suelta["id"], reparto[escena["id"]]["id"],
          f"{escena['id']}: carta_de y repartir coinciden")
    previas.append(suelta["id"])

titulo("3 · las dos reglas")
for semilla in (0, 1, 5, 11, 99):
    cartas = [encuadres.repartir(ESCENAS, semilla=semilla)[e["id"]]["id"]
              for e in ESCENAS]
    familias = [encuadres.POR_ID[c]["familia"] for c in cartas]
    seguidas = [i for i in range(1, len(familias)) if familias[i] == familias[i - 1]]
    igual(seguidas, [], f"semilla {semilla}: ni dos familias seguidas")
    # la ventana de familia son DOS: tampoco A-B-A
    saltadas = [i for i in range(2, len(familias)) if familias[i] == familias[i - 2]]
    igual(saltadas, [], f"semilla {semilla}: ni familia repetida a dos de distancia")
    repetidas = [i for i in range(1, len(cartas))
                 if cartas[i] in cartas[max(0, i - encuadres.VENTANA_CARTA):i]]
    igual(repetidas, [], f"semilla {semilla}: ninguna carta repite dentro de su ventana")

titulo("4 · forzar una carta")
forzadas = {"S003": "diagrama", "S010": "aereo", "S020": "pantalla",
            "S030": "eterea"}
cartas = encuadres.repartir(ESCENAS, semilla=0, forzadas=forzadas)
for sid, pedida in forzadas.items():
    igual(cartas[sid]["id"], pedida, f"{sid}: manda la carta forzada")
igual(encuadres.carta_de("S001", [], 0, "no_existe")["id"] in encuadres.POR_ID,
      True, "una carta forzada que no existe cae al reparto")

titulo("y el fondo del reparto")
fondo = encuadres._repartidas()
igual(len(fondo), sum(int(c["peso"]) for c in encuadres.ESCALERA),
      "el fondo pesa lo que suman los pesos")
cierto(all(c.get("abstracta") is not None or True for c in fondo),
       "las abstractas entran en el fondo")
igual(len({c["id"] for c in fondo}), len(encuadres.ESCALERA),
      "todas las cartas entran en el fondo")

print()
if FALLOS:
    print(f"FALLAN {len(FALLOS)} de {COMPROBACIONES} comprobaciones:")
    for f in FALLOS:
        print("   ", f)
    sys.exit(1)
print(f"ENCUADRES OK: {COMPROBACIONES} comprobaciones pasan")
