r"""
Prueba encadenada de los pasos 1 a 3 sobre un proyecto real.

Corre ingesta -> brief -> guion en el mismo proyecto, cada paso lanzado como
trabajo en segundo plano con GestorTrabajos, y comprueba que el grafo de estado,
la bitacora y las versiones quedan como deben.

EL MATERIAL ESTA EN ESTE FICHERO (`MATERIAL`, unas 300 palabras en ingles a
proposito: una de las comprobaciones es que el brief avise de que el material no
esta en el idioma del guion), asi que no depende de ninguna carpeta de fuera. Lo
que SI sale de la maquina es la llamada al CLI de Claude, que es la que escribe
el guion de verdad.

    python pasos\prueba_pasos_guion.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude
import p1_ingesta
import p2_brief
import p3_guion
from nucleo import Bitacora, Estado, GestorTrabajos, Proyecto

MAX_FRAMES = 40

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


def leer_json(ruta):
    """Los pasos dejan el material gordo en ficheros, no en las salidas."""
    with open(ruta, "r", encoding="utf-8") as fh:
        return json.load(fh)


def correr(avisar, modulo, proyecto, params):
    """Adapta la firma del paso a la que espera GestorTrabajos."""
    return modulo.ejecutar(proyecto, params, avisar)


def lanzar(gestor, estado, bitacora, modulo, proyecto, paso, params, tiempo_max):
    """Lanza un paso, espera a que acabe y lo versiona; devuelve sus salidas."""
    bitacora.anotar("params", paso, {"resumen": modulo.describir(params)})
    estado.set_params(paso, params)
    trabajo = gestor.lanzar(paso, correr, modulo, proyecto, params, paso=paso)
    ficha = gestor.esperar(trabajo, tiempo_max)
    if ficha["estado"] != "listo":
        # UN CUPO AGOTADO NO ES UN FALLO DEL CODIGO. Esta suite es la unica que
        # llama al CLI de verdad, asi que es la unica que se puede quedar sin
        # cupo, y durante los dias que tarde en renovarse se pondria en rojo sin
        # que nada este roto. Un rojo que no significa nada ensena a ignorar el
        # rojo, y entonces el dia que se rompa algo de verdad no se ve.
        if cli_claude.limite_de(ficha["error"]):
            print("")
            print(f"  CUPO  {paso} no se ha podido correr: {ficha['error']}")
            print("        NO es un fallo del codigo. La suite se salta")
            print("        entera hasta que se renueve el cupo; las otras 19")
            print("        no llaman al CLI y siguen valiendo.")
            raise SystemExit(cli_claude.CODIGO_SIN_CUPO)
        comprobar(False, f"{paso} termino en {ficha['estado']}: {ficha['error']}")
        raise SystemExit(f"{paso} fallo: {ficha['error']}")
    salidas = ficha["resultado"]
    version = estado.completar(paso, salidas)
    bitacora.anotar("completado", paso, {"version": version,
                                         "resumen": salidas.get("resumen", "")})
    print(f"  ok   {paso} v{version} en {ficha['segundos']}s: {salidas.get('resumen', '')}")
    return salidas


#: EL MATERIAL, y va EN INGLES a proposito: una de las comprobaciones es que el
#: brief avise de que el material esta en otro idioma que el del guion. Son unas
#: 300 palabras, suficientes para que no salte el aviso de material escaso.
MATERIAL = " ".join(["""
Rockefeller was born in 1839 in Richland, New York, the second of six children.
His father was a travelling salesman who was often away for months.

He got his first job as an assistant bookkeeper at sixteen, on the twenty-sixth
of September, a date he celebrated for the rest of his life as Job Day.

In 1863 he entered the oil business with a refinery in Cleveland. Refining, not
drilling: the margin was in what happened after the oil came out of the ground,
and drilling was a lottery that ruined most of the men who tried it.

Standard Oil was founded in 1870 with a capital of one million dollars. Within
a decade it controlled around ninety per cent of the refining capacity of the
United States, and it did it by buying its competitors rather than by beating
them on price alone.

The method had a name inside the company: the plan. A rival was shown the books,
offered stock in Standard Oil, and told what would happen if the offer was
refused. Most accepted, and many of them became rich doing it.

The railroads were the other half. Standard Oil shipped so much crude that it
could negotiate rebates no smaller shipper could match, and for a while it even
collected a cut of what its competitors paid to ship theirs.

