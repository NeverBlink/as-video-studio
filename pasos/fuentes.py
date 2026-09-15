r"""
De donde sale el material del video. UN SOLO SITIO, y esa es toda la idea.

Por que este modulo es tan pequeno
----------------------------------
Antes habia dos vias para el material: la transcripcion de un video de
referencia y un DOSIER que un agente documentalista armaba con lo que se pegara
mas lo que buscara en internet. Con dos vias hacia falta alguien que decidiera
cual manda, y ese alguien era este modulo.

Ahora el material es lo que se escribe en el paso «Origen» (`p1_ingesta`) y no
hay nada que decidir. Lo que queda es la LECTURA, y sigue viviendo aqui --y no
dentro de `p3_guion`-- por el mismo motivo de siempre: es el unico sitio donde
se abre ese fichero. Con dos lecturas distintas del mismo material, una de las
dos se queda vieja el dia que cambie el formato.

Se queda como modulo, y no se fusiona con `p1_ingesta`, porque quien lee no es
quien escribe: `p1_ingesta` produce el material y esto lo consume desde otro
paso. Juntarlos haria que `p3_guion` importara el paso 1 para leer un fichero.
"""
try:
    from . import comun
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import comun

#: Cuantas palabras hacen falta para que el material sostenga un video. Por
#: debajo de esto el guion se lo inventa casi todo, y eso se dice ANTES de
#: escribirlo: es la diferencia entre un aviso y un video que hay que tirar.
PALABRAS_MATERIAL_SUFICIENTE = 120


def material_de(proyecto):
    """El material del video. -> (transcript, metadatos, de_donde)

    `transcript` es la lista de trozos `{t_in, t_out, texto}` que dejo el paso
    «Origen». Los tiempos van a cero porque el material es texto escrito; el
    porque esta en la cabecera de `p1_ingesta`.

    `de_donde` es 'ingesta' o '' y se usa para decirlo en los avisos: saber con
    que material se escribio un guion es la mitad de poder corregirlo.
    """
    try:
        ingesta = comun.leer_salida(proyecto, "ingesta", "ingesta.json",
                                    obligatorio=False) or {}
    except Exception:                                         # noqa: BLE001
        # que el fichero este roto no puede tumbar la lectura: quien llama ya
        # sabe tratar un material vacio, y un error aqui saldria como un 500 en
        # una pantalla que solo queria contar palabras
        ingesta = {}
    trozos = ingesta.get("transcript") or []
    if trozos:
        return (trozos, ingesta.get("metadatos") or {}, "ingesta")
    return ([], {}, "")


def palabras_de(proyecto):
    """Cuantas palabras de material hay. -> int"""
    trozos, _meta, _de = material_de(proyecto)
    return sum(comun.contar_palabras(t.get("texto", "")) for t in trozos)


def material_escaso(proyecto):
    """Si hay tan poco material que el guion va a tener que inventarse. -> bool

    Se pregunta por PROYECTO y no por una lista de fuentes: el material es uno y
    esta en un sitio, asi que la unica forma de contarlo mal seria contarlo dos
    veces.
    """
    return 0 < palabras_de(proyecto) < PALABRAS_MATERIAL_SUFICIENTE
