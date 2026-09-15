r"""
Paso 1: EL MATERIAL. Lo que este video cuenta, escrito.

Que hace este paso
------------------
Toma el material que se ha escrito o pegado --notas, un articulo copiado, una
cronologia, lo que sea-- y lo deja en la forma que leen los pasos de abajo: una
lista de trozos en `ingesta.json`, mas su ficha de metadatos.

No baja nada, no sale a la red y no mira ningun video. El material es lo que se
escribe, y solo eso.

Por que sigue existiendo un paso para esto
-----------------------------------------
Porque el material es una ENTRADA del grafo, y las entradas tienen que tener su
propia version. Cambiar el material deja obsoleto el brief, el guion, la voz y
todo lo que cuelga -- y eso solo pasa si el material vive en un paso con su
firma, no en un cajon suelto. Pegar dos parrafos distintos y que el video siga
diciendo «listo» seria peor que no tener el paso.

Es tambien lo que hace que se pueda volver: cada version guarda el material con
el que se escribio ese guion, asi que revertir a la v2 recupera el texto de la
v2 y no el de ahora.

Los trozos NO llevan tiempos, y es a proposito
----------------------------------------------
El formato de `transcript` es una lista de `{t_in, t_out, texto}`, y `p3_guion`
sabe leerlo. Aqui no hay tiempos que poner: el material es texto escrito, no
algo que alguien dijo en un minuto concreto. Se escriben a cero y se dice en
`sin_tiempos`.

Poner tiempos inventados --repartir el texto por parrafos a tantos segundos
cada uno-- seria peor que no ponerlos: aguas abajo hay codigo que ordena y
recorta por tiempo, y unos tiempos falsos le harian tomar decisiones sobre algo
que no existe. Un cero se ve; un 47,3 inventado no.

Que hay en las salidas y que hay en los ficheros
------------------------------------------------
Las salidas que devuelve `ejecutar()` se sellan en estado.json, y ahi solo caben
cosas pequenas: el nucleo sustituye por un resumen cualquier clave que pase de
unos pocos KB. Por eso aqui las salidas son SOLO cifras y banderas; el texto
entero vive en `ingesta.json` y en `material.txt` dentro de la version.
"""
import os
import re
import time

try:
    from . import comun, estadisticas
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import comun
    import estadisticas

PASO = "ingesta"

#: Cuanto tarda de serie, para la barra. Es casi instantaneo --no hay red ni
#: modelo-- pero la barra necesita un numero de partida.
TIEMPO_BASE_S = 2

#: Tope de lo que se acepta pegado. 400.000 caracteres son unas 65.000
#: palabras: mas que suficiente para cualquier video, y el limite esta para que
#: un pegado accidental de un fichero entero no se cuele en cada prompt de aqui
#: abajo -- que es donde se paga.
MAX_CARACTERES = 400000

PARAMS_POR_DEFECTO = {
    # El material, tal y como se escribio. Entra en la firma del paso, asi que
    # cambiar una coma deja obsoleto lo que se hizo leyendolo.
    "texto": "",
    # Como se llama esto, si se le quiere poner nombre. Opcional: sin el, el
    # nombre del proyecto ya dice de que va.
    "titulo": "",
    # EN QUE IDIOMA ESTA EL MATERIAL. Opcional, y vacio de fabrica: con texto
    # escrito no hay nada que detectar, y adivinarlo daria un aviso falso la
    # mitad de las veces. Puesto, el brief avisa si el guion se pide en otro
    # (ver `p2_brief`): traducir mientras se redacta se nota, y saberlo antes
    # de escribir 2.000 palabras cuesta menos que descubrirlo despues.
    "idioma": "",
}


def describir(params):
    """Resumen de una linea de la configuracion del paso, para la bitacora."""
    opciones = _normalizar(params, estricto=False)
    palabras = _palabras(opciones["texto"])
    if not palabras:
        return "material vacio"
    titulo = opciones["titulo"]
    return (f"material escrito: {palabras} palabras"
            + (f" en {opciones['idioma']}" if opciones["idioma"] else "")
            + (f" · «{titulo}»" if titulo else ""))


# --------------------------------------------------------------------- params