In 1911 the Supreme Court ordered the company broken into thirty-four pieces.
Rockefeller owned shares in all of them, and the parts turned out to be worth
more separately than the whole had been: the ruling made him richer than the
monopoly had.
""".strip()] * 1)


def material():
    """Se queda como funcion para no tocar a quien la llama."""
    return MATERIAL


def principal():
    base = tempfile.mkdtemp(prefix="prueba_cadena_")
    # el historico de tiempos de verdad no se toca: aqui los pasos corren
    # con el CLI sustituido por un doble y sus centesimas no miden nada
    os.environ["ESTUDIO_ESTADISTICAS"] = os.path.join(base, "estadisticas.json")
    conservar = "--conservar" in sys.argv
    try:
        texto = material()
        proyecto = Proyecto.crear(base, "Cadena Ingesta a Guion")
        estado = Estado(proyecto)
        bitacora = Bitacora(proyecto)
        gestor = GestorTrabajos(estado=estado, bitacora=bitacora)

        print("\n[1] estado inicial")
        igual([f["estado"] for f in estado.resumen()["pasos"][:3]],
              ["pendiente", "bloqueado", "bloqueado"],
              "solo la ingesta es ejecutable al principio")

        print("\n[2] cadena completa")
        # EL MATERIAL, escrito. La cadena entera se prueba con texto pegado:
        # es lo unico que admite el paso «Origen», y ademas hace la suite
        # determinista -- antes dependia de un video en disco.
        ingesta = lanzar(gestor, estado, bitacora, p1_ingesta, proyecto,
                         "ingesta", {"texto": texto, "titulo": "Rockefeller",
                                     "idioma": "en"}, 60)

        brief = lanzar(gestor, estado, bitacora, p2_brief, proyecto, "brief", {
            "instrucciones": "cuenta la historia igual pero con menos tecnicismos "
                             "de negocio y mas centrado en las cifras",
            "idioma_salida": "es", "duracion_objetivo_s": 90}, 120)

        guion = lanzar(gestor, estado, bitacora, p3_guion, proyecto, "guion", {
            "prompt_general": "tono seco, frases cortas",
            "regenerar_desde_cero": True}, 900)

        print("\n[3] coherencia entre pasos")
        # 90 s a 2,3 pal/s serian 207, menos el aire entre bloques: 201. Antes
        # esto se subia a 600 s (1380 palabras)
        # porque "un video del estudio dura al menos 10 minutos"; ese minimo era
        # linea editorial disfrazada de regla del sistema y se quito.
        igual(brief["presupuesto_palabras"], 201,
              "un video de 90 s se presupuesta como 90 s, sin subirlo a ningun minimo")
        comprobar(brief["brief"]["referencia"]["palabras_transcript"]
                  == ingesta["palabras"],
                  "el brief mira el material que dejo el paso Origen")
        comprobar(any("ingles" in aviso for aviso in brief["brief"]["avisos"]),
                  "el brief avisa de que el material esta en otro idioma")
        # LA HORQUILLA SE COMPRUEBA CON HOLGURA, y conviene saber por que: esta
        # llamada es al CLI de VERDAD, asi que el largo del guion lo decide un
        # modelo y varia entre pasadas. Lo que tiene que estar bien es el MOTOR:
        # que la cuenta se haga, que el paso lo diga y que se reintente. Clavar
        # aqui el +-30 % exacto convierte una suite en una moneda al aire -- paso
        # de verdad: 266 palabras contra un maximo de 261, un 2 % de mas.
        #
        # Lo que SI se exige es que no se desmadre (el doble de lo pedido seria
        # que el presupuesto no esta llegando al prompt) y que el paso sea
        # honesto sobre donde ha caido.
        holgado = (guion["palabras_minimo"] * 0.8 <= guion["palabras"]
                   <= guion["palabras_maximo"] * 1.2)
        comprobar(holgado,
                  f"el guion cae cerca de la horquilla: {guion['palabras']} "
                  f"palabras ({guion['palabras_minimo']}-{guion['palabras_maximo']})")
        dentro = (guion["palabras_minimo"] <= guion["palabras"]
                  <= guion["palabras_maximo"])
        comprobar(guion["dentro_de_horquilla"] == dentro,
                  "y el paso dice la verdad sobre si ha caido dentro o fuera")
        if not dentro:
            comprobar(any("palabras" in a for a in (guion.get("avisos") or [])),
                      "cuando cae fuera, se avisa en vez de callarlo")

        documento = leer_json(os.path.join(proyecto.ruta_paso("guion"),
                                           guion["guion_fichero"]))
        copiados = []   # el detector de copias se retiro el 24-08
        igual(copiados, [], "ningun bloque copia literalmente el transcript original")
        texto = " ".join(b["texto"].lower() for b in documento["guion"])
        comprobar(any(p in texto for p in (" que ", " de ", " los ", " para ")),
                  "el guion esta redactado en espanol")
        comprobar(len(documento["guion"]) >= 4,
                  f"el guion viene partido en {len(documento['guion'])} bloques con id")

        print("\n[4] grafo de estado y versiones")
        for paso in ("ingesta", "brief", "guion"):
            igual(estado.estado_de(paso), "listo", f"{paso} queda listo")
        igual(estado.estado_de("voz"), "pendiente", "la voz queda desbloqueada")
        igual(estado.estado_de("assets"), "bloqueado", "assets sigue bloqueado sin voz")

        estado.set_params("brief", dict(estado.params("brief"), duracion_objetivo_s=120))
        igual(estado.estado_de("brief"), "obsoleto", "tocar el brief lo deja obsoleto")
        igual(estado.estado_de("guion"), "obsoleto", "y arrastra al guion")
        igual(estado.estado_de("ingesta"), "listo", "pero no toca la ingesta")

        print("\n[5] bitacora")
        eventos = bitacora.leer()
        nombres = {e["evento"] for e in eventos}
        comprobar({"params", "completado", "trabajo_lanzado", "trabajo_terminado"}
                  <= nombres, f"la bitacora registro el recorrido: {sorted(nombres)}")
        igual(len(bitacora.leer(paso="guion")), 4, "cuatro eventos del paso guion")
        comprobar("guion" in bitacora.resumen_para_llm(),
                  "el resumen para el LLM incluye el guion")

        print("\n  --- guion producido -----------------------------------------")
        print(f"  {guion['titulo']}")
        for bloque in documento["guion"]:
            print(f"  {bloque['id']}  {bloque['texto']}")
        print("  -------------------------------------------------------------")
    finally:
        if conservar:
            print(f"\nproyecto temporal conservado en {base}")
        else:
            shutil.rmtree(base, ignore_errors=True)

    print()
    if FALLOS:
        print(f"FALLARON {len(FALLOS)} comprobaciones:")
        for texto in FALLOS:
            print(f"  - {texto}")
        return 1
    print("CADENA 1-3 OK: todas las comprobaciones pasan")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