def _normalizar(params, estricto=True):
    """Los params completos y con los tipos correctos."""
    opciones = dict(PARAMS_POR_DEFECTO)
    opciones.update({c: v for c, v in (params or {}).items()
                     if c in PARAMS_POR_DEFECTO})

    texto = str(opciones.get("texto") or "")
    if len(texto) > MAX_CARACTERES:
        if estricto:
            raise ValueError(
                f"el material son {len(texto)} caracteres y el tope son "
                f"{MAX_CARACTERES}: recorta lo que no sea de este video")
        texto = texto[:MAX_CARACTERES]
    opciones["texto"] = texto
    opciones["titulo"] = " ".join(str(opciones.get("titulo") or "").split())
    opciones["idioma"] = str(opciones.get("idioma") or "").strip().lower()
    return opciones


def _palabras(texto):
    return len([p for p in re.split(r"\s+", str(texto or "")) if p])


def _trozos(texto):
    """El material partido en parrafos. -> [{t_in, t_out, texto}]

    Se parte por LINEA EN BLANCO y no por frase: un parrafo es la unidad que
    escribio una persona, y respetarla es lo que permite que el guionista lea
    «esto va junto» sin que nadie se lo diga.
    """
    crudos = re.split(r"\n\s*\n+", str(texto or "").strip())
    trozos = []
    for crudo in crudos:
        limpio = " ".join(crudo.split())
        if limpio:
            trozos.append({"t_in": 0.0, "t_out": 0.0, "texto": limpio})
    return trozos


# ------------------------------------------------------------------- ejecutar

def ejecutar(proyecto, params, avisar):
    """Deja el material escrito en la forma que leen los pasos de abajo."""
    arranque = time.time()
    opciones = _normalizar(params)
    trabajo = proyecto.ruta_trabajo(PASO)

    avisar(0.1, "leyendo el material")
    texto = opciones["texto"]
    if not texto.strip():
        raise RuntimeError(
            "el material esta vacio: escribe o pega de que va este video. Es "
            "lo unico de lo que salen los hechos del guion, asi que sin el no "
            "hay nada que contar")

    trozos = _trozos(texto)
    palabras = _palabras(texto)

    avisar(0.6, f"{palabras} palabras en {len(trozos)} parrafo(s)")
    metadatos = {
        "titulo": opciones["titulo"],
        "origen": "escrito",
        # LO QUE LEE EL BRIEF: cuantas palabras de material hay. Con esto avisa
        # si el objetivo del video las supera -- de 200 palabras no salen 2.000
        # de guion sin inventarse casi todo.
        "palabras_transcript": palabras,
        # NO hay duracion: esto no se dijo en ningun sitio durante un rato. La
        # clave esta --hay codigo abajo que la lee-- y vale cero, que es la
        # verdad, y no un numero inventado que alguien tomaria por medido.
        "duracion_s": 0,
        "idioma_transcript": opciones["idioma"],
        "sin_tiempos": True,
    }
    resumen = (f"{palabras} palabras de material escrito"
               + (f" · «{opciones['titulo']}»" if opciones["titulo"] else ""))

    # Las cifras van en las salidas como NUMEROS y el material gordo en
    # ficheros: ver la cabecera.
    salidas = {
        "palabras": palabras,
        "parrafos": len(trozos),
        "caracteres": len(texto),
        "sin_tiempos": True,
        "metadatos": metadatos,
        "avisos": [],
        "resumen": resumen,
    }

    avisar(0.9, "escribiendo ingesta.json")
    documento = dict(salidas)
    documento["transcript"] = trozos
    comun.escribir_json(os.path.join(trabajo, "ingesta.json"), documento)
    comun.escribir_json(os.path.join(trabajo, "transcript.json"), {
        "palabras": palabras, "intervenciones": len(trozos),
        "fuente": "escrito", "idioma": "",
        "transcript": trozos,
    })
    # Y EN TEXTO PLANO, que es lo que se abre para comprobar que lo que se pego
    # es lo que se queria pegar. Un JSON con el texto dentro no se lee.
    comun.escribir_texto(os.path.join(trabajo, "material.txt"),
                         "\n\n".join(t["texto"] for t in trozos) + "\n")

    estadisticas.anotar(PASO, time.time() - arranque, tamano=palabras,
                        detalle={"palabras": palabras, "parrafos": len(trozos)})
    avisar(1.0, resumen)
    return salidas
